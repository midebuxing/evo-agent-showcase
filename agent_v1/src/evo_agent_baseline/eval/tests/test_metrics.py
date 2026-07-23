"""metrics.py 单测（spec §8.4.1 ~ §8.4.4）。

用造的 W2 `TruthBundle` + agent 义务 fixture，验证 verdict / coverage /
threshold / closure 各指标的算法。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.eval.mapper import (
    aggregate_agent_family_verdicts,
    default_crosswalk_path,
    load_crosswalk,
)
from evo_agent_baseline.eval.metrics import (
    compute_closure_metrics,
    compute_coverage_metrics,
    compute_threshold_metrics,
    compute_verdict_metrics,
)
from evo_agent_baseline.eval.tests._fixtures import (
    make_closure_result,
    make_obligation,
    make_truth_bundle,
)

_CW = load_crosswalk(default_crosswalk_path())


# ---------------------------------------------------------------------------
# §8.4.1 verdict metrics
# ---------------------------------------------------------------------------


def test_verdict_accuracy_exact_match():
    """expected_verdict_accuracy：agent verdict 与 W2 expected_verdict exact match。"""
    # W2 真值：fragment F1 的 drainage family expected_verdict=fail。
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "severe",
                "required_slots": [],
            }
        ],
    )
    # agent：F1 drainage 一条 violated 义务 → fail。
    obs = [
        make_obligation(
            "O1",
            fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed",
            satisfaction_status="violated",
        )
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_verdict_metrics(av, truth)
    assert m.compared_pairs == 1
    assert m.expected_verdict_accuracy == 1.0


def test_verdict_accuracy_mismatch():
    """agent verdict 与 W2 不符 → accuracy=0。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    # agent 判 pass（全 satisfied）。
    obs = [
        make_obligation(
            "O1",
            fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            satisfaction_status="satisfied",
        )
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_verdict_metrics(av, truth)
    assert m.expected_verdict_accuracy == 0.0


def test_verdict_unmapped_family_not_counted():
    """fine family 不在 crosswalk → coarse 为 None → 不计入 compared_pairs。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    obs = [make_obligation("O1", fragment_id="F1", source_family_id="bogus.family")]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_verdict_metrics(av, truth)
    assert m.compared_pairs == 0
    assert m.expected_verdict_accuracy is None


def test_severity_weighted_accuracy_weights_by_band():
    """severity_weighted_accuracy：emergency 命中权重大于 minor 命中。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "emergency",
                "required_slots": [],
            },
            {
                "world_id": "WB-T", "fragment_id": "F2", "projection_id": "NP-2",
                "projection_family": "mbis.inspection.ubw",
                "selected_family": "mbis.inspection.ubw",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            },
        ],
    )
    # agent：F1 (emergency) 命中 fail；F2 (minor) 判 pass 不命中。
    obs = [
        make_obligation(
            "O1", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        ),
        make_obligation(
            "O2", fragment_id="F2",
            source_family_id="mbis.inspection.ubw_and_related_scope.ri.coverage",
            satisfaction_status="satisfied",
        ),
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_verdict_metrics(av, truth)
    # 命中权重 4（emergency）/ 总权重 4+1=5 = 0.8。
    assert m.severity_weighted_accuracy == 0.8
    # exact accuracy = 1/2。
    assert m.expected_verdict_accuracy == 0.5


# ---------------------------------------------------------------------------
# §8.4.2 coverage metrics
# ---------------------------------------------------------------------------


def test_family_recall_and_precision():
    """family_recall / family_precision：agent coarse vs W2 matched family。"""
    truth = make_truth_bundle(
        matched_families_rows=[
            {"projection_id": "NP-1", "family_id": "mbis.inspection.drainage",
             "applicability_state": "applicable", "verdict": "fail", "rule_ids": []},
            {"projection_id": "NP-2", "family_id": "mbis.inspection.ubw",
             "applicability_state": "applicable", "verdict": "fail", "rule_ids": []},
        ],
    )
    # agent 覆盖 drainage（命中）+ external_components（W2 没有，precision 拉低）。
    obs = [
        make_obligation("O1", source_family_id="mbis.inspection.drainage.ri.coverage"),
        make_obligation(
            "O2", fragment_id="F2",
            source_family_id="mbis.inspection.external_defects.ri.identify",
        ),
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_coverage_metrics(av, obs, [], truth)
    # recall: drainage ∈ {drainage, ubw} → 1/2。
    assert m.family_recall == 0.5
    # precision: agent {drainage, external_components}；drainage 在 W2 → 1/2。
    assert m.family_precision == 0.5


def test_rule_card_recall_proxy():
    """rule_card_recall_proxy：W2 matched rule_ids 与 agent retrieved 的 overlap。"""
    truth = make_truth_bundle(
        matched_families_rows=[
            {"projection_id": "NP-1", "family_id": "mbis.inspection.drainage",
             "applicability_state": "applicable", "verdict": "fail",
             "rule_ids": ["rc.a", "rc.b", "rc.c"]},
        ],
    )
    obs = [make_obligation("O1", source_family_id="mbis.inspection.drainage.ri.coverage")]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_coverage_metrics(av, obs, ["rc.a", "rc.b", "rc.x"], truth)
    # overlap {rc.a, rc.b} / W2 {rc.a,rc.b,rc.c} = 2/3。
    assert abs(m.rule_card_recall_proxy - 2 / 3) < 1e-9


def test_slot_requirement_recall():
    """slot_requirement_recall：W2 required_slots 被 agent obligations slot 覆盖。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": ["slot.a", "slot.b", "slot.c", "slot.d"],
            }
        ],
    )
    obs = [
        make_obligation("O1", slot_ids=["slot.a", "slot.b"]),
        make_obligation("O2", slot_ids=["slot.c"]),
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_coverage_metrics(av, obs, [], truth)
    # agent {a,b,c} / W2 {a,b,c,d} = 3/4。
    assert m.slot_requirement_recall == 0.75


def test_slot_requirement_recall_counts_threshold_measure_keys():
    """threshold 义务的 measure_keys 计入 slot 覆盖（口径修正 2026-06-11）。

    threshold 义务的 slot 身份记在 measure_keys（obligation_deriver 的
    evaluate_threshold 只写 measure_keys 不写 slot_ids）；分子需取
    slot_ids ∪ slot_ref_ids ∪ measure_keys，否则 measurement 类真值 slot
    结构性必丢。依据：杂物箱/slot_recall_drilldown.md 修1。
    """
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": ["slot.a", "ratio.x", "stress.y", "slot.miss"],
            }
        ],
    )
    obs = [
        # 普通义务：slot_ids 通道。
        make_obligation("O1", slot_ids=["slot.a"]),
        # threshold 义务：身份只在 measure_keys，slot_ids 为空。
        make_obligation(
            "O2", kind="threshold", slot_ids=[],
            measure_keys=["ratio.x", "stress.y"],
            operator=">", threshold_value_json="0.8",
            observed_value_json="1.07", comparator_result=True,
        ),
    ]
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_coverage_metrics(av, obs, [], truth)
    # agent {slot.a} ∪ {ratio.x, stress.y} / W2 4 个 = 3/4。
    assert m.slot_requirement_recall == 0.75


# ---------------------------------------------------------------------------
# §8.4.3 threshold metrics
# ---------------------------------------------------------------------------


def test_threshold_metrics_full_match():
    """threshold operator/value/observed/pass_bool 全对齐时各指标=1。"""
    truth = make_truth_bundle(
        projections_rows=[{
            "world_id": "WB-T", "fragment_id": "FRG-T-0", "projection_id": "NP-1",
            "projection_family": "mbis.inspection.drainage",
            "selected_family": "mbis.inspection.drainage", "expected_verdict": "pass",
            "severity_band": "minor", "required_slots": [],
        }],
        threshold_rows=[
            {
                "projection_id": "NP-1", "family_id": "mbis.inspection.drainage",
                "rule_id": "rc.thr.c01", "slot_id": "ratio.x", "operator": ">",
                "threshold_value_json": "0.8", "observed_value_json": "1.07",
                "regime_tag": "far_above", "pass_bool": True,
            }
        ],
    )
    obs = [
        make_obligation(
            "O1",
            kind="threshold",
            source_rule_card_id="rc.thr.c01",
            slot_ids=["ratio.x"],
            operator=">",
            threshold_value_json="0.8",
            observed_value_json="1.07",
            comparator_result=True,
        )
    ]
    m = compute_threshold_metrics(obs, truth, {"O1": "regime.default"})
    assert m.compared_pairs == 1
    assert m.threshold_operator_match == 1.0
    assert m.threshold_value_match == 1.0
    assert m.observed_value_tolerance_match == 1.0
    assert m.threshold_pass_bool_match == 1.0


def test_threshold_regime_join_is_order_independent_and_instance_aware():
    """同卡同 measure 的两个制度分别命中，且真值行序不影响结果。"""
    projections = [
        {"world_id": "WB-T", "fragment_id": "F1", "projection_id": "P1",
         "projection_family": "f", "selected_family": "f", "expected_verdict": "pass",
         "severity_band": "minor", "required_slots": []},
        {"world_id": "WB-T", "fragment_id": "F2", "projection_id": "P2",
         "projection_family": "f", "selected_family": "f", "expected_verdict": "fail",
         "severity_band": "minor", "required_slots": []},
    ]
    rows = [
        {"projection_id": "P1", "family_id": "f", "rule_id": "rc.same",
         "threshold_regime_id": "rc.same.t01", "slot_id": "duration.interval",
         "operator": "<=", "threshold_value_json": "14", "observed_value_json": "10",
         "regime_tag": "t01", "pass_bool": True},
        {"projection_id": "P2", "family_id": "f", "rule_id": "rc.same",
         "threshold_regime_id": "rc.same.t02", "slot_id": "duration.interval",
         "operator": "<=", "threshold_value_json": "7", "observed_value_json": "8",
         "regime_tag": "t02", "pass_bool": False},
    ]
    obs = [
        make_obligation("O1", fragment_id="F1", kind="threshold",
                        source_rule_card_id="rc.same", measure_keys=["duration.interval"],
                        operator="<=", threshold_value_json="14", observed_value_json="10",
                        comparator_result=True),
        make_obligation("O2", fragment_id="F2", kind="threshold",
                        source_rule_card_id="rc.same", measure_keys=["duration.interval"],
                        operator="<=", threshold_value_json="7", observed_value_json="8",
                        comparator_result=False),
    ]
    regime_map = {"O1": "rc.same.t01", "O2": "rc.same.t02"}

    first = compute_threshold_metrics(
        obs, make_truth_bundle(projections_rows=projections, threshold_rows=rows), regime_map
    )
    reversed_result = compute_threshold_metrics(
        obs, make_truth_bundle(projections_rows=projections, threshold_rows=list(reversed(rows))),
        regime_map,
    )

    assert first.as_dict() == reversed_result.as_dict()
    assert first.threshold_value_hits == first.threshold_value_compared == 2
    assert first.threshold_operator_hits == first.threshold_operator_compared == 2
    assert first.threshold_pass_bool_hits == first.threshold_pass_bool_compared == 2
    assert first.observed_value_hits == first.observed_value_compared == 2


def test_threshold_duplicate_regime_key_conflict_hard_fails():
    """同完整键的静态阈值签名不一致时禁止静默覆盖。"""
    rows = [
        {"projection_id": "P1", "family_id": "f", "rule_id": "rc.same",
         "threshold_regime_id": "rc.same.t01", "slot_id": "duration.interval",
         "operator": "<=", "threshold_value_json": "14"},
        {"projection_id": "P2", "family_id": "f", "rule_id": "rc.same",
         "threshold_regime_id": "rc.same.t01", "slot_id": "duration.interval",
         "operator": "<=", "threshold_value_json": "7"},
    ]
    with pytest.raises(ValueError, match="conflicting threshold truth rows for regime"):
        compute_threshold_metrics([], make_truth_bundle(threshold_rows=rows), {})


def test_threshold_missing_regime_is_excluded_and_counted():
    """closure 无制度身份时不回退粗键，并上报 coverage 缺口。"""
    truth = make_truth_bundle(threshold_rows=[{
        "projection_id": "P1", "family_id": "f", "rule_id": "rc.same",
        "threshold_regime_id": "rc.same.t01", "slot_id": "duration.interval",
        "operator": "<=", "threshold_value_json": "14",
    }])
    obs = [make_obligation(
        "O1", kind="threshold", source_rule_card_id="rc.same",
        measure_keys=["duration.interval"], operator="<=", threshold_value_json="14",
    )]

    result = compute_threshold_metrics(obs, truth, {})

    assert result.compared_pairs == 0
    assert result.threshold_value_compared == 0
    assert result.threshold_obligations == 1
    assert result.threshold_obligations_missing_regime == 1


def test_threshold_observed_value_numeric_tolerance():
    """observed_value_tolerance_match：数值近似（非字符串相等）也算命中。"""
    truth = make_truth_bundle(
        projections_rows=[{
            "world_id": "WB-T", "fragment_id": "FRG-T-0", "projection_id": "NP-1",
            "projection_family": "f", "selected_family": "f",
            "expected_verdict": "pass", "severity_band": "minor", "required_slots": [],
        }],
        threshold_rows=[
            {
                "projection_id": "NP-1", "family_id": "f", "rule_id": "rc.thr.c01",
                "slot_id": "ratio.x", "operator": ">", "threshold_value_json": "0.8",
                "observed_value_json": "1.0700000001", "regime_tag": "t",
                "pass_bool": True,
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", kind="threshold", source_rule_card_id="rc.thr.c01",
            slot_ids=["ratio.x"], operator=">", threshold_value_json="0.8",
            observed_value_json="1.07", comparator_result=True,
        )
    ]
    m = compute_threshold_metrics(obs, truth, {"O1": "regime.default"})
    # 1.07 vs 1.0700000001 在默认 rel_tol 内 → 命中。
    assert m.observed_value_tolerance_match == 1.0


def test_threshold_operator_mismatch():
    """operator 不一致 → threshold_operator_match=0。"""
    truth = make_truth_bundle(
        threshold_rows=[
            {
                "projection_id": "NP-1", "family_id": "f", "rule_id": "rc.thr.c01",
                "slot_id": "ratio.x", "operator": ">=", "threshold_value_json": "0.8",
                "observed_value_json": "1.07", "regime_tag": "t", "pass_bool": True,
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", kind="threshold", source_rule_card_id="rc.thr.c01",
            slot_ids=["ratio.x"], operator=">", threshold_value_json="0.8",
            observed_value_json="1.07", comparator_result=True,
        )
    ]
    m = compute_threshold_metrics(obs, truth, {"O1": "regime.default"})
    assert m.threshold_operator_match == 0.0


def test_threshold_non_threshold_obligation_ignored():
    """非 threshold kind 的义务不参与 threshold metrics。"""
    truth = make_truth_bundle(
        threshold_rows=[
            {
                "projection_id": "NP-1", "family_id": "f", "rule_id": "rc.thr.c01",
                "slot_id": "ratio.x", "operator": ">", "threshold_value_json": "0.8",
                "observed_value_json": "1.07", "regime_tag": "t", "pass_bool": True,
            }
        ],
    )
    obs = [make_obligation("O1", kind="evidence", slot_ids=["ratio.x"])]
    m = compute_threshold_metrics(obs, truth)
    assert m.compared_pairs == 0
    assert m.threshold_operator_match is None


# ---------------------------------------------------------------------------
# §8.4.4 closure metrics
# ---------------------------------------------------------------------------


def test_closure_allow_stop_precision_recall_when_evaluable():
    """allow_stop precision/recall：W2 可评估 + agent allow_stop=true 无 open/blocked。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, allow_stop=True)
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_closure_metrics(closure, av, truth)
    assert m.allow_stop_precision == 1.0
    assert m.allow_stop_recall == 1.0


def test_closure_allow_stop_recall_zero_when_not_stopped():
    """W2 可评估但 agent allow_stop=false → allow_stop_recall=0。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="open", satisfaction_status="unknown",
            open_reason_code="missing_fact",
        )
    ]
    closure = make_closure_result(obs)  # 有 open → allow_stop 自动 False
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_closure_metrics(closure, av, truth)
    assert closure.allow_stop is False
    assert m.allow_stop_recall == 0.0
    # 本 run 没触发 allow_stop → precision 不计。
    assert m.allow_stop_precision is None


def test_closure_closed_violated_detection_rate():
    """closed_violated_detection_rate：W2 fail 中 agent 判 fail 的比例。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, allow_stop=True)
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_closure_metrics(closure, av, truth)
    assert m.closed_violated_detection_rate == 1.0


