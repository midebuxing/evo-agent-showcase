"""组件类目成员行派生（spec 草案·DEBT-049 第二波 §3，2026-07-08）。

词表层级墙修复：卡端限定符用上位类目（external_component）而事实行带成员值
（external_wall 恒等映射）。fragment 级同源类目行 = 深拷贝换键——值恒等源行是
实现不变量（codex 复议验收：禁止独立重算；无键消费者绑双行同值故无歧义）。
"""

from __future__ import annotations

import json

from evo_agent_baseline.contracts import FactAtom
from evo_agent_baseline.retrieval.fact_retriever import (
    derive_category_membership_facts,
)

CATS = {
    "_note": "test 段注释键须被忽略",
    "external_component": {
        "members": ["external_wall", "cantilevered_canopy", "wall_tiles"],
        "aggregation": "any_true",
    },
}


def _decl(fid, ctype, value=True, frag="FR1", extra=None):
    q = {"component_type_key": ctype, "carrier_domain": "scope",
         "fragment_id": frag}
    q.update(extra or {})
    return FactAtom(
        fact_id=fid, world_id="W1", building_id="B1",
        carrier_type="sidecar_entry", carrier_id=fid, target_ref=None,
        slot_id="scope.component.inspection_included", measure_key=None,
        value_json=json.dumps(value), value_type="boolean", unit=None,
        qualifiers=q, confidence_index=None,
        source_path="t", source_node_id=fid,
    )


def test_member_fragment_row_copied_with_category_key() -> None:
    """成员 fragment 行 → 复制换类目键，其余限定符全继承、值恒等源行。"""
    facts = [_decl("f1", "external_wall", True, "FR1",
                   {"location_class_key": "external"})]
    out = derive_category_membership_facts(facts, CATS)
    assert len(out) == 1
    cat = out[0]
    assert cat.qualifiers["component_type_key"] == "external_component"
    assert cat.qualifiers["fragment_id"] == "FR1"
    assert cat.qualifiers["location_class_key"] == "external"  # 位置维度继承
    assert cat.value_json == facts[0].value_json  # 深拷贝不变量：禁止独立重算
    assert cat.provenance["derivation"] == "category_membership"
    assert cat.fact_id != facts[0].fact_id
    # 源行不被改写（复制非改写）
    assert facts[0].qualifiers["component_type_key"] == "external_wall"
    assert "derivation" not in facts[0].provenance


def test_non_member_fragment_no_row() -> None:
    """非成员 fragment 不发类目行（缺席=诚实 missing，不伪造真假）。"""
    facts = [_decl("f1", "drainage_component", True)]
    assert derive_category_membership_facts(facts, CATS) == []


def test_category_valued_row_idempotent() -> None:
    """塌桥产物（component_type_key 已是类目值）不复制——幂等防双行。"""
    facts = [_decl("f1", "external_component", True)]
    assert derive_category_membership_facts(facts, CATS) == []


def test_building_aggregation_rows_not_copied_as_fragment_rows() -> None:
    """带 aggregation=building 标记的行不产 fragment 类目复制行（只进广播输入）。"""
    facts = [_decl("f1", "external_wall", True, "FR1",
                   {"aggregation": "building"})]
    out = derive_category_membership_facts(facts, CATS)
    assert all("fragment_id" not in a.qualifiers for a in out)
    assert all(a.carrier_type == "building" for a in out)


def test_rows_without_fragment_stamp_skipped() -> None:
    """无 fragment 戳的行不派生（类目行语义定义在 fragment 作用域）。"""
    f = _decl("f1", "external_wall", True)
    f.qualifiers.pop("fragment_id")
    assert derive_category_membership_facts([f], CATS) == []


def test_keyless_consumer_sees_consistent_values() -> None:
    """无键消费者安全性：本类行与类目行同源同值（恒真）→ 一致真无歧义。"""
    facts = [_decl("f1", "external_wall", True, "FR1")]
    out = derive_category_membership_facts(facts, CATS)
    vals = {a.value_json for a in facts + out}
    assert vals == {"true"}


