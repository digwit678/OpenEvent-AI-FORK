"""Measure Step-4 offer performance with warm caches."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict

import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.utils.runtime import reset_runtime_state
from backend.workflow_email import process_msg


def _configure_stub(mapping: Dict[str, Dict[str, Any]]) -> None:
    from backend.workflows.llm import adapter as llm_adapter

    agent = llm_adapter.adapter

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    if hasattr(agent, "extract_user_information"):
        agent.extract_user_information = fake_extract  # type: ignore[attr-defined]
    else:
        agent.extract_entities = fake_extract  # type: ignore[attr-defined]


def _message(body: str, *, msg_id: str, subject: str = "Event request") -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Test Client",
        "from_email": "client@example.com",
        "subject": subject,
        "ts": "2025-01-01T09:00:00Z",
        "body": body,
    }


def _run_flow(db_path: Path, mapping: Dict[str, Dict[str, Any]]) -> None:
    def send(msg_id: str, body: str, *, info: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if info is not None:
            mapping[msg_id] = info
        return process_msg(_message(body, msg_id=msg_id), db_path=db_path)

    res1 = send(
        "lead",
        "Hello, we need a room for 20 people.",
        info={"date": "2025-09-10", "participants": 20, "room": "Room A"},
    )
    print(f"  Lead intake → action={res1.get('action')} step={res1.get('current_step')}")

    mapping["hil-room"] = {"hil_approve_step": 3}
    res2 = send("hil-room", "HIL approval for room", info={"hil_approve_step": 3})
    print(f"  Room approval → action={res2.get('action')} step={res2.get('current_step')}")

    res3 = send(
        "add-products",
        "Could you add a lunch menu as well?",
        info={"products_add": [{"name": "Lunch Menu", "quantity": 20, "unit_price": 45.0}]},
    )
    print(f"  Offer update → action={res3.get('action')} step={res3.get('current_step')}")


def main() -> None:
    os.environ.setdefault("AGENT_MODE", "stub")
    reset_runtime_state()

    with TemporaryDirectory() as tmp:
        for run in range(2):
            print(f"\n=== Offer flow run {run + 1} ===")
            mapping: Dict[str, Dict[str, Any]] = {}
            _configure_stub(mapping)
            db_path = Path(tmp) / f"measure_offer_{run + 1}.json"
            if db_path.exists():
                db_path.unlink()
            _run_flow(db_path, mapping)


if __name__ == "__main__":
    main()
