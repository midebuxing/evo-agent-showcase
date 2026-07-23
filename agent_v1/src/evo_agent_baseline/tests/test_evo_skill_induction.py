"""Skill Induction 单元测试（spec v1 §9.3）。"""

from __future__ import annotations

import pytest

from evo_agent_baseline.contracts import (
    EvoRunStep,
    EvoRunTrace,
    FeedbackCell,
    SanitizedFeedbackPacket,
)
from evo_agent_baseline.evo.replay_buffer import ReplayBuffer
from evo_agent_baseline.evo.skill_induction import (
    DRAFT_PROMPT_NON_AUTHORITY,
    HARD_FORBIDDEN_ACTIONS,
    InductionCandidate,
    detect_feedback_gap_trigger,
    detect_repeated_failure_trigger,
    detect_repeated_success_trigger,
    generate_draft_skill_package,
)


# ---------------- helpers ----------------------------------------------------


def _build_trace(
    idx: int,
    *,
    rule_family: str = "mbis.reporting.x",
    obligation_kind: str = "report_field",
    slot_class: str = "artifact_evidence",
    open_reason: str = "missing_artifact_evidence",
    building_id_hash: str = None,
    world_id_hash: str = None,
    tool_count: int = 10,
    steps: list = None,
    active_skill_set_id: str = "SS-default",
    closed_count: int = 5,
    open_count: int = 1,
    blocked_count: int = 0,
) -> EvoRunTrace:
    cs = {
        "closed_count": closed_count,
        "open_count": open_count,
        "blocked_count": blocked_count,
        "total_obligations": closed_count + open_count + blocked_count,
        "open_reason_counts": {open_reason: open_count} if open_count > 0 else {},
        "blocked_reason_counts": {},
        "rule_families": [rule_family],
        "obligation_kinds": [obligation_kind],
        "semantic_slot_classes": [slot_class],
    }
    return EvoRunTrace(
        trace_id=f"ERT-test-{idx:03d}",
        run_id=f"CAR-{idx:03d}",
        world_id_hash=world_id_hash or f"sha256:world_{idx % 3:03d}",
        building_id_hash=building_id_hash or f"sha256:bld_{idx % 5:03d}",
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
        agent_version="v1.0.0",
        verifier_version="v1.0.0",
        evo_policy_version_id="policy.mbis.runtime.default.v1.0.0",
        active_skill_set_id=active_skill_set_id,
        active_skill_version_ids=[],
        input_guard_hash="sha256:guard",
        retrieval_summary={
            "rule_families": [rule_family],
            "semantic_slot_classes": [slot_class],
        },
        candidate_universe_hash="sha256:universe",
        fact_pack_hash="sha256:facts",
        rule_slice_hash="sha256:rules",
        closure_result_ref="closure_ref",
        closure_summary=cs,
        report_ref=None,
        hook_results_hash="sha256:hooks",
        tool_call_count=tool_count,
        llm_iterations_used=3,
        cost={"tokens": 100},
        fallback_reason=None,
        steps=steps or [],
        sanitized_feedback_refs=[],
        trace_visibility="agent_visible_trace",
        forbidden_scan_passed=True,
        source_visibility_audit_passed=True,
        schema_audit_passed=True,
        candidate_floor_passed=True,
        created_at=f"2026-05-{idx % 28 + 1:02d}T00:00:00Z",
    )


# ---------------- 触发 A：重复失败 -------------------------------------------


def test_repeated_failure_trigger_fires_at_5plus_traces_3plus_buildings():
    buf = ReplayBuffer()
    for i in range(5):
        buf.add_trace(_build_trace(i, building_id_hash=f"sha256:bld_{i:03d}"))
    cands = detect_repeated_failure_trigger(buf)
    assert len(cands) >= 1
    c = cands[0]
    assert c.trigger_type == "repeated_failure"
    assert c.support_counts["trace_count"] == 5
    assert c.support_counts["building_count"] == 5


def test_repeated_failure_trigger_skips_below_min_count():
    buf = ReplayBuffer()
    for i in range(3):
        buf.add_trace(_build_trace(i, building_id_hash=f"sha256:bld_{i:03d}"))
    cands = detect_repeated_failure_trigger(buf)
    assert cands == []


