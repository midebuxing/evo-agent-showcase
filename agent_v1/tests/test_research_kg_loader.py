"""Tests for DualSourceResearchKG loader."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
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

# 语料构建器写的子树（`rulecard_v2` 不在其射程内，排除以免被别的测试的
# 变异—还原夹具干扰本文件的「真实树未被写」断言）。
_CORPUS_SUBTREES = ("extracted", "markdown", "corpus", "manifests", "failed", "raw")


def _real_corpus_fingerprint() -> dict[str, tuple[int, int]]:
    """真实法规语料树逐文件 (mtime_ns, size) 快照——用来断言本测试没有写它。"""
    snapshot: dict[str, tuple[int, int]] = {}
    for sub in _CORPUS_SUBTREES:
        root = _REPO / "regulations" / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                stat = path.stat()
                snapshot[path.relative_to(_REPO).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


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

    _tmp: tempfile.TemporaryDirectory
    _tmp_root: Path
    _corpus_before: dict[str, tuple[int, int]]

    @classmethod
    def setUpClass(cls) -> None:
        """🔴 测试卫生（2026-08-06，门 A 新码批双线终审两线同挖出的第三写入源）。

        改前：`setUp` 每轮无条件 `build_regulation_corpus(_REPO)`，而 `_REPO` 就是
        **真实 `agent_v1/`** ⇒ 原地重建 `agent_v1/regulations/` 下 **29 个已跟踪文件**
        （四份守则的 extracted 12 ／ markdown 4 ／ corpus 8 ／ manifests 4 ／ failed 1，
        实测：干净临时树上跑一遍构建器，产出 29 个非 raw 文件、29/29 均为已跟踪路径，
        `审核结果_c批新码_20260806.md` §四.3）；本类 7 个测试方法
        ⇒ **每跑一次全量 pytest 就真·覆盖写 7 遍**。

        为什么必须改：它**不是**变异—还原夹具——**没有 tearDown、没有备份、没有还原断言**。
        字节之所以一直没变，纯粹因为这条流水线在输入不变时是幂等的。上游任何输入漂移
        （原始 PDF、`data/*.md`）或流水线引入任何不确定性，一次全量 pytest 就会在无人
        察觉下**永久改写权威法规源文件**，而它们全部落在 `run_baseline_batch.CODE_STATE_SCOPE`
        （`agent_v1/regulations/`）内 —— 与 A3 封存值直接冲突：封存与全量测试若重叠，
        漂移就被封进锚里。

        改后：构建输出落**临时目录**，真实法规树全程只读；并由
        `test_corpus_build_does_not_write_the_real_regulations_tree` 把这条钉成回归闸。
        """
        cls._corpus_before = _real_corpus_fingerprint()
        cls._tmp = tempfile.TemporaryDirectory(
            prefix="research_kg_corpus_", ignore_cleanup_errors=True
        )
        cls._tmp_root = Path(cls._tmp.name)
        # 构建器只读两处输入——`<root>/regulations/raw/`（canonical 源）与
        # `<root>/data/*.md`（`preferred_markdown_candidates`）；其余全由它自己生成。
        raw_dst = cls._tmp_root / "regulations" / "raw"
        raw_dst.mkdir(parents=True, exist_ok=True)
        for item in (_REPO / "regulations" / "raw").iterdir():
            if item.is_file():
                shutil.copy2(item, raw_dst / item.name)
        data_dst = cls._tmp_root / "data"
        data_dst.mkdir(parents=True, exist_ok=True)
        for item in (_REPO / "data").glob("*.md"):
            shutil.copy2(item, data_dst / item.name)
        build_regulation_corpus(cls._tmp_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.kg = load_dual_source_kg(RESEARCH_KG_DIR)

    def test_corpus_build_does_not_write_the_real_regulations_tree(self) -> None:
        """回归闸：语料构建器不许再原地重建真实 `agent_v1/regulations/`。

        判据是逐文件 `(mtime_ns, size)` ——**只比内容不够**：这条流水线幂等，
        写回同样的字节内容级口径一个都抓不到（这正是它潜伏至今的原因）。
        """
        after = _real_corpus_fingerprint()
        touched = sorted(
            rel for rel, sig in after.items() if self._corpus_before.get(rel) != sig
        )
        self.assertEqual(
            touched,
            [],
            "真实法规语料树在本测试类运行期间被写过——构建器必须指向临时目录，"
            f"被碰文件：{touched[:10]}（共 {len(touched)} 个）",
        )
        self.assertEqual(
            sorted(self._corpus_before), sorted(after), "真实法规语料树的文件集合被增删"
        )
        # 反面：构建产物确实落在临时目录里（否则「没写真实树」只是因为压根没建）
        built_manifest = self._tmp_root / "regulations" / "manifests" / "ingest_manifest.json"
        self.assertTrue(
            built_manifest.is_file(), f"构建产物未落临时目录：{built_manifest}"
        )

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
