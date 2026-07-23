from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

ObligationType = Literal["prerequisite", "exception", "definition", "threshold"]
ObligationStatus = Literal["supported", "contradicted", "unknown", "blocked"]
BlockedReasonCode = Literal["missing_fact", "missing_rule_edge", "unsupported_case"]


class Obligation(BaseModel):
    obligation_id: str
    source_rule_id: str
    type: ObligationType
    required_fact_slots: List[str] = Field(default_factory=list)
    status: ObligationStatus
    evidence_refs: List[str] = Field(default_factory=list)
    notes: str = ""
    blocked_reason_code: Optional[BlockedReasonCode] = None

    @model_validator(mode="after")
    def validate_blocked_reason(self) -> "Obligation":
        if self.status == "blocked" and self.blocked_reason_code is None:
            raise ValueError("blocked obligation must include blocked_reason_code")
        if self.status != "blocked" and self.blocked_reason_code is not None:
            raise ValueError("blocked_reason_code is only valid when status=blocked")
        return self


class ObligationSet(BaseModel):
    obligations: List[Obligation] = Field(default_factory=list)


class ClosureSummary(BaseModel):
    total_obligations: int
    open_obligations_count: int
    high_risk_open_count: int
    status_counts: Dict[ObligationStatus, int]
    type_counts: Dict[ObligationType, int]
    blocked_reason_counts: Dict[BlockedReasonCode, int]
    stop_reason: str


class ClosureValidationResult(BaseModel):
    obligations: List[Obligation]
    allow_stop: bool
    closure_summary: ClosureSummary
    unmet_obligations: List[Obligation]

