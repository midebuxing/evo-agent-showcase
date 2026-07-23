import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.closure_validator import validate_closure  # noqa: E402
from workflow_engine.evidence_schema import FactItem, FactPack, RuleCard, RuleCondition  # noqa: E402
from workflow_engine.obligation_schema import Obligation  # noqa: E402


class ClosureValidatorTests(unittest.TestCase):
    def _build_rule_missing_edges(self) -> RuleCard:
        return RuleCard(
            rule_id="RC-CRACK-WIDTH",
            title="Crack width threshold",
            rationale="MVP rule without closure edges.",
            conditions=[RuleCondition(fact_key="crack_width_mm", comparator="<=", threshold=0.3)],
        )

    def _build_rule_fully_closed(self) -> RuleCard:
        return RuleCard(
            rule_id="RC-CLOSED",
            title="Closed rule",
            rationale=(
                "closure.prerequisite_slots=precheck_done "
                "closure.exception_slots=has_exception "
                "closure.definition_slots=definition_ref"
            ),
            conditions=[RuleCondition(fact_key="crack_width_mm", comparator="<=", threshold=0.3)],
        )

    def test_allow_stop_false_when_missing_rule_edge_exists(self) -> None:
        fact_pack = FactPack(
            case_id="case_missing_edge",
            generated_at="2026-03-10T00:00:00Z",
            facts=[
                FactItem(
                    fact_id="f-1",
                    key="crack_width_mm",
                    value=0.2,
                    source_type="observer",
                    confidence=1.0,
                )
            ],
        )
        result = validate_closure([self._build_rule_missing_edges()], fact_pack)
        self.assertFalse(result.allow_stop)
        self.assertGreater(result.closure_summary.high_risk_open_count, 0)
        self.assertIn("missing_rule_edge", result.closure_summary.stop_reason)

    def test_allow_stop_true_when_closure_is_fully_satisfied(self) -> None:
        fact_pack = FactPack(
            case_id="case_closed",
            generated_at="2026-03-10T00:00:00Z",
            facts=[
                FactItem(
                    fact_id="f-1",
                    key="precheck_done",
                    value=True,
                    source_type="observer",
                    confidence=1.0,
                ),
                FactItem(
                    fact_id="f-2",
                    key="has_exception",
                    value=False,
                    source_type="observer",
                    confidence=1.0,
                ),
                FactItem(
                    fact_id="f-3",
                    key="definition_ref",
                    value="DEF-1",
                    source_type="observer",
                    confidence=1.0,
                ),
                FactItem(
                    fact_id="f-4",
                    key="crack_width_mm",
                    value=0.2,
                    source_type="observer",
                    confidence=1.0,
                ),
            ],
        )
        result = validate_closure([self._build_rule_fully_closed()], fact_pack)
        self.assertTrue(result.allow_stop)
        self.assertEqual(result.closure_summary.high_risk_open_count, 0)
        self.assertTrue(any(item.type == "threshold" and item.status == "supported" for item in result.obligations))

    def test_allow_stop_false_when_high_risk_unmet_exists(self) -> None:
        fact_pack = FactPack(case_id="case_blocked", generated_at="2026-03-10T00:00:00Z", facts=[])
        result = validate_closure([self._build_rule_missing_edges()], fact_pack)
        self.assertFalse(result.allow_stop)
        self.assertGreater(result.closure_summary.high_risk_open_count, 0)
        self.assertGreater(len(result.unmet_obligations), 0)

    def test_blocked_obligations_always_have_reason_code(self) -> None:
        fact_pack = FactPack(case_id="case_blocked", generated_at="2026-03-10T00:00:00Z", facts=[])
        result = validate_closure([self._build_rule_missing_edges()], fact_pack)
        blocked = [item for item in result.obligations if item.status == "blocked"]
        self.assertGreater(len(blocked), 0)
        self.assertTrue(all(item.blocked_reason_code is not None for item in blocked))

    def test_obligation_schema_blocked_reason_pass_and_fail(self) -> None:
        valid = Obligation(
            obligation_id="obl-1",
            source_rule_id="RC-1",
            type="threshold",
            required_fact_slots=["slot_1"],
            status="blocked",
            evidence_refs=[],
            notes="missing fact",
            blocked_reason_code="missing_fact",
        )
        self.assertEqual(valid.blocked_reason_code, "missing_fact")

        with self.assertRaises(ValidationError):
            Obligation(
                obligation_id="obl-2",
                source_rule_id="RC-1",
                type="threshold",
                required_fact_slots=["slot_1"],
                status="blocked",
                evidence_refs=[],
                notes="missing reason",
            )


if __name__ == "__main__":
    unittest.main()
