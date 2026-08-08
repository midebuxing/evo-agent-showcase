"""DEBT-040 修复单测：CoverageRelation → scope.component.* 存在性事实。

背景：coverage_relations.parquet 早已声明为事实源并灌成 KG 节点，但检索从未消费
（FactRetrievalRaw 无字段、facts_from_raw 不展开），触发器查 scope.component.* 恒
missing。本测锁"消费链存在且形状正确"。
"""

from evo_agent_baseline.retrieval.fact_retriever import FactRetrievalRaw, facts_from_raw
from evo_agent_baseline.retrieval.pack_builder import fact_atom_from_coverage_relation


def _cvr_node(**over):
    node = {
        "coverage_id": "CVR-T-0001",
        "world_id": "WB-T",
        "coverage_relation_type": "scope.component.in_scope",
        "coverage_state": "covered",
        "covered_area_m2": 12.5,
        "inspected_area_m2": 12.5,
    }
    node.update(over)
    return node


def test_converter_shape():
    atom = fact_atom_from_coverage_relation(_cvr_node(), "FRG-T-0", "WB-T", "BLD-T")
    assert atom.fact_id == "CVR-T-0001"
    assert atom.slot_id == "scope.component.in_scope"
    assert atom.value_json == "true"
    assert atom.value_type == "boolean"
    assert atom.carrier_type == "fragment"
    assert atom.carrier_id == "FRG-T-0"
    assert atom.qualifiers["fragment_id"] == "FRG-T-0"
    assert atom.source_path == "coverage_relations.parquet"


def test_converter_obscuration_qualifier():
    atom = fact_atom_from_coverage_relation(
        _cvr_node(
            coverage_relation_type="scope.component.obscured_by_services",
            obscuration_class="access_blocked",
        ),
        "FRG-T-1", "WB-T", "BLD-T",
    )
    assert atom.slot_id == "scope.component.obscured_by_services"
    assert atom.qualifiers["obscuration_class"] == "access_blocked"


def test_facts_from_raw_expands_coverage_relations():
    raw = FactRetrievalRaw(
        world={"world_id": "WB-T"},
        building={"building_id": "BLD-T"},
        coverage_relations=[
            dict(_cvr_node(), _fragment_id="FRG-T-0"),
            dict(
                _cvr_node(
                    coverage_id="CVR-T-0002",
                    coverage_relation_type="scope.component.excluded_from_scope",
                ),
                _fragment_id="FRG-T-1",
            ),
        ],
    )
    atoms = facts_from_raw(raw)
    cov = [a for a in atoms if a.source_path == "coverage_relations.parquet"]
    assert len(cov) == 2
    assert {a.slot_id for a in cov} == {
        "scope.component.in_scope",
        "scope.component.excluded_from_scope",
    }
    assert {a.carrier_id for a in cov} == {"FRG-T-0", "FRG-T-1"}


