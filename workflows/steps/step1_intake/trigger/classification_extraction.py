"""LLM Classification and Entity Extraction.

Handles intent classification and user information extraction
with tracing and fallback mechanisms.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from domain import IntentLabel
from debug.hooks import trace_marker, trace_prompt_in, trace_prompt_out
from workflows.common.datetime_parse import parse_first_date
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.nlu.preferences import extract_preferences

from ..llm.analysis import classify_intent, extract_user_information
from .llm_classification import validate_extracted_room as _validate_extracted_room
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from .intent_helpers import (
    needs_vague_date_confirmation as _needs_vague_date_confirmation,
    initial_intent_detail as _initial_intent_detail,
    has_same_turn_shortcut as _has_same_turn_shortcut,
)

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of intent classification and entity extraction."""
    intent: IntentLabel
    confidence: float
    user_info: Dict[str, Any]
    intent_detail: Optional[str] = None
    needs_vague_date_confirmation: bool = False
    shortcut_detected: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)


def classify_and_extract(
    message_payload: Dict[str, Any],
    thread_id: str,
    owner_step: str,
) -> ClassificationResult:
    """Perform LLM classification and entity extraction with tracing.

    Args:
        message_payload: Raw message data
        thread_id: For tracing
        owner_step: Step for tracing

    Returns:
        ClassificationResult with intent, confidence, and extracted user_info
    """
    # Build prompt payload for tracing
    prompt_payload = (
        f"Subject: {message_payload.get('subject') or ''}\n"
        f"Body:\n{message_payload.get('body') or ''}"
    )

    # Trace and classify intent
    trace_prompt_in(thread_id, owner_step, "classify_intent", prompt_payload)
    intent, confidence = classify_intent(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "classify_intent",
        json.dumps({"intent": intent.value, "confidence": round(confidence, 3)}, ensure_ascii=False),
        outputs={"intent": intent.value, "confidence": round(confidence, 3)},
    )
    trace_marker(
        thread_id,
        "AGENT_CLASSIFY",
        detail=intent.value,
        data={"confidence": round(confidence, 3)},
        owner_step=owner_step,
    )

    intent_detail = _initial_intent_detail(intent)

    # Trace and extract user information
    trace_prompt_in(thread_id, owner_step, "extract_user_information", prompt_payload)
    user_info = extract_user_information(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "extract_user_information",
        json.dumps(user_info, ensure_ascii=False),
        outputs=user_info,
    )

    # Room validation - reject false positive extractions
    if user_info.get("room"):
        original_text = f"{message_payload.get('subject', '')} {message_payload.get('body', '')}".strip()
        validated_room = _validate_extracted_room(user_info["room"], message_text=original_text)
        if validated_room != user_info["room"]:
            logger.debug(
                "[Step1][ROOM_VALIDATION] Rejected room extraction: %r -> %r",
                user_info["room"],
                validated_room,
            )
        user_info["room"] = validated_room

    # Date regex fallback if LLM missed it
    if not user_info.get("date") and not user_info.get("event_date"):
        body_text = message_payload.get("body") or ""
        fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
        parsed_date = parse_first_date(body_text, fallback_year=fallback_year)
        if parsed_date:
            user_info["date"] = parsed_date.isoformat()
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(parsed_date.isoformat())
            logger.debug("[Step1] Regex fallback extracted date: %s", parsed_date.isoformat())
            # Boost confidence if we found date via regex
            if intent == IntentLabel.EVENT_REQUEST and confidence < 0.90:
                confidence = 0.90
                logger.debug("[Step1] Boosted confidence to %s due to regex date extraction", confidence)

    # Check for vague date confirmation needs
    needs_vague = _needs_vague_date_confirmation(user_info)
    if needs_vague:
        user_info.pop("event_date", None)
        user_info.pop("date", None)

    # Extract preferences
    raw_pref_text = "\n".join([
        message_payload.get("subject") or "",
        message_payload.get("body") or "",
    ]).strip()
    preferences = extract_preferences(user_info, raw_text=raw_pref_text or None)
    if preferences:
        user_info["preferences"] = preferences

    # Check for same-turn shortcut eligibility
    shortcut_detected = False
    extras: Dict[str, Any] = {}
    if intent == IntentLabel.EVENT_REQUEST and _has_same_turn_shortcut(user_info):
        intent_detail = "event_intake_shortcut"
        shortcut_detected = True
        extras["shortcut_detected"] = True

    return ClassificationResult(
        intent=intent,
        confidence=confidence,
        user_info=user_info,
        intent_detail=intent_detail,
        needs_vague_date_confirmation=needs_vague,
        shortcut_detected=shortcut_detected,
        extras=extras,
    )


__all__ = [
    "ClassificationResult",
    "classify_and_extract",
]
