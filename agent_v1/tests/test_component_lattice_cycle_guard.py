"""subsumption 任意长度有向环检测（护栏缺口 1，2026-07-27）。

缺口：`load_component_lattice` 只拒二元环（A⇄B），三节点以上的环
（A→B→C→A）会被接受。后果：祖先遍历（`obligation_deriver.py`）把环上
类型当有效祖先 ⇒ 错误绑定事实 ⇒ 本应阻断的义务被关闭 ⇒ 放过真实违规。

本文件用**最小真实构造**：完整走真加载器 `load_component_lattice`，
资产 dict 除 subsumption 外全部满足 §2.3 校验（词表二分 / disjoint 下界
覆盖 / 双快照哈希 / bundle 绑定），确保测试红的唯一原因是环检测本身。
"""
from __future__ import annotations

import itertools

import pytest

from evo_agent_baseline.closure.component_lattice import (
    LatticeIngestError,
    canonical_hash,
    load_component_lattice,
)

_LEAF = ["leaf_a", "leaf_b"]
_BUNDLE = "rulecard_v2.test"


def _lattice_doc(subsumption: dict, non_leaf: list) -> dict:
    """造一个除 subsumption 外**全部合法**的类型格资产 dict。"""
    domain = sorted(_LEAF + list(non_leaf))
    alias_map: dict = {}
    return {
        "rulecard_bundle_id": _BUNDLE,
        "leaf_types": list(_LEAF),
        "non_leaf_types": list(non_leaf),
        "disjoint_pairs": [list(c) for c in itertools.combinations(_LEAF, 2)],
        "subsumption": subsumption,
        "vocabulary_snapshot_sha256": canonical_hash(sorted(domain)),
        "alias_mapping_snapshot_sha256": canonical_hash(alias_map),
    }


def _load(subsumption: dict, non_leaf: list):
    return load_component_lattice(
        _lattice_doc(subsumption, non_leaf),
        vocab_domain=sorted(_LEAF + list(non_leaf)),
        alias_map={},
        expected_bundle_id=_BUNDLE,
    )


def test_three_node_cycle_is_rejected():
    """🔴 核心缺口：A→B→C→A 必须 hard-fail（修复前会被接受）。"""
    with pytest.raises(LatticeIngestError, match="成环"):
        _load({"a": ["b"], "b": ["c"], "c": ["a"]}, ["a", "b", "c"])


def test_four_node_cycle_with_tail_is_rejected():
    """环不必覆盖全部节点：挂叶子的四节点环同样要拒。"""
    sub = {"a": ["b", "leaf_a"], "b": ["c"], "c": ["d"], "d": ["a"]}
    with pytest.raises(LatticeIngestError, match="成环"):
        _load(sub, ["a", "b", "c", "d"])


def test_two_node_cycle_still_rejected():
    """二元环是原有行为，锁住防回退。"""
    with pytest.raises(LatticeIngestError, match="成环"):
        _load({"a": ["b"], "b": ["a"]}, ["a", "b"])


def test_acyclic_multi_level_chain_is_accepted():
    """正对照：多级无环链（DEBT-076 合法形态）不得被误杀。"""
    lattice = _load(
        {"top": ["mid", "leaf_b"], "mid": ["leaf_a"]},
        ["top", "mid"],
    )
    assert lattice.subsumption["top"] == frozenset({"mid", "leaf_b"})
