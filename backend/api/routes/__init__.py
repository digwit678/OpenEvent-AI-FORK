"""
MODULE: backend/api/routes/__init__.py
PURPOSE: FastAPI route handlers organized by domain.

WILL CONTAIN (after main.py split):
    - messages.py    Message handling (/api/send-message, threads)
    - tasks.py       HIL task management (/api/tasks/*)
    - events.py      Event operations (/api/event/*)
    - debug.py       Debug endpoints (/api/debug/*)
    - config.py      Configuration (/api/config/*)
    - clients.py     Client operations (/api/client/*)

MIGRATION STATUS:
    Prepared for Phase C of refactoring.
    Routes will be extracted from main.py.
"""
