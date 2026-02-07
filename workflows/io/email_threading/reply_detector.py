"""Layer 1: Reply Detection (NO LLM required).

This module detects email replies using protocol-level headers and tokens,
enabling deterministic thread linking without calling any LLM. It checks:

1. In-Reply-To header (RFC 5322) - direct parent reference
2. References header (RFC 5322) - ancestor chain
3. OE footer token [OE-xxxxxxxx] - explicit event linking

Only when all three methods fail does the message proceed to Layer 2 (LLM resolver).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import EmailMessage, ThreadMapping

logger = logging.getLogger(__name__)

# Pattern to detect explicit OE tokens in email body/footer
# Format: [OE-xxxxxxxx] where x is alphanumeric (8 characters)
OE_TOKEN_PATTERN = re.compile(r'\[OE-([a-zA-Z0-9]{8})\]', re.IGNORECASE)


def is_reply(email_headers: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Detect if email is a reply using ONLY headers (no LLM).

    Checks three sources in order of reliability:
    1. In-Reply-To header - explicit parent message reference
    2. References header - chain of ancestor messages
    3. OE footer token - custom tracking token

    Args:
        email_headers: Dict containing email headers and optionally body.
            Expected keys: "In-Reply-To", "References", "body", "Message-ID"

    Returns:
        Tuple of (is_reply: bool, parent_identifier: Optional[str])
        - If is_reply=True, parent_identifier is the Message-ID or OE token
        - If is_reply=False, parent_identifier is None
    """
    # Check In-Reply-To header (most reliable)
    in_reply_to = _extract_header(email_headers, "In-Reply-To", "in_reply_to", "in-reply-to")
    if in_reply_to:
        logger.debug("[THREAD] Reply detected via In-Reply-To: %s", in_reply_to)
        return True, _clean_message_id(in_reply_to)

    # Check References header chain (next most reliable)
    references = _extract_references(email_headers)
    if references:
        # Last reference is the immediate parent
        parent_id = _clean_message_id(references[-1])
        logger.debug("[THREAD] Reply detected via References chain (parent: %s)", parent_id)
        return True, parent_id

    # Check for explicit OE token in body/footer
    body = email_headers.get("body", "")
    if body:
        token_match = OE_TOKEN_PATTERN.search(body)
        if token_match:
            token = token_match.group(1).lower()
            parent_id = f"oe-token:{token}"
            logger.debug("[THREAD] Reply detected via OE token: %s", token)
            return True, parent_id

    # No reply indicators found
    return False, None


def link_reply_to_thread(
    parent_identifier: str,
    email_messages: List[Dict[str, Any]],
    thread_mappings: List[Dict[str, Any]],
) -> Optional[str]:
    """Link reply to existing event using stored message metadata.

    Searches for the parent message/token in:
    1. email_messages collection (by message_id)
    2. thread_mappings collection (by OE token or thread_id)

    Args:
        parent_identifier: The Message-ID or OE token from is_reply()
        email_messages: List of stored EmailMessage dicts
        thread_mappings: List of stored ThreadMapping dicts

    Returns:
        event_id if found, None otherwise
    """
    # Handle OE token format
    if parent_identifier.startswith("oe-token:"):
        token = parent_identifier.split(":", 1)[1]
        # Search thread_mappings for token
        for mapping in thread_mappings:
            email_thread_id = mapping.get("email_thread_id", "")
            if email_thread_id.endswith(token) or token in email_thread_id.lower():
                event_id = mapping.get("event_id")
                logger.debug("[THREAD] OE token %s linked to event %s", token, event_id)
                return event_id
        logger.debug("[THREAD] OE token %s not found in mappings", token)
        return None

    # Search email_messages for parent message_id
    parent_clean = _clean_message_id(parent_identifier)
    for msg in email_messages:
        msg_id = _clean_message_id(msg.get("message_id", ""))
        if msg_id == parent_clean:
            event_id = msg.get("resolved_event_id")
            if event_id:
                logger.debug("[THREAD] Parent message %s linked to event %s", parent_clean, event_id)
                return event_id

    # Also check if parent matches any thread_id directly
    for mapping in thread_mappings:
        if _clean_message_id(mapping.get("email_thread_id", "")) == parent_clean:
            event_id = mapping.get("event_id")
            logger.debug("[THREAD] Thread mapping %s linked to event %s", parent_clean, event_id)
            return event_id

    logger.debug("[THREAD] Parent %s not found in stored messages", parent_clean)
    return None


