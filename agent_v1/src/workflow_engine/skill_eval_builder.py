from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.evidence_schema import DecisionTrace, EvidencePack  # noqa: E402
from workflow_engine.skill_candidate_schema import SkillCandidateDraft  # noqa: E402
from workflow_engine.skill_eval_schema import SkillEvalNotes, SkillEvalReport  # noqa: E402


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _iter_case_dirs(run_dir: Path) -> Iterable[Path]:
    cases_dir = run_dir / "cases"
    if not cases_dir.exists():
        return []
    return sorted(path for path in cases_dir.iterdir() if path.is_dir())


def _load_candidate_drafts(path: Path) -> List[SkillCandidateDraft]:
    drafts: List[SkillCandidateDraft] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            drafts.append(SkillCandidateDraft.model_validate(json.loads(line)))
    return drafts


def _load_case_payloads(run_dir: Path) -> Dict[str, tuple[EvidencePack, DecisionTrace]]:
    payloads: Dict[str, tuple[EvidencePack, DecisionTrace]] = {}
    for case_dir in _iter_case_dirs(run_dir):
        evidence_pack = EvidencePack.model_validate(_load_json(case_dir / "evidence_pack.json"))
        decision_trace = DecisionTrace.model_validate(_load_json(case_dir / "decision_trace.json"))
        payloads[evidence_pack.case_id] = (evidence_pack, decision_trace)
    return payloads


def _case_matches_trigger(evidence_pack: EvidencePack, trigger_id: str) -> bool:
    return any(
        item.trigger_id == trigger_id and item.matched
        for item in evidence_pack.seed_runtime.trigger_evaluation
    )


def _case_has_closure_block(evidence_pack: EvidencePack) -> bool:
    if not evidence_pack.closure_summary:
        return False
    return sum(evidence_pack.closure_summary.blocked_reason_counts.values()) > 0


def build_skill_eval_reports(
    *,
    run_dir: Path,
    drafts_path: Path | None = None,
) -> List[SkillEvalReport]:
    drafts_file = drafts_path or (run_dir / "skill_candidate_drafts.jsonl")
    drafts = _load_candidate_drafts(drafts_file)
    case_payloads = _load_case_payloads(run_dir=run_dir)

    reports: List[SkillEvalReport] = []
    for draft in drafts:
        evaluated_case_ids: List[str] = []
        closure_blocked_case_ids: List[str] = []
        decision_pass_count = 0
        decision_fail_count = 0
        allow_stop_true_count = 0
        allow_stop_false_count = 0

        for case_id in sorted(case_payloads):
            evidence_pack, decision_trace = case_payloads[case_id]
            if not _case_matches_trigger(evidence_pack=evidence_pack, trigger_id=draft.trigger_signature.trigger_id):
                continue
            evaluated_case_ids.append(case_id)
            if decision_trace.final_decision == "pass":
                decision_pass_count += 1
            elif decision_trace.final_decision == "fail":
                decision_fail_count += 1
            if evidence_pack.allow_stop is True:
                allow_stop_true_count += 1
            elif evidence_pack.allow_stop is False:
                allow_stop_false_count += 1
            if _case_has_closure_block(evidence_pack):
                closure_blocked_case_ids.append(case_id)

        matched_case_count = len(evaluated_case_ids)
        reports.append(
            SkillEvalReport(
                candidate_id=draft.candidate_id,
                trigger_id=draft.trigger_signature.trigger_id,
                evaluated_case_ids=evaluated_case_ids,
                matched_case_count=matched_case_count,
                decision_pass_count=decision_pass_count,
                decision_fail_count=decision_fail_count,
                allow_stop_true_count=allow_stop_true_count,
                allow_stop_false_count=allow_stop_false_count,
                closure_blocked_case_ids=closure_blocked_case_ids,
                status="evaluated",
                notes=SkillEvalNotes(
                    trigger_coverage_summary=(
                        f"Trigger coverage: matched_case_count={matched_case_count}, "
                        f"evaluated_case_ids={', '.join(evaluated_case_ids) if evaluated_case_ids else 'none'}."
                    ),
                    symbolic_result_summary=(
                        f"Symbolic results: decision_pass_count={decision_pass_count}, "
                        f"decision_fail_count={decision_fail_count}, "
                        f"allow_stop_true_count={allow_stop_true_count}, "
                        f"allow_stop_false_count={allow_stop_false_count}."
                    ),
                    closure_risk_summary=(
                        f"Closure risks: blocked_case_count={len(closure_blocked_case_ids)}, "
                        f"closure_blocked_case_ids={', '.join(closure_blocked_case_ids) if closure_blocked_case_ids else 'none'}."
                    ),
                ),
            )
        )
    return reports


def write_skill_eval_reports(
    *,
    run_dir: Path,
    drafts_path: Path | None = None,
    output_path: Path | None = None,
) -> tuple[Path, Path]:
    reports = build_skill_eval_reports(run_dir=run_dir, drafts_path=drafts_path)
    out_path = output_path or (run_dir / "SkillEvalReport.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([item.model_dump() for item in reports], f, ensure_ascii=False, indent=2)

    schema_path = out_path.with_name("SkillEvalReport.schema.json")
    with schema_path.open("w", encoding="utf-8") as f:
        json.dump(SkillEvalReport.model_json_schema(), f, ensure_ascii=False, indent=2)
    return out_path, schema_path
