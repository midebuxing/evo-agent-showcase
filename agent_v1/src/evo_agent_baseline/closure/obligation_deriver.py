"""义务推导 —— spec §6.3.3 ~ §6.3.10。

各义务源 → Obligation 的确定性推导：
- §6.3.3 trigger obligations + aggregate_trigger_logic
- §6.3.4 slot role obligations + qualifiers_match
- §6.3.5 threshold obligations（评估逻辑在 threshold_eval.py）
- §6.3.6 artifact / evidence obligations + [v0.4-C-1] artifact alias map
- §6.3.7 deadline obligations
- §6.3.8 exception obligations
- §6.3.9 definition obligations
- §6.3.10 obligation_graph nodes + edges

确定性、无 LLM、无 Neo4j。obligation_id 由 validator 在落库前统一回填，本模块
构造 Obligation 时先用占位 id（validator.assign_obligation_ids 重写）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from evo_agent_baseline.contracts import FactAtom, Obligation, RuleCardDTO

from .fact_binding import FactIndex, conflict_status, parse_value
from .schema import ObligationEdgeDTO, ObligationNodeDTO
from .threshold_eval import (
    bind_measure,
    evaluate_threshold_comparison,
)

# 构造期占位 obligation_id；validator 落库前用确定性 hash 重写。
_PLACEHOLDER_OID = "PENDING"


class SourceToken(NamedTuple):
    """扁平化前来源令牌（identity-v5 现网键切换增补 §1.2/§1.4）——node/edge 求值器内部在「正在处理
    哪个源项」处**旁路登记**，供关联层按五元组从 catalog 取蓝图、组 `BoundObligation`。

    **纯旁路红线（§1.3）**：登记**不改**返回 v1 `Obligation` 字节、**不参与**任何状态判断、
    **不进** `evaluate_*` 判定分支——`source_sink=None`（默认，即现网 live 路径）时零副作用、
    产物 byte-identical。`primary_id` 为**原始源标识**（node_id / artifact_id / deadline_id /
    edge_id / target_node_id，未编码 SID）；SID 编码由关联层做（与 blueprint 侧同一编码，杜绝反推/漂移）。

    **fail-closed 完备令牌（§1.4，codex 阻断 2 修订）**：令牌**自携**关联所需全部维度——
    `scope_fid`（求值时冻结 scope，None=building）、`channel`（参与键构造、须 ↔ role 规范映射一致）、
    `member`/`edge_ids`（edge 分身/聚合判别）；关联层按令牌自身确定五元组，**调用者不得自由补 scope**。

    `role` discriminator（消 obligation_graph channel 内 node/method/edge 歧义）：
      node          —— node-level 主义务（out[0]）
      method        —— method-derivation 子义务（可分 → 独立 method-derived 身份；不可分 → 折回 node-main）
      edge_dangling —— 悬空 edge 审计（source ∨ target node 缺失，§3.4.3）
      edge_unknown  —— 未知 relation 分身审计（member=source/target，§3.4.3）
      edge_inactive —— inactive-target 聚合审计（edge_ids=完整排序集，§3.4.3）
      artifact      —— node 内 artifact 子义务（由 workflow_artifact channel 承载，§1.2）
      deadline      —— node 内 deadline 子义务（由 workflow_deadline channel 承载，§1.2）
    """

    channel: str
    primary_id: str
    role: str
    scope_fid: Optional[str]          # §1.4 冻结 scope（求值时 fragment_id；None=building）
    member: str = ""                  # edge_unknown 分身判别（"source"/"target"），其它 ""
    edge_ids: Tuple[str, ...] = ()    # edge_inactive 聚合完整排序集，其它 ()


# ===================================================================== #
# §6.3.6 [v0.4-C-1] artifact alias map（收口版）
# ===================================================================== #
# 17 个精确绑定 —— 每个 artifact_key 独占一个 sidecar slot，slot 互不共享。
ARTIFACT_KEY_TO_SIDECAR_SLOT: Dict[str, str] = {
    "certificate.material_compliance": "artifact.certificate.material_or_product",
    "drawing.annotated_location_plan": "artifact.plan.annotated",
    "form.mbi3_or_mbi3a": "artifact.form.mbi3_or_mbi3a",
    "form.mbi4": "artifact.form.mbi4",
    "form.mbi5": "artifact.form.mbi5",
    "notice.detailed_investigation_intention": "artifact.notice.investigation_intention",
    "photo.annotated_defect": "artifact.photo.annotated",
    "proposal.detailed_investigation": "artifact.proposal.detailed_investigation",
    "proposal.repair": "artifact.proposal.repair",
    "proposal.repair_revision": "artifact.proposal.repair_revision",
    "record.inspection_log": "artifact.record.inspection_log",
    "record.nonconformity_correction_sp2": "artifact.record.nonconformity_sp2",
    "report.completion": "artifact.report.completion",
    "report.inspection": "artifact.report.inspection",
    "report.test_result": "artifact.record.test_or_material_witness",
    "statement.mbis_repairs_separated_from_additional_upgrades": "artifact.statement.extra_works_separated",
    "statement.outstanding_order_scope_included": "artifact.statement.scope_and_order_coverage",
}

# 8 个无专属 slot —— 与他人共用 slot，sidecar 无 artifact_key 限定词无法消歧，
# 一律判 blocked + artifact_not_modeled_upstream，不桥接、不假 satisfied。
ARTIFACT_KEYS_NOT_MODELED: set = {
    "notice.representative_appointment_intended",
    "notice.ri_appointment",
    "notice.ri_cessation",
    "notice.ri_temporary_nomination",
    "notice.temporary_ri_nomination_cessation",
    "proposal.supervision",
    "record.site_visit_log",
    "record.supervision_checklist",
}

# W0_09 §5.2 sidecar artifact.* slot（实测 20 个）—— resolve_artifact_slot 安全断言用。
W0_09_ARTIFACT_SLOTS: set = {
    "artifact.certificate.material_or_product",
    "artifact.form.mbi1",
    "artifact.form.mbi2",
    "artifact.form.mbi3_or_mbi3a",
    "artifact.form.mbi4",
    "artifact.form.mbi5",
    "artifact.notice.investigation_intention",
    "artifact.photo.annotated",
    "artifact.plan.annotated",
    "artifact.proposal.detailed_investigation",
    "artifact.proposal.repair",
    "artifact.proposal.repair_revision",
    "artifact.record.inspection_log",
    "artifact.record.nonconformity_sp2",
    "artifact.record.supervision_log_sp1",
    "artifact.record.test_or_material_witness",
    "artifact.report.completion",
    "artifact.report.inspection",
    "artifact.statement.extra_works_separated",
    "artifact.statement.scope_and_order_coverage",
}

# 全量 25 个 artifact_key（17 + 8）—— resolve_artifact_slot 用来识别「未登记新 key」。
_KNOWN_ARTIFACT_KEYS: set = set(ARTIFACT_KEY_TO_SIDECAR_SLOT) | ARTIFACT_KEYS_NOT_MODELED

# §6.3.6 truthy / falsy canonicalization。
TRUTHY_VALUES: set = {
    True,
    "true",
    "present",
    "submitted",
    "delivered",
    "completed",
    "available",
    "yes",
}
FALSY_VALUES: set = {
    False,
    "false",
    "absent",
    "missing",
    "not_submitted",
    "no",
}

# ---- spec §6.3.6 收口规则的内部一致性断言（import 时即校验）----
assert len(ARTIFACT_KEY_TO_SIDECAR_SLOT) == 17, "must be 17 precise bindings"
assert len(ARTIFACT_KEYS_NOT_MODELED) == 8, "must be 8 not-modeled keys"
assert (
    set(ARTIFACT_KEY_TO_SIDECAR_SLOT) & ARTIFACT_KEYS_NOT_MODELED == set()
), "two groups must be disjoint"
assert (
    len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values())) == 17
), "each slot bound by at most one key"
assert (
    set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values()) <= W0_09_ARTIFACT_SLOTS
), "all binding targets must be real W0_09 artifact slots"
assert (
    "form.mbi1" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
    and "form.mbi2" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
), "form.mbi1/mbi2 are sidecar slots without artifact_key, must not be in map"


class SchemaContractError(Exception):
    """rule_card 出现 spec 未登记的结构（spec §6.3.6 resolve_artifact_slot）。"""


def resolve_artifact_slot(artifact_key: str) -> Optional[str]:
    """artifact_key → sidecar slot（spec §6.3.6 resolve_artifact_slot）。

    - 在精确绑定 map 内 → 返回 slot
    - 在 NOT_MODELED 内 → 返回 None（上层判 blocked + artifact_not_modeled_upstream）
    - 既不在 map 也不在 NOT_MODELED → 抛 SchemaContractError（未登记新 key）

    禁止 prefix fallback。
    """
    if artifact_key in ARTIFACT_KEY_TO_SIDECAR_SLOT:
        return ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]
    if artifact_key in ARTIFACT_KEYS_NOT_MODELED:
        return None
    raise SchemaContractError(
        f"unknown artifact_key {artifact_key!r} — rule_card 出现 spec 未登记的新 key"
    )


def _canon_truthy(value: Any) -> Optional[bool]:
    """artifact value canonicalization → True / False / None（无法判定）。"""
    if isinstance(value, str):
        v: Any = value.strip().lower()
    else:
        v = value
    if v in TRUTHY_VALUES or v is True:
        return True
    if v in FALSY_VALUES or v is False:
        return False
    return None


# ===================================================================== #
# Obligation 构造辅助
# ===================================================================== #
def _new_obligation(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    closure_status: str,
    satisfaction_status: str,
    **extra: Any,
) -> Obligation:
    """统一构造 Obligation，回填 run/world/building、source 元数据与状态码。

    fact_pack_meta 携带 run_id / world_id / building_id。extra 透传义务专有字段。
    obligation_id 先填占位，validator 落库前重写。
    """
    base: Dict[str, Any] = dict(
        obligation_id=_PLACEHOLDER_OID,
        run_id=fact_pack_meta["run_id"],
        world_id=fact_pack_meta["world_id"],
        building_id=fact_pack_meta["building_id"],
        # fragment 级派生（spec 草案 §6.3.0）：fragment 作用域下派生的义务携带归属，
        # 楼级派生时 meta 无此键 → None（v0.4 行为不变）。在 obligation_id 生成前填
        # （compute_obligation_id 公式本含 fragment 段）。
        fragment_id=fact_pack_meta.get("fragment_id"),
        source_rule_card_id=card.rule_card_id,
        source_family_id=card.family_id,
        kind=kind,
        closure_status=closure_status,
        satisfaction_status=satisfaction_status,
    )
    base.update(extra)
    return Obligation(**base)


def _card_clause_ids(card: RuleCardDTO) -> List[str]:
    """从 card.source_section 收集 clause id（best-effort）。"""
    out: List[str] = []
    for sec in card.source_section or []:
        if isinstance(sec, dict):
            cid = sec.get("clause_id") or sec.get("section_id") or sec.get("id")
            if cid:
                out.append(str(cid))
    return out


def _card_quote_ids(card: RuleCardDTO) -> List[str]:
    """从 card.source_quote 收集 source_quote_id（best-effort）。"""
    out: List[str] = []
    for q in card.source_quote or []:
        if isinstance(q, dict):
            qid = q.get("source_quote_id") or q.get("quote_local_id") or q.get("id")
            if qid:
                out.append(str(qid))
    return out


# ===================================================================== #
# §6.3.3 trigger obligations
# ===================================================================== #
# trigger predicate 支持的运算符。
_TRIGGER_OPERATORS = {"==", "!=", "in", "not_in", "<", "<=", ">", ">="}


def _compare_trigger(observed: Any, op: str, expected: Any) -> Optional[bool]:
    """trigger predicate 比较（复用 threshold 比较器语义）。"""
    from .threshold_eval import compare

    return compare(observed, op, expected)


def _evaluate_measure_trigger(
    card: RuleCardDTO,
    trigger: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    common: Dict[str, Any],
    measure_aliases: Optional[Dict[str, str]] = None,
) -> Obligation:
    """measure 型触发谓词（spec §6.3.3 增补案 2026-07-08 定稿）。

    求值整体复用 §6.3.5 阈值机器（bind_measure 全 5 级 + 单位规则 + 比较器）：
    把触发项适配成 threshold 形状交 evaluate_threshold_comparison，再把
    closed+satisfied / closed+violated 翻译回 trigger true / false 语义。
    绑定档位保留全 5 级（sidecar 兜底档 4/5 是覆盖率测量键的唯一居所——
    实测 3 键 30/30 楼全在 sidecar_entry）；作为对价，bind_path 必落 notes
    供审计（codex 合议验收条件）。缺量记 missing_measurement 与 slot 侧
    missing_fact 分账。
    """
    from .threshold_eval import evaluate_threshold_comparison  # 局部导入避免环依赖

    op = trigger.get("operator")
    measure_key = trigger.get("measure_key")
    if op not in _TRIGGER_OPERATORS:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = f"trigger operator {op!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )
    if not measure_key:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = "trigger predicate_kind=measure but measure_key missing"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    common["measure_keys"] = [str(measure_key)]
    pseudo_threshold = {
        "operator": op,
        "measure_key": measure_key,
        "qualifiers": dict(trigger.get("qualifiers") or {}),
        "unit": trigger.get("unit"),
        "value": trigger.get("expected_value", trigger.get("value")),
    }
    closure_status, satisfaction, detail = evaluate_threshold_comparison(
        pseudo_threshold, fact_index, measure_aliases
    )

    for key in (
        "open_reason_code",
        "blocked_reason_code",
        "evidence_fact_ids",
        "observed_value_json",
        "expected_value_json",
        "threshold_value_json",
        "comparator_result",
        "unit",
    ):
        if key in detail:
            common[key] = detail[key]
    note_bits = [b for b in (detail.get("notes"),) if b]
    if detail.get("bind_path"):
        note_bits.append(f"bind_path={detail['bind_path']}")
    if note_bits:
        common["notes"] = "; ".join(note_bits)

    if closure_status in ("open", "blocked"):
        return _new_obligation(
            card, fact_pack_meta, "trigger", closure_status, "unknown", **common
        )
    # closed：threshold 的 satisfied/violated → trigger true/false（spec §6.3.3 既有语义）。
    if satisfaction == "satisfied":
        return _new_obligation(
            card, fact_pack_meta, "trigger", "closed", "satisfied", **common
        )
    return _new_obligation(
        card, fact_pack_meta, "trigger", "closed", "not_applicable", **common
    )


def evaluate_trigger(
    card: RuleCardDTO,
    trigger: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    *,
    measure_aliases: Optional[Dict[str, str]] = None,
    scope_component_types: Optional[set] = None,
    known_component_types: Optional[set] = None,
    scope_location_classes: Optional[set] = None,
    known_location_classes: Optional[set] = None,
    auth_target: Optional[str] = None,
    w0_identity: Optional[str] = None,
    lattice_disjoint: Optional[set] = None,
) -> Obligation:
    """评估一个 trigger condition item（spec §6.3.3）。

    trigger 是 trigger_conditions.items[] 的一项 dict，含 condition_id /
    predicate_kind / slot_ref_id / operator / expected_value / qualifiers 等。
    spec §6.3.3 + §5.4.3：trigger 通过 slot_ref_id 引用 slot_role_map[]，由
    slot_role_map[] 提供 slot_id 和默认 qualifiers；slot_role_map[] 是
    "slot reference → 具体 slot_id" 的解析表。
    predicate_kind=measure 走 _evaluate_measure_trigger（§6.3.3 增补案）。

    scope_component_types（DEBT-050 修案·spec 增补 2026-07-08）：本求值作用域
    相容的 canonical 组件身份集（fragment 作用域=该部位组件类型、楼级=楼内组件
    类集，均含类目成员展开，由 validator 预计算）。None = 判定关闭（旧行为，
    含作用域身份未知的保守回落）。known_component_types：已知 canonical 组件
    身份宇宙（词表值+类目键）——T 不在其中（卡端脏值/未规范化）不得推断 NA
    （codex 裁决护栏），回落 missing_fact。
    scope_location_classes / known_location_classes（DEBT-050 location 维度扩展
    ②，2026-07-08）：位置维度同构护栏——required location_class_key 与作用域
    location 不相容（location 无类目层级，直接值判）→ 同判 NA；component 或
    location 任一结构不可满足即 NA（析取）。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    predicate_kind = trigger.get("predicate_kind")
    op = trigger.get("operator")

    # spec §6.3.3：trigger 通过 slot_ref_id 引用 slot_role_map[]。
    slot_ref_id = trigger.get("slot_ref_id")
    slot_id: Optional[str] = None
    map_qualifiers: Dict[str, Any] = {}
    if slot_ref_id:
        for sr in (card.slot_role_map or []):
            if isinstance(sr, dict) and sr.get("slot_ref_id") == slot_ref_id:
                slot_id = sr.get("slot_id")
                map_qualifiers = dict(sr.get("qualifiers") or {})
                break
    # 兼容直接给 slot_id 的旧字段（contract 兜底）。
    if not slot_id:
        slot_id = trigger.get("slot_id")
    qualifiers: Dict[str, Any] = dict(trigger.get("qualifiers") or map_qualifiers)

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        slot_ref_ids=[slot_ref_id] if slot_ref_id else [],
        slot_ids=[slot_id] if slot_id else [],
        operator=op if isinstance(op, str) else None,
    )

    # predicate_kind 支持 slot / measure（后者为 §6.3.3 2026-07-08 增补案）。
    if predicate_kind == "measure":
        return _evaluate_measure_trigger(
            card, trigger, fact_index, fact_pack_meta, common,
            measure_aliases=measure_aliases,
        )
    if predicate_kind != "slot":
        common["blocked_reason_code"] = "unsupported_predicate_kind"
        common["notes"] = f"predicate_kind={predicate_kind!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    # operator 不支持。
    if op not in _TRIGGER_OPERATORS:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = f"trigger operator {op!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    if not slot_id:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = "trigger predicate_kind=slot but slot_id missing"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    # 绑定 slot fact + qualifier 过滤 + §6.4.3 目标作用域分级（scoped_facts：
    # 楼级求值时 building 载体聚合读数优先于 fragment 戳 sidecar 行——此前该
    # 机器零消费者，聚合行与部位行混判 ambiguous）。
    candidates = fact_index.slot_index.get(
        fact_index.canonical_slot(slot_id), []
    )
    # qfiltered = 未经 scoped_facts 的 qualifier 过滤结果（DEBT-049 Phase 3 §3.2：
    # qualifier_conflict 分账用原始 candidates 判，与 evaluate_slot_role 完全同构、
    # 与作用域无关）；bound = 再过 §6.4.3 目标作用域分级后交 conflict_status 判 0/1/N。
    qfiltered = _filter_by_qualifiers(candidates, qualifiers)
    bound = fact_index.scoped_facts(qfiltered)
    status = conflict_status(bound, fact_index.numeric_tolerance)

    if status == "missing":
        # DEBT-050 修案（spec 增补·触发器限定符结构不可满足→NA，2026-07-08）：
        # required 限定的组件身份与本求值作用域不相容 → 该组合结构性不可满足，
        # 按闭世界空真判假（closed+not_applicable，下游不激活——本部位不是该类
        # 构件，"其上缺陷"是范畴性无此项而非漏记）。护栏：仅 bound=∅ 时触发
        # （绝不覆盖实际绑定）；身份相容时保持 missing_fact（供给缺口诚实为 open）。
        # 组件 或 位置任一结构不可满足即 NA（析取）。location 维度 DEBT-050 扩展
        # （2026-07-08 ②）：private-lane 排水卡不适用于 common-pipe-duct 排水
        # fragment——location 范畴不符=卡不适用该 fragment，同 component 空真。
        req_ct = qualifiers.get("component_type_key")
        req_lc = qualifiers.get("location_class_key")
        # DEBT-065 §3.2:触发器级同卡级判据——触发器组件限定须恒等于该卡授权目标叶型
        # (§3.2-④),与 fragment 单值身份显式登记排斥才 NA;楼级(身份 None)自然不早退
        # (组件维楼级结构 NA 废止)。缺省拒绝:未授权/身份未知/非恒等/未登记排斥 → 不 NA。
        ct_incompat = (
            auth_target is not None
            and isinstance(req_ct, str) and req_ct == auth_target
            and w0_identity is not None and w0_identity != auth_target
            and lattice_disjoint is not None
            and frozenset((auth_target, w0_identity)) in lattice_disjoint
        )
        lc_incompat = (
            scope_location_classes is not None
            and isinstance(req_lc, str) and req_lc
            and req_lc not in scope_location_classes
            and (known_location_classes is None or req_lc in known_location_classes)
        )
        if ct_incompat or lc_incompat:
            dim = "component_type_key=" + repr(req_ct) if ct_incompat else \
                "location_class_key=" + repr(req_lc)
            common["comparator_result"] = False
            common["notes"] = (
                f"structurally_unsatisfiable_qualifier: {dim} "
                "incompatible with evaluation scope"
            )
            return _new_obligation(
                card, fact_pack_meta, "trigger", "closed", "not_applicable",
                **common,
            )
        # DEBT-049 Phase 3 U1 分账对齐（spec §3.2）：结构 NA 判定之后、missing_fact
        # 兜底之前，镜像 evaluate_slot_role 的 qualifier_conflict 分支——原始候选存在、
        # required qualifier 非空、但没有一条 fact 带 required qualifier（=槽有事实但限定符
        # 对不上）→ blocked/qualifier_conflict（非事实缺失 open）。用未经 scoped_facts 的原始
        # candidates 判（与 slot-role:667-675 完全同构，与作用域无关）。只在直接 trigger cohort
        # 重归账 open→blocked；allow_stop 恒 False→False（trigger 自身两态均非 satisfied）。
        if candidates and qualifiers and not qfiltered:
            common["blocked_reason_code"] = "qualifier_conflict"
            common["notes"] = (
                f"required qualifiers {qualifiers!r} matched no trigger fact "
                f"for slot_id={slot_id!r}"
            )
            return _new_obligation(
                card, fact_pack_meta, "trigger", "blocked", "unknown", **common
            )
        common["open_reason_code"] = "missing_fact"
        common["notes"] = f"trigger slot fact missing for slot_id={slot_id!r}"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = f"conflicting trigger facts for slot_id={slot_id!r}"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    fact = bound[0]
    observed = parse_value(fact.value_json)
    common["observed_value_json"] = fact.value_json
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["evidence_node_refs"] = [f.source_node_id for f in bound if f.source_node_id]
    # rule_card v2 字段名为 expected_value；兼容旧字段 value。
    expected = trigger.get("expected_value", trigger.get("value"))
    common["expected_value_json"] = json.dumps(expected, ensure_ascii=False)

    if observed is None:
        common["open_reason_code"] = "null_observed_value"
        common["notes"] = "trigger slot observed value is null"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "open", "unknown", **common
        )

    if op in {"in", "not_in"} and not isinstance(expected, (list, tuple, set)):
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = f"trigger operator {op!r} requires list value"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    result = _compare_trigger(observed, op, expected)
    if result is None:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = "trigger comparison type-incompatible"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    common["comparator_result"] = result
    # spec §6.3.3：trigger evidence 存在且为 false → closed + not_applicable；
    #              trigger true → closed + satisfied（下游激活）。
    if result:
        return _new_obligation(
            card, fact_pack_meta, "trigger", "closed", "satisfied", **common
        )
    return _new_obligation(
        card, fact_pack_meta, "trigger", "closed", "not_applicable", **common
    )


