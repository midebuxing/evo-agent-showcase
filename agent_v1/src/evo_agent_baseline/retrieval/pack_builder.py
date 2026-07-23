"""FactPack / RuleSlice 组装器（spec §5.4.3 + §5.5 + §5.6）。

把 KG 检索取回的扁平节点 / 子图还原为契约 DTO，并组装最终的
`FactPack`（事实包）与 `RuleSlice`（规则切片）。

实现的 spec 章节：
- §5.5 FactPack —— 从事实侧节点 dict 构造 FactAtom + 倒排索引；
- §5.4.3 DTO builder —— 把 graph expansion 的扁平子图还原为 rule_cards.json 原嵌套结构；
- §5.6 RuleSlice —— RuleCardDTO 保留原嵌套形态 + registry 子 DTO + retrieval_policy。

全部 DTO 从 `evo_agent_baseline.contracts` import，不重定义（任务约定）。

evo-agent blind：FactAtom / RuleCardDTO 等 DTO 严禁携带 §2.2.3 禁止属性名；
本模块装配时只读事实层 / 法规层字段，并在 `assert_dto_blind_safe` 做收口检查。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import (
    ArtifactDTO,
    FactAtom,
    FactPack,
    MeasureDTO,
    RuleCardDTO,
    RuleFamilyDTO,
    RuleSlice,
    SemanticSlotDTO,
    SourceQuoteDTO,
    TimeAnchorDTO,
)
from evo_agent_baseline.ingest.guard import FORBIDDEN_AGENT_PROPERTIES, SecurityError


_LOG = logging.getLogger(__name__)

# carrier label → FactAtom.carrier_type 映射（spec §5.5 carrier_type 枚举）。
_LABEL_TO_CARRIER_TYPE: Dict[str, str] = {
    "Building": "building",
    "Component": "component",
    "Location": "location",
    "Fragment": "fragment",
    "DriverState": "driver",
    "MechanismState": "mechanism",
    "ConditionState": "condition",
    "DrainageState": "drainage",
    "UBWState": "ubw",
    "FireSafetyState": "fire_safety",
    "RepairAssessmentState": "repair_assessment",
    "Measurement": "measurement",
    "SidecarEntry": "sidecar_entry",
}

# carrier label → 主键属性名。
_LABEL_TO_KEY_PROP: Dict[str, str] = {
    "Building": "building_id",
    "Component": "component_id",
    "Location": "location_id",
    "Fragment": "fragment_id",
    "DriverState": "driver_id",
    "MechanismState": "mechanism_state_id",
    "ConditionState": "condition_id",
    "DrainageState": "drainage_id",
    "UBWState": "ubw_id",
    "FireSafetyState": "fire_state_id",
    "RepairAssessmentState": "repair_assessment_id",
    "Measurement": "measurement_id",
    "SidecarEntry": "sidecar_entry_id",
}


# ===========================================================================
# blind 收口检查
# ===========================================================================
def assert_dto_blind_safe(payload: Dict[str, Any], dto_name: str) -> Dict[str, Any]:
    """检查 DTO 装配输入 dict 不含 §2.2.3 禁止属性名（spec §5.6 要求 5）。

    Args:
        payload: 待装配的属性 dict。
        dto_name: DTO 名称（报错定位用）。

    Returns:
        原 payload。

    Raises:
        SecurityError: 命中禁止属性名。
    """
    leaked = set(payload.keys()) & FORBIDDEN_AGENT_PROPERTIES
    if leaked:
        raise SecurityError(
            f"{dto_name} carries forbidden W2 property {sorted(leaked)} — "
            "evo-agent blind violation (spec §5.6 要求 5)"
        )
    return payload


def _loads(value: Any, default: Any) -> Any:
    """安全 json.loads：None / 非字符串 / 解析失败时返回 default。"""
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# ===========================================================================
# §5.5 FactAtom 构造
# ===========================================================================
def _infer_value_type(value: Any) -> str:
    """从解析后的 Python 值推断 FactAtom.value_type（spec §5.5 枚举）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (dict, list)):
        return "object"
    return "string"


