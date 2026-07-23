import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import (  # noqa: E402
    ArtifactRef,
    DecisionStep,
    DecisionTrace,
    EvidencePack,
    FactItem,
    FactPack,
    RuleCard,
    RuleCondition,
    SeedRuntime,
    TaskEdge,
    TaskGraph,
    TaskNode,
)


class EvidenceSchemaTests(unittest.TestCase):
    def _build_valid_pack(self) -> EvidencePack:
        task_graph = TaskGraph(
            case_id="case_test",
            phase="A",
            nodes=[TaskNode(node_id="n1", node_type="start", description="start")],
            edges=[TaskEdge(source="n1", target="n1")],
        )
        rule_cards = [
            RuleCard(
                rule_id="RC-1",
                title="rule",
                conditions=[RuleCondition(fact_key="crack_width_mm", comparator="<=", threshold=0.3)],
                rationale="test",
            )
        ]
        fact_pack = FactPack(
            case_id="case_test",
            generated_at="2026-02-26T00:00:00Z",
            facts=[
                FactItem(
                    fact_id="fact-1",
                    key="crack_width_mm",
                    value=0.2,
                    source_type="observer",
                    confidence=0.9,
                )
            ],
        )
        decision_trace = DecisionTrace(
            case_id="case_test",
            generated_at="2026-02-26T00:00:01Z",
            steps=[
                DecisionStep(
                    step_id="step-1",
                    rule_id="RC-1",
                    fact_ids=["fact-1"],
                    comparator="<=",
                    threshold=0.3,
                    observed_value=0.2,
                    passed=True,
                    reason="0.2 <= 0.3",
                )
            ],
            final_decision="pass",
            summary="ok",
        )
        references = [
            ArtifactRef(artifact_id="a1", artifact_type="task_graph", path="task_graph.json"),
            ArtifactRef(artifact_id="a2", artifact_type="rule_card", path="rule_cards.json"),
            ArtifactRef(artifact_id="a3", artifact_type="fact_pack", path="fact_pack.json"),
            ArtifactRef(artifact_id="a4", artifact_type="decision_trace", path="decision_trace.json"),
            ArtifactRef(artifact_id="a5", artifact_type="evidence_pack", path="evidence_pack.json"),
        ]
        return EvidencePack(
            phase="A",
            case_id="case_test",
            generated_at="2026-02-26T00:00:02Z",
            task_graph=task_graph,
            rule_cards=rule_cards,
            fact_pack=fact_pack,
            decision_trace=decision_trace,
            evidence_completeness=1.0,
            references=references,
        )

    def test_valid_evidence_pack(self) -> None:
        pack = self._build_valid_pack()
        self.assertEqual(pack.decision_trace.final_decision, "pass")
        self.assertEqual(pack.seed_runtime.matched_feature_ids, [])

    def test_invalid_fact_reference(self) -> None:
        pack = self._build_valid_pack()
        payload = pack.model_dump()
        payload["decision_trace"]["steps"][0]["fact_ids"] = ["missing"]
        with self.assertRaises(ValidationError):
            EvidencePack.model_validate(payload)

    def test_seed_runtime_contract_accepts_expected_shape(self) -> None:
        runtime = SeedRuntime.model_validate(
            {
                "matched_feature_ids": ["FF-001"],
                "matched_pattern_ids": ["FP-001"],
                "pattern_diagnostics": [
                    {
                        "pattern_id": "FP-001",
                        "name": "structural_crack_seed",
                        "matched": True,
                        "coverage_state": "grounded",
                        "missing_required": [],
                        "mismatched_required_values": [],
                        "blocked_by_negative": [],
                    }
                ],
                "trigger_evaluation": [
                    {
                        "trigger_id": "TR-001",
                        "name": "structural_crack_seed",
                        "matched": True,
                        "target_rule_ids": ["RC-CRACK-WIDTH"],
                        "missing_required_feature_ids": [],
                        "missing_required_pattern_ids": [],
                        "blocked_negative_feature_ids": [],
                    }
                ],
                "rule_seed_bridge": {
                    "RC-CRACK-WIDTH": {
                        "crack_width_mm": {
                            "feature_ids": ["FF-001"],
                            "pattern_ids": ["FP-001"],
                            "trigger_ids": ["TR-001"],
                        }
                    }
                },
            }
        )
        self.assertEqual(runtime.trigger_evaluation[0].trigger_id, "TR-001")
        self.assertEqual(
            runtime.rule_seed_bridge["RC-CRACK-WIDTH"]["crack_width_mm"].pattern_ids,
            ["FP-001"],
        )

    def test_seed_runtime_contract_rejects_invalid_trigger_shape(self) -> None:
        with self.assertRaises(ValidationError):
            SeedRuntime.model_validate(
                {
                    "matched_feature_ids": ["FF-001"],
                    "matched_pattern_ids": ["FP-001"],
                    "pattern_diagnostics": [],
                    "trigger_evaluation": [
                        {
                            "name": "missing_trigger_id",
                            "matched": True,
                            "target_rule_ids": [],
                            "missing_required_feature_ids": [],
                            "missing_required_pattern_ids": [],
                            "blocked_negative_feature_ids": [],
                        }
                    ],
                    "rule_seed_bridge": {},
                }
            )


if __name__ == "__main__":
    unittest.main()
