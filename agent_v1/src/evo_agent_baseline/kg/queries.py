"""KG-RAG 检索 Cypher 查询库（spec §5.3 + §5.4）。

本模块只承载 Cypher 查询字符串与参数构造，不执行。执行交给
`kg.neo4j_client.Neo4jClient.read`；查询结果的 DTO 装配交给 `retrieval/`。

实现的 spec 章节：
- §5.3 Fact KG-RAG 检索：building shell / fragment-component-location 子图 /
  conditions-states / measurements / sidecar entries；
- §5.4 Rule KG-RAG 检索：slot-driven / measure-driven / applicability-driven
  候选卡 + §5.4.3 graph expansion 一跳展开。

所有查询都是 evo-agent blind safe：只 MATCH 事实侧 / 法规-Skills 侧 label，
绝不触碰 W2 NormativeProjection 等 label（spec §2.2.3）。
"""

from __future__ import annotations

from typing import Any, Dict, List

# ===========================================================================
# §5.3 Fact KG-RAG 检索查询
# ===========================================================================

# §5.3.1 building shell —— 取建筑 + 所属 world。
FACT_BUILDING_SHELL = """
MATCH (b:Building {building_id: $building_id})<-[:HAS_BUILDING]-(w:World)
RETURN w AS world, b AS building
""".strip()

# §5.3.2 fragment / component / location 子图。
FACT_FRAGMENT_SUBGRAPH = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:OF_COMPONENT]->(c:Component)
OPTIONAL MATCH (f)-[:AT_LOCATION]->(l:Location)
RETURN f AS fragment, c AS component, l AS location
ORDER BY f.fragment_id
""".strip()

# §5.3.2 补：coverage relations —— scope.component.* 覆盖范围状态。
# DEBT-040 修复：coverage_relations.parquet 早已声明为事实源并灌成 CoverageRelation
# 节点，但检索从未消费，触发器查 scope.component.* 恒 missing。
FACT_COVERAGE_RELATIONS = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)-[:HAS_COVERAGE]->(cvr:CoverageRelation)
RETURN cvr AS coverage_relation, f.fragment_id AS fragment_id
ORDER BY cvr.coverage_id
""".strip()

# DEBT-040 ②：限定符值对照（检索侧充实事实 qualifiers 用；同节点、单独取该属性）。
FACT_QUALIFIER_VALUE_ALIASES = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.qualifier_value_aliases_json AS qualifier_value_aliases_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# DEBT-049 Phase3 U2：method 别名分组表（检索侧 verification.test.performed 派生 canonicalize
# 用；同节点、单独取该属性）。暗部署期节点尚无此属性→返回 null→检索侧按空表 identity 归一。
FACT_METHOD_ALIASES = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.method_aliases_json AS method_aliases_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# 缺陷类组合桥（检索侧双极派生用；同节点、单独取该属性）。
FACT_DEFECT_COMBINATION_BRIDGES = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.defect_class_combination_bridges_json AS defect_class_combination_bridges_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# 组件类目→成员表（DEBT-049 第二波：检索侧 fragment 级类目行派生用；同节点属性）。
FACT_COMPONENT_CATEGORY_MEMBERS = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.component_category_members_json AS component_category_members_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# slot_targets 段（lookup_rule 通用派生用，2026-07-27 接线；同节点、单独取该属性）。
# ⚠️ 本注释原写「加载器尚未写该属性 ⇒ 暗部署」，**已过时**：同日
# `rulecard_loader.py:889` 已写 `slot_targets_json`，故重灌库后本查询取得到值、
# 派生是**活路径**。旧库（属性缺席）仍返回 null ⇒ 检索侧按空表无操作，不阻断。
# 🔴 活路径下的已知暴露：`derive_slot_target_lookup_rule_facts` 的「已有同名事实
# 就跳过」去重是**裸比**（未过别名归一），而 27 个 slot_targets 键里 10 个正是
# 别名表的键 ⇒ 对这 10 个恒不命中。真实批实测这 10 个当前派生 0 条、故尚未产生
# 双源；但 clause 一旦可满足即会双源。详见
# `agent_v1/tests/test_slot_alias_normalization_scan.py` 的 `_KNOWN_UNNORMALIZED`。
FACT_SLOT_TARGETS = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.slot_targets_json AS slot_targets_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# 卡侧「被请求限定符」组合表 {slot_id: [组合...]}（2026-07-27 P1-C 接线；同节点属性）。
# lookup_rule 形态二子句（contains_requested_qualifier）离了它无法求值——生产路径此前
# 固定传空 dict，等于该形态永不派生。属性缺席 → null → 检索侧退空表（暗部署，不阻断）。
FACT_SLOT_TARGET_REQUESTED_QUALIFIERS = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.slot_target_requested_qualifiers_json AS slot_target_requested_qualifiers_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# 风险槽→risk_class_key 盖章表 + 语义桥派生表（DEBT-049 第四波件甲；同节点属性）。
FACT_RISK_SLOT_CLASS_KEYS = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.risk_slot_class_keys_json AS risk_slot_class_keys_json,
       m.risk_slot_derivations_json AS risk_slot_derivations_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# §5.3.3 conditions / states —— driver / mechanism / condition / repair_assessment。