def fact_atom_from_carrier_field(
    node: Dict[str, Any],
    carrier_label: str,
    world_id: str,
    building_id: str,
    field_name: str,
    value: Any,
    *,
    slot_id: Optional[str] = None,
    measure_key: Optional[str] = None,
    unit: Optional[str] = None,
    qualifiers: Optional[Dict[str, Any]] = None,
    confidence_index: Optional[float] = None,
    source_path: str = "",
) -> FactAtom:
    """把承载节点的一个字段值包装成一条 FactAtom（spec §5.5）。

    fact_id 合成 `<carrier_id>::<field_name>` 保证同一承载内唯一。

    Args:
        node: 承载节点 dict（KG 取回）。
        carrier_label: 承载节点 label。
        world_id / building_id: 所属 world / building。
        field_name: 被包装的字段名（作 slot_id 兜底 / fact_id 后缀）。
        value: 字段值（已 JSON 友好）。
        slot_id / measure_key / unit / qualifiers / confidence_index: 见 FactAtom 字段。
        source_path: 来源 parquet / 文件标识。

    Returns:
        FactAtom。
    """
    key_prop = _LABEL_TO_KEY_PROP.get(carrier_label, "id")
    carrier_id = str(node.get(key_prop, ""))
    fact_id = f"{carrier_id}::{field_name}"
    carrier_type = _LABEL_TO_CARRIER_TYPE.get(carrier_label, "building")
    return FactAtom(
        fact_id=fact_id,
        world_id=world_id,
        building_id=building_id,
        carrier_type=carrier_type,  # type: ignore[arg-type]
        carrier_id=carrier_id,
        target_ref=node.get("target_ref"),
        slot_id=slot_id if slot_id is not None else field_name,
        measure_key=measure_key,
        value_json=json.dumps(value, ensure_ascii=False, sort_keys=True),
        value_type=_infer_value_type(value),  # type: ignore[arg-type]
        unit=unit,
        qualifiers=qualifiers or {},
        confidence_index=confidence_index,
        source_path=source_path,
        source_node_id=carrier_id,
        provenance={"carrier_label": carrier_label},
    )


def fact_atoms_from_measurement(
    node: Dict[str, Any], world_id: str, building_id: str
) -> FactAtom:
    """Measurement 节点 → 一条 FactAtom（spec §5.5 + §3.3.4）。

    value_json 直接用 Measurement.value_json；qualifiers 从 qualifiers_json 解析
    （spec §3.3.4：verifier 须 json.loads(qualifiers_json) 得 dict）。
    """
    measurement_id = str(node.get("measurement_id", ""))
    qualifiers = _loads(node.get("qualifiers_json"), {})
    if not isinstance(qualifiers, dict):
        qualifiers = {}
    # spec §6.3.10.3 授权绑定 measurement method_class；FactIndex.method_index 从
    # qualifiers.method_class 建索引（fact_binding.py），节点属性须并入 qualifiers
    # 才可达（DEBT-049 复核时 codex 发现的第七例"登记了没接线"）。
    method_class = node.get("method_class")
    if method_class is not None and "method_class" not in qualifiers:
        qualifiers["method_class"] = str(method_class)
    value_json = node.get("value_json") or "null"
    parsed = _loads(value_json, None)
    return FactAtom(
        fact_id=measurement_id,
        world_id=world_id,
        building_id=building_id,
        carrier_type="measurement",
        carrier_id=measurement_id,
        target_ref=node.get("target_ref"),
        slot_id=node.get("slot_id"),
        measure_key=node.get("slot_id"),  # §3.3.4：slot_id 可能对应 measure_key
        value_json=value_json,
        value_type=_infer_value_type(parsed),  # type: ignore[arg-type]
        unit=node.get("unit"),
        qualifiers=qualifiers,
        confidence_index=node.get("confidence_index"),
        source_path="measurements.parquet",
        source_node_id=measurement_id,
        provenance={
            "carrier_label": "Measurement",
            "measurement_family": node.get("measurement_family"),
            "derivation_mode": node.get("derivation_mode"),
        },
    )


