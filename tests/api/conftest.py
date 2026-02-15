"""Shared fixtures for API route tests.

Provides realistic mock data and a pre-configured TestClient
with auth disabled and stub agent mode.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict
from unittest.mock import patch

import pytest

# Fix sys.path to prioritize project root
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path = [p for p in sys.path if "tests/api" not in p and "tests\\api" not in p]
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ---------------------------------------------------------------------------
# Environment: auth disabled, stub LLM
# ---------------------------------------------------------------------------

@pytest.fixture()
def env_no_auth():
    """Patch environment to disable auth and use stub agent."""
    with patch.dict(os.environ, {"AUTH_ENABLED": "0", "AGENT_MODE": "stub", "ENV": "dev"}, clear=False):
        yield


# ---------------------------------------------------------------------------
# Reusable test data factories
# ---------------------------------------------------------------------------

def make_event(
    event_id: str = "evt-001",
    *,
    current_step: int = 4,
    client_email: str = "alice@example.com",
    chosen_date: str = "2026-04-15",
    locked_room: str = "Room A",
    offer_accepted: bool = False,
    deposit_required: bool = True,
    deposit_paid: bool = False,
    status: str = "active",
) -> Dict[str, Any]:
    """Build a realistic event dict at an arbitrary workflow step."""
    event: Dict[str, Any] = {
        "event_id": event_id,
        "thread_id": f"thread-{event_id}",
        "current_step": current_step,
        "chosen_date": chosen_date,
        "locked_room_id": locked_room,
        "offer_accepted": offer_accepted,
        "status": status,
        "event_data": {
            "Email": client_email,
            "Name": "Alice Test",
            "Company": "TestCorp",
            "Event Date": chosen_date,
            "Number of Participants": "30",
            "Type of Event": "workshop",
        },
        "requirements": {"number_of_participants": 30},
        "logs": [],
        "pending_hil_requests": [],
    }
    if deposit_required:
        event["deposit_info"] = {
            "deposit_required": True,
            "deposit_amount": "CHF 500",
            "deposit_due_date": "2026-04-01",
            "deposit_paid": deposit_paid,
            "deposit_paid_at": "2026-03-28T10:00:00Z" if deposit_paid else None,
        }
    return event


def make_task(
    task_id: str = "task-001",
    *,
    event_id: str = "evt-001",
    task_type: str = "offer_message",
    client_id: str = "alice@example.com",
) -> Dict[str, Any]:
    """Build a realistic HIL task dict."""
    return {
        "task_id": task_id,
        "id": task_id,
        "type": task_type,
        "event_id": event_id,
        "client_id": client_id,
        "created_at": "2026-04-10T08:00:00Z",
        "status": "pending",
        "notes": "Auto-generated offer",
        "payload": {
            "snippet": "Your event on 15.04.2026 ...",
            "draft_body": "Dear Alice, here is your offer ...",
            "thread_id": f"thread-{event_id}",
            "step_id": "step4",
        },
    }


@pytest.fixture()
def sample_event() -> Dict[str, Any]:
    return make_event()


@pytest.fixture()
def sample_task() -> Dict[str, Any]:
    return make_task()


@pytest.fixture()
def mock_db(sample_event, sample_task) -> Dict[str, Any]:
    """Realistic db dict with 1 event at step 4, deposit info, and 1 pending task."""
    return {
        "events": [sample_event],
        "tasks": [sample_task],
        "config": {},
    }


# ---------------------------------------------------------------------------
# TestClient with patched environment
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(env_no_auth):
    """FastAPI TestClient with auth disabled.

    Each test gets a fresh app to avoid cross-test state leakage.
    """
    from fastapi.testclient import TestClient
    from app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Admin context helper (for config POST endpoints)
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin_ctx():
    """Bypass require_admin_role() check for admin-only endpoints.

    Context variables don't propagate from the test thread into the ASGI
    request handler, so we mock the guard function itself.
    """
    with patch("api.routes.config.require_admin_role"):
        yield
