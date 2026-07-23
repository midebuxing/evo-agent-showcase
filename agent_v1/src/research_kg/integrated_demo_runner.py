from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from research_kg.baseline_config import LocalLLMConfig
from research_kg.baseline_runner import (
    _build_extraction_prompt,
    _build_fact_pack,
    _build_rule_cards_for_closure,
    _build_seed_rule_bridge,
    _call_llm,
    _normalize_selected_rule_ids,
    _parse_llm_response,
)
from research_kg.kg_retriever import RetrievalResult, retrieve_from_kg
from research_kg.loader import DualSourceResearchKG, load_dual_source_kg
from workflow_engine.closure_validator import validate_closure
from workflow_engine.evidence_schema import FactPack
from workflow_engine.fact_feature_pattern_matcher import match_fact_pack
from workflow_engine.fact_feature_pattern_schema import load_fact_feature_pattern_catalog
from workflow_engine.fact_trigger_contract import (
    build_rule_seed_bridge,
    evaluate_trigger_specs,
    load_seed_trigger_specs,
)
from workflow_engine.trigger_routing_schema import TriggerRanker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESEARCH_KG_DIR = PROJECT_ROOT / "research_kg"
DEFAULT_FEATURE_CATALOG = PROJECT_ROOT / "experiments" / "fact_features_v1.json"
DEFAULT_PATTERN_CATALOG = PROJECT_ROOT / "experiments" / "fact_patterns_v1.json"
DEFAULT_TRIGGER_SPEC_PATH = PROJECT_ROOT / "experiments" / "seed_trigger_specs_v1.json"
DEFAULT_TRIGGER_RANKER_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "runs"
    / "review_phaseB_trigger_routing_v1"
    / "TriggerRanker.v1.json"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "experiments"
    / "runs"
    / "review_phaseE_integrated_demo_v1"
)
DEFAULT_DEMO_QUERY_SET_PATH = DEFAULT_OUTPUT_DIR / "DemoQuerySet.json"
SUPPORTED_MODES = {"baseline", "routing_assisted"}
PRIMARY_CHAIN_NAMES = ("crack_chain", "rebar_spall_chain")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _load_trigger_ranker(path: Path) -> TriggerRanker:
    return TriggerRanker.model_validate(_load_json(path))


def _empty_fact_pack(case_id: str) -> FactPack:
    return FactPack(case_id=case_id, generated_at=_utc_now_iso(), facts=[])


def _build_chain_status(matched_chain: str, status: str) -> Dict[str, str]:
    chain_status = {
        "crack_chain": "not_run",
        "rebar_spall_chain": "not_run",
    }
    if matched_chain == "unknown":
        chain_status["crack_chain"] = "not_matched"
        chain_status["rebar_spall_chain"] = "not_matched"
        return chain_status
    if matched_chain in chain_status:
        chain_status[matched_chain] = status
    return chain_status


def _count_successful_queries(results: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in results if "success" in item.get("chain_status", {}).values())


def _has_chain_regression(
    baseline_status: Mapping[str, str],
    routing_status: Mapping[str, str],
) -> bool:
    for chain_name in PRIMARY_CHAIN_NAMES:
        baseline_value = baseline_status.get(chain_name, "")
        routing_value = routing_status.get(chain_name, "")
        if baseline_value == "success" and routing_value != "success":
            return True
    return False


