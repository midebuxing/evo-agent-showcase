"""T-25 5-bin threshold regime tests (spec 06 §15)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    THRESHOLD_REGIMES,
    classify_threshold_regime,
    compute_threshold_width,
)


class ThresholdRegimesEnumTests(unittest.TestCase):
    def test_six_regimes_present(self) -> None:
        self.assertEqual(len(THRESHOLD_REGIMES), 6)

    def test_all_regime_strings_unique(self) -> None:
        self.assertEqual(len(THRESHOLD_REGIMES), len(set(THRESHOLD_REGIMES)))

    def test_spec_regime_names(self) -> None:
        expected = {
            "far_below", "near_below", "exact_threshold",
            "near_above", "far_above", "not_numeric",
        }
        self.assertEqual(set(THRESHOLD_REGIMES), expected)


class ComputeThresholdWidthTests(unittest.TestCase):
    """spec 06 §15 family-specific width 计算."""

    def test_geometry_length_mm(self) -> None:
        # threshold 0.1mm, rel*thr=0.01, abs_min(mm)=0.05 → width=0.05
        self.assertAlmostEqual(compute_threshold_width(0.1, "geometry_length", slot_unit="mm"), 0.05)

    def test_geometry_length_mm_above_abs_min(self) -> None:
        # threshold 1.0mm, rel*thr=0.10, abs_min=0.05 → width=0.10
        self.assertAlmostEqual(compute_threshold_width(1.0, "geometry_length", slot_unit="mm"), 0.10)

    def test_geometry_length_m(self) -> None:
        # threshold 0.05m, rel*thr=0.005, abs_min(m)=0.01 → width=0.01
        self.assertAlmostEqual(compute_threshold_width(0.05, "geometry_length", slot_unit="m"), 0.01)

    def test_geometry_area(self) -> None:
        # threshold 0.5m², rel=0.20, abs_min=0.01 → width=0.10
        self.assertAlmostEqual(compute_threshold_width(0.5, "geometry_area"), 0.10)

    def test_geometry_area_minimum(self) -> None:
        # threshold 0.01m², rel*thr=0.002, abs_min=0.01 → width=0.01
        self.assertAlmostEqual(compute_threshold_width(0.01, "geometry_area"), 0.01)

    def test_ratio(self) -> None:
        # threshold 0.5, rel=0.10, abs_min=0.02 → width=0.05
        self.assertAlmostEqual(compute_threshold_width(0.5, "ratio"), 0.05)

    def test_ratio_minimum(self) -> None:
        # threshold 0.1, rel*thr=0.01, abs_min=0.02 → width=0.02
        self.assertAlmostEqual(compute_threshold_width(0.1, "ratio"), 0.02)

    def test_count(self) -> None:
        # always 1
        self.assertEqual(compute_threshold_width(50, "count"), 1.0)
        self.assertEqual(compute_threshold_width(0, "count"), 1.0)

    def test_rate(self) -> None:
        # threshold 5, rel=0.10, abs_min=0.1 → width=0.5
        self.assertAlmostEqual(compute_threshold_width(5.0, "rate"), 0.5)

    def test_rate_minimum(self) -> None:
        # threshold 0.5, rel*thr=0.05, abs_min=0.1 → width=0.1
        self.assertAlmostEqual(compute_threshold_width(0.5, "rate"), 0.1)

    def test_stress(self) -> None:
        # threshold 100, rel=0.05, abs_min=1.0 → width=5.0
        self.assertAlmostEqual(compute_threshold_width(100.0, "stress"), 5.0)

    def test_stress_minimum(self) -> None:
        # threshold 5, rel*thr=0.25, abs_min=1.0 → width=1.0
        self.assertAlmostEqual(compute_threshold_width(5.0, "stress"), 1.0)

    def test_bool_returns_zero_width(self) -> None:
        self.assertEqual(compute_threshold_width(0.5, "bool"), 0.0)

    def test_enum_returns_zero_width(self) -> None:
        self.assertEqual(compute_threshold_width(0.5, "enum"), 0.0)

    def test_unknown_family_returns_zero_width(self) -> None:
        self.assertEqual(compute_threshold_width(0.5, "wat_unknown"), 0.0)


class ClassifyThresholdRegimeTests(unittest.TestCase):
    """spec 06 §15 5-bin classification."""

    def test_exact_threshold_float(self) -> None:
        self.assertEqual(
            classify_threshold_regime(observed=0.5, threshold=0.5, measurement_family="ratio"),
            "exact_threshold",
        )

    def test_exact_threshold_within_epsilon(self) -> None:
        # diff = 1e-12 < 1e-9 → exact
        self.assertEqual(
            classify_threshold_regime(observed=0.5 + 1e-12, threshold=0.5, measurement_family="ratio"),
            "exact_threshold",
        )

    def test_exact_threshold_integer(self) -> None:
        self.assertEqual(
            classify_threshold_regime(
                observed=10, threshold=10, measurement_family="count", integer_compare=True,
            ),
            "exact_threshold",
        )

    def test_near_below_ratio(self) -> None:
        # threshold 0.5, width 0.05; observed 0.46 → diff -0.04 within width → near_below
        self.assertEqual(
            classify_threshold_regime(observed=0.46, threshold=0.5, measurement_family="ratio"),
            "near_below",
        )

    def test_far_below_ratio(self) -> None:
        # threshold 0.5, width 0.05; observed 0.30 → diff -0.20 > width → far_below
        self.assertEqual(
            classify_threshold_regime(observed=0.30, threshold=0.5, measurement_family="ratio"),
            "far_below",
        )

    def test_near_above_ratio(self) -> None:
        # threshold 0.5, width 0.05; observed 0.54 → diff +0.04 within width → near_above
        self.assertEqual(
            classify_threshold_regime(observed=0.54, threshold=0.5, measurement_family="ratio"),
            "near_above",
        )

    def test_far_above_ratio(self) -> None:
        # threshold 0.5, width 0.05; observed 0.80 → diff +0.30 > width → far_above
        self.assertEqual(
            classify_threshold_regime(observed=0.80, threshold=0.5, measurement_family="ratio"),
            "far_above",
        )

    def test_count_near_below(self) -> None:
        # threshold 10, width 1; observed 9 → near_below
        self.assertEqual(
            classify_threshold_regime(
                observed=9, threshold=10, measurement_family="count", integer_compare=True,
            ),
            "near_below",
        )

    def test_count_far_below(self) -> None:
        self.assertEqual(
            classify_threshold_regime(
                observed=5, threshold=10, measurement_family="count", integer_compare=True,
            ),
            "far_below",
        )

    def test_count_near_above(self) -> None:
        self.assertEqual(
            classify_threshold_regime(
                observed=11, threshold=10, measurement_family="count", integer_compare=True,
            ),
            "near_above",
        )

    def test_count_far_above(self) -> None:
        self.assertEqual(
            classify_threshold_regime(
                observed=20, threshold=10, measurement_family="count", integer_compare=True,
            ),
            "far_above",
        )

    def test_geometry_length_mm_classification(self) -> None:
        # threshold 1.0mm, width 0.10; observed 1.05mm → near_above (within width)
        self.assertEqual(
            classify_threshold_regime(
                observed=1.05, threshold=1.0,
                measurement_family="geometry_length", slot_unit="mm",
            ),
            "near_above",
        )

    def test_bool_family_returns_not_numeric(self) -> None:
        self.assertEqual(
            classify_threshold_regime(observed=True, threshold=False, measurement_family="bool"),
            "not_numeric",
        )

    def test_boolean_assertion_returns_not_numeric(self) -> None:
        self.assertEqual(
            classify_threshold_regime(
                observed=True, threshold=True, measurement_family="boolean_assertion",
            ),
            "not_numeric",
        )

    def test_enum_family_returns_not_numeric(self) -> None:
        self.assertEqual(
            classify_threshold_regime(observed="foo", threshold="bar", measurement_family="enum"),
            "not_numeric",
        )

    def test_non_coercible_returns_not_numeric(self) -> None:
        # 任意 string non-numeric
        self.assertEqual(
            classify_threshold_regime(
                observed="abc", threshold=10, measurement_family="ratio",
            ),
            "not_numeric",
        )

    def test_stress_classification(self) -> None:
        # threshold 100, width 5.0; observed 102 → diff +2 within width → near_above
        self.assertEqual(
            classify_threshold_regime(
                observed=102.0, threshold=100.0, measurement_family="stress",
            ),
            "near_above",
        )

    def test_stress_far_above(self) -> None:
        # threshold 100, width 5.0; observed 120 → diff +20 > width → far_above
        self.assertEqual(
            classify_threshold_regime(
                observed=120.0, threshold=100.0, measurement_family="stress",
            ),
            "far_above",
        )


if __name__ == "__main__":
    unittest.main()
