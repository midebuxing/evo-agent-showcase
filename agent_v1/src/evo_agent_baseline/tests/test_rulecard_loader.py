"""rule_card loader 测试：rule_card v2 → 结构化子节点（spec §4.3 + §3.4）。

不依赖 Neo4j。测 section_id 归一化、各子结构转换、formula 保留、
端到端 397 卡灌库 + 全部质量门。
"""

from __future__ import annotations

from pathlib import Path

from evo_agent_baseline.ingest import rulecard_loader
from evo_agent_baseline.ingest.guard import AuditLog, FORBIDDEN_AGENT_PROPERTIES


# ===========================================================================
# §4.3.4 section_id 归一化
# ===========================================================================
def test_normalize_section_id_already_normal() -> None:
    """已是点号 / 括号形态 → 原样返回（spec §4.3.4）。"""
    assert rulecard_loader.normalize_section_id("2.1.3(o)") == "2.1.3(o)"
    assert rulecard_loader.normalize_section_id("3.4.2") == "3.4.2"


def test_normalize_section_id_underscore_form() -> None:
    """下划线形态 s2_1_3_o → 2.1.3(o)（spec §4.3.4）。"""
    assert rulecard_loader.normalize_section_id("s2_1_3_o") == "2.1.3(o)"


# ===========================================================================
# §3.4.3 子结构转换（单元 dict）
# ===========================================================================
def _minimal_card() -> dict:
    """最小可用的 rule card dict。"""
    return {
        "rule_card_id": "rc.test.c01",
        "source_document_id": "MBIS_CoP_2023",
        "family_id": "mbis.test.family",
        "normalized_rule_text": "test rule",
        "applicability": {"regime": "mbis", "actors": ["ri"], "phase": "reporting",
                          "subject": "x", "component_scope": [], "building_scope": [],
                          "exclusions": []},
        "source_quote": [],
        "source_section": [],
        "trigger_conditions": {"logic": "all", "items": []},
        "workflow_operands": {},
        "slot_role_map": [],
        "threshold_regimes": [],
        "exceptions": [],
        "definitions": [],
        "obligation_graph": {"nodes": [], "edges": []},
        "neighbor_families": [],
        "evidence_requirements": {},
        "version": {"authoring_revision": "1.0.0", "interpretation_revision": 1},
        "provenance": {},
    }


def test_build_source_quote_synthesizes_local_id() -> None:
    """source_quote 无 quote_id → 生成 sq%02d（spec §3.4.3）。"""
    card = _minimal_card()
    card["source_quote"] = [{"text": "quote text", "page": 1}]
    batch = rulecard_loader.build_source_quote_nodes(card, AuditLog())
    quotes = [n for n in batch.nodes if n.label == "SourceQuote"]
    assert len(quotes) == 1
    assert quotes[0].props["quote_local_id"] == "sq01"
    assert quotes[0].key_value == "rc.test.c01::sq01"


def test_build_rule_card_node_preserves_trigger_logic_any() -> None:
    """trigger_conditions.logic 落在父 RuleCard 节点，且 any 不被改写。"""
    card = _minimal_card()
    card["trigger_conditions"]["logic"] = "any"

    node = rulecard_loader.build_rule_card_node(card)

    assert node.props["trigger_logic"] == "any"


def test_build_source_quote_uses_upstream_quote_id() -> None:
    """source_quote 有 quote_id → 用上游 id。"""
    card = _minimal_card()
    card["source_quote"] = [{"quote_id": "sq05", "text": "x"}]
    batch = rulecard_loader.build_source_quote_nodes(card, AuditLog())
    quotes = [n for n in batch.nodes if n.label == "SourceQuote"]
    assert quotes[0].key_value == "rc.test.c01::sq05"


def test_build_threshold_preserves_formula() -> None:
    """RuleThreshold 必须从上游 formula 还原 formula_json（spec §3.4.3 / G-004）。"""
    card = _minimal_card()
    card["threshold_regimes"] = [{
        "threshold_regime_id": "rc.test.c01.t01",
        "measure_key": "count.pull_test.additional_after_failure",
        "operator": "formula",
        "formula": {"expression": "n^2 - 2n + 3",
                    "variables": [{"measure_key": "count.failed", "symbol": "n"}]},
        "unit": "test",
    }]
    batch = rulecard_loader.build_threshold_nodes(card, AuditLog())
    thresholds = [n for n in batch.nodes if n.label == "RuleThreshold"]
    assert len(thresholds) == 1
    assert thresholds[0].props["formula_json"] is not None
    assert "n^2" in thresholds[0].props["formula_json"]
    # family_id 由 loader 从父卡派生（C-2）。
    assert thresholds[0].props["family_id"] == "mbis.test.family"


