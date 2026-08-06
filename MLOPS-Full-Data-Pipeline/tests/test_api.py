import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app

def test_api_endpoints():
    with TestClient(app) as client:
        # Live check
        r1 = client.get("/live_check")
        assert r1.status_code == 200
        assert r1.json() == {"status": "alive"}

        # Ready check
        r2 = client.get("/ready_check")
        assert r2.status_code == 200
        assert r2.json() == {"status": "ready"}

        # Valid prediction
        payload = {
            "V1": -1.35, "V2": -0.07, "V3": 2.53, "V4": 1.37, "V5": -0.33,
            "V6": 0.46, "V7": 0.23, "V8": 0.09, "V9": 0.36, "V10": 0.09,
            "V11": -0.55, "V12": -0.61, "V13": -0.99, "V14": -0.31, "V15": 1.46,
            "V16": -0.47, "V17": 0.20, "V18": 0.02, "V19": 0.40, "V20": 0.25,
            "V21": -0.01, "V22": 0.27, "V23": -0.11, "V24": 0.06, "V25": 0.12,
            "V26": -0.18, "V27": 0.13, "V28": -0.02, "Amount": 149.62
        }
        r3 = client.post("/predict", json=payload)
        assert r3.status_code == 200
        data = r3.json()
        assert "prediction" in data
        assert "predicted_class" in data
        assert data["predicted_class"] in ["Fraud", "Not Fraud"]
        assert "probability" in data

        # Invalid schema
        r4 = client.post("/predict", json={"Amount": 10.0})
        assert r4.status_code == 422
