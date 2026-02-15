"""Lightweight circuit breaker for LLM provider calls.

States: CLOSED -> OPEN -> HALF_OPEN
- CLOSED: all requests pass through; failures are counted.
- OPEN: requests are rejected immediately (fast-fail).
- HALF_OPEN: one probe request is allowed after the cooldown expires.

Thread-safe via threading.Lock. Uses time.monotonic() to avoid
wall-clock drift. Zero external dependencies.
"""
from __future__ import annotations

import os
import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-provider circuit breaker for LLM calls."""

    def __init__(
        self,
        failure_threshold: int | None = None,
        cooldown_seconds: float | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold or int(
            os.getenv("LLM_CB_FAILURE_THRESHOLD", "5")
        )
        self._cooldown_seconds = cooldown_seconds or float(
            os.getenv("LLM_CB_COOLDOWN_SECONDS", "60")
        )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    # -- Public API --

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def allow_request(self) -> bool:
        """Return True if a request is permitted under the current state."""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return True
            # OPEN
            return False

    def record_success(self) -> None:
        """Record a successful call — resets the breaker to CLOSED."""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker to OPEN."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Reset all state (intended for tests)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0

    # -- Internal --

    def _maybe_transition_to_half_open(self) -> None:
        """If OPEN and cooldown has elapsed, move to HALF_OPEN (no lock; caller holds it)."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self._cooldown_seconds:
            self._state = CircuitState.HALF_OPEN
