from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import EvidencePack  # noqa: E402
from workflow_engine.trigger_routing_schema import (  # noqa: E402
    CandidateReductionIfTopK,
    RoutingContext,
    RoutingTraceDataset,
    RoutingTraceRow,
    RoutingTriggerTrace,
    ShadowRoutingReport,
    TriggerRanker,
)

_FIXED_CANDIDATE_SET = ["TR-001", "TR-002", "TR-003"]
_NO_TRIGGER = "NO_TRIGGER"
_FEATURE_WEIGHT = 1.0
_PATTERN_WEIGHT = 2.0


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _iter_case_dirs(run_dir: Path) -> Iterable[Path]:
    cases_dir = run_dir / "cases"
    if not cases_dir.exists():
        return []
    return sorted(path for path in cases_dir.iterdir() if path.is_dir())


def _load_evidence_pack(path: Path) -> EvidencePack:
    return EvidencePack.model_validate(_load_json(path))


def _matched_trigger_ids(evidence_pack: EvidencePack) -> List[str]:
    return [
        item.trigger_id
        for item in evidence_pack.seed_runtime.trigger_evaluation
        if item.trigger_id in _FIXED_CANDIDATE_SET and item.matched
    ]


def _has_rule_seed_bridge_for_trigger(evidence_pack: EvidencePack, trigger_id: str) -> bool:
    for slot_map in evidence_pack.seed_runtime.rule_seed_bridge.values():
        for slot in slot_map.values():
            if trigger_id in slot.trigger_ids:
                return True
    return False


def _compute_reward(*, matched: bool, has_bridge: bool, evidence_pack: EvidencePack) -> float:
    if not matched:
        return 0.0
    reward = 0.5
    if has_bridge:
        reward += 0.3
    if evidence_pack.closure_summary is not None:
        reward += 0.2
        blocked_total = sum(evidence_pack.closure_summary.blocked_reason_counts.values())
        if blocked_total > 0:
            reward -= 0.2
    return max(0.0, min(1.0, round(reward, 4)))


def build_routing_trace_dataset(*, run_dirs: List[Path]) -> RoutingTraceDataset:
    rows: List[RoutingTraceRow] = []
    source_run_ids = sorted(path.name for path in run_dirs)
    for run_dir in sorted(run_dirs, key=lambda path: path.name):
        run_id = run_dir.name
        for case_dir in _iter_case_dirs(run_dir):
            evidence_pack = _load_evidence_pack(case_dir / "evidence_pack.json")
            matched_trigger_ids = _matched_trigger_ids(evidence_pack)
            chosen_action = matched_trigger_ids[0] if matched_trigger_ids else _NO_TRIGGER
            has_bridge = (
                chosen_action != _NO_TRIGGER
                and _has_rule_seed_bridge_for_trigger(evidence_pack=evidence_pack, trigger_id=chosen_action)
            )
            rows.append(
                RoutingTraceRow(
                    source_run_id=run_id,
                    phase=evidence_pack.phase,
                    case_id=evidence_pack.case_id,
                    routing_point_id=f"{run_id}:{evidence_pack.case_id}:trigger_routing_v1",
                    context=RoutingContext(
                        matched_feature_ids=list(evidence_pack.seed_runtime.matched_feature_ids),
                        matched_pattern_ids=list(evidence_pack.seed_runtime.matched_pattern_ids),
                        trigger_evaluation=[
                            RoutingTriggerTrace(
                                trigger_id=item.trigger_id,
                                matched=item.matched,
                                missing_required_feature_ids=list(item.missing_required_feature_ids),
                                missing_required_pattern_ids=list(item.missing_required_pattern_ids),
                                blocked_negative_feature_ids=list(item.blocked_negative_feature_ids),
                            )
                            for item in evidence_pack.seed_runtime.trigger_evaluation
                            if item.trigger_id in _FIXED_CANDIDATE_SET
                        ],
                        closure_summary={
                            "allow_stop": evidence_pack.allow_stop,
                            "blocked_reason_counts": dict(
                                evidence_pack.closure_summary.blocked_reason_counts
                            )
                            if evidence_pack.closure_summary
                            else {},
                            "high_risk_open_count": (
                                evidence_pack.closure_summary.high_risk_open_count
                                if evidence_pack.closure_summary
                                else 0
                            ),
                            "stop_reason": (
                                evidence_pack.closure_summary.stop_reason
                                if evidence_pack.closure_summary
                                else ""
                            ),
                        },
                    ),
                    candidate_set=list(_FIXED_CANDIDATE_SET),
                    chosen_action=chosen_action,
                    reward=_compute_reward(
                        matched=chosen_action != _NO_TRIGGER,
                        has_bridge=has_bridge,
                        evidence_pack=evidence_pack,
                    ),
                    materialized_rule_seed_bridge=has_bridge,
                    source_refs=[
                        (Path(run_id) / "cases" / evidence_pack.case_id / "evidence_pack.json").as_posix(),
                        (Path(run_id) / "cases" / evidence_pack.case_id / "decision_trace.json").as_posix(),
                        (Path(run_id) / "cases" / evidence_pack.case_id / "seed_runtime.json").as_posix(),
                    ],
                )
            )
    return RoutingTraceDataset(
        version="v1",
        source_run_ids=source_run_ids,
        candidate_set=list(_FIXED_CANDIDATE_SET),
        rows=rows,
    )


