"""identity-v5 `IdentityBlueprintCatalog` —— Decimal 读径生成的全卡全 channel 逐 scope 蓝图
全集 + 五元组关联索引（现网键切换增补 §5，DEBT-054 最后一役步 2/3）。

**加性影子模式**（本模块不接 live 判定主链、不切活动键、不改判定语义）：

- **catalog 生成（§5.1）**：由权威 bundle 的 **Decimal 读径**（`rulecard_decimal_load.load_identity_cards`
  → scope-aware 逐 scope 派生）生成；float `RuleSlice` 不能直接生成严格身份（literal 阈值须走 Decimal
  ingress）。catalog 携 bundle / profile / schema 哈希（`bundle_sha256` 锚**完整权威 bundle**、
  `identity_catalog_sha256` 锚**本次所选卡集及实际 card_scopes**）。

- **scope-aware 蓝图物化（§2）**：每张所选卡按冻结 `card_scopes` 公式（镜像 validator.py 主循环：
  `list(fragment_ids) if fragment_ids and _card_is_fragment_scoped(card) else [None]`）逐 scope 物化——
  fragment 承载卡 + 非空 fragment 集 → 逐 `fragment_id`（`ObligationScope(kind="fragment")` 进 hash）；
  否则 → `[None]` building 回退（单趟 building scope）。applicability 恒 building、每卡一条。

- **三类控制审计身份（§3）**：applicability（现有 builder）+ structural_scope_audit（fragment）+
  trigger_aggregation_audit（building/fragment）；后两者 blueprint 由 `blueprint_deriver` 的两新 builder
  按 §5.3.1 静态条件逐 scope 声明。

- **五元组关联索引（§5.1）**：`{(rule_card_id, scope.kind, scope.scope_id, source_channel,
  source_item_id) -> ObligationBlueprint}`；建索引任一键重复 → hard-fail `duplicate_blueprint_key`
  （不静默覆盖，镜像 `_index_blueprints` blocker 1④）。

- **卡集口径（§5.1）**：身份材料从**完整 Decimal bundle** 生成；本次传入的 catalog 是按
  `RuleSlice.candidate_rule_cards` 精确投影的 run catalog——catalog 卡集必须与 RuleSlice 卡集相等
  （不等 → hard-fail `read_path_card_set_mismatch`）。

blind 红线（§12）：本模块**禁 import** `eval.*` / `TruthBundle` / `NormativeProjection` /
`expected_verdict` / `threshold_evaluations` / `workflow_engine`；catalog 只从权威 bundle 的
`rule_cards.json` Decimal 读径生成，三类审计身份材料只含规则侧要求（component_type_key /
location_class_key / logic / 成员 SID），不含 W2 真值、不含实际楼况事实。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canonical_profile import CANONICAL_PROFILE_ID, canonical_json, parse_json_decimal

from .blueprint_deriver import (
    RegimeSignatureRegistry,
    _applicability_sid,
    _card_component_types,
    _card_is_fragment_scoped,
    _card_qualifier_values,
    _structural_audit_sid,
    _trigger_agg_audit_sid,
    build_structural_scope_audit_blueprint,
    build_trigger_aggregation_audit_blueprint,
    derive_covered_card_blueprints,
)
from .blueprint_state_eval import _declared_covered_source_items
from .identity_v2 import (
    IDENTITY_SCHEMA,
    ObligationBlueprint,
    ObligationContractError,
)
from .rulecard_decimal_load import (
    load_identity_cards,
    load_identity_cards_from_text,
)

CATALOG_SCHEMA = "identity_blueprint_catalog_v1"

# 固定权威 bundle 缺省路径（§5.2）：生产/orchestrator 每 run 从此定点经 Decimal 读径建 run
# catalog（float `RuleSlice` 不能直接生成严格身份 → 身份材料只从权威 bundle 的 literal 阈值走
# Decimal ingress）。相对本模块定位 `agent_v1/`（parents[3]：closure → evo_agent_baseline →
# src → agent_v1），与 `allow_stop_reconcile.py` / smoke 脚本的 BUNDLE 常量同一物理文件。
DEFAULT_AUTHORITATIVE_BUNDLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
    / "rule_cards.json"
)

# 五元组关联键：把 float 判定读径产物关联回 Decimal 身份读径蓝图（§1.1）。
FiveTupleKey = Tuple[str, str, str, str, str]
# = (rule_card_id, scope.kind, scope.scope_id, source_channel, source_item_id)


def _bp_five_tuple_key(bp: ObligationBlueprint) -> FiveTupleKey:
    idn = bp.identity
    return (
        idn.source_rule_card_id,
        idn.scope.kind,
        idn.scope.scope_id,
        idn.source_channel,
        idn.source_item_id,
    )


# ===========================================================================
# scope 迭代基建（镜像 validator.py 主循环：slot_domain / fragment_ids 由运行输入定）
# ===========================================================================


def derive_slot_domain(rule_slice: Any) -> Dict[str, str]:
    """slot_id → semantic_domain（镜像 validator.py:807-811，源 `rule_slice.semantic_slots`）。

    供 `_card_is_fragment_scoped` 判卡是否 fragment 承载——与判定读径同源（同一 semantic_slots）。
    """
    slot_domain: Dict[str, str] = {}
    for s in rule_slice.semantic_slots or []:
        sid = getattr(s, "slot_id", None)
        if sid:
            slot_domain[str(sid)] = str(getattr(s, "semantic_domain", "") or "")
    return slot_domain


def _fact_fragment_id(f: Any) -> Optional[str]:
    """一条 fact 的 fragment 归属（镜像 validator.py:813-819）。"""
    q = f.qualifiers.get("fragment_id") if f.qualifiers else None
    if isinstance(q, str) and q:
        return q
    if f.carrier_type == "fragment" and f.carrier_id:
        return str(f.carrier_id)
    return None


def derive_fragment_ids(fact_pack: Any) -> List[str]:
    """本 `FactPack` 实际求值的 fragment 全集（升序，镜像 validator.py:821-823）。

    fragment 集合来源与 live 主循环一致（`fact_pack.facts` 的 qualifiers.fragment_id /
    carrier_type=="fragment" 归属），保证判定读径与身份读径的 fragment 粒度对齐。
    """
    return sorted({fid for fid in (_fact_fragment_id(f) for f in fact_pack.facts) if fid})


def _card_scopes(
    card: Any, fragment_ids: List[str], slot_domain: Dict[str, str]
) -> List[Optional[str]]:
    """冻结 `card_scopes` 公式（§2.2，镜像 validator.py:984-988 逐字节同源）。

        card_scopes = list(fragment_ids) if fragment_ids and _card_is_fragment_scoped(card) else [None]

    fragment 承载卡 + 非空 fragment 集 → 逐 fragment_id；否则 → `[None]`（building 回退，单趟）。
    """
    if fragment_ids and _card_is_fragment_scoped(card, slot_domain):
        return list(fragment_ids)
    return [None]


# ===========================================================================
# scope-aware 逐卡蓝图物化（§2 + §3：覆盖 channel 逐 scope + 三类审计）
# ===========================================================================


def _derive_card_catalog_blueprints(
    card: Any,
    base_meta: Dict[str, Any],
    card_scopes: List[Optional[str]],
) -> List[ObligationBlueprint]:
    """一张卡的 scope-aware 蓝图全集（§2 逐 scope 覆盖 channel + §3 三类审计）。

    - **覆盖 channel + applicability**：复用**已过闸** `derive_covered_card_blueprints(card, scope_meta)`
      （scope_meta 带 fragment_id → 覆盖 channel 经 `_scope_from_meta` 落 fragment scope；applicability
      硬写 building scope，与卡是否 fragment 承载无关 → 每卡恒一条，逐 scope 去重）。
    - **structural_scope_audit（§5.3.1）**：仅真 fragment scope（`scope_fid is not None`）且卡的
      component_type_key ∨ location_class_key 要求集非空 → 逐该 fragment 声明一条。
    - **trigger_aggregation_audit（§5.3.1）**：卡有 ≥1 trigger item → 逐当前 scope 声明一条。
    """
    out: List[ObligationBlueprint] = []
    applicability_added = False
    has_trigger = bool((card.trigger_conditions or {}).get("items"))
    struct_nonempty = bool(
        _card_component_types(card)
        or _card_qualifier_values(card, "location_class_key")
    )
    for scope_fid in card_scopes:
        scope_meta = (
            base_meta if scope_fid is None else {**base_meta, "fragment_id": scope_fid}
        )
        # 覆盖 channel + applicability（已过闸派生；applicability 逐 scope 去重）。
        for bp in derive_covered_card_blueprints(card, scope_meta):
            if bp.identity.source_channel == "applicability":
                if applicability_added:
                    continue  # applicability 每卡恒一条 building scope，跨 scope 去重
                applicability_added = True
            out.append(bp)

        # structural_scope_audit：仅真 fragment scope + 要求集非空（§5.3.1）。
        if scope_fid is not None and struct_nonempty:
            out.append(
                build_structural_scope_audit_blueprint(card, scope_fid, scope_meta)
            )

        # trigger_aggregation_audit：卡有 ≥1 trigger item（§5.3.1，随当前 scope）。
        if has_trigger:
            out.append(build_trigger_aggregation_audit_blueprint(card, scope_meta))

    return out


# ===========================================================================
# 五元组 manifest（float 声明侧 + blueprint 侧同源，§5.3.2）
# ===========================================================================


def declare_five_tuples(
    card: Any, fragment_ids: List[str], slot_domain: Dict[str, str]
) -> List[FiveTupleKey]:
    """float 声明侧 scope-aware 五元组 manifest（§5.3.2 冻结）——**multiset（保留多重性）**。

    catalog blueprint 侧用**同一函数体条件**枚举 manifest（同源，杜绝漂移）：
      (a) applicability 审计：每卡恒 1 条，building scope（与 scope 迭代无关）。
      (b) 覆盖 channel 源项（`_declared_covered_source_items` multiset）逐 scope 展开为五元组。
      (c) 结构审计：仅真 fragment scope 且要求集非空（§5.3.1）。
      (d) trigger 聚合审计：卡有 ≥1 trigger item（§5.3.1）。

    据实报（spec/code 调和）：spec §5.3.2 伪码 `_card_is_fragment_scoped(card)` 隐含 slot_domain
    环境常量；本实现把 slot_domain 显式串入（与 validator.py 判定读径同源），语义不变、只除歧义。
    """
    out: List[FiveTupleKey] = []
    rid = str(card.rule_card_id)
    scopes = _card_scopes(card, fragment_ids, slot_domain)

    # (a) applicability：每卡恒 1 条，building scope（与 scope 迭代无关）。
    out.append((rid, "building", "", "applicability", _applicability_sid(card)))

    has_trigger = bool((card.trigger_conditions or {}).get("items"))
    struct_nonempty = bool(
        _card_component_types(card)
        or _card_qualifier_values(card, "location_class_key")
    )
    for scope_fid in scopes:
        scope_kind = "building" if scope_fid is None else "fragment"
        scope_id = "" if scope_fid is None else scope_fid

        # (b) 覆盖 channel 源项 multiset 逐 scope 展开为五元组。
        for (channel, sid) in _declared_covered_source_items(card):
            out.append((rid, scope_kind, scope_id, channel, sid))

        # (c) 结构审计：仅真 fragment scope 且要求集非空。
        if scope_fid is not None and struct_nonempty:
            out.append(
                (rid, "fragment", scope_id, "structural_scope_audit",
                 _structural_audit_sid(card))
            )

        # (d) trigger 聚合审计：卡有 ≥1 trigger item。
        if has_trigger:
            out.append(
                (rid, scope_kind, scope_id, "trigger_aggregation_audit",
                 _trigger_agg_audit_sid(card))
            )
    return out


# ===========================================================================
# IdentityBlueprintCatalog + 双 sha256
# ===========================================================================


@dataclass(frozen=True)
class IdentityBlueprintCatalog:
    """经 Decimal 读径闸门生成的全卡全 channel 逐 scope 蓝图全集 + 五元组索引（§5.1.1 冻结字段集）。"""

    catalog_schema: str
    obligation_identity_schema: str
    canonical_profile_id: str
    bundle_sha256: str
    identity_catalog_sha256: str
    blueprints: Tuple[ObligationBlueprint, ...]
    index: Dict[FiveTupleKey, ObligationBlueprint]

    def get(self, key: FiveTupleKey) -> Optional[ObligationBlueprint]:
        return self.index.get(key)

    def require(self, key: FiveTupleKey) -> ObligationBlueprint:
        """按五元组取蓝图；未命中 → hard-fail `blueprint_association_miss`（不 fail-open）。"""
        bp = self.index.get(key)
        if bp is None:
            raise ObligationContractError(
                "blueprint_association_miss:"
                f"{key[0]}:{key[1]}:{key[2]}:{key[3]}:{key[4]}"
            )
        return bp


def compute_bundle_sha256(rule_cards_json_text: str) -> str:
    """`bundle_sha256` 唯一公式（§5.1 冻结）：

        bundle_root  = parse_json_decimal(rule_cards_json_text)  # 完整根对象（含顶层 bundle_id）
        bundle_sha256 = sha256(canonical_json(bundle_root).encode("utf-8")).hexdigest()  # 64 位小写 hex

    锚**完整权威 bundle**（非仅 cards 数组、非 raw bytes）。
    """
    bundle_root = parse_json_decimal(rule_cards_json_text)
    return hashlib.sha256(
        canonical_json(bundle_root).encode("utf-8")
    ).hexdigest()


def compute_identity_catalog_sha256(
    blueprints: Tuple[ObligationBlueprint, ...], bundle_sha256: str
) -> str:
    """`identity_catalog_sha256` canonical preimage（§5.1.2 冻结排序/编码）。

    `canonical_json` = NFC + 键升序 + UTF-8；数组顺序由**五元组键升序**固定（canonical_json 不重排
    数组，故排序须显式）。**同一完整 bundle + 同一 profile/schema + 同一 selected card set + 同一
    实际 card_scopes manifest** → 同一 hash，跨机可复算对账。64 位小写 hex（内容完整性锚）。
    """
    ordered = sorted(blueprints, key=_bp_five_tuple_key)
    preimage = {
        "catalog_schema": CATALOG_SCHEMA,
        "obligation_identity_schema": IDENTITY_SCHEMA,
        "canonical_profile_id": CANONICAL_PROFILE_ID,
        "bundle_sha256": bundle_sha256,
        "blueprints": [
            {
                "key": [
                    bp.identity.source_rule_card_id,
                    bp.identity.scope.kind,
                    bp.identity.scope.scope_id,
                    bp.identity.source_channel,
                    bp.identity.source_item_id,
                ],
                "canonical_identity_hash": bp.canonical_identity_hash,
                "immutable": bp.immutable.model_dump(),
            }
            for bp in ordered
        ],
    }
    return hashlib.sha256(canonical_json(preimage).encode("utf-8")).hexdigest()


def _build_five_tuple_index(
    blueprints: Tuple[ObligationBlueprint, ...],
) -> Dict[FiveTupleKey, ObligationBlueprint]:
    """五元组 → blueprint；任一键重复 → hard-fail `duplicate_blueprint_key`（不静默覆盖）。"""
    index: Dict[FiveTupleKey, ObligationBlueprint] = {}
    for bp in blueprints:
        key = _bp_five_tuple_key(bp)
        if key in index:
            raise ObligationContractError(
                "duplicate_blueprint_key:"
                f"{key[0]}:{key[1]}:{key[2]}:{key[3]}:{key[4]}"
            )
        index[key] = bp
    return index


def build_identity_blueprint_catalog(
    bundle_path: Any,
    rule_slice: Any,
    fact_pack: Any,
    meta: Dict[str, Any],
) -> IdentityBlueprintCatalog:
    """构建 `IdentityBlueprintCatalog`（§5.1，Decimal 读径 scope-aware 生成 + 五元组索引 + 双 sha256）。

    步骤：
      1. Decimal 读径读**完整** bundle → `bundle_sha256`（锚完整权威 bundle）。
      2. 所选卡集 = `RuleSlice.candidate_rule_cards`；投影 Decimal 卡到所选集。
         catalog 卡集必须与 RuleSlice 卡集相等（不等 → hard-fail `read_path_card_set_mismatch`）。
      3. slot_domain（`rule_slice.semantic_slots`）+ fragment_ids（`fact_pack.facts`）——与判定读径同源。
      4. 逐所选卡按冻结 `card_scopes` 逐 scope 物化（覆盖 channel + applicability + 两类审计）。
      5. 运行级 `RegimeSignatureRegistry` 跨卡签名闸。
      6. 五元组索引（键重复 hard-fail）+ `identity_catalog_sha256`（锚 selected card set + 实际 card_scopes）。

    现网键切换后本函数由调用方（validator 调用点 / 影子对账 / 测试）在**进 `validate_building_closure`
    前**调，产 run catalog 显式传入（§5.2）。
    """
    return build_identity_blueprint_catalog_from_text(
        Path(bundle_path).read_text(encoding="utf-8"),
        rule_slice,
        fact_pack,
        meta,
    )


def build_run_catalog(
    rule_slice: Any,
    fact_pack: Any,
    meta: Dict[str, Any],
    bundle_path: Any = None,
) -> IdentityBlueprintCatalog:
    """便捷入口（§5.2）：从**固定权威 bundle 路径**经 Decimal 读径建 run catalog，供 orchestrator /
    smoke / 影子对账在进 `validate_building_closure` 前统一调用。

    - `bundle_path=None` → `DEFAULT_AUTHORITATIVE_BUNDLE_PATH`（生产每 run 缺省用权威定点）；显式传路
      径仅测试/内存 bundle 场景用。
    - bundle 文件缺失 → hard-fail `authoritative_bundle_missing`（**绝不回退**空 catalog / 不从 float
      `RuleSlice` 重建身份 / 不读隐式仓库路径，镜像切键红线 §5.2）。
    - 其余委托 `build_identity_blueprint_catalog`：读**完整** bundle 算 `bundle_sha256`、按
      `RuleSlice.candidate_rule_cards` 精确投影（slice ⊄ bundle → `read_path_card_set_mismatch`）。
    """
    path = (
        Path(bundle_path)
        if bundle_path is not None
        else DEFAULT_AUTHORITATIVE_BUNDLE_PATH
    )
    if not path.is_file():
        raise ObligationContractError(f"authoritative_bundle_missing:{path}")
    return build_identity_blueprint_catalog(path, rule_slice, fact_pack, meta)


def build_identity_blueprint_catalog_from_text(
    bundle_text: str,
    rule_slice: Any,
    fact_pack: Any,
    meta: Dict[str, Any],
) -> IdentityBlueprintCatalog:
    """`build_identity_blueprint_catalog` 的**文本入口**（无磁盘 I/O，合成卡测试/内存 bundle 用）。

    与路径入口同一 Decimal 读径 + scope-aware 生成 + 双 sha256 + 五元组索引；`bundle_sha256` 锚
    传入的完整 bundle 文本、`identity_catalog_sha256` 锚本次所选卡集及实际 card_scopes。
    """
    text = bundle_text
    bundle_sha256 = compute_bundle_sha256(text)

    all_decimal_cards = load_identity_cards_from_text(text)
    decimal_by_id: Dict[str, Any] = {
        str(c.rule_card_id): c for c in all_decimal_cards
    }

    slice_ids = [str(c.rule_card_id) for c in rule_slice.candidate_rule_cards]
    slice_id_set = set(slice_ids)

    # 卡集相等闸（§5.1）：RuleSlice 所选卡必须全在权威 bundle 内。
    missing_in_bundle = sorted(slice_id_set - set(decimal_by_id.keys()))
    if missing_in_bundle:
        raise ObligationContractError(
            f"read_path_card_set_mismatch:slice_only={missing_in_bundle}"
        )

    slot_domain = derive_slot_domain(rule_slice)
    fragment_ids = derive_fragment_ids(fact_pack)

    blueprints: List[ObligationBlueprint] = []
    for rid in sorted(slice_id_set):
        card = decimal_by_id[rid]
        card_scopes = _card_scopes(card, fragment_ids, slot_domain)
        blueprints.extend(
            _derive_card_catalog_blueprints(card, meta, card_scopes)
        )

    # 运行级跨卡 regime 签名闸（镜像 `derive_run_blueprints`）。
    regime_registry = RegimeSignatureRegistry()
    for bp in blueprints:
        regime_registry.record(bp.identity.source_predicate_spec)

    blueprints_tuple = tuple(blueprints)
    index = _build_five_tuple_index(blueprints_tuple)
    identity_catalog_sha256 = compute_identity_catalog_sha256(
        blueprints_tuple, bundle_sha256
    )

    return IdentityBlueprintCatalog(
        catalog_schema=CATALOG_SCHEMA,
        obligation_identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        bundle_sha256=bundle_sha256,
        identity_catalog_sha256=identity_catalog_sha256,
        blueprints=blueprints_tuple,
        index=index,
    )


# ===========================================================================
# catalog 自洽闸（§5.1：进 validate_building_closure 前，header / index / hash 独立自证）
# ===========================================================================


def assert_catalog_header_and_hash(catalog: IdentityBlueprintCatalog) -> None:
    """catalog 自洽闸（现网键切换增补 §5.1；进 `validate_building_closure` 前，绝不 fail-open）。

    独立于双读径五元组闸（§5.3，对 float 判定读径）——本闸只核 catalog **自身内容完整性**：

    ① header 三字段等于冻结常量（`catalog_schema`==`CATALOG_SCHEMA` /
       `obligation_identity_schema`==`IDENTITY_SCHEMA` / `canonical_profile_id`==`CANONICAL_PROFILE_ID`）
       —— 不符 → `catalog_header_mismatch`（拦 header v4 / 错 profile 的旧或伪 catalog）；
    ② 五元组索引完备（键集 = 全 blueprint 五元组、无缺无多，且每键映回其五元组对应 blueprint）
       —— 不符 → `catalog_header_mismatch`；
    ③ `identity_catalog_sha256` 从 `blueprints` + `bundle_sha256` **重算一致** —— 不符 →
       `catalog_hash_mismatch`（拦伪 hash：内容与 sha 不匹配的 catalog 冒充现网身份材料）。
    """
    header = (
        ("catalog_schema", catalog.catalog_schema, CATALOG_SCHEMA),
        ("obligation_identity_schema", catalog.obligation_identity_schema, IDENTITY_SCHEMA),
        ("canonical_profile_id", catalog.canonical_profile_id, CANONICAL_PROFILE_ID),
    )
    for field, got, exp in header:
        if got != exp:
            raise ObligationContractError(
                f"catalog_header_mismatch:{field}:{got!r}!={exp!r}"
            )

    # ② 索引完备：从 blueprints **重建期望索引**并逐键做对象全等比较——不只验键集+
    # 映射值自身五元组（后者可被"换成同五元组但 immutable 翻转的伪蓝图"穿透而 hash
    # 仍锚 blueprints 不变——codex 019f7328 阻断 2）。blueprint 为 frozen+extra=forbid
    # pydantic 值对象，`==` 即完整结构值全等（当前规范化 schema 下等价于 canonical 内容一致）。
    expected_index = {}
    for bp in catalog.blueprints:
        k = _bp_five_tuple_key(bp)
        if k in expected_index:
            raise ObligationContractError(f"duplicate_blueprint_key:{k!r}")
        expected_index[k] = bp
    if set(catalog.index.keys()) != set(expected_index.keys()):
        raise ObligationContractError("catalog_header_mismatch:index_incomplete")
    for key, bp in catalog.index.items():
        if bp != expected_index[key]:
            raise ObligationContractError(
                "catalog_header_mismatch:index_not_anchored_to_blueprints"
            )

    # ③ sha256 重算一致（内容完整性锚）。
    recomputed = compute_identity_catalog_sha256(catalog.blueprints, catalog.bundle_sha256)
    if recomputed != catalog.identity_catalog_sha256:
        raise ObligationContractError(
            f"catalog_hash_mismatch:{catalog.identity_catalog_sha256}!={recomputed}"
        )


# ===========================================================================
# 双读径五元组核对闸（§5.3：进主循环前，float 声明 ↔ catalog blueprint 双向 0 差）
# ===========================================================================


def assert_catalog_dual_read_path_consistency(
    catalog: IdentityBlueprintCatalog,
    float_cards: List[Any],
    fragment_ids: List[str],
    slot_domain: Dict[str, str],
) -> None:
    """双读径**五元组**双向核对闸（§5.3 扩展；进主循环前，绝不 fail-open）。

    - float 卡（v1 判定读径）逐卡 `declare_five_tuples` multiset ↔ catalog blueprint 五元组 manifest
      **双向相等**（含 fragment scope + 三类审计 channel）。
    - float 多 / blueprint 缺 → `blueprint_association_miss`；blueprint 多 / float 缺 →
      `obligation_association_orphan`；float multiset 重复键 → `duplicate_source_item_in_read_path`。
    - 两侧卡集相等（任一侧缺/多 → `read_path_card_set_mismatch`）；float 卡 ID 唯一
      （重复 → `duplicate_float_card`）。

    三类审计因 declare 侧 (a)/(c)/(d) 与 blueprint 侧同条件声明，**恒不落孤儿**。
    """
    # float 卡 ID 唯一。
    float_ids: set = set()
    for c in float_cards:
        cid = str(c.rule_card_id)
        if cid in float_ids:
            raise ObligationContractError(f"duplicate_float_card:{cid}")
        float_ids.add(cid)

    # blueprint 侧按卡分组的五元组 manifest（multiset via list）。
    bp_by_card: Dict[str, List[FiveTupleKey]] = {}
    for bp in catalog.blueprints:
        key = _bp_five_tuple_key(bp)
        bp_by_card.setdefault(key[0], []).append(key)

    # 卡集相等。
    bp_ids = set(bp_by_card.keys())
    if float_ids != bp_ids:
        float_only = sorted(float_ids - bp_ids)
        blueprint_only = sorted(bp_ids - float_ids)
        raise ObligationContractError(
            f"read_path_card_set_mismatch:float_only={float_only}:"
            f"blueprint_only={blueprint_only}"
        )

    for c in float_cards:
        rid = str(c.rule_card_id)
        declared = declare_five_tuples(c, fragment_ids, slot_domain)

        # float multiset 无重复键（配对前 hard-fail；multiset 保留多重性）。
        seen_float: set = set()
        for key in declared:
            if key in seen_float:
                raise ObligationContractError(
                    f"duplicate_source_item_in_read_path:{key[3]}:{key[4]}"
                )
            seen_float.add(key)

        # blueprint 侧本卡键集（catalog 索引已保证无重复 → set 等价）。
        bp_keys = set(bp_by_card.get(rid, []))

        missing = seen_float - bp_keys  # float 声明、blueprint 缺。
        if missing:
            k = sorted(missing)[0]
            raise ObligationContractError(
                f"blueprint_association_miss:{k[3]}:{k[4]}"
            )
        orphan = bp_keys - seen_float  # blueprint 有、float 不声明。
        if orphan:
            k = sorted(orphan)[0]
            raise ObligationContractError(
                f"obligation_association_orphan:{k[3]}:{k[4]}"
            )


__all__ = [
    "CATALOG_SCHEMA",
    "DEFAULT_AUTHORITATIVE_BUNDLE_PATH",
    "FiveTupleKey",
    "IdentityBlueprintCatalog",
    "derive_slot_domain",
    "derive_fragment_ids",
    "declare_five_tuples",
    "build_identity_blueprint_catalog",
    "build_run_catalog",
    "build_identity_blueprint_catalog_from_text",
    "compute_bundle_sha256",
    "compute_identity_catalog_sha256",
    "assert_catalog_header_and_hash",
    "assert_catalog_dual_read_path_consistency",
]
