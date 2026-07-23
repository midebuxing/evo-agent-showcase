"""EvoFeedbackBroker —— v1.1 角色降级为 runtime trend feedback 接口。

权威：spec v1 §8（`团队文档/我的笔记/蓝图汇总/evo-agent_v1_设计规格.md`）。

**v1.1 角色降级（spec §0.6 修订 1 + §2.1.4 + §8.1 + §8.6）**：

v1.0 把 broker 设为 "trainer 信号源"。v1.1 后 trainer 直接读 raw
``EvalTruthReport``（spec §2.1.3 / §2.5 凭证已加 ``evaluator_truth_store/raw``
读权限），不再走 broker。broker 的剩余角色降级为：

    **runtime agent 可选的"历史趋势反馈接口"** —— runtime LLM 想看跨 run 历史模式时
    可通过 tool 读取 packet。该接口在 v1.1 实验室阶段非必选实现；保留 broker
    代码作为接口契约，但 trainer 工作流不强制走 broker。

边界（v1.1 后）：
    - artifact 层 blind：runtime-loadable artifact 不得含 raw W2（约束未变）；
    - runtime 层 blind：runtime agent 不能直接读 W2 truth（约束未变）；
    - trainer 工作流 blind：v1.1 取消（trainer 可直接读 raw W2 算 reward/loss）；
    - broker 输出 packet：仍受 §8.4 / §8.5 k-anonymity / rounding 硬约束
      （为保 runtime 暴露通道时不泄漏 case-specific signal）。

本模块只负责"raw EvalTruthReport → SanitizedFeedbackPacket"的盲化转换；
不写入 EvoMemoryStore、不发布 packet、不调用 trainer。

设计要点：
    - 输入：`EvalTruthReport` dict（含 raw W2 expected_verdict / projection_refs
      / family_comparison 等，但 broker 内部处理后**不输出**任何 raw 字段）。
    - 输出：`SanitizedFeedbackPacket`，每个 cell 满足 spec v1 §8.4 / §8.5 硬约束。
    - 失败：抛 `BrokerLeakageError`（自定义异常）。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from evo_agent_baseline.contracts import (
    EvoRunTrace,
    FeedbackCell,
    SanitizedFeedbackPacket,
)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class BrokerLeakageError(RuntimeError):
    """Broker 盲化或 k-anonymity 检查失败的硬终止异常。

    spec v1 §8.4 / §8.5：任何 cell 残留 forbidden field、未通过 k-anonymity、
    或 reconstruction probe 超过 5pp 都必须中止发布；不得退化为静默 suppress。
    """


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# spec v1 §2.3.4 / §10.2 / §8.5：禁止出现在 sanitized cell 内的字段名。
# 涵盖 raw W2 reference 字段、raw evaluator note 字段、原始 run/building/world id。
_FORBIDDEN_CELL_KEYS: Tuple[str, ...] = (
    "expected_verdict",
    "projection_refs",
    "projection_id",
    "basis_item_refs",
    "basis_item_text",
    "family_comparison",
    "threshold_comparison",
    "evaluator_comment",
    "evaluator_note",
    "free_text",
    "run_id",
    "building_id",
    "world_id",
    "obligation_id",
    "raw_basis",
)

# spec v1 §8.4：单 cell 必须 ≥10 runs ≥3 buildings。
_K_RUN_MIN_DEFAULT = 10
_K_BUILDING_MIN_DEFAULT = 3


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_sha256(obj: Any) -> str:
    """spec v1 §3.8：canonical JSON + sha256 摘要。"""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _round_nearest_005(x: float) -> float:
    """spec v1 §8.4 / §8.8：metric 四舍五入到 0.05。"""
    return round(round(x / 0.05) * 0.05, 4)


def _bucket_low_medium_high(x: float) -> str:
    """spec v1 §8.4：枚举 bucket（[-1,1] 区间）。

    简单切分：<=-0.05 low / [-0.05, 0.05] medium / >=0.05 high。
    """
    if x <= -0.05:
        return "low"
    if x >= 0.05:
        return "high"
    return "medium"


def _format_delta_bucket(x: float) -> str:
    """spec v1 §9.4.6 record canonical form：`+0.05` / `-0.10` 等格式。"""
    rounded = _round_nearest_005(x)
    return f"{rounded:+.2f}"


def _contains_forbidden_dimension(dim: Dict[str, str]) -> List[str]:
    """检测 dimension dict 内的 forbidden key。"""
    hits: List[str] = []
    for k in dim.keys():
        if k in _FORBIDDEN_CELL_KEYS:
            hits.append(k)
    return hits


def _cell_has_forbidden(cell: FeedbackCell) -> List[str]:
    """对单 cell 全字段扫禁词。"""
    hits = _contains_forbidden_dimension(cell.dimension)
    for forbidden in _FORBIDDEN_CELL_KEYS:
        if forbidden in cell.metric_name.lower():
            hits.append(f"metric_name::{forbidden}")
    return hits


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------


class EvoFeedbackBroker:
    """spec v1 §8.3-§8.8 broker 实现。

    本类是有状态的工厂：构造时锁定 k-anonymity / rounding / release_delay 策略，
    每次 `ingest_eval_truth_report` 输出一个新 `SanitizedFeedbackPacket`。
    """

    def __init__(
        self,
        *,
        k_run_min: int = _K_RUN_MIN_DEFAULT,
        k_building_min: int = _K_BUILDING_MIN_DEFAULT,
        rounding_policy: str = "nearest_0.05",
        release_delay_windows: int = 1,
    ) -> None:
        """构造 broker（k-anonymity / rounding / release_delay 策略）。

        **v1.1 修订（spec §8.1 / §8.6）**：``release_delay_windows`` 默认仍为 1
        但**不强制** ≥1（v1.0 强制延迟发布是为生产 traffic 假设服务，实验室
        阶段无意义；§8.6 整段删）。broker 角色降级为 runtime trend feedback
        接口，trainer 工作流不强制走 broker。

        Args:
            k_run_min: 单 cell 最少 runs（spec §8.4 k-anonymity 硬约束，未变）。
            k_building_min: 单 cell 最少 buildings（同上）。
            rounding_policy: ``nearest_0.05`` 或 ``bucket_low_medium_high``。
            release_delay_windows: v1.1 后非强制；仅当真用作 runtime trend
                feedback 接口且需要延迟暴露时填非零。允许传 0 / 负数（不抛错），
                但 ``apply_release_delay`` 方法仍要求 ≥1。
        """
        if k_run_min < 1 or k_building_min < 1:
            raise ValueError("k_run_min / k_building_min 必须 >= 1")
        if rounding_policy not in {"nearest_0.05", "bucket_low_medium_high"}:
            raise ValueError(f"rounding_policy 不支持: {rounding_policy}")
        # v1.1 §0.6 修订 2 + §8.6：取消 release_delay_windows >= 1 硬约束
        # （broker 角色降级，延迟发布在实验室阶段非必选）
        self.k_run_min = k_run_min
        self.k_building_min = k_building_min
        self.rounding_policy = rounding_policy
        self.release_delay_windows = release_delay_windows

    # ---------------- 主入口 -------------------------------------------------

    def ingest_eval_truth_report(
        self,
        raw_report: Dict[str, Any],
        *,
        aggregation_level: str = "batch_rule_family",
    ) -> SanitizedFeedbackPacket:
        """spec v1 §8.3：消费 raw `EvalTruthReport`，输出 SanitizedFeedbackPacket。

        流程对照 spec v1 §8.8 broker_release pseudocode：
            1. aggregate；
            2. remove_ids + round + k-anon；
            3. forbidden scan；
            4. release delay 标记；
            5. packet build + canonical hash。
        """
        if "eval_window_id" not in raw_report:
            raise BrokerLeakageError("raw_report 缺 eval_window_id")
        if "per_run_results" not in raw_report:
            raise BrokerLeakageError("raw_report 缺 per_run_results")

        raw_hash = _canonical_sha256(raw_report)
        cells = self.aggregate_to_batch(raw_report, aggregation_level)
        cells = self.apply_k_anonymity(cells)
        cells = self.apply_rounding(cells)

        # spec v1 §8.4：硬性条件——packet 层 run_count ≥ 10 / building_count ≥ 3。
        packet_run_count = self._count_runs(raw_report)
        packet_building_count = self._count_buildings(raw_report)
        k_anon_passed = (
            packet_run_count >= self.k_run_min
            and packet_building_count >= self.k_building_min
        )

        # forbidden_scan：cell + raw_report 路径标志位
        packet_id = f"SFP-{raw_report['eval_window_id']}-{raw_hash[:12]}"
        packet = SanitizedFeedbackPacket(
            feedback_packet_id=packet_id,
            eval_window_id=raw_report["eval_window_id"],
            source_eval_truth_report_hash=raw_hash,
            aggregation_level=aggregation_level,  # type: ignore[arg-type]
            run_count=packet_run_count,
            building_count=packet_building_count,
            cell_count=len(cells),
            rounding_policy=self.rounding_policy,  # type: ignore[arg-type]
            release_delay_window_count=self.release_delay_windows,
            cells=cells,
            forbidden_scan_passed=False,  # 先占位，下面 run_forbidden_scan 后回填
            k_anonymity_passed=k_anon_passed,
            reconstruction_audit_passed=False,  # 调用者负责 run_reconstruction_audit
            created_at=_utc_now_iso(),
            released_at=_utc_now_iso(),
        )
        # 内置 forbidden scan（不消费 agent traces）
        if not self.run_forbidden_scan(packet):
            raise BrokerLeakageError(
                f"forbidden scan 失败：packet={packet_id} 含 forbidden 字段"
            )
        # mutate 已校验后的 packet 字段（pydantic v2 允许 model_copy）
        packet = packet.model_copy(update={"forbidden_scan_passed": True})

        if not k_anon_passed:
            raise BrokerLeakageError(
                f"k-anonymity 失败：runs={packet_run_count} buildings={packet_building_count} "
                f"未达 k_run_min={self.k_run_min} / k_building_min={self.k_building_min}"
            )

        return packet

    # ---------------- aggregate ----------------------------------------------

    def aggregate_to_batch(
        self, raw_report: Dict[str, Any], aggregation_level: str
    ) -> List[FeedbackCell]:
        """spec v1 §8.4：把 per-run results 聚合到 batch 维度。

        支持 4 个 aggregation_level（spec v1 §3.6.5）：
            batch_rule_family / batch_slot_class / batch_obligation_kind /
            batch_error_taxonomy
        """
        legal = {
            "batch_rule_family",
            "batch_slot_class",
            "batch_obligation_kind",
            "batch_error_taxonomy",
        }
        if aggregation_level not in legal:
            raise ValueError(f"非法 aggregation_level={aggregation_level}")

        # key = canonical dimension tuple → (run_set, building_set, metric_sum, n)
        bucket: Dict[Tuple[Tuple[str, str], ...], Dict[str, Any]] = defaultdict(
            lambda: {
                "runs": set(),
                "buildings": set(),
                "metric_sum": 0.0,
                "n": 0,
                "metric_name": None,
                "suggested_evo_action": None,
            }
        )

        for per_run in raw_report.get("per_run_results", []):
            for cell_raw in per_run.get("aggregable_cells", []):
                dim_key = self._dimension_key_for_level(cell_raw, aggregation_level)
                if dim_key is None:
                    continue
                slot = bucket[dim_key]
                slot["runs"].add(per_run.get("run_id"))
                if "building_id" in per_run:
                    slot["buildings"].add(per_run["building_id"])
                slot["metric_sum"] += float(cell_raw.get("metric_value", 0.0))
                slot["n"] += 1
                slot["metric_name"] = cell_raw.get("metric_name")
                # 触发 suggestion 透传（broker 不更名，下游 induction 决定）
                if cell_raw.get("suggested_evo_action"):
                    slot["suggested_evo_action"] = cell_raw["suggested_evo_action"]

        cells: List[FeedbackCell] = []
        packet_window = raw_report.get("eval_window_id", "EW-unknown")
        for idx, (dim_key, slot) in enumerate(sorted(bucket.items())):
            dim: Dict[str, str] = dict(dim_key)
            mean = slot["metric_sum"] / slot["n"] if slot["n"] else 0.0
            cell = FeedbackCell(
                feedback_cell_id=f"SFP-{packet_window}-cell-{idx}",
                feedback_packet_id=f"SFP-{packet_window}",
                dimension=dim,
                metric_name=str(slot["metric_name"] or "unknown_metric"),
                metric_bucket=f"{mean:.4f}",  # 未 round；下游 apply_rounding 处理
                delta_bucket=f"{mean:+.4f}",  # 未 round；下游 apply_rounding 处理
                run_count=len(slot["runs"]),
                building_count=len(slot["buildings"]),
                suppressed=False,
                suppression_reason=None,
                suggested_evo_action=slot["suggested_evo_action"],
            )
            cells.append(cell)
        return cells

    def _dimension_key_for_level(
        self, cell_raw: Dict[str, Any], level: str
    ) -> Optional[Tuple[Tuple[str, str], ...]]:
        dim_raw = cell_raw.get("dimension", {})
        if level == "batch_rule_family":
            v = dim_raw.get("rule_family")
            if not v:
                return None
            return (("rule_family", str(v)),)
        if level == "batch_slot_class":
            v = dim_raw.get("semantic_slot_class")
            if not v:
                return None
            obl = dim_raw.get("obligation_kind", "")
            return (("semantic_slot_class", str(v)), ("obligation_kind", str(obl)))
        if level == "batch_obligation_kind":
            v = dim_raw.get("obligation_kind")
            if not v:
                return None
            return (("obligation_kind", str(v)),)
        if level == "batch_error_taxonomy":
            v = dim_raw.get("error_code")
            if not v:
                return None
            return (("error_code", str(v)),)
        return None

    # ---------------- k-anonymity --------------------------------------------

    def apply_k_anonymity(
        self,
        cells: List[FeedbackCell],
        min_runs: int = _K_RUN_MIN_DEFAULT,
        min_buildings: int = _K_BUILDING_MIN_DEFAULT,
    ) -> List[FeedbackCell]:
        """spec v1 §8.5：cell 不满足 k-anonymity 转 suppressed=True 不输出 metric。

        优先级（spec v1 §8.5）：合并到更粗 taxonomy → 仍不满足则 suppress。
        baseline 仅实现 suppress 路径；coarser-merge 留 hook（trainer 可在 layer F2
        重新发起更粗粒度的 ingest）。
        """
        out: List[FeedbackCell] = []
        for cell in cells:
            run_ok = cell.run_count >= max(min_runs, self.k_run_min)
            bld_ok = cell.building_count >= max(min_buildings, self.k_building_min)
            if run_ok and bld_ok:
                out.append(cell)
                continue
            suppressed = cell.model_copy(
                update={
                    "suppressed": True,
                    "suppression_reason": (
                        f"k_anonymity_min_runs={min_runs}_min_buildings={min_buildings}"
                        f"_actual_runs={cell.run_count}_buildings={cell.building_count}"
                    ),
                    "metric_bucket": "suppressed",
                    "delta_bucket": None,
                }
            )
            out.append(suppressed)
        return out

    # ---------------- rounding -----------------------------------------------

    def apply_rounding(
        self, cells: List[FeedbackCell], policy: Optional[str] = None
    ) -> List[FeedbackCell]:
        """spec v1 §8.4：metric_bucket 四舍五入 0.05 或枚举 low/medium/high。"""
        effective_policy = policy or self.rounding_policy
        out: List[FeedbackCell] = []
        for cell in cells:
            if cell.suppressed:
                out.append(cell)
                continue
            try:
                raw_metric = float(cell.metric_bucket)
            except (TypeError, ValueError):
                # 已经是 bucket label，直接保留
                out.append(cell)
                continue
            if effective_policy == "nearest_0.05":
                new_bucket = f"{_round_nearest_005(raw_metric):.2f}"
            elif effective_policy == "bucket_low_medium_high":
                new_bucket = _bucket_low_medium_high(raw_metric)
            else:
                raise ValueError(f"非法 rounding policy={effective_policy}")
            delta_str: Optional[str]
            if cell.delta_bucket is not None:
                try:
                    delta_str = _format_delta_bucket(float(cell.delta_bucket))
                except (TypeError, ValueError):
                    delta_str = cell.delta_bucket
            else:
                delta_str = None
            out.append(
                cell.model_copy(
                    update={"metric_bucket": new_bucket, "delta_bucket": delta_str}
                )
            )
        return out

    # ---------------- release delay ------------------------------------------

    def apply_release_delay(
        self, packet: SanitizedFeedbackPacket, delay_windows: int = 1
    ) -> SanitizedFeedbackPacket:
        """spec v1 §8.6（v1.1 删）：W2-derived feedback 延迟发布。

        baseline 通过把 `released_at` 推迟 `delay_windows * 24h` 实现。

        **v1.1 注（spec §0.6 修订 2 + §8.6）**：实验室阶段非必选；仅当 broker 真用作
        runtime trend feedback 接口且需要延迟暴露时调用本方法。本方法本身仍
        要求 ``delay_windows >= 1``（API 契约不变；实验脚本若不需要延迟，
        直接不调用即可）。spec §8.6 整段在 v1.1 删除，本方法保留供历史兼容。
        """
        if delay_windows < 1:
            raise ValueError("delay_windows 必须 >= 1（spec v1 §8.6 历史契约）")
        created_dt = datetime.strptime(packet.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        released = created_dt + timedelta(days=delay_windows)
        return packet.model_copy(
            update={
                "release_delay_window_count": delay_windows,
                "released_at": released.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    # ---------------- reconstruction audit -----------------------------------

    def run_reconstruction_audit(
        self,
        packet: SanitizedFeedbackPacket,
        agent_visible_traces: Sequence[EvoRunTrace],
    ) -> bool:
        """spec v1 §8.7.3（v1.1 语义重定位）：W2 reconstruction probe。

        合规阈值（spec v1 §8.7.3 / §8.8）：
            用 agent-visible trace + sanitized feedback 预测 per-run expected outcome；
            若相对 prior accuracy 提升超过 5pp，则 audit fail。

        baseline 实现：用 cell.delta_bucket / metric_bucket 的 *信息熵* 作为
        proxy delta —— 若所有 cell 的 metric 全部同 bucket（无信息差），probe delta=0；
        若分布越平均，delta 越接近 prior baseline 上限。
        当 cell_count == 0 视为 0 信息增益（通过）。

        完整实现需要 evaluator-side LLM 探针，此 baseline 不接 LLM，故只检查
        必要数据 invariant：
            - agent_visible_traces 必须非空（否则不能做 probe）
            - packet.cells 任意 suppressed=False 的 metric_bucket 不得是空字符串

        **v1.1 注（spec §0.6 修订 1 + §8.7.3 + §11.9）**：本方法的语义已重定位
        ——现在 reconstruction audit 的真正落点在 **artifact 端**（trainer 输出的
        candidate SkillPackage / candidate EvoPolicyVersion）而非 packet 端，详见
        ``evo_agent_baseline.evo.audits.adversarial_reconstruction_audit``。
        本 packet-端的 entropy proxy 保留供历史兼容；新代码请把 audit 焦点放在
        artifact 端。
        """
        if not agent_visible_traces and packet.cells:
            # 无 agent trace 无法做 probe，spec v1 §8.7.3 要求 probe 成功才发布。
            # baseline 容忍：若 packet 中所有 cell suppressed 也可通过。
            if any(not c.suppressed for c in packet.cells):
                return False
        # 简单 entropy proxy
        non_suppressed = [c for c in packet.cells if not c.suppressed]
        if not non_suppressed:
            return True
        bucket_counts: Dict[str, int] = defaultdict(int)
        for c in non_suppressed:
            bucket_counts[c.metric_bucket] += 1
        total = sum(bucket_counts.values())
        # Shannon entropy
        entropy = 0.0
        for v in bucket_counts.values():
            p = v / total
            if p > 0:
                entropy -= p * math.log2(p)
        # 若 entropy < 0.5（绝大多数 cell 同 bucket），probe delta 应近 0，pass
        # 若 entropy > log2(N) - 0.1（分布几乎均匀），prior baseline 已经接近上限
        # spec v1 §8.7.3 阈值 5pp 在 baseline 用启发式：entropy 在合理区间即通过
        max_entropy = math.log2(max(total, 2))
        # delta = entropy / max_entropy ∈ [0,1]
        # 经验：若 delta > 0.95 视为"分布过度均匀，probe 提升可能 >5pp"
        delta = entropy / max_entropy if max_entropy > 0 else 0.0
        return delta <= 0.95

    # ---------------- forbidden scan -----------------------------------------

    def run_forbidden_scan(self, packet: SanitizedFeedbackPacket) -> bool:
        """spec v1 §8.7.1：packet schema/text 无 forbidden field/phrase。"""
        # packet 顶层字段名硬白名单已由 Pydantic `extra=forbid` 保证。
        # 这里扫每个 cell 的 dimension / metric_name 是否含 forbidden 字段
        for cell in packet.cells:
            hits = _cell_has_forbidden(cell)
            if hits:
                return False
        return True

    # ---------------- 内部辅助 -----------------------------------------------

    def _count_runs(self, raw_report: Dict[str, Any]) -> int:
        runs = raw_report.get("runs_evaluated")
        if isinstance(runs, list):
            return len(runs)
        per_run = raw_report.get("per_run_results", [])
        return len({r.get("run_id") for r in per_run if r.get("run_id")})

    def _count_buildings(self, raw_report: Dict[str, Any]) -> int:
        per_run = raw_report.get("per_run_results", [])
        return len({r.get("building_id") for r in per_run if r.get("building_id")})


__all__ = ["EvoFeedbackBroker", "BrokerLeakageError"]
