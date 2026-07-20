# Incident Simulation Playbook

This playbook provides step-by-step instructions to trigger real incidents in your cluster and observe the SRE Copilot autonomously detect, diagnose, and remediate them.

> **Prerequisites**: The SRE Copilot and `fraud-detection-api` must be deployed and running. See the [Setup Guide](SETUP.md).

---

## Scenario 1: Memory Starvation (OOMKill)

**Goal**: Trigger resource starvation by crushing memory limits, watch the agent detect it and generate a Pull Request to fix it.

### Step 1: Verify Current State

```bash
kubectl get deploy fraud-detection-api -n oppe2-app \
  -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'
```

Expected: `{"cpu":"500m","memory":"256Mi"}` (or similar healthy values)

### Step 2: Inject the Fault

Dramatically lower the memory limit to force a memory starvation scenario:

```bash
kubectl patch deploy fraud-detection-api -n oppe2-app \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"fraud-api-container","resources":{"limits":{"memory":"100Mi"},"requests":{"memory":"100Mi"}}}]}}}}'
```

### Step 3: Watch the Agent

```bash
kubectl logs -f -l app=sre-copilot -n oppe2-app
```

Within 10–30 seconds, you should see:

```
INFO  - Polling SigNoz API for live telemetry...
WARNING - 🚨 Anomalous telemetry detected via SigNoz API!
INFO  - Starting Intelligent Diagnostic & Remediation Loop...
INFO  - Invoking target tool: patch_pod_limits with arguments: {'name': 'fraud-detection-api', 'namespace': 'oppe2-app', 'cpu': '2000m', 'memory': '2Gi'}
INFO  - [TIER 2] Destructive action proposed. PR opened for Human Review: https://github.com/...
```

### Step 4: Review the Pull Request

Open the PR link from the logs. You'll see:

- **Title**: `[URGENT] AI Remediation Proposal: OOMKilled`
- **Body**: The LLM's reasoning for why it chose `patch_pod_limits` and the specific CPU/memory values it computed.

### Step 5: Merge and Observe Argo CD Sync

Merge the PR on GitHub. If Argo CD is configured, it will automatically sync the new manifest to the cluster, restoring healthy resource limits.

Verify the fix was applied:

```bash
kubectl get deploy fraud-detection-api -n oppe2-app \
  -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'
```

Expected: `{"cpu":"2000m","memory":"2Gi"}` (or the values the LLM computed)

### Step 6: Clean Up

Restore original limits:

```bash
kubectl patch deploy fraud-detection-api -n oppe2-app \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"fraud-api-container","resources":{"limits":{"cpu":"500m","memory":"256Mi"},"requests":{"cpu":"500m","memory":"256Mi"}}}]}}}}'
```

---

## Scenario 2: Traffic Spike (Horizontal Scaling)

**Goal**: Simulate high request volume to trigger the agent to invoke `scale_deployment`.

> **Note**: This scenario requires the SigNoz PromQL API to return QPS/latency metrics that indicate a traffic spike. If running in demo mode (SigNoz API 401 fallback), the mock payload simulates memory starvation by default. To test this scenario fully, ensure SigNoz is properly collecting HTTP metrics from the target workload.

### Trigger

Generate sustained load against the fraud-detection-api:

```bash
# Install a load generator if you don't have one
kubectl run load-generator --image=busybox -n oppe2-app --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://fraud-detection-api:8001/predict; done"
```

### Expected Behavior

The agent should detect elevated QPS metrics and invoke `scale_deployment` to increase replica count. Since `scale_deployment` is a **Tier 1** action, it pushes directly to `main` without creating a PR.

### Clean Up

```bash
kubectl delete pod load-generator -n oppe2-app
```

---

## Scenario 3: Safety Interlock (HALT)

**Goal**: Verify that the agent correctly refuses to act when it encounters an incident outside its toolset.

### How It Works

The safety interlock is enforced by the LLM's system prompt. If the telemetry indicates an issue that doesn't match any of the 5 registered tools (e.g., database connection pool drops, expired certificates, network partitions), the LLM is instructed to:

1. **NOT** invoke any tool.
2. Output `HALT_INSUFFICIENT_TOOLS` with an explanation.

The agent detects this keyword and logs a warning:

```
🚨 [PHASE 2 GUARDRAIL BREACHED] - Agent lacks the necessary tools to safely cure this incident.
```

### Trigger (Manual Test)

To test this, you can temporarily modify the telemetry payload to simulate an unknown incident:

```python
# In query_signoz_telemetry(), return a payload the LLM won't recognize:
return json.dumps({
    "source": "SigNoz_PromQL",
    "metric_data": [{"metric": {"error_type": "TLS_CERT_EXPIRED"}, "values": [[1721469600, "1"]]}],
    "cluster_namespace": "oppe2-app"
})
```

### Expected Behavior

The LLM should output `HALT_INSUFFICIENT_TOOLS` and the agent should log the guardrail breach without invoking any tool or pushing any code.

---

## Understanding the PR Body

Every Tier 2 Pull Request generated by the agent follows this structure:

```markdown
### AI Remediation Proposal

**Incident:** OOMKilled
**Proposed Action:** patch_pod_limits
**Arguments:** {
  "name": "fraud-detection-api",
  "namespace": "oppe2-app",
  "cpu": "2000m",
  "memory": "2Gi"
}

### LLM Reasoning

Detected memory usage spiking near 1Gi limit. The time-series data shows
a consistent upward trend over the last 5 minutes, approaching the configured
memory ceiling. Patching pod limits to 2000m CPU and 2Gi Memory to prevent
imminent OOMKill events.
```

Key sections:
- **Incident**: The classified incident type.
- **Proposed Action**: The exact tool the LLM chose.
- **Arguments**: The computed parameters (these are NOT hardcoded — the LLM calculates them based on the severity of the metrics).
- **LLM Reasoning**: The model's natural-language explanation, providing full auditability.

---

## Quick Reference: kubectl Commands

| Command | Purpose |
|---|---|
| `kubectl logs -f -l app=sre-copilot -n oppe2-app` | Stream agent logs in real-time |
| `kubectl get pods -n oppe2-app` | Check pod status |
| `kubectl get deploy fraud-detection-api -n oppe2-app -o yaml` | Inspect current deployment state |
| `kubectl delete pod -l app=sre-copilot -n oppe2-app` | Force restart the agent pod |
| `kubectl describe pod <pod-name> -n oppe2-app` | Debug pod scheduling or crash issues |
