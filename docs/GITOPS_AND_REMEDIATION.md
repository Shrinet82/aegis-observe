# 🐙 GitOps Engine & Tiered Remediation Strategy

**Aegis-Observe** enforces a two-tier remediation model to ensure declarative infrastructure management, auditable version control, and human oversight.

---

## 🏛️ Tiered Remediation Overview

```mermaid
graph TD
    INCIDENT[Incident Detected & Evaluated by LLM] --> TIER_CHECK{Execution Mode?}
    
    TIER_CHECK -->|Tier 1 / Direct Commit| TIER1[Tier 1: Direct Main Push]
    TIER_CHECK -->|Tier 2 / PR Mode| TIER2[Tier 2: GitHub Pull Request]
    TIER_CHECK -->|Direct K8s Tool| K8S_DIRECT[K8s API Direct Exec]

    TIER1 -->|Clone Repo| CLONE1[Clone flagship-gitops Repo]
    CLONE1 -->|Update Manifest| UPDATE1[Patch manifests/mlops/deployment.yaml]
    UPDATE1 -->|Git Commit & Push| PUSH1[git push origin main]
    PUSH1 -->|ArgoCD Sync| ARGOCD[ArgoCD Automatically Syncs Cluster]

    TIER2 -->|Checkout Branch| BRANCH[git checkout -b sre-copilot-remediation-ts]
    BRANCH -->|Update Manifest| UPDATE2[Patch Target Manifest]
    UPDATE2 -->|Push Branch| PUSH2[git push origin sre-copilot-remediation-ts]
    PUSH2 -->|GitHub REST API| PR_CREATE[Create Pull Request for Review]

    K8S_DIRECT -->|Node Cordon & Drain| CORDON[kubectl cordon & drain]
```

---

## 🛡️ Remediation Tools & Execution Matrix

| Tool Name | Scope | Default Strategy | Trigger Conditions |
| :--- | :--- | :--- | :--- |
| `scale_deployment` | GitOps Manifest | Tier 1 (or PR override) | Traffic Spikes, 504 Gateway Timeouts, High Inference Latency |
| `patch_pod_limits` | GitOps Manifest | Tier 1 (or PR override) | Container Memory Starvation, OOMKilled events, CPU Throttling |
| `rollback_deployment` | GitOps Manifest | Tier 2 (PR Draft) | CrashLoopBackOff, ImagePullBackOff, Post-release error spikes |
| `trigger_retraining` | GitOps Job | Tier 2 (PR Draft) | ML Prediction Drift, Confidence metrics falling below 60% |
| `cordon_and_drain` | Direct K8s API | Direct Execution | Node DiskPressure, Hardware MemoryPressure |

---

## ⏱️ Cooldown & Safety Annotations

To prevent duplicate remediations or flapping:
* **Cooldown Period**: A 300-second (5-minute) cooldown is enforced per incident signature.
* **Kubernetes Annotations**: Cooldown timestamps are persisted directly as annotations on target deployment objects (`remediation.aegis.io/last-remediated`).

---

## 🖼️ Live GitHub Pull Request & GitOps Evidence

| GitHub Pull Request Created by Agent (#47) | GitHub Pull Request Merged into Main |
| :---: | :---: |
| ![GitHub PR Created](file:///home/shrinet82/Opensource/SigNoz/docs/assets/github_pr_open.png) | ![GitHub PR Merged](file:///home/shrinet82/Opensource/SigNoz/docs/assets/github_pr_merged.png) |

---

## 🔗 Related Documentation
- [README.md](file:///home/shrinet82/Opensource/SigNoz/README.md) — Main Project Overview & Quickstart
- [ARCHITECTURE.md](file:///home/shrinet82/Opensource/SigNoz/docs/ARCHITECTURE.md) — System Architecture
- [SLACK_UX_AND_HITL.md](file:///home/shrinet82/Opensource/SigNoz/docs/SLACK_UX_AND_HITL.md) — Interactive Slack UX & Circuit Breaker
- [DASHBOARDS_AND_OBSERVABILITY.md](file:///home/shrinet82/Opensource/SigNoz/docs/DASHBOARDS_AND_OBSERVABILITY.md) — SigNoz Dashboards Guide
