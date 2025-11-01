from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator


class AssistantReply(BaseModel):
    """Normalized envelope every agent turn must return."""

    assistant_text: str = Field(..., description="Plain-text response for the client.")
    requires_hil: bool = Field(..., description="Whether the draft requires human approval.")
    action: str = Field(..., description="Workflow action identifier (e.g., 'date_options_proposed').")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured workflow payload.")

    @field_validator("assistant_text")
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("assistant_text must not be empty")
        return cleaned

    @field_validator("action")
    def _validate_action(cls, value: str) -> str:
        if not value or value.strip() != value:
            raise ValueError("action must be a non-empty string without leading/trailing whitespace")
        return value


class ToolError(BaseModel):
    """Wrapper used when a tool execution fails validation."""

    assistant_text: str = Field(..., description="Friendly explanation for the client.")
    requires_hil: bool = Field(default=True, description="Tool failures always require HIL.")
    action: str = Field(default="tool_validation_failed")
    payload: Dict[str, Any] = Field(default_factory=dict)


def validate_envelope(data: Dict[str, Any]) -> AssistantReply:
    """Validate raw agent output and normalize into an AssistantReply."""

    try:
        return AssistantReply.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - thin wrapper
        raise ValueError(f"Invalid agent reply: {exc}") from exc


class URLPayload(BaseModel):
    url: HttpUrl


class CandidateDates(BaseModel):
    dates: List[str] = Field(default_factory=list)

    @field_validator("dates")
    def _date_format(cls, value: List[str]) -> List[str]:
        for item in value:
            if len(item) != 10 or item[2] != "." or item[5] != ".":
                raise ValueError("Dates must be formatted as DD.MM.YYYY")
        return value


class LockedRoomPayload(BaseModel):
    locked_room_id: str
    chosen_date: str

    @field_validator("locked_room_id")
    def _room_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("locked_room_id is required")
        return value

    @field_validator("chosen_date")
    def _date_format(cls, value: str) -> str:
        if len(value) != 10 or value[2] != "." or value[5] != ".":
            raise ValueError("chosen_date must be formatted as DD.MM.YYYY")
        return value


class OfferPayload(BaseModel):
    offer_id: str
    total_amount: float

    @field_validator("offer_id")
    def _offer_id(cls, value: str) -> str:
        if not value:
            raise ValueError("offer_id must be provided")
        return value


class NegotiationPayload(BaseModel):
    status: str = Field(..., pattern=r"^(accept|decline|counter|clarify)$")
    offer_id: Optional[str]
    counter_count: Optional[int]


class TransitionPayload(BaseModel):
    status: str = Field(..., pattern=r"^(in_progress|awaiting_client|complete)$")
    current_step: Optional[int]


class ConfirmationPayload(BaseModel):
    classification: str = Field(..., pattern=r"^(confirm_booking|reserve_option|schedule_site_visit|deposit_request|decline|clarify)$")
    next_step: Optional[int]


class SessionState(BaseModel):
    """Session snapshot persisted between agent turns."""

    event_id: Optional[str]
    current_step: Optional[int]
    caller_step: Optional[int]
    requirements_hash: Optional[str]
    room_eval_hash: Optional[str]
    offer_hash: Optional[str]
    status: Optional[str]


def safe_envelope(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate `data` as an AssistantReply, converting failures into a HIL-blocking
    placeholder so the UI never receives malformed content.
    """

    try:
        envelope = validate_envelope(data)
        return envelope.model_dump()
    except ValueError as exc:
        error = ToolError(
            assistant_text="Something went wrong while drafting the response. A manager will double-check and follow up.",
            payload={"error": str(exc)},
        )
        return error.model_dump()
