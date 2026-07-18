"""Tests for the streaming timeout setting (R-audit, 2026-06-10).

Before this audit the
streaming chat path
relied on the Anthropic
SDK's default 5s
``httpx`` read timeout.
The MiniMax-M3 endpoint
takes much longer than
that to think + emit all
tokens for a complex turn
with 44 tools, and the
agent loop would crash
with
``httpcore.ReadTimeout``
in the middle of a
multi-step investigation
-- typically after 5-20s
of "no chunk arrived"
silence.

The audit adds a
dedicated settings field
``llm_stream_timeout_seconds``
(``120.0``) and passes
``timeout=`` to both
``_openai_create_with_retry``
and
``_anthropic_create_with_retry``
when ``stream=True``.
Non-streaming chat keeps
the existing 20s
``llm_call_timeout_seconds``
because a single
non-streaming request
fits in 20s comfortably
and we do not want a
slow LLM to block the
non-streaming enrichment
path.
"""
from __future__ import annotations

import os

import pytest


def test_stream_timeout_setting_exists() -> None:
    """The setting is
    declared on the
    Settings model so
    users can override it
    via env var
    ``MANUSIFT_LLM_STREAM_TIMEOUT_SECONDS``.
    """
    from manusift.config import Settings

    s = Settings()
    assert hasattr(s, "llm_stream_timeout_seconds")
    # Default
    # is
    # well
    # above
    # the
    # 5s
    # SDK
    # default.
    assert s.llm_stream_timeout_seconds >= 30.0


def test_stream_timeout_default_is_600s() -> None:
    """600s is the chosen
    default -- thinking
    models can pause a long
    time between SSE events;
    the 2026-07 pilot saw
    TimeoutError at the old
    120s budget, so the
    default was raised
    (see config.py comment)."""
    from manusift.config import Settings

    assert Settings().llm_stream_timeout_seconds == 600.0


def test_stream_timeout_overridable_via_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Users can bump or
    shrink the streaming
    timeout via the env
    var without code
    changes."""
    monkeypatch.setenv(
        "MANUSIFT_LLM_STREAM_TIMEOUT_SECONDS", "300.0"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.llm_stream_timeout_seconds == 300.0


def test_non_streaming_timeout_default() -> None:
    """The non-streaming
    timeout default is 300s.
    Thinking models + large
    tool schemas often
    exceeded the old 20s
    budget (DeepSeek /
    Claude thinking), so the
    default was raised --
    see the config.py
    comment."""
    from manusift.config import Settings

    assert Settings().llm_call_timeout_seconds == 300.0


def test_streaming_chat_passes_timeout_to_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: when
    ``AnthropicLLM.chat_stream``
    is called, the
    underlying
    ``sdk.messages.create``
    receives the streaming
    timeout. We verify by
    monkey-patching the
    SDK factory and
    inspecting the kwargs.

    This is the load-bearing
    test: if the kwargs
    stop carrying the
    timeout, the agent
    loop regresses to the
    5s default and the
    MiniMax-M3 streaming
    crash comes back.
    """
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from manusift.llm.client import AnthropicLLM

    # Build
    # a
    # real
    # AnthropicLLM
    # with
    # the
    # settings.
    s = get_settings()
    if not s.has_anthropic:
        pytest.skip("no anthropic key")
    llm = AnthropicLLM(s)

    # Replace
    # the
    # SDK
    # factory
    # so
    # we
    # can
    # inspect
    # the
    # call.
    captured: list[dict] = []

    class _FakeSDK:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured.append(kwargs)
                # Return
                # an
                # empty
                # async-style
                # iterator
                # so
                # the
                # loop
                # exits
                # cleanly.
                return iter([])

    # The
    # AnthropicLLM
    # uses
    # ``_sdk()``
    # to
    # get
    # the
    # SDK
    # instance.
    # Patch
    # that
    # method.
    monkeypatch.setattr(llm, "_sdk", lambda: _FakeSDK)

    # Drive
    # ``chat_stream``
    # and
    # inspect
    # the
    # captured
    # kwargs.
    list(
        llm.chat_stream(
            messages=[
                {"role": "user", "content": "hi"}
            ],
            tools=None,
            max_tokens=64,
        )
    )

    # The
    # stream=True
    # call
    # must
    # carry
    # our
    # timeout.
    stream_call = next(
        c for c in captured if c.get("stream")
    )
    assert "timeout" in stream_call, (
        "streaming call to sdk.messages.create is "
        "missing the `timeout=` kwarg; this regresses "
        "to the 5s SDK default and the MiniMax-M3 "
        "thinking pause crashes the agent loop."
    )
    # The
    # value
    # must
    # come
    # from
    # the
    # settings
    # field,
    # not
    # a
    # hard-coded
    # literal.
    assert (
        stream_call["timeout"]
        == s.llm_stream_timeout_seconds
    )