"""Adapters that expose agent capabilities for the workflow.

Tests can call `reset_agent_adapter()` to clear the shared singleton between runs.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.domain import IntentLabel

try:  # pragma: no cover - optional dependency resolved at runtime
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - library may be unavailable in tests
    OpenAI = None  # type: ignore


class AgentAdapter:
    """Base adapter defining the agent interface for intent routing and entity extraction."""

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        """Classify an inbound email into intent labels understood by the workflow."""

        raise NotImplementedError("route_intent must be implemented by subclasses.")

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalized entities for the event workflow."""

        raise NotImplementedError("extract_entities must be implemented by subclasses.")

    def describe(self) -> Dict[str, Any]:
        """Metadata describing the underlying adapter implementation."""

        return {"adapter": "stub", "model": "stub"}

    def last_call_info(self) -> Dict[str, Any]:
        """Expose telemetry for the most recent adapter invocation."""

        return {"adapter": "stub", "model": "stub", "phase": "none"}


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


class OpenAIAgentAdapter(AgentAdapter):
    """Adapter backed by OpenAI chat completions for intent/entity tasks."""

    _INTENT_PROMPT = (
        "Classify the email below. Respond with JSON object {\"intent\": <event_request|other>, "
        "\"confidence\": <0-1 float>}."
    )
    _ENTITY_PROMPT = (
        "Extract booking details from the email. Return JSON with keys: date (YYYY-MM-DD or null), "
        "start_time, end_time, city, participants, room, name, email, type, catering, phone, company, "
        "language, notes, billing_address. Use null when unknown."
    )

    _ENTITY_KEYS = [
        "date",
        "start_time",
        "end_time",
        "city",
        "participants",
        "room",
        "name",
        "email",
        "type",
        "catering",
        "phone",
        "company",
        "language",
        "notes",
        "billing_address",
    ]

    def __init__(self) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package is required when AGENT_MODE=openai")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set when AGENT_MODE=openai")
        self._client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_AGENT_MODEL", "gpt-4o-mini")
        self._intent_model = os.getenv("OPENAI_INTENT_MODEL", model)
        self._entity_model = os.getenv("OPENAI_ENTITY_MODEL", model)
        self._fallback = StubAgentAdapter()
        self._last_call_info: Dict[str, Any] = {
            "adapter": "openai",
            "model": self._intent_model,
            "phase": "init",
            "intent_model": self._intent_model,
            "entity_model": self._entity_model,
        }

    def _run_completion(self, *, prompt: str, body: str, subject: str, model: str) -> Dict[str, Any]:
        message = f"Subject: {subject}\n\nBody:\n{body}"
        deterministic = os.getenv("OPENAI_TEST_MODE") == "1"
        system_preface = os.getenv("OPENAI_TEST_SYSTEM_PREFACE")
        system_prompt = f"{system_preface}\n\n{prompt}" if system_preface else prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]
        completion_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        completion_kwargs.update(self._sampling_parameters(deterministic))
        response = self._client.chat.completions.create(**completion_kwargs)
        content = response.choices[0].message.content if response.choices else "{}"
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError:
            return {}

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            payload = self._run_completion(
                prompt=self._INTENT_PROMPT,
                body=body,
                subject=subject,
                model=self._intent_model,
            )
            self._set_last_call_info(adapter_label="openai", model=self._intent_model, phase="intent")
            intent = str(payload.get("intent") or "").strip().lower()
            if intent not in {IntentLabel.EVENT_REQUEST.value, IntentLabel.NON_EVENT.value}:
                intent = IntentLabel.NON_EVENT.value
            confidence_raw = payload.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            return intent or IntentLabel.NON_EVENT.value, confidence
        except Exception:
            self._set_last_call_info(adapter_label="stub", model="stub", phase="intent")
            return self._fallback.route_intent(msg)

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            payload = self._run_completion(
                prompt=self._ENTITY_PROMPT,
                body=body,
                subject=subject,
                model=self._entity_model,
            )
            self._set_last_call_info(adapter_label="openai", model=self._entity_model, phase="entities")
            entities: Dict[str, Any] = {}
            for key in self._ENTITY_KEYS:
                entities[key] = payload.get(key)
            return entities
        except Exception:
            self._set_last_call_info(adapter_label="stub", model="stub", phase="entities")
            return self._fallback.extract_entities(msg)

    def extract_user_information(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        return self.extract_entities(msg)

    def describe(self) -> Dict[str, Any]:
        return {
            "adapter": "openai",
            "intent_model": self._intent_model,
            "entity_model": self._entity_model,
        }

    def last_call_info(self) -> Dict[str, Any]:
        info = dict(self._last_call_info)
        info.setdefault("intent_model", self._intent_model)
        info.setdefault("entity_model", self._entity_model)
        return info

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _sampling_parameters(self, deterministic: bool) -> Dict[str, Any]:
        if deterministic:
            params: Dict[str, Any] = {
                "temperature": 0.0,
                "top_p": 0.0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
            }
            params["seed"] = 42
            return params

        return {
            "temperature": self._float_env("OPENAI_AGENT_TEMPERATURE", 0.0),
            "top_p": self._float_env("OPENAI_AGENT_TOP_P", 1.0),
            "presence_penalty": self._float_env("OPENAI_AGENT_PRESENCE_PENALTY", 0.0),
            "frequency_penalty": self._float_env("OPENAI_AGENT_FREQUENCY_PENALTY", 0.0),
        }

    def _float_env(self, name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _set_last_call_info(self, *, adapter_label: str, model: str, phase: str) -> None:
        self._last_call_info = {
            "adapter": adapter_label,
            "model": model,
            "phase": phase,
            "intent_model": self._intent_model,
            "entity_model": self._entity_model,
        }


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
    if mode == "openai":
        _AGENT_SINGLETON = OpenAIAgentAdapter()
        return _AGENT_SINGLETON
    raise RuntimeError(f"Unsupported AGENT_MODE: {mode}")


def reset_agent_adapter() -> None:
    """Reset the cached adapter instance (used by tests)."""

    global _AGENT_SINGLETON
    _AGENT_SINGLETON = None
