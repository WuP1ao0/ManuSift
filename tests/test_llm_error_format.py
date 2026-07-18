"""Tests for the LLM error formatter (R-audit 2026-06-10).

Before this audit, when
the upstream LLM provider
returned a 500 / 502 /
429 / 401, the user saw
the raw Python exception
in the chat log:

    error: Error code: 500
    - {'type': 'error',
    'error': {'type':
    'api_error', 'message':
    'unknown error, 999
    (1000)'}, 'request_id':
    '0679f641...'}

with no hint about
whether the error was
transient, no friendly
summary, and no
distinction between
"upstream is down,
retry" and "your API
key is wrong, fix
config".

The new
``_format_llm_error``
helper extracts the
structured fields from
the SDK exception and
returns a short, operator-
friendly one-liner.
"""
from __future__ import annotations

import os
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[1]))


# ---------- 1. Anthropic SDK 5xx ----------


def test_format_anthropic_5xx_with_request_id() -> None:
    """The user's exact
    case: 500 with
    ``'unknown error, 999
    (1000)'`` from MiniMax
    upstream. The
    formatted output must
    include the request_id
    and a "press Ctrl+R to
    retry" hint."""
    import httpx
    import anthropic

    # Build
    # a
    # fake
    # ``APIStatusError``
    # matching
    # the
    # user's
    # case.
    request = httpx.Request(
        "POST", "https://api.minimaxi.com/anthropic/v1/messages"
    )
    response = httpx.Response(
        500,
        request=request,
        headers={
            "request-id": "0679f641b1adab730c8c29c2963520e2",
            "content-type": "application/json",
        },
        json={
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "unknown error, 999 (1000)",
            },
        },
    )
    exc = anthropic.APIStatusError(
        "Error code: 500 - ...",
        response=response,
        body=response.json(),
    )
    from manusift.llm.client import _format_llm_error

    msg = _format_llm_error(exc)
    # The
    # raw
    # exception
    # text
    # is
    # NOT
    # echoed.
    assert "Error code: 500" not in msg
    # The
    # raw
    # Python
    # repr
    # is
    # NOT
    # echoed.
    assert "{'type':" not in msg
    # The
    # request_id
    # is
    # preserved.
    assert "0679f641b1adab730c8c29c2963520e2" in msg
    # The
    # error
    # type
    # is
    # included
    # for
    # the
    # log.
    assert "api_error" in msg
    # The
    # status
    # code
    # is
    # included.
    assert "500" in msg
    # The
    # user
    # gets
    # a
    # hint
    # to
    # retry.
    assert "transient" in msg.lower() or "retry" in msg.lower()


def test_format_anthropic_401_gives_api_key_hint() -> None:
    """A 401 from the
    upstream suggests the
    API key is wrong. The
    hint must point the
    user at the env var."""
    import httpx
    import anthropic

    request = httpx.Request("POST", "https://api.example.com/v1/messages")
    response = httpx.Response(
        401,
        request=request,
        headers={"request-id": "rid-401"},
        json={"type": "error", "error": {"type": "authentication_error"}},
    )
    exc = anthropic.APIStatusError(
        "Unauthorized", response=response, body=response.json()
    )
    from manusift.llm.client import _format_llm_error

    msg = _format_llm_error(exc)
    assert "401" in msg
    assert "MANUSIFT_ANTHROPIC_API_KEY" in msg
    # No
    # "transient
    # /
    # retry"
    # hint
    # --
    # the
    # user
    # must
    # fix
    # config.
    assert "retry" not in msg.lower() or "press" not in msg.lower()


def test_format_anthropic_429_is_rate_limited() -> None:
    """A 429 must be
    classified as
    transient -- the user
    should retry."""
    import httpx
    import anthropic

    request = httpx.Request("POST", "https://api.example.com/v1/messages")
    response = httpx.Response(
        429,
        request=request,
        headers={"request-id": "rid-429"},
        json={"type": "error", "error": {"type": "rate_limit_error"}},
    )
    exc = anthropic.APIStatusError(
        "Too Many Requests", response=response, body=response.json()
    )
    from manusift.llm.client import _format_llm_error

    msg = _format_llm_error(exc)
    assert "429" in msg
    assert (
        "transient" in msg.lower()
        or "retry" in msg.lower()
    )


# ---------- 2. Anthropic SDK 4xx (bad request) ----------


def test_format_anthropic_400_is_bad_request() -> None:
    """A 400 is *not*
    transient -- the user
    must fix the request
    (e.g. bad system
    prompt, bad tool
    schema). The hint
    must NOT be
    "transient / retry"."""
    import httpx
    import anthropic

    request = httpx.Request("POST", "https://api.example.com/v1/messages")
    response = httpx.Response(
        400,
        request=request,
        headers={"request-id": "rid-400"},
        json={"type": "error", "error": {"type": "invalid_request_error"}},
    )
    exc = anthropic.APIStatusError(
        "Bad Request", response=response, body=response.json()
    )
    from manusift.llm.client import _format_llm_error

    msg = _format_llm_error(exc)
    assert "400" in msg
    # "fix
    # the
    # request"
    # hint
    # is
    # present.
    assert (
        "request" in msg.lower()
        and "rejected" in msg.lower()
    )


# ---------- 3. OpenAI SDK 5xx ----------


