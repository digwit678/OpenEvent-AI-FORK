from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from workflows.common.requirements import requirements_hash
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.common.datetime_parse import to_iso_date
from workflows.steps.step1_intake.condition.checks import suggest_dates

if TYPE_CHECKING:
    from workflows.common.types import WorkflowState


@dataclass
class GuardSnapshot:
    """Deterministic guard outcome for steps 2–4.

    This is a pure data structure - no side effects. The caller is responsible
    for applying any metadata updates indicated by the snapshot fields.
    """

    step2_required: bool
    step3_required: bool
    step4_required: bool
    requirements_hash: Optional[str]
    room_eval_hash: Optional[str]
    chosen_date: Optional[str]
    candidate_dates: List[str]

    # P2 extension: metadata update decisions (caller applies these)
    forced_step: Optional[int] = None  # Step to force, if any
    requirements_hash_changed: bool = False  # True if hash was recomputed
    deposit_bypass: bool = False  # True if deposit payment bypass is active


def _iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return to_iso_date(value) or value


def _normalize_date(value: Optional[str]) -> Optional[str]:
    iso_val = _iso(value)
    if not iso_val:
        return None
    return format_iso_date_to_ddmmyyyy(iso_val) or iso_val


def _compute_candidate_dates(state: "WorkflowState", preferred_room: Optional[str]) -> List[str]:
    if not state.event_entry:
        return []
    anchor_ts = state.message.ts or datetime.utcnow().isoformat() + "Z"
    candidates_ddmmyyyy = suggest_dates(
        state.db,
        preferred_room=preferred_room or "Not specified",
        start_from_iso=anchor_ts,
        days_ahead=45,
        max_results=5,
    )
    iso_values: List[str] = []
    seen: set[str] = set()
    for raw in candidates_ddmmyyyy:
        iso = to_iso_date(raw)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        iso_values.append(iso)
        if len(iso_values) >= 5:
            break
    return iso_values


