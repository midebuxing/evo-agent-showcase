"""规范效力漂移审计器的行为锁定(DEBT-068)。

两条断言直接对应第一版的两个**假阳 bug**(2026-07-25 抽验当场抓到):
  ① 章节窗口没切到下一节 → §5.1.5(原文「**無須**事先獲得批准」)把 §5.1.6 的一堆
     「須」吃进窗口,误判成 shall→may 降级(实际英文引文忠实);
  ② 分项定位不到时退回整章 → 整章别处的效力词假报到本分项。

两个 bug 叠加让漂移数虚高到 26 条;修完是 18 条。**假阳比漏报更糟**——它会让人去"修"
本来正确的法规卡,而改卡在本项目已经翻车过一次。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_rulecard_modality_drift as audit  # noqa: E402


def test_negated_modality_is_stripped():
    """「無須」不得被读成「須」——否则否定条款会被误判为强制。"""
    assert "須" not in audit._strip_negated("工程的展開無須事先獲得批准")
    # 正常的「須」不能被误剔
    assert "須" in audit._strip_negated("註冊檢驗人員須進行評估")


def test_all_negation_forms_covered():
    """繁简与异体都要覆盖——法规是繁体，但仓库里两种都可能出现。"""
    for neg in ("無須", "无须", "不須", "不须", "毋須", "毋须"):
        assert "須" not in audit._strip_negated(f"甲{neg}乙"), f"{neg} 未被剔除"


def test_subsection_miss_does_not_fall_back_to_whole_chapter():
    """分项定位不到时必须记未覆盖，**不得**退回整章——否则整章的效力词假报到本分项。"""
    # 2026-07-26 两次搬家，断言跟着搬、行为断言不变：
    #   ① 收窄改成**逐级**后，约束表述从"不得退回整章"泛化成"不得退回上一层"（更强）；
    #   ② 定位逻辑抽成 `locate_scope`（供 DEBT-071 内容审计器复用），注释随之搬过去。
    src = inspect.getsource(audit.locate_scope)
    assert "不得退回上一层" in src, "须在代码里写明这条约束的理由"
    sections = {"9.9.9": "9.9.9 標題\n\n註冊檢驗人員須進行評估\n"}
    tok, how = audit.cn_modality(sections, "9.9.9(Z)")
    assert tok is None, "分项 (Z) 不存在时不该借整章的「須」出结论"
    assert "定位不到" in how


def test_chapter_window_is_bounded_by_next_section():
    """章节窗口必须切到下一个章节号——否则会吃进下一节的效力词。"""
    cn = "1.1.1 甲節\n\n此節無效力詞。\n\n1.1.2 乙節\n\n註冊檢驗人員須進行評估\n"
    sections = audit.cn_body_sections(cn)
    assert "須" not in sections["1.1.1"], "1.1.1 的窗口吃进了 1.1.2 的「須」"
    assert "須" in sections["1.1.2"]


def test_audit_declares_its_own_limitation():
    """审计器必须自陈局限:只比效力档位、不比语义忠实度(動詞漂移它抓不到)。"""
    src = inspect.getsource(audit.main)
    assert "不比语义忠实度" in src, "须显式声明它抓不到「進行→考慮」这类动词漂移"
    assert "禁静默丢弃" in src, "未覆盖项必须报出原因，不许静默丢"


def test_mixed_modality_paragraph_is_not_judged():
    """段落含多个效力档位时必须不判——"取最强"在混合段落里必假阳。

    实证(2026-07-25 第四轮假阳):App6 para 2「註冊檢驗人員**可**委任1級代表…
    註冊檢驗人員**須**為其監督人員隊伍負全責」——`可` 管委任、`須` 管负责，
    卡引的是**委任**那句，英文 `may` 完全忠实；"取最强"把它判成 須→may 降级。
    """
    assert audit._mixed_modality("註冊檢驗人員可委任代表，並須負全責") is not None
    assert audit._mixed_modality("註冊檢驗人員須進行評估") is None
    sections = {"9.9.9": "9.9.9 標題\n\n甲可為之，乙須為之\n"}
    tok, how = audit.cn_modality(sections, "9.9.9")
    assert tok is None and "混合效力" in how


def test_appendix_locator_hits_body_not_toc():
    """附录定位器必须抓正文，不是目录表格（目录里是 `<td>附錄六</td>`）。"""
    apps = audit.appendix_sections(audit.load_cn())
    assert "App6" in apps, "附錄六 未定位到"
    body = apps["App6"]
    assert "<td>" not in body[:120], "抓到了目录行"
    assert "註冊檢驗人員" in body[:400], "附录正文特征缺失"


def test_appendix_without_narrowing_anchor_is_uncovered():
    """`Tbl1` 这类无收窄锚的分项必须记未覆盖，不得退回整附录。"""
    apps = {"App9": "附錄九\n\n1. 註冊檢驗人員須確保甲。\n"}
    tok, how = audit.appendix_modality(apps, "App9 Tbl1")
    assert tok is None
    assert "表格" in how or "收窄锚" in how


def test_compound_words_are_not_read_as_modality():
    """🔴 第五类假阳:中文没有词边界，複合詞里的字被当成效力标记。

    语料实测(`MBIS_CoP_2023.md` 全文):「應」68 次里 31 次(45.6%)是複合詞
    (因應 9 / 效應 8 / 應用 8 / 應力 4 / 相應 2)，「可」187 次里 55 次(29.4%)是
    (認可 34 / 可行 14 / 許可 5 / 可靠 2)。「應力」是力学应力、「認可人士」是
    authorized person，跟规范效力毫无关系。
    """
    # 力学/语义複合詞不得留下效力字
    for word in ("應力", "應用", "因應", "效應", "相應"):
        assert "應" not in audit._strip_compounds(f"甲{word}乙"), f"{word} 未被剔除"
    for word in ("認可", "可行", "許可", "可靠"):
        assert "可" not in audit._strip_compounds(f"甲{word}乙"), f"{word} 未被剔除"
    # 真效力标记不得被误剔
    assert "須" in audit._strip_compounds("註冊檢驗人員須進行評估")
    assert "應" in audit._strip_compounds("註冊檢驗人員應考慮")
    # 「可+动词」是真许可，不许剔
    assert "可" in audit._strip_compounds("註冊檢驗人員可聘用代表")


def test_compound_false_positive_suppresses_real_drift():
    """複合詞假阳的**第二重危害**:它把段落误判成「混合效力」→ 不判 → 真漂移被压掉。

    这才是它比"多报几条混合"严重的地方:漂移数因此是下界。
    """
    # 段落真实只有一档(須)，但含「認可人士」——修前会被读成 須+可 = 混合
    scope = "註冊檢驗人員須將報告交予認可人士審核"
    assert audit._mixed_modality(scope) is not None, "前提:未剔複合詞时确实被判混合"
    assert audit._mixed_modality(audit._strip_compounds(scope)) is None, (
        "剔掉複合詞后应恢复成单一档位，否则真漂移仍被压住"
    )


def test_strip_compounds_runs_at_the_single_classification_site():
    """接线闸:剔複合詞必须发生在**唯一**的分类入口 `_classify`，不许有第二处。

    沿革(2026-07-26):首版三个作用域取值点各自剔一次，本测试断言 ==3，用来防"新增取值点
    忘了接"。后来把定位与分类拆开（`locate_scope` / `locate_appendix_scope` 只定位，
    `_classify` 唯一负责分类），剔除点收敛成 1 处——**这是更强的状态**：单点剔除漏不掉。
    附录路径还因此白捡了它此前没有的**禁止轴检查**（覆盖 82→81，少判一条，保守方向）。

    断言改成 ==1 并锁死"只能有一处"，防有人日后再拆出并行分类路径。
    """
    src = inspect.getsource(audit)
    assert src.count("_strip_compounds(_strip_negated(scope))") == 1, (
        "剔複合詞必须只在 `_classify` 一处；出现第二处＝又有并行分类路径会分叉"
    )
    assert "_strip_compounds(_strip_negated(scope))" in inspect.getsource(audit._classify)


def test_sibling_boundary_is_level_aware():
    """🔴 第六类假阳:分项窗口的边界必须按**同级**标签算，不能用"下一个任意括号标签"。

    实证结构(§3.3.2):`(G) 幕牆…` → `(a) …須認明…` → `(i)-(vi) …` → `(b) …`。
    用任意标签作边界，`(G)` 的窗口在 `(a)` 前就被切断，`(G)(a)(vi)` 这类多括号
    section_id 的子标签永远定位不到（实测覆盖因此从 76 掉到 71）。
    """
    assert audit._label_class("(G)") == "upper"
    assert audit._label_class("(a)") == "lower"
    assert audit._label_class("(vi)") == "roman"
    # 大写层的边界只认大写，不能被小写子项截断
    import re as _re
    text = "(G) 標題\n\n(a) 子項\n\n(b) 子項\n\n## (H) 下一節"
    m = _re.search(audit._sibling_boundary("(G)"), text)
    assert m is not None and "(H)" in text[m.start():], "大写层边界被小写子项截断了"
    # 小写层的边界要排除罗马数字，否则 (a) 会在 (i) 处被切断
    m2 = _re.search(audit._sibling_boundary("(a)"), "(a) 引言\n\n(i) 甲\n\n(ii) 乙\n\n(b) 丙")
    assert m2 is not None and "(b)" in "(a) 引言\n\n(i) 甲\n\n(ii) 乙\n\n(b) 丙"[m2.start():]


def test_sibling_list_reference_is_not_treated_as_nesting():
    """并列引用（`§5.6.1(c)(d)`）不是嵌套路径，不得按嵌套定位，也不得静默丢。

    实证:`(c)(d)` / `(e)(f)` / `(a)(b)` 标签对全是连续同级字母——那是"第 (c) 及 (d) 项"。
    并列引用跨多个分项，无法确定卡引哪一项 → 记未覆盖、不判（同混合效力的处置）。
    """
    sections = {"9.9.9": "9.9.9 標題\n\n(c) 甲須為之\n\n(d) 乙可為之\n"}
    tok, how = audit.cn_modality(sections, "9.9.9(c)(d)")
    assert tok is None
    assert "并列" in how or "范围引用" in how
    # 真嵌套（不同层级）仍须正常收窄
    assert audit._label_class("(B)") != audit._label_class("(d)")


def test_openable_window_adjective_is_not_modality():
    """「可開啓的窗戶」= openable windows（形容词），不是「可」情态。

    实证:§3.3.2(G) 标题含「可開啓」，害得 (G) 底下两条被读成「可」而误报漂移——
    那两条原文其实写的是「須」。
    """
    assert "可" not in audit._strip_compounds("幕牆及其中的可開啓的窗戶")
    assert "可" not in audit._strip_compounds("可供使用的有利位置")
    assert "可" not in audit._strip_compounds("公眾可進入的私家街道")


def test_prohibition_is_not_on_the_modality_axis():
    """🔴 第八类假阳:禁止性表述在**两侧都**被判错(2026-07-26 做 §4.2.3 逐卡裁定时撞出)。

    实证 §4.2.3:中文「詳細調查建議在未獲…認可前，**不得**進行…註冊檢驗人員仍**可**安排」。
      中文侧:「不得」不在 CN_RANK 里 → 只看见段尾「仍可」的「可」(rank 1);
      英文侧:`en_modality("must not be conducted")` 命中 `\bmust\b` → 返回 must(rank 3)。
    于是拿"段落的可"比"引文的 must"，报成升级——而卡引文对「不得進行」其实**完全忠实**。
    禁止不是 shall/should/may 轴上的档位，是另一个极。
    """
    assert audit.en_modality("A proposal must not be conducted") == "PROHIBIT"
    assert audit.en_modality("shall not commence") == "PROHIBIT"
    assert audit.en_modality("the RI may not arrange") == "PROHIBIT"
    # 肯定式不得被误判成禁止
    assert audit.en_modality("the RI must arrange") == "must"
    assert audit.en_modality("the RI may arrange") == "may"
    # 中文侧
    assert audit.cn_is_prohibition("未獲認可前不得進行")
    assert not audit.cn_is_prohibition("註冊檢驗人員須進行評估")


def test_prohibition_mixed_with_modality_is_not_judged():
    """段落兼有禁止与情态(正是 §4.2.3 的形状)→ 不可比，记未覆盖，**不得报漂移**。"""
    sections = {"9.9.9": "9.9.9 標題\n\n建議在未獲認可前不得進行。其後註冊檢驗人員仍可安排。\n"}
    tok, how = audit.cn_modality(sections, "9.9.9")
    assert tok is None
    assert "禁止" in how and "不可比" in how


def test_pure_prohibition_paragraph_returns_prohibit_token():
    """纯禁止段落返回 PROHIBIT，好让比较处与英文侧的 must not 对上判"一致"。"""
    sections = {"9.9.9": "9.9.9 標題\n\n有關工程不得展開。\n"}
    tok, how = audit.cn_modality(sections, "9.9.9")
    assert tok == "PROHIBIT" and "禁止性" in how


def test_appendix_multilabel_narrows_progressively():
    """🔴 第十类:附录路径**只取第一层标签**（`labels[0]`）——正文路径已修、附录漏了。

    子代理核 §App5 1.1(b)(vii) 时当场撞出：定位器只收窄到 `(b)`，窗口在 `(iv)` 前被截断
    （(i)-(iii) 带 `* ` 项目符号、不匹配 `\n(`），于是代理拿到"修補用砂漿"那段，而 (vii)
    讲的是"新鋼筋須符合 CS2"——代理据此报卡错，**其实卡是对的、错的是定位器**。
    影响 17 张附录多层标签卡。

    **这是"同一个 bug 修了一条路径漏了另一条"的教科书案例**，也是把定位收敛成共用函数的
    正当性来源：两条路径各写一份，就会各带各的历史 bug。
    """
    apps = audit.appendix_sections(audit.load_cn())
    scope, how = audit.locate_appendix_scope(apps, "App5 1.1(b)(vii)")
    assert scope is not None, "App5 1.1(b)(vii) 定位不到"
    assert "CS2" in scope, f"收窄错了，拿到的是别的分项：{scope[:60]}"
    assert "修補用砂漿的抗壓強度" not in scope, "窗口吃进了 (b)(i) 的砂漿内容"
    # 相邻分项各归各的
    s_c, _ = audit.locate_appendix_scope(apps, "App5 1.1(c)")
    assert "10 毫米至 20 毫米" in s_c
    s_d, _ = audit.locate_appendix_scope(apps, "App5 1.1(d)")
    assert "大於 15%" in s_d and "10 毫米至 20 毫米" not in s_d


def test_appendix_bullet_prefixed_items_are_reachable():
    """附录分项可能带 markdown 项目符号（`* (i)` / `- (ii)`），边界正则要容得下。"""
    apps = audit.appendix_sections(audit.load_cn())
    scope, _ = audit.locate_appendix_scope(apps, "App5 1.1(b)(i)")
    assert scope is not None and "修補用砂漿" in scope
    assert "CS2" not in scope, "(b)(i) 的窗口吃到了 (b)(vii)"


def test_appendix_subitem_carries_lead_in():
    """🔴 第十五类:**附录路径没有取引出句**——正文修了、附录又漏了（同一形状第三次）。

    实证附錄二:「(h) 有關樓宇檢驗、糾正及修葺的過往記錄；以及」本身是无动词名词短语，
    情态在引导句「註冊檢驗人員**須**於進行樓宇檢驗前，取得及審閱以下的樓宇背景資料：」里。
    缺引出句时子代理只能标 uncertain 无从判——修好后当场解答:卡写 "must obtain and
    review" **是忠实的**。
    """
    apps = audit.appendix_sections(audit.load_cn())
    scope, how = audit.locate_appendix_scope(apps, "App2(h)")
    assert scope is not None
    assert "引出句" in how, f"附录分项未带引出句:{how}"
    assert "須於進行樓宇檢驗前" in scope, "引导句没带上，情态仍不可判"
    assert "(h) 有關樓宇檢驗" in scope


def test_appendix_lead_in_stops_at_first_sibling():
    """引出句必须切到**第一个同级标签**之前——否则后面的分项会把前面的兄弟全吞进来。

    正文路径已经栽过一次:§4.3.1(k) 的"引出句"曾把 (a)-(j) 全带出来，内容审计从 41 炸到 106。
    """
    apps = audit.appendix_sections(audit.load_cn())
    s_i, _ = audit.locate_appendix_scope(apps, "App2(i)")
    assert s_i is not None
    assert "(h) 有關樓宇檢驗" not in s_i, "(i) 的引出句把兄弟项 (h) 吞进来了"
    assert "須於進行樓宇檢驗前" in s_i, "引导句仍要带"


def test_appendix_numbered_para_offset_is_from_match_end():
    """`App7 sec 2` 的作用域不得退化成只剩一个 `###`。

    实证:边界搜索起点原写死 `i + len(n) + 3`（旧版从 `\n` 匹配时的距离），改成行首匹配后
    `i` 指向 `#`，偏移错位 → 边界正则在原地又匹配到本段标题 → 窗口长度 0。影响 9 张卡。
    """
    apps = audit.appendix_sections(audit.load_cn())
    scope, _ = audit.locate_appendix_scope(apps, "App7 sec 2")
    assert scope is not None and len(scope) > 20, f"作用域退化:{scope!r}"
    assert "摘要" in scope


def test_roman_or_lower_ninth_item_is_disambiguated_by_context():
    """`(i)` 到底是罗马数字还是小写第 9 项——按上下文里有没有 `(h)` 判。

    实证:§4.3.1 的列表是 (a)…(k)，`(i)` 是小写第 9 项；恒判罗马会让它找不到同级兄弟，
    窗口吞掉 (a)-(h)（子代理报"作用域把整段列表带出来"）。
    """
    assert audit._label_class_in_context("(i)", "(h) 甲\n(i) 乙\n(j) 丙") == "lower"
    # 真罗马语境(有 (ii)/(iii) 兄弟、没有 (h))仍判罗马
    assert audit._label_class_in_context("(i)", "(i) 甲\n(ii) 乙\n(iii) 丙") == "roman"
    cn = audit.load_cn()
    sec = audit.cn_body_sections(cn)
    scope, _b, _l, _h = audit.locate_scope(sec, "4.3.1(i)")
    assert scope is not None
    assert "樓宇的整體移動" in scope
    assert "橫樑面的螺旋形裂縫" not in scope, "窗口吞进了兄弟项 (c)"
