"""EvoFeedbackBroker 单元测试（spec v1 §8）。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from evo_agent_baseline.contracts import (
    EvoRunStep,
    EvoRunTrace,
    FeedbackCell,
    SanitizedFeedbackPacket,
)
from evo_agent_baseline.evo.feedback_broker import (
    BrokerLeakageError,
    EvoFeedbackBroker,
)


# ---------------- fixtures ---------------------------------------------------


def _build_raw_report(
    *,
    run_count: int = 12,
    building_count: int = 4,
    aggregable_cells_per_run: int = 1,
    rule_family: str = "mbis.reporting.artifact",
    metric_value: float = -0.12,
    suggested_action: str = "skill_induction_candidate",
) -> Dict[str, Any]:
    per_run = []
    for i in range(run_count):
        b_idx = i % building_count
        per_run.append(
            {
                "run_id": f"CAR-test-{i:03d}",
                "building_id": f"BLD-test-{b_idx:03d}",
                "expected_verdict": "violated",  # raw W2 字段（broker 内部应不暴露）
                "projection_refs": ["proj-foo"],
                "aggregable_cells": [
                    {
                        "dimension": {
                            "rule_family": rule_family,
                            "semantic_slot_class": "artifact_evidence",
                            "obligation_kind": "report_field",
                            "error_code": "missing_artifact",
                        },
                        "metric_name": "slot_requirement_recall_delta",
                        "metric_value": metric_value,
                        "suggested_evo_action": suggested_action,
                    }
                    for _ in range(aggregable_cells_per_run)
                ],
            }
        )
    return {
        "eval_truth_report_id": "ETR-test-001",
        "eval_window_id": "EW-test-001",
        "source_w2_bundle_id": "W2-test",
        "runs_evaluated": [f"CAR-test-{i:03d}" for i in range(run_count)],
        "per_run_results": per_run,
    }


def _build_trace(idx: int) -> EvoRunTrace:
    return EvoRunTrace(
        trace_id=f"ERT-test-{idx:03d}",
        run_id=f"CAR-test-{idx:03d}",
        world_id_hash=f"sha256:world_{idx:03d}",
        building_id_hash=f"sha256:bld_{idx:03d}",
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
        closure_summary={},
        report_ref=None,
        hook_results_hash="sha256:hooks",
        tool_call_count=10,
        llm_iterations_used=5,
        cost={"tokens": 100},
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


# ---------------- happy path ------------------------------------------------


def test_broker_happy_path_outputs_packet_with_k_anon_and_rounded_metrics():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report(run_count=12, building_count=4, metric_value=-0.12)
    packet = broker.ingest_eval_truth_report(raw, aggregation_level="batch_rule_family")
    assert isinstance(packet, SanitizedFeedbackPacket)
    assert packet.run_count == 12
    assert packet.building_count == 4
    assert packet.k_anonymity_passed is True
    assert packet.forbidden_scan_passed is True
    assert packet.cell_count >= 1
    # rounded 0.05：-0.12 → -0.10 后格式 +-0.10
    assert all(c.metric_bucket in {"-0.10", "-0.15"} for c in packet.cells if not c.suppressed)


def test_broker_packet_has_no_raw_w2_fields():
    """spec v1 §2.3.4：packet 内禁止 expected_verdict / projection_refs。"""
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw)
    packet_text = packet.model_dump_json()
    assert "expected_verdict" not in packet_text
    assert "projection_refs" not in packet_text


# ---------------- k-anonymity / suppression ---------------------------------


def test_broker_rejects_when_run_count_below_k():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report(run_count=5, building_count=2)
    with pytest.raises(BrokerLeakageError, match="k-anonymity"):
        broker.ingest_eval_truth_report(raw)


def test_broker_suppresses_cell_under_k_but_passes_packet_when_packet_k_pass():
    """cell 维度 k 不达：suppressed=True；packet 顶层 k 仍达可发布。"""
    broker = EvoFeedbackBroker()
    # 构造：12 runs / 4 buildings，但 cell 维度只有 1 building（同一 building 12 次）
    per_run = [
        {
            "run_id": f"CAR-{i}",
            "building_id": f"BLD-{i % 4}",
            "aggregable_cells": [
                {
                    "dimension": {"rule_family": "rare_family", "obligation_kind": "trigger"},
                    "metric_name": "x",
                    "metric_value": 0.0,
                }
            ]
            if i < 2
            else [],
        }
        for i in range(12)
    ]
    raw = {
        "eval_window_id": "EW-supp",
        "runs_evaluated": [f"CAR-{i}" for i in range(12)],
        "per_run_results": per_run,
    }
    packet = broker.ingest_eval_truth_report(raw)
    assert packet.k_anonymity_passed is True
    assert any(c.suppressed for c in packet.cells)
    # suppressed cell 不输出 metric
    for c in packet.cells:
        if c.suppressed:
            assert c.metric_bucket == "suppressed"
            assert c.delta_bucket is None


# ---------------- rounding ---------------------------------------------------


def test_broker_apply_rounding_nearest_005():
    broker = EvoFeedbackBroker(rounding_policy="nearest_0.05")
    cells = [
        FeedbackCell(
            feedback_cell_id="c1",
            feedback_packet_id="p1",
            dimension={"rule_family": "x"},
            metric_name="m",
            metric_bucket="0.123",
            delta_bucket="-0.073",
            run_count=15,
            building_count=4,
            suppressed=False,
        )
    ]
    out = broker.apply_rounding(cells)
    assert out[0].metric_bucket == "0.10"
    assert out[0].delta_bucket == "-0.05"


def test_broker_apply_rounding_bucket_low_medium_high():
    broker = EvoFeedbackBroker(rounding_policy="bucket_low_medium_high")
    cells = [
        FeedbackCell(
            feedback_cell_id="c1",
            feedback_packet_id="p1",
            dimension={},
            metric_name="m",
            metric_bucket="-0.20",
            run_count=15,
            building_count=4,
            suppressed=False,
        ),
        FeedbackCell(
            feedback_cell_id="c2",
            feedback_packet_id="p1",
            dimension={},
            metric_name="m",
            metric_bucket="0.0",
            run_count=15,
            building_count=4,
            suppressed=False,
        ),
        FeedbackCell(
            feedback_cell_id="c3",
            feedback_packet_id="p1",
            dimension={},
            metric_name="m",
            metric_bucket="0.30",
            run_count=15,
            building_count=4,
            suppressed=False,
        ),
    ]
    out = broker.apply_rounding(cells)
    buckets = [c.metric_bucket for c in out]
    assert buckets == ["low", "medium", "high"]


# ---------------- release delay ---------------------------------------------


def test_broker_apply_release_delay_pushes_released_at():
    broker = EvoFeedbackBroker(release_delay_windows=2)
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw)
    delayed = broker.apply_release_delay(packet, delay_windows=2)
    assert delayed.release_delay_window_count == 2
    assert delayed.released_at > delayed.created_at


def test_broker_apply_release_delay_rejects_zero():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw)
    with pytest.raises(ValueError, match="delay_windows 必须 >= 1"):
        broker.apply_release_delay(packet, delay_windows=0)


# ---------------- forbidden scan --------------------------------------------


def test_broker_forbidden_scan_detects_forbidden_field_in_dimension():
    broker = EvoFeedbackBroker()
    cell = FeedbackCell(
        feedback_cell_id="c1",
        feedback_packet_id="p1",
        dimension={"expected_verdict": "violated"},
        metric_name="m",
        metric_bucket="0.10",
        run_count=15,
        building_count=4,
        suppressed=False,
    )
    pkt = SanitizedFeedbackPacket(
        feedback_packet_id="p1",
        eval_window_id="EW-x",
        source_eval_truth_report_hash="sha256:x",
        aggregation_level="batch_rule_family",
        run_count=15,
        building_count=4,
        cell_count=1,
        rounding_policy="nearest_0.05",
        release_delay_window_count=1,
        cells=[cell],
        forbidden_scan_passed=False,
        k_anonymity_passed=True,
        reconstruction_audit_passed=False,
        created_at="2026-05-24T00:00:00Z",
        released_at="2026-05-24T00:00:00Z",
    )
    assert broker.run_forbidden_scan(pkt) is False


# ---------------- reconstruction audit --------------------------------------


def test_broker_reconstruction_audit_passes_for_low_entropy():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw)
    traces = [_build_trace(i) for i in range(12)]
    assert broker.run_reconstruction_audit(packet, traces) is True


def test_broker_reconstruction_audit_fails_with_empty_traces_when_cells_present():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw)
    # 非 suppressed cell 存在但 traces 为空 → audit fail
    assert broker.run_reconstruction_audit(packet, []) is False


# ---------------- raw report 必填字段 ---------------------------------------


def test_broker_rejects_raw_report_missing_eval_window_id():
    broker = EvoFeedbackBroker()
    with pytest.raises(BrokerLeakageError, match="eval_window_id"):
        broker.ingest_eval_truth_report({"per_run_results": []})


def test_broker_rejects_raw_report_missing_per_run_results():
    broker = EvoFeedbackBroker()
    with pytest.raises(BrokerLeakageError, match="per_run_results"):
        broker.ingest_eval_truth_report({"eval_window_id": "EW-x"})


# ---------------- aggregation level -----------------------------------------


def test_broker_aggregation_level_batch_slot_class():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    packet = broker.ingest_eval_truth_report(raw, aggregation_level="batch_slot_class")
    assert packet.aggregation_level == "batch_slot_class"
    # 维度内含 semantic_slot_class
    for c in packet.cells:
        if not c.suppressed:
            assert "semantic_slot_class" in c.dimension


def test_broker_rejects_invalid_aggregation_level():
    broker = EvoFeedbackBroker()
    raw = _build_raw_report()
    with pytest.raises(ValueError, match="非法 aggregation_level"):
        broker.ingest_eval_truth_report(raw, aggregation_level="bogus_level")
