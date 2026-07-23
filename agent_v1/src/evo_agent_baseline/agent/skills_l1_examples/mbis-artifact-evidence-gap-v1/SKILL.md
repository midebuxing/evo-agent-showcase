# artifact evidence gap retrieval macro

## Purpose
Use this retrieval macro when artifact or report-field obligations remain open because required artifact evidence was not found in sidecar entries or fact KG. The goal is to expand candidate coverage for artifact / sidecar lookup before report generation, so that downstream closure verifier has more signal to either close the obligation or to record a precise open reason.

## Trigger
- `open_reason_code` is `missing_artifact_evidence` or `missing_sidecar_entry`
- `obligation_kind` is `artifact`, `evidence`, or `report_field`
- `rule_family` is in MBIS reporting or submission families

## Allowed actions
- `inspect_obligation` for each open obligation matched by the trigger
- `retrieve_building_facts` filtered by sidecar carrier and matched artifact / slot keys
- `retrieve_applicable_rules` with neighbor expansion on the source rule family
- `append_candidates` only (never `remove_candidate`)

## Retrieval / routing plan
See `plan.yaml`. The plan runs three steps:

1. inspect the open obligation to extract `artifact_keys` and `slot_ids`;
2. expand sidecar fact lookup along those keys;
3. expand neighbor rule cards in the same rule family.

Each step writes its outputs as additional candidates without removing existing ones, and the verifier candidate floor is preserved.

## Fallback
If any guard fails (pre_skill_runtime_load_guard, pre_skill_candidate_guard, or post_evo_writeback_audit), disable this skill for the run and continue with CoreSkills. The run-level fallback is reported via `fallback_reason="skill_guard_disabled"`.

## Safety and authority boundary
This Skill is non-authoritative. It only changes retrieval ordering and expands evidence lookup; it does not modify allow_stop, closure_status, satisfaction_status, or any verifier output. It does not access evaluator-only data, does not write to the fact KG, and does not write to the rule_card KG. The closure verifier remains the only authority that decides `allow_stop`, and the report writer remains the only component allowed to produce the final report skeleton.

## Do not
- Do not emit final verdict or any final-compliance phrasing.
- Do not force `allow_stop`.
- Do not suppress rule candidates returned by RuleCard KG-RAG.
- Do not use evaluator truth, projections, or any W2 reference outputs.
- Do not introduce building / world / run literal ids into the trigger or plan.
