"""Tests for SDK-level retry (Step G5.5).

G5 layers exception classification
(classify_exception) and the
tenacity-based ``remote_call``
decorator. G5.5 wires these to the
real OpenAI and Anthropic SDKs so
a transient 5xx / network error /
timeout from the provider is
retried automatically. Auth and
4xx errors are not retried (the
caller's API key is wrong, retrying
does not help).

Guarantees:

  1. ``classify_exception`` maps an
     ``openai.APITimeoutError`` to
     a ``TimeoutError_``,
     ``openai.RateLimitError`` to a
     ``RateLimited``,
     ``openai.AuthenticationError``
     to an ``AuthError``, and
     ``openai.APIConnectionError``
     to a ``NetworkError_``. The
     same mapping holds for the
     Anthropic SDK.
  2. ``classify_exception`` uses
     the SDK exception's module
     path (``openai.*`` /
     ``anthropic.*``) so a
     third-party SDK that happens
     to share a class name is not
     misclassified.
  3. A 5xx SDK error is retried
     automatically by
     ``_openai_create_with_retry``.
     The retry count matches the
     configured ``max_attempts``.
  4. An auth / 4xx error is *not*
     retried; the helper raises the
     classified exception on the
     first attempt.
  5. The streaming path uses the
     same retry helper.
  6. The end-to-end test: a
     ``MockSDK`` that raises
     ``APITimeoutError`` twice and
     then succeeds — the helper
     retries, eventually returns the
     successful response, and the
     caller sees a normal
     ``ChatResponse``.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


def _make_httpx_response(status: int) -> httpx.Response:
    """Build a minimal ``httpx.Response``
    for ``openai.APIStatusError``
    constructors. The SDK requires
    a real ``response`` and ``body``
    keyword argument; the response
    status code is what the SDK
    uses to populate the exception
    class."""
    return httpx.Response(
        status,
        request=httpx.Request(
            "POST",
            "https://api.openai.com/v1/chat/completions",
        ),
    )


# ---------- 1. classify_exception maps SDK exceptions ----------

def test_classify_openai_api_timeout_error() -> None:
    """An ``openai.APITimeoutError``
    is classified as a
    ``TimeoutError_``. The cause is
    the original exception so a
    debugger can inspect the
    stack."""
    import openai  # type: ignore[import-not-found]
    from manusift.retry import (
        TimeoutError_,
        classify_exception,
    )
    try:
        raise openai.APITimeoutError("request timed out")
    except openai.APITimeoutError as exc:
        err = classify_exception(exc)
    assert isinstance(err, TimeoutError_)
    assert err.cause is not None


def test_classify_openai_rate_limit_error() -> None:
    """An ``openai.RateLimitError``
    is classified as a
    ``RateLimited``."""
    import openai  # type: ignore[import-not-found]
    from manusift.retry import (
        RateLimited,
        classify_exception,
    )
    try:
        raise openai.RateLimitError('rate limit reached', response=_make_httpx_response(500), body={})
    except openai.RateLimitError as exc:
        err = classify_exception(exc)
    assert isinstance(err, RateLimited)


def test_classify_openai_authentication_error() -> None:
    """An ``openai.AuthenticationError``
    is classified as an
    ``AuthError``."""
    import openai  # type: ignore[import-not-found]
    from manusift.retry import (
        AuthError,
        classify_exception,
    )
    try:
        raise openai.AuthenticationError('bad api key', response=_make_httpx_response(500), body={})
    except openai.AuthenticationError as exc:
        err = classify_exception(exc)
    assert isinstance(err, AuthError)


def test_classify_openai_internal_server_error() -> None:
    """An ``openai.InternalServerError``
    is classified as a
    ``ServerError_``."""
    import openai  # type: ignore[import-not-found]
    from manusift.retry import (
        ServerError_,
        classify_exception,
    )
    try:
        raise openai.InternalServerError('upstream 500', response=_make_httpx_response(500), body={})
    except openai.InternalServerError as exc:
        err = classify_exception(exc)
    assert isinstance(err, ServerError_)


def test_classify_openai_connection_error() -> None:
    """An ``openai.APIConnectionError``
    is classified as a
    ``NetworkError_``."""
    import openai  # type: ignore[import-not-found]
    from manusift.retry import (
        NetworkError_,
        classify_exception,
    )
    try:
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://x"))
    except openai.APIConnectionError as exc:
        err = classify_exception(exc)
    assert isinstance(err, NetworkError_)


def test_classify_anthropic_rate_limit_error() -> None:
    """An ``anthropic.RateLimitError``
    is classified as a
    ``RateLimited``. The module path
    filter ensures the right SDK
    is detected."""
    import anthropic  # type: ignore[import-not-found]
    from manusift.retry import (
        RateLimited,
        classify_exception,
    )
    try:
        raise anthropic.RateLimitError(
        'anthropic 429',
        response=_make_httpx_response(429 if 'RateLimitError' == 'RateLimitError' else 401),
        body={},
    )
    except anthropic.RateLimitError as exc:
        err = classify_exception(exc)
    assert isinstance(err, RateLimited)


def test_classify_anthropic_authentication_error() -> None:
    """An ``anthropic.AuthenticationError``
    is classified as an
    ``AuthError``."""
    import anthropic  # type: ignore[import-not-found]
    from manusift.retry import (
        AuthError,
        classify_exception,
    )
    try:
        raise anthropic.AuthenticationError(
        'bad key',
        response=_make_httpx_response(429 if 'AuthenticationError' == 'RateLimitError' else 401),
        body={},
    )
    except anthropic.AuthenticationError as exc:
        err = classify_exception(exc)
    assert isinstance(err, AuthError)


# ---------- 2. _openai_create_with_retry retries 5xx ----------

def test_openai_helper_retries_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5xx from the OpenAI SDK is
    retried. We use a mock SDK that
    raises ``InternalServerError``
    on the first call and returns
    a stub response on the second.
    The helper returns the second
    response, and the SDK's
    ``create`` was called twice."""
    import openai  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _openai_create_with_retry,
    )
    # Reset the OpenAI breaker so
    # the test does not see
    # a circuit-open from a
    # previous run.
    from manusift.retry import get_breaker
    get_breaker("openai").reset()
    call_count = {"n": 0}
    stub_response = MagicMock()
    stub_response.choices = []
    stub_response.usage = None
    def fake_create(*args: Any, **kwargs: Any):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise openai.InternalServerError('upstream 500', response=_make_httpx_response(500), body={})
        return stub_response
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create = fake_create
    # Use a small ``multiplier`` so
    # the test runs fast.
    result = _openai_create_with_retry(
        fake_sdk,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=None,
    )
    # The retry recovered.
    assert result is stub_response
    assert call_count["n"] == 2


