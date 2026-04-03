import os
import requests
from typing import Dict, Any

XANDER_OPERATOR_URL = os.getenv("XANDER_OPERATOR_URL", "http://localhost:8001")

def run_xander_operator(task: str, context: str = "") -> Dict[str, Any]:
    """
    Call the xander-operator agent via HTTP API.
    """
    try:
        resp = requests.post(
            f"{XANDER_OPERATOR_URL}/run",
            json={"task": task, "workdir": os.getenv("XANDER_OPERATOR_WORKDIR")},
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"status": "error", "error": str(e)}
