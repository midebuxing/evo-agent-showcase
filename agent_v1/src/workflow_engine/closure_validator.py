from __future__ import annotations

import operator
import re
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Sequence, Tuple, Union

from workflow_engine.evidence_schema import FactItem, FactPack, RuleCard
from workflow_engine.obligation_schema import (
    BlockedReasonCode,
    ClosureSummary,
    ClosureValidationResult,
    Obligation,
    ObligationStatus,
    ObligationType,
)

RuleCardLike = Union[RuleCard, Mapping[str, Any]]
FactPackLike = Union[FactPack, Mapping[str, Any]]

_COMPARATORS: Dict[str, Any] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}
_TYPE_ORDER: Dict[ObligationType, int] = {
    "prerequisite": 0,
    "exception": 1,
    "definition": 2,
    "threshold": 3,
}
_HIGH_RISK_BLOCKED_REASONS: Tuple[BlockedReasonCode, ...] = (
    "missing_fact",
    "missing_rule_edge",
    "unsupported_case",
)


def validate_closure(
    rule_cards: Sequence[RuleCardLike],
    fact_pack: FactPackLike,
    seed_rule_bridge: Mapping[str, Mapping[str, Mapping[str, Sequence[str]]]] | None = None,
) -> ClosureValidationResult:
    rule_models = [card if isinstance(card, RuleCard) else RuleCard.model_validate(card) for card in rule_cards]
    fact_pack_model = fact_pack if isinstance(fact_pack, FactPack) else FactPack.model_validate(fact_pack)

    fact_index = _build_fact_index(fact_pack_model)
    obligations: List[Obligation] = []
    for rule in sorted(rule_models, key=lambda item: item.rule_id):
        obligations.extend(
            _build_rule_obligations(
                rule=rule,
                fact_index=fact_index,
                seed_rule_bridge=seed_rule_bridge or {},
            )
        )

    obligations = sorted(
        obligations,
        key=lambda item: (item.source_rule_id, _TYPE_ORDER[item.type], item.obligation_id),
    )

    unmet_obligations = [item for item in obligations if item.status != "supported"]
    high_risk_open_count = _count_high_risk_unmet(unmet_obligations)
    allow_stop = high_risk_open_count == 0

    closure_summary = _build_closure_summary(
        obligations=obligations,
        high_risk_open_count=high_risk_open_count,
        allow_stop=allow_stop,
    )

    return ClosureValidationResult(
        obligations=obligations,
        allow_stop=allow_stop,
        closure_summary=closure_summary,
        unmet_obligations=unmet_obligations,
    )


