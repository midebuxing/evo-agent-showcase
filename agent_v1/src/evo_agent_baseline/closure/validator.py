"""闭包验证器主入口 —— spec §6.6 / §6.5 / §6.7。

- `validate_building_closure(rule_slice, fact_pack, config)` —— §6.6 主入口。
- `sort_and_dedupe_obligations` —— §6.6.1。
- `find_high_risk_items` —— §6.6.2。
- `build_machine_report` —— §6.6.3。
- allow_stop / stop_reason / report gate —— §6.5。
- obligation_id deterministic key —— §6.7。
- assert_no_forbidden_sources —— §6.1 forbidden input 守卫。

确定性、无 LLM、无 Neo4j：输入纯 DTO，纯 Python。
IT-004：同一输入重复运行 obligation_set.json byte-identical。

evo-agent v1 §6.2 provenance instrumentation：在 ClosureValidationResult.
machine_readable_report 内加 4 个 v1 字段（skill_invocation_ids /
candidate_universe_hash / fact_pack_hash / rule_slice_hash），不改变 verifier
判定逻辑、不改 allow_stop 规则（spec v1 §6.3 Skill/Policy 不影响 verifier
authority 不变量）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from canonical_profile import CANONICAL_PROFILE_ID, canonical_json

from evo_agent_baseline import slot_alias_policy
from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    FactPack,
    Obligation,
    ObligationSet,
    RuleSlice,
)

from . import unknown_attribution
from .applicability import (
    collect_building_component_classes,
    evaluate_applicability,
)
from .fact_binding import FactIndex, build_method_canonical_map
from .identity_binding import BoundObligation
from .identity_blueprint_catalog import (
    IdentityBlueprintCatalog,
    assert_catalog_dual_read_path_consistency,
    assert_catalog_header_and_hash,
)
from .identity_v2 import (
    IDENTITY_SCHEMA,
    CanonicalObligationIdentity,
    ObligationContractError,
    RunInstanceEnvelope,
    compute_canonical_identity_hash,
    compute_obligation_id_v2,
)
from .obligation_deriver import (
    aggregate_trigger_logic,
    derive_workflow_artifact_obligations,
    derive_workflow_deadline_obligations,
    evaluate_definition,
    evaluate_evidence_requirement,
    evaluate_exception,
    evaluate_obligation_edges,
    evaluate_obligation_node,
    evaluate_slot_role,
    evaluate_threshold,
    evaluate_trigger,
    make_rule_not_applicable_by_trigger,
    make_scope_not_applicable,
    make_scope_open,
)
from .schema import (
    ApplicabilityResult,
    HighRiskItem,
    ObligationNodeDTO,
    VerifierConfig,
)

# spec §2.2.3 / §6.1：禁止出现在 agent KG / FactPack / RuleSlice 的属性名。
FORBIDDEN_PROPERTY_NAMES = {
    "expected_verdict",
    "selected_family",
    "projection_status",
    "basis_items",
    "unknown_reason_code",
    "projection_id",
    "projection_registry_id",
    "projection_family",
    "projection_version",
    "required_world_core_slots",
    "required_measurement_slots",
    "required_qualifier_slots",
    "required_sidecar_interfaces",
    "matched_component_refs",
    "matched_measurement_ids",
    "coverage_status",
    "raw_projection_ref_hash",
    "projection_ref_hash",
}
# spec §6.1 forbidden input label / 表名片段。
FORBIDDEN_SOURCE_TOKENS = {
    "normativeprojection",
    "projectionfamilyeval",
    "expectedverdict",
    "evalprojection",
    "evaltruth",
    "projections.parquet",
    "matched_families.parquet",
    "threshold_evaluations.parquet",
    "basis_items.parquet",
    "normative_projection_meta.parquet",
    "coverage_control_metadata.parquet",
}


class ForbiddenSourceError(Exception):
    """RuleSlice / FactPack 含 W2 参考真值字段（spec §6.9 test_blind_inputs）。"""


# ===================================================================== #
# §6.1 forbidden input 守卫
# ===================================================================== #
def _scan_for_forbidden(obj: Any, path: str = "") -> List[str]:
    """递归扫描任意结构里的禁止属性名 / 禁止源 token。

    返回命中的描述列表（空列表表示干净）。
    """
    hits: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in FORBIDDEN_PROPERTY_NAMES:
                hits.append(f"{path}.{ks}" if path else ks)
            if ks.lower() in FORBIDDEN_SOURCE_TOKENS:
                hits.append(f"{path}.{ks}" if path else ks)
            hits.extend(_scan_for_forbidden(v, f"{path}.{ks}" if path else ks))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hits.extend(_scan_for_forbidden(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        low = obj.lower()
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token in low:
                hits.append(f"{path}=<contains {token}>")
    return hits


def assert_no_forbidden_sources(
    fact_pack: FactPack, rule_slice: RuleSlice
) -> None:
    """检查 FactPack / RuleSlice 不含 W2 禁止字段（spec §6.6 第一行）。

    命中即抛 ForbiddenSourceError（hard fail）。
    """
    hits: List[str] = []
    hits.extend(_scan_for_forbidden(fact_pack.model_dump(), "fact_pack"))
    hits.extend(_scan_for_forbidden(rule_slice.model_dump(), "rule_slice"))
    if hits:
        raise ForbiddenSourceError(
            "forbidden W2 reference-truth fields detected: "
            + ", ".join(sorted(set(hits))[:20])
        )


# ===================================================================== #
# §6.7 obligation_id key —— v1 只读（现网键切换增补 §6.2）+ v5 活动
# ===================================================================== #
# identity-v5 现网键切换增补 §6.2：v1 拼串键**改名只读**（compute_obligation_id_v1 /
# dedupe_key_v1 / assign_obligation_ids_v1 / sort_and_dedupe_obligations_v1）——只供旧 v1
# 历史产物重算 / 影子对账 v1 基线，**不接 live 切换后的编号与去重**。活动 `compute_obligation_id` /
# `dedupe_key` / `sort_and_dedupe_obligations` 收 `BoundObligation`（§6.1/§6.3），键换成规范身份哈希、
# 编号换成 compute_obligation_id_v2（身份 + 运行信封）。**禁自动回退**：活动函数不兼容裸 `Obligation`。
def compute_obligation_id_v1(o: Obligation) -> str:
    """obligation_id 确定性 key（spec §6.7，**v1 只读**——不接活路径，现网键切换增补 §6.2）。"""
    raw = "|".join(
        [
            o.run_id,
            o.source_rule_card_id,
            o.kind,
            o.fragment_id or "",
            o.component_id or "",
            ",".join(sorted(o.slot_ref_ids)),
            ",".join(sorted(o.measure_keys)),
            ",".join(sorted(o.artifact_ids)),
            ",".join(sorted(o.deadline_ids)),
            o.obligation_node_id or "",
            ",".join(sorted(o.obligation_edge_ids)),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _run_envelope_for(bound: BoundObligation) -> RunInstanceEnvelope:
    """绑定义务的运行信封（§6.1）——取蓝图冻结 provenance run/world/building，并与 v1 义务一致性校验
    （不一致 = 误配对 → hard-fail `blueprint_obligation_scope_mismatch`，不静默）。"""
    bp = bound.blueprint
    o = bound.obligation
    if (
        o.run_id != bp.provenance.run_id
        or o.world_id != bp.provenance.world_id
        or o.building_id != bp.provenance.building_id
    ):
        raise ObligationContractError(
            "blueprint_obligation_scope_mismatch:"
            f"{bp.provenance.run_id}/{bp.provenance.world_id}/{bp.provenance.building_id}"
            f"!={o.run_id}/{o.world_id}/{o.building_id}"
        )
    return RunInstanceEnvelope(
        run_id=bp.provenance.run_id,
        world_id=bp.provenance.world_id,
        building_id=bp.provenance.building_id,
    )


def compute_obligation_id(bound: BoundObligation) -> str:
    """**活动** obligation_id（现网键切换增补 §6.1）= compute_obligation_id_v2(规范身份, 运行信封)。

    只依赖身份与运行信封 → 同 canonical_identity_hash 组内恒同 id（合并后重算必相同，§6.3 步 6）。
    **只收 `BoundObligation`**（禁裸 `Obligation`、禁自动回退到 v1）。
    """
    return compute_obligation_id_v2(bound.blueprint.identity, _run_envelope_for(bound))


def _rule_card_short(rule_card_id: str) -> str:
    """rule_card_id 的短码（display id 用）。"""
    return rule_card_id.split(".")[-1].split(":")[-1][:16] or rule_card_id[:16]


def display_obligation_id(o: Obligation) -> str:
    """Display ID：OBL-<rule_card_short>-<kind>-<hash8>（spec §6.7）。"""
    return f"OBL-{_rule_card_short(o.source_rule_card_id)}-{o.kind}-{o.obligation_id[:8]}"


def assign_obligation_ids_v1(obligations: List[Obligation]) -> List[Obligation]:
    """给所有 obligation 回填 v1 确定性 obligation_id（**v1 只读**——不接活路径，现网键切换增补 §6.2）。"""
    for o in obligations:
        o.obligation_id = compute_obligation_id_v1(o)
    return obligations


# ===================================================================== #
# §6.6.1 sort_and_dedupe_obligations
# ===================================================================== #
# 合并保守序：blocked > open > closed。
_CLOSURE_RANK = {"blocked": 2, "open": 1, "closed": 0}
# closed 内满足性保守序：violated > satisfied > not_applicable。
_SAT_RANK = {"violated": 2, "satisfied": 1, "not_applicable": 0, "unknown": -1}


def dedupe_key_v1(o: Obligation) -> Tuple:
    """去重键（spec §6.6.1 dedupe_key，**v1 只读**——不接活路径，现网键切换增补 §6.2）。"""
    return (
        o.source_rule_card_id,
        o.kind,
        o.fragment_id or "",
        o.component_id or "",
        tuple(sorted(o.slot_ref_ids)),
        tuple(sorted(o.slot_ids)),
        tuple(sorted(o.measure_keys)),
        tuple(sorted(o.artifact_ids)),
        tuple(sorted(o.deadline_ids)),
        o.obligation_node_id or "",
        tuple(sorted(o.obligation_edge_ids)),
    )


def dedupe_key(bound: BoundObligation) -> str:
    """**活动**去重键（现网键切换增补 §6.1）= 规范身份哈希（`canonical_identity_hash`）。

    **只收 `BoundObligation`**（禁裸 `Obligation`、禁自动回退到 v1 tuple 键）。
    """
    return bound.blueprint.canonical_identity_hash


def sort_key(o: Obligation) -> Tuple:
    """排序键（spec §6.6.1 sort_key）。"""
    return (
        o.source_family_id,
        o.source_rule_card_id,
        o.kind,
        o.fragment_id or "",
        o.component_id or "",
        o.obligation_node_id or "",
        o.obligation_id,
    )


def _stable_unique(items: List[str]) -> List[str]:
    """list 去重并排序（spec §6.6.1 lists: stable_unique(sorted)）。"""
    return sorted({str(x) for x in items if x is not None})


def _merge_two(a: Obligation, b: Obligation) -> Obligation:
    """合并两条同 dedupe_key 的 obligation（spec §6.6.1 合并规则）。

    状态取最保守：blocked > open > closed；closed 内 violated > satisfied >
    not_applicable。lists 合并去重；notes 拼接并打 source 标签。
    """
    # 选保守状态。
    if _CLOSURE_RANK[a.closure_status] >= _CLOSURE_RANK[b.closure_status]:
        primary, secondary = a, b
    else:
        primary, secondary = b, a
    closure_status = primary.closure_status

    if closure_status == "closed":
        # closed：satisfaction 取保守。
        sat = (
            a.satisfaction_status
            if _SAT_RANK[a.satisfaction_status] >= _SAT_RANK[b.satisfaction_status]
            else b.satisfaction_status
        )
    else:
        sat = "unknown"

    # 原因码：取 primary（保守状态来源）的；若 primary 没有用 secondary 的。
    open_reason = primary.open_reason_code or (
        secondary.open_reason_code if closure_status == "open" else None
    )
    blocked_reason = primary.blocked_reason_code or (
        secondary.blocked_reason_code if closure_status == "blocked" else None
    )
    if closure_status != "open":
        open_reason = None
    if closure_status != "blocked":
        blocked_reason = None

    # notes 拼接。
    notes_parts = [n for n in (a.notes, b.notes) if n]
    merged_notes = " | ".join(dict.fromkeys(notes_parts))

    depends = a.depends_on_open_trigger or b.depends_on_open_trigger
    trigger_dep_ids = _stable_unique(
        a.trigger_dependency_ids + b.trigger_dependency_ids
    )
    # depends_on_open_trigger 不变式：为 true 时 trigger_dependency_ids 不得为空。
    if depends and not trigger_dep_ids:
        depends = False

    merged = primary.model_copy(
        update=dict(
            closure_status=closure_status,
            satisfaction_status=sat,
            open_reason_code=open_reason,
            blocked_reason_code=blocked_reason,
            source_clause_ids=_stable_unique(
                a.source_clause_ids + b.source_clause_ids
            ),
            source_quote_ids=_stable_unique(
                a.source_quote_ids + b.source_quote_ids
            ),
            recipient_ids=_stable_unique(a.recipient_ids + b.recipient_ids),
            slot_ref_ids=_stable_unique(a.slot_ref_ids + b.slot_ref_ids),
            slot_ids=_stable_unique(a.slot_ids + b.slot_ids),
            measure_keys=_stable_unique(a.measure_keys + b.measure_keys),
            artifact_ids=_stable_unique(a.artifact_ids + b.artifact_ids),
            artifact_keys=_stable_unique(a.artifact_keys + b.artifact_keys),
            deadline_ids=_stable_unique(a.deadline_ids + b.deadline_ids),
            time_anchor_keys=_stable_unique(
                a.time_anchor_keys + b.time_anchor_keys
            ),
            obligation_edge_ids=_stable_unique(
                a.obligation_edge_ids + b.obligation_edge_ids
            ),
            evidence_fact_ids=_stable_unique(
                a.evidence_fact_ids + b.evidence_fact_ids
            ),
            evidence_node_refs=_stable_unique(
                a.evidence_node_refs + b.evidence_node_refs
            ),
            trigger_dependency_ids=trigger_dep_ids,
            depends_on_open_trigger=depends,
            notes=merged_notes,
        )
    )
    return merged


def sort_and_dedupe_obligations_v1(
    obligations: List[Obligation],
) -> List[Obligation]:
    """去重 + 合并 + 排序（spec §6.6.1，**v1 只读**——不接活路径，现网键切换增补 §6.2）。

    IT-004：同输入重复运行 byte-identical —— 故先按稳定键排序再合并。供旧 v1 历史产物重算 /
    影子对账 v1 基线（stage-two 等价性门槛），不参与 live 切换后的编号与去重。
    """
    # 先回填 obligation_id（合并依赖 dedupe_key，id 不参与 dedupe_key 但参与
    # sort_key；合并后再重算一次 id）。
    assign_obligation_ids_v1(obligations)

    merged: Dict[Tuple, Obligation] = {}
    # 以稳定顺序遍历，保证合并结果确定。
    for o in sorted(obligations, key=sort_key):
        key = dedupe_key_v1(o)
        if key in merged:
            merged[key] = _merge_two(merged[key], o)
        else:
            merged[key] = o

    result = list(merged.values())
    # 合并改了字段，重算 obligation_id。
    assign_obligation_ids_v1(result)
    result.sort(key=sort_key)
    return result


class _BoundGroup:
    """v5 去重折叠组（同 canonical_identity_hash）——首成员冻结身份/immutable bytes，rep 累积折叠。"""

    __slots__ = ("first", "rep", "identity_bytes", "immutable_bytes", "count")

    def __init__(self, first: BoundObligation) -> None:
        self.first = first
        self.rep = first.obligation
        self.identity_bytes = canonical_json(first.blueprint.identity.model_dump())
        self.immutable_bytes = canonical_json(first.blueprint.immutable.model_dump())
        self.count = 1


def _assert_group_consistent(g: _BoundGroup, b: BoundObligation) -> None:
    """§6.3 步 3/4：**合并前**同组 identity canonical bytes 全等（真 hash collision → hard-fail
    `identity_hash_collision_pre_merge`）+ ImmutablePayload canonical bytes 全等（→
    `merge_immutable_payload_conflict`）。合法去重（同源项同身份多状态）恒通过。"""
    if canonical_json(b.blueprint.identity.model_dump()) != g.identity_bytes:
        raise ObligationContractError(
            f"identity_hash_collision_pre_merge:{b.blueprint.canonical_identity_hash}"
        )
    if canonical_json(b.blueprint.immutable.model_dump()) != g.immutable_bytes:
        raise ObligationContractError(
            f"merge_immutable_payload_conflict:{b.blueprint.canonical_identity_hash}"
        )


def sort_and_dedupe_obligations(
    bound: List[BoundObligation],
) -> Tuple[List[Obligation], List[Dict[str, Any]]]:
    """**活动**去重（现网键切换增补 §6.3，"只换键"）——按 `canonical_identity_hash` 分组、状态仍走
    v1 `_merge_two`（判定公式一字不动），返回 (最终扁平 v1 义务列表, identity_manifest)。

    只换分组键与编号（键=规范身份哈希、编号=compute_obligation_id_v2），排序/折叠/状态合并/lists 合并
    **完全复刻** `sort_and_dedupe_obligations_v1`（order-dependent 生产语义，primary=首参）。

    流程（§6.3）：①绑定产物回填 v5 obligation_id（身份+信封派生、组内不变）→ ②按 hash 分组（稳定
    sort_key 序遍历）→ ③合并前同组 identity bytes 全等（真 collision hard-fail）→ ④ImmutablePayload
    全等 → ⑤状态走 `_merge_two` → ⑥合并后 obligation_id 重算相同 → identity_manifest 每最终义务一条。
    IT-004：同输入 byte-identical（稳定 sort_key + 确定折叠）。
    """
    # ① 回填 v5 obligation_id（身份+信封派生 → 组内恒同；供 sort_key 稳定 + 最终编号）。
    for b in bound:
        b.obligation.obligation_id = compute_obligation_id(b)

    # ② 按 canonical_identity_hash 分组，稳定 sort_key 序折叠（primary=首参，order-dependent）。
    groups: Dict[str, _BoundGroup] = {}
    order: List[str] = []
    for b in sorted(bound, key=lambda x: sort_key(x.obligation)):
        h = dedupe_key(b)
        g = groups.get(h)
        if g is None:
            groups[h] = _BoundGroup(b)
            order.append(h)
        else:
            _assert_group_consistent(g, b)  # ③④ 合并前单射闸（真 collision / immutable 冲突拦）
            g.rep = _merge_two(g.rep, b.obligation)  # ⑤ 状态走 v1 _merge_two（判定公式零改）
            g.count += 1

    # 组装最终列表 + identity_manifest。
    result: List[Obligation] = []
    manifest: List[Dict[str, Any]] = []
    for h in order:
        g = groups[h]
        rep = g.rep
        # ⑥ 合并后 obligation_id 重算必相同（身份组内不变）——幂等重算 = 显式断言 step 6。
        recomputed = compute_obligation_id(g.first)
        if rep.obligation_id != recomputed:
            raise ObligationContractError(
                f"obligation_id_recompute_mismatch:{h}"
            )
        result.append(rep)
        manifest.append(
            {
                "obligation_id": rep.obligation_id,
                "canonical_identity_hash": h,
                "identity": g.first.blueprint.identity.model_dump(),
                "immutable": g.first.blueprint.immutable.model_dump(),
            }
        )

    result.sort(key=sort_key)
    # manifest 跟随 result 排序（1:1，按 obligation_id 对齐；碰撞后置保证 id 单射 → 映射安全）。
    _manifest_by_id = {m["obligation_id"]: m for m in manifest}
    manifest = [_manifest_by_id[o.obligation_id] for o in result]
    return result, manifest


def run_collision_postcheck_live(
    manifest: List[Dict[str, Any]], run_envelope: RunInstanceEnvelope
) -> None:
    """§6.3 步 7 全集碰撞后置检查（`run_collision_postcheck` 语义，作用域=**整个 ObligationSet**）。

    ①stored_id == recompute（obligation_id + canonical_identity_hash 双重 recompute 一致）；
    ②obligation_id → canonical identity bytes **全局单射**；③canonical_identity_hash → canonical
    identity bytes **全局单射（无 identity-scope 限缩）**；④dedupe 无逃逸（同 hash ≥2 → hard-fail）。
    fragment_id 已进 identity.scope → hash 已编码 scope，故单射对整个 ObligationSet 成立（跨 fragment /
    跨 building 全集）。一次 building 闭包 = 单一 (world_id, building_id)，run_envelope 分桶即等于全集。
    """
    by_obl_id: Dict[str, str] = {}
    by_hash: Dict[str, str] = {}
    seen_hash: Dict[str, int] = {}
    for m in manifest:
        identity = CanonicalObligationIdentity.model_validate(m["identity"])
        identity_bytes = canonical_json(identity.model_dump())
        # ① recompute 一致（obligation_id 含运行信封 + canonical_identity_hash 不含）。
        if m["obligation_id"] != compute_obligation_id_v2(identity, run_envelope):
            raise ObligationContractError("obligation_id_recompute_mismatch")
        if m["canonical_identity_hash"] != compute_canonical_identity_hash(identity):
            raise ObligationContractError("obligation_id_recompute_mismatch")
        # ② obligation_id → identity 全局单射。
        prev = by_obl_id.get(m["obligation_id"])
        if prev is not None and prev != identity_bytes:
            raise ObligationContractError("obligation_id_not_injective")
        by_obl_id[m["obligation_id"]] = identity_bytes
        # ③ canonical_identity_hash → identity 全局单射（无 scope 限缩）。
        prev_h = by_hash.get(m["canonical_identity_hash"])
        if prev_h is not None and prev_h != identity_bytes:
            raise ObligationContractError("identity_hash_not_injective")
        by_hash[m["canonical_identity_hash"]] = identity_bytes
        # ④ dedupe 无逃逸（同 hash 出现 ≥2 条）。
        seen_hash[m["canonical_identity_hash"]] = (
            seen_hash.get(m["canonical_identity_hash"], 0) + 1
        )
        if seen_hash[m["canonical_identity_hash"]] >= 2:
            raise ObligationContractError("dedupe_escape")


# ===================================================================== #
# §6.3.3 trigger_dependency_ids 回填
# ===================================================================== #
# obligation_deriver 在派生下游 obligation 时使用的占位常量：表示"等这张卡的
# 某 trigger（具体哪条尚未点名）"。回填 pass 会把它展开为该卡所有 trigger 的
# 运行时 obligation_id 列表。spec §6.3.3 / §6.7。
PENDING_CARD_TRIGGER_PLACEHOLDER = "__card_trigger__"


def backfill_trigger_dependency_ids(
    obligations: List[Obligation],
    trigger_provenance: Dict[Tuple[str, str], Obligation],
) -> None:
    """sort_and_dedupe 后把下游 obligation 的 trigger_dependency_ids 从
    `trigger_condition_id` / `__card_trigger__` 占位 解析成运行时 trigger
    obligation_id（spec §6.3.3）。

    `compute_obligation_id`（spec §6.7）不依赖 `trigger_dependency_ids`，
    所以此处改字段不会破坏 id 稳定性。

    入参：
    - obligations: 已 sort_and_dedupe 的 obligation 列表（id 已稳定）。
    - trigger_provenance: 主循环收集的 (rule_card_id, condition_id) →
      trigger Obligation 引用映射。

    就地修改 obligations。回填后保持以下不变式：
    - depends_on_open_trigger=True → trigger_dependency_ids 非空且全是运行时
      trigger obligation_id（没有 trigger_condition_id 或占位符残留）。
    - 占位符 `__card_trigger__` 全部展开为该卡所有 trigger 的运行时 id。
    - 若某 condition_id 在 provenance 里找不到（理论上不应发生，做兜底），
      保留原 condition_id 不删，保证不变式 "trigger_dependency_ids 非空" 不破。
    """
    # 1. 建索引 (card_id, condition_id, fragment_id or "") → 运行时 trigger obligation_id
    #    （spec 草案 §6.3.0 fragment 级派生：同卡触发器按 fragment 分身，回填按下游
    #    义务自身的 fragment 归属精确匹配）。
    by_condition: Dict[Tuple[str, str, str], str] = {
        key: obl.obligation_id for key, obl in trigger_provenance.items()
    }
    # 2. 建索引 (card_id, fragment_id or "") → 该卡该作用域全部 trigger id（展开占位符用）
    by_card_scope: Dict[Tuple[str, str], List[str]] = {}
    for (card_id, _condition_id, frag), obl in trigger_provenance.items():
        by_card_scope.setdefault((card_id, frag), []).append(obl.obligation_id)
    for key in by_card_scope:
        by_card_scope[key] = sorted(set(by_card_scope[key]))

    for o in obligations:
        # codex 审查修正：node 义务无论 trigger_active 真假都携带原始 condition_id
        # （deriver 构造 common 时无条件复制 node.trigger_condition_ids），旧实现只回填
        # depends_on_open_trigger=True 的义务，False 侧残留 trg01/trg02 原始 token。
        # 改为"非空即解析"（compute_obligation_id 不含此字段，id 稳定性不受影响）。
        if not o.trigger_dependency_ids:
            continue
        o_frag = o.fragment_id or ""
        resolved: List[str] = []
        seen = set()
        for ref in o.trigger_dependency_ids:
            if ref == PENDING_CARD_TRIGGER_PLACEHOLDER:
                # 占位 → 展开为该卡该作用域全部 trigger obligation_id
                for tid in by_card_scope.get((o.source_rule_card_id, o_frag), []):
                    if tid not in seen:
                        resolved.append(tid)
                        seen.add(tid)
            else:
                # ref 可能已是 trigger condition_id（line 1327 那条路径）
                tid = by_condition.get((o.source_rule_card_id, ref, o_frag))
                if tid is not None:
                    if tid not in seen:
                        resolved.append(tid)
                        seen.add(tid)
                else:
                    # 兜底：找不到映射保留原值，确保不变式"非空"不破。
                    if ref not in seen:
                        resolved.append(ref)
                        seen.add(ref)
        if resolved:
            o.trigger_dependency_ids = resolved


# ===================================================================== #
# §6.6.2 find_high_risk_items
# ===================================================================== #
def find_high_risk_items(obligations: List[Obligation]) -> List[dict]:
    """高风险项（spec §6.6.2）。返回 dict 列表（ClosureValidationResult 字段类型）。"""
    items: List[dict] = []
    for o in obligations:
        severity: Optional[str] = None
        reason = ""
        if o.closure_status == "closed" and o.satisfaction_status == "violated":
            severity = "high"
            reason = "closed obligation with violated satisfaction"
            if o.kind in {"threshold", "prohibition", "escalation"}:
                reason = f"{o.kind} obligation violated"
        elif o.closure_status == "blocked" and o.blocked_reason_code in {
            "unit_mismatch",
            "ambiguous_fact_binding",
            "unsupported_formula",
        }:
            severity = "medium"
            reason = f"blocked: {o.blocked_reason_code}"
        elif o.closure_status == "open":
            artifact_related = o.open_reason_code in {
                "missing_artifact_evidence",
                "missing_time_anchor",
                "missing_required_field_group",
                "missing_measurement",
                "missing_sidecar_entry",
            }
            if artifact_related:
                severity = "medium"
                reason = f"open: {o.open_reason_code}"
            else:
                severity = "low"
                reason = f"open: {o.open_reason_code}"
        if severity is None:
            continue
        items.append(
            HighRiskItem(
                obligation_id=o.obligation_id,
                severity=severity,
                reason=reason,
                source_rule_card_id=o.source_rule_card_id,
                source_family_id=o.source_family_id,
                evidence_fact_ids=list(o.evidence_fact_ids),
            ).model_dump()
        )
    return items


# ===================================================================== #
# §6.2.4 / §6.5 summarize + allow_stop
# ===================================================================== #
def summarize(
    obligations: List[Obligation],
    guard_result: Dict[str, Any],
    schema_validation_passed: bool = True,
) -> ClosureSummary:
    """统计摘要 + allow_stop / stop_reason（spec §6.2.4 / §6.5）。"""
    closed = sum(1 for o in obligations if o.closure_status == "closed")
    open_c = sum(1 for o in obligations if o.closure_status == "open")
    blocked = sum(1 for o in obligations if o.closure_status == "blocked")

    satisfied = sum(1 for o in obligations if o.satisfaction_status == "satisfied")
    violated = sum(1 for o in obligations if o.satisfaction_status == "violated")
    unknown = sum(1 for o in obligations if o.satisfaction_status == "unknown")
    not_app = sum(
        1 for o in obligations if o.satisfaction_status == "not_applicable"
    )

    open_reason_counts: Dict[str, int] = {}
    blocked_reason_counts: Dict[str, int] = {}
    for o in obligations:
        if o.open_reason_code:
            open_reason_counts[o.open_reason_code] = (
                open_reason_counts.get(o.open_reason_code, 0) + 1
            )
        if o.blocked_reason_code:
            blocked_reason_counts[o.blocked_reason_code] = (
                blocked_reason_counts.get(o.blocked_reason_code, 0) + 1
            )

    rule_card_ids = {o.source_rule_card_id for o in obligations}
    family_ids = {o.source_family_id for o in obligations}
    fragment_ids = {o.fragment_id for o in obligations if o.fragment_id}

    forbidden_passed = bool(
        guard_result.get("forbidden_source_check_passed", True)
    )

    allow_stop, stop_reason = compute_allow_stop_and_reason(
        open_c, blocked, violated, schema_validation_passed, forbidden_passed
    )

    return ClosureSummary(
        total_obligations=len(obligations),
        closed_count=closed,
        open_count=open_c,
        blocked_count=blocked,
        satisfied_count=satisfied,
        violated_count=violated,
        unknown_count=unknown,
        not_applicable_count=not_app,
        open_reason_counts=dict(sorted(open_reason_counts.items())),
        blocked_reason_counts=dict(sorted(blocked_reason_counts.items())),
        rule_card_count=len(rule_card_ids),
        family_count=len(family_ids),
        fragment_count=len(fragment_ids),
        allow_stop=allow_stop,
        stop_reason=stop_reason,
    )


def compute_allow_stop_and_reason(
    open_count: int,
    blocked_count: int,
    violated_count: int,
    schema_validation_passed: bool,
    forbidden_source_check_passed: bool,
) -> Tuple[bool, str]:
    """allow_stop + stop_reason（spec §6.5.1 / §6.5.2）。

    allow_stop = open==0 and blocked==0 and schema_ok and forbidden_ok。
    violated_count > 0 不影响 allow_stop。
    """
    # stop_reason 优先级（spec §6.5.2 表）：先 forbidden / schema，再 open / blocked。
    if not forbidden_source_check_passed:
        return (False, "forbidden_reference_truth_detected")
    if not schema_validation_passed:
        return (False, "schema_validation_failed")
    if open_count > 0:
        return (False, "open_obligations_remain")
    if blocked_count > 0:
        return (False, "blocked_obligations_remain")
    # 无 open / blocked。
    if violated_count > 0:
        return (
            True,
            "all_applicable_obligations_closed_with_violations_for_human_review",
        )
    return (True, "all_applicable_obligations_closed_and_satisfied")


# ===================================================================== #
# §6.2 v1 instrumentation helpers (spec v1 §6.2 + §3.8 canonical JSON)
# ===================================================================== #
def _canonical_dumps(payload: Any) -> str:
    """canonical JSON：sort_keys + utf-8 + ensure_ascii=False（spec v1 §3.8）。

    list 默认保持语义顺序；调用方对 set-semantic 字段应自行 sort 后再传入。
    """
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _sha256_hex(text: str) -> str:
    """SHA-256 hex lowercase（spec v1 §3.8 hash 规则）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# 🔴 DEBT-079：这些字段是**运行期标识**，每跑一次都变，不属于「输入内容」。