def evaluate(state: "WorkflowState") -> GuardSnapshot:
    """
    Evaluate deterministic entry guards for Steps 2–4 and surface derived state.

    This function is PURE - it returns a GuardSnapshot with all decisions but
    does NOT modify state or event_entry. The caller is responsible for applying
    any metadata updates indicated by the snapshot fields.

    P2 refactoring: Side effects removed, decisions returned in snapshot.
    """

    event_entry = state.event_entry or {}

    # [DEPOSIT PAYMENT BYPASS] When deposit is just paid and offer was accepted,
    # skip guard-forced step changes so workflow proceeds to step 5.
    is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
    if is_deposit_signal and event_entry.get("offer_accepted"):
        # Return early with deposit bypass flag - caller will force step 5
        return GuardSnapshot(
            step2_required=False,
            step3_required=False,
            step4_required=False,
            requirements_hash=event_entry.get("requirements_hash"),
            room_eval_hash=event_entry.get("room_eval_hash"),
            chosen_date=_normalize_date(event_entry.get("chosen_date")),
            candidate_dates=[],
            forced_step=5 if event_entry.get("current_step") != 5 else None,
            deposit_bypass=True,
        )

    user_info = state.user_info or {}

    chosen_date = event_entry.get("chosen_date")
    date_confirmed = bool(event_entry.get("date_confirmed"))
    user_date = user_info.get("event_date") or user_info.get("date")
    normalized_user_date = _normalize_date(user_date)
    normalized_chosen = _normalize_date(chosen_date)

    # Check if message is a deposit/payment date mention (not event date)
    # "We paid the deposit on 02.01.2026" - payment dates should NOT trigger step 2
    import re
    message_text = (state.message.body or "") if state.message else ""
    _deposit_date_pattern = re.compile(
        r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
        re.IGNORECASE
    )
    is_deposit_payment_date = bool(message_text and _deposit_date_pattern.search(message_text))

    # Step 2 guard -----------------------------------------------------------
    step2_required = False
    candidate_dates: List[str] = []

    if not chosen_date or not date_confirmed:
        step2_required = True
    elif normalized_user_date and normalized_user_date != normalized_chosen and not is_deposit_payment_date:
        # Date differs from chosen_date, but skip if it's a deposit payment date
        step2_required = True

    # Check if requirements_hash needs updating (pure computation, no side effect)
    requirements = event_entry.get("requirements") or {}
    req_hash = event_entry.get("requirements_hash")
    requirements_hash_changed = False
    if requirements:
        computed_hash = requirements_hash(requirements)
        if req_hash != computed_hash:
            req_hash = computed_hash
            requirements_hash_changed = True
    else:
        req_hash = None

    room_eval_hash = event_entry.get("room_eval_hash")
    locked_room_id = event_entry.get("locked_room_id")
    user_room = user_info.get("room")

    # -------------------------------------------------------------------------
    # Q&A GUARD: Check if this is a Q&A message (not a change request)
    # If unified_detection indicates is_question=True or qna_types is non-empty,
    # AND is_change_request=False, then skip room-change-based step 3 triggering.
    # This prevents "Does Room A have a projector?" from triggering step 3.
    # -------------------------------------------------------------------------
    import logging
    _guard_logger = logging.getLogger(__name__)

    is_qna_not_change = False
    unified_detection_data = state.extras.get("unified_detection") if state.extras else None
    _guard_logger.debug("[GUARD_QNA] state.extras=%s, unified_detection_data=%s",
                        bool(state.extras), bool(unified_detection_data))
    if unified_detection_data and isinstance(unified_detection_data, dict):
        signals = unified_detection_data.get("signals", {})
        is_question = signals.get("question", False)
        is_change_request = signals.get("change_request", False)
        qna_types = unified_detection_data.get("qna_types", [])
        is_qna_detected = is_question or bool(qna_types)
        _guard_logger.debug("[GUARD_QNA] is_question=%s, is_change_request=%s, qna_types=%s, is_qna_detected=%s",
                           is_question, is_change_request, qna_types, is_qna_detected)
        if is_qna_detected and not is_change_request:
            is_qna_not_change = True
            _guard_logger.debug("[GUARD_QNA] Q&A guard activated: is_qna_not_change=True")

    # Step 3 guard -----------------------------------------------------------
    step3_required = False
    _guard_logger.debug("[GUARD_STEP3] locked_room_id=%s, user_room=%s, is_qna_not_change=%s",
                       locked_room_id, user_room, is_qna_not_change)
    if not step2_required:
        if not locked_room_id:
            step3_required = True
            _guard_logger.debug("[GUARD_STEP3] Triggered: no locked_room_id")
        elif user_room and user_room != locked_room_id and not is_qna_not_change:
            # Only trigger room change if NOT a Q&A message
            step3_required = True
            _guard_logger.debug("[GUARD_STEP3] Triggered: room change %s != %s", user_room, locked_room_id)
        elif req_hash and room_eval_hash and req_hash != room_eval_hash and not is_qna_not_change:
            # Only trigger hash mismatch if NOT a Q&A message
            # Q&A messages like "Does Room A have a projector?" extract "projector" as a product,
            # which changes the requirements hash. This should NOT trigger step 3 re-evaluation.
            step3_required = True
            _guard_logger.debug("[GUARD_STEP3] Triggered: hash mismatch")
        else:
            _guard_logger.debug("[GUARD_STEP3] No condition triggered")

    # Step 4 guard -----------------------------------------------------------
    step4_required = False
    if not step2_required and not step3_required:
        if not date_confirmed:
            step4_required = False
        else:
            offer_status = str(event_entry.get("offer_status") or "").strip().lower()
            if not locked_room_id:
                step4_required = False
            elif req_hash and room_eval_hash and req_hash != room_eval_hash:
                step4_required = False
            else:
                step4_required = offer_status not in {"sent", "accepted", "accepted_final"}

    # Compute candidate dates if step2 required (pure computation)
    if step2_required and not candidate_dates:
        preferred_room = requirements.get("preferred_room")
        candidate_dates = _compute_candidate_dates(state, preferred_room)

    # Determine forced step (pure computation, no side effect)
    forced_step: Optional[int] = None
    if step2_required:
        forced_step = 2
    elif step3_required:
        forced_step = 3
    elif step4_required:
        forced_step = 4

    # Only indicate forced_step if it differs from current
    current_step = event_entry.get("current_step")
    if forced_step == current_step:
        forced_step = None

    return GuardSnapshot(
        step2_required=step2_required,
        step3_required=step3_required,
        step4_required=step4_required,
        requirements_hash=req_hash,
        room_eval_hash=room_eval_hash,
        chosen_date=normalized_chosen,
        candidate_dates=candidate_dates,
        forced_step=forced_step,
        requirements_hash_changed=requirements_hash_changed,
        deposit_bypass=False,
    )


def shortcut_ready(state: "WorkflowState") -> bool:
    """
    Determine whether the first message contains enough signals for the fast-path.
    """

    if not state.event_entry:
        return False

    user_info = state.user_info or {}
    date_ready = bool(user_info.get("date") or user_info.get("event_date"))
    attendees_ready = bool(user_info.get("participants"))

    if not (date_ready and attendees_ready):
        return False

    chosen_date = state.event_entry.get("chosen_date")
    if chosen_date:
        return False

    return True