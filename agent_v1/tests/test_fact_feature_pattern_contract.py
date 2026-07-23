import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import FactItem, FactPack  # noqa: E402
from workflow_engine.fact_feature_pattern_matcher import match_fact_pack  # noqa: E402
from workflow_engine.fact_feature_pattern_schema import (  # noqa: E402
    load_fact_feature_pattern_catalog,
)


class FactFeaturePatternContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.features, self.patterns = load_fact_feature_pattern_catalog(
            feature_catalog_path=PROJECT_ROOT / "experiments" / "fact_features_v1.json",
            pattern_catalog_path=PROJECT_ROOT / "experiments" / "fact_patterns_v1.json",
        )

    def test_catalog_loads_frozen_9_plus_3(self) -> None:
        self.assertEqual(len(self.features), 9)
        self.assertEqual(len(self.patterns), 3)
        self.assertIn("FF-006", {item.feature_id for item in self.features})
        self.assertIn("FF-011", {item.feature_id for item in self.features})
        self.assertIn("FP-001", {item.pattern_id for item in self.patterns})
        self.assertIn("FP-002", {item.pattern_id for item in self.patterns})
        self.assertIn("FP-004", {item.pattern_id for item in self.patterns})

    def test_fp_001_can_be_stably_matched(self) -> None:
        fact_pack = FactPack(
            case_id="case_fp001",
            generated_at="2026-03-12T00:00:00Z",
            facts=[
                FactItem(
                    fact_id="f1",
                    key="crack_width_mm",
                    value=0.2,
                    source_type="observer",
                    confidence=1.0,
                ),
                FactItem(
                    fact_id="f2",
                    key="has_crack",
                    value=True,
                    source_type="observer",
                    confidence=1.0,
                ),
            ],
        )
        matched = match_fact_pack(
            fact_pack=fact_pack,
            features=self.features,
            patterns=self.patterns,
        )
        self.assertIn("FP-001", {item["pattern_id"] for item in matched["matched_patterns"]})

    def test_fp_002_stub_does_not_raise_when_missing_data(self) -> None:
        fact_pack = FactPack(case_id="case_stub", generated_at="2026-03-12T00:00:00Z", facts=[])
        matched = match_fact_pack(
            fact_pack=fact_pack,
            features=self.features,
            patterns=self.patterns,
        )
        self.assertNotIn("FP-002", {item["pattern_id"] for item in matched["matched_patterns"]})


if __name__ == "__main__":
    unittest.main()
