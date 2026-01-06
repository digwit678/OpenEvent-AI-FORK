from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from workflow_email import process_msg as workflow_process_msg

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_transition_sync": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "client_email": {"type": "string"},
            "message": {"type": "string"},
            "msg_id": {"type": ["string", "null"]},
        },
        "required": ["event_id", "client_email", "message"],
        "additionalProperties": False,
    }
}


class TransitionInput(BaseModel):
    event_id: str = Field(..., description="Event identifier for the transition step.")
    client_email: str = Field(..., description="Client email address.")
    message: str = Field(..., description="Client transition response.")
    msg_id: Optional[str] = Field(None, description="Optional message identifier.")


class TransitionOutput(BaseModel):
    action: str
    payload: Dict[str, Any]


def tool_transition_sync(params: TransitionInput) -> TransitionOutput:
    """
    Proxy transition handling to the existing workflow Step 6 pipeline.
    """

    synthetic_message = {
        "msg_id": params.msg_id or f"agent-transition-{params.event_id}",
        "from_name": "Client (Agent)",
        "from_email": params.client_email,
        "subject": "Transition update",
        "ts": None,
        "body": params.message,
    }
    result = workflow_process_msg(synthetic_message)
    action = result.get("action") or "transition_progress"
    payload = {k: v for k, v in result.items() if k != "draft_messages"}
    payload["draft_messages"] = result.get("draft_messages") or []
    return TransitionOutput(action=action, payload=payload)
