"""evo-agent v1 namespace 节点 / 关系 / 索引 DDL（spec v1 §3.4 ~ §3.7）。

本模块只生成 Cypher DDL 字符串，不执行；执行交给 `kg.neo4j_client`。
所有 DDL 用 `IF NOT EXISTS` 保证幂等。

v1 namespace 覆盖范围（与 baseline `cypher_schema.py` 互补，不重复 v0.4 节点）：

- Rule-Skills KG 节点（spec v1 §3.4）：
  - `(:Skill)` skill_id unique（v0.4 已有；这里复述以保完整 v1 视图）
  - `(:SkillVersion)` skill_version_id unique
  - `(:SkillTrigger)` trigger_id unique（v0.4 已有）
  - `(:SkillActivation)` activation_id unique
  - `(:SkillValidationRecord)` validation_id unique
  - `(:SkillSet)` skill_set_id unique
  - `(:SkillConflictRecord)` conflict_id unique

- EvoMemoryStore 节点（spec v1 §3.6）：
  - `(:EvoRunTrace)` trace_id unique
  - `(:EvoRunStep)` step_id unique
  - `(:ReplayCase)` replay_case_id unique
  - `(:EvoPolicy)` policy_id unique
  - `(:EvoPolicyVersion)` policy_version_id unique
  - `(:SanitizedFeedbackPacket)` feedback_packet_id unique
  - `(:FeedbackCell)` feedback_cell_id unique
  - `(:EvoReleaseCard)` release_card_id unique

- B 树索引（spec v1 §3.7）：
  - SkillVersion(status, kind, rulecard_bundle_id)
  - ReplayCase(split, eligibility, purpose)
  - SanitizedFeedbackPacket(eval_window_id, aggregation_level)
  - SkillValidationRecord(skill_version_id, validation_stage)
  - EvoRunTrace(rulecard_bundle_id, evo_policy_version_id)
  - EvoPolicyVersion(status, policy_id)
  - SkillActivation(run_id, skill_version_id)
  - SkillSet(policy_version_id)

注：约束含 v0.4 已有的 `Skill.skill_id` / `SkillTrigger.trigger_id` 是为了 v1 文档完整；
执行时与 baseline `cypher_schema.CONSTRAINTS` 合并由调用方做幂等去重。

边类型在 spec v1 §3.5 由 `MERGE (a)-[r:REL]->(b)` 写入逻辑承担；
Neo4j 关系无独立约束，仅靠端点节点 unique 即可保证业务唯一性，本模块不为关系
单独建 statement，但在 `EVO_RELATIONSHIP_TYPES` 列出全部边类型供 audit 参考。
"""

from __future__ import annotations

from typing import List

# ===========================================================================
# spec v1 §3.4 Rule-Skills KG 节点 约束
# ===========================================================================
RULE_SKILLS_CONSTRAINTS: List[str] = [
    "CREATE CONSTRAINT skill_id_unique IF NOT EXISTS "
    "FOR (n:Skill) REQUIRE n.skill_id IS UNIQUE",
    "CREATE CONSTRAINT skill_version_id_unique IF NOT EXISTS "
    "FOR (n:SkillVersion) REQUIRE n.skill_version_id IS UNIQUE",
    "CREATE CONSTRAINT skill_trigger_id_unique IF NOT EXISTS "
    "FOR (n:SkillTrigger) REQUIRE n.trigger_id IS UNIQUE",
    "CREATE CONSTRAINT skill_activation_id_unique IF NOT EXISTS "
    "FOR (n:SkillActivation) REQUIRE n.activation_id IS UNIQUE",
    "CREATE CONSTRAINT skill_validation_record_id_unique IF NOT EXISTS "
    "FOR (n:SkillValidationRecord) REQUIRE n.validation_id IS UNIQUE",
    "CREATE CONSTRAINT skill_set_id_unique IF NOT EXISTS "
    "FOR (n:SkillSet) REQUIRE n.skill_set_id IS UNIQUE",
    "CREATE CONSTRAINT skill_conflict_record_id_unique IF NOT EXISTS "
    "FOR (n:SkillConflictRecord) REQUIRE n.conflict_id IS UNIQUE",
]

# ===========================================================================
# spec v1 §3.6 EvoMemoryStore 节点 约束
# ===========================================================================
EVO_MEMORY_CONSTRAINTS: List[str] = [
    "CREATE CONSTRAINT trace_id_unique IF NOT EXISTS "
    "FOR (n:EvoRunTrace) REQUIRE n.trace_id IS UNIQUE",
    "CREATE CONSTRAINT evo_run_step_id_unique IF NOT EXISTS "
    "FOR (n:EvoRunStep) REQUIRE n.step_id IS UNIQUE",
    "CREATE CONSTRAINT replay_case_id_unique IF NOT EXISTS "
    "FOR (n:ReplayCase) REQUIRE n.replay_case_id IS UNIQUE",
    "CREATE CONSTRAINT evo_policy_id_unique IF NOT EXISTS "
    "FOR (n:EvoPolicy) REQUIRE n.policy_id IS UNIQUE",
    "CREATE CONSTRAINT policy_version_id_unique IF NOT EXISTS "
    "FOR (n:EvoPolicyVersion) REQUIRE n.policy_version_id IS UNIQUE",
    "CREATE CONSTRAINT feedback_packet_id_unique IF NOT EXISTS "
    "FOR (n:SanitizedFeedbackPacket) REQUIRE n.feedback_packet_id IS UNIQUE",
    "CREATE CONSTRAINT feedback_cell_id_unique IF NOT EXISTS "
    "FOR (n:FeedbackCell) REQUIRE n.feedback_cell_id IS UNIQUE",
    "CREATE CONSTRAINT release_card_id_unique IF NOT EXISTS "
    "FOR (n:EvoReleaseCard) REQUIRE n.release_card_id IS UNIQUE",
]

