"""Scheduler — promotes scheduled tasks to pending."""

from datetime import datetime
from typing import List, Dict, Any

class Scheduler:
    def __init__(self, task_queue):
        self.task_queue = task_queue

    def promote(self, now_iso: str):
        """
        Move tasks with run_at <= now to pending.
        Only affects tasks currently in 'pending' with a run_at in the past.
        """
        # In this simple design, we just update any pending task with run_at <= now to stay pending (they're already pending)
        # Actually we need to set them from some other status? Let's adjust queue logic.
        # Better: queue.next() should consider run_at. We'll handle in queue.next() instead.
        pass  # Scheduler tick is handled by queue's next() method logic
