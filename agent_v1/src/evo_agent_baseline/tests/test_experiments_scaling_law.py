"""Scaling Law 指标测试（spec v1 §11.1-§11.4 + §11.8）。

覆盖：
- effective trace 公式（spec §11.2 / §11.3）：valid/invalid/novelty 衰减/
  coverage clamp / feedback bool 切换；
- E_runtime（spec §11.3）：trace 是否属 sanitized packet aggregate window
  影响 feedback_available_i ∈ {1.0, 1.2}；
- 三类指标 happy / edge：verdict_macro_f1 / closure non-regression /
  skill_attributable_delta；
- Error(E) 曲线拟合（spec §11.8）：A>0, alpha>0, beta>=0 + 不足样本抛错。

evo-agent blind：本测试输入 dict aggregate，不含 raw W2 字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from evo_agent_baseline.experiments.scaling_law import (
    COVERAGE_WEIGHT_MAX,
    NOVELTY_FLOOR,
    compute_closure_quality_metrics,
    compute_compliance_quality_metrics,
    compute_e_runtime,
    compute_effective_trace_count,
    compute_evo_specific_metrics,
    fit_error_curve,
)


# ---------------------------------------------------------------------------
# 简易 fixture：mock trace / skill / policy / validation 对象
# ---------------------------------------------------------------------------


@dataclass
class _MockTrace:
    """模拟 EvoRunTrace（contracts.py B.2 字段子集）。"""

    trace_id: str
    forbidden_scan_passed: bool = True
    source_visibility_audit_passed: bool = True
    schema_audit_passed: bool = True
    candidate_floor_passed: bool = True
    trace_visibility: str = "agent_visible_trace"
    rule_family: str = "structural_inspection"
    semantic_slot_class: str = "world_core"
    obligation_kind: str = "presence_check"
    open_or_blocked_reason: str = ""
    sanitized_feedback_refs: List[str] = field(default_factory=list)
    tool_call_count: int = 4
    closure_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _MockPacket:
    feedback_packet_id: str


@dataclass
class _MockSkill:
    activation_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _MockPolicy:
    status: str
    validation_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _MockValidation:
    validation_stage: str
    passed: bool = True
    leakage_hits: List[str] = field(default_factory=list)
    metric_name: str = ""
    metric_value_bucket: str = "0.0"


def _eligible_map(trace_ids: List[str]) -> Dict[str, str]:
    return {tid: "eligible" for tid in trace_ids}


# ---------------------------------------------------------------------------
# effective_trace_count
# ---------------------------------------------------------------------------


def test_effective_trace_count_all_valid_baseline_weight() -> None:
    """spec §11.3：单 trace 全 valid + 默认 coverage/feedback → weight = 1*1*1*1 = 1."""
    traces = [_MockTrace("T1")]
    count = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1"]),
    )
    assert count == pytest.approx(1.0)


def test_effective_trace_count_invalid_trace_zero() -> None:
    """spec §11.2：invalid trace（任一谓词 False） → 0 贡献."""
    traces = [_MockTrace("T1", forbidden_scan_passed=False)]
    count = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1"]),
    )
    assert count == 0.0


def test_effective_trace_count_replay_ineligible_zero() -> None:
    """spec §11.2 第 6 条：replay_case eligibility != eligible → 0."""
    traces = [_MockTrace("T1")]
    count = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace={"T1": "invalid_leakage"},
    )
    assert count == 0.0


def test_effective_trace_count_novelty_decays_on_repeat_pattern() -> None:
    """spec §11.3 ``novelty_i = 1/sqrt(1+n_seen(pattern))``，下限 0.2。

    3 个同 pattern → novelty 序列 [1.0, 1/√2, 1/√3] ≈ [1.0, 0.707, 0.577]。
    """
    traces = [
        _MockTrace("T1"),
        _MockTrace("T2"),
        _MockTrace("T3"),
    ]
    count = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1", "T2", "T3"]),
    )
    # 1.0 + 1/√2 + 1/√3 ≈ 2.284
    assert count == pytest.approx(1.0 + 1 / 2**0.5 + 1 / 3**0.5, rel=1e-4)


def test_effective_trace_count_novelty_floor_at_0_2() -> None:
    """spec §11.3 novelty 下限 0.2：极多同 pattern → 至少 0.2/条."""
    traces = [_MockTrace(f"T{i}") for i in range(200)]
    count = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map([f"T{i}" for i in range(200)]),
    )
    # n=200 时 1/sqrt(200) ≈ 0.0707 < 0.2，所以后段 trace 取 floor 0.2
    # 总和 >= 0.2 × (200 - 一些早期 trace 的高 novelty) ≈ >= 40
    assert count > 40.0
    # 上界宽：early traces 都接近 1.0，后段 0.2 floor
    assert count < 100.0


def test_effective_trace_count_coverage_weight_clamped() -> None:
    """spec §11.3 coverage_weight ∈ [1.0, 3.0]。传入越界值时夹紧。"""
    traces = [_MockTrace("T1")]
    over = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1"]),
        coverage_weight_by_trace={"T1": 10.0},
    )
    under = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1"]),
        coverage_weight_by_trace={"T1": 0.1},
    )
    assert over == pytest.approx(COVERAGE_WEIGHT_MAX)  # clamp 到 3.0
    assert under == pytest.approx(1.0)  # clamp 到 1.0


def test_effective_trace_count_feedback_bonus_1_2() -> None:
    """spec §11.3 feedback_available_i ∈ {1.0, 1.2}。"""
    traces = [_MockTrace("T1")]
    count_with_fb = compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=_eligible_map(["T1"]),
        feedback_available_trace_ids=["T1"],
    )
    assert count_with_fb == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# E_runtime
# ---------------------------------------------------------------------------


def test_e_runtime_links_traces_to_packets_via_sanitized_refs() -> None:
    """spec §11.3：trace.sanitized_feedback_refs 与 packet.feedback_packet_id
    交集非空 → trace 在 aggregate window 内 → feedback_available=1.2。"""
    traces = [
        _MockTrace("T1", sanitized_feedback_refs=["SFP-W1-AAA"]),
        _MockTrace("T2", sanitized_feedback_refs=[]),
    ]
    packets = [_MockPacket("SFP-W1-AAA")]
    e = compute_e_runtime(
        traces,
        packets,
        replay_eligibility_by_trace=_eligible_map(["T1", "T2"]),
    )
    # T1: 1×1×1×1.2=1.2, T2 同 pattern n_seen=1: 1×(1/√2)×1×1=0.707
    expected = 1.2 + 1 / 2**0.5
    assert e == pytest.approx(expected, rel=1e-4)


def test_e_runtime_no_packets_falls_back_to_default_feedback() -> None:
    """没 packet 时所有 trace feedback_available=1.0."""
    traces = [_MockTrace("T1")]
    e = compute_e_runtime(
        traces,
        [],
        replay_eligibility_by_trace=_eligible_map(["T1"]),
    )
    assert e == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 第 1 类：合规任务质量指标
# ---------------------------------------------------------------------------


def test_compliance_metrics_perfect_match_macro_f1_1() -> None:
    """完美预测 → macro F1 = 1.0."""
    records = [
        {"predicted_verdict": "pass", "reference_verdict": "pass"},
        {"predicted_verdict": "fail", "reference_verdict": "fail"},
        {"predicted_verdict": "unknown", "reference_verdict": "unknown"},
        {"predicted_verdict": "not_applicable", "reference_verdict": "not_applicable"},
    ]
    metrics = compute_compliance_quality_metrics(records)
    assert metrics["verdict_macro_f1"] == pytest.approx(1.0)
    assert metrics["severity_weighted_accuracy"] == pytest.approx(1.0)


def test_compliance_metrics_empty_returns_zero() -> None:
    """空输入返回 0，spec §11.4.1 不报错."""
    metrics = compute_compliance_quality_metrics([])
    assert metrics["verdict_macro_f1"] == 0.0


def test_compliance_metrics_family_recall_precision() -> None:
    """family_recall / family_precision 计算正确（aggregate dict）。"""
    records = [
        {
            "agent_families": ["F1", "F2"],
            "reference_families": ["F1", "F3"],
            "predicted_verdict": "pass",
            "reference_verdict": "pass",
        }
    ]
    m = compute_compliance_quality_metrics(records)
    # recall: F1 in ref → 1/2, precision: F1 in agent → 1/2
    assert m["family_recall"] == pytest.approx(0.5)
    assert m["family_precision"] == pytest.approx(0.5)


def test_compliance_metrics_threshold_alignment() -> None:
    """threshold_operator/value/observed 全等才算 aligned."""
    records = [
        {
            "predicted_threshold_operator": ">=",
            "reference_threshold_operator": ">=",
            "predicted_threshold_value": 0.7,
            "reference_threshold_value": 0.7,
            "predicted_observed_comparator": "actual",
            "reference_observed_comparator": "actual",
        },
        {
            "predicted_threshold_operator": ">",
            "reference_threshold_operator": ">=",
            "predicted_threshold_value": 0.7,
            "reference_threshold_value": 0.7,
            "predicted_observed_comparator": "actual",
            "reference_observed_comparator": "actual",
        },
    ]
    m = compute_compliance_quality_metrics(records)
    assert m["threshold_alignment"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 第 2 类：closure 质量指标
# ---------------------------------------------------------------------------


def test_closure_metrics_allow_stop_proxy_pass() -> None:
    """allow_stop=True 且 open/blocked=0 + guard pass → proxy=1.0."""
    closures = [
        {
            "allow_stop": True,
            "open_count": 0,
            "blocked_count": 0,
            "guard_passed": True,
            "evidence_coverage_rate": 0.9,
            "candidate_floor_passed": True,
            "schema_contract_passed": True,
        }
    ]
    m = compute_closure_quality_metrics(closures)
    assert m["allow_stop_precision_proxy"] == pytest.approx(1.0)
    assert m["candidate_floor_pass_rate"] == 1.0
    assert m["schema_contract_pass_rate"] == 1.0


def test_closure_metrics_allow_stop_proxy_fail_when_open_nonzero() -> None:
    """allow_stop=True 但 open=2 → proxy=0（不该 allow_stop）."""
    closures = [
        {
            "allow_stop": True,
            "open_count": 2,
            "blocked_count": 0,
            "guard_passed": True,
            "open_blocked_reasons": {"missing_measurement": 2},
        }
    ]
    m = compute_closure_quality_metrics(closures)
    assert m["allow_stop_precision_proxy"] == 0.0
    assert m["open_blocked_by_reason"]["missing_measurement"] == 2


def test_closure_metrics_non_regression_detects_worsening() -> None:
    """spec §11.4.2 closure_non_regression：open_count 平均变高 → fail."""
    closures = [{"open_count": 5, "blocked_count": 0, "evidence_coverage_rate": 0.5}]
    prev = {
        "open_count_avg": 2.0,
        "blocked_count_avg": 0.0,
        "evidence_coverage_rate_avg": 0.5,
    }
    m = compute_closure_quality_metrics(closures, previous_release_metrics=prev)
    assert m["closure_non_regression"] == 0.0


def test_closure_metrics_non_regression_first_release() -> None:
    """无 previous_release → 默认 1.0（pass）."""
    closures = [{"open_count": 5}]
    m = compute_closure_quality_metrics(closures)
    assert m["closure_non_regression"] == 1.0


def test_closure_metrics_empty_returns_defaults() -> None:
    m = compute_closure_quality_metrics([])
    assert m["allow_stop_precision_proxy"] == 0.0
    assert m["open_count"] == 0.0


# ---------------------------------------------------------------------------
# 第 3 类：Evo 特有指标
# ---------------------------------------------------------------------------


def test_evo_metrics_skill_attributable_delta() -> None:
    """skill_attributable_delta = avg(with_skill - baseline)."""
    paired = [
        {"with_skill_metric": 0.8, "baseline_metric": 0.6},
        {"with_skill_metric": 0.7, "baseline_metric": 0.6},
    ]
    m = compute_evo_specific_metrics(
        traces=[],
        skills=[],
        policy_versions=[],
        validation_records=[],
        paired_results=paired,
    )
    assert m["skill_attributable_delta"] == pytest.approx(0.15)


def test_evo_metrics_skill_activation_precision() -> None:
    """activation_stats: eligible=10, positive=8 → ratio 0.8."""
    skills = [
        _MockSkill({"eligible_activation_count": 10, "positive_benefit_count": 8})
    ]
    m = compute_evo_specific_metrics(
        traces=[], skills=skills, policy_versions=[], validation_records=[]
    )
    assert m["skill_activation_precision"] == pytest.approx(0.8)


def test_evo_metrics_skill_half_life_median() -> None:
    """skill_half_life = median(active_to_retired_window_count)."""
    skills = [
        _MockSkill({"active_to_retired_window_count": 5}),
        _MockSkill({"active_to_retired_window_count": 10}),
        _MockSkill({"active_to_retired_window_count": 15}),
    ]
    m = compute_evo_specific_metrics(
        traces=[], skills=skills, policy_versions=[], validation_records=[]
    )
    assert m["skill_half_life"] == pytest.approx(10.0)


def test_evo_metrics_policy_version_improvement_rate() -> None:
    """active policy 中 positive_heldout_delta=True 比例."""
    policies = [
        _MockPolicy("active", {"positive_heldout_delta": True}),
        _MockPolicy("active", {"positive_heldout_delta": False}),
        _MockPolicy("retired", {"positive_heldout_delta": True}),  # 非 active 排除
    ]
    m = compute_evo_specific_metrics(
        traces=[], skills=[], policy_versions=policies, validation_records=[]
    )
    assert m["policy_version_improvement_rate"] == pytest.approx(0.5)


def test_evo_metrics_tool_cost_per_closed_obligation() -> None:
    """tool_cost = total tool_call_count / closed_obligation_count."""
    traces = [_MockTrace("T1"), _MockTrace("T2")]
    m = compute_evo_specific_metrics(
        traces=traces,
        skills=[],
        policy_versions=[],
        validation_records=[],
        closed_obligation_count=2,
    )
    # 默认 tool_call_count=4, 2 trace → 8 / 2 = 4
    assert m["tool_cost_per_closed_obligation"] == pytest.approx(4.0)


def test_evo_metrics_w2_reconstruction_probe_delta_max() -> None:
    """从 release_gate validation 中取最大 probe_delta."""
    records = [
        _MockValidation(
            "release_gate",
            metric_name="w2_reconstruction_probe_delta",
            metric_value_bucket="0.03",
        ),
        _MockValidation(
            "release_gate",
            metric_name="w2_reconstruction_probe_delta",
            metric_value_bucket="0.045",
        ),
        # 干扰：非 release_gate / 非 reconstruction
        _MockValidation(
            "gate0_static",
            metric_name="w2_reconstruction_probe_delta",
            metric_value_bucket="0.10",
        ),
    ]
    m = compute_evo_specific_metrics(
        traces=[], skills=[], policy_versions=[], validation_records=records
    )
    assert m["w2_reconstruction_probe_delta"] == pytest.approx(0.045)


def test_evo_metrics_feedback_blindness_pass_rate() -> None:
    """gate0/gate1/release_gate 中 passed + leakage_hits 空的比例."""
    records = [
        _MockValidation("gate0_static", passed=True),
        _MockValidation("gate1_schema_provenance", passed=True),
        _MockValidation("gate1_schema_provenance", passed=False),
        _MockValidation("release_gate", passed=True, leakage_hits=["x"]),
    ]
    m = compute_evo_specific_metrics(
        traces=[], skills=[], policy_versions=[], validation_records=records
    )
    # 2 通过 / 4 relevant = 0.5
    assert m["feedback_blindness_pass_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# §11.8 学习曲线拟合
# ---------------------------------------------------------------------------


def test_fit_error_curve_recovers_power_law() -> None:
    """合成 Error(E) = 10·E^-0.5 + 0.1 → 拟合应 alpha ≈ 0.5, beta ≈ 0.1."""
    import math as _math

    es = [1.0, 4.0, 9.0, 16.0, 25.0, 36.0]
    ys = [10.0 * (e ** -0.5) + 0.1 for e in es]
    A, alpha, beta = fit_error_curve(es, ys)
    # 拟合精度允许一些误差（网格 0.05 步长）
    assert alpha == pytest.approx(0.5, abs=0.1)
    assert A > 5.0  # 应接近 10
    assert beta >= 0.0


def test_fit_error_curve_constant_returns_mean() -> None:
    """完全 constant 误差 → 返 (0, 0, mean)."""
    A, alpha, beta = fit_error_curve([1.0, 2.0, 3.0], [0.5, 0.5, 0.5])
    assert A == 0.0
    assert alpha == 0.0
    assert beta == pytest.approx(0.5)


def test_fit_error_curve_insufficient_samples_raises() -> None:
    with pytest.raises(ValueError, match="至少需要 3 个观测点"):
        fit_error_curve([1.0, 2.0], [0.5, 0.4])


def test_fit_error_curve_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="长度必须一致"):
        fit_error_curve([1.0, 2.0, 3.0], [0.5, 0.4])


def test_fit_error_curve_non_positive_experience_raises() -> None:
    with pytest.raises(ValueError, match="必须严格正"):
        fit_error_curve([1.0, 0.0, 3.0], [0.5, 0.4, 0.3])
