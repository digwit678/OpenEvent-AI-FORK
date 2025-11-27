"""
Universal Verbalizer for all client-facing messages.

This module provides a unified verbalization layer that transforms ALL workflow
messages into warm, human-like communication that helps clients make decisions
easily without overwhelming them with raw data.

Design Principles:
1. Human-like tone - conversational, empathetic, professional
2. Decision-friendly - highlight key comparisons and recommendations
3. Complete & correct - all facts preserved, nothing invented
4. UX-focused - no data dumps, clear next steps
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Message Context Types
# =============================================================================

@dataclass
class MessageContext:
    """Context for verbalization - captures all hard facts that must be preserved."""

    # Step and topic
    step: int
    topic: str

    # Event context
    event_date: Optional[str] = None  # DD.MM.YYYY format
    event_date_iso: Optional[str] = None
    participants_count: Optional[int] = None
    time_window: Optional[str] = None

    # Room context
    room_name: Optional[str] = None
    room_status: Optional[str] = None  # Available | Option | Unavailable
    rooms: List[Dict[str, Any]] = field(default_factory=list)

    # Pricing context
    total_amount: Optional[float] = None
    deposit_amount: Optional[float] = None
    products: List[Dict[str, Any]] = field(default_factory=list)

    # Date candidates (for date confirmation step)
    candidate_dates: List[str] = field(default_factory=list)

    # Client info
    client_name: Optional[str] = None

    # Status
    event_status: Optional[str] = None  # Lead | Option | Confirmed

    def extract_hard_facts(self) -> Dict[str, List[str]]:
        """Extract all hard facts that must appear in verbalized output."""
        facts: Dict[str, List[str]] = {
            "dates": [],
            "amounts": [],
            "room_names": [],
            "counts": [],
        }

        if self.event_date:
            facts["dates"].append(self.event_date)
        for date in self.candidate_dates:
            if date and date not in facts["dates"]:
                facts["dates"].append(date)

        if self.total_amount is not None:
            facts["amounts"].append(f"CHF {self.total_amount:.2f}")
        if self.deposit_amount is not None:
            facts["amounts"].append(f"CHF {self.deposit_amount:.2f}")
        for product in self.products:
            price = product.get("unit_price") or product.get("price")
            if price is not None:
                try:
                    facts["amounts"].append(f"CHF {float(price):.2f}")
                except (TypeError, ValueError):
                    pass

        if self.room_name:
            facts["room_names"].append(self.room_name)
        for room in self.rooms:
            name = room.get("name") or room.get("id")
            if name and name not in facts["room_names"]:
                facts["room_names"].append(name)

        if self.participants_count is not None:
            facts["counts"].append(str(self.participants_count))

        return facts


# =============================================================================
# UX-Focused Prompt Templates
# =============================================================================

UNIVERSAL_SYSTEM_PROMPT = """You are OpenEvent's client communication assistant for The Atelier, a premium event venue in Zurich.

Your role is to transform structured workflow messages into warm, human-like communication that helps clients make decisions easily.

CORE PRINCIPLES:
1. **Sound like a helpful human** - Use "I" and conversational language, not robotic bullet points
2. **Help clients decide** - Highlight the best options with clear reasons, don't just list data
3. **Be concise but complete** - Every fact must appear, but wrap it in context that helps
4. **Show empathy** - Acknowledge the client's needs and situation
5. **Guide next steps** - Make it crystal clear what happens next

STYLE GUIDELINES:
- Start with warmth (acknowledge the request/situation)
- Lead with the recommendation or key insight
- Support with 2-3 key facts, woven naturally into sentences
- End with a clear, easy-to-take action
- Use "you" and "your" to address the client directly
- Avoid: bullet lists of raw data, technical jargon, passive voice

HARD RULES (NEVER BREAK):
1. ALL dates must appear exactly as provided (DD.MM.YYYY format)
2. ALL prices must appear exactly as provided (CHF X.XX format)
3. ALL room names must appear exactly as provided
4. ALL participant counts must appear
5. NEVER invent dates, prices, or room names not in the facts
6. NEVER change any numbers

TRANSFORMATION EXAMPLES:

BAD (data dump):
"Room A - Available - Capacity 50 - Coffee: ✓ - Projector: ✓
Room B - Option - Capacity 80 - Coffee: ✓ - Projector: ✗"

GOOD (human-like):
"Great news! Room A is available for your event on 15.03.2025 and fits your 30 guests perfectly. It has everything you asked for — the coffee service and projector are both included.

If you'd like more space, Room B (capacity 80) is also open, though we'd need to arrange the projector separately. I'd recommend Room A as your best match.

Just let me know which you prefer, and I'll lock it in for you."
"""

STEP_PROMPTS = {
    2: """You're helping a client confirm their event date.

