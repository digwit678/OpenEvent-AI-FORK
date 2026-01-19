"""
Central Billing Address Capture-Anytime Utility

This module provides a single point of truth for billing capture that works at ANY step.
It's called from pre_route.py BEFORE step handlers run, ensuring billing is always captured.

Architecture:
- Pre-filter first (no LLM cost) for billing signal detection
- LLM structured data used when available (already extracted in unified detection)
- Hybrid message support: billing extracted from statement section only

Cost model:
- Pre-filter regex: $0 (always runs)
- LLM extraction: $0 extra (piggybacks on unified detection)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflows.common.types import WorkflowState
from workflows.common.billing import (
    update_billing_details,
    missing_billing_fields,
    billing_prompt_for_missing_fields,
    has_complete_billing as _has_complete_billing,
)
from workflows.common.capture import split_statement_vs_question
from detection.unified import UnifiedDetectionResult

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class BillingCaptureResult:
    """Result of billing capture attempt."""

    captured: bool = False  # Whether billing was captured this turn
    complete: bool = False  # Whether all required fields are present
    missing_fields: List[str] = field(default_factory=list)  # e.g., ["postal_code", "city"]
    source: str = ""  # "unified_llm" | "pre_filter_parse" | "already_captured"


# =============================================================================
# BILLING SIGNAL DETECTION
# =============================================================================

# Patterns that indicate billing address content (not questions about billing)
# These are stricter than pre_filter patterns - require actual address content
_BILLING_CONTENT_PATTERNS = [
    # English phrases with content indicator (: or is)
    r'\bbilling\s*(?:address\s*)?(?:is|:)',  # "billing address is", "billing:", "billing is"
    r'\binvoice\s*(?:address\s*)?(?:is|to\s*:?)',  # "invoice address is", "invoice to:"
    r'\bsend\s*(?:invoice|bill)\s*to\s*:?',  # "send invoice to"
    # German phrases with content indicator
    r'\brechnungs?\s*adresse\s*:?',         # "Rechnungsadresse:" or "Rechnungsadresse"
    r'\brechnung\s*an\s*:?',                # "Rechnung an:"
    # French phrases with content indicator
    r'\badresse\s*de\s*facturation\s*:?',   # "adresse de facturation:"
    r'\bfacturer\s*[àa]\s*:?',              # "facturer à:"
    # Structural patterns (actual address content)
    r'\b\d{4,5}\s+[A-Za-zÀ-ÿ]+',            # EU postal code + city (4-5 digits)
    r'\bCH[-\s]?\d{4}\b',                   # Swiss postal code (CH-8000)
    r'\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b',  # UK postal code (SW1A 1AA)
    r'\b\d{5}(?:-\d{4})?\b',                # US ZIP code (10001 or 10001-1234)
    r'\b[A-Za-zÀ-ÿ]+(?:strasse|straße|str\.?)\s*\d+',  # German street
    r'\b\d+\s+[A-Za-zÀ-ÿ]+\s*(?:street|st|road|rd|avenue|ave|lane|ln|blvd)\b',  # US street
]


def has_billing_content(text: str) -> bool:
    """
    Check if text contains actual billing address content (not just questions about billing).

    This differs from pre_filter.has_billing_signal in that it's more strict:
    - "What's the billing address?" → False (question)
    - "Billing: Acme Corp, Street 1, 8000 Zürich" → True (content)
    """
    if not text:
        return False

    for pattern in _BILLING_CONTENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# Patterns that signal the START of billing content (extract text AFTER these)
_BILLING_START_PATTERNS = [
    # English phrases - order matters: most specific first
    r'\bour\s+billing\s*(?:address\s*)?(?:is\s*:?|:)\s*', # "our billing address is:" with optional colon
    r'\bbilling\s*address\s*(?:is\s*:?|:)\s*',            # "billing address is:" with optional colon
    r'\bbilling\s*(?:is\s*:?|:)\s*',                      # "billing:" or "billing is:"
    r'\binvoice\s*(?:address\s*)?(?:is|to)\s*:?\s*',      # "invoice address is ", "invoice to:"
    r'\bsend\s*(?:invoice|bill)\s*to\s*:?\s*',            # "send invoice to "
    # German phrases
    r'\brechnungs?\s*adresse\s*:?\s*',                    # "Rechnungsadresse:"
    r'\brechnung\s*an\s*:?\s*',                           # "Rechnung an:"
    # French phrases
    r'\badresse\s*de\s*facturation\s*:?\s*',              # "adresse de facturation:"
    r'\bfacturer\s*[àa]\s*:?\s*',                         # "facturer à:"
]


def _extract_billing_text(message_text: str) -> str:
    """
    Extract billing-relevant text from potentially hybrid message.

    For hybrid messages like "We confirm the date. Our billing address is Acme Corp, Zurich",
    extracts ONLY the billing payload (e.g., "Acme Corp, Zurich"), not the entire message.

    Strategy:
    1. Find billing start pattern (e.g., "billing address is")
    2. Extract everything AFTER that pattern until end or next sentence boundary
    """
    if not message_text:
        return ""

    # Try to find billing start pattern and extract content AFTER it
    for pattern in _BILLING_START_PATTERNS:
        match = re.search(pattern, message_text, re.IGNORECASE)
        if match:
            # Extract everything after the pattern
            billing_payload = message_text[match.end():].strip()
            if billing_payload:
                # Clean up: remove trailing punctuation if it's sentence-ending
                # But keep commas and periods that are part of address
                # Stop at sentence boundaries that look like new topics
                # e.g., "Acme Corp, Zurich. What about parking?" → "Acme Corp, Zurich"
                sentence_end = re.search(r'\.\s+(?=[A-Z]|What|How|Can|Could|Do|Is|Are|Will)', billing_payload)
                if sentence_end:
                    billing_payload = billing_payload[:sentence_end.start()].strip()
                # Remove trailing period if present
                billing_payload = billing_payload.rstrip('.')
                return billing_payload

    # Fallback: if no explicit billing pattern but has billing content signals
    # (e.g., just an address), return the full text for the parser to handle
    statements, _ = split_statement_vs_question(message_text)
    if has_billing_content(statements):
        return statements
    if has_billing_content(message_text):
        return message_text

    return ""


# =============================================================================
# MAIN CAPTURE FUNCTION
# =============================================================================

def capture_billing_anytime(
    state: WorkflowState,
    unified_result: Optional[UnifiedDetectionResult],
    pre_filter_signals: Dict[str, bool],
    message_text: str,
) -> BillingCaptureResult:
    """
    Capture billing address from message if detected.

    This is the CENTRAL billing capture function called from pre_route.py.
    It ensures billing is captured at ANY workflow step.

    Priority:
    1. unified_result.billing_address (structured, from LLM) - highest quality
    2. Pre-filter signal + parse from statement section of message - fallback

    Args:
        state: Current workflow state with event_entry
        unified_result: Result from unified LLM detection (may have billing_address)
        pre_filter_signals: Dict of pre-filter signal flags (e.g., {"billing": True})
        message_text: Full message text (for fallback parsing)

    Returns:
        BillingCaptureResult with captured, complete, and missing_fields
    """
    result = BillingCaptureResult()

    if not state.event_entry:
        return result

    event_entry = state.event_entry

    # Check if billing already captured this turn (avoid duplicate work)
    if state.turn_notes.get("_billing_captured_this_turn"):
        result.source = "already_captured"
        result.missing_fields = missing_billing_fields(event_entry)
        result.complete = len(result.missing_fields) == 0
        return result

    # Track whether we captured anything new
    captured_new = False
    billing_raw = None

    # Priority 1: Use structured LLM-extracted billing address
    if unified_result and unified_result.billing_address:
        billing_data = unified_result.billing_address
        logger.debug("[BILLING_CAPTURE] Using LLM-extracted billing: %s", billing_data)

        # Store structured data into event_data for update_billing_details() to process
        event_data = event_entry.setdefault("event_data", {})

        # Build raw address string for storage
        parts = []
        if billing_data.get("name_or_company"):
            parts.append(billing_data["name_or_company"])
            if not event_data.get("Company"):
                event_data["Company"] = billing_data["name_or_company"]
        if billing_data.get("street"):
            parts.append(billing_data["street"])
        if billing_data.get("postal_code"):
            parts.append(billing_data["postal_code"])
        if billing_data.get("city"):
            parts.append(billing_data["city"])
        if billing_data.get("country"):
            parts.append(billing_data["country"])

        if parts:
            billing_raw = ", ".join(parts)
            event_data["Billing Address"] = billing_raw
            captured_new = True
            result.source = "unified_llm"

    # Priority 2: Pre-filter signal + parse from statement section
    elif pre_filter_signals.get("billing"):
        billing_text = _extract_billing_text(message_text)
        if billing_text:
            logger.debug("[BILLING_CAPTURE] Using pre-filter parsed billing from: %s", billing_text[:100])
            event_data = event_entry.setdefault("event_data", {})
            # Only update if we don't already have a billing address
            if not event_data.get("Billing Address"):
                event_data["Billing Address"] = billing_text
                billing_raw = billing_text
                captured_new = True
                result.source = "pre_filter_parse"

    # If we captured something new, run the structured parser
    if captured_new:
        update_billing_details(event_entry)
        state.extras["persist"] = True
        state.turn_notes["_billing_captured_this_turn"] = True
        result.captured = True

        logger.info(
            "[BILLING_CAPTURE] Captured billing at step %s: %s",
            event_entry.get("current_step"),
            billing_raw[:50] if billing_raw else "N/A"
        )

    # Always check completeness (whether newly captured or previously stored)
    result.missing_fields = missing_billing_fields(event_entry)
    result.complete = len(result.missing_fields) == 0

    return result


def get_billing_validation_prompt(
    capture_result: BillingCaptureResult,
) -> Optional[str]:
    """
    Generate prompt for missing billing fields.

    Args:
        capture_result: Result from capture_billing_anytime()

    Returns:
        - None if billing is complete or not captured
        - Validation prompt string if fields are missing
    """
    if capture_result.complete or not capture_result.captured:
        return None

    if not capture_result.missing_fields:
        return None

    prompt = billing_prompt_for_missing_fields(capture_result.missing_fields)
    if not prompt:
        return None

    return prompt


def should_prompt_for_billing(state: WorkflowState) -> bool:
    """
    Check if we should prompt user for billing details.

    Returns True if:
    - Billing was captured this turn but is incomplete
    - We haven't already prompted this turn
    """
    if not state.event_entry:
        return False

    # Check if billing was just captured and is incomplete
    if not state.turn_notes.get("_billing_captured_this_turn"):
        return False

    # Check if we already prompted
    if state.turn_notes.get("_billing_prompt_added"):
        return False

    # Check for missing fields
    missing = missing_billing_fields(state.event_entry)
    return len(missing) > 0


def add_billing_validation_draft(
    state: WorkflowState,
    capture_result: BillingCaptureResult,
) -> bool:
    """
    Add a draft message prompting for missing billing fields if needed.

    UX DECISION (Option B - Amazon Model):
    - Steps 1-3: OK to prompt for billing completion (still gathering info)
    - Steps 4-6: NO prompts - don't nag during offer/negotiation (friction before price reveal)
    - Step 7: Gate at confirmation - require complete billing for final contract

    This function handles Steps 1-3 prompting. Step 7 gating is handled separately
    in the step7_handler.

    Args:
        state: Workflow state to add draft message to
        capture_result: Result from capture_billing_anytime()

    Returns:
        True if a validation prompt was added, False otherwise
    """
    if not capture_result.captured or capture_result.complete:
        return False

    if state.turn_notes.get("_billing_prompt_added"):
        return False

    # UX RULE: Don't nag during offer/negotiation/transition (Steps 4-6)
    # This follows the "Amazon model" - show cart total first, ask for address at checkout
    current_step = state.current_step or (state.event_entry or {}).get("current_step") or 1
    if current_step in (4, 5, 6):
        logger.debug(
            "[BILLING_CAPTURE] Skipping validation prompt at Step %d (offer/negotiation phase)",
            current_step
        )
        return False

    prompt = get_billing_validation_prompt(capture_result)
    if not prompt:
        return False

    # Add as a draft message with special topic for response composer
    # The composer will append this after other content with proper spacing
    state.add_draft_message({
        "body_markdown": prompt,
        "topic": "billing_validation",
        "append_mode": True,  # Signal to append to existing response
        "requires_approval": False,  # Don't need HIL for validation prompt
    })

    state.turn_notes["_billing_prompt_added"] = True
    logger.debug("[BILLING_CAPTURE] Added validation prompt for missing fields: %s",
                capture_result.missing_fields)

    return True


# Re-export has_complete_billing for convenience (canonical implementation is in billing.py)
has_complete_billing = _has_complete_billing