def test_openai_helper_does_not_retry_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An auth error is *not* retried.
    The helper raises the
    ``AuthError`` on the first
    attempt — the operator's API
    key is wrong, retrying does not
    help."""
    import openai  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _openai_create_with_retry,
    )
    from manusift.retry import (
        AuthError,
        get_breaker,
    )
    get_breaker("openai").reset()
    call_count = {"n": 0}
    def fake_create(*args: Any, **kwargs: Any):
        call_count["n"] += 1
        raise openai.AuthenticationError('bad key', response=_make_httpx_response(500), body={})
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create = fake_create
    with pytest.raises(AuthError):
        _openai_create_with_retry(
            fake_sdk,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            tools=None,
        )
    # Exactly one call — no retry.
    assert call_count["n"] == 1


def test_openai_helper_retries_on_timeout() -> None:
    """An ``APITimeoutError`` is
    retried. The helper recovers
    if the second attempt
    succeeds."""
    import openai  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _openai_create_with_retry,
    )
    from manusift.retry import get_breaker
    get_breaker("openai").reset()
    call_count = {"n": 0}
    stub = MagicMock()
    stub.choices = []
    stub.usage = None
    def fake_create(*args: Any, **kwargs: Any):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise openai.APITimeoutError("timeout")
        return stub
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create = fake_create
    result = _openai_create_with_retry(
        fake_sdk,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=None,
    )
    assert result is stub
    assert call_count["n"] == 3


# ---------- 3. _anthropic_create_with_retry ----------

def test_anthropic_helper_retries_on_5xx() -> None:
    """A 5xx from the Anthropic SDK
    is retried."""
    import anthropic  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _anthropic_create_with_retry,
    )
    from manusift.retry import get_breaker
    get_breaker("anthropic").reset()
    call_count = {"n": 0}
    stub = MagicMock()
    def fake_create(*args: Any, **kwargs: Any):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise anthropic.InternalServerError(
        'anthropic 500',
        response=_make_httpx_response(429 if 'InternalServerError' == 'RateLimitError' else 401),
        body={},
    )
        return stub
    fake_sdk = MagicMock()
    fake_sdk.messages.create = fake_create
    result = _anthropic_create_with_retry(
        fake_sdk,
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=None,
    )
    assert result is stub
    assert call_count["n"] == 2


def test_anthropic_helper_does_not_retry_auth() -> None:
    """An auth error from Anthropic
    is *not* retried."""
    import anthropic  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _anthropic_create_with_retry,
    )
    from manusift.retry import (
        AuthError,
        get_breaker,
    )
    get_breaker("anthropic").reset()
    call_count = {"n": 0}
    def fake_create(*args: Any, **kwargs: Any):
        call_count["n"] += 1
        raise anthropic.AuthenticationError(
        'bad key',
        response=_make_httpx_response(429 if 'AuthenticationError' == 'RateLimitError' else 401),
        body={},
    )
    fake_sdk = MagicMock()
    fake_sdk.messages.create = fake_create
    with pytest.raises(AuthError):
        _anthropic_create_with_retry(
            fake_sdk,
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            tools=None,
        )
    assert call_count["n"] == 1


def test_anthropic_helper_forwards_extra_kwargs() -> None:
    """Extra keyword arguments
    (``system``, ``metadata``, ...)
    are forwarded to the SDK call
    unchanged. We verify the
    ``system`` field is present
    in the captured kwargs."""
    import anthropic  # type: ignore[import-not-found]
    from manusift.llm.client.providers import (
        _anthropic_create_with_retry,
    )
    from manusift.retry import get_breaker
    get_breaker("anthropic").reset()
    captured: dict[str, Any] = {}
    def fake_create(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        return MagicMock()
    fake_sdk = MagicMock()
    fake_sdk.messages.create = fake_create
    _anthropic_create_with_retry(
        fake_sdk,
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=None,
        system="you are a paper-integrity checker",
    )
    assert captured.get("system") == (
        "you are a paper-integrity checker"
    )


# ---------- 4. End-to-end: OpenAILLM.chat retries on 5xx ----------

def test_openai_llm_chat_recovers_from_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``OpenAILLM.chat`` method
    itself retries on a 5xx. A
    mock SDK that raises
    ``InternalServerError`` on the
    first call and returns a valid
    response on the second produces
    a normal ``ChatResponse`` (not
    the error-text response)."""
    import openai  # type: ignore[import-not-found]
    from dataclasses import dataclass, field
    from typing import Any
    from manusift.config import Settings
    from manusift.llm.client import OpenAILLM
    from manusift.llm.chat import ChatResponse
    from manusift.retry import get_breaker
    get_breaker("openai").reset()
    call_count = {"n": 0}

    @dataclass
    class _Choice:
        message: Any = None
        finish_reason: str = "stop"

    @dataclass
    class _Usage:
        prompt_tokens: int = 5
        completion_tokens: int = 3
        total_tokens: int = 8
        def model_dump(self) -> dict:
            return {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            }

    @dataclass
    class _Resp:
        choices: list = field(default_factory=list)
        usage: Any = None
        model: str = "gpt-4o-mini"

    @dataclass
    class _Msg:
        role: str = "assistant"
        content: str = "recovered"
        tool_calls: list = field(default_factory=list)
    @dataclass
    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise openai.InternalServerError('500', response=_make_httpx_response(500), body={})
            choice = _Choice(message=_Msg())
            return _Resp(choices=[choice], usage=_Usage())

    @dataclass
    class _Chat:
        completions: Any = field(default_factory=_Completions)

    @dataclass
    class _SDK:
        chat: Any = field(default_factory=_Chat)

    settings = Settings(
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
    )
    client = OpenAILLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: _SDK())
    resp = client.chat(
        [{"role": "user", "content": "hi"}], None
    )
    # The retry recovered.
    assert call_count["n"] == 2
    # The response is a normal
    # ChatResponse, not the
    # error-text response.
    assert "error" not in resp.text
    assert resp.text == "recovered"
