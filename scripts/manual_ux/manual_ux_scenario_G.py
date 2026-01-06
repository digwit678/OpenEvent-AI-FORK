#!/usr/bin/env python3
"""
Manual UX Scenario G — Deposit request with delayed payment.

Walks through a standard confirmation path where the client asks for a deposit
hold, receives the deposit request (with HIL approval), later confirms payment,
and finally receives the confirmed booking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from workflow_email import load_db, process_msg, save_db
from workflows.llm import adapter as llm_adapter

DB_PATH = Path(__file__).resolve().parents[1] / "manual_ux_scenario_G.json"


TurnHook = Callable[[], None]


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
            pre_hook: Optional[TurnHook] = turn.get("pre")  # type: ignore[assignment]
            if pre_hook:
                pre_hook()

            result = process_msg(_message(turn["body"], turn["msg_id"]), db_path=DB_PATH)
            event = _current_event()

            post_hook: Optional[TurnHook] = turn.get("post")  # type: ignore[assignment]
            if post_hook:
                post_hook()

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
            summary = {
                "turn": idx,
                "msg_id": turn["msg_id"],
                "action": result.get("action"),
                "draft_topic": draft_topic,
                "state": state_line,
                "offers": offers,
                "audit_tail": audit_tail,
            }
            print(json.dumps(summary, indent=2, ensure_ascii=False))
    finally:
        llm_adapter.adapter.route_intent = original_route  # type: ignore[assignment]
        if hasattr(llm_adapter.adapter, "extract_user_information"):
            llm_adapter.adapter.extract_user_information = original_extract  # type: ignore[assignment]
        else:
            llm_adapter.adapter.extract_entities = original_extract  # type: ignore[assignment]
        if DB_PATH.exists():
            # Clean up the temporary DB so subsequent runs start fresh.
            DB_PATH.unlink()


def _build_intent_overrides(turns: list[Dict[str, Any]]) -> Dict[str, tuple[str, float]]:
    overrides: Dict[str, tuple[str, float]] = {turns[0]["msg_id"]: ("other", 0.99)}
    for turn in turns[1:]:
        overrides[turn["msg_id"]] = ("event_request", 0.99)
    return overrides


def _message(body: str, msg_id: str) -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Scenario G Client",
        "from_email": "clientG@example.com",
        "subject": "Manual UX Scenario G",
        "ts": "2025-03-15T09:00:00Z",
        "body": body,
    }


def _set_deposit_state() -> None:
    db = load_db(DB_PATH)
    events = db.get("events") or []
    if not events:
        return
    event = events[0]
    event["deposit_state"] = {
        "required": True,
        "percent": 30,
        "status": "required",
        "due_amount": 2250.0,
    }
    save_db(db, DB_PATH)


def _script(mapping: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
    turns: list[Dict[str, Any]] = [
        {"msg_id": "TURN0", "body": "Is anyone there?"},
        {
            "msg_id": "TURN1",
            "body": "Hi there! We’d like to reserve Room C on 5 May for 28 guests.",
            "info": {"date": "2025-05-05", "participants": 28, "room": "Room C"},
        },
        {
            "msg_id": "TURN2",
            "body": "Sounds promising so far.",
        },
        {
            "msg_id": "TURN3_HIL",
            "body": "HIL approval for the availability summary.",
            "info": {"hil_approve_step": 3},
        },
        {
            "msg_id": "TURN4",
            "body": "Thanks, happy to review the formal offer.",
        },
        {
            "msg_id": "TURN5",
            "body": "Great overview. Let’s proceed.",
        },
        {
            "msg_id": "TURN6",
            "body": "We accept the offer as proposed.",
        },
        {
            "msg_id": "TURN6A",
            "body": "Before we wrap up, please note we might be 30 guests now.",
            "info": {"participants": 30},
        },
        {
            "msg_id": "TURN6A_HIL",
            "body": "HIL approval for the updated headcount.",
            "info": {"hil_approve_step": 3},
        },
        {
            "msg_id": "TURN6B",
            "body": "Thanks for updating everything — we accept the revised offer.",
        },
        {
            "msg_id": "TURN7",
            "body": "Could you pencil in the date and send the deposit request?",
            "pre": _set_deposit_state,
        },
        {
            "msg_id": "TURN7_HIL",
            "body": "HIL approval to send the deposit instructions.",
            "info": {"hil_approve_step": 7},
        },
        {
            "msg_id": "TURN8",
            "body": "Deposit has been transferred this morning.",
        },
        {
            "msg_id": "TURN9_HIL",
            "body": "Final HIL approval to dispatch the confirmation.",
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