def fact_atom_from_sidecar_entry(
    node: Dict[str, Any], world_id: str, building_id: str
) -> FactAtom:
    """SidecarEntry 节点 → 一条 FactAtom（spec §5.5 + §3.3.5）。"""
    entry_id = str(node.get("sidecar_entry_id", ""))
    qualifiers = _loads(node.get("qualifiers_json"), {})
    if not isinstance(qualifiers, dict):
        qualifiers = {}
    value_json = node.get("value_json") or "null"
    parsed = _loads(value_json, None)
    # 楼级聚合行（spec 草案·流程槽粒度语义 §3.2）：载体升 "building"——
    # scope_rank 拆级后楼级绑定优先选中聚合读数、不与 fragment 戳行混绑；
    # fragment 作用域按 qualifiers.aggregation 排除（validator._fragment_index）。
    carrier = (
        "building"
        if qualifiers.get("aggregation") == "building"
        else "sidecar_entry"
    )
    return FactAtom(
        fact_id=entry_id,
        world_id=world_id,
        building_id=building_id,
        carrier_type=carrier,
        carrier_id=entry_id,
        target_ref=None,
        slot_id=node.get("slot_id"),
        measure_key=node.get("slot_id"),
        value_json=value_json,
        value_type=_infer_value_type(parsed),  # type: ignore[arg-type]
        # q6 裁定链（2026-07-08）：数值 sidecar 行带注册表量纲，闭包单位规则得以比对。
        unit=node.get("unit"),
        qualifiers=qualifiers,
        confidence_index=None,
        source_path="sidecar_entries.parquet",
        source_node_id=entry_id,
        provenance={
            "carrier_label": "SidecarEntry",
            "entry_type": node.get("entry_type"),
            "time_anchor_key": node.get("time_anchor_key"),
        },
    )


def fact_atoms_from_condition_derived_flags(
    node: Dict[str, Any], world_id: str, building_id: str
) -> List[FactAtom]:
    """ConditionState 的 derived_outcomes 各 *_flags entry → FactAtom 列表（spec §3.3.2）。

    spec §3.3.2 处理规则 3：verifier 构建 FactPack 时必须把每个 *_flags entry
    展成 FactAtom(slot_id=<flag_key>, value_json=<flag_value>, carrier_type="condition")。
    fallback_reasons 不参与 satisfied/violated 判定，但本函数仍展出供解释用。

    Args:
        node: ConditionState 节点 dict。
        world_id / building_id: 所属 world / building。

    Returns:
        FactAtom 列表（每个 flag 一条）。
    """
    atoms: List[FactAtom] = []
    condition_id = str(node.get("condition_id", ""))
    # 四组 *_flags 是判定用；risk_index_values / fallback_reasons 也展出。
    for group in (
        "risk_flags", "repair_flags", "verification_flags",
        "assessment_flags", "risk_index_values", "fallback_reasons",
    ):
        flags = _loads(node.get(f"{group}_json"), {})
        if not isinstance(flags, dict):
            continue
        for flag_key, flag_value in flags.items():
            fact_id = f"{condition_id}::{group}::{flag_key}"
            atoms.append(FactAtom(
                fact_id=fact_id,
                world_id=world_id,
                building_id=building_id,
                carrier_type="condition",
                carrier_id=condition_id,
                target_ref=None,
                slot_id=flag_key,
                measure_key=None,
                value_json=json.dumps(flag_value, ensure_ascii=False, sort_keys=True),
                value_type=_infer_value_type(flag_value),  # type: ignore[arg-type]
                unit=None,
                qualifiers={},
                confidence_index=None,
                source_path="fragment_states.parquet",
                source_node_id=condition_id,
                provenance={"carrier_label": "ConditionState", "derived_outcome_group": group},
            ))
    return atoms


