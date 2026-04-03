"""Execute a task via xander-operator CLI."""
import subprocess
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("openclaw.tools.xander_exec")

def xander_exec(task: str, workdir: str = None) -> Dict[str, Any]:
    """
    Run xander-operator CLI with the given task and return its result.
    Expects xander-operator to be installed and on PATH.
    """
    cmd = ["xander-operator", "--task", task]
    if workdir:
        cmd.extend(["--workdir", workdir])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return {
                "status": "error",
                "error": f"xander-operator failed: {result.stderr}",
                "stdout": result.stdout,
            }
        # Parse JSON output if possible
        try:
            output = json.loads(result.stdout)
            return {"status": "success", "result": output}
        except json.JSONDecodeError:
            return {"status": "success", "output": result.stdout}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "xander-operator timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
