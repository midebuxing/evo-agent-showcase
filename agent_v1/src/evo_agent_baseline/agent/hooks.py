"""evo-agent baseline agent 运行期 hook（spec §7.3）。

本文件实现 spec §7.3.1 hook event list 列出的五个 hard hook，是 evo-agent blind
红线的第二道与第三道防线（System Prompt 为第一道）：

| hook                       | 时机                     | hard/soft |
|----------------------------|--------------------------|-----------|
| pre_run_input_guard        | 创建 run 后、检索前      | hard      |
| pre_retrieval_query_guard  | 每次 KG query 前         | hard      |
| post_retrieval_source_audit| FactPack/RuleSlice 构造后| hard      |
| post_verifier_stop_gate    | verifier 返回后          | hard      |
| pre_output_language_guard  | LLM 输出前               | hard      |

红线（spec §1.0 原则 3 / §7.1 规则 3、9）：W2 NormativeProjection /
expected_verdict / 参考真值不得成为 agent 输入、KG、检索源或 verifier 输入；
agent 不得输出最终合规裁决。以上 hook 在各时点强制拦截违规。

spec→code 单向：禁止常量集合按 spec §7.3.3 / 附录 A 照搬，不自创。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ===========================================================================
# 一、安全异常
# ===========================================================================


# blind 红线异常统一定义在包根 errors.py（与 ingest.guard 共用同一类，确保
# 检索/灌库层抛的 SecurityError 能被本层及编排层的 except 捕获、不跨层漏接）。
from evo_agent_baseline.errors import SecurityError  # noqa: E402,F401  re-export


class OutputGuardError(Exception):
    """输出语言守卫违规异常（spec §7.3.6）。

    LLM 输出含禁止话术（最终裁决等）时抛出，要求重写。
    """


# ===========================================================================
# 二、禁止常量集合（spec §7.3.3 / 附录 A.1 / A.2 / A.3）
# ===========================================================================

# 附录 A.1：agent database 禁止 labels。
# 注意（spec §7.3.3 末注）：`RuleThreshold` 是允许 label；`ThresholdEval` 是禁止 label。
AGENT_FORBIDDEN_LABELS = frozenset(
    {
        "NormativeProjection",
        "ProjectionFamilyEval",
        "ThresholdEval",
        "ReportBasisItem",
        "ExpectedVerdict",
        "EvalNormativeProjection",
        "EvalProjectionFamilyEval",
        "EvalThresholdEval",
        "EvalBasisItem",
        "HiddenGold",
        "QueryEpisode",
        "InvestigatorSimulation",
    }
)

# 附录 A.2：agent database 禁止属性名（blind 第二道防线）。
AGENT_FORBIDDEN_PROPERTIES = frozenset(
    {
        "expected_verdict",
        "selected_family",
        "projection_status",
        "basis_items",
        "unknown_reason_code",
        "regime_tag",
        "pass_bool",
        "projection_id",
        "projection_registry_id",
        "projection_family",
        "projection_version",
        "required_world_core_slots",
        "required_measurement_slots",
        "required_qualifier_slots",
        "required_sidecar_interfaces",
        "matched_component_refs",
        "matched_measurement_ids",
        "coverage_status",
        "raw_projection_ref_hash",
        "projection_ref_hash",
    }
)

# 附录 A.3：agent database 禁止 files（W2 法规映射层 parquet）。
AGENT_FORBIDDEN_FILES = frozenset(
    {
        "normative_projection_meta.parquet",
        "projections.parquet",
        "matched_families.parquet",
        "threshold_evaluations.parquet",
        "coverage_control_metadata.parquet",
        "basis_items.parquet",
    }
)

# spec §7.3.4 白名单例外：以下名字虽为 substring 易误命中，但属合法 W0 事实字段
# 或 verifier 自有字段，post_retrieval_source_audit 不得据此判违规。
# - world_id / fragment_id / severity_band：W0 事实字段
# - applicability_state：verifier-owned 字段（不得来自 W2）
AUDIT_WHITELIST_EXCEPTIONS = frozenset(
    {
        "world_id",
        "fragment_id",
        "severity_band",
        "applicability_state",
    }
)

# spec §7.3.3：pre_retrieval_query_guard 拒绝任何含以下片段的查询。
# 每个片段为独立子模式，命中任一即拒。`.parquet` 中的点已转义为字面量。
FORBIDDEN_QUERY_PATTERNS: List[str] = [
    # 第 1 组：W2 labels
    r"NormativeProjection",
    r"ExpectedVerdict",
    r"ProjectionFamilyEval",
    r"ThresholdEval",
    r"ReportBasisItem",
    # 第 2 组：W2 / evaluator 属性名
    r"expected_verdict",
    r"selected_family",
    r"projection_status",
    r"basis_items",
    r"coverage_status",
    # 第 3 组：W2 projection input slot 字段
    r"required_world_core_slots",
    r"required_measurement_slots",
    r"required_qualifier_slots",
    r"required_sidecar_interfaces",
    # 第 4 组：W2 match 字段
    r"matched_component_refs",
    r"matched_measurement_ids",
    # 第 5 组：W2 parquet 文件名
    r"projections\.parquet",
    r"matched_families\.parquet",
    r"threshold_evaluations\.parquet",
    r"basis_items\.parquet",
]

# 预编译为单个 alternation 正则，大小写不敏感（查询文本可能含变体）。
_FORBIDDEN_QUERY_RE = re.compile(
    "|".join(f"(?:{p})" for p in FORBIDDEN_QUERY_PATTERNS),
    re.IGNORECASE,
)

# spec §7.3.6 / 附录 A.4：pre_output_language_guard 禁止话术。
FORBIDDEN_OUTPUT_PHRASES: List[str] = [
    "最终裁决",
    "最终合规",
    "最终不合规",
    "结案",
    "本建筑已合规",
    "本建筑不合规",
    "according to expected_verdict",
    "based on NormativeProjection",
]

# spec 附录 A.4 显式列出的“允许替代表述”含否定式免责声明，例如
# “本报告为人工审查辅助材料，非最终裁决…”；spec §7.2.4 / 附录 C 强制的报告
# 标题也是“# MBIS 辅助审查报告（非最终裁决）”。因此禁止话术若以否定语
# “非”/“不构成”/“不是”/“不输出”等开头，属合规免责声明，不应拦截。
# 下表为否定前缀白名单：禁止话术紧跟在这些前缀之后时放行。
# 与 spec 的口径：§7.3.6 拦截的是“断言式最终裁决”，不是“声明本报告非最终裁决”。
OUTPUT_NEGATION_PREFIXES: List[str] = [
    # 收敛到「在真实文案里直接紧贴 FORBIDDEN_OUTPUT_PHRASES 出现」的前缀。
    # 间接修饰（如 "不得输出最终合规裁决" 里的 "不得" 中间隔了 "输出"）由更近的
    # 前缀 "不输出" 救；文案不含禁话术（如 "不替代人工审查员最终判断"，"最终判断"
    # 不在禁话术列表）则根本无需豁免。新增前缀须同步：1) spec §7.3.6 白名单
    # 2) 真实文案紧贴禁话术 3) 单测 test_pre_output_language_guard_allows_each_negation_prefix。
    # 不允许预防性扩展。
    "非",            # "本报告……非最终裁决"（report_writer 报告抬头 / spec 附录 A.4）
    "不是",          # "你不是最终裁决者"（system_prompt 角色定位）
    "不构成",        # "不构成最终合规裁决"（report_writer 第 7 节限制）
    "不输出",        # "不输出最终合规裁决"（report_writer 限制 / system_prompt）
]


# 叙述节是模型自由文本，不沿用模板整稿白名单的“模板中已有固定文案”口径；
# 但扩展仍须逐词有实证、仅收否定语义副词，并通过专属 guard 留下命中审计。
# 本表就是可审计的“前缀 -> 实证触发文案”登记；不得预防性加入近义词。
NARRATIVE_OUTPUT_NEGATION_CASES: Dict[str, str] = {
    "尚未": "审查是否有任何法定调查令尚未结案",
}


# ===========================================================================
# 三、内部工具
# ===========================================================================


def _serialize(payload: Any) -> str:
    """把任意 payload 递归展平为可扫描字符串。

    对 pydantic / dict / list / 标量统一处理：pydantic 走 model_dump，
    再用 repr 兜底，确保嵌套结构里的属性名与文件路径都进入扫描文本。
    """
    if payload is None:
        return ""
    # pydantic BaseModel
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return repr(dump())
        except Exception:  # pragma: no cover - 防御性
            return repr(payload)
    return repr(payload)


def _scan_forbidden_names(text: str) -> List[str]:
    """在文本中扫描禁止 label / 属性名，返回命中清单（去白名单后）。

    spec §7.3.4：forbidden_names = AGENT_FORBIDDEN_PROPERTIES | AGENT_FORBIDDEN_LABELS。
    白名单例外（world_id / fragment_id / severity_band / applicability_state）
    不计入命中。
    """
    hits: List[str] = []
    forbidden = AGENT_FORBIDDEN_PROPERTIES | AGENT_FORBIDDEN_LABELS
    for name in sorted(forbidden):
        if name in AUDIT_WHITELIST_EXCEPTIONS:
            continue
        if name in text:
            hits.append(name)
    return hits


# ===========================================================================
# 四、hook 1 —— pre_run_input_guard（spec §7.3.2）
# ===========================================================================


def pre_run_input_guard(run_input: Dict[str, Any]) -> Dict[str, Any]:
    """创建 run 后、检索前的输入守卫（spec §7.3.2，hard）。

    检查：
    - 输入必须有 building_id / world_id；
    - 输入不得包含 W2 table path 或 forbidden property name；
    - 输入不得要求“直接给最终合规裁决”。

    入参：run_input —— 用户原始请求 dict，至少含 building_id / world_id，
        可选 raw_request / user_text 等自由文本字段。
    返回：input_guard_result dict（写入 ComplianceAssessmentRun.input_guard_result）。
    违规：缺字段抛 ValueError；blind 违规抛 SecurityError。
    """
    building_id = run_input.get("building_id")
    world_id = run_input.get("world_id")

    # 检查 1：building_id / world_id 必填
    if not building_id or not world_id:
        raise ValueError(
            "pre_run_input_guard: 输入必须同时提供非空 building_id 与 world_id"
        )

    serialized = _serialize(run_input)

    # 检查 2a：W2 table path（禁止 parquet 文件名）
    file_hits = sorted(f for f in AGENT_FORBIDDEN_FILES if f in serialized)
    # 检查 2b：forbidden property / label name
    name_hits = _scan_forbidden_names(serialized)

    if file_hits or name_hits:
        raise SecurityError(
            "forbidden_reference_truth_detected: 输入上下文出现 W2 参考真值 "
            f"table/属性 —— files={file_hits} names={name_hits}"
        )

    # 检查 3：禁止“直接给最终合规裁决”类诉求
    text_blob = " ".join(
        str(run_input.get(k, ""))
        for k in ("raw_request", "user_text", "instruction", "request")
    )
    final_verdict_markers = [
        "最终合规裁决",
        "直接给最终",
        "给出最终裁决",
        "最终裁决",
        "final compliance verdict",
        "give the final verdict",
    ]
    verdict_hits = [m for m in final_verdict_markers if m in text_blob]
    if verdict_hits:
        raise SecurityError(
            "forbidden_final_verdict_request: 输入要求直接给最终合规裁决，"
            f"baseline 只产闭包验证与辅助报告 —— 命中={verdict_hits}"
        )

    return {
        "guard": "pre_run_input_guard",
        "passed": True,
        "building_id": building_id,
        "world_id": world_id,
        "forbidden_file_hits": [],
        "forbidden_name_hits": [],
        "final_verdict_request_hits": [],
    }


# ===========================================================================
# 五、hook 2 —— pre_retrieval_query_guard（spec §7.3.3）
# ===========================================================================


def pre_retrieval_query_guard(query: str) -> Dict[str, Any]:
    """每次 KG query 前的检索查询守卫（spec §7.3.3，hard）。

    拒绝任何包含 FORBIDDEN_QUERY_PATTERNS 片段的查询（大小写不敏感）。
    注意（spec §7.3.3 末注）：`RuleThreshold` 是允许 label；`ThresholdEval`
    是禁止 label —— 正则只匹配 `ThresholdEval`，不会误伤 `RuleThreshold`。

    入参：query —— 即将下发的 Cypher / 检索查询字符串。
    返回：通过时的 guard dict。
    违规：命中禁止片段抛 SecurityError。
    """
    if not isinstance(query, str):
        raise ValueError("pre_retrieval_query_guard: query 必须是字符串")

    matches = sorted({m.group(0) for m in _FORBIDDEN_QUERY_RE.finditer(query)})
    if matches:
        raise SecurityError(
            "forbidden_reference_truth_detected: 检索查询命中 W2 / evaluator "
            f"禁止片段 —— {matches}"
        )

    return {
        "guard": "pre_retrieval_query_guard",
        "passed": True,
        "matched_forbidden_fragments": [],
    }


# ===========================================================================
# 六、hook 3 —— post_retrieval_source_audit（spec §7.3.4）
# ===========================================================================


def post_retrieval_source_audit(
    fact_pack: Any,
    rule_slice: Any,
) -> Dict[str, Any]:
    """FactPack / RuleSlice 构造后的来源审计（spec §7.3.4，hard）。

    spec §7.3.4 伪代码：
        forbidden_names = AGENT_FORBIDDEN_PROPERTIES | AGENT_FORBIDDEN_LABELS
        if any(name in serialized_payload for name in forbidden_names):
            raise SecurityError("forbidden_reference_truth_detected")

    白名单例外：world_id / fragment_id / severity_band 作为 W0 事实字段允许；
    applicability_state 作为 verifier-owned 字段允许（但不得来自 W2，
    此处只能做名称级审计，来源级隔离由灌库守卫负责）。

    入参：fact_pack —— FactPack；rule_slice —— RuleSlice。
    返回：audit dict（含 forbidden_sources_loaded，供 run_audit 记录）。
    违规：检出禁止名称抛 SecurityError。
    """
    serialized = _serialize(fact_pack) + "\n" + _serialize(rule_slice)

    name_hits = _scan_forbidden_names(serialized)
    file_hits = sorted(f for f in AGENT_FORBIDDEN_FILES if f in serialized)

    if name_hits or file_hits:
        raise SecurityError(
            "forbidden_reference_truth_detected: FactPack/RuleSlice 含 W2 "
            f"参考真值字段/文件 —— names={name_hits} files={file_hits}"
        )

    return {
        "guard": "post_retrieval_source_audit",
        "passed": True,
        "forbidden_sources_loaded": [],
        "forbidden_name_hits": [],
        "forbidden_file_hits": [],
    }


# ===========================================================================
# 七、hook 4 —— post_verifier_stop_gate（spec §7.3.5）
# ===========================================================================


def post_verifier_stop_gate(closure_result: Any) -> Dict[str, Any]:
    """verifier 返回后的停机门（spec §7.3.5，hard）。

    spec §7.3.5 伪代码：
        if not closure_result.allow_stop:
            force_template("incomplete_closure_notice")
        else:
            allow_template("auxiliary_review_report")

    LLM 不能覆盖 allow_stop —— 模板由本 hook 按 verifier 的 allow_stop 锁定。

    入参：closure_result —— ClosureValidationResult。
    返回：gate dict，含 forced_template / allow_full_report，供编排器选模板。
    """
    allow_stop = bool(getattr(closure_result, "allow_stop", False))

    if not allow_stop:
        forced_template = "incomplete_closure_notice"
        allow_full_report = False
    else:
        forced_template = "auxiliary_review_report"
        allow_full_report = True

    return {
        "guard": "post_verifier_stop_gate",
        "passed": True,
        "allow_stop": allow_stop,
        "forced_template": forced_template,
        "allow_full_report": allow_full_report,
    }


# ===========================================================================
# 八、hook 5 —— pre_output_language_guard（spec §7.3.6）
# ===========================================================================


def _is_negated_occurrence(
    text: str,
    phrase: str,
    pos: int,
    negation_prefixes: List[str],
) -> bool:
    """判断 text[pos:] 处的禁止话术是否处于否定语境（合规免责声明）。

    spec 附录 A.4 允许“非最终裁决 / 不构成最终合规裁决”等否定式声明；
    若紧挨禁止话术之前的文本以 negation_prefixes 中任一前缀结尾，
    判为否定语境，放行。
    """
    head = text[:pos]
    return any(head.endswith(prefix) for prefix in negation_prefixes)


def pre_output_language_guard(
    output_text: str,
    *,
    narrative_context: bool = False,
) -> Dict[str, Any]:
    """LLM 输出前的语言守卫（spec §7.3.6，hard）。

    禁止话术（spec §7.3.6 / 附录 A.4）：最终裁决 / 最终合规 / 最终不合规 /
    结案 / 本建筑已合规 / 本建筑不合规 / according to expected_verdict 等。
    若以断言形式出现，输出阻断并要求重写。

    否定式免责声明放行：spec 附录 A.4 把“本报告…非最终裁决”列为允许替代
    表述，§7.2.4 / 附录 C 强制的报告标题也含“（非最终裁决）”。因此禁止话术
    若紧跟“非 / 不构成 / 不输出”等否定前缀，属合规声明，不拦截
    （决策点见交付报告 D-3）。

    入参：output_text —— LLM 即将输出的报告/说明文本。
    返回：通过时的 guard dict。
    违规：命中断言式禁止话术抛 OutputGuardError。
    """
    if not isinstance(output_text, str):
        raise ValueError("pre_output_language_guard: output_text 必须是字符串")

    negation_prefixes = list(OUTPUT_NEGATION_PREFIXES)
    if narrative_context:
        negation_prefixes.extend(NARRATIVE_OUTPUT_NEGATION_CASES)

    # 按 Markdown 渲染后的连续文字扫描：强调符/行内代码定界符不应能把
    # 「最终**裁决**」一类禁话术拆开。HTML 注释不渲染，先剥除。
    scan_text = re.sub(r"<!--[\s\S]*?-->", "", output_text).translate(
        str.maketrans("", "", "*_`")
    )

    asserted_hits: List[str] = []
    negated_exemptions: List[Dict[str, str]] = []
    for phrase in FORBIDDEN_OUTPUT_PHRASES:
        scan_phrase = phrase.translate(str.maketrans("", "", "*_`"))
        start = 0
        while True:
            pos = scan_text.find(scan_phrase, start)
            if pos < 0:
                break
            exempt_prefix = None
            head = scan_text[:pos]
            for prefix in negation_prefixes:
                if not head.endswith(prefix):
                    continue
                if prefix in NARRATIVE_OUTPUT_NEGATION_CASES:
                    # 叙述节专属前缀防双重否定滑坡：「不是/并非/不/非 + 尚未」
                    # 语义反转为肯定断言（"并非尚未结案"=已结案），不得豁免。
                    before = head[: -len(prefix)]
                    if before.endswith(("不是", "并非")) or before.endswith(
                        ("不", "非")
                    ):
                        continue
                exempt_prefix = prefix
                break
            if exempt_prefix is None:
                asserted_hits.append(phrase)
                break  # 同一话术命中一次即足够
            if narrative_context and exempt_prefix in NARRATIVE_OUTPUT_NEGATION_CASES:
                negated_exemptions.append(
                    {"phrase": phrase, "prefix": exempt_prefix}
                )
            start = pos + len(scan_phrase)

    if asserted_hits:
        raise OutputGuardError(
            "output_blocked_forbidden_phrase: 输出含断言式禁止话术，必须重写 —— "
            f"{asserted_hits}。允许替代表述见 spec 附录 A.4"
            "（如“疑似未满足，建议人工复核”“本报告…非最终裁决”）。"
        )

    result: Dict[str, Any] = {
        "guard": "pre_output_language_guard",
        "passed": True,
        "matched_forbidden_phrases": [],
    }
    if narrative_context:
        # 仅叙述节语境返回豁免审计字段；默认模板路径审计形状保持不变
        # （复审发现：无条件加字段会改变确定性档 run_audit 的字节形状）。
        result["negated_forbidden_phrase_exemptions"] = negated_exemptions
    return result


# ===========================================================================
# 九、evo v1 hook 公共禁止集合（spec v1 §2.3 + §7.4 + Appendix A）
# ===========================================================================

# spec v1 §2.3.1 + Appendix A.1：v1 在 v0.4 基础上新增的禁止 labels
EVO_FORBIDDEN_LABELS = AGENT_FORBIDDEN_LABELS | frozenset(
    {
        "EvalTruthReport",
        "RawEvalTruth",
        "W2Truth",
        "W2BasisItem",
        "W2ThresholdTruth",
        "ExpectedOutcome",
        "ReferenceVerdict",
        "ProjectionAnswer",
        "RawFeedback",
        "PerRunConfusion",
    }
)

# spec v1 §2.3.1 + Appendix A.2：v1 在 v0.4 基础上新增的禁止 properties
EVO_FORBIDDEN_PROPERTIES = AGENT_FORBIDDEN_PROPERTIES | frozenset(
    {
        "truth_label",
        "expected_label",
        "reference_outcome",
        "w2_basis_ref",
        "basis_item_id",
        "projection_cell_id",
        "per_run_confusion",
        "raw_metric_by_run",
        "w2_threshold_truth",
        "w2_observed_value",
        "w2_expected_operator",
        "feedback_truth_comment",
        "leaked_expected_verdict",
        "raw_eval_truth",
        "raw_w2_metric",
    }
)

# spec v1 §2.3.2 SkillPackage 禁止字段（任何 skill 包文件不得出现）
SKILL_PACKAGE_FORBIDDEN_TOKENS = frozenset(
    {
        "expected_verdict",
        "NormativeProjection",
        "basis_items",
        "projection_id",
        "EvalTruthReport",
        "truth_label",
        "force allow_stop",
        "override verifier",
        "final decision",
        "force_allow_stop",
        "override_verifier",
    }
)

# spec v1 §2.3.3 EvoPolicy 禁止字段
POLICY_FORBIDDEN_TOKENS = frozenset(
    {
        "rule_exclusion_list",
        "verifier_override",
        "allow_stop_policy",
        "satisfaction_status_override",
        "expected_verdict_weight",
        "truth_label_weight",
        "per_building_reward",
        "per_run_w2_label",
    }
)

# spec v1 §2.3.4 SanitizedFeedbackPacket 禁止字段
FEEDBACK_FORBIDDEN_TOKENS = frozenset(
    {
        "run_id_list",
        "building_id_list",
        "world_id_list",
        "expected_verdict",
        "basis_item",
        "projection_id",
        "raw_confusion_matrix",
        "free_text_evaluator_comment",
        "feedback_truth_comment",
        "evaluator_note",
    }
)

# spec v1 §9.4.1 Gate 0：必须出现在 forbidden_actions 的 5 个 hard 项
SKILL_REQUIRED_FORBIDDEN_ACTIONS = frozenset(
    {
        "override_verifier",
        "force_allow_stop",
        "emit_final_verdict",
        "read_evaluator_truth",
        "suppress_rule_candidate",
    }
)

# spec v1 §7.3.2 Layer 1 OperationalSkills 允许的 kind 枚举
SKILL_ALLOWED_KINDS = frozenset(
    {"micro_routing", "retrieval_macro", "report_structure", "diagnostic_hint"}
)

# spec v1 §10.7 Skill naming 禁词（verdict 类结果词不可出现在 skill_id）
SKILL_ID_FORBIDDEN_WORDS = frozenset(
    {"verdict", "pass", "fail", "satisfied", "violated"}
)

# spec v1 §10.7 不得含建筑 / 运行实例 literal 的子串模式
SKILL_ID_FORBIDDEN_LITERAL_PATTERNS: List[str] = [
    r"\bB-\d+",          # building_id 形态 B-XXXXXX
    r"\bCAR-\d+",        # run_id 形态 CAR-...
    r"\bW-\d+",          # world_id 形态 W-...
    r"\bERT-\d+",        # trace_id 形态
]
_SKILL_ID_LITERAL_RE = re.compile(
    "|".join(f"(?:{p})" for p in SKILL_ID_FORBIDDEN_LITERAL_PATTERNS)
)

# spec v1 §6.5 / §6.3 verifier authority 字段：Policy / Skill 不得携带这些 key
VERIFIER_AUTHORITY_FIELDS = frozenset(
    {
        "allow_stop_policy",
        "allow_stop_override",
        "closure_status_override",
        "satisfaction_status_override",
        "verifier_override",
        "force_allow_stop",
    }
)


# spec §7.4.1 + §10.8：SKILL.md 标准免责声明的否定前缀，紧贴禁词出现时不算违规。
_SKILL_TOKEN_NEGATION_PREFIXES: List[str] = [
    "does not ",
    "do not ",
    "not ",
    "non-",
    "non ",
    "without ",
    "cannot ",
    "must not ",
    "shall not ",
    "is not ",
    "are not ",
    "non-authoritative",
    "non authoritative",
    "不构成",
    "不输出",
    "非",
]


def _strip_negated_phrases(text: str, tokens: frozenset) -> str:
    """对 text 内每个 token 出现，若前置 24 字符以否定前缀结尾，则把该次出现替换为空格。

    用于 SKILL_PACKAGE_FORBIDDEN_TOKENS 等需要 negation context exemption 的扫描。
    label / property 类禁词（NormativeProjection / expected_verdict / ...）不应
    用这个 helper —— 它们是结构化字段名，不存在 negation 上下文。
    """
    if not text or not tokens:
        return text
    low = text.lower()
    out_parts: List[str] = []
    cursor = 0
    while cursor < len(text):
        # 找下一个最近的 token 出现位置
        next_pos = -1
        next_token = ""
        for tok in tokens:
            if not tok:
                continue
            tok_low = tok.lower()
            p = low.find(tok_low, cursor)
            if p < 0:
                continue
            if next_pos < 0 or p < next_pos:
                next_pos = p
                next_token = tok
        if next_pos < 0:
            out_parts.append(text[cursor:])
            break
        # 检查否定前缀
        head = low[max(0, next_pos - 24) : next_pos]
        negated = any(head.endswith(pref) for pref in _SKILL_TOKEN_NEGATION_PREFIXES)
        out_parts.append(text[cursor:next_pos])
        if negated:
            out_parts.append(" " * len(next_token))  # 占位空格
        else:
            out_parts.append(text[next_pos : next_pos + len(next_token)])
        cursor = next_pos + len(next_token)
    return "".join(out_parts)


def _strip_action_lists_for_scan(pkg: Any) -> Any:
    """复制 candidate_pkg 抠掉 spec §9.4.1 强制声明字段，避免禁词扫描误命中。

    spec §9.4.1 Gate 0 要求 `forbidden_actions` 列表必须显式含 'override_verifier'
    / 'force_allow_stop' 等字符串作为"声明不会做"，这些字符串本身也在 SKILL_PACKAGE_
    FORBIDDEN_TOKENS 内（防 LLM 在其它位置自描述要做这件事）。扫描前从 dict 抠掉
    `forbidden_actions` / `allowed_tools` 这两个白名单字段。
    """
    if isinstance(pkg, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in pkg.items():
            if k in {"forbidden_actions", "allowed_tools"}:
                # skip：声明清单不参与扫描
                continue
            cleaned[k] = _strip_action_lists_for_scan(v)
        return cleaned
    if isinstance(pkg, list):
        return [_strip_action_lists_for_scan(item) for item in pkg]
    return pkg


def _scan_text_tokens(text: str, tokens: frozenset) -> List[str]:
    """在大写敏感串里扫描 token；区分大小写以匹配 spec 列出的命名。"""
    hits: List[str] = []
    for tok in sorted(tokens):
        if tok and tok in text:
            hits.append(tok)
    return hits


def _scan_dict_tree_for_keys(obj: Any, forbidden: frozenset) -> List[str]:
    """递归扫 dict/list 树的 key 是否落入 forbidden 集合。"""
    hits: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k in forbidden:
                hits.append(k)
            hits.extend(_scan_dict_tree_for_keys(v, forbidden))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            hits.extend(_scan_dict_tree_for_keys(item, forbidden))
    return hits


# ===========================================================================
# 十、evo hook 1 —— pre_skill_candidate_guard（spec v1 §7.4.1 + §9.4.1 Gate 0）
# ===========================================================================


def pre_skill_candidate_guard(candidate_pkg: Dict[str, Any]) -> Dict[str, Any]:
    """LLM/trainer 起草 SkillPackage 后、写入 candidate store 前的静态安全门。

    spec v1 §7.4.1 + §9.4.1 Gate 0：package 全文件 forbidden scan / 禁 W2 /
    禁 verdict-like phrase / 禁 verifier override / kind 在允许枚举 /
    SKILL.md 含 non-authority statement / forbidden_actions 含 5 hard 项 /
    skill_id 不含 building/world/run literal。

    入参：candidate_pkg —— EvoSkillPackage 序列化 dict 或含 skill / files /
        skill_md_text 等字段的 candidate 包。
    返回：guard 结果 dict。
    违规：抛 SecurityError。
    """
    violations: List[str] = []

    skill = candidate_pkg.get("skill") if isinstance(candidate_pkg, dict) else None
    if not isinstance(skill, dict):
        skill = candidate_pkg if isinstance(candidate_pkg, dict) else {}

    # 1) kind 必须在 v1 四类
    kind = skill.get("kind")
    if kind not in SKILL_ALLOWED_KINDS:
        violations.append(
            f"kind={kind!r} 不在 v1 允许枚举 {sorted(SKILL_ALLOWED_KINDS)}"
        )

    # 2) layer 必须为 L1_operational（Layer 0 是 core seed，不走 candidate gate；
    #    Layer 2 spec v1 §7.3.3 不允许 runtime active）
    layer = skill.get("layer")
    if layer not in {"L1_operational"}:
        violations.append(
            f"layer={layer!r} 必须是 L1_operational（L0 core 不走候选门；L2 禁加载）"
        )

    # 3) forbidden_actions 必须含 5 hard 项
    forbidden_actions = set(skill.get("forbidden_actions") or [])
    missing_actions = SKILL_REQUIRED_FORBIDDEN_ACTIONS - forbidden_actions
    if missing_actions:
        violations.append(
            "forbidden_actions 缺 hard 项: " + ",".join(sorted(missing_actions))
        )

    # 4) skill_id 禁含 building/world/run literal + verdict 类结果词
    skill_id = str(skill.get("skill_id") or "")
    if _SKILL_ID_LITERAL_RE.search(skill_id):
        violations.append(f"skill_id={skill_id!r} 含建筑/运行实例 literal")
    skill_id_low = skill_id.lower()
    bad_words = [w for w in SKILL_ID_FORBIDDEN_WORDS if w in skill_id_low]
    if bad_words:
        violations.append(f"skill_id={skill_id!r} 含 verdict 类结果词 {bad_words}")

    # 5) 全 package 序列化扫 W2 forbidden labels/properties + SkillPackage 禁词
    #    forbidden_actions 列表里 spec §9.4.1 强制要求出现 override_verifier /
    #    force_allow_stop 等字符串作为"声明禁止"的项，不应被禁词扫描误命中。
    #    做法：序列化时把 skill.forbidden_actions / skill.allowed_tools / 顶层
    #    similar 白名单字段抠掉再扫。
    pkg_sanitized = _strip_action_lists_for_scan(candidate_pkg)
    serialized = _serialize(pkg_sanitized)
    # SKILL.md 标准免责声明（spec §7.4.1）："does not override verifier" 等否定式
    # 不算违规。对 SKILL_PACKAGE_FORBIDDEN_TOKENS 在扫描前剔除 negated 上下文。
    skill_md_blob = (
        candidate_pkg.get("skill_md_text")
        or candidate_pkg.get("skill_md")
        or ""
    )
    skill_md_blob = str(skill_md_blob)
    serialized_for_skill_tokens = _strip_negated_phrases(
        serialized, SKILL_PACKAGE_FORBIDDEN_TOKENS
    )
    # SKILL.md 单独再剥一次（确保 markdown 文本里 negated 声明被剥）
    # 注意：serialized 里 skill_md_text 内容已包含；额外 strip 不会破坏其它字段。
    label_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_LABELS)
    prop_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_PROPERTIES)
    skill_token_hits = _scan_text_tokens(
        serialized_for_skill_tokens, SKILL_PACKAGE_FORBIDDEN_TOKENS
    )
    file_hits = sorted(f for f in AGENT_FORBIDDEN_FILES if f in serialized)
    if label_hits or prop_hits or skill_token_hits or file_hits:
        violations.append(
            "package 含 W2/skill 禁字段: "
            f"labels={label_hits} props={prop_hits} skill_tokens={skill_token_hits} files={file_hits}"
        )

    # 6) SKILL.md 必须含 non-authority statement（spec v1 §10.8）
    skill_md = candidate_pkg.get("skill_md_text") or candidate_pkg.get("skill_md") or ""
    if not isinstance(skill_md, str):
        skill_md = str(skill_md)
    non_auth_markers = [
        "non-authoritative",
        "cannot decide compliance",
        "does not override",
        "not authoritative",
        "non-authority",
        "不构成最终",
        "非最终裁决",
        "非权威",
    ]
    has_non_auth = any(m in skill_md for m in non_auth_markers) or any(
        m in str(skill.get("non_authority_statement") or "")
        for m in ["non-authoritative", "not authoritative", "非权威", "非最终"]
    )
    if skill_md and not has_non_auth:
        violations.append("SKILL.md 缺 non-authority statement（spec v1 §10.8）")

    # 7) verdict-like / verifier override phrase 扫描
    verdict_phrases = [
        "force allow_stop",
        "override verifier",
        "override the verifier",
        "final verdict",
        "expected_verdict",
        "最终裁决",
    ]
    serialized_low = serialized.lower()
    verdict_hits = [p for p in verdict_phrases if p.lower() in serialized_low]
    # SKILL.md 里可能合法引用 "does not override verifier" 等否定式 → 已 hit list 里
    # 移除被「does not / not / 非 / 不」前缀化的项；用粗糙但确定的逻辑
    filtered_hits: List[str] = []
    for phrase in verdict_hits:
        idx = 0
        ok = True
        while True:
            pos = serialized_low.find(phrase.lower(), idx)
            if pos < 0:
                break
            head = serialized_low[max(0, pos - 24) : pos]
            negated = any(
                neg in head
                for neg in ("does not", "not ", "non-", "non ", "非 ", "非", "不构成", "不输出", "do not")
            )
            if not negated:
                ok = False
                break
            idx = pos + len(phrase)
        if not ok:
            filtered_hits.append(phrase)
    if filtered_hits:
        violations.append(f"verdict-like / verifier-override phrase 命中: {filtered_hits}")

    if violations:
        raise SecurityError(
            "pre_skill_candidate_guard 拒绝 SkillPackage 候选: " + " | ".join(violations)
        )

    return {
        "guard": "pre_skill_candidate_guard",
        "passed": True,
        "violations": [],
    }


# ===========================================================================
# 十一、evo hook 2 —— post_skill_validation_audit（spec v1 §7.4.2 + §9.4.6）
# ===========================================================================


# spec v1 §9.4.6：metric_delta_bucket 必须是 0.05 网格的 +/- 字符串（如 +0.05 / -0.10）
_METRIC_BUCKET_RE = re.compile(r"^[+-]?\d+(?:\.\d{1,2})?$")


def post_skill_validation_audit(
    validation_record: Dict[str, Any],
) -> Dict[str, Any]:
    """Gate 2-4 replay/holdout 完成后核验单条 SkillValidationRecord。

    spec v1 §7.4.2：Gate 0-4 均存在 / closure regression count=0 / leakage hits=[]
    / stability K=5 / holdout pass / 自由文本无 W2 泄漏 / metric bucket 不含
    per-run truth（必须落 0.05 粒度网格 或 low/medium/high 枚举）。

    入参：validation_record —— SkillValidationRecord 序列化 dict。
    返回：guard 结果 dict。
    违规：抛 OutputGuardError。
    """
    violations: List[str] = []

    if not isinstance(validation_record, dict):
        raise OutputGuardError(
            "post_skill_validation_audit: validation_record 必须是 dict"
        )

    stage = validation_record.get("validation_stage")
    valid_stages = {
        "gate0_static",
        "gate1_schema_provenance",
        "gate2_replay_ab",
        "gate3_stability",
        "gate4_holdout_counterfactual",
        "release_gate",
    }
    if stage not in valid_stages:
        violations.append(f"validation_stage={stage!r} 不在 5 Gate 枚举")

    # leakage hits = []
    leakage = validation_record.get("leakage_hits") or []
    if leakage:
        violations.append(f"leakage_hits 非空: {leakage[:5]}")

    # closure regression count = 0
    closure_reg = validation_record.get("closure_regression_count")
    if closure_reg not in (None, 0):
        violations.append(f"closure_regression_count={closure_reg} 不为 0")

    # allow_stop_authority_check 必须 True
    if validation_record.get("allow_stop_authority_check") is False:
        violations.append("allow_stop_authority_check=False 表示 Skill 影响了 verifier 权威")

    # metric bucket 粒度审计（spec v1 §9.4.6）
    delta = validation_record.get("metric_delta_bucket")
    if delta is not None:
        if not isinstance(delta, str) or not _METRIC_BUCKET_RE.match(delta.strip()):
            violations.append(
                f"metric_delta_bucket={delta!r} 不符 0.05 粒度网格"
            )
        else:
            # 数值粒度：必须是 0.05 的整数倍
            try:
                v = float(delta)
                # 整数倍判断容忍 1e-9
                if abs(round(v / 0.05) * 0.05 - v) > 1e-6:
                    violations.append(
                        f"metric_delta_bucket={delta!r} 不是 0.05 整数倍"
                    )
            except (TypeError, ValueError):
                violations.append(f"metric_delta_bucket={delta!r} 不可解析为数")

    metric_value = validation_record.get("metric_value_bucket")
    if metric_value is not None:
        # 允许 0.05 网格 或 low/medium/high 枚举
        ok_enum = isinstance(metric_value, str) and metric_value.strip().lower() in {
            "low",
            "medium",
            "high",
        }
        ok_num = isinstance(metric_value, str) and _METRIC_BUCKET_RE.match(
            metric_value.strip()
        )
        if not (ok_enum or ok_num):
            violations.append(
                f"metric_value_bucket={metric_value!r} 不在 low/medium/high 或 0.05 网格"
            )

    # 自由文本字段：禁出现 W2 关键词；只允许 failure_reasons 这种受限 list[str]
    serialized = _serialize(validation_record)
    label_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_LABELS)
    prop_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_PROPERTIES)
    if label_hits or prop_hits:
        violations.append(
            f"validation_record 含 W2 字段: labels={label_hits} props={prop_hits}"
        )

    # spec v1 §8.4：禁含 free text evaluator note / evaluator comment 类字段
    forbidden_note_keys = {
        "notes",
        "evaluator_comment",
        "free_text_evaluator_comment",
        "feedback_truth_comment",
    }
    if isinstance(validation_record, dict):
        note_hits = [k for k in forbidden_note_keys if k in validation_record]
        if note_hits:
            violations.append(f"validation_record 含禁字段 {note_hits}")

    if violations:
        raise OutputGuardError(
            "post_skill_validation_audit 拒绝: " + " | ".join(violations)
        )

    return {
        "guard": "post_skill_validation_audit",
        "passed": True,
        "violations": [],
    }


# ===========================================================================
# 十二、evo hook 3 —— pre_skill_runtime_load_guard（spec v1 §7.4.3）
# ===========================================================================


def pre_skill_runtime_load_guard(
    skill_pkg: Dict[str, Any],
    current_kg_snapshot_id: str,
    current_rulecard_bundle_id: str,
) -> Dict[str, Any]:
    """runtime 加载 SkillSet 前的硬门（spec v1 §7.4.3）。

    检查：status in {core, active} / staleness_status='fresh' /
    package hash 与记录一致 / rulecard bundle 与 KG snapshot 匹配 /
    Layer 2 不可加载 / forbidden_actions 完整。

    入参：
    - skill_pkg：SkillPackage 序列化 dict 或 SkillJson；
    - current_kg_snapshot_id / current_rulecard_bundle_id：当前 runtime 环境。
    返回：guard 结果 dict。
    违规：抛 SecurityError。
    """
    violations: List[str] = []

    skill = skill_pkg.get("skill") if isinstance(skill_pkg, dict) else None
    if not isinstance(skill, dict):
        skill = skill_pkg if isinstance(skill_pkg, dict) else {}

    status = skill.get("status")
    layer = skill.get("layer")

    # Codex review 2026-05-27 A3[P3]：按 layer 区分允许的 status：
    # - L0_core：spec §7.3.1 固定 4 个 system 内置 skill，永远 "core" 或 "active"
    # - L1_operational：spec §10.6 v1.1 3 态 draft/active/retired，runtime 只允许 "active"
    # - L2_meta_disabled：spec §7.3.3 v1 production 不可加载（所有 status 都拒）
    # 原实现允许任何 layer 走 {"core","active"}，但 L1 SkillJson schema 不允许 "core"，
    # 容易让 L1 错误状态 leak 进 runtime
    if layer == "L0_core":
        if status not in {"core", "active"}:
            violations.append(
                f"L0 CoreSkill status={status!r} 不可 runtime 加载（只允许 core/active）"
            )
    elif layer == "L1_operational":
        if status != "active":
            violations.append(
                f"L1 OperationalSkill status={status!r} 不可 runtime 加载（只允许 active；"
                f"draft 须先过 Gate 0-4 + leakage audit promote）"
            )
    elif layer == "L2_meta_disabled":
        violations.append("Layer 2 MetaSkills 在 v1 production 不可加载（spec §7.3.3）")
    else:
        violations.append(
            f"layer={layer!r} 未知，不可 runtime 加载（允许 L0_core / L1_operational）"
        )

    staleness = (
        skill_pkg.get("staleness_status")
        if isinstance(skill_pkg, dict)
        else None
    ) or skill.get("staleness_status")
    if staleness and staleness != "fresh":
        violations.append(f"staleness_status={staleness!r} 非 fresh")

    # KG snapshot / bundle 与 runtime 必须一致
    skill_snapshot = skill.get("kg_snapshot_id")
    if (
        skill_snapshot
        and current_kg_snapshot_id
        and skill_snapshot != current_kg_snapshot_id
    ):
        violations.append(
            f"kg_snapshot_id mismatch: skill={skill_snapshot!r} runtime={current_kg_snapshot_id!r}"
        )

    skill_bundle = skill.get("rulecard_bundle_id")
    if (
        skill_bundle
        and current_rulecard_bundle_id
        and skill_bundle != current_rulecard_bundle_id
    ):
        violations.append(
            f"rulecard_bundle_id mismatch: skill={skill_bundle!r} runtime={current_rulecard_bundle_id!r}"
        )

    # forbidden_actions 完整性（spec §9.4.1）
    forbidden_actions = set(skill.get("forbidden_actions") or [])
    missing_actions = SKILL_REQUIRED_FORBIDDEN_ACTIONS - forbidden_actions
    if missing_actions:
        violations.append(
            "runtime-loadable Skill forbidden_actions 缺 hard 项: "
            + ",".join(sorted(missing_actions))
        )

    if violations:
        raise SecurityError(
            "pre_skill_runtime_load_guard 拒绝加载: " + " | ".join(violations)
        )

    return {
        "guard": "pre_skill_runtime_load_guard",
        "passed": True,
        "violations": [],
    }


# ===========================================================================
# 十三、evo hook 4 —— pre_feedback_ingest_guard（spec v1 §7.4.4 + §8.4 / §8.5）
# ===========================================================================


def pre_feedback_ingest_guard(packet: Dict[str, Any]) -> Dict[str, Any]:
    """SanitizedFeedbackPacket 写入 EvoMemoryStore 前的硬门。

    spec v1 §7.4.4 + §8.4 + §8.5：
    - run_count >= 10；
    - 每个 unsuppressed cell building_count >= 3 / run_count >= 10；
    - rounding_policy in {nearest_0.05, bucket_low_medium_high}；
    - 不含 run_id/building_id/world_id 明细；
    - forbidden_scan_passed = true；
    - reconstruction_audit_passed = true。

    **v1.1 修订（spec §0.6 修订 2 + §3.6.5 + §8.6）**：原 ``release_delay_window_count
    >= 1`` 检查已删除（实验室阶段 broker 角色降级为 runtime trend feedback 接口，
    无 production traffic 防 leak 节奏需求；§8.6 整段删）。字段保留 Optional
    供 caller 在真启用 runtime trend feedback 接口时填非零；guard 不再硬约束。

    入参：packet —— SanitizedFeedbackPacket 序列化 dict。
    返回：guard 结果 dict。
    违规：抛 SecurityError。
    """
    violations: List[str] = []

    if not isinstance(packet, dict):
        raise SecurityError(
            "pre_feedback_ingest_guard: packet 必须是 dict（SanitizedFeedbackPacket）"
        )

    run_count = packet.get("run_count")
    if not isinstance(run_count, int) or run_count < 10:
        violations.append(f"run_count={run_count} <10（k-anonymity 不满足）")

    building_count = packet.get("building_count")
    if not isinstance(building_count, int) or building_count < 3:
        violations.append(f"building_count={building_count} <3（k-anonymity 不满足）")

    rounding = packet.get("rounding_policy")
    if rounding not in {"nearest_0.05", "bucket_low_medium_high"}:
        violations.append(f"rounding_policy={rounding!r} 非合法枚举")

    # v1.1 §0.6 修订 2 + §3.6.5 + §8.6：release_delay_window_count 不再硬约束
    # （broker 角色降级为 runtime trend feedback 接口；实验室阶段无延迟发布需求）；
    # 字段保留 Optional 供 caller 在真启用 runtime trend feedback 接口时填非零

    if packet.get("forbidden_scan_passed") is not True:
        violations.append("forbidden_scan_passed!=True")
    if packet.get("k_anonymity_passed") is not True:
        violations.append("k_anonymity_passed!=True")
    # Codex review 2026-05-27 B2[P2] + spec §0.6 修订 1 + §11.9：v1.1 reconstruction
    # audit 焦点已从 packet 端搬到 artifact 端（candidate SkillPackage / EvoPolicyVersion
    # 是真危险路径，packet 不是）。原 hard 门 reconstruction_audit_passed=True 已
    # 不合 v1.1 语义。packet ingest 改为只校验静态 forbidden / k-anonymity / 文本扫；
    # artifact promotion 阶段（pre_policy_publish_guard / pre_skill_runtime_load_guard）
    # 才要求 §11.9 artifact-端 audit pass。
    # 字段 reconstruction_audit_passed 在 DTO 中保留 backward-compat / 调试用，
    # 但 packet 默认值 False 不再阻挡 ingest。

    # cells 校验
    cells = packet.get("cells") or []
    if isinstance(cells, list):
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                continue
            if cell.get("suppressed"):
                # suppressed cell 不要求最小 count（spec §8.5 / §3.6.5）
                continue
            cc_rc = cell.get("run_count")
            cc_bc = cell.get("building_count")
            if not isinstance(cc_rc, int) or cc_rc < 10:
                violations.append(
                    f"cells[{i}] unsuppressed run_count={cc_rc} <10"
                )
            if not isinstance(cc_bc, int) or cc_bc < 3:
                violations.append(
                    f"cells[{i}] unsuppressed building_count={cc_bc} <3"
                )

    # 禁含 run_id / building_id / world_id 明细 + 自由文本
    serialized = _serialize(packet)
    feedback_token_hits = _scan_text_tokens(serialized, FEEDBACK_FORBIDDEN_TOKENS)
    label_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_LABELS)
    prop_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_PROPERTIES)
    if feedback_token_hits or label_hits or prop_hits:
        violations.append(
            f"packet 含禁 token: feedback={feedback_token_hits} "
            f"labels={label_hits} props={prop_hits}"
        )

    # 扫 packet 内出现的具体 id literal 样式（B-… / W-… / CAR-…）
    id_literal_pattern = re.compile(r"\b(?:B-|W-|CAR-|ERT-)\w+")
    id_hits = sorted(set(id_literal_pattern.findall(serialized)))
    if id_hits:
        violations.append(
            f"packet 含具体 id literal（应只用 hash/聚合）: {id_hits[:5]}"
        )

    if violations:
        raise SecurityError(
            "pre_feedback_ingest_guard 拒绝: " + " | ".join(violations)
        )

    return {
        "guard": "pre_feedback_ingest_guard",
        "passed": True,
        "violations": [],
    }


# ===========================================================================
# 十四、evo hook 5 —— pre_policy_publish_guard（spec v1 §7.4.5 + §2.3.3）
# ===========================================================================


def pre_policy_publish_guard(policy: Dict[str, Any]) -> Dict[str, Any]:
    """EvoPolicyVersion 发布 active 前的硬门（spec v1 §7.4.5）。

    检查：
    - candidate_cutoff_policy.verifier_floor='all_score_positive_not_deterministically_excluded'；
    - 不含 allow_stop_policy / verifier_override 等禁字段；
    - ranking_weights 在 [-2.0, 2.0]；
    - candidate_cutoff_policy 中 context_top_k 不破坏 verifier floor。

    入参：policy —— EvoPolicyVersion 序列化 dict。
    返回：guard 结果 dict。
    违规：抛 SecurityError。

    **v1.1 修订（spec §0.6 修订 2 + §3.6.4 + §9.9）**：原 "rollback ref 字段
    存在（``rollback_condition`` 非空）" 检查已删除——v1.1 实验室阶段无 canary /
    rollback artifact 概念，``rollback_condition`` 字段从 EvoPolicyVersion 移除，
    回滚靠 git revert 代替；按 §0.6.1 全局映射规则，原 "staged" 中间态合进
    "active"，hook 角色定位为 "publish to active 前的硬门"。
    """
    violations: List[str] = []

    if not isinstance(policy, dict):
        raise SecurityError(
            "pre_policy_publish_guard: policy 必须是 dict（EvoPolicyVersion）"
        )

    # 1) candidate_cutoff_policy 必须含 verifier_floor 且为约束串
    cutoff = policy.get("candidate_cutoff_policy") or {}
    if not isinstance(cutoff, dict):
        violations.append("candidate_cutoff_policy 必须是 dict")
    else:
        floor = cutoff.get("verifier_floor")
        if floor != "all_score_positive_not_deterministically_excluded":
            violations.append(
                "candidate_cutoff_policy.verifier_floor 必须 = "
                "'all_score_positive_not_deterministically_excluded'，"
                f"当前={floor!r}"
            )

    # 2) 顶层不得含 allow_stop_policy / 其它禁字段
    forbidden_top_hits = [k for k in policy.keys() if k in POLICY_FORBIDDEN_TOKENS]
    if forbidden_top_hits:
        violations.append(f"policy 顶层含禁字段: {forbidden_top_hits}")

    # 3) 递归扫整个 policy 树有没有 verifier authority 字段（嵌套在 sub-dict 也算）
    auth_hits = _scan_dict_tree_for_keys(policy, VERIFIER_AUTHORITY_FIELDS)
    if auth_hits:
        violations.append(f"policy 含 verifier authority 字段: {sorted(set(auth_hits))}")

    # 4) ranking_weights 在 [-2.0, 2.0]
    weights = policy.get("ranking_weights") or {}
    if isinstance(weights, dict):
        for name, w in weights.items():
            try:
                w_val = float(w)
            except (TypeError, ValueError):
                violations.append(f"ranking_weights.{name}={w!r} 不是数")
                continue
            if w_val < -2.0 or w_val > 2.0:
                violations.append(f"ranking_weights.{name}={w_val} 超出 [-2.0, 2.0]")

    # 5) v1.1 §0.6 修订 2 + §9.9：rollback_condition 检查已删除（实验室阶段
    # 无 canary / rollback artifact，git revert 代替；EvoPolicyVersion schema
    # 已删该字段）

    # 6) 全序列化扫 W2 关键词 + feedback 禁词
    serialized = _serialize(policy)
    label_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_LABELS)
    prop_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_PROPERTIES)
    if label_hits or prop_hits:
        violations.append(f"policy 含 W2 字段: labels={label_hits} props={prop_hits}")

    if violations:
        raise SecurityError(
            "pre_policy_publish_guard 拒绝: " + " | ".join(violations)
        )

    return {
        "guard": "pre_policy_publish_guard",
        "passed": True,
        "violations": [],
    }


# ===========================================================================
# 十五、evo hook 6 —— post_evo_writeback_audit（spec v1 §7.4.6）
# ===========================================================================


# spec v1 §3.6 + A.1：EvoMemoryStore 允许的节点 labels
EVO_ALLOWED_LABELS = frozenset(
    {
        "Skill",
        "SkillVersion",
        "SkillTrigger",
        "SkillActivation",
        "SkillValidationRecord",
        "SkillSet",
        "SkillConflictRecord",
        "EvoRunTrace",
        "EvoRunStep",
        "ReplayCase",
        "EvoPolicy",
        "EvoPolicyVersion",
        "SanitizedFeedbackPacket",
        "FeedbackCell",
        "EvoReleaseCard",
        "PolicyTrainingRun",
        # 关系类型也允许出现在 label 字段（写边时）
        "TRIGGERED",
        "ACTIVATED",
        "VALIDATED_BY",
        "PROMOTED_TO",
        "SUPERSEDES",
        "DERIVED_FROM",
    }
)


def post_evo_writeback_audit(node_or_edge: Dict[str, Any]) -> Dict[str, Any]:
    """写 EvoMemoryStore 节点 / 边前的硬门（spec v1 §7.4.6）。

    检查：
    - label 在 EVO_ALLOWED_LABELS（namespace 限制）；
    - properties 不含 forbidden（W2 / evaluator-only / authority）；
    - 关系 / target 不指向 evaluator truth；
    - runtime-safe projection 不含 validation metric 细节。

    入参：node_or_edge —— 即将写入的节点/边 dict，至少含 'label' 或
        'type'，可含 'properties' 子 dict。
    返回：guard 结果 dict。
    违规：抛 SecurityError（spec §7.4.6 写入回滚 + security incident artifact）。
    """
    violations: List[str] = []

    if not isinstance(node_or_edge, dict):
        raise SecurityError(
            "post_evo_writeback_audit: node_or_edge 必须是 dict"
        )

    label = node_or_edge.get("label") or node_or_edge.get("type") or ""
    if label and label not in EVO_ALLOWED_LABELS:
        violations.append(
            f"label={label!r} 不在 EvoMemoryStore allowed namespace"
        )

    # property keys 扫禁字段
    props = node_or_edge.get("properties") or {}
    if isinstance(props, dict):
        forbidden_prop_hits = [k for k in props.keys() if k in EVO_FORBIDDEN_PROPERTIES]
        if forbidden_prop_hits:
            violations.append(
                f"properties 含禁 keys: {forbidden_prop_hits}"
            )
        # evaluator-only 字段：扫 truth_label / expected_label / ...
        eval_only_keys = {
            "expected_verdict",
            "truth_label",
            "expected_label",
            "reference_outcome",
            "raw_eval_truth",
            "w2_basis_ref",
            "basis_item_id",
            "feedback_truth_comment",
            "leaked_expected_verdict",
        }
        eval_hits = [k for k in props.keys() if k in eval_only_keys]
        if eval_hits:
            violations.append(f"properties 含 evaluator-only 字段: {eval_hits}")

    # 关系审计：禁向 evaluator truth 节点指
    target_label = node_or_edge.get("target_label") or node_or_edge.get(
        "to_label"
    )
    if target_label and target_label not in EVO_ALLOWED_LABELS:
        forbidden_target = {
            "EvalTruthReport",
            "RawEvalTruth",
            "W2Truth",
            "ExpectedOutcome",
            "ReferenceVerdict",
            "RawFeedback",
        }
        if target_label in forbidden_target:
            violations.append(
                f"target_label={target_label!r} 指向 evaluator truth"
            )

    # 序列化扫 W2 关键词（防嵌套结构里有禁字段值）
    serialized = _serialize(node_or_edge)
    label_hits = _scan_text_tokens(serialized, EVO_FORBIDDEN_LABELS)
    # 排除节点自身合法的 label 名（label 字段命中是上面已经判断过的）
    label_hits = [h for h in label_hits if h != label]
    if label_hits:
        violations.append(f"含 W2 label 字符串: {label_hits}")

    if violations:
        raise SecurityError(
            "post_evo_writeback_audit 拒绝写入: " + " | ".join(violations)
        )

    return {
        "guard": "post_evo_writeback_audit",
        "passed": True,
        "violations": [],
    }


__all__ = [
    "SecurityError",
    "OutputGuardError",
    "AGENT_FORBIDDEN_LABELS",
    "AGENT_FORBIDDEN_PROPERTIES",
    "AGENT_FORBIDDEN_FILES",
    "AUDIT_WHITELIST_EXCEPTIONS",
    "FORBIDDEN_QUERY_PATTERNS",
    "FORBIDDEN_OUTPUT_PHRASES",
    "EVO_FORBIDDEN_LABELS",
    "EVO_FORBIDDEN_PROPERTIES",
    "EVO_ALLOWED_LABELS",
    "SKILL_PACKAGE_FORBIDDEN_TOKENS",
    "POLICY_FORBIDDEN_TOKENS",
    "FEEDBACK_FORBIDDEN_TOKENS",
    "SKILL_REQUIRED_FORBIDDEN_ACTIONS",
    "SKILL_ALLOWED_KINDS",
    "VERIFIER_AUTHORITY_FIELDS",
    "pre_run_input_guard",
    "pre_retrieval_query_guard",
    "post_retrieval_source_audit",
    "post_verifier_stop_gate",
    "pre_output_language_guard",
    # v1 evo hooks
    "pre_skill_candidate_guard",
    "post_skill_validation_audit",
    "pre_skill_runtime_load_guard",
    "pre_feedback_ingest_guard",
    "pre_policy_publish_guard",
    "post_evo_writeback_audit",
]
