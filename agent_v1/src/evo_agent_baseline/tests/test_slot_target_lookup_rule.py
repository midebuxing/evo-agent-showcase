"""slot_targets.lookup_rule 通用派生（"登记了从没接线"修复，2026-07-27）。

卡包 projection_runtime_mapping_v1.json 的 slot_targets 段 27 条登记里 5 条带
lookup_rule，此前全仓零消费者（reporting.artifact.prepared 的 any_of 成员折叠走
硬编码 _SLOT_TARGET_FALLBACKS 旧通道，本文件不碰——两条通道并存，旧通道行为由
test_slot_target_fallback.py 锁定）。

语义来源（非猜测）：归档 MVP `agent_mvp_已归档/src/workflow_engine/
regulation_projection_executor.py::_lookup_via_rule` 的同段求值器——
- mode=all_of：每个子句至少一条匹配事实，否则整查落空；
- 形态一（qualifiers_mode=ignore、无 value_mode）：该槽任一显式 true；
- 形态二（value_mode=contains_requested_qualifier）：取"被请求的限定符"（=卡侧
  slot_ref 的 qualifiers，归档实现 `requested_qualifiers=target.get("qualifiers")`）
  中 requested_qualifier_key 的值列表，要求子句槽存在事实其值列表包含全部被请求值。

真实数据测试用真实卡包 + 真实批产物（baseline_batch_final_seed301，30 栋），
不凭空构造输入。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evo_agent_baseline.contracts import FactAtom
from evo_agent_baseline.retrieval.fact_retriever import (
    derive_slot_target_lookup_rule_facts,
    harvest_slot_target_requested_qualifiers,
)

_ROOT = Path(__file__).resolve().parents[4]
_MAPPING_PATH = (
    _ROOT / "agent_v1/regulations/rulecard_v2/mbis_cop_2023"
    / "projection_runtime_mapping_v1.json"
)
_CARDS_PATH = (
    _ROOT / "agent_v1/regulations/rulecard_v2/mbis_cop_2023/rule_cards.json"
)
_BATCH_GLOB = (
    _ROOT / "agent_v1/experiments/baseline_batch_final_seed301/buildings"
)


def _fact(fid, slot, value, qualifiers=None, carrier="sidecar_entry"):
    return FactAtom(
        fact_id=fid, world_id="W1", building_id="B1",
        carrier_type=carrier, carrier_id=fid, target_ref=None,
        slot_id=slot, measure_key=None,
        value_json=json.dumps(value), value_type="boolean", unit=None,
        qualifiers=dict(qualifiers or {}), confidence_index=None,
        source_path="t", source_node_id=fid,
    )


_RULE_DETAILED = {
    "mode": "all_of",
    "clauses": [
        {"slot_id": "procedure.investigation.started", "qualifiers_mode": "ignore"},
        {"slot_id": "artifact.proposal.detailed_investigation",
         "qualifiers_mode": "ignore"},
    ],
}
_RULE_QUALIFIED = {
    "mode": "all_of",
    "clauses": [
        {"slot_id": "procedure.supervision_team.submitted",
         "qualifiers_mode": "ignore"},
        {"slot_id": "qual.actor_role",
         "value_mode": "contains_requested_qualifier",
         "requested_qualifier_key": "actor_role_key"},
    ],
}
_TARGET_DETAILED = "procedure.investigation.detailed.started"
_TARGET_QUALIFIED = "actor.representative.qualified_for_assigned_role"


# ---------------------------------------------------------------------------
# 合成单元测试：子句语义
# ---------------------------------------------------------------------------

def test_all_of_both_true_derives_true() -> None:
    facts = [
        _fact("f1", "procedure.investigation.started", True),
        _fact("f2", "artifact.proposal.detailed_investigation", True),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_DETAILED: {"lookup_rule": _RULE_DETAILED}},
        {}, "W1", "B1",
    )
    assert len(out) == 1
    assert out[0].slot_id == _TARGET_DETAILED
    assert out[0].value_json == "true"
    assert out[0].carrier_type == "building"
    assert out[0].provenance["derivation"] == "slot_target_lookup_rule"


def test_all_of_conjunction_not_collapsed_to_single_alias() -> None:
    """红线：all_of 不得简化成单项别名——调查已开始但无詳細調查建议书证物时，
    必须派生 false（§4.2.3 prohibition 卡防假违规）。"""
    facts = [
        _fact("f1", "procedure.investigation.started", True),
        _fact("f2", "artifact.proposal.detailed_investigation", False),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_DETAILED: {"lookup_rule": _RULE_DETAILED}},
        {}, "W1", "B1",
    )
    assert len(out) == 1
    assert out[0].value_json == "false"


def test_clause_slot_entirely_absent_emits_nothing() -> None:
    """子句槽整体无事实 → 不可判 → 不出事实（诚实缺量，不造 false）。"""
    facts = [_fact("f1", "procedure.investigation.started", True)]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_DETAILED: {"lookup_rule": _RULE_DETAILED}},
        {}, "W1", "B1",
    )
    assert out == []


def test_direct_facts_win_over_lookup_rule() -> None:
    """目标槽已有匹配限定符组合的直接事实 → 跳过派生（归档 direct-wins 语义）。"""
    facts = [
        _fact("d1", _TARGET_DETAILED, False),
        _fact("f1", "procedure.investigation.started", True),
        _fact("f2", "artifact.proposal.detailed_investigation", True),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_DETAILED: {"lookup_rule": _RULE_DETAILED}},
        {}, "W1", "B1",
    )
    assert out == []


def test_contains_requested_qualifier_match_derives_true() -> None:
    facts = [
        _fact("f1", "procedure.supervision_team.submitted", True),
        _fact("f2", "qual.actor_role", "ri_rep_lvl1"),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_QUALIFIED: {"lookup_rule": _RULE_QUALIFIED}},
        {_TARGET_QUALIFIED: [{"actor_role_key": "ri_rep_lvl1"}]}, "W1", "B1",
    )
    assert len(out) == 1
    assert out[0].value_json == "true"
    assert out[0].qualifiers["actor_role_key"] == "ri_rep_lvl1"


def test_contains_requested_qualifier_miss_emits_nothing() -> None:
    """containment 未命中 → 不出事实（无法区分"角色确缺席"与"世界词表不含
    所请键"，宁缺勿错，不造 false）。"""
    facts = [
        _fact("f1", "procedure.supervision_team.submitted", True),
        _fact("f2", "qual.actor_role", "registered_inspector"),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_QUALIFIED: {"lookup_rule": _RULE_QUALIFIED}},
        {_TARGET_QUALIFIED: [{"actor_role_key": "ri_rep_lvl1"}]}, "W1", "B1",
    )
    assert out == []


