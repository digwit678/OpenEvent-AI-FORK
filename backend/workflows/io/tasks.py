from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from vocabulary import TaskStatus, TaskType


def enqueue_task(
    db: Dict[str, Any],
    task_type: TaskType,
    client_id: str,
    event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Queue a human-facing task for manual follow-up."""

    task_id = str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "created_at": datetime.utcnow().isoformat(),
        "type": task_type.value,
        "status": TaskStatus.PENDING.value,
        "client_id": client_id,
        "event_id": event_id,
        "payload": payload,
        "notes": "",
    }
    db.setdefault("tasks", []).append(task)
    return task_id


def update_task_status(
    db: Dict[str, Any], task_id: str, status: Union[str, TaskStatus], notes: Optional[str] = None
) -> None:
    """[OpenEvent Action] Update the lifecycle state of a task after human input."""

    if isinstance(status, TaskStatus):
        normalized_status = status.value
    else:
        try:
            normalized_status = TaskStatus(status).value
        except ValueError as exc:
            raise ValueError(f"Unsupported task status '{status}'") from exc
    task = _find_task(db, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    task["status"] = normalized_status
    if notes is not None:
        task["notes"] = notes


def list_pending_tasks(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[OpenEvent Action] Return tasks that still await manual handling."""

    return [task for task in db.get("tasks", []) if task.get("status") == TaskStatus.PENDING.value]


def _find_task(db: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    """[OpenEvent Action] Locate a task dictionary inside the database."""

    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None
