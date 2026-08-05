"""rule_card loader：rule_card v2 → 结构化子节点（spec §4.3 + §3.4.2 / §3.4.3 / §3.4.4）。

把 rule_card v2 包（397 卡 / 43 family / 各 registry）灌入法规-Skills 侧 KG。
spec §4.3.3 明确：必须逐项落图为结构化子节点，不允许只把整张卡塞 JSON。

实现的 spec 章节：
- §3.4.2 RuleCard / RuleFamily；
- §3.4.3 SourceQuote / ApplicabilityPredicate / TriggerCondition / SlotRef /
  RuleThreshold / ObligationNode / ObligationEdge / workflow operand nodes /
  EvidenceRequirement；
- §3.4.4 registries SemanticSlot / Measure / Artifact / TimeAnchor / VocabularyTerm /
  ExceptionDefinition；
- §4.3.2 RuleCardBundle；§4.3.3 rule card parsing；§4.3.4 source section → clause。

rule-blind 红线只属 W0/W1（见 memory）：rule_card 是 agent-visible 结构化法规知识
（spec §2.1），rulecard loader 正常加载。但 §2.2.3 禁止属性名仍适用 —— RuleThreshold
必须命名为 threshold_value_json / operator / formula_json，不得伪装成 W2 ThresholdEval。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from evo_agent_baseline.ingest._common import (
    as_str_list,
    canonical_json,
    opt_int,
    opt_str,
)
from evo_agent_baseline.ingest._graphspec import EdgeSpec, GraphBatch, NodeSpec
from evo_agent_baseline.ingest.guard import (
    AuditLog,
    gate_g003_rulecard_child_completeness,
    gate_g004_threshold_formula_preservation,
    gate_g005_obligation_edge_preservation,
    gate_g007_source_quote_key,
    raise_if_failed,
)

# §4.3.1 rule_card v2 输入文件。
RULECARD_FILES: Dict[str, str] = {
    "manifest": "manifest.json",
    "rule_cards": "rule_cards.json",
    "family_index": "family_index.json",
    "slot_index": "slot_index.json",
    "threshold_regime_index": "threshold_regime_index.json",
    "exception_definition_index": "exception_definition_index.json",
    "semantic_slot_registry": "semantic_slot_registry_v1.json",
    "measure_registry": "measure_registry_v1.json",
    "artifact_semantics_registry": "artifact_semantics_registry_v1.json",
    "time_anchor_registry": "time_anchor_registry_v1.json",
    "controlled_vocabularies": "controlled_vocabularies_v1.json",
    "projection_runtime_mapping": "projection_runtime_mapping_v1.json",
    # DEBT-065 第一波:组件类型格(共享本体,排斥关系)+ 精确目标授权表。
    "component_type_lattice": "component_type_lattice_v1.json",
    "exact_fragment_target_authorizations": "exact_fragment_target_authorizations_v1.json",
}

# §1.0 / §3.4.3 评论：obligation edge 基线允许的 relation。
ALLOWED_OBLIGATION_EDGE_RELATIONS: Set[str] = {"if_failed_then", "if_unable_then"}


@dataclass
class RuleCardLoadResult:
    """rule_card loader 灌库结果。"""

    batch: GraphBatch
    bundle_id: Optional[str] = None
    card_count: int = 0
    family_count: int = 0
    audit: AuditLog = field(default_factory=AuditLog)


# ===========================================================================
# §4.3.4 section_id 归一化
# ===========================================================================
def normalize_section_id(section_id: str) -> str:
    """归一化 rule_card source_section.section_id（spec §4.3.4）。

    示例（spec §4.3.4）：
        "2.1.3(o)"  -> "2.1.3(o)"
        "s2_1_3_o"  -> "2.1.3(o)"

    规则：去掉前导 's'，下划线还原为点号，末段单字母 / 数字若是括号后缀形态
    则包成 `(x)`。无法识别的原样返回。

    Args:
        section_id: 上游 section_id。

    Returns:
        归一化 section_id。
    """
    raw = section_id.strip()
    # 已是点号 / 括号形态，直接返回。
    if "_" not in raw:
        return raw
    body = raw
    if body.lower().startswith("s") and len(body) > 1 and (body[1].isdigit() or body[1] == "_"):
        body = body[1:]
    parts = [p for p in body.split("_") if p != ""]
    if not parts:
        return raw
    # 末段若是单个字母 / 短 token，作括号后缀。
    last = parts[-1]
    if len(parts) >= 2 and re.fullmatch(r"[a-zA-Z0-9]{1,3}", last) and not last.isdigit():
        return ".".join(parts[:-1]) + f"({last})"
    return ".".join(parts)


# ===========================================================================
# JSON 加载工具
# ===========================================================================
def _load_json(path: Path) -> Any:
    """加载 JSON 文件。"""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _canon_or_none(value: Any) -> Optional[str]:
    """value 为 None 时返回 None，否则 canonical JSON（spec §3.4.3 formula_json 口径）。"""
    if value is None:
        return None
    return canonical_json(value)


# ===========================================================================
# §3.4.2 RuleCard / RuleFamily
# ===========================================================================
def build_rule_card_node(card: Dict[str, Any]) -> NodeSpec:
    """rule_cards.json 一张卡 → (:RuleCard) 节点（spec §3.4.2 + §4.3.3）。

    属性按 spec §3.4.2 表；source_quote_texts 是 loader 派生字段
    （source_quote[].text 展平，供全文索引）。
    """
    applicability = card.get("applicability", {}) or {}
    workflow = card.get("workflow_operands", {}) or {}
    version = card.get("version", {}) or {}
    source_quotes = card.get("source_quote", []) or []
    trigger_conditions = card.get("trigger_conditions", {}) or {}

    props = {
        "source_document_id": opt_str(card.get("source_document_id")),
        "normalized_rule_text": card.get("normalized_rule_text", "") or "",
        "family_id": opt_str(card.get("family_id")),
        "phase": opt_str(applicability.get("phase")),
        "subject": opt_str(applicability.get("subject")),
        "regime": opt_str(applicability.get("regime")),
        "actors": as_str_list(applicability.get("actors")),
        "component_scope": as_str_list(applicability.get("component_scope")),
        "building_scope": as_str_list(applicability.get("building_scope")),
        "neighbor_families": as_str_list(card.get("neighbor_families")),
        # 聚合逻辑属于整张卡的 trigger_conditions 容器；落父节点避免逐 trigger 重复，
        # 也能覆盖 items 为空的卡。
        "trigger_logic": opt_str(trigger_conditions.get("logic")),
        "primary_actor": opt_str(workflow.get("primary_actor")),
        "primary_action": opt_str(workflow.get("primary_action")),
        "method_keys_allowed": as_str_list(workflow.get("method_keys_allowed")),
        "version_authoring_revision": opt_str(version.get("authoring_revision")),
        "version_interpretation_revision": opt_int(version.get("interpretation_revision")),
        # source_section 是 list-of-dict，沿用复杂卡字段的 canonical JSON 存法。
        "source_section_json": canonical_json(card.get("source_section", []) or []),
        "provenance_json": canonical_json(card.get("provenance", {}) or {}),
        # loader 派生：source_quote[].text 展平。
        "source_quote_texts": [
            str(q.get("text")) for q in source_quotes if isinstance(q, dict) and q.get("text")
        ],
    }
    # audiences 当前应为空数组；非空时透传到 audiences_json + warning（spec §3.4.3）。
    audiences = workflow.get("audiences")
    if audiences:
        props["audiences_json"] = canonical_json(audiences)
    return NodeSpec("RuleCard", "rule_card_id", card["rule_card_id"], props)


def build_rule_family_node(family: Dict[str, Any]) -> NodeSpec:
    """family_index.json 一个 family → (:RuleFamily) 节点（spec §3.4.2）。

    family_index 的 family_id 不带 `mbis.` 之外前缀（实测如
    `mbis.reporting.inspection_report.ri.submit`）；card_count 由 card_ids 长度推。
    """
    card_ids = as_str_list(family.get("card_ids"))
    props = {
        "family_name": opt_str(family.get("family_name")),
        "phase": opt_str(family.get("phase")),
        "actor": opt_str(family.get("actor")),
        "subject": opt_str(family.get("subject")),
        "action_cluster": opt_str(family.get("action_cluster")),
        "deprecated_family_ids": as_str_list(family.get("deprecated_family_ids")),
        "card_count": family.get("card_count")
        if family.get("card_count") is not None else len(card_ids),
    }
    return NodeSpec("RuleFamily", "family_id", family["family_id"], props)


# ===========================================================================
# §3.4.3 rule card 子结构
# ===========================================================================
def build_source_quote_nodes(card: Dict[str, Any], audit: AuditLog) -> GraphBatch:
    """rule card 的 source_quote[] → (:SourceQuote) 节点（spec §3.4.3 + §4.3.3）。

    quote_local_id 规则：上游有 quote_id 用它，否则按数组序生成 sq%02d。
    source_quote_id = rule_card_id + "::" + quote_local_id。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    for idx, quote in enumerate(card.get("source_quote", []) or []):
        if not isinstance(quote, dict):
            continue
        quote_local_id = opt_str(quote.get("quote_id")) or f"sq{idx + 1:02d}"
        source_quote_id = f"{rule_card_id}::{quote_local_id}"
        props = {
            "rule_card_id": rule_card_id,
            "quote_local_id": quote_local_id,
            "text": opt_str(quote.get("text")),
            "page": quote.get("page"),
            "language": opt_str(quote.get("language")),
        }
        # G-007：SourceQuote 必须含 source_quote_id。
        full_props = dict(props)
        full_props["source_quote_id"] = source_quote_id
        raise_if_failed(gate_g007_source_quote_key(rule_card_id, full_props))
        batch.add_node(NodeSpec("SourceQuote", "source_quote_id", source_quote_id, props))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_SOURCE_QUOTE",
            "SourceQuote", "source_quote_id", source_quote_id,
        ))
    return batch