def test_format_openai_5xx() -> None:
    """An OpenAI SDK
    ``APIStatusError``
    (5xx) is formatted
    with the same
    template."""
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        503,
        request=request,
        headers={"x-request-id": "xrid-503"},
        json={
            "error": {
                "message": "Service Unavailable",
                "type": "server_error",
            }
        },
    )
    exc = openai.APIStatusError(
        "Service Unavailable", response=response, body=response.json()
    )
    from manusift.llm.client import _format_llm_error

    msg = _format_llm_error(exc)
    assert "503" in msg
    assert "xrid-503" in msg
    assert (
        "transient" in msg.lower()
        or "retry" in msg.lower()
    )


# ---------- 4. Network / timeout fallthrough ----------


def test_format_httpx_timeout() -> None:
    """A plain
    ``httpx.TimeoutException``
    is formatted as a
    timeout with a
    connection hint."""
    import httpx
    from manusift.llm.client import _format_llm_error

    exc = httpx.ReadTimeout("the server hung up")
    msg = _format_llm_error(exc)
    assert "timeout" in msg.lower()
    assert "retry" in msg.lower() or "connection" in msg.lower()


def test_format_httpx_connect_error() -> None:
    """A plain
    ``httpx.ConnectError``
    is formatted as a
    network error."""
    import httpx
    from manusift.llm.client import _format_llm_error

    exc = httpx.ConnectError("no route to host")
    msg = _format_llm_error(exc)
    assert "network" in msg.lower() or "error" in msg.lower()


# ---------- 5. Generic exception ----------


def test_format_unknown_exception_falls_back_to_str() -> None:
    """An exception that is
    not a known SDK error
    falls back to
    ``str(exc)`` -- no
    crash."""
    from manusift.llm.client import _format_llm_error

    class WeirdError(Exception):
        pass

    exc = WeirdError("custom error string")
    msg = _format_llm_error(exc)
    assert "WeirdError" in msg
    assert "custom error string" in msg


# ---------- 6. The runner wires the formatted text into the chat log ----------
#
# This is a regression
# test for the user's
# exact bug: the raw
# exception was being
# emitted to the chat
# log. We verify the
# integration end-to-end
# by patching the
# Anthropic SDK to raise
# a 500.


def test_streaming_error_does_not_leak_raw_exception(
    monkeypatch,
) -> None:
    """The Anthropic
    streaming path now
    uses
    ``_format_llm_error``
    instead of
    ``f"error: {exc}"``."""
    import httpx
    import anthropic
    from dotenv import load_dotenv
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    load_dotenv()
    from manusift.llm.client import AnthropicLLM

    llm = AnthropicLLM(get_settings())

    # Patch
    # ``_anthropic_create_with_retry``
    # to
    # raise
    # a
    # 500.
    def boom(*a, **k):
        request = httpx.Request(
            "POST",
            "https://api.minimaxi.com/anthropic/v1/messages",
        )
        response = httpx.Response(
            500,
            request=request,
            headers={"request-id": "test-rid-500"},
            json={
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "unknown error, 999 (1000)",
                },
            },
        )
        raise anthropic.APIStatusError(
            "Error code: 500 - {'type': 'error', ...}",
            response=response,
            body=response.json(),
        )

    monkeypatch.setattr(
        "manusift.llm.client.providers._anthropic_create_with_retry",
        boom,
    )

    chunks = list(llm.chat_stream([], None))
    assert len(chunks) == 1
    text = "".join(
        b.get("text", "")
        for b in chunks[0].content_blocks
        if b.get("type") == "text"
    )
    # The
    # raw
    # exception
    # message
    # is
    # NOT
    # echoed.
    assert "Error code: 500" not in text
    assert "{'type':" not in text
    # The
    # request
    # id
    # IS
    # preserved.
    assert "test-rid-500" in text
    # The
    # error
    # type
    # is
    # present.
    assert "api_error" in text
    # The
    # user
    # gets
    # a
    # retry
    # hint.
    assert (
        "transient" in text.lower()
        or "retry" in text.lower()
    )


def test_non_streaming_anthropic_chat_uses_formatter(monkeypatch) -> None:
    """Same as
    ``test_streaming_error_does_not_leak_raw_exception``
    but for the non-
    streaming path."""
    import httpx
    import anthropic
    from dotenv import load_dotenv
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    load_dotenv()
    from manusift.llm.client import AnthropicLLM

    llm = AnthropicLLM(get_settings())

    def boom(*a, **k):
        request = httpx.Request(
            "POST",
            "https://api.minimaxi.com/anthropic/v1/messages",
        )
        response = httpx.Response(
            500,
            request=request,
            headers={"request-id": "test-rid-500-ns"},
            json={"type": "error", "error": {"type": "api_error"}},
        )
        raise anthropic.APIStatusError(
            "Error code: 500",
            response=response,
            body=response.json(),
        )

    monkeypatch.setattr(
        "manusift.llm.client.providers._anthropic_create_with_retry",
        boom,
    )

    resp = llm.chat(
        [{"role": "user", "content": "hi"}],
        None,
    )
    text = "".join(
        b.get("text", "")
        for b in resp.content_blocks
        if b.get("type") == "text"
    )
    assert "Error code: 500" not in text
    assert "test-rid-500-ns" in text
