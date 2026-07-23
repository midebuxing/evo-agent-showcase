"""#3 整合测试: T-23 + T-24 + T-25 闭环 (evaluate_fragment_projection_candidates)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    build_threshold_evaluation,
    evaluate_fragment_projection_candidates,
)


class BuildThresholdEvaluationTests(unittest.TestCase):
    """T-25 + operator routing 集成 (build_threshold_evaluation)."""

    def test_pass_bool_le_within_bounds(self) -> None:
        # observed=0.46, threshold=0.5, ratio width=max(0.02, 0.10*0.5)=0.05
        # diff=-0.04 within width → near_below
        result = build_threshold_evaluation(
            rule_id="R001", threshold_regime_id="R001.t01", slot_id="ratio.test", operator="<=",
            threshold_value=0.5, observed_value=0.46,
            measurement_family="ratio",
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "near_below")
        self.assertEqual(result["rule_id"], "R001")
        self.assertEqual(result["slot_id"], "ratio.test")

    def test_pass_bool_le_at_threshold(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R002", threshold_regime_id="R002.t01", slot_id="ratio.test", operator="<=",
            threshold_value=0.5, observed_value=0.5,
            measurement_family="ratio",
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "exact_threshold")

    def test_pass_bool_lt_strict(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R003", threshold_regime_id="R003.t01", slot_id="ratio.test", operator="<",
            threshold_value=0.5, observed_value=0.5,
            measurement_family="ratio",
        )
        self.assertFalse(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "exact_threshold")

    def test_pass_bool_ge_at_threshold(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R004", threshold_regime_id="R004.t01", slot_id="stress.test", operator=">=",
            threshold_value=100.0, observed_value=100.0,
            measurement_family="stress",
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "exact_threshold")

    def test_pass_bool_eq_int_compare(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R005", threshold_regime_id="R005.t01", slot_id="count.x", operator="==",
            threshold_value=10, observed_value=10,
            measurement_family="count", integer_compare=True,
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "exact_threshold")

    def test_pass_bool_in_operator(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R006", threshold_regime_id="R006.t01", slot_id="enum.cls", operator="in",
            threshold_value=["a", "b"], observed_value="a",
            measurement_family="enum",
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "not_numeric")

    def test_pass_bool_not_in_operator(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R007", threshold_regime_id="R007.t01", slot_id="enum.cls", operator="not_in",
            threshold_value=["a", "b"], observed_value="c",
            measurement_family="enum",
        )
        self.assertTrue(result["pass_bool"])

    def test_regime_tag_near_above(self) -> None:
        result = build_threshold_evaluation(
            rule_id="R008", threshold_regime_id="R008.t01", slot_id="ratio.test", operator=">=",
            threshold_value=0.5, observed_value=0.54,  # diff +0.04, width=0.05
            measurement_family="ratio",
        )
        self.assertTrue(result["pass_bool"])
        self.assertEqual(result["regime_tag"], "near_above")

    def test_formula_regime_not_evaluable_unknown_not_false(self) -> None:
        """DEBT-056 前向修：formula 型制度（operator=='formula'，无 literal value）
        保守化为 not-numerically-evaluable → pass_bool=None（unknown），绝不 False（假 FAIL）。"""
        result = build_threshold_evaluation(
            rule_id="rc.pull.c01",
            threshold_regime_id="rc.pull.c01.t01",
            slot_id="count.pull_test.additional_after_failure",
            operator="formula",
            threshold_value=None,
            observed_value=5,
            measurement_family="count",
        )
        # pass_bool 必须是 None（not-evaluable），不是 False（假 FAIL）也不是 True。
        self.assertIsNone(result["pass_bool"])
        self.assertIsNot(result["pass_bool"], False)
        self.assertEqual(result["regime_tag"], "not_numeric")

    def test_formula_regime_family_verdict_unknown(self) -> None:
        """formula 型制度单独作为 family 唯一 threshold → family verdict = unknown（回基线态，非 fail）。"""
        from workflow_engine.regulation_projection_executor import _derive_family_verdict
        te = build_threshold_evaluation(
            rule_id="rc.pull.c01",
            threshold_regime_id="rc.pull.c01.t01",
            slot_id="count.pull_test.additional_after_failure",
            operator="formula",
            threshold_value=None,
            observed_value=5,
            measurement_family="count",
        )
        self.assertEqual(
            _derive_family_verdict("mbis.repair.external_structural_validation", [te], "covered"),
            "unknown",
        )


class EvaluateFragmentProjectionCandidatesTests(unittest.TestCase):
    """#3 整合: 闭环 evaluate_fragment_projection_candidates."""

    def test_no_candidates_returns_uncovered(self) -> None:
        """空 candidates → unknown_reason=no_known_family_match + projection_status=uncovered.

        W2-004 / spec 09 §2: projection_status 三态 covered/uncovered/conflict（无 unknown）；
        candidates 全空 → uncovered（无 family 适用）。
        """
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-001",
            candidate_families=[],
        )
        self.assertEqual(result["fragment_id"], "FRG-001")
        self.assertEqual(result["selected_family_ids"], [])
        self.assertEqual(result["unknown_reason_code"], "no_known_family_match")
        self.assertEqual(result["projection_status"], "uncovered")
        self.assertEqual(result["threshold_evaluations"], [])

    def test_single_applicable_family_returns_covered(self) -> None:
        """单 applicable family → covered, no unknown reason."""
        candidates = [{
            "family_id": "fam_A",
            "applicability_score": 0.8,
            "target_component_id": "CMP-001",
            "required_slots_present": True,
        }]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-002",
            candidate_families=candidates,
        )
        self.assertEqual(result["selected_family_ids"], ["fam_A"])
        self.assertIsNone(result["unknown_reason_code"])
        self.assertEqual(result["projection_status"], "covered")

    def test_multi_same_component_unresolvable_returns_conflict(self) -> None:
        """多 family 同 component (assessment_repair conflict_group) → multi_family_conflict + projection_status=conflict.

        W2-004 / spec 09 §2: same group multi-applicable 无 selector 解析 → conflict（不是 unknown）。
        """
        candidates = [
            {"family_id": "fam_A", "applicability_score": 0.8,
             "target_component_id": "CMP-001", "required_slots_present": True},
            {"family_id": "fam_B", "applicability_score": 0.7,
             "target_component_id": "CMP-001", "required_slots_present": True},
        ]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-003",
            candidate_families=candidates,
            conflict_group_id="assessment_repair",
        )
        self.assertEqual(result["selected_family_ids"], [])
        self.assertEqual(result["unknown_reason_code"], "multi_family_conflict")
        self.assertEqual(result["projection_status"], "conflict")

    def test_structural_external_falls_back_to_highest_score(self) -> None:
        """structural_external_surface group: 多 same component → highest_applicability_score."""
        candidates = [
            {"family_id": "fam_low", "applicability_score": 0.4,
             "target_component_id": "CMP-001", "required_slots_present": True},
            {"family_id": "fam_high", "applicability_score": 0.9,
             "target_component_id": "CMP-001", "required_slots_present": True},
        ]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-004",
            candidate_families=candidates,
            conflict_group_id="structural_external_surface",
        )
        self.assertEqual(result["selected_family_ids"], ["fam_high"])
        self.assertIsNone(result["unknown_reason_code"])

    def test_distinct_components_drainage_allows_multi(self) -> None:
        """drainage group + distinct target_component → allow multi-family."""
        candidates = [
            {"family_id": "drainage_A", "applicability_score": 0.7,
             "target_component_id": "CMP-pipe1", "required_slots_present": True},
            {"family_id": "drainage_B", "applicability_score": 0.6,
             "target_component_id": "CMP-pipe2", "required_slots_present": True},
        ]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-005",
            candidate_families=candidates,
            conflict_group_id="drainage",
        )
        self.assertEqual(set(result["selected_family_ids"]), {"drainage_A", "drainage_B"})
        self.assertIsNone(result["unknown_reason_code"])

    def test_threshold_evaluations_built_for_covered_family(self) -> None:
        """selected_family present + threshold_eval_inputs → threshold_evaluations 含 regime + pass_bool."""
        candidates = [{
            "family_id": "fam_A", "applicability_score": 0.8,
            "target_component_id": "CMP-001", "required_slots_present": True,
        }]
        threshold_inputs = [
            {
                "rule_id": "R001", "threshold_regime_id": "R001.t01",
                "slot_id": "ratio.cov",
                "operator": "<=", "threshold_value": 0.8,
                "observed_value": 0.5,
                "measurement_family": "ratio",
            },
            {
                "rule_id": "R002", "threshold_regime_id": "R002.t01",
                "slot_id": "stress.test",
                "operator": ">=", "threshold_value": 100.0,
                "observed_value": 95.0,
                "measurement_family": "stress",
            },
        ]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-006",
            candidate_families=candidates,
            threshold_eval_inputs=threshold_inputs,
        )
        self.assertEqual(len(result["threshold_evaluations"]), 2)
        self.assertEqual(result["threshold_evaluations"][0]["rule_id"], "R001")
        self.assertTrue(result["threshold_evaluations"][0]["pass_bool"])
        self.assertEqual(result["threshold_evaluations"][1]["rule_id"], "R002")
        # observed=95 < threshold=100，但在 width=5 内 → near_below
        self.assertEqual(result["threshold_evaluations"][1]["regime_tag"], "near_below")
        self.assertFalse(result["threshold_evaluations"][1]["pass_bool"])

    def test_extra_unknown_context_routes_to_specific_reason(self) -> None:
        """extra_unknown_context 提供时，T-24 routing 用更精确 reason."""
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-007",
            candidate_families=[],
            extra_unknown_context={"binding_registry_gap": True},
        )
        # has_known_family_match=False (空 candidates) → no_known_family_match 优先于 binding_registry_gap
        self.assertEqual(result["unknown_reason_code"], "no_known_family_match")

    def test_extra_unknown_context_with_known_family_routes_correctly(self) -> None:
        """有 candidate 但 required_slots_present=False，结合 extra context."""
        candidates = [{
            "family_id": "fam_A", "applicability_score": 0.8,
            "target_component_id": "CMP-001",
            "required_slots_present": False,  # binding 缺
        }]
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-008",
            candidate_families=candidates,
            extra_unknown_context={"binding_registry_gap": True},
        )
        self.assertEqual(result["selected_family_ids"], [])
        # candidates 都 required_slots_present=False → has_known_family_match=False → no_known_family_match
        # 优先于 binding_registry_gap
        self.assertEqual(result["unknown_reason_code"], "no_known_family_match")

    def test_threshold_evaluations_empty_when_unknown(self) -> None:
        """unknown 状态下 threshold_evaluations 留空（无 selected family 不评估 threshold）."""
        result = evaluate_fragment_projection_candidates(
            fragment_id="FRG-009",
            candidate_families=[],
            threshold_eval_inputs=[
                {"rule_id": "R001", "slot_id": "ratio.x", "operator": "<=",
                 "threshold_value": 0.5, "observed_value": 0.3,
                 "measurement_family": "ratio"}
            ],
        )
        self.assertEqual(result["threshold_evaluations"], [])