def test_strict_filter_partitions_member_and_category_rows() -> None:
    """严格子集匹配分流：按成员限定只中成员行、按类目限定只中类目行。"""
    from evo_agent_baseline.closure.obligation_deriver import (
        _filter_by_qualifiers,
    )
    facts = [_decl("f1", "external_wall", True, "FR1")]
    allrows = facts + derive_category_membership_facts(facts, CATS)
    hit_member = _filter_by_qualifiers(
        allrows, {"component_type_key": "external_wall"})
    hit_cat = _filter_by_qualifiers(
        allrows, {"component_type_key": "external_component"})
    assert [a.fact_id for a in hit_member] == ["f1"]
    assert len(hit_cat) == 1 and hit_cat[0].fact_id.endswith(
        "::category::external_component")


def test_defect_slot_derives_category_row() -> None:
    """②扩项：defect.class.present 成员行 → 类目行（保留 defect_class_key/location）。"""
    f = _decl("f1", "external_wall", False, "FR1",
              {"defect_class_key": "crack", "location_class_key": "external"}
              ).model_copy(update={"slot_id": "defect.class.present"})
    out = derive_category_membership_facts([f], CATS)
    assert len(out) == 1
    c = out[0]
    assert c.slot_id == "defect.class.present"
    assert c.qualifiers["component_type_key"] == "external_component"
    assert c.qualifiers["defect_class_key"] == "crack"  # 保留
    assert c.qualifiers["location_class_key"] == "external"  # 保留
    assert c.value_json == f.value_json  # 值恒等（负例 false 保留）
    assert c.provenance["derivation"] == "category_membership"


def test_non_accession_slot_untouched() -> None:
    """未接入槽（如 repair.prescribed.started）仍不派生。"""
    f = _decl("f1", "external_wall", True).model_copy(
        update={"slot_id": "repair.prescribed.started"})
    assert derive_category_membership_facts([f], CATS) == []


def test_report_field_group_facts() -> None:
    """C1：RI 报告章节存在事实（qual.artifact_field_group，无 aggregation 标记）。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        derive_report_field_group_facts,
    )
    out = derive_report_field_group_facts("W1", "B1")
    groups = {f.qualifiers["artifact_field_group"] for f in out}
    assert "inspection_results" in groups and "reference_documents" in groups
    assert "completion_record" in groups  # report.completion 扩展
    for f in out:
        assert f.slot_id == "qual.artifact_field_group"
        assert "aggregation" not in f.qualifiers  # fragment 作用域须可见
        assert f.value_type == "boolean" or f.value_type == "string"
        assert f.provenance["derivation"] == "report_field_group_contract"


def test_verification_performed_from_measurement() -> None:
    """verification.test.performed：测量（method_class∈测试集）→ 测试已执行=true。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        derive_verification_performed_facts,
    )
    m1 = _decl("m1", "wall_tiles", True, "FR1",
               {"method_class": "pull_test"}).model_copy(
        update={"slot_id": "count.pull_test"})
    m2 = _decl("m2", "external_wall", True, "FR2",
               {"method_class": "visual_inspection"}).model_copy(
        update={"slot_id": "ratio.covered"})
    out = derive_verification_performed_facts([m1, m2])
    # pull_test（测试方法）派生；visual_inspection（非物理测试）不派生
    assert len(out) == 1
    o = out[0]
    assert o.slot_id == "verification.test.performed"
    assert o.qualifiers["method_key"] == "pull_test"
    assert o.qualifiers["component_type_key"] == "wall_tiles"
    assert o.value_json == "true"
    assert o.provenance["derivation"] == "test_performed_from_measurement"


def test_empty_or_malformed_table_no_crash() -> None:
    facts = [_decl("f1", "external_wall", True)]
    assert derive_category_membership_facts(facts, {}) == []
    assert derive_category_membership_facts(facts, {"_note": "x"}) == []
    assert derive_category_membership_facts(
        facts, {"external_component": "not_a_dict"}) == []


def _str_row(fid, slot, value, frag="FR1", ctype="drainage_component"):
    """字符串态回退行（value_type=string，如 spec 06 §11 not_applicable）。"""
    return _decl(fid, ctype, True, frag).model_copy(update={
        "slot_id": slot, "value_json": json.dumps(value), "value_type": "string"})


