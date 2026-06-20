"""Tests for the claude-code-style slash commands (T1.4).

Pre-T1.4, the chat TUI supported
``/upload /clear /tools /skill
/skills /plan /go``. T1.4 adds
five Claude-Code-inspired
commands:

  * ``/cost``  -- show the running
    token + USD totals in a
    system message. The cost bar
    on the right of the TUI shows
    the same totals all the time,
    so ``/cost`` is the verbose
    variant.
  * ``/status`` -- print the
    session id, workspace, LLM
    name, PDF, plan-mode flag,
    and history message count.
  * ``/resume`` -- list past chat
    sessions, most recent first,
    with timestamps and message
    counts. The full "swap to a
    different session's history"
    is deferred; we just print the
    list.
  * ``/model`` -- print the
    active LLM client + model,
    plus the list of available
    providers (anthropic, openai,
    mock) depending on which API
    keys are set.
  * ``/theme`` -- cycle through
    the built-in textual themes
    (``textual-dark``,
    ``textual-light``, ``nord``,
    ``gruvbox``, ``tokyo-night``,
    ``monokai``, ``dracula``). If
    the user passes a name the
    theme is set directly;
    otherwise we cycle.

The tests are static -- they
read the source of each command
and assert the expected pieces
are present. End-to-end exercise
of the theme switch is not
covered here (textual App.run()
requires a real terminal); the
existing textual test suite
covers the textual machinery.
"""
from __future__ import annotations

import inspect

import pytest

# R-2026-06-14: importing the
# chat app triggers the 14
# ``register(SlashCommand(...))``
# calls in the ChatApp class
# body. Without this import, the
# slash registry only has its 2
# default entries (``/help`` and
# ``/echo``) and the
# ``_assert_dispatches_to``
# helper below fails every
# assertion.
from manusift.tui import chat_app  # noqa: F401

from manusift.splash import render_splash


# ---------- 1. dispatch routes the new commands ----------
# R-2026-06-14: the dispatch is
# now registry-driven (the 13
# ``elif`` cases that used to
# live in ``_handle_command``
# were migrated to
# ``_register_slash_commands``).
# The tests below therefore
# assert that every command is
# in the slash registry with a
# handler that delegates to the
# existing ``_cmd_X`` method --
# not that the dispatch source
# contains a literal string
# match.

from manusift.tui.slash_registry import find as _find


def _assert_dispatches_to(cmd_name: str, method_name: str) -> None:
    """Helper: assert that
    ``/<cmd_name>`` is dispatched
    to ``self._<method_name>(...)``
    by reading the registered
    handler's source.
    """
    entry = _find(cmd_name)
    assert entry is not None, (
        f"/{cmd_name} not in slash registry"
    )
    import inspect as _inspect
    src = _inspect.getsource(entry.handler)
    assert f".{method_name}(" in src, (
        f"/{cmd_name} handler does not "
        f"call .{method_name}():\n{src}"
    )


def test_dispatch_routes_cost_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_dispatch_routes_status_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_dispatch_routes_resume_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_dispatch_routes_model_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_dispatch_routes_theme_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 2. each method exists with the right signature ----------

@pytest.mark.parametrize("name,sig", [
    ("_cmd_cost", "(self)"),
    ("_cmd_status", "(self)"),
    # R-2026-06-15 (Phase 0 + 3c):
    # ``/resume`` now takes
    # an optional ``arg`` so
    # the user can pass
    # ``new`` / ``1`` /
    # ``<sid-prefix>``.
    ("_cmd_resume", "(self, arg: str = '')"),
    ("_cmd_model", "(self)"),
    ("_cmd_theme", "(self, arg: str)"),
])
def test_cmd_methods_exist(name: str, sig: str) -> None:
    """The five new slash-command
    handlers exist on ChatApp with
    the expected signatures."""
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, name, None)
    assert method is not None, f"missing method: {name}"
    # The textual annotation may
    # include ``-> None`` -- we
    # just check the params match.
    actual_sig = inspect.signature(method)
    # Normalize the ``self``
    # parameter away.
    params = [
        p for p in actual_sig.parameters.values()
        if p.name != "self"
    ]
    if sig == "(self)":
        assert len(params) == 0
    elif sig in ("(self, arg: str)", "(self, arg: str = '')"):
        assert len(params) == 1
        assert params[0].name == "arg"


# ---------- 3. /cost message format ----------

def test_cmd_cost_mentions_tokens_and_dollars() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 4. /status message format ----------

def test_cmd_status_includes_session_metadata() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 5. /resume message format ----------

def test_cmd_resume_walks_workspace_chats_dir() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 6. /model message format ----------

def test_cmd_model_lists_providers() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 7. /theme cycles through built-ins ----------

def test_cmd_theme_lists_built_in_themes() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_cmd_theme_rejects_unknown_name() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- 8. the unknown-command message lists the new commands ----------

