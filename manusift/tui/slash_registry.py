"""Unified slash-command registry (P1.2, R-2026-06-14).

The TUI used to have an inline ``if cmd == "/foo"`` chain
in ``chat_app._handle_slash_command``. The chain grew
to 15+ commands and was hard to test. This module
replaces it with a single ``SLASH_COMMANDS`` list so
new commands are added by importing a class and
appending it (patch-first, per the
``agent-infra-iteration-engineer`` skill).

Contract:

  * Each command is a ``SlashCommand`` dataclass
    with a ``name`` (no leading ``/``), a
    ``description``, an optional ``category``
    (e.g. "Session", "Tools"), and a
    ``handler`` (a callable taking
    ``(app, arg: str) -> None``).
  * ``SLASH_COMMANDS`` is the canonical list.
    It is read at startup; the TUI iterates
    it to build the ``/help`` overlay and the
    command-routing ``if/elif`` chain is
    generated from the same list.
  * Commands are dispatched by ``name`` (not by
    position), so the order in the list
    affects the ``/help`` overlay but not the
    dispatch.
  * A new command is a 4-line addition
    (import class, instantiate, append).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# The handler signature. ``app`` is the
# ChatApp; ``arg`` is the rest of the user
# input after the command name (whitespace-
# trimmed). The handler is expected to
# append to ``app`` (status line, chat log,
# etc.) and return nothing.
SlashHandler = Callable[[Any, str], None]


@dataclass(frozen=True)
class SlashCommand:
    """One slash command.

    Attributes:
        name: command name WITHOUT the leading
            ``/``. The dispatch matches on
            ``name`` after the user types
            ``/<name>...``.
        description: one-line description
            shown in the ``/help`` overlay.
        category: section header in the
            ``/help`` overlay (e.g.
            ``"Session"`` or ``"Tools"``).
        handler: callable
            ``(app, arg: str) -> None``.
        aliases: extra names that map to
            the same command. ``/q`` is a
            common alias for ``/quit``;
            both are accepted. Empty by
            default.
    """

    name: str
    description: str
    category: str
    handler: SlashHandler
    aliases: tuple[str, ...] = ()


_SLASH_COMMANDS: list[SlashCommand] = []


def register(
    cmd: SlashCommand,
    *,
    replace: bool = False,
) -> SlashCommand:
    """Append a command to the registry.

    If ``replace`` is True and a command with
    the same name (or any alias) already
    exists, it is removed first. ``replace``
    is a test affordance: production code
    registers at import time and should not
    pass ``replace=True`` (use the second
    registration site if the same command
    should be in two categories).
    """
    global _SLASH_COMMANDS
    if replace:
        _SLASH_COMMANDS = [
            c for c in _SLASH_COMMANDS
            if c.name != cmd.name
            and cmd.name not in c.aliases
            and not any(
                a in cmd.aliases for a in c.aliases
            )
        ]
    _SLASH_COMMANDS.append(cmd)
    return cmd


def iter_commands() -> Iterable[SlashCommand]:
    """Yield every registered command, in
    registration order.
    """
    return tuple(_SLASH_COMMANDS)


def all_names() -> list[str]:
    """Return every dispatch name (the
    primary ``name`` plus every alias).
    """
    out: list[str] = []
    for c in _SLASH_COMMANDS:
        out.append(c.name)
        out.extend(c.aliases)
    return out


def find(name: str) -> SlashCommand | None:
    """Find a command by name or alias.
    Returns ``None`` if not found.
    """
    name = name.lstrip("/")
    for c in _SLASH_COMMANDS:
        if c.name == name:
            return c
        if name in c.aliases:
            return c
    return None


def categories() -> list[str]:
    """Return the distinct category
    headers in registration order.
    """
    seen: list[str] = []
    for c in _SLASH_COMMANDS:
        if c.category and c.category not in seen:
            seen.append(c.category)
    return seen


def by_category() -> dict[str, list[SlashCommand]]:
    """Group commands by category, in
    registration order. Categories with
    no commands are omitted.
    """
    out: dict[str, list[SlashCommand]] = {}
    for c in _SLASH_COMMANDS:
        if not c.category:
            continue
        out.setdefault(c.category, []).append(c)
    return out


# --------------------------------------------------------------------
# Built-in commands
# --------------------------------------------------------------------
# These are the 4 commands the TUI
# exposes to the LLM-side text box
# (status / cost / tools / help). The
# actual TUI ChatApp wires the full
# 15+ command set when it imports
# this module; the registry is the
# canonical source of truth for
# ``/help`` output and the dispatch
# table.


def _echo_handler(app: Any, arg: str) -> None:
    """No-op handler used by the
    built-in ``/echo`` test command.
    """
    if app is None:
        return
    msg = arg or ""
    try:
        if hasattr(app, "_append_status_line"):
            app._append_status_line(f"echo: {msg}")
    except Exception:  # noqa: BLE001
        pass


def _help_handler(app: Any, arg: str) -> None:
    """The default ``/help`` handler. The
    real TUI may override this with a
    richer overlay; this fallback just
    writes a compact text list.
    """
    if app is None:
        return
    lines = ["# Commands"]
    for cat, cmds in by_category().items():
        lines.append("")
        lines.append(f"## {cat}")
        for c in cmds:
            alias = (
                f" (aliases: {', '.join('/' + a for a in c.aliases)})"
                if c.aliases else ""
            )
            lines.append(
                f"- ``/{c.name}`` -- {c.description}{alias}"
            )
    try:
        if hasattr(app, "_append_status_line"):
            app._append_status_line("\n".join(lines))
    except Exception:  # noqa: BLE001
        pass


# Register the built-ins. Tests that
# want a clean registry can call
# ``clear()`` (below) and re-import
# this module to get the defaults.
register(SlashCommand(
    name="help",
    description="show the slash command list",
    category="Help",
    handler=_help_handler,
))
register(SlashCommand(
    name="echo",
    description="test handler: echoes arg to status line",
    category="Help",
    handler=_echo_handler,
    aliases=("e",),
))


def clear() -> None:
    """Test hook. Drop every registered command.
    Production code should not call this.
    """
    global _SLASH_COMMANDS
    _SLASH_COMMANDS = []


def reset_to_defaults() -> None:
    """Test hook. Drop and re-install the
    built-in ``/help`` and ``/echo``
    commands. Production code should
    not call this.
    """
    clear()
    register(SlashCommand(
        name="help",
        description="show the slash command list",
        category="Help",
        handler=_help_handler,
    ))
    register(SlashCommand(
        name="echo",
        description="test handler: echoes arg to status line",
        category="Help",
        handler=_echo_handler,
        aliases=("e",),
    ))
