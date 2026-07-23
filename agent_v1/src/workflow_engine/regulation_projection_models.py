"""W2 法规映射层输出对象 dataclass。

按 W2 spec 09 输出契约 + W0 spec 04 §17-§22 字段合约：
- ThresholdEval（spec 04 §20）
- ReportBasisItem（spec 04 §21，5 kind）
- ProjectionFamilyEval（spec 04 §19）
- NormativeProjection（spec 04 §18，per-fragment 主输出对象）

DEBT-018-followup-1 第一波 2026-05-13 拆迁：
本文件原物理位置在 `agent_v1/src/workflow_engine/worldgen/models.py` L399-L470，
按 DEBT-030 §A 组 + DEBT-031 gap 13/14 同源耦合点解除，迁到 W2 平级位置
（跟现有 regulation_projection.py / regulation_projection_executor.py 等
W2 端代码同级）。

共享类型（SeverityBand / CoverageStatus）仍引自 W0 worldgen.constants —
按 W2 spec 10 §4 dependency import audit：W2 → W0 单向消费是允许的边界。

2026-05-13 同步：sidecar_join_status 由原 4 枚举（含 `sidecar_derivation_failed`）
撤回为 3 枚举（`available / partial / unavailable`），sidecar 派生失败场景归
`unavailable` + `unknown_reason_code = sidecar_only_fact_pattern` 扩义承担细分语义。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from workflow_engine.worldgen.constants import CoverageStatus, SeverityBand


__all__ = [
    "ThresholdOperator",
    "ThresholdRegime",
    "ApplicabilityState",
    "ExpectedVerdict",
    "FamilyVerdict",
    "ProjectionStatus",
    "ThresholdEval",
    "ReportBasisItem",
    "ProjectionFamilyEval",
    "NormativeProjection",
    "CoverageControlBatchMetadata",
]


ThresholdOperator = Literal["<=", "<", ">=", ">", "==", "!=", "in", "not_in"]
ThresholdRegime = Literal[
    "far_below",
    "near_below",
    "exact_threshold",
    "near_above",
    "far_above",
    "not_numeric",
]
# W2-009 / spec 09 §4: ProjectionFamilyEval.applicability_state 4 enum
ApplicabilityState = Literal["applicable", "neighbor", "inapplicable", "uncovered"]
# W2-001 / spec 09 §2 + §3: NormativeProjection.expected_verdict 4 enum；NI-008 红线禁 pending
ExpectedVerdict = Literal["pass", "fail", "unknown", "not_applicable"]
# spec 09 §4: ProjectionFamilyEval.verdict 4 enum；与 expected_verdict 同 enum 空间
FamilyVerdict = Literal["pass", "fail", "unknown", "not_applicable"]
# W2-004 / spec 09 §2: projection_status 3 enum（封口总则 row projection_status）
ProjectionStatus = Literal["covered", "uncovered", "conflict"]


class ThresholdEval(BaseModel):  # T-14 新建，spec 04 §20
    rule_id: str
    # DEBT-054 Block B.1：规则卡制度键 threshold_regime_id（required，非 Optional——
    # 忘透传即 ValidationError，防"缺字段仍生成合法 v2"）。⊥ regime_tag（观测分箱六值，
    # coverage_control 依赖，二者正交并存、命名勿混）。空串按缺失 hard-fail。
    threshold_regime_id: str
    slot_id: str
    operator: ThresholdOperator
    threshold_value: Union[float, bool, str, List[Any]]
    observed_value: Union[float, bool, str]
    regime_tag: ThresholdRegime
    pass_bool: bool

    @field_validator("threshold_regime_id")
    @classmethod
    def _threshold_regime_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "threshold_regime_id_empty: ThresholdEval.threshold_regime_id 必填非空"
                "（Block B.1，空串按缺失 hard-fail）"
            )
        return v


class ReportBasisItem(BaseModel):  # T-14 拆 5 kind，spec 04 §21
    basis_kind: Literal[
        "threshold_compare",
        "bool_assertion",
        "family_uncovered",
        "world_origin",
        "measurement_origin",
    ]
    basis_id: str = ""  # T-14 新增
    family_id: str = ""  # T-14 新增
    rule_id: str = ""  # T-14 新增
    slot_id: str = ""
    source_projection_id: str = ""  # T-14 新增
    # threshold_compare 专用
    operator: Optional[ThresholdOperator] = None
    threshold_value: Union[float, bool, str, List[Any], None] = None
    unit: Optional[str] = None
    regime_tag: Optional[ThresholdRegime] = None
    # bool_assertion 专用
    expected_value: Optional[Any] = None
    statement_code: Optional[str] = None
    # family_uncovered 专用
    reason_code: Optional[str] = None
    candidate_known_families: List[str] = Field(default_factory=list)
    # 通用
    observed_value: Any = None
    pass_bool: Optional[bool] = None
    # legacy 工程辅助（D04-3 保留）
    source_ref: str = ""


class ProjectionFamilyEval(BaseModel):
    family_id: str
    applicability_score: float
    # W2-009: applicability_state 改为 4 enum Literal（spec 09 §4）
    applicability_state: ApplicabilityState
    trigger_ids: List[str] = Field(default_factory=list)
    rule_ids: List[str] = Field(default_factory=list)  # T-14 补，spec 04 §19
    slot_role_map: Dict[str, str] = Field(default_factory=dict)
    threshold_evaluations: List[ThresholdEval] = Field(default_factory=list)  # T-14 新增
    # spec 09 §4: family-level verdict 4 enum；与顶层 expected_verdict 同 enum 空间
    verdict: FamilyVerdict = "unknown"


class NormativeProjection(BaseModel):
    projection_id: str
    projection_registry_id: str
    projection_family: str
    world_id: str
    # W2-002: 新增 fragment_id 必填字段（spec 09 §2 + projection_id 拼接需要）
    fragment_id: str
    projection_version: str = "2.0.0"
    matched_families: List[ProjectionFamilyEval] = Field(default_factory=list)
    selected_family: str = "unknown"
    # W2-004: projection_status 3 enum（covered/uncovered/conflict，spec 09 §2；NO unknown）
    projection_status: ProjectionStatus = "covered"
    # W2-001: 新增 expected_verdict 必填字段（spec 09 §2 + §3 4 派生规则）
    expected_verdict: ExpectedVerdict
    required_slots: List[str] = Field(default_factory=list)
    basis_items: List[ReportBasisItem] = Field(default_factory=list)
    unknown_reason_code: Optional[str] = None
    sidecar_join_status: str = "available"
    severity_band: SeverityBand = "moderate"
    required_world_core_slots: List[str] = Field(default_factory=list)
    required_measurement_slots: List[str] = Field(default_factory=list)
    required_qualifier_slots: List[str] = Field(default_factory=list)
    required_sidecar_interfaces: List[str] = Field(default_factory=list)
    matched_component_refs: List[str] = Field(default_factory=list)
    matched_measurement_ids: List[str] = Field(default_factory=list)
    coverage_status: CoverageStatus
    notes: List[str] = Field(default_factory=list)


# W2-007 (批次 D 2026-05-21)：spec 11 §3.2 coverage-controlled rejection batch metadata.
# 6 字段全按 spec 11 §3.2 表；位置在 W2 模型层（跟 NormativeProjection 平级），
# 不污染 NormativeProjection（spec 11 §3.2 "per-sample rejection trace 不进 NormativeProjection"）.
#
# NI 红线：
#   - public_report_note 不暴露 internal target ratio（spec 11 §3.2 / §4.2 / NI-004）.
#   - bucket counts 是 batch audit / 大汇报材料，不作 evo-agent feature pipeline 输入.
#   - rejection reason 不回传 W1（spec 11 §3.3 / NI-002 rule-blind 红线）.
class CoverageControlBatchMetadata(BaseModel):
    coverage_control_profile_id: str  # spec 11 §3.2 row 1，如 "CCP-MBIS-V1"
    raw_candidate_bucket_counts: Dict[str, int] = Field(default_factory=dict)  # spec §3.2 row 2
    accepted_bucket_counts: Dict[str, int] = Field(default_factory=dict)  # spec §3.2 row 3
    rejected_bucket_counts: Dict[str, int] = Field(default_factory=dict)  # spec §3.2 row 4
    bucket_definition_version: str  # spec §3.2 row 5
    public_report_note: str = ""  # spec §3.2 row 6（只说做了边界覆盖控制，不暴露 target ratio）
