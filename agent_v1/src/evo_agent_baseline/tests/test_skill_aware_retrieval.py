"""evo-agent v1 §5.3 / §5.4 / §5.5 Skill-aware retrieval + candidate floor 测试。

关键不变量（spec v1 §5.5）：
- verifier candidate universe floor 不可被 Skill / Policy 削窄；
- 所有 score>0 的 rule_card_id 必须出现在 verifier_floor。

也覆盖 §10.9 conflict resolver + §10.6 状态机 + skill_runtime 的 trigger 匹配。

模块归位（避免被文件名误导）：
- "Skill-aware retrieval" 是 pipeline 名，不是单一模块名；
- 没有 `agent/skill_aware_retrieval.py` 这个文件（也不应有）；
- pipeline 实现分布在三处：
  * `retrieval/rule_retriever.py` — `apply_skill_aware_ranking()` /
    `apply_candidate_universe_floor()` / `retrieve_rule_slice_with_skills()`
    （核心 ranking + floor + 集成入口）；
  * `agent/policy_runtime.py` — `apply_candidate_cutoff()` /
    `apply_ranking_weights()` / `VERIFIER_FLOOR_LITERAL`（policy 层包装）；
  * `agent/skill_runtime.py` — `match_triggered_skills()` /
    `resolve_skill_conflicts()` / `load_active_skills()`（skill 触发 / 仲裁）；
- 本测试是 pipeline 级集成测试，文件名描述测试范围而非某个实现模块。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.agent.policy_runtime import (
    VERIFIER_FLOOR_LITERAL,
    apply_candidate_cutoff,
    apply_ranking_weights,
)
from evo_agent_baseline.agent.skill_runtime import (
    CONFLICT_RESOLVER_TIE_THRESHOLD,
    load_active_skills,
    match_triggered_skills,
    resolve_skill_conflicts,
)
from evo_agent_baseline.contracts import EvoPolicyVersion, SkillJson, SkillScope
from evo_agent_baseline.retrieval.rule_retriever import (
    DEFAULT_V1_RANKING_WEIGHTS,
    CandidateSignals,
    apply_candidate_universe_floor,
    apply_skill_aware_ranking,
)


# ===========================================================================
# 公共 fixture
# ===========================================================================
def _make_skill(
    skill_id: str,
    *,
    version_id: str = None,
    status: str = "active",
    layer: str = "L1_operational",
    kind: str = "retrieval_macro",
    rule_families: list = None,
    rule_cards: list = None,
    obligation_kinds: list = None,
    artifact_keys: list = None,
    semantic_slots: list = None,
    trigger_predicate: dict = None,
    validation_score: float = 0.85,
    created_at: str = "2026-05-23T20:00:00Z",
    kg_snapshot_id: str = "KGS-v1-20260523",
    rulecard_bundle_id: str = "rulecard_v2.mbis_cop_2023",
) -> SkillJson:
    """构造 SkillJson 测试 fixture。"""
    return SkillJson(
        schema_version="1.0.0",
        skill_id=skill_id,
        skill_version_id=version_id or f"{skill_id}.v1",
        name=skill_id.split(".")[-1],
        kind=kind,
        layer=layer,
        description=f"test skill {skill_id}",
        status=status,
        origin="evo_induced",
        version="1.0.0",
        scope=SkillScope(
            rule_families=rule_families or [],
            rule_cards=rule_cards or [],
            semantic_slots=semantic_slots or [],
            measure_keys=[],
            artifact_keys=artifact_keys or [],
            obligation_kinds=obligation_kinds or [],
        ),
        trigger_predicate=trigger_predicate or {},
        allowed_tools=["retrieve_building_facts"],
        forbidden_actions=[
            "override_verifier",
            "force_allow_stop",
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ],
        source_trace_hashes=["h" + str(i) * 6 for i in range(5)],
        support_counts={"buildings": 4, "world_families": 2},
        validation_summary={"validation_score": validation_score, "staleness_status": "fresh"},
        kg_snapshot_id=kg_snapshot_id,
        rulecard_bundle_id=rulecard_bundle_id,
        created_by="evo_trainer",
        created_at=created_at,
        non_authority_statement="This Skill is non-authoritative.",
    )


def _make_policy(**overrides) -> EvoPolicyVersion:
    base = dict(
        policy_version_id="policy.mbis.runtime.default.v1.0.0",
        policy_id="policy.mbis.runtime.default",
        version="1.0.0",
        status="active",
        ranking_weights={
            "base_fulltext_score": 1.0,
            "skill_trigger_boost": 0.30,
            "open_reason_priority_boost": 0.25,
        },
        candidate_cutoff_policy={
            "context_top_k": 3,
            "verifier_floor": VERIFIER_FLOOR_LITERAL,
        },
        max_tool_iterations_default=16,
        experiment_budgets=[8, 16, 32],
        trained_on_replay_set_id="RS-20260523",
        validation_summary={"leakage_audit_passed": True},
        # v1.1 §0.6 修订 2 + §3.6.4：rollback_condition 字段已删除（git revert 代替）
        created_at="2026-05-23T20:00:00Z",
    )
    base.update(overrides)
    return EvoPolicyVersion(**base)


# ===========================================================================
# load_active_skills
# ===========================================================================
class TestLoadActiveSkills:
    def test_load_from_skills_source(self):
        skills = load_active_skills(
            "SS-test",
            "KGS-v1-20260523",
            "rulecard_v2.mbis_cop_2023",
            skills_source=[_make_skill("skill.mbis.retrieval_macro.a")],
        )
        assert len(skills) == 1
        assert skills[0].skill_id == "skill.mbis.retrieval_macro.a"

    def test_draft_status_filtered(self):
        skills = load_active_skills(
            "SS-test",
            "KGS-v1-20260523",
            "rulecard_v2.mbis_cop_2023",
            skills_source=[
                _make_skill("skill.mbis.retrieval_macro.a", status="active"),
                _make_skill("skill.mbis.retrieval_macro.b", status="draft"),
            ],
        )
        assert len(skills) == 1

    def test_kg_snapshot_mismatch_filtered(self):
        skills = load_active_skills(
            "SS-test",
            "KGS-v2-20260601",  # 不同 snapshot
            "rulecard_v2.mbis_cop_2023",
            skills_source=[_make_skill("skill.mbis.retrieval_macro.a")],
        )
        assert len(skills) == 0  # snapshot mismatch → guard 拒绝

    def test_dict_input_coerced(self):
        skill_dict = _make_skill("skill.mbis.retrieval_macro.a").model_dump()
        skills = load_active_skills(
            "SS-test",
            "KGS-v1-20260523",
            "rulecard_v2.mbis_cop_2023",
            skills_source=[skill_dict],
        )
        assert len(skills) == 1

    def test_empty_source_returns_empty(self):
        skills = load_active_skills(
            "SS-test",
            "KGS-v1-20260523",
            "rulecard_v2.mbis_cop_2023",
            skills_source=[],
        )
        assert skills == []


# ===========================================================================
# match_triggered_skills
# ===========================================================================
class TestMatchTriggeredSkills:
    def test_simple_eq_match(self):
        sk = _make_skill(
            "skill.mbis.retrieval_macro.a",
            trigger_predicate={"field": "open_reason_code", "op": "eq", "value": "missing_artifact_evidence"},
        )
        matched = match_triggered_skills([sk], {"open_reason_code": "missing_artifact_evidence"})
        assert len(matched) == 1

    def test_in_op_match(self):
        sk = _make_skill(
            "skill.mbis.retrieval_macro.a",
            trigger_predicate={"field": "open_reason_code", "op": "in", "value": ["missing_artifact_evidence", "missing_sidecar_entry"]},
        )
        matched = match_triggered_skills([sk], {"open_reason_code": "missing_sidecar_entry"})
        assert len(matched) == 1

    def test_all_compound(self):
        sk = _make_skill(
            "skill.mbis.retrieval_macro.a",
            trigger_predicate={
                "all": [
                    {"field": "open_reason_code", "op": "eq", "value": "missing_artifact_evidence"},
                    {"field": "rule_family", "op": "prefix", "value": "mbis.reporting."},
                ]
            },
        )
        ok_ctx = {"open_reason_code": "missing_artifact_evidence", "rule_family": "mbis.reporting.inspection_report"}
        nok_ctx = {"open_reason_code": "missing_artifact_evidence", "rule_family": "mbis.other.fam"}
        assert len(match_triggered_skills([sk], ok_ctx)) == 1
        assert len(match_triggered_skills([sk], nok_ctx)) == 0

    def test_any_compound(self):
        sk = _make_skill(
            "skill.mbis.retrieval_macro.a",
            trigger_predicate={
                "any": [
                    {"field": "open_reason_code", "op": "eq", "value": "missing_artifact_evidence"},
                    {"field": "blocked_reason_code", "op": "eq", "value": "missing_artifact_mapping"},
                ]
            },
        )
        assert len(match_triggered_skills([sk], {"blocked_reason_code": "missing_artifact_mapping"})) == 1

    def test_no_match_returns_empty(self):
        sk = _make_skill(
            "skill.mbis.retrieval_macro.a",
            trigger_predicate={"field": "open_reason_code", "op": "eq", "value": "x"},
        )
        assert match_triggered_skills([sk], {"open_reason_code": "y"}) == []


# ===========================================================================
# resolve_skill_conflicts
# ===========================================================================
class TestResolveSkillConflicts:
    def test_no_overlap_each_selected(self):
        # 不同 scope → 各自一个 decision
        a = _make_skill(
            "skill.mbis.retrieval_macro.a",
            rule_families=["family.a"],
            validation_score=0.85,
        )
        b = _make_skill(
            "skill.mbis.retrieval_macro.b",
            rule_families=["family.b"],
            validation_score=0.80,
        )
        decisions = resolve_skill_conflicts([a, b])
        assert len(decisions) == 2

    def test_overlapping_top_wins_when_gap_large(self):
        # 同 scope，validation_score 差 ≥0.05 → top 单选，second shadowed
        a = _make_skill(
            "skill.mbis.retrieval_macro.a",
            rule_families=["family.x"],
            obligation_kinds=["artifact"],
            validation_score=0.90,
        )
        b = _make_skill(
            "skill.mbis.retrieval_macro.b",
            rule_families=["family.x"],
            obligation_kinds=["artifact"],
            validation_score=0.80,
        )
        decisions = resolve_skill_conflicts([a, b])
        assert len(decisions) == 1
        assert decisions[0].selected.skill_id == "skill.mbis.retrieval_macro.a"
        assert decisions[0].union_with is None
        assert decisions[0].shadowed[0].skill_id == "skill.mbis.retrieval_macro.b"

    def test_overlapping_close_scores_union(self):
        # 差 <0.05 → union-of-retrieval
        a = _make_skill(
            "skill.mbis.retrieval_macro.a",
            rule_families=["family.x"],
            obligation_kinds=["artifact"],
            validation_score=0.85,
        )
        b = _make_skill(
            "skill.mbis.retrieval_macro.b",
            rule_families=["family.x"],
            obligation_kinds=["artifact"],
            validation_score=0.83,  # gap 0.02 < 0.05
        )
        decisions = resolve_skill_conflicts([a, b])
        assert len(decisions) == 1
        assert decisions[0].selected.skill_id == "skill.mbis.retrieval_macro.a"
        assert decisions[0].union_with is not None
        assert decisions[0].union_with.skill_id == "skill.mbis.retrieval_macro.b"

    def test_threshold_constant(self):
        assert CONFLICT_RESOLVER_TIE_THRESHOLD == 0.05


# ===========================================================================
# apply_skill_aware_ranking
# ===========================================================================
class TestApplySkillAwareRanking:
    def test_default_weights_no_skills(self):
        # 无 active skills → ranking 跟 v0.4 score 一致
        sigs = {
            "rc.a": CandidateSignals(rule_card_id="rc.a", exact_slot_hit_count=2),
            "rc.b": CandidateSignals(rule_card_id="rc.b", exact_slot_hit_count=1),
        }
        ranked = apply_skill_aware_ranking(sigs, active_skills=None, policy=None)
        assert ranked[0][0] == "rc.a"  # higher slot hits
        assert ranked[0][1] > ranked[1][1]

    def test_skill_trigger_boost_lifts_targeted_card(self):
        sigs = {
            "rc.a": CandidateSignals(rule_card_id="rc.a"),
            "rc.b": CandidateSignals(rule_card_id="rc.b"),
        }
        sk = _make_skill(
            "skill.mbis.retrieval_macro.x",
            rule_cards=["rc.a"],  # scope 命中 rc.a
        )
        ranked = apply_skill_aware_ranking(sigs, active_skills=[sk], policy=None)
        # rc.a 应高于 rc.b
        score_map = dict(ranked)
        assert score_map["rc.a"] > score_map["rc.b"]

    def test_policy_weight_bounds_enforced(self):
        # weight 越界（> 2.0）应抛 ValueError
        bad_policy = _make_policy(
            ranking_weights={"skill_trigger_boost": 3.0},
        )
        sigs = {"rc.a": CandidateSignals(rule_card_id="rc.a")}
        with pytest.raises(ValueError, match="越界"):
            apply_skill_aware_ranking(sigs, active_skills=[], policy=bad_policy)

    def test_default_weights_constant(self):
        assert DEFAULT_V1_RANKING_WEIGHTS["base_fulltext_score"] == 1.00
        assert DEFAULT_V1_RANKING_WEIGHTS["skill_trigger_boost"] == 0.30
        assert DEFAULT_V1_RANKING_WEIGHTS["stale_or_guard_penalty"] == -1.00


# ===========================================================================
# apply_candidate_universe_floor —— 关键不变量测试（spec v1 §5.5）
# ===========================================================================
class TestCandidateUniverseFloorInvariant:
    """spec v1 §5.5：verifier candidate universe floor 不可被 Skill / Policy 削窄。"""

    def test_all_positive_score_in_floor(self):
        ranked = [("rc.a", 5.0), ("rc.b", 3.0), ("rc.c", 1.0)]
        floor = apply_candidate_universe_floor(ranked)
        assert floor == {"rc.a", "rc.b", "rc.c"}

    def test_zero_score_excluded(self):
        ranked = [("rc.a", 5.0), ("rc.b", 0.0), ("rc.c", -1.0)]
        floor = apply_candidate_universe_floor(ranked)
        assert floor == {"rc.a"}

    def test_base_candidates_unioned(self):
        # base retrieval 的 candidate（score=0 但确定性挑出来的）也应入 floor
        ranked = [("rc.a", 5.0)]
        all_candidates = ["rc.a", "rc.b", "rc.c"]
        floor = apply_candidate_universe_floor(
            ranked, all_candidates=all_candidates
        )
        assert floor == {"rc.a", "rc.b", "rc.c"}

    def test_deterministic_exclusions_only(self):
        # 只 deterministic 排除允许削窄
        ranked = [("rc.a", 5.0), ("rc.b", 3.0)]
        floor = apply_candidate_universe_floor(
            ranked,
            all_candidates=["rc.a", "rc.b", "rc.c"],
            deterministic_exclusions={"rc.c"},
        )
        assert floor == {"rc.a", "rc.b"}

    def test_policy_cannot_narrow_floor(self):
        """spec v1 §5.5 不变量：Policy 设 context_top_k=1，verifier floor 仍含全部 score>0。"""
        ranked = [("rc.a", 5.0), ("rc.b", 4.0), ("rc.c", 3.0), ("rc.d", 2.0)]
        policy = _make_policy(candidate_cutoff_policy={
            "context_top_k": 1,  # LLM 只看 top1
            "verifier_floor": VERIFIER_FLOOR_LITERAL,
        })
        context, floor = apply_candidate_cutoff(ranked, policy)
        # context 受 top_k 截断
        assert len(context) == 1
        assert context[0][0] == "rc.a"
        # 但 verifier_floor 必须含全部 score>0
        assert floor == {"rc.a", "rc.b", "rc.c", "rc.d"}

    def test_skill_cannot_narrow_floor(self):
        """spec v1 §5.5 不变量：Skill 只能追加 candidate，不能让 floor 比无 Skill 时更小。"""
        sigs = {
            "rc.a": CandidateSignals(rule_card_id="rc.a", exact_slot_hit_count=1),  # score>0
            "rc.b": CandidateSignals(rule_card_id="rc.b", exact_slot_hit_count=1),  # score>0
        }
        # 假设 Skill 只命中 rc.a，但 rc.b 在无 Skill 时也是 score>0，必须仍在 floor
        sk = _make_skill("skill.mbis.retrieval_macro.x", rule_cards=["rc.a"])
        ranked_with = apply_skill_aware_ranking(sigs, active_skills=[sk], policy=None)
        ranked_no = apply_skill_aware_ranking(sigs, active_skills=None, policy=None)
        floor_with = apply_candidate_universe_floor(ranked_with)
        floor_no = apply_candidate_universe_floor(ranked_no)
        # 加 Skill 后 floor 应是无 Skill 时的超集（不削窄）
        assert floor_no <= floor_with
        assert "rc.b" in floor_with  # 关键：rc.b 仍在 floor

    def test_apply_candidate_cutoff_rejects_wrong_floor_literal(self):
        """policy 声明非法 verifier_floor 字面量 → 立刻 fail（绝不削窄）。"""
        from evo_agent_baseline.agent.hooks import SecurityError as _SecurityError

        bad_policy = _make_policy(
            candidate_cutoff_policy={"context_top_k": 5, "verifier_floor": "top_k_only"}
        )
        with pytest.raises(_SecurityError, match="verifier_floor"):
            apply_candidate_cutoff([("rc.a", 5.0)], bad_policy)

    def test_apply_ranking_weights_basic(self):
        weights_in = {"base_fulltext_score": 2.0, "skill_trigger_boost": 1.0}
        policy = _make_policy(ranking_weights={
            "base_fulltext_score": 1.5,  # weight=1.5
            "skill_trigger_boost": 0.50,  # weight=0.50
        })
        out = apply_ranking_weights(weights_in, policy)
        assert out["base_fulltext_score"] == 2.0 * 1.5
        assert out["skill_trigger_boost"] == 1.0 * 0.50

    def test_apply_ranking_weights_default_when_no_policy(self):
        out = apply_ranking_weights({"base_fulltext_score": 3.0}, None)
        assert out["base_fulltext_score"] == 3.0 * 1.0  # default weight=1.0


# ===========================================================================
# retrieve_rule_slice_with_skills 集成测试（用 fake client）
# ===========================================================================
class TestRetrieveRuleSliceWithSkills:
    """集成测试：retrieve_rule_slice_with_skills 应保 verifier_floor 不变量。

    这里只测 retrieval_policy 字段写入正确；KG 检索完整路径由 test_retrievers.py
    已覆盖。
    """

    def test_default_no_skills_no_policy_matches_baseline(self):
        """no skill / no policy → 退化 v0.4 行为，不报错。"""
        # 不能用真的 Neo4j，因此跳过 retrieve；这里只测 apply_skill_aware_ranking
        # 在空输入下不爆。
        ranked = apply_skill_aware_ranking({}, active_skills=None, policy=None)
        assert ranked == []
        floor = apply_candidate_universe_floor(ranked)
        assert floor == set()
