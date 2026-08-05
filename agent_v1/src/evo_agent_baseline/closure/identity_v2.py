"""identity-v2 地基层 schema + 身份哈希 + merge 格（spec 草案 v4 Block A）。

Phase 0 交付（**未接线进 live 派生器、未改现有 compute_obligation_id/dedupe_key、
未动 validate_building_closure**）：

- A.2.1-A.2.6：全套 frozen 值对象（CanonicalBinding / DeadlineBinding /
  ObligationScope / VariableBinding / PredicateSpecV1（判别式）/
  CanonicalObligationIdentity（判别式）/ ImmutablePayload / BlueprintProvenance /
  ObligationBlueprint / RunInstanceEnvelope / ObligationStateV2（非 frozen）/
  ObligationProvenanceV2 / ObligationV2（组合模型 + source_operator audit））。
- A.5：canonical_json + 双哈希（canonical_identity_hash 不含 run；obligation_id 含
  run_envelope world/building）+ 碰撞后置检查 + `ObligationContractError`。
- A.2.4 非阻断⑤：`source_item_id` 复合键 canonical 编码。
- A.7：merge 格（标量 agreement-or-bottom + 状态 max-by-rank + closure 后投影 +
  B4 ⊥→blocked）+ reason code 全序表。

blind 红线（A.9）：本模块**禁 import** `eval.*` / `TruthBundle` /
`threshold_evaluations` / `workflow_engine`；只向下 import 中立 `canonical_profile`。
"""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, model_validator

from canonical_profile import (
    CANONICAL_PROFILE_ID,
    canonical_json,
    sha256_hex_24,
)

# v2→v3（2026-07-14，fail-closed 连贯设计 blocker 5）：本轮改了 `SourceChannel` 可接受集
# （删可写 scope、纳 applicability）+ 派生语义（binding qualifier 指纹进折叠键/局部引用、
# formula 匹配纳 output_measure、artifact 空键/悬空 hard-fail、卡级各源容器整体
# model_validate、总入口遇真模型缺口 fail-closed）→ 身份材料语义变，据版本纪律 bump v3。
# CANONICAL_PROFILE_ID 已 bump `mbis_canonical_v2` 保留（profile registry 变，另一维）。
#
# v3→v4（2026-07-15，identity-v2 身份模型缺口增补 / DEBT-054 收尾）：本轮补两真模型缺口 +
# method 子义务配套——`SourceChannel` 增 `workflow_deadline`（独立 deadline 义务）+ 放宽
# `obligation_graph` 判别式（普通/升级 node：predicate_kind∈{obligation,escalation}、spec=None）+
# 新绑定灌注（DeadlineBinding channel 化 + node 身份内嵌已解引用的完整 DeadlineBinding）+
# method_keys_allowed 进 `qualifiers` + method-derived 复合 SID（parts={"derived":"method"}）→
# 同一类身份材料语义变，据同一版本纪律 bump v4。
#
# v4→v5（2026-07-17，identity-v5 现网键切换增补 §4.1 / DEBT-054 最后一役）：本轮为切 live 主链新增
# **两个控制审计 channel**——`structural_scope_audit`（DEBT-050 fragment 结构 NA，fragment scope）+
# `trigger_aggregation_audit`（trigger 聚合 false 审计，building/fragment scope）；两 channel 均无谓词类
# （落 `_predicate_kind_spec_consistency` 的 else 分支：predicate_kind=""、spec=None）。新增控制审计 channel
# 属身份语义变，据版本纪律 bump v5。`CANONICAL_PROFILE_ID` 仍 `mbis_canonical_v2` 保留（profile registry
# 维度未变，与身份 schema 正交）。
IDENTITY_SCHEMA = "obligation_identity_v5"


class ObligationContractError(Exception):
    """义务身份契约致命错误（A.5 非阻断⑦）。

    **直接继承 Exception**，不继承任何被 `except Exception` 兜底吞掉的中间基类；
    约定所有 `except Exception` 兜底处须 `if isinstance(e, ObligationContractError): raise`
    （re-raise 白名单），使碰撞后置检查失败能直穿到调用方、终止产物发布。
    """


# ===========================================================================
# A.2.1 CanonicalBinding + DeadlineBinding
# ===========================================================================


