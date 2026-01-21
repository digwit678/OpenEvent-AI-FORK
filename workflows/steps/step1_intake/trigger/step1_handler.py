from __future__ import annotations

import logging
import os
from datetime import datetime, time

logger = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional, Tuple

from workflows.common.prompts import append_footer
from workflows.common.requirements import build_requirements, merge_client_profile, requirements_hash
from workflows.common.timeutils import format_ts_to_ddmmyyyy, format_iso_date_to_ddmmyyyy
from workflows.common.types import GroupResult, WorkflowState
from workflows.change_propagation import (
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from detection.keywords.buckets import has_revision_signal
import json

from domain import IntentLabel
from debug.hooks import (
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_prompt_in,
    trace_prompt_out,
    trace_state,
    trace_step,
)
from workflows.io.database import (
    append_history,
    append_audit_entry,
    context_snapshot,
    create_event_entry,
    default_event_record,
    find_event_idx_by_id,
    last_event_for_email,
    load_rooms,
    tag_message,
    update_event_entry,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
import re
from ..llm.analysis import classify_intent, extract_user_information
from workflows.nlu.preferences import extract_preferences
from services import client_memory
from ..billing_flow import handle_billing_capture
from workflows.common.datetime_parse import parse_first_date
from services.products import list_product_records, merge_product_requests, normalise_product_payload
from workflows.common.menu_options import DINNER_MENU_OPTIONS
from workflows.qna.router import generate_hybrid_qna_response
from detection.intent.classifier import _detect_qna_types
from workflows.common.catalog import list_room_features
from services.room_eval import evaluate_rooms
from workflows.steps.step2_date_confirmation.trigger.date_parsing import iso_date_is_past, normalize_iso_candidate

# Extracted pure helpers (I1 refactoring)
from .normalization import normalize_quotes as _normalize_quotes
from .normalization import normalize_room_token as _normalize_room_token
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from .gate_confirmation import looks_like_offer_acceptance as _looks_like_offer_acceptance
from .gate_confirmation import looks_like_billing_fragment as _looks_like_billing_fragment
from workflows.common.detection_utils import get_unified_detection


def _validate_extracted_room(room_value: Optional[str], message_text: Optional[str] = None) -> Optional[str]:
    """Validate that extracted room matches a known room name exactly (case-insensitive).

    The LLM entity extraction can produce false positives like extracting "Room F"
    from "room for 30 people". This filter:
    1. Ensures the room name exists in the database
    2. Detects false positives from "room <preposition>" patterns

    Returns:
        The room name if valid, None otherwise.
    """
    if not room_value:
        return None

    # Get valid room names from database
    valid_rooms = load_rooms()
    if not valid_rooms:
        return None

    # Case-insensitive exact match against known rooms
    room_lower = room_value.strip().lower()
    canonical_room = None
    for valid_room in valid_rooms:
        if valid_room.lower() == room_lower:
            canonical_room = valid_room
            break

    if not canonical_room:
        return None

    # [FALSE POSITIVE DETECTION] Check if extraction might be from "room <preposition>"
    # Pattern: "room for", "room to", "room in", etc. where LLM extracts "Room F", "Room T", etc.
    if message_text:
        text_lower = message_text.lower()
        # Common prepositions that follow "room" in generic phrases
        prepositions = ["for", "to", "in", "at", "with", "on", "is", "as", "and", "or", "the"]
        # Extract the room suffix (e.g., "F" from "Room F")
        room_suffix = canonical_room.split()[-1].lower() if " " in canonical_room else canonical_room.lower()

        for prep in prepositions:
            # Check if message has "room <preposition>" pattern
            pattern = rf"\broom\s+{prep}\b"
            if re.search(pattern, text_lower) and prep.startswith(room_suffix):
                # The extracted room letter matches a preposition - likely false positive
                # Additional check: is there an explicit room selection in the message?
                explicit_room_pattern = rf"\broom\s*{room_suffix}\b"
                # Don't reject if there's also an explicit "Room F" or "room f" in the message
                if not re.search(explicit_room_pattern, text_lower):
                    logger.debug(
                        "[Step1][ROOM_FALSE_POSITIVE] Detected 'room %s' pattern without explicit room selection",
                        prep,
                    )
                    return None

    return canonical_room


def _extract_billing_from_body(body: str) -> Optional[str]:
    """
    Extract billing address from message body if it contains billing info.

    Handles cases where billing is embedded in a larger message (e.g., event request
    that also includes billing address).

    Returns the extracted billing portion, or None if no billing info found.
    """
    if not body or not body.strip():
        return None

    # Check for explicit billing section markers
    billing_markers = [
        r"(?:our\s+)?billing\s+address(?:\s+is)?[:\s]*",
        r"(?:our\s+)?address(?:\s+is)?[:\s]*",
        r"invoice\s+(?:to|address)[:\s]*",
        r"send\s+invoice\s+to[:\s]*",
    ]

    for pattern in billing_markers:
        match = re.search(pattern + r"(.+?)(?:\n\n|Best|Kind|Thank|Regards|$)", body, re.IGNORECASE | re.DOTALL)
        if match:
            billing_text = match.group(1).strip()
            # Validate it looks like an address (has street/postal)
            if _looks_like_billing_fragment(billing_text):
                return billing_text

    # Fallback: check if message contains billing keywords but no explicit marker
    # Only extract if it looks like a complete address
    if _looks_like_billing_fragment(body):
        # Try to find a multi-line address block
        lines = body.split("\n")
        address_lines = []
        in_address = False

        for line in lines:
            line = line.strip()
            if not line:
                if in_address and len(address_lines) >= 2:
                    break  # End of address block
                continue

            # Check if line looks like address part (has postal code, street number, or company name)
            has_postal = re.search(r"\b\d{4,6}\b", line)
            has_street_num = re.search(r"\d+\w*\s*$|\s\d+\s", line)
            is_company = bool(re.search(r"\b(gmbh|ag|ltd|inc|corp|llc|sarl|sa)\b", line, re.IGNORECASE))
            is_city_country = bool(re.search(r"\b(zurich|zürich|geneva|bern|basel|switzerland|schweiz)\b", line, re.IGNORECASE))

            if has_postal or has_street_num or is_company or is_city_country:
                in_address = True
                address_lines.append(line)
            elif in_address:
                # Continue adding lines until we hit something that's clearly not address
                if len(line) < 50 and not re.search(r"\b(hello|hi|dear|please|thank|we|i am|looking)\b", line, re.IGNORECASE):
                    address_lines.append(line)
                else:
                    break

        if len(address_lines) >= 2:
            return "\n".join(address_lines)

    return None

# I1 Phase 1: Intent helpers
from .intent_helpers import (
    needs_vague_date_confirmation as _needs_vague_date_confirmation,
    initial_intent_detail as _initial_intent_detail,
    has_same_turn_shortcut as _has_same_turn_shortcut,
    resolve_owner_step as _resolve_owner_step,
)

# I1 Phase 1: Keyword matching
from .keyword_matching import (
    PRODUCT_ADD_KEYWORDS as _PRODUCT_ADD_KEYWORDS,
    PRODUCT_REMOVE_KEYWORDS as _PRODUCT_REMOVE_KEYWORDS,
    keyword_regex as _keyword_regex,
    contains_keyword as _contains_keyword,
    product_token_regex as _product_token_regex,
    match_product_token as _match_product_token,
    extract_quantity_from_window as _extract_quantity_from_window,
    menu_token_candidates as _menu_token_candidates,
)

# I1 Phase 1: Confirmation parsing
from .confirmation_parsing import (
    DATE_TOKEN as _DATE_TOKEN,
    MONTH_TOKENS as _MONTH_TOKENS,
    AFFIRMATIVE_TOKENS as _AFFIRMATIVE_TOKENS,
    extract_confirmation_details as _extract_confirmation_details,
    looks_like_gate_confirmation as _looks_like_gate_confirmation,
)

# I1 Phase 2: Room detection
from .room_detection import detect_room_choice as _detect_room_choice

# I1 Phase 2: Product detection
from .product_detection import (
    menu_price_value as _menu_price_value,
    detect_menu_choice as _detect_menu_choice,
)

# I1 Phase 2: Entity extraction
from .entity_extraction import participants_from_event as _participants_from_event

# Dev/test mode helper (I2 refactoring)
from .dev_test_mode import maybe_show_dev_choice as _maybe_show_dev_choice

__workflow_role__ = "trigger"


# Generic product suffixes that shouldn't match standalone.
# These appear as the last word in product names (e.g., "Vegetarian Menu")
# but are too ambiguous to match without the full product name context.
_GENERIC_PRODUCT_TOKENS = frozenset({
    "menu", "menus",
    "option", "options",
    "package", "packages",
    "service", "services",
    "setup", "setups",
})


# Patterns for bulk menu/food removal requests
_BULK_MENU_REMOVE_PATTERNS = (
    r"\b(?:remove|drop|skip|exclude|cut)\s+(?:all\s+)?(?:the\s+)?(?:menus?|food|catering)",
    r"\b(?:no|don'?t\s+need|don'?t\s+want)\s+(?:any\s+)?(?:menus?|food|catering)",
    r"\bwithout\s+(?:any\s+)?(?:menus?|food|catering)",
    r"\b(?:menus?|food|catering)\s+(?:is|are)\s+not\s+(?:needed|required)",
)


def _detect_bulk_menu_removal(text: str) -> bool:
    """Detect if user wants to remove all menus/food from the offer."""
    for pattern in _BULK_MENU_REMOVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# NOTE: _detect_product_update_request kept here as it has side effects (mutates user_info)
# and DB dependencies - candidate for future refactoring to return tuple instead of mutating
def _detect_product_update_request(
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
    linked_event: Optional[Dict[str, Any]],
) -> bool:
    subject = message_payload.get("subject") or ""
    body = message_payload.get("body") or ""
    text = f"{subject}\n{body}".strip().lower()
    if not text:
        return False

    participant_count = _participants_from_event(linked_event)
    existing_additions = user_info.get("products_add")
    existing_removals = user_info.get("products_remove")
    existing_ops = bool(existing_additions or existing_removals)
    additions: List[Dict[str, Any]] = []
    removals: List[str] = []
    catalog = list_product_records()

    # Bulk removal detection: "remove all menus", "no food", "don't need any food"
    bulk_remove_menus = _detect_bulk_menu_removal(text)
    if bulk_remove_menus:
        # Add special marker that apply_product_operations will handle
        # This will remove ALL products with "menu" in the name or Catering category
        removals.append("__BULK_REMOVE_MENUS__")
        # Also add specific menu names for more precise matching
        for menu in DINNER_MENU_OPTIONS:
            menu_name = str(menu.get("menu_name") or "").strip()
            if menu_name:
                removals.append(menu_name)
        # Also remove any catalog products with "menu" in category
        for record in catalog:
            cat = (record.category or "").lower()
            name = record.name or ""
            if "menu" in cat or "catering" in cat:
                removals.append(name)

    for record in catalog:
        tokens: List[str] = []
        primary = (record.name or "").strip().lower()
        if primary:
            tokens.append(primary)
            if not primary.endswith("s"):
                tokens.append(f"{primary}s")
            # Also match the last word of the product name (e.g., "mic", "microphone")
            # Skip generic tokens like "menu", "option", "service" to avoid false positives
            primary_parts = primary.split()
            if primary_parts:
                last_primary = primary_parts[-1]
                if len(last_primary) >= 3 and last_primary not in _GENERIC_PRODUCT_TOKENS:
                    tokens.append(last_primary)
                    if not last_primary.endswith("s"):
                        tokens.append(f"{last_primary}s")
        for synonym in record.synonyms or []:
            synonym_token = str(synonym or "").strip().lower()
            if not synonym_token:
                continue
            tokens.append(synonym_token)
            if not synonym_token.endswith("s"):
                tokens.append(f"{synonym_token}s")
            # And the last word of each synonym (e.g., "mic")
            # Skip generic tokens like "menu", "option" to avoid false positives
            synonym_parts = synonym_token.split()
            if synonym_parts:
                last_syn = synonym_parts[-1]
                if len(last_syn) >= 3 and last_syn not in _GENERIC_PRODUCT_TOKENS:
                    tokens.append(last_syn)
                    if not last_syn.endswith("s"):
                        tokens.append(f"{last_syn}s")
        matched_idx: Optional[int] = None
        matched_token: Optional[str] = None
        for token_candidate in tokens:
            idx = _match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue
        # Skip matches that occur inside parentheses; these are often explanatory
        # fragments (e.g., `covers "background music"`) rather than explicit
        # product selection signals.
        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue
        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]
        if _contains_keyword(window, _PRODUCT_REMOVE_KEYWORDS):
            removals.append(record.name)
            continue
        quantity = _extract_quantity_from_window(window, matched_token)
        add_signal = _contains_keyword(window, _PRODUCT_ADD_KEYWORDS)
        if add_signal or quantity:
            payload: Dict[str, Any] = {"name": record.name}
            if quantity:
                payload["quantity"] = quantity
            else:
                # Default to a single additional unit; downstream upsert increments existing quantity.
                payload["quantity"] = 1
            additions.append(payload)

    # Also detect dinner menu selections/removals so they behave like standard products.
    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "").strip()
        if not name:
            continue
        matched_idx: Optional[int] = None
        matched_token: Optional[str] = None
        for token_candidate in _menu_token_candidates(name):
            idx = _match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue
        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue
        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]
        if _contains_keyword(window, _PRODUCT_REMOVE_KEYWORDS):
            removals.append(name)
            continue
        quantity = _extract_quantity_from_window(window, matched_token) or 1
        additions.append(
            {
                "name": name,
                "quantity": 1 if str(menu.get("unit") or "").strip().lower() == "per_event" else quantity,
                "unit_price": _menu_price_value(menu.get("price")),
                "unit": menu.get("unit") or "per_event",
                "category": "Catering",
                "wish": "menu",
            }
        )

    combined_additions: List[Dict[str, Any]] = []
    if existing_additions:
        combined_additions.extend(
            normalise_product_payload(existing_additions, participant_count=participant_count)
        )
    if additions:
        normalised = normalise_product_payload(additions, participant_count=participant_count)
        if normalised:
            combined_additions = (
                merge_product_requests(combined_additions, normalised) if combined_additions else normalised
            )
    if combined_additions:
        user_info["products_add"] = combined_additions

    combined_removals: List[str] = []
    removal_seen = set()
    if isinstance(existing_removals, list):
        for entry in existing_removals:
            name = entry.get("name") if isinstance(entry, dict) else entry
            text_name = str(name or "").strip()
            if text_name:
                lowered = text_name.lower()
                if lowered not in removal_seen:
                    removal_seen.add(lowered)
                    combined_removals.append(text_name)
    if removals:
        for name in removals:
            lowered = name.lower()
            if lowered not in removal_seen:
                removal_seen.add(lowered)
                combined_removals.append(name)
    if combined_removals:
        user_info["products_remove"] = combined_removals

    return bool(additions or removals or combined_additions or combined_removals or existing_ops)


