"""A 门(结构与密度)脚本 `agent_v1/scripts/check_report_usability.py` 的行为测试。

codex 聚合审核阻断#2/#3 整改(2026-07-23):覆盖——
- 嵌套栈校验:逆序标签拒绝 / 不闭合拒绝 / 合法标签通过;
- v4 组形态校验:合法组通过 / 组头 N 与入口条目数不符拒绝 / 组头后插入可见行拒绝。
"""
import importlib.util
import os
import textwrap
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_report_usability.py"
_spec = importlib.util.spec_from_file_location("check_report_usability", _SCRIPT)
cru = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cru)

# 默认阈值(宽松,不让其它硬指标干扰结构测试)
_TH = {"main_max": 9999, "dup_max": 1.0, "mix_max": 1.0}


def _write_report(tmp_path, text: str) -> str:
    """写一份临时报告,返回文件路径。"""
    p = tmp_path / "report.md"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return str(p)


# ────────────────── 嵌套栈校验 ──────────────────

def test_reversed_details_tags_rejected(tmp_path):
    """</details> 出现在 <details> 之前(逆序)→ details_pairing 失败。"""
    path = _write_report(tmp_path, """\
    一些内容
    </details>
    <details>
    <summary>标题</summary>
    内部内容
    </details>
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is False
    assert r["passed"] is False


def test_unclosed_details_rejected(tmp_path):
    """<details> 打开后未关闭 → details_pairing 失败。"""
    path = _write_report(tmp_path, """\
    一些内容
    <details>
    <summary>标题</summary>
    内部内容
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is False
    assert r["passed"] is False


def test_valid_nested_details_passes(tmp_path):
    """正确嵌套的 <details>/<summary> → details_pairing 通过。"""
    path = _write_report(tmp_path, """\
    一些内容
    <details>
    <summary>标题</summary>
    内部内容
    </details>
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is True


def test_summary_outside_details_rejected(tmp_path):
    """<summary> 出现在 <details> 外 → details_pairing 失败。"""
    path = _write_report(tmp_path, """\
    一些内容
    <summary>标题</summary>
    正文
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is False
    assert r["passed"] is False


# ────────────────── v4 组形态校验 ──────────────────

def _minimal_v4_report(
    n_declared=1, entries="[O1/R1]", extra_line_before_details="",
    has_status_line=True, has_blank_line=True, has_details=True
) -> str:
    """生成最小合法 v4 报告文本(可按参数注入缺陷)。"""
    lines = ["<!-- report contract v4 -->"]
    lines.append(f"### G1｜证据缺口｜{n_declared} 项")
    lines.append(f"- 义务入口：{entries}")
    if has_status_line:
        lines.append("- 状态 / 原因 / 动作：未闭合；缺少证据；建议人工复核。")
    if has_blank_line:
        lines.append("")
    if extra_line_before_details:
        lines.append(extra_line_before_details)
    if has_details:
        lines.append("<details>")
        lines.append("<summary>展开 1 项的所选证据与法规原文</summary>")
        lines.append("")
        lines.append("#### [O1/R1]")
        lines.append("- 现有证据：示例证据。")
        lines.append("- 法规依据：[R1] 「条文」")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def test_valid_v4_group_shape_passes(tmp_path):
    """完整合法 v4 组形态 → v4_group_shape 通过。"""
    path = _write_report(tmp_path, _minimal_v4_report())
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is True
    assert r["passed"] is True


def test_v4_group_n_mismatch_rejected(tmp_path):
    """组头声明 2 项但入口行只有 1 条 → v4_group_shape 失败。"""
    path = _write_report(tmp_path, _minimal_v4_report(
        n_declared=2, entries="[O1/R1]"))
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is False
    assert r["passed"] is False


def test_v4_visible_line_after_header_rejected(tmp_path):
    """组头后状态行与 <details> 之间插入可见行 → v4_group_shape 失败。"""
    path = _write_report(tmp_path, _minimal_v4_report(
        extra_line_before_details="这是一行不该存在的可见内容"))
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is False
    assert r["passed"] is False


def test_v4_missing_status_line_rejected(tmp_path):
    """组头后缺 '- 状态 / 原因 / 动作：' 行 → v4_group_shape 失败。"""
    path = _write_report(tmp_path, _minimal_v4_report(has_status_line=False))
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is False
    assert r["passed"] is False


def test_v4_multi_group_valid(tmp_path):
    """两个合法组 → v4_group_shape 通过。"""
    text = "<!-- report contract v4 -->\n"
    for gi, oa, ra in [(1, "O1", "R1"), (2, "O2", "R2")]:
        text += f"### G{gi}｜证据缺口｜1 项\n"
        text += f"- 义务入口：[{oa}/{ra}]\n"
        text += "- 状态 / 原因 / 动作：未闭合；缺少证据；建议人工复核。\n"
        text += "\n"
        text += "<details>\n"
        text += f"<summary>展开 1 项的所选证据与法规原文</summary>\n"
        text += "\n"
        text += f"#### [{oa}/{ra}]\n"
        text += "- 现有证据：示例证据。\n"
        text += f"- 法规依据：[{ra}] 「条文」\n"
        text += "\n"
        text += "</details>\n"
        text += "\n"
    path = _write_report(tmp_path, text)
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is True
    assert r["checks"]["v4_group_count"][1] is True
    assert r["passed"] is True


# ────────────────── codex 复审二轮差分反例(2026-07-23) ──────────────────

def test_cross_closed_tags_rejected(tmp_path):
    """交叉闭合 <details><summary>…</details></summary> → 拒绝
    (复审二轮:两个独立深度计数验不了关闭顺序,须真栈)。"""
    path = _write_report(tmp_path, """\
    <details>
    <summary>标题
    </details>
    </summary>
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is False


def test_malformed_group_head_rejected(tmp_path):
    """畸形组头 `### G1｜X｜N items`(宽松匹配但不严格合形)→ v4_group_shape 失败
    (复审二轮:曾被计数却跳过全部形态校验)。"""
    path = _write_report(tmp_path, """\
    report contract v4
    ### G1｜X｜N items
    随便什么内容
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["v4_group_shape"][1] is False


def test_same_line_multi_tag_cross_close_rejected(tmp_path):
    """同一行多标签 `</details></summary>` 交叉闭合 → 拒绝
    (codex 终判三轮:逐行 if/elif 只认其一,曾假绿;现按行内词元序进栈)。"""
    path = _write_report(tmp_path, """\
    <details>
    <summary>x
    </details></summary>
    </details>
    """)
    r = cru.analyze(path, _TH)
    assert r["checks"]["details_pairing"][1] is False
