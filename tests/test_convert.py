"""Smoke tests for ``aind_contraqctor_to_schema_export.convert``."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from contraqctor import qc as cqc
from contraqctor.qc._context_extensions import ContextExportableObj

from aind_contraqctor_to_schema_export import NO_GROUP, QC_TYPE, results_to_metrics, to_builtin


def _result(status, test, *, value=None, context=None):
    """Build a contraqctor ``Result`` for testing."""
    return cqc.Result(
        status=status,
        result=value,
        test_name=test,
        suite_name="Suite",
        message="m",
        description="d",
        context=context,
    )


def test_to_builtin_converts_nested_numpy_and_rounds_floats():
    """Numpy values at any depth become builtins; floats are rounded."""
    value = {"a": np.float32(39.5634727), "b": [np.int64(2), (1.23456, "x")], "c": np.array([1])}
    assert to_builtin(value) == {"a": 39.563, "b": [2, [1.235, "x"]], "c": [1]}


def test_results_to_metrics_smoke(tmp_path):
    """Names, tags, statuses, figures, and reported context all reach the metrics."""
    fig = plt.figure()
    lick_metrics = {"lick_rate": np.float64(2.5)}
    results = {
        "HarpHub": [
            # A test yielding twice, once with a contraqctor-wrapped figure.
            _result(cqc.Status.PASSED, "sub", context=ContextExportableObj.as_context(fig)),
            _result(cqc.Status.FAILED, "sub"),
            # Details reported only in context (dropped Harp requests).
            _result(cqc.Status.FAILED, "req", context={"register_errors": [{"register": "R"}]}),
            # Context that repeats the result is not duplicated.
            _result(cqc.Status.WARNING, "lick", value=lick_metrics, context=lick_metrics),
        ],
        None: [_result(cqc.Status.PASSED, "solo", value=True)],
    }
    metrics = {m.name: m for m in results_to_metrics(results, str(tmp_path))}
    plt.close(fig)

    names = ["sub:HarpHub:0", "sub:HarpHub:1", "req:HarpHub", "lick:HarpHub", f"solo:{NO_GROUP}"]
    assert list(metrics) == names
    assert metrics["sub:HarpHub:0"].reference == f"{tmp_path.name}/HarpHub_Suite_sub_0.png"
    assert (tmp_path / "HarpHub_Suite_sub_0.png").exists()
    assert metrics["sub:HarpHub:0"].value is None
    assert metrics["req:HarpHub"].value == {
        "result": None,
        "context": {"register_errors": [{"register": "R"}]},
    }
    assert metrics["lick:HarpHub"].value == {"lick_rate": 2.5}
    # Warnings count as failing (the session-level allowance excuses them).
    assert metrics["lick:HarpHub"].status_history[0].status == "Fail"
    assert metrics[f"solo:{NO_GROUP}"].tags == {"type": QC_TYPE, "group": NO_GROUP}