def fact_atom_from_manifestation_flag(
    node: Dict[str, Any], world_id: str, building_id: str
) -> FactAtom:
    """ManifestationFlag 节点 → 一条 FactAtom（spec §3.3.2）。"""
    flag_id = str(node.get("manifestation_flag_id", ""))
    qualifiers = _loads(node.get("qualifier_ids"), {})
    if not isinstance(qualifiers, dict):
        qualifiers = {}
    value_json = node.get("value_json") or "null"
    parsed = _loads(value_json, None)
    return FactAtom(
        fact_id=flag_id,
        world_id=world_id,
        building_id=building_id,
        carrier_type="condition",
        carrier_id=str(node.get("condition_id", "")),
        target_ref=None,
        slot_id=node.get("slot_id"),
        measure_key=None,
        value_json=value_json,
        value_type=_infer_value_type(parsed),  # type: ignore[arg-type]
        unit=None,
        qualifiers=qualifiers,
        confidence_index=None,
        source_path="fragment_states.parquet",
        source_node_id=flag_id,
        provenance={"carrier_label": "ManifestationFlag"},
    )


def fact_atom_from_coverage_relation(
    node: Dict[str, Any], fragment_id: str, world_id: str, building_id: str
) -> FactAtom:
    """CoverageRelation 节点 → 一条 `scope.component.*` 存在性 FactAtom（spec §3.3.1）。

    DEBT-040 修复：`coverage_relations.parquet` 早已列入 `_FACT_SOURCE_TABLES` 并灌成
    KG 节点，但检索从未消费——触发器查 `scope.component.*` 恒 missing。
    slot_id 取 `coverage_relation_type` 的值（如 `scope.component.in_scope`），值恒 true
    （存在性事实）；rule_card 端裸名（`scope.component.inspection_included` 等）经
    projection_runtime_mapping 别名表 canonical 到这些名字。
    coverage_state / 面积数值字段暂不展开（阈值类消费走 measure 路径，另案）。
    """
    coverage_id = str(node.get("coverage_id", ""))
    qualifiers: Dict[str, Any] = {"fragment_id": fragment_id}
    obscuration = node.get("obscuration_class")
    if isinstance(obscuration, str) and obscuration:
        qualifiers["obscuration_class"] = obscuration
    return FactAtom(
        fact_id=coverage_id,
        world_id=world_id,
        building_id=building_id,
        carrier_type="fragment",
        carrier_id=fragment_id,
        target_ref=None,
        slot_id=node.get("coverage_relation_type"),
        measure_key=None,
        value_json="true",
        value_type="boolean",
        unit=None,
        qualifiers=qualifiers,
        confidence_index=None,
        source_path="coverage_relations.parquet",
        source_node_id=coverage_id,
        provenance={"carrier_label": "CoverageRelation"},
    )


# ===========================================================================
# §5.5 FactPack 组装
# ===========================================================================
def build_fact_pack(
    run_id: str,
    world_id: str,
    building_id: str,
    facts: List[FactAtom],
    source_tables: List[str],
) -> FactPack:
    """从 FactAtom 列表组装 FactPack + 三个倒排索引（spec §5.5）。

    slot_index / measure_index / carrier_index 的 value 都是 fact_id 列表。

    Args:
        run_id / world_id / building_id: run 标识。
        facts: 全部 FactAtom。
        source_tables: 本次涉及的源表名列表。

    Returns:
        FactPack。
    """
    slot_index: Dict[str, List[str]] = {}
    measure_index: Dict[str, List[str]] = {}
    carrier_index: Dict[str, List[str]] = {}
    for fact in facts:
        if fact.slot_id:
            slot_index.setdefault(fact.slot_id, []).append(fact.fact_id)
        if fact.measure_key:
            measure_index.setdefault(fact.measure_key, []).append(fact.fact_id)
        carrier_index.setdefault(fact.carrier_id, []).append(fact.fact_id)
    return FactPack(
        run_id=run_id,
        world_id=world_id,
        building_id=building_id,
        facts=facts,
        slot_index=slot_index,
        measure_index=measure_index,
        carrier_index=carrier_index,
        source_tables=sorted(set(source_tables)),
    )


# ===========================================================================
# §5.4.3 扁平子图 → RuleCardDTO 原嵌套还原
# ===========================================================================
def _strip_internal(node: Dict[str, Any], drop_keys: tuple[str, ...] = ()) -> Dict[str, Any]:
    """去掉 KG 内部字段，返回干净 dict。

    Neo4j 节点 dict 含 loader 合成的内部键（如 rule_card_id 反指）；
    还原原嵌套结构时按需丢弃。
    """
    return {k: v for k, v in node.items() if k not in drop_keys}


