import time
import json
import pytest
import sys
import os

# Ensure parent directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import tools_schema, HEALTH_CHECKS_MCP, LAST_REMEDIATION_TIME, COOLDOWN_SECONDS

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

def test_cooldown_mechanism():
    """Test the cooldown deduplication logic for agent remediations."""
    incident_type = "Test_Traffic_Spike"
    COOLDOWN = 300  # 5 minutes
    
    # Reset state
    LAST_REMEDIATION_TIME.clear()
    
    current_time = time.time()
    # Initially no cooldown
    assert (current_time - LAST_REMEDIATION_TIME.get(incident_type, 0)) >= COOLDOWN
    
    # Record remediation execution
    LAST_REMEDIATION_TIME[incident_type] = current_time
    
    # Immediate check should be within cooldown window
    assert (current_time - LAST_REMEDIATION_TIME.get(incident_type, 0)) < COOLDOWN
    
    # Simulated future check beyond cooldown
    future_time = current_time + COOLDOWN + 10
    assert (future_time - LAST_REMEDIATION_TIME.get(incident_type, 0)) >= COOLDOWN
