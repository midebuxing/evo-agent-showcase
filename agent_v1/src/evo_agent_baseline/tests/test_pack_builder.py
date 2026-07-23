"""FactPack / RuleSlice 组装器测试（spec §5.4.3 + §5.5 + §5.6）。

不依赖 Neo4j：测节点 dict → FactAtom / DTO 转换、扁平子图 → RuleCardDTO
原嵌套还原、FactPack / RuleSlice 组装。
"""

from __future__ import annotations

import json

import pytest

from evo_agent_baseline.contracts import FactAtom, FactPack, RuleCardDTO, RuleSlice
from evo_agent_baseline.closure import identity_blueprint_catalog as catalog_builder
from evo_agent_baseline.closure.obligation_deriver import _card_clause_ids
from evo_agent_baseline.ingest import rulecard_loader
from evo_agent_baseline.ingest._graphspec import assert_node_blind_safe
from evo_agent_baseline.ingest.guard import FORBIDDEN_AGENT_PROPERTIES, SecurityError
from evo_agent_baseline.retrieval import pack_builder


# ===========================================================================
# §5.5 FactAtom 构造
# ===========================================================================
def test_fact_atom_from_carrier_field() -> None:
    """承载节点字段 → FactAtom，fact_id 合成 carrier_id::field。"""
    node = {"building_id": "BLD-1", "building_use": "industrial"}
    atom = pack_builder.fact_atom_from_carrier_field(
        node, "Building", "WB-1", "BLD-1", "building_use", "industrial",
        source_path="buildings.parquet",
    )
    assert atom.fact_id == "BLD-1::building_use"
    assert atom.carrier_type == "building"
    assert atom.carrier_id == "BLD-1"
    assert atom.value_type == "string"
    assert json.loads(atom.value_json) == "industrial"


def test_fact_atoms_from_measurement() -> None:
    """Measurement 节点 → FactAtom（spec §3.3.4：qualifiers 从 qualifiers_json 解析）。"""
    node = {
        "measurement_id": "MSR-1", "target_ref": "FRG-1",
        "slot_id": "test.slot", "value_json": "0.5",
        "unit": "ratio", "qualifiers_json": '{"actor":"ri"}',
        "confidence_index": 0.9,
    }
    atom = pack_builder.fact_atoms_from_measurement(node, "WB-1", "BLD-1")
    assert atom.carrier_type == "measurement"
    assert atom.fact_id == "MSR-1"
    assert atom.slot_id == "test.slot"
    assert atom.qualifiers == {"actor": "ri"}   # dict，不是字符串
    assert atom.value_type == "number"


def test_fact_atom_from_sidecar_entry() -> None:
    """SidecarEntry 节点 → FactAtom。"""
    node = {
        "sidecar_entry_id": "SCR-1::facts::0", "slot_id": "qual.actor_role",
        "value_json": '"building_authority"', "qualifiers_json": "{}",
        "entry_type": "facts",
    }
    atom = pack_builder.fact_atom_from_sidecar_entry(node, "WB-1", "BLD-1")
    assert atom.carrier_type == "sidecar_entry"
    assert atom.value_type == "string"


def test_fact_atoms_from_condition_derived_flags() -> None:
    """ConditionState derived_outcomes 展为多条 FactAtom（spec §3.3.2 规则 3）。"""
    node = {
        "condition_id": "CND-1",
        "risk_flags_json": json.dumps({"risk.public_danger.present": True}),
        "repair_flags_json": json.dumps({"repair.required": False}),
        "verification_flags_json": "{}",
        "assessment_flags_json": "{}",
        "risk_index_values_json": "{}",
        "fallback_reasons_json": "{}",
    }
    atoms = pack_builder.fact_atoms_from_condition_derived_flags(node, "WB-1", "BLD-1")
    assert len(atoms) == 2
    slots = {a.slot_id for a in atoms}
    assert "risk.public_danger.present" in slots
    assert "repair.required" in slots
    # 每条 carrier_type=condition。
    assert all(a.carrier_type == "condition" for a in atoms)


