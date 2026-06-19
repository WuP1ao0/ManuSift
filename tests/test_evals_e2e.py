"""Pytest integration for the end-to-end eval suite.

Each JSON case under ``evals/cases/e2e/`` becomes one pytest test
that drives the FastAPI app via TestClient and checks the full HTTP
surface: upload -> poll -> findings -> report HTML.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from evals.e2e import _load_e2e_cases, _run_e2e_one


pytestmark = pytest.mark.slow


def _all_e2e_cases() -> list[dict]:
    return _load_e2e_cases()


@pytest.mark.parametrize("case", _all_e2e_cases(), ids=lambda c: c["name"])
def test_e2e_case(case: dict, tmp_path: Path) -> None:
    """Run the FastAPI app against the case's fixture end-to-end."""
    workspace = tmp_path / "jobs"
    result = _run_e2e_one(case, workspace)
    assert result.passed, (
        f"e2e case {case['name']!r} failed:\n"
        + "\n".join(f"  - {f}" for f in result.failures)
    )
