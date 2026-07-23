"""运行时 Scaling Law 指标（spec v1 §11.1-§11.4）。

本模块提供 evo-agent v1 运行时 Scaling Law 的 6 个核心函数：

| 函数 | spec 锚点 |
|------|----------|
| ``compute_effective_trace_count`` | §11.2 effective trace 公式 |
| ``compute_e_runtime`` | §11.3 ``E_runtime = Σ_i v×n×c×f`` 公式 |
| ``compute_compliance_quality_metrics`` | §11.4.1 第 1 类（合规任务） |
| ``compute_closure_quality_metrics`` | §11.4.2 第 2 类（closure 质量） |
| ``compute_evo_specific_metrics`` | §11.4.3 第 3 类（evo 特有） |
| ``fit_error_curve`` | §11.8 ``Error(E) = A × E^-α + β`` 拟合 |

工程边界（项目原则 2 + 3）：
- evo-agent blind：本模块输入 traces / skills / policies / validation_records /
  closure_results 均是 agent / evo trainer 已可见对象；**不** 直接读 W2 字段。
  合规质量指标 ``eval_results`` 是 evaluator 私域产出的 aggregate（dict 形态），
  evaluator 自己负责脱 sensitive 字段；本模块只做算术。
- allow_stop 不可逆：本模块只统计 ``allow_stop`` 分布，**绝不** 反写 verifier。

数值约束（spec v1 §11.3）：
- ``validity_i ∈ {0, 1}``
- ``novelty_i ∈ [0.2, 1.0]``  ；公式 ``novelty = 1/sqrt(1 + n_seen)``，下限 0.2
- ``coverage_weight_i ∈ [1.0, 3.0]``  ；默认 1.0、rare 1.5、release gate 指定可达 3.0
- ``feedback_available_i ∈ {1.0, 1.2}``

novelty pattern key 严格按 spec v1 §11.3：
``(rule_family, semantic_slot_class, obligation_kind, open_or_blocked_reason)``。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# §11.2 effective trace + §11.3 E_runtime
# ---------------------------------------------------------------------------

#: spec v1 §11.3 novelty 下限。
NOVELTY_FLOOR: float = 0.2

#: spec v1 §11.3 coverage_weight 下/上限。
COVERAGE_WEIGHT_MIN: float = 1.0
COVERAGE_WEIGHT_MAX: float = 3.0

#: spec v1 §11.3 feedback_available 二值集合。
FEEDBACK_AVAILABLE_VALUES: Tuple[float, float] = (1.0, 1.2)


def _is_effective_trace(trace: Any, replay_eligibility: Optional[str]) -> bool:
    """spec v1 §11.2 ``effective`` 判定。

    一个 trace 是 effective trace 当且仅当满足全部 6 个谓词：

    1. ``trace.forbidden_scan_passed``
    2. ``trace.source_visibility_audit_passed``
    3. ``trace.schema_audit_passed``
    4. ``trace.candidate_floor_passed``
    5. ``trace.raw_w2_access == False``（trace 上无该字段时按 EvoRunTrace
       `trace_visibility="agent_visible_trace"` 推断 = 不访问 W2 = True）
    6. ``replay_case.eligibility == "eligible"``

    EvoRunTrace（contracts.py B.2）不显式落 ``raw_w2_access`` 字段；其
    ``trace_visibility`` 被 Literal 限定为 ``"agent_visible_trace"``，等价于
    spec §11.2 第 5 条。本函数若 trace 上能取到 ``raw_w2_access`` 则严格
    用之；否则用 ``trace_visibility == "agent_visible_trace"`` 推断。
    """
    if not getattr(trace, "forbidden_scan_passed", False):
        return False
    if not getattr(trace, "source_visibility_audit_passed", False):
        return False
    if not getattr(trace, "schema_audit_passed", False):
        return False
    if not getattr(trace, "candidate_floor_passed", False):
        return False
    raw_w2_access = getattr(trace, "raw_w2_access", None)
    if raw_w2_access is True:
        return False
    if raw_w2_access is None:
        # 退化按 trace_visibility 推断（EvoRunTrace 默认 agent_visible_trace）
        visibility = getattr(trace, "trace_visibility", None)
        if visibility != "agent_visible_trace":
            return False
    if replay_eligibility != "eligible":
        return False
    return True


def _pattern_key(trace: Any) -> Tuple[str, str, str, str]:
    """spec v1 §11.3 novelty pattern key（4 元组）。

    ``(rule_family, semantic_slot_class, obligation_kind, open_or_blocked_reason)``

    任一缺失字段以空字符串补；空字符串不豁免计数（保持 conservative）。
    """
    rule_family = str(getattr(trace, "rule_family", "") or "")
    slot_class = str(getattr(trace, "semantic_slot_class", "") or "")
    obligation_kind = str(getattr(trace, "obligation_kind", "") or "")
    reason = str(getattr(trace, "open_or_blocked_reason", "") or "")
    return (rule_family, slot_class, obligation_kind, reason)


def _novelty_from_n_seen(n_seen: int) -> float:
    """spec v1 §11.3 ``novelty_i = 1 / sqrt(1 + n_seen)``；下限 0.2。"""
    value = 1.0 / math.sqrt(1 + max(0, int(n_seen)))
    return max(NOVELTY_FLOOR, value)


def _replay_lookup(
    replay_eligibility_by_trace: Optional[Mapping[str, str]],
    trace_id: str,
) -> Optional[str]:
    if replay_eligibility_by_trace is None:
        return None
    return replay_eligibility_by_trace.get(trace_id)


def _coverage_weight_lookup(
    coverage_weight_by_trace: Optional[Mapping[str, float]],
    trace_id: str,
) -> float:
    if coverage_weight_by_trace is None:
        return COVERAGE_WEIGHT_MIN
    w = coverage_weight_by_trace.get(trace_id, COVERAGE_WEIGHT_MIN)
    return float(max(COVERAGE_WEIGHT_MIN, min(COVERAGE_WEIGHT_MAX, w)))


def _feedback_available_lookup(
    feedback_available_trace_ids: Optional[Iterable[str]],
    trace_id: str,
) -> float:
    if feedback_available_trace_ids is None:
        return FEEDBACK_AVAILABLE_VALUES[0]
    return (
        FEEDBACK_AVAILABLE_VALUES[1]
        if trace_id in set(feedback_available_trace_ids)
        else FEEDBACK_AVAILABLE_VALUES[0]
    )


def compute_effective_trace_count(
    traces: Sequence[Any],
    *,
    replay_eligibility_by_trace: Optional[Mapping[str, str]] = None,
    coverage_weight_by_trace: Optional[Mapping[str, float]] = None,
    feedback_available_trace_ids: Optional[Iterable[str]] = None,
) -> float:
    """加权 effective trace 总数（spec v1 §11.2 + §11.3）。

    定义：
        ``effective_trace_count = Σ_i validity_i × novelty_i ×
        coverage_weight_i × feedback_available_i``

    与 ``compute_e_runtime`` 的区别：本函数等价于 ``E_runtime`` 当
    ``feedback_packets`` 视图与 ``feedback_available_trace_ids`` 一致；
    本函数留作 spec §11.6 ``EvoReleaseCard.effective_trace_count`` 写入字段。

    参数：
        traces: 候选 trace 序列；通常是 EvoRunTrace（contracts.py B.2）。
        replay_eligibility_by_trace: ``trace_id -> eligibility``；缺失视作
            ``None``（不可知）→ trace 不进 effective 集合。
        coverage_weight_by_trace: ``trace_id -> coverage_weight``；缺失按
            §11.3 默认 1.0。
        feedback_available_trace_ids: 属已发布 SanitizedFeedbackPacket
            aggregate window 的 trace_id 集合；其余按 §11.3 默认 1.0。

    返回：累加 effective weight；invalid trace 贡献 0。
    """
    n_seen: Counter = Counter()
    total = 0.0
    for trace in traces:
        trace_id = getattr(trace, "trace_id", "")
        eligibility = _replay_lookup(replay_eligibility_by_trace, trace_id)
        validity = 1.0 if _is_effective_trace(trace, eligibility) else 0.0
        # novelty 必须基于已见 pattern 数累积；invalid trace 也不应计入
        # n_seen，否则会扭曲后续 trace 的 novelty
        if validity == 0.0:
            continue
        key = _pattern_key(trace)
        novelty = _novelty_from_n_seen(n_seen[key])
        n_seen[key] += 1
        coverage = _coverage_weight_lookup(coverage_weight_by_trace, trace_id)
        feedback = _feedback_available_lookup(
            feedback_available_trace_ids, trace_id
        )
        total += validity * novelty * coverage * feedback
    return total


def compute_e_runtime(
    traces: Sequence[Any],
    feedback_packets: Sequence[Any],
    *,
    replay_eligibility_by_trace: Optional[Mapping[str, str]] = None,
    coverage_weight_by_trace: Optional[Mapping[str, float]] = None,
) -> float:
    """``E_runtime`` 综合经验量（spec v1 §11.3）。

    ``feedback_packets`` 决定哪些 trace 的 ``feedback_available_i = 1.2``：
    spec §11.3 ``feedback_available_i=1.2 当 trace 属于已发布
    SanitizedFeedbackPacket 的 aggregate window``。本函数取
    ``packet.sanitized_feedback_refs`` ∪ trace 的
    ``sanitized_feedback_refs``（EvoRunTrace B.2 字段）反查：trace
    若其 ``sanitized_feedback_refs`` 与任一 packet ``feedback_packet_id``
    交集非空，则视为 packet aggregate window 内。

    返回：见 §11.3 ``E_runtime = Σ_i validity × novelty × coverage × feedback``。
    """
    packet_ids = {
        getattr(pkt, "feedback_packet_id", None)
        for pkt in feedback_packets
        if getattr(pkt, "feedback_packet_id", None)
    }
    feedback_available_trace_ids: List[str] = []
    for trace in traces:
        refs = list(getattr(trace, "sanitized_feedback_refs", []) or [])
        if any(ref in packet_ids for ref in refs):
            feedback_available_trace_ids.append(getattr(trace, "trace_id", ""))
    return compute_effective_trace_count(
        traces,
        replay_eligibility_by_trace=replay_eligibility_by_trace,
        coverage_weight_by_trace=coverage_weight_by_trace,
        feedback_available_trace_ids=feedback_available_trace_ids,
    )


# ---------------------------------------------------------------------------
# §11.4.1 第 1 类：合规任务质量指标
# ---------------------------------------------------------------------------

#: spec v1 §11.4.1 verdict 4 类标签（用于 macro F1 / accuracy 聚合）。
VERDICT_LABELS: Tuple[str, ...] = ("pass", "fail", "unknown", "not_applicable")


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def _macro_f1(records: Sequence[Mapping[str, Any]]) -> float:
    """4 类 verdict macro-F1（spec v1 §11.4.1 ``verdict_macro_f1``）。

    每条记录至少含 ``predicted_verdict`` 和 ``reference_verdict``（aggregate
    数据由 evaluator private side 提供，本模块不读 W2 raw）。
    """
    if not records:
        return 0.0
    per_label_f1: List[float] = []
    for label in VERDICT_LABELS:
        tp = sum(
            1
            for r in records
            if r.get("predicted_verdict") == label
            and r.get("reference_verdict") == label
        )
        fp = sum(
            1
            for r in records
            if r.get("predicted_verdict") == label
            and r.get("reference_verdict") != label
        )
        fn = sum(
            1
            for r in records
            if r.get("predicted_verdict") != label
            and r.get("reference_verdict") == label
        )
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_label_f1.append(f1)
    return sum(per_label_f1) / len(per_label_f1)


def _severity_weighted_accuracy(records: Sequence[Mapping[str, Any]]) -> float:
    """spec v1 §11.4.1 ``severity_weighted_accuracy``。

    每条记录可含 ``severity_weight``（评测私域产生的标量；缺失 = 1.0）。
    """
    if not records:
        return 0.0
    num = 0.0
    den = 0.0
    for r in records:
        weight = float(r.get("severity_weight", 1.0))
        if r.get("predicted_verdict") == r.get("reference_verdict"):
            num += weight
        den += weight
    return _safe_div(num, den)


def _threshold_alignment(records: Sequence[Mapping[str, Any]]) -> float:
    """spec v1 §11.4.1 ``threshold_alignment``。

    比较 ``threshold_operator`` / ``threshold_value`` / ``observed_comparator``
    aggregate 对齐率（三者全等才算 aligned）。
    """
    if not records:
        return 0.0
    aligned = 0
    for r in records:
        if (
            r.get("predicted_threshold_operator") == r.get("reference_threshold_operator")
            and r.get("predicted_threshold_value") == r.get("reference_threshold_value")
            and r.get("predicted_observed_comparator") == r.get("reference_observed_comparator")
        ):
            aligned += 1
    return _safe_div(aligned, len(records))


def _family_recall_precision(
    records: Sequence[Mapping[str, Any]],
) -> Tuple[float, float]:
    """spec v1 §11.4.1 ``family_recall`` / ``family_precision``。

    每条记录 ``agent_families`` (set/list) 与 ``reference_families``
    (set/list) — 都是 evaluator aggregate 输出的 family id 集合。
    """
    if not records:
        return 0.0, 0.0
    recall_total = 0.0
    precision_total = 0.0
    for r in records:
        agent = set(r.get("agent_families", []) or [])
        ref = set(r.get("reference_families", []) or [])
        if ref:
            recall_total += len(agent & ref) / len(ref)
        else:
            # reference 空 → recall 默认 1（无需召回）
            recall_total += 1.0
        if agent:
            precision_total += len(agent & ref) / len(agent)
        else:
            # agent 空 → precision 默认 1（没产 spurious）
            precision_total += 1.0
    n = len(records)
    return recall_total / n, precision_total / n


def _slot_requirement_recall(records: Sequence[Mapping[str, Any]]) -> float:
    """spec v1 §11.4.1 ``slot_requirement_recall``。

    每条记录 ``required_semantic_slots`` 与 ``covered_semantic_slots``。
    """
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        required = set(r.get("required_semantic_slots", []) or [])
        covered = set(r.get("covered_semantic_slots", []) or [])
        if required:
            total += len(required & covered) / len(required)
        else:
            total += 1.0
    return total / len(records)


def _artifact_evidence_alignment(records: Sequence[Mapping[str, Any]]) -> float:
    """spec v1 §11.4.1 ``artifact_evidence_alignment``。

    artifact_required 与 artifact_observed aggregate 对齐率。
    """
    if not records:
        return 0.0
    aligned = 0
    for r in records:
        if r.get("artifact_required") == r.get("artifact_observed_aggregate"):
            aligned += 1
    return _safe_div(aligned, len(records))


def compute_compliance_quality_metrics(
    eval_results: Sequence[Mapping[str, Any]],
) -> Dict[str, float]:
    """spec v1 §11.4.1 第 1 类指标（合规任务质量）。

    输入：evaluator private side 产出的 aggregate 记录序列；每条至少含上述
    各 helper 函数引用的字段。**注意**：本函数不接受 raw W2 字段名
    （expected_verdict / basis_items / projection_id 等）；评测侧自己已经
    脱 sensitive 名 → ``reference_verdict`` / ``reference_families`` 等已聚合
    名出现，符合 spec v1 §2.2.3 evo-agent blind 红线。

    返回 dict 含 7 个 metric（spec v1 §11.4.1 全表）。
    """
    family_recall, family_precision = _family_recall_precision(eval_results)
    return {
        "verdict_macro_f1": _macro_f1(eval_results),
        "severity_weighted_accuracy": _severity_weighted_accuracy(eval_results),
        "family_recall": family_recall,
        "family_precision": family_precision,
        "slot_requirement_recall": _slot_requirement_recall(eval_results),
        "threshold_alignment": _threshold_alignment(eval_results),
        "artifact_evidence_alignment": _artifact_evidence_alignment(eval_results),
    }


# ---------------------------------------------------------------------------
# §11.4.2 第 2 类：Closure 质量指标
# ---------------------------------------------------------------------------


def compute_closure_quality_metrics(
    closure_results: Sequence[Mapping[str, Any]],
    *,
    previous_release_metrics: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """spec v1 §11.4.2 第 2 类指标（closure 质量）。

    输入：agent-owned closure artifacts 序列；每条至少含：

    - ``allow_stop`` (bool)
    - ``open_count`` (int)
    - ``blocked_count`` (int)
    - ``open_blocked_reasons`` (dict[str, int])，按 reason code 计数
    - ``evidence_coverage_rate`` (float, 0-1)
    - ``candidate_floor_passed`` (bool)
    - ``schema_contract_passed`` (bool)
    - ``guard_passed`` (bool)

    ``closure_non_regression`` 与上一 release 的 metrics 对比，若提供
    ``previous_release_metrics``（dict with ``open_count_avg`` /
    ``blocked_count_avg`` / ``evidence_coverage_rate_avg``），返回当前
    是否未 regression（1.0 通过 / 0.0 fail）。未提供则返回 1.0（首发）。
    """
    n = len(closure_results)
    if n == 0:
        return {
            "allow_stop_precision_proxy": 0.0,
            "open_count": 0.0,
            "blocked_count": 0.0,
            "open_blocked_by_reason": {},  # type: ignore[dict-item]
            "evidence_coverage_rate": 0.0,
            "candidate_floor_pass_rate": 0.0,
            "closure_non_regression": 1.0,
            "schema_contract_pass_rate": 0.0,
        }

    # allow_stop_precision_proxy：spec v1 §11.4.2 = allow_stop=True 时
    # open/blocked=0 且 guard pass 比例。仅 evaluator aggregate 校验；
    # 这里给出 agent 侧 proxy。
    allow_stop_true = [r for r in closure_results if r.get("allow_stop") is True]
    if allow_stop_true:
        proxy_num = sum(
            1
            for r in allow_stop_true
            if int(r.get("open_count", 0)) == 0
            and int(r.get("blocked_count", 0)) == 0
            and r.get("guard_passed") is True
        )
        proxy = _safe_div(proxy_num, len(allow_stop_true))
    else:
        # 无 allow_stop=True → spec 未定义；保守返 0
        proxy = 0.0

    open_avg = sum(int(r.get("open_count", 0)) for r in closure_results) / n
    blocked_avg = sum(int(r.get("blocked_count", 0)) for r in closure_results) / n

    reason_counter: Counter = Counter()
    for r in closure_results:
        for reason, cnt in (r.get("open_blocked_reasons", {}) or {}).items():
            reason_counter[reason] += int(cnt)

    evidence_avg = (
        sum(float(r.get("evidence_coverage_rate", 0.0)) for r in closure_results) / n
    )
    candidate_floor_rate = _safe_div(
        sum(1 for r in closure_results if r.get("candidate_floor_passed") is True),
        n,
    )
    schema_rate = _safe_div(
        sum(1 for r in closure_results if r.get("schema_contract_passed") is True),
        n,
    )

    if previous_release_metrics:
        # non-regression：open / blocked 不变多，evidence 不变少
        non_regression = 1.0
        if open_avg > float(previous_release_metrics.get("open_count_avg", open_avg)):
            non_regression = 0.0
        if blocked_avg > float(
            previous_release_metrics.get("blocked_count_avg", blocked_avg)
        ):
            non_regression = 0.0
        if evidence_avg < float(
            previous_release_metrics.get("evidence_coverage_rate_avg", evidence_avg)
        ):
            non_regression = 0.0
    else:
        non_regression = 1.0

    return {
        "allow_stop_precision_proxy": proxy,
        "open_count": float(open_avg),
        "blocked_count": float(blocked_avg),
        "open_blocked_by_reason": dict(reason_counter),  # type: ignore[dict-item]
        "evidence_coverage_rate": float(evidence_avg),
        "candidate_floor_pass_rate": candidate_floor_rate,
        "closure_non_regression": non_regression,
        "schema_contract_pass_rate": schema_rate,
    }


# ---------------------------------------------------------------------------
# §11.4.3 第 3 类：Evo 特有指标
# ---------------------------------------------------------------------------


def _skill_attributable_delta(
    paired_results: Sequence[Mapping[str, Any]],
) -> float:
    """spec v1 §11.4.3 ``skill_attributable_delta``。

    输入 paired 结果序列：每条含 ``baseline_metric`` 与 ``with_skill_metric``，
    返回平均 delta。
    """
    if not paired_results:
        return 0.0
    deltas = [
        float(r.get("with_skill_metric", 0.0)) - float(r.get("baseline_metric", 0.0))
        for r in paired_results
    ]
    return sum(deltas) / len(deltas)


def _evo_gain_vs_static_baseline(
    paired_results: Sequence[Mapping[str, Any]],
) -> float:
    """spec v1 §11.4.3 ``evo_gain_vs_static_baseline``。

    每条含 ``static_baseline_metric`` 与 ``full_evo_metric``。
    """
    if not paired_results:
        return 0.0
    deltas = [
        float(r.get("full_evo_metric", 0.0))
        - float(r.get("static_baseline_metric", 0.0))
        for r in paired_results
    ]
    return sum(deltas) / len(deltas)


def _experience_efficiency(
    effective_trace_count: float,
    metric_gain: float,
) -> float:
    """spec v1 §11.4.3 ``experience_efficiency`` = 每 10 effective traces
    带来的 metric gain。"""
    if effective_trace_count <= 0:
        return 0.0
    return metric_gain * 10.0 / effective_trace_count


def _skill_activation_precision(skills: Sequence[Any]) -> float:
    """spec v1 §11.4.3 ``skill_activation_precision``。

    每个 skill 的 ``activation_stats`` 含 ``eligible_activation_count`` 与
    ``positive_benefit_count``；返回平均比例。
    """
    if not skills:
        return 0.0
    ratios: List[float] = []
    for skill in skills:
        stats = getattr(skill, "activation_stats", {}) or {}
        eligible = int(stats.get("eligible_activation_count", 0))
        positive = int(stats.get("positive_benefit_count", 0))
        if eligible > 0:
            ratios.append(positive / eligible)
    return sum(ratios) / len(ratios) if ratios else 0.0


def _skill_half_life(skills: Sequence[Any]) -> float:
    """spec v1 §11.4.3 ``skill_half_life``：active → retired median window 数。

    每个 skill 的 ``activation_stats`` 可含 ``active_to_retired_window_count``；
    缺失的 skill（如仍 active）不参与 median。
    """
    windows = []
    for skill in skills:
        stats = getattr(skill, "activation_stats", {}) or {}
        if "active_to_retired_window_count" in stats:
            windows.append(int(stats["active_to_retired_window_count"]))
    if not windows:
        return 0.0
    windows.sort()
    mid = len(windows) // 2
    if len(windows) % 2 == 0:
        return (windows[mid - 1] + windows[mid]) / 2.0
    return float(windows[mid])


def _policy_version_improvement_rate(policy_versions: Sequence[Any]) -> float:
    """spec v1 §11.4.3 ``policy_version_improvement_rate``。

    active policy version 中带 ``positive_heldout_delta=True`` 的比例。
    """
    active = [
        p
        for p in policy_versions
        if getattr(p, "status", None) == "active"
    ]
    if not active:
        return 0.0
    positive = sum(
        1
        for p in active
        if bool(
            (getattr(p, "validation_summary", {}) or {}).get(
                "positive_heldout_delta", False
            )
        )
    )
    return positive / len(active)


def _tool_cost_per_closed_obligation(
    traces: Sequence[Any],
    closed_obligation_count: int,
) -> float:
    """spec v1 §11.4.3 ``tool_cost_per_closed_obligation`` = tool calls / closed."""
    if closed_obligation_count <= 0:
        return 0.0
    total_calls = sum(int(getattr(t, "tool_call_count", 0)) for t in traces)
    return total_calls / closed_obligation_count


def _report_citation_coverage(traces: Sequence[Any]) -> float:
    """spec v1 §11.4.3 ``report_citation_coverage``。

    每条 trace ``closure_summary.report_claims_with_citation_ratio`` 平均。
    """
    if not traces:
        return 0.0
    ratios: List[float] = []
    for t in traces:
        cs = getattr(t, "closure_summary", {}) or {}
        ratio = cs.get("report_claims_with_citation_ratio")
        if ratio is not None:
            ratios.append(float(ratio))
    return sum(ratios) / len(ratios) if ratios else 0.0


def _feedback_blindness_pass_rate(validation_records: Sequence[Any]) -> float:
    """spec v1 §11.4.3 ``feedback_blindness_pass_rate``。

    validation_records 中 stage = gate0/gate1/release_gate 且 ``passed=True``
    且 ``leakage_hits=[]`` 的比例。
    """
    if not validation_records:
        return 0.0
    relevant = [
        r
        for r in validation_records
        if getattr(r, "validation_stage", None)
        in {"gate0_static", "gate1_schema_provenance", "release_gate"}
    ]
    if not relevant:
        return 0.0
    passed = sum(
        1
        for r in relevant
        if getattr(r, "passed", False) and not getattr(r, "leakage_hits", [])
    )
    return passed / len(relevant)


def _w2_reconstruction_probe_delta(
    validation_records: Sequence[Any],
) -> float:
    """spec v1 §11.4.3 ``w2_reconstruction_probe_delta``。

    从 validation_records 找 ``release_gate`` 阶段，取最大
    ``probe_accuracy_delta``（若 metric_value_bucket 形式存储则解析为 float）。
    spec §11.4.3 + §11.9 要求 ≤5pp。
    """
    deltas: List[float] = []
    for r in validation_records:
        if getattr(r, "validation_stage", None) != "release_gate":
            continue
        if getattr(r, "metric_name", None) != "w2_reconstruction_probe_delta":
            continue
        bucket = getattr(r, "metric_value_bucket", None)
        try:
            deltas.append(float(bucket))
        except (TypeError, ValueError):
            continue
    return max(deltas) if deltas else 0.0


def compute_evo_specific_metrics(
    traces: Sequence[Any],
    skills: Sequence[Any],
    policy_versions: Sequence[Any],
    validation_records: Sequence[Any],
    *,
    paired_results: Optional[Sequence[Mapping[str, Any]]] = None,
    effective_trace_count: Optional[float] = None,
    metric_gain: float = 0.0,
    closed_obligation_count: int = 0,
) -> Dict[str, float]:
    """spec v1 §11.4.3 第 3 类指标（Evo 特有）。

    返回 dict 含 10 个 metric（§11.4.3 全表）。

    参数：
        traces: EvoRunTrace 序列。
        skills: SkillJson 序列（spec v1 B.3）。
        policy_versions: EvoPolicyVersion 序列（spec v1 B.4）。
        validation_records: SkillValidationRecord 序列（spec v1 B.6）。
        paired_results: 可选 paired ablation 结果用于
            ``skill_attributable_delta`` / ``evo_gain_vs_static_baseline``。
        effective_trace_count: 若提供，直接用于 ``experience_efficiency``；
            否则按 traces 长度（粗 proxy）计算。
        metric_gain: paired gain 标量，用于 ``experience_efficiency``。
        closed_obligation_count: 用于 ``tool_cost_per_closed_obligation``。
    """
    eff_count = (
        float(effective_trace_count)
        if effective_trace_count is not None
        else float(len(traces))
    )
    return {
        "skill_attributable_delta": _skill_attributable_delta(paired_results or []),
        "evo_gain_vs_static_baseline": _evo_gain_vs_static_baseline(
            paired_results or []
        ),
        "experience_efficiency": _experience_efficiency(eff_count, metric_gain),
        "skill_activation_precision": _skill_activation_precision(skills),
        "skill_half_life": _skill_half_life(skills),
        "policy_version_improvement_rate": _policy_version_improvement_rate(
            policy_versions
        ),
        "tool_cost_per_closed_obligation": _tool_cost_per_closed_obligation(
            traces, closed_obligation_count
        ),
        "report_citation_coverage": _report_citation_coverage(traces),
        "feedback_blindness_pass_rate": _feedback_blindness_pass_rate(
            validation_records
        ),
        "w2_reconstruction_probe_delta": _w2_reconstruction_probe_delta(
            validation_records
        ),
    }


# ---------------------------------------------------------------------------
# §11.8 学习曲线拟合
# ---------------------------------------------------------------------------


def fit_error_curve(
    experience_levels: Sequence[float],
    errors: Sequence[float],
) -> Tuple[float, float, float]:
    """spec v1 §11.8 拟合 ``Error(E) = A × E^-α + β``。

    使用 scipy 风格的简单网格 + 局部下降（不引外部依赖）。算法：

    1. 取 ``β ≈ min(errors) × 0.5``（β 是渐近 floor，不可大于最小观测误差）；
    2. 对 ``α ∈ {0.1, 0.2, ..., 2.0}`` 网格搜索；
    3. 对每个 α，按最小二乘解析解求 A：
       ``A = Σ_i (error_i - β) × E_i^-α / Σ_i E_i^-2α``；
    4. 选最小残差的 (A, α, β)；
    5. 对最佳 β 做 ±20% 局部精化。

    spec v1 §11.8：v1 不要求预设 α/γ，但要求记录足够数据以拟合，所以
    本函数返回 ``(A, alpha, beta)`` 三元组写入 EvoReleaseCard。

    参数：
        experience_levels: 单调（或非负）经验量序列；长度 ≥3。
        errors: 对应的误差度量。

    返回：``(A, alpha, beta)``；若样本不足/全等返 ``(0.0, 0.0, mean_error)``。

    异常：``ValueError`` 当 ``len(experience_levels) != len(errors)`` 或长度 <3
        或任一 ``experience_levels`` <=0。
    """
    if len(experience_levels) != len(errors):
        raise ValueError("experience_levels 和 errors 长度必须一致")
    if len(experience_levels) < 3:
        raise ValueError("拟合至少需要 3 个观测点")
    if any(e <= 0 for e in experience_levels):
        raise ValueError("experience_levels 必须严格正")

    err_list = [float(x) for x in errors]
    exp_list = [float(x) for x in experience_levels]
    min_err = min(err_list)
    max_err = max(err_list)
    if abs(max_err - min_err) < 1e-9:
        return 0.0, 0.0, sum(err_list) / len(err_list)

    def residual(A: float, alpha: float, beta: float) -> float:
        return sum(
            (A * (e ** (-alpha)) + beta - y) ** 2
            for e, y in zip(exp_list, err_list)
        )

    alpha_grid = [0.05 * k for k in range(1, 41)]  # 0.05..2.0
    beta_grid = [min_err * f for f in (0.0, 0.25, 0.5, 0.75, 0.95)]
    best: Tuple[float, float, float, float] = (
        0.0,
        0.0,
        sum(err_list) / len(err_list),
        float("inf"),
    )
    for beta in beta_grid:
        for alpha in alpha_grid:
            num = sum(
                (y - beta) * (e ** (-alpha)) for e, y in zip(exp_list, err_list)
            )
            den = sum(e ** (-2 * alpha) for e in exp_list)
            if den <= 0:
                continue
            A = num / den
            r = residual(A, alpha, beta)
            if r < best[3]:
                best = (A, alpha, beta, r)
    return best[0], best[1], best[2]


__all__ = [
    "NOVELTY_FLOOR",
    "COVERAGE_WEIGHT_MIN",
    "COVERAGE_WEIGHT_MAX",
    "FEEDBACK_AVAILABLE_VALUES",
    "VERDICT_LABELS",
    "compute_effective_trace_count",
    "compute_e_runtime",
    "compute_compliance_quality_metrics",
    "compute_closure_quality_metrics",
    "compute_evo_specific_metrics",
    "fit_error_curve",
]