def build_applicability_node(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 applicability → (:ApplicabilityPredicate)（spec §3.4.3）。"""
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    applicability = card.get("applicability", {}) or {}
    applicability_id = f"{rule_card_id}::applicability"
    props = {
        "rule_card_id": rule_card_id,
        "regime": opt_str(applicability.get("regime")),
        "actors": as_str_list(applicability.get("actors")),
        "phase": opt_str(applicability.get("phase")),
        "subject": opt_str(applicability.get("subject")),
        "component_scope": as_str_list(applicability.get("component_scope")),
        "building_scope": as_str_list(applicability.get("building_scope")),
        "exclusions_json": canonical_json(applicability.get("exclusions", []) or []),
    }
    batch.add_node(NodeSpec(
        "ApplicabilityPredicate", "applicability_id", applicability_id, props
    ))
    batch.add_edge(EdgeSpec(
        "RuleCard", "rule_card_id", rule_card_id,
        "HAS_APPLICABILITY",
        "ApplicabilityPredicate", "applicability_id", applicability_id,
    ))
    return batch


def build_trigger_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 trigger_conditions.items[] → (:TriggerCondition)（spec §3.4.3）。

    trigger_condition_id = rule_card_id + "::trigger::" + condition_id。
    expected_value_json 为上游 expected_value 的 canonical JSON。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    triggers = (card.get("trigger_conditions", {}) or {}).get("items", []) or []
    for trig in triggers:
        if not isinstance(trig, dict):
            continue
        condition_id = opt_str(trig.get("condition_id"))
        if condition_id is None:
            continue
        trigger_condition_id = f"{rule_card_id}::trigger::{condition_id}"
        slot_ref_id = opt_str(trig.get("slot_ref_id"))
        props = {
            "rule_card_id": rule_card_id,
            "condition_id": condition_id,
            "predicate_kind": opt_str(trig.get("predicate_kind")),
            "slot_ref_id": slot_ref_id,
            "operator": opt_str(trig.get("operator")),
            "expected_value_json": canonical_json(trig.get("expected_value")),
            # DEBT-048：measure 型触发器（全库 6 张覆盖率卡）依赖以下三字段；
            # 此前漏灌导致 KG 侧 measure_key=None、下游无数据可绑。
            "measure_key": opt_str(trig.get("measure_key")),
            "qualifiers_json": canonical_json(trig.get("qualifiers", {}) or {}),
            "unit": opt_str(trig.get("unit")),
        }
        batch.add_node(NodeSpec(
            "TriggerCondition", "trigger_condition_id", trigger_condition_id, props
        ))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_TRIGGER",
            "TriggerCondition", "trigger_condition_id", trigger_condition_id,
        ))
        if slot_ref_id:
            batch.add_edge(EdgeSpec(
                "TriggerCondition", "trigger_condition_id", trigger_condition_id,
                "REFERS_TO_SLOT_REF",
                "SlotRef", "slot_ref_id", slot_ref_id,
            ))
    return batch


def build_slot_ref_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 slot_role_map[] → (:SlotRef)（spec §3.4.3）。

    每行一个 SlotRef（同 slot_id 经不同 qualifiers/roles 扮不同语义）。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    for entry in card.get("slot_role_map", []) or []:
        if not isinstance(entry, dict):
            continue
        slot_ref_id = opt_str(entry.get("slot_ref_id"))
        if slot_ref_id is None:
            continue
        slot_id = opt_str(entry.get("slot_id"))
        props = {
            "rule_card_id": rule_card_id,
            "slot_id": slot_id,
            "qualifiers_json": canonical_json(entry.get("qualifiers", {}) or {}),
            "roles": as_str_list(entry.get("roles")),
            "required": bool(entry.get("required", False)),
        }
        batch.add_node(NodeSpec("SlotRef", "slot_ref_id", slot_ref_id, props))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_SLOT_REF",
            "SlotRef", "slot_ref_id", slot_ref_id,
        ))
        if slot_id:
            batch.add_edge(EdgeSpec(
                "SlotRef", "slot_ref_id", slot_ref_id,
                "REFERS_TO_SEMANTIC_SLOT",
                "SemanticSlot", "slot_id", slot_id,
            ))
    return batch


def build_threshold_nodes(card: Dict[str, Any], audit: AuditLog) -> GraphBatch:
    """rule card 的 threshold_regimes[] → (:RuleThreshold)（spec §3.4.3 + §4.3.3）。

    spec §3.4.3 映射：
    - family_id 由 loader 从父 RuleCard.family_id 派生（C-2）；
    - threshold_value_json = 上游 value 的 canonical JSON，缺失则 null；
    - formula_json = 上游 formula 的 canonical JSON，无 formula 则 null。
    G-004：operator='formula' 且上游有 formula 时 formula_json 不得为空。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    family_id = opt_str(card.get("family_id"))   # C-2：从父卡派生
    for thr in card.get("threshold_regimes", []) or []:
        if not isinstance(thr, dict):
            continue
        threshold_regime_id = opt_str(thr.get("threshold_regime_id"))
        if threshold_regime_id is None:
            continue
        operator = opt_str(thr.get("operator"))
        upstream_formula = thr.get("formula")
        formula_json = _canon_or_none(upstream_formula)
        measure_key = opt_str(thr.get("measure_key"))
        time_anchor_key = opt_str(thr.get("time_anchor_key"))
        source_quote_refs = as_str_list(thr.get("source_quote_refs"))
        props = {
            "rule_card_id": rule_card_id,
            "family_id": family_id,
            "measure_key": measure_key,
            "operator": operator,
            "threshold_value_json": canonical_json(thr.get("value")),
            "unit": opt_str(thr.get("unit")),
            "qualifiers_json": canonical_json(thr.get("qualifiers", {}) or {}),
            "time_anchor_key": time_anchor_key,
            "source_quote_refs": source_quote_refs,
            "formula_json": formula_json,
        }
        # 🔴 审计留痕必须进图(DEBT-072 阻断 1)：卡自带阈值与旁路回填阈值若在图里
        # 无法区分，日后没人能查"这条阈值是谁按什么裁的"。只在有值时写，
        # 卡自带阈值不受影响（属性不出现）。
        for _audit_key in ("provenance", "source_zh"):
            _v = opt_str(thr.get(_audit_key))
            if _v:
                props[_audit_key] = _v
        # G-004：formula 保留校验。
        raise_if_failed(gate_g004_threshold_formula_preservation(
            threshold_regime_id, operator, upstream_formula is not None, formula_json,
        ))
        batch.add_node(NodeSpec(
            "RuleThreshold", "threshold_regime_id", threshold_regime_id, props
        ))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_THRESHOLD",
            "RuleThreshold", "threshold_regime_id", threshold_regime_id,
        ))
        if measure_key:
            batch.add_edge(EdgeSpec(
                "RuleThreshold", "threshold_regime_id", threshold_regime_id,
                "REFERS_TO_MEASURE",
                "Measure", "measure_key", measure_key,
            ))
        if time_anchor_key:
            batch.add_edge(EdgeSpec(
                "RuleThreshold", "threshold_regime_id", threshold_regime_id,
                "USES_TIME_ANCHOR",
                "TimeAnchor", "time_anchor_key", time_anchor_key,
            ))
        # SUPPORTED_BY_QUOTE：source_quote_refs 是 quote_local_id，拼成 source_quote_id。
        for quote_local_id in source_quote_refs:
            batch.add_edge(EdgeSpec(
                "RuleThreshold", "threshold_regime_id", threshold_regime_id,
                "SUPPORTED_BY_QUOTE",
                "SourceQuote", "source_quote_id", f"{rule_card_id}::{quote_local_id}",
            ))
    return batch


