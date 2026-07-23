"""baseline 批跑驱动纯逻辑与聚合器单测。"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import aggregate_baseline_batch as aggregate_module  # noqa: E402
import run_baseline_batch as batch_module  # noqa: E402
from aggregate_baseline_batch import (  # noqa: E402
    add_completion,
    aggregate_batch,
    aggregate_reports,
    render_markdown,
)
from run_baseline_batch import (  # noqa: E402
    anchor_mismatches,
    build_command,
    check_pool_health,
    child_environment,
    classify_run,
    queue_verdict_distribution,
    require_isolated_database,
    run_profile,
    select_buildings,
    should_skip,
    verdict_distribution,
)


def test_database_guard_has_no_main_database_bypass():
    with pytest.raises(ValueError):
        require_isolated_database(None)
    with pytest.raises(ValueError):
        require_isolated_database("neo4j")
    assert require_isolated_database("exp_008_isolated") == "exp_008_isolated"


def test_building_selection_sorted_count_and_explicit_order():
    available = ["BLD-03", "BLD-01", "BLD-02", "BLD-02"]
    assert select_buildings(available, 2) == ["BLD-01", "BLD-02"]
    assert select_buildings(available, 30, ["BLD-03,BLD-01"]) == ["BLD-03", "BLD-01"]
    with pytest.raises(ValueError):
        select_buildings(available, 30, ["BLD-99"])


def test_health_gate_and_full_distribution():
    distribution = verdict_distribution(["pass", "fail", "unknown", "pass", None])
    assert distribution == {"<missing>": 1, "fail": 1, "pass": 2, "unknown": 1}
    assert check_pool_health({"pass": 3, "fail": 7}) == (True, 0.3)
    assert check_pool_health({"pass": 1, "fail": 9}) == (False, 0.1)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "baseline_batch"


@pytest.fixture
def work_path():
    root = Path(__file__).parent / ".baseline_batch_test_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        resolved = path.resolve()
        if resolved.parent == root.resolve():
            shutil.rmtree(resolved)
        try:
            root.rmdir()
        except OSError:
            pass


def test_resume_skip_requires_completed_and_eval_report():
    output = FIXTURE_ROOT / "B1"
    latest = {"BLD-01": {"status": "completed"}}
    assert not should_skip("BLD-01", latest, FIXTURE_ROOT / "missing")
    latest = {"B1": {"status": "completed"}}
    assert should_skip("B1", latest, output)
    latest["B1"]["status"] = "failed"
    assert not should_skip("B1", latest, output)


def test_anchor_validation_covers_commit_pool_cohort_and_database():
    base = {"git_commit": "a", "worldgen_run_dir": "C:/pool", "building_ids": ["B1"],
            "environment": {"neo4j_database": "exp_a"}}
    assert anchor_mismatches(base, dict(base)) == []
    changed = {**base, "git_commit": "b", "worldgen_run_dir": "C:/other",
               "building_ids": ["B2"],
               "environment": {"neo4j_database": "exp_b"}}
    assert anchor_mismatches(base, changed) == [
        "worldgen_run_dir", "git_commit", "building_ids", "neo4j_database"]


def test_build_command_wipe_then_skip_ingest_policy(work_path):
    wipe = build_command("B1", work_path / "pool", work_path / "out", False, True)
    skip = build_command("B2", work_path / "pool", work_path / "out2", True, False)
    assert "--wipe" in wipe and "--skip-ingest" not in wipe and "--llm" not in wipe
    assert "--skip-ingest" in skip and "--wipe" not in skip and "--llm" in skip


def test_llm_tool_call_zero_or_missing_fails_and_is_not_skipped(work_path):
    for name, audit, expected_reason in (
        ("zero", {"llm_tool_call_count": 0}, "tool_call_zero"),
        ("missing", {"llm_turns": [{"tool_call_count": 1}]}, "tool_call_missing"),
    ):
        output = work_path / name
        (output / "runs" / "R1").mkdir(parents=True)
        (output / "eval_report.json").write_text("{}", encoding="utf-8")
        (output / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        status, reason = classify_run(0, True, True, output)
        assert (status, reason) == ("failed", expected_reason)
        assert not should_skip(name, {name: {"status": status, "reason": reason}}, output)


def test_floor_run_does_not_apply_tool_call_gate(work_path):
    output = work_path / "floor"
    output.mkdir()
    assert classify_run(0, True, False, output) == ("completed", None)


@pytest.mark.parametrize(("audit", "expected_reason"), [
    ({"llm_tool_call_count": 0}, "tool_call_zero"),
    ({"llm_turns": [{"tool_call_count": 1}]}, "tool_call_missing"),
])
def test_llm_main_writes_tool_call_failure_reason(
        work_path, monkeypatch, audit, expected_reason):
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _path: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")

    def fake_run(command, **_kwargs):
        if "--output-dir" not in command:
            # 消费者门(A/B)子进程调用(2026-07-23 正式入口自动跑门):桩过
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 0, "failed_count": 1}})

    result = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm",
    ])

    row = json.loads((batch_root / "progress.jsonl").read_text(encoding="utf-8"))
    assert result == 1
    assert row["status"] == "failed"
    assert row["reason"] == expected_reason


def test_queue_health_uses_only_selected_worlds():
    building_worlds = {"B1": "W1", "B2": "W2"}
    world_verdicts = {
        "W1": ["pass"] + ["fail"] * 9,
        "W2": ["pass"] * 5 + ["fail"] * 5,
    }
    full = verdict_distribution(v for values in world_verdicts.values() for v in values)
    queue = queue_verdict_distribution(["B1"], building_worlds, world_verdicts)
    assert full == {"fail": 14, "pass": 6}
    assert queue == {"fail": 9, "pass": 1}
    assert check_pool_health(full) == (True, 0.3)
    assert check_pool_health(queue) == (False, 0.1)


def test_run_profile_marks_floor_and_full_llm():
    """档位×契约矩阵(2026-07-23 codex 收官商议第 1 步):满血+v4=收官形态可验收;
    满血+v3=历史兼容/对照形态不具收官资格;地板档不变。"""
    floor = run_profile(False, None)
    full_v4 = run_profile(True, "v4")
    full_v3 = run_profile(True, "v3")
    assert floor["kind"] == "deterministic_floor"
    assert floor["baseline_acceptance_eligible"] is False
    assert "不得用于五道门验收" in floor["warning"]
    assert full_v4["kind"] == "full_llm"
    assert full_v4["report_contract"] == "v4"
    assert full_v4["baseline_acceptance_eligible"] is True
    assert full_v3["kind"] == "full_llm_v3_legacy"
    assert full_v3["baseline_acceptance_eligible"] is False
    assert "不具收官资格" in full_v3["warning"]


def test_child_environment_pins_report_contract():
    """契约由驱动显式下发:满血批写死 EVO_REPORT_CONTRACT,地板批清除环境残留。"""
    import os
    os.environ["EVO_REPORT_CONTRACT"] = "v3"  # 模拟外壳残留
    try:
        env_v4 = child_environment("v4")
        assert env_v4["EVO_REPORT_CONTRACT"] == "v4"
        env_floor = child_environment(None)
        assert "EVO_REPORT_CONTRACT" not in env_floor
    finally:
        os.environ.pop("EVO_REPORT_CONTRACT", None)


def test_anchor_mismatch_covers_contract_and_pool_hash():
    """续跑劈锚检查覆盖契约与池内容哈希(2026-07-23 codex 收官商议第 2 步)。"""
    base = {"worldgen_run_dir": "p", "git_commit": "c", "building_ids": ["B1"],
            "pool_content_sha256": "h1",
            "environment": {"neo4j_database": "db", "report_contract": "v4"}}
    other = json.loads(json.dumps(base))
    other["pool_content_sha256"] = "h2"
    other["environment"]["report_contract"] = "v3"
    assert anchor_mismatches(base, base) == []
    got = anchor_mismatches(base, other)
    assert "pool_content_sha256" in got and "report_contract" in got


def test_aggregate_uses_pair_denominators_and_rolls_up_audits(work_path):
    report_dirs = []
    for building_id, hits, compared in (("B1", 1, 2), ("B2", 6, 6)):
        report = json.loads(
            (FIXTURE_ROOT / building_id / "eval_report.json").read_text(encoding="utf-8")
        )
        metrics = report["metrics"]
        for prefix, metric_hits in (
            ("threshold_value", hits),
            ("threshold_pass_bool", hits),
            ("threshold_operator", compared),
        ):
            metrics[f"{prefix}_hits"] = metric_hits
            metrics[f"{prefix}_compared"] = compared
        target = work_path / building_id
        shutil.copytree(FIXTURE_ROOT / building_id, target)
        (target / "eval_report.json").write_text(json.dumps(report), encoding="utf-8")
        report_dirs.append(target)
    summary = aggregate_reports(report_dirs)

    threshold = summary["threshold_subset"]
    assert threshold["threshold_compared_pairs"] == 8
    assert threshold["value_match"] == pytest.approx(0.875)
    assert threshold["pass_bool_match"] == pytest.approx(0.875)
    assert threshold["operator_match"] == 1.0

    n1 = summary["coarse_family_n1"]
    assert n1["compared_pairs"] == 8
    assert n1["unknown_to_fail"] == 2
    assert n1["unknown_to_pass"] == 1
    assert summary["verifiable_subuniverse"]["fragment_level"][
        "expected_verdict_accuracy"] == pytest.approx(0.875)

    ledger = summary["obligation_ledger"]
    assert ledger["closed_ratio"] == 0.4
    assert ledger["open_reason_counts"] == {"missing_observation": 10}
    assert ledger["blocked_reason_counts"] == {"missing_rule_edge": 2}

    llm = summary["llm_audit"]
    assert llm["tool_call_count"] == {"min": 0, "median": 1.5, "max": 3}
    assert llm["tool_call_zero_buildings"] == ["B2"]
    assert llm["llm_forced_finalize_buildings"] == ["B2"]
    assert summary["leakage_audit"]["any_leakage_buildings"] == ["B2"]

    summary["completion"] = {"completed_count": 1, "planned_count": 2,
                             "failed_buildings": ["B2"]}
    markdown = render_markdown(summary)
    assert "公式" in markdown
    assert "reason_code" in markdown


def test_aggregate_does_not_fall_back_to_nested_tool_counts(work_path):
    output = work_path / "B-NESTED"
    (output / "runs" / "R1").mkdir(parents=True)
    (output / "eval_report.json").write_text(json.dumps({
        "building_id": "B-NESTED", "metrics": {},
        "leakage_audit": {}, "leakage_findings": [],
    }), encoding="utf-8")
    (output / "runs" / "R1" / "run_audit.json").write_text(json.dumps({
        "llm_turns": [{"tool_call_count": 1},
                      {"tool_call_count": 1, "llm_forced_finalize": True}],
        "status_trace": ["created", "report_ready"],
    }), encoding="utf-8")

    llm = aggregate_reports([output])["llm_audit"]
    assert llm["tool_call_count"] == {"min": None, "median": None, "max": None}
    assert llm["tool_call_missing_buildings"] == ["B-NESTED"]
    assert llm["llm_forced_finalize_buildings"] == []


def test_add_completion_uses_manifest_and_latest_progress(work_path):
    (work_path / "batch_manifest.json").write_text(json.dumps({
        "building_ids": ["B1", "B2", "B3"]}), encoding="utf-8")
    (work_path / "progress.jsonl").write_text("\n".join(json.dumps(row) for row in (
        {"building_id": "B1", "status": "failed"},
        {"building_id": "B1", "status": "completed"},
        {"building_id": "B2", "status": "completed"},
    )), encoding="utf-8")
    (work_path / "buildings" / "B1").mkdir(parents=True)
    (work_path / "buildings" / "B1" / "eval_report.json").write_text(
        "{}", encoding="utf-8")
    summary = {"building_ids": ["IGNORED"]}

    add_completion(summary, work_path)

    assert summary["completion"] == {
        "planned_count": 3,
        "completed_count": 1,
        "failed_count": 2,
        "completed_buildings": ["B1"],
        "failed_buildings": ["B2", "B3"],
    }


def test_aggregate_batch_excludes_failed_run_from_metrics(work_path):
    batch_root = work_path / "batch"
    buildings = batch_root / "buildings"
    for building_id, tool_calls, value_match, confusion in (
        ("GOOD", 5, 1.0, {"pass->pass": 100}),
        ("VACUOUS", 0, 0.0, {"unknown->fail": 100}),
    ):
        output = buildings / building_id
        run_dir = output / "runs" / "R1"
        run_dir.mkdir(parents=True)
        (output / "eval_report.json").write_text(json.dumps({
            "building_id": building_id,
            "metrics": {
                "threshold_compared_pairs": 100,
                "threshold_value_match": value_match,
                "threshold_value_hits": int(value_match * 100),
                "threshold_value_compared": 100,
                "threshold_pass_bool_match": value_match,
                "threshold_pass_bool_hits": int(value_match * 100),
                "threshold_pass_bool_compared": 100,
                "threshold_operator_match": value_match,
                "threshold_operator_hits": int(value_match * 100),
                "threshold_operator_compared": 100,
                "confusion": confusion,
            },
            "leakage_audit": {},
            "leakage_findings": [],
        }), encoding="utf-8")
        (run_dir / "run_audit.json").write_text(json.dumps({
            "llm_tool_call_count": tool_calls,
            "status_trace": ["created", "report_ready"],
        }), encoding="utf-8")

    (batch_root / "batch_manifest.json").write_text(json.dumps({
        "building_ids": ["GOOD", "VACUOUS"],
    }), encoding="utf-8")
    (batch_root / "progress.jsonl").write_text("\n".join((
        json.dumps({"building_id": "GOOD", "status": "completed"}),
        json.dumps({"building_id": "VACUOUS", "status": "failed",
                    "reason": "tool_call_zero"}),
    )) + "\n", encoding="utf-8")

    summary = aggregate_batch(batch_root)

    threshold = summary["threshold_subset"]
    assert threshold["threshold_compared_pairs"] == 100
    assert threshold["value_match"] == 1.0
    assert "unknown->fail" not in summary["coarse_family_n1"]["confusion"]
    assert summary["excluded_from_metrics"] == [{
        "building_id": "VACUOUS",
        "status": "failed",
        "reason": "tool_call_zero",
    }]
    markdown = (batch_root / "batch_summary.md").read_text(encoding="utf-8")
    assert "分母只包含状态为 completed" in markdown
    assert "VACUOUS：status=failed；reason=tool_call_zero" in markdown


def test_force_anchor_mismatch_migrates_only_when_no_progress(
        work_path, monkeypatch, capsys):
    """--force 越锚只许**空进度原地迁移**(旧 manifest 备份 superseded 后重写);
    已有进度的场景由 test_force_with_existing_progress_refuses_anchor_change
    锁定为拒绝(codex 审阻断#2:原测试固化"复用 completed+重写 manifest"危险行为)。"""
    batch_root = work_path / "batch"
    (batch_root / "buildings").mkdir(parents=True)  # 无 progress.jsonl=空进度
    old_manifest = {
        "worldgen_run_dir": str((work_path / "pool").resolve()),
        "git_commit": "old-commit",
        "building_ids": ["B1"],
        "environment": {"neo4j_database": "old_database"},
    }
    old_text = json.dumps(old_manifest, ensure_ascii=False, indent=2) + "\n"
    manifest_path = batch_root / "batch_manifest.json"
    manifest_path.write_text(old_text, encoding="utf-8")
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "new_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _path: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "new-commit")
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    def fake_run(command, **_kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    result = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--force",
    ])

    assert result == 0
    backups = list(batch_root.glob("batch_manifest.superseded_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == old_text
    rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rewritten["git_commit"] == "new-commit"
    assert rewritten["environment"]["neo4j_database"] == "new_database"
    assert rewritten["pool_health"]["queue"] == {
        "expected_verdict_distribution": {"fail": 7, "pass": 3},
        "pass_ratio": 0.3,
    }
    assert rewritten["pool_health"]["gate_basis"] == "queue"
    assert rewritten["run_profile"]["kind"] == "deterministic_floor"
    assert "非基线本体，不得用于五道门验收" in capsys.readouterr().out


def test_aggregate_sums_each_metric_real_denominator_with_none_metric(work_path):
    """逐指标直接累加 hits/compared；比例 None 不得触发统一分母推算。"""
    b3 = work_path / "B3"
    b3.mkdir()
    (b3 / "eval_report.json").write_text(json.dumps({
        "building_id": "B3",
        "metrics": {
            "threshold_compared_pairs": 100,
            "threshold_value_match": None,
            "threshold_pass_bool_match": None,
            "threshold_operator_match": 0.5,
            "threshold_value_hits": 0,
            "threshold_value_compared": 0,
            "threshold_pass_bool_hits": 0,
            "threshold_pass_bool_compared": 0,
            "threshold_operator_hits": 50,
            "threshold_operator_compared": 100,
            "confusion": {},
        },
        "leakage_audit": {},
        "leakage_findings": [],
    }, ensure_ascii=False), encoding="utf-8")

    b1_report = json.loads(
        (FIXTURE_ROOT / "B1" / "eval_report.json").read_text(encoding="utf-8")
    )
    b1_report["metrics"].update({
        "threshold_value_hits": 1, "threshold_value_compared": 2,
        "threshold_pass_bool_hits": 1, "threshold_pass_bool_compared": 2,
        "threshold_operator_hits": 2, "threshold_operator_compared": 2,
    })
    b1 = work_path / "B1"
    b1.mkdir()
    (b1 / "eval_report.json").write_text(json.dumps(b1_report), encoding="utf-8")
    summary = aggregate_reports([b1, b3])
    threshold = summary["threshold_subset"]
    # 总配对数保留兼容口径；三个指标只按自己的真实分母累加。
    assert threshold["threshold_compared_pairs"] == 102
    assert threshold["metric_pair_denominators"] == {
        "value_match": 2, "pass_bool_match": 2, "operator_match": 102}
    assert threshold["value_match"] == pytest.approx(0.5)
    assert threshold["pass_bool_match"] == pytest.approx(0.5)
    assert threshold["operator_match"] == pytest.approx((1.0 * 2 + 0.5 * 100) / 102)


def test_pool_content_sha256_framing_distinguishes_path_content_split(work_path):
    """长度前缀框架:文件 a+内容 bc 与文件 ab+内容 c 必须不同哈希(codex 审边界坑)。"""
    d1 = work_path / "p1"
    d2 = work_path / "p2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a").write_bytes(b"bc")
    (d2 / "ab").write_bytes(b"c")
    assert (batch_module.pool_content_sha256(d1)
            != batch_module.pool_content_sha256(d2))


def test_anchor_mismatch_covers_model_and_digest():
    """模型锚参与劈锚比较(codex 审阻断#1:落清单不比较=续跑换模型静默混批)。"""
    base = {"worldgen_run_dir": "p", "git_commit": "c", "building_ids": ["B1"],
            "pool_content_sha256": "h",
            "environment": {"neo4j_database": "db", "report_contract": "v4",
                            "llm_model_resolved": "m1", "llm_model_digest": "d1"}}
    other = json.loads(json.dumps(base))
    other["environment"]["llm_model_resolved"] = "m2"
    other["environment"]["llm_model_digest"] = "d2"
    got = anchor_mismatches(base, other)
    assert "llm_model_resolved" in got and "llm_model_digest" in got


def test_force_with_existing_progress_refuses_anchor_change(
        work_path, monkeypatch, capsys):
    """--force 只许空进度原地迁移:已有进度时锚变必须拒绝(codex 审阻断#2:
    复用旧锚 completed 再重写 manifest = 伪造统一锚)。"""
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit-new")
    (batch_root / "buildings").mkdir(parents=True)
    (batch_root / "batch_manifest.json").write_text(json.dumps({
        "worldgen_run_dir": str(work_path / "pool"), "git_commit": "commit-old",
        "building_ids": ["B1"], "pool_content_sha256": "old",
        "environment": {"neo4j_database": "test_database", "report_contract": "v3"},
    }), encoding="utf-8")
    (batch_root / "progress.jsonl").write_text(
        json.dumps({"building_id": "B1", "status": "completed"}) + "\n",
        encoding="utf-8")
    rc = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm", "--force",
    ])
    assert rc == 2
    assert "不得复用旧锚产物" in capsys.readouterr().err


