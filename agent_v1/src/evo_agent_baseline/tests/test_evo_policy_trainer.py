"""EvoPolicy Trainer 单元测试（spec v1 §9.7）。"""

from __future__ import annotations

from typing import List

import pytest

from evo_agent_baseline.contracts import (
    EvoPolicyVersion,
    EvoRunStep,
    EvoRunTrace,
    FeedbackCell,
    SanitizedFeedbackPacket,
)
from evo_agent_baseline.evo.policy_trainer import (
    TOOL_CALLS_INCREASE_THRESHOLD,
    WEIGHT_MAX,
    WEIGHT_MAX_DELTA_PER_VERSION,
    WEIGHT_MIN,
    WEIGHT_STEP,
    EvoPolicyTrainer,
)


# ---------------- fixtures ---------------------------------------------------


def _make_policy(
    *,
    policy_version_id: str = "policy.mbis.runtime.default.v1.0.0",
    version: str = "1.0.0",
    weights: dict = None,
    fallback_thresholds: dict = None,
    candidate_cutoff: dict = None,
) -> EvoPolicyVersion:
    # v1.1 §0.6 修订 2 + §3.6.4：3 态简化，删除 previous_active_version_id /
    # rollback_condition 字段
    return EvoPolicyVersion(
        policy_version_id=policy_version_id,
        policy_id="policy.mbis.runtime.default",
        version=version,
        status="active",
        ranking_weights=weights or {"slot_class::artifact_evidence": 0.1},
        tool_preferences={},
        skill_activation_order={},
        open_obligation_priority={},
        candidate_cutoff_policy=candidate_cutoff or {"max_candidates": 50},
        report_template_policy={},
        fallback_thresholds=fallback_thresholds or {"deep_lookup_max_per_run": 5},
        max_tool_iterations_default=16,
        experiment_budgets=[8, 16, 32],
        trained_on_replay_set_id="RS-old",
        trained_on_artifacts=[],
        trained_on_feedback_packet_ids=[],
        validation_summary={},
        created_at="2026-05-01T00:00:00Z",
        activated_at="2026-05-01T00:00:00Z",
    )


def _make_trace(
    idx: int,
    *,
    open_reason: str = "missing_artifact_evidence",
    open_count: int = 1,
    closed_count: int = 5,
    blocked_count: int = 0,
    tool_count: int = 10,
    skill_ids: list = None,
) -> EvoRunTrace:
    steps = [
        EvoRunStep(
            step_id=f"ERS-{idx}-{i}",
            trace_id=f"ERT-{idx}",
            seq=i,
            stage="skill_activation",
            tool_name=None,
            selected_skill_ids=sid_list,
            created_at="2026-05-24T00:00:00Z",
        )
        for i, sid_list in enumerate([skill_ids or []])
    ]
    return EvoRunTrace(
        trace_id=f"ERT-{idx}",
        run_id=f"CAR-{idx}",
        world_id_hash=f"sha256:world_{idx % 3}",
        building_id_hash=f"sha256:bld_{idx % 4}",
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
        closure_summary={
            "closed_count": closed_count,
            "open_count": open_count,
            "blocked_count": blocked_count,
            "total_obligations": closed_count + open_count + blocked_count,
            "open_reason_counts": {open_reason: open_count} if open_count > 0 else {},
            "blocked_reason_counts": {},
        },
        report_ref=None,
        hook_results_hash="sha256:hooks",
        tool_call_count=tool_count,
        llm_iterations_used=3,
        cost={},
        fallback_reason=None,
        steps=steps,
        sanitized_feedback_refs=[],
        trace_visibility="agent_visible_trace",
        forbidden_scan_passed=True,
        source_visibility_audit_passed=True,
        schema_audit_passed=True,
        candidate_floor_passed=True,
        created_at="2026-05-24T00:00:00Z",
    )


def _make_feedback_packet(
    *,
    cells: List[FeedbackCell] = None,
) -> SanitizedFeedbackPacket:
    return SanitizedFeedbackPacket(
        feedback_packet_id="SFP-001",
        eval_window_id="EW-001",
        source_eval_truth_report_hash="sha256:x",
        aggregation_level="batch_slot_class",
        run_count=15,
        building_count=4,
        cell_count=len(cells or []),
        rounding_policy="nearest_0.05",
        release_delay_window_count=1,
        cells=cells or [],
        forbidden_scan_passed=True,
        k_anonymity_passed=True,
        reconstruction_audit_passed=True,
        created_at="2026-05-24T00:00:00Z",
        released_at="2026-05-24T00:00:00Z",
    )


# ---------------- 训练主流程 ------------------------------------------------


