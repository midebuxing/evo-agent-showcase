from __future__ import annotations

import re
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

EvalStatus = Literal["evaluated"]


class SkillEvalNotes(BaseModel):
    trigger_coverage_summary: str
    symbolic_result_summary: str
    closure_risk_summary: str


class SkillEvalReport(BaseModel):
    candidate_id: str
    trigger_id: str
    evaluated_case_ids: List[str]
    matched_case_count: int = Field(..., ge=0)
    decision_pass_count: int = Field(..., ge=0)
    decision_fail_count: int = Field(..., ge=0)
    allow_stop_true_count: int = Field(..., ge=0)
    allow_stop_false_count: int = Field(..., ge=0)
    closure_blocked_case_ids: List[str]
    status: EvalStatus
    notes: SkillEvalNotes

    @model_validator(mode="after")
    def validate_report(self) -> "SkillEvalReport":
        if not re.fullmatch(r"scd-tr-\d{3}(?:-[a-z0-9]+)+", self.candidate_id):
            raise ValueError(f"Invalid candidate_id: {self.candidate_id}")
        if not re.fullmatch(r"TR-\d{3}", self.trigger_id):
            raise ValueError(f"Invalid trigger_id: {self.trigger_id}")
        if self.matched_case_count != len(self.evaluated_case_ids):
            raise ValueError("matched_case_count must equal len(evaluated_case_ids)")
        if self.decision_pass_count + self.decision_fail_count > self.matched_case_count:
            raise ValueError("decision counts cannot exceed matched_case_count")
        if self.allow_stop_true_count + self.allow_stop_false_count > self.matched_case_count:
            raise ValueError("allow_stop counts cannot exceed matched_case_count")
        return self
