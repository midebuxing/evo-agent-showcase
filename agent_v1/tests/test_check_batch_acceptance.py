"""批后验收编排的档位路由测试。"""
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

import check_batch_acceptance as acceptance_module  # noqa: E402


@pytest.fixture
def work_path():
    root = Path(__file__).parent / ".check_batch_acceptance_test_tmp"
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


def _write_manifest(root: Path, eligible=...):
    payload = {"schema_version": "1"}
    if eligible is not ...:
        payload["run_profile"] = {"baseline_acceptance_eligible": eligible}
    (root / "batch_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fake_usability_module(root: Path, *, rc: int, marker: str):
    report = root / "buildings" / "BLD-01" / "runs" / "RUN-01" / "report.md"
    namespace = SimpleNamespace()

    def analyze(path, thresholds):
        return {
            "main_lines": 154,
            "main_hashes": 0,
            "dup_rate": 0.144,
            "mix_rate": 1.0,
        }

    def main(argv):
        namespace.analyze(str(report), {"main_max": 180, "dup_max": 0.05})
        print(marker)
        return rc

    namespace.analyze = analyze
    namespace.main = main
    return namespace


def _route(work_path, monkeypatch, *, eligible, rc, marker="A 门原始输出"):
    _write_manifest(work_path, eligible)
    fake = _fake_usability_module(work_path, rc=rc, marker=marker)
    monkeypatch.setattr(
        acceptance_module, "_load",
        lambda name: fake if name == "check_report_usability" else None)
    lines = []
    hard_calls = []

    def hard(ok, name, detail):
        hard_calls.append((ok, name, detail))

    notice, diagnostics = acceptance_module._append_report_usability_gate(
        work_path, hard, lines, verbose=False)
    return notice, diagnostics, lines, hard_calls


def test_floor_profile_makes_a_not_applicable_but_keeps_four_diagnostics(
        work_path, monkeypatch):
    notice, diagnostics, lines, hard_calls = _route(
        work_path, monkeypatch, eligible=False, rc=1, marker="本来会判失败 ❌")

    assert notice is None
    assert hard_calls == []
    assert lines == [
        "  ⏭️ [不适用] A 门·报告可读性       "
        "不适用于基线收官（地板档,契约 "
        "`baseline_acceptance_eligible=false`）"
    ]
    rendered = "\n".join(diagnostics)
    assert "地板档可读性诊断（原始四项；仅报数，不判过/不过，不进硬项）" in rendered
    assert "BLD-01｜主视图行数 154｜主视图哈希 0｜重复率 14.4%｜混排率 100.0%" in rendered
    assert "❌" not in rendered
    assert "本来会判失败" not in rendered


def test_baseline_profile_still_judges_a_gate(work_path, monkeypatch):
    notice, diagnostics, lines, hard_calls = _route(
        work_path, monkeypatch, eligible=True, rc=1, marker="A 门失败原文")

    assert notice is None
    assert diagnostics == []
    assert hard_calls == [(False, "A 门·报告可读性", "失败（见下）")]
    assert any("A 门失败原文" in line for line in lines)


def test_missing_profile_field_warns_and_preserves_legacy_judgement(
        work_path, monkeypatch):
    notice, diagnostics, lines, hard_calls = _route(
        work_path, monkeypatch, eligible=..., rc=0)

    assert notice == (
        "⚠️ 批清单缺少 `run_profile.baseline_acceptance_eligible`；"
        "按老批兼容策略照常判 A 门。"
    )
    assert diagnostics == []
    assert lines == []
    assert hard_calls == [(True, "A 门·报告可读性", "通过")]


def _complete_delivery_for_payload():
    truth_doc = {
        "truth_file": str(acceptance_module.TRUTH_FILE),
        "truth_coverage_complete": True,
        "truth_item_count": 1,
        "truth_building_count": 1,
        "truth_chapter_count": 1,
        "card_quantifier_meaning": "any=条款级",
        # 分母三件套必须齐（2026-08-06 P4 门限契约）：召回分母、召回本身、挂起量。
        # 缺任一项都会被新的 fail-loud 判成证据未闭合——这正是它该做的事，
        # 故这个「完整交付」造具也必须造完整（旧版只有 covered/applicable 两项）。
        "truth_applicable_state_counts": {
            "applicable": 1, "not_applicable": 0, "pending": 0,
        },
        "overall": {
            "covered_count": 1,
            "applicable_item_count": 1,
            "applicable_item_recall": 1.0,
            "pending_item_count": 0,
        },
    }
    return {
        "A": {"eligible": False, "status": "not_applicable", "detail": None},
        "1": {"status": "passed", "planned": 1, "completed": 1,
              "failed": 0, "excluded": [], "detail": "通过"},
        "2": {"status": "passed", "exemption_count": 0, "detail": "通过"},
        "3": {"status": "passed", "keyset_equal_count": 1,
              "building_count": 1, "degradation_signal_count": 0,
              "degradation_signals": [], "detail": "通过"},
        "4": {"status": "passed", "in_scope": 0, "inventory_total": 8,
              "failed": 0, "passed": 0, "detail": "通过"},
        "5": {"status": "reported", "clause_level": truth_doc,
              "obligation_unit_level": truth_doc, "error": None},
        "6": {"status": "reported", "open_suspect_groups": 0,
              "total_suspect_groups": 0, "error": None},
        "7": {"status": "not_requested", "baseline_batch": None,
              "equal": None, "unequal": None, "error": None},
    }


def test_item_json_contract_has_all_required_evidence_fields():
    item = acceptance_module._item_record(
        "X", "测试项", hardness="hard", status="passed",
        numerator=1, denominator=1, formula="1 / 1",
        exclusions=[], quantifier_scope="全部测试项",
        truth_file={"path": "truth.jsonl", "sha256": "a" * 64},
        source_artifact_paths=["source.json"], detail=None,
    )

    assert set(item) == {
        "item_id", "name", "hardness", "status", "numerator",
        "denominator", "formula", "exclusions", "quantifier_scope",
        "truth_file", "source_artifact_paths", "detail",
    }


def test_missing_anchor_forces_citable_false(work_path, monkeypatch):
    (work_path / "batch_manifest.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        acceptance_module, "_truth_anchor",
        lambda *_a, **_kw: (None, ["truth_file"]),
    )
    monkeypatch.setattr(
        acceptance_module, "_collect_citation_anchors",
        lambda root, manifest, truth: (
            {"seed": None, "pool_content_sha256": "b" * 64,
             "git_commit": "c" * 40, "code_state_sha256": "d" * 64,
             "neo4j_database": "s25smoke", "llm_model_resolved": "model",
             "rulecard_pack_sha256": "e" * 64,
             "applicability_bundle_sha256": "f" * 64,
             "truth_file": None},
            {}, ["seed"],
        ),
    )
    monkeypatch.setattr(
        acceptance_module, "_batch_tail_conservation",
        lambda root, summary: ([
            {"check_id": "all", "status": "passed", "numerator": 1,
             "denominator": 1, "formula": "1 == 1", "detail": "通过"}
        ], [], []),
    )

    payload = acceptance_module._build_acceptance_payload(
        work_path, {"excluded_from_metrics": []},
        _complete_delivery_for_payload(), [],
    )

    assert payload["citable"] is False
    assert payload["citation_anchors"]["seed"] is None
    assert payload["missing_anchors"] == ["truth_file", "seed"]


def test_uncitable_citation_block_renders_null_without_positive_label():
    block = acceptance_module._render_citation_block({
        "batch_id": "batch-x", "citable": False,
        "missing_anchors": ["llm_model_resolved"],
        "citable_reasons": ["missing_anchor:llm_model_resolved"],
        "citation_anchors": {
            "seed": 301, "pool_content_sha256": "a" * 64,
            "git_commit": "b" * 40, "code_state_sha256": "c" * 64,
            "neo4j_database": "s25smoke", "llm_model_resolved": None,
            "rulecard_pack_sha256": "d" * 64,
            "applicability_bundle_sha256": "e" * 64,
            "truth_file": None,
        },
    })

    assert "已解析模型名：null" in block
    assert "真值文件：null" in block
    assert "数字可引" not in block
    assert "`citable=false`" in block


def test_acceptance_artifacts_write_json_and_replace_block_idempotently(work_path):
    (work_path / "batch_summary.md").write_text("# 摘要\n", encoding="utf-8")
    payload = {
        "schema_version": "batch_acceptance.v1",
        "batch_id": "batch-x", "citable": True,
        "missing_anchors": [], "citable_reasons": [],
        "citation_anchors": {
            "seed": 301, "pool_content_sha256": "a" * 64,
            "git_commit": "b" * 40, "code_state_sha256": "c" * 64,
            "neo4j_database": "s25smoke", "llm_model_resolved": "model",
            "rulecard_pack_sha256": "d" * 64,
            "applicability_bundle_sha256": "e" * 64,
            "truth_file": {"path": "truth.jsonl", "sha256": "f" * 64},
        },
        "items": [], "conservation_checks": [],
    }

    acceptance_module._write_acceptance_artifacts(work_path, payload)
    acceptance_module._write_acceptance_artifacts(work_path, payload)

    written = json.loads(
        (work_path / "batch_acceptance.json").read_text(encoding="utf-8"))
    summary = (work_path / "batch_summary.md").read_text(encoding="utf-8")
    assert written["schema_version"] == "batch_acceptance.v1"
    assert written["citable"] is True
    assert summary.count(acceptance_module.CITATION_BLOCK_START) == 1
    assert "## 数字可引·引用块" in summary


def test_true_summary_mutation_is_caught_by_batch_tail_recomputation(
        work_path):
    building_id = "BLD-TEST-0001"
    building = work_path / "buildings" / building_id
    run = building / "runs" / "RUN-0001"
    run.mkdir(parents=True)
    (work_path / "batch_manifest.json").write_text(json.dumps({
        "building_ids": [building_id],
    }), encoding="utf-8")
    (work_path / "progress.jsonl").write_text(json.dumps({
        "building_id": building_id, "status": "completed",
    }) + "\n", encoding="utf-8")
    (building / "eval_report.json").write_text(json.dumps({
        "building_id": building_id, "metrics": {}, "leakage_audit": {},
    }), encoding="utf-8")
    (run / "closure_validation_result.json").write_text(json.dumps({
        "closure_summary": {},
    }), encoding="utf-8")
    (run / "run_audit.json").write_text(json.dumps({
        "llm_tool_call_count": 1, "llm_forced_finalize": False,
        "status_trace": ["created", "report_ready"],
        "report_filename": "report.md",
    }), encoding="utf-8")
    (run / "report.md").write_text("# 报告\n", encoding="utf-8")
    aggregate = acceptance_module._load("aggregate_baseline_batch")
    summary = aggregate.aggregate_batch(work_path)

    # 真变异：只把批摘要的报告数 1 改为 2，逐栋产物保持不变。
    summary["report_count"] = 2
    (work_path / "batch_summary.json").write_text(
        json.dumps(summary), encoding="utf-8")
    checks, _, _ = acceptance_module._batch_tail_conservation(
        work_path, summary)
    by_id = {check["check_id"]: check for check in checks}

    assert by_id["report_count_conservation"]["status"] == "failed"
    assert by_id["summary_recomputed_from_buildings"]["status"] == "failed"
    assert by_id["summary_recomputed_from_buildings"]["detail"] == {
        "mismatched_fields": ["report_count"]
    }


# ── run 目录唯一性结构闸 ────────────────────────────────────────────────
# 案源：步 D 第一段地板批中断残留 run 目录被聚合算成「51/51 栋」并判 ✅。
# 这一组测试的形态就是当日的复现：先造干净批（闸绿），再**只加一个多余
# run 目录**（闸必红）——不加这一半，闸就只是「在批上碰巧是绿的」。


def _fake_batch(root: Path, building_ids, runs_per_building):
    for index, building_id in enumerate(building_ids):
        # 栋目录无条件建——run 数为 0 的栋必须存在，否则「零 run 目录」那条
        # 分支根本没有人群可判（判据必须在被筛人群上有意义）。
        (root / "buildings" / building_id / "runs").mkdir(parents=True)
        for run_index in range(runs_per_building[index]):
            (root / "buildings" / building_id / "runs"
             / f"RUN-{run_index:04d}").mkdir()
    return root


def test_run_dir_gate_passes_on_one_run_per_building(work_path):
    _fake_batch(work_path, ["BLD-A", "BLD-B", "BLD-C"], [1, 1, 1])

    got = acceptance_module.run_directory_uniqueness(work_path, 3)

    assert got["ok"] is True
    assert got["run_dir_total"] == 3
    assert got["building_count"] == 3
    assert got["multi_run_buildings"] == []
    assert got["count_matches_completed"] is True
    assert "每栋恰 1，且与完成栋数相等" in got["detail"]


def test_run_dir_gate_reds_on_one_extra_stale_run_dir(work_path):
    """变异对照：唯一改动＝给 BLD-B 加一个多余 run 目录。"""
    _fake_batch(work_path, ["BLD-A", "BLD-B", "BLD-C"], [1, 1, 1])
    assert acceptance_module.run_directory_uniqueness(work_path, 3)["ok"] is True

    (work_path / "buildings" / "BLD-B" / "runs" / "RUN-STALE").mkdir()

    got = acceptance_module.run_directory_uniqueness(work_path, 3)

    assert got["ok"] is False
    assert got["multi_run_buildings"] == ["BLD-B"]
    # 当日现场的读数：栋数还是 3，run 目录却是 4——闸要抓的正是这个差。
    assert got["run_dir_total"] == 4
    assert got["building_count"] == 3
    assert "多 run 目录栋 1" in got["detail"]
    assert "BLD-B×2" in got["detail"]


def test_run_dir_gate_reds_when_total_does_not_match_completed(work_path):
    """反向：每栋恰 1，但完成清单说 4 栋——glob 射程与完成清单不同源。"""
    _fake_batch(work_path, ["BLD-A", "BLD-B", "BLD-C"], [1, 1, 1])

    got = acceptance_module.run_directory_uniqueness(work_path, 4)

    assert got["ok"] is False
    assert got["count_matches_completed"] is False
    assert got["multi_run_buildings"] == []
    assert "与完成栋数不等" in got["detail"]


def test_run_dir_gate_does_not_red_on_missing_completed_count(work_path):
    """老批 schema 缺 `completed_count`：只报不判，别拿缺字段当失败。"""
    _fake_batch(work_path, ["BLD-A", "BLD-B"], [1, 1])

    got = acceptance_module.run_directory_uniqueness(work_path, None)

    assert got["ok"] is True
    assert got["count_matches_completed"] is None
    assert "未做反向对账" in got["detail"]


def test_run_dir_gate_logs_zero_run_buildings_without_reding(work_path):
    """零 run 目录的栋由「跑批完成度」承接，本闸只登记——避免同一故障红两处。"""
    _fake_batch(work_path, ["BLD-A", "BLD-B"], [1, 0])

    got = acceptance_module.run_directory_uniqueness(work_path, 1)

    assert got["ok"] is True
    assert got["zero_run_buildings"] == ["BLD-B"]
    assert got["run_dir_total"] == 1
    assert "无 run 目录" in got["detail"]