def test_trainer_produces_draft_with_bumped_minor_version():
    """v1.1 §3.6.4 + §9.7.5：trainer 输出 candidate 进入 ``draft`` 状态
    （v1.0 是 ``candidate`` 中间态，v1.1 简化为 draft → active 3 态）。
    """
    trainer = EvoPolicyTrainer()
    current = _make_policy(version="1.0.0")
    traces = [_make_trace(i) for i in range(10)]
    new = trainer.train_from_traces(traces, [], current)
    assert new.status == "draft"
    assert new.version == "1.1.0"
    assert new.policy_version_id.endswith(".v1.1.0")
    # v1.1 §3.6.4：previous_active_version_id 字段已删除（git history 代替）
    assert not hasattr(new, "previous_active_version_id") or getattr(
        new, "previous_active_version_id", None
    ) is None


def test_trainer_aggregates_open_blocked_reasons_into_priority():
    trainer = EvoPolicyTrainer()
    current = _make_policy()
    traces = [_make_trace(i, open_reason="missing_artifact_evidence") for i in range(5)] + [
        _make_trace(10 + i, open_reason="missing_measurement") for i in range(3)
    ]
    new = trainer.train_from_traces(traces, [], current)
    ranks = new.open_obligation_priority.get("ranks", {})
    # missing_artifact_evidence 频次 5 + fixable +10 = 15；missing_measurement 3 +10 = 13
    assert ranks["missing_artifact_evidence"] == 1
    assert ranks["missing_measurement"] == 2


def test_trainer_adjusts_ranking_weights_from_deficit_feedback():
    trainer = EvoPolicyTrainer()
    current = _make_policy(weights={"slot_class::artifact_evidence": 0.10})
    cell = FeedbackCell(
        feedback_cell_id="c1",
        feedback_packet_id="SFP-001",
        dimension={"semantic_slot_class": "artifact_evidence"},
        metric_name="slot_recall_delta",
        metric_bucket="-0.10",
        delta_bucket="-0.10",
        run_count=15,
        building_count=4,
        suppressed=False,
    )
    packet = _make_feedback_packet(cells=[cell])
    new = trainer.train_from_traces([], [packet], current)
    # 调整 +0.05
    assert new.ranking_weights["slot_class::artifact_evidence"] == pytest.approx(0.15)


def test_trainer_weight_adjustment_capped_at_per_version_delta():
    trainer = EvoPolicyTrainer()
    current = _make_policy(weights={"slot_class::x": 0.0})
    cells = []
    # 故意丢 5 个相同 deficit cell（每个 +0.05 累计 0.25 > 0.20 上限）
    for i in range(5):
        cells.append(
            FeedbackCell(
                feedback_cell_id=f"c{i}",
                feedback_packet_id="SFP-001",
                dimension={"semantic_slot_class": "x"},
                metric_name="m",
                metric_bucket="-0.10",
                delta_bucket="-0.10",
                run_count=15,
                building_count=4,
                suppressed=False,
            )
        )
    packet = _make_feedback_packet(cells=cells)
    new = trainer.train_from_traces([], [packet], current)
    # 上限 ±0.20
    assert abs(new.ranking_weights["slot_class::x"]) <= WEIGHT_MAX_DELTA_PER_VERSION + 1e-9


def test_trainer_enforces_weight_bounds_min_max():
    trainer = EvoPolicyTrainer()
    current = _make_policy(weights={"feature_x": 5.0})  # 超过 WEIGHT_MAX=2.0
    new = trainer.train_from_traces([], [], current)
    assert new.ranking_weights["feature_x"] == WEIGHT_MAX


def test_trainer_skill_activation_order_sorts_by_closed_rate():
    trainer = EvoPolicyTrainer()
    current = _make_policy()
    traces = []
    # skill A 出现 5 次，全 closed
    for i in range(5):
        traces.append(
            _make_trace(
                i,
                closed_count=10,
                open_count=0,
                blocked_count=0,
                skill_ids=["skill.A.v1"],
            )
        )
    # skill B 出现 5 次，没 closed
    for i in range(5, 10):
        traces.append(
            _make_trace(
                i,
                closed_count=0,
                open_count=10,
                blocked_count=0,
                skill_ids=["skill.B.v1"],
            )
        )
    new = trainer.train_from_traces(traces, [], current)
    order = new.skill_activation_order["ordered_skill_version_ids"]
    assert order.index("skill.A.v1") < order.index("skill.B.v1")


def test_trainer_tightens_deep_lookup_budget_on_tool_calls_increase():
    trainer = EvoPolicyTrainer()
    current = _make_policy(fallback_thresholds={"deep_lookup_max_per_run": 5})
    # baseline median 10，本批 median 20（+100% 增长，远超 15% 阈值）
    traces = [_make_trace(i, tool_count=20) for i in range(10)]
    new = trainer.train_from_traces(
        traces, [], current, baseline_tool_calls_median=10.0
    )
    assert new.fallback_thresholds["deep_lookup_max_per_run"] == 4


