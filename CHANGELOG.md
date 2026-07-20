# Changelog

All notable **user-facing** changes to ManuSift are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning aims at [SemVer](https://semver.org/) once past beta.

GitHub **Releases** may mirror tagged notes for a given version; this file
is the in-repo history for contributors and clone-from-source users.

## [Unreleased]

### Added

### Changed

- README / docs: spell out **MCP tools (~83 default, ~45 curated)** vs
  **detectors (52 registered / 44 offline pipeline / 8 excluded)** so the
  counts are not conflated; align `docs/mcp/README.md` and
  `docs/DETECTOR_LAYERS.md`.
- README: clarify optional local HTTP API (`uvicorn` on `127.0.0.1`) is
  loopback-only, not a hosted ManuSift cloud.
- MCP example configs: portable `manusift-mcp` / `./data/jobs` instead of
  machine-specific absolute paths.
- Public comment hygiene: drop "leaked Claude Code" attributions and
  personal path residue from source notes.
- `pipeline.py`: eliminate double detector instantiation (`cls().name` →
  `cls.name`); remove redundant `import os as _os`; issues.json written
  once after aggregation + adjudication (was twice).
- `image_forensics.py`: precompute file sizes and SHA1 hashes before the
  O(n²) cross-image SIFT pair loop (N² stat/hash calls reduced to N).

### Fixed

- **`stats_algo.chi2_sf_approx`**: was returning the *lower-tail* CDF with
  the wrong argument (`x` instead of `x/2`), inverting all p-values for
  Benford, last-digit uniformity, and statcheck χ² tests. Rewritten with
  correct Q(df/2, x/2) using series + Lentz continued fraction.
- **`table_stats._chi2_sf`**: same bug in the legacy Benford path; now
  delegates to the verified `_chi2_sf_exact` implementation.
- `pipeline.py`: restore `llm_skipped=True` marking for high/medium
  findings when `llm_max_concurrency=0` (frozen dataclass via
  `object.__setattr__`).
- `test_screen_verdict.py`: MCP curated tool count assertion 40 → 45.

### Removed

- README: Related work table; one-line benchmark snapshot claim
  (negative-control / core-recall marketing sentence).

## [0.1.0b1] - 2026-07

Beta open-source readiness cut of the **B + C** product (batch CLI + MCP).

### Added

- Offline `manusift screen` pipeline with multi-suite detectors (image,
  table/source-data, text/metadata, optional external checks).
- MCP Domain Kernel (`manusift mcp` / `manusift-mcp`); default exposes the
  full tool registry; `--curated` for a smaller allow-list.
- Parallel detector workers after shared parse (`MANUSIFT_DETECTOR_WORKERS`,
  default 4; set `1` for serial).
- Install smoke (`scripts/install_smoke.py`) and tracked `evals/fixtures/`
  sample PDFs for clean-clone offline checks.
- Investigation-pairs HTML as the primary batch report path; optional LLM
  packaging only when API keys / concurrency allow.

### Notes

- Conversational chat TUI (`chat_app`) is **not** part of the product.
- Full pytest tree is large; CI runs a reproducible subset (see
  `.github/workflows/ci.yml`).
- Screening aid only—not a legal determination of misconduct.