def rule_card_dto_from_subgraph(row: Dict[str, Any]) -> RuleCardDTO:
    """把 graph expansion 一行扁平子图还原为 RuleCardDTO（spec §5.4.3 + §5.6）。

    spec §5.6 要求 1：RuleCardDTO 必须保留 rule_card v2 原嵌套形态。
    本函数把 RULE_GRAPH_EXPANSION 返回的 collect(DISTINCT ...) 扁平列表
    重组为 trigger_conditions.items[] / workflow_operands.{...}[] /
    obligation_graph.{nodes,edges}[] / evidence_requirements.{三 bucket}[] 等嵌套。

    Args:
        row: RULE_GRAPH_EXPANSION 查询的一行结果 dict。

    Returns:
        RuleCardDTO。
    """
    rule_card = row.get("rule_card", {}) or {}
    rule_card_id = rule_card.get("rule_card_id", "")

    # --- applicability（还原嵌套 dict）---
    applicabilities = row.get("applicabilities", []) or []
    applicability: Dict[str, Any] = {}
    if applicabilities:
        ap = applicabilities[0]
        applicability = {
            "regime": ap.get("regime"),
            "actors": ap.get("actors", []),
            "phase": ap.get("phase"),
            "subject": ap.get("subject"),
            "component_scope": ap.get("component_scope", []),
            "building_scope": ap.get("building_scope", []),
            "exclusions": _loads(ap.get("exclusions_json"), []),
        }
    else:
        # 退化：从 RuleCard 节点字段取。
        applicability = {
            "regime": rule_card.get("regime"),
            "actors": rule_card.get("actors", []),
            "phase": rule_card.get("phase"),
            "subject": rule_card.get("subject"),
            "component_scope": rule_card.get("component_scope", []),
            "building_scope": rule_card.get("building_scope", []),
            "exclusions": [],
        }

    # --- trigger_conditions.items[] ---
    trigger_items: List[Dict[str, Any]] = []
    for tc in row.get("trigger_conditions", []) or []:
        trigger_items.append({
            "condition_id": tc.get("condition_id"),
            "predicate_kind": tc.get("predicate_kind"),
            "slot_ref_id": tc.get("slot_ref_id"),
            "operator": tc.get("operator"),
            "expected_value": _loads(tc.get("expected_value_json"), None),
            # DEBT-048：measure 型触发器三字段还原（slot 型这三项为 None/{}，形状不变）。
            "measure_key": tc.get("measure_key"),
            "qualifiers": _loads(tc.get("qualifiers_json"), {}),
            "unit": tc.get("unit"),
        })
    trigger_items.sort(key=lambda x: x.get("condition_id") or "")
    trigger_logic = rule_card.get("trigger_logic")
    if trigger_logic is None:
        trigger_logic = "all"
        _LOG.warning(
            "RuleCard %s has no trigger_logic in KG; falling back to 'all'",
            rule_card_id,
        )
    trigger_conditions = {"logic": trigger_logic, "items": trigger_items}

    # --- slot_role_map[] ---
    slot_role_map: List[Dict[str, Any]] = []
    for sr in row.get("slot_refs", []) or []:
        slot_role_map.append({
            "slot_ref_id": sr.get("slot_ref_id"),
            "slot_id": sr.get("slot_id"),
            "qualifiers": _loads(sr.get("qualifiers_json"), {}),
            "roles": sr.get("roles", []),
            "required": sr.get("required", False),
        })
    slot_role_map.sort(key=lambda x: x.get("slot_ref_id") or "")

    # --- threshold_regimes[]（formula 从 formula_json 还原，spec §5.6 要求 3）---
    threshold_regimes: List[Dict[str, Any]] = []
    for thr in row.get("thresholds", []) or []:
        regime: Dict[str, Any] = {
            "threshold_regime_id": thr.get("threshold_regime_id"),
            "measure_key": thr.get("measure_key"),
            "operator": thr.get("operator"),
            "value": _loads(thr.get("threshold_value_json"), None),
            "unit": thr.get("unit"),
            "qualifiers": _loads(thr.get("qualifiers_json"), {}),
            "time_anchor_key": thr.get("time_anchor_key"),
            "source_quote_refs": thr.get("source_quote_refs", []),
        }
        formula = _loads(thr.get("formula_json"), None)
        if formula is not None:
            regime["formula"] = formula
        threshold_regimes.append(regime)
    threshold_regimes.sort(key=lambda x: x.get("threshold_regime_id") or "")

    # --- workflow_operands（artifacts/deadlines/recipients）---
    workflow_artifacts: List[Dict[str, Any]] = []
    for wa in row.get("workflow_artifacts", []) or []:
        artifact_id = wa.get("artifact_id", "")
        local_id = artifact_id.split("::")[-1] if artifact_id else artifact_id
        workflow_artifacts.append({
            "artifact_id": local_id,
            "artifact_type": wa.get("artifact_type"),
            "artifact_key": wa.get("artifact_key"),
        })
    workflow_artifacts.sort(key=lambda x: x.get("artifact_id") or "")
    workflow_deadlines: List[Dict[str, Any]] = []
    for wd in row.get("workflow_deadlines", []) or []:
        deadline_id = wd.get("deadline_id", "")
        local_id = deadline_id.split("::")[-1] if deadline_id else deadline_id
        workflow_deadlines.append({
            "deadline_id": local_id,
            "relation": wd.get("relation"),
            "offset_value": wd.get("offset_value"),
            "offset_unit": wd.get("offset_unit"),
            "time_anchor_key": wd.get("time_anchor_key"),
        })
    workflow_deadlines.sort(key=lambda x: x.get("deadline_id") or "")
    workflow_recipients: List[Dict[str, Any]] = []
    for wr in row.get("workflow_recipients", []) or []:
        recipient_id = wr.get("recipient_id", "")
        local_id = recipient_id.split("::")[-1] if recipient_id else recipient_id
        workflow_recipients.append({
            "recipient_id": local_id,
            "recipient_type": wr.get("recipient_type"),
            "recipient_key": wr.get("recipient_key"),
            "delivery_mode": wr.get("delivery_mode"),
        })
    workflow_recipients.sort(key=lambda x: x.get("recipient_id") or "")
    workflow_operands = {
        "primary_actor": rule_card.get("primary_actor"),
        "primary_action": rule_card.get("primary_action"),
        "method_keys_allowed": rule_card.get("method_keys_allowed", []),
        "artifacts": workflow_artifacts,
        "deadlines": workflow_deadlines,
        "recipients": workflow_recipients,
    }

    # --- obligation_graph.{nodes,edges}[] ---
    obligation_nodes: List[Dict[str, Any]] = []
    for on in row.get("obligation_nodes", []) or []:
        obligation_nodes.append({
            "obligation_node_id": on.get("obligation_node_id"),
            "node_kind": on.get("node_kind"),
            "actor": on.get("actor"),
            "action": on.get("action"),
            "recipient_ids": on.get("recipient_ids", []),
            "artifact_ids": on.get("artifact_ids", []),
            "deadline_ids": on.get("deadline_ids", []),
            "trigger_condition_ids": on.get("trigger_condition_ids", []),
        })
    obligation_nodes.sort(key=lambda x: x.get("obligation_node_id") or "")
    obligation_edges: List[Dict[str, Any]] = []
    for oe in row.get("obligation_edges", []) or []:
        obligation_edges.append({
            "source_node_id": oe.get("source_node_id"),
            "target_node_id": oe.get("target_node_id"),
            "relation": oe.get("relation"),
        })
    obligation_edges.sort(
        key=lambda x: (x.get("source_node_id") or "", x.get("target_node_id") or "")
    )
    obligation_graph = {"nodes": obligation_nodes, "edges": obligation_edges}

    # --- evidence_requirements.{for_matching,for_submission,for_completion}[] ---
    evidence_requirements: Dict[str, List[Dict[str, Any]]] = {
        "for_matching": [], "for_submission": [], "for_completion": [],
    }
    for er in row.get("evidence_requirements", []) or []:
        bucket = er.get("bucket")
        if bucket not in evidence_requirements:
            continue
        evidence_requirements[bucket].append({
            "evidence_requirement_id": er.get("evidence_requirement_id"),
            "kind": er.get("kind"),
            "required": er.get("required", False),
            "description": er.get("description"),
            "artifact_ids": er.get("artifact_ids", []),
            "slot_ref_ids": er.get("slot_ref_ids", []),
            "measure_keys": er.get("measure_keys", []),
            "required_field_groups": er.get("required_field_groups", []),
        })
    for bucket in evidence_requirements:
        evidence_requirements[bucket].sort(
            key=lambda x: x.get("evidence_requirement_id") or ""
        )

    # --- source_quote[] ---
    source_quote: List[Dict[str, Any]] = []
    for sq in row.get("source_quotes", []) or []:
        source_quote.append({
            "quote_id": sq.get("quote_local_id"),
            "text": sq.get("text"),
            "page": sq.get("page"),
            "language": sq.get("language"),
        })
    source_quote.sort(key=lambda x: x.get("quote_id") or "")

    # --- definitions[] ---
    definitions: List[Dict[str, Any]] = []
    for definition in row.get("definitions", []) or []:
        source_quote_refs = _loads(definition.get("source_quote_refs"), [])
        if not isinstance(source_quote_refs, list):
            source_quote_refs = []
        definitions.append({
            "definition_id": definition.get("definition_id"),
            "term_key": definition.get("term_key"),
            "definition_text": definition.get("definition_text"),
            "scope_note": definition.get("scope_note"),
            "source_quote_refs": source_quote_refs,
        })
    definitions.sort(key=lambda x: x.get("definition_id") or "")

    source_section = _loads(rule_card.get("source_section_json"), [])
    if not isinstance(source_section, list):
        source_section = []

    payload = {
        "rule_card_id": rule_card_id,
        "source_document_id": rule_card.get("source_document_id", ""),
        "source_section": source_section,
        "source_quote": source_quote,
        "normalized_rule_text": rule_card.get("normalized_rule_text", ""),
        "family_id": rule_card.get("family_id", ""),
        "applicability": applicability,
        "trigger_conditions": trigger_conditions,
        "workflow_operands": workflow_operands,
        "slot_role_map": slot_role_map,
        "threshold_regimes": threshold_regimes,
        "exceptions": [],
        "definitions": definitions,
        "obligation_graph": obligation_graph,
        "neighbor_families": rule_card.get("neighbor_families", []),
        "evidence_requirements": evidence_requirements,
        "version": {
            "authoring_revision": rule_card.get("version_authoring_revision"),
            "interpretation_revision": rule_card.get("version_interpretation_revision"),
        },
        "provenance": _loads(rule_card.get("provenance_json"), {}),
    }
    assert_dto_blind_safe(rule_card, "RuleCardDTO")
    return RuleCardDTO(**payload)


