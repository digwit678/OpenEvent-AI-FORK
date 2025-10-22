from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

from backend.adapters.agent_adapter import get_agent_adapter
from backend.domain import TaskStatus

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.common.types import GroupResult
from backend.workflows.groups import intake, date_confirmation, room_availability
from backend.workflows.groups.offer.trigger import process as process_offer
from backend.workflows.groups.negotiation_close import process as process_negotiation
from backend.workflows.groups.transition_checkpoint import process as process_transition
from backend.workflows.groups.event_confirmation.trigger import process as process_confirmation
from backend.workflows.io import database as db_io
from backend.workflows.io import tasks as task_io
from backend.workflows.llm import adapter as llm_adapter


DB_PATH = Path(__file__).with_name("events_database.json")
LOCK_PATH = Path(__file__).with_name(".events_db.lock")

enqueue_task = task_io.enqueue_task
update_task_status = task_io.update_task_status
list_pending_tasks = task_io.list_pending_tasks
get_default_db = db_io.get_default_db


def _same_default(path: Path) -> bool:
    """[Condition] Detect whether a path resolves to the default workflow database."""

    try:
        return path.resolve() == DB_PATH.resolve()
    except FileNotFoundError:
        return path == DB_PATH


def _resolve_lock_path(path: Path) -> Path:
    """[OpenEvent Database] Determine the lockfile used for a database path."""

    if _same_default(path):
        return LOCK_PATH
    return db_io.lock_path_for(path)


def load_db(path: Path = DB_PATH) -> Dict[str, Any]:
    """[OpenEvent Database] Load the workflow database with locking safeguards."""

    path = Path(path)
    lock_path = _resolve_lock_path(path)
    return db_io.load_db(path, lock_path=lock_path)


def save_db(db: Dict[str, Any], path: Path = DB_PATH) -> None:
    """[OpenEvent Database] Persist the workflow database atomically."""

    path = Path(path)
    lock_path = _resolve_lock_path(path)
    db_io.save_db(db, path, lock_path=lock_path)


def _persist_if_needed(state: WorkflowState, path: Path, lock_path: Path) -> None:
    """[OpenEvent Database] Write stateful changes to disk when groups request it."""

    if state.extras.pop("persist", False):
        db_io.save_db(state.db, path, lock_path=lock_path)


def process_msg(msg: Dict[str, Any], db_path: Path = DB_PATH) -> Dict[str, Any]:
    """[Trigger] Process an inbound message through workflow groups A–C."""

    path = Path(db_path)
    lock_path = _resolve_lock_path(path)
    db = db_io.load_db(path, lock_path=lock_path)

    message = IncomingMessage.from_dict(msg)
    state = WorkflowState(message=message, db_path=path, db=db)

    last_result = intake.process(state)
    _persist_if_needed(state, path, lock_path)
    if last_result.halt:
        return _finalize_output(last_result, state)

    for _ in range(6):
        event_entry = state.event_entry
        if not event_entry:
            break
        step = event_entry.get("current_step")
        if step == 2:
            last_result = date_confirmation.process(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        if step == 3:
            last_result = room_availability.process(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        if step == 4:
            last_result = process_offer(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        if step == 5:
            last_result = process_negotiation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        if step == 6:
            last_result = process_transition(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        if step == 7:
            last_result = process_confirmation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                return _finalize_output(last_result, state)
            continue
        break

    return _finalize_output(last_result, state)


def run_samples() -> list[Any]:
    """[Trigger] Execute a deterministic sample flow for manual testing."""

    os.environ["AGENT_MODE"] = "stub"
    llm_adapter.adapter = get_agent_adapter()
    if DB_PATH.exists():
        DB_PATH.unlink()

    samples = [
        {
            "msg_id": "sample-1",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Event inquiry for our workshop",
            "ts": "2025-10-13T09:00:00Z",
            "body": (
                "Hello,\n"
                "We would like to reserve Room A for approx 15 ppl next month for a workshop.\n"
                "Could you share available dates? Language: en.\n"
                "Phone: 042754980\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
        {
            "msg_id": "sample-2",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Event Request: 15.03.2025 Room A",
            "ts": "2025-10-14T10:31:00Z",
            "body": (
                "Hello,\n"
                "We confirm the workshop should be on 15.03.2025 in Room A.\n"
                "We expect 15 participants and would like catering preference: Standard Buffet.\n"
                "Start at 14:00 and end by 16:00.\n"
                "Company: TechCorp\n"
                "Language: English\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
        {
            "msg_id": "sample-3",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Parking question",
            "ts": "2025-10-16T08:05:00Z",
            "body": (
                "Hello,\n"
                "Is there parking available nearby? Just checking for next week.\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
    ]

    outputs: list[Any] = []
    for msg in samples:
        res = process_msg(msg)
        print(res)
        outputs.append(res)

    if sys.stdin.isatty():
        task_cli_loop()
    return outputs


def task_cli_loop(db_path: Path = DB_PATH) -> None:
    """[OpenEvent Action] Provide a simple CLI to inspect and update tasks."""

    while True:
        print("\nOpenEvent Action Queue")
        print("1) List pending tasks")
        print("2) Approve a task")
        print("3) Reject a task")
        print("4) Mark task done")
        print("5) Exit")
        choice = input("Select option: ").strip()
        if choice == "1":
            db = load_db(db_path)
            pending = list_pending_tasks(db)
            if not pending:
                print("No pending tasks.")
            else:
                for task in pending:
                    payload_preview = task.get("payload") or {}
                    print(
                        f"- {task.get('task_id')} | {task.get('type')} | "
                        f"{payload_preview.get('reason') or payload_preview.get('preferred_room')}"
                    )
        elif choice in {"2", "3", "4"}:
            task_id = input("Task ID: ").strip()
            notes = input("Notes (optional): ").strip() or None
            status_map = {"2": TaskStatus.APPROVED, "3": TaskStatus.REJECTED, "4": TaskStatus.COMPLETED}
            db = load_db(db_path)
            update_task_status(db, task_id, status_map[choice], notes)
            save_db(db, db_path)
            print(f"Task {task_id} updated to {status_map[choice].value}.")
        elif choice == "5":
            return
        else:
            print("Invalid choice.")


def _finalize_output(result: GroupResult, state: WorkflowState) -> Dict[str, Any]:
    """[Trigger] Normalise final payload with workflow metadata."""

    payload = result.merged()
    event_entry = state.event_entry
    if event_entry:
        payload.setdefault("event_id", event_entry.get("event_id"))
        payload["current_step"] = event_entry.get("current_step")
        payload["caller_step"] = event_entry.get("caller_step")
        payload["thread_state"] = event_entry.get("thread_state")
    elif state.thread_state:
        payload["thread_state"] = state.thread_state
    if state.draft_messages:
        payload["draft_messages"] = state.draft_messages
    else:
        payload.setdefault("draft_messages", [])
    return payload
