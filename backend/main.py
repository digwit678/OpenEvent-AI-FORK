from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
from typing import Optional
from backend.domain import ConversationState, EventInformation
from backend.conversation_manager import (
    classify_email, generate_response, create_summary,
    active_conversations, extract_information_incremental,
)
from pathlib import Path
from backend.adapters.calendar_adapter import get_calendar_adapter
from backend.adapters.client_gui_adapter import ClientGUIAdapter
from backend.workflows.groups.room_availability import run_availability_workflow
from backend.utils import json_io

os.environ.setdefault("AGENT_MODE", os.environ.get("AGENT_MODE_DEFAULT", "openai"))

from backend.workflow_email import (
    process_msg as wf_process_msg,
    DB_PATH as WF_DB_PATH,
    load_db as wf_load_db,
    save_db as wf_save_db,
    list_pending_tasks as wf_list_pending_tasks,
    update_task_status as wf_update_task_status,
)
from backend.api.debug import debug_get_trace, debug_get_timeline, resolve_timeline_path

app = FastAPI(title="AI Event Manager")

DEBUG_TRACE_ENABLED = os.getenv("DEBUG_TRACE") == "1"

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
    wf_res = None
    wf_action = None
    try:
        wf_res = wf_process_msg(msg)
        wf_action = wf_res.get("action")
        print(f"[WF] start action={wf_action} client={request.client_email} event_id={wf_res.get('event_id')} task_id={wf_res.get('task_id')}")
    except Exception as e:
        print(f"[WF][ERROR] {e}")
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

    # Classify the email
    workflow_type = classify_email(request.email_body)
    
    # Handle different workflow types
    if workflow_type == "update":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "This appears to be a request to update an existing booking. This feature is coming soon! For now, please contact us directly at info@theatelier.ch to modify your booking.",
            "is_complete": False,
            "event_info": None
        }
    
    elif workflow_type == "follow_up":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "Thank you for your follow-up message! This feature is under development. For immediate assistance, please email us at info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    elif workflow_type == "other":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "Thank you for your message. However, this doesn't appear to be a new event booking request. I specialize in processing new venue bookings. For other inquiries, please contact our team at info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    # Only proceed if it's a new event
    if workflow_type != "new_event":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "I apologize, but I can only process new event booking requests at this time. For other matters, please reach out to info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    # Create new conversation for new_event
    session_id = str(uuid.uuid4())
    
    event_info = EventInformation(
        date_email_received=datetime.now().strftime("%d.%m.%Y"),
        email=request.client_email
    )
    
    conversation_state = ConversationState(
        session_id=session_id,
        event_info=event_info,
        conversation_history=[],
        workflow_type=workflow_type
    )
    
    # Generate first response
    response_text = generate_response(conversation_state, request.email_body)
    
    # Store in memory
    active_conversations[session_id] = conversation_state
    
    return {
        "session_id": session_id,
        "workflow_type": workflow_type,
        "response": response_text,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump()
    }

@app.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """Condition (purple): continue chat or trigger confirm-date prompt when a valid date appears."""
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[request.session_id]

    previous_date = conversation_state.event_info.event_date
    try:
        conversation_state.event_info = extract_information_incremental(
            request.message,
            conversation_state.event_info,
        )
    except Exception as exc:
        print(f"[WF][WARN] incremental extraction failed: {exc}")

    current_date = conversation_state.event_info.event_date or ""
    has_new_date = (
        current_date
        and DATE_PATTERN.fullmatch(current_date.strip())
        and current_date.strip() != (previous_date or "").strip()
    )

    if has_new_date:
        chosen_date = current_date.strip()
        conversation_state.conversation_history.append({"role": "user", "content": request.message})
        assistant_reply = (
            f"Thanks - I've noted {chosen_date}. Please confirm this is your preferred date."
        )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": {"type": "confirm_date", "date": chosen_date},
        }

    user_message_clean = request.message.strip().lower()
    stored_date = (conversation_state.event_info.event_date or "").strip()
    if (
        stored_date
        and stored_date not in {"Not specified", "none"}
        and user_message_clean in CONFIRM_PHRASES
    ):
        if not DATE_PATTERN.fullmatch(stored_date):
            iso_candidate = _to_iso_date(stored_date)
            if iso_candidate:
                try:
                    stored_date = datetime.strptime(iso_candidate, "%Y-%m-%d").strftime("%d.%m.%Y")
                except ValueError:
                    pass
        conversation_state.conversation_history.append({"role": "user", "content": request.message})
        assistant_reply = _persist_confirmed_date(conversation_state, stored_date)
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    response_text = generate_response(conversation_state, request.message)

    print(f"\n=== DEBUG INFO ===")
    print(f"User message: {request.message}")
    print(f"Is complete: {conversation_state.is_complete}")
    print(f"Event info complete: {conversation_state.event_info.is_complete()}")
    print(f"==================\n")

    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": response_text,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": None,
    }


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


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as approved from the GUI."""
    try:
        db = wf_load_db()
        wf_update_task_status(db, task_id, "approved", request.notes)
        wf_save_db(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to approve task: {exc}") from exc
    print(f"[WF] task approved id={task_id}")
    return {"task_id": task_id, "status": "approved"}


@app.post("/api/tasks/{task_id}/reject")
async def reject_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as rejected from the GUI."""
    try:
        db = wf_load_db()
        wf_update_task_status(db, task_id, "rejected", request.notes)
        wf_save_db(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reject task: {exc}") from exc
    print(f"[WF] task rejected id={task_id}")
    return {"task_id": task_id, "status": "rejected"}


if DEBUG_TRACE_ENABLED:

    @app.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace(thread_id: str):
        return debug_get_trace(thread_id)

    @app.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline(thread_id: str):
        return debug_get_timeline(thread_id)

    @app.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline(thread_id: str):
        path = resolve_timeline_path(thread_id)
        if not path:
            raise HTTPException(status_code=404, detail="Timeline not available")
        safe_id = thread_id.replace("/", "_").replace("\\", "_")
        filename = f"openevent_timeline_{safe_id}.jsonl"
        return FileResponse(path, media_type="application/json", filename=filename)

else:

    @app.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace_disabled(thread_id: str):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline_disabled(thread_id: str):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @app.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline_disabled(thread_id: str):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")


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


atexit.register(_stop_frontend_process)

if __name__ == "__main__":
    import uvicorn
    _frontend_process = _launch_frontend()
    threading.Thread(target=_open_browser_when_ready, name="frontend-browser", daemon=True).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        _stop_frontend_process()
