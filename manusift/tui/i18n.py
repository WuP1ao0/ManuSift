"""TUI i18n (R-2026-06-14).

Lightweight English/Chinese string lookup for the chat
TUI. Every user-facing string that is not LLM-generated
content (i.e. status bar, tool trace block, debug drawer,
slash-command output) goes through ``t()``.

Design choices
==============

  * **Default = English**. The LLM is a global tool; we
    do not assume the user is Chinese-speaking.
  * **Switch via env var** ``MANUSIFT_LANG=zh``. Set in
    the user's shell or the TUI's startup script. Tests
    that need Chinese call ``set_lang("zh")`` directly.
  * **No gettext / .mo files**. The translation table is
    a small dict (under 60 strings) and the user is
    either a developer (English OK) or a Chinese
    speaker (Chinese is the only non-English locale for
    now). Adding gettext would be premature.
  * **Format args use named placeholders** so the same
    key works in both languages (e.g. ``"cost so far"``
    becomes ``"累计: ↑ {n_in} 入, ↓ {n_out} 出, ${cost} USD"``).
  * **Fallback to English** if a key is missing in the
    active locale -- the UI must never crash because of
    a missing translation.
  * **Stable, well-known keys**. Keys are lowercase
    snake_case and form a closed set. Adding a new key
    is a deliberate, code-reviewed act.

What is NOT in scope
=====================

  * The system prompt's English text. The LLM reads
    English; translating the system prompt would change
    the agent's behaviour. Users get Chinese TUI chrome
    and English LLM responses -- the same split Claude
    Code uses.
  * The Markdown report body. The ``render_report`` tool
    has its own ``language`` parameter (en / zh) that
    produces ``report.md`` vs ``report.zh.md`` -- that is
    a separate i18n layer for the report renderer.
  * Slash command help text. Commands like ``/help``,
    ``/cost`` are developer-facing; English is fine.

Usage
=====

::

    from .i18n import t
    self._set_status(t("ready"))
    self._set_status(
        t("calling_tool", name="ingest_from_path")
    )
"""

from __future__ import annotations

import os
from threading import Lock

# --------------------------------------------------------------------
# Locale tables
# --------------------------------------------------------------------

# English is the source of truth -- every key is present
# here. The Chinese table is a partial override; missing
# keys fall back to English.
_EN: dict[str, str] = {
    # --- status bar ---
    "ready": "ready",
    "thinking": "thinking\u2026",
    "calling_tool": "calling {name}\u2026",
    "generation_cancelled": "\u25cb generation cancelled",
    "agent_finished": "agent finished ({stopped})",
    "agent_finished_cost_cap": (
        "\u25cf agent finished "
        "(cost cap reached, "
        "see MANUSIFT_AGENT_MAX_COST_USD)"
    ),
    "agent_finished_max_steps": (
        "\u25cb agent finished "
        "(hit step cap at {stopped})"
    ),
    "agent_finished_crashed": (
        "ready (crashed)"
    ),
    "agent_crashed": "agent crashed: {err}",
    "agent_still_running": (
        "agent is still running; "
        "press Esc to cancel"
    ),
    "queued_pending": (
        "queued ({n} pending) -- the agent will pick "
        "this up when the current turn finishes. "
        "Press Esc to cancel."
    ),
    "debug_drawer_on": (
        "\u25c6 debug drawer: ON (raw tool args/results)"
    ),
    "debug_drawer_off": (
        "\u25c7 debug drawer: OFF (press d to open)"
    ),
    # --- ToolTraceBlock summary ---
    "tools_summary": "  \u25cf tools {n} call{s}",
    "tools_ok": " \u00b7 {n} ok",
    "tools_skipped": " \u00b7 {n} skipped",
    "tools_error": " \u00b7 {n} error",
    "tools_running": " \u00b7 running\u2026",
    "tools_thinking": "  \u25cf thinking\u2026",
    "tool_status_skipped": "skipped: {msg}",
    "tool_status_error": "error: {msg}",
    # --- /cost and /status slash commands ---
    "cost_so_far": (
        "cost so far: \u2191 {n_in} input tokens, "
        "\u2193 {n_out} output tokens, ${cost:.4f} USD"
    ),
    "status_session": "session: {sid}",
    "status_workspace": "workspace: {ws}",
    "status_llm": "llm: {llm}",
    "status_pdf": "pdf: {pdf}",
    "status_plan_mode": "plan mode: {flag}",
    "status_history": "history: {n} message{s}",
    # --- DetectorTraceBlock summary ---
    "detectors_summary_running": (
        "detectors {running}/{total} running"
    ),
    "detectors_summary_done": (
        "detectors {done}/{total} done"
    ),
    "detectors_summary_final": (
        "detectors {done}/{total} done "
        "\u00b7 {findings} findings "
        "\u00b7 {skipped} skipped "
        "\u00b7 {errors} errors"
    ),
    # --- phase labels (used in detector trace) ---
    "phase_extracting_pdf": "extracting PDF",
    "phase_running_detectors": "running detectors",
    "phase_generating_report": "generating report",
}

