import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[3]))

import pytest

from backend import workflow_email
from backend.adapters import calendar_adapter
from backend.main import approve_task, TaskDecisionRequest
from backend.ux.verb_rubric import validate
from backend.llm.verbalizer_agent import verbalize_gui_reply
from backend.workflow_email import process_msg
from backend.workflows.io.database import get_default_db


_TESTDATA_DIR = Path(__file__).with_name("testdata")


@pytest.fixture(autouse=True)
def stub_calendar(monkeypatch):
    availability_path = _TESTDATA_DIR / "availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))

    class StubCalendarAdapter:
        def get_busy(self, calendar_id: str, start_iso: str, end_iso: str):
            return availability.get(calendar_id, [])

    monkeypatch.setattr(
        calendar_adapter, "get_calendar_adapter", lambda data_dir=None: StubCalendarAdapter()
    )
    monkeypatch.setattr(calendar_adapter, "_CALENDAR_SINGLETON", StubCalendarAdapter())


@pytest.fixture
def workflow_db(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow_events.json"
    lock_path = tmp_path / ".workflow_events.lock"
    workflow_email.save_db(get_default_db(), db_path)
    monkeypatch.setattr(workflow_email, "DB_PATH", db_path)
    monkeypatch.setattr(workflow_email, "LOCK_PATH", lock_path)
    from backend import main as main_module

    monkeypatch.setattr(main_module, "wf_load_db", lambda: workflow_email.load_db(db_path))
    monkeypatch.setattr(main_module, "wf_save_db", lambda data: workflow_email.save_db(data, db_path))
    monkeypatch.setenv("VERBALIZER_TONE", "plain")
    return db_path


def _send(db_path: Path, body: str, msg_id: str, email: str = "client@example.com"):
    payload = {
        "msg_id": msg_id,
        "from_name": "Workflow Client",
        "from_email": email,
        "subject": "Event request",
        "ts": "2025-01-01T10:00:00Z",
        "body": body,
    }
    return process_msg(payload, db_path=db_path)


def test_shortcut_message_creates_room_tasks_and_passes_rubric(workflow_db):
    body = "Hi! 15.03.2026, 24 participants, Room A if free from 18:00 to 22:00."
    result = _send(workflow_db, body, "msg-1")

    steps = [draft.get("step") for draft in result.get("draft_messages", [])]
    assert steps == [2, 3]



    db_snapshot = workflow_email.load_db(workflow_db)
    pending = db_snapshot["events"][0].get("pending_hil_requests")
    assert pending is not None and len(pending) == 2

    task_types = {task["type"] for task in db_snapshot["tasks"]}
    assert task_types == {"date_confirmation_message", "room_availability_message"}


def test_hil_approval_auto_resumes_and_clears_pending(workflow_db):
    body = "Hello! Please secure Room A on 15.03.2026 for 20 guests from 18:00 to 22:00."
    _send(workflow_db, body, "msg-1")

    db_snapshot = workflow_email.load_db(workflow_db)
    first_task = db_snapshot["tasks"][0]

    response = asyncio.run(approve_task(first_task["task_id"], TaskDecisionRequest()))
    assert response["task_status"] == "approved"
    assert "assistant_reply" in response and response["assistant_reply"]

    db_after = workflow_email.load_db(workflow_db)
    pending = db_after["events"][0].get("pending_hil_requests") or []
    assert all(entry["task_id"] != first_task["task_id"] for entry in pending)


def test_rubric_rejects_missing_greeting():
    text = "There are three options available.\n\nNEXT STEP:\n- Let me know.\n- Thanks!"
    report = validate(text)
    assert not report.ok
    assert report.reason == "missing_greeting"
