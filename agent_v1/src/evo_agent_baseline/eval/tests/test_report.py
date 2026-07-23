"""report.py 单测（spec §8.5）。

验证 evaluate_run 串起 truth_loader/mapper/metrics/leakage 后的 §8.5 输出 JSON，
重点覆盖：正常评测、leakage 作废、crosswalk 缺失 blocked 三条路径。
"""

from __future__ import annotations

import json

from evo_agent_baseline.eval.report import (
    EvalInputs,
    evaluate_run,
    make_eval_run_id,
    write_eval_report,
)
from evo_agent_baseline.eval.tests._fixtures import (
    make_closure_result,
    make_obligation,
    make_truth_bundle,
)


def _basic_truth():
    """一个含单条 fail projection 的 W2 真值 fixture。"""
    return make_truth_bundle(
        projections_rows=[
            {
                "world_id": "WB-T", "fragment_id": "F1", "projection_id": "NP-1",
                "projection_family": "mbis.inspection.drainage",
                "selected_family": "mbis.inspection.drainage",
                "expected_verdict": "fail", "severity_band": "severe",
                "required_slots": ["slot.a"],
            }
        ],
        matched_families_rows=[
            {"projection_id": "NP-1", "family_id": "mbis.inspection.drainage",
             "applicability_state": "applicable", "verdict": "fail",
             "rule_ids": ["rc.x"]},
        ],
        basis_rows=[
            {"projection_id": "NP-1", "basis_kind": "threshold_compare",
             "basis_id": "BI-NP1-0001", "family_id": "mbis.inspection.drainage",
             "rule_id": "rc.x"},
        ],
    )


def test_make_eval_run_id_format():
    """eval_run_id 形如 EVAL-<ts>-<hash>。"""
    rid = make_eval_run_id("CAR-abc")
    assert rid.startswith("EVAL-")
    parts = rid.split("-")
    assert len(parts) == 3
    assert len(parts[2]) == 8


def test_evaluate_run_completed_path():
    """正常评测：valid=True，evaluation_status=completed，含 §8.5 各字段。"""
    obs = [
        make_obligation(
            "O1", world_id="WB-T", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, world_id="WB-T", allow_stop=True)
    inputs = EvalInputs(
        agent_run_id="CAR-T",
        world_id="WB-T",
        building_id="BLD-T",
        closure_result=closure,
        truth=_basic_truth(),
        retrieved_rule_card_ids=["rc.x"],
        run_audit={"forbidden_source_check_passed": True},
        report_text="本楼宇排水构件存在缺陷，建议跟进维修。",
    )
    report = evaluate_run(inputs)
    assert report["evaluation_status"] == "completed"
    assert report["valid"] is True
    assert report["invalid_reasons"] == []
    # §8.5 必备字段。
    for key in (
        "eval_run_id", "agent_run_id", "world_id", "building_id",
        "metrics", "per_fragment_results", "leakage_audit",
    ):
        assert key in report, f"输出缺字段 {key}"
    # metrics 含 §8.4 各类指标键。
    for mk in (
        "expected_verdict_accuracy", "family_recall",
        "threshold_pass_bool_match", "allow_stop_precision",
    ):
        assert mk in report["metrics"]
    # agent 判 fail，W2 fail → exact accuracy=1。
    assert report["metrics"]["expected_verdict_accuracy"] == 1.0
    # per_fragment_results 有 1 条且 verdict_match=True。
    assert len(report["per_fragment_results"]) == 1
    assert report["per_fragment_results"][0]["verdict_match"] is True


def test_evaluate_run_invalid_on_leakage():
    """leakage 检出 → valid=False，invalid_reasons 含 invalid_due_to_answer_leakage。"""
    obs = [
        make_obligation(
            "O1", world_id="WB-T", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, world_id="WB-T", allow_stop=True)
    inputs = EvalInputs(
        agent_run_id="CAR-T",
        world_id="WB-T",
        building_id="BLD-T",
        closure_result=closure,
        truth=_basic_truth(),
        retrieved_rule_card_ids=["rc.x"],
        # 报告直接泄漏 expected_verdict 字段名。
        report_text="根据 expected_verdict 判定不合格。",
    )
    report = evaluate_run(inputs)
    assert report["valid"] is False
    assert "invalid_due_to_answer_leakage" in report["invalid_reasons"]
    assert report["leakage_audit"]["expected_verdict_text_leak"] is True


def test_evaluate_run_invalid_on_known_basis_id_leak():
    """报告引用 W2 真值里的 basis_id → 检出 basis_item_id_leak 并作废。"""
    obs = [
        make_obligation(
            "O1", world_id="WB-T", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, world_id="WB-T", allow_stop=True)
    inputs = EvalInputs(
        agent_run_id="CAR-T",
        world_id="WB-T",
        building_id="BLD-T",
        closure_result=closure,
        truth=_basic_truth(),  # basis_items 含 BI-NP1-0001
        retrieved_rule_card_ids=["rc.x"],
        report_text="结论参考了 BI-NP1-0001。",
    )
    report = evaluate_run(inputs)
    assert report["valid"] is False
    assert report["leakage_audit"]["basis_item_id_leak"] is True


def test_evaluate_run_blocked_missing_crosswalk(tmp_path):
    """crosswalk 缺失 → evaluation_status=blocked_missing_crosswalk，仍出 leakage_audit。"""
    obs = [
        make_obligation(
            "O1", world_id="WB-T", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
        )
    ]
    closure = make_closure_result(obs, world_id="WB-T")
    inputs = EvalInputs(
        agent_run_id="CAR-T",
        world_id="WB-T",
        building_id="BLD-T",
        closure_result=closure,
        truth=_basic_truth(),
        retrieved_rule_card_ids=[],
        report_text="正常报告文本。",
    )
    # 指向不存在的 crosswalk 路径。
    missing = str(tmp_path / "no_crosswalk.json")
    report = evaluate_run(inputs, crosswalk_path=missing)
    assert report["evaluation_status"] == "blocked_missing_crosswalk"
    assert report["metrics"] == {}
    assert "leakage_audit" in report  # leakage 审计不依赖 crosswalk
    # 无泄漏时 blocked 路径下 valid 仍可为 True（agent run 不受影响）。
    assert report["valid"] is True


def test_write_eval_report_roundtrip(tmp_path):
    """write_eval_report 落盘后可被 json.load 还原。"""
    obs = [
        make_obligation(
            "O1", world_id="WB-T", fragment_id="F1",
            source_family_id="mbis.inspection.drainage.ri.coverage",
            closure_status="closed", satisfaction_status="violated",
        )
    ]
    closure = make_closure_result(obs, world_id="WB-T", allow_stop=True)
    inputs = EvalInputs(
        agent_run_id="CAR-T",
        world_id="WB-T",
        building_id="BLD-T",
        closure_result=closure,
        truth=_basic_truth(),
        retrieved_rule_card_ids=["rc.x"],
        report_text="正常报告。",
    )
    report = evaluate_run(inputs)
    out = tmp_path / "eval_report.json"
    write_eval_report(report, str(out))
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["eval_run_id"] == report["eval_run_id"]
    assert loaded["metrics"] == report["metrics"]
