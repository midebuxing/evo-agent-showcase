"""identity-v5 影子现网路径 —— 加性对账驱动（现网键切换增补 §10 步 5-7，DEBT-054 最后一役）。

**加性影子模式（本模块不接 live 判定主链、不切活动键、不改判定语义、不提交）**：

- **步 5（影子现网路径）**：`run_shadow_closure` 建 run catalog（卡集投影 + card_scopes）→ 调
  `validate_building_closure(..., shadow_sink=sink)` 拿 **v1 判定权威结果** + **逐义务（pre-dedup）
  来源五元组键**（主循环旁路登记，判定语义零改、shadow_sink=None 时字节不变）→ 每条 v1 义务经五元组
  `catalog.require` 绑定 catalog 蓝图（`BoundObligation`）。

- **步 6/7（对账）**：`reconcile_shadow` 在**同一 pre-dedup 义务多重集**上分别按 v1 `dedupe_key`（旧键）
  与 v5 `canonical_identity_hash`（新键）去重（**只换键**，状态仍走现有 v1 `_merge_two`），对比
  `allow_stop` / open/blocked 存在性 / 逐源状态；义务集差异逐条归因（v1 有损去重 / v5 过合并）。

**判定语义零改红线（§12）**：本模块**不改** `validate_building_closure` 返回结果；只在其旁读 pre-dedup
义务 + 按新键重算去重计数。`allow_stop` 由 `compute_allow_stop_and_reason`（判定权威）重算，本模块不改判。

**`_ShadowRegistrar`（validator 主循环内旁路登记器）**：模块级**不 import validator**（避免环）；validator
以**局部 import** 引本类。driver 函数以**局部 import** 引 validator（同避环）。

blind 红线（§12）：本模块**禁 import** `eval.*` / `TruthBundle` / `NormativeProjection` /
`workflow_engine`；只在同包中立身份/蓝图/catalog/义务模块间关联。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from canonical_profile import nfc

from evo_agent_baseline.contracts import Obligation

from .blueprint_deriver import (
    _applicability_sid,
    _structural_audit_sid,
    _trigger_agg_audit_sid,
)
from .blueprint_state_eval import (
    _encode_source_item_id,
    _evidence_sid,
    _nodes_by_id,
    _trigger_sid,
)
from .identity_binding import BoundObligation, token_five_tuple_key
from .identity_blueprint_catalog import (
    FiveTupleKey,
    IdentityBlueprintCatalog,
    assert_catalog_dual_read_path_consistency,
    build_identity_blueprint_catalog,
    derive_fragment_ids,
    derive_slot_domain,
)
from .identity_v2 import (
    ObligationContractError,
    RunInstanceEnvelope,
    compute_obligation_id_v2,
)
from .obligation_deriver import SourceToken


def _norm_scope(fid: Optional[str]) -> Optional[str]:
    """归一 scope 标识（§1.4）：None/"" → None（building）；其它保留。"""
    return fid if fid else None


# =========================================================================== #
# _ShadowRegistrar —— validator 主循环内的逐义务旁路来源登记器（§10 步 5）
# =========================================================================== #


class _ShadowRegistrar:
    """主循环每 append 一条 pre-dedup 义务即登记 `(义务深拷贝, 五元组键)` 到 sink（判定语义零改）。

    - **单项 channel**（applicability / structural / trigger_agg / trigger / slot_role / threshold /
      evidence / exception / definition）：五元组键的 (channel, source_item_id) 由**与
      `_declared_covered_source_items` / catalog 侧同一 SID 构造点**产出，字节一致杜绝漂移。
    - **fan-out channel**（node / edge / workflow_artifact / workflow_deadline）：由求值器 `source_sink`
      登记的 `SourceToken` 经 `token_five_tuple_key`（**单一 SID 权威**）产键，token[i] ↔ obls[i] 同序。

    **深拷贝快照**：登记时即 `model_copy(deep=True)`，与主循环 `sort_and_dedupe` 之后的原地回填
    （`assign_obligation_ids` 等）隔离，保 pre-dedup 状态干净。
    """

    __slots__ = ("sink", "_deep")

    def __init__(
        self,
        sink: List[Tuple[Obligation, FiveTupleKey]],
        deep_copy: bool = True,
    ) -> None:
        # deep_copy=True（默认，影子对账）：登记深拷贝快照，与 sort_and_dedupe 后原地回填隔离。
        # deep_copy=False（现网键切换后 validator live 绑定）：登记真义务引用（同批直接绑定去重）。
        self.sink = sink
        self._deep = deep_copy

    def _snapshot(self, obl: Obligation) -> Obligation:
        return obl.model_copy(deep=True) if self._deep else obl

    def _rec(
        self,
        card: Any,
        obl: Obligation,
        channel: str,
        sid: str,
        scope_fid: Optional[str],
    ) -> None:
        rid = str(card.rule_card_id)
        scope_fid = _norm_scope(scope_fid)
        scope_kind = "building" if scope_fid is None else "fragment"
        scope_id = "" if scope_fid is None else str(scope_fid)
        self.sink.append(
            (self._snapshot(obl), (rid, scope_kind, scope_id, channel, sid))
        )

    # ---- 三类控制审计（scope 由 spec 冻结：applicability 恒 building；结构 fragment；trigger_agg 当前）
    def applicability(self, card: Any, obl: Obligation) -> None:
        self._rec(card, obl, "applicability", _applicability_sid(card), None)

    def structural_audit(self, card: Any, obl: Obligation, scope_fid: Optional[str]) -> None:
        self._rec(card, obl, "structural_scope_audit", _structural_audit_sid(card), scope_fid)

    def trigger_agg_audit(self, card: Any, obl: Obligation, scope_fid: Optional[str]) -> None:
        self._rec(
            card, obl, "trigger_aggregation_audit", _trigger_agg_audit_sid(card), scope_fid
        )

    # ---- 覆盖 channel 单项（SID 编码逐字节镜像 `_declared_covered_source_items` / Path B）
    def trigger(self, card: Any, obl: Obligation, trigger: Dict[str, Any], scope_fid) -> None:
        self._rec(card, obl, "trigger", _trigger_sid(trigger), scope_fid)

    def slot_role(self, card: Any, obl: Obligation, slot_ref: Dict[str, Any], scope_fid) -> None:
        self._rec(
            card, obl, "slot_role",
            _encode_source_item_id("slot_role", str(slot_ref.get("slot_ref_id") or "")),
            scope_fid,
        )

    def threshold(self, card: Any, obl: Obligation, threshold: Dict[str, Any], scope_fid) -> None:
        self._rec(
            card, obl, "threshold",
            _encode_source_item_id(
                "threshold", nfc(str(threshold.get("threshold_regime_id") or ""))
            ),
            scope_fid,
        )

    def evidence(self, card: Any, obl: Obligation, req: Dict[str, Any], scope_fid) -> None:
        self._rec(card, obl, "evidence", _evidence_sid(req), scope_fid)

    def exception(self, card: Any, obl: Obligation, exc: Dict[str, Any], scope_fid) -> None:
        self._rec(
            card, obl, "exception",
            _encode_source_item_id("exception", nfc(str(exc.get("exception_kind") or ""))),
            scope_fid,
        )

    def definition(self, card: Any, obl: Obligation, defn: Dict[str, Any], scope_fid) -> None:
        self._rec(
            card, obl, "definition",
            _encode_source_item_id(
                "definition",
                nfc(str(defn.get("definition_id") or "")),
                {"term_key": nfc(str(defn.get("term_key") or ""))},
            ),
            scope_fid,
        )

    # ---- fan-out channel（node / edge / workflow_artifact / workflow_deadline）：token → 五元组键
    def fanout(
        self,
        card: Any,
        obls: List[Obligation],
        tokens: List[SourceToken],
        scope_fid: Optional[str],
        nodes_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        if len(obls) != len(tokens):
            raise ObligationContractError(
                f"shadow_source_token_count_mismatch:{len(obls)}!={len(tokens)}"
            )
        loop_scope = _norm_scope(scope_fid)
        nbid = nodes_by_id if nodes_by_id is not None else _nodes_by_id(card)
        for obl, tok in zip(obls, tokens):
            # 三者一致闸（§1.4）：token 冻结 scope ↔ 义务 fragment_id ↔ 循环 scope 归一后须全等。
            if not (
                _norm_scope(tok.scope_fid) == _norm_scope(obl.fragment_id) == loop_scope
            ):
                raise ObligationContractError(
                    f"token_scope_mismatch:token={tok.scope_fid!r}:"
                    f"obligation={obl.fragment_id!r}:loop={scope_fid!r}"
                )
            key = token_five_tuple_key(card, tok, nbid)
            self.sink.append((self._snapshot(obl), key))


# =========================================================================== #
# 影子驱动 —— 建 catalog + 跑影子现网路径 + 绑定（§10 步 5）
# =========================================================================== #


@dataclass
class ShadowClosureRun:
    """一栋楼影子现网路径产物（v1 判定权威 + pre-dedup 绑定 + catalog）。"""

    building_id: str
    v1_result: Any                              # ClosureValidationResult（判定权威，不改）
    bound: List[BoundObligation]                # pre-dedup 每条 v1 义务 ↔ 恰一 catalog 蓝图
    catalog: IdentityBlueprintCatalog
    pre_dedup_count: int


def run_shadow_closure(
    bundle_path: Any,
    rule_slice: Any,
    fact_pack: Any,
    meta: Dict[str, str],
    *,
    config: Any = None,
    measure_aliases: Optional[Dict[str, str]] = None,
) -> ShadowClosureRun:
    """步 5：先建 run catalog + 双读径核对，再跑影子现网路径拿 pre-dedup 义务 + 绑定（判定语义零改）。

    1. `build_identity_blueprint_catalog`（Decimal 读径 scope-aware 生成 + 双 sha256 + 五元组索引）。
    2. `assert_catalog_dual_read_path_consistency`（float 声明 ↔ catalog blueprint 五元组双向 0 差）。
    3. `validate_building_closure(..., shadow_sink=sink)`：拿 v1 判定权威结果 + 逐义务五元组键
       （主循环旁路登记，shadow_sink=None 时字节不变）。
    4. 每条 pre-dedup v1 义务经五元组 `catalog.require` 绑定蓝图（未命中 → `blueprint_association_miss`
       = unbound_live_obligation 前置拦截，绝不 fail-open）。
    """
    from .validator import validate_building_closure  # 局部 import 破环

    catalog = build_identity_blueprint_catalog(bundle_path, rule_slice, fact_pack, meta)

    # 双读径五元组双向核对闸亦在 validate_building_closure 内跑（此处冗余保留，belt-and-suspenders）。
    slot_domain = derive_slot_domain(rule_slice)
    fragment_ids = derive_fragment_ids(fact_pack)
    assert_catalog_dual_read_path_consistency(
        catalog, list(rule_slice.candidate_rule_cards), fragment_ids, slot_domain
    )

    # 现网键切换后：validate_building_closure 已是 v5 活动路径（判定权威）。经 pre_dedup_out 捕获
    # pre-dedup 绑定多重集深拷贝快照（供 v1 旧键 vs v5 新键重算对账）；活动结果即 v5 判定权威。
    pre_dedup: List[BoundObligation] = []
    authoritative_result = validate_building_closure(
        rule_slice,
        fact_pack,
        config,
        identity_blueprint_catalog=catalog,
        pre_dedup_out=pre_dedup,
    )

    return ShadowClosureRun(
        building_id=str(fact_pack.building_id),
        v1_result=authoritative_result,
        bound=pre_dedup,
        catalog=catalog,
        pre_dedup_count=len(pre_dedup),
    )


# =========================================================================== #
# v1 / v5 去重（只换键：同一 pre-dedup 多重集，键 v1 dedupe_key → v5 canonical_identity_hash）
# =========================================================================== #


def _counts(obls: List[Obligation]) -> Dict[str, int]:
    o = b = c = sat = vio = unk = na = 0
    for x in obls:
        o += x.closure_status == "open"
        b += x.closure_status == "blocked"
        c += x.closure_status == "closed"
        sat += x.satisfaction_status == "satisfied"
        vio += x.satisfaction_status == "violated"
        unk += x.satisfaction_status == "unknown"
        na += x.satisfaction_status == "not_applicable"
    return dict(
        total=len(obls), open=o, blocked=b, closed=c,
        satisfied=sat, violated=vio, unknown=unk, not_applicable=na,
    )


def _allow_stop(counts: Dict[str, int]) -> bool:
    from .validator import compute_allow_stop_and_reason
    return compute_allow_stop_and_reason(
        counts["open"], counts["blocked"], counts["violated"], True, True
    )[0]


@dataclass
class _DedupGroup:
    rep: Obligation                     # 合并代表（_merge_two 折叠结果）
    members: List[BoundObligation] = field(default_factory=list)


def _dedup_by(
    bound: List[BoundObligation], key_kind: str
) -> Dict[Any, _DedupGroup]:
    """在 pre-dedup 绑定多重集上按 v1 `dedupe_key`（旧）或 v5 `canonical_identity_hash`（新）去重。

    **只换键**：分组键之外，排序 / 折叠 / 状态合并**完全复刻** `sort_and_dedupe_obligations`——
    先 `assign_obligation_ids`（v1 编号，供 `sort_key` 稳定），按 `sort_key` 稳定序遍历，同组 `_merge_two`
    保守折叠（primary=首参，order-dependent 生产语义）。state 仍走 v1 `_merge_two`（§6.3 步 5）。
    """
    from .validator import (
        _merge_two,
        assign_obligation_ids_v1,
        dedupe_key_v1 as v1_dedupe_key,
        sort_key,
    )

    # 复刻 sort_and_dedupe：先回填 v1 obligation_id（供 sort_key 稳定），再按 sort_key 遍历折叠。
    assign_obligation_ids_v1([b.obligation for b in bound])

    def group_key(b: BoundObligation) -> Any:
        if key_kind == "v1":
            return v1_dedupe_key(b.obligation)
        return b.blueprint.canonical_identity_hash  # v5

    groups: Dict[Any, _DedupGroup] = {}
    for b in sorted(bound, key=lambda x: sort_key(x.obligation)):
        k = group_key(b)
        g = groups.get(k)
        if g is None:
            groups[k] = _DedupGroup(rep=b.obligation, members=[b])
        else:
            g.rep = _merge_two(g.rep, b.obligation)
            g.members.append(b)
    return groups


def _assert_no_hash_collision(bound: List[BoundObligation]) -> int:
    """同 `canonical_identity_hash` 组内 identity canonical bytes 必全等（真 hash 碰撞 → hard-fail
    `identity_hash_collision_pre_merge`，§6.3 步 3）。返回去重后不同身份数。"""
    from canonical_profile import canonical_json
    by_hash: Dict[str, str] = {}
    for b in bound:
        h = b.blueprint.canonical_identity_hash
        cb = canonical_json(b.blueprint.identity.model_dump())
        prev = by_hash.get(h)
        if prev is None:
            by_hash[h] = cb
        elif prev != cb:
            raise ObligationContractError(f"identity_hash_collision_pre_merge:{h}")
    return len(by_hash)


# =========================================================================== #
# reconcile_shadow —— 步 6/7 对账（allow_stop / 存在性 / 逐源状态 / 逐条归因）
# =========================================================================== #


def reconcile_shadow(run: ShadowClosureRun) -> Dict[str, Any]:
    """步 6/7 精确现网对账：同一 pre-dedup 多重集，v1 旧键 vs v5 新键去重，产验收证据 + 归因表。

    验收：
      ① `allow_stop` 零翻转：v1 判定权威 `run.v1_result.allow_stop` vs v5 键去重后重算 allow_stop。
      ② open/blocked 存在性零翻转。
      ③ 状态字段逐源零差：逐 source 身份 v1-组状态 vs v5-组状态；差异必落已登记归因（v1 有损去重 /
         v5 过合并），**未归因差 = 0**（红旗）。
      ④ 义务集差异逐条归因：v1 有损去重（v1 组跨 >1 身份哈希）/ v5 过合并（v5 组跨 >1 v1 键）。
    """
    from .validator import dedupe_key_v1 as v1_dedupe_key

    bound = run.bound

    # 碰撞前置：同 hash 身份 bytes 全等（真碰撞 hard-fail）。
    distinct_identities = _assert_no_hash_collision(bound)

    v1_groups = _dedup_by(bound, "v1")
    v5_groups = _dedup_by(bound, "v5")

    v1_reps = [g.rep for g in v1_groups.values()]
    v5_reps = [g.rep for g in v5_groups.values()]
    v1_counts = _counts(v1_reps)
    v5_counts = _counts(v5_reps)

    # 活动判定权威（现网键切换后 validate_building_closure 结果 = **v5 live**，不改）。
    auth = run.v1_result.closure_summary
    auth_allow = bool(run.v1_result.allow_stop)
    v1_allow = _allow_stop(v1_counts)
    v5_allow = _allow_stop(v5_counts)

    # ---- ④ 逐条归因：v1 有损去重 / v5 过合并 ----
    v1_lossy = []       # v1 组跨 >1 身份哈希（v1 折叠了不同身份）
    for k, g in v1_groups.items():
        hashes = {b.blueprint.canonical_identity_hash for b in g.members}
        if len(hashes) > 1:
            channels = sorted({b.blueprint.identity.source_channel for b in g.members})
            v1_lossy.append({
                "v1_key": _key_repr(k),
                "distinct_identities": len(hashes),
                "member_count": len(g.members),
                "channels": channels,
            })

    v5_over = []        # v5 组跨 >1 v1 键（v5 合并了 v1 分开的）
    for h, g in v5_groups.items():
        v1keys = {v1_dedupe_key(b.obligation) for b in g.members}
        if len(v1keys) > 1:
            v5_over.append({
                "identity_hash": h,
                "channel": g.members[0].blueprint.identity.source_channel,
                "distinct_v1_keys": len(v1keys),
                "member_count": len(g.members),
            })

    # ---- ③ 逐源状态零差：以 canonical_identity_hash 为源；v5 状态 vs v1-组状态 ----
    v5_status_by_hash = {
        h: (g.rep.closure_status, g.rep.satisfaction_status)
        for h, g in v5_groups.items()
    }
    v1_status_by_v1key = {
        k: (g.rep.closure_status, g.rep.satisfaction_status)
        for k, g in v1_groups.items()
    }
    # v1 组是否「纯」（成员同一身份哈希）+ v5 组是否「纯」（成员同一 v1 键）。
    v1_mixed_keys = {
        k for k, g in v1_groups.items()
        if len({b.blueprint.canonical_identity_hash for b in g.members}) > 1
    }
    v5_mixed_hashes = {
        h for h, g in v5_groups.items()
        if len({v1_dedupe_key(b.obligation) for b in g.members}) > 1
    }
    per_source_status_diffs = 0
    unexplained_status_diffs = 0
    unexplained_samples: List[Dict[str, Any]] = []
    for b in bound:
        h = b.blueprint.canonical_identity_hash
        vk = v1_dedupe_key(b.obligation)
        v5s = v5_status_by_hash[h]
        v1s = v1_status_by_v1key[vk]
        if v5s != v1s:
            per_source_status_diffs += 1
            explained = (vk in v1_mixed_keys) or (h in v5_mixed_hashes)
            if not explained:
                unexplained_status_diffs += 1
                if len(unexplained_samples) < 5:
                    unexplained_samples.append({
                        "identity_hash": h,
                        "channel": b.blueprint.identity.source_channel,
                        "v1_status": v1s,
                        "v5_status": v5s,
                    })

    # ---- v5 影子交叉核对（现网键切换加固②）：v5 键去重应等于活动判定权威（live v5）**全部 summary 计数** ----
    # 现网键切换后活动路径即 v5，故 v5-键影子去重必须逐字段重现 live v5 判定权威（不止 open/blocked/total）。
    v5_shadow_matches_auth = (
        v5_counts["open"] == auth.open_count
        and v5_counts["blocked"] == auth.blocked_count
        and v5_counts["closed"] == auth.closed_count
        and v5_counts["total"] == auth.total_obligations
        and v5_counts["violated"] == auth.violated_count
        and v5_counts["satisfied"] == auth.satisfied_count
        and v5_counts["unknown"] == auth.unknown_count
        and v5_counts["not_applicable"] == auth.not_applicable_count
        and v5_allow == auth_allow
    )

    return {
        "building_id": run.building_id,
        "pre_dedup_total": run.pre_dedup_count,
        "distinct_identities": distinct_identities,
        # 活动判定权威（现网键切换后 = v5 live）。
        "authoritative": {
            "allow_stop": auth_allow,
            "open": auth.open_count,
            "blocked": auth.blocked_count,
            "total": auth.total_obligations,
            "closed": auth.closed_count,
            "violated": auth.violated_count,
            "satisfied": auth.satisfied_count,
            "unknown": auth.unknown_count,
            "not_applicable": auth.not_applicable_count,
        },
        "v1_shadow": {"allow_stop": v1_allow, **v1_counts, "groups": len(v1_groups)},
        "v5_shadow": {"allow_stop": v5_allow, **v5_counts, "groups": len(v5_groups)},
        # ① allow_stop 零翻转：v1 旧键去重 vs v5 新键（=live）去重（切键前后 allow_stop 不翻转）。
        "allow_stop_flip": v1_allow != v5_allow,
        # ② open/blocked 存在性零翻转（v1 键 vs v5 键，同一 pre-dedup 多重集）。
        "open_exist_flip": (v1_counts["open"] > 0) != (v5_counts["open"] > 0),
        "blocked_exist_flip": (v1_counts["blocked"] > 0) != (v5_counts["blocked"] > 0),
        # v5 影子交叉核对（v5 键去重 == 活动判定权威 live v5，全 summary 计数；加固②）。
        "v5_shadow_matches_authoritative": v5_shadow_matches_auth,
        # ③ 逐源状态（v1 组状态 vs v5 组状态，未归因差应 0）
        "per_source_status_diffs": per_source_status_diffs,
        "unexplained_status_diffs": unexplained_status_diffs,
        "unexplained_status_samples": unexplained_samples,
        # ④ 逐条归因
        "v1_lossy_merge_groups": len(v1_lossy),
        "v1_lossy_merge_samples": v1_lossy[:8],
        "v5_over_merge_groups": len(v5_over),
        "v5_over_merge_samples": v5_over[:8],
    }


def _key_repr(k: Any) -> str:
    """v1 dedupe_key（tuple）→ 紧凑字符串（归因表可读）。"""
    if isinstance(k, tuple):
        return "|".join(
            "/".join(map(str, x)) if isinstance(x, tuple) else str(x) for x in k
        )
    return str(k)


__all__ = [
    "_ShadowRegistrar",
    "ShadowClosureRun",
    "run_shadow_closure",
    "reconcile_shadow",
]
