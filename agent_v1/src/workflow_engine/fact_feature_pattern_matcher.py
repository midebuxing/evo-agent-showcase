from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import FactPack  # noqa: E402
from workflow_engine.fact_feature_pattern_schema import (  # noqa: E402
    FactFeature,
    FactPattern,
    load_fact_feature_pattern_catalog,
)

DEFAULT_FEATURE_CATALOG = PROJECT_ROOT / "experiments" / "fact_features_v1.json"
DEFAULT_PATTERN_CATALOG = PROJECT_ROOT / "experiments" / "fact_patterns_v1.json"


def _build_fact_index(fact_pack: FactPack) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    for fact in sorted(fact_pack.facts, key=lambda item: item.fact_id):
        if fact.key not in index:
            index[fact.key] = fact.value
    return index


def _derive_feature_value(*, feature: FactFeature, fact_index: Mapping[str, Any]) -> Any:
    for key in feature.source_fact_keys:
        if key in fact_index:
            return fact_index[key]

    if feature.name == "has_water_seepage" and "has_water_leak" in fact_index:
        return bool(fact_index["has_water_leak"])

    structural_markers = {
        "crack_width_mm",
        "spalling_area_m2",
        "has_rebar_exposed",
        "has_water_leak",
        "has_hollowing",
        "has_water_seepage",
    }
    if feature.name == "component_type":
        if any(key in fact_index for key in structural_markers):
            return "structural"
    if feature.name == "location_zone":
        if any(key in fact_index for key in structural_markers):
            return "structural_member"
    return None


def match_fact_pack(
    *,
    fact_pack: FactPack,
    features: List[FactFeature],
    patterns: List[FactPattern],
) -> Dict[str, Any]:
    fact_index = _build_fact_index(fact_pack)

    matched_features: Dict[str, Dict[str, Any]] = {}
    for feature in sorted(features, key=lambda item: item.feature_id):
        value = _derive_feature_value(feature=feature, fact_index=fact_index)
        if value is None:
            continue
        matched_features[feature.feature_id] = {
            "feature_id": feature.feature_id,
            "name": feature.name,
            "value": value,
            "coverage_state": feature.coverage_state,
        }

    matched_patterns: List[Dict[str, Any]] = []
    pattern_diagnostics: List[Dict[str, Any]] = []
    for pattern in sorted(patterns, key=lambda item: item.pattern_id):
        missing_required = [item for item in pattern.required_features if item not in matched_features]
        mismatched_required_values: List[str] = []
        for feature_id, expected in pattern.required_feature_values.items():
            if feature_id not in matched_features:
                continue
            if matched_features[feature_id]["value"] != expected:
                mismatched_required_values.append(feature_id)

        blocked_by_negative = []
        for feature_id in pattern.negative_features:
            if feature_id in matched_features and bool(matched_features[feature_id]["value"]):
                blocked_by_negative.append(feature_id)

        is_match = (
            not missing_required
            and not mismatched_required_values
            and not blocked_by_negative
        )
        diagnostic = {
            "pattern_id": pattern.pattern_id,
            "name": pattern.name,
            "matched": is_match,
            "coverage_state": pattern.coverage_state,
            "missing_required": missing_required,
            "mismatched_required_values": mismatched_required_values,
            "blocked_by_negative": blocked_by_negative,
        }
        pattern_diagnostics.append(diagnostic)
        if is_match:
            matched_patterns.append(
                {
                    "pattern_id": pattern.pattern_id,
                    "name": pattern.name,
                    "coverage_state": pattern.coverage_state,
                    "routing_implication": pattern.routing_implication,
                }
            )

    return {
        "case_id": fact_pack.case_id,
        "matched_features": sorted(matched_features.values(), key=lambda item: item["feature_id"]),
        "matched_patterns": matched_patterns,
        "pattern_diagnostics": pattern_diagnostics,
    }


def _load_fact_pack(path: Path) -> FactPack:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return FactPack.model_validate(payload)


def _run_for_fact_pack_paths(
    *,
    fact_pack_paths: List[Path],
    features: List[FactFeature],
    patterns: List[FactPattern],
) -> Dict[str, Any]:
    per_case: List[Dict[str, Any]] = []
    pattern_hit_counts: Dict[str, int] = {}
    for path in fact_pack_paths:
        matched = match_fact_pack(
            fact_pack=_load_fact_pack(path),
            features=features,
            patterns=patterns,
        )
        per_case.append(
            {
                "case_id": matched["case_id"],
                "fact_pack_path": str(path),
                "matched_feature_ids": [item["feature_id"] for item in matched["matched_features"]],
                "matched_pattern_ids": [item["pattern_id"] for item in matched["matched_patterns"]],
                "pattern_diagnostics": matched["pattern_diagnostics"],
            }
        )
        for pattern in matched["matched_patterns"]:
            pattern_id = pattern["pattern_id"]
            pattern_hit_counts[pattern_id] = pattern_hit_counts.get(pattern_id, 0) + 1
    return {
        "total_fact_packs": len(per_case),
        "pattern_hit_counts": pattern_hit_counts,
        "cases": per_case,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal matcher for FactFeature/FactPattern v1.")
    parser.add_argument("--fact-pack", default="", help="Path to one fact_pack.json")
    parser.add_argument("--run-dir", default="", help="Path to experiments/runs/<run_id>")
    parser.add_argument("--feature-catalog", default=str(DEFAULT_FEATURE_CATALOG))
    parser.add_argument("--pattern-catalog", default=str(DEFAULT_PATTERN_CATALOG))
    parser.add_argument("--output", default="", help="Optional output json path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    feature_catalog_path = Path(args.feature_catalog)
    pattern_catalog_path = Path(args.pattern_catalog)
    features, patterns = load_fact_feature_pattern_catalog(
        feature_catalog_path=feature_catalog_path,
        pattern_catalog_path=pattern_catalog_path,
    )

    fact_pack_paths: List[Path] = []
    if args.fact_pack:
        fact_pack_paths = [Path(args.fact_pack)]
    elif args.run_dir:
        run_dir = Path(args.run_dir)
        fact_pack_paths = sorted(run_dir.glob("cases/*/fact_pack.json"))
    else:
        raise RuntimeError("Either --fact-pack or --run-dir must be provided.")

    result = _run_for_fact_pack_paths(
        fact_pack_paths=fact_pack_paths,
        features=features,
        patterns=patterns,
    )

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
    print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