# 合并：spec v1 §3.7 显式列出的核心约束（含 v0.4 已有项）。
EVO_CONSTRAINTS: List[str] = RULE_SKILLS_CONSTRAINTS + EVO_MEMORY_CONSTRAINTS


# ===========================================================================
# spec v1 §3.7 索引
# ===========================================================================
EVO_INDEXES: List[str] = [
    # SkillVersion lookup：spec §3.7 skill_scope_family
    "CREATE INDEX skill_scope_family IF NOT EXISTS "
    "FOR (sv:SkillVersion) ON (sv.status, sv.kind, sv.rulecard_bundle_id)",
    # ReplayCase split lookup：spec §3.7 replay_split_eligibility
    "CREATE INDEX replay_split_eligibility IF NOT EXISTS "
    "FOR (rc:ReplayCase) ON (rc.split, rc.eligibility, rc.purpose)",
    # SanitizedFeedbackPacket window lookup：spec §3.7 feedback_packet_window
    "CREATE INDEX feedback_packet_window IF NOT EXISTS "
    "FOR (s:SanitizedFeedbackPacket) ON (s.eval_window_id, s.aggregation_level)",
    # SkillValidationRecord 按 skill_version_id + stage 查（5 Gate 链路）
    "CREATE INDEX skill_validation_record_skill_stage IF NOT EXISTS "
    "FOR (svr:SkillValidationRecord) ON (svr.skill_version_id, svr.validation_stage)",
    # EvoRunTrace 按 bundle + policy 查（replay buffer 切片）
    "CREATE INDEX evo_run_trace_bundle_policy IF NOT EXISTS "
    "FOR (t:EvoRunTrace) ON (t.rulecard_bundle_id, t.evo_policy_version_id)",
    # EvoPolicyVersion 按 status + policy_id 查（active 版本快速 lookup）
    "CREATE INDEX evo_policy_version_status IF NOT EXISTS "
    "FOR (p:EvoPolicyVersion) ON (p.status, p.policy_id)",
    # SkillActivation 按 run + skill 查（trace provenance）
    "CREATE INDEX skill_activation_run_skill IF NOT EXISTS "
    "FOR (sa:SkillActivation) ON (sa.run_id, sa.skill_version_id)",
    # SkillSet 按 policy 查
    "CREATE INDEX skill_set_policy IF NOT EXISTS "
    "FOR (ss:SkillSet) ON (ss.policy_version_id)",
]


# ===========================================================================
# spec v1 §3.5 关系类型清单（仅供 audit / 文档；无独立约束）
# ===========================================================================
EVO_RELATIONSHIP_TYPES: List[str] = [
    "HAS_VERSION",          # Skill -> SkillVersion
    "HAS_TRIGGER",          # SkillVersion -> SkillTrigger
    "APPLIES_TO",           # SkillVersion -> RuleFamily
    "APPLIES_TO_CARD",      # SkillVersion -> RuleCard
    "TARGETS_SLOT",         # SkillVersion -> SemanticSlot
    "TARGETS_MEASURE",      # SkillVersion -> Measure
    "TARGETS_ARTIFACT",     # SkillVersion -> Artifact
    "VALIDATED_BY",         # SkillVersion -> SkillValidationRecord
    "SUPERSEDES",           # SkillVersion -> SkillVersion
    "INVOKED_SKILL",        # SkillActivation -> SkillVersion
    "LOADS",                # SkillSet -> SkillVersion
    "LOADS_SKILL_SET",      # EvoPolicyVersion -> SkillSet
    "LOADED_BY_POLICY",     # SkillSet -> EvoPolicyVersion (reverse provenance)
    "ACTIVATES",            # SkillTrigger -> SkillActivation (runtime)
    "TARGETS",              # 广义 targeting alias
]


def all_evo_schema_statements() -> List[str]:
    """返回 v1 evo namespace 全部 DDL 语句（约束 + 索引）。

    Returns:
        Cypher DDL 字符串列表，调用方逐条 `client.execute(stmt)`。
    """
    statements: List[str] = []
    statements.extend(EVO_CONSTRAINTS)
    statements.extend(EVO_INDEXES)
    return statements


__all__ = [
    "RULE_SKILLS_CONSTRAINTS",
    "EVO_MEMORY_CONSTRAINTS",
    "EVO_CONSTRAINTS",
    "EVO_INDEXES",
    "EVO_RELATIONSHIP_TYPES",
    "all_evo_schema_statements",
]
