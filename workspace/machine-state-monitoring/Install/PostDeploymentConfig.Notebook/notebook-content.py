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
eventhouse_name = "MachineMonitoringEH"
kql_db_name = "MachineMonitoringEH"

kusto_query_uri = get_kusto_query_uri(workspace_id, eventhouse_name, client)

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

# ## 3. Create Activator with real database and QuerySet IDs
# 
# The Activator (Reflex) is not deployed by fabric-launcher because its
# definition requires real workspace-specific IDs that can't use placeholders.
# This step creates it via API with the correct IDs resolved at runtime.

# CELL ********************

import json, base64

activator_name = "MachineStateActivator"
queryset_name = "SubscriptionsMonitoringKQL"
kql_db_name = "MachineMonitoringEH"

# Resolve real IDs
db_items_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=KQLDatabase")
db_items_resp.raise_for_status()
db_item = next(
    (i for i in db_items_resp.json()["value"] if i["displayName"] == kql_db_name),
    None,
)

qs_items_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=KQLQueryset")
qs_items_resp.raise_for_status()
qs_item = next(
    (i for i in qs_items_resp.json()["value"] if i["displayName"] == queryset_name),
    None,
)

if not db_item:
    raise RuntimeError(f"KQL Database '{kql_db_name}' not found in workspace")
if not qs_item:
    raise RuntimeError(f"KQL QuerySet '{queryset_name}' not found in workspace")

db_id = db_item["id"]
qs_id = qs_item["id"]
print(f"KQL Database ID: {db_id}")
print(f"KQL QuerySet ID: {qs_id}")

# Check if Activator already exists
reflex_resp = client.get(f"/v1/workspaces/{workspace_id}/items?type=Reflex")
reflex_resp.raise_for_status()
existing = next(
    (i for i in reflex_resp.json()["value"] if i["displayName"] == activator_name),
    None,
)

if existing:
    print(f"Activator '{activator_name}' already exists (ID: {existing['id']}) — skipping creation")
