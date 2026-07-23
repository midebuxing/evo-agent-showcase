"""Tests for noise_models.py — spec 06 §13/§14 named noise model."""

from __future__ import annotations

import random
import unittest

from workflow_engine.worldgen.noise_models import (
    MEASUREMENT_FAMILY_TO_NOISE_MODEL,
    NOISE_MODEL_PARAMS,
    PRECISION_ROUNDING,
    apply_named_noise,
    apply_noise_bool_passthrough,
    apply_noise_count_poisson_round,
    apply_noise_geom_rel_abs_gauss,
    apply_noise_ratio_abs_gauss,
    apply_noise_tech_rel_gauss,
    apply_precision_rounding,
    get_noise_model_for_family,
)


class NoiseModelTests(unittest.TestCase):

    # 1. GEOM_REL_ABS_GAUSS：sigma 跟 rel*v 取 max，结果在 bounds 内
    def test_geom_rel_abs_gauss_clips_to_bounds(self) -> None:
        rng = random.Random(42)
        bounds = (0.0, 10.0)
        for _ in range(200):
            result = apply_noise_geom_rel_abs_gauss(5.0, 0.05, bounds, rng)
            self.assertGreaterEqual(result, bounds[0])
            self.assertLessEqual(result, bounds[1])

    def test_geom_rel_abs_gauss_uses_rel_sigma_when_larger(self) -> None:
        # rel_sigma=0.08 * 100 = 8.0 >> abs_sigma=0.05，所以 sigma 应该用 rel*v
        rng = random.Random(0)
        results = [apply_noise_geom_rel_abs_gauss(100.0, 0.05, (0.0, 200.0), rng) for _ in range(500)]
        # 输出应该围绕 100 散布（rel sigma=8，绝大多数 within ±30）
        self.assertTrue(any(abs(r - 100.0) > 1.0 for r in results), "Expected some noise around 100")

    # 2. RATIO_ABS_GAUSS：clip 到 [0, 1]
    def test_ratio_abs_gauss_clips_to_unit_interval(self) -> None:
        rng = random.Random(7)
        for _ in range(500):
            result = apply_noise_ratio_abs_gauss(0.5, rng)
            self.assertGreaterEqual(result, 0.0)
            self.assertLessEqual(result, 1.0)

    def test_ratio_abs_gauss_clips_near_boundary(self) -> None:
        rng = random.Random(99)
        # 边界值 0.0 和 1.0 大量采样也不越界
        for v in (0.0, 1.0):
            for _ in range(200):
                result = apply_noise_ratio_abs_gauss(v, rng)
                self.assertGreaterEqual(result, 0.0)
                self.assertLessEqual(result, 1.0)

    # 3. COUNT_POISSON_ROUND：返回非负整数；λ=0 返回 0
    def test_count_poisson_round_returns_non_negative_int(self) -> None:
        rng = random.Random(13)
        for lam in (0.0, 1.0, 5.0, 10.0):
            for _ in range(100):
                result = apply_noise_count_poisson_round(lam, rng)
                self.assertIsInstance(result, int)
                self.assertGreaterEqual(result, 0)

    def test_count_poisson_round_zero_lambda_returns_zero(self) -> None:
        rng = random.Random(0)
        self.assertEqual(apply_noise_count_poisson_round(0.0, rng), 0)

    # 4. TECH_REL_GAUSS：rel_sigma_override 生效
    def test_tech_rel_gauss_override_changes_spread(self) -> None:
        rng_default = random.Random(42)
        rng_override = random.Random(42)
        bounds = (0.0, 100.0)
        v = 50.0
        abs_sigma = 0.1
        results_default = [apply_noise_tech_rel_gauss(v, abs_sigma, bounds, rng_default) for _ in range(300)]
        results_override = [apply_noise_tech_rel_gauss(v, abs_sigma, bounds, rng_override, rel_sigma_override=0.05) for _ in range(300)]
        # 同 seed 但不同 rel_sigma，结果列表应该不同
        self.assertNotEqual(results_default, results_override)

    def test_tech_rel_gauss_clips_to_bounds(self) -> None:
        rng = random.Random(55)
        bounds = (10.0, 20.0)
        for _ in range(200):
            result = apply_noise_tech_rel_gauss(15.0, 0.5, bounds, rng)
            self.assertGreaterEqual(result, bounds[0])
            self.assertLessEqual(result, bounds[1])

    # 5. BOOL_DERIVED_NOISELESS：True → True，False → False
    def test_bool_passthrough_true(self) -> None:
        self.assertTrue(apply_noise_bool_passthrough(True))

    def test_bool_passthrough_false(self) -> None:
        self.assertFalse(apply_noise_bool_passthrough(False))

    # 6. apply_precision_rounding：standard / fine / coarse 各自步长
    def test_precision_rounding_standard(self) -> None:
        result = apply_precision_rounding(1.234, "geometry_width_mm", "standard")
        # standard step = 0.05，1.234 → round(1.234/0.05)*0.05 = round(24.68)*0.05 = 25*0.05 = 1.25
        self.assertAlmostEqual(result, 1.25, places=6)

    def test_precision_rounding_coarse(self) -> None:
        result = apply_precision_rounding(1.234, "geometry_width_mm", "coarse")
        # coarse step = 0.10，1.234 → round(12.34)*0.10 = 12*0.10 = 1.20
        self.assertAlmostEqual(result, 1.20, places=6)

    def test_precision_rounding_fine(self) -> None:
        result = apply_precision_rounding(1.234, "geometry_width_mm", "fine")
        # fine step = 0.01，1.234 → round(123.4)*0.01 = 123*0.01 = 1.23
        self.assertAlmostEqual(result, 1.23, places=6)

    def test_precision_rounding_unknown_key_passthrough(self) -> None:
        result = apply_precision_rounding(3.14159, "unknown_key")
        self.assertAlmostEqual(result, 3.14159, places=6)

    def test_precision_rounding_all_keys_present(self) -> None:
        expected_keys = {
            "geometry_width_mm", "geometry_length_m", "geometry_area_m2",
            "coverage_ratio", "test_stress", "thickness_depth_mm", "assessment_ratio",
        }
        self.assertEqual(set(PRECISION_ROUNDING.keys()), expected_keys)

    # 7. get_noise_model_for_family：5 个 family 都 map 到正确 model_id
    def test_get_noise_model_for_family_all_mappings(self) -> None:
        expected = {
            "defect_geometry": "GEOM_REL_ABS_GAUSS",
            "coverage_sampling": "RATIO_ABS_GAUSS",
            "technical_validation": "TECH_REL_GAUSS",
            "derived_risk_measurement": "TECH_REL_GAUSS",
            "boolean_assertion": "BOOL_DERIVED_NOISELESS",
        }
        for family, expected_model in expected.items():
            with self.subTest(family=family):
                self.assertEqual(get_noise_model_for_family(family), expected_model)

    def test_get_noise_model_for_family_unknown_defaults_to_tech(self) -> None:
        self.assertEqual(get_noise_model_for_family("nonexistent_family"), "TECH_REL_GAUSS")

    def test_measurement_family_to_noise_model_has_five_entries(self) -> None:
        self.assertEqual(len(MEASUREMENT_FAMILY_TO_NOISE_MODEL), 5)

    # 8. apply_named_noise dispatch：5 个 model_id 都能调通
    def test_apply_named_noise_geom(self) -> None:
        rng = random.Random(1)
        result = apply_named_noise("GEOM_REL_ABS_GAUSS", 5.0, (0.0, 10.0), abs_sigma=0.05, rng=rng)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 10.0)

    def test_apply_named_noise_ratio(self) -> None:
        rng = random.Random(2)
        result = apply_named_noise("RATIO_ABS_GAUSS", 0.5, (0.0, 1.0), rng=rng)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_apply_named_noise_count(self) -> None:
        rng = random.Random(3)
        result = apply_named_noise("COUNT_POISSON_ROUND", 5.0, (0.0, 100.0), rng=rng)
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)

    def test_apply_named_noise_tech(self) -> None:
        rng = random.Random(4)
        result = apply_named_noise("TECH_REL_GAUSS", 10.0, (0.0, 50.0), abs_sigma=0.1, rng=rng)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 50.0)

    def test_apply_named_noise_bool(self) -> None:
        rng = random.Random(5)
        self.assertTrue(apply_named_noise("BOOL_DERIVED_NOISELESS", True, (0.0, 1.0), rng=rng))
        self.assertFalse(apply_named_noise("BOOL_DERIVED_NOISELESS", False, (0.0, 1.0), rng=rng))

    def test_apply_named_noise_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            apply_named_noise("UNKNOWN_MODEL", 1.0, (0.0, 10.0))  # type: ignore[arg-type]

    # 9. 同 seed 输出可复现（pure function 立场）
    def test_reproducibility_same_seed(self) -> None:
        bounds = (0.0, 20.0)
        results_a = [apply_named_noise("GEOM_REL_ABS_GAUSS", 10.0, bounds, abs_sigma=0.1, rng=random.Random(77)) for _ in range(20)]
        results_b = [apply_named_noise("GEOM_REL_ABS_GAUSS", 10.0, bounds, abs_sigma=0.1, rng=random.Random(77)) for _ in range(20)]
        self.assertEqual(results_a, results_b)

    def test_reproducibility_different_seed_differs(self) -> None:
        bounds = (0.0, 20.0)
        results_a = [apply_named_noise("GEOM_REL_ABS_GAUSS", 10.0, bounds, abs_sigma=0.1, rng=random.Random(1)) for _ in range(20)]
        results_b = [apply_named_noise("GEOM_REL_ABS_GAUSS", 10.0, bounds, abs_sigma=0.1, rng=random.Random(2)) for _ in range(20)]
        self.assertNotEqual(results_a, results_b)

    # 10. NOISE_MODEL_PARAMS 有 5 個 model key
    def test_noise_model_params_has_five_models(self) -> None:
        expected_keys = {
            "GEOM_REL_ABS_GAUSS",
            "RATIO_ABS_GAUSS",
            "COUNT_POISSON_ROUND",
            "TECH_REL_GAUSS",
            "BOOL_DERIVED_NOISELESS",
        }
        self.assertEqual(set(NOISE_MODEL_PARAMS.keys()), expected_keys)


