"""
Workflow package exposing the modular email pipeline components.
"""

# Re-export convenience entrypoints for downstream imports.
from .io.database import load_db, save_db, get_default_db  # noqa: F401
from .io.tasks import enqueue_task, update_task_status, list_pending_tasks  # noqa: F401
