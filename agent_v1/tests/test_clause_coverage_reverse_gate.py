"""反向闸（精确率侧）判据的口径锁定（2026-07-30）。

## 为什么改

`_check_structural_exclusion` 量的是「真值说**不适用**、系统却评了」——
验收③ 的另一侧（前面所有工作都在「漏」，这一侧是「不该评的乱评了没有」）。

旧判据含 `applicability_state == "applicable"`，而该字段占全部义务的绝大多数
⇒ **判据里出现占比 >90% 的字段等于没这个条件**。实测 **399/443 = 90.1%** 报 anomaly
（**落改前口径**，见下方「数字口径」），近饱和、几无分辨力。

而按**判定权红线**，`applicability_state` **不是判定**（判定是
`satisfaction_status`/`closure_status`）⇒「进了作用域但没下判定」**不构成误评**。
修正判据：**误评 = 对真值说不适用的项下了非簿记的实质判定**。
实测 **149/443 = 33.6%**（**落改前口径**），250 项翻转。

## ⚠️ 数字口径：443／149 是**落改前**的历史值，已作废

本 docstring 里的 `399/443`、`149/443`、`399→149` 全部是
**2026-07-30 实测、2026-08-05 #25 真值落改前的口径**。落改后：
分母 `443 → 423`（`applicable=false` 行转出 20 行）、误评 `149 → 134`。
**分母不是常数**——它是真值文件自身的属性，随每次真值落改变化，
**别把它当常数引**（#25 审核门必须修 4）。本文件的断言**不依赖**这两个数
（锁的是判据形状与「两个都报」，不是具体计数），故沿用历史值只作沿革说明。

## 🔴 锁的三条

1. **两个判据都报、不替换。** 修正后数字**变小**（399→149，落改前口径），
   让数字变小的改动尤其必须并排——否则无法与「调判据让指标好看」区分。
   旧数必须可还原：`anomaly + legacy_anomaly == 旧 anomaly`。
2. **判据不许再引入占比 >90% 的字段。** 这是本次病灶本身，做成源码级断言。
3. **本函数不进过门/召回**（docstring 明写「不进 D/E」）——
   实测轨一与轨二在本次改动前后**逐位不变**。

## 变异验证（写测试时实跑过）

- 把 `substantive` 的 `not _is_bookkeeping(o)` 删掉 ⇒ `test_bookkeeping_is_not_mis_evaluation` 失败
- 把 `applicability_state` 加回 `substantive` ⇒ `test_criterion_has_no_saturated_field` 失败
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

BUNDLE_ITEM = {
    "normative_item_id": "mbis.test.notapplicable",
    "source_clause_id": "X",
    "scope_type": "building",
    "scope_id": "BLD-1",
    "applicable": False,
    "expected_card_ids": ["rc.a"],
}


def _o(**kw) -> dict:
    base = {"source_rule_card_id": "rc.a", "kind": "action", "scope_type": "building",
            "satisfaction_status": "unknown", "closure_status": "open"}
    base.update(kw)
    return base


def test_substantive_verdict_on_a_not_applicable_item_is_mis_evaluation() -> None:
    got = scorer._check_structural_exclusion(
        BUNDLE_ITEM, [_o(satisfaction_status="violated")], {})
    assert got == "anomaly_false_item_evaluated"


def test_applicable_label_alone_is_not_mis_evaluation() -> None:
    """只贴了 applicable 标签、没下判定 ⇒ 不是误评（但旧判据会报，故落 legacy 桶）。"""
    got = scorer._check_structural_exclusion(
        BUNDLE_ITEM, [_o(applicability_state="applicable")], {})
    assert got == "excluded_consistent_legacy_anomaly"


def test_bookkeeping_is_not_mis_evaluation() -> None:
    """簿记行**带确定判定**也不算误评——本项目已四处发现簿记行冒充实质证据。

    🔴 夹具必须让簿记行**真的带 satisfied/violated**，否则这条测试是空的：
    首版我写了 `satisfaction_status="not_applicable"`，那本来就不在
    `(satisfied, violated)` 里 ⇒ 删掉簿记过滤器测试照样过（变异验证当场暴露）。
    """
    row = _o(kind="scope", satisfaction_status="satisfied",
             applicability_state="not_applicable")
    assert scorer._is_bookkeeping(row), "夹具本身不是簿记行，这条测试就没测到东西"
    got = scorer._check_structural_exclusion(BUNDLE_ITEM, [row], {})
    assert got != "anomaly_false_item_evaluated"


def test_clean_exclusion_stays_clean() -> None:
    assert scorer._check_structural_exclusion(BUNDLE_ITEM, [], {}) == "excluded_consistent"


def test_old_count_is_recoverable() -> None:
    """旧 anomaly 必须可还原 = 新 anomaly + legacy_anomaly。

    这条保证「数字变小」不是把项目丢掉，而是重新分桶。
    """
    cases = [
        [_o(satisfaction_status="violated")],                    # 新旧都报
        [_o(applicability_state="applicable")],                  # 只旧报
        [],                                                      # 都不报
    ]
    outs = [scorer._check_structural_exclusion(BUNDLE_ITEM, c, {}) for c in cases]
    new_anom = sum(o == "anomaly_false_item_evaluated" for o in outs)
    legacy_only = sum(o == "excluded_consistent_legacy_anomaly" for o in outs)
    assert new_anom == 1 and legacy_only == 1          # 旧 anomaly 应为 2
    assert new_anom + legacy_only == 2


def test_criterion_has_no_saturated_field() -> None:
    """🔴 新判据不许再引入 `applicability_state`——那正是本次的病灶。

    源码级断言：`substantive` 那个列表推导里不得出现该字段。
    （`legacy` 里出现是对的，它就是为了还原旧数。）
    """
    src = inspect.getsource(scorer._check_structural_exclusion)
    # 只看 `substantive = [ ... ]` 这一个列表推导的**代码**，不含上方注释——
    # 首版没收窄，结果断言抓到的是我自己注释里提的那个字段名（测试自身的 bug）。
    _, _, after = src.partition("substantive = [")
    body, _, rest = after.partition("]")
    assert "applicability_state" not in body, \
        f"新判据里出现了近饱和字段 applicability_state：{body!r}"
    assert "_is_bookkeeping" in body, "新判据丢了簿记剔除"
    assert "applicability_state" in rest, "legacy 判据丢了，旧数无法还原"
