from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from workflows.io.database import append_audit_entry, update_event_metadata


def _tmp_log_path(name: str) -> Path:
    """Return the log path for a given live scenario (ensures directory exists)."""

    root = Path("tmp-integration")
    root.mkdir(exist_ok=True)
    return root / f"e2e-live-{name}.jsonl"


def dump_turn(path: Path, payload: Dict[str, Any]) -> None:
    """Append a JSON payload representing a turn to the artifact file."""

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def assert_buttons(payload: Dict[str, Any], rendered: bool, enabled: bool) -> None:
    """Assert helper for button state expectations."""

    assert payload.get("buttons_rendered") is rendered, "Unexpected button rendering state"
    assert payload.get("buttons_enabled") is enabled, "Unexpected button enabled state"


def fill_billing(event: Dict[str, Any], save_db_fn) -> None:
    """Populate billing details with deterministic fixture data."""

    event["billing"] = {
        "name_or_company": "Pixel Forge GmbH",
        "street": "Samplestrasse 1",
        "postal_code": "8000",
        "city": "Zürich",
        "country": "CH",
        "contact": {"email": "ops@pixelforge.ch"},
    }
    save_db_fn()


def approve_room_option(event: Dict[str, Any], save_db_fn) -> None:
    """Simulate manager approval to lock the selected room option."""

    pending = event.get("room_pending_decision") or {}
    selected = pending.get("selected_room")
    if not selected:
        raise AssertionError("Expected a pending room decision to approve.")
    requirements_hash = event.get("requirements_hash") or pending.get("requirements_hash")
    update_event_metadata(
        event,
        locked_room_id=selected,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="In Progress",
    )
    append_audit_entry(event, 3, 4, "room_hil_approved")
    event.pop("room_pending_decision", None)
    save_db_fn()


def ensure_products(event: Dict[str, Any], items: Iterable[Dict[str, Any]], save_db_fn) -> None:
    """Merge the requested products into the event record."""

    catalog = event.setdefault("products", [])
    existing = {entry.get("name", "").lower(): entry for entry in catalog if entry.get("name")}
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if lower in existing:
            existing[lower].update(item)
        else:
            catalog.append(dict(item))
    save_db_fn()
