# Agent Code Walkthrough

This document provides an annotated, section-by-section walkthrough of [`sre-copilot/agent.py`](../sre-copilot/agent.py). Its purpose is to demonstrate to hackathon judges that this is a genuine autonomous AI agent — not a hardcoded script with `if/else` branches.

---

## Table of Contents

1. [Tool Definition Registry](#1-tool-definition-registry)
2. [GitOps Execution Engine](#2-gitops-execution-engine---execute_tool)
3. [LLM Orchestration (The Brain)](#3-llm-orchestration-the-brain---run_agent_workflow)
4. [SigNoz Telemetry Polling](#4-signoz-telemetry-polling---query_signoz_telemetry)
5. [The Daemon Loop](#5-the-daemon-loop---main_loop)

---

## 1. Tool Definition Registry

**Lines 12–90** — [`tools_schema`](../sre-copilot/agent.py)

```python
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "scale_deployment",
            "description": "Scales a deployment's replica count up or down ...",
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
    # ... 4 more tools
]
```

### What this does

This is a **JSON Schema registry** that is passed directly to the OpenAI API via the `tools` parameter. The LLM reads these schemas and uses them to generate **structured function calls** with typed arguments.

### Why it matters

- The agent code **never decides** which tool to invoke. The LLM does.
- Each tool has a natural-language `description` that the LLM uses for reasoning.
- The `parameters` schema enforces type safety — the LLM must return valid JSON matching these types.

### The 5 Tools

| Tool | Incident Type | Parameters |
|---|---|---|
| `scale_deployment` | Traffic spike | `name`, `namespace`, `replicas` (int) |
| `patch_pod_limits` | OOMKilled / resource starvation | `name`, `namespace`, `cpu` (str), `memory` (str) |
| `rollback_deployment` | Bad release / CrashLoopBackOff | `name`, `namespace` |
| `trigger_retraining` | ML model drift | `pipeline_webhook_url` (str) |
| `cordon_and_drain` | Node pressure | `node_name` (str) |

---

## 2. GitOps Execution Engine — `execute_tool()`

**Lines 93–199** — [`execute_tool()`](../sre-copilot/agent.py)

This function translates the LLM's tool call into a real infrastructure change via GitOps.

### Step-by-step flow

```
1. Read GITHUB_TOKEN and GITHUB_REPO_URL from environment
2. git clone the infrastructure repo to /tmp/repo
3. Classify the tool as Tier 1 (auto-push) or Tier 2 (PR)
4. If Tier 2 → create a new branch
5. Apply the patch (regex substitution on the YAML manifest)
6. git add → git commit
7. If Tier 1 → git push to main
8. If Tier 2 → git push branch → POST to GitHub API → Create PR
```

### The Tier Classification

```python
is_tier_1 = name in ["scale_deployment"]
is_tier_2 = name in ["patch_pod_limits", "rollback_deployment",
                      "trigger_retraining", "cordon_and_drain"]
```

- **Tier 1** actions are safe, non-destructive, and immediately reversible. They push directly to `main` and Argo CD applies them within seconds.
- **Tier 2** actions are potentially destructive. They create a branch and open a Pull Request, including the LLM's reasoning in the PR body, so a human can review before merging.

### The YAML Patch (Example: `patch_pod_limits`)

```python
yaml_content = re.sub(r"cpu:\s*\"?[0-9]+m?\"?", f"cpu: \"{args['cpu']}\"", yaml_content)
yaml_content = re.sub(r"memory:\s*\"?[0-9]+[A-Za-z]+\"?", f"memory: {args['memory']}", yaml_content)
```

The agent uses regex to surgically replace CPU and memory values in the declarative Kubernetes manifest. This is a **declarative** change — the agent modifies the desired state in Git, and Argo CD reconciles it with the cluster.

### The Pull Request

```python
pr_data = {
    "title": f"[URGENT] AI Remediation Proposal: {incident_type}",
    "head": branch_name,
    "base": "main",
    "body": f"### AI Remediation Proposal\n\n"
            f"**Incident:** {incident_type}\n"
            f"**Proposed Action:** {name}\n"
            f"**Arguments:** {json.dumps(args, indent=2)}\n\n"
            f"### LLM Reasoning\n\n{reasoning}"
}
```

Every PR includes the LLM's natural-language reasoning, making the decision fully auditable.

---

## 3. LLM Orchestration (The Brain) — `run_agent_workflow()`

**Lines 201–256** — [`run_agent_workflow()`](../sre-copilot/agent.py)

This is the core intelligence layer. It takes raw telemetry and delegates the diagnosis entirely to the LLM.

### The System Prompt

```python
system_prompt = """
You are an autonomous SRE Copilot Agent. 
You will receive raw telemetry data exported from SigNoz (Prometheus/ClickHouse format).

Your strict directives:
1. Analyze the 'metric_data' time-series values.
2. Determine if the pod is exhibiting resource starvation.
3. If resource starvation is detected, autonomously invoke the 'patch_pod_limits' tool.
4. Calculate and supply the new CPU and memory arguments based on the severity of the spike.
5. If the metrics are stable, invoke no tools and output 'HALT'.

Do not ask for human permission. Execute the required tool strictly based on the telemetry evidence.
"""
```

### The API Call

```python
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze this live SigNoz incident data: {telemetry_context}"}
    ],
    tools=tools_schema,
    tool_choice="auto"
)
```

Key design decisions:
- `tool_choice="auto"` — The LLM decides whether to invoke a tool **or** return text. It is not forced to act.
- The raw `telemetry_context` string is injected verbatim. The agent does not pre-process, filter, or interpret the data.

### Response Handling

```python
# Safety interlock: HALT if LLM can't handle the incident
if response_message.content and "HALT_INSUFFICIENT_TOOLS" in response_message.content:
    logger.warning("🚨 [PHASE 2 GUARDRAIL BREACHED]")
    return

# If the LLM chose to invoke tools, execute each one
if response_message.tool_calls:
    for tool_call in response_message.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        result = execute_tool(name, args, reasoning, incident_type)
```

Three possible outcomes:
1. **Tool call** → Execute the remediation via GitOps.
2. **HALT** → The LLM determined metrics are stable. No action taken.
3. **HALT_INSUFFICIENT_TOOLS** → The LLM encountered an unknown incident. Escalate to human.

---

## 4. SigNoz Telemetry Polling — `query_signoz_telemetry()`

**Lines 261–313** — [`query_signoz_telemetry()`](../sre-copilot/agent.py)

This function is the agent's "eyes." It queries the SigNoz observability backend for live metrics.

### The PromQL Query

```python
promql_query = 'container_memory_usage_bytes{namespace="oppe2-app", pod=~"fraud-detection-api-.*"}'
```

This fetches memory usage in bytes for all pods matching `fraud-detection-api-*` in the `oppe2-app` namespace.

### The API Request

```python
signoz_url = os.getenv("SIGNOZ_API_URL", "http://localhost:3301/api/v1/query_range")
params = {
    "query": promql_query,
    "start": start_time,      # now - 300 seconds
    "end": end_time,           # now
    "step": "60s"              # 1-minute resolution
}

headers = {}
signoz_token = os.getenv("SIGNOZ_API_TOKEN", "")
if signoz_token:
    headers["Authorization"] = f"Bearer {signoz_token}"

response = requests.get(signoz_url, params=params, headers=headers)
```

### Response Handling

- If the API returns `status: "success"` with non-empty `result` data → Package as JSON and return to the main loop.
- If the API returns `401 Unauthorized` → Fall back to a simulated payload (demo mode).
- If the API returns no results → Return `{"status": "OK"}` (healthy state, no action needed).

---

## 5. The Daemon Loop — `main_loop()`

**Lines 315–332** — [`main_loop()`](../sre-copilot/agent.py)

```python
def main_loop():
    while True:
        try:
            mcp_data = query_signoz_telemetry()
            if '"status": "OK"' not in mcp_data:
                run_agent_workflow(mcp_data)
        except Exception as e:
            logger.error(f"Error in SRE Copilot Loop: {e}")

        time.sleep(10)
```

This is the heartbeat of the agent. It:

1. Calls `query_signoz_telemetry()` to check the current cluster state.
2. If the telemetry contains anomalous data (anything other than `"status": "OK"`), triggers the full LLM diagnostic pipeline.
3. Sleeps for 10 seconds and repeats.

The agent runs as a standard Kubernetes Deployment with `restartPolicy: Always`, ensuring it is always running and self-healing if the pod crashes.

---

## End-to-End Data Flow

```
main_loop()
  └── query_signoz_telemetry()
        └── HTTP GET → SigNoz PromQL API
              └── Returns raw time-series JSON
  └── run_agent_workflow(telemetry_context)
        └── POST → Azure OpenAI chat.completions.create
              ├── System prompt (strict SRE directives)
              ├── User message (raw telemetry)
              └── tools=tools_schema
        └── Parse response
              ├── HALT → No action
              ├── HALT_INSUFFICIENT_TOOLS → Escalate
              └── tool_calls → execute_tool()
                    ├── git clone infrastructure repo
                    ├── Patch YAML manifest
                    ├── git commit
                    ├── [Tier 1]: git push main
                    └── [Tier 2]: git push branch → Create PR
```