def build_obligation_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 obligation_graph.nodes[] → (:ObligationNode)（spec §3.4.3）。"""
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    nodes = (card.get("obligation_graph", {}) or {}).get("nodes", []) or []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        obligation_node_id = opt_str(node.get("obligation_node_id"))
        if obligation_node_id is None:
            continue
        artifact_ids = as_str_list(node.get("artifact_ids"))
        deadline_ids = as_str_list(node.get("deadline_ids"))
        recipient_ids = as_str_list(node.get("recipient_ids"))
        trigger_condition_ids = as_str_list(node.get("trigger_condition_ids"))
        props = {
            "rule_card_id": rule_card_id,
            "node_kind": opt_str(node.get("node_kind")),
            "actor": opt_str(node.get("actor")),
            "action": opt_str(node.get("action")),
            "recipient_ids": recipient_ids,
            "artifact_ids": artifact_ids,
            "deadline_ids": deadline_ids,
            "trigger_condition_ids": trigger_condition_ids,
        }
        batch.add_node(NodeSpec(
            "ObligationNode", "obligation_node_id", obligation_node_id, props
        ))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_OBLIGATION_NODE",
            "ObligationNode", "obligation_node_id", obligation_node_id,
        ))
        # ObligationNode-TRIGGERED_BY->TriggerCondition（trigger_condition_ids 是
        # card 内 condition_id；拼全 trigger_condition_id）。
        for condition_id in trigger_condition_ids:
            batch.add_edge(EdgeSpec(
                "ObligationNode", "obligation_node_id", obligation_node_id,
                "TRIGGERED_BY",
                "TriggerCondition", "trigger_condition_id",
                f"{rule_card_id}::trigger::{condition_id}",
            ))
        # ObligationNode-REQUIRES_ARTIFACT->WorkflowArtifact 等。
        for artifact_id in artifact_ids:
            batch.add_edge(EdgeSpec(
                "ObligationNode", "obligation_node_id", obligation_node_id,
                "REQUIRES_ARTIFACT",
                "WorkflowArtifact", "artifact_id", f"{rule_card_id}::{artifact_id}",
            ))
        for deadline_id in deadline_ids:
            batch.add_edge(EdgeSpec(
                "ObligationNode", "obligation_node_id", obligation_node_id,
                "HAS_DEADLINE",
                "WorkflowDeadline", "deadline_id", f"{rule_card_id}::{deadline_id}",
            ))
        for recipient_id in recipient_ids:
            batch.add_edge(EdgeSpec(
                "ObligationNode", "obligation_node_id", obligation_node_id,
                "SENT_TO",
                "WorkflowRecipient", "recipient_id", f"{rule_card_id}::{recipient_id}",
            ))
    return batch


def build_obligation_edges(card: Dict[str, Any], audit: AuditLog) -> GraphBatch:
    """rule card 的 obligation_graph.edges[] → (:ObligationEdge)（spec §3.4.3 + §4.3.3）。

    obligation_edge_id = rule_card_id + "::edge::" + source + "::" + relation + "::" + target。
    未知 relation 不丢弃（verifier 处理为 blocked + unsupported_obligation_edge_relation）。
    端点缺失时标 edge_resolution_state="unresolved"（verifier 输出
    blocked + missing_obligation_edge_target）。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    obligation_graph = card.get("obligation_graph", {}) or {}
    nodes = obligation_graph.get("nodes", []) or []
    node_ids = {
        opt_str(n.get("obligation_node_id"))
        for n in nodes if isinstance(n, dict)
    }
    edges = obligation_graph.get("edges", []) or []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source_node_id = opt_str(edge.get("source_node_id"))
        target_node_id = opt_str(edge.get("target_node_id"))
        relation = opt_str(edge.get("relation"))
        if source_node_id is None or target_node_id is None or relation is None:
            audit.warn(f"{rule_card_id}: obligation edge missing field, skipped")
            continue
        obligation_edge_id = (
            f"{rule_card_id}::edge::{source_node_id}::{relation}::{target_node_id}"
        )
        both_resolved = source_node_id in node_ids and target_node_id in node_ids
        props = {
            "rule_card_id": rule_card_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation": relation,
            # §4.3.3 步骤 4：端点缺失标 unresolved。
            "edge_resolution_state": "resolved" if both_resolved else "unresolved",
        }
        if relation not in ALLOWED_OBLIGATION_EDGE_RELATIONS:
            audit.warn(
                f"{rule_card_id}: obligation edge relation {relation!r} not in baseline set"
            )
        batch.add_node(NodeSpec(
            "ObligationEdge", "obligation_edge_id", obligation_edge_id, props
        ))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_OBLIGATION_EDGE",
            "ObligationEdge", "obligation_edge_id", obligation_edge_id,
        ))
        # 端点都存在时建 FROM/TO + ObligationNode-OBLIGATION_EDGE->ObligationNode。
        if both_resolved:
            batch.add_edge(EdgeSpec(
                "ObligationEdge", "obligation_edge_id", obligation_edge_id,
                "FROM_OBLIGATION_NODE",
                "ObligationNode", "obligation_node_id", source_node_id,
            ))
            batch.add_edge(EdgeSpec(
                "ObligationEdge", "obligation_edge_id", obligation_edge_id,
                "TO_OBLIGATION_NODE",
                "ObligationNode", "obligation_node_id", target_node_id,
            ))
            batch.add_edge(EdgeSpec(
                "ObligationNode", "obligation_node_id", source_node_id,
                "OBLIGATION_EDGE",
                "ObligationNode", "obligation_node_id", target_node_id,
                {"relation": relation, "obligation_edge_id": obligation_edge_id},
            ))
    return batch


