import os
import sys
import json
import logging
import time
from openai import AzureOpenAI

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from mcp_client import run_mcp_checks
from k8s_tools import run_k8s_checks, get_cooldown, set_cooldown
from gitops import execute_tool
import slack_notifier

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sre-copilot")

# Setup OTel Tracing
resource = Resource.create({"service.name": "sre-copilot-agent"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer("sre-copilot.agent")
span_processor = BatchSpanProcessor(OTLPSpanExporter(
    endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://signoz-ingester.signoz.svc.cluster.local:4317"),
    insecure=True
))
trace.get_tracer_provider().add_span_processor(span_processor)

# Tool Definition Registry
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "scale_deployment",
            "description": "Scales a deployment's replica count up or down horizontally to handle traffic spikes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                    "replicas": {"type": "integer"}
                },
                "required": ["name", "namespace", "replicas"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch_pod_limits",
            "description": "Increases CPU and memory resource ceilings when a pod encounters resource starvation or OOMKilled events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                    "cpu": {"type": "string", "description": "e.g., '1000m'"},
                    "memory": {"type": "string", "description": "e.g., '1Gi'"}
                },
                "required": ["name", "namespace", "cpu", "memory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_deployment",
            "description": "Rolls back a deployment to its previous stable revision if a bad release or corrupted image tag breaks the pod status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"}
                },
                "required": ["name", "namespace"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_retraining",
            "description": "Kicks off an automated MLflow retraining pipeline when statistical model drift is detected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_webhook_url": {"type": "string"}
                },
                "required": ["pipeline_webhook_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cordon_and_drain",
            "description": "Cordon a hardware node and gracefully evict pods when disk or memory pressure threatens node stability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {"type": "string"}
                },
                "required": ["node_name"]
            }
        }
    }
]

COOLDOWN_SECONDS = 300
ACTIVE_REMEDIATIONS = {}  # {incident_type: {"time": timestamp, "tools": ["..."]}}
PENDING_INCIDENTS = set()  # Locks incidents currently sitting in Slack awaiting human authorization

@tracer.start_as_current_span("run_agent_workflow")
def run_agent_workflow(telemetry_context: str):
    span = trace.get_current_span()
    span.set_attribute("incident.context", telemetry_context)
    logger.info("Starting Intelligent Diagnostic & Remediation Loop...")
    
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-05-01-preview",
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    
    system_prompt = os.getenv("SYSTEM_PROMPT", "Default SRE behavior.")
    
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this live SigNoz incident data: {telemetry_context}"}
        ],
        tools=tools_schema,
        tool_choice="auto"
    )
    
    span.set_attribute("gen_ai.usage.prompt_tokens", response.usage.prompt_tokens if response.usage else 0)
    span.set_attribute("gen_ai.usage.completion_tokens", response.usage.completion_tokens if response.usage else 0)
    
    response_message = response.choices[0].message
    
    # Check for Explicit Phase 2 Interlock Stop (HALT)
    if response_message.content and "HALT_INSUFFICIENT_TOOLS" in response_message.content:
        logger.warning("🚨 [PHASE 2 GUARDRAIL BREACHED] - Agent lacks the necessary tools to safely cure this incident.")
        logger.warning(f"Reasoning breakdown from LLM: {response_message.content}")
        slack_notifier.send_slack_message(f"🚨 *Operational failure detected!* Requiring Manual Intervention.\n*Details:* {response_message.content}")
        return []
        
    executed_tools = []
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            reasoning = response_message.content or "PromQL telemetry indicates resource starvation/latency threshold breached. AI recommends applying manifest patch."
            
            try:
                incident_dict = json.loads(telemetry_context)
                incident_type = incident_dict.get("incident", "Unknown Incident")
                deployment = incident_dict.get("deployment", "fraud-detection-api")
                namespace = incident_dict.get("namespace", "oppe2-app")
                trace_id = incident_dict.get("trace_id", "N/A")
            except Exception:
                incident_type = "Unknown Incident"
                deployment = "fraud-detection-api"
                namespace = "oppe2-app"
                trace_id = "N/A"

            incident_key = f"{deployment}:{incident_type}"

            # Build and send interactive Human-in-the-Loop Slack Card with 3 approval buttons
            interactive_blocks = slack_notifier.build_interactive_proposal_blocks(
                incident_type=incident_type,
                target_pod=deployment,
                namespace=namespace,
                reasoning=reasoning,
                tool_name=name,
                tool_args=args,
                trace_id=trace_id
            )
            
            slack_notifier.send_slack_message(
                message=f"🚨 [CRITICAL ALERT] {incident_type} - Action Required",
                blocks=interactive_blocks
            )
            logger.info(f"Dispatched interactive Slack approval card for tool proposal: {name} with args {args}")

            # If Socket Mode is active, human approval via Slack buttons executes the action.
            # Set circuit-breaker lock so 10s diagnostic loop skips re-evaluating this incident.
            if os.getenv("SLACK_APP_TOKEN"):
                PENDING_INCIDENTS.add(incident_key)
                logger.info(f"🔒 [CIRCUIT BREAKER] Incident locked as '{incident_key}'. Execution deferred until human approval in Slack.")
            else:
                result = execute_tool(name, args, reasoning, incident_type)
                executed_tools.append(name)
                logger.info(f"Action Result (Direct Execution): {result}")
    else:
        logger.info(f"Telemetry evaluated. No remediation action required or safe state reached: {response_message.content}")

    return executed_tools


