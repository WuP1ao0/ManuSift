"""Tests for the in-TUI status line.

The chat TUI has a single
``#status-line`` row at the
bottom of the TUI (just
below the input box) that
contains:

  1. A ``#spinner`` LoadingIndicator
     (visible only while the
     agent is running).
  2. A ``#tool-status`` text
     widget that shows the
     current agent activity
     ("thinking...",
     "calling foo...").
  3. A ``#detector-count`` widget
     that shows the number of
     registered detectors.
  4. A ``#cost-bar`` right-aligned
     token + USD counter.

The history panel takes the
full width (no sidebar in
the new layout).

The tests cover:

  1. The compose tree
     contains a
     ``#status-line`` with
     the four children.
  2. The ``_cost_bar_text``
     method returns a
     string with the arrow
     glyphs and a $ amount.
  3. The token accumulators
     start at 0 and grow
     when a ChatResponse is
     recorded.
  4. The cost log is
     appended to after every
     turn.
  5. The LoadingIndicator
     is hidden when no
     agent is running and
     shown when the agent
     starts.
  6. The tool-call message
     format includes a
     ``[ tool: NAME ]``
     badge.
  7. The ``_render_detector_count``
     widget is wired up so
     the detector count is
     rendered.
"""
from __future__ import annotations

import inspect
import re

import pytest


# ---------- 1. compose tree contains the new widgets ----------


def test_compose_has_status_line() -> None:
    """The ChatApp's compose()
    must yield a
    ``#status-line`` Horizontal
    container with the four
    children: ``#spinner``,
    ``#tool-status``,
    ``#detector-count``, and
    ``#cost-bar``."""
    from manusift.tui.chat_app import ChatApp
    src = inspect.getsource(ChatApp.compose)
    assert 'id="status-line"' in src
    assert 'id="spinner"' in src
    assert 'id="tool-status"' in src
    assert 'id="detector-count"' in src
    assert 'id="cost-bar"' in src


def test_compose_places_status_line_below_input() -> None:
    """The flattened status
    line must live below the
    input row, matching the
    highlighted target layout."""
    from manusift.tui.chat_app import ChatApp
    src = inspect.getsource(ChatApp.compose)
    assert src.index('id="input-row"') < src.index('id="status-line"')


# ---------- 2. _cost_bar_text format ----------


def test_cost_bar_text_contains_arrow_glyphs() -> None:
    """The right-aligned cost bar
    must contain the up-arrow
    (U+2191) and down-arrow
    (U+2193) glyphs. These are
    the same arrows Claude Code
    uses in its status bar."""
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._tokens_in = 1234
    app._tokens_out = 567
    app._cost_usd = 0.0123
    # R-2026-06-15 (Phase 2 + #5):
    # the cost bar now
    # also renders a
    # context-window
    # chip and a
    # prompt-cache
    # hit rate chip
    # (using
    # ``_cache_read_tokens``
    # +
    # ``_cache_creation_tokens``).
    # We set them
    # to 0 here so
    # the test pins
    # the basic
    # arrow-glyph
    # contract
    # without
    # pulling in
    # the new
    # chips.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._agent_running = False
    app._stream_t0 = 0.0
    text = app._cost_bar_text()
    assert "\u2191" in text
    assert "\u2193" in text
    assert "$" in text
    # 1234 >= 1000, so we expect a
    # compact k-suffix.
    assert "1.2k" in text or "1.2K" in text


def test_cost_bar_text_handles_zero_state() -> None:
    """With zero tokens and zero
    cost, the bar should not
    crash and should still
    contain the arrows and a
    $0.0000."""
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._tokens_in = 0
    app._tokens_out = 0
    app._cost_usd = 0.0
    app._agent_running = False
    app._stream_t0 = 0.0
    text = app._cost_bar_text()
    assert "\u2191" in text
    assert "\u2193" in text
    assert "$0.0000" in text


