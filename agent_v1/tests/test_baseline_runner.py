"""Tests for Phase D DualSourceBaselineRunner.

Tests are split into:
  1. Offline tests (no LLM call) — always run
  2. Integration test (real LLM call) — requires env vars, skipped if unavailable
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from research_kg.baseline_config import LocalLLMConfig
from research_kg.baseline_runner import (
    DualSourceBaselineRunner,
    LocalBaselineReport,
    _build_fact_pack,
    _build_extraction_prompt,
    _build_rule_cards_for_closure,
    _build_seed_rule_bridge,
    _parse_llm_response,
    run_baseline,
)
from research_kg.kg_retriever import RetrievalResult, detect_chain, retrieve_from_kg
from research_kg.loader import load_dual_source_kg

RESEARCH_KG_DIR = _REPO / "research_kg"


class TestChainDetection(unittest.TestCase):
    def test_crack_keywords(self) -> None:
        self.assertEqual(detect_chain("外墙有0.5mm裂缝"), "crack_chain")
        self.assertEqual(detect_chain("crack width 0.3mm"), "crack_chain")

    def test_rebar_spall_keywords(self) -> None:
        self.assertEqual(detect_chain("楼板混凝土剥落，钢筋外露"), "rebar_spall_chain")
        self.assertEqual(detect_chain("rebar exposed with spalling"), "rebar_spall_chain")

    def test_rebar_spall_takes_priority(self) -> None:
        # When both keywords present, rebar_spall wins (more severe)
        self.assertEqual(detect_chain("裂缝和钢筋外露"), "rebar_spall_chain")

    def test_unknown(self) -> None:
        self.assertEqual(detect_chain("天气很好"), "unknown")


class TestKGRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_crack_chain_retrieval(self) -> None:
        result = retrieve_from_kg(self.kg, "外墙有0.5mm裂缝")
        self.assertEqual(result.matched_chain, "crack_chain")
        self.assertTrue(len(result.rule_cards) > 0)
        self.assertEqual(result.rule_cards[0]["node_id"], "RC-CRACK-WIDTH")
        self.assertTrue(len(result.skills) > 0)

    def test_rebar_spall_chain_retrieval(self) -> None:
        result = retrieve_from_kg(self.kg, "剥落和钢筋外露")
        self.assertEqual(result.matched_chain, "rebar_spall_chain")
        rc_ids = [rc["node_id"] for rc in result.rule_cards]
        self.assertIn("RC-REBAR-EXPOSED", rc_ids)
        self.assertIn("RC-SPALL-AREA", rc_ids)

    def test_unknown_query_returns_empty(self) -> None:
        result = retrieve_from_kg(self.kg, "今天天气不错")
        self.assertEqual(result.matched_chain, "unknown")
        self.assertEqual(len(result.rule_cards), 0)

    def test_retrieval_summary(self) -> None:
        result = retrieve_from_kg(self.kg, "裂缝")
        s = result.summary()
        self.assertIn("matched_chain", s)
        self.assertIn("rule_card_ids", s)


class TestLLMResponseParsing(unittest.TestCase):
    def test_parse_clean_json(self) -> None:
        raw = '{"extracted_facts": {"crack_width_mm": 0.5}, "selected_rule_ids": ["RC-CRACK-WIDTH"], "reasoning": "test"}'
        parsed = _parse_llm_response(raw)
        self.assertEqual(parsed["extracted_facts"]["crack_width_mm"], 0.5)

    def test_parse_markdown_fenced_json(self) -> None:
        raw = '```json\n{"extracted_facts": {"crack_width_mm": 0.3}, "selected_rule_ids": [], "reasoning": "ok"}\n```'
        parsed = _parse_llm_response(raw)
        self.assertEqual(parsed["extracted_facts"]["crack_width_mm"], 0.3)

    def test_parse_invalid_json(self) -> None:
        raw = "This is not JSON at all"
        parsed = _parse_llm_response(raw)
        self.assertIn("parse_error", parsed)


class TestFactPackBuilder(unittest.TestCase):
    def test_builds_from_extracted_facts(self) -> None:
        extracted = {"crack_width_mm": 0.5, "has_rebar_exposed": None}
        fp = _build_fact_pack("test query", extracted, "crack_chain")
        self.assertEqual(fp.case_id, "phaseD-baseline-crack_chain")
        self.assertEqual(len(fp.facts), 1)
        self.assertEqual(fp.facts[0].key, "crack_width_mm")
        self.assertEqual(fp.facts[0].value, 0.5)

    def test_empty_facts(self) -> None:
        fp = _build_fact_pack("test", {}, "unknown")
        self.assertEqual(len(fp.facts), 0)


class TestRuleCardConversion(unittest.TestCase):
    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_converts_to_evidence_schema(self) -> None:
        retrieval = retrieve_from_kg(self.kg, "裂缝0.3mm")
        rcs = _build_rule_cards_for_closure(retrieval)
        self.assertTrue(len(rcs) > 0)
        rc = rcs[0]
        self.assertEqual(rc.rule_id, "RC-CRACK-WIDTH")
        self.assertTrue(len(rc.conditions) > 0)


class TestSeedRuleBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_bridge_for_crack_chain(self) -> None:
        retrieval = retrieve_from_kg(self.kg, "裂缝")
        bridge = _build_seed_rule_bridge(retrieval)
        self.assertIn("RC-CRACK-WIDTH", bridge)
        self.assertIn("crack_width_mm", bridge["RC-CRACK-WIDTH"])
        slot = bridge["RC-CRACK-WIDTH"]["crack_width_mm"]
        self.assertIn("TR-001", slot["trigger_ids"])


class TestBaselineReportSerialization(unittest.TestCase):
    def test_report_to_json_round_trip(self) -> None:
        """Test that a report with mock data serializes to valid JSON."""
        from workflow_engine.evidence_schema import FactPack

        report = LocalBaselineReport(
            query="test",
            config_summary={"model": "test-model"},
            retrieval_summary={"matched_chain": "crack_chain"},
            llm_response={"reasoning": "test"},
            fact_pack=FactPack(case_id="test", generated_at="2026-01-01T00:00:00Z", facts=[]),
            closure_result=None,
            chain_status={"crack_chain": "success"},
        )
        j = report.to_json()
        reloaded = json.loads(j)
        self.assertEqual(reloaded["query"], "test")


class TestBaselineRunnerOffline(unittest.TestCase):
    """Test runner with mocked LLM call."""

    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def _mock_llm_response(self) -> str:
        return json.dumps({
            "extracted_facts": {"crack_width_mm": 0.25},
            "selected_rule_ids": ["RC-CRACK-WIDTH"],
            "reasoning": "描述中提到裂缝宽度",
        })

    @patch("research_kg.baseline_runner._call_llm")
    def test_crack_chain_end_to_end(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.return_value = self._mock_llm_response()
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.25mm裂缝")

        self.assertEqual(report.chain_status["crack_chain"], "success")
        self.assertIsNotNone(report.closure_result)
        # Threshold passes (0.25 <= 0.3), but allow_stop=False because
        # exception/definition slots are not configured (missing_rule_edge).
        # This is correct closure validator behavior.
        self.assertFalse(report.closure_result.allow_stop)
        # Verify threshold obligation itself is supported
        threshold_obls = [
            o for o in report.closure_result.obligations if o.type == "threshold"
        ]
        self.assertTrue(any(o.status == "supported" for o in threshold_obls))

    @patch("research_kg.baseline_runner._call_llm")
    def test_crack_chain_fail(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.return_value = json.dumps({
            "extracted_facts": {"crack_width_mm": 0.5},
            "selected_rule_ids": ["RC-CRACK-WIDTH"],
            "reasoning": "裂缝宽度超标",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.5mm裂缝")

        self.assertEqual(report.chain_status["crack_chain"], "success")
        self.assertIsNotNone(report.closure_result)
        # 0.5mm > 0.3mm threshold, so allow_stop should be False
        self.assertFalse(report.closure_result.allow_stop)

    @patch("research_kg.baseline_runner._call_llm")
    def test_rebar_spall_chain(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.return_value = json.dumps({
            "extracted_facts": {
                "has_rebar_exposed": True,
                "spalling_area_m2": 0.2,
            },
            "selected_rule_ids": ["RC-REBAR-EXPOSED", "RC-SPALL-AREA"],
            "reasoning": "钢筋外露且剥落面积超标",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("楼板混凝土剥落约0.2平方米，钢筋外露")

        self.assertEqual(report.chain_status["rebar_spall_chain"], "success")
        self.assertIsNotNone(report.closure_result)
        # rebar exposed=True fails RC-REBAR-EXPOSED, spalling 0.2>0.1 fails RC-SPALL-AREA
        self.assertFalse(report.closure_result.allow_stop)

    @patch("research_kg.baseline_runner._call_llm")
    def test_unknown_query(self, mock_call: unittest.mock.MagicMock) -> None:
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("今天天气不错")

        self.assertEqual(report.chain_status["crack_chain"], "not_matched")
        self.assertIsNone(report.closure_result)
        mock_call.assert_not_called()  # LLM should not be called for unknown


class TestLocalURLValidation(unittest.TestCase):
    """Verify that non-local URLs are rejected."""

    def test_localhost_accepted(self) -> None:
        config = LocalLLMConfig(
            base_url="http://localhost:11434/v1",
            api_key="no-key",
            model="test",
        )
        self.assertEqual(config.base_url, "http://localhost:11434/v1")

    def test_127_accepted(self) -> None:
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="no-key",
            model="test",
        )
        self.assertIn("127.0.0.1", config.base_url)

    def test_remote_url_rejected(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            LocalLLMConfig(
                base_url="https://hiapi.online/v1",
                api_key="some-key",
                model="test",
            )
        self.assertIn("本地地址", str(ctx.exception))

    def test_public_ip_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            LocalLLMConfig(
                base_url="http://8.8.8.8:8080/v1",
                api_key="key",
                model="test",
            )

    def test_default_model_switches_to_qwen35(self) -> None:
        with patch("research_kg.baseline_config._load_env"), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCAL_LLM_MODEL", None)
            os.environ.pop("LLM_MODEL", None)
            os.environ.pop("LLM_TIMEOUT", None)
            config = LocalLLMConfig(
                base_url="http://127.0.0.1:11434/v1",
                api_key="no-key",
            )
        self.assertEqual(config.model, "qwen3.5:latest")
        self.assertEqual(config.timeout, 360)


class TestSelectedRuleIdsFiltering(unittest.TestCase):
    """Verify that LLM selected_rule_ids drives closure input."""

    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_filter_rule_cards(self) -> None:
        retrieval = retrieve_from_kg(self.kg, "剥落和钢筋外露")
        self.assertEqual(len(retrieval.rule_cards), 2)
        filtered = retrieval.filter_rule_cards(["RC-REBAR-EXPOSED"])
        self.assertEqual(len(filtered.rule_cards), 1)
        self.assertEqual(filtered.rule_cards[0]["node_id"], "RC-REBAR-EXPOSED")
        # Other fields preserved
        self.assertEqual(filtered.matched_chain, "rebar_spall_chain")
        self.assertEqual(len(filtered.skills), len(retrieval.skills))

    @patch("research_kg.baseline_runner._call_llm")
    def test_selected_ids_used_in_closure(self, mock_call: unittest.mock.MagicMock) -> None:
        """When LLM returns selected_rule_ids, only those rules go to closure."""
        mock_call.return_value = json.dumps({
            "extracted_facts": {
                "has_rebar_exposed": True,
                "spalling_area_m2": 0.2,
            },
            "selected_rule_ids": ["RC-REBAR-EXPOSED"],  # Only one of two
            "reasoning": "只选了露筋规则",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("楼板混凝土剥落约0.2平方米，钢筋外露")

        self.assertEqual(report.llm_response["_rule_selection_mode"], "llm_selected")
        # Closure should only have obligations for RC-REBAR-EXPOSED, not RC-SPALL-AREA
        if report.closure_result:
            rule_ids_in_obligations = {
                o.source_rule_id for o in report.closure_result.obligations
            }
            self.assertIn("RC-REBAR-EXPOSED", rule_ids_in_obligations)
            self.assertNotIn("RC-SPALL-AREA", rule_ids_in_obligations)

    @patch("research_kg.baseline_runner._call_llm")
    def test_selected_ids_with_prefix_are_normalized(self, mock_call: unittest.mock.MagicMock) -> None:
        """LLM may prepend Chinese labels like '规则 '; normalization should recover node ids."""
        mock_call.return_value = json.dumps({
            "extracted_facts": {"crack_width_mm": 0.5},
            "selected_rule_ids": ["规则 RC-CRACK-WIDTH"],
            "reasoning": "裂缝宽度超标",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.5mm裂缝")

        self.assertEqual(report.llm_response["selected_rule_ids"], ["RC-CRACK-WIDTH"])
        self.assertEqual(report.llm_response["_rule_selection_mode"], "llm_selected")
        self.assertIsNotNone(report.closure_result)
        if report.closure_result:
            rule_ids_in_obligations = {
                o.source_rule_id for o in report.closure_result.obligations
            }
            self.assertIn("RC-CRACK-WIDTH", rule_ids_in_obligations)

    @patch("research_kg.baseline_runner._call_llm")
    def test_unmatched_selected_ids_fallback_to_all_rules(
        self,
        mock_call: unittest.mock.MagicMock,
    ) -> None:
        """Non-empty but unmatched selected ids should not produce an empty closure input."""
        mock_call.return_value = json.dumps({
            "extracted_facts": {"crack_width_mm": 0.3},
            "selected_rule_ids": ["NOT-A-REAL-RULE"],
            "reasoning": "错误规则名",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.3mm裂缝")

        self.assertEqual(report.llm_response["selected_rule_ids"], [])
        self.assertEqual(report.llm_response["_rule_selection_mode"], "fallback_all")
        self.assertIn("_rule_selection_warning", report.llm_response)
        self.assertIsNotNone(report.closure_result)
        if report.closure_result:
            rule_ids_in_obligations = {
                o.source_rule_id for o in report.closure_result.obligations
            }
            self.assertIn("RC-CRACK-WIDTH", rule_ids_in_obligations)

    @patch("research_kg.baseline_runner._call_llm")
    def test_empty_selected_ids_fallback(self, mock_call: unittest.mock.MagicMock) -> None:
        """When LLM returns empty selected_rule_ids, all rules used as fallback."""
        mock_call.return_value = json.dumps({
            "extracted_facts": {"crack_width_mm": 0.3},
            "selected_rule_ids": [],
            "reasoning": "没选具体规则",
        })
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.3mm裂缝")

        self.assertEqual(report.llm_response["_rule_selection_mode"], "fallback_all")

    @patch("research_kg.baseline_runner._call_llm")
    def test_llm_error_not_reported_as_success(self, mock_call: unittest.mock.MagicMock) -> None:
        mock_call.side_effect = TimeoutError("LLM timed out")
        config = LocalLLMConfig(
            base_url="http://127.0.0.1:8080/v1",
            api_key="fake-key",
            model="fake-model",
        )
        runner = DualSourceBaselineRunner(kg=self.kg, config=config)
        report = runner.run("外墙有0.3mm裂缝")

        self.assertTrue(report.llm_response["llm_error"])
        self.assertEqual(report.chain_status["crack_chain"], "llm_error")
        self.assertIsNone(report.closure_result)


if __name__ == "__main__":
    unittest.main()
