"""缺陷类组合桥双极派生（spec 草案·缺陷类组合桥 2026-07-08 定稿）。

成员缺陷类 ∧ 组件类 → 目标缺陷类；双极（未命中出 false，封闭世界缺席=真缺席）；
组件类不在桥内的 fragment 不出事实（外墙裂缝不入 structural_damage_sign）。
"""

from __future__ import annotations

from evo_agent_baseline.retrieval.fact_retriever import (
    FactRetrievalRaw,
    derive_combination_bridge_facts,
)

BRIDGES = [{
    "target_defect_class_key": "structural_damage_sign",
    "member_condition_classes": ["DC_CRACK"],
    "component_classes": ["structural_component"],
    "bipolar": True,
}]
ALIASES = {"component_type_key": {
    "structural_member": "structural_component",
    "external_wall": "external_wall",
}}


def _raw():
    return FactRetrievalRaw(
        fragments=[
            {"fragment_id": "FR1", "component_id": "C1"},   # 结构构件·有裂缝
            {"fragment_id": "FR2", "component_id": "C1"},   # 结构构件·无缺陷
            {"fragment_id": "FR3", "component_id": "C2"},   # 外墙·有裂缝（不入桥）
        ],
        components=[
            {"component_id": "C1", "component_type": "structural_member"},
            {"component_id": "C2", "component_type": "external_wall"},
        ],
        conditions=[
            {"condition_id": "cd1", "fragment_id": "FR1",
             "condition_classes": ["DC_CRACK", "DC_MOISTURE_STAINING"]},
            {"condition_id": "cd3", "fragment_id": "FR3",
             "condition_classes": ["DC_CRACK"]},
        ],
    )


def test_bridge_bipolar_and_component_scoping() -> None:
    atoms = derive_combination_bridge_facts(_raw(), BRIDGES, ALIASES, "W1", "B1")
    by_frag = {a.qualifiers["fragment_id"]: a for a in atoms}
    # 结构构件命中 → true；结构构件无成员类 → false（双极）；外墙不出事实。
    assert by_frag["FR1"].value_json == "true"
    assert by_frag["FR2"].value_json == "false"
    assert "FR3" not in by_frag
    assert all(a.qualifiers["defect_class_key"] == "structural_damage_sign"
               for a in atoms)
    assert all(a.slot_id == "defect.class.present" for a in atoms)


def test_bridge_unipolar_when_bipolar_false() -> None:
    bridges = [dict(BRIDGES[0], bipolar=False)]
    atoms = derive_combination_bridge_facts(_raw(), bridges, ALIASES, "W1", "B1")
    frags = {a.qualifiers["fragment_id"] for a in atoms}
    assert frags == {"FR1"}


def test_bridge_empty_table_no_atoms() -> None:
    assert derive_combination_bridge_facts(_raw(), [], ALIASES, "W1", "B1") == []
