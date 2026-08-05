"""Fact KG-RAG 检索器（spec §5.3 + §5.5）。

对指定 building 跑 §5.3 的全部 Cypher 检索，把取回的事实侧节点转换为
`FactAtom` 列表并组装成 `FactPack`。

实现的 spec 章节：
- §5.3.1 ~ §5.3.5 Fact KG-RAG 检索；
- §5.5 FactPack 组装（经 `pack_builder`）。

evo-agent blind：只检索事实侧 label（World/Building/Fragment/.../SidecarEntry），
绝不查 W2 NormativeProjection（spec §2.2.3）；查询库 `kg.queries` 已保证。

设计：检索逻辑（跑查询 + 转 FactAtom）拆成两段——
- `facts_from_*` 纯转换函数：raw 节点 dict 列表 → FactAtom 列表，可单测；
- `retrieve_fact_pack` 编排：Neo4jClient 跑查询 → 调纯转换 → build_fact_pack。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import FactAtom, FactPack
from evo_agent_baseline.kg import queries
from evo_agent_baseline.retrieval.pack_builder import (
    build_fact_pack,
    fact_atom_from_carrier_field,
    fact_atom_from_coverage_relation,
    fact_atom_from_manifestation_flag,
    fact_atom_from_sidecar_entry,
    fact_atoms_from_condition_derived_flags,
    fact_atoms_from_measurement,
)

# 检索侧诊断日志（DEBT-049 Phase3 U6 补遗）：映射段坏 JSON 现为静默退空表——保守语义
# （空表=identity 归一、不改判定）本身正确，但**无可见性**：别名段坏了会让 CCTV 三拼法桥
# 静默失效（drainage_cctv 不再归一成 cctv_survey → performed 不派生 → 卡回落 open），
# 而指标层只看到「卡没闭合」查不到根因。故只加告警、**不改控制流**。
_LOG = logging.getLogger(__name__)


def _warn_mapping_degraded(segment: str, exc: BaseException, building_id: str) -> None:
    """映射段坏 JSON → 记一条告警，**不改控制流**（调用方仍退保守空表）。

    姊妹读径 `rule_retriever.py` 把同类错误戳进 `retrieval_policy`
    （`projection_runtime_mapping_error`）使其可见；`FactPack` 无同类自由元数据位，
    故检索侧走日志。两侧此前**不对称**（闭包侧可见、检索侧全静默），本函数补齐。
    """
    _LOG.warning(
        "projection_runtime_mapping segment %r unusable for building %s "
        "(%s: %s); falling back to empty table — derived facts depending on "
        "this segment will be absent",
        segment, building_id, type(exc).__name__, exc,
    )


# 各承载节点上需要展成 FactAtom 的「事实值」字段（spec §5.5）。
# 主键 / FK / payload_json / world_id 等结构字段不展为 fact。
_BUILDING_FACT_FIELDS = [
    "building_use", "structure_type", "age_years", "storey_count",
    "primary_materials", "configuration_tags", "occupancy_state",
]
_COMPONENT_FACT_FIELDS = [
    "component_type", "material_system", "structural_role",
    "cover_depth_mm", "access_class",
    "length_m", "width_m", "height_m", "visible_area_m2", "thickness_mm",
]
_LOCATION_FACT_FIELDS = [
    "location_class", "exposure_zone", "storey_band", "spatial_tags",
]
_FRAGMENT_FACT_FIELDS = [
    "fragment_role", "fragment_area_m2", "fragment_length_m",
    "in_scope", "exclusion_reason",
]
_DRIVER_FACT_FIELDS = [
    "service_load_ratio", "restraint_level", "moisture_ingress_index",
    "chloride_exposure_index", "carbonation_index",
    "workmanship_deficit_index", "maintenance_deficit_index",
    "drainage_fault_propensity", "alteration_propensity",
    "fire_safety_deficit_index", "repair_quality_index",
]
_MECHANISM_FACT_FIELDS = [
    "mechanism_family", "active", "severity_index",
    "primary_mechanism_id", "crack_mechanism_kind",
    "corrosion_active", "delamination_active",
    "drainage_fault_kind", "ubw_signal_kind",
    "fire_safety_deficiency_kind",
    "assessment_origin_kind", "verification_origin_kind", "cause_tags",
]
_CONDITION_FACT_FIELDS = [
    "condition_class", "severity_band", "severity_index",
    "extent_area_m2", "extent_length_m", "depth_mm", "count",
    "uncertainty_flag", "condition_classes", "source_tags",
]
_REPAIR_FACT_FIELDS = [
    "repair_quality_index", "repair_required", "maintenance_required",
    "verification_failed", "safe_until_next_cycle", "residual_risk_index",
]
_DRAINAGE_FACT_FIELDS = [
    "segment_type", "connection_state", "blockage_index", "leakage_index",
    "misconnection_present", "public_health_risk_index",
]
_UBW_FACT_FIELDS = [
    "alteration_type", "authorization_status_proxy", "present",
    "subdivided_unit_sign_present", "structural_impact_index", "structural_impact",
]
_FIRE_FACT_FIELDS = [
    "fire_component_class", "deficiency_class",
    "deficiency_present", "severity_index",
    "record_status_proxy", "component_deficiency_present",
]


@dataclass
class FactRetrievalRaw:
    """Fact KG-RAG 各查询的原始结果（写图 / 单测中转用）。"""

    world: Dict[str, Any] = field(default_factory=dict)
    building: Dict[str, Any] = field(default_factory=dict)
    fragments: List[Dict[str, Any]] = field(default_factory=list)
    components: List[Dict[str, Any]] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    # DEBT-040：coverage relation 节点 + 所属 fragment_id（键 `_fragment_id`）。
    coverage_relations: List[Dict[str, Any]] = field(default_factory=list)
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    mechanisms: List[Dict[str, Any]] = field(default_factory=list)
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    repair_assessments: List[Dict[str, Any]] = field(default_factory=list)
    drainage_states: List[Dict[str, Any]] = field(default_factory=list)
    ubw_states: List[Dict[str, Any]] = field(default_factory=list)
    fire_safety_states: List[Dict[str, Any]] = field(default_factory=list)
    manifestation_flags: List[Dict[str, Any]] = field(default_factory=list)
    measurements: List[Dict[str, Any]] = field(default_factory=list)
    sidecar_entries: List[Dict[str, Any]] = field(default_factory=list)


def _facts_from_nodes(
    nodes: List[Dict[str, Any]],
    carrier_label: str,
    fact_fields: List[str],
    world_id: str,
    building_id: str,
    source_path: str,
) -> List[FactAtom]:
    """把一组同类承载节点的指定字段展成 FactAtom 列表（spec §5.5）。

    None 值字段跳过（缺失事实不展为 null fact —— verifier 自行判 missing）。

    Args:
        nodes: 承载节点 dict 列表。
        carrier_label: 节点 label。
        fact_fields: 要展为 fact 的字段名列表。
        world_id / building_id: run 标识。
        source_path: 来源表名。

    Returns:
        FactAtom 列表。
    """
    atoms: List[FactAtom] = []
    for node in nodes:
        if not node:
            continue
        for field_name in fact_fields:
            value = node.get(field_name)
            if value is None:
                continue
            atoms.append(fact_atom_from_carrier_field(
                node, carrier_label, world_id, building_id,
                field_name, value, source_path=source_path,
            ))
    return atoms


def facts_from_raw(raw: FactRetrievalRaw) -> List[FactAtom]:
    """把 Fact KG-RAG 原始结果转换为完整 FactAtom 列表（纯函数，可单测）。

    Args:
        raw: FactRetrievalRaw。

    Returns:
        全部 FactAtom（建筑壳 + 子图 + 状态 + 量测 + sidecar + 衍生旗标）。
    """
    world_id = str(raw.world.get("world_id", "")) if raw.world else ""
    building_id = str(raw.building.get("building_id", "")) if raw.building else ""
    atoms: List[FactAtom] = []

    atoms += _facts_from_nodes(
        [raw.building] if raw.building else [], "Building",
        _BUILDING_FACT_FIELDS, world_id, building_id, "buildings.parquet",
    )
    atoms += _facts_from_nodes(
        raw.components, "Component", _COMPONENT_FACT_FIELDS,
        world_id, building_id, "components.parquet",
    )
    atoms += _facts_from_nodes(
        raw.locations, "Location", _LOCATION_FACT_FIELDS,
        world_id, building_id, "locations.parquet",
    )
    atoms += _facts_from_nodes(
        raw.fragments, "Fragment", _FRAGMENT_FACT_FIELDS,
        world_id, building_id, "fragments.parquet",
    )
    atoms += _facts_from_nodes(
        raw.drivers, "DriverState", _DRIVER_FACT_FIELDS,
        world_id, building_id, "fragment_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.mechanisms, "MechanismState", _MECHANISM_FACT_FIELDS,
        world_id, building_id, "fragment_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.conditions, "ConditionState", _CONDITION_FACT_FIELDS,
        world_id, building_id, "fragment_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.repair_assessments, "RepairAssessmentState", _REPAIR_FACT_FIELDS,
        world_id, building_id, "fragment_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.drainage_states, "DrainageState", _DRAINAGE_FACT_FIELDS,
        world_id, building_id, "specialized_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.ubw_states, "UBWState", _UBW_FACT_FIELDS,
        world_id, building_id, "specialized_states.parquet",
    )
    atoms += _facts_from_nodes(
        raw.fire_safety_states, "FireSafetyState", _FIRE_FACT_FIELDS,
        world_id, building_id, "specialized_states.parquet",
    )

    # CoverageRelation → scope.component.* 存在性事实（DEBT-040：声明过的事实源，
    # 此前从未消费；rule_card 裸名经别名表 canonical 到 coverage_relation_type）。
    for cvr in raw.coverage_relations:
        if cvr:
            frag_id = str(cvr.get("_fragment_id", ""))
            atoms.append(fact_atom_from_coverage_relation(
                cvr, frag_id, world_id, building_id,
            ))
            # scope.component.covered 派生事实：语义注册表定义为"covered or otherwise
            # obscured"（现场可及性受限），与 coverage_state=='obscured' 对应
            # （注意词汇反差：coverage_state=='covered' 是"检验覆盖到了"，不是遮盖）。
            if cvr.get("coverage_state") == "obscured":
                covered = fact_atom_from_coverage_relation(
                    cvr, frag_id, world_id, building_id,
                )
                covered.fact_id = f"{covered.fact_id}::covered"
                covered.slot_id = "scope.component.covered"
                covered.source_node_id = covered.fact_id
                atoms.append(covered)

    # ConditionState derived_outcomes 各 *_flags 展为独立 FactAtom（spec §3.3.2）。
    for cond in raw.conditions:
        if cond:
            atoms += fact_atoms_from_condition_derived_flags(cond, world_id, building_id)

    # ConditionState.condition_classes → defect.class.present 派生事实（DEBT-040 ②）：
    # rule_card 触发器按 `defect.class.present` + `defect_class_key` 限定符问"某类缺陷
    # 是否存在"；世界数据的分类就在 condition_classes（DC_* 代码），此处按类各派生一条
    # 存在性事实、qualifiers 带原生 DC_* 值——canonical 翻译交给 enrich（词表对照，
    # 未映射的 DC_* 保持原样、不会误匹配规则词汇）。
    import json as _json
    for cond in raw.conditions:
        if not cond:
            continue
        classes = cond.get("condition_classes")
        if isinstance(classes, str):
            try:
                classes = _json.loads(classes)
            except ValueError:
                classes = [classes]
        if not isinstance(classes, list):
            classes = [cond.get("condition_class")] if cond.get("condition_class") else []
        cond_id = str(cond.get("condition_id", ""))
        for cls in classes:
            if not isinstance(cls, str) or not cls:
                continue
            atoms.append(FactAtom(
                fact_id=f"{cond_id}::defect_class::{cls}",
                world_id=world_id,
                building_id=building_id,
                carrier_type="condition",
                carrier_id=cond_id,
                target_ref=None,
                slot_id="defect.class.present",
                measure_key=None,
                value_json="true",
                value_type="boolean",
                unit=None,
                qualifiers={"defect_class_key": cls},
                confidence_index=None,
                source_path="fragment_states.parquet",
                source_node_id=f"{cond_id}::defect_class::{cls}",
                provenance={"carrier_label": "ConditionState",
                            "derivation": "condition_classes_to_defect_class_present"},
            ))

    # 闭世界负例（DEBT-049 第三波 件A"闭世界总声明"，codex 仲裁修正后通过）：
    # 缺席类逐类派生 defect.class.present=false（与正例对称；限定符经 enrich 补齐
    # component/location/fragment 维度）。主消费字段 = absent_condition_classes
    # （分类全集 − 实际类：W0 按构造完备，未生成即不存在）；老池无此字段时回退
    # generatable_absent_classes（第一波机制可达集口径）。防伪装建模缺口职责在
    # 生成侧 ClassReachabilityAudit 硬审计产物，不再由 eval unknown 承担。
    for cond in raw.conditions:
        if not cond:
            continue
        absent = cond.get("absent_condition_classes")
        if not absent:
            absent = cond.get("generatable_absent_classes")
        if isinstance(absent, str):
            try:
                absent = _json.loads(absent)
            except ValueError:
                absent = []
        if not isinstance(absent, list):
            continue
        cond_id = str(cond.get("condition_id", ""))
        for cls in absent:
            if not isinstance(cls, str) or not cls:
                continue
            atoms.append(FactAtom(
                fact_id=f"{cond_id}::defect_class_absent::{cls}",
                world_id=world_id,
                building_id=building_id,
                carrier_type="condition",
                carrier_id=cond_id,
                target_ref=None,
                slot_id="defect.class.present",
                measure_key=None,
                value_json="false",
                value_type="boolean",
                unit=None,
                qualifiers={"defect_class_key": cls},
                confidence_index=None,
                source_path="fragment_states.parquet",
                source_node_id=f"{cond_id}::defect_class_absent::{cls}",
                provenance={"carrier_label": "ConditionState",
                            "derivation": "closed_world_absent_class"},
            ))

    # ManifestationFlag。
    for flag in raw.manifestation_flags:
        if flag:
            atoms.append(fact_atom_from_manifestation_flag(flag, world_id, building_id))

    # Measurement 1:1。
    for msr in raw.measurements:
        if msr:
            atoms.append(fact_atoms_from_measurement(msr, world_id, building_id))

    # SidecarEntry 1:1。
    for entry in raw.sidecar_entries:
        if entry:
            atom = fact_atom_from_sidecar_entry(entry, world_id, building_id)
            atoms.append(atom)
            # EXP-011 设计①：角色枚举 → 按角色等级各派生一条布尔指派事实（双极）。
            # role==该级 → true；否则（含 none）→ false——"未指派"是可求值的否定事实，
            # 让触发器判 false → 卡 not_applicable，而非"查无"永久 open。
            # 角色域镜像自 registry 枚举 enum_values 的非 none 部分（单一来源注记）。
            if atom.slot_id == "actor.representative.assigned_role":
                try:
                    role = _json.loads(atom.value_json)
                except ValueError:
                    role = None
                if isinstance(role, str) and role:
                    for level in ("ri_rep_lvl1", "ri_rep_lvl2"):
                        atoms.append(atom.model_copy(update={
                            "fact_id": f"{atom.fact_id}::assigned::{level}",
                            "slot_id": "actor.representative.assigned",
                            "measure_key": None,
                            "value_json": "true" if role == level else "false",
                            "value_type": "boolean",
                            "qualifiers": {**atom.qualifiers, "actor_role_key": level},
                            "source_node_id": f"{atom.fact_id}::assigned::{level}",
                        }))

    return atoms


# 本检索涉及的源表（FactPack.source_tables）。
_FACT_SOURCE_TABLES = [
    "buildings.parquet", "fragments.parquet", "components.parquet",
    "locations.parquet", "coverage_relations.parquet",
    "fragment_states.parquet", "specialized_states.parquet",
    "measurements.parquet", "sidecar_records.parquet", "sidecar_entries.parquet",
]


def retrieve_fact_raw(client: Any, building_id: str) -> FactRetrievalRaw:
    """对指定 building 跑 §5.3 全部 Cypher，收集原始结果。

    Args:
        client: `kg.neo4j_client.Neo4jClient` 实例。
        building_id: 目标建筑 id。

    Returns:
        FactRetrievalRaw。
    """
    raw = FactRetrievalRaw()
    params = queries.building_params(building_id)

    # §5.3.1 building shell。
    shell = client.read(queries.FACT_BUILDING_SHELL, params)
    if shell:
        raw.world = shell[0].get("world") or {}
        raw.building = shell[0].get("building") or {}

    # §5.3.2 fragment / component / location 子图。
    for row in client.read(queries.FACT_FRAGMENT_SUBGRAPH, params):
        if row.get("fragment"):
            raw.fragments.append(row["fragment"])
        if row.get("component"):
            raw.components.append(row["component"])
        if row.get("location"):
            raw.locations.append(row["location"])

    # §5.3.2 补：coverage relations（DEBT-040：此前声明未消费）。
    for row in client.read(queries.FACT_COVERAGE_RELATIONS, params):
        node = row.get("coverage_relation")
        if node:
            entry = dict(node)
            entry["_fragment_id"] = row.get("fragment_id") or ""
            raw.coverage_relations.append(entry)

    # §5.3.3 conditions / states。
    for row in client.read(queries.FACT_CONDITIONS_STATES, params):
        raw.drivers.extend(row.get("drivers") or [])
        raw.mechanisms.extend(row.get("mechanisms") or [])
        raw.conditions.extend(row.get("conditions") or [])
        raw.repair_assessments.extend(row.get("repair_assessments") or [])

    # §3.3.3 专项状态。
    for row in client.read(queries.FACT_SPECIALIZED_STATES, params):
        raw.drainage_states.extend(row.get("drainage_states") or [])
        raw.ubw_states.extend(row.get("ubw_states") or [])
        raw.fire_safety_states.extend(row.get("fire_safety_states") or [])

    # §3.3.2 ManifestationFlag。
    for row in client.read(queries.FACT_MANIFESTATION_FLAGS, params):
        raw.manifestation_flags.extend(row.get("manifestation_flags") or [])

    # §5.3.4 measurements（fragment / component / condition 三级）。
    for query in (
        queries.FACT_FRAGMENT_MEASUREMENTS,
        queries.FACT_COMPONENT_MEASUREMENTS,
        queries.FACT_CONDITION_MEASUREMENTS,
    ):
        for row in client.read(query, params):
            raw.measurements.extend(row.get("measurements") or [])

    # §5.3.5 sidecar entries。
    for row in client.read(queries.FACT_SIDECAR_ENTRIES, params):
        if row.get("sidecar_entry"):
            raw.sidecar_entries.append(row["sidecar_entry"])

    return raw


def _dedupe_measurements(raw: FactRetrievalRaw) -> None:
    """measurements 三级查询可能重复取同一 Measurement，按 measurement_id 去重。"""
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for msr in raw.measurements:
        mid = msr.get("measurement_id") if msr else None
        if mid is None or mid in seen:
            continue
        seen.add(mid)
        unique.append(msr)
    raw.measurements = unique


def enrich_qualifiers_from_structure(
    atoms: List[FactAtom],
    raw: FactRetrievalRaw,
    qualifier_value_aliases: Dict[str, Any],
) -> List[FactAtom]:
    """按世界结构给事实充实规范限定符（DEBT-040 ②，纯函数可单测）。

    触发器按 `component_type_key` / `location_class_key` 过滤事实，而事实原本无标签
    （限定符只有 fragment_id / carrier_domain 等）。本函数经 Fragment→Component/
    Location 结构取 W0 原生值（`component_type` / `location_class`），再经
    `qualifier_value_aliases`（W0 词汇→controlled_vocabularies 规范值，来自
    projection_runtime_mapping）转换后写入 qualifiers。

    保守规则：无对照的原生值不写（宁缺勿错）；已有该键的事实不覆盖；只补有
    fragment 归属（qualifiers.fragment_id 或 carrier_type=fragment）的事实。
    """
    comp_type = {
        c.get("component_id"): c.get("component_type") for c in raw.components if c
    }
    loc_class = {
        l.get("location_id"): l.get("location_class") for l in raw.locations if l
    }
    frag_info: Dict[str, tuple] = {}
    for f in raw.fragments:
        if f and f.get("fragment_id"):
            frag_info[f["fragment_id"]] = (
                comp_type.get(f.get("component_id")),
                loc_class.get(f.get("location_id")),
                f.get("component_id"),  # P1-1:身份来源证明(原始 Fragment→Component 的 component_id)
            )
    # 载体→fragment 反查：condition/driver/mechanism/repair_assessment/measurement/
    # 旗标载体的事实（qualifiers 无 fragment_id）经节点自身的 fragment_id 属性归属。
    carrier_frag: Dict[str, str] = {}
    for nodes, id_key in (
        (raw.conditions, "condition_id"),
        (raw.drivers, "driver_id"),
        (raw.mechanisms, "mechanism_state_id"),
        (raw.repair_assessments, "repair_assessment_id"),
        (raw.measurements, "measurement_id"),
        (raw.manifestation_flags, "manifestation_flag_id"),
    ):
        for n in nodes:
            if n and n.get(id_key) and n.get("fragment_id"):
                carrier_frag[str(n[id_key])] = str(n["fragment_id"])

    ct_alias = (qualifier_value_aliases or {}).get("component_type_key") or {}
    lc_alias = (qualifier_value_aliases or {}).get("location_class_key") or {}
    for atom in atoms:
        frag_id = atom.qualifiers.get("fragment_id") or (
            atom.carrier_id if atom.carrier_type == "fragment" else None
        ) or carrier_frag.get(str(atom.carrier_id or ""))
        info = frag_info.get(frag_id) if frag_id else None
        if not info:
            continue
        # fragment 归属戳（spec 草案·义务 fragment 级派生）：可解析出 fragment 的事实
        # 统一盖 qualifiers.fragment_id，闭包按它做 fragment 作用域过滤。
        if "fragment_id" not in atom.qualifiers and isinstance(frag_id, str) and frag_id:
            atom.qualifiers["fragment_id"] = frag_id
        raw_ct, raw_lc = info[0], info[1]
        if "component_type_key" not in atom.qualifiers and isinstance(raw_ct, str):
            canon = ct_alias.get(raw_ct)
            if isinstance(canon, str) and canon:
                atom.qualifiers["component_type_key"] = canon
        if "location_class_key" not in atom.qualifiers and isinstance(raw_lc, str):
            canon = lc_alias.get(raw_lc)
            if isinstance(canon, str) and canon:
                atom.qualifiers["location_class_key"] = canon

    # 已带原生值的限定符按词表翻译成规范值（如 defect_class_key 的 DC_CRACK→crack）；
    # 词表没有的键/值保持原样（不会误匹配规则词汇）。
    for atom in atoms:
        for qkey, amap in (qualifier_value_aliases or {}).items():
            if not isinstance(amap, dict) or qkey.startswith("_"):
                continue
            cur = atom.qualifiers.get(qkey)
            if isinstance(cur, str):
                canon = amap.get(cur)
                if isinstance(canon, str) and canon:
                    atom.qualifiers[qkey] = canon

    # P1-1(§3.0 专用身份通道):从原始 Fragment→Component 关系(frag_info)生成专用
    # w0_component_identity 原子,每 fragment 一个(count==1 天然——frag_info 每 fragment 单
    # component_id)。validator 只认此通道判组件身份(不扫一般事实 qualifier、不 set 折叠多来源),
    # 消除复审 P1-1 的伪造/多来源折叠红线。真实数据有效:frag_info 来自 raw.fragments。
    if atoms:
        _wid, _bid = atoms[0].world_id, atoms[0].building_id
        for _frag_id, _finfo in frag_info.items():
            _raw_ct = _finfo[0]
            if not isinstance(_raw_ct, str):
                continue
            _canon = ct_alias.get(_raw_ct)
            if not (isinstance(_canon, str) and _canon):
                continue
            atoms.append(FactAtom(
                fact_id=f"w0id::{_frag_id}",
                world_id=_wid,
                building_id=_bid,
                carrier_type="fragment",
                carrier_id=_frag_id,
                target_ref=None,
                slot_id="w0_component_identity",
                measure_key=None,
                value_json=json.dumps(_canon),
                value_type="string",
                unit=None,
                qualifiers={
                    "fragment_id": _frag_id,
                    "component_id": _finfo[2] if len(_finfo) > 2 else None,
                    "canonical_component_type": _canon,
                },
                confidence_index=None,
                source_path="fragment_component_projection",
                source_node_id=f"w0id::{_frag_id}",
                provenance={
                    "channel": "w0_component_identity",
                    "derivation": "fragment_component_projection",
                },
            ))
    return atoms


# slot_targets 回退绑定表（第十例"登记了没接线"修复，2026-07-08）：
# projection_runtime_mapping_v1.slot_targets 声明 reporting.artifact.prepared 由四个
# sidecar 接口 any_of 供证，但该段从无消费者。表值 = 四接口（inspection_report/
# completion_report/procedure_gate/supervision）在 W0 接口 schema 的 artifact 类
# target_slot_ids 并集（分层单向禁 import workflow_engine，故落常量、注明双源；
# 接口 schema 变更时须同步）。语义：任一报告类证物在 → 已准备（双极）。
_SLOT_TARGET_FALLBACKS: Dict[str, List[str]] = {
    "reporting.artifact.prepared": [
        "artifact.form.mbi3_or_mbi3a",
        "artifact.form.mbi4",
        "artifact.photo.annotated",
        "artifact.plan.annotated",
        "artifact.proposal.repair",
        "artifact.record.inspection_log",
        "artifact.record.nonconformity_sp2",
        "artifact.record.supervision_log_sp1",
        "artifact.record.test_or_material_witness",
        "artifact.report.completion",
        "artifact.report.inspection",
        "artifact.statement.scope_and_order_coverage",
    ],
}


def _assert_slot_target_fallback_members_are_artifact_slots() -> None:
    """第三锚结构性前提：回退表成员必须全是产物齐备槽。

    闭包侧 `is_artifact_state_fact` 认 `derivation=slot_target_fallback` 为产物齐备布尔，
    **不**按目标槽名白名单。若有人往表里塞非产物成员，派生事实会被误认 ——
    故在生产者侧锁死「成员 ⊆ W0_09_ARTIFACT_SLOTS」。延迟导入避免循环依赖。
    """
    # 🔴 2026-07-27 终审 P2：原从 `closure.obligation_deriver` 取，构成
    # `retrieval → closure` 反向依赖，违反规格 v0.4:4739（只允许闭包层消费检索数据对象）。
    # 延迟 import **不改变分层关系**。改从中立纯数据层取（权威源已移至那里）。
    from evo_agent_baseline.rulecard_assets import W0_09_ARTIFACT_SLOTS

    for target, members in _SLOT_TARGET_FALLBACKS.items():
        bad = set(members) - W0_09_ARTIFACT_SLOTS
        if bad:
            raise AssertionError(
                f"_SLOT_TARGET_FALLBACKS[{target!r}] 含非产物槽 {sorted(bad)}；"
                "第三锚认 derivation=slot_target_fallback，成员必须 ⊆ W0_09_ARTIFACT_SLOTS"
            )


def infer_method_class_for_verification_flags(
    atoms: List[FactAtom],
) -> None:
    """verification.test.failed 补 method_class 维度（spec 草案·第一波 §4，原地改）。

    W0 的 fail 旗标是融合旗标不分方法；卡端按 method_key 限定。推断规则（宁缺勿错）：
    同 carrier 共存的测量事实 method_class **唯一**时才补，歧义/缺失不补。
    """
    by_carrier: Dict[str, set] = {}
    for f in atoms:
        mc = f.qualifiers.get("method_class")
        if isinstance(mc, str) and mc and f.carrier_id:
            by_carrier.setdefault(str(f.carrier_id), set()).add(mc)
    for f in atoms:
        if f.slot_id != "verification.test.failed":
            continue
        if "method_class" in f.qualifiers:
            continue
        methods = by_carrier.get(str(f.carrier_id or ""), set())
        if len(methods) == 1:
            f.qualifiers["method_class"] = next(iter(methods))


def derive_slot_target_fallback_facts(
    facts: List[FactAtom],
    world_id: str,
    building_id: str,
) -> List[FactAtom]:
    """slot_targets 回退派生（纯函数可单测）：按 fragment 出双极事实。

    对 _SLOT_TARGET_FALLBACKS 每个目标槽：某 fragment 的成员槽事实里任一值为
    true → 目标槽 true；有成员事实但全非 true → false（封闭世界）；该 fragment
    无任何成员事实 → 不出事实（维持 missing 诚实缺量）。
    """
    _assert_slot_target_fallback_members_are_artifact_slots()
    by_frag: Dict[str, Dict[str, List[FactAtom]]] = {}
    for f in facts:
        frag = f.qualifiers.get("fragment_id")
        if not isinstance(frag, str) or not frag:
            continue
        by_frag.setdefault(frag, {}).setdefault(str(f.slot_id or ""), []).append(f)

    def _atom(fact_id: str, target: str, hit: bool, carrier_type: str,
              carrier_id: str, qualifiers: Dict[str, Any]) -> FactAtom:
        return FactAtom(
            fact_id=fact_id,
            world_id=world_id,
            building_id=building_id,
            carrier_type=carrier_type,  # type: ignore[arg-type]
            carrier_id=carrier_id,
            target_ref=None,
            slot_id=target,
            measure_key=None,
            value_json="true" if hit else "false",
            value_type="boolean",
            unit=None,
            qualifiers=qualifiers,
            confidence_index=None,
            source_path="sidecar_entries.parquet",
            source_node_id=fact_id,
            provenance={
                "carrier_label": "Fragment" if carrier_type == "fragment" else "Building",
                "derivation": "slot_target_fallback",
            },
        )

    # 三层发射（v11 修正：无限定符消费端撞 12 条逐键行判歧义）：
    # ① fragment 逐键行（部位卡按 artifact_key 精确取）；
    # ② 楼级逐键聚合行（楼级卡按 artifact_key 取；any_true 跨部位，标 aggregation
    #    走 building 载体 rank 3，压过 fragment 行不混绑）；
    # ③ 楼级无键联合行（无限定符楼级消费端唯一读数；aggregation 标记使其被
    #    fragment 作用域排除，不污染部位卡）。
    out: List[FactAtom] = []
    for target, members in _SLOT_TARGET_FALLBACKS.items():
        member_set = set(members)
        key_hits: Dict[str, List[bool]] = {}
        any_hit = False
        seen_any = False
        for frag, slots in sorted(by_frag.items()):
            for sid in sorted(member_set & set(slots)):
                member_facts = slots[sid]
                hit = any(
                    json.loads(f.value_json) is True
                    for f in member_facts
                    if f.value_json
                )
                artifact_key = (
                    sid[len("artifact."):] if sid.startswith("artifact.") else sid
                )
                seen_any = True
                any_hit = any_hit or hit
                key_hits.setdefault(artifact_key, []).append(hit)
                out.append(_atom(
                    f"{frag}::slot_target::{target}::{artifact_key}",
                    target, hit, "fragment", frag,
                    {"fragment_id": frag, "artifact_key": artifact_key},
                ))
        for artifact_key, hits in sorted(key_hits.items()):
            out.append(_atom(
                f"{building_id}::slot_target::{target}::{artifact_key}",
                target, any(hits), "building", building_id,
                {"artifact_key": artifact_key, "aggregation": "building"},
            ))
        if seen_any:
            out.append(_atom(
                f"{building_id}::slot_target::{target}",
                target, any_hit, "building", building_id,
                {"aggregation": "building"},
            ))
    return out


# ---------------------------------------------------------------------------
# slot_targets.lookup_rule 通用派生（"登记了从没接线"修复，2026-07-27）
#
# 卡包 projection_runtime_mapping_v1.json 的 slot_targets 段共 27 条登记，其中 5 条
# 带 lookup_rule。本实现【只消费 lookup_rule】；【未消费 owning_interfaces /
# owning_interface_mode】——后者（如 procedure.investigation.detailed.started 的
# all_of 双接口供证）语义比 lookup_rule 更严，两者关系规格里没说清，待裁定。
#
# lookup_rule 求值语义来源（非猜测）：归档 MVP
# agent_mvp_已归档/src/workflow_engine/regulation_projection_executor.py 的
# _lookup_via_rule——"被请求的限定符"= 卡侧 slot_ref 的 qualifiers（归档实现
# requested_qualifiers = target.get("qualifiers")）。两点有意偏离，均偏保守：
# ① 形态二 containment 未命中时【不出事实】而非判 false——当前世界 qual.actor_role
#    词表（registered_inspector 等行为者类）与卡侧被请求词表（ri_rep_lvl1/lvl2
#    代表等级）不交，无法区分"角色确缺席"与"世界词表不含所请键"，宁缺勿错；
# ② 形态二子句在被请求限定符值缺失时【目标槽整体跳过】，不做归档的 vacuous 通过
#   （生产侧无卡侧请求上下文，防"任一 qual.actor_role 事实在即算角色合格"假阳性）。
# 未登记的 mode / qualifiers_mode / value_mode 取值一律 ValueError，不静默当 ignore。
# ---------------------------------------------------------------------------


def _parsed_json_value(value_json: Any) -> Any:
    try:
        return json.loads(value_json)
    except (TypeError, ValueError):
        return None


def _as_value_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def harvest_slot_target_requested_qualifiers(
    rule_cards_doc: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """从规则卡文档采集各槽的"被请求限定符"组合（形态二求值的输入，纯函数）。

    遍历每张卡的 slot_ref（同时带 slot_ref_id 与 slot_id 的 dict），按 slot_id
    归集其 qualifiers 组合并去重，顺序确定（按 JSON 排序）。"被请求的"即卡侧
    义务节点声明的限定符——与归档 _lookup_via_rule 的 requested_qualifiers 同源。
    """
    combos: Dict[str, set] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            slot_id = node.get("slot_id")
            if isinstance(slot_id, str) and "slot_ref_id" in node:
                quals = node.get("qualifiers")
                quals = quals if isinstance(quals, dict) else {}
                key = json.dumps(quals, ensure_ascii=False, sort_keys=True)
                combos.setdefault(slot_id, set()).add(key)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    cards = rule_cards_doc.get("cards") if isinstance(rule_cards_doc, dict) else None
    for card in cards or []:
        _walk(card)
    return {
        slot: [json.loads(k) for k in sorted(keys)]
        for slot, keys in sorted(combos.items())
    }



def _slot_aliases_for_lookup_rule(client: Any, building_id: str) -> Dict[str, Any]:
    """取 `slot_aliases`（卡侧名→世界侧名），供 lookup_rule 派生两侧同口径比较。

    **复用** `RULE_PROJECTION_RUNTIME_MAPPING`（DEBT-040 已建的别名运输查询），
    不新造第二条——保证与闭包侧 `canonical_slot` 读的是**同一条运输链、同一张表**。
    读不到就返回空表 ⇒ `_canon_slot` 退化为恒等 ⇒ **行为与修复前一致**，
    不会因为取不到别名而少派生或多派生（诚实降级，非 fail-open 判定）。
    """
    try:
        rows = client.read(queries.RULE_PROJECTION_RUNTIME_MAPPING)
        if rows:
            parsed = json.loads(rows[0].get("slot_aliases_json") or "{}")
            if isinstance(parsed, dict):
                return parsed
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        _warn_mapping_degraded("slot_aliases", exc, building_id)
    return {}

def derive_slot_target_lookup_rule_facts(
    facts: List[FactAtom],
    slot_targets: Dict[str, Any],
    requested_qualifiers: Dict[str, List[Dict[str, Any]]],
    world_id: str,
    building_id: str,
    slot_aliases: Optional[Dict[str, Any]] = None,
) -> List[FactAtom]:
    """slot_targets.lookup_rule 通用楼级派生（纯函数可单测）。

    对 slot_targets 中每个带 lookup_rule 的目标槽、每个被请求限定符组合
    （requested_qualifiers 缺该槽时退化为单无限定符组合）：

    - 直接事实优先：目标槽已有 qualifiers 涵盖该组合的事实 → 跳过（归档
      _resolve_target_facts 的 direct-wins）；
    - mode=all_of 完整合取（【绝不简化成单项别名】）：全部子句满足 → 派生 true；
      全部子句可判但未全满足 → 派生 false（封闭世界双极）；任一子句不可判
      （槽整体无事实，或形态二 containment 未命中）→ 不出事实（诚实缺量）；
    - 子句形态一（qualifiers_mode=ignore、无 value_mode）：该槽任一显式 true 即满足，
      该槽有事实即可判；
    - 子句形态二（value_mode=contains_requested_qualifier）：子句槽存在事实、其
      值列表包含被请求限定符键的全部值即满足；未命中不可判（偏离归档，见文件头
      注）；组合里没有被请求限定符键 → 该组合跳过（生产侧传空 map ⇒ 形态二
      目标槽整体不派生）。

    派生事实为楼级行（carrier=building + aggregation=building 标记 + 组合限定符），
    provenance.derivation="slot_target_lookup_rule"。

    ⚠️ **别名归一在当前数据下是空操作（2026-07-27 agy 独立复核实测）**：
    带 `lookup_rule` 的 5 个目标槽及其子句 `slot_id`，与 `slot_aliases` 的键**交集为空**；
    而**是**别名表键的那 10 个 `slot_targets` 条目**全都没有 `lookup_rule`**、
    在 `if rule is None: continue` 处就跳出了。
    ⇒ 归一三处（去重 / 子句收集 / 派生结果 `slot_id`）当前全部退化为恒等。
    **保留归一是为口径一致**，不是为当下的行为——别把它读成"正在生效的修复"。
    🔴 codex 审核门原判「10 个键恒不命中导致重复派生」**不成立**（它们走不到那两处比较）；
    若确实想让这 10 个可派生，**要查的是卡包为何没给它们配 `lookup_rule`**，不是比较语义。
    """
    out: List[FactAtom] = []
    # 卡侧名 → 世界侧规范名（两侧同口径比较；缺表则退化为恒等，不改行为）。
    from evo_agent_baseline.slot_alias_policy import slot_aliases_from_policy

    # 🔴 codex 二审 P2（实测坐实）：`slot_aliases_from_policy` 收的是
    # **`retrieval_policy` 那层包裹结构**（读 `policy["slot_aliases"]` 与
    # `policy["projection_runtime_mapping_v1"]["slot_aliases"]`），而这里拿到的是
    # **裸别名表**。直接喂 → 实测 15 条变 **0 条** ⇒ `_alias` 恒空 ⇒ 归一恒等
    # ⇒ **整个修复静默失效**。故须包一层。
    # ⚠️ 这正是本项目反复吃亏的形状：接口两侧形状不一致，且**不报错、只是恒空**。
    _alias = slot_aliases_from_policy({"slot_aliases": slot_aliases or {}})

    def _canon_slot(name: str) -> str:
        return _alias.get(name, name)

    for target in sorted(slot_targets):
        if target.startswith("_"):
            continue
        entry = slot_targets[target]
        if not isinstance(entry, dict):
            continue
        rule = entry.get("lookup_rule")
        if rule is None:
            continue  # 27 条里 22 条只有 owning_interfaces、无推导规则——无事可做
        if not isinstance(rule, dict) or rule.get("mode") != "all_of":
            raise ValueError(
                f"slot_targets[{target}].lookup_rule 未登记的 mode: "
                f"{rule.get('mode') if isinstance(rule, dict) else rule!r}"
            )
        clauses = rule.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(
                f"slot_targets[{target}].lookup_rule.clauses 缺失或为空"
            )
        for clause in clauses:
            if not isinstance(clause, dict) or not clause.get("slot_id"):
                raise ValueError(
                    f"slot_targets[{target}] 子句缺 slot_id: {clause!r}"
                )
            qmode = clause.get("qualifiers_mode", "ignore")
            if qmode != "ignore":
                raise ValueError(
                    f"slot_targets[{target}] 未登记的 qualifiers_mode: {qmode!r}"
                )
            vmode = clause.get("value_mode")
            if vmode is not None and vmode != "contains_requested_qualifier":
                raise ValueError(
                    f"slot_targets[{target}] 未登记的 value_mode: {vmode!r}"
                )

        combos = requested_qualifiers.get(target) or [{}]
        for combo in combos:
            if not isinstance(combo, dict):
                continue
            # 形态二子句需要组合里带被请求限定符键，否则该组合无法求值（跳过）。
            if any(
                c.get("value_mode") == "contains_requested_qualifier"
                and not _as_value_list(combo.get(c.get("requested_qualifier_key")))
                for c in clauses
            ):
                continue
            # 直接事实优先（qualifiers 涵盖组合即命中）。
            # 🔴 2026-07-27 codex 审核门 P1：此处与下面子句收集处原本都是**裸比**
            # （`f.slot_id == target`），而 `target` / `clause["slot_id"]` 是**卡侧名**、
            # `f.slot_id` 是**世界侧名**。27 个 slot_targets 键里 **10 个正是别名表的键**
            # （`repair.prescribed.{started,completed}` / `procedure.appointment.completed`
            # / `reporting.*` 等）⇒ 去重检查对这 10 个**恒不命中**（重复派生），
            # 子句收集则**把合法事实当作缺失而跳过派生**（后者更糟：少产事实）。
            # 修法：两侧同口径——都归一到世界侧规范名再比。
            # ⚠️ 教训在先：同日「半边归一比不归一更糟」已实证一次
            # （只归一查询侧使 `scope.component.inspection_included` 26→0）。
            if any(
                _canon_slot(f.slot_id) == _canon_slot(target)
                and all(f.qualifiers.get(k) == v for k, v in combo.items())
                for f in facts
            ):
                continue
            clause_states: List[tuple] = []  # (satisfied, decidable)
            for clause in clauses:
                _cslot = _canon_slot(clause["slot_id"])
                cfacts = [f for f in facts if _canon_slot(f.slot_id) == _cslot]
                if clause.get("value_mode") == "contains_requested_qualifier":
                    requested_values = _as_value_list(
                        combo.get(clause["requested_qualifier_key"]))
                    satisfied = any(
                        all(
                            v in _as_value_list(_parsed_json_value(f.value_json))
                            for v in requested_values
                        )
                        for f in cfacts
                    )
                    # containment 未命中不可判（词表缺口与真缺席不可分），宁缺勿错。
                    clause_states.append((satisfied, satisfied))
                else:
                    satisfied = any(
                        _parsed_json_value(f.value_json) is True for f in cfacts
                    )
                    clause_states.append((satisfied, bool(cfacts)))
            if all(s for s, _ in clause_states):
                hit: Optional[bool] = True
            elif all(d for _, d in clause_states):
                hit = False
            else:
                hit = None
            if hit is None:
                continue
            suffix = "" if not combo else "::" + ",".join(
                f"{k}={v}" for k, v in sorted(combo.items()))
            fact_id = f"{building_id}::slot_target_lookup::{target}{suffix}"
            out.append(FactAtom(
                fact_id=fact_id,
                world_id=world_id,
                building_id=building_id,
                carrier_type="building",
                carrier_id=building_id,
                target_ref=None,
                # 🔴 第三处不对称（2026-07-27 agy 独立复核挖出，codex 那条 P1 没提）：
                # 前两处修的是「读」的口径，这里是「写」的口径。若派生结果仍以**卡侧名**
                # 落 slot_id，而去重/子句收集已归一到世界侧名，三者口径就不一致；
                # 下游闭包若按世界侧名查，这条派生事实**查不到**。
                # 当前数据下三处都退化为恒等（见函数头注释），但口径必须一致，
                # 否则等哪天某个带 lookup_rule 的键进了别名表，这是最难查的一处。
                slot_id=_canon_slot(target),
                measure_key=None,
                value_json="true" if hit else "false",
                value_type="boolean",
                unit=None,
                qualifiers={**combo, "aggregation": "building"},
                confidence_index=None,
                source_path="sidecar_entries.parquet",
                source_node_id=fact_id,
                provenance={
                    "carrier_label": "Building",
                    "derivation": "slot_target_lookup_rule",
                    "slot_target": target,
                },
            ))
    return out


def derive_combination_bridge_facts(
    raw: FactRetrievalRaw,
    bridges: List[Dict[str, Any]],
    qualifier_value_aliases: Dict[str, Any],
    world_id: str,
    building_id: str,
) -> List[FactAtom]:
    """缺陷类组合桥双极派生（spec 草案·缺陷类组合桥 2026-07-08 定稿，纯函数可单测）。

    每座桥定义：成员缺陷类（W0 原生 DC_* 码）∧ 组件类（规则卡端词表值）→ 目标
    缺陷类（规则卡端词表值）。按 fragment 求值：该 fragment 的组件类在桥的
    component_classes 内时，检查其 condition 是否含任一成员类，命中出 true、
    未命中出 false（双极——W0 生成世界封闭，缺席=真缺席，"无迹象"可判触发假）；
    组件类不在桥内的 fragment 不出事实（如外墙裂缝不入 structural_damage_sign，
    防直桥误伤）。目标值是规则卡端词表值，后续别名翻译不再碰它（别名表键是
    W0 词汇）。
    """
    if not bridges:
        return []
    comp_type = {
        c.get("component_id"): c.get("component_type") for c in raw.components if c
    }
    ct_alias = (qualifier_value_aliases or {}).get("component_type_key") or {}
    # fragment → (规范组件类, 该 fragment 的缺陷类集合)
    frag_class: Dict[str, str] = {}
    for f in raw.fragments:
        if not f or not f.get("fragment_id"):
            continue
        raw_ct = comp_type.get(f.get("component_id"))
        canon = ct_alias.get(raw_ct) if isinstance(raw_ct, str) else None
        if isinstance(canon, str) and canon:
            frag_class[str(f["fragment_id"])] = canon
    frag_defects: Dict[str, set] = {}
    for cond in raw.conditions:
        if not cond or not cond.get("fragment_id"):
            continue
        classes = cond.get("condition_classes")
        if isinstance(classes, str):
            try:
                classes = json.loads(classes)
            except ValueError:
                classes = [classes]
        if not isinstance(classes, list):
            classes = [cond.get("condition_class")] if cond.get("condition_class") else []
        bucket = frag_defects.setdefault(str(cond["fragment_id"]), set())
        bucket.update(c for c in classes if isinstance(c, str) and c)

    atoms: List[FactAtom] = []
    for bridge in bridges:
        target = bridge.get("target_defect_class_key")
        members = {
            m for m in (bridge.get("member_condition_classes") or [])
            if isinstance(m, str)
        }
        comp_classes = {
            c for c in (bridge.get("component_classes") or [])
            if isinstance(c, str)
        }
        bipolar = bool(bridge.get("bipolar", True))
        if not isinstance(target, str) or not target or not members or not comp_classes:
            continue
        for frag_id in sorted(frag_class):
            if frag_class[frag_id] not in comp_classes:
                continue
            hit = bool(frag_defects.get(frag_id, set()) & members)
            if not hit and not bipolar:
                continue
            atoms.append(FactAtom(
                fact_id=f"{frag_id}::bridge::{target}",
                world_id=world_id,
                building_id=building_id,
                carrier_type="fragment",
                carrier_id=frag_id,
                target_ref=None,
                slot_id="defect.class.present",
                measure_key=None,
                value_json="true" if hit else "false",
                value_type="boolean",
                unit=None,
                qualifiers={
                    "defect_class_key": target,
                    "fragment_id": frag_id,
                    "component_type_key": frag_class[frag_id],
                },
                confidence_index=None,
                source_path="fragment_states.parquet",
                source_node_id=f"{frag_id}::bridge::{target}",
                provenance={
                    "carrier_label": "Fragment",
                    "derivation": "defect_class_combination_bridge",
                },
            ))
    return atoms


def derive_risk_slot_facts(
    facts: List[FactAtom],
    risk_slot_derivations: Dict[str, Any],
) -> List[FactAtom]:
    """风险槽语义桥派生（DEBT-049 第四波件甲 A1'，codex 修正后实施）。

    W0 旗标（如 `fire_safety.deficiency.present`）系 spec 06 §11 三态：布尔值
    OR 字符串 `not_applicable` + 同槽 fallback 原因行（`no_fire_component` 等），
    同 fragment 同槽双脏串行。裸 slot_aliases 词桥会把卡接到脏值域撞 blocked/
    ambiguous。故只从**布尔源行**深拷贝派生干净目标槽行（值恒等源行、限定符
    全继承，含 enrich 补的 component_type_key/location/fragment 戳）；字符串态
    不派生——非消防 fragment 由触发器结构不可满足 NA（DEBT-050）兜住，语义
    同构 spec 06 §11 的 not_applicable。**语义收窄（codex a 项）**：本桥是 W0
    建模定义域内的低置信操作性桥，false 只表'无已建模消防组件缺陷'，不覆盖
    CoP 3.5.2(E)/(F) 违法改动/用途改变面（W0 未建模，挂账下波）。
    """
    if not isinstance(risk_slot_derivations, dict) or not risk_slot_derivations:
        return []
    table = {k: v for k, v in risk_slot_derivations.items()
             if isinstance(v, str) and v and not str(k).startswith("_")}
    # target_slot → source_slot（映射方向：卡端消费槽 → W0 事实端源槽）
    out: List[FactAtom] = []
    for a in facts:
        for target_slot, source_slot in table.items():
            if a.slot_id != source_slot or a.value_type != "boolean":
                continue
            out.append(a.model_copy(update={
                "fact_id": f"{a.fact_id}::risk_bridge::{target_slot}",
                "slot_id": target_slot,
                "source_node_id": f"{a.source_node_id}::risk_bridge::{target_slot}",
                "provenance": {**(a.provenance or {}),
                               "derivation": "risk_slot_semantic_bridge"},
            }))
    return out


# DEBT-049 C1（codex CoP 裁定 附录七 §4 参考文件 / §6 检验结果）：RI 检验报告恒有的
# 章节（field group）——固定报告结构契约（同 slot_target fallback 性质，非世界依赖）。
# 派生"章节存在"事实（qual.artifact_field_group），不伪造章节内容（具体缺陷/测试/文件
# 仍来自 W0/W1 事实——codex 风险提示）。只列 CoP 附录七 inspection report 明列章节。
_REPORT_INSPECTION_FIELD_GROUPS: List[str] = [
    "cover_page",                 # 附录七 §1
    "building_information",        # 附录七 §2/§3
    "representative_particulars",  # 附录七 §2：RI 详情
    "reference_documents",        # 附录七 §4：经 RI 检视的文件清单
    "inspection_results",         # 附录七 §6：检验结果（含欠妥概要/测试结果）
    "defect_summary_table",       # 附录七 §6.1(d)：欠妥及不完备概要表
    "elevation_photos",           # 附录七 §6：立面照片
    "inspection_stage_test_results",  # 附录七 §6.1(g)：检验阶段测试结果
    "defects_extending_into_private_premises_record",  # 附录七 §6：伸入私人处所缺陷
    "regular_maintenance_highlights",  # 附录七 §6：定期保养重点
    "summary",                    # 附录七 §6.1(d) 欠妥及不完备概要
]
# report.completion（MWIS 修缮完工报告）+ 监督/程序类报告章节（低置信 engineering_
# estimate_DEBT049，待法规卡侧核 MWIS/附录章节；同 inspection report 契约性质——章节
# 存在事实，不载具体内容）。
_REPORT_OTHER_FIELD_GROUPS: Dict[str, List[str]] = {
    "report.completion": [
        "completion_record", "repair_work_summary",
        "completed_work_demarcation_plans", "post_repair_elevation_photos",
        "proof_test_method_and_results", "previous_submission_statement_and_case_refs",
    ],
    "report.supervision": [
        "daily_inspection_records", "inspection_method_statement",
    ],
}


# DEBT-049 verification.test.performed（codex CoP §4.3 方法 / 附录七 §6.1(g) 测试结果）：
# 卡端按 method_key 限定要"测试已执行"证据。物理：有该方法的测量=测试已执行。
# **白名单存 canonical 形，消费点先 canonicalize 再判**（DEBT-049 Phase3 U3；见下派生器）。
# Phase3 U3 暗部署扩四员 {air_test, ball_test, water_test, smoke_test}——四方法现网零命中
# （air/ball 不在任何测量 slot、water/smoke 仅 drainage slot 非首元素而生成层恒取 [0]），
# 故扩员对现网 verdict 零改，供 U5 W0 供给上线后作用。**cctv_survey 不扩**——drainage_cctv
# 现网恒生成，纳入会点亮甲组 s4_4_2_a_cctv_survey 卡（非中性），入 U4/U5 gate。
_TEST_METHOD_CLASSES = frozenset({
    "pull_test", "hammer_tapping", "core_sample", "destructive_probe",
    "material_test", "self_closing_test",
    # DEBT-049 Phase3 U3 暗部署（现网零命中，canonical 形）：
    "air_test", "ball_test", "water_test", "smoke_test",
    # DEBT-049 Phase3 CCTV 三拼法桥（canonical 形；入 U4/U5 不可拆发布单元 gate，非中性）：
    # 现网恒生成 drainage_cctv，经 method_aliases 归一成 cctv_survey 后落此白名单 → 派生
    # verification.test.performed{method_key=cctv_survey}，点亮甲组 s4_4_2_a_cctv_survey 卡。
    # 别名 drainage_cctv/CCTV 归一后已收敛，不入白名单（此处只放 canonical cctv_survey）。
    "cctv_survey",
})


def derive_verification_performed_facts(
    facts: List[FactAtom],
    method_aliases: Optional[Dict[str, str]] = None,
) -> List[FactAtom]:
    """测量事实 → verification.test.performed 派生（DEBT-049，检索侧）。

    带 method_class（归一后 ∈测试方法集）的测量事实 = 该方法测试已在该 fragment 执行 →
    派生 verification.test.performed{method_key, component_type_key, fragment 戳}=true。
    每 (fragment, method_key) 一条（去重）。视觉/公式类非物理测试不派生。

    DEBT-049 Phase3 U3｜**canonicalize-first**：`method_aliases` 是运行态展开表
    ``{alias→canonical}``（由 build_method_canonical_map 反转全展开）。消费点先
    ``mc = 展开表.get(raw, raw)`` 归一，再判白名单成员 + 派生 method_key（保白名单/派生/
    卡端求交三处同一 canonical 词域）。表为 None/空 → identity（暗部署四方法即 identity；
    CCTV 三拼法桥入 U4/U5 gate、暗部署期展开表不含 drainage_cctv→cctv_survey）。
    """
    amap = method_aliases or {}
    seen: set = set()
    out: List[FactAtom] = []
    for f in facts:
        raw_mc = (f.qualifiers or {}).get("method_class")
        # 非 str（含 None / list / dict）不参与——须在白名单成员判定**之前**短路
        # （DEBT-049 Phase3 U6 补遗修）：`qualifiers` 由 `json.loads(qualifiers_json)`
        # 还原，值可能是 list/dict 等**不可哈希**类型，旧写法把原值直接送进
        # `in frozenset` 会抛 `TypeError: unhashable type`、炸掉整条检索链。语义与旧实现
        # 等价（可哈希非 str 旧路径本就在成员判定处 continue），只去掉崩溃面。
        if not isinstance(raw_mc, str):
            continue
        # 先 canonicalize 再判白名单（顺序冻结）：保白名单/派生/卡端求交同一词域。
        mc = amap.get(raw_mc, raw_mc)
        if mc not in _TEST_METHOD_CLASSES:
            continue
        frag = (f.qualifiers or {}).get("fragment_id")
        key = (frag, mc)
        if key in seen:
            continue
        seen.add(key)
        q: Dict[str, Any] = {"method_key": mc}
        if isinstance(frag, str) and frag:
            q["fragment_id"] = frag
        ct = (f.qualifiers or {}).get("component_type_key")
        if isinstance(ct, str) and ct:
            q["component_type_key"] = ct
        lc = (f.qualifiers or {}).get("location_class_key")
        if isinstance(lc, str) and lc:
            q["location_class_key"] = lc
        out.append(FactAtom(
            fact_id=f"{f.fact_id}::test_performed::{mc}",
            world_id=f.world_id, building_id=f.building_id,
            carrier_type=f.carrier_type, carrier_id=f.carrier_id, target_ref=None,
            slot_id="verification.test.performed", measure_key=None,
            value_json="true", value_type="boolean", unit=None, qualifiers=q,
            confidence_index=None, source_path="derived",
            source_node_id=f"{f.source_node_id}::test_performed::{mc}",
            provenance={"derivation": "test_performed_from_measurement"},
        ))
    return out


def derive_report_field_group_facts(
    world_id: str, building_id: str,
) -> List[FactAtom]:
    """RI 检验报告章节存在事实派生（DEBT-049 C1）。

    卡端 evidence 要 required_field_groups（inspection_results/reference_documents），
    闭包 `_check_required_field_groups` 查 `qual.artifact_field_group` 槽事实。RI 报告
    按 CoP 附录七恒有这些章节 → 楼级派生章节存在事实。**只声明章节存在**，不载具体
    内容（具体缺陷/测试/文件来自 W0/W1 事实——防伪造报告内容）。
    """
    out: List[FactAtom] = []
    groups_by_artifact = {"report.inspection": _REPORT_INSPECTION_FIELD_GROUPS}
    groups_by_artifact.update(_REPORT_OTHER_FIELD_GROUPS)
    for artifact_key, groups in groups_by_artifact.items():
        for group in groups:
            out.append(FactAtom(
                fact_id=f"{building_id}::field_group::{group}",
                world_id=world_id, building_id=building_id,
                carrier_type="sidecar_entry",
                carrier_id=f"{building_id}::{artifact_key}",
                target_ref=None, slot_id="qual.artifact_field_group",
                measure_key=None, value_json=json.dumps(group), value_type="string",
                unit=None,
                # 无 aggregation 标记（章节契约在 fragment 作用域也须可见——identify 卡
                # fragment-scoped，带 aggregation=building 会被作用域排除）。
                qualifiers={"artifact_key": artifact_key,
                            "artifact_field_group": group},
                confidence_index=None, source_path="derived",
                source_node_id=f"{building_id}::field_group::{group}",
                provenance={"derivation": "report_field_group_contract"},
            ))
    return out


def stamp_risk_class_qualifiers(
    facts: List[FactAtom],
    risk_slot_class_keys: Dict[str, Any],
) -> None:
    """风险槽事实行补 risk_class_key 限定符（DEBT-049 第四波件甲 A2）。

    卡端风险槽限定符全带 risk_class_key 维度（值域四个，卡库实测），事实侧从未
    盖章 → 候选被限定符全灭。按映射表显式声明盖章（键=消费端风险槽名，值=卡端
    risk_class_key 词汇——值域是卡端词非槽名同义反复，故显式表不搞后缀魔法）；
    已有键不覆盖。**布尔护栏**：只盖布尔行——串态回退行（not_applicable/
    no_drainage 等）本就"不适用"，盖章会让脏行可见并在同 fragment 撞 ambiguous
    （public_health 双串行实测）；不盖即维持 invisible，非适用 fragment 由结构
    NA 兜住。子集匹配语义下加观测键只增不减命中面。
    """
    if not isinstance(risk_slot_class_keys, dict) or not risk_slot_class_keys:
        return
    table = {k: v for k, v in risk_slot_class_keys.items()
             if isinstance(v, str) and v and not str(k).startswith("_")}
    for a in facts:
        key = table.get(a.slot_id or "")
        if (key and a.value_type == "boolean"
                and "risk_class_key" not in (a.qualifiers or {})):
            a.qualifiers["risk_class_key"] = key


def stamp_artifact_key_qualifiers(facts: List[FactAtom]) -> None:
    """artifact.* 事实行补 artifact_key 限定符（DEBT-049 第二波，第十四例）。

    卡端证据槽经 slot_role_map 按 {artifact_key: X} 限定，artifact 类事实行的
    键即槽名后缀（artifact.record.inspection_log → record.inspection_log，与
    slot_target 回退派生的键风格同源），但事实侧从未盖章 → 候选被限定符全灭
    判 qualifier_conflict。同义反复式机械补齐：不发明语义、已有键不覆盖；
    子集匹配语义下加观测键只增不减命中面，无回归风险。
    """
    for a in facts:
        sid = a.slot_id or ""
        if sid.startswith("artifact.") and "artifact_key" not in (a.qualifiers or {}):
            a.qualifiers["artifact_key"] = sid[len("artifact."):]


# 组件类目成员行派生的接入槽（spec 草案·DEBT-049 第二波 §3）。第二波只接范围声明；
# ②扩项（2026-07-08）：加 defect.class.present——identify 卡按上位类目 external_component
# 限定 defect（+defect_class_key+location），而闭世界负例/正例带成员值 external_wall →
# 类目行缺口撞 qualifier_conflict（同词表层级墙，wave6 实测 ~120 条）。派生复制成员
# defect 行仅换 component_type_key 为类目、保留 defect_class_key/location（单组件/
# fragment，无楼级广播——defect 行无 aggregation=building 标记，广播段自然不触发）。
_CATEGORY_MEMBERSHIP_SLOTS = {
    "scope.component.inspection_included",
    "defect.class.present",
    "verification.test.performed",  # DEBT-049：卡按 external_component 类目限定测试证据
}


def derive_category_membership_facts(
    facts: List[FactAtom],
    category_members: Dict[str, Any],
) -> List[FactAtom]:
    """组件类目成员行派生（spec 草案·DEBT-049 第二波 §3，纯函数可单测）。

    卡端限定符用上位类目（external_component）而事实行带成员值（external_wall
    恒等映射，其它卡按成员身份限定故映射不可改）——平面别名表表达不了类目从属
    （词表层级墙）。对范围声明 fragment 行（有 fragment 戳、无 aggregation 标记），
    桥后 component_type_key ∈ 某类目 members → 复制该行、仅换 component_type_key
    为类目值，其余限定符原样继承（fragment 戳 / carrier_domain / 经 enrich 补的
    location 维度）；值同源行（本类行恒真 → 类目行恒真，无键消费者绑到的双行
    同值，无歧义回归）。已是类目值的行（塌桥产物）不复制（幂等防双行）。

    另发**楼级广播行**（v3，codex ③b 实证修正）：W2 把该族义务按楼宇级广播投至
    全部 fragment 切片（实测排水切片期望 fail），故类目范围真值须对所有 fragment
    作用域可见。广播行 = carrier_type=building、不带 aggregation 标记、不带
    fragment 戳（fragment 作用域按"无 fragment 归属"放行；rank 3 在 scoped_facts
    压过 sidecar 行 rank 4，成为唯一读数）；值 = 成员楼级声明行（含塌桥类目值行）
    any_true，**仅真才发**——假案例由卡级适用性 NA 兜住（楼内无外部构件类则
    subject 词桥判整卡 not_applicable），true-only 保无键消费者无真假混值。
    须在 enrich_qualifiers_from_structure 之后调用（依赖桥后规范值）。
    """
    if not isinstance(category_members, dict) or not category_members:
        return []
    member_to_cats: Dict[str, List[str]] = {}
    category_keys: set = set()
    for cat, spec in category_members.items():
        if cat.startswith("_") or not isinstance(spec, dict):
            continue
        category_keys.add(cat)
        for m in spec.get("members") or []:
            if isinstance(m, str) and m:
                member_to_cats.setdefault(m, []).append(cat)
    if not member_to_cats:
        return []
    out: List[FactAtom] = []
    for atom in facts:
        if atom.slot_id not in _CATEGORY_MEMBERSHIP_SLOTS:
            continue
        q = atom.qualifiers or {}
        if q.get("aggregation") == "building":
            continue
        frag_id = q.get("fragment_id")
        if not (isinstance(frag_id, str) and frag_id):
            continue
        ct = q.get("component_type_key")
        if not isinstance(ct, str) or ct in category_keys:
            continue
        for cat in member_to_cats.get(ct, []):
            out.append(atom.model_copy(update={
                "fact_id": f"{atom.fact_id}::category::{cat}",
                "qualifiers": {**q, "component_type_key": cat},
                "source_node_id": f"{atom.source_node_id}::category::{cat}",
                "provenance": {**(atom.provenance or {}),
                               "derivation": "category_membership"},
            }))

    # 楼级广播行（docstring v3 段）：成员楼级声明行 any_true、仅真才发。
    for cat, spec in category_members.items():
        if cat.startswith("_") or not isinstance(spec, dict):
            continue
        members = {m for m in (spec.get("members") or []) if isinstance(m, str)}
        inputs = [
            a for a in facts
            if a.slot_id in _CATEGORY_MEMBERSHIP_SLOTS
            and (a.qualifiers or {}).get("aggregation") == "building"
            and (a.qualifiers or {}).get("component_type_key") in (members | {cat})
        ]
        if not inputs:
            continue
        if not any(str(a.value_json).strip().lower() == "true" for a in inputs):
            continue
        proto = inputs[0]
        for slot in sorted({str(a.slot_id) for a in inputs}):
            node_id = f"{proto.building_id}::category_scope::{cat}::{slot}"
            out.append(proto.model_copy(update={
                "fact_id": node_id,
                "carrier_type": "building",
                "carrier_id": proto.building_id,
                "slot_id": slot,
                "value_json": "true",
                "value_type": "boolean",
                "qualifiers": {"component_type_key": cat,
                               "carrier_domain": "scope",
                               "granularity": "building"},
                "source_node_id": node_id,
                "provenance": {**(proto.provenance or {}),
                               "derivation": "category_membership"},
            }))
    return out


def retrieve_fact_pack(
    client: Any,
    run_id: str,
    building_id: str,
) -> FactPack:
    """对指定 building 完成 Fact KG-RAG 检索并组装 FactPack（spec §5.3 + §5.5）。

    Args:
        client: `Neo4jClient` 实例。
        run_id: ComplianceAssessmentRun id。
        building_id: 目标建筑 id。

    Returns:
        FactPack。
    """
    raw = retrieve_fact_raw(client, building_id)
    _dedupe_measurements(raw)
    world_id = str(raw.world.get("world_id", "")) if raw.world else ""
    facts = facts_from_raw(raw)

    # DEBT-040 ②：取限定符词表对照并按世界结构充实 qualifiers。检索层读 rulecard
    # 注册表属本职（rule-blind 红线只禁 W2 真值）；映射缺失/坏 JSON 不阻断检索，
    # 不充实即维持现状（触发器按 missing 保守判 open）。
    value_aliases: Dict[str, Any] = {}
    try:
        rows = client.read(queries.FACT_QUALIFIER_VALUE_ALIASES)
        if rows:
            value_aliases = json.loads(
                rows[0].get("qualifier_value_aliases_json") or "{}"
            )
    except (TypeError, ValueError) as exc:
        value_aliases = {}
        _warn_mapping_degraded("qualifier_value_aliases", exc, building_id)
    if value_aliases:
        enrich_qualifiers_from_structure(facts, raw, value_aliases)

    # 缺陷类组合桥双极派生（同一映射节点的另一段；缺失/坏 JSON 同样不阻断）。
    bridges: List[Dict[str, Any]] = []
    try:
        rows = client.read(queries.FACT_DEFECT_COMBINATION_BRIDGES)
        if rows:
            parsed = json.loads(
                rows[0].get("defect_class_combination_bridges_json") or "[]"
            )
            if isinstance(parsed, list):
                bridges = [b for b in parsed if isinstance(b, dict)]
    except (TypeError, ValueError) as exc:
        bridges = []
        _warn_mapping_degraded("defect_class_combination_bridges", exc, building_id)
    if bridges:
        facts.extend(derive_combination_bridge_facts(
            raw, bridges, value_aliases, world_id, building_id,
        ))

    # DEBT-049 Phase3 U2/U3：method 别名运行态展开表（检索侧 performed 派生 canonicalize 用）。
    # 局部 import（fact_binding 纯 canonicalization 模块、无反向依赖，破环）。暗部署期
    # ProjectionRuntimeMapping 节点无 method_aliases_json → null → 空展开表 → identity 归一
    # （现网零漂移）；缺失/坏 JSON 不阻断。CCTV 三拼法桥入 U4/U5 gate、暗部署期展开表不含
    # drainage_cctv→cctv_survey。
    from evo_agent_baseline.slot_alias_policy import build_method_canonical_map
    method_alias_map: Dict[str, str] = {}
    try:
        rows = client.read(queries.FACT_METHOD_ALIASES)
        if rows:
            method_alias_map = build_method_canonical_map(
                json.loads(rows[0].get("method_aliases_json") or "{}")
            )
    except (TypeError, ValueError) as exc:
        method_alias_map = {}
        # 别名段坏掉 = CCTV 三拼法桥静默失效（drainage_cctv 不再归一成 cctv_survey
        # → performed 不派生 → 甲组/§5.6.5(e) 卡回落 open），指标层只看得到「卡没闭合」。
        _warn_mapping_degraded("method_aliases", exc, building_id)

    # verification.test.performed 派生（测量→测试已执行；须在 enrich 后、类目派生前）。
    facts.extend(derive_verification_performed_facts(facts, method_alias_map))

    # 组件类目成员行派生（同映射节点另一段；缺失/坏 JSON 不阻断；须在 enrich 之后）。
    category_members: Dict[str, Any] = {}
    try:
        rows = client.read(queries.FACT_COMPONENT_CATEGORY_MEMBERS)
        if rows:
            category_members = json.loads(
                rows[0].get("component_category_members_json") or "{}"
            )
    except (TypeError, ValueError) as exc:
        category_members = {}
        _warn_mapping_degraded("component_category_members", exc, building_id)
    if isinstance(category_members, dict) and category_members:
        facts.extend(derive_category_membership_facts(facts, category_members))

    # C1：RI 检验报告章节存在事实（field group 契约，附录七章节）。
    facts.extend(derive_report_field_group_facts(world_id, building_id))

    # artifact_key 限定符补齐（第十四例：卡端证据槽限定维度事实侧从未盖章）。
    stamp_artifact_key_qualifiers(facts)

    # 风险槽语义桥派生 + risk_class_key 盖章（第四波件甲；缺失/坏 JSON 不阻断）。
    # 一次查询取两表（同节点属性）；派生须在盖章前跑——派生出的目标槽干净行也要
    # 被盖 risk_class_key。派生从布尔源行深拷贝（已含 enrich 补的组件/位置戳）。
    risk_keys: Dict[str, Any] = {}
    risk_derivs: Dict[str, Any] = {}
    try:
        rows = client.read(queries.FACT_RISK_SLOT_CLASS_KEYS)
        if rows:
            risk_keys = json.loads(
                rows[0].get("risk_slot_class_keys_json") or "{}"
            )
            risk_derivs = json.loads(
                rows[0].get("risk_slot_derivations_json") or "{}"
            )
    except (TypeError, ValueError) as exc:
        risk_keys, risk_derivs = {}, {}
        _warn_mapping_degraded("risk_slot_class_keys+derivations", exc, building_id)
    facts.extend(derive_risk_slot_facts(facts, risk_derivs))
    stamp_risk_class_qualifiers(facts, risk_keys)

    # verification.test.failed 补 method_class 维度（同载体唯一推断，宁缺勿错）。
    infer_method_class_for_verification_flags(facts)

    # slot_targets 回退派生（reporting.artifact.prepared 等，enrich 盖完 fragment 戳后跑）。
    facts.extend(derive_slot_target_fallback_facts(facts, world_id, building_id))

    # slot_targets.lookup_rule 通用派生（2026-07-27 接线；与上面的硬编码回退两条
    # 通道并存——reporting.artifact.prepared 的 any_of 成员折叠不是 lookup_rule 语义，
    # 仍走旧通道、行为逐位不变）。本实现只消费 lookup_rule，未消费
    # owning_interfaces / owning_interface_mode（两者关系规格未说清，待裁定）。
    # 节点属性缺席 → 空表 → 无操作（暗部署模式，同 method_aliases）。
    slot_targets: Dict[str, Any] = {}
    try:
        rows = client.read(queries.FACT_SLOT_TARGETS)
        if rows:
            parsed = json.loads(rows[0].get("slot_targets_json") or "{}")
            if isinstance(parsed, dict):
                slot_targets = parsed
    except (TypeError, ValueError) as exc:
        slot_targets = {}
        _warn_mapping_degraded("slot_targets", exc, building_id)
    # 🔴 2026-07-27 codex 审核门 P1-C：卡侧「被请求限定符」组合表。
    # 此前这里**固定传 `{}`**，注释还把它写成设计（"生产侧无卡侧请求上下文"）——
    # 实际后果两条：①形态二子句（contains_requested_qualifier）永远因缺
    # `requested_qualifier_key` 被跳过；②形态一目标槽退化成"单个无限定符组合"，
    # 而「直接事实优先」里空组合被**任何**已有事实涵盖 ⇒ 只要该槽已有一条直接事实，
    # 卡真正要的那些**带限定符**的组合就一条都不派生（实测：真实批 30 栋里
    # `supervision.record.{completed,retained}` 因此 0 派生，接通后 +90 条）。
    # 采集函数 `harvest_slot_target_requested_qualifiers` 早已写好并导出，全仓只有
    # 测试在调（第九个「登记了没接线」）。现由 loader 经同一节点属性运输过来。
    # ⚠️ 诚实边界：接通后 `actor.representative.*` 两个目标槽**仍派生 0 条**——
    # 卡侧请求 `actor_role_key=ri_rep_lvl1/lvl2`（代表等级），世界侧 `qual.actor_role`
    # 只有 4 类行为者类型，两个词表结构上不相交。那是卡包 authoring 问题，不是接线问题
    # （`tests/test_slot_targets_lookup_rule_wiring.py` 把它钉成显式断言）。
    requested_qualifiers: Dict[str, Any] = {}
    try:
        rows = client.read(queries.FACT_SLOT_TARGET_REQUESTED_QUALIFIERS)
        if rows:
            parsed = json.loads(
                rows[0].get("slot_target_requested_qualifiers_json") or "{}")
            if isinstance(parsed, dict):
                requested_qualifiers = parsed
    except (TypeError, ValueError) as exc:
        requested_qualifiers = {}
        _warn_mapping_degraded("slot_target_requested_qualifiers", exc, building_id)
    if slot_targets:
        facts.extend(derive_slot_target_lookup_rule_facts(
            facts, slot_targets, requested_qualifiers, world_id, building_id,
            slot_aliases=_slot_aliases_for_lookup_rule(client, building_id),
        ))

    return build_fact_pack(
        run_id=run_id,
        world_id=world_id,
        building_id=building_id,
        facts=facts,
        source_tables=_FACT_SOURCE_TABLES,
    )


__all__ = [
    "FactRetrievalRaw",
    "derive_category_membership_facts",
    "derive_combination_bridge_facts",
    "derive_slot_target_lookup_rule_facts",
    "facts_from_raw",
    "harvest_slot_target_requested_qualifiers",
    "retrieve_fact_raw",
    "retrieve_fact_pack",
]
