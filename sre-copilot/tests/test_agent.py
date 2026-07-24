import time
import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Ensure parent directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import tools_schema, COOLDOWN_SECONDS
from mcp_client import HEALTH_CHECKS_MCP
from k8s_tools import get_cooldown, set_cooldown

def test_tools_schema_validity():
    """Verify that tools_schema contains all 5 required SRE remediation tools."""
    assert len(tools_schema) == 5
    tool_names = [t["function"]["name"] for t in tools_schema]
    expected_tools = [
        "scale_deployment",
        "patch_pod_limits",
        "rollback_deployment",
        "trigger_retraining",
        "cordon_and_drain"
    ]
    for name in expected_tools:
        assert name in tool_names

def test_health_checks_mcp_structure():
    """Verify MCP health checks list covers key SRE anomaly patterns."""
    assert len(HEALTH_CHECKS_MCP) >= 4
    check_names = [check["name"] for check in HEALTH_CHECKS_MCP]
    assert any("Resource Starvation" in name for name in check_names)
    assert any("Traffic Spike" in name for name in check_names)
    assert any("Model Drift" in name for name in check_names)

@patch('k8s_tools.subprocess.run')
def test_cooldown_mechanism(mock_run):
    """Test the cooldown deduplication logic backed by Kubernetes annotations."""
    incident_type = "Test_Traffic_Spike"
    safe_incident_type = incident_type.replace(" ", "-").replace("/", "-")
    annotation_key = f"remediation.aegis.io/last-{safe_incident_type}"
    
    current_time = time.time()
    
    # Mocking get_cooldown (initial state: no annotation)
    mock_res_empty = MagicMock()
    mock_res_empty.stdout = 'null'
    mock_run.return_value = mock_res_empty
    
    assert get_cooldown(incident_type) == 0.0
    
    # Mocking get_cooldown (state: annotation set to current_time)
    mock_res_annotated = MagicMock()
    mock_res_annotated.stdout = json.dumps({annotation_key: str(current_time)})
    mock_run.return_value = mock_res_annotated
    
    assert get_cooldown(incident_type) == current_time
    
    # Verify cooldown check behavior
    assert (current_time - get_cooldown(incident_type)) < COOLDOWN_SECONDS
    
    # Test setting cooldown calls correct kubectl command
    set_cooldown(incident_type, current_time)
    
    # Verify the last call to subprocess.run was the annotation patch
    last_call_args = mock_run.call_args[0][0]
    assert "kubectl annotate deployment sre-copilot" in last_call_args
    assert f"{annotation_key}='{current_time}'" in last_call_args
    assert "--overwrite" in last_call_args

@patch('k8s_tools.subprocess.run')
def test_cordon_node(mock_run):
    """Test that cordon_and_drain_node invokes kubectl cordon."""
    from k8s_tools import cordon_and_drain_node
    mock_res = MagicMock()
    mock_res.stdout = 'node/k8s-node-1 cordoned'
    mock_run.return_value = mock_res

    res = cordon_and_drain_node('k8s-node-1')
    assert 'cordoned successfully' in res
    mock_run.assert_called_once_with('kubectl cordon k8s-node-1', shell=True, capture_output=True, text=True, check=True)

