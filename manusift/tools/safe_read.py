"""R-2026-06-17 (Phase A:
borrow from
Claude Code +
Hermes):
8 small
``read_file``
hardening
modules
combined
in one
file so
``direct_fs.py``
stays clean.

Each module is a
*pure function*
(0 IO where
possible) so it
can be unit-tested
in isolation. The
functions are
called in
``ReadFileTool.execute``
(``direct_fs.py``)
*before* the file is
actually opened, so
the most common
failure modes
(device hangs,
binary blobs, secret
leaks, BOM
artefacts) never
reach the read path.

Borrowed from
(see the comparison
doc):

  * ``_is_blocked_device``
    — Hermes
    ``file_tools.py:248``.
    Pure-path check
    that blocks
    ``/dev/zero``,
    ``/dev/random``,
    ``/proc/*/environ``,
    Windows ``CON``,
    ``NUL``,
    ``COM1-9``
    before they hang
    the read.

  * ``has_binary_extension``
    — Hermes
    ``binary_extensions``.
    Pre-block on
    common binary
    formats (image /
    archive / exe)
    so the user gets a
    helpful redirect
    to ``vision_analyze``
    or
    ``ingest_from_path``
    instead of a
    50 MB blob.

  * ``expand_user_path``
    — Hermes
    ``file_operations.py:810``.
    ``~`` /
    ``~user`` expansion
    that validates
    the username
    against
    ``[a-zA-Z0-9._-]+``
    *before* handing
    it to the shell,
    so a user-typed
    ``~; rm -rf /``
    never reaches
    ``os.path.expanduser``.

  * ``is_proc_secret_path``
    — Hermes
    ``file_tools.py:258``.
    Defends against
    agent reading
    host process
    secrets
    (``/proc/self/environ``,
    ``/proc/<pid>/cmdline``,
    ``/proc/<pid>/maps``).

  * ``enforce_char_limit``
    — Hermes
    ``file_tools.py:905``
    + Claude Code
    2000-line hint.
    Reject reads over
    100K chars *after*
    read, with a
    friendly
    ``Use offset+limit``
    hint. Catches OOM
    before the LLM
    pays for it.

  * ``strip_utf8_bom``
    — Hermes
    ``file_operations.py:1030``.
    The BOM
    (``\\ufeff``)
    only lives at
    byte 0; later
    pages can't carry
    it. Strip only on
    the first chunk
    so a BOM-looking
    sequence in the
    middle of a file
    is preserved.

  * ``is_protected_dir``
    — Claude Code
    protected
    directories
    (``.git`` /
    ``.vscode`` /
    ``.idea`` /
    ``.manusift``).
    Reads from
    these are *allowed*
    (they are local
    files) but writes
    are blocked. The
    read side surfaces
    a "this is a
    config file" hint
    so the LLM does
    not paraphrase
    ``.git/config``
    into its final
    report.

  * ``try_extract_document``
    — Hermes
    ``file_tools.py:768``.
    Malformed .docx /
    .xlsx / .ipynb
    fall through to
    the normal
    binary / text
    branch instead of
    crashing the read
    with an
    unhandled
    exception.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


# =============================================================================
# A-1: blocked-device check
# =============================================================================

# Linux infinite-output + blocking-input devices.
# Reading any of these
# either produces
# infinite output
# (``/dev/zero``) or
# blocks forever on
# stdin
# (``/dev/tty``).
# Pure path check -- 0
# I/O.
_BLOCKED_DEVICE_PATHS: frozenset[str] = frozenset(
    {
        # Infinite output
        # -- never reach
        # EOF
        "/dev/zero",
        "/dev/random",
        "/dev/urandom",
        "/dev/full",
        # Blocks waiting
        # for input
        "/dev/stdin",
        "/dev/tty",
        "/dev/console",
        # Nonsensical to
        # read
        "/dev/stdout",
        "/dev/stderr",
        # fd aliases
        "/dev/fd/0",
        "/dev/fd/1",
        "/dev/fd/2",
    }
)

# Windows reserved
# device names
# (case-insensitive,
# no extension, with
# or without ``:``).
# ``os.path.expanduser``
# does NOT block
# these, so we
# check ourselves.
# Keys are UPPERCASE
# so we can do a
# fast case-insensitive
# lookup against
# ``stem.upper()``.
_WINDOWS_RESERVED: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


def is_blocked_device(path: str) -> bool:
    """Return ``True`` for paths that would hang or leak secrets if read.

    R-2026-06-17
    (Phase A):
    check the
    literal
    path
    first
    so
    aliases
    like
    ``/dev/stdin``
    are
    caught
    *before*
    they
    resolve
    to
    terminal-specific
    paths.
    Then
    check
    the
    resolved
    path
    so
    a
    workspace
    symlink
    to
    ``/dev/zero``
    cannot
    bypass
    the
    guard.
    """
    if not path:
        return True
    # Linux/WSL:
    # exact match
    # first
    if path in _BLOCKED_DEVICE_PATHS:
        return True
    # ``/proc/self/fd/0-2``,
    # ``/proc/<pid>/fd/0-2``
    # are
    # Linux
    # aliases
    # for
    # stdio
    normalized = os.path.expanduser(path)
    if normalized in _BLOCKED_DEVICE_PATHS:
        return True
    if normalized.startswith("/proc/") and normalized.endswith(
        ("/fd/0", "/fd/1", "/fd/2")
    ):
        return True
    # Windows
    # reserved
    # names
    # (case
    # insensitive,
    # no
    # extension).
    # Match
    # ``CON``,
    # ``CON.txt``,
    # ``C:\CON``,
    # etc.
    # The
    # set
    # stores
    # UPPERCASE
    # keys
    # so we
    # can do
    # an
    # O(1)
    # case-insensitive
    # ``in``
    # check
    # against
    # ``stem.upper()``.
    base = Path(normalized).name
    stem = Path(base).stem.upper()
    # ``CON.txt``
    # →
    # ``CON``;
    # strip
    # trailing
    # ``.``
    stem_clean = stem.rstrip(".")
    if stem_clean in _WINDOWS_RESERVED:
        return True
    # Resolved
    # path
    # check
    # (catches
    # symlinks
    # to
    # blocked
    # devices).
    try:
        resolved = str(Path(normalized).resolve())
    except OSError:
        return False
    if resolved in _BLOCKED_DEVICE_PATHS:
        return True
    if resolved.startswith("/proc/") and resolved.endswith(
        ("/fd/0", "/fd/1", "/fd/2")
    ):
        return True
    base_r = Path(resolved).name
    stem_r = Path(base_r).stem.upper().rstrip(".")
    if stem_r in _WINDOWS_RESERVED:
        return True
    return False


# =============================================================================
# A-2: binary-extension pre-block
# =============================================================================

# Common binary
# formats that
# ``read_file``
# cannot serve as
# text.  PDFs are
# handled
# separately
# (they are
# rejected with a
# helpful
# ``use ingest_from_path``
# hint
# elsewhere).
_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".ico",
        ".tiff",
        ".tif",
        # Audio /
        # video
        ".mp3",
        ".wav",
        ".flac",
        ".ogg",
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".webm",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".xz",
        # Executables
        # / object
        # code
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".lib",
        ".class",
        ".pyc",
        ".pyo",
        # Native
        # binaries
        ".bin",
        ".dat",
        # Office
        # (older
        # binary
        # formats;
        # modern
        # .docx/.xlsx
        # are
        # zip-based
        # and
        # handled
        # via
        # extract)
        ".doc",
        ".xls",
        ".ppt",
    }
)


def has_binary_extension(path: str) -> str | None:
    """Return the offending extension if the path is binary; else ``None``.

    R-2026-06-17
    (Phase A):
    the
    caller
    gets
    the
    extension
    so
    the
    error
    message
    can
    say
    "Cannot
    read
    .png"
    instead
    of
    just
    "binary".
    """
    if not path:
        return None
    suffix = Path(path).suffix.lower()
    if suffix in _BINARY_EXTENSIONS:
        return suffix
    return None


# =============================================================================
# A-3: ~ / ~user expansion
# =============================================================================

# Per Hermes
# ``file_operations.py:810``:
# only allow the
# ``~user`` form when
# the username is a
# safe identifier
# (alphanum +
# ``. _ -``).
# This blocks shell
# injection via
# paths like
# ``~; rm -rf /`` or
# ``~$(malicious)``
# because
# ``os.path.expanduser``
# is implemented in
# C (no shell), but a
# future refactor
# that pipes the
# result through a
# shell MUST keep
# this regex.
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def expand_user_path(
    path: str,
    *,
    home: str | None = None,
) -> str:
    """Expand ``~`` / ``~user`` to an absolute path safely.

    R-2026-06-17
    (Phase A):
    1.
    ``~``
    alone
    →
    home
    dir
    2.
    ``~/foo``
    →
    home
    +
    ``/foo``
    3.
    ``~user/foo``
    →
    user
    home
    +
    ``/foo``
    (only
    when
    ``user``
    matches
    the
    safe-identifier
    regex)

    Absolute
    paths
    and
    non-``~``
    paths
    are
    returned
    unchanged.
    The
    ``home``
    kwarg
    is
    for
    test
    injection;
    in
    production
    it
    defaults
    to
    ``os.path.expanduser('~')``.
    """
    if not path:
        return path
    if not path.startswith("~"):
        return path
    # Strip
    # leading
    # ``~``
    if home is None:
        # R-2026-06-17 (Phase A):
        # ``os.path.expanduser``
        # behaviour
        # differs
        # across
        # platforms:
        #
        # * Linux
        # /
        # macOS
        # → uses
        # ``$HOME``
        # (then
        # ``pwd``
        # lookup
        # for
        # ``~user``)
        # * Windows
        # → uses
        # ``$USERPROFILE``
        # (and
        # ignores
        # ``$HOME``
        # unless
        # ``$HOME``
        # is the
        # only
        # one set)
        #
        # For
        # testability
        # (monkeypatch
        # ``HOME``)
        # *and*
        # cross-platform
        # consistency
        # we look
        # up
        # ``$HOME``
        # first
        # when it
        # is set,
        # then fall
        # back to
        # ``os.path.expanduser``.
        # This
        # also
        # makes
        # the
        # sandbox
        # / Docker
        # case work
        # (where
        # ``$HOME``
        # is
        # ``/root``
        # and
        # ``$USERPROFILE``
        # is unset).
        home = os.environ.get("HOME")
        if not home:
            home = os.path.expanduser("~")
    if path == "~":
        return home
    if path.startswith("~/"):
        # R-2026-06-17 (Phase A):
        # ``os.path.join`` uses
        # the wrong separator
        # on Windows (``\``
        # when joining an
        # absolute POSIX path).
        # Use ``Path`` to
        # normalise the
        # separator to the
        # platform-native
        # one (``\`` on
        # Windows, ``/``
        # elsewhere) so the
        # result is a valid
        # absolute path the
        # rest of the read
        # pipeline can
        # handle.
        suffix = path[2:]
        combined = str(Path(home) / suffix)
        return combined
    # ``~user``
    # form.
    # Strip
    # the
    # leading
    # ``~``,
    # find
    # the
    # username
    # (up
    # to
    # first
    # ``/``
    # or
    # end).
    rest = path[1:]
    slash = rest.find("/")
    username = rest[:slash] if slash >= 0 else rest
    suffix = rest[slash:] if slash >= 0 else ""
    if not username or not _USERNAME_RE.match(username):
        # Not a
        # safe
        # ``~user``
        # form.
        # Return
        # the
        # path
        # unchanged
        # so the
        # caller
        # surfaces
        # a
        # clear
        # "invalid
        # path"
        # error
        # rather
        # than
        # silently
        # doing
        # something
        # weird.
        return path
    # Use
    # ``pwd``
    # lookup
    # via
    # the
    # stdlib
    # only
    # (no
    # shell).
    # On
    # Windows
    # ``~user``
    # is
    # not
    # supported;
    # we
    # only
    # handle
    # POSIX
    # here.
    try:
        import pwd
        pwent = pwd.getpwnam(username)
        user_home = pwent.pw_dir
    except (KeyError, ImportError, OSError):
        # Unknown
        # user
        # or
        # not
        # POSIX
        # →
        # return
        # unchanged
        # (caller
        # will
        # see
        # a
        # "not
        # found"
        # error).
        return path
    return user_home + suffix


# =============================================================================
# A-4: /proc secret leak check
# =============================================================================


def is_proc_secret_path(path: str) -> bool:
    """Return ``True`` if the path is a ``/proc`` secret that must not be read.

    R-2026-06-17
    (Phase A):
    these
    Linux
    proc
    files
    leak
    the
    host
    process's
    environment
    variables
    (containing
    API
    keys),
    command-line
    args
    (containing
    secrets
    in
    ``--api-key=...``),
    and
    memory
    layout
    (containing
    any
    key
    the
    process
    has
    loaded).
    Reading
    them
    is
    almost
    always
    a
    mistake
    (and
    a
    leak
    in
    any
    report).
    """
    if not path:
        return False
    normalized = os.path.expanduser(path)
    if not normalized.startswith("/proc/"):
        return False
    # Match
    # ``/proc/<anything>/environ``
    # ``/proc/<anything>/cmdline``
    # ``/proc/<anything>/maps``
    # where
    # ``<anything>``
    # is
    # self
    # /
    # a
    # PID.
    for suffix in ("/environ", "/cmdline", "/maps"):
        if normalized.endswith(suffix):
            return True
    return False


# =============================================================================
# A-5: char-count guard
# =============================================================================

# Hermes uses 100K.
# We pick 100K too so
# the read result +
# line-number prefix
# fits comfortably in
# one Anthropic
# context block.
DEFAULT_READ_CHAR_LIMIT = 100_000


def enforce_char_limit(
    content: str,
    *,
    limit: int | None = None,
    offset: int = 1,
    total_lines: int | None = None,
    path: str | None = None,
) -> str | None:
    """Return ``None`` if content is within the limit; else an error JSON.

    R-2026-06-17
    (Phase A):
    the
    caller
    passes
    the
    *formatted*
    content
    (with
    line
    numbers
    prepended),
    not
    the
    raw
    file
    bytes,
    because
    that's
    what
    actually
    enters
    the
    LLM
    context.
    Returns
    a
    JSON
    string
    in
    the
    same
    shape
    as
    other
    read_file
    errors
    so
    the
    LLM
    can
    handle
    them
    uniformly.

    ``limit=None`` (the
    default) means "look up
    ``DEFAULT_READ_CHAR_LIMIT``
    at call time". This
    makes the limit
    monkey-patchable in
    tests.
    """
    # Resolve
    # ``limit``
    # at call
    # time so
    # tests
    # can
    # monkey-patch
    # ``DEFAULT_READ_CHAR_LIMIT``
    # without
    # the
    # default
    # arg
    # being
    # frozen
    # at
    # import
    # time.
    if limit is None:
        limit = DEFAULT_READ_CHAR_LIMIT
    if not content:
        return None
    if len(content) <= limit:
        return None
    n_chars = len(content)
    err: dict[str, Any] = {
        "ok": False,
        "error_kind": "too_large",
        "error": (
            f"Read produced {n_chars:,} characters which exceeds "
            f"the safety limit ({limit:,} chars). Use offset and "
            f"limit to read a smaller range."
        ),
    }
    if total_lines is not None:
        err["total_lines"] = total_lines
    if path is not None:
        err["path"] = path
    next_offset = offset + (limit // 50)  # rough heuristic
    err["hint"] = (
        f"Try offset={next_offset} (file has {total_lines or '?'} lines)"
    )
    import json as _json
    return _json.dumps(err, ensure_ascii=False)


# =============================================================================
# A-6: UTF-8 BOM strip
# =============================================================================

_UTF8_BOM = "\ufeff"


def strip_utf8_bom(
    text: str,
    *,
    is_first_chunk: bool,
) -> str:
    """Strip the UTF-8 BOM (``\\ufeff``) from the *first* chunk of a read.

    R-2026-06-17
    (Phase A):
    per
    Hermes
    ``file_operations.py:1030``,
    the
    BOM
    only
    lives
    at
    byte
    0
    of
    a
    file.
    Later
    pages
    of
    a
    paginated
    read
    can't
    carry
    it.
    Stripping
    it
    from
    non-first
    chunks
    would
    silently
    mangle
    a
    file
    that
    *contains*
    the
    U+FEFF
    sequence
    mid-stream
    (rare
    but
    legal).
    """
    if not is_first_chunk:
        return text
    if text.startswith(_UTF8_BOM):
        return text[len(_UTF8_BOM):]
    return text


# =============================================================================
# A-7: protected-dir hint
# =============================================================================

# Claude Code's
# permanent
# protection
# set -- reads are
# allowed, writes
# require explicit
# approval.  We add
# ``.manusift``
# because it's
# ManuSift's own
# config dir (the
# agent must not
# paraphrase
# ``.manusift/config.yaml``
# into the user
# report).
_PROTECTED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".vscode",
        ".idea",
        ".husky",
        ".claude",
        ".manusift",
    }
)


def is_protected_dir(path: str) -> str | None:
    """Return the protected dir name if ``path`` is inside one, else ``None``.

    R-2026-06-17
    (Phase A):
    reads
    are
    still
    allowed
    (we
    don't
    block),
    but
    the
    caller
    gets
    a
    hint
    so
    the
    LLM
    does
    not
    paraphrase
    ``.git/config``
    into
    the
    final
    user-facing
    report.
    Writes
    are
    blocked
    by
    the
    write_file
    tool
    (out
    of
    scope
    here).
    """
    if not path:
        return None
    normalized = os.path.expanduser(path)
    parts = Path(normalized).parts
    for part in parts:
        if part in _PROTECTED_DIRS:
            return part
    return None


# =============================================================================
# A-8: extract_document_text fallback
# =============================================================================


def is_extractable_document(path: str) -> bool:
    """Return ``True`` if the file is a structured doc we can extract text from.

    R-2026-06-17
    (Phase A):
    modern
    Office
    formats
    are
    zip-based,
    not
    text
    --
    they
    need
    a
    real
    parser
    (python-docx,
    openpyxl,
    nbformat).
    We
    *can*
    extract
    them
    in-process,
    so
    we
    route
    through
    ``try_extract_document``
    before
    the
    binary
    guard
    fires
    (so
    a
    .docx
    is
    not
    misclassified
    as
    binary).
    """
    if not path:
        return False
    suffix = Path(path).suffix.lower()
    return suffix in {".docx", ".xlsx", ".pptx", ".ipynb"}


def try_extract_document(
    path: str,
    *,
    on_error: str = "fallback",
) -> str | None:
    """Try to extract text from a structured document; return ``None`` on failure.

    R-2026-06-17
    (Phase A):
    the
    caller
    (``ReadFileTool.execute``)
    passes
    ``on_error="fallback"``
    so a
    malformed
    .docx
    / .xlsx
    / .ipynb
    falls
    through
    to
    the
    normal
    text-read
    branch
    (which
    will
    then
    fail
    with
    a
    clearer
    "not
    text"
    error)
    instead
    of
    crashing
    the
    whole
    read
    with
    an
    unhandled
    exception.
    Returns
    the
    extracted
    text
    on
    success;
    ``None``
    on
    failure
    (caller
    decides
    what
    to
    do).
    """
    if not path or not os.path.exists(path):
        return None
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".docx":
            from .read_extract import (
                ExtractionError,
                extract_docx_text,
            )
            return extract_docx_text(path)
        if suffix == ".xlsx":
            from .read_extract import (
                ExtractionError,
                extract_xlsx_text,
            )
            return extract_xlsx_text(path)
        if suffix == ".pptx":
            from .read_extract import (
                ExtractionError,
                extract_pptx_text,
            )
            return extract_pptx_text(path)
        if suffix == ".ipynb":
            from .read_extract import (
                ExtractionError,
                extract_ipynb_text,
            )
            return extract_ipynb_text(path)
    except ImportError:
        # The
        # read_extract
        # module
        # doesn't
        # exist
        # yet
        # (Phase
        # A
        # #4
        # deferred
        # to
        # short-term).
        # Fall
        # through
        # to
        # the
        # binary
        # guard.
        return None
    except Exception:
        # Malformed
        # file
        # or
        # other
        # extraction
        # error.
        # Return
        # ``None``
        # so the
        # caller
        # can
        # fall
        # back
        # to
        # the
        # normal
        # branch
        # (which
        # will
        # give
        # a
        # cleaner
        # "not
        # text"
        # error).
        if on_error == "fallback":
            return None
        raise
    return None