def test_contains_requested_qualifier_without_request_skips_target() -> None:
    """形态二子句无被请求限定符值可供比对 → 该目标槽整体跳过（不 vacuous 通过）。"""
    facts = [
        _fact("f1", "procedure.supervision_team.submitted", True),
        _fact("f2", "qual.actor_role", "registered_inspector"),
    ]
    out = derive_slot_target_lookup_rule_facts(
        facts, {_TARGET_QUALIFIED: {"lookup_rule": _RULE_QUALIFIED}},
        {}, "W1", "B1",
    )
    assert out == []


def test_unregistered_mode_raises() -> None:
    with pytest.raises(ValueError, match="mode"):
        derive_slot_target_lookup_rule_facts(
            [], {"t": {"lookup_rule": {"mode": "any_of", "clauses": []}}},
            {}, "W1", "B1",
        )


def test_unregistered_qualifiers_mode_raises() -> None:
    rule = {"mode": "all_of", "clauses": [
        {"slot_id": "s", "qualifiers_mode": "inherit"}]}
    with pytest.raises(ValueError, match="qualifiers_mode"):
        derive_slot_target_lookup_rule_facts(
            [], {"t": {"lookup_rule": rule}}, {}, "W1", "B1",
        )


def test_unregistered_value_mode_raises() -> None:
    rule = {"mode": "all_of", "clauses": [
        {"slot_id": "s", "value_mode": "equals_requested_qualifier",
         "requested_qualifier_key": "k"}]}
    with pytest.raises(ValueError, match="value_mode"):
        derive_slot_target_lookup_rule_facts(
            [], {"t": {"lookup_rule": rule}}, {}, "W1", "B1",
        )


def test_harvest_requested_qualifiers_from_real_cards() -> None:
    """采集器对真实 rule_cards.json：两个 actor 槽各收到 lvl1/lvl2 两个组合。"""
    doc = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
    harvested = harvest_slot_target_requested_qualifiers(doc)
    assert {q["actor_role_key"]
            for q in harvested["actor.representative.qualified_for_assigned_role"]} == {
        "ri_rep_lvl1", "ri_rep_lvl2",
    }
    # 🔴 2026-07-28 放宽：`actor.representative.assigned` 允许**无限定符**的引用。
    # 原断言要求每一处引用都带 `actor_role_key`，补 §2.1.3(a) 卡后被打破——
    # 该条中文正文是「註冊檢驗人員仍須就**其代表**所認明的欠妥範圍負上個人責任」，
    # 责任**不分代表等级**，所以那张卡的 `qualifiers` 空着是语义正确的，
    # 是这条断言的假设过窄（它把"当时恰好都带等级"当成了不变量）。
    # 现口径：**带限定符的引用其取值必须在 {lvl1, lvl2} 内**；无限定符 = 「任意代表」，合法。
    _assigned = harvested["actor.representative.assigned"]
    assert {q["actor_role_key"] for q in _assigned if "actor_role_key" in q} == {
        "ri_rep_lvl1", "ri_rep_lvl2",
    }
    assert any("actor_role_key" not in q for q in _assigned), (
        "§2.1.3(a) 的无限定符引用应被采集到；若它消失了，说明该卡被改窄或被丢弃"
    )
    assert {} in [dict(q) for q in harvested[_TARGET_DETAILED]] or \
        harvested[_TARGET_DETAILED] == [{}]


# ---------------------------------------------------------------------------
# 真实数据测试：真实卡包 + 真实批产物（30 栋）
# ---------------------------------------------------------------------------

