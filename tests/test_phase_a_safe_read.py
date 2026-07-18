"""R-2026-06-17 (Phase A:
borrow from
Claude Code +
Hermes):
8 small
``read_file``
hardening
modules in
``manusift/tools/safe_read.py``,
all wired into
``ReadFileTool.execute``
(``manusift/tools/direct_fs.py``).

Each test below
asserts ONE
specific guard
fires, in the
order the guards
are applied in
``ReadFileTool.execute``.
The order is:

    A-3  expand ``~``
    A-1  blocked device
    A-4  ``/proc`` secret
    is_absolute check
    exists check
    is_dir check
    A-7  protected-dir hint (read still allowed)
    A-2  binary extension pre-block
    A-8  structured document extraction (try before text-read)
    size cap
    utf-8 read
    A-6  BOM strip
    A-5  char-limit guard (after truncation)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manusift.tools.safe_read import (
    DEFAULT_READ_CHAR_LIMIT,
    enforce_char_limit,
    expand_user_path,
    has_binary_extension,
    is_blocked_device,
    is_extractable_document,
    is_proc_secret_path,
    is_protected_dir,
    strip_utf8_bom,
    try_extract_document,
)
from manusift.tools.direct_fs import ReadFileTool
from manusift.tools.tool import ToolContext


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Redirect MANUSIFT_WORKSPACE_DIR to tmp_path so direct_fs is happy."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def ctx():
    return ToolContext(trace_id="test_trace", current_pdf=None, metadata={})


@pytest.fixture
def read_file_tool():
    return ReadFileTool()


# ============================================================================
# A-3: ~ / ~user expansion (pure function, no IO)
# ============================================================================


class TestExpandUserPath:
    def test_tilde_alone(self):
        assert expand_user_path("~", home="/home/alice") == "/home/alice"

    def test_tilde_slash(self):
        # ``Path(home) / suffix`` normalises the
        # separator to the platform-native one
        # (``\`` on Windows, ``/`` elsewhere).
        # The user-facing semantic is "joined path"
        # so the test uses ``Path()`` to compare.
        from pathlib import Path
        assert (
            Path(expand_user_path("~/notes.md", home="/home/alice"))
            == Path("/home/alice/notes.md")
        )

    def test_tilde_user(self):
        # ``~bob`` is only expanded
        # if the platform
        # supports it. On
        # Linux/macOS this
        # requires ``pwd``
        # to have the user.
        # We just test the
        # username regex
        # gate here.
        result = expand_user_path(
            "~; rm -rf /", home="/home/alice"
        )
        # The path
        # contains ``;``
        # so the username
        # regex fails and
        # we return the
        # path unchanged.
        assert result == "~; rm -rf /"

    def test_tilde_injection_blocked(self):
        # ``~$(...)`` is a
        # shell-injection
        # attempt. The
        # username regex
        # must reject it.
        result = expand_user_path(
            "~$(whoami)/notes", home="/home/alice"
        )
        assert result == "~$(whoami)/notes"

    def test_absolute_unchanged(self):
        assert (
            expand_user_path("/abs/path", home="/home/alice")
            == "/abs/path"
        )

    def test_windows_path_unchanged(self):
        assert (
            expand_user_path(r"C:\Users\me\notes.md", home="/home/alice")
            == r"C:\Users\me\notes.md"
        )

    def test_empty_unchanged(self):
        assert expand_user_path("", home="/home/alice") == ""

    def test_relative_path_unchanged(self):
        assert (
            expand_user_path("notes.md", home="/home/alice")
            == "notes.md"
        )


# ============================================================================
# A-1: blocked-device check
# ============================================================================


class TestIsBlockedDevice:
    @pytest.mark.parametrize(
        "p",
        [
            "/dev/zero",
            "/dev/random",
            "/dev/urandom",
            "/dev/full",
            "/dev/stdin",
            "/dev/tty",
            "/dev/console",
            "/dev/stdout",
            "/dev/stderr",
            "/dev/fd/0",
            "/dev/fd/1",
            "/dev/fd/2",
        ],
    )
    def test_linux_blocked(self, p):
        assert is_blocked_device(p) is True

    @pytest.mark.parametrize(
        "p",
        [
            "CON",
            "con",
            "Con",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM9",
            "LPT1",
            "LPT9",
            "CON.txt",
            "nul.txt",
            "com1.log",
            r"C:\CON",
            r"C:\foo\CON",
            r"C:\Users\me\Documents\nul",
        ],
    )
    def test_windows_reserved_blocked(self, p):
        assert is_blocked_device(p) is True

    @pytest.mark.parametrize(
        "p",
        [
            "/dev/null",  # NOT in our blocklist; user has a real /dev/null file
            "notes.md",
            r"C:\Users\me\notes.md",
            "/tmp/foo.txt",
            "console.log",  # not the same as CON
            "print.txt",  # not the same as PRN
        ],
    )
    def test_normal_paths_allowed(self, p):
        assert is_blocked_device(p) is False

    def test_empty_path_blocked(self):
        # Empty path
        # = "not a
        # valid file".
        # We block it
        # for safety.
        assert is_blocked_device("") is True


# ============================================================================
# A-2: binary extension pre-block
# ============================================================================


class TestHasBinaryExtension:
    @pytest.mark.parametrize(
        "p,ext",
        [
            ("foo.png", ".png"),
            ("foo.jpg", ".jpg"),
            ("foo.jpeg", ".jpeg"),
            ("foo.gif", ".gif"),
            ("foo.webp", ".webp"),
            ("foo.bmp", ".bmp"),
            ("foo.mp4", ".mp4"),
            ("foo.zip", ".zip"),
            ("foo.tar", ".tar"),
            ("foo.gz", ".gz"),
            ("foo.exe", ".exe"),
            ("foo.dll", ".dll"),
            ("foo.so", ".so"),
            ("foo.doc", ".doc"),
            ("foo.xls", ".xls"),
        ],
    )
    def test_binary_extensions_detected(self, p, ext):
        assert has_binary_extension(p) == ext

    @pytest.mark.parametrize(
        "p",
        [
            "foo.py",
            "foo.md",
            "foo.json",
            "foo.csv",
            "foo.tsv",
            "foo.txt",
            "foo.yaml",
            "foo.html",
        ],
    )
    def test_text_extensions_allowed(self, p):
        assert has_binary_extension(p) is None

    def test_case_insensitive(self):
        assert has_binary_extension("FOO.PNG") == ".png"
        assert has_binary_extension("Foo.Zip") == ".zip"

    def test_empty_path(self):
        assert has_binary_extension("") is None


# ============================================================================
# A-4: /proc secret path check
# ============================================================================


class TestIsProcSecretPath:
    @pytest.mark.parametrize(
        "p",
        [
            "/proc/self/environ",
            "/proc/self/cmdline",
            "/proc/self/maps",
            "/proc/1234/environ",
            "/proc/1234/cmdline",
            "/proc/1234/maps",
            "/proc/1/environ",
        ],
    )
    def test_proc_secret_detected(self, p):
        assert is_proc_secret_path(p) is True

    @pytest.mark.parametrize(
        "p",
        [
            "/proc/foo",
            "/proc/cpuinfo",
            "/proc/meminfo",
            "/proc/version",
            "/proc/self/status",
            "/proc/self/fd/0",
            "notes.md",
            "/tmp/environ.txt",  # basename match doesn't count
        ],
    )
    def test_non_secret_proc_paths_allowed(self, p):
        assert is_proc_secret_path(p) is False

    def test_empty(self):
        assert is_proc_secret_path("") is False


# ============================================================================
# A-6: BOM strip
# ============================================================================


class TestStripUtf8Bom:
    def test_first_chunk_stripped(self):
        assert strip_utf8_bom("\ufeffhello", is_first_chunk=True) == "hello"

    def test_no_bom_unchanged(self):
        assert strip_utf8_bom("hello", is_first_chunk=True) == "hello"

    def test_second_chunk_unchanged(self):
        # The BOM
        # only lives
        # at byte 0
        # of a file.
        # If a file
        # *contains*
        # U+FEFF in
        # the middle,
        # we MUST
        # preserve it.
        assert (
            strip_utf8_bom("\ufeffhello", is_first_chunk=False)
            == "\ufeffhello"
        )

    def test_empty(self):
        assert strip_utf8_bom("", is_first_chunk=True) == ""

    def test_only_bom(self):
        assert strip_utf8_bom("\ufeff", is_first_chunk=True) == ""


# ============================================================================
# A-5: char-limit guard
# ============================================================================


class TestEnforceCharLimit:
    def test_within_limit(self):
        # Returns
        # ``None``
        # = "OK, no
        # error".
        assert enforce_char_limit("hello", limit=10) is None

    def test_exactly_at_limit(self):
        assert enforce_char_limit("x" * 10, limit=10) is None

    def test_over_limit(self):
        err_json = enforce_char_limit(
            "a" * 100, limit=10, total_lines=5, path="foo.md"
        )
        assert err_json is not None
        err = json.loads(err_json)
        assert err["ok"] is False
        assert err["error_kind"] == "too_large"
        assert "100" in err["error"]
        assert "10" in err["error"]
        assert err["total_lines"] == 5
        assert err["path"] == "foo.md"
        assert "hint" in err
        assert "offset=" in err["hint"]

    def test_empty_content_passes(self):
        assert enforce_char_limit("", limit=10) is None

    def test_default_limit_100k(self):
        # 100K - 1 = OK
        assert enforce_char_limit("x" * (DEFAULT_READ_CHAR_LIMIT - 1)) is None
        # 100K + 1 = fail
        err = enforce_char_limit("x" * (DEFAULT_READ_CHAR_LIMIT + 1))
        assert err is not None

    def test_over_limit_no_metadata(self):
        # Optional
        # fields
        # (total_lines,
        # path) are
        # omitted when
        # not given.
        err_json = enforce_char_limit("a" * 20, limit=10)
        err = json.loads(err_json)
        assert "total_lines" not in err
        assert "path" not in err


# ============================================================================
# A-7: protected dir hint
# ============================================================================


class TestIsProtectedDir:
    @pytest.mark.parametrize(
        "p,name",
        [
            (".git/config", ".git"),
            (".git/HEAD", ".git"),
            (".vscode/settings.json", ".vscode"),
            (".idea/workspace.xml", ".idea"),
            (".husky/pre-commit", ".husky"),
            (".manusift/config.yaml", ".manusift"),
            ("foo/.git/config", ".git"),
            (r"C:\repo\.git\config", ".git"),
            ("subdir/.manusift/x.yaml", ".manusift"),
        ],
    )
    def test_protected_dirs_detected(self, p, name):
        assert is_protected_dir(p) == name

    @pytest.mark.parametrize(
        "p",
        [
            "notes.md",
            "src/main.py",
            "data/table.csv",
            "git-config.txt",  # basename starts with "git" but no ".git" dir
            "manusift.txt",  # similar
        ],
    )
    def test_normal_paths_not_protected(self, p):
        assert is_protected_dir(p) is None

    def test_empty(self):
        assert is_protected_dir("") is None


# ============================================================================
# A-8: extractable document detection + try_extract
# ============================================================================


class TestIsExtractableDocument:
    @pytest.mark.parametrize(
        "p",
        ["foo.docx", "foo.xlsx", "foo.pptx", "foo.ipynb", "FOO.DOCX"],
    )
    def test_extractable(self, p):
        assert is_extractable_document(p) is True

    @pytest.mark.parametrize(
        "p",
        ["foo.txt", "foo.pdf", "foo.doc", "foo.xls", "foo.zip", "foo"],
    )
    def test_not_extractable(self, p):
        assert is_extractable_document(p) is False

    def test_empty(self):
        assert is_extractable_document("") is False


class TestTryExtractDocument:
    def test_returns_none_for_missing_file(self, tmp_path):
        # File does
        # not exist
        # → ``None``
        # (caller
        # falls
        # through).
        result = try_extract_document(str(tmp_path / "nope.docx"))
        assert result is None

    def test_returns_none_for_unparseable_file(self, tmp_path):
        # ``.docx``
        # file
        # containing
        # random
        # bytes
        # (not a
        # real
        # zip) →
        # extraction
        # raises
        # → ``None``
        # because
        # ``on_error="fallback"``.
        bad_docx = tmp_path / "bad.docx"
        bad_docx.write_bytes(b"not a real docx file")
        result = try_extract_document(str(bad_docx))
        assert result is None


# ============================================================================
# End-to-end: ReadFileTool.execute with all A-1..A-8 guards
# ============================================================================


class TestReadFileToolA1BlockedDevice:
    def test_dev_zero_blocked(self, read_file_tool, ctx):
        out = read_file_tool.execute({"path": "/dev/zero"}, ctx)
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error_kind"] == "argument_invalid"
        assert "device file" in data["error"]
        assert data["path"] == "/dev/zero"

    def test_con_blocked(self, read_file_tool, ctx):
        out = read_file_tool.execute({"path": "CON"}, ctx)
        data = json.loads(out)
        assert data["ok"] is False
        assert "device file" in data["error"]

    def test_proc_environ_blocked(self, read_file_tool, ctx):
        out = read_file_tool.execute(
            {"path": "/proc/self/environ"}, ctx
        )
        data = json.loads(out)
        assert data["ok"] is False
        # A-1 and
        # A-4 are
        # *both*
        # correct
        # here
        # (proc
        # secret
        # is
        # more
        # specific
        # so the
        # error
        # kind is
        # permission_denied).
        assert data["error_kind"] == "permission_denied"
        assert "/proc" in data["error"]


class TestReadFileToolA2BinaryExtension:
    def test_png_blocked(self, read_file_tool, ctx, tmp_path):
        png = tmp_path / "test.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        out = read_file_tool.execute({"path": str(png)}, ctx)
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error_kind"] == "argument_invalid"
        assert data["extension"] == ".png"
        assert "binary" in data["error"]

    def test_zip_blocked(self, read_file_tool, ctx, tmp_path):
        zf = tmp_path / "test.zip"
        zf.write_bytes(b"PK\x03\x04fake zip content")
        out = read_file_tool.execute({"path": str(zf)}, ctx)
        data = json.loads(out)
        assert data["ok"] is False
        assert data["extension"] == ".zip"


class TestReadFileToolA3TildeExpansion:
    def test_tilde_expansion(
        self, read_file_tool, ctx, tmp_path, monkeypatch
    ):
        # Create a
        # file in
        # a fake
        # home
        # dir.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        notes = fake_home / "notes.md"
        notes.write_text("hello world\n", encoding="utf-8")
        # Point
        # ``HOME``
        # to the
        # fake
        # home so
        # ``expanduser``
        # returns
        # it.
        monkeypatch.setenv("HOME", str(fake_home))
        out = read_file_tool.execute(
            {"path": "~/notes.md"}, ctx
        )
        data = json.loads(out)
        assert data["ok"] is True, data.get("error")
        assert "hello world" in data["content"]


class TestReadFileToolA5CharLimit:
    def test_over_limit_file(
        self, read_file_tool, ctx, tmp_path, monkeypatch
    ):
        # 50K of
        # content
        # (one
        # char per
        # line)
        # → 50K
        # chars
        # after
        # line
        # joining.
        big = tmp_path / "big.md"
        big.write_text("x" * 50_000, encoding="utf-8")
        # Lower
        # the
        # limit
        # so the
        # test is
        # fast.
        from manusift.tools import safe_read
        monkeypatch.setattr(
            safe_read, "DEFAULT_READ_CHAR_LIMIT", 1_000
        )
        out = read_file_tool.execute(
            {"path": str(big)}, ctx
        )
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error_kind"] == "too_large"
        assert data["total_lines"] >= 1
        assert data["path"] == str(big)
        assert "hint" in data


class TestReadFileToolA6BomStrip:
    def test_bom_stripped(
        self, read_file_tool, ctx, tmp_path
    ):
        f = tmp_path / "bom.md"
        f.write_text("\ufeffhello world\n", encoding="utf-8")
        out = read_file_tool.execute({"path": str(f)}, ctx)
        data = json.loads(out)
        assert data["ok"] is True
        assert data["content"].startswith("hello")
        assert "\ufeff" not in data["content"]


class TestReadFileToolA7ProtectedDirHint:
    """R-2026-06-19 (P1-B2):
    the
    ``is_protected_dir``
    guard was
    added in
    Phase A as a
    *hint*
    (read
    was still
    allowed).
    P1-B2 wired the
    new
    ``block_protected_dir_reads=True``
    default into
    ``ReadFileTool.execute``
    so paths
    inside
    ``.git`` /
    ``.vscode`` /
    ``.manusift``
    now return
    ``error_kind: "permission_denied"``
    instead of the
    file content.
    The user can
    opt out via
    ``MANUSIFT_BLOCK_PROTECTED_DIR_READS=0``
    in the env.

    The default
    test below
    exercises the
    blocking path;
    a second test
    uses the
    opt-out to
    verify the
    legacy
    "allow with
    hint"
    behavior
    still works
    when the user
    explicitly
    disables
    blocking.
    """

    def test_git_config_is_blocked_by_default(
        self, read_file_tool, ctx, tmp_path
    ):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        cfg = git_dir / "config"
        cfg.write_text(
            "[user]\n\tname = test\n", encoding="utf-8"
        )
        out = read_file_tool.execute(
            {"path": str(cfg)}, ctx
        )
        data = json.loads(out)
        # Read
        # is
        # *blocked*
        # by
        # the
        # new
        # ``block_protected_dir_reads=True``
        # default.
        assert data["ok"] is False
        assert data["error_kind"] == "permission_denied"
        assert data["protected_dir"] == ".git"
        # The file content must NOT be in the
        # response (the only "leak" is the
        # ``path`` field which is the path the
        # user already passed in).
        assert "test" not in data.get("error", "")

    def test_git_config_allowed_with_opt_out(
        self, read_file_tool, ctx, tmp_path, monkeypatch
    ):
        # Opt out: the user *really* wants to
        # read .git/config. The setting can be
        # disabled via the env var, but our
        # test monkey-patches the settings
        # directly because the env-var is read
        # only on the first ``get_settings()``
        # call and most tests in this file
        # have already triggered that.
        from manusift import config as cfg_mod
        from manusift.config import Settings
        # Invalidate the cached settings so the
        # next call picks up the env var.
        monkeypatch.setenv(
            "MANUSIFT_BLOCK_PROTECTED_DIR_READS", "0"
        )
        cfg_mod._settings_cache = None  # type: ignore[attr-defined]
        try:
            git_dir = tmp_path / ".git"
            git_dir.mkdir()
            cfg = git_dir / "config"
            cfg.write_text(
                "[user]\n\tname = test\n", encoding="utf-8"
            )
            out = read_file_tool.execute(
                {"path": str(cfg)}, ctx
            )
            data = json.loads(out)
            # Now the read succeeds; the
            # ``protected_dir`` hint is still
            # in the response for transparency.
            assert data["ok"] is True
            assert "test" in data["content"]
            assert data["protected_dir"] == ".git"
        finally:
            cfg_mod._settings_cache = None  # type: ignore[attr-defined]


class TestReadFileToolA8DocxFallback:
    def test_corrupted_docx_falls_through(
        self, read_file_tool, ctx, tmp_path
    ):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"not a real docx")
        out = read_file_tool.execute({"path": str(bad)}, ctx)
        data = json.loads(out)
        # Extraction
        # failed
        # → fall
        # through
        # to
        # normal
        # text-read
        # which
        # sees a
        # binary
        # file
        # and
        # fails
        # with
        # UnicodeDecodeError
        # (Latin-1
        # fallback
        # will
        # succeed
        # and we
        # get the
        # raw
        # bytes).
        # Either
        # way,
        # no
        # crash.
        assert isinstance(data, dict)
        assert "ok" in data


# ============================================================================
# Regression: existing behavior preserved
# ============================================================================


class TestReadFileToolRegression:
    def test_normal_text_file(self, read_file_tool, ctx, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("line 1\nline 2\n", encoding="utf-8")
        out = read_file_tool.execute({"path": str(f)}, ctx)
        data = json.loads(out)
        assert data["ok"] is True
        assert "line 1" in data["content"]
        assert "line 2" in data["content"]
        # A-7:
        # normal
        # files
        # have
        # no
        # protected
        # dir.
        assert data["protected_dir"] is None

    def test_pdf_still_rejected_with_ingest_hint(
        self, read_file_tool, ctx, tmp_path
    ):
        f = tmp_path / "paper.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        out = read_file_tool.execute({"path": str(f)}, ctx)
        data = json.loads(out)
        assert data["ok"] is False
        assert "ingest_from_path" in data["error"]

    def test_missing_file_still_not_found(
        self, read_file_tool, ctx, tmp_path
    ):
        out = read_file_tool.execute(
            {"path": str(tmp_path / "nope.md")}, ctx
        )
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error_kind"] == "not_found"

    def test_relative_path_still_rejected(
        self, read_file_tool, ctx
    ):
        out = read_file_tool.execute(
            {"path": "notes.md"}, ctx
        )
        data = json.loads(out)
        assert data["ok"] is False
        assert "absolute" in data["error"]
