"""fact loader 测试：worldgen parquet → 事实侧图节点（spec §4.2 + §3.3）。

不依赖 Neo4j —— 全测 parquet→GraphBatch 的纯转换逻辑。既用单元 dict 测
转换函数，也用真实 worldgen seed 做端到端 build_fact_graph 验证。
"""

from __future__ import annotations

import json
from pathlib import Path

from evo_agent_baseline.ingest import fact_loader
from evo_agent_baseline.ingest._graphspec import compile_batch
from evo_agent_baseline.ingest.guard import AuditLog, FORBIDDEN_AGENT_PROPERTIES


# ===========================================================================
# §3.3.1 核心节点转换（单元 dict）
# ===========================================================================
def test_build_world_node_synthesizes_loader_fields() -> None:
    """World 节点的 source_kind / kg_snapshot_id / loaded_at 由 loader 合成。"""
    row = {
        "world_id": "WB-1", "schema_version": "v1",
        "generator_version": "gen-v2", "random_seed": 42,
    }
    node = fact_loader.build_world_node(row, "KGS-1", "2026-05-23T00:00:00Z")
    assert node.label == "World"
    assert node.key_value == "WB-1"
    assert node.props["source_kind"] == "synthetic_worldgen"
    assert node.props["kg_snapshot_id"] == "KGS-1"
    assert node.props["loaded_at"] == "2026-05-23T00:00:00Z"


def test_build_component_node_extracts_geometry() -> None:
    """Component 从 geometry_proxy_json 浅抽 5 个派生列（spec §3.3.1）。"""
    row = {
        "component_id": "CMP-1", "world_id": "WB-1",
        "component_type": "wall", "material_system": "rc",
        "structural_role": "load_bearing", "location_id": "LOC-1",
        "geometry_proxy_json": json.dumps({"length_m": 24.98, "thickness_mm": 363.8}),
        "access_class": "accessible",
    }
    node = fact_loader.build_component_node(row)
    assert node.props["length_m"] == 24.98
    assert node.props["thickness_mm"] == 363.8
    # 缺失的几何 key 填 None。
    assert node.props["width_m"] is None
    assert node.props["height_m"] is None
    # 原 geometry_proxy_json 保留。
    assert "length_m" in node.props["geometry_proxy_json"]


def test_build_component_node_handles_bad_geometry() -> None:
    """geometry_proxy_json 非法 → 5 个派生列全 None，不报错。"""
    row = {
        "component_id": "CMP-1", "world_id": "WB-1",
        "component_type": "wall", "material_system": "rc",
        "structural_role": "x", "location_id": "LOC-1",
        "geometry_proxy_json": "not-json", "access_class": "x",
    }
    node = fact_loader.build_component_node(row)
    assert node.props["length_m"] is None


def test_build_coverage_node_uses_coverage_state() -> None:
    """CoverageRelation 字段名为 coverage_state，禁止 coverage_status（spec §3.3.1）。"""
    row = {
        "coverage_id": "CVR-1", "world_id": "WB-1",
        "coverage_relation_type": "scope.obscured",
        "coverage_state": "covered", "covered_area_m2": 13.6,
        "inspected_area_m2": 9.1, "obscuration_class": "access_blocked",
    }
    node = fact_loader.build_coverage_node(row)
    assert node.props["coverage_state"] == "covered"
    assert "coverage_status" not in node.props


# ===========================================================================
# §3.3.2 状态节点 + derived_outcomes
# ===========================================================================
def test_build_condition_state_extracts_derived_outcomes() -> None:
    """ConditionState 把 derived_outcomes 六组字段抽为独立 *_json（spec §4.2.5）。"""
    payload = {
        "condition_id": "CND-1", "fragment_id": "FRG-1",
        "condition_class": "spalling", "severity_band": "high",
        "derived_outcomes": {
            "risk_flags": {"risk.public_danger.present": True},
            "repair_flags": {"repair.required": True},
            "verification_flags": {"verification.test.failed": False},
            "assessment_flags": {"assessment.fsp.below_required_safety": True},
            "risk_index_values": {"risk.index": 0.7},
            "fallback_reasons": {},
        },
    }
    row = {
        "world_id": "WB-1", "state_type": "condition",
        "state_id": "CND-1", "fragment_id": "FRG-1",
        "payload_json": json.dumps(payload),
    }
    batch = fact_loader.build_fragment_state(row, AuditLog())
    cond_nodes = [n for n in batch.nodes if n.label == "ConditionState"]
    assert len(cond_nodes) == 1
    props = cond_nodes[0].props
    for group in fact_loader.DERIVED_OUTCOME_GROUPS:
        assert f"{group}_json" in props
    # risk_flags_json 是 canonical JSON 字符串。
    risk = json.loads(props["risk_flags_json"])
    assert risk["risk.public_danger.present"] is True
    assert "derived_outcomes_json" in props