def test_repeated_failure_trigger_requires_building_or_world_family_diversity():
    """同一 building 5 次但 world_family 也只 1 个 → 不触发。"""
    buf = ReplayBuffer()
    for i in range(5):
        buf.add_trace(
            _build_trace(
                i,
                building_id_hash="sha256:bld_same",
                world_id_hash="sha256:world_same",
            )
        )
    cands = detect_repeated_failure_trigger(buf)
    assert cands == []


# ---------------- 触发 B：重复成功 -------------------------------------------


def test_repeated_success_trigger_fires_on_tool_calls_drop():
    buf = ReplayBuffer()
    # baseline: 10 个 trace tool_count=20
    for i in range(10):
        buf.add_trace(_build_trace(i, tool_count=20, active_skill_set_id="SS-baseline"))
    # cluster: 5 trace 用 SS-fast 且 tool_count=10 (median drop -50%)
    fast_steps = [
        EvoRunStep(
            step_id="ERS-fast-0",
            trace_id="ERT-fast",
            seq=0,
            stage="fact_retrieval",
            tool_name="retrieve_building_facts",
            created_at="2026-05-24T00:00:00Z",
        )
    ]
    for i in range(10, 15):
        buf.add_trace(
            _build_trace(
                i, tool_count=10, active_skill_set_id="SS-fast", steps=fast_steps
            )
        )
    cands = detect_repeated_success_trigger(buf)
    success = [c for c in cands if c.trigger_type == "repeated_success"]
    assert success, "应触发重复成功 candidate"
    assert "SS-fast" in success[0].pattern_dimension["active_skill_set_id"]


def test_repeated_success_trigger_no_fire_when_no_improvement():
    buf = ReplayBuffer()
    same_steps = [
        EvoRunStep(
            step_id="ERS-0",
            trace_id="ERT-x",
            seq=0,
            stage="fact_retrieval",
            tool_name="t1",
            created_at="2026-05-24T00:00:00Z",
        )
    ]
    for i in range(10):
        buf.add_trace(_build_trace(i, tool_count=10, steps=same_steps))
    cands = detect_repeated_success_trigger(buf)
    success = [c for c in cands if c.trigger_type == "repeated_success"]
    assert success == []


# ---------------- 触发 C：feedback gap ---------------------------------------


def test_feedback_gap_trigger_fires_on_cell_with_action():
    packet = SanitizedFeedbackPacket(
        feedback_packet_id="SFP-001",
        eval_window_id="EW-001",
        source_eval_truth_report_hash="sha256:x",
        aggregation_level="batch_slot_class",
        run_count=12,
        building_count=4,
        cell_count=1,
        rounding_policy="nearest_0.05",
        release_delay_window_count=1,
        cells=[
            FeedbackCell(
                feedback_cell_id="cell-1",
                feedback_packet_id="SFP-001",
                dimension={
                    "semantic_slot_class": "artifact_evidence",
                    "obligation_kind": "report_field",
                },
                metric_name="slot_recall_delta",
                metric_bucket="low",
                delta_bucket="-0.10",
                run_count=12,
                building_count=4,
                suppressed=False,
                suggested_evo_action="skill_induction_candidate",
            )
        ],
        forbidden_scan_passed=True,
        k_anonymity_passed=True,
        reconstruction_audit_passed=True,
        created_at="2026-05-24T00:00:00Z",
        released_at="2026-05-24T00:00:00Z",
    )
    cands = detect_feedback_gap_trigger([packet])
    assert len(cands) == 1
    assert cands[0].trigger_type == "feedback_gap"


