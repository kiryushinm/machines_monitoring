# Machine Fleet State Monitoring — Fabric RTI Architecture

## Overview

A real-time alerting solution built on Fabric Real-Time Intelligence that notifies users when machines remain in a specific state beyond a configured duration threshold.

## Scenario

1. A fleet of machines sends events whenever a machine's state changes. Each event contains a timestamp, machine ID, and the new state.

2. Machine operators can subscribe to execution status of individual machines through a portal where they can:
   - Specify a list of machine IDs they are interested in
   - Select execution states to monitor, each with a duration chosen from a predefined list

   The operator is notified whenever a machine enters and then remains in the selected state beyond the configured duration.

3. Machine operators can unsubscribe from previously created alerts.

### Components

```
┌──────────┐    ┌─────────────┐    ┌────────────────────────────┐
│ Machine  │──▶│ Eventstream │──▶ │ Eventhouse (KQL DB)        │
│ Fleet    │    │ (events)    │    │                            │
└──────────┘    └─────────────┘    │  MachineStateEvents (raw)  │
                                   │                            │
┌──────────┐    ┌─────────────┐    │  UserSubscriptions         │
│ Portal   │──▶│ Eventstream │──▶ │                            │
│ (Web UI) │    │ (subs)      │    │                            │
└──────────┘    └─────────────┘    │  ActiveSubscriptions       │
                                   │    (materialized view)     │
                                   └─────────────┬──────────────┘
                                                 │ KQL poll
                                   ┌─────────────▼──────────────┐
                                   │  Activator                 │
                                   │  (threshold breach alerts) │
                                   └─────────────┬──────────────┘
                                                 ▼
                                          Teams / Email
```

## Data Flow

1. **Machine Fleet → Eventstream (events)** — Machines emit state-change events (timestamp, machine_id, state) ingested via Custom Endpoint or Event Hub.
2. **Portal → Eventstream (subs)** — Users manage alert subscriptions through a web portal; each change is appended as an event.
3. **Eventstreams → Eventhouse** — Both streams land in their respective KQL tables.
4. **Activator → Eventhouse** — Polls a KQL query every 5 minutes to detect threshold breaches.
5. **Activator → Teams / Email** — Sends notifications to subscribed users.

## Eventhouse Schema

### Table: `MachineStateEvents`

Raw telemetry from the machine fleet.

| Column       | Type   | Description                |
|--------------|--------|----------------------------|
| `timestamp`  | long   | Epoch timestamp of event   |
| `machine_id` | guid   | Machine identifier         |
| `state`      | string | One of: Ready, Stopped, Optional Stop, Program Stopped, Interrupted, Feed Hold, Disabled, Communication Lost, Unavailable |

### Table: `UserSubscriptions`

Every subscription change is a new row. The latest event per (user, machine, state) determines current state.

| Column             | Type     | Description                              |
|--------------------|----------|------------------------------------------|
| `timestamp`        | datetime | When the change occurred                 |
| `user_id`          | string   | User who made the change                 |
| `user_email`       | string   | Notification target                      |
| `machine_id`       | guid     | Target machine                           |
| `state`            | string   | Target execution state                   |
| `duration_threshold_minutes` | int      | Threshold (5, 10, 60, 120, 360, 720, 1440) |
| `action`           | string   | `"subscribe"` or `"unsubscribe"`         |

### Materialized View: `ActiveSubscriptions`

Maintains the current set of active subscriptions by resolving the latest event per subscription key (user, machine, state)

```kql
.create materialized-view ActiveSubscriptions on table UserSubscriptions {
    UserSubscriptions
    | extend subscription_key = strcat(user_id, '|', machine_id, '|', state)
    | summarize arg_max(timestamp, action, duration_threshold_minutes, user_email, user_id, machine_id, state) by subscription_key
    | where action == "subscribe"
}
```

## Activator

### Trigger Query

Polls every 5 minutes. Each subscription is tracked as a distinct object via a compound `subscription_key`.

The Activator uses a **Becomes** condition on the `is_breached` column, which fires only when the value transitions from `false` to `true` for a given `subscription_key`. This means:
- An alert fires **once** when a machine first exceeds the subscribed duration threshold.
- While the machine remains in the same state, `is_breached` stays `true` — no repeated alerts.
- When the machine changes state, `is_breached` flips to `false`, resetting the condition so a new alert can fire if the threshold is crossed again.

For this to work, the query must return a row for **every active subscription on every poll** (not just the breached ones), so the Activator always has an explicit `true` or `false` signal per object. The query achieves this as follows:

1. **`machine_states`** — Computes the latest state and how long each machine has been in it. Uses `arg_max(timestamp, state)` to pick the most recent event per `machine_id`, then calculates `duration_min` as the time elapsed since that event.

2. **`leftouter` join** — Starts from `ActiveSubscriptions` (left side) and joins `machine_states` on `machine_id` only (not on state). This ensures **every active subscription produces a row on every poll**, even if the machine's current state doesn't match the subscribed state. The `is_breached` flag is then computed by comparing the subscribed `state` against `current_state` and checking the duration threshold. This guarantees the Activator receives explicit `true → false` transitions when a machine leaves a subscribed state, properly resetting the **Becomes** condition.

```kql
let now_ts = tolong(datetime_diff('Millisecond', now(), datetime(1970-01-01)));
let machine_states = MachineStateEvents
    | summarize arg_max(timestamp, state) by machine_id
    | extend duration_min = (now_ts - timestamp) / 60000
    | project machine_id, current_state = state, duration_min;
ActiveSubscriptions
| join kind=leftouter machine_states on machine_id
| extend is_breached = (current_state == state and duration_min >= duration_threshold_minutes)
| project subscription_key, machine_id, state, current_state, duration_min, user_email, duration_threshold_minutes, is_breached
```

### Trigger Configuration

| Setting        | Value                                                                 |
|----------------|-----------------------------------------------------------------------|
| **Object ID**  | `subscription_key` — compound key of `user_id`, `machine_id`, `state` |
| **Condition**  | **Becomes** — monitors `is_breached`, fires only on the false → true transition per object |
| **Action**     | Send Teams or Email notification to `user_email`                      |

The **Becomes** condition ensures each subscription is alerted only once when the threshold is first crossed. If the machine later leaves the state and re-enters it, the condition resets and a new alert fires.