def test_build_condition_state_caused_by_edge() -> None:
    """ConditionState-CAUSED_BY->MechanismState 边（spec §3.3.2）。"""
    payload = {
        "condition_id": "CND-1", "fragment_id": "FRG-1",
        "mechanism_state_id": "MCH-1", "condition_class": "x",
    }
    row = {
        "world_id": "WB-1", "state_type": "condition",
        "state_id": "CND-1", "fragment_id": "FRG-1",
        "payload_json": json.dumps(payload),
    }
    batch = fact_loader.build_fragment_state(row, AuditLog())
    caused_by = [e for e in batch.edges if e.rel_type == "CAUSED_BY"]
    assert len(caused_by) == 1
    assert caused_by[0].end_key_value == "MCH-1"


def test_build_mechanism_state_expands_activations() -> None:
    """MechanismState 把 activated_mechanisms 展为 MechanismActivation（spec §3.3.2）。"""
    payload = {
        "mechanism_state_id": "MCH-1", "fragment_id": "FRG-1",
        "mechanism_family": "corrosion",
        "activated_mechanisms": [
            {
                "mechanism_id": "M-corr-1", "mechanism_family": "corrosion",
                "activation_score": 0.77,
                "derived_from_driver_ids": ["DRV-1"],
            }
        ],
    }
    row = {
        "world_id": "WB-1", "state_type": "mechanism",
        "state_id": "MCH-1", "fragment_id": "FRG-1",
        "payload_json": json.dumps(payload),
    }
    batch = fact_loader.build_fragment_state(row, AuditLog())
    activations = [n for n in batch.nodes if n.label == "MechanismActivation"]
    assert len(activations) == 1
    # 主键 = mechanism_state_id::mechanism_id。
    assert activations[0].key_value == "MCH-1::M-corr-1"
    # DERIVED_FROM_DRIVER 边。
    deriv = [e for e in batch.edges if e.rel_type == "DERIVED_FROM_DRIVER"]
    assert len(deriv) == 1
    assert deriv[0].end_key_value == "DRV-1"


def test_build_fragment_state_unknown_state_type_skipped() -> None:
    """未知 state_type → 跳过 + warning。"""
    audit = AuditLog()
    row = {"world_id": "WB-1", "state_type": "bogus", "state_id": "X-1",
           "payload_json": "{}"}
    batch = fact_loader.build_fragment_state(row, audit)
    assert batch.nodes == []
    assert any("bogus" in w for w in audit.warnings)


# ===========================================================================
# §3.3.3 专项状态
# ===========================================================================
def test_build_specialized_state_drainage() -> None:
    """specialized_states drainage → DrainageState + HAS_DRAINAGE_STATE（spec §4.2.6）。"""
    payload = {
        "drainage_id": "DRN-1", "component_id": "CMP-1",
        "segment_type": "stack", "blockage_index": 0.3,
    }
    row = {"world_id": "WB-1", "state_type": "drainage",
           "state_id": "DRN-1", "payload_json": json.dumps(payload)}
    batch = fact_loader.build_specialized_state(row, AuditLog())
    nodes = [n for n in batch.nodes if n.label == "DrainageState"]
    assert len(nodes) == 1
    assert nodes[0].props["component_id"] == "CMP-1"
    edges = [e for e in batch.edges if e.rel_type == "HAS_DRAINAGE_STATE"]
    assert len(edges) == 1


def test_build_specialized_state_missing_component_id() -> None:
    """specialized_states 缺 component_id → 节点仍写、不建边 + target_unresolved warning。"""
    audit = AuditLog()
    payload = {"ubw_id": "UBW-1"}  # 无 component_id
    row = {"world_id": "WB-1", "state_type": "ubw",
           "state_id": "UBW-1", "payload_json": json.dumps(payload)}
    batch = fact_loader.build_specialized_state(row, audit)
    assert len([n for n in batch.nodes if n.label == "UBWState"]) == 1
    assert [e for e in batch.edges if e.rel_type == "HAS_UBW_STATE"] == []
    assert any("target_unresolved" in w for w in audit.warnings)


