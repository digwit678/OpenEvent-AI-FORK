from __future__ import annotations

import os


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean-like environment flag without overriding OS-provided values."""

    value = os.getenv(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "on"}
