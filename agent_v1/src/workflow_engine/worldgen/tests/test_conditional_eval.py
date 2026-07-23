"""Tests for spec 06 §11.6 conditional formula evaluator (DEBT-020 Round5 sub-task 3 配套)."""

from __future__ import annotations

import math
import random
import unittest

from workflow_engine.worldgen.conditional_eval import (
    ALLOWED_INPUTS,
    build_evaluator_context,
    evaluate_bool_conditional,
    evaluate_enum_conditional,
    expected_marginal_bool,
    expected_marginal_enum,
    validate_formula,
)


class BoolSigmoidLinearTests(unittest.TestCase):
    def test_zero_bias_zero_inputs_p_half(self) -> None:
        formula = {"type": "sigmoid_linear", "bias": 0.0, "terms": {}}
        # 期望 P=0.5 → 1000 sample 后 mean ≈ 0.5 ± 0.05
        rng = random.Random(42)
        samples = [evaluate_bool_conditional(formula, {}, rng) for _ in range(2000)]
        mean = sum(samples) / len(samples)
        self.assertAlmostEqual(mean, 0.5, delta=0.05)

    def test_extreme_negative_bias_near_zero(self) -> None:
        formula = {"type": "sigmoid_linear", "bias": -10.0, "terms": {}}
        rng = random.Random(7)
        samples = [evaluate_bool_conditional(formula, {}, rng) for _ in range(500)]
        # sigmoid(-10) ≈ 0.0000454 → 500 sample 几乎全 False
        self.assertLess(sum(samples), 5)

    def test_extreme_positive_bias_near_one(self) -> None:
        formula = {"type": "sigmoid_linear", "bias": 10.0, "terms": {}}
        rng = random.Random(11)
        samples = [evaluate_bool_conditional(formula, {}, rng) for _ in range(500)]
        self.assertGreater(sum(samples), 495)

    def test_input_drives_p(self) -> None:
        # bias=0 + 5*defect_class_present ; defect=1 → sigmoid(5)=0.993
        formula = {"type": "sigmoid_linear", "bias": 0.0, "terms": {"defect_class_present": 5.0}}
        rng = random.Random(13)
        samples = [evaluate_bool_conditional(formula, {"defect_class_present": 1.0}, rng) for _ in range(500)]
        mean_with = sum(samples) / 500
        rng = random.Random(13)
        samples = [evaluate_bool_conditional(formula, {"defect_class_present": 0.0}, rng) for _ in range(500)]
        mean_without = sum(samples) / 500
        self.assertGreater(mean_with, 0.95)
        self.assertAlmostEqual(mean_without, 0.5, delta=0.05)

    def test_missing_input_defaults_to_zero_no_error(self) -> None:
        formula = {"type": "sigmoid_linear", "bias": 1.0, "terms": {"age_norm": 2.0}}
        rng = random.Random(17)
        # 不传 age_norm → 当 0；总 raw = 1.0 + 0 = 1.0 → sigmoid(1)=0.731
        samples = [evaluate_bool_conditional(formula, {}, rng) for _ in range(2000)]
        mean = sum(samples) / 2000
        self.assertAlmostEqual(mean, 0.731, delta=0.04)

    def test_round5_proagent_formula_real(self) -> None:
        """Round5 sub-task 3 实例 procedure.ri.appointment.completed (round4 marginal=0.86)."""
        formula = {
            "type": "sigmoid_linear",
            "bias": 1.05,
            "terms": {
                "defect_class_present": 0.45,
                "age_norm": 0.20,
                "building_total_severity_max": 0.15,
                "maintenance_deficit": -0.25,
            },
        }
        # 模拟 1000 fragment 群体（与 round4 fragment population 大致 stress test）
        rng = random.Random(42)
        ctxs = []
        for _ in range(1000):
            ctxs.append(build_evaluator_context(
                age_years=rng.uniform(0, 100),
                maintenance_deficit=rng.random(),
                defect_class_present=rng.random() > 0.3,  # 70% 有 defect 倾向
                building_total_severity_max=rng.random() * 0.8,
            ))
        marginal = expected_marginal_bool(formula, ctxs)
        # round4 prevalence 0.86，conditional 期望 0.84-0.88
        self.assertGreater(marginal, 0.78)
        self.assertLess(marginal, 0.92)


