# Aegis Observe Command Center

This repository contains the core components of the Aegis Observe AI SRE setup. It is designed to work seamlessly with [SigNoz](https://signoz.io/) to provide deep Kubernetes observability combined with an autonomous AI remediation engine.

## Components

1. **`k8s_overview_dashboard.json`**: An official, battle-tested Kubernetes cluster metrics dashboard providing deep visibility into node health, pod phases, CPU/Memory saturation, and network IO.
2. **`aegis_dashboard.json`**: A custom Copilot Audit Stream dashboard used to monitor the live decision-making and GitOps actions proposed by the SRE AI agent.
3. **`sre-copilot/`**: The core AI SRE Agent (`agent.py`) built with GPT-4 (or GPT-4o-mini). It hooks directly into the SigNoz Model Context Protocol (MCP) telemetry streams to automatically detect anomalies (e.g., OOMKills, traffic spikes) and automatically orchestrate scaling, rollbacks, and node cordoning via GitOps pull requests.

## How to use

1. Import both `.json` files into your SigNoz instance via the **Dashboards > Import JSON** UI.
2. Deploy the `sre-copilot` as a background worker in your cluster (ensure you have provided the necessary `AZURE_OPENAI_API_KEY` and `GITHUB_TOKEN` environment variables).

For the full end-to-end microservices pipeline implementation, check out the companion fork at [MLOPS-Full-Data-Pipeline](https://github.com/Shrinet82/MLOPS-Full-Data-Pipeline).
