from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import logging

from backend.domain import TaskStatus, TaskType

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
from backend.workflows.planner import maybe_run_smart_shortcuts
from backend.utils.profiler import profile_step
from backend.workflow.state import stage_payload
from backend.debug.lifecycle import close_if_ended
from backend.workflow.guards import evaluate as evaluate_guards

logger = logging.getLogger(__name__)
WF_DEBUG = os.getenv("WF_DEBUG_STATE") == "1"


def _debug_state(stage: str, state: WorkflowState, extra: Optional[Dict[str, Any]] = None) -> None:
    debug_trace_enabled = os.getenv("DEBUG_TRACE") == "1"
    if not WF_DEBUG and not debug_trace_enabled:
        return

    event_entry = state.event_entry or {}
    requirements = event_entry.get("requirements") or {}
    shortcuts = event_entry.get("shortcuts") or {}
    info = {
        "stage": stage,
        "step": event_entry.get("current_step"),
        "caller": event_entry.get("caller_step"),
        "thread": event_entry.get("thread_state"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "chosen_date": event_entry.get("chosen_date"),
        "participants": requirements.get("number_of_participants") or requirements.get("participants"),
        "capacity_shortcut": shortcuts.get("capacity_ok"),
        "vague_month": event_entry.get("vague_month"),
        "vague_weekday": event_entry.get("vague_weekday"),
        "vague_time": event_entry.get("vague_time_of_day"),
    }
    if extra:
        info.update(extra)
    if WF_DEBUG:
        serialized = " ".join(f"{key}={value}" for key, value in info.items())
        print(f"[WF DEBUG][state] {serialized}")

    if not debug_trace_enabled:
        return

    thread_id = _thread_identifier(state)
    snapshot = dict(info)
    snapshot.update(
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "offer_id": event_entry.get("offer_id"),
            "locked_room_id": event_entry.get("locked_room_id"),
            "wish_products": event_entry.get("wish_products"),
            "thread_state": state.thread_state,
            "caller_step": event_entry.get("caller_step"),
        }
    )
    from backend.debug.hooks import trace_state  # pylint: disable=import-outside-toplevel
    from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

    trace_state(thread_id, _snapshot_step_name(event_entry), snapshot)
    STATE_STORE.update(thread_id, snapshot)
    close_if_ended(thread_id, snapshot)


_TRACE_STEP_NAMES = {
    1: "Step1_Intake",
    2: "Step2_Date",
    3: "Step3_Room",
    4: "Step4_Offer",
    5: "Step5_Negotiation",
    6: "Step6_Transition",
    7: "Step7_Confirmation",
}


def _snapshot_step_name(event_entry: Optional[Dict[str, Any]]) -> str:
    if not event_entry:
        return "intake"
    raw = event_entry.get("current_step")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return "intake"
    return _TRACE_STEP_NAMES.get(value, "intake")


