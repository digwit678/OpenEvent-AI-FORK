from __future__ import annotations

import importlib
from typing import Any

from fastapi.testclient import TestClient


def _reload_main() -> Any:
    module = importlib.import_module("backend.main")
    return importlib.reload(module)


def test_trace_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DEBUG_TRACE", raising=False)
    monkeypatch.delenv("DEBUG_TRACE_DEFAULT", raising=False)

    main = _reload_main()
    client = TestClient(main.app)

    response = client.get("/api/debug/threads/any-thread")
    assert response.status_code == 200

    timeline_response = client.get("/api/debug/threads/any-thread/timeline")
    assert timeline_response.status_code == 200

    text_response = client.get("/api/debug/threads/any-thread/timeline/text")
    assert text_response.status_code == 200
    assert "No trace events" in text_response.text


def test_trace_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DEBUG_TRACE", "0")

    main = _reload_main()
    client = TestClient(main.app)

    response = client.get("/api/debug/threads/any-thread")
    assert response.status_code == 404

    timeline_response = client.get("/api/debug/threads/any-thread/timeline")
    assert timeline_response.status_code == 404

    text_response = client.get("/api/debug/threads/any-thread/timeline/text")
    assert text_response.status_code == 404
