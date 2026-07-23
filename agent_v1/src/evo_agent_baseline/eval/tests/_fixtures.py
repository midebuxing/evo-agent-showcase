"""eval/ 单测共用的造数据工具。

提供合法 `Obligation` / `ObligationSet` / `ClosureValidationResult` 构造器，
以及内存 W2 `TruthBundle` 构造器，供 mapper / metrics / leakage / report 测试用。
不读真实 parquet，全部用 fixture——保证测试可重复且不依赖 W2 产料目录。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    Obligation,
    ObligationSet,
)
from evo_agent_baseline.eval.truth_loader import TruthBundle


def make_obligation(
    obligation_id: str,
    *,
    world_id: str = "WB-T",
    building_id: str = "BLD-T",
    fragment_id: Optional[str] = "FRG-T-0",
    source_family_id: str = "mbis.inspection.drainage.ri.coverage",
    kind: str = "evidence",
    closure_status: str = "closed",
    satisfaction_status: str = "satisfied",
    applicability_state: str = "applicable",
    open_reason_code: Optional[str] = None,
    blocked_reason_code: Optional[str] = None,
    operator: Optional[str] = None,
    threshold_value_json: Optional[str] = None,
    observed_value_json: Optional[str] = None,
    comparator_result: Optional[bool] = None,
    unit: Optional[str] = None,
    slot_ids: Optional[List[str]] = None,
    measure_keys: Optional[List[str]] = None,
    source_rule_card_id: str = "rc.test.card.c01",
    run_id: str = "CAR-T",
) -> Obligation:
    """构造一条满足 contracts.Obligation validator 的义务。

    closure/satisfaction/原因码组合自动补全，避免触发 pydantic validator 报错。
    """
    return Obligation(
        obligation_id=obligation_id,
        run_id=run_id,
        world_id=world_id,
        building_id=building_id,
        fragment_id=fragment_id,
        source_rule_card_id=source_rule_card_id,
        source_family_id=source_family_id,
        kind=kind,  # type: ignore[arg-type]
        closure_status=closure_status,  # type: ignore[arg-type]
        satisfaction_status=satisfaction_status,  # type: ignore[arg-type]
        applicability_state=applicability_state,  # type: ignore[arg-type]
        open_reason_code=open_reason_code,  # type: ignore[arg-type]
        blocked_reason_code=blocked_reason_code,  # type: ignore[arg-type]
        operator=operator,
        threshold_value_json=threshold_value_json,
        observed_value_json=observed_value_json,
        comparator_result=comparator_result,
        unit=unit,
        slot_ids=slot_ids or [],
        measure_keys=measure_keys or [],
    )


def make_closure_result(
    obligations: List[Obligation],
    *,
    run_id: str = "CAR-T",
    world_id: str = "WB-T",
    building_id: str = "BLD-T",
    allow_stop: Optional[bool] = None,
) -> ClosureValidationResult:
    """从义务列表构造 `ClosureValidationResult`，统计字段自动汇总。"""
    closed = sum(1 for o in obligations if o.closure_status == "closed")
    opened = sum(1 for o in obligations if o.closure_status == "open")
    blocked = sum(1 for o in obligations if o.closure_status == "blocked")
    satisfied = sum(1 for o in obligations if o.satisfaction_status == "satisfied")
    violated = sum(1 for o in obligations if o.satisfaction_status == "violated")
    unknown = sum(1 for o in obligations if o.satisfaction_status == "unknown")
    na = sum(1 for o in obligations if o.satisfaction_status == "not_applicable")

    blocked_reason_counts: Dict[str, int] = {}
    open_reason_counts: Dict[str, int] = {}
    for o in obligations:
        if o.blocked_reason_code:
            blocked_reason_counts[o.blocked_reason_code] = (
                blocked_reason_counts.get(o.blocked_reason_code, 0) + 1
            )
        if o.open_reason_code:
            open_reason_counts[o.open_reason_code] = (
                open_reason_counts.get(o.open_reason_code, 0) + 1
            )

    if allow_stop is None:
        allow_stop = opened == 0 and blocked == 0

    summary = ClosureSummary(
        total_obligations=len(obligations),
        closed_count=closed,
        open_count=opened,
        blocked_count=blocked,
        satisfied_count=satisfied,
        violated_count=violated,
        unknown_count=unknown,
        not_applicable_count=na,
        open_reason_counts=open_reason_counts,
        blocked_reason_counts=blocked_reason_counts,
        rule_card_count=len({o.source_rule_card_id for o in obligations}),
        family_count=len({o.source_family_id for o in obligations}),
        fragment_count=len({o.fragment_id for o in obligations if o.fragment_id}),
        allow_stop=allow_stop,
        stop_reason="ok" if allow_stop else "open_or_blocked",
    )
    ob_set = ObligationSet(
        obligation_set_id="OS-T",
        run_id=run_id,
        world_id=world_id,
        building_id=building_id,
        created_at="2026-01-01T00:00:00Z",
        rulecard_bundle_id="RCB-T",
        verifier_version="v-test",
        obligations=obligations,
        derivation_policy={},
    )
    return ClosureValidationResult(
        run_id=run_id,
        obligation_set=ob_set,
        closure_summary=summary,
        allow_stop=allow_stop,
        allow_report_generation=allow_stop,
        high_risk_items=[],
        machine_readable_report={},
    )


def make_truth_bundle(
    *,
    projections_rows: Optional[List[Dict[str, Any]]] = None,
    matched_families_rows: Optional[List[Dict[str, Any]]] = None,
    threshold_rows: Optional[List[Dict[str, Any]]] = None,
    basis_rows: Optional[List[Dict[str, Any]]] = None,
    truth_dir: str = "<fixture>",
) -> TruthBundle:
    """构造一个内存 W2 `TruthBundle`，列名与真实 parquet schema 对齐。"""
    proj_cols = [
        "world_id", "fragment_id", "projection_id", "projection_family",
        "selected_family", "expected_verdict", "severity_band", "required_slots",
    ]
    mf_cols = ["projection_id", "family_id", "applicability_state", "verdict", "rule_ids"]
    th_cols = [
        "projection_id", "family_id", "rule_id", "threshold_regime_id",
        "slot_id", "operator",
        "threshold_value_json", "observed_value_json", "regime_tag", "pass_bool",
    ]
    bi_cols = ["projection_id", "basis_kind", "basis_id", "family_id", "rule_id"]

    proj = pd.DataFrame(projections_rows or [], columns=proj_cols)
    mf = pd.DataFrame(matched_families_rows or [], columns=mf_cols)
    threshold_data = [
        {**row, "threshold_regime_id": row.get("threshold_regime_id") or "regime.default"}
        for row in (threshold_rows or [])
    ]
    th = pd.DataFrame(threshold_data, columns=th_cols)
    bi = pd.DataFrame(basis_rows or [], columns=bi_cols)
    meta = pd.DataFrame(
        [{"version": "v2", "generated_at": "2026", "registry_bundle_hash": "h",
          "deterministic_key": "k"}]
    )
    return TruthBundle(
        truth_dir=truth_dir,
        normative_projection_meta=meta,
        projections=proj,
        matched_families=mf,
        threshold_evaluations=th,
        basis_items=bi,
        coverage_control_metadata=None,
        backend="pandas",
        loaded_tables=["normative_projection_meta", "projections",
                       "matched_families", "threshold_evaluations", "basis_items"],
    )