def build_workflow_operand_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 workflow_operands.{recipients,artifacts,deadlines}[] → 工件节点（spec §3.4.3）。

    生成 WorkflowRecipient / WorkflowArtifact / WorkflowDeadline；
    主键合成 `rule_card_id + "::" + local_id` 保证跨卡唯一。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    workflow = card.get("workflow_operands", {}) or {}

    for recipient in workflow.get("recipients", []) or []:
        if not isinstance(recipient, dict):
            continue
        local_id = opt_str(recipient.get("recipient_id"))
        if local_id is None:
            continue
        node_id = f"{rule_card_id}::{local_id}"
        props = {
            "rule_card_id": rule_card_id,
            "recipient_type": opt_str(recipient.get("recipient_type")),
            "recipient_key": opt_str(recipient.get("recipient_key")),
            "delivery_mode": opt_str(recipient.get("delivery_mode")),
        }
        batch.add_node(NodeSpec("WorkflowRecipient", "recipient_id", node_id, props))

    for artifact in workflow.get("artifacts", []) or []:
        if not isinstance(artifact, dict):
            continue
        local_id = opt_str(artifact.get("artifact_id"))
        if local_id is None:
            continue
        node_id = f"{rule_card_id}::{local_id}"
        artifact_key = opt_str(artifact.get("artifact_key"))
        props = {
            "rule_card_id": rule_card_id,
            "artifact_type": opt_str(artifact.get("artifact_type")),
            "artifact_key": artifact_key,
        }
        batch.add_node(NodeSpec("WorkflowArtifact", "artifact_id", node_id, props))
        # WorkflowArtifact 对应到 registry Artifact（artifact_key 可解析时）。
        if artifact_key:
            batch.add_edge(EdgeSpec(
                "WorkflowArtifact", "artifact_id", node_id,
                "REFERS_TO_ARTIFACT_TYPE",
                "Artifact", "artifact_key", artifact_key,
            ))

    for deadline in workflow.get("deadlines", []) or []:
        if not isinstance(deadline, dict):
            continue
        local_id = opt_str(deadline.get("deadline_id"))
        if local_id is None:
            continue
        node_id = f"{rule_card_id}::{local_id}"
        time_anchor_key = opt_str(deadline.get("time_anchor_key"))
        props = {
            "rule_card_id": rule_card_id,
            "relation": opt_str(deadline.get("relation")),
            "offset_value": deadline.get("offset_value"),
            "offset_unit": opt_str(deadline.get("offset_unit")),
            "time_anchor_key": time_anchor_key,
        }
        batch.add_node(NodeSpec("WorkflowDeadline", "deadline_id", node_id, props))
        if time_anchor_key:
            batch.add_edge(EdgeSpec(
                "WorkflowDeadline", "deadline_id", node_id,
                "USES_TIME_ANCHOR",
                "TimeAnchor", "time_anchor_key", time_anchor_key,
            ))
    return batch


def build_evidence_requirement_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 evidence_requirements.{for_matching,for_submission,for_completion}[]
    → (:EvidenceRequirement)（spec §3.4.3）。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    evidence = card.get("evidence_requirements", {}) or {}
    for bucket in ("for_matching", "for_submission", "for_completion"):
        for req in evidence.get(bucket, []) or []:
            if not isinstance(req, dict):
                continue
            evidence_requirement_id = opt_str(req.get("evidence_requirement_id"))
            if evidence_requirement_id is None:
                continue
            artifact_ids = as_str_list(req.get("artifact_ids"))
            slot_ref_ids = as_str_list(req.get("slot_ref_ids"))
            measure_keys = as_str_list(req.get("measure_keys"))
            props = {
                "rule_card_id": rule_card_id,
                "bucket": bucket,
                "kind": opt_str(req.get("kind")),
                "required": bool(req.get("required", False)),
                "description": opt_str(req.get("description")),
                "artifact_ids": artifact_ids,
                "slot_ref_ids": slot_ref_ids,
                "measure_keys": measure_keys,
                "required_field_groups": as_str_list(req.get("required_field_groups")),
            }
            batch.add_node(NodeSpec(
                "EvidenceRequirement", "evidence_requirement_id",
                evidence_requirement_id, props,
            ))
            batch.add_edge(EdgeSpec(
                "RuleCard", "rule_card_id", rule_card_id,
                "HAS_EVIDENCE_REQUIREMENT",
                "EvidenceRequirement", "evidence_requirement_id", evidence_requirement_id,
            ))
            for slot_ref_id in slot_ref_ids:
                batch.add_edge(EdgeSpec(
                    "EvidenceRequirement", "evidence_requirement_id", evidence_requirement_id,
                    "REQUIRES_SLOT_REF",
                    "SlotRef", "slot_ref_id", slot_ref_id,
                ))
            for measure_key in measure_keys:
                batch.add_edge(EdgeSpec(
                    "EvidenceRequirement", "evidence_requirement_id", evidence_requirement_id,
                    "REQUIRES_MEASURE",
                    "Measure", "measure_key", measure_key,
                ))
            for artifact_id in artifact_ids:
                batch.add_edge(EdgeSpec(
                    "EvidenceRequirement", "evidence_requirement_id", evidence_requirement_id,
                    "REQUIRES_WORKFLOW_ARTIFACT",
                    "WorkflowArtifact", "artifact_id", f"{rule_card_id}::{artifact_id}",
                ))
    return batch


