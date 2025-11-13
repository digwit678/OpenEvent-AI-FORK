from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.qna_readonly import RoomAvailabilityRow, RoomSummary
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.qna.engine import StructuredQnAResult, build_structured_qna_result


@pytest.fixture
def workflow_state():
    message = IncomingMessage(
        msg_id="msg-1",
        from_name="Client",
        from_email="client@example.com",
        subject="",
        body="",
        ts=None,
    )
    state = WorkflowState(
        message=message,
        db_path=Path("."),
        db={},
    )
    state.event_entry = {"current_step": 3}
    state.intent = None
    state.confidence = 0.0
    return state


def test_structured_catalog_by_capacity_calls_read_only_adapter(monkeypatch, workflow_state):
    calls = {}

    def fake_list_rooms_by_capacity(*, min_capacity, capacity_range, product_requirements):
        calls["kwargs"] = {
            "min_capacity": min_capacity,
            "capacity_range": capacity_range,
            "product_requirements": product_requirements,
        }
        return [
            RoomSummary(
                room_id="room_b",
                room_name="Room B",
                capacity_max=80,
                capacity_by_layout={"theater": 70},
                products=list(product_requirements),
            )
        ]

    def fake_verbalizer(payload):
        return {"body_markdown": "Mock answer", "model": "mock", "used_fallback": True}

    monkeypatch.setattr("backend.workflows.qna.engine.list_rooms_by_capacity", fake_list_rooms_by_capacity)
    monkeypatch.setattr("backend.workflows.qna.engine.render_qna_answer", fake_verbalizer)

    extraction = {
        "msg_type": "event",
        "qna_intent": "select_static",
        "qna_subtype": "catalog_by_capacity",
        "q_values": {"n_exact": 60},
    }
    result = build_structured_qna_result(workflow_state, extraction)
    assert isinstance(result, StructuredQnAResult)
    assert result.handled is True
    assert result.action_payload["handled"] is True
    assert result.action_payload["db_summary"]["rooms"][0]["room_name"] == "Room B"
    assert calls["kwargs"]["min_capacity"] == 60
    assert result.body_markdown == "Mock answer"
    assert "extraction" in result.action_payload
    assert result.debug["extraction"]["qna_subtype"] == "catalog_by_capacity"
    assert workflow_state.turn_notes["structured_qna_handled"] is True


def test_update_candidate_skips_db_adapters(monkeypatch, workflow_state):
    def fail(*args, **kwargs):
        raise AssertionError("DB adapter should not be called for update flows")

    monkeypatch.setattr("backend.workflows.qna.engine.list_rooms_by_capacity", fail)
    monkeypatch.setattr("backend.workflows.qna.engine.fetch_room_availability", fail)
    monkeypatch.setattr("backend.workflows.qna.engine.fetch_product_repertoire", fail)
    monkeypatch.setattr("backend.workflows.qna.engine.load_room_static", fail)

    extraction = {
        "msg_type": "event",
        "qna_intent": "update_candidate",
        "qna_subtype": "update_candidate",
        "q_values": {"room": "Room B"},
    }
    result = build_structured_qna_result(workflow_state, extraction)
    assert isinstance(result, StructuredQnAResult)
    assert result.handled is False
    assert result.action_payload["handled"] is False
    assert result.action_payload["db_summary"]["rooms"] == []
    assert result.body_markdown is None
    assert result.debug["extraction"]["qna_subtype"] == "update_candidate"


def test_room_availability_path_uses_exclude_and_products(monkeypatch, workflow_state):
    calls = {}

    def fake_fetch_room_availability(*, date_scope, attendee_scope, room_filter, exclude_rooms, product_requirements):
        calls["kwargs"] = {
            "date_scope": date_scope,
            "attendee_scope": attendee_scope,
            "room_filter": room_filter,
            "exclude_rooms": list(exclude_rooms),
            "product_requirements": list(product_requirements),
        }
        return [
            RoomAvailabilityRow(
                room_id="room_c",
                room_name="Room C",
                capacity_max=120,
                date="2024-04-06",
                status="available",
                features=["Projector"],
                products=list(product_requirements),
            )
        ]

    def fake_verbalizer(payload):
        return {"body_markdown": "Availability answer", "model": "mock", "used_fallback": True}

    monkeypatch.setattr("backend.workflows.qna.engine.fetch_room_availability", fake_fetch_room_availability)
    monkeypatch.setattr("backend.workflows.qna.engine.render_qna_answer", fake_verbalizer)

    workflow_state.event_entry = {
        "current_step": 3,
        "requirements": {"number_of_participants": 40},
        "wish_products": ["Projector & Screen"],
    }

    extraction = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {"exclude_rooms": ["Room A"]},
    }
    result = build_structured_qna_result(workflow_state, extraction)
    assert result.handled is True
    assert calls["kwargs"]["product_requirements"] == ["Projector & Screen"]
    assert calls["kwargs"]["exclude_rooms"] == ["Room A"]
    assert isinstance(calls["kwargs"]["date_scope"], dict)
    assert result.action_payload["db_summary"]["rooms"][0]["room_id"] == "room_c"


def test_room_availability_respects_december_pattern(workflow_state):
    extraction = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {
            "date_pattern": "second week of December 2026 around December 10 or 11",
            "n_exact": 22,
        },
    }
    workflow_state.event_entry = {
        "current_step": 3,
        "requirements": {"number_of_participants": 22},
    }
    result = build_structured_qna_result(workflow_state, extraction)
    assert result.handled is True
    room_rows = result.action_payload["db_summary"]["rooms"]
    assert any(row["date"] == "2026-12-10" for row in room_rows)
    assert any(row["date"] == "2026-12-11" for row in room_rows)
    effective_d = result.debug["effective"]["D"]
    assert effective_d["source"] == "Q"
    assert effective_d["meta"].get("month_index") == 12
    assert 10 in effective_d["meta"].get("days_hint", [])
    assert 11 in effective_d["meta"].get("days_hint", [])


def test_attendee_range_precedence_over_captured(workflow_state):
    workflow_state.event_entry = {
        "current_step": 3,
        "requirements": {"number_of_participants": 22},
    }
    extraction = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {
            "n_range": {"min": 30, "max": 40},
        },
    }
    result = build_structured_qna_result(workflow_state, extraction)
    effective_n = result.debug["effective"]["N"]
    assert effective_n["source"] == "Q"
    assert effective_n["value"] == {"min": 30, "max": 40}
    assert result.action_payload["effective"]["N"]["value"] == {"min": 30, "max": 40}


def test_product_precedence_prefers_query(workflow_state):
    workflow_state.event_entry = {
        "current_step": 3,
        "products": ["Coffee service"],
    }
    extraction = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {
            "products": ["Projector & Screen"],
        },
    }
    result = build_structured_qna_result(workflow_state, extraction)
    effective_p = result.debug["effective"]["P"]
    assert effective_p["source"] == "Q"
    assert effective_p["value"] == ["Projector & Screen"]


def test_room_exclusion_respected(workflow_state):
    workflow_state.event_entry = {
        "current_step": 3,
        "requirements": {"number_of_participants": 28},
    }
    extraction = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_exclusion_followup",
        "q_values": {
            "exclude_rooms": ["Room A"],
        },
    }
    result = build_structured_qna_result(workflow_state, extraction)
    assert result.action_payload["exclude_rooms"] == ["Room A"]
    assert result.debug["effective"]["R"]["source"] == "UNUSED"
    assert result.debug["effective"]["N"]["value"] == 28