def test_feedback_gap_trigger_skips_suppressed_or_no_action():
    packet = SanitizedFeedbackPacket(
        feedback_packet_id="SFP-002",
        eval_window_id="EW-002",
        source_eval_truth_report_hash="sha256:y",
        aggregation_level="batch_slot_class",
        run_count=12,
        building_count=4,
        cell_count=2,
        rounding_policy="nearest_0.05",
        release_delay_window_count=1,
        cells=[
            FeedbackCell(
                feedback_cell_id="cell-1",
                feedback_packet_id="SFP-002",
                dimension={"semantic_slot_class": "x"},
                metric_name="m",
                metric_bucket="suppressed",
                run_count=5,
                building_count=2,
                suppressed=True,
                suggested_evo_action="skill_induction_candidate",
            ),
            FeedbackCell(
                feedback_cell_id="cell-2",
                feedback_packet_id="SFP-002",
                dimension={"semantic_slot_class": "y"},
                metric_name="m",
                metric_bucket="0.10",
                run_count=12,
                building_count=4,
                suppressed=False,
                suggested_evo_action="none",
            ),
        ],
        forbidden_scan_passed=True,
        k_anonymity_passed=True,
        reconstruction_audit_passed=True,
        created_at="2026-05-24T00:00:00Z",
        released_at="2026-05-24T00:00:00Z",
    )
    cands = detect_feedback_gap_trigger([packet])
    assert cands == []


# ---------------- draft 生成 ------------------------------------------------


def test_generate_draft_skill_package_has_hard_forbidden_actions():
    cand = InductionCandidate(
        trigger_type="repeated_failure",
        pattern_key=("mbis.reporting.x", "artifact_evidence", "report_field", "missing_fact"),
        pattern_dimension={
            "rule_family": "mbis.reporting.x",
            "semantic_slot_class": "artifact_evidence",
            "obligation_kind": "report_field",
            "reason_code": "missing_fact",
        },
        source_trace_ids=[f"ERT-{i}" for i in range(5)],
        support_counts={"trace_count": 5, "building_count": 3, "world_family_count": 2},
    )
    pkg = generate_draft_skill_package(cand)
    assert pkg.skill.status == "draft"
    assert pkg.skill.origin == "evo_induced"
    for action in HARD_FORBIDDEN_ACTIONS:
        assert action in pkg.skill.forbidden_actions
    assert len(pkg.skill.source_trace_hashes) == 5
    assert pkg.skill.non_authority_statement


def test_generate_draft_skill_package_description_contains_non_authority_phrase():
    cand = InductionCandidate(
        trigger_type="feedback_gap",
        pattern_key=("cell-001",),
        pattern_dimension={"semantic_slot_class": "x"},
        source_trace_ids=[],
        support_counts={"run_count": 12, "building_count": 4},
        suggested_kind="retrieval_macro",
    )
    pkg = generate_draft_skill_package(cand)
    assert "Do not decide compliance" in pkg.skill.description


def test_generate_draft_skill_package_plan_yaml_for_retrieval_macro():
    cand = InductionCandidate(
        trigger_type="repeated_failure",
        pattern_key=("a", "b", "c", "d"),
        pattern_dimension={
            "rule_family": "a",
            "reason_code": "d",
        },
        source_trace_ids=["ERT-x"],
        support_counts={},
        suggested_kind="retrieval_macro",
    )
    pkg = generate_draft_skill_package(cand)
    assert pkg.plan_yaml_sha256 is not None


def test_generate_draft_skill_package_no_plan_yaml_for_diagnostic_hint():
    cand = InductionCandidate(
        trigger_type="repeated_failure",
        pattern_key=("a", "b", "c", "d"),
        pattern_dimension={
            "rule_family": "a",
            "reason_code": "d",
        },
        source_trace_ids=["ERT-x"],
        support_counts={},
        suggested_kind="diagnostic_hint",
    )
    pkg = generate_draft_skill_package(cand)
    assert pkg.plan_yaml_sha256 is None


def test_generate_draft_package_sha256_format():
    cand = InductionCandidate(
        trigger_type="repeated_success",
        pattern_key=("SS", "t1"),
        pattern_dimension={"active_skill_set_id": "SS"},
        source_trace_ids=[],
        support_counts={},
        suggested_kind="micro_routing",
    )
    pkg = generate_draft_skill_package(cand)
    assert pkg.package_sha256.startswith("sha256:")
    assert len(pkg.package_sha256) == 7 + 64
