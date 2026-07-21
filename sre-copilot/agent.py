import os
import sys
import json
import subprocess
import logging
import requests
import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession
from openai import AzureOpenAI
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

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

# Core Execution Logic
@tracer.start_as_current_span("execute_tool")
def execute_tool(name, args, reasoning="", incident_type="Unknown Incident"):
    span = trace.get_current_span()
    span.set_attribute("tool.name", name)
    span.set_attribute("tool.args", json.dumps(args))
    logger.info(f"Invoking target tool: {name} with arguments: {args}")
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_url = os.getenv("GITHUB_REPO_URL")
        if not github_token or not repo_url:
            raise Exception("Missing GITHUB_TOKEN or GITHUB_REPO_URL environment variables")
            
        subprocess.run("rm -rf /tmp/repo", shell=True)
        clone_cmd = f"git clone https://oauth2:{github_token}@{repo_url} /tmp/repo"
        res = subprocess.run(clone_cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            raise Exception(f"Git clone failed: {res.stderr}")
            
        subprocess.run('git config --global user.email "sre-copilot@example.com"', shell=True, cwd="/tmp/repo")
        subprocess.run('git config --global user.name "SRE Copilot"', shell=True, cwd="/tmp/repo")
        
        target_file = "/tmp/repo/manifests/mlops/deployment.yaml"
        commit_msg = ""
        is_tier_1 = name in ["scale_deployment", "patch_pod_limits"]
        is_tier_2 = name in ["rollback_deployment", "trigger_retraining", "cordon_and_drain"]
        
        if is_tier_2:
            import time
            branch_name = f"sre-copilot-remediation-{int(time.time())}"
            subprocess.run(f"git checkout -b {branch_name}", shell=True, cwd="/tmp/repo", check=True)
            
        if name == "scale_deployment":
            import re
            with open(target_file, 'r') as f:
                yaml_content = f.read()
            yaml_content = re.sub(r"replicas:\s*\d+", f"replicas: {args['replicas']}", yaml_content)
            with open(target_file, 'w') as f:
                f.write(yaml_content)
            commit_msg = f"[Auto-Remediation] Traffic Spike"
            
        elif name == "patch_pod_limits":
            import re
            with open(target_file, 'r') as f:
                yaml_content = f.read()
            yaml_content = re.sub(r"cpu:\s*\"?[0-9]+m?\"?", f"cpu: \"{args['cpu']}\"", yaml_content)
            yaml_content = re.sub(r"memory:\s*\"?[0-9]+[A-Za-z]+\"?", f"memory: {args['memory']}", yaml_content)
            with open(target_file, 'w') as f:
                f.write(yaml_content)
            commit_msg = f"[Auto-Remediation] Resource Starvation"
            
        elif name == "rollback_deployment":
            subprocess.run('git revert --no-commit HEAD', shell=True, cwd="/tmp/repo", check=True)
            commit_msg = f"[Tier 2 Proposal] Rollback Bad Release"
            
        elif name == "trigger_retraining":
            os.makedirs("/tmp/repo/audit", exist_ok=True)
            with open("/tmp/repo/audit/PROPOSAL.md", "w") as f:
                f.write(f"# ML Pipeline Retraining Proposal\n\nTarget Webhook: {args['pipeline_webhook_url']}\n")
            commit_msg = f"[Tier 2 Proposal] Trigger Retraining Pipeline"
            
        elif name == "cordon_and_drain":
            os.makedirs("/tmp/repo/audit", exist_ok=True)
            with open("/tmp/repo/audit/PROPOSAL.md", "w") as f:
                f.write(f"# Cordon and Drain Proposal\n\nTarget Node: {args['node_name']}\n")
            commit_msg = f"[Tier 2 Proposal] Cordon and Drain Node"
        
        subprocess.run('git add .', shell=True, cwd="/tmp/repo", check=True)
        subprocess.run(f'git commit -m "{commit_msg}"', shell=True, cwd="/tmp/repo", check=True)
        
        if is_tier_1:
            subprocess.run('git push origin main', shell=True, cwd="/tmp/repo", check=True)
            logger.info("[TIER 1] Auto-remediation pushed to main.")
            return f"GitOps Success: {commit_msg}"
            
        elif is_tier_2:
            subprocess.run(f'git push origin {branch_name}', shell=True, cwd="/tmp/repo", check=True)
            
            import urllib.parse
            # Repo URL format: github.com/owner/repo.git
            parsed = urllib.parse.urlparse("https://" + repo_url)
            path_parts = parsed.path.strip('/').replace('.git', '').split('/')
            owner = path_parts[0]
            repo = path_parts[1]
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            pr_data = {
                "title": f"[URGENT] AI Remediation Proposal: {incident_type}",
                "head": branch_name,
                "base": "main",
                "body": f"### AI Remediation Proposal\n\n**Incident:** {incident_type}\n**Proposed Action:** {name}\n**Arguments:** {json.dumps(args, indent=2)}\n\n### LLM Reasoning\n\n{reasoning}"
            }
            
            pr_res = requests.post(api_url, headers=headers, json=pr_data)
            if pr_res.status_code == 201:
                pr_url = pr_res.json().get("html_url")
                logger.info(f"[TIER 2] Destructive action proposed. PR opened for Human Review: {pr_url}")
                return f"PR created successfully: {pr_url}"
            else:
                logger.error(f"Failed to create PR: {pr_res.text}")
                return f"Branch pushed, but PR creation failed: {pr_res.text}"
                
    except subprocess.CalledProcessError as e:
        logger.error(f"Execution failed for tool {name}: {e.stderr}")
        return f"Execution error: {e.stderr}"
    except Exception as e:
        logger.error(f"Unexpected error in tool execution: {str(e)}")
        return f"Error: {str(e)}"

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
        # Placeholder for Slack/PagerDuty notification webhook hook here
        print(f"SLACK_ALERT: Operational failure detected. Requiring Manual Intervention. Details: {response_message.content}")
        return
        
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            reasoning = response_message.content or "No explicit reasoning provided by LLM."
            try:
                incident_type = json.loads(telemetry_context).get("incident", "Unknown Incident")
            except:
                incident_type = "Unknown Incident"
            result = execute_tool(name, args, reasoning, incident_type)
            logger.info(f"Action Result: {result}")
    else:
        logger.info(f"Telemetry evaluated. No remediation action required or safe state reached: {response_message.content}")


@tracer.start_as_current_span("query_signoz_mcp")
def query_signoz_mcp() -> str:
    span = trace.get_current_span()
    logger.info("Polling live telemetry for fraud-detection-api anomalies via SigNoz MCP...")
    
    mcp_endpoint = os.getenv("SIGNOZ_MCP_ENDPOINT", "http://signoz-mcp.oppe2-app.svc.cluster.local:8000/mcp")
    
    async def _query_mcp():
        try:
            # Connect to the SigNoz MCP server using Streamable HTTP
            async with streamablehttp_client(mcp_endpoint) as (read_stream, write_stream, get_sid):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    
                    # Search logs for OOMKilled via MCP server's exposed tool
                    args = {
                        "searchText": "OOMKilled",
                        "filter": "kubernetes.labels.app = 'fraud-detection-api'",
                        "timeRange": "5m"
                    }
                    result = await session.call_tool("signoz_search_logs", args)
                    
                    # Parse the MCP tool execution result
                    if hasattr(result, "content") and result.content:
                        content_str = result.content[0].text
                        data = json.loads(content_str)
                        if isinstance(data, list) and len(data) > 0:
                            # Usually log results return a list of matching logs
                            span.set_attribute("incident.detected", True)
                            span.set_attribute("incident.type", "OOMKilled")
                            logger.warning("🚨 SigNoz MCP Alert: OOMKilled detected via MCP telemetry query!")
                            return json.dumps({
                                "incident": "OOMKilled",
                                "deployment": "fraud-detection-api",
                                "namespace": "oppe2-app",
                                "error_rate": "100%",
                                "description": "Pod terminated due to memory starvation (OOMKilled). Critical resource exhaustion detected via MCP."
                            })
                    
                    span.set_attribute("incident.detected", False)
                    return json.dumps({"status": "OK"})
        except Exception as e:
            logger.warning(f"SigNoz MCP unreachable or query failed, falling back to k8s api... ({e})")
            span.set_attribute("mcp.fallback", True)
            
            # Fallback to direct K8s API query if MCP is not responding
            cmd = "kubectl get pods -l app=fraud-detection-api -n oppe2-app -o json"
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
                pods = json.loads(res.stdout).get("items", [])
                for pod in pods:
                    statuses = pod.get("status", {}).get("containerStatuses", [])
                    for status in statuses:
                        state = status.get("state", {})
                        last_state = status.get("lastState", {})
                        
                        is_oom = False
                        if state.get("terminated", {}).get("reason") == "OOMKilled":
                            is_oom = True
                        if last_state.get("terminated", {}).get("reason") == "OOMKilled":
                            is_oom = True
                        
                        if is_oom:
                            span.set_attribute("incident.detected", True)
                            span.set_attribute("incident.type", "OOMKilled")
                            logger.warning("🚨 Alert: OOMKilled detected in live telemetry!")
                            return json.dumps({
                                "incident": "OOMKilled",
                                "deployment": "fraud-detection-api",
                                "namespace": "oppe2-app",
                                "error_rate": "100%",
                                "description": "Pod terminated due to memory starvation (OOMKilled). Critical resource exhaustion detected."
                            })
            except Exception as e2:
                span.record_exception(e2)
                logger.error(f"Error polling telemetry: {e2}")
                
            return json.dumps({"status": "OK"})
            
    return asyncio.run(asyncio.wait_for(_query_mcp(), timeout=10.0))

def main_loop():
    logger.info("Starting Intelligent Remediation Loop...")
    while True:
        try:
            mcp_data = query_signoz_mcp()
            if '"status": "OK"' not in mcp_data:
                run_agent_workflow(mcp_data)
        except Exception as e:
            logger.error(f"Error in SRE Copilot Loop: {e}")

        logger.info("Sleeping for 10 seconds before next check...")
        time.sleep(10)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Exiting Copilot...")