def test_enrich_qualifiers_from_structure():
    """DEBT-040 ②：按 Fragment→Component/Location 结构充实规范限定符。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        enrich_qualifiers_from_structure,
    )

    raw = FactRetrievalRaw(
        world={"world_id": "WB-T"},
        building={"building_id": "BLD-T"},
        fragments=[
            {"fragment_id": "FRG-T-0", "component_id": "CMP-T-0", "location_id": "LOC-T-0"},
        ],
        components=[{"component_id": "CMP-T-0", "component_type": "structural_member"}],
        locations=[{"location_id": "LOC-T-0", "location_class": "external_wall"}],
        coverage_relations=[dict(_cvr_node(), _fragment_id="FRG-T-0")],
    )
    atoms = facts_from_raw(raw)
    aliases = {
        "component_type_key": {"structural_member": "structural_component"},
        "location_class_key": {"external_wall": "external"},
    }
    enrich_qualifiers_from_structure(atoms, raw, aliases)
    cov = [a for a in atoms if a.source_path == "coverage_relations.parquet"][0]
    assert cov.qualifiers["component_type_key"] == "structural_component"
    assert cov.qualifiers["location_class_key"] == "external"


def test_enrich_skips_unmapped_and_existing():
    """无对照的原生值不写；已有键不覆盖。"""
    from evo_agent_baseline.retrieval.fact_retriever import (
        enrich_qualifiers_from_structure,
    )

    raw = FactRetrievalRaw(
        world={"world_id": "WB-T"},
        building={"building_id": "BLD-T"},
        fragments=[
            {"fragment_id": "FRG-T-0", "component_id": "CMP-T-0", "location_id": "LOC-T-9"},
        ],
        components=[{"component_id": "CMP-T-0", "component_type": "transfer_floor_thing"}],
        locations=[{"location_id": "LOC-T-9", "location_class": "transfer_floor"}],
        coverage_relations=[dict(_cvr_node(), _fragment_id="FRG-T-0")],
    )
    atoms = facts_from_raw(raw)
    cov = [a for a in atoms if a.source_path == "coverage_relations.parquet"][0]
    cov.qualifiers["component_type_key"] = "preset_value"
    aliases = {"component_type_key": {"transfer_floor_thing": "should_not_overwrite"}}
    enrich_qualifiers_from_structure(atoms, raw, aliases)
    assert cov.qualifiers["component_type_key"] == "preset_value"  # 不覆盖
    assert "location_class_key" not in cov.qualifiers  # transfer_floor 无对照不写


def test_authority_alias_table_maps_private_premises():
    """2026-08-07 卡包合流乙随窗小修：权威别名表必须含 `private_premises` 键。

    背景（`裁定_结构闸新8卡_20260807.md` §〇）：`qualifier_value_aliases.
    location_class_key` 原 9 行无 `private_premises` 键，`enrich_qualifiers_from_
    structure` 查不到别名就**不写限定符**（宁缺勿错的保守规则）——即便世界生成了
    私人处所片段，`(×, private_premises)` 组合照样出不来；新 8 卡维持组（4/6/7/8）
    的载体正确性依赖该键。本测吃**权威文件本体**，不吃合成表——防止表修了测试
    还绿、或表被回退而测试不红。
    """
    import json
    import pathlib

    from evo_agent_baseline.retrieval.fact_retriever import (
        enrich_qualifiers_from_structure,
    )

    reg_dir = (pathlib.Path(__file__).resolve().parents[3]
               / "regulations" / "rulecard_v2" / "mbis_cop_2023")
    mapping = json.loads((reg_dir / "projection_runtime_mapping_v1.json")
                         .read_text(encoding="utf-8"))
    aliases = mapping["qualifier_value_aliases"]
    lc = aliases["location_class_key"]
    assert lc.get("private_premises") == "private_premises"
    vocab = json.loads((reg_dir / "controlled_vocabularies_v1.json")
                       .read_text(encoding="utf-8"))
    assert "private_premises" in vocab["vocabularies"]["location_class_key"], (
        "规范值必须真在受控词表里——别名表不许指向词表外取值"
    )

    # 端到端：私人处所片段的事实经权威表真的被盖上限定符（生产者→消费者接口，
    # 不止测表本身）。
    raw = FactRetrievalRaw(
        world={"world_id": "WB-T"},
        building={"building_id": "BLD-T"},
        fragments=[
            {"fragment_id": "FRG-T-P", "component_id": "CMP-T-P", "location_id": "LOC-T-P"},
        ],
        components=[{"component_id": "CMP-T-P", "component_type": "floor_trap"}],
        locations=[{"location_id": "LOC-T-P", "location_class": "private_premises"}],
        coverage_relations=[dict(_cvr_node(), _fragment_id="FRG-T-P")],
    )
    atoms = facts_from_raw(raw)
    enrich_qualifiers_from_structure(atoms, raw, aliases)
    cov = [a for a in atoms if a.source_path == "coverage_relations.parquet"][0]
    assert cov.qualifiers["location_class_key"] == "private_premises"
