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
└──────────┘    └─────────────┘    │  SubscriptionsState        │
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
3. **Eventstreams → Eventhouse** — Both streams use Direct Ingestion mode to land data in their respective KQL tables.
4. **Activator → Eventhouse** — Polls a KQL query every 60 seconds to detect threshold breaches.
5. **Activator → Teams / Email** — Sends notifications to subscribed users.

## Eventhouse Schema

### Table: `MachineStateEvents`

Raw telemetry from the machine fleet.

| Column       | Type     | Description                |
|--------------|----------|----------------------------|
| `timestamp`  | datetime | Timestamp of event         |
| `machine_id` | string   | Machine identifier         |
| `state`      | string | One of: Ready, Stopped, Optional Stop, Program Stopped, Interrupted, Feed Hold, Disabled, Communication Lost, Unavailable |

### Table: `UserSubscriptions`

Every subscription change is a new row. The latest event per (user, machine, state) determines current state.

| Column             | Type     | Description                              |
|--------------------|----------|------------------------------------------|
| `timestamp`        | datetime | When the change occurred                 |
| `user_id`          | string   | User who made the change                 |
| `user_email`       | string   | Notification target                      |
| `machine_id`       | string   | Target machine                           |
| `state`            | string   | Target execution state                   |
| `duration_threshold_minutes` | int      | Threshold (5, 10, 60, 120, 360, 720, 1440) |
| `action`           | string   | `"subscribe"` or `"unsubscribe"`         |

### Materialized View: `SubscriptionsState`

Maintains the latest subscription event per subscription key (user, machine, state). The `where action == "subscribe"` filter is applied at query time (in the Activator query) rather than in the view itself.

```kql
.create-or-alter materialized-view SubscriptionsState on table UserSubscriptions {
    UserSubscriptions
    | summarize arg_max(timestamp, action, duration_threshold_minutes, user_email, user_id, machine_id, state) by subscription_key = strcat(user_id, '|', machine_id, '|', state)
}
```

## Activator

### Trigger Query

Polls every 60 seconds. Each subscription is tracked as a distinct object via a compound `subscription_key`.

The Activator uses a **Becomes** condition on the `is_breached` column, which fires only when the value transitions from `false` to `true` for a given `subscription_key`. This means:
- An alert fires **once** when a machine first exceeds the subscribed duration threshold.
- While the machine remains in the same state, `is_breached` stays `true` — no repeated alerts.
- When the machine changes state, `is_breached` flips to `false`, resetting the condition so a new alert can fire if the threshold is crossed again.

For this to work, the query must return a row for **every active subscription on every poll** (not just the breached ones), so the Activator always has an explicit `true` or `false` signal per object. The query achieves this as follows:

1. **`machine_states`** — Computes the latest state and how long each machine has been in it. Uses `arg_max(timestamp, state)` to pick the most recent event per `machine_id`, then calculates `duration_min` as the minutes elapsed since that event.

2. **`leftouter` join** — Starts from `SubscriptionsState` (left side) and joins `machine_states` on `machine_id` only (not on state). This ensures **every active subscription produces a row on every poll**, even if the machine's current state doesn't match the subscribed state. The `is_breached` flag is then computed by comparing the subscribed `state` against `current_state` and checking the duration threshold. This guarantees the Activator receives explicit `true → false` transitions when a machine leaves a subscribed state, properly resetting the **Becomes** condition.

```kql
let machine_states = MachineStateEvents
    | summarize arg_max(timestamp, state) by machine_id
    | extend duration_min = datetime_diff('minute', now(), timestamp)
    | project machine_id, current_state = state, duration_min;
SubscriptionsState
| where action == "subscribe"
| join kind=leftouter machine_states on machine_id
| extend is_breached = (current_state == state and duration_min >= duration_threshold_minutes)
| project subscription_key, machine_id, state, current_state, duration_min, user_email, duration_threshold_minutes, is_breached
```

