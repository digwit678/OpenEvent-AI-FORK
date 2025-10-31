from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import os
import re
import atexit
import logging
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple
from backend.domain import ConversationState, EventInformation, TaskType
from backend.conversation_manager import (
    create_summary,
    active_conversations,
)
from pathlib import Path
from backend.adapters.calendar_adapter import get_calendar_adapter
from backend.adapters.client_gui_adapter import ClientGUIAdapter
from backend.workflows.groups.room_availability import run_availability_workflow
from backend.utils import json_io
from backend.workflows.io.database import ensure_event_defaults

os.environ.setdefault("AGENT_MODE", os.environ.get("AGENT_MODE_DEFAULT", "openai"))

from backend.workflow_email import (
    process_msg as wf_process_msg,
    DB_PATH as WF_DB_PATH,
    load_db as wf_load_db,
    save_db as wf_save_db,
    list_pending_tasks as wf_list_pending_tasks,
    update_task_status as wf_update_task_status,
    enqueue_task as wf_enqueue_task,
)
from backend.api.agent_router import router as agent_router
from backend.llm.verbalizer_agent import verbalize_gui_reply, _split_required_sections
from backend.workflows.advance import advance_after_review
from backend.llm.intent_classifier import classify_intent as classify_turn_intent
from backend.workflows.io.database import find_event_idx_by_id, last_event_for_email
from backend.workflows.qna.router import route_general_qna
from backend.workflows.qna.templates import build_qna_info_and_next_step
from scripts.ports import is_port_in_use, first_free_port, kill_port_process

app = FastAPI(title="AI Event Manager")
app.include_router(agent_router)

GUI_ADAPTER = ClientGUIAdapter()
DEV_LOGGER = logging.getLogger("openevent.dev")
FRONTEND_PROCESS: Optional[subprocess.Popen] = None
FRONTEND_CANDIDATE_PORTS = [3000, 3001, 3002]
FRONTEND_PIDFILE = Path(__file__).resolve().parents[1] / ".dev" / "frontend.pid"

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CENTRALIZED EVENTS DATABASE
EVENTS_FILE = "events_database.json"

def load_events_database():
    """Load all events from the database file"""
    if Path(EVENTS_FILE).exists():
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            return json_io.load(f)
    return {"events": []}

def save_events_database(database):
    """Save all events to the database file"""
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json_io.dump(database, f, indent=2, ensure_ascii=False)

# REQUEST/RESPONSE MODELS
class StartConversationRequest(BaseModel):
    email_body: str
    client_email: str

class SendMessageRequest(BaseModel):
    session_id: str
    message: str


class TaskDecisionRequest(BaseModel):
    notes: Optional[str] = None


class ConfirmDateRequest(BaseModel):
    date: Optional[str] = None

class ConversationResponse(BaseModel):
    session_id: str
    workflow_type: str
    response: str
    is_complete: bool
    event_info: dict

# ENDPOINTS

DATE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
CONFIRM_PHRASES = {
    "yes",
    "yes.",
    "yes!",
    "yes please",
    "yes please do",
    "yes it is",
    "yes that's fine",
    "yes thats fine",
    "yes confirm",
    "yes confirmed",
    "confirmed",
    "confirm",
    "sounds good",
    "that works",
    "perfect",
    "perfect thanks",
    "okay",
    "ok",
    "ok thanks",
    "great",
    "great thanks",
}


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _to_iso_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    text = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _trigger_room_availability(event_id: Optional[str], chosen_date: str) -> None:
    if not event_id:
        print("[WF] Skipping room availability trigger - missing event_id.")
        return
    try:
        db = wf_load_db()
    except Exception as exc:
        print(f"[WF][ERROR] Failed to load workflow DB: {exc}")
        return
    events = db.get("events", [])
    event_entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not event_entry:
        print(f"[WF][WARN] Event {event_id} not found in DB; cannot trigger availability workflow.")
        return

    event_data = event_entry.setdefault("event_data", {})
    event_data["Status"] = "Date Confirmed"
    iso_date = _to_iso_date(chosen_date) or _to_iso_date(event_data.get("Event Date"))
    if iso_date:
        event_data["Event Date"] = iso_date

    logs = event_entry.setdefault("logs", [])
    if iso_date:
        for log in reversed(logs):
            if log.get("action") == "room_availability_assessed":
                details = log.get("details") or {}
                requested_days = details.get("requested_days") or []
                first_day = requested_days[0] if requested_days else None
                if first_day == iso_date:
                    wf_save_db(db)
                    print(f"[WF] Availability already assessed for {iso_date}; skipping rerun.")
                    return

    logs.append(
        {
            "ts": _now_iso(),
            "actor": "Platform",
            "action": "room_availability_triggered_after_date_confirm",
            "details": {"event_id": event_id},
        }
    )

    wf_save_db(db)

    try:
        run_availability_workflow(event_id, get_calendar_adapter(), GUI_ADAPTER)
    except Exception as exc:
        print(f"[WF][ERROR] Availability workflow failed: {exc}")


