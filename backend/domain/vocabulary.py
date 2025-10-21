"""Centralized enumerations for workflow vocabulary."""

from __future__ import annotations

from enum import Enum


class IntentLabel(str, Enum):
    """Normalized email intents emitted by the classification pipeline."""

    EVENT_REQUEST = "event_request"
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


class TaskStatus(str, Enum):
    """Possible lifecycle states for human approval tasks."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"


__all__ = ["IntentLabel", "TaskType", "TaskStatus"]
