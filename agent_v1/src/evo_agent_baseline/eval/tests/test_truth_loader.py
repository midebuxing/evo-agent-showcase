"""truth_loader.py 单测（spec §8.2）。

用 fixture 造一个 5 表齐全的 parquet 目录验证加载；并验证缺表 / 缺目录报错。
"""

from __future__ import annotations

import pandas as pd
import pytest

from evo_agent_baseline.eval.truth_loader import (
    TRUTH_TABLE_FILES,
    TruthLoadError,
    load_truth_bundle,
)


def _write_minimal_truth_dir(root) -> str:
    """在 root 下写 5 张最小 W2 真值 parquet，返回目录路径。"""
    pd.DataFrame([{"version": "v2"}]).to_parquet(
        root / "normative_projection_meta.parquet"
    )
    pd.DataFrame(
        [{"world_id": "WB-1", "fragment_id": "F1", "projection_id": "NP-1",
          "projection_family": "mbis.inspection.drainage",
          "expected_verdict": "fail"}]
    ).to_parquet(root / "projections.parquet")
    pd.DataFrame(
        [{"projection_id": "NP-1", "family_id": "mbis.inspection.drainage",
          "verdict": "fail"}]
    ).to_parquet(root / "matched_families.parquet")
    pd.DataFrame(
        [{"projection_id": "NP-1", "rule_id": "rc.x", "slot_id": "s",
          "operator": ">", "pass_bool": True}]
    ).to_parquet(root / "threshold_evaluations.parquet")
    pd.DataFrame(
        [{"projection_id": "NP-1", "basis_id": "BI-1", "basis_kind": "x"}]
    ).to_parquet(root / "basis_items.parquet")
    return str(root)


def test_load_truth_bundle_reads_all_five_tables(tmp_path):
    """5 表齐全时 load_truth_bundle 成功，各 DataFrame 非空。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)
    bundle = load_truth_bundle(truth_dir)
    assert len(bundle.projections) == 1
    assert len(bundle.matched_families) == 1
    assert len(bundle.threshold_evaluations) == 1
    assert len(bundle.basis_items) == 1
    assert set(TRUTH_TABLE_FILES.keys()).issubset(set(bundle.loaded_tables))
    assert bundle.backend in {"pandas", "duckdb"}


def test_projection_family_index(tmp_path):
    """projection_family_index 返回 projection_id → coarse family 映射。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)
    bundle = load_truth_bundle(truth_dir)
    idx = bundle.projection_family_index()
    assert idx["NP-1"] == "mbis.inspection.drainage"


def test_missing_dir_raises(tmp_path):
    """目录不存在 → TruthLoadError。"""
    with pytest.raises(TruthLoadError):
        load_truth_bundle(str(tmp_path / "no_such_dir"))


def test_missing_table_raises(tmp_path):
    """缺一张必需表 → TruthLoadError。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)
    (tmp_path / "basis_items.parquet").unlink()
    with pytest.raises(TruthLoadError):
        load_truth_bundle(truth_dir)


def test_pandas_fallback_when_duckdb_unavailable(tmp_path):
    """prefer_duckdb=False 强制 pandas 后端，仍能正确加载。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)
    bundle = load_truth_bundle(truth_dir, prefer_duckdb=False)
    assert bundle.backend == "pandas"
    assert len(bundle.projections) == 1


def test_truth_schema_defaults_to_v1_when_meta_lacks_column(tmp_path):
    """DEBT-054 Block B.3：旧 bundle meta 无 truth_schema 列 → truth_v1（legacy 只读）。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)  # meta 仅 {"version": "v2"}
    bundle = load_truth_bundle(truth_dir)
    assert bundle.truth_schema == "truth_v1"


def test_truth_schema_read_from_meta_column(tmp_path):
    """含 truth_schema 列的新 bundle → 读回该版本号。"""
    truth_dir = _write_minimal_truth_dir(tmp_path)
    pd.DataFrame([{"version": "v2", "truth_schema": "truth_v2_regime"}]).to_parquet(
        tmp_path / "normative_projection_meta.parquet"
    )
    bundle = load_truth_bundle(truth_dir)
    assert bundle.truth_schema == "truth_v2_regime"
