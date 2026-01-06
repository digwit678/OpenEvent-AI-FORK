"""Centralized enumerations for workflow vocabulary."""

from __future__ import annotations

from enum import Enum


class IntentLabel(str, Enum):
    """Normalized email intents emitted by the classification pipeline."""

    EVENT_REQUEST = "event_request"
    CONFIRM_DATE = "confirm_date"
    CONFIRM_DATE_PARTIAL = "confirm_date_partial"
    EDIT_DATE = "edit_date"
    EDIT_ROOM = "edit_room"
    EDIT_REQUIREMENTS = "edit_requirements"
    CAPABILITY_QNA = "capability_qna"
    RESUME_MAIN_FLOW = "resume_main_flow"
    MESSAGE_MANAGER = "message_manager"
    NON_EVENT = "other"

    @classmethod
    def normalize(cls, raw: str | None) -> "IntentLabel":
        """Map arbitrary strings to the closest supported intent label."""

        if raw is None:
            return cls.NON_EVENT
        try:
            return cls(raw)
        except ValueError:
            return cls.NON_EVENT


class TaskType(str, Enum):
    """Task categories surfaced to the human approval queue."""

    MANUAL_REVIEW = "manual_review"
    REQUEST_MISSING_EVENT_DATE = "ask_for_date"
    ROUTE_POST_OFFER = "route_post_offer"
    ROUTE_SITE_VISIT = "route_site_visit"
    SITE_VISIT_HIL_REVIEW = "site_visit_hil_review"
    MESSAGE_MANAGER = "message_manager"
    DATE_CONFIRMATION_MESSAGE = "date_confirmation_message"
    ROOM_AVAILABILITY_MESSAGE = "room_availability_message"
    OFFER_MESSAGE = "offer_message"
    # NEW: AI reply approval (when OE_HIL_ALL_LLM_REPLIES=true)
    # All AI-generated outbound replies go to separate "AI Reply Approval" queue
    AI_REPLY_APPROVAL = "ai_reply_approval"


class TaskStatus(str, Enum):
    """Possible lifecycle states for human approval tasks."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"


__all__ = ["IntentLabel", "TaskType", "TaskStatus"]