def trigger_state(o: Obligation) -> Any:
    """单条 trigger obligation → 四态（spec §6.3.3 aggregate_trigger_logic 注释）。

    True   = closed + satisfied
    False  = closed + not_applicable 或 closed + violated
    "open"   = closure_status == open
    "blocked"= closure_status == blocked
    """
    if o.closure_status == "open":
        return "open"
    if o.closure_status == "blocked":
        return "blocked"
    # closed
    if o.satisfaction_status == "satisfied":
        return True
    return False


def aggregate_trigger_logic(
    logic: str, trigger_obligations: List[Obligation]
) -> Any:
    """card-level trigger 聚合（spec §6.3.3 aggregate_trigger_logic）。

    输出四态：True / False / "open" / "blocked"。
    """
    states = [trigger_state(o) for o in trigger_obligations]
    if any(s == "blocked" for s in states):
        return "blocked"
    if not states:
        return True
    if logic == "all":
        if any(s is False for s in states):
            return False
        if any(s == "open" for s in states):
            return "open"
        return True
    if logic == "any":
        if any(s is True for s in states):
            return True
        if any(s == "open" for s in states):
            return "open"
        return False
    return "blocked"


# ===================================================================== #
# §6.3.4 slot role obligations
# ===================================================================== #
# role → ObligationKind（spec §6.3.4 表）。
_SLOT_ROLE_TO_KIND = {
    "trigger": "trigger",
    "prerequisite": "prerequisite",
    "evidence": "evidence",
    "definition_reference": "definition",
}


