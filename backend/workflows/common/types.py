from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain import IntentLabel


@dataclass
class IncomingMessage:
    """[Trigger] Normalized representation of an inbound workflow message."""

    msg_id: Optional[str]
    from_name: Optional[str]
    from_email: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    ts: Optional[str]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IncomingMessage":
        """[Trigger] Build an IncomingMessage from a raw dict payload."""

        return cls(
            msg_id=payload.get("msg_id"),
            from_name=payload.get("from_name"),
            from_email=payload.get("from_email"),
            subject=payload.get("subject"),
            body=payload.get("body"),
            ts=payload.get("ts"),
        )

    def to_payload(self) -> Dict[str, Optional[str]]:
        """[Trigger] Expose message details in adapter-friendly format."""

        return {
            "msg_id": self.msg_id,
            "from_name": self.from_name,
            "from_email": self.from_email,
            "subject": self.subject,
            "body": self.body,
            "ts": self.ts,
        }


@dataclass
class WorkflowState:
    """[OpenEvent Database] Mutable state shared between workflow groups."""

    message: IncomingMessage
    db_path: Path
    db: Dict[str, Any]
    client: Optional[Dict[str, Any]] = None
    client_id: Optional[str] = None
    intent: Optional[IntentLabel] = None
    confidence: Optional[float] = None
    user_info: Dict[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None
    event_entry: Optional[Dict[str, Any]] = None
    updated_fields: list[str] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    def record_context(self, context: Dict[str, Any]) -> None:
        """[OpenEvent Database] Store the latest context snapshot for the workflow."""

        self.context_snapshot = context


@dataclass
class GroupResult:
    """[Trigger] Encapsulates the outcome of a workflow group."""

    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    halt: bool = False

    def merged(self) -> Dict[str, Any]:
        """[Condition] Combine the action label with payload for orchestrator consumption."""

        data = dict(self.payload)
        data.setdefault("action", self.action)
        return data