def test_stamp_risk_class_from_mapping_table() -> None:
    """风险槽盖 risk_class_key（显式表）；已有键不覆盖；表外槽不动（件甲 A2）。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        stamp_risk_class_qualifiers,
    )
    table = {"_note": "x",
             "risk.public_danger.present": "public_danger",
             "risk.fire_safety.adverse_impact": "fire_safety_adverse_impact"}
    a1 = _decl("a1", "external_wall", True).model_copy(
        update={"slot_id": "risk.public_danger.present"})
    a2 = _decl("a2", "external_wall", True).model_copy(
        update={"slot_id": "risk.fire_safety.adverse_impact"})
    a3 = _decl("a3", "external_wall", True).model_copy(
        update={"slot_id": "risk.public_danger.present"})
    a3.qualifiers["risk_class_key"] = "custom"
    a4 = _decl("a4", "external_wall", True)  # 非风险槽不动
    stamp_risk_class_qualifiers([a1, a2, a3, a4], table)
    assert a1.qualifiers["risk_class_key"] == "public_danger"
    assert a2.qualifiers["risk_class_key"] == "fire_safety_adverse_impact"
    assert a3.qualifiers["risk_class_key"] == "custom"
    assert "risk_class_key" not in a4.qualifiers
    stamp_risk_class_qualifiers([a4], {})  # 空表不炸不动
    assert "risk_class_key" not in a4.qualifiers


def test_stamp_risk_class_boolean_guard() -> None:
    """布尔护栏：串态回退行不盖章（防脏行可见撞 ambiguous）。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        stamp_risk_class_qualifiers,
    )
    table = {"risk.public_health.emergency": "public_health_emergency"}
    b = _decl("b", "drainage_component", False).model_copy(
        update={"slot_id": "risk.public_health.emergency"})
    s = _str_row("s", "risk.public_health.emergency", "not_applicable")
    stamp_risk_class_qualifiers([b, s], table)
    assert b.qualifiers["risk_class_key"] == "public_health_emergency"
    assert "risk_class_key" not in s.qualifiers  # 串态不盖


def test_derive_risk_slot_from_boolean_only() -> None:
    """A1' 派生：只从布尔源行深拷贝干净目标行；串态回退行不派生。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        derive_risk_slot_facts,
    )
    derivs = {"_note": "x",
              "risk.fire_safety.adverse_impact": "fire_safety.deficiency.present"}
    boolrow = _decl("d1", "fire_safety_component", True).model_copy(update={
        "slot_id": "fire_safety.deficiency.present"})
    s1 = _str_row("d2", "fire_safety.deficiency.present", "not_applicable")
    s2 = _str_row("d3", "fire_safety.deficiency.present", "no_fire_component")
    out = derive_risk_slot_facts([boolrow, s1, s2], derivs)
    assert len(out) == 1
    d = out[0]
    assert d.slot_id == "risk.fire_safety.adverse_impact"
    assert d.value_json == boolrow.value_json  # 值恒等源行
    assert d.qualifiers["component_type_key"] == "fire_safety_component"  # 限定符继承
    assert d.qualifiers["fragment_id"] == "FR1"
    assert d.provenance["derivation"] == "risk_slot_semantic_bridge"
    assert boolrow.slot_id == "fire_safety.deficiency.present"  # 源行不改
    assert derive_risk_slot_facts([boolrow], {}) == []


def test_derive_then_stamp_chain() -> None:
    """派生→盖章链：派生的 adverse_impact 行随后被盖 risk_class_key。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        derive_risk_slot_facts, stamp_risk_class_qualifiers,
    )
    derivs = {"risk.fire_safety.adverse_impact": "fire_safety.deficiency.present"}
    keys = {"risk.fire_safety.adverse_impact": "fire_safety_adverse_impact"}
    boolrow = _decl("d1", "fire_safety_component", True).model_copy(update={
        "slot_id": "fire_safety.deficiency.present"})
    facts = [boolrow]
    facts.extend(derive_risk_slot_facts(facts, derivs))
    stamp_risk_class_qualifiers(facts, keys)
    derived = [f for f in facts if f.slot_id == "risk.fire_safety.adverse_impact"]
    assert len(derived) == 1
    assert derived[0].qualifiers["risk_class_key"] == "fire_safety_adverse_impact"


