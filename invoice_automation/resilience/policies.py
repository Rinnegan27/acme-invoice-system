"""Timeout, retry with jitter, circuit breaker, and bulkhead helpers."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open."""


@dataclass
class CircuitBreaker:
    """Simple closed → open → half-open circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    _failures: int = 0
    _opened_at: float | None = None
    _state: str = "closed"

    def before_call(self) -> None:
        if self._state == "open":
            assert self._opened_at is not None
            if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
                self._state = "half_open"
            else:
                raise CircuitOpenError("circuit breaker is open")

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold or self._state == "half_open":
            self._state = "open"
            self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        return self._state


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_s: float = 0.05,
    max_delay_s: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    no_retry_on: tuple[type[BaseException], ...] = (),
) -> T:
    """Execute ``fn`` with exponential backoff and full jitter.

    Parameters
    ----------
    fn : callable
        Zero-arg callable to execute.
    attempts : int
        Maximum attempts.
    base_delay_s : float
        Base backoff delay.
    max_delay_s : float
        Cap on backoff delay.
    retry_on : tuple
        Exception types that trigger retry.
    no_retry_on : tuple
        Exception types that must fail immediately (never retried).

    Returns
    -------
    T
        Function result.

    Raises
    ------
    BaseException
        Last exception if all attempts fail.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except no_retry_on:
            raise
        except retry_on as exc:  # type: ignore[misc]
            last = exc
            if attempt == attempts - 1:
                break
            sleep_for = min(max_delay_s, base_delay_s * (2**attempt))
            sleep_for = random.uniform(0, sleep_for)
            time.sleep(sleep_for)
    assert last is not None
    raise last
