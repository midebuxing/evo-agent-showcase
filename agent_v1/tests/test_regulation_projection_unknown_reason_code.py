"""T-24 unknown_reason_code routing tests (spec 06 §16.3 / spec 07 §5).

13 项 reason code priority routing + helper functions.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    UNKNOWN_REASON_CODES,
    derive_unknown_reason_code,
    detect_binding_registry_gap,
    detect_unit_incompatible,
    has_known_family_match,
    is_sidecar_only_fact_pattern,
)


class UnknownReasonCodesEnumTests(unittest.TestCase):
    """spec 06 §16.3 完整 13 项枚举."""

    def test_thirteen_reason_codes_present(self) -> None:
        self.assertEqual(len(UNKNOWN_REASON_CODES), 13)

    def test_all_codes_unique(self) -> None:
        self.assertEqual(len(UNKNOWN_REASON_CODES), len(set(UNKNOWN_REASON_CODES)))

    def test_spec_codes_present(self) -> None:
        expected = {
            "no_known_family_match",
            "unsupported_material_system",
            "unsupported_component_type",
            "unsupported_damage_pattern",
            "unsupported_location_context",
            "projection_binding_incompatible",
            "binding_registry_gap",
            "multi_family_conflict",
            "sidecar_only_fact_pattern",
            "coverage_unimplemented_domain",
            "measurement_family_unimplemented",
            "method_class_unimplemented",
            "unit_incompatible",
        }
        self.assertEqual(set(UNKNOWN_REASON_CODES), expected)


class DeriveUnknownReasonCodeTests(unittest.TestCase):
    """spec 06 §16.3 priority routing."""

    def test_no_unknown_condition_returns_none(self) -> None:
        result = derive_unknown_reason_code({"has_known_family_match": True})
        self.assertIsNone(result)

    def test_no_known_family_match(self) -> None:
        result = derive_unknown_reason_code({"has_known_family_match": False})
        self.assertEqual(result, "no_known_family_match")

    def test_multi_family_conflict_top_priority(self) -> None:
        """multi_family_conflict 优先级最高。"""
        ctx = {
            "multi_family_conflict": True,
            "has_known_family_match": False,
            "coverage_unimplemented_domain": True,
        }
        self.assertEqual(derive_unknown_reason_code(ctx), "multi_family_conflict")

    def test_coverage_unimplemented_domain(self) -> None:
        ctx = {"coverage_unimplemented_domain": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "coverage_unimplemented_domain")

    def test_binding_registry_gap(self) -> None:
        ctx = {"binding_registry_gap": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "binding_registry_gap")

    def test_measurement_family_unimplemented(self) -> None:
        ctx = {"measurement_family_unimplemented": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "measurement_family_unimplemented")

    def test_method_class_unimplemented(self) -> None:
        ctx = {"method_class_unimplemented": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "method_class_unimplemented")

    def test_unsupported_material_system(self) -> None:
        ctx = {"unsupported_material_system": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "unsupported_material_system")

    def test_unsupported_component_type(self) -> None:
        ctx = {"unsupported_component_type": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "unsupported_component_type")

    def test_unsupported_damage_pattern(self) -> None:
        ctx = {"unsupported_damage_pattern": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "unsupported_damage_pattern")

    def test_unsupported_location_context(self) -> None:
        ctx = {"unsupported_location_context": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "unsupported_location_context")

    def test_unit_incompatible(self) -> None:
        ctx = {"unit_incompatible": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "unit_incompatible")

    def test_projection_binding_incompatible(self) -> None:
        ctx = {"projection_binding_incompatible": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "projection_binding_incompatible")

    def test_sidecar_only_fact_pattern_lowest_priority(self) -> None:
        ctx = {"sidecar_only_fact_pattern": True}
        self.assertEqual(derive_unknown_reason_code(ctx), "sidecar_only_fact_pattern")

    def test_priority_unsupported_material_over_unit_incompatible(self) -> None:
        """unsupported_material_system 优先级 > unit_incompatible."""
        ctx = {
            "unsupported_material_system": True,
            "unit_incompatible": True,
        }
        self.assertEqual(derive_unknown_reason_code(ctx), "unsupported_material_system")

    def test_priority_binding_registry_gap_over_unsupported_material(self) -> None:
        """binding_registry_gap 优先级 > unsupported_material_system."""
        ctx = {
            "binding_registry_gap": True,
            "unsupported_material_system": True,
        }
        self.assertEqual(derive_unknown_reason_code(ctx), "binding_registry_gap")


class HelperFunctionsTests(unittest.TestCase):
    """T-24 detection helper functions."""

    def test_has_known_family_match_empty(self) -> None:
        self.assertFalse(has_known_family_match([]))

    def test_has_known_family_match_with_required_slots(self) -> None:
        candidates = [{"family_id": "fam1", "required_slots_present": True}]
        self.assertTrue(has_known_family_match(candidates))

    def test_has_known_family_match_no_required_slots(self) -> None:
        candidates = [{"family_id": "fam1", "required_slots_present": False}]
        self.assertFalse(has_known_family_match(candidates))

    def test_is_sidecar_only_when_no_world_facts(self) -> None:
        self.assertTrue(is_sidecar_only_fact_pattern(world_facts_present=False, sidecar_facts_present=True))

    def test_not_sidecar_only_when_world_facts_present(self) -> None:
        self.assertFalse(is_sidecar_only_fact_pattern(world_facts_present=True, sidecar_facts_present=True))

    def test_not_sidecar_only_when_no_sidecar_facts(self) -> None:
        self.assertFalse(is_sidecar_only_fact_pattern(world_facts_present=False, sidecar_facts_present=False))

    def test_detect_binding_registry_gap_all_bound(self) -> None:
        self.assertFalse(detect_binding_registry_gap(["a", "b"], {"a", "b", "c"}))

    def test_detect_binding_registry_gap_missing(self) -> None:
        self.assertTrue(detect_binding_registry_gap(["a", "b", "z"], {"a", "b"}))

    def test_detect_unit_incompatible_match(self) -> None:
        units = {"slot1": "mm", "slot2": "ratio"}
        expected = {"slot1": "mm", "slot2": "ratio"}
        self.assertFalse(detect_unit_incompatible(units, expected))

    def test_detect_unit_incompatible_mismatch(self) -> None:
        units = {"slot1": "mm"}
        expected = {"slot1": "m"}
        self.assertTrue(detect_unit_incompatible(units, expected))

    def test_detect_unit_incompatible_missing_unit_treated_as_compat(self) -> None:
        """缺 unit 的 slot 不视为 incompatible（spec 没明确，工程口径)."""
        units = {}  # no unit reported
        expected = {"slot1": "mm"}
        self.assertFalse(detect_unit_incompatible(units, expected))


if __name__ == "__main__":
    unittest.main()
