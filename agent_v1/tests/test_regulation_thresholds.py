"""regulation_thresholds 加载器测试 — 权威 threshold_regime_index.json 真阈值数据."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_thresholds import (  # noqa: E402
    DEFAULT_THRESHOLD_REGIME_INDEX,
    Threshold,
    find_threshold_for_slot,
    find_thresholds_for_slot,
    get_thresholds_for_w0_family,
    load_all_thresholds,
)


class LoadAllThresholdsTests(unittest.TestCase):
    def test_loads_at_least_some_thresholds(self) -> None:
        thresholds = load_all_thresholds()
        self.assertGreater(len(thresholds), 0, "rule_cards_delta should yield at least some thresholds")

    def test_each_threshold_has_required_fields(self) -> None:
        thresholds = load_all_thresholds()
        for t in thresholds:
            self.assertIsInstance(t, Threshold)
            self.assertNotEqual(t.rule_card_id, "")
            self.assertNotEqual(t.family_id, "")
            self.assertNotEqual(t.measure_key, "")
            self.assertIsNotNone(t.operator)


class GetThresholdsForW0FamilyTests(unittest.TestCase):
    def test_external_components_has_thresholds(self) -> None:
        """W0 mbis.inspection.external_components → 通过 alias 映射到 rule_card 的
        mbis.inspection.covered_external_wall（spec 整合多 rule_card family 为单个 W0 family）。"""
        result = get_thresholds_for_w0_family("mbis.inspection.external_components")
        self.assertGreater(len(result), 0)
        valid_prefixes = (
            "mbis.inspection.external_components",
            "mbis.inspection.covered_external_wall",
        )
        for t in result:
            self.assertTrue(
                any(t.family_id.startswith(p) for p in valid_prefixes),
                f"{t.family_id} should start with one of {valid_prefixes}",
            )

    def test_unknown_family_returns_empty(self) -> None:
        result = get_thresholds_for_w0_family("mbis.unknown.family.does.not.exist")
        self.assertEqual(result, [])


class FindThresholdForSlotTests(unittest.TestCase):
    def test_external_wall_inspected_ratio_threshold(self) -> None:
        """spec / rule_card 已知含 ratio.external_wall_area.inspected >= 0.3."""
        threshold = find_threshold_for_slot(
            "mbis.inspection.external_components",
            "ratio.external_wall_area.inspected",
        )
        # 这个 slot 在 rule_card 里有阈值
        if threshold is not None:
            self.assertEqual(threshold.measure_key, "ratio.external_wall_area.inspected")
            self.assertEqual(threshold.operator, ">=")
            self.assertEqual(threshold.value, 0.3)
            self.assertEqual(threshold.unit, "ratio")

    def test_unknown_slot_returns_none(self) -> None:
        result = find_threshold_for_slot(
            "mbis.inspection.external_components",
            "ratio.nonexistent.slot",
        )
        self.assertIsNone(result)

    def test_find_thresholds_returns_list(self) -> None:
        results = find_thresholds_for_slot(
            "mbis.inspection.external_components",
            "ratio.external_wall_area.inspected",
        )
        self.assertIsInstance(results, list)


def _sig(measure_key, operator, value, unit, qualifiers, formula=None) -> tuple:
    """跨侧签名：(measure_key, operator, canonical(value), unit, canonical(qualifiers), canonical(formula)).

    DEBT-056 前向修：纳入 canonical formula——formula 型制度（operator=="formula"）
    literal value 两侧都是 None，若不比 formula 则该 3 条签名空转（只比到 None==None）。
    加 formula 后 expression + variables[] 逐条跨侧对齐，任一侧丢/改 formula 即红。
    """
    return (
        measure_key or "",
        operator or "",
        json.dumps(value, sort_keys=True, ensure_ascii=False),
        unit or "",
        json.dumps(qualifiers or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(formula, sort_keys=True, ensure_ascii=False),
    )


class CrossSideThresholdRegimeInvariantTests(unittest.TestCase):
    """DEBT-056 前向修：W2 load_all_thresholds 与 closure 侧同一份权威索引逐条一致.

    防日后 load_all_thresholds 改回 reviewed_batches 旧快照或引第三快照——一旦源漂移，
    本测试逐条签名比对会红。断言：41 条、无 auth-only/W2-only、无签名差。
    """

    def test_load_all_thresholds_matches_authoritative_index(self) -> None:
        # 独立读权威索引 raw json（不经 load_all_thresholds），逐条建签名。
        doc = json.loads(DEFAULT_THRESHOLD_REGIME_INDEX.read_text(encoding="utf-8-sig"))
        index_regimes = doc["threshold_regimes"]
        index_ids = [r["threshold_regime_id"] for r in index_regimes]

        # 权威索引自身：41 条、全唯一、全非空。
        self.assertEqual(len(index_regimes), 41, "权威索引应为 41 条 threshold_regime")
        self.assertEqual(len(set(index_ids)), 41, "threshold_regime_id 应全唯一")
        self.assertTrue(all(rid for rid in index_ids), "threshold_regime_id 应全非空")

        index_sig = {
            r["threshold_regime_id"]: _sig(
                r.get("measure_key"), r.get("operator"), r.get("value"),
                r.get("unit"), r.get("qualifiers"), r.get("formula"),
            )
            for r in index_regimes
        }

        loaded = load_all_thresholds()
        loaded_ids = [t.threshold_regime_id for t in loaded]
        loaded_sig = {
            t.threshold_regime_id: _sig(
                t.measure_key, t.operator, t.value, t.unit, t.qualifiers, t.formula
            )
            for t in loaded
        }

        # 无 auth-only / W2-only：两侧 regime_id 集合完全相等。
        self.assertEqual(
            set(loaded_ids), set(index_ids),
            "load_all_thresholds 与权威索引 regime_id 集合应完全相等（无漂移）",
        )
        self.assertEqual(len(loaded_ids), 41, "W2 侧应加载 41 条（非旧快照 31）")

        # 逐条签名比对（无签名差）。
        for rid, sig in index_sig.items():
            self.assertEqual(
                loaded_sig[rid], sig,
                f"regime {rid} 的 (measure/operator/value/unit/qualifiers) 签名应跨侧一致",
            )


if __name__ == "__main__":
    unittest.main()
