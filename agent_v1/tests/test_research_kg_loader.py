"""Tests for DualSourceResearchKG loader."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Ensure src is on the path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from research_kg.loader import (
    DualSourceResearchKG,
    SubgraphSeed,
    load_dual_source_kg,
    load_subgraph,
)
from research_kg.regulation_corpus import RegulationCorpus, build_regulation_corpus

RESEARCH_KG_DIR = _REPO / "research_kg"


class TestSubgraphLoad(unittest.TestCase):
    """Test individual subgraph loading."""

    def test_load_building_fact_kg(self) -> None:
        sg = load_subgraph(RESEARCH_KG_DIR / "building_fact_kg", "BuildingFactKG")
        self.assertEqual(sg.graph_name, "BuildingFactKG")
        self.assertGreater(len(sg.nodes), 0)
        self.assertGreater(len(sg.edges), 0)
        # Must contain expected node types
        for nt in ("Building", "Component", "Defect", "Measurement", "FactFeature", "FactPattern"):
            self.assertIn(nt, sg.node_types, f"Missing node type: {nt}")

    def test_load_rule_skill_kg(self) -> None:
        sg = load_subgraph(RESEARCH_KG_DIR / "rule_skill_kg", "RuleSkillKG")
        self.assertEqual(sg.graph_name, "RuleSkillKG")
        self.assertGreater(len(sg.nodes), 0)
        self.assertGreater(len(sg.edges), 0)
        for nt in ("RuleCard", "FactPattern", "Skill", "Trigger"):
            self.assertIn(nt, sg.node_types, f"Missing node type: {nt}")

    def test_no_duplicate_node_ids(self) -> None:
        for side in ("building_fact_kg", "rule_skill_kg"):
            sg = load_subgraph(RESEARCH_KG_DIR / side, side)
            ids = [n["node_id"] for n in sg.nodes]
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate node_id in {side}")

    def test_no_duplicate_edge_ids(self) -> None:
        for side in ("building_fact_kg", "rule_skill_kg"):
            sg = load_subgraph(RESEARCH_KG_DIR / side, side)
            ids = [e["edge_id"] for e in sg.edges]
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate edge_id in {side}")


class TestDualSourceLoad(unittest.TestCase):
    """Test full dual-source KG loading."""

    def setUp(self) -> None:
        build_regulation_corpus(_REPO)
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_top_level_type(self) -> None:
        self.assertIsInstance(self.kg, DualSourceResearchKG)

    def test_both_sides_loaded(self) -> None:
        self.assertIsInstance(self.kg.building_fact, SubgraphSeed)
        self.assertIsInstance(self.kg.rule_skill, SubgraphSeed)
        self.assertIsInstance(self.kg.regulation_corpus, RegulationCorpus)

    def test_bridge_nodes_exist_on_both_sides(self) -> None:
        bridge = set(self.kg.top_manifest.get("bridge_nodes", []))
        bf_ids = {n["node_id"] for n in self.kg.building_fact.nodes}
        rs_ids = {n["node_id"] for n in self.kg.rule_skill.nodes}
        for bid in bridge:
            self.assertIn(bid, bf_ids, f"Bridge {bid} missing in BuildingFactKG")
            self.assertIn(bid, rs_ids, f"Bridge {bid} missing in RuleSkillKG")

    def test_mainline_crack_chain(self) -> None:
        chains = self.kg.top_manifest["mainline_chains"]
        self.assertIn("crack_chain", chains)
        cc = chains["crack_chain"]
        self.assertEqual(cc["fact_pattern"], "FP-001")
        self.assertEqual(cc["trigger"], "TR-001")
        self.assertIn("RC-CRACK-WIDTH", cc["rule_cards"])

    def test_mainline_rebar_spall_chain(self) -> None:
        chains = self.kg.top_manifest["mainline_chains"]
        self.assertIn("rebar_spall_chain", chains)
        rc = chains["rebar_spall_chain"]
        self.assertEqual(rc["fact_pattern"], "FP-004")
        self.assertEqual(rc["trigger"], "TR-002")
        self.assertIn("RC-REBAR-EXPOSED", rc["rule_cards"])
        self.assertIn("RC-SPALL-AREA", rc["rule_cards"])

    def test_summary_structure(self) -> None:
        s = self.kg.summary()
        self.assertEqual(s["graph_name"], "DualSourceResearchKG")
        self.assertIn("building_fact_kg", s)
        self.assertIn("rule_skill_kg", s)
        self.assertIn("regulation_corpus", s)
        self.assertIn("total_nodes", s)
        self.assertIn("total_edges", s)
        self.assertGreater(s["total_nodes"], 0)
        self.assertGreater(s["total_edges"], 0)

    def test_regulation_corpus_summary(self) -> None:
        corpus = self.kg.regulation_corpus
        assert corpus is not None
        summary = corpus.summary()
        self.assertEqual(summary["corpus_id"], "hk_building_regulations")
        self.assertGreaterEqual(summary["document_count"], 4)
        self.assertEqual(summary["independent_source_count"], 3)
        self.assertEqual(summary["alias_document_count"], 1)
        self.assertIn("MBIS_MWIS_Operation_Note", summary["alias_document_ids"])
        self.assertGreater(summary["chunk_count"], 0)


class TestSummaryOutput(unittest.TestCase):
    """Test that summary is valid JSON-serializable."""

    def test_summary_json_round_trip(self) -> None:
        kg = load_dual_source_kg(RESEARCH_KG_DIR)
        s = kg.summary()
        dumped = json.dumps(s, ensure_ascii=False)
        reloaded = json.loads(dumped)
        self.assertEqual(reloaded["graph_name"], "DualSourceResearchKG")


if __name__ == "__main__":
    unittest.main()
