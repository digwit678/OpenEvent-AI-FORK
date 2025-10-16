from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from agent_adapter import get_agent_adapter
from models import EventStatus
from vocabulary import IntentLabel, TaskStatus, TaskType


DB_PATH = Path(__file__).with_name("events_database.json")
LOCK_PATH = Path(__file__).with_name(".events_db.lock")
LOCK_TIMEOUT = 5.0
LOCK_SLEEP = 0.1

ROOM_ALIASES = {
    "punkt.null": "Punkt.Null",
    "punktnull": "Punkt.Null",
    "room a": "Room A",
    "room b": "Room B",
    "room c": "Room C",
}

LANGUAGE_ALIASES = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "italian": "it",
    "spanish": "es",
}

USER_INFO_KEYS = [
    "date",
    "start_time",
    "end_time",
    "city",
    "participants",
    "room",
    "type",
    "catering",
    "phone",
    "company",
    "language",
    "notes",
]

adapter = get_agent_adapter()
_CURRENT_AGENT_MSG: Optional[Dict[str, Any]] = None


class FileLock:
    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT, sleep: float = LOCK_SLEEP) -> None:
        self.path = path
        self.timeout = timeout
        self.sleep = sleep
        self.fd: Optional[int] = None

    def acquire(self) -> None:
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                return
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Could not acquire lock {self.path}")
                time.sleep(self.sleep)

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.path.exists():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


def _prepare_agent_payload(subject: Optional[str], body: Optional[str]) -> Dict[str, Any]:
    payload = dict(_CURRENT_AGENT_MSG or {})
    if subject is not None:
        payload["subject"] = subject
    else:
        payload["subject"] = payload.get("subject") or ""
    if body is not None:
        payload["body"] = body
    else:
        payload["body"] = payload.get("body") or ""
    return payload


def _clean_text(value: Any, trailing: str = "") -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            text = f"{value}"
        else:
            text = str(int(value))
    else:
        text = str(value)
    cleaned = text.strip()
    if trailing:
        cleaned = cleaned.rstrip(trailing)
    return cleaned or None


