import json
import logging
import subprocess
import os
import time
import re
import requests
from opentelemetry import trace

from k8s_tools import cordon_and_drain_node

logger = logging.getLogger("sre-copilot.gitops")
tracer = trace.get_tracer("sre-copilot.gitops")

@tracer.start_as_current_span("execute_tool")
def execute_tool(name: str, args: dict, reasoning: str = "", incident_type: str = "Unknown Incident", mode: str = None) -> str:
    span = trace.get_current_span()
    span.set_attribute("tool.name", name)
    span.set_attribute("tool.args", json.dumps(args))
    if mode:
        span.set_attribute("tool.mode", mode)
    logger.info(f"Invoking target tool: {name} with arguments: {args} (mode={mode})")

    # Cordon and drain is an immediate infrastructure operation bypassing GitOps
    if name == "cordon_and_drain":
        node_name = args.get("node_name", "unknown")
        return cordon_and_drain_node(node_name)

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
        
        if mode == "tier1":
            is_tier_1 = True
            is_tier_2 = False
        elif mode == "tier2":
            is_tier_1 = False
            is_tier_2 = True
        else:
            is_tier_1 = name in ["scale_deployment", "patch_pod_limits"]
            is_tier_2 = name in ["rollback_deployment", "trigger_retraining"]
        
        if is_tier_2:
            branch_name = f"sre-copilot-remediation-{int(time.time())}"
            subprocess.run(f"git checkout -b {branch_name}", shell=True, cwd="/tmp/repo", check=True)
            
        if name == "scale_deployment":
            with open(target_file, 'r') as f:
                yaml_content = f.read()
            yaml_content = re.sub(r"replicas:\s*\d+", f"replicas: {args['replicas']}", yaml_content)
            with open(target_file, 'w') as f:
                f.write(yaml_content)
            commit_msg = f"[Auto-Remediation] Traffic Spike"
            
        elif name == "patch_pod_limits":
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
            timestamp = int(time.time())
            job_yaml = f"""apiVersion: batch/v1
kind: Job
metadata:
  name: ml-retrain-{timestamp}
  namespace: oppe2-app
spec:
  template:
    spec:
      containers:
      - name: retrainer
        image: fraud-app:local
        command: ["python", "train.py"]
      restartPolicy: Never
  backoffLimit: 2
"""
            job_file_path = f"/tmp/repo/manifests/mlops/job-retrain-{timestamp}.yaml"
            with open(job_file_path, "w") as f:
                f.write(job_yaml)
            commit_msg = f"[Tier 2 Proposal] Trigger Retraining Pipeline Job ml-retrain-{timestamp}"

        
        subprocess.run('git add .', shell=True, cwd="/tmp/repo", check=True)
        subprocess.run(f'git commit -m "{commit_msg}"', shell=True, cwd="/tmp/repo", check=True)
        
        if is_tier_1:
            subprocess.run('git push origin main', shell=True, cwd="/tmp/repo", check=True)
            logger.info("[TIER 1] Auto-remediation pushed to main.")
            return f"GitOps Success: {commit_msg}"
            
        elif is_tier_2:
            subprocess.run(f'git push origin {branch_name}', shell=True, cwd="/tmp/repo", check=True)
            
            import urllib.parse
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
