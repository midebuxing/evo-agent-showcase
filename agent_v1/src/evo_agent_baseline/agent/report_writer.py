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

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from evo_agent_baseline.contracts import (
    ClosureValidationResult,
    FactPack,
    RuleSlice,
)
from evo_agent_baseline.ingest import zh_authority
from evo_agent_baseline.rulecard_assets import DEFAULT_AUTHORITATIVE_BUNDLE_PATH


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


def _field(value: Any, key: str, default: Any = "") -> Any:
    """同时读取字典与契约对象，且把 None 归一为缺省值。"""
    if isinstance(value, dict):
        found = value.get(key, default)
    else:
        found = getattr(value, key, default)
    return default if found is None else found


@lru_cache(maxsize=1)
def _rulecard_clause_index() -> Dict[str, Tuple[str, ...]]:
    """只从权威卡包的结构化来源锚构造「卡号 → 条款号」索引。

    本索引刻意只读 `rule_card_id` 与 `source_section[].section_id`；卡包读取失败时
    返回空映射，由消费者渲染层保留原卡号，绝不猜造条款号。
    """
    try:
        bundle = json.loads(
            DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return {}

    index: Dict[str, Tuple[str, ...]] = {}
    for card in bundle.get("cards", []) or []:
        card_id = str(card.get("rule_card_id") or "").strip()
        if not card_id:
            continue
        clause_ids = {
            str(section.get("section_id") or "").strip().lstrip("§")
            for section in card.get("source_section", []) or []
            if str(section.get("section_id") or "").strip().lstrip("§")
        }
        if clause_ids:
            index[card_id] = tuple(sorted(clause_ids))
    return index


def _source_clause_tuple(obligation: Any) -> Tuple[str, ...]:
    """取义务自身条款号并归一为确定性元组；缺失时返回空元组。"""
    raw_clause_ids = _field(obligation, "source_clause_ids", []) or []
    if isinstance(raw_clause_ids, str):
        raw_clause_ids = [raw_clause_ids]
    clause_ids = {
        str(clause_id).strip().lstrip("§")
        for clause_id in raw_clause_ids
        if str(clause_id).strip().lstrip("§")
    }
    return tuple(sorted(clause_ids))


def _rule_reference(obligation: Any = None, card_id: str = "") -> str:
    """按「义务条款 → 卡包条款 → 原卡号」优先级生成消费者引用。"""
    clause_ids = _source_clause_tuple(obligation) if obligation is not None else ()
    clean_card_id = str(card_id or "").strip()
    if not clause_ids and clean_card_id:
        clause_ids = _rulecard_clause_index().get(clean_card_id, ())
    if clause_ids:
        return "、".join(f"§{clause_id}" for clause_id in clause_ids)
    return clean_card_id or "—"


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

def _mirror_verdict_counts(result: Any) -> Tuple[int, int]:
    """DEBT-083 丁护栏②消费端（2026-08-02 codex 终审硬条件）：镜像一致性副本计数。

    哨兵边界修复的丁（消灭双轨）会让槽角色触发器副本镜像真触发器的判定，notes 带
    `consistency_mirror_of=trigger_slot_ref:<id>`。这些副本**不是独立法规判断**——
    报告须分「原生判定」与「镜像一致性副本」两账，否则同一触发器判定被消费者
    重复计数（批 I 实测 820 条镜像里 `reporting.artifact.prepared` 一槽就 512 条）。
    返回 (mirror_satisfied, mirror_violated)。开关关闭的产物无该标记 ⇒ 恒 (0,0)，
    渲染逐字节不变。
    """
    sat = vio = 0
    try:
        obligations = result.obligation_set.obligations
    except AttributeError:
        return 0, 0
    for o in obligations:
        if "consistency_mirror_of=" in (str(getattr(o, "notes", "") or "")):
            status = str(getattr(o, "satisfaction_status", ""))
            if status == "satisfied":
                sat += 1
            elif status == "violated":
                vio += 1
    return sat, vio


def _verdict_count_line(label: str, total: int, mirror: int) -> str:
    """判定计数行：有镜像时分账（原生 + 镜像一致性副本），无镜像时与旧格式逐字节同。"""
    if mirror:
        return (
            f"- {label}: {total}（原生 {total - mirror} ＋ 镜像一致性副本 {mirror}；"
            "镜像与来源触发器同判，不构成独立法规判断）"
        )
    return f"- {label}: {total}"


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
        # DEBT-083 丁护栏②：镜像一致性副本分账（无镜像时与旧格式逐字节同）。
        _verdict_count_line("satisfied", summary.satisfied_count,
                            _mirror_verdict_counts(result)[0]),
        _verdict_count_line("violated", summary.violated_count,
                            _mirror_verdict_counts(result)[1]),
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

    # 🔴🔴 「你该做什么」必须排在最前（2026-07-30）
    #
    # 改这一处的理由是实测出来的，不是风格偏好：
    # 单栋 49 KB / 约 460 行的文档里，**对专业审查员有行动价值的只有 4 项 / 17 条**，
    # 而它们原先埋在**第 266 行**——前面 235 行是未闭合项逐组穷举、
    # 13 个归因分节，讲的全是**系统自己哪里不知道**（5,071 条，占 99.7%）。
    #
    # 审查员打开文档第一眼看到的是 `run_id` / `allow_stop` / `stop_reason`
    # 和 `artifact_state_not_valid_evidence` 这类原因码——**开发者语言**。
    # 而他要问的只有一句：「这栋楼我现在该去看什么、补什么」。
    #
    # ⚠️ 这不是把系统自述删掉——**一条都没删**，只是换了顺序：
    # 行动项在最前，系统自述与机器标识挪到文末「诊断信息」。
    # 「系统对自己诚实」与「对使用者好用」是两件事，本项目此前只做到了前者。
    obligation_index = _index_unclosed_obligations(open_items, blocked_items)
    _action_first = _render_professional_action_items(
        result.unknown_attribution_by_obligation_id or {},
        obligation_index=obligation_index,
        building_id=str(_g(mr, "building_id") or ""),
    )
    if _action_first:
        lines.extend(_action_first)
        lines.append("")
    lines.append(
        "> 以下为诊断明细。**若你只想知道该做什么，看完上面一节即可**——"
        "其余内容说明系统自身在哪些地方无法给出结论，不需要你补录。"
    )
    lines.append("")

    # 未闭合项 —— 分组聚合，不再逐条穷举
    #
    # 🔴 2026-07-28 改：原实现把每一条 open / blocked 义务各占一行铺出来，
    # 实测**单栋 1,060 KB**（open 182.8 KB / 844 行、blocked 576.7 KB / 2,638 行、
    # 建议 286.8 KB / 1,394 行；而真正有用的归因分节只有 14 KB）。
    # 专业审查员无法把 1 MB 的文档当文档用——这直接违背「消费者优雅可用」。
    #
    # **明细一条都没丢**：全部 open_items / blocked_items 原样在同目录的
    # `closure_validation_result.json` → `machine_readable_report.{open_items,blocked_items}`。
    # 本节只做分组聚合并指路，**不做截断**：每组给出完整计数，
    # 组内示例封顶但**显式写明"另有 N 条"**，绝不静默省略。
    lines.append("## 未闭合项")
    lines.append("")
    lines.append(
        "> 下表先按原因码、再按条款依据聚合。"
        "**逐条明细未省略**，完整清单见同目录 `closure_validation_result.json` 的 "
        "`machine_readable_report.open_items` / `blocked_items`。"
    )
    lines.append("")
    lines.extend(_render_unclosed_group_table(
        "open obligations（资料缺失，待补充）", open_items, "open_reason_code"))
    lines.extend(_render_unclosed_group_table(
        "blocked obligations（验证器无法处理，需人工介入）",
        blocked_items, "blocked_reason_code"))

    # unknown 归因（消费者验收标准落点；老产物的 None / 空映射显式降级）
    attribution_mapping = result.unknown_attribution_by_obligation_id
    if attribution_mapping:
        # skip_action_items=True：本函数已在文首渲染过行动项（消费者轴改造），
        # 不传这个参数会让整节出现两遍。另两个调用点（辅助审查报告 / v3-v4 组合报告）
        # 文首没有这一节，保持缺省 False。
        lines.extend(render_unknown_attribution_section(
            result, skip_action_items=True))
    else:
        lines.extend(_unknown_attribution_missing_lines())

    # 补充建议：有归因时只做交叉引用，不把文首行动项重复一遍。
    lines.append("## 建议补充 / 检查资料")
    lines.append("")
    if attribution_mapping:
        action_buckets = _collect_professional_action_buckets(
            attribution_mapping,
            obligation_index,
            building_id=str(_g(mr, "building_id") or ""),
        )
        professional_count = sum(
            bucket["obligation_count"] for bucket in action_buckets.values()
        )
        system_count = sum(
            1
            for attr in attribution_mapping.values()
            if _field(attr, "responsibility") != "professional_input_required"
        )
        lines.append(
            "需要你补充的资料已列在文首「需要你补充的资料」一节"
            f"（共 {len(action_buckets)} 项 / {professional_count} 条义务）。"
        )
        lines.append("")
        lines.append(
            f"其余 **{system_count}** 条未闭合项属**系统侧缺口**"
            "（规则卡未绑定核验通道、上游触发器未求值等），"
            "**不需要你补录资料**，已记录待维护方处理；"
            "分布见上节「unknown 归因」，逐条明细见 "
            "`closure_validation_result.json`。"
        )
    else:
        lines.append(
            "（本次结果未带归因映射，以下按未闭合项原样列出，"
            "其中部分可能属系统侧缺口。）"
        )
        lines.append("")
        suggestions = _collect_suggestions(open_items, blocked_items)
        if suggestions:
            for suggestion in suggestions:
                lines.append(f"- {suggestion}")
        else:
            lines.append("- 本次没有可列出的未闭合项。")
    lines.append("")
    # 文首注释承诺的「诊断信息」节——机器标识从文首挪到这里，不是删除。
    # run_id / stop_reason 是跨批对账键（审计与复现都靠它们定位产物），
    # 2026-08-04 提交前审核实测发现「行动项前置」改造时此节漏建、字段实际丢失，补回。
    lines.append("## 诊断信息（机器标识，供对账与复现）")
    lines.append("")
    lines.append(f"- run_id: {result.run_id}")
    lines.append(f"- world_id: {_g(mr, 'world_id')}")
    lines.append(f"- building_id: {_g(mr, 'building_id')}")
    lines.append(f"- allow_stop: {result.allow_stop}")
    lines.append(f"- stop_reason: {_g(mr, 'stop_reason', summary.stop_reason)}")
    lines.append(
        f"- open: {summary.open_count}　blocked: {summary.blocked_count}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "本说明为人工审查辅助材料，非最终裁决。闭包验证通过前不生成完整辅助审查报告。"
    )
    lines.append("")
    return "\n".join(lines)


_REFERENCES_PER_REASON = 10  # 每个原因码下列几个条款依据；超出时显式写明余量
_SUGGESTION_CAP = 40         # 老产物降级条目上限；超出**显式写明**，不静默截断


def _render_unclosed_group_table(
    title: str, items: List[Dict[str, Any]], reason_field: str,
) -> List[str]:
    """把未闭合义务聚合成两级：先原因码，再按条款依据合并。"""
    out: List[str] = ["", f"### {title}", ""]
    if not items:
        out += [f"（无 {title.split('（')[0].strip()}）", ""]
        return out

    by_reason: Dict[str, List[Dict[str, Any]]] = {}
    for obligation in items:
        by_reason.setdefault(
            _fmt_value(_g(obligation, reason_field)), []
        ).append(obligation)

    references = {
        _rule_reference(
            obligation,
            str(_g(obligation, "source_rule_card_id") or ""),
        )
        for obligation in items
    }
    out.append(
        f"共 **{len(items)}** 条，涉及 **{len(references)}** 个条款依据、"
        f"**{len(by_reason)}** 个原因码。"
    )
    out.append("")
    out.append("| 条数 | 原因码 | 涉及条款数 |")
    out.append("|---:|---|---:|")
    for reason, obligations in sorted(
        by_reason.items(), key=lambda item: -len(item[1])
    ):
        reason_references = {
            _rule_reference(
                obligation,
                str(_g(obligation, "source_rule_card_id") or ""),
            )
            for obligation in obligations
        }
        out.append(f"| {len(obligations)} | {reason} | {len(reason_references)} |")
    out.append("")

    for reason, obligations in sorted(
        by_reason.items(), key=lambda item: -len(item[1])
    ):
        per_reference: Dict[str, int] = {}
        first_id: Dict[str, str] = {}
        for obligation in obligations:
            reference = _rule_reference(
                obligation,
                str(_g(obligation, "source_rule_card_id") or ""),
            )
            per_reference[reference] = per_reference.get(reference, 0) + 1
            first_id.setdefault(
                reference, _fmt_value(_g(obligation, "obligation_id"))
            )
        ranked = sorted(
            per_reference.items(), key=lambda item: (-item[1], item[0])
        )
        out.append(
            f"<details><summary>{reason}（{len(obligations)} 条 / "
            f"{len(ranked)} 个条款依据）</summary>"
        )
        out.append("")
        # 本表在**折叠块内**（机器下钻面），保留 `示例 obligation_id` 是有意的：
        # 消费者验收 A 门只对**主视图**要求哈希数=0，折叠内不计；
        # 而 `test_incomplete_closure_notice_lists_open_and_blocked` 明确要求
        # 义务 id 出现在文档里——删它会伤可追溯性、换不来任何门禁收益。
        # （2026-07-31 曾误删一次：那 10 个主视图哈希其实来自「继承根聚合」表，
        #   不是本表；改前没定位就动手，数字纹丝不动还断了测试。）
        out.append("| 条数 | 法规依据 | 示例 obligation_id |")
        out.append("|---:|---|---|")
        for reference, count in ranked[:_REFERENCES_PER_REASON]:
            out.append(
                f"| {count} | {reference} | {first_id.get(reference, '')} |"
            )
        if len(ranked) > _REFERENCES_PER_REASON:
            rest = sum(count for _, count in ranked[_REFERENCES_PER_REASON:])
            out.append(
                f"| … | **另有 {len(ranked) - _REFERENCES_PER_REASON} 个条款依据"
                f"、合计 {rest} 条**（完整清单见结果 JSON） | — |"
            )
        out.append("")
        out.append("</details>")
        out.append("")
    return out


def _collect_suggestions(
    open_items: List[Dict[str, Any]],
    blocked_items: List[Dict[str, Any]],
) -> List[str]:
    """老产物缺归因映射时按「条款依据 × 原因码」聚合，绝不渲染 notes。"""
    counts: Dict[tuple, int] = {}
    for obligation in list(open_items) + list(blocked_items):
        reference = _rule_reference(
            obligation,
            str(_g(obligation, "source_rule_card_id") or ""),
        )
        reason = _fmt_value(
            _g(obligation, "open_reason_code")
            or _g(obligation, "blocked_reason_code")
        )
        key = (reference, reason)
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    out: List[str] = []
    for (reference, reason), count in ordered[:_SUGGESTION_CAP]:
        out.append(f"[{reference} / {reason}] 共 {count} 条待补充。")
    if len(ordered) > _SUGGESTION_CAP:
        rest = sum(count for _, count in ordered[_SUGGESTION_CAP:])
        out.append(
            f"…另有 **{len(ordered) - _SUGGESTION_CAP}** 组（合计 {rest} 条）未在此列出，"
            "完整清单见 `closure_validation_result.json`。"
        )
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
    # DEBT-083 丁护栏②：镜像一致性副本分账（无镜像时与旧格式逐字节同）。
    _m_sat, _m_vio = _mirror_verdict_counts(result)
    lines.append(_verdict_count_line("satisfied", summary.satisfied_count, _m_sat))
    lines.append(_verdict_count_line("violated", summary.violated_count, _m_vio))
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

    # --- 7.5 unknown 归因（与另一条报告入口共用同一渲染实现，杜绝两条路各说各话）---
    lines.extend(render_unknown_attribution_section(result))

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
# 三·五、unknown 归因渲染（消费者验收标准「有故 unknown 须说清为什么」的落点）
# ===========================================================================
#
# 用户拍板：「不是判定系统……**但是也不能无故 unknown，这是两码事**」。归因本身由
# 闭包验证器的旁路映射 `ClosureValidationResult.unknown_attribution_by_obligation_id`
# 产出，**本层只渲染、绝不自行计算**（自算必然与权威映射分叉——本文件有两条报告
# 入口 + 一处证据包截断，任何一处自算都会各说各话）。
#
# 🔴 三条硬约束：
# 1. **只读映射**：本节全部文字来自映射里的 `explanation` / `cause_code` /
#    `responsibility`，本层不做任何归因判断。
# 2. **模型零参与**：本节属程序确定性骨架，模型可以在分析节复述，但权威文本在这里。
# 3. **缺映射或映射不全 → 显式失败/显式告知，绝不静默降级**成旧的不分家 unknown。


class UnknownAttributionRenderError(RuntimeError):
    """归因映射与义务集不一致时抛出（fail-closed，绝不静默按旧格式渲染）。"""


# 主视图聚合封顶（与下方 v4 聚合表同口径；此处先定义供本节默认参数用）。
_AGG_TOP_N = 10


# 责任 → (给专业人员看的名字, 这意味着他要做什么)
_UNKNOWN_RESPONSIBILITY_LABELS: Dict[str, tuple] = {
    "professional_input_required": (
        "需要专业人员提供",
        "系统已定位到具体缺口，请补录对应资料后重跑",
    ),
    "system_unresolved": (
        "系统未能确定",
        "系统自身的缺口，不需要你补录资料，已记录待维护方处理",
    ),
}

# cause_code → 一句话说明（表头用；逐项细节仍用映射里的 explanation 原文）
# 🔴 每条文案声称的事实必须对该码 100% 义务为真（见
# `test_cause_label_structural_truth_on_batch`）。
_UNKNOWN_CAUSE_LABELS: Dict[str, str] = {
    "inherited_from_root": "上游义务未闭合，本条在等根因",
    "upstream_trigger_blocked": "卡级触发器堵死，本条从未进入求值",
    "no_slot_declared": "义务图节点未绑定事实槽，且无更具体的验证器原因码",
    "non_slot_handle": "句柄不是事实槽（不是漏查，这类义务不走事实槽轴）",
    "qualifier_mismatch": "世界侧有数据，但规则卡按现有条件取不到",
    "slot_not_supplied": "世界侧未供给该项数据",
    "diagnostic_binding_not_valid_evidence": "读数已取得，但这类读数经裁定不能证明本义务已履行（有意的保守设计）",
    "artifact_state_not_valid_evidence": "查到了文件，但「文件在」不足以证明义务已履行（有意的保守设计）",
    "missing_artifact_evidence": "事实包中没有义务要求的证据文件记录",
    "missing_time_anchor": "缺期限锚点，系统无法核验期限",
    "ambiguous_fact_binding": "候选事实不唯一，系统拒绝任取其一下结论",
    "observed_false_without_violation_basis": (
        "已取得完整聚合读数，正向条件尚未成立；无期限或终局违约依据，"
        "程序不判违反，交由专业人员复核"),
    "binding_requires_adjudication_authorization": (
        "读数在，但该义务绑定未获消费此类读数下判定的裁定授权，"
        "程序不给结论（待维护方逐绑定裁定）"),
    # #33 保护闸（2026-08-05）。⚠️ 本码覆盖真假两侧，故文案不许提「文件不存在」，
    # 也不许提「查到了文件」——那只对真值侧成立，会违反「文案声称的事实须对该码
    # 全部义务为真」这条不变量（`test_cause_label_structural_truth_on_batch`）。
    "evidence_event_coupling_unproven": (
        "判定依据是「已呈交／送达／签署」状态读数，但系统尚未确立"
        "「记录到该状态即代表事件确已发生」，故不据其判满足；须专业人员核实事件是否发生"),
    "missing_rule_edge": "规则边或引用缺失（非卡级触发器堵死）",
    "missing_satisfaction_binding": "缺满足通道绑定，无法沿事实槽核验",
    "artifact_not_modeled_upstream": "产物键未在上游世界模型建模",
    "missing_measurement": "缺量测值，无法核验阈值或比较",
    "missing_fact": "事实包中查不到本条所需事实",
    "missing_required_field_group": "缺必填字段组",
    "unit_mismatch": "单位不一致，系统拒绝比较",
    "attribution_input_missing": "归因层未能判别原因，待维护方跟进",
}

# 渲染顺序：先给"要你做的"，再给"不要你做的"；同组内按可操作性排。
_UNKNOWN_CAUSE_ORDER = (
    "slot_not_supplied",
    "inherited_from_root",
    "upstream_trigger_blocked",
    "qualifier_mismatch",
    "missing_satisfaction_binding",
    "observed_false_without_violation_basis",
    "binding_requires_adjudication_authorization",
    # #33 保护闸：排在两个「永久不能确立」码**之前**——它是可解封的，
    # 对专业人员的行动含义更强（核实事件是否发生 ⇒ 能推动解封）。
    "evidence_event_coupling_unproven",
    "no_slot_declared",
    "non_slot_handle",
    "artifact_state_not_valid_evidence",
    "diagnostic_binding_not_valid_evidence",
    "missing_artifact_evidence",
    "artifact_not_modeled_upstream",
    "missing_time_anchor",
    "missing_measurement",
    "missing_fact",
    "missing_required_field_group",
    "unit_mismatch",
    "ambiguous_fact_binding",
    "missing_rule_edge",
    "attribution_input_missing",
)

_UNKNOWN_SECTION_TITLE = "## unknown 归因（这些项为什么还没有结论）"


# ===================================================================== #
# 乙11：共享读数的**分辨率限制披露**（2026-08-05，决议_33处置_20260805.md §一.2）
# ===================================================================== #
# 病与 #33 **不同**：#33 是「证据力为零的事实在解除义务」⇒ 判定无依据 ⇒ 必须闸掉；
# 乙11 是「证据力成立但**分辨率不足**」⇒ 判定有依据 ⇒ 闸掉就是丢掉有依据的判定。
# ⇒ 处置＝**保留判定 ＋ 结果层披露**，不是撤销判定。
#
# 🔴 为什么披露必须落在**这份文件**里：上游 `worldgen/registry.py` 的
# `semantic_note` 已经把这条简化记了账，但那是世界侧台账——**消费者看不到**。
# pro 审的质疑原话是「台账注记不能代替结果层保护」，正确的补法是披露，
# 不是撤销判定。
#
# ⚠️ 层界说明（分层单向红线）：`workflow_engine` 与 `evo_agent_baseline` 互不 import，
# 故上游 `semantic_note` 无法在此直接引用，本表是**受控重述**。
# 两处必须同批改；同源性另有机器面守卫（两义务 `evidence_fact_ids` 必须相等的
# 契约测试，见 `closure/tests/test_yi11_shared_reading_disclosure.py`）——
# 那条守卫比文字更硬：它防的是将来有人把一条读数「修」成两条不同 fact，
# 让同源性从机器可查变成不可查。
_SHARED_READING_DISCLOSURES: Dict[str, Dict[str, str]] = {
    # §2.1.3(p)：修葺建議修訂须于向建築事務監督呈交同日送交「該名由他人代為進行
    # 訂明修葺的人」；§2.1.3(q)：同日送交註冊承建商。
    # 两条的**起算事件是同一个**（向監督呈交之日），天数也相同（同日＝0 日），
    # 世界侧由**一条量** `duration.delivery.repair_revision_proposal` 承载。
    "rc.mbis.reporting.ri_procedural_notifications.ri.submit."
    "s2_1_3_p_revised_proposal_to_person_same_day.c01": {
        "group": "yi11_repair_revision_same_day",
        "peer": "§2.1.3(q)（送交註冊承建商）",
    },
    "rc.mbis.repair.prescribed_repair_inputs.ri.deliver."
    "s2_1_3_q_revised_proposal_to_rc_same_day.c01": {
        "group": "yi11_repair_revision_same_day",
        "peer": "§2.1.3(p)（送交該名由他人代為進行訂明修葺的人）",
    },
}

_SHARED_READING_GROUP_TEXT: Dict[str, str] = {
    "yi11_repair_revision_same_day": (
        "本判定依据的是**同一条送交时长读数**，它同时覆盖 §2.1.3(p) 与 §2.1.3(q) "
        "两个收件人。系统**无法区分**是否只送交了其中一方——"
        "「交了承建商没交业主」这种情形当前建模不出来，两支必然同判。"
        "⇒ 请**分别**核实两个收件人是否都已收到。"
    ),
}

_SHARED_READING_SECTION_TITLE = "## 分辨率限制披露（两条义务由同一条读数支撑）"


def shared_reading_disclosure_for(rule_card_id: str) -> Optional[Dict[str, str]]:
    """该规则卡是否属于「共享读数、分辨率受限」披露面。返回登记项或 None。"""
    return _SHARED_READING_DISCLOSURES.get(str(rule_card_id or ""))


def render_shared_reading_disclosure_section(
    obligations: Sequence[Any],
    display_ref_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """渲染乙11 披露专节；本次运行没有命中的卡时返回空清单（不占版面）。

    🔴 **不得**渲染成「该判定不可信」或「系统未能判定」——判定是有依据的，
    受限的只是分辨率。措辞边界与 #33 的闸码文案是**两回事**，别互相抄。
    """
    hits: Dict[str, List[Any]] = {}
    for ob in obligations or ():
        reg = shared_reading_disclosure_for(getattr(ob, "source_rule_card_id", ""))
        if reg is not None:
            hits.setdefault(reg["group"], []).append(ob)
    if not hits:
        return []
    refs = display_ref_map or {}
    lines: List[str] = [_SHARED_READING_SECTION_TITLE, ""]
    lines.append(
        "> 下列义务的判定**有依据**（读数真实存在、程序据其判定），"
        "但一条读数同时承载了两条义务，**分辨率不足以区分两者**。"
        "这不是「系统没判」，而是「系统判了，但分不开」。"
    )
    lines.append("")
    for group, obs in sorted(hits.items()):
        lines.append(_SHARED_READING_GROUP_TEXT.get(group, ""))
        lines.append("")
        for ob in sorted(obs, key=lambda o: str(getattr(o, "obligation_id", ""))):
            oid = str(getattr(ob, "obligation_id", ""))
            reg = _SHARED_READING_DISCLOSURES[str(ob.source_rule_card_id)]
            lines.append(
                f"- [{refs.get(oid, '—')}] rule_card "
                f"{_fmt_value(ob.source_rule_card_id)}"
                f"（当前判定：{_fmt_value(getattr(ob, 'satisfaction_status', None))}）"
                f"——与 {reg['peer']} 共用同一条读数，必然同判。"
            )
        lines.append("")
    return lines


def _unknown_attribution_missing_lines() -> List[str]:
    """映射为 None（旧产物 / 本次未计算）时的**显式告知**。

    刻意**不**回退成旧的不分家 unknown：静默回退会让读者以为"系统说不清"，
    而真相是"这一版根本没算"。两者对使用者的含义完全不同。
    """
    return [
        _UNKNOWN_SECTION_TITLE,
        "",
        "> 本次运行**未计算** unknown 归因（产物早于归因功能，或本次未启用）。",
        "> 因此下方 unknown 项**未作分类**，无法区分「需要你补录资料」与"
        "「系统自身未能确定」。如需分类，请用当前版本重跑。",
        "",
    ]


_SCOPE_RELATION_LABELS: Dict[str, str] = {
    "same": "类型相同",
    "category_compatible": "类目相容",
    "authorized_disjoint": "经授权且显式互斥",
    "different_unresolved": "关系尚未证成",
    "card_unconstrained": "卡侧未限定构件类型",
    "identity_unavailable": "片段权威身份不可用",
}

_SCOPE_RELATION_ORDER = (
    "same",
    "category_compatible",
    "authorized_disjoint",
    "different_unresolved",
    "card_unconstrained",
    "identity_unavailable",
)


def _scope_values(values: List[str], *, empty_label: str) -> str:
    cleaned = sorted({str(value) for value in values if str(value)})
    if not cleaned:
        return empty_label
    return "、".join(f"`{value}`" for value in cleaned)


def render_scope_relation_diagnostic_section(
    result: ClosureValidationResult,
) -> List[str]:
    """Render the orthogonal scope relation axis without recomputing it."""
    title = "## 作用域关系诊断"
    mapping = result.unknown_attribution_by_obligation_id
    if mapping is None:
        return [title, "", "> 本次运行未计算作用域关系诊断。", ""]
    if not mapping:
        return [title, "", "> 本次没有 unknown 项。", ""]
    if any(_field(attr, "scope_relation", None) is None for attr in mapping.values()):
        return [
            title,
            "",
            "> 本次归因载荷不含完整的结构化作用域关系；本节不作推测。",
            "",
        ]

    buckets: Dict[str, Dict[str, Any]] = {}
    for attr in mapping.values():
        scope = _field(attr, "scope_relation", None)
        if scope is None:
            continue
        bucket = buckets.setdefault(
            scope.relation,
            {
                "count": 0,
                "card_types": [],
                "fragment_types": [],
                "causes": [],
                "authorization_statuses": [],
                "policy_versions": [],
            },
        )
        bucket["count"] += 1
        bucket["card_types"].extend(scope.card_component_type_keys)
        if scope.fragment_component_type:
            bucket["fragment_types"].append(scope.fragment_component_type)
        bucket["causes"].append(attr.cause_code)
        bucket["authorization_statuses"].append(
            scope.target_authorization_status
        )
        bucket["policy_versions"].append(scope.relation_policy_version)

    lines = [
        title,
        "",
        "> 本表是 unknown 归因的正交诊断轴；现有原因表继续完整保留。",
        "",
        "| 条数 | 作用域观察 | 精确目标授权状态 | 关系策略版本锚 |",
        "|---:|---|---|---|",
    ]
    for relation in _SCOPE_RELATION_ORDER:
        bucket = buckets.get(relation)
        if not bucket:
            continue
        card_types = _scope_values(
            bucket["card_types"], empty_label="（未限定）"
        )
        fragment_types = _scope_values(
            bucket["fragment_types"], empty_label="（不可用）"
        )
        causes = "、".join(sorted({
            _UNKNOWN_CAUSE_LABELS.get(code, code)
            for code in bucket["causes"]
        }))
        observation = (
            "**状态仍为未知，判定未改变。** 作用域观察：本卡引用的事实限定含 "
            f"{card_types}，本片段的权威构件身份为 {fragment_types}；"
            f"两者关系为【{_SCOPE_RELATION_LABELS[relation]}】。"
            "**本记录不等于 `not_applicable`，也不能据此免除该条款评估。** "
            f"当前直接阻塞机制仍为【{causes}】。"
        )
        if relation == "authorized_disjoint":
            observation += (
                " 若要据此改判不适用，仍须另行通过规格、召回及漏项审查；"
                "本次只记录诊断证据。"
            )
        authorization_statuses = "、".join(sorted(set(
            bucket["authorization_statuses"]
        )))
        policy_versions = "、".join(sorted(set(bucket["policy_versions"])))
        lines.append(
            f"| {bucket['count']} | {_escape_markdown_cell(observation)} | "
            f"{_escape_markdown_cell(authorization_statuses)} | "
            f"{_escape_markdown_cell(policy_versions)} |"
        )
    lines.append("")
    return lines


def render_unknown_attribution_section(
    result: ClosureValidationResult,
    *,
    max_rows: int = _AGG_TOP_N,
    collapsible: bool = False,
    display_ref_map: Optional[Dict[str, str]] = None,
    skip_action_items: bool = False,
    action_items_relocated: bool = False,
) -> List[str]:
    """渲染 unknown 归因节（程序确定性；两条报告入口共用同一实现）。

    入参 `result` 的归因映射：
    - `None`            → 显式告知"本次未计算归因"（不静默按旧格式渲染）；
    - 键集与 unknown 义务集不一致 → 抛 `UnknownAttributionRenderError`（fail-closed）；
    - 一致             → 渲染责任计数 + cause_code 分项计数 + 逐项解释 + 行动指引。

    `inherited_from_root` **按根聚合**：不逐条列继承项，只把**根义务**列为行动项，
    附"受影响义务 N 条"——继承项自身无病，逐条列只会把行动清单淹掉。
    """
    obligations = result.obligation_set.obligations
    unknown_ids = {
        o.obligation_id for o in obligations if o.satisfaction_status == "unknown"
    }
    mapping = result.unknown_attribution_by_obligation_id

    if mapping is None:
        return _unknown_attribution_missing_lines()

    actual = set(mapping)
    if actual != unknown_ids:
        raise UnknownAttributionRenderError(
            "unknown 归因映射与义务集不一致，拒绝渲染（缺 "
            f"{len(unknown_ids - actual)} 条 / 多 {len(actual - unknown_ids)} 条）；"
            "报告层不得自行归因、也不得静默降级成未分类 unknown。"
        )

    lines: List[str] = [_UNKNOWN_SECTION_TITLE, ""]
    if not mapping:
        lines.append("> 本次没有 unknown 项——全部义务都已得出闭包结论。")
        lines.append("")
        lines.extend(render_scope_relation_diagnostic_section(result))
        return lines

    lines.append(
        "> 本节由系统确定性渲染，逐条归因取自闭包验证器的归因映射；模型不参与。"
        "归因解释**为什么**还没有结论，本身不是合规结论。"
    )
    lines.append("")

    by_id = {o.obligation_id: o for o in obligations}
    resp_counts: Dict[str, int] = {}
    cause_counts: Dict[str, int] = {}
    for attr in mapping.values():
        resp_counts[attr.responsibility] = resp_counts.get(attr.responsibility, 0) + 1
        cause_counts[attr.cause_code] = cause_counts.get(attr.cause_code, 0) + 1

    # --- 责任划分（消费者最先要看的一格）---
    lines.append(f"unknown 共 {len(mapping)} 条，按责任划分：")
    lines.append("")
    lines.append("| 责任 | 条数 | 这对你意味着什么 |")
    lines.append("|---|---:|---|")
    for key in ("professional_input_required", "system_unresolved"):
        label, meaning = _UNKNOWN_RESPONSIBILITY_LABELS[key]
        lines.append(f"| {label} | {resp_counts.get(key, 0)} | {meaning} |")
    lines.append("")

    # --- 专业人员行动项（按「条款 × 行动说明」聚合；不逐义务列）---
    #
    # 🔴 `skip_action_items`：调用方**已在文首渲染过**这一节时传 True，否则整节会出现两遍。
    # 缺省 False ⇒ 对不传参的调用方（v3 组合报告 / 辅助审查报告）行为逐字节不变。
    # `action_items_relocated`：仅在 skip_action_items=True 时生效——v4 文首已渲染，
    # 原位置留一行指回，不让读者以为这节丢了（v1 告知书有自己的交叉引用节，不传此参）。
    #
    # 这个洞是 2026-07-31 实测撞出来的：把行动项提到文首（消费者轴改造）时，
    # 只看了「它现在在第 7 行了」，没查「原来那份还在不在」——结果同一份文档里
    # 两份完全相同的行动项表，把 A 门重复行率从 4.6% 顶到 7.8%（判据 ≤5%），
    # 一个本来通过的子判据被改成了不通过。单测全绿，因为**没有一条断言「只出现一次」**。
    mr = result.machine_readable_report or {}
    obligation_index = _index_unclosed_obligations(
        mr.get("open_items", []) or [],
        mr.get("blocked_items", []) or [],
    )
    if not skip_action_items:
        lines.extend(
            _render_professional_action_items(
                mapping,
                obligation_index=obligation_index,
                building_id=str(_g(mr, "building_id") or ""),
                max_rows=max_rows,
            )
        )
    elif action_items_relocated:
        lines.append("> 需要你补充的资料已提前列于文首。")
        lines.append("")

    # --- cause_code 分项计数：消费者说明在前，机器对账键降到末列 ---
    lines.append("| 说明 | 条数 | 原因码 |")
    lines.append("|---|---:|---|")
    for code in _UNKNOWN_CAUSE_ORDER:
        if code not in cause_counts:
            continue
        lines.append(
            f"| {_UNKNOWN_CAUSE_LABELS.get(code, '—')} | {cause_counts[code]} "
            f"| <small><code>{code}</code></small> |"
        )
    for code in sorted(set(cause_counts) - set(_UNKNOWN_CAUSE_ORDER)):
        lines.append(
            f"| 其他未分类原因 | {cause_counts[code]} "
            f"| <small><code>{code}</code></small> |"
        )
    lines.append("")

    detail_lines: List[str] = []

    # --- 逐项解释：先"要你做的"，再"不要你做的" ---
    for code in _UNKNOWN_CAUSE_ORDER + tuple(
        sorted(set(cause_counts) - set(_UNKNOWN_CAUSE_ORDER))
    ):
        items = [(oid, a) for oid, a in mapping.items() if a.cause_code == code]
        if not items:
            continue
        detail_lines.append(
            f"### {_UNKNOWN_CAUSE_LABELS.get(code, code)}（{len(items)} 条）"
        )
        detail_lines.append("")
        if code == "inherited_from_root":
            detail_lines.extend(
                _render_inherited_by_root(items, mapping, by_id, max_rows, display_ref_map)
            )
        else:
            detail_lines.extend(_render_cause_group(items, by_id, max_rows))
        detail_lines.append("")

    if collapsible and detail_lines:
        lines.append("<details>")
        lines.append("<summary>unknown 归因逐项说明（程序渲染，点击展开）</summary>")
        lines.append("")
        lines.extend(detail_lines)
        lines.append("</details>")
        lines.append("")
    else:
        lines.extend(detail_lines)
    lines.extend(render_scope_relation_diagnostic_section(result))
    return lines


def _index_unclosed_obligations(
    open_items: List[Dict[str, Any]],
    blocked_items: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """按义务编号索引机器报告中的 open / blocked 项。"""
    indexed: Dict[str, Dict[str, Any]] = {}
    for obligation in list(open_items) + list(blocked_items):
        obligation_id = str(_g(obligation, "obligation_id") or "").strip()
        if obligation_id:
            indexed[obligation_id] = obligation
    return indexed



def _short_fragment_id(fragment_id: str, building_id: str) -> str:
    """剥掉同栋恒定的 `FRG-<building_id>-` 前缀，只保留部位尾段。"""
    fragment_id = str(fragment_id or "").strip()
    building_id = str(building_id or "").strip()
    if not fragment_id or not building_id:
        return fragment_id

    building_candidates = [building_id]
    if building_id.startswith("BLD-"):
        building_candidates.append(building_id[len("BLD-"):])
    for candidate in building_candidates:
        prefix = f"FRG-{candidate}-"
        if fragment_id.startswith(prefix):
            return fragment_id[len(prefix):]
    return fragment_id


def _type_incompatible_obligation_ids(
    result: ClosureValidationResult,
) -> FrozenSet[str]:
    """行动项部位过滤集（纯呈现，不碰判定）：只收「显式互斥」的义务。

    判据直接读闭包验证器挂上的结构化作用域关系旁路（`scope_relation`），
    报告层不重算：只有 `authorized_disjoint`（卡侧唯一授权目标叶型与片段叶型
    落在类型关系表的 disjoint 对里）才剔；`same` / `category_compatible`
    （子型相容，如片段 external_wall 属于卡侧 external_component）以及
    判不出关系的（未登记 / 非叶型 / 身份缺失 / 旁路缺席）一律保留——
    缺省保守，绝不按「字符串不等」剔。本函数不改任何义务状态与计数，
    只决定行动项「涉及 N 处」列表里哪些部位不列出。
    """
    mapping = result.unknown_attribution_by_obligation_id or {}
    incompatible: set = set()
    for obligation_id, attr in mapping.items():
        scope = _field(attr, "scope_relation", None)
        if scope is None:
            continue
        if _field(scope, "relation", "") == "authorized_disjoint":
            incompatible.add(str(obligation_id))
    return frozenset(incompatible)


def _render_professional_action_items(
    mapping: Dict[str, Any],
    obligation_index: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    building_id: str = "",
    max_rows: int = _AGG_TOP_N,
    type_incompatible_obligation_ids: Optional[FrozenSet[str]] = None,
) -> List[str]:
    """把需专业人员补录的义务按「条款元组 × 行动说明」聚合。

    义务索引是可选增强项：缺省时仍稳定渲染，但明确写出条款和部位未标注。
    超出 `max_rows` 时显式写「另有 M 项、合计 N 条」，绝不静默截断。

    `type_incompatible_obligation_ids`：与卡侧要求类型**显式互斥**的义务集合
    （由 `_type_incompatible_obligation_ids` 从验证器作用域关系旁路读出）。
    这些义务的部位不进「涉及 N 处」列表，但**不静默消失**——每项下显式写
    「另有 N 处因构件类型与本条款不相容未列出」。缺省 None = 不过滤（v1 / v3
    调用面行为逐字节不变）。
    """
    obligation_index = obligation_index or {}
    incompatible_ids = frozenset(type_incompatible_obligation_ids or ())

    # 「提供了会怎样」——可行动四要素的第四个（2026-08-03 补）。
    # 前三个（哪栋楼哪个部位 / 哪条守则 / 要提供什么）此前已有，第四个**全批零条**：
    # 审查员看完不知道补了这一项能换来什么，于是这份报告对他不产生优先级。
    #
    # 唯一诚实且可算的答案是「连带解开多少条正在等它的义务」：
    # 反向索引 `root_dependency_ids`（谁把这条列为根依赖）。
    # 批 I 实测 488 条待补项里 **229 条（47%）**有下游在等，最多一条带 7 个。
    #
    # 🔴 措辞红线：只写「解除阻塞并重新求值」，**绝不写「补了就会判合规」**——
    # 解除本项阻塞不蕴含该义务随后能得出确定判定（可能还有别的缺口）。
    # 对审查员承诺一个我们保证不了的结果，与本轮要修的「假合格」是同一种不诚实。
    downstream_by_root: Dict[str, int] = {}
    for attr in mapping.values():
        for root in (getattr(attr, "root_dependency_ids", None) or []):
            downstream_by_root[str(root)] = downstream_by_root.get(str(root), 0) + 1

    buckets: Dict[Tuple[Tuple[str, ...], str], Dict[str, Any]] = {}
    for obligation_id, attr in mapping.items():
        if attr.responsibility != "professional_input_required":
            continue
        action = (
            (attr.professional_action or "").strip()
            or "（登记表未给出具体交件说明）"
        )
        obligation = obligation_index.get(str(obligation_id), {})
        clause_ids = _source_clause_tuple(obligation)
        key = (clause_ids, action)
        bucket = buckets.setdefault(
            key,
            {
                "obligation_count": 0,
                "fragment_ids": set(),
                "unlocated_count": 0,
                "incompatible_fragment_ids": set(),
                "downstream_count": 0,
            },
        )
        bucket["obligation_count"] += 1
        bucket["downstream_count"] += downstream_by_root.get(str(obligation_id), 0)
        fragment_id = str(_g(obligation, "fragment_id") or "").strip()
        if fragment_id:
            short_fragment_id = _short_fragment_id(fragment_id, building_id)
            if str(obligation_id) in incompatible_ids:
                bucket["incompatible_fragment_ids"].add(short_fragment_id)
            else:
                bucket["fragment_ids"].add(short_fragment_id)
        else:
            bucket["unlocated_count"] += 1

    lines: List[str] = [
        "### 需要你补充的资料",
        "",
    ]
    if not buckets:
        lines.append("> 本次没有需要你补充的资料（责任二分「需要专业人员提供」为 0）。")
        lines.append("")
        return lines

    def _scope_count(bucket: Dict[str, Any]) -> int:
        fragment_count = len(bucket["fragment_ids"])
        if fragment_count:
            return fragment_count + bucket["unlocated_count"]
        return bucket["obligation_count"]

    ranked = sorted(
        buckets.items(),
        key=lambda item: (
            -_scope_count(item[1]),
            item[0][0],
            item[0][1],
        ),
    )
    total_obligations = sum(
        bucket["obligation_count"] for _, bucket in ranked
    )
    lines.append(
        f"共 **{len(ranked)} 项**，涉及 **{total_obligations} 条义务**。"
        "以下每项都注明了法规依据，可据此判断是否适用。"
    )
    lines.append("")

    shown = ranked[:max_rows]
    for item_number, ((clause_ids, action), bucket) in enumerate(shown, start=1):
        lines.append(f"**{item_number}. {action}**")
        lines.append("")
        if clause_ids:
            rendered_clauses = "、".join(f"§{clause_id}" for clause_id in clause_ids)
            lines.append(f"- 依据：守则 {rendered_clauses}")
        else:
            lines.append("- 依据：（本项未标注条款，见结果 JSON）")

        fragment_ids = sorted(bucket["fragment_ids"])
        # 显式互斥被剔的部位不静默消失：同一片段若另有相容义务仍列出，
        # 则不算「未列出」，只在真正从列表里消失时计数（B3）。
        hidden_fragment_ids = sorted(
            bucket["incompatible_fragment_ids"] - set(fragment_ids)
        )
        if fragment_ids:
            shown_fragments = fragment_ids[:8]
            rendered_fragments = "、".join(
                f"`{fragment_id}`" for fragment_id in shown_fragments
            )
            if len(fragment_ids) > 8:
                rendered_fragments += (
                    f"、…（共 {len(fragment_ids)} 处，完整清单见结果 JSON）"
                )
            lines.append(
                f"- 涉及 **{len(fragment_ids)} 处**：{rendered_fragments}"
            )
            if bucket["unlocated_count"]:
                lines.append(
                    f"- 另有 **{bucket['unlocated_count']} 条义务**"
                    "未定位到具体部位"
                )
        elif not hidden_fragment_ids:
            lines.append(
                f"- 涉及 **{bucket['obligation_count']} 条义务**"
                "（未定位到具体部位）"
            )
        if hidden_fragment_ids:
            lines.append(
                f"<sub>另有 {len(hidden_fragment_ids)} 处因构件类型与本条款"
                "不相容未列出（诊断见结果 JSON）</sub>"
            )
        # 第四要素「提供了会怎样」。措辞红线见函数开头：只说解除阻塞与重新求值。
        downstream = int(bucket.get("downstream_count") or 0)
        if downstream:
            lines.append(
                f"- 补录后：解除本项 **{bucket['obligation_count']} 条**义务的阻塞，"
                f"并连带解开 **{downstream} 条**正在等它的义务，随后重新求值"
            )
        else:
            lines.append(
                f"- 补录后：本项 **{bucket['obligation_count']} 条**义务解除阻塞、"
                "重新求值"
            )
        lines.append("")

    if len(ranked) > max_rows:
        rest = ranked[max_rows:]
        rest_obligations = sum(
            bucket["obligation_count"] for _, bucket in rest
        )
        lines.append(
            f"**另有 {len(rest)} 项、合计 {rest_obligations} 条义务未在此展开；"
            "完整清单见结果 JSON。**"
        )
        lines.append("")
    return lines


def _collect_professional_action_buckets(
    mapping: Dict[str, Any],
    obligation_index: Dict[str, Dict[str, Any]],
    *,
    building_id: str = "",
) -> Dict[Tuple[Tuple[str, ...], str], Dict[str, Any]]:
    """复用行动项的分组口径，供文首清单与尾部交叉引用精确对账。"""
    buckets: Dict[Tuple[Tuple[str, ...], str], Dict[str, Any]] = {}
    for obligation_id, attr in mapping.items():
        if _field(attr, "responsibility") != "professional_input_required":
            continue
        action = (
            str(_field(attr, "professional_action") or "").strip()
            or "（登记表未给出具体交件说明）"
        )
        obligation = obligation_index.get(str(obligation_id), {})
        clause_ids = _source_clause_tuple(obligation)
        key = (clause_ids, action)
        bucket = buckets.setdefault(
            key,
            {"obligation_count": 0, "fragment_ids": set(), "unlocated_count": 0},
        )
        bucket["obligation_count"] += 1
        fragment_id = str(_field(obligation, "fragment_id") or "").strip()
        if fragment_id:
            bucket["fragment_ids"].add(
                _short_fragment_id(fragment_id, building_id)
            )
        else:
            bucket["unlocated_count"] += 1
    return buckets


def _render_inherited_by_root(
    items: List[tuple],
    mapping: Dict[str, Any],
    by_id: Dict[str, Any],
    max_rows: int,
    display_ref_map: Optional[Dict[str, str]],
) -> List[str]:
    """继承型**按根聚合**：只列根义务作为行动项，附受影响条数。

    继承项自身无病（上游 trigger 卡住传下来），逐条列会把真正的行动项淹掉；
    解决一个根义务即连带解开它下面全部受影响义务。
    """
    root_hits: Dict[str, int] = {}
    for _oid, attr in items:
        for root in attr.root_dependency_ids or []:
            root_hits[root] = root_hits.get(root, 0) + 1
    if not root_hits:
        return ["（归因未给出根义务编号）", ""]

    lines = [
        f"这些义务自身无缺陷，是上游未闭合传下来的；共涉及 **{len(root_hits)} 个根义务**，"
        "解决根义务即连带解开下面全部受影响义务。",
        "",
        # 🔴 不列根义务的运行期 id：24 位裸哈希对审查员零价值，
        # 而消费者验收 A 门要求主视图哈希数 = 0（`check_report_usability.py`）。
        # 实测这一列是主视图里**唯一**的哈希来源（单栋 10 个）。
        # 审查员要的是「哪条条款、连带几条、根因是什么」；逐条 id 在结果 JSON 里下钻。
        "| 受影响义务 | 根义务法规依据 | 根义务自身的原因 |",
        "|---:|---|---|",
    ]
    ordered = sorted(root_hits.items(), key=lambda kv: (-kv[1], kv[0]))
    for root, count in ordered[:max_rows]:
        ref = (display_ref_map or {}).get(root) or root
        root_obl = by_id.get(root)
        card_id = (
            str(_field(root_obl, "source_rule_card_id") or "")
            if root_obl is not None
            else ""
        )
        reference = _rule_reference(root_obl, card_id)
        root_attr = mapping.get(root)
        root_cause = (
            _UNKNOWN_CAUSE_LABELS.get(root_attr.cause_code, root_attr.cause_code)
            if root_attr is not None
            else "根义务已闭合或不在本次义务集内"
        )
        lines.append(f"| {count} | {reference} | {root_cause} |")
    rest = ordered[max_rows:]
    if rest:
        lines.append(
            f"| {sum(n for _, n in rest)} | （其余 {len(rest)} 个根义务） | — |"
        )
    return lines


def _render_cause_group(
    items: List[tuple], by_id: Dict[str, Any], max_rows: int
) -> List[str]:
    """非继承型：按**解释原文**分组计数，主视图列前 N 组，其余折成一行。

    解释文本直接来自归因映射（人话已在归因层写好），本层不改写、不生成。
    """
    groups: Dict[str, List[str]] = {}
    for oid, attr in items:
        groups.setdefault(attr.explanation, []).append(oid)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    # 同一原因码下各组解释**只差开头那段**（形如「这条义务（kind / action）」），
    # 其余是逐字相同的样板。整段重复打进每一行会让单节膨胀到十几 KB
    # （实测 `ambiguous_fact_binding` 58 条占了 12.3 KB / 全文 21%）。
    # ⇒ 抽出公共后缀，在表上方**说一次**；行里只留真正变化的部分。
    # 🔴 这是去重不是截断——一个字都没丢。
    # ⚠️ 只在**实际会渲染出来的**那些组上算公共后缀。
    # 第一版在全部 `ordered` 上算，结果任何一个没被渲染的离群组都会把公共后缀
    # 打没——实测只省下 0.2 KB，等于白改。
    shown_groups = ordered[:max_rows]
    shared = _longest_common_suffix([e for e, _ in shown_groups])
    lines: List[str] = []
    if len(shared) >= _SHARED_SUFFIX_MIN:
        lines += [f"> {_escape_markdown_cell(shared.strip())}", ""]

    lines += ["| 条数 | 法规依据 | 说明（系统原文，公共部分见上） |", "|---:|---|---|"]
    for explanation, oids in ordered[:max_rows]:
        references = sorted(
            {
                _rule_reference(
                    by_id[obligation_id],
                    str(_field(by_id[obligation_id], "source_rule_card_id") or ""),
                )
                for obligation_id in oids
                if obligation_id in by_id
            }
        )
        reference_text = "、".join(references) or "—"
        shown = explanation
        if len(shared) >= _SHARED_SUFFIX_MIN and explanation.endswith(shared):
            shown = explanation[: -len(shared)].rstrip() or "（同上）"
        lines.append(
            f"| {len(oids)} | {reference_text} | {_escape_markdown_cell(shown)} |"
        )
    rest = ordered[max_rows:]
    if rest:
        lines.append(
            f"| {sum(len(v) for _, v in rest)} | — | （其余 {len(rest)} 组同类说明） |"
        )
    return lines


# 公共后缀短于这个长度就不值得抽（抽了反而多两行）。
_SHARED_SUFFIX_MIN = 40


def _longest_common_suffix(texts: List[str]) -> str:
    """一组解释文本的最长公共后缀；少于 2 条或无公共部分时返回空串。"""
    if len(texts) < 2:
        return ""
    ref = texts[0]
    n = len(ref)
    for t in texts[1:]:
        m = 0
        # 🔴 索引 ref 必须始终从 len(ref) 末尾数——第一版写成 ref[n-1-m]，
        # 而 n 每轮都在缩，第二轮起就从错误位置比，公共后缀恒被算成 0（实测省 0 KB）。
        while m < n and m < len(t) and ref[len(ref) - 1 - m] == t[len(t) - 1 - m]:
            m += 1
        n = m
        if n == 0:
            return ""
    return ref[len(ref) - n:]


def _escape_markdown_cell(text: str) -> str:
    """表格单元格转义：竖线与换行会撑破表格。"""
    return str(text).replace("|", "\\|").replace("\n", " ")


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
    """只取中文权威正文；缺失时宁可不附规则文本，也不回退到派生译文。

    卡包译文已实测存在大规模内容失真，不能生成任何面向消费者的主张。调用方仍可用
    条款号与页码作引用；本函数没有中文权威正文时返回 ``None``。
    """
    del rule_slice  # 保留既有调用签名；RuleSlice 中的引文同样属于禁用译文层。
    zh = zh_authority.zh_text_for_card(getattr(card, "rule_card_id", ""))
    return zh.strip() if zh and zh.strip() else None


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

_NARRATIVE_REASON_LABELS: Dict[str, str] = {
    **_UNKNOWN_CAUSE_LABELS,
    "missing_obligation_edge_target": "缺少义务边目标",
    "unsupported_obligation_edge_relation": "义务边关系暂不支持",
    "unsupported_predicate_kind": "谓词类型暂不支持",
    "unsupported_operator": "比较运算暂不支持",
    "unsupported_formula": "计算公式暂不支持",
    "unsupported_deadline_relation": "期限关系暂不支持",
    "schema_contract_violation": "数据结构不符合契约",
    "target_unresolved": "核验目标无法定位",
    "qualifier_conflict": "限定条件互相冲突",
    "missing_artifact_mapping": "缺少产物映射",
    "internal_error": "系统内部处理异常",
    "null_observed_value": "实测值为空",
    "missing_sidecar_entry": "缺少补充数据项",
    "missing_required_qualifier": "缺少必需限定条件",
    "applicability_uncertain": "适用性尚未确定",
    "depends_on_open_trigger": "所依赖的触发义务尚未闭合",
}


def _narrative_reason_label(reason_code: Any) -> str:
    """把验证器原因码翻译为叙述标签；未知码不进入消费者叙述。"""
    code = str(reason_code or "").strip()
    return _NARRATIVE_REASON_LABELS.get(code, "原因码见未闭合项表")


def _narrative_value(value: Any) -> str:
    """确定性渲染叙述中的实测值或阈值，并保留假值与零值。"""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _narrative_item_aliases(items: List[Dict[str, Any]]) -> str:
    """列出聚合项的全部义务别名，并保留已有规则卡证据别名。"""
    rendered: List[str] = []
    for item in items:
        alias = f"[{item['alias']}]"
        rule_alias = item.get("rule_card_alias")
        if rule_alias:
            alias += f"（规则卡 [{rule_alias}]）"
        rendered.append(alias)
    return "、".join(rendered)


def render_deterministic_narrative(pack: NarrativeEvidencePack) -> str:
    """确定性叙述槽位模板（契约 v2 修订 4；两条 allow_stop 分支各一形态）。

    模型叙述未被接纳（拒绝耗尽 / 超时 / 未提交可用分析）时填入分析节槽位。
    不变量（按构造洁净）：
    - 输出守卫：禁止话术只以否定前缀（“非”）形态出现；
    - 叙述节闸：key_items 存在时每个要点都带证据别名；key_items 为空时
      alias_map 也为空，证据把手检查按定义跳过。
    消费者形态由 agent_v1/scripts/check_report_usability.py 审计，本函数不复制其判据。
    """
    lines = ["### 确定性叙述（程序模板，未采用模型分析）", ""]
    if pack.key_items:
        grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        for item in pack.key_items:
            category = item["category"]
            if category == "violated":
                key = (
                    category,
                    _narrative_value(item.get("observed")),
                    _narrative_value(item.get("threshold")),
                )
            else:
                key = (
                    category,
                    _narrative_reason_label(item.get("reason_code")),
                    "",
                )
            grouped.setdefault(key, []).append(item)

        for (category, detail, threshold), items in grouped.items():
            aliases = _narrative_item_aliases(items)
            count = len(items)
            if category == "violated":
                if count > 1:
                    lines.append(
                        f"- 以下 {count} 项疑似未满足（实测值 {detail}，阈值 "
                        f"{threshold}）：{aliases}；"
                        "建议人工审查员优先复核证据链。"
                    )
                else:
                    lines.append(
                        f"- {aliases} 疑似未满足：实测值 {detail}，阈值 "
                        f"{threshold}；建议人工审查员优先复核证据链。"
                    )
            elif category == "open":
                if count > 1:
                    lines.append(
                        f"- 以下 {count} 项未闭合（原因：{detail}）：{aliases}；"
                        "建议人工补充相关资料后重新评估。"
                    )
                else:
                    lines.append(
                        f"- {aliases} 未闭合（原因：{detail}）："
                        "建议人工补充相关资料后重新评估。"
                    )
            else:
                if count > 1:
                    lines.append(
                        f"- 以下 {count} 项验证器无法处理（原因：{detail}）："
                        f"{aliases}；需人工介入检查资料与规则适用性。"
                    )
                else:
                    lines.append(
                        f"- {aliases} 验证器无法处理（原因：{detail}）："
                        "需人工介入检查资料与规则适用性。"
                    )
    elif pack.allow_stop:
        lines.append(
            "- 闭包验证器确认开放项为 0、阻断项为 0，资料闭包已完成；"
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
    deferred_detail_blocks: List[List[str]] = []

    def _defer_latest_detail(start_index: int) -> None:
        """v4 把刚渲染的完整台账移到主视图之后；v3 保持原位。"""
        if contract_version < 4:
            return
        block = lines[start_index:]
        if not block or block[0] != "<details>" or "</details>" not in block:
            raise RuntimeError("v4 详细台账边界不完整，拒绝静默重排")
        deferred_detail_blocks.append(block)
        del lines[start_index:]

    def _extend_with_deferred_details(section_lines: List[str]) -> None:
        """保留节内主视图行，抽出顶层折叠块并按原顺序延后。"""
        if contract_version < 4:
            lines.extend(section_lines)
            return
        detail: List[str] = []
        depth = 0
        for line in section_lines:
            if depth == 0 and line == "<details>":
                detail = [line]
                depth = 1
            elif depth:
                detail.append(line)
                if line == "<details>":
                    depth += 1
                elif line == "</details>":
                    depth -= 1
                    if depth == 0:
                        deferred_detail_blocks.append(detail)
                        detail = []
            else:
                lines.append(line)
        if depth:
            raise RuntimeError("v4 节内详细台账未闭合，拒绝静默重排")
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

    # --- 行动项前置（v4 消费者轴，2026-08-01 与 v1 告知书同一改造同步）---
    # v1（render_incomplete_closure_notice）2026-07-30 已把「需要你补充的资料」
    # 提到文首——审查员打开文档首先要回答的是「这栋楼我现在该去看什么、补什么」，
    # 不是 run_id / stop_reason 这类开发者语言。v4 当时没同步（同一个改动只做了
    # 一半），行动项埋在 unknown 归因节里。此处只换顺序、不删内容：归因节原位置
    # 留一行指回（见 render_unknown_attribution_section 的 skip_action_items 注释）。
    # 行动项的「涉及 N 处」按验证器作用域关系旁路剔显式互斥部位（纯呈现）。
    if contract_version >= 4:
        _mr_v4 = result.machine_readable_report or {}
        lines.extend(
            _render_professional_action_items(
                result.unknown_attribution_by_obligation_id or {},
                obligation_index=_index_unclosed_obligations(
                    _mr_v4.get("open_items", []) or [],
                    _mr_v4.get("blocked_items", []) or [],
                ),
                building_id=str(_g(_mr_v4, "building_id") or ""),
                type_incompatible_obligation_ids=(
                    _type_incompatible_obligation_ids(result)
                ),
            )
        )
        lines.append(
            "> 以下为诊断明细。**若你只想知道该做什么，看完上面一节即可**。"
        )
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
        family_detail_start: Optional[int] = None
        # v4 收官形态把 40+ 行 family 明细表折进 <details>（2026-07-23 codex 聚合
        # 设计商议：不折叠时 v4 主视图压不进 A 门 180 行预算）；v3 保持原样。
        if contract_version >= 4:
            total_cards = sum(
                int(fam.get("rule_card_count") or 0) for fam in rule_families)
            lines.append(
                f"- 适用法规切片：{len(rule_families)} 个 family、"
                f"{total_cards} 张 rule card（明细见下折叠表）")
            lines.append("")
            family_detail_start = len(lines)
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
        if family_detail_start is not None:
            _defer_latest_detail(family_detail_start)

    # --- 权威闭包概览 ---
    lines.append("## 权威闭包概览")
    lines.append("")
    lines.append("> 本节由系统确定性生成；以下字段以闭包验证器结果为准。")
    lines.append("")
    lines.append(f"- total: {summary.total_obligations}")
    lines.append(f"- open: {summary.open_count}")
    lines.append(f"- blocked: {summary.blocked_count}")
    lines.append(f"- closed: {summary.closed_count}")
    # DEBT-083 丁护栏②：镜像一致性副本分账（无镜像时与旧格式逐字节同）。
    _m_sat, _m_vio = _mirror_verdict_counts(result)
    lines.append(_verdict_count_line("satisfied", summary.satisfied_count, _m_sat))
    lines.append(_verdict_count_line("violated", summary.violated_count, _m_vio))
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
        unclosed_detail_start = len(lines)
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
        _defer_latest_detail(unclosed_detail_start)

    # display_ref 映射(spec §7.4.4 E-4.2):由权威 canonical_identity_hash 派生,
    # 供本节高风险表、分析节、复核提示节统一使用,运行期哈希移出人读主视图。
    identity_manifest = getattr(result.obligation_set, "identity_manifest", None)
    display_ref_map, cano_by_oid = _build_display_ref_map(obligations, identity_manifest)

    # --- unknown 归因（消费者验收标准落点）---
    # 与 `render_incomplete_closure_notice` / `render_auxiliary_review_report`
    # 共用同一渲染实现：两条报告入口只要有一条自算，就必然与权威映射分叉。
    # v4 主视图有行数预算，故 v4+ 把逐项说明折进 <details>（计数表仍在主视图）。
    _extend_with_deferred_details(render_unknown_attribution_section(
        result,
        collapsible=contract_version >= 4,
        display_ref_map=display_ref_map,
        # v4 文首已渲染行动项（消费者轴改造）：原位置不重复渲染、只留指回行——
        # 重复会把 A 门重复行率顶过 5%（2026-07-31 v1 改造时实测撞过一次）。
        # v3 保持缺省 False，行为逐字节不变。
        skip_action_items=contract_version >= 4,
        action_items_relocated=contract_version >= 4,
    ))

    # --- violated / high-risk 项与程序计数 ---
    lines.append("## 疑似未满足 / 高风险项")
    lines.append("")
    # DEBT-083 丁护栏②：violated 里的镜像副本单列，不计独立法规判断。
    _pc_mirror_vio = _mirror_verdict_counts(result)[1]
    _pc_mirror_note = (
        f"（其中镜像一致性副本 {_pc_mirror_vio} 条，与来源触发器同判、"
        "不构成独立法规判断）" if _pc_mirror_vio else ""
    )
    lines.append(
        f"程序计数：violated = {summary.violated_count}{_pc_mirror_note}，"
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
    violated_detail_start: Optional[int] = None
    if violated_items:
        lines.append("**疑似未满足聚合（按规则卡，主视图；完整逐条见下方折叠块）**")
        lines.append("| rule_card | 条数 |")
        lines.append("|---|---:|")
        lines.extend(_violated_agg_rows(violated_items, guard_safe_data))
        lines.append("")
        violated_detail_start = len(lines)
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
        if violated_detail_start is not None:
            _defer_latest_detail(violated_detail_start)
    if result.high_risk_items:
        high_risk_detail_start = len(lines)
        if contract_version >= 4:
            lines.append("<details>")
            lines.append(
                "<summary>额外高风险项完整台账（程序渲染，点击展开）</summary>"
            )
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
        if contract_version >= 4:
            lines.append("</details>")
        lines.append("")
        if contract_version >= 4:
            _defer_latest_detail(high_risk_detail_start)

    # --- 法规引用与证据（程序辑录，别名↔真实 ID 对照供人工回查）---
    evidence_detail_start = len(lines)
    if contract_version >= 4:
        lines.append("<details>")
        lines.append(
            "<summary>法规引用与证据完整台账（程序辑录，点击展开）</summary>"
        )
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
    if contract_version >= 4:
        lines.append("</details>")
    lines.append("")
    if contract_version >= 4:
        _defer_latest_detail(evidence_detail_start)

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

    # --- 乙11 分辨率限制披露（2026-08-05，决议_33处置_20260805.md §一.2）---
    # 位置在「人工复核提示」**之前**：它给的是复核时必须知道的前提
    # （这两条必然同判、要分别核实），读者先看到前提再看到动作才成立。
    # 本次运行未命中登记卡时返回空清单 ⇒ 不占版面。
    lines.extend(render_shared_reading_disclosure_section(
        list(result.obligation_set.obligations), display_ref_map))

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
    review_detail_start: Optional[int] = None
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
        review_detail_start = len(lines)
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
    if review_detail_start is not None:
        _defer_latest_detail(review_detail_start)

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
        display_map_detail_start = len(lines)
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
        _defer_latest_detail(display_map_detail_start)

    if contract_version >= 4 and deferred_detail_blocks:
        lines.append(
            "> 以下为完整逐条台账，默认收起、可逐块展开。"
            "PDF/打印导出前须先展开全部折叠块；Markdown 源文件与 JSON 产物"
            "始终保留完整逐条内容。"
        )
        for detail_block in deferred_detail_blocks:
            lines.extend(detail_block)

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
    "render_scope_relation_diagnostic_section",
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
