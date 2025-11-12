from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class _InMemoryStateStore:
    """Thread-safe container for workflow debug snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: Dict[str, Dict[str, Any]] = {}

    def get(self, thread_id: Optional[str]) -> Dict[str, Any]:
        if not thread_id:
            return {}
        key = str(thread_id)
        with self._lock:
            snapshot = self._payload.get(key)
            return dict(snapshot) if isinstance(snapshot, dict) else {}

    def update(self, thread_id: Optional[str], payload: Dict[str, Any]) -> None:
        if not thread_id or not isinstance(payload, dict):
            return
        key = str(thread_id)
        with self._lock:
            existing = self._payload.get(key, {})
            merged = dict(existing)
            merged.update(payload)
            self._payload[key] = merged

    def clear(self, thread_id: Optional[str] = None) -> None:
        with self._lock:
            if thread_id is None:
                self._payload.clear()
            else:
                self._payload.pop(str(thread_id), None)


STATE_STORE = _InMemoryStateStore()

__all__ = ["STATE_STORE"]