# ===========================================================================
# §5.5 FactPack 组装
# ===========================================================================
def test_build_fact_pack_inverted_indexes() -> None:
    """FactPack 的 slot_index / measure_index / carrier_index 是倒排索引（spec §5.5）。"""
    facts = [
        FactAtom(
            fact_id="F1", world_id="WB-1", building_id="BLD-1",
            carrier_type="condition", carrier_id="CND-1", target_ref=None,
            slot_id="slot.a", measure_key=None, value_json="true",
            value_type="boolean", unit=None, source_path="x", source_node_id="CND-1",
        ),
        FactAtom(
            fact_id="F2", world_id="WB-1", building_id="BLD-1",
            carrier_type="measurement", carrier_id="MSR-1", target_ref=None,
            slot_id="slot.a", measure_key="measure.x", value_json="1.0",
            value_type="number", unit=None, source_path="x", source_node_id="MSR-1",
        ),
    ]
    pack = pack_builder.build_fact_pack("RUN-1", "WB-1", "BLD-1", facts, ["t.parquet"])
    assert isinstance(pack, FactPack)
    # slot.a 命中两条 fact。
    assert set(pack.slot_index["slot.a"]) == {"F1", "F2"}
    assert pack.measure_index["measure.x"] == ["F2"]
    assert set(pack.carrier_index.keys()) == {"CND-1", "MSR-1"}


# ===========================================================================
# §5.4.3 扁平子图 → RuleCardDTO 原嵌套还原
# ===========================================================================
def _expansion_row() -> dict:
    """构造一行 graph expansion 结果。"""
    return {
        "rule_card": {
            "rule_card_id": "rc.test.c01",
            "source_document_id": "MBIS_CoP_2023",
            "normalized_rule_text": "rule text",
            "family_id": "mbis.test.family",
            "primary_actor": "ri", "primary_action": "submit",
            "method_keys_allowed": [],
            "neighbor_families": ["mbis.other"],
            "version_authoring_revision": "1.0.0",
            "version_interpretation_revision": 1,
            "provenance_json": "{}",
        },
        "applicabilities": [{
            "regime": "mbis", "actors": ["ri"], "phase": "reporting",
            "subject": "x", "component_scope": [], "building_scope": ["tag1"],
            "exclusions_json": "[]",
        }],
        "trigger_conditions": [{
            "condition_id": "trg01", "predicate_kind": "slot",
            "slot_ref_id": "sr01", "operator": "==",
            "expected_value_json": "true",
        }],
        "slot_refs": [{
            "slot_ref_id": "sr01", "slot_id": "procedure.x",
            "qualifiers_json": "{}", "roles": ["trigger"], "required": True,
        }],
        "thresholds": [{
            "threshold_regime_id": "t01", "measure_key": "duration.deadline",
            "operator": "<=", "threshold_value_json": "7", "unit": "day",
            "qualifiers_json": "{}", "time_anchor_key": "anchor.x",
            "source_quote_refs": ["sq01"], "formula_json": None,
        }],
        "measures": [{"measure_key": "duration.deadline", "quantity_family": "duration",
                      "unit": "day", "allowed_operators": ["<="],
                      "semantic_meaning": "deadline"}],
        "time_anchors": [{"time_anchor_key": "anchor.x", "semantic_meaning": "x"}],
        "evidence_requirements": [{
            "evidence_requirement_id": "e01", "bucket": "for_matching",
            "kind": "state_timestamp", "required": True, "description": "d",
            "artifact_ids": [], "slot_ref_ids": ["sr01"], "measure_keys": [],
            "required_field_groups": [],
        }],
        "obligation_nodes": [{
            "obligation_node_id": "n01", "node_kind": "obligation",
            "actor": "ri", "action": "submit", "recipient_ids": ["rcpt01"],
            "artifact_ids": ["art01"], "deadline_ids": ["ddl01"],
            "trigger_condition_ids": ["trg01"],
        }],
        "obligation_edges": [],
        "workflow_artifacts": [{
            "artifact_id": "rc.test.c01::art01", "artifact_type": "report",
            "artifact_key": "report.inspection",
        }],
        "workflow_deadlines": [{
            "deadline_id": "rc.test.c01::ddl01", "relation": "within",
            "offset_value": 7, "offset_unit": "day", "time_anchor_key": "anchor.x",
        }],
        "workflow_recipients": [{
            "recipient_id": "rc.test.c01::rcpt01", "recipient_type": "regulator",
            "recipient_key": "ba", "delivery_mode": "submit_to",
        }],
        "source_quotes": [{
            "source_quote_id": "rc.test.c01::sq01", "quote_local_id": "sq01",
            "rule_card_id": "rc.test.c01", "text": "quote", "page": 15,
            "language": "en",
        }],
        "definitions": [],
        "artifacts": [],
    }


