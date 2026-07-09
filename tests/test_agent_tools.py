"""Tests for the 7 general-purpose agent tools
(R-audit 2026-06-10).

Closes the Claude Code /
OpenCode / Hermes tool-
gap. Seven tools:

  * ``web_search(query)``
  * ``web_fetch(url)``
  * ``bash(command)``
  * ``grep(pattern, path)``
  * ``glob(pattern, path)``
  * ``task(subagent_prompt)``
  * ``todo_write(items)``

Each tool has tests for
its basic happy path
plus the safety /
contract guarantees
(deny-list for bash,
size caps, pattern
validation, etc.).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. web_search (DuckDuckGo backend) ----------


def test_web_search_default_backend() -> None:
    """The default backend
    is DuckDuckGo (no API
    key required)."""
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.web_search_provider == "duckduckgo"


def test_web_search_duckduckgo_returns_results() -> None:
    """``web_search`` returns
    a JSON list of
    ``{title, url, snippet}``
    dicts when the DuckDuckGo
    backend is used.

    We allow the test to
    be skipped if the
    sandbox blocks outbound
    HTTP (some CI envs
    lock down egress)."""
    from manusift.tools.agent_tools import WebSearchTool
    from manusift.tools.tool import ToolContext

    tool = WebSearchTool()
    out = json.loads(
        tool.execute(
            {"query": "python", "max_results": 3},
            ToolContext(trace_id="t"),
        )
    )
    if not out.get("ok"):
        # Allow
        # skip
        # on
        # network
        # failure
        # (sandboxed
        # CI).
        import pytest
        pytest.skip(
            f"web_search not reachable: {out.get('error')!r}"
        )
    assert out["provider"] == "duckduckgo"
    results = out["results"]
    assert isinstance(results, list)
    if not results:
        import pytest
        pytest.skip("web_search returned no DuckDuckGo results")
    assert len(results) > 0
    assert "title" in results[0]
    assert "url" in results[0]
    assert "snippet" in results[0]


# ---------- 2. web_fetch ----------


def test_web_fetch_strips_html() -> None:
    """``web_fetch`` returns
    the page's plain text
    after stripping HTML
    tags."""
    from manusift.tools.agent_tools import WebFetchTool
    from manusift.tools.tool import ToolContext

    tool = WebFetchTool()
    out = json.loads(
        tool.execute(
            {"url": "https://example.com/"},
            ToolContext(trace_id="t"),
        )
    )
    if not out.get("ok"):
        import pytest
        pytest.skip(
            f"web_fetch not reachable: {out.get('error')!r}"
        )
    assert out["url"] == "https://example.com/"
    # ``example.com``
    # has
    # a
    # known
    # tagline.
    assert "Example" in out["text"] or "example" in out["text"].lower()
    # No
    # HTML
    # tags
    # leak.
    assert "<html" not in out["text"].lower()
    assert "<body" not in out["text"].lower()


def test_web_fetch_rejects_non_http_schemes() -> None:
    """``file://`` /
    ``ftp://`` / etc. are
    rejected."""
    from manusift.tools.agent_tools import WebFetchTool
    from manusift.tools.tool import ToolContext

    tool = WebFetchTool()
    out = json.loads(
        tool.execute(
            {"url": "file:///etc/passwd"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "unsupported scheme" in out["error"]


def test_web_fetch_strips_html_without_network(monkeypatch) -> None:
    """``web_fetch`` should strip HTML with its local stdlib path.

    The network smoke test above may skip on egress failures, so this
    pins the actual parser path without depending on example.com.
    """
    from manusift.tools.agent_tools import web_fetch as wf
    from manusift.tools.agent_tools import WebFetchTool
    from manusift.tools.tool import ToolContext

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n: int) -> bytes:
            return b"<html><script>bad()</script><body>Hello <b>world</b></body></html>"

    def fake_urlopen(req, timeout=15):
        return FakeResponse()

    monkeypatch.setattr(wf.urllib.request, "urlopen", fake_urlopen)

    out = json.loads(
        WebFetchTool().execute(
            {"url": "https://example.test/page"},
            ToolContext(trace_id="t"),
        )
    )

    assert out["ok"] is True
    assert out["text"] == "Hello world"


# ---------- 3. bash (with safety blocklist) ----------


def test_bash_runs_simple_command() -> None:
    """A simple command
    (e.g. ``echo hello``)
    runs and returns
    stdout / stderr /
    returncode."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "echo hello"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["returncode"] == 0
    assert "hello" in out["stdout"]
    assert out["stderr"] == ""


