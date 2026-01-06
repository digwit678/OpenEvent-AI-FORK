from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.workflow_email import process_msg as workflow_process_msg

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_classify_confirmation": {
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


class ConfirmationInput(BaseModel):
    event_id: str = Field(..., description="Event identifier.")
    client_email: str = Field(..., description="Client email address.")
    message: str = Field(..., description="Client confirmation step message.")
    msg_id: Optional[str] = Field(None, description="Optional message identifier.")


class ConfirmationOutput(BaseModel):
    action: str
    payload: Dict[str, Any]


def tool_classify_confirmation(params: ConfirmationInput) -> ConfirmationOutput:
    """
    Run the existing Step 7 workflow and return its structured output.
    """

    synthetic_message = {
        "msg_id": params.msg_id or f"agent-confirmation-{params.event_id}",
        "from_name": "Client (Agent)",
        "from_email": params.client_email,
        "subject": "Confirmation update",
        "ts": None,
        "body": params.message,
    }
    result = workflow_process_msg(synthetic_message)
    action = result.get("action") or "confirmation_pending"
    payload = {k: v for k, v in result.items() if k != "draft_messages"}
    payload["draft_messages"] = result.get("draft_messages") or []
    return ConfirmationOutput(action=action, payload=payload)
