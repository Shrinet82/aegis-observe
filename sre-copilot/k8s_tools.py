import json
import logging
import subprocess
import time
from opentelemetry import trace

logger = logging.getLogger("sre-copilot.k8s")
tracer = trace.get_tracer("sre-copilot.k8s")

@tracer.start_as_current_span("check_k8s_health")
def run_k8s_checks() -> str:
    """Run Kubernetes API health checks. Returns incident JSON or OK."""
    span = trace.get_current_span()
    namespace = "oppe2-app"
    deployment = "fraud-detection-api"

    # --- Check 1: Pod-level anomalies (OOMKilled, CrashLoopBackOff, ImagePullBackOff) ---
    try:
        cmd = f"kubectl get pods -l app={deployment} -n {namespace} -o json"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        pods = json.loads(res.stdout).get("items", [])
        for pod in pods:
            pod_name = pod.get("metadata", {}).get("name", "unknown")
            statuses = pod.get("status", {}).get("containerStatuses", [])
            for status in statuses:
                state = status.get("state", {})
                last_state = status.get("lastState", {})

                # OOMKilled
                if state.get("terminated", {}).get("reason") == "OOMKilled" or \
                   last_state.get("terminated", {}).get("reason") == "OOMKilled":
                    span.set_attribute("incident.detected", True)
                    span.set_attribute("incident.type", "OOMKilled")
                    logger.warning("\U0001F6A8 Alert: OOMKilled detected in live telemetry!")
                    return json.dumps({
                        "incident": "OOMKilled",
                        "deployment": deployment,
                        "namespace": namespace,
                        "pod": pod_name,
                        "description": "Pod terminated due to memory starvation (OOMKilled). Critical resource exhaustion detected."
                    })

                # CrashLoopBackOff
                waiting = state.get("waiting", {})
                if waiting.get("reason") in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
                    reason = waiting["reason"]
                    span.set_attribute("incident.detected", True)
                    span.set_attribute("incident.type", reason)
                    logger.warning(f"\U0001F6A8 Alert: {reason} detected for pod {pod_name}!")
                    return json.dumps({
                        "incident": "Bad Release" if reason in ["ImagePullBackOff", "ErrImagePull"] else "CrashLoop",
                        "deployment": deployment,
                        "namespace": namespace,
                        "pod": pod_name,
                        "description": f"Pod {pod_name} is in {reason} state. Likely a bad release or configuration error."
                    })

            # Check restart count for silent crash loops
            for status in statuses:
                restart_count = status.get("restartCount", 0)
                if restart_count >= 5:
                    span.set_attribute("incident.detected", True)
                    span.set_attribute("incident.type", "ExcessiveRestarts")
                    logger.warning(f"\U0001F6A8 Alert: Pod {pod_name} has {restart_count} restarts!")
                    return json.dumps({
                        "incident": "CrashLoop",
                        "deployment": deployment,
                        "namespace": namespace,
                        "pod": pod_name,
                        "description": f"Pod {pod_name} has restarted {restart_count} times. Possible silent crash loop."
                    })

    except Exception as e:
        logger.error(f"K8s pod check failed: {e}")

    # --- Check 2: Node-level pressure conditions ---
    try:
        cmd = "kubectl get nodes -o json"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        nodes = json.loads(res.stdout).get("items", [])
        for node in nodes:
            node_name = node.get("metadata", {}).get("name", "unknown")
            conditions = node.get("status", {}).get("conditions", [])
            for cond in conditions:
                if cond.get("type") in ["MemoryPressure", "DiskPressure", "PIDPressure"] and \
                   cond.get("status") == "True":
                    pressure_type = cond["type"]
                    span.set_attribute("incident.detected", True)
                    span.set_attribute("incident.type", pressure_type)
                    logger.warning(f"\U0001F6A8 Alert: Node {node_name} has {pressure_type}!")
                    return json.dumps({
                        "incident": "Node Pressure",
                        "deployment": deployment,
                        "namespace": namespace,
                        "node": node_name,
                        "description": f"Node {node_name} reports {pressure_type}. Hardware resource exhaustion imminent."
                    })
    except Exception as e:
        logger.error(f"K8s node check failed: {e}")

    span.set_attribute("incident.detected", False)
    return json.dumps({"status": "OK"})


def get_cooldown(incident_type: str) -> float:
    """Reads the last remediation timestamp from the sre-copilot deployment annotations."""
    # We sanitize the incident type for the annotation key
    safe_incident_type = incident_type.replace(" ", "-").replace("/", "-")
    annotation_key = f"remediation.aegis.io/last-{safe_incident_type}"
    try:
        # Get annotations of the sre-copilot deployment in oppe2-app namespace
        cmd = "kubectl get deployment sre-copilot -n oppe2-app -o jsonpath='{.metadata.annotations}'"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        
        # Check if the output is not empty (it returns a JSON object string of annotations)
        if not res.stdout or res.stdout == 'null':
            return 0.0
            
        annotations = json.loads(res.stdout.strip("'"))
        if annotation_key in annotations:
            return float(annotations[annotation_key])
        return 0.0
    except Exception as e:
        logger.error(f"Failed to read cooldown annotation: {e}")
        return 0.0


def set_cooldown(incident_type: str, timestamp: float):
    """Sets the last remediation timestamp on the sre-copilot deployment annotations."""
    safe_incident_type = incident_type.replace(" ", "-").replace("/", "-")
    annotation_key = f"remediation.aegis.io/last-{safe_incident_type}"
    try:
        cmd = f"kubectl annotate deployment sre-copilot -n oppe2-app {annotation_key}='{timestamp}' --overwrite"
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        logger.info(f"Successfully recorded cooldown for {incident_type} in Kubernetes annotations.")
    except Exception as e:
        logger.error(f"Failed to write cooldown annotation: {e}")


def cordon_and_drain_node(node_name: str) -> str:
    """Cordons the specified node to prevent new pod scheduling."""
    try:
        cmd = f"kubectl cordon {node_name}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        logger.info(f"Node {node_name} successfully cordoned: {res.stdout.strip()}")
        return f"Node {node_name} cordoned successfully: {res.stdout.strip()}"
    except Exception as e:
        logger.error(f"Failed to cordon node {node_name}: {e}")
        return f"Failed to cordon node {node_name}: {e}"

