from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class RubricReport:
    """Structured outcome for UX rubric validation."""

    ok: bool
    reason: Optional[str] = None
    greeting: Optional[str] = None
    word_count: int = 0
    bullet_count: int = 0
    cta_count: int = 0


_BULLET_PREFIXES = ("- ", "• ", "* ")
_GREETING_PATTERN = re.compile(
    r"^(hello|hi|hey|guten tag|grüezi|good\s+(?:morning|afternoon|evening))[,\s]",
    re.IGNORECASE,
)
_CTA_PATTERN = re.compile(r"\b(next step:|please let me know|let me know|could you confirm|can you confirm)\b", re.IGNORECASE)


def _iter_lines(text: str) -> Iterable[str]:
    for raw in text.splitlines():
        yield raw.rstrip()


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w']+\b", text, flags=re.UNICODE)
    return len(tokens)


def validate(text: str) -> RubricReport:
    """
    Validate a rendered assistant message against the UX rubric.

    Rules:
    - Greeting required on the first non-empty line.
    - ≤120 words OR ≤6 bullet lines (both conditions must be satisfied).
    - Exactly one CTA line (keywords or explicit NEXT STEP label).
    """

    if not text:
        return RubricReport(ok=False, reason="empty")

    lines = list(_iter_lines(text))
    non_empty = [line for line in lines if line.strip()]

    greeting = None
    for line in non_empty:
        if _GREETING_PATTERN.match(line.strip()):
            greeting = line.strip()
            break
        if line.strip():
            greeting = line.strip()
            break

    if not greeting or not _GREETING_PATTERN.match(greeting.lower()):
        return RubricReport(ok=False, reason="missing_greeting", greeting=greeting)

    bullet_tuple = tuple(_BULLET_PREFIXES)
    bullets = sum(1 for line in lines if line.strip().startswith(bullet_tuple))
    words = _word_count(text)

    if words > 120:
        return RubricReport(
            ok=False,
            reason="too_many_words",
            greeting=greeting,
            word_count=words,
            bullet_count=bullets,
        )

    if bullets > 6:
        return RubricReport(
            ok=False,
            reason="too_many_bullets",
            greeting=greeting,
            bullet_count=bullets,
            word_count=words,
        )

    cta_lines = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("NEXT STEP:"):
            cta_lines += 1
            continue
        if _CTA_PATTERN.search(line):
            prev = lines[idx - 1].strip().upper() if idx > 0 else ""
            if prev.startswith("NEXT STEP:"):
                continue
            cta_lines += 1
    if cta_lines != 1:
        return RubricReport(
            ok=False,
            reason="cta_count_mismatch",
            greeting=greeting,
            bullet_count=bullets,
            word_count=words,
            cta_count=cta_lines,
        )

    return RubricReport(
        ok=True,
        greeting=greeting,
        word_count=words,
        bullet_count=bullets,
        cta_count=cta_lines,
    )


def _default_greeting(existing: Optional[str]) -> str:
    if existing and _GREETING_PATTERN.match(existing.lower()):
        return existing
    return "Hello,"


def _repair(text: str, report: RubricReport) -> str:
    lines = list(_iter_lines(text))

    if report.reason == "missing_greeting":
        lines = [_default_greeting(report.greeting)] + [""] + lines
        return "\n".join(lines).strip("\n")

    if report.reason == "too_many_words":
        limit = 120
        total = 0
        truncated: list[str] = []
        for line in lines:
            words_in_line = re.findall(r"\b[\w']+\b", line, flags=re.UNICODE)
            if not words_in_line:
                truncated.append(line)
                continue
            if total + len(words_in_line) <= limit:
                truncated.append(line)
                total += len(words_in_line)
                continue
            remaining = limit - total
            if remaining > 0:
                shortened = " ".join(words_in_line[:remaining])
                truncated.append(shortened)
            break
        return "\n".join(truncated).strip()

    if report.reason == "too_many_bullets":
        bullet_tuple = tuple(_BULLET_PREFIXES)
        kept = 0
        filtered: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(bullet_tuple):
                if kept >= 6:
                    continue
                kept += 1
            filtered.append(line)
        return "\n".join(filtered)

    if report.reason == "cta_count_mismatch":
        cta_indices: list[int] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.upper().startswith("NEXT STEP:"):
                cta_indices.append(idx)
            elif _CTA_PATTERN.search(line):
                prev = lines[idx - 1].strip().upper() if idx > 0 else ""
                if prev.startswith("NEXT STEP:"):
                    continue
                cta_indices.append(idx)
        if not cta_indices:
            lines.append("")
            lines.append("NEXT STEP: Please let me know how you'd like to proceed.")
            return "\n".join(lines)
        first = cta_indices[0]
        cleaned: list[str] = []
        for idx, line in enumerate(lines):
            stripped_upper = line.strip().upper()
            if idx == first:
                cleaned.append(line)
                continue
            if stripped_upper.startswith("NEXT STEP:"):
                continue
            if _CTA_PATTERN.search(line):
                prev = lines[idx - 1].strip().upper() if idx > 0 else ""
                if prev.startswith("NEXT STEP:"):
                    cleaned.append(line)
                    continue
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    return text


def enforce(text: str, fallback: str) -> str:
    """
    Return the provided text when it satisfies the rubric, otherwise fall back.
    """

    candidate = text
    for _ in range(2):
        report = validate(candidate)
        if report.ok:
            return candidate
        candidate = _repair(candidate, report)

    fallback_report = validate(fallback)
    if fallback_report.ok:
        return fallback
    repaired_fallback = _repair(fallback, fallback_report)
    final_report = validate(repaired_fallback)
    return repaired_fallback if final_report.ok else fallback
