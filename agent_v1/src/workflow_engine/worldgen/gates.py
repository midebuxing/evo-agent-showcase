"""W0 worldgen P0/P1/P2 generation-time gate framework (T-21).

按 spec 07 §1 / §2 priority repair pass + §4.6 7 项决策实施：

- T-21.1 (B)：building bundle 完成后一次 gate（worldgen 主路径每栋调一次）
- T-21.2 (A)：P0 violation 触发整 building resample（外层 retry budget 3）
- T-21.3 (A)：P1/P2 repair 形态 pure function（返回新 WorldBundle，不动 input）
- T-21.4 (A)：worldgen gate 管 P0/P1/P2；P3 跨 fragment 关系约束在 projection 阶段
- T-21.5 (A)：iteration 上限 3 次（外层 resample；内层 P1 repair 上限 5）
- T-21.6 (A)：FrameworkManifest 加 rejected_count + reject_reasons 桶（spec 07 健康度指标）
- T-21.7 (B)：coarse 粗粒度（per-building 整体 gate，不按 fragment 细分）

T-22 工单实施 spec 07 §2 C001-C026 各级 check 函数；本工单提供框架 + 空 placeholder check。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from workflow_engine.worldgen.models import RegistryBundle, WorldBundle

if TYPE_CHECKING:  # 仅注解用（P2AuditAccumulator 定义在 p2_audit），避免运行时循环 import
    from workflow_engine.worldgen.p2_audit import P2AuditAccumulator


# ---------- 模块级常量 ----------

# DEBT-030 C 组 / spec 07 §4 line 70：P2 aggregate summary 每 check_id 保留前 K=20 个代表性
# sample_actions detail；超 K 后只增 count + 累积 max/mean magnitude，不再 append detail。
# K 上限设计理由：99% audit trace 目标（调试 / 频率分析 / 合规审计）20 个 sample 已 cover；
# 罕见 outlier 升级到 full detail 按需展开（spec 07 §4 line 71）。
P2_SAMPLE_CAP: int = 20


# ---------- 数据类 ----------


@dataclass
class Violation:
    """单条 gate violation 记录（spec 07 §1）."""

    check_id: str  # spec 07 C001-C026
    priority: str  # "P0" / "P1" / "P2"
    detail: str
    fragment_id: Optional[str] = None  # 若 violation 跟具体 fragment 相关


@dataclass
class RepairAction:
    """单次 P1/P2 修复动作 audit 记录 (DEBT-030 C 组 / spec 07 §4 line 68).

    spec 07 §4：不允许 silent 修复——每次 P1/P2 修复必须 log（audit trace）.
    本 dataclass 是 P1 修复函数返回的修复事实条目（per-violation per-fix）.

    字段 / Fields:
        check_id:      Violation.check_id 对应的修复目标 check（如 C007_EXTENT_AREA_BOUND）
        fragment_id:   被修复 entity 的 fragment_id（可空——repair_assessment_state 走 fragment 关联）
        detail:        修复动作短文本描述（before/after 之外的语境信息）
        before_value:  修复前数值 / 状态（数值 clamp / bool flip / enum override 通用 Any）
        after_value:   修复后数值 / 状态
    """

    check_id: str
    fragment_id: Optional[str] = None
    detail: str = ""
    before_value: Any = None
    after_value: Any = None


@dataclass
class P2ClampSummary:
    """单条 P2 inline clamp aggregate summary (spec 07 §4 line 70).

    P2 是 generation-time inline clip（typical_bounds / physical_bounds / precision_rounding
    / count_nonneg_clamp 等）的修复，**触发频率可能非常高**——不像 P1 是事后 check 触发的稀疏
    事件。spec 07 §4 line 71 设计理由：aggregate summary + bounded sample (K=20) 已 cover
    99% audit trace 目标（调试 / 频率分析 / 合规审计），剩 1% 罕见 outlier 场景按需升级到 full
    detail 不冲突当前架构。

    字段 / Fields:
        check_id: aggregation key, 如:
          - ``TYPICAL_BOUNDS_CLIP``：_sample_typical_distribution 的 typical_bounds + physical
            _bounds 双阶 clip (W0 spec 06 §11.5)
          - ``PRECISION_ROUNDING``：apply_precision_rounding / precision_steps 走的 step rounding
          - ``COUNT_NONNEG_CLAMP``：integer slot 非负 clamp + bounds 截断
          - ``C013_RATIO_BOUND`` 等 spec 07 §2 显式 P2 check_id（如有）
        count: 总 trigger 次数（每次 before != after 计 1，before == after 不计）
        max_magnitude: max(abs(before - after))
        mean_magnitude: cumulative running mean of abs(before - after)；增量算法
            new_mean = old_mean + (mag - old_mean) / new_count
        sample_actions: 前 K=20 个代表性 detail（含 slot_id / fragment_id / before / after）；
            满 K 后**不 append detail** 但 count / max_magnitude / mean_magnitude 持续累加.
    """

    check_id: str
    count: int = 0
    max_magnitude: float = 0.0
    mean_magnitude: float = 0.0
    sample_actions: List["RepairAction"] = field(default_factory=list)

    def record(
        self,
        before: float,
        after: float,
        slot_id: Optional[str] = None,
        fragment_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        """累加单次 clamp 事件到本 summary（O(1) 增量更新，无 IO）.

        before == after 时 **caller 应跳过本方法**（不算 clamp，节约 magnitude 累计）。
        本方法假设 caller 已判定真的发生了 clamp。
        """
        magnitude = abs(float(before) - float(after))
        new_count = self.count + 1
        # 增量算法：new_mean = old_mean + (x - old_mean) / new_count；O(1)
        self.mean_magnitude = self.mean_magnitude + (magnitude - self.mean_magnitude) / new_count
        if magnitude > self.max_magnitude:
            self.max_magnitude = magnitude
        self.count = new_count
        # K=20 cap 后不再 append 详情（spec 07 §4 line 70）
        if len(self.sample_actions) < P2_SAMPLE_CAP:
            self.sample_actions.append(
                RepairAction(
                    check_id=self.check_id,
                    fragment_id=fragment_id,
                    detail=detail or (f"slot={slot_id}" if slot_id else ""),
                    before_value=before,
                    after_value=after,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "count": self.count,
            "max_magnitude": self.max_magnitude,
            "mean_magnitude": self.mean_magnitude,
            "sample_actions": [
                {
                    "check_id": a.check_id,
                    "fragment_id": a.fragment_id,
                    "detail": a.detail,
                    "before_value": a.before_value,
                    "after_value": a.after_value,
                }
                for a in self.sample_actions
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "P2ClampSummary":
        sample_actions = [
            RepairAction(
                check_id=a.get("check_id", data.get("check_id", "")),
                fragment_id=a.get("fragment_id"),
                detail=a.get("detail", ""),
                before_value=a.get("before_value"),
                after_value=a.get("after_value"),
            )
            for a in data.get("sample_actions", [])
        ]
        return cls(
            check_id=data["check_id"],
            count=int(data.get("count", 0)),
            max_magnitude=float(data.get("max_magnitude", 0.0)),
            mean_magnitude=float(data.get("mean_magnitude", 0.0)),
            sample_actions=sample_actions,
        )


@dataclass
class GateResult:
    """单次 gate pass 结果（spec 07 §1）.

    passed=True 表示 P0 + P1 全过；P2 仅作 warning 不阻塞（violations 列表会含 P2）。
    """

    passed: bool
    iterations: int  # 内层 P1 repair iteration 计数
    violations: List[Violation] = field(default_factory=list)
    reject_reason: Optional[str] = None  # spec 07 §5 unknown_reason_code 子集
    world_bundle: Optional[WorldBundle] = None  # passed=True 时携带（可能被 P1 repaired）
    # DEBT-030 C 组：P1/P2 修复 audit trace（spec 07 §4 "不允许 silent 修复"）.
    # repair_actions 累积本次 gate pass 中所有 P1 repair 函数返回的修复条目；
    # 每条对应一个 RepairAction 实例；空 list 表示无修复发生（含 P0 reject 路径）.
    repair_actions: List[RepairAction] = field(default_factory=list)


# ---------- check 注册（T-22 填充实施） ----------


# T-21 框架：T-22 工单注册具体 check（spec 07 §2 C001-C032 各级；C026 已删 / C023-C025 属 W2）
# CheckFn signature: (world_bundle, registries) -> List[Violation]
CheckFn = Callable[[WorldBundle, RegistryBundle], List[Violation]]

# RepairFn signature: (world_bundle, violations) -> (WorldBundle, List[RepairAction]).
# DEBT-030 C 组：spec 07 §4 "不允许 silent 修复"——repair 函数必须返回修复动作 audit 列表.
# pure function 立场不变：返回新 WorldBundle，不动 input；同时返回本次 invocation 内的修复条目.
RepairFn = Callable[[WorldBundle, List[Violation]], Tuple[WorldBundle, List["RepairAction"]]]

P0_CHECKS: List[CheckFn] = []  # T-22 填：C001 / C004 / C007 / C008 / C012 等
P1_CHECKS: List[CheckFn] = []  # T-22 填：C013 / C014 / C015 等
# C023 / C024 / C025 是 W2 法规映射层 NormativeProjection-level 约束（W2 规格 07 §5），
# 跟 worldgen 端 WorldBundle-level CheckFn signature 不同。这 3 条 W2 端约束的强制执行
# 在 `regulation_projection_executor.build_normative_projections_for_world` 内 inline 完成
# （per-NormativeProjection 输出前 gate），不挂本表（本表仅留作 worldgen P2 check 占位）。
P2_CHECKS: List[CheckFn] = []
P1_REPAIRS: List[RepairFn] = []  # T-22 填：repair 函数（per check_id 路由）


def register_p0_check(fn: CheckFn) -> CheckFn:
    """T-22 装饰器：注册 P0 check 函数."""
    P0_CHECKS.append(fn)
    return fn


def register_p1_check(fn: CheckFn) -> CheckFn:
    P1_CHECKS.append(fn)
    return fn


def register_p2_check(fn: CheckFn) -> CheckFn:
    P2_CHECKS.append(fn)
    return fn


def register_p1_repair(fn: RepairFn) -> RepairFn:
    P1_REPAIRS.append(fn)
    return fn


def clear_check_registry() -> None:
    """测试用：清空所有注册的 check / repair（独立测试 fixture 隔离）."""
    P0_CHECKS.clear()
    P1_CHECKS.clear()
    P2_CHECKS.clear()
    P1_REPAIRS.clear()


# ---------- check / repair 调用（pure functions） ----------


def check_p0_violations(world_bundle: WorldBundle, registries: RegistryBundle) -> List[Violation]:
    """汇总所有注册的 P0 check 函数输出（spec 07 §1 强制硬约束）."""
    violations: List[Violation] = []
    for fn in P0_CHECKS:
        violations.extend(fn(world_bundle, registries))
    return violations


def check_p1_violations(world_bundle: WorldBundle, registries: RegistryBundle) -> List[Violation]:
    """汇总所有注册的 P1 check 函数输出（spec 07 §1 可修复软约束）."""
    violations: List[Violation] = []
    for fn in P1_CHECKS:
        violations.extend(fn(world_bundle, registries))
    return violations


def check_p2_violations(world_bundle: WorldBundle, registries: RegistryBundle) -> List[Violation]:
    """汇总所有注册的 P2 check 函数输出（spec 07 §1 警告）."""
    violations: List[Violation] = []
    for fn in P2_CHECKS:
        violations.extend(fn(world_bundle, registries))
    return violations


def repair_p1(
    world_bundle: WorldBundle,
    violations: List[Violation],
) -> Tuple[WorldBundle, List[RepairAction]]:
    """T-21.3 pure function：用所有注册的 P1 repair 函数依次 transform world_bundle.

    每个 repair 函数返回新 WorldBundle + 本次修复动作 list，链式 apply。无 P1 repair 时
    返回原对象 + 空 list（pure function 立场下也可以 model_copy(deep=True)；当前 None-op 时不做
    copy 节约成本）.

    DEBT-030 C 组：repair 函数 contract 由原 ``(wb, violations) -> wb`` 升级为
    ``(wb, violations) -> (wb, List[RepairAction])``——保证 spec 07 §4 "不允许 silent 修复".
    """
    if not P1_REPAIRS:
        return world_bundle, []
    current = world_bundle
    actions: List[RepairAction] = []
    for repair_fn in P1_REPAIRS:
        new_bundle, fn_actions = repair_fn(current, violations)
        current = new_bundle
        if fn_actions:
            actions.extend(fn_actions)
    return current, actions


# ---------- gate orchestration ----------


_DEFAULT_MAX_RETRIES = 3  # T-21.5: 外层 resample budget = 3
_DEFAULT_MAX_P1_REPAIR_ITERATIONS = 5  # 内层 P1 repair 上限


def apply_gate_single_pass(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
    max_p1_repair_iterations: int = _DEFAULT_MAX_P1_REPAIR_ITERATIONS,
) -> GateResult:
    """单次 gate pass：P0 检查 → P1 检查 + repair 迭代 → P2 警告.

    P0 violation：立即返回 reject（spec 07 §1，caller 负责 resample）。
    P1 violation：调 repair_p1，重新 check，最多迭代 max_p1_repair_iterations 次。
    P2 violation：纳入 violations list 但 passed=True 不阻塞（warning 性质）。
    """
    p0_violations = check_p0_violations(world_bundle, registries)
    if p0_violations:
        return GateResult(
            passed=False,
            iterations=0,
            violations=p0_violations,
            reject_reason="P0_violation",
            world_bundle=None,
        )

    current = world_bundle
    repair_iter = 0
    accumulated_actions: List[RepairAction] = []
    while repair_iter < max_p1_repair_iterations:
        p1_violations = check_p1_violations(current, registries)
        if not p1_violations:
            break
        current, iter_actions = repair_p1(current, p1_violations)
        # DEBT-030 C 组：spec 07 §4 audit trace—累积 per-iteration repair actions
        if iter_actions:
            accumulated_actions.extend(iter_actions)
        repair_iter += 1
    else:
        # else 跑到这里说明 P1 repair 迭代 max 次仍有 P1 violation
        return GateResult(
            passed=False,
            iterations=repair_iter,
            violations=check_p1_violations(current, registries),
            reject_reason="P1_repair_unfeasible",
            world_bundle=None,
            repair_actions=accumulated_actions,
        )

    p2_violations = check_p2_violations(current, registries)
    return GateResult(
        passed=True,
        iterations=repair_iter,
        violations=p2_violations,
        reject_reason=None,
        world_bundle=current,
        repair_actions=accumulated_actions,
    )


def apply_gate_with_retry(
    generator_fn: Callable[[int], WorldBundle],
    registries: RegistryBundle,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    max_p1_repair_iterations: int = _DEFAULT_MAX_P1_REPAIR_ITERATIONS,
) -> Tuple[Optional[WorldBundle], GateResult]:
    """T-21.2 + T-21.5 主入口：外层 P0 retry + 内层 P1 repair iteration.

    Args:
        generator_fn: takes retry_index (0..max_retries-1), returns fresh WorldBundle.
        registries: registry bundle for check 函数访问。
        max_retries: P0 retry budget (T-21.5 default 3).
        max_p1_repair_iterations: P1 repair inner loop budget.

    Returns:
        (passed_world_bundle_or_None, final_GateResult).
        passed_world_bundle_or_None=None 表示重试 max 次仍 reject；reject_reason 在 GateResult 中。
    """
    last_result = GateResult(
        passed=False,
        iterations=0,
        violations=[],
        reject_reason="no_attempt",
        world_bundle=None,
    )
    for retry_index in range(max_retries):
        candidate = generator_fn(retry_index)
        result = apply_gate_single_pass(
            world_bundle=candidate,
            registries=registries,
            max_p1_repair_iterations=max_p1_repair_iterations,
        )
        if result.passed:
            return result.world_bundle, result
        last_result = result
    # 全部重试都 reject
    return None, GateResult(
        passed=False,
        iterations=last_result.iterations,
        violations=last_result.violations,
        reject_reason=last_result.reject_reason or "max_retries_exceeded",
        world_bundle=None,
        repair_actions=last_result.repair_actions,
    )


# ---------- 批次统计（T-21.6） ----------


@dataclass
class BatchGateStats:
    """spec 07 §1 批次健康度指标（T-21.6） + DEBT-030 C 组 P1/P2 修复 audit trace 计数."""

    accepted_count: int = 0
    rejected_count: int = 0
    reject_reasons: Dict[str, int] = field(default_factory=dict)  # reason → count
    # DEBT-030 C 组 / spec 07 §4 line 69 audit trace：per check_id P1 修复发生次数计数.
    # 性能注：仅 O(1) dict 累加，避免 stderr / 字符串拼接（DEBT-022 P1 repair 性能 trace 同源）.
    repair_action_counts: Dict[str, int] = field(default_factory=dict)  # check_id → count
    # DEBT-030 C 组 / spec 07 §4 line 70 audit trace：per check_id P2 inline clamp aggregate
    # summary（count / max/mean magnitude / 前 K=20 sample detail）.
    # 性能注：仅 O(1) summary 增量更新；累 K 后 sample_actions 不再 append（cap K=20）.
    p2_clamp_summaries: Dict[str, P2ClampSummary] = field(default_factory=dict)
    # W1-012 / spec 10 §6 silent fallback 红线：sidecar conditional formula 异常 fallback 到
    # marginal 时的 per reason class 计数（caller 通过 audit_capture_sidecar_fallback() context
    # manager 收集后调 record_sidecar_fallback_counts merge 进本字段）.
    sidecar_fallback_counts: Dict[str, int] = field(default_factory=dict)

    def record_accepted(self) -> None:
        self.accepted_count += 1

    def record_rejected(self, reason: str) -> None:
        self.rejected_count += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def record_repair_actions(self, actions: List[RepairAction]) -> None:
        """DEBT-030 C 组：累加 per-check_id 修复次数到 batch 桶.

        spec 07 §4 line 69 "不允许 silent 修复" audit trace 落地点（P1 per-action detail）：
        ``apply_gate_with_retry`` 返回 GateResult.repair_actions 后调本方法填 batch 统计.
        性能：list 遍历 + dict[k] = dict.get(k,0)+1，每个 action 严格 O(1)，无 IO.
        """
        if not actions:
            return
        for action in actions:
            cid = action.check_id
            self.repair_action_counts[cid] = self.repair_action_counts.get(cid, 0) + 1

    def record_sidecar_fallback_counts(self, counts: Optional[Dict[str, int]]) -> None:
        """W1-012：merge worker-local sidecar fallback counts dict → batch 桶.

        spec 10 §6 silent fallback 红线 audit trace 落地点：caller wrap
        ``audit_capture_sidecar_fallback()`` 后把 dict merge 进 BatchGateStats.
        """
        if not counts:
            return
        for reason, n in counts.items():
            if not n:
                continue
            self.sidecar_fallback_counts[reason] = self.sidecar_fallback_counts.get(reason, 0) + n

    def record_p2_clamps_from_accumulator(
        self,
        accumulator: "P2AuditAccumulator",
    ) -> None:
        """DEBT-030 C 组：merge worker P2AuditAccumulator → batch p2_clamp_summaries 桶.

        spec 07 §4 line 70 "P2 修复 aggregate summary" 落地点：generator 主入口 finally
        block 收 contextvars accumulator 后调本方法把 per-build summary merge 进 batch 统计.

        合并语义（per check_id）：
            - count: 直接累加
            - max_magnitude: max(自身, accumulator 中)
            - mean_magnitude: 加权平均（按 count 权重）—— new_mean =
              (self_count * self_mean + acc_count * acc_mean) / (self_count + acc_count)
            - sample_actions: append until total < K=20，cap 后丢弃 acc 超出部分

        性能：O(#unique_check_id × min(K, #acc_samples)) per build；不 stderr / 字符串拼接.
        """
        if accumulator is None:
            return
        acc_summaries = getattr(accumulator, "summaries", None)
        if not acc_summaries:
            return
        for check_id, acc_summary in acc_summaries.items():
            if acc_summary.count == 0:
                continue
            existing = self.p2_clamp_summaries.get(check_id)
            if existing is None:
                # 直接接管 acc summary（含 sample_actions），但 cap 在 K
                merged = P2ClampSummary(
                    check_id=check_id,
                    count=acc_summary.count,
                    max_magnitude=acc_summary.max_magnitude,
                    mean_magnitude=acc_summary.mean_magnitude,
                    sample_actions=list(acc_summary.sample_actions[:P2_SAMPLE_CAP]),
                )
                self.p2_clamp_summaries[check_id] = merged
                continue
            # 加权 mean merge
            total = existing.count + acc_summary.count
            if total > 0:
                existing.mean_magnitude = (
                    existing.count * existing.mean_magnitude
                    + acc_summary.count * acc_summary.mean_magnitude
                ) / total
            existing.count = total
            if acc_summary.max_magnitude > existing.max_magnitude:
                existing.max_magnitude = acc_summary.max_magnitude
            # sample_actions: append until K
            remaining = P2_SAMPLE_CAP - len(existing.sample_actions)
            if remaining > 0 and acc_summary.sample_actions:
                existing.sample_actions.extend(acc_summary.sample_actions[:remaining])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "reject_reasons": dict(self.reject_reasons),
            "repair_action_counts": dict(self.repair_action_counts),
            "p2_clamp_summaries": {
                cid: summary.to_dict()
                for cid, summary in self.p2_clamp_summaries.items()
            },
            # W1-012 silent fallback audit trace
            "sidecar_fallback_counts": dict(self.sidecar_fallback_counts),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchGateStats":
        """parquet / json round-trip 反序列化入口."""
        p2_raw = data.get("p2_clamp_summaries") or {}
        p2_summaries: Dict[str, P2ClampSummary] = {
            cid: P2ClampSummary.from_dict(payload)
            for cid, payload in p2_raw.items()
        }
        return cls(
            accepted_count=int(data.get("accepted_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            reject_reasons=dict(data.get("reject_reasons", {})),
            repair_action_counts=dict(data.get("repair_action_counts", {})),
            p2_clamp_summaries=p2_summaries,
            sidecar_fallback_counts=dict(data.get("sidecar_fallback_counts", {})),
        )