class EnumSoftmaxPerClassTests(unittest.TestCase):
    def test_uniform_logits_uniform_distribution(self) -> None:
        formula = {
            "type": "softmax_per_class",
            "classes": {
                "a": {"bias": 0.0, "terms": {}},
                "b": {"bias": 0.0, "terms": {}},
                "c": {"bias": 0.0, "terms": {}},
            },
        }
        rng = random.Random(42)
        counts = {"a": 0, "b": 0, "c": 0}
        for _ in range(3000):
            sample = evaluate_enum_conditional(formula, {}, rng)
            counts[sample] += 1
        for c in counts:
            # 期望 each ≈ 1000，允许 ±100
            self.assertGreater(counts[c], 880)
            self.assertLess(counts[c], 1120)

    def test_dominant_class_high_logit(self) -> None:
        formula = {
            "type": "softmax_per_class",
            "classes": {
                "dominant": {"bias": 5.0, "terms": {}},
                "minor_a": {"bias": 0.0, "terms": {}},
                "minor_b": {"bias": 0.0, "terms": {}},
            },
        }
        rng = random.Random(7)
        counts = {"dominant": 0, "minor_a": 0, "minor_b": 0}
        for _ in range(1000):
            sample = evaluate_enum_conditional(formula, {}, rng)
            counts[sample] += 1
        # softmax(5)/(softmax(5)+2*softmax(0)) ≈ 148/150 ≈ 0.987
        self.assertGreater(counts["dominant"], 970)

    def test_input_shifts_class_probabilities(self) -> None:
        # qual.method_class 简化版
        formula = {
            "type": "softmax_per_class",
            "classes": {
                "drainage_cctv": {
                    "bias": -0.6,
                    "terms": {"drainage_blockage_index": 1.10, "drainage_leakage_index": 0.70},
                },
                "visual_inspection": {
                    "bias": 1.0,
                    "terms": {"defect_class_present": 0.25},
                },
            },
        }
        rng = random.Random(11)
        # 高 drainage 缺陷 → drainage_cctv 应胜出
        ctx_drainage = {"drainage_blockage_index": 0.9, "drainage_leakage_index": 0.85, "defect_class_present": 1.0}
        counts_drainage = {"drainage_cctv": 0, "visual_inspection": 0}
        for _ in range(1000):
            sample = evaluate_enum_conditional(formula, ctx_drainage, rng)
            counts_drainage[sample] += 1
        # logit_cctv = -0.6 + 0.99 + 0.595 = 0.985
        # logit_visual = 1.0 + 0.25 = 1.25
        # P(visual)/P(cctv) = exp(1.25-0.985) = exp(0.265) ≈ 1.30
        # P(cctv) ≈ 1/(1+1.30) ≈ 0.435
        self.assertGreater(counts_drainage["drainage_cctv"], 350)
        self.assertLess(counts_drainage["drainage_cctv"], 540)


class ValidateFormulaTests(unittest.TestCase):
    def test_none_ok(self) -> None:
        validate_formula(None)  # should not raise

    def test_valid_sigmoid_linear(self) -> None:
        validate_formula({
            "type": "sigmoid_linear",
            "bias": 0.5,
            "terms": {"age_norm": 0.3, "defect_class_present": -0.2},
        })

    def test_valid_softmax_per_class(self) -> None:
        validate_formula({
            "type": "softmax_per_class",
            "classes": {
                "a": {"bias": 0.0, "terms": {"age_norm": 0.5}},
                "b": {"bias": 1.0, "terms": {}},
            },
        })

    def test_unknown_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({"type": "linear_regression", "bias": 0.0, "terms": {}})

    def test_unknown_input_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_formula({
                "type": "sigmoid_linear",
                "bias": 0.0,
                "terms": {"random_unknown_input": 0.5},
            })
        self.assertIn("ALLOWED_INPUTS", str(ctx.exception))

    def test_non_numeric_coef_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({
                "type": "sigmoid_linear",
                "bias": 0.0,
                "terms": {"age_norm": "0.5"},  # str 不是 number
            })

    def test_bool_coef_rejected(self) -> None:
        # bool 是 int 的子类，但语义上不应作为 coefficient
        with self.assertRaises(ValueError):
            validate_formula({
                "type": "sigmoid_linear",
                "bias": True,
                "terms": {},
            })

    def test_softmax_empty_classes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({"type": "softmax_per_class", "classes": {}})


