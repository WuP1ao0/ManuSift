"""Textual-pilot TUI snapshot script.

We cannot use Playwright on
this machine because the
bundled Chromium download
times out and the CDN that
serves xterm.js is blocked
by the local network. The
text-dump approach is
sufficient: textual's
``Pilot`` runs the app
headless, the
``_compositor`` renders
the screen on every
event, and we capture the
rendered text into a file
the LLM can read.

The output is a text file
under ``docs/screenshots/``
named ``NN_kind_payload.txt``
where ``NN`` is a sequence
number.

Usage:
    python tests/visual_tui_shoot.py [step=type:hello] ...
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

SCREENSHOT_DIR = Path(r"C:/Users/22509/Desktop/ManuSift1/docs/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def shoot_text(label: str, text: str) -> Path:
    """Save a text snapshot of the TUI."""
    path = SCREENSHOT_DIR / f"{label}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"  saved {path}", flush=True)
    return path


async def capture_initial() -> str:
    """Run the TUI for 0.5
    seconds and capture the
    rendered screen."""
    from manusift.tui.chat_app import ChatApp
    from rich.console import Console
    app = ChatApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.5)
        c = Console(
            width=100,
            record=True,
            color_system="truecolor",
            force_terminal=True,
        )
        try:
            content = (
                pilot.app.screen._compositor.render_update(
                    pilot.app.screen._compositor.full_map
                )
            )
            c.print(content)
        except Exception as exc:
            return f"render failed: {exc}"
        return c.export_text(clear=False, styles=False)


async def capture_after_type(text_to_type: str) -> str:
    """Type a string into the
    TUI input and capture
    the resulting screen."""
    from manusift.tui.chat_app import ChatApp
    from rich.console import Console
    from textual.widgets import Input, TextArea
    app = ChatApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        try:
            inp = pilot.app.query_one("#input", TextArea)
            inp.text = text_to_type
            await pilot.press("ctrl+j")
            await pilot.pause(0.4)
        except Exception as exc:
            return f"interaction failed: {exc}"
        c = Console(
            width=100,
            record=True,
            color_system="truecolor",
            force_terminal=True,
        )
        try:
            content = (
                pilot.app.screen._compositor.render_update(
                    pilot.app.screen._compositor.full_map
                )
            )
            c.print(content)
        except Exception as exc:
            return f"render failed: {exc}"
        return c.export_text(clear=False, styles=False)


async def run(steps: list[tuple[str, str]]) -> None:
    text = await capture_initial()
    shoot_text("00_initial", text)
    for i, (kind, payload) in enumerate(steps, start=1):
        label = f"{i:02d}_{kind}_{payload[:24]}"
        if kind == "type":
            text = await capture_after_type(payload)
        elif kind == "screenshot":
            text = await capture_initial()
        else:
            print(f"unknown kind: {kind}", file=sys.stderr)
            continue
        shoot_text(label, text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("steps", nargs="*", default=[])
    args = parser.parse_args()
    parsed: list[tuple[str, str]] = []
    for raw in args.steps:
        if ":" in raw:
            kind, payload = raw.split(":", 1)
        else:
            kind, payload = raw, ""
        parsed.append((kind, payload))
    asyncio.run(run(parsed))


if __name__ == "__main__":
    main()