def test_rule_card_dto_from_subgraph_preserves_nesting() -> None:
    """扁平子图还原为 RuleCardDTO 原嵌套形态（spec §5.6 要求 1）。"""
    dto = pack_builder.rule_card_dto_from_subgraph(_expansion_row())
    assert isinstance(dto, RuleCardDTO)
    assert dto.rule_card_id == "rc.test.c01"
    # trigger_conditions 还原为 {logic, items[]}。
    assert dto.trigger_conditions["items"][0]["condition_id"] == "trg01"
    # workflow_operands 含 artifacts/deadlines/recipients 嵌套。
    assert dto.workflow_operands["artifacts"][0]["artifact_key"] == "report.inspection"
    assert dto.workflow_operands["recipients"][0]["recipient_key"] == "ba"
    # workflow 子对象 id 去掉 rule_card_id 前缀（还原 local id）。
    assert dto.workflow_operands["artifacts"][0]["artifact_id"] == "art01"
    # obligation_graph 还原为 {nodes, edges}。
    assert dto.obligation_graph["nodes"][0]["obligation_node_id"] == "n01"
    # evidence_requirements 三 bucket。
    assert len(dto.evidence_requirements["for_matching"]) == 1
    # slot_role_map list。
    assert dto.slot_role_map[0]["slot_id"] == "procedure.x"


def test_trigger_logic_any_loader_to_retrieval_roundtrip() -> None:
    """any 经 loader 节点与内存图查询行往返后保持不变。"""
    card = {
        "rule_card_id": "rc.test.any",
        "source_document_id": "MBIS_CoP_2023",
        "normalized_rule_text": "rule text",
        "family_id": "mbis.test.family",
        "trigger_conditions": {
            "logic": "any",
            "items": [{
                "condition_id": "trg01",
                "predicate_kind": "slot",
                "slot_ref_id": "sr01",
                "operator": "==",
                "expected_value": True,
            }],
        },
    }
    rule_node = rulecard_loader.build_rule_card_node(card)
    trigger_batch = rulecard_loader.build_trigger_nodes(card)
    row = _expansion_row()
    row["rule_card"] = rule_node.all_props()
    row["trigger_conditions"] = [
        node.all_props()
        for node in trigger_batch.nodes
        if node.label == "TriggerCondition"
    ]

    dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert dto.trigger_conditions["logic"] == "any"


def test_source_section_loader_to_retrieval_and_obligation_roundtrip() -> None:
    """两条法规锚经节点 JSON、检索 DTO 后逐字段保真，并可被义务侧消费。"""
    source_section = [
        {"section_id": "2.1.3(o)", "document_id": "MBIS_CoP_2023", "page": 15},
        {"section_id": "App4 2.2-2.3", "note": "表列范围"},
    ]
    card = {
        "rule_card_id": "rc.test.source-section",
        "source_document_id": "MBIS_CoP_2023",
        "normalized_rule_text": "rule text",
        "family_id": "mbis.test.family",
        "trigger_conditions": {"logic": "all", "items": []},
        "source_section": source_section,
    }

    rule_node = rulecard_loader.build_rule_card_node(card)
    assert json.loads(rule_node.props["source_section_json"]) == source_section
    assert "source_section_json" not in FORBIDDEN_AGENT_PROPERTIES
    assert_node_blind_safe(rule_node)

    row = _expansion_row()
    row["rule_card"] = rule_node.all_props()
    dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert dto.source_section == source_section
    assert _card_clause_ids(dto) == ["2.1.3(o)", "App4 2.2-2.3"]


def test_source_section_missing_in_old_kg_defaults_to_empty_without_warning(caplog) -> None:
    """旧库没有 source_section_json 时静默还原为空列表。"""
    row = _expansion_row()
    row["rule_card"]["trigger_logic"] = "all"

    with caplog.at_level("WARNING", logger=pack_builder.__name__):
        dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert dto.source_section == []
    assert not caplog.records


def test_trigger_logic_missing_falls_back_with_warning(caplog) -> None:
    """旧图确实缺 trigger_logic 时回退 all，并留下检索告警。"""
    row = _expansion_row()

    with caplog.at_level("WARNING", logger=pack_builder.__name__):
        dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert dto.trigger_conditions["logic"] == "all"
    assert "has no trigger_logic in KG" in caplog.text


