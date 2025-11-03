from __future__ import annotations

import os
from typing import Optional

from .providers.base import LLMProvider
from .providers.openai_provider import OpenAIProvider

_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Return the configured provider (defaults to OpenAI)."""

    global _provider
    if _provider is not None:
        return _provider
    name = os.getenv("PROVIDER", "openai").lower()
    if name == "openai":
        _provider = OpenAIProvider()
    else:
        # Fallback to OpenAI until additional providers are introduced.
        _provider = OpenAIProvider()
    return _provider


def reset_provider_for_tests() -> None:
    """Reset the cached provider (intended for tests)."""

    global _provider
    _provider = None