# ===========================================================================
# registry 子 DTO
# ===========================================================================
def rule_family_dto_from_node(node: Dict[str, Any]) -> RuleFamilyDTO:
    """RuleFamily 节点 dict → RuleFamilyDTO（spec §3.4.2）。"""
    return RuleFamilyDTO(
        family_id=node.get("family_id", ""),
        family_name=node.get("family_name"),
        phase=node.get("phase"),
        actor=node.get("actor"),
        subject=node.get("subject"),
        action_cluster=node.get("action_cluster"),
        deprecated_family_ids=node.get("deprecated_family_ids", []) or [],
        card_count=node.get("card_count"),
    )


def semantic_slot_dto_from_node(node: Dict[str, Any]) -> SemanticSlotDTO:
    """SemanticSlot 节点 dict → SemanticSlotDTO（spec §3.4.4）。"""
    return SemanticSlotDTO(
        slot_id=node.get("slot_id", ""),
        semantic_domain=node.get("semantic_domain"),
        allowed_roles=node.get("allowed_roles", []) or [],
        semantic_meaning=node.get("semantic_meaning"),
    )


def measure_dto_from_node(node: Dict[str, Any]) -> MeasureDTO:
    """Measure 节点 dict → MeasureDTO（spec §3.4.4）。"""
    return MeasureDTO(
        measure_key=node.get("measure_key", ""),
        quantity_family=node.get("quantity_family"),
        unit=node.get("unit"),
        allowed_operators=node.get("allowed_operators", []) or [],
        semantic_meaning=node.get("semantic_meaning"),
    )


