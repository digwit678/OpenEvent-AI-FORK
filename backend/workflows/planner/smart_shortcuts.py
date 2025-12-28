from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
import logging

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.datetime_parse import build_window_iso
import importlib
from backend.workflows.steps.step1_intake.condition.checks import suggest_dates

date_process_module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.process")
ConfirmationWindow = getattr(date_process_module, "ConfirmationWindow")
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.services.products import normalise_product_payload

# Import from extracted modules and re-export for compatibility
from backend.workflows.planner.shortcuts_flags import (
    _flag_enabled,
    _max_combined,
    _legacy_shortcuts_allowed,
    _needs_input_priority,
    _product_flow_enabled,
    _capture_budget_on_hil,
    _no_unsolicited_menus,
    _event_scoped_upsell_enabled,
    _budget_default_currency,
    _budget_parse_strict,
    _max_missing_items_per_hil,
    atomic_turns_enabled,
    shortcut_allow_date_room,
)
from backend.workflows.planner.shortcuts_gate import (
    _shortcuts_allowed,
    _coerce_participants,
    _debug_shortcut_gate,
)
from backend.workflows.planner.shortcuts_types import (
    ParsedIntent,
    PlannerTelemetry,
    AtomicDecision,
    PlannerResult,
    _PREASK_CLASS_COPY,
    _CLASS_KEYWORDS,
    _ORDINAL_WORDS_BY_LANG,
)

# S3: Import extracted handler modules
from backend.workflows.planner.budget_parser import (
    extract_budget_info as _extract_budget_info_impl,
    parse_budget_value as _parse_budget_value_impl,
    parse_budget_text as _parse_budget_text_impl,
)
from backend.workflows.planner.dag_guard import (
    dag_guard as _dag_guard_impl,
    is_date_confirmed as _is_date_confirmed_impl,
    is_room_locked as _is_room_locked_impl,
    can_collect_billing as _can_collect_billing_impl,
    set_dag_block as _set_dag_block_impl,
    ensure_prerequisite_prompt as _ensure_prerequisite_prompt_impl,
)
from backend.workflows.planner.date_handler import (
    normalize_time as _normalize_time_impl,
    time_from_iso as _time_from_iso_impl,
    window_to_payload as _window_to_payload_impl,
    window_from_payload as _window_from_payload_impl,
    infer_times_for_date as _infer_times_for_date_impl,
    preferred_date_slot as _preferred_date_slot_impl,
    candidate_date_options as _candidate_date_options_impl,
    maybe_emit_date_options_answer as _maybe_emit_date_options_answer_impl,
    resolve_window_from_module as _resolve_window_from_module_impl,
    manual_window_from_user_info as _manual_window_from_user_info_impl,
    parse_date_intent as _parse_date_intent_impl,
    ensure_date_choice_intent as _ensure_date_choice_intent_impl,
    apply_date_confirmation as _apply_date_confirmation_impl,
    should_execute_date_room_combo as _should_execute_date_room_combo_impl,
    execute_date_room_combo as _execute_date_room_combo_impl,
)
from backend.workflows.planner.product_handler import (
    format_money as _format_money_impl,
    missing_item_display as _missing_item_display_impl,
    products_state as _products_state_impl,
    product_lookup as _product_lookup_impl,
    normalise_products as _normalise_products_impl,
    current_participant_count as _current_participant_count_impl,
    infer_quantity as _infer_quantity_impl,
    format_product_line as _format_product_line_impl,
    product_subtotal_lines as _product_subtotal_lines_impl,
    build_product_confirmation_lines as _build_product_confirmation_lines_impl,
    parse_product_intent as _parse_product_intent_impl,
    apply_product_add as _apply_product_add_impl,
    load_catering_names as _load_catering_names_impl,
)
from backend.workflows.planner.choice_handler import (
    load_choice_context as _load_choice_context_impl,
    maybe_handle_choice_context_reply as _maybe_handle_choice_context_reply_impl,
    parse_choice_selection as _parse_choice_selection_impl,
    choice_clarification_prompt as _choice_clarification_prompt_impl,
    format_choice_item as _format_choice_item_impl,
    apply_choice_selection as _apply_choice_selection_impl,
    complete_choice_selection as _complete_choice_selection_impl,
    handle_choice_selection as _handle_choice_selection_impl,
)
from backend.workflows.planner.preask_handler import (
    preask_feature_enabled as _preask_feature_enabled_impl,
    menu_preview_lines as _menu_preview_lines_impl,
    explicit_menu_requested as _explicit_menu_requested_impl,
    process_preask as _process_preask_impl,
    maybe_emit_preask_prompt_only as _maybe_emit_preask_prompt_only_impl,
    handle_preask_responses as _handle_preask_responses_impl,
    detect_preask_response as _detect_preask_response_impl,
    single_pending_class as _single_pending_class_impl,
    prepare_preview_for_requests as _prepare_preview_for_requests_impl,
    hydrate_preview_from_context as _hydrate_preview_from_context_impl,
    build_preview_for_class as _build_preview_for_class_impl,
    maybe_preask_lines as _maybe_preask_lines_impl,
    finalize_preask_state as _finalize_preask_state_impl,
)

# Re-export gate function for tests that import it directly
_shortcuts_allowed = _shortcuts_allowed  # noqa: F811 - intentional re-export

