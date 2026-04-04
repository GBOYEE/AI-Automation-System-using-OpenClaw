"""Planner Agent — selects appropriate tool(s) for a given task description."""
from typing import Dict, Any, List

class PlannerAgent:
    """
    Very simple rule-based planner. For now:
    - Coding tasks -> xander_operator
    - Shell tasks -> shell
    - Disk cleanup -> disk_clean
    - Docker restart -> docker_restart
    """
    def plan(self, description: str) -> Dict[str, Any]:
        desc = description.lower()
        if any(word in desc for word in ["code", "fix", "implement", "refactor", "build", "add feature", "create api"]):
            tool = "xander_operator"
            args = {"task": description, "context": ""}
        elif "disk" in desc or "clean" in desc or "free space" in desc:
            tool = "disk_clean"
            args = {"limit_mb": 500}
        elif "restart" in desc and "docker" in desc:
            tool = "docker_restart"
            # Try to extract container name; fallback to placeholder
            args = {"container": "unknown"}
        else:
            tool = "shell"
            # Very simple: wrap description in echo
            args = {"cmd": f"echo 'No specific tool; task: {description}'"}
        steps = [{"step": 1, "action": tool, "args": args}]
        # Estimate risk from permissions? Hardcoded for now.
        estimated_risk = "high" if tool == "xander_operator" else ("medium" if tool.startswith("docker") else "low")
        return {"steps": steps, "estimated_risk": estimated_risk}