def test_closure_blocked_rate_by_reason():
    """blocked_rate_by_reason：blocked reason 占总义务比例。"""
    obs = [
        make_obligation("O1", closure_status="closed", satisfaction_status="satisfied"),
        make_obligation(
            "O2", closure_status="blocked", satisfaction_status="unknown",
            blocked_reason_code="internal_error",
        ),
    ]
    closure = make_closure_result(obs)
    truth = make_truth_bundle()
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_closure_metrics(closure, av, truth)
    # 1 个 internal_error / 2 个义务 = 0.5。
    assert m.blocked_rate_by_reason.get("internal_error") == 0.5


def test_closure_open_when_reference_unknown_rate():
    """open_when_reference_unknown_rate：W2 unknown 时 agent 也 unknown 的比例。"""
    truth = make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "unknown", "severity_band": "minor",
                "required_slots": [],
            }
        ],
    )
    obs = [
        make_obligation(
            "O1", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="open", satisfaction_status="unknown",
            open_reason_code="missing_fact",
        )
    ]
    closure = make_closure_result(obs)
    av = aggregate_agent_family_verdicts(obs, _CW)
    m = compute_closure_metrics(closure, av, truth)
    # W2 unknown 1 个，agent 同 family 判 unknown → 1/1。
    assert m.open_when_reference_unknown_rate == 1.0
