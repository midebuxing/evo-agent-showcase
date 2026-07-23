from __future__ import annotations

import re
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

CandidateState = Literal["candidate"]
SkillType = Literal["strategy"]


class TriggerSignature(BaseModel):
    trigger_id: str
    matched_feature_ids: List[str]
    matched_pattern_ids: List[str]

    @model_validator(mode="after")
    def validate_signature(self) -> "TriggerSignature":
        if not re.fullmatch(r"TR-\d{3}", self.trigger_id):
            raise ValueError(f"Invalid trigger_id: {self.trigger_id}")
        if not self.matched_pattern_ids:
            raise ValueError("TriggerSignature.matched_pattern_ids cannot be empty")
        return self


class SkillCandidateMetrics(BaseModel):
    matched_case_count: int = Field(default=0, ge=0)
    decision_pass_count: int = Field(default=0, ge=0)
    decision_fail_count: int = Field(default=0, ge=0)
    allow_stop_true_count: int = Field(default=0, ge=0)
    allow_stop_false_count: int = Field(default=0, ge=0)


class SkillCandidateDraft(BaseModel):
    candidate_id: str
    skill_type: SkillType
    trigger_signature: TriggerSignature
    target_rule_ids: List[str]
    procedure_steps: List[str]
    guardrails: List[str]
    provenance_case_ids: List[str]
    provenance_trace_refs: List[str]
    state: CandidateState = "candidate"
    metrics: SkillCandidateMetrics

    @model_validator(mode="after")
    def validate_draft(self) -> "SkillCandidateDraft":
        if not re.fullmatch(r"scd-tr-\d{3}(?:-[a-z0-9]+)+", self.candidate_id):
            raise ValueError(f"Invalid candidate_id: {self.candidate_id}")
        if not self.target_rule_ids:
            raise ValueError("SkillCandidateDraft.target_rule_ids cannot be empty")
        if not self.procedure_steps:
            raise ValueError("SkillCandidateDraft.procedure_steps cannot be empty")
        if not self.guardrails:
            raise ValueError("SkillCandidateDraft.guardrails cannot be empty")
        if not self.provenance_case_ids:
            raise ValueError("SkillCandidateDraft.provenance_case_ids cannot be empty")
        if not self.provenance_trace_refs:
            raise ValueError("SkillCandidateDraft.provenance_trace_refs cannot be empty")
        return self
