"""RuleCard v2 bundle loader, semantic-normalization validator, and index rebuilder."""
from __future__ import annotations

import argparse
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
FAMILY_ID_RE = re.compile(
    r"^(mbis|mwis)\.[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$"
)
RULE_CARD_ID_RE = re.compile(
    r"^rc\.(mbis|mwis)(\.[a-z0-9_]+){4}\.s[a-z0-9_]+(?:_[a-z0-9_]+)*\.c\d{2}$"
)
SUBORDINATE_ID_RE = re.compile(r"^.+\.(t|x|d|e|n)\d{2}$")
SLOT_REF_ID_RE = re.compile(r"^.+\.sr\d{2}$")
# 语义槽词根白名单。**这不是一个闭集**——蓝图未把词根定义成闭集，只规定新增槽走
# 规范点分命名、且卡侧槽与世界槽靠「同名或别名」衔接。
# 2026-07-29 增补 5 个词根（第三方审核裁定，规格依据见下）：
#   artifact / assessment / fire_safety / maintenance / ubw
# 它们都是**世界模型实产**的槽域（实测事实数 artifact.* 2,550、fire_safety.* 347、
# ubw.* 120、assessment.* 120、maintenance.* 120），蓝图亦逐个点名：
#   W0 §01 设计原则与本体边界（artifact.* 为旁车行政事实）、W1 §08 派生 flag
#   （maintenance.pre_next_cycle.required / ubw.present / fire_safety.deficiency.present /
#     assessment.fsp.below_required_safety）、W2 §06 canonical_slots 与 projection_binding。
# 替代方案（把槽名改写到旧词根下）被否：那会凭空制造新的命名分叉，
# 而命名不匹配正是本项目一整类静默失效的来源。
# ⚠️ 世界侧另有约 100 个词根（count / duration / crack_width_mm 等）是**量表键**，
# 走下面的 MEASURE_KEY_RE，**不得**并进本表（实测两表交集为空）。
SLOT_ID_RE = re.compile(
    r"^(actor|artifact|assessment|defect|fire_safety|investigation|maintenance"
    r"|procedure|repair|reporting|risk|scope|supervision|ubw|verification)"
    r"(\.[a-z0-9_]+)+$"
)
MEASURE_KEY_RE = re.compile(
    r"^(area|ratio|count|length|duration|rate|stress|pressure|strength|depth|thickness)(\.[a-z0-9_]+)+$"
)
ARTIFACT_KEY_RE = re.compile(
    r"^(report|form|notice|proposal|record|photo|drawing|certificate|statement)(\.[a-z0-9_]+)+$"
)
TIME_ANCHOR_KEY_RE = re.compile(
    r"^(appointment|nomination|inspection|investigation|repair|role|site_visit|validation_test)(\.[a-z0-9_]+){1,}$"
)
ROLE_SET = {"trigger", "prerequisite", "evidence", "definition_reference"}
NODE_KIND_SET = {"obligation", "prohibition", "escalation"}
LOGIC_SET = {"all", "any"}
PREDICATE_KIND_SET = {"slot", "measure"}
REQUIRED_VOCABS = {
    "actor_role_key",
    "component_type_key",
    "location_class_key",
    "defect_class_key",
    "risk_class_key",
    "method_key",
    "artifact_field_group_key",
    "status_term",
    "material_class_key",
}


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


# 契约校验违规收集器。非 None 时 `_ensure` 把失败写入列表并继续，
# 以便一次列出全部违规（批跑闸 / 摸清全貌）；None 时保持遇错即抛。
_VIOLATION_COLLECTOR: Optional[List[str]] = None


def _ensure(condition: bool, message: str) -> None:
    if condition:
        return
    if _VIOLATION_COLLECTOR is not None:
        _VIOLATION_COLLECTOR.append(message)
        return
    raise ValueError(message)


@contextmanager
def _collecting_violations() -> Iterator[List[str]]:
    """进入收集模式：契约失败写入列表，不中断后续检查。"""
    global _VIOLATION_COLLECTOR
    bucket: List[str] = []
    prev = _VIOLATION_COLLECTOR
    _VIOLATION_COLLECTOR = bucket
    try:
        yield bucket
    finally:
        _VIOLATION_COLLECTOR = prev


def _require_keys(payload: dict, keys: Sequence[str], label: str) -> None:
    for key in keys:
        _ensure(key in payload, f"{label} missing required key: {key}")


