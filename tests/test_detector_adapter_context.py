from __future__ import annotations

import json
from types import SimpleNamespace

from manusift.detectors.base import DetectorResult
from manusift.tools.detector_adapter import DetectorToolAdapter
from manusift.tools.tool import ToolContext


class RecordingDetector:
    name = "recording"

    def __init__(self) -> None:
        self.seen_trace_ids: list[str] = []

    def run(self, doc) -> DetectorResult:
        self.seen_trace_ids.append(doc.trace_id)
        return DetectorResult(detector=self.name, ok=True)


def test_detector_adapter_empty_input_uses_ctx_trace_id_when_current_pdf_is_path(
    tmp_path,
) -> None:
    detector = RecordingDetector()
    adapter = DetectorToolAdapter(detector)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    ctx = ToolContext(
        trace_id="abc123ef",
        current_pdf=str(pdf),
        metadata={"parsed_doc": SimpleNamespace(trace_id="abc123ef")},
    )

    raw = adapter.execute({}, ctx)

    payload = json.loads(raw)
    assert payload["ok"] is True
    assert detector.seen_trace_ids == ["abc123ef"]


def test_detector_adapter_still_accepts_legacy_current_pdf_trace_id() -> None:
    detector = RecordingDetector()
    adapter = DetectorToolAdapter(detector)
    ctx = ToolContext(
        trace_id="",
        current_pdf="feed1234",
        metadata={"parsed_doc": SimpleNamespace(trace_id="feed1234")},
    )

    raw = adapter.execute({}, ctx)

    payload = json.loads(raw)
    assert payload["ok"] is True
    assert detector.seen_trace_ids == ["feed1234"]
