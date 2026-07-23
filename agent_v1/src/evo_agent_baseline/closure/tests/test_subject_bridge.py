"""DEBT-047 适用性 subject 词桥单测：三态（无交集 NA / 有交集续判 / 表外不过滤）。"""

from evo_agent_baseline.closure.applicability import evaluate_applicability

from .fixtures import make_fact_pack, make_rule_card


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
