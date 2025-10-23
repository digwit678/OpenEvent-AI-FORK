"""Adapters that expose agent capabilities for the workflow.

Tests can call `reset_agent_adapter()` to clear the shared singleton between runs.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.domain import IntentLabel


class AgentAdapter:
    """Base adapter defining the agent interface for intent routing and entity extraction."""

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        """Classify an inbound email into intent labels understood by the workflow."""

        raise NotImplementedError("route_intent must be implemented by subclasses.")

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalized entities for the event workflow."""

        raise NotImplementedError("extract_entities must be implemented by subclasses.")


class StubAgentAdapter(AgentAdapter):
    """Deterministic heuristic stub replicating the pre-agent workflow behaviour."""

    KEYWORDS = {
        "event",
        "booking",
        "request",
        "date",
        "guests",
        "people",
        "catering",
        "venue",
        "offer",
        "quotation",
        "availability",
        "participants",
        "room",
        "schedule",
    }

    MONTHS = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        subject = (msg.get("subject") or "").lower()
        body = (msg.get("body") or "").lower()
        score = 0.0
        for kw in self.KEYWORDS:
            if kw in subject:
                score += 1.5
            if kw in body:
                score += 1.0
        if "?" in (msg.get("subject") or ""):
            score += 0.1
        if score >= 2.0:
            conf = min(1.0, 0.4 + 0.15 * score)
            return IntentLabel.EVENT_REQUEST.value, conf
        conf = min(1.0, 0.2 + 0.1 * score)
        return IntentLabel.NON_EVENT.value, conf

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        body = msg.get("body") or ""
        lower_body = body.lower()
        entities: Dict[str, Any] = {
            "date": self._extract_date(body),
            "start_time": None,
            "end_time": None,
            "city": None,
            "participants": None,
            "room": None,
            "type": None,
            "catering": None,
            "phone": None,
            "company": None,
            "language": None,
            "notes": None,
        }

        times = self._extract_times(body)
        if times:
            entities["start_time"] = times[0]
            if len(times) > 1:
                entities["end_time"] = times[1]

        participants_match = re.search(
            r"(?:~|approx(?:\.|imately)?|about|around)?\s*(\d{1,4})\s*(?:\+)?\s*(?:ppl|people|guests|participants)\b",
            lower_body,
        )
        if participants_match:
            entities["participants"] = int(participants_match.group(1))

        room_match = re.search(r"\b(room\s*[a-z0-9]+|punkt\.?null)\b", body, re.IGNORECASE)
        if room_match:
            entities["room"] = room_match.group(0).strip()

        for evt_type in ["workshop", "meeting", "conference", "seminar", "wedding", "party", "training"]:
            if evt_type in lower_body:
                entities["type"] = evt_type
                break

        catering_match = re.search(r"catering(?:\s*(?:preference|option|request)?)?:\s*([^\n\r]+)", body, re.IGNORECASE)
        if catering_match:
            entities["catering"] = catering_match.group(1)
        else:
            inline_match = re.search(r"catering\s+(?:is|to|with|for)\s+([^\n\r.]+)", body, re.IGNORECASE)
            if inline_match:
                entities["catering"] = inline_match.group(1)

        phone_match = re.search(r"\+?\d[\d\s\-]{6,}\d", body)
        if phone_match:
            entities["phone"] = phone_match.group(0)

        company_match = re.search(r"company[:\-\s]+([^\n\r,]+)", body, re.IGNORECASE)
        if not company_match:
            company_match = re.search(r"\bfrom\s+([A-Z][A-Za-z0-9 &]+)", body)
        if company_match:
            entities["company"] = company_match.group(1)

        language_label = re.search(r"language[:\-\s]+([^\n\r,]+)", body, re.IGNORECASE)
        if language_label:
            entities["language"] = language_label.group(1)
        language_inline = re.search(r"\bin\s+(english|german|french|italian|spanish|en|de|fr|it|es)\b", lower_body)
        if language_inline:
            entities["language"] = language_inline.group(1)

        city_match = re.search(r"\bin\s+([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)\b", body)
        if city_match:
            entities["city"] = city_match.group(1)

        notes_section = re.search(r"(?:notes?|details?)[:\-]\s*([^\n]+)", body, re.IGNORECASE)
        if notes_section:
            entities["notes"] = notes_section.group(1)

        return entities

    def _extract_times(self, text: str) -> List[str]:
        matches = re.findall(r"\b(\d{1,2}:\d{2})\b", text)
        results: List[str] = []
        for match in matches:
            hours, minutes = map(int, match.split(":"))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                results.append(f"{hours:02d}:{minutes:02d}")
        return results

    def _extract_date(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b",
            r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
            r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{4})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 3 and groups[0].isdigit():
                    day, month, year = map(int, groups)
                elif len(groups) == 3 and groups[1].isdigit():
                    year, month, day = map(int, groups)
                else:
                    day = int(groups[0])
                    month = self.MONTHS.get(groups[1][:3].lower())
                    year = int(groups[2])
                try:
                    parsed = date(year, month, day)
                except ValueError:
                    continue
                return parsed.isoformat()
        return None


_AGENT_SINGLETON: Optional[AgentAdapter] = None


def get_agent_adapter() -> AgentAdapter:
    """Factory selecting the adapter implementation based on AGENT_MODE."""

    global _AGENT_SINGLETON
    if _AGENT_SINGLETON is not None:
        return _AGENT_SINGLETON

    mode = os.environ.get("AGENT_MODE", "stub").lower()
    if mode == "stub":
        _AGENT_SINGLETON = StubAgentAdapter()
        return _AGENT_SINGLETON
    raise RuntimeError(f"Unsupported AGENT_MODE: {mode}")


def reset_agent_adapter() -> None:
    """Reset the cached adapter instance (used by tests)."""

    global _AGENT_SINGLETON
    _AGENT_SINGLETON = None
