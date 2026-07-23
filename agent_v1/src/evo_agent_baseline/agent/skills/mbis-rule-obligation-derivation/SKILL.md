---
name: mbis-rule-obligation-derivation
description: 'Construct a RuleSlice (candidate rule cards + families + slot/measure/artifact registries + source quotes) for a given FactPack. Use after fact retrieval and before deterministic closure verification. Never decides obligation closure — that is the verifier job.'
---

# MBIS rule obligation derivation

## Instructions

Procedure:

1. Use FactPack slots, measures, artifact slots and component / building
   scope tags to retrieve candidate RuleCards.
2. Expand every candidate card to original rule_card v2 nested shape.
3. Include `threshold_regimes[].formula` from `RuleThreshold.formula_json`
   when present.
4. Include `obligation_graph.nodes[]` and `obligation_graph.edges[]`.
5. Include all evidence requirement buckets: `for_matching`,
   `for_submission`, `for_completion`.
6. Include source quotes with `source_quote_id` and `quote_local_id`.

## Guidelines

- Never include W2 family verdicts, projections, threshold evaluations or
  basis items.
- This skill constructs `RuleSlice` only — it does not decide obligation
  closure; the deterministic verifier does.
- LLM agents trigger this via the `retrieve_applicable_rules` tool.
