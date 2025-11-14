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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ChangeType(Enum):
    """Types of changes that can trigger re-evaluation."""

    DATE = "date"                    # chosen_date changed
    ROOM = "room"                    # locked_room_id requested change
    REQUIREMENTS = "requirements"    # participants/layout/duration/special changed
    PRODUCTS = "products"            # selected_products/catering changed
    COMMERCIAL = "commercial"        # pure price/terms negotiation
    DEPOSIT = "deposit"              # reservation/deposit/option operations


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

    Detection Rules:
        1. If user_info has "date" or "event_date" AND date_confirmed=True → DATE
        2. If user_info has "room" AND it differs from locked_room_id → ROOM
        3. If user_info has participants/layout/duration/special AND differs → REQUIREMENTS
        4. If user_info has products/catering only → PRODUCTS
        5. If negotiation/price keywords without structural changes → COMMERCIAL
        6. If deposit/reservation keywords → DEPOSIT
    """
    date_confirmed = bool(event_state.get("date_confirmed"))
    chosen_date = event_state.get("chosen_date")
    locked_room_id = event_state.get("locked_room_id")
    current_step = event_state.get("current_step") or 1

    # Check for date change
    user_date = user_info.get("date") or user_info.get("event_date")
    if user_date:
        # If date is already confirmed and user provides a new date, it's a DATE change
        if date_confirmed and chosen_date and user_date != chosen_date:
            return ChangeType.DATE
        # If no date confirmed yet, this is normal flow, not a "change"
        if not date_confirmed:
            return None

    # Check for room change
    user_room = user_info.get("room") or user_info.get("preferred_room")
    if user_room and locked_room_id:
        if str(user_room).strip().lower() != str(locked_room_id).strip().lower():
            return ChangeType.ROOM

    # Check for requirements change
    # Any change in participants, layout, duration, or special_requirements
    req_fields = ["participants", "number_of_participants", "layout", "type",
                  "start_time", "end_time", "notes", "special_requirements"]
    has_req_change = any(user_info.get(field) is not None for field in req_fields)

    if has_req_change and locked_room_id:
        # Requirements change after room is locked
        return ChangeType.REQUIREMENTS

    # Check for products/catering change
    product_fields = ["products", "catering", "menu", "wine", "beverage"]
    has_product_change = any(user_info.get(field) is not None for field in product_fields)

    if has_product_change and current_step >= 4:
        # Products change in offer phase
        return ChangeType.PRODUCTS

    # Check for commercial negotiation keywords
    if message_text and current_step >= 5:
        commercial_keywords = ["price", "discount", "cheaper", "negotiate", "budget",
                               "cost", "expensive", "payment terms"]
        text_lower = message_text.lower()
        if any(keyword in text_lower for keyword in commercial_keywords):
            # Commercial negotiation without structural changes
            return ChangeType.COMMERCIAL

    # Check for deposit/reservation keywords
    if message_text and current_step >= 7:
        deposit_keywords = ["deposit", "reservation", "reserve", "option", "hold",
                           "payment", "invoice", "site visit"]
        text_lower = message_text.lower()
        if any(keyword in text_lower for keyword in deposit_keywords):
            return ChangeType.DEPOSIT

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
