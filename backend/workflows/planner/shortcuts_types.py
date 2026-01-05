"""Type definitions and data structures for smart shortcuts.

This module contains dataclasses, constants, and payload types used
by the smart shortcuts planner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Constants ---------------------------------------------------------------------

PREASK_CLASS_COPY = {
    "catering": "Would you like to see catering options we can provide on-site?",
    "av": "Would you like to see AV add-ons (e.g., extra mics, adapters)?",
    "furniture": "Would you like to see furniture layouts or add-ons?",
}

CLASS_KEYWORDS = {
    "catering": {"catering", "food", "menu", "buffet", "lunch", "coffee"},
    "av": {"av", "audio", "visual", "video", "projector", "sound", "microphone"},
    "furniture": {"furniture", "chairs", "tables", "layout", "seating"},
}

ORDINAL_WORDS_BY_LANG = {
    "en": {
        "first": 1,
        "1st": 1,
        "one": 1,
        "second": 2,
        "2nd": 2,
        "two": 2,
        "third": 3,
        "3rd": 3,
        "three": 3,
        "fourth": 4,
        "4th": 4,
        "four": 4,
        "fifth": 5,
        "5th": 5,
        "five": 5,
    },
    "de": {
        "erste": 1,
        "zuerst": 1,
        "zweite": 2,
        "zweiter": 2,
        "dritte": 3,
        "dritter": 3,
        "vierte": 4,
        "vierter": 4,
        "fuenfte": 5,
    },
}


# Intent structures -------------------------------------------------------------


@dataclass
class ParsedIntent:
    """Represents a parsed user intent from message text."""
    type: str
    data: Dict[str, Any]
    verifiable: bool
    reason: Optional[str] = None


@dataclass
class PlannerTelemetry:
    """Telemetry data collected during shortcut planning."""
    executed_intents: List[str] = field(default_factory=list)
    combined_confirmation: bool = False
    needs_input_next: Optional[str] = None
    deferred: List[Dict[str, Any]] = field(default_factory=list)
    artifact_match: Optional[str] = None
    added_items: List[Dict[str, Any]] = field(default_factory=list)
    missing_items: List[Dict[str, Any]] = field(default_factory=list)
    offered_hil: bool = False
    hil_request_created: bool = False
    budget_provided: bool = False
    upsell_shown: bool = False
    room_checked: bool = False
    menus_included: str = "false"
    menus_phase: str = "none"
    product_prices_included: bool = False
    product_price_missing: bool = False
    gatekeeper_passed: Optional[bool] = None
    answered_question_first: Optional[bool] = None
    delta_availability_used: Optional[bool] = None
    preask_candidates: List[str] = field(default_factory=list)
    preask_shown: List[str] = field(default_factory=list)
    preask_response: Dict[str, str] = field(default_factory=dict)
    preview_class_shown: str = "none"
    preview_items_count: int = 0
    choice_context_active: bool = False
    selection_method: str = "none"
    re_prompt_reason: str = "none"
    legacy_shortcut_invocations: int = 0
    shortcut_path_used: str = "none"

    def to_log(self, msg_id: Optional[str], event_id: Optional[str]) -> Dict[str, Any]:
        """Convert telemetry to a loggable dictionary."""
        return {
            "executed_intents": list(self.executed_intents),
            "combined_confirmation": bool(self.combined_confirmation),
            "needs_input_next": self.needs_input_next,
            "deferred_count": len(self.deferred),
            "source_msg_id": msg_id,
            "event_id": event_id,
            "artifact_match": self.artifact_match,
            "added_items": self.added_items,
            "missing_items": self.missing_items,
            "offered_hil": self.offered_hil,
            "hil_request_created": self.hil_request_created,
            "budget_provided": self.budget_provided,
            "upsell_shown": self.upsell_shown,
            "room_checked": self.room_checked,
            "menus_included": self.menus_included,
            "menus_phase": self.menus_phase,
            "product_prices_included": self.product_prices_included,
            "product_price_missing": self.product_price_missing,
            "gatekeeper_passed": self.gatekeeper_passed,
            "answered_question_first": self.answered_question_first,
            "delta_availability_used": self.delta_availability_used,
            "legacy_shortcut_invocations": self.legacy_shortcut_invocations,
            "shortcut_path_used": self.shortcut_path_used,
        }


@dataclass
class AtomicDecision:
    """Decision about which intents to execute atomically."""
    execute: List[ParsedIntent]
    deferred: List[Tuple[ParsedIntent, str]]
    use_combo: bool = False
    shortcut_path_used: str = "none"


class PlannerResult(dict):
    """Dictionary-like payload returned by the shortcut planner with a stable accessor."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__(payload)

    def merged(self) -> Dict[str, Any]:
        """Return a shallow copy of the planner payload for external consumers."""
        payload = dict(self)
        payload.setdefault("message", "")
        payload.setdefault("telemetry", {})
        payload.setdefault("state_delta", {})
        return payload


# Compatibility aliases (underscore prefix convention for internal use)
_PREASK_CLASS_COPY = PREASK_CLASS_COPY
_CLASS_KEYWORDS = CLASS_KEYWORDS
_ORDINAL_WORDS_BY_LANG = ORDINAL_WORDS_BY_LANG
