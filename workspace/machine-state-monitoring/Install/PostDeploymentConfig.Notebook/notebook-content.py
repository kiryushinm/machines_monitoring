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
# It validates Eventhouse connectivity.

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
