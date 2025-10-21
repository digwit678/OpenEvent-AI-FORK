from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from backend.domain import TaskStatus, TaskType
from backend.workflows.io.tasks import enqueue_task as _enqueue_task

__workflow_role__ = "Action"

__all__ = [
    "attach_post_offer_classification",
    "enqueue_post_offer_routing_task",
]


def attach_post_offer_classification(
    db: Dict[str, Any],
    client_email: str,
    message_id: str,
    classification: Dict[str, Any],
) -> None:
    """Store the post-offer classification on the matching client history item."""

    email_key = (client_email or "").lower()
    clients = db.get("clients") or {}
    client = clients.get(email_key)
    if not client:
        raise KeyError(f"Client '{email_key}' not found in database.")

    history = client.get("history") or []
    for entry in history:
        if entry.get("msg_id") == message_id:
            entry["post_offer_classification"] = copy.deepcopy(classification)
            return

    raise KeyError(f"Message '{message_id}' not found in history for client '{email_key}'.")


def enqueue_post_offer_routing_task(
    db: Dict[str, Any],
    client_email: str,
    event_id: Optional[str],
    message_id: str,
    routing_hint: str,
) -> str:
    """Queue a route_post_offer task if one does not already exist for this message."""

    email_key = (client_email or "").lower()
    tasks = db.setdefault("tasks", [])
    for task in tasks:
        if (
            task.get("type") == TaskType.ROUTE_POST_OFFER.value
            and task.get("status") == TaskStatus.PENDING.value
            and (task.get("payload") or {}).get("message_msg_id") == message_id
        ):
            task.setdefault("payload", {})["routing_hint"] = routing_hint
            return task["task_id"]

    payload = {
        "routing_hint": routing_hint,
        "message_msg_id": message_id,
    }
    return _enqueue_task(
        db,
        TaskType.ROUTE_POST_OFFER,
        email_key,
        event_id,
        payload,
    )