# 含它们的哈希跨运行永远不可能相等 ⇒ 不能当跨批对账锚。
_VOLATILE_IDENTITY_FIELDS = ("run_id",)


def _content_only(payload: dict) -> dict:
    """剔掉运行期标识后的 payload（只在顶层剔，不递归——那些字段只在顶层）。"""
    return {k: v for k, v in payload.items() if k not in _VOLATILE_IDENTITY_FIELDS}


def compute_fact_pack_content_hash(fact_pack: FactPack) -> str:
    """FactPack 的**内容**哈希——剔掉 `run_id` 等运行期标识（DEBT-079）。

    与 `compute_fact_pack_hash` 的关系：**两者并存，用途不同，不可互换**。

    | | 含 `run_id` | 用途 |
    |---|---|---|
    | `compute_fact_pack_hash` | ✅ | 本次运行的输入指纹（spec v1 §6.2/§3.8 口径，**不动**） |
    | `compute_fact_pack_content_hash` | ❌ | **跨批对账**：内容同 ⇒ 哈希必等 |

    为什么要新加一个而不是改老的：老的口径写在 spec 里，改它属规格面；
    而「跨批证明事实包没变」这个需求是纯新增的，加一个字段即可满足，
    不需要重定义任何既有字段。

    **实证背景**（2026-07-29，批 D vs 批 E，同池同库同档位）：
    两批 `fact_pack.json` 逐字段比对**只有 `run_id` 不同**，
    而 30/30 栋 `fact_pack_hash` **全部不同**——门④「事实包没变」
    此前**没有任何落盘哈希能证明**，只能靠人逐字段比。
    """
    return _sha256_hex(_canonical_dumps(_content_only(fact_pack.model_dump())))


