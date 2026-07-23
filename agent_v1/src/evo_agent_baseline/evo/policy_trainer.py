"""EvoPolicy Trainer —— 从 trace / raw W2 / feedback 训练新 policy candidate。

权威：spec v1 §9.7（v1.1 修订）。

5 步算子（spec v1 §9.7.3 pseudocode）：
    1) open/blocked reason priority：aggregate_open_blocked_reasons → rank
    2) skill activation ordering：aggregate_skill_activation_stats → sort
    3) retrieval weights：aggregate_feedback_deficits → adjust ranking_weights ±0.05
    4) cost fallback：if median tool calls 增长 >15%，tighten deep_lookup budget
    5) enforce bounds：candidate_floor + weight bounds [-2.0, 2.0]

约束：
    - weight step 固定 0.05
    - 单 version 对同 weight 调整不超过 ±0.20（避免震荡）

**v1.1 修订（spec §0.6 修订 1 + §9.7.1 + §2.1.3 / §2.5）**：

- ``train_from_traces`` 接口扩容：trainer 可直接读 raw ``EvalTruthReport`` 与
  W2 projection tables 算 reward / loss / counterfactual（spec §9.7.1 输入清单）；
- artifact 输出端约束保留：trainer 输出的 candidate `EvoPolicyVersion` 经
  Gate 0 静态扫 + §11.9 artifact 端 reconstruction probe 确认不含 raw W2 token
  / case-specific signal 后才能 promote；
- candidate 输出 ``status='draft'``（v1.1 3 态简化，spec §3.6.4 / §9.7.5）；
- ``trained_on_artifacts`` 新字段：trainer 输入 artifact ref 列表，含 raw
  ``EvalTruthReport`` ref / replay set / trace set 等，供审计追溯。
"""

from __future__ import annotations

import copy
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from evo_agent_baseline.contracts import (
    EvoPolicyVersion,
    EvoRunTrace,
    SanitizedFeedbackPacket,
)


WEIGHT_STEP = 0.05
WEIGHT_MAX_DELTA_PER_VERSION = 0.20
WEIGHT_MIN = -2.0
WEIGHT_MAX = 2.0
TOOL_CALLS_INCREASE_THRESHOLD = 0.15  # spec v1 §9.7.3 步骤 4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_sha256(obj: Any) -> str:
    """spec v1 §3.8：canonical JSON + sha256 摘要（trained_on_artifacts hash 用）。"""
    try:
        canonical = json.dumps(
            obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        )
    except TypeError:
        canonical = str(obj)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 内部聚合
# ---------------------------------------------------------------------------


def _aggregate_open_blocked_reasons(
    traces: Sequence[EvoRunTrace],
) -> Dict[str, int]:
    """统计 open + blocked reason 总频次（spec v1 §9.7.3 步骤 1）。"""
    counts: Dict[str, int] = defaultdict(int)
    for trace in traces:
        cs = trace.closure_summary or {}
        for reason, n in (cs.get("open_reason_counts") or {}).items():
            counts[reason] += int(n)
        for reason, n in (cs.get("blocked_reason_counts") or {}).items():
            counts[reason] += int(n)
    return dict(counts)


def _rank_by_frequency_and_fixability(reason_counts: Dict[str, int]) -> Dict[str, int]:
    """rank reason 优先级。

    spec v1 §9.7.3 步骤 1：rank_by_frequency_and_fixability。
    baseline：纯频次降序 + 已知"fixable"reason 加 10 优先级 boost。
    """
    # 已知 fixable reason（agent 自身可推动）
    fixable = {
        "missing_fact",
        "missing_measurement",
        "missing_sidecar_entry",
        "missing_artifact_evidence",
        "ambiguous_fact_binding",
    }
    scored = {
        r: n + (10 if r in fixable else 0) for r, n in reason_counts.items()
    }
    ordered = sorted(scored.items(), key=lambda x: (-x[1], x[0]))
    return {reason: rank for rank, (reason, _) in enumerate(ordered, start=1)}


