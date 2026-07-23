from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

from pydantic import BaseModel, Field, model_validator


class FactPredicates(BaseModel):
    required_feature_ids: List[str] = Field(default_factory=list)
    required_pattern_ids: List[str] = Field(default_factory=list)
    negative_feature_ids: List[str] = Field(default_factory=list)


class TriggerSlotSeedBridge(BaseModel):
    feature_ids: List[str] = Field(default_factory=list)
    pattern_ids: List[str] = Field(default_factory=list)


class SeedTriggerSpec(BaseModel):
    trigger_id: str
    name: str
    target_rule_ids: List[str] = Field(default_factory=list)
    fact_predicates: FactPredicates
    slot_seed_bridge: Dict[str, TriggerSlotSeedBridge] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_trigger_id(self) -> "SeedTriggerSpec":
        if not re.fullmatch(r"TR-\d{3}", self.trigger_id):
            raise ValueError(f"Invalid trigger_id: {self.trigger_id}")
        return self


def load_seed_trigger_specs(path: Path) -> List[SeedTriggerSpec]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError("seed_trigger_specs_v1 catalog must be a JSON array")
    return [SeedTriggerSpec.model_validate(item) for item in payload]


def evaluate_trigger_specs(
    *,
    trigger_specs: List[SeedTriggerSpec],
    matched_feature_ids: List[str],
    matched_pattern_ids: List[str],
) -> List[Dict[str, Any]]:
    matched_feature_set = set(matched_feature_ids)
    matched_pattern_set = set(matched_pattern_ids)
    evaluations: List[Dict[str, Any]] = []

    for spec in sorted(trigger_specs, key=lambda item: item.trigger_id):
        missing_required_feature_ids = [
            feature_id
            for feature_id in spec.fact_predicates.required_feature_ids
            if feature_id not in matched_feature_set
        ]
        missing_required_pattern_ids = [
            pattern_id
            for pattern_id in spec.fact_predicates.required_pattern_ids
            if pattern_id not in matched_pattern_set
        ]
        blocked_negative_feature_ids = [
            feature_id
            for feature_id in spec.fact_predicates.negative_feature_ids
            if feature_id in matched_feature_set
        ]
        matched = (
            not missing_required_feature_ids
            and not missing_required_pattern_ids
            and not blocked_negative_feature_ids
        )
        evaluations.append(
            {
                "trigger_id": spec.trigger_id,
                "name": spec.name,
                "matched": matched,
                "target_rule_ids": list(spec.target_rule_ids),
                "missing_required_feature_ids": missing_required_feature_ids,
                "missing_required_pattern_ids": missing_required_pattern_ids,
                "blocked_negative_feature_ids": blocked_negative_feature_ids,
            }
        )
    return evaluations


def build_rule_seed_bridge(
    *,
    trigger_specs: List[SeedTriggerSpec],
    trigger_evaluations: List[Mapping[str, Any]],
) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    matched_trigger_ids = {
        str(item["trigger_id"])
        for item in trigger_evaluations
        if bool(item.get("matched"))
    }
    rule_bridge: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    for spec in trigger_specs:
        if spec.trigger_id not in matched_trigger_ids:
            continue
        for rule_id in spec.target_rule_ids:
            slot_map = rule_bridge.setdefault(rule_id, {})
            for slot_name, bridge in spec.slot_seed_bridge.items():
                existing = slot_map.setdefault(
                    slot_name,
                    {"feature_ids": [], "pattern_ids": [], "trigger_ids": []},
                )
                existing["feature_ids"] = sorted(set(existing["feature_ids"] + list(bridge.feature_ids)))
                existing["pattern_ids"] = sorted(set(existing["pattern_ids"] + list(bridge.pattern_ids)))
                existing["trigger_ids"] = sorted(set(existing["trigger_ids"] + [spec.trigger_id]))
    return rule_bridge