### Trigger Configuration

| Setting        | Value                                                                 |
|----------------|-----------------------------------------------------------------------|
| **Object ID**  | `subscription_key` — compound key of `user_id`, `machine_id`, `state` |
| **Condition**  | **ChangesTo 1** — monitors `is_breached` (Number), fires when the value changes to `1` per object |
| **Action**     | Send Email notification to `user_email` with `machine_id`, `state`, `duration_min`, `duration_threshold_minutes` |

The **ChangesTo** condition ensures each subscription is alerted only once when the threshold is first crossed. If the machine later leaves the state and re-enters it, the condition resets and a new alert fires.

## Prerequisites

- **Microsoft Fabric Capacity**: F2 or higher
- **Fabric Workspace**: A workspace with contributor or admin permissions
- Familiarity with Microsoft Fabric concepts (Eventhouses, Eventstreams) is helpful but not required

## Installation Instructions

### Step 1: Prepare Workspace

1. Log in to [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Use an existing workspace or create a new one (e.g., "Machine State Monitoring")
3. Ensure a Fabric capacity is assigned

### Step 2: Install the Solution

1. In your Fabric workspace, click **+ New** → **Notebook**
2. Add the following code to three separate cells:

**Cell 1** — Install dependencies and restart Python:
```python
%pip install fabric-launcher --quiet
import notebookutils
notebookutils.session.restartPython()
```

**Cell 2** — Deploy all Fabric items (for private repos, add `github_token` parameter):
```python
from fabric_launcher import FabricLauncher

launcher = FabricLauncher(
    notebookutils,
    api_root_url="https://api.fabric.microsoft.com"
)

launcher.download_and_deploy(
    repo_owner="makiryus_microsoft",
    repo_name="machines_state_monitoring",
    branch="main",
    workspace_folder="workspace",
    allow_non_empty_workspace=True,
    item_type_stages=[
        ["KQLDatabase", "Eventhouse"],
        ["Notebook", "Eventstream", "KQLQueryset"]
    ],
    validate_after_deployment=True,
    generate_report=True,
    github_token="<YOUR_GITHUB_PAT>"  # Required for private repos; remove for public repos
)
```

3. Run Cell 1 first, wait for the Python session to restart, then run Cell 2
4. If the Eventhouse shows a "not available yet" error, wait 2–3 minutes and re-run Cell 2

### Step 3: Run the Post-Deployment Configuration

After all Fabric items are deployed, open the **PostDeploymentConfig** notebook (located in the **Install** folder) and run all cells sequentially. This notebook:

1. **Patches the KQL QuerySet** — resolves the real KQL Database item ID and cluster URI, then updates the QuerySet definition so it connects to the deployed Eventhouse
2. **Creates the Activator** — builds the MachineStateActivator (Reflex) via API with the correct workspace-specific IDs and moves it to the **Act** folder

## Usage Instructions

### Testing End-to-End Alerting

Open the **MachineStateSimulation** notebook (located in the **Simulation** folder). Paste the Event Hub connection strings from each Eventstream's Custom Endpoint into the configuration cell:

- `MACHINE_EVENTS_CONNECTION_STRING` — from **MachineEventsStream**
- `SUBSCRIPTION_EVENTS_CONNECTION_STRING` — from **SubscriptionEventsStream**

To find a connection string: open the Eventstream item in the Fabric portal, select the Custom Endpoint source, and copy the connection string.

Once configured, run the notebook cells to test the full pipeline:

1. **Send a subscription event** — run the subscription cell to create an alert subscription for a specific machine, state, user, and duration threshold
2. **Send a machine state event** — run the machine event cell to simulate the subscribed machine entering that state
3. **Wait for the alert** — the Activator polls the Eventhouse every 60 seconds. Once the machine has remained in the subscribed state beyond the configured duration, an email alert is sent to the subscribed user

The **MachineStateActivator** monitors all active subscriptions and sends alerts when machines exceed configured duration thresholds.

Access: Navigate to **Act** → **MachineStateActivator**

The Activator is pre-configured to:
- Poll the Eventhouse KQL database every 60 seconds
- Fire when `is_breached` changes to `1` for any subscription
- Send Email notifications to the subscribed user's email address with machine_id, state, and duration details

### Running the Bulk Simulation

The same notebook also contains a bulk simulation cell that generates state-change events for 1,000 machines every 10 seconds over a configurable duration (default: 2 hours). Run this cell to load-test the pipeline.

## Extending the Solution: Alert Acknowledgement & Escalation

This section describes how the existing implementation can be extended to support alert acknowledgement tracking and automatic escalation when alerts are not acknowledged within a configured time window.

### Requirements

1. **Alert record storage** — When the Activator fires an alert (email, Teams message), store a record of it.
2. **Acknowledgement tracking** — Employees acknowledge alerts through a custom Teams UI (e.g., a button click). The acknowledgement is recorded against the original alert.
3. **Automatic escalation** — If an acknowledgement is not received within 60 minutes of the breach starting, re-send the alert to a manager, VP, or other escalation contacts.

### Design Approach

The key insight is that the breach start time does not need to be tracked via state transitions on the `is_breached` column. It is **deterministic** from existing data:

```
breach_started_at = state_entered_at + duration_threshold_minutes
```

- `state_entered_at` is the timestamp of the most recent state-change event for the machine (already computed via `arg_max(timestamp, state)` on `MachineStateEvents`).
- `duration_threshold_minutes` is the threshold configured in the subscription.

This means the escalation query can compute breach timing purely from existing tables, join with a new acknowledgements table, and check whether 60 minutes have elapsed — all without persisting `is_breached` history.

### Architecture

```
                                    ┌────────────────────────────────┐
                                    │ Eventhouse (KQL DB)            │
                                    │                                │
                                    │  MachineStateEvents     (existing) │
                                    │  UserSubscriptions      (existing) │
                                    │  SubscriptionsState     (existing) │
                                    │                                │
┌──────────┐    ┌─────────────┐     │  Acknowledgements       (NEW)  │
│ Teams UI │──▶│ Eventstream │──▶  │  EscalationConfig       (NEW)  │
│ (ack btn)│    │ (acks)      │     │                                │
└──────────┘    └─────────────┘     └──────────────┬─────────────────┘
                                                   │ KQL poll
                                    ┌──────────────▼─────────────────┐
                                    │  EscalationActivator     (NEW) │
                                    │  (unacked breach alerts)       │
                                    └──────────────┬─────────────────┘
                                                   ▼
                                            Manager / VP alert
```

### New Eventhouse Schema

#### Table: `Acknowledgements`

Records acknowledgement events sent from the Teams custom UI.

| Column             | Type     | Description                                      |
|--------------------|----------|--------------------------------------------------|
| `subscription_key` | string   | Matches the subscription that triggered the alert |
| `ack_at`           | datetime | When the user acknowledged the alert             |

A `subscription_key` uniquely identifies a subscription (`user_id|machine_id|state`). When an alert fires for a given `subscription_key`, the employee clicks the acknowledge button in Teams, which posts an event containing the `subscription_key` and current timestamp. This event is ingested into the `Acknowledgements` table via a new Eventstream with a Custom Endpoint.

Because `is_breached` resets whenever the machine changes state, each breach cycle is implicitly scoped to the machine's current state stint. An acknowledgement for a previous breach does not suppress future alerts — once the machine leaves and re-enters the monitored state, a new breach cycle begins with no prior acknowledgement.

#### Table: `EscalationConfig`

Stores the escalation chain per user or subscription.

| Column             | Type    | Description                                                  |
|--------------------|---------|--------------------------------------------------------------|
| `user_id`          | string  | The employee whose alerts may be escalated                   |
| `escalation_contacts` | dynamic | Ordered JSON array of escalation contacts, e.g., `["manager@co.com", "vp@co.com"]` |

Alternatively, escalation contacts can be added as a new column on the `UserSubscriptions` table if escalation chains vary per subscription rather than per user.

### Escalation Activator

A second Activator (`EscalationActivator`) polls the Eventhouse every 60 seconds with the following query:

```kql
let machine_states = MachineStateEvents
    | summarize arg_max(timestamp, state) by machine_id
    | project machine_id, current_state = state, state_entered_at = timestamp;
let active_breaches = SubscriptionsState
    | where action == "subscribe"
    | join kind=inner machine_states on machine_id
    | where current_state == state
    | extend breach_started_at = state_entered_at + duration_threshold_minutes * 1m
    | where now() >= breach_started_at;
let unacked_breaches = active_breaches
    | join kind=leftanti Acknowledgements on subscription_key;
let with_escalation = unacked_breaches
    | join kind=leftouter EscalationConfig on user_id;
with_escalation
| extend minutes_since_breach = datetime_diff('minute', now(), breach_started_at)
| extend needs_escalation = (minutes_since_breach >= 60)
| project subscription_key, machine_id, state, user_email,
         breach_started_at, minutes_since_breach,
         escalation_contacts, needs_escalation
```

#### How the Query Works

1. **`machine_states`** — Same as the existing Activator query: computes the latest state and when each machine entered it.
2. **`active_breaches`** — Joins active subscriptions with machine states, computes `breach_started_at` as `state_entered_at + duration_threshold_minutes`, and filters to currently breached subscriptions.
3. **`unacked_breaches`** — Uses a `leftanti` join against `Acknowledgements` to keep only breaches that have not been acknowledged. When an employee clicks the acknowledge button, their `subscription_key` appears in the `Acknowledgements` table, and the `leftanti` join removes it from the escalation pipeline.
4. **`with_escalation`** — Joins escalation contact configuration so the Activator knows who to notify.
5. **Final projection** — Computes `minutes_since_breach` and a boolean `needs_escalation` flag.

#### Trigger Configuration

| Setting        | Value                                                                 |
|----------------|-----------------------------------------------------------------------|
| **Object ID**  | `subscription_key`                                                    |
| **Condition**  | **ChangesTo 1** — monitors `needs_escalation`, fires when the value changes to `1` per object |
| **Action**     | Send Email / Teams notification to `escalation_contacts` with `machine_id`, `state`, `minutes_since_breach` |

The **ChangesTo** condition works the same way as the existing Activator: it fires once when `needs_escalation` transitions from `false` to `true` for a given `subscription_key`. The condition resets when the machine changes state (breach disappears) or when the employee acknowledges (row removed by `leftanti` join).

### New Fabric Items Summary

| Item                      | Type         | Purpose                                              |
|---------------------------|--------------|-------------------------------------------------------|
| `Acknowledgements`        | KQL Table    | Stores acknowledgement events from the Teams UI       |
| `EscalationConfig`        | KQL Table    | Escalation contact chain per user                     |
| `AcknowledgementStream`   | Eventstream  | Ingests acknowledgement button clicks via Custom Endpoint |
| `EscalationActivator`     | Activator    | Polls for unacknowledged breaches and escalates       |

### Multi-Level Escalation

For multi-level escalation (e.g., manager at 60 min, VP at 120 min, director at 180 min), the query can be extended to compute the current escalation tier:

```kql
| extend escalation_tier = case(
    minutes_since_breach >= 180, 2,  // director
    minutes_since_breach >= 120, 1,  // VP
    minutes_since_breach >= 60,  0,  // manager
    -1)                              // no escalation
| where escalation_tier >= 0
| extend escalation_target = escalation_contacts[escalation_tier]
| extend needs_escalation = true
```

Using `escalation_tier` as part of the Activator object ID (e.g., `strcat(subscription_key, '|', escalation_tier)`) ensures each escalation level triggers independently via the **ChangesTo** condition.

