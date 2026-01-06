"""Quick smoke run for intake routing behaviour."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from backend.workflow_email import process_msg


def _msg(body: str, mid: str) -> Dict[str, Any]:
    return {
        "msg_id": mid,
        "from_name": "Smoke",
        "from_email": "smoke@example.com",
        "subject": "Smoke Probe",
        "ts": "2025-05-01T09:00:00Z",
        "body": body,
    }


def _run_case(label: str, body: str) -> None:
    db_path = Path("artifacts") / f"manual_smoke_{label}.json"
    db_path.unlink(missing_ok=True)
    result = process_msg(_msg(body, label.upper()), db_path=db_path)
    draft = (result.get("draft_messages") or [{}])[-1]
    print(
        f"{label}: action={result.get('action')} step={result.get('current_step')} "
        f"topic={draft.get('topic')} conf={result.get('confidence')}"
    )


def main() -> None:
    Path("artifacts").mkdir(exist_ok=True)
    _run_case(
        "free_form",
        "We'd like a one-day conference for ~35 ppl around the 15th of June. Room B if free.",
    )
    _run_case(
        "iso_date",
        "Event request for 35 participants on 2025-06-15 in Room B. Please confirm availability.",
    )


if __name__ == "__main__":
    main()
