from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from workflow_engine.regulation_projection_mapping import load_runtime_mapping
from workflow_engine.rulecard_v2 import load_rulecard_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULECARD_BUNDLE_DIR = PROJECT_ROOT / "regulations" / "rulecard_v2" / "mbis_cop_2023"

PROJECTION_CONTRACT_VERSION = "regulation_projection.contract.v1"
PROJECTION_SPEC_VERSION = "regulation_projection.spec.v1"

WORLD_SLOT_PREFIXES = ("building.", "scope.", "defect.", "risk.", "repair.", "maintenance.")
SIDECAR_SLOT_PREFIXES = ("actor.", "artifact.", "duration.", "procedure.", "reporting.", "supervision.")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def _normalized_qualifiers(qualifiers: Dict[str, Any] | None) -> Dict[str, Any]:
    if not qualifiers:
        return {}
    return json.loads(json.dumps(qualifiers, ensure_ascii=False, sort_keys=True))


def _mapping_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _slot_aliases(mapping: Dict[str, Any], slot_id: str) -> List[str]:
    return list(mapping.get("slot_aliases", {}).get(slot_id, []))


def _measure_aliases(mapping: Dict[str, Any], measure_key: str) -> List[str]:
    return list(mapping.get("measure_aliases", {}).get(measure_key, []))


def _method_aliases(mapping: Dict[str, Any], method_key: str) -> List[str]:
    # DEBT-049 Phase3 U2：method 别名 grouped raw {canonical:[alias...]}（canonical=卡端
    # method_key，与 slot/measure 同 _*_aliases 取法一致）。承载到 compiled 契约否则
    # transport 死码（此前 method 全丢）。四方法暗部署为空 alias 列表 → dead-carry 零行为。
    return list(mapping.get("method_aliases", {}).get(method_key, []))


def _slot_target_config(mapping: Dict[str, Any], slot_id: str) -> Dict[str, Any]:
    return dict(mapping.get("slot_targets", {}).get(slot_id, {}))


def _measure_target_config(mapping: Dict[str, Any], measure_key: str) -> Dict[str, Any]:
    return dict(mapping.get("measure_targets", {}).get(measure_key, {}))


def _card_override(mapping: Dict[str, Any], rule_card_id: str) -> Dict[str, Any]:
    return dict(mapping.get("card_overrides", {}).get(rule_card_id, {}))


def _family_projection_filter(mapping: Dict[str, Any], family_id: str) -> List[str]:
    return list(mapping.get("family_projection_filters", {}).get(family_id, []))


def _slot_partition(slot_id: str) -> str:
    if slot_id.startswith("qual."):
        return "qualifier"
    if slot_id in {
        "investigation.fsp.below_required_safety",
        "verification.test.failed",
        "repair.required",
        "repair.outcome.safe_until_next_cycle",
        "maintenance.pre_next_cycle.required",
    }:
        return "world"
    if slot_id in {
        "repair.prescribed.completed",
        "repair.prescribed.started",
        "repair.proposal.revision_required",
        "fire_safety.upgrade_outstanding",
    }:
        return "sidecar"
    if slot_id.startswith(WORLD_SLOT_PREFIXES):
        return "world"
    if slot_id.startswith(SIDECAR_SLOT_PREFIXES) or slot_id.startswith("fire_safety."):
        return "sidecar"
    return "world"


def _measure_partition(measure_key: str) -> str:
    if measure_key.startswith("duration."):
        return "sidecar"
    return "measurement"