def test_build_threshold_no_formula_null() -> None:
    """无 formula 的 threshold → formula_json 为 None（spec §3.4.3）。"""
    card = _minimal_card()
    card["threshold_regimes"] = [{
        "threshold_regime_id": "rc.test.c01.t01",
        "measure_key": "duration.deadline", "operator": "<=", "value": 7,
    }]
    batch = rulecard_loader.build_threshold_nodes(card, AuditLog())
    thr = [n for n in batch.nodes if n.label == "RuleThreshold"][0]
    assert thr.props["formula_json"] is None
    assert thr.props["threshold_value_json"] == "7"
    # operator / threshold_value_json / formula_json 命名，不是 W2 ThresholdEval。
    assert "regime_tag" not in thr.props
    assert "pass_bool" not in thr.props


def test_build_obligation_edge_id_format() -> None:
    """ObligationEdge 主键 = rule_card_id::edge::source::relation::target（spec §3.4.3）。"""
    card = _minimal_card()
    card["obligation_graph"] = {
        "nodes": [
            {"obligation_node_id": "n01", "node_kind": "obligation"},
            {"obligation_node_id": "n02", "node_kind": "escalation"},
        ],
        "edges": [
            {"source_node_id": "n01", "target_node_id": "n02",
             "relation": "if_failed_then"},
        ],
    }
    batch = rulecard_loader.build_obligation_edges(card, AuditLog())
    edges = [n for n in batch.nodes if n.label == "ObligationEdge"]
    assert len(edges) == 1
    assert edges[0].key_value == "rc.test.c01::edge::n01::if_failed_then::n02"
    assert edges[0].props["edge_resolution_state"] == "resolved"


def test_build_obligation_edge_unresolved_endpoint() -> None:
    """ObligationEdge 端点缺失 → edge_resolution_state=unresolved（spec §4.3.3 步骤 4）。"""
    card = _minimal_card()
    card["obligation_graph"] = {
        "nodes": [{"obligation_node_id": "n01", "node_kind": "obligation"}],
        "edges": [{"source_node_id": "n01", "target_node_id": "n_missing",
                   "relation": "if_failed_then"}],
    }
    batch = rulecard_loader.build_obligation_edges(card, AuditLog())
    edge = [n for n in batch.nodes if n.label == "ObligationEdge"][0]
    assert edge.props["edge_resolution_state"] == "unresolved"


def test_build_obligation_edge_unknown_relation_kept() -> None:
    """未知 relation 不丢弃，仍落 ObligationEdge + warning（spec §3.4.3）。"""
    audit = AuditLog()
    card = _minimal_card()
    card["obligation_graph"] = {
        "nodes": [
            {"obligation_node_id": "n01", "node_kind": "obligation"},
            {"obligation_node_id": "n02", "node_kind": "obligation"},
        ],
        "edges": [{"source_node_id": "n01", "target_node_id": "n02",
                   "relation": "weird_relation"}],
    }
    batch = rulecard_loader.build_obligation_edges(card, audit)
    assert len([n for n in batch.nodes if n.label == "ObligationEdge"]) == 1
    assert any("weird_relation" in w for w in audit.warnings)


def test_build_evidence_requirement_buckets() -> None:
    """EvidenceRequirement 按 for_matching/for_submission/for_completion 三 bucket。"""
    card = _minimal_card()
    card["evidence_requirements"] = {
        "for_matching": [{"evidence_requirement_id": "e01", "kind": "x",
                          "required": True, "slot_ref_ids": ["sr01"]}],
        "for_submission": [{"evidence_requirement_id": "e02", "kind": "y",
                            "required": False}],
        "for_completion": [],
    }
    batch = rulecard_loader.build_evidence_requirement_nodes(card)
    ers = [n for n in batch.nodes if n.label == "EvidenceRequirement"]
    assert len(ers) == 2
    buckets = {n.props["bucket"] for n in ers}
    assert buckets == {"for_matching", "for_submission"}


# ===========================================================================
# 端到端：真实 rule_card v2 包
# ===========================================================================
def test_missing_component_lattice_is_explicitly_rejected(tmp_path) -> None:
    """变异证据：删掉被忽略的类型格后，直接灌库纯转换入口必须拒绝。"""
    from types import SimpleNamespace

    import pytest

    from evo_agent_baseline.closure.component_lattice import LatticeIngestError

    with pytest.raises(LatticeIngestError, match="类型格派生物缺失|直接灌库已拒绝"):
        rulecard_loader._load_component_lattice_and_authorizations(
            SimpleNamespace(), [], tmp_path, AuditLog()
        )

