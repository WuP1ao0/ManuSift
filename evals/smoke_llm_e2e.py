"""End-to-end smoke for LLM enrichment through the FastAPI app.

Runs TestClient with the OpenAILLM client monkey-patched so its
``_call`` method returns a canned verdict (no real LLM traffic, no
network). Verifies that:

  1. The pipeline still completes end-to-end.
  2. The /findings response contains a non-empty llm_verdict on
     a high/medium-severity finding.
  3. The /report HTML embeds the LLM verdict string.

Run::

    ./.venv/Scripts/python.exe -m evals.smoke_llm_e2e
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import httpx

from manusift import pipeline as pipeline_mod
from manusift.llm import client as llm_client


FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_PDF = FIXTURES / "chatbot_text.pdf"


def _patched_call(self, finding) -> str | None:
    """A fake OpenAILLM._call that returns a deterministic verdict."""
    return f"[fake-llm] {finding.detector} looks plausible, visual check recommended."


def main() -> int:
    if not FIXTURE_PDF.exists():
        print(f"fixture missing: {FIXTURE_PDF} — run build_fixtures first")
        return 2

    # Use a fresh tmp workspace so this smoke doesn't pollute prod.
    tmp = Path(tempfile.mkdtemp(prefix="manusift-llm-smoke-"))
    old_workspace = os.environ.get("MANUSIFT_WORKSPACE_DIR")
    os.environ["MANUSIFT_WORKSPACE_DIR"] = str(tmp / "jobs")
    os.environ["MANUSIFT_OPENAI_API_KEY"] = "sk-fake-but-accepted"
    os.environ["MANUSIFT_LLM_MAX_CONCURRENCY"] = "2"
    os.environ["MANUSIFT_LLM_ENRICHMENT_BUDGET_SECONDS"] = "10"

    # Make the OpenAILLM's _call go through our patched version.
    orig_call = llm_client.OpenAILLM._call
    llm_client.OpenAILLM._call = _patched_call  # type: ignore[assignment]
    llm_client._reset_for_tests()

    try:
        from fastapi.testclient import TestClient
        from manusift.web.app import create_app

        app = create_app()
        with TestClient(app) as client, open(FIXTURE_PDF, "rb") as f:
            upload = client.post(
                "/api/upload",
                files={"file": (FIXTURE_PDF.name, f, "application/pdf")},
            )
            if upload.status_code != 202:
                print(f"upload failed: {upload.status_code} {upload.text[:200]}")
                return 1
            tid = upload.json()["trace_id"]

            # Poll.
            import time
            for _ in range(100):
                jr = client.get(f"/api/jobs/{tid}")
                if jr.json().get("status") in ("done", "failed"):
                    break
                time.sleep(0.1)

            fr = client.get(f"/api/jobs/{tid}/findings").json()
            findings = fr.get("findings", [])
            llm_verdicts = [f for f in findings if f.get("llm_verdict")]
            report = client.get(f"/api/jobs/{tid}/report").text

            print("=" * 60)
            print(f"trace_id       : {tid}")
            print(f"findings       : {len(findings)}")
            print(f"with verdicts  : {len(llm_verdicts)}")
            print("=" * 60)
            for f in findings:
                verdict = f.get("llm_verdict")
                if verdict:
                    print(f"  [{f['severity']:6}] {f['detector']:18} verdict={verdict[:80]!r}")
                else:
                    print(f"  [{f['severity']:6}] {f['detector']:18} (no verdict)")

            ok = (
                len(findings) >= 1
                and len(llm_verdicts) >= 1
                and any(v["llm_verdict"] in report for v in llm_verdicts)
            )
            print("=" * 60)
            print("PASS" if ok else "FAIL")
            return 0 if ok else 1
    finally:
        # Restore.
        llm_client.OpenAILLM._call = orig_call  # type: ignore[assignment]
        llm_client._reset_for_tests()
        if old_workspace is None:
            os.environ.pop("MANUSIFT_WORKSPACE_DIR", None)
        else:
            os.environ["MANUSIFT_WORKSPACE_DIR"] = old_workspace
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
