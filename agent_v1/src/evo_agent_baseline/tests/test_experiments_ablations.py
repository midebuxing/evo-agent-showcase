"""Ablation 配置 + 执行测试（spec v1 §11.7）。

覆盖：
- 5 个核心 variant 默认配置可枚举（baseline_static / trace_only /
  policy_only / skill_only / full_evo）；
- AblationConfig __post_init__ 校验：no_candidate_floor 强绑同名 variant /
  skill_disabled 必须带 disabled_skill_id；
- ``full_evo_no_candidate_floor`` publishable=False（spec §11.7 末段）；
- run_ablation：factory 接 config，跑 paired held-out，聚合 delta；
- run_ablation 返回 PairedResult 数量 = holdout 长度。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import pytest

from evo_agent_baseline.experiments.ablations import (
    DEFAULT_ABLATIONS,
    AblationConfig,
    AblationResult,
    AblationVariant,
    list_default_ablations,
    run_ablation,
)
from evo_agent_baseline.experiments.paired_runner import (
    CaseRunner,
    PairedExperimentRunner,
)


def _make_cases(n: int = 4) -> List[Dict[str, Any]]:
    return [
        {
            "case_id": f"H-{i:03d}",
            "building_id": f"BLD-H-{i:03d}",
            "world_family": "fam_X",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 默认 5 variant 注册表
# ---------------------------------------------------------------------------


def test_default_ablations_has_five_core_variants() -> None:
    """spec v1 §11.7 5 个必跑 variant 默认配置都在注册表里。"""
    expected = {
        "baseline_static",
        "trace_only",
        "policy_only",
        "skill_only",
        "full_evo",
    }
    assert set(DEFAULT_ABLATIONS.keys()) >= expected


def test_list_default_ablations_returns_five_in_order() -> None:
    configs = list_default_ablations()
    assert len(configs) == 5
    variants = [c.variant for c in configs]
    assert variants == [
        "baseline_static",
        "trace_only",
        "policy_only",
        "skill_only",
        "full_evo",
    ]


def test_baseline_static_disables_all_evo_components() -> None:
    """spec §11.7 ``baseline_static`` = v0.4 frozen 无 evo."""
    c = DEFAULT_ABLATIONS["baseline_static"]
    assert not c.enable_trace_capture
    assert not c.enable_skill_runtime
    assert not c.enable_policy_runtime
    assert not c.enable_feedback_broker


def test_trace_only_enables_only_trace_capture() -> None:
    c = DEFAULT_ABLATIONS["trace_only"]
    assert c.enable_trace_capture
    assert not c.enable_skill_runtime
    assert not c.enable_policy_runtime


def test_skill_only_enables_skill_not_policy() -> None:
    c = DEFAULT_ABLATIONS["skill_only"]
    assert c.enable_skill_runtime
    assert not c.enable_policy_runtime


def test_policy_only_enables_policy_not_skill() -> None:
    c = DEFAULT_ABLATIONS["policy_only"]
    assert c.enable_policy_runtime
    assert not c.enable_skill_runtime


def test_full_evo_enables_all_four_components() -> None:
    c = DEFAULT_ABLATIONS["full_evo"]
    assert c.enable_trace_capture
    assert c.enable_skill_runtime
    assert c.enable_policy_runtime
    assert c.enable_feedback_broker


# ---------------------------------------------------------------------------
# AblationConfig 校验
# ---------------------------------------------------------------------------


def test_ablation_no_candidate_floor_only_for_matching_variant() -> None:
    """no_candidate_floor=True 只允许同名 variant。"""
    with pytest.raises(ValueError, match="no_candidate_floor=True 只允许"):
        AblationConfig(
            variant="full_evo",
            enable_trace_capture=True,
            enable_skill_runtime=True,
            enable_policy_runtime=True,
            no_candidate_floor=True,
        )


def test_ablation_skill_disabled_requires_skill_id() -> None:
    """skill_disabled variant 必须带 disabled_skill_id。"""
    with pytest.raises(ValueError, match="disabled_skill_id"):
        AblationConfig(variant="skill_disabled")


def test_full_evo_no_candidate_floor_not_publishable() -> None:
    """spec §11.7 末段：``不可作为 release gain`` → publishable=False."""
    cfg = AblationConfig(
        variant="full_evo_no_candidate_floor",
        enable_trace_capture=True,
        enable_skill_runtime=True,
        enable_policy_runtime=True,
        enable_feedback_broker=True,
        no_candidate_floor=True,
    )
    assert cfg.publishable is False


def test_standard_full_evo_is_publishable() -> None:
    assert DEFAULT_ABLATIONS["full_evo"].publishable is True


def test_skill_disabled_with_id_constructs_ok() -> None:
    cfg = AblationConfig(
        variant="skill_disabled",
        enable_trace_capture=True,
        disabled_skill_id="skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
    )
    assert cfg.disabled_skill_id


# ---------------------------------------------------------------------------
# run_ablation
# ---------------------------------------------------------------------------


def _baseline_runner(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
    return {"family_recall": 0.5, "blocked_count": 3, "open_count": 4}


def _ablation_factory(config: AblationConfig) -> CaseRunner:
    """简单 factory：full_evo 给 +0.2 family_recall，trace_only 给 +0.05。"""
    if config.variant == "full_evo":
        gain = 0.2
    elif config.variant == "trace_only":
        gain = 0.05
    else:
        gain = 0.0

    def runner(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return {
            "family_recall": 0.5 + gain,
            "blocked_count": max(0, 3 - int(gain * 10)),
            "open_count": max(0, 4 - int(gain * 10)),
        }

    return runner


def test_run_ablation_returns_paired_results_for_each_case() -> None:
    """run_ablation 返回的 paired_results 数 = holdout 长度。"""
    cases = _make_cases(4)
    runner = PairedExperimentRunner(seed=1)
    result = run_ablation(
        DEFAULT_ABLATIONS["full_evo"],
        runner,
        holdout_cases=cases,
        baseline_runner_ref=_baseline_runner,
        ablation_runner_factory=_ablation_factory,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    assert isinstance(result, AblationResult)
    assert len(result.paired_results) == 4
    assert result.publishable is True


def test_run_ablation_aggregate_delta_averages_metric_diffs() -> None:
    """aggregate_delta 是逐 metric key 跨 case 的平均 delta。"""
    cases = _make_cases(4)
    runner = PairedExperimentRunner(seed=1)
    result = run_ablation(
        DEFAULT_ABLATIONS["full_evo"],
        runner,
        holdout_cases=cases,
        baseline_runner_ref=_baseline_runner,
        ablation_runner_factory=_ablation_factory,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    # full_evo gain 0.2 → family_recall delta = +0.2 平均
    assert result.aggregate_delta["family_recall"] == pytest.approx(0.2)
    # blocked_count delta = max(0, 3-2) - 3 = -2
    assert result.aggregate_delta["blocked_count"] == pytest.approx(-2.0)


def test_run_ablation_baseline_static_produces_zero_delta() -> None:
    """baseline_static variant 与 baseline_runner_ref 相同 → delta ≈ 0."""
    cases = _make_cases(3)
    runner = PairedExperimentRunner(seed=1)
    result = run_ablation(
        DEFAULT_ABLATIONS["baseline_static"],
        runner,
        holdout_cases=cases,
        baseline_runner_ref=_baseline_runner,
        ablation_runner_factory=_ablation_factory,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    assert result.aggregate_delta["family_recall"] == pytest.approx(0.0)


def test_run_ablation_no_candidate_floor_marked_non_publishable() -> None:
    """``full_evo_no_candidate_floor`` 跑完 publishable 仍 False."""
    cfg = AblationConfig(
        variant="full_evo_no_candidate_floor",
        enable_trace_capture=True,
        enable_skill_runtime=True,
        enable_policy_runtime=True,
        enable_feedback_broker=True,
        no_candidate_floor=True,
    )
    cases = _make_cases(2)
    runner = PairedExperimentRunner(seed=1)
    result = run_ablation(
        cfg,
        runner,
        holdout_cases=cases,
        baseline_runner_ref=_baseline_runner,
        ablation_runner_factory=_ablation_factory,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    assert result.publishable is False