Context: The client is choosing from available dates. Help them understand the options and make a confident choice.

Focus on:
- Confirming which dates work
- Highlighting the date(s) that best match their preferences (e.g., Saturday evening if they asked)
- Making it easy to say "yes" to a date

Example transformation:
BEFORE: "Available dates: 07.02.2026, 14.02.2026, 21.02.2026"
AFTER: "Great news! I have several Saturday evenings open in February for your dinner. The 14th is Valentine's Day weekend if you'd like something special, or the 7th and 21st are also available. Which works best for your family?" """,

    3: """You're presenting room options to a client.

Context: The client needs to choose a room for their event. Help them understand which room is the best fit BY REASONING ABOUT THEIR SPECIFIC NEEDS.

CRITICAL - You must:
1. START with a clear recommendation ("I'd recommend Room A because...")
2. EXPLAIN WHY it matches their requirements (capacity, features they asked for)
3. COMPARE alternatives and note trade-offs ("Room E is larger if you want more space, but...")
4. MENTION what's included vs. what might need arranging
5. Make the decision EASY with a clear next step

DO NOT just list rooms in a table. REASON about the options.

Example transformation:
BEFORE: "- Room A — Matches: Background Music · Capacity ✓ (max 40)
- Room E — Matches: Background Music · Capacity ✓ (max 120)"

AFTER: "For your dinner of 30 guests on 14.02.2026, I'd recommend **Room A** — it's perfectly sized (max 40) and includes the background music setup you mentioned. It's intimate enough for a family celebration without feeling too large.

If you'd prefer a grander setting, Room E (max 120) also has music capabilities and could work beautifully for a more spacious feel — though it might feel a bit open for 30 guests.

Room F has great acoustics too, though we'd need to set up the music system separately.

I'd go with Room A for the best fit. Shall I hold it for you?" """,

    4: """You're presenting an offer/quote to a client.

Context: This is a key decision moment. The client is reviewing pricing before confirming.

Focus on:
- Confirming what's included in clear terms
- Making the total feel justified by connecting to their requirements
- Highlighting value and any special considerations
- Making it easy to say "yes" or ask questions

Example transformation:
BEFORE: "Room A - CHF 500, Menu - CHF 92 x 30 = CHF 2,760, Total: CHF 3,260"
AFTER: "Here's what I've put together for your family dinner on 14.02.2026:

Room A gives you the intimate setting perfect for 30 guests, with the background music included. For your three-course dinner with wine, the Seasonal Garden Trio at CHF 92 per guest offers a beautiful vegetarian option with Swiss wines.

**Total: CHF 3,260** (Room + dinner for 30 guests)

This includes everything you asked for. Ready to confirm, or would you like to explore other menu options?" """,

    5: """You're in negotiation/acceptance with a client.

Context: The client may be accepting, declining, or discussing terms.

Focus on:
- Acknowledging their decision warmly
- Confirming next steps clearly
- If there are open questions, addressing them directly
- Keeping momentum toward confirmation""",

    7: """You're in the final confirmation stage.

Context: The booking is being finalized. This might involve deposits, site visits, or final confirmations.

Focus on:
- Celebrating their choice (they're committing!)
- Being crystal clear about any remaining steps
- Making administrative details feel easy, not bureaucratic
- Ending with excitement about their upcoming event""",
}

TOPIC_HINTS = {
    "date_candidates": "Present available dates as options, recommend the best match",
    "date_confirmed": "Celebrate the date being locked in, transition smoothly to room selection",
    "room_avail_result": "Present rooms with a clear recommendation, explain the match to their needs",
    "room_selected_follow_up": "Confirm room choice, smoothly transition to products/offer",
    "offer_draft": "Present the offer as a complete package, make value clear",
    "offer_products_prompt": "Ask about catering/add-ons in a helpful, not pushy way",
    "negotiation_accept": "Celebrate acceptance, confirm immediate next steps",
    "negotiation_clarification": "Ask for clarity in a specific, helpful way",
    "confirmation_deposit_pending": "Make deposit request feel routine and easy",
    "confirmation_final": "Celebrate the confirmed booking with genuine warmth",
    "confirmation_site_visit": "Offer site visit as a helpful option, not obligation",
}


# =============================================================================
# Verbalizer Core
# =============================================================================

