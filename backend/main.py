from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional
from backend.domain import ConversationState, EventInformation
from backend.conversation_manager import (
    create_summary,
    active_conversations,
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

app = FastAPI(title="AI Event Manager")

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
        # Create a session even when manual review is enqueued so the client can continue messaging.
        session_id = str(uuid.uuid4())
        event_info = EventInformation(
            date_email_received=datetime.now().strftime("%d.%m.%Y"),
            email=request.client_email,
        )
        assistant_reply = (
            "Thanks for your message. We routed it for manual review and will get back to you shortly."
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
        return {
            "session_id": session_id,
            "workflow_type": "new_event",
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.model_dump(),
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
    assistant_reply = _wf_compose_reply(wf_res or {})
    # Optional greeting for GUI conversations to avoid abrupt starts.
    # Keep workflow drafts intact for tests; this only affects the GUI endpoint.
    if isinstance(assistant_reply, str) and assistant_reply.startswith("AVAILABLE DATES"):
        name = _name_from_email(request.client_email)
        salutation = f"Hi {name}," if name else "Hi,"
        assistant_reply = f"{salutation}\n\n{assistant_reply}"
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
    return {
        "session_id": session_id,
        "workflow_type": "new_event",
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump(),
    }

@app.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """Condition (purple): continue chat or trigger confirm-date prompt when a valid date appears."""
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[request.session_id]

    # Route all messages through Workflow v3 and return its drafts
    msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Client (GUI)",
        "from_email": conversation_state.event_info.email or "unknown@example.com",
        "subject": "Client message",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.message or "",
    }
    wf_res = wf_process_msg(msg)
    assistant_reply = _wf_compose_reply(wf_res or {})
    conversation_state.conversation_history.append({"role": "user", "content": request.message})
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