FACT_CONDITIONS_STATES = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:HAS_DRIVER_STATE]->(d:DriverState)
OPTIONAL MATCH (f)-[:HAS_MECHANISM_STATE]->(m:MechanismState)
OPTIONAL MATCH (f)-[:HAS_CONDITION]->(cond:ConditionState)
OPTIONAL MATCH (f)-[:HAS_REPAIR_ASSESSMENT]->(ra:RepairAssessmentState)
RETURN f.fragment_id AS fragment_id,
       collect(DISTINCT d) AS drivers,
       collect(DISTINCT m) AS mechanisms,
       collect(DISTINCT cond) AS conditions,
       collect(DISTINCT ra) AS repair_assessments
ORDER BY f.fragment_id
""".strip()

# §3.3.3 专项状态 —— drainage / ubw / fire_safety（挂在 Component 上）。
# spec §5.3 未单列查询块，但 FactPack 需要这些 carrier 事实，按 §3.3.3 关系补一条。
FACT_SPECIALIZED_STATES = """
MATCH (b:Building {building_id: $building_id})-[:HAS_COMPONENT]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_DRAINAGE_STATE]->(dr:DrainageState)
OPTIONAL MATCH (c)-[:HAS_UBW_STATE]->(ubw:UBWState)
OPTIONAL MATCH (c)-[:HAS_FIRE_SAFETY_STATE]->(fs:FireSafetyState)
RETURN c.component_id AS component_id,
       collect(DISTINCT dr) AS drainage_states,
       collect(DISTINCT ubw) AS ubw_states,
       collect(DISTINCT fs) AS fire_safety_states
ORDER BY c.component_id
""".strip()

# §3.3.2 ManifestationFlag —— 挂在 ConditionState 上的语义槽实现旗标。
FACT_MANIFESTATION_FLAGS = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
MATCH (f)-[:HAS_CONDITION]->(cond:ConditionState)
OPTIONAL MATCH (cond)-[:HAS_MANIFESTATION_FLAG]->(mf:ManifestationFlag)
RETURN cond.condition_id AS condition_id, collect(DISTINCT mf) AS manifestation_flags
ORDER BY cond.condition_id
""".strip()

