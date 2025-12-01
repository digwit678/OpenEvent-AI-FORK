from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
import uuid
import os
import re
import atexit
import subprocess
import socket
import time
import webbrowser
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.domain import ConversationState, EventInformation
from backend.conversation_manager import (
    active_conversations,
    extract_information_incremental,
    render_step3_reply,
    pop_step3_payload,
)
from pathlib import Path
from backend.adapters.calendar_adapter import get_calendar_adapter
from backend.adapters.client_gui_adapter import ClientGUIAdapter
from backend.workflows.common.payloads import PayloadValidationError, validate_confirm_date_payload
from backend.workflows.groups.date_confirmation import compose_date_confirmation_reply
from backend.workflows.common.prompts import append_footer
from backend.workflows.groups.room_availability import run_availability_workflow
from backend.utils import json_io

os.environ.setdefault("AGENT_MODE", os.environ.get("AGENT_MODE_DEFAULT", "openai"))

from backend.workflow_email import (
    process_msg as wf_process_msg,
    DB_PATH as WF_DB_PATH,
    load_db as wf_load_db,
    save_db as wf_save_db,
    list_pending_tasks as wf_list_pending_tasks,
    approve_task_and_send as wf_approve_task_and_send,
    reject_task_and_send as wf_reject_task_and_send,
    cleanup_tasks as wf_cleanup_tasks,
)
from backend.api.debug import (
    debug_get_trace,
    debug_get_timeline,
    debug_generate_report,
    resolve_timeline_path,
    render_arrow_log,
)
from backend.debug.settings import is_trace_enabled
from backend.debug.trace import BUS

app = FastAPI(title="AI Event Manager")

DEBUG_TRACE_ENABLED = is_trace_enabled()

GUI_ADAPTER = ClientGUIAdapter()

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
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "atelier-ai-frontend"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
_frontend_process: Optional[subprocess.Popen] = None


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _launch_frontend() -> Optional[subprocess.Popen]:
    if os.getenv("AUTO_LAUNCH_FRONTEND", "1") != "1":
        return None
    if _is_port_in_use(FRONTEND_PORT):
        print(f"[Frontend] Port {FRONTEND_PORT} already in use – assuming frontend is running.")
        return None
    if not FRONTEND_DIR.exists():
        print(f"[Frontend][WARN] Directory {FRONTEND_DIR} not found; skipping auto-launch.")
        return None
    cmd = ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", str(FRONTEND_PORT)]
    try:
        proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR))
        print(f"[Frontend] npm dev server starting on http://localhost:{FRONTEND_PORT}")
        return proc
    except FileNotFoundError:
        print("[Frontend][WARN] npm not found on PATH; skipping auto-launch.")
    except Exception as exc:
        print(f"[Frontend][ERROR] Failed to launch npm dev server: {exc}")
    return None


def _open_browser_when_ready() -> None:
    if os.getenv("AUTO_OPEN_FRONTEND", "1") != "1":
        return
    target_url = f"http://localhost:{FRONTEND_PORT}"
    debug_url = f"{target_url}/debug"
    for attempt in range(120):
        if _is_port_in_use(FRONTEND_PORT):
            try:
                webbrowser.open_new(target_url)
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    webbrowser.open_new_tab(debug_url)
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"[Frontend][WARN] Unable to open browser automatically: {exc}")
            else:
                print(f"[Frontend] Opened browser window at {target_url}")
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    print(f"[Frontend] Opened debug panel at {debug_url}")
            return
        time.sleep(0.5)
    print(f"[Frontend][WARN] Frontend not reachable on {target_url} after waiting 60s; skipping auto-open.")