_ZH: dict[str, str] = {
    # --- status bar ---
    "ready": "\u5c31\u7eea",
    "thinking": "\u601d\u8003\u4e2d\u2026",
    "calling_tool": "\u8c03\u7528 {name} \u4e2d\u2026",
    "generation_cancelled": "\u25cb \u5df2\u53d6\u6d88\u751f\u6210",
    "agent_finished": "\u4ee3\u7406\u5b8c\u6210 ({stopped})",
    "agent_finished_cost_cap": (
        "\u25cf \u4ee3\u7406\u5b8c\u6210\uff08"
        "\u8d85\u51fa\u6210\u672c\u4e0a\u9650\uff0c"
        "\u8bf7\u53c2\u8003 MANUSIFT_AGENT_MAX_COST_USD\uff09"
    ),
    "agent_finished_max_steps": (
        "\u25cb \u4ee3\u7406\u5b8c\u6210\uff08"
        "\u8fbe\u5230\u6b65\u9aa4\u4e0a\u9650\uff09"
    ),
    "agent_finished_crashed": (
        "\u5c31\u7eea\uff08\u5d29\u6e83\uff09"
    ),
    "agent_crashed": "\u4ee3\u7406\u5d29\u6e83\uff1a{err}",
    "agent_still_running": (
        "\u4ee3\u7406\u8fd8\u5728\u8fd0\u884c\uff0c"
        "\u8bf7\u6309 Esc \u53d6\u6d88"
    ),
    "queued_pending": (
        "\u5df2\u8fdb\u5165\u961f\u5217\uff08\u5176\u4e2d {n} \u6761\u5f85\u5904\u7406\uff09\u2014\u2014"
        "\u4ee3\u7406\u4f1a\u5728\u5f53\u524d\u8f6e\u5b8c\u6210\u540e\u5904\u7406\u3002"
        "\u8bf7\u6309 Esc \u53d6\u6d88\u3002"
    ),
    "debug_drawer_on": (
        "\u25c6 \u8c03\u8bd5\u7a97\u53e3\uff1a\u5f00\uff08\u663e\u793a\u539f\u59cb\u5de5\u5177\u8c03\u7528/\u8fd4\u56de\uff09"
    ),
    "debug_drawer_off": (
        "\u25c7 \u8c03\u8bd5\u7a97\u53e3\uff1a\u5173\uff08\u6309 d \u6253\u5f00\uff09"
    ),
    # --- ToolTraceBlock summary ---
    "tools_summary": "  \u25cf \u5de5\u5177 {n} \u6b21\u8c03\u7528",
    "tools_ok": " \u00b7 \u6210\u529f {n}",
    "tools_skipped": " \u00b7 \u8df3\u8fc7 {n}",
    "tools_error": " \u00b7 \u9519\u8bef {n}",
    "tools_running": " \u00b7 \u8fd0\u884c\u4e2d\u2026",
    "tools_thinking": "  \u25cf \u601d\u8003\u4e2d\u2026",
    "tool_status_skipped": "\u8df3\u8fc7\uff1a{msg}",
    "tool_status_error": "\u9519\u8bef\uff1a{msg}",
    # --- /cost and /status slash commands ---
    "cost_so_far": (
        "\u7d2f\u8ba1\u6210\u672c\uff1a\u2191 {n_in} \u8f93\u5165 token\uff0c"
        "\u2193 {n_out} \u8f93\u51fa token\uff0c${cost:.4f} \u7f8e\u5143"
    ),
    "status_session": "\u4f1a\u8bdd\uff1a{sid}",
    "status_workspace": "\u5de5\u4f5c\u76ee\u5f55\uff1a{ws}",
    "status_llm": "\u6a21\u578b\uff1a{llm}",
    "status_pdf": "\u8bba\u6587\u6587\u4ef6\uff1a{pdf}",
    "status_plan_mode": "\u8ba1\u5212\u6a21\u5f0f\uff1a{flag}",
    "status_history": "\u5386\u53f2\u8bb0\u5f55\uff1a{n} \u6761",
    # --- DetectorTraceBlock summary ---
    "detectors_summary_running": (
        "detector {running}/{total} \u8fd0\u884c\u4e2d"
    ),
    "detectors_summary_done": (
        "detector {done}/{total} \u5b8c\u6210"
    ),
    "detectors_summary_final": (
        "detector {done}/{total} \u5b8c\u6210"
        "\u00b7 {findings} \u4e2a\u53d1\u73b0"
        "\u00b7 {skipped} \u4e2a\u8df3\u8fc7"
        "\u00b7 {errors} \u4e2a\u9519\u8bef"
    ),
    # --- phase labels ---
    "phase_extracting_pdf": "\u63d0\u53d6 PDF",
    "phase_running_detectors": "\u8fd0\u884c\u68c0\u6d4b\u5668",
    "phase_generating_report": "\u751f\u6210\u62a5\u544a",
}

