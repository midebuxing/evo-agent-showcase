"""Neo4j 约束 / 索引 / 全文索引 DDL（spec §3.7）。

本模块只生成 Cypher DDL 语句字符串，不执行；执行交给 `kg.neo4j_client`。
所有 DDL 用 `IF NOT EXISTS` 保证幂等。

spec→code 单向：约束 / 索引 / 全文索引清单逐条照搬 spec §3.7.1 ~ §3.7.3，
不增不减。可选向量索引（§3.7.4）单独提供，baseline 默认不启用。

术语对照（中英）：
- constraint（约束）—— 唯一性约束，保证主键不重复；
- btree index（B 树索引）—— 普通属性索引，加速等值 / 范围查询；
- fulltext index（全文索引）—— 文本检索索引，支持法规原文 / rule card 文本检索。
"""

from __future__ import annotations

from typing import List

# ===========================================================================
# §3.7.1 唯一性约束（constraints）
# ===========================================================================
# 每条对应 spec §3.7.1 代码块中的一条 CREATE CONSTRAINT。
CONSTRAINTS: List[str] = [
    # 事实侧核心节点
    "CREATE CONSTRAINT world_id_unique IF NOT EXISTS "
    "FOR (n:World) REQUIRE n.world_id IS UNIQUE",
    "CREATE CONSTRAINT building_id_unique IF NOT EXISTS "
    "FOR (n:Building) REQUIRE n.building_id IS UNIQUE",
    "CREATE CONSTRAINT component_id_unique IF NOT EXISTS "
    "FOR (n:Component) REQUIRE n.component_id IS UNIQUE",
    "CREATE CONSTRAINT location_id_unique IF NOT EXISTS "
    "FOR (n:Location) REQUIRE n.location_id IS UNIQUE",
    "CREATE CONSTRAINT fragment_id_unique IF NOT EXISTS "
    "FOR (n:Fragment) REQUIRE n.fragment_id IS UNIQUE",
    "CREATE CONSTRAINT coverage_id_unique IF NOT EXISTS "
    "FOR (n:CoverageRelation) REQUIRE n.coverage_id IS UNIQUE",
    "CREATE CONSTRAINT measurement_id_unique IF NOT EXISTS "
    "FOR (n:Measurement) REQUIRE n.measurement_id IS UNIQUE",
    "CREATE CONSTRAINT sidecar_runtime_id_unique IF NOT EXISTS "
    "FOR (n:SidecarRuntimeRecord) REQUIRE n.runtime_id IS UNIQUE",
    "CREATE CONSTRAINT sidecar_entry_id_unique IF NOT EXISTS "
    "FOR (n:SidecarEntry) REQUIRE n.sidecar_entry_id IS UNIQUE",
    # 法规-Skills 侧节点
    "CREATE CONSTRAINT rule_card_id_unique IF NOT EXISTS "
    "FOR (n:RuleCard) REQUIRE n.rule_card_id IS UNIQUE",
    "CREATE CONSTRAINT rule_family_id_unique IF NOT EXISTS "
    "FOR (n:RuleFamily) REQUIRE n.family_id IS UNIQUE",
    "CREATE CONSTRAINT source_quote_id_unique IF NOT EXISTS "
    "FOR (n:SourceQuote) REQUIRE n.source_quote_id IS UNIQUE",
    "CREATE CONSTRAINT slot_ref_id_unique IF NOT EXISTS "
    "FOR (n:SlotRef) REQUIRE n.slot_ref_id IS UNIQUE",
    "CREATE CONSTRAINT trigger_condition_id_unique IF NOT EXISTS "
    "FOR (n:TriggerCondition) REQUIRE n.trigger_condition_id IS UNIQUE",
    "CREATE CONSTRAINT rule_threshold_id_unique IF NOT EXISTS "
    "FOR (n:RuleThreshold) REQUIRE n.threshold_regime_id IS UNIQUE",
    "CREATE CONSTRAINT obligation_node_id_unique IF NOT EXISTS "
    "FOR (n:ObligationNode) REQUIRE n.obligation_node_id IS UNIQUE",
    "CREATE CONSTRAINT obligation_edge_id_unique IF NOT EXISTS "
    "FOR (n:ObligationEdge) REQUIRE n.obligation_edge_id IS UNIQUE",
    "CREATE CONSTRAINT evidence_requirement_id_unique IF NOT EXISTS "
    "FOR (n:EvidenceRequirement) REQUIRE n.evidence_requirement_id IS UNIQUE",
    "CREATE CONSTRAINT semantic_slot_id_unique IF NOT EXISTS "
    "FOR (n:SemanticSlot) REQUIRE n.slot_id IS UNIQUE",
    "CREATE CONSTRAINT measure_key_unique IF NOT EXISTS "
    "FOR (n:Measure) REQUIRE n.measure_key IS UNIQUE",
    "CREATE CONSTRAINT artifact_key_unique IF NOT EXISTS "
    "FOR (n:Artifact) REQUIRE n.artifact_key IS UNIQUE",
    "CREATE CONSTRAINT time_anchor_key_unique IF NOT EXISTS "
    "FOR (n:TimeAnchor) REQUIRE n.time_anchor_key IS UNIQUE",
    "CREATE CONSTRAINT regulation_document_id_unique IF NOT EXISTS "
    "FOR (n:RegulationDocument) REQUIRE n.document_id IS UNIQUE",
    "CREATE CONSTRAINT regulation_clause_id_unique IF NOT EXISTS "
    "FOR (n:RegulationClause) REQUIRE n.clause_id IS UNIQUE",
    "CREATE CONSTRAINT skill_id_unique IF NOT EXISTS "
    "FOR (n:Skill) REQUIRE n.skill_id IS UNIQUE",
    "CREATE CONSTRAINT skill_trigger_id_unique IF NOT EXISTS "
    "FOR (n:SkillTrigger) REQUIRE n.trigger_id IS UNIQUE",
]

