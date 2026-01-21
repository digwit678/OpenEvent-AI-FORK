"""
Step 2 General Q&A Bridge - handles room/date availability queries.

Extracted from step2_handler.py as part of D5 refactoring (Dec 2025).

This module contains the Step 2-specific Q&A handling which differs from
the unified present_general_room_qna in common/general_qna.py due to:
- Range availability checking
- Router Q&A integration
- Complex state handling with window constraints
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from debug.hooks import set_subloop, trace_db_read, trace_general_qa_status
from utils.page_snapshots import create_snapshot
from utils.pseudolinks import generate_qna_link
from workflows.common.general_qna import _fallback_structured_body
from workflows.common.prompts import append_footer
from workflows.common.sorting import rank_rooms
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import load_rooms, update_event_metadata
from workflows.qna.engine import build_structured_qna_result
from workflows.qna.extraction import ensure_qna_extraction
from workflows.qna.router import route_general_qna
from workflows.steps.step3_room_availability.condition.decide import room_status_on_date

# D5: Import shared helpers from window_helpers (no circular deps)
from .window_helpers import (
    _resolve_window_hints,
    _has_window_constraints,
    _candidate_dates_for_constraints,
    _extract_participants_from_state,
)


def _search_range_availability(
    state: WorkflowState,
    thread_id: Optional[str],
    constraints: Dict[str, Any],
    participants: Optional[int],
    preferences: Dict[str, Any],
    preferred_room: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Search for room availability across a range of dates based on constraints.

    Returns list of {iso_date, date_label, room, status, hint} entries.
    """
    window_hints = _resolve_window_hints(constraints, state)
    strict_window = _has_window_constraints(window_hints)
    iso_dates = _candidate_dates_for_constraints(
        state,
        constraints,
        window_hints=window_hints,
        strict=strict_window,
    )
    if not iso_dates:
        return []

    rooms = load_rooms()
    results: List[Dict[str, Any]] = []
    iso_seen: set[str] = set()
    limit = 5

    for iso_date in iso_dates:
        status_map = {room: room_status_on_date(state.db, iso_date, room) for room in rooms}
        ranked = rank_rooms(
            status_map,
            preferred_room=preferred_room,
            pax=participants,
            preferences=preferences,
        )
        for entry in ranked[:3]:
            results.append(
                {
                    "iso_date": iso_date,
                    "date_label": datetime.strptime(iso_date, "%Y-%m-%d").strftime("%a %d %b %Y"),
                    "room": entry.room,
                    "status": entry.status,
                    "hint": entry.hint,
                }
            )
        iso_seen.add(iso_date)
        if len(iso_seen) >= limit:
            break

    if thread_id:
        trace_db_read(
            thread_id,
            "Step2_Date",
            "db.rooms.search_range",
            {
                "constraints": {
                    "month": constraints.get("vague_month"),
                    "weekday": constraints.get("weekday"),
                    "time_of_day": constraints.get("time_of_day"),
                    "pax": participants,
                },
                "result_count": len(results),
                "sample": results[:3],
            },
        )

    return results[: limit * 3]