def compute_rule_slice_content_hash(rule_slice: RuleSlice) -> str:
    """RuleSlice 的**内容**哈希——剔掉 `run_id` 等运行期标识（DEBT-079）。

    与 `compute_rule_slice_hash` 并存，用途见 `compute_fact_pack_content_hash`。
    """
    return _sha256_hex(_canonical_dumps(_content_only(rule_slice.model_dump())))


def compute_fact_pack_hash(fact_pack: FactPack) -> str:
    """canonical FactPack hash（spec v1 §6.2 + §3.8）。

    用 pydantic model_dump → canonical JSON → sha256。
    facts 列表保持语义顺序（FactPack 入参顺序即检索顺序）；slot_index /
    measure_index / carrier_index 的 list value 在 build 时已按 fact_id 顺序，
    canonical 化时 dict key 自动按 unicode 升序。
    """
    payload = fact_pack.model_dump()
    return _sha256_hex(_canonical_dumps(payload))


def compute_rule_slice_hash(rule_slice: RuleSlice) -> str:
    """canonical RuleSlice hash（spec v1 §6.2 + §3.8）。

    candidate_rule_cards 按 rule_card_id 排序后再 hash，避免 retrieval 顺序差
    导致 hash 漂移（spec §5.4.4 ranking 只影响 LLM context，verifier 全集是
    set 语义 → set-semantic list 应排序）。
    """
    payload = rule_slice.model_dump()
    # 关键 set-semantic list 在 hash 前显式排序
    cards = payload.get("candidate_rule_cards") or []
    cards.sort(key=lambda c: c.get("rule_card_id", ""))
    payload["candidate_rule_cards"] = cards
    rule_families = payload.get("rule_families") or []
    rule_families.sort(key=lambda f: f.get("family_id", ""))
    payload["rule_families"] = rule_families
    semantic_slots = payload.get("semantic_slots") or []
    semantic_slots.sort(key=lambda s: s.get("slot_id", ""))
    payload["semantic_slots"] = semantic_slots
    measures = payload.get("measures") or []
    measures.sort(key=lambda m: m.get("measure_key", ""))
    payload["measures"] = measures
    artifacts = payload.get("artifacts") or []
    artifacts.sort(key=lambda a: a.get("artifact_key", ""))
    payload["artifacts"] = artifacts
    time_anchors = payload.get("time_anchors") or []
    time_anchors.sort(key=lambda t: t.get("time_anchor_key", ""))
    payload["time_anchors"] = time_anchors
    source_quotes = payload.get("source_quotes") or []
    source_quotes.sort(key=lambda q: q.get("source_quote_id", ""))
    payload["source_quotes"] = source_quotes
    return _sha256_hex(_canonical_dumps(payload))


