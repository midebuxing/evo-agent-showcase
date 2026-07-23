from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

from workflow_engine.obligation_schema import ClosureSummary, Obligation

SchemaVersion = Literal["1.0.0"]
PhaseType = Literal["A", "B"]
DecisionLabel = Literal["pass", "fail", "unknown"]
Comparator = Literal["<", "<=", ">", ">=", "==", "!="]
SourceType = Literal["observer", "code_action", "query"]


class ArtifactRef(BaseModel):
    artifact_id: str
    artifact_type: str
    path: str = Field(..., description="Relative path under run directory")


class TaskNode(BaseModel):
    node_id: str
    node_type: str
    description: str


class TaskEdge(BaseModel):
    source: str
    target: str


class TaskGraph(BaseModel):
    case_id: str
    phase: PhaseType
    nodes: List[TaskNode]
    edges: List[TaskEdge]


class RuleCondition(BaseModel):
    fact_key: str
    comparator: Comparator
    threshold: Any


class RuleCard(BaseModel):
    rule_id: str
    title: str
    version: str = "v1"
    conditions: List[RuleCondition]
    rationale: str


class FactItem(BaseModel):
    fact_id: str
    key: str
    value: Any
    unit: Optional[str] = None
    source_type: SourceType
    confidence: float = Field(..., ge=0.0, le=1.0)
    artifact_ref: Optional[ArtifactRef] = None


class FactPack(BaseModel):
    """W1 数据生成 / case 侧的事实包（case_id + FactItem 列表）。

    ⚠️ 勿与 ``evo_agent_baseline.contracts.FactPack``（agent 底线层闭包输入、含
    slot/measure/carrier 倒排索引）混淆——两者同名但属不同层、不同结构。两包互不
    import，同一文件内不会撞，但跨层读代码时易看错。
    """

    case_id: str
    generated_at: str
    facts: List[FactItem]


class DecisionStep(BaseModel):
    step_id: str
    rule_id: str
    fact_ids: List[str]
    comparator: Comparator
    threshold: Any
    observed_value: Any
    passed: bool
    reason: str


class DecisionTrace(BaseModel):
    case_id: str
    generated_at: str
    steps: List[DecisionStep]
    final_decision: DecisionLabel
    summary: str
    allow_stop: Optional[bool] = None
    closure_summary: Optional[ClosureSummary] = None
    unmet_obligation_ids: List[str] = Field(default_factory=list)


CoverageState = Literal["grounded", "partial", "stub"]


class SeedPatternDiagnostic(BaseModel):
    pattern_id: str
    name: str
    matched: bool
    coverage_state: CoverageState
    missing_required: List[str] = Field(default_factory=list)
    mismatched_required_values: List[str] = Field(default_factory=list)
    blocked_by_negative: List[str] = Field(default_factory=list)


class SeedTriggerEvaluation(BaseModel):
    trigger_id: str
    name: str
    matched: bool
    target_rule_ids: List[str] = Field(default_factory=list)
    missing_required_feature_ids: List[str] = Field(default_factory=list)
    missing_required_pattern_ids: List[str] = Field(default_factory=list)
    blocked_negative_feature_ids: List[str] = Field(default_factory=list)


class SeedRuleBridgeSlot(BaseModel):
    feature_ids: List[str] = Field(default_factory=list)
    pattern_ids: List[str] = Field(default_factory=list)
    trigger_ids: List[str] = Field(default_factory=list)


class SeedRuntime(BaseModel):
    matched_feature_ids: List[str] = Field(default_factory=list)
    matched_pattern_ids: List[str] = Field(default_factory=list)
    pattern_diagnostics: List[SeedPatternDiagnostic] = Field(default_factory=list)
    trigger_evaluation: List[SeedTriggerEvaluation] = Field(default_factory=list)
    rule_seed_bridge: Dict[str, Dict[str, SeedRuleBridgeSlot]] = Field(default_factory=dict)


class EvidencePack(BaseModel):
    schema_version: SchemaVersion = "1.0.0"
    phase: PhaseType
    case_id: str
    generated_at: str
    task_graph: TaskGraph
    rule_cards: List[RuleCard]
    fact_pack: FactPack
    decision_trace: DecisionTrace
    obligations: List[Obligation] = Field(default_factory=list)
    allow_stop: Optional[bool] = None
    closure_summary: Optional[ClosureSummary] = None
    unmet_obligations: List[Obligation] = Field(default_factory=list)
    seed_runtime: SeedRuntime = Field(default_factory=SeedRuntime)
    evidence_completeness: float = Field(..., ge=0.0, le=1.0)
    references: List[ArtifactRef]

    @model_validator(mode="after")
    def validate_internal_references(self) -> "EvidencePack":
        fact_ids = {fact.fact_id for fact in self.fact_pack.facts}
        rule_ids = {rule.rule_id for rule in self.rule_cards}
        for step in self.decision_trace.steps:
            if step.rule_id not in rule_ids:
                raise ValueError(f"DecisionTrace references unknown rule_id: {step.rule_id}")
            for fact_id in step.fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError(f"DecisionTrace references unknown fact_id: {fact_id}")
        return self


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_evidence_pack(payload: Mapping[str, Any]) -> EvidencePack:
    return EvidencePack.model_validate(payload)


def model_json_schema_bundle() -> Dict[str, Dict[str, Any]]:
    models: Iterable[type[BaseModel]] = (
        TaskGraph,
        RuleCard,
        FactPack,
        ClosureSummary,
        Obligation,
        DecisionTrace,
        SeedRuntime,
        EvidencePack,
    )
    return {model.__name__: model.model_json_schema() for model in models}


def export_json_schema_bundle(output_dir: Path) -> List[Path]:
    import json

    output_dir.mkdir(parents=True, exist_ok=True)
    schema_paths: List[Path] = []
    for name, schema in model_json_schema_bundle().items():
        out_path = output_dir / f"{name}.schema.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        schema_paths.append(out_path)
    return schema_paths


def validation_error_to_text(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in item['loc'])}: {item['msg']}" for item in error.errors()
    )
