"""闭包验证器内部专用小类型（spec §6）。

公开 schema（`Obligation` / `ObligationSet` / `ClosureSummary` /
`ClosureValidationResult` / `FactAtom` / `FactPack` / `RuleSlice` 及子 DTO /
5 个 enum）全部统一在 `evo_agent_baseline.contracts`，本文件不重定义。

本文件只放 closure 内部专用、不进跨模块契约的小类型：

- `ApplicabilityResult`   —— spec §6.3.2 适用性评估结果。
- `HighRiskItem`         —— spec §6.6.2 高风险项结构化条目。
- `ObligationNodeDTO`    —— spec §6.3.10.1 obligation_graph node。
- `ObligationEdgeDTO`    —— spec §6.3.10.1 obligation_graph edge。
- `VerifierConfig`       —— spec §6.6 主入口的第三参数。

spec→code 单向：本文件不得自创规格未授权的字段。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 公开 schema 从 contracts re-export，方便 closure 内部模块统一从 schema 取用。
from evo_agent_baseline.contracts import (  # noqa: F401
    BlockedReasonCode,
    ClosureStatus,
    ClosureSummary,
    ClosureValidationResult,
    FactAtom,
    FactPack,
    Obligation,
    ObligationKind,
    ObligationSet,
    OpenReasonCode,
    RuleCardDTO,
    RuleSlice,
    SatisfactionStatus,
)


class ApplicabilityResult(BaseModel):
    """适用性评估结果（spec §6.3.2）。"""

    state: Literal["applicable", "not_applicable", "uncertain"]
    matched_facts: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class HighRiskItem(BaseModel):
    """高风险项结构化条目（spec §6.6.2）。

    high_risk_items 是结构化列表，不是自由文本。
    """

    obligation_id: str
    severity: Literal["high", "medium", "low"]
    reason: str
    source_rule_card_id: str
    source_family_id: str
    evidence_fact_ids: List[str] = Field(default_factory=list)


class ObligationNodeDTO(BaseModel):
    """obligation_graph 的 node（spec §6.3.10.1）。

    rule_card v2 的 `obligation_graph.nodes[]` 透传为 dict，本 DTO 是
    closure 内部对该 dict 的结构化视图（用 `from_dict` 构造，缺字段给默认值）。

    A.0（spec 草案 v4）：补 `frozen=True, extra="forbid"` 与其余八源 typed DTO 同契约。
    **母病闸真生效（copilot 阻断#2 修）**：`from_dict` **不预筛键**——原始 dict 全键透传给
    构造器，未知键触发 extra=forbid → ValidationError（防 graph 段新字段静默漂移；旧实现
    只映已声明字段，extra=forbid 永不触发＝化妆品）。真卡枚举确认 node 恰 8 键（401/401
    完整、无 None、无多余键），故透传对现行真卡解析安全；仅对 node_kind 未知值归一
    （→ obligation，保 `test_method_semantics` 的 `node_kind="duty"` 现行语义）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    obligation_node_id: str
    node_kind: Literal["obligation", "prohibition", "escalation"]
    actor: str = ""
    action: str = ""
    recipient_ids: List[str] = Field(default_factory=list)
    artifact_ids: List[str] = Field(default_factory=list)
    deadline_ids: List[str] = Field(default_factory=list)
    trigger_condition_ids: List[str] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ObligationNodeDTO":
        """从 rule_card 透传的 node dict 构造（全键透传，未知键→ValidationError）。

        node_kind 未知值归一为 obligation（现行语义）；obligation_node_id 缺失补 ""（现行
        默认，保派生器行为不破）。除此之外 **不预筛、不丢键**——extra=forbid 真拦漂移。
        """
        data = dict(raw)
        node_kind = data.get("node_kind", "obligation")
        if node_kind not in {"obligation", "prohibition", "escalation"}:
            node_kind = "obligation"
        data["node_kind"] = node_kind
        data.setdefault("obligation_node_id", "")
        return cls(**data)