class BuildEvaluatorContextTests(unittest.TestCase):
    def test_age_norm_clipped(self) -> None:
        ctx = build_evaluator_context(age_years=75)
        self.assertEqual(ctx["age_norm"], 1.0)  # 75/50 = 1.5 → clip to 1.0
        ctx = build_evaluator_context(age_years=10)
        self.assertEqual(ctx["age_norm"], 0.2)
        ctx = build_evaluator_context(age_years=-5)
        self.assertEqual(ctx["age_norm"], 0.0)

    def test_bool_to_float(self) -> None:
        ctx = build_evaluator_context(defect_class_present=True)
        self.assertEqual(ctx["defect_class_present"], 1.0)
        ctx = build_evaluator_context(defect_class_present=False)
        self.assertEqual(ctx["defect_class_present"], 0.0)

    def test_building_defect_count_normalized(self) -> None:
        ctx = build_evaluator_context(building_defect_count=10)
        self.assertEqual(ctx["building_defect_count_norm"], 0.5)
        ctx = build_evaluator_context(building_defect_count=30)
        self.assertEqual(ctx["building_defect_count_norm"], 1.0)  # cap

    def test_unset_inputs_not_in_context(self) -> None:
        ctx = build_evaluator_context(age_years=25)
        self.assertIn("age_norm", ctx)
        self.assertNotIn("crack_severity_index", ctx)  # 不传 → 不在 dict（evaluator 默认 0.0）

    def test_all_keys_in_allowed_inputs(self) -> None:
        # 全套参数都传，验证 build 出的 keys 都在 ALLOWED_INPUTS
        ctx = build_evaluator_context(
            age_years=30, service_load_ratio=0.7, restraint_level=0.4,
            workmanship_deficit=0.3, maintenance_deficit=0.2,
            moisture_ingress_index=0.5, chloride_exposure=0.4,
            crack_severity_index=0.5, spall_severity_index=0.3,
            corrosion_severity_index=0.2, delamination_severity_index=0.1,
            detachment_severity_index=0.1,
            drainage_blockage_index=0.3, drainage_leakage_index=0.2,
            public_health_risk_index=0.3,
            defect_class_present=True, ubw_alteration_present=False,
            fire_safety_deficiency_present=False,
            repair_quality_index=0.7, fsp_structural_performance=1.0,
            building_total_severity_max=0.6, building_defect_count=5,
        )
        for key in ctx.keys():
            self.assertIn(key, ALLOWED_INPUTS, f"unexpected context key {key}")


class ExpectedMarginalTests(unittest.TestCase):
    def test_bool_marginal_consistency(self) -> None:
        formula = {"type": "sigmoid_linear", "bias": 0.0, "terms": {"age_norm": 2.0}}
        # age_norm=0.5 across 1000 fragment → raw=1.0 → sigmoid(1)≈0.731
        ctxs = [{"age_norm": 0.5} for _ in range(1000)]
        marginal = expected_marginal_bool(formula, ctxs)
        self.assertAlmostEqual(marginal, 1.0 / (1.0 + math.exp(-1.0)), places=4)

    def test_enum_marginal_consistency(self) -> None:
        formula = {
            "type": "softmax_per_class",
            "classes": {
                "a": {"bias": 1.0, "terms": {}},
                "b": {"bias": 0.0, "terms": {}},
            },
        }
        ctxs = [{} for _ in range(100)]
        marginal = expected_marginal_enum(formula, ctxs)
        # P(a) = e^1 / (e^1 + e^0) = e/(e+1) ≈ 0.731
        self.assertAlmostEqual(marginal["a"], math.e / (math.e + 1), places=4)
        self.assertAlmostEqual(marginal["b"], 1.0 / (math.e + 1), places=4)


if __name__ == "__main__":
    unittest.main()
