#!/usr/bin/env python3
"""
Manual UX conversation test for OpenEvent workflow v3.

Simulates a realistic client conversation spanning Steps 1–7 and prints
TURN metadata, draft topics, and key workflow state after each exchange.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from workflow_email import load_db, process_msg
from workflows.llm import adapter as llm_adapter

DB_PATH = Path(__file__).resolve().parents[1] / "manual_ux_conversation.json"


def main() -> None:
    os.environ.setdefault("AGENT_MODE", "stub")

    mapping: Dict[str, Dict[str, Any]] = {}
    intent_overrides: Dict[str, str] = {}

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    def fake_route(payload: Dict[str, Any]) -> Any:
        # Prefer deterministic intent overrides for this scripted run.
        msg_id = payload.get("msg_id")
        if msg_id in intent_overrides:
            return intent_overrides[msg_id], 0.99
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

        turns = _script(mapping, intent_overrides)
        for idx, turn in enumerate(turns, start=1):
            result = process_msg(
                _message(turn["body"], turn["msg_id"]), db_path=DB_PATH
            )
            event = _current_event()
            draft_topic = result.get("draft_messages", [{}])[-1].get("topic") if result.get("draft_messages") else None
            offers = [
                {"id": offer.get("offer_id"), "status": offer.get("status")}
                for offer in (event.get("offers") or [])
            ] if event else []
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


def _message(body: str, msg_id: str) -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Manual UX Client",
        "from_email": "client@example.com",
        "subject": "Manual UX Conversation",
        "ts": "2025-01-01T09:00:00Z",
        "body": body,
    }


def _script(mapping: Dict[str, Dict[str, Any]], intent_overrides: Dict[str, str]) -> list[Dict[str, str]]:
    mapping.update(
        {
            "TURN1": {"date": "2025-06-10", "participants": 22, "room": "Room A"},
            "TURN2": {"event_date": "10.06.2025"},
            "TURN4": {"hil_approve_step": 3},
            "TURN6": {"offer_total_override": 1800.0},
            "TURN8": {"participants": 26},
            "TURN9": {"hil_approve_step": 3},
            "TURN10": {"hil_approve_step": 3},
            "TURN12": {"hil_approve_step": 7},
        }
    )
    intent_overrides["TURN0"] = "other"
    intent_overrides.update({f"TURN{i}": "event_request" for i in range(1, 13)})
    return [
        {"msg_id": "TURN0", "body": "Is anyone there?"},
        {"msg_id": "TURN1", "body": "Hello, we're planning an offsite for 22 people. Any dates in June?"},
        {"msg_id": "TURN2", "body": "Let's lock June 10th, please."},
        {"msg_id": "TURN3", "body": "Thanks for the availability update."},
        {"msg_id": "TURN4", "body": "HIL approval for Room A."},
        {"msg_id": "TURN5", "body": "Send over the detailed offer."},
        {"msg_id": "TURN6", "body": "Could you bring the total closer to 1800 CHF?"},
        {"msg_id": "TURN7", "body": "Thanks, the new total works. We accept."},
        {"msg_id": "TURN8", "body": "Actually, make it for 26 people."},
        {"msg_id": "TURN9", "body": "Room A still fine for us."},
        {"msg_id": "TURN10", "body": "Manager approves the update."},
        {"msg_id": "TURN11", "body": "Please confirm the booking. Deposit paid via transfer."},
        {"msg_id": "TURN12", "body": "HIL confirmation send-off."},
    ]


def _current_event() -> Optional[Dict[str, Any]]:
    db = load_db(DB_PATH)
    return db["events"][0] if db.get("events") else None


if __name__ == "__main__":
    main()