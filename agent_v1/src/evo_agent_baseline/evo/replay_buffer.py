"""ReplayBuffer —— EvoMemoryStore 内 ReplayCase 容器。

权威：spec v1 §3.6.1 / §3.6.3 / §9.2。

设计要点：
    - in-memory 实现 + 可选 filesystem JSON 落盘（用户配置 backend）。
    - 入库前 eligibility 检查（spec v1 §9.2.1 5 个 invariant）；不合格 trace
      允许保留（标 `eligibility != "eligible"`）以供审计，但 list_eligible_traces
      / aggregate_*_patterns / get_replay_set 全部只返回 eligible 子集。
    - aggregate_failure_patterns 按 (rule_family, semantic_slot, obligation_kind,
      open/blocked_reason) 4-元组聚合，spec v1 §9.3.1 触发 A 直接消费。
    - aggregate_success_patterns 按 active_skill_set_id 聚合，配合 trainer/induction
      触发 B（tool 序列优化）。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from evo_agent_baseline.contracts import EvoRunTrace


# spec v1 §9.2.2 split 默认比例
_DEFAULT_SPLIT_RATIO = {
    "evolve_train": 0.60,
    "gate_validation": 0.20,
    "held_out_test": 0.20,
}


Backend = Literal["memory", "filesystem"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trace_eligible(trace: EvoRunTrace) -> bool:
    """spec v1 §9.2.1 eligible 公式。"""
    return (
        trace.forbidden_scan_passed
        and trace.source_visibility_audit_passed
        and trace.schema_audit_passed
        and bool(trace.candidate_universe_hash)
        and bool(trace.closure_result_ref)
    )


def _canonical_set_hash(trace_ids: List[str]) -> str:
    """replay_set canonical hash（spec v1 §3.8 + §9.2.3）。"""
    payload = json.dumps(sorted(trace_ids), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _world_family_of(trace: EvoRunTrace) -> str:
    """world family 启发式：world_id_hash 前 6 字符作 family bucket。

    完整实现需 world manifest，此 baseline 用 hash 前缀代理。
    """
    return trace.world_id_hash[:6]


def _pattern_key_failure(
    trace: EvoRunTrace,
) -> List[Tuple[str, str, str, str]]:
    """spec v1 §9.3.1 触发 A 维度：
        (rule_family, semantic_slot_class, obligation_kind,
         open_reason_code/blocked_reason_code)。

    trace.closure_summary 内含 open_reason_counts / blocked_reason_counts
    （继承 v0.4 ClosureSummary）；rule_family / semantic_slot_class /
    obligation_kind 由 retrieval_summary / closure_summary 子结构提供。
    若结构不全则跳过。
    """
    cs = trace.closure_summary or {}
    rs = trace.retrieval_summary or {}
    rule_families = rs.get("rule_families") or cs.get("rule_families") or []
    slot_classes = rs.get("semantic_slot_classes") or cs.get("semantic_slot_classes") or []
    obligation_kinds = cs.get("obligation_kinds") or []
    open_reasons = list((cs.get("open_reason_counts") or {}).keys())
    blocked_reasons = list((cs.get("blocked_reason_counts") or {}).keys())
    reasons = open_reasons + blocked_reasons
    keys: List[Tuple[str, str, str, str]] = []
    if not rule_families or not reasons:
        return keys
    for rf in rule_families:
        for sc in slot_classes or [""]:
            for ok in obligation_kinds or [""]:
                for r in reasons:
                    keys.append((str(rf), str(sc), str(ok), str(r)))
    return keys


def _pattern_key_success(trace: EvoRunTrace) -> Tuple[str, ...]:
    """spec v1 §9.3.1 触发 B 维度：active skill set + tool sequence。"""
    tool_seq = tuple(
        step.tool_name for step in trace.steps if step.tool_name
    )
    return (trace.active_skill_set_id,) + tool_seq


class ReplayBuffer:
    """spec v1 §9.2 Replay Buffer 实现。

    in-memory 主存 + 可选 filesystem 持久化。
    `add_trace` 检查 eligibility + forbidden_scan_passed；
    后者不通过 → 直接拒收（spec v1 §9.2 顶部硬约束）。
    """

    def __init__(
        self,
        *,
        backend: Backend = "memory",
        store_dir: Optional[Path] = None,
    ) -> None:
        self.backend: Backend = backend
        self.store_dir: Optional[Path] = Path(store_dir) if store_dir else None
        if backend == "filesystem":
            if self.store_dir is None:
                raise ValueError("filesystem backend 必须给 store_dir")
            self.store_dir.mkdir(parents=True, exist_ok=True)
        self._traces: Dict[str, EvoRunTrace] = {}
        self._eligibility: Dict[str, bool] = {}
        # spec v1 §9.2.2 split assignment
        self._split: Dict[str, str] = {}
        # 冻结的 replay set 注册
        self._frozen_sets: Dict[str, List[str]] = {}

    # ---------------- 入库 / 列举 ---------------------------------------------

    def add_trace(self, trace: EvoRunTrace) -> bool:
        """入库；spec v1 §9.2：forbidden_scan_passed=False 直接拒。

        Returns:
            True 表示 eligible，False 表示入库但 ineligible（保留审计）。

        Raises:
            ValueError: ``forbidden_scan_passed=False`` 或 ``trace_id`` 已存在
            （Codex review 2026-05-27 C2[P2] + spec §9.2 行 901 unique 约束）。
        """
        if not trace.forbidden_scan_passed:
            raise ValueError(
                f"trace {trace.trace_id} forbidden_scan_passed=False，"
                "spec v1 §9.2 禁止入 Replay Buffer"
            )
        # Codex review 2026-05-27 C2[P2]：spec §9.2 行 901 明示
        # ``CREATE CONSTRAINT trace_id_unique FOR (t:EvoRunTrace) REQUIRE
        # t.trace_id IS UNIQUE``——重复 trace_id 静默覆盖会丢失旧 trace 不可审计。
        # 必须显式拒绝；若 caller 真要 reingest，应先 evict 旧条目。
        if trace.trace_id in self._traces:
            raise ValueError(
                f"trace_id {trace.trace_id!r} 已存在，违反 spec §9.2 unique 约束。"
                f"如需 reingest 请先调 evict_trace() 删旧条目。"
            )
        eligible = _trace_eligible(trace)
        self._traces[trace.trace_id] = trace
        self._eligibility[trace.trace_id] = eligible
        # 自动分 split（按 trace_id hash 取模简单切分）
        self._split[trace.trace_id] = self._assign_split(trace.trace_id)
        if self.backend == "filesystem" and self.store_dir is not None:
            (self.store_dir / f"{trace.trace_id}.json").write_text(
                trace.model_dump_json(), encoding="utf-8"
            )
        return eligible

    def _assign_split(self, trace_id: str) -> str:
        """spec v1 §9.2.2：按 building/world family/rule family 分层。

        baseline 使用 trace_id hash → 模 100 → 60/20/20 切分。完整 stratified
        sampling 留 hook 给 trainer 自定义 split_strategy。
        """
        h = int(hashlib.sha256(trace_id.encode()).hexdigest()[:8], 16) % 100
        if h < 60:
            return "evolve_train"
        if h < 80:
            return "gate_validation"
        return "held_out_test"

    def list_eligible_traces(self) -> List[EvoRunTrace]:
        """返回所有 eligible trace。"""
        return [
            self._traces[tid]
            for tid in self._traces
            if self._eligibility.get(tid, False)
        ]

    def list_all_traces(self) -> List[EvoRunTrace]:
        """返回全部 trace（含 ineligible，供审计）。"""
        return list(self._traces.values())

    def get_split(self, trace_id: str) -> Optional[str]:
        return self._split.get(trace_id)

    def list_split(self, split: str) -> List[EvoRunTrace]:
        """按 split 列出 eligible trace。"""
        return [
            self._traces[tid]
            for tid, s in self._split.items()
            if s == split and self._eligibility.get(tid, False)
        ]

    # ---------------- 模式聚合 ------------------------------------------------

    def aggregate_failure_patterns(
        self, window_size: int = 50
    ) -> Dict[Tuple[str, str, str, str], List[EvoRunTrace]]:
        """spec v1 §9.3.1 触发 A：聚合 (rule_family, slot_class, obligation_kind,
        reason_code) → trace list。仅 eligible trace。

        window_size：最近 N 个 eligible trace（按 created_at 排序）。
        """
        eligible_sorted = sorted(
            self.list_eligible_traces(), key=lambda t: t.created_at, reverse=True
        )[:window_size]
        bucket: Dict[Tuple[str, str, str, str], List[EvoRunTrace]] = defaultdict(list)
        for trace in eligible_sorted:
            keys = _pattern_key_failure(trace)
            for k in keys:
                bucket[k].append(trace)
        return dict(bucket)

    def aggregate_success_patterns(
        self, window_size: int = 50
    ) -> Dict[Tuple[str, ...], List[EvoRunTrace]]:
        """spec v1 §9.3.1 触发 B：聚合 active skill set + tool 序列 → trace list。"""
        eligible_sorted = sorted(
            self.list_eligible_traces(), key=lambda t: t.created_at, reverse=True
        )[:window_size]
        bucket: Dict[Tuple[str, ...], List[EvoRunTrace]] = defaultdict(list)
        for trace in eligible_sorted:
            k = _pattern_key_success(trace)
            if len(k) > 1:  # 至少有一个工具调用
                bucket[k].append(trace)
        return dict(bucket)

    # ---------------- 冻结 replay set ----------------------------------------

    def freeze_replay_set(
        self, set_id: str, trace_ids: List[str]
    ) -> str:
        """冻结一个 replay set；返回 canonical hash。

        gate2 / gate3 / gate4 必须引用 hash，不可引用 mutable query
        （spec v1 §9.2.3 末段）。

        Raises:
            ValueError: 任一 trace_id 未入库 / 非 eligible / 列表内重复
            （Codex review 2026-05-27 C2[P2]：spec §9.2 行 901 unique 约束
            适用于 frozen set 内部，否则 hash 会包含重复 ID 误导 paired diff）.
        """
        # Codex C2[P2]：先去重检查（不允许列表内出现同 trace_id 多次）
        if len(set(trace_ids)) != len(trace_ids):
            from collections import Counter as _Counter
            dups = [tid for tid, n in _Counter(trace_ids).items() if n > 1]
            raise ValueError(
                f"freeze_replay_set: trace_ids 列表内有重复 ID {dups!r}，违反 "
                f"spec §9.2 行 901 unique 约束。canonical hash 必须基于去重 ID 列表。"
            )
        # 校验所有 trace_id 都已入库且 eligible
        for tid in trace_ids:
            if tid not in self._traces:
                raise ValueError(f"trace_id {tid} 未在 buffer")
            if not self._eligibility.get(tid, False):
                raise ValueError(f"trace_id {tid} 非 eligible，不得入 replay set")
        self._frozen_sets[set_id] = list(trace_ids)
        return _canonical_set_hash(trace_ids)

    def get_replay_set(self, set_id: str) -> List[EvoRunTrace]:
        """取冻结 set 内的 trace（保持 set 内顺序）。"""
        if set_id not in self._frozen_sets:
            raise KeyError(f"replay set {set_id} 未冻结")
        return [self._traces[tid] for tid in self._frozen_sets[set_id]]

    # ---------------- effective trace weight ----------------------------------

    def compute_effective_weight(
        self,
        trace: EvoRunTrace,
        *,
        novelty_seen_count: Optional[Dict[Tuple[str, ...], int]] = None,
        has_feedback: bool = False,
        coverage_class: str = "common",
    ) -> float:
        """spec v1 §9.2.3 effective_trace_weight 公式。

            validity_i × novelty_i × coverage_weight_i × feedback_available_i

        参数对照 spec：
            - validity_i：eligible=1 else 0
            - novelty_i：1.0 - 重复组合 1/sqrt(1+n) 衰减，下限 0.2
            - coverage_weight_i：common=1.0 / rare=1.5 / very_rare_audited=2.0 (cap 3.0)
            - feedback_available_i：1.2 / 1.0
        """
        validity = 1.0 if _trace_eligible(trace) else 0.0
        # novelty
        if novelty_seen_count is None:
            novelty = 1.0
        else:
            keys = _pattern_key_failure(trace) or [_pattern_key_success(trace)]
            min_novelty = 1.0
            for k in keys:
                n_seen = novelty_seen_count.get(tuple(k) if isinstance(k, tuple) else (k,), 0)
                if n_seen <= 0:
                    nv = 1.0
                else:
                    nv = 1.0 / math.sqrt(1.0 + n_seen)
                min_novelty = min(min_novelty, nv)
            novelty = max(min_novelty, 0.2)
        # coverage weight
        coverage_map = {
            "common": 1.0,
            "rare": 1.5,
            "very_rare_audited": 2.0,
        }
        coverage_weight = min(coverage_map.get(coverage_class, 1.0), 3.0)
        # feedback bonus
        feedback_weight = 1.2 if has_feedback else 1.0
        return validity * novelty * coverage_weight * feedback_weight


__all__ = ["ReplayBuffer"]