#: All supported locales. Tests inspect this set.
SUPPORTED_LANGS = frozenset({"en", "zh"})

# --------------------------------------------------------------------
# Runtime language + lookup
# --------------------------------------------------------------------

_state_lock = Lock()
_active_lang: str = "en"


def _detect_initial_lang() -> str:
    """Read ``MANUSIFT_LANG`` once at import time. The
    user can override later via :func:`set_lang`."""
    val = os.environ.get("MANUSIFT_LANG", "").strip().lower()
    if val in SUPPORTED_LANGS:
        return val
    return "en"


_active_lang = _detect_initial_lang()


def get_lang() -> str:
    """Return the active locale code (``"en"`` or
    ``"zh"``)."""
    with _state_lock:
        return _active_lang


def set_lang(lang: str) -> None:
    """Set the active locale. ``"en"`` and ``"zh"`` are
    supported; anything else is silently ignored (the
    UI must never crash because of a bad env var)."""
    lang = (lang or "").strip().lower()
    if lang not in SUPPORTED_LANGS:
        return
    global _active_lang
    with _state_lock:
        _active_lang = lang


def reset_for_tests() -> None:
    """Reset the active locale to whatever the env var
    says (or English). Tests call this in setup."""
    global _active_lang
    with _state_lock:
        _active_lang = _detect_initial_lang()


def t(key: str, /, **kwargs: object) -> str:
    """Translate ``key`` and apply ``**kwargs`` formatting.

    Falls back to English if the key is missing in the
    active locale, and to the literal key if it is
    missing in BOTH locales -- so a missing translation
    is always visible (a dev can grep the UI for
    ``"tool_status_skipped"`` and find the untranslated
    spot).
    """
    with _state_lock:
        lang = _active_lang
    table = _ZH if lang == "zh" else _EN
    template = table.get(key) or _EN.get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        # The translation is missing a placeholder. Return
        # the raw template so the dev sees the problem
        # rather than getting a KeyError at runtime.
        return template
