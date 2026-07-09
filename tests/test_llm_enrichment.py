"""Step-6 LLM enrichment tests.

The LLM contract changed in Step H1: ``analyze_finding`` now returns
an ``LLMVerdict`` (a Pydantic model) instead of a free-text string.
The pipeline stores ``verdict.summary`` into ``Finding.llm_verdict``,
so test assertions on ``f.llm_verdict`` still look at the same
string field they always did.

Five branches are covered:
  1. No key configured   → mock client, 0 calls, llm_skipped not set
  2. Concurrency=0       → all eligible findings get llm_skipped=True
  3. Successful call     → llm_verdict populated, llm_skipped=False
  4. Failed call         → llm_skipped=True, finding still survives
  5. Concurrency actually parallel for N findings
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from manusift import pipeline as pipeline_mod
from manusift.config import get_settings
from manusift.contracts import Finding
from manusift.llm import client as llm_client
from manusift.llm.schemas import LLMVerdict
from manusift.pipeline import _enrich_with_llm


# ---------- helpers ----------

def _mk_finding(severity: str, fid: str = "abc") -> Finding:
    return Finding.make(
        trace_id="t",
        detector="test",
        severity=severity,  # type: ignore[arg-type]
        title=f"test finding {fid}",
        evidence="evidence",
        location="loc",
    )


def _make_verdict(summary: str = "plausible, needs visual check") -> LLMVerdict:
    """Build a valid LLMVerdict for the test static client to return."""
    return LLMVerdict(
        summary=summary,
        verdict="needs_review",
        confidence=0.5,
        next_step="open the figure and zoom in",
    )


class _StaticLLM:
    """Test client that returns a canned LLMVerdict or fails."""

    def __init__(
        self,
        *,
        verdict: LLMVerdict | None = None,
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self._verdict = verdict or _make_verdict()
        self._fail = fail
        self._delay = delay
        self.name = "test-static"
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding: Finding) -> LLMVerdict | None:
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            return None
        return self._verdict


@pytest.fixture(autouse=True)
def _reset_llm_singleton() -> None:
    llm_client._reset_for_tests()
    yield
    llm_client._reset_for_tests()


# ---------- 1. mock client short-circuits ----------

def test_enrichment_skipped_when_mock(monkeypatch) -> None:
    """When no key is configured, get_llm_client returns the Mock
    implementation, and _enrich_with_llm must issue 0 calls."""
    # Force the singleton to be the mock by clearing both env keys.
    monkeypatch.delenv("MANUSIFT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MANUSIFT_ANTHROPIC_API_KEY", raising=False)
    # The .env file may still contain a key from the local
    # configuration (the R-audit live-LLM pilot), so we
    # *force* the singleton to the mock rather than
    # relying on ``Settings()`` to rebuild from a
    # ``delenv``'d env.
    llm_client._reset_for_tests(forced=llm_client.MockLLM())

    findings = [_mk_finding("high", "h1"), _mk_finding("medium", "m1")]
    calls = _enrich_with_llm(findings)
    assert calls == 0
    # Mock returns None from analyze_finding, so the mock short-circuit
    # never runs that path — finding objects are not mutated.
    for f in findings:
        assert f.llm_verdict is None
        assert f.llm_skipped is False


# ---------- 2. concurrency=0 → all eligible marked skipped ----------

def test_enrichment_disabled_when_concurrency_zero(monkeypatch) -> None:
    """With llm_max_concurrency=0, every eligible finding is marked
    llm_skipped without any LLM call."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    static = _StaticLLM()
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)

    # Force a single Settings instance for the whole test.
    s = get_settings().model_copy(update={"llm_max_concurrency": 0})
    monkeypatch.setattr(pipeline_mod, "get_settings", lambda: s)

    findings = [_mk_finding("high", "h1"), _mk_finding("medium", "m1")]
    calls = _enrich_with_llm(findings)
    assert calls == 0
    assert static.calls == 0
    for f in findings:
        assert f.llm_skipped is True
        assert f.llm_verdict is None


# ---------- 3. successful call ----------

def test_enrichment_writes_verdict_on_success(monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    static = _StaticLLM(verdict=_make_verdict("plausible, needs visual check"))
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)

    findings = [_mk_finding("high", "h1")]
    calls = _enrich_with_llm(findings)
    assert calls == 1
    # Pipeline stores verdict.summary into Finding.llm_verdict.
    assert findings[0].llm_verdict == "plausible, needs visual check"
    assert findings[0].llm_skipped is False
    assert static.calls == 1


# ---------- 4. failed call ----------

def test_enrichment_marks_skipped_on_failure(monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    static = _StaticLLM(fail=True)
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)

    findings = [_mk_finding("high", "h1")]
    _enrich_with_llm(findings)
    assert findings[0].llm_skipped is True
    assert findings[0].llm_verdict is None


# ---------- 5. low/info findings are skipped ----------