def _persist_confirmed_date(conversation_state: ConversationState, chosen_date: str) -> str:
    conversation_state.event_info.event_date = chosen_date
    conversation_state.event_info.status = "Date Confirmed"

    os.environ.setdefault("AGENT_MODE", "openai")
    synthetic_msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Client (GUI)",
        "from_email": conversation_state.event_info.email,
        "subject": f"Confirmed event date {chosen_date}",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": f"The client confirms the preferred event date is {chosen_date}.",
    }
    wf_res = {}
    try:
        wf_res = wf_process_msg(synthetic_msg)
        print(
            "[WF] confirm_date action="
            f"{wf_res.get('action')} event_id={wf_res.get('event_id')} intent={wf_res.get('intent')}"
        )
    except Exception as exc:
        print(f"[WF][ERROR] Failed to persist confirmed date: {exc}")

    event_id = wf_res.get("event_id") or conversation_state.event_id
    conversation_state.event_id = event_id

    try:
        _trigger_room_availability(event_id, chosen_date)
    except Exception as exc:
        print(f"[WF][ERROR] trigger availability failed: {exc}")

    return "Date confirmed. I'm checking room availability now and will share options in a moment."


def _wf_compose_reply(wf_res: Dict[str, Any]) -> str:
    drafts = wf_res.get("draft_messages") or []
    bodies = [str(d.get("body", "")) for d in drafts if d.get("body")]
    if bodies:
        return "\n\n".join(bodies)
    if wf_res.get("summary"):
        return str(wf_res.get("summary"))
    if wf_res.get("reason"):
        return str(wf_res.get("reason"))
    return "\u200b"


def _dev_prepare_env() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    os.environ.setdefault("AGENT_MODE", "openai")
    os.environ.setdefault("VERBALIZER_TONE", "empathetic")
    if not os.getenv("OPENAI_API_KEY"):
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-a",
                    os.getenv("USER", ""),
                    "-s",
                    "openevent-api-test-key",
                    "-w",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                os.environ["OPENAI_API_KEY"] = result.stdout.strip()
        except FileNotFoundError:
            DEV_LOGGER.debug("Keychain lookup unavailable; skipping")


def _dev_free_port(port: int) -> None:
    if not is_port_in_use(port):
        return
    DEV_LOGGER.info("dev: freeing port %s", port)
    kill_port_process(port)
    deadline = time.time() + 5
    while is_port_in_use(port) and time.time() < deadline:
        time.sleep(0.1)
    if is_port_in_use(port):
        DEV_LOGGER.warning("dev: port %s still in use after kill attempt", port)


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pidfile() -> Optional[int]:
    if FRONTEND_PIDFILE.exists():
        try:
            pid = int(FRONTEND_PIDFILE.read_text().strip())
            if _pid_running(pid):
                return pid
        except Exception:
            pass
        try:
            FRONTEND_PIDFILE.unlink()
        except OSError:
            pass
    return None


def _write_pidfile(pid: int) -> None:
    FRONTEND_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_PIDFILE.write_text(str(pid))


def _ensure_frontend() -> Tuple[Optional[int], bool]:
    existing_pid = _read_pidfile()
    existing_port = next((p for p in FRONTEND_CANDIDATE_PORTS if is_port_in_use(p)), None)
    if existing_port and not existing_pid:
        DEV_LOGGER.info(
            "dev: frontend detected on port %s", existing_port,
            extra={"frontend_port": existing_port, "autostart": False},
        )
        return existing_port, False

    if existing_pid and existing_port:
        DEV_LOGGER.info(
            "dev: frontend already running",
            extra={"frontend_port": existing_port, "autostart": False},
        )
        return existing_port, False

    frontend_dir = Path(__file__).resolve().parents[1] / "atelier-ai-frontend"
    if not frontend_dir.exists():
        DEV_LOGGER.warning("dev: frontend directory missing; skipping auto-start")
        return None, False

    port = first_free_port(FRONTEND_CANDIDATE_PORTS)
    if port is None:
        DEV_LOGGER.warning("dev: no free frontend port available")
        return None, False

    env = os.environ.copy()
    env.setdefault("NEXT_PUBLIC_BACKEND_BASE", "http://localhost:8000")
    env.setdefault("NEXT_PUBLIC_VERBALIZER_TONE", os.getenv("VERBALIZER_TONE", "empathetic"))
    env["PORT"] = str(port)
    command = ["npm", "run", "dev"]
    process = subprocess.Popen(command, cwd=str(frontend_dir), env=env)

    global FRONTEND_PROCESS
    FRONTEND_PROCESS = process
    _write_pidfile(process.pid)
    DEV_LOGGER.info(
        "dev: frontend started",
        extra={"frontend_port": port, "autostart": True},
    )
    atexit.register(_shutdown_frontend)
    return port, True


