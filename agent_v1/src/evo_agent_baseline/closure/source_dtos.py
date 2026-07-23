"""A.0 生产源 typed DTO ingress 边界（spec 草案 v4 Block A §A.0）。

Phase 0/1 地基交付（**未接线进 live 派生器；不改 RuleCardDTO 现行 dict 透传；
不改 compute_obligation_id / dedupe_key / validate_building_closure 现行行为**）：

为九个生产源子结构各定义 typed frozen DTO（`model_config = ConfigDict(
frozen=True, extra="forbid")`），未知键 → 校验失败、不静默进入。字段名 / 类型以
**真实 397 卡枚举为准**（`agent_v1/regulations/rulecard_v2/mbis_cop_2023/
rule_cards.json`），非顺编 spec。

九源（对应 `RuleCardDTO` 内嵌裸容器，`contracts.py` L444-453）：

1. applicability            → ``ApplicabilityDTO``
2. trigger_conditions       → ``TriggerConditionsDTO`` + ``TriggerItemDTO``
3. workflow_operands        → ``WorkflowOperandsDTO`` + ``RecipientDTO`` /
                              ``WorkflowArtifactDTO`` / ``WorkflowDeadlineDTO``
4. slot_role_map[]          → ``SlotRoleDTO``
5. threshold_regimes[]      → ``ThresholdRegimeDTO`` + ``FormulaDTO`` /
                              ``FormulaVariableDTO``
6. evidence_requirements    → ``EvidenceRequirementsDTO`` + ``EvidenceRequirementDTO``
7. exceptions[]             → ``ExceptionDTO``（corpus-empty，按 deriver 消费键声明）
8. definitions[]            → ``DefinitionDTO``
9. obligation_graph         → ``ObligationNodeDTO`` / ``ObligationEdgeDTO``
                              （已存 `schema.py`，本单元补 frozen+extra=forbid）

跨源共享值对象 ``QualifierSetDTO``（八键空间，extra=forbid → 第九键报错，
对齐 C.6 / C.9 `unknown_qualifier_key`）。

**据实报的指令锚点漂移**（见文末 `INSTRUCTION_ANCHOR_DRIFT`）：
- recipients 真实字段 = ``recipient_id / recipient_type / recipient_key /
  delivery_mode``；v4 A.0 表（L53）/ A.6 表（L419）写作 ``type`` / ``key``——
  本 DTO 用真实字段名 ``recipient_type`` / ``recipient_key``。
- definitions 真实字段 = ``definition_id / term_key / definition_text /
  scope_note / source_quote_refs``；deriver 曾读 ``slot_id`` / ``source_quote_id``
  与真实字段不符（附录 D §D.2 已标注）——本 DTO 用真实字段名。

blind 红线（A.9）：本模块**禁 import** `eval.*` / `TruthBundle` /
`threshold_evaluations` / `workflow_engine`；仅 import 同包 `schema`（Node/Edge）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator

# obligation_graph node/edge DTO 已存于 schema.py（本单元补 frozen+extra=forbid）。
from .schema import ObligationEdgeDTO, ObligationNodeDTO  # noqa: F401

# 阻断#3（copilot 对抗审残留）：加 `strict=True` —— str 不再自动转 bool/int/float，
# type-wrong 源数据 → ValidationError（弱类型闸真生效，非空转）。nested BaseModel 字段
# 在 strict 下仍接受 dict 输入（实测），故对现行真卡 `**dict` 构造安全。
_FROZEN_FORBID = ConfigDict(frozen=True, extra="forbid", strict=True)


# ===========================================================================
# 跨源共享值对象：qualifiers 八键空间（C.6 / C.9）
# ===========================================================================

# 规则卡 qualifiers 八键（枚举全 397 卡 slot_role/trigger/threshold 三源，无第九键）。
QUALIFIER_EIGHT_KEYS = (
    "artifact_key",
    "component_type_key",
    "location_class_key",
    "actor_role_key",
    "defect_class_key",
    "method_key",
    "risk_class_key",
    "material_class_key",
)


class QualifierSetDTO(BaseModel):
    """qualifiers 八键值对象（C.6；extra=forbid → 第九键报错 = C.9 unknown_qualifier_key）。

    slot_role_map / trigger_conditions.items / threshold_regimes 三源共用同一
    八键空间（真实枚举确认，无跨源第九键）。值均为字符串。
    """

    model_config = _FROZEN_FORBID

    artifact_key: Optional[str] = None
    component_type_key: Optional[str] = None
    location_class_key: Optional[str] = None
    actor_role_key: Optional[str] = None
    defect_class_key: Optional[str] = None
    method_key: Optional[str] = None
    risk_class_key: Optional[str] = None
    material_class_key: Optional[str] = None


# ===========================================================================
# 1. applicability（单 dict）
# ===========================================================================


class ApplicabilityDTO(BaseModel):
    """applicability 单 dict（真实字段各 397/397）。

    适用性评估输入（`evaluate_applicability`）；评估结论落 `state.applicability_state`。
    spec A.6 另设想未来 scope-audit 义务（source_channel=applicability，进 identity），
    该路径**尚未接线**，本单元按当前具体消费（→ state）分类，见源覆盖矩阵。
    """

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：七字段全 397/397 存在 → **全 required**（去默认值，缺字段→
    # ValidationError）；四列表元素真卡全 str（actors/building_scope/component_scope/
    # exclusions），故 List[str] 非裸 List[Any]。
    regime: str
    actors: List[str]
    phase: str
    subject: str
    component_scope: List[str]
    building_scope: List[str]
    exclusions: List[str]


# ===========================================================================
# 2. trigger_conditions.{logic, items[]}
# ===========================================================================


class TriggerItemDTO(BaseModel):
    """trigger_conditions.items[] 元素（真实枚举 376 items）。

    condition_id/predicate_kind/operator/expected_value 各 376/376（必填）；
    slot_ref_id 370/376、measure_key/qualifiers/unit 各 6/376（measure-trigger 才有，
    Optional）。predicate_kind 真值域 ∈ {slot(370), measure(6)}（B1）。
    """

    model_config = _FROZEN_FORBID

    condition_id: str
    predicate_kind: str
    operator: str
    # 收紧（阻断#3）：真卡枚举 376/376 存在，值域恰 {bool(370),int(2),float(4)}。
    # fail-closed 连贯设计 §3：identity 入口经 `rulecard_decimal_load`（parse_float=Decimal）
    # 读，float token → Decimal（非二进制 float）→ 值域 {bool,int,Decimal}；strict Union
    # **拒 Python float**（float ingress 必炸，与 `_literal_value` 一致），Decimal 保真。
    expected_value: Union[bool, int, Decimal]
    slot_ref_id: Optional[str] = None
    measure_key: Optional[str] = None
    qualifiers: Optional[QualifierSetDTO] = None
    unit: Optional[str] = None


class TriggerConditionsDTO(BaseModel):
    """trigger_conditions 顶层（logic / items 各 397/397）。"""

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：logic/items 全 397/397 存在 → required（items 空列表卡照样带键）。
    logic: str
    items: List[TriggerItemDTO]


# ===========================================================================
# 3. workflow_operands（+ recipients / artifacts / deadlines）
# ===========================================================================


class RecipientDTO(BaseModel):
    """workflow_operands.recipients[] 元素（对象；真实 62 条各 4 字段）。

    ⚠️ 真实字段 = recipient_id / recipient_type / recipient_key / delivery_mode；
    v4 A.0/A.6 表写 type/key 系锚点漂移（见 INSTRUCTION_ANCHOR_DRIFT）。closure
    仅消费 recipient_id（deriver:1836，悬空校验集）；其余三字段未消费。

    **兼容裸 str（阻断#4 / 附录 D §D.7）**：真卡语料 62 条**全对象**，但 deriver
    `:1836/:1840` 兼容 `isinstance(r, str)`。ingress 归一：裸串 → `{recipient_id: <串>,
    其余三字段 ""}`（见 `from_raw` 与 `WorkflowOperandsDTO._normalize_recipients`）。四字段
    保持 required（对象形须齐 4 键，missing 由 pydantic 逮＝防对象形丢字段漂移）。
    """

    model_config = _FROZEN_FORBID

    recipient_id: str
    recipient_type: str
    recipient_key: str
    delivery_mode: str

    @staticmethod
    def normalize_raw(raw: Any) -> Any:
        """归一单个 recipient 源值：裸 str → 对象 dict；dict 原样返回（供 field_validator）。"""
        if isinstance(raw, str):
            return {
                "recipient_id": raw,
                "recipient_type": "",
                "recipient_key": "",
                "delivery_mode": "",
            }
        return raw

    @classmethod
    def from_raw(cls, raw: Any) -> "RecipientDTO":
        """从对象 dict 或裸 str 构造 RecipientDTO（裸串归一为仅 recipient_id 有值）。"""
        return cls(**cls.normalize_raw(raw))


class WorkflowArtifactDTO(BaseModel):
    """workflow_operands.artifacts[] 元素（真实 326 条各 3 字段）。"""

    model_config = _FROZEN_FORBID

    artifact_id: str
    artifact_type: str
    artifact_key: str


class WorkflowDeadlineDTO(BaseModel):
    """workflow_operands.deadlines[] 元素（真实 25 条）。

    deadline_id/relation/time_anchor_key 各 25/25（必填）；offset_value/offset_unit
    各 15/25（Optional）。⚠️ 现 deriver 未读 offset_unit（附录 D §D.6）——本 DTO 收录
    是「数据有、代码此前未消费」的补齐。
    """

    model_config = _FROZEN_FORBID

    deadline_id: str
    relation: str
    time_anchor_key: str
    # 收紧（阻断#3）：present 15/25（Optional 正确）；present 时真卡全 int → Optional[int]
    # 非裸 Any（未来若现 decimal offset＝真漂移，闸应逮，不预容）。
    offset_value: Optional[int] = None
    offset_unit: Optional[str] = None


class WorkflowOperandsDTO(BaseModel):
    """workflow_operands 顶层（真实 7 顶字段各 397/397）。

    primary_actor/primary_action 仅 KG ingest 消费、closure 不读（附录 D §D.3）；
    audiences 真实全空（`rulecard_loader.py:164` 非空透传+warning）。
    """

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：七顶字段全 397/397 存在 → **全 required**（去默认值）。空列表卡
    # （audiences 真实全空、recipients/deadlines 部分卡空）照样带键，故 required 不误伤。
    primary_actor: str
    primary_action: str
    recipients: List[RecipientDTO]
    artifacts: List[WorkflowArtifactDTO]
    deadlines: List[WorkflowDeadlineDTO]
    # audiences 真实全空（无元素可枚举），收紧 List[str]（阻断#3：非裸 Any；空列表满足）。
    audiences: List[str]
    method_keys_allowed: List[str]

    @field_validator("recipients", mode="before")
    @classmethod
    def _normalize_recipients(cls, v: Any) -> Any:
        """阻断#4 / §D.7：裸 str recipient → 对象 dict（ingress 归一，保 deriver 兼容）。"""
        if isinstance(v, list):
            return [RecipientDTO.normalize_raw(r) for r in v]
        return v


