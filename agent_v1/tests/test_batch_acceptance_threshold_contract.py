"""P4：`check_batch_acceptance` 门限契约（2026-08-06，换池前置第四项）。

## 这份文件是什么

`决议_换池前置_20260805.md` §二 P4 要求：**开跑前**把五个场景的「应过／应拒」
写死，不许看到新池结果之后再回来重锚门限。pro 换池前审问一 3.3 逐字列出五场景：

    - 当前最终工作树的真实分母；
    - pending 行增加但系统输出不变；
    - applicable 成员增减但比例不变；
    - 分母为零或接近零；
    - 同一输出在旧、新分母下是否改变过门结论。

⇒ **本文件即那份签字面**：每条测试的 docstring 写死场景、预期与判据来源；
数字与结论都是在**换池批开跑之前**落的。跑完新池若与此不符，只能新增带沿革的
条目，**不许原位改这里的期望**（`决议_换池前置_20260805.md` §二 P8）。

## 为什么这件事要单独立一个门

#25 真值落改把 `applicable` 变成三态后，**三个分母同时动了**：
召回分母 2324→2340、精确率侧反向闸分母 443→423、挂起量 0→4
（`实施记录_25_真值落改_20260805.md` §5.4）。而验收总闸消费的正是前两个。
⇒ 「门限随分母漂移而静默错判」这件事从此有了真实触发条件，不再是假想。

⚠️ **这三个数都不是常数**——它们是真值文件自身的属性。本文件因此
**只锁结构关系与判据形状**，涉及全库计数的地方一律以「当期实测」形式落在
`agent_v1/scripts/preregistration_dry_run.py` 的期望表里，由那张表承担沿革，
测试这边只断言「表在、口径在、与真值文件当期实测一致」。

## 判据单一真源

本文件一律走生产函数（`score_clause_coverage.score_building` /
`check_batch_acceptance._build_acceptance_payload`），**不在测试里重写任何判据**
——本仓成例：内联逻辑 + 复制式测试 = 假的变异验证。

## 变异验证（写测试时实跑过）

- 把 `_build_acceptance_payload` 里 `clause_coverage_denominator` 那条判据删掉
  ⇒ `test_s4_zero_denominator_forces_citable_false` 失败
- 把 `clause_coverage_pending_visibility` 删掉
  ⇒ `test_s2_missing_pending_field_blocks_citation` 与
    `test_s5_old_caliber_product_loses_citability_by_design` 失败
- 把第 5 项的 `hardness` 由 `soft` 改成 `hard`
  ⇒ `test_s5_hardness_table_is_frozen` 失败
- 把 `"8/8 仍被承接"` 那句硬编码文案改回去
  ⇒ `test_no_hardcoded_population_constants_in_gate_code` 失败
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_batch_acceptance as acceptance  # noqa: E402
import preregistration_dry_run as dry_run  # noqa: E402
import score_clause_coverage as scorer  # noqa: E402

PENDING = "unknown_pending"
BUILDING = "BLD-TEST-P4-CONTRACT-0001"
CARD = "rc.test.p4.threshold_contract"
FRAG = "FRG-TEST-P4-01"


# ── 造具：一份固定的系统产物 + 可变的真值 ────────────────────────────────
#
# 五场景里有四个都是「**系统输出不变**，只动真值那一侧」——造具因此把系统产物
# 做成 fixture 级常量，真值按场景现造。这样任何结论变化都只能来自真值侧。


def _truth_row(item_id: str, applicable, expected_card_ids: list[str]) -> dict:
    return {
        "schema_version": "applicable_normative_item_truth_v1",
        "world_id": "WB-TEST-P4-0001-S00301",
        "building_id": BUILDING,
        "normative_item_id": item_id,
        "source_clause_id": "2.1.3(n)",
        "scope_type": "building",
        "scope_id": BUILDING,
        "applicable": applicable,
        "modality_zh": "shall",
        "conditionality": "trigger_conditioned",
        "reason": "P4 门限契约造具",
        "expected_card_ids": expected_card_ids,
        "zh_source_excerpt": "測試",
    }


@pytest.fixture(scope="module")
def building_dir(tmp_path_factory) -> Path:
    """系统产物：一张卡、一条已满足义务。五场景全程一个字节不变。"""
    root = tmp_path_factory.mktemp("p4_threshold_contract")
    bdir = root / "buildings" / BUILDING
    run = bdir / "runs" / "RUN-TEST"
    run.mkdir(parents=True)
    (run / "fact_pack.json").write_text(json.dumps({
        "facts": [
            {"carrier_type": "fragment", "carrier_id": FRAG,
             "slot_id": "fragment_role",
             "qualifiers": {"component_type_key": "external_wall"}},
        ]
    }), encoding="utf-8")
    (run / "rule_slice.json").write_text(json.dumps({
        "candidate_rule_cards": [{"rule_card_id": CARD}],
    }), encoding="utf-8")
    (run / "obligation_set.json").write_text(json.dumps({
        "obligations": [
            {"obligation_id": "OB-1", "source_rule_card_id": CARD,
             "kind": "action", "scope_type": "building", "scope_id": BUILDING,
             "applicability_state": "applicable",
             "satisfaction_status": "satisfied", "closure_status": "closed"},
        ]
    }), encoding="utf-8")
    return bdir


def _score(building_dir: Path, items: list[dict]) -> dict:
    return scorer.score_building(building_dir, items, {CARD})


# ── 造具：把一份阅卷结果塞进验收总闸的载荷构造器 ──────────────────────────


def _coverage_doc(result: dict, *, states: dict | None = None,
                  drop_keys: tuple[str, ...] = ()) -> dict:
    """把单栋阅卷结果包成阅卷器顶层文档的形状（总闸消费的就是这个）。"""
    overall = {
        key: value for key, value in result.items()
        if key in ("covered_count", "applicable_item_count",
                   "applicable_item_recall", "missed_applicable_item_count",
                   "pending_item_count")
    }
    for key in drop_keys:
        overall.pop(key, None)
    return {
        "truth_file": str(acceptance.TRUTH_FILE),
        "truth_coverage_complete": True,
        "truth_item_count": len(result.get("items") or []),
        "truth_building_count": 1,
        "truth_chapter_count": 1,
        "card_quantifier_meaning": "any=条款级",
        "truth_applicable_state_counts": states if states is not None else {
            "applicable": result["applicable_item_count"],
            "not_applicable": 0,
            "pending": result.get("pending_item_count", 0),
        },
        "buildings": [result],
        "overall": overall,
    }


def _delivery(coverage: dict, *, error: str | None = None) -> dict:
    return {
        "A": {"eligible": False, "status": "not_applicable", "detail": None},
        "1": {"status": "passed", "planned": 1, "completed": 1,
              "failed": 0, "excluded": [], "detail": "完成 1 / 失败 0"},
        "2": {"status": "passed", "exemption_count": 0, "detail": "通过"},
        "3": {"status": "passed", "keyset_equal_count": 1,
              "building_count": 1, "degradation_signal_count": 0,
              "degradation_signals": [], "detail": "通过"},
        "4": {"status": "passed", "in_scope": 3, "inventory_total": 8,
              "failed": 0, "passed": 3, "detail": "3/3 仍被承接"},
        "5": {"status": "reported", "clause_level": coverage,
              "obligation_unit_level": coverage, "error": error},
        "6": {"status": "reported", "open_suspect_groups": 0,
              "total_suspect_groups": 0, "error": None},
        "7": {"status": "not_requested", "baseline_batch": None,
              "equal": None, "unequal": None, "error": None},
    }


@pytest.fixture
def payload_of(tmp_path, monkeypatch):
    """只让「覆盖证据」这一条决定 citable，其余锚一律造成齐备。

    这样任何 `citable=false` 都只可能来自分母语义，判别力集中在被测那件事上。
    """
    # `_truth_anchor` 2026-08-07 起收一个「选中的真值档路径」参数（缺省沿革调用面），
    # 这里用 `*_a` 吸收——本夹具关心的是锚齐备，不关心选了哪一档。
    monkeypatch.setattr(
        acceptance, "_truth_anchor",
        lambda *_a, **_kw: ({"path": "truth.jsonl", "sha256": "a" * 64}, []))
    monkeypatch.setattr(
        acceptance, "_collect_citation_anchors",
        lambda root, manifest, truth: (
            {"seed": 301, "pool_content_sha256": "b" * 64,
             "git_commit": "c" * 40, "code_state_sha256": "d" * 64,
             "neo4j_database": "s25smoke", "llm_model_resolved": "model",
             "rulecard_pack_sha256": "e" * 64,
             "applicability_bundle_sha256": "f" * 64,
             "truth_file": {"path": "truth.jsonl", "sha256": "a" * 64}},
            {}, [],
        ))
    monkeypatch.setattr(
        acceptance, "_batch_tail_conservation",
        lambda root, summary: ([
            {"check_id": "all", "status": "passed", "numerator": 1,
             "denominator": 1, "formula": "1 == 1", "detail": "通过"}
        ], [], []))
    (tmp_path / "batch_manifest.json").write_text("{}\n", encoding="utf-8")

    def build(delivery: dict, hard_fail: list[str] | None = None) -> dict:
        return acceptance._build_acceptance_payload(
            tmp_path, {"excluded_from_metrics": []},
            delivery, hard_fail or [])

    return build


def _item(payload: dict, item_id: str) -> dict:
    return next(i for i in payload["items"] if i["item_id"] == item_id)


# ══════════════════════════════════════════════════════════════════════
# 场景① 当前最终工作树的真实分母
# ══════════════════════════════════════════════════════════════════════


def test_s1_truth_file_three_state_distribution_is_the_current_denominator():
    """场景①（应过）：当前最终工作树上真值文件的三态分布 ＝ 三个分母的来源。

    **预期（开跑前写死）**：`{applicable: 2343, not_applicable: 423,
    pending: 4}`，合计 2770 行。三者分别是：召回分母的人群、精确率侧反向闸
    的人群、以及**不进任何分母**的挂起量（`决议_真值落改_20260805.md` §三.2）。

    **应拒的形状**：任何一格变了而没有新的沿革条目 ⇒ 本测试红。
    红不等于「代码坏了」，而是「分母人群变了、所有引用该分母的数字须重算」——
    这正是本门要挡的那件事（#25 尾巴 4 自述「换池批验收前必核」）。

    判据走生产函数 `_truth_applicable_state`，不在测试里重写三态判断。
    """
    counts = {"applicable": 0, "not_applicable": 0, "pending": 0}
    with acceptance.TRUTH_FILE.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                counts[scorer._truth_applicable_state(json.loads(line))] += 1

    assert counts == {"applicable": 2343, "not_applicable": 423, "pending": 4}
    assert sum(counts.values()) == 2770


def test_s1_dry_run_expectation_table_matches_the_truth_file():
    """场景①（应过）：预注册干跑表里登记的分母，与真值文件当期实测一致。

    分工：**测试锁口径、干跑表锁数字**。全库计数放在干跑表里，是因为它会随
    每次真值落改变化，需要的是「带沿革的条目」而不是「测试里的字面量」。
    这条测试只保证两边不会各说各话（一处改了另一处没改 ⇒ 红）。
    """
    table = {row.expectation_id: row for row in dry_run.EXPECTATIONS}
    assert table["P4-TRUTH-3STATE"].expected == {
        "applicable": 2343, "not_applicable": 423, "pending": 4,
    }
    assert table["P4-COV-DENOMINATOR"].expected == 2340
    assert table["P4-COV-PENDING"].expected == 4
    assert table["P4-PRECISION-DENOMINATOR"].expected == 423


def test_s1_gate_payload_surfaces_all_three_denominators(payload_of,
                                                         building_dir):
    """场景①（应过）：三个分母必须**同时**出现在验收产物里。

    修前实况：第 5 项只落 `numerator`/`denominator`（召回那一对），
    挂起量与精确率侧分母**一个字都没有**——而 #25 落改当日这两个各自动了
    +4 与 −20。只落一对分母 ⇒ 下一个人无法判断「分母为什么是这个数」。
    """
    result = _score(building_dir, [
        _truth_row("item.a", True, [CARD]),
        _truth_row("item.b", False, [CARD]),
        _truth_row("item.c", PENDING, []),
    ])
    payload = payload_of(_delivery(_coverage_doc(result)))
    item5 = _item(payload, "5")

    assert item5["denominator"] == result["applicable_item_count"] == 1
    assert item5["detail"]["pending_item_count"] == 1
    assert item5["detail"]["precision_side_denominator"] == 1
    assert item5["detail"]["truth_applicable_state_counts"] == {
        "applicable": 1, "not_applicable": 0, "pending": 1,
    }
    assert payload["citable"] is True


# ══════════════════════════════════════════════════════════════════════
# 场景② pending 行增加但系统输出不变
# ══════════════════════════════════════════════════════════════════════


def test_s2_pending_growth_never_changes_a_gate_verdict(payload_of,
                                                        building_dir):
    """场景②（应过）：系统产物一个字节不动、挂起行从 0 涨到 2 ⇒ 过门结论不得变。

    **预期（开跑前写死）**：
    - 硬项 A/1/2/3/4 状态逐门相同（挂起量与它们无关，本就不该动）；
    - `citable` 相同（都为 true）；
    - 第 5 项**软项**：分母 3→1、挂起 0→2、召回由 1/3 变 1/1；
    - 每栋过门判据是 `missed == 0`，挂起行不进 D 也不记漏 ⇒ 过门态不变。

    ⚠️ 这条**恰恰不是**「什么都没发生」：召回从 0.3333 跳到 1.0。
    结论不变而数字大变 ⇒ 若没有挂起量显形（见下一条），这就是纯粹的洗分母。
    """
    system_facts = [
        _truth_row("item.a", True, [CARD]),
        _truth_row("item.b", True, []),
        _truth_row("item.c", True, []),
    ]
    pending_facts = [
        _truth_row("item.a", True, [CARD]),
        _truth_row("item.b", PENDING, []),
        _truth_row("item.c", PENDING, []),
    ]
    before = _score(building_dir, system_facts)
    after = _score(building_dir, pending_facts)

    assert (before["applicable_item_count"], before["pending_item_count"]) == (3, 0)
    assert (after["applicable_item_count"], after["pending_item_count"]) == (1, 2)
    assert before["applicable_item_recall"] == pytest.approx(1 / 3)
    assert after["applicable_item_recall"] == 1.0
    # 过门判据是漏单，不是比率：挂起的两行原本就漏，移出分母后不再记漏。
    assert before["gate_pass"] is False
    assert after["gate_pass"] is True

    payload_before = payload_of(_delivery(_coverage_doc(before)))
    payload_after = payload_of(_delivery(_coverage_doc(after)))
    hard_before = {i["item_id"]: i["status"] for i in payload_before["items"]
                   if i["hardness"] == "hard"}
    hard_after = {i["item_id"]: i["status"] for i in payload_after["items"]
                  if i["hardness"] == "hard"}

    assert hard_before == hard_after
    assert payload_before["citable"] is payload_after["citable"] is True
    assert _item(payload_after, "5")["detail"]["pending_item_count"] == 2


def test_s2_missing_pending_field_blocks_citation(payload_of, building_dir):
    """场景②（应拒）：阅卷器不报挂起量 ⇒ 本批不可引。

    **为什么这是「拒」而不是「过」**：分母缩小本身合法（第三态本就不该进 D），
    但缩小必须**看得见**。阅卷文档里没有 `pending_item_count` 只有两种可能：
    ①旧版阅卷器（#25 之前，第三态被静默计进 D）②有人把第三态并回二态。
    两种情况下这批的召回都不可与三态口径的批比较。

    ⇒ 期望 `citable=false`，原因码 `missing_anchor:clause_coverage_pending_visibility`。
    """
    result = _score(building_dir, [_truth_row("item.a", True, [CARD])])
    payload = payload_of(_delivery(
        _coverage_doc(result, drop_keys=("pending_item_count",))))

    assert payload["citable"] is False
    assert "missing_anchor:clause_coverage_pending_visibility" in payload[
        "citable_reasons"]


# ══════════════════════════════════════════════════════════════════════
# 场景③ applicable 成员增减但比例不变
# ══════════════════════════════════════════════════════════════════════


def test_s3_same_ratio_different_membership_follows_missed_not_ratio(
        building_dir):
    """场景③（应过）：比率不变而成员增减 ⇒ 结论**按门限定义**走漏单，不走比率。

    门限定义（`score_clause_coverage.py` 文件头逐字）：
    「门槛：每栋 `missed_applicable_item_count == 0`（逐项漏单为空）。
    同时输出 `applicable_item_recall = |E|/|D|` 供观察，**但过门看漏单不看比率**。」

    **预期（开跑前写死）**——两组同比率、不同成员数：
    | 组 | D | 覆盖 | 比率 | 漏 | 过门 |
    |---|---|---|---|---|---|
    | 甲 | 2 | 1 | 0.5 | 1 | **否** |
    | 乙 | 4 | 2 | 0.5 | 2 | **否** |
    | 丙 | 1 | 1 | 1.0 | 0 | **是** |
    | 丁 | 3 | 3 | 1.0 | 0 | **是** |

    ⇒ 比率相同时结论也相同，但**不是因为比率相同**——是因为漏单同为 0 或同为正。
    构造一个「比率相同而漏单一 0 一正」的反例在算术上不可能（漏＝D−E，
    比率＝E/D 相同且 D 不同 ⇒ 漏同号），故本场景的正确结论是：
    **比率不是判据、也永远不会与判据冲突**；真正会变的是软项数字与分母 digest。
    """
    def missed_and_gate(rows: list[dict]) -> tuple[int, bool, float]:
        result = _score(building_dir, rows)
        return (result["missed_applicable_item_count"], result["gate_pass"],
                result["applicable_item_recall"])

    jia = missed_and_gate([_truth_row("i.a", True, [CARD]),
                           _truth_row("i.b", True, [])])
    yi = missed_and_gate([_truth_row("i.a", True, [CARD]),
                          _truth_row("i.b", True, [CARD]),
                          _truth_row("i.c", True, []),
                          _truth_row("i.d", True, [])])
    bing = missed_and_gate([_truth_row("i.a", True, [CARD])])
    ding = missed_and_gate([_truth_row("i.a", True, [CARD]),
                            _truth_row("i.b", True, [CARD]),
                            _truth_row("i.c", True, [CARD])])

    assert jia == (1, False, 0.5)
    assert yi == (2, False, 0.5)
    assert bing == (0, True, 1.0)
    assert ding == (0, True, 1.0)


def test_s3_membership_change_is_invisible_in_counts_but_not_in_digest(
        building_dir):
    """场景③（应过）：成员换了而计数不变 ⇒ 分母数字看不出，**成员 digest 必须看得出**。

    这是 P8「人群契约必须带 `population_membership_digest`」的机器理由：
    只登记分母数字的预注册条目，挡不住「人群整体换掉、大小恰好相同」。
    """
    left = _score(building_dir, [_truth_row("i.a", True, [CARD]),
                                 _truth_row("i.b", True, [CARD])])
    right = _score(building_dir, [_truth_row("i.a", True, [CARD]),
                                  _truth_row("i.zz", True, [CARD])])

    assert left["applicable_item_count"] == right["applicable_item_count"] == 2
    assert left["applicable_item_recall"] == right["applicable_item_recall"]

    def members(result: dict) -> list[str]:
        return [row["normative_item_id"] for row in result["items"]]

    assert dry_run.population_digest(members(left)) != dry_run.population_digest(
        members(right))


# ══════════════════════════════════════════════════════════════════════
# 场景④ 分母为零或接近零
# ══════════════════════════════════════════════════════════════════════


def test_s4_zero_denominator_yields_none_recall_not_one(building_dir):
    """场景④（应过）：分母为零时召回必须是 `None`，不得是 1.0 或 0.0。

    `score_clause_coverage.py:1203` 写的是 `(covered / D) if D else None`
    ——这是对的，本条锁住它不许被「改成 0 除保护返回 1.0」那类顺手改动。
    分母为零时报 1.0 会让「一条都没评」印成「全评对了」。
    """
    result = _score(building_dir, [_truth_row("i.a", PENDING, [])])

    assert result["applicable_item_count"] == 0
    assert result["applicable_item_recall"] is None
    assert result["pending_item_count"] == 1


def test_s4_zero_denominator_forces_citable_false(payload_of, building_dir):
    """场景④（应拒）：分母为零 ⇒ **fail-loud**，`citable=false`。

    修前实况（2026-08-06 实测）：`main()` 里第 5 项的 `status` 只由
    「`json.loads` 成功」决定，分母塌成 0、召回是 `None`、`soft()` 打印时抛
    `TypeError` 被吞——`delivery["5"]["status"]` 照样是 `reported`，
    于是 `evidence_missing` 一条不加，**`citable=true`、退出码 0**。
    一批「一条都没评上」的产物被认证为数字可引。

    ⇒ 期望两条原因码同时出现：`clause_coverage_denominator`（分母不是正整数）
    与 `clause_coverage_recall`（召回缺失）。
    """
    result = _score(building_dir, [_truth_row("i.a", PENDING, [])])
    payload = payload_of(_delivery(_coverage_doc(result)))

    assert payload["citable"] is False
    assert "missing_anchor:clause_coverage_denominator" in payload[
        "citable_reasons"]
    assert "missing_anchor:clause_coverage_recall" in payload["citable_reasons"]


def test_s4_scorer_error_with_parsed_doc_still_blocks_citation(
        payload_of, building_dir):
    """场景④（应拒）：阅卷器半程抛错但文档已解析 ⇒ 仍不可引。

    这是上一条的孪生形状：`coverage_doc` 非空 ⇒ `status == "reported"`，
    而 `error` 字段里明明写着异常。修前 `error` **没有任何消费者**，
    只在 JSON 里躺着。⇒ 期望 `missing_anchor:clause_coverage_error`。
    """
    result = _score(building_dir, [_truth_row("i.a", True, [CARD])])
    payload = payload_of(_delivery(
        _coverage_doc(result), error="ValueError: 阅卷器没给出 xxx"))

    assert payload["citable"] is False
    assert "missing_anchor:clause_coverage_error" in payload["citable_reasons"]


def test_s4_near_zero_denominator_is_reported_not_failed(payload_of,
                                                         building_dir):
    """场景④（应过）：分母**接近零**（D=1）是合法的，只须显形，不得判失败。

    分账要说清楚：「零」是证据缺失（不可引），「近零」是人群小（可引但脆弱）。
    把近零也判失败会造出假阻断——本仓记过「判据必须在被筛人群上有意义」。
    ⇒ 期望 `citable=true`，且分母 1 与挂起量原样落盘供人自行判断。
    """
    result = _score(building_dir, [_truth_row("i.a", True, [CARD])])
    payload = payload_of(_delivery(_coverage_doc(result)))

    assert payload["citable"] is True
    assert _item(payload, "5")["denominator"] == 1
    assert _item(payload, "5")["detail"]["pending_item_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# 场景⑤ 同一输出在旧、新分母口径下过门结论是否改变（逐门表列）
# ══════════════════════════════════════════════════════════════════════


def test_s5_hardness_table_is_frozen(payload_of, building_dir):
    """场景⑤（应过）：逐门冻结「硬/软」与「消不消费真值分母」两栏。

    | 门 | 名称 | 硬度 | 消费真值分母？ |
    |---|---|---|---|
    | A | 报告可读性 | hard | 否 |
    | 1 | 跑批完成度 | hard | 否 |
    | 2 | 卡包契约 | hard | 否 |
    | 3 | 归因守恒 | hard | 否 |
    | 4 | 在险真值项 | hard | 否（消费真值，但分母是**在险清单**不是三态分母）|
    | 5 | 验收③ 条款覆盖 | **soft** | **是（唯一一个）** |
    | 6 | 真值建模缺口断言 | soft | 否 |
    | 7 | 跨批可复现 | soft_optional | 否 |

    ⇒ 这就是场景⑤ 的结构性答案：**三态分母只喂第 5 项，而第 5 项是软项**，
    故分母怎么变都改不了退出码。会变的只有 `citable`（证据闭合与否）。
    把第 5 项改成硬项 ⇒ 本测试红：那是把「研究结论」升格成「过门判据」，
    与脚本自述「过门与否是研究结论，不该让一条命令替你宣布」冲突。
    """
    result = _score(building_dir, [_truth_row("i.a", True, [CARD])])
    payload = payload_of(_delivery(_coverage_doc(result)))
    table = {i["item_id"]: i["hardness"] for i in payload["items"]}

    assert table == {
        "A": "hard", "1": "hard", "2": "hard", "3": "hard", "4": "hard",
        "5": "soft", "6": "soft", "7": "soft_optional",
    }
    # 唯一消费三态分母的门：第 5 项。其余门的分母与真值三态无关。
    assert _item(payload, "5")["denominator"] == result["applicable_item_count"]
    assert _item(payload, "4")["denominator"] == 3          # 在险清单在批数
    assert _item(payload, "3")["denominator"] == 1          # 栋数
    assert _item(payload, "1")["denominator"] == 1          # 计划栋数


def test_s5_same_output_under_old_and_new_caliber_keeps_hard_verdicts(
        payload_of, building_dir):
    """场景⑤（应过）：同一份系统输出，旧口径（二态）与新口径（三态）并排。

    **预期（开跑前写死）**：
    | 项 | 旧口径 | 新口径 | 变？ |
    |---|---|---|---|
    | 硬项 A/1/2/3/4 状态 | 全 passed/not_applicable | 同 | **否** |
    | 退出码相关的 `hard_fail` | 空 | 空 | **否** |
    | 第 5 项分母 | 3（第三态被计进 D）| 1 | 是（软项）|
    | 第 5 项召回 | 0.3333 | 1.0 | 是（软项）|
    | `citable` | **false** | true | **是** |

    最后一行是本门有意造成的**结论改变**，须写明理由：旧口径产物没有
    `pending_item_count`，无法判断它的分母是「人群小」还是「第三态被吞」
    ⇒ 按 fail-loud 不予认证。**这不是回归，是拒绝给不可核的数字盖章。**
    """
    rows_new = [_truth_row("i.a", True, [CARD]),
                _truth_row("i.b", PENDING, []),
                _truth_row("i.c", PENDING, [])]
    new_result = _score(building_dir, rows_new)
    # 旧口径重演：#25 之前第三态被 Python 真值判断当成「适用」计进 D。
    old_result = _score(building_dir, [
        _truth_row("i.a", True, [CARD]),
        _truth_row("i.b", True, []),
        _truth_row("i.c", True, []),
    ])
    old_doc = _coverage_doc(old_result, drop_keys=("pending_item_count",))
    old_doc.pop("truth_applicable_state_counts")

    payload_old = payload_of(_delivery(old_doc))
    payload_new = payload_of(_delivery(_coverage_doc(new_result)))
    hard_old = {i["item_id"]: i["status"] for i in payload_old["items"]
                if i["hardness"] == "hard"}
    hard_new = {i["item_id"]: i["status"] for i in payload_new["items"]
                if i["hardness"] == "hard"}

    assert hard_old == hard_new
    assert [r for r in payload_old["citable_reasons"]
            if r.startswith("hard_item_failed")] == []
    assert [r for r in payload_new["citable_reasons"]
            if r.startswith("hard_item_failed")] == []
    assert _item(payload_old, "5")["denominator"] == 3
    assert _item(payload_new, "5")["denominator"] == 1


def test_s5_old_caliber_product_loses_citability_by_design(payload_of,
                                                           building_dir):
    """场景⑤（应拒）：旧口径产物在新契约下**不可引**——这条是有意的结论改变。

    单列一条是因为它是本次门限契约唯一**改变既有结论**的地方：
    2026-08-06 之前，一份没有挂起量字段的覆盖文档照样能得 `citable=true`。
    改动后它拿不到认证。⇒ 换池批之前跑的旧批若要再引用，必须用当期阅卷器重跑。
    """
    old_result = _score(building_dir, [_truth_row("i.a", True, [CARD])])
    old_doc = _coverage_doc(old_result, drop_keys=("pending_item_count",))
    old_doc.pop("truth_applicable_state_counts")
    payload = payload_of(_delivery(old_doc))

    assert payload["citable"] is False
    assert payload["citable_reasons"] == [
        "missing_anchor:clause_coverage_pending_visibility"]


# ══════════════════════════════════════════════════════════════════════
# 随分母漂移会静默错判的判据：源码级锁
# ══════════════════════════════════════════════════════════════════════


def _code_constants(path: Path) -> tuple[set[str], set[int]]:
    """取源码里**真正参与运算**的常量：排除 docstring，注释天然不在 AST 里。

    这样「文档里写历史值 443/149 作为沿革」不会误红，而「判据里写死 443」会红。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    strings: set[str] = set()
    integers: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in docstrings:
            if isinstance(node.value, str):
                strings.add(node.value)
            elif isinstance(node.value, int) and not isinstance(node.value, bool):
                integers.add(node.value)
    return strings, integers