def qualifiers_match(required: Dict[str, Any], observed: Dict[str, Any]) -> bool:
    """qualifier 子集匹配（spec §6.3.4 qualifiers_match）。

    required 必须是 observed 的子集（逐键 observed.get(k) == v）。
    """
    for k, v in (required or {}).items():
        if observed.get(k) != v:
            return False
    return True


def _filter_by_qualifiers(
    facts: List[FactAtom], required: Dict[str, Any]
) -> List[FactAtom]:
    """按 required qualifier 子集过滤 fact 列表。"""
    if not required:
        return list(facts)
    return [f for f in facts if qualifiers_match(required, f.qualifiers)]


def evaluate_slot_role(
    card: RuleCardDTO,
    slot_ref: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 required slot role ref（spec §6.3.4）。

    slot_ref 是 slot_role_map[] 的一项 dict，含 slot_ref_id / slot_id /
    role / qualifiers / required 等。每条义务带 slot_ref_id / slot_id /
    qualifiers_json。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    role = slot_ref.get("role")
    slot_id = slot_ref.get("slot_id")
    slot_ref_id = slot_ref.get("slot_ref_id")
    qualifiers: Dict[str, Any] = dict(slot_ref.get("qualifiers") or {})

    kind = _SLOT_ROLE_TO_KIND.get(role, "evidence")
    notes = "" if role in _SLOT_ROLE_TO_KIND else f"unknown slot role={role!r}"

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        slot_ref_ids=[slot_ref_id] if slot_ref_id else [],
        slot_ids=[slot_id] if slot_id else [],
        notes=notes,
    )

    # 下游受 trigger 聚合影响：False 跳过由 validator 主循环处理；这里只处理
    # open / blocked 继承（spec §6.3.3 下游标记表）。
    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    if not slot_id:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (notes + "; slot_id missing").strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    candidates = fact_index.slot_index.get(
        fact_index.canonical_slot(slot_id), []
    )
    # qualifiers 无法判定：候选有但 qualifier 既不全等也无交集 → qualifier_conflict。
    qfiltered = _filter_by_qualifiers(candidates, qualifiers)
    if candidates and qualifiers and not qfiltered:
        # 候选事实存在但 required qualifier 一个都不匹配。
        common["blocked_reason_code"] = "qualifier_conflict"
        common["notes"] = (
            notes + f"; required qualifiers {qualifiers!r} matched no fact"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    status = conflict_status(qfiltered, fact_index.numeric_tolerance)
    if status == "missing":
        common["open_reason_code"] = "missing_fact"
        common["notes"] = (notes + f"; slot fact missing slot_id={slot_id!r}").strip(
            "; "
        )
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = (notes + f"; conflicting facts slot_id={slot_id!r}").strip(
            "; "
        )
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # consistent：closed，用全部 evidence refs。
    common["evidence_fact_ids"] = [f.fact_id for f in qfiltered]
    common["evidence_node_refs"] = [
        f.source_node_id for f in qfiltered if f.source_node_id
    ]
    common["observed_value_json"] = qfiltered[0].value_json
    return _new_obligation(
        card, fact_pack_meta, kind, "closed", "satisfied", **common
    )


def _trigger_inheritance(
    trigger_active: Any, common: Dict[str, Any]
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """下游义务对 card-level trigger 聚合结果的继承（spec §6.3.3 下游标记表）。

    返回 None 表示正常评估（trigger True）；否则返回 (closure_status,
    satisfaction_status, 补充后的 common)。
    trigger False 不在此处理（由主循环 make_rule_not_applicable_by_trigger
    决定整张卡跳过）。
    """
    out = dict(common)
    if trigger_active == "open":
        out["depends_on_open_trigger"] = True
        out["open_reason_code"] = "depends_on_open_trigger"
        # trigger_dependency_ids 由调用方在 obligation 落库后补 trigger id；
        # 这里先放占位非空值满足 validator（trigger_dependency_ids 不得为空）。
        out.setdefault("trigger_dependency_ids", ["__card_trigger__"])
        out["trigger_state"] = "open"
        return ("open", "unknown", out)
    if trigger_active == "blocked":
        out["blocked_reason_code"] = "missing_rule_edge"
        out["trigger_state"] = "blocked"
        notes = out.get("notes", "")
        out["notes"] = (notes + "; trigger aggregate blocked").strip("; ")
        return ("blocked", "unknown", out)
    return None


# ===================================================================== #
# §6.3.5 threshold obligations
# ===================================================================== #
def evaluate_threshold(
    card: RuleCardDTO,
    threshold: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    measure_aliases: Optional[Dict[str, str]] = None,
) -> Obligation:
    """评估一个 threshold regime → kind=threshold obligation（spec §6.3.5）。"""
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    measure_key = threshold.get("measure_key")
    time_anchor_key = threshold.get("time_anchor_key")

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        measure_keys=[measure_key] if measure_key else [],
        time_anchor_keys=[time_anchor_key] if time_anchor_key else [],
        operator=threshold.get("operator")
        if isinstance(threshold.get("operator"), str)
        else None,
    )

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(
            card, fact_pack_meta, "threshold", *inherit[:2], **inherit[2]
        )

    closure_status, satisfaction, detail = evaluate_threshold_comparison(
        threshold, fact_index, measure_aliases
    )
    common.update(_detail_to_fields(detail))
    return _new_obligation(
        card, fact_pack_meta, "threshold", closure_status, satisfaction, **common
    )


def _detail_to_fields(detail: Dict[str, Any]) -> Dict[str, Any]:
    """把 threshold_eval 的 detail dict 映射进 Obligation 字段。"""
    out: Dict[str, Any] = {}
    for key in (
        "open_reason_code",
        "blocked_reason_code",
        "observed_value_json",
        "expected_value_json",
        "threshold_value_json",
        "comparator_result",
        "evidence_fact_ids",
        "unit",
        "operator",
    ):
        if key in detail and detail[key] is not None:
            out[key] = detail[key]
    if "notes" in detail and detail["notes"]:
        bind = detail.get("bind_path", "")
        out["notes"] = (
            f"{detail['notes']} (bind={bind})" if bind else detail["notes"]
        )
    elif detail.get("bind_path"):
        out["notes"] = f"bind={detail['bind_path']}"
    return out


# ===================================================================== #
# §6.3.6 artifact / evidence obligations
# ===================================================================== #
def _bind_artifact_fact(
    artifact_key: str, fact_index: FactIndex
) -> Tuple[str, List[FactAtom]]:
    """绑定 artifact_key 到 sidecar artifact slot fact。

    返回 (status, facts)，status ∈ missing / consistent / ambiguous。
    禁止 prefix fallback：只查精确 slot。
    """
    slot = ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]
    candidates = fact_index.artifact_index.get(slot, [])
    if not candidates:
        candidates = [
            f
            for f in fact_index.slot_index.get(slot, [])
            if f.carrier_type in ("sidecar_entry", "building")
        ]
    # §6.4.3 目标作用域分级：楼级求值时 building 载体聚合行（rank 3）压过
    # fragment 戳 sidecar 行（rank 4），文档类槽的跨部位聚合读数不再混绑。
    candidates = fact_index.scoped_facts(candidates)
    return conflict_status(candidates, fact_index.numeric_tolerance), candidates


