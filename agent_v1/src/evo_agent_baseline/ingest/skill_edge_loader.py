"""技能→法规 嵌边 loader（rule-skills-kg-rag「技能作为节点嵌入法规 KG」落地）。

把 `(:SkillVersion)` 节点按 `scope` 6 维挂边到法规侧节点。权威边名单 +
目标节点 label/key 取自 `ingest.cypher_schema_evo`（spec v1 §3.5）。

scope 维度 → 边类型 → 目标节点 映射（5 条嵌边；第 6 维 obligation_kinds 是
ObligationKind 枚举，无对应节点，故不挂边、保留为 SkillVersion 属性）：

    scope.rule_families  -[:APPLIES_TO]->      (:RuleFamily   {family_id})
    scope.rule_cards     -[:APPLIES_TO_CARD]-> (:RuleCard     {rule_card_id})
    scope.semantic_slots -[:TARGETS_SLOT]->    (:SemanticSlot {slot_id})
    scope.measure_keys   -[:TARGETS_MEASURE]-> (:Measure      {measure_key})
    scope.artifact_keys  -[:TARGETS_ARTIFACT]->(:Artifact     {artifact_key})

边起点是 `SkillVersion`（与 `cypher_schema_evo.EVO_RELATIONSHIP_TYPES` 注释
「SkillVersion -> RuleFamily」一致，也与 `evo.skill_package_loader` 既有
SkillVersion 中心建模一致）。

防孤儿（spec 多处「找不到目标则记 warning 不建悬空节点」口径）：scope 引用的
法规节点不存在时记 audit warning，**不硬建**目标节点；该边整条跳过。具体落地用
`MATCH ... MATCH ... MERGE` 语句形态（见 `_graphspec.edge_merge_cypher`）——
两端均 MATCH，端点不存在时 MERGE 无命中、关系自然不建。dry_run 模式额外用只读
存在性查询提前算出「将创建 / 目标缺失」两类计数。

两种输入形态：
1. `SkillJson` DTO —— 结构化 `scope`（authoritative；从磁盘 skill.json 解析）；
2. 库内 Skill 记录 dict —— 从 Neo4j 读出的 Skill / SkillVersion 属性。结构化
   `scope_*` 属性存在时直接用；不存在时 best-effort 从 `evo_trigger` /
   `evo_retrieval_pattern` 自由文本里抽 family_id（仅 rule_families 维度）。

写库入口 `load_skill_edges` 复用 `compile_batch` → `client.write_many`。
**本任务只交付 实现 + 单测 + dry_run；真灌库留主代理在 KG 治理后排。**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from evo_agent_baseline.contracts import SkillJson, SkillScope
from evo_agent_baseline.ingest._graphspec import (
    EdgeSpec,
    GraphBatch,
    compile_batch,
)
from evo_agent_baseline.ingest.guard import AuditLog


# ===========================================================================
# scope 维度 → 边类型 → 目标节点 映射表（spec v1 §3.5 权威边名单）
# ===========================================================================
@dataclass(frozen=True)
class ScopeEdgeRule:
    """一条 scope 维度的嵌边规则。

    Attributes:
        scope_field: `SkillScope` 上的字段名（6 维之一）。
        rel_type: 关系 type（UPPER_SNAKE_CASE，取自 cypher_schema_evo）。
        target_label: 目标节点 label。
        target_key_prop: 目标节点主键属性名。
    """

    scope_field: str
    rel_type: str
    target_label: str
    target_key_prop: str


# 5 条嵌边规则。obligation_kinds 无节点，不在此表（保留为 SkillVersion 属性）。
SCOPE_EDGE_RULES: Tuple[ScopeEdgeRule, ...] = (
    ScopeEdgeRule("rule_families", "APPLIES_TO", "RuleFamily", "family_id"),
    ScopeEdgeRule("rule_cards", "APPLIES_TO_CARD", "RuleCard", "rule_card_id"),
    ScopeEdgeRule("semantic_slots", "TARGETS_SLOT", "SemanticSlot", "slot_id"),
    ScopeEdgeRule("measure_keys", "TARGETS_MEASURE", "Measure", "measure_key"),
    ScopeEdgeRule("artifact_keys", "TARGETS_ARTIFACT", "Artifact", "artifact_key"),
)

# scope 中无对应法规节点、不挂边、保留为属性的维度（仅供文档 / audit）。
SCOPE_NON_EDGE_FIELDS: Tuple[str, ...] = ("obligation_kinds",)


# ===========================================================================
# 输入归一化：把不同输入形态统一成 (skill_version_id, SkillScope)
# ===========================================================================
@dataclass
class SkillScopeRef:
    """归一化后的「一个技能版本 + 其 scope」。

    Attributes:
        skill_version_id: SkillVersion 主键（嵌边起点）。
        skill_id: 逻辑 Skill id（仅用于 audit / 报告可读性）。
        scope: 结构化 scope（6 维列表）。
        scope_source: scope 来源标记（`skill_json` / `kg_scope_props` /
            `kg_text_recovered` / `empty`），供 dry_run 报告说明可信度。
    """

    skill_version_id: str
    skill_id: str
    scope: SkillScope
    scope_source: str = "skill_json"


def from_skill_json(skill_json: SkillJson) -> SkillScopeRef:
    """`SkillJson` → `SkillScopeRef`（结构化 scope，authoritative）。"""
    return SkillScopeRef(
        skill_version_id=skill_json.skill_version_id,
        skill_id=skill_json.skill_id,
        scope=skill_json.scope,
        scope_source="skill_json",
    )


# 库内自由文本里抽 family_id 的形态：mbis.<...>（点分小写片段，≥3 段）。
_FAMILY_ID_RE = re.compile(r"\bmbis(?:\.[a-z0-9_]+){2,}\b")


def _recover_families_from_text(*texts: Optional[str]) -> List[str]:
    """从 `evo_trigger` / `evo_retrieval_pattern` 自由文本 best-effort 抽 family_id。

    仅恢复 rule_families 维度（自由文本里唯一可结构化的法规引用）；其余维度无信号、
    返回空。匹配 `mbis.x.y.z...` 形态，去重保序。

    Args:
        *texts: 任意条自由文本（None 跳过）。

    Returns:
        去重保序的 family_id 候选列表。
    """
    seen: List[str] = []
    for text in texts:
        if not text:
            continue
        for m in _FAMILY_ID_RE.findall(text):
            if m not in seen:
                seen.append(m)
    return seen


def from_kg_record(record: Dict[str, Any]) -> SkillScopeRef:
    """库内 Skill / SkillVersion 记录 dict → `SkillScopeRef`。

    优先级：
    1. 结构化 `scope_*` 属性（`scope_rule_families` 等，由
       `evo.skill_package_loader` 风格 loader 写入）—— 直接用，scope_source=
       `kg_scope_props`；
    2. 无结构化 scope 时 best-effort 从 `evo_trigger` / `evo_retrieval_pattern`
       抽 family_id（仅 rule_families）—— scope_source=`kg_text_recovered`；
    3. 都没有 —— 空 scope，scope_source=`empty`（manual 跨切面技能正常会落此）。

    Args:
        record: 至少含 `skill_version_id`（或 `skill_id`）；其余 scope 属性可选。

    Returns:
        归一化 `SkillScopeRef`。
    """
    skill_id = record.get("skill_id") or record.get("skill_version_id") or ""
    skill_version_id = record.get("skill_version_id") or skill_id

    # 路径 1：结构化 scope_* 属性
    structured_keys = [
        ("scope_rule_families", "rule_families"),
        ("scope_rule_cards", "rule_cards"),
        ("scope_semantic_slots", "semantic_slots"),
        ("scope_measure_keys", "measure_keys"),
        ("scope_artifact_keys", "artifact_keys"),
        ("scope_obligation_kinds", "obligation_kinds"),
    ]
    has_structured = any(record.get(k) for k, _ in structured_keys)
    if has_structured:
        scope = SkillScope(
            **{
                field_name: list(record.get(prop_key) or [])
                for prop_key, field_name in structured_keys
            }
        )
        return SkillScopeRef(
            skill_version_id=skill_version_id,
            skill_id=skill_id,
            scope=scope,
            scope_source="kg_scope_props",
        )

    # 路径 2：自由文本恢复 family_id
    recovered = _recover_families_from_text(
        record.get("evo_trigger"),
        record.get("evo_retrieval_pattern"),
    )
    if recovered:
        return SkillScopeRef(
            skill_version_id=skill_version_id,
            skill_id=skill_id,
            scope=SkillScope(rule_families=recovered),
            scope_source="kg_text_recovered",
        )

    # 路径 3：无 scope 信号
    return SkillScopeRef(
        skill_version_id=skill_version_id,
        skill_id=skill_id,
        scope=SkillScope(),
        scope_source="empty",
    )


# ===========================================================================
# 边规格生成（纯转换段，不依赖 Neo4j，可全量单测）
# ===========================================================================
def build_skill_edges(ref: SkillScopeRef) -> List[EdgeSpec]:
    """一个 `SkillScopeRef` → 全部嵌边 `EdgeSpec`（不含目标存在性校验）。

    幂等由 `edge_merge_cypher` 的 MERGE 保证；目标缺失防孤儿由 MATCH 两端 +
    （dry_run / live 时）存在性预查承担，本函数只负责按映射表展开 scope。

    Args:
        ref: 归一化技能 scope。

    Returns:
        `EdgeSpec` 列表（起点 SkillVersion，终点法规节点）。去重保序。
    """
    edges: List[EdgeSpec] = []
    seen: set = set()
    for rule in SCOPE_EDGE_RULES:
        targets = getattr(ref.scope, rule.scope_field, []) or []
        for target_value in targets:
            if not target_value:
                continue
            dedup_key = (rule.rel_type, target_value)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            edges.append(
                EdgeSpec(
                    start_label="SkillVersion",
                    start_key_prop="skill_version_id",
                    start_key_value=ref.skill_version_id,
                    rel_type=rule.rel_type,
                    end_label=rule.target_label,
                    end_key_prop=rule.target_key_prop,
                    end_key_value=target_value,
                    props={"scope_source": ref.scope_source},
                )
            )
    return edges


def build_skill_edge_batch(refs: Iterable[SkillScopeRef]) -> GraphBatch:
    """多个 `SkillScopeRef` → 单个 `GraphBatch`（只含边，不建任何节点）。

    嵌边只 MATCH 既有节点、不新建节点：SkillVersion 应已由 skill 包 loader 建好，
    法规节点由 W2/规则 loader 建好。本 batch 不含 NodeSpec。

    Args:
        refs: 归一化技能 scope 序列。

    Returns:
        只含 EdgeSpec 的 GraphBatch。
    """
    batch = GraphBatch()
    for ref in refs:
        for edge in build_skill_edges(ref):
            batch.add_edge(edge)
    return batch


# ===========================================================================
# dry_run：连库只读，算「将创建 / 目标缺失」计数，绝不写库
# ===========================================================================
@dataclass
class EdgeDryRunStat:
    """单条 scope 维度 / 边类型的 dry_run 统计。"""

    rel_type: str
    target_label: str
    would_create: int = 0          # 目标节点存在、将创建的边数
    missing_target: int = 0        # 目标节点不存在、跳过的边数


@dataclass
class SkillEdgeDryRunResult:
    """整批 dry_run 结果。"""

    per_rel: Dict[str, EdgeDryRunStat] = field(default_factory=dict)
    total_would_create: int = 0
    total_missing_target: int = 0
    skill_count: int = 0
    scope_source_counts: Dict[str, int] = field(default_factory=dict)
    missing_target_examples: List[str] = field(default_factory=list)
    audit: AuditLog = field(default_factory=AuditLog)


def _target_exists(client: Any, label: str, key_prop: str, key_value: Any) -> bool:
    """只读查询：法规目标节点是否存在（dry_run 防孤儿判定）。

    用 `client.read`（只读事务）执行 `MATCH ... RETURN count(*)`。绝不写库。

    Args:
        client: Neo4jClient（提供 `read`）。
        label: 目标节点 label。
        key_prop: 目标主键属性名。
        key_value: 目标主键值。

    Returns:
        存在返回 True。
    """
    cypher = f"MATCH (n:{label} {{{key_prop}: $val}}) RETURN count(n) AS c"
    rows = client.read(cypher, {"val": key_value})
    if not rows:
        return False
    return int(rows[0].get("c", 0)) > 0


def dry_run_skill_edges(
    refs: Iterable[SkillScopeRef],
    client: Any,
    audit: Optional[AuditLog] = None,
) -> SkillEdgeDryRunResult:
    """dry_run：对一批技能 scope 算嵌边统计（连库只读，不写）。

    对每条候选边只读探测目标法规节点是否存在：存在计入 `would_create`，
    不存在计入 `missing_target` 并记 audit warning（防孤儿）。

    Args:
        refs: 归一化技能 scope 序列。
        client: Neo4jClient（只调用 `read`）。
        audit: 复用审计记录器；None 时新建。

    Returns:
        `SkillEdgeDryRunResult`（按边类型分计 + 总计 + 缺失样例）。
    """
    audit = audit or AuditLog()
    result = SkillEdgeDryRunResult(audit=audit)

    # 预填全部边类型，保证报告 5 类齐全（即便某类 0 计数）。
    for rule in SCOPE_EDGE_RULES:
        result.per_rel[rule.rel_type] = EdgeDryRunStat(
            rel_type=rule.rel_type, target_label=rule.target_label
        )

    refs_list = list(refs)
    result.skill_count = len(refs_list)

    # 目标存在性缓存（同一目标可能被多技能引用，省查询）。
    exists_cache: Dict[Tuple[str, Any], bool] = {}

    for ref in refs_list:
        result.scope_source_counts[ref.scope_source] = (
            result.scope_source_counts.get(ref.scope_source, 0) + 1
        )
        for edge in build_skill_edges(ref):
            stat = result.per_rel[edge.rel_type]
            cache_key = (edge.end_label, edge.end_key_value)
            if cache_key not in exists_cache:
                exists_cache[cache_key] = _target_exists(
                    client, edge.end_label, edge.end_key_prop, edge.end_key_value
                )
            if exists_cache[cache_key]:
                stat.would_create += 1
                result.total_would_create += 1
            else:
                stat.missing_target += 1
                result.total_missing_target += 1
                example = (
                    f"{ref.skill_version_id} -[:{edge.rel_type}]-> "
                    f"(:{edge.end_label} {{{edge.end_key_prop}={edge.end_key_value!r}}})"
                )
                if len(result.missing_target_examples) < 50:
                    result.missing_target_examples.append(example)
                audit.warn(
                    f"skill-edge dry_run: target not found, edge skipped — {example}"
                )

    return result


def format_dry_run_report(result: SkillEdgeDryRunResult) -> str:
    """把 dry_run 结果格式化为人读文本（落盘用）。"""
    lines: List[str] = []
    lines.append("# 技能→法规 嵌边 dry_run 报告（只读，未写库）")
    lines.append("")
    lines.append(f"扫描技能版本数: {result.skill_count}")
    lines.append(f"将创建边总数 (目标存在): {result.total_would_create}")
    lines.append(f"目标缺失跳过边总数: {result.total_missing_target}")
    lines.append("")
    lines.append("## scope 来源分布")
    for source in sorted(result.scope_source_counts):
        lines.append(f"  {source}: {result.scope_source_counts[source]}")
    lines.append("")
    lines.append("## 按边类型分计")
    lines.append(f"{'边类型':<20}{'目标节点':<16}{'将创建':>8}{'目标缺失':>10}")
    for rule in SCOPE_EDGE_RULES:
        stat = result.per_rel[rule.rel_type]
        lines.append(
            f"{stat.rel_type:<20}{stat.target_label:<16}"
            f"{stat.would_create:>8}{stat.missing_target:>10}"
        )
    if result.missing_target_examples:
        lines.append("")
        lines.append("## 目标缺失样例（最多 50 条）")
        for ex in result.missing_target_examples:
            lines.append(f"  - {ex}")
    return "\n".join(lines) + "\n"


# ===========================================================================
# 写库入口（留主代理调用；本任务不执行真灌库）
# ===========================================================================
def load_skill_edges(
    refs: Iterable[SkillScopeRef],
    client: Any,
    audit: Optional[AuditLog] = None,
    skip_missing_targets: bool = True,
) -> Dict[str, Any]:
    """把技能嵌边写入 Neo4j（MERGE 幂等）。

    spec §4.2.3：MERGE 幂等。防孤儿：`skip_missing_targets=True` 时先只读探测
    目标存在性，缺失的边整条跳过并记 warning，绝不硬建目标节点；
    `edge_merge_cypher` 本身也用 MATCH 两端，端点不存在 MERGE 无命中。

    **本任务交付阶段不调用此函数**；保留供主代理在 KG 治理后真灌库。

    Args:
        refs: 归一化技能 scope 序列。
        client: Neo4jClient（`read` + `write_many`）。
        audit: 审计记录器。
        skip_missing_targets: 是否预过滤目标缺失的边（默认 True，防孤儿）。

    Returns:
        统计 dict（written_edge_count / skipped_missing_count）。
    """
    audit = audit or AuditLog()
    batch = build_skill_edge_batch(refs)

    edges_to_write: List[EdgeSpec] = []
    skipped = 0
    exists_cache: Dict[Tuple[str, Any], bool] = {}
    for edge in batch.edges:
        if skip_missing_targets:
            cache_key = (edge.end_label, edge.end_key_value)
            if cache_key not in exists_cache:
                exists_cache[cache_key] = _target_exists(
                    client, edge.end_label, edge.end_key_prop, edge.end_key_value
                )
            if not exists_cache[cache_key]:
                skipped += 1
                audit.warn(
                    f"skill-edge load: target not found, edge skipped — "
                    f"{edge.start_key_value} -[:{edge.rel_type}]-> "
                    f"(:{edge.end_label} {{{edge.end_key_prop}={edge.end_key_value!r}}})"
                )
                continue
        edges_to_write.append(edge)

    write_batch = GraphBatch(edges=edges_to_write)
    statements = compile_batch(write_batch)
    client.write_many(statements)

    return {
        "written_edge_count": len(edges_to_write),
        "skipped_missing_count": skipped,
    }


__all__ = [
    "ScopeEdgeRule",
    "SCOPE_EDGE_RULES",
    "SCOPE_NON_EDGE_FIELDS",
    "SkillScopeRef",
    "from_skill_json",
    "from_kg_record",
    "build_skill_edges",
    "build_skill_edge_batch",
    "EdgeDryRunStat",
    "SkillEdgeDryRunResult",
    "dry_run_skill_edges",
    "format_dry_run_report",
    "load_skill_edges",
]