def _definition_card() -> dict:
    """构造带一条 definition 的最小完整卡。"""
    row = _expansion_row()
    dto = pack_builder.rule_card_dto_from_subgraph(row)
    card = dto.model_dump()
    card["workflow_operands"]["audiences"] = []
    card["definitions"] = [{
        "definition_id": "d01",
        "term_key": "ri_supervision_team",
        "definition_text": "注册检验人员组成的监督团队。",
        "scope_note": "适用于现场巡查频率条款。",
        "source_quote_refs": ["sq01"],
    }]
    return card


def test_definition_loader_to_retrieval_roundtrip_preserves_five_fields() -> None:
    """definition 经 loader 节点与内存查询行往返后五字段保真。"""
    card = _definition_card()
    rule_node = rulecard_loader.build_rule_card_node(card)
    definition_batch = rulecard_loader.build_definition_nodes(card)
    row = _expansion_row()
    row["rule_card"] = rule_node.all_props()
    row["definitions"] = [
        node.all_props()
        for node in definition_batch.nodes
        if node.label == "ExceptionDefinition"
    ]

    dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert len(dto.definitions) == 1
    assert dto.definitions[0] == card["definitions"][0]
    assert set(dto.definitions[0]) == {
        "definition_id", "term_key", "definition_text", "scope_note",
        "source_quote_refs",
    }


def test_definition_identity_matches_catalog_blueprint() -> None:
    """检索 float 声明与磁盘 blueprint 的 definition 五元组一致。"""
    card = _definition_card()
    rule_node = rulecard_loader.build_rule_card_node(card)
    definition_batch = rulecard_loader.build_definition_nodes(card)
    row = _expansion_row()
    row["rule_card"] = rule_node.all_props()
    row["definitions"] = [node.all_props() for node in definition_batch.nodes]
    float_card = pack_builder.rule_card_dto_from_subgraph(row)

    bundle_text = json.dumps(
        {"bundle_id": "bundle-definition", "cards": [card]}, ensure_ascii=False,
    )
    rule_slice = pack_builder.build_rule_slice(
        run_id="RUN-1", rulecard_bundle_id="bundle-definition",
        candidate_rule_cards=[float_card], rule_families=[], semantic_slots=[],
        measures=[], artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy={},
    )
    fact_pack = pack_builder.build_fact_pack("RUN-1", "WB-1", "BLD-1", [], [])
    catalog = catalog_builder.build_identity_blueprint_catalog_from_text(
        bundle_text, rule_slice, fact_pack,
        {"run_id": "RUN-1", "world_id": "WB-1", "building_id": "BLD-1"},
    )

    declared = {
        key for key in catalog_builder.declare_five_tuples(float_card, [], {})
        if key[3] == "definition"
    }
    blueprint = {key for key in catalog.index if key[3] == "definition"}
    assert declared == blueprint
    assert len(declared) == 1


def test_card_without_definition_returns_empty_without_warning(caplog) -> None:
    """没有 HAS_DEFINITION 行是常态：返回空列表且不发 definition 告警。"""
    row = _expansion_row()
    row["rule_card"]["trigger_logic"] = "all"

    with caplog.at_level("WARNING", logger=pack_builder.__name__):
        dto = pack_builder.rule_card_dto_from_subgraph(row)

    assert dto.definitions == []
    assert "definition" not in caplog.text.lower()


def test_rule_card_dto_threshold_value_restored() -> None:
    """threshold_regimes value 从 threshold_value_json 还原（spec §5.6 要求 3）。"""
    dto = pack_builder.rule_card_dto_from_subgraph(_expansion_row())
    regime = dto.threshold_regimes[0]
    assert regime["value"] == 7
    assert regime["operator"] == "<="


def test_rule_card_dto_formula_restored() -> None:
    """threshold formula 从 formula_json 还原（spec §5.6 要求 3）。"""
    row = _expansion_row()
    row["thresholds"][0]["formula_json"] = json.dumps({"expression": "n^2-2n+3"})
    row["thresholds"][0]["operator"] = "formula"
    dto = pack_builder.rule_card_dto_from_subgraph(row)
    assert dto.threshold_regimes[0]["formula"] == {"expression": "n^2-2n+3"}