# ===========================================================================
# §3.3.4 Measurement
# ===========================================================================
def test_build_measurement_value_resolution() -> None:
    """Measurement 值解析：bool 优先 num 优先 enum（spec §3.3.4）。"""
    # value_num 路径。
    row = {
        "measurement_id": "MSR-1", "world_id": "WB-1",
        "target_ref": "FRG-1", "value_num": 0.5,
        "value_bool": None, "value_enum": None,
    }
    node = fact_loader.build_measurement_node(row)
    assert node.props["value_json"] == "0.5"
    # value_bool 优先于其它。
    row2 = dict(row, value_bool=True, value_num=0.5)
    node2 = fact_loader.build_measurement_node(row2)
    assert node2.props["value_json"] == "true"


def test_build_measurement_derivation_refs_merge() -> None:
    """Measurement 合并 4 个 ref 别名列 stable_unique（spec §3.3.4）。"""
    row = {
        "measurement_id": "MSR-1", "world_id": "WB-1", "target_ref": "FRG-1",
        "derivation_refs": ["A", "B"], "upstream_refs": ["B", "C"],
        "origin_chain_refs": ["C"], "derived_from_measurement_ids": ["D"],
    }
    node = fact_loader.build_measurement_node(row)
    # 去重保序：A, B, C, D。
    assert node.props["derivation_refs"] == ["A", "B", "C", "D"]


def test_resolve_target_kind() -> None:
    """measurement target_ref 解析优先级 Fragment > Component > Condition（spec §4.2.7）。"""
    fragments = {"FRG-1"}
    components = {"CMP-1"}
    conditions = {"CND-1"}
    assert fact_loader.resolve_target_kind("FRG-1", fragments, components, conditions) == "fragment"
    assert fact_loader.resolve_target_kind("CMP-1", fragments, components, conditions) == "component"
    assert fact_loader.resolve_target_kind("CND-1", fragments, components, conditions) == "condition"
    assert fact_loader.resolve_target_kind("ZZZ", fragments, components, conditions) == "unknown"


def test_measurement_target_edge_unknown_no_edge() -> None:
    """target_kind=unknown → 不建 target 边（spec §4.2.7）。"""
    assert fact_loader.measurement_target_edge("MSR-1", "ZZZ", "unknown") is None
    edge = fact_loader.measurement_target_edge("MSR-1", "FRG-1", "fragment")
    assert edge is not None
    assert edge.rel_type == "HAS_MEASUREMENT"
    assert edge.start_label == "Fragment"


# ===========================================================================
# 端到端：真实 worldgen seed
# ===========================================================================
def test_build_fact_graph_real_seed(worldgen_seed_dir: Path) -> None:
    """真实 worldgen seed 端到端 build_fact_graph。"""
    result = fact_loader.build_fact_graph(
        worldgen_seed_dir, "KGS-test", "2026-05-23T00:00:00Z"
    )
    # 应有 world / building / fragment 等核心节点。
    assert len(result.world_ids) > 0
    assert len(result.building_ids) > 0
    assert len(result.fragment_ids) > 0
    labels = {n.label for n in result.batch.nodes}
    assert "World" in labels
    assert "Building" in labels
    assert "Fragment" in labels
    assert "Measurement" in labels
    assert "ConditionState" in labels


def test_build_fact_graph_no_forbidden_props(worldgen_seed_dir: Path) -> None:
    """fact loader 产出的任何节点都不带 §2.2.3 禁止属性名（evo-agent blind）。"""
    result = fact_loader.build_fact_graph(
        worldgen_seed_dir, "KGS-test", "2026-05-23T00:00:00Z"
    )
    for node in result.batch.nodes:
        leaked = set(node.all_props().keys()) & FORBIDDEN_AGENT_PROPERTIES
        assert not leaked, f"{node.label} 泄露禁止属性 {leaked}"


def test_build_fact_graph_compiles(worldgen_seed_dir: Path) -> None:
    """真实 seed 的 GraphBatch 全量可编译为 MERGE 语句（blind 检查在编译期跑）。"""
    result = fact_loader.build_fact_graph(
        worldgen_seed_dir, "KGS-test", "2026-05-23T00:00:00Z"
    )
    statements = compile_batch(result.batch)
    assert len(statements) == len(result.batch.nodes) + len(result.batch.edges)
    # 全是 MERGE，无 CREATE。
    assert all("CREATE " not in cypher for cypher, _ in statements)
