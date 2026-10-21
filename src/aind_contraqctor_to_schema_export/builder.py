"""Assemble an ``aind_data_schema`` ``QualityControl`` object from metrics.

Collects a flat list of metrics into a single ``QualityControl``, wiring up
``default_grouping`` so the QC portal groups metrics by their ``type`` tag and
then by ``group``, and ``allow_tag_failures`` so failing ``contraqctor`` checks
are reported without failing the session's overall QC.
"""

import typing as t
from collections import Counter

from aind_data_schema.core.quality_control import QCMetric, QualityControl

from aind_contraqctor_to_schema_export.convert import GROUP_TAG, QC_TYPE, TYPE_TAG

#: Split on ``type`` (e.g. "Harp QC Suite"), then ``group`` (the device or
#: stream). Every metric must carry exactly these two tag keys, so the portal
#: can build the tree.
DEFAULT_GROUPING = [TYPE_TAG, GROUP_TAG]

#: Tags whose metric failures do not fail the overall QC: every converted
#: ``contraqctor`` metric (``type:Harp QC Suite``). The ``key:value`` form
#: matches the ``type`` tag only, never a ``group`` that happens to share the
#: value. Metrics with any other ``type`` (e.g. a pipeline's own behavior
#: metrics) still fail the session.
DEFAULT_ALLOW_TAG_FAILURES = [f"{TYPE_TAG}:{QC_TYPE}"]


def build_quality_control(
    metrics: t.List[QCMetric],
    *,
    default_grouping: t.Optional[t.List[t.Union[str, t.Tuple[str, ...]]]] = None,
    allow_tag_failures: t.Optional[t.List[str]] = None,
    key_experimenters: t.Optional[t.List[str]] = None,
    notes: t.Optional[str] = None,
) -> QualityControl:
    """Wrap a flat list of metrics into a ``QualityControl`` object.

    Parameters
    ----------
    metrics : list of QCMetric
        All metrics for the session, e.g. converted ``contraqctor`` results
        together with any metrics the caller computes itself.
    default_grouping : list of str or tuple of str, optional
        Tag keys the portal groups by, one tree level per entry; a tuple splits
        on any of its keys at that level. Defaults to :data:`DEFAULT_GROUPING`.
    allow_tag_failures : list of str, optional
        Tag values (or ``"key:value"`` pairs) whose metric failures should not
        fail the overall QC. Defaults to :data:`DEFAULT_ALLOW_TAG_FAILURES`;
        when converting with a custom ``qc_type``, pass the matching
        ``"type:<qc_type>"`` here instead.
    key_experimenters : list of str, optional
        Experimenters associated with the session.
    notes : str, optional
        Free-text notes.

    Returns
    -------
    QualityControl
        The assembled quality-control object.

    Raises
    ------
    ValueError
        If two metrics share a name. The QC portal identifies metrics by name
        and silently drops every metric with a duplicated one, so this fails
        instead.
    """
    counts = Counter(metric.name for metric in metrics)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"QC metric names must be unique; duplicated: {duplicates}")
    return QualityControl(
        metrics=metrics,
        default_grouping=default_grouping if default_grouping is not None else DEFAULT_GROUPING,
        allow_tag_failures=(
            allow_tag_failures if allow_tag_failures is not None else DEFAULT_ALLOW_TAG_FAILURES
        ),
        key_experimenters=key_experimenters,
        notes=notes,
    )