# ===========================================================================
# 4. slot_role_map[]
# ===========================================================================


class SlotRoleDTO(BaseModel):
    """slot_role_map[] 元素（真实 769 条各 5 字段）。"""

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：五字段全 769/769 存在 → required（roles 元素全 str）。
    slot_ref_id: str
    slot_id: str
    qualifiers: QualifierSetDTO
    roles: List[str]
    required: bool


# ===========================================================================
# 5. threshold_regimes[]（+ formula 嵌套 DTO）
# ===========================================================================


class FormulaVariableDTO(BaseModel):
    """threshold_regimes[].formula.variables[] 元素（真实 measure_key + symbol）。"""

    model_config = _FROZEN_FORBID

    measure_key: str
    symbol: str


class FormulaDTO(BaseModel):
    """threshold_regimes[].formula 嵌套 DTO（真实 3 条：expression + variables[]）。"""

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：expression/variables 全 3/3 存在 → required。
    expression: str
    variables: List[FormulaVariableDTO]


class ThresholdRegimeDTO(BaseModel):
    """threshold_regimes[] 元素（真实 41 条）。

    threshold_regime_id/measure_key/operator/unit/qualifiers/source_quote_refs 各
    41/41（必填）；value 38/41、time_anchor_key 7/41、formula 3/41（Optional）。
    operator 真值域 = {<=(15),>(2),>=(17),formula(3),<(1),==(3)}（无 in/not_in/!=）。
    """

    model_config = _FROZEN_FORBID

    threshold_regime_id: str
    measure_key: str
    operator: str
    unit: str
    qualifiers: QualifierSetDTO
    # 收紧（阻断#3）：source_quote_refs 41/41 全 str → **required**（去默认值）；value
    # present 38/41（Optional 正确），present 时真卡混 int(25)/float(13) →
    # Optional[Union[int,float]] 非裸 Any（实测保真）。
    source_quote_refs: List[str]
    # fail-closed 连贯设计 §3：value 剔 float 纳 Decimal——identity 入口经
    # `rulecard_decimal_load`（parse_float=Decimal）读，float token → Decimal；strict
    # Union[int, Decimal] **拒 Python float**（float ingress 必炸），int/Decimal 保真。
    # present 38/41（Optional 正确），present 时真卡混 int(25)/decimal-token(13)。
    value: Optional[Union[int, Decimal]] = None
    time_anchor_key: Optional[str] = None
    formula: Optional[FormulaDTO] = None