@trace_step("Step1_Intake")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""
    message_payload = state.message.to_payload()
    thread_id = _thread_id(state)

    # Resolve owner step for tracing based on existing conversation state
    email = (message_payload.get("from_email") or "").lower()
    linked_event = last_event_for_email(state.db, email) if email else None
    current_step = linked_event.get("current_step") if linked_event else 1
    # Fallback if current_step is None/invalid
    if not isinstance(current_step, int):
        current_step = 1
    owner_step = _resolve_owner_step(current_step)

    # [TESTING CONVENIENCE] Dev/test mode choice prompt (I2 extraction)
    skip_dev_choice = state.extras.get("skip_dev_choice", False)
    dev_choice_result = _maybe_show_dev_choice(
        linked_event=linked_event,
        current_step=current_step,
        owner_step=owner_step,
        client_email=email,
        skip_dev_choice=skip_dev_choice,
    )
    if dev_choice_result:
        return dev_choice_result

    trace_marker(
        thread_id,
        "TRIGGER_Intake",
        detail=message_payload.get("subject"),
        data={"msg_id": state.message.msg_id},
        owner_step=owner_step,
    )
    prompt_payload = (
        f"Subject: {message_payload.get('subject') or ''}\n"
        f"Body:\n{message_payload.get('body') or ''}"
    )
    trace_prompt_in(thread_id, owner_step, "classify_intent", prompt_payload)
    intent, confidence = classify_intent(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "classify_intent",
        json.dumps({"intent": intent.value, "confidence": round(confidence, 3)}, ensure_ascii=False),
        outputs={"intent": intent.value, "confidence": round(confidence, 3)},
    )
    trace_marker(
        thread_id,
        "AGENT_CLASSIFY",
        detail=intent.value,
        data={"confidence": round(confidence, 3)},
        owner_step=owner_step,
    )
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = _initial_intent_detail(intent)

    trace_prompt_in(thread_id, owner_step, "extract_user_information", prompt_payload)
    user_info = extract_user_information(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "extract_user_information",
        json.dumps(user_info, ensure_ascii=False),
        outputs=user_info,
    )
    # [ROOM VALIDATION] Reject false positive room extractions (e.g., "Room F" from "room for")
    # The LLM can misinterpret phrases like "room for 30 people" as a room selection.
    # Only accept room values that exactly match known room names.
    if user_info.get("room"):
        original_text = f"{message_payload.get('subject', '')} {message_payload.get('body', '')}".strip()
        validated_room = _validate_extracted_room(user_info["room"], message_text=original_text)
        if validated_room != user_info["room"]:
            logger.debug(
                "[Step1][ROOM_VALIDATION] Rejected room extraction: %r -> %r",
                user_info["room"],
                validated_room,
            )
        user_info["room"] = validated_room
    # [REGEX FALLBACK] If LLM failed to extract date, try regex parsing
    # This handles cases like "February 14th, 2026" that LLM might miss
    if not user_info.get("date") and not user_info.get("event_date"):
        body_text = message_payload.get("body") or ""
        fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
        parsed_date = parse_first_date(body_text, fallback_year=fallback_year)
        if parsed_date:
            user_info["date"] = parsed_date.isoformat()
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(parsed_date.isoformat())
            logger.debug("[Step1] Regex fallback extracted date: %s", parsed_date.isoformat())
            # Boost confidence if we found date via regex - indicates valid event request
            if intent == IntentLabel.EVENT_REQUEST and confidence < 0.90:
                confidence = 0.90
                state.confidence = confidence
                logger.debug("[Step1] Boosted confidence to %s due to regex date extraction", confidence)
    # Preserve raw message content for downstream semantic extraction.
    needs_vague_date_confirmation = _needs_vague_date_confirmation(user_info)
    if needs_vague_date_confirmation:
        user_info.pop("event_date", None)
        user_info.pop("date", None)
    raw_pref_text = "\n".join(
        [
            message_payload.get("subject") or "",
            message_payload.get("body") or "",
        ]
    ).strip()
    preferences = extract_preferences(user_info, raw_text=raw_pref_text or None)
    if preferences:
        user_info["preferences"] = preferences
    if intent == IntentLabel.EVENT_REQUEST and _has_same_turn_shortcut(user_info):
        state.intent_detail = "event_intake_shortcut"
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")
    _trace_user_entities(state, message_payload, user_info, owner_step)

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    # linked_event is already fetched above
    body_text_raw = message_payload.get("body") or ""
    body_text = _normalize_quotes(body_text_raw)
    fallback_year = _fallback_year_from_ts(message_payload.get("ts"))

    confirmation_detected = False
    if (
        linked_event
        and not user_info.get("date")
        and not user_info.get("event_date")
        and _looks_like_gate_confirmation(body_text, linked_event)
    ):
        iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year)
        if iso_date:
            user_info["date"] = iso_date
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
            confirmation_detected = True
        if start_time and "start_time" not in user_info:
            user_info["start_time"] = start_time
        if end_time and "end_time" not in user_info:
            user_info["end_time"] = end_time
    # Capture short acceptances on existing offers to avoid manual-review loops.
    acceptance_detected = linked_event and _looks_like_offer_acceptance(body_text)
    if acceptance_detected:
        intent = IntentLabel.EVENT_REQUEST
        confidence = max(confidence, 0.99)
        state.intent = intent
        state.confidence = confidence
        if state.intent_detail in (None, "intake"):
            state.intent_detail = "event_intake_negotiation_accept"
        # Always route acceptances through HIL so the manager can approve/decline before confirmation.
        target_step = max(linked_event.get("current_step") or 0, 5)
        user_info.setdefault("hil_approve_step", target_step)
        update_event_metadata(
            linked_event,
            current_step=target_step,
            thread_state="Waiting on HIL",
            caller_step=None,
        )
        state.extras["persist"] = True
    # Early room-choice detection so we don't rely on classifier confidence
    # Pass unified detection to enable question guard ("Is Room A available?" should not lock)
    unified_detection = get_unified_detection(state)

    # HYBRID FIX: Set general_qna_detected based on unified detection
    # This is needed for hybrid messages (workflow action + Q&A in same message)
    # IMPORTANT: Only set if LLM detected is_question=True, otherwise it's just a workflow action
    has_qna_types = bool(getattr(unified_detection, "qna_types", None) if unified_detection else False)
    is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    if has_qna_types and is_question:
        state.extras["general_qna_detected"] = True
        state.extras["_has_qna_types"] = True

    early_room_choice = _detect_room_choice(body_text, linked_event, unified_detection)
    logger.info("[Step1] early_room_choice=%s (linked_event.current_step=%s)",
                early_room_choice, linked_event.get("current_step") if linked_event else None)
    if early_room_choice:
        user_info["room"] = early_room_choice
        user_info["_room_choice_detected"] = True
        state.extras["room_choice_selected"] = early_room_choice
        logger.info("[Step1] Set _room_choice_detected=True for room=%s", early_room_choice)
        # Bump confidence to prevent Step 3 nonsense gate from triggering HIL
        confidence = 1.0
        intent = IntentLabel.EVENT_REQUEST
        state.intent = intent
        state.confidence = confidence

    # Capture explicit menu selection (e.g., "Room E with Seasonal Garden Trio")
    menu_choice = _detect_menu_choice(body_text)
    if menu_choice:
        user_info["menu_choice"] = menu_choice["name"]
        participants = _participants_from_event(linked_event) or user_info.get("participants")
        try:
            participants = int(participants) if participants is not None else None
        except (TypeError, ValueError):
            participants = None
        if menu_choice.get("price"):
            product_payload = {
                "name": menu_choice["name"],
                "quantity": 1 if menu_choice.get("unit") == "per_event" else (participants or 1),
                "unit_price": menu_choice["price"],
                "unit": menu_choice.get("unit") or "per_event",
                "category": "Catering",
                "wish": "menu",
            }
            existing = user_info.get("products_add") or []
            if isinstance(existing, list):
                user_info["products_add"] = existing + [product_payload]
            else:
                user_info["products_add"] = [product_payload]

    product_update_detected = _detect_product_update_request(message_payload, user_info, linked_event)
    if product_update_detected:
        state.extras["product_update_detected"] = True
        if not is_event_request(intent):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_product_update"
        elif state.intent_detail in (None, "intake", "event_intake"):
            state.intent_detail = "event_intake_product_update"
    state.user_info = user_info
    append_history(client, message_payload, intent.value, confidence, user_info)

    # Store in client memory for personalization (if enabled)
    client_memory.append_message(
        client,
        role="client",
        text=message_payload.get("body") or "",
        metadata={"intent": intent.value, "confidence": confidence},
    )
    # Update profile with detected language/preferences
    if user_info.get("language"):
        client_memory.update_profile(client, language=user_info["language"])

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    # [CONFIDENCE BOOST FOR CLEAR EVENT REQUESTS]
    # If LLM detected event_request intent AND we have both date and participants,
    # this is unambiguously an event inquiry - boost confidence to avoid false manual_review.
    # This fixes cases where LLM returns 0.7 confidence for clear event requests.
    if is_event_request(intent) and confidence < 0.85:
        has_date = bool(user_info.get("date") or user_info.get("event_date"))
        has_participants = bool(user_info.get("participants"))
        if has_date and has_participants:
            logger.info(
                "[Step1] Boosting confidence %.2f -> 0.90 for clear event request "
                "(has date=%s, participants=%s)",
                confidence, user_info.get("date"), user_info.get("participants")
            )
            confidence = max(confidence, 0.90)
            state.confidence = confidence

    # [SKIP MANUAL REVIEW FOR EXISTING EVENTS]
    # If there's an existing event at step > 1, we should NOT do "is this an event?"
    # classification. These messages should flow through to the step-specific handlers
    # which have their own logic for handling detours, Q&A, confirmations, etc.
    skip_manual_review_check = linked_event and linked_event.get("current_step", 1) > 1

    if not skip_manual_review_check and (not is_event_request(intent) or confidence < 0.85):
        body_text = message_payload.get("body") or ""
        awaiting_billing = linked_event and (linked_event.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        if awaiting_billing:
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_billing_update"
            if body_text.strip() and _looks_like_billing_fragment(body_text):
                user_info["billing_address"] = body_text.strip()
        elif _looks_like_gate_confirmation(body_text, linked_event):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.95)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_followup"
            fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
            iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year)
            if iso_date:
                user_info["date"] = iso_date
                user_info["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
            if start_time:
                user_info["start_time"] = start_time
            if end_time:
                user_info["end_time"] = end_time
        else:
            # unified_detection already fetched above, reuse it
            room_choice = _detect_room_choice(body_text, linked_event, unified_detection)
            if room_choice:
                intent = IntentLabel.EVENT_REQUEST
                confidence = max(confidence, 0.96)
                state.intent = intent
                state.confidence = confidence
                state.intent_detail = "event_intake_room_choice"
                user_info["room"] = room_choice
                user_info["_room_choice_detected"] = True
                state.extras["room_choice_selected"] = room_choice
                # Only lock immediately if no room is currently locked; otherwise let Step 3 handle a switch.
                if linked_event:
                    locked = linked_event.get("locked_room_id")
                    if not locked:
                        req_hash = linked_event.get("requirements_hash")
                        update_event_metadata(
                            linked_event,
                            locked_room_id=room_choice,
                            room_eval_hash=req_hash,
                            room_status="Available",
                            caller_step=None,
                        )
            else:
                if _looks_like_billing_fragment(body_text):
                    intent = IntentLabel.EVENT_REQUEST
                    confidence = max(confidence, 0.92)
                    state.intent = intent
                    state.confidence = confidence
                    state.intent_detail = "event_intake_billing_capture"
                    user_info["billing_address"] = body_text.strip()

                # Handle standalone Q&A without event - don't route to manual_review
                # This allows Q&A questions like "do you have parking?" to be answered
                # even when there's no existing booking context
                is_qna_intent = intent in (IntentLabel.NON_EVENT, IntentLabel.CAPABILITY_QNA) or "qna" in intent.value.lower()
                if is_qna_intent and not linked_event:
                    # Try to generate specific Q&A response (pricing, parking, etc.)
                    qna_types = _detect_qna_types((state.message.body or "").lower())
                    hybrid_response = None
                    if qna_types:
                        hybrid_response = generate_hybrid_qna_response(
                            qna_types=qna_types,
                            message_text=state.message.body or "",
                            event_entry=None,
                            db=None,
                        )

                    if hybrid_response:
                        # Use the specific Q&A response
                        qna_response = hybrid_response
                    else:
                        # Fallback: ask for event details
                        qna_response = (
                            "Thank you for your question! To help you best, could you let me know if "
                            "you're interested in booking an event with us? If so, please share:\n"
                            "- Your preferred date\n"
                            "- Expected number of guests\n\n"
                            "If you have a general question about our venue or services, "
                            "feel free to ask and I'll do my best to help."
                        )
                    qna_response = append_footer(
                        qna_response,
                        step=1,
                        next_step=1,
                        thread_state="Awaiting Client",
                    )
                    state.add_draft_message(
                        {
                            "body": qna_response,
                            "step": 1,
                            "topic": "standalone_qna",
                        }
                    )
                    state.set_thread_state("Awaiting Client")
                    payload = {
                        "client_id": state.client_id,
                        "event_id": None,
                        "intent": intent.value,
                        "confidence": round(confidence, 3),
                        "draft_messages": state.draft_messages,
                        "thread_state": state.thread_state,
                        "standalone_qna": True,
                    }
                    return GroupResult(action="standalone_qna", payload=payload, halt=True)

                if not is_event_request(intent) or confidence < 0.85:
                    trace_marker(
                        thread_id,
                        "CONDITIONAL_HIL",
                        detail="manual_review_required",
                        data={"intent": intent.value, "confidence": round(confidence, 3)},
                        owner_step=owner_step,
                    )
                    linked_event_id = linked_event.get("event_id") if linked_event else None
                    task_payload: Dict[str, Any] = {
                        "subject": message_payload.get("subject"),
                        "snippet": (message_payload.get("body") or "")[:200],
                        "ts": message_payload.get("ts"),
                        "reason": "manual_review_required",
                        "thread_id": thread_id,
                    }
                    task_id = enqueue_manual_review_task(
                        state.db,
                        state.client_id,
                        linked_event_id,
                        task_payload,
                    )
                    state.extras.update({"task_id": task_id, "persist": True})
                    clarification = (
                        "Thanks for your message. A member of our team will review it shortly "
                        "to make sure it reaches the right place."
                    )
                    clarification = append_footer(
                        clarification,
                        step=1,
                        next_step="Team review (HIL)",
                        thread_state="Waiting on HIL",
                    )
                    state.add_draft_message(
                        {
                            "body": clarification,
                            "step": 1,
                            "topic": "manual_review",
                        }
                    )
                    state.set_thread_state("Waiting on HIL")
                    logger.debug("[Step1] manual_review_enqueued: conf=%.2f, parsed_date=%s, intent=%s",
                                confidence, user_info.get('date'), intent.value)
                    payload = {
                        "client_id": state.client_id,
                        "event_id": linked_event_id,
                        "intent": intent.value,
                        "confidence": round(confidence, 3),
                        "persisted": True,
                        "task_id": task_id,
                        "user_info": user_info,
                        "context": context,
                        "draft_messages": state.draft_messages,
                        "thread_state": state.thread_state,
                    }
                    return GroupResult(action="manual_review_enqueued", payload=payload, halt=True)

    event_entry = _ensure_event_record(state, message_payload, user_info)
    if event_entry.get("pending_hil_requests"):
        event_entry["pending_hil_requests"] = []
        state.extras["persist"] = True

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True

    # Extract billing from message body if not already captured
    # This allows billing to be captured even from event requests that include billing info
    if not user_info.get("billing_address"):
        body_text = message_payload.get("body") or ""
        extracted_billing = _extract_billing_from_body(body_text)
        if extracted_billing:
            user_info["billing_address"] = extracted_billing
            trace_entity(thread_id, owner_step, "billing_address", extracted_billing[:100], True)

    handle_billing_capture(state, event_entry)
    menu_choice_name = user_info.get("menu_choice")
    if menu_choice_name:
        catering_list = event_entry.setdefault("selected_catering", [])
        if menu_choice_name not in catering_list:
            catering_list.append(menu_choice_name)
            event_entry.setdefault("event_data", {})["Catering Preference"] = menu_choice_name
            state.extras["persist"] = True
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    requirements_snapshot = event_entry.get("requirements") or {}

    # [PRODUCTS-ONLY CHECK] Save original user_info products fields before fallback
    # to detect if this is a products-only message (not a requirements change)
    original_products_add = user_info.get("products_add")
    original_products_remove = user_info.get("products_remove")
    original_notes = user_info.get("notes")
    # Check if the ORIGINAL user_info (before fallback) has requirements fields
    original_has_requirements = any([
        user_info.get("participants"),
        user_info.get("layout") or user_info.get("type"),
        user_info.get("start_time") or user_info.get("end_time"),
        user_info.get("date") or user_info.get("event_date"),
        user_info.get("room") or user_info.get("preferred_room"),
    ])

    def _needs_fallback(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0
        return False

    if _needs_fallback(user_info.get("participants")) and requirements_snapshot.get("number_of_participants") is not None:
        user_info["participants"] = requirements_snapshot.get("number_of_participants")

    snapshot_layout = requirements_snapshot.get("seating_layout")
    if snapshot_layout:
        if _needs_fallback(user_info.get("layout")):
            user_info["layout"] = snapshot_layout
        if _needs_fallback(user_info.get("type")):
            user_info["type"] = snapshot_layout

    duration_snapshot = requirements_snapshot.get("event_duration")
    if isinstance(duration_snapshot, dict):
        if _needs_fallback(user_info.get("start_time")) and duration_snapshot.get("start"):
            user_info["start_time"] = duration_snapshot.get("start")
        if _needs_fallback(user_info.get("end_time")) and duration_snapshot.get("end"):
            user_info["end_time"] = duration_snapshot.get("end")

    snapshot_notes = requirements_snapshot.get("special_requirements")
    if snapshot_notes and _needs_fallback(user_info.get("notes")):
        user_info["notes"] = snapshot_notes

    snapshot_room = requirements_snapshot.get("preferred_room")
    if snapshot_room and _needs_fallback(user_info.get("room")):
        user_info["room"] = snapshot_room

    # [PRODUCTS-ONLY FIX] When the message is a products-only change (e.g., "add a projector"),
    # don't rebuild requirements from user_info. The LLM might extract product names into
    # special_requirements, which would invalidate the requirements_hash and cause unnecessary
    # re-routing to step 3.
    # Use ORIGINAL user_info values (saved before fallback) to check if this is products-only
    notes_looks_like_product = any(p in (original_notes or "").lower() for p in [
        "projector", "screen", "microphone", "flipchart", "beamer", "av",
        "catering", "coffee", "tea", "lunch", "dinner",
    ]) if isinstance(original_notes, str) else False

    has_products_signal = original_products_add or original_products_remove or notes_looks_like_product
    is_products_only_change = has_products_signal and not original_has_requirements

    logger.debug("[Step1] Products check: original_notes=%s, notes_looks_like_product=%s, "
                 "has_products_signal=%s, original_has_requirements=%s, is_products_only=%s",
                 original_notes, notes_looks_like_product, has_products_signal,
                 original_has_requirements, is_products_only_change)

    if is_products_only_change and requirements_snapshot:
        # Keep existing requirements, don't rebuild from user_info
        logger.debug("[Step1] Products-only change detected, preserving existing requirements")
        requirements = requirements_snapshot
        new_req_hash = event_entry.get("requirements_hash")
    else:
        requirements = build_requirements(user_info)
        new_req_hash = requirements_hash(requirements)

    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    # [SMART SHORTCUT] If initial message has room + date + participants, verify inline and jump to offer
    # This avoids an extra round-trip through Step 3 when all info is provided upfront
    preferred_room_from_msg = requirements.get("preferred_room") or user_info.get("room")
    event_date_from_msg = user_info.get("event_date") or user_info.get("date")
    participants_from_msg = requirements.get("participants") or requirements.get("number_of_participants")

    # [PAST DATE VALIDATION] Check if the extracted date is in the past - this applies UNIVERSALLY
    # (not just smart shortcut) for all new events with a date
    # NOTE: We DON'T clear user_info["event_date"] here - Step 2's validate_window will detect
    # the past date and provide a friendly message with alternative dates
    past_date_detected = False
    if event_date_from_msg and not event_entry.get("date_confirmed"):
        normalized_date = normalize_iso_candidate(event_date_from_msg)
        if normalized_date and iso_date_is_past(normalized_date):
            logger.info("[Step1][PAST_DATE] Date %s is in the past - routing to Step 2", event_date_from_msg)
            past_date_detected = True
            state.extras["past_date_rejected"] = event_date_from_msg
            # Don't clear date from user_info - Step 2 needs it to show the rejection message
            event_date_from_msg = None  # Don't use it for smart shortcut (skip room verification)

    # Only trigger smart shortcut for NEW events (no existing room lock) that have all three fields
    is_new_event = not event_entry.get("locked_room_id") and not event_entry.get("date_confirmed")
    has_all_shortcut_fields = preferred_room_from_msg and event_date_from_msg and participants_from_msg

    # Route to Step 2 if past date was detected (with flag for alternatives suggestion)
    if past_date_detected:
        logger.info("[Step1][PAST_DATE] Routing to Step 2 for date alternatives")
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
        )
        state.current_step = 2
        state.extras["persist"] = True
        # Fall through - Step 2 handler will see past_date_rejected and suggest alternatives

    if is_new_event and has_all_shortcut_fields and not needs_vague_date_confirmation:
        logger.debug("[Step1][SMART_SHORTCUT] Checking inline availability: room=%s, date=%s, participants=%s",
                    preferred_room_from_msg, event_date_from_msg, participants_from_msg)

        # Set up event_entry with requested_window for evaluate_rooms
        start_time = user_info.get("start_time") or "09:00"
        end_time = user_info.get("end_time") or "18:00"
        event_entry["requested_window"] = {
            "date_iso": event_date_from_msg,
            "start": start_time,
            "end": end_time,
        }
        event_entry["chosen_date"] = event_date_from_msg

        # Evaluate room availability (pass db to check Option/Confirmed bookings)
        try:
            evaluations = evaluate_rooms(event_entry, db=state.db)
            target_eval = next(
                (e for e in evaluations if e.record.name.lower() == str(preferred_room_from_msg).lower()),
                None
            )

            if target_eval and target_eval.status in ("Available", "Option"):
                # Room is available! Set all gatekeeping variables
                logger.info("[Step1][SMART_SHORTCUT] Room %s is %s - jumping to Step 4",
                           preferred_room_from_msg, target_eval.status)

                update_event_metadata(
                    event_entry,
                    chosen_date=event_date_from_msg,
                    date_confirmed=True,
                    locked_room_id=target_eval.record.name,
                    room_status=target_eval.status,
                    room_eval_hash=new_req_hash,
                    current_step=4,
                    thread_state="Awaiting Client",
                    caller_step=None,
                )
                event_entry.setdefault("event_data", {})["Event Date"] = event_date_from_msg
                event_entry.setdefault("event_data", {})["Preferred Room"] = target_eval.record.name
                append_audit_entry(event_entry, 1, 4, "smart_shortcut_room_verified")

                state.current_step = 4
                state.set_thread_state("Awaiting Client")
                state.extras["persist"] = True

                # Store pending decision for Step 4 to use
                event_entry["room_pending_decision"] = {
                    "selected_room": target_eval.record.name,
                    "selected_status": target_eval.status,
                    "missing_products": [p.get("name") for p in target_eval.missing_products] if target_eval.missing_products else [],
                }

                # Store room confirmation prefix for Step 4 (same as Step 3 does)
                # This ensures Step 4 knows room was just confirmed and generates the offer
                participants_count = user_info.get("participants")
                confirmation_intro = (
                    f"Great choice! {target_eval.record.name} on {event_date_from_msg or 'your date'} is confirmed"
                )
                if participants_count:
                    confirmation_intro += f" for your event with {participants_count} guests."
                else:
                    confirmation_intro += "."
                event_entry["room_confirmation_prefix"] = confirmation_intro + "\n\n"
                logger.info("[Step1][SMART_SHORTCUT] Set room_confirmation_prefix for Step 4")

                # Generate Q&A response if detected
                if state.extras.get("general_qna_detected"):
                    unified_detection = state.extras.get("unified_detection") or {}
                    qna_types = unified_detection.get("qna_types") or []
                    if not qna_types:
                        qna_types = _detect_qna_types((state.message.body or "").lower())
                    if qna_types:
                        hybrid_qna_response = generate_hybrid_qna_response(
                            qna_types=qna_types,
                            message_text=state.message.body or "",
                            event_entry=event_entry,
                            db=state.db,
                        )
                        if hybrid_qna_response:
                            state.extras["hybrid_qna_response"] = hybrid_qna_response

                payload = {
                    "client_id": state.client_id,
                    "event_id": event_entry.get("event_id"),
                    "intent": intent.value,
                    "confidence": round(confidence, 3),
                    "locked_room_id": target_eval.record.name,
                    "thread_state": state.thread_state,
                    "persisted": True,
                    "smart_shortcut": True,
                }
                return GroupResult(action="smart_shortcut_to_offer", payload=payload, halt=False)
            else:
                logger.debug("[Step1][SMART_SHORTCUT] Room %s not available (status=%s) - proceeding normally",
                            preferred_room_from_msg, target_eval.status if target_eval else "not found")
        except Exception as ex:
            logger.warning("[Step1][SMART_SHORTCUT] Room evaluation failed: %s - proceeding normally", ex)

    preferences = user_info.get("preferences") or {}
    wish_products = list((preferences.get("wish_products") or []))
    vague_month = user_info.get("vague_month")
    vague_weekday = user_info.get("vague_weekday")
    vague_time = user_info.get("vague_time_of_day")
    week_index = user_info.get("week_index")
    weekdays_hint = user_info.get("weekdays_hint")
    window_scope = user_info.get("window") if isinstance(user_info.get("window"), dict) else None
    metadata_updates: Dict[str, Any] = {}
    if wish_products:
        metadata_updates["wish_products"] = wish_products
    if preferences:
        metadata_updates["preferences"] = preferences
    if vague_month:
        metadata_updates["vague_month"] = vague_month
    if vague_weekday:
        metadata_updates["vague_weekday"] = vague_weekday
    if vague_time:
        metadata_updates["vague_time_of_day"] = vague_time
    if week_index:
        metadata_updates["week_index"] = week_index
    if weekdays_hint:
        metadata_updates["weekdays_hint"] = list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else weekdays_hint
    if window_scope:
        metadata_updates["window_scope"] = {
            key: value
            for key, value in window_scope.items()
            if key in {"month", "week_index", "weekdays_hint"}
        }
    if metadata_updates:
        update_event_metadata(event_entry, **metadata_updates)

    room_choice_selected = state.extras.pop("room_choice_selected", None)
    if room_choice_selected:
        existing_lock = event_entry.get("locked_room_id")
        # If a different room is already locked, DON'T update the lock here.
        # Let the normal workflow continue so change detection can route to Step 3.
        if existing_lock and existing_lock != room_choice_selected:
            logger.debug("[Step1] Room change detected: %s → %s, skipping room_choice_captured",
                        existing_lock, room_choice_selected)
            # Don't return here - let the normal flow continue with change detection
            # The user_info["room"] is already set, so detect_change_type_enhanced will find it
        else:
            pending_info = event_entry.get("room_pending_decision") or {}
            selected_status = None
            if isinstance(pending_info, dict) and pending_info.get("selected_room") == room_choice_selected:
                selected_status = pending_info.get("selected_status")
            status_value = selected_status or "Available"
            chosen_date = (
                event_entry.get("chosen_date")
                or user_info.get("event_date")
                or user_info.get("date")
            )
            # [ARRANGEMENT FLOW BYPASS] If room_pending_decision has missing_products,
            # DON'T auto-advance to step 4. Let step 3 handle arrangement requests.
            # The client may be saying "Room A sounds good, please arrange the flipchart"
            missing_products_for_room = (pending_info or {}).get("missing_products", [])
            if missing_products_for_room:
                logger.debug("[Step1] Room has missing products %s - letting Step 3 handle arrangement",
                            missing_products_for_room)
                # Don't lock or advance - fall through to let step 3 detect arrangement
                # Store room choice for step 3 to use if client confirms without arrangement
                user_info["room"] = room_choice_selected
                user_info["_room_choice_detected"] = True
            else:
                update_event_metadata(
                    event_entry,
                    locked_room_id=room_choice_selected,
                    room_status=status_value,
                    room_eval_hash=event_entry.get("requirements_hash"),
                    caller_step=None,
                    current_step=4,
                    thread_state="Awaiting Client",
                )
                event_entry.setdefault("event_data", {})["Preferred Room"] = room_choice_selected
                append_audit_entry(event_entry, state.current_step or 1, 4, "room_choice_captured")
                state.current_step = 4
                state.caller_step = None
                state.set_thread_state("Awaiting Client")
                state.extras["persist"] = True

                # Store room confirmation prefix for Step 4 (same as Step 3 does)
                # This ensures Step 4 knows room was just confirmed and generates the offer
                participants_count = user_info.get("participants")
                chosen_date_display = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date") or "your date"
                confirmation_intro = f"Great choice! {room_choice_selected} on {chosen_date_display} is confirmed"
                if participants_count:
                    confirmation_intro += f" for your event with {participants_count} guests."
                else:
                    confirmation_intro += "."
                event_entry["room_confirmation_prefix"] = confirmation_intro + "\n\n"
                logger.info("[Step1] Set room_confirmation_prefix for Step 4")

                # [HYBRID Q&A] Generate Q&A response if general Q&A was detected
                # This handles hybrid messages like "Room B looks great + which rooms in February?"
                # Store on state.extras so it survives across steps (routing loop continues to Step 4)
                if state.extras.get("general_qna_detected"):
                    # Try unified_detection first, fall back to keyword detection
                    # (unified_detection runs AFTER intake, so may not be available yet)
                    unified_detection = state.extras.get("unified_detection") or {}
                    qna_types = unified_detection.get("qna_types") or []
                    if not qna_types:
                        # Run keyword-based Q&A type detection directly on message
                        message_text = state.message.body or ""
                        qna_types = _detect_qna_types(message_text.lower())
                        if not qna_types:
                            # Last resort: use generic "general" type
                            qna_types = ["general"]
                    logger.debug("[HYBRID Step1] qna_types=%s", qna_types)
                    if qna_types:
                        message_text = state.message.body or ""
                        hybrid_qna_response = generate_hybrid_qna_response(
                            qna_types=qna_types,
                            message_text=message_text,
                            event_entry=event_entry,
                            db=state.db,
                        )
                        if hybrid_qna_response:
                            state.extras["hybrid_qna_response"] = hybrid_qna_response
                            logger.debug("[Step1] Generated hybrid Q&A response for room shortcut: %s chars",
                                        len(hybrid_qna_response))

                # [ROOM CONFIRMED RESPONSE] Generate draft message for room confirmation
                # This is needed because room_choice_captured bypasses Step 3 where the
                # "Room Confirmed" response would normally be generated
                chosen_date = event_entry.get("chosen_date") or ""
                display_date = format_iso_date_to_ddmmyyyy(chosen_date) if chosen_date else "your date"
                participants = (event_entry.get("requirements") or {}).get("participants", "")
                participants_str = f" for {participants} guests" if participants else ""

                # Get room features for the selected room
                room_features = list_room_features(room_choice_selected)
                features_str = ""
                if room_features:
                    # Join features inline with commas (user preference: no bullets)
                    features_str = f"\n\nFeatures: {', '.join(room_features[:6])}"

                confirmation_body = (
                    f"Great choice! {room_choice_selected} on {display_date} is confirmed{participants_str}."
                    f"{features_str}"
                    f"\n\nI'll prepare the offer for you now."
                )
                draft_message = {
                    "body_markdown": confirmation_body,
                    "step": 4,
                    "topic": "room_confirmed",
                    "headers": ["Room Confirmed"],
                    "thread_state": "Awaiting Client",
                    "requires_approval": False,
                }
                state.add_draft_message(draft_message)
                logger.debug("[Step1] Added Room Confirmed draft for shortcut: %s", room_choice_selected)

                payload = {
                    "client_id": state.client_id,
                    "event_id": event_entry.get("event_id"),
                    "intent": intent.value,
                    "confidence": round(confidence, 3),
                    "locked_room_id": room_choice_selected,
                    "thread_state": state.thread_state,
                    "persisted": True,
                }
                return GroupResult(action="room_choice_captured", payload=payload, halt=False)

    new_preferred_room = requirements.get("preferred_room")

    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1
    detoured_to_step2 = False

    # Use centralized change propagation system for systematic change detection and routing
    # Enhanced detection with dual-condition logic (revision signal + bound target)
    # Skip change detection during billing flow - billing addresses shouldn't trigger date/room changes
    in_billing_flow = (
        event_entry.get("offer_accepted")
        and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    # BUG FIX: Only use message body for change detection, NOT subject.
    # The subject contains system-generated timestamps (e.g., "Client follow-up (2025-12-24 17:18)")
    # which were incorrectly triggering DATE change detection.
    message_text = state.message.body or ""

    # Skip date change detection for deposit payment messages
    # "We paid the deposit on 02.01.2026" - the date is payment date, not event date
    import re
    _deposit_date_pattern = re.compile(
        r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
        re.IGNORECASE
    )
    is_deposit_date_context = bool(message_text and _deposit_date_pattern.search(message_text))
    # Check if this looks like a date change request (even during billing flow)
    # Prefer LLM signal; only fallback to heuristic if unified detection is unavailable.
    from workflows.steps.step5_negotiation.trigger.step5_handler import _looks_like_date_change
    llm_change_request = bool(getattr(unified_detection, "is_change_request", False) if unified_detection else False)
    message_looks_like_date_change = False
    if unified_detection is None:
        message_looks_like_date_change = _looks_like_date_change(message_text)
    change_request_signal = llm_change_request or message_looks_like_date_change

    # GUARD: Skip date change detection when site visit flow is active
    # When client selects a date for site visit, it should NOT update the event date
    from workflows.common.site_visit_state import (
        is_site_visit_active,
        is_site_visit_scheduled,
        is_site_visit_change_request,
    )
    site_visit_active = is_site_visit_active(event_entry)
    # Also check if this is a site visit CHANGE request (when already scheduled)
    site_visit_scheduled = is_site_visit_scheduled(event_entry)
    is_sv_change_request = is_site_visit_change_request(message_text or "")

    if is_deposit_date_context:
        # Deposit payment context - don't detect date changes
        # "We paid the deposit on 02.01.2026" - the date is payment date, not event date
        change_type = None
    elif in_billing_flow and not change_request_signal:
        # In billing flow with normal billing input - skip change detection
        # But if it looks like a date change, let detection run for proper detour
        change_type = None
    else:
        # Pass unified_detection so Q&A messages don't trigger false change detours
        enhanced_result = detect_change_type_enhanced(
            event_entry, user_info, message_text=message_text, unified_detection=unified_detection
        )
        change_type = enhanced_result.change_type if enhanced_result.is_change else None
        # If site visit is active OR it's a site visit change request, suppress date change detection
        # Date in message is for site visit selection/change, not event date change
        suppress_for_sv_active = site_visit_active and change_type and change_type.value == "date"
        suppress_for_sv_change = site_visit_scheduled and is_sv_change_request and change_type and change_type.value == "date"
        if suppress_for_sv_active:
            logger.info("[Step1][SV_GUARD] Site visit active - suppressing date change detection")
            change_type = None
        elif suppress_for_sv_change:
            logger.info("[Step1][SV_GUARD] Site visit change request detected - suppressing event date change detection")
            change_type = None
        logger.debug("[Step1][CHANGE_DETECT] user_info.date=%s, user_info.event_date=%s",
                    user_info.get('date'), user_info.get('event_date'))
        logger.debug("[Step1][CHANGE_DETECT] is_change=%s, change_type=%s",
                    enhanced_result.is_change, change_type)
        logger.debug("[Step1][CHANGE_DETECT] message_text=%s...",
                    message_text[:100] if message_text else 'None')

    # [Q&A DATE GUARD] Don't reset date confirmation if:
    # 1. Q&A is detected (vague month might come from Q&A question, not workflow intent)
    # 2. Date is already confirmed (shouldn't lose confirmed date due to Q&A question)
    # Example: "Room B looks great. Which rooms are available in February next year?"
    # The "February" is for Q&A, not for the main booking flow.
    has_qna_question = state.extras.get("general_qna_detected", False)
    date_already_confirmed = event_entry.get("date_confirmed", False)
    skip_vague_date_reset = has_qna_question and date_already_confirmed

    # [COMPREHENSIVE Q&A GUARD] Pre-compute Q&A status for ALL fallback guards
    # Q&A messages should NEVER trigger step changes, regardless of extracted entities
    # "Are you open on March 15?" should NOT trigger date change
    # "Does Room A have a projector?" should NOT trigger room change
    # "Can you serve 100 people?" should NOT trigger requirements change
    message_text_for_qna = state.message.body or ""
    llm_is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    llm_general_qna = bool(
        getattr(unified_detection, "intent", "") in ("general_qna", "non_event") if unified_detection else False
    )
    is_qna_no_change = has_qna_question or llm_is_question or llm_general_qna
    logger.debug(
        "[Step1][QNA_COMPREHENSIVE_GUARD] has_qna=%s, llm_is_question=%s, llm_general_qna=%s, is_qna_no_change=%s",
        has_qna_question, llm_is_question, llm_general_qna, is_qna_no_change
    )

    if needs_vague_date_confirmation and not in_billing_flow and not skip_vague_date_reset:
        event_entry["range_query_detected"] = True
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
            thread_state="Awaiting Client Response",
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_pending_vague_request")
        detoured_to_step2 = True
        state.set_thread_state("Awaiting Client Response")
    elif needs_vague_date_confirmation and skip_vague_date_reset:
        logger.debug("[Step1] Skipping vague date reset - Q&A detected and date already confirmed")

    # Handle change routing using DAG-based change propagation
    logger.info("[Step1][CHANGE_ROUTING] change_type=%s, previous_step=%s", change_type, previous_step)
    if change_type is not None and previous_step > 1:
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)
        logger.info("[Step1][CHANGE_ROUTING] decision: next_step=%s, caller_step=%s",
                   decision.next_step, decision.updated_caller_step)

        # Apply the routing decision
        if decision.updated_caller_step is not None and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)
            trace_marker(
                _thread_id(state),
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": previous_step,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                },
                owner_step="Step1_Intake",
            )

        if decision.next_step != previous_step:
            update_event_metadata(event_entry, current_step=decision.next_step)
            audit_reason = f"{change_type.value}_change_detected"
            append_audit_entry(event_entry, previous_step, decision.next_step, audit_reason)

            # [BILLING FLOW DETOUR FIX] When a date change is detected during billing flow,
            # we must clear awaiting_billing_for_accept so that correct_billing_flow_step()
            # won't force step back to 5. The client is no longer providing billing for
            # the old offer - they want a new date, which means a new offer.
            if in_billing_flow and change_type.value == "date":
                billing_req = event_entry.get("billing_requirements") or {}
                billing_req["awaiting_billing_for_accept"] = False
                event_entry["billing_requirements"] = billing_req
                # Also clear offer_accepted since the offer needs to be regenerated
                event_entry["offer_accepted"] = False
                logger.info("[Step1][DETOUR_FIX] Cleared billing flow state for date change detour")

            # Handle room lock based on change type
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    if change_type.value == "date":
                        # DATE change to Step 2: KEEP locked_room_id so Step 3 can fast-skip
                        # if the room is still available on the new date
                        # CRITICAL: Also invalidate offer_hash - a new offer with the new date
                        # must be generated even if the room is still available
                        update_event_metadata(
                            event_entry,
                            date_confirmed=False,
                            room_eval_hash=None,  # Invalidate for re-verification
                            offer_hash=None,  # Invalidate offer - must regenerate with new date
                            # NOTE: Do NOT clear locked_room_id for date changes
                        )
                    else:
                        # REQUIREMENTS change to Step 2: clear room lock since room may no longer fit
                        # EXCEPTION: Don't clear room lock if sourcing was completed for this room
                        sourced = event_entry.get("sourced_products")
                        if sourced and sourced.get("room") == event_entry.get("locked_room_id"):
                            update_event_metadata(
                                event_entry,
                                date_confirmed=False,
                                room_eval_hash=None,
                            )
                        else:
                            update_event_metadata(
                                event_entry,
                                date_confirmed=False,
                                room_eval_hash=None,
                                locked_room_id=None,
                            )
                    detoured_to_step2 = True
                elif decision.next_step == 3:
                    # Going to Step 3 for requirements change: clear room lock but KEEP date confirmed
                    # EXCEPTION: Don't clear room lock if sourcing was completed for this room
                    sourced = event_entry.get("sourced_products")
                    if sourced and sourced.get("room") == event_entry.get("locked_room_id"):
                        # Sourcing completed - protect room lock, just invalidate hash
                        update_event_metadata(
                            event_entry,
                            room_eval_hash=None,
                        )
                    else:
                        update_event_metadata(
                            event_entry,
                            room_eval_hash=None,
                            locked_room_id=None,
                        )
                    # Set change_detour flag so Step 3 bypasses Q&A path and goes to room evaluation
                    state.extras["change_detour"] = True

    # Fallback: legacy logic for cases not handled by change propagation
    # Skip during billing flow, deposit payment context, OR site visit flow
    # When site visit is active, date in message is for site visit selection, not event date change
    # Also skip when this is a site visit CHANGE request (status=scheduled + explicit change intent)
    # [Q&A GUARD] Also skip for Q&A messages - "Are you open on March 15?" is NOT a date change request
    elif new_date and new_date != event_entry.get("chosen_date") and not in_billing_flow and not is_deposit_date_context and not site_visit_active and not (site_visit_scheduled and is_sv_change_request) and not is_qna_no_change:
        # Check if new_date is in the past (normalize first to handle DD.MM.YYYY format)
        normalized_new_date = normalize_iso_candidate(new_date)
        date_is_past = iso_date_is_past(normalized_new_date) if normalized_new_date else False

        if date_is_past:
            # Past date - route to Step 2 for alternatives
            logger.info("[Step1] Date %s is in the past - routing to Step 2", new_date)
            update_event_metadata(
                event_entry,
                chosen_date=None,
                date_confirmed=False,
                current_step=2,
                room_eval_hash=None,
                locked_room_id=None,
            )
            state.extras["past_date_rejected"] = new_date
            append_audit_entry(event_entry, previous_step, 2, "past_date_rejected")
            detoured_to_step2 = True
        elif (
            previous_step not in (None, 1, 2)
            and event_entry.get("caller_step") is None
        ):
            update_event_metadata(event_entry, caller_step=previous_step)
            if previous_step <= 1:
                update_event_metadata(
                    event_entry,
                    chosen_date=new_date,
                    date_confirmed=True,
                    current_step=3,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                event_entry.setdefault("event_data", {})["Event Date"] = new_date
                append_audit_entry(event_entry, previous_step, 3, "date_updated_initial")
                detoured_to_step2 = False
            else:
                update_event_metadata(
                    event_entry,
                    chosen_date=new_date,
                    date_confirmed=False,
                    current_step=2,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                event_entry.setdefault("event_data", {})["Event Date"] = new_date
                append_audit_entry(event_entry, previous_step, 2, "date_updated")
                detoured_to_step2 = True
        elif previous_step <= 1:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=True,
                current_step=3,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 3, "date_updated_initial")
            detoured_to_step2 = False
        else:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=False,
                current_step=2,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 2, "date_updated")
            detoured_to_step2 = True

    # Handle missing date (initial flow, not a change)
    if needs_vague_date_confirmation:
        new_date = None
    if not new_date and not event_entry.get("chosen_date") and change_type is None:
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_missing")
        detoured_to_step2 = True

    # Fallback: requirements change detection (legacy)
    # FIX: Skip hash mismatch routing for Q&A questions - extracted products shouldn't trigger step 3
    # "Does Room A have a projector?" extracts "projector" but this is NOT a change request
    hash_check = prev_req_hash is not None and prev_req_hash != new_req_hash and not detoured_to_step2 and change_type is None
    if hash_check:
        if is_qna_no_change:
            logger.debug(
                "[Step1][HASH_QNA_GUARD] Skipping requirements hash routing - Q&A question detected: "
                "qna=%s, llm_is_question=%s, prev_hash=%s, new_hash=%s",
                has_qna_question, llm_is_question, prev_req_hash[:8] if prev_req_hash else None,
                new_req_hash[:8] if new_req_hash else None
            )
        else:
            target_step = 3
            if previous_step != target_step and event_entry.get("caller_step") is None:
                update_event_metadata(event_entry, caller_step=previous_step)
                update_event_metadata(event_entry, current_step=target_step)
                append_audit_entry(event_entry, previous_step, target_step, "requirements_updated")
                # Clear stale negotiation state - old offer no longer valid after requirements change
                event_entry.pop("negotiation_pending_decision", None)

    # Fallback: room change detection (legacy)
    # Skip room change detection if in billing flow - billing addresses shouldn't trigger room changes
    in_billing_flow_for_room = (
        event_entry.get("offer_accepted")
        and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    logger.debug(
        "[Step1][ROOM_ROUTE_CHECK] new_preferred_room=%s, locked_room_id=%s, change_type=%s, is_qna_no_change=%s, current_step=%s",
        new_preferred_room, event_entry.get("locked_room_id"), change_type, is_qna_no_change, event_entry.get("current_step")
    )
    room_check = new_preferred_room and new_preferred_room != event_entry.get("locked_room_id") and change_type is None
    if room_check:
        # Don't route to Step 3 for Q&A questions - room mentions in questions are NOT change requests
        if is_qna_no_change:
            logger.debug(
                "[Step1][ROOM_QNA_GUARD] Skipping room routing - Q&A question detected: "
                "qna=%s, llm_is_question=%s, room=%s",
                has_qna_question, llm_is_question, new_preferred_room
            )
        elif not detoured_to_step2 and not in_billing_flow_for_room:
            prev_step_for_room = event_entry.get("current_step") or previous_step
            if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
                update_event_metadata(event_entry, caller_step=prev_step_for_room)
                update_event_metadata(event_entry, current_step=3)
                append_audit_entry(event_entry, prev_step_for_room, 3, "room_preference_updated")

    tag_message(event_entry, message_payload.get("msg_id"))

    if not event_entry.get("thread_state"):
        update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    state.extras["persist"] = True

    # Handle hybrid messages: booking intent + Q&A questions in same message
    # e.g., "Book room for April 5 + what menu options do you have?"
    # Store on state.extras so it survives across steps
    if state.extras.get("general_qna_detected") and not state.extras.get("hybrid_qna_response"):
        # Try unified_detection first, fall back to keyword detection
        unified_detection = state.extras.get("unified_detection") or {}
        qna_types = unified_detection.get("qna_types") or []
        if not qna_types:
            # Run keyword-based Q&A type detection directly on message
            message_text = state.message.body or ""
            qna_types = _detect_qna_types(message_text.lower())
            if not qna_types:
                qna_types = ["general"]
        if qna_types:
            message_text = state.message.body or ""
            hybrid_qna_response = generate_hybrid_qna_response(
                qna_types=qna_types,
                message_text=message_text,
                event_entry=event_entry,
                db=state.db,
            )
            if hybrid_qna_response:
                state.extras["hybrid_qna_response"] = hybrid_qna_response

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": intent.value,
        "confidence": round(confidence, 3),
        "user_info": user_info,
        "context": context,
        "persisted": True,
        "current_step": event_entry.get("current_step"),
        "caller_step": event_entry.get("caller_step"),
        "thread_state": event_entry.get("thread_state"),
        "draft_messages": state.draft_messages,
    }
    trace_state(
        _thread_id(state),
        "Step1_Intake",
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "current_step": event_entry.get("current_step"),
            "caller_step": event_entry.get("caller_step"),
            "thread_state": event_entry.get("thread_state"),
        },
    )
    return GroupResult(action="intake_complete", payload=payload)


