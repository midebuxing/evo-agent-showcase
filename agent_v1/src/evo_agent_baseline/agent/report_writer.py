"""evo-agent baseline 辅助审查报告生成（spec §7.4 + 附录 C；报告契约 v2）。

按闭包验证器输出的 allow_stop 二选一：
- allow_stop=true  → auxiliary_review_report.md（辅助审查报告，非最终裁决）
- allow_stop=false → incomplete_closure_notice.md（闭包未完成说明）

报告契约 v2（草案 团队文档/我的笔记/spec草案_报告契约v2_20260712.md）：
- 报告成品不再由 LLM 整篇生成：程序确定性渲染全部权威骨架
  （`render_contract_v2_report`），LLM 只提交分析节候选文本，插入唯一槽位；
- 程序从闭包产物构造 `NarrativeEvidencePack`（closure summary + 重点
  violated/high-risk/open/blocked 项 + rule card 短引文 + fact refs + 未取到项），
  对模型用短别名 [O1]/[R2]/[F3]，alias_map 落审计；
- 叙述失败时以 `render_deterministic_narrative` 的确定性叙述模板填槽位；
- **不变量：程序骨架与两条确定性叙述模板必须按构造即输出守卫
  （`pre_output_language_guard`，spec §7.3.6）洁净**——本文件新增任何免责/告知
  文案时，禁止话术只允许紧跟否定前缀白名单（非 / 不是 / 不构成 / 不输出）出现，
  杜绝"守卫拦截确定性兜底稿→无终稿可用"的自指循环。

设计要点（spec §1.0 原则 1、5；§7.1 规则 6、7）：
- 报告是确定性渲染，不引入 LLM 自由发挥（v2 下 LLM 文本只进分析节槽位）；
- 任何话术都用“疑似未满足 / 建议人工复核”，不用“最终不合规”
  （spec §7.2.4 规则 4、§7.3.6）。
- 不引用、不推断 W2 expected_verdict（spec §7.1 规则 3）。

spec→code 单向：报告骨架与字段照 spec §7.4 / 附录 C + 报告契约 v2 草案，不自创章节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import (
    ClosureValidationResult,
    FactPack,
    RuleSlice,
)


# ===========================================================================
# 一、内部渲染工具
# ===========================================================================

# 报告生成时统一的非最终裁决声明（spec §7.1 规则 2、附录 C 抬头）。
_DISCLAIMER = (
    "本报告由 evo-agent baseline 生成，仅供人工审查员辅助使用，"
    "不构成最终合规裁决。本报告不读取 W2 参考真值，不替代人工审查员最终判断。"
)


def demote_h1_outside_fenced_code(markdown: str) -> str:
    """Demote H1/H2 to H3 outside CommonMark-style fenced code blocks.

    H2 一并降级：防模型在分析节伪造与程序骨架同名的「## 权威闭包概览」等
    二级权威节冒充程序渲染内容（复审 P2）。
    """
    fence_char = ""
    fence_length = 0
    rendered: List[str] = []
    for line in markdown.splitlines(keepends=True):
        if fence_char:
            rendered.append(line)
            closing = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*(?:\r?\n)?$", line)
            if (
                closing
                and closing.group(1)[0] == fence_char
                and len(closing.group(1)) >= fence_length
            ):
                fence_char = ""
                fence_length = 0
            continue

        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence_char = opening.group(1)[0]
            fence_length = len(opening.group(1))
            rendered.append(line)
            continue

        rendered.append(re.sub(r"^#{1,2}(?!#)", "###", line))
    return "".join(rendered)


def _g(d: Dict[str, Any], key: str, default: Any = "") -> Any:
    """dict 取值兜底——缺键返回 default，避免报告渲染因字段缺失中断。"""
    val = d.get(key, default)
    return default if val is None else val


def _fmt_value(value: Any) -> str:
    """把义务字段里的值渲染成单元格文本；None / 空串归一为占位符。"""
    if value is None or value == "":
        return "—"
    return str(value)


def _obligation_target(ob: Dict[str, Any]) -> str:
    """从义务 dict 拼一个可读的 target 描述（fragment / component 维度）。"""
    frag = _g(ob, "fragment_id")
    comp = _g(ob, "component_id")
    parts = [p for p in (frag, comp) if p]
    return " / ".join(parts) if parts else "建筑级"


def _obligation_evidence(ob: Dict[str, Any]) -> str:
    """汇总义务证据引用——evidence_fact_ids + source_quote_ids。"""
    facts = _g(ob, "evidence_fact_ids", []) or []
    quotes = _g(ob, "source_quote_ids", []) or []
    chunks: List[str] = []
    if facts:
        chunks.append("fact:" + ",".join(str(f) for f in facts))
    if quotes:
        chunks.append("quote:" + ",".join(str(q) for q in quotes))
    return "; ".join(chunks) if chunks else "—"

def render_authoritative_closure_overview(
    result: ClosureValidationResult,
    *,
    allow_stop: bool,
    world_id: str,
    building_id: str,
    generated_at: str,
) -> str:
    """渲染程序权威闭包概览，供 LLM 报告收档前注入（spec §7.4）。"""
    summary = result.closure_summary
    title = (
        "# MBIS 辅助审查报告（非最终裁决）"
        if allow_stop
        else "# MBIS 闭包未完成说明（非最终裁决）"
    )

    def top_five(counts: Dict[str, int]) -> str:
        rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        return "、".join(f"{reason}={count}" for reason, count in rows) or "无"

    lines = [
        title,
        "",
        "## 权威闭包概览",
        "",
        "> 本节由系统确定性生成；以下字段以闭包验证器结果为准。",
        "",
        f"- total: {summary.total_obligations}",
        f"- open: {summary.open_count}",
        f"- blocked: {summary.blocked_count}",
        f"- closed: {summary.closed_count}",
        f"- satisfied: {summary.satisfied_count}",
        f"- violated: {summary.violated_count}",
        f"- unknown: {summary.unknown_count}",
        f"- allow_stop: {result.allow_stop}",
        f"- open reason top-5: {top_five(summary.open_reason_counts)}",
        f"- blocked reason top-5: {top_five(summary.blocked_reason_counts)}",
        f"- building_id: {building_id}",
        f"- world_id: {world_id}",
        f"- run_id: {result.run_id}",
        f"- 运行时间戳: {generated_at}",
        "",
    ]
    return "\n".join(lines)

# ===========================================================================
# 二、incomplete_closure_notice（spec §7.4.2 / §6.5.3）
# ===========================================================================


def render_incomplete_closure_notice(
    result: ClosureValidationResult,
) -> str:
    """生成闭包未完成说明（spec §7.4.2，allow_stop=false 专用）。

    spec §7.4.2 固定格式：只列 open / blocked obligations 与补充建议，
    不得输出完整报告的第 3-9 节。

    入参：result —— ClosureValidationResult（allow_stop 预期为 false）。
    返回：incomplete_closure_notice.md 全文。
    """
    mr = result.machine_readable_report or {}
    summary = result.closure_summary

    open_items: List[Dict[str, Any]] = mr.get("open_items", []) or []
    blocked_items: List[Dict[str, Any]] = mr.get("blocked_items", []) or []

    lines: List[str] = []
    lines.append("# MBIS 闭包未完成说明（非最终裁决）")
    lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    lines.append("")
    lines.append("本次资料闭包验证未通过，不能生成完整辅助审查报告。")
    lines.append("")
    lines.append(f"- run_id: {result.run_id}")
    lines.append(f"- world_id: {_g(mr, 'world_id')}")
    lines.append(f"- building_id: {_g(mr, 'building_id')}")
    lines.append(f"- allow_stop: {result.allow_stop}")
    lines.append(f"- stop_reason: {_g(mr, 'stop_reason', summary.stop_reason)}")
    lines.append(
        f"- open: {summary.open_count}　blocked: {summary.blocked_count}"
        f"　closed: {summary.closed_count}"
    )
    lines.append("")

    # 未闭合项 —— open
    lines.append("## 未闭合项")
    lines.append("")
    lines.append("### open obligations（资料缺失，待补充）")
    lines.append("")
    if open_items:
        lines.append("| obligation_id | target | rule_card | kind | open_reason |")
        lines.append("|---|---|---|---|---|")
        for ob in open_items:
            lines.append(
                f"| {_fmt_value(_g(ob, 'obligation_id'))} "
                f"| {_obligation_target(ob)} "
                f"| {_fmt_value(_g(ob, 'source_rule_card_id'))} "
                f"| {_fmt_value(_g(ob, 'kind'))} "
                f"| {_fmt_value(_g(ob, 'open_reason_code'))} |"
            )
    else:
        lines.append("（无 open obligations）")
    lines.append("")

    # 未闭合项 —— blocked
    lines.append("### blocked obligations（验证器无法处理，需人工介入）")
    lines.append("")
    if blocked_items:
        lines.append("| obligation_id | target | rule_card | kind | blocked_reason |")
        lines.append("|---|---|---|---|---|")
        for ob in blocked_items:
            lines.append(
                f"| {_fmt_value(_g(ob, 'obligation_id'))} "
                f"| {_obligation_target(ob)} "
                f"| {_fmt_value(_g(ob, 'source_rule_card_id'))} "
                f"| {_fmt_value(_g(ob, 'kind'))} "
                f"| {_fmt_value(_g(ob, 'blocked_reason_code'))} |"
            )
    else:
        lines.append("（无 blocked obligations）")
    lines.append("")

    # 补充建议
    lines.append("## 建议补充 / 检查资料")
    lines.append("")
    suggestions = _collect_suggestions(open_items, blocked_items)
    if suggestions:
        for s in suggestions:
            lines.append(f"- {s}")
    else:
        lines.append("- 请人工审查员复核上表未闭合项并补充对应建筑事实 / 法规依据。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "本说明为人工审查辅助材料，非最终裁决。闭包验证通过前不生成完整辅助审查报告。"
    )
    lines.append("")
    return "\n".join(lines)


def _collect_suggestions(
    open_items: List[Dict[str, Any]],
    blocked_items: List[Dict[str, Any]],
) -> List[str]:
    """从 open / blocked 义务的 notes 与原因码汇总补充建议（去重保序）。"""
    seen: set = set()
    out: List[str] = []
    for ob in list(open_items) + list(blocked_items):
        note = str(_g(ob, "notes")).strip()
        rule = _fmt_value(_g(ob, "source_rule_card_id"))
        reason = _fmt_value(
            _g(ob, "open_reason_code") or _g(ob, "blocked_reason_code")
        )
        if note:
            msg = f"[{rule} / {reason}] {note}"
        else:
            msg = f"[{rule}] 待补充资料以闭合 {reason}。"
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


# ===========================================================================
# 三、auxiliary_review_report（spec §7.4.1 / 附录 C）
# ===========================================================================


def render_auxiliary_review_report(
    result: ClosureValidationResult,
    *,
    kg_snapshot_id: str = "",
    rulecard_bundle_id: str = "",
    fact_source_tables: Optional[List[str]] = None,
    rule_families: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """生成辅助审查报告（spec §7.4.1 + 附录 C，allow_stop=true 专用）。

    报告骨架取 spec §7.2.4 固定结构与附录 C 模板的并集：
    1 报告声明 / 2 建筑与资料范围 / 3 适用法规与 rule card 切片 /
    4 闭包验证摘要 / 5 逐项义务闭包表 / 6 疑似未满足 / 风险项 /
    7 证据链与来源 / 8 建议人工复核点 / 9 限制与未覆盖范围。

    入参：
    - result —— ClosureValidationResult（allow_stop 预期为 true）。
    - kg_snapshot_id / rulecard_bundle_id —— run 元数据，填入“资料范围”。
    - fact_source_tables —— 事实来源表清单（来自 FactPack.source_tables）。
    - rule_families —— 适用法规切片，每项形如
      {"family": ..., "rule_card_count": ..., "source_clauses": ...}。
    返回：auxiliary_review_report.md 全文。
    """
    mr = result.machine_readable_report or {}
    summary = result.closure_summary

    obligations: List[Dict[str, Any]] = mr.get("obligations", []) or []
    violated_items: List[Dict[str, Any]] = mr.get("violated_items", []) or []
    high_risk: List[Dict[str, Any]] = mr.get("high_risk_items", []) or []

    lines: List[str] = []

    # --- 抬头 ---
    lines.append("# MBIS 辅助审查报告（非最终裁决）")
    lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    lines.append("")

    # --- 1 报告声明 ---
    lines.append("## 1. 报告声明")
    lines.append("")
    lines.append(
        "本报告为人工审查员副驾驶辅助材料，仅给出闭包验证情况与疑似未满足项，"
        "不构成最终合规裁决，不宣告本建筑合规或不合规。"
    )
    lines.append("本报告不读取、不引用 W2 NormativeProjection / expected_verdict 等参考真值。")
    lines.append("")

    # --- 2 建筑与资料范围 ---
    lines.append("## 2. 建筑与资料范围")
    lines.append("")
    lines.append(f"- run_id: {result.run_id}")
    lines.append(f"- world_id: {_g(mr, 'world_id')}")
    lines.append(f"- building_id: {_g(mr, 'building_id')}")
    lines.append(f"- KG snapshot: {kg_snapshot_id or '—'}")
    lines.append(
        "- 事实来源: "
        + (", ".join(fact_source_tables) if fact_source_tables else "WorldBundle / SidecarRuntimeBundle")
    )
    lines.append(f"- 法规 / rule card 版本: {rulecard_bundle_id or '—'}")
    lines.append("")

    # --- 3 适用法规与 rule card 切片 ---
    lines.append("## 3. 适用法规 / rule card 切片")
    lines.append("")
    lines.append("| family | rule_card_count | source clauses |")
    lines.append("|---|---:|---|")
    if rule_families:
        for fam in rule_families:
            lines.append(
                f"| {_fmt_value(fam.get('family'))} "
                f"| {_fmt_value(fam.get('rule_card_count'))} "
                f"| {_fmt_value(fam.get('source_clauses'))} |"
            )
    else:
        rs = mr.get("rule_slice_summary", {}) or {}
        lines.append(
            f"| （共 {_fmt_value(rs.get('family_count'))} 个 family） "
            f"| {_fmt_value(rs.get('rule_card_count'))} | — |"
        )
    lines.append("")

    # --- 4 闭包验证摘要 ---
    lines.append("## 4. 闭包验证摘要")
    lines.append("")
    lines.append(f"- allow_stop: {result.allow_stop}")
    lines.append(f"- stop_reason: {_g(mr, 'stop_reason', summary.stop_reason)}")
    lines.append(f"- total_obligations: {summary.total_obligations}")
    lines.append(f"- closed: {summary.closed_count}")
    lines.append(f"- open: {summary.open_count}")
    lines.append(f"- blocked: {summary.blocked_count}")
    lines.append(f"- satisfied: {summary.satisfied_count}")
    lines.append(f"- violated: {summary.violated_count}")
    lines.append(f"- not_applicable: {summary.not_applicable_count}")
    lines.append("")
    # spec §7.4.1 要求 6：open/blocked 为 0 的确认
    if summary.open_count == 0 and summary.blocked_count == 0:
        lines.append("> 确认：open obligations = 0，blocked obligations = 0，资料闭包完成。")
    lines.append("")

    # --- 5 逐项义务闭包表 ---
    lines.append("## 5. 逐项义务闭包表")
    lines.append("")
    lines.append(
        "| obligation_id | target | rule_card | kind | closure | satisfaction | evidence |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for ob in obligations:
        lines.append(
            f"| {_fmt_value(_g(ob, 'obligation_id'))} "
            f"| {_obligation_target(ob)} "
            f"| {_fmt_value(_g(ob, 'source_rule_card_id'))} "
            f"| {_fmt_value(_g(ob, 'kind'))} "
            f"| {_fmt_value(_g(ob, 'closure_status'))} "
            f"| {_fmt_value(_g(ob, 'satisfaction_status'))} "
            f"| {_obligation_evidence(ob)} |"
        )
    if not obligations:
        lines.append("| — | — | — | — | — | — | — |")
    lines.append("")

    # --- 6 疑似未满足 / 风险项 ---
    lines.append("## 6. 疑似未满足 / 风险项")
    lines.append("")
    lines.append(
        "下表所列为闭包验证显示的疑似未满足项，建议人工复核；本表不构成最终不合规结论。"
    )
    lines.append("")
    lines.append("| obligation_id | rule_card | observed | required | note |")
    lines.append("|---|---|---|---|---|")
    risk_rows = violated_items if violated_items else []
    for ob in risk_rows:
        lines.append(
            f"| {_fmt_value(_g(ob, 'obligation_id'))} "
            f"| {_fmt_value(_g(ob, 'source_rule_card_id'))} "
            f"| {_fmt_value(_g(ob, 'observed_value_json'))} "
            f"| {_fmt_value(_g(ob, 'threshold_value_json') or _g(ob, 'expected_value_json'))} "
            f"| {_fmt_value(_g(ob, 'notes'))} |"
        )
    if not risk_rows:
        lines.append("| — | — | — | — | 未发现疑似未满足项 |")
    lines.append("")
    if high_risk:
        lines.append("额外高风险项（verifier high_risk_items）：")
        for item in high_risk:
            lines.append(f"- {item}")
        lines.append("")

    # --- 7 证据链与来源 ---
    lines.append("## 7. 证据链与来源")
    lines.append("")
    lines.append(
        "每条义务的证据链见第 5 节 evidence 列（fact 为 KG 事实节点，"
        "quote 为 rule_card 法规原文引用）。所有数字阈值与义务均可追溯到 "
        "rule_card / 法规条文 / KG fact node。"
    )
    src_guard = mr.get("source_guard", {}) or {}
    lines.append(
        f"- forbidden_source_check_passed: {src_guard.get('forbidden_source_check_passed', True)}"
    )
    lines.append(f"- forbidden_sources: {src_guard.get('forbidden_sources', [])}")
    lines.append("")

    # --- 8 建议人工复核点 ---
    lines.append("## 8. 建议人工复核点")
    lines.append("")
    review_points = _collect_review_points(violated_items, high_risk)
    if review_points:
        for p in review_points:
            lines.append(f"- {p}")
    else:
        lines.append("- 闭包验证未发现疑似未满足项；建议人工审查员按常规流程抽检。")
    lines.append("")

    # --- 9 限制与未覆盖范围 ---
    lines.append("## 9. 限制与未覆盖范围")
    lines.append("")
    lines.append("- 本报告不读取 W2 参考真值（NormativeProjection / expected_verdict）。")
    lines.append("- 本报告不替代人工审查员最终判断，不输出最终合规裁决。")
    lines.append(
        "- 闭包验证仅覆盖检索到的 rule card 切片范围；切片外法规义务未在本报告评估。"
    )
    lines.append("")
    return "\n".join(lines)


def _collect_review_points(
    violated_items: List[Dict[str, Any]],
    high_risk: List[Dict[str, Any]],
) -> List[str]:
    """从 violated / high-risk 义务汇总人工复核点（去重保序）。"""
    seen: set = set()
    out: List[str] = []
    for ob in violated_items:
        rule = _fmt_value(_g(ob, "source_rule_card_id"))
        note = str(_g(ob, "notes")).strip()
        msg = (
            f"复核 rule_card {rule} 的疑似未满足义务"
            f"{('：' + note) if note else ''}（建议人工复核）。"
        )
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    for item in high_risk:
        msg = f"复核高风险项：{item}（建议人工复核）。"
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


# ===========================================================================
# 四、统一入口（spec §7.3.5 stop gate 决定模板）
# ===========================================================================


def write_report(
    result: ClosureValidationResult,
    *,
    kg_snapshot_id: str = "",
    rulecard_bundle_id: str = "",
    fact_source_tables: Optional[List[str]] = None,
    rule_families: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """按 allow_stop 选模板生成报告（spec §7.3.5 / §7.4）。

    allow_stop=true  → auxiliary_review_report.md；
    allow_stop=false → incomplete_closure_notice.md。
    模板由 verifier 的 allow_stop 锁定，LLM 不能覆盖。

    入参：见 render_auxiliary_review_report。
    返回：{"filename": <文件名>, "content": <markdown 全文>}。
    """
    if result.allow_stop:
        content = render_auxiliary_review_report(
            result,
            kg_snapshot_id=kg_snapshot_id,
            rulecard_bundle_id=rulecard_bundle_id,
            fact_source_tables=fact_source_tables,
            rule_families=rule_families,
        )
        return {"filename": "auxiliary_review_report.md", "content": content}

    content = render_incomplete_closure_notice(result)
    return {"filename": "incomplete_closure_notice.md", "content": content}


# ===========================================================================
# 五、报告契约 v2 —— 叙述证据包（NarrativeEvidencePack）
# ===========================================================================

# 证据包默认上限（草案开放问题 2 的实现默认值；截断必须显式标注、不得冒充全量）
NARRATIVE_MAX_ITEMS_PER_CATEGORY = 8
NARRATIVE_MAX_QUOTE_CHARS = 200
NARRATIVE_MAX_FACTS_PER_ITEM = 3

# 短别名 token 形态。格式层把大小写变体也识别为“别名提及”，但只有契约
# 规定的 ASCII 大写形态可绑定、可展开；因此 o1 不会被静默归一化成 O1。
_NARRATIVE_ALIAS_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_Ａ-Ｚａ-ｚ０-９])"
    r"[ORForfＯＲＦｏｒｆ][0-9０-９]+"
    r"(?![A-Za-z0-9_Ａ-Ｚａ-ｚ０-９])"
)
_CANONICAL_ALIAS_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])[ORF][0-9]+(?![A-Za-z0-9_])"
)
_ALIAS_GROUP_CONTENT_RE = re.compile(
    r"(?:[ORF][0-9]+)(?:\s*[,，、]\s*[ORF][0-9]+)*"
)
_BRACKETED_TEXT_RE = re.compile(r"\[[^\]\r\n]*\]")


@dataclass
class NarrativeEvidencePack:
    """面向叙述节的证据包（报告契约 v2 修订 3）。

    程序从 deterministic retrieval/closure 产物构造；对模型只暴露短别名
    （[O*] obligation / [R*] rule card / [F*] fact），`alias_map` 是别名→真实 ID
    的单向映射，随 run_audit 落盘。只来自 agent 可见的 RuleSlice / FactPack /
    ClosureValidationResult，不引入 W2/evaluator 输入（blind 红线不变）。
    """

    run_id: str
    world_id: str
    building_id: str
    allow_stop: bool
    summary: Dict[str, Any] = field(default_factory=dict)
    key_items: List[Dict[str, Any]] = field(default_factory=list)
    rule_cards: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[Dict[str, Any]] = field(default_factory=list)
    unavailable: List[str] = field(default_factory=list)
    truncated: Dict[str, int] = field(default_factory=dict)
    alias_map: Dict[str, str] = field(default_factory=dict)

    def to_model_payload(self) -> Dict[str, Any]:
        """模型可见的证据包 payload（随 run_closure_verification 返回）。"""
        payload = {
            "contract": "report_contract_v3",
            "summary": dict(self.summary),
            "key_items": list(self.key_items),
            "rule_cards": list(self.rule_cards),
            "facts": list(self.facts),
            "unavailable": list(self.unavailable),
            "truncated": dict(self.truncated),
            "usage_rules": [
                "text 可自然提及别名，但提及 token 必须属于本点 evidence_aliases",
                "evidence_aliases 只使用本包 key_items 中列出的裸别名",
                "每点只写事实限制、疑似风险、证据缺口或人工复核动作",
                "权威计数以程序渲染的报告骨架为准；证据包截断项不代表全量",
            ],
        }

        forbidden_id_fields = {
            "obligation_id", "rule_card_id", "fact_id",
            "source_rule_card_id", "evidence_fact_ids", "copyable_handle",
        }
        aliases_by_id = {
            real_id: f"[{alias}]" for alias, real_id in self.alias_map.items()
        }

        def _redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: _redact(item)
                    for key, item in value.items()
                    if key not in forbidden_id_fields
                }
            if isinstance(value, list):
                return [_redact(item) for item in value]
            if isinstance(value, str):
                for real_id in sorted(aliases_by_id, key=len, reverse=True):
                    value = value.replace(real_id, aliases_by_id[real_id])
            return value

        return _redact(payload)


def _first_quote_for_card(rule_slice: Optional[RuleSlice], card: Any) -> Optional[str]:
    """取 rule card 的第一条法规原文短引文（RuleSlice.source_quotes 优先）。"""
    if rule_slice is not None:
        for sq in rule_slice.source_quotes:
            if sq.rule_card_id == card.rule_card_id and (sq.text or "").strip():
                return sq.text.strip()
    for quote in getattr(card, "source_quote", None) or []:
        if isinstance(quote, dict) and str(quote.get("text") or "").strip():
            return str(quote["text"]).strip()
    text = (getattr(card, "normalized_rule_text", "") or "").strip()
    return text or None


def _copyable_evidence_handle(
    obligation_alias: str,
    rule_alias: Optional[str],
    fact_aliases: List[str],
) -> str:
    """只用本项短别名拼模型可复制把手，不附加判断性叙述。"""
    related = []
    if rule_alias:
        related.append(f"关联规则 [{rule_alias}]")
    if fact_aliases:
        related.append(f"相关事实 [{', '.join(fact_aliases)}]")
    suffix = f"（{'；'.join(related)}）" if related else ""
    return f"[{obligation_alias}]{suffix}"


def build_narrative_evidence_pack(
    closure_result: ClosureValidationResult,
    rule_slice: Optional[RuleSlice] = None,
    fact_pack: Optional[FactPack] = None,
    *,
    max_items_per_category: int = NARRATIVE_MAX_ITEMS_PER_CATEGORY,
    max_quote_chars: int = NARRATIVE_MAX_QUOTE_CHARS,
    max_facts_per_item: int = NARRATIVE_MAX_FACTS_PER_ITEM,
) -> NarrativeEvidencePack:
    """从权威闭包产物确定性构造叙述证据包（契约 v2 修订 3）。

    重点项选择 / 排序 / 截断 / “未取到项”标记全部由程序完成并可审计：
    - 类别优先级 violated → open → blocked，类内按 high-risk、severity 降序，
      再按 obligation_id 字典序；
    - 每类最多 `max_items_per_category` 条，截断计入 `truncated` 并写入
      `unavailable`（截断不得被表述为全量）；
    - high-risk 以 `high_risk` 旗标标注在命中的重点项上
      （closure_result.high_risk_items 里可解析出 obligation_id 的项）。
    """
    summary = closure_result.closure_summary
    obligations = closure_result.obligation_set.obligations

    def _category(o: Any) -> Optional[str]:
        if o.closure_status == "closed" and o.satisfaction_status == "violated":
            return "violated"
        if o.closure_status == "open":
            return "open"
        if o.closure_status == "blocked":
            return "blocked"
        return None

    high_risk_ids = {
        str(item.get("obligation_id"))
        for item in closure_result.high_risk_items
        if isinstance(item, dict) and item.get("obligation_id")
    }
    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    high_risk_severity: Dict[str, int] = {}
    for item in closure_result.high_risk_items:
        if not isinstance(item, dict) or not item.get("obligation_id"):
            continue
        oid = str(item["obligation_id"])
        rank = severity_order.get(str(item.get("severity") or "").lower(), 0)
        high_risk_severity[oid] = max(high_risk_severity.get(oid, 0), rank)

    unavailable: List[str] = []
    truncated: Dict[str, int] = {}
    selected: List[Any] = []
    for category in ("violated", "open", "blocked"):
        matched = sorted(
            (o for o in obligations if _category(o) == category),
            key=lambda o: (
                -(o.obligation_id in high_risk_ids),
                -high_risk_severity.get(o.obligation_id, 0),
                o.obligation_id,
            ),
        )
        omitted = len(matched) - max_items_per_category
        if omitted > 0:
            truncated[category] = omitted
            unavailable.append(
                f"{category} 项共 {len(matched)} 条，证据包仅列前 "
                f"{max_items_per_category} 条（截断，不代表全量）"
            )
        selected.extend(matched[:max_items_per_category])

    alias_map: Dict[str, str] = {}
    rule_card_alias: Dict[str, str] = {}
    fact_alias: Dict[str, str] = {}
    cards_by_id = {
        c.rule_card_id: c
        for c in (rule_slice.candidate_rule_cards if rule_slice else [])
    }
    facts_by_id = {f.fact_id: f for f in (fact_pack.facts if fact_pack else [])}

    key_items: List[Dict[str, Any]] = []
    rule_cards: List[Dict[str, Any]] = []
    facts: List[Dict[str, Any]] = []

    for idx, ob in enumerate(selected, start=1):
        o_alias = f"O{idx}"
        alias_map[o_alias] = ob.obligation_id
        category = _category(ob) or "open"

        rc_id = ob.source_rule_card_id
        if rc_id and rc_id not in rule_card_alias:
            r_alias = f"R{len(rule_card_alias) + 1}"
            rule_card_alias[rc_id] = r_alias
            alias_map[r_alias] = rc_id
            card = cards_by_id.get(rc_id)
            quote = _first_quote_for_card(rule_slice, card) if card else None
            if quote and len(quote) > max_quote_chars:
                quote = quote[:max_quote_chars] + "…"
                unavailable.append(f"rule card {rc_id} 引文超长已截断")
            if not quote:
                unavailable.append(f"rule card {rc_id} 未取得可用原文引文")
            rule_cards.append(
                {
                    "alias": r_alias,
                    "rule_card_id": rc_id,
                    "quote": quote or "（未取得引文）",
                }
            )

        f_aliases: List[str] = []
        evidence_ids = list(ob.evidence_fact_ids)
        for fid in evidence_ids[:max_facts_per_item]:
            if fid not in fact_alias:
                f_alias = f"F{len(fact_alias) + 1}"
                fact_alias[fid] = f_alias
                alias_map[f_alias] = fid
                atom = facts_by_id.get(fid)
                if atom is not None:
                    facts.append(
                        {
                            "alias": f_alias,
                            "fact_id": fid,
                            "slot_id": atom.slot_id,
                            "value": atom.value_json,
                            "unit": atom.unit,
                        }
                    )
                else:
                    facts.append(
                        {"alias": f_alias, "fact_id": fid, "slot_id": None,
                         "value": None, "unit": None}
                    )
                    unavailable.append(f"证据 fact {fid} 未在本次 FactPack 内取得")
            f_aliases.append(fact_alias[fid])
        if len(evidence_ids) > max_facts_per_item:
            unavailable.append(
                f"[{o_alias}] 证据 fact 共 {len(evidence_ids)} 条，"
                f"证据包仅列前 {max_facts_per_item} 条（截断）"
            )
        if category == "open" and not evidence_ids and ob.slot_ids:
            unavailable.append(
                f"[{o_alias}] 所需 slot {list(ob.slot_ids)[:3]} 未取得对应 fact"
            )

        key_items.append(
            {
                "alias": o_alias,
                "obligation_id": ob.obligation_id,
                "category": category,
                # 权威原始状态随包携带（closure 结果本就 agent 可见，非 W2）——
                # 供 v4 层对 category 做三重一致性互证（codex 聚合审核阻断#1：
                # category 单字段可被伪权威项绕过）。
                "closure_status": str(ob.closure_status),
                "satisfaction_status": str(ob.satisfaction_status),
                "high_risk": ob.obligation_id in high_risk_ids,
                "rule_card_alias": rule_card_alias.get(rc_id),
                "kind": str(ob.kind),
                "reason_code": ob.open_reason_code or ob.blocked_reason_code,
                "slots": list(ob.slot_ids)[:3],
                "observed": ob.observed_value_json,
                "threshold": ob.threshold_value_json or ob.expected_value_json,
                "fact_aliases": f_aliases,
                "evidence_aliases": [
                    o_alias,
                    *([rule_card_alias[rc_id]] if rc_id in rule_card_alias else []),
                    *f_aliases,
                ],
                "copyable_handle": _copyable_evidence_handle(
                    o_alias, rule_card_alias.get(rc_id), f_aliases
                ),
            }
        )

    return NarrativeEvidencePack(
        run_id=closure_result.run_id,
        world_id=closure_result.obligation_set.world_id,
        building_id=closure_result.obligation_set.building_id,
        allow_stop=closure_result.allow_stop,
        summary={
            "total_obligations": summary.total_obligations,
            "closed_count": summary.closed_count,
            "open_count": summary.open_count,
            "blocked_count": summary.blocked_count,
            "satisfied_count": summary.satisfied_count,
            "violated_count": summary.violated_count,
            "unknown_count": summary.unknown_count,
            "not_applicable_count": summary.not_applicable_count,
            "high_risk_item_count": len(closure_result.high_risk_items),
            "allow_stop": closure_result.allow_stop,
            "stop_reason": summary.stop_reason,
        },
        key_items=key_items,
        rule_cards=rule_cards,
        facts=facts,
        unavailable=unavailable,
        truncated=truncated,
        alias_map=alias_map,
    )


# 行内最小转义集：只转义 CommonMark 在**行内**真会解析的控制字符。
# 早前的宽集把 . _ ( ) { } # + ! ~ - 一并转义，导致法规/槽位标识符被打成
# `artifact\.record\.test\_or\_material\_witness`（单份报告 \_ 9,752 处、
# \. 534 处），可读性差且渲染器不同还可能直接显示反斜杠。收窄依据：
#   - `.` `(` `)` `{` `}` `!` 行内从不触发结构；
#   - `_` 词内不构成强调（CommonMark intraword underscore），标识符安全；
#   - `#` `+` `-` 只在**行首**才是标题/列表标记，由 _escape_line_leading 处理；
#   - `~` 需成对才是删除线，单个无害。
_MARKDOWN_ESCAPE_RE = re.compile(r"([\\\x60*\[\]<>|])")
# 行首结构标记：仅当出现在行首（可带缩进）时才需转义。
_MARKDOWN_LINE_LEADING_RE = re.compile(r"^(\s*)([#+\-~]|\d+\.)", re.MULTILINE)


def _escape_markdown_text(value: str) -> str:
    """转义模型槽位中的 Markdown 控制字符，保持可见文本字面值。

    分两层：行内最小集（反斜杠/反引号/星号/方括号/尖括号/竖线）+ 行首结构
    标记（标题、无序列表、有序列表、删除线起手）。标识符里的 `.` `_` 不再
    被转义，报告可读性显著改善且不引入结构歧义。
    """
    escaped = _MARKDOWN_ESCAPE_RE.sub(r"\\\1", value)
    return _MARKDOWN_LINE_LEADING_RE.sub(r"\1\\\2", escaped)


def extract_narrative_alias_tokens(text: str) -> List[str]:
    """按首次出现顺序提取别名提及；保留原始大小写以便做精确子集比较。"""
    return list(dict.fromkeys(_NARRATIVE_ALIAS_TOKEN_RE.findall(text)))


def _expand_narrative_alias_references(
    text: str,
    alias_map: Dict[str, str],
    *,
    escape_markdown: bool,
) -> tuple[str, List[str]]:
    """展开裸别名/规范方括号组，并返回实际展开的别名。

    任意非规范方括号内容（尤其 ``[O1:xxx]`` 伪展开）整段按作者字面值
    保留，不在其内部做二次 token 替换。
    """
    expanded: List[str] = []

    def literal(value: str) -> str:
        return _escape_markdown_text(value) if escape_markdown else value

    def rendered_alias(alias: str) -> str:
        if alias not in expanded:
            expanded.append(alias)
        real_id = alias_map[alias]
        safe_real_id = _escape_markdown_text(real_id) if escape_markdown else real_id
        return f"[{alias}:{safe_real_id}]"

    def expand_bare(value: str) -> str:
        parts: List[str] = []
        cursor = 0
        for match in _CANONICAL_ALIAS_TOKEN_RE.finditer(value):
            parts.append(literal(value[cursor : match.start()]))
            alias = match.group(0)
            parts.append(rendered_alias(alias) if alias in alias_map else literal(alias))
            cursor = match.end()
        parts.append(literal(value[cursor:]))
        return "".join(parts)

    parts: List[str] = []
    cursor = 0
    for match in _BRACKETED_TEXT_RE.finditer(text):
        parts.append(expand_bare(text[cursor : match.start()]))
        bracketed = match.group(0)
        content = bracketed[1:-1]
        aliases = re.findall(r"[ORF][0-9]+", content)
        if (
            _ALIAS_GROUP_CONTENT_RE.fullmatch(content) is not None
            and aliases
            and all(alias in alias_map for alias in aliases)
        ):
            parts.append(
                "[" + ", ".join(
                    rendered_alias(alias)[1:-1] for alias in aliases
                ) + "]"
            )
        else:
            parts.append(literal(bracketed))
        cursor = match.end()
    parts.append(expand_bare(text[cursor:]))
    return "".join(parts), expanded


def expand_narrative_aliases(
    text: str,
    pack_or_alias_map: NarrativeEvidencePack | Dict[str, str],
    *,
    escape_markdown: bool = False,
) -> str:
    """把已绑定的合法短别名展开为 ``[O1:<真实 ID>]``。

    v3 同时支持正文里的裸别名和规范方括号别名。``escape_markdown=True``
    用于最终模型槽位：只让程序生成的展开标记保留 Markdown 形态，其余作者
    文本（含伪展开形态）全部按字面转义。
    """
    alias_map = (
        pack_or_alias_map.alias_map
        if isinstance(pack_or_alias_map, NarrativeEvidencePack)
        else pack_or_alias_map
    )
    rendered, _ = _expand_narrative_alias_references(
        text, alias_map, escape_markdown=escape_markdown
    )
    return rendered


def render_structured_narrative_points(
    points: List[Dict[str, Any]], alias_map: Dict[str, str]
) -> str:
    """契约 v3 确定性逐点渲染；点序与每点别名序均保持提交顺序。"""
    lines: List[str] = []
    for point in points:
        rendered_text = expand_narrative_aliases(
            point["text"], alias_map, escape_markdown=True
        )
        _, expanded_aliases = _expand_narrative_alias_references(
            point["text"], alias_map, escape_markdown=False
        )
        supplemental_aliases = [
            alias
            for alias in point["evidence_aliases"]
            if alias not in expanded_aliases
        ]
        suffix = ""
        if supplemental_aliases:
            evidence = "、".join(
                "[" + alias + ":" + _escape_markdown_text(alias_map[alias]) + "]"
                for alias in supplemental_aliases
            )
            suffix = f"（证据：{evidence}）"
        lines.append(f"- {rendered_text}{suffix}")
    return "\n".join(lines)

def render_deterministic_narrative(pack: NarrativeEvidencePack) -> str:
    """确定性叙述槽位模板（契约 v2 修订 4；两条 allow_stop 分支各一形态）。

    模型叙述未被接纳（拒绝耗尽 / 超时 / 未提交可用分析）时填入分析节槽位。
    不变量（按构造洁净）：
    - 输出守卫：禁止话术只以否定前缀（“非”）形态出现；
    - 叙述节闸：key_items 存在时每个要点都带证据别名；key_items 为空时
      alias_map 也为空，证据把手检查按定义跳过。
    """
    lines = ["### 确定性叙述（程序模板，未采用模型分析）", ""]
    if pack.key_items:
        for item in pack.key_items:
            alias = f"[{item['alias']}]"
            rc = (
                f"（rule card [{item['rule_card_alias']}]）"
                if item.get("rule_card_alias")
                else ""
            )
            category = item["category"]
            if category == "violated":
                lines.append(
                    f"- {alias}{rc} 疑似未满足：observed="
                    f"{item.get('observed') or '—'}，threshold="
                    f"{item.get('threshold') or '—'}；建议人工审查员优先复核该项证据链。"
                )
            elif category == "open":
                lines.append(
                    f"- {alias}{rc} 未闭合（open，原因码 "
                    f"{item.get('reason_code') or '—'}）：建议人工补充相关资料后重新评估。"
                )
            else:
                lines.append(
                    f"- {alias}{rc} 验证器无法处理（blocked，原因码 "
                    f"{item.get('reason_code') or '—'}）：需人工介入检查资料与规则适用性。"
                )
    elif pack.allow_stop:
        lines.append(
            "- 闭包验证器确认 open=0、blocked=0，资料闭包已完成；"
            "满足性计数以上文权威闭包概览为准，本节为辅助说明，非最终裁决。"
        )
    else:
        lines.append(
            "- 本次闭包验证未通过（详见上文权威闭包概览与未闭合项表）："
            "建议按表列项补充资料后重新评估；本节为辅助说明，非最终裁决。"
        )
    lines.append("")
    return "\n".join(lines)


# ===========================================================================
# 六、报告契约 v2 —— 程序骨架渲染（唯一分析节槽位）
# ===========================================================================

# v2 分析节槽位节名（契约 v2 §7.4.1 / §7.4.2 固定）
ANALYSIS_SECTION_TITLE_ALLOW_STOP = "分析与建议（模型生成）"
ANALYSIS_SECTION_TITLE_INCOMPLETE = "未闭合原因与补充资料建议（模型生成）"


_AGG_TOP_N = 10

# 只匹配 O 别名的运行期 24 位哈希，前后允许分组边界（`[O1:hash, R1:..]` 也命中），
# 不含 R/F（其展开是语义 id，非运行期哈希，且避免伪映射行）。
_OBLIGATION_ID_IN_TEXT_RE = re.compile(r"\b(O\d+):([0-9a-f]{24})\b")


def _build_display_ref_map(
    obligations: List[Any], identity_manifest: Optional[List[Dict[str, Any]]] = None
) -> tuple[Dict[str, str], Dict[str, str]]:
    """义务 obligation_id → (display_ref, canonical_identity_hash)（spec §7.4.4 E-4.2）。

    **display_ref = `OB-<完整 canonical_identity_hash>`**——直接用 identity-v5 的
    全字段权威哈希本体,**不截断、不做碰撞检测、不做集合相关的回退**（2026-07-23
    codex 三轮审出:任何"撞前缀就回退"都依赖当前报告义务集合、破坏集合无关性;
    截断前缀又有碰撞风险。用完整 canonical hash 则**绝对集合无关、唯一、跨批稳定**,
    代价仅是编号略长,正确性优先）。

    **fail-closed（manifest 缺 canonical hash）**:不派 `OB-` 稳定编号（那会假装
    稳定却可能碰撞/漂移）,直接用运行期 `obligation_id` 并加 `RUN-` 前缀明确标注
    "此项无稳定展示编号、跨批不保证"。收官批产物均带 identity_manifest,此为防御路径。

    display_ref 仅用于人读呈现,绝不替代 obligation_id 成身份键、绝不进 dedupe/identity。
    返回 (obligation_id → display_ref, obligation_id → canonical_identity_hash)。
    覆盖**传入的全部义务**。
    """
    cano_by_oid: Dict[str, str] = {}
    for entry in (identity_manifest or []):
        oid = entry.get("obligation_id")
        ch = entry.get("canonical_identity_hash")
        if oid and ch:
            cano_by_oid[oid] = ch
    ref_map: Dict[str, str] = {}
    out_cano: Dict[str, str] = {}
    for ob in obligations:
        ch = cano_by_oid.get(ob.obligation_id)
        if ch:
            ref_map[ob.obligation_id] = f"OB-{ch.upper()}"
            out_cano[ob.obligation_id] = ch
        else:
            # fail-closed:无权威 canonical hash → 不假装稳定,明确标注运行期编号
            ref_map[ob.obligation_id] = f"RUN-{ob.obligation_id}"
            out_cano[ob.obligation_id] = "（无 identity_manifest，无稳定编号）"
    return ref_map, out_cano


def _swap_ids_for_display_refs(text: str, ref_map: Dict[str, str]) -> str:
    """把已渲染文本里 O 别名展开的 `O1:24位obligation_id` 换成 `O1:display_ref`（E-4.2）。

    支持分组形态 `[O1:hash, R1:rc.x]`；只换 O 别名的运行期哈希，R/F 语义 id 不动。
    """
    def repl(m):
        alias, oid = m.group(1), m.group(2)
        return f"{alias}:{ref_map.get(oid, oid)}"
    return _OBLIGATION_ID_IN_TEXT_RE.sub(repl, text)


def _violated_agg_rows(items: List[Any], guard_safe_data: bool = False) -> List[str]:
    """violated 项按 rule_card 聚合 top-N 主视图行（spec §7.4.4 E-4.1）。"""
    from collections import Counter
    counts = Counter(o.source_rule_card_id for o in items)
    ordered = counts.most_common()
    rows = [f"| {_fmt_value(rc)} | {n} |" for rc, n in ordered[:_AGG_TOP_N]]
    rest = ordered[_AGG_TOP_N:]
    if rest:
        rows.append(f"| （其余 {len(rest)} 张规则卡，共 {sum(n for _, n in rest)} 条） | "
                    f"{sum(n for _, n in rest)} |")
    return rows


def _aggregate_unclosed_rows(
    items: List[Any], reason_key: str, *, guard_safe_data: bool = False
) -> List[str]:
    """聚合概览行（spec §7.4.4 E-4.1）：按 (rule_card, reason_code) 分组计数，
    只在主视图列**条数最多的前 `_AGG_TOP_N` 组**，其余归一行"其余 M 组 N 条"。

    全程序确定性聚合，不经 LLM、不改判定。完整逐条表仍在折叠块内一条不少，
    此处只为主视图压缩：几百个规则卡多数各 1-2 条，全列反而更长，故封顶 top-N。
    """
    from collections import defaultdict
    groups: Dict[tuple, List[Any]] = defaultdict(list)
    for ob in items:
        key = (ob.source_rule_card_id, str(getattr(ob, reason_key) or "—"))
        groups[key].append(ob)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0] or ""))
    rows: List[str] = []
    for (rc, reason), obs in ordered[:_AGG_TOP_N]:
        if guard_safe_data:
            targets = "见权威义务记录"
        else:
            frags = sorted({o.fragment_id for o in obs if o.fragment_id})
            # 片段短标签:取 FRG-<楼>-<部位>-NN-MM 的部位+编号段(倒数 3 段),
            # 无歧义;>3 个只报计数。(旧 `split[-2:][0]` 取错段致不同片段同标签)
            def _frag_label(fid: str) -> str:
                parts = fid.split("-")
                return "-".join(parts[-3:]) if len(parts) >= 3 else fid
            targets = (
                f"{len(frags)} 个片段" if len(frags) > 3
                else "、".join(_frag_label(f) for f in frags)
                or "建筑级"
            )
        rows.append(f"| {_fmt_value(rc)} | {_fmt_value(reason)} | {len(obs)} | {targets} |")
    rest = ordered[_AGG_TOP_N:]
    if rest:
        rest_obl = sum(len(obs) for _, obs in rest)
        rows.append(
            f"| （其余 {len(rest)} 组，共 {rest_obl} 条，见完整台账） | — | {rest_obl} | — |"
        )
    return rows


def _ob_row(ob: Any, reason_key: str, *, guard_safe_data: bool = False) -> str:
    """未闭合项表单行（从权威 Obligation 对象渲染，不经模型）。"""
    target_parts = [] if guard_safe_data else [
        p for p in (ob.fragment_id, ob.component_id) if p
    ]
    target = " / ".join(target_parts) if target_parts else "建筑级"
    return (
        f"| {_fmt_value(ob.obligation_id)} "
        f"| {target} "
        f"| {_fmt_value(ob.source_rule_card_id)} "
        f"| {_fmt_value(ob.kind) if not guard_safe_data else '见权威义务记录'} "
        f"| {_fmt_value(getattr(ob, reason_key)) if not guard_safe_data else '见权威义务记录'} |"
    )


def render_contract_v2_report(
    result: ClosureValidationResult,
    *,
    world_id: str,
    building_id: str,
    generated_at: str,
    kg_snapshot_id: str = "",
    rulecard_bundle_id: str = "",
    fact_source_tables: Optional[List[str]] = None,
    rule_families: Optional[List[Dict[str, Any]]] = None,
    evidence_pack: Optional[NarrativeEvidencePack] = None,
    analysis_markdown: str = "",
    analysis_is_llm: bool = False,
    guard_safe_data: bool = False,
    contract_version: int = 3,
) -> str:
    """报告契约 v2 组合终稿：程序确定性渲染全部权威骨架 + 唯一分析节槽位。

    骨架内容（契约 v2 修订 1 的 9 项）全部从程序持有的权威对象渲染：标题按
    `allow_stop` 分支、免责说明、run/building/source scope、权威闭包概览、
    未闭合项表（或 open/blocked=0 确认）、violated/high-risk 程序计数表、
    法规引用 / rule card 短引文 / fact refs、分析节槽位、人工复核提示。
    `analysis_markdown`（已接纳的模型分析或确定性叙述模板，别名已展开）是
    唯一模型可影响的槽位；插入前一级标题降三级，防与权威 H1 打架。
    """
    summary = result.closure_summary
    allow_stop = result.allow_stop
    obligations = result.obligation_set.obligations

    title = (
        "# MBIS 辅助审查报告（非最终裁决）"
        if allow_stop
        else "# MBIS 闭包未完成说明（非最终裁决）"
    )
    slot_title = (
        ANALYSIS_SECTION_TITLE_ALLOW_STOP
        if allow_stop
        else ANALYSIS_SECTION_TITLE_INCOMPLETE
    )

    def top_five(counts: Dict[str, int]) -> str:
        rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        return "、".join(f"{reason}={count}" for reason, count in rows) or "无"

    lines: List[str] = [title, ""]
    lines.append(f"> {_DISCLAIMER}")
    lines.append(
        "> 本报告骨架（标题 / 计数 / 表格 / 引用）由程序确定性渲染"
        f"（report contract v{contract_version}）；模型只提供结构化点列，"
        "权威字段不由模型产出。"
    )
    lines.append("")
    if not allow_stop:
        lines.append("本次资料闭包验证未通过，不能生成完整辅助审查报告。")
        lines.append("")

    # --- 评估范围（run / building / source scope）---
    lines.append("## 评估范围")
    lines.append("")
    lines.append(f"- run_id: {result.run_id}")
    lines.append(f"- world_id: {world_id}")
    lines.append(f"- building_id: {building_id}")
    lines.append(f"- KG snapshot: {kg_snapshot_id or '—'}")
    lines.append(
        "- 事实来源: "
        + (", ".join(fact_source_tables)
           if fact_source_tables
           else "WorldBundle / SidecarRuntimeBundle")
    )
    lines.append(f"- 法规 / rule card 版本: {rulecard_bundle_id or '—'}")
    lines.append(f"- 运行时间戳: {generated_at}")
    lines.append("")
    if rule_families:
        # v4 收官形态把 40+ 行 family 明细表折进 <details>（2026-07-23 codex 聚合
        # 设计商议：不折叠时 v4 主视图压不进 A 门 180 行预算）；v3 保持原样。
        if contract_version >= 4:
            total_cards = sum(
                int(fam.get("rule_card_count") or 0) for fam in rule_families)
            lines.append(
                f"- 适用法规切片：{len(rule_families)} 个 family、"
                f"{total_cards} 张 rule card（明细见下折叠表）")
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>family 明细表（程序渲染，点击展开）</summary>")
            lines.append("")
        lines.append("| family | rule_card_count | source clauses |")
        lines.append("|---|---:|---|")
        for fam in rule_families:
            lines.append(
                f"| {_fmt_value(fam.get('family'))} "
                f"| {_fmt_value(fam.get('rule_card_count'))} "
                f"| {_fmt_value(fam.get('source_clauses')) if not guard_safe_data else '见 rule card 索引'} |"
            )
        if contract_version >= 4:
            lines.append("")
            lines.append("</details>")
        lines.append("")

    # --- 权威闭包概览 ---
    lines.append("## 权威闭包概览")
    lines.append("")
    lines.append("> 本节由系统确定性生成；以下字段以闭包验证器结果为准。")
    lines.append("")
    lines.append(f"- total: {summary.total_obligations}")
    lines.append(f"- open: {summary.open_count}")
    lines.append(f"- blocked: {summary.blocked_count}")
    lines.append(f"- closed: {summary.closed_count}")
    lines.append(f"- satisfied: {summary.satisfied_count}")
    lines.append(f"- violated: {summary.violated_count}")
    lines.append(f"- unknown: {summary.unknown_count}")
    lines.append(f"- not_applicable: {summary.not_applicable_count}")
    lines.append(f"- allow_stop: {result.allow_stop}")
    lines.append(f"- stop_reason: {summary.stop_reason}")
    lines.append(f"- open reason top-5: {top_five(summary.open_reason_counts)}")
    lines.append(f"- blocked reason top-5: {top_five(summary.blocked_reason_counts)}")
    lines.append("")

    # --- 未闭合项表 或 open/blocked=0 确认 ---
    lines.append("## 未闭合项")
    lines.append("")
    open_items = [o for o in obligations if o.closure_status == "open"]
    blocked_items = [o for o in obligations if o.closure_status == "blocked"]
    if summary.open_count == 0 and summary.blocked_count == 0:
        if allow_stop:
            lines.append(
                "> 确认：open obligations = 0，blocked obligations = 0，资料闭包完成。"
            )
        else:
            lines.append(
                "> open obligations = 0，blocked obligations = 0，但闭包验证未通过"
                f"（stop_reason={summary.stop_reason}），详见权威闭包概览。"
            )
        lines.append("")
    else:
        # --- 主视图:聚合概览(spec §7.4.4 E-4.1,程序确定性,不经 LLM)---
        lines.append("### 未闭合项聚合概览（按规则卡 × 原因码，主视图）")
        lines.append("")
        lines.append(
            f"open = {summary.open_count}，blocked = {summary.blocked_count}。"
            "完整逐条清单见下方折叠块「未闭合项完整台账」。"
        )
        lines.append("")
        if open_items:
            lines.append("**open（资料缺失，待补充）**")
            lines.append("| rule_card | open_reason | 条数 | 目标范围 |")
            lines.append("|---|---|---:|---|")
            lines.extend(_aggregate_unclosed_rows(
                open_items, "open_reason_code", guard_safe_data=guard_safe_data))
            lines.append("")
        if blocked_items:
            lines.append("**blocked（验证器无法处理，需人工介入）**")
            lines.append("| rule_card | blocked_reason | 条数 | 目标范围 |")
            lines.append("|---|---|---:|---|")
            lines.extend(_aggregate_unclosed_rows(
                blocked_items, "blocked_reason_code", guard_safe_data=guard_safe_data))
            lines.append("")

        # --- 完整台账:折叠(spec §7.4.4 E-4.1,骨架第 5 项,逐条一字不少)---
        lines.append("<details>")
        lines.append("<summary>未闭合项完整台账（逐条，程序渲染，点击展开）</summary>")
        lines.append("")
        lines.append("### open obligations（资料缺失，待补充）")
        lines.append("")
        if open_items:
            lines.append("| obligation_id | target | rule_card | kind | open_reason |")
            lines.append("|---|---|---|---|---|")
            for ob in open_items:
                lines.append(_ob_row(ob, "open_reason_code", guard_safe_data=guard_safe_data))
        else:
            lines.append("（无 open obligations）")
        lines.append("")
        lines.append("### blocked obligations（验证器无法处理，需人工介入）")
        lines.append("")
        if blocked_items:
            lines.append(
                "| obligation_id | target | rule_card | kind | blocked_reason |"
            )
            lines.append("|---|---|---|---|---|")
            for ob in blocked_items:
                lines.append(_ob_row(ob, "blocked_reason_code", guard_safe_data=guard_safe_data))
        else:
            lines.append("（无 blocked obligations）")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # display_ref 映射(spec §7.4.4 E-4.2):由权威 canonical_identity_hash 派生,
    # 供本节高风险表、分析节、复核提示节统一使用,运行期哈希移出人读主视图。
    identity_manifest = getattr(result.obligation_set, "identity_manifest", None)
    display_ref_map, cano_by_oid = _build_display_ref_map(obligations, identity_manifest)

    # --- violated / high-risk 项与程序计数 ---
    lines.append("## 疑似未满足 / 高风险项")
    lines.append("")
    lines.append(
        f"程序计数：violated = {summary.violated_count}，"
        f"high_risk = {len(result.high_risk_items)}。"
        "下表所列为闭包验证显示的疑似未满足项，建议人工复核；"
        "本表不构成最终不合规结论。"
    )
    lines.append("")
    violated_items = [
        o for o in obligations
        if o.closure_status == "closed" and o.satisfaction_status == "violated"
    ]
    # 主视图:violated 按 rule_card 聚合 top-N（spec §7.4.4 E-4.1）
    if violated_items:
        lines.append("**疑似未满足聚合（按规则卡，主视图；完整逐条见下方折叠块）**")
        lines.append("| rule_card | 条数 |")
        lines.append("|---|---:|")
        lines.extend(_violated_agg_rows(violated_items, guard_safe_data))
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>疑似未满足完整台账（逐条，程序渲染，点击展开）</summary>")
        lines.append("")
    lines.append("| obligation_id | rule_card | observed | required | note |")
    lines.append("|---|---|---|---|---|")
    for ob in violated_items:
        lines.append(
            f"| {_fmt_value(ob.obligation_id)} "
            f"| {_fmt_value(ob.source_rule_card_id)} "
            f"| {_fmt_value(ob.observed_value_json) if not guard_safe_data else '见权威义务记录'} "
            f"| {_fmt_value(ob.threshold_value_json or ob.expected_value_json) if not guard_safe_data else '见权威义务记录'} "
            f"| {_fmt_value(ob.notes) if not guard_safe_data else '建议人工复核'} |"
        )
    if not violated_items:
        lines.append("| — | — | — | — | 未发现疑似未满足项 |")
    lines.append("")
    if violated_items:
        lines.append("</details>")
        lines.append("")
    if result.high_risk_items:
        lines.append("额外高风险项（verifier high_risk_items，top-10）：")
        lines.append("| display_ref | family | severity | reason |")
        lines.append("|---|---|---|---|")
        for item in result.high_risk_items[:10]:
            raw_oid = str(item.get("obligation_id") or "")
            # 用 display_ref 替代运行期哈希前 12 位(spec §7.4.4 E-4.2)
            dref = display_ref_map.get(raw_oid, raw_oid[:12] or "—")
            reason = (
                _fmt_value(item.get("reason"))
                if not guard_safe_data else "见权威闭包记录"
            )
            lines.append(
                f"| {dref} | {_fmt_value(item.get('source_family_id'))} "
                f"| {_fmt_value(item.get('severity'))} | {reason} |"
            )
        remaining = len(result.high_risk_items) - 10
        if remaining > 0:
            lines.append(f"其余高风险项 {remaining} 条，详见 closure_validation_result.json。")
        lines.append("")

    # --- 法规引用与证据（程序辑录，别名↔真实 ID 对照供人工回查）---
    lines.append("## 法规引用与证据（程序辑录）")
    lines.append("")
    if evidence_pack is not None and (
        evidence_pack.rule_cards or evidence_pack.facts or evidence_pack.unavailable
    ):
        for card in evidence_pack.rule_cards:
            if guard_safe_data:
                lines.append(f"- [{card['alias']}] rule card {card['rule_card_id']}")
            else:
                lines.append(
                    f"- [{card['alias']}] {card['rule_card_id']}：「{card['quote']}」"
                )
        for fact in evidence_pack.facts:
            if guard_safe_data:
                lines.append(f"- [{fact['alias']}] fact {fact['fact_id']}")
            else:
                lines.append(
                    f"- [{fact['alias']}] fact {fact['fact_id']}"
                    f"（slot={_fmt_value(fact.get('slot_id'))}，"
                    f"value={_fmt_value(fact.get('value'))}，"
                    f"unit={_fmt_value(fact.get('unit'))}）"
                )
        if evidence_pack.unavailable and not guard_safe_data:
            lines.append("")
            lines.append("未取得 / 截断项（程序标注，截断不代表全量）：")
            for note in evidence_pack.unavailable:
                lines.append(f"- {note}")
    else:
        lines.append("（本次无重点证据项）")
    lines.append("")

    # --- 唯一分析节槽位 ---
    # display_ref(spec §7.4.4 E-4.2):把分析文本里 O 别名展开的运行期
    # obligation_id 哈希换成由权威 canonical_identity_hash 派生的稳定编号,
    # 运行期哈希移出人读主视图、保留在下方折叠三列映射块与 JSON 产物里。
    # (display_ref_map/cano_by_oid 已在"疑似未满足"节前构造,此处复用。)
    pre_swap = demote_h1_outside_fenced_code((analysis_markdown or "").strip())
    referenced_oids = {m.group(2) for m in _OBLIGATION_ID_IN_TEXT_RE.finditer(pre_swap)}
    lines.append(f"## {slot_title}")
    lines.append("")
    # 规则内容权威性声明。v3(自由文本)：模型转述规则实测残留约 6% 严重错位
    # (EXP-015),故声明"转述仅供参考"。v4(结构化,spec §7.4.5)：模型**不撰写任何
    # 规则内容**,四层全由程序从权威对象组装,声明据实改为"程序确定性组装"。
    if contract_version == 4:
        lines.append(
            "> 本节由程序从权威闭包结果与法规辑录**确定性组装**；模型只选择"
            "需关注的义务与相关证据，**不撰写任何规则/状态/原因文字**。规则原文见"
            "「法规引用与证据（程序辑录）」节，义务/事实/规则绑定由程序确定性核验。"
        )
    else:
        lines.append(
            "> 本节为模型生成的辅助分析。**其中对规则卡要求内容的转述仅供参考、"
            "可能不准确；规则要求的权威内容以上文「法规引用与证据（程序辑录）」节"
            "逐条呈现的原文为准。** 义务/事实/规则的绑定关系由程序确定性核验。"
        )
    lines.append("")
    body = _swap_ids_for_display_refs(pre_swap, display_ref_map)
    lines.append(body if body else "（本节无内容）")
    lines.append("")

    # --- 人工复核提示（spec §7.4.4 E-4.1:主视图聚合 + 前 N 复核动作 + 完整逐条折叠）---
    lines.append("## 人工复核提示")
    lines.append("")
    violated_ids = {str(ob.obligation_id) for ob in violated_items}
    # reviewable_high_risk **排除已在 violated 里的**(high_risk_items 本就含 violated,
    # 防双计——2026-07-23 codex 复审)。
    reviewable_high_risk = [
        item for item in result.high_risk_items
        if str(item.get("severity") or "").lower() in {"medium", "high", "critical"}
        and str(item.get("obligation_id") or "") not in violated_ids
    ]
    if violated_items or reviewable_high_risk:
        from collections import Counter
        rc_counts = Counter(ob.source_rule_card_id for ob in violated_items)
        lines.append(
            f"共 {len(violated_items)} 项疑似未满足需复核，涉及 {len(rc_counts)} 张规则卡"
            f"（另有非 violated 高风险 {len(reviewable_high_risk)} 项）。"
        )
        lines.append("")
        # 主视图:前 N 条复核动作(带 display_ref,E-4.1 要求主视图给前 N 动作)
        lines.append("**优先复核动作（主视图，前 10）**")
        shown = 0
        for ob in violated_items:
            if shown >= _AGG_TOP_N:
                break
            dref = display_ref_map.get(ob.obligation_id, "—")
            lines.append(
                f"- [{dref}] 复核 rule_card {_fmt_value(ob.source_rule_card_id)} "
                "的疑似未满足项。"
            )
            shown += 1
        for item in reviewable_high_risk:
            if shown >= _AGG_TOP_N:
                break
            oid = str(item.get("obligation_id") or "")
            dref = display_ref_map.get(oid, "—")
            lines.append(
                f"- [{dref}] 复核高风险项（severity="
                f"{_fmt_value(item.get('severity'))}）。"
            )
            shown += 1
        total_actions = len(violated_items) + len(reviewable_high_risk)
        if total_actions > shown:
            lines.append(f"- （其余 {total_actions - shown} 项见下方折叠逐条清单）")
        lines.append("")
        # 完整逐条折叠,用 display_ref 而非运行期哈希
        lines.append("<details>")
        lines.append("<summary>逐条复核清单（程序渲染，点击展开）</summary>")
        lines.append("")
        for ob in violated_items:
            dref = display_ref_map.get(ob.obligation_id, ob.obligation_id)
            lines.append(
                f"- 复核 rule_card {_fmt_value(ob.source_rule_card_id)} 的疑似未满足"
                f"义务 [{dref}]（建议人工复核）。"
            )
        for item in reviewable_high_risk:
            oid = str(item.get("obligation_id") or "—")
            dref = display_ref_map.get(oid, oid[:12])
            lines.append(
                f"- 复核高风险义务 [{dref}]"
                f"（severity={_fmt_value(item.get('severity'))}，建议人工复核）。"
            )
        lines.append("")
        lines.append("</details>")
    elif open_items or blocked_items:
        lines.append("- 请人工审查员复核未闭合项表并补充对应建筑事实 / 法规依据。")
    else:
        lines.append("- 闭包验证未发现疑似未满足项；建议人工审查员按常规流程抽检。")
    lines.append("")

    # --- display_ref → obligation_id → canonical_identity_hash 映射(折叠,供下钻)---
    # 覆盖**报告里所有出现 display_ref 的义务**(分析节引用 ∪ 复核逐条 ∪ 高风险 top-10),
    # 保证任一处显示的 display_ref 都能回查(2026-07-23 codex 复审:原只覆盖分析引用)。
    shown_oids = set(referenced_oids)
    shown_oids |= {ob.obligation_id for ob in violated_items}
    shown_oids |= {str(item.get("obligation_id") or "") for item in reviewable_high_risk}
    shown_oids |= {str(item.get("obligation_id") or "")
                   for item in result.high_risk_items[:10]}
    shown_oids = {o for o in shown_oids if o and o in display_ref_map}
    # 映射块只含 id/hash（非敏感字段值），guard_safe_data 下**仍输出**——否则
    # display_ref 显示了却无法下钻（2026-07-23 codex 复审）。
    if shown_oids:
        lines.append("<details>")
        lines.append("<summary>展示编号 → obligation_id → canonical_identity_hash 映射（下钻回查用，覆盖本报告全部展示编号）</summary>")
        lines.append("")
        lines.append("| display_ref | obligation_id | canonical_identity_hash |")
        lines.append("|---|---|---|")
        for oid in sorted(shown_oids, key=lambda o: display_ref_map[o]):
            lines.append(
                f"| {display_ref_map.get(oid, '—')} | {oid} | {cano_by_oid.get(oid, '—')} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append("")
    if allow_stop:
        lines.append("本报告为人工审查辅助材料，非最终裁决。")
    else:
        lines.append(
            "本说明为人工审查辅助材料，非最终裁决。"
            "闭包验证通过前不生成完整辅助审查报告。"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "render_incomplete_closure_notice",
    "render_auxiliary_review_report",
    "render_authoritative_closure_overview",
    "write_report",
    # 报告契约 v2
    "NarrativeEvidencePack",
    "build_narrative_evidence_pack",
    "extract_narrative_alias_tokens",
    "expand_narrative_aliases",
    "render_deterministic_narrative",
    "render_structured_narrative_points",
    "render_contract_v2_report",
    "ANALYSIS_SECTION_TITLE_ALLOW_STOP",
    "ANALYSIS_SECTION_TITLE_INCOMPLETE",
    "NARRATIVE_MAX_ITEMS_PER_CATEGORY",
    "NARRATIVE_MAX_QUOTE_CHARS",
    "NARRATIVE_MAX_FACTS_PER_ITEM",
]