def _normalize_phone(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = _clean_text(value) or ""
    if not text:
        return None
    digits = re.sub(r"[^\d+]", "", text)
    return digits or text


def _sanitize_participants(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = _clean_text(value) or ""
    match = re.search(r"(\d{1,4})", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def get_default_db() -> Dict[str, Any]:
    return {"events": [], "clients": {}, "tasks": []}


def lock_path_for(path: Path) -> Path:
    path = Path(path)
    try:
        if path.resolve() == DB_PATH.resolve():
            return LOCK_PATH
    except FileNotFoundError:
        pass
    return path.with_name(f".{path.name}.lock")


def load_db(path: Path = DB_PATH) -> Dict[str, Any]:
    """Load the persistent event database while guaranteeing required keys."""
    path = Path(path)
    lock_path = lock_path_for(path)
    if not path.exists():
        return get_default_db()
    with FileLock(lock_path):
        with path.open("r", encoding="utf-8") as fh:
            db = json.load(fh)
    if "events" not in db or not isinstance(db["events"], list):
        db["events"] = []
    if "clients" not in db or not isinstance(db["clients"], dict):
        db["clients"] = {}
    if "tasks" not in db or not isinstance(db["tasks"], list):
        db["tasks"] = []
    return db


def save_db(db: Dict[str, Any], path: Path = DB_PATH) -> None:
    """Persist the event database atomically to avoid partial writes."""
    path = Path(path)
    lock_path = lock_path_for(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_db = {
        "events": db.get("events", []),
        "clients": db.get("clients", {}),
        "tasks": db.get("tasks", []),
    }
    with FileLock(lock_path):
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(out_db, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def classify_intent(subject: str, body: str) -> Tuple[IntentLabel, float]:
    """Delegate intent classification to the agent adapter and normalize output."""

    payload = _prepare_agent_payload(subject, body)
    intent, confidence = adapter.route_intent(payload)
    return IntentLabel.normalize(intent), float(confidence)


def enqueue_task(
    db: Dict[str, Any],
    task_type: TaskType,
    client_id: str,
    event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """Queue a human-facing task aligned with the management plan workflow."""

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
    """Update the lifecycle state of a task after human input."""

    if isinstance(status, TaskStatus):
        normalized_status = status.value
    else:
        try:
            normalized_status = TaskStatus(status).value
        except ValueError as exc:
            raise ValueError(f"Unsupported task status '{status}'") from exc
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            task["status"] = normalized_status
            if notes is not None:
                task["notes"] = notes
            return
    raise ValueError(f"Task {task_id} not found")


def list_pending_tasks(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List tasks awaiting human action."""

    return [task for task in db.get("tasks", []) if task.get("status") == TaskStatus.PENDING.value]


def _find_task(db: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def extract_user_information(txt: str) -> Dict[str, Optional[Any]]:
    """Delegate detailed user-information extraction to the agent adapter."""
    subject = (_CURRENT_AGENT_MSG or {}).get("subject")
    payload = _prepare_agent_payload(subject, txt)
    if hasattr(adapter, "extract_user_information"):
        raw = adapter.extract_user_information(payload) or {}
    else:
        raw = adapter.extract_entities(payload) or {}
    return sanitize_user_info(raw)


def normalize_room(token: Any) -> Optional[str]:
    """Normalize preferred room naming so it matches our inventory vocabulary."""
    if token is None:
        return None
    cleaned = _clean_text(token) or ""
    if not cleaned:
        return None
    key_variants = {
        cleaned.lower(),
        cleaned.lower().replace(" ", ""),
        cleaned.lower().replace(".", ""),
    }
    for key in key_variants:
        if key in ROOM_ALIASES:
            return ROOM_ALIASES[key]
    if cleaned.lower().startswith("room"):
        suffix = cleaned[4:].strip()
        if suffix:
            suffix_norm = suffix.upper() if len(suffix) == 1 else suffix.title()
            return f"Room {suffix_norm}"
        return "Room"
    return cleaned


def normalize_language(token: Optional[Any]) -> Optional[str]:
    """Normalize language preferences to standardized locale codes."""
    if token is None:
        return None
    cleaned = _clean_text(token, trailing=" .;")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lowered]
    if lowered in {"en", "de", "fr", "it", "es"}:
        return lowered
    return cleaned


def sanitize_user_info(raw: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """Coerce adapter outputs into the workflow schema expected by the platform."""
    sanitized: Dict[str, Optional[Any]] = {}
    for key in USER_INFO_KEYS:
        value = raw.get(key) if raw else None
        if key == "participants":
            sanitized[key] = _sanitize_participants(value)
        elif key == "language":
            sanitized[key] = normalize_language(value)
        elif key == "room":
            sanitized[key] = normalize_room(value)
        elif key == "phone":
            sanitized[key] = _normalize_phone(value)
        elif key in {"catering", "company", "notes"}:
            sanitized[key] = _clean_text(value, trailing=" .;")
        elif key == "type":
            sanitized[key] = _clean_text(value)
        elif key == "city":
            city_text = _clean_text(value)
            if city_text and city_text.lower() not in {"english", "german", "french", "italian", "spanish"} and "room" not in city_text.lower():
                sanitized[key] = city_text
            else:
                sanitized[key] = None
        elif key in {"date", "start_time", "end_time"}:
            sanitized[key] = _clean_text(value)
        else:
            sanitized[key] = value  # keep any additional data untouched
    return sanitized


def build_event_record(user_info: Dict[str, Optional[Any]], msg: Dict[str, Any]) -> Dict[str, Any]:
    """Translate extracted user information into the event database schema."""

    received_ts = msg.get("ts")
    received_date = format_ts_to_ddmmyyyy(received_ts)
    event_date = format_iso_date_to_ddmmyyyy(user_info.get("date"))
    name = msg.get("from_name") or "Not specified"

    participant_count: Optional[str]
    if user_info.get("participants") is None:
        participant_count = "Not specified"
    else:
        participant_count = str(user_info["participants"])

    event_record = {
        "Date Email Received": received_date,
        "Status": EventStatus.LEAD.value,
        "Event Date": event_date or "Not specified",
        "Name": name,
        "Email": msg.get("from_email"),
        "Phone": user_info.get("phone") or "Not specified",
        "Company": user_info.get("company") or "Not specified",
        "Billing Address": "Not specified",
        "Start Time": user_info.get("start_time") or "Not specified",
        "End Time": user_info.get("end_time") or "Not specified",
        "Preferred Room": user_info.get("room") or "Not specified",
        "Number of Participants": participant_count,
        "Type of Event": user_info.get("type") or "Not specified",
        "Catering Preference": user_info.get("catering") or "Not specified",
        "Billing Amount": "none",
        "Deposit": "none",
        "Language": user_info.get("language") or "Not specified",
        "Additional Info": user_info.get("notes") or "Not specified",
    }
    return event_record


def format_ts_to_ddmmyyyy(ts_str: Optional[str]) -> str:
    if not ts_str:
        return date.today().strftime("%d.%m.%Y")
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return date.today().strftime("%d.%m.%Y")
    return dt.strftime("%d.%m.%Y")


def format_iso_date_to_ddmmyyyy(iso_date: Optional[str]) -> Optional[str]:
    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date)
    except ValueError:
        return None
    return dt.strftime("%d.%m.%Y")


def upsert_client(db: Dict[str, Any], email: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Persist/ensure client"""
    client_id = (email or "").lower()
    clients = db.setdefault("clients", {})
    client = clients.setdefault(
        client_id,
        {
            "profile": {"name": None, "org": None, "phone": None},
            "history": [],
            "event_ids": [],
        },
    )
    if name:
        client["profile"]["name"] = client["profile"]["name"] or name
    return client


def append_history(client: Dict[str, Any], msg: Dict[str, Any], intent: str, conf: float, user_info: Dict[str, Any]) -> None:
    """Persist: client history (captures user_info snapshot)"""
    history = client.setdefault("history", [])
    body_preview = (msg.get("body") or "")[:160]
    history.append(
        {
            "msg_id": msg.get("msg_id"),
            "ts": msg.get("ts"),
            "subject": msg.get("subject"),
            "body_preview": body_preview,
            "intent": intent,
            "confidence": float(conf),
            "user_info": dict(user_info),
        }
    )


def link_event_to_client(client: Dict[str, Any], event_id: str) -> None:
    """Link event to client"""
    event_ids = client.setdefault("event_ids", [])
    if event_id not in event_ids:
        event_ids.append(event_id)


def _last_event_for_email(db: Dict[str, Any], email_lc: str) -> Optional[Dict[str, Any]]:
    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for idx, event in enumerate(db.get("events", [])):
        data = event.get("event_data", {})
        if (data.get("Email") or "").lower() == email_lc:
            created = event.get("created_at") or ""
            candidates.append((created, idx, event))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _context_snapshot(db: Dict[str, Any], client: Dict[str, Any], email_lc: str) -> Dict[str, Any]:
    history_tail = client.get("history", [])[-5:]
    return {
        "profile": dict(client.get("profile", {})),
        "history_tail": history_tail,
        "last_event": _last_event_for_email(db, email_lc),
    }


def find_event_idx(db: Dict[str, Any], client_email: str, event_date_ddmmyyyy: str) -> Optional[int]:
    """Condition (purple): check DB for same Email + Event Date"""
    candidates: List[Tuple[int, str]] = []
    for idx, event in enumerate(db.get("events", [])):
        data = event.get("event_data", {})
        if (data.get("Email") or "").lower() == (client_email or "").lower() and data.get("Event Date") == event_date_ddmmyyyy:
            created = event.get("created_at", "")
            candidates.append((idx, created))
    if not candidates:
        return None
    candidates.sort(key=lambda item: ((item[1] or ""), item[0]), reverse=True)
    return candidates[0][0]


def create_event_entry(db: Dict[str, Any], event_data: Dict[str, Any]) -> str:
    """Action: create event"""
    event_id = str(uuid.uuid4())
    entry = {
        "event_id": event_id,
        "created_at": datetime.utcnow().isoformat(),
        "event_data": event_data,
        "msgs": [],  # internal helper; does not alter event_data schema
    }
    db.setdefault("events", []).append(entry)
    return event_id


def update_event_entry(db: Dict[str, Any], idx: int, new_data: Dict[str, Any]) -> List[str]:
    """Action: update event"""
    event = db["events"][idx]
    event_data = event.setdefault("event_data", {})
    updated: List[str] = []
    for key, value in new_data.items():
        if value in (None, "Not specified"):
            continue
        current = event_data.get(key)
        if (
            key == "Additional Info"
            and current
            and current != "Not specified"
            and current != value
            and isinstance(current, str)
            and isinstance(value, str)
        ):
            if value not in current:
                combined = f"{current} | {value}"
            else:
                combined = current
            if combined != current:
                event_data[key] = combined
                updated.append(key)
            continue
        if current != value:
            event_data[key] = value
            updated.append(key)
    return updated


def has_event_date(user_info: Dict[str, Any]) -> bool:
    """Condition (purple): Date Provided?"""
    date_val = user_info.get("date")
    if not date_val:
        return False
    try:
        datetime.fromisoformat(date_val)
    except ValueError:
        return False
    return True


def room_status_on_date(db: Dict[str, Any], date_ddmmyyyy: str, room_name: str) -> str:
    """Static helper: check events on a specific date for the same room."""
    if not room_name or room_name == "Not specified":
        return "Available"
    room_lc = room_name.lower()
    status_found = None
    for event in db.get("events", []):
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        status = (data.get("Status") or "").lower()
        if status == "confirmed":
            return "Confirmed"
        if status == "option":
            status_found = "Option"
    return status_found or "Available"


def suggest_dates(
    db: Dict[str, Any],
    preferred_room: str,
    start_from_iso: Optional[str],
    days_ahead: int = 30,
    max_results: int = 5,
) -> List[str]:
    """Static helper: propose future available dates for a preferred room."""
    today = date.today()
    start_date = today
    if start_from_iso:
        try:
            start_dt = datetime.fromisoformat(start_from_iso.replace("Z", "+00:00"))
            start_date = start_dt.date()
        except ValueError:
            start_date = today
    if start_date < today:
        start_date = today
    suggestions: List[str] = []
    for offset in range(days_ahead):
        day = start_date + timedelta(days=offset)
        day_ddmmyyyy = day.strftime("%d.%m.%Y")
        status = room_status_on_date(db, day_ddmmyyyy, preferred_room)
        if status == "Available":
            suggestions.append(day_ddmmyyyy)
            if len(suggestions) >= max_results:
                break
    return suggestions


def process_msg(msg: Dict[str, Any], db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Process an inbound email following the management plan workflow."""
    global _CURRENT_AGENT_MSG
    _CURRENT_AGENT_MSG = {
        "msg_id": msg.get("msg_id"),
        "from_name": msg.get("from_name"),
        "from_email": msg.get("from_email"),
        "subject": msg.get("subject"),
        "body": msg.get("body"),
        "ts": msg.get("ts"),
    }
    try:
        intent, conf = classify_intent(msg.get("subject", ""), msg.get("body", ""))
        user_info = extract_user_information(msg.get("body", ""))
    finally:
        _CURRENT_AGENT_MSG = None
    db = load_db(db_path)
    client = upsert_client(db, msg.get("from_email", ""), msg.get("from_name"))
    append_history(client, msg, intent.value, conf, user_info)
    client_id = msg.get("from_email", "").lower()

    if intent != IntentLabel.EVENT_REQUEST:
        task_payload = {
            "subject": msg.get("subject"),
            "snippet": (msg.get("body") or "")[:200],
            "ts": msg.get("ts"),
            "reason": "not_event",
        }
        task_id = enqueue_task(db, TaskType.MANUAL_REVIEW, client_id, None, task_payload)
        save_db(db, db_path)
        context = _context_snapshot(db, client, client_id)
        return {
            "action": "manual_review_enqueued",
            "client_id": client_id,
            "event_id": None,
            "intent": intent.value,
            "confidence": round(conf, 3),
            "updated_fields": [],
            "persisted": True,
            "task_id": task_id,
            "user_info": user_info,
            "context": context,
        }

    if not has_event_date(user_info):
        preferred_room = user_info.get("room") or "Not specified"
        suggestions = suggest_dates(
            db,
            preferred_room=preferred_room,
            start_from_iso=msg.get("ts"),
        )
        last_event = _last_event_for_email(db, client_id)
        linked_event_id = last_event.get("event_id") if last_event else None
        task_payload = {
            "suggested_dates": suggestions,
            "preferred_room": preferred_room,
            "user_info": user_info,
        }
        task_id = enqueue_task(db, TaskType.REQUEST_MISSING_EVENT_DATE, client_id, linked_event_id, task_payload)
        save_db(db, db_path)
        context = _context_snapshot(db, client, client_id)
        return {
            "action": "ask_for_date_enqueued",
            "client_id": client_id,
            "event_id": linked_event_id,
            "intent": intent.value,
            "confidence": round(conf, 3),
            "updated_fields": [],
            "persisted": True,
            "task_id": task_id,
            "suggested_dates": suggestions,
            "user_info": user_info,
            "context": context,
        }

    event_data = build_event_record(user_info, msg)
    idx = find_event_idx(db, msg.get("from_email", ""), event_data["Event Date"])
    if idx is None:
        event_id = create_event_entry(db, event_data)
        link_event_to_client(client, event_id)
        updated_fields: List[str] = []
        action = "created_event"
        event_entry = db["events"][-1]
    else:
        updated_fields = update_event_entry(db, idx, event_data)
        event_entry = db["events"][idx]
        event_id = event_entry["event_id"]
        link_event_to_client(client, event_id)
        action = "updated_event"

    msgs_list = event_entry.setdefault("msgs", [])
    msg_id = msg.get("msg_id")
    if msg_id and msg_id not in msgs_list:
        msgs_list.append(msg_id)

    save_db(db, db_path)
    context = _context_snapshot(db, client, client_id)
    res = {
        "action": action,
        "client_id": client_id,
        "event_id": event_id,
        "intent": intent.value,
        "confidence": round(conf, 3),
        "updated_fields": updated_fields,
        "persisted": True,
        "user_info": user_info,
        "context": context,
    }
    return res


def run_samples() -> None:
    os.environ["AGENT_MODE"] = "stub"
    global adapter
    adapter = get_agent_adapter()
    if DB_PATH.exists():
        DB_PATH.unlink()

    sample1 = {
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
    }

    sample2 = {
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
    }

    sample3 = {
        "msg_id": "sample-3",
        "from_name": "Sarah Thompson",
        "from_email": "sarah.thompson@techcorp.com",
        "subject": "Update Request: March 15 2025 details",
        "ts": "2025-10-15T09:15:00Z",
        "body": (
            "Hi,\n"
            "Regarding our event on Mar 15 2025, we now expect ~20 ppl.\n"
            "Please move us to Room B and arrange catering: Premium package.\n"
            "Schedule from 14:00 to 16:30.\n"
            "Thank you!\n"
        ),
    }

    sample4 = {
        "msg_id": "sample-4",
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
    }

    for msg in (sample1, sample2, sample3, sample4):
        res = process_msg(msg)
        print(res)

    if sys.stdin.isatty():
        task_cli_loop()


def task_cli_loop(db_path: Path = DB_PATH) -> None:
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
                        f"- Task {task['task_id']} | type={task['type']} | client={task['client_id']} | event={task['event_id']}\n"
                        f"  created_at={task['created_at']} | payload_keys={list(payload_preview.keys())}"
                    )
                    subj = (payload_preview.get("subject") or "")[:80]
                    snip = (payload_preview.get("snippet") or "")[:80]
                    print(f"  subject={subj}  snippet={snip}")
        elif choice in {"2", "3", "4"}:
            task_id = input("Task ID: ").strip()
            db = load_db(db_path)
            task = _find_task(db, task_id)
            if not task:
                print("Task not found.")
                continue
            notes_input = input("Notes (optional): ").strip()
            notes = notes_input or None
            try:
                if choice == "2":
                    if task.get("type") == TaskType.REQUEST_MISSING_EVENT_DATE.value:
                        payload = task.get("payload") or {}
                        suggestions = payload.get("suggested_dates") or []
                        print("Suggested dates:", ", ".join(suggestions) if suggestions else "<none>")
                        print("Template: Please let us know which proposed date works best for your team.")
                    elif task.get("type") == TaskType.MANUAL_REVIEW.value:
                        payload = task.get("payload") or {}
                        print("Manual review task for subject:", payload.get("subject"))
                    update_task_status(db, task_id, TaskStatus.APPROVED, notes)
                    print("Task approved.")
                elif choice == "3":
                    update_task_status(db, task_id, TaskStatus.REJECTED, notes)
                    print("Task rejected.")
                else:
                    update_task_status(db, task_id, TaskStatus.DONE, notes)
                    print("Task marked done.")
                save_db(db, db_path)
            except ValueError as exc:
                print(f"Error: {exc}")
        elif choice == "5" or choice == "":
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    run_samples()
