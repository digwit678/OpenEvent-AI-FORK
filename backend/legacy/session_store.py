"""
Session store and Step 3 caching utilities.

Extracted from conversation_manager.py as part of C1 refactoring (Dec 2025).

This module contains session/cache management that does NOT require OpenAI:
- active_conversations: In-memory conversation state storage
- Step 3 draft/payload caching for de-duplication
- render_step3_reply: Workflow-driven Step 3 reply rendering
- pop_step3_payload: Retrieve and remove cached Step 3 payload

Usage:
    from backend.legacy.session_store import (
        active_conversations,
        render_step3_reply,
        pop_step3_payload,
    )
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain import ConversationState, IntentLabel
from backend.workflow_email import DB_PATH as WF_DB_PATH, load_db as wf_load_db, save_db as wf_save_db
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step3_room_availability.trigger import process as step3_process


# In-memory storage for demo
active_conversations: dict[str, ConversationState] = {}

# Step 3 caches for de-duplication
STEP3_DRAFT_CACHE: Dict[str, str] = {}
STEP3_PAYLOAD_CACHE: Dict[str, Dict[str, Any]] = {}


def _step3_cache_key(session_id: Optional[str]) -> str:
    """Generate cache key for Step 3 draft/payload storage."""
    return session_id or "__default__"


def _normalise_step3_draft(
    session_id: Optional[str],
    drafts: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Normalize and cache Step 3 drafts to prevent duplicate delivery."""
    if not drafts:
        return None

    cache_key = _step3_cache_key(session_id)

    for draft in drafts:
        step_raw = draft.get("step")
        is_step_three = False

        if isinstance(step_raw, int):
            is_step_three = step_raw == 3
        else:
            step_str = str(step_raw or "").strip()
            if step_str.lower().startswith("step3"):
                is_step_three = True
            else:
                match = re.match(r"^(\d+)", step_str)
                if match:
                    is_step_three = int(match.group(1)) == 3

        if not is_step_three:
            continue

        body_md = draft.get("body_markdown") or draft.get("body_md") or draft.get("body")
        if not isinstance(body_md, str) or not body_md.strip():
            continue

        signature = body_md.strip()
        cached = STEP3_DRAFT_CACHE.get(cache_key)
        if cached and cached == signature:
            return None  # Already delivered

        STEP3_DRAFT_CACHE[cache_key] = signature
        payload = {
            "subject": draft.get("subject") or "Room options and available dates",
            "body_markdown": body_md,
            "body": draft.get("body") or body_md,
            "actions": draft.get("actions") or [],
            "footer": draft.get("footer"),
        }
        STEP3_PAYLOAD_CACHE[cache_key] = payload
        return payload

    return None


def _render_step3_from_workflow(state: ConversationState) -> Optional[Dict[str, Any]]:
    """Render Step 3 reply by invoking the workflow engine."""
    event_id = state.event_id
    if not event_id:
        return None

    try:
        db = wf_load_db()
    except Exception as exc:
        print(f"[WF][WARN] Step-3 render skipped (load failed): {exc}")
        return None

    events = db.get("events") or []
    event_entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not event_entry:
        return None

    current = event_entry.get("current_step")
    try:
        current_step = int(current)
    except (TypeError, ValueError):
        current_step = None

    if current_step != 3:
        return None

    message = IncomingMessage(
        msg_id=f"step3-refresh::{event_id}",
        from_name=state.event_info.name or event_entry.get("contact_name") or "Client",
        from_email=state.event_info.email or event_entry.get("contact_email"),
        subject=event_entry.get("subject") or "Room availability update",
        body="",
        ts=datetime.utcnow().isoformat() + "Z",
    )
    wf_state = WorkflowState(message=message, db_path=Path(WF_DB_PATH), db=db)
    wf_state.event_entry = event_entry
    wf_state.event_id = event_id
    wf_state.client_id = event_entry.get("client_id") or (state.event_info.email or "").lower()
    wf_state.thread_id = event_entry.get("thread_id") or state.session_id
    wf_state.intent = IntentLabel.EVENT_REQUEST
    wf_state.confidence = 1.0
    wf_state.user_info = dict(event_entry.get("user_info") or {})
    wf_state.context_snapshot = event_entry.get("context_snapshot") or {}
    wf_state.thread_state = event_entry.get("thread_state") or "Awaiting Client"
    wf_state.current_step = 3
    wf_state.caller_step = event_entry.get("caller_step")

    try:
        step3_process(wf_state)
    except Exception as exc:
        print(f"[WF][ERROR] Step-3 workflow failed: {exc}")
        return None

    if wf_state.extras.get("persist"):
        try:
            wf_save_db(db)
        except Exception as exc:
            print(f"[WF][WARN] Step-3 persist failed: {exc}")

    return _normalise_step3_draft(state.session_id, wf_state.draft_messages)


def render_step3_reply(
    conversation_state: ConversationState,
    drafts: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the workflow-authored Step-3 reply if available and not yet delivered."""
    cached = _normalise_step3_draft(conversation_state.session_id, drafts)
    if cached:
        return cached
    return _render_step3_from_workflow(conversation_state)


def pop_step3_payload(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieve and remove the cached Step 3 payload for a session."""
    cache_key = _step3_cache_key(session_id)
    return STEP3_PAYLOAD_CACHE.pop(cache_key, None)


__all__ = [
    "active_conversations",
    "STEP3_DRAFT_CACHE",
    "STEP3_PAYLOAD_CACHE",
    "render_step3_reply",
    "pop_step3_payload",
]