def _build_rule_obligations(
    *,
    rule: RuleCard,
    fact_index: Mapping[str, List[FactItem]],
    seed_rule_bridge: Mapping[str, Mapping[str, Mapping[str, Sequence[str]]]],
) -> List[Obligation]:
    obligations: List[Obligation] = []
    rule_seed_bridge = seed_rule_bridge.get(rule.rule_id, {})

    prerequisite_slots = _extract_slots(rule=rule, slot_type="prerequisite")
    if not prerequisite_slots:
        prerequisite_slots = sorted({condition.fact_key for condition in rule.conditions if condition.fact_key})
    obligations.append(
        _evaluate_slot_obligation(
            rule_id=rule.rule_id,
            obligation_type="prerequisite",
            obligation_suffix="prerequisite",
            required_slots=prerequisite_slots,
            fact_index=fact_index,
            rule_seed_bridge=rule_seed_bridge,
        )
    )

    exception_slots = _extract_slots(rule=rule, slot_type="exception")
    obligations.append(
        _evaluate_slot_obligation(
            rule_id=rule.rule_id,
            obligation_type="exception",
            obligation_suffix="exception",
            required_slots=exception_slots,
            fact_index=fact_index,
            rule_seed_bridge=rule_seed_bridge,
        )
    )

    definition_slots = _extract_slots(rule=rule, slot_type="definition")
    obligations.append(
        _evaluate_slot_obligation(
            rule_id=rule.rule_id,
            obligation_type="definition",
            obligation_suffix="definition",
            required_slots=definition_slots,
            fact_index=fact_index,
            rule_seed_bridge=rule_seed_bridge,
        )
    )

    if not rule.conditions:
        obligations.append(
            Obligation(
                obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix="threshold-0"),
                source_rule_id=rule.rule_id,
                type="threshold",
                required_fact_slots=[],
                status="blocked",
                blocked_reason_code="missing_rule_edge",
                evidence_refs=[],
                notes="Rule has no threshold condition to evaluate.",
            )
        )
        return obligations

    for idx, condition in enumerate(rule.conditions, start=1):
        slot = condition.fact_key
        evidence_refs = [fact.fact_id for fact in fact_index.get(slot, [])]
        seed_note = _build_seed_bridge_note(required_slots=[slot], rule_seed_bridge=rule_seed_bridge)
        if slot not in fact_index:
            obligations.append(
                Obligation(
                    obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix=f"threshold-{idx}"),
                    source_rule_id=rule.rule_id,
                    type="threshold",
                    required_fact_slots=[slot],
                    status="blocked",
                    blocked_reason_code="missing_fact",
                    evidence_refs=evidence_refs,
                    notes=_append_seed_note(f"Missing fact slot: {slot}", seed_note),
                )
            )
            continue

        observed_value = fact_index[slot][0].value
        if observed_value is None:
            obligations.append(
                Obligation(
                    obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix=f"threshold-{idx}"),
                    source_rule_id=rule.rule_id,
                    type="threshold",
                    required_fact_slots=[slot],
                    status="unknown",
                    evidence_refs=evidence_refs,
                    notes=_append_seed_note(f"Observed value is None for slot: {slot}", seed_note),
                )
            )
            continue

        comparator_fn = _COMPARATORS.get(condition.comparator)
        if comparator_fn is None:
            obligations.append(
                Obligation(
                    obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix=f"threshold-{idx}"),
                    source_rule_id=rule.rule_id,
                    type="threshold",
                    required_fact_slots=[slot],
                    status="blocked",
                    blocked_reason_code="unsupported_case",
                    evidence_refs=evidence_refs,
                    notes=_append_seed_note(f"Unsupported comparator: {condition.comparator}", seed_note),
                )
            )
            continue

        try:
            passed = bool(comparator_fn(observed_value, condition.threshold))
        except Exception as exc:
            obligations.append(
                Obligation(
                    obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix=f"threshold-{idx}"),
                    source_rule_id=rule.rule_id,
                    type="threshold",
                    required_fact_slots=[slot],
                    status="blocked",
                    blocked_reason_code="unsupported_case",
                    evidence_refs=evidence_refs,
                    notes=_append_seed_note(f"Threshold comparison failed: {exc}", seed_note),
                )
            )
            continue

        obligations.append(
            Obligation(
                obligation_id=_make_obligation_id(rule_id=rule.rule_id, suffix=f"threshold-{idx}"),
                source_rule_id=rule.rule_id,
                type="threshold",
                required_fact_slots=[slot],
                status="supported" if passed else "contradicted",
                evidence_refs=evidence_refs,
                notes=_append_seed_note(f"{observed_value} {condition.comparator} {condition.threshold}", seed_note),
            )
        )

    return obligations