def evaluate_artifact_obligation(
    card: RuleCardDTO,
    artifact_key: str,
    kind: str,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    artifact_id: Optional[str] = None,
    bucket: Optional[str] = None,
) -> Obligation:
    """单个 artifact_key → artifact / evidence obligation（spec §6.3.6）。

    kind 由调用方按 bucket 语义传入（for_matching→evidence 等）。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        artifact_keys=[artifact_key],
        artifact_ids=[artifact_id] if artifact_id else [],
    )
    if bucket:
        common["notes"] = f"bucket={bucket}"

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    # 解析 artifact slot。
    try:
        slot = resolve_artifact_slot(artifact_key)
    except SchemaContractError:
        # rule_card 出现 spec 未登记的新 key → blocked + missing_artifact_mapping。
        common["blocked_reason_code"] = "missing_artifact_mapping"
        common["notes"] = (
            (common.get("notes", "") + f"; unknown artifact_key {artifact_key!r}")
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # key ∈ NOT_MODELED → blocked + artifact_not_modeled_upstream。
    if slot is None:
        common["blocked_reason_code"] = "artifact_not_modeled_upstream"
        common["notes"] = (
            common.get("notes", "")
            + f"; artifact_key {artifact_key!r} not modeled in sidecar"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    common["slot_ids"] = [slot]
    status, facts = _bind_artifact_fact(artifact_key, fact_index)

    if status == "missing":
        common["open_reason_code"] = "missing_artifact_evidence"
        common["notes"] = (
            common.get("notes", "") + f"; artifact fact missing slot={slot}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = (
            common.get("notes", "") + f"; conflicting artifact facts slot={slot}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # consistent：canonical truthy / falsy。
    common["evidence_fact_ids"] = [f.fact_id for f in facts]
    common["evidence_node_refs"] = [
        f.source_node_id for f in facts if f.source_node_id
    ]
    observed = parse_value(facts[0].value_json)
    common["observed_value_json"] = facts[0].value_json
    truthy = _canon_truthy(observed)
    if truthy is True:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "satisfied", **common
        )
    if truthy is False:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "violated", **common
        )
    # 值非 truthy/falsy 词表 —— 视为 null_observed（无法判定 presence）。
    common["open_reason_code"] = "null_observed_value"
    common["notes"] = (
        common.get("notes", "") + f"; artifact value {observed!r} not truthy/falsy"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _extract_artifact_key(item: Any) -> Optional[str]:
    """从 workflow_operands.artifacts[] 或 evidence requirement 的 artifact 引用
    抽 artifact_key。item 可为 str 或 dict。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("artifact_key") or item.get("artifact_id") or None
    return None