def test_build_rulecard_graph_real_bundle(rulecard_dir: Path) -> None:
    """真实 rule_card v2 端到端：397 卡 / 43 family（spec §4.3.2）。"""
    result = rulecard_loader.build_rulecard_graph(rulecard_dir, "2026-05-23T00:00:00Z")
    # 沿革：2026-07-28 补 64 张缺卡；2026-08-04 件四批 1 §3.2.6 同义重复卡二保一
    # 退役 1 张（两卷裁定一致，退役卡留档 杂物箱/垃圾箱/2026-08-04_件四批1退役卡_s3_2_6重复/）
    # ⇒ 470 → 469（先量后冻：卡包实测 469）。
    assert result.card_count == 470  # 2026-08-05 #23 补 §5.4.3(b) masonry 缺卡 469→470
    assert result.family_count == 57  # 2026-07-28 补 64 张缺卡 → +9 fine family（44→53）
    assert result.bundle_id == "rulecard_v2.mbis_cop_2023"


def test_build_rulecard_graph_all_quality_gates_pass(rulecard_dir: Path) -> None:
    """真实 rule_card：G-003/G-004/G-005/G-007 全过（build 不抛 QualityGateError）。"""
    # build_rulecard_graph 内部跑全部质量门；不抛异常即 G-003~G-007 通过。
    result = rulecard_loader.build_rulecard_graph(rulecard_dir, "2026-05-23T00:00:00Z")
    assert result.card_count > 0


def test_build_rulecard_graph_child_structures(rulecard_dir: Path) -> None:
    """真实 rule_card：各结构化子节点齐全（spec §4.3.3 不允许只塞 JSON）。"""
    result = rulecard_loader.build_rulecard_graph(rulecard_dir, "2026-05-23T00:00:00Z")
    labels = {n.label for n in result.batch.nodes}
    for required in (
        "RuleCard", "RuleFamily", "SourceQuote", "ApplicabilityPredicate",
        "SlotRef", "TriggerCondition", "RuleThreshold", "ObligationNode",
        "EvidenceRequirement", "SemanticSlot", "Measure", "Artifact", "TimeAnchor",
    ):
        assert required in labels, f"缺子节点类型 {required}"


def test_build_rulecard_graph_no_forbidden_props(rulecard_dir: Path) -> None:
    """真实 rule_card：任何节点不带 §2.2.3 禁止属性名。"""
    result = rulecard_loader.build_rulecard_graph(rulecard_dir, "2026-05-23T00:00:00Z")
    for node in result.batch.nodes:
        leaked = set(node.all_props().keys()) & FORBIDDEN_AGENT_PROPERTIES
        assert not leaked, f"{node.label} 泄露禁止属性 {leaked}"


def test_build_rulecard_graph_formula_card_preserved(rulecard_dir: Path) -> None:
    """真实 rule_card：含 formula 的 RuleThreshold formula_json 非空（G-004）。"""
    result = rulecard_loader.build_rulecard_graph(rulecard_dir, "2026-05-23T00:00:00Z")
    formula_thresholds = [
        n for n in result.batch.nodes
        if n.label == "RuleThreshold" and n.props.get("operator") == "formula"
    ]
    assert len(formula_thresholds) > 0, "rule_card v2 应至少有 1 个 formula threshold"
    for thr in formula_thresholds:
        assert thr.props["formula_json"] is not None


def test_build_trigger_measure_fields_roundtrip() -> None:
    """measure 型触发器三字段必须灌进节点属性（DEBT-048：漏灌致 KG 侧 measure_key=None）。"""
    card = _minimal_card()
    card["trigger_conditions"] = {"logic": "all", "items": [{
        "condition_id": "trg02",
        "predicate_kind": "measure",
        "measure_key": "area.signboard.display",
        "qualifiers": {"component_type_key": "external_wall"},
        "operator": ">",
        "expected_value": 40,
        "unit": "m2",
    }]}
    batch = rulecard_loader.build_trigger_nodes(card)
    nodes = [n for n in batch.nodes if n.label == "TriggerCondition"]
    assert len(nodes) == 1
    props = nodes[0].props
    assert props["measure_key"] == "area.signboard.display"
    assert "external_wall" in (props["qualifiers_json"] or "")
    assert props["unit"] == "m2"


def test_build_trigger_slot_kind_measure_fields_none() -> None:
    """slot 型触发器三字段为空值/空 JSON（形状不变，不影响既有消费方）。"""
    card = _minimal_card()
    card["trigger_conditions"] = {"logic": "all", "items": [{
        "condition_id": "trg01",
        "predicate_kind": "slot",
        "slot_ref_id": "rc.test.c01.sr01",
        "operator": "==",
        "expected_value": True,
    }]}
    batch = rulecard_loader.build_trigger_nodes(card)
    props = [n for n in batch.nodes if n.label == "TriggerCondition"][0].props
    assert props["measure_key"] is None
    assert props["unit"] is None