def test_trainer_does_not_tighten_when_increase_within_threshold():
    trainer = EvoPolicyTrainer()
    current = _make_policy(fallback_thresholds={"deep_lookup_max_per_run": 5})
    traces = [_make_trace(i, tool_count=11) for i in range(10)]  # +10%
    new = trainer.train_from_traces(
        traces, [], current, baseline_tool_calls_median=10.0
    )
    assert new.fallback_thresholds["deep_lookup_max_per_run"] == 5


def test_trainer_candidate_floor_enforced():
    trainer = EvoPolicyTrainer()
    current = _make_policy(candidate_cutoff={"max_candidates": 0})
    new = trainer.train_from_traces([], [], current)
    # 0 被矫正为 1
    assert new.candidate_cutoff_policy["max_candidates"] == 1


def test_trainer_records_trained_on_feedback_packet_ids():
    """v1.1 §3.6.4：``trained_on_feedback_packet_ids`` 保留但不再硬约束。

    trainer 仍记录 packet id 供 runtime trend feedback 接口审计；同时
    在新字段 ``trained_on_artifacts`` 中以 ``sanitized_packet:<id>`` 前缀引用。
    """
    trainer = EvoPolicyTrainer()
    current = _make_policy()
    packets = [_make_feedback_packet() for _ in range(3)]
    for i, p in enumerate(packets):
        packets[i] = p.model_copy(update={"feedback_packet_id": f"SFP-{i}"})
    new = trainer.train_from_traces([], packets, current)
    assert sorted(new.trained_on_feedback_packet_ids) == ["SFP-0", "SFP-1", "SFP-2"]
    # v1.1 §3.6.4：trained_on_artifacts 内同时含 sanitized_packet 引用
    for pkt_id in ("SFP-0", "SFP-1", "SFP-2"):
        assert any(
            ref.startswith(f"sanitized_packet:{pkt_id}")
            for ref in new.trained_on_artifacts
        ), f"trained_on_artifacts 缺 sanitized_packet:{pkt_id} 引用"


def test_trainer_records_trained_on_artifacts_with_raw_eval_truth_report():
    """v1.1 §9.7.1：trainer 可直接读 raw ``EvalTruthReport``；
    输出 ``trained_on_artifacts`` 含 ``eval_truth_report:<id>:<hash>`` 引用。
    """
    trainer = EvoPolicyTrainer()
    current = _make_policy()
    eval_reports = [
        {
            "eval_truth_report_id": "ETR-test-001",
            "eval_window_id": "EW-001",
            "per_run_results": [],
        }
    ]
    new = trainer.train_from_traces(
        [],
        [],
        current,
        eval_truth_reports=eval_reports,
        trained_on_replay_set_id="RS-test",
    )
    # 必含 raw eval_truth_report 引用 + replay_set 引用
    assert any(
        ref.startswith("eval_truth_report:ETR-test-001:")
        for ref in new.trained_on_artifacts
    )
    assert any(ref.startswith("replay_set:RS-test") for ref in new.trained_on_artifacts)


def test_trainer_records_trained_on_artifacts_with_raw_w2_artifacts():
    """v1.1 §9.7.1：trainer 可直接读 raw W2 projection tables；
    输出 ``trained_on_artifacts`` 含 ``w2_artifact:<id>:<hash>`` 引用。
    """
    trainer = EvoPolicyTrainer()
    current = _make_policy()
    w2_arts = [
        {"artifact_id": "projections.parquet", "schema_version": "1.0"},
        {"artifact_id": "threshold_evaluations.parquet", "schema_version": "1.0"},
    ]
    new = trainer.train_from_traces(
        [],
        [],
        current,
        raw_w2_artifacts=w2_arts,
    )
    assert any(
        ref.startswith("w2_artifact:projections.parquet:")
        for ref in new.trained_on_artifacts
    )
    assert any(
        ref.startswith("w2_artifact:threshold_evaluations.parquet:")
        for ref in new.trained_on_artifacts
    )


def test_trainer_no_allow_stop_policy_field():
    """spec v1 §6 / §12.2：EvoPolicyVersion 不得含 allow_stop_policy 字段。

    通过 Pydantic `extra=forbid` 间接保证，本测试通过尝试构造确认。
    """
    with pytest.raises(Exception):
        EvoPolicyVersion(
            policy_version_id="x",
            policy_id="x",
            version="1.0.0",
            status="draft",
            allow_stop_policy={"override": True},  # type: ignore[call-arg]
            trained_on_replay_set_id="RS-x",
            created_at="2026-05-24T00:00:00Z",
        )
