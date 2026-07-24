"""Rule KG-RAG 检索器（spec §5.4 + §5.6）。

从 `FactPack` 出发检索候选 rule_card，按 §5.4.4 打分排序，graph expansion
一跳展开，最后组装成 `RuleSlice`。

实现的 spec 章节：
- §5.4.1 slot-driven / measure-driven 候选卡；
- §5.4.2 applicability-driven 候选卡；
- §5.4.3 graph expansion + DTO builder（经 `pack_builder`）；
- §5.4.4 retrieval ranking 打分公式 + cutoff policy；
- §5.6 RuleSlice 组装。

§5.4.4 关键规则（严格照实现）：
- 排名只影响 LLM context 顺序，不影响闭包验证器的确定性候选全集；
- verifier 默认候选集 = 所有 `score > 0` 且 applicability 未明确排除的 RuleCard；
- 使用 candidate cutoff 前必须记录 cutoff policy。

rule-blind 红线只属 W0/W1（见 memory）：rule_card 检索是 baseline 本职，
不受 blind 约束；但取回的 DTO 仍经 `pack_builder.assert_dto_blind_safe` 收口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from evo_agent_baseline.contracts import FactPack, RuleSlice
from evo_agent_baseline.kg import queries
from evo_agent_baseline.retrieval.pack_builder import (
    artifact_dto_from_node,
    build_rule_slice,
    measure_dto_from_node,
    rule_card_dto_from_subgraph,
    rule_family_dto_from_node,
    semantic_slot_dto_from_node,
    source_quote_dto_from_node,
    time_anchor_dto_from_node,
)

# §5.4.4 打分权重（严格照 spec 公式）。
SCORE_WEIGHTS: Dict[str, float] = {
    "exact_slot_hit": 5.0,
    "exact_measure_hit": 4.0,
    "applicability_match": 2.0,
    "source_clause_fulltext": 1.5,
    "neighbor_family_hit": 1.0,
    "explicit_exclusion": -3.0,
}


@dataclass
class CandidateSignals:
    """单张候选卡的各路命中信号（§5.4.4 打分输入）。"""

    rule_card_id: str
    exact_slot_hit_count: int = 0
    exact_measure_hit_count: int = 0
    applicability_match_count: int = 0
    source_clause_fulltext_score: float = 0.0
    neighbor_family_hit_count: int = 0
    explicit_exclusion_match_count: int = 0

    def score(self) -> float:
        """按 §5.4.4 公式算候选卡排序分数。

        Returns:
            排序分数（float）。
        """
        return (
            SCORE_WEIGHTS["exact_slot_hit"] * self.exact_slot_hit_count
            + SCORE_WEIGHTS["exact_measure_hit"] * self.exact_measure_hit_count
            + SCORE_WEIGHTS["applicability_match"] * self.applicability_match_count
            + SCORE_WEIGHTS["source_clause_fulltext"] * self.source_clause_fulltext_score
            + SCORE_WEIGHTS["neighbor_family_hit"] * self.neighbor_family_hit_count
            + SCORE_WEIGHTS["explicit_exclusion"] * self.explicit_exclusion_match_count
        )


def rank_candidates(signals: Dict[str, CandidateSignals]) -> List[tuple[str, float]]:
    """对候选卡按 §5.4.4 分数降序排序（同分按 rule_card_id 稳定升序）。

    Args:
        signals: rule_card_id → CandidateSignals。

    Returns:
        (rule_card_id, score) 列表，按 score 降序、id 升序。
    """
    scored = [(cid, sig.score()) for cid, sig in signals.items()]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def select_verifier_candidates(
    signals: Dict[str, CandidateSignals],
) -> List[str]:
    """选出 verifier 确定性候选全集（§5.4.4）。

    默认规则：所有 `score > 0` 且 applicability 未明确排除的 RuleCard。
    `explicit_exclusion_match_count > 0` 视为明确排除，剔除。

    Args:
        signals: rule_card_id → CandidateSignals。

    Returns:
        verifier 候选 rule_card_id 列表（按 id 升序，保证确定性）。
    """
    selected: List[str] = []
    for cid, sig in signals.items():
        if sig.explicit_exclusion_match_count > 0:
            continue
        if sig.score() > 0:
            selected.append(cid)
    return sorted(selected)


@dataclass
class RuleRetrievalResult:
    """Rule KG-RAG 检索的中间结果（写图 / 单测中转用）。"""

    signals: Dict[str, CandidateSignals] = field(default_factory=dict)
    ranked: List[tuple[str, float]] = field(default_factory=list)
    verifier_candidate_ids: List[str] = field(default_factory=list)
    expansion_rows: List[Dict[str, Any]] = field(default_factory=list)


def _get_signal(signals: Dict[str, CandidateSignals], rule_card_id: str) -> CandidateSignals:
    """取或建一张候选卡的信号对象。"""
    if rule_card_id not in signals:
        signals[rule_card_id] = CandidateSignals(rule_card_id=rule_card_id)
    return signals[rule_card_id]


def collect_candidate_signals(
    client: Any,
    fact_pack: FactPack,
    regime: str = "mbis",
    building_scope_tags: Optional[List[str]] = None,
    component_scope_tags: Optional[List[str]] = None,
) -> Dict[str, CandidateSignals]:
    """跑 §5.4.1 / §5.4.2 各路检索，汇总候选卡信号（spec §5.4）。

    Args:
        client: `Neo4jClient` 实例。
        fact_pack: 已检索好的 FactPack（提供 slot / measure 集合）。
        regime: 法规 regime，默认 mbis。
        building_scope_tags: 建筑 scope 标签集合。
        component_scope_tags: 构件 scope 标签集合。

    Returns:
        rule_card_id → CandidateSignals。
    """
    signals: Dict[str, CandidateSignals] = {}

    # §5.4.1 slot-driven。
    slot_ids = sorted(fact_pack.slot_index.keys())
    if slot_ids:
        for row in client.read(queries.RULE_SLOT_DRIVEN_CARDS, queries.slot_params(slot_ids)):
            sig = _get_signal(signals, row["rule_card_id"])
            sig.exact_slot_hit_count = int(row.get("slot_hits") or 0)

    # §5.4.1 measure-driven。
    measure_keys = sorted(fact_pack.measure_index.keys())
    if measure_keys:
        for row in client.read(
            queries.RULE_MEASURE_DRIVEN_CARDS, queries.measure_params(measure_keys)
        ):
            sig = _get_signal(signals, row["rule_card_id"])
            sig.exact_measure_hit_count = int(row.get("threshold_hits") or 0)

    # §5.4.2 applicability-driven —— building scope。
    building_tags = building_scope_tags or []
    for row in client.read(
        queries.RULE_APPLICABILITY_BUILDING_SCOPE,
        queries.applicability_building_params(regime, building_tags),
    ):
        sig = _get_signal(signals, row["rule_card_id"])
        sig.applicability_match_count += 1

    # §5.4.2 applicability-driven —— component scope。
    component_tags = component_scope_tags or []
    if component_tags:
        for row in client.read(
            queries.RULE_APPLICABILITY_COMPONENT_SCOPE,
            queries.applicability_component_params(component_tags),
        ):
            sig = _get_signal(signals, row["rule_card_id"])
            sig.applicability_match_count += 1

    return signals


def retrieve_rule_slice(
    client: Any,
    run_id: str,
    fact_pack: FactPack,
    rulecard_bundle_id: str,
    regime: str = "mbis",
    building_scope_tags: Optional[List[str]] = None,
    component_scope_tags: Optional[List[str]] = None,
) -> RuleSlice:
    """完整 Rule KG-RAG 检索 + 组装 RuleSlice（spec §5.4 + §5.6）。

    流程：候选信号汇总 → §5.4.4 排序 + verifier 候选集选取 →
    §5.4.3 graph expansion → DTO builder 还原原嵌套 → 组装 RuleSlice。

    Args:
        client: `Neo4jClient` 实例。
        run_id: ComplianceAssessmentRun id。
        fact_pack: 已检索的 FactPack。
        rulecard_bundle_id: rule_card bundle id。
        regime: 法规 regime。
        building_scope_tags / component_scope_tags: scope 标签。

    Returns:
        RuleSlice。
    """
    result = run_rule_retrieval(
        client, fact_pack, regime, building_scope_tags, component_scope_tags
    )
    return assemble_rule_slice(run_id, rulecard_bundle_id, result, client)


def run_rule_retrieval(
    client: Any,
    fact_pack: FactPack,
    regime: str = "mbis",
    building_scope_tags: Optional[List[str]] = None,
    component_scope_tags: Optional[List[str]] = None,
) -> RuleRetrievalResult:
    """跑候选信号 + 排序 + verifier 候选集 + graph expansion（spec §5.4）。

    Args:
        client: `Neo4jClient` 实例。
        fact_pack: FactPack。
        regime / building_scope_tags / component_scope_tags: 检索范围参数。

    Returns:
        RuleRetrievalResult。
    """
    signals = collect_candidate_signals(
        client, fact_pack, regime, building_scope_tags, component_scope_tags
    )
    ranked = rank_candidates(signals)
    verifier_candidate_ids = select_verifier_candidates(signals)

    expansion_rows: List[Dict[str, Any]] = []
    if verifier_candidate_ids:
        expansion_rows = client.read(
            queries.RULE_GRAPH_EXPANSION,
            queries.expansion_params(verifier_candidate_ids),
        )
    return RuleRetrievalResult(
        signals=signals,
        ranked=ranked,
        verifier_candidate_ids=verifier_candidate_ids,
        expansion_rows=expansion_rows,
    )


def assemble_rule_slice(
    run_id: str,
    rulecard_bundle_id: str,
    result: RuleRetrievalResult,
    client: Any,
) -> RuleSlice:
    """把 RuleRetrievalResult 装配为 RuleSlice（spec §5.4.3 + §5.6）。

    Args:
        run_id: run id。
        rulecard_bundle_id: bundle id。
        result: run_rule_retrieval 的结果。
        client: `Neo4jClient` 实例（取 family 元数据）。

    Returns:
        RuleSlice。
    """
    candidate_dtos = [rule_card_dto_from_subgraph(row) for row in result.expansion_rows]

    # 从 expansion 子图收集 registry 子 DTO（去重）。
    semantic_slots: Dict[str, Any] = {}
    measures: Dict[str, Any] = {}
    artifacts: Dict[str, Any] = {}
    time_anchors: Dict[str, Any] = {}
    source_quotes: Dict[str, Any] = {}
    family_ids: Set[str] = set()

    for row in result.expansion_rows:
        for node in row.get("semantic_slots", []) or []:
            if node and node.get("slot_id"):
                semantic_slots[node["slot_id"]] = semantic_slot_dto_from_node(node)
        for node in row.get("measures", []) or []:
            if node and node.get("measure_key"):
                measures[node["measure_key"]] = measure_dto_from_node(node)
        for node in row.get("time_anchors", []) or []:
            if node and node.get("time_anchor_key"):
                time_anchors[node["time_anchor_key"]] = time_anchor_dto_from_node(node)
        for node in row.get("workflow_artifacts", []) or []:
            # WorkflowArtifact 不是 registry Artifact；artifact registry 单独查。
            pass
        for node in row.get("source_quotes", []) or []:
            if node and node.get("source_quote_id"):
                source_quotes[node["source_quote_id"]] = source_quote_dto_from_node(node)
        rc = row.get("rule_card") or {}
        if rc.get("family_id"):
            family_ids.add(rc["family_id"])

    # family 元数据。
    rule_families: List[Any] = []
    if family_ids:
        for row in client.read(
            queries.RULE_FAMILIES_BY_ID, queries.family_params(sorted(family_ids))
        ):
            node = row.get("rule_family") or {}
            if node.get("family_id"):
                rule_families.append(rule_family_dto_from_node(node))

    # artifact registry：候选卡 WorkflowArtifact 的 artifact_key → registry Artifact。
    artifact_keys: Set[str] = set()
    for dto in candidate_dtos:
        for art in dto.workflow_operands.get("artifacts", []) or []:
            if isinstance(art, dict) and art.get("artifact_key"):
                artifact_keys.add(art["artifact_key"])
    artifact_dtos: List[Any] = []
    # registry Artifact 节点没有专用 by-key 查询，复用 expansion 子图里没有的话
    # 留空（artifact 语义在 closure 侧用 artifact alias map，spec §6.3.6）。
    # 这里只把候选卡里出现过、且 expansion 已带回的 registry Artifact 收进来。
    for row in result.expansion_rows:
        for node in row.get("artifacts", []) or []:
            if node and node.get("artifact_key"):
                artifacts[node["artifact_key"]] = artifact_dto_from_node(node)
    artifact_dtos = list(artifacts.values())

    # §5.4.4：retrieval_policy 必须记录 cutoff policy + ranking。
    retrieval_policy: Dict[str, Any] = {
        "ranking_formula": "spec_5_4_4",
        "score_weights": dict(SCORE_WEIGHTS),
        "candidate_cutoff_policy": "all_score_gt_0_not_explicitly_excluded",
        "verifier_candidate_count": len(result.verifier_candidate_ids),
        "ranked_order": [cid for cid, _ in result.ranked],
        "ranked_scores": {cid: score for cid, score in result.ranked},
        "note": (
            "ranking 只影响 LLM context 顺序；verifier 候选全集为 score>0 "
            "且 applicability 未明确排除的全部 RuleCard（spec §5.4.4）"
        ),
    }

    # spec §6.4.2 canonicalization：把 projection_runtime_mapping 的 slot/measure
    # 别名带进 retrieval_policy（闭包 _slot_aliases_from_policy /
    # _measure_aliases_from_policy 消费）。DEBT-040 修复：此前 KG 里没有该节点、
    # policy 也不带，触发器按 rule_card 裸名查 W0 带前缀事实（procedure.*）必 miss。
    mapping_rows = client.read(queries.RULE_PROJECTION_RUNTIME_MAPPING)
    if mapping_rows:
        row = mapping_rows[0]
        try:
            retrieval_policy["projection_runtime_mapping_v1"] = {
                "slot_aliases": json.loads(row.get("slot_aliases_json") or "{}"),
                "measure_aliases": json.loads(row.get("measure_aliases_json") or "{}"),
                # DEBT-049 Phase3 U2：method 别名分组表（闭包侧 _method_aliases_from_policy
                # 反转全展开成运行态 {alias→canonical}）。暗部署期节点无此属性→null→空表 identity。
                "method_aliases": json.loads(row.get("method_aliases_json") or "{}"),
                # DEBT-047：适用性 subject 词桥 + 限定符值对照（闭包侧规则 3 用）。
                "qualifier_value_aliases": json.loads(
                    row.get("qualifier_value_aliases_json") or "{}"
                ),
                "subject_component_crosswalk": json.loads(
                    row.get("subject_component_crosswalk_json") or "{}"
                ),
                # DEBT-050 修案：组件类目成员表进闭包侧（触发器限定符结构
                # 可满足性判定的类目展开用）。
                "component_category_members": json.loads(
                    row.get("component_category_members_json") or "{}"
                ),
            }
        except (TypeError, ValueError) as exc:
            # 坏 JSON 不阻断检索，但可见化进 policy（codex 评审硬化：静默降级会让
            # 回归隐身）；闭包侧按无别名运行（保守，不影响判定权）。
            retrieval_policy["projection_runtime_mapping_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

    # DEBT-065 第一波:组件类型格 + 精确目标授权表进 policy(闭包侧组件结构不相容早退
    # 判据消费:授权卡目标叶型 × fragment 单值身份 可证排斥才 NA)。loader ingest 已验证
    # 并产出 {rule_card_id: {target, sha}};坏 JSON 不阻断检索,可见化进 policy(闭包侧
    # 无资产则保守关闭组件结构早退,不影响判定权)。
    lattice_rows = client.read(queries.RULE_COMPONENT_TYPE_LATTICE)
    _lattice_bundle_id: Optional[str] = None
    if lattice_rows:
        try:
            retrieval_policy["component_type_lattice"] = json.loads(
                lattice_rows[0].get("lattice_json") or "{}"
            )
            _lattice_bundle_id = lattice_rows[0].get("rulecard_bundle_id")
        except (TypeError, ValueError) as exc:
            retrieval_policy["component_type_lattice_error"] = f"{type(exc).__name__}: {exc}"
    auth_rows = client.read(queries.RULE_EXACT_FRAGMENT_TARGET_AUTHORIZATIONS)
    _auth_bundle_id: Optional[str] = None
    if auth_rows:
        try:
            retrieval_policy["exact_fragment_target_authorizations"] = json.loads(
                auth_rows[0].get("authorized_targets_json") or "{}"
            )
            _auth_bundle_id = auth_rows[0].get("rulecard_bundle_id")
        except (TypeError, ValueError) as exc:
            retrieval_policy["exact_fragment_target_authorizations_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

    # P1-2:版本冻结同源校验——lattice / 授权表 / 当前卡包的 rulecard_bundle_id 必须
    # 三方一致;任一不一致或缺失 → 不放进 policy(等价缺席,validator 保守关闭组件早退)。
    _bundle_ids = [
        b for b in (_lattice_bundle_id, _auth_bundle_id, rulecard_bundle_id) if b
    ]
    if len(set(_bundle_ids)) != 1 or len(_bundle_ids) != 3:
        retrieval_policy.pop("component_type_lattice", None)
        retrieval_policy.pop("exact_fragment_target_authorizations", None)
        retrieval_policy["component_structure_bundle_mismatch"] = {
            "lattice_bundle_id": _lattice_bundle_id,
            "auth_bundle_id": _auth_bundle_id,
            "current_bundle_id": rulecard_bundle_id,
            "note": "P1-2 同源校验失败——资产 bundle 不一致,保守关闭组件结构早退",
        }

    return build_rule_slice(
        run_id=run_id,
        rulecard_bundle_id=rulecard_bundle_id,
        candidate_rule_cards=candidate_dtos,
        rule_families=rule_families,
        semantic_slots=list(semantic_slots.values()),
        measures=list(measures.values()),
        artifacts=artifact_dtos,
        time_anchors=list(time_anchors.values()),
        source_quotes=list(source_quotes.values()),
        retrieval_policy=retrieval_policy,
    )


# ===========================================================================
# evo-agent v1 §5.3 / §5.4 / §5.5 Skill-aware ranking + verifier candidate floor
# ===========================================================================
#
# spec v1 §5.4 默认 Skill-aware ranking 公式（在 §5.4.4 v0.4 6 路打分基础上叠加）：
#   score = 1.00 * base_fulltext_score
#         + 0.35 * graph_neighbor_boost
#         + 0.30 * skill_trigger_boost
#         + 0.25 * open_reason_priority_boost
#         + 0.20 * artifact_slot_match_boost
#         + 0.15 * recent_policy_success_boost
#         - 1.00 * stale_or_guard_penalty
#
# Policy 可调权重，但必须满足 §5.4 末段：
#   0 <= positive weights <= 2.0
#   -2.0 <= penalties <= 0
#   candidate_floor enabled
#
# spec v1 §5.5 verifier candidate universe floor 不变量：
#   Skill / Policy 不可削窄。verifier candidate universe =
#     base_retrieval ∪ skill_added ∪ neighbor_expansion ∪ all_score_positive
#   减 deterministic_exclusions（spec §5.5.1）。
DEFAULT_V1_RANKING_WEIGHTS: Dict[str, float] = {
    "base_fulltext_score": 1.00,
    "graph_neighbor_boost": 0.35,
    "skill_trigger_boost": 0.30,
    "open_reason_priority_boost": 0.25,
    "artifact_slot_match_boost": 0.20,
    "recent_policy_success_boost": 0.15,
    "stale_or_guard_penalty": -1.00,
}

# spec v1 §5.4 末段 ranking weights bounds
RANKING_WEIGHT_MIN = -2.0
RANKING_WEIGHT_MAX = 2.0

# spec v1 Appendix B.4 candidate_cutoff_policy.verifier_floor 字面量
VERIFIER_FLOOR_LITERAL = "all_score_positive_not_deterministically_excluded"


def _normalize_policy_weights(
    policy: Optional[Any],
) -> Dict[str, float]:
    """从 EvoPolicyVersion 取 ranking_weights，缺失时回退 v1 默认。

    入参 policy 可以是 EvoPolicyVersion 实例（有 .ranking_weights）或 dict。
    weight 越界（[-2.0, 2.0]）抛 ValueError，落实 spec §5.4 weight bounds。
    """
    weights: Dict[str, float] = dict(DEFAULT_V1_RANKING_WEIGHTS)
    if policy is None:
        return weights
    raw = (
        policy.ranking_weights
        if hasattr(policy, "ranking_weights")
        else (policy.get("ranking_weights") if isinstance(policy, dict) else {})
    )
    if not isinstance(raw, dict):
        return weights
    for name, val in raw.items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v < RANKING_WEIGHT_MIN or v > RANKING_WEIGHT_MAX:
            raise ValueError(
                f"EvoPolicy ranking_weights.{name}={v} 越界 "
                f"[{RANKING_WEIGHT_MIN}, {RANKING_WEIGHT_MAX}]（spec v1 §5.4）"
            )
        weights[name] = v
    return weights


def _skill_boost_for_card(
    rule_card_id: str,
    active_skills: List[Any],
) -> Tuple[float, float, float]:
    """对单张候选卡按 active Skill 集合算 3 路 boost。

    返回 (skill_trigger_boost, artifact_slot_match_boost, open_reason_priority_boost)。
    boost 是 0/1 信号汇总（每条 Skill 命中即 +1），由 caller 乘以权重。

    入参 active_skills 可以是 SkillJson list 或 dict list；本函数只读 scope /
    trigger_predicate / scope.rule_cards / scope.semantic_slots /
    scope.artifact_keys / kind 等字段。
    """
    trigger_hits = 0.0
    artifact_hits = 0.0
    open_reason_hits = 0.0
    rcid = str(rule_card_id)
    for sk in active_skills or []:
        scope = (
            sk.scope.model_dump()
            if hasattr(sk, "scope") and hasattr(sk.scope, "model_dump")
            else (sk.get("scope") if isinstance(sk, dict) else {})
        ) or {}
        kind = (
            sk.kind
            if hasattr(sk, "kind")
            else (sk.get("kind") if isinstance(sk, dict) else None)
        )

        # rule_cards 显式命中
        scoped_cards = set(scope.get("rule_cards") or [])
        if rcid in scoped_cards:
            trigger_hits += 1.0

        # retrieval_macro / micro_routing 的 artifact_keys / semantic_slots
        # 暗示 artifact_slot_match_boost
        if kind in {"retrieval_macro", "micro_routing"}:
            if scope.get("artifact_keys") or scope.get("semantic_slots"):
                artifact_hits += 0.5  # 二阶信号

        # diagnostic_hint / micro_routing 的 open_reason 命中
        trigger_pred = (
            sk.trigger_predicate
            if hasattr(sk, "trigger_predicate")
            else (sk.get("trigger_predicate") if isinstance(sk, dict) else {})
        ) or {}
        if isinstance(trigger_pred, dict):
            # 简单匹配：trigger_predicate 含 open_reason_code / blocked_reason_code 字段
            pred_str = repr(trigger_pred)
            if "open_reason" in pred_str or "blocked_reason" in pred_str:
                open_reason_hits += 0.5

    return trigger_hits, artifact_hits, open_reason_hits


def apply_skill_aware_ranking(
    candidates: Dict[str, "CandidateSignals"],
    active_skills: Optional[List[Any]] = None,
    policy: Optional[Any] = None,
) -> List[Tuple[str, float]]:
    """对 §5.4.4 v0.4 6 路打分基础上叠加 Skill / Policy boost（spec v1 §5.4）。

    入参：
    - candidates：rule_card_id → CandidateSignals（v0.4 信号）；
    - active_skills：active SkillJson 列表（可选）；
    - policy：EvoPolicyVersion 实例或 dict（可选）。

    返回：[(rule_card_id, augmented_score)]，按 score 降序、id 升序。

    重要：本函数只算 ranking 影响 LLM context 顺序；verifier candidate floor
    由 `apply_candidate_universe_floor()` 单独保证。
    """
    weights = _normalize_policy_weights(policy)
    augmented: List[Tuple[str, float]] = []
    for rcid, sig in candidates.items():
        base = sig.score()  # v0.4 §5.4.4 score
        skill_trigger, artifact_match, open_reason = _skill_boost_for_card(
            rcid, active_skills or []
        )
        # base_fulltext_score 权重在 base 内已隐含，这里把 base 当作 1.00 系数；
        # v1 默认 weights["base_fulltext_score"]=1.0 不缩放 base。
        base_scaled = base * weights.get("base_fulltext_score", 1.0)
        added = (
            weights.get("skill_trigger_boost", 0.30) * skill_trigger
            + weights.get("artifact_slot_match_boost", 0.20) * artifact_match
            + weights.get("open_reason_priority_boost", 0.25) * open_reason
        )
        # graph_neighbor_boost / recent_policy_success_boost / stale_or_guard_penalty
        # 需要更多上下文（KG 邻居 / sanitized success / staleness），这里没数据时设 0
        # —— 不主动惩罚，符合 spec §5.5 candidate floor 不削窄不变量。
        augmented.append((rcid, base_scaled + added))
    augmented.sort(key=lambda x: (-x[1], x[0]))
    return augmented


def apply_candidate_universe_floor(
    ranked: List[Tuple[str, float]],
    all_candidates: Optional[List[str]] = None,
    deterministic_exclusions: Optional[Set[str]] = None,
) -> Set[str]:
    """返回 verifier candidate universe（spec v1 §5.5 不变量）。

    = 所有 score>0 candidate ∪ all_candidates（base retrieval / skill_added /
      neighbor_expansion 的并集）
    - deterministic_exclusions（applicability false / schema invalid /
      duplicate canonical / bundle mismatch / forbidden source；spec §5.5.1）

    Skill / Policy 不可削窄此集合：本函数对 ranked 输入只用 score>0 判定，
    不接受任何外部 cutoff 参数。

    入参：
    - ranked：apply_skill_aware_ranking 输出（或 v0.4 rank_candidates）；
    - all_candidates：base retrieval / skill / neighbor 三路并集 rule_card_id list
      （可选；缺省时只用 ranked 里 score>0 的）；
    - deterministic_exclusions：deterministic 排除集（spec §5.5.1 5 类）。

    返回：verifier 必须送入 closure 的 rule_card_id 集合（去重 set）。
    """
    floor: Set[str] = set()
    for rcid, score in ranked or []:
        if score > 0:
            floor.add(rcid)
    if all_candidates:
        floor.update(all_candidates)
    # deterministic 排除
    if deterministic_exclusions:
        floor -= set(deterministic_exclusions)
    return floor


def retrieve_rule_slice_with_skills(
    client: Any,
    run_id: str,
    fact_pack: FactPack,
    rulecard_bundle_id: str,
    *,
    regime: str = "mbis",
    building_scope_tags: Optional[List[str]] = None,
    component_scope_tags: Optional[List[str]] = None,
    active_skills: Optional[List[Any]] = None,
    policy: Optional[Any] = None,
) -> RuleSlice:
    """v1 Skill-aware retrieve_rule_slice（spec v1 §5.3 + §5.4 + §5.5）。

    跟 `retrieve_rule_slice()` 入口一致；缺省 active_skills / policy 时退化为
    v0.4 行为。`retrieval_policy` 内额外记录 v1 ranking + verifier_floor。

    candidate universe floor 不变量：本函数在算 verifier_candidate_ids 时
    强制 `apply_candidate_universe_floor()` —— Skill / Policy 即便给了
    cutoff，verifier 全集仍包含所有 score>0 candidate。
    """
    result = run_rule_retrieval(
        client, fact_pack, regime, building_scope_tags, component_scope_tags
    )

    # v1 Skill-aware ranking（不破坏 v0.4 result.ranked）
    augmented_ranked = apply_skill_aware_ranking(
        result.signals,
        active_skills=active_skills,
        policy=policy,
    )
    # verifier floor —— Skill 加入 candidate（这里没有 Skill-added candidate
    # ids，所以 all_candidates = base v0.4 选出的 verifier_candidate_ids）
    verifier_floor = apply_candidate_universe_floor(
        augmented_ranked,
        all_candidates=result.verifier_candidate_ids,
    )

    # 把 v1 ranking + floor 写进 retrieval_policy
    result.verifier_candidate_ids = sorted(verifier_floor)
    slice_ = assemble_rule_slice(
        run_id, rulecard_bundle_id, result, client
    )
    # 增补 v1 retrieval_policy 字段（不删 v0.4 既有 keys）
    slice_.retrieval_policy["v1_ranking_weights"] = (
        _normalize_policy_weights(policy)
    )
    slice_.retrieval_policy["v1_augmented_order"] = [
        cid for cid, _ in augmented_ranked
    ]
    slice_.retrieval_policy["v1_verifier_floor"] = VERIFIER_FLOOR_LITERAL
    slice_.retrieval_policy["v1_verifier_floor_count"] = len(verifier_floor)
    slice_.retrieval_policy["v1_active_skill_count"] = len(active_skills or [])
    return slice_


__all__ = [
    "SCORE_WEIGHTS",
    "CandidateSignals",
    "RuleRetrievalResult",
    "rank_candidates",
    "select_verifier_candidates",
    "collect_candidate_signals",
    "run_rule_retrieval",
    "assemble_rule_slice",
    "retrieve_rule_slice",
    # v1
    "DEFAULT_V1_RANKING_WEIGHTS",
    "RANKING_WEIGHT_MIN",
    "RANKING_WEIGHT_MAX",
    "VERIFIER_FLOOR_LITERAL",
    "apply_skill_aware_ranking",
    "apply_candidate_universe_floor",
    "retrieve_rule_slice_with_skills",
]
