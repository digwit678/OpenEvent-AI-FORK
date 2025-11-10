from __future__ import annotations

import importlib
import re
from datetime import datetime

import pytest

from backend.workflows.common.types import IncomingMessage, WorkflowState

date_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")


def _contains_room_dates_block(text: str) -> bool:
    pattern = r"Room\s+[A-Z].*Available on:\s*(?:\d{2}\.\d{2}\.\d{4}|[A-Za-z]{3}\s+\d{2}\s+[A-Za-z]{3}\s+\d{4})"
    return bool(re.search(pattern, text))


def _assert_no_full_menu_dump(text: str) -> None:
    too_many_bullets = len(re.findall(r"^\s*[-•]\s+", text, flags=re.MULTILINE)) > 8
    keywords = [
        "Starter:",
        "Main:",
        "Dessert:",
        "CHF ",
        "Gourmet dessert selection",
        "Choice of 3 main",
    ]
    has_menu_keywords = any(keyword in text for keyword in keywords)
    assert not (too_many_bullets and has_menu_keywords), "Full menu dump detected where not allowed."


def _actions_are_only_date_confirms(actions) -> bool:
    return bool(actions) and all(action.get("type") == "select_date" for action in actions)


def _actions_are_room_selects(actions) -> bool:
    return bool(actions) and all(action.get("type") == "select_room" for action in actions)


def _build_message(subject: str, body: str) -> IncomingMessage:
    return IncomingMessage(
        msg_id=f"msg-{datetime.utcnow().timestamp()}",
        from_name="Test Client",
        from_email="client@example.com",
        subject=subject,
        body=body,
        ts=datetime.utcnow().isoformat() + "Z",
    )


def _initial_state(message: IncomingMessage, tmp_path) -> WorkflowState:
    return WorkflowState(message=message, db_path=tmp_path / "events.json", db={"events": []})


def _render_step2_draft(subject: str, body: str, tmp_path, monkeypatch: pytest.MonkeyPatch):
    message = _build_message(subject, body)
    state = _initial_state(message, tmp_path)
    state.event_entry = {
        "event_id": "EVT-ROOM",
        "thread_state": "Awaiting Client",
        "requirements": {},
        "current_step": 2,
    }
    state.set_thread_state("Awaiting Client")

    range_payload = [
        {
            "iso_date": "2026-02-07",
            "date_label": "Sat 07 Feb 2026",
            "room": "Room A",
            "status": "Available",
        },
        {
            "iso_date": "2026-02-14",
            "date_label": "Sat 14 Feb 2026",
            "room": "Room A",
            "status": "Available",
        },
        {
            "iso_date": "2026-02-07",
            "date_label": "Sat 07 Feb 2026",
            "room": "Room B",
            "status": "Option",
        },
    ]

    monkeypatch.setattr(date_module, "_search_range_availability", lambda *args, **kwargs: range_payload)
    monkeypatch.setattr(date_module, "list_free_dates", lambda count, db, preferred_room: [
        "01.02.2026",
        "08.02.2026",
        "15.02.2026",
    ])

    classification = date_module.detect_general_room_query(body, state)
    date_module._present_general_room_qna(state, state.event_entry, classification, thread_id="THREAD-1")
    return state.draft_messages[-1]


