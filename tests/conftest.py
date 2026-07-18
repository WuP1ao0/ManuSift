"""Shared test fixtures.

``tmp_workspace`` points each test at an isolated workspace under a
tmp dir so tests don't pollute ``data/jobs/``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "vision" in item.keywords and not _env_enabled(
        "MANUSIFT_RUN_VISION"
    ):
        pytest.skip("requires MANUSIFT_RUN_VISION=1")
    if "real_ocr" in item.keywords and not _env_enabled(
        "MANUSIFT_RUN_REAL_OCR"
    ):
        pytest.skip("requires MANUSIFT_RUN_REAL_OCR=1")
    if "slow" in item.keywords and not (
        _env_enabled("MANUSIFT_RUN_SLOW")
        or _env_enabled("MANUSIFT_RUN_REAL_OCR")
    ):
        pytest.skip("requires MANUSIFT_RUN_SLOW=1")


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    # Clear the LLM singleton between tests.
    from manusift.llm import client as llm_client
    llm_client._reset_for_tests()
    return tmp_path / "jobs"


@pytest.fixture(autouse=True)
def _reset_global_state() -> None:
    """Reset module-level mutable state between tests to prevent
    test-order state leakage (disabled tools, get_settings patches,
    LLM client singleton).
    """
    from manusift.tools import registry as tool_reg
    import manusift.config as cfg_mod
    from manusift.llm import client as llm_client

    tool_reg.reset_disabled()
    _original_get_settings = cfg_mod.get_settings
    llm_client._reset_for_tests()
    yield
    tool_reg.reset_disabled()
    cfg_mod.get_settings = _original_get_settings
    llm_client._reset_for_tests()
