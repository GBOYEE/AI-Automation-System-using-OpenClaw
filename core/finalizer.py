"""Finalizer: Deliver results + proof after task completion."""

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from .task_queue import TaskQueue
from skills.telegram.send_file import send_file_with_config
from skills.telegram.send_message import send_message

logger = logging.getLogger(__name__)

class Finalizer:
    def __init__(self, task_queue: TaskQueue):
        self.task_queue = task_queue

    def safe_finalize(self, task_id: str, task_name: str, output_path: str, summary: str, max_retries: int = 3) -> bool:
        """
        Perform finalization: send file, send message, log, mark done.
        Retries on failure up to max_retries.
        """
        for attempt in range(max_retries):
            try:
                # 1. Send file to Telegram
                file_result = send_file_with_config(
                    file_path=output_path,
                    caption=f"✅ Task Completed\n\n{task_name}\n\n{summary}"
                )
                if not file_result.get("ok"):
                    raise RuntimeError(f"Telegram file send failed: {file_result.get('error')}")

                # 2. Send summary message
                msg_result = send_message(
                    text=f"✅ TASK COMPLETED\n\n"
                         f"<b>{task_name}</b>\n"
                         f"📁 <code>{Path(output_path).name}</code>\n"
                         f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
                         f"📝 {summary}"
                )
                if not msg_result.get("ok"):
                    raise RuntimeError(f"Telegram message send failed: {msg_result.get('error')}")

                # 3. Log completion
                self._log_completion(task_id, task_name, output_path, file_result.get("message_id"))

                # 4. Mark task completed in queue
                self.task_queue.update(task_id, status="completed", completed_at=True)

                logger.info(f"Task {task_id} finalized successfully")
                return True

            except Exception as e:
                logger.warning(f"Finalize attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"Finalize failed after {max_retries} attempts for task {task_id}")
                    return False

    def _log_completion(self, task_id: str, task_name: str, output_path: str, telegram_message_id: str):
        """Append to /logs/history.json (global) and also write to task record."""
        log_dir = Path("/logs") if Path("/logs").exists() else Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        history_file = log_dir / "history.json"

        entry = {
            "task_id": task_id,
            "task": task_name,
            "output_path": output_path,
            "telegram_message_id": telegram_message_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Load existing or start new
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                if not isinstance(history, list):
                    history = []
            except:
                history = []
        else:
            history = []

        history.append(entry)
        history_file.write_text(json.dumps(history, indent=2))
