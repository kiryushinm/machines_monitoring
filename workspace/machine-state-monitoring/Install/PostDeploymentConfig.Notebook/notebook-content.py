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

%pip install fabric-launcher --quiet

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

# ## 3. Patch Activator with real database and QuerySet IDs
# 
# The Activator (Reflex) definition ships with placeholder IDs for the
# KQL Database and QuerySet. This step resolves the real IDs and patches
# the Activator definition so it points to the deployed items.

# CELL ********************

activator_name = "MachineStateActivator"
ZERO_GUID = "00000000-0000-0000-0000-000000000000"

# Find the Reflex item
reflex_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=Reflex")
reflex_resp.raise_for_status()
reflex_item = next(
    (i for i in reflex_resp.json()["value"] if i["displayName"] == activator_name),
    None,
)

if not reflex_item:
    print(f"⚠️ Activator '{activator_name}' not found — skipping patch")
elif not db_item or not queryset_item:
    print("⚠️ KQL Database or QuerySet not found — skipping Activator patch")
else:
    reflex_id = reflex_item["id"]
    print(f"Activator ID: {reflex_id}")

    # Get current Reflex definition
    def_resp = client.post(
        f"/v1/workspaces/{workspace_id}/items/{reflex_id}/getDefinition"
    )
    def_resp.raise_for_status()
    definition = def_resp.json()["definition"]

    # Find and patch ReflexEntities.json
    for part in definition["parts"]:
        if part["path"] == "ReflexEntities.json":
            content = json.loads(base64.b64decode(part["payload"]).decode("utf-8"))

            # Patch eventhouseItem
            source = content.get("source", {})
            eh_item = source.get("eventhouseItem", {})
            if eh_item.get("itemId") == ZERO_GUID:
                eh_item["itemId"] = db_id
            if eh_item.get("workspaceId") == ZERO_GUID:
                eh_item["workspaceId"] = workspace_id

            # Patch metadata
            metadata = source.get("metadata", {})
            if metadata.get("workspaceId") == ZERO_GUID:
                metadata["workspaceId"] = workspace_id
            if metadata.get("querySetId") == ZERO_GUID:
                metadata["querySetId"] = queryset_id

            part["payload"] = base64.b64encode(
                json.dumps(content, indent=2).encode("utf-8")
            ).decode("utf-8")
            break

    # Update the Reflex definition
    update_body = {"definition": definition}
    update_resp = client.post(
        f"/v1/workspaces/{workspace_id}/items/{reflex_id}/updateDefinition",
        json=update_body,
    )
    update_resp.raise_for_status()
    print(f"✅ Activator patched — connected to DB '{kql_db_name}' and QuerySet '{queryset_name}'")

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
