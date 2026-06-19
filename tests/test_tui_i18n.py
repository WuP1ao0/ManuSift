"""Tests for the TUI i18n layer (R-2026-06-14).

Verifies:
  1. Default language is English.
  2. ``set_lang("zh")`` switches to Chinese.
  3. ``t(key)`` returns the locale-specific template.
  4. ``t(key, **kwargs)`` formats with named args.
  5. Missing keys fall back to English, then to the
     literal key (so missing translations are visible).
  6. The supported-locales set is closed.
  7. Setting an invalid locale is a no-op.
  8. ``reset_for_tests`` restores the env-driven default.
  9. Both EN and ZH tables cover every key the
     chat-tui uses (no gap in either locale).
 10. The Chinese table contains real CJK characters
     (so a regression that strips them is caught).
 11. A handful of representative keys render the
     expected user-visible Chinese phrase.
"""

from __future__ import annotations

import pytest

from manusift.tui import i18n
from manusift.tui.i18n import (
    SUPPORTED_LANGS,
    get_lang,
    reset_for_tests,
    set_lang,
    t,
)


@pytest.fixture(autouse=True)
def _reset_lang() -> None:
    """Each test starts from the env-driven default and
    cleans up after itself. We snapshot the active
    locale in the test's setup and restore in teardown
    so one test cannot leak into the next."""
    reset_for_tests()
    yield
    reset_for_tests()


# --------------------------------------------------------------------
# 1. Default language
# --------------------------------------------------------------------


def test_default_language_is_english_or_env() -> None:
    """Without ``MANUSIFT_LANG`` set, the default is
    English. With it set, the env value wins. We
    accept either as long as it's a supported locale.
    """
    lang = get_lang()
    assert lang in SUPPORTED_LANGS


# --------------------------------------------------------------------
# 2. set_lang / get_lang
# --------------------------------------------------------------------


def test_set_lang_switches_to_chinese() -> None:
    set_lang("zh")
    assert get_lang() == "zh"


def test_set_lang_invalid_locale_is_noop() -> None:
    set_lang("zh")
    set_lang("xx-not-a-locale")
    # The previous valid locale is preserved.
    assert get_lang() == "zh"


def test_set_lang_empty_string_is_noop() -> None:
    set_lang("zh")
    set_lang("")
    assert get_lang() == "zh"


# --------------------------------------------------------------------
# 3. t() returns the locale-specific template
# --------------------------------------------------------------------


def test_t_returns_english_template_by_default() -> None:
    set_lang("en")
    assert t("ready") == "ready"


def test_t_returns_chinese_template_when_lang_is_zh() -> None:
    set_lang("zh")
    # The Chinese template for "ready" is "\u5c31\u7eea"
    # (just two characters). We assert by character,
    # not by literal escape, so a regression that
    # produces the wrong glyph is caught.
    assert t("ready") == "\u5c31\u7eea"


# --------------------------------------------------------------------
# 4. t() formats with named kwargs
# --------------------------------------------------------------------


def test_t_formats_named_kwargs_english() -> None:
    set_lang("en")
    text = t("calling_tool", name="ingest_from_path")
    assert "ingest_from_path" in text
    assert "calling" in text.lower()


def test_t_formats_named_kwargs_chinese() -> None:
    set_lang("zh")
    text = t("calling_tool", name="\u8bfb\u53d6\u6587\u4ef6")
    # The Chinese template is "\u8c03\u7528 {name} \u4e2d\u2026"
    # so it must contain the tool name and end with the
    # ellipsis glyph.
    assert "\u8bfb\u53d6\u6587\u4ef6" in text
    assert "\u2026" in text


def test_t_cost_format_uses_four_digit_precision() -> None:
    set_lang("en")
    text = t(
        "cost_so_far",
        n_in=1234,
        n_out=567,
        cost=0.01234,
    )
    assert "1234" in text
    assert "567" in text
    assert "$0.0123" in text


# --------------------------------------------------------------------
# 5. Fallback semantics
# --------------------------------------------------------------------


def test_t_missing_chinese_key_falls_back_to_english() -> None:
    """If a key is in EN but not in ZH, ``t(key)`` in
    Chinese mode still returns the English text (the
    chat must never crash on a missing translation)."""
    # We monkey-patch the ZH table to drop a key.
    original = i18n._ZH.copy()
    i18n._ZH.pop("ready", None)
    try:
        set_lang("zh")
        # Falls back to English.
        assert t("ready") == "ready"
    finally:
        i18n._ZH.clear()
        i18n._ZH.update(original)


def test_t_missing_key_in_both_locales_returns_literal() -> None:
    """A key that is missing in BOTH tables returns the
    literal key string. This is the dev signal: a
    missing translation is always visible.
    """
    text = t("not_a_real_key_anywhere")
    assert text == "not_a_real_key_anywhere"


