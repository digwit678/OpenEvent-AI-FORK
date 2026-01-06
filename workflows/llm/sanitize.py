"""LLM Input Sanitization Utilities.

This module provides sanitization functions to protect against prompt injection
attacks when passing user-provided content to LLM prompts.

Security considerations:
- User input (email body, subject, notes) should be sanitized before LLM calls
- Control characters and escape sequences should be neutralized
- Length limits prevent token exhaustion attacks
- Suspicious patterns are flagged for review

Usage:
    from workflows.llm.sanitize import sanitize_for_llm, sanitize_message

    # Sanitize a single field
    safe_text = sanitize_for_llm(user_input, max_length=2000)

    # Sanitize an entire message dict
    safe_message = sanitize_message({"subject": subject, "body": body})
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Maximum lengths for different field types
MAX_SUBJECT_LENGTH = 500
MAX_BODY_LENGTH = 10000
MAX_NOTES_LENGTH = 5000
MAX_FIELD_LENGTH = 2000  # Default for other fields

# Patterns that might indicate prompt injection attempts
SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"forget\s+(everything|all|your)\s+(you\s+)?(know|learned|were\s+told)",
    r"you\s+are\s+now\s+(a|an|the)",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*",
    r"<\s*system\s*>",
    r"\[\s*SYSTEM\s*\]",
    r"act\s+as\s+(if\s+)?(you\s+)?(are|were|have)",
    r"pretend\s+(to\s+be|you\s+are|you\s+have)",
    r"override\s+(your\s+)?(instructions?|programming|rules?)",
    r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions?)",
    r"what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions?|hidden\s+instructions?)",
    r"print\s+(your\s+)?(system\s+)?(prompt|instructions?)",
    r"(show|tell|give)\s+(me\s+)?(your\s+)?(hidden\s+)?instructions?",
    r"(do\s+)?anything\s+now",  # DAN pattern
    r"no\s+(safety\s+)?guidelines?",
    r"without\s+(any\s+)?(restrictions?|limits?|safety)",
]

# Compiled pattern for efficiency
_SUSPICIOUS_RE = re.compile(
    "|".join(f"({p})" for p in SUSPICIOUS_PATTERNS),
    re.IGNORECASE
)

# Control characters to remove (except newlines and tabs which are normalized)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Multiple newlines/spaces normalization
_EXCESSIVE_WHITESPACE_RE = re.compile(r"\n{4,}")
_EXCESSIVE_SPACES_RE = re.compile(r" {10,}")


def sanitize_for_llm(
    text: Any,
    *,
    max_length: int = MAX_FIELD_LENGTH,
    field_name: str = "input",
    strip_control_chars: bool = True,
    normalize_whitespace: bool = True,
    check_injection: bool = True,
) -> str:
    """Sanitize user-provided text before including in LLM prompts.

    Args:
        text: The input text to sanitize (will be converted to string)
        max_length: Maximum allowed length (truncates if exceeded)
        field_name: Name of the field (for logging/debugging)
        strip_control_chars: Remove control characters
        normalize_whitespace: Reduce excessive whitespace
        check_injection: Check for suspicious prompt injection patterns

    Returns:
        Sanitized string safe for LLM prompts
    """
    if text is None:
        return ""

    # Convert to string
    if not isinstance(text, str):
        text = str(text)

    # Strip leading/trailing whitespace
    result = text.strip()

    # Remove control characters (keep \n and \t but normalize them)
    if strip_control_chars:
        result = _CONTROL_CHARS_RE.sub("", result)

    # Normalize excessive whitespace
    if normalize_whitespace:
        result = _EXCESSIVE_WHITESPACE_RE.sub("\n\n\n", result)
        result = _EXCESSIVE_SPACES_RE.sub("    ", result)
        # Normalize tabs to spaces
        result = result.replace("\t", "    ")

    # Truncate to max length
    if len(result) > max_length:
        result = result[:max_length] + "..."

    return result


def check_prompt_injection(text: str) -> tuple[bool, Optional[str]]:
    """Check if text contains suspicious prompt injection patterns.

    Args:
        text: The text to check

    Returns:
        Tuple of (is_suspicious, matched_pattern)
    """
    if not text:
        return False, None

    match = _SUSPICIOUS_RE.search(text)
    if match:
        return True, match.group(0)

    return False, None


def sanitize_message(
    message: Dict[str, Any],
    *,
    check_injection: bool = True,
) -> Dict[str, str]:
    """Sanitize a message dict (subject, body, etc.) for LLM processing.

    Args:
        message: Dict with 'subject', 'body', and optionally other fields
        check_injection: Whether to check for prompt injection patterns

    Returns:
        Sanitized message dict with all string values
    """
    result: Dict[str, str] = {}

    # Define field-specific max lengths
    field_limits = {
        "subject": MAX_SUBJECT_LENGTH,
        "body": MAX_BODY_LENGTH,
        "notes": MAX_NOTES_LENGTH,
        "special_requirements": MAX_NOTES_LENGTH,
        "additional_info": MAX_NOTES_LENGTH,
    }

    for key, value in message.items():
        if value is None:
            result[key] = ""
            continue

        max_len = field_limits.get(key, MAX_FIELD_LENGTH)
        result[key] = sanitize_for_llm(
            value,
            max_length=max_len,
            field_name=key,
            check_injection=check_injection,
        )

    return result


def escape_for_json_prompt(text: str) -> str:
    """Escape text for safe inclusion in JSON that will be sent to LLM.

    This provides an additional layer of protection when user text
    will be JSON-serialized and embedded in prompts.

    Args:
        text: The text to escape

    Returns:
        Escaped text safe for JSON embedding
    """
    if not text:
        return ""

    # Escape backslashes first, then other special chars
    result = text.replace("\\", "\\\\")
    result = result.replace('"', '\\"')
    result = result.replace("\n", "\\n")
    result = result.replace("\r", "\\r")
    result = result.replace("\t", "\\t")

    return result


def wrap_user_content(text: str, label: str = "USER_INPUT") -> str:
    """Wrap user content with clear delimiters for LLM context.

    This helps the LLM distinguish between instructions and user content,
    making prompt injection attacks less effective.

    Args:
        text: The user-provided text
        label: Label to use in delimiters

    Returns:
        Text wrapped with delimiters
    """
    sanitized = sanitize_for_llm(text)
    return f"<{label}>\n{sanitized}\n</{label}>"


# Convenience functions for common use cases
def sanitize_email_body(body: str) -> str:
    """Sanitize email body text for LLM processing."""
    return sanitize_for_llm(body, max_length=MAX_BODY_LENGTH, field_name="email_body")


def sanitize_email_subject(subject: str) -> str:
    """Sanitize email subject for LLM processing."""
    return sanitize_for_llm(subject, max_length=MAX_SUBJECT_LENGTH, field_name="email_subject")


def sanitize_notes(notes: str) -> str:
    """Sanitize notes/special requirements for LLM processing."""
    return sanitize_for_llm(notes, max_length=MAX_NOTES_LENGTH, field_name="notes")
