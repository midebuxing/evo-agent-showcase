"""验收闸真值档显式二选一（2026-08-07，D9 正单 §一.①）。

被测的是**换锚这件事本身**：选中的那份要一路贯穿到引用锚、阅卷器实参、
产物声明；而**不随开关变的两项**（第 4/6 项各自硬编码 v1）要在产物里显形，
不许被选中的那份冒名。

形与阅卷器 `score_clause_coverage.py` 对齐：显式参数、缺省不跟着换、沿革注记。
三条判别力的来源：
  1. 换锚**不能顺手把对账关掉** —— 选 v2 而阅卷器报 v1 仍须报错位；
  2. 换锚**不能自带一条恒红断言** —— 选 v2 且阅卷器也报 v2 时不许多出缺锚；
  3. 空作用域通过 ≠ 检查通过 —— 在险清单是旧池楼号，换池后恒真。
"""
from __future__ import annotations

import inspect
import io
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_batch_acceptance as acceptance  # noqa: E402


def _complete_delivery(truth_path: str) -> dict:
    """一份「其余锚全齐」的交付，只让真值档选择决定结果。"""
    truth_doc = {
        "truth_file": truth_path,
        "truth_coverage_complete": True,
        "truth_item_count": 1,
        "truth_building_count": 1,
        "truth_chapter_count": 1,
        "card_quantifier_meaning": "any=条款级",
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


@pytest.fixture
def build_payload(tmp_path, monkeypatch):
    (tmp_path / "batch_manifest.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        acceptance, "_collect_citation_anchors",
        lambda root, manifest, truth: (
            {"seed": 401, "pool_content_sha256": "b" * 64,
             "git_commit": "c" * 40, "code_state_sha256": "d" * 64,
             "neo4j_database": "s25smoke", "llm_model_resolved": "model",
             "rulecard_pack_sha256": "e" * 64,
             "applicability_bundle_sha256": "f" * 64,
             "truth_file": truth},
            {}, [],
        ))
    monkeypatch.setattr(
        acceptance, "_batch_tail_conservation",
        lambda root, summary: ([
            {"check_id": "all", "status": "passed", "numerator": 1,
             "denominator": 1, "formula": "1 == 1", "detail": "通过"}
        ], [], []))

    def build(delivery: dict, selection: str | None) -> dict:
        return acceptance._build_acceptance_payload(
            tmp_path, {"excluded_from_metrics": []}, delivery, [],
            truth_selection=selection)

    return build


def _by_id(payload: dict) -> dict:
    return {item["item_id"]: item for item in payload["items"]}


# ── 名字表与缺省 ──────────────────────────────────────────────────────

def test_default_is_v1_and_the_name_table_is_shared_with_both_consumers():
    """缺省不跟着新池换；三个消费者认同一组名字、且同名指同一文件。"""
    import assert_pool_truth_disjoint as disjoint  # noqa: PLC0415
    import score_clause_coverage as scorer  # noqa: PLC0415

    assert acceptance.DEFAULT_TRUTH_FILE == "v1"
    assert acceptance.TRUTH_FILE == acceptance.NAMED_TRUTH_FILES["v1"]
    assert (sorted(acceptance.NAMED_TRUTH_FILES)
            == sorted(scorer.NAMED_TRUTH_FILES)
            == sorted(disjoint.NAMED_TRUTH_FILES))
    for name, path in acceptance.NAMED_TRUTH_FILES.items():
        assert path.resolve() == (
            acceptance.REPO / scorer.NAMED_TRUTH_FILES[name]).resolve()


def test_unknown_name_raises_instead_of_silently_falling_back():
    """选错档绝不静默回退到缺省——那正是静默换锚的形状。"""
    assert acceptance._resolve_truth_file(None) == (
        acceptance.NAMED_TRUTH_FILES["v1"])
    assert acceptance._resolve_truth_file("v2") == (
        acceptance.NAMED_TRUTH_FILES["v2"])
    with pytest.raises(ValueError, match="不认识的真值档"):
        acceptance._resolve_truth_file("v3")


def test_truth_anchor_defaults_to_v1_but_follows_an_explicit_path(tmp_path):
    """`_truth_anchor` 的沿革调用面（零参）行为一字节不变。"""
    legacy, missing = acceptance._truth_anchor()
    assert missing == []
    assert legacy["path"].endswith("applicable_normative_item_truth_v1.jsonl")

    picked, missing2 = acceptance._truth_anchor(
        acceptance.NAMED_TRUTH_FILES["v2"])
    assert missing2 == []
    assert picked["path"].endswith("applicable_normative_item_truth_v2.jsonl")
    assert picked["sha256"] != legacy["sha256"]

    absent, missing3 = acceptance._truth_anchor(tmp_path / "nope.jsonl")
    assert absent is None and missing3 == ["truth_file"]


# ── 换锚贯穿产物 ──────────────────────────────────────────────────────

def test_selected_v2_becomes_the_citation_anchor(build_payload):
    delivery = _complete_delivery(
        str(acceptance.NAMED_TRUTH_FILES["v2"]))
    payload = build_payload(delivery, "v2")

    selection = payload["truth_file_selection"]
    assert selection["selected"] == "v2"
    assert selection["explicit"] is True
    assert selection["path"].endswith("applicable_normative_item_truth_v2.jsonl")
    assert _by_id(payload)["5"]["truth_file"]["path"].endswith(
        "applicable_normative_item_truth_v2.jsonl")
    # 换锚不许自带一条恒红断言（原实现把 `same_truth` 写死比 v1，一换就永远缺锚）。
    assert "clause_coverage_truth_file" not in payload["missing_anchors"]


def test_scorer_reading_a_different_file_is_still_caught(build_payload):
    """选 v2 而阅卷器报 v1 ⇒ 必须报错位。换锚不能顺手把对账关掉。"""
    delivery = _complete_delivery(str(acceptance.NAMED_TRUTH_FILES["v1"]))
    payload = build_payload(delivery, "v2")

    assert "clause_coverage_truth_file" in payload["missing_anchors"]
    assert payload["citable"] is False


def test_pinned_items_keep_the_v1_anchor_and_declare_the_misalignment(
        build_payload):
    """第 6 项硬编码 v1：锚必须记它真读的那份，错位在产物里显形。

    🔴 **第 4 项已于 2026-08-07 摘出该集合**（阶段丙尾巴）：
    `audit_atrisk_truth_items.py` 接了 `--truth-file`，且**在险清单随档换**
    （`AT_RISK_REGISTRY`），故它不再是「锚固定在缺省档」的例外项。
    这里用字面量 `{"6"}` 钉住——把断言写成 `== TRUTH_ANCHOR_PINNED_ITEMS`
    等于让测试跟着实现一起漂，那样这条断言就什么都不保证了。
    """
    delivery = _complete_delivery(str(acceptance.NAMED_TRUTH_FILES["v2"]))
    payload = build_payload(delivery, "v2")
    items = _by_id(payload)

    for item_id in sorted(acceptance.TRUTH_ANCHOR_PINNED_ITEMS):
        assert items[item_id]["truth_file"]["path"].endswith(
            "applicable_normative_item_truth_v1.jsonl")
        note = items[item_id]["detail"]["truth_anchor_pinned"]
        assert note["reads"] == "v1"
        assert note["selected"] == "v2"
    assert set(payload["truth_file_selection"]["pinned_items"]) == {"6"}


def test_atrisk_item_follows_the_selected_truth_file(build_payload):
    """第 4 项**跟着 `--truth-file` 走**，且不再声明任何错位（2026-08-07 新契约）。

    反面判例就是它自己的旧形态：清单钉死在旧池楼号 ⇒ 换池批上零交集 ⇒
    `vacuous` ⇒ 一道什么都没检查的闸。真值与在险清单必须同时换，
    本断言钉的是「同时」——只换其一都会让这条红。
    """
    delivery = _complete_delivery(str(acceptance.NAMED_TRUTH_FILES["v2"]))
    payload = build_payload(delivery, "v2")
    item4 = _by_id(payload)["4"]

    assert item4["truth_file"]["path"].endswith(
        "applicable_normative_item_truth_v2.jsonl")
    assert item4["detail"]["truth_anchor_pinned"] is None
    assert "4" not in payload["truth_file_selection"]["pinned_items"]


def test_no_misalignment_declared_when_the_default_is_used(build_payload):
    """选缺省档时三项同源，不该印一条无中生有的错位警告。"""
    delivery = _complete_delivery(str(acceptance.TRUTH_FILE))
    payload = build_payload(delivery, None)

    selection = payload["truth_file_selection"]
    assert selection["selected"] == "v1"
    assert selection["explicit"] is False
    assert selection["pinned_items"] == {}
    items = _by_id(payload)
    for item_id in ("4", "6"):
        assert items[item_id]["detail"]["truth_anchor_pinned"] is None
        assert items[item_id]["truth_file"]["path"].endswith(
            "applicable_normative_item_truth_v1.jsonl")


# ── 空作用域通过 ≠ 检查通过 ────────────────────────────────────────────

def test_empty_at_risk_scope_is_marked_vacuous(build_payload):
    delivery = _complete_delivery(str(acceptance.TRUTH_FILE))
    assert delivery["4"]["in_scope"] == 0
    assert _by_id(build_payload(delivery, None))["4"]["detail"]["vacuous"] is True

    delivery["4"]["in_scope"] = 8
    delivery["4"]["passed"] = 8
    assert _by_id(build_payload(delivery, None))["4"]["detail"]["vacuous"] is False

    delivery["4"]["in_scope"] = None
    assert _by_id(build_payload(delivery, None))["4"]["detail"]["vacuous"] is None


# ── 空作用域必须打退出码（2026-08-07 波次二补完阶段 0，DEBT-092 ①）──────

def _at_risk_stub(in_scope: int, inventory_total: int = 8, rc: int = 0):
    """把 `audit_atrisk_truth_items` 换成只印计数行的假桩。

    验收闸是**用正则从审计器 stdout 取计数**的，所以桩必须印真实格式的那一行 ——
    换成直接塞返回值就测不到「取数 → 判据」这一段。
    """
    class _Stub:
        @staticmethod
        def main(argv):
            print(f"在险真值项 {in_scope}/{inventory_total} 项在本批内，批 = x")
            print("失守 0 项")
            return rc
    return _Stub


@pytest.mark.parametrize("in_scope, expect_rc, expect_status", [
    (0, 1, "failed"),
    (3, 0, "passed"),
])
def test_vacuous_at_risk_scope_fails_the_gate(
        tmp_path, monkeypatch, capsys, in_scope, expect_rc, expect_status):
    """🔴 变异对照：`in_scope == 0` ⇒ 硬项失败 ＋ 退出码 1 ＋ `citable=false`。

    2026-08-07 之前这里只「显形」（印警告 ＋ 落 `vacuous=true`）而**退出码照旧 0**
    ——一道什么都没检查的回归闸被算进「全部硬项通过」，`citable` 照样 true。
    在险清单是**旧池楼号**积累出来的，换池后与本批零交集 ⇒ 全称量词落在空集上恒真。

    ⚠️ 本条**跑真 `main()`**、断言的是**退出码与落盘产物**，不是只看那个标记位。
    只测 `_build_acceptance_payload` 的 `vacuous` 字段（上一条测的）**测不到退出码**
    ——本仓记过「只测生产者自身等于没测」，那正是这个缺陷活了一天的原因。
    """
    root = _fake_batch(tmp_path / "batch")
    # 让 A 门落 not_applicable：本条要隔离的是第 4 项，不该被别的硬项污染退出码。
    (root / "batch_manifest.json").write_text(
        json.dumps({"run_profile": {"baseline_acceptance_eligible": False}}),
        encoding="utf-8")
    real_load = acceptance._load
    monkeypatch.setattr(
        acceptance, "_load",
        lambda name: (_at_risk_stub(in_scope) if name == "audit_atrisk_truth_items"
                      else real_load(name)))

    rc = acceptance.main(["--batch-root", str(root)])
    out = capsys.readouterr().out
    assert rc == expect_rc, "退出码必须只由第 4 项决定（其余硬项在本夹具里都绿）"

    written = json.loads((root / "batch_acceptance.json").read_text(encoding="utf-8"))
    item4 = _by_id(written)["4"]
    assert item4["detail"]["vacuous"] is (in_scope == 0)
    assert item4["status"] == expect_status

    if in_scope == 0:
        assert "空作用域，判失败" in out
        # 解法要印出来：不加豁免开关，改按本批的池重新识别清单。
        assert "--rediscover" in out
        assert written["citable"] is False
        assert "hard_item_failed:在险真值项" in written["citable_reasons"]
    else:
        assert "hard_item_failed:在险真值项" not in written["citable_reasons"]


def test_vacuous_has_no_exemption_switch():
    """🔴 不许用开关把这道闸关掉。

    「加个 `--allow-vacuous` 让它继续绿」是给「登记了但没人消费」再添一例；
    真解法是按本批的池重新识别在险清单。本条把这个设计取舍钉住：
    命令行上不存在任何跳过／豁免本项的入口。
    """
    parser_src = inspect.getsource(acceptance.main)
    for forbidden in ("allow-vacuous", "allow_vacuous", "skip-at-risk", "skip_at_risk"):
        assert forbidden not in parser_src


# ── 引用块自带选择 ────────────────────────────────────────────────────

def test_citation_block_carries_the_selection():
    """引用块常被整段拷进笔记，而命令行不跟着走。"""
    base = {
        "batch_id": "batch-x", "citable": False,
        "missing_anchors": [], "citable_reasons": [],
        "citation_anchors": {
            "truth_file": {"path": "t.jsonl", "sha256": "a" * 64}},
    }
    block_v2 = acceptance._render_citation_block({
        **base,
        "truth_file_selection": {
            "selected": "v2", "default": "v1", "explicit": True,
            "path": "t2.jsonl", "pinned_items": {"4": {}, "6": {}},
        },
    })
    assert "真值档选择：`v2`（显式）" in block_v2
    assert "第 4/6 项仍读 `v1`" in block_v2

    block_v1 = acceptance._render_citation_block({
        **base,
        "truth_file_selection": {
            "selected": "v1", "default": "v1", "explicit": False,
            "path": "t1.jsonl", "pinned_items": {},
        },
    })
    assert "真值档选择：`v1`（缺省）" in block_v1
    assert "仍读" not in block_v1

    # 老产物（没有该字段）不许崩——引用块渲染是产物出口，崩了就什么都没有。
    assert "真值档选择：null" in acceptance._render_citation_block(base)


# ── 生产路径：两次阅卷器调用都显式带参 ────────────────────────────────

def _fake_batch(root: Path) -> Path:
    """最小可跑批：只要有一份闭包产物，`main()` 就不会走「桩批跳过」早退。"""
    run = root / "buildings" / "BLD-X" / "runs" / "RUN-1"
    run.mkdir(parents=True)
    (run / "closure_validation_result.json").write_text(
        json.dumps({"machine_readable_report": {"obligations": []}}),
        encoding="utf-8")
    (root / "batch_manifest.json").write_text("{}\n", encoding="utf-8")
    (root / "batch_summary.json").write_text(
        json.dumps({"completion": {"planned_count": 1, "completed_count": 1,
                                   "failed_count": 0}}), encoding="utf-8")
    return root


@pytest.mark.parametrize("selection", ["v1", "v2"])
def test_both_scorer_invocations_carry_an_explicit_truth_file(
        tmp_path, monkeypatch, selection):
    """跑真正的 `main()`，把阅卷器换成只记 argv 的假桩。

    ⚠️ 不用「搜源码字符串」验这条——本项目记过「只测生产者自身等于没测」。
    """
    root = _fake_batch(tmp_path / "batch")
    seen: list[list[str]] = []

    class _RecordingScorer:
        @staticmethod
        def main(argv):
            seen.append(list(argv))
            print(json.dumps({
                "truth_file": str(acceptance.NAMED_TRUTH_FILES[selection]),
                "truth_coverage_complete": True,
                "overall": {
                    "covered_count": 0, "applicable_item_count": 1,
                    "applicable_item_recall": 0.0, "pending_item_count": 0,
                    "buildings_gate_pass": 0, "buildings_scored": 0,
                    "missed_applicable_item_count": 0,
                },
                "buildings": [],
            }, ensure_ascii=False))
            return 0

    real_load = acceptance._load
    monkeypatch.setattr(
        acceptance, "_load",
        lambda name: (_RecordingScorer if name == "score_clause_coverage"
                      else real_load(name)))

    acceptance.main(["--batch-root", str(root), "--truth-file", selection])

    assert len(seen) == 2, "条款级 + 义务单元级，两次都要调"
    for argv in seen:
        assert "--truth-file" in argv
        assert argv[argv.index("--truth-file") + 1] == selection
    # 义务单元级那次还得带量词口径，别把两个参数改成互斥。
    assert "--card-quantifier" in seen[1]

    written = json.loads(
        (root / "batch_acceptance.json").read_text(encoding="utf-8"))
    assert written["truth_file_selection"]["selected"] == selection
    assert written["truth_file_selection"]["explicit"] is True


# ── 控制台编码：闸不许因为打印而崩溃 ──────────────────────────────────

def test_gate_forces_utf8_on_a_gbk_console(monkeypatch, capsys):
    """变异复现：把 stdout 换成 GBK 流 → 修前 `UnicodeEncodeError` 崩掉整条命令。

    🔴 崩点在**结论行之前**，所有判据都白跑了，而退出码看起来像「硬项失败」
    ——一条与真实结论无关的假红。2026-08-07 D9 实撞（`⚠️` 印不出去）。

    这里不测「打印得好看」，只测**流被切到 UTF-8**：能写出 ✅❌⚠️ 三个字符
    就说明那条崩溃路径关上了。
    """
    with capsys.disabled():
        raw = io.BytesIO()
        gbk_stream = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
        monkeypatch.setattr(sys, "stdout", gbk_stream)
        monkeypatch.setattr(sys, "stderr", gbk_stream)

        # 修前：这三个字符任一都会在 GBK 流上抛 UnicodeEncodeError
        with pytest.raises(UnicodeEncodeError):
            gbk_stream.write("⚠️")
            gbk_stream.flush()

        acceptance._force_utf8_streams()

        sys.stdout.write("✅❌⚠️")
        sys.stdout.flush()
        assert "✅❌⚠️".encode("utf-8") in raw.getvalue()


def test_force_utf8_is_a_noop_on_a_captured_stringio(monkeypatch):
    """`_run_quiet` 把 stdout 换成 `StringIO`（无 `reconfigure`）——不许因此炸。

    批驱动收尾时是**内嵌调用** `main()`，走的正是这条路；
    在这里抛异常等于「防护本身成了新的崩溃源」。
    """
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(sys, "stderr", buffer)
    acceptance._force_utf8_streams()          # 不抛即通过
    sys.stdout.write("✅")
    assert buffer.getvalue() == "✅"


def test_gate_main_survives_a_gbk_console_end_to_end(tmp_path, monkeypatch):
    """端到端：GBK 流下跑完整 `main()`，退出码由判据决定、不由编码决定。"""
    root = _fake_batch(tmp_path / "batch")
    raw = io.BytesIO()
    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(raw, encoding="gbk", errors="strict"))
    monkeypatch.setattr(sys, "stderr", sys.stdout)

    code = acceptance.main(["--batch-root", str(root), "--truth-file", "v2"])

    sys.stdout.flush()
    assert isinstance(code, int)
    printed = raw.getvalue().decode("utf-8")
    assert "真值档：v2" in printed        # 真值档：v2
    assert "⚠" in printed                              # 锚错位警告印出去了