def _aggregate_skill_activation_stats(
    traces: Sequence[EvoRunTrace],
) -> Dict[str, Dict[str, float]]:
    """统计每个 active skill_version 的 activation count / closed contribution。

    baseline：从 trace.steps 取 selected_skill_ids，汇总每 skill 出现次数。
    """
    stats: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"activation_count": 0.0, "closed_runs": 0.0, "total_runs": 0.0}
    )
    for trace in traces:
        skill_ids_in_run = {
            sid for step in trace.steps for sid in step.selected_skill_ids
        }
        closed = (trace.closure_summary or {}).get("closed_count", 0)
        total = (trace.closure_summary or {}).get("total_obligations", 0)
        for sid in skill_ids_in_run:
            stats[sid]["activation_count"] += 1
            stats[sid]["total_runs"] += 1
            if total > 0 and closed / total >= 0.8:
                stats[sid]["closed_runs"] += 1
    return dict(stats)


def _sort_skills_by_score(
    stats: Dict[str, Dict[str, float]],
) -> List[str]:
    """skill_activation_order：按 validation_score / median_benefit / staleness。

    baseline：用 closed_runs/total_runs 作 validation_score 代理；按 desc 排。
    """
    def _score(sid: str) -> float:
        s = stats[sid]
        if s["total_runs"] == 0:
            return 0.0
        return s["closed_runs"] / s["total_runs"]

    return sorted(stats.keys(), key=lambda s: (-_score(s), s))


def _aggregate_feedback_deficits(
    packets: Sequence[SanitizedFeedbackPacket],
) -> List[Dict[str, Any]]:
    """从 sanitized feedback 中提取 deficit cell。

    baseline：cell 中 delta_bucket 起始为 '-' 表示 deficit。
    输出 list of {dimension, metric_name, delta_bucket}。
    """
    out = []
    for packet in packets:
        for cell in packet.cells:
            if cell.suppressed:
                continue
            if cell.delta_bucket and cell.delta_bucket.startswith("-"):
                out.append(
                    {
                        "dimension": dict(cell.dimension),
                        "metric_name": cell.metric_name,
                        "delta_bucket": cell.delta_bucket,
                    }
                )
    return out


def _mapped_feature(deficit: Dict[str, Any]) -> Optional[str]:
    """deficit → ranking_weights 字段名映射。

    baseline 简单映射：把 dimension['semantic_slot_class'] / dimension['rule_family']
    转 weight feature key。
    """
    dim = deficit.get("dimension", {})
    if "semantic_slot_class" in dim:
        return f"slot_class::{dim['semantic_slot_class']}"
    if "rule_family" in dim:
        return f"rule_family::{dim['rule_family']}"
    if "obligation_kind" in dim:
        return f"obl_kind::{dim['obligation_kind']}"
    return None


def _adjust_weight(
    weights: Dict[str, float],
    feature: str,
    step: float,
    *,
    delta_tracker: Dict[str, float],
) -> None:
    """spec v1 §9.7.3 ：weight ±step，单 version 同 feature 累计 ≤ ±0.20。"""
    accumulated = delta_tracker.get(feature, 0.0)
    if abs(accumulated + step) > WEIGHT_MAX_DELTA_PER_VERSION:
        # 截断到上限
        step = (WEIGHT_MAX_DELTA_PER_VERSION - abs(accumulated)) * (
            1 if step > 0 else -1
        )
        if abs(step) < 1e-9:
            return
    weights[feature] = weights.get(feature, 0.0) + step
    delta_tracker[feature] = delta_tracker.get(feature, 0.0) + step


def _enforce_candidate_floor(policy: EvoPolicyVersion) -> None:
    """spec v1 §9.7.3 步骤 5：candidate_cutoff_policy 不可破坏 candidate floor。

    1. ``max_candidates / topk / limit`` 下限 1（避免空 candidate set，spec §5.5.1）
    2. ``verifier_floor`` 字面量强制 ``"all_score_positive_not_deterministically_excluded"``
       （spec §5.5 + Appendix B.4；publish guard 也校验此字段，trainer 必须先写正）

    Codex review 2026-05-27 A2[P2]：原实现只修 max_candidates 等，未写
    ``verifier_floor``，trainer 产物会被 ``pre_policy_publish_guard`` 拒绝。
    """
    p = policy.candidate_cutoff_policy
    if not isinstance(p, dict):
        # 极端兜底：candidate_cutoff_policy 必须是 dict（Pydantic 已校验），
        # 不是 dict 时无法写入 floor 字段，让 publish guard 兜底拦截
        return
    for k in ("max_candidates", "topk", "limit"):
        if k in p and isinstance(p[k], int) and p[k] < 1:
            p[k] = 1
    # spec §5.5 不变量：verifier_floor 字面量必填
    from evo_agent_baseline.agent.policy_runtime import VERIFIER_FLOOR_LITERAL
    p["verifier_floor"] = VERIFIER_FLOOR_LITERAL


