from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent_adapter import get_agent_adapter
from vocabulary import IntentLabel

from workflows.common.room_rules import (
    USER_INFO_KEYS,
    clean_text,
    normalize_language,
    normalize_phone,
    normalize_room,
    sanitize_participants,
)
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

adapter = get_agent_adapter()


def _prepare_payload(message: Dict[str, Optional[str]]) -> Dict[str, str]:
    """[LLM] Ensure the adapter payload always provides subject/body strings."""

    payload = dict(message)
    payload["subject"] = payload.get("subject") or ""
    payload["body"] = payload.get("body") or ""
    return payload


def classify_intent(message: Dict[str, Optional[str]]) -> Tuple[IntentLabel, float]:
    """[LLM] Delegate intent classification to the agent adapter and normalize output."""

    payload = _prepare_payload(message)
    intent, confidence = adapter.route_intent(payload)
    return IntentLabel.normalize(intent), float(confidence)


def extract_user_information(message: Dict[str, Optional[str]]) -> Dict[str, Optional[Any]]:
    """[LLM] Extract structured event details from free-form text."""

    payload = _prepare_payload(message)
    if hasattr(adapter, "extract_user_information"):
        raw = adapter.extract_user_information(payload) or {}
    else:
        raw = adapter.extract_entities(payload) or {}
    return sanitize_user_info(raw)


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
        elif key in {"catering", "company", "notes"}:
            sanitized[key] = clean_text(value, trailing=" .;")
        elif key == "type":
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