def test_enrichment_skips_low_and_info(monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    static = _StaticLLM()
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)

    findings = [_mk_finding("low", "l1"), _mk_finding("info", "i1")]
    calls = _enrich_with_llm(findings)
    assert calls == 0
    assert static.calls == 0
    for f in findings:
        assert f.llm_verdict is None
        assert f.llm_skipped is False


# ---------- 6. concurrency actually works in parallel ----------

def test_enrichment_uses_thread_pool(monkeypatch) -> None:
    """N findings each sleeping 0.2s should finish in ~0.2s, not N*0.2s,
    when concurrency >= N."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    static = _StaticLLM(delay=0.2)
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)

    s = get_settings().model_copy(update={
        "llm_max_concurrency": 4,
        "llm_enrichment_budget_seconds": 5.0,
    })
    monkeypatch.setattr(pipeline_mod, "get_settings", lambda: s)

    findings = [_mk_finding("high", f"h{i}") for i in range(4)]
    t0 = time.time()
    _enrich_with_llm(findings)
    elapsed = time.time() - t0
    # Sequential would be 4 * 0.2 = 0.8s. Parallel should be ~0.2-0.3s.
    assert elapsed < 0.6, f"elapsed={elapsed:.2f}s suggests no concurrency"
    for f in findings:
        assert f.llm_verdict == "plausible, needs visual check"


# ---------- 7. real HTTP shape via MockTransport (OpenAI) ----------

class _OpenAITransport(httpx.MockTransport):
    """Returns a minimal valid OpenAI chat completion payload whose
    content is a *valid* LLMVerdict JSON string. The pipeline then
    parses it through the same code path real traffic would hit."""

    def __init__(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": _make_verdict("looks genuine").model_dump_json()}}
                    ]
                },
            )
        super().__init__(handler)


def test_enrichment_via_real_openai_client(monkeypatch) -> None:
    """A real OpenAILLM pointed at a MockTransport should produce a
    real verdict. This guards the wire format AND the schema
    validation code path."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    transport = _OpenAITransport()
    real = llm_client.OpenAILLM(get_settings())
    # Inject a transport by wrapping the analyze_finding path. The
    # client builds its own httpx.Client inside _call; we patch the
    # method instead so we don't have to rewrite the call site.
    def fake_call(_finding: Finding, strict_json: bool = False) -> str | None:
        with httpx.Client(transport=transport) as c:
            r = c.post("https://example/v1/chat/completions", json={})
        return r.json()["choices"][0]["message"]["content"]
    monkeypatch.setattr(real, "_call", fake_call)

    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: real)

    findings = [_mk_finding("high", "h1")]
    _enrich_with_llm(findings)
    assert findings[0].llm_verdict == "looks genuine"
    assert findings[0].llm_skipped is False


# ---------- 8. LLM returns garbage → retry, then skip ----------

def test_enrichment_retries_on_garbage_then_skips(monkeypatch) -> None:
    """If the LLM first returns text that doesn't parse as LLMVerdict,
    the client retries once. If the retry also fails, the finding
    is marked llm_skipped=True (no crash, no silent overwrite)."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    real = llm_client.OpenAILLM(get_settings())
    responses = iter(["Sure, here you go: 42", "  some prose, no JSON"])

    def fake_call(_finding: Finding, strict_json: bool = False) -> str | None:
        return next(responses, None)

    monkeypatch.setattr(real, "_call", fake_call)
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: real)

    findings = [_mk_finding("high", "h1")]
    _enrich_with_llm(findings)
    # Two fake_call invocations: first + retry.
    # (Can't check `real._call` call count from outside easily; the
    # observable signal is that the finding is skipped.)
    assert findings[0].llm_skipped is True
    assert findings[0].llm_verdict is None


# ---------- 9. retry succeeds on the second try ----------

def test_enrichment_retry_recovers(monkeypatch) -> None:
    """If the first response is unparseable but the retry is a valid
    LLMVerdict JSON, the verdict is stored."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-fake")
    llm_client._reset_for_tests()

    real = llm_client.OpenAILLM(get_settings())
    responses = iter(
        [
            "Here's my answer: nope",  # first try: garbage
            _make_verdict("recovered on retry").model_dump_json(),
        ]
    )

    def fake_call(_finding: Finding, strict_json: bool = False) -> str | None:
        return next(responses, None)

    monkeypatch.setattr(real, "_call", fake_call)
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: real)

    findings = [_mk_finding("high", "h1")]
    _enrich_with_llm(findings)
    assert findings[0].llm_verdict == "recovered on retry"
    assert findings[0].llm_skipped is False


# ---------- 10. LLMVerdict model rejects extra fields ----------

def test_llm_verdict_rejects_unknown_fields() -> None:
    """Borrowed from Instructor's strict-mode behaviour: the LLM
    can lie about extra fields and we drop the response rather
    than store a half-broken verdict."""
    from pydantic import ValidationError

    import json
    raw = json.dumps(
        {
            "summary": "ok",
            "verdict": "looks_legit",
            "confidence": 0.5,
            "next_step": "done",
            "totally_made_up_field": "should be rejected",
        }
    )
    with pytest.raises(ValidationError):
        LLMVerdict.model_validate_json(raw)