def _thread_identifier(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


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
    """[OpenEvent Database] Flag persistence requests so we can coalesce writes."""

    if state.extras.pop("persist", False):
        state.extras["_pending_save"] = True


def _flush_pending_save(state: WorkflowState, path: Path, lock_path: Path) -> None:
    """[OpenEvent Database] Flush debounced writes at the end of the turn."""

    if state.extras.pop("_pending_save", False):
        db_io.save_db(state.db, path, lock_path=lock_path)


def _flush_and_finalize(result: GroupResult, state: WorkflowState, path: Path, lock_path: Path) -> Dict[str, Any]:
    """Persist pending state and normalise the outgoing payload."""

    output = _finalize_output(result, state)
    _flush_pending_save(state, path, lock_path)
    return output


def _hil_signature(draft: Dict[str, Any], event_entry: Dict[str, Any]) -> str:
    base = {
        "step": draft.get("step"),
        "topic": draft.get("topic"),
        "caller": event_entry.get("caller_step"),
        "requirements_hash": event_entry.get("requirements_hash"),
        "room_eval_hash": event_entry.get("room_eval_hash"),
        "body": draft.get("body"),
    }
    payload = json.dumps(base, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _enqueue_hil_tasks(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    pending_records = event_entry.setdefault("pending_hil_requests", [])
    seen_signatures = {entry.get("signature") for entry in pending_records if entry.get("signature")}

    for draft in state.draft_messages:
        if draft.get("requires_approval") is False:
            continue
        signature = _hil_signature(draft, event_entry)
        if signature in seen_signatures:
            continue

        step_id = draft.get("step")
        try:
            step_num = int(step_id)
        except (TypeError, ValueError):
            continue
        if step_num not in {2, 3, 4}:
            continue
        if step_num == 4:
            task_type = TaskType.OFFER_MESSAGE
        elif step_num == 3:
            task_type = TaskType.ROOM_AVAILABILITY_MESSAGE
        elif step_num == 2:
            task_type = TaskType.DATE_CONFIRMATION_MESSAGE
        else:
            task_type = TaskType.MANUAL_REVIEW

        task_payload = {
            "step_id": step_num,
            "intent": state.intent.value if state.intent else None,
            "event_id": event_entry.get("event_id"),
            "draft_msg": draft.get("body"),
            "language": (state.user_info or {}).get("language"),
            "caller_step": event_entry.get("caller_step"),
            "requirements_hash": event_entry.get("requirements_hash"),
            "room_eval_hash": event_entry.get("room_eval_hash"),
        }

        client_id = state.client_id or (state.message.from_email or "unknown@example.com").lower()
        task_id = enqueue_task(
            state.db,
            task_type,
            client_id,
            event_entry.get("event_id"),
            task_payload,
        )
        pending_records.append(
            {
                "task_id": task_id,
                "signature": signature,
                "step": step_num,
                "draft": dict(draft),
            }
        )
        seen_signatures.add(signature)
        state.extras["persist"] = True


@profile_step("workflow.router.process_msg")
def process_msg(msg: Dict[str, Any], db_path: Path = DB_PATH) -> Dict[str, Any]:
    """[Trigger] Process an inbound message through workflow groups A–C."""

    path = Path(db_path)
    lock_path = _resolve_lock_path(path)
    db = db_io.load_db(path, lock_path=lock_path)

    message = IncomingMessage.from_dict(msg)
    state = WorkflowState(message=message, db_path=path, db=db)
    raw_thread_id = (
        msg.get("thread_id")
        or msg.get("thread")
        or msg.get("session_id")
        or msg.get("msg_id")
        or msg.get("from_email")
        or "unknown-thread"
    )
    state.thread_id = str(raw_thread_id)
    _debug_state("init", state)
    last_result = intake.process(state)
    _debug_state("post_intake", state, extra={"intent": state.intent.value if state.intent else None})
    _persist_if_needed(state, path, lock_path)
    if last_result.halt:
        _debug_state("halt_post_intake", state)
        return _flush_and_finalize(last_result, state, path, lock_path)

    guard_snapshot = evaluate_guards(state)
    if guard_snapshot.step2_required and guard_snapshot.candidate_dates:
        state.extras["guard_candidate_dates"] = list(guard_snapshot.candidate_dates)

    shortcut_result = maybe_run_smart_shortcuts(state)
    if shortcut_result is not None:
        _debug_state(
            "smart_shortcut",
            state,
            extra={"shortcut_action": shortcut_result.action},
        )
        _persist_if_needed(state, path, lock_path)
        return _flush_and_finalize(shortcut_result, state, path, lock_path)

    for _ in range(6):
        event_entry = state.event_entry
        if not event_entry:
            break
        step = event_entry.get("current_step")
        if step == 2:
            last_result = date_confirmation.process(state)
            _debug_state("post_step2", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step2", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 3:
            last_result = room_availability.process(state)
            _debug_state("post_step3", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step3", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 4:
            last_result = process_offer(state)
            _debug_state("post_step4", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step4", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 5:
            last_result = process_negotiation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step5", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 6:
            last_result = process_transition(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step6", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 7:
            last_result = process_confirmation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step7", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        break

    _debug_state("final", state)
    return _flush_and_finalize(last_result, state, path, lock_path)


def run_samples() -> list[Any]:
    """[Trigger] Execute a deterministic sample flow for manual testing."""

    os.environ["AGENT_MODE"] = "stub"
    llm_adapter.reset_llm_adapter()
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
        payload.setdefault("stage", stage_payload(event_entry))
    elif state.thread_state:
        payload["thread_state"] = state.thread_state
    if state.draft_messages:
        payload["draft_messages"] = state.draft_messages
        if event_entry:
            _enqueue_hil_tasks(state, event_entry)
    else:
        payload.setdefault("draft_messages", [])
    if state.telemetry:
        payload["telemetry"] = state.telemetry.to_payload()
    return payload
