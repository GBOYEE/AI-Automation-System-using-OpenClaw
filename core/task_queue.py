"""Task Queue for Xander Autonomous System."""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

class TaskQueue:
    def __init__(self, db_path: str = "/data/tasks.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    priority INTEGER DEFAULT 2,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    run_at TEXT,  -- ISO datetime or NULL
                    assigned_to TEXT DEFAULT 'xander-operator',
                    result_json TEXT,
                    completed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_priority ON tasks(status, priority)")
            conn.commit()

    def add(self, task_id: str, title: str, priority: int = 2, run_at: Optional[str] = None):
        """Add a new task to the queue.
        
        Args:
            task_id: unique identifier
            title: task description
            priority: 1=high, 2=medium, 3=low
            run_at: ISO datetime string to schedule, or None for immediate
        """
        status = "scheduled" if run_at else "pending"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                    INSERT OR REPLACE INTO tasks 
                    (id, title, priority, status, created_at, run_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, title, priority, status, datetime.utcnow().isoformat(), run_at)
            )
            conn.commit()

    def next(self) -> Optional[Dict[str, Any]]:
        """Get the next task to execute.
        
        Returns the highest priority task that is either:
        - status = 'pending'
        - OR status = 'scheduled' AND run_at <= now
        """
        now_iso = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Try to find pending first
            cur = conn.execute(
                """
                    SELECT * FROM tasks
                    WHERE status = 'pending'
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                # No pending; try scheduled that are due
                cur = conn.execute(
                    """
                        SELECT * FROM tasks
                        WHERE status = 'scheduled' AND run_at <= ?
                        ORDER BY priority ASC, run_at ASC
                        LIMIT 1
                    """,
                    (now_iso,)
                )
                row = cur.fetchone()
            if row:
                task = dict(row)
                # Mark as running immediately to avoid double-fetch
                conn.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (task["id"],))
                conn.commit()
                if task["result_json"]:
                    task["result"] = json.loads(task["result_json"])
                return task
            return None

    def update(self, task_id: str, status: str = None, result: Dict[str, Any] = None, completed_at: bool = False):
        """Update task status and optionally store result."""
        updates = []
        params = []
        if status:
            updates.append("status = ?")
            params.append(status)
        if result is not None:
            updates.append("result_json = ?")
            params.append(json.dumps(result))
        if completed_at and status == "completed":
            updates.append("completed_at = ?")
            params.append(datetime.utcnow().isoformat())
        if not updates:
            return
        params.append(task_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

    def promote_scheduled(self, now_iso: str):
        """Move scheduled tasks (run_at <= now) to pending."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tasks
                SET status = 'pending'
                WHERE status = 'pending' AND run_at IS NOT NULL AND run_at <= ?
            """, (now_iso,))
            conn.commit()

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                cur = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            rows = cur.fetchall()
            tasks = []
            for row in rows:
                task = dict(row)
                if task["result_json"]:
                    task["result"] = json.loads(task["result_json"])
                tasks.append(task)
            return tasks
