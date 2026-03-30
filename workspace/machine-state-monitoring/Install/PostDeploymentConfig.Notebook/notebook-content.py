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

# ## 2. Patch KQL QuerySet with real database connection
# 
# The KQL QuerySet definition ships with placeholder IDs.
# This step resolves the real KQL Database item ID and cluster URI,
# then updates the QuerySet definition so it connects to the deployed Eventhouse.

# CELL ********************

import json, base64, time

queryset_name = "SubscriptionsMonitoringKQL"

# Find the KQL QuerySet item in the workspace
items_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=KQLQueryset")
items_resp.raise_for_status()
queryset_item = next(
    (i for i in items_resp.json()["value"] if i["displayName"] == queryset_name),
    None,
)

# Find the KQL Database item in the workspace
db_items_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=KQLDatabase")
db_items_resp.raise_for_status()
db_item = next(
    (i for i in db_items_resp.json()["value"] if i["displayName"] == kql_db_name),
    None,
)

if not queryset_item:
    print(f"⚠️ KQL QuerySet '{queryset_name}' not found — skipping patch")
elif not db_item:
    print(f"⚠️ KQL Database '{kql_db_name}' not found — skipping patch")
else:
    queryset_id = queryset_item["id"]
    db_id = db_item["id"]
    print(f"KQL QuerySet ID: {queryset_id}")
    print(f"KQL Database ID: {db_id}")

    # Get current QuerySet definition
    def_resp = client.post(
        f"/v1/workspaces/{workspace_id}/items/{queryset_id}/getDefinition"
    )
    def_resp.raise_for_status()
    definition = def_resp.json()["definition"]

    # Find and patch the RealTimeQueryset.json part
    for part in definition["parts"]:
        if part["path"] == "RealTimeQueryset.json":
            content = json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
            for ds in content.get("queryset", {}).get("dataSources", []):
                ds["databaseItemId"] = db_id
                ds["clusterUri"] = kusto_query_uri
            part["payload"] = base64.b64encode(
                json.dumps(content, indent=2).encode("utf-8")
            ).decode("utf-8")
            break

    # Update the QuerySet definition
    update_body = {"definition": definition}
    update_resp = client.post(
        f"/v1/workspaces/{workspace_id}/items/{queryset_id}/updateDefinition",
        json=update_body,
    )
    update_resp.raise_for_status()
    print(f"✅ KQL QuerySet patched — now connected to database '{kql_db_name}'")

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
