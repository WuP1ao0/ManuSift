"""Build manusift/detectors/tortured_phrases_data.json from the curated
PaperGuard / Cabanac-derived tortured-phrases CSV.

Provenance:
  https://github.com/maymy832410/paperguard-curated-tortured-phrases
  (tortured_phrases.csv; itself derived from the Cabanac et al. tortured-
  phrases list, rows marked verification_status=verified and
  ai_review_status=likely_tortured).

Usage:
  .venv\\Scripts\\python.exe scripts/build_tortured_dict.py [csv_path]

Fetches the CSV when no local path is given. The output JSON is a flat
{tortured_phrase_lower: intended_phrase} dict consumed by
manusift/detectors/tortured_phrases.py at import time.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

CSV_URL = (
    "https://raw.githubusercontent.com/maymy832410/"
    "paperguard-curated-tortured-phrases/main/tortured_phrases.csv"
)
OUT = (
    Path(__file__).resolve().parent.parent
    / "manusift" / "detectors" / "tortured_phrases_data.json"
)

# Entries that are common legitimate English and would false-positive.
_BLOCKLIST = {"transient"}

_HAS_LETTER = re.compile(r"[A-Za-z一-鿿]")


def build(csv_text: str) -> dict[str, str]:
    phrases: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("verification_status") != "verified":
            continue
        if row.get("ai_review_status") != "likely_tortured":
            continue
        try:
            conf = float(row.get("ai_review_confidence") or 0)
        except ValueError:
            conf = 0.0
        if conf < 0.9:
            continue
        tortured = (row.get("tortured_phrase") or "").strip().lower()
        intended = (row.get("expected_phrase") or "").strip()
        if len(tortured) < 4 or not _HAS_LETTER.search(tortured):
            continue
        if tortured in _BLOCKLIST:
            continue
        phrases.setdefault(tortured, intended)
    return phrases


def main() -> int:
    if len(sys.argv) > 1:
        csv_text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(CSV_URL, timeout=60) as resp:  # noqa: S310
            csv_text = resp.read().decode("utf-8")
    phrases = build(csv_text)
    OUT.write_text(
        json.dumps(phrases, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    print(f"wrote {OUT} with {len(phrases)} phrases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
