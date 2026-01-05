"""
Client Memory Service - Personalization through conversation history.

Stores and retrieves client-specific context for personalized responses:
- Message history (client + assistant messages)
- Profile enrichment (preferences, language, notes)
- Summary generation for prompt injection

See docs/reports/CLIENT_MEMORY_PLAN_2026_01_03.md for full specification.

Config toggles (environment variables):
- CLIENT_MEMORY_ENABLED=0|1 (default: 0)
- CLIENT_MEMORY_MAX_MESSAGES=50 (cap history length)
- CLIENT_MEMORY_SUMMARY_INTERVAL=10 (re-summarize every N messages)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Configuration from environment
CLIENT_MEMORY_ENABLED = os.getenv("CLIENT_MEMORY_ENABLED", "0") == "1"
CLIENT_MEMORY_MAX_MESSAGES = int(os.getenv("CLIENT_MEMORY_MAX_MESSAGES", "50"))
CLIENT_MEMORY_SUMMARY_INTERVAL = int(os.getenv("CLIENT_MEMORY_SUMMARY_INTERVAL", "10"))


def is_enabled() -> bool:
    """Check if client memory feature is enabled."""
    return CLIENT_MEMORY_ENABLED


def _normalize_email(email: str) -> str:
    """Normalize email for consistent keying."""
    return (email or "").strip().lower()


def _ensure_memory_structure(client: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure client dict has memory-related fields."""
    # Extend profile with memory fields
    profile = client.setdefault("profile", {})
    profile.setdefault("language", None)
    profile.setdefault("preferences", [])
    profile.setdefault("notes", [])

    # Memory-specific fields
    client.setdefault("memory", {
        "conversation_history": [],  # Full message history for memory
        "summary": None,             # LLM-generated personalization summary
        "last_updated": None,
        "message_count": 0,
    })

    return client


