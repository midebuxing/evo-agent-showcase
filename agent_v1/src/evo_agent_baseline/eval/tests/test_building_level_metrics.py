"""DEBT-046 楼级对齐口径（过渡期主对齐层）+ 分层诊断计数 单测。

覆盖：lattice 归约序、truth 楼级聚合（任一 fail 传染）、fragment_id=None 的
agent verdict 在楼级口径下产生 compared pairs、族唯一回退（N2）与歧义排除（N3）。
"""

from evo_agent_baseline.eval.mapper import AgentFamilyVerdict
from evo_agent_baseline.eval.metrics import (
    _reduce_verdicts_lattice,
    compute_alignment_diagnostics,
    compute_building_verdict_metrics,
)

from ._fixtures import make_truth_bundle


def _av(world_id, coarse, verdict, fine=None, fragment_id=None):
    return AgentFamilyVerdict(
        world_id=world_id,
        fragment_id=fragment_id,
        family_id=fine or f"{coarse}.ri.coverage",
        coarse_family_id=coarse,
        verdict=verdict,
        obligation_count=1,
    )


def _proj_row(world_id, fragment_id, family, verdict, severity="minor"):
    return {
        "world_id": world_id,
        "fragment_id": fragment_id,
        "projection_id": f"PJ-{world_id}-{fragment_id}-{family}",
        "projection_family": family,
        "selected_family": family,
        "expected_verdict": verdict,
        "severity_band": severity,
        "required_slots": "[]",
    }


# ---------------------------------------------------------------------------
# lattice 归约器
# ---------------------------------------------------------------------------


def test_lattice_unknown_dominates():
    assert _reduce_verdicts_lattice(["pass", "unknown", "fail"]) == "unknown"


def test_lattice_any_fail_when_no_unknown():
    assert _reduce_verdicts_lattice(["pass", "fail", "pass"]) == "fail"


def test_lattice_all_not_applicable():
    assert _reduce_verdicts_lattice(["not_applicable", "not_applicable"]) == "not_applicable"


def test_lattice_pass_na_mix_is_pass():
    assert _reduce_verdicts_lattice(["pass", "not_applicable"]) == "pass"


def test_lattice_empty_returns_blank():
    assert _reduce_verdicts_lattice([]) == ""


# ---------------------------------------------------------------------------
# 楼级 verdict metrics（方案④）
# ---------------------------------------------------------------------------


def test_building_level_pairs_with_fragment_none_agent():
    """agent fragment_id=None（现状）在楼级口径下应产生 compared pairs。"""
    truth = make_truth_bundle(
        projections_rows=[
            _proj_row("W1", "F1", "mbis.inspection.drainage", "pass"),
            _proj_row("W1", "F2", "mbis.inspection.ubw", "fail"),
        ]
    )
    avs = [
        _av("W1", "mbis.inspection.drainage", "pass"),
        _av("W1", "mbis.inspection.ubw", "fail"),
    ]
    m = compute_building_verdict_metrics(avs, truth)
    assert m.compared_pairs == 2
    assert m.expected_verdict_accuracy == 1.0
    assert m.confusion == {"pass->pass": 1, "fail->fail": 1}


def test_building_truth_aggregation_any_fail_contaminates():
    """同族多 fragment：truth 楼级聚合任一 fail → fail（agent 判 pass 记不匹配）。"""
    truth = make_truth_bundle(
        projections_rows=[
            _proj_row("W1", "F1", "mbis.inspection.drainage", "pass"),
            _proj_row("W1", "F2", "mbis.inspection.drainage", "fail"),
        ]
    )
    avs = [_av("W1", "mbis.inspection.drainage", "pass")]
    m = compute_building_verdict_metrics(avs, truth)
    assert m.compared_pairs == 1
    assert m.expected_verdict_accuracy == 0.0
    assert m.confusion == {"pass->fail": 1}


def test_building_level_agent_fine_families_reduce_to_coarse():
    """多个 fine family 映射同一 coarse：agent 侧按 lattice 归约后再对齐。"""
    truth = make_truth_bundle(
        projections_rows=[_proj_row("W1", "F1", "mbis.inspection.drainage", "fail")]
    )
    avs = [
        _av("W1", "mbis.inspection.drainage", "pass", fine="mbis.inspection.drainage.ri.coverage"),
        _av("W1", "mbis.inspection.drainage", "fail", fine="mbis.inspection.drainage.ri.identify"),
    ]
    m = compute_building_verdict_metrics(avs, truth)
    assert m.compared_pairs == 1
    # agent 侧 pass+fail → fail；truth fail → 匹配
    assert m.expected_verdict_accuracy == 1.0


def test_building_level_unmapped_coarse_skipped():
    truth = make_truth_bundle(
        projections_rows=[_proj_row("W1", "F1", "mbis.inspection.drainage", "pass")]
    )
    avs = [_av("W1", None, "pass")]  # crosswalk 未登记
    m = compute_building_verdict_metrics(avs, truth)
    assert m.compared_pairs == 0


# ---------------------------------------------------------------------------
# 分层诊断计数（N2 / N3）
# ---------------------------------------------------------------------------


def test_alignment_diagnostics_unique_vs_ambiguous():
    truth = make_truth_bundle(
        projections_rows=[
            _proj_row("W1", "F1", "mbis.inspection.drainage", "pass"),   # 族唯一
            _proj_row("W1", "F2", "mbis.inspection.ubw", "fail"),        # 族有 2 fragment
            _proj_row("W1", "F3", "mbis.inspection.ubw", "pass"),
        ]
    )
    avs = [
        _av("W1", "mbis.inspection.drainage", "pass"),
        _av("W1", "mbis.inspection.ubw", "unknown"),
    ]
    diag = compute_alignment_diagnostics(avs, truth)
    assert diag["family_unique_fallback_pairs"] == 1
    assert diag["ambiguous_excluded_pairs"] == 1
    assert diag["family_unique_fallback_confusion"] == {"pass->pass": 1}
