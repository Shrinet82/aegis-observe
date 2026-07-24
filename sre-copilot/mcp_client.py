import json
import logging
import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession
from opentelemetry import trace

logger = logging.getLogger("sre-copilot.mcp")
tracer = trace.get_tracer("sre-copilot.mcp")

HEALTH_CHECKS_MCP = [
    {
        "name": "Resource Starvation (OOM)",
        "searchText": "OOMKilled",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "5m",
        "incident_template": {
            "incident": "OOMKilled",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "Pod terminated due to memory starvation (OOMKilled). Critical resource exhaustion detected via MCP."
        }
    },
    {
        "name": "Resource Starvation (Limit)",
        "searchText": "MemoryLimitExceeded",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "5m",
        "incident_template": {
            "incident": "OOMKilled",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "Pod memory usage limit exceeded. Critical resource exhaustion detected via MCP."
        }
    },
    {
        "name": "Traffic Spike / Latency (Timeout)",
        "searchText": "timeout",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "5m",
        "incident_template": {
            "incident": "Traffic Spike",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "Sustained timeout or high-latency errors detected. Possible traffic spike overwhelming available replicas."
        }
    },
    {
        "name": "Traffic Spike / Latency (504)",
        "searchText": "504",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "5m",
        "incident_template": {
            "incident": "Traffic Spike",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "504 gateway timeout errors detected in API. Possible traffic spike overwhelming available replicas."
        }
    },
    {
        "name": "Model Drift (Drift)",
        "searchText": "drift detected",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "10m",
        "incident_template": {
            "incident": "Model Drift",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "ML model drift detected. Prediction confidence has fallen below acceptable threshold."
        }
    },
    {
        "name": "Model Drift (Confidence)",
        "searchText": "confidence below threshold",
        "filter": "resource.k8s.deployment.name = 'fraud-detection-api'",
        "timeRange": "10m",
        "incident_template": {
            "incident": "Model Drift",
            "deployment": "fraud-detection-api",
            "namespace": "oppe2-app",
            "description": "Model prediction confidence has degraded below acceptable thresholds."
        }
    }
]

@tracer.start_as_current_span("check_mcp_health")
def run_mcp_checks(mcp_endpoint: str) -> str:
    """Run all MCP-based health checks against SigNoz logs. Returns incident JSON or OK."""
    span = trace.get_current_span()

    async def _query():
        try:
            async with streamablehttp_client(mcp_endpoint) as (read_stream, write_stream, get_sid):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    for check in HEALTH_CHECKS_MCP:
                        args = {
                            "searchText": check["searchText"],
                            "filter": check["filter"],
                            "timeRange": check["timeRange"]
                        }
                        try:
                            result = await session.call_tool("signoz_search_logs", args)
                            if hasattr(result, "content") and result.content:
                                content_str = result.content[0].text
                                data = json.loads(content_str)
                                
                                # Parse the nested query results structure from SigNoz MCP
                                results = data.get("data", {}).get("data", {}).get("results", [])
                                rows = []
                                if results and len(results) > 0:
                                    rows = results[0].get("rows", [])
                                    
                                if len(rows) > 0:
                                    span.set_attribute("incident.detected", True)
                                    span.set_attribute("incident.type", check["name"])
                                    logger.warning(f"\U0001F6A8 SigNoz MCP Alert: {check['name']} detected!")
                                    
                                    incident_data = dict(check["incident_template"])
                                    
                                    # Extract trace_id from row if available
                                    first_row = rows[0]
                                    trace_id = None
                                    if isinstance(first_row, dict):
                                        trace_id = first_row.get("trace_id") or first_row.get("traceId")
                                    elif isinstance(first_row, list):
                                        for item in first_row:
                                            if isinstance(item, str) and len(item) == 32:
                                                trace_id = item
                                                break

                                    if trace_id:
                                        try:
                                            logger.info(f"Fetching trace details via MCP for trace_id: {trace_id}")
                                            trace_res = await session.call_tool("signoz_get_trace_details", {"traceId": trace_id})
                                            if hasattr(trace_res, "content") and trace_res.content:
                                                incident_data["trace_id"] = trace_id
                                                incident_data["description"] += f" [Enriched via MCP Trace {trace_id}]"
                                        except Exception as trace_err:
                                            logger.warning(f"Failed to fetch trace details for {trace_id}: {trace_err}")

                                    return json.dumps(incident_data)
                        except Exception as tool_err:
                            logger.debug(f"MCP check '{check['name']}' tool error: {tool_err}")
                            continue

                    span.set_attribute("incident.detected", False)
                    return json.dumps({"status": "OK"})
        except Exception as e:
            raise e

    return asyncio.run(asyncio.wait_for(_query(), timeout=15.0))
