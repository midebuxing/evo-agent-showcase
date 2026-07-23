"""Round-trip tests for RegulationProjectionResults.v2 parquet I/O (2026-05-10).

Results.v2 顶层 schema 跟 WorldgenNormativeProjection.v2 几乎同构，只差 meta 字段:
  - Results 有 buildings_count, 没有 registry_bundle_hash / deterministic_key
  - NormativeProjection 反过来

复用 worldgen.parquet_io 的 NormativeProjection writer/reader, 通过 _write/_read
projection_results_parquet 包一层 strip + buildings_count 回填.

测试目标:
  payload (dict) → write parquet dir → read → 与原始 payload 完全等价 (递归 dict 比较).
  注意 buildings_count 由 reader 重算, 跟原 payload 里的值会一致 (assuming caller 给的
  buildings_count == len(buildings)).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    _read_projection_results_parquet,
    _write_projection_results_parquet,
    is_projection_results_parquet_dir,
)


def _sample_results_payload() -> dict:
    """Results.v2 payload — 跟 sample_projection_payload 同构, 仅 meta 字段差异."""
    return {
        "version": "regulation_projection.results.v2",
        "generated_at": "2026-05-10T00:00:00+00:00",
        "buildings_count": 1,
        "buildings": [
            {
                "world_id": "WB-TESTSEED-S00042",
                "projection_count": 1,
                "projections": [
                    {
                        "projection_id": "NP-FRG-TEST-A-00-00",
                        "projection_registry_id": "NP_TEST_V1",
                        "projection_family": "mbis.inspection.test",
                        "world_id": "WB-TESTSEED-S00042",
                        # SA-2: NormativeProjection 必填字段，须 parquet 往返保全.
                        "fragment_id": "FRG-TEST-A",
                        "expected_verdict": "pass",
                        "projection_version": "2.0.0",
                        "matched_families": [
                            {
                                "family_id": "mbis.inspection.test",
                                "applicability_score": 0.5,
                                "applicability_state": "applicable",
                                "trigger_ids": ["t1"],
                                "rule_ids": [],
                                "slot_role_map": {"slot_x": "role_y"},
                                "threshold_evaluations": [
                                    {"rule_id": "rc.t.c01",
                                     "threshold_regime_id": "rc.t.c01.t01",
                                     "slot_id": "duration.x",
                                     "operator": "==", "threshold_value": 7.0,
                                     "observed_value": 7.0, "regime_tag": "exact_threshold",
                                     "pass_bool": True},
                                ],
                                "verdict": "covered",
                            },
                        ],
                        "selected_family": "mbis.inspection.test",
                        "projection_status": "covered",
                        "required_slots": ["a", "b"],
                        "basis_items": [
                            {"basis_kind": "threshold_compare", "basis_id": "b1",
                             "family_id": "mbis.inspection.test", "rule_id": "rc.t.c01",
                             "slot_id": "duration.x", "source_projection_id": "",
                             "operator": "==", "threshold_value": 7.0, "unit": "day",
                             "regime_tag": "exact_threshold", "expected_value": None,
                             "statement_code": None, "reason_code": None,
                             "candidate_known_families": [], "observed_value": 7.0,
                             "pass_bool": True, "source_ref": ""},
                        ],
                        "unknown_reason_code": None,
                        "sidecar_join_status": "available",
                        "severity_band": "severe",
                        "required_world_core_slots": ["s1"],
                        "required_measurement_slots": ["m1"],
                        "required_qualifier_slots": ["q1", "q2"],
                        "required_sidecar_interfaces": ["i1"],
                        "matched_component_refs": ["c1"],
                        "matched_measurement_ids": ["m_id_1"],
                        "coverage_status": "world_core_ready",
                        "notes": [],
                    },
                ],
            },
        ],
    }


def test_results_parquet_roundtrip(tmp_path: Path) -> None:
    """write → read → 完全等价 (含 buildings_count 重算)."""
    payload = _sample_results_payload()
    out = _write_projection_results_parquet(tmp_path / "results_pq", payload)
    assert out.is_dir(), "writer 应返回 parquet directory"
    restored = _read_projection_results_parquet(out)

    # buildings_count 由 reader 重算 (len(buildings))
    assert restored["buildings_count"] == payload["buildings_count"]
    # 关键：不应混入 NormativeProjection-only 字段 (writer 透传 None, reader 删掉)
    assert "registry_bundle_hash" not in restored
    assert "deterministic_key" not in restored
    # 顶层等价
    assert restored == payload, f"roundtrip mismatch:\nEXPECTED={payload}\n\nACTUAL={restored}"


def test_results_parquet_empty_buildings(tmp_path: Path) -> None:
    """空 buildings list — schema 不能崩."""
    payload = {
        "version": "regulation_projection.results.v2",
        "generated_at": "2026-05-10T00:00:00+00:00",
        "buildings_count": 0,
        "buildings": [],
    }
    out = _write_projection_results_parquet(tmp_path / "results_empty", payload)
    restored = _read_projection_results_parquet(out)
    assert restored == payload


def test_is_projection_results_parquet_dir_detector(tmp_path: Path) -> None:
    """detector 应识别已写出的 parquet directory."""
    payload = _sample_results_payload()
    out = _write_projection_results_parquet(tmp_path / "results_detect", payload)
    assert is_projection_results_parquet_dir(out)
    # 普通空目录不是
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not is_projection_results_parquet_dir(empty)


def test_results_parquet_compression_smoke(tmp_path: Path) -> None:
    """Smoke check: parquet 比 JSON 序列化小."""
    import json as _json
    base = _sample_results_payload()
    one_b = base["buildings"][0]
    base["buildings"] = []
    for i in range(50):
        bw = _json.loads(_json.dumps(one_b))  # deep copy
        bw["world_id"] = f"WB-TESTSEED-S{i:05d}"
        base["buildings"].append(bw)
    base["buildings_count"] = len(base["buildings"])
    json_bytes = len(_json.dumps(base, ensure_ascii=False).encode("utf-8"))
    out = _write_projection_results_parquet(tmp_path / "results_compress", base)
    pq_bytes = sum(p.stat().st_size for p in out.glob("*.parquet"))
    assert pq_bytes < json_bytes, (
        f"parquet ({pq_bytes}) NOT smaller than JSON ({json_bytes})"
    )
    print(
        f"[smoke] json={json_bytes/1024:.1f}KB parquet={pq_bytes/1024:.1f}KB "
        f"ratio={json_bytes/pq_bytes:.2f}x"
    )