def test_stamp_artifact_key_from_slot_suffix() -> None:
    """artifact.* 行补 artifact_key=槽名后缀；已有键不覆盖；非 artifact 槽不动。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        stamp_artifact_key_qualifiers,
    )
    a1 = _decl("a1", "external_wall", True).model_copy(
        update={"slot_id": "artifact.record.inspection_log"})
    a2 = _decl("a2", "external_wall", True).model_copy(
        update={"slot_id": "artifact.form.mbi4"})
    a2.qualifiers["artifact_key"] = "custom.key"
    a3 = _decl("a3", "external_wall", True)  # scope 槽不动
    stamp_artifact_key_qualifiers([a1, a2, a3])
    assert a1.qualifiers["artifact_key"] == "record.inspection_log"
    assert a2.qualifiers["artifact_key"] == "custom.key"
    assert "artifact_key" not in a3.qualifiers


def _bldg(fid, ctype, value):
    """楼级声明行（aggregation=building 标记、无 fragment 戳）。"""
    f = _decl(fid, ctype, value, frag="X")
    f.qualifiers.pop("fragment_id")
    f.qualifiers["aggregation"] = "building"
    f.qualifiers["granularity"] = "building"
    return f


def _broadcasts(out):
    return [a for a in out if a.carrier_type == "building"]


def test_broadcast_row_from_member_building_rows() -> None:
    """楼级广播行：成员楼级行 any_true → carrier=building、无 aggregation 标记。"""
    facts = [_bldg("b1", "external_wall", True),
             _bldg("b2", "wall_tiles", False)]
    out = derive_category_membership_facts(facts, CATS)
    bc = _broadcasts(out)
    assert len(bc) == 1
    row = bc[0]
    assert row.value_json == "true"
    assert row.qualifiers["component_type_key"] == "external_component"
    assert "aggregation" not in row.qualifiers  # fragment 作用域可见是本意
    assert "fragment_id" not in row.qualifiers
    assert row.provenance["derivation"] == "category_membership"


def test_broadcast_true_only() -> None:
    """仅真才发：成员行全假 → 无广播行（假案例由卡级适用性 NA 兜住）。"""
    facts = [_bldg("b1", "external_wall", False),
             _bldg("b2", "wall_tiles", False)]
    assert _broadcasts(derive_category_membership_facts(facts, CATS)) == []


def test_broadcast_counts_collapsed_bridge_rows() -> None:
    """塌桥类目值楼级行（signboard 等桥后为 external_component）计入 any_true。"""
    facts = [_bldg("b1", "external_wall", False),
             _bldg("b2", "external_component", True)]
    bc = _broadcasts(derive_category_membership_facts(facts, CATS))
    assert len(bc) == 1 and bc[0].value_json == "true"


def test_broadcast_no_inputs_no_row() -> None:
    """无楼级声明行（如纯 fragment 池）→ 不发广播行。"""
    facts = [_decl("f1", "external_wall", True)]  # 仅 fragment 行
    assert _broadcasts(derive_category_membership_facts(facts, CATS)) == []


def test_broadcast_rank_beats_sidecar_rows() -> None:
    """scoped_facts 下广播行（building rank 3）压过 sidecar 行（rank 4）成唯一读数。"""
    from evo_agent_baseline.closure.fact_binding import FactIndex
    from evo_agent_baseline.retrieval.pack_builder import build_fact_pack

    facts = [_decl("f1", "external_wall", True, "FR1"),
             _bldg("b1", "external_wall", True)]
    out = derive_category_membership_facts(facts, CATS)
    allrows = facts + out
    idx = FactIndex(build_fact_pack(
        run_id="R1", world_id="W1", building_id="B1",
        facts=allrows, source_tables=[],
    ))
    frag_row = [a for a in allrows
                if a.qualifiers.get("component_type_key") == "external_component"
                and a.qualifiers.get("fragment_id")]
    bc_row = [a for a in allrows if a.carrier_type == "building"
              and a.qualifiers.get("component_type_key") == "external_component"]
    scoped = idx.scoped_facts(frag_row + bc_row)
    assert scoped == bc_row  # rank 3 唯一保留，双行同值真故语义等价