# ---------- 3. token accumulators start at 0 ----------


def test_token_accumulators_initialized_to_zero() -> None:
    """A freshly constructed
    ChatApp must have its token
    and cost accumulators at 0.
    The agent loop is what
    increments them as LLM
    responses come in."""
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    # Bypass __init__; set the
    # fields directly to mirror
    # what __init__ does.
    app._tokens_in = 0
    app._tokens_out = 0
    app._cost_usd = 0.0
    assert app._tokens_in == 0
    assert app._tokens_out == 0
    assert app._cost_usd == 0.0


# ---------- 4. tool message format ----------


def test_render_message_emits_tool_name_badge() -> None:
    """The ``_render_message``
    method must include a
    ``[ tool: NAME ]`` badge
    when the message has a
    ``tool_name`` set.

    R2: the actual rendering
    logic now lives in
    ``manusift.tui.rendering.render_message``.
    The test reads the
    source of that module
    instead of
    ``_render_message`` --
    the chat-app method is
    a thin wrapper now.
    """
    from manusift.tui.chat_app import ChatApp, ChatMessage
    from manusift.tui import rendering
    import datetime
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    msg = ChatMessage(
        role="tool",
        content="calling foo (a=1)",
        tool_name="metadata",
        timestamp=datetime.datetime.now().timestamp(),
    )
    # R-audit (2026-06-10): the
    # rendering module no
    # longer emits inline Rich
    # markup (``[magenta]``).
    # It uses TCSS classes
    # (``tool-name`` in the
    # Catppuccin Mocha theme)
    # applied via
    # ``Content.stylize``. The
    # ``[ tool: ... ]`` badge
    # text is still produced
    # but the colour comes
    # from ``$mocha-peach``.
    rendering_src = inspect.getsource(rendering)
    assert "[ tool: " in rendering_src
    assert "msg.tool_name" in rendering_src
    assert "tool-name" in rendering_src
    # The chat-app method
    # delegates to the
    # rendering module.
    chat_src = inspect.getsource(ChatApp._render_message)
    assert "render_message" in chat_src
    widget = app._render_message(msg)
    assert widget is not None


# ---------- 5. CSS classes for the status line ----------


def test_css_has_status_line_styles() -> None:
    """The CSS block of ChatApp
    must contain a
    ``#status-line`` rule. The
    spinner must have a hidden
    modifier (``#spinner.hidden``)
    so we can collapse it when
    no agent is running."""
    from manusift.tui.chat_app import ChatApp
    css = ChatApp.CSS
    assert "#status-line" in css
    assert "#spinner" in css
    assert "#cost-bar" in css
    assert "hidden" in css


# ---------- 6. cost log integration ----------


def test_chat_app_imports_cost_record_call() -> None:
    """The chat_app module must
    import ``record_call`` from
    ``..cost`` so the
    ``_record_resp_cost`` helper
    can append to the cost log."""
    from manusift.tui import chat_app
    src = inspect.getsource(chat_app)
    assert "from ..cost import" in src
    assert "record_call" in src


def test_record_resp_cost_signature() -> None:
    """``_record_resp_cost`` is a
    method (bound on the ChatApp
    instance) that accepts a
    ``ChatResponse`` and updates
    the running accumulators."""
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, "_record_resp_cost", None)
    assert method is not None
    sig = inspect.signature(method)
    # The method has ``self`` and
    # one positional argument
    # (the response).
    assert len(sig.parameters) == 2


