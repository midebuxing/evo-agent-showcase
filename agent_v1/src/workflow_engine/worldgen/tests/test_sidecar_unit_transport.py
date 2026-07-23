"""sidecar 数值行量纲全链运输（q6 裁定链，2026-07-08）。"""

from __future__ import annotations

import random

from workflow_engine.worldgen.sidecar import _sample_sidecar_facts_for_fragment


def test_numeric_row_carries_registry_unit() -> None:
    records = [{
        "slot_id": "ratio.covered_structure_area.inspected",
        "value_type": "ratio", "unit": "ratio",
        "carrier_domain": "inspection_execution",
        "physical_bounds": [0.0, 1.0], "typical_bounds": [0.2, 0.9],
        "recommended_distribution": "uniform",
        "recommended_mean": 0.5, "recommended_sigma": 0.1,
        "precision_steps": 0.01,
    }]
    buckets = _sample_sidecar_facts_for_fragment("WB", "FR1", records, random.Random(1))
    rows = [v for vs in buckets.values() for v in vs]
    assert rows and rows[0].unit == "ratio"
