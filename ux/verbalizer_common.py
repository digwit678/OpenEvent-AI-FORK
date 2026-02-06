"""Shared verbalizer utilities — single source of truth for tone + LLM calling."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


def resolve_verbalizer_tone() -> str:
    """Determine verbalization tone from environment.

    Default is 'empathetic' for human-like UX.
    Set VERBALIZER_TONE=plain to disable LLM verbalization.
    """
    tone_env = os.getenv("VERBALIZER_TONE")
    if tone_env:
        candidate = tone_env.strip().lower()
        if candidate in {"empathetic", "plain"}:
            return candidate
    # Check for explicit disable flag
    plain_flag = os.getenv("PLAIN_VERBALIZER", "")
    if plain_flag.strip().lower() in {"1", "true", "yes", "on"}:
        return "plain"
    # Default to empathetic for human-like UX
    return "empathetic"


def call_verbalizer_llm(payload: Dict[str, Any], *, temperature: float = 0.3) -> str:
    """Call LLM for verbalization using the adapter pattern.

    Uses the configured verbalization provider (hybrid mode support).
    Respects OPENAI_TEST_MODE=1 for deterministic test output (temperature → 0.0).

    Args:
        payload: Dict with 'system' and 'user' keys for the LLM prompt.
        temperature: Sampling temperature (default 0.3). Callers may override
                     (e.g. verbalizer_agent uses 0.2 for tighter output).

    Returns:
        LLM-generated text (stripped).
    """
    from adapters.agent_adapter import get_adapter_for_provider
    from llm.provider_config import get_verbalization_provider

    # Deterministic mode for tests
    if os.getenv("OPENAI_TEST_MODE") == "1":
        temperature = 0.0

    provider = get_verbalization_provider()
    adapter = get_adapter_for_provider(provider)

    return adapter.complete(
        prompt=payload["user"],
        system_prompt=payload["system"],
        temperature=temperature,
        json_mode=False,
    )
