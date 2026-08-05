"""DEBT-081 触发器级结构 NA 正向授权（六字段键，2026-08-02 决策门形态）。

面：①精确命中→NA 带 source_combo ②邻接原生型不搭便车 ③限定符形状漂移→
授权行失效（fail-visible 注记）④缺省空=逐位不变 ⑤condition_id 不符不命中
⑥missing_fact 形态同样命中（授权与「有事实但不匹配/无事实」正交）。
键=(卡, condition_id, slot_ref_id, 要求类型, 叶身份, **原生型**)——原生型防
规范叶型过粗（fire_door 的叶身份就是 fire_safety_component）。
"""
from __future__ import annotations

from evo_agent_baseline.closure.applicability_v3 import canonical_hash
from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_trigger

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
SLOT = "defect.class.present"
QUALS = {"component_type_key": "cantilevered_canopy"}


def _trigger():
    return {"condition_id": "trg01", "predicate_kind": "slot",
            "slot_id": SLOT, "operator": "==", "expected_value": True,
            "qualifiers": dict(QUALS)}


def _mismatch_fact():
    return make_fact("F-auth-01", slot_id=SLOT, value=True,
                     value_type="boolean",
                     qualifiers={"component_type_key": "external_wall"})


def _auth(shape_quals=None, combo=42):
    key = ("RC.test.001", "trg01", "", "cantilevered_canopy",
           "external_wall", "canopy")
    return {key: {
        "qualifiers_shape_sha256": canonical_hash(
            dict(QUALS) if shape_quals is None else shape_quals),
        "source_combo_no": combo,
    }}


def _run(auth, raw="canopy", facts=None):
    idx = FactIndex(make_fact_pack(
        [_mismatch_fact()] if facts is None else facts))
    return evaluate_trigger(
        make_rule_card(), _trigger(), idx, META,
        auth_target=None, w0_identity="external_wall",
        lattice_disjoint=frozenset(),
        trigger_na_authorizations=auth, w0_raw_type=raw,
    )


def test_exact_hit_yields_authorized_na():
    o = _run(_auth())
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert o.comparator_result is False
    assert "authorized_structural_na: source_combo=42" in (o.notes or "")


def test_adjacent_raw_type_does_not_free_ride():
    """同叶身份、不同原生型（如未来 fire_resisting_wall 形状）→ 不命中。"""
    o = _run(_auth(), raw="drainage_stack")
    assert (o.closure_status, o.blocked_reason_code) == (
        "blocked", "qualifier_conflict")
    assert "authorized_structural_na" not in (o.notes or "")


def test_qualifier_shape_drift_invalidates_row():
    """卡限定符形状与裁定时不同 → 该授权行失效、保持原路径并注记漂移。"""
    o = _run(_auth(shape_quals={"component_type_key": "cantilevered_canopy",
                                "location_class_key": "external"}))
    assert (o.closure_status, o.blocked_reason_code) == (
        "blocked", "qualifier_conflict")
    assert "trigger_na_auth_shape_drift" in (o.notes or "")


def test_default_empty_bitwise_unchanged():
    for auth in (None, {}):
        o = _run(auth)
        assert (o.closure_status, o.blocked_reason_code) == (
            "blocked", "qualifier_conflict")
        assert "authorized_structural_na" not in (o.notes or "")
        assert "trigger_na_auth_shape_drift" not in (o.notes or "")


def test_condition_id_mismatch_no_hit():
    auth = _auth()
    ((card_id, _cid, sr, rct, leaf, raw), val), = auth.items()
    o = _run({(card_id, "trg99", sr, rct, leaf, raw): val})
    assert (o.closure_status, o.blocked_reason_code) == (
        "blocked", "qualifier_conflict")


def test_missing_fact_shape_also_hits():
    o = _run(_auth(), facts=[])
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "authorized_structural_na" in (o.notes or "")
