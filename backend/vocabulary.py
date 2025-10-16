"""Centralized enumerations for workflow vocabulary.

The management plan defines consistent terminology for intents, tasks,
and task statuses across the event management platform.  Having a single
module that codifies those values makes it easier to read the codebase
and reason about the workflow logic.
"""

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


class TaskStatus(str, Enum):
    """Possible lifecycle states for human approval tasks."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"


__all__ = ["IntentLabel", "TaskType", "TaskStatus"]
