# CRITICAL: Clear bytecode caches on startup
# This prevents stale .pyc files from causing "unexpected keyword argument" errors on reload
import sys
import os
import shutil
import importlib
from pathlib import Path as _Path
sys.dont_write_bytecode = True  # Prevent new cache writes

# Clear pycache directories
_backend_dir = _Path(__file__).parent
for _cache_dir in _backend_dir.rglob("__pycache__"):
    try:
        shutil.rmtree(_cache_dir)
    except Exception:
        pass

# Invalidate import caches (but don't delete already-loaded modules as that breaks uvicorn)
importlib.invalidate_caches()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uuid
import re
import atexit
import subprocess
import socket
import signal
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
# NOTE: pricing imports (derive_room_rate, normalise_rate) moved to backend/api/routes/tasks.py
from backend.workflows.groups.room_availability import run_availability_workflow
from backend.utils import json_io
from backend.utils.test_data_providers import (
    get_all_catering_menus,
    get_catering_menu_details,
    get_qna_items,
    get_rooms_for_display,
)

os.environ.setdefault("AGENT_MODE", os.environ.get("AGENT_MODE_DEFAULT", "openai"))

from backend.workflow_email import (
    process_msg as wf_process_msg,
    DB_PATH as WF_DB_PATH,
    load_db as wf_load_db,
    save_db as wf_save_db,
    # NOTE: Task functions moved to backend/api/routes/tasks.py
)
from backend.workflows.io.integration.config import is_hil_all_replies_enabled
from backend.api.debug import (
    debug_get_trace,
    debug_get_timeline,
    debug_generate_report,
    resolve_timeline_path,
    render_arrow_log,
    debug_llm_diagnosis,
)
from backend.debug.settings import is_trace_enabled
from backend.debug.trace import BUS
from backend.api.routes import tasks_router, events_router, config_router, clients_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to handle startup and shutdown events."""
    # --- Startup: clear Python cache to prevent stale bytecode issues ---
    # This runs regardless of how the app is started (uvicorn direct, --reload, etc.)
    # and prevents errors like `__init__() got an unexpected keyword argument 'draft'`.
    backend_dir = Path(__file__).parent
    cleared = 0
    for cache_dir in backend_dir.rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(cache_dir)
            cleared += 1
        except Exception:
            pass
    if cleared:
        print(f"[Backend] Startup: cleared {cleared} __pycache__ directories")
    
    yield
    # --- Shutdown logic (if any) can go here ---

app = FastAPI(title="AI Event Manager", lifespan=lifespan)

# Include route modules (Phase C refactoring - extracting from main.py)
app.include_router(tasks_router)
app.include_router(events_router)
app.include_router(config_router)
app.include_router(clients_router)

DEBUG_TRACE_ENABLED = is_trace_enabled()

GUI_ADAPTER = ClientGUIAdapter()

# CORS for frontend - configurable origins for security
# Default allows localhost:3000 for local development
# Set ALLOWED_ORIGINS env var for production (comma-separated list)
_raw_allowed_origins = os.getenv("ALLOWED_ORIGINS")
if _raw_allowed_origins:
    allowed_origins = [origin.strip() for origin in _raw_allowed_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Dev default: allow any localhost origin, regardless of port (3000/3001/etc).
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# CENTRALIZED EVENTS DATABASE
EVENTS_FILE = "events_database.json"
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "atelier-ai-frontend"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
_frontend_process: Optional[subprocess.Popen] = None
DEV_DIR = Path(__file__).resolve().parents[1] / ".dev"
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _pids_listening_on_tcp_port(port: int) -> List[int]:
    """Return PIDs listening on localhost TCP port (best effort; macOS/Linux)."""
    import shutil

    if not shutil.which("lsof"):
        return []
    try:
        output = subprocess.check_output(  # nosec B603,B607 (dev-only port cleanup)
            ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    pids: List[int] = []
    for line in output.decode().splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            pids.append(int(value))
        except ValueError:
            continue
    return sorted(set(pids))


def _terminate_pid(pid: int, timeout_s: float = 3.0) -> None:
    """Terminate a pid (TERM then KILL), best effort."""
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _ensure_backend_port_free(port: int) -> None:
    if not _is_port_in_use(port):
        return
    if os.getenv("AUTO_FREE_BACKEND_PORT", "1") != "1":
        raise RuntimeError(
            f"Port {port} is already in use. Stop the existing process or set AUTO_FREE_BACKEND_PORT=1."
        )
    pids = _pids_listening_on_tcp_port(port)
    if not pids:
        raise RuntimeError(
            f"Port {port} is already in use, but no PID could be discovered (missing lsof?)."
        )
    print(f"[Backend][WARN] Port {port} is in use; terminating listeners: {', '.join(map(str, pids))}")
    for pid in pids:
        _terminate_pid(pid)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_port_in_use(port):
            return
        time.sleep(0.1)
    remaining = _pids_listening_on_tcp_port(port)
    raise RuntimeError(
        f"Port {port} is still in use after attempting cleanup (remaining PIDs: {remaining or 'unknown'})."
    )


def _write_pidfile(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[Backend][WARN] Failed to write pidfile {path}: {exc}")


def _cleanup_pidfile(path: Path) -> None:
    try:
        if not path.exists():
            return
        existing = path.read_text(encoding="utf-8").strip()
        if existing and existing != str(os.getpid()):
            return
        path.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best effort
        return


def _is_frontend_healthy(port: int, timeout: float = 2.0) -> bool:
    """Check if frontend returns a healthy response (not 500 error)."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"http://localhost:{port}/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500  # 404 is OK (might be a different route), 500 is not
    except Exception:
        return False


