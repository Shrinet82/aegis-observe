import os
import json
import logging
import threading
import requests
from opentelemetry import trace

logger = logging.getLogger("sre-copilot.slack")
tracer = trace.get_tracer("sre-copilot.slack")

# Slack Bolt & Socket Mode imports
try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    BOLT_AVAILABLE = True
except ImportError:
    BOLT_AVAILABLE = False
    logger.warning("slack_bolt library not installed. Interactive Socket Mode will be disabled.")

bolt_app = None
socket_handler = None

def init_socket_mode():
    """Initializes and starts Slack Socket Mode background thread if tokens are set."""
    global bolt_app, socket_handler
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not BOLT_AVAILABLE or not bot_token or not app_token:
        logger.warning("Slack Bot/App tokens missing or slack_bolt unavailable. Running in webhook-only mode.")
        return False

    try:
        bolt_app = App(token=bot_token)

        # Register interactive button action handlers
        @bolt_app.action("approve_commit")
        def handle_approve_commit(ack, body, respond, client):
            ack()
            user = body.get("user", {}).get("username", "Engineer")
            action_value = body["actions"][0]["value"]
            payload = json.loads(action_value)
            
            tool_name = payload.get("tool_name")
            tool_args = payload.get("tool_args", {})
            reasoning = payload.get("reasoning", "")
            incident_type = payload.get("incident_type", "Unknown Anomaly")
            target_pod = payload.get("target_pod", "fraud-detection-api")
            trace_id = payload.get("trace_id", "N/A")

            incident_key = f"{target_pod}:{incident_type}"
            logger.info(f"⚡ [SLACK INTERACTIVE] Approved by @{user}: {tool_name} {tool_args} (key={incident_key})")

            # Import gitops lazily to avoid circular import
            from gitops import execute_tool
            with tracer.start_as_current_span("slack_approval_tier1") as span:
                span.set_attribute("slack.user", user)
                span.set_attribute("trace_id", trace_id)
                res = execute_tool(tool_name, tool_args, reasoning, incident_type, mode="tier1")

            # Release PENDING_INCIDENTS lock and record ACTIVE_REMEDIATION for verification loop
            try:
                import time, agent
                agent.PENDING_INCIDENTS.discard(incident_key)
                agent.ACTIVE_REMEDIATIONS[incident_type] = {"time": time.time(), "tools": [tool_name]}
                logger.info(f"🔓 Released PENDING_INCIDENTS lock for '{incident_key}' after approval.")
            except Exception as e:
                logger.warning(f"Could not update agent state: {e}")

            respond(
                replace_original=True,
                blocks=[
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"✅ APPROVED & PUSHED: {incident_type}", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚡ *Action Authorized by @{user}*\n\n*Applied Action:* `{tool_name}`\n*GitOps Status:* {res}\n*Target Branch:* `main`"
                        }
                    },
                    {"type": "divider"},
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "🤖 *Aegis SRE Copilot* | Tier-1 Commit Pushed to GitOps Repo"}]
                    }
                ]
            )

        @bolt_app.action("create_pr")
        def handle_create_pr(ack, body, respond, client):
            ack()
            user = body.get("user", {}).get("username", "Engineer")
            action_value = body["actions"][0]["value"]
            payload = json.loads(action_value)

            tool_name = payload.get("tool_name")
            tool_args = payload.get("tool_args", {})
            reasoning = payload.get("reasoning", "")
            incident_type = payload.get("incident_type", "Unknown Anomaly")
            target_pod = payload.get("target_pod", "fraud-detection-api")
            trace_id = payload.get("trace_id", "N/A")

            incident_key = f"{target_pod}:{incident_type}"
            logger.info(f"📝 [SLACK INTERACTIVE] PR requested by @{user}: {tool_name} {tool_args} (key={incident_key})")

            from gitops import execute_tool
            with tracer.start_as_current_span("slack_approval_tier2") as span:
                span.set_attribute("slack.user", user)
                span.set_attribute("trace_id", trace_id)
                res = execute_tool(tool_name, tool_args, reasoning, incident_type, mode="tier2")

            # Release PENDING_INCIDENTS lock
            try:
                import agent
                agent.PENDING_INCIDENTS.discard(incident_key)
                logger.info(f"🔓 Released PENDING_INCIDENTS lock for '{incident_key}' after PR creation.")
            except Exception as e:
                logger.warning(f"Could not update agent state: {e}")

            respond(
                replace_original=True,
                blocks=[
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"📝 GITHUB PR OPENED: {incident_type}", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"📝 *PR Requested by @{user}*\n\n*Proposed Action:* `{tool_name}`\n*GitHub Status:* {res}"
                        }
                    },
                    {"type": "divider"},
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "🤖 *Aegis SRE Copilot* | Tier-2 Pull Request Drafted for Review"}]
                    }
                ]
            )

        @bolt_app.action("reject_plan")
        def handle_reject_plan(ack, body, respond, client):
            ack()
            user = body.get("user", {}).get("username", "Engineer")
            action_value = body["actions"][0]["value"]
            payload = json.loads(action_value)
            incident_type = payload.get("incident_type", "Unknown Anomaly")
            target_pod = payload.get("target_pod", "fraud-detection-api")

            incident_key = f"{target_pod}:{incident_type}"
            logger.info(f"✖ [SLACK INTERACTIVE] Rejected by @{user}: {incident_type} (key={incident_key})")

            try:
                import agent
                agent.PENDING_INCIDENTS.discard(incident_key)
                if incident_type in agent.ACTIVE_REMEDIATIONS:
                    del agent.ACTIVE_REMEDIATIONS[incident_type]
                logger.info(f"🔓 Released PENDING_INCIDENTS lock for '{incident_key}' after plan rejection.")
            except Exception as e:
                logger.warning(f"Could not clear agent state: {e}")

            respond(
                replace_original=True,
                blocks=[
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"✖ REMEDIATION PLAN REJECTED: {incident_type}", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🚫 *Plan Rejected by @{user}*\n\nNo infrastructure or GitOps changes were applied. Repository remains pristine."
                        }
                    },
                    {"type": "divider"},
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "🤖 *Aegis SRE Copilot* | Action Cancelled by Human Engineer"}]
                    }
                ]
            )

        handler = SocketModeHandler(bolt_app, app_token)
        t = threading.Thread(target=handler.start, daemon=True)
        t.start()
        logger.info("⚡ Slack Socket Mode handler started successfully in background thread.")
        return True
    except Exception as e:
        logger.error(f"Failed to start Slack Socket Mode: {e}")
        return False


