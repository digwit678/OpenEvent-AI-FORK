from __future__ import annotations

from typing import Any, Dict

from .settings import is_trace_enabled

def close_if_ended(thread_id: str, state: Dict[str, Any]) -> None:
    if not is_trace_enabled():
        return
    if not state:
        return
    thread_state = state.get("thread_state") or state.get("threadState")
    if isinstance(thread_state, str) and thread_state.lower() == "closed":
        try:
            from . import timeline  # pylint: disable=import-outside-toplevel

            timeline.mark_closed(thread_id, "Closed")
        except Exception:
            pass


__all__ = ["close_if_ended"]