# §5.3.4 measurements —— fragment-level。
FACT_FRAGMENT_MEASUREMENTS = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:HAS_MEASUREMENT]->(msr:Measurement)
RETURN f.fragment_id AS fragment_id, collect(DISTINCT msr) AS measurements
ORDER BY f.fragment_id
""".strip()

# §5.3.4 measurements —— component-level。
FACT_COMPONENT_MEASUREMENTS = """
MATCH (b:Building {building_id: $building_id})-[:HAS_COMPONENT]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_MEASUREMENT]->(msr:Measurement)
RETURN c.component_id AS component_id, collect(DISTINCT msr) AS measurements
ORDER BY c.component_id
""".strip()

# §5.3.4 measurements —— condition-level。
FACT_CONDITION_MEASUREMENTS = """
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
MATCH (f)-[:HAS_CONDITION]->(cond:ConditionState)
OPTIONAL MATCH (cond)-[:HAS_MEASUREMENT]->(msr:Measurement)
RETURN cond.condition_id AS condition_id, collect(DISTINCT msr) AS measurements
ORDER BY cond.condition_id
""".strip()

# §5.3.5 sidecar entries。
FACT_SIDECAR_ENTRIES = """
MATCH (b:Building {building_id: $building_id})<-[:HAS_BUILDING]-(w:World)
MATCH (w)-[:HAS_SIDECAR_RECORD]->(r:SidecarRuntimeRecord)-[:HAS_SIDECAR_ENTRY]->(e:SidecarEntry)
RETURN r.runtime_id AS runtime_id, e AS sidecar_entry
ORDER BY r.runtime_id, e.entry_type, e.sidecar_entry_id
""".strip()


# ===========================================================================
# §5.4 Rule KG-RAG 检索查询
# ===========================================================================

# §6.4.2 canonicalization 别名传输源（DEBT-040 修复：把 projection_runtime_mapping
# 的 slot/measure 别名带回 RuleSlice.retrieval_policy，供闭包 canonical_slot 用）。
RULE_PROJECTION_RUNTIME_MAPPING = """
MATCH (m:ProjectionRuntimeMapping)
RETURN m.version AS version,
       m.slot_aliases_json AS slot_aliases_json,
       m.measure_aliases_json AS measure_aliases_json,
       m.method_aliases_json AS method_aliases_json,
       m.qualifier_value_aliases_json AS qualifier_value_aliases_json,
       m.subject_component_crosswalk_json AS subject_component_crosswalk_json,
       m.component_category_members_json AS component_category_members_json
ORDER BY m.version DESC
LIMIT 1
""".strip()

# DEBT-065 第一波:组件类型格(共享本体,排斥关系)+ 精确目标授权表(loader 已验证并
# 产出 {rule_card_id: target})。TODO(多版本):v2.2 §2.4 要求运行期按精确版本键查询;
# v1 单版本先沿 mapping 的 ORDER BY version DESC LIMIT 1,多版本落地时改精确键(禁字典序)。
RULE_COMPONENT_TYPE_LATTICE = """
MATCH (l:ComponentTypeLattice)
RETURN l.version AS version, l.lattice_json AS lattice_json,
       l.rulecard_bundle_id AS rulecard_bundle_id
ORDER BY l.version DESC
LIMIT 1
""".strip()

RULE_EXACT_FRAGMENT_TARGET_AUTHORIZATIONS = """
MATCH (a:ExactFragmentTargetAuthorizations)
RETURN a.version AS version, a.authorized_targets_json AS authorized_targets_json,
       a.rulecard_bundle_id AS rulecard_bundle_id
ORDER BY a.version DESC
LIMIT 1
""".strip()

# §5.4.1 slot-driven candidate cards —— 从 FactPack 的 slot_id 集合查命中卡。
RULE_SLOT_DRIVEN_CARDS = """
MATCH (s:SemanticSlot)<-[:REFERS_TO_SEMANTIC_SLOT]-(sr:SlotRef)<-[:HAS_SLOT_REF]-(rc:RuleCard)
WHERE s.slot_id IN $slot_ids
RETURN rc.rule_card_id AS rule_card_id, count(sr) AS slot_hits
ORDER BY slot_hits DESC, rc.rule_card_id
""".strip()

# §5.4.1 measure-driven candidate cards。
RULE_MEASURE_DRIVEN_CARDS = """
MATCH (m:Measure)<-[:REFERS_TO_MEASURE]-(t:RuleThreshold)<-[:HAS_THRESHOLD]-(rc:RuleCard)
WHERE m.measure_key IN $measure_keys
RETURN rc.rule_card_id AS rule_card_id, count(t) AS threshold_hits
ORDER BY threshold_hits DESC, rc.rule_card_id
""".strip()

# §5.4.2 applicability-driven candidate cards —— building scope。
RULE_APPLICABILITY_BUILDING_SCOPE = """
MATCH (fam:RuleFamily)-[:HAS_RULE_CARD]->(rc:RuleCard)-[:HAS_APPLICABILITY]->(ap:ApplicabilityPredicate)
WHERE ap.regime = $regime
  AND (
    size(ap.building_scope) = 0 OR
    any(scope IN ap.building_scope WHERE scope IN $building_scope_tags)
  )
