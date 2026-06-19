"""Per-job file layout.

All artifacts for one analysis live under::

    <workspace_dir>/<trace_id>/
        original.pdf           uploaded file
        job.json               job state + summary
        findings.json          AnalysisResult (raw, for evals)
        report.html            human-readable report
        steps/                 per-detector checkpoints (Step H3)
            00_metadata.json
            01_image_dup.json
            02_image_forensics.json
            03_text_patterns.json

Each ``steps/NN_<name>.json`` is the serialized ``DetectorResult``
for that step. The pipeline reads them at startup so a job that
crashed mid-run can be resumed: detectors whose step file is
present and ``ok=True`` are skipped. (Borrowed from LangGraph's
"checkpoint per super-step" pattern, but per-file rather than per-
graph because our pipeline is a flat sequence, not a graph.)

The directory is created lazily on first access. We never write
outside this directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobPaths:
    trace_id: str
    root: Path

    @classmethod
    def for_trace(cls, trace_id: str, workspace_dir: Path) -> "JobPaths":
        return cls(trace_id=trace_id, root=workspace_dir / trace_id)

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def original(self) -> Path:
        return self.root / "original.pdf"

    @property
    def job_json(self) -> Path:
        return self.root / "job.json"

    @property
    def findings_json(self) -> Path:
        return self.root / "findings.json"

    @property
    def report_html(self) -> Path:
        return self.root / "report.html"

    @property
    def steps_dir(self) -> Path:
        return self.root / "steps"

    def step_path(self, index: int, detector: str) -> Path:
        """Per-detector checkpoint file. ``index`` is the 0-based
        position in the pipeline's detector list (so files sort
        naturally in shell listings). ``detector`` is the
        detector's name."""
        safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in detector)
        return self.steps_dir / f"{index:02d}_{safe}.json"

    def list_step_files(self) -> list[Path]:
        """Return step checkpoint files in pipeline order.

        Returns an empty list if ``steps/`` does not exist yet.
        Files that do not match the ``NN_<name>.json`` pattern are
        ignored (defensive — the directory is shared with the
        user and could in theory have unrelated files)."""
        if not self.steps_dir.exists():
            return []
        out: list[Path] = []
        for p in sorted(self.steps_dir.iterdir()):
            name = p.name
            if not (name.endswith(".json") and len(name) >= 4 and name[2] == "_"):
                continue
            out.append(p)
        return out
