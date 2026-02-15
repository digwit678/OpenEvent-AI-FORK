"""Tests for api/routes/events.py endpoints."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tests.api.conftest import make_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_with(*events):
    return {"events": list(events), "tasks": [], "config": {}}


def _empty_db():
    return {"events": [], "tasks": [], "config": {}}


# ---------------------------------------------------------------------------
# GET /api/events
# ---------------------------------------------------------------------------

class TestGetAllEvents:

    def test_empty_db(self, client):
        with patch("api.routes.events.wf_load_db", return_value=_empty_db()):
            resp = client.get("/api/events")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 0
        assert resp.json()["events"] == []

    def test_with_events(self, client, sample_event):
        with patch("api.routes.events.wf_load_db", return_value=_db_with(sample_event)):
            resp = client.get("/api/events")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 1


# ---------------------------------------------------------------------------
# GET /api/events/{event_id}
# ---------------------------------------------------------------------------

class TestGetEventById:

    def test_found(self, client, sample_event):
        with patch("api.routes.events.wf_load_db", return_value=_db_with(sample_event)):
            resp = client.get(f"/api/events/{sample_event['event_id']}")
        assert resp.status_code == 200
        assert resp.json()["event_id"] == sample_event["event_id"]

    def test_not_found(self, client):
        with patch("api.routes.events.wf_load_db", return_value=_empty_db()):
            resp = client.get("/api/events/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/event/{id}/deposit
# ---------------------------------------------------------------------------

class TestGetDepositStatus:

    def test_not_found(self, client):
        with patch("api.routes.events.wf_load_db", return_value=_empty_db()):
            resp = client.get("/api/event/nope/deposit")
        assert resp.status_code == 404

    def test_no_deposit(self, client):
        event = make_event(deposit_required=False)
        with patch("api.routes.events.wf_load_db", return_value=_db_with(event)):
            resp = client.get(f"/api/event/{event['event_id']}/deposit")
        assert resp.status_code == 200
        assert resp.json()["deposit_required"] is False

    def test_with_deposit(self, client, sample_event):
        with patch("api.routes.events.wf_load_db", return_value=_db_with(sample_event)):
            resp = client.get(f"/api/event/{sample_event['event_id']}/deposit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deposit_required"] is True
        assert data["deposit_paid"] is False


# ---------------------------------------------------------------------------
# POST /api/event/deposit/pay
# ---------------------------------------------------------------------------

class TestPayDeposit:

    def test_disabled_guard(self, client):
        """Mock endpoint should be disabled by default."""
        with patch.dict(os.environ, {"ENABLE_TEST_ENDPOINTS": "false"}, clear=False):
            resp = client.post("/api/event/deposit/pay", json={"event_id": "evt-001"})
        assert resp.status_code == 403

    def test_not_found(self, client):
        with patch.dict(os.environ, {"ENABLE_TEST_ENDPOINTS": "true"}, clear=False):
            with patch("api.routes.events.wf_load_db", return_value=_empty_db()):
                resp = client.post("/api/event/deposit/pay", json={"event_id": "nope"})
        assert resp.status_code == 404

    def test_wrong_step(self, client):
        event = make_event(current_step=2)
        with patch.dict(os.environ, {"ENABLE_TEST_ENDPOINTS": "true"}, clear=False):
            with patch("api.routes.events.wf_load_db", return_value=_db_with(event)):
                resp = client.post("/api/event/deposit/pay", json={"event_id": event["event_id"]})
        assert resp.status_code == 400

    def test_already_paid(self, client):
        event = make_event(deposit_paid=True)
        with patch.dict(os.environ, {"ENABLE_TEST_ENDPOINTS": "true"}, clear=False):
            with patch("api.routes.events.wf_load_db", return_value=_db_with(event)):
                resp = client.post("/api/event/deposit/pay", json={"event_id": event["event_id"]})
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_paid"

    def test_success_offer_not_accepted(self, client, sample_event):
        db = _db_with(sample_event)
        with patch.dict(os.environ, {"ENABLE_TEST_ENDPOINTS": "true"}, clear=False):
            with patch("api.routes.events.wf_load_db", return_value=db), \
                 patch("api.routes.events.wf_save_db") as mock_save, \
                 patch("activity.persistence.log_workflow_activity"):
                resp = client.post("/api/event/deposit/pay", json={"event_id": sample_event["event_id"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["workflow_continued"] is False
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/event/{id}/cancel
# ---------------------------------------------------------------------------

class TestCancelEvent:

    def test_bad_confirmation(self, client, sample_event):
        db = _db_with(sample_event)
        with patch("api.routes.events.wf_load_db", return_value=db):
            resp = client.post(
                f"/api/event/{sample_event['event_id']}/cancel",
                json={"event_id": sample_event["event_id"], "confirmation": "nope"},
            )
        assert resp.status_code == 400

    def test_id_mismatch(self, client, sample_event):
        db = _db_with(sample_event)
        with patch("api.routes.events.wf_load_db", return_value=db):
            resp = client.post(
                f"/api/event/{sample_event['event_id']}/cancel",
                json={"event_id": "wrong-id", "confirmation": "CANCEL"},
            )
        assert resp.status_code == 400

    def test_not_found(self, client):
        with patch("api.routes.events.wf_load_db", return_value=_empty_db()):
            resp = client.post(
                "/api/event/nope/cancel",
                json={"event_id": "nope", "confirmation": "CANCEL"},
            )
        assert resp.status_code == 404

    def test_already_cancelled(self, client):
        event = make_event(status="cancelled")
        event["cancelled_at"] = "2026-04-01T00:00:00Z"
        db = _db_with(event)
        with patch("api.routes.events.wf_load_db", return_value=db):
            resp = client.post(
                f"/api/event/{event['event_id']}/cancel",
                json={"event_id": event["event_id"], "confirmation": "CANCEL"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_cancelled"

    def test_success(self, client, sample_event):
        db = _db_with(sample_event)
        with patch("api.routes.events.wf_load_db", return_value=db), \
             patch("api.routes.events.wf_save_db"), \
             patch("activity.persistence.log_workflow_activity"), \
             patch("workflows.io.database.delete_event", return_value={"deleted": True}):
            resp = client.post(
                f"/api/event/{sample_event['event_id']}/cancel",
                json={"event_id": sample_event["event_id"], "confirmation": "CANCEL"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancellation_type"] == "standard"
