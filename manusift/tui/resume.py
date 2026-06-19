"""Resume-helper for the chat TUI
(R-2026-06-15, Phase 0 + 3c).

The user wants Claude-Code /
Hermes behaviour: every
restart starts a fresh
context window, but a
``/resume`` slash command
can switch back into a
prior context window.
Combined with prompt
caching (Phase 0 + 3c.1),
the resumed context window
lands on the same cache
bucket and the first
turn is a 100% cache hit.

This module is a **pure
helper** (no textual App,
no chat-app coupling).
The chat app calls
``list_sessions(chats_dir)``
to render a ``/resume``
listing and
``parse_resume_arg(arg, listings)``
to interpret the user's
argument.

The contract:

  * ``list_sessions(chats_dir)``
    returns a list of
    ``SessionListing``
    dataclasses sorted
    most-recent-first by
    ``last_message_ts``.
    A missing or empty
    directory returns
    ``[]``.
  * Each ``SessionListing``
    has: ``session_id``,
    ``message_count``,
    ``last_user_preview``
    (the first 80 chars
    of the most recent
    user message),
    ``last_message_ts``
    (the last message's
    Unix timestamp, or
    ``None`` if there
    are no messages),
    ``model`` (from
    session metadata
    if present, else
    ``"?"``).
  * ``parse_resume_arg(arg, listings)``
    interprets the
    ``/resume`` argument.
    Returns a ``ResumeTarget``
    with ``mode``
    in ``{"list", "switch",
    "new", "invalid"}``
    and (for ``"switch"``)
    the resolved
    ``session_id``.
  * The argument is one
    of:
    - ``""`` (empty, just
      ``/resume``) -> list
      mode.
    - ``"new"`` -> start
      a brand-new session.
    - an integer like
      ``"2"`` -> pick the
      second listing
      (1-based, the most
      recent = ``"1"``).
    - a session id that
      starts with a hex
      prefix -> pick the
      listing whose id
      starts with the
      given prefix.
  * An unknown argument
    returns ``mode="invalid"``
    with a ``reason`` field.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pattern: a session id
# produced by
# ``uuid.uuid4().hex[:12]``
# (12 hex chars) or a
# longer uuid hex prefix.
_HEX_PREFIX = re.compile(r"^[0-9a-fA-F]+$")


@dataclass(frozen=True)
class SessionListing:
    """One row in the
    ``/resume`` listing.
    """

    session_id: str
    message_count: int
    last_user_preview: str
    last_message_ts: float | None
    model: str


@dataclass(frozen=True)
class ResumeTarget:
    """The result of parsing
    a ``/resume`` argument.
    """

    mode: str  # "list" | "switch" | "new" | "invalid"
    session_id: str | None = None
    reason: str = ""


def _read_session_meta(
    session_dir: Path,
) -> dict[str, Any]:
    """Read a session's
    metadata file
    (``session.json``) if
    it exists. Returns
    ``{}`` for a missing
    or corrupt file.
    """
    p = session_dir / "session.json"
    if not p.exists():
        return {}
    try:
        return json.loads(
            p.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}


def _read_messages(
    session_dir: Path,
) -> list[dict[str, Any]]:
    """Read a session's
    ``messages.jsonl``
    file. Returns ``[]``
    for a missing or
    corrupt file.
    """
    p = session_dir / "messages.jsonl"
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in p.read_text(
            encoding="utf-8"
        ).splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip
                # corrupt
                # lines
                # (defensive).
                continue
    except OSError:
        return []
    return out


def _last_user_preview(
    messages: list[dict[str, Any]],
) -> str:
    """Return the first 80
    characters of the most
    recent user message, or
    ``"(no user messages yet)"``
    if there are none.
    """
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                # The
                # OpenAI-style
                # content
                # blocks.
                for c in content:
                    if (
                        isinstance(c, dict)
                        and c.get("type")
                        == "text"
                    ):
                        text = c.get(
                            "text", ""
                        )
                        if text:
                            return (
                                text[:80]
                                + (
                                    "..."
                                    if len(text)
                                    > 80
                                    else ""
                                )
                            )
            else:
                text = str(content)
                if text:
                    return (
                        text[:80]
                        + (
                            "..."
                            if len(text)
                            > 80
                            else ""
                        )
                    )
    return "(no user messages yet)"


def list_sessions(
    chats_dir: Path,
) -> list[SessionListing]:
    """List all chat sessions
    under ``chats_dir``,
    most-recent-first.

    Each session is a
    sub-directory whose
    name is the session id.
    The session's
    ``messages.jsonl``
    supplies the message
    count and the last user
    preview. The
    ``session.json``
    (written by the chat
    app on first
    ``_append_history``)
    supplies the model.

    The contract:

      * A missing
        ``chats_dir``
        returns
        ``[]``.
      * A session
        directory
        with no
        messages
        is still
        listed
        (with
        ``message_count=0``
        and a
        default
        preview).
      * Sessions
        are
        sorted by
        ``last_message_ts``
        descending
        (most
        recent
        first).
        A session
        with no
        messages
        (and no
        timestamp)
        sorts to
        the end.
    """
    if not chats_dir.is_dir():
        return []
    out: list[SessionListing] = []
    for child in sorted(chats_dir.iterdir()):
        if not child.is_dir():
            continue
        messages = _read_messages(child)
        meta = _read_session_meta(child)
        # Last message
        # timestamp: parse
        # an ISO-8601 ``ts``
        # field if present,
        # else ``None``.
        last_ts: float | None = None
        if messages:
            last_msg = messages[-1]
            ts_str = last_msg.get("ts")
            if isinstance(ts_str, str):
                try:
                    from datetime import (
                        datetime,
                    )
                    dt = datetime.fromisoformat(
                        ts_str
                    )
                    last_ts = dt.timestamp()
                except ValueError:
                    last_ts = None
        out.append(
            SessionListing(
                session_id=child.name,
                message_count=len(messages),
                last_user_preview=_last_user_preview(
                    messages
                ),
                last_message_ts=last_ts,
                model=str(meta.get("model", "?")),
            )
        )
    out.sort(
        key=lambda s: (
            s.last_message_ts is None,
            -(s.last_message_ts or 0.0),
        )
    )
    return out


def parse_resume_arg(
    arg: str,
    listings: list[SessionListing],
) -> ResumeTarget:
    """Interpret a
    ``/resume <arg>``
    argument.

    The contract:

      * ``""`` or
        whitespace
        only
        ->
        ``ResumeTarget(mode="list")``
        (the user
        wants
        to see
        the
        listing).
      * ``"new"``
        ->
        ``ResumeTarget(mode="new")``
        (start
        a
        brand-new
        session).
      * A
        positive
        integer
        string
        ``"1"``,
        ``"2"``,
        ...
        -> 1-based
        index
        into
        ``listings``.
        ``"1"``
        is
        the
        most
        recent
        session.
      * A
        hex
        prefix
        (one
        or
        more
        hex
        digits)
        ->
        the
        first
        listing
        whose
        id
        starts
        with
        the
        prefix
        (case-insensitive).
      * Anything
        else
        ->
        ``ResumeTarget(mode="invalid", reason="...")``
        with
        a
        human-readable
        reason.

    The argument is
    stripped of leading
    and trailing
    whitespace before
    interpretation.
    """
    arg = (arg or "").strip()
    if not arg:
        return ResumeTarget(mode="list")
    if arg == "new":
        return ResumeTarget(mode="new")
    # Integer
    # index?
    if arg.isdigit():
        idx = int(arg)
        if idx < 1 or idx > len(listings):
            return ResumeTarget(
                mode="invalid",
                reason=(
                    f"index {idx} is out of "
                    f"range; /resume accepts "
                    f"1..{len(listings)}"
                ),
            )
        return ResumeTarget(
            mode="switch",
            session_id=listings[
                idx - 1
            ].session_id,
        )
    # Hex
    # prefix?
    if _HEX_PREFIX.match(arg):
        prefix = arg.lower()
        for listing in listings:
            if (
                listing.session_id.lower()
                .startswith(prefix)
            ):
                return ResumeTarget(
                    mode="switch",
                    session_id=listing.session_id,
                )
        return ResumeTarget(
            mode="invalid",
            reason=(
                f"no session id starts "
                f"with {arg!r}"
            ),
        )
    return ResumeTarget(
        mode="invalid",
        reason=(
            f"unknown resume target "
            f"{arg!r}; expected 'new', "
            f"a 1-based index, or a "
            f"session-id prefix"
        ),
    )


def render_resume_listing(
    listings: list[SessionListing],
    *,
    page_size: int = 20,
    page: int = 0,
) -> str:
    """Return a multi-line
    human-readable listing
    of past sessions.

    The contract:

      * Lines are
        stable
        (``"  <idx>. <sid>  <n> msgs  <preview>"``)
        so tests can pin
        individual lines.
      * An empty list
        returns
        ``"no saved sessions; this is your first run."``.
      * The first
        column is the
        1-based index
        (so a ``/resume <n>``
        can be issued).
      * A session with
        a model != ``"?"``
        is suffixed with
        ``"(model=<model>)"``.

    R-2026-06-19 (P2-D6):
    when there
    are more
    than
    ``page_size``
    sessions
    (default
    20), the
    listing
    paginates.
    The user
    sees one
    page at
    a time
    + a
    footer
    saying
    "page X of Y;
    /resume
    <n> for
    the
    N-th
    session".
    This is
    *virtual
    scrolling*
    in the
    sense
    that
    the
    listing
    never
    renders
    more
    than
    ``page_size``
    lines
    even
    if
    the
    user
    has
    10,000
    saved
    sessions.
    The
    TUI
    calls
    ``render_resume_listing(listings)``
    on
    the
    first
    ``/resume``
    and
    then
    ``render_resume_listing(listings, page=1)``
    for
    the
    next
    page.
    """
    if not listings:
        return (
            "no saved sessions; this is "
            "your first run."
        )
    n_total = len(listings)
    # R-2026-06-19 (P2-D6):
    # the
    # virtual
    # scrolling
    # window.
    # ``page=0``
    # means
    # the
    # first
    # ``page_size``
    # entries;
    # ``page=1``
    # means
    # the
    # next
    # ``page_size``
    # entries;
    # etc.
    n_pages = max(
        1, (n_total + page_size - 1) // page_size
    )
    page = max(0, min(page, n_pages - 1))
    start = page * page_size
    end = min(start + page_size, n_total)
    windowed = listings[start:end]
    lines: list[str] = []
    if n_pages > 1:
        # Multi-page
        # header.
        lines.append(
            f"=== Past chat sessions === "
            f"(page {page + 1} of {n_pages})"
        )
    else:
        lines.append("=== Past chat sessions ===")
    for i, s in enumerate(windowed, start=start + 1):
        suffix = (
            f"  (model={s.model})"
            if s.model and s.model != "?"
            else ""
        )
        lines.append(
            f"  {i}. {s.session_id}  "
            f"{s.message_count} msg"
            f"{'s' if s.message_count != 1 else ''}"
            f"  {s.last_user_preview}"
            f"{suffix}"
        )
    # R-2026-06-19 (P2-D6):
    # footer
    # with
    # navigation
    # hint
    # when
    # there
    # are
    # more
    # pages.
    if n_pages > 1:
        if page < n_pages - 1:
            lines.append("")
            lines.append(
                f"-- {n_total - end} more; "
                f"see /resume next or "
                f"/resume <N> for a specific page"
            )
        else:
            lines.append("")
            lines.append(
                "-- end of list; "
                "use /resume <N> to switch"
            )
    return "\n".join(lines)
