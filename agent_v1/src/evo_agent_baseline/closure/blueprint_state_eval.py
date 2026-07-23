"""identity-v2 阶段二求值器 —— 在**阶段一已过闸**的 `ObligationBlueprint`（身份）上跑求值，
产 `ObligationStateV2` + 组装 `ObligationV2`（spec 草案 v4 Block A · A.1 两阶段架构·阶段二）。

**加性旁路**（本模块与 v1 判定路径**并存**，不接活路径、不切换）：

- **核心架构——消费阶段一已过闸 blueprint（不重建、不绕闸）**：阶段二**不**自己 `build_*_blueprint`
  重建身份，而是**消费**阶段一 `derive_covered_card_blueprints` / `derive_covered_blueprints_from_bundle`
  产出的**已过闸** `ObligationBlueprint`（带 `CardBindingRegistry` 跨源项闸、DTO 聚合校验、
  `RegimeSignatureRegistry` 跨卡签名闸、空 applicability fail-closed、Decimal ingress 全已生效）。
  阶段二**按 (source_channel, source_item_id) 把 blueprint 关联到其源义务**，逐个跑 v1
  `obligation_deriver.evaluate_*` 配状态。阶段一闸在**取 blueprint 时**就已 hard-fail 非法卡
  （重复 threshold_regime_id / 空 applicability / float 阈值断线等）——阶段二直接继承，绝不重建绕过。

- **核心约束——复用 v1 求值语义（不新写判定逻辑）**：阶段二的每条状态都由 v1
  `evaluate_*`（threshold_eval 的比较、fact_binding 的解引用、trigger 匹配等）产出一个 v1
  `Obligation`，再由 `obligation_to_state_v2` **无判定地重打包**成 `ObligationStateV2`。判定权仍在
  v1 确定性求值器；本模块只做「状态搬运 + 身份关联组装」。故同一源义务的 v2 状态与 v1 `Obligation`
  的 closure_status / satisfaction_status / reason_code **逐条字节等价**。

- **身份来自阶段一**：`ObligationV2.identity / immutable / canonical_identity_hash` 全取自
  **已过闸** `ObligationBlueprint`（从源头冻结、不含求值态）；`state` 来自 v1 求值；`provenance` =
  蓝图冻结 provenance（身份期）∪ v1 义务运行期 provenance（evidence_fact_ids / recipient_ids）。

- **Decimal / float 双读径分工（blocker 6）**：blueprint（身份）走 **Decimal 读径**
  （`rulecard_decimal_load`，float 阈值卡不断线）；v1 evaluate（判定）走 **float 卡**（v1 生产读径，
  Decimal 卡不序列化失败）。二者按 (rule_card_id, source_channel, source_item_id) 关联——source_item_id
  编码与数值无关（只吃 regime_id / condition_id / slot_ref_id 等字符串键），故跨 Decimal/float 稳定。

- **去重 / 碰撞挂点（blocker 5：折叠前单射）**：`finalize_obligations_v2` 走
  `dedupe_key`(≡canonical_identity_hash) 分组；**折叠前**先验单射（`_assert_pre_merge_injective`：
  同组成员 canonical identity bytes 全等 + recompute 一致），使真 hash collision（同 hash 异 identity）
  在 `merge_obligations` 折叠**擦除第二身份之前**就 hard-fail；发布前再挂 `run_collision_postcheck`。

**覆盖 channel（源义务 1:1 配对 v1 evaluate_*）**：trigger（slot+measure）/ slot_role /
threshold（literal+formula）/ workflow_artifact / **workflow_deadline**（v4：独立 deadline 义务）/
evidence / definition / exception / obligation_graph（**v4：全 node**（node-main out[0]）+
**method-derived 子义务** + edge）。

**条件产出 channel（阶段一身份恒存，v1 仅在特定 verdict 分支产运行义务；阶段二仅在 v1 产义务处
配对状态）**：
- **obligation_graph edge**（target 未激活 / 悬空 / 未知关系才产义务；target 激活产 0 条）。
- **method-derived 子义务**（§5.3 + §3.4③ blocker 1）：阶段一 method-derived blueprint **仅结构可分
  节点**静态建（`_node_method_separable`：node 产 method **且** 带 artifact_ids/deadline_ids 区分键 →
  node-main dedupe ≠ method-sub dedupe → v1 不折叠，真卡 5 卡）；**不可分**节点（真卡 2 卡，v1 必折叠）
  **不建**独立 method-derived。v1 `evaluate_obligation_node` 在 trigger_active=open/blocked 或悬空引用时
  **提前返回**、`node_out` 不含 method 子义务 → 阶段二**仅当实际含 method 子义务才配对**——**可分** node
  配 method-derived blueprint（异 hash → finalize 保 2）、**不可分** node 配回 **node-main blueprint**
  （同 hash → finalize merge 成 1，v2 净 == v1 净）；不存在时不消费该 blueprint（不合成、不报 miss、
  不改双向核对闸——`_declared_covered_source_items` 按同一可分条件静态登记与 blueprint manifest 双向一致）。

**node 携带的子义务（阶段二不单独配对，被独立 channel 覆盖、字节等价）**：
- **node artifact 子**（`evaluate_obligation_node` out[1:] 里的 artifact sub）→ 由 workflow_artifact
  channel 承载、dedup 等价（§4.2）。
- **node deadline 子**（out[1:] 里的 deadline sub）→ 由 workflow_deadline channel（独立 deadline）
  承载、字节等价（同一 `evaluate_deadline`），finalize dedup 后同一集（§4.1/§5.1）。

**隔离 channel（据实报，不接阶段二状态）**：
- **applicability**：`ApplicabilityDTO.building_scope/component_scope` 声明 `List[str]`
  （`source_dtos`），而 v1 活路径求值器 `applicability.py:evaluate_applicability` 按 **dict**
  处理（`_scope_conflicts` / `_match_component_scope` 迭代 `.items()`，且 `isinstance(...,dict)`
  门控）——DTO/求值器类型不一致。对齐类型须改 `evaluate_applicability`（= 动 v1 判定路径，本
  加性单元禁）或改 DTO 为 dict（= 改身份材料、须 bump），二者均越本单元范围。且 applicability
  的 v1 侧是**卡级**判定（`evaluate_applicability`→`make_scope_*`），产 kind="scope" 义务且**仅**
  在 not_applicable/uncertain 分支产、与蓝图 kind="scope_audit"（每卡恒一条）不 1:1。故本单元
  **隔离** applicability 阶段二状态、据实登记缺陷（`APPLICABILITY_TYPE_DEFECT`），不 fail-open 糊。
  （阶段一仍为每卡冻结一条 applicability scope-audit 蓝图；阶段二只是**不关联/不配状态**。）

**v1 判定路径零改**：本模块**只调用** v1 `evaluate_*` / `aggregate_trigger_logic`（读语义），
**绝不改写** closure_status / satisfaction_status / allow_stop；不 import/触碰
`validate_building_closure` / v1 `dedupe_key` / `_merge_two`。

blind 红线（A.9）：本模块**禁 import** `eval.*` / `TruthBundle` / `threshold_evaluations` /
`workflow_engine`；只 import 同包中立求值/身份/蓝图模块 + 中立 `canonical_profile` 传递依赖。
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from canonical_profile import canonical_json, nfc

from evo_agent_baseline.contracts import Obligation

from .blueprint_deriver import (
    _assert_known_node_kind,
    _card_edge_audit_specs,
    _edge_dangling_sid,
    _edge_inactive_target_sid,
    _edge_unknown_relation_sid,
    _encode_source_item_id,
    derive_covered_blueprints_from_bundle,
    derive_covered_card_blueprints,
    edge_audit_spec_source_item,
)
from .fact_binding import FactIndex
from .identity_v2 import (
    COMPARATOR_NOT_EVALUATED,
    IDENTITY_SCHEMA,
    ObligationBlueprint,
    ObligationContractError,
    ObligationProvenanceV2,
    ObligationStateV2,
    ObligationV2,
    RunInstanceEnvelope,
    compute_canonical_identity_hash,
    compute_obligation_id_v2,
    dedupe_key,
    merge_obligations,
    run_collision_postcheck,
)
from .obligation_deriver import (
    SourceToken,
    _extract_artifact_key,
    _stable_key,
    aggregate_trigger_logic,
    evaluate_artifact_obligation,
    evaluate_deadline,
    evaluate_definition,
    evaluate_evidence_requirement,
    evaluate_exception,
    evaluate_obligation_edges,
    evaluate_obligation_node,
    evaluate_slot_role,
    evaluate_threshold,
    evaluate_trigger,
    refine_action_kind,
)
from .schema import ObligationEdgeDTO, ObligationNodeDTO

# ===========================================================================
# 据实报缺陷：applicability DTO/求值器类型不一致（见模块 docstring 隔离 channel）
# ===========================================================================
APPLICABILITY_TYPE_DEFECT: Dict[str, str] = {
    "symptom": (
        "ApplicabilityDTO.building_scope/component_scope 声明 List[str]（source_dtos.py），"
        "evaluate_applicability（applicability.py）按 dict 处理："
        "building_scope 经 `isinstance(...,dict)` 门控 + `_scope_conflicts` 迭代 .items()；"
        "component_scope 同构 `_match_component_scope`。list 形 scope → 规则 2/3 静默跳过。"
    ),
    "disposition": (
        "隔离（本加性单元不接 applicability 阶段二状态）。对齐类型二选一均越本单元范围："
        "①改 evaluate_applicability 收 List[str] = 动 v1 判定路径（禁）；"
        "②改 ApplicabilityDTO 为 dict = 改身份材料、须 bump（另 spec 先行单元）。"
    ),
    "asymmetry": (
        "applicability v1 侧为卡级判定（evaluate_applicability→make_scope_*），产 kind='scope' "
        "义务且仅 not_applicable/uncertain 分支产；蓝图 kind='scope_audit' 每卡恒一条 → 不 1:1。"
    ),
}

# ===========================================================================
# 验收契约诚实化登记（blocker 2 / 修 overclaim）：v1 `_merge_two`（**order-dependent** 生产语义，
# primary=首参）与 v2 `merge_states`（**order-independent** committed 契约，A.7，**不可动**，
# max-by-rank）在合并**异 reason** 义务时选**不同** reason_code。
#
# **旧登记 overclaim = 「恰 2 对列明保守漂移」——已删**。真相：该发散是**一般的**（general
# divergence），非 2 对。跨完整 **v1-可构造** reason 全序表（OPEN_REASON_ORDER ∩ v1 open Literal
# = 8 码；BLOCKED_REASON_ORDER ∩ v1 blocked Literal = 13 码，剔 merge-only `ambiguous_merged_observation`）
# 实测 **106 处方向发散**（28 open + 78 blocked），旧登记的 2 对只是其真子集（其余 104 处旧测未覆盖）；
# 且 **25 处在 advisory 高风险 tier 上非保守**（merge_states 选**更低** tier，反例
# `missing_required_field_group`[medium] → `depends_on_open_trigger`[low]）——故「2 对保守漂移」
# 声称双重失真（既非 2、也非恒保守）。
#
# **可达性诚实重述（旧「生产不可达」声称已删——被 codex 证伪）**：identity（`CanonicalObligationIdentity`）
# **不含 FactIndex 快照**，故「同 (scope, identity) ⟹ 同事实 ⟹ 同 reason」不成立——同一
# (run, scope, identity) 可来自**不同事实快照**产**异 reason**。活代码反例（codex，见测试
# `test_multisnapshot_same_identity_advisory_reason_drift_reachable`）：同一 evidence blueprint、
# 同 run/scope/identity，两个合法 FactIndex 快照分别产 `missing_measurement`（快照 B：field group 在、
# measure 缺）与 `missing_required_field_group`（快照 A：field group 缺）——两者 closure 均 open、
# `merged_observation_bottom=()`；送 `finalize_obligations_v2`（生产合并入口）**合并成功**、v1 `_merge_two`
# 选 primary=`missing_measurement`、v2 `merge_states` 选 max-by-rank=`missing_required_field_group`。
# 故 reason 漂移**可达**，落点是 **advisory 层**（reason_code + `find_high_risk_items` 高风险 tier →
# 只影响报告排序与人工复核提示），**不入 allow_stop 公式**（`compute_allow_stop_and_reason` 只吃
# open/blocked/violated 计数 + schema/forbidden，reason_code 不入参）。真语料当前 1885 组全 singleton
# （无多成员组），故**真语料不演任何真实 merge**——它是「当前语料无多成员组」的事实快照，**不证**漂移
# 不可达（旧测把 singleton 空转误当不可达证明，已删/重述）。
#
# **切换透明性验收（诚实重述；等价声称限定在无观测冲突合并）**：
#   ① allow_stop **字节等价**（proven，**限定**：`merged_observation_bottom == ()` 的合并——纯 reason 漂移、
#      无观测冲突）——`compute_allow_stop_and_reason` reason_code 不入参。
#   ② closure_status / satisfaction 判定投影**等价**（proven，**同上限定**）——全 reason 序表
#      cross-product 0 mismatch；多快照异 reason 反例合并与 v1 `_merge_two` 逐字段等价。
#   ③ reason / tier 的 **advisory 层漂移**在多快照合并场景**可达**，已登记为**已知限制**（非「生产不可达」）。
#   ④ **B4 观测冲突合并 = 独立已知差异（可达、严格更保守、会改判定投影与 allow_stop）**：同 identity
#      两快照产**异观测**（如 observed 5 vs 9）合并落 ⊥（`merged_observation_bottom != ()`）→ v2 强制
#      `(blocked, unknown, ambiguous_merged_observation)`，而 v1 `_merge_two` 保 primary（可 `(closed,
#      violated)`）→ **判定投影与 allow_stop 都变**（v1 allow=True → v2 allow=False）。方向**严格更保守**
#      （v2 blocked ⟹ ¬allow_stop，绝不比 v1 松——冲突观测不得自信 closed 骗过停机，正是 B4 设计意图），
#      经公开合并入口可达（见 `PHASE_TWO_B4_OBSERVATION_CONFLICT` 登记 + 测试承认该分歧）。
#
# 下列常量为**诚实登记**（非 overclaim）：measured_* 计数由测试对活代码 `_merge_two` / `merge_states`
# 实测核对（`test_merge_reason_selection_diverges_in_general_not_two_pairs`），防回退到旧「恰 2 对」声称；
# reachability 由多快照反例测试守护，防回退到旧「生产不可达」声称。
# ===========================================================================
PHASE_TWO_REASON_DRIFT: Dict[str, Any] = {
    "nature": "general_divergence_reachable_advisory_only",
    "summary": (
        "v2 merge_states（order-independent, max-by-rank）与 v1 _merge_two（order-dependent, "
        "primary=首参）合并**异 reason** 义务时选不同 reason_code。此发散**一般**（非旧 overclaim "
        "『恰 2 对保守漂移』）：全 v1-可构造 reason 序表实测 106 处方向发散（28 open + 78 blocked），"
        "25 处在 advisory tier 上非保守（merge_states 更低 tier）。发散**可达**（identity 不含事实快照，"
        "同 (scope,identity) 可来自异快照产异 reason），落点仅 advisory 层、不入 allow_stop。"
    ),
    # 判定投影（closure_status + satisfaction_status = allow_stop 地基）在全部**纯 reason 发散**上
    # 字节等价——**限定 merged_observation_bottom == ()（无观测冲突）**；观测冲突合并见
    # PHASE_TWO_B4_OBSERVATION_CONFLICT（B4 独立已知差异，会改判定投影、严格更保守）。
    "judgement_projection_byte_equiv": "true_iff_no_observation_conflict",
    # allow_stop 公式不吃 reason_code（reason 发散不触 allow_stop）。
    "reason_code_enters_allow_stop": False,
    # 全序表实测发散计数（诚实登记；测试核对活代码，防回退 overclaim）。
    "measured_directional_divergences": 106,
    "measured_open_divergences": 28,
    "measured_blocked_divergences": 78,
    "measured_nonconservative_tier": 25,
    # 旧 overclaim 登记的 2 对（现仅作『真子集』佐证，证明它远非全部）。
    "legacy_overclaim_pairs": (
        ("open", "missing_fact", "missing_measurement"),
        ("blocked", "unit_mismatch", "ambiguous_fact_binding"),
    ),
    # 可达性（旧「生产不可达」已被 codex 证伪，删）：多快照合并场景**可达**，漂移仅落 advisory 层。
    "reachability": "reachable_advisory_only",
    "reachable_scenario": (
        "identity 不含 FactIndex 快照 ⟹ 同 (run, scope, identity) 可来自不同事实快照产异 reason。"
        "活代码反例：同 evidence blueprint、同 run/scope/identity，快照 B（field group 在/measure 缺）"
        "产 missing_measurement、快照 A（field group 缺）产 missing_required_field_group；两者 closure=open、"
        "merged_observation_bottom=()；送 finalize_obligations_v2 合并成功，v1 _merge_two 选 primary="
        "missing_measurement、v2 merge_states 选 max-by-rank=missing_required_field_group。"
    ),
    # 漂移落点：advisory 层（reason_code + find_high_risk_items 高风险 tier → 报告排序 + 人工复核提示）。
    # **限定**：此「仅 advisory」结论只覆盖纯 reason 漂移（merged_observation_bottom == ()）；观测冲突
    # 合并是另一类（B4，会改判定投影），独立登记于 PHASE_TWO_B4_OBSERVATION_CONFLICT。
    "advisory_layer_only": (
        "纯 reason 漂移（无观测冲突）下：reason_code 与 find_high_risk_items 高风险 tier 只影响报告排序与"
        "人工复核提示；不入 allow_stop 公式、不改 closure/satisfaction 判定投影（该限定范围内等价 "
        "proven：merge_states 与 _merge_two 保守序一致）。"
    ),
    "switch_transparency_acceptance": (
        "allow_stop 字节等价 + closure/satisfaction 判定投影等价（proven，**限定 merged_observation_bottom"
        " == () 的合并**）；reason/tier 的 advisory 层漂移在多快照合并场景可达、已登记为已知限制；"
        "B4 观测冲突合并=独立已知差异（可达、严格更保守、会改判定投影与 allow_stop，见 "
        "PHASE_TWO_B4_OBSERVATION_CONFLICT）——**非全局无条件等价**。"
    ),
}


# ===========================================================================
# B4 观测冲突合并 = 独立已知差异（诚实登记；codex 终审 019f69f8 活代码反例确认可达）。
# 同 (run, scope, identity) 两快照产**异观测**（observed 5 vs 9）→ 合并落 ⊥
# （merged_observation_bottom != ()）→ v2 强制 (blocked, unknown, ambiguous_merged_observation)；
# v1 _merge_two 保 primary（可 (closed, violated)）→ 判定投影与 allow_stop 都变
# （实测 v1 allow=True → v2 allow=False）。方向**严格更保守**：v2 blocked ⟹ ¬allow_stop，
# 绝不比 v1 松——冲突观测不得自信 closed 骗过停机（B4 设计意图，spec v4 A.7③）。
# ===========================================================================
PHASE_TWO_B4_OBSERVATION_CONFLICT: Dict[str, Any] = {
    "nature": "observation_conflict_merge_reachable_strictly_more_conservative",
    "reachable": True,
    "changes_judgement_projection": True,
    "changes_allow_stop": True,
    "direction": "strictly_more_conservative",  # v2 blocked ⟹ ¬allow_stop；绝不放松停机
    "scenario": (
        "同 identity 两合法 FactIndex 快照产异观测（如 observed 5 vs 9）→ finalize 合并落 ⊥"
        "（merged_observation_bottom 含 observed_value_json/comparator_result）→ v2 (blocked, unknown, "
        "ambiguous_merged_observation) vs v1 _merge_two 保 primary (closed, violated)：allow_stop "
        "True→False。"
    ),
    "rationale": (
        "B4 设计意图（spec v4 A.7③）：合并后冲突观测不得自信 closed 骗过 allow_stop——此差异是"
        "有意保守化、非 bug；切换后该场景 v2 只会更难停，不会放松判定。"
    ),
}


# 覆盖 channel（源义务 1:1 配对 v1 evaluate_*）。
COVERED_STATE_CHANNELS = (
    "trigger",
    "slot_role",
    "threshold",
    "workflow_artifact",
    "workflow_deadline",  # v4：独立 workflow_operands.deadlines 义务（§2）
    "evidence",
    "definition",
    "exception",
    "obligation_graph",  # 全 node（node-main out[0]）+ method-derived 子义务 + edge（条件产出）
)

# 隔离 channel（据实报，不接阶段二状态）。
ISOLATED_STATE_CHANNELS = ("applicability",)


# ===========================================================================
# v1 Obligation → ObligationStateV2 纯映射（状态搬运，无判定）
# ===========================================================================

# v2 evaluated_comparator 允许集（identity_v2.ObligationStateV2 的 Literal，除哨兵）。
_V2_COMPARATORS = frozenset({"<=", "<", ">=", ">", "==", "!=", "in", "not_in"})


def _map_comparator(operator: Optional[str]) -> str:
    """v1 `Obligation.operator` → v2 `evaluated_comparator`（运行时实际比较器）。

    - 8 个比较器原样保留（trigger/threshold 比较分支覆写后的运行时算子；formula 达比较时
      threshold_eval 覆写为 `>=`）。
    - `None` / `"formula"`（formula 未达比较即 open/blocked，operator 停留 "formula"）/ 任何
      非比较器串 → `COMPARATOR_NOT_EVALUATED`（""）：语义为「未评估比较器」，与 open/blocked
      未达比较一致。`"⊥"`（COMPARATOR_BOTTOM）仅 merge 落，不由本映射产。
    """
    if isinstance(operator, str) and operator in _V2_COMPARATORS:
        return operator
    return COMPARATOR_NOT_EVALUATED


def obligation_to_state_v2(o: Obligation) -> ObligationStateV2:
    """把 v1 `Obligation` 的 verdict **无判定地重打包**成 `ObligationStateV2`。

    这是「复用 v1 求值语义」的搬运点：closure_status / satisfaction_status / open_reason_code /
    blocked_reason_code / comparator_result / observed / applicability_state / trigger_state /
    depends_on_open_trigger 全**逐字段直取** v1 值（无重判、无归约）；operator → evaluated_comparator
    经 `_map_comparator`（同语义映射）；expected_value_json → evaluated_expected_value_json。
    `merged_observation_bottom` 恒 ()（未合并）。
    """
    return ObligationStateV2(
        closure_status=o.closure_status,
        satisfaction_status=o.satisfaction_status,
        applicability_state=o.applicability_state,
        trigger_state=o.trigger_state,
        depends_on_open_trigger=o.depends_on_open_trigger,
        evaluated_comparator=_map_comparator(o.operator),
        comparator_result=o.comparator_result,
        observed_value_json=o.observed_value_json,
        evaluated_expected_value_json=o.expected_value_json,
        open_reason_code=o.open_reason_code,
        blocked_reason_code=o.blocked_reason_code,
        merged_observation_bottom=(),
    )


# ===========================================================================
# ObligationV2 组装（阶段一冻结身份 + 阶段二状态 + 融合 provenance）
# ===========================================================================


def _sorted_unique(*iterables: Any) -> tuple:
    acc: set = set()
    for it in iterables:
        for x in it or ():
            if x is not None:
                acc.add(str(x))
    return tuple(sorted(acc))


def _provenance_v2(bp: ObligationBlueprint, o: Obligation) -> ObligationProvenanceV2:
    """阶段二 provenance = 蓝图冻结 provenance（身份期）∪ v1 义务运行期 provenance。

    列表字段全 stable_unique(sorted)、顺序无关。evidence_fact_ids / workflow_recipient_ids
    是运行期新增（蓝图无，源自 v1 求值）。
    """
    bpp = bp.provenance
    return ObligationProvenanceV2(
        source_family_id=bpp.source_family_id,
        slot_ref_ids=_sorted_unique(bpp.slot_ref_ids, o.slot_ref_ids),
        artifact_local_ids=_sorted_unique(bpp.artifact_local_ids, o.artifact_ids),
        trigger_dependency_ids=_sorted_unique(
            bpp.trigger_dependency_ids, o.trigger_dependency_ids
        ),
        evidence_fact_ids=_sorted_unique(o.evidence_fact_ids),
        evidence_node_refs=_sorted_unique(bpp.evidence_node_refs, o.evidence_node_refs),
        source_clause_ids=_sorted_unique(bpp.source_clause_ids, o.source_clause_ids),
        source_quote_ids=_sorted_unique(bpp.source_quote_ids, o.source_quote_ids),
        workflow_recipient_ids=_sorted_unique(o.recipient_ids),
    )


def assemble_obligation_v2(bp: ObligationBlueprint, o: Obligation) -> ObligationV2:
    """组装 `ObligationV2`：阶段一冻结身份/immutable + 阶段二状态（v1 verdict 重打包）+ 融合 provenance。

    run_envelope 取蓝图 provenance 的 run/world/building；与 v1 义务的 run/world/building 一致性
    在此校验（不一致 = 误配对，hard-fail `blueprint_obligation_scope_mismatch`，不静默）。
    obligation_id 由 `compute_obligation_id_v2`（含 run_envelope）算，canonical_identity_hash 取
    蓝图冻结值。
    """
    if (
        o.run_id != bp.provenance.run_id
        or o.world_id != bp.provenance.world_id
        or o.building_id != bp.provenance.building_id
    ):
        raise ObligationContractError(
            "blueprint_obligation_scope_mismatch:"
            f"{bp.provenance.run_id}/{bp.provenance.world_id}/{bp.provenance.building_id}"
            f" != {o.run_id}/{o.world_id}/{o.building_id}"
        )
    run_env = RunInstanceEnvelope(
        run_id=bp.provenance.run_id,
        world_id=bp.provenance.world_id,
        building_id=bp.provenance.building_id,
    )
    return ObligationV2(
        obligation_identity_schema=IDENTITY_SCHEMA,
        obligation_id=compute_obligation_id_v2(bp.identity, run_env),
        canonical_identity_hash=bp.canonical_identity_hash,
        identity=bp.identity,
        immutable=bp.immutable,
        state=obligation_to_state_v2(o),
        run_envelope=run_env,
        provenance=_provenance_v2(bp, o),
        notes=o.notes or "",
    )


# ===========================================================================
# 去重 + 碰撞后置（发布前挂点；blocker 5：折叠前单射闸）
# ===========================================================================


def _assert_pre_merge_injective(group: List[ObligationV2]) -> None:
    """blocker 5：折叠**前**验单射（`merge_obligations` 折叠**前**就 hard-fail 非法同 hash 成员）。

    `merge_obligations` 仅比 `canonical_identity_hash`：同 hash 即合并、结果取 `first.identity`。
    真 hash collision（同 hash 异 identity）会被折叠**擦除第二身份**，之后 `run_collision_postcheck`
    只见 merged 单条、`stored_id==recompute` 自洽而**静默通过**（第二身份已丢失、检不出）。

    故在折叠**前**、按 **canonical identity bytes**（非仅 hash）验单射：
    - 同组（同 scope 同 canonical_identity_hash）成员 identity bytes 必须全等 —— 异 →
      `identity_hash_collision_pre_merge`（真 collision，折叠前拦，第二身份不被擦除）；
    - 每条 stored hash / id 与 recompute 一致 —— 异 → `obligation_id_recompute_mismatch`。
    合法去重（同源项同身份多状态）identity bytes 全等 → 恒通过。
    """
    id_bytes: Optional[str] = None
    for o in group:
        b = canonical_json(o.identity.model_dump())
        if id_bytes is None:
            id_bytes = b
        elif b != id_bytes:
            raise ObligationContractError("identity_hash_collision_pre_merge")
    for o in group:
        if o.canonical_identity_hash != compute_canonical_identity_hash(o.identity):
            raise ObligationContractError("obligation_id_recompute_mismatch")
        if o.obligation_id != compute_obligation_id_v2(o.identity, o.run_envelope):
            raise ObligationContractError("obligation_id_recompute_mismatch")


def finalize_obligations_v2(obligations: List[ObligationV2]) -> List[ObligationV2]:
    """去重（同 scope 同身份合并）+ 发布前 `run_collision_postcheck`（A.5）。

    分组键 = (run_id, world_id, building_id, canonical_identity_hash)（dedupe_key ≡ 身份哈希；
    同 scope 同身份 → 一组）。**折叠前**逐组 `_assert_pre_merge_injective`（blocker 5：同 hash
    异 identity 折叠前 hard-fail、不被 merge 擦除），再 `merge_obligations`（state 格 + immutable
    hard-fail + provenance union）；合并后全集喂 `run_collision_postcheck`（recompute 一致 +
    双单射 + dedupe 无逃逸），任一违反 hard-fail、产物不发布。
    """
    groups: Dict[tuple, List[ObligationV2]] = {}
    order: List[tuple] = []
    for o in obligations:
        key = (
            o.run_envelope.run_id,
            o.run_envelope.world_id,
            o.run_envelope.building_id,
            dedupe_key(o),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(o)

    merged: List[ObligationV2] = []
    for k in order:
        group = groups[k]
        _assert_pre_merge_injective(group)  # blocker 5：折叠前验单射（真 collision 折叠前拦）
        merged.append(merge_obligations(group))
    run_collision_postcheck(merged)
    return merged


# ===========================================================================
# 卡级阶段二求值驱动（消费阶段一已过闸 blueprint；按 (channel, source_item_id) 关联 + v1 evaluate_*）
# ===========================================================================


class PairedObligationV2(NamedTuple):
    """一源义务的阶段一/二配对（供等价性测试内省 + 生产消费）。

    - `channel`：source_channel（COVERED_STATE_CHANNELS 之一）。
    - `blueprint`：阶段一**已过闸**冻结 `ObligationBlueprint`（`derive_covered_*` 产、非本模块重建）。
    - `v1_obligation`：v1 `evaluate_*` 产的扁平 `Obligation`（判定权源）。
    - `obligation_v2`：`assemble_obligation_v2(blueprint, v1_obligation)`。
    """

    channel: str
    blueprint: ObligationBlueprint
    v1_obligation: Obligation
    obligation_v2: ObligationV2


def _safe(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else default


def _pair(channel: str, bp: ObligationBlueprint, o: Obligation) -> PairedObligationV2:
    return PairedObligationV2(channel, bp, o, assemble_obligation_v2(bp, o))


# ---- 阶段一 blueprint 关联索引 + source_item_id 关联键（镜像 blueprint_deriver 编码，drift 由探针守护） ----


def _index_blueprints(
    card: Any, blueprints: List[ObligationBlueprint]
) -> Dict[tuple, ObligationBlueprint]:
    """本卡的**已过闸** blueprint → {(source_channel, source_item_id): blueprint}。

    传入 blueprints 可为 run 级全卡集；按 `source_rule_card_id == card.rule_card_id` 过滤本卡。
    """
    rid = str(card.rule_card_id)
    idx: Dict[tuple, ObligationBlueprint] = {}
    for bp in blueprints:
        if bp.identity.source_rule_card_id != rid:
            continue
        key = (bp.identity.source_channel, bp.identity.source_item_id)
        if key in idx:
            # blocker 1④：重复 (channel, source_item_id) 键**报错不覆盖**（旧代码后者静默覆盖前者，
            # 擦除一条已过闸 blueprint 身份而不留痕）。
            raise ObligationContractError(
                f"duplicate_blueprint_key:{rid}:{key[0]}:{key[1]}"
            )
        idx[key] = bp
    return idx


def _bp_for(
    idx: Dict[tuple, ObligationBlueprint], channel: str, sid: str
) -> ObligationBlueprint:
    """按 (channel, source_item_id) 取已过闸 blueprint；未命中 → hard-fail（不 fail-open 静默跳）。

    关联失配（sid 编码 drift / 蓝图缺项）→ `blueprint_association_miss`，绝不静默产无身份 pair。
    """
    bp = idx.get((channel, sid))
    if bp is None:
        raise ObligationContractError(f"blueprint_association_miss:{channel}:{sid}")
    return bp


def _trigger_sid(trigger: Dict[str, Any]) -> str:
    """镜像 `build_trigger_blueprint` 的 source_item_id 编码（condition_id + slot_ref + predicate_kind）。"""
    condition_id = nfc(str(trigger.get("condition_id") or ""))
    slot_ref_id = trigger.get("slot_ref_id")
    predicate_kind = str(trigger.get("predicate_kind") or "")
    return _encode_source_item_id(
        "trigger",
        condition_id,
        {
            "slot_ref_id": nfc(str(slot_ref_id)) if slot_ref_id else "",
            "predicate_kind": predicate_kind,
        },
    )


def _deadline_sid(deadline: Dict[str, Any]) -> str:
    """镜像 `build_workflow_deadline_blueprint` 的 source_item_id 编码（deadline_id + parts={}）。"""
    return _encode_source_item_id(
        "workflow_deadline", nfc(str(deadline.get("deadline_id") or "")), {}
    )


def _method_sid(node: Dict[str, Any]) -> str:
    """镜像 `build_method_derived_blueprint` 的 source_item_id 复合键（node_id + parts={"derived":"method"}）。"""
    return _encode_source_item_id(
        "obligation_graph",
        nfc(str(node.get("obligation_node_id") or "")),
        {"derived": "method"},
    )


def _card_method_keys(card: Any) -> List[Any]:
    return (card.workflow_operands or {}).get("method_keys_allowed", []) or []


def _node_produces_method(card: Any, node: Dict[str, Any]) -> bool:
    """node 是否会产 v1 method 子义务（镜像 `blueprint_deriver._node_produces_method`：
    `refine_action_kind→method` 且卡有 `method_keys_allowed`）。静态结构判据、与运行态无关。"""
    return bool(_card_method_keys(card)) and (
        refine_action_kind(str(node.get("node_kind") or ""), str(node.get("action") or ""))
        == "method"
    )


def _node_method_separable(card: Any, node: Dict[str, Any]) -> bool:
    """method 子义务与 node-main **结构上可分**（§3.4③ blocker 1；镜像
    `blueprint_deriver._node_method_separable`：node 带非空 `artifact_ids`/`deadline_ids` 等 v1 dedupe
    区分键 → node-main dedupe_key ≠ method-sub dedupe_key → v1 不折叠 → 建独立 method-derived blueprint）。

    **静态结构判据**（与阶段一 `build_method_derived_blueprint` 构建条件、`_declared_covered_source_items`
    method-derived 登记条件**完全一致**）：可分 → 阶段二 method 子配 method-derived blueprint（`_method_sid`）；
    **不可分**（真卡 2 卡，v1 必折叠）→ 阶段一不建 method-derived、method 子**配回 node-main blueprint**
    （两 ObligationV2 同 hash → finalize merge 成 1 → v2 净 1 == v1 净 1；非「集合投影掩盖净集真差」）。"""
    return _node_produces_method(card, node) and (
        bool(node.get("artifact_ids")) or bool(node.get("deadline_ids"))
    )


# ===========================================================================
# 来源令牌 → (source_channel, source_item_id) 单一权威（§1.4/§3.4.3，Path A/B 共用）
# ===========================================================================

# role → 规范 source_channel（fail-closed 映射，§1.4）。令牌 channel 参与键构造且**必须**等于此，
# 否则 `token_channel_mismatch`；未知 role → `unknown_source_token_role`。
_ROLE_CANONICAL_CHANNEL: Dict[str, str] = {
    "node": "obligation_graph",
    "method": "obligation_graph",
    "edge_dangling": "obligation_graph",
    "edge_unknown": "obligation_graph",
    "edge_inactive": "obligation_graph",
    "artifact": "workflow_artifact",
    "deadline": "workflow_deadline",
}


def _nodes_by_id(card: Any) -> Dict[str, Dict[str, Any]]:
    return {
        str(n.get("obligation_node_id")): n
        for n in (card.obligation_graph or {}).get("nodes", []) or []
        if isinstance(n, dict)
    }


def token_source_item(
    card: Any,
    token: SourceToken,
    nodes_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """来源令牌 → `(source_channel, source_item_id)`（**单一权威**，§1.4/§3.4.3）。

    Path A（关联层 `identity_binding.token_five_tuple_key`）与 Path B（阶段二 edge 配对）**共用**；
    SID 编码复用 blueprint 侧同一构造点（`_encode_source_item_id` / `_method_sid` / `_deadline_sid` /
    `_edge_dangling_sid` / `_edge_unknown_relation_sid` / `_edge_inactive_target_sid`），杜绝漂移。

    **fail-closed（§1.4，codex 阻断 2 修订）**：
      - 未知 role → `unknown_source_token_role`；
      - `token.channel` **参与键构造**且必须等于 role 的规范 channel，不一致 → `token_channel_mismatch`
        （改任意 channel 串必炸）；
      - `method` 令牌 node 在卡 nodes 缺失 → `method_token_node_missing`（**删静默回落 node-main**）；
        node 在但结构不可分（`_node_method_separable` false）→ 折回 node-main SID（合法，§3.4③）。
    """
    role = token.role
    canonical_channel = _ROLE_CANONICAL_CHANNEL.get(role)
    if canonical_channel is None:
        raise ObligationContractError(f"unknown_source_token_role:{role}")
    if token.channel != canonical_channel:
        raise ObligationContractError(
            f"token_channel_mismatch:{role}:{token.channel}!={canonical_channel}"
        )
    # 令牌契约收紧（codex 非阻断加固）：`member` 仅 edge_unknown 分身合法、`edge_ids` 仅 edge_inactive
    # 聚合合法；其它 role 若携非空判别字段 → hard-fail（杜绝令牌字段错置致误编码/误绑定）。
    if role != "edge_unknown" and token.member != "":
        raise ObligationContractError(
            f"token_member_not_allowed:{role}:{token.member!r}"
        )
    if role != "edge_inactive" and token.edge_ids != ():
        raise ObligationContractError(
            f"token_edge_ids_not_allowed:{role}:{token.edge_ids!r}"
        )
    if role == "node":
        sid = _encode_source_item_id("obligation_graph", nfc(str(token.primary_id)))
    elif role == "method":
        by_id = nodes_by_id if nodes_by_id is not None else _nodes_by_id(card)
        node = by_id.get(str(token.primary_id))
        if node is None:
            raise ObligationContractError(
                f"method_token_node_missing:{token.primary_id}"
            )
        sid = (
            _method_sid(node)
            if _node_method_separable(card, node)
            else _encode_source_item_id("obligation_graph", nfc(str(token.primary_id)))
        )
    elif role == "edge_dangling":
        sid = _edge_dangling_sid(str(token.primary_id))
    elif role == "edge_unknown":
        sid = _edge_unknown_relation_sid(str(token.primary_id), token.member)
    elif role == "edge_inactive":
        sid = _edge_inactive_target_sid(str(token.primary_id), list(token.edge_ids))
    elif role == "artifact":
        sid = _encode_source_item_id("workflow_artifact", str(token.primary_id))
    else:  # deadline
        sid = _deadline_sid({"deadline_id": token.primary_id})
    return (canonical_channel, sid)


def _method_sub_obligation(node_out: List[Obligation]) -> Optional[Obligation]:
    """从 v1 `evaluate_obligation_node` 的 `node_out` 取 method-derivation 子义务（§5.3 控制流镜像）：
    kind=="method" 且 notes 含 "method derivation"（`_evaluate_method_obligation` 标记）。

    **不存在时返回 None**：v1 在 trigger_active=open/blocked 或 node 悬空引用时提前返回、`node_out`
    不含 method 子义务（append 发生在提前返回之后的主路径）——阶段二据此**仅当实际存在时才配对**
    （不合成、不报 miss，与 trigger=false 下游不关联同构）。
    """
    for o in node_out:
        if o.kind == "method" and "method derivation" in (o.notes or ""):
            return o
    return None


def _evidence_sid(req: Dict[str, Any]) -> str:
    """镜像 `build_evidence_blueprint` 的 source_item_id 复合键编码。"""
    req_id = nfc(str(req.get("evidence_requirement_id") or ""))
    ev_kind = str(req.get("kind") or "")
    field_groups = sorted(nfc(str(g)) for g in (req.get("required_field_groups") or []))
    return _encode_source_item_id(
        "evidence",
        req_id,
        {
            "kind": ev_kind,
            "required_field_groups": field_groups,
            "slot_ref_ids": sorted(nfc(str(r)) for r in (req.get("slot_ref_ids") or [])),
            "artifact_ids": sorted(nfc(str(a)) for a in (req.get("artifact_ids") or [])),
            "measure_keys": sorted(nfc(str(m)) for m in (req.get("measure_keys") or [])),
        },
    )


def _declared_covered_source_items(card: Any) -> List[tuple]:
    """float 卡**静态声明的覆盖 channel 源项** `[(source_channel, source_item_id), ...]`（无 trigger
    门控、**排除 applicability 隔离 channel**）。

    **返回 multiset（list，保留多重性）——不折叠重复键**（blocker 1：旧实现用 set 折叠重复
    `(channel, source_item_id)`，后续只做集合差 → float 卡**重复声明同一源项不炸、eval 循环却按
    多重性双配对**，1885→1886 静默过。保留多重性后由 `_assert_dual_read_path_consistency` 在配对
    **前**检测重复键 hard-fail）。

    **镜像 `derive_covered_card_blueprints` 的覆盖枚举 + sid 编码**（blueprint 身份侧的 source-item
    清单），供 run 级双读径**双向**核对（blocker 1③）。与 `evaluate_covered_card_obligations_v2` 的
    eval 循环不同：**不做 trigger_active 门控、不做 evidence/artifact 求值筛**，只按卡结构静态枚举
    （blueprint 身份恒存、与运行态无关）。edge 走 `_card_edge_audit_specs` 三态静态分类（§3.4.3/§5.3.3，
    与 blueprint 侧 `derive_edge_audit_blueprints` 共用同一分类器 + SID 构造点）。枚举漂移由全 397 语料
    双向核对 0 差守护（漂移 → 真语料即 hard-fail）。
    """
    enc = _encode_source_item_id
    out: List[tuple] = []
    # triggers（slot + measure）
    for tr in (card.trigger_conditions or {}).get("items", []) or []:
        if isinstance(tr, dict):
            out.append(("trigger", _trigger_sid(tr)))
    # slot roles（required）
    for sr in card.slot_role_map or []:
        if isinstance(sr, dict) and sr.get("required"):
            out.append(("slot_role", enc("slot_role", str(sr.get("slot_ref_id") or ""))))
    # thresholds（literal + formula）
    for th in card.threshold_regimes or []:
        if isinstance(th, dict):
            out.append((
                "threshold",
                enc("threshold", nfc(str(th.get("threshold_regime_id") or ""))),
            ))
    # obligation_graph：v4 全 node（node-main）+ **结构可分** method 产出 node 的 method-derived（复合
    # parts，§3.4③）+ edge（全边，派生 edge_id）。**静态登记**——method-derived SID 按**结构条件**
    # （`_node_method_separable`：node 产 method **且** 带 artifact_ids/deadline_ids 区分键）登记（与阶段一
    # 构建 method-derived blueprint 条件完全一致），**不随 v1 实际产出变化**（§5.3 唯一口径）：阶段二仅当
    # node_out 实际含 method 子义务才配对——可分 node 配 method-derived、不可分 node 配回 node-main（无独立
    # method-derived）；不配对时不消费该 blueprint、不报 miss、不改本双向核对闸（本清单核「静态声明↔
    # blueprint manifest」，非「实际 pairs↔blueprint」）。
    graph = card.obligation_graph or {}
    for node in graph.get("nodes", []) or []:
        if isinstance(node, dict):
            out.append((
                "obligation_graph",
                enc("obligation_graph", nfc(str(node.get("obligation_node_id") or ""))),
            ))
            # §3.4③：method-derived SID **仅结构可分节点**登记（与阶段一构建条件一致）；不可分 node 的
            # method 子配回 node-main（无独立 method-derived blueprint）→ 不登记 method SID，双向核对 0 差。
            if _node_method_separable(card, node):
                out.append(("obligation_graph", _method_sid(node)))
    # edge 审计三态（§3.4.3/§5.3.3）：dangling / unknown-relation 分身 / inactive-target 聚合。
    # 与 blueprint 侧（`derive_edge_audit_blueprints`）**共用** `_card_edge_audit_specs` 单一分类器 +
    # `edge_audit_spec_source_item` 单一 SID 构造点（同源杜绝漂移；旧「一 edge 一 SID」身份不完备：
    # 未知 relation 一 edge 产 source/target 两义务撞同 SID、多 edge 同 target 只登 min(edge) 丢余身份）。
    for spec in _card_edge_audit_specs(card):
        out.append(edge_audit_spec_source_item(spec))
    # workflow artifacts（镜像 blueprint 侧：每 item 一条）
    for item in (card.workflow_operands or {}).get("artifacts", []) or []:
        if isinstance(item, dict):
            out.append((
                "workflow_artifact",
                enc(
                    "workflow_artifact",
                    str(item.get("artifact_id") or item.get("artifact_key") or ""),
                ),
            ))
    # workflow deadlines（§2：每 deadline 一条 workflow_deadline）
    for deadline in (card.workflow_operands or {}).get("deadlines", []) or []:
        if isinstance(deadline, dict):
            out.append(("workflow_deadline", _deadline_sid(deadline)))
    # evidence requirements（三 bucket，required）
    for reqs in (card.evidence_requirements or {}).values():
        if not isinstance(reqs, list):
            continue
        for req in reqs:
            if isinstance(req, dict) and req.get("required", True):
                out.append(("evidence", _evidence_sid(req)))
    # definitions
    for d in card.definitions or []:
        if isinstance(d, dict):
            out.append((
                "definition",
                enc(
                    "definition",
                    nfc(str(d.get("definition_id") or "")),
                    {"term_key": nfc(str(d.get("term_key") or ""))},
                ),
            ))
    # exceptions（真卡语料 0 条）
    for exc in card.exceptions or []:
        if isinstance(exc, dict):
            out.append((
                "exception",
                enc("exception", nfc(str(exc.get("exception_kind") or ""))),
            ))
    return out


def _assert_card_read_path_consistency(
    card: Any, blueprints: List[ObligationBlueprint]
) -> None:
    """blocker 1：**卡级**双读径一致性闸（run 级与 card 级公开入口共用同一判据）。

    单卡 float 声明覆盖源项 multiset 与本卡 blueprint 覆盖源项**双向**核对（`blueprints` 可为 run 级
    全卡集，按 `source_rule_card_id == card.rule_card_id` 过滤本卡）：

      ④ 本卡 blueprint 覆盖 (channel, source_item_id) **无重复**（→ `duplicate_blueprint_key`）；
      ⑤ 本卡 **float 声明覆盖源项 multiset 无重复键**（→ `duplicate_source_item_in_read_path`；
         旧 set 折叠掩盖多重性 → 重复声明同一源项不炸、eval 循环按多重性双配对静默折回）；
      ③ **float 声明覆盖源项 ⟷ blueprint 覆盖源项 双向一致**
         （float 多 / blueprint 缺 → `blueprint_association_miss`；blueprint 多 / float 缺 →
          `obligation_association_orphan`）。

    applicability 是**隔离 channel**（`ISOLATED_STATE_CHANNELS`，不接阶段二状态），其 blueprint
    合法不配对，故双向核对**仅限 `COVERED_STATE_CHANNELS`**（不误报 applicability 蓝图为孤儿）。

    此为 run 级 `_assert_dual_read_path_consistency` 逐卡委托的**同一闸**，亦被 card 级公开入口
    `evaluate_covered_card_obligations_v2` 直接调用（blocker 1 补漏：旧 card 级入口只建 blueprint
    索引不跑 multiset 闸 → 传 `blueprints=` 时 float 卡重复声明同一源项被 eval 循环按多重性双配对、
    再被 finalize 静默折回，base_pairs→+1→折回）。
    """
    rid = str(card.rule_card_id)
    # ④ 本卡 blueprint 覆盖键无重复（仅覆盖 channel；applicability 隔离蓝图不入 manifest）。
    blueprint_manifest: set = set()
    for bp in blueprints:
        if bp.identity.source_rule_card_id != rid:
            continue
        if bp.identity.source_channel in COVERED_STATE_CHANNELS:
            key = (bp.identity.source_channel, bp.identity.source_item_id)
            if key in blueprint_manifest:
                raise ObligationContractError(
                    f"duplicate_blueprint_key:{rid}:{key[0]}:{key[1]}"
                )
            blueprint_manifest.add(key)

    # ⑤ float 侧 multiset 无重复键 → 配对前 hard-fail（multiset 非 set；旧 set 折叠掩盖多重性）。
    float_items = _declared_covered_source_items(card)  # multiset（保留多重性）
    seen_float: set = set()
    for key in float_items:
        if key in seen_float:
            raise ObligationContractError(
                f"duplicate_source_item_in_read_path:{key[0]}:{key[1]}"
            )
        seen_float.add(key)
    float_manifest = seen_float  # 已证无重复键 → 与 set 等价（供双向差）。

    # ③ 双向一致。
    missing = float_manifest - blueprint_manifest  # float 声明、blueprint 缺。
    if missing:
        ch, sid = sorted(missing)[0]
        raise ObligationContractError(f"blueprint_association_miss:{ch}:{sid}")
    orphan = blueprint_manifest - float_manifest  # blueprint 有、float 不声明。
    if orphan:
        ch, sid = sorted(orphan)[0]
        raise ObligationContractError(f"obligation_association_orphan:{ch}:{sid}")


def _assert_dual_read_path_consistency(
    float_cards: List[Any], blueprints: List[ObligationBlueprint]
) -> Dict[str, List[ObligationBlueprint]]:
    """blocker 1：run 级双读径关联**先双向校验再配对**（绝不 fail-open 静默吞孤儿/重复/断线）。

    float 卡（v1 生产读径，judgement）与 blueprint（Decimal 读径，identity）按 rule_card_id +
    覆盖源项**双向**核对（旧 `by_card.get(...,[])` 单向遍历静默吞 blueprint 孤儿）：

      ② float 卡 rule_card_id **唯一**（重复 → `duplicate_float_card`）；
      ① 两侧**卡集相等**（任一侧缺/多 → `read_path_card_set_mismatch`）；
      ③④⑤ 逐卡委托 `_assert_card_read_path_consistency`（card 级公开入口**同一闸**）：blueprint
         覆盖键无重复 + float 声明覆盖源项 multiset 无重复键 + 双向一致。

    返回**全 channel** 的 by_card 分组（供后续逐卡消费；校验通过后每 float 卡 id 必存）。
    """
    # ② float 卡 ID 唯一。
    float_ids: set = set()
    for c in float_cards:
        cid = str(c.rule_card_id)
        if cid in float_ids:
            raise ObligationContractError(f"duplicate_float_card:{cid}")
        float_ids.add(cid)

    # blueprint 分组（全 channel，供后续逐卡消费）。
    by_card: Dict[str, List[ObligationBlueprint]] = {}
    for bp in blueprints:
        by_card.setdefault(bp.identity.source_rule_card_id, []).append(bp)

    # ① 两侧卡集相等。
    bp_ids = set(by_card.keys())
    if float_ids != bp_ids:
        float_only = sorted(float_ids - bp_ids)
        blueprint_only = sorted(bp_ids - float_ids)
        raise ObligationContractError(
            f"read_path_card_set_mismatch:float_only={float_only}:"
            f"blueprint_only={blueprint_only}"
        )

    # ③④⑤ 逐卡覆盖源项**双向**一致（委托 card 级同一闸）。
    for c in float_cards:
        _assert_card_read_path_consistency(c, by_card[str(c.rule_card_id)])

    return by_card


def evaluate_covered_card_obligations_v2(
    card: Any,
    fact_index: FactIndex,
    meta: Dict[str, str],
    *,
    blueprints: Optional[List[ObligationBlueprint]] = None,
    measure_aliases: Optional[Dict[str, str]] = None,
    trigger_eval_kwargs: Optional[Dict[str, Any]] = None,
) -> List[PairedObligationV2]:
    """一张卡的**覆盖 channel** 阶段二配对求值（单 building scope；镜像 v1 drive-loop 覆盖子集）。

    **消费阶段一已过闸 blueprint（核心架构）**：
    - `blueprints=None` → 就地走 `derive_covered_card_blueprints(card, meta)`（**带 registry 的
      过闸派生**：CardBindingRegistry 跨源项闸 / DTO 聚合校验 / regime 签名闸 / 空 applicability
      fail-closed / Decimal ingress 全生效）。非法卡在**此处** hard-fail、阶段二直接继承（**不**再
      per-item `build_*_blueprint(registry=None)` 重建绕闸）。
    - `blueprints=<已过闸集>` → 直接消费（真语料 float 卡不可就地 Decimal 过闸，须外部 run 级
      `derive_covered_blueprints_from_bundle` 传入；见 `evaluate_covered_run_obligations_v2`）。

    对每个覆盖源项调 v1 `evaluate_*`（判定）→ 按 (source_channel, source_item_id) `_bp_for` 关联到
    **已过闸** blueprint → `assemble_obligation_v2`。关联失配 hard-fail（不 fail-open）。

    **忠实 v1 控制流**：trigger_active 由 `aggregate_trigger_logic`（v1 函数）聚合；trigger 聚合
    False → v1 跳过下游 action 义务 → 阶段二亦只产 trigger 配对（下游已过闸 blueprint 仍在阶段一
    集里、只是本卡此 fact 下不关联状态）。

    **不产**：applicability（隔离，见 `APPLICABILITY_TYPE_DEFECT`）。obligation_graph edge 与
    method-derived 子义务按条件产出（v1 产义务处才配对，§5.3）；node 携带的 artifact/deadline 子
    由 workflow_artifact / workflow_deadline channel 覆盖、不单独配对（§4.1/§4.2）。

    trigger_eval_kwargs：透传给 `evaluate_trigger` 的 DEBT-050 作用域参数（scope_component_types
    等）；默认 None = building 作用域简单判定（判定关闭），与非 fragment 承载卡的楼级求值一致。
    """
    if blueprints is None:
        # 阶段一过闸派生（带 registry；非 per-item registry=None 重建）。
        blueprints = derive_covered_card_blueprints(card, meta)
    # blocker 1 补漏：card 级公开入口（**无论 blueprints 传入与否**）也跑 run 级**同一** multiset
    # 一致性闸——float 声明覆盖源项 multiset 无重复键 + 与本卡 blueprint 覆盖源项双向核对。旧 card 级
    # 入口只建 blueprint 索引不跑此闸 → 传 `blueprints=` 时 float 卡重复声明同一源项被 eval 循环按
    # 多重性双配对、再被 finalize 静默折回（base_pairs→+1→折回 base）。此闸令重复在配对**前** hard-fail。
    _assert_card_read_path_consistency(card, blueprints)
    idx = _index_blueprints(card, blueprints)

    tkw = dict(trigger_eval_kwargs or {})
    enc = _encode_source_item_id
    pairs: List[PairedObligationV2] = []

    # ---- triggers（slot + measure；无 trigger_active）----
    trigger_conditions = card.trigger_conditions or {}
    trigger_items = trigger_conditions.get("items", []) or []
    trigger_results: List[Obligation] = []
    for trigger in sorted(trigger_items, key=lambda x: str(_safe(x, "condition_id"))):
        if not isinstance(trigger, dict):
            continue
        o = evaluate_trigger(
            card, dict(trigger), fact_index, meta, measure_aliases=measure_aliases, **tkw
        )
        bp = _bp_for(idx, "trigger", _trigger_sid(trigger))
        pairs.append(_pair("trigger", bp, o))
        trigger_results.append(o)

    trigger_active = aggregate_trigger_logic(
        trigger_conditions.get("logic", "all"), trigger_results
    )
    # trigger 聚合 False：v1 跳过下游 action 义务（合成 not_applicable 审计无蓝图源项）。
    if trigger_active is False:
        return pairs

    # ---- slot roles（required；trigger_active 继承）----
    for slot_ref in sorted(
        card.slot_role_map or [], key=lambda x: str(_safe(x, "slot_ref_id"))
    ):
        if isinstance(slot_ref, dict) and slot_ref.get("required"):
            o = evaluate_slot_role(card, dict(slot_ref), fact_index, trigger_active, meta)
            bp = _bp_for(idx, "slot_role", enc("slot_role", str(slot_ref.get("slot_ref_id") or "")))
            pairs.append(_pair("slot_role", bp, o))

    # ---- thresholds（literal + formula；trigger_active 继承）----
    for threshold in sorted(
        card.threshold_regimes or [], key=lambda x: str(_safe(x, "threshold_regime_id"))
    ):
        if isinstance(threshold, dict):
            o = evaluate_threshold(
                card, dict(threshold), fact_index, trigger_active, meta, measure_aliases
            )
            bp = _bp_for(
                idx, "threshold",
                enc("threshold", nfc(str(threshold.get("threshold_regime_id") or ""))),
            )
            pairs.append(_pair("threshold", bp, o))

    # ---- obligation_graph nodes（v4 全 node：node-main out[0] + method-derivation 子义务）----
    graph = card.obligation_graph or {}
    for node in sorted(
        graph.get("nodes", []) or [], key=lambda x: str(_safe(x, "obligation_node_id"))
    ):
        if not isinstance(node, dict):
            continue
        # blocker 3：raw-kind 闸也守**外供 blueprint** 入口——`blueprints=` 传入时不经
        # `derive_covered_card_blueprints`（其含闸），故 node 消费路径在 `from_dict` 归一**之前**
        # 亦过 `_assert_known_node_kind`（共享同一闸）；否则 brand_new_kind 被 from_dict 归一 obligation
        # 静默接受（母病断根被绕过）。
        _assert_known_node_kind(node)
        node_out = evaluate_obligation_node(
            card, ObligationNodeDTO.from_dict(dict(node)), fact_index,
            trigger_active, meta,
        )
        bp = _bp_for(
            idx, "obligation_graph",
            enc("obligation_graph", nfc(str(node.get("obligation_node_id") or ""))),
        )
        # out[0] 恒为 node-level 主义务（继承/悬空早退单元素；主判定路径亦首 append）。
        pairs.append(_pair("obligation_graph", bp, node_out[0]))
        # method 子义务（§5.3 控制流镜像）：**仅当 node_out 实际含 method-derivation 子义务才配对**
        # （v1 在 trigger_active=open/blocked 或悬空引用时提前返回、node_out 不含 method 子 → 不配对、
        # 不合成状态、不报 blueprint_association_miss——blueprint 当次无状态关联，与 trigger=false 下游
        # blueprint 不关联同构）。**§3.4③ blocker 1**：配对宿主由结构可分性决定——**可分** node 配
        # method-derived blueprint（异 hash → finalize 保 2，v2 净 2 == v1 净 2）；**不可分** node（真卡
        # 2 卡，无独立 method-derived）配回 **node-main blueprint**（同 hash → finalize merge 成 1，
        # v2 净 1 == v1 净 1；不再「集合投影掩盖净集真差」）。
        if _node_produces_method(card, node):
            msub = _method_sub_obligation(node_out)
            if msub is not None:
                mbp = (
                    _bp_for(idx, "obligation_graph", _method_sid(node))
                    if _node_method_separable(card, node)
                    else bp  # 不可分：配回 node-main → finalize merge
                )
                pairs.append(_pair("obligation_graph", mbp, msub))

    # ---- obligation_graph edges（条件产出：按 obligation_edge_id 配对 v1 边义务）----
    edges = graph.get("edges", []) or []
    if edges:
        # v1 边义务需 node_obligations 上下文（source node 激活判定）；全 node（含普通/升级）经 v1 评。
        node_obligations: Dict[str, List[Obligation]] = {}
        for node in sorted(
            graph.get("nodes", []) or [],
            key=lambda x: str(_safe(x, "obligation_node_id")),
        ):
            if not isinstance(node, dict):
                continue
            _assert_known_node_kind(node)  # blocker 3：edge 上下文 node 重构亦守 raw-kind 闸
            node_dto = ObligationNodeDTO.from_dict(dict(node))
            node_obligations[node_dto.obligation_node_id] = evaluate_obligation_node(
                card, node_dto, fact_index, trigger_active, meta
            )
        # 边义务按**来源令牌**（§1.4/§3.4.3 edge 审计三态）配对——Path B 与 Path A（关联层）**共用**
        # `token_source_item` 单一 SID 权威（旧「按 obligation_edge_id 逐 id 配对」对未知 relation 分身/
        # 多 edge 聚合会误配或多配，身份不完备）。每条边义务恰一令牌（token[i] ↔ edge_obls[i]，同序登记）。
        etokens: List[SourceToken] = []
        edge_obls = evaluate_obligation_edges(
            card, edges, node_obligations, fact_index, meta, source_sink=etokens
        )
        if len(etokens) != len(edge_obls):
            raise ObligationContractError(
                f"source_token_count_mismatch:{len(edge_obls)}!={len(etokens)}"
            )
        edge_nodes_by_id = _nodes_by_id(card)
        for eo, tok in zip(edge_obls, etokens):
            channel, sid = token_source_item(card, tok, edge_nodes_by_id)
            bp = _bp_for(idx, channel, sid)
            pairs.append(_pair(channel, bp, eo))

    # ---- workflow_operands.artifacts（trigger_active 继承）----
    for item in sorted(
        (card.workflow_operands or {}).get("artifacts", []) or [],
        key=lambda x: _stable_key(x),
    ):
        if not isinstance(item, dict):
            continue
        key = _extract_artifact_key(item)
        if not key:
            continue
        o = evaluate_artifact_obligation(
            card, key, "artifact", fact_index, trigger_active, meta,
            artifact_id=item.get("artifact_id"), bucket="workflow_operands.artifacts",
        )
        bp = _bp_for(
            idx, "workflow_artifact",
            enc("workflow_artifact", str(item.get("artifact_id") or item.get("artifact_key") or "")),
        )
        pairs.append(_pair("workflow_artifact", bp, o))

    # ---- workflow_operands.deadlines（§2；镜像 derive_workflow_deadline_obligations，trigger_active 继承）----
    # 独立 deadline 义务（v1 `derive_workflow_deadline_obligations` 对称补的独立循环）；node 携带的
    # deadline 子义务（`evaluate_obligation_node` out[1:] 里的 deadline sub）阶段二**不单独配对**——
    # 被独立 deadline 覆盖、字节等价（同一 `evaluate_deadline`），finalize dedup 后同一集（§4.1/§5.1）。
    for deadline in sorted(
        (card.workflow_operands or {}).get("deadlines", []) or [],
        key=lambda x: _stable_key(x),
    ):
        if not isinstance(deadline, dict):
            continue
        o = evaluate_deadline(card, dict(deadline), fact_index, trigger_active, meta)
        bp = _bp_for(idx, "workflow_deadline", _deadline_sid(deadline))
        pairs.append(_pair("workflow_deadline", bp, o))

    # ---- evidence_requirements（三 bucket，required；trigger_active 继承）----
    evidence_reqs = card.evidence_requirements or {}
    for bucket_name in sorted(evidence_reqs.keys()):
        reqs = evidence_reqs.get(bucket_name) or []
        if not isinstance(reqs, list):
            continue
        for req in sorted(reqs, key=lambda x: str(_safe(x, "evidence_requirement_id"))):
            if isinstance(req, dict) and req.get("required", True):
                o = evaluate_evidence_requirement(
                    card, bucket_name, dict(req), fact_index, trigger_active, meta
                )
                bp = _bp_for(idx, "evidence", _evidence_sid(req))
                pairs.append(_pair("evidence", bp, o))

    # ---- exceptions（真卡语料 0 条；无 trigger_active）----
    for exc in sorted(card.exceptions or [], key=lambda x: _stable_key(x)):
        if isinstance(exc, dict):
            o = evaluate_exception(card, dict(exc), fact_index, meta)
            bp = _bp_for(idx, "exception", enc("exception", nfc(str(exc.get("exception_kind") or ""))))
            pairs.append(_pair("exception", bp, o))

    # ---- definitions（无 trigger_active）----
    for definition in sorted(card.definitions or [], key=lambda x: _stable_key(x)):
        if isinstance(definition, dict):
            o = evaluate_definition(card, dict(definition), fact_index, meta)
            bp = _bp_for(
                idx, "definition",
                enc(
                    "definition",
                    nfc(str(definition.get("definition_id") or "")),
                    {"term_key": nfc(str(definition.get("term_key") or ""))},
                ),
            )
            pairs.append(_pair("definition", bp, o))

    return pairs


def evaluate_covered_card_v2(
    card: Any,
    fact_index: FactIndex,
    meta: Dict[str, str],
    *,
    blueprints: Optional[List[ObligationBlueprint]] = None,
    measure_aliases: Optional[Dict[str, str]] = None,
    trigger_eval_kwargs: Optional[Dict[str, Any]] = None,
) -> List[ObligationV2]:
    """便捷入口：卡级覆盖 channel 阶段二求值 → 去重/碰撞后 `ObligationV2` 列表。"""
    pairs = evaluate_covered_card_obligations_v2(
        card, fact_index, meta,
        blueprints=blueprints,
        measure_aliases=measure_aliases, trigger_eval_kwargs=trigger_eval_kwargs,
    )
    return finalize_obligations_v2([p.obligation_v2 for p in pairs])


def evaluate_covered_run_obligations_v2(
    bundle_path: Any,
    float_cards: List[Any],
    fact_index: FactIndex,
    meta: Dict[str, str],
    *,
    measure_aliases: Optional[Dict[str, str]] = None,
    trigger_eval_kwargs: Optional[Dict[str, Any]] = None,
) -> List[PairedObligationV2]:
    """**统一 run 级入口（blocker 1&2 / blocker 6 生产 Decimal 读径）**：

    从 `bundle_path` 经 `derive_covered_blueprints_from_bundle`（Decimal 读径 + run 级
    `RegimeSignatureRegistry` 跨卡签名闸 + 卡级全闸）拿**已过闸** blueprint（阶段一）；再逐张
    `float_cards`（v1 生产读径，用于 evaluate 判定）走阶段二配状态。

    Decimal / float 分工：identity 来自 Decimal 读径（13 float 阈值卡不断线），judgement 来自 float
    卡（5 Decimal 卡不序列化失败）；按 (rule_card_id, channel, source_item_id) 关联（sid 数值无关、
    跨 Decimal/float 稳定）。非法卡（重复 regime / 空 applicability / 签名冲突）在取 blueprint 时即
    hard-fail、阶段二继承。
    """
    blueprints = derive_covered_blueprints_from_bundle(bundle_path, meta)
    # blocker 1：双读径**先双向校验再配对**（卡集相等 + float 卡唯一 + 覆盖源项双向一致 +
    # blueprint 键无重复）；旧 `by_card.get(...,[])` 单向遍历会静默吞 blueprint 孤儿（fail-open）。
    by_card = _assert_dual_read_path_consistency(float_cards, blueprints)
    pairs: List[PairedObligationV2] = []
    for card in float_cards:
        card_bps = by_card[str(card.rule_card_id)]  # 校验后必存（无 .get 兜底 = 无静默吞）。
        pairs.extend(
            evaluate_covered_card_obligations_v2(
                card, fact_index, meta, blueprints=card_bps,
                measure_aliases=measure_aliases, trigger_eval_kwargs=trigger_eval_kwargs,
            )
        )
    return pairs


__all__ = [
    "APPLICABILITY_TYPE_DEFECT",
    "PHASE_TWO_REASON_DRIFT",
    "COVERED_STATE_CHANNELS",
    "ISOLATED_STATE_CHANNELS",
    "PairedObligationV2",
    "obligation_to_state_v2",
    "assemble_obligation_v2",
    "finalize_obligations_v2",
    "evaluate_covered_card_obligations_v2",
    "evaluate_covered_card_v2",
    "evaluate_covered_run_obligations_v2",
]
