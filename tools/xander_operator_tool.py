"""Execute a task via xander-operator by writing to its SQLite task queue and polling."""
import sqlite3
import time
import json
import uuid
import os
from pathlib import Path
from typing import Dict, Any

# Workspace: use XANDER_WORKSPACE if set, else OPENCLAW_WORKSPACE, else default
WORKSPACE = Path(os.getenv("XANDER_WORKSPACE", os.getenv("OPENCLAW_WORKSPACE", "/root/.openclaw/workspace"))).expanduser()
DB_FILE = WORKSPACE / "memory" / "tasks.db"

# Xander-operator schema (minimal)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    type TEXT NOT NULL,
    url TEXT,
    selectors TEXT,  -- JSON
    field_values TEXT, -- JSON
    status TEXT DEFAULT 'pending',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    result TEXT,  -- JSON
    params TEXT,  -- JSON
    next_action TEXT
)
"""

def _ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()

def run_xander_operator(task: str, context: str = "") -> Dict[str, Any]:
    """
    Insert a task into xander-operator's task DB and wait for completion.
    Returns {'status': 'success', 'result': ...} or {'status': 'error', 'error': ...}.
    """
    _ensure_db()
    task_id = str(uuid.uuid4())
    created = time.strftime("%Y-%m-%d %H:%M:%S")
    params = {}
    if context:
        params["context"] = context
    params_json = json.dumps(params)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                """INSERT INTO tasks (id, description, type, status, created, attempts, last_error, result, params, next_action)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, task, "code", "pending", created, 0, "", None, params_json, "")
            )
            conn.commit()
        # Poll for completion
        timeout = 300
        interval = 1
        start = time.time()
        while time.time() - start < timeout:
            with sqlite3.connect(DB_FILE) as conn:
                cur = conn.execute("SELECT status, result, last_error FROM tasks WHERE id=?", (task_id,))
                row = cur.fetchone()
                if row:
                    status, result_json, error = row
                    if status == "done":
                        result = json.loads(result_json) if result_json else {}
                        return {"status": "success", "result": result}
                    elif status in ("failed", "error"):
                        return {"status": "error", "error": error or "unknown"}
            time.sleep(interval)
        return {"status": "error", "error": "timeout waiting for xander-operator"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