def append_message(
    client: Dict[str, Any],
    role: str,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append a message to client's conversation history.

    Args:
        client: Client dict from database
        role: "client" or "assistant"
        text: Message content
        metadata: Optional extra data (intent, step, etc.)
    """
    if not CLIENT_MEMORY_ENABLED:
        return

    _ensure_memory_structure(client)
    memory = client["memory"]

    # Create message entry
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "role": role,
        "text": text[:500],  # Truncate to prevent bloat
    }
    if metadata:
        entry["metadata"] = metadata

    # Append to history
    history = memory["conversation_history"]
    history.append(entry)

    # Enforce max length (FIFO eviction)
    while len(history) > CLIENT_MEMORY_MAX_MESSAGES:
        history.pop(0)

    # Update counters
    memory["message_count"] = memory.get("message_count", 0) + 1
    memory["last_updated"] = datetime.utcnow().isoformat()

    # Check if summary needs refresh
    if memory["message_count"] % CLIENT_MEMORY_SUMMARY_INTERVAL == 0:
        _mark_summary_stale(memory)


def _mark_summary_stale(memory: Dict[str, Any]) -> None:
    """Mark summary as needing refresh (actual refresh is lazy)."""
    memory["summary_stale"] = True


def get_memory_context(
    client: Dict[str, Any],
    max_messages: int = 10,
) -> Dict[str, Any]:
    """
    Get client memory context for prompt injection.

    Returns:
        Dict with:
        - summary: Personalization summary (if available)
        - recent_messages: Last N messages
        - profile: Client profile data
        - preferences: Extracted preferences
    """
    if not CLIENT_MEMORY_ENABLED:
        return {}

    _ensure_memory_structure(client)
    memory = client.get("memory", {})
    profile = client.get("profile", {})

    # Get recent messages
    history = memory.get("conversation_history", [])
    recent = history[-max_messages:] if history else []

    return {
        "summary": memory.get("summary"),
        "recent_messages": recent,
        "profile": {
            "name": profile.get("name"),
            "company": profile.get("org"),
            "language": profile.get("language"),
        },
        "preferences": profile.get("preferences", []),
        "notes": profile.get("notes", []),
        "message_count": memory.get("message_count", 0),
    }


def format_memory_for_prompt(client: Dict[str, Any], max_messages: int = 5) -> str:
    """
    Format client memory as a string for LLM prompt injection.

    Returns a concise summary suitable for system prompt context.
    """
    if not CLIENT_MEMORY_ENABLED:
        return ""

    context = get_memory_context(client, max_messages=max_messages)
    if not context:
        return ""

    parts = []

    # Add summary if available
    if context.get("summary"):
        parts.append(f"Client summary: {context['summary']}")

    # Add profile info
    profile = context.get("profile", {})
    if profile.get("name"):
        parts.append(f"Client name: {profile['name']}")
    if profile.get("company"):
        parts.append(f"Company: {profile['company']}")
    if profile.get("language"):
        parts.append(f"Preferred language: {profile['language']}")

    # Add preferences
    prefs = context.get("preferences", [])
    if prefs:
        parts.append(f"Known preferences: {', '.join(prefs[:5])}")

    # Add recent conversation context
    recent = context.get("recent_messages", [])
    if recent:
        parts.append(f"Recent conversation ({len(recent)} messages):")
        for msg in recent[-3:]:  # Last 3 only for prompt
            role = msg.get("role", "?")
            text = msg.get("text", "")[:100]
            parts.append(f"  [{role}]: {text}...")

    return "\n".join(parts) if parts else ""


def update_profile(
    client: Dict[str, Any],
    language: Optional[str] = None,
    preferences: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
) -> None:
    """
    Update client profile with memory-related fields.

    Args:
        client: Client dict from database
        language: Detected or stated language preference
        preferences: List of preference strings to add
        notes: List of notes to add
    """
    if not CLIENT_MEMORY_ENABLED:
        return

    _ensure_memory_structure(client)
    profile = client["profile"]

    if language:
        profile["language"] = language

    if preferences:
        existing = set(profile.get("preferences", []))
        existing.update(preferences)
        profile["preferences"] = list(existing)[:20]  # Cap at 20

    if notes:
        existing = profile.get("notes", [])
        existing.extend(notes)
        profile["notes"] = existing[-10:]  # Keep last 10


def generate_summary(client: Dict[str, Any]) -> Optional[str]:
    """
    Generate a personalization summary from conversation history.

    This is a placeholder for LLM-based summarization.
    For now, returns a simple rule-based summary.
    """
    if not CLIENT_MEMORY_ENABLED:
        return None

    _ensure_memory_structure(client)
    memory = client.get("memory", {})
    profile = client.get("profile", {})

    # Simple rule-based summary (LLM version would go here)
    parts = []

    if profile.get("name"):
        parts.append(f"Returning client: {profile['name']}")

    msg_count = memory.get("message_count", 0)
    if msg_count > 10:
        parts.append(f"Active correspondent ({msg_count} messages)")
    elif msg_count > 0:
        parts.append(f"Recent contact ({msg_count} messages)")

    prefs = profile.get("preferences", [])
    if prefs:
        parts.append(f"Preferences: {', '.join(prefs[:3])}")

    if parts:
        summary = ". ".join(parts) + "."
        memory["summary"] = summary
        memory["summary_stale"] = False
        return summary

    return None


def clear_memory(client: Dict[str, Any]) -> None:
    """
    Clear client's conversation memory (for testing or GDPR requests).

    Preserves profile data, only clears conversation history and summary.
    """
    if "memory" in client:
        client["memory"] = {
            "conversation_history": [],
            "summary": None,
            "last_updated": datetime.utcnow().isoformat(),
            "message_count": 0,
        }


__all__ = [
    "is_enabled",
    "append_message",
    "get_memory_context",
    "format_memory_for_prompt",
    "update_profile",
    "generate_summary",
    "clear_memory",
    "CLIENT_MEMORY_ENABLED",
    "CLIENT_MEMORY_MAX_MESSAGES",
]
