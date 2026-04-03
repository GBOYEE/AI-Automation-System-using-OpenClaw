"""OpenClaw Orchestrator — explicit pipeline: receive → plan → execute → observe."""
import uuid
import logging
import os
import json
import requests
from typing import Dict, Any, Optional
from datetime import datetime

from ..telemetry import get_trace_id

logger = logging.getLogger("openclaw.orchestrator")

class SimpleLLMPlanner:
    """"Uses Ollama to generate a step-by-step plan.
    """
    def __init__(self, model: str = "phi3:mini", base_url: str = None):
        self.model = model
        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

    def plan(self, description: str) -> Dict[str, Any]:
        prompt = f"""You are a disciplined assistant that creates step-by-step execution plans.

Task: {description}

Available tools:
- shell: run a shell command (cmd: string)
- disk_clean: clean temporary files (limit_mb: int)
- docker_restart: restart a container (container: string)
- file_read: read a file (path: string)
- file_write: write a file (path: string, content: string)

Provide a JSON plan with:
{{
  "objective": "string",
  "steps": [
    {{"step": 1, "action": "tool_name", "args": {{...}}, "validation": "how to check"}}
  ]
}}

Keep steps <= 5. Respond ONLY with JSON."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 512}
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "").strip()
            # Extract JSON
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end != -1:
                plan = json.loads(text[start:end])
                return plan
            else:
                raise ValueError("No JSON found in LLM response")
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            # Fallback: single shell step with the original description as a generic command
            return {
                "objective": description,
                "steps": [
                    {"step": 1, "action": "shell", "args": {"cmd": description}, "validation": "Check exit code"}
                ]
            }

class Orchestrator:
    """
    Coordinates the flow of a task from reception to completion.
    Steps: receive → plan → execute → observe
    """
    def __init__(self, db_session_factory, permissions: Dict[str, Any], planner=None):
        self.db_session = db_session_factory
        self.permissions = permissions
        self.planner = planner or SimpleLLMPlanner()
        self.metrics = {
            "tasks_received": 0,
            "tasks_planned": 0,
            "tasks_executed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "approvals_requested": 0,
            "approvals_granted": 0,
            "approvals_rejected": 0,
        }

    def receive_task(self, task_type: str, payload: Dict[str, Any]) -> str:
        task_id = str(uuid.uuid4())
        event = {
            "event_id": str(uuid.uuid4()),
            "type": "task_received",
            "task_id": task_id,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "gateway",
            "trace_id": get_trace_id(),
        }
        self._log_event(event)
        self.metrics["tasks_received"] += 1
        logger.info("Task received", extra={"task_id": task_id, "type": task_type})
        return task_id

    def plan_task(self, task_id: str, description: str) -> Dict[str, Any]:
        plan = self.planner.plan(description)
        plan["task_id"] = task_id
        event = {
            "event_id": str(uuid.uuid4()),
            "task_id": task_id,
            "type": "planned",
            "payload": plan,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "orchestrator",
            "trace_id": get_trace_id(),
        }
        self._log_event(event)
        self.metrics["tasks_planned"] += 1
        logger.info("Task planned", extra={"task_id": task_id, "steps": len(plan["steps"])})
        return plan

    def execute_plan(self, task_id: str, plan: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        steps = plan["steps"]
        results = []
        for step in steps:
            tool = step["action"]
            args = step.get("args", {})
            risk = self._assess_risk(tool, args)
            if risk == "block":
                results.append({"status": "blocked", "reason": "tool blocked by policy"})
                break
            if risk == "high":
                approval_id = self._request_approval(task_id, step, user)
                self.metrics["approvals_requested"] += 1
                results.append({"status": "awaiting_approval", "approval_id": approval_id})
                break
            # low or medium (medium allowed if auto_execute configured)
            result = self._execute_tool(tool, args)
            results.append(result)
            if result.get("status") != "success":
                break

        success = all(r.get("status") == "success" for r in results)
        event_type = "executed"
        if success:
            self.metrics["tasks_succeeded"] += 1
        else:
            self.metrics["tasks_failed"] += 1
        self.metrics["tasks_executed"] += 1

        event = {
            "event_id": str(uuid.uuid4()),
            "task_id": task_id,
            "type": event_type,
            "payload": {"results": results, "success": success},
            "timestamp": datetime.utcnow().isoformat(),
            "source": "orchestrator",
            "trace_id": get_trace_id(),
        }
        self._log_event(event)
        return event

    def _assess_risk(self, tool: str, args: Dict[str, Any]) -> str:
        tool_cfg = self.permissions.get("tools", {}).get(tool, {})
        return tool_cfg.get("risk", "medium")

    def _request_approval(self, task_id: str, step: Dict[str, Any], user: Optional[str]) -> str:
        approval_id = str(uuid.uuid4())
        with self.db_session() as session:
            from ..state.models import Approval
            approval = Approval(
                approval_id=approval_id,
                task_id=task_id,
                step=step["step"],
                tool=step["action"],
                args=step.get("args", {}),
                requested_by=user or "system",
                status="pending",
                created_at=datetime.utcnow(),
            )
            session.add(approval)
            session.commit()
        logger.info("Approval requested", extra={"approval_id": approval_id, "task_id": task_id})
        return approval_id

    def _execute_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if tool == "shell":
                from ..tools.system_tools import run_shell
                return run_shell(args.get("cmd", ""), capture_output=True, timeout=10)
            elif tool == "disk_clean":
                from ..tools.system_tools import disk_clean
                return disk_clean(limit_mb=args.get("limit_mb", 500))
            elif tool == "docker_restart":
                from ..tools.docker_tools import restart_container
                return restart_container(args.get("container"))
            elif tool == "xander_operator":
                from ..tools.xander_operator_tool import run_xander_operator
                return run_xander_operator(task=args.get("task", ""), context=args.get("context", ""))
            else:
                return {"status": "error", "error": f"Unknown tool: {tool}"}
        except Exception as e:
            logger.exception("Tool execution failed")
            return {"status": "error", "error": str(e)}

    def _log_event(self, event: Dict[str, Any]):
        with self.db_session() as session:
            from ..state.models import Event, EventType
            ev = Event(
                event_id=event["event_id"],
                type=EventType(event["type"]),
                task_id=event.get("task_id"),
                payload=event,
                timestamp=datetime.fromisoformat(event["timestamp"]),
                source=event.get("source"),
            )
            session.add(ev)
            session.commit()
        # Log only metadata, not full payload (avoid secrets)
        log_extra = {k: event.get(k) for k in ('event_id', 'type', 'task_id', 'source', 'trace_id') if k in event}
        logger.info("Event", extra=log_extra)
