# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Machine State Simulation
# 
# Generates synthetic machine state-change events and sends them to the
# **MachineEventsStream** Eventstream Custom Endpoint.
# 
# **Configuration:**
# - `NUM_MACHINES` — number of simulated machines (default: 1000)
# - `SIMULATION_DURATION_MINUTES` — how long to run (default: 120)
# - `EVENT_INTERVAL_SECONDS` — seconds between event batches (default: 10)

# CELL ********************

%pip install azure-eventhub --quiet

# CELL ********************

# Configuration
NUM_MACHINES = 1000
SIMULATION_DURATION_MINUTES = 120
EVENT_INTERVAL_SECONDS = 10

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

# MARKDOWN ********************

# ## Initialize Event Hub Connection
# 
# The Eventstream Custom Endpoint exposes an Event Hub-compatible connection string.
# Replace `EVENT_HUB_CONNECTION_STRING` with the connection string from your
# MachineEventsStream Custom Endpoint.

# CELL ********************

import json
import random
import time
from datetime import datetime, timezone

from azure.eventhub import EventHubProducerClient, EventData

# Retrieve the connection string from the Eventstream Custom Endpoint
# Set this after deployment — see PostDeploymentConfig notebook
EVENT_HUB_CONNECTION_STRING = ""  # e.g. "Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...;EntityPath=..."

if not EVENT_HUB_CONNECTION_STRING:
    raise ValueError(
        "EVENT_HUB_CONNECTION_STRING is not set. "
        "Copy the connection string from the MachineEventsStream Custom Endpoint in the Fabric portal."
    )

producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONNECTION_STRING)
print("Connected to MachineEventsStream Custom Endpoint.")

# MARKDOWN ********************

# ## Initialize Machine Fleet

# CELL ********************

# Create machine fleet with initial states
machines = {}
for i in range(1, NUM_MACHINES + 1):
    machine_id = f"MACHINE-{i:04d}"
    machines[machine_id] = random.choice(MACHINE_STATES)

print(f"Initialized {NUM_MACHINES} machines.")
for mid, state in list(machines.items())[:5]:
    print(f"  {mid}: {state}")
print(f"  ... and {NUM_MACHINES - 5} more")

# MARKDOWN ********************

# ## Run Simulation Loop
# 
# Each iteration:
# 1. Randomly selects a subset of machines to transition
# 2. Assigns them new states
# 3. Sends events to the Eventstream

# CELL ********************

start_time = time.time()
end_time = start_time + (SIMULATION_DURATION_MINUTES * 60)
batch_count = 0

print(f"Starting simulation for {SIMULATION_DURATION_MINUTES} minutes...")
print(f"Sending events every {EVENT_INTERVAL_SECONDS} seconds.\n")

try:
    while time.time() < end_time:
        # Randomly pick 1-20 machines to transition
        num_transitions = random.randint(1, min(20, NUM_MACHINES))
        transitioning = random.sample(list(machines.keys()), num_transitions)

        event_batch = producer.create_batch()

        for machine_id in transitioning:
            old_state = machines[machine_id]
            # Pick a new state different from current
            new_state = random.choice([s for s in MACHINE_STATES if s != old_state])
            machines[machine_id] = new_state

            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "machine_id": machine_id,
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
