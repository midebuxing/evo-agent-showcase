"""W0 worldgen sidecar 派生层（spec 09 §1.2 双路径派生层，静态）.

现状（2026-05-09 修订后）：
    sidecar bundle 由 worldgen 在同一 pipeline 自家生成，**不依赖任何外部 admin record**。
    数值类 slot facts 按 sidecar_measurement_registry.recommended_distribution 采样；
    bool / categorical slot 按 sidecar_bool_slot_registry + conditional_eval 派生。
    按 carrier_domain 派发到 procedure_gate_state / supervision_runtime_state /
    artifact_requirement_state / facts 桶。

    一切 generator 数据源都在静态 registry 内，**不接收 runtime 调参输入**。

历史 trailing note（spec 09 §1 历史背景，已 2026-05-09 废止）：
    早期 mvp 蓝图曾设计 W0-only / with-sidecar 双 mode + SidecarInput / sidecar_inputs
    外部注入接口 + marker.sidecar_missing + _detect_worldgen_owned_slot_intrusions
    防入侵机制；2026-05-09 spec 09 修订统一为静态派生路径，全部移除。
"""

from __future__ import annotations

import contextlib
import random
from contextvars import ContextVar, Token
from typing import Any, Dict, Iterator, List, Optional, Tuple

from workflow_engine.worldgen.conditional_eval import (
    HIDDEN_STATE_PRIOR_MEANS,
    build_evaluator_context,
    evaluate_bool_conditional,
    evaluate_enum_conditional,
)
from workflow_engine.worldgen.constants import (
    SOURCE_DOCUMENTS,
    _utc_now_iso,
)
from workflow_engine.worldgen.models import (
    RegistryBundle,
    SidecarRuntimeBundle,
    SidecarRuntimeRecord,
    SidecarRuntimeValue,
)


# ---------- W1-012 sidecar conditional fallback audit accumulator ----------
# spec 10 §6 "不允许 silent fallback" — conditional formula 异常 fallback 到 marginal
# 时记 batch 级计数（per reason class），caller wrap audit_capture_sidecar_fallback() 后
# 把 accumulator merge 进 BatchGateStats.sidecar_fallback_counts 桶.

_sidecar_fallback_ctx: ContextVar[Optional[Dict[str, int]]] = ContextVar(
    "sidecar_fallback", default=None
)


def get_sidecar_fallback_context() -> Optional[Dict[str, int]]:
    """读取 ContextVar 中 fallback counts dict；未 set 时返回 None (fast path)."""
    return _sidecar_fallback_ctx.get()


def record_sidecar_fallback(reason_code: str) -> None:
    """conditional fallback 触发时累加 +1；context 未 set 时静默 (caller 责任)."""
    counts = _sidecar_fallback_ctx.get()
    if counts is None:
        return
    counts[reason_code] = counts.get(reason_code, 0) + 1


@contextlib.contextmanager
def audit_capture_sidecar_fallback(
    accumulator: Optional[Dict[str, int]] = None,
) -> Iterator[Dict[str, int]]:
    """Context manager：set/reset sidecar fallback ContextVar.

    用法::

        with audit_capture_sidecar_fallback() as fallback_counts:
            bundle = _build_sidecar_runtime_bundle_for_buildings(...)
        batch_stats.sidecar_fallback_counts.update(fallback_counts)
    """
    if accumulator is None:
        accumulator = {}
    token: Token = _sidecar_fallback_ctx.set(accumulator)
    try:
        yield accumulator
    finally:
        _sidecar_fallback_ctx.reset(token)


# spec 09 §7.1 + §1.2：carrier_domain → SidecarRuntimeRecord 桶映射
# 数值类（sidecar_measurement_registry）+ bool/categorical（sidecar_bool_slot_registry）
# 共用同一映射表（按 carrier_domain 分发）.
# - procedure (deadlines / appointment / submission / repair completion 等程序节点)
#                                                        → procedure_gate_state
# - supervision (site visit / record retention)          → supervision_runtime_state
# - inspection_execution (coverage / sampling / check)   → supervision_runtime_state
#                                                          监管动作的数值参数，归 supervision 桶
# - artifact (forms / reports / proposals / records / photos / certificates / statements)
#                                                        → artifact_requirement_state
# - qualifier (qual.actor_role / method_class / artifact_field_group)
#                                                        → facts (跨桶通用 qualifier)
# - fire_safety (fire_safety.upgrade_outstanding，spec 09 §1.1.2 新归位 B 类)
#                                                        → procedure_gate_state
#                                                          (statutory order 是 procedural 状态)
# W1-008：当前 sidecar_measurement_registry / sidecar_bool_slot_registry **没有**
# carrier_domain="completion" 的 slot record (artifact.report.completion.* slot 当前都标
# carrier_domain="artifact")；mapping 表预留 "completion" → "completion_runtime_state" 入口
# 是为兼容 future slot 扩展 (若后续 spec 把 completion 单独切 carrier_domain 出来) +
# 防 fallback 路由 (避免任何 slot 误命中 .get(carrier_domain, "facts") 落到 facts 桶).
# completion_runtime_state 桶在 SidecarRuntimeRecord 已存在 (models.py:602)；当前批次产出该
# 桶仍为空 list 属预期态.
_CARRIER_DOMAIN_TO_BUCKET: Dict[str, str] = {
    "procedure": "procedure_gate_state",
    "supervision": "supervision_runtime_state",
    "inspection_execution": "supervision_runtime_state",
    "artifact": "artifact_requirement_state",
    "qualifier": "facts",
    "fire_safety": "procedure_gate_state",
    "completion": "completion_runtime_state",
}

# EXP-011 设计④：程序阶段蕴含约束（后置 gate ⇒ 前置 gate）。依据 MBIS CoP 流程链
# （提名→终止；调查意向→建议→认可→启动；修葺开工→竣工→完工复验）。后置采样为
# True 而其已采样前置为 False 时钳为 False——消除"竣工未开工"类矛盾楼。生效前提
# "前置先采"已核：六对的 DAG sampling_order 全部满足（3<4 / 14<16 / 16<18 / 18<19 /
# 25<36 / 36<37），零 registry 改动。前置缺失/未采样时不钳（保守 no-op）。
# codex 审查后默认关闭（见 clamp 应用处注释）；启用前须过"法规依据+统计+再标定"三关。
_ENABLE_STAGE_IMPLICATION_CLAMP = False

_PROCEDURE_STAGE_PREREQS: Dict[str, Tuple[str, ...]] = {
    "procedure.repair.prescribed.completed": (
        "procedure.repair.prescribed.started",
    ),
    "procedure.temp_ri_nomination.terminated": (
        "procedure.temp_ri_nomination.completed",
    ),
    "procedure.investigation.proposal.submitted": (
        "procedure.investigation.intention_notified",
    ),
    "procedure.investigation.proposal.recognized": (
        "procedure.investigation.proposal.submitted",
    ),
    "procedure.investigation.started": (
        "procedure.investigation.proposal.recognized",
    ),
    "procedure.completed_work.final_inspection_performed": (
        "procedure.repair.prescribed.completed",
    ),
}


def _collect_sidecar_measurement_slots(
    registries: Optional[RegistryBundle],
) -> List[Dict[str, Any]]:
    """提取 sidecar_measurement_registry 的所有 numeric slot records.

    registries 为 None 时返回空 list（worldgen pipeline 必传；None 仅供 unit test 便利）。
    """
    if registries is None:
        return []
    for registry in registries.registries:
        if registry.registry_id == "sidecar_measurement_registry":
            return list(registry.records)
    return []


def _collect_sidecar_bool_slots(
    registries: Optional[RegistryBundle],
) -> List[Dict[str, Any]]:
    """提取 sidecar_bool_slot_registry 的所有 bool / categorical slot records.

    spec 02 §1 第 19 张 registry / spec 09 §1.2 双路径修订（2026-05-09）.
    """
    if registries is None:
        return []
    for registry in registries.registries:
        if registry.registry_id == "sidecar_bool_slot_registry":
            return list(registry.records)
    return []


