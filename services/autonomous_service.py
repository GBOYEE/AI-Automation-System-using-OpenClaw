"""Autonomous Service — Xander Orchestrator + Scheduler."""

import time
import logging
from datetime import datetime
from typing import Optional

from .core.task_queue import TaskQueue
from .core.scheduler import Scheduler
from .core.finalizer import Finalizer
from .tools.xander_operator_client import OperatorClient
from .config.settings import settings

logger = logging.getLogger(__name__)

class AutonomousService:
    """
    Runs two loops:
    1. Scheduler: promotes scheduled tasks to pending every minute
    2. Orchestrator: executes pending tasks via Operator and finalizes
    """
    def __init__(self):
        self.task_queue = TaskQueue(settings.task_queue_path)
        self.scheduler = Scheduler(self.task_queue)
        self.finalizer = Finalizer(self.task_queue)
        self.operator = OperatorClient(mode=settings.operator_mode, api_url=settings.operator_api_url)
        self.running = False

    def start(self):
        """Start both scheduler and orchestrator loops (blocking)."""
        self.running = True
        logger.info("Autonomous service starting...")

        # Start scheduler in background? For simplicity, we interleave in one thread
        while self.running:
            try:
                self._scheduler_tick()
                self._orchestrator_tick()
                time.sleep(5)  # loop interval
            except KeyboardInterrupt:
                logger.info("Shutting down autonomous service")
                break
            except Exception as e:
                logger.exception(f"Loop error: {e}")
                time.sleep(5)

    def _scheduler_tick(self):
        now_iso = datetime.utcnow().isoformat()
        self.scheduler.promote(now_iso)

    def _orchestrator_tick(self):
        task = self.task_queue.next()
        if task:
            task_id = task["id"]
            task_title = task["title"]
            logger.info(f"Executing task: {task_id} - {task_title}")
            # Mark running
            self.task_queue.update(task_id, status="running")
            try:
                result = self.operator.execute(task_title)
                # Finalize if completed
                if result.get("status") == "completed":
                    output_path = result.get("output_path")
                    summary = result.get("summary", "")
                    success = self.finalizer.safe_finalize(task_id, task_title, output_path, summary)
                    if success:
                        logger.info(f"Task {task_id} finalized successfully")
                    else:
                        logger.error(f"Task {task_id} finalize failed; leaving as completed with delivery issues")
                else:
                    # Task failed
                    logger.error(f"Task {task_id} execution failed: {result.get('summary')}")
                    self.task_queue.update(task_id, status="failed")
            except Exception as e:
                logger.exception(f"Task {task_id} execution exception")
                self.task_queue.update(task_id, status="failed")

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    service = AutonomousService()
    service.start()

if __name__ == "__main__":
    main()
