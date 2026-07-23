"""Paired held-out runner 测试（spec v1 §11.5 + §11.6）。

覆盖：
- split_dataset：building disjoint / world_family stratified /
  比例和 1 校验 / rare artifact 强制进 holdout / 缺 building_id 抛错；
- run_paired：同 budget / model / kg_snapshot / rulecard 等控制条件全部
  传给两 runner；
- PairedResult.compute_delta：数值差 + 非数值跳过 + 单边 key 跳过；
- run_scaling_budgets：[8,16,32] 三个 budget 各跑 paired。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import pytest

from evo_agent_baseline.experiments.paired_runner import (
    DEFAULT_EQUAL_BUDGET,
    DEFAULT_SCALING_BUDGETS,
    PairedExperimentRunner,
    PairedResult,
)


# ---------------------------------------------------------------------------
# 简易 case fixture
# ---------------------------------------------------------------------------


def _make_cases(n: int = 20, world_families: List[str] = None) -> List[Dict[str, Any]]:
    """生成 n 个 case，分散到 world_families（默认 3 个）。"""
    fams = world_families or ["fam_A", "fam_B", "fam_C"]
    out: List[Dict[str, Any]] = []
    for i in range(n):
        out.append(
            {
                "case_id": f"C-{i:03d}",
                "building_id": f"BLD-{i:03d}",
                "world_family": fams[i % len(fams)],
                "rule_families": ["structural", "fire_safety"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# split_dataset
# ---------------------------------------------------------------------------


def test_split_dataset_ratios_sum_to_total() -> None:
    """3 段长度之和 = 输入长度（building disjoint hold）。"""
    cases = _make_cases(30)
    runner = PairedExperimentRunner(seed=1)
    train, gate, holdout = runner.split_dataset(cases)
    assert len(train) + len(gate) + len(holdout) == len(cases)


def test_split_dataset_building_disjoint() -> None:
    """同 building_id 只能落入一段（spec §11.5 hard constraint）。"""
    cases = _make_cases(30)
    runner = PairedExperimentRunner(seed=1)
    train, gate, holdout = runner.split_dataset(cases)
    train_b = {c["building_id"] for c in train}
    gate_b = {c["building_id"] for c in gate}
    holdout_b = {c["building_id"] for c in holdout}
    assert train_b.isdisjoint(gate_b)
    assert train_b.isdisjoint(holdout_b)
    assert gate_b.isdisjoint(holdout_b)


def test_split_dataset_world_family_stratified() -> None:
    """每段都应至少出现每个 family（足够大 n 时）。"""
    cases = _make_cases(30, world_families=["A", "B"])
    runner = PairedExperimentRunner(seed=42)
    train, gate, holdout = runner.split_dataset(cases)
    train_fams = {c["world_family"] for c in train}
    holdout_fams = {c["world_family"] for c in holdout}
    assert "A" in train_fams and "B" in train_fams
    # holdout 至少有一个 family
    assert holdout_fams


def test_split_dataset_rare_artifact_forced_into_holdout() -> None:
    """spec §11.5 ``rare artifact/threshold boundary 保证 held_out 至少覆盖``。"""
    cases = _make_cases(30)
    # 给 case 0 标 rare
    cases[0]["is_rare_artifact_or_threshold"] = True
    runner = PairedExperimentRunner(seed=7)
    _, _, holdout = runner.split_dataset(cases)
    rare_buildings = {c["building_id"] for c in cases if c.get("is_rare_artifact_or_threshold")}
    holdout_buildings = {c["building_id"] for c in holdout}
    # 至少有一个 rare building 进了 holdout
    assert rare_buildings & holdout_buildings


def test_split_dataset_invalid_ratio_sum_raises() -> None:
    runner = PairedExperimentRunner(seed=1)
    with pytest.raises(ValueError, match="切分比例必须和为 1.0"):
        runner.split_dataset(
            _make_cases(10), train_pct=0.5, gate_pct=0.3, holdout_pct=0.3
        )


def test_split_dataset_missing_building_id_raises() -> None:
    runner = PairedExperimentRunner(seed=1)
    with pytest.raises(ValueError, match="缺 building_id"):
        runner.split_dataset([{"case_id": "X"}])


def test_split_dataset_deterministic_with_seed() -> None:
    """同 seed 多次 split 结果一致。"""
    cases = _make_cases(30)
    runner_a = PairedExperimentRunner(seed=42)
    runner_b = PairedExperimentRunner(seed=42)
    ta, ga, ha = runner_a.split_dataset(cases)
    tb, gb, hb = runner_b.split_dataset(cases)
    assert [c["building_id"] for c in ta] == [c["building_id"] for c in tb]
    assert [c["building_id"] for c in ga] == [c["building_id"] for c in gb]
    assert [c["building_id"] for c in ha] == [c["building_id"] for c in hb]


# ---------------------------------------------------------------------------
# run_paired
# ---------------------------------------------------------------------------


def test_run_paired_passes_control_conditions_to_both_runners() -> None:
    """spec §11.6 ``same model / kg / budget / verifier`` 必须传给两 runner。"""
    captured_baseline: List[Dict[str, Any]] = []
    captured_evo: List[Dict[str, Any]] = []

    def baseline_runner(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        captured_baseline.append(dict(kw))
        return {"family_recall": 0.5, "blocked_count": 3}

    def evo_runner(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        captured_evo.append(dict(kw))
        return {"family_recall": 0.6, "blocked_count": 2}

    runner = PairedExperimentRunner(seed=1)
    results = runner.run_paired(
        _make_cases(3),
        baseline_runner,
        evo_runner,
        model="qwen3.5-32b",
        kg_snapshot="kgsnap-1",
        rulecard_bundle="rcb-1",
        verifier_version="cv-1.0.0",
    )
    assert len(results) == 3
    assert len(captured_baseline) == 3 == len(captured_evo)
    for kw in captured_baseline + captured_evo:
        assert kw["model"] == "qwen3.5-32b"
        assert kw["kg_snapshot"] == "kgsnap-1"
        assert kw["rulecard_bundle"] == "rcb-1"
        assert kw["verifier_version"] == "cv-1.0.0"
        assert kw["tool_budget"] == DEFAULT_EQUAL_BUDGET  # 16


def test_run_paired_computes_delta() -> None:
    """delta = evo - baseline（数值 key 才算）。"""

    def baseline(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return {"family_recall": 0.5, "blocked_count": 3, "label": "x"}

    def evo(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return {"family_recall": 0.7, "blocked_count": 1, "label": "y"}

    runner = PairedExperimentRunner(seed=1)
    results = runner.run_paired(
        _make_cases(1),
        baseline,
        evo,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    assert results[0].delta["family_recall"] == pytest.approx(0.2)
    assert results[0].delta["blocked_count"] == pytest.approx(-2.0)
    assert "label" not in results[0].delta  # 非数值跳过


def test_run_paired_respects_custom_budget() -> None:
    """tool_budget 显式传入时覆盖默认 equal_budget。"""
    seen_budgets: List[int] = []

    def runner_fn(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        seen_budgets.append(kw["tool_budget"])
        return {}

    runner = PairedExperimentRunner(seed=1)
    runner.run_paired(
        _make_cases(2),
        runner_fn,
        runner_fn,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
        tool_budget=8,
    )
    assert seen_budgets == [8, 8, 8, 8]


def test_run_paired_records_case_id_and_budget() -> None:
    def noop(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return {}

    runner = PairedExperimentRunner(seed=1)
    results = runner.run_paired(
        _make_cases(2),
        noop,
        noop,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
        tool_budget=32,
        run_mode="stochastic",
    )
    assert results[0].budget == 32
    assert results[0].run_mode == "stochastic"
    assert results[0].case_id == "C-000"


# ---------------------------------------------------------------------------
# PairedResult.compute_delta（单元）
# ---------------------------------------------------------------------------


def test_paired_result_compute_delta_skips_single_side_keys() -> None:
    """只出现在一边的 key 不进 delta。"""
    delta = PairedResult.compute_delta(
        {"x": 1.0, "y": 2.0}, {"x": 3.0, "z": 4.0}
    )
    assert delta == {"x": 2.0}


def test_paired_result_compute_delta_empty_inputs() -> None:
    assert PairedResult.compute_delta({}, {}) == {}


# ---------------------------------------------------------------------------
# run_scaling_budgets
# ---------------------------------------------------------------------------


def test_run_scaling_budgets_iterates_8_16_32() -> None:
    """[8,16,32] 每个 budget 都跑 paired，返回 dict[budget, results]。"""

    def noop(case: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return {"family_recall": 0.5}

    runner = PairedExperimentRunner(seed=1)
    out = runner.run_scaling_budgets(
        _make_cases(2),
        noop,
        noop,
        model="m",
        kg_snapshot="k",
        rulecard_bundle="r",
        verifier_version="v",
    )
    assert set(out.keys()) == set(DEFAULT_SCALING_BUDGETS)
    for budget, results in out.items():
        assert len(results) == 2
        assert all(r.budget == budget for r in results)
