from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime
import logging

from backend.domain import TaskStatus, TaskType

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.common.types import GroupResult
from backend.workflows.steps import step1_intake as intake
from backend.workflows.steps import step2_date_confirmation as date_confirmation
from backend.workflows.steps import step3_room_availability as room_availability
from backend.workflows.steps.step4_offer.trigger import process as process_offer
from backend.workflows.steps.step5_negotiation import process as process_negotiation
from backend.workflows.steps.step6_transition import process as process_transition
from backend.workflows.steps.step7_confirmation.trigger import process as process_confirmation
from backend.workflows.io import database as db_io
from backend.workflows.io.database import update_event_metadata
from backend.workflows.io import tasks as task_io
from backend.workflows.io.integration.config import is_hil_all_replies_enabled
from backend.workflows.llm import adapter as llm_adapter
from backend.workflows.planner import maybe_run_smart_shortcuts
from backend.workflows.nlu import (
    detect_general_room_query,
    empty_general_qna_detection,
    quick_general_qna_scan,
)
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.utils.profiler import profile_step
from backend.workflow.state import stage_payload, WorkflowStep, write_stage
from backend.debug.lifecycle import close_if_ended
from backend.debug.settings import is_trace_enabled
from backend.debug.trace import set_hil_open
from backend.workflow.guards import evaluate as evaluate_guards
from backend.debug.state_store import STATE_STORE

# Import HIL task APIs from runtime module (W2 extraction)
from backend.workflows.runtime.hil_tasks import (
    approve_task_and_send,
    reject_task_and_send,
    cleanup_tasks,
    list_pending_tasks,
)

logger = logging.getLogger(__name__)
WF_DEBUG = os.getenv("WF_DEBUG_STATE") == "1"

# ============================================================================
# PUBLIC API SURFACE (W-PUBLIC)
# ============================================================================
# Only these symbols are part of the stable public interface. External code
# (API routes, agents, tests) should import ONLY from this list.
#
# Constants:
#   DB_PATH                - Default database path
#
# Database operations:
#   load_db                - Load database (use with `with FileLock(...)`)
#   save_db                - Save database (use with `with FileLock(...)`)
#   get_default_db         - Get default database dict (re-export from db_io)
#
# Core workflow:
#   process_msg            - Process incoming message through workflow
#
# HIL task management:
#   list_pending_tasks     - List pending HIL tasks (re-export from task_io)
#   approve_task_and_send  - Approve HIL task and send response
#   reject_task_and_send   - Reject HIL task and send response
#   cleanup_tasks          - Clean up stale/orphaned tasks
#
# CLI utilities:
#   run_samples            - Run sample conversations (CLI only)
#   task_cli_loop          - Interactive task management (CLI only)
# ============================================================================

__all__ = [
    # Constants
    "DB_PATH",
    # Database operations
    "load_db",
    "save_db",
    "get_default_db",
    # Core workflow
    "process_msg",
    # HIL task management
    "list_pending_tasks",
    "approve_task_and_send",
    "reject_task_and_send",
    "cleanup_tasks",
    # CLI utilities
    "run_samples",
    "task_cli_loop",
]

_ENTITY_LABELS = {
    "client": "Client",
    "assistant": "Agent",
    "agent": "Agent",
    "trigger": "Trigger",
    "system": "System",
    "qa": "Q&A",
    "q&a": "Q&A",
}


def _debug_state(stage: str, state: WorkflowState, extra: Optional[Dict[str, Any]] = None) -> None:
    debug_trace_enabled = is_trace_enabled()
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
    general_flag = state.extras.get("general_qna_detected")
    if general_flag is not None:
        info["general_qna"] = bool(general_flag)
    if extra and "entity" in extra:
        entity_raw = extra["entity"]
        if isinstance(entity_raw, str):
            info.setdefault("entity", _ENTITY_LABELS.get(entity_raw.lower(), entity_raw))
        else:
            info.setdefault("entity", entity_raw)
    elif stage == "init":
        info.setdefault("entity", "Client")
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
             "locked_room_status": event_entry.get("selected_status") or (event_entry.get("room_pending_decision") or {}).get("selected_status"),
            "wish_products": event_entry.get("wish_products"),
            "thread_state": state.thread_state,
            "caller_step": event_entry.get("caller_step"),
            "offer_status": event_entry.get("offer_status"),
            "event_data": event_entry.get("event_data"),
            "billing_details": event_entry.get("billing_details"),
        }
    )
    subloop = state.extras.pop("subloop", None)
    if subloop:
        snapshot["subloop"] = subloop
    from backend.debug.hooks import trace_state, set_subloop, clear_subloop  # pylint: disable=import-outside-toplevel
    from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

    pending_hil = (event_entry or {}).get("pending_hil_requests") or []
    snapshot["hil_open"] = bool(pending_hil)
    if subloop:
        set_subloop(thread_id, subloop)
    trace_state(thread_id, _snapshot_step_name(event_entry), snapshot)
    if subloop:
        clear_subloop(thread_id)
    existing_state = STATE_STORE.get(thread_id)
    merged_state = dict(existing_state)
    merged_state.update(snapshot)
    if "flags" in existing_state:
        merged_state.setdefault("flags", existing_state.get("flags", {}))
    STATE_STORE.update(thread_id, merged_state)
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
# list_pending_tasks is now imported from backend.workflows.runtime.hil_tasks
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