class ObligationEdgeDTO(BaseModel):
    """obligation_graph 的 edge（spec §6.3.10.1）。

    spec §6.3.10.1 只给 source/target/relation 三字段；§6.3.10.5 伪代码引用了
    `edge.obligation_edge_id`，故保留 `obligation_edge_id` 字段，但它 **始终由
    from_dict 从 source/target/relation 三元组派生**（派生值权威，源端注入一律丢弃）。
    relation 未知值不在构造期强制，留给 §6.3.10.5 判 `unsupported_obligation_edge_relation`。

    A.0（spec 草案 v4）：补 `frozen=True, extra="forbid"`（同 NodeDTO）。真实 edge 无
    `edge_id`（三字段 source/target/relation，真卡枚举 4/4 恰 3 键），`obligation_edge_id`
    为从三元组派生的便捷字段（非 JSON 源字段），A.6 矩阵按 derived 标注。
    **母病闸真生效（copilot 阻断#2 修 + 收口残留修）**：`from_dict` 除派生
    obligation_edge_id 外 **不预筛键**，未知键触发 extra=forbid → ValidationError；
    并加 `model_validator(mode="before")` **无条件**从三元组重派生 obligation_edge_id，
    使**直构（`ObligationEdgeDTO(...)`）与 from_dict 统一不可伪造**——任何构造路径传入的
    `obligation_edge_id` 一律**丢弃**（派生值权威）。真卡 edge 4/4 恰 3 键、从不带 edge_id，
    故对现行真卡路径零行为变化。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_node_id: str
    target_node_id: str
    relation: str
    obligation_edge_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive_edge_id(cls, data: Any) -> Any:
        """统一所有构造路径：无条件从 source/target/relation 三元组重派生
        obligation_edge_id，丢弃任何传入值（直构与 from_dict 都不可伪造，派生值权威）。

        仅对 dict 输入生效（正常构造路径）；缺三元组键时以 "" 兜底派生，required 校验
        随后仍由 pydantic 逮（missing source/target/relation → ValidationError）。绝不
        pop/改动其它键——未知键交由 extra=forbid 拦（母病闸不被绕过）。
        """
        if isinstance(data, dict):
            data = dict(data)
            src = data.get("source_node_id", "")
            tgt = data.get("target_node_id", "")
            rel = data.get("relation", "")
            data["obligation_edge_id"] = f"{src}->{tgt}:{rel}"
        return data

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ObligationEdgeDTO":
        """从 rule_card 透传的 edge dict 构造（全键透传，未知键→ValidationError）。

        `obligation_edge_id` 由 `_derive_edge_id`（model_validator）**始终**从三元组派生
        （派生值权威，源端注入一律丢弃）；本方法只补三源键缺省 ""（现行默认，保派生器行为
        不破），除此**不预筛、不丢其它键**——extra=forbid 真拦漂移。真卡 edge 4/4 恰 3 键、
        从不带 edge_id，故此路径零行为变化（派生结果与旧实现同）。
        """
        data = dict(raw)
        data.setdefault("source_node_id", "")
        data.setdefault("target_node_id", "")
        data.setdefault("relation", "")
        return cls(**data)


class VerifierConfig(BaseModel):
    """闭包验证器运行配置（spec §6.6 主入口第三参数）。

    spec §6.6 伪代码 `compute_allow_stop(summary, guard_result=config.guard_result)`：
    `guard_result` 携带 pre_run_input_guard 的禁止源审计结论，是 allow_stop
    的输入之一。`numeric_tolerance` 用于 §6.4.4 数值等价判定（默认 1e-9）。
    """

    verifier_version: str = "evo-agent-baseline-closure-v0.4"
    numeric_tolerance: float = 1e-9
    # pre_run_input_guard 结果；至少含 forbidden_source_check_passed。
    guard_result: Dict[str, Any] = Field(
        default_factory=lambda: {"forbidden_source_check_passed": True}
    )


__all__ = [
    "ApplicabilityResult",
    "HighRiskItem",
    "ObligationNodeDTO",
    "ObligationEdgeDTO",
    "VerifierConfig",
    # re-export
    "Obligation",
    "ObligationSet",
    "ClosureSummary",
    "ClosureValidationResult",
    "FactAtom",
    "FactPack",
    "RuleSlice",
    "RuleCardDTO",
    "ObligationKind",
    "ClosureStatus",
    "SatisfactionStatus",
    "BlockedReasonCode",
    "OpenReasonCode",
]