def test_main_records_v4_default_and_fails_on_gate_failure(work_path, monkeypatch):
    """满血批缺省契约 v4 入清单/子环境;消费者门失败时批级非零退出且
    consumer_gates.json 落盘(codex 审测试覆盖缺口)。"""
    batch_root = work_path / "batch"
    monkeypatch.setenv("EVO_AGENT_NEO4J_DATABASE", "test_database")
    monkeypatch.setenv("EVO_AGENT_LLM_MODEL", "fake-model:test")
    monkeypatch.setattr(batch_module, "read_pool", lambda _p: (
        ["B1"], {"fail": 7, "pass": 3}, {"B1": "W1"},
        {"W1": ["pass"] * 3 + ["fail"] * 7}))
    monkeypatch.setattr(batch_module, "git_commit", lambda: "commit")
    monkeypatch.setattr(batch_module, "ollama_model_digest", lambda _m: "digest-x")
    calls = []

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            calls.append(Path(command[1]).name)  # 门脚本名
            return SimpleNamespace(returncode=1, stdout="gate out", stderr="gate err")
        env = kwargs.get("env") or {}
        assert env.get("EVO_REPORT_CONTRACT") == "v4"  # 契约显式下发
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "runs" / "R1").mkdir(parents=True)
        (output_dir / "eval_report.json").write_text("{}", encoding="utf-8")
        (output_dir / "runs" / "R1" / "run_audit.json").write_text(
            json.dumps({"llm_tool_call_count": 3}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)
    monkeypatch.setattr(aggregate_module, "aggregate_batch", lambda _root: {
        "completion": {"completed_count": 1, "failed_count": 0}})

    rc = batch_module.main([
        "--worldgen-run-dir", str(work_path / "pool"),
        "--batch-root", str(batch_root), "--llm",
    ])
    assert rc == 1  # 跑批全成但门失败 → 非零
    assert calls == ["check_report_usability.py", "check_report_authority.py"]
    manifest = json.loads(
        (batch_root / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["environment"]["report_contract"] == "v4"
    assert manifest["environment"]["llm_model_resolved"] == "fake-model:test"
    assert manifest["environment"]["llm_model_digest"] == "digest-x"
    assert manifest["params"]["report_contract"] == "v4"
    assert len(manifest["pool_content_sha256"]) == 64
    gates = json.loads(
        (batch_root / "consumer_gates.json").read_text(encoding="utf-8"))
    assert gates["usability_gate_a"]["exit_code"] == 1
    assert gates["authority_gate_b"]["exit_code"] == 1
    assert "gate out" in gates["usability_gate_a"]["output_tail"]
