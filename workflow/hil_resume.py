from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from llm.verbalizer_agent import verbalize_gui_reply
from workflow.state import stage_payload, WorkflowStep, write_stage


def _locate_event(db: Dict[str, Any], event_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not event_id:
        return None
    for event in db.get("events", []):
        if event.get("event_id") == event_id:
            return event
    return None


def hil_resume(
    db: Dict[str, Any],
    event_id: Optional[str],
    task_id: str,
    *,
    client_email: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Resume a workflow step after HIL approval and compose the approved message payload.
    """

    if not task_id:
        return None

    event_entry = _locate_event(db, event_id)
    if not event_entry:
        return None

    pending = event_entry.get("pending_hil_requests") or []
    pending_entry = next((item for item in pending if item.get("task_id") == task_id), None)
    if not pending_entry:
        return None

    draft = pending_entry.get("draft") or {}
    if not draft:
        event_entry["pending_hil_requests"] = [item for item in pending if item.get("task_id") != task_id]
        return None

    event_entry["pending_hil_requests"] = [item for item in pending if item.get("task_id") != task_id]
    event_entry.setdefault("hil_resumes", []).append(
        {
            "task_id": task_id,
            "step": draft.get("step"),
            "approved_at": datetime.utcnow().isoformat() + "Z",
        }
    )

    # Ensure current step metadata stays aligned with the approved draft.
    step_num = draft.get("step")
    if isinstance(step_num, int) and 2 <= step_num <= 7:
        event_entry["current_step"] = step_num
        try:
            workflow_step = WorkflowStep(f"step_{step_num}")
            write_stage(event_entry, current_step=workflow_step)
        except ValueError:
            pass

    stage = stage_payload(event_entry)
    fallback = str(draft.get("body") or "")
    assistant_text = verbalize_gui_reply([draft], fallback, client_email=client_email)

    payload = {
        "assistant_text": assistant_text,
        "draft_messages": [draft],
        "action": draft.get("topic") or f"hil_step_{draft.get('step')}_approved",
        "payload": {
            "event_id": event_entry.get("event_id"),
            "task_id": task_id,
            "draft": draft,
            "stage": stage,
        },
        "step": draft.get("step"),
        "status": event_entry.get("status"),
        "stage": stage,
    }
    return payload