def _render_step3_draft(subject: str, body: str, tmp_path, monkeypatch: pytest.MonkeyPatch):
    message = _build_message(subject, body)
    state = _initial_state(message, tmp_path)
    state.event_id = "EVT-ROOM"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "14.02.2026",
        "date_confirmed": True,
        "thread_state": "Awaiting Client",
        "requirements": {"number_of_participants": 30},
        "requirements_hash": "hash",
        "room_eval_hash": None,
        "preferences": {"wish_products": ["Dinner XXL"], "keywords": ["wine"]},
    }
    state.user_info = {
        "range_query_detected": True,
        "vague_month": "February",
        "vague_weekday": "Saturday",
    }

    monkeypatch.setattr(
        room_module,
        "evaluate_room_statuses",
        lambda _db, _date: [
            {"Room A": "Available"},
            {"Room B": "Option"},
        ],
    )
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        room_module,
        "_dates_in_month_weekday_wrapper",
        lambda *_args, **_kwargs: [
            "2026-02-07",
            "2026-02-14",
            "2026-02-21",
        ],
    )
    monkeypatch.setattr(
        room_module,
        "_closest_alternatives_wrapper",
        lambda *_args, **_kwargs: [
            "2026-02-21",
            "2026-02-28",
            "2026-03-07",
        ],
    )

    def fake_room_status_on_date(_db, date_ddmmyyyy, room_name):
        if room_name == "Room A" and date_ddmmyyyy in {"07.02.2026", "14.02.2026", "21.02.2026"}:
            return "Available"
        if room_name == "Room B" and date_ddmmyyyy in {"07.02.2026", "14.02.2026", "21.02.2026"}:
            return "Option"
        return "Unavailable"

    monkeypatch.setattr(room_module, "room_status_on_date", fake_room_status_on_date)

    room_module.process(state)
    return state.draft_messages[-1]


@pytest.mark.parametrize("subject, body", [
    (
        "Private Dinner Event – Date Options in February",
        """Hello,

We’d like to organize a private dinner for our family (around 30 guests) at your venue.
We’re flexible but are thinking sometime in February, preferably a Saturday evening.

Requirements:
– Long dining table setup
– Three-course dinner menu with wine
– Background music (live or playlist)

Could you please let me know which dates in February you still have available and what menu options you can offer?

Many thanks,
Laura Meier
laura.meier@bluewin.ch
+41 78 222 44 55
        """,
    ),
])
def test_step2_hybrid_shows_room_dates_plus_compact_products(subject, body, tmp_path, monkeypatch):
    draft = _render_step2_draft(subject, body, tmp_path, monkeypatch)

    assert str(draft["step"]).startswith("2"), "Expected Step-2 draft."

    assert _contains_room_dates_block(draft["body"]), "Missing per-room 'Available on:' dates in Step-2."

    assert "Products & Catering (summary)" in draft["body"]
    _assert_no_full_menu_dump(draft["body"])

    assert _actions_are_only_date_confirms(draft["actions"]), "Step-2 must only offer date confirm actions."

    footer = draft.get("footer")
    footer_text = footer.get("text", "") if isinstance(footer, dict) else (footer or "")
    assert "Step: 2 Date Confirmation" in footer_text
    assert "Next: Confirm date" in footer_text


@pytest.mark.parametrize("subject, body", [
    (
        "Hi there",
        """Hi there,

We’re planning a private family dinner for about 30 guests and are thinking Saturday evenings in February.
Could you tell us which rooms are available on those Saturdays for ~30 people?
If Sat, 14 February is free, that would be our first choice; otherwise we’re happy to pick from the Saturdays you suggest.

Billing details (we’ll complete anything missing): ACME AG, Bahnhofstrasse 1, Zürich, CH (VAT CHE-123.456.789)
Contact: Laura Meer l***@bluewin.ch [redacted-number]
Thanks
        """,
    ),
])
def test_step3_rooms_plus_alt_dates_no_menu_dump(subject, body, tmp_path, monkeypatch):
    draft = _render_step3_draft(subject, body, tmp_path, monkeypatch)

    assert str(draft["step"]).startswith("3"), "Expected Step-3 draft."

    assert _actions_are_room_selects(draft["actions"]), "Step-3 must offer room selection actions."

    body_text = draft.get("body_markdown") or draft["body"]
    assert "Available dates" in body_text or "Alternative dates" in body_text
    assert "Products" in body_text or "Catering" in body_text
    _assert_no_full_menu_dump(body_text)

    assert "Alternative Dates" in body_text, "Step-3 should show alternative dates."
    if "Alternative Dates (top 5)" in body_text or "Alternative Dates (top 3)" in body_text:
        assert "more options" in body_text.lower() or "ask for more" in body_text.lower()

    footer = draft.get("footer")
    footer_text = footer.get("text", "") if isinstance(footer, dict) else (footer or "")
    assert "Step: 3 Room Availability" in footer_text
    assert "Next: Choose a room" in footer_text