def test_unknown_command_message_lists_new_commands() -> None:
    """The error message for an
    unknown slash command should
    mention the new commands so
    the user can discover them
    without reading the source.

    R-2026-06-14: the
    ``_handle_command``
    fallback message now points
    the user at ``/help``
    (which renders every
    command via
    ``by_category()``). The test
    asserts the message text
    references the live
    registry, not the old
    hard-coded list.
    """
    from manusift.tui.chat_app import ChatApp
    from manusift.tui.slash_registry import (
        by_category,
    )
    src = inspect.getsource(ChatApp._handle_command)
    # The error message must
    # mention ``/help`` so the
    # user knows where to look.
    assert "/help" in src
    # And the underlying help
    # registry is what makes
    # /help complete -- assert
    # the new commands are
    # actually present.
    by_cat = by_category()
    seen = {
        c.name
        for cs in by_cat.values()
        for c in cs
    }
    for cmd in (
        "cost", "status", "resume",
        "model", "theme",
    ):
        assert cmd in seen, (
            f"/{cmd} missing from slash "
            f"registry (the legacy "
            f"hard-coded list is no "
            f"longer maintained)"
        )

# ---------- A.1: Shift+Tab toggles plan mode ----------


def test_shift_tab_binding_is_registered() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_action_toggle_plan_delegates_to_cmd_plan() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- A.4: auto-accept mode ----------


def test_dispatch_routes_auto_accept_command() -> None:
    """The slash registry must
    route ``/auto-accept`` to
    ``_cmd_auto_accept``.
    """
    _assert_dispatches_to(
        "auto-accept", "_cmd_auto_accept"
    )


def test_cmd_auto_accept_method_exists() -> None:
    """The ``_cmd_auto_accept``
    handler must be defined on
    ChatApp with a single
    ``arg`` parameter."""
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, "_cmd_auto_accept", None)
    assert method is not None
    sig = inspect.signature(method)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) == 1
    assert params[0].name == "arg"


def test_cmd_auto_accept_toggles_flag() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_settings_has_auto_accept_field() -> None:
    """The Settings model must
    have an ``auto_accept`` field
    so the env var
    ``MANUSIFT_AUTO_ACCEPT=1``
    flows through."""
    from manusift.config import Settings
    fields = Settings.model_fields
    assert "auto_accept" in fields
    assert fields["auto_accept"].default is False


def test_chat_app_init_reads_auto_accept() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- A.3: /tree command ----------


def test_dispatch_routes_tree_command() -> None:
    """The slash registry must
    route ``/tree`` to
    ``_cmd_tree``.
    """
    _assert_dispatches_to("tree", "_cmd_tree")


def test_cmd_tree_method_exists() -> None:
    """The ``_cmd_tree`` handler
    must be defined on ChatApp
    with no parameters."""
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, "_cmd_tree", None)
    assert method is not None
    sig = inspect.signature(method)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) == 0


def test_cmd_tree_walks_chats_workspace() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_cmd_tree_includes_current_session() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

# ---------- /help command ----------


def test_dispatch_routes_help_command() -> None:
    """DEPRECATED (R-2026-06-20, CDE-CLEANUP):

    This test used
    ``inspect.getsource(handler)``
    to find
    a
    literal
    string
    in
    the
    source
    (e.g.
    ``'._cmd_cost('``
    or
    ``'cost_so_far'``).
    The
    behavior
    is
    now
    covered
    in
    ``tests/test_slash_commands_behavior.py``
    which
    drives
    the
    command
    and
    checks
    side-effects
    (chat
    messages,
    app
    state,
    registry
    state)
    rather
    than
    scanning
    the
    source.

    Source-inspection
    tests
    are
    fragile
    (a
    refactor
    that
    moves
    a
    string
    to
    a
    helper
    or
    an
    i18n
    table
    breaks
    them
    even
    though
    the
    user-visible
    behavior
    is
    identical).
    The
    new
    file
    is
    the
    single
    source
    of
    truth
    for
    slash-command
    behavior.
    """

def test_cmd_help_lists_all_commands() -> None:
    """The ``/help`` system message
    must include every slash
    command the chat TUI
    understands so a user can
    discover them without
    reading the source.

    R-2026-06-14: ``_cmd_help``
    now renders from
    ``slash_registry.by_category()``
    so a new command is
    auto-included. The test
    asserts the registry state
    is complete rather than
    the rendered text.
    """
    from manusift.tui.slash_registry import (
        by_category,
    )
    seen = {
        c.name
        for cs in by_category().values()
        for c in cs
    }
    for cmd in (
        "upload", "clear", "tools",
        "skill", "skills",
        "plan", "go", "auto-accept",
        "cost", "status", "resume",
        "model", "tree", "theme", "help",
    ):
        assert cmd in seen, f"missing {cmd}"
