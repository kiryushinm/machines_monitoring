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

To verify the full pipeline — from event ingestion through to alert delivery — follow these steps:

**1. Get the Event Hub connection strings**

Each Eventstream exposes a Custom Endpoint that accepts Event Hub–compatible messages. In the Fabric portal, open each Eventstream item and copy its connection string:

- **MachineEventsStream** — receives machine state-change events
- **SubscriptionEventsStream** — receives subscription events

**2. Send a subscription event**

Publish a JSON message to the **SubscriptionEventsStream** endpoint to create an alert subscription. For example:

```json
{
  "timestamp": "2026-03-30T22:00:00Z",
  "user_id": "user1",
  "user_email": "user1@contoso.com",
  "machine_id": "machine-42",
  "state": "Stopped",
  "duration_threshold_minutes": 5,
  "action": "subscribe"
}
```

This subscribes `user1` to be alerted when `machine-42` remains in the `Stopped` state for more than 5 minutes.

**3. Send a machine state event**

Publish a JSON message to the **MachineEventsStream** endpoint simulating the machine entering the subscribed state:

```json
{
  "timestamp": "2026-03-30T22:01:00Z",
  "machine_id": "machine-42",
  "state": "Stopped"
}
```

**4. Wait for the alert**

The Activator polls the Eventhouse every 60 seconds. Once the machine has been in the `Stopped` state for longer than the configured duration (5 minutes in this example), the `is_breached` flag transitions to `true` and an email alert is sent to `user1@contoso.com`.

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
- Poll the Eventhouse KQL database every 60 seconds
- Fire when `is_breached` changes to `1` for any subscription
- Send Email notifications to the subscribed user's email address with machine_id, state, and duration details
