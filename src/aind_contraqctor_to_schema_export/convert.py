"""Convert ``contraqctor`` QC runner results into ``aind_data_schema`` ``QCMetric`` objects.

Each ``contraqctor`` ``Result`` becomes one ``QCMetric`` named ``"<test>:<group>"``
(plus ``":<n>"`` for a test that yields several results, so names are unique per
session) and tagged with exactly the :data:`~.builder.DEFAULT_GROUPING` keys:
``type`` (the QC portal's top-level group, :data:`QC_TYPE` by default) and
``group`` (the runner group, i.e. the device or stream being checked).

Nothing a test reports is dropped: its figure becomes the metric's
``reference``, and any other ``context`` it attaches (e.g. which registers lost
Harp messages in ``test_request_response``) is kept in the metric's ``value``.
"""

import datetime
import re
import typing as t
from collections import Counter
from pathlib import Path

import matplotlib.figure
import numpy as np
from aind_data_schema.core.quality_control import QCMetric, QCStatus, Stage, Status
from aind_data_schema_models.modalities import Modality
from contraqctor import qc
from contraqctor.qc._context_extensions import ASSET_RESERVED_KEYWORD, ContextExportableObj

#: Tag key holding the QC portal's top-level group.
TYPE_TAG = "type"

#: Tag key holding the runner group (device or stream) a result belongs to.
GROUP_TAG = "group"

#: Default ``type`` tag for converted results (their QC portal group).
QC_TYPE = "Harp QC Suite"

#: Group value used when a runner result has no group.
NO_GROUP = "NoGroup"

#: Decimal places metric values are rounded to when converted for serialization.
VALUE_DECIMALS = 3

#: Map ``contraqctor`` test statuses onto schema statuses. Skips count as
#: passing; warnings count as failing, like failures and errors. None of these
#: fail the session's overall QC, since ``build_quality_control`` allows every
#: converted metric to fail (see :data:`~.builder.DEFAULT_ALLOW_TAG_FAILURES`);
#: a ``PENDING`` status, by contrast, would hold the whole session at pending.
STATUS_CONVERTER: t.Dict[qc.Status, Status] = {
    qc.Status.PASSED: Status.PASS,
    qc.Status.SKIPPED: Status.PASS,
    qc.Status.WARNING: Status.FAIL,
    qc.Status.FAILED: Status.FAIL,
    qc.Status.ERROR: Status.FAIL,
}


def to_builtin(value: t.Any) -> t.Any:
    """Convert numpy scalars/arrays to JSON-serializable Python builtins.

    Recurses into containers: a numpy scalar nested inside a dict, list, tuple,
    or set is converted too. Test results carry whole dicts of numpy values, and
    pydantic refuses to serialize any numpy type that survives.

    Floats are rounded to ``VALUE_DECIMALS`` decimal places — a metric reporting
    ``float32`` sensor readings otherwise writes out its full binary expansion
    (``39.563472747802734``), which is noise rather than precision.

    Parameters
    ----------
    value : Any
        A value that may be a numpy scalar or array, or a container holding
        them at any depth.

    Returns
    -------
    Any
        The equivalent Python builtin (``list`` for arrays and other sequences,
        rounded ``float`` for floating-point values, dicts rebuilt with
        converted keys and values), or ``value`` unchanged when it is neither a
        numpy type, a float, nor a container.
    """
    if isinstance(value, np.ndarray):
        return to_builtin(value.tolist())
    if isinstance(value, np.generic):
        return to_builtin(value.item())
    if isinstance(value, float):
        return round(value, VALUE_DECIMALS)
    if isinstance(value, t.Mapping):
        return {to_builtin(key): to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_builtin(item) for item in value]
    return value


