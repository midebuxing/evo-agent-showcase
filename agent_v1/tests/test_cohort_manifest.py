"""cohort_manifest.py 单测 — B.5 外置 append-only 双层 hash（DEBT-054 Phase 0 v4 Block B.5）."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.cohort_manifest import (  # noqa: E402
    append_cohort_manifest,
    compute_cohort_manifest,
    compute_tree_hash,
    file_entry,
    read_cohort_manifest,
)


def _files(a="alpha", b="beta"):
    return [
        {"path": "b.parquet", "sha256": b, "size": 20, "row_count": 2},
        {"path": "a.parquet", "sha256": a, "size": 10, "row_count": 1},
    ]


def _manifest(**over):
    kw = dict(
        identity_schema="",
        truth_schema="truth_v2_regime",
        projection_schema="projection_v2_regime",
        canonical_profile_id="",
        cohort_id="C1",
        config_anchors={"code_commit": "abc"},
    )
    kw.update(over)
    return compute_cohort_manifest(_files(), **kw)


def test_tree_hash_order_independent():
    """tree_hash 对 file entry 输入顺序无关（内部按 path 排序）."""
    forward = _files()
    reversed_ = list(reversed(forward))
    assert compute_tree_hash(forward) == compute_tree_hash(reversed_)


def test_tree_hash_changes_on_byte_change():
    """任一文件 sha256 变 → tree_hash 变."""
    base = compute_tree_hash(_files())
    changed = compute_tree_hash(_files(a="alpha2"))
    assert base != changed


def test_manifest_hash_changes_on_schema_change():
    """schema/profile 标识变（即便文件字节不变）→ manifest_hash 变（B.5 第二条锁）."""
    base = _manifest()
    diff_truth = _manifest(truth_schema="truth_v1")
    diff_profile = _manifest(canonical_profile_id="mbis_canonical_v1")
    assert base["tree_hash"] == diff_truth["tree_hash"]  # 文件不变
    assert base["manifest_hash"] != diff_truth["manifest_hash"]
    assert base["manifest_hash"] != diff_profile["manifest_hash"]


def test_manifest_hash_stable():
    """同输入 → manifest_hash 确定性稳定；cohort_manifest_sha == manifest_hash."""
    m1 = _manifest()
    m2 = _manifest()
    assert m1["manifest_hash"] == m2["manifest_hash"]
    assert m1["cohort_manifest_sha"] == m1["manifest_hash"]


def test_file_entry_real_file(tmp_path):
    """file_entry 计算真实文件 sha256/size."""
    p = tmp_path / "x.parquet"
    p.write_bytes(b"hello")
    fe = file_entry("x.parquet", p, row_count=3)
    assert fe["size"] == 5 and fe["row_count"] == 3 and len(fe["sha256"]) == 64


def test_append_only_and_read(tmp_path):
    """append_cohort_manifest 只追加，read 按序返回."""
    mp = tmp_path / "cohort_manifest.jsonl"
    append_cohort_manifest(mp, _manifest(cohort_id="C1"))
    append_cohort_manifest(mp, _manifest(cohort_id="C2"))
    entries = read_cohort_manifest(mp)
    assert [e["cohort_id"] for e in entries] == ["C1", "C2"]
    # 每行是合法 canonical json（sorted keys）。
    for line in mp.read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_read_missing_returns_empty(tmp_path):
    assert read_cohort_manifest(tmp_path / "nope.jsonl") == []
