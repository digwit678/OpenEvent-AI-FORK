"""
Cancellation detection for client emails.

Detects when a client wants to cancel their event booking and routes
to manager for confirmation. Different handling based on workflow stage:
- Site visit scheduled → Manager confirms, sends regret email
- Normal flow → Manager confirms, archives event

See docs/internal/planning/OPEN_DECISIONS.md DECISION-012 for details.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from backend.detection.keywords.buckets import is_decline, detect_language


# Strong cancellation signals - explicit intent to cancel the EVENT (not just decline an offer)
CANCELLATION_SIGNALS_EN = [
    r"\bcancel\s+(the\s+)?(event|booking|reservation|meeting)\b",
    r"\bwant\s+to\s+cancel\b",
    r"\bneed\s+to\s+cancel\b",
    r"\bhave\s+to\s+cancel\b",
    r"\bmust\s+cancel\b",
    r"\bplease\s+cancel\b",
    r"\bcancel\s+(it|this|everything)\b",
    r"\bwon'?t\s+(be\s+)?(needing|proceeding|going\s+ahead)\b",
    r"\bno\s+longer\s+(need|require|want)\b.*\b(room|event|booking)\b",
]

CANCELLATION_SIGNALS_DE = [
    r"\b(veranstaltung|buchung|reservierung|termin)\s+(stornieren|absagen|canceln)\b",
    r"\bstornieren\s+(wir\s+)?(die\s+)?(veranstaltung|buchung)\b",
    r"\bmöchten?\s+(die\s+)?(veranstaltung|buchung)\s+(stornieren|absagen)\b",
    r"\bmüssen\s+(leider\s+)?(stornieren|absagen)\b",
    r"\bbittet?\s+(um\s+)?stornierung\b",
    r"\bbrauchen\s+(den\s+raum|die\s+buchung)\s+nicht\s+mehr\b",
]

CANCELLATION_SIGNALS_FR = [
    r"\bannuler\s+(la\s+)?(réservation|événement|location)\b",
    r"\bvoulons?\s+annuler\b",
    r"\bdevons?\s+annuler\b",
    r"\bmerci\s+d'?annuler\b",
    r"\bn'?(avons?|aurons?)\s+plus\s+besoin\b",
]

CANCELLATION_SIGNALS_IT = [
    r"\bannullare\s+(la\s+)?(prenotazione|evento|riunione)\b",
    r"\bvogliamo\s+annullare\b",
    r"\bdobbiamo\s+annullare\b",
    r"\bper\s+favore\s+annullare\b",
    r"\bnon\s+(abbiamo\s+)?più\s+bisogno\b",
]

CANCELLATION_SIGNALS_ES = [
    r"\bcancelar\s+(la\s+)?(reserva|evento|reunión)\b",
    r"\bqueremos\s+cancelar\b",
    r"\btenemos\s+que\s+cancelar\b",
    r"\bpor\s+favor\s+cancelar\b",
    r"\bya\s+no\s+necesitamos\b",
]


def detect_cancellation_intent(text: str) -> Tuple[bool, float, str]:
    """
    Detect if the message indicates a cancellation request.

    Returns:
        Tuple of (is_cancellation, confidence, language)
        - is_cancellation: True if message appears to be a cancellation request
        - confidence: 0.0-1.0 confidence score
        - language: detected language code (en, de, fr, it, es)
    """
    if not text or len(text.strip()) < 5:
        return False, 0.0, "en"

    text_lower = text.lower()
    language = detect_language(text)

    # Check strong cancellation signals first
    patterns = []
    if language in ("en", "mixed"):
        patterns.extend(CANCELLATION_SIGNALS_EN)
    if language in ("de", "mixed"):
        patterns.extend(CANCELLATION_SIGNALS_DE)
    if language in ("fr", "mixed"):
        patterns.extend(CANCELLATION_SIGNALS_FR)
    if language in ("it", "mixed"):
        patterns.extend(CANCELLATION_SIGNALS_IT)
    if language in ("es", "mixed"):
        patterns.extend(CANCELLATION_SIGNALS_ES)

    # Strong cancellation signal = high confidence
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True, 0.95, language

    # Weaker signal: just "decline" without event context
    # Only if short message (avoids false positives from "I decline your offer for room X")
    if len(text) < 100 and is_decline(text, language):
        # Check if it's about the whole event, not just an offer detail
        event_words = {"event", "booking", "reservation", "meeting", "veranstaltung", "buchung", "réservation", "evento"}
        if any(word in text_lower for word in event_words):
            return True, 0.7, language

    return False, 0.0, language


def format_cancellation_subject(original_subject: str, client_email: str) -> str:
    """
    Format subject line to highlight cancellation for manager.

    Example: "⚠️ CANCELLATION REQUEST from client@example.com | Re: Room booking"
    """
    # Strip common prefixes
    clean_subject = original_subject
    for prefix in ("Re:", "RE:", "Fwd:", "FWD:", "Aw:", "AW:"):
        if clean_subject.startswith(prefix):
            clean_subject = clean_subject[len(prefix):].strip()

    # Truncate if too long
    if len(clean_subject) > 40:
        clean_subject = clean_subject[:37] + "..."

    return f"⚠️ CANCELLATION REQUEST from {client_email} | {clean_subject}"


__all__ = [
    "detect_cancellation_intent",
    "format_cancellation_subject",
]
