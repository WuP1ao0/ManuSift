"""R-2026-06-21 (CDE-UI-P1.1):

Right Rail widget.

A 360px-wide panel on the right side of
the chat, showing 4 tabs:

1. **PDF** — info about the loaded
   PDF (pages, figures, tables).
   "no pdf loaded" if nothing
   uploaded.

2. **Finds** — detector findings
   (severity >= medium) from the
   current run. When the agent is
   not running, shows a hint.

3. **Tools** — recent tool entries
   from the current run (last 5).
   Same as the ToolTraceBlock in
   the chat log but persistent.

4. **Cost** — current session
   cost: tokens in / out, USD
   spent, % of cap (color-coded).

The widget is mounted once via
``ChatApp.compose`` and updated
via the ``_tick_live_elapsed``
1 Hz poller (which already updates
the bottom status bar).

Ponytail
ladder
notes:

* rung 1: user-
  visible state
  (PDF info,
  detector
  findings,
  recent tools,
  cost) was
  scattered
  across the
  bottom
  status bar --
  consolidating
  into a single
  side panel is
  the
  recommended
  fix (Hermes
  ``right-rail``
  reference).
* rung 4:
  ``TabbedContent``
  + ``TabPane``
  are Textual
  built-ins
  (widgets/
  _tabbed_content.py).
  No new
  framework.
* rung 5:
  this is the
  minimum
  implementation --
  one new file
  + 3 call-site
  additions
  (compose,
  BINDINGS,
  _tick_live_elapsed).
"""
from __future__ import annotations

from typing import Any

from textual.widgets import Static, TabbedContent, TabPane