def test_no_hardcoded_population_constants_in_gate_code():
    """（应过）验收总闸的代码里不得出现人群计数常量。

    实测抓到过两处（2026-08-06 修）：
    - 第 4 项文案硬编码 `"8/8 仍被承接"`——在险清单会长、批作用域会变，
      这行字与 `delivery["4"]` 的真实计数是两个数；
    - 批尾守恒把可重算字段数硬编码成 `8`，与 `comparable_fields` 元组长度两处。

    被禁的整数是**分母类**人群计数（真值三态、精确率侧、批 I 召回分母）。
    小整数（0/1/2/索引）不在禁列——判据要在被筛人群上有意义，
    禁一切整数等于这条闸永远命中，没有判别力。
    """
    strings, integers = _code_constants(
        Path(acceptance.__file__))

    assert not [s for s in strings if "8/8" in s], (
        "第 4 项的通过文案又被写死了：在险清单与批作用域都会变，"
        "硬编码那一刻起这行字就与真实计数脱钩。"
    )
    forbidden = {443, 149, 423, 134, 2324, 2340, 2343, 2770}
    assert not (integers & forbidden), (
        f"门限代码里出现了人群计数常量 {sorted(integers & forbidden)}——"
        "这些数是真值文件自身的属性，每次真值落改都会变。"
    )


