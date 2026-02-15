"""Tests for api/routes/tasks.py endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.api.conftest import make_event, make_task


def _db_with_task():
    event = make_event()
    task = make_task(event_id=event["event_id"])
    return {"events": [event], "tasks": [task], "config": {}}


def _empty_db():
    return {"events": [], "tasks": [], "config": {}}


# ---------------------------------------------------------------------------
# GET /api/tasks/pending
# ---------------------------------------------------------------------------

class TestGetPendingTasks:

    def test_empty(self, client):
        with patch("api.routes.tasks.wf_load_db", return_value=_empty_db()), \
             patch("api.routes.tasks.wf_list_pending_tasks", return_value=[]):
            resp = client.get("/api/tasks/pending")
        assert resp.status_code == 200
        assert resp.json()["tasks"] == []

    def test_with_tasks(self, client):
        db = _db_with_task()
        tasks = db["tasks"]
        with patch("api.routes.tasks.wf_load_db", return_value=db), \
             patch("api.routes.tasks.wf_list_pending_tasks", return_value=tasks):
            resp = client.get("/api/tasks/pending")
        assert resp.status_code == 200
        assert len(resp.json()["tasks"]) >= 1

    def test_deduplication(self, client):
        """Two tasks for same event+thread should deduplicate to one."""
        event = make_event()
        task1 = make_task(task_id="t1", event_id=event["event_id"], task_type="offer_message")
        task2 = make_task(task_id="t2", event_id=event["event_id"], task_type="manual_review")
        db = {"events": [event], "tasks": [task1, task2], "config": {}}
        with patch("api.routes.tasks.wf_load_db", return_value=db), \
             patch("api.routes.tasks.wf_list_pending_tasks", return_value=[task1, task2]):
            resp = client.get("/api/tasks/pending")
        assert resp.status_code == 200
        # Dedup should keep the higher-priority task (offer_message)
        payload = resp.json()["tasks"]
        assert len(payload) == 1
        assert payload[0]["type"] == "offer_message"


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/approve
# ---------------------------------------------------------------------------

class TestApproveTask:

    def test_success(self, client):
        result = {
            "res": {"assistant_draft_text": "Offer sent."},
            "thread_id": "thread-001",
            "event_id": "evt-001",
        }
        with patch("api.routes.tasks.wf_approve_task_and_send", return_value=result):
            resp = client.post("/api/tasks/task-001/approve", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_status"] == "approved"
        assert data["assistant_reply"] == "Offer sent."

    def test_not_found(self, client):
        with patch("api.routes.tasks.wf_approve_task_and_send", side_effect=ValueError("not found")):
            resp = client.post("/api/tasks/bad-id/approve", json={})
        assert resp.status_code == 404

    def test_with_edited_message(self, client):
        result = {
            "res": {"assistant_draft_text": "Edited draft."},
            "thread_id": "t1",
            "event_id": "e1",
        }
        with patch("api.routes.tasks.wf_approve_task_and_send", return_value=result) as mock_fn:
            resp = client.post(
                "/api/tasks/task-001/approve",
                json={"edited_message": "Manager edit"},
            )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with("task-001", manager_notes=None, edited_message="Manager edit")


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/reject
# ---------------------------------------------------------------------------

class TestRejectTask:

    def test_success(self, client):
        result = {
            "res": {"assistant_draft_text": "Rejected."},
            "thread_id": "t1",
            "event_id": "e1",
        }
        with patch("api.routes.tasks.wf_reject_task_and_send", return_value=result):
            resp = client.post("/api/tasks/task-001/reject", json={})
        assert resp.status_code == 200
        assert resp.json()["task_status"] == "rejected"

    def test_not_found(self, client):
        with patch("api.routes.tasks.wf_reject_task_and_send", side_effect=ValueError("not found")):
            resp = client.post("/api/tasks/bad-id/reject", json={})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/tasks/cleanup
# ---------------------------------------------------------------------------

class TestCleanupTasks:

    def test_success(self, client):
        with patch("api.routes.tasks.wf_load_db", return_value=_empty_db()), \
             patch("api.routes.tasks.wf_cleanup_tasks", return_value=3), \
             patch("api.routes.tasks.wf_save_db"):
            resp = client.post("/api/tasks/cleanup", json={})
        assert resp.status_code == 200
        assert resp.json()["removed"] == 3

    def test_with_keep_thread_id(self, client):
        with patch("api.routes.tasks.wf_load_db", return_value=_empty_db()), \
             patch("api.routes.tasks.wf_cleanup_tasks", return_value=1) as mock_cleanup, \
             patch("api.routes.tasks.wf_save_db"):
            resp = client.post("/api/tasks/cleanup", json={"keep_thread_id": "thread-keep"})
        assert resp.status_code == 200
        mock_cleanup.assert_called_once()
        call_kwargs = mock_cleanup.call_args
        assert call_kwargs[1].get("keep_thread_id") == "thread-keep" or \
               (len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "thread-keep") or \
               "thread-keep" in str(call_kwargs)