def _kill_unhealthy_frontend() -> None:
    """Kill any existing frontend processes and clear cache."""
    import shutil
    print("[Frontend] Killing unhealthy frontend and clearing cache...")
    # Kill next dev processes
    subprocess.run(["pkill", "-f", "next dev"], capture_output=True)
    time.sleep(0.5)
    # Clear the .next cache which often causes 500 errors
    next_cache = FRONTEND_DIR / ".next"
    if next_cache.exists():
        try:
            shutil.rmtree(next_cache)
            print("[Frontend] Cleared .next cache")
        except Exception as e:
            print(f"[Frontend][WARN] Could not clear .next cache: {e}")
    time.sleep(0.5)


def _launch_frontend() -> Optional[subprocess.Popen]:
    if os.getenv("AUTO_LAUNCH_FRONTEND", "1") != "1":
        return None
    frontend_pidfile = DEV_DIR / "frontend.pid"
    try:
        if frontend_pidfile.exists():
            existing = frontend_pidfile.read_text(encoding="utf-8").strip()
            existing_pid = int(existing) if existing else None
            if (
                existing_pid
                and _pid_exists(existing_pid)
                and _is_port_in_use(FRONTEND_PORT)
                and _is_frontend_healthy(FRONTEND_PORT)
            ):
                print(
                    f"[Frontend] Reusing existing frontend process (pid={existing_pid}) on http://localhost:{FRONTEND_PORT}"
                )
                return None
            frontend_pidfile.unlink(missing_ok=True)
    except Exception:
        pass
    if _is_port_in_use(FRONTEND_PORT):
        # Port is in use - check if it's actually healthy
        if _is_frontend_healthy(FRONTEND_PORT):
            print(f"[Frontend] Port {FRONTEND_PORT} already in use – frontend is healthy.")
            return None
        else:
            print(f"[Frontend][WARN] Port {FRONTEND_PORT} in use but returning errors!")
            if os.getenv("AUTO_FIX_FRONTEND", "1") == "1":
                _kill_unhealthy_frontend()
                # Now port should be free, continue to launch
            else:
                print(f"[Frontend][WARN] Set AUTO_FIX_FRONTEND=1 to auto-fix, or run:")
                print(f"[Frontend][WARN]   pkill -f 'next dev' && rm -rf atelier-ai-frontend/.next")
                return None
    if not FRONTEND_DIR.exists():
        print(f"[Frontend][WARN] Directory {FRONTEND_DIR} not found; skipping auto-launch.")
        return None
    cmd = ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", str(FRONTEND_PORT)]
    try:
        env = os.environ.copy()
        env.setdefault("NEXT_PUBLIC_BACKEND_BASE", f"http://localhost:{BACKEND_PORT}")
        proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR), env=env, start_new_session=True)
        try:
            DEV_DIR.mkdir(parents=True, exist_ok=True)
            frontend_pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
        except Exception:
            pass
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

    # Check if HIL approval for ALL LLM replies is enabled - don't show message until approved
    res_meta = wf_res.get("res") or {}
    if res_meta.get("pending_hil_approval"):
        # Message is pending manager approval - return empty string (no chat message)
        # The frontend will show the task in the approval queue instead
        return "", wf_res.get("actions") or []

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