def _sample_sidecar_facts_for_fragment(
    building_world_id: str,
    fragment_id: str,
    sidecar_slot_records: List[Dict[str, Any]],
    rng: random.Random,
) -> Dict[str, List[SidecarRuntimeValue]]:
    """spec 09 §1.2：按 sidecar_measurement_registry 派发到 SidecarRuntimeRecord 各桶.

    返回 dict：
        facts / procedure_gate_state / supervision_runtime_state /
        artifact_requirement_state / completion_runtime_state
        → List[SidecarRuntimeValue]

    每个数值类 sidecar slot（procedure_duration / supervision_interval /
    inspection_coverage / inspection_plan）调用 generator._sample_value_for_slot。
    若 slot 含 recommended_distribution → Path A 采样；否则 fallback 走中点
    （sidecar slot 应全部填 distribution 参数；fallback 命中说明 spec 缺数据）。
    """
    # 延迟 import：generator.py 不 import sidecar.py，反向应不会循环；保守起见用延迟 import
    from workflow_engine.worldgen.generator import _sample_value_for_slot

    buckets: Dict[str, List[SidecarRuntimeValue]] = {
        "facts": [],
        "procedure_gate_state": [],
        "supervision_runtime_state": [],
        "artifact_requirement_state": [],
        "completion_runtime_state": [],
    }
    refs = [building_world_id, fragment_id]

    for slot_record in sidecar_slot_records:
        slot_id = slot_record.get("slot_id")
        if not slot_id:
            continue
        carrier_domain = str(slot_record.get("carrier_domain") or "")
        bucket_key = _CARRIER_DOMAIN_TO_BUCKET.get(carrier_domain, "facts")

        value_num, value_bool, value_enum = _sample_value_for_slot(slot_record, rng)
        if value_num is not None:
            sample_value: Any = value_num
        elif value_bool is not None:
            sample_value = value_bool
        elif value_enum is not None:
            sample_value = value_enum
        else:
            continue  # 三种 value 全 None → 不入桶（异常态，理论不应触发）

        buckets[bucket_key].append(
            SidecarRuntimeValue(
                slot_id=slot_id,
                value=sample_value,
                unit=slot_record.get("unit") or None,
                qualifiers={
                    "fragment_id": fragment_id,
                    "carrier_domain": carrier_domain,
                },
                time_anchor_key=None,
                source_refs=refs,
                notes=[
                    "sidecar 派生层采样 (spec 09 §1.2 + sidecar_measurement_registry); "
                    f"distribution={slot_record.get('recommended_distribution', 'fallback_midpoint')}"
                ],
            )
        )

    return buckets


def _sample_one_bool_slot(
    slot_record: Dict[str, Any],
    base_evaluator_ctx: Optional[Dict[str, float]],
    sidecar_upstream_state: Dict[str, Any],
    rng: random.Random,
) -> Optional[tuple]:
    """采一个 bool/enum 槽（spec 06 §11.6 双路径，从原 per-fragment 循环体抽出）。

    返回 (value, sampling_path)；缺 prevalence/enum_values 或 value_type 不识别返回 None
    （spec 09 §1.1.3 rule 4：跳过不伪造）。conditional 失败走 fallback marginal 并
    record_sidecar_fallback（spec 10 §6 silent fallback 红线）。
    """
    value_type = str(slot_record.get("value_type") or "bool").lower()
    prevalence = slot_record.get("prevalence")
    conditional_formula = slot_record.get("conditional_formula")

    if conditional_formula is not None and base_evaluator_ctx is not None:
        slot_ctx = dict(base_evaluator_ctx)
        for up_slot_id, up_val in sidecar_upstream_state.items():
            if isinstance(up_val, bool):
                slot_ctx[up_slot_id] = 1.0 if up_val else 0.0
            elif isinstance(up_val, (int, float)):
                slot_ctx[up_slot_id] = float(up_val)
            elif isinstance(up_val, str):
                slot_ctx[up_slot_id] = 1.0 if up_val else 0.0
        try:
            if value_type == "bool":
                return (
                    bool(evaluate_bool_conditional(conditional_formula, slot_ctx, rng)),
                    "conditional",
                )
            if value_type == "enum":
                return (
                    evaluate_enum_conditional(conditional_formula, slot_ctx, rng),
                    "conditional",
                )
            return None
        except (ValueError, KeyError, TypeError) as exc:
            reason_code = type(exc).__name__
            record_sidecar_fallback(reason_code)
            value = _marginal_sample(value_type, prevalence, slot_record, rng)
            if value is None:
                return None
            return (value, f"conditional_fallback_marginal(reason={reason_code})")
    value = _marginal_sample(value_type, prevalence, slot_record, rng)
    if value is None:
        return None
    return (value, "marginal")


def _resolve_building_upstream(
    up_slot_id: str,
    building_state: Dict[str, Any],
    frag_states: Dict[str, Dict[str, Any]],
    granularity_by_slot: Dict[str, str],
    aggregation_table: Dict[str, str],
) -> Optional[Any]:
    """楼级槽的上游解析（spec 草案·流程槽粒度语义 §3.4）。

    building 上游 → 楼级缓存值；fragment 上游 → 按 BUILDING_READING_AGGREGATION
    聚合各 fragment 已采值；fragment 上游无聚合声明 → 抛 ValueError fail-fast
    （禁静默漏边，codex 二审 d 项的机器保证）。非 sidecar 槽（物理输入）返回 None
    交楼级 context 处理。
    """
    if up_slot_id in building_state:
        return building_state[up_slot_id]
    gran = granularity_by_slot.get(up_slot_id)
    if gran is None:
        return None  # 不是 sidecar bool 槽（物理/H.* 输入），由 context 或 fallback 兜底
    if gran == "building":
        return None  # building 槽但尚未采样（拓扑序应保证；缺失走 fallback）
    vals = [
        st[up_slot_id] for st in frag_states.values() if up_slot_id in st
    ]
    bool_vals = [v for v in vals if isinstance(v, bool)]
    if not bool_vals:
        return None
    agg = aggregation_table.get(up_slot_id)
    if agg is None:
        raise ValueError(
            f"cross-granularity upstream {up_slot_id!r} has no declared "
            "building-reading aggregation (BUILDING_READING_AGGREGATION)"
        )
    if agg == "all_true":
        return all(bool_vals)
    if agg == "any_true":
        return any(bool_vals)
    raise ValueError(f"unknown aggregation {agg!r} for {up_slot_id!r}")


