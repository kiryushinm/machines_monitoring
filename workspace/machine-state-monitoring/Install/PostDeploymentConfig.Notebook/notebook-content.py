# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Post-Deployment Configuration
# 
# Run this notebook after the Solution Installer has deployed all Fabric items.
# It performs the following tasks:
# 1. Validates Eventhouse connectivity
# 2. Seeds sample subscription data for demo purposes

# CELL ********************

import sempy.fabric as fabric

client = fabric.FabricRestClient()
workspace_id = fabric.get_workspace_id()

print(f"Workspace ID: {workspace_id}")
print("Post-deployment configuration starting...")

# MARKDOWN ********************

# ## 1. Validate Eventhouse Connectivity

# CELL ********************

from fabric_launcher.post_deployment_utils import (
    get_kusto_query_uri,
    exec_kql_command,
)

eventhouse_name = "MachineMonitoringEH"
kql_db_name = "MachineMonitoringEH"

kusto_query_uri = get_kusto_query_uri(workspace_id, eventhouse_name, client)
print(f"Eventhouse query URI: {kusto_query_uri}")

# Verify tables exist
result = exec_kql_command(
    kusto_query_uri,
    kql_db_name,
    ".show tables | project TableName",
    notebookutils,
)
print("Tables found:")
print(result)

# MARKDOWN ********************

# ## 2. Seed Sample Subscription Data
# 
# Inserts a few sample subscriptions so the Activator has data to work with
# during a demo. These can be removed later.

# CELL ********************

import json
from datetime import datetime, timezone

sample_subscriptions = [
    {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": "demo-operator-1",
        "user_email": "operator1@contoso.com",
        "machine_id": "MACHINE-0001",
        "state": "Stopped",
        "duration_threshold_minutes": 10,
        "action": "subscribe",
    },
    {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": "demo-operator-1",
        "user_email": "operator1@contoso.com",
        "machine_id": "MACHINE-0002",
        "state": "Communication Lost",
        "duration_threshold_minutes": 5,
        "action": "subscribe",
    },
    {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": "demo-operator-2",
        "user_email": "operator2@contoso.com",
        "machine_id": "MACHINE-0005",
        "state": "Interrupted",
        "duration_threshold_minutes": 60,
        "action": "subscribe",
    },
]

# Ingest sample subscriptions into UserSubscriptions table
ingest_commands = []
for sub in sample_subscriptions:
    cols = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in [
        sub["timestamp"], sub["user_id"], sub["user_email"],
        sub["machine_id"], sub["state"], sub["duration_threshold_minutes"],
        sub["action"],
    ])
    ingest_commands.append(
        f".ingest inline into table UserSubscriptions <| {cols}"
    )

for cmd in ingest_commands:
    try:
        exec_kql_command(kusto_query_uri, kql_db_name, cmd, notebookutils)
    except Exception as e:
        print(f"Warning: {e}")

print(f"Seeded {len(sample_subscriptions)} sample subscriptions.")

# MARKDOWN ********************

# ## Done
# 
# Post-deployment configuration is complete.
# 
# **Next steps:**
# 1. Open the **MachineStateSimulation** notebook and run it to start generating events
# 2. Check the **MachineMonitoringEH** Eventhouse to verify data is flowing
# 3. Monitor the **MachineStateActivator** for triggered alerts

# CELL ********************

print("✅ Post-deployment configuration complete!")
