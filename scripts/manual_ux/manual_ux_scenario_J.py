#!/usr/bin/env python3
"""
Manual UX Scenario J — Alternative dates for a better room and late change.

Simulates a large group that requests larger-room alternatives, selects one of
the suggested dates, later shifts the event again, and completes confirmation
after the updated offer is accepted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from workflow_email import load_db, process_msg
from workflows.llm import adapter as llm_adapter

DB_PATH = Path(__file__).resolve().parents[1] / "manual_ux_scenario_J.json"


def main() -> None:
    os.environ.setdefault("AGENT_MODE", "stub")

    mapping: Dict[str, Dict[str, Any]] = {}
    turns = _script(mapping)
    intent_overrides = _build_intent_overrides(turns)

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    def fake_route(payload: Dict[str, Any]) -> Any:
        msg_id = payload.get("msg_id")
        if msg_id in intent_overrides:
            label, conf = intent_overrides[msg_id]
            return label, conf
        return original_route(payload)

    if hasattr(llm_adapter.adapter, "extract_user_information"):
        original_extract = llm_adapter.adapter.extract_user_information
        llm_adapter.adapter.extract_user_information = fake_extract  # type: ignore[assignment]
    else:
        original_extract = llm_adapter.adapter.extract_entities  # type: ignore[attr-defined]
        llm_adapter.adapter.extract_entities = fake_extract  # type: ignore[attr-defined]

    original_route = llm_adapter.adapter.route_intent
    llm_adapter.adapter.route_intent = fake_route  # type: ignore[assignment]

    try:
        if DB_PATH.exists():
            DB_PATH.unlink()

        for idx, turn in enumerate(turns, start=1):
            result = process_msg(_message(turn["body"], turn["msg_id"]), db_path=DB_PATH)
            event = _current_event()

            draft_topic = (
                result.get("draft_messages", [{}])[-1].get("topic") if result.get("draft_messages") else None
            )
            offers = (
                [
                    {"id": offer.get("offer_id"), "status": offer.get("status")}
                    for offer in (event.get("offers") or [])
                ]
                if event
                else []
            )
            audit_tail = (event.get("audit") or [])[-1] if event else None
            state_line = {
                "step": event.get("current_step") if event else None,
                "caller": event.get("caller_step") if event else None,
                "thread": event.get("thread_state") if event else None,
                "chosen_date": event.get("chosen_date") if event else None,
                "locked_room": event.get("locked_room_id") if event else None,
                "requirements_hash": event.get("requirements_hash") if event else None,
                "room_eval_hash": event.get("room_eval_hash") if event else None,
                "counter_count": (event.get("negotiation_state") or {}).get("counter_count") if event else None,
            }
            alt_dates = result.get("alt_dates_for_better_room")
            if alt_dates is None:
                alt_dates = (result.get("payload") or {}).get("alt_dates_for_better_room")
            summary = {
                "turn": idx,
                "msg_id": turn["msg_id"],
                "action": result.get("action"),
                "draft_topic": draft_topic,
                "state": state_line,
                "offers": offers,
                "audit_tail": audit_tail,
                "alt_dates_for_better_room": alt_dates,
            }
            print(json.dumps(summary, ensure_ascii=False))
    finally:
        llm_adapter.adapter.route_intent = original_route  # type: ignore[assignment]
        if hasattr(llm_adapter.adapter, "extract_user_information"):
            llm_adapter.adapter.extract_user_information = original_extract  # type: ignore[assignment]
        else:
            llm_adapter.adapter.extract_entities = original_extract  # type: ignore[assignment]
        if DB_PATH.exists():
            DB_PATH.unlink()


def _build_intent_overrides(turns: list[Dict[str, Any]]) -> Dict[str, tuple[str, float]]:
    overrides: Dict[str, tuple[str, float]] = {turns[0]["msg_id"]: ("other", 0.99)}
    for turn in turns[1:]:
        overrides[turn["msg_id"]] = ("event_request", 0.99)
    return overrides


def _message(body: str, msg_id: str) -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Scenario J Client",
        "from_email": "clientJ@example.com",
        "subject": "Manual UX Scenario J",
        "ts": "2025-05-05T09:00:00Z",
        "body": body,
    }


def _script(mapping: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
    turns: list[Dict[str, Any]] = [
        {"msg_id": "TURN0", "body": "Hello?"},
        {
            "msg_id": "TURN1",
            "body": "We need space for 60 participants on 10 July, ideally Room A.",
            "info": {"date": "2025-07-10", "event_date": "10.07.2025", "participants": 60, "room": "Room A"},
        },
        {
            "msg_id": "TURN2",
            "body": "The rooms on that date aren't a good fit — any larger rooms on nearby dates?",
            "info": {"room_feedback": "not_good_enough"},
        },
        {
            "msg_id": "TURN3",
            "body": "Let's lock the 24 July option if Room B works.",
            "info": {"date": "2025-07-24", "event_date": "24.07.2025"},
        },
        {
            "msg_id": "TURN4_HIL",
            "body": "HIL approval for the updated availability summary.",
            "info": {"hil_approve_step": 3},
        },
        {
            "msg_id": "TURN5_HIL",
            "body": "HIL approval for the revised offer draft.",
            "info": {"hil_approve_step": 4},
        },
        {
            "msg_id": "TURN6",
            "body": "We accept the 24 July proposal.",
        },
        {
            "msg_id": "TURN7",
            "body": "Could we shift everything to 5 August instead?",
            "info": {"date": "2025-08-05", "event_date": "05.08.2025"},
        },
        {
            "msg_id": "TURN7_HIL",
            "body": "HIL approval for the new availability summary.",
            "info": {"hil_approve_step": 3},
        },
        {
            "msg_id": "TURN7B_HIL",
            "body": "HIL approval for the refreshed offer draft.",
            "info": {"hil_approve_step": 4},
        },
        {
            "msg_id": "TURN8",
            "body": "The August 5th offer looks great — we accept.",
        },
        {
            "msg_id": "TURN8_HIL",
            "body": "Final HIL approval to send the confirmation.",
            "info": {"hil_approve_step": 7},
        },
    ]

    for turn in turns:
        info = turn.get("info")
        if info:
            mapping[turn["msg_id"]] = info  # type: ignore[index]
    return turns


def _current_event() -> Optional[Dict[str, Any]]:
    db = load_db(DB_PATH)
    return db["events"][0] if db.get("events") else None


if __name__ == "__main__":
    main()