def _evaluate_slot_obligation(
    *,
    rule_id: str,
    obligation_type: ObligationType,
    obligation_suffix: str,
    required_slots: Sequence[str],
    fact_index: Mapping[str, List[FactItem]],
    rule_seed_bridge: Mapping[str, Mapping[str, Sequence[str]]],
) -> Obligation:
    slot_list = sorted({slot for slot in required_slots if slot})
    seed_note = _build_seed_bridge_note(required_slots=slot_list, rule_seed_bridge=rule_seed_bridge)
    evidence_refs: List[str] = []
    for slot in slot_list:
        evidence_refs.extend(fact.fact_id for fact in fact_index.get(slot, []))
    evidence_refs = sorted(set(evidence_refs))

    if not slot_list:
        return Obligation(
            obligation_id=_make_obligation_id(rule_id=rule_id, suffix=obligation_suffix),
            source_rule_id=rule_id,
            type=obligation_type,
            required_fact_slots=[],
            status="blocked",
            blocked_reason_code="missing_rule_edge",
            evidence_refs=[],
            notes=_append_seed_note(
                f"No configured {obligation_type} slots in rule definition.",
                seed_note,
            ),
        )

    missing_slots = [slot for slot in slot_list if slot not in fact_index]
    if missing_slots:
        return Obligation(
            obligation_id=_make_obligation_id(rule_id=rule_id, suffix=obligation_suffix),
            source_rule_id=rule_id,
            type=obligation_type,
            required_fact_slots=slot_list,
            status="blocked",
            blocked_reason_code="missing_fact",
            evidence_refs=evidence_refs,
            notes=_append_seed_note(f"Missing fact slots: {', '.join(missing_slots)}", seed_note),
        )

    first_values = {slot: fact_index[slot][0].value for slot in slot_list}
    if any(value is None for value in first_values.values()):
        return Obligation(
            obligation_id=_make_obligation_id(rule_id=rule_id, suffix=obligation_suffix),
            source_rule_id=rule_id,
            type=obligation_type,
            required_fact_slots=slot_list,
            status="unknown",
            evidence_refs=evidence_refs,
            notes=_append_seed_note(f"{obligation_type} contains None value slot.", seed_note),
        )

    status: ObligationStatus = "supported"
    notes = "All required slots are present."

    if obligation_type == "prerequisite":
        failed_slots = [slot for slot, value in first_values.items() if isinstance(value, bool) and value is False]
        if failed_slots:
            status = "contradicted"
            notes = f"Prerequisite is false for slots: {', '.join(failed_slots)}"
    elif obligation_type == "exception":
        triggered_slots = [slot for slot, value in first_values.items() if bool(value)]
        if triggered_slots:
            status = "contradicted"
            notes = f"Exception triggered by slots: {', '.join(triggered_slots)}"
        else:
            notes = "No exception slot is triggered."
    elif obligation_type == "definition":
        empty_slots = [slot for slot, value in first_values.items() if value == ""]
        if empty_slots:
            status = "unknown"
            notes = f"Definition slots are empty: {', '.join(empty_slots)}"
        else:
            notes = "Definition slots are populated."

    return Obligation(
        obligation_id=_make_obligation_id(rule_id=rule_id, suffix=obligation_suffix),
        source_rule_id=rule_id,
        type=obligation_type,
        required_fact_slots=slot_list,
        status=status,
        evidence_refs=evidence_refs,
        notes=_append_seed_note(notes, seed_note),
    )


def _extract_slots(*, rule: RuleCard, slot_type: str) -> List[str]:
    text_parts = [rule.title or "", rule.rationale or ""]
    text = " ".join(part for part in text_parts if part).strip()
    if not text:
        return []

    slot_list_pattern = r"([a-zA-Z0-9_.-]+(?:\s*[,|]\s*[a-zA-Z0-9_.-]+)*)"
    patterns = [
        rf"closure\.{slot_type}_slots\s*[:=]\s*{slot_list_pattern}",
        rf"{slot_type}_slots\s*[:=]\s*{slot_list_pattern}",
        rf"\[{slot_type}\s*:\s*([^\]]+)\]",
    ]
    for pattern in patterns:
        matched = re.search(pattern, text, re.IGNORECASE)
        if not matched:
            continue
        raw = matched.group(1).strip()
        if not raw:
            continue
        slots = [token.strip() for token in re.split(r"[,|]", raw) if token.strip()]
        return sorted(set(slots))
    return []


def _build_fact_index(fact_pack: FactPack) -> Dict[str, List[FactItem]]:
    index: Dict[str, List[FactItem]] = defaultdict(list)
    for fact in fact_pack.facts:
        index[fact.key].append(fact)
    for key in index:
        index[key] = sorted(index[key], key=lambda item: item.fact_id)
    return dict(index)