def _sample_sidecar_bool_slots_for_building(
    building_world_id: str,
    fragment_ids: List[str],
    sidecar_bool_slot_records: List[Dict[str, Any]],
    rng: random.Random,
    per_fragment_contexts: Dict[str, Optional[Dict[str, float]]],
    building_context: Optional[Dict[str, float]] = None,
) -> tuple:
    """spec 草案·流程槽粒度语义 §3.4：按全局拓扑序逐槽、粒度两相分派采样。

    - granularity=building 槽：一栋一抽（上游：楼级缓存 + fragment 值按声明聚合；
      公式引用楼级 context 缺失的输入时走既有 conditional fallback，诚实计数）；
    - granularity=fragment 槽（缺省）：逐 fragment 抽，building 上游经楼级缓存广播；
    - AGGREGATE_ROW_SLOTS 四槽在全 fragment 采完后追加楼级聚合行
      （qualifiers 标 {"aggregation": "building"}，闭包 fragment 作用域按此排除）。

    返回 (bool_buckets_by_fragment, building_values_by_bucket)。
    既有钳制语义保持：completed_and_retained 联合上界 / assigned_role planned 钳
    ——prereq 读数走 fragment 本地 + 楼级缓存合并视图。
    """
    from .registry import AGGREGATE_ROW_SLOTS, BUILDING_READING_AGGREGATION

    def _empty_buckets() -> Dict[str, List[SidecarRuntimeValue]]:
        return {
            "facts": [],
            "procedure_gate_state": [],
            "supervision_runtime_state": [],
            "artifact_requirement_state": [],
            "completion_runtime_state": [],
        }

    buckets_by_fragment: Dict[str, Dict[str, List[SidecarRuntimeValue]]] = {
        fid: _empty_buckets() for fid in fragment_ids
    }
    building_buckets: Dict[str, List[SidecarRuntimeValue]] = _empty_buckets()

    ordered_records = sorted(
        sidecar_bool_slot_records,
        key=lambda r: (
            r.get("sampling_order") if r.get("sampling_order") is not None else 9999,
            str(r.get("slot_id") or ""),
        ),
    )
    granularity_by_slot = {
        str(r.get("slot_id")): str(r.get("granularity") or "fragment")
        for r in ordered_records
        if r.get("slot_id")
    }

    building_state: Dict[str, Any] = {}
    frag_states: Dict[str, Dict[str, Any]] = {fid: {} for fid in fragment_ids}
    building_base_ctx = dict(building_context) if building_context else None

    def _apply_clamps(
        slot_id: str, sample_value: Any, sampling_path: str, seen: Dict[str, Any]
    ) -> tuple:
        # supervision.record.completed_and_retained 联合上界（spec 06 §11.6.7）。
        if slot_id == "supervision.record.completed_and_retained" and isinstance(
            sample_value, bool
        ):
            completed = seen.get("supervision.record.completed")
            retained = seen.get("supervision.record.retained")
            if isinstance(completed, bool) and isinstance(retained, bool):
                joint_bound = bool(completed) and bool(retained)
                if sample_value and not joint_bound:
                    return False, sampling_path + "+post_sample_clamp"
        # EXP-011 设计①配套：代表未规划 ⇒ 不可能已指派。
        if (
            slot_id == "actor.representative.assigned_role"
            and isinstance(sample_value, str)
            and sample_value != "none"
        ):
            planned = seen.get("procedure.supervision_representative.planned")
            if isinstance(planned, bool) and not planned:
                return "none", sampling_path + "+stage_implication_clamp"
        return sample_value, sampling_path

    def _emit(
        target: Dict[str, List[SidecarRuntimeValue]],
        slot_record: Dict[str, Any],
        sample_value: Any,
        sampling_path: str,
        qualifiers: Dict[str, Any],
        refs: List[str],
    ) -> None:
        carrier_domain = str(slot_record.get("carrier_domain") or "")
        bucket_key = _CARRIER_DOMAIN_TO_BUCKET.get(carrier_domain, "facts")
        target[bucket_key].append(
            SidecarRuntimeValue(
                slot_id=str(slot_record.get("slot_id")),
                value=sample_value,
                qualifiers=qualifiers,
                time_anchor_key=None,
                source_refs=refs,
                notes=[
                    "sidecar 派生层 bool/categorical 采样 (spec 09 §1.2 + 粒度两相分派); "
                    f"value_type={slot_record.get('value_type')}, path={sampling_path}, "
                    f"prevalence={slot_record.get('prevalence')}, "
                    f"sampling_order={slot_record.get('sampling_order')}"
                ],
            )
        )

    for slot_record in ordered_records:
        slot_id = str(slot_record.get("slot_id") or "")
        if not slot_id:
            continue
        carrier_domain = str(slot_record.get("carrier_domain") or "")
        granularity = granularity_by_slot.get(slot_id, "fragment")

        if granularity == "building":
            # 楼级上游 context：building base + 已采楼级槽 + fragment 上游聚合值。
            upstream: Dict[str, Any] = dict(building_state)
            for up_id in slot_record.get("conditional_inputs") or []:
                resolved = _resolve_building_upstream(
                    str(up_id), building_state, frag_states,
                    granularity_by_slot, BUILDING_READING_AGGREGATION,
                )
                if resolved is not None:
                    upstream[str(up_id)] = resolved
            sampled = _sample_one_bool_slot(
                slot_record, building_base_ctx, upstream, rng
            )
            if sampled is None:
                continue
            sample_value, sampling_path = sampled
            sample_value, sampling_path = _apply_clamps(
                slot_id, sample_value, sampling_path, building_state
            )
            building_state[slot_id] = sample_value
            _emit(
                building_buckets, slot_record, sample_value, sampling_path,
                qualifiers={
                    "carrier_domain": carrier_domain,
                    "granularity": "building",
                },
                refs=[building_world_id],
            )
        else:
            for fid in fragment_ids:
                # fragment 上游 = 本 fragment 已采值 + 楼级缓存广播。
                upstream = dict(building_state)
                upstream.update(frag_states[fid])
                sampled = _sample_one_bool_slot(
                    slot_record, per_fragment_contexts.get(fid), upstream, rng
                )
                if sampled is None:
                    continue
                sample_value, sampling_path = sampled
                merged_seen = dict(building_state)
                merged_seen.update(frag_states[fid])
                sample_value, sampling_path = _apply_clamps(
                    slot_id, sample_value, sampling_path, merged_seen
                )
                frag_states[fid][slot_id] = sample_value
                _emit(
                    buckets_by_fragment[fid], slot_record, sample_value,
                    sampling_path,
                    qualifiers={
                        "fragment_id": fid,
                        "carrier_domain": carrier_domain,
                    },
                    refs=[building_world_id, fid],
                )

    # §3.2 四槽楼级聚合行（生成侧派生，检索零改动）。
    record_by_slot = {str(r.get("slot_id")): r for r in ordered_records if r.get("slot_id")}
    for slot_id in AGGREGATE_ROW_SLOTS:
        vals = [
            st[slot_id] for st in frag_states.values() if slot_id in st
        ]
        bool_vals = [v for v in vals if isinstance(v, bool)]
        if not bool_vals:
            continue
        agg = BUILDING_READING_AGGREGATION[slot_id]
        agg_value = all(bool_vals) if agg == "all_true" else any(bool_vals)
        slot_record = record_by_slot.get(slot_id) or {"slot_id": slot_id,
                                                      "carrier_domain": "procedure"}
        _emit(
            building_buckets, slot_record, agg_value, f"building_aggregate({agg})",
            qualifiers={
                "aggregation": "building",
                "carrier_domain": str(slot_record.get("carrier_domain") or ""),
            },
            refs=[building_world_id],
        )

    return buckets_by_fragment, building_buckets


