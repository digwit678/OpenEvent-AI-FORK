"""Tests for workflows/llm/circuit_breaker.py — state machine, thresholds, cooldown."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from workflows.llm.circuit_breaker import CircuitBreaker, CircuitState


class TestStateTransitions:
    """Verify the three-state machine: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate cooldown elapsed by mocking time.monotonic
        with patch("workflows.llm.circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 2):
            assert cb.state == CircuitState.HALF_OPEN
            assert cb.allow_request() is True

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=1)
        cb.record_failure()
        cb.record_failure()

        with patch("workflows.llm.circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 2):
            assert cb.state == CircuitState.HALF_OPEN
            cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=1)
        cb.record_failure()
        cb.record_failure()

        with patch("workflows.llm.circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 2):
            assert cb.state == CircuitState.HALF_OPEN
            cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestAllowRequest:

    def test_closed_allows(self):
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60)
        assert cb.allow_request() is True

    def test_open_blocks(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        cb.record_failure()
        assert cb.allow_request() is False

    def test_half_open_allows_probe(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=1)
        cb.record_failure()
        with patch("workflows.llm.circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 2):
            assert cb.allow_request() is True


class TestReset:

    def test_reset_clears_all_state(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True
        assert cb._failure_count == 0

    def test_reset_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=1)
        cb.record_failure()
        with patch("workflows.llm.circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 2):
            assert cb.state == CircuitState.HALF_OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestSuccessResets:

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # Should be back to 0 failures — one more won't trip it
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED


class TestEnvVarDefaults:

    def test_default_threshold(self):
        with patch.dict("os.environ", {}, clear=False):
            cb = CircuitBreaker()
        assert cb._failure_threshold == 5

    def test_custom_threshold_from_env(self):
        with patch.dict("os.environ", {"LLM_CB_FAILURE_THRESHOLD": "10"}):
            cb = CircuitBreaker()
        assert cb._failure_threshold == 10

    def test_custom_cooldown_from_env(self):
        with patch.dict("os.environ", {"LLM_CB_COOLDOWN_SECONDS": "120"}):
            cb = CircuitBreaker()
        assert cb._cooldown_seconds == 120.0


class TestThreadSafety:

    def test_concurrent_failures(self):
        """Multiple threads recording failures should not corrupt state."""
        cb = CircuitBreaker(failure_threshold=100, cooldown_seconds=60)
        errors = []

        def record_n_failures(n):
            try:
                for _ in range(n):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_n_failures, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 4 threads × 50 failures = 200, which exceeds threshold of 100
        assert cb.state == CircuitState.OPEN
        assert cb._failure_count == 200

    def test_concurrent_success_and_failure(self):
        """Mixed success/failure from different threads should not deadlock."""
        cb = CircuitBreaker(failure_threshold=1000, cooldown_seconds=60)
        errors = []

        def do_work(success: bool, n: int):
            try:
                for _ in range(n):
                    if success:
                        cb.record_success()
                    else:
                        cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=do_work, args=(True, 100)),
            threading.Thread(target=do_work, args=(False, 100)),
            threading.Thread(target=do_work, args=(True, 100)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # State should be valid (no crash, no deadlock)
        assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN)
