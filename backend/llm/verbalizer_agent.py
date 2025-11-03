from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.ux.verb_rubric import enforce as enforce_rubric

logger = logging.getLogger(__name__)

HEADERS_TO_PRESERVE = {
    "AVAILABLE DATES:",
    "ROOM OPTIONS:",
    "NEXT STEP:",
    "OFFER:",
    "PRICE:",
    "VALID UNTIL:",
    "DEPOSIT:",
    "DEADLINE:",
    "AVAILABLE SLOTS:",
    "FOLLOW-UP:",
    "INFO:",
}


def verbalize_gui_reply(
    drafts: List[Dict[str, Any]],
    fallback_text: str,
    *,
    client_email: str | None = None,
) -> str:
    """
    Generate the client-facing reply while preserving deterministic workflow facts.

    Tone selection is controlled by VERBALIZER_TONE (empathetic | plain). When
    the desired tone cannot be produced (e.g., SDK failure), the function
    automatically falls back to the plain deterministic text.
    """

    fallback_text = (fallback_text or "").strip()
    if not fallback_text:
        return fallback_text

    tone = _resolve_tone()
    sections = _split_required_sections(fallback_text)
    must_contain_slot = "18:00–22:00" in fallback_text

    if tone == "plain":
        logger.debug(
            "verbalizer plain tone used",
            extra=_telemetry_extra(tone, drafts, len(sections), False, None),
        )
        return enforce_rubric(fallback_text, fallback_text)

    try:
        prompt_input = _build_prompt_payload(drafts, fallback_text, sections, client_email)
        raw_response = _call_verbalizer(prompt_input)
    except Exception as exc:  # pragma: no cover - network guarded
        logger.warning(
            "verbalizer fallback to plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, str(exc)),
        )
        return enforce_rubric(fallback_text, fallback_text)

    candidate = raw_response.strip()
    if not candidate:
        logger.warning(
            "verbalizer empty response; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "empty"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    if not _validate_sections(candidate, sections):
        logger.warning(
            "verbalizer failed section validation; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "section_mismatch"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    if must_contain_slot and "18:00–22:00" not in candidate:
        logger.warning(
            "verbalizer missing 18:00–22:00 slot; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "missing_slot"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    logger.debug(
        "verbalizer empathetic tone applied",
        extra=_telemetry_extra(tone, drafts, len(sections), False, None),
    )
    return enforce_rubric(candidate, fallback_text)


def _resolve_tone() -> str:
    tone_env = os.getenv("VERBALIZER_TONE")
    if tone_env:
        candidate = tone_env.strip().lower()
        if candidate in {"empathetic", "plain"}:
            return candidate
    empathetic_flag = os.getenv("EMPATHETIC_VERBALIZER", "")
    if empathetic_flag.strip().lower() in {"1", "true", "yes", "on"}:
        return "empathetic"
    return "plain"


def _telemetry_extra(
    tone: str,
    drafts: List[Dict[str, Any]],
    sections_count: int,
    fallback_used: bool,
    reason: Optional[str],
) -> Dict[str, Any]:
    step = next((draft.get("step") for draft in drafts if isinstance(draft, dict) and draft.get("step") is not None), None)
    status = next((draft.get("status") for draft in drafts if isinstance(draft, dict) and draft.get("status") is not None), None)
    payload: Dict[str, Any] = {
        "tone_mode": tone,
        "tone_fallback_used": fallback_used,
        "sections_count": sections_count,
        "step": step,
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    return payload


HEADER_PATTERN = re.compile(r"^[A-Z][A-Z \-/]+:\s*$")


def _split_required_sections(text: str) -> List[Tuple[str, List[str]]]:
    """
    Capture immutable sections: header line + immediate bullet lines.
    """

    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in HEADERS_TO_PRESERVE or HEADER_PATTERN.match(line):
            bullet_lines: List[str] = []
            j = i + 1
            while j < len(lines):
                candidate = lines[j]
                if candidate.startswith("- ") or candidate.startswith("• "):
                    bullet_lines.append(candidate)
                    j += 1
                else:
                    break
            sections.append((line, bullet_lines))
            i = j
        else:
            i += 1
    return sections


def _build_prompt_payload(
    drafts: List[Dict[str, Any]],
    fallback_text: str,
    sections: List[Tuple[str, List[str]]],
    client_email: str | None,
) -> Dict[str, Any]:
    preserve_instructions = "\n".join(
        ["- " + header if bullets else "- " + header for header, bullets in sections]
    )
    facts = {
        "client_email": client_email,
        "draft_messages": drafts,
        "fallback_text": fallback_text,
        "sections": [
            {"header": header, "bullets": bullets} for header, bullets in sections
        ],
    }
    return {
        "system": (
            "You are OpenEvent's voice. Rewrite the provided draft in a warm, "
            "professional tone while preserving all factual content and workflow "
            "structure.\n\n"
            "Rules:\n"
            "1. Preserve the following headers exactly when they appear:\n"
            f"{preserve_instructions or '- (none)'}\n"
            "2. Do not reorder or alter the bullet lines immediately after each header.\n"
            "3. Keep monetary amounts, times (including 18:00–22:00), and room names exactly as given.\n"
            "4. You may add one friendly lead-in sentence before the first header, "
            "but do not add extra commentary anywhere else.\n"
            "5. Never invent new information."
        ),
        "user": (
            "Use the facts below to compose the reply.\n"
            "Return only the final message text.\n"
            f"Facts JSON:\n{json.dumps(facts, ensure_ascii=False)}"
        ),
    }


def _call_verbalizer(payload: Dict[str, Any]) -> str:
    deterministic = os.getenv("OPENAI_TEST_MODE") == "1"
    temperature = 0.0 if deterministic else 0.2
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"OpenAI SDK unavailable: {exc}") from exc

    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_VERBALIZER_MODEL", "gpt-4o-mini"),
        input=[
            {"role": "system", "content": payload["system"]},
            {"role": "user", "content": payload["user"]},
        ],
        temperature=temperature,
    )
    return getattr(response, "output_text", "").strip()


def _validate_sections(text: str, sections: List[Tuple[str, List[str]]]) -> bool:
    positions: List[int] = []
    for header, bullets in sections:
        header_idx = text.find(header)
        if header_idx == -1:
            return False
        positions.append(header_idx)
        last_idx = header_idx
        for bullet in bullets:
            bullet_idx = text.find(bullet, last_idx)
            if bullet_idx == -1:
                return False
            if bullet_idx < last_idx:
                return False
            last_idx = bullet_idx
    if positions != sorted(positions):
        return False
    return True