def _enforce_weight_bounds(weights: Dict[str, float]) -> None:
    for k, v in list(weights.items()):
        weights[k] = max(WEIGHT_MIN, min(WEIGHT_MAX, v))


def _median_tool_calls(traces: Sequence[EvoRunTrace]) -> float:
    if not traces:
        return 0.0
    return statistics.median([t.tool_call_count for t in traces])


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class EvoPolicyTrainer:
    """spec v1 §9.7 deterministic batch rule trainer。

    baseline：纯规则；未来可换 LTR / bandit（保留接口）。
    """

    def __init__(self, *, policy_id_default: str = "policy.mbis.runtime.default") -> None:
        self.policy_id_default = policy_id_default

    def train_from_traces(
        self,
        traces: Sequence[EvoRunTrace],
        feedback: Sequence[SanitizedFeedbackPacket],
        current_policy: EvoPolicyVersion,
        *,
        new_version: Optional[str] = None,
        baseline_tool_calls_median: Optional[float] = None,
        trained_on_replay_set_id: str = "RS-default",
        # v1.1 §9.7.1 新增输入：trainer 可直接读 raw W2 / EvalTruthReport
        eval_truth_reports: Sequence[Mapping[str, Any]] = (),
        raw_w2_artifacts: Sequence[Mapping[str, Any]] = (),
    ) -> EvoPolicyVersion:
        """从 trace + raw W2 / feedback 训练新 policy candidate。

        spec v1 §9.7.3 5 步算子；输出 ``status='draft'``（v1.1 3 态简化，
        spec §3.6.4 / §9.7.5）。

        **v1.1 §9.7.1 新参数语义**（trainer 工作流 blind 取消）：
            - ``eval_truth_reports``：trainer 直接读取的 raw ``EvalTruthReport``
              dict 序列（每个 dict 形如 spec §8.2 示例：含 ``eval_truth_report_id``
              / ``per_run_results`` / ``raw_metrics`` 等 W2 truth 信息）；
            - ``raw_w2_artifacts``：trainer 直接读取的 raw W2 projection tables /
              threshold_evaluations / basis_items 等 artifact 引用 dict 序列。

        本 baseline 实现暂不真正消费这两个新参数（spec 修订是开放接口，code
        实现可分阶段；本 PR **不要求**真实算 W2-aware reward —— 那是后续 evo
        算法升级任务）；但要在输出的 ``EvoPolicyVersion.trained_on_artifacts``
        正确填充 raw report hash + raw W2 artifact ref，供审计追溯
        （spec §9.11 audit log 字段 ``input_eval_truth_report_hashes``）。

        artifact 输出端约束（v1.1 后真正的 blind 落点）：
            - candidate artifact 须经 Gate 0 静态扫确认不含 raw W2 token；
            - 经 §11.9 artifact 端 reconstruction probe 确认 prior→probe accuracy
              提升 ≤ 0.05；
            - 通过后方可 promote draft → active。
        """
        # 1. open/blocked reason priority
        reason_counts = _aggregate_open_blocked_reasons(traces)
        priority = _rank_by_frequency_and_fixability(reason_counts)

        # 2. skill activation ordering
        skill_stats = _aggregate_skill_activation_stats(traces)
        skill_order = _sort_skills_by_score(skill_stats)
        skill_activation_order = {
            "ordered_skill_version_ids": skill_order,
            "stats_snapshot": skill_stats,
        }

        # 3. retrieval weights：从 deficit 调整
        new_weights = copy.deepcopy(current_policy.ranking_weights)
        delta_tracker: Dict[str, float] = {}
        for deficit in _aggregate_feedback_deficits(feedback):
            feat = _mapped_feature(deficit)
            if feat is None:
                continue
            # deficit 是负 delta_bucket，因此 boost feature（+WEIGHT_STEP）
            _adjust_weight(new_weights, feat, WEIGHT_STEP, delta_tracker=delta_tracker)

        # 4. cost fallback：若 median tool calls 增长 >15%，tighten deep_lookup budget
        new_fallback_thresholds = copy.deepcopy(current_policy.fallback_thresholds)
        if baseline_tool_calls_median is not None and baseline_tool_calls_median > 0:
            current_median = _median_tool_calls(traces)
            growth = (current_median - baseline_tool_calls_median) / baseline_tool_calls_median
            if growth > TOOL_CALLS_INCREASE_THRESHOLD:
                new_fallback_thresholds["deep_lookup_max_per_run"] = max(
                    1,
                    int(new_fallback_thresholds.get("deep_lookup_max_per_run", 5)) - 1,
                )

        # 5. bounds
        _enforce_weight_bounds(new_weights)

        # 构造新 candidate（v1.1 输出 status='draft'，3 态简化）
        version_str = new_version or self._bump_semver(current_policy.version)
        new_policy_version_id = f"{current_policy.policy_id}.v{version_str}"

        # v1.1 §3.6.4 + §9.11：trained_on_artifacts 记录 trainer 输入 artifact ref
        # 含 raw EvalTruthReport hash + W2 artifact ref + replay set + feedback packet
        trained_on_artifacts: List[str] = []
        if trained_on_replay_set_id:
            trained_on_artifacts.append(f"replay_set:{trained_on_replay_set_id}")
        for report in eval_truth_reports:
            report_hash = _canonical_sha256(report)
            report_id = report.get("eval_truth_report_id", "unknown")
            trained_on_artifacts.append(f"eval_truth_report:{report_id}:{report_hash}")
        for w2_art in raw_w2_artifacts:
            art_hash = _canonical_sha256(w2_art)
            art_id = w2_art.get("artifact_id") or w2_art.get("id") or "unknown"
            trained_on_artifacts.append(f"w2_artifact:{art_id}:{art_hash}")
        for packet in feedback:
            trained_on_artifacts.append(
                f"sanitized_packet:{packet.feedback_packet_id}"
            )

        candidate = EvoPolicyVersion(
            policy_version_id=new_policy_version_id,
            policy_id=current_policy.policy_id,
            version=version_str,
            # v1.1 §3.6.4 + §9.7.5：3 态简化，trainer 输出 candidate 进入 draft
            status="draft",
            ranking_weights=new_weights,
            tool_preferences=copy.deepcopy(current_policy.tool_preferences),
            skill_activation_order=skill_activation_order,
            open_obligation_priority={"ranks": priority},
            candidate_cutoff_policy=copy.deepcopy(current_policy.candidate_cutoff_policy),
            report_template_policy=copy.deepcopy(current_policy.report_template_policy),
            fallback_thresholds=new_fallback_thresholds,
            max_tool_iterations_default=current_policy.max_tool_iterations_default,
            experiment_budgets=list(current_policy.experiment_budgets),
            trained_on_replay_set_id=trained_on_replay_set_id,
            # v1.1 §3.6.4 新字段：trainer 输入 artifact ref 列表
            trained_on_artifacts=trained_on_artifacts,
            # v1.1 §3.6.4 保留但不再硬约束：仅 runtime trend feedback 接口启用时填
            trained_on_feedback_packet_ids=[p.feedback_packet_id for p in feedback],
            validation_summary={},
            # v1.1 §3.6.4 删除：previous_active_version_id（git history 代替）
            # v1.1 §3.6.4 + §9.9 删除：rollback_condition（无 canary / rollback）
            created_at=_utc_now_iso(),
            activated_at=None,
        )

        _enforce_candidate_floor(candidate)
        return candidate

    def _bump_semver(self, version: str) -> str:
        """对 'M.m.p' 做 minor bump（M.m+1.0）。"""
        parts = version.split(".")
        if len(parts) != 3:
            return "1.0.0"
        try:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{major}.{minor + 1}.0"
        except ValueError:
            return "1.0.0"


__all__ = [
    "EvoPolicyTrainer",
    "WEIGHT_STEP",
    "WEIGHT_MAX_DELTA_PER_VERSION",
    "WEIGHT_MIN",
    "WEIGHT_MAX",
    "TOOL_CALLS_INCREASE_THRESHOLD",
]
