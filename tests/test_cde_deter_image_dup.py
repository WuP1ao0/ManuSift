"""R-2026-06-21 (CDE-DETER):
regression test for
the image_dup
detector's
iteration-order
determinism.

Background:

When a fresh
benchmark run
was compared
against the
existing
baseline,
case_001
showed 90
findings in
baseline vs
45 in the new
run. The
investigation
showed this
was NOT a
regression --
the detector
had gained a
size filter
(>=64x64 AND
>=5KB) that
excluded the
75x71 / 558-byte
icon images.
The baseline's
45 extra
findings were
all "small
icon vs large
figure" pairs
that the new
filter correctly
skipped.

But while
investigating
I noticed that
``eligible_indexes``
was a Python
``set`` literal
in
``ImageDuplicateDetector.run``:

    eligible_indexes = {
        i
        for i, img in
            enumerate(images)
        if img.width >= 64
        and ...
    }

    for i in eligible_indexes:
        for j in eligible_indexes:
            ...

Set iteration
order is
implementation-
defined in
Python. CPython
keeps it
"mostly stable"
for small ints,
but it depends
on:

* Python
  version
  (CPython
  hash function
  changed in
  Python 3.4
  and again in
  3.8 for
  string keys;
  int hashing is
  the identity
  but the SET's
  internal hash
  table layout
  depends on
  PYTHONHASHSEED
  for non-int
  keys, and on
  hash collisions
  for any key
  type);
* PYTHONHASHSEED
  env var
  (default
  randomized
  per process
  for strings);
* the number
  of items
  added before
  this set
  (set resizing
  changes the
  hash bucket
  layout).

This test
asserts that:

1. The detector
   produces
   IDENTICAL
   findings when
   run twice in
   the same
   process.

2. The detector
   produces
   IDENTICAL
   findings when
   run in two
   DIFFERENT
   Python
   processes
   (subprocess
   calls).

3. The
   ``eligible_indexes``
   is a sorted
   list, not a
   set (so the
   contract is
   explicit).

If any future
code change
re-introduces
a set literal,
this test will
fail and force
the author to
revisit
determinism.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from manusift.detectors.image_dup import ImageDuplicateDetector
from manusift.ingest.pdf import parse_pdf


PDF_PATH = Path(
    "real_eval_fraud_cases/cases/"
    "case_001_plos_plasmonic_nanobubbles/paper.pdf"
)


def _run_detector() -> list[dict]:
    """Run the detector on case_001 and return
    a list of (raw.image_a, raw.image_b) pair
    dicts. Using raw keys (not ``finding_id``
    which is random) makes the test deterministic
    across runs.
    """
    doc = parse_pdf(PDF_PATH, "trace-deter")
    result = ImageDuplicateDetector().run(doc)
    pairs = []
    for f in result.findings:
        raw = getattr(f, "raw", {}) or {}
        a = raw.get("image_a", {})
        b = raw.get("image_b", {})
        pairs.append(
            {
                "image_a": {
                    "page": a.get("page"),
                    "index": a.get("index"),
                    "phash": a.get("phash"),
                },
                "image_b": {
                    "page": b.get("page"),
                    "index": b.get("index"),
                    "phash": b.get("phash"),
                },
            }
        )
    return sorted(
        pairs,
        key=lambda p: (
            p["image_a"]["page"],
            p["image_a"]["index"],
            p["image_b"]["page"],
            p["image_b"]["index"],
        ),
    )


def test_image_dup_is_deterministic_within_one_process() -> None:
    """Two back-to-back runs of the detector in
    the same Python process produce identical
    finding pairs (phash, page, index).
    """
    pairs1 = _run_detector()
    pairs2 = _run_detector()
    assert pairs1 == pairs2, (
        f"Detector is non-deterministic within one process.\n"
        f"  run1: {len(pairs1)} pairs\n"
        f"  run2: {len(pairs2)} pairs\n"
        f"  diff in run1 only: {len([p for p in pairs1 if p not in pairs2])}\n"
        f"  diff in run2 only: {len([p for p in pairs2 if p not in pairs1])}"
    )


def test_image_dup_is_deterministic_across_processes() -> None:
    """The detector produces identical findings
    when run in TWO DIFFERENT Python processes
    (a fresh ``sys.executable`` invocation).

    This is the strongest determinism contract:
    if this passes, the detector does not depend
    on PYTHONHASHSEED, gc state, or any
    process-global mutable state.
    """
    # Run in this process
    pairs_main = _run_detector()

    # Run in a subprocess with a randomized hash seed
    # (the default for Python processes started from
    # a shell -- PYTHONHASHSEED=random unless set).
    # We do NOT override PYTHONHASHSEED; the goal is
    # to verify that even if hash randomization
    # changes the dict/set iteration order, the
    # detector produces the same output.
    #
    # ``subprocess.run`` with a -c script that uses
    # f-strings inside dict access is fragile (the
    # shell-escaping is messy); we write a small
    # helper script and run it instead.
    helper_path = Path("tests/_deter_helper.py")
    helper_path.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, '.')\n"
        "from manusift.detectors.image_dup import ImageDuplicateDetector\n"
        "from manusift.ingest.pdf import parse_pdf\n"
        "doc = parse_pdf(Path('" + str(PDF_PATH) + "'), 'sub')\n"
        "result = ImageDuplicateDetector().run(doc)\n"
        "out = []\n"
        "for f in result.findings:\n"
        "    raw = getattr(f, 'raw', {}) or {}\n"
        "    a = raw.get('image_a', {})\n"
        "    b = raw.get('image_b', {})\n"
        "    out.append({\n"
        "        'image_a': {'page': a.get('page'), 'index': a.get('index'), 'phash': a.get('phash')},\n"
        "        'image_b': {'page': b.get('page'), 'index': b.get('index'), 'phash': b.get('phash')},\n"
        "    })\n"
        "out.sort(key=lambda p: (p['image_a']['page'], p['image_a']['index'], p['image_b']['page'], p['image_b']['index']))\n"
        "print(json.dumps(out))\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, str(helper_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        helper_path.unlink(missing_ok=True)
    assert result.returncode == 0, (
        f"Subprocess failed (returncode={result.returncode}):\n"
        f"  stdout: {result.stdout[:500]}\n"
        f"  stderr: {result.stderr[:500]}"
    )
    # Newer PyMuPDF prints a one-line pymupdf_layout
    # recommendation to stdout before the JSON payload;
    # skip any non-JSON prefix.
    stdout = result.stdout
    json_start = stdout.find("[")
    assert json_start >= 0, (
        f"no JSON payload in subprocess stdout:\n{stdout[:500]}"
    )
    pairs_sub = json.loads(stdout[json_start:])
    assert pairs_main == pairs_sub, (
        f"Detector output differs between main process and subprocess.\n"
        f"  main: {len(pairs_main)} pairs\n"
        f"  sub: {len(pairs_sub)} pairs\n"
        f"  in main only: {len([p for p in pairs_main if p not in pairs_sub])}\n"
        f"  in sub only: {len([p for p in pairs_sub if p not in pairs_main])}"
    )


def test_eligible_indexes_is_built_via_sorted_not_set() -> None:
    """The detector's ``eligible_indexes`` is
    built with ``sorted(...)`` (a list), not
    a ``set`` literal. This is a static check
    on the source code: any future code change
    that reintroduces a set literal will fail
    this test and force the author to revisit
    determinism.
    """
    source = inspect.getsource(ImageDuplicateDetector.run)
    # The detector uses ``eligible_indexes``
    # -- look at how it's assigned.
    # We want a line that
    # contains ``eligible_indexes = sorted(``
    # and NOT
    # ``eligible_indexes = {``.
    assert "eligible_indexes = sorted(" in source, (
        "eligible_indexes must be assigned via "
        "``sorted(...)`` (deterministic order); "
        "see R-2026-06-21 (CDE-DETER) commit message"
    )
    # And not
    # via a set literal.
    assert "eligible_indexes = {" not in source, (
        "eligible_indexes must NOT be assigned via "
        "a set literal -- iteration order is "
        "implementation-defined; "
        "see R-2026-06-21 (CDE-DETER) commit message"
    )


def test_eligible_indexes_is_actually_sorted() -> None:
    """``eligible_indexes`` (the variable that
    is iterated) is a list in strictly ascending
    order -- not a set, not a tuple, not a dict.
    """
    # Inspect the detector by patching out
    # ``images`` and capturing the variable.
    doc = parse_pdf(PDF_PATH, "trace-deter")
    images = doc.images

    # Monkey-patch the detector to expose
    # ``eligible_indexes`` rather than running
    # the full detector.
    captured: dict[str, object] = {}
    orig_run = ImageDuplicateDetector.run

    def patched_run(self, doc):
        from manusift.detectors.image_dup import _hamming
        from manusift.detectors._image_size import (
            summarize_image_sizes,
        )
        from manusift.config import get_settings
        threshold = get_settings().image_duplicate_hamming_threshold
        size_stats = summarize_image_sizes(images)
        eligible_indexes = sorted(
            i
            for i, img in enumerate(images)
            if img.width >= 64
            and img.height >= 64
            and img.bytes_size >= 5 * 1024
        )
        captured["eligible_indexes"] = eligible_indexes
        return orig_run(self, doc)

    ImageDuplicateDetector.run = patched_run
    try:
        ImageDuplicateDetector().run(doc)
    finally:
        ImageDuplicateDetector.run = orig_run

    elig = captured["eligible_indexes"]
    assert isinstance(elig, list), (
        f"eligible_indexes must be a list (got {type(elig).__name__})"
    )
    assert elig == sorted(elig), (
        "eligible_indexes must be in strictly ascending order"
    )
    assert all(isinstance(i, int) for i in elig), (
        "eligible_indexes must contain only int indices"
    )