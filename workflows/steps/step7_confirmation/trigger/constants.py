"""Keyword constants for Step 7 message classification.

Extracted from step7_handler.py as part of F1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Tuple

CONFIRM_KEYWORDS: Tuple[str, ...] = ("confirm", "go ahead", "locked", "booked", "ready to proceed", "accept")
RESERVE_KEYWORDS: Tuple[str, ...] = ("reserve", "hold", "pencil", "option")
VISIT_KEYWORDS: Tuple[str, ...] = ("visit", "tour", "view", "walkthrough", "see the space", "stop by")
DECLINE_KEYWORDS: Tuple[str, ...] = ("cancel", "decline", "not interested", "no longer", "won't proceed")
CHANGE_KEYWORDS: Tuple[str, ...] = ("change", "adjust", "different", "increase", "decrease", "move", "switch")
QUESTION_KEYWORDS: Tuple[str, ...] = ("could", "would", "do you", "can you")
