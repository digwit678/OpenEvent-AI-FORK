"""Change detection and routing for Step 4.

Encompasses: catering→products_add conversion, nonsense gate, Q&A classification,
enhanced change detection, DAG routing, product extraction, and detour acknowledgment.
Returns a ``Step4ChangeResult`` that carries the ``classification`` dict downstream
for the Q&A guard.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult, WorkflowState
from workflows.common.detection_utils import get_unified_detection
from workflows.change_propagation import (
    ChangeType,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.detour_acknowledgment import (
    generate_detour_acknowledgment,
    add_detour_acknowledgment_draft,
)
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.nlu import detect_general_room_query
from services.products import find_product
from debug.hooks import trace_marker

logger = logging.getLogger(__name__)


@dataclass
class Step4ChangeResult:
    """Result of the change detection / routing pipeline at Step 4."""
    halt_result: Optional[GroupResult] = None
    classification: Dict[str, Any] = field(default_factory=dict)
    message_text: str = ""
    normalized_message_text: str = ""
    user_info: Dict[str, Any] = field(default_factory=dict)
    unified_detection: Any = None


def run_change_detection(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    thread_id: str,
) -> Step4ChangeResult:
    """Run change detection, nonsense gate, Q&A classification, and routing.

    Returns ``Step4ChangeResult``.  If ``halt_result`` is set, the caller
    should return it immediately.  Otherwise, ``classification`` carries
    forward for the Q&A guard.
    """
    from .helpers import _message_text, _normalize_quotes, handle_nonsense_gate
    from .product_ops import menu_name_set as _menu_name_set

    result = Step4ChangeResult()

    message_text = _message_text(state)
    normalized_message_text = _normalize_quotes(message_text)
    user_info = state.user_info or {}
    result.message_text = message_text
    result.normalized_message_text = normalized_message_text
    result.user_info = user_info

    # -------------------------------------------------------------------------
    # CATERING -> PRODUCTS_ADD CONVERSION
    # -------------------------------------------------------------------------
    catering_pref = user_info.get("catering")
    if catering_pref and isinstance(catering_pref, str) and not user_info.get("products_add"):
        catering_product = find_product(catering_pref)
        if catering_product:
            participant_count = (
                user_info.get("participants")
                or (event_entry.get("requirements") or {}).get("number_of_participants")
                or (event_entry.get("event_data") or {}).get("Number of Participants")
            )
            try:
                quantity = int(participant_count) if participant_count else 1
            except (TypeError, ValueError):
                quantity = 1
            user_info["products_add"] = [{"name": catering_product.name, "quantity": quantity}]
            state.user_info = user_info
            logger.info("[Step4] Converted catering field '%s' to products_add: %s (qty: %d)",
                       catering_pref, catering_product.name, quantity)

    # -------------------------------------------------------------------------
    # NONSENSE GATE
    # -------------------------------------------------------------------------
    nonsense_halt = handle_nonsense_gate(state, event_entry, message_text)
    if nonsense_halt is not None:
        result.halt_result = nonsense_halt
        return result

    # Q&A classification
    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    result.classification = classification

    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step4_Offer",
        )

    # -------------------------------------------------------------------------
    # CHANGE DETECTION (enhanced, dual-condition)
    # -------------------------------------------------------------------------
    unified_detection = get_unified_detection(state)
    result.unified_detection = unified_detection
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection,
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None
    if state.extras.get("detour_change_applied") == "date" and change_type == ChangeType.DATE:
        change_type = None
        if thread_id:
            trace_marker(
                thread_id,
                "SKIP_DUPLICATE_DATE_DETOUR",
                detail="Date change already applied in detour flow; skipping re-detection in Step4",
                owner_step="Step4_Offer",
            )

    if change_type is None:
        return result

    # Change detected: route per DAG rules
    decision = route_change_on_updated_variable(event_entry, change_type, from_step=4)

    if thread_id:
        trace_marker(
            thread_id,
            "CHANGE_DETECTED",
            detail=f"change_type={change_type.value}",
            data={
                "change_type": change_type.value,
                "from_step": 4,
                "to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "needs_reeval": decision.needs_reeval,
                "skip_reason": decision.skip_reason,
            },
            owner_step="Step4_Offer",
        )

    if decision.updated_caller_step is not None:
        update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

    # PRODUCTS change stays in step 4 — set flag to skip Q&A and regenerate offer
    if change_type.value == "products" and decision.next_step == 4:
        state.extras["products_change_detected"] = True
        if message_text and not user_info.get("products_add"):
            product_match = find_product(message_text)
            if product_match:
                user_info["products_add"] = [{"name": product_match.name, "quantity": 1}]
                state.user_info = user_info
                logger.info("[Step4] Extracted product from message: %s", product_match.name)
            else:
                menu_names = _menu_name_set()
                text_lower = message_text.lower()
                for menu in menu_names:
                    if menu.lower() in text_lower:
                        user_info["products_add"] = [{"name": menu, "quantity": 1}]
                        state.user_info = user_info
                        logger.info("[Step4] Extracted menu from message: %s", menu)
                        break
        # Continue to product processing (skip Q&A) — no halt_result
        return result

    if decision.next_step == 4:
        return result

    # Route to different step (detour)
    update_event_metadata(event_entry, current_step=decision.next_step)

    if change_type.value == "date" and decision.next_step == 2:
        update_event_metadata(
            event_entry,
            date_confirmed=False,
            room_eval_hash=None,
        )
    elif change_type.value == "requirements" and decision.next_step in (2, 3):
        metadata_updates: Dict[str, Any] = {"room_eval_hash": None, "locked_room_id": None}
        if decision.next_step == 2:
            metadata_updates["date_confirmed"] = False
        update_event_metadata(event_entry, **metadata_updates)

    append_audit_entry(event_entry, 4, decision.next_step, f"{change_type.value}_change_detected")

    ack_result = generate_detour_acknowledgment(
        change_type=change_type,
        decision=decision,
        event_entry=event_entry,
        user_info=user_info,
    )
    if ack_result.generated:
        add_detour_acknowledgment_draft(state, ack_result)

    update_event_metadata(event_entry, current_step=decision.next_step)
    state.current_step = decision.next_step
    state.set_thread_state("In Progress")
    state.extras["persist"] = True
    state.extras["change_detour"] = True
    state.extras.pop("hybrid_qna_response", None)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "change_type": change_type.value,
        "detour_to_step": decision.next_step,
        "caller_step": decision.updated_caller_step,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    result.halt_result = GroupResult(action="change_detour", payload=payload, halt=False)
    return result