logger = logging.getLogger(__name__)


# NOTE: Constants and dataclasses (ParsedIntent, PlannerTelemetry, AtomicDecision,
# PlannerResult, _PREASK_CLASS_COPY, _CLASS_KEYWORDS, _ORDINAL_WORDS_BY_LANG)
# are now imported from shortcuts_types.py (see imports at top of file)


class AtomicTurnPolicy:
    def __init__(self) -> None:
        self.atomic_turns = atomic_turns_enabled()
        self.allow_date_room = shortcut_allow_date_room()

    def decide(self, planner: "_ShortcutPlanner") -> AtomicDecision:
        if not self.atomic_turns:
            return AtomicDecision(execute=list(planner.verifiable), deferred=[])

        verifiable = list(planner.verifiable)
        decision = AtomicDecision(execute=[], deferred=[], use_combo=False, shortcut_path_used="none")

        date_intent = next((intent for intent in verifiable if intent.type == "date_confirmation"), None)
        room_intent = next((intent for intent in verifiable if intent.type == "room_selection"), None)

        if (
            self.allow_date_room
            and date_intent
            and room_intent
            and planner._should_execute_date_room_combo()
        ):
            decision.execute = [date_intent, room_intent]
            decision.use_combo = True
            decision.shortcut_path_used = "date+room"
            for intent in verifiable:
                if intent not in decision.execute:
                    decision.deferred.append((intent, "combined_limit_reached"))
            return decision

        if verifiable:
            primary = verifiable[0]
            decision.execute = [primary]
            for intent in verifiable[1:]:
                decision.deferred.append((intent, "combined_limit_reached"))

        return decision


# NOTE: PlannerResult is now imported from shortcuts_types.py


# Planner execution ------------------------------------------------------------


def maybe_run_smart_shortcuts(state: WorkflowState) -> Optional[GroupResult]:
    policy = AtomicTurnPolicy()
    if policy.atomic_turns:
        state.telemetry.atomic_default = True
    if not _flag_enabled():
        return None
    event_entry = state.event_entry
    if not event_entry:
        return None
    if not _shortcuts_allowed(event_entry):
        _debug_shortcut_gate("blocked", event_entry, state.user_info)
        return None
    _debug_shortcut_gate("allowed", event_entry, state.user_info)

    planner = _ShortcutPlanner(state, policy)
    result = planner.handle_lightweight_turn()
    if result is None:
        result = planner.run()
    if not result:
        return None

    # Replace draft messages with the planner-composed reply.
    state.draft_messages.clear()
    state.draft_messages.append(
        {
            "body": result["message"],
            "step": event_entry.get("current_step") or state.current_step or 2,
            "topic": "smart_shortcut_combined_confirmation",
            "requires_approval": True,
        }
    )
    state.extras["persist"] = True
    state.extras["subloop"] = "shortcut"
    return GroupResult(action="smart_shortcut_processed", payload=result.merged())


# NOTE: _shortcuts_allowed, _coerce_participants, _debug_shortcut_gate
# are now imported from shortcuts_gate.py (see imports at top of file)