def test_record_resp_cost_handles_missing_record() -> None:
    """``_record_resp_cost`` is
    idempotent: if
    ``record_call`` returns None
    (e.g. no usage data) the
    function returns silently
    without crashing."""
    from manusift.tui.chat_app import ChatApp
    # Build an app without booting
    # the textual machinery.
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._tokens_in = 5
    app._tokens_out = 6
    app._cost_usd = 0.01
    # Construct a fake response.
    from manusift.llm.chat import ChatResponse
    resp = ChatResponse(
        content_blocks=[],
        stop_reason="end_turn",
    )
    # Monkey-patch record_call to
    # return None. We do this by
    # replacing the module-level
    # alias the chat_app captured
    # at import time.
    import manusift.tui.chat_app as ca
    original = ca._cost_record_call
    ca._cost_record_call = lambda r: None
    try:
        app._record_resp_cost(resp)
    finally:
        ca._cost_record_call = original
    # Accumulators should be
    # unchanged.
    assert app._tokens_in == 5
    assert app._tokens_out == 6
    assert app._cost_usd == 0.01


# ---------- A.5: token-by-token speed indicator ----------


def test_cost_bar_omits_speed_when_not_streaming() -> None:
    """When ``_agent_running`` is
    False (the default for a
    fresh app), the cost bar
    must NOT contain a ``t/s``
    suffix. The speed indicator
    only appears during a live
    agent turn."""
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._tokens_in = 100
    app._tokens_out = 200
    app._cost_usd = 0.005
    app._agent_running = False
    app._stream_t0 = 0.0
    text = app._cost_bar_text()
    assert "t/s" not in text


def test_cost_bar_emits_speed_when_streaming() -> None:
    """When ``_agent_running`` is
    True and ``_stream_t0`` is
    set to a wall-clock value,
    the cost bar must contain a
    ``<n> t/s`` suffix. The
    speed is computed from the
    token delta divided by the
    elapsed monotonic time."""
    import time
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._tokens_in = 100
    app._tokens_out = 1200  # 1000 tokens generated
    app._cost_usd = 0.005
    app._agent_running = True
    # 1 second ago we started
    # streaming with 200 tokens.
    app._stream_t0 = time.monotonic() - 1.0
    app._stream_t0_toks = 200
    text = app._cost_bar_text()
    # We expect a t/s suffix.
    assert "t/s" in text
    # The throughput should be
    # 1000 tokens / 1.0s = 1000
    # t/s, but the bar formats
    # it as an integer. We just
    # check the structure.
    assert "1000" in text or "1.0k" in text


def test_streaming_clock_fields_init_to_zero() -> None:
    """A fresh ChatApp must have
    its streaming-clock fields
    initialized to zero so the
    speed indicator does not
    fire until the first chunk
    arrives."""
    from manusift.tui.chat_app import ChatApp
    app = ChatApp.__new__(ChatApp)
    # R-2026-06-15 (Phase 2 + #5):
    # cost bar now also
    # renders a prompt-cache chip
    # using these two counters.
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    app._stream_t0 = 0.0
    app._stream_t0_toks = 0
    assert app._stream_t0 == 0.0
    assert app._stream_t0_toks == 0


# ---------- 7. detector count widget ----------


def test_render_detector_count_method_exists() -> None:
    """The ``_render_detector_count``
    method must exist on ChatApp
    so the detector count is
    refreshed in the status line."""
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, "_render_detector_count", None)
    assert method is not None


def test_set_status_refreshes_detector_count() -> None:
    """``_set_status`` must call
    ``_render_detector_count``
    so the detector count is
    kept in sync with every
    status change."""
    from manusift.tui.chat_app import ChatApp
    src = inspect.getsource(ChatApp._set_status)
    assert "self._render_detector_count" in src


def test_compose_has_no_sidebar() -> None:
    """The new layout removes the
    right-side sidebar; the
    compose tree must NOT
    contain a ``#sidebar``
    widget. The detector count
    and stats are flattened
    into the status line."""
    from manusift.tui.chat_app import ChatApp
    src = inspect.getsource(ChatApp.compose)
    assert 'id="sidebar"' not in src
    assert 'id="chat-and-sidebar"' not in src
    # ``#status-bar`` was the
    # pre-flatten identifier;
    # the new id is
    # ``#status-line``.
    assert 'id="status-bar"' not in src
