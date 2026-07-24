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
from typing import Any, Dict, List, Optional, Tuple

from canonical_profile import CANONICAL_PROFILE_ID, canonical_json

from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    FactPack,
    Obligation,
    ObligationSet,
    RuleSlice,
)

from .applicability import evaluate_applicability
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


def _normalize_alias_map(aliases: Any) -> Dict[str, str]:
    """别名表归一为 {orig: canonical} 单值映射。

    DEBT-040 修复：projection_runtime_mapping_v1 的值是**列表**（如
    `{"repair.prescribed.started": ["procedure.repair.prescribed.started"]}`），
    旧实现 `str(v)` 会把列表搅成 "['procedure...']" 垃圾键、canonical 查找必 miss。
    这里 str 直取、list 取首个非空 str（v1 实际均为单元素列表；多元素取首并忽略其余，
    与 canonical_slot 单值语义一致）。
    """
    if not isinstance(aliases, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in aliases.items():
        canon: Optional[str] = None
        if isinstance(v, str) and v:
            canon = v
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item:
                    canon = item
                    break
        if canon is not None:
            out[str(k)] = canon
    return out


def _measure_aliases_from_policy(rule_slice: RuleSlice) -> Dict[str, str]:
    """从 retrieval_policy 取 projection_runtime_mapping_v1.measure_aliases。

    spec §6.3.5 fact binding 第 2 级用此别名表。policy 无此键时返回空。
    """
    policy = rule_slice.retrieval_policy or {}
    mapping = policy.get("projection_runtime_mapping_v1") or {}
    return _normalize_alias_map(mapping.get("measure_aliases") or {})


def _slot_aliases_from_policy(rule_slice: RuleSlice) -> Dict[str, str]:
    """从 retrieval_policy 取 slot_aliases（spec §6.4.2 canonical_slot 用）。

    合并语义（codex 评审硬化）：mapping 的 slot_aliases 为基底，policy 顶层
    `slot_aliases` 按键覆盖——不再"顶层非空即整表遮蔽 mapping"（那会让新映射静默失效）。
    """
    policy = rule_slice.retrieval_policy or {}
    mapping = policy.get("projection_runtime_mapping_v1") or {}
    merged: Dict[str, Any] = {}
    if isinstance(mapping.get("slot_aliases"), dict):
        merged.update(mapping["slot_aliases"])
    top_level = policy.get("slot_aliases")
    if isinstance(top_level, dict):
        merged.update(top_level)
    return _normalize_alias_map(merged)


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


def validate_building_closure(
    rule_slice: RuleSlice,
    fact_pack: FactPack,
    config: Optional[VerifierConfig] = None,
    *,
    identity_blueprint_catalog: IdentityBlueprintCatalog,
    skill_invocation_ids: Optional[List[str]] = None,
    policy_version_id: Optional[str] = None,
    pre_dedup_out: Optional[List[BoundObligation]] = None,
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
    fact_index = FactIndex(
        fact_pack,
        slot_aliases=slot_aliases,
        measure_aliases=measure_aliases,
        method_aliases=method_aliases,
        numeric_tolerance=config.numeric_tolerance,
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
    building_component_classes: set = set()
    for _f in fact_pack.facts:
        if _f.slot_id == "component_type":
            try:
                _v = json.loads(_f.value_json)
            except (TypeError, ValueError):
                _v = None
            if isinstance(_v, str) and _v:
                _canon = _ct_value_alias.get(_v)
                building_component_classes.add(
                    _canon if isinstance(_canon, str) and _canon else _v
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
            )
        return _frag_index_cache[fid]

    def _card_is_fragment_scoped(card: Any) -> bool:
        for ref in card.slot_role_map or []:
            sid = str(_safe_get(ref, "slot_id") or "")
            if _slot_domain.get(sid, "") in _FRAGMENT_DOMAINS:
                return True
        return False

    def _card_qualifier_values(card: Any, qkey: str) -> set:
        """卡引用的某限定符键并集（DEBT-050 扩展·件乙 spec 增补，qkey 泛化）。

        = 全 slot_role_map qualifiers（覆盖 trigger 经 slot_ref_id 引用的）
        ∪ 各 trigger item 自带 qualifiers 的 qkey（字符串值）。
        """
        vals: set = set()
        for ref in card.slot_role_map or []:
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
            _auth_target = _auth_targets.get(card.rule_card_id)
            _w0_identity = _w0_fragment_identity(scope_fid)
            _ct_na = (
                _auth_target is not None
                and _w0_identity is not None
                and _provable_disjoint(_auth_target, _w0_identity)
            )
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
                    auth_target=_auth_targets.get(card.rule_card_id),
                    w0_identity=_w0_fragment_identity(scope_fid),
                    lattice_disjoint=_lattice_disjoint,
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
                    obligations.append(
                        evaluate_slot_role(
                            card, dict(slot_ref), scope_index, trigger_active,
                            scope_meta,
                        )
                    )
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
    "compute_rule_slice_hash",
    "compute_candidate_universe_hash",
    "FORBIDDEN_PROPERTY_NAMES",
    "FORBIDDEN_SOURCE_TOKENS",
]