def test_conservation_denominator_is_derived_not_literal(tmp_path):
    """（应过）批尾守恒的分母 ＝ 可重算字段元组的长度，不是字面量 8。

    变异验证：往 `comparable_fields` 里加一个字段而分母仍报 8 ⇒ 新字段
    不进分母、失配不显形。本条把「两处」压成「一处」。
    """
    import inspect

    source = inspect.getsource(acceptance._batch_tail_conservation)
    assert '"denominator": len(comparable_fields)' in source, (
        "分母又被写成字面量了：它必须由 `comparable_fields` 的长度算出，"
        "否则加字段时分母不跟着走、新字段的失配不显形。"
    )

    # 行为面：分母 == 源码里那个元组的真实长度（从 AST 数，不抄字面量）。
    tree = ast.parse(source.lstrip())
    tuples = [node for node in ast.walk(tree)
              if isinstance(node, ast.Tuple)
              and node.elts
              and isinstance(node.elts[0], ast.Constant)
              and node.elts[0].value == "report_count"]
    assert len(tuples) == 1
    expected_fields = len(tuples[0].elts)

    (tmp_path / "batch_summary.json").write_text("{}", encoding="utf-8")
    checks, _, _ = acceptance._batch_tail_conservation(tmp_path, {})
    recompute = next(c for c in checks
                     if c["check_id"] == "summary_recomputed_from_buildings")

    assert recompute["denominator"] == expected_fields