def build_definition_nodes(card: Dict[str, Any]) -> GraphBatch:
    """rule card 的 definitions[] / exceptions[] → (:ExceptionDefinition)（spec §3.4.4）。

    spec §3.4.4 给的 ExceptionDefinition 字段：definition_id, term_key,
    definition_text, scope_note, source_quote_refs, family_id, rule_card_id。
    """
    batch = GraphBatch()
    rule_card_id = card["rule_card_id"]
    family_id = opt_str(card.get("family_id"))
    for entry in (card.get("definitions", []) or []) + (card.get("exceptions", []) or []):
        if not isinstance(entry, dict):
            continue
        definition_id = opt_str(entry.get("definition_id")) or opt_str(entry.get("exception_id"))
        if definition_id is None:
            continue
        props = {
            "term_key": opt_str(entry.get("term_key")),
            "definition_text": opt_str(entry.get("definition_text")),
            "scope_note": opt_str(entry.get("scope_note")),
            "source_quote_refs": as_str_list(entry.get("source_quote_refs")),
            "family_id": family_id,
            "rule_card_id": rule_card_id,
        }
        batch.add_node(NodeSpec(
            "ExceptionDefinition", "definition_id", definition_id, props
        ))
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "HAS_DEFINITION",
            "ExceptionDefinition", "definition_id", definition_id,
        ))
    return batch


# ===========================================================================
# §3.4.4 registries
# ===========================================================================
def _harvest_requested_qualifiers(rulecard_dir: Path) -> Dict[str, Any]:
    """采集卡侧「被请求限定符」组合表 {slot_id: [限定符组合...]}（P1-C 接线用）。

    复用检索侧的纯函数 `harvest_slot_target_requested_qualifiers`，**不复制第二份
    遍历逻辑**——两份迟早漂移，而这张表决定形态二子句能不能求值。
    函数内 import：ingest 只在此一处用检索侧的纯函数，模块级导入会把两个子包绑死。
    卡包缺席 → 空表（与本文件其它段同样的暗部署语义，不阻断灌库）。
    """
    from evo_agent_baseline.retrieval.fact_retriever import (
        harvest_slot_target_requested_qualifiers,
    )

    cards_path = rulecard_dir / RULECARD_FILES["rule_cards"]
    if not cards_path.is_file():
        return {}
    return harvest_slot_target_requested_qualifiers(_load_json(cards_path))


