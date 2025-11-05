from __future__ import annotations

import threading
from typing import Any, Dict


class _StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}

    def update(self, thread_id: str, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            self._data[thread_id] = dict(snapshot)

    def get(self, thread_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data.get(thread_id, {}))


STATE_STORE = _StateStore()


__all__ = ["STATE_STORE"]
