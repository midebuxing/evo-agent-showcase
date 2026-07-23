from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, model_validator

CoverageState = Literal["grounded", "partial", "stub"]
FeatureType = Literal[
    "MeasurementFeature",
    "DefectFeature",
    "ComponentFeature",
    "ContextFeature",
    "ConditionFeature",
]


class FactFeature(BaseModel):
    feature_id: str
    name: str
    feature_type: FeatureType
    coverage_state: CoverageState
    description: str
    source_fact_keys: List[str] = Field(default_factory=list)
    derive_rule: str = ""

    @model_validator(mode="after")
    def validate_feature_id(self) -> "FactFeature":
        if not re.fullmatch(r"FF-\d{3}", self.feature_id):
            raise ValueError(f"Invalid feature_id: {self.feature_id}")
        if self.coverage_state == "grounded" and not self.source_fact_keys and not self.derive_rule:
            raise ValueError("grounded FactFeature must provide source_fact_keys or derive_rule")
        return self


class FactPattern(BaseModel):
    pattern_id: str
    name: str
    coverage_state: CoverageState
    required_features: List[str]
    optional_features: List[str] = Field(default_factory=list)
    negative_features: List[str] = Field(default_factory=list)
    required_feature_values: Dict[str, Any] = Field(default_factory=dict)
    routing_implication: str
    notes: str = ""

    @model_validator(mode="after")
    def validate_pattern_id(self) -> "FactPattern":
        if not re.fullmatch(r"FP-\d{3}", self.pattern_id):
            raise ValueError(f"Invalid pattern_id: {self.pattern_id}")
        if not self.required_features:
            raise ValueError("FactPattern.required_features cannot be empty")
        return self


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_fact_features(path: Path) -> List[FactFeature]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError("fact_features_v1 catalog must be a JSON array")
    return [FactFeature.model_validate(item) for item in payload]


def load_fact_patterns(path: Path) -> List[FactPattern]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError("fact_patterns_v1 catalog must be a JSON array")
    return [FactPattern.model_validate(item) for item in payload]


def validate_catalog_contract(
    *,
    features: Sequence[FactFeature],
    patterns: Sequence[FactPattern],
) -> None:
    feature_ids = [item.feature_id for item in features]
    pattern_ids = [item.pattern_id for item in patterns]
    if len(feature_ids) != len(set(feature_ids)):
        raise ValueError("Duplicate feature_id in FactFeature catalog")
    if len(pattern_ids) != len(set(pattern_ids)):
        raise ValueError("Duplicate pattern_id in FactPattern catalog")

    feature_id_set = set(feature_ids)
    for pattern in patterns:
        referenced = (
            list(pattern.required_features)
            + list(pattern.optional_features)
            + list(pattern.negative_features)
            + list(pattern.required_feature_values.keys())
        )
        for feature_id in referenced:
            if feature_id not in feature_id_set:
                raise ValueError(
                    f"Pattern {pattern.pattern_id} references unknown feature_id: {feature_id}"
                )


def load_fact_feature_pattern_catalog(
    *,
    feature_catalog_path: Path,
    pattern_catalog_path: Path,
) -> tuple[List[FactFeature], List[FactPattern]]:
    features = load_fact_features(feature_catalog_path)
    patterns = load_fact_patterns(pattern_catalog_path)
    validate_catalog_contract(features=features, patterns=patterns)
    return features, patterns

