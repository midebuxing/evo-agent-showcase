"""DEBT-047 适用性 subject 词桥单测：三态（无交集 NA / 有交集续判 / 表外不过滤）。"""

from evo_agent_baseline.closure.applicability import (
    collect_building_component_classes,
    evaluate_applicability,
)

from .fixtures import make_fact, make_fact_pack, make_rule_card


def _card(subject):
    return make_rule_card(
        "RC.test.bridge",
        applicability={
            "regime": "mbis",
            "subject": subject,
            "component_scope": ["free text scope"],
        },
    )


_XWALK = {"fire_safety_components": ["fire_safety_component"]}


def test_bridge_no_intersection_not_applicable():
    r = evaluate_applicability(
        _card("fire_safety_components"), make_fact_pack(),
        subject_component_crosswalk=_XWALK,
        building_component_classes={"external_wall", "structural_component"},
    )
    assert r.state == "not_applicable"
    assert any("fire_safety_components" in x for x in r.reasons)


def test_bridge_intersection_continues():
    r = evaluate_applicability(
        _card("fire_safety_components"), make_fact_pack(),
        subject_component_crosswalk=_XWALK,
        building_component_classes={"fire_safety_component"},
    )
    assert r.state != "not_applicable"
    assert "subject_bridge:fire_safety_components" in r.matched_facts


def test_admin_subject_not_filtered():
    """行政/流程类 subject 不在词桥表内 → 不做组件过滤。"""
    r = evaluate_applicability(
        _card("inspection_report"), make_fact_pack(),
        subject_component_crosswalk=_XWALK,
        building_component_classes=set(),
    )
    assert r.state != "not_applicable"


def test_backward_compat_without_bridge():
    """缺省参数（既有调用方式）→ 词桥跳过，行为与 v0.4 相同。"""
    r = evaluate_applicability(_card("fire_safety_components"), make_fact_pack())
    assert r.state != "not_applicable"


def test_building_component_classes_include_controlled_carrier_type():
    """载体类型已在组件词汇中登记时，成为楼内组件类；不依赖 component_type 事实。"""
    pack = make_fact_pack([
        make_fact(
            "F-UBW",
            slot_id="present",
            value=True,
            value_type="boolean",
            carrier_type="ubw",
        ),
    ])
    aliases = {"unauthorized_structure": "ubw"}

    classes = collect_building_component_classes(pack, aliases)

    assert classes == {"ubw"}


def test_building_component_classes_ignore_non_component_carriers():
    """普通载体枚举不在组件词汇中时不得进入组件类集，锁住通用映射的边界。"""
    pack = make_fact_pack([
        make_fact("F-BLD", slot_id="building.use", value="residential"),
        make_fact(
            "F-MSR",
            slot_id=None,
            measure_key="m.test",
            value=1,
            value_type="number",
            carrier_type="measurement",
        ),
    ])

    classes = collect_building_component_classes(
        pack,
        {"unauthorized_structure": "ubw"},
    )

    assert classes == set()


def test_explicit_component_type_source_keeps_existing_alias_semantics():
    """显式 component_type 读取源继续按同一别名表规范化。"""
    pack = make_fact_pack([
        make_fact(
            "F-CT",
            slot_id="component_type",
            value="structural_member",
        ),
    ])

    classes = collect_building_component_classes(
        pack,
        {"structural_member": "structural_component"},
    )

    assert classes == {"structural_component"}