pytestmark_real = pytest.mark.skipif(
    not _BATCH_GLOB.is_dir(), reason="真实批产物目录不在本机（实验产物不入库）",
)


def _load_real_inputs():
    slot_targets = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))["slot_targets"]
    cards_doc = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
    requested = harvest_slot_target_requested_qualifiers(cards_doc)
    packs = sorted(_BATCH_GLOB.glob("*/runs/*/fact_pack.json"))
    assert len(packs) == 30
    return slot_targets, requested, packs


def _any_true(facts, slot):
    return any(f.slot_id == slot and f.value_json == "true" for f in facts)


@pytestmark_real
def test_real_batch_detailed_investigation_started_derived() -> None:
    """30 栋真实批产物：procedure.investigation.detailed.started 每栋恰好派生
    一条楼级双极事实，值与操作数独立重算一致（started∧artifact 全真→true；
    两槽可判但未全真→false）。"""
    slot_targets, requested, packs = _load_real_inputs()
    n_true = n_false = 0
    for p in packs:
        pack = json.loads(p.read_text(encoding="utf-8"))
        facts = [FactAtom(**f) for f in pack["facts"]]
        out = derive_slot_target_lookup_rule_facts(
            facts, slot_targets, requested,
            pack["world_id"], pack["building_id"],
        )
        rows = [o for o in out if o.slot_id == _TARGET_DETAILED]
        assert len(rows) == 1, f"{pack['building_id']}: {len(rows)}"
        expected = (
            _any_true(facts, "procedure.investigation.started")
            and _any_true(facts, "artifact.proposal.detailed_investigation")
        )
        assert rows[0].value_json == ("true" if expected else "false")
        assert rows[0].carrier_type == "building"
        if expected:
            n_true += 1
        else:
            n_false += 1
    # 与改前独立预算对账：30 栋全真派生，15 true / 15 false。
    assert (n_true, n_false) == (15, 15)


@pytestmark_real
def test_real_batch_qualified_for_assigned_role_not_derived() -> None:
    """actor.representative.qualified_for_assigned_role 在当前世界派生 0 条——
    世界 qual.actor_role 词表（registered_inspector/registered_contractor/
    building_authority/owner）与卡侧被请求词表（ri_rep_lvl1/lvl2）不交，
    containment 恒不命中。本测试把该缺口钉成显式断言：哪天世界侧补了等级
    词汇，这里会变非零、必须回头复核。"""
    slot_targets, requested, packs = _load_real_inputs()
    total = 0
    for p in packs:
        pack = json.loads(p.read_text(encoding="utf-8"))
        facts = [FactAtom(**f) for f in pack["facts"]]
        out = derive_slot_target_lookup_rule_facts(
            facts, slot_targets, requested,
            pack["world_id"], pack["building_id"],
        )
        total += sum(1 for o in out if o.slot_id == _TARGET_QUALIFIED)
    assert total == 0


@pytestmark_real
def test_real_batch_supervision_record_derived_per_requested_artifact_key() -> None:
    """S3 B 侧后：completed 派生恒 0（lookup_rule 已删）；retained 照旧逐键派生
    并与 completed_and_retained 任一 true 重算一致。"""
    slot_targets, requested, packs = _load_real_inputs()
    n_completed = n_retained = 0
    for p in packs:
        pack = json.loads(p.read_text(encoding="utf-8"))
        facts = [FactAtom(**f) for f in pack["facts"]]
        out = derive_slot_target_lookup_rule_facts(
            facts, slot_targets, requested,
            pack["world_id"], pack["building_id"],
        )
        expected = "true" if _any_true(
            facts, "supervision.record.completed_and_retained") else "false"
        comp = [o for o in out if o.slot_id == "supervision.record.completed"]
        ret = [o for o in out if o.slot_id == "supervision.record.retained"]
        # S3 B 侧（2026-08-02）：completed 的 lookup_rule 已删（原生 all_true
        # 唯一权威、any_true 反推+假轴是病灶）——派生必须为 0；retained 未涉
        # 本轮裁定、维持原派生并按重算值核对。
        assert comp == [], f"completed 派生必须为 0: {len(comp)}"
        assert {o.qualifiers.get("artifact_key") for o in ret} == {
            "record.supervision_checklist",
        }
        assert all(o.value_json == expected for o in ret)
        n_completed += len(comp)
        n_retained += len(ret)
    assert (n_completed, n_retained) == (0, 30)


@pytestmark_real
def test_real_batch_actor_representative_assigned_not_double_sourced() -> None:
    """actor.representative.assigned 已有带 actor_role_key 的直接事实（世界侧
    角色枚举展开），direct-wins 命中 → 不重复派生。"""
    slot_targets, requested, packs = _load_real_inputs()
    for p in packs:
        pack = json.loads(p.read_text(encoding="utf-8"))
        facts = [FactAtom(**f) for f in pack["facts"]]
        out = derive_slot_target_lookup_rule_facts(
            facts, slot_targets, requested,
            pack["world_id"], pack["building_id"],
        )
        assert not [o for o in out
                    if o.slot_id == "actor.representative.assigned"]
