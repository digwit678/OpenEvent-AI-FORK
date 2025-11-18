"""
Change Propagation & DAG-based Routing (V4 Authoritative)

This module implements the deterministic change-routing logic per v4_dag_and_change_rules.md.
When a confirmed/captured variable is updated (date, room, requirements, products, offer),
ONLY the dependent steps re-run, using hash guards to avoid unnecessary recomputation.

Dependency DAG:
    participants ┐
    seating_layout ┼──► requirements ──► requirements_hash
    duration ┘
    special_requirements ┘
            │
            ▼
    chosen_date ───────────────────────────► Room Evaluation ──► locked_room_id
            │                                    │
            │                                    └────────► room_eval_hash
            ▼
    Offer Composition ──► selected_products ──► offer_hash
            ▼
    Confirmation / Deposit

Detour Flow:
    [ c a l l e r ] ──(change detected)──► [ owner step ]
    ▲                                           │
    └──────────(resolved + hashes)──────────────┘
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ChangeType(Enum):
    """Types of changes that can trigger re-evaluation."""

    DATE = "date"                    # chosen_date changed
    ROOM = "room"                    # locked_room_id requested change
    REQUIREMENTS = "requirements"    # participants/layout/duration/special changed
    PRODUCTS = "products"            # selected_products/catering changed
    COMMERCIAL = "commercial"        # pure price/terms negotiation
    DEPOSIT = "deposit"              # reservation/deposit/option operations
    SITE_VISIT = "site_visit"        # site visit date/time change
    CLIENT_INFO = "client_info"      # billing address, contact info, company details


@dataclass
class NextStepDecision:
    """Decision on which step to run next after a change."""

    next_step: int                          # Target step number (2-7)
    maybe_run_step3: bool = False           # Whether Step 3 might be needed
    updated_caller_step: Optional[int] = None  # New caller_step value
    skip_reason: Optional[str] = None       # Reason for skipping (e.g., "hash_match")
    needs_reeval: bool = True               # Whether re-evaluation is actually needed

    def __str__(self) -> str:
        parts = [f"next_step={self.next_step}"]
        if self.maybe_run_step3:
            parts.append("maybe_step3=True")
        if self.updated_caller_step:
            parts.append(f"caller={self.updated_caller_step}")
        if self.skip_reason:
            parts.append(f"skip={self.skip_reason}")
        if not self.needs_reeval:
            parts.append("needs_reeval=False")
        return f"NextStepDecision({', '.join(parts)})"


# ============================================================================
# SHARED HELPER FUNCTIONS FOR CHANGE DETECTION
# ============================================================================


def has_requirement_update(event_state: Dict[str, Any], user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any requirement field updates.

    Args:
        event_state: Current event entry
        user_info: Extracted user information

    Returns:
        True if any requirement field differs from the current event_state
    """
    requirements = event_state.get("requirements") or {}
    duration_snapshot = requirements.get("event_duration") or {}
    requirement_fields = [
        "participants", "number_of_participants",
        "layout", "type", "seating_layout",
        "start_time", "end_time", "duration",
        "notes", "special_requirements"
    ]
    for field in requirement_fields:
        value = user_info.get(field)
        if value is None:
            continue

        # Map incoming user_info fields onto canonical requirement keys
        if field in ("participants", "number_of_participants"):
            current = requirements.get("number_of_participants")
        elif field in ("layout", "type", "seating_layout"):
            current = requirements.get("seating_layout")
        elif field in ("notes", "special_requirements"):
            current = requirements.get("special_requirements")
        elif field in ("start_time", "end_time", "duration"):
            new_start = user_info.get("start_time")
            new_end = user_info.get("end_time")
            current_start = duration_snapshot.get("start")
            current_end = duration_snapshot.get("end")

            # Treat any explicit change to start/end as a requirement update
            if new_start is not None and str(new_start) != str(current_start):
                return True
            if new_end is not None and str(new_end) != str(current_end):
                return True
            continue
        else:
            current = None

        if current is None and value not in (None, ""):
            return True
        if current is not None and str(current) != str(value):
            return True

    return False


