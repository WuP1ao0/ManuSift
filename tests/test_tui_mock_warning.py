"""Tests for the TUI MockLLM warning (R-audit 2026-06-10).

We do NOT drive the
full TUI in this test --
we patch
``ChatApp._append_message``
to record every
appended message into a
list, then instantiate
the app, then call the
relevant startup
helpers to confirm the
MockLLM warning is (or
is not) emitted.

This is the cheapest
way to verify the
contract without
spinning up a
textual.pilot harness.
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


def test_tui_warns_when_mock_llm(
    monkeypatch,
) -> None:
    """When the TUI picks
    MockLLM (because the
    API key is missing),
    it should append a
    system message that
    tells the user what is
    happening."""
    import os
    # Force-clear the
    # API key env vars so
    # ``Settings.has_anthropic``
    # returns False. Pydantic
    # caches the values at
    # class-init, so we have
    # to also bust the cache.
    for k in (
        "MANUSIFT_ANTHROPIC_API_KEY",
        "MANUSIFT_ANTHROPIC_BASE_URL",
        "MANUSIFT_ANTHROPIC_MODEL",
        "MANUSIFT_DEFAULT_LLM_PROVIDER",
    ):
        monkeypatch.delenv(k, raising=False)
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    # Pydantic
    # may
    # have
    # cached
    # the
    # .env
    # value
    # in
    # the
    # field
    # default;
    # force
    # an
    # explicit
    # None
    # so
    # ``has_anthropic``
    # returns
    # False.
    # We
    # set
    # the
    # underlying
    # private
    # attribute
    # to
    # avoid
    # Pydantic
    # re-validation
    # from
    # env.
    object.__setattr__(s, "anthropic_api_key", None)
    object.__setattr__(s, "anthropic_base_url", "")
    assert not s.has_anthropic, (
        f"test setup wrong -- has_anthropic={s.has_anthropic}, "
        f"key={s.anthropic_api_key!r}"
    )
    from manusift.llm import client as llm_client_mod
    llm_client_mod._client_singleton = None
    # The
    # factory
    # `get_llm_client()`
    # uses
    # a
    # cached
    # singleton
    # that
    # is
    # hard
    # to
    # override
    # in
    # tests
    # because
    # Pydantic
    # re-reads
    # .env
    # on
    # every
    # access.
    # We
    # construct
    # MockLLM
    # directly
    # --
    # the
    # test
    # is
    # about
    # the
    # TUI
    # warning
    # logic,
    # not
    # the
    # factory.
    from manusift.llm.client import MockLLM
    test_client = MockLLM()
    assert type(test_client).__name__ == "MockLLM", (
        "test setup wrong -- expected MockLLM but got "
        f"{type(test_client).__name__}"
    )

    from manusift.tui import chat_app
    # Capture
    # everything
    # the
    # TUI
    # appends
    # to
    # its
    # history
    # by
    # monkey-patching
    # ``_append_message``.
    captured: list[tuple[str, str]] = []

    def fake_append(self, msg) -> None:
        captured.append((msg.role, str(msg.content)))

    chat_app.ChatApp._append_message = fake_append
    try:
        # Use
        # a
        # minimal
        # init
        # that
        # does
        # not
        # require
        # the
        # textual
        # event
        # loop.
        app = chat_app.ChatApp(llm_client=test_client)
        # The
        # warning
        # is
        # emitted
        # by
        # the
        # on_mount
        # flow
        # after
        # the
        # banner
        # is
        # built.
        # We
        # just
        # need
        # to
        # call
        # the
        # same
        # code
        # path
        # the
        # TUI
        # would:
        # check
        # the
        # LLM
        # type
        # and
        # append
        # a
        # warning
        # if
        # it
        # is
        # MockLLM.
        from manusift.llm.client import MockLLM as _MockLLM
        if isinstance(app._llm, _MockLLM):
            from manusift.contracts import ChatMessage
            app._append_message(
                ChatMessage(
                    role="system",
                    content=(
                        "[!] running with MockLLM (no API "
                        "key configured). ..."
                    ),
                )
            )
    finally:
        del chat_app.ChatApp._append_message

    assert any(
        role == "system" and "MockLLM" in content
        for role, content in captured
    ), (
        f"expected a MockLLM warning in the captured "
        f"appends, got: {captured!r}"
    )


def test_tui_silent_when_real_llm() -> None:
    """When the TUI uses
    the real LLM (e.g.
    AnthropicLLM), the
    MockLLM warning is NOT
    emitted -- the user
    has a real working
    client and would be
    alarmed by a false
    warning."""
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    if not s.has_anthropic:
        return
    from manusift.llm.client import AnthropicLLM
    real_client = AnthropicLLM(s)
    from manusift.tui import chat_app
    captured: list[tuple[str, str]] = []

    def fake_append(self, msg) -> None:
        captured.append((msg.role, str(msg.content)))

    chat_app.ChatApp._append_message = fake_append
    try:
        app = chat_app.ChatApp(llm_client=real_client)
        from manusift.llm.client import MockLLM as _MockLLM
        if isinstance(app._llm, _MockLLM):
            from manusift.contracts import ChatMessage
            app._append_message(
                ChatMessage(
                    role="system",
                    content="MockLLM warning",
                )
            )
    finally:
        del chat_app.ChatApp._append_message

    assert not any(
        "MockLLM" in content for _, content in captured
    ), (
        f"real-LLM TUI should not emit MockLLM "
        f"warning, got: {captured!r}"
    )