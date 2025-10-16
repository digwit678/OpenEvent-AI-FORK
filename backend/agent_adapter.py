from __future__ import annotations

import os
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from vocabulary import IntentLabel


class AgentAdapter:
    """Base adapter defining the agent interface for intent routing and relevant information extraction."""

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        """
        Input: msg with keys {subject, body, from_email, from_name, ts}
        Output: (intent, confidence) where intent ∈ {"event_request","other"}
        """
        raise NotImplementedError("route_intent must be implemented by subclasses.")

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return the normalized entities dict for workflow_email.to_event_data:
        {
          "date": "YYYY-MM-DD"|None,
          "start_time": "HH:MM"|None,
          "end_time": "HH:MM"|None,
          "city": str|None,
          "participants": int|None,
          "room": str|None,
          "type": str|None,
          "catering": str|None,
          "phone": str|None,
          "company": str|None,
          "language": str|None,
          "notes": str|None
        }
        """
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

        notes_match = re.search(r"(?:notes|additional info)[:\-\s]+([^\n\r]+)", body, re.IGNORECASE)
        if notes_match:
            entities["notes"] = notes_match.group(1)

        return entities

    def _extract_date(self, txt: str) -> Optional[str]:
        patterns = [
            re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"),
            re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b"),
            re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:,)?\s+(\d{4})\b"),
        ]
        for pattern in patterns:
            for match in pattern.finditer(txt):
                try:
                    return self._normalize_date_match(match)
                except ValueError:
                    continue
        return None

    def _normalize_date_match(self, match: re.Match) -> str:
        groups = match.groups()
        if len(groups) != 3:
            raise ValueError("Invalid date groups")
        if groups[0].isdigit() and groups[1].isdigit():
            day = int(groups[0])
            month = int(groups[1])
            year = int(groups[2])
        elif groups[0].isdigit():
            day = int(groups[0])
            month = self._month_from_token(groups[1])
            year = int(groups[2])
        else:
            month = self._month_from_token(groups[0])
            day = int(groups[1])
            year = int(groups[2])
        return date(year, month, day).isoformat()

    def _month_from_token(self, token: str) -> int:
        token = token.strip().lower()
        if len(token) >= 3:
            token = token[:4] if token.startswith("sept") else token[:3]
        if token in self.MONTHS:
            return self.MONTHS[token]
        raise ValueError("Unknown month token")

    def _extract_times(self, txt: str) -> List[str]:
        pattern = re.compile(r"\b(\d{1,2})(?:(?::|h)(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
        times: List[str] = []
        for match in pattern.finditer(txt):
            hour = int(match.group(1))
            minute = match.group(2)
            am_pm = match.group(3).lower() if match.group(3) else None
            if minute is None and am_pm is None:
                continue
            minute_val = int(minute) if minute else 0
            if minute_val > 59 or hour > 24:
                continue
            if am_pm:
                if hour == 12:
                    hour = 0
                if am_pm == "pm":
                    hour += 12
            if hour == 24:
                hour = 0
            times.append(f"{hour:02d}:{minute_val:02d}")
        return times


def get_agent_adapter() -> AgentAdapter:
    """
    If ENV AGENT_MODE=stub → return StubAgentAdapter
    Else → return StubAgentAdapter for now (placeholder)
    """
    mode = (os.getenv("AGENT_MODE") or "stub").strip().lower()
    if mode == "stub":
        return StubAgentAdapter()
    # Placeholder until real agent integration is available.
    return StubAgentAdapter()


# NOTE: When plugging in a real agent, subclass AgentAdapter and implement
# route_intent/extract_entities to call the LLM or orchestration layer while
# preserving the exact shapes defined above to avoid DB drift.