# ===========================================================================
# §3.7.2 B 树索引（btree indexes）
# ===========================================================================
BTREE_INDEXES: List[str] = [
    "CREATE INDEX fragment_world_idx IF NOT EXISTS "
    "FOR (n:Fragment) ON (n.world_id)",
    "CREATE INDEX component_world_type_idx IF NOT EXISTS "
    "FOR (n:Component) ON (n.world_id, n.component_type)",
    "CREATE INDEX component_geometry_idx IF NOT EXISTS "
    "FOR (n:Component) ON (n.visible_area_m2, n.thickness_mm, n.length_m, n.width_m, n.height_m)",
    "CREATE INDEX location_world_class_idx IF NOT EXISTS "
    "FOR (n:Location) ON (n.world_id, n.location_class)",
    "CREATE INDEX measurement_world_slot_idx IF NOT EXISTS "
    "FOR (n:Measurement) ON (n.world_id, n.slot_id)",
    "CREATE INDEX measurement_target_ref_idx IF NOT EXISTS "
    "FOR (n:Measurement) ON (n.target_ref)",
    "CREATE INDEX sidecar_world_slot_idx IF NOT EXISTS "
    "FOR (n:SidecarEntry) ON (n.world_id, n.slot_id)",
    "CREATE INDEX condition_world_class_idx IF NOT EXISTS "
    "FOR (n:ConditionState) ON (n.world_id, n.condition_class)",
    "CREATE INDEX condition_severity_idx IF NOT EXISTS "
    "FOR (n:ConditionState) ON (n.world_id, n.severity_band, n.severity_index)",
    "CREATE INDEX rule_card_family_idx IF NOT EXISTS "
    "FOR (n:RuleCard) ON (n.family_id)",
    "CREATE INDEX rule_card_phase_subject_idx IF NOT EXISTS "
    "FOR (n:RuleCard) ON (n.phase, n.subject)",
    "CREATE INDEX rule_threshold_measure_idx IF NOT EXISTS "
    "FOR (n:RuleThreshold) ON (n.measure_key)",
    "CREATE INDEX rule_threshold_operator_idx IF NOT EXISTS "
    "FOR (n:RuleThreshold) ON (n.operator)",
    "CREATE INDEX slot_ref_slot_idx IF NOT EXISTS "
    "FOR (n:SlotRef) ON (n.slot_id)",
    "CREATE INDEX evidence_bucket_idx IF NOT EXISTS "
    "FOR (n:EvidenceRequirement) ON (n.bucket, n.kind)",
    "CREATE INDEX obligation_edge_relation_idx IF NOT EXISTS "
    "FOR (n:ObligationEdge) ON (n.relation)",
    "CREATE INDEX skill_status_idx IF NOT EXISTS "
    "FOR (n:Skill) ON (n.status, n.allowed_in_baseline)",
]

# ===========================================================================
# §3.7.3 全文索引（fulltext indexes）
# ===========================================================================
FULLTEXT_INDEXES: List[str] = [
    "CREATE FULLTEXT INDEX regulation_clause_text_ft IF NOT EXISTS "
    "FOR (n:RegulationClause) ON EACH [n.heading, n.text]",
    "CREATE FULLTEXT INDEX rule_card_text_ft IF NOT EXISTS "
    "FOR (n:RuleCard) ON EACH [n.normalized_rule_text, n.source_quote_texts]",
    "CREATE FULLTEXT INDEX skill_text_ft IF NOT EXISTS "
    "FOR (n:Skill) ON EACH [n.name, n.description, n.content_md, n.notes]",
]

# ===========================================================================
# §3.7.4 可选向量索引（vector index）—— baseline 默认不启用
# ===========================================================================
# spec §3.7.4：baseline 不依赖 vector index；没有 embedding 时不得降级为读 W2。
VECTOR_INDEX_RULE_CARD: str = (
    "CREATE VECTOR INDEX rule_card_embedding_idx IF NOT EXISTS "
    "FOR (n:RuleCard) ON (n.embedding) "
    "OPTIONS {indexConfig: {"
    "`vector.dimensions`: 1536, "
    "`vector.similarity_function`: 'cosine'}}"
)


def all_schema_statements(include_vector_index: bool = False) -> List[str]:
    """返回全部 schema DDL 语句，按 约束 → B 树索引 → 全文索引 顺序。

    Args:
        include_vector_index: 是否附加可选向量索引（spec §3.7.4）；baseline 默认 False。

    Returns:
        Cypher DDL 字符串列表，调用方逐条执行。
    """
    statements: List[str] = []
    statements.extend(CONSTRAINTS)
    statements.extend(BTREE_INDEXES)
    statements.extend(FULLTEXT_INDEXES)
    if include_vector_index:
        statements.append(VECTOR_INDEX_RULE_CARD)
    return statements


__all__ = [
    "CONSTRAINTS",
    "BTREE_INDEXES",
    "FULLTEXT_INDEXES",
    "VECTOR_INDEX_RULE_CARD",
    "all_schema_statements",
]