def _ensure_general_qna_classification(state: WorkflowState, message_text: str) -> Dict[str, Any]:
    """Ensure the general Q&A classification is available on the workflow state."""

    scan = state.extras.get("general_qna_scan")
    if not scan:
        scan = quick_general_qna_scan(message_text)
        state.extras["general_qna_scan"] = scan

    ensure_qna_extraction(state, message_text, scan)
    extraction_payload = state.extras.get("qna_extraction")
    if extraction_payload:
        event_entry = state.event_entry or {}
        cache = event_entry.setdefault("qna_cache", {})
        cache["extraction"] = extraction_payload
        cache["meta"] = state.extras.get("qna_extraction_meta")
        cache["last_message_text"] = message_text
        state.event_entry = event_entry
        state.extras["persist"] = True

    classification = state.extras.get("_general_qna_classification")
    if classification:
        state.extras["general_qna_detected"] = bool(classification.get("is_general"))
        return classification

    needs_detailed = bool(
        scan.get("likely_general")
        or (scan.get("heuristics") or {}).get("borderline")
    )
    if needs_detailed:
        classification = detect_general_room_query(message_text, state)
    else:
        classification = empty_general_qna_detection()
        classification["heuristics"] = scan.get("heuristics", classification["heuristics"])
        classification["parsed"] = scan.get("parsed", classification["parsed"])
        classification["constraints"] = {
            "vague_month": classification["parsed"].get("vague_month"),
            "weekday": classification["parsed"].get("weekday"),
            "time_of_day": classification["parsed"].get("time_of_day"),
            "pax": classification["parsed"].get("pax"),
        }
        classification["llm_called"] = False
        classification["cached"] = False

    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    return classification


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
    thread_id = _thread_identifier(state)

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
        if step_num not in {2, 3, 4, 5}:
            continue
        # Drop older pending requests for the same step to avoid duplicate reviews.
        stale_requests = [entry for entry in pending_records if entry.get("step") == step_num]
        if stale_requests:
            for stale in stale_requests:
                task_id = stale.get("task_id")
                if task_id:
                    try:
                        update_task_status(state.db, task_id, TaskStatus.DONE)
                    except Exception:
                        pass
                try:
                    pending_records.remove(stale)
                except ValueError:
                    pass
            state.extras["persist"] = True
        if step_num == 5:
            earlier_steps = [entry for entry in pending_records if (entry.get("step") or 0) < 5]
            for stale in earlier_steps:
                task_id = stale.get("task_id")
                if task_id:
                    try:
                        update_task_status(state.db, task_id, TaskStatus.DONE)
                    except Exception:
                        pass
                try:
                    pending_records.remove(stale)
                except ValueError:
                    pass
            if earlier_steps:
                state.extras["persist"] = True
        if step_num == 4:
            task_type = TaskType.OFFER_MESSAGE
        elif step_num == 5:
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
            "thread_id": thread_id,
        }
        hil_reason = draft.get("hil_reason")
        if hil_reason:
            task_payload["reason"] = hil_reason

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
                "thread_id": thread_id,
            }
        )
        seen_signatures.add(signature)
        state.extras["persist"] = True

    set_hil_open(thread_id, bool(pending_records))


def _hil_action_type_for_step(step_id: Optional[int]) -> Optional[str]:
    if step_id == 2:
        return "ask_for_date_enqueued"
    if step_id == 3:
        return "room_options_enqueued"
    if step_id == 4:
        return "offer_enqueued"
    if step_id == 5:
        return "negotiation_enqueued"
    return None