def _shutdown_frontend() -> None:
    global FRONTEND_PROCESS
    if FRONTEND_PROCESS and FRONTEND_PROCESS.poll() is None:
        try:
            FRONTEND_PROCESS.terminate()
            FRONTEND_PROCESS.wait(timeout=5)
        except Exception:
            pass
        FRONTEND_PROCESS = None
    if FRONTEND_PIDFILE.exists():
        try:
            FRONTEND_PIDFILE.unlink()
        except OSError:
            pass


def _name_from_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    local = (email.split("@", 1)[0] or "").strip()
    if not local:
        return None
    # Split on common separators and take first token
    for sep in (".", "_", "-"):
        if sep in local:
            local = local.split(sep, 1)[0]
            break
    if not local:
        return None
    return local.capitalize()


def _expect_resume(conversation_state: ConversationState) -> bool:
    for entry in reversed(conversation_state.conversation_history):
        if entry.get("role") != "assistant":
            continue
        content = str(entry.get("content") or "")
        if "Proceed with" in content:
            return True
        break
    return False


def _locate_event_entry(db: Dict[str, Any], event_id: Optional[str], client_email: Optional[str]) -> Optional[Dict[str, Any]]:
    entry: Optional[Dict[str, Any]] = None
    if event_id:
        idx = find_event_idx_by_id(db, event_id)
        if idx is not None:
            entry = db["events"][idx]
            ensure_event_defaults(entry)
    if not entry and client_email:
        entry = last_event_for_email(db, client_email.lower())
        if entry:
            ensure_event_defaults(entry)
    return entry


def _current_step_from_event(event_entry: Optional[Dict[str, Any]]) -> int:
    if event_entry and isinstance(event_entry.get("current_step"), int):
        return int(event_entry["current_step"])
    return 2


