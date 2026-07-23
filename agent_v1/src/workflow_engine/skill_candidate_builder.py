from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import EvidencePack  # noqa: E402
from workflow_engine.fact_trigger_contract import load_seed_trigger_specs  # noqa: E402
from workflow_engine.skill_candidate_schema import (  # noqa: E402
    SkillCandidateDraft,
    SkillCandidateMetrics,
    TriggerSignature,
)

TRIGGER_SPEC_PATH = PROJECT_ROOT / "experiments" / "seed_trigger_specs_v1.json"

_SUPPORTED_TRIGGER_CONFIGS: Dict[str, Dict[str, List[str] | str]] = {
    "TR-001": {
        "candidate_id": "scd-tr-001-fp-001",
        "target_rule_ids": ["RC-CRACK-WIDTH"],
        "procedure_steps": [
            "Detect the structural crack seed path from the frozen trigger signature.",
            "Load the crack-width rule card before making any planning suggestion.",
            "Verify the crack width fact slot and preserve the seed bridge provenance.",
            "Keep the symbolic verdict outside the draft and leave final pass/fail to the verifier.",
        ],
        "guardrails": [
            "Do not emit final Pass/Fail from the draft.",
            "Require symbolic comparison on crack_width_mm before any downstream recommendation.",
            "Keep provenance links to decision_trace.json for replay and audit.",
        ],
    },
    "TR-002": {
        "candidate_id": "scd-tr-002-fp-004",
        "target_rule_ids": ["RC-REBAR-EXPOSED", "RC-SPALL-AREA"],
        "procedure_steps": [
            "Detect the composite rebar-and-spall seed path from the frozen trigger signature.",
            "Load both rebar exposure and spalling area rule cards before planning next actions.",
            "Verify has_rebar_exposed and spalling_area_m2 while preserving the explicit seed bridge.",
            "Keep the symbolic verdict outside the draft and leave final pass/fail to the verifier.",
        ],
        "guardrails": [
            "Do not emit final Pass/Fail from the draft.",
            "Require symbolic checks for both has_rebar_exposed and spalling_area_m2.",
            "Keep provenance links to decision_trace.json for replay and audit.",
        ],
    },
}


@dataclass
class _DraftAccumulator:
    provenance_case_ids: set[str] = field(default_factory=set)
    provenance_trace_refs: set[str] = field(default_factory=set)
    decision_pass_count: int = 0
    decision_fail_count: int = 0
    allow_stop_true_count: int = 0
    allow_stop_false_count: int = 0


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_evidence_pack(case_dir: Path) -> EvidencePack:
    return EvidencePack.model_validate(_load_json(case_dir / "evidence_pack.json"))


def _iter_case_dirs(run_dir: Path) -> Iterable[Path]:
    cases_dir = run_dir / "cases"
    if not cases_dir.exists():
        return []
    return sorted(path for path in cases_dir.iterdir() if path.is_dir())


def build_skill_candidate_drafts(run_dir: Path) -> List[SkillCandidateDraft]:
    trigger_specs = {
        spec.trigger_id: spec
        for spec in load_seed_trigger_specs(TRIGGER_SPEC_PATH)
        if spec.trigger_id in _SUPPORTED_TRIGGER_CONFIGS
    }
    accumulators: Dict[str, _DraftAccumulator] = {}

    for case_dir in _iter_case_dirs(run_dir):
        evidence_pack = _load_evidence_pack(case_dir)
        for evaluation in evidence_pack.seed_runtime.trigger_evaluation:
            if not evaluation.matched:
                continue
            if evaluation.trigger_id not in _SUPPORTED_TRIGGER_CONFIGS:
                continue

            accumulator = accumulators.setdefault(evaluation.trigger_id, _DraftAccumulator())
            accumulator.provenance_case_ids.add(evidence_pack.case_id)
            accumulator.provenance_trace_refs.add(
                (Path("cases") / evidence_pack.case_id / "decision_trace.json").as_posix()
            )
            if evidence_pack.decision_trace.final_decision == "pass":
                accumulator.decision_pass_count += 1
            elif evidence_pack.decision_trace.final_decision == "fail":
                accumulator.decision_fail_count += 1
            if evidence_pack.allow_stop is True:
                accumulator.allow_stop_true_count += 1
            elif evidence_pack.allow_stop is False:
                accumulator.allow_stop_false_count += 1

    drafts: List[SkillCandidateDraft] = []
    for trigger_id in sorted(accumulators):
        spec = trigger_specs[trigger_id]
        config = _SUPPORTED_TRIGGER_CONFIGS[trigger_id]
        accumulator = accumulators[trigger_id]
        drafts.append(
            SkillCandidateDraft(
                candidate_id=str(config["candidate_id"]),
                skill_type="strategy",
                trigger_signature=TriggerSignature(
                    trigger_id=trigger_id,
                    matched_feature_ids=list(spec.fact_predicates.required_feature_ids),
                    matched_pattern_ids=list(spec.fact_predicates.required_pattern_ids),
                ),
                target_rule_ids=list(config["target_rule_ids"]),
                procedure_steps=list(config["procedure_steps"]),
                guardrails=list(config["guardrails"]),
                provenance_case_ids=sorted(accumulator.provenance_case_ids),
                provenance_trace_refs=sorted(accumulator.provenance_trace_refs),
                state="candidate",
                metrics=SkillCandidateMetrics(
                    matched_case_count=len(accumulator.provenance_case_ids),
                    decision_pass_count=accumulator.decision_pass_count,
                    decision_fail_count=accumulator.decision_fail_count,
                    allow_stop_true_count=accumulator.allow_stop_true_count,
                    allow_stop_false_count=accumulator.allow_stop_false_count,
                ),
            )
        )
    return drafts


def write_skill_candidate_drafts(
    *,
    run_dir: Path,
    output_path: Path | None = None,
) -> tuple[Path, Path]:
    drafts = build_skill_candidate_drafts(run_dir=run_dir)
    out_path = output_path or (run_dir / "skill_candidate_drafts.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for draft in drafts:
            f.write(json.dumps(draft.model_dump(), ensure_ascii=False) + "\n")

    schema_path = out_path.with_name("SkillCandidateDraft.schema.json")
    with schema_path.open("w", encoding="utf-8") as f:
        json.dump(SkillCandidateDraft.model_json_schema(), f, ensure_ascii=False, indent=2)
    return out_path, schema_path