def _sample_sidecar_bool_slots_for_fragment(
    building_world_id: str,
    fragment_id: str,
    sidecar_bool_slot_records: List[Dict[str, Any]],
    rng: random.Random,
    evaluator_context: Optional[Dict[str, float]] = None,
) -> Dict[str, List[SidecarRuntimeValue]]:
    """spec 09 §1.2 + sidecar_bool_slot_registry：bool / categorical slot 采样.

    DEBT-020 Round 6 + Round 7 (2026-05-11): conditional_formula 改成 centered upstream
    pattern (spec 06 §11.6.1)，按 sampling_order 拓扑顺序采样，已采样的 sidecar slot
    作为后续 slot 的 upstream input.

    双路径（spec 06 §11.6.3）：

    1. **conditional_formula 不为 None** → 走 conditional path:
       - bool: sigmoid(logit(anchor) + Σ coef*(upstream-upstream_expected)) 中心化条件采样
       - enum: per-class softmax(log(anchor)+Σ coef*(upstream-upstream_expected)) → multinomial
       evaluator_context 由 caller 从 WorldBundle 物理 state 构造（H.* hidden state +
       physical state；详见 conditional_eval.py ALLOWED_INPUTS）.
       sampling 按 sampling_order 拓扑顺序，已采样的 sidecar slot 通过 sidecar_upstream
       注入 evaluator context，供后续 slot 的 centered upstream 公式使用.

    2. **conditional_formula = None** → 走 marginal path:
       Bool slot：rng.random() < prevalence → True / False
       Enum slot：rng.choices(enum_values, weights=prevalence)[0]

    Post-sample consistency (spec 06 §11.6.7):
       supervision.record.completed_and_retained 不应 > min(completed, retained).
       单个 fragment Bernoulli 上理论可能 > min；这里强制 clamp.

    缺 prevalence / enum_values 的 slot 跳过、不伪造（spec 09 §1.1.3 rule 4）.
    """
    buckets: Dict[str, List[SidecarRuntimeValue]] = {
        "facts": [],
        "procedure_gate_state": [],
        "supervision_runtime_state": [],
        "artifact_requirement_state": [],
        "completion_runtime_state": [],
    }
    refs = [building_world_id, fragment_id]

    # DEBT-020 Round 6 §1.3 sampling_order: 按 sampling_order 升序遍历 (None 排末尾,
    # marginal-only 兼容). 这样 centered upstream 公式 read 到的 sidecar upstream slot 都已采样.
    ordered_records = sorted(
        sidecar_bool_slot_records,
        key=lambda r: (
            r.get("sampling_order") if r.get("sampling_order") is not None else 9999,
            str(r.get("slot_id") or ""),
        ),
    )

    # DEBT-020 Round 6 §1.2: 已采样的 sidecar slot value 累积到 sidecar_upstream_state
    # (slot_id → 0/1 bool 或 enum class str). 后续 slot evaluator context 包含此 state
    # 通过 build_evaluator_context(sidecar_upstream=...) 注入.
    sidecar_upstream_state: Dict[str, Any] = {}
    sampled_slot_value: Dict[str, Any] = {}  # 用于 post-sample consistency clamp

    base_evaluator_ctx = dict(evaluator_context) if evaluator_context else None

    for slot_record in ordered_records:
        slot_id = slot_record.get("slot_id")
        if not slot_id:
            continue
        carrier_domain = str(slot_record.get("carrier_domain") or "")
        bucket_key = _CARRIER_DOMAIN_TO_BUCKET.get(carrier_domain, "facts")
        value_type = str(slot_record.get("value_type") or "bool").lower()
        prevalence = slot_record.get("prevalence")
        conditional_formula = slot_record.get("conditional_formula")

        sampled = _sample_one_bool_slot(
            slot_record, base_evaluator_ctx, sidecar_upstream_state, rng
        )
        if sampled is None:
            continue
        sample_value, sampling_path = sampled

        # DEBT-020 Round 6 §1.2 post-sample consistency clamp:
        # supervision.record.completed_and_retained 不应 > min(completed, retained)
        if slot_id == "supervision.record.completed_and_retained" and isinstance(sample_value, bool):
            completed = sampled_slot_value.get("supervision.record.completed")
            retained = sampled_slot_value.get("supervision.record.retained")
            if isinstance(completed, bool) and isinstance(retained, bool):
                # logical conjunction upper bound: 若 completed 或 retained 为 False, joint 必须 False
                joint_bound = bool(completed) and bool(retained)
                if sample_value and not joint_bound:
                    sample_value = False
                    sampling_path = sampling_path + "+post_sample_clamp"

        # EXP-011 设计④：程序阶段蕴含 clamp——后置 gate=True 但已采样前置=False 时钳 False。
        # codex 审查（2026-07-02）：六对钳制对既有 slot 边际分布冲击超预期（离线估算
        # investigation.submitted -39/200 等）且两对缺条款级依据——按"先不并入主口径"
        # 意见默认关闭；待补法规依据 + post-clamp 统计 + 边际再标定后启用（EXP-011 尾巴）。
        if _ENABLE_STAGE_IMPLICATION_CLAMP and isinstance(sample_value, bool) and sample_value:
            for prereq in _PROCEDURE_STAGE_PREREQS.get(slot_id, ()):
                upstream_val = sampled_slot_value.get(prereq)
                if isinstance(upstream_val, bool) and not upstream_val:
                    sample_value = False
                    sampling_path = sampling_path + "+stage_implication_clamp"
                    break

        # EXP-011 设计①配套：代表未规划 ⇒ 不可能已指派（enum 钳回 'none'）。
        if (
            slot_id == "actor.representative.assigned_role"
            and isinstance(sample_value, str)
            and sample_value != "none"
        ):
            planned = sampled_slot_value.get(
                "procedure.supervision_representative.planned"
            )
            if isinstance(planned, bool) and not planned:
                sample_value = "none"
                sampling_path = sampling_path + "+stage_implication_clamp"

        sampled_slot_value[slot_id] = sample_value
        sidecar_upstream_state[slot_id] = sample_value

        buckets[bucket_key].append(
            SidecarRuntimeValue(
                slot_id=slot_id,
                value=sample_value,
                qualifiers={
                    "fragment_id": fragment_id,
                    "carrier_domain": carrier_domain,
                },
                time_anchor_key=None,
                source_refs=refs,
                notes=[
                    "sidecar 派生层 bool/categorical 采样 (spec 09 §1.2 + sidecar_bool_slot_registry); "
                    f"value_type={value_type}, path={sampling_path}, prevalence={prevalence}, "
                    f"sampling_order={slot_record.get('sampling_order')}"
                ],
            )
        )

    return buckets


def _marginal_sample(
    value_type: str,
    prevalence: Any,
    slot_record: Dict[str, Any],
    rng: random.Random,
) -> Any:
    """marginal-only fallback 采样：bool 走 Bernoulli(prevalence)；enum 走 multinomial(prevalence)。

    缺 prevalence / enum_values → 返回 None（caller 跳过该 slot）.
    """
    if value_type == "bool":
        if not isinstance(prevalence, (int, float)):
            return None
        p = max(0.0, min(1.0, float(prevalence)))
        return bool(rng.random() < p)
    if value_type == "enum":
        enum_values = slot_record.get("enum_values") or []
        if not enum_values:
            return None
        if isinstance(prevalence, list) and len(prevalence) == len(enum_values):
            weights = [max(0.0, float(w)) for w in prevalence]
            if sum(weights) <= 0:
                weights = [1.0] * len(enum_values)
            return rng.choices(enum_values, weights=weights, k=1)[0]
        return rng.choices(enum_values, k=1)[0]
    return None


def _merge_buckets(
    target: Dict[str, List[SidecarRuntimeValue]],
    source: Dict[str, List[SidecarRuntimeValue]],
) -> None:
    """In-place 合并两个桶 dict (numeric + bool 采样结果合并)."""
    for key, values in source.items():
        if key not in target:
            target[key] = list(values)
        else:
            target[key].extend(values)


