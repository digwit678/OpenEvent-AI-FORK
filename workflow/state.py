from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from domain import EventStatus
from workflows.io.database import ensure_event_defaults, update_event_metadata


class WorkflowStep(Enum):
    STEP_1 = "step_1"
    STEP_2 = "step_2"
    STEP_3 = "step_3"
    STEP_4 = "step_4"
    STEP_5 = "step_5"
    STEP_6 = "step_6"
    STEP_7 = "step_7"

    @property
    def numeric(self) -> int:
        mapping = {
            "step_1": 1,
            "step_2": 2,
            "step_3": 3,
            "step_4": 4,
            "step_5": 5,
            "step_6": 6,
            "step_7": 7,
        }
        return mapping[self.value]

    @property
    def label(self) -> str:
        labels = {
            "step_1": "Intake",
            "step_2": "Date Confirmation",
            "step_3": "Room Availability",
            "step_4": "Offer Review",
            "step_5": "Negotiation",
            "step_6": "Transition Checkpoint",
            "step_7": "Confirmation",
        }
        return labels[self.value]


@dataclass
class WorkflowStage:
    current_step: WorkflowStep
    subflow_group: str
    caller_step: Optional[WorkflowStep]
    status: str

    @property
    def label(self) -> str:
        return f"Step {self.current_step.numeric} — {self.current_step.label}"


def _coerce_step(value: Any, default: WorkflowStep = WorkflowStep.STEP_1) -> WorkflowStep:
    if isinstance(value, WorkflowStep):
        return value
    if isinstance(value, int) and 1 <= value <= 7:
        return WorkflowStep(f"step_{value}")
    if isinstance(value, str):
        lowered = value.strip().lower()
        value_map = WorkflowStep._value2member_map_
        if lowered in value_map:
            return value_map[lowered]
        if lowered in WorkflowStep.__members__:
            return WorkflowStep[lowered]
    return default


_DEFAULT_SUBFLOW_BY_STEP = {
    WorkflowStep.STEP_1: "intake",
    WorkflowStep.STEP_2: "date_confirmation",
    WorkflowStep.STEP_3: "room_availability",
    WorkflowStep.STEP_4: "offer_review",
    WorkflowStep.STEP_5: "negotiation",
    WorkflowStep.STEP_6: "transition_checkpoint",
    WorkflowStep.STEP_7: "confirmation",
}


def default_subflow(step: WorkflowStep) -> str:
    return _DEFAULT_SUBFLOW_BY_STEP.get(step, "intake")


def read_stage(event_entry: Dict[str, Any]) -> WorkflowStage:
    ensure_event_defaults(event_entry)
    raw_step = event_entry.get("current_step_stage") or event_entry.get("current_step")
    subflow = event_entry.get("subflow_group") or "intake"
    caller_raw = event_entry.get("caller_step_stage") or event_entry.get("caller_step")
    status = event_entry.get("status") or EventStatus.LEAD.value
    current_step = _coerce_step(raw_step)
    caller_step = None if caller_raw is None else _coerce_step(caller_raw, default=current_step)
    return WorkflowStage(current_step=current_step, subflow_group=subflow, caller_step=caller_step, status=status)


def write_stage(
    event_entry: Dict[str, Any],
    *,
    current_step: Optional[WorkflowStep] = None,
    subflow_group: Optional[str] = None,
    caller_step: Optional[WorkflowStep] = None,
    status: Optional[EventStatus] = None,
) -> None:
    ensure_event_defaults(event_entry)
    fields: Dict[str, Any] = {}
    if current_step is not None:
        fields["current_step_stage"] = current_step.value
        fields["current_step"] = current_step.numeric
    if subflow_group is not None:
        fields["subflow_group"] = subflow_group
    elif current_step is not None:
        fields["subflow_group"] = default_subflow(current_step)
    if caller_step is not None:
        fields["caller_step_stage"] = caller_step.value
        fields["caller_step"] = caller_step.numeric
    if status is not None:
        fields["status"] = status.value if isinstance(status, EventStatus) else str(status)
    if fields:
        update_event_metadata(event_entry, **fields)


def stage_payload(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    stage = read_stage(event_entry)
    payload = {
        "current_step": stage.current_step.value,
        "current_step_numeric": stage.current_step.numeric,
        "current_step_label": stage.label,
        "subflow_group": stage.subflow_group,
        "status": stage.status,
    }
    if stage.caller_step is not None:
        payload["caller_step"] = stage.caller_step.value
        payload["caller_step_numeric"] = stage.caller_step.numeric
        payload["caller_step_label"] = f"Step {stage.caller_step.numeric} — {stage.caller_step.label}"
    return payload


def get_thread_state(thread_id: str) -> Dict[str, Any]:
    from debug.state_store import STATE_STORE

    return STATE_STORE.get(thread_id)
