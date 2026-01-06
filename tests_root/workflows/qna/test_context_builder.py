from __future__ import annotations

import datetime as dt

import pytest

from backend.workflows.qna.context_builder import CASE_MAP, build_qna_context


def test_conflicting_date_pattern_overrides_captured_date():
    captured = {"date": "2024-02-12", "attendees": 50, "products": []}
    q_values = {"date_pattern": "Saturdays in April"}
    context = build_qna_context(
        "select_dependent",
        "date_pattern_availability",
        q_values,
        captured,
    )

    assert context.effective["D"].value == "Saturdays in April"
    assert context.effective["D"].source == "Q"
    assert context.effective["N"].value == 50
    assert context.effective["N"].source == "C"
    assert context.effective["R"].source == "UNUSED"
    assert context.case_tags == CASE_MAP["date_pattern_availability"]


def test_catalog_capacity_uses_query_attendees():
    context = build_qna_context(
        "select_static",
        "catalog_by_capacity",
        {"n_exact": 60},
        {},
    )

    assert context.effective["N"].value == 60
    assert context.effective["N"].source == "Q"
    assert context.effective["D"].source == "UNUSED"
    assert context.case_tags == CASE_MAP["catalog_by_capacity"]


def test_static_room_question_marks_date_unused():
    context = build_qna_context(
        "select_static",
        "room_capacity_static",
        {"room": "Room B"},
        {},
    )

    assert context.effective["R"].value == "Room B"
    assert context.effective["R"].source == "Q"
    assert context.effective["N"].source == "UNUSED"
    assert context.effective["D"].source == "UNUSED"


def test_event_specific_recommendation_uses_captured_defaults():
    captured = {
        "date": "2024-05-10",
        "attendees": 42,
        "products": ["vegan lunch"],
    }
    context = build_qna_context(
        "select_dependent",
        "room_list_for_us",
        {},
        captured,
    )
    assert context.effective["D"].value == "2024-05-10"
    assert context.effective["D"].source == "C"
    assert context.effective["N"].value == 42
    assert context.effective["N"].source == "C"
    assert context.effective["P"].value == ["vegan lunch"]
    assert context.effective["P"].source == "C"


def test_repertoire_check_sets_today_and_fallback_products():
    reference_date = dt.date(2024, 3, 1)

    context = build_qna_context(
        "select_static",
        "repertoire_check",
        {"products": ["vegan lunch"]},
        {},
        now_fn=lambda: reference_date,
    )
    assert context.effective["D"].source == "F"
    assert context.effective["D"].value == reference_date.isoformat()
    assert context.effective["P"].value == ["vegan lunch"]
    assert context.effective["P"].source == "Q"


def test_update_candidate_marks_unhandled_without_db():
    context = build_qna_context(
        "update_candidate",
        "update_candidate",
        {"room": "Room B"},
        {"room": "Room A"},
    )
    assert context.handled is False
    assert context.unresolved == ["update_flow"]


def test_room_capacity_delta_adds_delta_without_mutating_c():
    captured = {"attendees": 40, "room": "Room A"}
    context = build_qna_context(
        "select_static",
        "room_capacity_delta",
        {"n_exact": 5},
        captured,
    )
    assert context.effective["N"].value == 45
    assert context.effective["N"].source == "C"
    assert context.effective["N"].meta["delta"] == 5
    assert context.effective["N"].meta["base"] == 40
    assert context.effective["R"].value == "Room A"