def _build_sidecar_record_for_fragment(
    building_world_id: str,
    fragment_id: str,
    sidecar_slot_records: List[Dict[str, Any]],
    sidecar_bool_slot_records: List[Dict[str, Any]],
    rng: random.Random,
    projection_id: str = "",
    expected_interface_ids: Optional[List[str]] = None,
    evaluator_context: Optional[Dict[str, float]] = None,
    pre_sampled_bool_buckets: Optional[Dict[str, List[SidecarRuntimeValue]]] = None,
) -> SidecarRuntimeRecord:
    """spec 09 §1.2 sidecar 派生层入口（per fragment）— 双路径采样.

    无 W0-only / with-sidecar 分叉；从两张 registry 采样合并：
      - sidecar_measurement_registry → numeric slot (duration / ratio / count / length / time)
      - sidecar_bool_slot_registry → bool / categorical slot
        (procedure.* / artifact.* / supervision.* / qual.* / fire_safety.*)

    缺 prevalence 或 enum_values 的 bool slot 跳过、不伪造（符合 spec 09 §1.1.3 rule 4）.

    evaluator_context: spec 06 §11.6 conditional_formula 评估器输入（per fragment）.
        None → bool/enum slot 走 marginal-only fallback（pre-Round5 行为）.
    """
    numeric_buckets = _sample_sidecar_facts_for_fragment(
        building_world_id=building_world_id,
        fragment_id=fragment_id,
        sidecar_slot_records=sidecar_slot_records,
        rng=rng,
    )
    # 粒度两相分派（spec 草案·流程槽粒度语义 §3.4）：主管线由楼级编排器预采
    # bool 槽后传入；未传（旧调用/单测路径）退回 per-fragment 采样（全槽按
    # fragment 粒度，兼容旧行为）。
    if pre_sampled_bool_buckets is not None:
        bool_buckets = pre_sampled_bool_buckets
    else:
        bool_buckets = _sample_sidecar_bool_slots_for_fragment(
            building_world_id=building_world_id,
            fragment_id=fragment_id,
            sidecar_bool_slot_records=sidecar_bool_slot_records,
            rng=rng,
            evaluator_context=evaluator_context,
        )
    _merge_buckets(numeric_buckets, bool_buckets)
    buckets = numeric_buckets

    return SidecarRuntimeRecord(
        runtime_id=f"SCR-{fragment_id}",
        world_id=building_world_id,
        projection_id=projection_id,
        interface_ids=list(expected_interface_ids or []),
        facts=buckets["facts"],
        # spec 09 §1.2 修订：废止 marker.sidecar_missing 占位 marker；
        # 派生异常时由对应 slot 输出 unknown / not_applicable，不再用桶外 marker
        runtime_markers=[],
        artifact_requirement_state=buckets["artifact_requirement_state"],
        procedure_gate_state=buckets["procedure_gate_state"],
        supervision_runtime_state=buckets["supervision_runtime_state"],
        completion_runtime_state=buckets["completion_runtime_state"],
    )


def _build_evaluator_context_for_fragment(
    building_world: Any,  # WorldBundle
    fragment: Any,  # FragmentContext
    *,
    drivers_by_fragment: Optional[Dict[str, Any]] = None,
    mechanisms_by_fragment: Optional[Dict[str, Any]] = None,
    conditions_by_fragment: Optional[Dict[str, List[Any]]] = None,
    drainage_by_fragment: Optional[Dict[str, Any]] = None,
    fire_safety_by_fragment: Optional[Dict[str, Any]] = None,
    ubw_by_fragment: Optional[Dict[str, Any]] = None,
    repair_by_fragment: Optional[Dict[str, Any]] = None,
    building_total_severity_max: Optional[float] = None,
    building_defect_count: Optional[int] = None,
) -> Dict[str, float]:
    """spec 06 §11.6 conditional_formula evaluator context for a fragment.

    从 WorldBundle 各 list（drivers / mechanisms / conditions / drainage_states /
    fire_safety_states / ubw_states / repair_assessment_states）按 fragment_id 提取，
    + building.age_years 和 building-level 聚合，组装 evaluator 输入 dict.

    DEBT-020 Round 6 (2026-05-11) 扩展：还要派生 19 个 H.* hidden state
    (admin / case / repair_need / testing_need / etc.) 注入 evaluator context.
    见 _build_round6_hidden_state_for_fragment.

    所有 lookup 缺失时安全 fallback（context 字段缺失 → evaluator 默认 0.0）.
    """
    fragment_id = getattr(fragment, "fragment_id", "")
    drivers_by_fragment = drivers_by_fragment or {}
    mechanisms_by_fragment = mechanisms_by_fragment or {}
    conditions_by_fragment = conditions_by_fragment or {}
    drainage_by_fragment = drainage_by_fragment or {}
    fire_safety_by_fragment = fire_safety_by_fragment or {}
    ubw_by_fragment = ubw_by_fragment or {}
    repair_by_fragment = repair_by_fragment or {}

    driver = drivers_by_fragment.get(fragment_id)
    mechanism = mechanisms_by_fragment.get(fragment_id)
    fragment_conditions = conditions_by_fragment.get(fragment_id, [])
    drainage = drainage_by_fragment.get(fragment_id)
    fire_safety = fire_safety_by_fragment.get(fragment_id)
    ubw = ubw_by_fragment.get(fragment_id)
    repair = repair_by_fragment.get(fragment_id)

    # building level
    building = getattr(building_world, "building", None)
    age_years = getattr(building, "age_years", None) if building is not None else None

    # driver 字段
    service_load_ratio = getattr(driver, "service_load_ratio", None) if driver else None
    restraint_level = getattr(driver, "restraint_level", None) if driver else None
    workmanship_deficit = getattr(driver, "workmanship_deficit_index", None) if driver else None
    maintenance_deficit = getattr(driver, "maintenance_deficit_index", None) if driver else None
    moisture_ingress_index = getattr(driver, "moisture_ingress_index", None) if driver else None
    chloride_exposure = getattr(driver, "chloride_exposure_index", None) if driver else None
    repair_quality_index = getattr(driver, "repair_quality_index", None) if driver else None

    # mechanism / condition severity（per fragment 多个 condition_class，按 condition_class 分桶）
    crack_severity = None
    spall_severity = None
    detachment_severity = None
    delamination_severity = None
    corrosion_severity = None
    for cond in fragment_conditions:
        cls = getattr(cond, "condition_class", "") or ""
        sev = getattr(cond, "severity_index", 0.0) or 0.0
        if cls in ("DC_CRACK",):
            crack_severity = max(crack_severity or 0.0, float(sev))
        elif cls in ("DC_SPALL_REBAR",):
            spall_severity = max(spall_severity or 0.0, float(sev))
        elif cls in ("DC_HOLLOWING",):
            delamination_severity = max(delamination_severity or 0.0, float(sev))
        elif cls in ("DC_DETACHMENT",):
            detachment_severity = max(detachment_severity or 0.0, float(sev))
    # corrosion_severity_index 来自 mechanism (corrosion_active + severity_index)
    if mechanism is not None and getattr(mechanism, "corrosion_active", False):
        corrosion_severity = float(getattr(mechanism, "severity_index", 0.0) or 0.0)

    # drainage / ubw / fire_safety
    drainage_blockage = getattr(drainage, "blockage_index", None) if drainage else None
    drainage_leakage = getattr(drainage, "leakage_index", None) if drainage else None
    public_health_risk = getattr(drainage, "public_health_risk_index", None) if drainage else None
    ubw_present = getattr(ubw, "present", None) if ubw else None
    fire_def = getattr(fire_safety, "deficiency_present", None) if fire_safety else None

    # repair
    rqi = getattr(repair, "repair_quality_index", None) if repair else repair_quality_index

    defect_present = bool(fragment_conditions) or any(
        (getattr(c, "severity_index", 0.0) or 0.0) > 0 for c in fragment_conditions
    )

    # DEBT-020 Round 6 §1.2: 派生 19 个 H.* hidden state.
    hidden_state = _build_round6_hidden_state_for_fragment(
        age_years=age_years,
        driver=driver,
        mechanism=mechanism,
        fragment_conditions=fragment_conditions,
        drainage=drainage,
        fire_safety=fire_safety,
        ubw=ubw,
        repair=repair,
        building_total_severity_max=building_total_severity_max,
        defect_present=defect_present,
        crack_severity=crack_severity,
        spall_severity=spall_severity,
        delamination_severity=delamination_severity,
        detachment_severity=detachment_severity,
        corrosion_severity=corrosion_severity,
    )

    return build_evaluator_context(
        age_years=age_years,
        service_load_ratio=service_load_ratio,
        restraint_level=restraint_level,
        workmanship_deficit=workmanship_deficit,
        maintenance_deficit=maintenance_deficit,
        moisture_ingress_index=moisture_ingress_index,
        chloride_exposure=chloride_exposure,
        crack_severity_index=crack_severity,
        spall_severity_index=spall_severity,
        corrosion_severity_index=corrosion_severity,
        delamination_severity_index=delamination_severity,
        detachment_severity_index=detachment_severity,
        drainage_blockage_index=drainage_blockage,
        drainage_leakage_index=drainage_leakage,
        public_health_risk_index=public_health_risk,
        defect_class_present=defect_present,
        ubw_alteration_present=ubw_present,
        fire_safety_deficiency_present=fire_def,
        repair_quality_index=rqi,
        building_total_severity_max=building_total_severity_max,
        building_defect_count=building_defect_count,
        hidden_state=hidden_state,
    )


