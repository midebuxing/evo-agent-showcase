"""slot_targets 逐证物键回退派生（第十例修复 + v10 逐键修正，2026-07-08）。"""

from __future__ import annotations

from evo_agent_baseline.retrieval.fact_retriever import (
    derive_slot_target_fallback_facts,
)
from evo_agent_baseline.contracts import FactAtom


def _fact(fid, slot, value, frag):
    import json
    return FactAtom(
        fact_id=fid, world_id="W1", building_id="B1",
        carrier_type="sidecar_entry", carrier_id=fid, target_ref=None,
        slot_id=slot, measure_key=None,
        value_json=json.dumps(value), value_type="boolean", unit=None,
        qualifiers={"fragment_id": frag}, confidence_index=None,
        source_path="t", source_node_id=fid,
    )


def test_per_artifact_key_rows_with_member_values() -> None:
    """fragment 层：每成员槽一条带 artifact_key 的事实，值随成员原值（双极）。"""
    facts = [
        _fact("f1", "artifact.report.inspection", True, "FR1"),
        _fact("f2", "artifact.form.mbi4", False, "FR1"),
    ]
    out = derive_slot_target_fallback_facts(facts, "W1", "B1")
    by_key = {o.qualifiers["artifact_key"]: o for o in out
              if o.carrier_type == "fragment"}
    assert set(by_key) == {"report.inspection", "form.mbi4"}
    assert by_key["report.inspection"].value_json == "true"
    assert by_key["form.mbi4"].value_json == "false"
    assert all(o.slot_id == "reporting.artifact.prepared" for o in out)
    assert all(o.qualifiers["fragment_id"] == "FR1" for o in out
               if o.carrier_type == "fragment")


def test_consumer_qualifier_selects_single_row() -> None:
    """带 artifact_key 限定符的消费端恰好选中一条（qualifiers 子集匹配语义）。"""
    facts = [
        _fact("f1", "artifact.proposal.repair", True, "FR1"),
        _fact("f2", "artifact.report.completion", False, "FR1"),
    ]
    out = derive_slot_target_fallback_facts(facts, "W1", "B1")
    sel = [o for o in out
           if o.qualifiers.get("artifact_key") == "proposal.repair"
           and o.carrier_type == "fragment"]
    assert len(sel) == 1 and sel[0].value_json == "true"
    # 楼级逐键聚合行独立存在（binding 时经作用域分级与 fragment 行分离）。
    sel_b = [o for o in out
             if o.qualifiers.get("artifact_key") == "proposal.repair"
             and o.carrier_type == "building"]
    assert len(sel_b) == 1


def test_no_member_facts_no_derivation() -> None:
    facts = [_fact("f1", "procedure.ri.appointment.completed", True, "FR1")]
    assert derive_slot_target_fallback_facts(facts, "W1", "B1") == []


def test_three_tier_emission() -> None:
    """三层发射：fragment 逐键 + 楼级逐键聚合 + 楼级无键联合（v11 歧义修正）。"""
    facts = [
        _fact("f1", "artifact.report.inspection", True, "FR1"),
        _fact("f2", "artifact.report.inspection", False, "FR2"),
        _fact("f3", "artifact.form.mbi4", False, "FR1"),
    ]
    out = derive_slot_target_fallback_facts(facts, "W1", "B1")
    frag_rows = [o for o in out if o.carrier_type == "fragment"]
    bldg_key = [o for o in out if o.carrier_type == "building"
                and "artifact_key" in o.qualifiers]
    bldg_union = [o for o in out if o.carrier_type == "building"
                  and "artifact_key" not in o.qualifiers]
    assert len(frag_rows) == 3
    # 楼级逐键：report.inspection any_true(True,False)=True；form.mbi4=False
    bk = {o.qualifiers["artifact_key"]: o.value_json for o in bldg_key}
    assert bk == {"report.inspection": "true", "form.mbi4": "false"}
    # 楼级联合：任一键真 → true；且带 aggregation 标记（fragment 作用域排除用）
    assert len(bldg_union) == 1 and bldg_union[0].value_json == "true"
    assert all(o.qualifiers.get("aggregation") == "building"
               for o in bldg_key + bldg_union)


def test_method_class_inferred_when_unique() -> None:
    """件4：同载体唯一 method_class 才补维（宁缺勿错）。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        infer_method_class_for_verification_flags,
    )
    flag = _fact("f1", "verification.test.failed", True, "FR1")
    m1 = _fact("m1", "count.pull_test", True, "FR1")
    m1.qualifiers["method_class"] = "pull_test"
    # 同载体
    flag2 = _fact("f2", "verification.test.failed", True, "FR2")
    m2a = _fact("m2a", "x", True, "FR2"); m2a.qualifiers["method_class"] = "pull_test"
    m2b = _fact("m2b", "y", True, "FR2"); m2b.qualifiers["method_class"] = "core_sample"
    for a, carrier in ((flag, "C1"), (m1, "C1"), (flag2, "C2"), (m2a, "C2"), (m2b, "C2")):
        object.__setattr__(a, "carrier_id", carrier) if False else setattr(a, "carrier_id", carrier)
    atoms = [flag, m1, flag2, m2a, m2b]
    infer_method_class_for_verification_flags(atoms)
    assert flag.qualifiers.get("method_class") == "pull_test"
    assert "method_class" not in flag2.qualifiers  # 歧义不补