# NOTE: TaskDecisionRequest and TaskCleanupRequest moved to backend/api/routes/tasks.py
# NOTE: ClientResetRequest moved to backend/api/routes/clients.py
# NOTE: GlobalDepositConfig moved to backend/api/routes/config.py


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
        import traceback
        print(f"[WF][ERROR] {e}")
        traceback.print_exc()
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
    # Only use fallback message if reply is empty AND HIL approval is NOT pending
    # When HIL approval is pending, we want NO message in the chat
    res_meta = wf_res.get("res") or {}
    hil_pending = res_meta.get("pending_hil_approval", False)
    if not assistant_reply and not hil_pending:
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
    # Only use fallback message if reply is empty AND HIL approval is NOT pending
    # When HIL approval is pending, we want NO message in the chat
    res_meta = wf_res.get("res") or {}
    hil_pending = res_meta.get("pending_hil_approval", False)
    if not assistant_reply and not hil_pending:
        assistant_reply = "Thanks for the update. I'll keep you posted as I gather the details."

    # Only apply step3_payload override if HIL is NOT pending
    # When HIL is pending, the message is in the approval queue and should not appear in chat
    if not hil_pending:
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

    # Include deposit_info from the event for frontend payment button
    # IMPORTANT: Only send deposit_info at Step 4+ (after offer is generated with pricing)
    deposit_info = None
    if conversation_state.event_id:
        try:
            db = wf_load_db()
            for event in db.get("events") or []:
                if event.get("event_id") == conversation_state.event_id:
                    current_step = event.get("current_step", 1)
                    # Only include deposit info at Step 4+ (after room selection and offer generation)
                    if current_step >= 4:
                        raw_deposit = event.get("deposit_info")
                        if raw_deposit and raw_deposit.get("deposit_required"):
                            deposit_info = {
                                "deposit_required": raw_deposit.get("deposit_required", False),
                                "deposit_amount": raw_deposit.get("deposit_amount"),
                                "deposit_due_date": raw_deposit.get("deposit_due_date"),
                                "deposit_paid": raw_deposit.get("deposit_paid", False),
                                "event_id": conversation_state.event_id,
                            }
                    break
        except Exception:
            pass

    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": pending_actions,
        "deposit_info": deposit_info,
    }


