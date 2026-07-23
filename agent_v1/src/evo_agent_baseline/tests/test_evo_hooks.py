"""evo-agent v1 §7.4 六个 evo hook 单元测试。

覆盖（每 hook 至少 forbidden 字段拦截 + 正确放行 + 边界 case）：

1. `pre_skill_candidate_guard`（spec v1 §7.4.1 + §9.4.1 Gate 0）
2. `post_skill_validation_audit`（spec v1 §7.4.2 + §9.4.6）
3. `pre_skill_runtime_load_guard`（spec v1 §7.4.3）
4. `pre_feedback_ingest_guard`（spec v1 §7.4.4 + §8.4 / §8.5）
5. `pre_policy_publish_guard`（spec v1 §7.4.5）
6. `post_evo_writeback_audit`（spec v1 §7.4.6）

每条 hook 抛 SecurityError / OutputGuardError 必须 hard fail；不允许降级 warning。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.agent.hooks import (
    OutputGuardError,
    SecurityError,
    post_evo_writeback_audit,
    post_skill_validation_audit,
    pre_feedback_ingest_guard,
    pre_policy_publish_guard,
    pre_skill_candidate_guard,
    pre_skill_runtime_load_guard,
)


# ===========================================================================
# 公共 fixture
# ===========================================================================
def _valid_skill_dict(**overrides):
    """构造合规 SkillJson dict 的最小集合（spec v1 §10.2 + Appendix B.3）。"""
    d = {
        "schema_version": "1.0.0",
        "skill_id": "skill.mbis.retrieval_macro.artifact_evidence_gap",
        "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
        "name": "artifact evidence gap retrieval macro",
        "kind": "retrieval_macro",
        "layer": "L1_operational",
        "description": "expand retrieval when artifact obligations are open",
        "status": "active",
        "origin": "evo_induced",
        "version": "1.0.0",
        "scope": {
            "rule_families": ["mbis.reporting.inspection_report.ri.schema"],
            "rule_cards": [],
            "semantic_slots": [],
            "measure_keys": [],
            "artifact_keys": ["mbis.reporting.inspection_report.ri"],
            "obligation_kinds": ["artifact", "report_field"],
        },
        "trigger_predicate": {
            "all": [
                {"field": "open_reason_code", "op": "in", "value": ["missing_artifact_evidence"]}
            ]
        },
        "allowed_tools": ["retrieve_building_facts"],
        "forbidden_actions": [
            "override_verifier",
            "force_allow_stop",
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ],
        "source_trace_hashes": ["sha256:a" * 6, "sha256:b" * 6, "sha256:c" * 6, "sha256:d" * 6, "sha256:e" * 6],
        "support_counts": {"buildings": 4, "world_families": 2},
        "kg_snapshot_id": "KGS-v1-20260523",
        "rulecard_bundle_id": "rulecard_v2.mbis_cop_2023",
        "created_by": "evo_trainer",
        "created_at": "2026-05-23T20:00:00Z",
        "non_authority_statement": "This Skill is non-authoritative and cannot decide compliance.",
    }
    d.update(overrides)
    return d


def _valid_candidate_pkg(**skill_overrides):
    return {
        "package_schema_version": "1.0.0",
        "package_uri": "skills/skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
        "package_sha256": "sha256:" + "a" * 64,
        "skill": _valid_skill_dict(**skill_overrides),
        "skill_md_text": (
            "# artifact evidence gap retrieval macro\n\n"
            "This Skill is non-authoritative and cannot decide compliance.\n"
        ),
    }


def _valid_policy_dict(**overrides):
    # v1.1 §0.6 修订 2 + §3.6.4：3 态简化（"candidate" → "draft"），
    # 删 previous_active_version_id / rollback_condition 字段
    d = {
        "policy_version_id": "policy.mbis.runtime.default.v1.0.0",
        "policy_id": "policy.mbis.runtime.default",
        "version": "1.0.0",
        "status": "draft",
        "ranking_weights": {
            "base_fulltext_score": 1.0,
            "skill_trigger_boost": 0.30,
        },
        "tool_preferences": {"deep_lookup_after_open": True},
        "skill_activation_order": {"resolver": "validation_score_then_specificity"},
        "open_obligation_priority": {"missing_artifact_evidence": 0.9},
        "candidate_cutoff_policy": {
            "context_top_k": 80,
            "verifier_floor": "all_score_positive_not_deterministically_excluded",
        },
        "report_template_policy": {"default": "mbis_auxiliary_report_v1"},
        "fallback_thresholds": {"max_added_tool_calls_per_skill": 3},
        "max_tool_iterations_default": 16,
        "experiment_budgets": [8, 16, 32],
        "trained_on_replay_set_id": "RS-evolve-train-20260523",
        "trained_on_artifacts": ["sanitized_packet:SFP-EW-20260523-001"],
        "trained_on_feedback_packet_ids": ["SFP-EW-20260523-001"],
        "validation_summary": {"leakage_audit_passed": True},
        "created_at": "2026-05-23T20:00:00Z",
        "activated_at": None,
    }
    d.update(overrides)
    return d


def _valid_packet_dict(**overrides):
    d = {
        "feedback_packet_id": "SFP-EW-20260523-001",
        "eval_window_id": "EW-20260523",
        "source_eval_truth_report_hash": "sha256:" + "a" * 64,
        "aggregation_level": "batch_rule_family",
        "run_count": 25,
        "building_count": 5,
        "cell_count": 2,
        "rounding_policy": "nearest_0.05",
        "release_delay_window_count": 1,
        "cells": [
            {
                "feedback_cell_id": "SFP-EW-20260523-001-cell-0",
                "feedback_packet_id": "SFP-EW-20260523-001",
                "dimension": {"rule_family": "mbis.reporting"},
                "metric_name": "open_count_delta",
                "metric_bucket": "+0.10",
                "delta_bucket": None,
                "run_count": 25,
                "building_count": 5,
                "suppressed": False,
                "suppression_reason": None,
                "suggested_evo_action": "policy_weight_adjustment",
            }
        ],
        "forbidden_scan_passed": True,
        "k_anonymity_passed": True,
        "reconstruction_audit_passed": True,
        "created_at": "2026-05-23T20:00:00Z",
        "released_at": "2026-05-24T20:00:00Z",
    }
    d.update(overrides)
    return d


# ===========================================================================
# Hook 1: pre_skill_candidate_guard
# ===========================================================================
class TestPreSkillCandidateGuard:
    def test_valid_skill_pass(self):
        out = pre_skill_candidate_guard(_valid_candidate_pkg())
        assert out["guard"] == "pre_skill_candidate_guard"
        assert out["passed"] is True

    def test_invalid_kind_rejected(self):
        pkg = _valid_candidate_pkg(kind="bogus_kind")
        with pytest.raises(SecurityError, match="kind="):
            pre_skill_candidate_guard(pkg)

    def test_layer_must_be_L1(self):
        pkg = _valid_candidate_pkg()
        pkg["skill"]["layer"] = "L2_meta_disabled"
        with pytest.raises(SecurityError, match="layer="):
            pre_skill_candidate_guard(pkg)

    def test_missing_forbidden_actions_rejected(self):
        pkg = _valid_candidate_pkg(forbidden_actions=["override_verifier"])
        with pytest.raises(SecurityError, match="forbidden_actions"):
            pre_skill_candidate_guard(pkg)

    def test_skill_id_with_building_literal_rejected(self):
        pkg = _valid_candidate_pkg(skill_id="skill.mbis.B-12345.x")
        with pytest.raises(SecurityError, match="literal"):
            pre_skill_candidate_guard(pkg)

    def test_skill_id_with_verdict_word_rejected(self):
        pkg = _valid_candidate_pkg(skill_id="skill.mbis.report.verdict_predictor")
        with pytest.raises(SecurityError, match="verdict"):
            pre_skill_candidate_guard(pkg)

    def test_w2_label_in_package_rejected(self):
        pkg = _valid_candidate_pkg()
        # 在 description 里偷塞一个 W2 label
        pkg["skill"]["description"] = "uses NormativeProjection to rank"
        with pytest.raises(SecurityError, match="(W2|NormativeProjection)"):
            pre_skill_candidate_guard(pkg)

    def test_forbidden_property_in_package_rejected(self):
        pkg = _valid_candidate_pkg()
        pkg["skill"]["trigger_predicate"] = {
            "all": [{"field": "expected_verdict", "op": "eq", "value": "pass"}]
        }
        with pytest.raises(SecurityError, match="expected_verdict"):
            pre_skill_candidate_guard(pkg)

    def test_skill_md_missing_non_authority_rejected(self):
        pkg = _valid_candidate_pkg()
        pkg["skill_md_text"] = "# bare md without disclosure\n"
        # 同时把 skill.non_authority_statement 弱化，确保没有 non-auth marker 命中
        pkg["skill"]["non_authority_statement"] = "do something"
        with pytest.raises(SecurityError, match="non-authority"):
            pre_skill_candidate_guard(pkg)

    def test_verdict_phrase_unnegated_rejected(self):
        pkg = _valid_candidate_pkg()
        pkg["skill_md_text"] = (
            "# bad skill\n\nThis Skill should override verifier when needed.\n"
        )
        with pytest.raises(SecurityError):
            pre_skill_candidate_guard(pkg)

    def test_verdict_phrase_negated_allowed(self):
        # "does not override verifier" 是 SKILL.md 标准免责声明，应放行
        pkg = _valid_candidate_pkg()
        pkg["skill_md_text"] = (
            "# safe skill\n\nThis Skill is non-authoritative and does not "
            "override verifier authority.\n"
        )
        out = pre_skill_candidate_guard(pkg)
        assert out["passed"] is True


# ===========================================================================
# Hook 2: post_skill_validation_audit
# ===========================================================================
class TestPostSkillValidationAudit:
    def _valid_record(self, **overrides):
        d = {
            "validation_id": "SVR-x-gate2-20260523",
            "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
            "validation_stage": "gate2_replay_ab",
            "eval_set_id": "RS-gate-validation-20260523",
            "eval_set_hash": "sha256:" + "a" * 64,
            "run_count": 40,
            "building_count": 12,
            "world_family_count": 4,
            "metric_name": "target_artifact_evidence_coverage_delta",
            "metric_value_bucket": "+0.05",
            "metric_delta_bucket": "+0.05",
            "confidence_bucket": "medium",
            "passed": True,
            "failure_reasons": [],
            "leakage_hits": [],
            "closure_regression_count": 0,
            "allow_stop_authority_check": True,
            "validator_version": "skill_gate_v1.0",
            "created_at": "2026-05-23T20:00:00Z",
        }
        d.update(overrides)
        return d

    def test_valid_record_pass(self):
        out = post_skill_validation_audit(self._valid_record())
        assert out["passed"] is True

    def test_invalid_stage_rejected(self):
        rec = self._valid_record(validation_stage="bogus_stage")
        with pytest.raises(OutputGuardError, match="validation_stage"):
            post_skill_validation_audit(rec)

    def test_leakage_hits_rejected(self):
        rec = self._valid_record(leakage_hits=["building_id_leaked"])
        with pytest.raises(OutputGuardError, match="leakage"):
            post_skill_validation_audit(rec)

    def test_closure_regression_rejected(self):
        rec = self._valid_record(closure_regression_count=2)
        with pytest.raises(OutputGuardError, match="closure_regression_count"):
            post_skill_validation_audit(rec)

    def test_allow_stop_authority_check_false_rejected(self):
        rec = self._valid_record(allow_stop_authority_check=False)
        with pytest.raises(OutputGuardError, match="allow_stop_authority"):
            post_skill_validation_audit(rec)

    def test_metric_delta_bucket_off_grid_rejected(self):
        rec = self._valid_record(metric_delta_bucket="+0.037")  # 非 0.05 整数倍
        with pytest.raises(OutputGuardError, match="0.05"):
            post_skill_validation_audit(rec)

    def test_metric_value_bucket_low_medium_high_allowed(self):
        out = post_skill_validation_audit(self._valid_record(metric_value_bucket="medium"))
        assert out["passed"] is True

    def test_w2_label_in_record_rejected(self):
        rec = self._valid_record(metric_name="NormativeProjection_eval")
        with pytest.raises(OutputGuardError, match="W2"):
            post_skill_validation_audit(rec)

    def test_free_text_evaluator_comment_rejected(self):
        rec = self._valid_record()
        rec["evaluator_comment"] = "this skill is great"
        with pytest.raises(OutputGuardError, match="禁字段"):
            post_skill_validation_audit(rec)


# ===========================================================================
# Hook 3: pre_skill_runtime_load_guard
# ===========================================================================
class TestPreSkillRuntimeLoadGuard:
    def test_active_skill_pass(self):
        skill_pkg = {
            "skill": _valid_skill_dict(),
            "staleness_status": "fresh",
        }
        out = pre_skill_runtime_load_guard(
            skill_pkg,
            current_kg_snapshot_id="KGS-v1-20260523",
            current_rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
        )
        assert out["passed"] is True

    def test_draft_status_rejected(self):
        skill_pkg = {"skill": _valid_skill_dict(status="draft")}
        with pytest.raises(SecurityError, match="status="):
            pre_skill_runtime_load_guard(
                skill_pkg, "KGS-v1-20260523", "rulecard_v2.mbis_cop_2023"
            )

    def test_layer_l2_rejected(self):
        sk = _valid_skill_dict()
        sk["layer"] = "L2_meta_disabled"
        skill_pkg = {"skill": sk}
        with pytest.raises(SecurityError, match="Layer 2"):
            pre_skill_runtime_load_guard(
                skill_pkg, "KGS-v1-20260523", "rulecard_v2.mbis_cop_2023"
            )

    def test_stale_status_rejected(self):
        skill_pkg = {
            "skill": _valid_skill_dict(),
            "staleness_status": "stale_rule_bundle",
        }
        with pytest.raises(SecurityError, match="staleness"):
            pre_skill_runtime_load_guard(
                skill_pkg, "KGS-v1-20260523", "rulecard_v2.mbis_cop_2023"
            )

    def test_kg_snapshot_mismatch_rejected(self):
        skill_pkg = {"skill": _valid_skill_dict(), "staleness_status": "fresh"}
        with pytest.raises(SecurityError, match="kg_snapshot"):
            pre_skill_runtime_load_guard(
                skill_pkg,
                current_kg_snapshot_id="KGS-v2-20260601",  # 不同
                current_rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
            )

    def test_bundle_mismatch_rejected(self):
        skill_pkg = {"skill": _valid_skill_dict(), "staleness_status": "fresh"}
        with pytest.raises(SecurityError, match="rulecard_bundle"):
            pre_skill_runtime_load_guard(
                skill_pkg,
                current_kg_snapshot_id="KGS-v1-20260523",
                current_rulecard_bundle_id="rulecard_v2.mbis_cop_2024",  # 不同
            )

    def test_missing_forbidden_actions_rejected(self):
        skill_pkg = {
            "skill": _valid_skill_dict(forbidden_actions=["override_verifier"]),
            "staleness_status": "fresh",
        }
        with pytest.raises(SecurityError, match="forbidden_actions"):
            pre_skill_runtime_load_guard(
                skill_pkg, "KGS-v1-20260523", "rulecard_v2.mbis_cop_2023"
            )


# ===========================================================================
# Hook 4: pre_feedback_ingest_guard
# ===========================================================================
class TestPreFeedbackIngestGuard:
    def test_valid_packet_pass(self):
        out = pre_feedback_ingest_guard(_valid_packet_dict())
        assert out["passed"] is True

    def test_low_run_count_rejected(self):
        pkt = _valid_packet_dict(run_count=8)
        with pytest.raises(SecurityError, match="run_count"):
            pre_feedback_ingest_guard(pkt)

    def test_low_building_count_rejected(self):
        pkt = _valid_packet_dict(building_count=2)
        with pytest.raises(SecurityError, match="building_count"):
            pre_feedback_ingest_guard(pkt)

    def test_bad_rounding_rejected(self):
        pkt = _valid_packet_dict(rounding_policy="raw_value")
        with pytest.raises(SecurityError, match="rounding_policy"):
            pre_feedback_ingest_guard(pkt)

    def test_v1_1_release_delay_no_longer_enforced(self):
        """v1.1 §0.6 修订 2 + §3.6.5 + §8.6：``release_delay_window_count`` 不再
        硬约束（broker 角色降级为 runtime trend feedback 接口；实验室阶段无延迟
        发布需求）。

        ``release_delay_window_count=0`` 不再触发 SecurityError；
        ``release_delay_window_count=None`` 也允许通过。
        """
        # 0 delay：应通过
        pkt = _valid_packet_dict(release_delay_window_count=0)
        out = pre_feedback_ingest_guard(pkt)
        assert out["passed"] is True
        # None delay：应通过（v1.1 §3.6.5 字段改 Optional）
        pkt2 = _valid_packet_dict(release_delay_window_count=None)
        out2 = pre_feedback_ingest_guard(pkt2)
        assert out2["passed"] is True

    def test_unsuppressed_cell_below_k_rejected(self):
        pkt = _valid_packet_dict()
        pkt["cells"][0]["run_count"] = 5
        with pytest.raises(SecurityError, match="run_count"):
            pre_feedback_ingest_guard(pkt)

    def test_suppressed_cell_allowed_below_k(self):
        pkt = _valid_packet_dict()
        pkt["cells"][0]["suppressed"] = True
        pkt["cells"][0]["run_count"] = 1
        pkt["cells"][0]["building_count"] = 1
        out = pre_feedback_ingest_guard(pkt)
        assert out["passed"] is True

    def test_building_id_literal_rejected(self):
        pkt = _valid_packet_dict()
        pkt["cells"][0]["dimension"] = {"first_seen_building": "B-12345"}
        with pytest.raises(SecurityError, match="(literal|building)"):
            pre_feedback_ingest_guard(pkt)

    def test_evaluator_comment_rejected(self):
        pkt = _valid_packet_dict()
        pkt["cells"][0]["dimension"] = {"feedback_truth_comment": "wrong"}
        with pytest.raises(SecurityError, match="feedback_truth_comment"):
            pre_feedback_ingest_guard(pkt)

    def test_scan_passes_required(self):
        pkt = _valid_packet_dict(forbidden_scan_passed=False)
        with pytest.raises(SecurityError, match="forbidden_scan"):
            pre_feedback_ingest_guard(pkt)


# ===========================================================================
# Hook 5: pre_policy_publish_guard
# ===========================================================================
class TestPrePolicyPublishGuard:
    def test_valid_policy_pass(self):
        out = pre_policy_publish_guard(_valid_policy_dict())
        assert out["passed"] is True

    def test_missing_verifier_floor_rejected(self):
        policy = _valid_policy_dict()
        policy["candidate_cutoff_policy"] = {"context_top_k": 80}
        with pytest.raises(SecurityError, match="verifier_floor"):
            pre_policy_publish_guard(policy)

    def test_wrong_verifier_floor_literal_rejected(self):
        policy = _valid_policy_dict()
        policy["candidate_cutoff_policy"] = {
            "context_top_k": 80,
            "verifier_floor": "top_k_only",  # 错误字面量
        }
        with pytest.raises(SecurityError, match="verifier_floor"):
            pre_policy_publish_guard(policy)

    def test_allow_stop_policy_rejected(self):
        policy = _valid_policy_dict()
        policy["allow_stop_policy"] = {"always_true": True}
        with pytest.raises(SecurityError, match="(allow_stop|authority)"):
            pre_policy_publish_guard(policy)

    def test_verifier_override_nested_rejected(self):
        policy = _valid_policy_dict()
        policy["tool_preferences"]["verifier_override"] = True
        with pytest.raises(SecurityError, match="(verifier|authority)"):
            pre_policy_publish_guard(policy)

    def test_ranking_weight_out_of_bounds_rejected(self):
        policy = _valid_policy_dict()
        policy["ranking_weights"]["skill_trigger_boost"] = 3.0
        with pytest.raises(SecurityError, match="超出"):
            pre_policy_publish_guard(policy)

    def test_v1_1_no_rollback_check(self):
        """v1.1 §0.6 修订 2 + §3.6.4 + §9.9：``rollback_condition`` 字段已删除
        （实验室阶段无 canary / rollback artifact，git revert 代替）。

        本测试验证 pre_policy_publish_guard 不再检查 ``rollback_condition``。
        policy 不含 ``rollback_condition`` 字段时，guard 不应抛 SecurityError；
        即使 caller 显式传 ``rollback_condition={}``（extra field），policy DTO
        会被 pydantic ``extra='forbid'`` 在 model 层拒绝，guard 本身不处理。
        """
        # _valid_policy_dict 现在不含 rollback_condition；guard 应通过该检查
        policy = _valid_policy_dict()
        result = pre_policy_publish_guard(policy)
        assert result["passed"] is True

    def test_w2_field_in_policy_rejected(self):
        policy = _valid_policy_dict()
        policy["open_obligation_priority"]["expected_verdict"] = 0.9
        with pytest.raises(SecurityError, match="(W2|expected_verdict)"):
            pre_policy_publish_guard(policy)


# ===========================================================================
# Hook 6: post_evo_writeback_audit
# ===========================================================================
class TestPostEvoWritebackAudit:
    def test_valid_node_pass(self):
        node = {
            "label": "SkillVersion",
            "properties": {
                "skill_version_id": "skill.x.v1",
                "status": "active",
            },
        }
        out = post_evo_writeback_audit(node)
        assert out["passed"] is True

    def test_invalid_label_rejected(self):
        node = {"label": "EvalTruthReport", "properties": {}}
        with pytest.raises(SecurityError, match="label"):
            post_evo_writeback_audit(node)

    def test_evaluator_truth_property_rejected(self):
        node = {
            "label": "SkillValidationRecord",
            "properties": {"truth_label": "pass"},
        }
        with pytest.raises(SecurityError, match="evaluator-only"):
            post_evo_writeback_audit(node)

    def test_w2_property_rejected(self):
        node = {
            "label": "EvoRunTrace",
            "properties": {"expected_verdict": "fail"},
        }
        with pytest.raises(SecurityError, match="(evaluator-only|expected_verdict)"):
            post_evo_writeback_audit(node)

    def test_target_label_pointing_to_truth_rejected(self):
        edge = {
            "label": "TRIGGERED",
            "target_label": "W2Truth",
        }
        with pytest.raises(SecurityError, match="evaluator truth"):
            post_evo_writeback_audit(edge)

    def test_nested_w2_string_in_properties_rejected(self):
        node = {
            "label": "EvoPolicyVersion",
            "properties": {"notes": "uses NormativeProjection signal"},
        }
        with pytest.raises(SecurityError, match="(W2|NormativeProjection)"):
            post_evo_writeback_audit(node)

    def test_relationship_edge_label_pass(self):
        edge = {
            "label": "TRIGGERED",
            "target_label": "SkillActivation",
            "properties": {"created_at": "2026-05-23T20:00:00Z"},
        }
        out = post_evo_writeback_audit(edge)
        assert out["passed"] is True