def present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
    qa_payload: Optional[Dict[str, Any]] = None,
) -> GroupResult:
    """
    Handle general room/date Q&A queries in Step 2.

    This is the Step 2-specific Q&A handler with:
    - Range availability checking
    - Router Q&A integration for catering/products
    - Multi-turn Q&A context preservation

    Returns GroupResult with action 'general_rooms_qna' or 'general_rooms_qna_fallback'.
    """
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    resolved_thread_id = thread_id or state.thread_id
    constraints = classification.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}
    participants = _extract_participants_from_state(state)
    user_preferences = {}
    if isinstance(state.user_info, dict):
        user_preferences = state.user_info.get("preferences") or {}
    if not user_preferences and isinstance(event_entry, dict):
        user_preferences = event_entry.get("preferences") or {}
    if not isinstance(user_preferences, dict):
        user_preferences = {}
    requirements = event_entry.get("requirements") if isinstance(event_entry, dict) else None
    preferred_room = None
    if isinstance(state.user_info, dict):
        preferred_room = state.user_info.get("preferred_room")
    if not preferred_room and isinstance(requirements, dict):
        preferred_room = requirements.get("preferred_room")
    range_results = _search_range_availability(
        state,
        resolved_thread_id,
        constraints,
        participants,
        user_preferences,
        preferred_room,
    )
    range_lookup: Dict[str, str] = {}
    for entry in range_results:
        iso_value = entry.get("iso_date")
        if not iso_value:
            continue
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        label = parsed.strftime("%d.%m.%Y")
        range_lookup.setdefault(label, parsed.date().isoformat())
    range_candidate_dates = sorted(range_lookup.keys(), key=lambda lbl: range_lookup[lbl])[:5]
    range_actions = [
        {
            "type": "select_date",
            "label": f"Confirm {label}",
            "date": label,
            "iso_date": range_lookup[label],
        }
        for label in range_candidate_dates
    ]
    if qa_payload:
        state.turn_notes["general_qa"] = qa_payload
        event_entry.setdefault("general_qa_payload", qa_payload)
        state.extras["persist"] = True
        trace_general_qa_status(
            resolved_thread_id,
            "payload_attached",
            {"has_payload": True, "range_results": len(range_results)},
        )
    else:
        trace_general_qa_status(
            resolved_thread_id,
            "payload_missing",
            {"has_payload": False, "range_results": len(range_results)},
        )
    if thread_id:
        set_subloop(thread_id, subloop_label)

    # MULTI-TURN FIX: Always run fresh extraction for each general_room_qna message
    # Store minimal "last_general_qna" context only for follow-up detection
    last_qna_context = event_entry.get("last_general_qna") if isinstance(event_entry, dict) else {}

    # Always extract fresh from current message
    message = state.message
    subject = (message.subject if message else "") or ""
    body = (message.body if message else "") or ""
    message_text = f"{subject}\n{body}".strip() or body or subject

    scan = state.extras.get("general_qna_scan")
    # Force fresh extraction (force_refresh=True) for multi-turn Q&A
    ensure_qna_extraction(state, message_text, scan, force_refresh=True)
    extraction = state.extras.get("qna_extraction")

    # Clear stale qna_cache AFTER extraction to prevent reuse of old extraction
    # (force_refresh=True prevents new cache from being saved)
    if isinstance(event_entry, dict):
        event_entry.pop("qna_cache", None)

    structured = build_structured_qna_result(state, extraction) if extraction else None

    if structured and structured.handled:
        rooms = structured.action_payload.get("db_summary", {}).get("rooms", [])
        date_lookup: Dict[str, str] = {}
        for entry in rooms:
            iso_date = entry.get("date") or entry.get("iso_date")
            if not iso_date:
                continue
            try:
                parsed = datetime.fromisoformat(iso_date)
            except ValueError:
                try:
                    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
                except ValueError:
                    continue
            label = parsed.strftime("%d.%m.%Y")
            date_lookup.setdefault(label, parsed.date().isoformat())

        candidate_dates = sorted(date_lookup.keys(), key=lambda label: date_lookup[label])[:5]
        actions = [
            {
                "type": "select_date",
                "label": f"Confirm {label}",
                "date": label,
                "iso_date": date_lookup[label],
            }
            for label in candidate_dates
        ]

        body_markdown = (structured.body_markdown or _fallback_structured_body(structured.action_payload)).strip()

        footer_body = append_footer(
            body_markdown,
            step=2,
            next_step=3,
            thread_state="Awaiting Client",
        )

        # Check for secondary Q&A types (catering_for, products_for, etc.)
        secondary_types = list(classification.get("secondary") or [])
        # Pure informational Q&A types that don't need "Availability overview" header
        pure_info_qna_types = {
            "room_features", "parking_policy", "accessibility_inquiry",
            "catering_for", "products_for", "pricing_inquiry", "site_visit_overview"
        }
        is_pure_info_qna = bool(set(secondary_types) & pure_info_qna_types)

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 2,
            "next_step": 3,
            "thread_state": "Awaiting Client",
            "topic": "general_room_qna",
            "candidate_dates": candidate_dates,
            "actions": actions,
            "subloop": subloop_label,
        }
        # Only add "Availability overview" header when response contains availability data
        if not is_pure_info_qna:
            draft_message["headers"] = ["Availability overview"]
        if not candidate_dates and range_candidate_dates:
            candidate_dates = range_candidate_dates
            actions = range_actions
            draft_message["candidate_dates"] = candidate_dates
            draft_message["actions"] = actions
        if range_results:
            draft_message["range_results"] = range_results

        # Check for router-handled Q&A types
        secondary_types = list(classification.get("secondary") or [])
        router_types = {"catering_for", "products_for", "rooms_by_feature", "room_features", "free_dates", "parking_policy", "site_visit_overview"}
        router_applicable = bool(set(secondary_types) & router_types)

        if router_applicable:
            message = state.message
            msg_payload = {
                "subject": (message.subject if message else "") or "",
                "body": (message.body if message else "") or "",
                "thread_id": state.thread_id,
            }
            router_result = route_general_qna(
                msg_payload,
                event_entry,
                event_entry,
                None,  # db not needed for catering/products router responses
                classification,
            )
            router_blocks = router_result.get("post_step") or router_result.get("pre_step") or []
            if router_blocks:
                router_body = router_blocks[0].get("body", "")
                if router_body:
                    # Add info link for catering Q&A
                    qna_link_suffix = ""
                    if "catering_for" in secondary_types:
                        query_params = {"room": event_entry.get("preferred_room") or "general"}
                        snapshot_data = {"catering_options": router_body, "event_id": event_entry.get("event_id")}
                        snapshot_id = create_snapshot(
                            snapshot_type="catering",
                            data=snapshot_data,
                            event_id=event_entry.get("event_id"),
                            params=query_params,
                        )
                        qna_link = generate_qna_link("Catering", query_params=query_params, snapshot_id=snapshot_id)
                        qna_link_suffix = f"\n\nFull menu details: {qna_link}"
                    # Append router Q&A content to the draft message body
                    original_body = draft_message.get("body", "")
                    draft_message["body"] = f"{original_body}\n\n---\n\n{router_body}{qna_link_suffix}"
                    draft_message["body_markdown"] = f"{draft_message.get('body_markdown', '')}\n\n---\n\n{router_body}{qna_link_suffix}"
                    draft_message["router_qna_appended"] = True

        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            thread_state="Awaiting Client",
            current_step=2,
            candidate_dates=candidate_dates,
        )
        state.set_thread_state("Awaiting Client")
        state.record_subloop(subloop_label)
        state.intent_detail = "event_intake_with_question"
        state.extras["persist"] = True

        # Store minimal last_general_qna context for follow-up detection only
        if extraction and isinstance(event_entry, dict):
            q_values = extraction.get("q_values") or {}
            event_entry["last_general_qna"] = {
                "topic": structured.action_payload.get("qna_subtype"),
                "date_pattern": q_values.get("date_pattern"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "candidate_dates": candidate_dates,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "general_qna": True,
            "structured_qna": structured.handled,
            "qna_select_result": structured.action_payload,
            "structured_qna_debug": structured.debug,
            "actions": actions,
        }
        if extraction:
            payload["qna_extraction"] = extraction
        return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    state.extras["structured_qna_fallback"] = True
    structured_payload = structured.action_payload if structured else {}
    structured_debug = structured.debug if structured else {"reason": "missing_structured_context"}

    # Use router for Q&A types it handles (catering_for, products_for, etc.)
    # This ensures proper formatting through the existing verbalizer infrastructure
    secondary_types = list(classification.get("secondary") or [])
    router_types = {"catering_for", "products_for", "rooms_by_feature", "room_features", "free_dates", "parking_policy", "site_visit_overview"}
    router_applicable = bool(set(secondary_types) & router_types)

    if router_applicable:
        message = state.message
        msg_payload = {
            "subject": (message.subject if message else "") or "",
            "body": (message.body if message else "") or "",
            "thread_id": state.thread_id,
        }
        router_result = route_general_qna(
            msg_payload,
            event_entry,
            event_entry,
            None,  # db not needed for catering/products router responses
            classification,
        )
        router_blocks = router_result.get("post_step") or router_result.get("pre_step") or []
        if router_blocks:
            router_body = router_blocks[0].get("body", "")
            router_topic = router_blocks[0].get("topic", "general_qna")

            # Add info link for catering Q&A
            if "catering_for" in secondary_types:
                query_params = {"room": event_entry.get("preferred_room") or "general"}
                snapshot_data = {"catering_options": router_body, "event_id": event_entry.get("event_id")}
                snapshot_id = create_snapshot(
                    snapshot_type="catering",
                    data=snapshot_data,
                    event_id=event_entry.get("event_id"),
                    params=query_params,
                )
                qna_link = generate_qna_link("Catering", query_params=query_params, snapshot_id=snapshot_id)
                router_body = f"{router_body}\n\nFull menu details: {qna_link}"

            footer_body = append_footer(
                router_body,
                step=2,
                next_step=3,
                thread_state="Awaiting Client",
            )

            # Pure informational Q&A types that don't need "Availability overview" header
            pure_info_qna_types = {
                "room_features", "parking_policy", "accessibility_inquiry",
                "catering_for", "products_for", "pricing_inquiry", "site_visit_overview"
            }
            is_pure_info_qna = bool(set(secondary_types) & pure_info_qna_types)

            draft_message = {
                "body": footer_body,
                "body_markdown": router_body,
                "step": 2,
                "next_step": 3,
                "thread_state": "Awaiting Client",
                "topic": router_topic,
                "candidate_dates": range_candidate_dates,
                "actions": range_actions,
                "subloop": subloop_label,
            }
            # Only add "Availability overview" header when response contains availability data
            if not is_pure_info_qna:
                draft_message["headers"] = ["Availability overview"]
            if range_results:
                draft_message["range_results"] = range_results

            state.add_draft_message(draft_message)
            update_event_metadata(
                event_entry,
                thread_state="Awaiting Client",
                current_step=2,
                candidate_dates=range_candidate_dates,
            )
            state.set_thread_state("Awaiting Client")
            state.record_subloop(subloop_label)
            state.extras["persist"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "candidate_dates": range_candidate_dates,
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
                "general_qna": True,
                "structured_qna": True,  # Mark as handled via router
                "router_qna": True,
                "qna_select_result": structured_payload,
                "structured_qna_debug": structured_debug,
                "actions": range_actions,
                "range_results": range_results,
            }
            if extraction:
                payload["qna_extraction"] = extraction
            return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": range_candidate_dates,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "general_qna": True,
        "structured_qna": False,
        "structured_qna_fallback": True,
        "qna_select_result": structured_payload,
        "structured_qna_debug": structured_debug,
        "candidate_dates_range": range_candidate_dates,
        "actions": range_actions,
        "range_results": range_results,
    }
    if extraction:
        payload["qna_extraction"] = extraction
    return GroupResult(action="general_rooms_qna_fallback", payload=payload, halt=False)


# Backwards compatibility alias
_present_general_room_qna = present_general_room_qna

__all__ = [
    "present_general_room_qna",
    "_present_general_room_qna",  # Backwards compat
    "_search_range_availability",
]