def _build_seed_bridge_note(
    *,
    required_slots: Sequence[str],
    rule_seed_bridge: Mapping[str, Mapping[str, Sequence[str]]],
) -> str:
    parts: List[str] = []
    for slot in required_slots:
        bridge = rule_seed_bridge.get(slot)
        if not bridge:
            continue
        feature_ids = ", ".join(bridge.get("feature_ids", []))
        pattern_ids = ", ".join(bridge.get("pattern_ids", []))
        trigger_ids = ", ".join(bridge.get("trigger_ids", []))
        details: List[str] = []
        if feature_ids:
            details.append(f"features[{feature_ids}]")
        if pattern_ids:
            details.append(f"patterns[{pattern_ids}]")
        if trigger_ids:
            details.append(f"triggers[{trigger_ids}]")
        if details:
            parts.append(f"{slot} <- " + ", ".join(details))
    if not parts:
        return ""
    return "Seed bridge: " + "; ".join(parts) + "."


def _append_seed_note(base: str, seed_note: str) -> str:
    if not seed_note:
        return base
    return f"{base} {seed_note}"


def _count_high_risk_unmet(unmet_obligations: Sequence[Obligation]) -> int:
    count = 0
    for obligation in unmet_obligations:
        if obligation.status in ("contradicted", "unknown"):
            count += 1
            continue
        if (
            obligation.status == "blocked"
            and obligation.blocked_reason_code in _HIGH_RISK_BLOCKED_REASONS
        ):
            count += 1
    return count


def _build_closure_summary(
    *,
    obligations: Sequence[Obligation],
    high_risk_open_count: int,
    allow_stop: bool,
) -> ClosureSummary:
    status_counts: Dict[ObligationStatus, int] = {
        "supported": 0,
        "contradicted": 0,
        "unknown": 0,
        "blocked": 0,
    }
    type_counts: Dict[ObligationType, int] = {
        "prerequisite": 0,
        "exception": 0,
        "definition": 0,
        "threshold": 0,
    }
    blocked_reason_counts: Dict[BlockedReasonCode, int] = {
        "missing_fact": 0,
        "missing_rule_edge": 0,
        "unsupported_case": 0,
    }

    open_obligations_count = 0
    for obligation in obligations:
        status_counts[obligation.status] += 1
        type_counts[obligation.type] += 1
        if obligation.status != "supported":
            open_obligations_count += 1
        if obligation.status == "blocked" and obligation.blocked_reason_code:
            blocked_reason_counts[obligation.blocked_reason_code] += 1

    high_risk_reason_counts: Dict[BlockedReasonCode, int] = {
        key: blocked_reason_counts[key]
        for key in _HIGH_RISK_BLOCKED_REASONS
        if blocked_reason_counts[key] > 0
    }

    if allow_stop and open_obligations_count == 0:
        stop_reason = "All obligations are supported."
    elif allow_stop:
        stop_reason = "Only low-risk blocked obligations remain."
    else:
        if high_risk_reason_counts:
            details = ", ".join(f"{key}={value}" for key, value in sorted(high_risk_reason_counts.items()))
            stop_reason = f"High-risk open obligations remain ({details})."
        else:
            stop_reason = "High-risk open obligations remain."

    return ClosureSummary(
        total_obligations=len(obligations),
        open_obligations_count=open_obligations_count,
        high_risk_open_count=high_risk_open_count,
        status_counts=status_counts,
        type_counts=type_counts,
        blocked_reason_counts=blocked_reason_counts,
        stop_reason=stop_reason,
    )


def _make_obligation_id(*, rule_id: str, suffix: str) -> str:
    normalized_rule = re.sub(r"[^a-zA-Z0-9]+", "-", rule_id).strip("-").lower()
    normalized_suffix = re.sub(r"[^a-zA-Z0-9]+", "-", suffix).strip("-").lower()
    return f"obl-{normalized_rule}-{normalized_suffix}"
