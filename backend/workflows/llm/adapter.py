from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.adapters.agent_adapter import AgentAdapter, get_agent_adapter, reset_agent_adapter
from backend.domain import IntentLabel

from backend.services.products import list_product_records, normalise_product_payload
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
_LAST_CALL_METADATA: Dict[str, Any] = {}

_MONTHS = {name.lower(): idx for idx, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    start=1,
)}
_DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+of\s+([A-Za-z]+)\b", re.IGNORECASE)

_LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "u shape": "U-shape",
    "u-shaped": "U-shape",
    "boardroom": "Boardroom",
    "standing": "Standing reception",
    "cocktail": "Standing reception",
}

_FEATURE_KEYWORDS = {
    "projector": ["projector", "screen", "beamer"],
    "sound system": ["sound system", "speakers", "audio", "music"],
    "coffee service": ["coffee service", "coffee bar", "coffee", "barista", "espresso", "tea service"],
}


def _extract_requirement_hints(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    layout = None
    for token, label in _LAYOUT_KEYWORDS.items():
        if token in lowered:
            layout = label
            break

    features: List[str] = []
    for label, keywords in _FEATURE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            features.append(label)

    catering = None
    if "coffee" in lowered or "barista" in lowered or "espresso" in lowered:
        catering = "Coffee service"

    return {"layout": layout, "features": features, "catering": catering}


def _match_catalog_products(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    catalog_names = [record.name for record in list_product_records()]
    raw_matches = _agent().match_catalog_items(text, catalog_names)
    matches: List[Dict[str, Any]] = []
    if not raw_matches:
        return matches

    for entry in raw_matches:
        name: Optional[str]
        score: float
        if isinstance(entry, tuple) and entry:
            name = str(entry[0]) if entry[0] is not None else None
            try:
                score = float(entry[1]) if len(entry) > 1 else 0.0
            except (TypeError, ValueError):
                score = 0.0
        elif isinstance(entry, dict):
            name = entry.get("name")
            raw_score = entry.get("confidence")
            try:
                score = float(raw_score) if raw_score is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
        else:
            name = str(entry) if entry else None
            score = 0.65
        if not name:
            continue
        matches.append({"name": name, "confidence": max(0.0, min(1.0, score))})
    return matches


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

def _record_last_call(agent: AgentAdapter, phase: str) -> None:
    """Store metadata about the most recent adapter invocation for telemetry."""

    global _LAST_CALL_METADATA
    info: Dict[str, Any] = {}
    if hasattr(agent, "last_call_info"):
        try:
            raw = agent.last_call_info()  # type: ignore[attr-defined]
            if isinstance(raw, dict):
                info = dict(raw)
        except Exception:
            info = {}
    if not info and hasattr(agent, "describe"):
        try:
            raw_desc = agent.describe()
            if isinstance(raw_desc, dict):
                info = dict(raw_desc)
        except Exception:
            info = {}
    info.setdefault("phase", phase)
    if "model" not in info:
        phase_key = "intent_model" if phase == "intent" else "entity_model"
        if phase_key in info and info[phase_key]:
            info["model"] = info[phase_key]
    _LAST_CALL_METADATA = info

def last_call_metadata() -> Dict[str, Any]:
    """Expose metadata for the most recent adapter call."""

    return dict(_LAST_CALL_METADATA)


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
    agent = _agent()
    intent, confidence = agent.route_intent(payload)
    _record_last_call(agent, phase="intent")
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
    _record_last_call(agent, phase="entities")
    sanitized = sanitize_user_info(raw)
    if not sanitized.get("date") and (
        os.getenv("AGENT_MODE", "").lower() == "stub" or os.getenv("INTENT_FORCE_EVENT_REQUEST") == "1"
    ):
        inferred = _infer_date_from_body(payload.get("body") or "")
        if inferred:
            sanitized["date"] = inferred
            if not sanitized.get("event_date"):
                sanitized["event_date"] = dt.datetime.strptime(inferred, "%Y-%m-%d").strftime("%d.%m.%Y")

    body_text = payload.get("body") or ""
    hints = _extract_requirement_hints(body_text)
    if hints.get("layout") and not sanitized.get("layout"):
        sanitized["layout"] = hints["layout"]
    if hints.get("catering") and not sanitized.get("catering"):
        sanitized["catering"] = hints["catering"]

    note_tokens: List[str] = []
    if sanitized.get("notes"):
        note_tokens.extend([token.strip() for token in str(sanitized["notes"]).split(",") if token.strip()])
    for token in hints.get("features", []):
        if token not in note_tokens:
            note_tokens.append(token)
    if note_tokens:
        sanitized["notes"] = ", ".join(note_tokens)

    matched_products = _match_catalog_products(body_text)
    if matched_products:
        high_confidence: List[str] = []
        for item in matched_products:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            try:
                score = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if score >= 0.6:
                high_confidence.append(str(name))
        if high_confidence:
            participant_count = sanitized.get("participants")
            participant_value = participant_count if isinstance(participant_count, int) else None
            normalised = normalise_product_payload(
                high_confidence,
                participant_count=participant_value,
            )
            if normalised:
                existing = normalise_product_payload(
                    sanitized.get("products_add"),
                    participant_count=participant_value,
                )
                combined_names = {item["name"] for item in existing}
                for item in normalised:
                    if item["name"] not in combined_names:
                        existing.append(item)
                sanitized["products_add"] = existing

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
        elif key == "layout":
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
    global _LAST_CALL_METADATA
    reset_agent_adapter()
    adapter = get_agent_adapter()
    _LAST_CALL_METADATA = {}


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
