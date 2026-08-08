"""unknown 归因（纯函数旁路）——把「要专业人员填」与「系统坏了」分开。

用户拍板的验收标准：「不是判定系统，最终判决从一开始就是使用这个系统的专业人员做的
事情，**但是也不能无故 unknown，这是两码事**」。当前两类 unknown 共用一个标签，专业
人员分不出「要我填」还是「系统坏了」——这是最伤的可用性缺陷。

🔴 判定权红线靠**结构**保证，不靠"小心"：

1. 本模块的公开函数**全是纯函数**：只接收 frozen dataclass / 基本值快照，只返回映射；
   **不持有任何可变权威对象**（不收 Obligation / ObligationSet / ClosureValidationResult）。
   故它在结构上**没有能力**改写 closure_status / satisfaction_status / allow_stop。
2. 调用点在 `validate_building_closure` 里排在 `summarize()` 与 `allow_stop` 之后。
3. `compute_allow_stop_and_reason()` 的签名不含任何归因参数。
4. 输入只来自 FactPack / RuleSlice 派生的槽池；**不 import `eval`**（blind 红线）。

缺能力快照时归 `attribution_input_missing` 并计数报警。
🔴 缺依据时一律 `system_unresolved`，**绝不默认成「需要你提供」**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple

from ..contracts import UnknownAttribution, UnknownScopeRelation
from ..rulecard_assets import DEFAULT_AUTHORITATIVE_BUNDLE_PATH
from .component_lattice import _card_component_values, canonical_hash

# 归因策略版本（写进每条 UnknownAttribution.policy_version，供跨批对账）。
# v3：验证器已产出的原因码优先于结构兜底；卡级触发器 blocked 单列
# `upstream_trigger_blocked`（与真·`missing_rule_edge` 分流）。
UNKNOWN_ATTRIBUTION_POLICY_VERSION = "unknown_attribution_v3"

# 权威责任登记表（完整版；不进卡包 manifest，避免契约校验射程）。
DEFAULT_RESPONSIBILITY_REGISTRY_PATH = (
    DEFAULT_AUTHORITATIVE_BUNDLE_PATH.parent / "responsibility_registry_v1.json"
)

# 投影别名表——运行时 `canonical_slot` 归一的**唯一真源**。责任表按卡侧键书写，
# 扁平化时要照这张表把责任/行动说明复制到归一名上（见 `_load_projection_slot_aliases`）。
_PROJECTION_RUNTIME_MAPPING_PATH = (
    DEFAULT_AUTHORITATIVE_BUNDLE_PATH.parent / "projection_runtime_mapping_v1.json"
)

# 🔴 允许标成「需要专业人员提供」的封闭白名单（用户复核拍板，55/4）。
# 闸的牙齿：登记表里任何 professional 槽必须 ⊆ 本集合，且本集合每个槽都必须
# 在表里标为 professional——扩表白名单必须同步改本常量 + 过审核。
APPROVED_PROFESSIONAL_INPUT_SLOTS: FrozenSet[str] = frozenset(
    {
        "scope.component.covered_by_large_attached_signboard",
        "procedure.investigation.proposal.refused_by_ba",
        "procedure.person.decides_to_proceed_with_investigation",
        "procedure.person.informed_of_ba_refusal",
    }
)

# 卡侧槽名 → 运行时 `canonical_slot` 会归一到的别名。登记表按卡侧键书写；
# 扁平映射时把责任/行动说明**复制**到别名键，否则归因层用归一名查找会永远落空。
#
# 🔴 2026-07-29 改为**从投影别名表派生**，不再硬编码（本函数是唯一真源读取点）。
#
# 原实现硬编码了一条 `covered_by_large_attached_signboard →
# covered_by_large_signboard`，而这条别名**当天已从投影表删除**
# （目标槽世界侧 0 条事实，是死桥；见该表 `_note_deleted_large_signboard_alias`）
# ——代码把一个已裁定删掉的名字搬了回来，且**两表之间没有任何东西在对账**。
# 但把它简单清空同样是错的：登记表 59 个键里约 10 个（`repair.prescribed.*` /
# `reporting.record.maintained` / `scope.component.inspection_*` 等）在投影表里
# **确有活别名**，清空会让它们归一后查不到。
#
# ⇒ 唯一不漂移的解法：**读投影表**。它增删别名，本表自动跟随。
def _load_projection_slot_aliases() -> Mapping[str, Tuple[str, ...]]:
    """读投影别名表的 `slot_aliases`（键以 `_` 开头的是注记，跳过）。

    读不到时返回空表并**静默降级**——责任归因是旁路，缺别名只会让个别槽
    回落到 `system_unresolved`（保守方向），绝不能因此拖垮整条归因或判定。
    """
    try:
        doc = json.loads(
            _PROJECTION_RUNTIME_MAPPING_PATH.read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001 —— 旁路，缺文件不得影响判定
        return {}
    out: Dict[str, Tuple[str, ...]] = {}
    for src, targets in (doc.get("slot_aliases") or {}).items():
        if src.startswith("_"):
            continue
        vals = targets if isinstance(targets, list) else [targets]
        vals = tuple(str(v) for v in vals if isinstance(v, str))
        if vals:
            out[src] = vals
    return out


_RESPONSIBILITY_SLOT_RUNTIME_ALIASES: Mapping[str, Tuple[str, ...]] = (
    _load_projection_slot_aliases()
)
_RUNTIME_ALIAS_TO_REGISTRY_KEY: Mapping[str, str] = {
    alias: src
    for src, aliases in _RESPONSIBILITY_SLOT_RUNTIME_ALIASES.items()
    for alias in aliases
}

__all__ = [
    "UNKNOWN_ATTRIBUTION_POLICY_VERSION",
    "DEFAULT_RESPONSIBILITY_REGISTRY_PATH",
    "APPROVED_PROFESSIONAL_INPUT_SLOTS",
    "ResponsibilityRegistryError",
    "UnknownObligationSnapshot",
    "ScopeRelationPolicySnapshot",
    "SuppliedSlotPools",
    "build_card_component_type_key_map",
    "build_fragment_component_type_map",
    "build_scope_relation_policy",
    "unavailable_scope_relation_policy",
    "classify_scope_relation",
    "attach_scope_relations",
    "attach_unavailable_scope_relations",
    "build_supplied_slot_pools",
    "build_slot_ref_bindings",
    "build_slot_ref_qualifiers",
    "build_unknown_snapshots",
    "validate_responsibility_registry",
    "load_responsibility_registry",
    "flat_responsibility_maps",
    "attribute_unknown_obligations",
    "fallback_attribution",
    "summarize_attribution",
]


class ResponsibilityRegistryError(ValueError):
    """责任登记表不合法（缺字段 / 越权标 professional / 白名单失配）。"""


# ===================================================================== #
# 一、不可变输入快照
# ===================================================================== #
QualifierSet = FrozenSet[Tuple[str, str]]


@dataclass(frozen=True)
class UnknownObligationSnapshot:
    """单条 unknown 义务的**基本值快照**（frozen；不含任何权威对象引用）。"""

    obligation_id: str
    closure_status: str
    fragment_id: Optional[str]
    canonical_slot_ids: Tuple[str, ...]
    declared_qualifiers: QualifierSet
    trigger_dependency_ids: Tuple[str, ...]
    depends_on_open_trigger: bool
    kind: str
    action: Optional[str]
    # 义务是否绑定了**任何** slot 句柄（`slot_ids` 或 `slot_ref_ids` 非空）。
    # 判据 `no_slot_declared` / `non_slot_handle` 完全建立在结构事实上，
    # 不看槽名前缀、不猜字符串。
    has_slot_handle: bool = True
    # 是否来自义务图节点行（`obligation_node_id` 非空）。与 `has_slot_handle` 合取
    # 决定拆码：有节点 → `no_slot_declared`；无节点 → `non_slot_handle`。
    has_obligation_node: bool = False
    # 该义务携带的**非 slot** 事实句柄字段名（artifact_ids / measure_keys / ...），
    # 只用于把 explanation 写准（"它只带了 artifact 句柄"），不参与判据。
    other_fact_handles: Tuple[str, ...] = ()
    # 逐槽卡侧限定符：(canonical_slot, QualifierSet)。多 slot_ref 时**分别**比较，
    # 禁止并成一个集合再拿去逐槽比对（并集会制造假阳 qualifier_mismatch）。
    # 空元组 = 无逐槽信息（旧调用面只给了并集）→ 比对回退到 declared_qualifiers。
    declared_qualifiers_by_slot: Tuple[Tuple[str, QualifierSet], ...] = ()
    # 验证器原始原因码的基本值拷贝（`open_reason_code or blocked_reason_code`）。
    # **带缺省的可选字段**：老调用面不传时行为与改动前完全一致（兜底分支仍全落报警桶）。
    validator_reason_code: Optional[str] = None
    # 义务上的 `trigger_state` 基本值拷贝。用于把「卡级触发器聚合 blocked」
    # 从 `missing_rule_edge` 中分出 `upstream_trigger_blocked`（不读 notes）。
    trigger_state: str = "not_evaluated"
    # Orthogonal scope-relation inputs; basic values only.
    card_component_type_keys: Tuple[str, ...] = ()
    fragment_component_type: Optional[str] = None


@dataclass(frozen=True)
class ScopeRelationPolicySnapshot:
    """Frozen relation inputs copied from this run's RuleSlice product."""

    leaf_types: FrozenSet[str]
    subsumption: Tuple[Tuple[str, Tuple[str, ...]], ...]
    disjoint_pairs: FrozenSet[FrozenSet[str]]
    authorized_targets: Tuple[Tuple[str, str], ...]
    invalid_authorization_card_ids: FrozenSet[str]
    authorization_policy_present: bool
    relation_policy_version: str


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def build_card_component_type_key_map(
    rule_slice: Any,
) -> Mapping[str, Tuple[str, ...]]:
    """Read card component keys through the repository's single ingest helper."""
    out: Dict[str, Tuple[str, ...]] = {}
    for card in _field(rule_slice, "candidate_rule_cards", ()) or ():
        card_id = str(_field(card, "rule_card_id", "") or "")
        if not card_id:
            continue
        if isinstance(card, Mapping):
            raw_card = dict(card)
        elif hasattr(card, "model_dump"):
            raw_card = card.model_dump(mode="python")
        else:
            continue
        out[card_id] = tuple(sorted(str(v) for v in _card_component_values(raw_card)))
    return out


