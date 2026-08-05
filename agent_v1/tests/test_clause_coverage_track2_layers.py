"""轨二「冻结可判定契约」分层的口径锁定（预注册 2026-07-30）。

权威文档：`团队文档/我的笔记/预注册_验收3双轨判据_20260730.md`
依据：grok / codex / PlusAI Pro **三家独立商议收敛到同一设计**。

## 为什么有轨二

原判据「每栋 missed_applicable_item_count == 0」**同时在考四件事**：
法规有没有进卡包 / 世界有没有生成场景 / 条款存在但触发条件在当前快照为假 /
**验证器有没有静默丢掉本该求值的义务**。压成一个数的后果已实测：
召回 0.7530→0.7767（漏 574→519），**过门 0/10 纹丝不动**——它无法分辨版本进步。

轨二只问一件事：**事前声明为「卡在、世界资产在、当前快照可求值」的义务，
验证器有没有静默丢掉？** 判据：每栋 L3 层漏项 == 0。
实测（批 `phase_i_fragcov2_seed301_20260729`）：
L0 30 / L1 189 / L2 296 / **L3 4**，回收 519 = 轨一漏组；轨二过门 **6/10**。

## 🔴 这里锁的五条，每条都对应一个「会把轨二变成刷分装置」的失效

1. **轨一不受影响**：轨二只读、只分账；轨一的 `covered_count` / `missed_...` /
   `gate_pass` 一个字节不动。
2. **严格回收**：四层之和必须等于轨一漏组数。少一条就是静默丢项——
   而「静默丢项」正是轨二要测的东西，它自己绝不能犯。
3. **只由资产存在性定层**：判据里**不许出现** `satisfaction_status` /
   `closure_status`。否则就成了「系统做对的算一层、做错的算另一层」，即自己划考试范围。
4. **组级取最靠近验证器责任的那层**（L3 > L2 > L1 > L0）：一组里只要有一条
   「本该可判定却漏了」，整组算验证器的账。偏保守，防止用一条 L1 把 L3 洗掉。
5. **L2 文案固定**：不得被解释成「不适用」或「窗口未开放」——那是三家一致
   否决的语义偷渡（我为此否掉过一个 +9.4 点的改法）。

## 变异验证（**逐条实跑，锚点与失败测试名都已核对**）

| 变异 | 失败的测试 |
|---|---|
| `_STATE_TO_LAYER` 里 `not_modeled` 改指 L3 | `test_no_card_is_L0` ✅ |
| `_has_inactive_trigger` 恒返回 False | `test_inactive_trigger_is_L2` ✅ |
| **生产** `_group_gate_layer` 的 `max` 改 `min` | `test_group_takes_the_most_system_responsible_layer` ✅ |
| **生产**分层时让 `L1_no_world_asset` 漏计 | `test_layers_must_reconcile_to_track1` ✅ |

## 🔴 这份 docstring 曾经写过两条假的验证声明（codex 审核门 2026-07-30 抓出）

1. 声称「删掉回收断言 ⇒ `test_layers_must_reconcile_to_track1` 失败」，
   而**那个测试函数当时根本不存在**——只在 docstring 里出现过它的名字。
2. 声称「组级 `max→min` ⇒ 该测试失败」，而那条测试**一次都没调生产函数**，
   它在对自己造的 list 调 `max`；改生产代码它照样通过。

**假的验证声明比没写测试更糟**——它让后来的人以为这里有保障。
两条都已修：组级逻辑提成 `_group_gate_layer` 让测试能直接喂生产路径；
回收测试真写出来并跑 `score_building`。

**另一条修正**：「删掉断言」不是验证回收的正确变异（测试自己算和比对，
删掉生产断言不制造不一致）。正确变异是**让某一层漏计**，已实测会失败。
⇒ 教训：**写变异说明时，变异必须是「能破坏被断言的性质」的那一个，
不是「删掉断言语句」。**
"""
from __future__ import annotations

import pathlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

BUNDLE = {"rc.a", "rc.b"}


def _item(scope_type: str = "building", cards=("rc.a",), scope_id: str = "BLD-1") -> dict:
    return {
        "normative_item_id": "mbis.test.item",
        "source_clause_id": "X",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "applicable": True,
        "expected_card_ids": list(cards),
    }


def _obl(card: str = "rc.a", trigger_state: str | None = None, kind: str = "action") -> dict:
    o = {"source_rule_card_id": card, "kind": kind, "scope_type": "building",
         "satisfaction_status": "unknown", "closure_status": "open"}
    if trigger_state:
        o["trigger_state"] = trigger_state
    return o


def test_no_card_is_L0() -> None:
    """期望卡不在卡包 ⇒ 法规表示层缺口，不进轨二分母。"""
    assert scorer._gate_layer(_item(), "not_modeled", [], BUNDLE, {}) == "L0_no_card"


def test_no_world_asset_is_L1() -> None:
    """本栋无该类片段 ⇒ 供给侧，不进轨二分母。"""
    for state in ("supply_side_no_fragment_of_class", "structural_na_no_such_fragment"):
        assert scorer._gate_layer(_item(), state, [], BUNDLE, {}) == "L1_no_world_asset"


def test_inactive_trigger_is_L2() -> None:
    """留下了「触发条件求值为假」的承接记录 ⇒ L2，不进轨二分母。"""
    obls = [_obl(trigger_state="inactive")]
    got = scorer._gate_layer(_item(), "retrieved_no_evaluation", obls, BUNDLE, {})
    assert got == "L2_trigger_false"


def test_silent_drop_is_L3() -> None:
    """卡在、资产在、却连「触发为假」的记录都没留 ⇒ 验证器静默丢掉，进轨二分母。"""
    obls = [_obl(trigger_state="not_evaluated")]
    got = scorer._gate_layer(_item(), "retrieved_no_evaluation", obls, BUNDLE, {})
    assert got == "L3_decidable"


