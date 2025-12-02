from __future__ import annotations

"""
Semantic pattern matching for client responses.
Uses regex patterns + fuzzy matching instead of exact keyword lists.
"""

import re
from functools import lru_cache
from typing import List, Sequence, Tuple

from backend.services.rooms import load_room_catalog

# ============================================================================
# ACCEPTANCE / DECLINE / COUNTER PATTERNS
# ============================================================================

# Explicit agreement patterns and informal approvals
ACCEPTANCE_PATTERNS = [
    r"\b(accept|agree|approved?|confirm)\w*\b",
    r"\b(looks?|sounds?|all|good\s+to)\s+(good|great|fine|okay|ok)\b",
    r"\b(yes|ok|okay|sure|yep|ja|oui)[\s,]*(please|send|go|proceed|do\s+it)?\b",
    r"\b(that'?s?|i'?m?|all)?\s+fine\b",
    r"\b(send\s+it|go\s+ahead|proceed|let'?s?\s+(do|go|proceed))\b",
    r"\b(works?\s+for|happy\s+with|satisfied)\b",
    r"\b(d'?accord|einverstanden|va\s+bene)\b",
    r"\b(gerne|sehr\s+gut|perfekt|perfetto|perfecto|vale|claro|muy\s+bien)\b",
]

DECLINE_PATTERNS = [
    r"\b(no|nope|nah)\b",
    r"\b(not\s+interested|not\s+moving\s+forward|no\s+longer\s+interested)\b",
    r"\b(cancel(?:led|ing)?|cancellation)\b",
    r"\b(pass|skip)\b",
    r"\b(decline|rejected?|turn\s+down)\b",
    r"\b(do\s+not|don't)\s+(want|proceed|move\s+forward)\b",
]

COUNTER_PATTERNS = [
    r"\b(discount|better\s+price|reduce|lower|cheaper)\b",
    r"\b(can\s+you\s+do|could\s+you\s+do|would\s+you\s+do)\s+\d",
    r"\b(counter(?:\s*offer)?)\b",
    r"\b(budget\s+is|max\s+we\s+can\s+do|meet\s+us\s+at)\b",
    r"\b(could\s+you\s+do)\b",
]

CHANGE_PATTERNS = [
    r"\b(change|modify|update|adjust|switch|move|shift|reschedule)\b",
    r"\b(instead\s+of|rather\s+than|replace\s+with|swap\s+(out|for))\b",
    r"\b(actually|correction|i\s+meant|sorry)\b",
    r"\b(can|could|would)\s+(we|i|you)\s+(please\s+)?(change|modify|update|adjust)\b",
]

QUESTION_PREFIXES = (
    "do you",
    "can you",
    "could you",
    "would you",
    "what",
    "which",
    "when",
    "where",
    "how",
)

ROOM_PATTERNS = [
    r"\broom\s+[a-z]\b",  # "room a", "room b"
    r"\bpunkt\.?\s*null\b",
    r"\b(sky\s*loft|garden|terrace)\b",
]

ROOM_SELECTION_SIGNALS = [
    "looks good",
    "sounds good",
    "prefer",
    "choose",
    "go with",
    "take",
    "like",
    "works",
]

HYPOTHETICAL_MARKERS = [
    r"\bwhat\s+if\b",
    r"\bhypothetically\b",
    r"\bin\s+theory\b",
    r"\bwould\s+it\s+be\s+possible\b",
    r"\bcould\s+we\s+potentially\b",
    r"\bjust\s+(curious|wondering|asking)\b",
    r"\bthinking\s+about\b",
    r"\bconsidering\b",
]


def _score_match(text: str, match: re.Match[str], *, multiplier: float = 0.02) -> float:
    """
    Score a regex match based on length, position, and exactness.
    """
    match_length = len(match.group(0))
    start = match.start()
    exact = match.group(0).strip() == text.strip()

    score = 0.65 + (match_length * multiplier)
    if start < 10:
        score += 0.1
    if exact:
        score += 0.1
    return min(0.95, score)


def _match_patterns(text: str, patterns: Sequence[str]) -> Tuple[bool, float, str]:
    text_lower = (text or "").lower().strip()
    best: Tuple[bool, float, str] = (False, 0.0, "")
    for pattern in patterns:
        for match in re.finditer(pattern, text_lower):
            score = _score_match(text_lower, match)
            if score > best[1]:
                best = (True, score, match.group(0))
    return best


def _is_question(text: str) -> bool:
    text_lower = (text or "").strip().lower()
    if "?" in text_lower:
        return True
    return any(text_lower.startswith(prefix) for prefix in QUESTION_PREFIXES)


def matches_acceptance_pattern(text: str) -> Tuple[bool, float, str]:
    """
    Check if text matches acceptance patterns.

    Returns:
        (is_match, confidence, matched_pattern)
    """
    if _is_question(text) or is_room_selection(text):
        return False, 0.0, ""
    return _match_patterns(text, ACCEPTANCE_PATTERNS)


def matches_decline_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches decline/rejection patterns."""
    return _match_patterns(text, DECLINE_PATTERNS)


def matches_counter_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches counter/negotiation patterns."""
    return _match_patterns(text, COUNTER_PATTERNS)


def matches_change_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches change intent patterns, avoiding hypotheticals."""
    if looks_hypothetical(text):
        return False, 0.0, ""
    return _match_patterns(text, CHANGE_PATTERNS)


def looks_hypothetical(text: str) -> bool:
    """Check if message is a hypothetical question vs actual request."""
    text_lower = (text or "").lower()
    if not text_lower:
        return False
    has_marker = any(re.search(marker, text_lower) for marker in HYPOTHETICAL_MARKERS)
    return has_marker and ("?" in text_lower or _is_question(text_lower))


def is_room_selection(text: str) -> bool:
    """Detect if a message is selecting a room rather than accepting an offer."""
    text_lower = (text or "").lower()
    room_patterns = ROOM_PATTERNS + _room_patterns_from_catalog()
    mentions_room = any(re.search(pattern, text_lower) for pattern in room_patterns)
    if not mentions_room:
        return False
    return any(signal in text_lower for signal in ROOM_SELECTION_SIGNALS)


@lru_cache(maxsize=1)
def _room_patterns_from_catalog() -> List[str]:
    """
    Build room regex patterns from the room catalog to avoid stale hardcoding.
    """
    patterns: List[str] = []
    try:
        for record in load_room_catalog():
            name = record.name.strip().lower()
            room_id = record.room_id.strip().lower()
            if name:
                patterns.append(rf"\b{re.escape(name)}\b")
            if room_id and room_id != name:
                patterns.append(rf"\b{re.escape(room_id)}\b")
    except Exception:
        # Defensive: fall back to empty if catalog unavailable
        return []
    return patterns


__all__ = [
    "matches_acceptance_pattern",
    "matches_decline_pattern",
    "matches_counter_pattern",
    "matches_change_pattern",
    "looks_hypothetical",
    "is_room_selection",
    "ACCEPTANCE_PATTERNS",
    "DECLINE_PATTERNS",
    "COUNTER_PATTERNS",
    "CHANGE_PATTERNS",
]