@tracer.start_as_current_span("diagnostic_engine")
def run_diagnostic_engine() -> str:
    """
    Autonomous Diagnostic Engine: runs MCP checks first, then K8s API checks.
    Returns the first detected incident or OK.
    """
    span = trace.get_current_span()
    mcp_endpoint = os.getenv("SIGNOZ_MCP_ENDPOINT", "http://signoz-mcp.oppe2-app.svc.cluster.local:8000/mcp")

    # --- Phase A: MCP-based telemetry checks ---
    logger.info("Diagnostic Engine: Running MCP-based health checks...")
    try:
        mcp_result = run_mcp_checks(mcp_endpoint)
        if '"status": "OK"' not in mcp_result:
            span.set_attribute("detection.source", "MCP")
            return mcp_result
    except Exception as e:
        logger.warning(f"MCP checks failed, falling back to K8s API... ({e})")
        span.set_attribute("mcp.fallback", True)

    # --- Phase B: Kubernetes API health checks (always run as augmentation) ---
    logger.info("Diagnostic Engine: Running K8s API health checks...")
    k8s_result = run_k8s_checks()
    if '"status": "OK"' not in k8s_result:
        span.set_attribute("detection.source", "K8sAPI")
        return k8s_result

    return json.dumps({"status": "OK"})


def main_loop():
    logger.info("Starting Autonomous Diagnostic Engine...")
    # Initialize Slack Socket Mode for interactive Human-in-the-Loop buttons
    slack_notifier.init_socket_mode()

    while True:
        try:
            incident_data = run_diagnostic_engine()
            current_time = time.time()
            
            if '"status": "OK"' in incident_data:
                # Post-Remediation Verification check
                resolved_incidents = []
                for inc_type, state in ACTIVE_REMEDIATIONS.items():
                    blocks = slack_notifier.build_success_blocks(inc_type, state['tools'])
                    slack_notifier.send_slack_message(message=f"✅ Remediation Successful: {inc_type}", blocks=blocks)
                    resolved_incidents.append(inc_type)
                for inc_type in resolved_incidents:
                    del ACTIVE_REMEDIATIONS[inc_type]
            else:
                try:
                    incident_dict = json.loads(incident_data)
                    incident_type = incident_dict.get("incident", "Unknown")
                    deployment = incident_dict.get("deployment", "fraud-detection-api")
                except Exception:
                    incident_dict = {"incident": "Unknown"}
                    incident_type = "Unknown"
                    deployment = "fraud-detection-api"
                
                incident_key = f"{deployment}:{incident_type}"

                # Circuit Breaker: If an alert is sitting in Slack awaiting human authorization, skip loop execution!
                if incident_key in PENDING_INCIDENTS:
                    logger.info(f"⏸️ [CIRCUIT BREAKER] Incident '{incident_key}' is awaiting human decision in Slack. Skipping loop iteration.")
                    time.sleep(10)
                    continue

                # Check for failed remediations (persists for > 2 mins since remediation)
                if incident_type in ACTIVE_REMEDIATIONS:
                    time_since = current_time - ACTIVE_REMEDIATIONS[incident_type]["time"]
                    if time_since > 120:
                        slack_notifier.send_slack_message(f"❌ *Remediation Failed!* Incident `{incident_type}` persists after 2 minutes despite tools: {ACTIVE_REMEDIATIONS[incident_type]['tools']}. Manual intervention required!")
                        # Push timestamp far into future to prevent webhook spam
                        ACTIVE_REMEDIATIONS[incident_type]["time"] = current_time + 86400  
                
                last_time = get_cooldown(incident_type)
                
                if current_time - last_time < COOLDOWN_SECONDS:
                    logger.info(f"Cooldown active for '{incident_type}'. Skipping remediation.")
                else:
                    executed_tools = run_agent_workflow(incident_data)
                    if executed_tools:
                        ACTIVE_REMEDIATIONS[incident_type] = {"time": current_time, "tools": executed_tools}
                    set_cooldown(incident_type, current_time)
        except Exception as e:
            logger.error(f"Error in SRE Copilot Loop: {e}")

        logger.info("Sleeping for 10 seconds before next check...")
        time.sleep(10)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Exiting Copilot...")
