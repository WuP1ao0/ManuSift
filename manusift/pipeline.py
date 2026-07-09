"""End-to-end pipeline: ingest -> detectors -> LLM enrich -> report.

The pipeline is a single function that takes a workspace path + a PDF
path, runs every stage, writes artifacts, and returns an
``AnalysisResult``. It is called from a FastAPI BackgroundTask — there
is no concurrent job runner, so we do not need locks.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from pathlib import Path
from typing import Any, Callable

from .checkpoint import read_step_silent, write_step
from .config import get_settings
from .contracts import AnalysisResult, Finding, JobState
from .detectors import (
    DetectorResult,
    detector_name_for_class,
    iter_entrypoint_detectors,
    load_detector_class,
)
from .events import Event, get_bus
from .llm import get_llm_client
from .report.builder import build_report_html
from .trace import get_logger
from .workspace import JobPaths
log = get_logger(__name__)


def _parse_pdf(pdf_path: Path, trace_id: str, workspace_dir: Path):
    from .ingest.pdf import parse_pdf

    return parse_pdf(
        pdf_path,
        trace_id=trace_id,
        workspace_dir=workspace_dir,
    )


def _enrich_with_llm(findings: list[Finding]) -> int:
    """Call the LLM for high-severity findings. Returns call count.

    Concurrency: ``settings.llm_max_concurrency`` workers (0 disables).
    Per-call timeout: ``settings.llm_call_timeout_seconds``.
    Total budget: ``settings.llm_enrichment_budget_seconds`` — after
    this the remaining findings are marked ``llm_skipped=True`` and
    no more calls are issued.
    """
    settings = get_settings()
    client = get_llm_client()
    # Mock client has no real LLM behind it — short-circuit before
    # we even think about a thread pool.
    if client.name == "mock":
        return 0
    max_concurrency = int(settings.llm_max_concurrency)
    if max_concurrency <= 0:
        # User opted out of LLM enrichment entirely.
        for f in findings:
            if f.severity in ("medium", "high"):
                object.__setattr__(f, "llm_skipped", True)  # type: ignore[attr-defined]
        return 0

    targets = [f for f in findings if f.severity in ("medium", "high")]
    if not targets:
        return 0

    deadline = time.time() + float(settings.llm_enrichment_budget_seconds)
    per_call_timeout = float(settings.llm_call_timeout_seconds)

    # Snapshot each target's position so we can mutate the right
    # Finding from the worker threads without re-scanning the list.
    futures: dict[Any, Finding] = {}
    calls = 0
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        # Throttle submission by time-budget so we don't fire 100 calls
        # only to find we ran out of budget 5 seconds in.
        for f in targets:
            if time.time() >= deadline:
                object.__setattr__(f, "llm_skipped", True)  # type: ignore[attr-defined]
                continue
            futures[pool.submit(client.analyze_finding, f)] = f
            calls += 1

        for fut, f in list(futures.items()):
            remaining = max(0.0, deadline - time.time())
            try:
                verdict = fut.result(timeout=remaining or per_call_timeout)
            except FutTimeout:
                log.warning("llm enrichment timed out", extra={"fid": f.finding_id})
                object.__setattr__(f, "llm_skipped", True)  # type: ignore[attr-defined]
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "llm enrichment crashed",
                    extra={"fid": f.finding_id, "err": str(exc)},
                )
                object.__setattr__(f, "llm_skipped", True)  # type: ignore[attr-defined]
                continue
            if verdict is None:
                object.__setattr__(f, "llm_skipped", True)  # type: ignore[attr-defined]
            else:
                # Store the structured summary as a free-text verdict
                # for backwards compatibility with the report HTML —
                # the schema fields live in the LLM's memory but
                # we don't expose them in the v0.1 report yet.
                object.__setattr__(f, "llm_verdict", verdict.summary)  # type: ignore[attr-defined]
    return calls


def _persist_findings(paths: JobPaths, result: AnalysisResult) -> None:
    payload = {
        "trace_id": result.trace_id,
        "detectors_run": result.detectors_run,
        "llm_calls": result.llm_calls,
        "duration_ms": result.duration_ms,
        "findings": [f.__dict__ for f in result.findings],
    }
    paths.findings_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _persist_job_state(paths: JobPaths, state: JobState) -> None:
    paths.job_json.write_text(
        json.dumps(state.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# Detector list — the source of truth for both the pipeline and
# the web layer's /progress endpoint. The web layer imports
# ``detector_names_for_progress`` to avoid a circular import
# (pipeline -> web) and the test/UI drift this comment warns
# about. The built-in detectors come first; third-party
# detectors registered as entry points (Step H4) are appended
# in the order returned by ``iter_entrypoint_detectors``.
_BUILTIN_DETECTOR_CLASS_NAMES: list[str] = [
    "MetadataDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark): the
    # ``PdfMetadataDetector`` is now first in the
    # list so it runs on every case. Previously
    # it was missing from this list entirely,
    # which is why the gap report's "expected
    # but zero findings" list included
    # ``pdf_metadata``. The detector code in
    # ``manusift/detectors/pdf_metadata.py`` was
    # complete; the bug was that the offline
    # pipeline never instantiates it. This is a
    # 1-line fix: just add the class name here.
    "PdfMetadataDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the supplementary-data detector is now
    # in the offline pipeline. Previously it
    # was missing; the gap report notes that
    # "this detector reads XLSX/CSV companion
    # files, which are not in the PDF. With
    # only the PDF, the detector has nothing to
    # do." -- but the detector also reads the
    # data-availability section of the paper
    # to surface a "raw data unavailable"
    # structural finding (P2-D3 below). With
    # the PDF-only case, it can at least fire
    # the "no data availability statement"
    # finding.
    "SupplementaryFileDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the author-emails / non-academic-email
    # detector is now in the offline pipeline.
    # It looks for ``@gmail.com`` /
    # ``@yahoo.com`` / ``@hotmail.com`` in the
    # author affiliation block (a paper-mill
    # red flag per the "Hindawi 511-paper
    # paper-mill" 2023 retraction). Closes the
    # ``author_emails`` gap.
    "AuthorEmailAnalyzer",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the data-availability / compliance
    # detector is now in the offline pipeline.
    # Closes the ``compliance`` gap (the
    # detector reads the data-availability
    # statement for red-flag phrasing like
    # "available upon reasonable request").
    "ComplianceStatementDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the image SIFT keypoint copymove detector
    # is now in the offline pipeline. Closes
    # the ``image_sift_copymove`` gap (Frontiers
    # figures often lack enough SIFT keypoints
    # but the detector still fires on bar
    # charts with axis ticks).
    "SiftCopyMoveDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the duplicate-reference detector is now
    # in the offline pipeline. Closes the
    # ``ref_duplicate`` gap. Note: ref_duplicate
    # catches "the same paper cited twice with
    # different DOIs" (a paper-mill red flag
    # where 2+ authors recycle one reference).
    "DuplicateReferenceDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the reference-format anomaly detector is
    # now in the offline pipeline. Closes the
    # ``ref_format_anomaly`` gap.
    "ReferenceFormatAnomalyDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the GRIM (granularity-related inconsistency
    # of means) statistical detector is now
    # in the offline pipeline. Closes the
    # ``stat_grim`` gap. The detector reads
    # table-extracted values and runs the GRIM
    # test on every percentage. It can ALSO
    # be run on figure OCR text (figure_stat_text
    # writes the OCR-pass results to the
    # shared evidence store, so stat_grim
    # picks them up after). Phase 3 wired
    # figure_stat_text's output into stat_grim's
    # input.
    "GrimTestDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the p-value consistency detector. Closes
    # the ``stat_pvalue`` gap.
    "PValueConsistencyDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the percent-divisibility detector. Closes
    # the ``stat_percent`` gap.
    "PercentDivisibilityDetector",
    "TableRelationshipDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the noise-inconsistency detector (catches
    # images where the noise floor is different
    # across regions, a sign of stitching
    # panels from different sources). Closes
    # the ``image_noise_inconsistency`` gap.
    "NoiseInconsistencyDetector",
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the panel-segmentation detector. Closes
    # the ``panel_duplicate`` gap. (Note: the
    # detector is named ``PanelSegmentationDetector``
    # in the registry but publishes under
    # ``panel_duplicate``; this is the
    # detector that finds "this paper has
    # 1 panel that is identical to another
    # panel in the same paper".)
    "PanelSegmentationDetector",
    # R-2026-06-13: AI-generated-figure detector runs early (after
        # metadata) so the AI-tool fingerprint and prompt-token probes
        # have the /Info + XMP in hand before the heavier image
        # detectors run. Closes the case_011 (Frontiers AI-figure
        # retraction) gap; aligned with the P0-AI patch.
        "AIGeneratedFigureDetector",
    # R-2026-06-13: paper-mill / peer-review authorship-signal
        # detector. Pure text matching on the byline; closes the
        # case_032 (Frontiers 122-paper peer-review network) gap;
        # aligned with the P0-PEER patch.
        "PaperMillAuthorshipDetector",
        "ImageDuplicateDetector",
    "ImageForensicsDetector",
    "TextPatternDetector",
    # R-2026-06-12: data-availability-concern detector reads
        # the paper's data-availability section for red-flag
        # phrasing (e.g. "raw data are not available",
        # "available upon reasonable request"). Pure text
        # classification, no LLM. Inserted after the offline
        # detectors because it only needs the parsed text.
    "DataAvailabilityConcernDetector",
    # R-2026-06-12: page-raster duplicate detector renders
    # every page to a bitmap and hashes the figure
    # regions. This catches image-duplication in Frontiers
    # and other modern-PDF papers where figures are
    # embedded as vector drawings (not raster images) and
    # the existing image_dup detector sees 0 candidates.
    # Slow-ish (~50-200ms per page) so it runs after the
    # pure-text detectors.
    "PageRasterDuplicateDetector",
    # R-2026-06-12: panel-duplicate detector splits each
    # figure region into constituent panels using
    # whitespace-gap detection, then hashes each panel
    # independently. This catches panel-level duplications
    # (e.g. Figure 1A == Figure 1B) that the whole-figure
    # hash misses. Closes the case_005 Frontiers gap.
    "PanelDuplicateDetector",
    # R-2026-06-12: figure-body stat-text detector runs
    # EasyOCR on each figure region and emits findings
    # for recognised text fragments that look like
    # statistical descriptors (n=, p<0.05, mean+/-SD,
    # percentages, significance markers). Slow (~5-30s
    # per case) so it runs last among the local
    # detectors. Provides the evidence base for the
    # case_004 "sample size" not_testable target.
    "FigureStatTextDetector",
    # R-2026-06-12: figure-body GRIM consistency detector
    # reuses the same OCR pass as figure_stat_text and
    # GRIM-checks every recognised percentage in the
    # figure body. A GRIM-inconsistent percentage cannot
    # be reconciled with a wide range of plausible sample
    # sizes (N in [3, 100]). Closes the case_004 "sample
    # size" and "data interpretation" not_testable targets.
    "FigureGRIMDetector",
    # P2-D1 — the Crossref citation-network
    # detector runs last because it is the
    # only network-dependent step. Putting it
    # after the offline detectors means a
    # Crossref outage cannot delay the local
    # checks. The operator can opt out via
    # ``MANUSIFT_CROSSREF_ENABLED=0``.
    "CitationNetworkDetector",
]


def _pipeline_detector_classes() -> list[type]:
    """Return the built-in detector classes followed by any
    third-party detectors registered as entry points. The
    entry-point look-up is done lazily (every call) so a
    plugin installed *during* the process lifetime is picked
    up on the next pipeline run.

    Honors the ``benchmark_skip_detectors`` settings field:
    a comma-separated list of detector names that the
    pipeline should skip. Used by benchmark / eval runners
    that do not need slow OCR or Crossref calls. The skip
    list is NOT applied to the agent-loop tool registry (LLM-
    visible detectors) -- only to the offline pipeline.
    """
    try:
        from .config import get_settings
        skip = {
            s.strip() for s in (
                get_settings().benchmark_skip_detectors or ""
            ).split(",") if s.strip()
        }
    except Exception:  # noqa: BLE001
        skip = set()

    out: list[type] = []
    for class_name in _BUILTIN_DETECTOR_CLASS_NAMES:
        det_name = detector_name_for_class(class_name)
        if det_name in skip:
            continue
        out.append(load_detector_class(class_name))
    for plugin in iter_entrypoint_detectors():
        plugin_name = getattr(plugin, "name", None)
        if plugin_name in skip:
            continue
        out.append(type(plugin))
    return out


def detector_names_for_progress() -> list[str]:
    """Return the ordered list of detector names the pipeline
    runs. The web layer's /progress endpoint uses this so the
    'total_steps' field is consistent with the actual detector
    list. Always equal to ``[d().name for d in _pipeline_detector_classes()]``
    but does not require a Settings instance."""
    names = [
        detector_name_for_class(class_name)
        for class_name in _BUILTIN_DETECTOR_CLASS_NAMES
    ]
    for plugin in iter_entrypoint_detectors():
        names.append(plugin.name)
    return names


def run_pipeline(
    pdf_path: Path,
    paths: JobPaths,
    job_state: JobState,
    on_step_complete: Callable[[DetectorResult, JobState], None] | None = None,
) -> AnalysisResult:
    """Execute the full analysis. Side-effects: writes 4 files under
    ``paths`` (job.json, findings.json, report.html, steps/NN_*.json)
    and mutates ``job_state`` in place.

    ``on_step_complete`` is an optional hook called immediately
    after each detector step finishes and its checkpoint has been
    written. The web layer uses it to update the in-memory job
    registry so the progress endpoint can answer without
    re-reading the steps/ directory. Errors raised by the hook
    are swallowed — progress is a UI nicety, not a critical
    signal, and the pipeline must not abort because of it.
    """
    settings = get_settings()
    t0 = time.time()

    log.info("pipeline start", extra={"pdf": str(pdf_path)})
    # R-2026-06-13: emit job.started is done below, after the
    # detector class list is known, so the payload includes the
    # real ``detector_count`` for the TUI's progress bar.
    job_state.status = "running"
    _persist_job_state(paths, job_state)
    # R-2026-06-13: pre-compute the detector list once so the
    # ``job.started`` event can include the total detector count.
    # This is what the TUI's DetectorTraceBlock uses to render a
    # count-based progress bar (``12/38 done``) instead of an
    # indeterminate spinner.
    try:
        _detector_classes = _pipeline_detector_classes()
    except Exception:  # noqa: BLE001
        # Fallback to a tiny list -- the loop body will re-resolve
        # and the trace will just show 0/total.
        _detector_classes = []
    _detector_total = len(_detector_classes)
    # R-2026-06-13: pre-compute the detector list once so the
    # ``job.started`` event can include the total detector count.
    # This is what the TUI's DetectorTraceBlock uses to render a
    # count-based progress bar (``12/38 done``) instead of an
    # indeterminate spinner.
    # R-2026-06-13: subscribe a DetectorTraceListener on the
    # bus for the duration of this run. The listener builds an
    # in-memory DetectorTrace that the TUI's DetectorTraceBlock
    # widget subscribes to via the same listener pattern. The
    # trace is also written to ``detector_summary.json`` at the
    # end of the run (after the loop body). We always
    # unsubscribe in a finally block so a crashed pipeline does
    # not leave a dangling listener on the bus.
    from .detector_trace import (
        DetectorTrace,
        DetectorTraceListener,
        write_summary,
    )
    _det_trace = DetectorTrace(
        trace_id=job_state.trace_id, total=_detector_total
    )
    _det_listener = DetectorTraceListener(_det_trace)
    get_bus().subscribe(_det_listener)
    # The job.started event below is re-emitted below with the
    # total count. We use a one-shot variable to skip the
    # re-emission if the original emit was deferred to here.
    _job_started_emitted = False
    if _detector_total:
        try:
            get_bus().emit(Event(
                "job.started",
                {
                    "trace_id": job_state.trace_id,
                    "filename": pdf_path.name,
                    "detector_count": _detector_total,
                },
            ))
            _job_started_emitted = True
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "job.started event emission failed",
                extra={"err": str(exc)},
            )

    try:
        doc = _parse_pdf(
            pdf_path,
            trace_id=job_state.trace_id,
            workspace_dir=paths.root.parent,
        )

        # Step H3 — checkpoint-aware detector loop.
        #
        # Each detector gets its own try/except. Its result is
        # written to ``steps/NN_<name>.json`` the moment it
        # finishes, ok or not, so a crash partway through loses at
        # most one detector's work. On a fresh run, the runner
        # first checks each step's checkpoint file and skips the
        # detector if the file exists and ``ok=True``.
        detectors_run: list[str] = []
        results: list[DetectorResult] = []

        for idx, cls in enumerate(_detector_classes):
            name = cls().name
            step_file = paths.step_path(idx, name)
            # R-2026-06-13: detector-trace instrumentation. Emit
            # ``detector.started`` BEFORE the detector runs so the
            # TUI's progress block can show the "running" state.
            # The phase is empty for now; detectors that emit
            # mid-run progress (e.g. OCR step) will call
            # ``emit_progress`` themselves. The skip heuristic
            # decides BEFORE the run whether to emit
            # ``detector.skipped`` instead.
            from .detector_trace import (
                DetectorTrace,
                emit_done,
                emit_error,
                emit_skipped,
                emit_started,
                should_skip_detector,
            )
            # R-2026-06-13: only apply the skip heuristic to
            # built-in detectors. Plugin (entry-point) detectors
            # were explicitly installed by the user; the heuristic
            # must not second-guess their intent (e.g. a plugin
            # with a ``citation_network``-style name is not the
            # same as the built-in citation_network detector).
            _is_builtin = cls.__name__ in _BUILTIN_DETECTOR_CLASS_NAMES
            skip_it, skip_reason = should_skip_detector(
                name, doc, is_builtin=_is_builtin
            )
            if skip_it:
                try:
                    emit_skipped(
                        job_state.trace_id, name, skip_reason
                    )
                except Exception:  # noqa: BLE001
                    pass
                # Still record the skip as a DetectorResult so the
                # downstream pipeline sees a deterministic entry.
                res = DetectorResult(
                    detector=name,
                    ok=True,
                    findings=[],
                    duration_ms=0,
                )
                # Persist a checkpoint so a resume re-runs would
                # also be a no-op.
                try:
                    write_step(step_file, res)
                except OSError as exc:  # pragma: no cover
                    log.warning(
                        "could not write step file (skip)",
                        extra={
                            "path": str(step_file),
                            "err": str(exc),
                        },
                    )
                detectors_run.append(name)
                results.append(res)
                # Still emit a job.step_completed for parity with
                # the non-skip path -- the trace contract says one
                # step_completed per detector.
                try:
                    get_bus().emit(Event(
                        "job.step_completed",
                        {
                            "trace_id": job_state.trace_id,
                            "detector": name,
                            "ok": True,
                            "duration_ms": 0,
                            "findings_count": 0,
                            "skipped": True,
                            "skip_reason": skip_reason,
                        },
                    ))
                except Exception:  # noqa: BLE001
                    pass
                continue
            cached = read_step_silent(step_file) if step_file.exists() else None
            if cached is not None and cached.ok:
                # Resume: this detector already finished, reuse it.
                log.info(
                    "detector step cached; skipping rerun",
                    extra={"detector": name, "step": str(step_file.name)},
                )
                detectors_run.append(name)
                results.append(cached)
                # R-2026-06-13: also emit detector.started + done
                # for resumed steps so the TUI trace reflects the
                # full lifecycle (otherwise the TUI's "done" count
                # would undercount).
                try:
                    emit_started(job_state.trace_id, name)
                    emit_done(
                        job_state.trace_id,
                        name,
                        int(getattr(cached, "duration_ms", 0) or 0),
                        len(cached.findings),
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue
            # Otherwise run the detector and write its step.
            t0 = time.time()
            # R-2026-06-13: emit detector.started before run().
            try:
                emit_started(job_state.trace_id, name)
            except Exception:  # noqa: BLE001
                pass
            try:
                res = cls().run(doc)
            except Exception as exc:  # noqa: BLE001 — isolation is the point
                log.exception(
                    "detector crashed", extra={"detector": name}
                )
                crashed = Finding.make(
                    trace_id=doc.trace_id,
                    detector=name,
                    severity="info",
                    title=f"{name} crashed",
                    evidence=(
                        f"Detector raised: {type(exc).__name__}: {exc}"
                    ),
                    location="(pipeline)",
                    raw={"exception": repr(exc)},
                )
                res = DetectorResult(
                    detector=name,
                    ok=False,
                    findings=[crashed],
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((time.time() - t0) * 1000),
                )
                # R-2026-06-13: emit detector.error.
                try:
                    emit_error(
                        job_state.trace_id,
                        name,
                        res.error or "",
                        int(res.duration_ms or 0),
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                # Decorate with duration — cls.run() may not have.
                res = DetectorResult(
                    detector=res.detector,
                    ok=res.ok,
                    findings=res.findings,
                    error=res.error,
                    duration_ms=int((time.time() - t0) * 1000) or res.duration_ms,
                )
                # R-2026-06-13: emit detector.done.
                try:
                    emit_done(
                        job_state.trace_id,
                        name,
                        int(res.duration_ms or 0),
                        len(res.findings),
                    )
                except Exception:  # noqa: BLE001
                    pass
            # Persist the step atomically before doing anything else.
            try:
                write_step(step_file, res)
            except OSError as exc:  # pragma: no cover — disk full etc.
                log.warning(
                    "could not write step file",
                    extra={"path": str(step_file), "err": str(exc)},
                )
            detectors_run.append(name)
            results.append(res)
            # E3: emit job.step_completed
            # so a webhook consumer can
            # react to per-detector
            # outcomes. The ``ok`` field
            # is the per-detector status;
            # ``duration_ms`` is the
            # wall-clock time spent in
            # the detector; ``findings_count``
            # is the size of the
            # detector's findings list.
            try:
                get_bus().emit(Event(
                    "job.step_completed",
                    {
                        "trace_id": job_state.trace_id,
                        "detector": name,
                        "ok": res.ok,
                        "duration_ms": res.duration_ms,
                        "findings_count": len(res.findings),
                    },
                ))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "job.step_completed event emission failed",
                    extra={"err": str(exc)},
                )
            # Live progress notification. Errors here must not
            # break the pipeline — the hook is a UI nicety.
            if on_step_complete is not None:
                try:
                    on_step_complete(res, job_state)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "on_step_complete hook raised",
                        extra={"err": str(exc)},
                    )

        # Flatten DetectorResult envelopes into the list of Finding
        # objects the rest of the pipeline + report builder expects.
        findings: list[Finding] = []
        for r in results:
            findings.extend(r.findings)
        if any(not r.ok for r in results):
            failed = [r.detector for r in results if not r.ok]
            log.warning(
                "some detectors failed",
                extra={"failed": failed, "results": len(results)},
            )

        llm_calls = _enrich_with_llm(findings)

        # R-2026-06-13: build the detector summary from the
        # in-memory trace (same data the TUI's
        # DetectorTraceBlock consumes) and pass it to the
        # report builder. The builder renders it as the
        # ``Detector summary`` block at the top of the
        # report. If the trace is empty (legacy / non-
        # detector callers), the block is omitted -- the
        # meta line still lists the detector names.
        try:
            detector_summary_dict = _det_trace.to_summary()
        except Exception:  # noqa: BLE001
            detector_summary_dict = {}

        html = build_report_html(
            trace_id=job_state.trace_id,
            findings=findings,
            detectors_run=detectors_run,
            llm_calls=llm_calls,
            settings=settings,
            detector_summary=detector_summary_dict,
        )
        paths.report_html.write_text(html, encoding="utf-8")

        duration_ms = int((time.time() - t0) * 1000)
        result = AnalysisResult(
            trace_id=job_state.trace_id,
            findings=findings,
            detectors_run=detectors_run,
            llm_calls=llm_calls,
            duration_ms=duration_ms,
        )
        _persist_findings(paths, result)

        job_state.status = "done"
        job_state.finished_at = time.time()
        job_state.detectors_run = detectors_run
        job_state.finding_count = len(findings)
        job_state.duration_ms = duration_ms
        _persist_job_state(paths, job_state)

        log.info(
            "pipeline done",
            extra={"findings": len(findings), "ms": duration_ms},
        )
        # E3: emit job.completed. A
        # webhook consumer that just
        # listens for this event can
        # skip the per-step events and
        # be notified when the job is
        # fully done.
        try:
            get_bus().emit(Event(
                "job.completed",
                {
                    "trace_id": job_state.trace_id,
                    "total_findings": len(findings),
                    "llm_calls": 0,
                    "duration_ms": duration_ms,
                },
            ))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "job.completed event emission failed",
                extra={"err": str(exc)},
            )
        # R-2026-06-13: write the detector-trace summary to disk
        # AND unsubscribe the listener. The summary is what the
        # HTML report loader uses to render the final
        # ``detectors 38/38 done · 5 findings · 7 skipped · 0
        # errors`` block.
        try:
            write_summary(
                paths.root / "detector_summary.json", _det_trace
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "detector_summary.json write failed",
                extra={"err": str(exc)},
            )
        try:
            get_bus().unsubscribe(_det_listener)
        except Exception:  # noqa: BLE001
            pass
        return result

    except Exception as exc:  # noqa: BLE001 — the route needs the error message
        log.exception("pipeline failed")
        job_state.status = "failed"
        job_state.finished_at = time.time()
        job_state.error = f"{type(exc).__name__}: {exc}"
        _persist_job_state(paths, job_state)
        # E3: emit job.failed. A
        # webhook consumer that listens
        # for this event can page the
        # operator. The original
        # exception is preserved on
        # ``error`` so a downstream
        # system can route on the
        # exception type.
        try:
            get_bus().emit(Event(
                "job.failed",
                {
                    "trace_id": job_state.trace_id,
                    "error": str(exc),
                },
            ))
        except Exception as emit_exc:  # noqa: BLE001
            log.warning(
                "job.failed event emission failed",
                extra={"err": str(emit_exc)},
            )
        # R-2026-06-13: even on failure, write a partial detector
        # summary so the report HTML can show what got done
        # before the crash.
        try:
            write_summary(
                paths.root / "detector_summary.json", _det_trace
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            get_bus().unsubscribe(_det_listener)
        except Exception:  # noqa: BLE001
            pass
        raise
