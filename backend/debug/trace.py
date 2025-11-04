from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .settings import is_trace_enabled

TraceKind = Literal[
    "STEP_ENTER",
    "STEP_EXIT",
    "GATE_PASS",
    "GATE_FAIL",
    "DB_READ",
    "DB_WRITE",
    "ENTITY_CAPTURE",
    "ENTITY_SUPERSEDED",
    "DETOUR",
    "QA_ENTER",
    "QA_EXIT",
    "DRAFT_SEND",
    "STATE_SNAPSHOT",
]

Lane = Literal["step", "gate", "db", "entity", "detour", "qa", "draft"]

LANE_BY_KIND: Dict[TraceKind, Lane] = {
    "STEP_ENTER": "step",
    "STEP_EXIT": "step",
    "DRAFT_SEND": "draft",
    "STATE_SNAPSHOT": "step",
    "GATE_PASS": "gate",
    "GATE_FAIL": "gate",
    "DB_READ": "db",
    "DB_WRITE": "db",
    "ENTITY_CAPTURE": "entity",
    "ENTITY_SUPERSEDED": "entity",
    "DETOUR": "detour",
    "QA_ENTER": "qa",
    "QA_EXIT": "qa",
}


@dataclass
class TraceEvent:
    thread_id: str
    ts: float
    kind: TraceKind
    lane: Lane
    step: Optional[str] = None
    detail: Optional[str] = None
    subject: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    loop: bool = False
    detour_to_step: Optional[int] = None
    wait_state: Optional[str] = None


class TraceBus:
    def __init__(self, max_events: int = 2000) -> None:
        self._buf: Dict[str, List[TraceEvent]] = {}
        self._lock = threading.Lock()
        self._max = max_events

    def emit(self, ev: TraceEvent) -> None:
        with self._lock:
            buf = self._buf.setdefault(ev.thread_id, [])
            buf.append(ev)
            if len(buf) > self._max:
                del buf[: len(buf) - self._max]

    def get(self, thread_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(ev) for ev in self._buf.get(thread_id, [])]


BUS = TraceBus()


def emit(
    thread_id: str,
    kind: TraceKind,
    *,
    step: Optional[str] = None,
    detail: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    subject: Optional[str] = None,
    status: Optional[str] = None,
    summary: Optional[str] = None,
    lane: Optional[Lane] = None,
    loop: bool = False,
    detour_to_step: Optional[int] = None,
    wait_state: Optional[str] = None,
) -> None:
    if not is_trace_enabled():
        return
    lane_value = lane or LANE_BY_KIND[kind]
    details = dict(data or {})
    summary_text = summary or _derive_summary(kind, step, detail, subject, status, details)
    event = TraceEvent(
        thread_id=thread_id,
        ts=time.time(),
        kind=kind,
        lane=lane_value,
        step=step,
        detail=detail,
        subject=subject,
        status=status,
        summary=summary_text,
        details=details,
        data=details,
        loop=loop,
        detour_to_step=detour_to_step,
        wait_state=wait_state,
    )
    BUS.emit(event)
    try:
        from . import timeline  # pylint: disable=import-outside-toplevel

        timeline.append(thread_id, asdict(event))
    except Exception:
        pass


def _derive_summary(
    kind: TraceKind,
    step: Optional[str],
    detail: Optional[str],
    subject: Optional[str],
    status: Optional[str],
    payload: Dict[str, Any],
) -> Optional[str]:
    """Generate a compact summary line for the timeline table."""

    if subject:
        value = payload.get("value")
        if value is None and "summary" in payload:
            value = payload.get("summary")
        if value is not None:
            return f"{subject}={_stringify(value)}"

    if kind in {"DB_READ", "DB_WRITE"}:
        target = detail or step or payload.get("resource") or "db"
        action = "READ" if kind == "DB_READ" else "WRITE"
        return f"{action} {target}"

    if kind in {"GATE_PASS", "GATE_FAIL"}:
        label = detail or step or subject or "gate"
        verdict = status or ("pass" if kind == "GATE_PASS" else "fail")
        return f"{label}: {verdict}"

    if kind == "DETOUR":
        return detail or payload.get("reason") or "detour"

    if kind == "DRAFT_SEND":
        footer = payload.get("footer") or {}
        step_label = footer.get("step") or step or "Draft"
        next_step = footer.get("next")
        state = footer.get("wait_state")
        pieces = [step_label]
        if next_step:
            pieces.append(f"→ {next_step}")
        if state:
            pieces.append(state)
        return " · ".join(pieces)

    if payload.get("summary"):
        return str(payload["summary"])

    if detail:
        return detail
    if step:
        return step
    return None


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        text = str(value)
    else:
        text = str(value)
    if len(text) > 80:
        return f"{text[:77]}…"
    return text


__all__ = [
    "TraceEvent",
    "TraceBus",
    "TraceKind",
    "Lane",
    "LANE_BY_KIND",
    "BUS",
    "emit",
]