def send_slack_message(message: str = None, blocks: list = None, webhook_url: str = None) -> bool:
    """Sends a text message or a rich Block Kit JSON payload to Slack."""
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
    bot_token = os.getenv("SLACK_BOT_TOKEN")

    # If Bot token is set and bolt_app is initialized, send via WebClient API
    if bolt_app and bolt_app.client:
        try:
            channel_id = os.getenv("SLACK_CHANNEL_ID", "C0BJWGLJMQB")  # default or fallback channel
            payload = {"channel": channel_id}
            if blocks:
                payload["blocks"] = blocks
            if message:
                payload["text"] = message
            bolt_app.client.chat_postMessage(**payload)
            logger.info("Successfully dispatched Slack message via Bot WebClient API.")
            return True
        except Exception as e:
            logger.warning(f"Bot WebClient send failed, falling back to Webhook: {e}")

    if not url:
        logger.warning("SLACK_WEBHOOK_URL is not set. Skipping Slack notification.")
        return False

    payload = {}
    if blocks:
        payload["blocks"] = blocks
        if message:
            payload["text"] = message
    else:
        payload["text"] = message or "SRE Copilot Alert"

    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=5.0
        )
        response.raise_for_status()
        logger.info("Successfully dispatched Slack notification via Webhook.")
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


