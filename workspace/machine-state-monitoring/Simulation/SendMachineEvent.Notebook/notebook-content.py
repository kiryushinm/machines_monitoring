# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Send Machine State Event
# 
# Sends a single machine state-change event to the
# **MachineEventsStream** Custom Endpoint.
# 
# **Steps:**
# 1. Configure the parameters below
# 2. Set `EVENT_HUB_CONNECTION_STRING` to the connection string from the
#    MachineEventsStream Custom Endpoint
# 3. Run all cells

# CELL ********************

%pip install azure-eventhub --quiet

# CELL ********************

# === CONFIGURATION ===
# Set the connection string from MachineEventsStream Custom Endpoint
EVENT_HUB_CONNECTION_STRING = "<PASTE_CONNECTION_STRING_HERE>"

# Event parameters
machine_id = "MACHINE-001"
state = "Stopped"  # Ready, Stopped, Optional Stop, Program Stopped, Interrupted, Feed Hold, Disabled, Communication Lost, Unavailable

# CELL ********************

import json
from datetime import datetime, timezone
from azure.eventhub import EventHubProducerClient, EventData

event = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "machine_id": machine_id,
    "state": state,
}

producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONNECTION_STRING)

with producer:
    batch = producer.create_batch()
    batch.add(EventData(json.dumps(event)))
    producer.send_batch(batch)

print(f"✅ Sent machine state event:")
print(json.dumps(event, indent=2))