class ThresholdEvalRegimeIdModelTests(unittest.TestCase):
    """DEBT-054 Block B.1：ThresholdEval.threshold_regime_id required + ⊥ regime_tag twin."""

    def _model(self):
        from workflow_engine.regulation_projection_models import ThresholdEval
        return ThresholdEval

    def test_threshold_regime_id_and_regime_tag_coexist(self) -> None:
        """制度键 threshold_regime_id 与观测分箱 regime_tag 正交并存、命名勿混。"""
        te = self._model()(
            rule_id="rc.x.c01",
            threshold_regime_id="rc.x.c01.t01",
            slot_id="ratio.x",
            operator="<=",
            threshold_value=0.5,
            observed_value=0.4,
            regime_tag="near_below",
            pass_bool=True,
        )
        self.assertEqual(te.threshold_regime_id, "rc.x.c01.t01")
        self.assertEqual(te.regime_tag, "near_below")
        self.assertNotEqual(te.threshold_regime_id, te.regime_tag)

    def test_missing_threshold_regime_id_raises(self) -> None:
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self._model()(
                rule_id="rc.x.c01", slot_id="ratio.x", operator="<=",
                threshold_value=0.5, observed_value=0.4,
                regime_tag="near_below", pass_bool=True,
            )

    def test_empty_threshold_regime_id_raises(self) -> None:
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self._model()(
                rule_id="rc.x.c01", threshold_regime_id="", slot_id="ratio.x",
                operator="<=", threshold_value=0.5, observed_value=0.4,
                regime_tag="near_below", pass_bool=True,
            )


if __name__ == "__main__":
    unittest.main()