RETURN rc.rule_card_id AS rule_card_id, fam.family_id AS family_id
ORDER BY rc.rule_card_id
""".strip()

# §5.4.2 applicability-driven candidate cards —— component scope。
RULE_APPLICABILITY_COMPONENT_SCOPE = """
MATCH (rc:RuleCard)-[:HAS_APPLICABILITY]->(ap:ApplicabilityPredicate)
WHERE size(ap.component_scope) = 0
   OR any(x IN ap.component_scope WHERE x IN $component_scope_tags)
RETURN rc.rule_card_id AS rule_card_id
ORDER BY rc.rule_card_id
""".strip()

# §5.4.3 graph expansion —— 候选卡一跳展开，取回原嵌套 DTO 所需全部子结构。
RULE_GRAPH_EXPANSION = """
MATCH (rc:RuleCard)
WHERE rc.rule_card_id IN $candidate_rule_card_ids
OPTIONAL MATCH (rc)-[:HAS_SLOT_REF]->(sr:SlotRef)-[:REFERS_TO_SEMANTIC_SLOT]->(slot:SemanticSlot)
OPTIONAL MATCH (rc)-[:HAS_THRESHOLD]->(thr:RuleThreshold)-[:REFERS_TO_MEASURE]->(mea:Measure)
OPTIONAL MATCH (thr)-[:USES_TIME_ANCHOR]->(ta:TimeAnchor)
OPTIONAL MATCH (rc)-[:HAS_EVIDENCE_REQUIREMENT]->(er:EvidenceRequirement)
OPTIONAL MATCH (rc)-[:HAS_OBLIGATION_NODE]->(on:ObligationNode)
OPTIONAL MATCH (rc)-[:HAS_OBLIGATION_EDGE]->(oe:ObligationEdge)
OPTIONAL MATCH (on)-[:REQUIRES_ARTIFACT]->(wa:WorkflowArtifact)
OPTIONAL MATCH (on)-[:HAS_DEADLINE]->(wd:WorkflowDeadline)
OPTIONAL MATCH (on)-[:SENT_TO]->(wr:WorkflowRecipient)
OPTIONAL MATCH (rc)-[:HAS_TRIGGER]->(tc:TriggerCondition)
OPTIONAL MATCH (rc)-[:HAS_SOURCE_QUOTE]->(sq:SourceQuote)
OPTIONAL MATCH (rc)-[:HAS_APPLICABILITY]->(ap:ApplicabilityPredicate)
OPTIONAL MATCH (rc)-[:HAS_DEFINITION]->(definition:ExceptionDefinition)
RETURN rc AS rule_card,
       collect(DISTINCT sr) AS slot_refs,
       collect(DISTINCT slot) AS semantic_slots,
       collect(DISTINCT thr) AS thresholds,
       collect(DISTINCT mea) AS measures,
       collect(DISTINCT ta) AS time_anchors,
       collect(DISTINCT er) AS evidence_requirements,
       collect(DISTINCT on) AS obligation_nodes,
       collect(DISTINCT oe) AS obligation_edges,
       collect(DISTINCT wa) AS workflow_artifacts,
       collect(DISTINCT wd) AS workflow_deadlines,
       collect(DISTINCT wr) AS workflow_recipients,
       collect(DISTINCT tc) AS trigger_conditions,
       collect(DISTINCT sq) AS source_quotes,
       collect(DISTINCT ap) AS applicabilities,
       collect(DISTINCT definition) AS definitions
ORDER BY rc.rule_card_id
""".strip()

# rule family 元数据（候选卡所属 family）。
RULE_FAMILIES_BY_ID = """
MATCH (fam:RuleFamily)
WHERE fam.family_id IN $family_ids
RETURN fam AS rule_family
ORDER BY fam.family_id
""".strip()

# neighbor family 一跳展开（§5.4.4 排序的 neighbor_family_hit_count 用）。
RULE_NEIGHBOR_FAMILIES = """
MATCH (fam:RuleFamily)-[nb:NEIGHBOR_OF]->(neighbor:RuleFamily)
WHERE fam.family_id IN $family_ids
RETURN fam.family_id AS family_id,
       neighbor.family_id AS neighbor_family_id,
       nb.card_count AS card_count
