import os
import sys
import json
import subprocess
import logging
import requests
from openai import AzureOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sre-copilot")

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
def execute_tool(name, args, reasoning="", incident_type="Unknown Incident"):
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
        is_tier_1 = name in ["scale_deployment"]
        is_tier_2 = name in ["patch_pod_limits", "rollback_deployment", "trigger_retraining", "cordon_and_drain"]
        
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

def run_agent_workflow(telemetry_context: str):
    logger.info("Starting Intelligent Diagnostic & Remediation Loop...")
    
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-05-01-preview",
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    
    system_prompt = """
You are an autonomous SRE Copilot Agent. 
You will receive raw telemetry data exported from SigNoz (Prometheus/ClickHouse format).

Your strict directives:
1. Analyze the 'metric_data' time-series values.
2. Determine if the pod is exhibiting resource starvation (e.g., memory usage spiking dangerously close to typical limits).
3. If resource starvation is detected, you must autonomously invoke the 'patch_pod_limits' tool.
4. You must calculate and supply the new CPU and memory arguments based on the severity of the spike.
5. If the metrics are stable, invoke no tools and output 'HALT'.

Do not ask for human permission. Execute the required tool strictly based on the telemetry evidence.
"""
    
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this live SigNoz incident data: {telemetry_context}"}
        ],
        tools=tools_schema,
        tool_choice="auto"
    )
    
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


import time

def query_signoz_telemetry() -> str:
    """
    Fetches raw telemetry directly from the SigNoz API.
    """
    logger.info("Polling SigNoz API for live telemetry...")
    
    signoz_url = os.getenv("SIGNOZ_API_URL", "http://localhost:3301/api/v1/query_range")
    # PromQL query to check if memory usage is approaching limits for the specific deployment
    promql_query = 'container_memory_usage_bytes{namespace="oppe2-app", pod=~"fraud-detection-api-.*"}'
    
    # Query the last 5 minutes of data
    end_time = int(time.time())
    start_time = end_time - 300
    
    params = {
        "query": promql_query,
        "start": start_time,
        "end": end_time,
        "step": "60s"
    }

    try:
        signoz_token = os.getenv("SIGNOZ_API_TOKEN", "")
        headers = {}
        if signoz_token:
            headers["Authorization"] = f"Bearer {signoz_token}"
            
        response = requests.get(signoz_url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # If data is returned, pass the raw payload to the LLM for analysis
        if data.get('status') == 'success' and data.get('data', {}).get('result'):
            logger.warning("🚨 Anomalous telemetry detected via SigNoz API!")
            return json.dumps({
                "source": "SigNoz_PromQL",
                "metric_data": data['data']['result'],
                "cluster_namespace": "oppe2-app"
            })
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            logger.warning("🚨 SigNoz API 401. Simulating anomalous telemetry for demo purposes...")
            return json.dumps({
                "source": "SigNoz_PromQL",
                "metric_data": [{"metric": {"namespace": "oppe2-app", "pod": "fraud-detection-api-xxxxx"}, "values": [[1784515103, "107000000"]]}],
                "cluster_namespace": "oppe2-app"
            })
        logger.error(f"Failed to query SigNoz API: {e}")
    except Exception as e:
        logger.error(f"Failed to query SigNoz API: {e}")
        
    return json.dumps({"status": "OK"})

def main_loop():
    logger.info("Starting Intelligent Remediation Loop...")
    while True:
        try:
            mcp_data = query_signoz_telemetry()
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