class _ShortcutPlanner:
    def __init__(self, state: WorkflowState, policy: Optional[AtomicTurnPolicy] = None):
        self.state = state
        self.event = state.event_entry or {}
        self.user_info = state.user_info or {}
        self.verifiable: List[ParsedIntent] = []
        self.needs_input: List[ParsedIntent] = []
        self.telemetry = PlannerTelemetry()
        self.summary_lines: List[str] = []
        self.pending_items: List[Dict[str, Any]] = []
        self.initial_snapshot = self._snapshot_event()
        self.policy = policy or AtomicTurnPolicy()
        self.legacy_allowed = _legacy_shortcuts_allowed()
        self.max_combined = _max_combined() if self.legacy_allowed else 1
        self.telemetry.shortcut_path_used = "none"
        self.telemetry.legacy_shortcut_invocations = 0
        if self.policy.atomic_turns:
            self.telemetry.atomic_default = True
        self.priority_order = _needs_input_priority()
        seen: set[str] = set()
        ordered: List[str] = []
        for item in self.priority_order + ["date_choice"]:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        self.priority_order = ordered
        if "budget" not in self.priority_order:
            self.priority_order.append("budget")
        if "offer_hil" not in self.priority_order:
            insert_pos = self.priority_order.index("budget") if "budget" in self.priority_order else len(self.priority_order)
            self.priority_order.insert(insert_pos, "offer_hil")
        if "product_followup" not in self.priority_order:
            self.priority_order.append("product_followup")
        self.pending_product_additions: List[Dict[str, Any]] = []
        self.pending_missing_products: List[Dict[str, Any]] = []
        self.menu_requested = self._explicit_menu_requested()
        self.room_checked_initial = bool(self.event.get("locked_room_id"))
        self.room_checked = self.room_checked_initial
        self.product_line_details: List[Dict[str, Any]] = []
        self.product_currency_totals: Dict[str, float] = {}
        self.product_price_missing = False
        self.budget_info = self._extract_budget_info()
        if self.budget_info:
            self.telemetry.budget_provided = True
        self.telemetry.menus_included = "false"
        self.telemetry.menus_phase = "none"
        self.telemetry.dag_blocked = "none"
        self.state.telemetry.dag_blocked = "none"
        self.telemetry.room_checked = self.room_checked
        self.products_state = self._products_state()
        self.preask_pending_state: Dict[str, bool] = dict(self.products_state.get("preask_pending") or {})
        self.presented_interest: Dict[str, str] = self.products_state.setdefault("presented_interest", {})
        self.manager_items_by_class = self._group_manager_items()
        self._sync_manager_catalog_signature()
        self.preview_requests: List[Tuple[str, int]] = []
        self.preask_clarifications: List[str] = []
        self.choice_context = self._load_choice_context()
        self.preview_lines: List[str] = []
        self.preview_class: Optional[str] = None
        self._choice_context_handled = False
        self._parsed = False
        self.preask_ack_lines: List[str] = []
        self._dag_block_reason: str = "none"

    def _greeting_line(self) -> str:
        profile = (self.state.client or {}).get("profile", {}) if self.state.client else {}
        raw_name = profile.get("name") or self.state.message.from_name
        if raw_name:
            token = str(raw_name).strip().split()
            if token:
                first = token[0].strip(",. ")
                if first:
                    return f"Hello {first},"
        return "Hello,"

    def _with_greeting(self, body: str) -> str:
        greeting = self._greeting_line()
        if not body:
            return greeting
        if body.startswith(greeting):
            return body
        return f"{greeting}\n\n{body}"

    def handle_lightweight_turn(self) -> Optional[PlannerResult]:
        choice_context_result = self._maybe_handle_choice_context_reply()
        if choice_context_result:
            return choice_context_result

        self._ensure_intents_prepared()

        if not self.verifiable and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                self.telemetry.answered_question_first = True
                return self._build_payload("\u200b")

        if self.preask_ack_lines and not self.verifiable and not self.needs_input:
            ack_message = "\n".join(self.preask_ack_lines).strip()
            self.preask_ack_lines.clear()
            self.telemetry.answered_question_first = True
            return self._build_payload(ack_message or "\u200b")

        date_answer = self._maybe_emit_date_options_answer()
        if date_answer:
            return date_answer

        if not self.verifiable and len(self.needs_input) == 1:
            follow_up = self._maybe_emit_single_followup()
            if follow_up:
                return follow_up

        return None

    def run(self) -> Optional[PlannerResult]:
        if not self._choice_context_handled:
            choice_context_result = self._maybe_handle_choice_context_reply()
            if choice_context_result:
                return choice_context_result

        self._ensure_intents_prepared()

        if not self.verifiable and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                return self._build_payload("\u200b")

        executed_count = 0
        combine_executed = False

        date_answer = self._maybe_emit_date_options_answer()
        if date_answer:
            return date_answer

        if self.policy.atomic_turns:
            decision = self.policy.decide(self)
            self.telemetry.shortcut_path_used = decision.shortcut_path_used
            if decision.use_combo:
                combine_executed = self._execute_date_room_combo()
                if combine_executed:
                    executed_count = 2
                else:
                    decision.use_combo = False
                    self.telemetry.shortcut_path_used = "none"
            if not decision.use_combo:
                for intent in decision.execute:
                    allowed, guard_reason = self._dag_guard(intent)
                    if not allowed:
                        self._set_dag_block(guard_reason)
                        self._ensure_prerequisite_prompt(guard_reason, intent)
                        self._defer_intent(intent, guard_reason or "dag_blocked")
                        continue
                    if self._execute_intent(intent):
                        executed_count += 1
                    else:
                        self._defer_intent(intent, "not_executable_now")
            for intent, reason in decision.deferred:
                allowed, guard_reason = self._dag_guard(intent)
                final_reason = guard_reason or reason or "not_executable_now"
                if guard_reason:
                    self._set_dag_block(guard_reason)
                    self._ensure_prerequisite_prompt(guard_reason, intent)
                self._defer_intent(intent, final_reason)
            self.telemetry.legacy_shortcut_invocations = 1 if decision.use_combo else 0
        else:
            if not self.legacy_allowed and self._should_execute_date_room_combo():
                combine_executed = self._execute_date_room_combo()
                if combine_executed:
                    executed_count = 2
                    remaining = [i for i in self.verifiable if i.type not in {"date_confirmation", "room_selection"}]
                    for intent in remaining:
                        self._defer_intent(intent, "combined_limit_reached")
                    self.verifiable = []
                    self.telemetry.shortcut_path_used = "date+room"
                    self.telemetry.legacy_shortcut_invocations = max(0, executed_count - 1)
            if not combine_executed and self.verifiable:
                combined_limit = max(1, min(self.max_combined, len(self.verifiable)))
                for intent in self.verifiable:
                    allowed, guard_reason = self._dag_guard(intent)
                    if not allowed:
                        self._set_dag_block(guard_reason)
                        self._ensure_prerequisite_prompt(guard_reason, intent)
                        self._defer_intent(intent, guard_reason or "dag_blocked")
                        continue
                    if executed_count >= combined_limit:
                        self._defer_intent(intent, "combined_limit_reached")
                        continue
                    handled = self._execute_intent(intent)
                    if handled:
                        executed_count += 1
                    else:
                        self._defer_intent(intent, "not_executable_now")
            if not combine_executed:
                if "date_confirmation" in self.telemetry.executed_intents and "room_selection" in self.telemetry.executed_intents:
                    self.telemetry.shortcut_path_used = "date+room"
                else:
                    self.telemetry.shortcut_path_used = "none"
                if self.legacy_allowed:
                    self.telemetry.legacy_shortcut_invocations = max(0, executed_count - 1)
                else:
                    self.telemetry.legacy_shortcut_invocations = 0

        if executed_count == 0 and len(self.needs_input) == 1:
            follow_up = self._maybe_emit_single_followup()
            if follow_up:
                return follow_up

        if executed_count == 0 and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                return self._build_payload("\u200b")
            if not self.preview_lines:
                return None

        if combine_executed:
            self.telemetry.combined_confirmation = True
        else:
            self.telemetry.combined_confirmation = bool(self.summary_lines or self.product_line_details)
            if not self.policy.atomic_turns and self.telemetry.shortcut_path_used != "date+room":
                self.telemetry.shortcut_path_used = "none"
        next_question = self._select_next_question()
        if next_question is None:
            if self.policy.atomic_turns:
                next_question = self._default_next_question()
            else:
                fallback = self._default_next_question()
                if fallback and fallback.get("intent") == "offer_prepare" and self._is_room_locked():
                    next_question = fallback
        self.telemetry.needs_input_next = next_question["intent"] if next_question else None
        message = self._compose_message(next_question)
        self.telemetry.room_checked = bool(self.event.get("locked_room_id")) or self.room_checked
        if not self.telemetry.menus_included:
            self.telemetry.menus_included = "false"
        self.telemetry.product_price_missing = bool(self.telemetry.product_price_missing)
        self.telemetry.answered_question_first = True
        self.telemetry.delta_availability_used = False
        if "date_confirmation" in self.telemetry.executed_intents and "room_selection" in self.telemetry.executed_intents:
            self.telemetry.gatekeeper_passed = True
        elif "date_confirmation" in self.telemetry.executed_intents and "room_selection" not in self.telemetry.executed_intents:
            self.telemetry.gatekeeper_passed = False
        if self._dag_block_reason == "none":
            self.telemetry.dag_blocked = "none"
            self.state.telemetry.dag_blocked = "none"

        self._finalize_preask_state()
        self._persist_pending_intents()
        return self._build_payload(message)

    def _ensure_intents_prepared(self) -> None:
        if self._parsed:
            return
        self._process_preask()
        self._parse_intents()
        self._parsed = True

    # --------------------------------------------------------------------- parse
    def _parse_intents(self) -> None:
        self._parse_date_intent()
        self._parse_room_intent()
        self._parse_participants_intent()
        self._parse_billing_intent()
        self._parse_product_intent()
        self._ensure_date_choice_intent()

    # S3: Date intent parsing delegated to date_handler.py
    def _parse_date_intent(self) -> None:
        _parse_date_intent_impl(self)

    def _parse_room_intent(self) -> None:
        room = self.user_info.get("room")
        if not room:
            return

        if self._can_lock_room(room):
            intent = ParsedIntent("room_selection", {"room": room}, verifiable=True)
            self.verifiable.append(intent)
        else:
            self._add_needs_input("availability", {"room": room, "reason": "room_requires_date"}, reason="room_requires_date")

    def _parse_participants_intent(self) -> None:
        participants = self.user_info.get("participants")
        if participants is None:
            return
        if isinstance(participants, (int, float)) or str(participants).isdigit():
            intent = ParsedIntent("participants_update", {"participants": int(participants)}, verifiable=True)
            self.verifiable.append(intent)
        else:
            self._add_needs_input("requirements", {"reason": "participants_unclear"}, reason="participants_unclear")

    def _parse_billing_intent(self) -> None:
        billing = self.user_info.get("billing_address")
        if billing:
            self._add_needs_input("billing", {"billing_address": billing, "reason": "billing_after_offer"}, reason="billing_after_offer")

    # S3: Product intent parsing delegated to product_handler.py
    def _parse_product_intent(self) -> None:
        _parse_product_intent_impl(self)

    def _ensure_date_choice_intent(self) -> None:
        _ensure_date_choice_intent_impl(self)

    # ------------------------------------------------------------------ execute
    # S3: DAG guard methods delegated to dag_guard.py
    def _is_date_confirmed(self) -> bool:
        return _is_date_confirmed_impl(self)

    def _is_room_locked(self) -> bool:
        return _is_room_locked_impl(self)

    def _can_collect_billing(self) -> bool:
        return _can_collect_billing_impl(self)

    def _set_dag_block(self, reason: Optional[str]) -> None:
        _set_dag_block_impl(self, reason)

    def _ensure_prerequisite_prompt(self, reason: Optional[str], intent: Optional[ParsedIntent] = None) -> None:
        _ensure_prerequisite_prompt_impl(self, reason, intent)

    def _dag_guard(self, intent: ParsedIntent) -> Tuple[bool, Optional[str]]:
        return _dag_guard_impl(self, intent)

    # S3: Time utilities delegated to date_handler.py
    def _time_from_iso(self, value: Optional[str]) -> Optional[str]:
        return _time_from_iso_impl(value)

    def _preferred_date_slot(self) -> str:
        return _preferred_date_slot_impl(self)

    def _candidate_date_options(self) -> List[str]:
        return _candidate_date_options_impl(self)

    def _maybe_emit_date_options_answer(self) -> Optional[PlannerResult]:
        return _maybe_emit_date_options_answer_impl(self)

    def _should_execute_date_room_combo(self) -> bool:
        return _should_execute_date_room_combo_impl(self)

    def _execute_date_room_combo(self) -> bool:
        return _execute_date_room_combo_impl(self)

    def _execute_intent(self, intent: ParsedIntent) -> bool:
        if intent.type == "date_confirmation":
            return self._apply_date_confirmation(intent.data["window"])
        if intent.type == "room_selection":
            return self._apply_room_selection(intent.data["room"])
        if intent.type == "participants_update":
            return self._apply_participants_update(intent.data["participants"])
        if intent.type == "product_add":
            return self._apply_product_add(intent.data.get("items") or [])
        return False

    # S3: Date confirmation delegated to date_handler.py
    def _apply_date_confirmation(self, window_payload: Dict[str, Any]) -> bool:
        return _apply_date_confirmation_impl(self, window_payload)

    def _apply_room_selection(self, requested_room: str) -> bool:
        pending = self.event.get("room_pending_decision") or {}
        selected = pending.get("selected_room") or self.event.get("locked_room_id")
        if not selected or selected.lower() != str(requested_room).strip().lower():
            return False
        status = pending.get("selected_status") or "Available"
        requirements_hash_value = pending.get("requirements_hash") or self.event.get("requirements_hash")
        update_event_metadata(
            self.event,
            locked_room_id=selected,
            room_eval_hash=requirements_hash_value,
            current_step=4,
            thread_state="In Progress",
            status="Option",  # Room selected → calendar blocked as Option
        )
        self.event.pop("room_pending_decision", None)
        append_audit_entry(self.event, 3, 4, "room_locked_via_shortcut")
        self.state.current_step = 4
        self.state.extras["persist"] = True
        self.telemetry.executed_intents.append("room_selection")
        self.summary_lines.append(f"• Room locked: {selected} ({status}) → Status: Option")
        self.room_checked = True
        return True

    def _apply_participants_update(self, participants: int) -> bool:
        requirements = dict(self.event.get("requirements") or {})
        requirements["number_of_participants"] = participants
        req_hash = requirements_hash(requirements)
        update_event_metadata(self.event, requirements=requirements, requirements_hash=req_hash)
        self.state.extras["persist"] = True
        self.telemetry.executed_intents.append("participants_update")
        self.summary_lines.append(f"• Headcount updated: {participants} guests")
        return True

    def _apply_product_add(self, items: List[Dict[str, Any]]) -> bool:
        return _apply_product_add_impl(self, items)

    # ------------------------------------------------------------ utilities
    def _snapshot_event(self) -> Dict[str, Any]:
        event = self.event
        return {
            "date": event.get("chosen_date"),
            "locked_room_id": event.get("locked_room_id"),
            "requirements": dict(event.get("requirements") or {}),
            "pending_intents": list(event.get("pending_intents") or []),
        }

    # S3: Window resolution delegated to date_handler.py
    def _resolve_window_from_module(self, preview: bool = False):
        return _resolve_window_from_module_impl(self, preview)

    def _manual_window_from_user_info(self) -> Optional[ConfirmationWindow]:
        return _manual_window_from_user_info_impl(self)

    def _can_lock_room(self, requested_room: str) -> bool:
        pending = self.event.get("room_pending_decision") or {}
        selected = pending.get("selected_room")
        status = pending.get("selected_status")
        if not selected:
            return False
        return selected.lower() == str(requested_room).strip().lower() and status in {"Available", "Option"}

    def _add_needs_input(self, intent_type: str, data: Dict[str, Any], reason: str = "needs_input") -> None:
        self.needs_input.append(ParsedIntent(intent_type, data, verifiable=False, reason=reason))
        payload = {
            "type": intent_type,
            "entities": data,
            "confidence": 0.75,
            "reason_deferred": reason,
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        self.telemetry.deferred.append(payload)
        self.pending_items.append(payload)

    def _select_next_question(self) -> Optional[Dict[str, Any]]:
        if not self.needs_input:
            return None
        priority_map = {intent.type: intent for intent in self.needs_input}
        for candidate in self.priority_order:
            intent = priority_map.get(candidate)
            if intent:
                return {"intent": intent.type, "data": intent.data}
        # Fall back to first deferred.
        intent = self.needs_input[0]
        return {"intent": intent.type, "data": intent.data}

    # S3: Product display methods delegated to product_handler.py
    def _build_product_confirmation_lines(self) -> List[str]:
        return _build_product_confirmation_lines_impl(self)

    def _format_product_line(self, detail: Dict[str, Any]) -> str:
        return _format_product_line_impl(self, detail)

    def _product_subtotal_lines(self) -> List[str]:
        return _product_subtotal_lines_impl(self)

    @staticmethod
    def _format_money(amount: float, currency: str) -> str:
        return _format_money_impl(amount, currency)

    def _compose_addons_section(self) -> Tuple[Optional[str], List[str]]:
        if self.preview_lines:
            phase = "post_room" if self.room_checked else "explicit_request"
            self.telemetry.menus_phase = phase
            self.telemetry.menus_included = "preview"
            if self.preview_class:
                self.telemetry.preview_class_shown = self.preview_class
                if not self.telemetry.preview_items_count:
                    item_count = sum(
                        1 for line in self.preview_lines if line.strip() and line.strip()[0].isdigit()
                    )
                    self.telemetry.preview_items_count = item_count
            return "preview", list(self.preview_lines)
        if not self.room_checked:
            if self.menu_requested:
                self.telemetry.menus_phase = "explicit_request"
            return None, []
        if self.menu_requested:
            preview_lines = self._menu_preview_lines() or []
            if preview_lines:
                self.telemetry.menus_phase = "explicit_request"
                self.telemetry.menus_included = "preview"
                return "explicit", preview_lines
        return None, []

    # S3: Menu preview delegated to preask_handler.py
    def _menu_preview_lines(self) -> Optional[List[str]]:
        return _menu_preview_lines_impl(self)

    def _default_next_question(self) -> Optional[Dict[str, Any]]:
        current = self.event.get("current_step") or 1
        if current >= 4:
            return {"intent": "offer_prepare", "data": {}}
        if current == 3:
            pending = self.event.get("room_pending_decision") or {}
            room = pending.get("selected_room")
            if room:
                return {"intent": "availability", "data": {"room": room}}
        if current <= 2:
            return {"intent": "date_choice", "data": {"reason": "date_missing"}}
        return None

    def _compose_message(self, next_question: Optional[Dict[str, Any]]) -> str:
        lines: List[str] = []
        combined_lines: List[str] = []
        if self.preask_ack_lines:
            lines.extend(self.preask_ack_lines)
            self.preask_ack_lines.clear()
            if lines:
                lines.append("")
        if self.summary_lines:
            combined_lines.extend(self.summary_lines)
        product_lines = self._build_product_confirmation_lines()
        if product_lines:
            if combined_lines and combined_lines[-1] != "":
                combined_lines.append("")
            combined_lines.extend(product_lines)
        if combined_lines:
            lines.append("Combined confirmation:")
            lines.extend(combined_lines)
        if next_question:
            question_text = self._question_for_intent(next_question["intent"], next_question["data"])
            if question_text:
                if lines:
                    lines.append("")
                lines.append("Next question:")
                lines.append(question_text)
        mode, addon_lines = self._compose_addons_section()
        if addon_lines:
            if lines:
                lines.append("")
            lines.append("Add-ons (optional)")
            lines.extend(addon_lines)
        else:
            if mode is None:
                self.telemetry.menus_included = "false"
        preask_lines = self._maybe_preask_lines()
        if preask_lines:
            if lines:
                lines.append("")
            lines.extend(preask_lines)
        return "\n".join(lines).strip()

    def _question_for_intent(self, intent_type: str, data: Dict[str, Any]) -> str:
        if intent_type == "time":
            chosen_date = self.user_info.get("event_date") or format_iso_date_to_ddmmyyyy(self.user_info.get("date"))
            if chosen_date:
                return f"What start and end time should we reserve for {chosen_date}? (e.g., 14:00–18:00)"
            return "What start and end time should we reserve? (e.g., 14:00–18:00)"
        if intent_type == "availability":
            room = data.get("room")
            if room:
                return f"Should I run availability for {room}? Let me know if you’d prefer a different space."
            return "Which room would you like me to check availability for?"
        if intent_type == "site_visit":
            return "Would you like me to propose a few slots for a site visit?"
        if intent_type == "date_choice":
            return "Which date should I check for you? Feel free to share a couple of options."
        if intent_type == "budget":
            currency = _budget_default_currency()
            return f"Could you share a budget cap? For example \"{currency} 60 total\" or \"{currency} 30 per item\"."
        if intent_type == "offer_hil":
            items = data.get("items") or []
            item_names = ", ".join(self._missing_item_display(item) for item in items)
            budget = data.get("budget") or self.budget_info
            currency = (budget or {}).get("currency") or _budget_default_currency()
            if budget:
                budget_text = budget.get("text") or self._format_money(budget.get("amount"), currency)
                return (
                    f"Would you like me to send a request to our manager for {item_names} with budget {budget_text}? "
                    "You'll receive an email once the manager replies."
                )
            if _capture_budget_on_hil():
                return (
                    f"Would you like me to send a request to our manager for {item_names}? "
                    f"If so, let me know a budget cap (e.g., \"{currency} 60 total\" or \"{currency} 30 per item\"). You'll receive an email once the manager replies."
                )
            return (
                f"Would you like me to send a request to our manager for {item_names}? "
                "You'll receive an email once they reply."
            )
        if intent_type == "billing":
            return "Could you confirm the billing address when you’re ready?"
        if intent_type == "offer_prepare":
            return "Should I start drafting the offer next, or is there another detail you'd like me to capture?"
        if intent_type == "product_followup":
            items = data.get("items") or []
            names = ", ".join(item.get("name") or "the item" for item in items) or "the pending item"
            return (
                f"I queued {names} for the next update because we already confirmed two items. "
                "Should I keep that plan, or is there another detail you’d like me to prioritize now?"
            )
        return "Let me know the next detail you’d like me to update."

    def _defer_intent(self, intent: ParsedIntent, reason: str) -> None:
        payload = {
            "type": intent.type,
            "entities": intent.data,
            "confidence": 0.95,
            "reason_deferred": reason,
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        self.telemetry.deferred.append(payload)
        self.pending_items.append(payload)
        if reason == "combined_limit_reached" and intent.type == "product_add":
            self.needs_input.append(ParsedIntent("product_followup", intent.data, verifiable=False, reason=reason))

    def _persist_pending_intents(self) -> None:
        if not self.pending_items:
            return
        existing = list(self.event.get("pending_intents") or [])
        existing.extend(self.pending_items)
        self.event["pending_intents"] = existing
        self.state.extras["persist"] = True

    def _record_telemetry_log(self) -> None:
        logs = self.event.setdefault("logs", [])
        log_entry = self.telemetry.to_log(self.state.message.msg_id, self.event.get("event_id"))
        log_entry["ts"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        log_entry["actor"] = "smart_shortcuts"
        logs.append(log_entry)

    def _group_manager_items(self) -> Dict[str, List[Dict[str, Any]]]:
        items = self.products_state.get("manager_added_items") or []
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for raw in items:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            class_name = str(raw.get("class") or "catering").strip().lower()
            grouped[class_name].append(dict(raw))
        return dict(grouped)

    def _manager_catalog_signature(self) -> List[Tuple[str, str]]:
        signature: List[Tuple[str, str]] = []
        for class_name, items in self.manager_items_by_class.items():
            for item in items:
                signature.append((class_name, str(item.get("name") or "")))
        signature.sort()
        return signature

    def _sync_manager_catalog_signature(self) -> None:
        current_signature = self._manager_catalog_signature()
        previous_raw = self.products_state.get("manager_catalog_signature") or []
        previous_signature = []
        for entry in previous_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            class_name = str(entry[0]).strip().lower()
            name = str(entry[1]).strip()
            previous_signature.append((class_name, name))
        previous_signature.sort()

        previous_map: Dict[str, set[str]] = defaultdict(set)
        for class_name, name in previous_signature:
            previous_map[class_name].add(name)
        current_map: Dict[str, set[str]] = defaultdict(set)
        for class_name, name in current_signature:
            current_map[class_name].add(name)

        changed_classes = {cls for cls in set(previous_map) | set(current_map) if previous_map.get(cls) != current_map.get(cls)}
        for class_name in changed_classes:
            self.presented_interest[class_name] = "unknown"
            self.preask_pending_state.pop(class_name, None)

        normalised_signature = [[cls, name] for cls, name in current_signature]
        should_persist = changed_classes or normalised_signature != previous_raw
        if should_persist:
            self.products_state["manager_catalog_signature"] = normalised_signature
            self.state.extras["persist"] = True

    # S3: Choice context delegated to choice_handler.py
    def _load_choice_context(self) -> Optional[Dict[str, Any]]:
        return _load_choice_context_impl(self)

    # S3: Product state methods delegated to product_handler.py
    def _products_state(self) -> Dict[str, Any]:
        return _products_state_impl(self)

    # S3: Preask methods delegated to preask_handler.py
    def _preask_feature_enabled(self) -> bool:
        return _preask_feature_enabled_impl(self)

    def _process_preask(self) -> None:
        _process_preask_impl(self)

    # S3: Choice reply handling delegated to choice_handler.py
    def _maybe_handle_choice_context_reply(self) -> Optional[PlannerResult]:
        return _maybe_handle_choice_context_reply_impl(self)

    def _choice_clarification_prompt(self, context: Dict[str, Any], text: str) -> Optional[str]:
        return _choice_clarification_prompt_impl(self, context, text)

    def _complete_choice_selection(
        self,
        context: Dict[str, Any],
        selection: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        return _complete_choice_selection_impl(self, context, selection)

    def _format_choice_item(self, item: Dict[str, Any]) -> str:
        return _format_choice_item_impl(self, item)

    def _maybe_emit_preask_prompt_only(self) -> Optional[PlannerResult]:
        return _maybe_emit_preask_prompt_only_impl(self)

    def _maybe_emit_single_followup(self) -> Optional[PlannerResult]:
        if len(self.needs_input) != 1:
            return None
        intent = self.needs_input[0]
        question = self._question_for_intent(intent.type, intent.data)
        if not question:
            return None
        self.telemetry.needs_input_next = intent.type
        self.telemetry.combined_confirmation = False
        self.telemetry.answered_question_first = True
        if not self.telemetry.menus_included:
            self.telemetry.menus_included = "false"
        return self._build_payload(question)

    def _build_payload(self, message: str, state_delta: Optional[Dict[str, Any]] = None) -> PlannerResult:
        message = message.strip()
        if not message:
            message = "\u200b"
        preview_display = self.telemetry.preview_class_shown
        preview_count = self.telemetry.preview_items_count
        self._finalize_preask_state()
        if preview_display and preview_display != "none":
            self.telemetry.preview_class_shown = preview_display
        if preview_count:
            self.telemetry.preview_items_count = preview_count
        self._persist_pending_intents()
        telemetry_snapshot = asdict(self.telemetry)
        payload = {
            "combined_confirmation": self.telemetry.combined_confirmation,
            "executed_intents": list(self.telemetry.executed_intents),
            "needs_input_next": self.telemetry.needs_input_next,
            "deferred_count": len(self.telemetry.deferred),
            "message": message,
            "pending_intents": list(self.pending_items),
            "artifact_match": self.telemetry.artifact_match,
            "added_items": self.telemetry.added_items,
            "missing_items": self.telemetry.missing_items,
            "offered_hil": self.telemetry.offered_hil,
            "hil_request_created": self.telemetry.hil_request_created,
            "budget_provided": self.telemetry.budget_provided,
            "upsell_shown": self.telemetry.upsell_shown,
            "room_checked": self.telemetry.room_checked,
            "menus_included": self.telemetry.menus_included or "false",
            "menus_phase": self.telemetry.menus_phase,
            "product_prices_included": self.telemetry.product_prices_included,
            "product_price_missing": self.telemetry.product_price_missing,
            "gatekeeper_passed": self.telemetry.gatekeeper_passed,
            "answered_question_first": self.telemetry.answered_question_first,
            "delta_availability_used": self.telemetry.delta_availability_used,
            "preask_candidates": list(self.telemetry.preask_candidates or []),
            "preask_shown": list(self.telemetry.preask_shown or []),
            "preask_response": dict(self.telemetry.preask_response or {}),
            "preview_class_shown": self.telemetry.preview_class_shown,
            "preview_items_count": self.telemetry.preview_items_count,
            "choice_context_active": self.telemetry.choice_context_active,
            "selection_method": self.telemetry.selection_method,
            "re_prompt_reason": self.telemetry.re_prompt_reason,
            "legacy_shortcut_invocations": self.telemetry.legacy_shortcut_invocations,
            "shortcut_path_used": self.telemetry.shortcut_path_used,
            "telemetry": telemetry_snapshot,
            "state_delta": state_delta or {},
        }
        self._record_telemetry_log()
        return PlannerResult(payload)
    def _handle_choice_selection(self, text: str) -> None:
        _handle_choice_selection_impl(self, text)

    def _parse_choice_selection(self, context: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        return _parse_choice_selection_impl(self, context, text)

    def _apply_choice_selection(self, context: Dict[str, Any], selection: Dict[str, Any]) -> None:
        _apply_choice_selection_impl(self, context, selection)

    def _handle_preask_responses(self, text: str) -> None:
        _handle_preask_responses_impl(self, text)

    def _detect_preask_response(self, class_name: str, text: str) -> Optional[str]:
        return _detect_preask_response_impl(self, class_name, text)

    def _single_pending_class(self, class_name: str) -> bool:
        return _single_pending_class_impl(self, class_name)

    def _prepare_preview_for_requests(self) -> None:
        _prepare_preview_for_requests_impl(self)

    def _hydrate_preview_from_context(self) -> None:
        _hydrate_preview_from_context_impl(self)

    def _build_preview_for_class(self, class_name: str, offset: int) -> None:
        _build_preview_for_class_impl(self, class_name, offset)

    def _maybe_preask_lines(self) -> List[str]:
        return _maybe_preask_lines_impl(self)

    def _finalize_preask_state(self) -> None:
        _finalize_preask_state_impl(self)

    # S3: Product utility methods delegated to product_handler.py
    def _product_lookup(self, bucket: str) -> Dict[str, Dict[str, Any]]:
        return _product_lookup_impl(self, bucket)

    def _normalise_products(self, payload: Any) -> List[Dict[str, Any]]:
        return _normalise_products_impl(self, payload)

    @staticmethod
    def _missing_item_display(item: Dict[str, Any]) -> str:
        return _missing_item_display_impl(item)

    # S3: Budget parsing methods delegated to budget_parser.py
    def _extract_budget_info(self) -> Optional[Dict[str, Any]]:
        return _extract_budget_info_impl(self)

    def _parse_budget_value(self, value: Any, scope_default: str) -> Optional[Dict[str, Any]]:
        return _parse_budget_value_impl(value, scope_default)

    @staticmethod
    def _parse_budget_text(value: str, scope_default: str) -> Optional[Dict[str, Any]]:
        return _parse_budget_text_impl(value, scope_default)

    def _infer_quantity(self, product_entry: Dict[str, Any]) -> int:
        return _infer_quantity_impl(self, product_entry)

    def _current_participant_count(self) -> Optional[int]:
        return _current_participant_count_impl(self)

    # S3: Window conversion and time utilities delegated to date_handler.py
    @staticmethod
    def _window_to_payload(window: ConfirmationWindow) -> Dict[str, Any]:
        return _window_to_payload_impl(window)

    @staticmethod
    def _window_from_payload(payload: Dict[str, Any]) -> ConfirmationWindow:
        return _window_from_payload_impl(payload)

    @staticmethod
    def _normalize_time(value: Any) -> Optional[str]:
        return _normalize_time_impl(value)

    def _infer_times_for_date(self, iso_date: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        return _infer_times_for_date_impl(self, iso_date)

    def _explicit_menu_requested(self) -> bool:
        return _explicit_menu_requested_impl(self)

# S3: Module-level catering lookup delegated to product_handler.py
def _load_catering_names() -> List[str]:
    return _load_catering_names_impl()
