"""Tests for api/routes/manager_actions.py endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.api.conftest import make_event, make_task
from workflows.manager_actions import ManagerActionResult, ManagerActionType


def _success_result(action_type: ManagerActionType, event_id: str = "evt-001") -> ManagerActionResult:
    return ManagerActionResult(
        success=True,
        action_type=action_type,
        event_id=event_id,
        previous_step=4,
        new_step=4,
        workflow_advanced=False,
        needs_client_notification=True,
        notification_draft="Changes applied.",
    )


def _db_with_event():
    event = make_event()
    return {"events": [event], "tasks": [], "config": {}}


def _db_with_task():
    event = make_event()
    task = make_task(event_id=event["event_id"])
    return {"events": [event], "tasks": [task], "config": {}}


# ---------------------------------------------------------------------------
# PUT /api/manager/events/{id}/date
# ---------------------------------------------------------------------------

class TestChangeDateEndpoint:

    def test_success(self, client):
        result = _success_result(ManagerActionType.DATE_CHANGE)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.put(
                "/api/manager/events/evt-001/date",
                json={"new_date": "2026-05-01"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_not_found(self, client):
        with patch("api.routes.manager_actions.wf_load_db", return_value={"events": [], "tasks": []}):
            resp = client.put(
                "/api/manager/events/nonexistent/date",
                json={"new_date": "2026-05-01"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/manager/events/{id}/room
# ---------------------------------------------------------------------------

class TestChangeRoomEndpoint:

    def test_success(self, client):
        result = _success_result(ManagerActionType.ROOM_CHANGE)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.put(
                "/api/manager/events/evt-001/room",
                json={"new_room": "Room B"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# PUT /api/manager/events/{id}/requirements
# ---------------------------------------------------------------------------

class TestUpdateRequirements:

    def test_success(self, client):
        result = _success_result(ManagerActionType.REQUIREMENTS_UPDATE)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.put(
                "/api/manager/events/evt-001/requirements",
                json={"participants": 50},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/manager/events/{id}/cancel-room
# ---------------------------------------------------------------------------

class TestCancelRoom:

    def test_success(self, client):
        result = _success_result(ManagerActionType.ROOM_CANCELLATION)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.post(
                "/api/manager/events/evt-001/cancel-room",
                json={},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/manager/site-visit/{id}/reschedule
# ---------------------------------------------------------------------------

class TestRescheduleSiteVisit:

    def test_success(self, client):
        result = _success_result(ManagerActionType.SITE_VISIT_RESCHEDULE)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.post(
                "/api/manager/site-visit/evt-001/reschedule",
                json={"new_date": "2026-05-10", "new_time": "14:00"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /api/manager/offers/{id}/update
# ---------------------------------------------------------------------------

class TestOfferUpdate:

    def test_success(self, client):
        result = _success_result(ManagerActionType.OFFER_UPDATE)
        with patch("api.routes.manager_actions.wf_load_db", return_value=_db_with_event()), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.put(
                "/api/manager/offers/evt-001/update",
                json={"price": 2500.0},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/manager/hil/{task_id}/approve
# ---------------------------------------------------------------------------

class TestHILApprove:

    def test_success(self, client):
        result = _success_result(ManagerActionType.HIL_APPROVE)
        db = _db_with_task()
        with patch("api.routes.manager_actions.wf_load_db", return_value=db), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.post(
                "/api/manager/hil/task-001/approve",
                json={},
            )
        assert resp.status_code == 200

    def test_not_found(self, client):
        with patch("api.routes.manager_actions.wf_load_db", return_value={"events": [], "tasks": []}):
            resp = client.post(
                "/api/manager/hil/nonexistent/approve",
                json={},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/manager/hil/{task_id}/reject
# ---------------------------------------------------------------------------

class TestHILReject:

    def test_success(self, client):
        result = _success_result(ManagerActionType.HIL_REJECT)
        db = _db_with_task()
        with patch("api.routes.manager_actions.wf_load_db", return_value=db), \
             patch("api.routes.manager_actions.process_manager_action", return_value=result), \
             patch("api.routes.manager_actions.wf_save_db"):
            resp = client.post(
                "/api/manager/hil/task-001/reject",
                json={"reason": "Bad draft"},
            )
        assert resp.status_code == 200

    def test_not_found(self, client):
        with patch("api.routes.manager_actions.wf_load_db", return_value={"events": [], "tasks": []}):
            resp = client.post(
                "/api/manager/hil/nonexistent/reject",
                json={"reason": "test"},
            )
        assert resp.status_code == 404
