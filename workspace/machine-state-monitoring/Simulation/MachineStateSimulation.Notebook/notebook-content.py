# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Machine State Monitoring — Test & Simulation
# 
# This notebook provides three tools:
# 1. **Send a single machine state event** — test the MachineEventsStream
# 2. **Send a subscription event** — subscribe/unsubscribe via SubscriptionEventsStream
# 3. **Run a full simulation** — generate events from 1000 machines over time
# 
# **Setup:** Configure the connection strings below, then run the section you need.

# CELL ********************

%pip install azure-eventhub --quiet

# MARKDOWN ********************

# ## Common Configuration

# CELL ********************

import json
import random
import time
from datetime import datetime, timezone
from azure.eventhub import EventHubProducerClient, EventData

# Connection strings from Eventstream Custom Endpoints (set these after deployment)
MACHINE_EVENTS_CONNECTION_STRING = ""   # From MachineEventsStream Custom Endpoint
SUBSCRIPTION_EVENTS_CONNECTION_STRING = ""  # From SubscriptionEventsStream Custom Endpoint

# Valid machine execution states
MACHINE_STATES = [
    "Ready",
    "Stopped",
    "Optional Stop",
    "Program Stopped",
    "Interrupted",
    "Feed Hold",
    "Disabled",
    "Communication Lost",
    "Unavailable",
]

# Valid duration thresholds (minutes)
DURATION_THRESHOLDS = [5, 10, 60, 120, 360, 720, 1440]

def send_event(connection_string, event):
    """Send a single event to an Eventstream Custom Endpoint."""
    producer = EventHubProducerClient.from_connection_string(connection_string)
    with producer:
        batch = producer.create_batch()
        batch.add(EventData(json.dumps(event)))
        producer.send_batch(batch)

# MARKDOWN ********************

# ---
# ## 1. Send a Single Machine State Event
# 
# Configure and run this cell to send one machine state-change event.

# CELL ********************

machine_id = "MACHINE-001"
state = "Stopped"  # Choose from MACHINE_STATES

event = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "machine_id": machine_id,
    "state": state,
}

send_event(MACHINE_EVENTS_CONNECTION_STRING, event)
print(f"✅ Sent machine state event:")
print(json.dumps(event, indent=2))

# MARKDOWN ********************

# ---
# ## 2. Send a Subscription Event
# 
# Configure and run this cell to subscribe or unsubscribe from machine state alerts.

# CELL ********************

user_id = "operator1"
user_email = "operator1@contoso.com"
machine_id = "MACHINE-001"
state = "Stopped"                   # Choose from MACHINE_STATES
duration_threshold_minutes = 10     # Choose from DURATION_THRESHOLDS
action = "subscribe"                # "subscribe" or "unsubscribe"

event = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "user_id": user_id,
    "user_email": user_email,
    "machine_id": machine_id,
    "state": state,
    "duration_threshold_minutes": duration_threshold_minutes,
    "action": action,
}

send_event(SUBSCRIPTION_EVENTS_CONNECTION_STRING, event)
print(f"✅ Sent {action} event:")
print(json.dumps(event, indent=2))

# MARKDOWN ********************

# ---
# ## 3. Run Full Simulation
# 
# Simulates 1000 machines sending state-change events every 10 seconds for 2 hours.
# 
# **Configuration:**
# - `NUM_MACHINES` — number of simulated machines
# - `SIMULATION_DURATION_MINUTES` — how long to run
# - `EVENT_INTERVAL_SECONDS` — seconds between event batches

# CELL ********************

NUM_MACHINES = 1000
SIMULATION_DURATION_MINUTES = 120
EVENT_INTERVAL_SECONDS = 10

# CELL ********************

# Initialize machine fleet
machines = {}
for i in range(1, NUM_MACHINES + 1):
    mid = f"MACHINE-{i:04d}"
    machines[mid] = random.choice(MACHINE_STATES)

print(f"Initialized {NUM_MACHINES} machines.")
for mid, s in list(machines.items())[:5]:
    print(f"  {mid}: {s}")
print(f"  ... and {NUM_MACHINES - 5} more")

# CELL ********************

producer = EventHubProducerClient.from_connection_string(MACHINE_EVENTS_CONNECTION_STRING)
start_time = time.time()
end_time = start_time + (SIMULATION_DURATION_MINUTES * 60)
batch_count = 0

print(f"Starting simulation for {SIMULATION_DURATION_MINUTES} minutes...")
print(f"Sending events every {EVENT_INTERVAL_SECONDS} seconds.\n")

try:
    while time.time() < end_time:
        num_transitions = random.randint(1, min(20, NUM_MACHINES))
        transitioning = random.sample(list(machines.keys()), num_transitions)

        event_batch = producer.create_batch()
        for mid in transitioning:
            old_state = machines[mid]
            new_state = random.choice([s for s in MACHINE_STATES if s != old_state])
            machines[mid] = new_state
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "machine_id": mid,
                "state": new_state,
            }
            event_batch.add(EventData(json.dumps(event)))

        producer.send_batch(event_batch)
        batch_count += 1

        elapsed = int(time.time() - start_time)
        if batch_count % 30 == 0:
            print(f"  [{elapsed}s] Sent {batch_count} batches, last batch: {num_transitions} events")

        time.sleep(EVENT_INTERVAL_SECONDS)

except KeyboardInterrupt:
    print("\nSimulation stopped by user.")
finally:
    producer.close()
    total_elapsed = int(time.time() - start_time)
    print(f"\nSimulation complete. Sent {batch_count} batches over {total_elapsed}s.")