class CanonicalBinding(BaseModel):
    """结构化绑定原子（A.2.1；slot/artifact/measure/time_anchor 四 namespace）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: Literal["slot", "artifact", "measure", "time_anchor"]
    resolution: Literal["resolved", "unresolved"]
    local_ref: str
    canonical_key: str

    @model_validator(mode="after")
    def _check_resolution_key_consistency(self) -> "CanonicalBinding":
        if self.resolution == "resolved":
            if self.canonical_key == "":
                raise ValueError("resolved binding 必须有非空 canonical_key")
        else:
            if self.canonical_key != "":
                raise ValueError("unresolved binding 的 canonical_key 必须为空")
        if self.local_ref == "" and self.resolution != "resolved":
            raise ValueError("unresolved binding 必须保留 local_ref 以区分")
        return self


class DeadlineBinding(BaseModel):
    """deadline 复合键绑定（A.2.1 / B2）——5 元复合键完整冻结进身份。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: Literal["deadline"]
    resolution: Literal["resolved", "unresolved"]
    local_ref: str
    canonical_key: str
    relation: str
    offset_value: str  # canonical decimal 字符串（C.8；"" 若无）
    offset_unit: str  # canonical unit（C.4；"" 若无）
    time_anchor_key: str  # canonical time_anchor 键（C.7；"" 若无）

    @model_validator(mode="after")
    def _check(self) -> "DeadlineBinding":
        if self.resolution == "resolved":
            if self.canonical_key == "":
                raise ValueError("resolved DeadlineBinding 必须有非空 canonical_key")
        else:
            if self.canonical_key != "":
                raise ValueError("unresolved DeadlineBinding 的 canonical_key 必须为空")
        if self.relation == "":
            raise ValueError("DeadlineBinding.relation 必填非空（deadline 义务身份核心）")
        return self


# ===========================================================================
# A.2.2 ObligationScope
# ===========================================================================


class ObligationScope(BaseModel):
    """判别式作用域（A.2.2）——取代平行 component_id（仲裁 1）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["building", "fragment"]  # 真需组件级时扩 "component"
    scope_id: str  # building: "" 楼级哨兵；fragment: fragment_id


# ===========================================================================
# A.2.3 VariableBinding + PredicateSpecV1
# ===========================================================================


class VariableBinding(BaseModel):
    """公式变量 canonical 绑定（A.2.3）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    canonical_measure_key: str
    qualifier_fingerprint: Tuple[Tuple[str, str], ...]


PredicateKindV1 = Literal[
    "threshold_literal",
    "threshold_formula",
    "bool_assertion",
    "prohibition",
    "obligation_edge",
]

_THRESHOLD_KINDS = {"threshold_literal", "threshold_formula"}
_NON_THRESHOLD_KINDS = {"bool_assertion", "prohibition", "obligation_edge"}


