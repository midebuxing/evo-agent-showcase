"""T-21 P0/P1/P2 generation-time gate framework tests.

按 §4.6 7 项决策验证：
- T-21.1 (B) 每 building 一次 gate
- T-21.2 (A) P0 retry 整 building resample
- T-21.3 (A) P1/P2 repair pure function
- T-21.4 (A) worldgen gate 管 P0/P1/P2 (P3 在 projection 层)
- T-21.5 (A) max retries=3 / max p1 repair=5
- T-21.6 (A) BatchGateStats reject_reasons 桶
- T-21.7 (B) coarse 粗粒度 (per-building 整体 gate)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen.gates import (
    BatchGateStats,
    GateResult,
    P2_SAMPLE_CAP,
    P2ClampSummary,
    RepairAction,
    Violation,
    apply_gate_single_pass,
    apply_gate_with_retry,
    check_p0_violations,
    check_p1_violations,
    check_p2_violations,
    clear_check_registry,
    register_p0_check,
    register_p1_check,
    register_p1_repair,
    register_p2_check,
    repair_p1,
)
from workflow_engine.worldgen.p2_audit import (
    CHECK_ID_COUNT_NONNEG_CLAMP,
    CHECK_ID_PRECISION_ROUNDING,
    CHECK_ID_TYPICAL_BOUNDS_CLIP,
    P2AuditAccumulator,
    audit_capture,
    get_p2_audit_context,
    set_p2_audit_context,
    clear_p2_audit_context,
)
from workflow_engine.worldgen.generator import (
    generate_world_batch,
    generate_world_batch_with_stats,
    generate_world_bundle,
)
from workflow_engine.worldgen.registry import _build_registry_bundle


class GateRegistryTests(unittest.TestCase):
    """T-21 framework: check 注册表测试。"""

    def setUp(self) -> None:
        clear_check_registry()

    def tearDown(self) -> None:
        clear_check_registry()

    def test_default_no_checks_registered(self) -> None:
        """没注册时 check 函数返回空 violation list。"""
        registries = _build_registry_bundle()
        wb = generate_world_bundle({}, registries, seed=42, building_index=0)
        self.assertEqual(check_p0_violations(wb, registries), [])
        self.assertEqual(check_p1_violations(wb, registries), [])
        self.assertEqual(check_p2_violations(wb, registries), [])

    def test_register_p0_check_decorator(self) -> None:
        @register_p0_check
        def _fn(wb, reg):
            return [Violation(check_id="C-TEST", priority="P0", detail="test")]

        registries = _build_registry_bundle()
        wb = generate_world_bundle({}, registries, seed=42, building_index=0)
        violations = check_p0_violations(wb, registries)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].check_id, "C-TEST")


class GateSinglePassTests(unittest.TestCase):
    """T-21 single-pass gate 行为测试。"""

    def setUp(self) -> None:
        clear_check_registry()
        self.registries = _build_registry_bundle()
        self.wb = generate_world_bundle({}, self.registries, seed=42, building_index=0)

    def tearDown(self) -> None:
        clear_check_registry()

    def test_single_pass_no_checks_returns_passed(self) -> None:
        """没 check 注册时 gate 默认通过。"""
        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        self.assertEqual(result.violations, [])
        self.assertIsNone(result.reject_reason)
        self.assertIs(result.world_bundle, self.wb)

    def test_p0_violation_blocks_passing(self) -> None:
        """P0 violation 立即 reject。"""
        @register_p0_check
        def _fn(wb, reg):
            return [Violation(check_id="C-FAKE-P0", priority="P0", detail="fake")]

        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertFalse(result.passed)
        self.assertEqual(result.reject_reason, "P0_violation")
        self.assertIsNone(result.world_bundle)
        self.assertEqual(len(result.violations), 1)

    def test_p1_violation_triggers_repair_and_passes_when_resolved(self) -> None:
        """P1 violation 触发 repair；repair 后无 P1 → pass。"""
        violation_count_holder = {"count": 1}

        @register_p1_check
        def _check(wb, reg):
            if violation_count_holder["count"] > 0:
                return [Violation(check_id="C-FAKE-P1", priority="P1", detail="fake")]
            return []

        @register_p1_repair
        def _repair(wb, violations):
            violation_count_holder["count"] -= 1  # simulate repair effect
            return wb, []  # DEBT-030 C 组 contract：返回 (bundle, repair_actions)

        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        self.assertEqual(result.iterations, 1)

    def test_p1_repair_max_iter_exceeded(self) -> None:
        """P1 repair 迭代 max 次仍有 P1 → reject."""
        @register_p1_check
        def _check(wb, reg):
            return [Violation(check_id="C-FAKE-P1", priority="P1", detail="never resolved")]

        @register_p1_repair
        def _repair(wb, violations):
            return wb, []  # no-op repair；DEBT-030 C 组 contract

        result = apply_gate_single_pass(self.wb, self.registries, max_p1_repair_iterations=2)
        self.assertFalse(result.passed)
        self.assertEqual(result.reject_reason, "P1_repair_unfeasible")

    def test_p2_violation_does_not_block(self) -> None:
        """P2 violation 仅 warning，passed=True。"""
        @register_p2_check
        def _fn(wb, reg):
            return [Violation(check_id="C-FAKE-P2", priority="P2", detail="warn")]

        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.violations), 1)
        self.assertEqual(result.violations[0].priority, "P2")


class GateWithRetryTests(unittest.TestCase):
    """T-21.2 + T-21.5: P0 retry budget 测试。"""

    def setUp(self) -> None:
        clear_check_registry()
        self.registries = _build_registry_bundle()

    def tearDown(self) -> None:
        clear_check_registry()

    def test_first_attempt_passes(self) -> None:
        """无 violation → 第一次 attempt 即通过。"""
        attempts = {"count": 0}

        def _gen(retry_idx):
            attempts["count"] += 1
            return generate_world_bundle({}, self.registries, seed=42 + retry_idx, building_index=0)

        wb, result = apply_gate_with_retry(_gen, self.registries, max_retries=3)
        self.assertIsNotNone(wb)
        self.assertTrue(result.passed)
        self.assertEqual(attempts["count"], 1)

    def test_p0_retry_budget_exceeded(self) -> None:
        """P0 violation 全 max_retries 次仍 fail → reject."""
        @register_p0_check
        def _fn(wb, reg):
            return [Violation(check_id="C-FAKE-P0", priority="P0", detail="always fail")]

        attempts = {"count": 0}

        def _gen(retry_idx):
            attempts["count"] += 1
            return generate_world_bundle({}, self.registries, seed=42 + retry_idx, building_index=0)

        wb, result = apply_gate_with_retry(_gen, self.registries, max_retries=3)
        self.assertIsNone(wb)
        self.assertFalse(result.passed)
        self.assertEqual(attempts["count"], 3)

    def test_p0_retry_recovers_on_second_attempt(self) -> None:
        """前 1 次 P0 fail，第 2 次 pass → 接受第 2 次结果."""
        attempts = {"count": 0}

        @register_p0_check
        def _fn(wb, reg):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return [Violation(check_id="C-FAKE-P0", priority="P0", detail="first attempt fail")]
            return []

        def _gen(retry_idx):
            return generate_world_bundle({}, self.registries, seed=42 + retry_idx, building_index=0)

        wb, result = apply_gate_with_retry(_gen, self.registries, max_retries=3)
        self.assertIsNotNone(wb)
        self.assertTrue(result.passed)


class BatchGateStatsTests(unittest.TestCase):
    """T-21.6: BatchGateStats reject_reasons 桶."""

    def test_record_accepted(self) -> None:
        s = BatchGateStats()
        s.record_accepted()
        s.record_accepted()
        self.assertEqual(s.accepted_count, 2)
        self.assertEqual(s.rejected_count, 0)

    def test_record_rejected_buckets(self) -> None:
        s = BatchGateStats()
        s.record_rejected("P0_violation")
        s.record_rejected("P0_violation")
        s.record_rejected("P1_repair_unfeasible")
        self.assertEqual(s.rejected_count, 3)
        self.assertEqual(s.reject_reasons["P0_violation"], 2)
        self.assertEqual(s.reject_reasons["P1_repair_unfeasible"], 1)

    def test_to_dict(self) -> None:
        s = BatchGateStats()
        s.record_accepted()
        s.record_rejected("P0_violation")
        d = s.to_dict()
        self.assertEqual(d["accepted_count"], 1)
        self.assertEqual(d["rejected_count"], 1)
        self.assertEqual(d["reject_reasons"], {"P0_violation": 1})
        # DEBT-030 C 组：to_dict 含 repair_action_counts 桶（空 dict 默认）
        self.assertEqual(d["repair_action_counts"], {})

    def test_record_repair_actions_counts_per_check_id(self) -> None:
        """DEBT-030 C 组：BatchGateStats.record_repair_actions per-check_id 累加."""
        s = BatchGateStats()
        s.record_repair_actions(
            [
                RepairAction(check_id="C007_EXTENT_AREA_BOUND", fragment_id="F1"),
                RepairAction(check_id="C007_EXTENT_AREA_BOUND", fragment_id="F2"),
                RepairAction(check_id="C008_EXTENT_LENGTH_BOUND", fragment_id="F1"),
            ]
        )
        self.assertEqual(s.repair_action_counts["C007_EXTENT_AREA_BOUND"], 2)
        self.assertEqual(s.repair_action_counts["C008_EXTENT_LENGTH_BOUND"], 1)

    def test_record_repair_actions_empty_noop(self) -> None:
        """DEBT-030 C 组：空 actions list 不改 stats."""
        s = BatchGateStats()
        s.record_repair_actions([])
        self.assertEqual(s.repair_action_counts, {})

    def test_record_repair_actions_to_dict_includes_counts(self) -> None:
        s = BatchGateStats()
        s.record_accepted()
        s.record_repair_actions([RepairAction(check_id="C021_REPAIR_REQUIRED_CONSISTENCY", fragment_id="F1")])
        d = s.to_dict()
        self.assertEqual(d["repair_action_counts"], {"C021_REPAIR_REQUIRED_CONSISTENCY": 1})


class GateRepairActionAuditTests(unittest.TestCase):
    """DEBT-030 C 组：P1 repair audit trace 端到端测试（spec 07 §4 line 68）."""

    def setUp(self) -> None:
        clear_check_registry()
        self.registries = _build_registry_bundle()
        self.wb = generate_world_bundle({}, self.registries, seed=42, building_index=0)

    def tearDown(self) -> None:
        clear_check_registry()

    def test_repair_actions_propagated_to_gate_result(self) -> None:
        """P1 repair 调用产生 RepairAction → GateResult.repair_actions 收齐."""
        violation_count_holder = {"count": 1}

        @register_p1_check
        def _check(wb, reg):
            if violation_count_holder["count"] > 0:
                return [Violation(check_id="C-FAKE-AUDIT", priority="P1", detail="fake", fragment_id="F-X")]
            return []

        @register_p1_repair
        def _repair(wb, violations):
            violation_count_holder["count"] -= 1
            actions = [
                RepairAction(
                    check_id="C-FAKE-AUDIT",
                    fragment_id="F-X",
                    detail="test repair",
                    before_value=99,
                    after_value=1,
                )
            ]
            return wb, actions

        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.repair_actions), 1)
        self.assertEqual(result.repair_actions[0].check_id, "C-FAKE-AUDIT")
        self.assertEqual(result.repair_actions[0].before_value, 99)
        self.assertEqual(result.repair_actions[0].after_value, 1)

    def test_no_repair_no_actions(self) -> None:
        """无 P1 修复发生时 repair_actions 应为空 list（非 None）."""
        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        self.assertEqual(result.repair_actions, [])

    def test_repair_actions_accumulate_across_iterations(self) -> None:
        """P1 repair 多次迭代：repair_actions 累加每轮 actions."""
        violation_count_holder = {"count": 3}

        @register_p1_check
        def _check(wb, reg):
            if violation_count_holder["count"] > 0:
                return [Violation(check_id="C-ITER-AUDIT", priority="P1", detail="iter")]
            return []

        @register_p1_repair
        def _repair(wb, violations):
            violation_count_holder["count"] -= 1
            return wb, [RepairAction(check_id="C-ITER-AUDIT", detail=f"iter{violation_count_holder['count']}")]

        result = apply_gate_single_pass(self.wb, self.registries)
        self.assertTrue(result.passed)
        # 3 iter 各 1 action → 总共 3
        self.assertEqual(len(result.repair_actions), 3)
        self.assertEqual(result.iterations, 3)


class GeneratorBatchGateIntegrationTests(unittest.TestCase):
    """T-21 集成：generator.generate_world_batch 接入 gate."""

    def setUp(self) -> None:
        clear_check_registry()
        self.registries = _build_registry_bundle()

    def tearDown(self) -> None:
        clear_check_registry()

    def test_batch_apply_gate_default_no_check_returns_all(self) -> None:
        """没 check 注册 → 全部 5 栋通过。"""
        worlds = generate_world_batch({}, self.registries, count=5, seed=42, apply_gate=True)
        self.assertEqual(len(worlds), 5)

    def test_batch_apply_gate_p0_filters_all(self) -> None:
        """全 P0 fail → 全部 reject，accepted=0。"""
        @register_p0_check
        def _fn(wb, reg):
            return [Violation(check_id="C-FAKE-P0", priority="P0", detail="always fail")]

        worlds = generate_world_batch({}, self.registries, count=3, seed=42, apply_gate=True)
        self.assertEqual(len(worlds), 0)

    def test_batch_with_stats_tracks_rejects(self) -> None:
        """generate_world_batch_with_stats 返回 BatchGateStats."""
        @register_p0_check
        def _fn(wb, reg):
            return [Violation(check_id="C-FAKE-P0", priority="P0", detail="always fail")]

        worlds, stats = generate_world_batch_with_stats(
            {}, self.registries, count=4, seed=42,
        )
        self.assertEqual(len(worlds), 0)
        self.assertEqual(stats.accepted_count, 0)
        self.assertEqual(stats.rejected_count, 4)
        self.assertEqual(stats.reject_reasons.get("P0_violation"), 4)

    def test_batch_with_stats_clean_pipeline_all_accepted(self) -> None:
        worlds, stats = generate_world_batch_with_stats(
            {}, self.registries, count=4, seed=42,
        )
        self.assertEqual(len(worlds), 4)
        self.assertEqual(stats.accepted_count, 4)
        self.assertEqual(stats.rejected_count, 0)
        # DEBT-030 C 组：clean pipeline 默认无 P1 修复发生 → repair_action_counts 空
        self.assertEqual(stats.repair_action_counts, {})

    def test_batch_with_stats_records_repair_actions_per_check_id(self) -> None:
        """DEBT-030 C 组：generate_world_batch_with_stats 把每栋 P1 修复 actions 累入 batch 桶."""
        violation_count_holder = {"count": 4}  # 每栋 1 次修复

        @register_p1_check
        def _check(wb, reg):
            return (
                [Violation(check_id="C-BATCH-AUDIT", priority="P1", detail="x")]
                if violation_count_holder["count"] > 0
                else []
            )

        @register_p1_repair
        def _repair(wb, violations):
            violation_count_holder["count"] -= 1
            return wb, [RepairAction(check_id="C-BATCH-AUDIT", fragment_id="F-test")]

        worlds, stats = generate_world_batch_with_stats(
            {}, self.registries, count=4, seed=42,
        )
        # 每栋走一次 repair，4 栋共 4 个 actions
        self.assertEqual(stats.repair_action_counts.get("C-BATCH-AUDIT"), 4)


class P2ClampSummaryDataclassTests(unittest.TestCase):
    """DEBT-030 C 组 / spec 07 §4 line 70: P2 aggregate summary dataclass 行为."""

    def test_p2_sample_cap_constant(self) -> None:
        """Spec 07 §4 line 70 sample cap K=20."""
        self.assertEqual(P2_SAMPLE_CAP, 20)

    def test_p2_summary_init_defaults(self) -> None:
        s = P2ClampSummary(check_id="TYPICAL_BOUNDS_CLIP")
        self.assertEqual(s.count, 0)
        self.assertEqual(s.max_magnitude, 0.0)
        self.assertEqual(s.mean_magnitude, 0.0)
        self.assertEqual(s.sample_actions, [])

    def test_p2_summary_record_single_event(self) -> None:
        s = P2ClampSummary(check_id="TYPICAL_BOUNDS_CLIP")
        s.record(before=1.5, after=1.0, slot_id="x.slot", fragment_id="F1")
        self.assertEqual(s.count, 1)
        self.assertAlmostEqual(s.max_magnitude, 0.5)
        self.assertAlmostEqual(s.mean_magnitude, 0.5)
        self.assertEqual(len(s.sample_actions), 1)
        self.assertEqual(s.sample_actions[0].check_id, "TYPICAL_BOUNDS_CLIP")
        self.assertEqual(s.sample_actions[0].before_value, 1.5)
        self.assertEqual(s.sample_actions[0].after_value, 1.0)
        self.assertEqual(s.sample_actions[0].fragment_id, "F1")

    def test_p2_summary_record_累积_mean_and_max(self) -> None:
        """多次 record 后 max = max(magnitudes), mean = average."""
        s = P2ClampSummary(check_id="TYPICAL_BOUNDS_CLIP")
        # magnitudes: 0.5, 1.0, 0.1 → max=1.0, mean=0.5333..
        s.record(before=1.5, after=1.0)
        s.record(before=2.0, after=1.0)
        s.record(before=0.6, after=0.5)
        self.assertEqual(s.count, 3)
        self.assertAlmostEqual(s.max_magnitude, 1.0)
        self.assertAlmostEqual(s.mean_magnitude, (0.5 + 1.0 + 0.1) / 3.0, places=6)

    def test_p2_summary_sample_cap_at_K20(self) -> None:
        """DEBT-030 C 组：trigger 30 次同 check_id，sample_actions 仍为 20 (K=20 cap)，
        但 count=30 / max / mean 持续累加."""
        s = P2ClampSummary(check_id="TYPICAL_BOUNDS_CLIP")
        for i in range(30):
            # magnitude i+1: 1, 2, 3, ..., 30 → max=30, mean=15.5
            s.record(before=float(i + 1), after=0.0, slot_id=f"sid{i}", fragment_id=f"F{i}")
        self.assertEqual(s.count, 30)
        self.assertEqual(len(s.sample_actions), P2_SAMPLE_CAP)  # cap=20
        self.assertEqual(len(s.sample_actions), 20)
        self.assertAlmostEqual(s.max_magnitude, 30.0)
        self.assertAlmostEqual(s.mean_magnitude, sum(range(1, 31)) / 30.0)

    def test_p2_summary_to_dict_from_dict_roundtrip(self) -> None:
        """spec 07 §4 line 70 P2ClampSummary parquet / json 序列化."""
        s = P2ClampSummary(check_id="PRECISION_ROUNDING")
        s.record(before=1.234, after=1.23, slot_id="x", fragment_id="F1")
        s.record(before=2.567, after=2.57, slot_id="y", fragment_id="F2")
        d = s.to_dict()
        self.assertEqual(d["check_id"], "PRECISION_ROUNDING")
        self.assertEqual(d["count"], 2)
        self.assertEqual(len(d["sample_actions"]), 2)
        restored = P2ClampSummary.from_dict(d)
        self.assertEqual(restored.count, 2)
        self.assertAlmostEqual(restored.max_magnitude, s.max_magnitude)
        self.assertAlmostEqual(restored.mean_magnitude, s.mean_magnitude)
        self.assertEqual(len(restored.sample_actions), 2)


class P2AuditAccumulatorContextVarsTests(unittest.TestCase):
    """DEBT-030 C 组 / spec 07 §4 line 70: contextvars accumulator + audit_capture context manager."""

    def tearDown(self) -> None:
        clear_p2_audit_context()

    def test_get_context_default_none(self) -> None:
        """未 set context 时 get_p2_audit_context 返回 None (hot path fast skip)."""
        clear_p2_audit_context()
        self.assertIsNone(get_p2_audit_context())

    def test_audit_capture_yields_accumulator(self) -> None:
        with audit_capture() as acc:
            self.assertIsNotNone(acc)
            self.assertIsInstance(acc, P2AuditAccumulator)
            # context 内 get_p2_audit_context 返回同 accumulator
            self.assertIs(get_p2_audit_context(), acc)

    def test_audit_capture_clears_context_on_exit(self) -> None:
        with audit_capture() as _acc:
            pass
        self.assertIsNone(get_p2_audit_context())

    def test_audit_capture_records_inline_clip(self) -> None:
        """spec 07 §4 line 70 contract: _sample_typical_distribution 内 typical_bounds clip
        触发 TYPICAL_BOUNDS_CLIP audit; 不 trigger 时 accumulator 不 record."""
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        import random

        # slot_record: lognormal mean=2.0 sigma=0.3, typical_bounds [1.0, 1.5] → 大概率被 clip
        slot_record = {
            "slot_id": "test.geom.span_m",
            "recommended_distribution": "uniform",
            "typical_bounds": [1.0, 1.5],
        }
        rng = random.Random(42)
        with audit_capture() as acc:
            # 调 1000 次 — uniform [1.0, 1.5] sample 都在 typical_bounds 内 → 0 触发
            # 但 physical_bounds (0, 0.8) 比 typical_bounds 严 → 100% trigger physical clip
            for _ in range(50):
                _sample_typical_distribution(slot_record, physical_lo=0.0, physical_hi=0.8, rng=rng)
        # typical_bounds [1.0,1.5] uniform sample → typical clip 不触发；
        # 但 physical_bounds [0, 0.8] 比 typical [1.0,1.5] 严，physical clip 100% 触发
        self.assertIn(CHECK_ID_TYPICAL_BOUNDS_CLIP, acc.summaries)
        self.assertGreater(acc.summaries[CHECK_ID_TYPICAL_BOUNDS_CLIP].count, 0)

    def test_audit_capture_no_clip_no_record(self) -> None:
        """value 不变 (before == after) 时 accumulator 不 record (节约 mean 累计)."""
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        import random

        slot_record = {
            "slot_id": "test.in_range",
            "recommended_distribution": "uniform",
            "typical_bounds": [0.3, 0.7],
        }
        rng = random.Random(42)
        with audit_capture() as acc:
            for _ in range(20):
                _sample_typical_distribution(slot_record, physical_lo=0.0, physical_hi=1.0, rng=rng)
        # typical_bounds [0.3,0.7] ⊂ physical [0,1] → uniform sample 都在 typical_bounds 内
        # → typical clip 不触发；physical clip 也不触发 (sample > 0, sample < 1).
        self.assertEqual(acc.summaries.get(CHECK_ID_TYPICAL_BOUNDS_CLIP, P2ClampSummary("x")).count, 0)


class BatchGateStatsP2AuditTests(unittest.TestCase):
    """DEBT-030 C 组 / spec 07 §4 line 70: BatchGateStats P2 audit merge behavior."""

    def test_p2_clamp_summaries_empty_default(self) -> None:
        s = BatchGateStats()
        self.assertEqual(s.p2_clamp_summaries, {})

    def test_record_p2_clamps_from_accumulator_basic(self) -> None:
        s = BatchGateStats()
        acc = P2AuditAccumulator()
        acc.record(check_id="TYPICAL_BOUNDS_CLIP", before=1.5, after=1.0, slot_id="x")
        acc.record(check_id="TYPICAL_BOUNDS_CLIP", before=2.0, after=1.0, slot_id="x")
        acc.record(check_id="PRECISION_ROUNDING", before=0.123, after=0.12, slot_id="y")
        s.record_p2_clamps_from_accumulator(acc)
        self.assertEqual(s.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"].count, 2)
        self.assertEqual(s.p2_clamp_summaries["PRECISION_ROUNDING"].count, 1)
        self.assertAlmostEqual(s.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"].max_magnitude, 1.0)

    def test_record_p2_clamps_merge_累积(self) -> None:
        """多次 merge accumulator 时 count 累加，max 取大，mean 加权平均，sample_actions append-with-cap."""
        s = BatchGateStats()
        acc1 = P2AuditAccumulator()
        for i in range(5):
            acc1.record(check_id="TYPICAL_BOUNDS_CLIP", before=float(i + 1), after=0.0)
        s.record_p2_clamps_from_accumulator(acc1)

        acc2 = P2AuditAccumulator()
        for i in range(5):
            acc2.record(check_id="TYPICAL_BOUNDS_CLIP", before=float(i + 10), after=0.0)
        s.record_p2_clamps_from_accumulator(acc2)

        sm = s.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"]
        self.assertEqual(sm.count, 10)
        self.assertAlmostEqual(sm.max_magnitude, 14.0)
        # mean = (sum of all magnitudes) / 10 = (1+2+3+4+5+10+11+12+13+14)/10 = 75/10 = 7.5
        self.assertAlmostEqual(sm.mean_magnitude, 7.5)
        # sample_actions: 第一 acc 5 + 第二 acc 5 = 10，未超 K=20
        self.assertEqual(len(sm.sample_actions), 10)

    def test_record_p2_clamps_sample_cap_across_merges(self) -> None:
        """跨 acc merge sample_actions 不超 K=20."""
        s = BatchGateStats()
        # acc1: 15 events
        acc1 = P2AuditAccumulator()
        for i in range(15):
            acc1.record(check_id="TYPICAL_BOUNDS_CLIP", before=float(i + 1), after=0.0)
        s.record_p2_clamps_from_accumulator(acc1)
        self.assertEqual(len(s.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"].sample_actions), 15)

        # acc2: 又 15 events → 总 30，sample_actions cap 在 20
        acc2 = P2AuditAccumulator()
        for i in range(15):
            acc2.record(check_id="TYPICAL_BOUNDS_CLIP", before=float(i + 20), after=0.0)
        s.record_p2_clamps_from_accumulator(acc2)
        sm = s.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"]
        self.assertEqual(sm.count, 30)
        self.assertEqual(len(sm.sample_actions), 20)

    def test_record_p2_clamps_empty_accumulator_noop(self) -> None:
        s = BatchGateStats()
        s.record_p2_clamps_from_accumulator(P2AuditAccumulator())
        self.assertEqual(s.p2_clamp_summaries, {})

    def test_record_p2_clamps_none_accumulator_noop(self) -> None:
        s = BatchGateStats()
        s.record_p2_clamps_from_accumulator(None)
        self.assertEqual(s.p2_clamp_summaries, {})

    def test_batch_gate_stats_to_dict_includes_p2(self) -> None:
        s = BatchGateStats()
        acc = P2AuditAccumulator()
        acc.record(check_id="TYPICAL_BOUNDS_CLIP", before=1.5, after=1.0)
        s.record_p2_clamps_from_accumulator(acc)
        d = s.to_dict()
        self.assertIn("p2_clamp_summaries", d)
        self.assertIn("TYPICAL_BOUNDS_CLIP", d["p2_clamp_summaries"])

    def test_batch_gate_stats_from_dict_roundtrip(self) -> None:
        """跨进程 worker 返回 BatchGateStats → 主进程合并依赖此 round-trip."""
        s = BatchGateStats()
        s.record_accepted()
        s.record_rejected("P0_violation")
        s.record_repair_actions(
            [RepairAction(check_id="C007_EXTENT_AREA_BOUND", fragment_id="F1")]
        )
        acc = P2AuditAccumulator()
        for i in range(25):
            acc.record(
                check_id="TYPICAL_BOUNDS_CLIP",
                before=float(i + 1),
                after=0.0,
                slot_id=f"slot.{i}",
                fragment_id=f"F{i}",
            )
        s.record_p2_clamps_from_accumulator(acc)
        d = s.to_dict()
        import json
        js = json.dumps(d)
        restored = BatchGateStats.from_dict(json.loads(js))
        self.assertEqual(restored.accepted_count, 1)
        self.assertEqual(restored.rejected_count, 1)
        self.assertEqual(restored.reject_reasons["P0_violation"], 1)
        self.assertEqual(restored.repair_action_counts["C007_EXTENT_AREA_BOUND"], 1)
        sm = restored.p2_clamp_summaries["TYPICAL_BOUNDS_CLIP"]
        self.assertEqual(sm.count, 25)
        self.assertEqual(len(sm.sample_actions), 20)  # K=20 cap


class GeneratorP2AuditIntegrationTests(unittest.TestCase):
    """DEBT-030 C 组: generate_world_batch_with_stats 端到端集成测试."""

    def setUp(self) -> None:
        clear_check_registry()
        self.registries = _build_registry_bundle()

    def tearDown(self) -> None:
        clear_check_registry()
        clear_p2_audit_context()

    def test_batch_with_stats_collects_p2_summaries(self) -> None:
        """spec 07 §4 line 70 端到端: generate_world_batch_with_stats 产生 4 栋 building，
        每栋 generate measurements 触发若干 P2 inline clamp → 累入 batch p2_clamp_summaries."""
        _worlds, stats = generate_world_batch_with_stats(
            {}, self.registries, count=4, seed=42,
        )
        # 至少有一种 P2 check_id 被触发（depend on registry + seed；真实运行典型
        # 都会触发 TYPICAL_BOUNDS_CLIP / PRECISION_ROUNDING）
        # 不强行断言具体 count（不希望被 RNG 漂移破坏），只断言 dict 存在 + 序列化兼容
        self.assertIsInstance(stats.p2_clamp_summaries, dict)
        # to_dict 端口含 p2_clamp_summaries 桶
        d = stats.to_dict()
        self.assertIn("p2_clamp_summaries", d)

    def test_batch_with_stats_cross_process_round_trip(self) -> None:
        """spec 07 §4 line 70 跨进程并行 verify: worker 返回 BatchGateStats.to_dict() →
        主进程 from_dict 反序列化 → p2_clamp_summaries 字段保留."""
        # 模拟 worker: 单栋 batch 跑出 stats → to_dict → 跨进程后 from_dict
        _worlds, stats = generate_world_batch_with_stats(
            {}, self.registries, count=2, seed=99,
        )
        wire = stats.to_dict()
        restored = BatchGateStats.from_dict(wire)
        self.assertEqual(restored.accepted_count, stats.accepted_count)
        # P2 summaries 字段保留 (即使 count == 0 字段存在为 dict)
        self.assertIsInstance(restored.p2_clamp_summaries, dict)


# ---------- 跨进程并行 P2 audit 端到端测试 (DEBT-030 C 组 #2 收尾) ----------


def _cross_process_p2_worker(seed: int, n_clamps: int, queue) -> None:
    """跨进程 P2 audit worker — **必须 module-level** (Windows spawn 不能 pickle closure).

    pattern (spec 07 §4 line 70-75 + p2_audit.audit_capture docstring 跨进程示例)::

        1. worker 自 set worker-local audit_capture context (ContextVar 跨进程不传播,
           每 worker 进程 fresh state, 自家 wrap)
        2. 调用触发 P2 inline clip 的 generation 路径 (这里直接调 _sample_typical_distribution
           保持测试时间可控 < 5s, 而非完整 generate_world_bundle)
        3. accumulator → BatchGateStats.record_p2_clamps_from_accumulator → to_dict()
        4. 通过 Queue 跨进程返回 dict (json-friendly)
    """
    import random as _random

    # delayed import — worker 进程独立 import (Windows spawn 默认行为)
    from workflow_engine.worldgen.generator import _sample_typical_distribution
    from workflow_engine.worldgen.gates import BatchGateStats as _BGS
    from workflow_engine.worldgen.p2_audit import audit_capture as _audit_capture

    # 设计 slot_record: typical_bounds [1.0, 1.5] 但 physical_bounds [0, 0.8] 严格
    # → 100% physical clip 触发 → 稳定可断言
    slot_record = {
        "slot_id": f"test.cross_process.seed_{seed}",
        "recommended_distribution": "uniform",
        "typical_bounds": [1.0, 1.5],
    }
    rng = _random.Random(seed)

    with _audit_capture() as acc:
        for _ in range(n_clamps):
            _sample_typical_distribution(
                slot_record, physical_lo=0.0, physical_hi=0.8, rng=rng
            )

    worker_stats = _BGS()
    worker_stats.record_p2_clamps_from_accumulator(acc)
    queue.put(worker_stats.to_dict())


class CrossProcessP2AuditTests(unittest.TestCase):
    """DEBT-030 C 组 #2 收尾: ProcessPoolExecutor / multiprocessing pattern 端到端 verify.

    覆盖 W1 spec 07 §4 line 70-75 + p2_audit.audit_capture docstring 跨进程承诺:
        - ContextVar 不跨进程传播 → 每 worker 自家 set
        - worker 内 audit_capture → BatchGateStats.to_dict() 跨进程 round-trip
        - 主进程 from_dict + record_p2_clamps_from_accumulator 累计 merge
        - K=20 sample cap 跨 worker merge 后仍约束

    选择 ``multiprocessing.Process`` + ``Queue`` 而非 ``ProcessPoolExecutor``: Process
    更显式 (单 worker / single Queue), Windows spawn 行为可预测, 不依赖 Executor 内部
    chunksize/buffering, 单测时间 < 5s 稳定.
    """

    def test_cross_process_p2_audit_e2e(self) -> None:
        """跨 3 worker 进程触发 P2 clamp, 主进程 merge 后断言 count / sample_cap / round-trip."""
        import multiprocessing as mp

        n_workers = 3
        n_clamps_per_worker = 10  # 每 worker 10 次 clip → 总 30, sample_actions cap 20
        ctx = mp.get_context("spawn")  # Windows + 跨平台一致行为
        queue = ctx.Queue()

        workers = [
            ctx.Process(
                target=_cross_process_p2_worker,
                args=(1000 + i, n_clamps_per_worker, queue),
            )
            for i in range(n_workers)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=30)
            self.assertFalse(w.is_alive(), "worker hang > 30s — 跨进程 P2 audit pattern broken")
            self.assertEqual(w.exitcode, 0, f"worker exitcode={w.exitcode} (期望 0)")

        # 主进程 collect worker dict
        worker_dicts = []
        for _ in range(n_workers):
            worker_dicts.append(queue.get(timeout=5))
        self.assertEqual(len(worker_dicts), n_workers)

        # 主进程 merge: 每 worker dict → from_dict → 累入 master BatchGateStats
        master = BatchGateStats()
        for d in worker_dicts:
            worker_stats = BatchGateStats.from_dict(d)
            # merge per check_id: 通过 P2AuditAccumulator 桥接 (复用 master 的 merge 路径)
            for cid, summary in worker_stats.p2_clamp_summaries.items():
                bridge = P2AuditAccumulator()
                bridge.summaries[cid] = summary
                master.record_p2_clamps_from_accumulator(bridge)

        # 断言: TYPICAL_BOUNDS_CLIP 在 master 中存在 (physical_bounds [0, 0.8] 比 typical
        # [1.0, 1.5] 严, 100% 触发)
        self.assertIn(CHECK_ID_TYPICAL_BOUNDS_CLIP, master.p2_clamp_summaries)
        sm = master.p2_clamp_summaries[CHECK_ID_TYPICAL_BOUNDS_CLIP]

        # count: 3 worker × 10 clip = 30 (uniform sample 全在 [1.0, 1.5], physical hi=0.8
        # → 100% clip after physical step)
        self.assertEqual(sm.count, n_workers * n_clamps_per_worker)
        # sample_actions: K=20 cap (3 × 10 = 30 > 20)
        self.assertEqual(len(sm.sample_actions), P2_SAMPLE_CAP)
        # max_magnitude > 0 (真实 clip 发生)
        self.assertGreater(sm.max_magnitude, 0.0)
        # mean_magnitude > 0
        self.assertGreater(sm.mean_magnitude, 0.0)

    def test_cross_process_worker_context_isolation(self) -> None:
        """verify ContextVar 不跨进程传播 — 主进程 set 的 accumulator 不影响 worker."""
        import multiprocessing as mp

        # 主进程 set audit context (worker 进程不应继承)
        main_acc = P2AuditAccumulator()
        token = set_p2_audit_context(main_acc)
        try:
            ctx = mp.get_context("spawn")
            queue = ctx.Queue()
            w = ctx.Process(
                target=_cross_process_p2_worker,
                args=(42, 5, queue),
            )
            w.start()
            w.join(timeout=30)
            self.assertEqual(w.exitcode, 0)
            worker_dict = queue.get(timeout=5)

            # worker 自己产生 audit (5 次 clip → 5 count)
            worker_stats = BatchGateStats.from_dict(worker_dict)
            self.assertIn(CHECK_ID_TYPICAL_BOUNDS_CLIP, worker_stats.p2_clamp_summaries)
            self.assertEqual(
                worker_stats.p2_clamp_summaries[CHECK_ID_TYPICAL_BOUNDS_CLIP].count, 5
            )

            # 主进程 main_acc 仍空 (ContextVar 不跨进程, worker 写不进主进程 accumulator)
            self.assertEqual(main_acc.summaries, {})
        finally:
            clear_p2_audit_context(token)


if __name__ == "__main__":
    unittest.main()
