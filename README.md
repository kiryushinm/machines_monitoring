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
3. **Eventstreams → Eventhouse** — Both streams land in their respective KQL tables.
4. **Activator → Eventhouse** — Polls a KQL query every 5 minutes to detect threshold breaches.
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

Polls every 5 minutes. Each subscription is tracked as a distinct object via a compound `subscription_key`.

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
| **Condition**  | **Becomes** — monitors `is_breached`, fires only on the false → true transition per object |
| **Action**     | Send Teams or Email notification to `user_email`                      |

The **Becomes** condition ensures each subscription is alerted only once when the threshold is first crossed. If the machine later leaves the state and re-enters it, the condition resets and a new alert fires.

## Prerequisites

- **Microsoft Fabric Capacity**: F16 or higher recommended
- **Fabric Workspace**: A workspace with contributor or admin permissions
- Familiarity with Microsoft Fabric concepts (Eventhouses, Eventstreams) is helpful but not required

## Installation Instructions

### Step 1: Prepare Workspace

1. Log in to [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Use an existing workspace or create a new one (e.g., "Machine State Monitoring")
3. Ensure a Fabric capacity is assigned

### Step 2: Install the Solution

1. In your Fabric workspace, click **+ New** → **Notebook**
2. Add the following code to two separate cells:

```python
%pip install fabric-launcher --quiet
import notebookutils
notebookutils.session.restartPython()
```

```python
from fabric_launcher import FabricLauncher

launcher = FabricLauncher(notebookutils)
launcher.download_and_deploy(
    repo_owner="makiryus_microsoft",
    repo_name="machines_state_monitoring",
    branch="main",
    workspace_folder="workspace",
    allow_non_empty_workspace=True,
    item_type_stages=[
        ["KQLDatabase", "Eventhouse"],
        ["Notebook", "Eventstream", "Reflex"]
    ],
    validate_after_deployment=True,
    generate_report=True
)
```

3. Run the notebook — it will deploy all items and run the PostDeploymentConfig notebook automatically

## Usage Instructions

### Running the Machine State Simulation

```
Location: Simulation / MachineStateSimulation
Duration: 2 hours (configurable)
Data Generated: State-change events for 1000 machines every 10 seconds
```

1. Open the **MachineStateSimulation** notebook
2. Set the `EVENT_HUB_CONNECTION_STRING` to the connection string from the **MachineEventsStream** Custom Endpoint (found in the Fabric portal under the Eventstream item)
3. Click **Run all**
4. Monitor progress in the output — status is printed every 5 minutes

**Valid machine states**: Ready, Stopped, Optional Stop, Program Stopped, Interrupted, Feed Hold, Disabled, Communication Lost, Unavailable

### Verifying Data Flow

1. Navigate to **StoreAndQuery** → **MachineMonitoringEH** (Eventhouse)
2. Open the KQL Database and run:

```kql
MachineStateEvents | take 10
```

3. Verify events are arriving with `timestamp`, `machine_id`, and `state` columns

### Using the Activator

The **MachineStateActivator** monitors all active subscriptions and sends alerts when machines exceed configured duration thresholds.

Access: Navigate to **Act** → **MachineStateActivator**

The Activator is pre-configured to:
- Poll every 5 minutes
- Fire when `is_breached` transitions from `false` to `true` for any subscription
- Send Email notifications to the subscribed user's email address
