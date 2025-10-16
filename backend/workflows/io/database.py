from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import EventStatus
from vocabulary import TaskStatus


LOCK_TIMEOUT = 5.0
LOCK_SLEEP = 0.1


class FileLock:
    """[OpenEvent Database] Coarse-grained filesystem lock to guard JSON persistence."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT, sleep: float = LOCK_SLEEP) -> None:
        self.path = path
        self.timeout = timeout
        self.sleep = sleep
        self.fd: Optional[int] = None

    def acquire(self) -> None:
        """[OpenEvent Database] Block until a lock file can be created or raise on timeout."""

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
        """[OpenEvent Database] Drop the lock file once a critical section completes."""

        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.path.exists():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "FileLock":
        """[OpenEvent Database] Enter a context manager that owns the lock."""

        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """[OpenEvent Database] Release the lock when leaving the context manager."""

        self.release()


def get_default_db() -> Dict[str, Any]:
    """[OpenEvent Database] Provide the baseline JSON schema for a clean database."""

    return {"events": [], "clients": {}, "tasks": []}


def lock_path_for(path: Path, default_lock: Optional[Path] = None) -> Path:
    """[OpenEvent Database] Derive a sibling lockfile path for a JSON resource."""

    path = Path(path)
    if default_lock is not None:
        return default_lock
    return path.with_name(f".{path.name}.lock")


def load_db(path: Path, lock_path: Optional[Path] = None) -> Dict[str, Any]:
    """[OpenEvent Database] Load and validate the events database from disk."""

    path = Path(path)
    if not path.exists():
        return get_default_db()
    lock_candidate = lock_path_for(path, lock_path)
    with FileLock(lock_candidate):
        with path.open("r", encoding="utf-8") as fh:
            db = json.load(fh)
    if "events" not in db or not isinstance(db["events"], list):
        db["events"] = []
    if "clients" not in db or not isinstance(db["clients"], dict):
        db["clients"] = {}
    if "tasks" not in db or not isinstance(db["tasks"], list):
        db["tasks"] = []
    return db


def save_db(db: Dict[str, Any], path: Path, lock_path: Optional[Path] = None) -> None:
    """[OpenEvent Database] Persist the database atomically with crash-safe semantics."""

    path = Path(path)
    lock_candidate = lock_path_for(path, lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_db = {
        "events": db.get("events", []),
        "clients": db.get("clients", {}),
        "tasks": db.get("tasks", []),
    }
    with FileLock(lock_candidate):
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


def upsert_client(db: Dict[str, Any], email: str, name: Optional[str] = None) -> Dict[str, Any]:
    """[OpenEvent Database] Create or return a client profile keyed by email."""

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
    """[OpenEvent Database] Record a message snapshot under the client's communication history."""

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
    """[OpenEvent Database] Associate an event identifier with a client record."""

    event_ids = client.setdefault("event_ids", [])
    if event_id not in event_ids:
        event_ids.append(event_id)


def _last_event_for_email(db: Dict[str, Any], email_lc: str) -> Optional[Dict[str, Any]]:
    """[OpenEvent Database] Locate the newest event entry for a given email."""

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


def context_snapshot(db: Dict[str, Any], client: Dict[str, Any], email_lc: str) -> Dict[str, Any]:
    """[OpenEvent Database] Assemble a short context payload for downstream steps."""

    history_tail = client.get("history", [])[-5:]
    return {
        "profile": dict(client.get("profile", {})),
        "history_tail": history_tail,
        "last_event": _last_event_for_email(db, email_lc),
    }


def last_event_for_email(db: Dict[str, Any], email_lc: str) -> Optional[Dict[str, Any]]:
    """[OpenEvent Database] Fetch the newest event associated with a client email."""

    return _last_event_for_email(db, email_lc)


def find_event_idx(db: Dict[str, Any], client_email: str, event_date_ddmmyyyy: str) -> Optional[int]:
    """[OpenEvent Database] Locate an existing event entry by email and event date."""

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
    """[OpenEvent Database] Insert a new event entry and return its identifier."""

    event_id = str(uuid.uuid4())
    entry = {
        "event_id": event_id,
        "created_at": datetime.utcnow().isoformat(),
        "event_data": event_data,
        "msgs": [],
    }
    db.setdefault("events", []).append(entry)
    return event_id


def update_event_entry(db: Dict[str, Any], idx: int, new_data: Dict[str, Any]) -> List[str]:
    """[OpenEvent Database] Apply partial updates to an existing event entry."""

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


def tag_message(event_entry: Dict[str, Any], msg_id: Optional[str]) -> None:
    """[OpenEvent Database] Link a processed message to the event entry for audit."""

    if not msg_id:
        return
    msgs_list = event_entry.setdefault("msgs", [])
    if msg_id not in msgs_list:
        msgs_list.append(msg_id)


def default_event_record(user_info: Dict[str, Any], msg: Dict[str, Any], received_date: str) -> Dict[str, Any]:
    """[OpenEvent Database] Translate sanitized user info into the event DB schema."""

    participant_count: Optional[str]
    if user_info.get("participants") is None:
        participant_count = "Not specified"
    else:
        participant_count = str(user_info["participants"])
    return {
        "Date Email Received": received_date,
        "Status": EventStatus.LEAD.value,
        "Event Date": user_info.get("event_date") or "Not specified",
        "Name": msg.get("from_name") or "Not specified",
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
