from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from research_kg.baseline_config import LocalLLMConfig
from research_kg.integrated_demo_runner import (
    DEFAULT_DEMO_QUERY_SET_PATH,
    DEFAULT_RESEARCH_KG_DIR,
    IntegratedDemoRunner,
    load_demo_query_set,
    write_phasee_comparison_artifacts,
)
from research_kg.loader import load_dual_source_kg


class IntegratedDemoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kg = load_dual_source_kg(DEFAULT_RESEARCH_KG_DIR)
        self.config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        self.runner = IntegratedDemoRunner(kg=self.kg, config=self.config)
        self.query_set_path = DEFAULT_DEMO_QUERY_SET_PATH
        self.query_set = load_demo_query_set(self.query_set_path)

    def _mock_llm_response(self, _config: LocalLLMConfig, prompt: str) -> str:
        if "外墙有1.5mm裂缝" in prompt:
            return json.dumps(
                {
                    "extracted_facts": {"crack_width_mm": 1.5},
                    "selected_rule_ids": ["RC-CRACK-WIDTH"],
                    "reasoning": "裂缝宽度明确命中裂缝链规则。",
                },
                ensure_ascii=False,
            )
        if "楼板混凝土剥落约0.2平方米，钢筋外露" in prompt:
            return json.dumps(
                {
                    "extracted_facts": {
                        "spalling_area_m2": 0.2,
                        "has_rebar_exposed": True,
                    },
                    "selected_rule_ids": ["RC-REBAR-EXPOSED", "RC-SPALL-AREA"],
                    "reasoning": "露筋与剥落事实同时出现，应命中复合缺陷链。",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "extracted_facts": {},
                "selected_rule_ids": [],
                "reasoning": "No supported facts extracted.",
            },
            ensure_ascii=False,
        )

    def test_demo_query_set_is_fixed_and_loadable(self) -> None:
        self.assertEqual(self.query_set["query_set_id"], "phasee_minimal_demo_v1")
        self.assertEqual(len(self.query_set["queries"]), 3)

    @patch("research_kg.integrated_demo_runner._call_llm")
    def test_baseline_crack_query_reaches_closure(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.side_effect = self._mock_llm_response

        result = self.runner.run(
            query="外墙有1.5mm裂缝",
            mode="baseline",
            query_id="demo_crack_chain",
        ).to_dict()

        self.assertEqual(result["selected_rule_ids"], ["RC-CRACK-WIDTH"])
        self.assertEqual(result["selected_rule_source"], "llm_selected")
        self.assertTrue(result["closure_verifier_reached"])
        self.assertEqual(result["chain_status"]["crack_chain"], "success")
        self.assertEqual(result["step_count"], 4)
        self.assertIsNone(result["routing_summary"])

    @patch("research_kg.integrated_demo_runner._call_llm")
    def test_routing_assisted_rebar_query_applies_top1_trigger(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.side_effect = self._mock_llm_response

        result = self.runner.run(
            query="楼板混凝土剥落约0.2平方米，钢筋外露",
            mode="routing_assisted",
            query_id="demo_rebar_spall_chain",
        ).to_dict()

        routing_summary = result["routing_summary"]
        self.assertIsNotNone(routing_summary)
        self.assertTrue(routing_summary["route_applied"])
        self.assertEqual(routing_summary["routed_trigger_id"], "TR-002")
        self.assertEqual(routing_summary["candidate_count_before"], 3)
        self.assertEqual(routing_summary["candidate_count_after"], 1)
        self.assertEqual(
            result["selected_rule_ids"],
            ["RC-REBAR-EXPOSED", "RC-SPALL-AREA"],
        )
        self.assertEqual(result["chain_status"]["rebar_spall_chain"], "success")
        self.assertTrue(result["closure_verifier_reached"])
        self.assertEqual(result["step_count"], 6)

    @patch("research_kg.integrated_demo_runner._call_llm")
    def test_unknown_query_stays_no_match_without_llm_call(
        self,
        mock_call: unittest.mock.MagicMock,
    ) -> None:
        result = self.runner.run(
            query="外墙涂料褪色，需要重新粉刷吗？",
            mode="routing_assisted",
            query_id="demo_unknown_chain",
        ).to_dict()

        self.assertFalse(result["closure_verifier_reached"])
        self.assertEqual(result["selected_rule_ids"], [])
        self.assertEqual(result["chain_status"]["crack_chain"], "not_matched")
        self.assertEqual(result["chain_status"]["rebar_spall_chain"], "not_matched")
        self.assertFalse(result["routing_summary"]["route_applied"])
        mock_call.assert_not_called()

    @patch("research_kg.integrated_demo_runner._call_llm")
    def test_write_phasee_comparison_artifacts(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.side_effect = self._mock_llm_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "phasee_demo"
            bundle = write_phasee_comparison_artifacts(
                query_set_path=self.query_set_path,
                output_dir=output_dir,
                config=self.config,
            )

            baseline_path = output_dir / "baseline_results.json"
            routing_path = output_dir / "routing_assisted_results.json"
            comparison_path = output_dir / "PhaseEComparisonReport.json"

            self.assertTrue(baseline_path.exists())
            self.assertTrue(routing_path.exists())
            self.assertTrue(comparison_path.exists())
            self.assertEqual(bundle["comparison_report_path"], str(comparison_path))

            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
            self.assertEqual(comparison["summary"]["regression_count"], 0)
            self.assertEqual(comparison["summary"]["route_applied_count"], 2)
            self.assertEqual(len(comparison["comparisons"]), 3)


if __name__ == "__main__":
    unittest.main()