def has_product_update(user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any product/catering field updates.

    Args:
        user_info: Extracted user information

    Returns:
        True if any product field is present in user_info
    """
    product_fields = [
        "products", "catering", "menu", "wine", "beverage",
        "products_add", "products_remove"
    ]
    return any(user_info.get(field) is not None for field in product_fields)


def has_client_info_update(user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any client information field updates.

    Args:
        user_info: Extracted user information

    Returns:
        True if any client info field is present in user_info
    """
    client_fields = [
        "billing_address", "billing_name", "company", "company_name",
        "vat", "vat_number", "phone", "email", "contact"
    ]
    return any(user_info.get(field) is not None for field in client_fields)


def extract_change_verbs_near_noun(message_text: str, target_nouns: List[str]) -> bool:
    """
    Check if change verbs appear near target nouns using regex.

    Example: "upgrade the coffee package" → True (upgrade + coffee/package)
    Example: "what coffee do you have" → False (no change verb)

    Args:
        message_text: Message text to search
        target_nouns: List of target nouns to look for near change verbs

    Returns:
        True if change verb appears within 5 words of target noun
    """
    if not message_text:
        return False

    text_lower = message_text.lower()

    # Change verb patterns
    change_verbs = [
        "change", "switch", "modify", "update", "adjust", "upgrade",
        "downgrade", "swap", "replace", "amend", "revise", "alter",
        "reschedule", "move"
    ]

    # Create pattern: (change_verb) .{0,50} (target_noun) OR (target_noun) .{0,50} (change_verb)
    # This allows up to ~10 words (5 chars/word avg) between verb and noun
    for verb in change_verbs:
        for noun in target_nouns:
            # Verb before noun: "upgrade ... package"
            pattern_forward = rf"\b{re.escape(verb)}\b.{{0,50}}\b{re.escape(noun)}\b"
            # Noun before verb: "package ... upgrade"
            pattern_backward = rf"\b{re.escape(noun)}\b.{{0,50}}\b{re.escape(verb)}\b"

            if re.search(pattern_forward, text_lower) or re.search(pattern_backward, text_lower):
                return True

    return False


def route_change_on_updated_variable(
    event_state: Dict[str, Any],
    change_type: ChangeType,
    *,
    from_step: Optional[int] = None,
) -> NextStepDecision:
    """
    Route a change to the correct owning step per v4 DAG change matrix.

    Args:
        event_state: Event entry dict containing:
            - current_step: int
            - caller_step: Optional[int]
            - chosen_date: str
            - date_confirmed: bool
            - requirements_hash: str
            - room_eval_hash: str
            - locked_room_id: str
            - offer_hash: str (if applicable)
        change_type: Type of change that occurred
        from_step: Current step making the change (if known)

    Returns:
        NextStepDecision with routing information

    Behavior per v4 DAG:
        - DATE → Step 2 (Date Confirmation)
        - ROOM → Step 3 (Room Availability)
        - REQUIREMENTS → Step 3 (if requirements_hash ≠ room_eval_hash)
        - PRODUCTS → Step 4 (stay in products mini-flow)
        - COMMERCIAL → Step 5 (Negotiation)
        - DEPOSIT → Step 7 (Confirmation)
    """
    current_step = event_state.get("current_step") or 1
    caller_step = event_state.get("caller_step")
    requirements_hash_val = event_state.get("requirements_hash")
    room_eval_hash_val = event_state.get("room_eval_hash")
    date_confirmed = bool(event_state.get("date_confirmed"))
    locked_room_id = event_state.get("locked_room_id")

    # Determine the caller_step for detours
    # If not already set, use from_step or current_step
    if caller_step is None:
        new_caller = from_step if from_step is not None else current_step
    else:
        new_caller = caller_step

    # DATE CHANGE → Always detour to Step 2
    if change_type == ChangeType.DATE:
        return NextStepDecision(
            next_step=2,
            maybe_run_step3=True,  # Step 3 might run after date confirmation
            updated_caller_step=new_caller if new_caller != 2 else None,
            needs_reeval=True,
        )

    # ROOM CHANGE → Always detour to Step 3
    elif change_type == ChangeType.ROOM:
        return NextStepDecision(
            next_step=3,
            maybe_run_step3=False,  # We ARE Step 3
            updated_caller_step=new_caller if new_caller != 3 else None,
            needs_reeval=True,
        )

    # REQUIREMENTS CHANGE → Step 3 if hash mismatch
    elif change_type == ChangeType.REQUIREMENTS:
        # Check if requirements actually changed
        if requirements_hash_val and room_eval_hash_val:
            hashes_match = str(requirements_hash_val) == str(room_eval_hash_val)
            if hashes_match:
                # Fast-skip: requirements didn't actually change
                return NextStepDecision(
                    next_step=new_caller if new_caller else 4,
                    maybe_run_step3=False,
                    updated_caller_step=None,
                    skip_reason="requirements_hash_match",
                    needs_reeval=False,
                )

        # Requirements changed → detour to Step 3
        return NextStepDecision(
            next_step=3,
            maybe_run_step3=False,
            updated_caller_step=new_caller if new_caller != 3 else None,
            needs_reeval=True,
        )

    # PRODUCTS CHANGE → Stay in Step 4 products mini-flow
    elif change_type == ChangeType.PRODUCTS:
        # Products are confined to Step 4; no structural dependencies upward
        return NextStepDecision(
            next_step=4,
            maybe_run_step3=False,
            updated_caller_step=None,  # Don't set caller for products loop
            skip_reason="products_only",
            needs_reeval=True,  # Still need to recompute offer
        )

    # COMMERCIAL CHANGE → Step 5 (Negotiation) only
    elif change_type == ChangeType.COMMERCIAL:
        return NextStepDecision(
            next_step=5,
            maybe_run_step3=False,
            updated_caller_step=None,
            needs_reeval=True,
        )

    # DEPOSIT/RESERVATION CHANGE → Step 7 (Confirmation) only
    elif change_type == ChangeType.DEPOSIT:
        return NextStepDecision(
            next_step=7,
            maybe_run_step3=False,
            updated_caller_step=None,
            needs_reeval=True,
        )

    # SITE VISIT CHANGE → Step 7 (Confirmation) only
    elif change_type == ChangeType.SITE_VISIT:
        return NextStepDecision(
            next_step=7,
            maybe_run_step3=False,
            updated_caller_step=None,
            skip_reason="site_visit_reschedule",
            needs_reeval=True,
        )

    # CLIENT INFO CHANGE → Stay in current step, update in place
    elif change_type == ChangeType.CLIENT_INFO:
        return NextStepDecision(
            next_step=current_step,  # No routing needed
            maybe_run_step3=False,
            updated_caller_step=None,
            skip_reason="client_info_update",
            needs_reeval=False,  # Local update only
        )

    # Fallback: shouldn't reach here
    return NextStepDecision(
        next_step=current_step,
        maybe_run_step3=False,
        updated_caller_step=None,
        skip_reason="unknown_change_type",
        needs_reeval=False,
    )


def detect_change_type(
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    message_text: Optional[str] = None,
) -> Optional[ChangeType]:
    """
    Detect which type of change occurred based on user_info and event state.

    Args:
        event_state: Current event entry
        user_info: Extracted user information from message
        message_text: Optional message text for heuristic detection

    Returns:
        ChangeType if a change is detected, None otherwise

    Detection Rules (PRECISE PATTERN):
        Change fires ONLY when:
        1. Confirmed/existing variable is mentioned in message
        2. AND change intent signals present ("change", "switch", "actually", "instead")
        3. AND/OR new value extracted in user_info

        Supported Change Types (ALL gatekeeping variables):
        - DATE: "Can we change the date to March 5th?" ✅
        - ROOM: "Let's switch to Sky Loft instead" ✅
        - REQUIREMENTS: "Actually we're 50 people now" ✅
        - PRODUCTS: "Add Prosecco to the order" ✅
        - COMMERCIAL: "Could you do CHF 3000 instead?" ✅
        - DEPOSIT: "I'd like to proceed with the deposit" ✅
        - SITE_VISIT: "Can we reschedule the site visit to Tuesday?" ✅
        - CLIENT_INFO: "Update billing address to Zurich HQ" ✅

        Examples that DON'T fire (no change intent):
        - "What's the total price?" ❌
        - "When is the deposit due?" ❌
        - "How many people can the room hold?" ❌
    """
    date_confirmed = bool(event_state.get("date_confirmed"))
    chosen_date = event_state.get("chosen_date")
    locked_room_id = event_state.get("locked_room_id")
    current_step = event_state.get("current_step") or 1

    # Prepare message text for pattern matching
    text_lower = message_text.lower() if message_text else ""

    # === CHANGE INTENT SIGNALS (EXPANDED) ===
    # Explicit change verbs
    change_verbs = [
        "change", "switch", "modify", "update", "adjust", "move to", "shift",
        "upgrade", "downgrade", "swap", "replace", "amend", "revise", "alter",
        "reschedule", "move", "drop", "reduce", "lower", "increase", "raise"
    ]
    # Redefinition markers
    redefinition_markers = [
        "actually", "instead", "rather", "correction", "make it", "make that",
        "in fact", "no wait", "sorry", "i meant", "to be clear", "let me correct"
    ]
    # Comparative language
    comparative = [
        "different", "another", "new", "alternate", "alternative",
        "better", "larger", "smaller", "bigger", "fewer", "more"
    ]
    # Question patterns requesting change
    change_questions = [
        "can we change", "could we change", "is it possible to change",
        "would it be possible", "can i change", "could i change",
        "what if we", "how about", "could you", "would you",
        "can we", "can you", "could we", "could you do"
    ]

    def has_change_intent(text: str) -> bool:
        """Check if text contains change intent signals."""
        return (
            any(verb in text for verb in change_verbs) or
            any(marker in text for marker in redefinition_markers) or
            any(comp in text for comp in comparative) or
            any(question in text for question in change_questions)
        )

    # === DATE CHANGE ===
    # Pattern: confirmed date mentioned + change intent + new date value
    user_date = user_info.get("date") or user_info.get("event_date")
    if user_date and date_confirmed and chosen_date:
        # New value extraction is present
        if user_date != chosen_date:
            # Check for date mention + change intent in message
            date_keywords = ["date", "day", "when", chosen_date.replace(".", "/")]
            date_mentioned = any(keyword in text_lower for keyword in date_keywords)

            if date_mentioned and has_change_intent(text_lower):
                return ChangeType.DATE
            # Also fire if new date extracted without explicit intent (strong signal)
            elif date_mentioned:
                return ChangeType.DATE

    # === ROOM CHANGE ===
    # Pattern: room mentioned + change intent + new room value
    user_room = user_info.get("room") or user_info.get("preferred_room")
    if user_room and locked_room_id:
        if str(user_room).strip().lower() != str(locked_room_id).strip().lower():
            # Check for room mention + change intent
            room_keywords = ["room", "space", "venue", locked_room_id.lower()]
            room_mentioned = any(keyword in text_lower for keyword in room_keywords)

            if room_mentioned and has_change_intent(text_lower):
                return ChangeType.ROOM
            # Also fire if new room extracted (strong signal)
            elif room_mentioned:
                return ChangeType.ROOM
            # Fire if new room extracted + change intent, even without explicit room mention
            elif has_change_intent(text_lower):
                return ChangeType.ROOM

    # === REQUIREMENTS CHANGE ===
    # Pattern: requirement field mentioned + change intent + new value
    has_req_change = has_requirement_update(event_state, user_info)

    if has_req_change and locked_room_id:
        # Check for requirement mention + change intent
        req_keywords = ["people", "guests", "participants", "attendees", "capacity",
                        "layout", "setup", "time", "duration", "requirement"]
        req_mentioned = any(keyword in text_lower for keyword in req_keywords)

        if req_mentioned and has_change_intent(text_lower):
            return ChangeType.REQUIREMENTS
        # Also fire if new requirement extracted (strong signal)
        elif req_mentioned:
            return ChangeType.REQUIREMENTS
        # Fire if requirement field extracted + change intent, even without explicit mention
        elif has_change_intent(text_lower):
            return ChangeType.REQUIREMENTS

    # === PRODUCTS CHANGE ===
    # Pattern: product mentioned + change intent + new value
    has_product_change = has_product_update(user_info)

    if has_product_change and current_step >= 4:
        # Check for product mention + change intent (EXPANDED keywords)
        product_keywords = [
            "product", "catering", "menu", "food", "drink", "wine", "beverage",
            "coffee", "prosecco", "tea", "juice", "water", "snack", "breakfast",
            "lunch", "dinner", "appetizer", "dessert", "package", "setup",
            "add", "remove", "include", "upgrade", "premium", "deluxe", "standard"
        ]
        product_mentioned = any(keyword in text_lower for keyword in product_keywords)

        if product_mentioned and has_change_intent(text_lower):
            return ChangeType.PRODUCTS
        # Also fire if explicit add/remove in user_info (strong signal)
        elif user_info.get("products_add") or user_info.get("products_remove"):
            return ChangeType.PRODUCTS
        # Regex pattern: change verb near product noun
        elif extract_change_verbs_near_noun(text_lower, product_keywords):
            return ChangeType.PRODUCTS

    # === COMMERCIAL CHANGE ===
    # Pattern: price/commercial term mentioned + change intent (NOT just questions)
    if message_text and current_step >= 5:
        # EXPANDED keywords for commercial/pricing changes
        commercial_keywords = [
            "price", "discount", "cheaper", "negotiate", "budget",
            "cost", "expensive", "payment terms", "total", "amount",
            "rate", "fee", "charge", "pricing", "quote", "estimate",
            "reduce", "lower", "decrease", "increase", "adjust price",
            "financial", "affordability", "affordable", "value", "competitive"
        ]
        commercial_mentioned = any(keyword in text_lower for keyword in commercial_keywords)

        # Check for currency mentions (CHF, EUR, USD, $, €, etc.) - strong price signal
        currency_patterns = ["chf", "eur", "usd", "$", "€", "£", "fr.", "francs"]
        has_currency = any(curr in text_lower for curr in currency_patterns)

        # ONLY fire if change intent is present (prevents "What's the price?" false positives)
        if commercial_mentioned and has_change_intent(text_lower):
            return ChangeType.COMMERCIAL
        # Fire if currency + change intent (e.g., "Could you do CHF 3000?")
        elif has_currency and has_change_intent(text_lower):
            return ChangeType.COMMERCIAL

        # Also check for explicit counter-offer language (EXPANDED)
        counter_signals = [
            "counter", "offer", "can you do", "would you accept",
            "how about", "what if we", "lower the", "reduce the",
            "meet us at", "work with", "budget is", "max we can do",
            "willing to pay", "comfortable with"
        ]
        if any(signal in text_lower for signal in counter_signals):
            return ChangeType.COMMERCIAL

    # === DEPOSIT CHANGE ===
    # Pattern: deposit/reservation term mentioned + action intent (NOT just questions)
    if message_text and current_step >= 7:
        # EXPANDED keywords for deposit/payment
        deposit_keywords = [
            "deposit", "reservation", "reserve", "option", "hold",
            "payment", "invoice", "upfront", "prepayment", "advance payment",
            "down payment", "initial payment", "partial payment", "installment",
            "pay now", "settle", "transfer", "wire", "book", "booking"
        ]
        deposit_mentioned = any(keyword in text_lower for keyword in deposit_keywords)

        # ONLY fire if change intent OR action verbs present (prevents "When is deposit due?" false positives)
        action_verbs = [
            "want to", "would like to", "ready to", "proceed with",
            "let's", "i'll", "we'll", "confirm", "book", "finalize",
            "go ahead", "complete", "process", "submit", "send"
        ]
        has_action_intent = any(verb in text_lower for verb in action_verbs)

        if deposit_mentioned and (has_change_intent(text_lower) or has_action_intent):
            return ChangeType.DEPOSIT

    # === SITE VISIT CHANGE ===
    # Pattern: site visit mentioned + date/time change intent
    if message_text and current_step >= 7:
        site_visit_keywords = ["site visit", "visit", "tour", "walkthrough", "viewing", "see the space"]
        site_visit_mentioned = any(keyword in text_lower for keyword in site_visit_keywords)

        # Check for time/date patterns with site visit
        time_keywords = ["time", "when", "schedule", "appointment", "slot"]
        time_mentioned = any(keyword in text_lower for keyword in time_keywords)

        if site_visit_mentioned and (has_change_intent(text_lower) or time_mentioned):
            # Also check if user_info has extracted a new time/date for site visit
            if user_info.get("site_visit_time") or user_info.get("visit_date"):
                return ChangeType.SITE_VISIT
            # Or if change language is present with site visit mention
            elif site_visit_mentioned and has_change_intent(text_lower):
                return ChangeType.SITE_VISIT

    # === CLIENT INFO CHANGE ===
    # Pattern: billing/contact info mentioned + change intent + new value
    has_client_info_change = has_client_info_update(user_info)

    if has_client_info_change:
        # Check for client info mention + change intent
        client_info_keywords = ["address", "billing", "invoice", "company", "vat",
                                "phone", "email", "contact", "name"]
        client_info_mentioned = any(keyword in text_lower for keyword in client_info_keywords)

        if client_info_mentioned and has_change_intent(text_lower):
            return ChangeType.CLIENT_INFO
        # Also fire if new client info extracted (strong signal)
        elif client_info_mentioned:
            return ChangeType.CLIENT_INFO

    return None


def should_skip_step3_after_date_change(
    event_state: Dict[str, Any],
    new_date: str,
) -> bool:
    """
    Determine if Step 3 can be skipped after a date change.

    Per v4 rules: Skip Step 3 if the same room remains valid and was
    explicitly locked for the new date.

    Args:
        event_state: Event entry with locked_room_id, room_eval_hash
        new_date: New confirmed date

    Returns:
        True if Step 3 can be skipped, False otherwise

    NOTE: This is a conservative check. The actual availability check
    happens in Step 3's process function. This just provides a hint.
    """
    locked_room_id = event_state.get("locked_room_id")
    room_eval_hash = event_state.get("room_eval_hash")
    requirements_hash_val = event_state.get("requirements_hash")

    # If no room is locked, can't skip
    if not locked_room_id:
        return False

    # If hashes don't match, can't skip
    if not room_eval_hash or not requirements_hash_val:
        return False

    if str(room_eval_hash) != str(requirements_hash_val):
        return False

    # Conservative: Let Step 3 decide based on actual calendar availability
    # We return False here to force the check, but Step 3 can still fast-skip
    # if the room is actually available
    return False


def compute_offer_hash(offer_payload: Dict[str, Any]) -> str:
    """
    Compute a stable hash for an offer to detect when it changes.

    Args:
        offer_payload: Offer dict with products, pricing, totals

    Returns:
        SHA256 hash of the offer
    """
    from backend.workflows.common.requirements import stable_hash

    # Extract relevant fields for offer hash
    offer_subset = {
        "products": offer_payload.get("products"),
        "total": offer_payload.get("total"),
        "subtotal": offer_payload.get("subtotal"),
        "tax": offer_payload.get("tax"),
        "pricing": offer_payload.get("pricing"),
    }

    return stable_hash(offer_subset)
