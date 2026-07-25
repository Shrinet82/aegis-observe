# 🎬 Aegis-Observe: Official Demo Video Script & Recording Guide

**Target Duration**: ~2 minutes 50 seconds  
**Track**: Agents of SigNoz · Track 1 (AI & Agent Observability)  
**Video Goal**: High-impact demonstration of rule-based SigNoz MCP telemetry signal detection, LLM remediation tool selection, interactive Slack authorization, GitOps remediation, and 5-pillar self-observability.

---

## ⏱️ Scene-by-Scene Production Breakdown

### 1. Hook [0:00–0:12] — Cold Open on the Money Shot
* **Voiceover (VO)**:  
  *"This is an AI SRE copilot that catches a production incident, proposes a fix, waits for my approval in Slack, and ships it through GitOps — all observable inside SigNoz."*
* **On-Screen Action**:  
  Fast montage: Interactive Slack proposal card appears ➔ Cursor clicks **`⚡ Approve & Push Commit`** ➔ GitHub commit/PR merged ➔ SigNoz metric graph recovering to green baseline.

---

### 2. The Problem & Vision [0:12–0:35] — Why Aegis-Observe Exists
* **Voiceover (VO)**:  
  *"AI and MLOps systems fail in messy ways — OOM kills, 504 spikes, model drift. Dashboards tell you what broke. Aegis-Observe takes the next step: it decides the fix and executes it, with a human in the loop."*
* **On-Screen Action**:  
  Show the System Architecture Diagram from `README.md` (`Fraud Detection API` ➔ `SigNoz MCP` ➔ `Aegis SRE Agent` ➔ `Slack Socket Mode` ➔ `GitOps / ArgoCD`).

---

### 3. How It Works [0:35–0:55] — 30-Second Architecture
* **Voiceover (VO)**:  
  *"The agent polls SigNoz over the MCP server for log signatures and traces, plus Kubernetes status. When it detects an incident, GPT-5-mini selects the exact remediation tool — scale, patch limits, rollback, retrain, or cordon. Nothing runs without approval."*
* **On-Screen Action**:  
  Quick screen view of `sre-copilot/mcp_client.py` log search queries (`signoz_search_logs`), panning across the tool definitions in `sre-copilot/agent.py`.

---

### 4. LIVE DEMO [0:55–2:05] — The Core Walkthrough
* **Beat 1 (0:55–1:10)** — **Trigger Incident**:
  * **VO**: *"I'll trigger a memory incident on the fraud API."*
  * **Screen**: Execute incident injection command; show `kubectl` pod status going into memory stress / `OOMKilled` or 504 errors in SigNoz log stream.
* **Beat 2 (1:10–1:25)** — **Detection & Proposal**:
  * **VO**: *"The agent detects it via SigNoz MCP, and the LLM proposes patching the memory limits."*
  * **Screen**: Terminal agent diagnostic log ➔ Slack interactive Block Kit proposal card pops up (showing LLM reasoning breakdown, SigNoz trace deep links, and the 3 buttons).
* **Beat 3 (1:25–1:40)** — **Human Approval**:
  * **VO**: *"I approve it."*
  * **Screen**: Cursor clicks **`⚡ Approve & Push Commit`** ➔ Card updates to `✅ APPROVED & PUSHED TO GITOPS MAIN`.
* **Beat 4 (1:40–1:55)** — **GitOps Sync**:
  * **VO**: *"That commits to the GitOps repo; ArgoCD syncs it to the cluster."*
  * **Screen**: Show GitHub commit on `Shrinet82/flagship-gitops` ➔ ArgoCD UI syncing green status.
* **Beat 5 (1:55–2:05)** — **Verification**:
  * **VO**: *"And the agent verifies recovery."*
  * **Screen**: SigNoz metric graph stabilizing to healthy ➔ Slack follow-up notification: `✅ REMEDIATION VERIFIED`.

---

### 5. The SigNoz Differentiator [2:05–2:35] — Observing the Observer & 5 Pillars
* **Voiceover (VO)**:  
  *"Because it's an AI agent, I observe the agent itself: its LLM token cost and every tool decision are traced into SigNoz. Plus alert rules on 504s and token runaway — so this uses all five pillars: traces, metrics, logs, dashboards, and alerts."*
* **On-Screen Action**:  
  Navigate across the **SigNoz SRE Agent Metrics Dashboard** (`sre_agent_dashboard.json`) showing real-time `gen_ai.usage.prompt_tokens` spline graph and `execute_tool` trace spans, then flash the **SigNoz Alerts** tab showing `llm_token_usage.json` and `fraud_api_504.json`.

---

### 6. Close [2:35–2:50] — Summary & Title Card
* **Voiceover (VO)**:  
  *"Aegis-Observe turns SigNoz from a passive dashboard into an active, human-authorized operator. Detect, reason, approve, remediate, verify — fully observable."*
* **On-Screen Action**:  
  Title card: **Aegis-Observe** | `https://github.com/Shrinet82/aegis-observe` | **Agents of SigNoz · Track 1**.

---

## 🛠️ Recording Setup Checklist

1. **SigNoz UI**: Port-forwarded on `http://localhost:8080` (Dashboards tab open to `SigNoz SRE Copilot Agent Metrics`).
2. **Slack Workspace**: Channel open showing Socket Mode bot notifications.
3. **Terminal**: Ready with incident trigger script / `kubectl get pods -n oppe2-app -w`.
4. **GitHub Repo**: `https://github.com/Shrinet82/flagship-gitops` tab open to view commits.