def test_rule_card_dto_trigger_measure_fields_restored() -> None:
    """Measure trigger transport fields are restored from the graph row."""
    row = _expansion_row()
    row["trigger_conditions"] = [{
        "condition_id": "m01",
        "predicate_kind": "measure",
        "slot_ref_id": None,
        "operator": ">=",
        "expected_value_json": "3",
        "measure_key": "area.signboard.display",
        "qualifiers_json": '{"component_type_key":"signboard"}',
        "unit": "m2",
    }]
    dto = pack_builder.rule_card_dto_from_subgraph(row)

    item = dto.trigger_conditions["items"][0]
    assert item["condition_id"] == "m01"
    assert item["predicate_kind"] == "measure"
    assert item["measure_key"] == "area.signboard.display"
    assert item["qualifiers"] == {"component_type_key": "signboard"}
    assert item["unit"] == "m2"
    assert item["expected_value"] == 3


def test_rule_card_dto_blind_safe() -> None:
    """RuleCard 节点带 W2 禁止属性 → 装配时 SecurityError（spec §5.6 要求 5）。"""
    row = _expansion_row()
    row["rule_card"]["expected_verdict"] = "compliant"
    with pytest.raises(SecurityError):
        pack_builder.rule_card_dto_from_subgraph(row)


# ===========================================================================
# §5.6 RuleSlice 组装
# ===========================================================================
def test_build_rule_slice_sorted_deterministic() -> None:
    """RuleSlice 的候选卡按 rule_card_id 稳定排序（§5.4.4 确定性）。"""
    dto_a = pack_builder.rule_card_dto_from_subgraph(_expansion_row())
    row_b = _expansion_row()
    row_b["rule_card"]["rule_card_id"] = "rc.test.c00"
    dto_b = pack_builder.rule_card_dto_from_subgraph(row_b)
    rule_slice = pack_builder.build_rule_slice(
        run_id="RUN-1", rulecard_bundle_id="bundle-1",
        candidate_rule_cards=[dto_a, dto_b],
        rule_families=[], semantic_slots=[], measures=[],
        artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy={"k": "v"},
    )
    assert isinstance(rule_slice, RuleSlice)
    # c00 排在 c01 前。
    ids = [c.rule_card_id for c in rule_slice.candidate_rule_cards]
    assert ids == ["rc.test.c00", "rc.test.c01"]


def test_registry_dto_converters() -> None:
    """registry 子 DTO 转换函数。"""
    sslot = pack_builder.semantic_slot_dto_from_node({
        "slot_id": "s.x", "semantic_domain": "d", "allowed_roles": ["trigger"],
        "semantic_meaning": "m",
    })
    assert sslot.slot_id == "s.x"
    measure = pack_builder.measure_dto_from_node({
        "measure_key": "m.x", "quantity_family": "duration", "unit": "day",
        "allowed_operators": ["<="], "semantic_meaning": "m",
    })
    assert measure.measure_key == "m.x"
    sq = pack_builder.source_quote_dto_from_node({
        "source_quote_id": "rc::sq01", "quote_local_id": "sq01",
        "rule_card_id": "rc", "text": "t", "page": 1, "language": "en",
    })
    assert sq.source_quote_id == "rc::sq01"
    assert sq.quote_local_id == "sq01"


def test_measurement_fact_merges_method_class_into_qualifiers() -> None:
    """Measurement 节点 method_class 并入 qualifiers（spec §6.3.10.3 绑定授权；
    method_index 从 qualifiers.method_class 建索引，不并入则永不可达）。"""
    atom = pack_builder.fact_atoms_from_measurement(
        {"measurement_id": "m01", "slot_id": "count.pull_test",
         "value_json": "3", "qualifiers_json": "{}",
         "method_class": "pull_test"},
        "W1", "B1",
    )
    assert atom.qualifiers["method_class"] == "pull_test"


def test_measurement_fact_method_class_no_overwrite() -> None:
    """qualifiers_json 已带 method_class 时节点属性不覆盖。"""
    atom = pack_builder.fact_atoms_from_measurement(
        {"measurement_id": "m02", "slot_id": "count.pull_test",
         "value_json": "3", "qualifiers_json": '{"method_class": "tap_test"}',
         "method_class": "pull_test"},
        "W1", "B1",
    )
    assert atom.qualifiers["method_class"] == "tap_test"


def test_sidecar_entry_restores_unit() -> None:
    """量纲第 5 跳：SidecarEntry 节点 unit → FactAtom.unit（q6 裁定链）。"""
    atom = pack_builder.fact_atom_from_sidecar_entry(
        {"sidecar_entry_id": "e1", "slot_id": "ratio.covered_structure_area.inspected",
         "value_json": "0.4", "qualifiers_json": "{}", "unit": "ratio"},
        "W1", "B1",
    )
    assert atom.unit == "ratio"