def test_wrong_structural_na_is_L3() -> None:
    """结构早退误杀是验证器自己的账——这个状态存在的唯一理由就是量它。"""
    assert scorer._gate_layer(_item(), "wrong_structural_na", [], BUNDLE, {}) == "L3_decidable"


def test_layer_predicate_never_reads_result_correctness_fields() -> None:
    """🔴 约束 3：定层判据不许读「做对没做对」的字段。

    做法是源码级检查——`_gate_layer` 与 `_has_inactive_trigger` 的函数体里
    不得出现 `satisfaction_status` / `closure_status`。
    这条防的是「系统做对的归一层、做错的归另一层」＝自己划考试范围。
    """
    import inspect
    for fn in (scorer._gate_layer, scorer._has_inactive_trigger):
        src = inspect.getsource(fn)
        for forbidden in ("satisfaction_status", "closure_status"):
            assert forbidden not in src, f"{fn.__name__} 读了结果正确性字段 {forbidden}"


def test_group_takes_the_most_system_responsible_layer() -> None:
    """组级取 L3 > L2 > L1 > L0——一条 L1 不许把同组的 L3 洗掉。

    🔴 **必须调生产函数 `_group_gate_layer`**。此前这条测试对自己造的 list 调 `max`，
    codex 审核门实测指出：把生产代码的 `max` 改成 `min`，它照样通过
    ⇒ 那是**假的变异验证**。现在改成直接喂生产路径。
    """
    item = _item(scope_type="component_class", cards=("rc.a",), scope_id="curtain_wall")
    # 两行漏项：一行会定成 L1（本栋无该类片段）、一行定成 L3（结构早退误杀）
    rows = [{"state": "supply_side_no_fragment_of_class", "is_missed": True},
            {"state": "wrong_structural_na", "is_missed": True},
            {"state": "evaluated_determinate", "is_missed": False}]
    got = scorer._group_gate_layer(item, rows, [], BUNDLE, {"FRG-1": "external_wall"})
    assert got == "L3_decidable", f"组级没取最靠近验证器责任的层，得到 {got}"
    # 反向：全是 L1 时不许升成 L3
    only_l1 = [{"state": "supply_side_no_fragment_of_class", "is_missed": True}]
    assert scorer._group_gate_layer(item, only_l1, [], BUNDLE,
                                    {"FRG-1": "external_wall"}) == "L1_no_world_asset"


def test_layers_must_reconcile_to_track1() -> None:
    """🔴 四层必须严格回收到轨一漏组数——这条此前**只在 docstring 里声称验证过，
    测试函数根本不存在**（codex 审核门抓出）。现在真写出来：
    直接跑 `score_building` 的分层段，核 `sum(gate_layer_counts) == 漏组数`。

    造一栋合成楼：3 个规范项，两个漏（不同层）、一个覆盖。
    """
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        bdir = pathlib.Path(td) / "BLD-T"
        run = bdir / "runs" / "r1"
        run.mkdir(parents=True)
        (run / "rule_slice.json").write_text(
            _json.dumps({"candidate_rule_cards": [{"rule_card_id": "rc.a"}]}),
            encoding="utf-8")
        (run / "obligation_set.json").write_text(
            _json.dumps({"obligations": [_obl("rc.a", trigger_state="inactive")]}),
            encoding="utf-8")
        (run / "fact_pack.json").write_text(
            _json.dumps({"facts": [{"carrier_type": "fragment", "carrier_id": "FRG-1",
                                    "qualifiers": {"component_type_key": "external_wall",
                                                   "fragment_id": "FRG-1"}}]}),
            encoding="utf-8")
        items = [
            # ① 期望卡不在卡包 ⇒ L0
            {**_item(cards=("rc.zzz",)), "normative_item_id": "it.l0"},
            # ② 构件类本栋无片段 ⇒ L1
            {**_item(scope_type="component_class", cards=("rc.a",), scope_id="curtain_wall"),
             "normative_item_id": "it.l1"},
        ]
        res = scorer.score_building(bdir, items, BUNDLE)
        lay = res.get("gate_layer_counts") or {}
        assert sum(lay.values()) == res["missed_applicable_item_count"], (
            f"分层未回收：{lay} 合计 {sum(lay.values())}"
            f" ≠ 漏组 {res['missed_applicable_item_count']}")
        assert lay.get("L0_no_card", 0) >= 1 and lay.get("L1_no_world_asset", 0) >= 1, lay


def test_l2_wording_does_not_adjudicate_legal_state() -> None:
    """🔴 约束 5：L2 文案不得被解释成「不适用」或「窗口未开放」。"""
    w = scorer.L2_RECORD_WORDING
    assert "不裁定" in w and "也不证明" in w
    assert "窗口" in w          # 明确点名它**不**证明窗口未开放
    # 反向：不许出现把它说成正确不适用的措辞
    assert "正确判定不适用" not in w


def test_all_layers_are_registered() -> None:
    """四层必须都在 GATE_LAYERS 里——新增层却忘登记会让回收断言算错。"""
    assert set(scorer.GATE_LAYERS) == {
        "L0_no_card", "L1_no_world_asset", "L2_trigger_false", "L3_decidable"}
    assert set(scorer._STATE_TO_LAYER.values()) <= set(scorer.GATE_LAYERS)


def test_every_missed_state_maps_to_some_layer() -> None:
    """任何漏态都必须能定层——不许有落不进四层的漏项（回收断言的前提）。"""
    for state in scorer.MISSED_STATES:
        got = scorer._gate_layer(_item(), state, [], BUNDLE, {})
        assert got in scorer.GATE_LAYERS, f"{state} 定不了层"
