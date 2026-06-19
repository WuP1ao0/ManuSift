"""Pytest integration for the eval suite.

Each JSON case under ``evals/cases/`` becomes one pytest test. A case
that reports a failure in the runner will fail here. Failing a case
on purpose is a useful way to ensure the runner's FAIL path is
covered.
"""
from __future__ import annotations

import pytest

from evals.runner import _load_cases, _run_one


pytestmark = pytest.mark.slow


def _all_cases() -> list[dict]:
    return _load_cases()


@pytest.mark.parametrize("case", _all_cases(), ids=lambda c: c["name"])
def test_eval_case(case: dict, tmp_path_factory) -> None:
    """Run the pipeline on the case's fixture and check expectations."""
    # Honor the same env-gated skip that the CLI runner uses, so a
    # LLM-dependent case shows up as pytest.skip rather than a silent
    # pass when MANUSIFT_LLM_EVALS isn't set.
    import os
    skip_env = case.get("skip_unless_env")
    if skip_env and not os.environ.get(skip_env):
        pytest.skip(f"requires {skip_env}=1 to run")

    # Use a per-case workspace to keep things isolated.
    workspace = tmp_path_factory.mktemp("evals_ws")
    old = os.environ.get("MANUSIFT_WORKSPACE_DIR")
    os.environ["MANUSIFT_WORKSPACE_DIR"] = str(workspace)
    try:
        result = _run_one(case)
    finally:
        if old is None:
            os.environ.pop("MANUSIFT_WORKSPACE_DIR", None)
        else:
            os.environ["MANUSIFT_WORKSPACE_DIR"] = old

    assert result.passed, (
        f"eval case {case['name']!r} failed:\n"
        + "\n".join(f"  - {f}" for f in result.failures)
    )