def store_email_message(
    db: Dict[str, Any],
    message_id: str,
    from_address: str,
    resolved_event_id: str,
    in_reply_to: Optional[str] = None,
    references: Optional[List[str]] = None,
) -> None:
    """Store email message metadata for future thread linking.

    Called after a message is processed to record its resolution.
    Enables future replies to be linked without LLM.

    Args:
        db: The database dict
        message_id: RFC 5322 Message-ID header
        from_address: Sender email address
        resolved_event_id: The event this message was resolved to
        in_reply_to: Optional In-Reply-To header
        references: Optional References header list
    """
    email_messages = db.setdefault("email_messages", [])

    # Avoid duplicates
    clean_id = _clean_message_id(message_id)
    for existing in email_messages:
        if _clean_message_id(existing.get("message_id", "")) == clean_id:
            # Update resolution if not set
            if not existing.get("resolved_event_id"):
                existing["resolved_event_id"] = resolved_event_id
            return

    # Add new message record
    msg_record = EmailMessage(
        message_id=clean_id,
        from_address=(from_address or "").lower(),
        in_reply_to=_clean_message_id(in_reply_to) if in_reply_to else None,
        references=[_clean_message_id(r) for r in (references or [])],
        resolved_event_id=resolved_event_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    email_messages.append(msg_record.to_dict())
    logger.debug("[THREAD] Stored email message %s -> event %s", clean_id, resolved_event_id)


def create_thread_mapping(
    db: Dict[str, Any],
    email_thread_id: str,
    event_id: str,
) -> None:
    """Create a mapping from thread ID to event for quick lookup.

    Used when processing a new thread to enable future lookups.

    Args:
        db: The database dict
        email_thread_id: Message-ID or OE token
        event_id: The resolved event ID
    """
    thread_mappings = db.setdefault("thread_mappings", [])

    # Avoid duplicates
    clean_id = _clean_message_id(email_thread_id)
    for existing in thread_mappings:
        if _clean_message_id(existing.get("email_thread_id", "")) == clean_id:
            return

    mapping = ThreadMapping(
        email_thread_id=clean_id,
        event_id=event_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    thread_mappings.append(mapping.to_dict())
    logger.debug("[THREAD] Created thread mapping %s -> event %s", clean_id, event_id)


def _extract_header(headers: Dict[str, Any], *keys: str) -> Optional[str]:
    """Extract a header value trying multiple key variations."""
    for key in keys:
        value = headers.get(key)
        if value:
            if isinstance(value, list):
                return value[0] if value else None
            return str(value)
    return None


def _extract_references(headers: Dict[str, Any]) -> List[str]:
    """Extract References header as a list of message IDs."""
    # Check for list directly first (before _extract_header which returns first element)
    for key in ("References", "references"):
        value = headers.get(key)
        if value:
            if isinstance(value, list):
                # Clean each reference in the list
                return [_clean_message_id(r) for r in value if r]
            # String: whitespace-separated
            return [r.strip() for r in str(value).split() if r.strip()]

    return []


def _clean_message_id(msg_id: Optional[str]) -> str:
    """Normalize Message-ID by removing angle brackets and whitespace."""
    if not msg_id:
        return ""
    # Remove < > brackets if present
    cleaned = msg_id.strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    return cleaned.strip()