def compute_candidate_universe_hash(rule_card_ids: List[str]) -> str:
    """verifier candidate universe canonical hash（spec v1 §5.5.2 + §6.2）。

    入参：已排序的 rule_card_id 列表（set 语义）。
    实现：去重 → 排序 → canonical JSON list → sha256。
    """
    uniq = sorted({str(r) for r in rule_card_ids if r is not None})
    return _sha256_hex(_canonical_dumps(uniq))


# ===================================================================== #
# §6.6.3 build_machine_report
# ===================================================================== #
def build_machine_report(
    obligations: List[Obligation],
    summary: ClosureSummary,
    run_id: str,
    world_id: str,
    building_id: str,
) -> Dict[str, Any]:
    """LLM 可读机器报告（spec §6.6.3）。

    禁止包含 W2 expected_verdict / projection_status / basis_items。
    """
    return {
        "run_id": run_id,
        "world_id": world_id,
        "building_id": building_id,
        "allow_stop": summary.allow_stop,
        "stop_reason": summary.stop_reason,
        "closure_summary": summary.model_dump(),
        "rule_slice_summary": {
            "rule_card_count": summary.rule_card_count,
            "family_count": summary.family_count,
        },
        "obligations": [o.model_dump() for o in obligations],
        "high_risk_items": find_high_risk_items(obligations),
        "open_items": [
            o.model_dump() for o in obligations if o.closure_status == "open"
        ],
        "blocked_items": [
            o.model_dump() for o in obligations if o.closure_status == "blocked"
        ],
        "violated_items": [
            o.model_dump()
            for o in obligations
            if o.satisfaction_status == "violated"
        ],
        "source_guard": {
            "forbidden_source_check_passed": True,
            "forbidden_sources": [],
        },
    }


# ===================================================================== #
# §6.6 主入口
# ===================================================================== #
def _fact_pack_meta(fact_pack: FactPack) -> Dict[str, str]:
    """从 FactPack 抽 run/world/building 元数据。"""
    return {
        "run_id": fact_pack.run_id,
        "world_id": fact_pack.world_id,
        "building_id": fact_pack.building_id,
    }


# 别名归一统一入口已收口到 `evo_agent_baseline.slot_alias_policy`（2026-07-27，
# 别名归一三咬后）；下面三个是**薄包装**保既有测试/脚本兼容，唯一权威实现在新模块。
# 新模块只依赖 contracts（吃 dict），closure / retrieval / scripts 三方 import 均无环。


def _normalize_alias_map(aliases: Any) -> Dict[str, str]:
    """薄包装 → `slot_alias_policy.normalize_alias_map`（语义逐字节不变）。"""
    return slot_alias_policy.normalize_alias_map(aliases)


def _measure_aliases_from_policy(rule_slice: RuleSlice) -> Dict[str, str]:
    """薄包装 → `slot_alias_policy.measure_aliases_from_policy`。"""
    return slot_alias_policy.measure_aliases_from_policy(
        rule_slice.retrieval_policy or {}
    )


def _slot_aliases_from_policy(rule_slice: RuleSlice) -> Dict[str, str]:
    """薄包装 → `slot_alias_policy.slot_aliases_from_policy`。"""
    return slot_alias_policy.slot_aliases_from_policy(
        rule_slice.retrieval_policy or {}
    )


def _method_aliases_from_policy(rule_slice: RuleSlice) -> Dict[str, str]:
    """从 retrieval_policy 取 method_aliases 并建**运行态展开表** ``{alias→canonical}``。

    DEBT-049 Phase3 U2（链②别名传输）。**不复用 ``_normalize_alias_map``**——method 的
    raw 是 grouped ``{canonical: [alias, ...]}``（canonical 在 key 侧，与 slot/measure 相反），
    ``_normalize_alias_map`` 取列表首项 + 方向 ``{key→首项}`` 会丢别名且反向；改走
    ``build_method_canonical_map`` 反转全展开（含 identity 自映射）。policy 无此键 → 空表
    → ``canonical_method`` 全走 ``.get(x, x)`` identity（保守，不改判定）。
    """
    policy = rule_slice.retrieval_policy or {}
    mapping = policy.get("projection_runtime_mapping_v1") or {}
    return build_method_canonical_map(mapping.get("method_aliases") or {})