def _clip01(value: float) -> float:
    """clamp to [0, 1]."""
    return max(0.0, min(1.0, float(value)))


def _build_round6_hidden_state_for_fragment(
    *,
    age_years: Optional[float],
    driver: Any,
    mechanism: Any,
    fragment_conditions: List[Any],
    drainage: Any,
    fire_safety: Any,
    ubw: Any,
    repair: Any,
    building_total_severity_max: Optional[float],
    defect_present: bool,
    crack_severity: Optional[float],
    spall_severity: Optional[float],
    delamination_severity: Optional[float],
    detachment_severity: Optional[float],
    corrosion_severity: Optional[float],
) -> Dict[str, float]:
    """DEBT-020 Round 6 §1.2 hidden state H.* 派生 (19 项).

    从 W0 generator 已采样 fragment / building / driver / mechanism / drainage /
    fire_safety / ubw / repair_assessment 状态派生. 缺数据 fallback 到 prior_means
    (HIDDEN_STATE_PRIOR_MEANS) — 保证 evaluator 不 crash 的同时 centered upstream
    offset 接近 0 (回归 marginal anchor).

    派生公式（直觉而非 spec 公式）：
      H.case_active: 当前 fragment 处在 active MBIS lifecycle (无终止) → 0.96 默认
      H.age_old_score = clip(age_years / 50, 0, 1)
      H.admin_discipline_score = 1 - maintenance_deficit (高 maintenance_deficit → 低 discipline)
      H.admin_instability_score = workmanship_deficit (proxy for admin instability)
      H.document_maturity_score = 1 - workmanship_deficit (proxy)
      H.defect_present = bool(defect_present) → 0/1
      H.defect_uncertainty: 多种 condition_class 共存或 mechanism uncertain → coarse heuristic
      H.defect_severity_score = max(per-class severity, 0)
      H.repair_need: 1 if repair.repair_required else 0 (fallback prior)
      H.repair_complexity_score: derived from defect_severity + multi-class count
      H.contractor_mobilisation_need: ~ repair_need * (1 + complexity)
      H.testing_need: ~ has corrosion or pull_test indicator from severity
      H.material_replacement_need: ~ spall_severity / detachment_severity
      H.nonconformity_risk: ~ workmanship_deficit + defect_severity
      H.repair_quality_score: repair.repair_quality_index if available
      H.fire_safety_need: fire_safety.deficiency_present → 1 else prior
      H.ubw_extra_work: ubw.present → 1 else prior
      H.drainage_issue: drainage.blockage_index / leakage_index aggregate
      H.fire_door_issue: fire_safety.deficiency_present + (component_class hint)
    """
    out: Dict[str, float] = dict(HIDDEN_STATE_PRIOR_MEANS)

    # H.case_active: assume MBIS case active when fragment present (worldgen built it)
    out["H.case_active"] = 1.0

    # H.age_old_score
    if age_years is not None:
        out["H.age_old_score"] = _clip01(float(age_years) / 50.0)

    # driver-derived admin scores
    maintenance_deficit = float(getattr(driver, "maintenance_deficit_index", 0.0) or 0.0) if driver else 0.0
    workmanship_deficit = float(getattr(driver, "workmanship_deficit_index", 0.0) or 0.0) if driver else 0.0
    if driver is not None:
        out["H.admin_discipline_score"] = _clip01(1.0 - maintenance_deficit)
        out["H.admin_instability_score"] = _clip01(workmanship_deficit)
        out["H.document_maturity_score"] = _clip01(1.0 - workmanship_deficit)

    # H.defect_present (0/1)
    out["H.defect_present"] = 1.0 if defect_present else 0.0

    # H.defect_uncertainty: count of distinct condition_class > 1 → uncertainty up
    distinct_classes = {getattr(c, "condition_class", "") or "" for c in fragment_conditions}
    distinct_classes.discard("")
    if len(distinct_classes) > 1:
        out["H.defect_uncertainty"] = _clip01(0.4 + 0.15 * (len(distinct_classes) - 1))
    elif defect_present:
        out["H.defect_uncertainty"] = 0.20
    else:
        out["H.defect_uncertainty"] = 0.10

    # H.defect_severity_score: max severity across condition / mechanism
    severities = [s for s in [crack_severity, spall_severity, delamination_severity,
                              detachment_severity, corrosion_severity] if s is not None]
    if severities:
        out["H.defect_severity_score"] = _clip01(max(severities))
    elif building_total_severity_max is not None:
        out["H.defect_severity_score"] = _clip01(float(building_total_severity_max))

    # H.repair_need: from repair_assessment or fallback to defect_severity
    repair_required = None
    if repair is not None:
        repair_required = getattr(repair, "repair_required", None)
    if repair_required is not None:
        out["H.repair_need"] = 1.0 if bool(repair_required) else 0.0
    else:
        # fallback: defect_severity > 0.4 strong proxy
        out["H.repair_need"] = _clip01(out["H.defect_severity_score"] * 1.2)

    # H.repair_complexity_score: severity + multi-class count
    out["H.repair_complexity_score"] = _clip01(
        0.4 * out["H.defect_severity_score"] + 0.15 * len(distinct_classes)
    )

    # H.contractor_mobilisation_need: repair_need * (0.5 + complexity)
    out["H.contractor_mobilisation_need"] = _clip01(
        out["H.repair_need"] * (0.5 + 0.5 * out["H.repair_complexity_score"])
    )

    # H.testing_need: corrosion or spall / delamination → testing
    if corrosion_severity is not None or spall_severity is not None:
        out["H.testing_need"] = _clip01(
            max(corrosion_severity or 0.0, spall_severity or 0.0) * 1.0
        )
    else:
        out["H.testing_need"] = _clip01(out["H.repair_need"] * 0.6)

    # H.material_replacement_need: from spall / detachment severity
    if spall_severity is not None or detachment_severity is not None:
        out["H.material_replacement_need"] = _clip01(
            max(spall_severity or 0.0, detachment_severity or 0.0)
        )
    else:
        out["H.material_replacement_need"] = _clip01(out["H.repair_need"] * 0.55)

    # H.nonconformity_risk: workmanship_deficit + defect_severity
    out["H.nonconformity_risk"] = _clip01(
        0.5 * workmanship_deficit + 0.5 * out["H.defect_severity_score"]
    )

    # H.repair_quality_score: from repair.repair_quality_index or driver fallback
    rqi = None
    if repair is not None:
        rqi = getattr(repair, "repair_quality_index", None)
    if rqi is None and driver is not None:
        rqi = getattr(driver, "repair_quality_index", None)
    if rqi is not None:
        out["H.repair_quality_score"] = _clip01(float(rqi))

    # H.fire_safety_need
    fire_def = bool(getattr(fire_safety, "deficiency_present", False)) if fire_safety else False
    if fire_def:
        out["H.fire_safety_need"] = 0.85
    else:
        out["H.fire_safety_need"] = HIDDEN_STATE_PRIOR_MEANS["H.fire_safety_need"]

    # H.ubw_extra_work
    ubw_present = bool(getattr(ubw, "present", False)) if ubw else False
    if ubw_present:
        out["H.ubw_extra_work"] = 0.80
    else:
        out["H.ubw_extra_work"] = HIDDEN_STATE_PRIOR_MEANS["H.ubw_extra_work"]

    # H.drainage_issue: aggregate drainage blockage / leakage
    if drainage is not None:
        bl = float(getattr(drainage, "blockage_index", 0.0) or 0.0)
        lk = float(getattr(drainage, "leakage_index", 0.0) or 0.0)
        out["H.drainage_issue"] = _clip01(0.5 * bl + 0.5 * lk)

    # H.fire_door_issue: fire_safety.deficiency_present rough proxy
    out["H.fire_door_issue"] = (
        0.55 if fire_def else HIDDEN_STATE_PRIOR_MEANS["H.fire_door_issue"]
    )

    return out


