"""Client for calling Xander Operator and enforcing contract."""

import json
import logging
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)

class OperatorClient:
    """
    Thin wrapper that invokes xander-operator (CLI or API) and ensures
    the result matches the strict completion contract.
    """

    def __init__(self, mode: str = "cli", api_url: str = "http://localhost:8001"):
        """
        Args:
            mode: "cli" to run `xander-operator` command, or "api" to POST to REST endpoint
            api_url: API base URL if mode == "api"
        """
        self.mode = mode
        self.api_url = api_url

    def execute(self, task: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a task via operator and return a validated contract.

        Expected contract:
        {
            "status": "completed" | "failed",
            "task": "task description",
            "output_path": "/absolute/path/to/output",
            "summary": "human readable summary"
        }
        """
        if self.mode == "cli":
            result = self._execute_cli(task, **kwargs)
        elif self.mode == "api":
            result = self._execute_api(task, **kwargs)
        else:
            raise ValueError(f"Unknown operator mode: {self.mode}")

        # Validate contract
        required = ["status", "task", "output_path", "summary"]
        missing = [k for k in required if k not in result]
        if missing:
            raise ValueError(f"Operator contract missing fields: {missing}")

        return result

    def _execute_cli(self, task: str, **kwargs) -> Dict[str, Any]:
        """Run xander-operator CLI and parse JSON output."""
        cmd = ["xander-operator", "--task", task, "--output", "json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"Operator CLI failed: {proc.stderr}")
        try:
            result = json.loads(proc.stdout)
            return result
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Operator CLI returned invalid JSON: {proc.stdout[:200]}") from e

    def _execute_api(self, task: str, **kwargs) -> Dict[str, Any]:
        """POST to Operator API."""
        import requests
        resp = requests.post(
            f"{self.api_url}/run",
            json={"task": task, **kwargs},
            timeout=300
        )
        resp.raise_for_status()
        return resp.json()
