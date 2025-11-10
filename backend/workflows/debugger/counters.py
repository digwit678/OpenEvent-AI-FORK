from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional, Tuple

__all__ = ["step1_count", "step2_count", "step3_count", "compute_step_counters"]


def _truthy_string(value: Any) -> bool:
    if value in (None, "", False):
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"not specified", "none"}:
            return False
        return True
    if isinstance(value, (int, float)):
        return value > 0
    return bool(value)


def _participants_value(state: MutableMapping[str, Any]) -> Optional[Any]:
    candidates = [
        state.get("participants"),
        state.get("number_of_participants"),
        state.get("participants_captured"),
    ]
    user_info = state.get("user_info")
    if isinstance(user_info, dict):
        candidates.append(user_info.get("participants"))
    event_data = state.get("event_data")
    if isinstance(event_data, dict):
        candidates.append(event_data.get("Number of Participants"))
    for candidate in candidates:
        if candidate not in (None, "", "Not specified"):
            return candidate
    return None


def step1_count(state: MutableMapping[str, Any]) -> Tuple[int, int]:
    """Return (met, total) for Step 1 intake gates."""

    total = 2
    met = 0
    intent_present = _truthy_string(
        state.get("intent")
        or state.get("intent_label")
        or state.get("detected_intent")
    )
    if intent_present:
        met += 1

    participants_value = _participants_value(state)
    participants_ok = _truthy_string(participants_value)
    if participants_ok:
        met += 1

    return met, total


def step2_count(state: MutableMapping[str, Any]) -> Tuple[int, int]:
    """Return (met, total) for Step 2 date confirmation gates."""

    total = 2
    met = 0
    chosen_date = (
        state.get("chosen_date")
        or state.get("event_date")
        or state.get("date")
    )
    if _truthy_string(chosen_date):
        met += 1

    date_confirmed = state.get("date_confirmed")
    if isinstance(date_confirmed, bool):
        confirmed = date_confirmed
    else:
        confirmed = _truthy_string(date_confirmed)
    if confirmed:
        met += 1

    return met, total


def _requirements_match(state: MutableMapping[str, Any]) -> bool:
    req_hash = state.get("requirements_hash") or state.get("req_hash")
    eval_hash = state.get("room_eval_hash") or state.get("eval_hash")
    locked_room = (
        state.get("locked_room_id")
        or state.get("selected_room")
        or (state.get("room_pending_decision") or {}).get("selected_room")
    )
    if not locked_room or not req_hash or not eval_hash:
        return False
    return str(req_hash) == str(eval_hash)


def step3_count(state: MutableMapping[str, Any]) -> Tuple[int, int]:
    """Return (met, total) for Step 3 room selection gates."""

    total = 3
    met = 0

    date_confirmed = state.get("date_confirmed")
    if isinstance(date_confirmed, bool):
        confirmed = date_confirmed
    else:
        confirmed = _truthy_string(date_confirmed)
    if confirmed:
        met += 1

    room_selected = (
        state.get("selected_room")
        or state.get("locked_room_id")
        or (state.get("room_pending_decision") or {}).get("selected_room")
    )
    if _truthy_string(room_selected):
        met += 1

    if _requirements_match(state):
        met += 1

    return met, total


def compute_step_counters(state: MutableMapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Compute step counters for debugger consumers."""

    step1_met, step1_total = step1_count(state)
    step2_met, step2_total = step2_count(state)
    step3_met, step3_total = step3_count(state)
    counters = {
        "Step1_Intake": {
            "met": step1_met,
            "total": step1_total,
        },
        "Step2_Date": {
            "met": step2_met,
            "total": step2_total,
        },
        "Step3_Room": {
            "met": step3_met,
            "total": step3_total,
        },
    }
    return counters
