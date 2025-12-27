"""Utility helpers for Step 7 confirmation.

Extracted from step7_handler.py as part of F1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from backend.workflows.common.types import WorkflowState


def iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    """Convert ISO date string to DD.MM.YYYY format."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%d.%m.%Y")


def base_payload(state: WorkflowState, event_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Build standard response payload for Step 7."""
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return payload


def thread_id(state: WorkflowState) -> str:
    """Extract thread ID from state for tracing."""
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def any_keyword_match(lowered: str, keywords: Tuple[str, ...]) -> bool:
    """Check if any keyword matches as whole word in lowered text."""
    return any(contains_word(lowered, keyword) for keyword in keywords)


def contains_word(text: str, keyword: str) -> bool:
    """Check if keyword appears as whole word in text."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text) is not None