def verbalize_message(
    fallback_text: str,
    context: MessageContext,
    *,
    locale: str = "en",
) -> str:
    """
    Verbalize any client-facing message using the universal verbalizer.

    This is the main entry point for all message verbalization. It:
    1. Checks if empathetic mode is enabled
    2. Builds an appropriate LLM prompt based on context
    3. Calls the LLM
    4. Verifies all hard facts are preserved
    5. Returns LLM output or falls back to deterministic text

    Args:
        fallback_text: Deterministic template to use if verification fails
        context: MessageContext with all facts and metadata
        locale: Language locale (en or de)

    Returns:
        Verbalized text (LLM if valid, fallback otherwise)
    """
    if not fallback_text or not fallback_text.strip():
        return fallback_text

    tone = _resolve_tone()
    if tone == "plain":
        logger.debug(f"universal_verbalizer: plain tone, step={context.step}, topic={context.topic}")
        return fallback_text

    # Check if LLM is available
    from backend.utils.openai_key import load_openai_api_key
    api_key = load_openai_api_key(required=False)
    if not api_key:
        logger.debug("universal_verbalizer: no API key, using fallback")
        return fallback_text

    try:
        prompt_payload = _build_prompt(context, fallback_text, locale)
        llm_text = _call_llm(prompt_payload)
    except Exception as exc:
        logger.warning(
            f"universal_verbalizer: LLM call failed for step={context.step}, topic={context.topic}",
            extra={"error": str(exc)},
        )
        return fallback_text

    if not llm_text or not llm_text.strip():
        logger.warning("universal_verbalizer: empty LLM response, using fallback")
        return fallback_text

    # Verify hard facts preserved
    hard_facts = context.extract_hard_facts()
    verification = _verify_facts(llm_text, hard_facts)

    if not verification[0]:
        logger.warning(
            f"universal_verbalizer: verification failed for step={context.step}, topic={context.topic}",
            extra={"missing": verification[1], "invented": verification[2]},
        )
        return fallback_text

    logger.debug(f"universal_verbalizer: success for step={context.step}, topic={context.topic}")
    return llm_text


def _resolve_tone() -> str:
    """Determine verbalization tone from environment.

    Default is 'empathetic' for human-like UX.
    Set VERBALIZER_TONE=plain to disable LLM verbalization.
    """
    tone_env = os.getenv("VERBALIZER_TONE")
    if tone_env:
        candidate = tone_env.strip().lower()
        if candidate in {"empathetic", "plain"}:
            return candidate
    # Check for explicit disable flag
    plain_flag = os.getenv("PLAIN_VERBALIZER", "")
    if plain_flag.strip().lower() in {"1", "true", "yes", "on"}:
        return "plain"
    # Default to empathetic for human-like UX
    return "empathetic"


def _build_prompt(
    context: MessageContext,
    fallback_text: str,
    locale: str,
) -> Dict[str, Any]:
    """Build the LLM prompt for verbalization."""

    # Build step-specific guidance
    step_guidance = STEP_PROMPTS.get(context.step, "")
    topic_hint = TOPIC_HINTS.get(context.topic, "")

    # Build facts summary
    facts_summary = _format_facts_for_prompt(context)

    # Locale instruction
    locale_instruction = "Write in German (Deutsch)." if locale == "de" else "Write in English."

    system_content = f"""{UNIVERSAL_SYSTEM_PROMPT}

{locale_instruction}

STEP {context.step} CONTEXT:
{step_guidance}

TOPIC: {context.topic}
{f"Hint: {topic_hint}" if topic_hint else ""}
"""

    user_content = f"""Transform this message into warm, human-like communication:

ORIGINAL MESSAGE:
{fallback_text}

FACTS TO PRESERVE:
{facts_summary}

Return ONLY the transformed message text. Do not include explanations or metadata."""

    return {
        "system": system_content,
        "user": user_content,
    }


def _format_facts_for_prompt(context: MessageContext) -> str:
    """Format context facts for the LLM prompt."""
    lines = []

    if context.event_date:
        lines.append(f"- Event date: {context.event_date}")
    if context.participants_count:
        lines.append(f"- Participants: {context.participants_count}")
    if context.room_name:
        status = f" ({context.room_status})" if context.room_status else ""
        lines.append(f"- Room: {context.room_name}{status}")
    if context.total_amount is not None:
        lines.append(f"- Total: CHF {context.total_amount:.2f}")
    if context.deposit_amount is not None:
        lines.append(f"- Deposit: CHF {context.deposit_amount:.2f}")
    if context.candidate_dates:
        lines.append(f"- Available dates: {', '.join(context.candidate_dates)}")
    if context.rooms:
        room_summary = []
        for room in context.rooms[:5]:  # Limit to top 5
            name = room.get("name", "Room")
            status = room.get("status", "")
            capacity = room.get("capacity", "")
            room_summary.append(f"{name} ({status}, cap {capacity})")
        lines.append(f"- Rooms: {'; '.join(room_summary)}")
    if context.products:
        product_summary = []
        for p in context.products[:5]:  # Limit to top 5
            name = p.get("name", "Item")
            price = p.get("unit_price") or p.get("price")
            if price:
                product_summary.append(f"{name} (CHF {float(price):.2f})")
            else:
                product_summary.append(name)
        lines.append(f"- Products: {', '.join(product_summary)}")
    if context.client_name:
        lines.append(f"- Client: {context.client_name}")

    return "\n".join(lines) if lines else "No specific facts extracted."


