# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Send Subscription Event
# 
# Sends a **subscribe** or **unsubscribe** event to the
# **SubscriptionEventsStream** Custom Endpoint.
# 
# **Steps:**
# 1. Configure the parameters below
# 2. Set `EVENT_HUB_CONNECTION_STRING` to the connection string from the
#    SubscriptionEventsStream Custom Endpoint
# 3. Run all cells

# CELL ********************

%pip install azure-eventhub --quiet

# CELL ********************

# === CONFIGURATION ===
# Set the connection string from SubscriptionEventsStream Custom Endpoint
EVENT_HUB_CONNECTION_STRING = "<PASTE_CONNECTION_STRING_HERE>"

# Subscription parameters
user_id = "operator1"
user_email = "operator1@contoso.com"
machine_id = "MACHINE-001"
state = "Stopped"                   # Ready, Stopped, Optional Stop, Program Stopped, Interrupted, Feed Hold, Disabled, Communication Lost, Unavailable
duration_threshold_minutes = 10     # 5, 10, 60, 120, 360, 720, 1440
action = "subscribe"                # "subscribe" or "unsubscribe"

# CELL ********************

import json
from datetime import datetime, timezone
from azure.eventhub import EventHubProducerClient, EventData

event = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "user_id": user_id,
    "user_email": user_email,
    "machine_id": machine_id,
    "state": state,
    "duration_threshold_minutes": duration_threshold_minutes,
    "action": action,
}

producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONNECTION_STRING)

with producer:
    batch = producer.create_batch()
    batch.add(EventData(json.dumps(event)))
    producer.send_batch(batch)

print(f"✅ Sent {action} event:")
print(json.dumps(event, indent=2))