class PredicateSpecV1(BaseModel):
    """结构化谓词判别式（A.2.3；仲裁1 + 非阻断⑥判别式补全）。

    **B1**：枚举**不含** trigger 的 slot/measure——trigger 谓词不走 predicate_spec。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_schema: Literal["predicate_spec_v1"]
    predicate_kind: PredicateKindV1
    threshold_regime_id: str
    canonical_measure_key: str
    source_operator: Literal["<=", "<", ">=", ">", "==", "!=", "in", "not_in", "formula", ""]
    literal_value_tag: Literal["decimal", "string", "bool", "list", "none"]
    literal_value_canonical: str
    formula_id: str
    canonical_unit: str
    canonical_time_anchor_key: str
    threshold_qualifier_fingerprint: Tuple[Tuple[str, str], ...]
    variable_bindings: Tuple[VariableBinding, ...]

    @model_validator(mode="after")
    def _discriminant(self) -> "PredicateSpecV1":
        if self.predicate_kind in _THRESHOLD_KINDS:
            if self.threshold_regime_id == "":
                raise ValueError("threshold 谓词 threshold_regime_id 必填非空")
            if self.source_operator == "":
                raise ValueError("threshold 谓词 source_operator 必填非空")
            if self.canonical_measure_key == "":
                raise ValueError("threshold 谓词 canonical_measure_key 必填非空")
            if self.predicate_kind == "threshold_formula":
                if self.formula_id == "":
                    raise ValueError("threshold_formula 必须有 formula_id")
                if self.source_operator != "formula":
                    raise ValueError("threshold_formula 的 source_operator 必为 'formula'")
            else:  # threshold_literal
                if self.literal_value_tag == "none":
                    raise ValueError("threshold_literal 必须有字面值")
                if self.formula_id != "":
                    raise ValueError("threshold_literal 的 formula_id 必须空")
        elif self.predicate_kind in _NON_THRESHOLD_KINDS:
            if self.threshold_regime_id != "":
                raise ValueError("非 threshold 谓词 threshold_regime_id 必须空")
            if self.source_operator != "":
                raise ValueError("非 threshold 谓词 source_operator 必须空")
            if self.formula_id != "":
                raise ValueError("非 threshold 谓词 formula_id 必须空")
            if self.literal_value_tag != "none":
                raise ValueError("非 threshold 谓词 literal_value_tag 必须 none")
            if self.canonical_measure_key != "":
                raise ValueError("非 threshold 谓词 canonical_measure_key 必须空")
            if self.literal_value_canonical != "":
                raise ValueError("非 threshold 谓词 literal_value_canonical 必须空")
            if self.canonical_unit != "":
                raise ValueError("非 threshold 谓词 canonical_unit 必须空")
            if self.canonical_time_anchor_key != "":
                raise ValueError("非 threshold 谓词 canonical_time_anchor_key 必须空")
            if self.threshold_qualifier_fingerprint != ():
                raise ValueError("非 threshold 谓词 threshold_qualifier_fingerprint 必须空")
            if self.variable_bindings != ():
                raise ValueError("非 threshold 谓词 variable_bindings 必须空")
        return self


# ===========================================================================
# A.2.4 CanonicalObligationIdentity
# ===========================================================================

# fail-closed 连贯设计 §5：删可写 `scope` channel（与 identity.scope 作用域重名混义）——
# scope-audit 义务改走 `applicability` channel（`build_applicability_blueprint`）。构造器
# 拒 source_channel="scope"（不在 Literal → pydantic ValidationError）。
SourceChannel = Literal[
    "evidence",
    "workflow_artifact",
    "workflow_deadline",  # v4 新增：独立 workflow_operands.deadlines 义务通道（无谓词类）
    "exception",
    "definition",
    "threshold",
    "trigger",
    "obligation_graph",
    "slot_role",
    "applicability",
    # v5 新增（identity-v5 现网键切换增补 §3.4，冻结字符串，落码不得改）：两个控制审计 channel，
    # 均为无谓词类（落 `_predicate_kind_spec_consistency` else 分支：predicate_kind=""、spec=None）。
    "structural_scope_audit",  # DEBT-050 fragment 结构 NA（fragment scope，§3.4.1）
    "trigger_aggregation_audit",  # trigger 聚合 false 审计（building/fragment scope，§3.4.2）
]


def encode_source_item_id(
    channel: str, primary_id: str, parts: Optional[dict] = None
) -> str:
    """非阻断⑤ source_item_id 复合键 canonical 编码（A.2.4）。

    定长键集 `{channel, primary_id, parts}`；parts 内子键 NFC 升序、值 canonical。
    同一载体恒同 source_item_id；不同 evidence kind/required_field_groups 复合区分。
    """
    return canonical_json(
        {
            "channel": channel,
            "primary_id": primary_id,
            "parts": parts or {},
        }
    )


class CanonicalObligationIdentity(BaseModel):
    """v2 身份（A.2.4；frozen；改进3 profile_id 进身份；B1/B2 落点）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_schema: Literal["obligation_identity_v5"]
    canonical_profile_id: str
    source_rule_card_id: str
    kind: str
    scope: ObligationScope
    obligation_node_id: str
    obligation_edge_ids: Tuple[str, ...]
    actor: str
    action: str
    recipient_ids: Tuple[str, ...]
    slot_bindings: Tuple[CanonicalBinding, ...]
    artifact_bindings: Tuple[CanonicalBinding, ...]
    measure_bindings: Tuple[CanonicalBinding, ...]
    deadline_bindings: Tuple[DeadlineBinding, ...]
    time_anchor_bindings: Tuple[CanonicalBinding, ...]
    source_channel: SourceChannel
    source_item_id: str
    predicate_kind: str
    source_predicate_spec: Optional[PredicateSpecV1]
    qualifiers: Tuple[Tuple[str, str], ...]

    @model_validator(mode="after")
    def _predicate_kind_spec_consistency(self) -> "CanonicalObligationIdentity":
        """B1：放宽为「仅 threshold 类须一致」的 predicate_kind ↔ spec 判别式。"""
        ch = self.source_channel
        pk = self.predicate_kind
        spec = self.source_predicate_spec
        if ch == "threshold":
            if pk not in _THRESHOLD_KINDS:
                raise ValueError("threshold 源 predicate_kind 须 ∈ {threshold_literal, threshold_formula}")
            if spec is None or spec.predicate_kind != pk:
                raise ValueError("threshold 源 predicate_kind 须 == source_predicate_spec.predicate_kind")
        elif ch == "trigger":
            if pk not in {"slot", "measure"}:
                raise ValueError("trigger 源 predicate_kind 须 ∈ {slot, measure}")
            if spec is not None:
                raise ValueError("trigger 源 source_predicate_spec 须为 None（B1：trigger 不走 predicate_spec）")
        elif ch == "obligation_graph":
            if pk in {"prohibition", "obligation_edge"}:
                # threshold-scoped 载荷全空的 NON_THRESHOLD spec（历史标记）；须一致。
                if spec is None or spec.predicate_kind != pk:
                    raise ValueError(
                        "obligation_graph 源 predicate_kind 须 == source_predicate_spec.predicate_kind"
                    )
            elif pk in {"obligation", "escalation"}:
                # v4 放宽：普通/升级 node（predicate_kind = raw node_kind）无 threshold 谓词，
                # source_predicate_spec 须为 None（node 主义务 truthy 判定属求值态归 state）。
                if spec is not None:
                    raise ValueError("普通/升级 node source_predicate_spec 须为 None")
            else:
                # 防御纵深（belt-and-suspenders）：raw-kind 闸已在派生入口拒未知 raw node_kind，
                # 真卡不可达此分支；若构造器被直接绕过传未知 predicate_kind，仍二次拦。
                raise ValueError(
                    f"obligation_graph 源未知 predicate_kind:{pk}"
                )
        else:
            # 其余无谓词类
            if pk != "":
                raise ValueError(f"{ch} 源 predicate_kind 须为空")
            if spec is not None:
                raise ValueError(f"{ch} 源 source_predicate_spec 须为 None")
        return self