def _slot_ref_lookup(card: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {item["slot_ref_id"]: item for item in card.get("slot_role_map", [])}


def _collect_required_sidecar_interfaces(card: Dict[str, Any], mapping: Dict[str, Any]) -> List[str]:
    interfaces: List[str] = []
    slot_ids = {item["slot_id"] for item in card.get("slot_role_map", [])}
    measure_keys = {item["measure_key"] for item in card.get("threshold_regimes", [])}
    artifact_keys = {
        artifact["artifact_key"]
        for artifact in card.get("workflow_operands", {}).get("artifacts", [])
        if artifact.get("artifact_key")
    }
    if any(slot_id.startswith("procedure.") for slot_id in slot_ids) or any(
        key.startswith("duration.") for key in measure_keys
    ):
        interfaces.append("procedure_gate_sidecar")
    if any(slot_id.startswith("supervision.") or slot_id.startswith("actor.") for slot_id in slot_ids):
        interfaces.append("supervision_sidecar")
    if any(slot_id.startswith("reporting.") for slot_id in slot_ids) or any(
        key.startswith(("report.", "form.", "notice.", "proposal.", "record.", "photo.", "drawing.", "certificate.", "statement."))
        for key in artifact_keys
    ):
        interfaces.append("inspection_report_sidecar")
    if any(
        key in {"report.completion", "form.mbi4", "certificate.material_or_product", "statement.extra_works_separated"}
        for key in artifact_keys
    ):
        interfaces.append("completion_report_sidecar")
    for slot_id in slot_ids:
        interfaces.extend(_slot_target_config(mapping, slot_id).get("owning_interfaces", []))
    for measure_key in measure_keys:
        interfaces.extend(_measure_target_config(mapping, measure_key).get("owning_interfaces", []))
    return sorted(set(interfaces))


def _compiled_slot_requirement(card: Dict[str, Any], slot_entry: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
    slot_id = slot_entry["slot_id"]
    target_config = _slot_target_config(mapping, slot_id)
    return {
        "slot_ref_id": slot_entry["slot_ref_id"],
        "slot_id": slot_id,
        "alias_slot_ids": _slot_aliases(mapping, slot_id),
        "partition": _slot_partition(slot_id),
        "qualifiers": _normalized_qualifiers(slot_entry.get("qualifiers")),
        "roles": list(slot_entry.get("roles", [])),
        "required": bool(slot_entry.get("required", False)),
        "lookup_rule": _mapping_copy(target_config["lookup_rule"]) if target_config.get("lookup_rule") else None,
        "owning_interface_ids": list(target_config.get("owning_interfaces", [])),
        "owning_interface_mode": target_config.get("owning_interface_mode", "any_of"),
        "deferred_reason_code": target_config.get("deferred_reason_code"),
        "deferred_note": target_config.get("deferred_note"),
    }


def _compiled_trigger_predicates(card: Dict[str, Any], mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    slot_ref_map = _slot_ref_lookup(card)
    predicates: List[Dict[str, Any]] = []
    for item in card.get("trigger_conditions", {}).get("items", []):
        predicate_kind = item.get("predicate_kind")
        if predicate_kind == "slot":
            slot_entry = slot_ref_map[item["slot_ref_id"]]
            slot_id = slot_entry["slot_id"]
            target_config = _slot_target_config(mapping, slot_id)
            predicates.append(
                {
                    "condition_id": item["condition_id"],
                    "predicate_kind": "slot",
                    "slot_ref_id": item["slot_ref_id"],
                    "slot_id": slot_id,
                    "alias_slot_ids": _slot_aliases(mapping, slot_id),
                    "partition": _slot_partition(slot_id),
                    "operator": item["operator"],
                    "expected_value": item.get("expected_value"),
                    "qualifiers": _normalized_qualifiers(slot_entry.get("qualifiers")),
                    "lookup_rule": _mapping_copy(target_config["lookup_rule"]) if target_config.get("lookup_rule") else None,
                    "owning_interface_ids": list(target_config.get("owning_interfaces", [])),
                    "owning_interface_mode": target_config.get("owning_interface_mode", "any_of"),
                    "deferred_reason_code": target_config.get("deferred_reason_code"),
                    "deferred_note": target_config.get("deferred_note"),
                }
            )
            continue
        measure_key = item.get("measure_key", "")
        target_config = _measure_target_config(mapping, measure_key) if measure_key else {}
        predicates.append(
            {
                "condition_id": item["condition_id"],
                "predicate_kind": predicate_kind,
                "measure_key": item.get("measure_key"),
                "alias_measure_keys": _measure_aliases(mapping, measure_key),
                "partition": _measure_partition(measure_key) if measure_key else "measurement",
                "operator": item.get("operator"),
                "expected_value": item.get("expected_value"),
                "qualifiers": _normalized_qualifiers(item.get("qualifiers")),
                "owning_interface_ids": list(target_config.get("owning_interfaces", [])),
                "owning_interface_mode": target_config.get("owning_interface_mode", "any_of"),
                "deferred_reason_code": target_config.get("deferred_reason_code"),
                "deferred_note": target_config.get("deferred_note"),
            }
        )
    return predicates


def _compiled_thresholds(card: Dict[str, Any], mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    compiled: List[Dict[str, Any]] = []
    for item in card.get("threshold_regimes", []):
        measure_key = item["measure_key"]
        target_config = _measure_target_config(mapping, measure_key)
        compiled.append(
            {
                "threshold_regime_id": item["threshold_regime_id"],
                "measure_key": measure_key,
                "alias_measure_keys": _measure_aliases(mapping, measure_key),
                "partition": _measure_partition(measure_key),
                "operator": item["operator"],
                "value": item.get("value"),
                "formula": item.get("formula"),
                "unit": item.get("unit"),
                "time_anchor_key": item.get("time_anchor_key"),
                "qualifiers": _normalized_qualifiers(item.get("qualifiers")),
                "owning_interface_ids": list(target_config.get("owning_interfaces", [])),
                "owning_interface_mode": target_config.get("owning_interface_mode", "any_of"),
                "deferred_reason_code": target_config.get("deferred_reason_code"),
                "deferred_note": target_config.get("deferred_note"),
            }
        )
    return compiled


def _compiled_card_spec(card: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
    card_override = _card_override(mapping, card["rule_card_id"])
    slot_requirements = [_compiled_slot_requirement(card, item, mapping) for item in card.get("slot_role_map", [])]
    trigger_predicates = _compiled_trigger_predicates(card, mapping)
    trigger_predicates.extend(_mapping_copy(card_override.get("extra_trigger_predicates", [])))
    evidence_requirements: List[Dict[str, Any]] = []
    for stage_name, items in card.get("evidence_requirements", {}).items():
        for item in items:
            evidence_requirements.append(
                {
                    "evidence_requirement_id": item["evidence_requirement_id"],
                    "stage": stage_name,
                    "kind": item["kind"],
                    "required": bool(item.get("required", False)),
                    "description": item.get("description", ""),
                    "artifact_ids": list(item.get("artifact_ids", [])),
                    "slot_ref_ids": list(item.get("slot_ref_ids", [])),
                    "measure_keys": list(item.get("measure_keys", [])),
                    "required_field_groups": list(item.get("required_field_groups", [])),
                }
            )
    return {
        "rule_card_id": card["rule_card_id"],
        "family_id": card["family_id"],
        "normalized_rule_text": card["normalized_rule_text"],
        "source_section_ids": [item["section_id"] for item in card.get("source_section", [])],
        "applicability": {
            "phase": card.get("applicability", {}).get("phase"),
            "subject": card.get("applicability", {}).get("subject"),
            "actors": list(card.get("applicability", {}).get("actors", [])),
            "building_scope": list(card.get("applicability", {}).get("building_scope", [])),
            "component_scope": list(card.get("applicability", {}).get("component_scope", [])),
        },
        "slot_requirements": slot_requirements,
        "trigger_logic": card.get("trigger_conditions", {}).get("logic", "all"),
        "trigger_predicates": trigger_predicates,
        "threshold_checks": _compiled_thresholds(card, mapping),
        "workflow_artifacts": [
            {
                "artifact_id": item["artifact_id"],
                "artifact_type": item["artifact_type"],
                "artifact_key": item["artifact_key"],
            }
            for item in card.get("workflow_operands", {}).get("artifacts", [])
        ],
        "workflow_deadlines": [
            {
                "deadline_id": item["deadline_id"],
                "relation": item["relation"],
                "offset_value": item.get("offset_value"),
                "offset_unit": item.get("offset_unit"),
                "time_anchor_key": item["time_anchor_key"],
            }
            for item in card.get("workflow_operands", {}).get("deadlines", [])
        ],
        # DEBT-049 Phase3 U2：承载卡端 method_keys_allowed（此前 workflow_operands 只挑
        # artifacts/deadlines、method 维度整丢 → transport 死码）。dead-carry：暂无消费者读
        # 此字段 → 投影结果零行为；CCTV 桥/供给（U4/U5）激活后为 method 义务比对提供卡端锚。
        "method_keys": list(
            card.get("workflow_operands", {}).get("method_keys_allowed", []) or []
        ),
        "evidence_requirements": evidence_requirements,
        "required_sidecar_interfaces": _collect_required_sidecar_interfaces(card, mapping),
    }


def compile_projection_contract(bundle_dir: Path | None = None) -> Dict[str, Any]:
    bundle_dir = bundle_dir or DEFAULT_RULECARD_BUNDLE_DIR
    bundle = load_rulecard_bundle(bundle_dir)
    mapping = load_runtime_mapping(bundle.bundle_dir)
    slot_ids = sorted({item["slot_id"] for card in bundle.cards for item in card.get("slot_role_map", [])})
    measure_keys = sorted({item["measure_key"] for card in bundle.cards for item in card.get("threshold_regimes", [])})
    # DEBT-049 Phase3 U2：卡端全 method_keys 并集（承载 method_alias_map 用；镜像 slot/measure）。
    method_keys = sorted({
        str(mk)
        for card in bundle.cards
        for mk in (card.get("workflow_operands", {}).get("method_keys_allowed", []) or [])
    })
    return {
        "version": PROJECTION_CONTRACT_VERSION,
        "generated_at": _utc_now_iso(),
        "rulecard_bundle_id": bundle.manifest["bundle_id"],
        "rulecard_schema_version": bundle.manifest["schema_version"],
        "runtime_mapping_version": mapping["version"],
        "runtime_mapping_path": mapping["mapping_path"],
        "input_partitions": ["world", "measurement", "qualifier", "sidecar"],
        "slot_partition_map": {slot_id: _slot_partition(slot_id) for slot_id in slot_ids},
        "measure_partition_map": {measure_key: _measure_partition(measure_key) for measure_key in measure_keys},
        "slot_alias_map": {
            slot_id: _slot_aliases(mapping, slot_id)
            for slot_id in slot_ids
            if _slot_aliases(mapping, slot_id)
        },
        "measure_alias_map": {
            measure_key: _measure_aliases(mapping, measure_key)
            for measure_key in measure_keys
            if _measure_aliases(mapping, measure_key)
        },
        # DEBT-049 Phase3 U2：method 别名承载（此前顶层无 method_alias_map、transport 死码）。
        # 四方法暗部署 alias 列表为空 → 过滤后 map 为空（dead-carry 零行为）；CCTV 桥（U4/U5）
        # 落 cctv_survey:[drainage_cctv,CCTV] 后此 map 才非空。方向：{canonical→[alias...]}。
        "method_alias_map": {
            method_key: _method_aliases(mapping, method_key)
            for method_key in method_keys
            if _method_aliases(mapping, method_key)
        },
        "result_contract": {
            "applicability_states": ["applicable", "not_applicable", "unknown"],
            "verdicts": ["pass", "fail", "unknown", "not_applicable"],
            "required_arrays": ["basis_items", "unmet_requirements", "unknown_reasons"],
            "batch_breakdowns": [
                "projection_coverage",
                "verdict_distribution",
                "unknown_reason_breakdown",
                "missing_sidecar_breakdown",
                "missing_measure_breakdown",
                "rule_hit_breakdown",
                "family_hit_breakdown",
            ],
        },
    }


def compile_projection_specs(bundle_dir: Path | None = None, contract: Dict[str, Any] | None = None) -> Dict[str, Any]:
    bundle_dir = bundle_dir or DEFAULT_RULECARD_BUNDLE_DIR
    bundle = load_rulecard_bundle(bundle_dir)
    contract = contract or compile_projection_contract(bundle.bundle_dir)
    mapping = load_runtime_mapping(bundle.bundle_dir)
    card_specs = {}
    for card in bundle.cards:
        compiled = _compiled_card_spec(card, mapping)
        card_specs[compiled["rule_card_id"]] = compiled
    family_specs: List[Dict[str, Any]] = []
    for family in bundle.families:
        family_specs.append(
            {
                "family_id": family["family_id"],
                "family_name": family.get("family_name", family["family_id"]),
                "phase": family.get("phase"),
                "actor": family.get("actor"),
                "subject": family.get("subject"),
                "action_cluster": family.get("action_cluster"),
                "allowed_world_projection_families": _family_projection_filter(mapping, family["family_id"]),
                "card_specs": [card_specs[card_id] for card_id in family.get("card_ids", []) if card_id in card_specs],
            }
        )
    return {
        "version": PROJECTION_SPEC_VERSION,
        "generated_at": _utc_now_iso(),
        "rulecard_bundle_id": bundle.manifest["bundle_id"],
        "rulecard_schema_version": bundle.manifest["schema_version"],
        "projection_contract_version": contract["version"],
        "runtime_mapping_version": mapping["version"],
        "runtime_mapping_path": mapping["mapping_path"],
        "family_count": len(family_specs),
        "rule_card_count": len(card_specs),
        "family_specs": family_specs,
    }


def write_projection_compile_artifacts(
    output_dir: Path,
    bundle_dir: Path | None = None,
) -> Dict[str, Path]:
    bundle_dir = bundle_dir or DEFAULT_RULECARD_BUNDLE_DIR
    contract = compile_projection_contract(bundle_dir)
    specs = compile_projection_specs(bundle_dir, contract)
    manifest = {
        "version": "regulation_projection.compile_manifest.v1",
        "generated_at": _utc_now_iso(),
        "rulecard_bundle_dir": str(bundle_dir),
        "rulecard_bundle_id": contract["rulecard_bundle_id"],
        "rulecard_schema_version": contract["rulecard_schema_version"],
        "projection_contract_version": contract["version"],
        "projection_spec_version": specs["version"],
        "runtime_mapping_version": contract["runtime_mapping_version"],
        "runtime_mapping_path": contract["runtime_mapping_path"],
    }
    return {
        "contract_path": _write_json(output_dir / "ProjectionContract.v1.json", contract),
        "spec_path": _write_json(output_dir / "ProjectionSpecs.v1.json", specs),
        "manifest_path": _write_json(output_dir / "ProjectionCompileManifest.v1.json", manifest),
    }


def iter_card_specs(compiled_spec: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for family in compiled_spec.get("family_specs", []):
        for card in family.get("card_specs", []):
            yield card