def _emit_scope_declaration_rows(
    building_world: Any,
    registries: Optional[RegistryBundle],
    building_buckets: Dict[str, List[SidecarRuntimeValue]],
) -> None:
    """scope.component.inspection_included 范围声明（spec 草案·DEBT-049 第一波 §5）。

    业务真实：RI 报告"检验范围"章节逐组件类声明涵盖与否。楼级主行
    （granularity=building，勿打 aggregation 标记——两作用域皆可见是本意），
    每组件类一行：楼内实例化的类恒 true、注册表其余类恒 false（缺席类如实
    "不涵盖"→消费端触发器判假→卡合法 NA）。qualifiers 带 W0 原生
    component_type，规范值翻译交检索 enrich 词表（无桥类型行惰性无害）。
    """
    if registries is None:
        return
    all_types: List[str] = []
    for registry in registries.registries:
        if registry.registry_id == "component_type_registry":
            all_types = [
                str(r.get("component_type"))
                for r in registry.records
                if r.get("component_type")
            ]
            break
    if not all_types:
        return
    present = {
        str(getattr(c, "component_type", ""))
        for c in getattr(building_world, "components", []) or []
    }
    wid = str(getattr(building_world, "world_id", ""))
    for ctype in sorted(all_types):
        building_buckets["facts"].append(
            SidecarRuntimeValue(
                slot_id="scope.component.inspection_included",
                value=ctype in present,
                qualifiers={
                    "component_type_key": ctype,
                    "carrier_domain": "scope",
                    "granularity": "building",
                    # 对账批修正：无限定符触发器在 fragment 作用域撞 19 条楼级行
                    # 判歧义——楼级声明行标 aggregation（fragment 作用域排除 +
                    # 有键消费端经载体升级走 rank3 唯一读数）。
                    "aggregation": "building",
                },
                time_anchor_key=None,
                source_refs=[wid],
                notes=[
                    "范围声明（spec 草案·DEBT-049 第一波 §5）：楼内实例化类恒 true、"
                    "注册表其余类恒 false（RI 报告检验范围章节的如实建模）"
                ],
            )
        )


def _build_sidecar_runtime_bundle_for_buildings(
    building_worlds: List[Any],  # List[WorldBundle] — Any 避免 module 顶层 circular import
    registries: Optional[RegistryBundle] = None,
    rng: Optional[random.Random] = None,
    projection_ids_by_fragment: Optional[Dict[str, str]] = None,
    interface_ids_by_fragment: Optional[Dict[str, List[str]]] = None,
) -> SidecarRuntimeBundle:
    """spec 09 §1.2 entry：building-centric sidecar bundle（worldgen 派生层）.

    每 building × fragment → 一条 SidecarRuntimeRecord，采样路径：
        sidecar_measurement_registry.recommended_distribution × _sample_value_for_slot
        → 按 carrier_domain 派发到 procedure_gate_state / supervision_runtime_state /
          facts 桶

    Args:
        building_worlds: List[WorldBundle]
        registries: RegistryBundle，从中提 sidecar_measurement_registry；为 None 时
            所有 record 桶为空（仅供测试便利，生产 pipeline 必传）
        rng: deterministic 采样 RNG；为 None 时用 random.Random()（非 deterministic，
            仅供测试便利）
        projection_ids_by_fragment: per-fragment projection_id 注入
        interface_ids_by_fragment: per-fragment expected interface_ids 注入

    （历史 trailing note：早期 sidecar_inputs / SidecarInput 外部注入接口
    已 2026-05-09 spec 09 §1.2 修订统一移除，函数签名不再接收外部 admin record。）
    """
    projection_ids_by_fragment = projection_ids_by_fragment or {}
    interface_ids_by_fragment = interface_ids_by_fragment or {}

    sidecar_slot_records = _collect_sidecar_measurement_slots(registries)
    sidecar_bool_slot_records = _collect_sidecar_bool_slots(registries)
    if rng is None:
        rng = random.Random()

    records: List[SidecarRuntimeRecord] = []
    for building_world in building_worlds:
        # spec 06 §11.6 evaluator context indexes — per building (lookup tables)
        # BC-3 fix (2026-05-23)：DriverState 自带 `fragment_id` 字段（spec 04 §9），
        # driver↔fragment 关系存在 driver 这一侧——直接按 `driver.fragment_id` 建索引。
        # 旧实现按 fragment list 序与 driver list 序 enumerate 配对，list 合法重排 /
        # 部分水化会把错 driver 挂到错 fragment；同时旧 `drivers_by_fragment`
        # （名为 by_fragment 实按 driver_id 建）是死代码，从未被读，一并移除。
        fragments = list(getattr(building_world, "fragments", []))
        fragment_to_driver: Dict[str, Any] = {
            getattr(d, "fragment_id", ""): d
            for d in getattr(building_world, "drivers", [])
            if getattr(d, "fragment_id", "")
        }

        mechanisms_by_fragment = {
            getattr(m, "fragment_id", ""): m for m in getattr(building_world, "mechanisms", [])
        }
        conditions_by_fragment: Dict[str, List[Any]] = {}
        for c in getattr(building_world, "conditions", []):
            conditions_by_fragment.setdefault(getattr(c, "fragment_id", ""), []).append(c)
        # LD-1 fix (2026-05-23)：drainage / ubw / fire_safety state 按 spec 04 §12/13/14
        # 锚 component_id（不是 fragment_id），sidecar 须自行重建 fragment→state 索引。
        # 旧实现按 `fragment.fragment_scope` 子集 + 生成顺序重建，但 W0-005 把
        # `fragment_scope` 从 FragmentContext 9 字段 contract 删了 → scope 过滤永远空集
        # → 三个域索引静默坍缩为空 dict。改按"触发该 state 的 mechanism family"过滤
        # fragments：generator 仅在 fragment 的 mechanism_family 命中对应 family 时
        # 生成 state（drainage_fault / ubw_signal / fire_safety_deficiency），且 state
        # 与 fragment 严格按 generator fragment-loop 顺序 lockstep append——按 mechanism
        # family 过滤后的 fragment 子集与 state list 是 exact 1:1（80 世界验证）。
        drainage_by_fragment = _index_state_by_fragment(
            getattr(building_world, "drainage_states", []), fragments,
            mechanisms_by_fragment=mechanisms_by_fragment,
            trigger_mechanism_family="drainage_fault",
        )
        # DEBT-049 B2：fire 态改按组件生成（消防构件恒有态），锚 component_id 索引，
        # 不再按 fire_safety_deficiency 机制对齐（该对齐 B2 后失效）。
        fire_safety_by_fragment = _index_state_by_fragment(
            getattr(building_world, "fire_safety_states", []), fragments,
            anchor_by_component_id=True,
        )
        ubw_by_fragment = _index_state_by_fragment(
            getattr(building_world, "ubw_states", []), fragments,
            mechanisms_by_fragment=mechanisms_by_fragment,
            trigger_mechanism_family="ubw_signal",
        )
        repair_by_fragment = {
            getattr(r, "fragment_id", ""): r for r in getattr(building_world, "repair_assessment_states", [])
        }

        # building-level aggregates
        all_severities = [
            float(getattr(c, "severity_index", 0.0) or 0.0)
            for conds in conditions_by_fragment.values()
            for c in conds
        ]
        building_total_severity_max = max(all_severities) if all_severities else 0.0
        building_defect_count = sum(1 for conds in conditions_by_fragment.values() if conds)

        # 粒度两相分派（spec 草案·流程槽粒度语义 §3.4）：先建全部 fragment 的
        # evaluator context，楼级编排器按拓扑序逐槽采样（building 槽一栋一抽、
        # fragment 槽逐 fragment 抽 + 楼级缓存广播），再逐 fragment 组记录。
        per_fragment_contexts: Dict[str, Optional[Dict[str, float]]] = {}
        for fragment in fragments:
            per_fragment_contexts[fragment.fragment_id] = (
                _build_evaluator_context_for_fragment(
                    building_world,
                    fragment,
                    drivers_by_fragment=fragment_to_driver,
                    mechanisms_by_fragment=mechanisms_by_fragment,
                    conditions_by_fragment=conditions_by_fragment,
                    drainage_by_fragment=drainage_by_fragment,
                    fire_safety_by_fragment=fire_safety_by_fragment,
                    ubw_by_fragment=ubw_by_fragment,
                    repair_by_fragment=repair_by_fragment,
                    building_total_severity_max=building_total_severity_max,
                    building_defect_count=building_defect_count,
                )
            )
        _bld = getattr(building_world, "building", None)
        building_context: Dict[str, float] = {
            "building.metadata.building_age_years": float(
                getattr(_bld, "age_years", 0.0) or 0.0
            ),
            "building_total_severity_max": float(building_total_severity_max),
            "building_defect_count": float(building_defect_count),
        }
        bool_by_fragment, building_buckets = _sample_sidecar_bool_slots_for_building(
            building_world_id=building_world.world_id,
            fragment_ids=[f.fragment_id for f in fragments],
            sidecar_bool_slot_records=sidecar_bool_slot_records,
            rng=rng,
            per_fragment_contexts=per_fragment_contexts,
            building_context=building_context,
        )
        _comp_type_by_id = {
            str(getattr(c, "component_id", "")): str(getattr(c, "component_type", ""))
            for c in getattr(building_world, "components", []) or []
        }
        for fragment in fragments:
            if registries is None:  # 契约：无注册表 → 空桶（测试便利）
                break
            _own_type = _comp_type_by_id.get(str(getattr(fragment, "component_id", "")), "")
            if not _own_type:
                continue
            bool_by_fragment[fragment.fragment_id]["facts"].append(
                SidecarRuntimeValue(
                    slot_id="scope.component.inspection_included",
                    value=True,
                    qualifiers={
                        "fragment_id": fragment.fragment_id,
                        "component_type_key": _own_type,
                        "carrier_domain": "scope",
                    },
                    time_anchor_key=None,
                    source_refs=[building_world.world_id, fragment.fragment_id],
                    notes=["范围声明 fragment 行：本部位组件类天然在检验范围内"],
                )
            )
        for fragment in fragments:
            record = _build_sidecar_record_for_fragment(
                building_world_id=building_world.world_id,
                fragment_id=fragment.fragment_id,
                sidecar_slot_records=sidecar_slot_records,
                sidecar_bool_slot_records=sidecar_bool_slot_records,
                rng=rng,
                projection_id=projection_ids_by_fragment.get(fragment.fragment_id, ""),
                expected_interface_ids=interface_ids_by_fragment.get(fragment.fragment_id),
                evaluator_context=per_fragment_contexts[fragment.fragment_id],
                pre_sampled_bool_buckets=bool_by_fragment[fragment.fragment_id],
            )
            records.append(record)
        # 范围声明楼级行（spec 草案·第一波 §5；fragment 行已在记录组装前发射——
        # 二轮对账修正：原发射点在桶消费之后，行全丢）。
        _emit_scope_declaration_rows(building_world, registries, building_buckets)
        # 楼级记录（行政槽主行 + §3.2 聚合行），有值才落。
        if any(building_buckets[b] for b in building_buckets):
            records.append(SidecarRuntimeRecord(
                runtime_id=f"SCR-BLDG-{building_world.world_id}",
                world_id=building_world.world_id,
                projection_id="",
                interface_ids=[],
                facts=building_buckets["facts"],
                runtime_markers=[],
                artifact_requirement_state=building_buckets["artifact_requirement_state"],
                procedure_gate_state=building_buckets["procedure_gate_state"],
                supervision_runtime_state=building_buckets["supervision_runtime_state"],
                completion_runtime_state=building_buckets["completion_runtime_state"],
            ))
    return SidecarRuntimeBundle(
        generated_at=_utc_now_iso(),
        source_documents=list(SOURCE_DOCUMENTS),
        records=records,
    )


