"""别名表覆盖闸（DEBT-095 丙案）的结构闸。

这些测试守的不是「某个数是多少」（那是池相关的，会随换池漂），
而是**闸本身不许被悄悄削弱**的四条结构性质：

1. 射程内的每个维度必须声明它喂哪个已知宇宙 —— 否则这行的"补它=打开早退"
   前提就不成立，闸在筛一个与机制无关的人群；
2. 每条豁免必须带裁定出处 —— 无出处的豁免＝把闸关掉；
3. 零覆盖判据真的能判红（用合成池验，不依赖任何真实池的具体数字）；
4. 射程外维度必须显式登记理由 —— 免得下一个人当成"漏了一个维度"补回去。

⚠️ 第 3 条用**合成池**（临时 parquet），因为真实池里当前恰好没有未豁免的零覆盖行
（401 池实测 0 条）——「测试跑在缺陷不可能显现的输入上」是本仓反复踩过的坑。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "agent_v1" / "scripts" / "audit_alias_value_pool_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("_alias_cov_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


GATE = _load()


class TestGateStructure(unittest.TestCase):
    def test_every_in_scope_dimension_declares_its_known_universe(self) -> None:
        """射程内维度必须写明喂哪个已知宇宙——这是"补行=打开早退"的前提。"""
        for dim, spec in GATE.DIMENSION_SOURCES.items():
            self.assertTrue(spec.get("known_universe"),
                            f"{dim} 未声明 known_universe：闸在筛一个与机制无关的人群")
            self.assertTrue(spec.get("caliber"), f"{dim} 未声明口径")
            self.assertTrue(spec.get("table") and spec.get("column"),
                            f"{dim} 未声明世界侧取值来源")

    def test_every_exemption_carries_an_adjudication_source(self) -> None:
        """无出处的豁免＝把闸关掉，不许加。"""
        self.assertTrue(GATE.EXEMPTIONS, "豁免表为空：应至少含 DEBT-095 乙案那条")
        for key, reason in GATE.EXEMPTIONS.items():
            self.assertIsInstance(key, tuple)
            self.assertEqual(len(key), 2, "豁免键必须是 (维度, W0值)")
            self.assertIn(key[0], GATE.DIMENSION_SOURCES,
                          f"豁免了一个射程外维度：{key[0]}")
            self.assertTrue(reason and len(reason) > 30,
                            f"{key} 的豁免理由过短，看不出裁定出处")
            self.assertRegex(reason, r"DEBT-\d+|决议|裁定|核验结果|实施记录",
                             f"{key} 的豁免理由未指向任何裁定出处")

    def test_private_premises_is_the_exempted_row(self) -> None:
        """DEBT-095 乙案那条必须在册——它是本闸的立案由头。"""
        self.assertIn(("location_class_key", "private_premises"), GATE.EXEMPTIONS)

    def test_out_of_scope_dimensions_are_registered_with_a_reason(self) -> None:
        """射程外维度必须显式登记，且不许与射程内重叠。"""
        self.assertTrue(GATE.OUT_OF_SCOPE_DIMENSIONS)
        for dim, why in GATE.OUT_OF_SCOPE_DIMENSIONS.items():
            self.assertNotIn(dim, GATE.DIMENSION_SOURCES)
            self.assertTrue(why and len(why) > 20, f"{dim} 未说明为什么在射程外")

    def test_alias_table_dimensions_are_all_accounted_for(self) -> None:
        """别名表里的每个真实维度键，要么在射程内、要么在射程外登记——不许静默漏。"""
        aliases = GATE.load_alias_table()
        for dim in aliases:
            if dim.startswith("_"):
                continue
            self.assertTrue(
                dim in GATE.DIMENSION_SOURCES or dim in GATE.OUT_OF_SCOPE_DIMENSIONS,
                f"别名表维度 {dim} 既不在射程内也未登记为射程外——静默漏掉一个维度")


class TestZeroCoverageDetection(unittest.TestCase):
    """用合成池验判红能力——真实 401 池当前 0 条未豁免零覆盖，测不出这条。"""

    def _synth_pool(self, tmp: pathlib.Path, locations, components) -> pathlib.Path:
        import pandas as pd
        root = tmp / "WorldgenWorldBundles.v2.parquet"
        root.mkdir(parents=True)
        pd.DataFrame({"location_class": locations}).to_parquet(
            root / "locations.parquet")
        pd.DataFrame({"component_type": components}).to_parquet(
            root / "components.parquet")
        return tmp

    def test_zero_coverage_row_is_flagged_red(self) -> None:
        aliases = GATE.load_alias_table()
        lcs = sorted(aliases["location_class_key"])
        cts = sorted(aliases["component_type_key"])
        # 合成池：只产第一个 location 类与第一个组件类，其余全部零覆盖
        with tempfile.TemporaryDirectory() as d:
            pool = self._synth_pool(pathlib.Path(d), [lcs[0]] * 3, [cts[0]] * 3)
            report = GATE.audit(pool, [])
        self.assertGreater(report["unexempted_zero_coverage_count"], 0,
                           "合成池里几乎全是零覆盖，闸却一条都没判红")
        exempt_keys = set(GATE.EXEMPTIONS)
        for row in report["rows"]:
            if row["kind"] != "在表行":
                continue
            key = (row["dimension"], row["w0_value"])
            covered = row["w0_value"] in (lcs[0], cts[0])
            self.assertEqual(row["zero_coverage"], not covered,
                             f"{key} 的零覆盖判定与合成池不符")
            if row["zero_coverage"] and key not in exempt_keys:
                self.assertFalse(row["exempted"])

    def test_fully_covered_pool_is_green(self) -> None:
        """反向对照：每个 W0 键都在池里 ⇒ 未豁免零覆盖必须为 0。"""
        aliases = GATE.load_alias_table()
        lcs = sorted(aliases["location_class_key"])
        cts = sorted(aliases["component_type_key"])
        with tempfile.TemporaryDirectory() as d:
            pool = self._synth_pool(pathlib.Path(d), lcs, cts)
            report = GATE.audit(pool, [])
        self.assertEqual(report["unexempted_zero_coverage_count"], 0)
        self.assertEqual(report["zero_coverage_count"], 0)

    def test_candidate_row_reports_without_turning_red(self) -> None:
        """候选行（尚未入表）只报现状，不参与判红——补行前的问答口径。"""
        with tempfile.TemporaryDirectory() as d:
            aliases = GATE.load_alias_table()
            pool = self._synth_pool(pathlib.Path(d),
                                    ["transfer_floor"] * 7,
                                    sorted(aliases["component_type_key"]))
            report = GATE.audit(pool, [("location_class_key", "transfer_floor")])
        cand = [r for r in report["rows"] if r["kind"].startswith("候选")]
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["pool_fact_count"], 7)
        self.assertTrue(cand[0]["exempted"], "候选行不该参与判红")
        self.assertNotIn("transfer_floor", aliases["location_class_key"],
                         "transfer_floor 若已入表，本用例的『尚未入表』前提失效")


if __name__ == "__main__":
    sys.exit(unittest.main())
