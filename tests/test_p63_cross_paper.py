"""P6.3: fingerprint index, cross-paper detector, SI PDF list, pattern groups."""
from __future__ import annotations

from pathlib import Path

from manusift.contracts import ExtractedImage, Finding, ParsedDoc
from manusift.detectors.cross_paper_image import CrossPaperImageDetector
from manusift.knowledge.fingerprint_index import (
    append_records,
    hamming_hex,
    index_paper_images,
    query_matches,
)
from manusift.report.investigation_pairs import (
    _pubpeer_pattern_groups,
    build_investigation_pairs_payload,
)


def test_hamming_hex_identical() -> None:
    assert hamming_hex("aabb", "aabb") == 0


def test_index_and_query(tmp_path: Path) -> None:
    idx = tmp_path / "fp.jsonl"
    append_records(
        [
            {
                "paper_id": "paper-A",
                "phash": "0123456789abcdef",
                "page": 0,
                "index": 0,
                "source": "main",
            }
        ],
        path=idx,
    )
    hits = query_matches(
        "0123456789abcdef",
        exclude_paper_id="paper-B",
        max_hamming=0,
        path=idx,
    )
    assert len(hits) == 1
    assert hits[0]["paper_id"] == "paper-A"
    # Same paper excluded
    assert (
        query_matches(
            "0123456789abcdef",
            exclude_paper_id="paper-A",
            path=idx,
        )
        == []
    )


def test_cross_paper_detector_hits_index(tmp_path: Path, monkeypatch) -> None:
    idx = tmp_path / "fp.jsonl"
    monkeypatch.setenv("MANUSIFT_FINGERPRINT_INDEX", str(idx))
    monkeypatch.setenv("MANUSIFT_CROSS_PAPER_IMAGE", "1")
    append_records(
        [
            {
                "paper_id": "other-doi",
                "phash": "aaaaaaaaaaaaaaaa",
                "page": 2,
                "index": 1,
            }
        ],
        path=idx,
    )
    doc = ParsedDoc(
        trace_id="t1",
        source_path="C:/papers/this_paper.pdf",
        text_blocks=[],
        images=[
            ExtractedImage(
                page=0,
                index=0,
                xref=1,
                phash="aaaaaaaaaaaaaaaa",
                width=200,
                height=200,
                bytes_size=20_000,
            )
        ],
        metadata={"doi": "10.1234/this"},
    )
    r = CrossPaperImageDetector().run(doc)
    assert r.findings
    assert r.findings[0].severity in ("high", "medium")
    assert (r.findings[0].raw or {}).get("matched_paper_id") == "other-doi"


def test_list_companion_pdfs(tmp_path: Path) -> None:
    from manusift.ingest.companion_pdf import list_companion_pdfs

    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "Supplementary_Information_MOESM1.pdf").write_bytes(b"%PDF")
    (materials / "notes.txt").write_text("x")
    (materials / "random.pdf").write_bytes(b"%PDF")  # no SI name
    found = list_companion_pdfs(materials)
    assert len(found) == 1
    assert "Supplementary" in found[0].name


def test_pubpeer_pattern_groups_in_payload() -> None:
    findings = [
        Finding.make(
            trace_id="t",
            detector="table_relationships",
            severity="high",
            title="seq reuse",
            evidence="e",
            location="loc",
            raw={"pubpeer_pattern": "source_data_block_paste", "check": "sequence_reuse"},
        ),
        Finding.make(
            trace_id="t",
            detector="table_relationships",
            severity="medium",
            title="seq2",
            evidence="e",
            location="loc",
            raw={"pubpeer_pattern": "source_data_block_paste"},
        ),
        Finding.make(
            trace_id="t",
            detector="image_dup",
            severity="high",
            title="flip",
            evidence="e",
            location="loc",
            raw={"pubpeer_pattern": "image_repositioned_reuse"},
        ),
    ]
    groups = _pubpeer_pattern_groups(findings)
    assert len(groups) == 2
    by = {g["pattern"]: g for g in groups}
    assert by["source_data_block_paste"]["count"] == 2
    assert by["source_data_block_paste"]["max_severity"] == "high"
    payload = build_investigation_pairs_payload(
        trace_id="t", findings=findings
    )
    assert payload.get("pubpeer_pattern_groups")
