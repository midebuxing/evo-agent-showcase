---
name: mbis-fact-kg-retrieval
description: 'Retrieve WorldBundle and SidecarRuntimeBundle facts for a building to build a FactPack. Use when an MBIS assessment workflow needs the fact subgraph before rule derivation. Returns FactPack with slot/measure/carrier/artifact/method indexes. Never includes W2 projection truth.'
---

# MBIS fact KG retrieval

## Instructions

Allowed sources:

- `World`, `Building`, `Fragment`, `Component`, `Location`
- State nodes: `DriverState`, `MechanismState`, `ConditionState`,
  `RepairAssessmentState`, `DrainageState`, `UBWState`, `FireSafetyState`
- `Measurement`
- `SidecarRuntimeRecord`, `SidecarEntry`

Procedure:

1. Retrieve the building shell.
2. Retrieve all fragments, components and locations.
3. Retrieve all condition / state nodes; parse
   `ConditionState.derived_outcomes_*_json` into facts.
4. Retrieve measurements; parse `qualifiers_json` into dict qualifiers.
5. Retrieve sidecar entries; do not expose or reconstruct `projection_id`.
6. Build FactAtoms and indexes: `slot_index`, `measure_index`,
   `carrier_index`, `artifact_index`, `method_index`.
7. Run forbidden source audit and fail if any W2 property / table appears.

## Guidelines

- Output must not contain `projection_id`, `expected_verdict`,
  `coverage_status`, `basis_items`, or evaluator-only paths.
- LLM agents trigger this via the `retrieve_building_facts` tool.
