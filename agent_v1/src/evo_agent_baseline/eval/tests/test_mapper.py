"""mapper.py 单测（spec §8.3.1 + §8.3.2）。

覆盖 agent obligation → family verdict 的规约规则（含 applicability audit）
和 fine→coarse crosswalk 映射。
"""

from __future__ import annotations

from evo_agent_baseline.eval.mapper import (
    aggregate_agent_family_verdicts,
    default_crosswalk_path,
    load_crosswalk,
)
from evo_agent_baseline.eval.tests._fixtures import make_obligation


def _verdict_of(results, family_id):
    """从聚合结果里取某 fine family 的 verdict。"""
    for r in results:
        if r.family_id == family_id:
            return r
    raise AssertionError(f"未找到 family {family_id}")


def test_open_obligation_yields_unknown():
    """spec §8.3.1：family 内任一义务 open → verdict=unknown。"""
    obs = [
        make_obligation("O1", closure_status="closed", satisfaction_status="satisfied"),
        make_obligation(
            "O2",
            closure_status="open",
            satisfaction_status="unknown",
            open_reason_code="missing_fact",
        ),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert len(res) == 1
    assert res[0].verdict == "unknown"


def test_blocked_obligation_yields_unknown():
    """spec §8.3.1：family 内任一义务 blocked → verdict=unknown。"""
    obs = [
        make_obligation(
            "O1",
            closure_status="blocked",
            satisfaction_status="unknown",
            blocked_reason_code="internal_error",
        ),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "unknown"


def test_violated_obligation_yields_fail():
    """spec §8.3.1：全闭合且任一 violated → verdict=fail。"""
    obs = [
        make_obligation("O1", closure_status="closed", satisfaction_status="satisfied"),
        make_obligation("O2", closure_status="closed", satisfaction_status="violated"),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "fail"


def test_open_takes_precedence_over_violated():
    """spec §8.3.1 顺序：open/blocked 先判，即使另有 violated 也是 unknown。"""
    obs = [
        make_obligation("O1", closure_status="closed", satisfaction_status="violated"),
        make_obligation(
            "O2",
            closure_status="open",
            satisfaction_status="unknown",
            open_reason_code="missing_fact",
        ),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "unknown"


def test_all_satisfied_yields_pass():
    """spec §8.3.1：全 satisfied/not_applicable 且无 scope not_applicable → pass。"""
    obs = [
        make_obligation("O1", kind="evidence", satisfaction_status="satisfied"),
        make_obligation("O2", kind="threshold", satisfaction_status="satisfied"),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "pass"


def test_scope_not_applicable_yields_not_applicable():
    """spec §8.3.1 applicability audit：scope 义务 not_applicable → not_applicable。"""
    obs = [
        make_obligation(
            "O1",
            kind="scope",
            closure_status="closed",
            satisfaction_status="not_applicable",
            applicability_state="not_applicable",
        ),
        make_obligation("O2", kind="evidence", satisfaction_status="satisfied"),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "not_applicable"


def test_not_applicable_without_scope_still_pass():
    """全 not_applicable 但无 scope kind 义务 → 仍判 pass（spec §8.3.1 otherwise）。"""
    obs = [
        make_obligation(
            "O1",
            kind="evidence",
            closure_status="closed",
            satisfaction_status="not_applicable",
        ),
    ]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].verdict == "pass"


def test_aggregation_groups_by_world_fragment_family():
    """spec §8.3.1：聚合键是 (world_id, fragment_id, family)。"""
    obs = [
        make_obligation("O1", fragment_id="F1", source_family_id="fam.a"),
        make_obligation("O2", fragment_id="F1", source_family_id="fam.a"),
        make_obligation("O3", fragment_id="F2", source_family_id="fam.a"),
        make_obligation("O4", fragment_id="F1", source_family_id="fam.b"),
    ]
    res = aggregate_agent_family_verdicts(obs)
    # (F1,fam.a) / (F2,fam.a) / (F1,fam.b) = 3 组
    assert len(res) == 3
    counts = {(r.fragment_id, r.family_id): r.obligation_count for r in res}
    assert counts[("F1", "fam.a")] == 2
    assert counts[("F2", "fam.a")] == 1
    assert counts[("F1", "fam.b")] == 1


def test_crosswalk_maps_fine_to_coarse():
    """spec §8.3.2：聚合时带上 crosswalk 则 coarse_family_id 被填。"""
    cw = load_crosswalk(default_crosswalk_path())
    obs = [
        make_obligation(
            "O1", source_family_id="mbis.inspection.drainage.ri.coverage"
        ),
        make_obligation(
            "O2",
            fragment_id="F2",
            source_family_id="mbis.repair.tile_pull_test.ri.validate",
        ),
    ]
    res = aggregate_agent_family_verdicts(obs, cw)
    drainage = _verdict_of(res, "mbis.inspection.drainage.ri.coverage")
    assert drainage.coarse_family_id == "mbis.inspection.drainage"
    tile = _verdict_of(res, "mbis.repair.tile_pull_test.ri.validate")
    assert tile.coarse_family_id == "mbis.repair.external_structural_validation"


def test_unknown_fine_family_maps_to_none_coarse():
    """fine family 不在 crosswalk 时 coarse_family_id 为 None（不报错）。"""
    cw = load_crosswalk(default_crosswalk_path())
    obs = [make_obligation("O1", source_family_id="not.a.real.family")]
    res = aggregate_agent_family_verdicts(obs, cw)
    assert res[0].coarse_family_id is None


def test_aggregation_without_crosswalk_leaves_coarse_none():
    """不传 crosswalk 时 coarse_family_id 一律 None（spec §8.3.2 blocked 场景）。"""
    obs = [make_obligation("O1")]
    res = aggregate_agent_family_verdicts(obs)
    assert res[0].coarse_family_id is None