def build_trigger_ranker(*, dataset: RoutingTraceDataset) -> TriggerRanker:
    positive_rows = [row for row in dataset.rows if row.chosen_action in _FIXED_CANDIDATE_SET]
    positive_count = len(positive_rows)
    action_counts = Counter(row.chosen_action for row in positive_rows)
    feature_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    pattern_counts: Dict[str, Counter[str]] = defaultdict(Counter)

    for row in positive_rows:
        for feature_id in sorted(set(row.context.matched_feature_ids)):
            feature_counts[feature_id][row.chosen_action] += 1
        for pattern_id in sorted(set(row.context.matched_pattern_ids)):
            pattern_counts[pattern_id][row.chosen_action] += 1

    prior_scores = {
        trigger_id: round(action_counts.get(trigger_id, 0) / positive_count, 6) if positive_count else 0.0
        for trigger_id in _FIXED_CANDIDATE_SET
    }
    feature_scores = {
        feature_id: {
            trigger_id: round(
                count / action_counts[trigger_id],
                6,
            )
            for trigger_id, count in sorted(counter.items())
            if action_counts[trigger_id] > 0
        }
        for feature_id, counter in sorted(feature_counts.items())
    }
    pattern_scores = {
        pattern_id: {
            trigger_id: round(
                count / action_counts[trigger_id],
                6,
            )
            for trigger_id, count in sorted(counter.items())
            if action_counts[trigger_id] > 0
        }
        for pattern_id, counter in sorted(pattern_counts.items())
    }

    return TriggerRanker(
        version="v1",
        candidate_set=list(_FIXED_CANDIDATE_SET),
        trained_row_count=len(dataset.rows),
        trained_positive_row_count=positive_count,
        prior_scores=prior_scores,
        feature_scores=feature_scores,
        pattern_scores=pattern_scores,
        feature_weight=_FEATURE_WEIGHT,
        pattern_weight=_PATTERN_WEIGHT,
        scoring_formula="prior_score + feature_weight*feature_score + pattern_weight*pattern_score",
    )


def rank_row(*, row: RoutingTraceRow, ranker: TriggerRanker) -> List[str]:
    def score(trigger_id: str) -> float:
        total = ranker.prior_scores.get(trigger_id, 0.0)
        total += ranker.feature_weight * sum(
            ranker.feature_scores.get(feature_id, {}).get(trigger_id, 0.0)
            for feature_id in row.context.matched_feature_ids
        )
        total += ranker.pattern_weight * sum(
            ranker.pattern_scores.get(pattern_id, {}).get(trigger_id, 0.0)
            for pattern_id in row.context.matched_pattern_ids
        )
        return round(total, 6)

    return sorted(ranker.candidate_set, key=lambda trigger_id: (-score(trigger_id), trigger_id))


def _has_clean_closure(row: RoutingTraceRow) -> bool:
    return (
        row.context.closure_summary.allow_stop is True
        and sum(row.context.closure_summary.blocked_reason_counts.values()) == 0
    )


