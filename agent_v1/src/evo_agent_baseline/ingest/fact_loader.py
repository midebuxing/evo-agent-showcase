"""agent fact loader：W0/W1 worldgen parquet → 事实侧 KG（spec §4.2 + §3.3）。

把 worldgen 9 张 parquet 灌入 Neo4j 事实侧 KG（不含 sidecar —— sidecar 见
`sidecar_loader.py`）。本模块严格只读 §2.2.1 白名单，绝不碰 §2.2.2 黑名单（W2）。

设计：parquet → `GraphBatch`（NodeSpec/EdgeSpec）的转换是纯函数，不依赖 Neo4j，
可全量单测；写入由 `load_fact_kg` 经 `Neo4jClient.write_many` 完成。

实现的 spec 章节：
- §3.3.1 核心节点 World/Building/Component/Location/Fragment/CoverageRelation；
- §3.3.2 状态节点 Driver/Mechanism/MechanismActivation/Condition/ManifestationFlag/RepairAssessment；
- §3.3.3 专项状态 Drainage/UBW/FireSafety；
- §3.3.4 Measurement；
- §4.2.4 ~ §4.2.7 各 parquet → graph 映射、状态分派、target 解析。

evo-agent blind：fact loader 只产事实层节点，不产任何 W2 label / 属性；
所有 NodeSpec 经 `assert_node_blind_safe`（在 `_graphspec` 编译期）二次拦截。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from evo_agent_baseline.ingest._common import (
    as_str_list,
    canonical_json,
    normalize_value,
    opt_float,
    opt_int,
    opt_str,
    read_parquet_rows,
    shallow_extract,
    stable_unique,
)
from evo_agent_baseline.ingest._graphspec import EdgeSpec, GraphBatch, NodeSpec
from evo_agent_baseline.ingest.guard import AuditLog

# ---------------------------------------------------------------------------
# §4.2.5 fragment_states 状态分派表
# ---------------------------------------------------------------------------
STATE_TYPE_LABEL: Dict[str, str] = {
    "driver": "DriverState",
    "mechanism": "MechanismState",
    "condition": "ConditionState",
    "repair_assessment": "RepairAssessmentState",
}

# §4.2.6 specialized_states 状态分派表
SPECIALIZED_STATE_LABEL: Dict[str, str] = {
    "drainage": "DrainageState",
    "ubw": "UBWState",
    "fire_safety": "FireSafetyState",
}

# §3.3.2 ConditionState derived_outcomes 六组字段
DERIVED_OUTCOME_GROUPS: List[str] = [
    "risk_flags",
    "repair_flags",
    "verification_flags",
    "assessment_flags",
    "risk_index_values",
    "fallback_reasons",
]

# 各状态节点高频抽取字段（spec §3.3.2 / §3.3.3 抽取字段块）。
_DRIVER_FIELDS = [
    "driver_id", "fragment_id",
    "service_load_ratio", "restraint_level", "moisture_ingress_index",
    "chloride_exposure_index", "carbonation_index",
    "workmanship_deficit_index", "maintenance_deficit_index",
    "drainage_fault_propensity", "alteration_propensity",
    "fire_safety_deficit_index", "repair_quality_index",
]
_MECHANISM_FIELDS = [
    "mechanism_state_id", "fragment_id",
    "mechanism_family", "active", "severity_index",
    "primary_mechanism_id", "crack_mechanism_kind",
    "corrosion_active", "delamination_active",
    "drainage_fault_kind", "ubw_signal_kind",
    "fire_safety_deficiency_kind",
    "assessment_origin_kind", "verification_origin_kind",
    "cause_tags",
]
_CONDITION_FIELDS = [
    "condition_id", "fragment_id", "mechanism_state_id",
    "condition_class", "severity_band", "severity_index",
    "extent_area_m2", "extent_length_m", "depth_mm", "count",
    "uncertainty_flag", "condition_classes", "source_tags",
    # DEBT-049 第一波 §2 可达缺席类（第三波后降级审计辅助）+ 第三波件A 全集缺席类
    # （闭世界总声明——检索侧负例派生的主消费字段，旧字段作老池回退）。
    "generatable_absent_classes",
    "absent_condition_classes",
]
_REPAIR_FIELDS = [
    "repair_assessment_id", "fragment_id",
    "repair_quality_index", "repair_required", "maintenance_required",
    "verification_failed", "safe_until_next_cycle", "residual_risk_index",
    "notes",
]
_DRAINAGE_FIELDS = [
    "drainage_id", "component_id", "segment_type",
    "connection_state", "blockage_index", "leakage_index",
    "misconnection_present", "public_health_risk_index",
    # DEBT-049 Phase3 U5 §2.1a：地上/地下判别（air_test 两压力档分档）
    "is_underground",
]
_UBW_FIELDS = [
    "ubw_id", "component_id", "alteration_type",
    "authorization_status_proxy", "present",
    "subdivided_unit_sign_present",
    "structural_impact_index", "structural_impact",
]
_FIRE_FIELDS = [
    "fire_state_id", "component_id",
    "fire_component_class", "deficiency_class",
    "deficiency_present", "severity_index",
    "record_status_proxy", "component_deficiency_present",
]


# ===========================================================================
# 加载结果
# ===========================================================================
@dataclass
class FactLoadResult:
    """fact loader 灌库结果（不含 sidecar）。"""

    batch: GraphBatch
    world_ids: Set[str] = field(default_factory=set)
    building_ids: Set[str] = field(default_factory=set)
    audit: AuditLog = field(default_factory=AuditLog)
    # 已知 id 集合，供下游 target 解析复用。
    fragment_ids: Set[str] = field(default_factory=set)
    component_ids: Set[str] = field(default_factory=set)
    condition_ids: Set[str] = field(default_factory=set)


def _qualifier_hash(value: Any) -> str:
    """对 qualifiers 取稳定短 hash（ManifestationFlag 合成主键用，spec §3.3.2）。"""
    digest = hashlib.sha1(canonical_json(value).encode("utf-8")).hexdigest()
    return digest[:12]


def derive_manifestation_flags(
    condition_classes: Optional[List[str]],
    fragment_in_scope: Optional[bool],
    component_type: Optional[str],
) -> List[Dict[str, Any]]:
    """spec v1 §3.2.1 ManifestationFlag 派生协议——从 condition_classes + fragment.in_scope +
    component.component_type 派生 12 个语义槽 flag。

    pure function，可独立单测；不查 Neo4j、不依赖 audit log。

    Args:
        condition_classes: condition.condition_classes 字段。
        fragment_in_scope: fragment.in_scope（None 等价 True 兜底）。
        component_type: component.component_type（None 时 domain-gated flag 一律 not_applicable）。

    Returns:
        12 条 ManifestationFlag dict（slot_id / value / qualifier_ids / notes）。
    """
    cc = set(condition_classes or [])
    in_scope_val = True if fragment_in_scope is None else bool(fragment_in_scope)
    is_drainage = component_type == "drainage_stack"
    is_ubw = component_type == "unauthorized_structure"
    qualifier_ids: Dict[str, Any] = (
        {"qual.component_type": component_type} if component_type else {}
    )
    notes = ["derived_by_fact_loader_v1"]

    def _flag(slot_id: str, value: Any) -> Dict[str, Any]:
        return {
            "slot_id": slot_id,
            "value": value,
            "qualifier_ids": qualifier_ids,
            "notes": notes,
        }

    def _domain_gated(in_domain: bool, present_when_in_domain: bool) -> Any:
        return present_when_in_domain if in_domain else "not_applicable"

    return [
        _flag("scope.component.in_scope", in_scope_val),
        _flag("scope.component.excluded_from_scope", not in_scope_val),
        _flag("defect.class.present", bool(cc)),
        _flag("defect.moisture_or_leakage.present", bool({"DC_MOISTURE_STAINING", "DC_LEAKAGE"} & cc)),
        _flag("defect.detachment_or_loose_fixing.present", bool({"DC_DETACHMENT", "DC_LOOSE_FIXING"} & cc)),
        _flag("defect.hollowing.present", "DC_HOLLOWING" in cc),
        _flag("defect.drainage.misconnection.present", _domain_gated(is_drainage, "DC_DRAINAGE_MISCONNECTION" in cc)),
        _flag("defect.drainage.blockage.present", _domain_gated(is_drainage, "DC_DRAINAGE_BLOCKAGE" in cc)),
        _flag("defect.drainage.leakage.present", _domain_gated(is_drainage, "DC_DRAINAGE_LEAKAGE" in cc)),
        _flag("defect.ubw.present", "DC_UBW_PRESENT" in cc),
        _flag("defect.subdivided_unit_sign.present", _domain_gated(is_ubw, "DC_SUBDIVIDED_SIGN" in cc)),
        _flag("defect.fire_safety.component_deficiency.present", bool({"DC_FIRE_DOOR_DEFICIENCY", "DC_FIRE_STOP_DEFICIENCY"} & cc)),
    ]


# ===========================================================================
# §3.3.1 核心节点转换
# ===========================================================================
def build_world_node(row: Dict[str, Any], kg_snapshot_id: str, loaded_at: str) -> NodeSpec:
    """buildings/meta 行 → (:World) 节点（spec §3.3.1）。

    World 与 Building 同源于 buildings.parquet（每行含 world_id + building_id）。

    Args:
        row: buildings.parquet 或 meta 的一行 dict。
        kg_snapshot_id: 本次灌库快照 id（loader 合成）。
        loaded_at: ISO 时间戳（loader 合成）。

    Returns:
        World NodeSpec。
    """
    props = {
        "schema_version": opt_str(row.get("schema_version")) or "unknown",
        "generator_version": opt_str(row.get("generator_version")) or "unknown",
        "random_seed": opt_int(row.get("random_seed")),
        "deterministic_key": opt_str(row.get("deterministic_key")),
        "source_kind": "synthetic_worldgen",     # loader 合成（固定值）
        "kg_snapshot_id": kg_snapshot_id,        # loader 合成
        "loaded_at": loaded_at,                  # loader 合成
    }
    return NodeSpec("World", "world_id", row["world_id"], props)


def build_building_node(row: Dict[str, Any]) -> NodeSpec:
    """buildings.parquet 行 → (:Building) 节点（spec §3.3.1）。

    BuildingContext 8 个业务字段 + BuildingMetadata 3 个 metadata 字段
    （building_template_id / building_name / unit_count）合表存储，
    均落 Building，metadata 字段照 spec 注释保留但语义上属 metadata。
    """
    props = {
        "world_id": row["world_id"],   # parquet FK
        "building_use": opt_str(row.get("building_use")),
        "structure_type": opt_str(row.get("structure_type")),
        "age_years": opt_float(row.get("age_years")),
        "storey_count": opt_int(row.get("storey_count")),
        "primary_materials": as_str_list(row.get("primary_materials")),
        "configuration_tags": as_str_list(row.get("configuration_tags")),
        "occupancy_state": opt_str(row.get("occupancy_state")),
        # BuildingMetadata（generator / reporting metadata；W2 不消费）。
        "building_template_id": opt_str(row.get("building_template_id")),
        "building_name": opt_str(row.get("building_name")),
        "unit_count": opt_int(row.get("unit_count")),
    }
    return NodeSpec("Building", "building_id", row["building_id"], props)


def build_component_node(row: Dict[str, Any]) -> NodeSpec:
    """components.parquet 行 → (:Component) 节点（spec §3.3.1）。

    §3.3.1 派生列规则：从 geometry_proxy_json 浅抽 5 个数值派生列，
    任一 key 缺失或无法 cast 数值填 null，并保留原 geometry_proxy_json。
    """
    geometry_json = opt_str(row.get("geometry_proxy_json")) or "{}"
    geometry: Dict[str, Any] = {}
    try:
        import json as _json

        parsed = _json.loads(geometry_json)
        if isinstance(parsed, dict):
            geometry = parsed
    except (ValueError, TypeError):
        geometry = {}

    props = {
        "world_id": row["world_id"],
        "component_type": opt_str(row.get("component_type")),
        "parent_component_id": opt_str(row.get("parent_component_id")),
        "material_system": opt_str(row.get("material_system")),
        "structural_role": opt_str(row.get("structural_role")),
        "location_id": opt_str(row.get("location_id")),
        "geometry_proxy_json": geometry_json,
        "cover_depth_mm": opt_float(row.get("cover_depth_mm")),
        "access_class": opt_str(row.get("access_class")),
        # loader 派生：shallow key extraction，缺失填 null。
        "length_m": opt_float(geometry.get("length_m")),
        "width_m": opt_float(geometry.get("width_m")),
        "height_m": opt_float(geometry.get("height_m")),
        "visible_area_m2": opt_float(geometry.get("visible_area_m2")),
        "thickness_mm": opt_float(geometry.get("thickness_mm")),
    }
    return NodeSpec("Component", "component_id", row["component_id"], props)


def build_location_node(row: Dict[str, Any]) -> NodeSpec:
    """locations.parquet 行 → (:Location) 节点（spec §3.3.1）。"""
    props = {
        "world_id": row["world_id"],
        "location_class": opt_str(row.get("location_class")),
        "exposure_zone": opt_str(row.get("exposure_zone")),
        "storey_band": opt_str(row.get("storey_band")),       # 缺失则 None
        "spatial_tags": as_str_list(row.get("spatial_tags")),  # 缺失则 []
    }
    return NodeSpec("Location", "location_id", row["location_id"], props)


def build_fragment_node(row: Dict[str, Any]) -> NodeSpec:
    """fragments.parquet 行 → (:Fragment) 节点（spec §3.3.1）。"""
    props = {
        "world_id": row["world_id"],
        "fragment_template_id": opt_str(row.get("fragment_template_id")),
        "component_id": opt_str(row.get("component_id")),
        "location_id": opt_str(row.get("location_id")),
        "fragment_role": opt_str(row.get("fragment_role")),
        "fragment_area_m2": opt_float(row.get("fragment_area_m2")),
        "fragment_length_m": opt_float(row.get("fragment_length_m")),
        "in_scope": _as_bool(row.get("in_scope")),
        "exclusion_reason": opt_str(row.get("exclusion_reason")),
    }
    return NodeSpec("Fragment", "fragment_id", row["fragment_id"], props)


def build_coverage_node(row: Dict[str, Any]) -> NodeSpec:
    """coverage_relations.parquet 行 → (:CoverageRelation) 节点（spec §3.3.1）。

    spec §3.3.1 注意：字段名统一 `coverage_state`，禁止 W2 `coverage_status`。
    """
    props = {
        "world_id": row["world_id"],
        "coverage_relation_type": opt_str(row.get("coverage_relation_type")),
        "coverage_state": opt_str(row.get("coverage_state")),   # 禁止 coverage_status
        "covered_area_m2": opt_float(row.get("covered_area_m2")),
        "inspected_area_m2": opt_float(row.get("inspected_area_m2")),
        "obscuration_class": opt_str(row.get("obscuration_class")),
    }
    return NodeSpec("CoverageRelation", "coverage_id", row["coverage_id"], props)


def _as_bool(value: Any) -> Optional[bool]:
    """规整为 Optional[bool]。"""
    value = normalize_value(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "yes", "1"}:
            return True
        if low in {"false", "no", "0"}:
            return False
    return None


# ===========================================================================
# §3.3.2 / §3.3.3 状态节点转换
# ===========================================================================
def build_fragment_state(row: Dict[str, Any], audit: AuditLog) -> GraphBatch:
    """fragment_states.parquet 一行 → 对应状态节点 + 边（spec §4.2.5）。

    按 state_type 分派为 Driver/Mechanism/Condition/RepairAssessment。
    每行：payload=json.loads(payload_json)，抽高频字段，原 dict 存 payload_json。

    Args:
        row: fragment_states.parquet 一行。
        audit: 审计记录器。

    Returns:
        GraphBatch（状态节点 + Fragment 关联边 + 子结构）。
    """
    import json as _json

    batch = GraphBatch()
    state_type = opt_str(row.get("state_type"))
    label = STATE_TYPE_LABEL.get(state_type or "")
    if label is None:
        audit.warn(f"fragment_states: unknown state_type {state_type!r}, row skipped")
        return batch

    payload_json = opt_str(row.get("payload_json")) or "{}"
    try:
        payload = _json.loads(payload_json)
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    world_id = opt_str(row.get("world_id"))
    fragment_id = opt_str(row.get("fragment_id")) or opt_str(payload.get("fragment_id"))
    state_id = opt_str(row.get("state_id"))
    if state_id is None:
        audit.warn(f"fragment_states: missing state_id for {label}, row skipped")
        return batch

    if state_type == "driver":
        node = _build_driver_node(state_id, world_id, payload, payload_json)
    elif state_type == "mechanism":
        node = _build_mechanism_node(state_id, world_id, payload, payload_json)
    elif state_type == "condition":
        node = _build_condition_node(state_id, world_id, payload, payload_json)
    else:  # repair_assessment
        node = _build_repair_node(state_id, world_id, payload, payload_json)
    batch.add_node(node)

    # Fragment 关联边。
    rel_by_label = {
        "DriverState": "HAS_DRIVER_STATE",
        "MechanismState": "HAS_MECHANISM_STATE",
        "ConditionState": "HAS_CONDITION",
        "RepairAssessmentState": "HAS_REPAIR_ASSESSMENT",
    }
    if fragment_id:
        batch.add_edge(EdgeSpec(
            "Fragment", "fragment_id", fragment_id,
            rel_by_label[label],
            label, node.key_prop, state_id,
        ))
    else:
        audit.warn(f"{label} {state_id}: no fragment_id, HAS_* edge not built")

    # MechanismState 额外子结构：MechanismActivation + CAUSED_BY 等。
    if state_type == "mechanism":
        _expand_mechanism(batch, state_id, world_id, payload, audit)
    if state_type == "condition":
        _expand_condition(batch, state_id, world_id, payload, audit)

    return batch


def _build_driver_node(
    state_id: str, world_id: Optional[str], payload: Dict[str, Any], payload_json: str
) -> NodeSpec:
    """构造 (:DriverState) 节点（spec §3.3.2）。"""
    props = shallow_extract(payload, _DRIVER_FIELDS)
    props["world_id"] = world_id
    props["payload_json"] = payload_json
    props.pop("driver_id", None)  # 作主键不重复落 props
    return NodeSpec("DriverState", "driver_id", state_id, props)


def _build_mechanism_node(
    state_id: str, world_id: Optional[str], payload: Dict[str, Any], payload_json: str
) -> NodeSpec:
    """构造 (:MechanismState) 节点（spec §3.3.2）。"""
    props = shallow_extract(payload, _MECHANISM_FIELDS)
    props["world_id"] = world_id
    props["payload_json"] = payload_json
    props.pop("mechanism_state_id", None)
    return NodeSpec("MechanismState", "mechanism_state_id", state_id, props)


def _build_condition_node(
    state_id: str, world_id: Optional[str], payload: Dict[str, Any], payload_json: str
) -> NodeSpec:
    """构造 (:ConditionState) 节点（spec §3.3.2 derived_outcomes 处理规则）。"""
    props = shallow_extract(payload, _CONDITION_FIELDS)
    props["world_id"] = world_id
    props["payload_json"] = payload_json
    props.pop("condition_id", None)

    # spec §4.2.5：condition 必须抽 derived_outcomes 六组字段为独立 *_json。
    derived = payload.get("derived_outcomes") or {}
    if not isinstance(derived, dict):
        derived = {}
    props["derived_outcomes_json"] = canonical_json(derived)
    for key in DERIVED_OUTCOME_GROUPS:
        props[f"{key}_json"] = canonical_json(derived.get(key, {}))
    return NodeSpec("ConditionState", "condition_id", state_id, props)


def _build_repair_node(
    state_id: str, world_id: Optional[str], payload: Dict[str, Any], payload_json: str
) -> NodeSpec:
    """构造 (:RepairAssessmentState) 节点（spec §3.3.2）。"""
    props = shallow_extract(payload, _REPAIR_FIELDS)
    props["world_id"] = world_id
    props["payload_json"] = payload_json
    props.pop("repair_assessment_id", None)
    return NodeSpec("RepairAssessmentState", "repair_assessment_id", state_id, props)


def _expand_mechanism(
    batch: GraphBatch,
    mechanism_state_id: str,
    world_id: Optional[str],
    payload: Dict[str, Any],
    audit: AuditLog,
) -> None:
    """展开 MechanismState 的 activated_mechanisms 为 (:MechanismActivation)（spec §3.3.2）。"""
    # MechanismState-DERIVED_FROM_DRIVER->DriverState（payload 无明确 driver 列时跳过）。
    activations = payload.get("activated_mechanisms") or []
    if not isinstance(activations, list):
        return
    for act in activations:
        if not isinstance(act, dict):
            continue
        mechanism_id = opt_str(act.get("mechanism_id"))
        if mechanism_id is None:
            audit.warn(f"{mechanism_state_id}: activation without mechanism_id, skipped")
            continue
        activation_id = f"{mechanism_state_id}::{mechanism_id}"
        driver_ids = as_str_list(act.get("derived_from_driver_ids"))
        props = {
            "mechanism_state_id": mechanism_state_id,
            "world_id": world_id,
            "mechanism_id": mechanism_id,
            "mechanism_family": opt_str(act.get("mechanism_family")),
            "activation_score": opt_float(act.get("activation_score")),
            "derived_from_driver_ids": driver_ids,
            "notes": as_str_list(act.get("notes")),
        }
        batch.add_node(NodeSpec(
            "MechanismActivation", "mechanism_activation_id", activation_id, props
        ))
        batch.add_edge(EdgeSpec(
            "MechanismState", "mechanism_state_id", mechanism_state_id,
            "HAS_ACTIVATION",
            "MechanismActivation", "mechanism_activation_id", activation_id,
        ))
        # §3.3.2：DERIVED_FROM_DRIVER 边源为 derived_from_driver_ids[]；
        # 列表空不建边，id 不存在写 warning（写入期 MATCH 端点不命中即静默不建）。
        for driver_id in driver_ids:
            batch.add_edge(EdgeSpec(
                "MechanismActivation", "mechanism_activation_id", activation_id,
                "DERIVED_FROM_DRIVER",
                "DriverState", "driver_id", driver_id,
            ))


def _expand_condition(
    batch: GraphBatch,
    condition_id: str,
    world_id: Optional[str],
    payload: Dict[str, Any],
    audit: AuditLog,
) -> None:
    """展开 ConditionState 的 manifestation_flags 与 CAUSED_BY 边（spec §3.3.2）。"""
    # ConditionState-CAUSED_BY->MechanismState。
    mechanism_state_id = opt_str(payload.get("mechanism_state_id"))
    if mechanism_state_id:
        batch.add_edge(EdgeSpec(
            "ConditionState", "condition_id", condition_id,
            "CAUSED_BY",
            "MechanismState", "mechanism_state_id", mechanism_state_id,
        ))

    flags = payload.get("manifestation_flags") or []
    if not isinstance(flags, list):
        return
    for flag in flags:
        if not isinstance(flag, dict):
            continue
        slot_id = opt_str(flag.get("slot_id"))
        if slot_id is None:
            audit.warn(f"{condition_id}: manifestation_flag without slot_id, skipped")
            continue
        qualifier_ids = flag.get("qualifier_ids") or flag.get("qualifiers") or {}
        flag_id = f"{condition_id}::{slot_id}::{_qualifier_hash(qualifier_ids)}"
        props = {
            "condition_id": condition_id,
            "world_id": world_id,
            "slot_id": slot_id,
            "value_json": canonical_json(flag.get("value")),
            "qualifier_ids": canonical_json(qualifier_ids),
            "notes": as_str_list(flag.get("notes")),
        }
        batch.add_node(NodeSpec(
            "ManifestationFlag", "manifestation_flag_id", flag_id, props
        ))
        batch.add_edge(EdgeSpec(
            "ConditionState", "condition_id", condition_id,
            "HAS_MANIFESTATION_FLAG",
            "ManifestationFlag", "manifestation_flag_id", flag_id,
        ))
        # REALIZES_SLOT 桥接边：slot 在 registry 存在时由写入期 MATCH 决定是否建。
        batch.add_edge(EdgeSpec(
            "ManifestationFlag", "manifestation_flag_id", flag_id,
            "REALIZES_SLOT",
            "SemanticSlot", "slot_id", slot_id,
        ))


def build_specialized_state(row: Dict[str, Any], audit: AuditLog) -> GraphBatch:
    """specialized_states.parquet 一行 → Drainage/UBW/FireSafety 节点（spec §4.2.6）。

    specialized_states 只有 state_type + payload_json + state_id；
    component_id 必须从 payload 读取后建 HAS_*_STATE 边。

    Args:
        row: specialized_states.parquet 一行。
        audit: 审计记录器。

    Returns:
        GraphBatch。
    """
    import json as _json

    batch = GraphBatch()
    state_type = opt_str(row.get("state_type"))
    label = SPECIALIZED_STATE_LABEL.get(state_type or "")
    if label is None:
        audit.warn(f"specialized_states: unknown state_type {state_type!r}, skipped")
        return batch

    payload_json = opt_str(row.get("payload_json")) or "{}"
    try:
        payload = _json.loads(payload_json)
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    world_id = opt_str(row.get("world_id"))
    state_id = opt_str(row.get("state_id"))
    component_id = opt_str(payload.get("component_id"))
    if state_id is None:
        audit.warn(f"specialized_states: missing state_id for {label}, skipped")
        return batch

    field_map = {
        "DrainageState": (_DRAINAGE_FIELDS, "drainage_id", "HAS_DRAINAGE_STATE"),
        "UBWState": (_UBW_FIELDS, "ubw_id", "HAS_UBW_STATE"),
        "FireSafetyState": (_FIRE_FIELDS, "fire_state_id", "HAS_FIRE_SAFETY_STATE"),
    }
    fields, key_prop, rel_type = field_map[label]
    props = shallow_extract(payload, fields)
    props["world_id"] = world_id
    props["payload_json"] = payload_json
    props.pop(key_prop, None)
    # §4.2.6：component_id 缺失/找不到时节点仍写入，component_id=null，记 target_unresolved。
    props["component_id"] = component_id
    batch.add_node(NodeSpec(label, key_prop, state_id, props))

    if component_id:
        batch.add_edge(EdgeSpec(
            "Component", "component_id", component_id,
            rel_type,
            label, key_prop, state_id,
        ))
    else:
        audit.warn(f"{label} {state_id}: target_unresolved (no component_id), HAS_* edge not built")

    return batch


# ===========================================================================
# §3.3.4 Measurement 转换
# ===========================================================================
def build_measurement_node(row: Dict[str, Any]) -> NodeSpec:
    """measurements.parquet 行 → (:Measurement) 节点（spec §3.3.4）。

    值解析、qualifiers canonicalize、derivation_refs 四列合并 stable_unique
    全按 spec §3.3.4 代码块。target_kind 由 target_ref 解析（见 resolve_target_kind）。
    """
    value_bool = normalize_value(row.get("value_bool"))
    value_num = normalize_value(row.get("value_num"))
    value_enum = normalize_value(row.get("value_enum"))
    # spec §3.3.4 值解析规则。
    if value_bool is not None:
        value_json = canonical_json(bool(value_bool))
    elif value_num is not None:
        value_json = canonical_json(value_num)
    elif value_enum is not None:
        value_json = canonical_json(value_enum)
    else:
        value_json = "null"

    # derivation_refs 四列合并（spec §3.3.4 迁移期别名列处理）。
    merged_refs = stable_unique(
        as_str_list(row.get("derivation_refs"))
        + as_str_list(row.get("upstream_refs"))
        + as_str_list(row.get("origin_chain_refs"))
        + as_str_list(row.get("derived_from_measurement_ids"))
    )

    # qualifiers canonical JSON。
    qualifiers_raw = opt_str(row.get("qualifiers_json"))
    if qualifiers_raw is not None:
        try:
            import json as _json

            qualifiers_json = canonical_json(_json.loads(qualifiers_raw))
        except (ValueError, TypeError):
            qualifiers_json = "{}"
    else:
        qualifiers_json = "{}"

    target_ref = opt_str(row.get("target_ref"))
    props = {
        "world_id": row["world_id"],
        "target_ref": target_ref,
        "target_kind": "unknown",   # 由 resolve_target_kind 在已知 id 集合就绪后改写
        "measurement_family": opt_str(row.get("measurement_family")),
        "slot_id": opt_str(row.get("slot_id")),
        "value_num": opt_float(value_num) if value_num is not None else None,
        "value_bool": _as_bool(value_bool) if value_bool is not None else None,
        "value_enum": opt_str(value_enum) if value_enum is not None else None,
        "value_json": value_json,
        "unit": opt_str(row.get("unit")),
        "precision_class": opt_str(row.get("precision_class")),
        "method_class": opt_str(row.get("method_class")),
        "sample_count": opt_int(row.get("sample_count")),
        "confidence_index": opt_float(row.get("confidence_index")),
        "derivation_refs": merged_refs,
        "derivation_mode": opt_str(row.get("derivation_mode")),
        "qualifiers_json": qualifiers_json,
        "notes": as_str_list(row.get("notes")),
    }
    return NodeSpec("Measurement", "measurement_id", row["measurement_id"], props)


def resolve_target_kind(
    target_ref: Optional[str],
    fragment_ids: Set[str],
    component_ids: Set[str],
    condition_ids: Set[str],
) -> str:
    """解析 measurement target_ref 的承载类型（spec §4.2.7）。

    优先级 Fragment > Component > ConditionState > Unknown。

    Args:
        target_ref: measurement.target_ref。
        fragment_ids / component_ids / condition_ids: 已知 id 集合。

    Returns:
        "fragment" / "component" / "condition" / "unknown"。
    """
    if target_ref is None:
        return "unknown"
    if target_ref in fragment_ids:
        return "fragment"
    if target_ref in component_ids:
        return "component"
    if target_ref in condition_ids:
        return "condition"
    return "unknown"


def measurement_target_edge(
    measurement_id: str, target_ref: Optional[str], target_kind: str
) -> Optional[EdgeSpec]:
    """按 target_kind 构造 measurement 的 HAS_MEASUREMENT 边（spec §4.2.7）。

    target_kind="unknown" 时不建 target 边（返回 None）。

    Returns:
        EdgeSpec 或 None。
    """
    if target_ref is None or target_kind == "unknown":
        return None
    label_by_kind = {
        "fragment": ("Fragment", "fragment_id"),
        "component": ("Component", "component_id"),
        "condition": ("ConditionState", "condition_id"),
    }
    start_label, start_key = label_by_kind[target_kind]
    return EdgeSpec(
        start_label, start_key, target_ref,
        "HAS_MEASUREMENT",
        "Measurement", "measurement_id", measurement_id,
    )


# ===========================================================================
# 顶层灌库编排
# ===========================================================================
def _find_table(run_dir: Path, table_name: str) -> Optional[Path]:
    """在 run_dir 下递归找指定 parquet 文件（worldgen 产出可能是 *.parquet 目录嵌套）。

    Args:
        run_dir: 灌库输入根目录。
        table_name: 文件名（如 buildings.parquet）。

    Returns:
        匹配到的 Path，或 None。
    """
    direct = run_dir / table_name
    if direct.is_file():
        return direct
    matches = sorted(run_dir.rglob(table_name))
    for match in matches:
        if match.is_file():
            return match
    return None


def build_fact_graph(
    run_dir: Path,
    kg_snapshot_id: str,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> FactLoadResult:
    """把一个 worldgen 输出目录转换为事实侧 GraphBatch（纯转换，不写 Neo4j）。

    本函数是 fact loader 的可单测核心：只读 §2.2.1 白名单 worldgen 表
    （不含 sidecar），产出 GraphBatch；写入由 `load_fact_kg` 负责。

    Args:
        run_dir: 灌库输入目录（含 WorldgenWorldBundles.v2.parquet/ 等子目录）。
        kg_snapshot_id: 本次快照 id。
        loaded_at: ISO 时间戳。
        audit: 复用的审计记录器。

    Returns:
        FactLoadResult。
    """
    audit = audit or AuditLog()
    result = FactLoadResult(batch=GraphBatch(), audit=audit)

    # --- buildings.parquet → World + Building ---
    buildings_path = _find_table(run_dir, "buildings.parquet")
    if buildings_path is not None:
        audit.record_source("buildings.parquet")
        seen_worlds: Set[str] = set()
        for row in read_parquet_rows(buildings_path):
            world_id = opt_str(row.get("world_id"))
            building_id = opt_str(row.get("building_id"))
            if world_id and world_id not in seen_worlds:
                seen_worlds.add(world_id)
                result.batch.add_node(build_world_node(row, kg_snapshot_id, loaded_at))
                result.world_ids.add(world_id)
            if building_id:
                result.batch.add_node(build_building_node(row))
                result.building_ids.add(building_id)
                if world_id:
                    result.batch.add_edge(EdgeSpec(
                        "World", "world_id", world_id,
                        "HAS_BUILDING",
                        "Building", "building_id", building_id,
                    ))
    else:
        audit.warn("buildings.parquet not found")

    # --- components.parquet → Component + 边 ---
    components_path = _find_table(run_dir, "components.parquet")
    if components_path is not None:
        audit.record_source("components.parquet")
        building_by_world: Dict[str, str] = {}
        # buildings 已加载：world → building 映射（每 world 一 building）。
        for node in result.batch.nodes:
            if node.label == "Building":
                building_by_world[node.props["world_id"]] = node.key_value
        for row in read_parquet_rows(components_path):
            component_id = opt_str(row.get("component_id"))
            if component_id is None:
                continue
            result.batch.add_node(build_component_node(row))
            result.component_ids.add(component_id)
            world_id = opt_str(row.get("world_id"))
            building_id = building_by_world.get(world_id or "")
            if building_id:
                result.batch.add_edge(EdgeSpec(
                    "Building", "building_id", building_id,
                    "HAS_COMPONENT",
                    "Component", "component_id", component_id,
                ))
            parent_id = opt_str(row.get("parent_component_id"))
            if parent_id:
                result.batch.add_edge(EdgeSpec(
                    "Component", "component_id", parent_id,
                    "PARENT_OF",
                    "Component", "component_id", component_id,
                ))
            location_id = opt_str(row.get("location_id"))
            if location_id:
                result.batch.add_edge(EdgeSpec(
                    "Component", "component_id", component_id,
                    "LOCATED_AT",
                    "Location", "location_id", location_id,
                ))
    else:
        audit.warn("components.parquet not found")

    # --- locations.parquet → Location + HAS_LOCATION ---
    locations_path = _find_table(run_dir, "locations.parquet")
    if locations_path is not None:
        audit.record_source("locations.parquet")
        building_by_world = {
            n.props["world_id"]: n.key_value
            for n in result.batch.nodes if n.label == "Building"
        }
        for row in read_parquet_rows(locations_path):
            location_id = opt_str(row.get("location_id"))
            if location_id is None:
                continue
            result.batch.add_node(build_location_node(row))
            building_id = building_by_world.get(opt_str(row.get("world_id")) or "")
            if building_id:
                result.batch.add_edge(EdgeSpec(
                    "Building", "building_id", building_id,
                    "HAS_LOCATION",
                    "Location", "location_id", location_id,
                ))
    else:
        audit.warn("locations.parquet not found")

    # --- fragments.parquet → Fragment + 边 ---
    fragments_path = _find_table(run_dir, "fragments.parquet")
    if fragments_path is not None:
        audit.record_source("fragments.parquet")
        building_by_world = {
            n.props["world_id"]: n.key_value
            for n in result.batch.nodes if n.label == "Building"
        }
        for row in read_parquet_rows(fragments_path):
            fragment_id = opt_str(row.get("fragment_id"))
            if fragment_id is None:
                continue
            result.batch.add_node(build_fragment_node(row))
            result.fragment_ids.add(fragment_id)
            building_id = building_by_world.get(opt_str(row.get("world_id")) or "")
            if building_id:
                result.batch.add_edge(EdgeSpec(
                    "Building", "building_id", building_id,
                    "HAS_FRAGMENT",
                    "Fragment", "fragment_id", fragment_id,
                ))
            component_id = opt_str(row.get("component_id"))
            if component_id:
                result.batch.add_edge(EdgeSpec(
                    "Fragment", "fragment_id", fragment_id,
                    "OF_COMPONENT",
                    "Component", "component_id", component_id,
                ))
            location_id = opt_str(row.get("location_id"))
            if location_id:
                result.batch.add_edge(EdgeSpec(
                    "Fragment", "fragment_id", fragment_id,
                    "AT_LOCATION",
                    "Location", "location_id", location_id,
                ))
    else:
        audit.warn("fragments.parquet not found")

    # --- coverage_relations.parquet → CoverageRelation + 边 ---
    coverage_path = _find_table(run_dir, "coverage_relations.parquet")
    if coverage_path is not None:
        audit.record_source("coverage_relations.parquet")
        for row in read_parquet_rows(coverage_path):
            coverage_id = opt_str(row.get("coverage_id"))
            if coverage_id is None:
                continue
            result.batch.add_node(build_coverage_node(row))
            # 上游字段名为 target_fragment_id。
            target_fragment_id = opt_str(row.get("target_fragment_id"))
            if target_fragment_id:
                result.batch.add_edge(EdgeSpec(
                    "Fragment", "fragment_id", target_fragment_id,
                    "HAS_COVERAGE",
                    "CoverageRelation", "coverage_id", coverage_id,
                ))
                result.batch.add_edge(EdgeSpec(
                    "CoverageRelation", "coverage_id", coverage_id,
                    "COVERS_FRAGMENT",
                    "Fragment", "fragment_id", target_fragment_id,
                ))
    else:
        audit.warn("coverage_relations.parquet not found")

    # --- fragment_states.parquet → Driver/Mechanism/Condition/RepairAssessment ---
    fragment_states_path = _find_table(run_dir, "fragment_states.parquet")
    if fragment_states_path is not None:
        audit.record_source("fragment_states.parquet")
        for row in read_parquet_rows(fragment_states_path):
            state_type = opt_str(row.get("state_type"))
            state_id = opt_str(row.get("state_id"))
            if state_type == "condition" and state_id:
                result.condition_ids.add(state_id)
            result.batch.extend(build_fragment_state(row, audit))
    else:
        audit.warn("fragment_states.parquet not found")

    # --- specialized_states.parquet → Drainage/UBW/FireSafety ---
    specialized_path = _find_table(run_dir, "specialized_states.parquet")
    if specialized_path is not None:
        audit.record_source("specialized_states.parquet")
        for row in read_parquet_rows(specialized_path):
            result.batch.extend(build_specialized_state(row, audit))
    else:
        audit.warn("specialized_states.parquet not found")

    # --- measurements.parquet → Measurement + target 边 ---
    measurements_path = _find_table(run_dir, "measurements.parquet")
    if measurements_path is not None:
        audit.record_source("measurements.parquet")
        for row in read_parquet_rows(measurements_path):
            measurement_id = opt_str(row.get("measurement_id"))
            if measurement_id is None:
                continue
            node = build_measurement_node(row)
            target_ref = node.props["target_ref"]
            # §4.2.7：target 解析在 fragment/component/condition id 集合就绪后做。
            target_kind = resolve_target_kind(
                target_ref, result.fragment_ids,
                result.component_ids, result.condition_ids,
            )
            # 改写 target_kind（NodeSpec frozen，重建一个）。
            new_props = dict(node.props)
            new_props["target_kind"] = target_kind
            result.batch.add_node(NodeSpec(
                "Measurement", "measurement_id", measurement_id, new_props
            ))
            edge = measurement_target_edge(measurement_id, target_ref, target_kind)
            if edge is not None:
                result.batch.add_edge(edge)
    else:
        audit.warn("measurements.parquet not found")

    # --- worldgen_world_bundles_meta.parquet（optional）---
    meta_path = _find_table(run_dir, "worldgen_world_bundles_meta.parquet")
    if meta_path is not None:
        audit.record_source("worldgen_world_bundles_meta.parquet")
    else:
        audit.warn("worldgen_world_bundles_meta.parquet not found (optional)")

    return result


def load_fact_kg(
    run_dir: Path,
    client: Any,
    kg_snapshot_id: str,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> FactLoadResult:
    """把 worldgen 事实侧 GraphBatch 写入 Neo4j（spec §4.2）。

    Args:
        run_dir: 灌库输入目录。
        client: `kg.neo4j_client.Neo4jClient` 实例。
        kg_snapshot_id: 快照 id。
        loaded_at: ISO 时间戳。
        audit: 审计记录器。

    Returns:
        FactLoadResult（已写入）。
    """
    from evo_agent_baseline.ingest._graphspec import compile_batch

    result = build_fact_graph(run_dir, kg_snapshot_id, loaded_at, audit)
    client.write_many(compile_batch(result.batch))
    return result


__all__ = [
    "STATE_TYPE_LABEL",
    "SPECIALIZED_STATE_LABEL",
    "DERIVED_OUTCOME_GROUPS",
    "FactLoadResult",
    "build_world_node",
    "build_building_node",
    "build_component_node",
    "build_location_node",
    "build_fragment_node",
    "build_coverage_node",
    "build_fragment_state",
    "build_specialized_state",
    "build_measurement_node",
    "resolve_target_kind",
    "measurement_target_edge",
    "build_fact_graph",
    "load_fact_kg",
]