def artifact_dto_from_node(node: Dict[str, Any]) -> ArtifactDTO:
    """Artifact 节点 dict → ArtifactDTO（spec §3.4.4）。"""
    return ArtifactDTO(
        artifact_key=node.get("artifact_key", ""),
        artifact_family=node.get("artifact_family"),
        semantic_meaning=node.get("semantic_meaning"),
    )


def time_anchor_dto_from_node(node: Dict[str, Any]) -> TimeAnchorDTO:
    """TimeAnchor 节点 dict → TimeAnchorDTO（spec §3.4.4）。"""
    return TimeAnchorDTO(
        time_anchor_key=node.get("time_anchor_key", ""),
        semantic_meaning=node.get("semantic_meaning"),
    )


def source_quote_dto_from_node(node: Dict[str, Any]) -> SourceQuoteDTO:
    """SourceQuote 节点 dict → SourceQuoteDTO（spec §3.4.3 + §5.6 要求 4）。"""
    return SourceQuoteDTO(
        source_quote_id=node.get("source_quote_id", ""),
        quote_local_id=node.get("quote_local_id", ""),
        rule_card_id=node.get("rule_card_id", ""),
        text=node.get("text"),
        page=node.get("page"),
        language=node.get("language"),
    )


# ===========================================================================
# §5.6 RuleSlice 组装
# ===========================================================================
def build_rule_slice(
    run_id: str,
    rulecard_bundle_id: str,
    candidate_rule_cards: List[RuleCardDTO],
    rule_families: List[RuleFamilyDTO],
    semantic_slots: List[SemanticSlotDTO],
    measures: List[MeasureDTO],
    artifacts: List[ArtifactDTO],
    time_anchors: List[TimeAnchorDTO],
    source_quotes: List[SourceQuoteDTO],
    retrieval_policy: Dict[str, Any],
) -> RuleSlice:
    """组装 RuleSlice（spec §5.6）。

    candidate_rule_cards 按 rule_card_id 稳定排序，保证可复现
    （§5.4.4：排名只影响 LLM context 顺序，不影响 verifier 确定性候选全集）。

    Args:
        run_id / rulecard_bundle_id: run / bundle 标识。
        candidate_rule_cards: 候选 RuleCardDTO。
        rule_families / semantic_slots / measures / artifacts / time_anchors /
        source_quotes: registry 子 DTO 列表。
        retrieval_policy: 检索策略（含 ranking / cutoff policy）。

    Returns:
        RuleSlice。
    """
    return RuleSlice(
        run_id=run_id,
        rulecard_bundle_id=rulecard_bundle_id,
        candidate_rule_cards=sorted(candidate_rule_cards, key=lambda c: c.rule_card_id),
        rule_families=sorted(rule_families, key=lambda f: f.family_id),
        semantic_slots=sorted(semantic_slots, key=lambda s: s.slot_id),
        measures=sorted(measures, key=lambda m: m.measure_key),
        artifacts=sorted(artifacts, key=lambda a: a.artifact_key),
        time_anchors=sorted(time_anchors, key=lambda t: t.time_anchor_key),
        source_quotes=sorted(source_quotes, key=lambda q: q.source_quote_id),
        retrieval_policy=retrieval_policy,
    )


__all__ = [
    "assert_dto_blind_safe",
    "fact_atom_from_carrier_field",
    "fact_atoms_from_measurement",
    "fact_atom_from_sidecar_entry",
    "fact_atoms_from_condition_derived_flags",
    "fact_atom_from_manifestation_flag",
    "build_fact_pack",
    "rule_card_dto_from_subgraph",
    "rule_family_dto_from_node",
    "semantic_slot_dto_from_node",
    "measure_dto_from_node",
    "artifact_dto_from_node",
    "time_anchor_dto_from_node",
    "source_quote_dto_from_node",
    "build_rule_slice",
]