class GetAbsSigmaForSlotTests(unittest.TestCase):
    """#2 noise sigma 校准: get_abs_sigma_for_slot slot-specific 路由 (spec §14)."""

    def test_geometry_mm_returns_005(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "defect_geometry", "unit": "mm"}
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.05)

    def test_geometry_m_returns_0005(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "defect_geometry", "unit": "m"}
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.005)

    def test_geometry_m2_returns_0001(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "defect_geometry", "unit": "m2"}
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.001)

    def test_ratio_returns_003(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "coverage_sampling", "unit": "ratio"}
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.03)

    def test_explicit_count_poisson_model(self) -> None:
        """显式指定 noise model 走 COUNT_POISSON_ROUND 表."""
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "technical_validation", "unit": "count"}
        self.assertAlmostEqual(
            get_abs_sigma_for_slot(slot, noise_model_id="COUNT_POISSON_ROUND"), 1.0
        )

    def test_technical_validation_stress_mpa(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "technical_validation", "unit": "MPa"}
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.5)

    def test_unknown_unit_falls_back_to_default(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "defect_geometry", "unit": "wat_unknown"}
        # geometry _default = 0.005
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.005)

    def test_no_unit_treated_as_default(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "defect_geometry"}  # no unit field
        self.assertAlmostEqual(get_abs_sigma_for_slot(slot), 0.005)

    def test_bool_returns_zero(self) -> None:
        from workflow_engine.worldgen.noise_models import get_abs_sigma_for_slot
        slot = {"measurement_family": "boolean_assertion", "unit": "bool"}
        self.assertEqual(get_abs_sigma_for_slot(slot), 0.0)


if __name__ == "__main__":
    unittest.main()
