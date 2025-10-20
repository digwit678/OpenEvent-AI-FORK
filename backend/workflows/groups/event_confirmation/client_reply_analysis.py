from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import LLMNode

__all__ = ["AnalyzeClientReply"]


class AnalyzeClientReply(LLMNode):
    """Interpret the client's follow-up message after the offer is delivered."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_text = (payload.get("client_msg_text") or "").strip()
        lowered = message_text.lower()
        deposit_percent = payload.get("deposit_percent")
        visit_allowed = bool(payload.get("visit_allowed", False))

        result: Dict[str, Any] = {
            "intent": "questions",
            "deposit_acknowledged": False,
            "proposed_times": [],
            "requested_changes": {},
        }

        if "accept" in lowered or "confirm" in lowered:
            result["intent"] = "accept"
            result["deposit_acknowledged"] = "deposit" in lowered or "down payment" in lowered
        elif "reserve" in lowered or "hold" in lowered:
            result["intent"] = "reserve_only"
        elif "view" in lowered or "visit" in lowered:
            result["intent"] = "request_viewing"
            result["proposed_times"] = self._extract_times(message_text) if visit_allowed else []
        elif "change" in lowered or "negotiate" in lowered or "adjust" in lowered:
            result["intent"] = "negotiate"
            result["requested_changes"] = {"note": message_text}
        elif "question" in lowered or "clarify" in lowered:
            result["intent"] = "questions"

        if deposit_percent in (None, 0):
            result["deposit_acknowledged"] = False

        return result

    def _extract_times(self, text: str) -> List[str]:
        """Naive heuristic to keep free-form client availability proposals."""

        separators = [",", ";", " or ", " and "]
        candidates: List[str] = [text]
        for sep in separators:
            temp: List[str] = []
            for chunk in candidates:
                temp.extend([part.strip() for part in chunk.split(sep)])
            candidates = temp

        suggestions = [entry for entry in candidates if any(char.isdigit() for char in entry)]
        return suggestions[:3] or candidates[:3]
