"""Tests for api/routes/messages.py endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.api.conftest import make_event


def _mock_wf_process_msg_success(**overrides):
    """Return a realistic wf_process_msg result."""
    base = {
        "action": "date_confirmed",
        "event_id": "evt-001",
        "task_id": None,
        "intent": "event_request",
        "draft_messages": [
            {
                "body": "Thank you for your inquiry!",
                "body_markdown": "Thank you for your inquiry!",
                "headers": [],
                "actions": [],
            }
        ],
        "assistant_message": "Thank you for your inquiry!",
        "res": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# POST /api/start-conversation
# ---------------------------------------------------------------------------

class TestStartConversation:

    def test_success(self, client):
        wf_res = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_res), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            resp = client.post(
                "/api/start-conversation",
                json={"email_body": "I want to book a room for 30 guests", "client_email": "test@example.com"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] is not None
        assert data["workflow_type"] == "new_event"
        assert len(data["response"]) > 0

    def test_missing_fields(self, client):
        """Missing required fields should return 422."""
        resp = client.post("/api/start-conversation", json={})
        assert resp.status_code == 422

    def test_workflow_error(self, client):
        """Workflow processing failure returns 500."""
        with patch("api.routes.messages.wf_process_msg", side_effect=Exception("boom")):
            resp = client.post(
                "/api/start-conversation",
                json={"email_body": "test", "client_email": "test@example.com"},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/send-message
# ---------------------------------------------------------------------------

class TestSendMessage:

    def test_session_not_found(self, client):
        resp = client.post(
            "/api/send-message",
            json={"session_id": "nonexistent", "message": "hello"},
        )
        assert resp.status_code == 404

    def test_success(self, client):
        """Send a message in an existing session."""
        # First start a conversation to register a session
        wf_start = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            start_resp = client.post(
                "/api/start-conversation",
                json={"email_body": "Book event for 30 guests", "client_email": "test@example.com"},
            )
        session_id = start_resp.json()["session_id"]

        # Now send a follow-up
        wf_follow = _mock_wf_process_msg_success(action="step2_continue")
        with patch("api.routes.messages.wf_process_msg", return_value=wf_follow), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            resp = client.post(
                "/api/send-message",
                json={"session_id": session_id, "message": "Yes, April 15 works"},
            )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == session_id

    def test_workflow_error_fallback(self, client):
        """Workflow exception should return a fallback message, not 500."""
        wf_start = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            start_resp = client.post(
                "/api/start-conversation",
                json={"email_body": "test", "client_email": "test@example.com"},
            )
        session_id = start_resp.json()["session_id"]

        with patch("api.routes.messages.wf_process_msg", side_effect=Exception("fail")):
            resp = client.post(
                "/api/send-message",
                json={"session_id": session_id, "message": "follow up"},
            )
        # send-message handles exceptions gracefully with fallback
        assert resp.status_code == 200
        assert len(resp.json()["response"]) > 0


# ---------------------------------------------------------------------------
# POST /api/conversation/{id}/confirm-date
# ---------------------------------------------------------------------------

class TestConfirmDate:

    def test_not_found(self, client):
        resp = client.post(
            "/api/conversation/nonexistent/confirm-date",
            json={"date": "2026-04-15"},
        )
        assert resp.status_code == 404

    def test_success(self, client):
        # Start conversation first
        wf_start = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            start = client.post(
                "/api/start-conversation",
                json={"email_body": "Event for 30 guests", "client_email": "test@example.com"},
            )
        sid = start.json()["session_id"]

        # Confirm date
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}), \
             patch("api.routes.messages.wf_save_db"), \
             patch("api.routes.messages.run_availability_workflow"):
            resp = client.post(
                f"/api/conversation/{sid}/confirm-date",
                json={"date": "2026-04-15"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/accept-booking/{id} and /api/reject-booking/{id}
# ---------------------------------------------------------------------------

class TestBookingActions:

    def _start_session(self, client):
        wf_start = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            resp = client.post(
                "/api/start-conversation",
                json={"email_body": "Book event", "client_email": "test@example.com"},
            )
        return resp.json()["session_id"]

    def test_accept_not_found(self, client):
        resp = client.post("/api/accept-booking/nonexistent")
        assert resp.status_code == 404

    def test_reject_not_found(self, client):
        resp = client.post("/api/reject-booking/nonexistent")
        assert resp.status_code == 404

    def test_accept_success(self, client):
        sid = self._start_session(client)
        with patch("api.routes.messages.load_events_database", return_value={"events": []}), \
             patch("api.routes.messages.save_events_database"):
            resp = client.post(f"/api/accept-booking/{sid}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Booking accepted and saved"

    def test_reject_success(self, client):
        sid = self._start_session(client)
        resp = client.post(f"/api/reject-booking/{sid}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Booking rejected and discarded"


# ---------------------------------------------------------------------------
# GET /api/conversation/{id}
# ---------------------------------------------------------------------------

class TestGetConversation:

    def test_not_found(self, client):
        resp = client.get("/api/conversation/nonexistent")
        assert resp.status_code == 404

    def test_success(self, client):
        wf_start = _mock_wf_process_msg_success()
        with patch("api.routes.messages.wf_process_msg", return_value=wf_start), \
             patch("api.routes.messages.wf_load_db", return_value={"events": [make_event()]}):
            start = client.post(
                "/api/start-conversation",
                json={"email_body": "Event please", "client_email": "test@example.com"},
            )
        sid = start.json()["session_id"]
        resp = client.get(f"/api/conversation/{sid}")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid
