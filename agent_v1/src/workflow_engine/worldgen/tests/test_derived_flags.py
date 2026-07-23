"""spec 06 §11 14 derived flag 派生 (populate_derived_flags) — W1-010 注释修正."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen.generator import (
    generate_world_bundle,
    populate_derived_flags,
)
from workflow_engine.worldgen.registry import _build_registry_bundle


class PopulateDerivedFlagsTests(unittest.TestCase):
    """spec 06 §11 14 个 derived flag 填充 condition.derived_outcomes (W1-010)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_derived_flags_populated_in_each_condition(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        for condition in world.conditions:
            self.assertGreater(
                len(condition.derived_outcomes.risk_flags), 0,
                f"condition {condition.condition_id} risk_flags empty",
            )
            self.assertGreater(
                len(condition.derived_outcomes.repair_flags), 0,
                f"condition {condition.condition_id} repair_flags empty",
            )
            self.assertGreater(
                len(condition.derived_outcomes.assessment_flags), 0,
            )

    def test_14_flags_present(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        for condition in world.conditions:
            risk = condition.derived_outcomes.risk_flags
            repair = condition.derived_outcomes.repair_flags
            verification = condition.derived_outcomes.verification_flags
            assessment = condition.derived_outcomes.assessment_flags
            # spec §11 expected flag slot keys
            expected_risk = {
                "risk.building_safety.emergency",
                "risk.public_health.emergency",
                "risk.public_danger.present",
                "drainage.misconnection.present",
                "ubw.present",
                "subdivided_unit_sign.present",
                "fire_safety.deficiency.present",
                "coverage.insufficient",
            }
            self.assertEqual(set(risk.keys()), expected_risk)
            expected_repair = {
                "repair.required",
                "maintenance.pre_next_cycle.required",
                "repair.outcome.safe_until_next_cycle",
            }
            self.assertEqual(set(repair.keys()), expected_repair)
            self.assertEqual(set(verification.keys()), {"verification.test.failed"})
            expected_assessment = {
                "assessment.fsp.below_required_safety",
                "defect.cause_or_extent.uncertain",
            }
            self.assertEqual(set(assessment.keys()), expected_assessment)

    def test_risk_index_values_populated(self) -> None:
        """spec §11 索引值（max_danger / fsp_estimate）写入 risk_index_values."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        for condition in world.conditions:
            self.assertIn("index.public_danger", condition.derived_outcomes.risk_index_values)
            self.assertIn("index.fsp.estimate", condition.derived_outcomes.risk_index_values)

    def test_severe_condition_triggers_repair_required(self) -> None:
        """spec §11 行 4 repair_required 当 severity >= 0.33（moderate band 起点）."""
        world = generate_world_bundle({}, self.registries, seed=99, building_index=0, fragment_count=10)
        severe_conditions = [c for c in world.conditions if c.severity_index >= 0.33]
        for c in severe_conditions:
            self.assertTrue(
                c.derived_outcomes.repair_flags["repair.required"],
                f"severe condition {c.condition_id} (severity={c.severity_index}) should trigger repair_required",
            )

    def test_drainage_specific_flags_only_when_drainage_present(self) -> None:
        """spec §11 drainage 类 flag：mechanism=drainage_fault 时填 bool；其它 fragment 填 not_applicable."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        drainage_fragment_ids = {ds.drainage_id.replace("DRN-", "") for ds in world.drainage_states}
        for condition in world.conditions:
            mechanism = next((m for m in world.mechanisms if m.fragment_id == condition.fragment_id), None)
            misc = condition.derived_outcomes.risk_flags.get("drainage.misconnection.present")
            if mechanism and mechanism.mechanism_family == "drainage_fault":
                self.assertIn(misc, [True, False])  # boolean
            else:
                self.assertEqual(misc, "not_applicable")

    def test_ubw_flag_logic(self) -> None:
        """spec §11 行 10 ubw_present = (alteration ≠ none + unauthorized_like)."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            mechanism = next((m for m in world.mechanisms if m.fragment_id == condition.fragment_id), None)
            ubw_flag = condition.derived_outcomes.risk_flags["ubw.present"]
            if mechanism and mechanism.mechanism_family == "ubw_signal":
                # ubw_state should exist; flag bool reflects authorization
                self.assertIn(ubw_flag, [True, False])
            else:
                self.assertFalse(ubw_flag)

    def test_pure_function_no_input_mutation(self) -> None:
        """populate_derived_flags 不能 mutate input world."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        # take snapshot of derived_outcomes BEFORE re-populate
        before = [dict(c.derived_outcomes.risk_flags) for c in world.conditions]
        # call populate_derived_flags again (already called in generate_world_bundle, this is idempotent check)
        new_world = populate_derived_flags(world)
        after_input = [dict(c.derived_outcomes.risk_flags) for c in world.conditions]
        # input not mutated by re-populate
        self.assertEqual(before, after_input)
        # output has same flags
        for in_flags, out_flags in zip(before, [dict(c.derived_outcomes.risk_flags) for c in new_world.conditions]):
            self.assertEqual(in_flags.keys(), out_flags.keys())


class DerivedFlagFallbackReasonsTests(unittest.TestCase):
    """DEBT-030 C 组 / spec 06 §11 unknown_policy 列：not_applicable fallback reason audit trace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def _assert_consistency(self, condition) -> None:
        """fallback_reasons 必须跟 derived flag 值一致：reason ⇔ value=="not_applicable"."""
        all_flags = {
            **condition.derived_outcomes.risk_flags,
            **condition.derived_outcomes.repair_flags,
            **condition.derived_outcomes.verification_flags,
            **condition.derived_outcomes.assessment_flags,
        }
        reasons = condition.derived_outcomes.fallback_reasons
        # 每个 reason key 对应的 flag 必须是 "not_applicable" / "unknown"
        for flag_id, reason in reasons.items():
            self.assertIn(
                all_flags.get(flag_id),
                ["not_applicable", "unknown"],
                f"fallback_reasons has '{flag_id}' = '{reason}' "
                f"but flag value = {all_flags.get(flag_id)!r} (expected not_applicable/unknown)",
            )
            # reason code 必须非空字符串
            self.assertIsInstance(reason, str)
            self.assertNotEqual(reason, "")

    def test_fallback_reasons_field_exists(self) -> None:
        """DEBT-030 C 组：DerivedOutcomeState.fallback_reasons 字段已加."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        for condition in world.conditions:
            # 默认 dict 字段（可能为空）
            self.assertIsInstance(condition.derived_outcomes.fallback_reasons, dict)

    def test_fallback_reasons_consistent_with_not_applicable_flag(self) -> None:
        """每个 fallback_reasons entry 对应 flag 值必须是 not_applicable / unknown."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            self._assert_consistency(condition)

    def test_verification_no_test_reason_code(self) -> None:
        """无 technical_validation_measurement → verification.test.failed = not_applicable + reason=no_test."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            vf = condition.derived_outcomes.verification_flags.get("verification.test.failed")
            if vf == "not_applicable":
                self.assertEqual(
                    condition.derived_outcomes.fallback_reasons.get("verification.test.failed"),
                    "no_test",
                )

    def test_drainage_no_drainage_reason_code(self) -> None:
        """无 drainage_state → risk.public_health.emergency + drainage.misconnection.present 双重 reason=no_drainage."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            ph = condition.derived_outcomes.risk_flags.get("risk.public_health.emergency")
            misc = condition.derived_outcomes.risk_flags.get("drainage.misconnection.present")
            reasons = condition.derived_outcomes.fallback_reasons
            if ph == "not_applicable":
                self.assertEqual(reasons.get("risk.public_health.emergency"), "no_drainage")
            if misc == "not_applicable":
                self.assertEqual(reasons.get("drainage.misconnection.present"), "no_drainage")

    def test_no_repair_when_no_assessment(self) -> None:
        """spec 06 §11 row 6：repair_outcome_safe_until_next_cycle 没 repair_assessment 时 not_applicable + reason=no_repair."""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            sc = condition.derived_outcomes.repair_flags.get("repair.outcome.safe_until_next_cycle")
            if sc == "not_applicable":
                self.assertEqual(
                    condition.derived_outcomes.fallback_reasons.get("repair.outcome.safe_until_next_cycle"),
                    "no_repair",
                )

    def test_reason_codes_are_valid_spec_terms(self) -> None:
        """所有 reason code 必须从 spec 06 §11 unknown_policy 列 verbatim 规范化."""
        # spec 06 §11 unknown_policy 列允许的 reason codes（按 spec verbatim 规范化）
        valid_reasons = {
            "no_drainage",
            "no_repair",
            "no_test",
            "no_assessment",
            "no_private_premises",
            "no_fire_component",
            "no_scope_target",
        }
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        for condition in world.conditions:
            for flag_id, reason in condition.derived_outcomes.fallback_reasons.items():
                self.assertIn(
                    reason,
                    valid_reasons,
                    f"flag {flag_id!r} fallback reason {reason!r} not in spec 06 §11 vocab {valid_reasons}",
                )


if __name__ == "__main__":
    unittest.main()