def _sorted_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted((_sorted_jsonable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _normalized_qualifiers(qualifiers: Dict[str, Any] | None) -> Dict[str, Any]:
    if not qualifiers:
        return {}
    normalized = _sorted_jsonable(qualifiers)
    _ensure(isinstance(normalized, dict), "qualifiers must normalize to a dict")
    return normalized


def _qualifier_fingerprint(slot_id: str, qualifiers: Dict[str, Any] | None) -> str:
    normalized = _normalized_qualifiers(qualifiers)
    return json.dumps({"slot_id": slot_id, "qualifiers": normalized}, sort_keys=True, ensure_ascii=False)


def _registry_index(items: Iterable[Dict[str, Any]], key_field: str, label: str) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for idx, item in enumerate(items):
        _ensure(key_field in item, f"{label}[{idx}] missing key field {key_field}")
        key = item[key_field]
        _ensure(key not in result, f"duplicate {key_field}: {key}")
        result[key] = item
    return result


def _validate_slot_id(slot_id: str, label: str) -> None:
    _ensure(SLOT_ID_RE.fullmatch(slot_id) is not None, f"{label} has invalid slot_id grammar: {slot_id}")
    for segment in slot_id.split("."):
        _ensure(not segment.startswith(("has_", "is_")), f"{label} must not use boolean implementation prefix: {slot_id}")
        _ensure(not segment.endswith(("_at", "_ts")), f"{label} must not encode timestamp suffix: {slot_id}")


def _validate_measure_key(measure_key: str, label: str) -> None:
    _ensure(MEASURE_KEY_RE.fullmatch(measure_key) is not None, f"{label} has invalid measure_key grammar: {measure_key}")


def _validate_artifact_key(artifact_key: str, label: str) -> None:
    _ensure(ARTIFACT_KEY_RE.fullmatch(artifact_key) is not None, f"{label} has invalid artifact_key grammar: {artifact_key}")


def _validate_time_anchor_key(time_anchor_key: str, label: str) -> None:
    _ensure(
        TIME_ANCHOR_KEY_RE.fullmatch(time_anchor_key) is not None,
        f"{label} has invalid time_anchor_key grammar: {time_anchor_key}",
    )


def _validate_qualifiers(
    qualifiers: Dict[str, Any] | None,
    vocabularies: Dict[str, List[str]],
    artifact_keys: Set[str],
    time_anchor_keys: Set[str],
    label: str,
) -> Dict[str, Any]:
    normalized = _normalized_qualifiers(qualifiers)
    for qualifier_key, qualifier_value in normalized.items():
        if qualifier_key == "artifact_key":
            allowed_values = artifact_keys
        elif qualifier_key == "time_anchor_key":
            allowed_values = time_anchor_keys
        else:
            _ensure(qualifier_key in vocabularies, f"{label} uses unknown qualifier namespace: {qualifier_key}")
            allowed_values = set(vocabularies[qualifier_key])

        values = qualifier_value if isinstance(qualifier_value, list) else [qualifier_value]
        _ensure(values, f"{label}.{qualifier_key} must not be empty")
        for value in values:
            _ensure(isinstance(value, str), f"{label}.{qualifier_key} values must be strings")
            _ensure(value in allowed_values, f"{label}.{qualifier_key} uses unsupported value: {value}")
    return normalized


@dataclass
class RuleCardBundle:
    bundle_dir: Path
    manifest: Dict[str, Any]
    cards_document: Dict[str, Any]
    family_index: Dict[str, Any]
    slot_index: Dict[str, Any]
    threshold_regime_index: Dict[str, Any]
    exception_definition_index: Dict[str, Any]
    semantic_slot_registry: Dict[str, Any]
    measure_registry: Dict[str, Any]
    artifact_semantics_registry: Dict[str, Any]
    time_anchor_registry: Dict[str, Any]
    controlled_vocabularies: Dict[str, Any]

    @property
    def cards(self) -> List[Dict[str, Any]]:
        return self.cards_document["cards"]

    @property
    def families(self) -> List[Dict[str, Any]]:
        return self.family_index["families"]

    def summary(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.manifest["bundle_id"],
            "schema_version": self.manifest["schema_version"],
            "source_document_count": len(self.manifest["source_documents"]),
            "family_count": len(self.families),
            "rule_card_count": len(self.cards),
            "semantic_slot_registry_count": len(self.semantic_slot_registry.get("slots", [])),
            "measure_registry_count": len(self.measure_registry.get("measures", [])),
            "artifact_registry_count": len(self.artifact_semantics_registry.get("artifacts", [])),
            "time_anchor_registry_count": len(self.time_anchor_registry.get("time_anchors", [])),
            "threshold_regime_count": len(self.threshold_regime_index.get("threshold_regimes", [])),
            "exception_count": len(self.exception_definition_index.get("exceptions", [])),
            "definition_count": len(self.exception_definition_index.get("definitions", [])),
            "slot_count": len(self.slot_index.get("slots", [])),
        }


def load_rulecard_bundle(bundle_dir: Path) -> RuleCardBundle:
    manifest = _load_json(bundle_dir / "manifest.json")
    _require_keys(manifest, ("bundle_id", "schema_version", "source_documents", "files"), "manifest")
    files = manifest["files"]
    _require_keys(
        files,
        (
            "rule_cards",
            "family_index",
            "slot_index",
            "threshold_regime_index",
            "exception_definition_index",
            "semantic_slot_registry",
            "measure_registry",
            "artifact_semantics_registry",
            "time_anchor_registry",
            "controlled_vocabularies",
        ),
        "manifest.files",
    )
    return RuleCardBundle(
        bundle_dir=bundle_dir,
        manifest=manifest,
        cards_document=_load_json(bundle_dir / files["rule_cards"]),
        family_index=_load_json(bundle_dir / files["family_index"]),
        slot_index=_load_json(bundle_dir / files["slot_index"]),
        threshold_regime_index=_load_json(bundle_dir / files["threshold_regime_index"]),
        exception_definition_index=_load_json(bundle_dir / files["exception_definition_index"]),
        semantic_slot_registry=_load_json(bundle_dir / files["semantic_slot_registry"]),
        measure_registry=_load_json(bundle_dir / files["measure_registry"]),
        artifact_semantics_registry=_load_json(bundle_dir / files["artifact_semantics_registry"]),
        time_anchor_registry=_load_json(bundle_dir / files["time_anchor_registry"]),
        controlled_vocabularies=_load_json(bundle_dir / files["controlled_vocabularies"]),
    )


def _slot_ref_lookup(card: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {item["slot_ref_id"]: item for item in card.get("slot_role_map", [])}


def derive_slot_index(cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    slot_map: Dict[str, Dict[str, Any]] = {}
    for card in cards:
        card_id = card["rule_card_id"]
        family_id = card["family_id"]
        slot_ref_map = _slot_ref_lookup(card)
        for item in card.get("slot_role_map", []):
            fingerprint = _qualifier_fingerprint(item["slot_id"], item.get("qualifiers"))
            bucket = slot_map.setdefault(
                fingerprint,
                {
                    "slot_id": item["slot_id"],
                    "qualifiers": _normalized_qualifiers(item.get("qualifiers")),
                    "roles": set(),
                    "rule_card_ids": set(),
                    "family_ids": set(),
                },
            )
            bucket["roles"].update(item.get("roles", []))
            bucket["rule_card_ids"].add(card_id)
            bucket["family_ids"].add(family_id)

        for item in card.get("trigger_conditions", {}).get("items", []):
            if item.get("predicate_kind") != "slot":
                continue
            slot_ref = slot_ref_map[item["slot_ref_id"]]
            fingerprint = _qualifier_fingerprint(slot_ref["slot_id"], slot_ref.get("qualifiers"))
            bucket = slot_map.setdefault(
                fingerprint,
                {
                    "slot_id": slot_ref["slot_id"],
                    "qualifiers": _normalized_qualifiers(slot_ref.get("qualifiers")),
                    "roles": set(),
                    "rule_card_ids": set(),
                    "family_ids": set(),
                },
            )
            bucket["roles"].add("trigger")
            bucket["rule_card_ids"].add(card_id)
            bucket["family_ids"].add(family_id)

        for phase in ("for_matching", "for_submission", "for_completion"):
            for requirement in card.get("evidence_requirements", {}).get(phase, []):
                for slot_ref_id in requirement.get("slot_ref_ids", []):
                    slot_ref = slot_ref_map[slot_ref_id]
                    fingerprint = _qualifier_fingerprint(slot_ref["slot_id"], slot_ref.get("qualifiers"))
                    bucket = slot_map.setdefault(
                        fingerprint,
                        {
                            "slot_id": slot_ref["slot_id"],
                            "qualifiers": _normalized_qualifiers(slot_ref.get("qualifiers")),
                            "roles": set(),
                            "rule_card_ids": set(),
                            "family_ids": set(),
                        },
                    )
                    bucket["roles"].add("evidence")
                    bucket["rule_card_ids"].add(card_id)
                    bucket["family_ids"].add(family_id)

    slots = []
    for fingerprint in sorted(slot_map):
        bucket = slot_map[fingerprint]
        slots.append(
            {
                "slot_id": bucket["slot_id"],
                "qualifiers": bucket["qualifiers"],
                "roles": sorted(bucket["roles"]),
                "rule_card_ids": sorted(bucket["rule_card_ids"]),
                "family_ids": sorted(bucket["family_ids"]),
            }
        )
    return {"slots": slots}


def derive_threshold_regime_index(cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    regimes = []
    for card in cards:
        for regime in card.get("threshold_regimes", []):
            entry = dict(regime)
            entry["family_id"] = card["family_id"]
            entry["rule_card_id"] = card["rule_card_id"]
            regimes.append(entry)
    regimes.sort(key=lambda item: item["threshold_regime_id"])
    return {"threshold_regimes": regimes}


def derive_exception_definition_index(cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    exceptions = []
    definitions = []
    for card in cards:
        for exception in card.get("exceptions", []):
            entry = dict(exception)
            entry["family_id"] = card["family_id"]
            entry["rule_card_id"] = card["rule_card_id"]
            exceptions.append(entry)
        for definition in card.get("definitions", []):
            entry = dict(definition)
            entry["family_id"] = card["family_id"]
            entry["rule_card_id"] = card["rule_card_id"]
            definitions.append(entry)
    exceptions.sort(key=lambda item: item["exception_id"])
    definitions.sort(key=lambda item: item["definition_id"])
    return {"exceptions": exceptions, "definitions": definitions}


def rebuild_derived_indexes(cards: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        "slot_index": derive_slot_index(cards),
        "threshold_regime_index": derive_threshold_regime_index(cards),
        "exception_definition_index": derive_exception_definition_index(cards),
    }


def _validate_manifest(bundle: RuleCardBundle) -> None:
    _ensure(SEMVER_RE.fullmatch(bundle.manifest["schema_version"]) is not None, "manifest.schema_version must be semver")
    _ensure(
        isinstance(bundle.manifest["source_documents"], list) and bundle.manifest["source_documents"],
        "manifest.source_documents must be a non-empty list",
    )
    for idx, source in enumerate(bundle.manifest["source_documents"]):
        label = f"manifest.source_documents[{idx}]"
        _require_keys(
            source,
            ("source_document_id", "source_document_version", "title", "page_count", "canonical_file"),
            label,
        )
        _ensure(isinstance(source["page_count"], int) and source["page_count"] > 0, f"{label}.page_count must be a positive integer")


def _validate_family_index(bundle: RuleCardBundle) -> Dict[str, Dict[str, Any]]:
    _ensure(isinstance(bundle.family_index.get("families"), list), "family_index.families must be a list")
    family_map: Dict[str, Dict[str, Any]] = {}
    for idx, family in enumerate(bundle.families):
        label = f"family_index.families[{idx}]"
        _require_keys(
            family,
            ("family_id", "family_name", "phase", "actor", "subject", "action_cluster", "deprecated_family_ids", "card_ids"),
            label,
        )
        family_id = family["family_id"]
        _ensure(FAMILY_ID_RE.fullmatch(family_id) is not None, f"{label}.family_id has invalid grammar: {family_id}")
        _ensure(family_id not in family_map, f"duplicate family_id: {family_id}")
        _ensure(isinstance(family["deprecated_family_ids"], list), f"{label}.deprecated_family_ids must be a list")
        _ensure(isinstance(family["card_ids"], list), f"{label}.card_ids must be a list")
        family_map[family_id] = family
    return family_map


def _validate_registries(
    bundle: RuleCardBundle,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    for label, registry in (
        ("semantic_slot_registry", bundle.semantic_slot_registry),
        ("measure_registry", bundle.measure_registry),
        ("artifact_semantics_registry", bundle.artifact_semantics_registry),
        ("time_anchor_registry", bundle.time_anchor_registry),
        ("controlled_vocabularies", bundle.controlled_vocabularies),
    ):
        _require_keys(registry, ("registry_id", "schema_version"), label)
        _ensure(SEMVER_RE.fullmatch(registry["schema_version"]) is not None, f"{label}.schema_version must be semver")

    _ensure(isinstance(bundle.semantic_slot_registry.get("slots"), list), "semantic_slot_registry.slots must be a list")
    semantic_slot_map = _registry_index(bundle.semantic_slot_registry["slots"], "slot_id", "semantic_slot_registry.slots")
    for slot_id, entry in semantic_slot_map.items():
        label = f"semantic_slot_registry.slots[{slot_id}]"
        _require_keys(entry, ("slot_id", "semantic_domain", "allowed_roles"), label)
        _validate_slot_id(slot_id, label)
        _ensure(set(entry["allowed_roles"]).issubset(ROLE_SET), f"{label}.allowed_roles contains unsupported role")

    _ensure(isinstance(bundle.measure_registry.get("measures"), list), "measure_registry.measures must be a list")
    measure_map = _registry_index(bundle.measure_registry["measures"], "measure_key", "measure_registry.measures")
    for measure_key, entry in measure_map.items():
        label = f"measure_registry.measures[{measure_key}]"
        _require_keys(entry, ("measure_key", "quantity_family", "unit", "allowed_operators"), label)
        _validate_measure_key(measure_key, label)

    _ensure(
        isinstance(bundle.artifact_semantics_registry.get("artifacts"), list),
        "artifact_semantics_registry.artifacts must be a list",
    )
    artifact_map = _registry_index(bundle.artifact_semantics_registry["artifacts"], "artifact_key", "artifact_semantics_registry.artifacts")
    for artifact_key, entry in artifact_map.items():
        label = f"artifact_semantics_registry.artifacts[{artifact_key}]"
        _require_keys(entry, ("artifact_key", "artifact_family", "semantic_meaning"), label)
        _validate_artifact_key(artifact_key, label)

    _ensure(isinstance(bundle.time_anchor_registry.get("time_anchors"), list), "time_anchor_registry.time_anchors must be a list")
    time_anchor_map = _registry_index(bundle.time_anchor_registry["time_anchors"], "time_anchor_key", "time_anchor_registry.time_anchors")
    for time_anchor_key, entry in time_anchor_map.items():
        label = f"time_anchor_registry.time_anchors[{time_anchor_key}]"
        _require_keys(entry, ("time_anchor_key", "semantic_meaning"), label)
        _validate_time_anchor_key(time_anchor_key, label)

    vocabularies = bundle.controlled_vocabularies.get("vocabularies")
    _ensure(isinstance(vocabularies, dict), "controlled_vocabularies.vocabularies must be an object")
    _ensure(REQUIRED_VOCABS.issubset(vocabularies.keys()), "controlled_vocabularies missing required vocabularies")
    for vocab_name, entries in vocabularies.items():
        _ensure(isinstance(entries, list) and entries, f"controlled_vocabularies.{vocab_name} must be a non-empty list")
        _ensure(all(isinstance(item, str) for item in entries), f"controlled_vocabularies.{vocab_name} values must be strings")

    return semantic_slot_map, measure_map, artifact_map, time_anchor_map, vocabularies


def _validate_card(
    card: Dict[str, Any],
    family_map: Dict[str, Dict[str, Any]],
    source_document_ids: Set[str],
    page_counts: Dict[str, int],
    semantic_slot_map: Dict[str, Dict[str, Any]],
    measure_map: Dict[str, Dict[str, Any]],
    artifact_map: Dict[str, Dict[str, Any]],
    time_anchor_map: Dict[str, Dict[str, Any]],
    vocabularies: Dict[str, List[str]],
) -> None:
    card_id = card["rule_card_id"]
    family_id = card["family_id"]
    _ensure(RULE_CARD_ID_RE.fullmatch(card_id) is not None, f"invalid rule_card_id grammar: {card_id}")
    _ensure(card_id.startswith(f"rc.{family_id}."), f"{card_id} must embed family_id {family_id}")
    _ensure(card["source_document_id"] in source_document_ids, f"{card_id} references unknown source_document_id {card['source_document_id']}")
    _ensure(family_id in family_map, f"{card_id} references unknown family_id {family_id}")
    _ensure(
        SEMVER_RE.fullmatch(card["version"]["authoring_revision"]) is not None,
        f"{card_id}.version.authoring_revision must be semver",
    )

    page_count = page_counts[card["source_document_id"]]
    for idx, section in enumerate(card["source_section"]):
        label = f"{card_id}.source_section[{idx}]"
        _require_keys(section, ("section_id", "page_start", "page_end"), label)
        _ensure(1 <= section["page_start"] <= section["page_end"] <= page_count, f"{label} page range is out of bounds")

    quote_ids = set()
    for idx, quote in enumerate(card["source_quote"]):
        label = f"{card_id}.source_quote[{idx}]"
        _require_keys(quote, ("quote_id", "text", "page", "language"), label)
        _ensure(quote["quote_id"] not in quote_ids, f"{card_id} duplicate quote_id {quote['quote_id']}")
        _ensure(1 <= quote["page"] <= page_count, f"{label}.page is out of bounds")
        quote_ids.add(quote["quote_id"])

    _ensure(card["trigger_conditions"]["logic"] in LOGIC_SET, f"{card_id}.trigger_conditions.logic must be one of {sorted(LOGIC_SET)}")

    artifact_keys = set(artifact_map)
    time_anchor_keys = set(time_anchor_map)
    slot_ref_map: Dict[str, Dict[str, Any]] = {}
    for mapping in card["slot_role_map"]:
        slot_ref_id = mapping["slot_ref_id"]
        _ensure(SLOT_REF_ID_RE.fullmatch(slot_ref_id) is not None, f"{card_id} has invalid slot_ref_id {slot_ref_id}")
        _ensure(slot_ref_id not in slot_ref_map, f"{card_id} duplicate slot_ref_id {slot_ref_id}")
        slot_id = mapping["slot_id"]
        _ensure(slot_id in semantic_slot_map, f"{card_id} references unknown slot_id {slot_id}")
        qualifiers = _validate_qualifiers(mapping.get("qualifiers"), vocabularies, artifact_keys, time_anchor_keys, f"{card_id}.{slot_ref_id}.qualifiers")
        roles = set(mapping["roles"])
        _ensure(roles.issubset(ROLE_SET), f"{card_id} has unsupported slot role(s) for {slot_ref_id}")
        _ensure(
            roles.issubset(set(semantic_slot_map[slot_id]["allowed_roles"])),
            f"{card_id}.{slot_ref_id} uses role not allowed by registry for {slot_id}",
        )
        slot_ref_map[slot_ref_id] = {**mapping, "qualifiers": qualifiers}

    _ensure(bool(slot_ref_map), f"{card_id}.slot_role_map must not be empty")

    condition_ids = set()
    for item in card["trigger_conditions"]["items"]:
        condition_id = item["condition_id"]
        _ensure(condition_id not in condition_ids, f"{card_id} duplicate condition_id {condition_id}")
        _ensure(item["predicate_kind"] in PREDICATE_KIND_SET, f"{card_id} has unsupported predicate_kind {item['predicate_kind']}")
        if item["predicate_kind"] == "slot":
            slot_ref_id = item["slot_ref_id"]
            _ensure(slot_ref_id in slot_ref_map, f"{card_id} trigger condition references unknown slot_ref_id {slot_ref_id}")
        else:
            measure_key = item["measure_key"]
            _ensure(measure_key in measure_map, f"{card_id} trigger condition references unknown measure_key {measure_key}")
            _validate_qualifiers(item.get("qualifiers"), vocabularies, artifact_keys, time_anchor_keys, f"{card_id}.{condition_id}.qualifiers")
        condition_ids.add(condition_id)

    workflow = card["workflow_operands"]
    _ensure(workflow["primary_actor"] in card["applicability"]["actors"], f"{card_id}.workflow_operands.primary_actor must appear in applicability.actors")
    _ensure(workflow["primary_actor"] in vocabularies["actor_role_key"], f"{card_id}.workflow_operands.primary_actor must be a known actor_role_key")

    recipient_ids = set()
    for recipient in workflow["recipients"]:
        recipient_id = recipient["recipient_id"]
        _ensure(recipient_id not in recipient_ids, f"{card_id} duplicate recipient_id {recipient_id}")
        _ensure(recipient["recipient_key"] in vocabularies["actor_role_key"], f"{card_id} recipient uses unknown actor_role_key")
        recipient_ids.add(recipient_id)

    artifact_ids = set()
    for artifact in workflow["artifacts"]:
        artifact_id = artifact["artifact_id"]
        _ensure(artifact_id not in artifact_ids, f"{card_id} duplicate artifact_id {artifact_id}")
        _ensure(artifact["artifact_key"] in artifact_map, f"{card_id} artifact uses unknown artifact_key {artifact['artifact_key']}")
        artifact_ids.add(artifact_id)

    deadline_ids = set()
    for deadline in workflow["deadlines"]:
        deadline_id = deadline["deadline_id"]
        _ensure(deadline_id not in deadline_ids, f"{card_id} duplicate deadline_id {deadline_id}")
        _ensure(deadline["time_anchor_key"] in time_anchor_map, f"{card_id} deadline uses unknown time_anchor_key {deadline['time_anchor_key']}")
        deadline_ids.add(deadline_id)

    for audience in workflow.get("audiences", []):
        _ensure(audience in vocabularies["actor_role_key"], f"{card_id} workflow audience uses unknown actor_role_key {audience}")
    for method_key in workflow.get("method_keys_allowed", []):
        # "*" = 开放集哨兵（2026-07-08 q5 专员判定 + codex 裁定转写：条款要求验证
        # 测试但方法集开放，如 §5.1.1 专业判断表述）——词表校验放行。
        if method_key == "*":
            continue
        _ensure(method_key in vocabularies["method_key"], f"{card_id} workflow uses unknown method_key {method_key}")

    threshold_ids = set()
    for regime in card["threshold_regimes"]:
        threshold_id = regime["threshold_regime_id"]
        _ensure(SUBORDINATE_ID_RE.fullmatch(threshold_id) is not None, f"{card_id} has invalid threshold_regime_id {threshold_id}")
        _ensure(threshold_id not in threshold_ids, f"{card_id} duplicate threshold_regime_id {threshold_id}")
        measure_key = regime["measure_key"]
        _ensure(measure_key in measure_map, f"{card_id} threshold references unknown measure_key {measure_key}")
        _validate_qualifiers(regime.get("qualifiers"), vocabularies, artifact_keys, time_anchor_keys, f"{card_id}.{threshold_id}.qualifiers")
        if "time_anchor_key" in regime:
            _ensure(regime["time_anchor_key"] in time_anchor_map, f"{card_id} threshold uses unknown time_anchor_key {regime['time_anchor_key']}")
        if "formula" in regime:
            for variable in regime["formula"].get("variables", []):
                _ensure(variable["measure_key"] in measure_map, f"{card_id} formula variable references unknown measure_key {variable['measure_key']}")
        _ensure(set(regime.get("source_quote_refs", [])).issubset(quote_ids), f"{card_id} threshold {threshold_id} has unknown source_quote_refs")
        threshold_ids.add(threshold_id)

    definition_ids = set()
    for definition in card["definitions"]:
        definition_id = definition["definition_id"]
        _ensure(SUBORDINATE_ID_RE.fullmatch(definition_id) is not None, f"{card_id} has invalid definition_id {definition_id}")
        _ensure(definition_id not in definition_ids, f"{card_id} duplicate definition_id {definition_id}")
        _ensure(set(definition.get("source_quote_refs", [])).issubset(quote_ids), f"{card_id} definition {definition_id} has unknown source_quote_refs")
        definition_ids.add(definition_id)

    exception_ids = set()
    for exception in card["exceptions"]:
        exception_id = exception["exception_id"]
        _ensure(SUBORDINATE_ID_RE.fullmatch(exception_id) is not None, f"{card_id} has invalid exception_id {exception_id}")
        _ensure(exception_id not in exception_ids, f"{card_id} duplicate exception_id {exception_id}")
        _ensure(set(exception.get("source_quote_refs", [])).issubset(quote_ids), f"{card_id} exception {exception_id} has unknown source_quote_refs")
        exception_ids.add(exception_id)

    nodes = card["obligation_graph"]["nodes"]
    _ensure(bool(nodes), f"{card_id}.obligation_graph.nodes must not be empty")
    node_ids = set()
    for node in nodes:
        node_id = node["obligation_node_id"]
        _ensure(SUBORDINATE_ID_RE.fullmatch(node_id) is not None, f"{card_id} has invalid obligation_node_id {node_id}")
        _ensure(node["node_kind"] in NODE_KIND_SET, f"{card_id} unsupported node kind {node['node_kind']}")
        _ensure(node_id not in node_ids, f"{card_id} duplicate obligation_node_id {node_id}")
        _ensure(set(node.get("recipient_ids", [])).issubset(recipient_ids), f"{card_id} node {node_id} references unknown recipient_ids")
        _ensure(set(node.get("artifact_ids", [])).issubset(artifact_ids), f"{card_id} node {node_id} references unknown artifact_ids")
        _ensure(set(node.get("deadline_ids", [])).issubset(deadline_ids), f"{card_id} node {node_id} references unknown deadline_ids")
        _ensure(set(node.get("trigger_condition_ids", [])).issubset(condition_ids), f"{card_id} node {node_id} references unknown trigger_condition_ids")
        node_ids.add(node_id)

    for edge in card["obligation_graph"]["edges"]:
        _ensure(edge["source_node_id"] in node_ids, f"{card_id} edge source not found: {edge['source_node_id']}")
        _ensure(edge["target_node_id"] in node_ids, f"{card_id} edge target not found: {edge['target_node_id']}")

    evidence_ids = set()
    for phase in ("for_matching", "for_submission", "for_completion"):
        for requirement in card["evidence_requirements"][phase]:
            evidence_id = requirement["evidence_requirement_id"]
            _ensure(SUBORDINATE_ID_RE.fullmatch(evidence_id) is not None, f"{card_id} has invalid evidence_requirement_id {evidence_id}")
            _ensure(evidence_id not in evidence_ids, f"{card_id} duplicate evidence_requirement_id {evidence_id}")
            _ensure(set(requirement.get("artifact_ids", [])).issubset(artifact_ids), f"{card_id} evidence requirement {evidence_id} references unknown artifact_ids")
            _ensure(set(requirement.get("slot_ref_ids", [])).issubset(slot_ref_map), f"{card_id} evidence requirement {evidence_id} references unknown slot_ref_ids")
            _ensure(set(requirement.get("measure_keys", [])).issubset(measure_map), f"{card_id} evidence requirement {evidence_id} references unknown measure_keys")
            _ensure(
                set(requirement.get("required_field_groups", [])).issubset(vocabularies["artifact_field_group_key"]),
                f"{card_id} evidence requirement {evidence_id} references unknown artifact_field_group_key",
            )
            evidence_ids.add(evidence_id)

    for neighbor in card.get("neighbor_families", []):
        _ensure(neighbor["family_id"] in family_map, f"{card_id} neighbor family not found: {neighbor['family_id']}")


def _validate_rulecard_bundle_body(bundle_dir: Path) -> RuleCardBundle:
    """契约校验本体。失败走 `_ensure`（收集模式写列表 / 否则即抛）。"""
    bundle = load_rulecard_bundle(bundle_dir)
    _validate_manifest(bundle)
    family_map = _validate_family_index(bundle)
    semantic_slot_map, measure_map, artifact_map, time_anchor_map, vocabularies = _validate_registries(bundle)

    cards = bundle.cards_document.get("cards")
    _ensure(bundle.cards_document.get("bundle_id") == bundle.manifest["bundle_id"], "cards_document.bundle_id must match manifest.bundle_id")
    _ensure(isinstance(cards, list) and cards, "rule_cards.cards must be a non-empty list")

    source_document_ids = {item["source_document_id"] for item in bundle.manifest["source_documents"]}
    page_counts = {item["source_document_id"]: item["page_count"] for item in bundle.manifest["source_documents"]}
    card_ids = set()
    for idx, card in enumerate(cards or []):
        label = f"rule_cards.cards[{idx}]"
        _require_keys(
            card,
            (
                "rule_card_id",
                "source_document_id",
                "source_section",
                "source_quote",
                "normalized_rule_text",
                "family_id",
                "applicability",
                "trigger_conditions",
                "workflow_operands",
                "slot_role_map",
                "threshold_regimes",
                "exceptions",
                "definitions",
                "obligation_graph",
                "neighbor_families",
                "evidence_requirements",
                "version",
                "provenance",
            ),
            label,
        )
        # 缺关键键时后续会 KeyError——那是结构崩坏，收集模式也不该硬吞。
        if "rule_card_id" not in card:
            continue
        _ensure(card["rule_card_id"] not in card_ids, f"duplicate rule_card_id: {card['rule_card_id']}")
        _validate_card(
            card,
            family_map,
            source_document_ids,
            page_counts,
            semantic_slot_map,
            measure_map,
            artifact_map,
            time_anchor_map,
            vocabularies,
        )
        card_ids.add(card["rule_card_id"])

    for family_id, family in family_map.items():
        declared = set(family["card_ids"])
        actual = {card["rule_card_id"] for card in (cards or []) if card.get("family_id") == family_id}
        _ensure(declared == actual, f"family_index.card_ids mismatch for {family_id}")

    derived = rebuild_derived_indexes(cards or [])
    _ensure(bundle.slot_index == derived["slot_index"], "slot_index.json does not match derived slot index")
    _ensure(
        bundle.threshold_regime_index == derived["threshold_regime_index"],
        "threshold_regime_index.json does not match derived threshold regime index",
    )
    _ensure(
        bundle.exception_definition_index == derived["exception_definition_index"],
        "exception_definition_index.json does not match derived exception/definition index",
    )
    return bundle


def collect_rulecard_bundle_violations(bundle_dir: Path) -> List[str]:
    """跑完整契约校验，返回**全部**违规文案（遇错继续，不早停）。

    与 `validate_rulecard_bundle` 同源；批跑闸用此函数一次列出全貌，
    再与显式豁免清单对账——禁止靠遇错即抛只看见第一条。
    """
    with _collecting_violations() as bucket:
        _validate_rulecard_bundle_body(bundle_dir)
    return list(bucket)


def validate_rulecard_bundle(bundle_dir: Path) -> RuleCardBundle:
    """校验卡包契约；有违规时一次抛出**全部**违规（不再遇错即停只报第一条）。"""
    with _collecting_violations() as bucket:
        bundle = _validate_rulecard_bundle_body(bundle_dir)
    if bucket:
        raise ValueError(
            f"rulecard bundle has {len(bucket)} contract violation(s):\n"
            + "\n".join(f"  - {message}" for message in bucket)
        )
    return bundle


def rebuild_rulecard_bundle_indexes(bundle_dir: Path) -> RuleCardBundle:
    bundle = load_rulecard_bundle(bundle_dir)
    derived = rebuild_derived_indexes(bundle.cards)
    files = bundle.manifest["files"]
    _write_json(bundle_dir / files["slot_index"], derived["slot_index"])
    _write_json(bundle_dir / files["threshold_regime_index"], derived["threshold_regime_index"])
    _write_json(bundle_dir / files["exception_definition_index"], derived["exception_definition_index"])
    return load_rulecard_bundle(bundle_dir)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or rebuild RuleCard v2 bundle assets.")
    parser.add_argument("command", choices=("validate", "rebuild"))
    parser.add_argument("bundle_dir", help="Absolute or relative path to the RuleCard v2 bundle directory.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    bundle_dir = Path(args.bundle_dir).resolve()
    if args.command == "rebuild":
        bundle = rebuild_rulecard_bundle_indexes(bundle_dir)
    else:
        bundle = validate_rulecard_bundle(bundle_dir)
    print(json.dumps(bundle.summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