def _index_state_by_fragment(
    states: List[Any],
    fragments: List[Any],
    mechanisms_by_fragment: Optional[Dict[str, Any]] = None,
    trigger_mechanism_family: Optional[str] = None,
    anchor_by_component_id: bool = False,
) -> Dict[str, Any]:
    """重建 drainage / ubw / fire_safety state 的 fragment→state 索引.

    spec 04 §12/13/14：DrainageState / UBWState / FireSafetyState 锚 `component_id`，
    **不带 `fragment_id` 字段**——故无法直接 `state.fragment_id` 索引。generator
    （generator.py generate_world_bundle fragment loop）仅在 fragment 的
    `mechanism.mechanism_family` 命中触发 family 时生成对应 state
    （drainage→drainage_fault / ubw→ubw_signal / fire→fire_safety_deficiency），
    且 state 与 fragment 严格按 fragment-loop 顺序 lockstep append。

    重建路径：按 `trigger_mechanism_family` 过滤 fragments 得到产出该域 state 的
    fragment 子集，再按 list 序与 states 1:1 对齐——子集长度与 states 长度恒等
    （generator 生成顺序保证）。

    LD-1 fix (2026-05-23)：旧实现按已从 FragmentContext 删除的 `fragment_scope`
    过滤（W0-005 reference-based 重构残留），导致 matching 永远空集、索引坍缩。
    `component_id → fragment_id` 反查不可行——一个 component 可被多 fragment 共享，
    同 component 上可挂多条同域 state（实测有碰撞），反查歧义；mechanism-family +
    生成顺序对齐是无歧义路径。

    trigger_mechanism_family=None 时退化为简单 1:1（与 fragments 全集按序对齐）.

    anchor_by_component_id=True（DEBT-049 B2，2026-07-08）：fire_safety state 改按
    **组件**生成（消防构件恒有态，机制无关），不再与 mechanism_family lockstep——改按
    state.component_id 匹配 fragment.component_id（同组件多 fragment 用消费法按序分配，
    无歧义）；mechanism-family 对齐路径对 fire 失效，component 锚定是新的无歧义路径。
    """
    if anchor_by_component_id:
        # state 锚 component_id → 匹配同 component_id 的 fragment，消费法处理共享组件。
        frags_by_comp: Dict[str, List[Any]] = {}
        for f in fragments:
            frags_by_comp.setdefault(getattr(f, "component_id", ""), []).append(f)
        cursor: Dict[str, int] = {}
        out: Dict[str, Any] = {}
        for state in states:
            cid = getattr(state, "component_id", "")
            bucket = frags_by_comp.get(cid, [])
            i = cursor.get(cid, 0)
            if i < len(bucket):
                fid = getattr(bucket[i], "fragment_id", "")
                if fid:
                    out[fid] = state
                cursor[cid] = i + 1
        return out
    if trigger_mechanism_family:
        mech_by_frag = mechanisms_by_fragment or {}
        matching = [
            f for f in fragments
            if getattr(
                mech_by_frag.get(getattr(f, "fragment_id", "")),
                "mechanism_family", None,
            ) == trigger_mechanism_family
        ]
    else:
        matching = list(fragments)
    out: Dict[str, Any] = {}
    for idx, state in enumerate(states):
        if idx < len(matching):
            fid = getattr(matching[idx], "fragment_id", "")
            if fid:
                out[fid] = state
    return out