def build_registry_graph(rulecard_dir: Path, audit: AuditLog) -> GraphBatch:
    """加载 5 个 registry + controlled vocabularies → registry 节点（spec §3.4.4）。

    SemanticSlot / Measure / Artifact / TimeAnchor / VocabularyTerm /
    ExceptionDefinition（来自 exception_definition_index.json）。

    Args:
        rulecard_dir: rule_card v2 目录。
        audit: 审计记录器。

    Returns:
        registry 节点 GraphBatch。
    """
    batch = GraphBatch()

    # SemanticSlot。
    slot_path = rulecard_dir / RULECARD_FILES["semantic_slot_registry"]
    if slot_path.is_file():
        audit.record_source(slot_path.name)
        for slot in _load_json(slot_path).get("slots", []) or []:
            slot_id = opt_str(slot.get("slot_id"))
            if slot_id is None:
                continue
            batch.add_node(NodeSpec("SemanticSlot", "slot_id", slot_id, {
                "semantic_domain": opt_str(slot.get("semantic_domain")),
                "allowed_roles": as_str_list(slot.get("allowed_roles")),
                "semantic_meaning": opt_str(slot.get("semantic_meaning")),
            }))

    # Measure。
    measure_path = rulecard_dir / RULECARD_FILES["measure_registry"]
    if measure_path.is_file():
        audit.record_source(measure_path.name)
        for measure in _load_json(measure_path).get("measures", []) or []:
            measure_key = opt_str(measure.get("measure_key"))
            if measure_key is None:
                continue
            batch.add_node(NodeSpec("Measure", "measure_key", measure_key, {
                "quantity_family": opt_str(measure.get("quantity_family")),
                "unit": opt_str(measure.get("unit")),
                "allowed_operators": as_str_list(measure.get("allowed_operators")),
                "semantic_meaning": opt_str(measure.get("semantic_meaning")),
            }))

    # Artifact。
    artifact_path = rulecard_dir / RULECARD_FILES["artifact_semantics_registry"]
    if artifact_path.is_file():
        audit.record_source(artifact_path.name)
        for artifact in _load_json(artifact_path).get("artifacts", []) or []:
            artifact_key = opt_str(artifact.get("artifact_key"))
            if artifact_key is None:
                continue
            batch.add_node(NodeSpec("Artifact", "artifact_key", artifact_key, {
                "artifact_family": opt_str(artifact.get("artifact_family")),
                "semantic_meaning": opt_str(artifact.get("semantic_meaning")),
            }))

    # ProjectionRuntimeMapping（spec §6.4.2 canonicalization 别名传输源）。
    # DEBT-040 修复：此文件此前只在 RULECARD_FILES 登记、从未被灌，导致 slot/measure
    # 别名永远到不了 RuleSlice.retrieval_policy，触发器按裸名查带前缀事实必 miss。
    # 嵌套 dict 存为 JSON 字符串属性（Neo4j 属性不支持嵌套 map），检索侧解析。
    mapping_path = rulecard_dir / RULECARD_FILES["projection_runtime_mapping"]
    if mapping_path.is_file():
        audit.record_source(mapping_path.name)
        mapping_doc = _load_json(mapping_path)
        mapping_version = opt_str(mapping_doc.get("version")) or "projection_runtime_mapping_v1"
        batch.add_node(NodeSpec("ProjectionRuntimeMapping", "version", mapping_version, {
            "slot_aliases_json": json.dumps(
                mapping_doc.get("slot_aliases") or {}, ensure_ascii=False, sort_keys=True
            ),
            "measure_aliases_json": json.dumps(
                mapping_doc.get("measure_aliases") or {}, ensure_ascii=False, sort_keys=True
            ),
            # DEBT-049 Phase3 U2：method 别名分组表 {canonical:[alias...]}（检索/闭包侧
            # 反转全展开成运行态 {alias→canonical} 用；_ 注释键剔除）。
            "method_aliases_json": json.dumps(
                {
                    k: v
                    for k, v in (mapping_doc.get("method_aliases") or {}).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-040 ②：W0 词汇→规范限定符值对照（检索侧充实事实 qualifiers 用）。
            "qualifier_value_aliases_json": json.dumps(
                {
                    k: v
                    for k, v in (mapping_doc.get("qualifier_value_aliases") or {}).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-047：subject 词桥（适用性规则 3 的组件类匹配用）。
            "subject_component_crosswalk_json": json.dumps(
                {
                    k: v
                    for k, v in (mapping_doc.get("subject_component_crosswalk") or {}).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-049 第四波件甲 A1'：风险槽语义桥派生表（检索侧布尔行派生用）。
            "risk_slot_derivations_json": json.dumps(
                {
                    k: v
                    for k, v in (
                        mapping_doc.get("risk_slot_derivations") or {}
                    ).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-049 第四波件甲 A2：风险槽→risk_class_key 盖章表（检索侧消费）。
            "risk_slot_class_keys_json": json.dumps(
                {
                    k: v
                    for k, v in (
                        mapping_doc.get("risk_slot_class_keys") or {}
                    ).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-049 第二波：组件类目→成员表（检索侧 fragment 级类目行派生用）。
            "component_category_members_json": json.dumps(
                {
                    k: v
                    for k, v in (
                        mapping_doc.get("component_category_members") or {}
                    ).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # DEBT-049 B 类：缺陷类组合桥（成员缺陷类 ∧ 组件类 → 目标缺陷类，双极派生）。
            "defect_class_combination_bridges_json": json.dumps(
                [
                    b
                    for b in (mapping_doc.get("defect_class_combination_bridges") or [])
                    if isinstance(b, dict)
                ],
                ensure_ascii=False, sort_keys=True,
            ),
            # slot_targets 段（2026-07-27 接线：此前查询 FACT_SLOT_TARGETS 取该属性
            # 而 loader 从未写 → 恒 null → lookup_rule 通用派生空转且不报错）。
            # 检索侧只消费 lookup_rule；owning_interfaces 一并搬运（原样传输，
            # 消费与否由检索侧裁定）。
            "slot_targets_json": json.dumps(
                {
                    k: v
                    for k, v in (mapping_doc.get("slot_targets") or {}).items()
                    if not k.startswith("_")
                },
                ensure_ascii=False, sort_keys=True,
            ),
            # 🔴 2026-07-27 codex 审核门 P1-C：卡侧「被请求限定符」组合表。
            # `derive_slot_target_lookup_rule_facts` 的形态二子句
            # （value_mode=contains_requested_qualifier）**必须**拿到它才能求值，
            # 而生产路径此前固定传空 dict ⇒ 求值器因缺 `actor_role_key` 直接跳过目标槽
            # ⇒ 采集函数写好、导出好，全仓只有测试在调（第九个「登记了没接线」）。
            # 载体选 ProjectionRuntimeMapping 同节点：它已经是 slot_targets 的运输节点，
            # 两张表天生配对（一张说"目标槽怎么推"、一张说"卡侧按什么限定符要"）。
            "slot_target_requested_qualifiers_json": json.dumps(
                _harvest_requested_qualifiers(rulecard_dir),
                ensure_ascii=False, sort_keys=True,
            ),
        }))

    # TimeAnchor。
    anchor_path = rulecard_dir / RULECARD_FILES["time_anchor_registry"]
    if anchor_path.is_file():
        audit.record_source(anchor_path.name)
        for anchor in _load_json(anchor_path).get("time_anchors", []) or []:
            time_anchor_key = opt_str(anchor.get("time_anchor_key"))
            if time_anchor_key is None:
                continue
            batch.add_node(NodeSpec("TimeAnchor", "time_anchor_key", time_anchor_key, {
                "semantic_meaning": opt_str(anchor.get("semantic_meaning")),
            }))

    # VocabularyTerm（从 controlled_vocabularies 的 {name: [value...]} 展平）。
    vocab_path = rulecard_dir / RULECARD_FILES["controlled_vocabularies"]
    if vocab_path.is_file():
        audit.record_source(vocab_path.name)
        vocabularies = _load_json(vocab_path).get("vocabularies", {}) or {}
        for vocab_name, values in vocabularies.items():
            for value in values or []:
                vocab_id = f"{vocab_name}::{value}"
                batch.add_node(NodeSpec("VocabularyTerm", "vocab_id", vocab_id, {
                    "vocabulary_name": vocab_name,
                    "value": value,
                }))

    # ExceptionDefinition（来自 exception_definition_index.json）。
    edi_path = rulecard_dir / RULECARD_FILES["exception_definition_index"]
    if edi_path.is_file():
        audit.record_source(edi_path.name)
        edi = _load_json(edi_path)
        for entry in (edi.get("definitions", []) or []) + (edi.get("exceptions", []) or []):
            definition_id = opt_str(entry.get("definition_id")) or opt_str(entry.get("exception_id"))
            if definition_id is None:
                continue
            batch.add_node(NodeSpec("ExceptionDefinition", "definition_id", definition_id, {
                "term_key": opt_str(entry.get("term_key")),
                "definition_text": opt_str(entry.get("definition_text")),
                "scope_note": opt_str(entry.get("scope_note")),
                "source_quote_refs": as_str_list(entry.get("source_quote_refs")),
                "family_id": opt_str(entry.get("family_id")),
                "rule_card_id": opt_str(entry.get("rule_card_id")),
            }))

    return batch


# ===========================================================================
# §4.3.2 bundle + 顶层编排
# ===========================================================================
def build_rulecard_bundle_node(
    manifest: Dict[str, Any],
    card_count: int,
    family_count: int,
    loaded_at: str,
) -> NodeSpec:
    """manifest.json → (:RuleCardBundle) 节点（spec §4.3.2）。"""
    bundle_id = opt_str(manifest.get("bundle_id")) or "rulecard_v2.mbis_cop_2023"
    source_docs = manifest.get("source_documents", []) or []
    source_document_id = (
        opt_str(source_docs[0].get("source_document_id")) if source_docs else None
    )
    canonical_file = (
        opt_str(source_docs[0].get("canonical_file")) if source_docs else None
    )
    props = {
        "schema_version": opt_str(manifest.get("schema_version")),
        "source_document_id": source_document_id,
        "canonical_file": canonical_file,
        "card_count": card_count,
        "family_count": family_count,
        "loaded_at": loaded_at,
    }
    return NodeSpec("RuleCardBundle", "bundle_id", bundle_id, props)


def build_rulecard_graph(
    rulecard_dir: Path,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> RuleCardLoadResult:
    """把 rule_card v2 目录转换为法规-Skills 侧 GraphBatch（纯转换，不写 Neo4j）。

    本函数是 rulecard loader 的可单测核心。

    Args:
        rulecard_dir: rule_card v2 目录（含 rule_cards.json 等）。
        loaded_at: ISO 时间戳。
        audit: 审计记录器。

    Returns:
        RuleCardLoadResult。
    """
    audit = audit or AuditLog()
    result = RuleCardLoadResult(batch=GraphBatch(), audit=audit)

    # --- registry 先建（card 子结构的桥接边端点）---
    result.batch.extend(build_registry_graph(rulecard_dir, audit))

    # --- family_index.json → RuleFamily ---
    family_path = rulecard_dir / RULECARD_FILES["family_index"]
    families: List[Dict[str, Any]] = []
    if family_path.is_file():
        audit.record_source(family_path.name)
        families = _load_json(family_path).get("families", []) or []
        for family in families:
            if not isinstance(family, dict) or not family.get("family_id"):
                continue
            result.batch.add_node(build_rule_family_node(family))
            result.family_count += 1
    else:
        audit.warn("family_index.json not found")

    # --- rule_cards.json → RuleCard + 全部子结构 ---
    cards_path = rulecard_dir / RULECARD_FILES["rule_cards"]
    cards: List[Dict[str, Any]] = []
    if cards_path.is_file():
        audit.record_source(cards_path.name)
        rule_cards_doc = _load_json(cards_path)
        cards = rule_cards_doc.get("cards", []) or []
        _seen_card_ids: set = set()
        for card in cards:
            if not isinstance(card, dict) or not card.get("rule_card_id"):
                continue
            rule_card_id = card["rule_card_id"]
            # P1-4:无条件全卡包 rule_card_id 唯一(不依赖 DEBT-065 资产存在)——重复 ID 字典
            # 覆盖会让授权只验证最后一张卡却作用于合并义务(复审 P1-4 根因)。
            if rule_card_id in _seen_card_ids:
                raise ValueError(f"卡包内重复 rule_card_id: {rule_card_id}(P1-4 全卡包唯一)")
            _seen_card_ids.add(rule_card_id)
            # P1-4 收尾:无条件每卡单组件检查——卡内所有 component_type_key 值(across
            # slot_role_map/threshold_regimes/trigger_conditions)必须一致,>1 个不同值 → hard-fail。
            # 此检查不依赖 DEBT-065 类型格/授权表资产存在,覆盖全卡包(复审 P1-4 根因)。
            from ..closure.component_lattice import _card_component_values
            _card_ct_vals = _card_component_values(card)
            if len(_card_ct_vals) > 1:
                raise ValueError(
                    f"卡 {rule_card_id} 包含多个 component_type_key 值: "
                    f"{sorted(_card_ct_vals)}(P1-4 每卡单组件无条件检查)"
                )
            family_id = opt_str(card.get("family_id"))

            result.batch.add_node(build_rule_card_node(card))
            result.card_count += 1

            # RuleFamily-HAS_RULE_CARD->RuleCard。
            if family_id:
                result.batch.add_edge(EdgeSpec(
                    "RuleFamily", "family_id", family_id,
                    "HAS_RULE_CARD",
                    "RuleCard", "rule_card_id", rule_card_id,
                ))

            # 子结构（注意 source_quote 在 trigger / threshold 引用之前建）。
            result.batch.extend(build_source_quote_nodes(card, audit))
            result.batch.extend(build_applicability_node(card))
            result.batch.extend(build_slot_ref_nodes(card))
            result.batch.extend(build_trigger_nodes(card))
            result.batch.extend(build_threshold_nodes(card, audit))
            result.batch.extend(build_workflow_operand_nodes(card))
            result.batch.extend(build_obligation_nodes(card))
            result.batch.extend(build_obligation_edges(card, audit))
            result.batch.extend(build_evidence_requirement_nodes(card))
            result.batch.extend(build_definition_nodes(card))

            # G-003：每张卡必须有 ApplicabilityPredicate + ObligationNode。
            obligation_nodes = (card.get("obligation_graph", {}) or {}).get("nodes", []) or []
            raise_if_failed(gate_g003_rulecard_child_completeness(
                rule_card_id,
                has_applicability=bool(card.get("applicability")),
                has_obligation_node=len(obligation_nodes) > 0,
            ))
            # G-005：obligation edges 保留校验。
            upstream_edges = (card.get("obligation_graph", {}) or {}).get("edges", []) or []
            loaded_edges = sum(
                1 for n in result.batch.nodes
                if n.label == "ObligationEdge" and n.props.get("rule_card_id") == rule_card_id
            )
            raise_if_failed(gate_g005_obligation_edge_preservation(
                rule_card_id, len(upstream_edges), loaded_edges,
            ))

            # CARD_NEIGHBOR_OF + family-level NEIGHBOR_OF 聚合见 _link_neighbors。
            _link_card_neighbors(result.batch, rule_card_id, family_id, card)

            # source_section → clause 解析（§4.3.4）。
            _link_source_section(result.batch, rule_card_id, card, audit)
    else:
        audit.warn("rule_cards.json not found")

    # --- family-level NEIGHBOR_OF 聚合 ---
    _aggregate_family_neighbors(result.batch, cards)

    # --- manifest.json → RuleCardBundle ---
    manifest_path = rulecard_dir / RULECARD_FILES["manifest"]
    if manifest_path.is_file():
        audit.record_source(manifest_path.name)
        manifest = _load_json(manifest_path)
        bundle_node = build_rulecard_bundle_node(
            manifest, result.card_count, result.family_count, loaded_at
        )
        result.batch.add_node(bundle_node)
        result.bundle_id = bundle_node.key_value
        # RuleCardBundle-HAS_RULE_FAMILY / HAS_RULE_CARD。
        for family in families:
            if isinstance(family, dict) and family.get("family_id"):
                result.batch.add_edge(EdgeSpec(
                    "RuleCardBundle", "bundle_id", result.bundle_id,
                    "HAS_RULE_FAMILY",
                    "RuleFamily", "family_id", family["family_id"],
                ))
        for card in cards:
            if isinstance(card, dict) and card.get("rule_card_id"):
                result.batch.add_edge(EdgeSpec(
                    "RuleCardBundle", "bundle_id", result.bundle_id,
                    "HAS_RULE_CARD",
                    "RuleCard", "rule_card_id", card["rule_card_id"],
                ))
    else:
        audit.warn("manifest.json not found")

    # --- DEBT-065 第一波:组件类型格 + 精确目标授权表(共享本体消费侧运输)---
    _load_component_lattice_and_authorizations(result, cards, rulecard_dir, audit)

    return result


def _load_component_lattice_and_authorizations(
    result, cards, rulecard_dir, audit
) -> None:
    """DEBT-065:灌 component_type_lattice + exact_fragment_target_authorizations 进 KG。

    ingest 时(§1.1 hard-fail)用 closure.component_lattice 验证:lattice 双快照哈希/二分/
    disjoint,授权表 bundle/单叶目标/evidence 格式。授权表条目级 stale(指纹+修订 vs **原始卡**)
    在此消解——loader 有原始 rule_cards.json,产出验证过的 {rule_card_id: target},检索侧只按
    id 查(绕开 KG 重建 DTO 与 card_fingerprint 口径分歧)。类型格资产缺席时明确拒绝灌库。
    """
    from ..closure.component_lattice import (
        LatticeIngestError, load_authorizations, load_component_lattice,
    )

    lattice_path = rulecard_dir / RULECARD_FILES["component_type_lattice"]
    if not lattice_path.is_file():
        raise LatticeIngestError(
            f"类型格派生物缺失：{lattice_path}。直接灌库已拒绝，不能在缺少"
            "组件类型格时静默完成。先运行："
            "python agent_v1/scripts/check_rulecard_derived_release.py --rebuild，"
            "再运行不带 --rebuild 的发布检查确认派生链闭合。"
        )
    audit.record_source(lattice_path.name)
    lattice_doc = _load_json(lattice_path)
    # P1-3:类型格资产在场但清单缺失(bundle_id 未加载)→ 强失败(不得让错误卡包类型格
    # 经 None 绕过配套校验入图)。expected_bundle_id 由此保证传入非 None。
    if not result.bundle_id:
        raise LatticeIngestError(
            "类型格资产在场但 bundle_id 缺失(manifest 未加载)——P1-3 配套校验强失败"
        )
    vocab_path = rulecard_dir / RULECARD_FILES["controlled_vocabularies"]
    ct_domain = (
        (_load_json(vocab_path).get("vocabularies") or {}).get("component_type_key") or []
        if vocab_path.is_file() else []
    )
    mapping_path = rulecard_dir / RULECARD_FILES["projection_runtime_mapping"]
    mapping_doc = _load_json(mapping_path) if mapping_path.is_file() else {}
    alias_map = (mapping_doc.get("qualifier_value_aliases") or {}).get("component_type_key") or {}
    # ingest 验证:资产坏 → LatticeIngestError → 批不启动(§1.1 hard-fail)
    lattice_obj = load_component_lattice(
        lattice_doc, ct_domain, alias_map, expected_bundle_id=result.bundle_id,
    )
    result.batch.add_node(NodeSpec(
        "ComponentTypeLattice", "version", opt_str(lattice_doc.get("version")) or "component_type_lattice.v1",
        {
            "lattice_json": json.dumps(lattice_doc, ensure_ascii=False, sort_keys=True),
            # P1-2:必须与授权表同源。**漏写这条会让三方同源校验恒失败**
            # (`rule_retriever` 读回 None → `len(_bundle_ids) != 3`),
            # 于是类型格与授权表被移出 policy、组件结构早退被保守关闭——
            # 表现为「外墙片段上的樓柱条款」判不了结构性 NA 只能 blocked,
            # 且**不报错**。2026-07-27 实测坐实该属性自始缺失。
            "rulecard_bundle_id": result.bundle_id,
        },
    ))

    auth_path = rulecard_dir / RULECARD_FILES["exact_fragment_target_authorizations"]
    if not auth_path.is_file() or not result.bundle_id:
        return
    audit.record_source(auth_path.name)
    auth_doc = _load_json(auth_path)
    # P1-4:卡标识唯一——字典静默覆盖会让授权只验证最后一张卡却作用于合并义务。
    cards_by_id: Dict[str, Any] = {}
    for c in cards:
        if not isinstance(c, dict) or not c.get("rule_card_id"):
            continue
        rid = c["rule_card_id"]
        if rid in cards_by_id:
            raise LatticeIngestError(f"卡包内重复 rule_card_id: {rid}")
        cards_by_id[rid] = c
    auth_obj = load_authorizations(
        auth_doc, result.bundle_id, lattice_obj.leaf_types, cards_by_id=cards_by_id,
    )
    validated: Dict[str, Any] = {}
    for rid in auth_obj.by_id:
        card = cards_by_id.get(rid)
        if card is None:
            continue  # stale_card_binding:卡不存在于卡包
        target = auth_obj.authorized_target(card)  # 指纹+修订校验 → None 则 stale
        if target is not None:
            # P1-2:授权运输保留指纹供审计/复核——validator 取 entry["target"]。
            entry = auth_obj.by_id[rid]
            validated[rid] = {
                "target": target,
                "card_content_sha256": entry.card_content_sha256,
            }
    result.batch.add_node(NodeSpec(
        "ExactFragmentTargetAuthorizations", "version",
        opt_str(auth_doc.get("version")) or "exact_fragment_target_authorizations.v1",
        {
            "authorized_targets_json": json.dumps(validated, ensure_ascii=False, sort_keys=True),
            # P1-2:绑定同一卡包 bundle_id(与 ComponentTypeLattice 同源)。
            "rulecard_bundle_id": result.bundle_id,
        },
    ))


def _link_card_neighbors(
    batch: GraphBatch, rule_card_id: str, family_id: Optional[str], card: Dict[str, Any]
) -> None:
    """建 RuleCard-CARD_NEIGHBOR_OF->RuleFamily 边（spec §3.4.2 / §4.3.3）。"""
    for neighbor_family_id in as_str_list(card.get("neighbor_families")):
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "CARD_NEIGHBOR_OF",
            "RuleFamily", "family_id", neighbor_family_id,
        ))


def _aggregate_family_neighbors(batch: GraphBatch, cards: List[Dict[str, Any]]) -> None:
    """按 (source_family, neighbor_family) 聚合 family-level NEIGHBOR_OF 边（spec §3.4.2）。

    card_count 为该 pair 在所有卡 neighbor_families[] 中的出现次数。
    """
    pair_counts: Dict[tuple[str, str], int] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        source_family = opt_str(card.get("family_id"))
        if source_family is None:
            continue
        for neighbor_family in as_str_list(card.get("neighbor_families")):
            key = (source_family, neighbor_family)
            pair_counts[key] = pair_counts.get(key, 0) + 1
    for (source_family, neighbor_family), count in sorted(pair_counts.items()):
        batch.add_edge(EdgeSpec(
            "RuleFamily", "family_id", source_family,
            "NEIGHBOR_OF",
            "RuleFamily", "family_id", neighbor_family,
            {"source": "card_neighbor_families", "card_count": count},
        ))


def _link_source_section(
    batch: GraphBatch, rule_card_id: str, card: Dict[str, Any], audit: AuditLog
) -> None:
    """建 RuleCard-SOURCED_FROM_DOCUMENT / SOURCED_FROM_CLAUSE 边（spec §4.3.4）。

    source_section.section_id 经 normalize_section_id 归一化后拼 clause_id。
    无法匹配时不建 SOURCED_FROM_CLAUSE，记 warning（quality gate 不 fail）。
    section→clause 是否真命中由写入期 MATCH 端点决定。
    """
    document_id = opt_str(card.get("source_document_id"))
    if document_id:
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "SOURCED_FROM_DOCUMENT",
            "RegulationDocument", "document_id", document_id,
        ))
    for section in card.get("source_section", []) or []:
        if not isinstance(section, dict):
            continue
        section_id = opt_str(section.get("section_id"))
        if section_id is None or document_id is None:
            continue
        normalized = normalize_section_id(section_id)
        clause_id = f"{document_id}::{normalized}"
        batch.add_edge(EdgeSpec(
            "RuleCard", "rule_card_id", rule_card_id,
            "SOURCED_FROM_CLAUSE",
            "RegulationClause", "clause_id", clause_id,
        ))


def load_rulecard_kg(
    rulecard_dir: Path,
    client: Any,
    loaded_at: str,
    audit: Optional[AuditLog] = None,
) -> RuleCardLoadResult:
    """把 rule_card KG 写入 Neo4j（spec §4.3）。

    Args:
        rulecard_dir: rule_card v2 目录。
        client: `Neo4jClient` 实例。
        loaded_at: ISO 时间戳。
        audit: 审计记录器。

    Returns:
        RuleCardLoadResult（已写入）。
    """
    from evo_agent_baseline.ingest._graphspec import compile_batch

    result = build_rulecard_graph(rulecard_dir, loaded_at, audit)
    client.write_many(compile_batch(result.batch))
    return result


__all__ = [
    "RULECARD_FILES",
    "ALLOWED_OBLIGATION_EDGE_RELATIONS",
    "RuleCardLoadResult",
    "normalize_section_id",
    "build_rule_card_node",
    "build_rule_family_node",
    "build_source_quote_nodes",
    "build_applicability_node",
    "build_trigger_nodes",
    "build_slot_ref_nodes",
    "build_threshold_nodes",
    "build_obligation_nodes",
    "build_obligation_edges",
    "build_workflow_operand_nodes",
    "build_evidence_requirement_nodes",
    "build_definition_nodes",
    "build_registry_graph",
    "build_rulecard_bundle_node",
    "build_rulecard_graph",
    "load_rulecard_kg",
]