def test_bash_blocks_rm_rf_root() -> None:
    """``rm -rf /`` is
    blocked by the safety
    blocklist."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "rm -rf /"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    # R-2026-06-15 (Phase 1 + 3b):
    # the
    # new
    # classifier
    # uses
    # a
    # richer
    # error
    # message
    # (the
    # matched
    # rule
    # id
    # is
    # in
    # ``out["rule"]``).
    # We
    # accept
    # any
    # of:
    # the
    # new
    # reason
    # ("rm -rf on / or home")
    # OR
    # the
    # old
    # "blocked"
    # substring
    # (so
    # the
    # test
    # is
    # stable
    # across
    # the
    # denylist/classifier
    # migration).
    err_lower = out["error"].lower()
    assert (
        "blocked" in err_lower
        or "rm -rf" in err_lower
    )
    # The
    # classifier
    # also
    # returns
    # the
    # matched
    # rule
    # id
    # in
    # ``out["rule"]``
    # (a
    # new
    # field;
    # absent
    # in
    # the
    # old
    # denylist
    # path).
    assert out.get("rule", "").startswith("rm")


def test_bash_blocks_mkfs() -> None:
    """``mkfs`` is blocked
    (would wipe a disk)."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "mkfs.ext4 /dev/sda1"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False


def test_bash_blocks_dd_to_block_dev() -> None:
    """``dd of=/dev/sda`` is
    blocked."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "dd if=/dev/zero of=/dev/sda bs=1M"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False


def test_bash_blocks_fork_bomb() -> None:
    """The classic fork bomb
    is blocked."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {
                "command": ":() { :|:& };:",
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False


