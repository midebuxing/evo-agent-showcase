"""Unit tests for worldgen.constants module.

Guards canonical constants, utility functions, and type alias definitions.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen.constants import (
    BATCH_CONTRACT_TARGETS,
    CANOPY_CHECK_LOCATION_INTERVAL_MAX_M,
    CANOPY_CHECK_LOCATIONS_MINIMUM,
    CORE_SAMPLE_RATE_PER_CONCRETE_VOLUME_MINIMUM,
    COVERAGE_RATIO_FLOOR_PROXY,
    DRAINAGE_BRANCH_INTERVAL_M,
    DRAINAGE_TEST_POINTS_MINIMUM,
    FIRE_DOOR_SAMPLE_MINIMUM,
    FIRE_DOOR_SELF_CLOSING_SURROGATE_SPLIT_SEC,
    FSP_LOW_TAIL_PROFILE_IDS,
    FSP_STRUCTURAL_PERFORMANCE_FLOOR,
    GENERATOR_VERSION,
    MAINTENANCE_SEVERITY_RANKS,
    PRIVATE_PREMISES_ACCESS_FLOOR_INTERVAL,
    PUBLIC_HEALTH_RISK_EMERGENCY_FLOOR,
    PULL_TEST_COUNT_PER_FLOOR_FULL_RETILING,
    PULL_TEST_COUNT_PER_REPAIRED_FACADE,
    PULL_TEST_RATE_PER_25M2,
    PULL_TEST_STRENGTH_CANONICAL_BASELINE,
    RELEASE_FSP_BELOW_SAFETY_FLOOR,
    RELEASE_NO_SIDECAR_DEPENDENCY_FLOOR,
    RELEASE_RESIDUAL_RISK_FALSE_FLOOR,
    RELEASE_SIDECAR_MISSING_FLOOR,
    REPAIR_MORTAR_SPECIMENS_PER_PROPERTY,
    REPAIR_MORTAR_TEST_AGE_DAYS,
    REPAIR_QUALITY_VERIFICATION_FLOOR,
    SEVERITY_EMERGENCY_MIN,
    SEVERITY_FLOOR_RELEASE,
    SEVERITY_MINOR_MAX,
    SEVERITY_MODERATE_MAX,
    SOURCE_DOCUMENTS,
    WORK_CATEGORY_VALUES,
    _canonical_json,
    _hash_payload,
    _resolve_batch_profile,
    _utc_now_iso,
)


class ConstantsValueTests(unittest.TestCase):
    """Guard canonical constant values as locked in a4/a12."""

    def test_pull_test_strength_canonical_baseline(self) -> None:
        # [DEBT-002 §15.7] confirmed canonical value
        self.assertEqual(PULL_TEST_STRENGTH_CANONICAL_BASELINE, 0.50)

    def test_coverage_ratio_floor_proxy(self) -> None:
        # [DEBT-013 §15.8] confirmed canonical value
        self.assertEqual(COVERAGE_RATIO_FLOOR_PROXY, 0.35)

    def test_severity_bands(self) -> None:
        self.assertEqual(SEVERITY_MINOR_MAX, 0.33)
        self.assertEqual(SEVERITY_MODERATE_MAX, 0.66)
        self.assertEqual(SEVERITY_EMERGENCY_MIN, 0.85)

    def test_fsp_structural_performance_floor(self) -> None:
        self.assertEqual(FSP_STRUCTURAL_PERFORMANCE_FLOOR, 0.75)

    def test_public_health_risk_emergency_floor(self) -> None:
        self.assertEqual(PUBLIC_HEALTH_RISK_EMERGENCY_FLOOR, 0.80)

    def test_repair_quality_verification_floor(self) -> None:
        self.assertEqual(REPAIR_QUALITY_VERIFICATION_FLOOR, 0.45)

    def test_maintenance_severity_ranks(self) -> None:
        self.assertEqual(MAINTENANCE_SEVERITY_RANKS, {1, 2})

    def test_repair_mortar_constants(self) -> None:
        # [SCAN03-F04] 规范常量
        self.assertEqual(REPAIR_MORTAR_TEST_AGE_DAYS, 28)
        self.assertEqual(REPAIR_MORTAR_SPECIMENS_PER_PROPERTY, 3)

    def test_fire_door_surrogate_split(self) -> None:
        # [SCAN06-F04]
        self.assertEqual(FIRE_DOOR_SELF_CLOSING_SURROGATE_SPLIT_SEC, 3.0)

    def test_pull_test_plan_constants(self) -> None:
        # [SCAN03-F07]
        self.assertEqual(PULL_TEST_RATE_PER_25M2, 1)
        self.assertEqual(PULL_TEST_COUNT_PER_REPAIRED_FACADE, 6)
        self.assertEqual(PULL_TEST_COUNT_PER_FLOOR_FULL_RETILING, 4)

    def test_drainage_plan_constants(self) -> None:
        self.assertEqual(DRAINAGE_TEST_POINTS_MINIMUM, 3)
        self.assertEqual(DRAINAGE_BRANCH_INTERVAL_M, 8.0)
        self.assertEqual(FIRE_DOOR_SAMPLE_MINIMUM, 4)
        self.assertEqual(PRIVATE_PREMISES_ACCESS_FLOOR_INTERVAL, 3)

    def test_canopy_constants(self) -> None:
        self.assertEqual(CANOPY_CHECK_LOCATIONS_MINIMUM, 2)
        self.assertEqual(CANOPY_CHECK_LOCATION_INTERVAL_MAX_M, 6.0)
        self.assertEqual(CORE_SAMPLE_RATE_PER_CONCRETE_VOLUME_MINIMUM, 0.02)

    def test_batch_contract_targets(self) -> None:
        self.assertEqual(BATCH_CONTRACT_TARGETS["smoke_batch"], 120)
        self.assertEqual(BATCH_CONTRACT_TARGETS["dev_batch"], 600)
        self.assertEqual(BATCH_CONTRACT_TARGETS["benchmark_batch"], 1200)
        self.assertEqual(BATCH_CONTRACT_TARGETS["release_batch"], 3000)

    def test_release_floor_constants(self) -> None:
        self.assertEqual(RELEASE_RESIDUAL_RISK_FALSE_FLOOR, 60)
        self.assertEqual(RELEASE_FSP_BELOW_SAFETY_FLOOR, 60)
        self.assertEqual(RELEASE_NO_SIDECAR_DEPENDENCY_FLOOR, 1500)
        self.assertEqual(RELEASE_SIDECAR_MISSING_FLOOR, 300)

    def test_severity_floor_release_bands(self) -> None:
        required_bands = {"emergency", "severe", "none", "not_applicable"}
        self.assertTrue(required_bands.issubset(set(SEVERITY_FLOOR_RELEASE.keys())))
        for band, floor in SEVERITY_FLOOR_RELEASE.items():
            self.assertGreater(floor, 0)

    def test_generator_version_format(self) -> None:
        self.assertTrue(GENERATOR_VERSION.startswith("worldgen."))

    def test_fsp_low_tail_profile_ids_is_set(self) -> None:
        self.assertIsInstance(FSP_LOW_TAIL_PROFILE_IDS, (set, frozenset))
        self.assertGreater(len(FSP_LOW_TAIL_PROFILE_IDS), 0)

    def test_source_documents_has_a8(self) -> None:
        self.assertTrue(any("a8.md" in doc for doc in SOURCE_DOCUMENTS))

    def test_work_category_values_nonempty(self) -> None:
        self.assertIsInstance(WORK_CATEGORY_VALUES, list)
        self.assertGreater(len(WORK_CATEGORY_VALUES), 0)
        self.assertIn("minor_works", WORK_CATEGORY_VALUES)


class UtilityFunctionTests(unittest.TestCase):
    """Guard utility functions from constants module."""

    def test_utc_now_iso_returns_string(self) -> None:
        ts = _utc_now_iso()
        self.assertIsInstance(ts, str)
        self.assertIn("T", ts)

    def test_hash_payload_stable(self) -> None:
        payload = {"key": "value", "num": 42}
        h1 = _hash_payload(payload)
        h2 = _hash_payload(payload)
        self.assertEqual(h1, h2)
        self.assertIsInstance(h1, str)
        self.assertEqual(len(h1), 64)  # SHA-256 hex digest

    def test_hash_payload_order_independent(self) -> None:
        h1 = _hash_payload({"a": 1, "b": 2})
        h2 = _hash_payload({"b": 2, "a": 1})
        self.assertEqual(h1, h2)

    def test_hash_payload_sensitive_to_content(self) -> None:
        h1 = _hash_payload({"key": "value"})
        h2 = _hash_payload({"key": "different"})
        self.assertNotEqual(h1, h2)

    def test_canonical_json_stable_across_key_order(self) -> None:
        j1 = _canonical_json({"z": 1, "a": 2})
        j2 = _canonical_json({"a": 2, "z": 1})
        self.assertEqual(j1, j2)

    def test_resolve_batch_profile_smoke(self) -> None:
        self.assertEqual(_resolve_batch_profile(120), "smoke_batch")

    def test_resolve_batch_profile_dev(self) -> None:
        self.assertEqual(_resolve_batch_profile(600), "dev_batch")

    def test_resolve_batch_profile_benchmark(self) -> None:
        self.assertEqual(_resolve_batch_profile(1200), "benchmark_batch")

    def test_resolve_batch_profile_release(self) -> None:
        self.assertEqual(_resolve_batch_profile(3000), "release_batch")

    def test_resolve_batch_profile_below_smoke(self) -> None:
        # Anything below smoke_batch threshold falls back to smallest label
        result = _resolve_batch_profile(11)
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
