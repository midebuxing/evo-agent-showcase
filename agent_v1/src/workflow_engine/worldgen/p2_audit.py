"""W0 worldgen P2 inline clamp audit accumulator (DEBT-030 C 组 / spec 07 §4 line 70).

设计动机
========
P2 是 generation-time inline clip 类型修复（typical_bounds clip / physical_bounds clip /
precision rounding / count_nonneg clamp 等），触发频率可能非常高。直接 propagate 整条
RepairAction 到 BatchGateStats 会产生过多 audit overhead；spec 07 §4 line 70 决议改用
**aggregate summary + bounded sample (K=20)** 形态（详见 ``gates.py::P2ClampSummary``）.

跨函数调用栈传递 audit context 的方案选项对比：

1. **显式 accumulator 参数透传** — 侵入性强（所有 inline clip helper 加参数）.
2. **module 全局变量** — 不支持多线程 / 多进程并发.
3. **threading.local** — 不跨 asyncio coroutine 边界（unrelated here，但 contextvars 更优）.
4. **contextvars.ContextVar** ✅ — Python 3.7+ 标准；跨 ProcessPoolExecutor 自然 OK
   （每 worker 进程独立 context；worker 主入口自己 set context 即可）.

跨进程并行注意
==============
``contextvars`` 不会跨进程自动传播。这里设计上是**每个 worker 进程自己 set 自己的
accumulator**：在 ``generator.py::generate_world_bundle`` 主入口 wrap 一层 context manager，
ProcessPoolExecutor fork / spawn 后的子进程进入函数时各自重新 set 自己的 context.
worker 结束时 merge accumulator 到该 worker 的 BatchGateStats；主进程合并所有 worker
返回的 BatchGateStats 即可（已经走 ``record_p2_clamps_from_accumulator`` 同语义）.

性能契约（DEBT-022 P1 repair 性能 trace 同源）
===============================================
- 每次 ``record`` 调用：O(1) — dict.get + 增量 mean update + max 比较 + （满 K 前）单 list append.
- 不写 stderr / 不做字符串格式化（spec 07 §4 line 71）.
- get_context 返回 None 时 fast path：caller 跳过 record，零开销.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Dict, Iterator, Optional

from workflow_engine.worldgen.gates import P2ClampSummary


# ---------- ContextVar ----------

# 默认 None — caller 调 get_p2_audit_context() 时取到 None，即可 fast path 跳过 record.
_p2_audit_ctx: ContextVar[Optional["P2AuditAccumulator"]] = ContextVar(
    "p2_audit", default=None
)


# ---------- Accumulator ----------


@dataclass
class P2AuditAccumulator:
    """Worker-local P2 inline clamp audit accumulator.

    accumulator 内 summaries dict 按 check_id 索引；caller (inline clip helper) 通过
    ``record(check_id, before, after, slot_id, fragment_id)`` 写入；worker 结束时
    ``BatchGateStats.record_p2_clamps_from_accumulator(self)`` merge 进 batch stats.

    使用 ``P2ClampSummary.record()``（spec 07 §4 line 70 增量算法 + K=20 cap）作为底层
    更新原语；本类只负责 dict 索引 + lazy 创建.
    """

    summaries: Dict[str, P2ClampSummary] = field(default_factory=dict)

    def record(
        self,
        check_id: str,
        before: float,
        after: float,
        slot_id: Optional[str] = None,
        fragment_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        """累加单次 inline clamp 事件.

        Caller 负责判定 before != after（真的发生 clamp）；本方法不再 noop 判定，
        节约 hot path 比较开销.
        """
        summary = self.summaries.get(check_id)
        if summary is None:
            summary = P2ClampSummary(check_id=check_id)
            self.summaries[check_id] = summary
        summary.record(
            before=before,
            after=after,
            slot_id=slot_id,
            fragment_id=fragment_id,
            detail=detail,
        )


# ---------- ContextVar helpers ----------


def set_p2_audit_context(accumulator: Optional[P2AuditAccumulator]) -> Token:
    """安装 accumulator 到 ContextVar。返回 token 供 ``reset`` 用.

    通常通过 ``audit_capture()`` context manager 间接调用；直接调用见 ``generator.py``.
    """
    return _p2_audit_ctx.set(accumulator)


def get_p2_audit_context() -> Optional[P2AuditAccumulator]:
    """读取当前 ContextVar 中的 accumulator；未 set 时返回 None.

    Inline clip helper 的 hot path 调用入口：返回 None 时跳过 record（性能 fast path）.
    """
    return _p2_audit_ctx.get()


def clear_p2_audit_context(token: Optional[Token] = None) -> None:
    """清理 ContextVar（一般通过 audit_capture context manager 自动 reset）.

    显式调用通常不需要——context manager exit 时已经 reset；保留供测试 fixture 隔离用.
    """
    if token is not None:
        _p2_audit_ctx.reset(token)
    else:
        _p2_audit_ctx.set(None)


@contextlib.contextmanager
def audit_capture(
    accumulator: Optional[P2AuditAccumulator] = None,
) -> Iterator[P2AuditAccumulator]:
    """Context manager：set/reset P2 audit context（测试 + 主入口共用）.

    用法 (测试)::

        with audit_capture() as acc:
            _clip(1.5, (0, 1))  # 触发 clamp -> acc 累加
        assert acc.summaries["TYPICAL_BOUNDS_CLIP"].count == 1

    用法 (生产主入口 — generator.py::generate_world_batch_with_stats 已内置)::

        with audit_capture() as acc:
            world = _generate_inner(...)
        batch_stats.record_p2_clamps_from_accumulator(acc)

    用法 (caller 单独调 generate_world_bundle — spec 07 §4 line 75 caller 责任)::

        from workflow_engine.worldgen.p2_audit import audit_capture
        from workflow_engine.worldgen.generator import generate_world_bundle

        with audit_capture() as acc:
            bundle = generate_world_bundle(batch_config, registries, seed=42, building_index=0)
        # acc.summaries 内含本次 generation 触发的 P2 inline clip aggregate summary
        # 不 wrap 不会 raise — P2 inline clip silently 跳过 record (spec 07 §4 line 75)

    accumulator 为 None → 自动 new 一个空 accumulator yield 出去.

    **跨进程并行注意 (spec 07 §4 line 70-75 + 本模块 module docstring)**:
        ``contextvars`` ContextVar 是 **进程级**——**不跨 ProcessPoolExecutor / multiprocessing
        worker 进程自动传播**。Windows ``spawn`` / POSIX ``fork`` 子进程进入 worker function
        时，``_p2_audit_ctx`` 默认值都是 None（fresh ContextVar 状态）.

        跨进程 pattern: 每 worker 进程**自己 set 自己的 accumulator**, 例::

            # worker function (必须 module-level — Windows spawn 不能 pickle closure)
            def _worker_task(seed: int) -> Dict:
                with audit_capture() as acc:
                    bundle = generate_world_bundle(..., seed=seed)
                # worker-local accumulator merge 进 worker-local BatchGateStats
                stats = BatchGateStats()
                stats.record_p2_clamps_from_accumulator(acc)
                return stats.to_dict()  # 通过 dict round-trip 跨进程返回

            # 主进程 collect + merge
            results = pool.map(_worker_task, seeds)
            master_stats = BatchGateStats()
            for d in results:
                worker_stats = BatchGateStats.from_dict(d)
                # 主进程合并: per check_id count 累加 / max 取大 / mean 加权
                for cid, sm in worker_stats.p2_clamp_summaries.items():
                    acc = P2AuditAccumulator()
                    acc.summaries[cid] = sm
                    master_stats.record_p2_clamps_from_accumulator(acc)

        端到端测试见 ``test_gates.py`` ``CrossProcessP2AuditTests``.
    """
    if accumulator is None:
        accumulator = P2AuditAccumulator()
    token = _p2_audit_ctx.set(accumulator)
    try:
        yield accumulator
    finally:
        _p2_audit_ctx.reset(token)


# ---------- Check ID 常量 ----------

# DEBT-030 C 组 / spec 07 §4 line 70 P2 inline clamp 类型分类（aggregation key）.
# 命名规则：大写 + 下划线分段，描述 clamp 性质（不写 check_id 编号——P2 inline clamp 多数
# 不对应 spec §2 C001-C026 显式 check_id，是 generation 阶段 inline guard rail）.
CHECK_ID_TYPICAL_BOUNDS_CLIP = "TYPICAL_BOUNDS_CLIP"
# typical_bounds → physical_bounds 双阶 clip（W0 spec 06 §11.5 DEBT-026）

CHECK_ID_PRECISION_ROUNDING = "PRECISION_ROUNDING"
# precision_steps / apply_precision_rounding step 规整（spec 06 §13）

CHECK_ID_COUNT_NONNEG_CLAMP = "COUNT_NONNEG_CLAMP"
# integer slot 非负 / bounds 截断（COUNT_POISSON_ROUND clip + value_type==integer clamp）

CHECK_ID_RATIO_BOUND_CLIP = "RATIO_BOUND_CLIP"
# ratio [0, 1] clamp（RATIO_ABS_GAUSS / sidecar Bernoulli prevalence 等）

CHECK_ID_PROBABILITY_BOUND_CLIP = "PROBABILITY_BOUND_CLIP"
# 概率参数 [0, 1] 输入 sanitize（_marginal_sample prevalence clamp 等；与 RATIO 区分：
# 前者是结构化 slot 输出 ratio，后者是采样器内部入参防御）
