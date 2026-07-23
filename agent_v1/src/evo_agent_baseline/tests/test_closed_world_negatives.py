"""闭世界负例派生（DEBT-049 第一波 §2 可达集口径 → 第三波件A 闭世界总声明全集口径）。"""

from __future__ import annotations

from evo_agent_baseline.retrieval.fact_retriever import FactRetrievalRaw, facts_from_raw


def test_full_set_field_preferred_over_legacy() -> None:
    """第三波件A：absent_condition_classes（全集）优先；旧可达集字段仅作老池回退。"""
    raw = FactRetrievalRaw(
        world={"world_id": "W1"}, building={"building_id": "B1"},
        conditions=[{
            "condition_id": "CND-1", "fragment_id": "FR1",
            "condition_class": "DC_CRACK",
            "condition_classes": ["DC_CRACK"],
            "generatable_absent_classes": ["DC_DEFORMATION_DISPLACEMENT"],
            "absent_condition_classes": ["DC_DEFORMATION_DISPLACEMENT",
                                          "DC_DRAINAGE_BLOCKAGE"],
        }],
    )
    neg = [a for a in facts_from_raw(raw)
           if a.provenance.get("derivation") == "closed_world_absent_class"]
    keys = {a.qualifiers["defect_class_key"] for a in neg}
    # 全集字段生效：目录不相容/机制不可达类（DRAINAGE_BLOCKAGE）也发负例
    assert keys == {"DC_DEFORMATION_DISPLACEMENT", "DC_DRAINAGE_BLOCKAGE"}
    assert all(a.value_json == "false" for a in neg)


def test_absent_classes_derive_false_facts() -> None:
    raw = FactRetrievalRaw(
        world={"world_id": "W1"}, building={"building_id": "B1"},
        conditions=[{
            "condition_id": "CND-1", "fragment_id": "FR1",
            "condition_class": "DC_CRACK",
            "condition_classes": ["DC_CRACK"],
            "generatable_absent_classes": ["DC_DEFORMATION_DISPLACEMENT"],
        }],
    )
    atoms = facts_from_raw(raw)
    neg = [a for a in atoms
           if a.provenance.get("derivation") == "closed_world_absent_class"]
    assert len(neg) == 1
    a = neg[0]
    assert a.slot_id == "defect.class.present"
    assert a.value_json == "false"
    assert a.qualifiers["defect_class_key"] == "DC_DEFORMATION_DISPLACEMENT"


def test_no_absent_field_no_negatives() -> None:
    raw = FactRetrievalRaw(
        world={"world_id": "W1"}, building={"building_id": "B1"},
        conditions=[{"condition_id": "CND-1", "fragment_id": "FR1",
                     "condition_class": "DC_CRACK"}],
    )
    atoms = facts_from_raw(raw)
    assert not [a for a in atoms
                if a.provenance.get("derivation") == "closed_world_absent_class"]