# ===========================================================================
# A.2.5 ImmutablePayload + BlueprintProvenance + ObligationBlueprint
# ===========================================================================


class ImmutablePayload(BaseModel):
    """不进 identity、进 dedupe 一致性校验（A.2.5 / A.7）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required: bool
    canonical_unit: str
    source_operator: str  # = identity.source_predicate_spec.source_operator（改进1）


class BlueprintProvenance(BaseModel):
    """阶段一 provenance（A.2.5）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    world_id: str
    building_id: str
    source_family_id: str
    slot_ref_ids: Tuple[str, ...]
    artifact_local_ids: Tuple[str, ...]
    source_clause_ids: Tuple[str, ...]
    source_quote_ids: Tuple[str, ...]
    trigger_dependency_ids: Tuple[str, ...]
    evidence_node_refs: Tuple[str, ...]


class ObligationBlueprint(BaseModel):
    """阶段一冻结产物（A.2.5）——身份此刻冻结。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blueprint_schema: Literal["obligation_blueprint_v1"]
    identity: CanonicalObligationIdentity
    canonical_identity_hash: str
    immutable: ImmutablePayload
    provenance: BlueprintProvenance


# ===========================================================================
# A.2.6 RunInstanceEnvelope + ObligationStateV2 + ObligationProvenanceV2 + ObligationV2
# ===========================================================================


class RunInstanceEnvelope(BaseModel):
    """run 实例信封（A.2.6）——进 obligation_id hash（N1 含 world/building）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    world_id: str
    building_id: str


# 独立哨兵常量（非阻断②）：区分「未求值」与「合并 ⊥」
COMPARATOR_NOT_EVALUATED = ""
COMPARATOR_BOTTOM = "⊥"

# merge 中参与 agreement-or-bottom 的 4 个标量字段（A.7①）
SCALAR_MERGE_FIELDS: Tuple[str, ...] = (
    "observed_value_json",
    "evaluated_expected_value_json",
    "evaluated_comparator",
    "comparator_result",
)


class ObligationStateV2(BaseModel):
    """阶段二求值状态（A.2.6；**非 frozen**，12 字段，A.7 逐字段 merge）。"""

    model_config = ConfigDict(extra="forbid")

    closure_status: Literal["open", "blocked", "closed"]
    satisfaction_status: Literal["satisfied", "violated", "not_applicable", "unknown"]
    applicability_state: Literal["applicable", "not_applicable", "uncertain"]
    trigger_state: Literal["active", "inactive", "open", "blocked", "not_evaluated"]
    depends_on_open_trigger: bool
    evaluated_comparator: Literal["<=", "<", ">=", ">", "==", "!=", "in", "not_in", "", "⊥"]
    comparator_result: Optional[bool]
    observed_value_json: Optional[str]
    evaluated_expected_value_json: Optional[str]
    open_reason_code: Optional[str]
    blocked_reason_code: Optional[str]
    merged_observation_bottom: Tuple[str, ...]  # B4 审计：合并落 ⊥ 的标量字段名（NFC 升序）


