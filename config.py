"""Backend configuration helpers and profile selection utilities.

Tests can call `reset_llm_profile_cache()` to force reloading profile
fixtures after mutating `configs/llm_profiles.json`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from utils import json_io

_DEFAULT_PROFILE = "v1-current"


def _profiles_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs" / "llm_profiles.json"


@lru_cache(maxsize=1)
def _load_profiles() -> Dict[str, Dict[str, Any]]:
    path = _profiles_path()
    with path.open("r", encoding="utf-8") as handle:
        payload = json_io.load(handle)
    return {str(name): dict(settings) for name, settings in (payload or {}).items()}


def get_llm_profile(name: str | None = None) -> Dict[str, Any]:
    """Return the profile configuration for the requested identifier."""

    profiles = _load_profiles()
    selected = name or os.environ.get("OE_LLM_PROFILE") or _DEFAULT_PROFILE
    profile = profiles.get(selected) or profiles.get(_DEFAULT_PROFILE, {})
    return dict(profile)


def available_llm_profiles() -> Dict[str, Dict[str, Any]]:
    """Expose all available profiles without breaking the cache."""

    profiles = _load_profiles()
    return {key: dict(value) for key, value in profiles.items()}


def reset_llm_profile_cache() -> None:
    """Clear the memoized profile payload (handy for tests)."""

    _load_profiles.cache_clear()


__all__ = ["get_llm_profile", "available_llm_profiles", "reset_llm_profile_cache"]