def derive_workflow_artifact_obligations(
    card: RuleCardDTO,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """workflow_operands.artifacts → artifact obligations（spec §6.3.6）。

    `source_sink`（identity-v5 §1.2 纯旁路来源登记，默认 None = 现网 live 路径零副作用）：非 None
    时每 append 一条义务即同序 append 一个 `SourceToken`（role="artifact"，channel="workflow_artifact"，
    primary_id=`artifact_id or artifact_key`——与阶段一 blueprint SID `enc("workflow_artifact",
    artifact_id or artifact_key)` 同键）。登记**不改**返回义务字节、**不进**判定分支。
    """
    out: List[Obligation] = []
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    artifacts = (card.workflow_operands or {}).get("artifacts", []) or []
    for item in sorted(artifacts, key=lambda x: _stable_key(x)):
        key = _extract_artifact_key(item)
        if not key:
            continue
        artifact_id = item.get("artifact_id") if isinstance(item, dict) else None
        out.append(
            evaluate_artifact_obligation(
                card,
                key,
                "artifact",
                fact_index,
                trigger_active,
                fact_pack_meta,
                artifact_id=artifact_id,
                bucket="workflow_operands.artifacts",
            )
        )
        if source_sink is not None:
            artifact_key = item.get("artifact_key") if isinstance(item, dict) else None
            source_sink.append(
                SourceToken(
                    "workflow_artifact",
                    str(artifact_id or artifact_key or ""),
                    "artifact",
                    scope_fid,
                )
            )
    return out


def derive_workflow_deadline_obligations(
    card: RuleCardDTO,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """workflow_operands.deadlines → deadline obligations（spec §6.3.7）。

    spec §6.3.7 明确「从 workflow_operands.deadlines 生成 deadline obligation」；
    §6.6 主入口伪代码遗漏了该独立循环（只在 obligation_graph node 的
    deadline_ids 派生 deadline），故此处与 artifact 对称补一个独立 deriver。
    见交付报告决策点 D-3。

    `source_sink`（identity-v5 §1.2 纯旁路来源登记，默认 None）：非 None 时每 append 一条义务即同序
    append 一个 `SourceToken`（role="deadline"，channel="workflow_deadline"，primary_id=deadline_id
    ——与阶段一 blueprint SID `_deadline_sid(deadline)` 同键）。登记不改返回义务字节、不进判定分支。
    """
    out: List[Obligation] = []
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    deadlines = (card.workflow_operands or {}).get("deadlines", []) or []
    for item in sorted(deadlines, key=lambda x: _stable_key(x)):
        if not isinstance(item, dict):
            continue
        out.append(
            evaluate_deadline(
                card, dict(item), fact_index, trigger_active, fact_pack_meta
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken(
                    "workflow_deadline",
                    str(item.get("deadline_id") or ""),
                    "deadline",
                    scope_fid,
                )
            )
    return out


# bucket → kind（spec §6.3.6 表）。for_submission / for_completion 默认 artifact，
# 但若 requirement 显式标 evidence_kind=evidence 则用 evidence。
_BUCKET_DEFAULT_KIND = {
    "for_matching": "evidence",
    "for_submission": "artifact",
    "for_completion": "artifact",
}


def evaluate_evidence_requirement(
    card: RuleCardDTO,
    bucket_name: str,
    req: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 evidence requirement（spec §6.3.6，三 bucket 都必须消费）。

    req 含 evidence_requirement_id / artifact_ids / artifact_keys / slot_ids /
    required_field_groups / evidence_kind 等。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    default_kind = _BUCKET_DEFAULT_KIND.get(bucket_name, "evidence")
    kind = req.get("evidence_kind") or default_kind
    if kind not in {"artifact", "evidence"}:
        kind = default_kind

    req_id = req.get("evidence_requirement_id")
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        notes=f"bucket={bucket_name}",
    )
    if req_id:
        common["evidence_node_refs"] = [str(req_id)]

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    # required_field_groups：缺失则 open + missing_required_field_group。
    field_groups = req.get("required_field_groups") or []
    if field_groups:
        missing_group = _check_required_field_groups(field_groups, fact_index)
        if missing_group is not None:
            common["open_reason_code"] = "missing_required_field_group"
            common["notes"] = (
                common["notes"] + f"; required field group {missing_group!r} missing"
            )
            return _new_obligation(
                card, fact_pack_meta, kind, "open", "unknown", **common
            )

    # ---- 三通道解引用（2026-07-08 诊断：第八例"登记了没接线"——本函数此前
    # ①不解 artifact_ids 卡内局部编号 ②读不存在的 req['slot_ids'] 且不走
    # slot_role_map 解引用（死链，DEBT-041 同族）③无 measure_keys 通道。
    # 修法均为 spec §6.3.6 既有引用语义的 code 侧兑现，不引入新判定语义。）----

    # 通道1：artifact 引用。artifact_keys 直取；artifact_ids 是卡内局部编号
    # （art01…），先过本卡 workflow_operands.artifacts 注册表解成 artifact_key，
    # 解不出再按字面兜底（兼容直接写键的卡）。
    local_artifact_registry: Dict[str, str] = {}
    for item in (card.workflow_operands or {}).get("artifacts", []) or []:
        if (
            isinstance(item, dict)
            and item.get("artifact_id")
            and item.get("artifact_key")
        ):
            local_artifact_registry[str(item["artifact_id"])] = str(
                item["artifact_key"]
            )

    artifact_keys: List[str] = []
    for ak in req.get("artifact_keys", []) or []:
        if ak:
            artifact_keys.append(str(ak))
    for aid in req.get("artifact_ids", []) or []:
        deref = (
            local_artifact_registry.get(str(aid)) if isinstance(aid, str) else None
        )
        k = deref or _extract_artifact_key(aid)
        if k:
            artifact_keys.append(k)

    if artifact_keys:
        # 取第一个 artifact_key 评估（多证物"取一"沿旧行为，是否合规格另核）。
        return evaluate_artifact_obligation(
            card,
            artifact_keys[0],
            kind,
            fact_index,
            trigger_active,
            fact_pack_meta,
            bucket=bucket_name,
        )

    # 通道2：slot 绑定。slot_ids 直取（契约兜底字段）；slot_ref_ids 是卡内引用，
    # 经 slot_role_map 解成 slot_id **并携带其 qualifiers**（v12 修正：此前丢限定符
    # 致有键派生行全撞判歧义——触发器路径带、证据路径漏，同款解引用补齐）。
    slot_ids = [str(s) for s in (req.get("slot_ids") or []) if s]
    slot_qualifiers: Dict[str, Dict[str, Any]] = {}
    srm_entries = {
        str(sr.get("slot_ref_id")): sr
        for sr in (card.slot_role_map or [])
        if isinstance(sr, dict) and sr.get("slot_ref_id")
    }
    for ref in req.get("slot_ref_ids", []) or []:
        sr = srm_entries.get(str(ref))
        if sr and sr.get("slot_id"):
            sid = str(sr["slot_id"])
            slot_ids.append(sid)
            q = sr.get("qualifiers")
            if isinstance(q, dict) and q:
                slot_qualifiers[sid] = q
    if slot_ids:
        return _evaluate_evidence_by_slot(
            card, kind, slot_ids, common, fact_index, fact_pack_meta,
            slot_qualifiers=slot_qualifiers,
        )

    # 通道3：measure 绑定（证据要求引测量记录：存在即证据在——测量是数值记录，
    # 不做真值性检查；缺量记 missing_measurement 与 artifact/slot 侧分账）。
    measure_keys = [str(m) for m in (req.get("measure_keys") or []) if m]
    if measure_keys:
        common["measure_keys"] = measure_keys
        bound: List[FactAtom] = []
        for mk in measure_keys:
            bound.extend(
                fact_index.measure_index.get(fact_index.canonical_measure(mk), [])
            )
        if not bound:
            common["open_reason_code"] = "missing_measurement"
            common["notes"] = common["notes"] + "; evidence measurement missing"
            return _new_obligation(
                card, fact_pack_meta, kind, "open", "unknown", **common
            )
        common["evidence_fact_ids"] = [f.fact_id for f in bound]
        common["observed_value_json"] = bound[0].value_json
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "satisfied", **common
        )

    # 三通道全空 —— evidence requirement 无可绑定引用（源卡内容缺口）。
    common["open_reason_code"] = "missing_artifact_evidence"
    common["notes"] = common["notes"] + "; evidence requirement has no bindable ref"
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _evaluate_evidence_by_slot(
    card: RuleCardDTO,
    kind: str,
    slot_ids: List[str],
    common: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    slot_qualifiers: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Obligation:
    """evidence requirement 按 slot_id 直接绑定评估（限定符过滤 + §6.4.3 作用域分级）。"""
    common = dict(common)
    common["slot_ids"] = slot_ids
    all_facts: List[FactAtom] = []
    for slot_id in slot_ids:
        candidates = fact_index.slot_index.get(
            fact_index.canonical_slot(slot_id), []
        )
        quals = (slot_qualifiers or {}).get(slot_id)
        if quals:
            candidates = _filter_by_qualifiers(candidates, quals)
        all_facts.extend(candidates)
    # §6.4.3 目标作用域分级（同触发器路径：楼级聚合读数优先）。
    all_facts = fact_index.scoped_facts(all_facts)
    status = conflict_status(all_facts, fact_index.numeric_tolerance)
    if status == "missing":
        common["open_reason_code"] = "missing_artifact_evidence"
        common["notes"] = common.get("notes", "") + "; evidence slot fact missing"
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = common.get("notes", "") + "; conflicting evidence facts"
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    common["evidence_fact_ids"] = [f.fact_id for f in all_facts]
    common["observed_value_json"] = all_facts[0].value_json
    observed = parse_value(all_facts[0].value_json)
    truthy = _canon_truthy(observed)
    if truthy is False:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "violated", **common
        )
    # truthy 或 非 presence 语义（普通 evidence 值）→ satisfied。
    return _new_obligation(
        card, fact_pack_meta, kind, "closed", "satisfied", **common
    )


def _check_required_field_groups(
    field_groups: List[Any], fact_index: FactIndex
) -> Optional[str]:
    """检查 required field group 是否在 sidecar qual.artifact_field_group 出现。

    返回第一个缺失的 field group 名；全部命中返回 None。
    """
    # qual.artifact_field_group slot 的事实，或任意 artifact entry 的
    # qualifiers.artifact_field_group。
    present: set = set()
    for f in fact_index.slot_index.get("qual.artifact_field_group", []):
        present.add(str(parse_value(f.value_json)))
    for facts in fact_index.artifact_index.values():
        for f in facts:
            g = f.qualifiers.get("artifact_field_group")
            if g is not None:
                present.add(str(g))
    for group in field_groups:
        if str(group) not in present:
            return str(group)
    return None


# ===================================================================== #
# §6.3.7 deadline obligations
# ===================================================================== #
_DEADLINE_RELATIONS = {"within", "before", "same_day_as"}
# sidecar numeric duration entries（spec §6.3.7 绑定来源优先级 1）。
_SIDECAR_DURATION_SLOTS = [
    "duration.notification.deadline",
    "duration.submission.deadline",
    "duration.delivery.deadline",
    "duration.site_visit.interval",
]


def evaluate_deadline(
    card: RuleCardDTO,
    deadline: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 deadline → kind=deadline obligation（spec §6.3.7）。

    deadline 含 deadline_id / relation / offset_value / offset_unit /
    time_anchor_key。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    deadline_id = deadline.get("deadline_id")
    relation = deadline.get("relation")
    offset_value = deadline.get("offset_value")
    time_anchor_key = deadline.get("time_anchor_key")

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        deadline_ids=[deadline_id] if deadline_id else [],
        time_anchor_keys=[time_anchor_key] if time_anchor_key else [],
    )

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(
            card, fact_pack_meta, "deadline", *inherit[:2], **inherit[2]
        )

    # 未知 relation。
    if relation not in _DEADLINE_RELATIONS:
        common["blocked_reason_code"] = "unsupported_deadline_relation"
        common["notes"] = f"deadline relation {relation!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "deadline", "blocked", "unknown", **common
        )

    # 绑定 duration / time anchor fact（spec §6.3.7 优先级）。
    fact = _bind_deadline_fact(deadline, fact_index)
    if fact is None:
        common["open_reason_code"] = "missing_time_anchor"
        common["notes"] = (
            f"no duration/time-anchor fact bound for relation={relation!r}"
        )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "open", "unknown", **common
        )

    common["evidence_fact_ids"] = [fact.fact_id]
    observed = parse_value(fact.value_json)
    common["observed_value_json"] = fact.value_json
    if observed is None:
        common["open_reason_code"] = "null_observed_value"
        common["notes"] = "deadline observed value is null"
        return _new_obligation(
            card, fact_pack_meta, "deadline", "open", "unknown", **common
        )

    # within / before（precomputed duration fallback）：observed_duration <= offset。
    if relation in {"within", "before"}:
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            # before 需要 timestamp 但只有非数值且非 duration → missing_time_anchor。
            common["open_reason_code"] = "missing_time_anchor"
            common["notes"] = (
                f"relation={relation!r} needs duration/timestamp; "
                f"observed {observed!r} unusable"
            )
            return _new_obligation(
                card, fact_pack_meta, "deadline", "open", "unknown", **common
            )
        if offset_value is None:
            common["blocked_reason_code"] = "schema_contract_violation"
            common["notes"] = f"relation={relation!r} requires offset_value"
            return _new_obligation(
                card, fact_pack_meta, "deadline", "blocked", "unknown", **common
            )
        result = float(observed) <= float(offset_value)
        common["operator"] = "<="
        common["expected_value_json"] = json.dumps(offset_value)
        common["threshold_value_json"] = json.dumps(offset_value)
        common["comparator_result"] = result
        if result:
            return _new_obligation(
                card, fact_pack_meta, "deadline", "closed", "satisfied", **common
            )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "closed", "violated", **common
        )

    # same_day_as：precomputed boolean → truthy 即 satisfied。
    truthy = _canon_truthy(observed)
    if truthy is True:
        common["comparator_result"] = True
        return _new_obligation(
            card, fact_pack_meta, "deadline", "closed", "satisfied", **common
        )
    if truthy is False:
        common["comparator_result"] = False
        return _new_obligation(
            card, fact_pack_meta, "deadline", "closed", "violated", **common
        )
    # 非 boolean 的 same_day_as 输入（需要 date 但无 date 引擎）。
    common["open_reason_code"] = "missing_time_anchor"
    common["notes"] = "same_day_as needs date or precomputed boolean"
    return _new_obligation(
        card, fact_pack_meta, "deadline", "open", "unknown", **common
    )


def _bind_deadline_fact(
    deadline: Dict[str, Any], fact_index: FactIndex
) -> Optional[FactAtom]:
    """deadline fact 绑定（spec §6.3.7 绑定来源优先级 1-4）。"""
    time_anchor_key = deadline.get("time_anchor_key")
    # 1. sidecar numeric duration entries。
    for slot in _SIDECAR_DURATION_SLOTS:
        facts = [
            f
            for f in fact_index.slot_index.get(slot, [])
            if f.carrier_type == "sidecar_entry"
        ]
        if facts:
            return facts[0]
    # 2. sidecar time anchor entries：time_anchor_key exact。
    if time_anchor_key:
        facts = [
            f
            for f in fact_index.slot_index.get(str(time_anchor_key), [])
            if f.carrier_type == "sidecar_entry"
        ]
        if facts:
            return facts[0]
        # 3. RuleThreshold duration.* measure / 4. measurement slot|measure exact。
        m = fact_index.measure_index.get(str(time_anchor_key))
        if m:
            return m[0]
    # 4. 也试 deadline_id 当 measure / slot。
    deadline_id = deadline.get("deadline_id")
    if deadline_id:
        m = fact_index.measure_index.get(str(deadline_id))
        if m:
            return m[0]
        s = fact_index.slot_index.get(str(deadline_id))
        if s:
            return s[0]
    return None