def _call_llm(payload: Dict[str, Any]) -> str:
    """Call the LLM for verbalization."""
    deterministic = os.getenv("OPENAI_TEST_MODE") == "1"
    temperature = 0.0 if deterministic else 0.3  # Slightly higher for more natural variation

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(f"OpenAI SDK unavailable: {exc}") from exc

    from backend.utils.openai_key import load_openai_api_key
    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=os.getenv("OPENAI_VERBALIZER_MODEL", "gpt-4o-mini"),
        input=[
            {"role": "system", "content": payload["system"]},
            {"role": "user", "content": payload["user"]},
        ],
        temperature=temperature,
    )
    return getattr(response, "output_text", "").strip()


def _verify_facts(
    llm_text: str,
    hard_facts: Dict[str, List[str]],
) -> Tuple[bool, List[str], List[str]]:
    """
    Verify that all hard facts appear in the LLM output.

    Returns:
        Tuple of (ok, missing_facts, invented_facts)
    """
    missing: List[str] = []
    invented: List[str] = []

    text_lower = llm_text.lower()
    text_normalized = llm_text.replace(" ", "").upper()

    # Check dates
    for date in hard_facts.get("dates", []):
        if date not in llm_text:
            missing.append(f"date:{date}")

    # Check room names (case-insensitive)
    for room in hard_facts.get("room_names", []):
        room_lower = room.lower()
        room_no_dot = room.replace(".", "").lower()
        if room_lower not in text_lower and room_no_dot not in text_lower:
            missing.append(f"room:{room}")

    # Check amounts
    for amount in hard_facts.get("amounts", []):
        amount_normalized = amount.replace(" ", "").upper()
        amount_no_decimal = re.sub(r"\.00$", "", amount_normalized)
        if amount_normalized not in text_normalized and amount_no_decimal not in text_normalized:
            missing.append(f"amount:{amount}")

    # Check counts (participant count)
    for count in hard_facts.get("counts", []):
        if count not in llm_text:
            missing.append(f"count:{count}")

    # Check for invented dates
    date_pattern = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")
    for match in date_pattern.finditer(llm_text):
        found_date = match.group(1)
        if found_date not in hard_facts.get("dates", []):
            invented.append(f"date:{found_date}")

    # Check for invented amounts
    amount_pattern = re.compile(r"\bCHF\s*(\d+(?:[.,]\d{1,2})?)\b", re.IGNORECASE)
    canonical_amounts = set()
    for amt in hard_facts.get("amounts", []):
        # Normalize for comparison
        normalized = amt.replace(" ", "").upper().replace(",", ".")
        match = re.search(r"CHF(\d+(?:\.\d{1,2})?)", normalized)
        if match:
            canonical_amounts.add(match.group(1))
            # Also add without .00
            canonical_amounts.add(re.sub(r"\.00$", "", match.group(1)))

    for match in amount_pattern.finditer(llm_text):
        found_amount = match.group(1).replace(",", ".")
        found_no_decimal = re.sub(r"\.00$", "", found_amount)
        if found_amount not in canonical_amounts and found_no_decimal not in canonical_amounts:
            invented.append(f"amount:CHF {found_amount}")

    ok = len(missing) == 0 and len(invented) == 0
    return (ok, missing, invented)


# =============================================================================
# Convenience Functions for Workflow Integration
# =============================================================================

def verbalize_step_message(
    fallback_text: str,
    step: int,
    topic: str,
    *,
    event_date: Optional[str] = None,
    participants_count: Optional[int] = None,
    room_name: Optional[str] = None,
    room_status: Optional[str] = None,
    rooms: Optional[List[Dict[str, Any]]] = None,
    total_amount: Optional[float] = None,
    deposit_amount: Optional[float] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    candidate_dates: Optional[List[str]] = None,
    client_name: Optional[str] = None,
    event_status: Optional[str] = None,
    locale: str = "en",
) -> str:
    """
    Convenience function to verbalize a workflow message.

    This is the primary integration point for workflow steps.
    """
    context = MessageContext(
        step=step,
        topic=topic,
        event_date=event_date,
        participants_count=participants_count,
        room_name=room_name,
        room_status=room_status,
        rooms=rooms or [],
        total_amount=total_amount,
        deposit_amount=deposit_amount,
        products=products or [],
        candidate_dates=candidate_dates or [],
        client_name=client_name,
        event_status=event_status,
    )
    return verbalize_message(fallback_text, context, locale=locale)


__all__ = [
    "MessageContext",
    "verbalize_message",
    "verbalize_step_message",
]