def build_fragment_component_type_map(
    facts: Iterable[Any],
) -> Mapping[str, Optional[str]]:
    """Read the strict W0 identity channel; duplicate sources stay unavailable."""
    by_fragment: Dict[str, list] = {}
    for fact in facts:
        if _field(fact, "slot_id") != "w0_component_identity":
            continue
        provenance = _field(fact, "provenance", {}) or {}
        if _field(provenance, "channel") != "w0_component_identity":
            continue
        qualifiers = _field(fact, "qualifiers", {}) or {}
        fragment_id = _field(qualifiers, "fragment_id")
        if not isinstance(fragment_id, str) or not fragment_id:
            continue
        value: Optional[str] = None
        try:
            parsed = json.loads(_field(fact, "value_json", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, str) and parsed:
            value = parsed
        by_fragment.setdefault(fragment_id, []).append(value)
    return {
        fragment_id: values[0] if len(values) == 1 and values[0] else None
        for fragment_id, values in by_fragment.items()
    }


def unavailable_scope_relation_policy() -> ScopeRelationPolicySnapshot:
    return ScopeRelationPolicySnapshot(
        leaf_types=frozenset(),
        subsumption=(),
        disjoint_pairs=frozenset(),
        authorized_targets=(),
        invalid_authorization_card_ids=frozenset(),
        authorization_policy_present=False,
        relation_policy_version=(
            "scope_relation.v1|lattice=unavailable|authorization=unavailable|"
            "bundle=unavailable"
        ),
    )


def build_scope_relation_policy(rule_slice: Any) -> ScopeRelationPolicySnapshot:
    """Freeze relation assets from RuleSlice.retrieval_policy, never from the worktree."""
    policy = _field(rule_slice, "retrieval_policy", {}) or {}
    if not isinstance(policy, Mapping):
        policy = {}
    lattice = policy.get("component_type_lattice") or {}
    if not isinstance(lattice, Mapping):
        lattice = {}
    authorization_present = (
        "exact_fragment_target_authorizations" in policy
        and isinstance(policy.get("exact_fragment_target_authorizations"), Mapping)
    )
    authorization = (
        policy.get("exact_fragment_target_authorizations")
        if authorization_present
        else {}
    )

    leaf_types = frozenset(
        str(value) for value in (lattice.get("leaf_types") or [])
        if isinstance(value, str) and value
    )
    subsumption = tuple(sorted(
        (
            str(parent),
            tuple(sorted(str(member) for member in (members or []) if isinstance(member, str))),
        )
        for parent, members in (lattice.get("subsumption") or {}).items()
        if isinstance(parent, str)
    ))
    disjoint_pairs = frozenset(
        frozenset(str(value) for value in pair)
        for pair in (lattice.get("disjoint_pairs") or [])
        if isinstance(pair, (list, tuple)) and len(set(pair)) == 2
    )

    authorized_targets = []
    invalid_authorizations = set()
    for card_id, entry in authorization.items():
        target = entry.get("target") if isinstance(entry, Mapping) else entry
        if isinstance(target, str) and target:
            authorized_targets.append((str(card_id), target))
        else:
            invalid_authorizations.add(str(card_id))

    if lattice:
        lattice_anchor = str(lattice.get("version") or f"sha256:{canonical_hash(lattice)}")
    else:
        lattice_anchor = "unavailable"
    authorization_version = policy.get("exact_fragment_target_authorizations_version")
    if isinstance(authorization_version, str) and authorization_version:
        authorization_anchor = authorization_version
    elif authorization_present:
        authorization_anchor = f"sha256:{canonical_hash(authorization)}"
    else:
        authorization_anchor = "unavailable"
    bundle_id = str(_field(rule_slice, "rulecard_bundle_id", "") or "unavailable")

    return ScopeRelationPolicySnapshot(
        leaf_types=leaf_types,
        subsumption=subsumption,
        disjoint_pairs=disjoint_pairs,
        authorized_targets=tuple(sorted(authorized_targets)),
        invalid_authorization_card_ids=frozenset(invalid_authorizations),
        authorization_policy_present=authorization_present,
        relation_policy_version=(
            f"scope_relation.v1|lattice={lattice_anchor}|"
            f"authorization={authorization_anchor}|bundle={bundle_id}"
        ),
    )


def _authorization_for(
    card_id: str,
    policy: ScopeRelationPolicySnapshot,
) -> Tuple[str, Optional[str]]:
    if not policy.authorization_policy_present:
        return "effective_authorization_policy_unavailable", None
    if card_id in policy.invalid_authorization_card_ids:
        return "effective_authorization_invalid", None
    target = dict(policy.authorized_targets).get(card_id)
    if target is None:
        return "effective_authorization_absent", None
    return "effective_authorization_present", target


def _subsumes(parent: str, child: str, policy: ScopeRelationPolicySnapshot) -> bool:
    graph = dict(policy.subsumption)
    pending = list(graph.get(parent, ()))
    seen = set()
    while pending:
        node = pending.pop()
        if node == child:
            return True
        if node in seen:
            continue
        seen.add(node)
        pending.extend(graph.get(node, ()))
    return False


def classify_scope_relation(
    snapshot: UnknownObligationSnapshot,
    policy: ScopeRelationPolicySnapshot,
    *,
    rule_card_id: str = "",
) -> UnknownScopeRelation:
    """Classify one relation with conservative, evidence-only precedence."""
    card_keys = tuple(sorted(set(snapshot.card_component_type_keys)))
    fragment_type = snapshot.fragment_component_type
    authorization_status, target = _authorization_for(rule_card_id, policy)

    if not fragment_type:
        relation = "identity_unavailable"
    elif not card_keys:
        relation = "card_unconstrained"
    elif fragment_type in card_keys:
        relation = "same"
    elif any(_subsumes(card_type, fragment_type, policy) for card_type in card_keys):
        relation = "category_compatible"
    elif (
        target is not None
        and len(card_keys) == 1
        and card_keys[0] == target
        and target in policy.leaf_types
        and fragment_type in policy.leaf_types
        and frozenset((target, fragment_type)) in policy.disjoint_pairs
    ):
        relation = "authorized_disjoint"
    else:
        relation = "different_unresolved"

    return UnknownScopeRelation(
        card_component_type_keys=card_keys,
        fragment_component_type=fragment_type,
        relation=relation,
        target_authorization_status=authorization_status,
        relation_policy_version=policy.relation_policy_version,
    )


def attach_scope_relations(
    mapping: Mapping[str, UnknownAttribution],
    snapshots: Sequence[UnknownObligationSnapshot],
    policy: Optional[ScopeRelationPolicySnapshot],
    *,
    rule_card_ids_by_obligation_id: Optional[Mapping[str, str]] = None,
) -> Dict[str, UnknownAttribution]:
    """Attach scope relations without changing any existing attribution field."""
    safe_policy = policy or unavailable_scope_relation_policy()
    by_id = {snapshot.obligation_id: snapshot for snapshot in snapshots}
    card_ids = rule_card_ids_by_obligation_id or {}
    out: Dict[str, UnknownAttribution] = {}
    for obligation_id, attribution in mapping.items():
        snapshot = by_id.get(obligation_id)
        if snapshot is None:
            relation = UnknownScopeRelation(
                card_component_type_keys=(),
                fragment_component_type=None,
                relation="identity_unavailable",
                target_authorization_status="relation_input_unavailable",
                relation_policy_version=safe_policy.relation_policy_version,
            )
        else:
            try:
                relation = classify_scope_relation(
                    snapshot,
                    safe_policy,
                    rule_card_id=str(card_ids.get(obligation_id, "")),
                )
            except Exception:  # noqa: BLE001 - relation side-channel cannot alter causes
                relation = UnknownScopeRelation(
                    card_component_type_keys=snapshot.card_component_type_keys,
                    fragment_component_type=snapshot.fragment_component_type,
                    relation="identity_unavailable",
                    target_authorization_status="relation_input_unavailable",
                    relation_policy_version=safe_policy.relation_policy_version,
                )
        out[obligation_id] = attribution.model_copy(
            update={"scope_relation": relation}
        )
    return out


def attach_unavailable_scope_relations(
    mapping: Mapping[str, UnknownAttribution],
    *,
    relation_policy_version: str,
) -> Dict[str, UnknownAttribution]:
    """Attach a deterministic unavailable relation without using the classifier."""
    relation = UnknownScopeRelation(
        card_component_type_keys=(),
        fragment_component_type=None,
        relation="identity_unavailable",
        target_authorization_status="relation_input_unavailable",
        relation_policy_version=relation_policy_version,
    )
    return {
        obligation_id: attribution.model_copy(
            update={"scope_relation": relation.model_copy(deep=True)}
        )
        for obligation_id, attribution in mapping.items()
    }

@dataclass(frozen=True)
class SuppliedSlotPools:
    """本次 FactPack 的**别名归一后**槽池 + 每槽的限定符组合。

    ⚠️ 第 2/3 条判据必须经别名归一再比——按裸 `slot_id` 比对制造过误判
    （`repair.prescribed.*` 曾被判成本体边界，实际世界各产 150 条）。

    三张表都按 canonical slot 建键，值是该槽下**各条事实的限定符键值对集合**：

    - `qual_all`：楼级读径全量（等价 `FactIndex.slot_index`）。
    - `qual_unscoped`：无 fragment 归属且非 `aggregation == "building"` 的事实
      （fragment 作用域也看得见的那部分，镜像 `validator._fragment_index`）。
    - `qual_by_fragment`：`(fragment_id, slot)` → 该 fragment 自有事实。
    """

    qual_all: Mapping[str, Tuple[QualifierSet, ...]]
    qual_unscoped: Mapping[str, Tuple[QualifierSet, ...]]
    qual_by_fragment: Mapping[Tuple[str, str], Tuple[QualifierSet, ...]]

    @property
    def all_keys(self) -> FrozenSet[str]:
        return frozenset(self.qual_all)

    def scope_options(
        self, fragment_id: Optional[str], slot: str
    ) -> Tuple[QualifierSet, ...]:
        """本义务作用域内该槽的全部限定符组合（空元组 = 该作用域看不到这个槽）。"""
        if not fragment_id:
            return tuple(self.qual_all.get(slot, ()))
        return tuple(self.qual_by_fragment.get((fragment_id, slot), ())) + tuple(
            self.qual_unscoped.get(slot, ())
        )


def _qualifier_pairs(qualifiers: Mapping[str, Any]) -> QualifierSet:
    """限定符 dict → 归一化的 (键, 字符串值) 对集合（跳过内部作用域标记）。"""
    return frozenset(
        (str(k), str(v))
        for k, v in (qualifiers or {}).items()
        if k not in _SCOPE_QUALIFIER_KEYS and v is not None
    )


# 这些键是作用域/来源标记，不是"卡侧要求的限定符"，比对时剔除避免假阳。
_SCOPE_QUALIFIER_KEYS = frozenset({"fragment_id", "aggregation"})

# ===================================================================== #
# 兜底分支窄口径透传：只透传、不重推
# ===================================================================== #
# 验证器原因码透传名单。归因层只读快照上的 `validator_reason_code`（验证器早已算出）
# 按本名单透传成 `cause_code`，**零新判据**；名单外的码仍落报警桶
# `attribution_input_missing`——保住它的报警语义。
# ⚠️ `missing_rule_edge` 在此只承接**非**卡级触发器 blocked 的残留（悬空引用等）；
# 触发器 blocked 已在更前的规则被 `upstream_trigger_blocked` 截走。
_PASSTHROUGH_CAUSE_CODES: FrozenSet[str] = frozenset({
    "binding_requires_adjudication_authorization",
    "observed_false_without_violation_basis",
    "artifact_state_not_valid_evidence",
    "diagnostic_binding_not_valid_evidence",
    # #33 保护闸（2026-08-05）：耦合未证拒判。与上面两码分立——上面两码是
    # 「永久不能确立」，本码是「耦合未证、根治后可解封」。
    "evidence_event_coupling_unproven",
    "missing_rule_edge",
    "ambiguous_fact_binding",
    "missing_artifact_evidence",
    "missing_time_anchor",
    "missing_satisfaction_binding",
    "artifact_not_modeled_upstream",
    "missing_measurement",
    "missing_fact",
    "missing_required_field_group",
    "unit_mismatch",
})

# 透传码 → 给专业审查员的解释主体（四要素：等什么 / 系统查了什么 / 谁动手；
# 「不需要你补录资料」与原因码对照在拼接处统一补上）。
# 🔴 每条文案声称的事实必须对该码 100% 义务为真（常驻测试锁定）。
_PASSTHROUGH_EXPLANATIONS: Dict[str, str] = {
    "binding_requires_adjudication_authorization": (
        "系统已取得相关读数，但该义务绑定尚未获得消费此类读数下判定的裁定授权，"
        "程序按保守原则不给结论。**这是有意设计，不是漏查**。"
        "要由维护方完成该绑定的逐绑定裁定后解锁。"
    ),
    "observed_false_without_violation_basis": (
        "系统已取得完整的楼级聚合读数，其值表明正向条件尚未成立；"
        "当前没有足够的期限或终局违约依据，程序不判违反。"
        "要由专业审查员复核处置进度。"
    ),
    "artifact_state_not_valid_evidence": (
        "系统查到了相关文件齐备的记录，但「文件在」不能证明这条义务已履行，"
        "系统按保守原则不给结论。**这是有意设计，不是漏查**。"
        "要由维护方为该义务接上正确的证据通道。"
    ),
    "diagnostic_binding_not_valid_evidence": (
        "系统已取得相关读数，但该义务与这类读数的**精确绑定**已经逐项对法规原文裁定为"
        "「此类读数不能确立本义务」，程序按保守原则不据其下判定。**这是有意设计，不是漏查**。"
        "要由维护方为该义务改接能确立义务的证据通道；改接后须重新裁定。"
    ),
    # #33 保护闸（2026-08-05）。⚠️ 本码覆盖真假两侧（诊断行两出口必须同码），
    # 故解释里**不许**出现「系统查到了该文件已呈交」这类只对真值侧为真的断言，
    # 否则会破「文案声称的事实须对该码 100% 义务为真」这条常驻测试锁定的不变量。
    "evidence_event_coupling_unproven": (
        "本条的判定依据是「相关文件已呈交／送达／签署」这一状态读数；系统尚未确立"
        "「记录到该状态即代表该事件确已发生」这条关联，故不据其判定义务已履行。"
        "**这是有意设计，不是漏查**——世界侧该状态与实际程序事件之间目前是独立采样。"
        "要由专业审查员核实该呈交／送达／签署事件是否真实发生；"
        "维护方补上该关联后，本条可恢复正常判定。"
    ),
    "missing_rule_edge": (
        "验证器报规则边或引用缺失（非卡级触发器堵死）。"
        "属规则图/派生接线缺口，要由维护方修。"
    ),
    "ambiguous_fact_binding": (
        "候选事实多于一条，系统拒绝任取其一下结论（避免误判）。"
        "要由维护方收紧限定符或绑定规则，消歧后再判。"
    ),
    "missing_artifact_evidence": (
        "本条要求以某文件为证据，系统查了本次事实包，其中没有该文件的记录。"
        "要由维护方核查是世界侧未供给还是取证通道未接上。"
    ),
    "missing_time_anchor": (
        "缺期限锚点，系统无法核验该期限是否满足。"
        "要由维护方核查期限锚点的供给或接线。"
    ),
    "missing_satisfaction_binding": (
        "验证器判定本条缺少满足通道绑定，无法沿事实槽核验是否已履行。"
        "要由维护方为该义务节点补上正确的事实槽绑定。"
    ),
    "artifact_not_modeled_upstream": (
        "本条依赖的产物键未在上游世界模型中建模，系统无法消歧。"
        "要由维护方补产物建模或接线。"
    ),
    "missing_measurement": (
        "缺量测值，系统无法核验阈值或比较条件。"
        "要由维护方核查量测供给或接线。"
    ),
    "missing_fact": (
        "系统在本次事实包中查不到本条所需的事实。"
        "要由维护方核查是世界侧未供给还是取数通道未接上。"
    ),
    "missing_required_field_group": (
        "缺必填字段组，系统无法完成核验。"
        "要由维护方核查字段组供给或接线。"
    ),
    "unit_mismatch": (
        "单位不一致，系统拒绝进行比较以免误判。"
        "要由维护方对齐单位后再判。"
    ),
}

# 非 slot 的事实句柄字段（Obligation 上真实存在的字段名）。只用于把 explanation
# 写准——告诉专业人员这条义务到底带了什么、没带什么，不参与任何判据。
_OTHER_FACT_HANDLE_FIELDS = (
    "measure_keys",
    "artifact_ids",
    "artifact_keys",
    "time_anchor_keys",
    "deadline_ids",
    "evidence_fact_ids",
    "evidence_node_refs",
)

# 句柄字段名 → 给专业人员看的中文名（explanation 用）。
_HANDLE_LABELS = {
    "measure_keys": "量表",
    "artifact_ids": "文件/表格",
    "artifact_keys": "文件/表格",
    "time_anchor_keys": "时间锚点",
    "deadline_ids": "期限",
    "evidence_fact_ids": "证据事实",
    "evidence_node_refs": "证据节点",
}


def build_supplied_slot_pools(
    facts: Iterable[Any],
    *,
    canonical_slot: Callable[[str], str],
    fragment_of_fact: Callable[[Any], Optional[str]],
) -> SuppliedSlotPools:
    """从 FactPack.facts 建槽池（只读；`canonical_slot` 由 FactIndex 提供，含别名表）。"""
    qual_all: Dict[str, list] = {}
    qual_unscoped: Dict[str, list] = {}
    qual_by_fragment: Dict[Tuple[str, str], list] = {}
    for fact in facts:
        slot_id = getattr(fact, "slot_id", None)
        if not slot_id:
            continue
        key = canonical_slot(str(slot_id))
        qualifiers = getattr(fact, "qualifiers", None) or {}
        pairs = _qualifier_pairs(qualifiers)
        qual_all.setdefault(key, []).append(pairs)
        # 楼级聚合读数不暴露给 fragment 作用域（镜像 _fragment_index）。
        if qualifiers.get("aggregation") == "building":
            continue
        frag = fragment_of_fact(fact)
        if frag:
            qual_by_fragment.setdefault((str(frag), key), []).append(pairs)
        else:
            qual_unscoped.setdefault(key, []).append(pairs)
    return SuppliedSlotPools(
        qual_all={k: tuple(v) for k, v in qual_all.items()},
        qual_unscoped={k: tuple(v) for k, v in qual_unscoped.items()},
        qual_by_fragment={k: tuple(v) for k, v in qual_by_fragment.items()},
    )


def build_slot_ref_bindings(
    rule_slice: Any,
) -> Mapping[Tuple[str, str], Tuple[Optional[str], QualifierSet]]:
    """从 RuleSlice 的 `slot_role_map` 建 (rule_card_id, slot_ref_id) → (slot_id, 限定符)。

    ⚠️ 卡包 `slot_role_map` 用复数 `roles`；限定符在 `qualifiers` 下。
    `slot_id` 可能为 None（缺字段的畸形项）——调用方须容忍。
    """
    out: Dict[Tuple[str, str], Tuple[Optional[str], QualifierSet]] = {}
    for card in getattr(rule_slice, "candidate_rule_cards", None) or []:
        card_id = str(getattr(card, "rule_card_id", "") or "")
        for ref in getattr(card, "slot_role_map", None) or []:
            if isinstance(ref, dict):
                ref_id = ref.get("slot_ref_id")
                slot_id = ref.get("slot_id")
                quals = ref.get("qualifiers")
            else:
                ref_id = getattr(ref, "slot_ref_id", None)
                slot_id = getattr(ref, "slot_id", None)
                quals = getattr(ref, "qualifiers", None)
            if not ref_id:
                continue
            out[(card_id, str(ref_id))] = (
                str(slot_id) if slot_id else None,
                _qualifier_pairs(quals or {}),
            )
    return out


def build_slot_ref_qualifiers(rule_slice: Any) -> Mapping[Tuple[str, str], QualifierSet]:
    """兼容壳：只返回限定符。新代码请用 `build_slot_ref_bindings`（带 slot_id）。"""
    return {k: v[1] for k, v in build_slot_ref_bindings(rule_slice).items()}


def build_unknown_snapshots(
    obligations: Sequence[Any],
    *,
    canonical_slot: Callable[[str], str],
    qualifiers_by_slot_ref: Optional[Mapping[Tuple[str, str], QualifierSet]] = None,
    slot_ref_bindings: Optional[
        Mapping[Tuple[str, str], Tuple[Optional[str], QualifierSet]]
    ] = None,
    card_component_type_keys_by_rule_card_id: Optional[
        Mapping[str, Tuple[str, ...]]
    ] = None,
    fragment_component_type_by_fragment_id: Optional[
        Mapping[str, Optional[str]]
    ] = None,
) -> Tuple[
    Tuple[UnknownObligationSnapshot, ...],
    Mapping[str, str],
    Mapping[str, Tuple[str, ...]],
]:
    """把义务列表投影成 (unknown 快照元组, 全量 closure_status 映射, 全量依赖映射)。

    返回的三样**全是基本值**——归因函数拿不到 Obligation 对象，故结构上改不了判定。
    `closure_status` / `trigger_dependency_ids` 全量给（不只 unknown 的），因为继承型
    归因要沿依赖链追到根。

    限定符输入优先 `slot_ref_bindings`（含 slot_id，可逐槽比较）；若只给了旧的
    `qualifiers_by_slot_ref`，则只能得到并集（无逐槽信息）。
    """
    snapshots = []
    status_by_id: Dict[str, str] = {}
    deps_by_id: Dict[str, Tuple[str, ...]] = {}
    if slot_ref_bindings is None and qualifiers_by_slot_ref is not None:
        slot_ref_bindings = {
            k: (None, v) for k, v in qualifiers_by_slot_ref.items()
        }
    bindings = slot_ref_bindings or {}
    card_component_types = card_component_type_keys_by_rule_card_id or {}
    fragment_component_types = fragment_component_type_by_fragment_id or {}
    for obl in obligations:
        oid = str(obl.obligation_id)
        status_by_id[oid] = str(obl.closure_status)
        deps_by_id[oid] = tuple(str(d) for d in (obl.trigger_dependency_ids or []))
        if obl.satisfaction_status != "unknown":
            continue
        declared: set = set()
        by_slot: Dict[str, set] = {}
        card_id = str(obl.source_rule_card_id or "")
        for ref_id in obl.slot_ref_ids or []:
            binding = bindings.get((card_id, str(ref_id)))
            if binding is None:
                continue
            sid, quals = binding
            declared |= set(quals)
            if sid:
                by_slot.setdefault(canonical_slot(str(sid)), set()).update(quals)
        others = tuple(
            f for f in _OTHER_FACT_HANDLE_FIELDS if getattr(obl, f, None)
        )
        snapshots.append(
            UnknownObligationSnapshot(
                obligation_id=oid,
                closure_status=str(obl.closure_status),
                fragment_id=str(obl.fragment_id) if obl.fragment_id else None,
                canonical_slot_ids=tuple(
                    canonical_slot(str(s)) for s in (obl.slot_ids or []) if s
                ),
                declared_qualifiers=frozenset(declared),
                trigger_dependency_ids=deps_by_id[oid],
                depends_on_open_trigger=bool(obl.depends_on_open_trigger),
                kind=str(obl.kind),
                action=str(obl.action) if obl.action else None,
                has_slot_handle=bool(obl.slot_ids) or bool(obl.slot_ref_ids),
                has_obligation_node=bool(getattr(obl, "obligation_node_id", None)),
                other_fact_handles=others,
                declared_qualifiers_by_slot=tuple(
                    (s, frozenset(q)) for s, q in sorted(by_slot.items())
                ),
                # 验证器早已算出原因码；这里只做基本值拷贝（open 必有 open 码、
                # blocked 必有 blocked 码，契约 model_validator 保证），归因层不重推。
                validator_reason_code=(
                    str(obl.open_reason_code or obl.blocked_reason_code)
                    if (obl.open_reason_code or obl.blocked_reason_code)
                    else None
                ),
                trigger_state=str(
                    getattr(obl, "trigger_state", None) or "not_evaluated"
                ),
                card_component_type_keys=tuple(
                    card_component_types.get(card_id, ())
                ),
                fragment_component_type=(
                    fragment_component_types.get(str(obl.fragment_id))
                    if obl.fragment_id
                    else None
                ),
            )
        )
    return tuple(snapshots), status_by_id, deps_by_id


# ===================================================================== #
# 一½、责任登记表（权威数据 → 扁平映射）
# ===================================================================== #
_VALID_RESPONSIBILITIES = frozenset(
    {"professional_input_required", "system_unresolved"}
)


def validate_responsibility_registry(doc: Mapping[str, Any]) -> None:
    """校验完整版责任登记表；失败抛 `ResponsibilityRegistryError`。

    🔴 核心闸：`professional_input_required` 槽集合必须**恰好等于**
    `APPROVED_PROFESSIONAL_INPUT_SLOTS`——把某个 `system_unresolved` 改成
    professional 会被本闸拦住（§0.3 纪律的牙齿）。
    """
    slots = doc.get("slots")
    if not isinstance(slots, dict) or not slots:
        raise ResponsibilityRegistryError("responsibility_registry.slots 必须是非空对象")
    professional: set = set()
    for slot_id, item in slots.items():
        if not isinstance(slot_id, str) or not slot_id:
            raise ResponsibilityRegistryError(f"非法 slot_id: {slot_id!r}")
        if not isinstance(item, dict):
            raise ResponsibilityRegistryError(f"slots[{slot_id}] 必须是对象")
        resp = item.get("responsibility")
        if resp not in _VALID_RESPONSIBILITIES:
            raise ResponsibilityRegistryError(
                f"slots[{slot_id}].responsibility 非法: {resp!r}"
            )
        if "reason" not in item or "professional_action" not in item:
            raise ResponsibilityRegistryError(
                f"slots[{slot_id}] 缺 reason 或 professional_action"
            )
        if resp == "professional_input_required":
            action = item.get("professional_action") or ""
            if not str(action).strip():
                raise ResponsibilityRegistryError(
                    f"slots[{slot_id}] 标为 professional_input_required "
                    "但 professional_action 为空"
                )
            professional.add(slot_id)
    approved = set(APPROVED_PROFESSIONAL_INPUT_SLOTS)
    extra = professional - approved
    missing = approved - professional
    if extra or missing:
        raise ResponsibilityRegistryError(
            "professional_input_required 槽集合必须恰好等于白名单；"
            f"越权={sorted(extra)} 缺失={sorted(missing)}"
        )


def flat_responsibility_maps(
    doc: Mapping[str, Any],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """完整版 → (`{slot: responsibility}`, `{slot: professional_action}`)。

    行动说明映射只收录非空字符串（system 槽通常为空串）。
    另：把 `_RESPONSIBILITY_SLOT_RUNTIME_ALIASES` 里的运行时别名键一并展开，
    与归因层 `canonical_slot` 对齐。
    """
    validate_responsibility_registry(doc)
    resp_map: Dict[str, str] = {}
    action_map: Dict[str, str] = {}
    for slot_id, item in doc["slots"].items():
        resp = str(item["responsibility"])
        resp_map[slot_id] = resp
        action = str(item.get("professional_action") or "").strip()
        if action:
            action_map[slot_id] = action
        for alias in _RESPONSIBILITY_SLOT_RUNTIME_ALIASES.get(slot_id, ()):
            resp_map[alias] = resp
            if action:
                action_map[alias] = action
    return resp_map, action_map


def load_responsibility_registry(
    path: Optional[Path] = None,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    """读磁盘权威表 → (责任扁平表, 行动说明表, 完整文档)。

    默认路径：卡包目录下的 `responsibility_registry_v1.json`（**未**登记进
    manifest，不进 `validate_rulecard_bundle` 射程）。
    """
    reg_path = Path(path) if path is not None else DEFAULT_RESPONSIBILITY_REGISTRY_PATH
    doc = json.loads(reg_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ResponsibilityRegistryError("责任登记表根必须是对象")
    resp_map, action_map = flat_responsibility_maps(doc)
    return resp_map, action_map, doc


# ===================================================================== #
# 二、纯归因函数
# ===================================================================== #
def _resolve_roots(
    obligation_id: str,
    deps_by_id: Mapping[str, Tuple[str, ...]],
    status_by_id: Mapping[str, str],
    *,
    max_depth: int = 64,
) -> Tuple[str, ...]:
    """沿 `trigger_dependency_ids` 追到**未闭合的根**（自身无未闭合上游者）。

    带 visited 环保护与深度上限；找不到任何未闭合上游 → 返回空元组（不算继承型）。
    """
    roots: list = []
    seen = {obligation_id}
    frontier = [d for d in deps_by_id.get(obligation_id, ())]
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        nxt: list = []
        for dep in frontier:
            if dep in seen:
                continue
            seen.add(dep)
            dep_status = status_by_id.get(dep)
            if dep_status is not None and dep_status == "closed":
                continue
            upstream = [u for u in deps_by_id.get(dep, ()) if u not in seen]
            # 未登记的依赖（回填兜底残留的 condition_id）也算根——它就是链条尽头。
            unclosed_upstream = [
                u for u in upstream if status_by_id.get(u, "open") != "closed"
            ]
            if unclosed_upstream:
                nxt.extend(unclosed_upstream)
            else:
                roots.append(dep)
        frontier = nxt
    return tuple(sorted(set(roots)))


def attribute_unknown_obligations(
    snapshots: Sequence[UnknownObligationSnapshot],
    *,
    closure_status_by_obligation_id: Mapping[str, str],
    dependency_ids_by_obligation_id: Mapping[str, Tuple[str, ...]],
    supplied_slot_pools: Optional[SuppliedSlotPools],
    responsibility_registry: Optional[Mapping[str, str]] = None,
    professional_action_by_slot: Optional[Mapping[str, str]] = None,
    policy_version: str = UNKNOWN_ATTRIBUTION_POLICY_VERSION,
) -> Dict[str, UnknownAttribution]:
    """纯归因：unknown 快照 → {obligation_id: UnknownAttribution}。

    判据优先级（本阶段只用**结构上可靠**的信号）：

    1. `depends_on_open_trigger` 为真且能追到未闭合根 → `inherited_from_root`
       （⚠️ 仅看该旗标，不看 `trigger_dependency_ids` 是否非空——派生器无条件复制
       依赖 id 作溯源，触发器已闭合时字段里照样留着；沿所有依赖追根会覆盖真实归因）。
    2. `trigger_state == "blocked"` → `upstream_trigger_blocked`
       （卡级触发器堵死，下游从未进入满足通道；与真·`missing_rule_edge` 分流）。
    3. 义务自身无事实槽句柄时：
       - 有验证器原因码且在透传名单 → **优先透传**（不再被结构兜底盖住）
       - 两码皆空 → 按是否义务图节点拆 `no_slot_declared` / `non_slot_handle`
       - 有码但不在名单 → `attribution_input_missing`（报警）
    4. 槽名经别名归一后在世界里**有**、但本作用域取不到 → `qualifier_mismatch`。
    5. 归一后槽池里**不存在** → `slot_not_supplied`。
    6. 判据全落空 → 兜底透传名单内验证器码；否则 `attribution_input_missing`。

    🔴 `responsibility_registry` 为 None / 空时，**全部**归 `system_unresolved`；
    缺槽池（能力快照缺失）时**整批**归 `attribution_input_missing`（无槽句柄路径
    已在第 3 步处理完），绝不默认成「需要你提供」。
    `professional_action_by_slot` 只在责任命中 professional 时写入归因对象。
    """
    out: Dict[str, UnknownAttribution] = {}
    registry_present = bool(responsibility_registry)
    action_by_slot = professional_action_by_slot or {}

    def _lookup_responsibility(
        slot_keys: Tuple[str, ...],
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """返回 (responsibility, responsible_slot_id, professional_action)。

        责任清单缺失 ⇒ 一律 system_unresolved（不猜"该你填"）。
        多槽时：**任一**槽登记为 professional → 整条归 professional
        （否则先扫到的 system 槽会把真·专业输入压掉）。
        """
        if not registry_present:
            return "system_unresolved", None, None
        professional_hit: Optional[str] = None
        system_hit: Optional[str] = None
        for key in slot_keys:
            claimed = (responsibility_registry or {}).get(key)
            if claimed == "professional_input_required" and professional_hit is None:
                professional_hit = key
            elif claimed == "system_unresolved" and system_hit is None:
                system_hit = key
        if professional_hit is not None:
            # 报告聚合用登记表主键（卡侧名），不用运行时别名。
            report_slot = _RUNTIME_ALIAS_TO_REGISTRY_KEY.get(
                professional_hit, professional_hit
            )
            return (
                "professional_input_required",
                report_slot,
                action_by_slot.get(professional_hit)
                or action_by_slot.get(report_slot)
                or None,
            )
        if system_hit is not None:
            report_slot = _RUNTIME_ALIAS_TO_REGISTRY_KEY.get(system_hit, system_hit)
            return "system_unresolved", report_slot, None
        return "system_unresolved", None, None

    def _passthrough(oid: str, snap: UnknownObligationSnapshot, reason_code: str) -> UnknownAttribution:
        return UnknownAttribution(
            obligation_id=oid,
            responsibility="system_unresolved",
            cause_code=reason_code,  # type: ignore[arg-type] —— 名单 ⊆ UnknownCauseCode
            explanation=(
                f"这条义务（{snap.kind}"
                + (f" / {snap.action}" if snap.action else "")
                + f"）{_PASSTHROUGH_EXPLANATIONS[reason_code]}"
                + f"验证器原因码：`{reason_code}`。"
                + "**不需要你补录资料** —— 这是系统侧缺口，已记录待维护方跟进。"
            ),
            root_dependency_ids=[],
            policy_version=policy_version,
            validator_reason_code=reason_code,
        )

    def _structural_no_slot(oid: str, snap: UnknownObligationSnapshot) -> UnknownAttribution:
        kind_action = (
            f"这条义务（{snap.kind}"
            + (f" / {snap.action}" if snap.action else "")
            + "）"
        )
        if snap.other_fact_handles:
            carried = "、".join(
                dict.fromkeys(
                    _HANDLE_LABELS.get(h, h) for h in snap.other_fact_handles
                )
            )
            handle_detail = f"它携带的是{carried}句柄（非事实槽）。"
        else:
            handle_detail = (
                "它没有任何可核验的事实依据——连量表、文件、期限句柄都没有。"
            )
        if snap.has_obligation_node:
            return UnknownAttribution(
                obligation_id=oid,
                responsibility="system_unresolved",
                cause_code="no_slot_declared",
                explanation=(
                    kind_action
                    + "是义务图节点行，但生成时没有绑定任何事实槽，"
                    "且验证器未给出更具体的原因码，"
                    "系统因此无法针对它查任何事实。"
                    + handle_detail
                    + "**不需要你补录资料** —— 这是系统未接线（缺满足通道），"
                    "要由维护方修派生逻辑。"
                ),
                root_dependency_ids=[],
                policy_version=policy_version,
                validator_reason_code=snap.validator_reason_code,
            )
        return UnknownAttribution(
            obligation_id=oid,
            responsibility="system_unresolved",
            cause_code="non_slot_handle",
            explanation=(
                kind_action
                + "不是义务图节点行，且未绑定任何事实槽，"
                + "且验证器未给出更具体的原因码。"
                + handle_detail
                + "**不是系统漏查了事实槽** —— 这类义务本来就不走"
                "「查事实槽」这条轴。"
                + "**不需要你补录资料** —— 属系统侧分类说明，"
                "要由维护方按非事实槽轴处理。"
            ),
            root_dependency_ids=[],
            policy_version=policy_version,
            validator_reason_code=snap.validator_reason_code,
        )

    for snap in snapshots:
        oid = snap.obligation_id

        # —— 判据 1：继承型（只在 depends_on_open_trigger 时走）——
        if snap.depends_on_open_trigger:
            roots = _resolve_roots(
                oid, dependency_ids_by_obligation_id, closure_status_by_obligation_id
            )
            if roots:
                resp, slot_hit, action = _lookup_responsibility(snap.canonical_slot_ids)
                out[oid] = UnknownAttribution(
                    obligation_id=oid,
                    responsibility=resp,  # type: ignore[arg-type]
                    cause_code="inherited_from_root",
                    explanation=(
                        f"本条因上游触发义务未闭合而阻塞：可追溯的未闭合根依赖 {len(roots)} 条；"
                        "根因解决后本条会自动重算。"
                    ),
                    root_dependency_ids=list(roots),
                    policy_version=policy_version,
                    validator_reason_code=snap.validator_reason_code,
                    responsible_slot_id=slot_hit,
                    professional_action=action,
                )
                continue

        # —— 判据 2：卡级触发器聚合 blocked（乙：与真·missing_rule_edge 分流）——
        # 结构可靠：只看义务权威字段 `trigger_state`，不读 notes、不猜字符串。
        if snap.trigger_state == "blocked":
            out[oid] = UnknownAttribution(
                obligation_id=oid,
                responsibility="system_unresolved",
                cause_code="upstream_trigger_blocked",
                explanation=(
                    f"这条义务（{snap.kind}"
                    + (f" / {snap.action}" if snap.action else "")
                    + "）所在卡的触发条件未能求值（堵死），"
                    "本条因此**从未进入**自身求值。"
                    # 🔴 2026-07-29 收窄（第三方审核）：原文写「不是这条义务本身缺资料 /
                    # 不需要你补录资料」——**这两句从 trigger_state 推不出来**。本条根本
                    # 没求值过，所以无法证明它自身不缺别的东西。只陈述能证的：先解触发器。
                    "在触发器可求值之前，**无法判断本条自身是否还缺别的东西**；"
                    "要由维护方先让卡级触发条件可求值，再回头看本条。"
                ),
                root_dependency_ids=[],
                policy_version=policy_version,
                validator_reason_code=snap.validator_reason_code,
            )
            continue

        # —— 判据 3：无事实槽句柄 —— 验证器码优先于结构兜底 ——
        if not snap.has_slot_handle:
            reason_code = snap.validator_reason_code
            if reason_code in _PASSTHROUGH_CAUSE_CODES:
                out[oid] = _passthrough(oid, snap, reason_code)
            elif reason_code is None:
                out[oid] = _structural_no_slot(oid, snap)
            else:
                out[oid] = UnknownAttribution(
                    obligation_id=oid,
                    responsibility="system_unresolved",
                    cause_code="attribution_input_missing",
                    explanation=(
                        f"未能判别原因：kind={snap.kind}"
                        + (f" / action={snap.action}" if snap.action else "")
                        + f"，验证器原因码 `{reason_code}` 不在归因透传名单内"
                        " —— 归因策略没有覆盖这个形态，属归因层自身的缺口，"
                        "需要维护方跟进。"
                    ),
                    root_dependency_ids=[],
                    policy_version=policy_version,
                    validator_reason_code=reason_code,
                )
            continue

        # —— 缺能力快照（槽池）⇒ 报警，不猜 ——
        if supplied_slot_pools is None:
            out[oid] = UnknownAttribution(
                obligation_id=oid,
                responsibility="system_unresolved",
                cause_code="attribution_input_missing",
                explanation="归因输入缺失：本次运行没有可用的事实槽池快照，无法判别 unknown 的来源。",
                root_dependency_ids=[],
                policy_version=policy_version,
                validator_reason_code=snap.validator_reason_code,
            )
            continue

        # —— 判据 4 / 5：槽池比对（必须经别名归一后再比）——
        # 每槽分三种可判形态：作用域内限定符对得上 / 对不上（含"作用域外有") / 全世界都没有。
        # 🔴 逐槽用该槽自身限定符；无逐槽表时回退到并集（旧调用面）。
        quals_by_slot = dict(snap.declared_qualifiers_by_slot)
        use_union_fallback = not quals_by_slot
        mismatched: list = []      # 数据在，卡侧取不到（限定符或作用域）
        not_supplied: list = []    # 全世界都没这个槽
        all_keys = supplied_slot_pools.all_keys
        for slot in snap.canonical_slot_ids:
            if slot not in all_keys:
                not_supplied.append(slot)
                continue
            options = supplied_slot_pools.scope_options(snap.fragment_id, slot)
            if not options:
                # 世界有、但本作用域看不到 ⇒ 作用域/限定符对不上。
                mismatched.append((slot, ()))
                continue
            demanded = (
                snap.declared_qualifiers
                if use_union_fallback
                else quals_by_slot.get(slot, frozenset())
            )
            if demanded and not any(demanded <= opt for opt in options):
                # 世界在本作用域供了这个槽，但没有一条事实满足该槽要求的全部限定符。
                supplied_values = sorted(
                    {f"{k}={v}" for opt in options for (k, v) in opt}
                )[:4]
                mismatched.append((slot, tuple(supplied_values)))

        if mismatched:
            demanded_show = sorted(f"{k}={v}" for k, v in snap.declared_qualifiers)[:4]
            names = ", ".join(sorted(s for s, _ in mismatched)[:3])
            seen_vals = sorted({v for _, vals in mismatched for v in vals})[:4]
            resp, slot_hit, action = _lookup_responsibility(
                tuple(s for s, _ in mismatched)
            )
            # 责任命中 professional 时不得再说「不需要专业人员补录」。
            if resp == "professional_input_required":
                tail = " —— 按责任登记，需专业人员按行动项补录对应资料。"
            else:
                tail = " —— 属系统侧接线问题，不需要专业人员补录。"
            out[oid] = UnknownAttribution(
                obligation_id=oid,
                responsibility=resp,  # type: ignore[arg-type]
                cause_code="qualifier_mismatch",
                explanation=(
                    f"世界侧有这些槽的数据（{names}），但卡侧取不到"
                    + (f"：卡要求 {demanded_show}" if demanded_show else "（本作用域看不到该槽）")
                    + (f"，世界给的是 {seen_vals}" if seen_vals else "")
                    + tail
                ),
                root_dependency_ids=[],
                policy_version=policy_version,
                validator_reason_code=snap.validator_reason_code,
                responsible_slot_id=slot_hit,
                professional_action=action,
            )
            continue
        if not_supplied:
            resp, slot_hit, action = _lookup_responsibility(tuple(not_supplied))
            out[oid] = UnknownAttribution(
                obligation_id=oid,
                responsibility=resp,  # type: ignore[arg-type]
                cause_code="slot_not_supplied",
                explanation=(
                    f"本次事实包里完全没有这些槽（{', '.join(sorted(not_supplied)[:3])}）"
                    " —— 世界侧未供给。"
                ),
                root_dependency_ids=[],
                policy_version=policy_version,
                validator_reason_code=snap.validator_reason_code,
                responsible_slot_id=slot_hit,
                professional_action=action,
            )
            continue

        # —— 判据 6：兜底 —— 透传名单内的验证器码直接透传；否则报警 ——
        reason_code = snap.validator_reason_code
        if reason_code in _PASSTHROUGH_CAUSE_CODES:
            out[oid] = _passthrough(oid, snap, reason_code)
            continue

        out[oid] = UnknownAttribution(
            obligation_id=oid,
            responsibility="system_unresolved",
            cause_code="attribution_input_missing",
            explanation=(
                f"未能判别原因：kind={snap.kind}"
                + (f" / action={snap.action}" if snap.action else "")
                + (
                    f"，验证器原因码 `{reason_code}` 不在归因透传名单内"
                    if reason_code
                    else "，无未闭合上游、已声明的槽在作用域内限定符也对得上"
                )
                + " —— "
                "归因策略没有覆盖这个形态，属归因层自身的缺口，需要维护方跟进。"
            ),
            root_dependency_ids=[],
            policy_version=policy_version,
            validator_reason_code=reason_code,
        )
    return out


def fallback_attribution(
    obligation_ids: Iterable[str],
    *,
    reason: str,
    policy_version: str = UNKNOWN_ATTRIBUTION_POLICY_VERSION,
) -> Dict[str, UnknownAttribution]:
    """兜底归因：整批落 `system_unresolved / attribution_input_missing` 并写明原因。

    用于归因策略抛异常 / 返回残缺映射时补齐——**不许**退成「需要你提供」。
    """
    return {
        oid: UnknownAttribution(
            obligation_id=oid,
            responsibility="system_unresolved",
            cause_code="attribution_input_missing",
            explanation=f"归因未产出，按报警兜底处理：{reason}",
            root_dependency_ids=[],
            policy_version=policy_version,
        )
        for oid in obligation_ids
    }


def summarize_attribution(
    mapping: Mapping[str, UnknownAttribution]
) -> Dict[str, Any]:
    """归因审计摘要（写进 machine_readable_report，只作 provenance）。"""
    cause_counts: Dict[str, int] = {}
    resp_counts: Dict[str, int] = {}
    scope_relation_counts: Dict[str, int] = {}
    scope_relation_missing_count = 0
    for attr in mapping.values():
        cause_counts[attr.cause_code] = cause_counts.get(attr.cause_code, 0) + 1
        resp_counts[attr.responsibility] = resp_counts.get(attr.responsibility, 0) + 1
        if attr.scope_relation is None:
            scope_relation_missing_count += 1
        else:
            relation = attr.scope_relation.relation
            scope_relation_counts[relation] = scope_relation_counts.get(relation, 0) + 1
    return {
        "policy_version": UNKNOWN_ATTRIBUTION_POLICY_VERSION,
        "total_unknown": len(mapping),
        "cause_code_counts": dict(sorted(cause_counts.items())),
        "responsibility_counts": dict(sorted(resp_counts.items())),
        "scope_relation_counts": dict(sorted(scope_relation_counts.items())),
        "scope_relation_missing_count": scope_relation_missing_count,
        "scope_relation_conservation_passed": (
            sum(scope_relation_counts.values()) == len(mapping)
            and scope_relation_missing_count == 0
        ),
        # 报警：落到兜底桶的条数（缺责任清单 / 缺能力快照 / 判据全落空）。
        "attribution_input_missing_alarm": cause_counts.get(
            "attribution_input_missing", 0
        ),
    }
