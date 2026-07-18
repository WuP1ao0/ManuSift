"""Pipeline/registry drift guard (2026-07, fraud_web_v1 follow-up).

The detector registry (``manusift.detectors._DETECTOR_SPECS``) and
the offline pipeline's class list
(``manusift.pipeline._BUILTIN_DETECTOR_CLASS_NAMES``) used to drift
silently: detectors were registered but never ran in the pipeline,
which cost real benchmark recalls (text_tortured_phrases and
paper_mill_template on fraud_web_v1).

Rule: every registry class must be either
  1. in the pipeline list, or
  2. documented in ``pipeline.PIPELINE_EXCLUDED`` with a non-empty
     reason.
"""
from __future__ import annotations


def test_registry_pipeline_no_silent_drift() -> None:
    from manusift.detectors import _DETECTOR_SPECS
    from manusift.pipeline import (
        _BUILTIN_DETECTOR_CLASS_NAMES,
        PIPELINE_EXCLUDED,
    )

    registry = {spec.class_name for spec in _DETECTOR_SPECS}
    in_pipeline = set(_BUILTIN_DETECTOR_CLASS_NAMES)
    excluded = set(PIPELINE_EXCLUDED)

    # No overlap between pipeline and excluded.
    overlap = in_pipeline & excluded
    assert not overlap, (
        f"classes both in pipeline and PIPELINE_EXCLUDED: {overlap}"
    )

    # Every registry class is accounted for.
    undocumented = registry - in_pipeline - excluded
    assert not undocumented, (
        f"registry classes neither in pipeline nor documented in "
        f"PIPELINE_EXCLUDED: {undocumented} -- add them to one of "
        f"the two lists in manusift/pipeline.py"
    )

    # Every exclusion documents an existing class and a reason.
    for class_name, reason in PIPELINE_EXCLUDED.items():
        assert class_name in registry, (
            f"PIPELINE_EXCLUDED mentions unknown class {class_name!r}"
        )
        assert reason and reason.strip(), (
            f"PIPELINE_EXCLUDED[{class_name!r}] has no reason"
        )

    # Every pipeline class exists in the registry.
    unknown = in_pipeline - registry
    assert not unknown, (
        f"pipeline classes missing from the registry: {unknown}"
    )