def build_shadow_routing_report(
    *,
    dataset: RoutingTraceDataset,
    ranker: TriggerRanker,
    dataset_ref: str,
    ranker_ref: str,
) -> ShadowRoutingReport:
    positive_rows = [row for row in dataset.rows if row.chosen_action in _FIXED_CANDIDATE_SET]
    non_routable_rows = [row for row in dataset.rows if row.chosen_action == _NO_TRIGGER]

    top1_hits = 0
    top2_hits = 0
    closure_regression_count = 0
    for row in positive_rows:
        ranking = rank_row(row=row, ranker=ranker)
        if ranking[0] == row.chosen_action:
            top1_hits += 1
        elif _has_clean_closure(row):
            closure_regression_count += 1
        if row.chosen_action in ranking[:2]:
            top2_hits += 1

    positive_count = len(positive_rows)
    observed_positive_counts = {
        trigger_id: sum(1 for row in positive_rows if row.chosen_action == trigger_id)
        for trigger_id in _FIXED_CANDIDATE_SET
    }

    notes: List[str] = []
    if non_routable_rows:
        notes.append(
            f"{len(non_routable_rows)}/{len(dataset.rows)} rows are NO_TRIGGER; current shadow ranker has no abstain path and falls back to priors."
        )
    for trigger_id, count in observed_positive_counts.items():
        if count == 0:
            notes.append(f"{trigger_id} has 0 positive rows in the frozen dataset, so the ranker cannot learn a positive routing preference for it.")
    notes.append(
        "The experiment replays mirrored Phase A/B fullreg runs; metrics show deterministic replay signal, not held-out generalization."
    )

    top1_hit_rate = round(top1_hits / positive_count, 4) if positive_count else 0.0
    top2_coverage = round(top2_hits / positive_count, 4) if positive_count else 0.0
    conclusion = (
        "learning_signal_present"
        if positive_count > 0
        and len([trigger_id for trigger_id, count in observed_positive_counts.items() if count > 0]) >= 2
        and top1_hit_rate >= 0.8
        else "signal_insufficient"
    )

    return ShadowRoutingReport(
        version="v1",
        dataset_row_count=len(dataset.rows),
        routable_row_count=positive_count,
        non_routable_row_count=len(non_routable_rows),
        observed_positive_counts=observed_positive_counts,
        top1_hit_rate=top1_hit_rate,
        top2_coverage=top2_coverage,
        candidate_reduction_if_topk=CandidateReductionIfTopK(
            top1=round(1 - (1 / len(_FIXED_CANDIDATE_SET)), 4),
            top2=round(1 - (2 / len(_FIXED_CANDIDATE_SET)), 4),
        ),
        closure_regression_count=closure_regression_count,
        notes_on_failure_modes=notes,
        conclusion=conclusion,
        dataset_ref=dataset_ref,
        ranker_ref=ranker_ref,
    )


def write_phaseb_trigger_routing_experiment(
    *,
    run_dirs: List[Path],
    output_dir: Path,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    dataset = build_routing_trace_dataset(run_dirs=run_dirs)
    ranker = build_trigger_ranker(dataset=dataset)
    dataset_path = output_dir / "RoutingTraceDataset.json"
    ranker_path = output_dir / "TriggerRanker.v1.json"
    report_path = output_dir / "ShadowRoutingReport.json"
    dataset_schema_path = output_dir / "RoutingTraceDataset.schema.json"
    ranker_schema_path = output_dir / "TriggerRanker.v1.schema.json"
    report_schema_path = output_dir / "ShadowRoutingReport.schema.json"

    output_dir.mkdir(parents=True, exist_ok=True)

    with dataset_path.open("w", encoding="utf-8") as f:
        json.dump(dataset.model_dump(), f, ensure_ascii=False, indent=2)
    with ranker_path.open("w", encoding="utf-8") as f:
        json.dump(ranker.model_dump(), f, ensure_ascii=False, indent=2)

    report = build_shadow_routing_report(
        dataset=dataset,
        ranker=ranker,
        dataset_ref=dataset_path.name,
        ranker_ref=ranker_path.name,
    )
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)

    with dataset_schema_path.open("w", encoding="utf-8") as f:
        json.dump(RoutingTraceDataset.model_json_schema(), f, ensure_ascii=False, indent=2)
    with ranker_schema_path.open("w", encoding="utf-8") as f:
        json.dump(TriggerRanker.model_json_schema(), f, ensure_ascii=False, indent=2)
    with report_schema_path.open("w", encoding="utf-8") as f:
        json.dump(ShadowRoutingReport.model_json_schema(), f, ensure_ascii=False, indent=2)

    return (
        dataset_path,
        dataset_schema_path,
        ranker_path,
        ranker_schema_path,
        report_path,
        report_schema_path,
    )
