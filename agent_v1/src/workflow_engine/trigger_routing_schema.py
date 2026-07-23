from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

RoutingTriggerId = Literal["TR-001", "TR-002", "TR-003"]
RoutingAction = Literal["TR-001", "TR-002", "TR-003", "NO_TRIGGER"]
RoutingConclusion = Literal["learning_signal_present", "signal_insufficient"]
RoutingPhase = Literal["A", "B"]


class RoutingTriggerTrace(BaseModel):
    trigger_id: RoutingTriggerId
    matched: bool
    missing_required_feature_ids: List[str] = Field(default_factory=list)
    missing_required_pattern_ids: List[str] = Field(default_factory=list)
    blocked_negative_feature_ids: List[str] = Field(default_factory=list)


class RoutingClosureContext(BaseModel):
    allow_stop: Optional[bool] = None
    blocked_reason_counts: Dict[str, int] = Field(default_factory=dict)
    high_risk_open_count: int = Field(default=0, ge=0)
    stop_reason: str = ""


class RoutingContext(BaseModel):
    matched_feature_ids: List[str] = Field(default_factory=list)
    matched_pattern_ids: List[str] = Field(default_factory=list)
    trigger_evaluation: List[RoutingTriggerTrace] = Field(default_factory=list)
    closure_summary: RoutingClosureContext = Field(default_factory=RoutingClosureContext)


class RoutingTraceRow(BaseModel):
    source_run_id: str
    phase: RoutingPhase
    case_id: str
    routing_point_id: str
    context: RoutingContext
    candidate_set: List[RoutingTriggerId]
    chosen_action: RoutingAction
    reward: float = Field(..., ge=0.0, le=1.0)
    materialized_rule_seed_bridge: bool
    source_refs: List[str]

    @model_validator(mode="after")
    def validate_row(self) -> "RoutingTraceRow":
        if not re.fullmatch(r"review_[AB]_seed_runtime_freeze_fullreg", self.source_run_id):
            raise ValueError(f"Invalid source_run_id: {self.source_run_id}")
        if not re.fullmatch(r"case_\d{2}", self.case_id):
            raise ValueError(f"Invalid case_id: {self.case_id}")
        if not self.routing_point_id:
            raise ValueError("routing_point_id cannot be empty")
        if sorted(self.candidate_set) != ["TR-001", "TR-002", "TR-003"]:
            raise ValueError("candidate_set must contain TR-001/TR-002/TR-003")
        if not self.source_refs:
            raise ValueError("source_refs cannot be empty")
        return self


class RoutingTraceDataset(BaseModel):
    version: Literal["v1"]
    source_run_ids: List[str]
    candidate_set: List[RoutingTriggerId]
    rows: List[RoutingTraceRow]

    @model_validator(mode="after")
    def validate_dataset(self) -> "RoutingTraceDataset":
        if sorted(self.source_run_ids) != [
            "review_A_seed_runtime_freeze_fullreg",
            "review_B_seed_runtime_freeze_fullreg",
        ]:
            raise ValueError("RoutingTraceDataset.source_run_ids must match the frozen fullreg inputs")
        if sorted(self.candidate_set) != ["TR-001", "TR-002", "TR-003"]:
            raise ValueError("RoutingTraceDataset.candidate_set must contain TR-001/TR-002/TR-003")
        if not self.rows:
            raise ValueError("RoutingTraceDataset.rows cannot be empty")
        return self


class TriggerRanker(BaseModel):
    version: Literal["v1"]
    candidate_set: List[RoutingTriggerId]
    trained_row_count: int = Field(..., ge=0)
    trained_positive_row_count: int = Field(..., ge=0)
    prior_scores: Dict[str, float] = Field(default_factory=dict)
    feature_scores: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    pattern_scores: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    feature_weight: float = Field(..., ge=0.0)
    pattern_weight: float = Field(..., ge=0.0)
    scoring_formula: str

    @model_validator(mode="after")
    def validate_ranker(self) -> "TriggerRanker":
        if sorted(self.candidate_set) != ["TR-001", "TR-002", "TR-003"]:
            raise ValueError("TriggerRanker.candidate_set must contain TR-001/TR-002/TR-003")
        if self.trained_positive_row_count > self.trained_row_count:
            raise ValueError("trained_positive_row_count cannot exceed trained_row_count")
        if not self.scoring_formula:
            raise ValueError("scoring_formula cannot be empty")
        return self


class CandidateReductionIfTopK(BaseModel):
    top1: float = Field(..., ge=0.0, le=1.0)
    top2: float = Field(..., ge=0.0, le=1.0)


class ShadowRoutingReport(BaseModel):
    version: Literal["v1"]
    dataset_row_count: int = Field(..., ge=0)
    routable_row_count: int = Field(..., ge=0)
    non_routable_row_count: int = Field(..., ge=0)
    observed_positive_counts: Dict[str, int] = Field(default_factory=dict)
    top1_hit_rate: float = Field(..., ge=0.0, le=1.0)
    top2_coverage: float = Field(..., ge=0.0, le=1.0)
    candidate_reduction_if_topk: CandidateReductionIfTopK
    closure_regression_count: int = Field(..., ge=0)
    notes_on_failure_modes: List[str] = Field(default_factory=list)
    conclusion: RoutingConclusion
    dataset_ref: str
    ranker_ref: str

    @model_validator(mode="after")
    def validate_report(self) -> "ShadowRoutingReport":
        if self.routable_row_count + self.non_routable_row_count != self.dataset_row_count:
            raise ValueError("Routing row counts must add up to dataset_row_count")
        if not self.dataset_ref:
            raise ValueError("dataset_ref cannot be empty")
        if not self.ranker_ref:
            raise ValueError("ranker_ref cannot be empty")
        return self