# NOTE: Task routes (/api/tasks/*) moved to backend/api/routes/tasks.py
# NOTE: Client routes (/api/client/*) moved to backend/api/routes/clients.py


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

    @app.get("/api/debug/threads/{thread_id}/llm-diagnosis")
    async def get_debug_llm_diagnosis(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        return debug_llm_diagnosis(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
        )

    @app.get("/api/debug/live")
    async def list_live_logs():
        """List all active thread IDs with live logs."""
        from backend.debug import live_log  # pylint: disable=import-outside-toplevel

        threads = live_log.list_active_logs()
        return {
            "active_threads": threads,
            "log_dir": str(live_log.ROOT),
            "watch_command": f"tail -f {live_log.ROOT}/<thread_id>.log",
        }

    @app.get("/api/debug/threads/{thread_id}/live")
    async def get_live_log(thread_id: str):
        """Get the live log content for a thread."""
        from backend.debug import live_log  # pylint: disable=import-outside-toplevel

        path = live_log.get_log_path(thread_id)
        if not path:
            raise HTTPException(status_code=404, detail="Live log not found for this thread")
        try:
            content = path.read_text(encoding="utf-8")
            return PlainTextResponse(content=content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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

    @app.get("/api/debug/threads/{thread_id}/llm-diagnosis")
    async def get_debug_llm_diagnosis_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
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


# Test data endpoints for development pages
@app.get("/api/test-data/rooms")
async def get_rooms_data(date: Optional[str] = None, capacity: Optional[str] = None):
    """Serve room availability data for test pages."""
    rooms = get_rooms_for_display(date, capacity)
    return rooms


@app.get("/api/test-data/catering")
async def get_catering_catalog(
    month: Optional[str] = None,
    vegetarian: Optional[str] = None,
    vegan: Optional[str] = None,
    courses: Optional[str] = None,
    wine_pairing: Optional[str] = None,
):
    """Serve catering menus for catalog page with dynamic filtering."""
    filters = {
        "month": month,
        "vegetarian": vegetarian == "true" if vegetarian else None,
        "vegan": vegan == "true" if vegan else None,
        "courses": int(courses) if courses and courses.isdigit() else None,
        "wine_pairing": wine_pairing == "true" if wine_pairing else None,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}
    menus = get_all_catering_menus(filters=filters)
    return menus


@app.get("/api/test-data/catering/{menu_slug}")
async def get_catering_data(menu_slug: str, room: Optional[str] = None, date: Optional[str] = None):
    """Serve specific catering menu data for test pages."""
    menu = get_catering_menu_details(menu_slug)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    menu["context"] = {
        "room": room,
        "date": date,
    }
    return menu


@app.get("/api/qna")
async def universal_qna(request: Request):
    """Universal Q&A endpoint - accepts any parameters, uses existing Q&A engine."""
    from backend.workflows.qna.engine import build_structured_qna_result
    from backend.workflows.common.types import WorkflowState, IncomingMessage as Message

    # Get all query params
    params = dict(request.query_params)
    category = params.get("category", "general")

    # Build q_values from query params for Q&A engine
    q_values = {}

    # Date/month parameters
    if params.get("date"):
        q_values["date"] = params["date"]
    if params.get("month"):
        q_values["date_pattern"] = params["month"]

    # Capacity parameters
    if params.get("capacity"):
        try:
            q_values["n_exact"] = int(params["capacity"])
        except ValueError:
            pass

    # Room parameters
    if params.get("room"):
        q_values["room"] = params["room"]

    # Product attributes
    product_attributes = []
    if params.get("vegetarian") == "true":
        product_attributes.append("vegetarian")
    if params.get("vegan") == "true":
        product_attributes.append("vegan")
    if params.get("wine_pairing") == "true":
        product_attributes.append("wine pairing")
    if params.get("courses"):
        product_attributes.append(f"{params['courses']}-course")
    if product_attributes:
        q_values["product_attributes"] = product_attributes

    # Build extraction structure
    qna_extraction = {
        "qna_subtype": category,
        "q_values": q_values,
        "msg_type": "event",
        "qna_intent": "select_dependent"
    }

    # Create minimal state for Q&A engine
    try:
        db = wf_load_db()
    except Exception:
        db = {}

    state = WorkflowState(
        client_id="qna-page",
        message=Message(
            msg_id="qna", 
            subject="", 
            body="", 
            from_name=None,
            from_email=None,
            ts=None
        ),
        db_path=Path(WF_DB_PATH),
        db=db,
        user_info={},
        event_entry={},
        intent=None,
        confidence=1.0
    )
    state.extras["qna_extraction"] = qna_extraction

    # Use existing Q&A engine
    try:
        result = build_structured_qna_result(state, qna_extraction)
        
        # Fetch legacy items to support FAQ page
        legacy_data = get_qna_items(category, filters=q_values)

        return {
            "query": params,
            "result_type": category,
            "filters_applied": q_values,
            "data": result.action_payload if result and result.handled else {},
            "items": legacy_data.get("items", []),
            "categories": legacy_data.get("categories", []),
            "menus": legacy_data.get("menus", []),
            "body_markdown": result.body_markdown if result and result.handled else "No results found",
            "handled": result.handled if result else False,
            "success": True
        }
    except Exception as e:
        import traceback
        return {
            "query": params,
            "result_type": category,
            "filters_applied": q_values,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "success": False
        }


@app.get("/api/test-data/qna")
async def get_qna_data(
    category: Optional[str] = None,
    month: Optional[str] = None,
    vegetarian: Optional[str] = None,
    vegan: Optional[str] = None,
    courses: Optional[str] = None,
    wine_pairing: Optional[str] = None,
    date: Optional[str] = None,
    capacity: Optional[str] = None,
):
    """Legacy endpoint - kept for backwards compatibility during migration."""
    filters = {
        "month": month,
        "vegetarian": vegetarian == "true" if vegetarian else None,
        "vegan": vegan == "true" if vegan else None,
        "courses": int(courses) if courses and courses.isdigit() else None,
        "wine_pairing": wine_pairing == "true" if wine_pairing else None,
        "date": date,
        "capacity": int(capacity) if capacity and capacity.isdigit() else None,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}
    return get_qna_items(category, filters=filters)


# ---------------------------------------------------------------------------
# Snapshot endpoints for persistent info page links
# ---------------------------------------------------------------------------

from backend.utils.page_snapshots import (
    get_snapshot,
    get_snapshot_data,
    list_snapshots,
    create_snapshot,
)


@app.get("/api/snapshots/{snapshot_id}")
async def get_snapshot_endpoint(snapshot_id: str):
    """
    Retrieve a stored snapshot by ID.

    Snapshots contain page data (rooms, products, etc.) that was captured
    at a specific point in time, allowing clients to revisit older links.
    """
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return {"error": "Snapshot not found or expired", "snapshot_id": snapshot_id}
    return snapshot


@app.get("/api/snapshots/{snapshot_id}/data")
async def get_snapshot_data_endpoint(snapshot_id: str):
    """
    Retrieve just the data payload from a snapshot.

    Use this endpoint when you only need the data, not the metadata.
    """
    data = get_snapshot_data(snapshot_id)
    if data is None:
        return {"error": "Snapshot not found or expired", "snapshot_id": snapshot_id}
    return {"snapshot_id": snapshot_id, "data": data}


@app.get("/api/snapshots")
async def list_snapshots_endpoint(
    type: Optional[str] = None,
    event_id: Optional[str] = None,
    limit: int = 50,
):
    """
    List available snapshots, optionally filtered by type or event_id.

    Returns metadata only (not full data) for efficiency.
    """
    return {
        "snapshots": list_snapshots(snapshot_type=type, event_id=event_id, limit=limit)
    }


@app.get("/api/workflow/health")
async def workflow_health():
    """Minimal health check for workflow integration."""
    return {"db_path": str(WF_DB_PATH), "ok": True}


@app.get("/api/workflow/hil-status")
async def get_hil_status():
    """Get the HIL toggle status for AI reply approval.

    Returns whether the OE_HIL_ALL_LLM_REPLIES toggle is enabled.
    When enabled, all AI replies require manager approval before
    being sent to the client.
    """
    return {
        "hil_all_replies_enabled": is_hil_all_replies_enabled(),
    }


# NOTE: Config routes (/api/config/*) moved to backend/api/routes/config.py
# NOTE: Deposit payment endpoints moved to backend/api/routes/events.py


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


# NOTE: /api/events routes moved to backend/api/routes/events.py


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
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
        except Exception:
            pass
    finally:
        try:
            pidfile = DEV_DIR / "frontend.pid"
            if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip() == str(proc.pid):
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass
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


if os.getenv("DEBUG_TRACE_PERSIST_ON_EXIT", "0") == "1":
    atexit.register(_persist_debug_reports)
atexit.register(_stop_frontend_process)

def _clear_python_cache() -> None:
    """Clear Python bytecode cache to prevent stale dataclass issues."""
    backend_dir = Path(__file__).parent
    cleared = 0
    for cache_dir in backend_dir.rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(cache_dir)
            cleared += 1
        except Exception:
            pass
    if cleared:
        print(f"[Backend] Cleared {cleared} __pycache__ directories")


if __name__ == "__main__":
    import uvicorn
    # Clear Python cache to prevent stale bytecode issues (e.g., missing dataclass fields)
    _clear_python_cache()

    backend_pidfile = DEV_DIR / "backend.pid"
    _write_pidfile(backend_pidfile)
    atexit.register(_cleanup_pidfile, backend_pidfile)

    _ensure_backend_port_free(BACKEND_PORT)
    _frontend_process = _launch_frontend()
    threading.Thread(target=_open_browser_when_ready, name="frontend-browser", daemon=True).start()
    try:
        uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
    finally:
        _stop_frontend_process()
