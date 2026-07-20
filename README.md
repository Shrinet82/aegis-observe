# Aegis Observe Command Center

This repository contains the core components of the Aegis Observe AI SRE setup. It is designed to work seamlessly with [SigNoz](https://signoz.io/) to provide deep Kubernetes observability combined with an autonomous AI remediation engine.

## Components

1. **Dashboards (`*.json`)**:
   - `k8s_overview_dashboard.json`: An official, battle-tested Kubernetes cluster metrics dashboard providing deep visibility into node health, pod phases, CPU/Memory saturation, and network IO.
   - `aegis_dashboard.json`: A custom Copilot Audit Stream dashboard used to monitor the live decision-making and GitOps actions proposed by the SRE AI agent.
2. **SRE Copilot (`sre-copilot/agent.py`)**: 
   The core AI SRE Agent built with Azure OpenAI. It natively polls the SigNoz PromQL API to detect anomalies (e.g., OOMKills, traffic spikes, memory starvation) and automatically orchestrates remediation via GitOps.
3. **Manifests (`manifests/`)**:
   Ready-to-use Kubernetes deployment YAMLs to launch the SRE Copilot and a dummy `fraud-detection-api` pod for incident simulation.

## How to Deploy and Experiment

### 1. Setup Secrets
Update the `manifests/secrets-template.yaml` with your actual API keys and apply it to your cluster:
```bash
kubectl apply -f manifests/secrets-template.yaml
```

### 2. Deploy the SRE Copilot
Create the ConfigMap holding the agent script, then deploy the agent:
```bash
kubectl create configmap sre-copilot-code \
  --from-file=agent.py=sre-copilot/agent.py \
  --from-file=requirements.txt=sre-copilot/requirements.txt \
  -n oppe2-app

kubectl apply -f manifests/sre-copilot-deployment.yaml
```

### 3. Trigger an Incident (Simulation)
Deploy the `fraud-detection-api` app:
```bash
kubectl apply -f manifests/fraud-detection-api.yaml
```
To trigger a resource starvation incident, dramatically lower its memory limits in the manifest or via `kubectl patch`, and watch the `sre-copilot` pod logs. The agent will detect the anomaly, generate a GitOps Pull Request to fix the limits, and (once merged) Argo CD will restore the cluster!

## Related Repositories
For the full end-to-end microservices pipeline implementation, check out the companion fork at [MLOPS-Full-Data-Pipeline](https://github.com/Shrinet82/MLOPS-Full-Data-Pipeline).
