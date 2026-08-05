"""报告契约 v4：无自由文本的结构化提交（spec §7.4.5 / E-5，Gate C 严格 0 严重错释）。

核心原则（spec E-5.7 不变量）：报告中任何关于法规要求/义务状态/阈值/事实值/原因的
陈述，必须由权威运行产物或经审定静态模板生成；**模型输出不得作为这些内容的数据源**。

模型每点只提交 4 字段（E-5.1，`additionalProperties: false`）：
    {obligation_alias, analysis_code, selected_fact_aliases, review_action_code}
严禁 text / gap_description / rule_alias / rule_summary / reason_code / status /
observed_value / threshold / 任意额外字段——一切规则语义由程序从权威对象组装。

本模块只提供 v4 的**契约常量 + 校验 + 确定性渲染**，是自足单元，不改 v3 现行路径。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, get_args

from evo_agent_baseline.contracts import BlockedReasonCode, OpenReasonCode

# ---------------------------------------------------------------------------
# E-5.5 reason_code → 中文模板。**只解释"系统为何 open/blocked"，不得偷渡规则卡释义**。
# 反例（禁止）：missing_artifact_evidence → "尚未取得规则要求的材料证书"（又在声称规则要求）。
# 正例（允许）：missing_artifact_evidence → "尚未取得用于核验该义务的材料证据"。
# 每条同时给 canonical analysis_code 与允许的 review_action_code 集合（数据驱动兼容矩阵）。
# ---------------------------------------------------------------------------
_R = Dict[str, Any]

REASON_CODE_SPEC: Dict[str, _R] = {
    # ---- open 原因码（11）----
    "missing_fact": {
        "zh": "系统尚未取得用于核验该义务的事实数据",
        "analysis": "EVIDENCE_GAP",
        "actions": ["OBTAIN_MISSING_EVIDENCE", "MANUAL_VERIFY"],
    },
    "null_observed_value": {
        "zh": "该义务对应的观测值为空，系统无法据以核验",
        "analysis": "EVIDENCE_GAP",
        "actions": ["OBTAIN_MISSING_EVIDENCE", "MANUAL_VERIFY"],
    },
    "missing_sidecar_entry": {
        "zh": "缺少所需的随附记录条目，系统无法据以核验",
        "analysis": "EVIDENCE_GAP",
        "actions": ["OBTAIN_MISSING_EVIDENCE", "MANUAL_VERIFY"],
    },
    "missing_measurement": {
        "zh": "尚未取得所需的测量数据",
        "analysis": "MEASUREMENT_REVIEW",
        "actions": ["OBTAIN_MEASUREMENT", "MANUAL_VERIFY"],
    },
    "missing_artifact_evidence": {
        "zh": "尚未取得用于核验该义务的材料/文件证据",
        "analysis": "EVIDENCE_GAP",
        "actions": ["OBTAIN_MISSING_EVIDENCE", "MANUAL_VERIFY"],
    },
    "missing_time_anchor": {
        "zh": "缺少所需的时间锚点，系统无法判定时限相关状态",
        "analysis": "TIME_ANCHOR_REVIEW",
        "actions": ["SUPPLY_TIME_ANCHOR", "MANUAL_VERIFY"],
    },
    "missing_required_qualifier": {
        "zh": "缺少所需的限定条件字段",
        "analysis": "FIELD_GROUP_REVIEW",
        "actions": ["SUPPLY_REQUIRED_FIELDS", "MANUAL_VERIFY"],
    },
    "missing_required_field_group": {
        "zh": "缺少所需的字段组，记录不完整",
        "analysis": "FIELD_GROUP_REVIEW",
        "actions": ["SUPPLY_REQUIRED_FIELDS", "MANUAL_VERIFY"],
    },
    "applicability_uncertain": {
        "zh": "该义务是否适用于本建筑尚不确定",
        "analysis": "APPLICABILITY_REVIEW",
        "actions": ["MANUAL_VERIFY"],
    },
    "depends_on_open_trigger": {
        "zh": "该义务取决于一个尚未闭合的前置触发条件",
        "analysis": "APPLICABILITY_REVIEW",
        "actions": ["RESOLVE_PRECONDITION", "MANUAL_VERIFY"],
    },
    # 2026-07-27 codex 审核门 P1-A：`obligation_deriver` 的「无卡侧可确定通道 → 缺省
    # 拒绝」分支产出此码（已登记在 `contracts.OpenReasonCode`），**却漏进本表** ⇒
    # `reason_key_of` 返回 None ⇒ 受影响义务过不了 v4 契约、整篇回退 ⇒ **消费者根本
    # 看不到这块缺口**。现批计数为 0 只因批用的是旧代码，重跑后它会是最大的一块。
    # 语义不是「缺一条事实」而是「系统不知道该核什么」（动作没绑到可核验的事实槽），
    # 故归 MODELING_GAP：让消费者去找建模缺口，别白跑一趟补资料。
    "missing_satisfaction_binding": {
        "zh": "系统未能确定该义务的满足判据（没有可核验的事实绑定），无法据以核验",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    # 2026-07-27：证据许可闸产出。语义**不是产物**的义务（检验涵盖范围 / 记录 /
    # 报告栏目 / 动作）此前会因「相关产物齐备布尔=true」被判 satisfied、=false 被判
    # violated——一份报告可以齐备而漏检半栋楼，该推断不成立。现改判 unknown。
    # 归 MODELING_GAP：要修的是卡侧把义务绑到了证明不了它的槽，不是消费者少交材料。
    "artifact_state_not_valid_evidence": {
        "zh": "该义务只绑定到「相关文件是否齐备」这一状态，而文件齐备并不能证明该义务本身"
              "已经履行，系统据此拒绝下确定判定",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    # 2026-08-03 仲裁「丁」路：同上闸，但绑定的是**非产物读数**，故文案不得提「文件」。
    "diagnostic_binding_not_valid_evidence": {
        "zh": "该义务绑定到的这类读数，经逐项对法规原文裁定并不能证明该义务本身已经履行，"
              "系统据此拒绝下确定判定",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    # A′裁决（2026-08-02，DEBT-083 第 5 步绑定级值授权）——不得渲染成
    # 「缺少事实」或「请补交同一证据」：读数已取得且完整。
    "observed_false_without_violation_basis": {
        "zh": "已取得完整聚合读数，结果表明正向条件尚未成立；当前没有足够的期限"
              "或终局违约依据，程序不判违反，交由专业人员复核",
        "analysis": "PENDING_COMPLETION_REVIEW",
        "actions": ["MANUAL_VERIFY"],
    },
    # S3 裁决（2026-08-02）：不得渲染成"缺少事实"——事实在，缺的是该绑定
    # 消费此类读数产判定的裁定授权。
    "binding_requires_adjudication_authorization": {
        "zh": "系统已取得相关读数，但该义务绑定尚未获得消费此类读数下判定的"
              "裁定授权，程序按保守原则不给结论，待维护方完成逐绑定裁定",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    # ---- blocked 原因码（15）----
    "missing_rule_edge": {
        "zh": "规则图谱缺少所需的关系边，系统无法完成该义务的核验编排",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "missing_obligation_edge_target": {
        "zh": "义务关系边的目标未解析，系统无法完成核验编排",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unsupported_obligation_edge_relation": {
        "zh": "义务关系类型当前不受支持，系统无法完成核验编排",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unsupported_predicate_kind": {
        "zh": "该义务的判定谓词类型当前不受支持",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unsupported_operator": {
        "zh": "该义务的比较算子当前不受支持",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unsupported_formula": {
        "zh": "该义务的计算公式当前不受支持",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unsupported_deadline_relation": {
        "zh": "该义务的时限关系当前不受支持",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "unit_mismatch": {
        "zh": "证据单位与义务所需单位不一致，系统无法直接比较",
        "analysis": "SCHEMA_ISSUE",
        "actions": ["RECONCILE_UNIT", "MANUAL_VERIFY"],
    },
    "ambiguous_fact_binding": {
        "zh": "该义务的事实绑定存在歧义，系统无法唯一确定所指",
        "analysis": "AMBIGUITY_REVIEW",
        "actions": ["DISAMBIGUATE_BINDING", "MANUAL_VERIFY"],
    },
    "schema_contract_violation": {
        "zh": "数据违反 schema 契约，系统无法安全核验",
        "analysis": "SCHEMA_ISSUE",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "target_unresolved": {
        "zh": "该义务的目标对象未能解析",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "qualifier_conflict": {
        "zh": "该义务的限定条件之间存在冲突",
        "analysis": "AMBIGUITY_REVIEW",
        "actions": ["DISAMBIGUATE_BINDING", "MANUAL_VERIFY"],
    },
    "missing_artifact_mapping": {
        "zh": "缺少所需的材料/文件映射，系统无法定位对应证据",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "artifact_not_modeled_upstream": {
        "zh": "所需材料/文件在上游数据建模中缺失",
        "analysis": "MODELING_GAP",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    "internal_error": {
        "zh": "核验过程中出现内部错误",
        "analysis": "SCHEMA_ISSUE",
        "actions": ["ESCALATE_MODELING_GAP", "MANUAL_VERIFY"],
    },
    # ---- violated 项合成键（closed 但 satisfaction=violated，无 open/blocked reason_code）----
    # 2026-07-23 真实数据集成测试发现:key_items 含 violated 义务，reason_code=None。
    # 用 category 合成此键,给它专属 analysis/模板/动作。
    "__violated__": {
        "zh": "程序判定为 closed，但满足状态为 violated（疑似未满足），建议人工复核",
        "analysis": "SUSPECTED_VIOLATION",
        "actions": ["MANUAL_VERIFY"],
    },
}

# review_action_code → 中文措辞。**只产"建议复核/补证"措辞，绝不升级为 satisfied/violated**
# （E-5.7 判定权红线）。
REVIEW_ACTION_ZH: Dict[str, str] = {
    # 措辞保持通用："材料/文件"会错误覆盖 missing_fact（普通触发 slot）/
    # null_observed_value（数值）等场景——具体缺什么由上方原因行（reason_code
    # 模板）说明，动作行不窄化（2026-07-23 copilot 终审四轮审出）。
    "OBTAIN_MISSING_EVIDENCE": "取得缺失的证据数据后重新运行核验",
    "OBTAIN_MEASUREMENT": "补充所需测量数据后重新运行核验",
    "SUPPLY_TIME_ANCHOR": "补充所需时间锚点后重新运行核验",
    "SUPPLY_REQUIRED_FIELDS": "补齐所需字段后重新运行核验",
    "RESOLVE_PRECONDITION": "先处理前置未闭合项，再复核本义务",
    "DISAMBIGUATE_BINDING": "人工厘清事实绑定歧义后复核",
    "RECONCILE_UNIT": "统一单位后重新比较",
    "ESCALATE_MODELING_GAP": "上报数据/规则建模缺口，暂由人工复核",
    "MANUAL_VERIFY": "建议人工审查员复核该义务",
}

# analysis_code / review_action_code 全集（Schema 闸枚举校验用）。
ANALYSIS_CODES = frozenset(spec["analysis"] for spec in REASON_CODE_SPEC.values())
REVIEW_ACTION_CODES = frozenset(REVIEW_ACTION_ZH)

# closure status 中文（E-5.5 "当前状态"层，来自 closure 权威，不由模型产出）。
# ---- reason → 允许状态（E-5.3 的 status+reason 兼容矩阵）----
# 2026-07-23 codex 聚合设计商议补缺:原实现只验 analysis/action↔reason,
# 从未验 category↔reason;供给侧错位(如 open 义务挂 blocked 原因码)曾可静默过。
_OPEN_REASONS = frozenset({
    "missing_fact", "null_observed_value", "missing_sidecar_entry",
    "missing_measurement", "missing_artifact_evidence", "missing_time_anchor",
    "missing_required_qualifier", "missing_required_field_group",
    "applicability_uncertain", "depends_on_open_trigger",
    "missing_satisfaction_binding", "artifact_state_not_valid_evidence",
    "diagnostic_binding_not_valid_evidence",
    "observed_false_without_violation_basis",
    "binding_requires_adjudication_authorization",
})
_BLOCKED_REASONS = frozenset({
    "missing_rule_edge", "missing_obligation_edge_target",
    "unsupported_obligation_edge_relation", "unsupported_predicate_kind",
    "unsupported_operator", "unsupported_formula", "unsupported_deadline_relation",
    "unit_mismatch", "ambiguous_fact_binding", "schema_contract_violation",
    "target_unresolved", "qualifier_conflict", "missing_artifact_mapping",
    "artifact_not_modeled_upstream", "internal_error",
})
assert set(REASON_CODE_SPEC) == (_OPEN_REASONS | _BLOCKED_REASONS | {"__violated__"}), \
    "REASON_CODE_SPEC 与状态兼容矩阵不同步"

# 🔴 结构性闸（2026-07-27 codex 审核门 P1-A）：**双向**对齐权威原因码清单
# （`contracts.OpenReasonCode` / `BlockedReasonCode`）。
# 上面那条 assert 只保证本文件**内部**三张表自洽——`missing_satisfaction_binding`
# 正是这样漏掉的：派生器产它、contracts 登记它、本表没有，内部依然自洽。
# 本闸在**导入时**就炸，故下次谁新增原因码而忘了登记模板，第一次 import 就知道。
# 方向二（本表多出 contracts 没有的码）同样拦——那意味着模板在解释一个不存在的状态。
_AUTHORITATIVE_REASONS = frozenset(
    get_args(OpenReasonCode) + get_args(BlockedReasonCode)
)
_SPEC_REASONS = frozenset(REASON_CODE_SPEC) - {"__violated__"}
assert _SPEC_REASONS == _AUTHORITATIVE_REASONS, (
    "REASON_CODE_SPEC 与 contracts 权威原因码清单不同步；"
    f"contracts 有而本表缺={sorted(_AUTHORITATIVE_REASONS - _SPEC_REASONS)}；"
    f"本表有而 contracts 缺={sorted(_SPEC_REASONS - _AUTHORITATIVE_REASONS)}"
)


def allowed_statuses(reason_key: str) -> frozenset:
    """该原因码允许出现的义务 category。空集=未知原因(调用方 fail-closed)。"""
    if reason_key == "__violated__":
        return frozenset({"violated"})
    if reason_key in _OPEN_REASONS:
        return frozenset({"open"})
    if reason_key in _BLOCKED_REASONS:
        return frozenset({"blocked"})
    return frozenset()


_STATUS_ZH = {"open": "程序判定为 open（资料未闭合）",
              "blocked": "程序判定为 blocked（核验器无法处理）",
              "closed": "程序判定为 closed",
              "violated": "程序判定为 closed，满足状态为 violated（疑似未满足）"}


def reason_key_of(item: Dict[str, Any]) -> Optional[str]:
    """从 key_item 解析 v4 模板键:有 open/blocked reason_code 用之;
    violated 项（closed 但 satisfaction=violated，无 reason_code）合成 `__violated__`。
    其余（无 reason 又非 violated）返回 None → 渲染/校验按缺权威 fail-closed。
    """
    reason = item.get("reason_code")
    if reason and str(reason) in REASON_CODE_SPEC:
        return str(reason)
    if str(item.get("category") or "") == "violated":
        return "__violated__"
    return None


def reason_zh(reason_code: Optional[str]) -> str:
    spec = REASON_CODE_SPEC.get(str(reason_code or ""))
    return spec["zh"] if spec else "系统未给出可解释的原因码"


def allowed_analysis(reason_code: Optional[str]) -> Optional[str]:
    spec = REASON_CODE_SPEC.get(str(reason_code or ""))
    return spec["analysis"] if spec else None


def allowed_actions(reason_code: Optional[str]) -> List[str]:
    spec = REASON_CODE_SPEC.get(str(reason_code or ""))
    return list(spec["actions"]) if spec else ["MANUAL_VERIFY"]


V4_REQUIRED_FIELDS = {"obligation_alias", "analysis_code",
                      "selected_fact_aliases", "review_action_code"}

# report_writer 对未取到引文的规则卡写的占位值；v4 渲染不得当权威条文（copilot 审#2）。
_PLACEHOLDER_QUOTES = {"（未取得引文）"}


def validate_submission_payload_v4(
    payload: Any, key_items: List[Dict[str, Any]]
) -> Tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """v4 Schema 闸 + 关系闸（spec E-5.4 ①②）。整篇原子：任一点失败 → 整篇拒绝。

    key_items = build_narrative_evidence_pack(...).key_items（权威证据包，程序产出）。
    返回 (规范化点列 or None, 错误列表)。错误非空即整篇不接纳。
    """
    errors: List[Dict[str, Any]] = []

    def add(code: str, pointer: str, hint: str) -> None:
        errors.append({"error_code": code, "pointer": pointer, "fix_hint": hint})

    if not isinstance(payload, dict):
        add("payload_not_object", "/", "提交必须是对象 {contract, points}")
        return None, errors
    if payload.get("contract") != "report_contract_v4":
        add("wrong_contract", "/contract", "contract 必须为 report_contract_v4")
    # 顶层 additionalProperties:false（2026-07-23 copilot 审出#4：顶层加 rule_summary
    # 等自由文本字段此前被直接接纳）。只允许 contract/points。
    top_extra = set(payload.keys()) - {"contract", "points"}
    if top_extra:
        add("top_additional_properties", "/",
            f"顶层禁止额外字段：{sorted(top_extra)}；只允许 contract/points")
    points = payload.get("points")
    if not isinstance(points, list) or not points:
        add("points_missing", "/points", "points 必须是非空数组")
        return None, errors

    # 权威索引:O 别名 → item
    item_by_alias = {it["alias"]: it for it in key_items}
    normalized: List[Dict[str, Any]] = []
    seen_o: set = set()

    for i, pt in enumerate(points):
        ptr = f"/points/{i}"
        if not isinstance(pt, dict):
            add("point_not_object", ptr, "每个点必须是对象")
            continue
        # E-5.4①Schema 闸:字段全集 + additionalProperties:false + 拒绝自由文本
        extra = set(pt.keys()) - V4_REQUIRED_FIELDS
        if extra:
            add("additional_properties", ptr,
                f"禁止额外字段（含任何自由文本）：{sorted(extra)}；"
                "v4 只接受 obligation_alias/analysis_code/selected_fact_aliases/review_action_code")
        missing = V4_REQUIRED_FIELDS - set(pt.keys())
        if missing:
            add("missing_fields", ptr, f"缺字段：{sorted(missing)}")
            continue

        # E-5.4①字段类型严格先验（2026-07-23 copilot 审出#4：类型未先验，
        # analysis_code=[] 等在集合成员检查处崩 TypeError→internal_error 而非干净拒绝）。
        o_alias = pt["obligation_alias"]
        analysis = pt["analysis_code"]
        facts = pt["selected_fact_aliases"]
        action = pt["review_action_code"]
        type_bad = False
        for fld, val, want_str in (("obligation_alias", o_alias, True),
                                   ("analysis_code", analysis, True),
                                   ("review_action_code", action, True)):
            if not isinstance(val, str):
                add("field_type", f"{ptr}/{fld}", f"{fld} 必须是字符串")
                type_bad = True
        if not isinstance(facts, list) or not all(isinstance(x, str) for x in facts):
            add("field_type", f"{ptr}/selected_fact_aliases",
                "selected_fact_aliases 必须是字符串数组")
            type_bad = True
        if type_bad:
            continue

        if o_alias not in item_by_alias:
            add("unknown_obligation_alias", f"{ptr}/obligation_alias",
                f"obligation_alias 必须是证据包内的 O 别名：{o_alias}")
            continue
        if o_alias in seen_o:
            add("duplicate_obligation", f"{ptr}/obligation_alias",
                f"同一义务 {o_alias} 重复提交；每义务至多一点")
            continue
        seen_o.add(o_alias)

        item = item_by_alias[o_alias]
        reason = reason_key_of(item)  # open/blocked reason_code 或 violated 合成键
        if reason is None:
            add("no_authoritative_reason", f"{ptr}/obligation_alias",
                f"义务 {o_alias} 无可解释的权威原因（非 open/blocked/violated）；不可入 v4 分析")
            continue

        # E-5.3 status↔reason 兼容（codex 聚合设计商议补缺：供给侧错位如 open
        # 义务挂 blocked 原因码，必须整篇拒绝，不得渲染自相矛盾的组）
        _cat = str(item.get("category") or "")
        if _cat not in allowed_statuses(reason):
            add("status_reason_incompatible", f"{ptr}/obligation_alias",
                f"义务 {o_alias} 的状态 {_cat or '（空）'} 与权威原因 {reason} 不兼容；"
                f"允许状态 {sorted(allowed_statuses(reason)) or '（无）'}")
            continue

        # E-5.4②关系闸:analysis_code 与权威 reason 兼容
        if analysis not in ANALYSIS_CODES:
            add("unknown_analysis_code", f"{ptr}/analysis_code",
                f"analysis_code 非法：{analysis}；合法集 {sorted(ANALYSIS_CODES)}")
        elif analysis != allowed_analysis(reason):
            add("analysis_reason_incompatible", f"{ptr}/analysis_code",
                f"analysis_code={analysis} 与该义务权威原因 {reason} 不兼容；"
                f"应为 {allowed_analysis(reason)}")

        # selected_fact_aliases ⊆ 该 O 的 fact_aliases
        if not isinstance(facts, list):
            add("facts_not_list", f"{ptr}/selected_fact_aliases", "必须是数组")
        else:
            allowed_facts = set(item.get("fact_aliases") or [])
            bad = [f for f in facts if f not in allowed_facts]
            if bad:
                add("fact_not_in_obligation", f"{ptr}/selected_fact_aliases",
                    f"这些事实不属于本义务的允许集合：{bad}；"
                    f"允许集 {sorted(allowed_facts) or '（无）'}")

        # review_action_code 合法且与 reason 兼容
        if action not in REVIEW_ACTION_CODES:
            add("unknown_action_code", f"{ptr}/review_action_code",
                f"review_action_code 非法：{action}")
        elif action not in allowed_actions(reason):
            add("action_reason_incompatible", f"{ptr}/review_action_code",
                f"review_action_code={action} 与 reason_code={reason} 不兼容；"
                f"允许 {allowed_actions(reason)}")

        normalized.append({
            "obligation_alias": o_alias,
            "analysis_code": analysis,
            "selected_fact_aliases": list(facts) if isinstance(facts, list) else [],
            "review_action_code": action,
        })

    if errors:
        return None, errors
    return normalized, errors


# ---------------------------------------------------------------------------
# E-5.5 确定性渲染（2026-07-23 codex 聚合设计定稿）：先**全点解析**（E-5.4③ 原子性
# 不变：任一点缺权威映射/quote/模板 → 返回 None 整篇 fallback），全部成功后按
# 语义四元组 (status, analysis_code, reason, action) 聚组展示——主视图每组三行
# （标题/义务入口/共享状态·原因·动作），逐义务明细（所选证据+法规逐字引文）折进
# 组内 <details>。A 门实证：逐点展开形态 24 点批主视图 ~325 行/重复 ~30%，聚合后
# 预算 ≤26 行。所有句子仍全部来自权威对象/审定模板，模型零自由文本（E-5 不变）。
# ---------------------------------------------------------------------------
_STATUS_ORDER = {"violated": 0, "open": 1, "blocked": 2}
_GROUP_MAX_MEMBERS = 8  # 单组成员上限；超出按同签名确定性分片，绝不跨签名合并


def _resolve_v4_points(
    pack: Any, normalized_points: List[Dict[str, Any]]
) -> Optional[List[Dict[str, Any]]]:
    """阶段一：逐点解析全部权威对象为 ResolvedV4Point；任一失败返回 None。"""
    item_by_alias = {it["alias"]: it for it in pack.key_items}
    card_by_alias = {c["alias"]: c for c in pack.rule_cards}
    fact_by_alias = {f["alias"]: f for f in pack.facts}

    resolved: List[Dict[str, Any]] = []
    for index, pt in enumerate(normalized_points):
        o_alias = pt["obligation_alias"]
        item = item_by_alias.get(o_alias)
        if item is None:
            return None  # 缺权威 O 映射 → 整篇 fallback
        reason = reason_key_of(item)  # open/blocked reason_code 或 violated 合成键
        if reason is None or reason not in REASON_CODE_SPEC:
            return None  # 缺 reason 模板 → 整篇 fallback
        r_alias = item.get("rule_card_alias")
        card = card_by_alias.get(r_alias) if r_alias else None
        # 缺权威条文的处理分两档（2026-08-04 收窄，保住两条底线）：
        # ① 卡都找不到 → 整篇 fallback（不变）；
        # ② 卡在、但引文是占位符「（未取得引文）」——即中文权威源对该卡**显式缺席**
        #    （11/470，附录表格类等）——**不再拉黑整篇**，该点的「法规依据」行降级为
        #    条款号引用＋缺席说明（诚实降级，见 render 段）。
        # 依据：2026-07-23 copilot 审出#2 防的是**占位符冒充引文**渲给消费者；
        # 显式写明「中文正文缺席，见条款号」不是冒充。而整篇拉黑的实测代价是
        # 11 张缺席卡把 15/30 栋的满血叙述全部黑洞掉——顶部 violated 项（如
        # §3.3.2(b) 缺陷识别）反而从叙述里消失，比诚实降级更误导。
        if card is None:
            return None  # 缺权威 R 映射 → 整篇 fallback（不变）
        _quote_absent = (not card.get("quote")
                         or card.get("quote") in _PLACEHOLDER_QUOTES)
        status = item.get("category")
        # 权威状态缺失/非法 → fail-closed（codex 聚合审核阻断#1：原实现
        # `or "open"` 会把缺失状态凭空补成 open，破坏"缺权威即 fallback"防御层）
        if status not in ("open", "blocked", "violated"):
            return None
        if status not in allowed_statuses(reason):
            return None  # status↔reason 不兼容（校验层也拦；渲染侧兜底 fail-closed）
        # 三重一致性互证（codex 聚合商议）：category 必须与权威原始字段一致——
        # violated ⇔ closure=closed 且 satisfaction=violated；open/blocked ⇔ 同名
        # closure 状态。字段缺失或不符 = 伪权威项 → 整篇 fallback。
        cs = item.get("closure_status")
        ss = item.get("satisfaction_status")
        if status == "violated":
            if not (cs == "closed" and ss == "violated"):
                return None
        elif cs != status:
            return None

        # 现有证据（模型选择的子集，值取自 FactPack 权威）。
        # copilot 审#2 的两种处置分级：
        #  · 占位 quote（法规依据，虚假权威声明）→ 整篇 fail-closed（上面已处理）；
        #  · 未解析事实（slot/value 皆 None，非虚假声明只是缺值）→ **从证据行略去**,
        #    不毁整篇（单个缺值事实不该 fallback 整报告）。全略光则显"暂无可列证据"。
        parts = []
        for f in (pt.get("selected_fact_aliases") or []):
            fd = fact_by_alias.get(f)
            if fd is None:
                return None  # 选了不存在的证据（关系闸本应已挡）→ 整篇 fallback
            if fd.get("slot_id") is None and fd.get("value") is None:
                continue  # 未解析事实：略去，不显示 value=None
            parts.append(
                f"[{f}] slot={fd.get('slot_id')}、value={fd.get('value')}、"
                f"unit={fd.get('unit')}")
        resolved.append({
            "submit_index": index,
            "o_alias": o_alias,
            "r_alias": r_alias,
            "rule_card_id": str(card.get("rule_card_id") or ""),
            "quote": card["quote"],
            "status": status,
            "reason": reason,
            "analysis_code": pt["analysis_code"],
            "action": pt["review_action_code"],
            "evidence_parts": parts,
            "quote_absent": _quote_absent,
        })
    return resolved


def render_v4_points(
    pack: Any, normalized_points: List[Dict[str, Any]]
) -> Optional[List[str]]:
    """把 v4 规范化点列渲染成确定性 markdown 行；缺任一权威条目返回 None。

    pack = NarrativeEvidencePack（key_items/rule_cards/facts 均程序权威产出）。
    展示形态＝语义四元组聚合（主视图三行/组 + 折叠逐义务明细），内容与安全
    属性同逐点展开形态（全部权威来源）。
    """
    resolved = _resolve_v4_points(pack, normalized_points)
    if resolved is None:
        return None

    # 阶段二：聚组（语义四元组签名）。组序 violated→open→blocked，再按
    # analysis/reason/action 字典序；组内保持提交顺序；单组 >8 同签名分片。
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for rp in resolved:
        sig = (rp["status"], rp["analysis_code"], rp["reason"], rp["action"])
        groups.setdefault(sig, []).append(rp)
    ordered_sigs = sorted(
        groups, key=lambda s: (_STATUS_ORDER.get(s[0], 9), s[1], s[2], s[3]))
    chunks: List[tuple] = []
    for sig in ordered_sigs:
        members = groups[sig]
        for i in range(0, len(members), _GROUP_MAX_MEMBERS):
            chunks.append((sig, members[i:i + _GROUP_MAX_MEMBERS]))

    # 阶段三：渲染。跨规则卡的组只是"同状态/同原因/同处置组"，法规语义仍
    # 逐义务展示（每个 O 紧邻自己的 R 与逐字引文，防"共享法规要求"视觉误导）。
    lines: List[str] = []
    for gi, (sig, members) in enumerate(chunks, 1):
        status, analysis, reason, action = sig
        lines.append(f"### G{gi}｜{_analysis_title(analysis)}｜{len(members)} 项")
        lines.append("- 义务入口："
                     + "、".join(f"[{m['o_alias']}/{m['r_alias']}]" for m in members))
        lines.append(
            f"- 状态 / 原因 / 动作：{_STATUS_ZH.get(status, status)}；"
            f"{reason_zh(reason)}；"
            f"{REVIEW_ACTION_ZH.get(action, '建议人工复核')}。")
        lines.append("")
        lines.append("<details>")
        lines.append(f"<summary>展开 {len(members)} 项的所选证据与法规原文</summary>")
        lines.append("")
        # 明细按 rule card、再按提交顺序排列
        for m in sorted(members, key=lambda x: (x["rule_card_id"], x["submit_index"])):
            lines.append(f"#### [{m['o_alias']}/{m['r_alias']}]")
            if m["evidence_parts"]:
                lines.append(f"- 现有证据：{'；'.join(m['evidence_parts'])}。")
            else:
                lines.append("- 现有证据：本义务暂无可列证据。")
            # 法规依据（逐字取程序辑录权威条文，绝不由模型撰写）
            if m.get("quote_absent"):
                # 诚实降级：不渲占位符、不编引文——条款号可查证，缺席说明如实。
                lines.append(
                    f"- 法规依据：[{m['r_alias']}] 卡 `{m['rule_card_id']}`"
                    "（中文权威正文对本卡显式缺席——附录表格类等，暂无逐字引文；"
                    "卡号内嵌条款号，请按其查阅守则原文）")
            else:
                lines.append(f"- 法规依据：[{m['r_alias']}] 「{m['quote']}」")
            lines.append("")
        lines.append("</details>")
        lines.append("")
    return lines


_ANALYSIS_TITLE = {
    "EVIDENCE_GAP": "证据缺口",
    "MEASUREMENT_REVIEW": "测量数据待补",
    "TIME_ANCHOR_REVIEW": "时间锚点待补",
    "FIELD_GROUP_REVIEW": "字段完整性待补",
    "APPLICABILITY_REVIEW": "适用性待复核",
    "AMBIGUITY_REVIEW": "绑定歧义待厘清",
    "MODELING_GAP": "建模缺口待上报",
    "SCHEMA_ISSUE": "数据契约问题",
    "SUSPECTED_VIOLATION": "疑似未满足待复核",
    "PENDING_COMPLETION_REVIEW": "正向条件尚未成立待复核",
}


def _analysis_title(code: str) -> str:
    return _ANALYSIS_TITLE.get(code, code)


def build_v4_model_payload(pack: Any) -> Dict[str, Any]:
    """把证据包转成 v4 模型可见 payload：复用 v3 脱敏基座，给每个 key_item 补
    `suggested_analysis_code`（由权威 reason_code 决定）与 `allowed_review_actions`，
    并换成 v4 usage_rules。不改 pack 的 v3 `to_model_payload`。
    """
    base = pack.to_model_payload()
    items: List[Dict[str, Any]] = []
    for it in base.get("key_items", []):
        reason = reason_key_of(it)  # open/blocked reason_code 或 violated 合成键
        items.append({
            **it,
            "suggested_analysis_code": allowed_analysis(reason) or "EVIDENCE_GAP",
            "allowed_review_actions": allowed_actions(reason),
        })
    return {
        **base,
        "contract": "report_contract_v4",
        "key_items": items,
        "usage_rules": [
            "只提交 obligation_alias/analysis_code/selected_fact_aliases/review_action_code 四字段，禁止任何其它字段与自由文本",
            "analysis_code 必须填该义务 key_item 的 suggested_analysis_code",
            "selected_fact_aliases 只能从该义务自己的 fact_aliases 里选",
            "review_action_code 从该义务 key_item 的 allowed_review_actions 里选",
            "规则要求/状态/原因/最终句子全部由程序权威生成，你不写任何规则语义",
        ],
    }
