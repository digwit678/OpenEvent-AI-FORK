from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Dict, Optional, Tuple

from backend.adapters.agent_adapter import AgentAdapter, get_agent_adapter, reset_agent_adapter
from backend.domain import IntentLabel

from backend.workflows.common.room_rules import (
    USER_INFO_KEYS,
    clean_text,
    normalize_language,
    normalize_phone,
    normalize_room,
    sanitize_participants,
)
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.datetime_parse import parse_first_date, parse_time_range

adapter: AgentAdapter = get_agent_adapter()

_MONTHS = {name.lower(): idx for idx, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    start=1,
)}
_DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+of\s+([A-Za-z]+)\b", re.IGNORECASE)


def _infer_date_from_body(body: str) -> Optional[str]:
    match = _DAY_RE.search(body or "")
    if not match:
        return None
    try:
        day = int(match.group(1))
    except ValueError:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if not month:
        return None
    clamped_day = max(1, min(day, 28))
    today = dt.date.today()
    try:
        candidate = dt.date(today.year, month, clamped_day)
    except ValueError:
        return None
    if candidate < today:
        candidate = dt.date(today.year + 1, month, clamped_day)
    return candidate.strftime("%Y-%m-%d")


def _agent() -> AgentAdapter:
    global adapter
    adapter = get_agent_adapter()
    return adapter


def _prepare_payload(message: Dict[str, Optional[str]]) -> Dict[str, str]:
    """[LLM] Ensure the adapter payload always provides subject/body strings."""

    payload = dict(message)
    payload["subject"] = payload.get("subject") or ""
    payload["body"] = payload.get("body") or ""
    return payload


def classify_intent(message: Dict[str, Optional[str]]) -> Tuple[IntentLabel, float]:
    """[LLM] Delegate intent classification to the agent adapter and normalize output."""

    payload = _prepare_payload(message)
    if os.getenv("INTENT_FORCE_EVENT_REQUEST") == "1":
        print("[DEV] intent override -> event_request")
        return IntentLabel.EVENT_REQUEST, 0.99
    intent, confidence = _agent().route_intent(payload)
    normalized = IntentLabel.normalize(intent)
    override = _heuristic_intent_override(payload, normalized)
    if override is not None:
        normalized = override
        confidence = max(confidence, 0.93)
    return normalized, float(confidence)


def extract_user_information(message: Dict[str, Optional[str]]) -> Dict[str, Optional[Any]]:
    """[LLM] Extract structured event details from free-form text."""

    payload = _prepare_payload(message)
    agent = _agent()
    if hasattr(agent, "extract_user_information"):
        raw = agent.extract_user_information(payload) or {}
    else:
        raw = agent.extract_entities(payload) or {}
    sanitized = sanitize_user_info(raw)
    if not sanitized.get("date") and (
        os.getenv("AGENT_MODE", "").lower() == "stub" or os.getenv("INTENT_FORCE_EVENT_REQUEST") == "1"
    ):
        inferred = _infer_date_from_body(payload.get("body") or "")
        if inferred:
            sanitized["date"] = inferred
            if not sanitized.get("event_date"):
                sanitized["event_date"] = dt.datetime.strptime(inferred, "%Y-%m-%d").strftime("%d.%m.%Y")
    return sanitized


def sanitize_user_info(raw: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """[LLM] Coerce adapter outputs into the workflow schema."""

    sanitized: Dict[str, Optional[Any]] = {}
    for key in USER_INFO_KEYS:
        value = raw.get(key) if raw else None
        if key == "participants":
            sanitized[key] = sanitize_participants(value)
        elif key == "language":
            sanitized[key] = normalize_language(value)
        elif key == "room":
            sanitized[key] = normalize_room(value)
        elif key == "phone":
            sanitized[key] = normalize_phone(value)
        elif key in {"catering", "company", "notes", "billing_address"}:
            sanitized[key] = clean_text(value, trailing=" .;")
        elif key == "type":
            sanitized[key] = clean_text(value)
        elif key in {"name", "email"}:
            sanitized[key] = clean_text(value)
        elif key == "city":
            city_text = clean_text(value)
            if city_text and city_text.lower() not in {"english", "german", "french", "italian", "spanish"} and "room" not in city_text.lower():
                sanitized[key] = city_text
            else:
                sanitized[key] = None
        elif key in {"date", "start_time", "end_time"}:
            sanitized[key] = clean_text(value)
        else:
            sanitized[key] = value
    sanitized["event_date"] = format_iso_date_to_ddmmyyyy(sanitized.get("date"))
    return sanitized


def reset_llm_adapter() -> None:
    """Reset the cached agent adapter (intended for tests)."""

    global adapter
    reset_agent_adapter()
    adapter = get_agent_adapter()


_CONFIRM_TOKENS = (
    "confirm",
    "confirmed",
    "please confirm",
    "we'll take",
    "we will take",
    "take that date",
    "lock it in",
    "proceed",
    "go ahead",
    "works for us",
    "that date works",
    "book it",
)
_AFFIRMATIVE_PREFIXES = ("yes", "yep", "ja", "oui", "si", "sounds good", "let's do")
_EDIT_TOKENS = ("change", "update", "adjust", "move", "shift", "switch", "different", "another", "reschedule")
_ROOM_TOKENS = ("room", "space", "hall")
_REQUIREMENT_TOKENS = (
    "people",
    "guests",
    "attendees",
    "participants",
    "headcount",
    "projector",
    "screen",
    "catering",
    "requirements",
    "layout",
    "package",
    "menu",
    "equipment",
)


def _heuristic_intent_override(
    payload: Dict[str, str],
    base_intent: IntentLabel,
) -> Optional[IntentLabel]:
    raw_subject = (payload.get("subject") or "")
    raw_body = (payload.get("body") or "")
    subject = raw_subject.strip()
    body = raw_body.strip()
    body_lower = body.lower()
    subject_lower = subject.lower()
    text = f"{subject_lower}\n{body_lower}"

    detected_date = parse_first_date(body) or parse_first_date(subject)
    start_time, end_time, _ = parse_time_range(body)
    has_time_range = bool(start_time and end_time)

    if detected_date:
        if any(token in text for token in _CONFIRM_TOKENS) or body_lower.startswith(_AFFIRMATIVE_PREFIXES):
            return IntentLabel.CONFIRM_DATE if has_time_range else IntentLabel.CONFIRM_DATE_PARTIAL

        if any(token in text for token in _EDIT_TOKENS):
            # "move to 17.04" → edit date
            if any(keyword in text for keyword in ("date", "day", "daytime", "calendar")) or not any(
                room_token in text for room_token in _ROOM_TOKENS
            ):
                return IntentLabel.EDIT_DATE

    if any(room_token in text for room_token in _ROOM_TOKENS) and any(token in text for token in _EDIT_TOKENS):
        return IntentLabel.EDIT_ROOM

    if any(req_token in text for req_token in _REQUIREMENT_TOKENS) and any(token in text for token in _EDIT_TOKENS):
        return IntentLabel.EDIT_REQUIREMENTS

    # Escalate direct affirmative + date replies even without keywords.
    if detected_date and body_lower.startswith(_AFFIRMATIVE_PREFIXES):
        return IntentLabel.CONFIRM_DATE if has_time_range else IntentLabel.CONFIRM_DATE_PARTIAL

    return None
