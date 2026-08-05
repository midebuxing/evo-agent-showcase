"""适用性 bundle 加载边界的排斥对形状校验（护栏缺口 2，2026-07-27）。

缺口：`load_bundle` 把 `leaf_exclusion_spec.disjoint_pairs` 原样装进判据，
不校验形状。若资产里出现**自反**对（`["external_wall", "external_wall"]`，
frozenset 坍缩成单元素）或**非二元**对，`early_exit` 的
`frozenset((target, identity)) in disjoint_pairs` 会在 target == identity
时命中 ⇒ 本该适用的条款被判「结构不适用」跳过义务 ⇒ 直接假阴性。

`component_lattice.py` 的加载器本来就拒这种资产，但独立适用性包的加载
路径没有复用该校验——本文件锁住「加载边界必须拒绝，且复用同一份校验」。

bundle 构造形状照 `test_applicability_bundle_failclosed.py`（与真实资产
`applicability_bundle_v1.json` 逐字段对齐的临时文件，真加载器真读盘）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from evo_agent_baseline.closure.applicability_v3 import canonical_hash, load_bundle

CARD = "rc.demo.card.c01"


def _write_bundle(tmp: pathlib.Path, disjoint_pairs: list) -> tuple[str, str]:
    manifest = {
        "rulecard_pack_sha256": "PACK",
        "cards": {CARD: {"authorized_target_leaf": "external_wall",
                         "card_content_sha256": "CARD"}},
    }
    lattice = {"leaf_types": ["external_wall", "drainage_component"],
               "disjoint_pairs": disjoint_pairs}
    ident = {"fragments": {"FRG-1": {"physical_leaf_identity": "external_wall"}}}
    members = {}
    for name, doc in (("card_applicability_manifest", manifest),
                      ("leaf_exclusion_spec", lattice),
                      ("w0_fragment_identity_manifest", ident)):
        f = tmp / f"{name}.json"
        f.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        members[name] = {"path": f.name, "content_sha256": canonical_hash(doc)}
    body = {"version": "applicability_bundle.v1",
            "rulecard_bundle_id": "rulecard_v2.demo",
            "worldgen_run_dir": "gen_demo",
            "leaf_types": ["external_wall", "drainage_component"],
            "members": members}
    body["bundle_sha256"] = canonical_hash(body)
    bp = tmp / "applicability_bundle_v1.json"
    bp.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return str(bp), body["bundle_sha256"]


def _load(tmp: pathlib.Path, disjoint_pairs: list):
    bp, bsha = _write_bundle(tmp, disjoint_pairs)
    return load_bundle(bp, bsha, repo_root=tmp, worldgen_run_dir="gen_demo",
                       card_content_shas={CARD: "CARD"},
                       rulecard_pack_sha256="PACK")


def test_reflexive_pair_is_rejected_at_load(tmp_path):
    """🔴 自反对 `["external_wall", "external_wall"]` → 整包拒绝。

    修复前它会被装进判据：`early_exit(CARD, "FRG-1")`（target == identity
    == external_wall）返回 (True, None) —— 外墙条款被误判结构不适用。
    """
    bundle, reason = _load(tmp_path, [["external_wall", "external_wall"]])
    assert bundle is None, (
        "自反排斥对被放行——target == identity 时 early_exit 会假阳性早退")
    assert reason is not None and reason.code == "disjoint_shape_invalid", reason


def test_single_element_pair_is_rejected_at_load(tmp_path):
    """单元素对（非二元）→ 整包拒绝。"""
    bundle, reason = _load(tmp_path, [["external_wall"]])
    assert bundle is None
    assert reason is not None and reason.code == "disjoint_shape_invalid", reason


def test_three_element_pair_is_rejected_at_load(tmp_path):
    """三元素对（非二元）→ 整包拒绝。"""
    bundle, reason = _load(
        tmp_path, [["external_wall", "drainage_component", "wall_tiles"]])
    assert bundle is None
    assert reason is not None and reason.code == "disjoint_shape_invalid", reason


def test_valid_pairs_still_load_and_no_reflexive_early_exit(tmp_path):
    """正对照：合法二元对正常加载；且 target == identity 永不早退。"""
    bundle, reason = _load(tmp_path, [["external_wall", "drainage_component"]])
    assert bundle is not None, f"合法 bundle 被拒: {reason}"
    # 同型（target == identity）即便真在排斥语义里也绝不构成早退
    exit_, _ = bundle.early_exit(CARD, "FRG-1")
    assert exit_ is False
