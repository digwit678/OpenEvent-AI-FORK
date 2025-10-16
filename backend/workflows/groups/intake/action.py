from __future__ import annotations

from typing import Any, Dict, Optional

from vocabulary import TaskType

from workflows.io.tasks import enqueue_task as _enqueue_task

__workflow_role__ = "Action"


def enqueue_manual_review_task(
    db: Dict[str, Any],
    client_id: str,
    linked_event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Queue a manual review task for non-event inquiries."""

    return _enqueue_task(db, TaskType.MANUAL_REVIEW, client_id, linked_event_id, payload)


def enqueue_missing_event_date_task(
    db: Dict[str, Any],
    client_id: str,
    linked_event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Queue a task requesting the client to confirm an event date."""

    return _enqueue_task(
        db,
        TaskType.REQUEST_MISSING_EVENT_DATE,
        client_id,
        linked_event_id,
        payload,
    )
