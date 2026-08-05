"""evo-agent baseline 跨模块共享契约（DTO / schema / enum）。

本文件是地基层唯一的契约定义点。ingest / kg / retrieval / closure / agent / eval
各模块全部 import 本文件的契约，所以字段名、类型、必填性、默认值、Literal 枚举值
必须保持精确稳定。

权威来源：《evo-agent baseline 全量实现级设计规格包》v0.4
- 闭包侧 enum / DTO         —— spec §6.2.1 ~ §6.2.5
- 数据侧 FactAtom / FactPack —— spec §5.5
- 数据侧 RuleSlice 及子 DTO  —— spec §5.6 + §3.4（子 DTO 字段从 KG 节点 schema 派生）
- 会话载体 ComplianceAssessmentRun —— spec §5.1.1

spec→code 单向：本文件不得自创规格未授权的契约字段。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


# ===========================================================================
# 一、闭包侧 enum（spec §6.2.1）
# ===========================================================================
# spec §6.2.1 用 `Xxx = Literal[...]` 形式定义；这里逐一照搬为模块级 Literal 别名，
# 供 Obligation 等 DTO 的字段类型引用。枚举值顺序与 spec 完全一致。

# 义务种类（spec §6.2.1 ObligationKind，15 个值）
ObligationKind = Literal[
    "scope",
    "trigger",
    "prerequisite",
    "definition",
    "exception",
    "evidence",
    "artifact",
    "deadline",
    "threshold",
    "method",
    "supervision",
    "report_field",
    "action",
    "prohibition",
    "escalation",
]

# 闭包状态（spec §6.2.1 ClosureStatus）
ClosureStatus = Literal["closed", "open", "blocked"]

# 满足性状态（spec §6.2.1 SatisfactionStatus），与闭包状态分离（spec D-004）
SatisfactionStatus = Literal[
    "satisfied",
    "violated",
    "unknown",
    "not_applicable",
]

# blocked 原因码（spec §6.2.1 BlockedReasonCode，15 个值）
# 注意含 `artifact_not_modeled_upstream`（spec §6.3.6：sidecar 无 artifact_key
# 限定词无法消歧时一律判 blocked + artifact_not_modeled_upstream）。
BlockedReasonCode = Literal[
    "missing_rule_edge",
    "missing_obligation_edge_target",
    "unsupported_obligation_edge_relation",
    "unsupported_predicate_kind",
    "unsupported_operator",
    "unsupported_formula",
    "unsupported_deadline_relation",
    "unit_mismatch",
    "ambiguous_fact_binding",
    "schema_contract_violation",
    "target_unresolved",
    "qualifier_conflict",
    "missing_artifact_mapping",
    "artifact_not_modeled_upstream",
    "internal_error",
]

# open 原因码（spec §6.2.1 OpenReasonCode）
OpenReasonCode = Literal[
    "missing_fact",
    "null_observed_value",
    "missing_sidecar_entry",
    "missing_measurement",
    "missing_artifact_evidence",
    "missing_time_anchor",
    "missing_required_qualifier",
    "missing_required_field_group",
    "applicability_uncertain",
    "depends_on_open_trigger",
    "missing_satisfaction_binding",
    # 2026-07-27：证据许可闸。世界侧「产物齐备布尔」（carrier_domain=artifact 的
    # sidecar 值，如 artifact.report.inspection）只能证明**该产物齐备**，不能证明
    # 一条语义不是产物的义务（检验涵盖范围 / 记录 / 报告栏目 / 动作）已经履行。
    # 命中此码 = 系统查到了那条布尔、但拒绝据它下确定判定 ⇒ 宁可 unknown。
    "artifact_state_not_valid_evidence",
    # 2026-08-03 三方决策门仲裁「丁」路新增。语义：系统已取得相关读数，但该**精确
    # 绑定**已逐项对中文法规原文裁定为「此类读数不能确立本义务」，故不据其下判定。
    # 🔴 与上一码的分工：上一码专指**产物齐备布尔**（说得出「查到了文件」）；本码用于
    # `procedure.*` / `risk.*` / `supervision.*` / `scope.*` 等**非产物读数**——
    # 对它们说「查到了文件」是**事实错误**，会违反仓库不变量「消费者文案所声称的事实
    # 须对该原因码下全部义务为真」，并污染机器排障线索。
    # ⚠️ 文案边界：**不得**写成「该义务永远不可核验」。准确边界是「当前精确绑定与
    # 该类读数永久不得作为此义务的判定依据；若改接能确立义务的证据通道，须重新裁定」。
    "diagnostic_binding_not_valid_evidence",
    # 2026-08-02 A′裁决（DEBT-083 第 5 步，绑定级值授权）：完整楼级聚合读数为
    # false——正向条件尚未成立；但无期限或终局违约判据，程序不判违反（「还没
    # 做完 ≠ 未履行」，同 2026-07-27 期限捏造教训），交专业人员复核。
    # 只可由值消费授权登记内的绑定产出（见 obligation_deriver
    # VALUE_CONSUMPTION_AUTHORIZED_BINDINGS）。
    "observed_false_without_violation_basis",
    # 2026-08-02 S3 甲′裁决：绑定要消费聚合读数/待裁片段事实产出判定，
    # 但该精确绑定未获裁定授权——不缺槽绑定也不缺事实，缺的是"消费这类读数
    # 产判定"的授权（丁组待裁保护；不 blocked、不借 schema_contract_violation）。
    "binding_requires_adjudication_authorization",
]


# ===========================================================================
# 二、闭包侧 DTO（spec §6.2.2 ~ §6.2.5）
# ===========================================================================


class Obligation(BaseModel):
    """单条义务（spec §6.2.2）。

    closure_status / satisfaction_status 分离（spec D-004）：
    前者表达资料是否闭合，后者表达是否满足。
    末尾 model_validator 实现 spec §6.2.2 的 validator 规则。
    """

    obligation_id: str
    run_id: str
    world_id: str
    building_id: str
    fragment_id: Optional[str] = None
    component_id: Optional[str] = None

    source_rule_card_id: str
    source_family_id: str
    source_clause_ids: List[str] = Field(default_factory=list)
    source_quote_ids: List[str] = Field(default_factory=list)

    kind: ObligationKind
    obligation_node_id: Optional[str] = None
    obligation_edge_ids: List[str] = Field(default_factory=list)
    actor: Optional[str] = None
    action: Optional[str] = None
    recipient_ids: List[str] = Field(default_factory=list)
    slot_ref_ids: List[str] = Field(default_factory=list)
    slot_ids: List[str] = Field(default_factory=list)
    measure_keys: List[str] = Field(default_factory=list)
    artifact_ids: List[str] = Field(default_factory=list)
    artifact_keys: List[str] = Field(default_factory=list)
    deadline_ids: List[str] = Field(default_factory=list)
    time_anchor_keys: List[str] = Field(default_factory=list)

    required: bool = True
    # verifier 自有字段，与 W2 ProjectionFamilyEval.applicability_state 互不派生
    # （spec §6.2.2 注释 + spec §2.2.3 说明 2）。
    applicability_state: Literal["applicable", "not_applicable", "uncertain"] = "applicable"

    depends_on_open_trigger: bool = False
    trigger_dependency_ids: List[str] = Field(default_factory=list)
    trigger_state: Literal[
        "active", "inactive", "open", "blocked", "not_evaluated"
    ] = "not_evaluated"

    closure_status: ClosureStatus
    satisfaction_status: SatisfactionStatus

    operator: Optional[str] = None
    expected_value_json: Optional[str] = None
    threshold_value_json: Optional[str] = None
    observed_value_json: Optional[str] = None
    unit: Optional[str] = None
    comparator_result: Optional[bool] = None

    evidence_fact_ids: List[str] = Field(default_factory=list)
    evidence_node_refs: List[str] = Field(default_factory=list)

    open_reason_code: Optional[OpenReasonCode] = None
    blocked_reason_code: Optional[BlockedReasonCode] = None
    notes: str = ""

    @model_validator(mode="after")
    def _check_closure_satisfaction_consistency(self) -> "Obligation":
        """spec §6.2.2 validator 规则——闭包状态 / 满足性 / 原因码一致性约束。"""
        if self.closure_status == "closed":
            assert self.blocked_reason_code is None, (
                "closed obligation 不得有 blocked_reason_code"
            )
            assert self.open_reason_code is None, (
                "closed obligation 不得有 open_reason_code"
            )
            assert self.satisfaction_status in {
                "satisfied",
                "violated",
                "not_applicable",
            }, "closed obligation 的 satisfaction_status 必须是 satisfied/violated/not_applicable"

        if self.closure_status == "open":
            assert self.open_reason_code is not None, (
                "open obligation 必须有 open_reason_code"
            )
            assert self.blocked_reason_code is None, (
                "open obligation 不得有 blocked_reason_code"
            )
            assert self.satisfaction_status == "unknown", (
                "open obligation 的 satisfaction_status 必须是 unknown"
            )

        if self.closure_status == "blocked":
            assert self.blocked_reason_code is not None, (
                "blocked obligation 必须有 blocked_reason_code"
            )
            assert self.satisfaction_status == "unknown", (
                "blocked obligation 的 satisfaction_status 必须是 unknown"
            )

        if self.depends_on_open_trigger:
            assert self.trigger_dependency_ids, (
                "depends_on_open_trigger=true 时 trigger_dependency_ids 不得为空"
            )
            assert (
                self.closure_status in {"open", "blocked"}
                or self.open_reason_code == "depends_on_open_trigger"
            ), (
                "depends_on_open_trigger=true 时 closure_status 必须 open/blocked，"
                "或 open_reason_code 为 depends_on_open_trigger"
            )
        return self


# identity-v5 现网键切换增补 §4.2 冻结版本常量——ObligationSet 容器/身份版本的**固定值集**
# （"固定值 v5 组合"契约锚点）。镜像 closure.identity_v2.IDENTITY_SCHEMA（`obligation_identity_v5`）/
# canonical_profile.CANONICAL_PROFILE_ID（`mbis_canonical_v2`）与 validator 构造点字面量。地基层
# 契约不反向 import closure/canonical_profile（避免环 import），以字面量固化；跨身份模式版本 bump
# 必须同步更新此处——否则新构造被下方校验拒收 = 显式 tripwire，防容器/身份版本静默漂移。
_FROZEN_OBLIGATION_SET_SCHEMA = "obligation_set_v2"
_FROZEN_OBLIGATION_IDENTITY_SCHEMA = "obligation_identity_v5"
_FROZEN_CANONICAL_PROFILE_ID = "mbis_canonical_v2"
_FROZEN_IDENTITY_KEY_POLICY = "canonical_identity_hash"


class ObligationSet(BaseModel):
    """一次运行推导出的全部义务集合（spec §6.2.3）。

    identity-v5 现网键切换增补 §4.2：容器与身份**分别版本化**。下列版本/身份字段
    为**可选**（默认 None/空）——旧缺字段产物（EXP-008 / mock 运行目录）**按 v1 只读**、
    加载时不谎标 v5（§4.3）；v5 现网路径由 `validate_building_closure` 显式抄录填入实际值。
    `obligations` 列表**仍是 v1 扁平 `Obligation`**（求值器与扁平结构不变），身份材料旁挂
    `identity_manifest`（每条最终义务一条：obligation_id / canonical_identity_hash /
    CanonicalObligationIdentity / ImmutablePayload，支持落盘后重算、碰撞审计、回放）。

    版本一致性闸（`_validate_identity_versioning`，§4.2）：四版本字段 **all-or-none**——
    全缺=v1 只读容器（identity_manifest 必空）/ 全齐且**等于固定 v5 值**=v5 组合（identity_manifest
    与 obligations 一一对应）；任何混合（部分缺 / 值不符 / v1 却挂 manifest）→ ValidationError
    （fail-closed，防伪造 `obligation_set_v2` + 身份 None 混合容器）。
    """

    obligation_set_id: str
    run_id: str
    world_id: str
    building_id: str
    created_at: str
    rulecard_bundle_id: str
    verifier_version: str
    obligations: List[Obligation]
    derivation_policy: Dict[str, Any]
    # identity-v5 版本/身份字段（§4.2；Optional=旧产物只读不谎标）。
    obligation_set_schema: Optional[str] = None
    obligation_identity_schema: Optional[str] = None
    canonical_profile_id: Optional[str] = None
    identity_key_policy: Optional[str] = None
    identity_manifest: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_identity_versioning(self) -> "ObligationSet":
        """identity-v5 增补 §4.2：容器/身份版本 all-or-none + identity_manifest ↔ obligations 一一对应。

        - 四版本字段（obligation_set_schema / obligation_identity_schema / canonical_profile_id /
          identity_key_policy）**全缺** = v1 只读容器（旧 obligation_set.json / EXP-008 / mock 目录），
          identity_manifest 必空；
        - **全齐且等于固定 v5 值集** = v5 组合，identity_manifest 逐条与 obligations 一一对应（长度相等
          + obligation_id 集相等）；
        - 任何**混合**（部分缺 / 值不符 / v1 却挂 identity_manifest）→ ValidationError（fail-closed）。
        """
        version_fields = {
            "obligation_set_schema": self.obligation_set_schema,
            "obligation_identity_schema": self.obligation_identity_schema,
            "canonical_profile_id": self.canonical_profile_id,
            "identity_key_policy": self.identity_key_policy,
        }
        present = [k for k, v in version_fields.items() if v is not None]

        # v1 只读容器：四版本字段全缺（旧产物不谎标 v5，也不得挂 v5 身份材料）。
        if not present:
            if self.identity_manifest:
                raise ValueError(
                    "identity versioning mixed: v1 read-only ObligationSet "
                    "(no version fields) must not carry identity_manifest"
                )
            return self

        # all-or-none：有其一必四者全齐（拦"obligation_set_v2 + 身份 None"混合容器）。
        if len(present) != len(version_fields):
            missing = sorted(set(version_fields) - set(present))
            raise ValueError(
                "identity versioning must be all-or-none; "
                f"present={sorted(present)} missing={missing}"
            )

        # 全齐 → 必须等于固定 v5 值集（拦错 profile / 伪版本）。
        expected = {
            "obligation_set_schema": _FROZEN_OBLIGATION_SET_SCHEMA,
            "obligation_identity_schema": _FROZEN_OBLIGATION_IDENTITY_SCHEMA,
            "canonical_profile_id": _FROZEN_CANONICAL_PROFILE_ID,
            "identity_key_policy": _FROZEN_IDENTITY_KEY_POLICY,
        }
        for key, exp in expected.items():
            if version_fields[key] != exp:
                raise ValueError(
                    f"identity versioning value mismatch: {key}="
                    f"{version_fields[key]!r} != frozen v5 {exp!r}"
                )

        # identity_manifest 与 obligations 一一对应——**多重集**相等（Counter），非
        # "长度+set"（后者可被 obligations=[a,a,b] vs manifest=[a,b,b] 穿透——codex
        # 019f7328 阻断 1）。且 obligation_id 必须唯一（去重后的最终容器不允许重复 ID）。
        from collections import Counter

        manifest_counter = Counter(
            m.get("obligation_id") for m in self.identity_manifest
        )
        obligation_counter = Counter(o.obligation_id for o in self.obligations)
        dup_ids = sorted(k for k, v in obligation_counter.items() if v > 1)
        if dup_ids:
            raise ValueError(
                f"duplicate obligation_id in obligations: {dup_ids[:5]!r}"
            )
        if manifest_counter != obligation_counter:
            raise ValueError(
                "identity_manifest obligation_id multiset does not match "
                "obligations (Counter mismatch)"
            )
        return self


class ClosureSummary(BaseModel):
    """闭包验证统计摘要（spec §6.2.4）。

    allow_stop 计算见 spec §6.5.1（open_count==0 且 blocked_count==0 且
    schema / forbidden source 校验通过）；violated_count>0 不影响 allow_stop。
    """

    total_obligations: int
    closed_count: int
    open_count: int
    blocked_count: int

    satisfied_count: int
    violated_count: int
    unknown_count: int
    not_applicable_count: int

    open_reason_counts: Dict[str, int]
    blocked_reason_counts: Dict[str, int]
    rule_card_count: int
    family_count: int
    fragment_count: int

    allow_stop: bool
    stop_reason: str


# ---------------------------------------------------------------------------
# unknown 归因（旁路映射，DEBT «无故 unknown 归零» 第一步）
# ---------------------------------------------------------------------------
# 用户拍板的验收标准：「不是判定系统……但是也不能无故 unknown，这是两码事」。
# 现在「要专业人员填」与「系统坏了」共用一个 `unknown` 标签，专业人员分不出。
#
# 🔴 落点是**旁路映射**，不是 Obligation 上的第三个字段——Obligation 的状态与原因码
# 受同一 model_validator 约束（本文件 §6.2.2），加同级字段会扩大权威对象表面，且会
# 穿过 closure/validator.py 的去重合并被重建。归因**只读、不参与判定**。

# 消费者只两类。「系统尚未实现」是 `system_unresolved` 下的一个 cause_code，不是第三类。
UnknownResponsibility = Literal["professional_input_required", "system_unresolved"]

# Orthogonal diagnostic axis; deliberately not part of UnknownCauseCode.
ScopeRelationKind = Literal[
    "same",
    "category_compatible",
    "authorized_disjoint",
    "different_unresolved",
    "card_unconstrained",
    "identity_unavailable",
]


class UnknownScopeRelation(BaseModel):
    """Structured component-scope relation for one unknown obligation."""

    card_component_type_keys: Tuple[str, ...]
    fragment_component_type: Optional[str]
    relation: ScopeRelationKind
    target_authorization_status: str
    relation_policy_version: str

# 本阶段只用**结构上可靠**的信号，不照搬旁路脚本的常量表。
UnknownCauseCode = Literal[
    # 上游 trigger 未闭合传下来的继承型 unknown（根因在别处，本条自身无病）
    "inherited_from_root",
    # 卡级触发器聚合为 blocked ⇒ 下游义务从未进入满足通道。
    # 判据：快照 `trigger_state == "blocked"`（验证器/派生器权威字段，不读 notes）。
    # 与 `missing_rule_edge` 分流：后者留给真·规则边/悬空引用等接线缺口。
    "upstream_trigger_blocked",
    # 槽名经别名归一后在本次 FactPack 槽池里**存在**，但不在本义务作用域内 ⇒ 限定符对不上
    "qualifier_mismatch",
    # 槽名经别名归一后在本次 FactPack 槽池里**不存在** ⇒ 世界侧未供给
    "slot_not_supplied",
    # 义务图节点行 + 未绑定任何事实槽句柄 + **验证器两个原因码皆空** ⇒
    # 结构兜底（最后手段）。有验证器码时优先透传/分流，不落本码。
    # **不是**「需要你提供」——responsibility 仍是 `system_unresolved`。
    "no_slot_declared",
    # 非义务图节点行 + 未绑定事实槽 + 验证器两码皆空：非事实槽句柄轴说明。
    # 判据纯结构：`obligation_node_id` 空 且 `has_slot_handle` 假 且无验证器码。
    "non_slot_handle",
    # 归因输入不足（缺责任清单 / 缺能力快照 / 归因策略异常 / 判据全部落空且原因码
    # 不在透传名单内）。
    # 🔴 这是**报警**值：绝不默认成「需要你提供」——对专业人员谎称"这该你填"而实际是
    # 系统坏了，比不归因更有害。
    "attribution_input_missing",
    # ---- 验证器原因码透传（只读快照 `validator_reason_code`，不重推）----
    # 证据许可闸：查到「产物齐备布尔」但拒绝据它下确定判定（有意的保守设计）。
    "artifact_state_not_valid_evidence",
    # 诊断型绑定闸：读数已取得，但该精确绑定经裁定不能确立本义务（非产物读数）。
    "diagnostic_binding_not_valid_evidence",
    # 真·规则边/悬空引用等接线缺口（**不含**卡级触发器聚合 blocked——那走
    # `upstream_trigger_blocked`）。
    "missing_rule_edge",
    # 候选事实多于一条，系统拒绝任取其一下结论。
    "ambiguous_fact_binding",
    # 义务要求以某文件为证据，事实包中没有该文件的记录。
    "missing_artifact_evidence",
    # 缺期限锚点，无法核验期限是否满足。
    "missing_time_anchor",
    # 义务图节点缺满足通道绑定（派生器拒绝动作名当槽名兜底后的诚实码）。
    "missing_satisfaction_binding",
    # 产物键未在上游世界模型建模，无法消歧。
    "artifact_not_modeled_upstream",
    # 缺量测值，无法核验阈值/比较。
    "missing_measurement",
    # 查不到所需事实。
    "missing_fact",
    # 缺必填字段组。
    "missing_required_field_group",
    # 单位不一致，拒绝比较。
    "unit_mismatch",
    # 完整楼级聚合读数为 false——正向条件尚未成立，且无期限/终局违约判据，
    # 程序不判违反（A′裁决，2026-08-02）。
    "observed_false_without_violation_basis",
    # 绑定未获裁定授权，程序拒绝据聚合/待裁读数下判定（S3，2026-08-02）。
    "binding_requires_adjudication_authorization",
]


class UnknownAttribution(BaseModel):
    """单条 `satisfaction_status == "unknown"` 义务的归因（旁路，只读）。

    责任二分取自权威登记表 `responsibility_registry_v1.json`；表缺席或槽未登记时
    **一律** `system_unresolved`（绝不默认成「需要你提供」）。
    """

    obligation_id: str
    responsibility: UnknownResponsibility
    cause_code: UnknownCauseCode
    explanation: str
    root_dependency_ids: List[str] = Field(default_factory=list)
    policy_version: str
    # 验证器原始原因码的基本值拷贝（恒等于该义务的
    # `open_reason_code or blocked_reason_code`），**对每一条归因都写**（不只是透传的那些）。
    # 🔴 纪律：机器对账 / 债清单 / 跨批对比一律用本字段，**禁止只引 `cause_code`**
    # ——`cause_code` 是消费者分节键，不是原始码全集（槽轴四类会重映射；透传名单与
    # `upstream_trigger_blocked` 分流见归因策略）。分组表只允许存在于渲染层
    # （report_writer 的标签/排序表），不得进 contracts.py / 本模型 /
    # machine_readable_report。
    validator_reason_code: Optional[str] = None
    # 驱动本条责任判定的槽（登记表命中时填写）；报告层按「槽 × 行动说明」聚合用。
    responsible_slot_id: Optional[str] = None
    # 专业人员可执行交件说明（仅 `professional_input_required` 时非空；来自登记表）。
    professional_action: Optional[str] = None
    # None is retained only for legacy artifacts and direct test payloads.
    # Current verifier runs attach this side-channel field after cause attribution.
    scope_relation: Optional[UnknownScopeRelation] = None


class ClosureValidationResult(BaseModel):
    """闭包验证器的最终输出（spec §6.2.5）。

    spec §6.5.3：allow_report_generation = allow_stop。
    """

    run_id: str
    obligation_set: ObligationSet
    closure_summary: ClosureSummary
    allow_stop: bool
    allow_report_generation: bool
    high_risk_items: List[dict]
    machine_readable_report: Dict[str, Any]
    # unknown 归因旁路映射：obligation_id -> UnknownAttribution。
    # `None` = **本次未计算**（旧产物 / 直接构造的测试与假桩按 v1 只读，不谎标已归因）；
    # 非 None 时由下方 model_validator 守恒门校验键集完整性。
    unknown_attribution_by_obligation_id: Optional[Dict[str, UnknownAttribution]] = None

    @model_validator(mode="after")
    def _validate_unknown_attribution_conservation(self) -> "ClosureValidationResult":
        """守恒门：映射键集合 == 全部 `satisfaction_status == "unknown"` 的义务 id 集合。

        🔴 本校验器**只验映射完整性、绝不回写义务**（判定权红线：判定由确定性闭包
        验证器产出，归因是旁路观察者）。字段为 None 时跳过（v1 只读容器）。
        """
        if self.unknown_attribution_by_obligation_id is None:
            return self
        expected = {
            o.obligation_id
            for o in self.obligation_set.obligations
            if o.satisfaction_status == "unknown"
        }
        actual = set(self.unknown_attribution_by_obligation_id)
        if expected != actual:
            missing = sorted(expected - actual)[:5]
            extra = sorted(actual - expected)[:5]
            raise ValueError(
                "unknown_attribution 守恒门失败："
                f"缺 {len(expected - actual)} 条 {missing!r}，"
                f"多 {len(actual - expected)} 条 {extra!r}"
            )
        # 每条映射的 obligation_id 必须与它的键一致（防错位挂载）。
        for key, attr in self.unknown_attribution_by_obligation_id.items():
            if attr.obligation_id != key:
                raise ValueError(
                    f"unknown_attribution 键错位：key={key!r} != "
                    f"payload.obligation_id={attr.obligation_id!r}"
                )
        return self


# ===========================================================================
# 三、数据侧 DTO —— FactAtom / FactPack（spec §5.5）
# ===========================================================================


class FactAtom(BaseModel):
    """单条事实原子（spec §5.5）。

    value_json 是值的 canonical JSON 字符串；value_type 标注原始值类型。
    禁止携带任何 W2 参考真值字段（spec §2.2.3）。
    """

    fact_id: str
    world_id: str
    building_id: str
    carrier_type: Literal[
        "building",
        "component",
        "location",
        "fragment",
        "driver",
        "mechanism",
        "condition",
        "drainage",
        "ubw",
        "fire_safety",
        "repair_assessment",
        "measurement",
        "sidecar_entry",
    ]
    carrier_id: str
    target_ref: Optional[str]
    slot_id: Optional[str]
    measure_key: Optional[str]
    value_json: str
    value_type: Literal["number", "boolean", "string", "enum", "object", "null"]
    unit: Optional[str]
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    confidence_index: Optional[float] = None
    source_path: str
    source_node_id: str
    provenance: Dict[str, Any] = Field(default_factory=dict)


class FactPack(BaseModel):
    """一次运行的事实包（spec §5.5）——agent 底线层闭包验证器的输入。

    slot_index / measure_index / carrier_index 为倒排索引，value 为 fact_id 列表。

    ⚠️ 勿与 ``workflow_engine.evidence_schema.FactPack``（W1 数据生成侧、case_id +
    FactItem、无倒排索引）混淆——两者同名但属不同层、不同结构；本类是 agent runtime
    用的那个。两包互不 import，同一文件内不会撞，但跨层读代码时易看错。
    """

    run_id: str
    world_id: str
    building_id: str
    facts: List[FactAtom]
    slot_index: Dict[str, List[str]]       # slot_id -> fact_id list
    measure_index: Dict[str, List[str]]    # measure_key -> fact_id list
    carrier_index: Dict[str, List[str]]    # carrier_id -> fact_id list
    source_tables: List[str]


# ===========================================================================
# 四、数据侧 DTO —— RuleSlice 及子 DTO（spec §5.6 + §3.4）
# ===========================================================================
# spec §5.6 只对 RuleCardDTO 给出完整 pydantic 定义；RuleFamilyDTO /
# SemanticSlotDTO / MeasureDTO / ArtifactDTO / TimeAnchorDTO / SourceQuoteDTO
# 在 RuleSlice 字段中被引用但未给独立 class。这些子 DTO 的字段按 spec §3.4 对应
# KG 节点 schema 派生（见各 class docstring 标注的来源行）。详见交付报告决策点 D-1。


class SourceQuoteDTO(BaseModel):
    """rule card 法规原文引用 DTO。

    字段来源：spec §3.4.3 `(:SourceQuote)` 节点 schema。
    spec §5.6 要求 4：主键统一为 `source_quote_id`，同时保留 `quote_local_id`。
    """

    source_quote_id: str        # = rule_card_id + "::" + quote_local_id
    quote_local_id: str
    rule_card_id: str
    text: Optional[str] = None
    page: Optional[Any] = None
    language: Optional[str] = None


class SemanticSlotDTO(BaseModel):
    """语义槽注册表条目 DTO。

    字段来源：spec §3.4.4 `(:SemanticSlot)` 节点 schema
    （slot_id, semantic_domain, allowed_roles, semantic_meaning）。
    """

    slot_id: str
    semantic_domain: Optional[str] = None
    allowed_roles: List[str] = Field(default_factory=list)
    semantic_meaning: Optional[str] = None


class MeasureDTO(BaseModel):
    """量度注册表条目 DTO。

    字段来源：spec §3.4.4 `(:Measure)` 节点 schema
    （measure_key, quantity_family, unit, allowed_operators, semantic_meaning）。
    """

    measure_key: str
    quantity_family: Optional[str] = None
    unit: Optional[str] = None
    allowed_operators: List[str] = Field(default_factory=list)
    semantic_meaning: Optional[str] = None


class ArtifactDTO(BaseModel):
    """工件（artifact）注册表条目 DTO。

    字段来源：spec §3.4.4 `(:Artifact)` 节点 schema
    （artifact_key, artifact_family, semantic_meaning）。
    """

    artifact_key: str
    artifact_family: Optional[str] = None
    semantic_meaning: Optional[str] = None


class TimeAnchorDTO(BaseModel):
    """时间锚点注册表条目 DTO。

    字段来源：spec §3.4.4 `(:TimeAnchor)` 节点 schema
    （time_anchor_key, semantic_meaning）。
    """

    time_anchor_key: str
    semantic_meaning: Optional[str] = None


class RuleFamilyDTO(BaseModel):
    """rule family DTO。

    字段来源：spec §3.4.2 `(:RuleFamily)` 节点 schema
    （family_id, family_name, phase, actor, subject, action_cluster,
    deprecated_family_ids, card_count）。
    """

    family_id: str
    family_name: Optional[str] = None
    phase: Optional[str] = None
    actor: Optional[str] = None
    subject: Optional[str] = None
    action_cluster: Optional[str] = None
    deprecated_family_ids: List[str] = Field(default_factory=list)
    card_count: Optional[int] = None


class RuleCardDTO(BaseModel):
    """rule_card v2 卡片 DTO（spec §5.6 DTO 结构要求 2）。

    spec §5.6 要求 1：必须保留 rule_card v2 原嵌套形态，不是扁平节点列表。
    嵌套子结构（trigger_conditions / workflow_operands / slot_role_map /
    threshold_regimes / obligation_graph / evidence_requirements 等）以 dict /
    list[dict] 透传原嵌套 JSON（spec §5.4.3：DTO builder 把扁平子图还原为
    rule_cards.json 原嵌套结构）。

    spec §5.6 要求 3：threshold_regimes[] 内的 formula 必须从
    RuleThreshold.formula_json 还原，不能丢失。
    spec §5.6 要求 5：DTO 不得含 §2.2.3 禁止属性名（W2 projection_* /
    expected_verdict / coverage_status 等）。
    """

    rule_card_id: str
    source_document_id: str
    source_section: List[dict] = Field(default_factory=list)
    source_quote: List[dict] = Field(default_factory=list)
    normalized_rule_text: str
    family_id: str
    applicability: dict = Field(default_factory=dict)
    trigger_conditions: dict = Field(default_factory=dict)   # {logic, items[]}
    workflow_operands: dict = Field(default_factory=dict)    # primary_actor/action, artifacts[], deadlines[], recipients[], method_keys_allowed[]
    slot_role_map: List[dict] = Field(default_factory=list)
    threshold_regimes: List[dict] = Field(default_factory=list)  # includes formula when present
    exceptions: List[dict] = Field(default_factory=list)
    definitions: List[dict] = Field(default_factory=list)
    obligation_graph: dict = Field(default_factory=dict)     # {nodes[], edges[]}
    neighbor_families: List[str] = Field(default_factory=list)
    evidence_requirements: dict = Field(default_factory=dict)  # for_matching / for_submission / for_completion
    version: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)


class RuleSlice(BaseModel):
    """一次运行的规则切片（spec §5.6）。

    由 Rule KG-RAG 检索 + DTO builder 装配；闭包验证器以
    RuleSlice + FactPack 为唯一输入。
    """

    run_id: str
    rulecard_bundle_id: str
    candidate_rule_cards: List[RuleCardDTO]
    rule_families: List[RuleFamilyDTO]
    semantic_slots: List[SemanticSlotDTO]
    measures: List[MeasureDTO]
    artifacts: List[ArtifactDTO]
    time_anchors: List[TimeAnchorDTO]
    source_quotes: List[SourceQuoteDTO]
    retrieval_policy: Dict[str, Any]


# ===========================================================================
# 五、会话载体 —— ComplianceAssessmentRun（spec §5.1.1）
# ===========================================================================


class ComplianceAssessmentRun(BaseModel):
    """一次评估会话的载体（spec §5.1.1）。

    旧 QueryEpisode 已废止（spec §0.6）；baseline 唯一会话载体。
    """

    run_id: str                       # CAR-<timestamp>-<hash>
    run_type: Literal["baseline_building_review"]
    world_id: str
    building_id: str
    requested_at: str
    completed_at: Optional[str] = None
    status: Literal[
        "created",
        "retrieving_facts",
        "retrieving_rules",
        "verifying_closure",
        "report_ready",
        "blocked",
        "failed",
    ]
    kg_snapshot_id: str
    agent_version: str
    verifier_version: str
    rulecard_bundle_id: str
    input_guard_result: Dict[str, Any]
    retrieval_summary: Dict[str, Any] = Field(default_factory=dict)
    closure_result_ref: Optional[str] = None
    report_ref: Optional[str] = None
    allow_stop: Optional[bool] = None
    notes: List[str] = Field(default_factory=list)
    # identity-v5 现网键切换增补 §7（原子版本传播）：会话载体携身份 schema，供 replay/eval
    # 按 obligation_identity_schema 分区。Optional=旧产物 / 未过闭包的 blocked/failed run 为
    # None（按 v1 只读）；新 run 过闭包后由编排器抄录 ObligationSet.obligation_identity_schema。
    obligation_identity_schema: Optional[str] = None


# ===========================================================================
# 六、evo-agent v1 DTO（spec v1 Appendix B；本节由 spec→code 单向落地）
# ===========================================================================
#
# 落自 `团队文档/我的笔记/蓝图汇总/evo-agent_v1_设计规格.md` Appendix B。
# spec v1 §12.2 明确：DTO 字段以 Appendix B 为准；不得添加未授权字段。
# Pydantic v2 `model_config = {"extra": "forbid"}` 强制契约。
#
# 8 个核心 DTO + 4 个辅助：
# - EvoRunTrace（B.2）+ EvoRunStep
# - EvoSkillPackage（B.3）+ SkillJson + SkillScope
# - EvoPolicyVersion（B.4）
# - SanitizedFeedbackPacket（B.5）+ FeedbackCell
# - SkillValidationRecord（B.6）
# - EvoMemoryStoreConfig（B.7）
# - EvoReleaseCard（B.8）


# --- B.2 EvoRunTrace ---------------------------------------------------------
class EvoRunStep(BaseModel):
    """EvoRunTrace 内的一步（spec v1 Appendix B.2）。"""

    model_config = {"extra": "forbid"}

    step_id: str
    trace_id: str
    seq: int
    stage: Literal[
        "input_guard",
        "fact_retrieval",
        "rule_retrieval",
        "skill_activation",
        "closure_verification",
        "deep_lookup",
        "report_generation",
        "guard",
    ]
    tool_name: Optional[str] = None
    tool_input_hash: Optional[str] = None
    tool_output_summary_hash: Optional[str] = None
    selected_skill_ids: List[str] = Field(default_factory=list)
    policy_decision_ref: Optional[str] = None
    candidate_set_hash: Optional[str] = None
    guard_results: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class EvoRunTrace(BaseModel):
    """一次 ComplianceAssessmentRun 的可审计经验记录（spec v1 §3.6 + B.2）。

    `trace_visibility="agent_visible_trace"`：可进 EvoMemoryStore + Replay Buffer。
    `forbidden_scan_passed=False` 时不得进入 Replay Buffer（spec v1 §9.2）。
    """

    model_config = {"extra": "forbid"}

    trace_id: str
    run_id: str
    world_id_hash: str
    building_id_hash: str
    kg_snapshot_id: str
    rulecard_bundle_id: str
    agent_version: str
    verifier_version: str
    evo_policy_version_id: str
    active_skill_set_id: str
    active_skill_version_ids: List[str] = Field(default_factory=list)
    input_guard_hash: str
    retrieval_summary: Dict[str, Any] = Field(default_factory=dict)
    candidate_universe_hash: str
    fact_pack_hash: str
    rule_slice_hash: str
    closure_result_ref: str
    closure_summary: Dict[str, Any] = Field(default_factory=dict)
    report_ref: Optional[str] = None
    hook_results_hash: str
    tool_call_count: int
    llm_iterations_used: int
    cost: Dict[str, Any] = Field(default_factory=dict)
    fallback_reason: Optional[str] = None
    steps: List[EvoRunStep] = Field(default_factory=list)
    sanitized_feedback_refs: List[str] = Field(default_factory=list)
    trace_visibility: Literal["agent_visible_trace"] = "agent_visible_trace"
    forbidden_scan_passed: bool
    source_visibility_audit_passed: bool
    schema_audit_passed: bool
    candidate_floor_passed: bool
    # identity-v5 现网键切换增补 §7（原子版本传播）：经验记录携身份 schema，统计序列 /
    # replay 必须按此字段分区（禁跨身份模式混算）。Optional=旧 trace / 未过闭包为 None（v1 只读）；
    # 新 run 由 TraceCapture 抄录 ObligationSet.obligation_identity_schema。
    obligation_identity_schema: Optional[str] = None
    created_at: str


# --- B.3 EvoSkillPackage -----------------------------------------------------
class SkillScope(BaseModel):
    """Skill 适用范围（spec v1 §10.2 + B.3）。"""

    model_config = {"extra": "forbid"}

    rule_families: List[str] = Field(default_factory=list)
    rule_cards: List[str] = Field(default_factory=list)
    semantic_slots: List[str] = Field(default_factory=list)
    measure_keys: List[str] = Field(default_factory=list)
    artifact_keys: List[str] = Field(default_factory=list)
    obligation_kinds: List[str] = Field(default_factory=list)


class SkillJson(BaseModel):
    """EvoSkillPackage 的机器权威源（spec v1 §10.2 + B.3）。

    `forbidden_actions` 必须含 5 个 hard 项（spec v1 §10.2 + §9.4.1 Gate 0）：
    override_verifier / force_allow_stop / emit_final_verdict /
    read_evaluator_truth / suppress_rule_candidate。

    **v1.1 修订（spec §0.6 修订 2 + §10.6）**：``status`` 简化为 3 态
    ``draft`` / ``active`` / ``retired``（去掉 ``candidate`` / ``staged`` /
    ``quarantined``）；状态映射按 §0.6.1 全局规则解读。
    """

    model_config = {"extra": "forbid"}

    schema_version: Literal["1.0.0"]
    skill_id: str
    skill_version_id: str
    name: str
    kind: Literal[
        "micro_routing", "retrieval_macro", "report_structure", "diagnostic_hint"
    ]
    layer: Literal["L1_operational"]
    description: str  # ≤1024 chars（spec v1 §10.2 / Gate 1）
    # v1.1 §0.6 修订 2 + §10.6：3 态简化（去掉 candidate/staged/quarantined）
    status: Literal["draft", "active", "retired"]
    origin: Literal["evo_induced", "manual_seed", "spec_revision"]
    version: str
    parent_skill_version_id: Optional[str] = None
    supersedes: List[str] = Field(default_factory=list)
    scope: SkillScope
    trigger_predicate: Dict[str, Any] = Field(default_factory=dict)
    action_plan_ref: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    forbidden_actions: List[str] = Field(default_factory=list)
    guardrails: Dict[str, Any] = Field(default_factory=dict)
    source_trace_hashes: List[str] = Field(default_factory=list)
    support_counts: Dict[str, int] = Field(default_factory=dict)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    activation_stats: Dict[str, Any] = Field(default_factory=dict)
    kg_snapshot_id: str
    rulecard_bundle_id: str
    expires_on_revision: Dict[str, bool] = Field(default_factory=dict)
    created_by: str
    created_at: str
    non_authority_statement: str


class EvoSkillPackage(BaseModel):
    """EvoSkillPackage 目录级容器（spec v1 §10.1 + B.3）。

    目录结构：`<package_uri>/{skill.json, SKILL.md, validation_records.jsonl,
    plan.yaml(可选)}`。`skill.json` 是机器权威源；`SKILL.md` 是 LLM-readable view。
    """

    model_config = {"extra": "forbid"}

    package_schema_version: Literal["1.0.0"]
    package_uri: str
    package_sha256: str
    skill: SkillJson
    skill_md_sha256: str
    plan_yaml_sha256: Optional[str] = None  # required for micro_routing/retrieval_macro
    validation_records_sha256: str
    manifest_sha256: str


# --- B.4 EvoPolicyVersion ----------------------------------------------------
class EvoPolicyVersion(BaseModel):
    """可加载到 runtime 的版本化策略（spec v1 §3.6.4 + B.4）。

    不得含 `allow_stop_policy` 字段（spec v1 §6 / §12.2：allow_stop 唯一权威 = closure verifier）。
    `max_tool_iterations_default=16`（spec v1 §12.2 production default）。
    `experiment_budgets=[8, 16, 32]`（spec v1 §11.4 paired experiment）。

    **v1.1 修订（spec §0.6 修订 1 + 修订 2 + §3.6.4）**：
    - ``status`` 简化为 3 态 ``draft`` / ``active`` / ``retired``；
    - 删除 ``previous_active_version_id``（由 git history 代替，spec §3.6.4 末段）；
    - 删除 ``rollback_condition``（实验室阶段无 canary，§9.8 / §9.9 整段删）；
    - 新增 ``trained_on_artifacts``（spec §3.6.4，trainer 输入 artifact ref 含 raw
      ``EvalTruthReport`` ref / replay set / trace set 等，替代旧 ``trained_on_feedback_packet_ids``）；
    - ``trained_on_feedback_packet_ids`` 保留但不再硬约束（spec §3.6.4 注：仅
      runtime trend feedback 接口启用时填）。
    """

    model_config = {"extra": "forbid"}

    policy_version_id: str
    policy_id: str
    version: str
    # v1.1 §0.6 修订 2 + §3.6.4：3 态简化
    status: Literal["draft", "active", "retired"]
    ranking_weights: Dict[str, float] = Field(default_factory=dict)
    tool_preferences: Dict[str, Any] = Field(default_factory=dict)
    skill_activation_order: Dict[str, Any] = Field(default_factory=dict)
    open_obligation_priority: Dict[str, Any] = Field(default_factory=dict)
    candidate_cutoff_policy: Dict[str, Any] = Field(default_factory=dict)
    report_template_policy: Dict[str, Any] = Field(default_factory=dict)
    fallback_thresholds: Dict[str, Any] = Field(default_factory=dict)
    max_tool_iterations_default: int = 16
    experiment_budgets: List[int] = Field(default_factory=lambda: [8, 16, 32])
    trained_on_replay_set_id: str
    # v1.1 §3.6.4 新增：trainer 输入 artifact ref（含 raw EvalTruthReport ref / replay set / trace set 等）
    trained_on_artifacts: List[str] = Field(default_factory=list)
    # v1.1 §3.6.4 保留但不再硬约束（仅 runtime trend feedback 接口启用时填）
    trained_on_feedback_packet_ids: List[str] = Field(default_factory=list)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    activated_at: Optional[str] = None


# --- B.5 SanitizedFeedbackPacket ---------------------------------------------
class FeedbackCell(BaseModel):
    """单个反馈 cell（spec v1 §8.4 + B.5）。

    `suppressed=True` 时 cell 不暴露（spec v1 §8.4 k-anonymity 不满足）。
    `suggested_evo_action` 决定下游 evo trainer 是否触发 induction / policy tune。
    """

    model_config = {"extra": "forbid"}

    feedback_cell_id: str
    feedback_packet_id: str
    dimension: Dict[str, str] = Field(default_factory=dict)
    metric_name: str
    metric_bucket: str
    delta_bucket: Optional[str] = None
    run_count: int
    building_count: int
    suppressed: bool
    suppression_reason: Optional[str] = None
    suggested_evo_action: Optional[
        Literal[
            "skill_induction_candidate",
            "policy_weight_adjustment",
            "report_guard_attention",
            "none",
        ]
    ] = None


class SanitizedFeedbackPacket(BaseModel):
    """evaluator → broker 输出的盲化反馈包（spec v1 §8.3 + B.5）。

    硬约束（spec v1 §8.4）：
    - run_count >= 10
    - building_count >= 3
    - cells 内未 suppressed 的 cell 各自 run_count>=10 + building_count>=3
    - metric_bucket 四舍五入 0.05 或枚举 low/medium/high
    - 不得含原始 ids / 自由文本 evaluator 评论

    **v1.1 修订（spec §0.6 修订 2 + §3.6.5 + §8.6）**：
    - ``release_delay_window_count`` 改 Optional（v1.0 强制 ≥1 是生产 traffic
      假设，实验室阶段无意义；§8.6 整段删）；
    - ``reconstruction_audit_passed`` 字段语义重定位至 artifact 端
      （spec §3.6.5 + §11.9 v1.1 修订），packet 端字段保留供历史兼容。
    """

    model_config = {"extra": "forbid"}

    feedback_packet_id: str
    eval_window_id: str
    source_eval_truth_report_hash: str
    aggregation_level: Literal[
        "batch_rule_family",
        "batch_slot_class",
        "batch_obligation_kind",
        "batch_error_taxonomy",
    ]
    run_count: int
    building_count: int
    cell_count: int
    rounding_policy: Literal["nearest_0.05", "bucket_low_medium_high"]
    # v1.1 §0.6 修订 2 + §3.6.5 + §8.6：改为可选（实验室阶段不强制延迟发布）
    release_delay_window_count: Optional[int] = None
    cells: List[FeedbackCell] = Field(default_factory=list)
    forbidden_scan_passed: bool
    k_anonymity_passed: bool
    reconstruction_audit_passed: bool
    created_at: str
    released_at: str


# --- B.6 SkillValidationRecord -----------------------------------------------
class SkillValidationRecord(BaseModel):
    """Skill 通过 5 Gate 的单条验证记录（spec v1 §9.4 + B.6）。

    active 状态要求：所有 gate 记录 passed=True / leakage_hits=[] /
    closure_regression_count=0 / allow_stop_authority_check=True。
    `notes` / 自由文本字段一律不允许（spec v1 §8.4 防 evaluator 文本泄漏）。
    """

    model_config = {"extra": "forbid"}

    validation_id: str
    skill_version_id: str
    validation_stage: Literal[
        "gate0_static",
        "gate1_schema_provenance",
        "gate2_replay_ab",
        "gate3_stability",
        "gate4_holdout_counterfactual",
        "release_gate",
    ]
    eval_set_id: str
    eval_set_hash: str
    run_count: int
    building_count: int
    world_family_count: int
    metric_name: str
    metric_value_bucket: str
    metric_delta_bucket: Optional[str] = None
    confidence_bucket: Optional[Literal["low", "medium", "high"]] = None
    passed: bool
    failure_reasons: List[str] = Field(default_factory=list)
    leakage_hits: List[str] = Field(default_factory=list)
    closure_regression_count: int = 0
    allow_stop_authority_check: bool
    validator_version: str
    created_at: str


# --- B.7 EvoMemoryStoreConfig ------------------------------------------------
class EvoMemoryStoreConfig(BaseModel):
    """EvoMemoryStore 逻辑 store 配置（spec v1 §3.6 + B.7）。

    `runtime_agent_direct_read=False` + `evaluator_raw_truth_read=False`
    是 v1 默认硬约束（spec v1 §2 4 类边界）：
    - runtime agent 不直接读 EvoMemoryStore（防 evo policy 信号反推 W2）；
    - evaluator raw truth 不进入 EvoMemoryStore（防 broker 旁路）。
    """

    model_config = {"extra": "forbid"}

    store_id: str
    backend: Literal["neo4j", "duckdb", "filesystem", "postgres"]
    visibility: Literal["evo_trainer_visible"] = "evo_trainer_visible"
    contains: List[
        Literal[
            "EvoRunTrace",
            "ReplayCase",
            "EvoPolicyVersion",
            "EvoSkillPackageMetadata",
            "SkillValidationRecord",
            "SanitizedFeedbackPacket",
            "EvoReleaseCard",
        ]
    ] = Field(default_factory=list)
    forbidden_labels: List[str] = Field(default_factory=list)
    forbidden_properties: List[str] = Field(default_factory=list)
    write_audit_required: bool = True
    runtime_agent_direct_read: bool = False
    evaluator_raw_truth_read: bool = False


# --- B.8 EvoReleaseCard ------------------------------------------------------
class EvoReleaseCard(BaseModel):
    """Skill / Policy / SkillSet 发布证据卡（spec v1 §3.6.6 + §9.7 + B.8）。

    spec v1 §11.6：没有 ReleaseCard 的 Skill / Policy 不能成为 scaling law
    论文曲线上的点。

    **v1.1 修订（spec §0.6 修订 2 + §3.6.6）**：
    - 删除 ``rollback_condition``（实验室阶段用 git revert 回滚，不需要
      schema 层维护回滚条件，§3.6.6 末段）；
    - 删除 ``canary_plan``（§9.8 canary 整段删）；
    - ``reconstruction_audit_passed`` 字段语义重定位至 artifact 端
      （§3.6.6 + §11.9 v1.1 修订：审 artifact 是否泄漏 raw W2，必须 true）。

    保留 audit 必要字段：``leakage_audit_passed`` / ``reconstruction_audit_passed`` /
    ``closure_non_regression_passed`` / ``candidate_floor_passed`` 仍是 release
    gate 必要凭证（spec §9.12 v1.1 简化后项 7 保留这些字段）。
    """

    model_config = {"extra": "forbid"}

    release_card_id: str
    artifact_type: Literal["skill", "policy", "skill_set"]
    artifact_version_id: str
    effective_trace_count: float
    n_valid_runs: int
    n_effective_traces: int
    n_active_skills: int
    n_effective_skills: int
    heldout_metric_summary: Dict[str, Any] = Field(default_factory=dict)
    ablation_delta: Dict[str, Any] = Field(default_factory=dict)
    leakage_audit_passed: bool
    reconstruction_audit_passed: bool
    closure_non_regression_passed: bool
    candidate_floor_passed: bool
    created_at: str


# ===========================================================================
# 导出清单
# ===========================================================================

__all__ = [
    # 闭包侧 enum（Literal 别名）
    "ObligationKind",
    "ClosureStatus",
    "SatisfactionStatus",
    "BlockedReasonCode",
    "OpenReasonCode",
    # 闭包侧 DTO
    "Obligation",
    "ObligationSet",
    "ClosureSummary",
    "ClosureValidationResult",
    # 数据侧 DTO
    "FactAtom",
    "FactPack",
    "RuleSlice",
    "RuleCardDTO",
    "RuleFamilyDTO",
    "SemanticSlotDTO",
    "MeasureDTO",
    "ArtifactDTO",
    "TimeAnchorDTO",
    "SourceQuoteDTO",
    # 会话载体
    "ComplianceAssessmentRun",
    # v1 evo DTO（spec v1 Appendix B）
    "EvoRunStep",
    "EvoRunTrace",
    "SkillScope",
    "SkillJson",
    "EvoSkillPackage",
    "EvoPolicyVersion",
    "FeedbackCell",
    "SanitizedFeedbackPacket",
    "SkillValidationRecord",
    "EvoMemoryStoreConfig",
    "EvoReleaseCard",
]
