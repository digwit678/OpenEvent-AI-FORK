"""Email threading module - Pre-workflow thread resolution.

This module provides two-layer email thread resolution:
1. Layer 1 (Reply Detection): Deterministic linking using email headers (no LLM)
2. Layer 2 (Thread Resolver): LLM-based semantic matching for new emails

The resolver runs BEFORE workflow processing to route messages to the correct event.
"""
from .models import EmailMessage, EventSignature, ThreadMapping, ResolutionResult
from .reply_detector import is_reply, link_reply_to_thread, store_email_message, create_thread_mapping
from .resolver import ThreadResolver

__all__ = [
    # Models
    "EmailMessage",
    "EventSignature",
    "ThreadMapping",
    "ResolutionResult",
    # Layer 1: Reply detection (no LLM)
    "is_reply",
    "link_reply_to_thread",
    "store_email_message",
    "create_thread_mapping",
    # Layer 2: Thread resolver (LLM)
    "ThreadResolver",
]