# ===========================================================================
# 6. evidence_requirements.{for_matching, for_submission, for_completion}[]
# ===========================================================================


class EvidenceRequirementDTO(BaseModel):
    """evidence_requirements.*[] 元素（真实 370 条各 8 字段）。"""

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：八字段全 370/370 存在 → **全 required**（四列表元素全 str）。
    evidence_requirement_id: str
    kind: str
    required: bool
    description: str
    artifact_ids: List[str]
    slot_ref_ids: List[str]
    measure_keys: List[str]
    required_field_groups: List[str]


class EvidenceRequirementsDTO(BaseModel):
    """evidence_requirements 顶层（三组各 397/397）。"""

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：三组全 397/397 存在 → required（空组卡照样带键）。
    for_matching: List[EvidenceRequirementDTO]
    for_submission: List[EvidenceRequirementDTO]
    for_completion: List[EvidenceRequirementDTO]


# ===========================================================================
# 7. exceptions[]（corpus-empty，按 deriver evaluate_exception 消费键声明）
# ===========================================================================


class ExceptionDTO(BaseModel):
    """exceptions[] 元素（⚠️ 全 397 卡 0 条）。

    schema 按 deriver `evaluate_exception` 消费键声明（obligation_deriver.py:
    1372/1373/1385 读 slot_id / exception_kind / qualifiers）。corpus-empty，
    真实字段无从枚举，故按代码消费契约声明。
    """

    model_config = _FROZEN_FORBID

    slot_id: str
    exception_kind: str
    qualifiers: Optional[QualifierSetDTO] = None