def load_demo_query_set(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("DemoQuerySet must be a JSON object.")
    if "queries" not in payload or not isinstance(payload["queries"], list):
        raise ValueError("DemoQuerySet.queries must be a JSON array.")
    for idx, item in enumerate(payload["queries"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"DemoQuerySet.queries[{idx}] must be an object.")
        if not item.get("query_id"):
            raise ValueError(f"DemoQuerySet.queries[{idx}] missing query_id.")
        if not item.get("query"):
            raise ValueError(f"DemoQuerySet.queries[{idx}] missing query.")
    return payload


class IntegratedDemoResult:
    def __init__(
        self,
        *,
        query_id: str,
        query: str,
        mode: str,
        retrieval_summary: Mapping[str, Any],
        llm_response: Mapping[str, Any],
        fact_pack: FactPack,
        selected_rule_ids: Sequence[str],
        selected_rule_source: str,
        chain_status: Mapping[str, str],
        closure_result: Any,
        step_trace: Sequence[str],
        routing_summary: Optional[Mapping[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.query_id = query_id
        self.query = query
        self.mode = mode
        self.retrieval_summary = dict(retrieval_summary)
        self.llm_response = dict(llm_response)
        self.fact_pack = fact_pack
        self.selected_rule_ids = list(selected_rule_ids)
        self.selected_rule_source = selected_rule_source
        self.chain_status = dict(chain_status)
        self.closure_result = closure_result
        self.step_trace = list(step_trace)
        self.routing_summary = dict(routing_summary) if routing_summary else None
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        closure_summary = None
        closure_allow_stop = None
        unmet_obligation_count = 0
        if self.closure_result is not None:
            closure_allow_stop = self.closure_result.allow_stop
            closure_summary = self.closure_result.closure_summary.model_dump()
            unmet_obligation_count = len(self.closure_result.unmet_obligations)
        return {
            "generated_at": _utc_now_iso(),
            "query_id": self.query_id,
            "query": self.query,
            "mode": self.mode,
            "retrieval": self.retrieval_summary,
            "llm_extraction": self.llm_response,
            "fact_count": len(self.fact_pack.facts),
            "selected_rule_ids": self.selected_rule_ids,
            "selected_rule_source": self.selected_rule_source,
            "chain_status": self.chain_status,
            "closure_verifier_reached": self.closure_result is not None,
            "closure_allow_stop": closure_allow_stop,
            "closure_summary": closure_summary,
            "unmet_obligation_count": unmet_obligation_count,
            "step_trace": self.step_trace,
            "step_count": len(self.step_trace),
            "routing_summary": self.routing_summary,
            "error": self.error,
        }


class IntegratedDemoRunner:
    def __init__(
        self,
        *,
        kg: DualSourceResearchKG,
        config: Optional[LocalLLMConfig] = None,
        feature_catalog_path: Path = DEFAULT_FEATURE_CATALOG,
        pattern_catalog_path: Path = DEFAULT_PATTERN_CATALOG,
        trigger_spec_path: Path = DEFAULT_TRIGGER_SPEC_PATH,
        trigger_ranker_path: Path = DEFAULT_TRIGGER_RANKER_PATH,
    ) -> None:
        self.kg = kg
        self.config = config or LocalLLMConfig()
        self.features, self.patterns = load_fact_feature_pattern_catalog(
            feature_catalog_path=feature_catalog_path,
            pattern_catalog_path=pattern_catalog_path,
        )
        self.trigger_specs = load_seed_trigger_specs(trigger_spec_path)
        self.trigger_ranker = _load_trigger_ranker(trigger_ranker_path)
        self.trigger_to_rule_ids = self._build_trigger_to_rule_ids()

    def _build_trigger_to_rule_ids(self) -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = {}
        chains = self.kg.top_manifest.get("mainline_chains", {})
        for chain_name in PRIMARY_CHAIN_NAMES:
            chain_def = chains.get(chain_name, {})
            trigger_id = chain_def.get("trigger")
            rule_ids = list(chain_def.get("rule_cards", []))
            if trigger_id and rule_ids:
                mapping[trigger_id] = rule_ids
        return mapping

    def _resolve_selected_rule_ids(
        self,
        *,
        llm_parsed: Dict[str, Any],
        retrieval: RetrievalResult,
    ) -> tuple[List[str], str]:
        raw_selected_ids = llm_parsed.get("selected_rule_ids", [])
        selected_ids = _normalize_selected_rule_ids(raw_selected_ids, retrieval)
        if raw_selected_ids != selected_ids:
            llm_parsed["_selected_rule_ids_raw"] = raw_selected_ids
        llm_parsed["selected_rule_ids"] = selected_ids
        if selected_ids:
            llm_parsed["_rule_selection_mode"] = "llm_selected"
            return selected_ids, "llm_selected"
        llm_parsed["_rule_selection_mode"] = "fallback_all"
        if raw_selected_ids:
            llm_parsed["_rule_selection_warning"] = (
                "LLM returned selected_rule_ids, but none matched the retrieved RuleCards. "
                "Falling back to all retrieved rules."
            )
        return [rc["node_id"] for rc in retrieval.rule_cards], "fallback_all"

    def _score_routing_signals(
        self,
        *,
        fact_pack: FactPack,
    ) -> Dict[str, Any]:
        matched = match_fact_pack(
            fact_pack=fact_pack,
            features=self.features,
            patterns=self.patterns,
        )
        matched_feature_ids = [item["feature_id"] for item in matched["matched_features"]]
        matched_pattern_ids = [item["pattern_id"] for item in matched["matched_patterns"]]
        trigger_evaluations = evaluate_trigger_specs(
            trigger_specs=self.trigger_specs,
            matched_feature_ids=matched_feature_ids,
            matched_pattern_ids=matched_pattern_ids,
        )
        evaluation_by_id = {
            item["trigger_id"]: item
            for item in trigger_evaluations
        }

        score_rows: List[Dict[str, Any]] = []
        for trigger_id in self.trigger_ranker.candidate_set:
            prior_score = float(self.trigger_ranker.prior_scores.get(trigger_id, 0.0))
            feature_score = sum(
                float(self.trigger_ranker.feature_scores.get(feature_id, {}).get(trigger_id, 0.0))
                for feature_id in matched_feature_ids
            )
            pattern_score = sum(
                float(self.trigger_ranker.pattern_scores.get(pattern_id, {}).get(trigger_id, 0.0))
                for pattern_id in matched_pattern_ids
            )
            total_score = round(
                prior_score
                + self.trigger_ranker.feature_weight * feature_score
                + self.trigger_ranker.pattern_weight * pattern_score,
                6,
            )
            evaluation = evaluation_by_id.get(trigger_id, {})
            score_rows.append(
                {
                    "trigger_id": trigger_id,
                    "prior_score": prior_score,
                    "feature_score": round(feature_score, 6),
                    "pattern_score": round(pattern_score, 6),
                    "total_score": total_score,
                    "hard_match": bool(evaluation.get("matched")),
                    "missing_required_feature_ids": list(
                        evaluation.get("missing_required_feature_ids", [])
                    ),
                    "missing_required_pattern_ids": list(
                        evaluation.get("missing_required_pattern_ids", [])
                    ),
                    "blocked_negative_feature_ids": list(
                        evaluation.get("blocked_negative_feature_ids", [])
                    ),
                }
            )

        score_rows.sort(key=lambda item: (-item["total_score"], item["trigger_id"]))
        for rank, item in enumerate(score_rows, start=1):
            item["rank"] = rank

        return {
            "matched_feature_ids": matched_feature_ids,
            "matched_pattern_ids": matched_pattern_ids,
            "trigger_evaluations": trigger_evaluations,
            "trigger_scores": score_rows,
        }

    def _apply_routing_assistance(
        self,
        *,
        retrieval: RetrievalResult,
        fact_pack: FactPack,
        baseline_selected_rule_ids: Sequence[str],
    ) -> tuple[List[str], str, Dict[str, Any]]:
        routing_summary = self._score_routing_signals(fact_pack=fact_pack)
        routed_trigger_id: Optional[str] = None
        routed_rule_ids: List[str] = []
        route_reason = "no_pattern_signal"
        route_applied = False

        top_score = routing_summary["trigger_scores"][0] if routing_summary["trigger_scores"] else None
        retrieval_rule_ids = [rc["node_id"] for rc in retrieval.rule_cards]
        if top_score is not None:
            candidate_rule_ids = self.trigger_to_rule_ids.get(top_score["trigger_id"], [])
            if not routing_summary["matched_pattern_ids"]:
                route_reason = "no_pattern_signal"
            elif not candidate_rule_ids:
                route_reason = "unsupported_trigger_for_phasee"
            elif not set(candidate_rule_ids).intersection(retrieval_rule_ids):
                route_reason = "top_trigger_outside_retrieved_chain"
            elif not (top_score["hard_match"] or top_score["pattern_score"] > 0.0):
                route_reason = "ranker_score_not_pattern_backed"
            else:
                routed_trigger_id = top_score["trigger_id"]
                routed_rule_ids = [rule_id for rule_id in candidate_rule_ids if rule_id in retrieval_rule_ids]
                route_reason = "pattern_backed_top1_within_retrieved_chain"
                route_applied = True

        selected_rule_ids = list(baseline_selected_rule_ids)
        selected_rule_source = "baseline_fallback"
        if route_applied:
            overlap = [rule_id for rule_id in baseline_selected_rule_ids if rule_id in routed_rule_ids]
            if overlap:
                selected_rule_ids = overlap
                selected_rule_source = "routing_intersection"
            else:
                selected_rule_ids = list(routed_rule_ids)
                selected_rule_source = "routing_trigger_rules"

        routing_summary.update(
            {
                "route_applied": route_applied,
                "route_reason": route_reason,
                "candidate_count_before": len(self.trigger_ranker.candidate_set),
                "candidate_count_after": 1 if route_applied else len(self.trigger_ranker.candidate_set),
                "routed_trigger_id": routed_trigger_id,
                "routed_rule_ids": routed_rule_ids,
                "baseline_selected_rule_ids": list(baseline_selected_rule_ids),
                "effective_selected_rule_ids": list(selected_rule_ids),
            }
        )
        return selected_rule_ids, selected_rule_source, routing_summary

    def _build_seed_bridge(
        self,
        *,
        retrieval: RetrievalResult,
        selected_rule_ids: Sequence[str],
        routing_summary: Optional[Mapping[str, Any]],
    ) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
        routed_trigger_id = None
        trigger_evaluations: List[Mapping[str, Any]] = []
        if routing_summary:
            routed_trigger_id = routing_summary.get("routed_trigger_id")
            trigger_evaluations = list(routing_summary.get("trigger_evaluations", []))

        if routed_trigger_id:
            forced_evaluations: List[Dict[str, Any]] = []
            for item in trigger_evaluations:
                forced_evaluations.append(
                    {
                        "trigger_id": item["trigger_id"],
                        "name": item.get("name", item["trigger_id"]),
                        "matched": item["trigger_id"] == routed_trigger_id,
                        "target_rule_ids": list(item.get("target_rule_ids", [])),
                        "missing_required_feature_ids": list(
                            item.get("missing_required_feature_ids", [])
                        ),
                        "missing_required_pattern_ids": list(
                            item.get("missing_required_pattern_ids", [])
                        ),
                        "blocked_negative_feature_ids": list(
                            item.get("blocked_negative_feature_ids", [])
                        ),
                    }
                )
            bridge = build_rule_seed_bridge(
                trigger_specs=self.trigger_specs,
                trigger_evaluations=forced_evaluations,
            )
            return {
                rule_id: slot_map
                for rule_id, slot_map in bridge.items()
                if rule_id in selected_rule_ids
            }

        filtered_retrieval = retrieval.filter_rule_cards(list(selected_rule_ids))
        return _build_seed_rule_bridge(filtered_retrieval)

    def run(
        self,
        *,
        query: str,
        mode: str,
        query_id: str = "adhoc_query",
    ) -> IntegratedDemoResult:
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode: {mode}")

        retrieval = retrieve_from_kg(self.kg, query)
        step_trace = ["retrieve_kg"]

        if retrieval.matched_chain == "unknown":
            return IntegratedDemoResult(
                query_id=query_id,
                query=query,
                mode=mode,
                retrieval_summary=retrieval.summary(),
                llm_response={},
                fact_pack=_empty_fact_pack(case_id=f"{query_id}-{mode}"),
                selected_rule_ids=[],
                selected_rule_source="no_match",
                chain_status=_build_chain_status("unknown", "not_matched"),
                closure_result=None,
                step_trace=step_trace,
                routing_summary={
                    "route_applied": False,
                    "route_reason": "baseline_chain_not_matched",
                    "candidate_count_before": len(self.trigger_ranker.candidate_set),
                    "candidate_count_after": len(self.trigger_ranker.candidate_set),
                }
                if mode == "routing_assisted"
                else None,
                error="Query did not match a supported Phase E mainline chain.",
            )

        prompt = _build_extraction_prompt(query, retrieval)
        step_trace.append("llm_extract_and_rule_select")
        try:
            raw_llm = _call_llm(self.config, prompt)
            llm_parsed = _parse_llm_response(raw_llm)
        except Exception as exc:
            llm_parsed = {
                "extracted_facts": {},
                "selected_rule_ids": [],
                "reasoning": f"LLM call failed: {exc}",
                "llm_error": True,
            }

        step_trace.append("build_fact_pack")
        fact_pack = _build_fact_pack(query, llm_parsed.get("extracted_facts", {}), retrieval.matched_chain)

        if llm_parsed.get("llm_error"):
            return IntegratedDemoResult(
                query_id=query_id,
                query=query,
                mode=mode,
                retrieval_summary=retrieval.summary(),
                llm_response=llm_parsed,
                fact_pack=fact_pack,
                selected_rule_ids=[],
                selected_rule_source="llm_error",
                chain_status=_build_chain_status(retrieval.matched_chain, "llm_error"),
                closure_result=None,
                step_trace=step_trace,
                routing_summary=None,
                error=llm_parsed.get("reasoning"),
            )

        baseline_selected_rule_ids, selected_rule_source = self._resolve_selected_rule_ids(
            llm_parsed=llm_parsed,
            retrieval=retrieval,
        )
        selected_rule_ids = list(baseline_selected_rule_ids)
        routing_summary = None

        if mode == "routing_assisted":
            step_trace.extend(["match_fact_signals", "rank_triggers"])
            selected_rule_ids, selected_rule_source, routing_summary = self._apply_routing_assistance(
                retrieval=retrieval,
                fact_pack=fact_pack,
                baseline_selected_rule_ids=baseline_selected_rule_ids,
            )

        filtered_retrieval = retrieval.filter_rule_cards(selected_rule_ids)
        rule_cards = _build_rule_cards_for_closure(filtered_retrieval)
        seed_bridge = self._build_seed_bridge(
            retrieval=retrieval,
            selected_rule_ids=selected_rule_ids,
            routing_summary=routing_summary,
        )

        step_trace.append("closure_verify")
        closure_result = None
        closure_error = None
        try:
            closure_result = validate_closure(
                rule_cards=rule_cards,
                fact_pack=fact_pack,
                seed_rule_bridge=seed_bridge,
            )
        except Exception as exc:
            closure_error = f"Closure Verifier failed: {exc}"

        chain_status = _build_chain_status(
            retrieval.matched_chain,
            "success" if closure_result is not None else "closure_error",
        )
        return IntegratedDemoResult(
            query_id=query_id,
            query=query,
            mode=mode,
            retrieval_summary=filtered_retrieval.summary(),
            llm_response=llm_parsed,
            fact_pack=fact_pack,
            selected_rule_ids=selected_rule_ids,
            selected_rule_source=selected_rule_source,
            chain_status=chain_status,
            closure_result=closure_result,
            step_trace=step_trace,
            routing_summary=routing_summary,
            error=closure_error,
        )

    def run_query_set(
        self,
        *,
        mode: str,
        query_set: Mapping[str, Any],
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        for item in query_set.get("queries", []):
            result = self.run(
                query=item["query"],
                mode=mode,
                query_id=item["query_id"],
            )
            result_dict = result.to_dict()
            result_dict["label"] = item.get("label", "")
            result_dict["expected_chain"] = item.get("expected_chain", "")
            results.append(result_dict)

        return {
            "generated_at": _utc_now_iso(),
            "mode": mode,
            "query_set_id": query_set.get("query_set_id", ""),
            "query_count": len(results),
            "results": results,
            "summary": {
                "closure_reached_count": sum(
                    1 for item in results if item["closure_verifier_reached"]
                ),
                "success_count": _count_successful_queries(results),
                "llm_error_count": sum(
                    1
                    for item in results
                    if "llm_error" in item.get("llm_extraction", {})
                ),
                "route_applied_count": sum(
                    1
                    for item in results
                    if bool((item.get("routing_summary") or {}).get("route_applied"))
                ),
            },
        }


def build_phasee_comparison_report(
    *,
    query_set: Mapping[str, Any],
    baseline_report: Mapping[str, Any],
    routing_report: Mapping[str, Any],
) -> Dict[str, Any]:
    baseline_by_id = {
        item["query_id"]: item
        for item in baseline_report.get("results", [])
    }
    routing_by_id = {
        item["query_id"]: item
        for item in routing_report.get("results", [])
    }

    comparisons: List[Dict[str, Any]] = []
    regression_count = 0
    for item in query_set.get("queries", []):
        query_id = item["query_id"]
        baseline_item = baseline_by_id[query_id]
        routing_item = routing_by_id[query_id]
        routing_summary = routing_item.get("routing_summary") or {}
        step_count_delta = routing_item["step_count"] - baseline_item["step_count"]
        regression = (
            baseline_item["closure_verifier_reached"]
            and not routing_item["closure_verifier_reached"]
        ) or _has_chain_regression(
            baseline_status=baseline_item["chain_status"],
            routing_status=routing_item["chain_status"],
        )
        if regression:
            regression_count += 1

        notes: List[str] = []
        if baseline_item["selected_rule_ids"] == routing_item["selected_rule_ids"]:
            notes.append("selected_rule_ids unchanged across the two modes.")
        else:
            notes.append("selected_rule_ids changed after routing assistance.")

        if routing_summary.get("route_applied"):
            notes.append(
                "routing_assisted reduced trigger candidates "
                f"{routing_summary.get('candidate_count_before')} -> "
                f"{routing_summary.get('candidate_count_after')} via "
                f"{routing_summary.get('routed_trigger_id')}."
            )
        else:
            notes.append(
                "routing_assisted stayed on baseline fallback because no safe routing signal was available."
            )

        if regression:
            notes.append("A regression was observed relative to baseline.")
        else:
            notes.append("No obvious regression was observed on this query.")

        comparisons.append(
            {
                "query_id": query_id,
                "label": item.get("label", ""),
                "query": item["query"],
                "baseline": {
                    "selected_rule_ids": baseline_item["selected_rule_ids"],
                    "closure_verifier_reached": baseline_item["closure_verifier_reached"],
                    "chain_status": baseline_item["chain_status"],
                    "step_count": baseline_item["step_count"],
                    "error": baseline_item["error"],
                },
                "routing_assisted": {
                    "selected_rule_ids": routing_item["selected_rule_ids"],
                    "closure_verifier_reached": routing_item["closure_verifier_reached"],
                    "chain_status": routing_item["chain_status"],
                    "step_count": routing_item["step_count"],
                    "error": routing_item["error"],
                    "routed_trigger_id": routing_summary.get("routed_trigger_id"),
                    "route_applied": routing_summary.get("route_applied", False),
                },
                "differences": {
                    "selected_rule_ids_changed": (
                        baseline_item["selected_rule_ids"] != routing_item["selected_rule_ids"]
                    ),
                    "closure_reached_changed": (
                        baseline_item["closure_verifier_reached"]
                        != routing_item["closure_verifier_reached"]
                    ),
                    "chain_status_changed": (
                        baseline_item["chain_status"] != routing_item["chain_status"]
                    ),
                    "step_count_delta": step_count_delta,
                    "candidate_count_before": routing_summary.get("candidate_count_before"),
                    "candidate_count_after": routing_summary.get("candidate_count_after"),
                    "regression": regression,
                    "notes": notes,
                },
            }
        )

    route_applied_count = sum(
        1
        for item in routing_report.get("results", [])
        if bool((item.get("routing_summary") or {}).get("route_applied"))
    )

    summary_notes = [
        "routing_assisted is implemented as a conservative overlay on top of the stable baseline chain.",
        "Current TriggerRanker.v1 provides useful top-1 routing signals for TR-001/TR-002, but still has no abstain path for new chains.",
    ]
    if regression_count == 0:
        summary_notes.append("No obvious regression was observed on the minimal demo query set.")
    else:
        summary_notes.append("At least one regression remains and should be addressed before broader demos.")

    return {
        "version": "v1",
        "generated_at": _utc_now_iso(),
        "query_set_id": query_set.get("query_set_id", ""),
        "compared_modes": ["baseline", "routing_assisted"],
        "comparisons": comparisons,
        "summary": {
            "baseline_closure_reached_count": baseline_report.get("summary", {}).get(
                "closure_reached_count", 0
            ),
            "routing_assisted_closure_reached_count": routing_report.get("summary", {}).get(
                "closure_reached_count", 0
            ),
            "route_applied_count": route_applied_count,
            "regression_count": regression_count,
            "notes": summary_notes,
        },
    }


def write_phasee_comparison_artifacts(
    *,
    query_set_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    kg_dir: Path = DEFAULT_RESEARCH_KG_DIR,
    config: Optional[LocalLLMConfig] = None,
) -> Dict[str, Any]:
    query_set = load_demo_query_set(query_set_path)
    kg = load_dual_source_kg(kg_dir)
    runner = IntegratedDemoRunner(kg=kg, config=config)
    baseline_report = runner.run_query_set(mode="baseline", query_set=query_set)
    routing_report = runner.run_query_set(mode="routing_assisted", query_set=query_set)
    comparison_report = build_phasee_comparison_report(
        query_set=query_set,
        baseline_report=baseline_report,
        routing_report=routing_report,
    )

    baseline_path = _write_json(output_dir / "baseline_results.json", baseline_report)
    routing_path = _write_json(output_dir / "routing_assisted_results.json", routing_report)
    comparison_path = _write_json(output_dir / "PhaseEComparisonReport.json", comparison_report)

    return {
        "baseline_results_path": str(baseline_path),
        "routing_results_path": str(routing_path),
        "comparison_report_path": str(comparison_path),
        "comparison_report": comparison_report,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase E integrated demo runner.")
    parser.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_MODES),
        default="baseline",
        help="Execution mode when running a single query or a query set.",
    )
    parser.add_argument("--query", default="", help="One ad-hoc query.")
    parser.add_argument("--query-id", default="adhoc_query", help="Identifier for --query mode.")
    parser.add_argument("--query-set", default="", help="Path to DemoQuerySet JSON.")
    parser.add_argument("--output", default="", help="Optional output path for single-mode JSON.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory used by --compare.",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run both modes on --query-set and write baseline/routing/comparison artifacts.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.compare:
        if not args.query_set:
            raise RuntimeError("--compare requires --query-set.")
        bundle = write_phasee_comparison_artifacts(
            query_set_path=Path(args.query_set),
            output_dir=Path(args.output_dir),
        )
        print(json.dumps(bundle["comparison_report"], ensure_ascii=False, indent=2))
        return 0

    kg = load_dual_source_kg(DEFAULT_RESEARCH_KG_DIR)
    runner = IntegratedDemoRunner(kg=kg)

    if args.query_set:
        query_set = load_demo_query_set(Path(args.query_set))
        payload = runner.run_query_set(mode=args.mode, query_set=query_set)
    else:
        if not args.query:
            raise RuntimeError("Either --query or --query-set must be provided.")
        payload = runner.run(
            query=args.query,
            mode=args.mode,
            query_id=args.query_id,
        ).to_dict()

    if args.output:
        _write_json(Path(args.output), payload)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
