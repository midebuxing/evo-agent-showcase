"""Skill Validation 5 Gate 单元测试（spec v1 §9.4）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Sequence

import pytest

from evo_agent_baseline.contracts import (
    EvoRunStep,
    EvoRunTrace,
    EvoSkillPackage,
    SkillJson,
    SkillScope,
)
from evo_agent_baseline.evo.skill_induction import (
    HARD_FORBIDDEN_ACTIONS,
    InductionCandidate,
    generate_draft_skill_package,
)
from evo_agent_baseline.evo.skill_validation import (
    VALIDATOR_VERSION,
    run_gate0_static,
    run_gate1_schema_provenance,
    run_gate2_replay_ab,
    run_gate3_stability,
    run_gate4_holdout_counterfactual,
    validate_skill,
)


# ---------------- helpers ----------------------------------------------------


def _make_valid_pkg(*, source_trace_count: int = 5) -> EvoSkillPackage:
    cand = InductionCandidate(
        trigger_type="repeated_failure",
        pattern_key=("mbis.reporting.x", "artifact_evidence", "report_field", "missing_artifact_evidence"),
        pattern_dimension={
            "rule_family": "mbis.reporting.x",
            "semantic_slot_class": "artifact_evidence",
            "obligation_kind": "report_field",
            "reason_code": "missing_artifact_evidence",
        },
        source_trace_ids=[f"ERT-{i}" for i in range(source_trace_count)],
        support_counts={
            "trace_count": source_trace_count,
            "building_count": 3,
            "world_family_count": 2,
        },
        suggested_kind="retrieval_macro",
    )
    return generate_draft_skill_package(cand)


def _make_trace(idx: int) -> EvoRunTrace:
    return EvoRunTrace(
        trace_id=f"ERT-{idx}",
        run_id=f"CAR-{idx}",
        world_id_hash=f"sha256:world_{idx%3}",
        building_id_hash=f"sha256:bld_{idx%4}",
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
        agent_version="v1.0.0",
        verifier_version="v1.0.0",
        evo_policy_version_id="policy.mbis.runtime.default.v1.0.0",
        active_skill_set_id="SS-test",
        active_skill_version_ids=[],
        input_guard_hash="sha256:guard",
        retrieval_summary={},
        candidate_universe_hash="sha256:universe",
        fact_pack_hash="sha256:facts",
        rule_slice_hash="sha256:rules",
        closure_result_ref="closure_ref",
        closure_summary={"closed_count": 5, "open_count": 1, "blocked_count": 0},
        report_ref=None,
        hook_results_hash="sha256:hooks",
        tool_call_count=10,
        llm_iterations_used=3,
        cost={},
        fallback_reason=None,
        steps=[],
        sanitized_feedback_refs=[],
        trace_visibility="agent_visible_trace",
        forbidden_scan_passed=True,
        source_visibility_audit_passed=True,
        schema_audit_passed=True,
        candidate_floor_passed=True,
        created_at="2026-05-24T00:00:00Z",
    )


# ---------------- Gate 0 ----------------------------------------------------


def test_gate0_passes_on_valid_pkg():
    pkg = _make_valid_pkg()
    rec = run_gate0_static(pkg)
    assert rec.passed
    assert rec.leakage_hits == []
    assert rec.failure_reasons == []


def test_gate0_fails_if_hard_forbidden_action_missing():
    pkg = _make_valid_pkg()
    bad_skill = pkg.skill.model_copy(
        update={
            "forbidden_actions": [a for a in HARD_FORBIDDEN_ACTIONS if a != "override_verifier"]
        }
    )
    bad_pkg = pkg.model_copy(update={"skill": bad_skill})
    rec = run_gate0_static(bad_pkg)
    assert not rec.passed
    assert any("override_verifier" in r for r in rec.failure_reasons)


def test_gate0_fails_on_w2_path_leakage():
    pkg = _make_valid_pkg()
    bad_skill = pkg.skill.model_copy(
        update={
            "description": "this skill reads w2_projection.parquet to decide compliance"
        }
    )
    bad_pkg = pkg.model_copy(update={"skill": bad_skill})
    rec = run_gate0_static(bad_pkg)
    assert not rec.passed
    assert any("w2_token" in h for h in rec.leakage_hits)


def test_gate0_fails_on_verifier_override_phrase():
    pkg = _make_valid_pkg()
    bad_skill = pkg.skill.model_copy(
        update={"description": "I will override verifier and force allow_stop"}
    )
    bad_pkg = pkg.model_copy(update={"skill": bad_skill})
    rec = run_gate0_static(bad_pkg)
    assert not rec.passed
    assert any("override_phrase" in h for h in rec.leakage_hits)


def test_gate0_fails_on_allowed_tool_outside_allowlist():
    pkg = _make_valid_pkg()
    rec = run_gate0_static(pkg, runtime_tool_allowlist=["only_this_one"])
    assert not rec.passed
    assert any("allowed_tools_outside_allowlist" in r for r in rec.failure_reasons)


# ---------------- Gate 1 ----------------------------------------------------


def test_gate1_passes_on_valid_pkg_with_5_traces_3_buildings():
    pkg = _make_valid_pkg(source_trace_count=5)
    rec = run_gate1_schema_provenance(pkg, promote_target="active")
    assert rec.passed, rec.failure_reasons


def test_gate1_fails_when_source_traces_less_than_5_for_active():
    """v1.1 §0.6.1 + §9.5：active 目标硬约束（draft → active 必须 ≥5 traces）。

    v1.0 旧版本是 ``candidate`` 阶段约束；v1.1 §0.6 修订 2 + §9.5 把所有 Gate
    合并为单一 gate 集合（draft → active 必须 Gate 0-4 全 pass + ≥5 traces +
    ≥3 buildings 或 ≥2 world families），故约束触发点为 ``promote_target='active'``。
    """
    pkg = _make_valid_pkg(source_trace_count=2)
    rec = run_gate1_schema_provenance(pkg, promote_target="active")
    assert not rec.passed
    assert any("source_trace_hashes_lt_5" in r for r in rec.failure_reasons)


def test_gate1_passes_for_draft_with_fewer_traces():
    """draft 阶段允许 source_trace_hashes < 5（spec v1 §9.3.3）。"""
    pkg = _make_valid_pkg(source_trace_count=2)
    rec = run_gate1_schema_provenance(pkg, promote_target="draft")
    assert rec.passed


def test_gate1_fails_on_trigger_predicate_field_outside_allowlist():
    pkg = _make_valid_pkg()
    bad_skill = pkg.skill.model_copy(
        update={"trigger_predicate": {"all": [{"field": "expected_verdict", "op": "eq", "value": "violated"}]}}
    )
    bad_pkg = pkg.model_copy(update={"skill": bad_skill})
    rec = run_gate1_schema_provenance(bad_pkg, promote_target="active")
    assert not rec.passed
    assert any("trigger_predicate_forbidden_field" in r for r in rec.failure_reasons)


def test_gate1_fails_when_scope_rule_family_not_in_bundle():
    pkg = _make_valid_pkg()
    rec = run_gate1_schema_provenance(
        pkg,
        bundle_rule_families=["mbis.other.family"],
        promote_target="active",
    )
    assert not rec.passed
    assert any("scope_rule_families_not_in_bundle" in r for r in rec.failure_reasons)


# ---------------- Gate 2（v1.1 per-case paired A/B framework） ---------------
#
# Runner 契约（spec §9.4.3 + skill_validation 模块 docstring）：
#     replay_runner(case: Mapping, active_skills: Sequence[SkillJson]) -> Mapping
# Gate 内部对每个 case 跑两次（active=baseline vs active=baseline+candidate），
# 自己 paired aggregate；mock runner 只需对"是否含 candidate"作出区分即可。


def _has_candidate(active_skills, pkg) -> bool:
    return any(s.skill_version_id == pkg.skill.skill_version_id for s in active_skills)


def _gate2_runner_clean_improvement(pkg):
    """B 侧（含 candidate）closure 改善 + target_metric 提升 + tool_calls 下降。"""
    def _runner(case, active_skills):
        if _has_candidate(active_skills, pkg):
            return {
                "closure_open_count": 0,
                "closure_blocked_count": 0,
                "closure_satisfied_count": 5,
                "closure_status": "closed",
                "allow_stop": True,
                "allow_stop_from_verifier": True,
                "retrieval_coverage": 0.85,
                "report_citation_coverage": 0.90,
                "target_metric": 0.85,
                "candidate_floor_pass": True,
                "tool_calls": 8.0,
                "leakage_hits": [],
                "forbidden_source_hits": [],
            }
        return {
            "closure_open_count": 0,
            "closure_blocked_count": 0,
            "closure_satisfied_count": 5,
            "closure_status": "closed",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "retrieval_coverage": 0.70,
            "report_citation_coverage": 0.80,
            "target_metric": 0.70,
            "candidate_floor_pass": True,
            "tool_calls": 10.0,
            "leakage_hits": [],
            "forbidden_source_hits": [],
        }
    return _runner


def _gate2_runner_with_regression(pkg):
    """B 侧让一些原本 closed 的 case 退化为 open（closure regression）。"""
    call_counter = {"n": 0}
    def _runner(case, active_skills):
        call_counter["n"] += 1
        if _has_candidate(active_skills, pkg):
            # 前 3 个 case 退化为 open
            is_first_three = call_counter["n"] <= 6 and call_counter["n"] % 2 == 0
            return {
                "closure_open_count": 2 if is_first_three else 0,
                "closure_blocked_count": 0,
                "closure_satisfied_count": 3 if is_first_three else 5,
                "closure_status": "open" if is_first_three else "closed",
                "allow_stop": False if is_first_three else True,
                "allow_stop_from_verifier": True,
                "retrieval_coverage": 0.85,
                "report_citation_coverage": 0.90,
                "target_metric": 0.85,
                "candidate_floor_pass": True,
                "tool_calls": 8.0,
                "leakage_hits": [],
                "forbidden_source_hits": [],
            }
        return {
            "closure_open_count": 0,
            "closure_blocked_count": 0,
            "closure_satisfied_count": 5,
            "closure_status": "closed",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "retrieval_coverage": 0.70,
            "report_citation_coverage": 0.80,
            "target_metric": 0.70,
            "candidate_floor_pass": True,
            "tool_calls": 10.0,
            "leakage_hits": [],
            "forbidden_source_hits": [],
        }
    return _runner


def _gate2_runner_with_leakage(pkg):
    """B 侧出现 leakage hit。"""
    def _runner(case, active_skills):
        base = _gate2_runner_clean_improvement(pkg)(case, active_skills)
        if _has_candidate(active_skills, pkg):
            base = {**base, "leakage_hits": ["w2_token::projection_refs"]}
        return base
    return _runner


def _gate2_runner_with_open_blocked_increase(pkg):
    """B 侧让 open+blocked 总数比 A 侧上升。"""
    def _runner(case, active_skills):
        if _has_candidate(active_skills, pkg):
            return {
                "closure_open_count": 3,
                "closure_blocked_count": 1,
                "closure_satisfied_count": 1,
                "closure_status": "open",
                "allow_stop": False,
                "allow_stop_from_verifier": True,
                "retrieval_coverage": 0.85,
                "report_citation_coverage": 0.90,
                "target_metric": 0.85,
                "candidate_floor_pass": True,
                "tool_calls": 8.0,
                "leakage_hits": [],
                "forbidden_source_hits": [],
            }
        return {
            "closure_open_count": 1,
            "closure_blocked_count": 0,
            "closure_satisfied_count": 4,
            "closure_status": "open",
            "allow_stop": False,
            "allow_stop_from_verifier": True,
            "retrieval_coverage": 0.70,
            "report_citation_coverage": 0.80,
            "target_metric": 0.70,
            "candidate_floor_pass": True,
            "tool_calls": 10.0,
            "leakage_hits": [],
            "forbidden_source_hits": [],
        }
    return _runner


def test_gate2_passes_with_clean_per_case_runner():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate2_replay_ab(pkg, traces, replay_runner=_gate2_runner_clean_improvement(pkg))
    assert rec.passed, rec.failure_reasons
    assert rec.closure_regression_count == 0
    assert rec.leakage_hits == []


def test_gate2_fails_on_closure_regression():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate2_replay_ab(pkg, traces, replay_runner=_gate2_runner_with_regression(pkg))
    assert not rec.passed
    assert rec.closure_regression_count > 0
    assert any("closure_regression" in r for r in rec.failure_reasons)


def test_gate2_fails_on_leakage_hits():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate2_replay_ab(pkg, traces, replay_runner=_gate2_runner_with_leakage(pkg))
    assert not rec.passed
    assert any("w2_token" in h for h in rec.leakage_hits)
    assert "leakage_hits_nonzero" in rec.failure_reasons


def test_gate2_fails_on_open_blocked_increase():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate2_replay_ab(
        pkg, traces, replay_runner=_gate2_runner_with_open_blocked_increase(pkg)
    )
    assert not rec.passed
    assert any("open_blocked_increase" in r for r in rec.failure_reasons)


def test_gate2_empty_replay_set_fails():
    """Codex review 2026-05-27 C1[P2]: 空 replay_set 不可 trivial pass Gate 2。
    spec §9.4 promotion 要求 ≥5 source traces；候选无可比较实证必 fail。
    """
    pkg = _make_valid_pkg()
    rec = run_gate2_replay_ab(pkg, [], replay_runner=_gate2_runner_clean_improvement(pkg))
    assert not rec.passed
    assert "empty_replay_set" in " ".join(rec.failure_reasons)
    assert rec.run_count == 0


def test_gate2_efficiency_claim_threshold():
    """guardrails.claim_efficiency=True 时 median tool calls 必须下降 ≥15%。
    threshold 显式参数化：传 -0.30（要求降 30%）让默认 -20% 的改善不达标。"""
    pkg = _make_valid_pkg()
    # 在 guardrails 里加 claim_efficiency=True
    skill_with_claim = pkg.skill.model_copy(
        update={"guardrails": {**pkg.skill.guardrails, "claim_efficiency": True}}
    )
    pkg2 = pkg.model_copy(update={"skill": skill_with_claim})
    traces = [_make_trace(i) for i in range(10)]
    # 默认 threshold=-0.15：clean runner 跑出 -20% 下降，达标
    rec_default = run_gate2_replay_ab(
        pkg2, traces, replay_runner=_gate2_runner_clean_improvement(pkg2)
    )
    assert rec_default.passed, rec_default.failure_reasons
    # 提高 threshold 到 -0.30（要求降 30%）：-20% 改善不达标，应 fail
    rec_strict = run_gate2_replay_ab(
        pkg2,
        traces,
        replay_runner=_gate2_runner_clean_improvement(pkg2),
        efficiency_improvement_threshold=-0.30,
    )
    assert not rec_strict.passed
    assert any("efficiency_claim_unmet" in r for r in rec_strict.failure_reasons)


# ---------------- Gate 3（v1.1 per-case + seed K=5 framework） --------------
#
# Runner 契约（spec §9.4.4 + skill_validation 模块 docstring）：
#     seed_variation_runner(case: Mapping, seed: int,
#                            active_skills: Sequence[SkillJson]) -> Mapping
# Gate 内部对每个 case 跑 K 次（K 个 seed），自己做 per-case 跨 seed 一致性比较。


def _gate3_runner_deterministic():
    """K=5 seeds 完全同样的输出——spec §6.9 deterministic repeatability。"""
    def _runner(case, seed, active_skills):
        return {
            "closure_summary_hash": "sha256:same",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "report_guard_pass": True,
            "infinite_loop": False,
            "tool_calls": 10.0,
            "forbidden_scan_pass": True,
        }
    return _runner


def _gate3_runner_seed_dependent():
    """K=5 seeds 不一致——closure_summary_hash 随 seed 变化。"""
    def _runner(case, seed, active_skills):
        return {
            "closure_summary_hash": f"sha256:seed_{seed}",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "report_guard_pass": True,
            "infinite_loop": False,
            "tool_calls": 10.0,
            "forbidden_scan_pass": True,
        }
    return _runner


def _gate3_runner_allow_stop_not_from_verifier():
    """allow_stop 是 True 但 allow_stop_from_verifier=False——
    Skill 自己决定停止 = authority 违规。"""
    def _runner(case, seed, active_skills):
        return {
            "closure_summary_hash": "sha256:same",
            "allow_stop": True,
            "allow_stop_from_verifier": False,  # 违规：非 verifier 产生
            "report_guard_pass": True,
            "infinite_loop": False,
            "tool_calls": 10.0,
            "forbidden_scan_pass": True,
        }
    return _runner


def test_gate3_passes_with_K5_consistent_runs():
    """spec §6.9 deterministic repeatability：K=5 seed 一致 → PASS。"""
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(5)]
    rec = run_gate3_stability(
        pkg, traces, K=5, seed_variation_runner=_gate3_runner_deterministic()
    )
    assert rec.passed, rec.failure_reasons
    assert rec.allow_stop_authority_check


def test_gate3_fails_when_seeds_diverge():
    """K=5 seed 出现不同 closure hash → FAIL。"""
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(5)]
    rec = run_gate3_stability(
        pkg, traces, K=5, seed_variation_runner=_gate3_runner_seed_dependent()
    )
    assert not rec.passed
    assert any("closure_summary_inconsistent" in r for r in rec.failure_reasons)


def test_gate3_K2_boundary_works():
    """K=2 边界（最小允许）；K=1 抛 ValueError。"""
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(3)]
    rec = run_gate3_stability(
        pkg, traces, K=2, seed_variation_runner=_gate3_runner_deterministic()
    )
    assert rec.passed
    with pytest.raises(ValueError, match="K 必须 >= 2"):
        run_gate3_stability(
            pkg, traces, K=1, seed_variation_runner=_gate3_runner_deterministic()
        )


def test_gate3_rejects_seeds_length_mismatch():
    """seeds 长度若指定，必须 == K。"""
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(3)]
    with pytest.raises(ValueError, match="seeds length"):
        run_gate3_stability(
            pkg,
            traces,
            K=5,
            seeds=[1, 2, 3],  # 长度 3 != K=5
            seed_variation_runner=_gate3_runner_deterministic(),
        )


def test_gate3_fails_on_allow_stop_not_from_verifier():
    """authority check：allow_stop 必须由 verifier 产生（spec §1.3 Authority Matrix）。"""
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(3)]
    rec = run_gate3_stability(
        pkg,
        traces,
        K=5,
        seed_variation_runner=_gate3_runner_allow_stop_not_from_verifier(),
    )
    assert not rec.passed
    assert "allow_stop_not_from_verifier" in rec.failure_reasons
    assert not rec.allow_stop_authority_check


# ---------------- Gate 4（v1.1 holdout + counterfactual paired） ----------
#
# Runner 契约（spec §9.4.5）：
#     holdout_runner(case, active_skills) -> Mapping  # 同 ReplayRunner
#     counterfactual_runner(case, active_skills, perturbation) -> Mapping


def _gate4_holdout_runner_clean(pkg):
    """holdout B 侧 target_metric 提升，零 leakage / literal_dep / verdict_like。"""
    def _runner(case, active_skills):
        if _has_candidate(active_skills, pkg):
            return {
                "closure_open_count": 0,
                "closure_blocked_count": 0,
                "closure_satisfied_count": 5,
                "closure_status": "closed",
                "allow_stop": True,
                "allow_stop_from_verifier": True,
                "retrieval_coverage": 0.85,
                "report_citation_coverage": 0.90,
                "target_metric": 0.85,
                "candidate_floor_pass": True,
                "tool_calls": 8.0,
                "leakage_hits": [],
                "forbidden_source_hits": [],
                "literal_dependency_hit": False,
                "verdict_like_output": False,
                "w2_reconstruction_probe": 1.0,
                "report_unsupported_claim_rate": 0.05,
            }
        return {
            "closure_open_count": 0,
            "closure_blocked_count": 0,
            "closure_satisfied_count": 5,
            "closure_status": "closed",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "retrieval_coverage": 0.70,
            "report_citation_coverage": 0.80,
            "target_metric": 0.70,
            "candidate_floor_pass": True,
            "tool_calls": 10.0,
            "leakage_hits": [],
            "forbidden_source_hits": [],
            "literal_dependency_hit": False,
            "verdict_like_output": False,
            "w2_reconstruction_probe": 0.5,
            "report_unsupported_claim_rate": 0.05,
        }
    return _runner


def _gate4_counterfactual_runner_clean(pkg):
    """counterfactual：6 perturbation 后 candidate 效果消失（target=baseline level）。"""
    def _runner(case, active_skills, perturbation):
        return {
            "closure_open_count": 0,
            "closure_blocked_count": 0,
            "closure_satisfied_count": 5,
            "closure_status": "closed",
            "allow_stop": True,
            "allow_stop_from_verifier": True,
            "retrieval_coverage": 0.70,
            "report_citation_coverage": 0.80,
            "target_metric": 0.70,  # 跟 baseline 一致 → 效果消失 = candidate 真有贡献
            "candidate_floor_pass": True,
            "tool_calls": 10.0,
            "leakage_hits": [],
            "forbidden_source_hits": [],
            "literal_dependency_hit": False,
            "verdict_like_output": False,
            "w2_reconstruction_probe": 0.5,
            "report_unsupported_claim_rate": 0.05,
        }
    return _runner


def _gate4_holdout_runner_w2_reconstruction(pkg):
    base = _gate4_holdout_runner_clean(pkg)
    def _runner(case, active_skills):
        out = dict(base(case, active_skills))
        if _has_candidate(active_skills, pkg):
            out["w2_reconstruction_probe"] = 12.0  # >5pp threshold
        return out
    return _runner


def _gate4_holdout_runner_literal_dep(pkg):
    base = _gate4_holdout_runner_clean(pkg)
    def _runner(case, active_skills):
        out = dict(base(case, active_skills))
        if _has_candidate(active_skills, pkg):
            out["literal_dependency_hit"] = True
        return out
    return _runner


def test_gate4_passes_with_clean_holdout_and_counterfactual():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate4_holdout_counterfactual(
        pkg,
        traces,
        holdout_runner=_gate4_holdout_runner_clean(pkg),
        counterfactual_runner=_gate4_counterfactual_runner_clean(pkg),
    )
    assert rec.passed, rec.failure_reasons


def test_gate4_fails_on_w2_reconstruction_gt_5pp():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate4_holdout_counterfactual(
        pkg,
        traces,
        holdout_runner=_gate4_holdout_runner_w2_reconstruction(pkg),
        counterfactual_runner=_gate4_counterfactual_runner_clean(pkg),
    )
    assert not rec.passed
    assert any("w2_reconstruction_gt" in r for r in rec.failure_reasons)


def test_gate4_fails_on_literal_dependency():
    pkg = _make_valid_pkg()
    traces = [_make_trace(i) for i in range(10)]
    rec = run_gate4_holdout_counterfactual(
        pkg,
        traces,
        holdout_runner=_gate4_holdout_runner_literal_dep(pkg),
        counterfactual_runner=_gate4_counterfactual_runner_clean(pkg),
    )
    assert not rec.passed
    assert any("holdout_building_run_literal_dep" in r for r in rec.failure_reasons)


# ---------------- 主 dispatcher ---------------------------------------------


def test_validate_skill_all_5_gates_pass():
    pkg = _make_valid_pkg(source_trace_count=5)
    traces = [_make_trace(i) for i in range(10)]
    holdout = [_make_trace(100 + i) for i in range(5)]
    ok, records = validate_skill(
        pkg,
        eval_set=traces,
        replay_set=traces,
        holdout_set=holdout,
        promote_target="active",
        replay_runner=_gate2_runner_clean_improvement(pkg),
        seed_variation_runner=_gate3_runner_deterministic(),
        holdout_runner=_gate4_holdout_runner_clean(pkg),
        counterfactual_runner=_gate4_counterfactual_runner_clean(pkg),
        K=5,
    )
    assert ok, [r.failure_reasons for r in records]
    assert len(records) == 5
    stages = [r.validation_stage for r in records]
    assert stages == [
        "gate0_static",
        "gate1_schema_provenance",
        "gate2_replay_ab",
        "gate3_stability",
        "gate4_holdout_counterfactual",
    ]


def test_validate_skill_short_circuits_on_gate0_fail():
    pkg = _make_valid_pkg()
    # 故意把 forbidden_actions 删一半
    bad_skill = pkg.skill.model_copy(update={"forbidden_actions": []})
    bad_pkg = pkg.model_copy(update={"skill": bad_skill})
    traces = [_make_trace(i) for i in range(10)]
    ok, records = validate_skill(
        bad_pkg, eval_set=traces, replay_set=traces, holdout_set=traces
    )
    assert not ok
    # 只跑了 Gate 0
    assert len(records) == 1
    assert records[0].validation_stage == "gate0_static"


def test_validate_skill_short_circuits_on_gate1_fail():
    pkg = _make_valid_pkg(source_trace_count=2)  # active 要求 ≥5（v1.1 §9.5）
    traces = [_make_trace(i) for i in range(10)]
    ok, records = validate_skill(
        pkg, eval_set=traces, replay_set=traces, holdout_set=traces, promote_target="active"
    )
    assert not ok
    assert len(records) == 2
    assert records[-1].validation_stage == "gate1_schema_provenance"


def test_validate_skill_short_circuits_on_gate2_fail():
    """Gate 2 fail（closure regression）→ Gate 3/4 不跑。"""
    pkg = _make_valid_pkg(source_trace_count=5)
    traces = [_make_trace(i) for i in range(10)]
    holdout = [_make_trace(100 + i) for i in range(5)]
    ok, records = validate_skill(
        pkg,
        eval_set=traces,
        replay_set=traces,
        holdout_set=holdout,
        promote_target="active",
        replay_runner=_gate2_runner_with_regression(pkg),
        seed_variation_runner=_gate3_runner_deterministic(),
        holdout_runner=_gate4_holdout_runner_clean(pkg),
        counterfactual_runner=_gate4_counterfactual_runner_clean(pkg),
    )
    assert not ok
    assert len(records) == 3
    assert records[-1].validation_stage == "gate2_replay_ab"


def test_validator_version_constant():
    assert VALIDATOR_VERSION == "skill_gate_v1.0"
