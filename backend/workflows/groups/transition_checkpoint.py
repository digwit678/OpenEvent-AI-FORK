from __future__ import annotations

from typing import Any, Dict, List

from backend.domain import TaskType
from backend.workflows.groups.negotiation_close import _handle_accept
from backend.workflows.io.tasks import enqueue_task

from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.utils.profiler import profile_step

__all__ = ["process"]


@profile_step("workflow.step6.transition")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Step 6 — transition checkpoint to validate consistency before confirmation."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": None,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event",
            "context": state.context_snapshot,
        }
        return GroupResult(action="transition_missing_event", payload=payload, halt=True)

    state.current_step = 6
    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    blockers = _collect_blockers(event_entry)
    if negotiation_state.get("pending_acceptance"):
        non_offer_blockers = [blocker for blocker in blockers if blocker != "accepted offer version"]
        if not non_offer_blockers:
            response = _handle_accept(event_entry)
            state.add_draft_message(response["draft"])
            negotiation_state["pending_acceptance"] = False
            task_payload = {
                "reason": "offer_accepted",
                "offer_id": response["offer_id"],
                "room": event_entry.get("locked_room_id"),
                "date": event_entry.get("chosen_date"),
                "total_amount": response.get("total_amount"),
            }
            enqueue_task(
                state.db,
                TaskType.ROUTE_POST_OFFER,
                state.client_id or "",
                event_entry.get("event_id"),
                task_payload,
            )
            state.telemetry.final_action = "accepted"
            blockers = _collect_blockers(event_entry)
    if blockers:
        blocker_text = "; ".join(blockers)
        draft = {
            "body": f"Transition halted: {blocker_text}. Please resolve before continuing.",
            "step": 6,
            "topic": "transition_clarification",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=6, transition_ready=False, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "blockers": blockers,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="transition_blocked", payload=payload, halt=True)

    update_event_metadata(event_entry, transition_ready=True, current_step=7, thread_state="In Progress")
    append_audit_entry(event_entry, 6, 7, "transition_ready")
    state.current_step = 7
    state.set_thread_state("In Progress")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "transition_ready": True,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="transition_ready", payload=payload, halt=True)


def _collect_blockers(event_entry: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not event_entry.get("chosen_date"):
        blockers.append("confirmed event date")
    if not event_entry.get("locked_room_id"):
        blockers.append("locked room selection")
    if event_entry.get("requirements_hash") and event_entry.get("room_eval_hash"):
        if event_entry["requirements_hash"] != event_entry["room_eval_hash"]:
            blockers.append("room availability check on latest requirements")
    offer_status = event_entry.get("offer_status")
    if offer_status != "Accepted":
        blockers.append("accepted offer version")

    deposit_state = event_entry.get("deposit_state") or {}
    if deposit_state.get("required") and deposit_state.get("status") not in {"paid", "not_required"}:
        blockers.append("deposit payment")
    return blockers
