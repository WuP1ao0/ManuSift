"""Tests for the HTTP retry + circuit-breaker
module (G1).

G1 layers three reliability patterns
(``RemoteServiceError`` classification,
tenacity-based exponential backoff retry,
and a per-host circuit breaker) on top of
the existing external call sites. The
behaviors we guarantee:

  1. ``classify_status`` maps an HTTP
     status code to the correct
     ``RemoteServiceError`` subclass
     (5xx → ``ServerError_``; 429 →
     ``RateLimited``; 401/403 →
     ``AuthError``; other 4xx →
     ``BadRequest``).
  2. ``classify_exception`` converts an
     ``httpx`` exception to a
     ``RemoteServiceError`` with the
     original preserved on ``.cause``.
  3. ``remote_call`` retries on
     ``ServerError_`` /
     ``NetworkError_`` /
     ``TimeoutError_`` and ``RateLimited``
     up to ``max_attempts`` times.
  4. ``remote_call`` does NOT retry on
     ``AuthError`` / ``BadRequest`` —
     they are non-transient.
  5. After exhausting retries, the
     *original* ``RemoteServiceError`` is
     re-raised (not a ``tenacity.RetryError``)
     so callers see a meaningful exception.
  6. The circuit breaker opens after
     ``failure_threshold`` consecutive
     failures and short-circuits further
     calls until the cool-down elapses.
  7. A successful call resets the breaker.
  8. The breaker is per-name, so an
     outage at one provider does not
     affect another.
  9. ``reset_all_breakers`` is a test
     hook; production code should not
     call it.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from manusift.retry import (
    AuthError,
    BadRequest,
    CircuitBreaker,
    CircuitBreakerOpenError,
    NetworkError_,
    RateLimited,
    RemoteServiceError,
    ServerError_,
    TimeoutError_,
    classify_exception,
    classify_status,
    get_breaker,
    remote_call,
    reset_all_breakers,
)


@pytest.fixture(autouse=True)
def _reset_breakers() -> None:
    """Reset the global breaker registry
    before and after each test so a
    failure in one test does not leak
    into the next."""
    reset_all_breakers()
    yield
    reset_all_breakers()


# ---------- 1. classify_status mapping ----------

def test_classify_status_5xx_is_server_error() -> None:
    """5xx → ``ServerError_`` (retried)."""
    assert classify_status(500) is ServerError_
    assert classify_status(502) is ServerError_
    assert classify_status(503) is ServerError_


def test_classify_status_429_is_rate_limited() -> None:
    """429 → ``RateLimited`` (retried with
    a longer backoff)."""
    assert classify_status(429) is RateLimited


def test_classify_status_401_403_is_auth_error() -> None:
    """401 / 403 → ``AuthError`` (NOT
    retried; the operator must fix the
    API key)."""
    assert classify_status(401) is AuthError
    assert classify_status(403) is AuthError


def test_classify_status_4xx_other_is_bad_request() -> None:
    """Other 4xx (e.g. 400, 404, 422) →
    ``BadRequest`` (NOT retried; the
    request is malformed)."""
    assert classify_status(400) is BadRequest
    assert classify_status(404) is BadRequest
    assert classify_status(422) is BadRequest


def test_classify_status_other_is_base_error() -> None:
    """Anything outside the standard 4xx
    / 5xx range (e.g. 1xx, 3xx) maps to
    the base ``RemoteServiceError``.
    These should not be happening in
    practice but the mapper is defensive."""
    assert classify_status(100) is RemoteServiceError
    assert classify_status(301) is RemoteServiceError


# ---------- 2. classify_exception mapping ----------

def test_classify_httpx_timeout() -> None:
    """An ``httpx.TimeoutException``
    becomes a ``TimeoutError_`` with the
    original on ``.cause``."""
    inner = httpx.TimeoutException("boom")
    err = classify_exception(inner)
    assert isinstance(err, TimeoutError_)
    assert err.cause is inner


def test_classify_httpx_network() -> None:
    """An ``httpx.ConnectError`` /
    ``httpx.NetworkError`` becomes a
    ``NetworkError_``."""
    inner = httpx.ConnectError("no route")
    err = classify_exception(inner)
    assert isinstance(err, NetworkError_)


def test_classify_httpx_status_error() -> None:
    """An ``httpx.HTTPStatusError`` is
    classified by its ``.response.status_code``."""
    response = httpx.Response(503, request=httpx.Request("GET", "https://x"))
    inner = httpx.HTTPStatusError(
        "boom", request=response.request, response=response
    )
    err = classify_exception(inner)
    assert isinstance(err, ServerError_)


# ---------- 3. remote_call retries ----------

def test_remote_call_retries_server_error() -> None:
    """A function that raises ``ServerError_``
    twice then succeeds is invoked 3 times
    (1 initial + 2 retries)."""
    calls: list[int] = []

    @remote_call("test-retry", max_attempts=3, multiplier=0.01)
    def flaky() -> str:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise ServerError_("boom")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3


def test_remote_call_does_not_retry_auth_error() -> None:
    """``AuthError`` is non-transient; the
    function is invoked exactly once."""
    calls: list[int] = []

    @remote_call("test-auth", max_attempts=3, multiplier=0.01)
    def bad() -> str:
        calls.append(1)
        raise AuthError("401")

    with pytest.raises(AuthError):
        bad()
    assert len(calls) == 1


def test_remote_call_exhausts_then_raises_original() -> None:
    """When all attempts fail, the LAST
    ``RemoteServiceError`` is re-raised
    — not a ``tenacity.RetryError``.
    Callers see the original exception
    type and can inspect ``.cause``."""
    calls: list[int] = []

    @remote_call(
        "test-exhaust", max_attempts=3, multiplier=0.01
    )
    def always_fails() -> str:
        calls.append(1)
        raise ServerError_(
            "remote down", cause=RuntimeError("upstream")
        )

    with pytest.raises(ServerError_) as exc_info:
        always_fails()
    # 3 attempts.
    assert len(calls) == 3
    # The original cause is preserved.
    assert isinstance(exc_info.value.cause, RuntimeError)


# ---------- 4. remote_call does NOT retry on BadRequest ----------

def test_remote_call_does_not_retry_bad_request() -> None:
    """``BadRequest`` is non-transient."""
    calls: list[int] = []

    @remote_call("test-bad", max_attempts=3, multiplier=0.01)
    def bad() -> str:
        calls.append(1)
        raise BadRequest("400")

    with pytest.raises(BadRequest):
        bad()
    assert len(calls) == 1


# ---------- 5. Circuit breaker behavior ----------

def test_circuit_breaker_opens_after_threshold() -> None:
    """The breaker opens after
    ``failure_threshold`` consecutive
    failures. Subsequent calls fail
    fast with ``CircuitBreakerOpenError``
    without invoking the wrapped
    function."""
    breaker = CircuitBreaker(
        name="x", failure_threshold=3, cool_down_seconds=0.05
    )
    calls: list[int] = []

    def always_fails() -> str:
        calls.append(1)
        raise ServerError_("boom")

    # 3 failures trip the breaker.
    for _ in range(3):
        with pytest.raises(ServerError_):
            breaker.call(always_fails)
    assert len(calls) == 3
    # 4th call short-circuits.
    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(always_fails)
    # The wrapped function was NOT called
    # for the 4th attempt.
    assert len(calls) == 3


def test_circuit_breaker_closes_after_cooldown_and_success() -> None:
    """After the cool-down elapses, the
    next call is allowed through
    (half-open). If it succeeds, the
    breaker closes; if it fails, the
    breaker re-opens."""
    now = 1.0
    breaker = CircuitBreaker(
        name="x",
        failure_threshold=2,
        cool_down_seconds=0.02,
        clock=lambda: now,
    )

    # Trip the breaker.
    for _ in range(2):
        with pytest.raises(ServerError_):
            breaker.call(
                lambda: (_ for _ in ()).throw(
                    ServerError_("boom")
                )
            )
    # Cool-down.
    now += 0.03
    # Half-open probe: a successful call
    # closes the breaker.
    breaker.call(lambda: "ok")
    # Now further calls succeed without
    # the breaker raising.
    assert breaker.call(lambda: "ok") == "ok"


def test_circuit_breaker_reopens_on_probe_failure() -> None:
    """A half-open probe that fails
    re-opens the breaker, so a brief
    recovery followed by a regression
    is correctly detected."""
    now = 1.0
    breaker = CircuitBreaker(
        name="x",
        failure_threshold=2,
        cool_down_seconds=0.02,
        clock=lambda: now,
    )
    for _ in range(2):
        with pytest.raises(ServerError_):
            breaker.call(
                lambda: (_ for _ in ()).throw(
                    ServerError_("boom")
                )
            )
    now += 0.03
    # Half-open probe fails.
    with pytest.raises(ServerError_):
        breaker.call(
            lambda: (_ for _ in ()).throw(ServerError_("x"))
        )
    # Breaker is back to open. Fast-fail.
    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(lambda: "ok")


def test_circuit_breaker_per_name() -> None:
    """Two breakers with different names
    are independent. An outage at one
    provider does not trip the other."""
    a = get_breaker("provider-a")
    b = get_breaker("provider-b")
    # Trip provider-a.
    for _ in range(5):
        try:
            a.call(
                lambda: (_ for _ in ()).throw(
                    ServerError_("x")
                )
            )
        except ServerError_:
            pass
    # provider-b is still closed.
    assert b.call(lambda: "ok") == "ok"


# ---------- 6. get_breaker is idempotent ----------

def test_get_breaker_returns_same_instance() -> None:
    """``get_breaker("foo")`` returns the
    same breaker on every call (so a
    remote call and a subsequent
    retry use the same failure counter)."""
    a = get_breaker("foo")
    b = get_breaker("foo")
    assert a is b


# ---------- 7. reset_all_breakers test hook ----------

def test_reset_all_breakers_clears_state() -> None:
    """``reset_all_breakers`` returns every
    breaker to a fully-closed state."""
    a = get_breaker("provider-a")
    # Trip the breaker.
    for _ in range(5):
        try:
            a.call(
                lambda: (_ for _ in ()).throw(
                    ServerError_("x")
                )
            )
        except ServerError_:
            pass
    with pytest.raises(CircuitBreakerOpenError):
        a.call(lambda: "ok")
    # Reset.
    reset_all_breakers()
    # Now the call succeeds.
    assert a.call(lambda: "ok") == "ok"