else:
    # Build ReflexEntities with real IDs injected
    reflex_entities = [{"uniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd","payload":{"name":"SubscriptionsMonitoringKQL","description":"Container Description","type":"kqlQueries"},"type":"container-v1"},{"uniqueIdentifier":"aa662b45-0c51-4414-b60c-2725e89e94ef","payload":{"name":"MachineMonitoringEH event","runSettings":{"executionIntervalInSeconds":60},"query":{"queryString":"let machine_states = MachineStateEvents\n    | summarize arg_max(timestamp, state) by machine_id\n    | extend duration_min = datetime_diff('minute', now(), timestamp)\n    | project machine_id, current_state = state, duration_min;\nSubscriptionsState\n| where action == \"subscribe\"\n| join kind=leftouter machine_states on machine_id\n| extend is_breached = (current_state == state and duration_min >= duration_threshold_minutes)\n| project subscription_key, machine_id, state, current_state, duration_min, user_email, duration_threshold_minutes, is_breached"},"eventhouseItem":{"itemId":"PLACEHOLDER_DB_ID","workspaceId":"PLACEHOLDER_WORKSPACE_ID","itemType":"KustoDatabase"},"metadata":{"workspaceId":"PLACEHOLDER_WORKSPACE_ID","querySetId":"PLACEHOLDER_QS_ID","queryId":"00000000-0000-0000-0000-000000000000"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"}},"type":"kqlSource-v1"},{"uniqueIdentifier":"00a68224-da49-483d-b007-f53f48fe5efa","payload":{"name":"MachineMonitoringEH event","parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Event","instance":"{\"steps\":[{\"id\":\"fa5555be-aeda-4426-8d74-2b62e68ddd1e\",\"name\":\"SourceEventStep\",\"rows\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"aa662b45-0c51-4414-b60c-2725e89e94ef\"}],\"kind\":\"SourceReference\",\"name\":\"SourceSelector\"}]}],\"templateId\":\"SourceEvent\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d","payload":{"name":"Subscription","parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Object"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"176bd76a-656c-4acc-acb9-5e5876f9d470","payload":{"name":"subscription_key","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"e3fa948c-6431-4e08-aa8e-b5590eac6e73\",\"name\":\"IdPartStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Text\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"IdentityPartAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"5c424c01-cf29-478a-8d34-415c36284797","payload":{"name":"subscription_key","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"bd28f6cd-78ee-45d7-a10d-3b23464ca60a\",\"name\":\"IdStructureStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"176bd76a-656c-4acc-acb9-5e5876f9d470\"}],\"kind\":\"AttributeReference\",\"name\":\"idPart\",\"type\":\"complex\"}],\"kind\":\"IdPart\",\"name\":\"IdPart\"}]}],\"templateId\":\"IdentityTupleAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"1f976774-a2c1-477b-9296-5ebe293142b5","payload":{"name":"MachineMonitoringEH event","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Event","instance":"{\"steps\":[{\"id\":\"f5d7e4c2-7118-4a99-b5d3-0247ceb554c4\",\"name\":\"SplitEventStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"00a68224-da49-483d-b007-f53f48fe5efa\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"subscription_key\"},{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"176bd76a-656c-4acc-acb9-5e5876f9d470\"}],\"kind\":\"AttributeReference\",\"name\":\"idPart\",\"type\":\"complex\"}],\"kind\":\"FieldIdMapping\",\"name\":\"FieldIdMapping\"},{\"arguments\":[{\"name\":\"isAuthoritative\",\"type\":\"boolean\",\"value\":true}],\"kind\":\"EventOptions\",\"name\":\"SplitEventOptions\"}]}],\"templateId\":\"SplitEvent\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"de0eec4a-b90a-40bd-a94d-d3a6799a60ea","payload":{"name":"duration_threshold_minutes","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"2c65f0b7-3178-497e-87fa-24083be3013a\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"duration_threshold_minutes\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"cea931a1-689e-4bb7-8af8-2fdeaec69418\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Number\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"f0c64b65-42d7-4e24-9ed0-b8be8b74be08","payload":{"name":"duration_min","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"34d05d97-a05f-492e-998f-0ad2c78c62d6\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"duration_min\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"1c63e40f-31c4-4ee8-a784-b72ff10bec3e\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Number\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"c74693d2-d555-4095-9be0-a238c4de6bba","payload":{"name":"is_breached","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"6188ffe5-07df-42b4-8fa3-a0d04f1979b0\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"is_breached\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"a6d6365b-68ec-4df1-8d35-25ba6297cff6\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Number\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"ae19cc57-a624-4dee-a27d-e82003da594e","payload":{"name":"machine_id","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"4e38bdbd-b884-400c-a541-51c90ace344e\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"machine_id\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"84d24c0f-4e13-4027-be9a-83f76cfe5138\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Text\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"31acd232-1e43-499e-b3a9-933c68dc8cd7","payload":{"name":"state","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"068c5bb0-1619-413a-9a3b-51c78ae2cca5\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"state\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"c601a820-d6f4-45b0-9524-3b36caa49bf6\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Text\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"53f5b0e5-a18e-4b00-bd5e-aa3ad5f5ef9a","payload":{"name":"user_email","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Attribute","instance":"{\"steps\":[{\"id\":\"512f8901-d1b3-4565-8981-c56d8fa03b08\",\"name\":\"EventSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"1f976774-a2c1-477b-9296-5ebe293142b5\"}],\"kind\":\"EventReference\",\"name\":\"event\",\"type\":\"complex\"}],\"kind\":\"Event\",\"name\":\"EventSelector\"},{\"arguments\":[{\"name\":\"fieldName\",\"type\":\"string\",\"value\":\"user_email\"}],\"kind\":\"EventField\",\"name\":\"EventFieldSelector\"}]},{\"id\":\"ccf76378-486a-44d8-9bfc-b2612dc67f91\",\"name\":\"EventComputeStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"Text\"},{\"name\":\"format\",\"type\":\"string\",\"value\":\"\"}],\"kind\":\"TypeAssertion\",\"name\":\"TypeAssertion\"}]}],\"templateId\":\"BasicEventAttribute\",\"templateVersion\":\"1.2.4\"}"}},"type":"timeSeriesView-v1"},{"uniqueIdentifier":"631c0186-3536-4c6b-96b9-ca8416cd1044","payload":{"name":"is_breached alert","parentObject":{"targetUniqueIdentifier":"d5de2210-dcd2-4947-8105-8ca326cee19d"},"parentContainer":{"targetUniqueIdentifier":"e8b90c63-1562-4610-962a-131dda6bbecd"},"definition":{"type":"Rule","instance":"{\"steps\":[{\"id\":\"4316b3c5-026a-42a1-a26e-9d1614d67c6d\",\"name\":\"ScalarSelectStep\",\"rows\":[{\"arguments\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"c74693d2-d555-4095-9be0-a238c4de6bba\"}],\"kind\":\"AttributeReference\",\"name\":\"attribute\",\"type\":\"complex\"}],\"kind\":\"Attribute\",\"name\":\"AttributeSelector\"}]},{\"id\":\"88527759-1cae-4eaa-b82f-2db326f66663\",\"name\":\"ScalarDetectStep\",\"rows\":[{\"arguments\":[{\"name\":\"op\",\"type\":\"string\",\"value\":\"ChangesTo\"},{\"name\":\"value\",\"type\":\"string\",\"value\":\"1\"}],\"kind\":\"TextChanges\",\"name\":\"TextChanges\"},{\"arguments\":[],\"kind\":\"EachTime\",\"name\":\"OccurrenceOption\"}]},{\"id\":\"81118079-f78e-4e0a-81ac-b4535d6d7d40\",\"name\":\"ActStep\",\"rows\":[{\"arguments\":[{\"name\":\"messageLocale\",\"type\":\"string\",\"value\":\"en-us\"},{\"name\":\"sentTo\",\"type\":\"array\",\"values\":[{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"53f5b0e5-a18e-4b00-bd5e-aa3ad5f5ef9a\"}],\"kind\":\"AttributeReference\",\"type\":\"complex\"}]},{\"name\":\"copyTo\",\"type\":\"array\",\"values\":[]},{\"name\":\"bCCTo\",\"type\":\"array\",\"values\":[]},{\"name\":\"subject\",\"type\":\"array\",\"values\":[{\"type\":\"string\",\"value\":\"Activator alert is_breached alert\"}]},{\"name\":\"headline\",\"type\":\"array\",\"values\":[{\"type\":\"string\",\"value\":\"The condition for 'is_breached alert' has been met\"}]},{\"name\":\"optionalMessage\",\"type\":\"array\",\"values\":[{\"type\":\"string\",\"value\":\"\"}]},{\"name\":\"additionalInformation\",\"type\":\"array\",\"values\":[{\"arguments\":[{\"name\":\"name\",\"type\":\"string\",\"value\":\"duration_min\"},{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"f0c64b65-42d7-4e24-9ed0-b8be8b74be08\"}],\"kind\":\"AttributeReference\",\"name\":\"reference\",\"type\":\"complexReference\"}],\"kind\":\"NameReferencePair\",\"type\":\"complex\"},{\"arguments\":[{\"name\":\"name\",\"type\":\"string\",\"value\":\"machine_id\"},{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"ae19cc57-a624-4dee-a27d-e82003da594e\"}],\"kind\":\"AttributeReference\",\"name\":\"reference\",\"type\":\"complexReference\"}],\"kind\":\"NameReferencePair\",\"type\":\"complex\"},{\"arguments\":[{\"name\":\"name\",\"type\":\"string\",\"value\":\"state\"},{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"31acd232-1e43-499e-b3a9-933c68dc8cd7\"}],\"kind\":\"AttributeReference\",\"name\":\"reference\",\"type\":\"complexReference\"}],\"kind\":\"NameReferencePair\",\"type\":\"complex\"},{\"arguments\":[{\"name\":\"name\",\"type\":\"string\",\"value\":\"duration_threshold_minutes\"},{\"arguments\":[{\"name\":\"entityId\",\"type\":\"string\",\"value\":\"de0eec4a-b90a-40bd-a94d-d3a6799a60ea\"}],\"kind\":\"AttributeReference\",\"name\":\"reference\",\"type\":\"complexReference\"}],\"kind\":\"NameReferencePair\",\"type\":\"complex\"}]}],\"kind\":\"EmailMessage\",\"name\":\"EmailBinding\"}]}],\"templateId\":\"AttributeTrigger\",\"templateVersion\":\"1.2.4\"}","settings":{"shouldRun":true,"shouldApplyRuleOnUpdate":true}}},"type":"timeSeriesView-v1"}]

    # Inject real IDs into the source entity
    for entity in reflex_entities:
        if entity.get("type") == "kqlSource-v1":
            src = entity["payload"]
            src["eventhouseItem"]["itemId"] = db_id
            src["eventhouseItem"]["workspaceId"] = workspace_id
            src["metadata"]["workspaceId"] = workspace_id
            src["metadata"]["querySetId"] = qs_id
            break

    payload_b64 = base64.b64encode(
        json.dumps(reflex_entities, indent=2).encode("utf-8")
    ).decode("utf-8")

    create_body = {
        "displayName": activator_name,
        "type": "Reflex",
        "definition": {
            "parts": [
                {
                    "path": "ReflexEntities.json",
                    "payload": payload_b64,
                    "payloadType": "InlineBase64"
                }
            ]
        }
    }

    create_resp = client.post(
        f"/v1/workspaces/{workspace_id}/items",
        json=create_body,
    )
    create_resp.raise_for_status()
    print(f"✅ Activator '{activator_name}' created with correct DB and QuerySet IDs")

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
