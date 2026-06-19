"""Async / loading widgets for the TUI (R-audit 2026-06-10).

Background: the previous
TUI was synchronous --
``_run_agent`` blocked
the main event loop for
the full duration of the
LLM call (sometimes 30s
for a thinking model).
The user could not type,
could not scroll, could
not press Ctrl-C. This
module introduces the
non-blocking loading
indicators and the
non-blocking worker
plumbing that the TUI's
``_run_agent`` uses.

Two widgets are
provided:

  1. ``PulsatingDots`` --
     a textual ``Static``
     that auto-rotates
     between three dot
     patterns every
     ``~150ms`` (GPT-style).
     Suitable for a
     single LLM turn that
     has not yet produced
     any text.

  2. ``PhaseSpinner`` --
     a textual ``Static``
     that combines the
     Braille-dot spinner
     glyph (``⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏``)
     with a phase label
     that the TUI updates
     as the LLM calls
     each tool (e.g.
     "Reading manuscript",
     "Verifying
     references"). The
     spinner advances
     every 80ms via
     ``set_interval`` and
     the phase label is
     updated by
     ``set_phase``.

Both widgets have a
``stop()`` method that
cancels their auto-update
intervals. The TUI calls
``stop()`` when the
real LLM response starts
streaming or when the
user cancels, and
``set_interval`` /
``update`` are no longer
fired after ``stop()``.

The user can press ``Esc``
or ``Ctrl+C`` to cancel
the running LLM. The
``PhaseSpinner.stop()``
method also flips an
``is_cancelled`` flag
the worker can poll to
short-circuit further
tool calls.
"""
from __future__ import annotations

import asyncio
from typing import Any

from textual.widgets import Static


# 10-frame Braille-dot
# spinner. We rotate
# through these on each
# tick.
_BRAILLE_FRAMES: tuple[str, ...] = (
    "\u280b",  # ⠋
    "\u2819",  # ⠙
    "\u2839",  # ⠹
    "\u2838",  # ⠸
    "\u283c",  # ⠼
    "\u2834",  # ⠴
    "\u2826",  # ⠦
    "\u2827",  # ⠧
    "\u2807",  # ⠇
    "\u280f",  # ⠏
)

# 3-frame dot pattern
# for the casual
# "thinking" indicator.
_DOT_FRAMES: tuple[str, ...] = (
    "\u25cf \u25cb \u25cb",  # ● ○ ○
    "\u25cb \u25cf \u25cb",  # ○ ● ○
    "\u25cb \u25cb \u25cf",  # ○ ○ ●
)


class PulsatingDots(Static):
    """GPT-style "ManuSift is
    thinking  ● ○ ○" indicator
    that rotates between the
    three dot patterns.

    The widget is a
    textual ``Static`` with
    ``markup=False`` (the
    text is the literal
    unicode dot
    characters). It owns a
    single ``set_interval``
    that fires every
    ``interval_ms``
    milliseconds. The
    ``stop()`` method
    cancels the interval
    and the widget no
    longer updates.
    """

    DEFAULT_CSS = """
    PulsatingDots {
        height: 1;
        color: #cba6f7;
        text-style: bold;
    }
    """

    def __init__(
        self,
        label: str = "ManuSift is thinking",
        interval_ms: int = 150,
        id: str | None = None,
    ) -> None:
        super().__init__(
            f"{label}  \u25cf \u25cb \u25cb",
            id=id,
        )
        self._label = label
        self._frame_idx = 0
        self._interval_ms = interval_ms
        self._interval = None
        self._stopped = False

    def on_mount(self) -> None:
        """Start the dot
        rotation when the
        widget is mounted."""
        self._interval = self.set_interval(
            self._interval_ms / 1000.0,
            self._advance,
        )

    def _advance(self) -> None:
        """Advance to the next
        frame and update the
        rendered text."""
        if self._stopped:
            return
        self._frame_idx = (self._frame_idx + 1) % len(
            _DOT_FRAMES
        )
        self.update(
            f"{self._label}  {_DOT_FRAMES[self._frame_idx]}"
        )

    def stop(self) -> None:
        """Stop the
        auto-rotation. Safe
        to call multiple
        times."""
        self._stopped = True
        if self._interval is not None:
            self._interval.stop()
            self._interval = None

    def set_label(self, label: str) -> None:
        """Update the
        displayed label (the
        'ManuSift is
        thinking' part)."""
        self._label = label
        self._advance()


class PhaseSpinner(Static):
    """A spinner that
    combines a rotating
    Braille-dot glyph
    with a phase label.

    The TUI updates the
    phase via
    ``set_phase("Reading
    manuscript")`` as the
    LLM calls each tool.
    The glyph advances
    every 80ms so the user
    can see that the
    process is alive even
    if no phase update has
    arrived in a while.
    """

    DEFAULT_CSS = """
    PhaseSpinner {
        height: 1;
        color: #cba6f7;
        text-style: bold;
    }
    """

    def __init__(
        self,
        phase: str = "thinking",
        interval_ms: int = 80,
        id: str | None = None,
    ) -> None:
        super().__init__(
            f"{_BRAILLE_FRAMES[0]} {phase}",
            id=id,
        )
        self._phase = phase
        self._frame_idx = 0
        self._interval_ms = interval_ms
        self._interval = None
        self._stopped = False
        self.is_cancelled: bool = False

    def on_mount(self) -> None:
        self._interval = self.set_interval(
            self._interval_ms / 1000.0,
            self._advance,
        )

    def _advance(self) -> None:
        if self._stopped:
            return
        self._frame_idx = (self._frame_idx + 1) % len(
            _BRAILLE_FRAMES
        )
        self.update(
            f"{_BRAILLE_FRAMES[self._frame_idx]} {self._phase}"
        )

    def set_phase(self, phase: str) -> None:
        """Update the phase
        label."""
        self._phase = phase
        self.update(
            f"{_BRAILLE_FRAMES[self._frame_idx]} {phase}"
        )

    def stop(self) -> None:
        """Stop the
        auto-rotation."""
        self._stopped = True
        if self._interval is not None:
            self._interval.stop()
            self._interval = None

    def cancel(self) -> None:
        """Mark the spinner
        as cancelled (the
        TUI worker can poll
        this to abort the
        in-flight LLM
        call)."""
        self.is_cancelled = True
        self.set_phase("cancelled")
        self.stop()