def _parse_kind_filter(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


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


def _format_draft_text(draft: Dict[str, Any]) -> str:
    headers = [
        str(header).strip()
        for header in draft.get("headers") or []
        if str(header).strip()
    ]
    body = draft.get("body_markdown") or draft.get("body") or ""
    parts = headers + [body]
    return "\n\n".join(part for part in parts if part)


def _extract_workflow_reply(wf_res: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    wf_action = wf_res.get("action")
    if wf_action in {
        "offer_accept_pending_hil",
        "negotiation_accept_pending_hil",
        "negotiation_hil_waiting",
        "offer_waiting_hil",
    }:
        waiting_text = (
            "Thanks for confirming - I've sent the full offer to our manager for approval. "
            "I'll let you know as soon as it's reviewed."
        )
        return waiting_text, wf_res.get("actions") or []

    drafts = wf_res.get("draft_messages") or []
    if drafts:
        draft = drafts[-1]
        text = _format_draft_text(draft)
        actions = draft.get("actions") or wf_res.get("actions") or []
        return text.strip(), actions
    text = wf_res.get("assistant_message") or ""
    return text.strip(), wf_res.get("actions") or []


def _merge_field(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    candidate_str = str(candidate).strip()
    if not candidate_str or candidate_str.lower() == "not specified":
        return current
    return candidate_str


def _update_event_info_from_db(event_info: EventInformation, event_id: Optional[str]) -> EventInformation:
    if not event_id:
        return event_info
    try:
        db = wf_load_db()
    except Exception as exc:
        print(f"[WF][WARN] Unable to refresh event info from DB: {exc}")
        return event_info

    events = db.get("events") or []
    entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not entry:
        return event_info

    event_info.status = _merge_field(event_info.status, entry.get("status"))
    data = entry.get("event_data") or {}

    event_info.event_date = _merge_field(event_info.event_date, data.get("Event Date"))
    event_info.name = _merge_field(event_info.name, data.get("Name"))
    event_info.email = _merge_field(event_info.email, data.get("Email"))
    event_info.phone = _merge_field(event_info.phone, data.get("Phone"))
    event_info.company = _merge_field(event_info.company, data.get("Company"))
    event_info.billing_address = _merge_field(event_info.billing_address, data.get("Billing Address"))
    event_info.start_time = _merge_field(event_info.start_time, data.get("Start Time"))
    event_info.end_time = _merge_field(event_info.end_time, data.get("End Time"))
    event_info.preferred_room = _merge_field(event_info.preferred_room, data.get("Preferred Room"))
    event_info.number_of_participants = _merge_field(
        event_info.number_of_participants, data.get("Number of Participants")
    )
    event_info.type_of_event = _merge_field(event_info.type_of_event, data.get("Type of Event"))
    event_info.catering_preference = _merge_field(
        event_info.catering_preference, data.get("Catering Preference")
    )
    event_info.billing_amount = _merge_field(event_info.billing_amount, data.get("Billing Amount"))
    event_info.deposit = _merge_field(event_info.deposit, data.get("Deposit"))
    event_info.language = _merge_field(event_info.language, data.get("Language"))
    event_info.additional_info = _merge_field(event_info.additional_info, data.get("Additional Info"))

    requirements = entry.get("requirements") or {}
    participants_req = requirements.get("number_of_participants")
    if participants_req:
        event_info.number_of_participants = _merge_field(
            event_info.number_of_participants, str(participants_req)
        )

    return event_info

# REQUEST/RESPONSE MODELS
class StartConversationRequest(BaseModel):
    email_body: str
    client_email: str

class SendMessageRequest(BaseModel):
    session_id: str
    message: str


class TaskDecisionRequest(BaseModel):
    notes: Optional[str] = None


class TaskCleanupRequest(BaseModel):
    keep_thread_id: Optional[str] = None


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


def _format_participants_label(raw: Optional[str]) -> str:
    if not raw:
        return "your group"
    text = str(raw).strip()
    if not text or text.lower() in {"not specified", "none"}:
        return "your group"
    match = re.search(r"\d{1,4}", text)
    if match:
        try:
            number = int(match.group(0))
            if number > 0:
                return "1 guest" if number == 1 else f"{number} guests"
        except ValueError:
            pass
    return text


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


def _persist_confirmed_date(conversation_state: ConversationState, chosen_date: str) -> Dict[str, Any]:
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

    iso_confirmed = _to_iso_date(chosen_date)
    if event_id and iso_confirmed:
        try:
            validate_confirm_date_payload({
                "action": "confirm_date",
                "event_id": event_id,
                "date": iso_confirmed,
            })
        except PayloadValidationError as exc:
            print(f"[WF][WARN] confirm_date payload validation failed: {exc}")

    try:
        _trigger_room_availability(event_id, chosen_date)
    except Exception as exc:
        print(f"[WF][ERROR] trigger availability failed: {exc}")

    rendered = render_step3_reply(conversation_state, wf_res.get("draft_messages"))
    actions: List[Dict[str, Any]] = []
    subject: Optional[str] = None
    assistant_reply = wf_res.get("assistant_message")

    if rendered:
        subject = rendered.get("subject")
        actions = rendered.get("actions") or []
        assistant_reply = rendered.get("body_markdown") or rendered.get("body") or assistant_reply

    if not assistant_reply:
        pax_label = _format_participants_label(conversation_state.event_info.number_of_participants)
        assistant_reply = compose_date_confirmation_reply(chosen_date, pax_label)
        assistant_reply = append_footer(
            assistant_reply,
            step=3,
            next_step="Availability result",
            thread_state="Checking",
        )

    return {
        "body": assistant_reply,
        "actions": actions,
        "subject": subject,
    }

@app.post("/api/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """Condition (purple): kick off workflow and branch on manual or ask-for-date pauses before legacy flow."""
    os.environ.setdefault("AGENT_MODE", "openai")
    subject_line = (request.email_body.splitlines()[0][:80] if request.email_body else "No subject")
    session_id = str(uuid.uuid4())
    msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Not specified",
        "from_email": request.client_email,
        "subject": subject_line,
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.email_body or "",
        "session_id": session_id,
        "thread_id": session_id,
    }
    wf_res = None
    wf_action = None
    try:
        wf_res = wf_process_msg(msg)
        wf_action = wf_res.get("action")
        print(f"[WF] start action={wf_action} client={request.client_email} event_id={wf_res.get('event_id')} task_id={wf_res.get('task_id')}")
    except Exception as e:
        print(f"[WF][ERROR] {e}")
    if not wf_res:
        raise HTTPException(status_code=500, detail="Workflow processing failed")
    if wf_action == "manual_review_enqueued":
        response_text = (
            "Thanks for your message. We routed it for manual review and will get back to you shortly."
        )
        return {
            "session_id": None,
            "workflow_type": "other",
            "response": response_text,
            "is_complete": False,
            "event_info": None,
        }
    if wf_action == "ask_for_date_enqueued":
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
            event_id=(wf_res or {}).get("event_id"),
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

    workflow_type = "new_event"
    event_info = EventInformation(
        date_email_received=datetime.now().strftime("%d.%m.%Y"),
        email=request.client_email
    )
    event_id = (wf_res or {}).get("event_id")

    conversation_state = ConversationState(
        session_id=session_id,
        event_info=event_info,
        conversation_history=[],
        workflow_type=workflow_type,
        event_id=event_id,
    )
    
    conversation_state.conversation_history.append({"role": "user", "content": request.email_body or ""})

    assistant_reply, action_items = _extract_workflow_reply(wf_res)
    if not assistant_reply:
        assistant_reply = "Thanks for your message. I'll follow up shortly with availability details."

    conversation_state.event_id = wf_res.get("event_id") or event_id
    conversation_state.event_info = _update_event_info_from_db(conversation_state.event_info, conversation_state.event_id)
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    active_conversations[session_id] = conversation_state

    pending_actions = {"type": "workflow_actions", "actions": action_items} if action_items else None

    return {
        "session_id": session_id,
        "workflow_type": workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump(),
        "pending_actions": pending_actions,
    }

@app.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """Condition (purple): continue chat or trigger confirm-date prompt when a valid date appears."""
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[request.session_id]

    try:
        conversation_state.event_info = extract_information_incremental(
            request.message,
            conversation_state.event_info,
        )
    except Exception as exc:
        print(f"[WF][WARN] incremental extraction failed: {exc}")

    conversation_state.conversation_history.append({"role": "user", "content": request.message})

    payload = {
        "msg_id": str(uuid.uuid4()),
        "from_name": conversation_state.event_info.name or "Client",
        "from_email": conversation_state.event_info.email,
        "subject": f"Client follow-up ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')})",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.message,
        "thread_id": request.session_id,
        "session_id": request.session_id,
    }

    try:
        wf_res = wf_process_msg(payload)
    except Exception as exc:
        print(f"[WF][ERROR] send_message workflow failed: {exc}")
        assistant_reply = "Thanks for the update. I'll follow up shortly with the latest availability."
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    wf_action = wf_res.get("action")
    if wf_action == "manual_review_enqueued":
        assistant_reply = (
            "Thanks for your message. We routed it for manual review and will get back to you shortly."
        )
        conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
        conversation_state.event_info = _update_event_info_from_db(
            conversation_state.event_info,
            conversation_state.event_id,
        )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    if wf_action == "ask_for_date_enqueued":
        suggested_dates = (wf_res or {}).get("suggested_dates") or []
        dates_text = ", ".join(suggested_dates) if suggested_dates else "No specific dates yet."
        assistant_reply = (
            f"Hello again,\n\nHere are the next available dates that fit your window: {dates_text}"
        )
        conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
        conversation_state.event_info = _update_event_info_from_db(
            conversation_state.event_info,
            conversation_state.event_id,
        )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    assistant_reply, action_items = _extract_workflow_reply(wf_res)
    if not assistant_reply:
        assistant_reply = "Thanks for the update. I’ll keep you posted as I gather the details."

    step3_payload = pop_step3_payload(request.session_id)
    if step3_payload:
        body_pref = step3_payload.get("body_markdown") or step3_payload.get("body")
        if body_pref:
            assistant_reply = body_pref
        actions_override = step3_payload.get("actions") or []
        if actions_override:
            action_items = actions_override

    conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
    conversation_state.event_info = _update_event_info_from_db(
        conversation_state.event_info,
        conversation_state.event_id,
    )
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    pending_actions = {"type": "workflow_actions", "actions": action_items} if action_items else None

    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": pending_actions,
    }


@app.get("/api/tasks/pending")
async def get_pending_tasks():
    """OpenEvent Action (light-blue): expose pending manual tasks for GUI approvals."""
    try:
        db = wf_load_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {exc}") from exc
    tasks = wf_list_pending_tasks(db)
    events_by_id = {event.get("event_id"): event for event in db.get("events") or [] if event.get("event_id")}
    payload = []
    offer_tasks_indices: Dict[tuple[str, str], int] = {}
    for task in tasks:
        payload_data = task.get("payload") or {}
        event_entry = events_by_id.get(task.get("event_id"))
        event_data = (event_entry or {}).get("event_data") or {}
        draft_body = payload_data.get("draft_body") or payload_data.get("draft_msg")
        if not draft_body and event_entry:
            for request in event_entry.get("pending_hil_requests") or []:
                if request.get("task_id") == task.get("task_id"):
                    draft_body = (request.get("draft") or {}).get("body") or draft_body
                    break

        event_summary = None
        if event_entry:
            def _line_items(entry: Dict[str, Any]) -> list[str]:
                items: list[str] = []
                for product in entry.get("products") or []:
                    name = product.get("name") or "Unnamed item"
                    try:
                        qty = float(product.get("quantity") or 0)
                    except (TypeError, ValueError):
                        qty = 0
                    try:
                        unit_price = float(product.get("unit_price") or 0.0)
                    except (TypeError, ValueError):
                        unit_price = 0.0
                    unit = product.get("unit")
                    total = qty * unit_price if qty and unit_price else unit_price
                    label = f"{qty:g}× {name}" if qty else name
                    price_text = f"CHF {total:,.2f}"
                    if unit == "per_person" and qty:
                        price_text += f" (CHF {unit_price:,.2f} per person)"
                    elif unit == "per_event":
                        price_text += " (per event)"
                    items.append(f"{label} · {price_text}")
                return items

            event_summary = {
                "client_name": event_data.get("Name"),
                "company": event_data.get("Company"),
                "billing_address": event_data.get("Billing Address"),
                "email": event_data.get("Email"),
                "chosen_date": event_entry.get("chosen_date"),
                "locked_room": event_entry.get("locked_room_id"),
                "line_items": _line_items(event_entry),
            }
            try:
                from backend.workflows.groups.negotiation_close import _determine_offer_total

                total_amount = _determine_offer_total(event_entry)
            except Exception:
                total_amount = None
            if total_amount not in (None, 0):
                event_summary["offer_total"] = total_amount

        record = {
            "task_id": task.get("task_id"),
            "type": task.get("type"),
            "client_id": task.get("client_id"),
            "event_id": task.get("event_id"),
            "created_at": task.get("created_at"),
            "notes": task.get("notes"),
            "payload": {
                "snippet": payload_data.get("snippet"),
                "draft_body": draft_body,
                "suggested_dates": payload_data.get("suggested_dates"),
                "thread_id": payload_data.get("thread_id"),
                "step_id": payload_data.get("step_id") or payload_data.get("step"),
                "event_summary": event_summary,
            },
        }
        payload.append(record)
        if task.get("type") == "offer_message" and payload_data.get("thread_id"):
            key = (task.get("event_id"), payload_data.get("thread_id"))
            offer_tasks_indices[key] = len(payload) - 1

    # Deduplicate per (event, thread) by priority so only one task shows in the manager panel.
    priority = {
        "offer_message": 0,
        "room_availability_message": 1,
        "date_confirmation_message": 2,
        "ask_for_date": 3,
        "manual_review": 4,
    }
    dedup: Dict[tuple[str, str], Dict[str, Any]] = {}
    for record in payload:
        thread_id = (record.get("payload") or {}).get("thread_id")
        event_id = record.get("event_id")
        key = (event_id, thread_id)
        rank = priority.get(record.get("type"), 99)
        current = dedup.get(key)
        if current is None or priority.get(current.get("type"), 99) > rank:
            dedup[key] = record
    payload = list(dedup.values())

    return {"tasks": payload}


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as approved from the GUI."""
    try:
        result = wf_approve_task_and_send(task_id, manager_notes=request.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to approve task: {exc}") from exc
    print(f"[WF] task approved id={task_id}")
    assistant_text = result.get("res", {}).get("assistant_draft_text")
    return {
        "task_id": task_id,
        "task_status": "approved",
        "assistant_reply": assistant_text,
        "thread_id": result.get("thread_id"),
        "event_id": result.get("event_id"),
        "review_state": "approved",
    }


@app.post("/api/tasks/{task_id}/reject")
async def reject_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as rejected from the GUI."""
    try:
        result = wf_reject_task_and_send(task_id, manager_notes=request.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reject task: {exc}") from exc
    print(f"[WF] task rejected id={task_id}")
    assistant_text = result.get("res", {}).get("assistant_draft_text")
    return {
        "task_id": task_id,
        "task_status": "rejected",
        "assistant_reply": assistant_text,
        "thread_id": result.get("thread_id"),
        "event_id": result.get("event_id"),
        "review_state": "rejected",
    }


@app.post("/api/tasks/cleanup")
async def cleanup_tasks(request: TaskCleanupRequest):
    """Remove resolved HIL tasks to declutter the task list."""
    try:
        db = wf_load_db()
        removed = wf_cleanup_tasks(db, keep_thread_id=request.keep_thread_id)
        wf_save_db(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup tasks: {exc}") from exc
    print(f"[WF] tasks cleanup removed={removed}")
    return {"removed": removed}


if DEBUG_TRACE_ENABLED:

    @app.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        return debug_get_trace(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            as_of_ts=as_of_ts,
        )

    @app.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        return debug_get_timeline(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            as_of_ts=as_of_ts,
        )

    @app.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline(thread_id: str):
        path = resolve_timeline_path(thread_id)
        if not path:
            raise HTTPException(status_code=404, detail="Timeline not available")
        safe_id = thread_id.replace("/", "_").replace("\\", "_")
        filename = f"openevent_timeline_{safe_id}.jsonl"
        return FileResponse(path, media_type="application/json", filename=filename)

    @app.get("/api/debug/threads/{thread_id}/timeline/text")
    async def download_debug_thread_timeline_text(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        return render_arrow_log(thread_id, granularity=granularity, kinds=_parse_kind_filter(kinds))

    @app.get("/api/debug/threads/{thread_id}/report")
    async def download_debug_thread_report(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        persist: bool = Query(False),
    ):
        body, saved_path = debug_generate_report(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            persist=persist,
        )
        headers = {}
        if saved_path:
            headers["X-Debug-Report-Path"] = saved_path
        return PlainTextResponse(content=body, headers=headers)

else:

    @app.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline_disabled(thread_id: str):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/timeline/text")
    async def download_debug_thread_timeline_text_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/report")
    async def download_debug_thread_report_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        persist: bool = Query(False),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")


@app.post("/api/conversation/{session_id}/confirm-date")
async def confirm_date(session_id: str, request: ConfirmDateRequest):
    """Condition (purple): persist the confirmed date and pause before availability checks."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[session_id]
    raw_date = (request.date or conversation_state.event_info.event_date or "").strip()
    iso_candidate = _to_iso_date(raw_date)
    if not iso_candidate:
        raise HTTPException(status_code=400, detail="Invalid or missing date. Use YYYY-MM-DD.")
    try:
        chosen_date = datetime.strptime(iso_candidate, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid or missing date. Use YYYY-MM-DD.") from exc

    assistant_payload = _persist_confirmed_date(conversation_state, chosen_date)
    assistant_reply = assistant_payload.get("body") or ""
    actions = assistant_payload.get("actions") or []
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
    pending_actions = {"type": "workflow_actions", "actions": actions} if actions else None

    return {
        "session_id": session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": pending_actions,
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


def _stop_frontend_process() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        _frontend_process = None


def _persist_debug_reports() -> None:
    if not DEBUG_TRACE_ENABLED:
        return
    try:
        thread_ids = BUS.list_threads()
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"[Debug][WARN] Unable to enumerate trace threads: {exc}")
        return
    for thread_id in thread_ids:
        try:
            debug_generate_report(thread_id, persist=True)
        except Exception as exc:
            print(f"[Debug][WARN] Failed to persist debug report for {thread_id}: {exc}")


atexit.register(_persist_debug_reports)
atexit.register(_stop_frontend_process)

if __name__ == "__main__":
    import uvicorn
    _frontend_process = _launch_frontend()
    threading.Thread(target=_open_browser_when_ready, name="frontend-browser", daemon=True).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        _stop_frontend_process()