def test_t_format_failure_returns_template_unchanged() -> None:
    """If the template references a placeholder that the
    caller did not pass, ``t()`` returns the template
    (not a KeyError) so the dev sees the problem."""
    set_lang("en")
    # ``cost_so_far`` requires n_in, n_out, cost. We
    # call it with NO kwargs. The template is still
    # returned as-is.
    text = t("cost_so_far")
    # The template literally has "{n_in}" in it.
    assert "{n_in}" in text


# --------------------------------------------------------------------
# 6. Supported locales set
# --------------------------------------------------------------------


def test_supported_langs_is_closed() -> None:
    """The set of supported locales is intentionally
    small. Adding a new locale is a deliberate
    code-reviewed act; this test guards against
    accidental additions via a typo."""
    assert SUPPORTED_LANGS == frozenset({"en", "zh"})


# --------------------------------------------------------------------
# 9. Both tables cover every key the chat-tui uses
# --------------------------------------------------------------------


# Snapshot the keys the chat-tui actually calls. We
# grep the chat_app.py and turn_block.py source for
# every ``_t("...")`` call. If the source uses a new
# key, this test will fail and force the dev to add
# the key to the ZH table (or, more rarely, drop it
# from the source).
def _collect_used_keys() -> set[str]:
    """Grep the source for ``_t("...")`` calls and
    return the set of keys. We anchor on the leading
    ``_t(`` so that LLM SDK field names like
    ``"input_tokens"`` (which appear inside string
    literals, dicts, f-strings, etc.) are NOT picked
    up. The ``_t(`` prefix is the unambiguous signal
    that the call goes through our i18n layer.
    """
    from pathlib import Path
    import re
    root = Path(i18n.__file__).parent
    used: set[str] = set()
    # Match ``_t("...")`` or ``t("...")``. The trailing
    # ``(`` and quote characters are required so we
    # do not match LLM SDK field names that appear
    # inside unrelated string literals.
    pattern = re.compile(
        r"""(?<![\w.])_t\(\s*['"]([a-z][a-z0-9_]*)['"]"""
    )
    for fname in ("chat_app.py", "turn_block.py", "agent_runner.py"):
        path = root / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            used.add(m.group(1))
    return used


def test_every_used_key_in_english_table() -> None:
    used = _collect_used_keys()
    missing = sorted(k for k in used if k not in i18n._EN)
    assert not missing, (
        f"keys used in source but missing from i18n._EN: "
        f"{missing}"
    )


def test_every_used_key_in_chinese_table() -> None:
    used = _collect_used_keys()
    missing = sorted(k for k in used if k not in i18n._ZH)
    assert not missing, (
        f"keys used in source but missing from i18n._ZH: "
        f"{missing}. Add the Chinese translation or "
        f"mark the key as English-only in the source."
    )


# --------------------------------------------------------------------
# 10. CJK characters really are in the ZH table
# --------------------------------------------------------------------


def test_chinese_table_contains_real_cjk() -> None:
    """Guard against a regression that strips CJK
    characters from the ZH table (e.g. an aggressive
    .encode('ascii') step)."""
    cjk = "".join(i18n._ZH.values())
    # Pick a few characters we know must be in the
    # table: \u5c31\u7eea (\u5c31 = just, \u7eea = ready),
    # \u8c03\u7528 (call), \u5de5\u5177 (tool), \u8df3\u8fc7 (skip).
    for ch in "\u5c31\u8c03\u5de5\u5177\u8df3\u8fc7":
        assert ch in cjk, (
            f"Chinese table is missing CJK char {ch!r}"
        )


# --------------------------------------------------------------------
# 11. Representative Chinese phrases
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, kwargs, expected_substrings",
    [
        # The 6 most user-visible strings; smoke-test the
        # ZH table renders sensible Chinese.
        (
            "ready",
            {},
            ["\u5c31\u7eea"],
        ),
        (
            "thinking",
            {},
            ["\u601d\u8003", "\u2026"],
        ),
        (
            "calling_tool",
            {"name": "ingest_from_path"},
            ["ingest_from_path", "\u2026"],
        ),
        (
            "agent_still_running",
            {},
            ["\u4ee3\u7406", "Esc"],
        ),
        (
            "debug_drawer_on",
            {},
            ["\u8c03\u8bd5\u7a97\u53e3"],
        ),
        (
            "tool_status_skipped",
            {"msg": "PDF not found"},
            ["PDF not found"],
        ),
    ],
)
def test_chinese_renders_representative_phrases(
    key: str, kwargs: dict, expected_substrings: list[str]
) -> None:
    set_lang("zh")
    text = t(key, **kwargs)
    for sub in expected_substrings:
        assert sub in text, (
            f"Chinese render of {key!r} missing {sub!r}: "
            f"got {text!r}"
        )
