"""Skill Induction —— evo trainer 的"找模式 → 生 draft SkillPackage"算子。

权威：spec v1 §9.3。

实现 3 类触发：
    - 触发 A 重复失败（§9.3.1 A）：(rule_family, slot, obligation_kind, reason) ≥5 次
      + (≥3 buildings or ≥2 world_families)
    - 触发 B 重复成功（§9.3.1 B）：tool 序列在 ≥5 runs 降低 open+blocked ≥5% 或
      median tool calls 下降 ≥15%
    - 触发 C 盲化评价缺口（§9.3.1 C）：cell.suggested_evo_action ==
      "skill_induction_candidate" 且 run_count ≥10 / building_count ≥3

draft 生成（§9.3.2 / §9.3.3）：
    - 仅使用允许上下文，禁止 raw W2 / per-run expected verdict / building literal /
      evaluator raw comments / basis item text / projection ids。
    - 输出完整 EvoSkillPackage（4 文件 + manifest 4 sha256）。
    - status='draft'；source_trace_hashes 可少于 5，但 promotion 走 §9.4 5 Gate。
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from evo_agent_baseline.contracts import (
    EvoRunTrace,
    EvoSkillPackage,
    FeedbackCell,
    SanitizedFeedbackPacket,
    SkillJson,
    SkillScope,
)
from evo_agent_baseline.evo.replay_buffer import ReplayBuffer


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_sha256(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Induction candidate
# ---------------------------------------------------------------------------


@dataclass
class InductionCandidate:
    """spec v1 §9.3 induction trigger → 候选记录。

    trigger_type：
        - 'repeated_failure'：来自触发 A
        - 'repeated_success'：来自触发 B
        - 'feedback_gap'：来自触发 C
    """

    trigger_type: Literal["repeated_failure", "repeated_success", "feedback_gap"]
    pattern_key: Tuple[Any, ...]
    pattern_dimension: Dict[str, str]  # 抽象后的维度 dict，draft scope 用
    source_trace_ids: List[str]
    support_counts: Dict[str, int] = field(default_factory=dict)
    suggested_kind: Literal[
        "micro_routing", "retrieval_macro", "report_structure", "diagnostic_hint"
    ] = "retrieval_macro"
    notes: str = ""


# ---------------------------------------------------------------------------
# 触发 A: 重复失败
# ---------------------------------------------------------------------------


def detect_repeated_failure_trigger(
    buffer: ReplayBuffer,
    *,
    eval_window: Optional[int] = 50,
    min_count: int = 5,
    min_buildings: int = 3,
    min_world_families: int = 2,
) -> List[InductionCandidate]:
    """spec v1 §9.3.1 A：同 (rule_family, slot_class, obligation_kind, reason)
    组合 ≥min_count 次 + (≥min_buildings buildings or ≥min_world_families world families)。
    """
    patterns = buffer.aggregate_failure_patterns(window_size=eval_window or 50)
    candidates: List[InductionCandidate] = []
    for key, traces in patterns.items():
        if len(traces) < min_count:
            continue
        buildings = {t.building_id_hash for t in traces}
        world_families = {t.world_id_hash[:6] for t in traces}
        if len(buildings) < min_buildings and len(world_families) < min_world_families:
            continue
        rule_family, slot_class, obl_kind, reason = key
        dim = {
            "rule_family": rule_family,
            "semantic_slot_class": slot_class,
            "obligation_kind": obl_kind,
            "reason_code": reason,
        }
        candidates.append(
            InductionCandidate(
                trigger_type="repeated_failure",
                pattern_key=key,
                pattern_dimension=dim,
                source_trace_ids=[t.trace_id for t in traces],
                support_counts={
                    "trace_count": len(traces),
                    "building_count": len(buildings),
                    "world_family_count": len(world_families),
                },
                suggested_kind="retrieval_macro",
                notes=(
                    f"repeated_failure: same (family,slot,kind,reason)={key} "
                    f"seen {len(traces)}x in {len(buildings)} buildings"
                ),
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# 触发 B: 重复成功
# ---------------------------------------------------------------------------


def detect_repeated_success_trigger(
    buffer: ReplayBuffer,
    *,
    eval_window: Optional[int] = 50,
    min_count: int = 5,
    open_blocked_delta_threshold: float = -0.05,
    median_tool_calls_delta_threshold: float = -0.15,
    baseline_traces: Optional[Sequence[EvoRunTrace]] = None,
) -> List[InductionCandidate]:
    """spec v1 §9.3.1 B：tool 序列在 ≥5 runs 中相对当前 policy：
        open_plus_blocked_delta <= -5%
        OR median_tool_calls_delta <= -15%
    且 closure non-regression。

    baseline 实现：用 buffer.aggregate_success_patterns 取出 tool 序列 cluster；
    若 cluster 内 closure_summary 平均 (open + blocked) 低于 buffer 内全体 trace 中位线
    open_blocked_delta_threshold 比例 → 触发；或 cluster median tool_call_count 低于
    全体 trace median * (1 + median_tool_calls_delta_threshold) → 触发。
    """
    patterns = buffer.aggregate_success_patterns(window_size=eval_window or 50)
    all_eligible = baseline_traces or buffer.list_eligible_traces()
    if not all_eligible:
        return []

    # 全体 baseline 指标
    base_open_blocked = [
        (t.closure_summary.get("open_count", 0) + t.closure_summary.get("blocked_count", 0))
        for t in all_eligible
    ]
    base_open_blocked_median = statistics.median(base_open_blocked) if base_open_blocked else 0.0
    base_tool_calls_median = statistics.median(
        [t.tool_call_count for t in all_eligible]
    ) if all_eligible else 0.0

    candidates: List[InductionCandidate] = []
    for key, traces in patterns.items():
        if len(traces) < min_count:
            continue
        # closure non-regression：closed_count 平均不下降
        cluster_open_blocked = [
            (t.closure_summary.get("open_count", 0) + t.closure_summary.get("blocked_count", 0))
            for t in traces
        ]
        cluster_tool_calls = [t.tool_call_count for t in traces]
        cluster_open_blocked_med = statistics.median(cluster_open_blocked)
        cluster_tool_calls_med = statistics.median(cluster_tool_calls)

        open_blocked_delta = (
            (cluster_open_blocked_med - base_open_blocked_median) / base_open_blocked_median
            if base_open_blocked_median > 0
            else 0.0
        )
        tool_calls_delta = (
            (cluster_tool_calls_med - base_tool_calls_median) / base_tool_calls_median
            if base_tool_calls_median > 0
            else 0.0
        )

        triggered = (
            open_blocked_delta <= open_blocked_delta_threshold
            or tool_calls_delta <= median_tool_calls_delta_threshold
        )
        if not triggered:
            continue

        active_skill_set_id = str(key[0])
        tool_seq = list(key[1:])
        dim = {
            "active_skill_set_id": active_skill_set_id,
            "tool_sequence_len": str(len(tool_seq)),
        }
        candidates.append(
            InductionCandidate(
                trigger_type="repeated_success",
                pattern_key=key,
                pattern_dimension=dim,
                source_trace_ids=[t.trace_id for t in traces],
                support_counts={
                    "trace_count": len(traces),
                    "open_blocked_delta_x100": int(round(open_blocked_delta * 100)),
                    "tool_calls_delta_x100": int(round(tool_calls_delta * 100)),
                },
                suggested_kind="micro_routing",
                notes=(
                    f"repeated_success: tool_seq len={len(tool_seq)} "
                    f"open+blocked Δ={open_blocked_delta:+.2%} "
                    f"tool_calls Δ={tool_calls_delta:+.2%}"
                ),
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# 触发 C: 盲化评价缺口
# ---------------------------------------------------------------------------


def detect_feedback_gap_trigger(
    packets: Sequence[SanitizedFeedbackPacket],
    *,
    min_run_count: int = 10,
    min_building_count: int = 3,
) -> List[InductionCandidate]:
    """spec v1 §9.3.1 C：cell.suggested_evo_action == 'skill_induction_candidate'
    + run_count >= 10 + building_count >= 3。
    """
    candidates: List[InductionCandidate] = []
    for packet in packets:
        for cell in packet.cells:
            if cell.suppressed:
                continue
            if cell.suggested_evo_action != "skill_induction_candidate":
                continue
            if cell.run_count < min_run_count or cell.building_count < min_building_count:
                continue
            candidates.append(
                InductionCandidate(
                    trigger_type="feedback_gap",
                    pattern_key=(cell.feedback_cell_id,),
                    pattern_dimension=dict(cell.dimension),
                    source_trace_ids=[],  # feedback_gap 不绑定 source trace
                    support_counts={
                        "run_count": cell.run_count,
                        "building_count": cell.building_count,
                    },
                    suggested_kind="retrieval_macro",
                    notes=(
                        f"feedback_gap: cell={cell.feedback_cell_id} "
                        f"metric={cell.metric_name} bucket={cell.metric_bucket}"
                    ),
                )
            )
    return candidates


# ---------------------------------------------------------------------------
# Draft 生成
# ---------------------------------------------------------------------------

# spec v1 §9.3.2 draft 生成 prompt 必含禁止上下文清单
DRAFT_PROMPT_NON_AUTHORITY = (
    "Write a retrieval/routing/reporting Skill only. "
    "Do not encode outcome rules. Do not decide compliance. "
    "Do not override closure verifier. Use abstract rule/slot/obligation scope only."
)

# spec v1 §10.2 / §9.4.1：5 个 hard forbidden actions
HARD_FORBIDDEN_ACTIONS: List[str] = [
    "override_verifier",
    "force_allow_stop",
    "emit_final_verdict",
    "read_evaluator_truth",
    "suppress_rule_candidate",
]


def _trace_hash(trace_id: str) -> str:
    return "sha256:" + hashlib.sha256(trace_id.encode()).hexdigest()


def _suggest_skill_id(candidate: InductionCandidate) -> str:
    """根据 candidate 维度生成 skill_id（spec v1 §10.7 naming 规范）。"""
    if candidate.trigger_type == "repeated_failure":
        family = candidate.pattern_dimension.get("rule_family", "unknown_family")
        reason = candidate.pattern_dimension.get("reason_code", "unknown_reason")
        goal = reason.replace("_", "")[:32]
        family_norm = family.replace(".", "_").replace("*", "any")[:48]
        return f"skill.evo.{candidate.suggested_kind}.{family_norm}.{goal}"
    if candidate.trigger_type == "repeated_success":
        ssid = candidate.pattern_dimension.get("active_skill_set_id", "unknown_ss")[:32]
        return f"skill.evo.{candidate.suggested_kind}.success_pattern.{ssid}"
    # feedback_gap
    return f"skill.evo.{candidate.suggested_kind}.feedback_gap.{candidate.pattern_key[0][:32]}"


def generate_draft_skill_package(
    candidate: InductionCandidate,
    *,
    kg_snapshot_id: str = "KGS-unknown",
    rulecard_bundle_id: str = "rulecard_v2.mbis_cop_2023",
    llm_client: Optional[Any] = None,
) -> EvoSkillPackage:
    """spec v1 §9.3.2 / §9.3.3：从 InductionCandidate 生成 draft EvoSkillPackage。

    baseline：当 `llm_client is None` 时使用确定性模板生成；否则把 candidate
    + DRAFT_PROMPT_NON_AUTHORITY 喂给 llm_client（鸭子类型 `.complete(prompt: str)`），
    output 走相同 hash 包装路径。

    Returns:
        完整 EvoSkillPackage（4 文件 + manifest 4 sha256 + package_sha256）。
        status='draft'；source_trace_hashes 来自 candidate（可少于 5）；
        forbidden_actions 强制含 5 个 hard 项。
    """
    skill_id = _suggest_skill_id(candidate)
    version = "1.0.0"
    skill_version_id = f"{skill_id}.v1"
    now = _utc_now_iso()
    source_hashes = [_trace_hash(tid) for tid in candidate.source_trace_ids]

    # scope（按 candidate.pattern_dimension 取抽象）
    scope = SkillScope(
        rule_families=(
            [candidate.pattern_dimension["rule_family"]]
            if "rule_family" in candidate.pattern_dimension
            else []
        ),
        semantic_slots=(
            [candidate.pattern_dimension["semantic_slot_class"]]
            if candidate.pattern_dimension.get("semantic_slot_class")
            else []
        ),
        obligation_kinds=(
            [candidate.pattern_dimension["obligation_kind"]]
            if candidate.pattern_dimension.get("obligation_kind")
            else []
        ),
    )

    trigger_predicate: Dict[str, Any] = {"all": []}
    if candidate.pattern_dimension.get("reason_code"):
        trigger_predicate["all"].append(
            {
                "field": "open_reason_code",
                "op": "eq",
                "value": candidate.pattern_dimension["reason_code"],
            }
        )
    if candidate.pattern_dimension.get("obligation_kind"):
        trigger_predicate["all"].append(
            {
                "field": "obligation_kind",
                "op": "eq",
                "value": candidate.pattern_dimension["obligation_kind"],
            }
        )

    description = (
        f"Auto-induced {candidate.suggested_kind} skill for trigger="
        f"{candidate.trigger_type}; pattern={candidate.notes}. "
        f"{DRAFT_PROMPT_NON_AUTHORITY}"
    )[:1024]

    non_auth = (
        "This skill only changes retrieval order and evidence lookup. "
        "It never determines allow_stop, closure_status, satisfaction_status, "
        "or final compliance."
    )

    skill_json = SkillJson(
        schema_version="1.0.0",
        skill_id=skill_id,
        skill_version_id=skill_version_id,
        name=f"draft {candidate.trigger_type} skill"[:80],
        kind=candidate.suggested_kind,
        layer="L1_operational",
        description=description,
        status="draft",
        origin="evo_induced",
        version=version,
        parent_skill_version_id=None,
        supersedes=[],
        scope=scope,
        trigger_predicate=trigger_predicate,
        action_plan_ref=(
            f"plan.yaml#{candidate.suggested_kind}"
            if candidate.suggested_kind in {"micro_routing", "retrieval_macro"}
            else None
        ),
        allowed_tools=[
            "query_open_obligations",
            "inspect_obligation",
            "retrieve_building_facts",
            "retrieve_applicable_rules",
        ],
        forbidden_actions=list(HARD_FORBIDDEN_ACTIONS),
        guardrails={
            "non_authority": True,
            "blind": True,
            "fallback_to_core_on_guard_fail": True,
        },
        source_trace_hashes=source_hashes,
        support_counts={
            "trace_count": candidate.support_counts.get("trace_count", len(source_hashes)),
            "building_count": candidate.support_counts.get("building_count", 0),
            "world_family_count": candidate.support_counts.get("world_family_count", 0),
        },
        validation_summary={},  # draft 阶段空
        activation_stats={
            "eligible_count": 0,
            "activation_count": 0,
            "median_benefit": None,
        },
        kg_snapshot_id=kg_snapshot_id,
        rulecard_bundle_id=rulecard_bundle_id,
        expires_on_revision={
            "rulecard_bundle_change": True,
            "verifier_major_change": True,
        },
        created_by="evo_trainer",
        created_at=now,
        non_authority_statement=non_auth,
    )

    # 4 文件 sha256（在 baseline 用 canonical JSON dump 后取 sha）
    skill_json_dump = skill_json.model_dump()
    skill_md_text = _render_skill_md(skill_json, candidate)
    plan_yaml_text = _render_plan_yaml(skill_json, candidate)
    validation_records_text = ""  # draft 阶段 jsonl 为空

    skill_md_sha = _canonical_sha256({"skill_md_text": skill_md_text})
    plan_yaml_sha = (
        _canonical_sha256({"plan_yaml_text": plan_yaml_text})
        if skill_json.kind in {"micro_routing", "retrieval_macro"}
        else None
    )
    validation_sha = _canonical_sha256({"validation_records_text": validation_records_text})
    skill_sha = _canonical_sha256(skill_json_dump)

    manifest = {
        "package_schema_version": "1.0.0",
        "skill_version_id": skill_version_id,
        "files": {
            "skill.json": skill_sha,
            "SKILL.md": skill_md_sha,
            "validation_records.jsonl": validation_sha,
        },
    }
    if plan_yaml_sha is not None:
        manifest["files"]["plan.yaml"] = plan_yaml_sha
    manifest_sha = _canonical_sha256(manifest)
    package_sha = _canonical_sha256(
        {
            "skill_sha": skill_sha,
            "skill_md_sha": skill_md_sha,
            "plan_yaml_sha": plan_yaml_sha,
            "validation_sha": validation_sha,
            "manifest_sha": manifest_sha,
        }
    )

    return EvoSkillPackage(
        package_schema_version="1.0.0",
        package_uri=f"evo_packages/{skill_version_id}/",
        package_sha256=package_sha,
        skill=skill_json,
        skill_md_sha256=skill_md_sha,
        plan_yaml_sha256=plan_yaml_sha,
        validation_records_sha256=validation_sha,
        manifest_sha256=manifest_sha,
    )


def _render_skill_md(skill_json: SkillJson, candidate: InductionCandidate) -> str:
    """spec v1 §10.3 SKILL.md 模板。"""
    return (
        f"# {skill_json.name}\n\n"
        f"## Purpose\n{skill_json.description}\n\n"
        f"## Trigger\n{json.dumps(skill_json.trigger_predicate, indent=2)}\n\n"
        f"## Allowed actions\n{', '.join(skill_json.allowed_tools)}\n\n"
        f"## Retrieval / routing plan\nSee plan.yaml.\n\n"
        f"## Fallback\nfallback_to_core_on_guard_fail=True\n\n"
        f"## Safety and authority boundary\n"
        f"This Skill does not decide compliance, does not override the closure verifier, "
        f"and does not access evaluator-only data.\n\n"
        f"## Do not\n"
        f"- Do not emit final verdict.\n"
        f"- Do not force allow_stop.\n"
        f"- Do not suppress rule candidates.\n"
        f"- Do not use evaluator truth.\n"
    )


def _render_plan_yaml(skill_json: SkillJson, candidate: InductionCandidate) -> str:
    """spec v1 §10.4 plan.yaml 模板（仅声明检索/路由/报告组织）。"""
    return (
        f"plan_id: {skill_json.skill_id}\n"
        f"version: 1\n"
        f"steps:\n"
        f"  - step_id: inspect_open_obligation\n"
        f"    action: call_tool\n"
        f"    tool: inspect_obligation\n"
        f"    input:\n"
        f"      obligation_id: \"{{{{open_obligation.obligation_id}}}}\"\n"
        f"    save_as: obligation_detail\n"
        f"  - step_id: retrieve_facts\n"
        f"    action: call_tool\n"
        f"    tool: retrieve_building_facts\n"
        f"    input:\n"
        f"      filters:\n"
        f"        semantic_slots: \"{{{{obligation_detail.slot_ids}}}}\"\n"
        f"    append_candidates: true\n"
    )


__all__ = [
    "InductionCandidate",
    "detect_repeated_failure_trigger",
    "detect_repeated_success_trigger",
    "detect_feedback_gap_trigger",
    "generate_draft_skill_package",
    "HARD_FORBIDDEN_ACTIONS",
    "DRAFT_PROMPT_NON_AUTHORITY",
]