class RightRail(TabbedContent):
    """R-2026-06-21 (CDE-UI-P1.1):
    Right-side panel with 4 tabs:
    PDF / Finds / Tools / Cost.
    """

    DEFAULT_CSS = """
    RightRail {
        width: 36;
        height: 1fr;
        background: #181825;
        border-left: heavy #313244;
        padding: 0 1;
    }
    RightRail > ContentSwitcher {
        height: 1fr;
    }
    RightRail .rail-tab-content {
        height: 1fr;
        padding: 0 1;
        color: #cdd6f4;
    }
    RightRail .rail-empty {
        color: #6c7086;
        text-style: italic;
        padding: 1 0;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Cache the inner Static widgets so we
        # can update them by ID without a
        # query (query_one is fine too but
        # less convenient when called every
        # second by ``_tick_live_elapsed``).
        self._pdf_static: Static | None = None
        self._finds_static: Static | None = None
        self._tools_static: Static | None = None
        self._cost_static: Static | None = None

    def compose(self) -> Any:
        """Yield the 4 tabs. Each tab has a
        single ``Static`` that the host
        ``ChatApp`` updates in place
        (``static.update(content)``).
        """
        with TabPane("PDF", id="rail-tab-pdf"):
            yield Static("no pdf loaded", classes="rail-tab-content", id="rail-pdf-content")
        with TabPane("Finds", id="rail-tab-finds"):
            yield Static(
                "(agent not running)",
                classes="rail-tab-content",
                id="rail-finds-content",
            )
        with TabPane("Tools", id="rail-tab-tools"):
            yield Static(
                "(no tool calls yet)",
                classes="rail-tab-content",
                id="rail-tools-content",
            )
        with TabPane("Cost", id="rail-tab-cost"):
            yield Static(
                "tokens in: 0\ntokens out: 0\ncost: $0.000",
                classes="rail-tab-content",
                id="rail-cost-content",
            )

    def on_mount(self) -> None:
        """Cache references to the inner
        ``Static`` widgets so updates are
        O(1) instead of ``query_one`` per
        tick.
        """
        try:
            self._pdf_static = self.query_one("#rail-pdf-content", Static)
            self._finds_static = self.query_one("#rail-finds-content", Static)
            self._tools_static = self.query_one("#rail-tools-content", Static)
            self._cost_static = self.query_one("#rail-cost-content", Static)
        except Exception:  # noqa: BLE001
            # ``on_mount`` may run before all
            # children are mounted in some
            # Textual versions. The first
            # ``_tick_live_elapsed`` tick will
            # retry via ``query_one``.
            pass

    # ------------------------------------------------------------------
    # Update methods (called by ``ChatApp._tick_live_elapsed`` 1 Hz poller)
    # ------------------------------------------------------------------

    def update_pdf(
        self,
        pdf_path: str | None,
        *,
        page_count: int | None = None,
        figure_count: int | None = None,
        table_count: int | None = None,
    ) -> None:
        """Update the PDF tab.

        ``pdf_path`` is the current
        ``_ctx.current_pdf`` (str or None).

        ``page_count`` / ``figure_count`` /
        ``table_count`` are optional. If
        not given, we only show the
        filename. When given, we show
        the full info block.
        """
        static = self._get_static("rail-pdf-content")
        if static is None:
            return
        if not pdf_path:
            static.update("[dim]no pdf loaded[/dim]")
            return
        # Show basename (the full path is in
        # ``_ctx.current_pdf`` if the user
        # wants to copy it).
        from pathlib import Path as _P
        try:
            name = _P(pdf_path).name
        except Exception:  # noqa: BLE001
            name = str(pdf_path)
        if page_count is None:
            static.update(f"[b]{name}[/b]\n[dim](detail not yet parsed)[/dim]")
            return
        static.update(
            f"[b]{name}[/b]\n"
            f"[cyan]{page_count}[/cyan] pages\n"
            f"[magenta]{figure_count or 0}[/magenta] figures\n"
            f"[yellow]{table_count or 0}[/yellow] tables"
        )

    def update_finds(
        self,
        findings: list[Any] | None,
    ) -> None:
        """Update the Finds tab.

        ``findings`` is a list of detector
        Finding objects (or None if agent
        is not running). Filters to
        ``severity >= medium`` and shows
        the first 20.
        """
        static = self._get_static("rail-finds-content")
        if static is None:
            return
        if not findings:
            static.update(
                "[dim](agent not running)[/dim]"
            )
            return
        visible = [
            f for f in findings
            if getattr(f, "severity", None) in ("medium", "high")
        ]
        if not visible:
            static.update(
                f"[green]no medium+ findings[/green] [dim]({len(findings)} total)[/dim]"
            )
            return
        lines: list[str] = [
            f"[b]{len(visible)} finding(s)[/b] [dim](medium+)[/dim]"
        ]
        for f in visible[:20]:
            sev = getattr(f, "severity", "?")
            detector = getattr(f, "detector", "?")
            title = getattr(f, "title", "")[:60]
            sev_color = "red" if sev == "high" else "yellow"
            lines.append(
                f" [{sev_color}]{sev[0].upper()}[/{sev_color}] "
                f"[b]{detector}[/b]: {title}"
            )
        if len(visible) > 20:
            lines.append(f"[dim]... and {len(visible) - 20} more[/dim]")
        static.update("\n".join(lines))

    def update_tools(self, tool_entries: list[Any] | None) -> None:
        """Update the Tools tab.

        ``tool_entries`` is the list of
        ``ToolEntry`` objects (most recent
        first or last -- we sort by
        insertion order either way).
        Shows up to 5 most recent.
        """
        static = self._get_static("rail-tools-content")
        if static is None:
            return
        if not tool_entries:
            static.update("[dim](no tool calls yet)[/dim]")
            return
        # Show the last 5 (most recent at the bottom).
        recent = tool_entries[-5:]
        lines: list[str] = [f"[b]{len(tool_entries)} total[/b]"]
        for entry in recent:
            name = getattr(entry, "name", "?")
            status = getattr(entry, "status", "?")
            ok = getattr(entry, "ok", None)
            color = (
                "green" if ok is True
                else "red" if ok is False
                else "yellow"
            )
            label = status if status != "ok" else "ok"
            lines.append(f" [{color}]{label[0].upper()}[/{color}] {name}")
        static.update("\n".join(lines))

    def update_cost(
        self,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        cap_usd: float = 0.0,
    ) -> None:
        """Update the Cost tab.

        ``cap_usd`` is the cost cap from
        ``MANUSIFT_AGENT_MAX_COST_USD``
        (0 = no cap). When cap is set,
        we show a percentage + color-code
        (green < 50%, yellow < 90%, red
        >= 90%).
        """
        static = self._get_static("rail-cost-content")
        if static is None:
            return
        lines = [
            f"[green]in  {tokens_in / 1000:.1f}k[/green] tokens",
            f"[yellow]out {tokens_out / 1000:.1f}k[/yellow] tokens",
            f"[magenta]${cost_usd:.3f}[/magenta] spent",
        ]
        if cap_usd > 0:
            pct = min(cost_usd / cap_usd, 1.0)
            if pct < 0.5:
                color = "green"
            elif pct < 0.9:
                color = "yellow"
            else:
                color = "red"
            lines.append(
                f"[{color}]${cost_usd:.3f} / ${cap_usd:.2f} "
                f"({pct * 100:.0f}%)[/{color}]"
            )
            # Mini progress bar
            bar_width = 20
            filled = int(pct * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            lines.append(f"[{color}]{bar}[/{color}]")
        else:
            lines.append("[dim](no cost cap set)[/dim]")
        static.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_static(self, sel_id: str) -> Static | None:
        """Look up an inner Static by ID.

        ``on_mount`` caches the references
        but if a query fails (e.g. the
        user called this before mount)
        we re-query here.
        """
        attr_name = f"_{sel_id.replace('-', '_').replace('rail_', '')}_static"
        # Fall through to a direct query for
        # any attr that doesn't match the
        # cached pattern.
        for cached_id, attr in (
            ("rail-pdf-content", "_pdf_static"),
            ("rail-finds-content", "_finds_static"),
            ("rail-tools-content", "_tools_static"),
            ("rail-cost-content", "_cost_static"),
        ):
            if cached_id == sel_id:
                cached = getattr(self, attr, None)
                if cached is not None:
                    return cached
                # Fall back to live query.
                try:
                    return self.query_one(f"#{sel_id}", Static)
                except Exception:  # noqa: BLE001
                    return None
        return None