def _missing_fields_for_step(step: int, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    missing: List[str] = []
    if not event_entry:
        if step == 2:
            missing.extend(["date", "time"])
        return missing
    if step == 2:
        window = event_entry.get("requested_window") or {}
        if not window.get("date_iso"):
            missing.append("date")
        if not (window.get("start_time") and window.get("end_time")):
            missing.append("time")
    elif step == 3:
        if not event_entry.get("locked_room_id"):
            missing.append("room")
        requirements = (event_entry.get("requirements") or {}) if isinstance(event_entry.get("requirements"), dict) else {}
        if not requirements.get("number_of_participants"):
            missing.append("attendees")
        if not requirements.get("seating_layout"):
            missing.append("layout")
    elif step == 4:
        products = event_entry.get("products") or []
        selected = event_entry.get("selected_products") or []
        if not products and not selected:
            missing.append("products")
        event_data = event_entry.get("event_data") or {}
        catering_pref = str(event_data.get("Catering Preference") or "").strip()
        if not catering_pref or catering_pref.lower() == "not specified":
            missing.append("catering")
    return missing


_STEP_INTENTS = {
    "date_confirmation",
    "room_availability",
    "offer_review",
    "site_visit",
    "follow_up",
}


def _load_workflow_db() -> Dict[str, Any]:
    try:
        return wf_load_db()
    except Exception:
        return {"events": [], "clients": {}, "tasks": []}


def _should_run_workflow(classification: Dict[str, Any], *, force: bool = False) -> bool:
    if classification.get("wants_resume"):
        return True
    primary = classification.get("primary")
    if primary == "message_manager":
        return False
    if force:
        return True
    return primary in _STEP_INTENTS


def _prepare_qna_body(body: str, include_resume_prompt: bool) -> Optional[str]:
    """Normalize Q&A payload text and optionally remove the NEXT STEP affordance."""

    text = (body or "").strip()
    if not text:
        return None
    if include_resume_prompt:
        return text

    split_marker = "\n\nNEXT STEP:"
    if split_marker in text:
        text = text.split(split_marker, 1)[0].rstrip()
    else:
        inline_marker = "\nNEXT STEP:"
        if inline_marker in text:
            text = text.split(inline_marker, 1)[0].rstrip()
    return text or None


def _compose_turn_drafts(
    step_drafts: List[Dict[str, Any]],
    qna_payload: Dict[str, Any],
    wf_res: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    drafts: List[Dict[str, Any]] = []
    sections: List[str] = []
    include_resume_prompt = not bool(step_drafts)

    for block in qna_payload.get("pre_step") or []:
        prepared_body = _prepare_qna_body(str(block.get("body") or ""), include_resume_prompt)
        if not prepared_body:
            continue
        block_payload = dict(block)
        block_payload["body"] = prepared_body
        sections.append(prepared_body)
        drafts.append(block_payload)

    for draft in step_drafts or []:
        body = str(draft.get("body") or "").strip()
        if body:
            sections.append(body)
        drafts.append(draft)

    for block in qna_payload.get("post_step") or []:
        prepared_body = _prepare_qna_body(str(block.get("body") or ""), include_resume_prompt)
        if not prepared_body:
            continue
        block_payload = dict(block)
        block_payload["body"] = prepared_body
        sections.append(prepared_body)
        drafts.append(block_payload)

    fallback_text = "\n\n".join(section for section in sections if section)
    if not fallback_text and wf_res:
        fallback_text = _wf_compose_reply(wf_res)
    if not fallback_text and step_drafts:
        fallback_text = _wf_compose_reply({"draft_messages": step_drafts})
    return drafts, fallback_text or "\u200b"


def _execute_turn(
    conversation_state: ConversationState,
    msg: Dict[str, Any],
    classification: Dict[str, Any],
    *,
    wf_res: Optional[Dict[str, Any]] = None,
    db_before: Optional[Dict[str, Any]] = None,
    event_entry_before: Optional[Dict[str, Any]] = None,
) -> Tuple[str, int, Optional[str]]:
    db_snapshot = db_before or _load_workflow_db()
    entry_before = event_entry_before or _locate_event_entry(
        db_snapshot,
        conversation_state.event_id,
        conversation_state.event_info.email,
    )

    force_run = wf_res is None and conversation_state.event_id is None and classification.get("primary") != "message_manager"
    run_workflow = _should_run_workflow(classification, force=force_run) and wf_res is None

    step_drafts: List[Dict[str, Any]] = []
    db_after = db_snapshot
    event_entry_after = entry_before
    result = wf_res

    if run_workflow:
        result = wf_process_msg(msg)
        event_id = result.get("event_id")
        if event_id:
            conversation_state.event_id = event_id
        db_after = _load_workflow_db()
        event_entry_after = _locate_event_entry(db_after, conversation_state.event_id, conversation_state.event_info.email)
        step_drafts = result.get("draft_messages") or []
    elif result is not None:
        event_id = result.get("event_id")
        if event_id:
            conversation_state.event_id = event_id
        db_after = _load_workflow_db()
        event_entry_after = _locate_event_entry(db_after, conversation_state.event_id, conversation_state.event_info.email)
        step_drafts = result.get("draft_messages") or []

    primary_intent = classification.get("primary")
    if primary_intent not in _STEP_INTENTS and primary_intent != "resume" and not classification.get("wants_resume"):
        step_drafts = []

    qna_payload = route_general_qna(msg, entry_before, event_entry_after, db_after, classification)
    drafts, fallback_text = _compose_turn_drafts(step_drafts, qna_payload, result)
    assistant_reply = verbalize_gui_reply(drafts, fallback_text, client_email=conversation_state.event_info.email)

    step_value = _current_step_from_event(event_entry_after)
    status_value = (event_entry_after or {}).get("status")
    return assistant_reply, step_value, status_value


def _verbalize_from_payload(payload: Dict[str, Any], client_email: Optional[str]) -> str:
    drafts = payload.get("draft_messages") or []
    fallback = ""
    if drafts:
        fallback = str(drafts[0].get("body") or "")
    elif payload.get("assistant_text"):
        fallback = str(payload["assistant_text"])
    return verbalize_gui_reply(drafts, fallback, client_email=client_email)


def _handle_message_manager(
    msg: Dict[str, Any],
    conversation_state: ConversationState,
    event_entry: Optional[Dict[str, Any]],
    db: Dict[str, Any],
) -> Dict[str, Any]:
    current_step = _current_step_from_event(event_entry)
    missing = _missing_fields_for_step(current_step, event_entry)
    info_lines = ["I've shared your note with our venue manager and will follow up soon."]
    body = build_qna_info_and_next_step(info_lines, current_step, missing)
    draft = {
        "body": body,
        "step": current_step,
        "topic": "manager_message_forwarded",
        "requires_approval": False,
    }
    client_id = (conversation_state.event_info.email or "").lower()
    event_id = (event_entry or {}).get("event_id") or conversation_state.event_id
    payload = {
        "note": msg.get("body"),
        "from_name": msg.get("from_name"),
        "msg_id": msg.get("msg_id"),
    }
    try:
        wf_enqueue_task(db, TaskType.MESSAGE_MANAGER, client_id, event_id, payload)
        wf_save_db(db)
    except Exception as exc:
        logging.getLogger("openevent.dev").warning("Failed to enqueue manager message: %s", exc)
    return {
        "draft_messages": [draft],
        "step": current_step,
        "status": (event_entry or {}).get("status"),
    }

@app.post("/api/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """Condition (purple): kick off workflow and branch on manual or ask-for-date pauses before legacy flow."""
    os.environ.setdefault("AGENT_MODE", "openai")
    subject_line = (request.email_body.splitlines()[0][:80] if request.email_body else "No subject")
    msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Not specified",
        "from_email": request.client_email,
        "subject": subject_line,
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.email_body or "",
    }
    db_before = _load_workflow_db()
    event_entry_before = _locate_event_entry(db_before, None, request.client_email)
    current_step_before = _current_step_from_event(event_entry_before)
    classification = classify_turn_intent(request.email_body or "", current_step=current_step_before)
    wf_res = None
    wf_action = None
    try:
        wf_res = wf_process_msg(msg)
        wf_action = wf_res.get("action")
        print(f"[WF] start action={wf_action} client={request.client_email} event_id={wf_res.get('event_id')} task_id={wf_res.get('task_id')}")
    except Exception as e:
        print(f"[WF][ERROR] {e}")
    if wf_action == "manual_review_enqueued":
        event_id = wf_res.get("event_id")
        # Create a session even when manual review is enqueued so the client can continue messaging.
        session_id = str(uuid.uuid4())
        event_info = EventInformation(
            date_email_received=datetime.now().strftime("%d.%m.%Y"),
            email=request.client_email,
        )
        assistant_reply = "Thanks for reaching out — I'll review the details and follow up shortly."
        conversation_state = ConversationState(
            session_id=session_id,
            event_info=event_info,
            conversation_history=[
                {"role": "user", "content": request.email_body or ""},
                {"role": "assistant", "content": assistant_reply},
            ],
            workflow_type="new_event",
        )
        if event_id:
            conversation_state.event_id = event_id
        active_conversations[session_id] = conversation_state
        return {
            "session_id": session_id,
            "workflow_type": "new_event",
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.model_dump(),
            "event_id": event_id,
        }
    if wf_action == "ask_for_date_enqueued":
        session_id = str(uuid.uuid4())
        event_info = EventInformation(
            date_email_received=datetime.now().strftime("%d.%m.%Y"),
            email=request.client_email,
        )
        user_info = (wf_res or {}).get("user_info") or {}
        if user_info.get("phone"):
            event_info.phone = str(user_info["phone"])
        if user_info.get("company"):
            event_info.company = str(user_info["company"])
        if user_info.get("language"):
            event_info.language = str(user_info["language"])
        if user_info.get("participants"):
            event_info.number_of_participants = str(user_info["participants"])
        if user_info.get("room"):
            event_info.preferred_room = str(user_info["room"])
        if user_info.get("type"):
            event_info.type_of_event = str(user_info["type"])
        if user_info.get("catering"):
            event_info.catering_preference = str(user_info["catering"])
        if user_info.get("start_time"):
            event_info.start_time = str(user_info["start_time"])
        if user_info.get("end_time"):
            event_info.end_time = str(user_info["end_time"])
        suggested_dates = (wf_res or {}).get("suggested_dates") or []
        dates_text = ", ".join(suggested_dates) if suggested_dates else "No specific dates yet."
        assistant_reply = (
            f"Hello,\n\nDo you already have a date in mind? Here are a few available dates: {dates_text}"
        )
        conversation_state = ConversationState(
            session_id=session_id,
            event_info=event_info,
            conversation_history=[
                {"role": "user", "content": request.email_body or ""},
                {"role": "assistant", "content": assistant_reply},
            ],
            workflow_type="new_event",
        )
        active_conversations[session_id] = conversation_state
        print(f"[WF] start pause ask_for_date session={session_id} task={wf_res.get('task_id')}")
        return {
            "session_id": session_id,
            "workflow_type": "new_event",
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.model_dump(),
            "pending_actions": None,
        }

    # Default: create a session and reply using Workflow v3 drafts (strict Step2->3->4)
    session_id = str(uuid.uuid4())
    event_info = EventInformation(
        date_email_received=datetime.now().strftime("%d.%m.%Y"),
        email=request.client_email,
    )
    conversation_state = ConversationState(
        session_id=session_id,
        event_info=event_info,
        conversation_history=[{"role": "user", "content": request.email_body or ""}],
        workflow_type="new_event",
    )
    active_conversations[session_id] = conversation_state
    event_id = wf_res.get("event_id") if wf_res else None
    if event_id:
        conversation_state.event_id = event_id

    db_after = _load_workflow_db()
    event_entry_after = _locate_event_entry(db_after, conversation_state.event_id, request.client_email)

    if classification.get("primary") == "message_manager":
        manager_payload = _handle_message_manager(msg, conversation_state, event_entry_after, db_after)
        assistant_reply = _verbalize_from_payload(manager_payload, request.client_email)
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        response_payload = {
            "session_id": session_id,
            "workflow_type": "new_event",
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.model_dump(),
            "step": manager_payload.get("step"),
            "status": manager_payload.get("status"),
        }
        if conversation_state.event_id:
            response_payload["event_id"] = conversation_state.event_id
        return response_payload

    assistant_reply, step_value, status_value = _execute_turn(
        conversation_state,
        msg,
        classification,
        wf_res=wf_res,
        db_before=db_before,
        event_entry_before=event_entry_before,
    )
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    response_payload = {
        "session_id": session_id,
        "workflow_type": "new_event",
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump(),
        "pending_actions": None,
    }
    if conversation_state.event_id:
        response_payload["event_id"] = conversation_state.event_id
    if step_value:
        response_payload["step"] = step_value
    if status_value:
        response_payload["status"] = status_value
    return response_payload

@app.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """Condition (purple): continue chat or trigger confirm-date prompt when a valid date appears."""
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[request.session_id]

    msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Client (GUI)",
        "from_email": conversation_state.event_info.email or "unknown@example.com",
        "subject": "Client message",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.message or "",
    }
    expect_resume = _expect_resume(conversation_state)
    db_before = _load_workflow_db()
    event_entry_before = _locate_event_entry(db_before, conversation_state.event_id, conversation_state.event_info.email)
    current_step_before = _current_step_from_event(event_entry_before)
    classification = classify_turn_intent(request.message or "", current_step=current_step_before, expect_resume=expect_resume)

    conversation_state.conversation_history.append({"role": "user", "content": request.message})

    wf_res = wf_process_msg(msg)
    event_id = wf_res.get("event_id")
    if event_id:
        conversation_state.event_id = event_id

    db_after = _load_workflow_db()
    event_entry_after = _locate_event_entry(db_after, conversation_state.event_id, conversation_state.event_info.email)

    if classification.get("primary") == "message_manager":
        manager_payload = _handle_message_manager(msg, conversation_state, event_entry_after, db_after)
        assistant_reply = _verbalize_from_payload(manager_payload, conversation_state.event_info.email)
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "step": manager_payload.get("step"),
            "status": manager_payload.get("status"),
            "pending_actions": None,
        }

    assistant_reply, step_value, status_value = _execute_turn(
        conversation_state,
        msg,
        classification,
        wf_res=wf_res,
        db_before=db_before,
        event_entry_before=event_entry_before,
    )
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    response_payload = {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": None,
    }
    if step_value:
        response_payload["step"] = step_value
    if status_value:
        response_payload["status"] = status_value
    return response_payload


@app.get("/api/tasks/pending")
async def get_pending_tasks():
    """OpenEvent Action (light-blue): expose pending manual tasks for GUI approvals."""
    try:
        db = wf_load_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {exc}") from exc
    tasks = wf_list_pending_tasks(db)
    payload = []
    for task in tasks:
        payload_data = task.get("payload") or {}
        payload.append(
            {
                "task_id": task.get("task_id"),
                "type": task.get("type"),
                "client_id": task.get("client_id"),
                "event_id": task.get("event_id"),
                "created_at": task.get("created_at"),
                "notes": task.get("notes"),
                "payload": {
                    "snippet": payload_data.get("snippet"),
                    "suggested_dates": payload_data.get("suggested_dates"),
                },
            }
        )
    return {"tasks": payload}


def _find_task(db: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def _append_conversation_message(event_id: Optional[str], client_email: Optional[str], content: str) -> None:
    target = None
    if event_id:
        target = next((state for state in active_conversations.values() if state.event_id == event_id), None)
    if not target and client_email:
        target = next(
            (
                state
                for state in active_conversations.values()
                if (state.event_info.email or "").lower() == client_email.lower()
            ),
            None,
        )
    if target is not None:
        target.conversation_history.append({"role": "assistant", "content": content})


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as approved from the GUI and advance workflow."""

    try:
        db = wf_load_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {exc}") from exc

    task = _find_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    event_id = task.get("event_id")
    client_email = (task.get("client_id") or "").lower() or None
    message_payload = (task.get("payload") or {}).get("message")
    step_before = None

    if event_id:
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                ensure_event_defaults(event)
                step_before = event.get("current_step")
                review_state = event.setdefault(
                    "review_state",
                    {"state": "none", "reviewed_at": None, "message": None},
                )
                if review_state.get("message"):
                    message_payload = review_state.get("message")
                review_state["state"] = "approved"
                review_state["reviewed_at"] = datetime.utcnow().isoformat() + "Z"
                review_state["message"] = None
                break

    try:
        wf_update_task_status(db, task_id, "approved", request.notes)
        wf_save_db(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to approve task: {exc}") from exc

    assistant_payload: Dict[str, Any] = {"assistant_text": "", "draft_messages": [], "action": "manual_review_approved", "payload": {}}

    if message_payload and event_id:
        result = advance_after_review(message_payload)
        draft_messages = result.get("draft_messages") or []
        fallback_text = _wf_compose_reply(result or {})
        verbalized = verbalize_gui_reply(draft_messages, fallback_text, client_email=message_payload.get("from_email"))
        combined = verbalized or fallback_text or ""
        assistant_payload = {
            "assistant_text": combined,
            "draft_messages": draft_messages,
            "action": result.get("action"),
            "payload": result,
            "step": result.get("step") or (draft_messages[0].get("step") if draft_messages else None),
            "status": result.get("status"),
        }

        db_after = wf_load_db()
        step_after = None
        status_after = None
        if event_id:
            for event in db_after.get("events", []):
                if event.get("event_id") == event_id:
                    ensure_event_defaults(event)
                    step_after = event.get("current_step")
                    status_after = event.get("status")
                    break

        tone_mode = os.getenv("VERBALIZER_TONE", "empathetic").lower()
        sections_count = len(_split_required_sections(fallback_text))
        tone_fallback_used = tone_mode == "empathetic" and verbalized.strip() == fallback_text.strip()
        DEV_LOGGER.info(
            "workflow.review.advance",
            extra={
                "event_id": event_id,
                "step_before": step_before,
                "step_after": step_after,
                "review_state": "approved",
                "tone_mode": tone_mode,
                "sections_count": sections_count,
                "tone_fallback_used": tone_fallback_used,
            },
        )

        _append_conversation_message(event_id, client_email, combined)
    else:
        step_after = step_before
        status_after = None
        _append_conversation_message(event_id, client_email, assistant_payload["assistant_text"])

    thread_id = next(
        (
            sid
            for sid, state in active_conversations.items()
            if state.event_id == event_id
        ),
        None,
    )
    if not thread_id and client_email:
        thread_id = next(
            (
                sid
                for sid, state in active_conversations.items()
                if (state.event_info.email or "").lower() == client_email
            ),
            None,
        )

    return {
        "task_status": "approved",
        "review_state": "approved",
        "task_id": task_id,
        "thread_id": thread_id,
        "event_id": event_id,
        "step": assistant_payload.get("step") or step_after,
        "status": assistant_payload.get("status") or status_after,
        "draft_messages": assistant_payload.get("draft_messages"),
        "assistant_reply": assistant_payload.get("assistant_text"),
    }


@app.post("/api/tasks/{task_id}/reject")
async def reject_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as rejected from the GUI."""
    try:
        db = wf_load_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {exc}") from exc

    task = _find_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    event_id = task.get("event_id")
    client_email = (task.get("client_id") or "").lower() or None

    if event_id:
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                ensure_event_defaults(event)
                review_state = event.setdefault(
                    "review_state",
                    {"state": "none", "reviewed_at": None, "message": None},
                )
                review_state["state"] = "rejected"
                review_state["reviewed_at"] = datetime.utcnow().isoformat() + "Z"
                review_state["message"] = None
                break

    try:
        wf_update_task_status(db, task_id, "rejected", request.notes)
        wf_save_db(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reject task: {exc}") from exc
    DEV_LOGGER.info("workflow.review.rejected", extra={"event_id": event_id})
    message = "Thanks for the update — could you share a bit more detail so I can keep things moving?"
    _append_conversation_message(event_id, client_email, message)
    thread_id = next(
        (
            sid
            for sid, state in active_conversations.items()
            if state.event_id == event_id
        ),
        None,
    )
    if not thread_id and client_email:
        thread_id = next(
            (
                sid
                for sid, state in active_conversations.items()
                if (state.event_info.email or "").lower() == client_email
            ),
            None,
        )
    return {
        "task_status": "rejected",
        "review_state": "rejected",
        "task_id": task_id,
        "thread_id": thread_id,
        "event_id": event_id,
        "assistant_reply": message,
    }


@app.post("/api/conversation/{session_id}/confirm-date")
async def confirm_date(session_id: str, request: ConfirmDateRequest):
    """Condition (purple): persist the confirmed date and pause before availability checks."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[session_id]
    chosen_date = (request.date or conversation_state.event_info.event_date or "").strip()
    if not chosen_date or not DATE_PATTERN.fullmatch(chosen_date):
        raise HTTPException(status_code=400, detail="Invalid or missing date. Use DD.MM.YYYY.")

    assistant_reply = _persist_confirmed_date(conversation_state, chosen_date)
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    return {
        "session_id": session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": None,
    }

@app.post("/api/accept-booking/{session_id}")
async def accept_booking(session_id: str):
    """
    User accepts the collected information - save to centralized JSON database
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation_state = active_conversations[session_id]
    
    # Load existing database
    database = load_events_database()
    
    # Add new event with unique ID and timestamp
    event_entry = {
        "event_id": session_id,
        "created_at": datetime.now().isoformat(),
        "event_data": conversation_state.event_info.to_dict()
    }
    
    database["events"].append(event_entry)
    
    # Save back to file
    save_events_database(database)
    
    # Clean up conversation
    del active_conversations[session_id]
    
    return {
        "message": "Booking accepted and saved",
        "filename": EVENTS_FILE,
        "event_id": session_id,
        "total_events": len(database["events"]),
        "event_info": conversation_state.event_info.to_dict()
    }


@app.get("/api/workflow/health")
async def workflow_health():
    """Minimal health check for workflow integration."""
    return {"db_path": str(WF_DB_PATH), "ok": True}

@app.post("/api/reject-booking/{session_id}")
async def reject_booking(session_id: str):
    """
    User rejects - discard conversation without saving
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Just remove from memory
    del active_conversations[session_id]
    
    return {"message": "Booking rejected and discarded"}

@app.get("/api/conversation/{session_id}")
async def get_conversation(session_id: str):
    """
    Get current conversation state
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation_state = active_conversations[session_id]
    
    return {
        "session_id": session_id,
        "conversation_history": conversation_state.conversation_history,
        "event_info": conversation_state.event_info.dict(),
        "is_complete": conversation_state.is_complete
    }

@app.get("/api/events")
async def get_all_events():
    """
    Get all saved events from database
    """
    database = load_events_database()
    return {
        "total_events": len(database["events"]),
        "events": database["events"]
    }

@app.get("/api/events/{event_id}")
async def get_event_by_id(event_id: str):
    """
    Get a specific event by ID
    """
    database = load_events_database()
    
    for event in database["events"]:
        if event["event_id"] == event_id:
            return event
    
    raise HTTPException(status_code=404, detail="Event not found")

@app.get("/")
async def root():
    database = load_events_database()
    return {
        "status": "AI Event Manager Running",
        "active_conversations": len(active_conversations),
        "total_saved_events": len(database["events"])
    }

if __name__ == "__main__":
    import uvicorn

    _dev_prepare_env()
    _dev_free_port(8000)
    frontend_port, autostart = _ensure_frontend()
    DEV_LOGGER.info(
        "dev: backend starting",
        extra={
            "frontend_port": frontend_port,
            "frontend_autostart": autostart,
        },
    )
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        _shutdown_frontend()