def build_interactive_proposal_blocks(
    incident_type: str,
    target_pod: str,
    namespace: str,
    reasoning: str,
    tool_name: str,
    tool_args: dict,
    trace_id: str = "N/A"
) -> list:
    """Builds the exact interactive Human-in-the-Loop Slack Block Kit UX card."""
    
    # Format proposed changes nicely
    param_changes = []
    for k, v in tool_args.items():
        if k not in ["name", "namespace"]:
            param_changes.append(f"*{k.upper()}:* `{v}`")
    remediation_str = "\n".join(param_changes) if param_changes else f"`{tool_name}` with {tool_args}"

    signoz_host = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080")
    signoz_dash_link = f"{signoz_host}/dashboard"
    trace_link = f"{signoz_host}/trace/{trace_id}" if trace_id != "N/A" else f"{signoz_host}/traces"

    # Embed complete action state into button value payload
    button_payload = json.dumps({
        "tool_name": tool_name,
        "tool_args": tool_args,
        "reasoning": reasoning,
        "incident_type": incident_type,
        "target_pod": target_pod,
        "namespace": namespace,
        "trace_id": trace_id
    })

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 [CRITICAL ALERT] {incident_type}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Target Workload:* `{target_pod}` ({namespace} namespace)"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🧠 *AI Diagnostic Reasoning:*\n{reasoning}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🛠️ *Proposed Remediation Plan (`{tool_name}`):*\n{remediation_str}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📊 <{signoz_dash_link}|*View Live SigNoz Metrics*> | 🔎 <{trace_link}|*View OTel Trace Details*>"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Action Required:* Do you approve this declarative manifest patch?"
            }
        },
        {
            "type": "actions",
            "block_id": "human_approval_block",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⚡ Approve & Push Commit", "emoji": True},
                    "style": "primary",
                    "action_id": "approve_commit",
                    "value": button_payload
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📝 Open GitHub PR Instead", "emoji": True},
                    "action_id": "create_pr",
                    "value": button_payload
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✖ Reject Plan", "emoji": True},
                    "style": "danger",
                    "action_id": "reject_plan",
                    "value": button_payload
                }
            ]
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "🤖 *Aegis SRE Copilot* | Interactive Human-in-the-Loop Gateway"}
            ]
        }
    ]
    return blocks


def build_incident_blocks(incident: dict) -> list:
    """Builds a rich Slack Block Kit layout for an incident detection event."""
    inc_name = incident.get("incident", "Unknown Incident")
    deployment = incident.get("deployment", "fraud-detection-api")
    namespace = incident.get("namespace", "oppe2-app")
    description = incident.get("description", "No description provided.")
    trace_id = incident.get("trace_id", "N/A")
    
    signoz_host = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080")
    trace_link = f"{signoz_host}/trace/{trace_id}" if trace_id != "N/A" else "N/A"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 SRE ALERT: {inc_name}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service / Deployment:*\n`{deployment}`"},
                {"type": "mrkdwn", "text": f"*Namespace:*\n`{namespace}`"},
                {"type": "mrkdwn", "text": "*Detection Source:*\nSigNoz MCP Telemetry"},
                {"type": "mrkdwn", "text": "*Severity:*\n🔴 High (Evaluating Solution)"}
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Telemetry Breakdown & Root Cause Context:*\n```{description}```"
            }
        }
    ]

    if trace_id != "N/A":
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔍 *SigNoz Trace Link:* <{trace_link}|View Active Trace in SigNoz UI>"
            }
        })

    blocks.extend([
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "🤖 *Aegis SRE Copilot* | Autonomous Diagnostic Engine Active"}
            ]
        }
    ])
    return blocks


def build_action_blocks(incident_name: str, tools: list, details: str = "") -> list:
    """Builds a rich Slack Block Kit layout for an automated remediation action."""
    tools_str = ", ".join([f"`{t}`" for t in tools])
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🤖 REMEDIATION EXECUTED: {incident_name}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Tools Triggered:*\n{tools_str}"},
                {"type": "mrkdwn", "text": "*Status:*\n⚙️ Executed & Monitoring Efficacy"}
            ]
        }
    ]

    if details:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Execution Summary / GitOps Details:*\n{details}"
            }
        })

    blocks.extend([
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "⏳ *Verification Loop:* Monitoring SigNoz MCP telemetry to verify recovery..."}
            ]
        }
    ])
    return blocks


def build_success_blocks(incident_name: str, tools: list) -> list:
    """Builds a rich Slack Block Kit layout for a successful verification event."""
    tools_str = ", ".join([f"`{t}`" for t in tools])
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"✅ REMEDIATION VERIFIED: {incident_name}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"The telemetry anomaly for `{incident_name}` has completely cleared in SigNoz. Service health restored to 100% nominal state.\n\n*Remediation Tools Used:* {tools_str}"
            }
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "🎉 *Aegis SRE Copilot* | Closed Incident Automatically"}
            ]
        }
    ]
