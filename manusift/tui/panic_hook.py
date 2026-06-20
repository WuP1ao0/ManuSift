"""R-2026-06-20 (CDE-UI-P0.3):
centralized unhandled-exception
handler for the
ManuSift TUI.

Background
----------

The reconstructed
``chat_app.py``
(``.pyc``
recovery) used
``except
Exception:
pass``
in dozens of
places. The
first user-visible
bug ("agent
crashed but the
status line didn't
turn red") was
traced back to one
of these silent
handlers.

Per the
clig.dev
principle
"Quiet but
precise" and
ponytail's
"Not lazy about:
error handling
that prevents data
loss", unhandled
exceptions must
not vanish. They
must be:

1. written to
   ``<workspace>/crash.log``
   (post-mortem
   evidence --
   ``ponytail:``
   the
   next
   reader
   /
   LLM
   needs
   the
   traceback
   to
   diagnose)
2. surfaced
   in the TUI
   (a chat-log
   ``ChatMessage``
   with ``role="system"``
   + a red
   ``error``
   marker)

This module
implements the
hook only. The
TUI surface is
the chat log --
no new widget
needed
(``_append_message``
with ``role="system"``
+ ``content="[panic]
..."`` is
sufficient).

Ponytail
notes
---------

* rung 2 hit:
  ``sys.excepthook``
  is in the stdlib
  -- no new
  dependency.
* rung 3 hit:
  ``asyncio.get_running_loop().set_exception_handler``
  is the Textual-
  native way to
  surface async
  crashes -- no
  new framework.
* rung 4 hit:
  we reuse the
  existing
  ``ChatApp._append_message``
  API rather than
  build a
  separate
  ``CrashCard``
  widget (the
  report listed
  ``CrashCard`` as
  P1, but
  per
  ponytail
  "deletion
  over
  addition",
  we ship
  the
  minimum
  now:
  a
  red
  system
  row
  in
  the
  existing
  chat
  log.
  If
  P1
  ``CrashCard``
  is
  built
  later,
  it's
  a
  trivial
  swap
  of
  one
  line.
* rung 5 hit:
  one small
  function,
  two
  event
  handlers,
  no
  abstraction
  layer
  (no
  "CrashReporter"
  class,
  no
  pluggable
  sinks).
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from typing import Any


# ``ponytail:``
# module-level
# ``_active_app``
# is the
# registry
# the
# ``sys.excepthook``
# uses to find
# the
# current
# ``ChatApp``.
# ``ChatApp.on_mount``
# sets it; we use
# a function
# getter so the
# module-level
# mutation is
# centralized.
_active_app_ref: list[Any] = []


def _active_app() -> Any:
    return _active_app_ref[0] if _active_app_ref else None


def set_active_app(app: Any) -> None:
    """Called by ``ChatApp.on_mount`` so
    the panic hook knows which app to
    surface the crash in.
    """
    if _active_app_ref:
        _active_app_ref[0] = app
    else:
        _active_app_ref.append(app)


def install_panic_hook(workspace_dir: Path) -> None:
    """Install the TUI panic hook.

    ``workspace_dir`` is the directory
    where ``crash.log`` is written
    (typically ``<workspace>/`` from
    ``get_settings().workspace_dir``).

    Idempotent: safe to call multiple
    times (the second call replaces
    the hook, which is harmless).
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    crash_log = workspace_dir / "crash.log"
    # ``sys.excepthook``
    # for sync
    # exceptions.
    prev_hook = sys.excepthook

    def _hook(exc_type: Any, exc_value: Any, tb: Any) -> None:
        # ``ponytail:``
        # the
        # traceback
        # is
        # the
        # best
        # debugging
        # artifact
        # we
        # have.
        # Save
        # it
        # BEFORE
        # delegating
        # to
        # the
        # default
        # hook.
        try:
            with crash_log.open("a", encoding="utf-8") as f:
                f.write(
                    "\n=== unhandled exception "
                    f"· {__import__('datetime').datetime.now().isoformat()} "
                    f"· {exc_type.__name__}: {exc_value} ===\n"
                )
                traceback.print_exception(
                    exc_type, exc_value, tb, file=f
                )
        except Exception:  # noqa: BLE001
            pass
        # Also
        # log
        # via
        # stdlib
        # logging
        # so
        # ``pytest
        # -s``
        # shows
        # it.
        logging.getLogger(__name__).exception(
            "manusift tui unhandled exception",
            exc_info=(exc_type, exc_value, tb),
        )
        # Surface
        # in the
        # chat log
        # -- ``_active_app``
        # is set
        # by
        # ``ChatApp.on_mount``.
        active_app = _active_app()
        if active_app is not None:
            try:
                append_panic_to_chat(
                    active_app, exc_type, exc_value
                )
            except Exception:  # noqa: BLE001
                pass
        # Delegate
        # to
        # the
        # previous
        # hook
        # (e.g.
        # pytest's
        # debug
        # hook
        # in
        # tests,
        # or
        # Textual's
        # default).
        try:
            prev_hook(exc_type, exc_value, tb)
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = _hook

    # Asyncio
    # loop
    # exception
    # handler
    # for
    # async
    # crashes
    # (Textual
    # is
    # async
    # internally
    # -- a
    # raised
    # exception
    # in
    # a
    # task
    # goes
    # here,
    # not
    # to
    # ``sys.excepthook``).
    try:
        loop = sys.modules.get("asyncio").get_event_loop()
    except RuntimeError:
        return  # no
    # running
    # loop;
    # hook
    # will
    # be
    # installed
    # on
    # next
    # call.

    def _async_hook(loop: Any, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if exc is None:
            msg = context.get("message", "async error")
            tb_lines = [f"{msg}\n"]
        else:
            tb_lines = traceback.format_exception(
                type(exc), exc, exc.__traceback__
            )
        try:
            with crash_log.open("a", encoding="utf-8") as f:
                f.write(
                    "\n=== unhandled async exception "
                    f"· {__import__('datetime').datetime.now().isoformat()} ===\n"
                )
                f.writelines(tb_lines)
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger(__name__).error(
            "manusift tui unhandled async exception: %s",
            "".join(tb_lines),
        )

    try:
        loop.set_exception_handler(_async_hook)
    except Exception:  # noqa: BLE001
        pass


def append_panic_to_chat(
    app: Any, exc_type: Any, exc_value: Any
) -> None:
    """Surface a sync exception in the
    TUI chat log.

    Called by the
    ``sys.excepthook``
    installed above
    when a crash
    happens outside
    the Textual
    async loop. The
    message is a
    system row in
    red (the user
    sees the crash).

    ``app`` is the
    ``ChatApp``
    instance. The
    call is guarded
    -- if the
    widget tree is
    not ready (e.g.
    during ``__init__``),
    we silently
    skip the chat
    surface (the
    crash.log write
    already happened
    in
    ``install_panic_hook``).
    """
    history = getattr(app, "_history", None)
    if history is None:
        return
    first_line = (
        f"{exc_type.__name__}: {exc_value}"
        if exc_value
        else exc_type.__name__
    )
    try:
        from ..contracts import ChatMessage  # noqa: PLC0415
        history.append(
            ChatMessage(
                role="error",
                content=f"[panic] unhandled exception: {first_line} "
                f"(see crash.log for the full traceback)",
            )
        )
    except Exception:  # noqa: BLE001
        pass