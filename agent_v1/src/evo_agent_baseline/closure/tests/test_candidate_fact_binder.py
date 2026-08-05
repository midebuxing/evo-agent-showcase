# -*- coding: utf-8 -*-
"""统一候选事实绑定器（DEBT-083 第 4 步，决策门分叉二）。

面：①固定顺序**先限定符过滤、后作用域选择**——反序会让错 key 的高层行挤掉
正确低层身份行（决策门原话，本文件用构造反例钉死）；②scope_selection=False
与旧槽位角色路径逐位等价（bound==qfiltered）；③审计面记录所选事实编号与
逐级排除数量；④槽名归一经 canonical_slot。
"""
from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    select_candidate_facts,
)
from .fixtures import make_fact, make_fact_pack


def _fact(fid, slot, value, carrier_type="fragment", quals=None):
    return make_fact(fid, slot_id=slot, value=value, value_type="boolean",
                     carrier_type=carrier_type, carrier_id=f"C-{fid}",
                     qualifiers=quals or {})


def _index(facts, **kw):
    return FactIndex(make_fact_pack(list(facts)), **kw)


def test_filter_then_scope_order_is_load_bearing():
    """顺序敏感反例：building 聚合行带错误 artifact_key、fragment 行带正确 key。

    先过滤后分级（正序）：过滤删掉错 key 的聚合行 → 绑定到正确 fragment 行。
    先分级后过滤（反序、被决策门否掉的形状）：聚合行挤掉 fragment 行 →
    再过滤后一无所剩。本测试钉正序结果；反序若被引入，绑定为空即红。
    """
    wrong_agg = _fact("f-agg", "proc.x", True, carrier_type="building",
                      quals={"artifact_key": "WRONG"})
    right_frag = _fact("f-frag", "proc.x", True,
                       quals={"artifact_key": "RIGHT"})
    idx = _index([wrong_agg, right_frag])
    sel = select_candidate_facts(
        idx, "proc.x", {"artifact_key": "RIGHT"}, scope_selection=True)
    assert [f.fact_id for f in sel.bound] == ["f-frag"]
    assert sel.status == "consistent"
    # 模拟反序（先 scoped 后过滤）证明它确实是另一种行为——防"顺序无所谓"回归
    reversed_bound = [f for f in idx.scoped_facts([wrong_agg, right_frag])
                      if f.qualifiers.get("artifact_key") == "RIGHT"]
    assert reversed_bound == []   # 聚合行挤掉 fragment 行后再过滤 → 空


def test_scope_selection_false_is_identity_on_qfiltered():
    """槽位角色路径今日口径：不做作用域选择，bound 与 qfiltered 同一列表。"""
    agg = _fact("f-agg", "proc.y", True, carrier_type="building")
    frag = _fact("f-frag", "proc.y", False)
    idx = _index([agg, frag])
    sel = select_candidate_facts(idx, "proc.y", {}, scope_selection=False)
    assert [f.fact_id for f in sel.bound] == [f.fact_id for f in sel.qfiltered]
    assert sel.status == "ambiguous"   # 聚合行与部位行混判——1,538 病灶原样保留
    sel2 = select_candidate_facts(idx, "proc.y", {}, scope_selection=True)
    assert [f.fact_id for f in sel2.bound] == ["f-agg"]   # 分级后聚合行优先


def test_audit_records_selection_and_exclusions():
    a = _fact("f1", "s.a", True, quals={"k": "v"})
    b = _fact("f2", "s.a", True, quals={"k": "other"})
    idx = _index([a, b])
    sel = select_candidate_facts(idx, "s.a", {"k": "v"}, scope_selection=False)
    assert sel.audit["selected_fact_ids"] == ["f1"]
    assert sel.audit["excluded_by_qualifiers"] == 1
    assert sel.audit["excluded_by_scope"] == 0
    assert sel.audit["scope_selection"] is False


def test_missing_slot_returns_missing():
    idx = _index([])
    sel = select_candidate_facts(idx, "no.such", {}, scope_selection=True)
    assert sel.status == "missing" and sel.bound == [] and sel.candidates == []
