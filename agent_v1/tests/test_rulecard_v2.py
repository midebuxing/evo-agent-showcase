import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.rulecard_v2 import (  # noqa: E402
    load_rulecard_bundle,
    rebuild_derived_indexes,
    validate_rulecard_bundle,
)


BUNDLE_DIR = PROJECT_ROOT / "regulations" / "rulecard_v2" / "mbis_cop_2023"


class RuleCardV2BundleTests(unittest.TestCase):
    def test_coverage_assets_are_declared_and_parseable(self) -> None:
        manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        for key in (
            "coverage_baseline",
            "family_coverage_baseline",
            "coverage_gap_audit",
        ):
            self.assertIn(key, files)
            parsed = json.loads((BUNDLE_DIR / files[key]).read_text(encoding="utf-8"))
            self.assertIn("schema_version", parsed)

    def test_load_summary_counts(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        summary = bundle.summary()
        self.assertEqual(summary["bundle_id"], "rulecard_v2.mbis_cop_2023")
        self.assertEqual(summary["family_count"], 43)
        self.assertEqual(summary["rule_card_count"], 397)
        self.assertEqual(summary["semantic_slot_registry_count"], 49)
        self.assertEqual(summary["measure_registry_count"], 28)
        self.assertEqual(summary["artifact_registry_count"], 25)
        self.assertEqual(summary["time_anchor_registry_count"], 19)
        self.assertEqual(summary["slot_count"], 165)
        self.assertEqual(summary["threshold_regime_count"], 41)
        self.assertEqual(summary["definition_count"], 1)
        self.assertEqual(summary["exception_count"], 0)

    def test_validate_bundle_passes(self) -> None:
        bundle = validate_rulecard_bundle(BUNDLE_DIR)
        self.assertEqual(bundle.manifest["schema_version"], "2.1.0")

    def test_rebuilt_indexes_match_stored_indexes(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        derived = rebuild_derived_indexes(bundle.cards)
        self.assertEqual(bundle.slot_index, derived["slot_index"])
        self.assertEqual(bundle.threshold_regime_index, derived["threshold_regime_index"])
        self.assertEqual(
            bundle.exception_definition_index,
            derived["exception_definition_index"],
        )

    def test_gate_card_uses_prerequisite_not_exception(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        gate_card = next(
            card
            for card in bundle.cards
            if card["rule_card_id"]
            == "rc.mbis.investigation.detailed_investigation.ri.gate.s4_2_3.c01"
        )
        gate_roles = {
            item["slot_id"]: set(item["roles"]) for item in gate_card["slot_role_map"]
        }
        self.assertIn(
            "prerequisite",
            gate_roles["procedure.investigation.proposal.recognized"],
        )
        self.assertEqual(gate_card["exceptions"], [])

    def test_cards_use_canonical_normalized_slot_and_measure_names(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        forbidden_slot_roots = ("admin.", "measurement.", "work.", "state.")
        for card in bundle.cards:
            for mapping in card["slot_role_map"]:
                self.assertFalse(mapping["slot_id"].startswith(forbidden_slot_roots))
                self.assertFalse(mapping["slot_id"].endswith(("_at", "_ts")))
            for threshold in card["threshold_regimes"]:
                self.assertNotIn("measure", threshold)
                self.assertIn("measure_key", threshold)


if __name__ == "__main__":
    unittest.main()