def _compute_unknown_attribution_isolated(
    obligations: List[Obligation],
    fact_pack: FactPack,
    rule_slice: RuleSlice,
    fact_index: FactIndex,
    fragment_of_fact: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """unknown 归因旁路——**结构隔离**的调用壳（判定权红线）。

    🔴 三条结构保证（不靠"小心"）：
    1. 本函数只在 `summarize()` 与 `allow_stop` **算完之后**被调用；它拿到的
       `obligations` 只用于**投影出基本值快照**，投影后即不再触碰——归因策略
       `unknown_attribution.attribute_unknown_obligations` 收到的全是 frozen
       dataclass / 基本值，结构上没有能力回写义务。
    2. 归因策略**任何异常**都被吞掉并落兜底（全部 `attribution_input_missing`
       并报警）——策略炸了也绝不改判定、绝不谎称"该你填"。
    3. 产出的键集与 unknown 义务集**强制对齐**（缺的补兜底、多的丢弃），故
       `ClosureValidationResult` 的守恒门恒成立。

    返回 (mapping, audit)。
    """
    unknown_ids = [
        o.obligation_id for o in obligations if o.satisfaction_status == "unknown"
    ]
    audit: Dict[str, Any] = {}
    mapping: Dict[str, Any] = {}
    degraded_reason: Optional[str] = None
    try:
        snapshots, status_by_id, deps_by_id = unknown_attribution.build_unknown_snapshots(
            obligations,
            canonical_slot=fact_index.canonical_slot,
            slot_ref_bindings=unknown_attribution.build_slot_ref_bindings(
                rule_slice
            ),
        )
        pools = unknown_attribution.build_supplied_slot_pools(
            fact_pack.facts,
            canonical_slot=fact_index.canonical_slot,
            fragment_of_fact=fragment_of_fact,
        )
        # 责任表加载失败 → 按「无登记」归因（全 system_unresolved），不拖垮原因码轴。
        resp_map: Optional[Mapping[str, str]] = None
        action_map: Optional[Mapping[str, str]] = None
        registry_present = False
        registry_load_error: Optional[str] = None
        try:
            resp_map, action_map, _doc = (
                unknown_attribution.load_responsibility_registry()
            )
            registry_present = True
        except Exception as reg_exc:  # noqa: BLE001
            registry_load_error = f"{type(reg_exc).__name__}: {reg_exc}"
        mapping = dict(
            unknown_attribution.attribute_unknown_obligations(
                snapshots,
                closure_status_by_obligation_id=status_by_id,
                dependency_ids_by_obligation_id=deps_by_id,
                supplied_slot_pools=pools,
                responsibility_registry=resp_map,
                professional_action_by_slot=action_map,
            )
        )
    except Exception as exc:  # noqa: BLE001 —— 归因绝不影响判定，异常一律降级
        degraded_reason = f"{type(exc).__name__}: {exc}"
        mapping = {}
        registry_present = False
        registry_load_error = None

    # 键集强制对齐：多的丢、缺的补兜底（守恒门恒成立）。
    extra = [k for k in mapping if k not in set(unknown_ids)]
    for k in extra:
        mapping.pop(k, None)
    missing = [oid for oid in unknown_ids if oid not in mapping]
    if missing:
        mapping.update(
            unknown_attribution.fallback_attribution(
                missing,
                reason=degraded_reason or "归因策略未覆盖该义务",
            )
        )

    # Scope relation is a second, orthogonal side-channel.  Its failure must never
    # replace the already-computed cause_code / validator reason / root dependency.
    scope_relation_degraded_reason: Optional[str] = None
    try:
        card_component_types = (
            unknown_attribution.build_card_component_type_key_map(rule_slice)
        )
        fragment_component_types = (
            unknown_attribution.build_fragment_component_type_map(fact_pack.facts)
        )
        relation_snapshots, _, _ = unknown_attribution.build_unknown_snapshots(
            obligations,
            canonical_slot=fact_index.canonical_slot,
            card_component_type_keys_by_rule_card_id=card_component_types,
            fragment_component_type_by_fragment_id=fragment_component_types,
        )
        rule_card_ids_by_obligation_id = {
            str(obligation.obligation_id): str(obligation.source_rule_card_id or "")
            for obligation in obligations
            if obligation.satisfaction_status == "unknown"
        }
        mapping = unknown_attribution.attach_scope_relations(
            mapping,
            relation_snapshots,
            unknown_attribution.build_scope_relation_policy(rule_slice),
            rule_card_ids_by_obligation_id=rule_card_ids_by_obligation_id,
        )
    except Exception as relation_exc:  # noqa: BLE001 - relation axis is non-authoritative
        scope_relation_degraded_reason = (
            f"{type(relation_exc).__name__}: {relation_exc}"
        )
        unavailable_policy = unknown_attribution.unavailable_scope_relation_policy()
        mapping = unknown_attribution.attach_unavailable_scope_relations(
            mapping,
            relation_policy_version=unavailable_policy.relation_policy_version,
        )

    audit = unknown_attribution.summarize_attribution(mapping)
    audit["degraded"] = degraded_reason is not None
    audit["degraded_reason"] = degraded_reason
    audit["scope_relation_degraded"] = scope_relation_degraded_reason is not None
    audit["scope_relation_degraded_reason"] = scope_relation_degraded_reason
    audit["backfilled_count"] = len(missing)
    audit["dropped_extra_count"] = len(extra)
    audit["responsibility_registry_present"] = registry_present
    if registry_load_error:
        audit["responsibility_registry_load_error"] = registry_load_error
    return mapping, audit


def validate_building_closure(
    rule_slice: RuleSlice,
    fact_pack: FactPack,
    config: Optional[VerifierConfig] = None,
    *,
    identity_blueprint_catalog: IdentityBlueprintCatalog,
    skill_invocation_ids: Optional[List[str]] = None,
    policy_version_id: Optional[str] = None,
    pre_dedup_out: Optional[List[BoundObligation]] = None,
    applicability_bundle: Optional[Any] = None,
    trigger_ct_disjoint_na: bool = False,
    exclude_fallback_reasons_facts: bool = False,
    authorized_scope_selection: bool = False,
    mask_lookup_targets: bool = False,
    c55_bucket_value_consumption: bool = False,
) -> ClosureValidationResult:
    """闭包验证器主入口（spec §6.6 + v1 §6.2 instrumentation）。

    输入 RuleSlice + FactPack（确定性、纯 DTO）；输出 ClosureValidationResult。
    生成顺序固定（spec §6.3.1）：applicability → triggers → slot roles →
    thresholds → obligation_graph nodes/edges → evidence requirements →
    exceptions → definitions → sort/dedupe。

    v1 §6.2 provenance instrumentation：
    - `skill_invocation_ids`：本次 closure 前触发过的 SkillActivation id 列表，
      仅作 provenance 写入 machine_readable_report，不影响判定逻辑。
    - `policy_version_id`：active policy version，同上仅作 provenance。
    - `candidate_universe_hash` / `fact_pack_hash` / `rule_slice_hash`：
      四个 hash 由本入口算出后写入 machine_readable_report。

    spec v1 §6.3 不变量：Skill / Policy 不可改 closure_status /
    satisfaction_status / allow_stop —— 本函数判定逻辑保持 v0.4 一致。

    identity-v5 现网键切换（现网键切换增补 §5.2/§6，**已切活动键**）：
    - `identity_blueprint_catalog`：**必填、无默认、无回退**——Decimal 读径生成的全卡全 channel 逐 scope
      蓝图全集 + 五元组索引（由调用方 `build_identity_blueprint_catalog` 建）。缺 catalog → `TypeError`
      （不静默回退 v1、不从 float `RuleSlice` 重建身份、不读隐式仓库路径）。
    - 主循环每条 pre-dedup 义务经**来源令牌五元组**绑定 catalog 蓝图（`BoundObligation`），去重按
      `canonical_identity_hash` 分组、编号换成 `compute_obligation_id_v2`（身份+运行信封）——**只换键**：
      状态合并仍走 v1 `_merge_two`、`allow_stop` 公式 / 各 `evaluate_*` 判定分支**一字不动**（§12 红线）。
    - `pre_dedup_out`：非 None 时收 **pre-dedup 绑定多重集深拷贝快照**（供影子对账驱动按 v1 旧键 vs v5
      新键重算去重、逐楼 allow_stop 零翻转核对）；不改返回结果字节。
    - `trigger_ct_disjoint_na`（「乙」放宽档，2026-08-01，**缺省 False=行为逐位不变**）：
      触发器组件限定与 fragment 身份显式登记 disjoint 即判结构 NA，不再要求限定值恒等于
      该卡授权目标叶型。只供配对重放量测与决策门评估；未过 codex 审核门**不得**在生产批开启。
      显式传参、不读环境变量（防静默配置退化族）。
      **2026-08-01 深夜追记：LLM 存量批重放实测乙伤召回（0.4548→0.4501），默认开启已被
      否决——本参数永久定位量测档，勿再提默认开启。**
    - `exclude_fallback_reasons_facts`（DEBT-083 第 3 步「事实用途边界分流」，2026-08-01，
      **缺省 False=行为逐位不变**）：spec 明文 `fallback_reasons` 只解释未知/不适用、不得
      参与满足/违反判定；开启后该组事实不进判定绑定索引（slot/measure/artifact/method），
      仍留事实包与 carrier 索引供解释。属「修判定」——过 DEBT-083 四门验收
      （转移矩阵/守恒/逐条真值核对/双批召回）前不得在生产批开启。
    """
    if config is None:
        config = VerifierConfig()

    # ---- catalog 自洽闸（现网键切换增补 §5.1；进主循环前，绝不 fail-open）----
    # header 三字段==冻结常量 + 五元组索引完备 + identity_catalog_sha256 重算一致；拦 header v4 /
    # 错 profile / 伪 hash 的 catalog 冒充现网身份材料（独立于下方 §5.3 双读径五元组闸）。
    assert_catalog_header_and_hash(identity_blueprint_catalog)

    # ---- identity-v5 活动来源绑定登记器（§6，登记机制转正为活动绑定路径）----
    # 主循环每 append 一条 pre-dedup 义务即同序登记其**真引用 + 五元组关联键**（deep_copy=False：live
    # 绑定真义务，非深拷贝）；登记不改返回义务字节、不进判定分支（§1.3 来源登记钩子红线）。
    from .identity_shadow import _ShadowRegistrar  # 局部 import 破环（identity_shadow 局部 import 本模块）
    bind_sink: List[Tuple[Obligation, Any]] = []
    _reg = _ShadowRegistrar(bind_sink, deep_copy=False)

    # §6.6 第一行：禁止源守卫。
    schema_validation_passed = True
    try:
        assert_no_forbidden_sources(fact_pack, rule_slice)
    except ForbiddenSourceError:
        # test_blind_inputs：含禁止字段 hard fail —— 直接抛给调用方。
        raise

    meta = _fact_pack_meta(fact_pack)
    measure_aliases = _measure_aliases_from_policy(rule_slice)
    slot_aliases = _slot_aliases_from_policy(rule_slice)
    method_aliases = _method_aliases_from_policy(rule_slice)  # DEBT-049 Phase3 U2 运行态展开表
    # 🔴 构件类型涵盖关系（DEBT-076）：从类型格 policy 取，喂给 FactIndex，
    # 由它贯穿全部限定符过滤点。**取不到 ⇒ 空 ⇒ 严格相等匹配（与改动前等价）。**
    # ⚠️ 必须在此处取而不能复用下方 `_lattice_policy`——那段在本行之后才执行。
    _ct_subsumption = (
        ((rule_slice.retrieval_policy or {}).get("component_type_lattice") or {})
        .get("subsumption") or {}
    )
    fact_index = FactIndex(
        fact_pack,
        slot_aliases=slot_aliases,
        measure_aliases=measure_aliases,
        method_aliases=method_aliases,
        numeric_tolerance=config.numeric_tolerance,
        component_subsumption=_ct_subsumption,
        exclude_explanatory=exclude_fallback_reasons_facts,
        mask_lookup_targets=mask_lookup_targets,
        c55_bucket_value_consumption=c55_bucket_value_consumption,
    )

    obligations: List[Obligation] = []
    # 主循环收集 (rule_card_id, trigger_condition_id, fragment_id or "") → trigger
    # obligation 引用，供 sort_and_dedupe 后的 trigger_dependency_ids 回填 pass 用
    # （spec §6.3.3；fragment 级派生下同卡触发器按 fragment 分身）。
    trigger_provenance: Dict[Tuple[str, str, str], Obligation] = {}

    # ---- fragment 级派生基建（spec 草案 §6.3.0，DEBT-046 路线①）----
    # fragment 承载域：卡内任一 slot 的 semantic_domain 落在这些域 → 该卡按
    # (card × fragment) 派生、以该 fragment 的事实子集求值（触发器/阈值/证据在
    # fragment 内绑定，消解跨 fragment 歧义、与 W2 真值同粒度）；否则维持楼级
    # （v0.4 行为）。判定权语义（allow_stop / 状态归约）一字不动。
    _FRAGMENT_DOMAINS = {"defect", "repair", "risk", "scope", "verification"}
    _slot_domain: Dict[str, str] = {}
    for s in rule_slice.semantic_slots or []:
        sid = getattr(s, "slot_id", None)
        if sid:
            _slot_domain[str(sid)] = str(getattr(s, "semantic_domain", "") or "")

    def _fact_frag(f: Any) -> Optional[str]:
        q = f.qualifiers.get("fragment_id") if f.qualifiers else None
        if isinstance(q, str) and q:
            return q
        if f.carrier_type == "fragment" and f.carrier_id:
            return str(f.carrier_id)
        return None

    fragment_ids = sorted({
        fid for fid in (_fact_frag(f) for f in fact_pack.facts) if fid
    })

    # ---- 双读径五元组核对闸（现网键切换增补 §5.3；进主循环前，绝不 fail-open）----
    # float 判定读径卡集 ↔ Decimal 身份 catalog 蓝图五元组 manifest 双向 0 差（含 fragment scope +
    # 三类控制审计 channel）。任一侧缺/多 → hard-fail（catalog 与判定读径同源 slot_domain / fragment_ids）。
    assert_catalog_dual_read_path_consistency(
        identity_blueprint_catalog,
        list(rule_slice.candidate_rule_cards),
        fragment_ids,
        _slot_domain,
    )

    # ---- DEBT-047：适用性规则 3 词桥基建 ----
    # 楼内组件类集（rule 词汇）：component_type 事实的 W0 原生值经
    # qualifier_value_aliases.component_type_key 翻译；无对照的保留原值。
    _mapping_policy = (rule_slice.retrieval_policy or {}).get(
        "projection_runtime_mapping_v1"
    ) or {}
    # DEBT-065 第一波:组件类型格 + 精确目标授权(loader ingest 已验证并产出
    # {rule_card_id: target},闭包侧只按 id 查,绕开 KG 重建 DTO 与 card_fingerprint 口径分歧)。
    # 无资产 → _auth_targets 空 → 组件结构早退判据恒 False(runtime 保守关闭)。
    _lattice_policy = (rule_slice.retrieval_policy or {}).get("component_type_lattice") or {}
    _lattice_leaf_types: set = set(_lattice_policy.get("leaf_types") or [])
    _lattice_disjoint: set = {
        frozenset(p) for p in (_lattice_policy.get("disjoint_pairs") or []) if len(set(p)) == 2
    }
    _auth_targets_raw: Dict[str, Any] = (
        (rule_slice.retrieval_policy or {}).get("exact_fragment_target_authorizations") or {}
    )
    # P1-2:授权运输新形态 {rule_card_id: {"target": ..., "card_content_sha256": ...}};
    # 兼容旧形态 {rule_card_id: str_target}(测试/历史 policy 可能仍为纯字符串)。
    _auth_targets: Dict[str, str] = {}
    for _atk, _atv in _auth_targets_raw.items():
        if isinstance(_atv, dict):
            _auth_targets[_atk] = _atv.get("target", "")
        elif isinstance(_atv, str):
            _auth_targets[_atk] = _atv
    _subject_crosswalk = _mapping_policy.get("subject_component_crosswalk") or {}
    _ct_value_alias = (
        _mapping_policy.get("qualifier_value_aliases") or {}
    ).get("component_type_key") or {}
    # P1-2:运行时同源校验——lattice 的 alias 快照须与当前 mapping alias 一致(防 KG 内
    # lattice 与 mapping 版本错配,旧授权作用于已变卡);不一致 → 整体关闭组件结构早退
    # (判据恒 False)。缺席亦整体关闭(_lattice_leaf_types/_auth_targets 缺省空)。
    # TODO(多版本):v2.2 §2.4 精确版本键冻结(run 级冻结三资产版本,禁 ORDER BY DESC 字典序
    # v9>v10);v1 单版本下 ORDER BY DESC LIMIT 1 取唯一版本 + loader ingest 校验 + 本同源校验兜底。
    from .component_lattice import canonical_hash as _ct_lattice_hash
    _lattice_alias_snap = _lattice_policy.get("alias_mapping_snapshot_sha256")
    if _lattice_alias_snap and _ct_lattice_hash(_ct_value_alias) != _lattice_alias_snap:
        _lattice_leaf_types = set()
        _lattice_disjoint = set()
        _auth_targets = {}
        # 🔴 2026-07-27 codex 四审 P1（fail-open）：上面三样清了，但**包含关系
        # `_ct_subsumption` 早在 :1071 就被读走、:1081 已传进 `FactIndex`**——
        # 校验发生在这里（:1159）时它已经在里面了。不收回 ⇒ `qualifiers_match`
        # 继续用**过期的父子关系**，把本该落 `qualifier_conflict`/`unknown` 的
        # 限定符当成命中 ⇒ **快照失配却改变了闭包判定**。
        # 「必须在此处取而不能复用下方 `_lattice_policy`」那条注释解决的是"取得到"，
        # 没解决"校验失败要收回"——本行补上后半截。
        # ⚠️ 这是今日第十三个同形状：**校验失败了，但某个消费者继续用未经校验的数据。**
        _ct_subsumption = {}
        fact_index.component_subsumption = {}
    building_component_classes = collect_building_component_classes(
        fact_pack,
        _ct_value_alias,
    )

    # ---- DEBT-050 修案：触发器限定符结构可满足性基建（spec 增补 2026-07-08）----
    # 作用域相容组件身份集：fragment=该部位组件类型（fragment 归属事实的
    # component_type_key 多数来源，剔类目派生行——其键已换类目值）、楼级=楼内
    # 组件类集；均含类目成员展开。身份未知 → None（判定关闭，保守回落 missing）。
    _cat_members: Dict[str, set] = {
        str(k): {m for m in (v or {}).get("members") or [] if isinstance(m, str)}
        for k, v in (_mapping_policy.get("component_category_members") or {}).items()
        if isinstance(v, dict) and not str(k).startswith("_")
    }

    def _with_categories(base: set) -> set:
        return base | {c for c, m in _cat_members.items() if base & m}

    _frag_ct: Dict[str, set] = {}
    for _f in fact_pack.facts:
        _fid = _fact_frag(_f)
        if not _fid:
            continue
        if (_f.provenance or {}).get("derivation") == "category_membership":
            continue
        _v = (_f.qualifiers or {}).get("component_type_key")
        if isinstance(_v, str) and _v:
            _frag_ct.setdefault(_fid, set()).add(_v)

    # P1-1(§3.0 专用身份通道,复审后完整版):身份只认检索器生成的 w0_component_identity
    # 专用原子(from 原始 Fragment→Component 关系,provenance.channel 标记,value_json 已 canonical)。
    # 不扫一般事实 qualifier(普通事实叶型不得误认)、按 fragment_id 索引、同 fragment 多来源
    # (不该发生)标 dup→None。真实数据有效(检索器 enrich 从 raw.fragments 生成)+ 不可伪造
    # (专用 slot_id + provenance.channel)。复审 P1-1 修复:旧 slot_id==component_type 近似真实
    # 数据下无效(真实事实无 fragment_id)、且可被普通事实伪造。
    _w0_identity_src: Dict[str, str] = {}
    _w0_identity_dup: set = set()
    for _f in fact_pack.facts:
        if _f.slot_id != "w0_component_identity":
            continue
        if (_f.provenance or {}).get("channel") != "w0_component_identity":
            continue
        _fid = (_f.qualifiers or {}).get("fragment_id")
        if not isinstance(_fid, str) or not _fid:
            continue
        try:
            _idv = json.loads(_f.value_json)
        except (TypeError, ValueError):
            _idv = None
        if isinstance(_idv, str) and _idv:
            if _fid in _w0_identity_src:
                _w0_identity_dup.add(_fid)
            _w0_identity_src[_fid] = _idv

    # 已知组件身份宇宙（codex 裁决护栏：T 卡端脏值/未规范化不得推断 NA）
    _known_ct: set = (
        set(_ct_value_alias.values()) | set(_cat_members.keys())
        | set(building_component_classes)
        | {v for vs in _frag_ct.values() for v in vs}
    )
    _building_compat = _with_categories(set(building_component_classes))

    def _scope_component_types(scope_fid: Optional[str]) -> Optional[set]:
        if scope_fid is None:
            return _building_compat if building_component_classes else None
        base = _frag_ct.get(scope_fid)
        return _with_categories(set(base)) if base else None

    def _w0_fragment_identity(scope_fid: Optional[str]) -> Optional[str]:
        """§3.0 fragment 单值 W0 组件身份(叶型)。仅认 w0_component_identity 专用通道
        (检索器 from 原始 Fragment→Component,provenance.channel 标记);同 fragment 多来源 /
        空 / 非叶 → None(不早退,不产未证成 NA)。楼级(scope_fid None)恒 None(组件维楼级 NA 废止)。
        """
        if scope_fid is None or scope_fid in _w0_identity_dup:
            return None
        v = _w0_identity_src.get(scope_fid)
        return v if v and v in _lattice_leaf_types else None

    def _provable_disjoint(target: str, identity: str) -> bool:
        """(授权目标叶型, fragment 身份叶型) 显式登记于 disjoint_pairs 才可证互斥。

        禁传递闭包、禁"未登记=互斥"(v2.2 红线 1/4)。
        """
        return (
            target in _lattice_leaf_types and identity in _lattice_leaf_types
            and target != identity and frozenset((target, identity)) in _lattice_disjoint
        )

    # ---- DEBT-050 location 维度扩展（②，2026-07-08）：位置结构可满足性基建 ----
    # location 无类目层级，直接值判（比 component 简单）。fragment location 集从
    # location_class_key 限定符事实取（enrich 后带）；楼级作用域 location 集=全池。
    _lc_value_alias = (
        _mapping_policy.get("qualifier_value_aliases") or {}
    ).get("location_class_key") or {}
    _frag_lc: Dict[str, set] = {}
    for _f in fact_pack.facts:
        _fid = _fact_frag(_f)
        if not _fid or (_f.provenance or {}).get("derivation") == "category_membership":
            continue
        _v = (_f.qualifiers or {}).get("location_class_key")
        if isinstance(_v, str) and _v:
            _frag_lc.setdefault(_fid, set()).add(_v)
    _building_locs: set = {v for vs in _frag_lc.values() for v in vs}
    _known_lc: set = set(_lc_value_alias.values()) | _building_locs

    def _scope_location_classes(scope_fid: Optional[str]) -> Optional[set]:
        if scope_fid is None:
            return _building_locs or None
        base = _frag_lc.get(scope_fid)
        return set(base) if base else None

    _frag_index_cache: Dict[str, FactIndex] = {}

    def _fragment_index(fid: str) -> FactIndex:
        """fid 作用域的事实索引：本 fragment 的事实 + 楼级（无 fragment 归属）事实。

        楼级聚合读数（qualifiers.aggregation=='building'，spec 草案·流程槽粒度
        语义 §3.2）**排除**——部位承载卡必须读本部位原值，聚合读数只暴露给
        楼级作用域；普通楼级事实（无该标记）照旧可见。
        """
        if fid not in _frag_index_cache:
            sub = [
                f for f in fact_pack.facts
                if _fact_frag(f) in (None, fid)
                and (f.qualifiers or {}).get("aggregation") != "building"
            ]
            _frag_index_cache[fid] = FactIndex(
                fact_pack.model_copy(update={"facts": sub}),
                slot_aliases=slot_aliases,
                measure_aliases=measure_aliases,
                method_aliases=method_aliases,
                numeric_tolerance=config.numeric_tolerance,
                component_subsumption=_ct_subsumption,
                # 分流必须贯穿逐片段索引——只接主索引会让 fragment 作用域绕过边界
                # （「同一假设散在多层」坑，缺省 False 与主索引同源）。
                exclude_explanatory=exclude_fallback_reasons_facts,
        mask_lookup_targets=mask_lookup_targets,
            )
        return _frag_index_cache[fid]

    def _card_is_fragment_scoped(card: Any) -> bool:
        """卡按什么粒度读数——**隐式判据**：任一槽的域 ∈ `_FRAGMENT_DOMAINS`。

        🔧 **DEBT-085 件二·声明读取路径的空转钩位（第一步声明期，此处不接线）**：
        显式粒度声明已落在 `binding_contract_registry` /
        `bucket_binding_registry` 行字段 `granularity_declaration`
        （受控枚举 `{"building","fragment"}`，键缺省＝未声明）。
        **声明期＝只登记不消费**——本函数今天仍只跑上面那条隐式判据，
        判定面逐位不变（决策门 Q2 两段式第一步）。

        第二步（冻结点）在这里接：先查本卡的显式声明，**未声明即 fail-closed
        拒判**，隐式判据退役。接线时必须同批改完五处镜像
        （本函数、`blueprint_deriver._card_is_fragment_scoped`、
        `identity_blueprint_catalog._card_scopes`、`retrieval/pack_builder`
        的 `aggregation=="building"` 排除、`unknown_attribution` 同款排除）
        ——`closure/tests/test_granularity_declaration.py` 的
        `test_declaration_has_no_runtime_reader_in_declaration_period`
        会在第一个消费者接上时转红，那就是「五处一起改」的闸。
        """
        for ref in card.slot_role_map or []:
            sid = str(_safe_get(ref, "slot_id") or "")
            if _slot_domain.get(sid, "") in _FRAGMENT_DOMAINS:
                return True
        return False

    def _card_qualifier_values(card: Any, qkey: str) -> set:
        """卡引用的某限定符键并集（DEBT-050 扩展·件乙 spec 增补，qkey 泛化）。

        = 全 slot_role_map qualifiers（覆盖 trigger 经 slot_ref_id 引用的）
        ∪ 各 trigger item 自带 qualifiers 的 qkey（字符串值）。

        🔧 **DEBT-096 角色感知（2026-08-08 案甲，两线全票）**：slot_role_map 中
        roles ⊆ {evidence, prerequisite} 的槽其限定符**不参与整卡结构早退**（法理：
        evidence/prerequisite 不收窄卡适用；trigger/definition_reference 参与）。
        多角色（含 trigger 等）/未知角色（roles 空）缺省参与。trigger_conditions.items
        自带 qualifiers 不受此过滤（本就是 trigger 角色）。与
        `blueprint_deriver._card_qualifier_values` 逐字节同源（双径一致，见
        test_debt096_role_aware_qualifiers.py）。
        """
        vals: set = set()
        for ref in card.slot_role_map or []:
            roles = _safe_get(ref, "roles") or []
            if roles and set(roles) <= {"evidence", "prerequisite"}:
                continue
            q = _safe_get(ref, "qualifiers") or {}
            v = q.get(qkey) if isinstance(q, dict) else None
            if isinstance(v, str) and v:
                vals.add(v)
        for trig in (card.trigger_conditions or {}).get("items", []) or []:
            q = _safe_get(trig, "qualifiers") or {}
            v = q.get(qkey) if isinstance(q, dict) else None
            if isinstance(v, str) and v:
                vals.add(v)
        return vals

    def _card_component_types(card: Any) -> set:
        return _card_qualifier_values(card, "component_type_key")

    # 按 rule_card_id 稳定排序遍历（spec §6.6）。
    for card in sorted(
        rule_slice.candidate_rule_cards, key=lambda c: c.rule_card_id
    ):
        applicability = evaluate_applicability(
            card,
            fact_pack,
            subject_component_crosswalk=_subject_crosswalk,
            building_component_classes=building_component_classes,
        )

        # not_applicable：只生成 scope audit obligation，跳过本卡。
        if applicability.state == "not_applicable":
            obligations.append(
                make_scope_not_applicable(card, applicability, meta)
            )
            _reg.applicability(card, obligations[-1])
            continue

        # uncertain：生成 scope open obligation，继续推导其余义务。
        if applicability.state == "uncertain":
            obligations.append(make_scope_open(card, applicability, meta))
            _reg.applicability(card, obligations[-1])

        # fragment 承载卡逐 fragment 派生；楼级卡走 [None] 单趟（scope_meta=meta）。
        card_scopes: List[Optional[str]] = (
            list(fragment_ids)
            if fragment_ids and _card_is_fragment_scoped(card)
            else [None]
        )
        # DEBT-096 注：结构早退的 component 轴已改走 applicability_bundle（见下方
        # _ct_na 赋值段），_card_ct 当前无消费者（死变量）；保留以维持生成顺序不变，
        # 不删逻辑。location 轴仍消费 _card_lc。
        _card_ct = _card_component_types(card)
        _card_lc = _card_qualifier_values(card, "location_class_key")
        for scope_fid in card_scopes:
            scope_index = fact_index if scope_fid is None else _fragment_index(scope_fid)
            scope_meta = meta if scope_fid is None else {**meta, "fragment_id": scope_fid}

            # ---- fragment 级结构适用边界早退（DEBT-050 扩展·件乙，spec 增补）----
            # 卡的 component_type_key / location_class_key 限定与本 fragment 身份结构性
            # 无交集 → 整卡不适用于该 fragment（发 kind=scope 的 NA audit + 跳过本卡本
            # fragment 全部义务）。四条件护栏（codex 裁决，防误杀跨组件证据引用卡）：
            # ①卡限定集非空 ②scope 身份已知 ③卡值全在已知 canonical 宇宙（有未知值不
            # 早退，保守）④卡集 ∩ scope 相容集==∅。component 或 location 任一不可满足
            # 即早退（②location 维度扩展：location 无类目层级，直接值判）。
            _scope_ct = _scope_component_types(scope_fid)
            _scope_lc = _scope_location_classes(scope_fid)
            # DEBT-065 第一波:替换旧"词表空交=互斥"为 v2.2 §3.1 正向授权可证排斥——
            # 授权表取该卡单目标叶型,fragment 取单值 W0 身份,二者显式登记排斥才 NA。
            # 缺省拒绝:未授权/身份未知/非叶/未登记排斥 → 不早退(不产未证成 NA)。
            # DEBT-065 v3 §1.3:applicability_bundle 提供时走**单 bundle 编译式微小谓词**
            # (生产路径必传;身份与授权全部来自离线产出、精确 digest 钉住的 bundle,
            #  runtime 不查授权表、不重建身份、不匹配指纹)。
            # 未提供 bundle 时回落 v2.2 判据——**仅为未迁移单测的过渡路径**,
            # 按 v3 §0.1 在发布门禁全过后删除,不得视为正式实现。
            if applicability_bundle is not None:
                _v3_na, _ = applicability_bundle.early_exit(card.rule_card_id, scope_fid)
                _ct_na = bool(_v3_na)
                _auth_target = applicability_bundle.card_targets.get(card.rule_card_id)
                _w0_identity = (
                    applicability_bundle.fragment_identities.get(scope_fid) if scope_fid else None
                )
            else:
                # v3 §0.1 双轨清理:v2.2 运行时组装路径(policy 授权表 + 事实身份通道)已删除。
                # 无 bundle → 一律不早退(fail-safe),不再回落任何旧判据。
                _ct_na = False
                _auth_target = None
                _w0_identity = None
            _lc_na = (
                _card_lc and _scope_lc is not None and _card_lc <= _known_lc
                and not (_card_lc & set(_scope_lc))
            )
            if scope_fid is not None and (_ct_na or _lc_na):
                _reason = (
                    f"authorized target {_auth_target} vs fragment identity "
                    f"{_w0_identity} provably disjoint" if _ct_na else
                    f"location_class_key {sorted(_card_lc)} vs fragment "
                    f"locations {sorted(_scope_lc or [])}"
                )
                obligations.append(make_scope_not_applicable(
                    card,
                    ApplicabilityResult(
                        state="not_applicable",
                        reasons=[
                            "structurally_unsatisfiable_card_scope: card "
                            + _reason + " incompatible"
                        ],
                    ),
                    scope_meta,
                ))
                _reg.structural_audit(card, obligations[-1], scope_fid)
                continue

            # ---- triggers ----
            trigger_conditions = card.trigger_conditions or {}
            trigger_items = trigger_conditions.get("items", []) or []
            trigger_results: List[Obligation] = []
            # 丁（DEBT-083 裁决新增方案）基建：本 (卡, 作用域) 内
            # slot_ref_id → 真触发器义务 映射 + 被 trigger_conditions 引用的
            # slot_ref_id 集，供槽角色循环消灭双轨求值（见下方 slot roles）。
            # 值语义：Obligation=唯一真触发器；None=同 ref 多触发项（护栏①显式阻断）。
            _trigger_by_slot_ref: Dict[str, Optional[Obligation]] = {}
            _trigger_ref_ids = {
                str(_safe_get(t, "slot_ref_id") or "")
                for t in trigger_items
                if _safe_get(t, "slot_ref_id")
            }
            for trigger in sorted(
                trigger_items, key=lambda x: str(_safe_get(x, "condition_id"))
            ):
                obl = evaluate_trigger(
                    card, dict(trigger), scope_index, scope_meta,
                    measure_aliases=measure_aliases,
                    scope_component_types=_scope_component_types(scope_fid),
                    known_component_types=_known_ct,
                    scope_location_classes=_scope_location_classes(scope_fid),
                    known_location_classes=_known_lc,
                    # v3 §1.3.1:触发器级与卡级共用同一数据源(bundle),不再走 policy 授权表
                    # 与事实身份通道;无 bundle 时三者为空 → 触发器级同样一律不早退。
                    auth_target=(
                        applicability_bundle.card_targets.get(card.rule_card_id)
                        if applicability_bundle is not None else None
                    ),
                    w0_identity=(
                        applicability_bundle.fragment_identities.get(scope_fid)
                        if applicability_bundle is not None and scope_fid else None
                    ),
                    lattice_disjoint=(
                        applicability_bundle.disjoint_pairs
                        if applicability_bundle is not None else frozenset()
                    ),
                    ct_disjoint_na_relaxed=trigger_ct_disjoint_na,
                    # DEBT-081 六字段正向授权（bundle 第四成员；缺省空=逐位不变）。
                    trigger_na_authorizations=(
                        applicability_bundle.trigger_na_authorizations
                        if applicability_bundle is not None else None
                    ),
                    w0_raw_type=(
                        applicability_bundle.fragment_raw_types.get(scope_fid)
                        if applicability_bundle is not None and scope_fid else None
                    ),
                )
                obligations.append(obl)
                trigger_results.append(obl)
                _reg.trigger(card, obl, dict(trigger), scope_fid)
                # 记录 (card_id, condition_id, fragment) → trigger obligation 引用。
                condition_id = str(_safe_get(trigger, "condition_id") or "")
                if condition_id:
                    trigger_provenance[
                        (card.rule_card_id, condition_id, scope_fid or "")
                    ] = obl
                # 丁护栏①（2026-08-02 codex 终审）：同 slot_ref_id 对应多个触发项时
                # **显式阻断镜像**，不许静默取排序首个——多义时记 None 哨兵，
                # 槽角色循环见 None 即打 schema_contract_violation。
                # （现网 470 卡/423 触发器槽引用重复数为 0，本护栏防未来卡包演化。）
                _t_sr = str(_safe_get(trigger, "slot_ref_id") or "")
                if _t_sr:
                    if _t_sr in _trigger_by_slot_ref:
                        _trigger_by_slot_ref[_t_sr] = None
                    else:
                        _trigger_by_slot_ref[_t_sr] = obl

            trigger_active = aggregate_trigger_logic(
                trigger_conditions.get("logic", "all"), trigger_results
            )

            # trigger 聚合 false：生成 not_applicable audit，跳过本作用域 action 义务。
            if trigger_active is False:
                obligations.append(
                    make_rule_not_applicable_by_trigger(
                        card, trigger_results, scope_meta
                    )
                )
                _reg.trigger_agg_audit(card, obligations[-1], scope_fid)
                continue

            # ---- slot roles ----
            for slot_ref in sorted(
                card.slot_role_map or [],
                key=lambda x: str(_safe_get(x, "slot_ref_id")),
            ):
                if _safe_get(slot_ref, "required"):
                    # 二轮审核门纠正：通用聚合护栏**只豁免一致性镜像副本**，
                    # 不按 kind 整类豁免（真触发器仍须受授权边界约束）。
                    # 镜像标记在求值之后才写进 notes，故判据必须在此**前置计算**
                    # 并传入——与下方 `_slot_obl` 镜像覆盖的条件严格同源，
                    # 两处任一改动都必须同改（漂移会让豁免面与实际镜像面不一致）。
                    # 🔴 判据必须与下方**实际发生镜像覆盖**的那一支严格等价：
                    # 不只是「slot_ref 被 trigger_conditions 引用」，还必须
                    # **真能取到来源触发器**（`_src is not None`）。
                    # 首版漏了后半条 ⇒ 引用了但取不到来源的那批（走下方
                    # `dual_track_multi_trigger_ref` 阻断支、或根本没有来源项）
                    # 被护栏豁免却拿不到镜像标记，实测在批 I 上放过 938 条
                    # 触发器实判（530 派生行 + 408 原生 procedure_gate_state）。
                    _sr_id_pre = str(_safe_get(slot_ref, "slot_ref_id") or "")
                    _mirror_now = bool(
                        exclude_fallback_reasons_facts
                        and trigger_active is True
                        and "trigger" in (_safe_get(slot_ref, "roles") or [])
                        and _sr_id_pre in _trigger_ref_ids
                        and _trigger_by_slot_ref.get(_sr_id_pre) is not None
                    )
                    _slot_obl = evaluate_slot_role(
                        card, dict(slot_ref), scope_index, trigger_active,
                        scope_meta,
                        authorized_scope_selection=authorized_scope_selection,
                        is_consistency_mirror=_mirror_now,
                    )
                    # 丁（DEBT-083 裁决新增方案，2026-08-02；同挂
                    # `exclude_fallback_reasons_facts` 既有开关，缺省关闭＝逐位不变）：
                    # roles 含 "trigger" 且 slot_ref_id 被本卡 trigger_conditions.items[]
                    # 引用的槽角色义务，不再独立走「存在即满足」，改为镜像同
                    # (卡, slot_ref_id, 作用域) 真触发器义务的求值结果——消除
                    # 「真触发器判不适用、槽角色副本判满足」的双轨。
                    # 仅在 trigger_active is True 时镜像：open/blocked 聚合下槽角色
                    # 已统一走继承通道，镜像只会撞 depends_on_open_trigger 契约。
                    # open/blocked 原因码一并镜像（契约一致性：闭包三态与原因码
                    # 联动校验），kind 与其余身份字段保持原样。
                    if exclude_fallback_reasons_facts and trigger_active is True:
                        _sr_roles = _safe_get(slot_ref, "roles") or []
                        _sr_id = str(_safe_get(slot_ref, "slot_ref_id") or "")
                        if (
                            "trigger" in _sr_roles
                            and _sr_id
                            and _sr_id in _trigger_ref_ids
                        ):
                            _src = _trigger_by_slot_ref.get(_sr_id)
                            if _src is not None:
                                _slot_obl = _slot_obl.model_copy(update={
                                    "closure_status": _src.closure_status,
                                    "satisfaction_status": _src.satisfaction_status,
                                    "operator": _src.operator,
                                    "expected_value_json": _src.expected_value_json,
                                    "comparator_result": _src.comparator_result,
                                    "evidence_fact_ids": list(_src.evidence_fact_ids),
                                    "open_reason_code": _src.open_reason_code,
                                    "blocked_reason_code": _src.blocked_reason_code,
                                    # 丁护栏②（codex 终审）：镜像副本记来源触发器
                                    # ——消费者/报告据此折叠或标「一致性副本」，
                                    # 不把镜像当独立法规判断重复计数。
                                    # ⚠️ 引用键用 (卡内唯一的) slot_ref 而非义务号：
                                    # 义务号在 v5 去重时会按身份重算，预去重号在
                                    # 产物里解析不到（实测踩过）。护栏①保证同 ref
                                    # 唯一，故 `卡+kind=trigger+同 slot_ref+同作用域`
                                    # 可唯一定位来源。
                                    "notes": (
                                        _slot_obl.notes
                                        + "; consistency_mirror_of="
                                        + f"trigger_slot_ref:{_sr_id}"
                                    ).strip("; "),
                                })
                            elif _sr_id in _trigger_by_slot_ref:
                                # 丁护栏①：同 slot_ref_id 多触发项 → 显式阻断，
                                # 绝不静默取第一个。
                                _slot_obl = _slot_obl.model_copy(update={
                                    "closure_status": "blocked",
                                    "satisfaction_status": "unknown",
                                    "blocked_reason_code": "schema_contract_violation",
                                    "open_reason_code": None,
                                    "notes": (
                                        _slot_obl.notes
                                        + "; dual_track_multi_trigger_ref"
                                    ).strip("; "),
                                })
                            else:
                                # 结构上不该发生（每个触发项必产义务）——
                                # fail-visible 不 fail-open：保持旧行为并记 notes。
                                _slot_obl = _slot_obl.model_copy(update={
                                    "notes": (
                                        _slot_obl.notes + "; dual_track_reuse_miss"
                                    ).strip("; "),
                                })
                    obligations.append(_slot_obl)
                    _reg.slot_role(card, obligations[-1], dict(slot_ref), scope_fid)

            # ---- thresholds ----
            for threshold in sorted(
                card.threshold_regimes or [],
                key=lambda x: str(_safe_get(x, "threshold_regime_id")),
            ):
                obligations.append(
                    evaluate_threshold(
                        card,
                        dict(threshold),
                        scope_index,
                        trigger_active,
                        scope_meta,
                        measure_aliases,
                    )
                )
                _reg.threshold(card, obligations[-1], dict(threshold), scope_fid)

            # ---- obligation_graph nodes ----
            node_obligations: Dict[str, List[Obligation]] = {}
            nodes = (card.obligation_graph or {}).get("nodes", []) or []
            for raw_node in sorted(
                nodes, key=lambda x: str(_safe_get(x, "obligation_node_id"))
            ):
                node_dto = ObligationNodeDTO.from_dict(dict(raw_node))
                _ntoks: List[Any] = []
                node_out = evaluate_obligation_node(
                    card, node_dto, scope_index, trigger_active, scope_meta,
                    source_sink=_ntoks,
                    authorized_scope_selection=authorized_scope_selection,
                )
                obligations.extend(node_out)
                node_obligations[node_dto.obligation_node_id] = node_out
                _reg.fanout(card, node_out, _ntoks, scope_fid)

            # ---- obligation_graph edges ----
            edges = (card.obligation_graph or {}).get("edges", []) or []
            _etoks: List[Any] = []
            edge_obligations = evaluate_obligation_edges(
                card, edges, node_obligations, scope_index, scope_meta,
                source_sink=_etoks,
            )
            obligations.extend(edge_obligations)
            _reg.fanout(card, edge_obligations, _etoks, scope_fid)

            # ---- workflow_operands.artifacts ----
            _atoks: List[Any] = []
            wf_artifacts = derive_workflow_artifact_obligations(
                card, scope_index, trigger_active, scope_meta, source_sink=_atoks
            )
            obligations.extend(wf_artifacts)
            _reg.fanout(card, wf_artifacts, _atoks, scope_fid)

            # ---- workflow_operands.deadlines ----
            _dtoks: List[Any] = []
            wf_deadlines = derive_workflow_deadline_obligations(
                card, scope_index, trigger_active, scope_meta, source_sink=_dtoks
            )
            obligations.extend(wf_deadlines)
            _reg.fanout(card, wf_deadlines, _dtoks, scope_fid)

            # ---- evidence_requirements（三 bucket 全消费）----
            evidence_reqs = card.evidence_requirements or {}
            for bucket_name in sorted(evidence_reqs.keys()):
                reqs = evidence_reqs.get(bucket_name) or []
                if not isinstance(reqs, list):
                    continue
                for req in sorted(
                    reqs, key=lambda x: str(_safe_get(x, "evidence_requirement_id"))
                ):
                    if _safe_get(req, "required", default=True):
                        obligations.append(
                            evaluate_evidence_requirement(
                                card,
                                bucket_name,
                                dict(req),
                                scope_index,
                                trigger_active,
                                scope_meta,
                                authorized_scope_selection=(
                                    authorized_scope_selection),
                            )
                        )
                        _reg.evidence(card, obligations[-1], dict(req), scope_fid)

            # ---- exceptions ----
            for exc in sorted(
                card.exceptions or [], key=lambda x: _stable_json_key(x)
            ):
                obligations.append(
                    evaluate_exception(card, dict(exc), scope_index, scope_meta)
                )
                _reg.exception(card, obligations[-1], dict(exc), scope_fid)

            # ---- definitions ----
            for definition in sorted(
                card.definitions or [], key=lambda x: _stable_json_key(x)
            ):
                obligations.append(
                    evaluate_definition(card, dict(definition), scope_index, scope_meta)
                )
                _reg.definition(card, obligations[-1], dict(definition), scope_fid)

    # ---- identity-v5 活动键绑定（现网键切换增补 §6）----
    # 每条 pre-dedup 义务经来源令牌五元组绑定 catalog 蓝图（BoundObligation）；bind_sink 与 obligations
    # 逐 append 同序对齐（每条义务恰一登记），数不等 → hard-fail `unbound_live_obligation`。
    if len(bind_sink) != len(obligations):
        raise ObligationContractError(
            f"unbound_live_obligation:{len(obligations)}!={len(bind_sink)}"
        )
    bound: List[BoundObligation] = []
    for obl, key in bind_sink:
        bp = identity_blueprint_catalog.require(key)  # 未命中 → blueprint_association_miss（= unbound 前置拦截，不 fail-open）
        bound.append(BoundObligation(obligation=obl, blueprint=bp))

    # 供影子对账捕获 pre-dedup 绑定多重集（深拷贝快照，与后续原地 dedup/backfill 隔离，判定结果字节不变）。
    if pre_dedup_out is not None:
        for b in bound:
            pre_dedup_out.append(
                BoundObligation(
                    obligation=b.obligation.model_copy(deep=True),
                    blueprint=b.blueprint,
                )
            )

    # ---- sort / dedupe（v5 只换键：canonical_identity_hash 分组、状态仍走 v1 _merge_two）----
    obligations, identity_manifest = sort_and_dedupe_obligations(bound)

    # ---- 全集碰撞后置检查（§6.3 步 7，作用域=整个 ObligationSet）----
    run_envelope = RunInstanceEnvelope(
        run_id=fact_pack.run_id,
        world_id=fact_pack.world_id,
        building_id=fact_pack.building_id,
    )
    run_collision_postcheck_live(identity_manifest, run_envelope)

    # ---- trigger_dependency_ids 二次回填 pass（spec §6.3.3）----
    # sort_and_dedupe 后 obligation_id 落定，把下游 obligation 的
    # trigger_dependency_ids 从 trigger_condition_id / 占位 解析成运行时
    # trigger obligation_id。compute_obligation_id（v5：身份+信封派生）不依赖
    # trigger_dependency_ids，所以此处改字段不破坏 id 稳定性。
    backfill_trigger_dependency_ids(obligations, trigger_provenance)

    summary = summarize(
        obligations,
        guard_result=config.guard_result,
        schema_validation_passed=schema_validation_passed,
    )

    obligation_set = ObligationSet(
        obligation_set_id=_obligation_set_id(fact_pack.run_id),
        run_id=fact_pack.run_id,
        world_id=fact_pack.world_id,
        building_id=fact_pack.building_id,
        created_at=_utc_now(),
        rulecard_bundle_id=rule_slice.rulecard_bundle_id,
        verifier_version=config.verifier_version,
        obligations=obligations,
        # identity-v5 版本/身份字段（现网键切换增补 §4.2；从实际去重产物抄录）。
        obligation_set_schema="obligation_set_v2",
        obligation_identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        identity_key_policy="canonical_identity_hash",
        identity_manifest=identity_manifest,
        derivation_policy={
            "generation_order": [
                "applicability",
                "triggers",
                "slot_roles",
                "thresholds",
                "obligation_graph_nodes",
                "obligation_graph_edges",
                "workflow_artifacts",
                "evidence_requirements",
                "exceptions",
                "definitions",
                "sort_dedupe",
            ],
            "spec_section": "6.3 / 6.6",
            "deterministic": True,
        },
    )

    machine_report = build_machine_report(
        obligations,
        summary,
        run_id=fact_pack.run_id,
        world_id=fact_pack.world_id,
        building_id=fact_pack.building_id,
    )

    # ---- v1 §6.2 instrumentation：4 hash + skill provenance ----
    # verifier candidate universe：本次实际进入 closure 的 rule_card_id 全集
    # （由 RuleSlice.candidate_rule_cards 投影而来；与 retrieval 侧 verifier
    # floor 是同一全集，但本入口不依赖 retrieval，直接基于送入的 RuleSlice）。
    used_card_ids = sorted(
        {c.rule_card_id for c in rule_slice.candidate_rule_cards}
    )
    candidate_universe_hash = compute_candidate_universe_hash(used_card_ids)
    fact_pack_hash = compute_fact_pack_hash(fact_pack)
    rule_slice_hash = compute_rule_slice_hash(rule_slice)
    skill_inv_ids = sorted(set(skill_invocation_ids or []))

    # 不变量校验：spec v1 §6.3 + §6.5 —— Skill/Policy 不影响 verifier authority
    verifier_authority_check = {
        "allow_stop_owned_by_verifier": True,
        "closure_status_owned_by_verifier": True,
        "satisfaction_status_owned_by_verifier": True,
        # 任何 skill_invocation_ids 都不应影响 allow_stop 公式（spec v1 §6.3）
        "skill_invocation_count": len(skill_inv_ids),
        "policy_version_id_recorded": policy_version_id,
    }

    machine_report["skill_invocation_ids"] = skill_inv_ids
    machine_report["candidate_universe_hash"] = candidate_universe_hash
    machine_report["fact_pack_hash"] = fact_pack_hash
    machine_report["rule_slice_hash"] = rule_slice_hash
    # DEBT-079：上面两个含 `run_id`，跨运行永远不等；下面两个才是跨批对账锚。
    machine_report["fact_pack_content_hash"] = compute_fact_pack_content_hash(fact_pack)
    machine_report["rule_slice_content_hash"] = compute_rule_slice_content_hash(rule_slice)
    machine_report["skill_augmented_retrieval_used"] = bool(skill_inv_ids)
    machine_report["policy_version_id"] = policy_version_id
    machine_report["verifier_authority_check"] = verifier_authority_check
    machine_report["verifier_candidate_floor_passed"] = True
    machine_report["source_visibility_audit_passed"] = True
    machine_report["skill_policy_non_authority_passed"] = True

    # ---- identity-v5 run_audit（现网键切换增补 §7 原子版本传播）----
    # 版本/身份 4 字段**从产出的 ObligationSet 实例抄录**（非常量重写）——run_audit 与容器身份
    # 版本原子一致，杜绝二者独立写值漂移；catalog sha256 从 catalog 抄录；unbound=0 /
    # collision_postcheck=True / legacy_v1_key_used=False 是本入口到此处的运行不变量
    # （require() 未命中即 hard-fail、run_collision_postcheck_live 已过、活动键=v5）。
    # ---- unknown 归因旁路（判定权红线：**在 summarize / allow_stop 之后**）----
    # 归因只读、只产旁路映射；策略异常一律降级为报警兜底，判定面逐字不动。
    unknown_attr_map, unknown_attr_audit = _compute_unknown_attribution_isolated(
        obligations, fact_pack, rule_slice, fact_index, _fact_frag
    )
    machine_report["unknown_attribution_audit"] = unknown_attr_audit

    machine_report["run_audit"] = {
        "obligation_set_schema": obligation_set.obligation_set_schema,
        "obligation_identity_schema": obligation_set.obligation_identity_schema,
        "canonical_profile_id": obligation_set.canonical_profile_id,
        "identity_catalog_sha256": identity_blueprint_catalog.identity_catalog_sha256,
        "identity_key_policy": obligation_set.identity_key_policy,
        "identity_binding_unbound_count": 0,
        "identity_collision_postcheck_passed": True,
        "legacy_v1_key_used": False,
    }

    return ClosureValidationResult(
        run_id=fact_pack.run_id,
        obligation_set=obligation_set,
        closure_summary=summary,
        allow_stop=summary.allow_stop,
        allow_report_generation=summary.allow_stop,  # §6.5.3
        high_risk_items=find_high_risk_items(obligations),
        machine_readable_report=machine_report,
        unknown_attribution_by_obligation_id=unknown_attr_map,
    )


# ===================================================================== #
# 内部小工具
# ===================================================================== #
def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """从 dict 或对象安全取属性（rule_card 子结构可能是 dict）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stable_json_key(obj: Any) -> str:
    """对 dict / 任意结构生成稳定排序键（spec §6.6 stable_json_key）。"""
    import json

    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


def _utc_now() -> str:
    """ISO8601 UTC 时间串（ObligationSet.created_at 用）。"""
    return datetime.now(timezone.utc).isoformat()


def _obligation_set_id(run_id: str) -> str:
    """ObligationSet id（确定性：从 run_id 派生，保证可复现）。"""
    h = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    return f"OBLSET-{h}"


__all__ = [
    "validate_building_closure",
    "assert_no_forbidden_sources",
    "ForbiddenSourceError",
    # identity-v5 活动键（现网键切换增补 §6.1/§6.3；收 BoundObligation）
    "compute_obligation_id",
    "dedupe_key",
    "sort_and_dedupe_obligations",
    "run_collision_postcheck_live",
    # v1 只读键（现网键切换增补 §6.2；不接活路径，供旧产物重算 / 影子对账 v1 基线）
    "compute_obligation_id_v1",
    "dedupe_key_v1",
    "assign_obligation_ids_v1",
    "sort_and_dedupe_obligations_v1",
    "display_obligation_id",
    "sort_key",
    "find_high_risk_items",
    "summarize",
    "compute_allow_stop_and_reason",
    "build_machine_report",
    "compute_fact_pack_hash",
    "compute_fact_pack_content_hash",
    "compute_rule_slice_content_hash",
    "compute_rule_slice_hash",
    "compute_candidate_universe_hash",
    "FORBIDDEN_PROPERTY_NAMES",
    "FORBIDDEN_SOURCE_TOKENS",
]
