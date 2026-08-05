"""内容失真审计器的行为锁定(DEBT-071)。

两条断言直接对应我**自己抽验抓到的两个假阳源**——审计器首版报 130 条，挤完剩 27 条，
**79% 是假阳**。教训同 `feedback_green_tests_hide_broken_wiring` 第 ⑦ 条:
**测量脚本本身要先自证**，否则拿假阳去"修"本来正确的卡（本项目已因此翻车过一次）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_rulecard_content_fidelity as fid  # noqa: E402


def test_page_markers_are_not_content_numbers():
    """🔴 假阳源一:`<!-- page: 24 -->` 的 24 被当成条款内容里的数量。

    实证:首版报 §3.3.2(J)(c)「缺 24」、§3.4.2(B)(e)「缺 28」——两个都是页码标记。
    """
    assert 24 not in fid.numbers_cn("檢驗至少30%的外牆面積。\n<!-- page: 24 -->\n")
    assert 30 in fid.numbers_cn("檢驗至少30%的外牆面積。\n<!-- page: 24 -->\n")


def test_clause_cross_references_are_not_content_numbers():
    """条款交叉引用（「根據第4.3.3及4.3.4節」）不是数量。"""
    nums = fid.numbers_cn("並考慮現場所得的資料，根據第4.3.3及4.3.4節進行評估")
    assert not ({3, 4} & nums), f"条款号被当成数量:{nums}"


def test_form_codes_are_not_content_numbers():
    """表格代号 MBI3 / MBI3a 里的 3 不是数量，两侧都要剔。"""
    assert 3 not in fid.numbers_cn("呈交MBI3或MBI3a表格")
    assert 3 not in fid.numbers_en("submit the MBI3 or MBI3a certificate")
    assert 7 in fid.numbers_en("within 7 days after completion")


def test_findings_are_aggregated_per_clause_not_per_card():
    """🔴 假阳源二:一个条款常由**多张卡分摊**，按单卡判必然假阳。

    实证 §3.4.2(B)(e):原文「檢查位置不可少於**兩個**，或在簷篷每隔**六米**的長度便有
    **一個**」被拆成两张卡，卡 A 只带 2、卡 B 只带 1 和 6，按单卡判两张都"缺数字"，
    **合起来其实是全的**。问的是"卡集合有没有丢内容"，不是"每张卡是否完整"。
    """
    import inspect
    src = inspect.getsource(fid.main)
    assert "per_section" in src, "必须按条款聚合"
    assert "数字缺失(条款级)" in src, "发现项须标明是条款级口径"


def test_audit_declares_its_own_limitation():
    """审计器必须自陈:只查数字与枚举项数两类机械信号，查不到「动作被换掉」。"""
    import inspect
    src = inspect.getsource(fid.main)
    assert "下界" in src, "须显式声明报出的数是下界"
    assert "禁静默丢弃" in src, "未覆盖项必须报出原因"


def test_chinese_numerals_with_measure_words():
    """中文数字要带量词才算数量——否则「第一」「二者」之类会误抓。"""
    assert 6 in fid.numbers_cn("在簷篷每隔六米的長度便有一個")
    assert 2 in fid.numbers_cn("檢查位置不可少於兩個")


def test_demonstrative_chinese_numeral_is_not_a_quantity():
    """🔴 第二十类假阳:「下**一個**檢驗周期」的「一個」是**指示词**不是数量。

    取数子代理指认——它看不到我的代码，只是发现「§5.5.4 队列标了数字 1，而中文原文里
    找不到任何对应来源」，我复核坐实。这是同一形状的第 N 次:**代理靠"对不上"报警，
    比我自查可靠，因为我只会查我以为会错的地方。**
    """
    assert fid.numbers_cn("維持至下一個檢驗周期") == set()
    assert fid.numbers_cn("每一次檢驗") == set()
    assert fid.numbers_cn("另一個位置") == set()
    # 真数量不得被误剔
    assert 2 in fid.numbers_cn("檢查位置不可少於兩個")
    assert 6 in fid.numbers_cn("在簷篷每隔六米的長度便有一個")


def test_decimal_quantities_are_captured_not_eaten_as_section_numbers():
    """🔴 第二十一类:小数量值被当条款号吃掉，而平方指数反被当成数量。

    取数子代理指认——它发现「§5.6.5 水测试的 **1.5 米** 水压没进自动抽取清单，
    是靠逐字读中文才补上的」。复核坐实两个方向都坏:
      `須維持1.5米水壓`   → 空集   （1.5 被 `\d+(?:\.\d+)+` 当条款号剔掉）
      `應力須不小於0.5N/mm2` → {2}  （0.5 被剔，却把 mm² 的平方指数 2 抓成数量）
    判据:**两个及以上小数点**必是条款号；**单个小数点**看后面跟不跟量词。
    """
    assert 1.5 in fid.numbers_cn("須維持1.5米水壓")
    assert fid.numbers_cn("應力須不小於 0.5N/mm2") == {0.5}, "平方指数被当成了数量"
    # 条款号仍须剔掉
    assert fid.numbers_cn("根據第4.3.3及4.3.4節進行評估") == set()
    # 整数不受影响
    assert {1, 25} <= fid.numbers_cn("每 25 平方米進行一個測試")