def test_bash_respects_cwd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cwd`` parameter
    switches the working
    directory for the
    command.

    R-2026-06-15 (Phase 1 + 3b):
    ``cd`` is a
    ``needs_confirm``
    command under the
    new classifier. We
    set
    ``MANUSIFT_ALLOW_NEEDS_CONFIRM=true``
    so the test can run
    the command (the
    classifier still
    returns a
    ``rule=posix.mutating``
    annotation in the
    success envelope so
    a future test can
    verify the
    classification is
    correct).
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.config import Settings
    from manusift.tools.tool import ToolContext

    if os.name != "nt":
        pytest.skip("cmd.exe cwd echo contract is Windows-only")
    monkeypatch.setenv(
        "MANUSIFT_ALLOW_NEEDS_CONFIRM", "true"
    )
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "cmd")
    ws_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        workspace_dir=tmp_path,  # type: ignore[arg-type]
    )
    import manusift.config as config_module
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: ws_settings,
    )
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {
                "command": "cd",
                "cwd": str(tmp_path),
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    # The Windows
    # ``cd``
    # returns
    # the
    # path
    # with
    # backslashes
    # (cmd.exe
    # default
    # since R-2026-06-14).
    assert (
        str(tmp_path) in out["stdout"]
        or str(tmp_path).replace("\\", "/") in out["stdout"].replace("\\", "/")
    )


def test_bash_rejects_relative_cwd() -> None:
    """Relative ``cwd`` paths
    are rejected (defence
    in depth: no cwd-
    relative traversal)."""
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext

    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "ls", "cwd": "relative/path"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "absolute" in out["error"]


def test_bash_can_be_disabled_via_settings() -> None:
    """``MANUSIFT_ALLOW_SHELL=false``
    disables the bash tool
    entirely."""
    import os as _os
    _os.environ["MANUSIFT_ALLOW_SHELL"] = "false"
    try:
        from manusift.config import get_settings
        if hasattr(get_settings, "cache_clear"):
            get_settings.cache_clear()
        from manusift.tools.agent_tools import BashTool
        from manusift.tools.tool import ToolContext
        tool = BashTool()
        out = json.loads(
            tool.execute(
                {"command": "echo hello"},
                ToolContext(trace_id="t"),
            )
        )
        assert out["ok"] is False
        assert "disabled" in out["error"].lower()
    finally:
        _os.environ.pop("MANUSIFT_ALLOW_SHELL", None)
        if hasattr(get_settings, "cache_clear"):
            get_settings.cache_clear()


# ---------- 4. grep ----------


def test_grep_finds_matches_in_text_files(tmp_path) -> None:
    """``grep`` finds
    occurrences of a
    pattern in text files
    under a directory."""
    from manusift.tools.agent_tools import GrepTool
    from manusift.tools.tool import ToolContext

    (tmp_path / "a.md").write_text(
        "Hello world\nThis is a test\nGoodbye world\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "Another file\nwith world in it\n",
        encoding="utf-8",
    )
    (tmp_path / "c.bin").write_bytes(b"\x00\x01\x02binary")

    tool = GrepTool()
    out = json.loads(
        tool.execute(
            {
                "pattern": "world",
                "path": str(tmp_path),
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    # 3
    # matches
    # across
    # 2
    # .md
    # files
    # (the
    # .bin
    # is
    # skipped
    # as
    # binary).
    assert out["match_count"] == 3
    files = {m["file"] for m in out["matches"]}
    assert any(f.endswith("a.md") for f in files)
    assert any(f.endswith("b.md") for f in files)
    # No
    # binary
    # file
    # in
    # the
    # matches.
    assert not any(f.endswith("c.bin") for f in files)


def test_grep_glob_filter(tmp_path) -> None:
    """``glob_filter``
    narrows the search to
    files matching the
    glob."""
    from manusift.tools.agent_tools import GrepTool
    from manusift.tools.tool import ToolContext

    (tmp_path / "a.md").write_text(
        "the pattern\n", encoding="utf-8"
    )
    (tmp_path / "b.txt").write_text(
        "the pattern\n", encoding="utf-8"
    )
    tool = GrepTool()
    out = json.loads(
        tool.execute(
            {
                "pattern": "the pattern",
                "path": str(tmp_path),
                "glob_filter": "*.md",
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["match_count"] == 1
    assert out["matches"][0]["file"].endswith("a.md")


def test_grep_rejects_relative_path() -> None:
    """Relative paths are
    rejected (defence in
    depth)."""
    from manusift.tools.agent_tools import GrepTool
    from manusift.tools.tool import ToolContext

    tool = GrepTool()
    out = json.loads(
        tool.execute(
            {"pattern": "foo", "path": "relative"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "absolute" in out["error"]


def test_grep_rejects_bad_regex() -> None:
    """A bad regex is
    reported, not
    silently swallowed."""
    from manusift.tools.agent_tools import GrepTool
    from manusift.tools.tool import ToolContext

    tool = GrepTool()
    out = json.loads(
        tool.execute(
            {"pattern": "[unclosed"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "regex" in out["error"].lower() or "bad" in out["error"].lower()


# ---------- 5. glob ----------


def test_glob_finds_matching_files(tmp_path) -> None:
    """``glob`` returns
    absolute paths of
    files matching a
    pattern."""
    from manusift.tools.agent_tools import GlobTool
    from manusift.tools.tool import ToolContext

    (tmp_path / "a.csv").write_text("h", encoding="utf-8")
    (tmp_path / "b.csv").write_text("h", encoding="utf-8")
    (tmp_path / "c.md").write_text("h", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.csv").write_text("h", encoding="utf-8")

    tool = GlobTool()
    out = json.loads(
        tool.execute(
            {"pattern": "**/*.csv", "path": str(tmp_path)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["count"] == 3
    # All
    # results
    # are
    # absolute
    # paths.
    for f in out["files"]:
        assert os.path.isabs(f)


def test_glob_no_match_returns_empty(tmp_path) -> None:
    """No matches returns
    an empty list (not an
    error)."""
    from manusift.tools.agent_tools import GlobTool
    from manusift.tools.tool import ToolContext

    tool = GlobTool()
    out = json.loads(
        tool.execute(
            {"pattern": "*.nonexistent", "path": str(tmp_path)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["files"] == []


# ---------- 6. todo_write ----------


def test_todo_write_validates_items() -> None:
    """``todo_write``
    validates each item
    and returns a summary."""
    from manusift.tools.agent_tools import TodoWriteTool
    from manusift.tools.tool import ToolContext

    tool = TodoWriteTool()
    out = json.loads(
        tool.execute(
            {
                "items": [
                    {
                        "content": "Read paper",
                        "status": "in_progress",
                    },
                    {
                        "content": "Run detectors",
                        "status": "pending",
                    },
                    {
                        "content": "Write report",
                        "status": "pending",
                    },
                ]
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["summary"]["total"] == 3
    assert out["summary"]["in_progress"] == 1
    assert out["summary"]["pending"] == 2
    assert out["summary"]["completed"] == 0


def test_todo_write_rejects_bad_status() -> None:
    """A bad status string
    is rejected."""
    from manusift.tools.agent_tools import TodoWriteTool
    from manusift.tools.tool import ToolContext

    tool = TodoWriteTool()
    out = json.loads(
        tool.execute(
            {
                "items": [
                    {
                        "content": "foo",
                        "status": "not-a-status",
                    }
                ]
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "status" in out["error"].lower()


def test_todo_write_rejects_missing_content() -> None:
    """Each item must
    have a non-empty
    ``content``."""
    from manusift.tools.agent_tools import TodoWriteTool
    from manusift.tools.tool import ToolContext

    tool = TodoWriteTool()
    out = json.loads(
        tool.execute(
            {"items": [{"status": "pending"}]},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False


# ---------- 7. task (subagent delegation) ----------


def test_task_delegates_to_subagent() -> None:
    """``task`` spawns a
    sub-agent and returns
    its final answer.
    Uses ``MockLLM`` so the
    test is offline."""
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.llm import MockLLM
    from manusift.tools import iter_registered_tools
    from manusift.tools.tool import ToolContext
    from manusift.tools.agent_tools import TaskTool

    # Override
    # the
    # LLM
    # client
    # to
    # MockLLM
    # for
    # the
    # duration
    # of
    # the
    # test.
    from manusift import llm
    original_get_client = llm.get_llm_client
    llm.get_llm_client = lambda *a, **k: MockLLM()
    try:
        tool = TaskTool()
        out = json.loads(
            tool.execute(
                {
                    "subagent_prompt": "say hello",
                    "isolated_context": True,
                },
                ToolContext(trace_id="t"),
            )
        )
        assert out["ok"] is True
        # MockLLM
        # echoes
        # the
        # user
        # message.
        assert "hello" in out["result"].lower()
    finally:
        llm.get_llm_client = original_get_client


# ---------- 8. All 7 tools are registered ----------


def test_all_seven_agent_tools_registered() -> None:
    """The 7 new agent tools
    are in the global
    registry."""
    from manusift.tools import iter_registered_tools

    names = {t.name for t in iter_registered_tools()}
    for n in (
        "web_search",
        "web_fetch",
        "bash",
        "grep",
        "glob",
        "task",
        "todo_write",
    ):
        assert n in names, f"missing {n!r}"
