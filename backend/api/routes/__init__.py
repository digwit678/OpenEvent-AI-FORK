"""
MODULE: backend/api/routes/__init__.py
PURPOSE: FastAPI route handlers organized by domain.

CONTAINS:
    - tasks.py       HIL task management (/api/tasks/*)
    - events.py      Event operations (/api/event/*, /api/events/*)
    - config.py      Configuration (/api/config/*)
    - clients.py     Client operations (/api/client/*)

PLANNED (not yet extracted):
    - messages.py    Message handling (/api/send-message, threads)

MIGRATION STATUS:
    Phase C of refactoring - in progress.
"""

from .tasks import router as tasks_router
from .events import router as events_router
from .config import router as config_router
from .clients import router as clients_router

__all__ = ["tasks_router", "events_router", "config_router", "clients_router"]
