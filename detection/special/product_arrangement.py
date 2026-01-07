"""
Detect client intent to arrange missing products.

When Step 3 presents rooms with missing products and asks "Would you like me
to check if I can arrange it separately?", we need to detect when the client:
1. Agrees to have the missing product(s) sourced/arranged
2. Confirms their room selection (explicitly or implicitly)

This detection is word-agnostic (LLM-based) to handle natural language variations:
- "Yes, please arrange the flipchart"
- "That would be great, can you source it?"
- "Go ahead with Room D, and check about the flipchart"
- "Room D works, yes please try to get a projector"

See docs/plans/OPEN_DECISIONS.md DECISION-010 for background.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from adapters.agent_adapter import AgentAdapter, get_agent_adapter

logger = logging.getLogger(__name__)


@dataclass
class ArrangementDetectionResult:
    """Result of product arrangement intent detection."""

    wants_arrangement: bool
    """Client wants us to arrange/source missing product(s)."""

    confirms_room: bool
    """Client explicitly or implicitly confirms their room selection."""

    products_to_source: List[str]
    """Specific products the client wants arranged (may be empty if "all")."""

    confidence: float
    """Confidence score (0.0-1.0)."""

    chosen_room: Optional[str] = None
    """Room name if client explicitly mentioned one (e.g., 'Room A')."""

    raw_response: Optional[Dict[str, Any]] = None
    """Raw LLM response for debugging."""


# Prompt for LLM-based detection
_ARRANGEMENT_DETECTION_PROMPT = """You are analyzing a client's response in a room booking conversation.

Context:
- We recommended a room for their event
- The room is missing these products/features that the client requested: {missing_products}
- We asked: "Would you like me to check if I can arrange it separately?"

Analyze the client's message and determine:
1. Does the client want us to arrange/source/find the missing product(s)?
2. Is the client confirming/accepting a room (explicitly or implicitly)?
3. Which specific products are they asking about? (or "all" if they mean all missing ones)
4. Did the client explicitly mention a room name (e.g., "Room A", "Room B")?

CLIENT MESSAGE:
{message}

Respond with JSON only:
{{
  "wants_arrangement": true/false,
  "confirms_room": true/false,
  "chosen_room": "Room X" or null,
  "products_to_source": ["product1", "product2"] or [],
  "reasoning": "brief explanation"
}}

Rules:
- wants_arrangement=true if client says yes/please/go ahead/try to get it/etc.
- confirms_room=true if client mentions a room positively OR says "go ahead" (implicit confirmation)
- chosen_room should be the exact room name if client explicitly mentioned one (e.g., "Room A", "Room D"), null otherwise
- products_to_source should list specific products mentioned, or be empty if they mean "all missing ones"
- If unsure, set wants_arrangement=false (we'll fall back to normal flow)"""


def detect_product_arrangement_intent(
    message_text: str,
    missing_products: List[str],
    adapter: Optional[AgentAdapter] = None,
) -> ArrangementDetectionResult:
    """
    Detect if the client wants to arrange missing products.

    Args:
        message_text: The client's message
        missing_products: List of products that are missing from the recommended room
        adapter: Optional agent adapter (uses default if not provided)

    Returns:
        ArrangementDetectionResult with detection outcome
    """
    if not message_text or not missing_products:
        return ArrangementDetectionResult(
            wants_arrangement=False,
            confirms_room=False,
            products_to_source=[],
            confidence=0.0,
        )

    if adapter is None:
        adapter = get_agent_adapter()

    # Format the prompt with context
    prompt = _ARRANGEMENT_DETECTION_PROMPT.format(
        missing_products=", ".join(missing_products),
        message=message_text.strip(),
    )

    try:
        response = adapter.complete(
            prompt,
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=300,
            json_mode=True,
        )

        # Parse the JSON response
        result = json.loads(response)

        # Handle case where LLM returns a list instead of dict
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            result = {}

        wants_arrangement = bool(result.get("wants_arrangement", False))
        confirms_room = bool(result.get("confirms_room", False))
        products_to_source = result.get("products_to_source", [])
        chosen_room = result.get("chosen_room")  # May be null

        # Ensure products_to_source is a list
        if not isinstance(products_to_source, list):
            products_to_source = []

        # Normalize chosen_room to string or None
        if chosen_room and isinstance(chosen_room, str):
            chosen_room = chosen_room.strip()
        else:
            chosen_room = None

        # If they want arrangement but didn't specify products, use all missing
        if wants_arrangement and not products_to_source:
            products_to_source = list(missing_products)

        # Calculate confidence based on response clarity
        confidence = 0.9 if wants_arrangement else 0.7

        logger.debug(
            "Product arrangement detection: wants=%s, room=%s, chosen_room=%s, products=%s (reason: %s)",
            wants_arrangement,
            confirms_room,
            chosen_room,
            products_to_source,
            result.get("reasoning", "?"),
        )

        return ArrangementDetectionResult(
            wants_arrangement=wants_arrangement,
            confirms_room=confirms_room,
            products_to_source=products_to_source,
            confidence=confidence,
            chosen_room=chosen_room,
            raw_response=result,
        )

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse arrangement detection response: %s", e)
        return ArrangementDetectionResult(
            wants_arrangement=False,
            confirms_room=False,
            products_to_source=[],
            confidence=0.0,
        )
    except Exception as e:
        logger.warning("Arrangement detection failed: %s", e)
        return ArrangementDetectionResult(
            wants_arrangement=False,
            confirms_room=False,
            products_to_source=[],
            confidence=0.0,
        )


def detect_continue_without_product(
    message_text: str,
    declined_products: List[str],
    adapter: Optional[AgentAdapter] = None,
) -> bool:
    """
    Detect if client wants to continue without the product that couldn't be sourced.

    Used after manager reports product is unavailable and we ask:
    "Unfortunately, we couldn't arrange [product]. Would you like to continue without it?"

    Args:
        message_text: The client's response
        declined_products: Products we couldn't source
        adapter: Optional agent adapter

    Returns:
        True if client wants to continue without the product
    """
    if not message_text:
        return False

    if adapter is None:
        adapter = get_agent_adapter()

    prompt = f"""A client was told we couldn't arrange these products for their event: {', '.join(declined_products)}
We asked if they'd like to continue without them.

Analyze their response and determine if they want to CONTINUE with the booking (without the product).

CLIENT MESSAGE:
{message_text}

Respond with JSON only:
{{"continue_without_product": true/false, "reasoning": "brief explanation"}}

Rules:
- continue_without_product=true if client agrees to proceed, says "yes", "that's fine", "let's continue", etc.
- continue_without_product=false if client wants to cancel, reconsider, or is unclear"""

    try:
        response = adapter.complete(prompt, temperature=0.1, max_tokens=200, json_mode=True)
        result = json.loads(response)
        return bool(result.get("continue_without_product", False))
    except Exception as e:
        logger.warning("Continue detection failed: %s", e)
        return False


__all__ = [
    "ArrangementDetectionResult",
    "detect_product_arrangement_intent",
    "detect_continue_without_product",
]
