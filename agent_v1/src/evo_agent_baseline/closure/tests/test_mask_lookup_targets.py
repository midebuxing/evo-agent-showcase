# -*- coding: utf-8 -*-
"""S3 A 侧查询行遮蔽（决策门 2026-08-02；六条辨识全须满足）。

面：①六条全满足才遮（五个近失配变体各不遮——**禁用假轴/编号当判据**的
机器面）；②遮后判定索引只剩原生行、审计面（carrier_index）保留被遮行；
③开关关闭逐位不变；④冻结集合外的槽不遮。
"""
from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import (
    FactIndex,
    MASKED_LOOKUP_TARGETS,
)
from .fixtures import BUILDING_ID, make_fact, make_fact_pack

SLOT = "supervision.record.completed"


def _lookup_row(fid="f-lk", **over):
    prov = {"derivation": "slot_target_lookup_rule", "slot_target": SLOT,
            "carrier_label": "Building"}
    quals = {"aggregation": "building", "artifact_key": "record.site_visit_log"}
    prov.update(over.pop("prov", {}))
    quals.update(over.pop("quals", {}))
    return make_fact(fid, slot_id=over.pop("slot_id", SLOT), value=True,
                     value_type="boolean", carrier_type="building",
                     carrier_id=BUILDING_ID, qualifiers=quals, provenance=prov)


def _native_row():
    return make_fact("f-nat", slot_id=SLOT, value=False, value_type="boolean",
                     carrier_type="building", carrier_id=BUILDING_ID,
                     qualifiers={"aggregation": "building"})


def test_frozen_target_set():
    assert MASKED_LOOKUP_TARGETS == {"supervision.record.completed"}


def test_full_match_masked_native_remains():
    idx = FactIndex(make_fact_pack([_lookup_row(), _native_row()]),
                    mask_lookup_targets=True)
    rows = idx.slot_index.get(SLOT, [])
    assert [f.fact_id for f in rows] == ["f-nat"]        # 判定索引只剩原生行
    assert any(f.fact_id == "f-lk"
               for f in idx.carrier_index.get(BUILDING_ID, []))  # 审计面保留


def test_switch_off_keeps_both():
    idx = FactIndex(make_fact_pack([_lookup_row(), _native_row()]))
    assert len(idx.slot_index.get(SLOT, [])) == 2


def test_near_miss_variants_not_masked():
    """五个近失配变体各不遮——部分匹配不许静默遮蔽（前置校验器另拦）。"""
    variants = [
        _lookup_row(prov={"derivation": "renamed"}),            # 派生标记不符
        _lookup_row(prov={"slot_target": "other.slot"}),        # slot_target 不符
        _lookup_row(quals={"aggregation": "fragment"}),         # 聚合标记不符
        _lookup_row(prov={"carrier_label": "Fragment"}),        # 载体标签不符
    ]
    for v in variants:
        idx = FactIndex(make_fact_pack([v]), mask_lookup_targets=True)
        assert len(idx.slot_index.get(SLOT, [])) == 1, v.fact_id


def test_out_of_scope_slot_not_masked():
    row = _lookup_row(slot_id="procedure.inspection.prescribed.completed",
                      prov={"slot_target":
                            "procedure.inspection.prescribed.completed"})
    idx = FactIndex(make_fact_pack([row]), mask_lookup_targets=True)
    assert len(idx.slot_index.get(
        "procedure.inspection.prescribed.completed", [])) == 1