# ===================================================================== #
# §6.3.8 exception obligations
# ===================================================================== #
def evaluate_exception(
    card: RuleCardDTO,
    exc: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 exception → kind=exception obligation（spec §6.3.8）。

    spec §6.3.8 baseline 默认：
    - exception 结构缺 required fields → blocked。
    - exception triggered 且有证据 → closed + not_applicable / closed + violated。
    - 语义无法由结构判断 → blocked + missing_rule_edge。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
    )

    exc_slot = exc.get("slot_id")
    exc_kind = exc.get("exception_kind")  # "exclusion" / "violation_condition"

    # 结构缺 required fields：既无 slot_id 也无可判定语义 → blocked。
    if not exc_slot:
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "exception missing slot_id / unresolvable by structure"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    common["slot_ids"] = [str(exc_slot)]
    facts = fact_index.slot_index.get(fact_index.canonical_slot(str(exc_slot)), [])
    qualifiers: Dict[str, Any] = dict(exc.get("qualifiers") or {})
    bound = _filter_by_qualifiers(facts, qualifiers)
    status = conflict_status(bound, fact_index.numeric_tolerance)

    if status == "missing":
        # exception 所需事实缺失 → open + missing_fact。
        common["open_reason_code"] = "missing_fact"
        common["notes"] = f"exception slot fact missing slot_id={exc_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "exception", "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = f"conflicting exception facts slot_id={exc_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["observed_value_json"] = bound[0].value_json
    triggered = _canon_truthy(parse_value(bound[0].value_json))
    if triggered is None:
        # 值无法判 triggered/未 triggered。
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "exception value not truthy/falsy; semantics unresolvable"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    if not triggered:
        # exception 未触发 —— 不排除义务、不违反；记 closed + satisfied。
        common["notes"] = "exception not triggered"
        return _new_obligation(
            card, fact_pack_meta, "exception", "closed", "satisfied", **common
        )

    # exception triggered。
    if exc_kind == "violation_condition":
        common["notes"] = "exception is a violation condition and is triggered"
        return _new_obligation(
            card, fact_pack_meta, "exception", "closed", "violated", **common
        )
    # 默认 / exclusion：排除义务。
    common["notes"] = "exception triggered; obligation excluded"
    return _new_obligation(
        card, fact_pack_meta, "exception", "closed", "not_applicable", **common
    )


# ===================================================================== #
# §6.3.9 definition obligations
# ===================================================================== #
def evaluate_definition(
    card: RuleCardDTO,
    definition: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 definition → kind=definition obligation（spec §6.3.9）。

    - definition slot 有事实或 source quote → closed + satisfied
    - definition 引用缺失 → blocked + missing_rule_edge
    - definition 所需事实缺失 → open + missing_fact
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
    )

    # DEBT-057 修（2026-07-18，agy+Opus4.6 只读核证 + 主会话复核）：真卡 definition 对象的
    # 字段集是 definition_id / term_key / definition_text / scope_note / **source_quote_refs**
    # （list），此处原只读 `source_quote_id` / `quote_local_id` —— 二者在真卡上**都不存在**，
    # 致真语料唯一那张有 definitions 的卡恒落 blocked/missing_rule_edge（假阻断）。
    # 修法：真字段只接受 list/tuple 形状并保留**全部非空字符串引用**；再与旧单值键
    # （合成/历史卡兼容）做去重并集。非法标量 source_quote_refs 保守忽略，不能把字符串
    # 当 iterable 拆字符、也不能把任意标量冒充有效引用。半径 = 1 卡 1 义务。
    def_slot = definition.get("slot_id")
    _quote_refs = definition.get("source_quote_refs")
    if isinstance(_quote_refs, (list, tuple)):
        definition_quote_ids = [
            ref for ref in _quote_refs if isinstance(ref, str) and ref
        ]
    else:
        definition_quote_ids = []
    for legacy_key in ("source_quote_id", "quote_local_id"):
        legacy_ref = definition.get(legacy_key)
        if isinstance(legacy_ref, str) and legacy_ref:
            definition_quote_ids.append(legacy_ref)
    definition_quote_ids = sorted(set(definition_quote_ids))

    # definition 引用缺失：既无 slot 也无 quote。
    if not def_slot and not definition_quote_ids:
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "definition has neither slot_id nor source_quote reference"
        return _new_obligation(
            card, fact_pack_meta, "definition", "blocked", "unknown", **common
        )

    if definition_quote_ids:
        common["source_quote_ids"] = sorted(set(quote_ids + definition_quote_ids))

    if def_slot:
        common["slot_ids"] = [str(def_slot)]
        facts = fact_index.slot_index.get(
            fact_index.canonical_slot(str(def_slot)), []
        )
        if facts:
            common["evidence_fact_ids"] = [f.fact_id for f in facts]
            common["observed_value_json"] = facts[0].value_json
            common["notes"] = "definition slot has fact"
            return _new_obligation(
                card, fact_pack_meta, "definition", "closed", "satisfied", **common
            )
        if definition_quote_ids:
            # 无事实但有 source quote → closed + satisfied（术语可解释）。
            common["notes"] = "definition resolved by source quote"
            return _new_obligation(
                card, fact_pack_meta, "definition", "closed", "satisfied", **common
            )
        # definition 所需事实缺失。
        common["open_reason_code"] = "missing_fact"
        common["notes"] = f"definition slot fact missing slot_id={def_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "definition", "open", "unknown", **common
        )

    # 只有 source quote。
    common["notes"] = "definition resolved by source quote"
    return _new_obligation(
        card, fact_pack_meta, "definition", "closed", "satisfied", **common
    )


# ===================================================================== #
# §6.3.10 obligation_graph nodes + edges
# ===================================================================== #
def refine_action_kind(node_kind: str, action: str) -> str:
    """action → ObligationKind refinement（spec §6.3.10.2）。"""
    action = action or ""
    if action.startswith("submit") or action.startswith("deliver"):
        return "artifact"
    if "report" in action or action.startswith("include_"):
        return "report_field"
    if action.startswith("conduct_supervision") or "supervision" in action:
        return "supervision"
    if "method" in action or action in {
        "perform_detailed_investigation_method",
        "conduct_validation_test",
    }:
        return "method"
    return {
        "obligation": "action",
        "prohibition": "prohibition",
        "escalation": "escalation",
    }.get(node_kind, "action")


def evaluate_obligation_node(
    card: RuleCardDTO,
    obligation_node: Any,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """评估一个 obligation_graph node（spec §6.3.10）。

    每个 node 至少生成 1 条 node-level obligation；artifact_ids / deadline_ids /
    method 派生子义务。返回该 node 产生的全部 obligation 列表。

    `source_sink`（§1.2 纯旁路来源登记，默认 None = 现网 live 路径零副作用）：非 None 时，
    每 append 一条义务即同序 append 一个 `SourceToken`（token[i] ↔ 返回列表[i]），供关联层组
    `BoundObligation`。登记**不改**返回义务字节、**不进**任何判定分支（fan-out N 条各携各自令牌）。
    """
    node = (
        obligation_node
        if isinstance(obligation_node, ObligationNodeDTO)
        else ObligationNodeDTO.from_dict(dict(obligation_node))
    )
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    base_kind = refine_action_kind(node.node_kind, node.action)
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）

    out: List[Obligation] = []

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        obligation_node_id=node.obligation_node_id,
        actor=node.actor or None,
        action=node.action or None,
        recipient_ids=list(node.recipient_ids),
        artifact_ids=list(node.artifact_ids),
        deadline_ids=list(node.deadline_ids),
        trigger_dependency_ids=list(node.trigger_condition_ids),
        notes="sources=[obligation_graph]",
    )

    # ---- node-level closure/satisfaction 优先级（spec §6.3.10.4）----
    # 1. card-level trigger 聚合 false 由主循环跳过；这里处理 open/blocked 继承。
    if trigger_active == "open":
        node_common = dict(common)
        node_common["depends_on_open_trigger"] = True
        node_common["open_reason_code"] = "depends_on_open_trigger"
        node_common["trigger_state"] = "open"
        if not node_common["trigger_dependency_ids"]:
            node_common["trigger_dependency_ids"] = ["__card_trigger__"]
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out
    if trigger_active == "blocked":
        node_common = dict(common)
        node_common["blocked_reason_code"] = "missing_rule_edge"
        node_common["trigger_state"] = "blocked"
        node_common["notes"] = common["notes"] + "; trigger aggregate blocked"
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out

    # 4. node 引用的 artifact / deadline / recipient id 不存在 → blocked。
    missing_ref = _node_dangling_reference(card, node)
    if missing_ref is not None:
        node_common = dict(common)
        node_common["blocked_reason_code"] = "missing_rule_edge"
        node_common["notes"] = common["notes"] + f"; dangling ref {missing_ref}"
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out

    # 5/6/7/8 node-level 主义务判定。
    node_obl = _evaluate_node_main(
        card, node, base_kind, common, fact_index, fact_pack_meta
    )
    out.append(node_obl)
    if source_sink is not None:
        source_sink.append(
            SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
        )

    # 派生 artifact 子义务（spec §6.3.10.3）。
    for artifact_id in sorted(node.artifact_ids):
        key = _resolve_node_artifact_key(card, artifact_id)
        if key:
            out.append(
                evaluate_artifact_obligation(
                    card,
                    key,
                    "artifact",
                    fact_index,
                    trigger_active,
                    fact_pack_meta,
                    artifact_id=artifact_id,
                    bucket="obligation_graph.node",
                )
            )
            if source_sink is not None:
                source_sink.append(
                    SourceToken("workflow_artifact", artifact_id, "artifact", scope_fid)
                )

    # 派生 deadline 子义务（spec §6.3.10.3）。
    for deadline_id in sorted(node.deadline_ids):
        dl = _resolve_node_deadline(card, deadline_id)
        if dl is not None:
            out.append(
                evaluate_deadline(
                    card, dl, fact_index, trigger_active, fact_pack_meta
                )
            )
            if source_sink is not None:
                source_sink.append(
                    SourceToken("workflow_deadline", deadline_id, "deadline", scope_fid)
                )

    # 派生 method 义务（spec §6.3.10.3）。
    method_keys = (card.workflow_operands or {}).get("method_keys_allowed", []) or []
    if method_keys and base_kind in {"method"}:
        out.append(
            _evaluate_method_obligation(
                card, node, method_keys, fact_index, fact_pack_meta
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "method", scope_fid)
            )

    return out


