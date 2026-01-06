"""
D15 Refactoring: State-dependent helper functions for Step 2.

Extracted from step2_handler.py to reduce file size.
Unlike step2_utils.py (pure functions), this module contains
helpers that read from WorkflowState.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from debug.hooks import trace_state
from workflows.common.datetime_parse import parse_all_dates
from workflows.common.menu_options import build_menu_payload
from workflows.common.types import WorkflowState

from .step2_utils import get_message_text
from .window_helpers import _reference_date_from_state


def thread_id(state: WorkflowState) -> str:
    """Extract thread ID from workflow state.

    Falls back through: thread_id -> client_id -> msg_id -> 'unknown-thread'

    Args:
        state: Current workflow state

    Returns:
        Thread identifier string
    """
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def emit_step2_snapshot(
    state: WorkflowState,
    event_entry: dict,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a state snapshot for Step 2 debugging.

    Args:
        state: Current workflow state
        event_entry: Event data dict
        extra: Additional fields to include in snapshot
    """
    tid = thread_id(state)
    snapshot: Dict[str, Any] = {
        "step": 2,
        "current_step": 2,
        "thread_state": event_entry.get("thread_state") or state.thread_state,
        "chosen_date": event_entry.get("chosen_date"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "range_query_detected": event_entry.get("range_query_detected"),
        "vague_month": event_entry.get("vague_month") or (state.user_info or {}).get("vague_month"),
        "vague_weekday": event_entry.get("vague_weekday") or (state.user_info or {}).get("vague_weekday"),
    }
    if extra:
        snapshot.update(extra)
    trace_state(tid, "Step2_Date", snapshot)


def client_requested_dates(state: WorkflowState) -> List[str]:
    """Extract explicit dates mentioned by the client in the current message.

    Results are cached in state.extras to avoid re-parsing.

    Args:
        state: Current workflow state

    Returns:
        List of ISO date strings mentioned in the message
    """
    cache_key = "_client_requested_dates"
    cached = state.extras.get(cache_key)
    if isinstance(cached, list):
        return list(cached)

    msg = state.message
    text = get_message_text(msg.subject if msg else None, msg.body if msg else None)
    reference_day = _reference_date_from_state(state)
    explicit_pattern = re.compile(
        r"(\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\b)",
        re.IGNORECASE,
    )
    iso_values: List[str] = []
    if text and explicit_pattern.search(text):
        seen: set[str] = set()
        for value in parse_all_dates(text, fallback_year=reference_day.year):
            iso = value.isoformat()
            if iso in seen:
                continue
            seen.add(iso)
            iso_values.append(iso)
    state.extras[cache_key] = list(iso_values)
    return iso_values


def maybe_general_qa_payload(state: WorkflowState) -> Optional[Dict[str, Any]]:
    """Build Q&A payload for menu/catering requests if detected.

    Args:
        state: Current workflow state

    Returns:
        Menu payload dict if catering/menu request detected, None otherwise
    """
    event_entry = state.event_entry or {}
    user_info = state.user_info or {}
    month_hint = user_info.get("vague_month") or event_entry.get("vague_month")
    msg = state.message
    message_text = get_message_text(msg.subject if msg else None, msg.body if msg else None)
    return build_menu_payload(message_text, context_month=month_hint)


__all__ = [
    "thread_id",
    "emit_step2_snapshot",
    "client_requested_dates",
    "maybe_general_qa_payload",
]
