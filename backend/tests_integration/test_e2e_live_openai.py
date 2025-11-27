from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from backend.workflow_email import load_db, process_msg, save_db
from backend.workflows.common.billing import update_billing_details
from backend.workflows.common.gatekeeper import explain_step7_gate, refresh_gatekeeper
from backend.workflows.llm import adapter as llm_adapter
from backend.utils.openai_key import SECRET_NAME, load_openai_api_key

from .utils_live import (
    _tmp_log_path,
    dump_turn,
    ensure_products,
    fill_billing,
)


# Live invocation (documented for developers):
# export AGENT_MODE=openai
# export OPENAI_API_KEY='sk-REAL-KEY'  # (often sourced from Keychain item 'openevent-api-test-key')
# export OPENAI_AGENT_MODEL=gpt-4o-mini
# export OPENAI_INTENT_MODEL=gpt-4o-mini
# export OPENAI_ENTITY_MODEL=gpt-4o-mini
# export OPENAI_TEST_MODE=1
# export ATOMIC_TURNS=1
# export LEGACY_SHORTCUTS_ALLOWED=0
# export NO_UNSOLICITED_MENUS=true
# export PRODUCT_FLOW_ENABLED=true
# export EVENT_SCOPED_UPSELL=true
# export CAPTURE_BUDGET_ON_HIL=true
# export ALLOW_AUTO_ROOM_LOCK=true
# export DISABLE_MANUAL_REVIEW_FOR_TESTS=true
# export TZ=Europe/Zurich
# export PYTHONPATH="$(pwd)"
# pytest backend/tests_integration/test_e2e_live_openai.py -m integration -q -rA -vv

_API_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_=")


