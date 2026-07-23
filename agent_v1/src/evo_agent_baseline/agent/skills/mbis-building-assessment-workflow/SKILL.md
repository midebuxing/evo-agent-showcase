---
name: mbis-building-assessment-workflow
description: 'Orchestrate one MBIS compliance assessment run for a user-specified building. Use when user asks to review / assess / closure-verify a specific building (building_id + world_id). Output: ComplianceAssessmentRun with either auxiliary review report when allow_stop is true, or incomplete-closure notice when allow_stop is false.'
---

# MBIS building assessment workflow

## Instructions

Use only for a user-specified `world_id` + `building_id`. Procedure:

1. Validate that the user request names exactly one building. Do not infer a
   building from W2 truth.
2. Create `ComplianceAssessmentRun(run_type="baseline_building_review")`.
3. Call `retrieve_building_facts` tool to build `FactPack`.
4. Call `retrieve_applicable_rules` tool to build `RuleSlice`.
5. Call `run_closure_verification` tool — `allow_stop` is decided here.
6. Read `allow_stop` only from the closure tool payload and use the supplied
   `narrative_evidence_pack`. Its short aliases `[O*]` / `[R*]` / `[F*]` are
   the only evidence handles allowed in model-authored analysis.
7. If `allow_stop=false`, call `submit_analysis(analysis_markdown=...)` with
   only the “unclosed reasons and suggested supplementary materials” analysis
   section. If `allow_stop=true`, submit only the “analysis and suggestions”
   section. The program renders the title, authoritative counts, tables,
   citations, review prompts, and the rest of the report skeleton.
8. Every independent analysis point must cite at least one valid evidence-pack
   alias. Use `query_open_obligations`, `inspect_obligation`,
   `lookup_rule_card`, or `lookup_clause` only when extra context is useful;
   never replace the aliases with guessed ids or text.

## Guidelines

- Never read or request `NormativeProjection`, `expected_verdict`, W2
  projection tables, or evaluator outputs.
- `allow_stop` is decided by the deterministic verifier — never override it.
- Do not write a whole report, headings that impersonate authoritative report
  sections, or restate verifier totals/counts in `analysis_markdown`.
- All five hooks (`pre_run_input_guard` / `pre_retrieval_query_guard` /
  `post_retrieval_source_audit` / `post_verifier_stop_gate` /
  `pre_output_language_guard`) are hard gates; do not try to bypass.
