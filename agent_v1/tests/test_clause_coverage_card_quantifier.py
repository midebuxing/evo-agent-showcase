"""期望卡量词 `--card-quantifier` 的口径锁定（2026-07-29 立）。

## 为什么有这个测试

阅卷器一直把真值的 `expected_card_ids` 当 **OR**：任一期望卡产出可评估义务，
整个规范项即算承接。2026-07-29 实测发现，去重后的 43 个多卡规范项里
**40 个各卡是不同义务单元**（收件人 / 文件 / 期限互不相同），只有 1 个是真
替代关系。于是新增 `all` 口径（逐卡分类取最弱态）作**并排观察量**。

🔴 这里锁的**不是**「`all` 更对」——验收标准③ 的措辞是「适用**条款**不漏」，
过门看的就是条款级 `any`。锁的是三条不变量：

1. **缺省等价**：不传参 == 传 `any` == 改动前行为。新能力必须缺省无副作用，
   否则「一个参数悄悄改了过门数字」就是又一次口径静默漂移。
2. **`all` 确实更严**：多卡项里任一卡未被承接 ⇒ 整项不算覆盖。
   若哪天 `all` 的覆盖数反而 ≥ `any`，说明取最弱态的逻辑坏了。
3. **已裁定的替代卡项豁免**：`GENUINE_OR_ITEMS` 里的项在 `all` 下仍按 `any` 判。
   这条防的是「把 §2.1.3(t)『小型工程程序**或**全面審批程序』也拆成 AND」。

## 变异验证（写测试时实跑过）

把 `_classify_item_quantified` 里的 `min` 改成 `max` ⇒ 断言 2 失败；
把 `GENUINE_OR_ITEMS` 判断删掉 ⇒ 断言 3 失败。两条都不是恒真断言。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

BUNDLE = {"rc.a", "rc.b"}
FRAG_COMP: dict[str, str] = {}


def _item(item_id: str, cards: list[str]) -> dict:
    return {
        "normative_item_id": item_id,
        "source_clause_id": "X.Y",
        "scope_type": "building",
        "scope_id": None,
        "applicable": True,
        "expected_card_ids": cards,
    }


def _obl(card: str, status: str) -> dict:
    """造一条**非簿记**的义务行：楼级项会剔掉簿记行，所以 kind 不能是 scope/artifact。"""
    return {
        "source_rule_card_id": card,
        "kind": "action",
        "satisfaction_status": status,
        "closure_status": "closed" if status in ("satisfied", "violated") else "open",
        "trigger_state": "active",
        "scope_type": "building",
    }


def test_any_is_the_default_and_unchanged() -> None:
    """不传参 == 传 any：缺省不改行为。"""
    item = _item("mbis.test.two_cards", ["rc.a", "rc.b"])
    obls = [_obl("rc.a", "satisfied")]          # 只有 A 有确定判定
    baseline = scorer._classify_item(item, obls, BUNDLE, BUNDLE, FRAG_COMP)
    default = scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "any")
    assert default == baseline == "evaluated_determinate"


def test_all_takes_the_weakest_card() -> None:
    """A 卡已确定、B 卡毫无记录 ⇒ all 口径下整项不算「已确定」。"""
    item = _item("mbis.test.two_cards", ["rc.a", "rc.b"])
    obls = [_obl("rc.a", "satisfied")]
    strict = scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "all")
    assert strict != "evaluated_determinate"
    assert scorer._STATE_STRENGTH[strict] < scorer._STATE_STRENGTH["evaluated_determinate"]
    assert strict not in scorer.COVERED_STATES


def test_all_agrees_with_any_when_every_card_is_determinate() -> None:
    """两张卡都有确定判定 ⇒ 两口径同解（`all` 不是无条件降级）。"""
    item = _item("mbis.test.two_cards", ["rc.a", "rc.b"])
    obls = [_obl("rc.a", "satisfied"), _obl("rc.b", "violated")]
    loose = scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "any")
    strict = scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "all")
    assert loose == strict == "evaluated_determinate"


def test_genuine_or_item_is_exempt_from_all() -> None:
    """已裁定为替代卡的项，在 all 口径下仍按 any 判。"""
    genuine = next(iter(scorer.GENUINE_OR_ITEMS))
    item = _item(genuine, ["rc.a", "rc.b"])
    obls = [_obl("rc.a", "satisfied")]           # 同上，只有 A 有记录
    strict = scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "all")
    assert strict == "evaluated_determinate"


def test_single_card_item_is_identical_under_both() -> None:
    """单卡项不受量词影响——多卡才有 AND/OR 之分。"""
    item = _item("mbis.test.one_card", ["rc.a"])
    obls = [_obl("rc.a", "satisfied")]
    assert (scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "any")
            == scorer._classify_item_quantified(item, obls, BUNDLE, BUNDLE, FRAG_COMP, "all"))


def test_card_groups_are_and_across_groups_or_within() -> None:
    """卡组：组间 AND、组内 OR。

    造一个三卡项、分两组 [{a}, {b, c}]：
      - b 已确定、c 无记录 ⇒ 第二组仍算已确定（组内 OR）
      - a 无记录          ⇒ 整项落到第一组的弱态（组间 AND）
    """
    item_id = "mbis.test.grouped"
    bundle = {"rc.a", "rc.b", "rc.c"}
    item = _item(item_id, ["rc.a", "rc.b", "rc.c"])
    scorer.CARD_GROUPS[item_id] = (frozenset({"rc.a"}), frozenset({"rc.b", "rc.c"}))
    try:
        # 只有 b 有确定判定：组内 OR 让第二组过关，但第一组（a）没记录 ⇒ 整项不覆盖
        got = scorer._classify_item_quantified(
            item, [_obl("rc.b", "satisfied")], bundle, bundle, FRAG_COMP, "all")
        assert got not in scorer.COVERED_STATES

        # a 也有了确定判定 ⇒ 两组都过 ⇒ 整项已确定；注意 c 始终没记录，
        # 若组内被误当 AND，这里会失败。
        got2 = scorer._classify_item_quantified(
            item, [_obl("rc.a", "satisfied"), _obl("rc.b", "satisfied")],
            bundle, bundle, FRAG_COMP, "all")
        assert got2 == "evaluated_determinate"
    finally:
        scorer.CARD_GROUPS.pop(item_id, None)


def test_registered_card_groups_resolve_against_the_real_bundle() -> None:
    """登记的卡组必须在真卡包里解析得出成员——防「登记了但卡 ID 打错，静默退化成逐卡 AND」。

    这条是必要的：`_register_card_groups` 用后缀匹配建组，打错一个字符不会报错，
    只会得到空集合，然后 `live` 过滤把它丢掉、悄悄退回扁平 AND。
    """
    import json as _json
    from pathlib import Path as _Path
    bundle_path = (_Path(__file__).resolve().parents[1]
                   / "regulations/rulecard_v2/mbis_cop_2023/rule_cards.json")
    real = {c["rule_card_id"]
            for c in _json.loads(bundle_path.read_text(encoding="utf-8"))["cards"]}
    scorer.CARD_GROUPS.clear()
    scorer._register_card_groups(real)
    assert scorer.CARD_GROUPS, "卡组登记表为空"
    for item_id, groups in scorer.CARD_GROUPS.items():
        assert groups, f"{item_id} 没有任何组"
        for i, g in enumerate(groups):
            assert g, f"{item_id} 第 {i} 组在真卡包里解析为空——卡 ID 后缀可能打错了"
            assert g <= real, f"{item_id} 第 {i} 组含卡包外的 ID"