def _looks_like_real_api_key(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    trimmed = value.strip()
    if len(trimmed) < 40:
        return False
    if " " in trimmed:
        return False
    if trimmed.endswith("..."):
        return False
    if not trimmed.startswith("sk-"):
        return False
    if trimmed.lower().startswith("sk-proj-") and len(trimmed) < 45:
        return False
    if any(ch not in _API_KEY_CHARS for ch in trimmed):
        return False
    return True


def _require_live_env() -> None:
    errors = []
    agent_mode = os.getenv("AGENT_MODE")
    if agent_mode != "openai":
        errors.append(f"AGENT_MODE must be 'openai' (got {agent_mode!r})")
    api_key = load_openai_api_key(required=False)
    if not _looks_like_real_api_key(api_key):
        safe_preview = (api_key or "").strip()[:8]
        errors.append(f"{SECRET_NAME} appears invalid (preview: {safe_preview!r})")
    if os.getenv("OPENAI_TEST_MODE") != "1":
        errors.append("OPENAI_TEST_MODE must be '1' for deterministic live tests")
    if errors:
        raise AssertionError("Live OpenAI test misconfigured: " + "; ".join(errors))


_require_live_env()


@dataclass
class LiveContext:
    db_path: Path
    log_path: Path
    turn_id: int = 0
    history: List[Tuple[str, str]] = None

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

    def append_history(self, role: str, content: str) -> None:
        self.history.append((role, content))
        if len(self.history) > 4:
            self.history = self.history[-4:]


@pytest.fixture()
def live_ctx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LiveContext:
    monkeypatch.setenv("AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_TEST_MODE", "1")
    monkeypatch.setenv("OPENAI_AGENT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_INTENT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_ENTITY_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("DRY_RUN_EMAILS", "true")
    monkeypatch.setenv("PAYMENTS_DRY_RUN", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("DISABLE_MANUAL_REVIEW_FOR_TESTS", "true")
    monkeypatch.setenv("TZ", "Europe/Zurich")
    monkeypatch.delenv("SMART_SHORTCUTS", raising=False)
    llm_adapter.reset_llm_adapter()

    db_path = tmp_path / "live-openai.json"
    log_path = _tmp_log_path("happy-path")
    if log_path.exists():
        log_path.unlink()

    return LiveContext(db_path=db_path, log_path=log_path)


def _log_turn(ctx: LiveContext, *, role: str, content: str, telemetry: Optional[Dict[str, Any]] = None) -> None:
    ctx.turn_id += 1
    ctx.append_history(role, content)
    telemetry = telemetry or {}
    gatekeeper = telemetry.get("gatekeeper_passed")
    gatekeeper_repr = "n/a"
    if isinstance(gatekeeper, dict):
        gatekeeper_repr = json.dumps(gatekeeper, sort_keys=True)
    elif gatekeeper is not None:
        gatekeeper_repr = str(gatekeeper)
    menus_raw = telemetry.get("menus_included", "false")
    menus_included = str(menus_raw).lower() == "true"
    payload = {
        "turn_id": ctx.turn_id,
        "role": role,
        "content": content,
        "telemetry": telemetry,
        "gatekeeper_passed": gatekeeper_repr,
        "menus_included": menus_included,
        "buttons_rendered": bool(telemetry.get("buttons_rendered", False)),
        "buttons_enabled": bool(telemetry.get("buttons_enabled", False)),
    }
    dump_turn(ctx.log_path, payload)


def _process_message(
    ctx: LiveContext,
    *,
    body: str,
    msg_id: str,
    subject: str = "Workshop at Atelier in November",
) -> Dict[str, Any]:
    _log_turn(ctx, role="user", content=body)
    result = process_msg(
        {
            "msg_id": msg_id,
            "from_name": "Live Test Client",
            "from_email": "integration@example.com",
            "subject": subject,
            "ts": "2025-11-01T09:00:00Z",
            "body": body,
        },
        db_path=ctx.db_path,
    )
    drafts = result.get("draft_messages") or []
    assistant_text = drafts[-1]["body"] if drafts else ""
    telemetry = result.get("telemetry") or {}
    assistant_telemetry = dict(telemetry)
    assistant_telemetry.setdefault("buttons_rendered", bool(result.get("buttons_rendered", False)))
    assistant_telemetry.setdefault("buttons_enabled", bool(result.get("buttons_enabled", False)))
    assistant_telemetry.setdefault("gatekeeper_passed", result.get("gatekeeper_passed"))
    _log_turn(ctx, role="assistant", content=assistant_text, telemetry=assistant_telemetry)
    return result


def _load_event(ctx: LiveContext) -> Dict[str, Any]:
    db = load_db(ctx.db_path)
    assert db["events"], "Expected at least one event entry"
    return db["events"][0]


def _append_failure(ctx: LiveContext, reason: str, details: Dict[str, Any]) -> None:
    payload = {
        "failure": True,
        "reason": reason,
        "last_two_pairs": ctx.history[-4:],
        "full_telemetry": details,
    }
    dump_turn(ctx.log_path, payload)


def _print_transcript_tail(path: Path, limit: int = 50) -> None:
    if not path.exists():
        print(f"[diagnostic] transcript not found at {path}")
        return
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    tail = lines[-limit:]
    print(f"\n[diagnostic] last {len(tail)} lines from {path}:")
    for line in tail:
        print(line.rstrip())


@pytest.mark.integration
def test_happy_path_live_openai(live_ctx: LiveContext) -> None:
    ctx = live_ctx
    failures: List[Tuple[str, Dict[str, Any]]] = []
    assistant_messages: List[str] = []

    def _draft_body(result: Dict[str, Any]) -> str:
        drafts = result.get("draft_messages") or []
        if drafts:
            return drafts[-1].get("body", "") or ""
        return ""

    def _parse_slots(block: str) -> List[str]:
        return [line[2:].strip() for line in block.splitlines() if line.strip().startswith("- ")]

    def _assert_no_manual_review() -> None:
        corpus = " ".join(assistant_messages).lower()
        assert "routed for manual review" not in corpus, "Assistant must not mention manual review routing"

    try:
        first = _process_message(
            ctx,
            msg_id="turn-1",
            body=(
                "We want to confirm an event booking at your Atelier venue for a 15-person design workshop this November. "
                "Please send 3–5 evening options (18:00–22:00) along with a rough price range."
            ),
        )
        first_body = _draft_body(first)
        assistant_messages.append(first_body)
        first_telemetry = first.get("telemetry") or {}
        first_llm = first_telemetry.get("llm") or {}
        assert first_llm.get("adapter") == "openai", f"Expected OpenAI adapter metadata, saw {first_llm}"
        model_descriptor = str(first_llm.get("model") or "")
        assert "gpt-4o-mini" in model_descriptor.lower(), f"Unexpected LLM model metadata: {model_descriptor}"
        assert first_telemetry.get("answered_question_first") is True, "First turn should answer the query before follow-ups"
        menus_flag = str(first_telemetry.get("menus_included", "false")).lower()
        assert menus_flag == "false", f"Menus must be disabled by default; saw {menus_flag}"
        dag_flag = first_telemetry.get("dag_blocked")
        assert dag_flag in (None, "none"), f"DAG should be clear on first turn; saw {dag_flag}"

        first_lines = first_body.splitlines()
        assert first_lines and first_lines[0].startswith("Hello"), "Assistant must greet the client"
        assert any(line.strip() == "AVAILABLE DATES:" for line in first_lines), "Assistant must include AVAILABLE DATES header"
        assert "NEXT STEP:" in first_body, "Assistant must include NEXT STEP guidance on first turn"
        offered_slots = _parse_slots(first_body)
        assert 3 <= len(offered_slots) <= 5, "Expected 3–5 suggested dates"
        for slot in offered_slots:
            assert "18:00" in slot and "22:00" in slot, "Timeslot must include 18:00–22:00 window"

        chosen_slot = offered_slots[1]
        chosen_date, time_block = chosen_slot.split(" ", 1)
        start_time, end_time = [part.strip() for part in time_block.split("–", 1)]

        second = _process_message(
            ctx,
            msg_id="turn-2",
            body=(
                f"Event follow-up: we'll go with the second option ({chosen_date} {time_block}) for our workshop. "
                "Please keep the other dates on standby as backups."
            ),
            subject="Workshop booking follow-up",
        )
        second_body = _draft_body(second)
        assistant_messages.append(second_body)
        assert second["action"] in {
            "room_auto_locked",
            "room_avail_result",
            "date_confirmation",
            "offer_draft_prepared",
            "smart_shortcut_processed",
        }
        event_after_second = _load_event(ctx)
        requested = event_after_second.get("requested_window") or {}
        assert requested.get("date_iso") == chosen_date, "Requested window date mismatch"
        assert requested.get("start_time") == start_time
        assert requested.get("end_time") == end_time
        assert event_after_second.get("locked_room_id") in (None, ""), "Room must not lock before explicit selection"
        current_step = event_after_second.get("current_step") or 0
        assert current_step >= 3, f"Expected to advance into room selection, saw step {current_step}"

        room_body = second_body

        third = _process_message(

            ctx,

            msg_id="turn-3",

            body="Please lock Room B for the confirmed workshop date and hold it for us.",

            subject="Room selection",

        )

        room_body = _draft_body(third)

        assistant_messages.append(room_body)

        assert third["action"] in {

            "room_auto_locked",

            "room_avail_result",

            "offer_draft_prepared",

            "room_lock_retained",

            "smart_shortcut_processed",

        }

        assert "ROOM OPTIONS:" in room_body, "Room response missing ROOM OPTIONS section"
        assert "Room B" in room_body, "Expected Room B to appear in room suggestions"

        room_event = _load_event(ctx)
        assert room_event.get("locked_room_id") == "Room B", "Room B should be locked"
        decision_status = (room_event.get("room_decision") or {}).get("status", "").lower()
        assert decision_status in {"locked", "held"}, f"Unexpected room decision status: {decision_status}"
        assert room_event.get("room_eval_hash") == room_event.get("requirements_hash"), "Room hash mismatch after lock"

        equipment = _process_message(
            ctx,
            msg_id="turn-4",
            body="Event equipment request: please add one projector and two wireless microphones to the booking.",
            subject="Equipment request",
        )
        equipment_body = _draft_body(equipment)
        assistant_messages.append(equipment_body)
        assert equipment["action"] in {
            "offer_draft_prepared",
            "negotiation_detail_updated",
            "room_lock_retained",
            "smart_shortcut_processed",
        }

        product_snapshot = load_db(ctx.db_path)
        assert product_snapshot["events"], "Expected event during product update"
        ensure_products(
            product_snapshot["events"][0],
            [
                {"name": "Projector", "quantity": 1, "unit_price": 0.0},
                {"name": "Wireless Microphone", "quantity": 2, "unit_price": 0.0},
            ],
            lambda: save_db(product_snapshot, ctx.db_path),
        )
        post_products_event = _load_event(ctx)
        assert post_products_event.get("locked_room_id") == "Room B", "Room lock lost after product update"

        billing_snapshot = load_db(ctx.db_path)
        assert billing_snapshot["events"], "Expected event before billing fill"
        billing_event = billing_snapshot["events"][0]
        fill_billing(billing_event, lambda: save_db(billing_snapshot, ctx.db_path))
        update_billing_details(billing_event)
        save_db(billing_snapshot, ctx.db_path)

        billing = _process_message(
            ctx,
            msg_id="turn-5",
            body="Event billing update: use Pixel Forge GmbH, Samplestrasse 1, 8000 Zürich, ops@pixelforge.ch.",
            subject="Billing update",
        )
        billing_body = _draft_body(billing)
        assistant_messages.append(billing_body)
        assert billing["action"] in {
            "offer_draft_prepared",
            "negotiation_detail_updated",
            "room_lock_retained",
            "smart_shortcut_processed",
        }

        final_event = _load_event(ctx)
        refresh_gatekeeper(final_event)
        gate_explain = explain_step7_gate(final_event)
        assert gate_explain.get("ready") is True, f"Gatekeeper missing prerequisites: {gate_explain}"
        assert not (gate_explain.get("missing_now") or []), f"Gatekeeper missing fields: {gate_explain.get('missing_now')}"

        final = _process_message(
            ctx,
            msg_id="turn-6",
            body="Event confirmation: everything looks good — please confirm the booking.",
            subject="Event confirmation",
        )
        final_body = _draft_body(final)
        assistant_messages.append(final_body)
        assert final["action"] in {
            "confirmation_finalized",
            "confirmation_draft",
            "confirmation_deposit_requested",
            "smart_shortcut_processed",
            "transition_ready",
        }
        telemetry = final.get("telemetry") or {}
        assert telemetry.get("buttons_rendered") is True, "Buttons should be rendered at confirmation"
        assert telemetry.get("buttons_enabled") is True, "Buttons should be enabled at confirmation"
        assert telemetry.get("final_action") == "accepted", "Expected final_action to be 'accepted'"
        llm_meta = telemetry.get("llm") or {}
        assert llm_meta.get("adapter") == "openai", f"Unexpected LLM adapter: {llm_meta}"
        assert "gpt-4o-mini" in str(llm_meta.get("model")), f"Unexpected LLM model: {llm_meta}"
        gate_payload = telemetry.get("gatekeeper_explain") or final.get("gatekeeper_explain") or gate_explain
        assert gate_payload.get("ready") is True, "Gatekeeper must mark ready on final payload"
        assert not (gate_payload.get("missing_now") or []), "Gatekeeper should not report missing fields"

        assert not any("menu" in message.lower() for message in assistant_messages), "Assistant must not include menus unless requested"
        _assert_no_manual_review()
    except AssertionError as exc:  # pragma: no cover - diagnostic logging
        failures.append((str(exc), {"assistant_messages": list(assistant_messages), "turn_id": ctx.turn_id}))
        _print_transcript_tail(ctx.log_path)
        raise AssertionError(f"{exc} (see transcript at {ctx.log_path})") from exc
    except Exception as exc:  # pragma: no cover - diagnostic logging
        failures.append((str(exc), {"assistant_messages": list(assistant_messages), "turn_id": ctx.turn_id}))
        _print_transcript_tail(ctx.log_path)
        raise AssertionError(f"Unexpected error: {exc} (see transcript at {ctx.log_path})") from exc
    finally:
        for reason, details in failures:
            _append_failure(ctx, reason, details)
