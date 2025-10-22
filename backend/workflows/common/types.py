from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    current_step: Optional[int] = None
    caller_step: Optional[int] = None
    thread_state: Optional[str] = None
    draft_messages: List[Dict[str, Any]] = field(default_factory=list)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)

    def record_context(self, context: Dict[str, Any]) -> None:
        """[OpenEvent Database] Store the latest context snapshot for the workflow."""

        self.context_snapshot = context

    def add_draft_message(self, message: Dict[str, Any]) -> None:
        """[HIL] Register a draft message awaiting approval before sending."""

        message.setdefault("requires_approval", True)
        message.setdefault("created_at_step", self.current_step)
        self.draft_messages.append(message)

    def set_thread_state(self, value: str) -> None:
        """[OpenEvent Database] Track whether the thread awaits a client reply."""

        self.thread_state = value

    def add_audit_entry(self, from_step: int, to_step: int, reason: str, actor: str = "system") -> None:
        """[OpenEvent Database] Buffer audit entries for persistence."""

        self.audit_log.append(
            {
                "from_step": from_step,
                "to_step": to_step,
                "reason": reason,
                "actor": actor,
            }
        )


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
