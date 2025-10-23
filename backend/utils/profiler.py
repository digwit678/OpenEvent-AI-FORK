"""Minimal profiling decorator gated by the `OE_PERF` environment flag."""

from __future__ import annotations

import os
from functools import wraps
from time import perf_counter
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def _perf_enabled() -> bool:
    return os.environ.get("OE_PERF", "0") == "1"


def profile_step(name: str) -> Callable[[F], F]:
    """Decorate a function to emit a `[PERF]` timing when `OE_PERF=1`."""

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _perf_enabled():
                return fn(*args, **kwargs)
            start = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                duration_ms = (perf_counter() - start) * 1000.0
                print(f"[PERF] {name}: {duration_ms:.1f} ms")

        return cast(F, wrapper)

    return decorator


__all__ = ["profile_step"]