ORDER BY fam.family_id, neighbor.family_id
""".strip()

# 法规原文全文检索（§5.4.4 source_clause_fulltext_score 用）。
REGULATION_CLAUSE_FULLTEXT = """
CALL db.index.fulltext.queryNodes('regulation_clause_text_ft', $query_text)
YIELD node, score
RETURN node.clause_id AS clause_id, node.document_id AS document_id, score
ORDER BY score DESC
LIMIT $limit
""".strip()

# rule_card 全文检索。
RULE_CARD_FULLTEXT = """
CALL db.index.fulltext.queryNodes('rule_card_text_ft', $query_text)
YIELD node, score
RETURN node.rule_card_id AS rule_card_id, score
ORDER BY score DESC
LIMIT $limit
""".strip()

# baseline 可用 Skill 检索（§3.5）。
SKILLS_BASELINE_ENABLED = """
MATCH (sk:Skill)
WHERE sk.allowed_in_baseline = true
OPTIONAL MATCH (sk)-[:HAS_TRIGGER]->(tr:SkillTrigger)
RETURN sk AS skill, collect(DISTINCT tr) AS triggers
ORDER BY sk.skill_id
""".strip()


# ===========================================================================
# 参数构造辅助
# ===========================================================================
def building_params(building_id: str) -> Dict[str, Any]:
    """构造 building 级查询参数。"""
    return {"building_id": building_id}


def slot_params(slot_ids: List[str]) -> Dict[str, Any]:
    """构造 slot-driven 检索参数。"""
    return {"slot_ids": list(slot_ids)}


def measure_params(measure_keys: List[str]) -> Dict[str, Any]:
    """构造 measure-driven 检索参数。"""
    return {"measure_keys": list(measure_keys)}


def applicability_building_params(
    regime: str, building_scope_tags: List[str]
) -> Dict[str, Any]:
    """构造 applicability building scope 检索参数。"""
    return {"regime": regime, "building_scope_tags": list(building_scope_tags)}


def applicability_component_params(component_scope_tags: List[str]) -> Dict[str, Any]:
    """构造 applicability component scope 检索参数。"""
    return {"component_scope_tags": list(component_scope_tags)}


def expansion_params(candidate_rule_card_ids: List[str]) -> Dict[str, Any]:
    """构造 graph expansion 检索参数。"""
    return {"candidate_rule_card_ids": list(candidate_rule_card_ids)}


def family_params(family_ids: List[str]) -> Dict[str, Any]:
    """构造 family 元数据检索参数。"""
    return {"family_ids": list(family_ids)}


def fulltext_params(query_text: str, limit: int = 50) -> Dict[str, Any]:
    """构造全文检索参数。"""
    return {"query_text": query_text, "limit": limit}


__all__ = [
    # Fact KG-RAG
    "FACT_BUILDING_SHELL",
    "FACT_FRAGMENT_SUBGRAPH",
    "FACT_COVERAGE_RELATIONS",
    "FACT_QUALIFIER_VALUE_ALIASES",
    "FACT_METHOD_ALIASES",
    "FACT_DEFECT_COMBINATION_BRIDGES",
    "FACT_CONDITIONS_STATES",
    "FACT_SPECIALIZED_STATES",
    "FACT_MANIFESTATION_FLAGS",
    "FACT_FRAGMENT_MEASUREMENTS",
    "FACT_COMPONENT_MEASUREMENTS",
    "FACT_CONDITION_MEASUREMENTS",
    "FACT_SIDECAR_ENTRIES",
    # Rule KG-RAG
    "RULE_SLOT_DRIVEN_CARDS",
    "RULE_MEASURE_DRIVEN_CARDS",
    "RULE_APPLICABILITY_BUILDING_SCOPE",
    "RULE_APPLICABILITY_COMPONENT_SCOPE",
    "RULE_GRAPH_EXPANSION",
    "RULE_FAMILIES_BY_ID",
    "RULE_NEIGHBOR_FAMILIES",
    "REGULATION_CLAUSE_FULLTEXT",
    "RULE_CARD_FULLTEXT",
    "SKILLS_BASELINE_ENABLED",
    # 参数构造
    "building_params",
    "slot_params",
    "measure_params",
    "applicability_building_params",
    "applicability_component_params",
    "expansion_params",
    "family_params",
    "fulltext_params",
]
