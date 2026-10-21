# aind-contraqctor-to-schema-export

[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
![Code Style](https://img.shields.io/badge/code%20style-ruff-black)
[![semantic-release: angular](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)
![Interrogate](https://img.shields.io/badge/interrogate-100.0%25-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![Python](https://img.shields.io/badge/python->=3.12-blue?logo=python)

Export [contraqctor](https://github.com/AllenNeuralDynamics/contraqctor) QC results to
[aind-data-schema](https://github.com/AllenNeuralDynamics/aind-data-schema) `QualityControl`
objects for the AIND QC portal. Shared by the dynamic foraging and VR foraging QC pipelines.

## What it does

`results_to_metrics` turns the grouped results of a contraqctor `Runner` into `QCMetric`s:

- **Names are unique per session:** `"<test>:<group>"`, plus `":<n>"` for a test that yields
  several results in one group (e.g. `HarpHubTestSuite`'s per-device checks).
- **Tags match the portal grouping:** every metric carries exactly
  `{"type": "Harp QC Suite", "group": "<runner group>"}`, so `DEFAULT_GROUPING = ["type", "group"]`
  builds a two-level tree (type, then device or stream).
- **Nothing reported is dropped:** a test's figure (attached with
  `ContextExportableObj.as_context`) is saved and becomes the metric's `reference`; any other
  `context` it reports (e.g. which registers lost Harp messages) is kept in the metric's `value`
  as `{"result": ..., "context": ...}`.

`build_quality_control` wraps the metrics (yours plus any you compute yourself) in a
`QualityControl`:

- **contraqctor failures don't fail the session:** `allow_tag_failures` defaults to
  `["type:Harp QC Suite"]`, so these metrics show as failed in the portal but the overall QC
  status ignores them. Metrics with any other `type` still count. contraqctor warnings and
  errors are mapped to `Fail` too (skips to `Pass`), so they are excused the same way instead of
  holding the session at `Pending`.
- **Duplicate names fail loudly:** it raises `ValueError` on duplicate metric names, which the
  portal would otherwise silently drop.

## Usage

```python
from aind_contraqctor_to_schema_export import build_quality_control, results_to_metrics

results = runner.run_all()  # a contraqctor qc.Runner
metrics = results_to_metrics(results, results_folder="/results/qc")
quality_control = build_quality_control(metrics)
```

`qc_type`, `modality` and `stage` can be passed to `results_to_metrics` to override the
defaults (`"Harp QC Suite"`, behavior, raw).

## Installation

```bash
uv sync
```