def _ensure_event_record(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """[Trigger] Create or refresh the event record for the intake step."""

    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    event_data = default_event_record(user_info, message_payload, received_date)

    last_event = last_event_for_email(state.db, state.client_id)
    if not last_event:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    # Check if we should create a NEW event instead of reusing the existing one
    # This happens when:
    # 1. The new message has a DIFFERENT event date than the existing event (new inquiry)
    # 2. The existing event is in a terminal state (Confirmed, site visit scheduled)
    should_create_new = False
    new_event_date = event_data.get("Event Date")
    existing_event_date = last_event.get("chosen_date") or (last_event.get("event_data") or {}).get("Event Date")

    # Different dates = new inquiry, but ONLY if BOTH dates are actual dates
    # (not "Not specified" default value) AND there's no DATE CHANGE intent
    placeholder_values = ("Not specified", "not specified", None, "")
    new_date_is_actual = new_event_date and new_event_date not in placeholder_values
    existing_date_is_actual = existing_event_date and existing_event_date not in placeholder_values

    # Check if this is a DATE CHANGE request vs a NEW inquiry
    # Date changes have revision signals ("change", "switch", "actually", "instead", etc.)
    message_text = (state.message.body or "") + " " + (state.message.subject or "")
    is_date_change_request = has_revision_signal(message_text)

    # Check if message is a deposit/payment date mention (not event date)
    # "We paid the deposit on 02.01.2026" - payment dates should NOT trigger new events
    import re
    _deposit_date_pattern = re.compile(
        r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
        re.IGNORECASE
    )
    is_deposit_payment_date = bool(message_text and _deposit_date_pattern.search(message_text))

    # GUARD: Skip date change logic when site visit flow is active
    # The date in message is for site visit selection, not event date change
    from workflows.common.site_visit_state import is_site_visit_active
    site_visit_active_for_new_check = is_site_visit_active(last_event)

    if new_date_is_actual and existing_date_is_actual and new_event_date != existing_event_date:
        if site_visit_active_for_new_check:
            # Site visit is active - date is for site visit, not event date change
            # Skip the "different date = new event" logic entirely
            logger.info("[STEP1][SV_GUARD] Site visit active - skipping date change/new event logic")
        elif is_date_change_request or is_deposit_payment_date:
            # This is a date CHANGE on existing event - don't create new event
            trace_db_write(_thread_id(state), "Step1_Intake", "date_change_detected", {
                "reason": "date_change_request",
                "old_date": existing_event_date,
                "new_date": new_event_date,
            })
            # Don't set should_create_new = True; continue with existing event
            # DON'T update date here - let the proper detour logic at line ~1224 handle it
            # The detour will: Step 2 (confirm date) → Step 3 (check room) → Step 4 (new offer)
            logger.info("[STEP1][DATE_CHANGE] Detected date change from %s to %s, will route via detour",
                        existing_event_date, new_event_date)
        else:
            # This is a genuine NEW inquiry with a different date
            should_create_new = True
            trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
                "reason": "different_date",
                "new_date": new_event_date,
                "existing_date": existing_event_date,
            })

    # Terminal states - don't reuse
    existing_status = last_event.get("status", "").lower()
    if existing_status in ("confirmed", "completed", "cancelled"):
        should_create_new = True
        trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
            "reason": "terminal_status",
            "status": existing_status,
        })

    # Offer already accepted - this event is essentially complete
    # UNLESS the client is still providing billing/deposit info for the accepted offer
    # In that case, we should continue the existing flow, not start fresh
    if last_event.get("offer_accepted"):
        # Check if this is a continuation of the accepted offer flow
        billing_reqs = last_event.get("billing_requirements") or {}
        awaiting_billing = billing_reqs.get("awaiting_billing_for_accept", False)
        # FIX: Use correct field name (deposit_info, not deposit_state)
        deposit_info = last_event.get("deposit_info") or {}
        awaiting_deposit = deposit_info.get("deposit_required") and not deposit_info.get("deposit_paid")

        # Also check if the message looks like billing info (address, postal code, etc.)
        message_body = (state.message.body or "").strip().lower()
        looks_like_billing = _looks_like_billing_fragment(message_body) if message_body else False

        # Check if this is a synthetic deposit payment notification
        # (comes from pay_deposit endpoint with deposit_just_paid flag)
        deposit_just_paid = state.message.extras.get("deposit_just_paid", False)

        # Check if message includes explicit event_id matching this event
        msg_event_id = state.message.extras.get("event_id")
        event_id_matches = msg_event_id and msg_event_id == last_event.get("event_id")

        # Check if this is a revision/change request (date, room, participants change)
        # Messages like "Can we switch to Room B?" or "Change the date to March 20"
        # should continue with the existing event, not create a new one
        message_text = (state.message.body or "") + " " + (state.message.subject or "")
        is_revision_message = has_revision_signal(message_text)

        # Only create new event if this is truly a NEW inquiry, not a billing/deposit/revision follow-up
        if awaiting_billing or awaiting_deposit or looks_like_billing or deposit_just_paid or event_id_matches or is_revision_message:
            # Continue with existing event - don't create new
            trace_db_write(_thread_id(state), "Step1_Intake", "offer_accepted_continue", {
                "reason": "billing_or_deposit_or_revision_followup",
                "awaiting_billing": awaiting_billing,
                "awaiting_deposit": awaiting_deposit,
                "looks_like_billing": looks_like_billing,
                "deposit_just_paid": deposit_just_paid,
                "event_id_matches": event_id_matches,
                "is_revision_message": is_revision_message,
            })
        else:
            # New inquiry from same client after offer was accepted - create fresh event
            should_create_new = True
            trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
                "reason": "offer_already_accepted",
                "event_id": last_event.get("event_id"),
            })

    # Site visit terminal states - the booking is finalized, create new event for new inquiries
    # "proposed" and "scheduled" are MID-FLOW states (client is actively engaged)
    # Only treat completed/declined/no_show as terminal states
    visit_state = last_event.get("site_visit_state") or {}
    visit_status = visit_state.get("status")
    if visit_status in ("completed", "declined", "no_show"):
        should_create_new = True
        trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
            "reason": f"site_visit_{visit_status}",
        })

    if should_create_new:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {
            "event_id": event_entry.get("event_id"),
            "reason": "new_inquiry_detected",
        })
        return event_entry

    idx = find_event_idx_by_id(state.db, last_event["event_id"])
    if idx is None:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    state.updated_fields = update_event_entry(state.db, idx, event_data)
    event_entry = state.db["events"][idx]
    # Ensure thread_id is set for backward compatibility with existing events
    if not event_entry.get("thread_id"):
        event_entry["thread_id"] = _thread_id(state)
    trace_db_write(
        _thread_id(state),
        "Step1_Intake",
        "db.events.update",
        {"event_id": event_entry.get("event_id"), "updated": list(state.updated_fields)},
    )
    update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
    return event_entry


def _trace_user_entities(state: WorkflowState, message_payload: Dict[str, Any], user_info: Dict[str, Any], owner_step: str) -> None:
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
    if email:
        trace_entity(thread_id, owner_step, "email", "message_header", True, {"value": email})

    event_date = user_info.get("event_date") or user_info.get("date")
    if event_date:
        trace_entity(thread_id, owner_step, "event_date", "llm", True, {"value": event_date})

    participants = user_info.get("participants") or user_info.get("number_of_participants")
    if participants:
        trace_entity(thread_id, owner_step, "participants", "llm", True, {"value": participants})


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
