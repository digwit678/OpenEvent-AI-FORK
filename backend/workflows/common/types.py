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
class TurnTelemetry:
    """[Telemetry] Per-turn instrumentation payload for downstream logging."""

    buttons_rendered: bool = False
    buttons_enabled: bool = False
    missing_fields: List[str] = field(default_factory=list)
    clicked_button: str = "none"
    final_action: str = "none"
    detour_started: bool = False
    detour_completed: bool = False
    no_op_detour: bool = False
    caller_step: Optional[int] = None
    gatekeeper_passed: Dict[str, bool] = field(
        default_factory=lambda: {"step2": False, "step3": False, "step4": False, "step7": False}
    )
    gatekeeper_explain: Dict[str, Any] = field(default_factory=dict)
    answered_question_first: bool = False
    delta_availability_used: bool = False
    menus_included: str = "false"
    preask_candidates: List[str] = field(default_factory=list)
    preask_shown: List[str] = field(default_factory=list)
    preask_response: Dict[str, str] = field(default_factory=dict)
    preview_class_shown: str = "none"
    preview_items_count: int = 0
    choice_context_active: bool = False
    selection_method: str = "none"
    re_prompt_reason: str = "none"
    llm: Dict[str, Any] = field(default_factory=dict)
    captured_fields: List[str] = field(default_factory=list)
    promoted_fields: List[str] = field(default_factory=list)
    deferred_intents: List[str] = field(default_factory=list)
    dag_blocked: str = "none"

    def to_payload(self) -> Dict[str, Any]:
        """Serialise telemetry into a JSON-friendly payload."""

        return {
            "buttons_rendered": self.buttons_rendered,
            "buttons_enabled": self.buttons_enabled,
            "missing_fields": list(self.missing_fields),
            "clicked_button": self.clicked_button,
            "final_action": self.final_action,
            "detour_started": self.detour_started,
            "detour_completed": self.detour_completed,
            "no_op_detour": self.no_op_detour,
            "caller_step": self.caller_step,
            "gatekeeper_passed": dict(self.gatekeeper_passed),
            "gatekeeper_explain": dict(self.gatekeeper_explain),
            "answered_question_first": self.answered_question_first,
            "delta_availability_used": self.delta_availability_used,
            "menus_included": self.menus_included,
            "preask_candidates": list(self.preask_candidates),
            "preask_shown": list(self.preask_shown),
            "preask_response": dict(self.preask_response),
            "preview_class_shown": self.preview_class_shown,
            "preview_items_count": self.preview_items_count,
            "choice_context_active": self.choice_context_active,
            "selection_method": self.selection_method,
            "re_prompt_reason": self.re_prompt_reason,
            "llm": dict(self.llm),
            "captured_fields": list(self.captured_fields),
            "promoted_fields": list(self.promoted_fields),
            "deferred_intents": list(self.deferred_intents),
            "dag_blocked": self.dag_blocked,
        }

    # ------------------------------------------------------------------ #
    # Mapping helpers for dynamic telemetry fields
    # ------------------------------------------------------------------ #

    def setdefault(self, key: str, default: Any) -> Any:
        """Mimic dict.setdefault for known telemetry attributes."""

        if hasattr(self, key):
            value = getattr(self, key)
            if key == "llm" and not value:
                assigned = dict(default) if isinstance(default, dict) else default
                setattr(self, key, assigned)
                return getattr(self, key)
            if isinstance(value, list) and not value:
                assigned_list = list(default) if isinstance(default, list) else default
                setattr(self, key, assigned_list)
                return getattr(self, key)
            if value is None:
                setattr(self, key, default)
                return getattr(self, key)
            return value
        setattr(self, key, default)
        return getattr(self, key)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
            return
        raise KeyError(key)


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
    telemetry: TurnTelemetry = field(default_factory=TurnTelemetry)

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
