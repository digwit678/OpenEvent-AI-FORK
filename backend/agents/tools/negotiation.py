from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.workflow_email import process_msg as workflow_process_msg

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_negotiate_offer": {
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


class NegotiationInput(BaseModel):
    """Proxy parameters for negotiation handling."""

    event_id: str = Field(..., description="Event identifier to route the negotiation message.")
    client_email: str = Field(..., description="Client email address.")
    message: str = Field(..., description="Client negotiation message body.")
    msg_id: Optional[str] = Field(None, description="Optional message identifier for traceability.")


class NegotiationOutput(BaseModel):
    action: str
    payload: Dict[str, Any]


def tool_negotiate_offer(params: NegotiationInput) -> NegotiationOutput:
    """
    Delegate negotiation handling to the deterministic workflow.

    This ensures all DB writes follow the existing Step 5 pathway while allowing
    the agent to treat the result as a tool response.
    """

    synthetic_message = {
        "msg_id": params.msg_id or f"agent-negotiation-{params.event_id}",
        "from_name": "Client (Agent)",
        "from_email": params.client_email,
        "subject": "Negotiation update",
        "ts": None,
        "body": params.message,
    }
    result = workflow_process_msg(synthetic_message)
    action = result.get("action") or "negotiation_clarification"
    payload = {k: v for k, v in result.items() if k != "draft_messages"}
    payload["draft_messages"] = result.get("draft_messages") or []
    return NegotiationOutput(action=action, payload=payload)