class ObligationProvenanceV2(BaseModel):
    """阶段二 provenance（A.2.6）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_family_id: str
    slot_ref_ids: Tuple[str, ...]
    artifact_local_ids: Tuple[str, ...]
    trigger_dependency_ids: Tuple[str, ...]
    evidence_fact_ids: Tuple[str, ...]
    evidence_node_refs: Tuple[str, ...]
    source_clause_ids: Tuple[str, ...]
    source_quote_ids: Tuple[str, ...]
    workflow_recipient_ids: Tuple[str, ...]


class ObligationV2(BaseModel):
    """组合模型（A.2.6，裁定1）。"""

    model_config = ConfigDict(extra="forbid")

    obligation_identity_schema: Literal["obligation_identity_v5"]
    obligation_id: str
    canonical_identity_hash: str
    identity: CanonicalObligationIdentity
    immutable: ImmutablePayload
    state: ObligationStateV2
    run_envelope: RunInstanceEnvelope
    provenance: ObligationProvenanceV2
    notes: str

    @model_validator(mode="after")
    def _source_operator_audit(self) -> "ObligationV2":
        """改进1：immutable.source_operator == identity.source_predicate_spec.source_operator。"""
        spec_op = (
            self.identity.source_predicate_spec.source_operator
            if self.identity.source_predicate_spec
            else ""
        )
        if self.immutable.source_operator != spec_op:
            raise ValueError(
                "immutable.source_operator 必须 == identity.source_predicate_spec.source_operator"
            )
        return self


# ===========================================================================
# A.5 canonical_json 双哈希 + 碰撞后置
# ===========================================================================


def compute_canonical_identity_hash(identity: CanonicalObligationIdentity) -> str:
    """canonical_identity_hash = sha256(canonical_json(identity))[:24]，不含 run（A.5）。"""
    return sha256_hex_24(canonical_json(identity.model_dump()))


def compute_obligation_id_v2(
    identity: CanonicalObligationIdentity, run_envelope: RunInstanceEnvelope
) -> str:
    """obligation_id = sha256(canonical_json({schema, run_envelope, identity}))[:24]（A.5，N1）。

    A.8：入口拒绝非当前 schema 对象（`IDENTITY_SCHEMA` 现为 v5，现网键切换增补 §4.1 bump）——
    identity_schema 必须为 v5；旧 v4/v3/v2/v1 对象一律拒。
    """
    if identity.identity_schema != IDENTITY_SCHEMA:
        raise ObligationContractError(
            f"obligation_id_v2_rejects_non_v5:{identity.identity_schema}"
        )
    return sha256_hex_24(
        canonical_json(
            {
                "identity_schema": IDENTITY_SCHEMA,
                "run_envelope": run_envelope.model_dump(),
                "identity": identity.model_dump(),
            }
        )
    )


def run_collision_postcheck(obligations: List[ObligationV2]) -> None:
    """碰撞后置检查全集（A.5；发布前 / load-time 双重挂点前调用）。

    ①stored_id == recompute；②obligation_id → identity 单射；
    ③canonical_identity_hash → identity 单射（同 scope）；④同 scope 重复 identity 未 dedupe。
    任一违反 → raise ObligationContractError(<code>)，产物不发布。
    """
    by_obligation_id: dict = {}
    by_hash_in_scope: dict = {}
    seen_scope_hash: dict = {}

    for o in obligations:
        scope = (o.run_envelope.world_id, o.run_envelope.building_id)

        # ① recompute 一致
        recomputed = compute_obligation_id_v2(o.identity, o.run_envelope)
        if o.obligation_id != recomputed:
            raise ObligationContractError("obligation_id_recompute_mismatch")
        # canonical_identity_hash 亦 recompute 一致（第二道防线）
        if o.canonical_identity_hash != compute_canonical_identity_hash(o.identity):
            raise ObligationContractError("obligation_id_recompute_mismatch")

        identity_bytes = canonical_json(o.identity.model_dump())

        # ② obligation_id → identity 单射
        prev = by_obligation_id.get(o.obligation_id)
        if prev is not None and prev != identity_bytes:
            raise ObligationContractError("obligation_id_not_injective")
        by_obligation_id[o.obligation_id] = identity_bytes

        # ③ canonical_identity_hash → identity 单射（同 scope 内）
        hkey = (scope, o.canonical_identity_hash)
        prev_h = by_hash_in_scope.get(hkey)
        if prev_h is not None and prev_h != identity_bytes:
            raise ObligationContractError("identity_hash_not_injective")
        by_hash_in_scope[hkey] = identity_bytes

        # ④ 同 scope 重复 identity 未被 dedupe（同 hash 出现 ≥2 条）
        seen_scope_hash[hkey] = seen_scope_hash.get(hkey, 0) + 1
        if seen_scope_hash[hkey] >= 2:
            raise ObligationContractError("dedupe_escape")


# ===========================================================================
# A.7 dedupe_key + reason code 全序表 + merge 格
# ===========================================================================


def dedupe_key(o: ObligationV2) -> str:
    """dedupe_key ≡ 身份（不含 run 实例，A.7/A.11 单一权威）。"""
    return o.canonical_identity_hash


# A.7③bis OpenReasonCode / BlockedReasonCode 全序表（非阻断③；rank 大者合并胜出）
OPEN_REASON_ORDER: dict = {
    # 2026-08-03 三方仲裁「丁」路新增，取新最大值（不动既有档位 ⇒ 既有 merge 逐字节不变）：
    # 「该精确绑定经裁定不能确立本义务」与下面那条同属「已知且确定」，不是缺口。
    # ⚠️ 档位取新最大值只证明**不扰动旧行为**，不证明「最高档」本身是对的——
    # 它会遮蔽同义务上的 `binding_requires_adjudication_authorization` /
    # `observed_false_without_violation_basis`。诊断行只产 open/unknown、
    # 同键竞争场景少，**影响面已评估为小并接受**（审核门 2026-08-03 要求留痕）。
    "diagnostic_binding_not_valid_evidence": 12,
    # 2026-08-02 A′裁决新增，取新最大值（不动既有档位 ⇒ 既有 merge 逐字节不变）：
    # 「完整聚合读数为假」是确定的已知信息（不是缺口），消费者最该先看到。
    "binding_requires_adjudication_authorization": 11,
    "observed_false_without_violation_basis": 10,
    # 2026-07-27 新增，取新最大值（不动任何既有档位，故既有 merge 结果逐字节不变）：
    # 证据许可闸命中意味着「绑错了槽」，比「缺一条事实」更值得让消费者先看到。
    "artifact_state_not_valid_evidence": 9,
    "missing_satisfaction_binding": 8,
    "applicability_uncertain": 7,
    "depends_on_open_trigger": 6,
    "missing_required_field_group": 5,
    "missing_time_anchor": 4,
    "missing_artifact_evidence": 3,
    "missing_measurement": 2,
    "missing_fact": 1,
    "null_observed_value": 0,
}

BLOCKED_REASON_ORDER: dict = {
    "ambiguous_merged_observation": 13,
    "schema_contract_violation": 12,
    "ambiguous_fact_binding": 11,
    "qualifier_conflict": 10,
    "missing_rule_edge": 9,
    "missing_obligation_edge_target": 8,
    "unsupported_obligation_edge_relation": 7,
    "unsupported_deadline_relation": 6,
    "unsupported_predicate_kind": 5,
    "unsupported_operator": 4,
    "unsupported_formula": 3,
    "unit_mismatch": 2,
    "missing_artifact_mapping": 1,
    "artifact_not_modeled_upstream": 0,
}

# ② 状态态 max-by-rank 全序（高→低取高）
_CLOSURE_RANK = {"blocked": 2, "open": 1, "closed": 0}
_CLOSURE_BY_RANK = {v: k for k, v in _CLOSURE_RANK.items()}
_APPLIC_RANK = {"uncertain": 2, "applicable": 1, "not_applicable": 0}
_APPLIC_BY_RANK = {v: k for k, v in _APPLIC_RANK.items()}
_TRIGGER_RANK = {"blocked": 4, "open": 3, "active": 2, "inactive": 1, "not_evaluated": 0}
_TRIGGER_BY_RANK = {v: k for k, v in _TRIGGER_RANK.items()}
# 已闭合满足性 max-by-rank
_CLOSED_SATIS_RANK = {"violated": 2, "satisfied": 1, "not_applicable": 0}
_CLOSED_SATIS_BY_RANK = {v: k for k, v in _CLOSED_SATIS_RANK.items()}

# ⊥ 值（A.7①）：三个 Optional 字段 ⊥=None；evaluated_comparator ⊥=独立哨兵
_SCALAR_BOTTOM = {
    "observed_value_json": None,
    "evaluated_expected_value_json": None,
    "comparator_result": None,
    "evaluated_comparator": COMPARATOR_BOTTOM,
}


def _stable_unique_sorted(values) -> Tuple[str, ...]:
    return tuple(sorted(set(values)))


def _max_by_rank(values, rank_map, by_rank_map):
    best = max(rank_map[v] for v in values)
    return by_rank_map[best]


def _lookup_open_rank(code: str) -> int:
    if code not in OPEN_REASON_ORDER:
        raise ObligationContractError(f"unknown_reason_code_in_total_order:{code}")
    return OPEN_REASON_ORDER[code]


def _lookup_blocked_rank(code: str) -> int:
    if code not in BLOCKED_REASON_ORDER:
        raise ObligationContractError(f"unknown_reason_code_in_total_order:{code}")
    return BLOCKED_REASON_ORDER[code]


def merge_states(states: List[ObligationStateV2]) -> ObligationStateV2:
    """A.7 完整 state 逐字段 merge 格——顺序无关（交换/结合/幂等）。

    注意 depends_on_open_trigger 的「trigger_dependency_ids 空 → false」后投影依赖
    provenance，不在本纯函数内做（由 `merge_obligations` 合并后 override）；本函数只取
    `a or b`，保持 state-only 纯函数性（便于属性测试）。
    """
    if not states:
        raise ValueError("merge_states 需至少一条 state")

    # ---- ① 标量 agreement-or-bottom + merged_observation_bottom 记账 ----
    mob = set()
    for s in states:
        mob |= set(s.merged_observation_bottom)

    scalar_values = {}
    for f in SCALAR_MERGE_FIELDS:
        present = set()
        for s in states:
            if f in s.merged_observation_bottom:
                mob.add(f)  # ⊥ 吸收（已带 f 者）
                continue
            present.add(getattr(s, f))
        if len(present) > 1:
            mob.add(f)  # 分歧 → ⊥
        if f in mob:
            scalar_values[f] = _SCALAR_BOTTOM[f]
        else:
            # 未落 ⊥ → 全体一致，取任一
            scalar_values[f] = next(iter(present)) if present else _SCALAR_BOTTOM[f]

    # ---- ② 状态态 max-by-rank ----
    raw_closure = _max_by_rank(
        [s.closure_status for s in states], _CLOSURE_RANK, _CLOSURE_BY_RANK
    )
    applic = _max_by_rank(
        [s.applicability_state for s in states], _APPLIC_RANK, _APPLIC_BY_RANK
    )
    trig = _max_by_rank(
        [s.trigger_state for s in states], _TRIGGER_RANK, _TRIGGER_BY_RANK
    )
    dep = any(s.depends_on_open_trigger for s in states)

    # ---- ③ 后投影（B4 ⊥→blocked 优先） ----
    if mob:
        final_closure = "blocked"
        blocked_reason: Optional[str] = "ambiguous_merged_observation"
        open_reason: Optional[str] = None
        satisfaction = "unknown"
    else:
        final_closure = raw_closure
        if final_closure == "closed":
            # closed 是最低 rank → fold=closed ⟺ 全体 closed；满足性 max-by-rank
            satis_vals = [
                s.satisfaction_status
                for s in states
                if s.satisfaction_status in _CLOSED_SATIS_RANK
            ]
            satisfaction = (
                _max_by_rank(satis_vals, _CLOSED_SATIS_RANK, _CLOSED_SATIS_BY_RANK)
                if satis_vals
                else "not_applicable"
            )
            open_reason = None
            blocked_reason = None
        elif final_closure == "open":
            satisfaction = "unknown"
            codes = [s.open_reason_code for s in states if s.open_reason_code is not None]
            open_reason = (
                max(codes, key=_lookup_open_rank) if codes else None
            )
            blocked_reason = None
        else:  # blocked
            satisfaction = "unknown"
            codes = [
                s.blocked_reason_code for s in states if s.blocked_reason_code is not None
            ]
            blocked_reason = (
                max(codes, key=_lookup_blocked_rank) if codes else None
            )
            open_reason = None

    return ObligationStateV2(
        closure_status=final_closure,
        satisfaction_status=satisfaction,
        applicability_state=applic,
        trigger_state=trig,
        depends_on_open_trigger=dep,
        evaluated_comparator=scalar_values["evaluated_comparator"],
        comparator_result=scalar_values["comparator_result"],
        observed_value_json=scalar_values["observed_value_json"],
        evaluated_expected_value_json=scalar_values["evaluated_expected_value_json"],
        open_reason_code=open_reason,
        blocked_reason_code=blocked_reason,
        merged_observation_bottom=_stable_unique_sorted(mob),
    )


def merge_immutable(payloads: List[ImmutablePayload]) -> ImmutablePayload:
    """A.7 合并前 immutable hard-fail：canonical bytes 不同 → merge_immutable_payload_conflict。"""
    if not payloads:
        raise ValueError("merge_immutable 需至少一条")
    first_bytes = canonical_json(payloads[0].model_dump())
    for p in payloads[1:]:
        if canonical_json(p.model_dump()) != first_bytes:
            raise ObligationContractError("merge_immutable_payload_conflict")
    return payloads[0]


def merge_provenance(provs: List[ObligationProvenanceV2]) -> ObligationProvenanceV2:
    """A.7④ provenance union（各列表字段 stable_unique(sorted)；source_family_id 取一致值）。"""
    if not provs:
        raise ValueError("merge_provenance 需至少一条")
    fams = {p.source_family_id for p in provs}
    if len(fams) > 1:
        raise ObligationContractError("merge_source_family_conflict")

    def _u(attr):
        acc = set()
        for p in provs:
            acc |= set(getattr(p, attr))
        return _stable_unique_sorted(acc)

    return ObligationProvenanceV2(
        source_family_id=next(iter(fams)),
        slot_ref_ids=_u("slot_ref_ids"),
        artifact_local_ids=_u("artifact_local_ids"),
        trigger_dependency_ids=_u("trigger_dependency_ids"),
        evidence_fact_ids=_u("evidence_fact_ids"),
        evidence_node_refs=_u("evidence_node_refs"),
        source_clause_ids=_u("source_clause_ids"),
        source_quote_ids=_u("source_quote_ids"),
        workflow_recipient_ids=_u("workflow_recipient_ids"),
    )


def _merge_notes(notes_list: List[str]) -> str:
    """A.7④ notes：去重 + canonical 排序拼接（顺序无关）。"""
    frags = {n for n in notes_list if n}
    return "; ".join(sorted(frags))


def merge_obligations(obligations: List[ObligationV2]) -> ObligationV2:
    """A.7 同 dedupe_key 义务合并（state 格 + immutable hard-fail + provenance union）。

    - dedupe 输入须同 run/world/building（mixed-scope → hard-fail dedupe_mixed_scope）；
    - 同 canonical_identity_hash（同身份）；
    - depends_on_open_trigger 后投影：合并 trigger_dependency_ids 空则置 false。
    """
    if not obligations:
        raise ValueError("merge_obligations 需至少一条")

    scopes = {
        (o.run_envelope.run_id, o.run_envelope.world_id, o.run_envelope.building_id)
        for o in obligations
    }
    if len(scopes) > 1:
        raise ObligationContractError("dedupe_mixed_scope")

    hashes = {o.canonical_identity_hash for o in obligations}
    if len(hashes) > 1:
        raise ObligationContractError("dedupe_identity_mismatch")

    merged_immutable = merge_immutable([o.immutable for o in obligations])
    merged_state = merge_states([o.state for o in obligations])
    merged_prov = merge_provenance([o.provenance for o in obligations])

    # depends_on_open_trigger 后投影（A.7②）：trigger_dependency_ids 空 → false
    if merged_state.depends_on_open_trigger and not merged_prov.trigger_dependency_ids:
        merged_state = merged_state.model_copy(update={"depends_on_open_trigger": False})

    first = obligations[0]
    return ObligationV2(
        obligation_identity_schema=IDENTITY_SCHEMA,
        obligation_id=first.obligation_id,
        canonical_identity_hash=first.canonical_identity_hash,
        identity=first.identity,
        immutable=merged_immutable,
        state=merged_state,
        run_envelope=first.run_envelope,
        provenance=merged_prov,
        notes=_merge_notes([o.notes for o in obligations]),
    )


__all__ = [
    "IDENTITY_SCHEMA",
    "ObligationContractError",
    "CanonicalBinding",
    "DeadlineBinding",
    "ObligationScope",
    "VariableBinding",
    "PredicateSpecV1",
    "PredicateKindV1",
    "CanonicalObligationIdentity",
    "SourceChannel",
    "encode_source_item_id",
    "ImmutablePayload",
    "BlueprintProvenance",
    "ObligationBlueprint",
    "RunInstanceEnvelope",
    "COMPARATOR_NOT_EVALUATED",
    "COMPARATOR_BOTTOM",
    "SCALAR_MERGE_FIELDS",
    "ObligationStateV2",
    "ObligationProvenanceV2",
    "ObligationV2",
    "compute_canonical_identity_hash",
    "compute_obligation_id_v2",
    "run_collision_postcheck",
    "dedupe_key",
    "OPEN_REASON_ORDER",
    "BLOCKED_REASON_ORDER",
    "merge_states",
    "merge_immutable",
    "merge_provenance",
    "merge_obligations",
]
