"""Smoke tests for ``aind_contraqctor_to_schema_export.builder``."""

import pytest
from aind_data_schema.core.quality_control import Status
from contraqctor import qc as cqc

from aind_contraqctor_to_schema_export import (
    DEFAULT_ALLOW_TAG_FAILURES,
    DEFAULT_GROUPING,
    build_quality_control,
    results_to_metrics,
)


def test_build_quality_control_and_reject_duplicates():
    """Failing contraqctor checks don't fail the session; a duplicated name raises."""
    result = cqc.Result(status=cqc.Status.FAILED, result=False, test_name="t", suite_name="S")
    metrics = results_to_metrics({"A": [result], "B": [result]})

    qc = build_quality_control(metrics)
    assert qc.default_grouping == DEFAULT_GROUPING == ["type", "group"]
    assert qc.allow_tag_failures == DEFAULT_ALLOW_TAG_FAILURES == ["type:Harp QC Suite"]
    assert all(m.status_history[-1].status == Status.FAIL for m in qc.metrics)
    assert qc.evaluate_status() == Status.PASS

    with pytest.raises(ValueError, match=r"duplicated: \['t:A'\]"):
        build_quality_control(metrics + metrics[:1])
