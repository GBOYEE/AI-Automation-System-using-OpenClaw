import os
from .base import Settings

settings = Settings()

# Autonomous service settings
settings.operator_mode = os.getenv("OPERATOR_MODE", "cli")
settings.operator_api_url = os.getenv("OPERATOR_API_URL", "http://localhost:8001")
settings.task_queue_path = os.getenv("TASK_QUEUE_PATH", "/data/tasks.db")
