"""
MODULE: backend/llm/client.py
PURPOSE: Centralized OpenAI client singleton with timeout and retry configuration.

All LLM operations should use this module instead of directly instantiating OpenAI.
This ensures:
1. Consistent timeout settings (no hung requests)
2. Automatic retry with exponential backoff
3. Single point for API key configuration
4. Easier testing and mocking

USAGE:
    from llm.client import get_openai_client, is_llm_available

    if is_llm_available():
        client = get_openai_client()
        response = client.chat.completions.create(...)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration (can be overridden via environment)
DEFAULT_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "30"))
DEFAULT_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))

# Singleton client instance
_client: Optional["OpenAI"] = None  # type: ignore


def is_llm_available() -> bool:
    """Check if LLM is available (API key set and not in stub mode)."""
    if os.getenv("AGENT_MODE", "").lower() == "stub":
        return False
    api_key = os.getenv("OPENAI_API_KEY", "")
    return bool(api_key and api_key.strip())


def get_openai_client() -> "OpenAI":  # type: ignore
    """
    Get the shared OpenAI client singleton.

    The client is configured with:
    - timeout: 30s default (configurable via OPENAI_TIMEOUT)
    - max_retries: 3 default (configurable via OPENAI_MAX_RETRIES)

    Returns:
        OpenAI client instance

    Raises:
        RuntimeError: If OpenAI SDK is not installed
        ValueError: If OPENAI_API_KEY is not set

    Example:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
        )
    """
    global _client

    if _client is not None:
        return _client

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI SDK not installed. Run: pip install openai"
        ) from exc

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable not set. "
            "Set it or use AGENT_MODE=stub for testing."
        )

    _client = OpenAI(
        api_key=api_key,
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )
    logger.debug("OpenAI client initialized (timeout=%s, retries=%s)",
                 DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES)

    return _client


def reset_client() -> None:
    """Reset the client singleton (for testing)."""
    global _client
    _client = None


# Convenience wrappers for common operations

def chat_completion(
    messages: list,
    *,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1000,
    json_mode: bool = False,
) -> str:
    """
    Convenience wrapper for chat completions.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model to use (defaults to OPENAI_MODEL or gpt-4o-mini)
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        json_mode: Whether to request JSON output

    Returns:
        Response text content

    Example:
        text = chat_completion([
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ])
    """
    client = get_openai_client()
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


__all__ = [
    "get_openai_client",
    "is_llm_available",
    "reset_client",
    "chat_completion",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
]