# ===========================================================================
# 8. definitions[]
# ===========================================================================


class DefinitionDTO(BaseModel):
    """definitions[] 元素（真实仅 1 条）。

    ⚠️ 真实字段 = definition_id / term_key / definition_text / scope_note /
    source_quote_refs；deriver 曾读 slot_id / source_quote_id 与真实字段不符
    （附录 D §D.2）。本 DTO 用**真实字段名**（见 INSTRUCTION_ANCHOR_DRIFT）。
    """

    model_config = _FROZEN_FORBID

    # 收紧（阻断#3）：五字段全 1/1 存在 → required（source_quote_refs 元素全 str）。
    definition_id: str
    term_key: str
    definition_text: str
    scope_note: str
    source_quote_refs: List[str]


# ===========================================================================
# 据实报：读真实卡与 v4 A.0/A.6 指令锚点不符处（供矩阵测试与汇报引用）
# ===========================================================================

INSTRUCTION_ANCHOR_DRIFT = {
    "recipients_field_names": (
        "v4 A.0 表 L53 / A.6 表 L419 写 recipient 对象字段为 recipient_id/type/key/"
        "delivery_mode；真实 62 条 recipients 字段名为 recipient_id/recipient_type/"
        "recipient_key/delivery_mode（type→recipient_type, key→recipient_key）。"
        "本 DTO 采真实字段名。"
    ),
    "definitions_deriver_field_mismatch": (
        "definitions 真实字段 = definition_id/term_key/definition_text/scope_note/"
        "source_quote_refs（唯 1 条）；deriver 读 slot_id/source_quote_id 与真实字段"
        "不符（v4 附录 D §D.2 已自报）。本 DTO 采真实字段名。"
    ),
    "transform_vocab_count": (
        "v4 L865 述 transform 词表『19 值』，但 L390 实列 18 值。矩阵按 L390 实列 18 "
        "值为准（executable table 权威）；差 1 疑为 L865 计数笔误或含 a/b 复合格误计。"
    ),
}


__all__ = [
    "QUALIFIER_EIGHT_KEYS",
    "QualifierSetDTO",
    "ApplicabilityDTO",
    "TriggerItemDTO",
    "TriggerConditionsDTO",
    "RecipientDTO",
    "WorkflowArtifactDTO",
    "WorkflowDeadlineDTO",
    "WorkflowOperandsDTO",
    "SlotRoleDTO",
    "FormulaVariableDTO",
    "FormulaDTO",
    "ThresholdRegimeDTO",
    "EvidenceRequirementDTO",
    "EvidenceRequirementsDTO",
    "ExceptionDTO",
    "DefinitionDTO",
    # re-export（obligation_graph 源，已存 schema.py）
    "ObligationNodeDTO",
    "ObligationEdgeDTO",
    "INSTRUCTION_ANCHOR_DRIFT",
]