# _compose_hil_decision_reply, approve_task_and_send, reject_task_and_send, cleanup_tasks
# are now imported from backend.workflows.runtime.hil_tasks


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
    STATE_STORE.clear(state.thread_id)
    combined_text = "\n".join(
        part for part in ((message.subject or "").strip(), (message.body or "").strip()) if part
    )
    state.extras["general_qna_scan"] = quick_general_qna_scan(combined_text)
    # [DEV TEST MODE] Pass through skip_dev_choice flag for testing convenience
    if msg.get("skip_dev_choice"):
        state.extras["skip_dev_choice"] = True
    classification = _ensure_general_qna_classification(state, combined_text)
    _debug_state("init", state, extra={"entity": "client"})
    last_result = intake.process(state)
    _debug_state("post_intake", state, extra={"intent": state.intent.value if state.intent else None})

    # [DUPLICATE MESSAGE DETECTION] Check if client sent the exact same message twice in a row
    # This prevents confusing duplicate responses when client accidentally resends
    if state.event_entry:
        last_client_msg = state.event_entry.get("last_client_message", "")
        normalized_current = combined_text.strip().lower()
        normalized_last = (last_client_msg or "").strip().lower()

        # Only check for duplicates if we have a previous message and messages are identical
        if normalized_last and normalized_current == normalized_last:
            # Don't flag as duplicate if this is a detour return or offer update flow
            is_detour = state.event_entry.get("caller_step") is not None
            current_step = state.event_entry.get("current_step", 1)
            # Don't flag as duplicate during billing flow - client may resend billing info
            in_billing_flow = (
                state.event_entry.get("offer_accepted")
                and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
            )

            if not is_detour and not in_billing_flow and current_step >= 2:
                # Return friendly "same message" response instead of processing
                duplicate_response = GroupResult(
                    action="duplicate_message",
                    halt=True,
                    payload={
                        "draft": {
                            "body_markdown": (
                                "I notice this is the same message as before. "
                                "Is there something specific you'd like to add or clarify? "
                                "I'm happy to help with any questions or changes."
                            ),
                            "hil_required": False,
                        },
                    },
                )
                from backend.debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel
                trace_marker(
                    state.thread_id,
                    "DUPLICATE_MESSAGE_DETECTED",
                    detail="Client sent identical message twice in a row",
                    owner_step=f"Step{current_step}",
                )
                return _flush_and_finalize(duplicate_response, state, path, lock_path)

        # Store current message for next comparison (only if not a duplicate)
        state.event_entry["last_client_message"] = combined_text.strip()
        state.extras["persist"] = True

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

    # [BILLING FLOW CORRECTION] Force step=5 when in billing flow
    # This handles cases where step was incorrectly set before billing flow started
    if state.event_entry:
        in_billing_flow = (
            state.event_entry.get("offer_accepted")
            and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        )
        stored_step = state.event_entry.get("current_step")
        if in_billing_flow and stored_step != 5:
            print(f"[WF][BILLING_FIX] Correcting step from {stored_step} to 5 for billing flow")
            state.event_entry["current_step"] = 5
            state.extras["persist"] = True
        elif in_billing_flow:
            print(f"[WF][BILLING_FLOW] Already at step 5, proceeding with billing flow")

    print(f"[WF][PRE_ROUTE] About to enter routing loop, event_entry exists={state.event_entry is not None}")
    if state.event_entry:
        print(f"[WF][PRE_ROUTE] current_step={state.event_entry.get('current_step')}, offer_accepted={state.event_entry.get('offer_accepted')}")

    for iteration in range(6):
        event_entry = state.event_entry
        if not event_entry:
            print(f"[WF][ROUTE][{iteration}] No event_entry, breaking")
            break
        step = event_entry.get("current_step")
        print(f"[WF][ROUTE][{iteration}] current_step={step}")
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
        print(f"[WF][ROUTE] No handler for step {step}, breaking")
        break

    _debug_state("final", state)
    print(f"[WF][FINAL] Returning with action={last_result.action if last_result else 'None'}, halt={last_result.halt if last_result else 'N/A'}")
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
            status_map = {"2": TaskStatus.APPROVED, "3": TaskStatus.REJECTED, "4": TaskStatus.DONE}
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
    if state.user_info:
        payload.setdefault("user_info", dict(state.user_info))
    if state.intent_detail:
        payload["intent_detail"] = state.intent_detail
    event_entry = state.event_entry
    if event_entry:
        payload.setdefault("event_id", event_entry.get("event_id"))
        payload["current_step"] = event_entry.get("current_step")
        payload["caller_step"] = event_entry.get("caller_step")
        payload["thread_state"] = event_entry.get("thread_state")
        payload.setdefault("stage", stage_payload(event_entry))
    elif state.thread_state:
        payload["thread_state"] = state.thread_state
    res_meta = payload.setdefault("res", {})
    actions_out = payload.setdefault("actions", [])
    requires_approval_flags: List[bool] = []
    # Check FIRST if HIL approval is required for ALL LLM replies (toggle)
    # This must be checked BEFORE _enqueue_hil_tasks to avoid creating duplicate tasks
    hil_all_replies_on = is_hil_all_replies_enabled()
    if state.draft_messages:
        payload["draft_messages"] = state.draft_messages
        # ALWAYS create step-specific HIL tasks (offer confirmation, special requests, etc.)
        # These are the original workflow HIL tasks - they work regardless of the AI reply toggle
        if event_entry:
            _enqueue_hil_tasks(state, event_entry)
        requires_approval_flags = [draft.get("requires_approval", True) for draft in state.draft_messages]
    else:
        payload.setdefault("draft_messages", [])

    if state.draft_messages:
        latest_draft = next(
            (draft for draft in reversed(state.draft_messages) if draft.get("requires_approval")),
            state.draft_messages[-1],
        )
        draft_body = latest_draft.get("body_markdown") or latest_draft.get("body") or ""
        draft_headers = list(latest_draft.get("headers") or [])

        # When HIL toggle is ON: DON'T include message in response (it goes to approval queue only)
        # When HIL toggle is OFF: Include message in response for immediate display
        if hil_all_replies_on:
            # Message pending approval - don't send to client chat yet
            res_meta["assistant_draft"] = None
            res_meta["assistant_draft_text"] = ""
            res_meta["pending_hil_approval"] = True  # Flag for frontend
        else:
            res_meta["assistant_draft"] = {"headers": draft_headers, "body": draft_body}
            res_meta["assistant_draft_text"] = draft_body
    else:
        res_meta.setdefault("assistant_draft", None)
        res_meta.setdefault("assistant_draft_text", "")
    general_qa_payload = state.turn_notes.get("general_qa")
    if general_qa_payload:
        res_meta["general_qa"] = general_qa_payload
    trace_payload = payload.setdefault("trace", {})
    trace_payload["subloops"] = list(state.subloops_trace)
    if state.draft_messages:
        # Check if HIL approval is required for ALL LLM replies (toggle)
        if hil_all_replies_on:
            # When toggle ON: ALL AI-generated replies go to separate "AI Reply Approval" queue
            # This allows managers to review/edit EVERY outbound message before it reaches clients
            latest_draft = state.draft_messages[-1]
            draft_body = latest_draft.get("body_markdown") or latest_draft.get("body") or ""
            draft_step = latest_draft.get("step", state.current_step)
            thread_id = _thread_identifier(state)

            # Check if there's already a PENDING ai_reply_approval task for this thread
            # This prevents duplicate tasks from being created
            existing_pending_task = None
            for task in state.db.get("tasks", []):
                if (task.get("type") == TaskType.AI_REPLY_APPROVAL.value
                    and task.get("status") == TaskStatus.PENDING.value
                    and task.get("payload", {}).get("thread_id") == thread_id):
                    existing_pending_task = task
                    break

            if existing_pending_task:
                # Update existing task with new draft instead of creating duplicate
                existing_pending_task["payload"]["draft_body"] = draft_body
                existing_pending_task["payload"]["step_id"] = draft_step
                task_id = existing_pending_task.get("task_id")
            else:
                # Create task for AI reply approval
                client_id = state.client_id or (state.message.from_email or "unknown@example.com").lower()
                task_payload = {
                    "step_id": draft_step,
                    "draft_body": draft_body,
                    "thread_id": thread_id,
                    "event_id": event_entry.get("event_id") if event_entry else None,
                    "editable": True,  # Manager can edit before approving
                    "event_summary": {
                        "client_name": event_entry.get("client_name", "Client") if event_entry else "Client",
                        "email": event_entry.get("client_id") if event_entry else None,
                        "company": (event_entry.get("event_data") or {}).get("Organization") if event_entry else None,
                        "chosen_date": event_entry.get("chosen_date") if event_entry else None,
                        "locked_room": event_entry.get("locked_room") if event_entry else None,
                    },
                }
                task_id = enqueue_task(
                    state.db,
                    TaskType.AI_REPLY_APPROVAL,
                    client_id,
                    event_entry.get("event_id") if event_entry else None,
                    task_payload,
                )

            hil_ai_payload = {
                "task_id": task_id,
                "event_id": event_entry.get("event_id") if event_entry else None,
                "client_name": event_entry.get("client_name", "Client") if event_entry else "Client",
                "client_email": event_entry.get("client_id") if event_entry else None,
                "draft_message": draft_body,
                "workflow_step": draft_step,
                "editable": True,  # Manager can edit before approving
            }
            actions_out.append({"type": "hil_ai_reply_approval", "payload": hil_ai_payload})
        elif any(not flag for flag in requires_approval_flags):
            # Toggle OFF + no approval needed: send directly (current behavior)
            actions_out.append({"type": "send_reply"})
        elif event_entry:
            # Toggle OFF + approval needed: route to step-specific HIL (current behavior)
            hil_type = _hil_action_type_for_step(state.draft_messages[-1].get("step"))
            if hil_type:
                hil_payload = {
                    "event_id": event_entry.get("event_id"),
                }
                if event_entry.get("candidate_dates"):
                    hil_payload["suggested_dates"] = list(event_entry.get("candidate_dates"))
                actions_out.append({"type": hil_type, "payload": hil_payload})
    if state.telemetry:
        payload["telemetry"] = state.telemetry.to_payload()
    return payload
