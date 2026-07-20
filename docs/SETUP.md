# Setup Guide

This guide walks you through deploying the full Aegis Observe stack from scratch — from a bare Kubernetes cluster to a running autonomous SRE agent.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Kubernetes cluster** | K3s, Minikube, EKS, GKE, or any conformant cluster. Tested on K3s. |
| **kubectl** | Configured and pointing to your cluster. |
| **Helm 3** | Required for installing SigNoz. |
| **Azure OpenAI access** | A deployed model (e.g., `gpt-5-mini`) with an API key and endpoint URL. |
| **GitHub account** | A Personal Access Token (PAT) with `repo` scope. |
| **A GitOps infrastructure repo** | A GitHub repository containing your Kubernetes manifests. The agent will push changes here. |

---

## Step 1: Install SigNoz

SigNoz is the observability backend that collects and stores metrics, traces, and logs from your cluster.

```bash
helm repo add signoz https://charts.signoz.io
helm repo update

kubectl create namespace signoz

helm install signoz signoz/signoz \
  --namespace signoz \
  --set otelCollector.enabled=true
```

Verify SigNoz is running:

```bash
kubectl get pods -n signoz
```

You should see pods for `signoz`, `clickhouse`, `zookeeper`, `otel-collector`, etc., all in `Running` state.

> **Note**: For detailed SigNoz installation options, see the [official docs](https://signoz.io/docs/install/kubernetes/).

---

## Step 2: Create the Application Namespace

```bash
kubectl create namespace oppe2-app
```

---

## Step 3: Create Kubernetes Secrets

The SRE Copilot requires three secrets to operate. Edit `manifests/secrets-template.yaml` with your real credentials:

```yaml
# manifests/secrets-template.yaml
apiVersion: v1
kind: Secret
metadata:
  name: azure-ai-secret
  namespace: oppe2-app
type: Opaque
stringData:
  api-key: "YOUR_AZURE_OPENAI_API_KEY_HERE"    # ← Replace this
---
apiVersion: v1
kind: Secret
metadata:
  name: git-credentials
  namespace: oppe2-app
type: Opaque
stringData:
  github-token: "YOUR_GITHUB_PAT_HERE"          # ← Replace this
---
apiVersion: v1
kind: Secret
metadata:
  name: signoz-auth-secret
  namespace: oppe2-app
type: Opaque
stringData:
  token: "YOUR_SIGNOZ_API_TOKEN_HERE"            # ← Replace this
```

Apply the secrets:

```bash
kubectl apply -f manifests/secrets-template.yaml
```

---

## Step 4: Create the Service Account

The SRE Copilot pod needs a service account with permissions to query the SigNoz API within the cluster:

```bash
kubectl create serviceaccount telemetry-access -n oppe2-app
```

---

## Step 5: Deploy the SRE Copilot

First, create the ConfigMap that mounts the agent code into the pod:

```bash
kubectl create configmap sre-copilot-code \
  --from-file=agent.py=sre-copilot/agent.py \
  --from-file=requirements.txt=sre-copilot/requirements.txt \
  -n oppe2-app
```

Then deploy the agent:

```bash
kubectl apply -f manifests/sre-copilot-deployment.yaml
```

---

## Step 6: Deploy the Target Workload

This deploys a sample `fraud-detection-api` application that the SRE Copilot monitors:

```bash
kubectl apply -f manifests/fraud-detection-api.yaml
```

---

## Step 7: Import SigNoz Dashboards

1. Open the SigNoz UI (typically at `http://<node-ip>:3301`).
2. Navigate to **Dashboards** → **Import**.
3. Upload `k8s_overview_dashboard.json` for cluster-wide metrics.
4. Upload `aegis_dashboard.json` for the Copilot Audit Stream.

---

## Step 8: Verify the Agent

Check the agent logs to confirm it's polling the SigNoz API:

```bash
kubectl logs -f -l app=sre-copilot -n oppe2-app
```

Expected output:

```
2026-07-20 02:43:23 - sre-copilot - INFO - Starting Intelligent Remediation Loop...
2026-07-20 02:43:23 - sre-copilot - INFO - Polling SigNoz API for live telemetry...
2026-07-20 02:43:23 - sre-copilot - INFO - Sleeping for 10 seconds before next check...
```

If you see this, the agent is running and ready to detect incidents.

---

## Environment Variables Reference

The SRE Copilot deployment uses the following environment variables:

| Variable | Source | Description |
|---|---|---|
| `AZURE_OPENAI_API_KEY` | Secret: `azure-ai-secret` | API key for Azure OpenAI |
| `AZURE_OPENAI_ENDPOINT` | Deployment YAML | The Azure OpenAI resource endpoint URL |
| `GITHUB_TOKEN` | Secret: `git-credentials` | GitHub PAT with `repo` scope |
| `GITHUB_REPO_URL` | Deployment YAML | The infrastructure repo (e.g., `github.com/user/repo.git`) |
| `SIGNOZ_API_URL` | Deployment YAML | SigNoz query API endpoint (e.g., `http://signoz.signoz.svc.cluster.local:8080/api/v1/query_range`) |
| `SIGNOZ_API_TOKEN` | Secret: `signoz-auth-secret` | Bearer token for SigNoz API authentication |

---

## Optional: Install Argo CD

For the full GitOps loop (agent pushes PR → human merges → Argo CD syncs to cluster):

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

Then create an Argo CD Application pointing to your infrastructure repository's manifest directory. When the agent creates a PR and it's merged, Argo CD will automatically detect the change and sync the new desired state to the cluster.

> For detailed Argo CD setup, see the [official getting started guide](https://argo-cd.readthedocs.io/en/stable/getting_started/).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: Could not open requirements file` | ConfigMap missing `requirements.txt` | Recreate ConfigMap with both files (see Step 5) |
| `401 Unauthorized` on SigNoz API | Missing or invalid SigNoz token | Update the `signoz-auth-secret` with a valid token |
| `Missing GITHUB_TOKEN` error | Secret not created or wrong key name | Verify `git-credentials` secret exists with key `github-token` |
| Agent logs show `Sleeping` but never acts | No anomalous telemetry detected | Trigger an incident (see [Incident Playbook](INCIDENT_PLAYBOOK.md)) |
| PR creation fails | GitHub PAT lacks `repo` scope | Regenerate PAT with full `repo` permissions |