def _evaluate_node_main(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    base_kind: str,
    common: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """node-level 主义务的 5/6/7/8 判定（spec §6.3.10.4）。"""
    common = dict(common)
    action = node.action or ""

    # method 类主节点走方法语义（q5 专员判定 + codex 逐卡裁定，2026-07-08）：
    # - method_keys_allowed 为空 = 条款无可枚举验证方法约束（专员积极判定，如
    #   重浇法/局部修补等修葺工法条款）→ closed+not_applicable（vacuous）；
    # - ["*"] = 开放集（验证义务真实、方法不限）→ 任意 method_class 证据满足；
    # - 非空具体集 → 白名单匹配（既有语义）。
    # 三案均在确定性验证器内，判定权/blind 红线不涉。
    if base_kind == "method":
        method_keys = (card.workflow_operands or {}).get(
            "method_keys_allowed", []
        ) or []
        if not method_keys:
            common["notes"] = (
                common.get("notes", "")
                + "; regulation prescribes no enumerable verification method"
                  " (q5 specialist-verified); method semantics vacuous"
            )
            return _new_obligation(
                card, fact_pack_meta, base_kind, "closed", "not_applicable",
                **common,
            )
        allowed = {str(k) for k in method_keys}
        if "*" in allowed:
            matched = [
                f for facts in fact_index.method_index.values() for f in facts
            ]
        else:
            matched = [
                f
                for key, facts in fact_index.method_index.items()
                if key in allowed
                for f in facts
            ]
        if not matched:
            common["open_reason_code"] = "missing_fact"
            common["notes"] = (
                common.get("notes", "") + "; method_class fact missing"
            )
            return _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **common
            )
        common["evidence_fact_ids"] = [f.fact_id for f in matched]
        common["observed_value_json"] = matched[0].value_json
        return _new_obligation(
            card, fact_pack_meta, base_kind, "closed", "satisfied", **common
        )

    # 7. prohibition：找 prohibited fact。
    if node.node_kind == "prohibition":
        # 用 action 当 slot 试绑。
        facts = fact_index.slot_index.get(fact_index.canonical_slot(action), [])
        status = conflict_status(facts, fact_index.numeric_tolerance)
        if status == "missing":
            common["open_reason_code"] = "missing_fact"
            common["notes"] = common.get("notes", "") + "; prohibited fact missing"
            return _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **common
            )
        if status == "ambiguous":
            common["blocked_reason_code"] = "ambiguous_fact_binding"
            return _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **common
            )
        common["evidence_fact_ids"] = [f.fact_id for f in facts]
        common["observed_value_json"] = facts[0].value_json
        truthy = _canon_truthy(parse_value(facts[0].value_json))
        if truthy is True:
            # prohibited fact truthy → 违反禁止。
            return _new_obligation(
                card, fact_pack_meta, base_kind, "closed", "violated", **common
            )
        if truthy is False:
            return _new_obligation(
                card, fact_pack_meta, base_kind, "closed", "satisfied", **common
            )
        common["open_reason_code"] = "missing_fact"
        common["notes"] = common.get("notes", "") + "; prohibited value not truthy/falsy"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "open", "unknown", **common
        )

    # 5. action 可由 artifact / evidence / sidecar fact 绑定（用 action 当 slot 试）。
    if action:
        facts = fact_index.slot_index.get(fact_index.canonical_slot(action), [])
        status = conflict_status(facts, fact_index.numeric_tolerance)
        if status == "consistent":
            common["evidence_fact_ids"] = [f.fact_id for f in facts]
            common["observed_value_json"] = facts[0].value_json
            common["slot_ids"] = [fact_index.canonical_slot(action)]
            truthy = _canon_truthy(parse_value(facts[0].value_json))
            if truthy is False:
                return _new_obligation(
                    card, fact_pack_meta, base_kind, "closed", "violated", **common
                )
            return _new_obligation(
                card, fact_pack_meta, base_kind, "closed", "satisfied", **common
            )
        if status == "ambiguous":
            common["blocked_reason_code"] = "ambiguous_fact_binding"
            return _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **common
            )

    # 8. 无任何可绑定 artifact/evidence/deadline/slot/measure，但有 source quote。
    #    （6 专业判断类动作并入此处：均为 open + missing_fact，不得 satisfied）。
    common["open_reason_code"] = "missing_fact"
    common["notes"] = common.get("notes", "") + "; action_not_fact_bound"
    return _new_obligation(
        card, fact_pack_meta, base_kind, "open", "unknown", **common
    )


