"""触发器限定符结构不可满足 → NA（DEBT-050 修案·spec §6.3.3 增补，2026-07-08）。

codex 裁决（方案甲通过/乙否决）测试面：不相容判 NA 三形态、相容保持 missing
（供给缺口护栏）、已有绑定零覆盖、类目成员展开、身份/词表缺失回落、脏 T 护栏。
"""

from __future__ import annotations

import itertools

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_trigger

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
KNOWN = {"structural_component", "drainage_component", "external_wall",
         "cantilevered_canopy", "external_component", "wall_tiles"}
# DEBT-065:组件类型格叶集 + 显式排斥对(触发器级新判据用)。
_LEAF = ["external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"]
_DISJOINT = {frozenset(p) for p in itertools.combinations(_LEAF, 2)}


def _slot_trigger(**over):
    trig = {
        "condition_id": "trg01",
        "predicate_kind": "slot",
        "slot_id": "defect.class.present",
        "operator": "==",
        "expected_value": True,
        "qualifiers": {"defect_class_key": "structural_damage_sign",
                       "component_type_key": "structural_component"},
    }
    trig.update(over)
    return trig


def _empty_index():
    return FactIndex(make_fact_pack([]))


def test_incompatible_fragment_scope_na() -> None:
    """DEBT-065:触发器组件限定恒等于授权目标叶型 × fragment 叶身份可证排斥 → NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META,
        auth_target="cantilevered_canopy",
        w0_identity="drainage_component",
        lattice_disjoint=_DISJOINT,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert o.comparator_result is False
    assert "structurally_unsatisfiable_qualifier" in (o.notes or "")


def test_building_scope_component_na_abolished() -> None:
    """DEBT-065:组件维楼级结构 NA 废止——楼级(单值身份 None)→ 不早退,回落 missing。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META,
        auth_target="cantilevered_canopy",
        w0_identity=None,
        lattice_disjoint=_DISJOINT,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


KNOWN_LC = {"external", "common_part", "common_pipe_duct",
            "public_access_private_lane", "roof_or_platform"}


def test_incompatible_location_na() -> None:
    """②location 维度：卡要 private_lane、fragment location=common_pipe_duct → NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "location_class_key" in (o.notes or "")


def test_compatible_location_keeps_missing() -> None:
    """location 相容而事实缺 → 仍 missing_fact（供给缺口诚实）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "common_pipe_duct"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_location_unknown_scope_falls_back_missing() -> None:
    """作用域 location 未知（None）→ 不判 NA，保持 missing。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_location_classes=None, known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_location_dirty_value_falls_back_missing() -> None:
    """卡 location 脏值（不在已知宇宙）→ 不判 NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "typo_location"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_component_or_location_disjunction() -> None:
    """component 相容但 location 不相容 → 仍 NA（析取）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "drainage_component",
                                  "location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "location_class_key" in (o.notes or "")


def test_compatible_scope_keeps_missing() -> None:
    """结构部位上要求 structural_component 而事实缺 → 仍 open/missing_fact（供给缺口诚实）。"""
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), _empty_index(), META,
        scope_component_types={"structural_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_category_member_not_na() -> None:
    """T 为类目且部位类型属 members（validator 预展开进相容集）→ 不 NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "external_component"}),
        _empty_index(), META,
        # validator 端 _with_categories 已把 external_component 并入外墙部位的相容集
        scope_component_types={"external_wall", "external_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_existing_binding_never_overridden() -> None:
    """已有绑定（即便与相容集矛盾）→ 走正常比较，结构判定绝不触发。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", slot_id="defect.class.present", value=True,
                  value_type="boolean",
                  qualifiers={"defect_class_key": "structural_damage_sign",
                              "component_type_key": "structural_component"}),
    ]))
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), idx, META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_scope_identity_unknown_falls_back_missing() -> None:
    """作用域身份未知（None）→ 判定关闭，保持 missing_fact。"""
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), _empty_index(), META,
        scope_component_types=None, known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_unknown_t_value_falls_back_missing() -> None:
    """T 不在已知身份宇宙（卡端脏值）→ 不得推断 NA，回落 missing_fact。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "typo_component"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_no_component_qualifier_unaffected() -> None:
    """无 component_type_key 限定的触发器（如 s4_3_1_a 单键）行为不变。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"defect_class_key": "crack"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"