def _sanitize(name: str) -> str:
    """Make ``name`` safe to use as a filename component."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", name)


def _save_asset(
    result: qc.Result,
    group: str,
    results_folder: t.Optional[str],
    index: t.Optional[int] = None,
) -> t.Optional[str]:
    """Save a result's figure asset (if any) and return its relative path.

    ``contraqctor`` tests attach figures with ``ContextExportableObj.as_context``,
    which stores the figure wrapped in a ``ContextExportableObj`` under
    ``context["asset"]``; the wrapper is unwrapped before saving.

    Parameters
    ----------
    result : contraqctor.qc.Result
        A single QC result; its ``context["asset"]`` may wrap a matplotlib figure.
    group : str
        The runner group (device/stream) the result belongs to; part of the
        file name so the same suite run on several devices doesn't overwrite.
    results_folder : str or None
        Directory to save figures into. If ``None``, nothing is saved.
    index : int, optional
        Position of the result among same-named results in its group (see
        :func:`results_to_metrics`); appended to the file name when given.

    Returns
    -------
    str or None
        The saved figure's reference (``"<results-folder-name>/<file>"``), or
        ``None`` when there is no figure asset (or no ``results_folder``). The
        file name combines the (sanitized) group, suite, and test names, e.g. a
        ``CameraTestSuite`` result for ``test_frame_rate`` in the ``BottomCamera``
        group under ``.../qc`` becomes
        ``"qc/BottomCamera_CameraTestSuite_test_frame_rate.png"``, or
        ``"..._test_frame_rate_1.png"`` with ``index=1``.
    """
    context = result.context
    if not isinstance(context, dict):
        return None
    asset = context.get(ASSET_RESERVED_KEYWORD)
    if isinstance(asset, ContextExportableObj):
        asset = asset.asset
    if not isinstance(asset, matplotlib.figure.Figure) or results_folder is None:
        return None
    stem = f"{_sanitize(group)}_{_sanitize(result.suite_name)}_{_sanitize(result.test_name)}"
    filename = f"{stem}.png" if index is None else f"{stem}_{index}.png"
    asset.savefig(Path(results_folder) / filename, dpi=300, bbox_inches="tight")
    # Reference is relative to the top-level results folder, where the QC JSON is
    # written; the images live in the named subfolder alongside it.
    return f"{Path(results_folder).name}/{filename}"


def _metric_value(result: qc.Result) -> t.Any:
    """Return the metric value: the test's result, plus any context it reports.

    ``contraqctor`` tests often report their details in ``context`` rather than
    ``result`` — e.g. ``test_request_response`` fails with ``result=None`` and
    lists the registers whose requests got no response (and when they were
    sent) under ``context["register_errors"]``. That context is kept alongside
    the result so the details reach the QC JSON.

    The figure asset (``context["asset"]``) is excluded, since it is saved as
    the metric's ``reference`` instead (see :func:`_save_asset`). Context that
    only repeats the result (some tests pass the same metrics dict as both) is
    not duplicated.

    Parameters
    ----------
    result : contraqctor.qc.Result
        A single QC result.

    Returns
    -------
    Any
        ``to_builtin(result.result)`` when the result has no other context, or
        ``{"result": ..., "context": ...}`` when it does.
    """
    value = to_builtin(result.result)
    context = result.context
    if isinstance(context, dict):
        context = {key: item for key, item in context.items() if key != ASSET_RESERVED_KEYWORD}
    context = to_builtin(context)
    if not context or context == value:
        return value
    return {"result": value, "context": context}


def results_to_metrics(
    results: t.Dict[t.Optional[str], t.List[qc.Result]],
    results_folder: t.Optional[str] = None,
    *,
    qc_type: str = QC_TYPE,
    modality: Modality.ONE_OF = Modality.BEHAVIOR,
    stage: Stage = Stage.RAW,
) -> t.List[QCMetric]:
    """Convert grouped ``contraqctor`` results into ``QCMetric`` objects.

    Parameters
    ----------
    results : dict
        Mapping of group name to list of ``contraqctor`` ``Result`` objects, as
        returned by ``contraqctor.qc.Runner.run_all``. The keys are the group
        names passed to ``runner.add_suite`` (e.g. ``"HarpBehavior"``,
        ``"HarpHub"``), and each ``Result`` carries its suite's class name as
        ``suite_name``. A ``None`` key becomes :data:`NO_GROUP`.
    results_folder : str, optional
        Directory to save figure assets into. If ``None``, assets are skipped.
    qc_type : str, optional
        Value of every metric's ``type`` tag — the QC portal's top-level group
        for these results. Defaults to :data:`QC_TYPE`.
    modality : Modality, optional
        Modality of every metric. Defaults to ``Modality.BEHAVIOR``.
    stage : Stage, optional
        Processing stage of every metric. Defaults to ``Stage.RAW``.

    Returns
    -------
    list of QCMetric
        One metric per result, named ``"<test>:<group>"`` (``"<test>:<group>:<n>"``
        for a test that yields several results), tagged
        ``{"type": qc_type, "group": group}``, and valued per :func:`_metric_value`.

    Examples
    --------
    A runner produces results grouped roughly like::

        {
            "HarpBehavior": [<HarpDeviceTestSuite results>],
            "HarpLickometerRight": [<HarpDeviceTestSuite results>],
            "HarpHub": [<HarpHubTestSuite results>],
        }

    The same suite (and so the same test names) runs once per device, so the
    group is appended to the test name to keep metric names unique, and also
    goes in the tags (the group implies the suite), e.g. a
    ``HarpDeviceTestSuite`` result in the ``"HarpBehavior"`` group yields::

        name = "test_has_whoami:HarpBehavior"
        tags = {"type": "Harp QC Suite", "group": "HarpBehavior"}

    A test can also yield several results, e.g. ``HarpHubTestSuite`` checks
    each device in turn under one test name (the device is only in the
    message, hence the description). Those are numbered in yield order::

        name = "test_devices_are_subordinate:HarpHub:0"
        name = "test_devices_are_subordinate:HarpHub:1"
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    metrics: t.List[QCMetric] = []
    for group, group_results in results.items():
        group_name = group if group is not None else NO_GROUP
        # Tests that yield several results share a name; number those so each
        # metric name stays unique.
        counts = Counter(result.test_name for result in group_results)
        seen: t.Counter[str] = Counter()
        for result in group_results:
            index: t.Optional[int] = None
            name = f"{result.test_name}:{group_name}"
            if counts[result.test_name] > 1:
                index = seen[result.test_name]
                seen[result.test_name] += 1
                name = f"{name}:{index}"
            status = QCStatus(
                evaluator="Automated",
                status=STATUS_CONVERTER[result.status],
                timestamp=timestamp,
            )
            metrics.append(
                QCMetric(
                    name=name,
                    modality=modality,
                    stage=stage,
                    value=_metric_value(result),
                    status_history=[status],
                    description=f"Test: {result.description} // Message: {result.message}",
                    reference=_save_asset(result, group_name, results_folder, index),
                    tags={TYPE_TAG: qc_type, GROUP_TAG: group_name},
                )
            )
    return metrics