def _evaluate_method_obligation(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    method_keys: List[Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """method 义务（spec §6.3.10.3：绑定 qual.method_class 或 measurement method_class）。"""
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        obligation_node_id=node.obligation_node_id,
        actor=node.actor or None,
        action=node.action or None,
        notes="sources=[obligation_graph]; method derivation",
    )
    # method_class fact：method_index 任意命中即视作可闭包。
    # "*" = 开放集哨兵（q5 专员判定 + codex 裁定 (iii)，2026-07-08）：条款要求
    # "合适的验证测试"但方法集开放（如 §5.1.1 专业判断表述）→ 任意验证测量
    # 方法证据均可满足。
    allowed = {str(k) for k in method_keys}
    if "*" in allowed:
        matched = [f for facts in fact_index.method_index.values() for f in facts]
    else:
        matched = [
            f
            for key, facts in fact_index.method_index.items()
            if key in allowed
            for f in facts
        ]
    if not matched:
        common["open_reason_code"] = "missing_fact"
        common["notes"] = common["notes"] + "; method_class fact missing"
        return _new_obligation(
            card, fact_pack_meta, "method", "open", "unknown", **common
        )
    common["evidence_fact_ids"] = [f.fact_id for f in matched]
    common["observed_value_json"] = matched[0].value_json
    return _new_obligation(
        card, fact_pack_meta, "method", "closed", "satisfied", **common
    )


def _node_dangling_reference(
    card: RuleCardDTO, node: ObligationNodeDTO
) -> Optional[str]:
    """检查 node 引用的 artifact / deadline / recipient id 是否在 card 内有定义。

    返回第一个悬空引用描述；全部存在返回 None。
    """
    wf = card.workflow_operands or {}
    # 已定义的 artifact_id / deadline_id / recipient_id 集合。
    defined_artifacts = {
        a.get("artifact_id")
        for a in (wf.get("artifacts", []) or [])
        if isinstance(a, dict) and a.get("artifact_id")
    }
    defined_deadlines = {
        d.get("deadline_id")
        for d in (wf.get("deadlines", []) or [])
        if isinstance(d, dict) and d.get("deadline_id")
    }
    defined_recipients = set()
    for r in wf.get("recipients", []) or []:
        if isinstance(r, dict):
            rid = r.get("recipient_id")
            if rid:
                defined_recipients.add(rid)
        elif isinstance(r, str):
            defined_recipients.add(r)

    # 只在 card 确实声明了对应定义列表时才判悬空（空列表视为「未建模」不判悬空）。
    if defined_artifacts:
        for aid in node.artifact_ids:
            if aid not in defined_artifacts:
                return f"artifact_id={aid!r}"
    if defined_deadlines:
        for did in node.deadline_ids:
            if did not in defined_deadlines:
                return f"deadline_id={did!r}"
    if defined_recipients:
        for rid in node.recipient_ids:
            if rid not in defined_recipients:
                return f"recipient_id={rid!r}"
    return None


def _resolve_node_artifact_key(
    card: RuleCardDTO, artifact_id: str
) -> Optional[str]:
    """从 workflow_operands.artifacts 把 node 的 artifact_id 解析成 artifact_key。

    若 artifact_id 本身就是已知 artifact_key，直接返回。
    """
    wf = card.workflow_operands or {}
    for a in wf.get("artifacts", []) or []:
        if isinstance(a, dict) and a.get("artifact_id") == artifact_id:
            return a.get("artifact_key") or artifact_id
    if artifact_id in _KNOWN_ARTIFACT_KEYS:
        return artifact_id
    return artifact_id  # 交由 resolve_artifact_slot 判未登记


def _resolve_node_deadline(
    card: RuleCardDTO, deadline_id: str
) -> Optional[Dict[str, Any]]:
    """从 workflow_operands.deadlines 把 node 的 deadline_id 解析成 deadline dict。"""
    wf = card.workflow_operands or {}
    for d in wf.get("deadlines", []) or []:
        if isinstance(d, dict) and d.get("deadline_id") == deadline_id:
            return d
    return None


class _NodeState:
    """summarize_node_state 的结果（spec §6.3.10.5）。"""

    def __init__(
        self,
        has_violation_or_failed_test: bool,
        has_open_or_blocked_or_unable_fact: bool,
    ) -> None:
        self.has_violation_or_failed_test = has_violation_or_failed_test
        self.has_open_or_blocked_or_unable_fact = has_open_or_blocked_or_unable_fact


def summarize_node_state(obligations: List[Obligation]) -> _NodeState:
    """汇总一个 node 的 obligations 状态（spec §6.3.10.5）。"""
    has_violation = any(
        (o.closure_status == "closed" and o.satisfaction_status == "violated")
        or o.comparator_result is False
        for o in obligations
    )
    has_open_blocked = any(
        o.closure_status in {"open", "blocked"} for o in obligations
    )
    return _NodeState(has_violation, has_open_blocked)


def evaluate_obligation_edges(
    card: RuleCardDTO,
    edges: List[Any],
    node_obligations: Dict[str, List[Obligation]],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """评估 obligation_graph edges（spec §6.3.10.5）。

    edges 表达义务间条件依赖。在所有 node-level obligations 初评后处理。
    返回 edge 相关的 audit obligation（target 未激活 / 悬空 / 未知关系）。

    `source_sink`（§1.2/§3.4.3 纯旁路来源登记，默认 None）：非 None 时每 append 一条边义务即同序
    append 一个 `SourceToken`，按 edge 审计三态携各自判别（§1.4/§3.4.3，codex 阻断 1 修订）：
      悬空 → role="edge_dangling"（primary_id=edge_id）；
      未知 relation → role="edge_unknown"（primary_id=edge_id, member=source/target）——source/target
        两义务各携 member 判别、**各绑各分身**（不再撞同一 SID 致 v5 误合并）；
      inactive-target 聚合 → role="edge_inactive"（primary_id=target_id, edge_ids=**完整排序集**）——
        身份携聚合全 edge（不再只登记 min(edge_id) 丢其余身份）。登记不改返回义务字节。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    nodes_by_id = {
        str(n.get("obligation_node_id")): n
        for n in (card.obligation_graph or {}).get("nodes", []) or []
        if isinstance(n, dict)
    }
    edge_dtos = [
        e if isinstance(e, ObligationEdgeDTO) else ObligationEdgeDTO.from_dict(dict(e))
        for e in edges or []
    ]

    out: List[Obligation] = []
    # 记录每个 target node 的激活情况：node_id -> (active, [edge_id]).
    activation: Dict[str, Tuple[bool, List[str]]] = {}

    for edge in sorted(
        edge_dtos, key=lambda e: (e.source_node_id, e.target_node_id, e.relation)
    ):
        common: Dict[str, Any] = dict(
            source_clause_ids=clause_ids,
            source_quote_ids=quote_ids,
            obligation_edge_ids=[edge.obligation_edge_id],
        )
        # 悬空 source / target。
        if (
            edge.source_node_id not in nodes_by_id
            or edge.target_node_id not in nodes_by_id
        ):
            common["blocked_reason_code"] = "missing_obligation_edge_target"
            common["notes"] = (
                f"edge {edge.obligation_edge_id} references missing node"
            )
            out.append(
                _new_obligation(
                    card, fact_pack_meta, "escalation", "blocked", "unknown", **common
                )
            )
            if source_sink is not None:
                source_sink.append(
                    SourceToken(
                        "obligation_graph", edge.obligation_edge_id,
                        "edge_dangling", scope_fid,
                    )
                )
            continue

        # 未知 relation。
        if edge.relation not in {"if_failed_then", "if_unable_then"}:
            common["blocked_reason_code"] = "unsupported_obligation_edge_relation"
            common["notes"] = f"edge relation {edge.relation!r} not supported"
            # source 与 target 均生成 blocked audit obligation（§3.4.3 两分身，各携 member 判别）。
            for member, nid in (
                ("source", edge.source_node_id),
                ("target", edge.target_node_id),
            ):
                c = dict(common)
                c["obligation_node_id"] = nid
                out.append(
                    _new_obligation(
                        card, fact_pack_meta, "escalation", "blocked", "unknown", **c
                    )
                )
                if source_sink is not None:
                    source_sink.append(
                        SourceToken(
                            "obligation_graph", edge.obligation_edge_id,
                            "edge_unknown", scope_fid, member=member,
                        )
                    )
            continue

        source_state = summarize_node_state(
            node_obligations.get(edge.source_node_id, [])
        )
        if edge.relation == "if_failed_then":
            active = source_state.has_violation_or_failed_test
        else:  # if_unable_then
            active = source_state.has_open_or_blocked_or_unable_fact

        prev_active, prev_edges = activation.get(
            edge.target_node_id, (False, [])
        )
        activation[edge.target_node_id] = (
            prev_active or active,
            prev_edges + [edge.obligation_edge_id],
        )

    # target 未激活 → closed + not_applicable audit obligation。
    for target_id, (active, edge_ids) in sorted(activation.items()):
        if not active:
            target_node = nodes_by_id.get(target_id, {})
            common = dict(
                source_clause_ids=clause_ids,
                source_quote_ids=quote_ids,
                obligation_node_id=target_id,
                obligation_edge_ids=sorted(edge_ids),
                notes="inactive_by_obligation_edge",
            )
            out.append(
                _new_obligation(
                    card,
                    fact_pack_meta,
                    "escalation",
                    "closed",
                    "not_applicable",
                    **common,
                )
            )
            if source_sink is not None:
                # inactive-target 聚合 → 身份携**完整 edge SID 排序集**（§3.4.3，codex 阻断 1 修订）：
                # primary_id=target_id、edge_ids=完整排序集——改/移除任一（含非最小）edge 改身份
                # （不再只登记 min(edge_id) 丢其余身份）。真语料每 target 恒 1 edge，退化为单元素集。
                source_sink.append(
                    SourceToken(
                        "obligation_graph", target_id, "edge_inactive", scope_fid,
                        edge_ids=tuple(sorted(edge_ids)),
                    )
                )
    return out


# ===================================================================== #
# §6.3.2 scope audit obligations
# ===================================================================== #
def make_scope_not_applicable(
    card: RuleCardDTO, applicability: Any, fact_pack_meta: Dict[str, str]
) -> Obligation:
    """not_applicable card 的 scope audit obligation（spec §6.3.2）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "scope",
        "closed",
        "not_applicable",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        applicability_state="not_applicable",
        notes="; ".join(applicability.reasons) or "card not applicable",
    )


def make_scope_open(
    card: RuleCardDTO, applicability: Any, fact_pack_meta: Dict[str, str]
) -> Obligation:
    """uncertain card 的 scope open obligation（spec §6.3.2）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "scope",
        "open",
        "unknown",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        applicability_state="uncertain",
        open_reason_code="applicability_uncertain",
        notes="; ".join(applicability.reasons) or "applicability uncertain",
    )


def make_rule_not_applicable_by_trigger(
    card: RuleCardDTO,
    trigger_results: List[Obligation],
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """trigger 聚合 false 时的 trigger not_applicable audit obligation（spec §6.3.3）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "trigger",
        "closed",
        "not_applicable",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        trigger_state="inactive",
        trigger_dependency_ids=[
            o.obligation_node_id or o.obligation_id
            for o in trigger_results
            if o.obligation_node_id
        ],
        notes="rule trigger aggregate evaluated false; action obligations skipped",
    )


# ===================================================================== #
# 排序辅助
# ===================================================================== #
def _stable_key(obj: Any) -> str:
    """对任意 dict / str 生成稳定排序键（spec §6.6 stable_json_key）。"""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


# ===================================================================== #
# identity-v2 阶段一旁路（加性；spec 草案 v4 A.1 两阶段架构）
# ===================================================================== #
def derive_obligation_blueprints(
    card: RuleCardDTO, fact_pack_meta: Dict[str, str]
) -> List[Any]:
    """派生器**并行**产出的 v2 `ObligationBlueprint`（从源头冻结身份，加性旁路）。

    与本模块的 v1 `Obligation` 产出**并存**：v1 判定路径零改，本入口只**增加** v2
    身份冻结（阶段一）。走 `blueprint_deriver.derive_covered_card_blueprints`（**可表示
    channel** 覆盖派生；真模型缺口 channel deadline / 普通-升级 node 显式排除、登记
    `MODEL_GAP_CHANNELS`，非静默伪装完整——STRICT 总入口
    `blueprint_deriver.derive_card_blueprints` 对含缺口的卡 fail-closed）。

    **blocker 6（Decimal 读径）**：本入口收**已解析** `RuleCardDTO`；须喂 **Decimal 读径**
    （`rulecard_decimal_load.load_identity_cards`，`parse_float=Decimal`）产出的卡——数字词元落
    int/Decimal。若喂 v1 float 读径（`json.loads`）产的卡，float 阈值会被 identity 入口
    hard-fail（13 卡 float 断线）。整包 Decimal 读+派生走 `derive_obligation_blueprints_from_bundle`。

    延迟 import 避免 import 期环依赖（`blueprint_deriver` 顶层 import 本模块的纯源读取 helper）。
    """
    from .blueprint_deriver import derive_covered_card_blueprints

    return derive_covered_card_blueprints(card, fact_pack_meta)


def derive_obligation_blueprints_from_bundle(
    bundle_path: Any, fact_pack_meta: Dict[str, str]
) -> List[Any]:
    """**blocker 6 生产入口**：从 `rule_cards.json` 路径经 Decimal 读径读原始词元 + 运行级覆盖
    派生（13 卡 float 阈值不再断线）。委托 `blueprint_deriver.derive_covered_blueprints_from_bundle`。
    """
    from .blueprint_deriver import derive_covered_blueprints_from_bundle

    return derive_covered_blueprints_from_bundle(bundle_path, fact_pack_meta)


__all__ = [
    "ARTIFACT_KEY_TO_SIDECAR_SLOT",
    "ARTIFACT_KEYS_NOT_MODELED",
    "W0_09_ARTIFACT_SLOTS",
    "TRUTHY_VALUES",
    "FALSY_VALUES",
    "SchemaContractError",
    "resolve_artifact_slot",
    "qualifiers_match",
    "evaluate_trigger",
    "trigger_state",
    "aggregate_trigger_logic",
    "evaluate_slot_role",
    "evaluate_threshold",
    "evaluate_artifact_obligation",
    "derive_workflow_artifact_obligations",
    "derive_workflow_deadline_obligations",
    "evaluate_evidence_requirement",
    "evaluate_deadline",
    "evaluate_exception",
    "evaluate_definition",
    "refine_action_kind",
    "evaluate_obligation_node",
    "evaluate_obligation_edges",
    "summarize_node_state",
    "make_scope_not_applicable",
    "make_scope_open",
    "make_rule_not_applicable_by_trigger",
    "_stable_key",
    "derive_obligation_blueprints",
    "derive_obligation_blueprints_from_bundle",
]
