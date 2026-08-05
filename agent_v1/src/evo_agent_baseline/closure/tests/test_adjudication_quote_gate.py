"""裁定引文校验闸自身的变异测试（2026-08-03 立）。

## 为什么这个闸需要自己的测试

`agent_v1/scripts/verify_adjudication_quotes.py` 是把外包裁定的「依据」那一句
逐条核回中文法规原文的闸。**裁定的全部证据力都压在那一句上**——
如果它是转述、翻译、截断或杜撰，整条裁定就没有依据，
而那正是本轮要修的病（拿不成立的依据下结论）本身。

## 🔴 这个闸被放宽过一次，所以必须有变异测试

它首版把「依据」行里**所有** `「」` 段一律按依据判，于是把括号里的
补充说明（「另 App8 2(e) 引出句为…」「各项均为 X/Y/Z 等行为」）也标红了
——**误报**：那两条的主依据其实逐字且已通过。
我据此把判据放宽成「只判第一段（主依据），后续段只提示」。

**在闸报红之后放宽闸，是本项目明确警告过的危险动作**
（[[feedback_dont_dismantle_a_gate_before_reading_its_tests]]、
「绕过闸，再拿绕坏的结果当证据」）。
⇒ 放宽之后**必须证明它还抓得住真问题**，这就是本文件。

## 闸自己也踩过两个坑（都在下面锁住）

1. **脚注标记**：原文 `…建築工程<sup>5</sup>，則…`，去标签后残留数字 `5`
   ⇒ 与去掉脚注的引文恒对不上。修法是连数字一起去 `<sup>\\d+</sup>`，
   **但不能笼统去所有数字**——法规里的数字是阈值。
2. **裸串比对**：不归一化标点/空白会大面积误报。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[5]
GATE = REPO / "agent_v1" / "scripts" / "verify_adjudication_quotes.py"
SRC = REPO / "agent_v1" / "regulations" / "markdown" / "MBIS_CoP_2023.md"

# 取自法规原文的真句（逐字），用作阳性对照。
_REAL = "註冊檢驗人員須妥為簽署完工報告。"
# 原文里带脚注标记那一句——引用时会去掉 `<sup>5</sup>`。
_WITH_FOOTNOTE = (
    "如糾正或修葺工程屬小型工程或豁免審批建築工程，"
    "則工程的展開無須事先獲得建築事務監督的批准及同意。"
)


def _run(tmp_path, body: str):
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    f = tmp_path / "case.md"
    f.write_text(body, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(GATE), str(f)],
        capture_output=True, text=True, encoding="utf-8",
        env={**__import__("os").environ, "PYTHONUTF8": "1"},
    )
    return r.returncode, r.stdout


@pytest.fixture(scope="module", autouse=True)
def _require_source():
    if not SRC.is_file():
        pytest.skip("本环境没有中文法规原文，闸无从校验")


def test_verbatim_quote_passes(tmp_path):
    """阳性对照：逐字原文必须放行。闸若连真句都拦，它就没法用。"""
    code, out = _run(tmp_path, f"3. 依据：「{_REAL}」\n")
    assert code == 0, out


def test_footnote_marker_does_not_cause_false_red(tmp_path):
    """原文里嵌 `<sup>5</sup>` 的句子，去掉脚注引用**不算改字**，必须放行。

    这是闸自己踩过的第一个坑：只去标签、把数字 `5` 留下 ⇒ 恒对不上。
    """
    code, out = _run(tmp_path, f"3. 依据：「{_WITH_FOOTNOTE}」\n")
    assert code == 0, out


def test_fabricated_quote_is_caught(tmp_path):
    """杜撰的「原文」必须红——这是闸存在的首要理由。"""
    fake = "註冊檢驗人員須確保所有文件均已妥為存檔並經上級覆核。"
    code, out = _run(tmp_path, f"3. 依据：「{fake}」\n")
    assert code == 1 and "主依据对不上" in out, out


def test_single_character_alteration_is_caught(tmp_path):
    """**改一个字**也必须红（「方法」→「方式」）。

    转写走样和杜撰在后果上没有区别：据以裁定的那句话不是法规说的话。
    """
    altered = "就決定修葺方式而言，註冊檢驗人員須考慮以下幾方面："
    code, out = _run(tmp_path, f"3. 依据：「{altered}」\n")
    assert code == 1 and "主依据对不上" in out, out


def test_elided_quote_is_caught(tmp_path):
    """带省略号 ＝ 非逐字引用，必须红。

    ⚠️ 不能靠「逐段验」代替：省略号两侧的残段各自都可能恰好在原文里，
    逐段验会误判成命中。故省略号单独成一档。
    """
    elided = "就修葺工程的記錄而言...須指明各項已完成的工程"
    code, out = _run(tmp_path, f"3. 依据：「{elided}」\n")
    assert code == 1 and "省略号" in out, out


def test_aside_after_a_valid_primary_only_warns(tmp_path):
    """🔴 放宽的那一条：主依据逐字通过时，括号里的补充说明只提示、不判红。

    这是闸被放宽的原因，也是最需要盯住的一条——
    **放宽面必须恰好是「补充说明」，不能顺带放过主依据。**
    下一条测试从反面锁住这一点。
    """
    # 真实文件里的补充说明也是用「」包着的（如「所用物料...的證書及報告」），
    # 所以夹具必须同形——裸写的括号说明不进 `「」` 提取，闸根本看不见（见下一条）。
    body = f"3. 依据：「{_REAL}」（另 App8 2(e) 列举「所用物料...的證書及報告」）\n"
    code, out = _run(tmp_path, body)
    assert code == 0, out
    assert "补充说明非逐字" in out, "补充说明应当被提示出来，而不是静默吞掉"


def test_unquoted_aside_is_invisible_to_the_gate(tmp_path):
    """边界（不是缺陷，但要写下来）：**没被 `「」` 包住的文字闸看不见。**

    闸的射程是「被当作引文声称的东西」。裸写的说明性文字不声称自己是原文，
    故不进校验——但也因此**不能靠这个闸挡住「用大白话转述法规当依据」**。
    那要靠工单里「依据必须是逐字原文」这条要求 ＋ 人看。
    """
    body = f"3. 依据：「{_REAL}」（另有 X/Y/Z 等要求，此处不引原文）\n"
    code, out = _run(tmp_path, body)
    assert code == 0, out
    assert "补充说明非逐字" not in out


def test_enumerated_stem_plus_subitem_is_accepted(tmp_path):
    """🔴 合法例外：**引出句 ＋ 分项**，两段在原文里不连续但都真实。

    枚举式条款的分项单摘是**裸名词短语**（「(v) 樓梯」），
    **情态在引出句里**（「檢驗項目須包括以下結構構件：」）
    ——本项目既有教训明确要求引用时带上引出句，否则会拿「无情态」去比「有情态」。
    ⇒ 闸必须容得下这种引法，否则会把**正确的引用实践**判红（实测一次误报 16 条）。
    """
    body = "3. 依据：檢驗項目須包括以下結構構件：(v) 樓梯\n"
    code, out = _run(tmp_path, body)
    assert code == 0, out


def test_short_subitem_must_be_near_its_stem(tmp_path):
    """短分项**不许远距离撞上**——窗口按分项长度缩放。

    「(i) 柱」归一后只有 2 个字，在长文里随便撞上的概率很高。
    若统一放宽到大窗，闸就退化成「原文里任意两句都能拼」。
    本测拿一个**真实存在但不属于该引出句**的短词做变异：必须红。
    """
    real = "3. 依据：檢驗項目須包括以下結構構件：(i) 柱\n"
    far = "3. 依据：檢驗項目須包括以下結構構件：(i) 消防\n"
    assert _run(tmp_path / "a", real)[0] == 0, "真分项被误判红"
    code, out = _run(tmp_path / "b", far)
    assert code == 1 and "主依据对不上" in out, "远处撞上的短词被放行 ⇒ 窗口没缩"


def test_silently_skipped_quote_is_reported_as_shortfall(tmp_path):
    """🔴🔴 **少抓必须报警**——审核门 2026-08-03 抓到的真实缺陷。

    闸首版只有「零命中当异常」守卫，**没有「抓到条数 < 组合数」守卫**。
    于是当正则收紧到「括注不许含汉字」后，
    `依据（**代表条款** App4 1.1）：` 这类合法行被**静默跳过**，
    脚本照报「引文条数 25」、一切正常——**我据此对外说了「52/52 逐字命中」，实为 51/52。**

    **少抓比抓错更危险：抓错会报红，少抓什么都不说。**
    """
    body = (
        "## 组合 1\n3. 依据（3.4.1）：註冊檢驗人員須妥為簽署完工報告。\n"
        "## 组合 2\n3. 这一行故意不写「依据」，模拟被跳过\n"
    )
    code, out = _run(tmp_path, body)
    assert code == 1, "少抓了一条却退出 0 ⇒ 守卫没生效"
    assert "少抓" in out and "2 个组合" in out, out


def test_clause_ref_with_cjk_is_still_captured(tmp_path):
    """括注里有汉字（「代表条款」）也必须抓到——这正是当初被静默跳过的形状。"""
    body = f"## 组合 1\n3. 依据（代表条款 App4 1.1）：{_REAL}\n"
    code, out = _run(tmp_path, body)
    assert code == 0, out
    assert "引文条数 1" in out, out


def test_workorder_instruction_line_is_still_excluded(tmp_path):
    """放宽括注之后，工单说明行「依据硬要求：…」**仍须被排除**。

    它无括注且冒号不紧跟 `依据`，两条都不满足 ⇒ 不进校验。
    若它被当引文抓进来，会凭空多出一条永远红的「引文」。
    """
    body = f"## 组合 1\n3. 依据：{_REAL}\n依据硬要求：连续逐字、不许省略号、不许改字。\n"
    code, out = _run(tmp_path, body)
    assert code == 0, out
    assert "引文条数 1" in out, "工单说明行被误抓进来了"


def test_relaxation_does_not_leak_to_the_primary(tmp_path):
    """反面锁：主依据是假的时候，**后面跟一段真引文也救不了它**。

    防的是「把一句好引的话垫在后面，真正的依据放在前面蒙混过关」的反向利用。
    """
    fake = "註冊檢驗人員須確保所有文件均已妥為存檔並經上級覆核。"
    body = f"3. 依据：「{fake}」（参见「{_REAL}」）\n"
    code, out = _run(tmp_path, body)
    assert code == 1 and "主依据对不上" in out, out


# ===== 显式标签形态（2026-08-03 放宽）的变异验证 =====
# 🔴 放宽必须配变异测试：闸新认识 `引出句：X 分项：Y` 这个写法后，
# 必须证明它**只是学会了拆标签**，没有顺带放过编造的分项。

def _gate():
    import importlib.util, pathlib as _p
    f = _p.Path(__file__).resolve().parents[4] / "scripts" / "verify_adjudication_quotes.py"
    spec = importlib.util.spec_from_file_location("_vaq", f)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_explicit_label_form_is_accepted_when_both_segments_verbatim():
    g = _gate()
    src = g.norm("就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
                 "(a) 須更換欠妥的部分，及糾正錯誤接駁情況；")
    q = ("引出句：就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
         " 分项：(a) 須更換欠妥的部分，及糾正錯誤接駁情況。")
    assert g._stem_and_item_ok(q, src)


def test_explicit_label_form_still_rejects_a_fabricated_item():
    """标签写对了，但分项是编的 ⇒ 必须仍判红。"""
    g = _gate()
    src = g.norm("就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
                 "(a) 須更換欠妥的部分。")
    q = ("引出句：就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
         " 分项：(z) 須每年委任認可人士覆核全部排水系統。")
    assert not g._stem_and_item_ok(q, src)


def test_explicit_label_form_still_rejects_a_fabricated_stem():
    g = _gate()
    src = g.norm("就公用排水渠而言：(a) 須更換欠妥的部分。")
    q = "引出句：就地下排水管及化糞池而言，須每季檢查： 分项：(a) 須更換欠妥的部分。"
    assert not g._stem_and_item_ok(q, src)


# ===== 错配变异（审核门 kimi 2026-08-03 用真实法规原文实测钉出的洞）=====
# 🔴 前三条只锁「编造文本」，**没锁「错配真实文本」**——而错配才是这条
# 放宽路径特有的失败模式：偷懒的裁定代理拿甲条款的引出句配乙条款的分项，
# 两段**都逐字属实**，闸照样该判红（它们不构成同一条规定）。
# 实测原窗口 4000 对 ≥8 字长分项等于不设防：偏移 300/1000/2000 全部放行。

def _real_src():
    import pathlib as _p
    f = (_p.Path(__file__).resolve().parents[4] / "regulations" / "markdown"
         / "MBIS_CoP_2023.md")
    return f.read_text(encoding="utf-8")


def test_mismatched_real_segments_from_distant_clauses_are_rejected():
    """真引出句 ＋ **别处**的真实文本当分项 ⇒ 必须判红。"""
    g = _gate()
    sn = g.norm(_real_src())
    stem = sn[20000:20030]                       # 真实文本，够长过守卫
    for offset in (300, 1000, 2000):
        item = sn[20030 + offset: 20030 + offset + 14]   # 同样真实，但属别的条款
        q = f"引出句：{stem} 分项：{item}"
        assert not g._stem_and_item_ok(q, sn), f"偏移 {offset} 不该放行"


def test_marked_item_within_measured_window_still_passes():
    """带枚举标记、且距离在实测范围内的真实分项**不能**被误伤。

    阈值是量出来的：带标记实测最大 445（取 600）、不带标记最大 168（取 200）。
    """
    g = _gate()
    src = g.norm("就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
                 "(a) 須更換欠妥的部分；(b) 所有膠管及裝置須為耐用。")
    q = ("引出句：就公用排水渠而言，註冊檢驗人員應考慮以下的修葺方法："
         " 分项：(b) 所有膠管及裝置須為耐用。")
    assert g._stem_and_item_ok(q, src)


def test_window_thresholds_are_the_measured_ones():
    """阈值被写死成常量，改动必须先复量分布——本测试是那个提醒。"""
    g = _gate()
    assert g._STEM_ITEM_WINDOW_MARKED == 600
    assert g._STEM_ITEM_WINDOW_PLAIN == 200
    assert not hasattr(g, "_STEM_ITEM_WINDOW"), "旧的 4000 单一窗口必须已删除"

