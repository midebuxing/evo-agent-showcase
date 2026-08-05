"""义务身份 v2 从源头冻结（spec 草案 v4 Block A · A.1 两阶段架构·阶段一）。

**加性旁路**：本模块与 `obligation_deriver.py` 的 v1 `Obligation` 产出**并存**，
在义务派生的**源头**（原始 `RuleCardDTO` 子结构 + 派生上下文）冻结不可变
``ObligationBlueprint``（含正确 ``CanonicalObligationIdentity``）。

**为什么从源头（吸取废桥教训，见 `杂物箱/垃圾箱/identity_derive废桥_20260714/`）**：
扁平化后的 `Obligation` 已丢结构信息（binding 配对 / 真 threshold_regime_id /
求值前 operator），从扁平义务反推 v2 身份必然出错。本模块从**原始卡字段**读取真
``threshold_regime_id`` / 规则侧原始 operator / 正确 binding 配对。

**fail-closed 连贯设计（2026-07-14，grok 4.5 + gpt-5.6-sol 多方综合，化解 codex 8 缺陷）**：
- **§1 local_ref/canonical_key 张力**：resolved binding **`local_ref := canonical_key`**
  （丢弃不透明卡内编号 → 别名 crack_width vs measure.crack_width 归一同 canonical_key →
  同 local_ref → **alias 稳定**）；unresolved 才保 namespaced 原始 ref。重复由**聚合闸**
  hard-fail（非靠 local_ref 区分）。不改 CanonicalBinding 字段集/哈希函数。
- **§2 聚合闸**：`CardBindingRegistry`（卡级，`derive_card_blueprints` 收尾）逮同卡跨源项
  `(namespace, 原始 ref)` 异目标→`unresolved_multi_target`、同 channel 同 source_item_id
  重复→`duplicate_source_item`；`RegimeSignatureRegistry`（运行级，`derive_run_blueprints`
  钩子）逮跨卡同 threshold_regime_id 异签名→`threshold_regime_signature_conflict`。
- **§3 Decimal ingress**：identity 入口经 `rulecard_decimal_load`（parse_float=Decimal）读；
  `_literal_value` **拒 Python float** → `canonical_number_float_ingress` hard-fail。
- **§5 applicability channel 接入**：`build_applicability_blueprint`（scope-audit 义务，
  source_channel=applicability，scope=building）；已删可写 `scope` channel。
- **§6 formula 登记表**：`FormulaRegistryEntry` + 受限表达式 → 规范 AST → 变量/度量精确
  匹配（`n^2-2n+3`）→ formula_id；不匹配一律 `unsupported_formula`（无任意散列）。
- **typed ingress**：各源入口真 `DTO.model_validate`（嵌套越界键/缺必填/类型错→
  pydantic ValidationError）；trigger `predicate_kind ∉ {slot, measure}` → hard-fail
  `unsupported_predicate_kind`（不静默归 slot）。

**判定权红线**：本模块**不产出任何判定**；只冻结**身份材料**（阶段一）。

**本单元覆盖的 channel（源字段齐全、可表示；v4 缺口增补后无剩余真模型缺口）**：
threshold / trigger（slot+measure）/ slot_role / workflow_artifact / **workflow_deadline**（v4：
独立 kind=deadline 义务，§2）/ evidence / definition / exception（真卡语料 0 条，code path 就位）/
obligation_graph（**v4：全 3 种 node_kind** —— prohibition + 普通 obligation + 升级 escalation node +
**method-derived 子义务**（§3.4）+ edge）/ **applicability**（scope-audit 义务，§5）。

**v4 缺口增补（identity-v2 收尾 / DEBT-054，切 live 硬前置）**——两真模型缺口 + method 子义务配套已补：
- **workflow deadline**：``SourceChannel`` 增 ``workflow_deadline`` 枚举 + DeadlineBinding 复合键灌注
  （`build_workflow_deadline_blueprint`，§2）；**node.deadline_ids → identity 内嵌已解引用的完整
  DeadlineBinding**（`_resolve_node_deadline_bindings`，§2.5/§3.2；与 channel 同值对象、字节相同）。
- **普通/升级 node**：obligation_graph 判别式**放宽**（predicate_kind = raw node_kind ∈ {obligation,
  escalation}、spec=None，§3.1）；`build_obligation_node_blueprint` 灌注全 3 种 node_kind。
- **method 子义务**：method 产出 node（refine→method 且卡有 method_keys_allowed）**且结构可分**
  （`_node_method_separable`：node 带非空 artifact_ids/deadline_ids v1-dedupe 区分键，真卡 5 卡）才额外建 method-derived
  blueprint（`build_method_derived_blueprint`，parts={"derived":"method"} + method_keys→qualifiers，§3.4）。
- **fail-closed 哨兵**：未知 raw node_kind 由 `_assert_known_node_kind` 在 `from_dict` 归一**之前**
  hard-fail（`unknown_node_kind`，§3.1.1）；v1 求值链归一语义保留（不破旧测）。
- **入口合一**：`MODEL_GAP_CHANNELS` 清空 → STRICT 总入口 `derive_card_blueprints` ≡ 覆盖入口
  `derive_covered_card_blueprints`（§9，真卡恒过）。生产 Decimal 读径入口
  `derive_covered_blueprints_from_bundle`（blocker 6）。

blind 红线（A.9）：本模块**禁 import** `eval.*` / `TruthBundle` /
`threshold_evaluations` / `workflow_engine`；只向下 import 中立 `canonical_profile`
与同包 `identity_v2` + `obligation_deriver` 的**纯源读取辅助** + `source_dtos`。
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from canonical_profile import (
    CANONICAL_PROFILE_ID,
    canonical_decimal_str,
    canonical_json,
    canonicalize_artifact,
    canonicalize_deadline,
    canonicalize_measure,
    canonicalize_slot,
    canonicalize_unit,
    in_not_in_sort,
    is_empty_source_value,
    nfc,
    qualifier_fingerprint,
)

from .identity_v2 import (
    IDENTITY_SCHEMA,
    BlueprintProvenance,
    CanonicalBinding,
    CanonicalObligationIdentity,
    DeadlineBinding,
    ImmutablePayload,
    ObligationBlueprint,
    ObligationContractError,
    ObligationScope,
    PredicateSpecV1,
    RunInstanceEnvelope,
    VariableBinding,
    compute_canonical_identity_hash,
    compute_obligation_id_v2,
)

# 纯源读取辅助 + kind 映射常量 + prohibition/edge 派生所需（v1 派生器里的确定性 helper /
# DTO 视图，不触求值/事实绑定路径）。
from .obligation_deriver import (
    _BUCKET_DEFAULT_KIND,
    _SLOT_ROLE_TO_KIND,
    _card_clause_ids,
    _card_quote_ids,
    _node_satisfaction_slot_refs,
    refine_action_kind,
)
from .schema import ObligationEdgeDTO, ObligationNodeDTO

# A.0 typed 源 DTO（ingress：真 model_validate → 嵌套越界键/缺必填/类型错 hard-fail）。
# blocker 3：除 leaf item DTO 外，另引**聚合源容器**顶层 DTO（TriggerConditions/
# WorkflowOperands/EvidenceRequirements），卡级对整个容器 model_validate（含未消费部分的
# 嵌套越界键，如 recipients[].brand_new_nested / deadlines[].brand_new）。
from .source_dtos import (
    ApplicabilityDTO,
    DefinitionDTO,
    EvidenceRequirementDTO,
    EvidenceRequirementsDTO,
    ExceptionDTO,
    SlotRoleDTO,
    ThresholdRegimeDTO,
    TriggerConditionsDTO,
    TriggerItemDTO,
    WorkflowArtifactDTO,
    WorkflowOperandsDTO,
)

BLUEPRINT_SCHEMA = "obligation_blueprint_v1"


# ===========================================================================
# 公共辅助：scope / run_env / provenance / qualifiers
# ===========================================================================


def _scope_from_meta(meta: Dict[str, Any]) -> ObligationScope:
    """镜像 v1 `_new_obligation`：有 fragment_id → fragment scope，否则楼级 building。"""
    fid = meta.get("fragment_id")
    if fid:
        return ObligationScope(kind="fragment", scope_id=str(fid))
    return ObligationScope(kind="building", scope_id="")


def _run_env(meta: Dict[str, Any]) -> RunInstanceEnvelope:
    return RunInstanceEnvelope(
        run_id=str(meta["run_id"]),
        world_id=str(meta["world_id"]),
        building_id=str(meta["building_id"]),
    )


def _provenance(
    meta: Dict[str, Any],
    card: Any,
    *,
    slot_ref_ids: Tuple[str, ...] = (),
    artifact_local_ids: Tuple[str, ...] = (),
    extra_quote_ids: Tuple[str, ...] = (),
    trigger_dependency_ids: Tuple[str, ...] = (),
    evidence_node_refs: Tuple[str, ...] = (),
) -> BlueprintProvenance:
    quotes = tuple(sorted(set(_card_quote_ids(card)) | set(extra_quote_ids)))
    return BlueprintProvenance(
        run_id=str(meta["run_id"]),
        world_id=str(meta["world_id"]),
        building_id=str(meta["building_id"]),
        source_family_id=str(getattr(card, "family_id", "")),
        slot_ref_ids=tuple(sorted(set(slot_ref_ids))),
        artifact_local_ids=tuple(sorted(set(artifact_local_ids))),
        source_clause_ids=tuple(sorted(set(_card_clause_ids(card)))),
        source_quote_ids=quotes,
        trigger_dependency_ids=tuple(sorted(set(trigger_dependency_ids))),
        evidence_node_refs=tuple(sorted(set(evidence_node_refs))),
    )


def _qualifier_fp(qualifiers: Optional[Dict[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    """顶层/threshold qualifiers → canonical fingerprint（C.6/C.9）。

    fail-closed（blocker 2·第九键）：只跳空值（C.9 empty→不生成 entry）；非空的键全喂给
    `qualifier_fingerprint` → `canonicalize_qualifier`；八键外的键触发 C.9
    `unknown_qualifier_key` hard-fail（不丢弃、不 str() 糊平）。
    """
    if not qualifiers:
        return ()
    pairs = [
        (k, str(v))
        for k, v in qualifiers.items()
        if not is_empty_source_value(v)
    ]
    return qualifier_fingerprint(pairs)


# CanonicalBinding namespace → registry（namespace ∈ {slot,artifact,measure,time_anchor}）。
_CANON_FN = {
    "slot": canonicalize_slot,
    "measure": canonicalize_measure,
    "artifact": canonicalize_artifact,
    "time_anchor": canonicalize_deadline,
}

# predicate_spec 标量 canonical 字段 → registry（含 unit，非 binding namespace）。
_SCALAR_CANON_FN = {
    "measure": canonicalize_measure,
    "unit": canonicalize_unit,
    "time_anchor": canonicalize_deadline,
}


# ===========================================================================
# §1 binding：resolved → local_ref := canonical_key；unresolved → namespaced 原始 ref
# ===========================================================================


class _RawBinding(NamedTuple):
    """单条 binding + 其**不透明原始 ref** + **qualifier 指纹**（blocker 1 折叠判别）。

    ``binding.local_ref``（进身份哈希）：resolved 时 = ``canonical_key`` +（有 qualifier 时）
    canonical 编码的 qualifier 指纹（§1 别名稳定 + blocker 1 异 qualifier 不折叠）、
    unresolved 时 = ``namespace:原始ref``(+qualifier)（保区分）。``original_ref`` 是不透明卡内
    编号（slot_ref_id / artifact_id / measure 原串），**仅供多目标闸**（`_finalize_bindings`
    卡内闸 + `CardBindingRegistry` 跨源项闸）判 `(namespace, original_ref)` 是否解析到多目标。
    ``qualifier_fp`` 是该引用上下文的 qualifier 指纹（如 evidence 经 slot_role_map 解引用时该
    slot_role 条目的 qualifiers）——**blocker 1 关键**：同 canonical **异 qualifier**（代表不同
    actor/artifact，非纯别名）→ **不折叠**（v1 分 v2 亦须分）。
    """

    binding: CanonicalBinding
    original_ref: str
    qualifier_fp: Tuple[Tuple[str, str], ...] = ()


# C.9 / blocker 2：artifact 维不可 unresolved —— 空 artifact_key / 悬空 artifact_id（value 空）
# **hard-fail**（不降级 unresolved）。measure/slot/unit/deadline 仍按 C.9 passthrough。
_HARD_FAIL_BINDING_NAMESPACES = {"artifact"}


def _encode_local_ref(
    base: str, qualifier_fp: Tuple[Tuple[str, str], ...]
) -> str:
    """local_ref = base（canonical_key 或 namespaced 原始 ref）；**有** qualifier 指纹时追加其
    canonical 编码（blocker 1：同 canonical 异 qualifier → 异 local_ref → 折叠键不同 → 不合并；
    **空** qualifier → base 原样 → 纯别名同 qualifier 折叠、R3 别名稳定保持）。"""
    if not qualifier_fp:
        return base
    return base + "#q:" + canonical_json([list(p) for p in qualifier_fp])


def _make_binding(
    namespace: str,
    original_ref: Optional[str],
    value_to_canon: Any,
    *,
    qualifier_fp: Tuple[Tuple[str, str], ...] = (),
) -> Optional[_RawBinding]:
    """构造单条 `_RawBinding`（A.4 三态；§1/blocker 1 local_ref 语义；C.9 各维策略；**不吞 hard-fail**）。

    - **artifact 维 value 空**（空 artifact_key / 悬空 artifact_id）→ **hard-fail**
      `artifact_unresolved_hard_fail`（blocker 2 / C.9：artifact 不可 unresolved）。
    - 其余维 value 空 + original_ref 空 → 该维度不存在（返回 None）。
    - resolved：registry 命中 → **local_ref := canonical_key(+qualifier 指纹)**（§1 别名归一 +
      blocker 1 异 qualifier 不折叠）；original_ref 随 `_RawBinding` 传给多目标闸。
    - unresolved：passthrough 维度（measure/slot/unit/deadline）未命中 → canonical_key=""，
      **local_ref := ``namespace:原始ref``(+qualifier)**（namespaced，保 unresolved 区分）。
    - **hard_fail 维度（artifact/formula）未命中 → `CanonicalProfileError` 直穿**——**绝不吞**。
    """
    ref_raw = nfc(str(original_ref)) if original_ref else ""
    empty_val = is_empty_source_value(value_to_canon)
    if empty_val:
        if namespace in _HARD_FAIL_BINDING_NAMESPACES:
            # blocker 2 / C.9：artifact 空键或悬空 artifact_id（无 key 可归一）→ hard-fail。
            raise ObligationContractError(
                f"artifact_unresolved_hard_fail:{namespace}:{ref_raw or '<empty>'}"
            )
        if not ref_raw:
            return None
        binding = CanonicalBinding(
            namespace=namespace,
            resolution="unresolved",
            local_ref=_encode_local_ref(f"{namespace}:{ref_raw}", qualifier_fp),
            canonical_key="",
        )
        return _RawBinding(binding, ref_raw, qualifier_fp)

    # 不吞：hard_fail 维度（artifact/formula）未命中的 CanonicalProfileError 直穿到派生入口。
    res = _CANON_FN[namespace](str(value_to_canon))
    # 多目标闸键：有独立不透明 ref 用之，否则用 canonical（threshold/trigger measure 无独立
    # 编号，`_make_binding(ns, None, measure)`）——两 threshold 同 measure 同键 → 同目标（不冲突）。
    gate_ref = ref_raw if ref_raw else res.canonical_key
    if res.resolution == "resolved":
        binding = CanonicalBinding(
            namespace=namespace,
            resolution="resolved",
            local_ref=_encode_local_ref(res.canonical_key, qualifier_fp),  # §1 + blocker 1
            canonical_key=res.canonical_key,
        )
        return _RawBinding(binding, gate_ref, qualifier_fp)
    # unresolved passthrough：namespaced 原始 ref（gate_ref 保区分）+ qualifier 指纹。
    binding = CanonicalBinding(
        namespace=namespace,
        resolution="unresolved",
        local_ref=_encode_local_ref(f"{namespace}:{gate_ref}", qualifier_fp),
        canonical_key="",
    )
    return _RawBinding(binding, gate_ref, qualifier_fp)


def _canon_scalar(namespace: str, value: Any) -> str:
    """predicate_spec 标量 canonical 字段（passthrough 值可用，非 CanonicalBinding）。

    返回 registry 的 canonical_key（含 passthrough 的 nfc 值）；hard_fail 维度的
    CanonicalProfileError 直穿（本函数三维 measure/unit/time_anchor 均 passthrough）。
    """
    if is_empty_source_value(value):
        return ""
    return _SCALAR_CANON_FN[namespace](str(value)).canonical_key


# ===========================================================================
# §2 聚合闸：CardBindingRegistry（卡级）+ RegimeSignatureRegistry（运行级）
# ===========================================================================


class CardBindingRegistry:
    """卡级聚合闸（`derive_card_blueprints` 收尾，§2）。

    - **跨源项多目标**：同卡内同 `(namespace, 原始 ref)` 解析到多个不同目标
      `(resolution, canonical_key)` → `unresolved_multi_target`（finalize 时逮）。
    - **重复源项**：同 `(channel, source_item_id)` 出现 ≥2 → `duplicate_source_item`
      （record 时立即逮）。

    真卡本无重复源项 / 无跨源项多目标（slot_ref_id / artifact_id / regime_id 卡内唯一）→
    本闸对真卡永不触发；生产异常输入被逮硬拒。
    """

    def __init__(self) -> None:
        self._by_ref: Dict[Tuple[str, str], set] = defaultdict(set)
        self._source_items: set = set()

    def record_binding(
        self, namespace: str, original_ref: str, resolution: str, canonical_key: str
    ) -> None:
        self._by_ref[(namespace, original_ref)].add((resolution, canonical_key))

    def record_source_item(self, channel: str, source_item_id: str) -> None:
        key = (channel, source_item_id)
        if key in self._source_items:
            raise ObligationContractError(f"duplicate_source_item:{channel}")
        self._source_items.add(key)

    def finalize(self) -> None:
        for (namespace, ref), targets in self._by_ref.items():
            if len(targets) > 1:
                raise ObligationContractError(
                    f"unresolved_multi_target:{namespace}:{ref}"
                )


class RegimeSignatureRegistry:
    """运行级 threshold_regime 签名一致性闸（`derive_run_blueprints` 钩子，§2 / A.3）。

    跨卡同 `threshold_regime_id` 的规则侧签名（measure/op/value/unit/qualifiers canonical，
    除 variable_bindings 外）不一致 → `threshold_regime_signature_conflict` hard-fail。
    真卡 41 regime_id 全唯一 → 永不触发；合成/异常输入被逮。
    """

    def __init__(self) -> None:
        self._by_regime: Dict[str, str] = {}

    def record(self, spec: Optional[PredicateSpecV1]) -> None:
        if spec is None or not spec.threshold_regime_id:
            return
        rid = spec.threshold_regime_id
        sig = _threshold_signature(spec)
        prev = self._by_regime.get(rid)
        if prev is not None and prev != sig:
            raise ObligationContractError(f"threshold_regime_signature_conflict:{rid}")
        self._by_regime[rid] = sig


def _finalize_bindings(
    raws: List[Optional[_RawBinding]],
    *,
    registry: Optional[CardBindingRegistry] = None,
    channel: str = "",
) -> Tuple[CanonicalBinding, ...]:
    """A.4 / §2：卡内 `(namespace, 原始 ref)` **恰一目标** → 任何多目标/重复 hard-fail。

    - 去 None（该维度不存在）。
    - 卡内闸①（**同不透明原始 ref**）：一 `(namespace, original_ref)` 解析到不同
      `(resolution, canonical_key)` → `unresolved_multi_target`（一编号多目标，A.4）；
      同 ref 完全重复（同编号出现 ≥2，如 measure_keys=["m.x","m.x"]）→
      `duplicate_local_ref_binding`（A.4 恰一条，**绝不静默压扁多目标/重复源项**）。
    - **§1/blocker 1 折叠（非 hard-fail）**：折叠键 = ``(namespace, resolution, canonical_key,
      qualifier 指纹)``——由 `local_ref` 承载（resolved: canonical_key(+qualifier)、unresolved:
      namespace:ref(+qualifier)）。**纯别名同 qualifier**（异 slot_ref_id 归一同 slot_id、同
      qualifier）→ 同 local_ref → **折叠**（真卡合法，别名稳定 R3）；**同 canonical 异 qualifier**
      （evidence 两 slot_ref 指同 slot_id 但 qualifier 代表不同 actor/artifact）→ 异 local_ref →
      **不折叠**（blocker 1：非纯别名、v1 分 v2 亦分）。
    - registry 提供时逐条喂给 `CardBindingRegistry`（跨源项多目标闸，finalize 时逮）。
    - 全序排序 (namespace, resolution, canonical_key, local_ref)（A.4）。
    """
    items = [r for r in raws if r is not None]
    within: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for r in items:
        key = (r.binding.namespace, r.original_ref)
        target = (r.binding.resolution, r.binding.canonical_key)
        prev = within.get(key)
        if prev is not None:
            loc = f"{channel}:{key[0]}:{key[1]}" if channel else f"{key[0]}:{key[1]}"
            if prev != target:
                raise ObligationContractError(f"unresolved_multi_target:{loc}")
            raise ObligationContractError(f"duplicate_local_ref_binding:{loc}")
        within[key] = target
        if registry is not None:
            registry.record_binding(
                r.binding.namespace, r.original_ref, r.binding.resolution, r.binding.canonical_key
            )
    # §1/blocker 1 折叠：折叠键 = local_ref（编码 canonical_key + qualifier 指纹）→ 异 qualifier
    # 不合、纯别名同 qualifier 合。
    unique: Dict[Tuple[str, str, str, str], CanonicalBinding] = {}
    for r in items:
        b = r.binding
        unique[(b.namespace, b.resolution, b.local_ref, b.canonical_key)] = b
    result = sorted(
        unique.values(),
        key=lambda b: (b.namespace, b.resolution, b.canonical_key, b.local_ref),
    )
    return tuple(result)


def _encode_source_item_id(
    channel: str, primary_id: str, parts: Optional[Dict[str, Any]] = None
) -> str:
    """A.2.4 非阻断⑤ source_item_id 复合键 canonical 编码（定长键集）。"""
    return canonical_json(
        {"channel": channel, "primary_id": nfc(str(primary_id)), "parts": parts or {}}
    )


def _register_source_item(
    registry: Optional[CardBindingRegistry], channel: str, source_item_id: str
) -> None:
    if registry is not None:
        registry.record_source_item(channel, source_item_id)


def _freeze(
    identity: CanonicalObligationIdentity,
    immutable: ImmutablePayload,
    provenance: BlueprintProvenance,
) -> ObligationBlueprint:
    """阶段一冻结：身份哈希此刻定死（不含 run；跨 run 稳定）。"""
    return ObligationBlueprint(
        blueprint_schema=BLUEPRINT_SCHEMA,
        identity=identity,
        canonical_identity_hash=compute_canonical_identity_hash(identity),
        immutable=immutable,
        provenance=provenance,
    )


# ===========================================================================
# §6 formula 登记表（受限表达式 → 规范 AST → 变量/度量精确匹配 → formula_id）
# ===========================================================================

# 受限表达式白名单 AST 节点（多项式：+ - * ** 一元负号 + 名字 + 数字常量）。
_ALLOWED_FORMULA_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)


def _preprocess_formula_expr(expression: str) -> str:
    """规范化表达式文本：去空白、`^`→`**`、补隐式乘（`2n`→`2*n`）。"""
    e = nfc(str(expression)).replace(" ", "").replace("^", "**")
    # 隐式乘法：数字后接名字/左括号（2n / 2( ）→ 插 `*`。
    e = re.sub(r"(\d)([A-Za-z(])", r"\1*\2", e)
    # `)(` / `)名字` / `)数字` → 插 `*`。
    e = re.sub(r"(\))([A-Za-z0-9(])", r"\1*\2", e)
    return e


def _canonicalize_formula_ast(expression: str) -> Tuple[str, Tuple[str, ...]]:
    """受限表达式 → (规范 AST dump, 排序变量符号)；越界节点/解析失败 → `unsupported_formula`。"""
    expr = _preprocess_formula_expr(expression)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ObligationContractError(
            f"unsupported_formula:parse_error:{expression}"
        ) from exc
    symbols: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_FORMULA_NODES):
            raise ObligationContractError(
                f"unsupported_formula:{type(node).__name__}:{expression}"
            )
        if isinstance(node, ast.Name):
            symbols.add(node.id)
    return ast.dump(tree), tuple(sorted(symbols))


@dataclass(frozen=True)
class FormulaRegistryEntry:
    """结构化 formula 登记条目（§6 copilot 结构）。

    - `formula_id`：稳定版本化 id（常量，跨 run/跨 Python 版本稳定）。
    - `canonical_ast`：受限表达式规范 AST dump（运行时精确比对；跨 Python 版本一致性由
      「登记条目与运行时同函数同解释器计算」保证，id 本身是常量不依赖 dump）。
    - `variable_measures`：排序 (symbol, canonical_measure_key)（变量→度量精确匹配）。
    - `output_measure`：公式产出的 canonical 度量（= threshold 的 canonical measure_key）；
      **参与匹配**（blocker 2：`_formula_id` 三元精确比对纳入 output_measure——表达式+变量度量
      相同但产出度量被改 → 不再 fail-open 命中，hard-fail `unsupported_formula`）。
    """

    formula_id: str
    canonical_ast: str
    variable_measures: Tuple[Tuple[str, str], ...]
    output_measure: str


def _build_formula_entry(
    expression: str,
    variable_measures: Tuple[Tuple[str, str], ...],
    output_measure: str,
    formula_id: str,
) -> FormulaRegistryEntry:
    canonical_ast, syms = _canonicalize_formula_ast(expression)
    declared = tuple(sorted(s for s, _m in variable_measures))
    if syms != declared:
        raise ObligationContractError(
            f"formula_registry_symbol_mismatch:{formula_id}:{syms}!={declared}"
        )
    return FormulaRegistryEntry(
        formula_id=formula_id,
        canonical_ast=canonical_ast,
        variable_measures=variable_measures,
        output_measure=output_measure,
    )


# 真语料仅 1 条不同公式（3 卡共用）：`n^2 - 2n + 3`，n → count.pull_test.failed_cumulative，
# 产出 count.pull_test.additional_after_failure。度量经 canonical registry 归一（identity 灌注）。
_FORMULA_ENTRIES: Tuple[FormulaRegistryEntry, ...] = (
    _build_formula_entry(
        "n^2 - 2n + 3",
        (("n", _canon_scalar("measure", "count.pull_test.failed_cumulative")),),
        _canon_scalar("measure", "count.pull_test.additional_after_failure"),
        "formula.pull_test_additional_after_failure",
    ),
)


def _formula_variable_measures(formula: Dict[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """formula.variables[] → 排序 (symbol, canonical_measure_key)（匹配 + spec 绑定共用）。"""
    out: List[Tuple[str, str]] = []
    for v in formula.get("variables", []) or []:
        if isinstance(v, dict):
            out.append(
                (
                    nfc(str(v.get("symbol", ""))),
                    _canon_scalar("measure", v.get("measure_key")),
                )
            )
    return tuple(sorted(out))


def _formula_id(formula: Dict[str, Any], output_measure: str) -> str:
    """受限表达式 + 变量/度量 + **output_measure** 精确匹配登记表 → formula_id；不匹配一律
    `unsupported_formula`（§6 / blocker 2）。

    blocker 2：匹配须**纳入 output_measure**（公式产出的 canonical 度量 = threshold 的
    canonical measure_key）。表达式 + 变量度量相同但产出度量被改（登记式 output 不符）→
    **不再 fail-open 命中**，而 hard-fail `unsupported_formula`。
    """
    expression = formula.get("expression", "")
    canonical_ast, syms = _canonicalize_formula_ast(expression)
    var_measures = _formula_variable_measures(formula)
    for entry in _FORMULA_ENTRIES:
        if (
            entry.canonical_ast == canonical_ast
            and entry.variable_measures == var_measures
            and entry.output_measure == output_measure  # blocker 2：纳入 output_measure
        ):
            return entry.formula_id
    raise ObligationContractError(f"unsupported_formula:unregistered:{expression}")


def _formula_variable_bindings(
    formula: Dict[str, Any],
) -> Tuple[VariableBinding, ...]:
    out = []
    for v in formula.get("variables", []) or []:
        if not isinstance(v, dict):
            continue
        out.append(
            VariableBinding(
                symbol=nfc(str(v.get("symbol", ""))),
                canonical_measure_key=_canon_scalar("measure", v.get("measure_key")),
                qualifier_fingerprint=(),
            )
        )
    out.sort(key=lambda vb: vb.symbol)
    return tuple(out)


def _literal_value(value: Any) -> Tuple[str, str]:
    """规则侧字面阈值 → (literal_value_tag, literal_value_canonical)（C.8）。

    fail-closed（§3）：**拒 Python float** → `canonical_number_float_ingress` hard-fail
    （identity 入口经 Decimal ingress，float 结构上不该出现；漏入即炸）。int/Decimal 走
    canonical_decimal_str，bool/string/list 各按 C.8。
    """
    if value is None:
        return ("none", "")
    if isinstance(value, bool):
        return ("bool", "true" if value else "false")
    if isinstance(value, float):
        raise ObligationContractError(f"canonical_number_float_ingress:{value!r}")
    if isinstance(value, (int, Decimal)):
        return ("decimal", canonical_decimal_str(value))
    if isinstance(value, (list, tuple)):
        tagged = []
        for v in value:
            if isinstance(v, bool):
                tagged.append(("bool", "true" if v else "false"))
            elif isinstance(v, float):
                raise ObligationContractError(f"canonical_number_float_ingress:{v!r}")
            elif isinstance(v, (int, Decimal)):
                tagged.append(("decimal", canonical_decimal_str(v)))
            else:
                tagged.append(("string", nfc(str(v))))
        return ("list", canonical_json(list(in_not_in_sort(tagged))))
    return ("string", nfc(str(value)))


# ===========================================================================
# threshold（源 channel = threshold；含真 threshold_regime_id — 母病锚）
# ===========================================================================


def build_threshold_blueprint(
    card: Any,
    threshold: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`threshold_regimes[]` 一项 → threshold 义务 blueprint（从源头，含真 regime_id）。

    A.3：operator 用**规则侧原始**（`threshold.operator`），**不**用求值后被覆写的 `>=`。
    literal value 用规则侧字面阈值（Decimal ingress），不用运行时算出的 expected。
    """
    ThresholdRegimeDTO.model_validate(threshold)
    regime_id = nfc(str(threshold.get("threshold_regime_id") or ""))
    measure_key = threshold.get("measure_key")
    operator = threshold.get("operator")
    unit = threshold.get("unit")
    time_anchor_key = threshold.get("time_anchor_key")
    value = threshold.get("value")
    formula = threshold.get("formula") if isinstance(threshold.get("formula"), dict) else None

    canon_measure = _canon_scalar("measure", measure_key)
    canon_unit = _canon_scalar("unit", unit)
    canon_time_anchor = _canon_scalar("time_anchor", time_anchor_key)

    is_formula = operator == "formula"
    if is_formula:
        predicate_kind = "threshold_formula"
        source_operator = "formula"
        if formula is None:
            raise ObligationContractError(
                f"threshold_formula_without_formula:{regime_id}"
            )
        # §6 / blocker 2：受限表达式 + 变量度量 + output_measure(=threshold canonical measure_key)
        # 精确匹配；不匹配 → unsupported_formula hard-fail（output 改亦不再 fail-open 命中）。
        formula_id = _formula_id(formula, canon_measure)
        literal_tag = "none"
        literal_canonical = ""
        variable_bindings = _formula_variable_bindings(formula)
    else:
        predicate_kind = "threshold_literal"
        source_operator = str(operator) if operator else ""
        formula_id = ""
        variable_bindings = ()
        literal_tag, literal_canonical = _literal_value(value)

    spec = PredicateSpecV1(
        spec_schema="predicate_spec_v1",
        predicate_kind=predicate_kind,
        threshold_regime_id=regime_id,
        canonical_measure_key=canon_measure,
        source_operator=source_operator,
        literal_value_tag=literal_tag,
        literal_value_canonical=literal_canonical,
        formula_id=formula_id,
        canonical_unit=canon_unit,
        canonical_time_anchor_key=canon_time_anchor,
        threshold_qualifier_fingerprint=_qualifier_fp(threshold.get("qualifiers")),
        variable_bindings=variable_bindings,
    )

    sid = _encode_source_item_id("threshold", regime_id)
    measure_binding = _make_binding("measure", None, measure_key)
    measure_bindings = _finalize_bindings(
        [measure_binding], registry=registry, channel="threshold"
    )
    _register_source_item(registry, "threshold", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="threshold",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=measure_bindings,
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="threshold",
        source_item_id=sid,
        predicate_kind=predicate_kind,
        source_predicate_spec=spec,
        qualifiers=(),
    )
    immutable = ImmutablePayload(
        required=True, canonical_unit=canon_unit, source_operator=source_operator
    )
    provenance = _provenance(
        meta,
        card,
        extra_quote_ids=tuple(str(q) for q in (threshold.get("source_quote_refs") or [])),
    )
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# trigger（源 channel = trigger；predicate_kind ∈ {slot, measure}，spec=None — B1）
# ===========================================================================


def build_trigger_blueprint(
    card: Any,
    trigger: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`trigger_conditions.items[]` 一项 → trigger 义务 blueprint（B1）。

    typed ingress：`predicate_kind ∉ {slot, measure}` → hard-fail `unsupported_predicate_kind`
    （**不静默归 slot**）。operator/expected/unit 是求值产物**不进身份**。
    """
    TriggerItemDTO.model_validate(trigger)
    condition_id = nfc(str(trigger.get("condition_id") or ""))
    predicate_kind = str(trigger.get("predicate_kind") or "")
    if predicate_kind not in {"slot", "measure"}:
        raise ObligationContractError(
            f"unsupported_predicate_kind:trigger:{predicate_kind}"
        )
    slot_ref_id = trigger.get("slot_ref_id")

    # slot_ref → slot_id 经 slot_role_map 解引用（真配对）。**不取首条**（blocker 1）：收集
    # 全部匹配 slot_role 条目、逐条建 slot binding，卡内 slot_ref_id 重复/多目标由闸 hard-fail。
    matches = (
        [
            sr
            for sr in (card.slot_role_map or [])
            if isinstance(sr, dict) and sr.get("slot_ref_id") == slot_ref_id
        ]
        if slot_ref_id
        else []
    )
    map_qualifiers = dict(matches[0].get("qualifiers") or {}) if matches else {}
    qualifiers = dict(trigger.get("qualifiers") or map_qualifiers)

    slot_bindings_raw: List[Optional[_RawBinding]] = []
    measure_bindings_raw: List[Optional[_RawBinding]] = []
    if predicate_kind == "measure":
        pk_identity = "measure"
        measure_key = trigger.get("measure_key")
        measure_bindings_raw.append(_make_binding("measure", None, measure_key))
    else:
        pk_identity = "slot"
        if matches:
            for sr in matches:
                slot_bindings_raw.append(
                    _make_binding("slot", slot_ref_id, sr.get("slot_id"))
                )
        else:
            slot_bindings_raw.append(
                _make_binding("slot", slot_ref_id, trigger.get("slot_id"))
            )

    slot_ref_ids = (str(slot_ref_id),) if slot_ref_id else ()
    # blocker 1：source_item_id 编码 condition_id + slot_ref（不透明引用编号）+ predicate_kind，
    # 足以区分不同引用（两 trigger 同 slot 异 slot_ref/异 condition → 异 source_item → v2 分）。
    sid = _encode_source_item_id(
        "trigger",
        condition_id,
        {
            "slot_ref_id": nfc(str(slot_ref_id)) if slot_ref_id else "",
            "predicate_kind": predicate_kind,
        },
    )
    slot_bindings = _finalize_bindings(
        slot_bindings_raw, registry=registry, channel="trigger"
    )
    measure_bindings = _finalize_bindings(
        measure_bindings_raw, registry=registry, channel="trigger"
    )
    _register_source_item(registry, "trigger", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="trigger",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=slot_bindings,
        artifact_bindings=(),
        measure_bindings=measure_bindings,
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="trigger",
        source_item_id=sid,
        predicate_kind=pk_identity,
        source_predicate_spec=None,  # B1：trigger 不走 predicate_spec
        qualifiers=_qualifier_fp(qualifiers),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta,
        card,
        slot_ref_ids=slot_ref_ids,
        trigger_dependency_ids=(condition_id,) if condition_id else (),
    )
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# slot_role（源 channel = slot_role；无谓词，predicate_kind=""）
# ===========================================================================


def build_slot_role_blueprint(
    card: Any,
    slot_ref: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`slot_role_map[]` 一项（required）→ slot_role 义务 blueprint。

    §1/R5：slot_id resolved → binding local_ref := canonical(slot_id)（同 slot_id 稳定）；
    不透明 slot_ref_id 进 **source_item_id**（同 slot_id 异 slot_ref_id → 哈希变）。
    """
    SlotRoleDTO.model_validate(slot_ref)
    roles = slot_ref.get("roles") or []
    role = roles[0] if roles else None
    slot_id = slot_ref.get("slot_id")
    slot_ref_id = slot_ref.get("slot_ref_id")
    qualifiers = dict(slot_ref.get("qualifiers") or {})
    required = bool(slot_ref.get("required", True))
    kind = _SLOT_ROLE_TO_KIND.get(role, "evidence")

    sid = _encode_source_item_id("slot_role", str(slot_ref_id or ""))
    slot_binding = _make_binding("slot", slot_ref_id, slot_id)
    slot_bindings = _finalize_bindings(
        [slot_binding], registry=registry, channel="slot_role"
    )
    _register_source_item(registry, "slot_role", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind=kind,
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=slot_bindings,
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="slot_role",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=_qualifier_fp(qualifiers),
    )
    immutable = ImmutablePayload(required=required, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta, card, slot_ref_ids=(str(slot_ref_id),) if slot_ref_id else ()
    )
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# workflow_artifact（源 channel = workflow_artifact）
# ===========================================================================


def build_workflow_artifact_blueprint(
    card: Any,
    artifact_item: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`workflow_operands.artifacts[]` 一项 → artifact 义务 blueprint（artifact_id↔key 真配对）。"""
    WorkflowArtifactDTO.model_validate(artifact_item)
    artifact_id = artifact_item.get("artifact_id")
    artifact_key = artifact_item.get("artifact_key")
    sid = _encode_source_item_id(
        "workflow_artifact", str(artifact_id or artifact_key or "")
    )
    artifact_binding = _make_binding("artifact", artifact_id, artifact_key)
    artifact_bindings = _finalize_bindings(
        [artifact_binding], registry=registry, channel="workflow_artifact"
    )
    _register_source_item(registry, "workflow_artifact", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="artifact",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=artifact_bindings,
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="workflow_artifact",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta, card, artifact_local_ids=(str(artifact_id),) if artifact_id else ()
    )
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# evidence（源 channel = evidence；source_item_id 复合键 parts=kind+field_groups）
# ===========================================================================


def _card_artifact_multimap(card: Any) -> Dict[str, List[str]]:
    """卡内 artifact_id → [artifact_key,...]（multimap，不覆盖；blocker 1 一致口径）。"""
    m: Dict[str, List[str]] = defaultdict(list)
    for item in (card.workflow_operands or {}).get("artifacts", []) or []:
        if isinstance(item, dict) and item.get("artifact_id") and item.get("artifact_key"):
            m[str(item["artifact_id"])].append(str(item["artifact_key"]))
    return m


def build_evidence_blueprint(
    card: Any,
    bucket_name: str,
    req: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`evidence_requirements.{bucket}[]` 一项 → evidence/artifact 义务 blueprint。

    source_item_id 复合键：primary_id=evidence_requirement_id，parts={kind,
    required_field_groups, slot_ref_ids, artifact_ids, measure_keys}（blocker 1：编码原始
    引用编号，足以区分不同引用）。artifact_id/slot_ref_id 经卡内 multimap 解引用；slot binding
    携带 slot_role qualifier 指纹（异 qualifier 同 slot_id 不折叠）。
    """
    EvidenceRequirementDTO.model_validate(req)
    default_kind = _BUCKET_DEFAULT_KIND.get(bucket_name, "evidence")
    kind = req.get("evidence_kind") or default_kind
    if kind not in {"artifact", "evidence"}:
        kind = default_kind
    req_id = nfc(str(req.get("evidence_requirement_id") or ""))
    ev_kind = str(req.get("kind") or "")
    field_groups = sorted(nfc(str(g)) for g in (req.get("required_field_groups") or []))
    required = bool(req.get("required", True))

    art_multi = _card_artifact_multimap(card)

    artifact_bindings_raw: List[Optional[_RawBinding]] = []
    for ak in req.get("artifact_keys", []) or []:
        # 系统性清空值前置过滤：**不 pre-filter**——空 artifact_key 送 artifact hard-fail gate
        # （`_make_binding("artifact", None, "")` → `artifact_unresolved_hard_fail`）。注：
        # `artifact_keys` 不在 `EvidenceRequirementDTO`（extra=forbid），带此键的 req 早被
        # 上游 `EvidenceRequirementDTO.model_validate` 拒（此循环对已校验 req 恒空、不可达）；
        # 去 `if ak:` 只为消除模式残留，非行为改变。
        artifact_bindings_raw.append(_make_binding("artifact", None, ak))
    artifact_local_ids: List[str] = []
    for aid in req.get("artifact_ids", []) or []:
        # blocker 1（入口级 fail-closed）：**不 pre-filter 空值**——空串 artifact_id 照样送
        # hard-fail gate（`_make_binding("artifact", "", None)` → 空值 → artifact 维不可
        # unresolved → `artifact_unresolved_hard_fail`）。旧 `if not aid: continue` 会静默返回
        # 零 artifact binding、不报错（`evidence.artifact_ids=[""]` 反例静默跳）。
        keys = art_multi.get(str(aid))
        if keys:
            for key in keys:
                artifact_bindings_raw.append(_make_binding("artifact", str(aid), key))
        else:
            artifact_bindings_raw.append(_make_binding("artifact", str(aid), None))
        artifact_local_ids.append(str(aid))

    slot_bindings_raw: List[Optional[_RawBinding]] = []
    slot_ref_ids: List[str] = []
    srm_multi: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sr in (card.slot_role_map or []):
        if isinstance(sr, dict) and sr.get("slot_ref_id"):
            srm_multi[str(sr["slot_ref_id"])].append(sr)
    for ref in req.get("slot_ref_ids", []) or []:
        entries = srm_multi.get(str(ref))
        if entries:
            for sr in entries:
                # blocker 1：slot binding 携带该 slot_role 条目的 qualifier 指纹——两 slot_ref_id
                # 指同 slot_id 但 qualifier 代表不同 actor/artifact → 异 local_ref → 不折叠。
                slot_bindings_raw.append(
                    _make_binding(
                        "slot",
                        str(ref),
                        sr.get("slot_id"),
                        qualifier_fp=_qualifier_fp(sr.get("qualifiers")),
                    )
                )
        else:
            slot_bindings_raw.append(_make_binding("slot", str(ref), None))
        slot_ref_ids.append(str(ref))
    for sid_val in req.get("slot_ids", []) or []:
        # 系统性清空值前置过滤：**不 pre-filter**——空值送 gate（slot 为 passthrough 维，
        # `_make_binding("slot", "", "")` → 空值+空 ref → None，`_finalize_bindings` 滤除，
        # 行为中性）。注：`slot_ids` 不在 `EvidenceRequirementDTO`（extra=forbid），带此键的
        # req 早被上游 model_validate 拒；此循环对已校验 req 恒空、不可达，去 `if` 仅消模式残留。
        slot_bindings_raw.append(_make_binding("slot", str(sid_val), sid_val))

    measure_bindings_raw: List[Optional[_RawBinding]] = []
    for mk in req.get("measure_keys", []) or []:
        # 系统性清空值前置过滤：**不 pre-filter**——空 measure_key 送 gate（measure 为
        # passthrough 维，`_make_binding("measure", "", "")` → 空值+空 ref → None，
        # `_finalize_bindings` 滤除，行为中性；C.9：measure 维不 hard-fail、可 unresolved）。
        measure_bindings_raw.append(_make_binding("measure", mk, mk))

    # blocker 1：source_item_id 编码**足以区分不同引用**——evidence_requirement_id +
    # 排序后的 slot_ref_ids / artifact_ids / measure_keys（原始引用编号，NFC 升序，顺序无关）。
    source_item_id = _encode_source_item_id(
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
    slot_bindings = _finalize_bindings(
        slot_bindings_raw, registry=registry, channel="evidence"
    )
    artifact_bindings = _finalize_bindings(
        artifact_bindings_raw, registry=registry, channel="evidence"
    )
    measure_bindings = _finalize_bindings(
        measure_bindings_raw, registry=registry, channel="evidence"
    )
    _register_source_item(registry, "evidence", source_item_id)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind=kind,
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=slot_bindings,
        artifact_bindings=artifact_bindings,
        measure_bindings=measure_bindings,
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="evidence",
        source_item_id=source_item_id,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=required, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta,
        card,
        slot_ref_ids=tuple(slot_ref_ids),
        artifact_local_ids=tuple(artifact_local_ids),
        evidence_node_refs=(req_id,) if req_id else (),
    )
    return _freeze(identity, immutable, provenance)


def _assert_evidence_artifact_integrity(card: Any, req: Dict[str, Any]) -> None:
    """blocker 1：evidence 的 artifact 引用完整性闸（**不分 required**，派生筛选**之前**先炸）。

    旧代码只对 `required=True` evidence 建 blueprint（唯一到达 `_make_binding` artifact hard-fail
    gate 的路径）；`required=False` 的 `artifact_ids=[""]` / 悬空 artifact_id 整项被 required 过滤
    跳过 → 绕过 artifact hard-fail（覆盖入口 + 严格入口都不炸，DTO 层 `List[str]` 视空串为合法元素、
    不拦）。本闸对**所有** evidence req（含非必需）逐条把 artifact 引用送 `_make_binding` gate：
    空 artifact_key / 空-或-悬空 artifact_id → `artifact_unresolved_hard_fail`（C.9：artifact 维
    不可 unresolved）。**不 pre-filter 空值**；与 `build_evidence_blueprint` 内 artifact 解析口径
    一致（同 `_card_artifact_multimap` 解引用）。真语料 370 evidence 全 required、无空/悬空 artifact
    → 本闸对真卡永不触发（见交付报告全卡实测）。
    """
    art_multi = _card_artifact_multimap(card)
    for ak in req.get("artifact_keys", []) or []:
        _make_binding("artifact", None, ak)  # 空 artifact_key → artifact hard-fail
    for aid in req.get("artifact_ids", []) or []:
        keys = art_multi.get(str(aid))
        if keys:
            for key in keys:
                _make_binding("artifact", str(aid), key)
        else:
            _make_binding("artifact", str(aid), None)  # 空/悬空 artifact_id → artifact hard-fail


# ===========================================================================
# definition（源 channel = definition；无谓词，predicate_kind=""）
# ===========================================================================


def build_definition_blueprint(
    card: Any,
    definition: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`definitions[]` 一项 → definition 义务 blueprint（真实字段 definition_id/term_key）。"""
    DefinitionDTO.model_validate(definition)
    definition_id = nfc(str(definition.get("definition_id") or ""))
    term_key = nfc(str(definition.get("term_key") or ""))
    sid = _encode_source_item_id("definition", definition_id, {"term_key": term_key})
    _register_source_item(registry, "definition", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="definition",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="definition",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta,
        card,
        extra_quote_ids=tuple(
            str(q) for q in (definition.get("source_quote_refs") or [])
        ),
    )
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# exception（源 channel = exception；无谓词；⚠️ 真卡语料 0 条，code path 就位）
# ===========================================================================


def build_exception_blueprint(
    card: Any,
    exc: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`exceptions[]` 一项 → exception 义务 blueprint（真卡语料 0 条，就位供合成单测）。"""
    ExceptionDTO.model_validate(exc)
    slot_id = exc.get("slot_id")
    exception_kind = nfc(str(exc.get("exception_kind") or ""))
    sid = _encode_source_item_id("exception", exception_kind)
    slot_binding = _make_binding("slot", slot_id, slot_id)
    slot_bindings = _finalize_bindings(
        [slot_binding], registry=registry, channel="exception"
    )
    _register_source_item(registry, "exception", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="exception",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=slot_bindings,
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="exception",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=_qualifier_fp(exc.get("qualifiers")),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# §5 applicability（源 channel = applicability；scope-audit 义务，scope=building）
# ===========================================================================


def _applicability_sid_from_dict(applicability: Dict[str, Any]) -> str:
    """applicability scope-audit source_item_id（**单一构造点**，`build_applicability_blueprint`
    与 catalog/declare 五元组侧共用，字节一致）：regime / subject / building_scope / component_scope
    进 parts（NFC 升序），channel/primary_id 常量字面量 "applicability"。
    """
    regime = nfc(str(applicability.get("regime") or ""))
    subject = nfc(str(applicability.get("subject") or ""))
    building_scope = sorted(nfc(str(x)) for x in (applicability.get("building_scope") or []))
    component_scope = sorted(
        nfc(str(x)) for x in (applicability.get("component_scope") or [])
    )
    return _encode_source_item_id(
        "applicability",
        "applicability",
        {
            "regime": regime,
            "subject": subject,
            "building_scope": building_scope,
            "component_scope": component_scope,
        },
    )


def _applicability_sid(card: Any) -> str:
    """卡的 applicability scope-audit SID（declare 五元组侧入口，读 `card.applicability`）。"""
    applicability = card.applicability if isinstance(card.applicability, dict) else {}
    return _applicability_sid_from_dict(dict(applicability))


def build_applicability_blueprint(
    card: Any,
    applicability: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`applicability` 单 dict → scope-audit 义务 blueprint（§5，A.6 有映射）。

    scope 决定字段（regime / subject / building_scope / component_scope）编入 source_item_id
    的 parts（source_channel=applicability, primary_id="applicability"）；phase / actors /
    exclusions 显式**不进身份**（explicitly_ignored，`evaluate_applicability` 未消费或 scope
    匹配显式跳过）。scope=building（§5：applicability 是楼级 scope-audit，非 fragment）。

    ⚠️ 据实报：`ApplicabilityDTO.building_scope/component_scope` 声明为 `List[str]`
    （source_dtos），而运行期求值器 `applicability.py:evaluate_applicability` 按 **dict**
    处理（`_scope_conflicts` / `_match_component_scope` 迭代 `.items()`）——DTO 与求值器
    类型不一致（见交付报告「与真卡/求值器不符处」）。本 blueprint **按 DTO 类型（列表）**
    编码进 source_item_id（NFC 升序），不触求值器路径（blind：identity 不消费求值语义）。
    """
    ApplicabilityDTO.model_validate(applicability)
    sid = _applicability_sid_from_dict(applicability)
    _register_source_item(registry, "applicability", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="scope_audit",
        scope=ObligationScope(kind="building", scope_id=""),  # §5：楼级 scope-audit
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="applicability",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# §3 两类控制审计蓝图（identity-v5 现网键切换增补 §3.4）——scope-audit 身份，无谓词类。
#   两 channel（structural_scope_audit / trigger_aggregation_audit）均落无谓词分支
#   （predicate_kind=""、source_predicate_spec=None）；kind 全 "scope_audit"（不新起 kind，
#   channel+SID 已足够区分）。scope 唯一编码在 identity.scope（SID parts 不重复放 scope）。
#
# 下列卡结构读取辅助（`_card_qualifier_values` / `_card_component_types` /
# `_card_is_fragment_scoped`）**镜像 `validator.py` 主循环现网实现**（validator.py:932-959），
# 与判定读径逐字节同源，供 catalog scope 迭代 + 审计身份材料共用（spec §2.2 / §5.3.2）。
# ===========================================================================

# fragment 承载域（镜像 validator.py:806）：卡内任一 slot 的 semantic_domain 落这些域 → 该卡
# 按 (card × fragment) 逐 fragment 物化。
_FRAGMENT_DOMAINS = {"defect", "repair", "risk", "scope", "verification"}


def _card_qualifier_values(card: Any, qkey: str) -> set:
    """卡引用的某限定符键并集（镜像 validator.py:939-956）。

    = 全 slot_role_map qualifiers（覆盖 trigger 经 slot_ref_id 引用的）∪ 各 trigger item
    自带 qualifiers 的 qkey（字符串值）。**规则侧要求**——不读运行态事实（blind：审计身份
    只含规则要求集，不含实际楼况）。
    """
    vals: set = set()
    for ref in card.slot_role_map or []:
        q = _safe(ref, "qualifiers") or {}
        v = q.get(qkey) if isinstance(q, dict) else None
        if isinstance(v, str) and v:
            vals.add(v)
    for trig in (card.trigger_conditions or {}).get("items", []) or []:
        q = _safe(trig, "qualifiers") or {}
        v = q.get(qkey) if isinstance(q, dict) else None
        if isinstance(v, str) and v:
            vals.add(v)
    return vals


def _card_component_types(card: Any) -> set:
    """卡引用的 component_type_key 要求集（镜像 validator.py:958-959）。"""
    return _card_qualifier_values(card, "component_type_key")


def _card_is_fragment_scoped(card: Any, slot_domain: Dict[str, str]) -> bool:
    """卡是否 fragment 承载（镜像 validator.py:932-937）。

    `slot_domain`：slot_id → semantic_domain 映射（源 `rule_slice.semantic_slots`，
    catalog 侧由调用方传入以与判定读径同源）。卡内任一 slot_role_map ref 的 slot_id 的
    semantic_domain ∈ `_FRAGMENT_DOMAINS` → True。

    🔧 **DEBT-085 件二·声明读取路径的空转钩位（第一步声明期，此处不接线）**：
    显式声明落在两张绑定表的 `granularity_declaration` 行字段。
    **声明期只登记不消费**，本镜像与 `validator._card_is_fragment_scoped`
    今天仍逐字节同源、行为逐位不变。第二步接线时**两处必须同批改**——
    只改一处会让过渡期产出按镜像不同的两套判定（kimi 过渡期风险点名项）。
    """
    for ref in card.slot_role_map or []:
        sid = str(_safe(ref, "slot_id") or "")
        if slot_domain.get(sid, "") in _FRAGMENT_DOMAINS:
            return True
    return False


def _member_trigger_sid(trigger: Dict[str, Any]) -> str:
    """成员 trigger 蓝图 source_item_id（**与 `build_trigger_blueprint` 冻结编码字节一致**：
    condition_id + parts{slot_ref_id, predicate_kind}）。供 trigger 聚合审计 SID 引用其构成 trigger。
    """
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


def _structural_audit_sid(card: Any) -> str:
    """结构审计蓝图 source_item_id（§3.4.1 冻结）：channel/primary_id 常量字面量
    "structural_scope_audit"；parts = 规则侧 component_type_key / location_class_key **要求集**
    （NFC 后去重再升序——`{"é","é"}` NFC 后同值须去重成 canonical set）。scope 不进 SID。
    """
    return _encode_source_item_id(
        "structural_scope_audit",
        "structural_scope_audit",
        {
            "component_type_key": sorted(
                {nfc(str(x)) for x in _card_component_types(card)}
            ),
            "location_class_key": sorted(
                {nfc(str(x)) for x in _card_qualifier_values(card, "location_class_key")}
            ),
        },
    )


def _trigger_agg_audit_sid(card: Any) -> str:
    """trigger 聚合审计蓝图 source_item_id（§3.4.2 冻结）：channel/primary_id 常量字面量
    "trigger_aggregation_audit"；parts = trigger_conditions.logic + 成员 trigger 蓝图 SID 排序集
    （NFC 升序）。scope 不进 SID。
    """
    tc = card.trigger_conditions or {}
    items = tc.get("items", []) or []
    return _encode_source_item_id(
        "trigger_aggregation_audit",
        "trigger_aggregation_audit",
        {
            "logic": nfc(str(tc.get("logic", "all"))),
            "member_trigger_source_item_ids": sorted(
                _member_trigger_sid(tr) for tr in items if isinstance(tr, dict)
            ),
        },
    )


def build_structural_scope_audit_blueprint(
    card: Any,
    fragment_id: str,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """DEBT-050 fragment 结构 NA 审计蓝图（§3.4.1，fragment scope）。

    身份材料 = 规则侧 `component_type_key` / `location_class_key` 要求集（`_structural_audit_sid`）
    + fragment scope；**不含实际楼况事实**（事实只决定该审计是否触发=状态，不进身份）。
    fragment 归属唯一编码在 `identity.scope.scope_id`。
    """
    sid = _structural_audit_sid(card)
    _register_source_item(registry, "structural_scope_audit", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="scope_audit",
        scope=ObligationScope(kind="fragment", scope_id=str(fragment_id)),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="structural_scope_audit",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


def build_trigger_aggregation_audit_blueprint(
    card: Any,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """trigger 聚合 false 审计蓝图（§3.4.2，building/fragment scope 随 meta.fragment_id）。

    身份材料 = `logic` + 成员 trigger 蓝图 SID 排序集（`_trigger_agg_audit_sid`）+ 当前 scope
    （`identity.scope`，由 `_scope_from_meta(meta)` 定）。成员 SID 复用 `_member_trigger_sid`
    （与 trigger channel 蓝图同一编码），使聚合审计精确指向其构成 trigger、不与任何单条 trigger
    蓝图或 applicability 蓝图撞身份。
    """
    sid = _trigger_agg_audit_sid(card)
    _register_source_item(registry, "trigger_aggregation_audit", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="scope_audit",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="trigger_aggregation_audit",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# §2 workflow_deadline（源 channel = workflow_deadline；无谓词，独立 kind=deadline 义务）
# ===========================================================================


def _canonical_offset_value(value: Any) -> str:
    """deadline offset_value → canonical decimal 字符串（C.8 Decimal ingress，拒 Python float）；
    缺省（键不存在，`.get` → None）→ `""`（§2.4）。

    identity 入口经 Decimal 读径（`derive_covered_blueprints_from_bundle`）→ offset_value 落
    int/Decimal，float 结构上不该出现；漏入即 hard-fail（镜像 `_literal_value` §3 fail-closed）。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ObligationContractError(f"canonical_number_bool_not_allowed:offset_value:{value!r}")
    if isinstance(value, float):
        raise ObligationContractError(f"canonical_number_float_ingress:{value!r}")
    if isinstance(value, (int, Decimal)):
        return canonical_decimal_str(value)
    return canonical_decimal_str(str(value))  # 字符串数字词元（Decimal 读径给 int/Decimal，容忍）


def _deadline_binding_from_dict(deadline: Dict[str, Any]) -> DeadlineBinding:
    """`workflow_operands.deadlines[]` 一项 → 完整 `DeadlineBinding`（§2.4 canonical 口径，B2 5 元复合键）。

    **单一权威构造点**：workflow_deadline channel（`build_workflow_deadline_blueprint`）与 node 身份
    内嵌（`_resolve_node_deadline_bindings`）均调本函数 → 同一 deadline 定义产**字节相同**的
    DeadlineBinding 值对象（§2.5 判据 4：node 内嵌与 channel 承载同值对象）。

    - resolution：`deadline_id` 经 C.7 deadline registry 判命中（真卡 `ddl01` 卡内句柄、registry
      不命中 → unresolved；unresolved → canonical_key=""、local_ref="deadline:<id>"）。
    - relation / time_anchor_key：C.7 `canonicalize_deadline`（passthrough 值 = NFC；真卡 relation
      ∈ {within,before,same_day_as} 恒非空 → validator 满足）。
    - offset_value：C.8 `canonical_decimal_str`（拒 float）；缺省 → ""。
    - offset_unit：C.4 `canonicalize_unit`；缺省 → ""（**v1 未读，此处补齐读取，不动比较语义**，§2.4）。
    """
    deadline_id = nfc(str(deadline.get("deadline_id") or ""))
    if deadline_id:
        res = canonicalize_deadline(deadline_id)
        if res.resolution == "resolved":
            resolution = "resolved"
            canonical_key = res.canonical_key
            local_ref = canonical_key
        else:
            resolution = "unresolved"
            canonical_key = ""
            local_ref = f"deadline:{deadline_id}"
    else:
        resolution = "unresolved"
        canonical_key = ""
        local_ref = "deadline:"
    return DeadlineBinding(
        namespace="deadline",
        resolution=resolution,
        local_ref=local_ref,
        canonical_key=canonical_key,
        relation=_canon_scalar("time_anchor", deadline.get("relation")),
        offset_value=_canonical_offset_value(deadline.get("offset_value")),
        offset_unit=_canon_scalar("unit", deadline.get("offset_unit")),
        time_anchor_key=_canon_scalar("time_anchor", deadline.get("time_anchor_key")),
    )


def build_workflow_deadline_blueprint(
    card: Any,
    deadline: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`workflow_operands.deadlines[]` 一项 → workflow_deadline 义务 blueprint（§2，无谓词类）。

    source_item_id = encode("workflow_deadline", deadline_id, parts={})（§2.3，单键载体，
    同 workflow_artifact / definition 模式）；DeadlineBinding 完整复合键灌进 `deadline_bindings`
    （§2.4）。kind="deadline"（镜像 v1 `_new_obligation(..., "deadline", ...)`）。
    """
    deadline_id = nfc(str(deadline.get("deadline_id") or ""))
    sid = _encode_source_item_id("workflow_deadline", deadline_id, {})
    binding = _deadline_binding_from_dict(deadline)
    _register_source_item(registry, "workflow_deadline", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="deadline",
        scope=_scope_from_meta(meta),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(binding,),
        time_anchor_bindings=(),
        source_channel="workflow_deadline",
        source_item_id=sid,
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


# ===========================================================================
# obligation_graph（源 channel = obligation_graph）
#   - prohibition node → predicate_kind="prohibition"（NON_THRESHOLD all-empty spec）
#   - 普通 obligation / 升级 escalation node → predicate_kind = raw node_kind、spec=None（v4 放宽）
#   - method 产出 node → 额外 method-derived blueprint（parts={"derived":"method"}，§3.4）
#   - edge → predicate_kind="obligation_edge"（三元组派生 edge_id）
#   - raw-kind 闸 `_assert_known_node_kind`：未知 raw node_kind → hard-fail（§3.1.1）
# ===========================================================================


def _prohibition_predicate_spec() -> PredicateSpecV1:
    """prohibition 谓词 spec（NON_THRESHOLD：所有 threshold-scoped 载荷清空，A.2.3）。"""
    return PredicateSpecV1(
        spec_schema="predicate_spec_v1",
        predicate_kind="prohibition",
        threshold_regime_id="",
        canonical_measure_key="",
        source_operator="",
        literal_value_tag="none",
        literal_value_canonical="",
        formula_id="",
        canonical_unit="",
        canonical_time_anchor_key="",
        threshold_qualifier_fingerprint=(),
        variable_bindings=(),
    )


def _obligation_edge_predicate_spec() -> PredicateSpecV1:
    """obligation_edge 谓词 spec（NON_THRESHOLD）。"""
    return PredicateSpecV1(
        spec_schema="predicate_spec_v1",
        predicate_kind="obligation_edge",
        threshold_regime_id="",
        canonical_measure_key="",
        source_operator="",
        literal_value_tag="none",
        literal_value_canonical="",
        formula_id="",
        canonical_unit="",
        canonical_time_anchor_key="",
        threshold_qualifier_fingerprint=(),
        variable_bindings=(),
    )


def _assert_known_node_kind(raw_node: Any) -> None:
    """§3.1.1 raw-kind 闸：v2 STRICT 派生入口在 `ObligationNodeDTO.from_dict` **归一之前**用 **raw**
    `node_kind` 字符串判——未知 raw node_kind（∉ {obligation,prohibition,escalation}）→ hard-fail
    `unknown_node_kind`（fail-closed，与真模型缺口同级语义）。

    **不改 v1 行为**：v1 求值链走 `from_dict` 归一（未知 → obligation），旧测 `node_kind="duty"`
    归一 obligation 语义保留（本闸只在 v2 STRICT 派生入口，不进 v1 求值链）。
    """
    rk = raw_node.get("node_kind", "obligation") if isinstance(raw_node, dict) else "obligation"
    if rk not in {"obligation", "prohibition", "escalation"}:
        raise ObligationContractError(f"unknown_node_kind:{rk}")


def _resolve_node_deadline_bindings(
    card: Any, node: ObligationNodeDTO
) -> Tuple[DeadlineBinding, ...]:
    """`node.deadline_ids` → 对同卡 `workflow_operands.deadlines[]` **解引用**得已解引用的完整
    DeadlineBinding tuple（§2.5/§3.2 option ii：node 身份内嵌与 workflow_deadline channel 同值对象）。

    逐 `deadline_id` 在同卡 deadlines 找定义（真卡零悬空、恒命中，§1.3），经 `_deadline_binding_from_dict`
    （§2.4 同一 canonical 口径）构 DeadlineBinding、NFC 升序去重成 tuple（真卡每 node 恰 1 deadline_id
    → 单元素）。悬空（真卡无）→ hard-fail `dangling_node_deadline_ref`（fail-closed，不静默丢）。
    """
    wf = card.workflow_operands or {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for d in wf.get("deadlines", []) or []:
        if isinstance(d, dict) and d.get("deadline_id"):
            by_id[str(d["deadline_id"])] = d
    raws: List[DeadlineBinding] = []
    for did in node.deadline_ids:
        d = by_id.get(str(did))
        if d is None:
            raise ObligationContractError(
                f"dangling_node_deadline_ref:{nfc(str(node.obligation_node_id))}:{did}"
            )
        raws.append(_deadline_binding_from_dict(d))
    unique: Dict[str, DeadlineBinding] = {}
    for b in raws:
        unique[canonical_json(b.model_dump())] = b
    return tuple(
        sorted(unique.values(), key=lambda b: canonical_json(b.model_dump()))
    )


def _method_keys_allowed(card: Any) -> List[Any]:
    return (card.workflow_operands or {}).get("method_keys_allowed", []) or []


def _method_keys_qualifiers(card: Any) -> Tuple[Tuple[str, str], ...]:
    """`workflow_operands.method_keys_allowed[]` → canonical qualifier 指纹（§3.4②）。

    **单一权威口径**：node-main（`build_obligation_node_blueprint`，base_kind=='method' 时）与
    method-derived（`build_method_derived_blueprint`）**共用本函数** → 同源 method_keys 产**字节相同**的
    qualifiers 条目（形如 `("method_key", nfc(k))` 逐 key 一条）。改 method_keys → 两身份 qualifiers
    同步变（母病断根：v4 A.6 L428「改值→变」）。"""
    return qualifier_fingerprint(
        [
            ("method_key", str(k))
            for k in _method_keys_allowed(card)
            if not is_empty_source_value(k)
        ]
    )


def _node_produces_method(card: Any, node: ObligationNodeDTO) -> bool:
    """node 是否会产 v1 method 子义务（`refine_action_kind→method` 且卡有 `method_keys_allowed`，
    镜像 `evaluate_obligation_node` L1636-1642 追加条件）。"""
    return bool(_method_keys_allowed(card)) and (
        refine_action_kind(node.node_kind, node.action) == "method"
    )


def _node_method_separable(card: Any, node: ObligationNodeDTO) -> bool:
    """method 子义务与 node-main **结构上可分**（§3.4③ blocker 1 设计修正）——**仅可分才建独立
    method-derived blueprint**。

    可分判据（纯卡结构静态可判，**与 `_declared_covered_source_items` 静态登记同条件**）：node 带非空
    `artifact_ids`/`deadline_ids` 等 **v1 dedupe 区分键**（`validator.py:197-211`：dedupe_key 含
    `sorted(artifact_ids)` L207 / `sorted(deadline_ids)` L208；node-main 主义务携 `list(node.artifact_ids)`
    / `list(node.deadline_ids)`（`obligation_deriver.py:1556-1557`），method 子义务**不携**这些字段
    （`_evaluate_method_obligation` common 无 artifact/deadline，`obligation_deriver.py:1780-1787`））→
    node-main dedupe_key ≠ method-sub dedupe_key → v1 `sort_and_dedupe` **不折叠**（真卡 5 卡）。

    **不可分（真卡 2 卡，node 无区分键）**：node-main 与 method-sub dedupe_key 恒同 → v1 **必折叠成 1 条**。
    此时**不建** method-derived blueprint；其 method 子义务（若 v1 产出）**配回 node-main blueprint**
    （阶段二 assemble → 两 ObligationV2 同 canonical_identity_hash → finalize merge 成 1 条 → v2 净 1 ==
    v1 净 1）。若仍建独立 method-derived（parts 异 → hash 异 → finalize 不折）则 **v2 净 2 ≠ v1 净 1**
    （codex 逮的「集合投影掩盖净集真差」）。"""
    return _node_produces_method(card, node) and (
        bool(node.artifact_ids) or bool(node.deadline_ids)
    )


def build_obligation_node_blueprint(
    card: Any,
    node_raw: Any,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """`obligation_graph.nodes[]` 一项 → node 义务 blueprint（v4 放宽全 3 种 node_kind）。

    - **prohibition node** → predicate_kind="prohibition" + NON_THRESHOLD all-empty spec（历史标记）。
    - **普通 obligation / 升级 escalation node** → predicate_kind = **raw node_kind**（携 raw 补
      `refine_action_kind` 有损洞：obligation↔escalation 变形失效，§3.1）、source_predicate_spec=None。
    - **node.deadline_ids → identity**（§2.5 option ii）：对同卡 deadlines 解引用 → `deadline_bindings`
      内嵌已解引用的完整 DeadlineBinding（与 workflow_deadline channel 同值对象、字节相同）。
    """
    node = (
        node_raw
        if isinstance(node_raw, ObligationNodeDTO)
        else ObligationNodeDTO.from_dict(dict(node_raw))
    )
    base_kind = refine_action_kind(node.node_kind, node.action)
    satisfaction_slot_refs = _node_satisfaction_slot_refs(card, node)
    satisfaction_slot_bindings = _finalize_bindings(
        [
            _make_binding(
                "slot",
                str(ref.get("slot_ref_id") or ""),
                ref.get("slot_id"),
                qualifier_fp=_qualifier_fp(dict(ref.get("qualifiers") or {})),
            )
            for ref in satisfaction_slot_refs
        ],
        registry=registry,
        channel="obligation_graph",
    )
    art_multi = _card_artifact_multimap(card)
    artifact_bindings_raw: List[Optional[_RawBinding]] = []
    artifact_local_ids: List[str] = []
    for aid in node.artifact_ids:
        # blocker 2（入口级 fail-closed）：**不 pre-filter 空值**——空串/None artifact_id 照样送
        # hard-fail gate（`_make_binding("artifact", "", None)` → 空值 → artifact 维不可
        # unresolved → `artifact_unresolved_hard_fail`）。
        keys = art_multi.get(str(aid))
        if keys:
            for key in keys:
                artifact_bindings_raw.append(_make_binding("artifact", str(aid), key))
        else:
            artifact_bindings_raw.append(_make_binding("artifact", str(aid), None))
        artifact_local_ids.append(str(aid))

    sid = _encode_source_item_id("obligation_graph", nfc(str(node.obligation_node_id)))
    artifact_bindings = _finalize_bindings(
        artifact_bindings_raw, registry=registry, channel="obligation_graph"
    )
    deadline_bindings = _resolve_node_deadline_bindings(card, node)  # §2.5/§3.2 内嵌
    _register_source_item(registry, "obligation_graph", sid)

    if node.node_kind == "prohibition":
        predicate_kind = "prohibition"
        predicate_spec: Optional[PredicateSpecV1] = _prohibition_predicate_spec()
    else:
        # v4 放宽：普通/升级 node predicate_kind = raw node_kind、spec=None（§3.1）。
        predicate_kind = node.node_kind
        predicate_spec = None

    # blocker 2（§3.4②）：base_kind=='method' 的 node-main 判定**直接依赖** method_keys_allowed
    # （`_evaluate_node_main` L1665-1703：空→closed/not_applicable 空判、非空→白名单闭包判 open/closed）
    # → 规则侧判定材料变而 node-main hash 不变 = 身份缺失。故 method 产出 node 的 **node-main 身份也灌
    # method_keys → qualifiers**（与 method-derived 同源 `_method_keys_qualifiers`，字节相同）；改 method_keys
    # → node-main hash 亦变。非 method node（base_kind != method）判定不涉 method_keys → qualifiers=()。
    node_qualifiers: Tuple[Tuple[str, str], ...] = (
        _method_keys_qualifiers(card) if base_kind == "method" else ()
    )

    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind=base_kind,
        scope=_scope_from_meta(meta),
        obligation_node_id=nfc(str(node.obligation_node_id)),
        obligation_edge_ids=(),
        actor=nfc(str(node.actor or "")),
        action=nfc(str(node.action or "")),
        recipient_ids=tuple(sorted(nfc(str(r)) for r in node.recipient_ids)),
        slot_bindings=satisfaction_slot_bindings,
        artifact_bindings=artifact_bindings,
        measure_bindings=(),
        deadline_bindings=deadline_bindings,
        time_anchor_bindings=(),
        source_channel="obligation_graph",
        source_item_id=sid,
        predicate_kind=predicate_kind,
        source_predicate_spec=predicate_spec,
        qualifiers=node_qualifiers,
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta,
        card,
        slot_ref_ids=tuple(
            str(ref.get("slot_ref_id"))
            for ref in satisfaction_slot_refs
            if ref.get("slot_ref_id")
        ),
        artifact_local_ids=tuple(artifact_local_ids),
        trigger_dependency_ids=tuple(
            nfc(str(t)) for t in node.trigger_condition_ids if t
        ),
    )
    return _freeze(identity, immutable, provenance)


def build_method_derived_blueprint(
    card: Any,
    node_raw: Any,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """method 产出 node → **额外** method-derived blueprint（§3.4①，承载 v1 追加的独立 method 子义务）。

    source_item_id = encode("obligation_graph", node_id, parts={"derived":"method"}) → 与 node-main
    （parts={}）**同 channel 同 node_id 异 parts** → 身份不撞（复合键 parts 即区分维）。
    kind="method"（镜像 v1 method 子义务 kind）；predicate_kind = raw node_kind（真卡恒 obligation）、
    spec=None（复用 §3.1 {obligation,escalation}→spec None 分支）。`method_keys_allowed` → qualifiers
    （§3.4②，qualifier canonical 口径：改 method_keys → hash 变；v1 `_evaluate_node_main` 亦用
    method_keys 判 open/closed，故 **node-main 同灌**——共享 `_method_keys_qualifiers` 字节相同）。
    """
    node = (
        node_raw
        if isinstance(node_raw, ObligationNodeDTO)
        else ObligationNodeDTO.from_dict(dict(node_raw))
    )
    sid = _encode_source_item_id(
        "obligation_graph", nfc(str(node.obligation_node_id)), {"derived": "method"}
    )
    _register_source_item(registry, "obligation_graph", sid)
    qualifiers = _method_keys_qualifiers(card)  # §3.4②：与 node-main 同源，字节相同
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="method",
        scope=_scope_from_meta(meta),
        obligation_node_id=nfc(str(node.obligation_node_id)),
        obligation_edge_ids=(),
        actor=nfc(str(node.actor or "")),
        action=nfc(str(node.action or "")),
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="obligation_graph",
        source_item_id=sid,
        predicate_kind=node.node_kind,  # raw node_kind（真卡恒 obligation），spec=None
        source_predicate_spec=None,
        qualifiers=qualifiers,
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(
        meta,
        card,
        trigger_dependency_ids=tuple(
            nfc(str(t)) for t in node.trigger_condition_ids if t
        ),
    )
    return _freeze(identity, immutable, provenance)


# ---------------------------------------------------------------------------
# obligation_graph edge 审计三态身份（identity-v5 §3.4.3，codex 阻断 1 修订）
#   一条 edge 落 dangling / unknown-relation 分身 / inactive-target 聚合三态之一。
#   单一 SID 构造点（blueprint 侧 / declare 五元组侧 / 令牌关联侧共用，字节一致杜绝漂移）。
# ---------------------------------------------------------------------------
_KNOWN_EDGE_RELATIONS = {"if_failed_then", "if_unable_then"}


def _edge_dangling_sid(edge_id: str) -> str:
    """dangling edge 审计 SID（§3.4.3）：primary=edge_id，parts `{"edge_audit":"dangling"}`。"""
    return _encode_source_item_id(
        "obligation_graph", nfc(str(edge_id)), {"edge_audit": "dangling"}
    )


def _edge_unknown_relation_sid(edge_id: str, member: str) -> str:
    """unknown-relation 分身审计 SID（§3.4.3）：primary=edge_id，parts 带 member（source/target）
    判别 → source/target 两分身异身份（v5 不误合并）。"""
    return _encode_source_item_id(
        "obligation_graph",
        nfc(str(edge_id)),
        {"edge_audit": "unknown_relation", "member": str(member)},
    )


def _edge_inactive_target_sid(target_id: str, edge_ids: List[str]) -> str:
    """inactive-target 聚合审计 SID（§3.4.3）：primary=target_id，parts 含**完整 edge SID 排序集**
    `{"edges": sorted(edge_ids)}` → 改/移除任一 edge 改身份（不再丢 min 外 edge）。"""
    return _encode_source_item_id(
        "obligation_graph",
        nfc(str(target_id)),
        {
            "edge_audit": "inactive_target",
            "edges": sorted(nfc(str(e)) for e in edge_ids),
        },
    )


def _card_edge_audit_specs(card: Any) -> List[Tuple]:
    """一张卡的 edge 审计三态**静态分类**（§5.3.3，镜像 `evaluate_obligation_edges` 分支）。

    返回 spec tuple 列表（blueprint 侧与 declare 侧**单一分类器**，杜绝漂移）：
      ("dangling", edge_id)
      ("unknown", edge_id, member, member_node_id)      # member ∈ {"source","target"}
      ("inactive_target", target_id, tuple(sorted(edge_ids)))

    static-only：与运行态是否触发正交（dangling/unknown 恒产、inactive-target 仅 target 未激活时
    产；未产则蓝图不消费、不报 miss，同 §5.3.1 条件绑定模式）。
    """
    graph = card.obligation_graph or {}
    nodes_by_id = {
        str(n.get("obligation_node_id")): n
        for n in graph.get("nodes", []) or []
        if isinstance(n, dict)
    }
    edge_dtos = [
        e if isinstance(e, ObligationEdgeDTO) else ObligationEdgeDTO.from_dict(dict(e))
        for e in graph.get("edges", []) or []
        if isinstance(e, (dict, ObligationEdgeDTO))
    ]
    specs: List[Tuple] = []
    activation_edges: Dict[str, List[str]] = {}  # target_id -> known-relation edge_ids
    for edge in sorted(
        edge_dtos, key=lambda e: (e.source_node_id, e.target_node_id, e.relation)
    ):
        if (
            edge.source_node_id not in nodes_by_id
            or edge.target_node_id not in nodes_by_id
        ):
            specs.append(("dangling", edge.obligation_edge_id))
            continue
        if edge.relation not in _KNOWN_EDGE_RELATIONS:
            specs.append(
                ("unknown", edge.obligation_edge_id, "source", edge.source_node_id)
            )
            specs.append(
                ("unknown", edge.obligation_edge_id, "target", edge.target_node_id)
            )
            continue
        activation_edges.setdefault(edge.target_node_id, []).append(
            edge.obligation_edge_id
        )
    for target_id in sorted(activation_edges):
        specs.append(
            ("inactive_target", target_id, tuple(sorted(activation_edges[target_id])))
        )
    return specs


def edge_audit_spec_source_item(spec: Tuple) -> Tuple[str, str]:
    """edge 审计 spec → (source_channel, source_item_id)（declare 五元组侧 / blueprint manifest 共用）。"""
    tag = spec[0]
    if tag == "dangling":
        return ("obligation_graph", _edge_dangling_sid(spec[1]))
    if tag == "unknown":
        return ("obligation_graph", _edge_unknown_relation_sid(spec[1], spec[2]))
    if tag == "inactive_target":
        return ("obligation_graph", _edge_inactive_target_sid(spec[1], list(spec[2])))
    raise ObligationContractError(f"unknown_edge_audit_spec:{tag}")


def build_edge_audit_blueprint(
    card: Any,
    spec: Tuple,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> ObligationBlueprint:
    """一条 edge 审计 spec（§3.4.3 三态之一）→ edge 义务 blueprint。

    channel 恒 obligation_graph、kind=escalation、predicate_kind="obligation_edge"、
    source_predicate_spec=`_obligation_edge_predicate_spec()`、scope=`_scope_from_meta(meta)`；
    身份材料（SID + obligation_node_id + obligation_edge_ids）随三态区分（§3.4.3 表）。
    """
    tag = spec[0]
    if tag == "dangling":
        edge_id = nfc(str(spec[1]))
        sid = _edge_dangling_sid(edge_id)
        node_id = ""
        edge_ids = (edge_id,)
    elif tag == "unknown":
        edge_id = nfc(str(spec[1]))
        member = str(spec[2])
        sid = _edge_unknown_relation_sid(edge_id, member)
        node_id = nfc(str(spec[3]))  # 该 member 的 node_id
        edge_ids = (edge_id,)
    elif tag == "inactive_target":
        target_id = nfc(str(spec[1]))
        sorted_edges = tuple(sorted(nfc(str(e)) for e in spec[2]))
        sid = _edge_inactive_target_sid(target_id, list(sorted_edges))
        node_id = target_id
        edge_ids = sorted_edges
    else:
        raise ObligationContractError(f"unknown_edge_audit_spec:{tag}")
    _register_source_item(registry, "obligation_graph", sid)
    identity = CanonicalObligationIdentity(
        identity_schema=IDENTITY_SCHEMA,
        canonical_profile_id=CANONICAL_PROFILE_ID,
        source_rule_card_id=str(card.rule_card_id),
        kind="escalation",
        scope=_scope_from_meta(meta),
        obligation_node_id=node_id,
        obligation_edge_ids=edge_ids,
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="obligation_graph",
        source_item_id=sid,
        predicate_kind="obligation_edge",
        source_predicate_spec=_obligation_edge_predicate_spec(),
        qualifiers=(),
    )
    immutable = ImmutablePayload(required=True, canonical_unit="", source_operator="")
    provenance = _provenance(meta, card)
    return _freeze(identity, immutable, provenance)


def derive_edge_audit_blueprints(
    card: Any,
    meta: Dict[str, Any],
    *,
    registry: Optional[CardBindingRegistry] = None,
) -> List[ObligationBlueprint]:
    """一张卡的 edge 审计三态 blueprint 全集（§3.4.3/§5.3.3；`_card_edge_audit_specs` 静态分类）。"""
    return [
        build_edge_audit_blueprint(card, spec, meta, registry=registry)
        for spec in _card_edge_audit_specs(card)
    ]


# ===========================================================================
# A.3 threshold_regime signature 一致性闸（卡级 + 运行级）
# ===========================================================================


def _threshold_signature(spec: PredicateSpecV1) -> str:
    """同 regime_id 一致性比对用的规则侧签名（spec 除 variable_bindings 外的 canonical bytes）。"""
    obj = spec.model_dump()
    obj.pop("variable_bindings", None)  # A.3：除 variable_bindings 运行无关部分外须一致
    return canonical_json(obj)


def check_threshold_regime_signatures(
    threshold_blueprints: List[ObligationBlueprint],
) -> None:
    """A.3：**同卡内**同 `threshold_regime_id` 规则侧签名不一致 → hard-fail
    `threshold_regime_signature_conflict`（`derive_card_blueprints` 卡级调用）。

    跨卡一致性由 `RegimeSignatureRegistry`（`derive_run_blueprints` 运行级）另行覆盖。
    """
    reg = RegimeSignatureRegistry()
    for bp in threshold_blueprints:
        reg.record(bp.identity.source_predicate_spec)


# ===========================================================================
# 卡级派生入口（镜像 v1 drive-loop 迭代；只产 blueprint，不求值、不判定）
# ===========================================================================

# 本单元覆盖的 kind（源 channel）；v4 缺口增补后 workflow_deadline 亦覆盖，无剩余真模型缺口。
COVERED_CHANNELS = (
    "threshold",
    "trigger",
    "slot_role",
    "workflow_artifact",
    "workflow_deadline",
    "evidence",
    "definition",
    "exception",
    "obligation_graph",
    "applicability",
)


# 真模型缺口 channel —— **v4 缺口增补后清空**（deadline channel 已接 + 普通/升级 node 判别式已放宽
# + node deadline_ids 内嵌 identity + method 子义务 method-derived 承载）；无剩余不可表示 channel。
# fail-closed 哨兵改由 `_assert_known_node_kind`（未知 raw node_kind → hard-fail）承担（§3.1.1）。
MODEL_GAP_CHANNELS: Tuple[str, ...] = ()


def derive_card_blueprints(
    card: Any, fact_pack_meta: Dict[str, Any]
) -> List[ObligationBlueprint]:
    """**STRICT 总入口 ≡ 覆盖入口**（v4 入口合一，§9）：真模型缺口消除后 `MODEL_GAP_CHANNELS` 清空、
    本入口对真卡恒过（全 397 卡 401 node + 25 deadline 全落 covered）；委托 `derive_covered_card_blueprints`。

    fail-closed 不弱化：未知 raw node_kind 由 `derive_covered_card_blueprints` 内的 `_assert_known_node_kind`
    在 `from_dict` 归一**之前** hard-fail（`unknown_node_kind`，§3.1.1）；空 applicability / 重复源项 /
    悬空 artifact / float ingress 等闸照旧继承（覆盖派生内生效）。
    """
    return derive_covered_card_blueprints(card, fact_pack_meta)


def derive_covered_card_blueprints(
    card: Any, fact_pack_meta: Dict[str, Any]
) -> List[ObligationBlueprint]:
    """一张卡的**全 channel** v2 blueprint（从源头冻结身份；§2 卡级聚合闸收尾）。

    覆盖 channel（v4 缺口消除后**无剩余真模型缺口**，STRICT 总入口 `derive_card_blueprints` ≡ 本入口，
    `MODEL_GAP_CHANNELS = ()`）：applicability（§5）/ trigger / slot_role / threshold /
    workflow_artifact / **workflow_deadline**（§2）/ evidence / definition / exception（corpus-empty）/
    obligation_graph（**全 3 种 node_kind**：普通 obligation + 升级 escalation + prohibition，§3.1；
    node.deadline_ids 内嵌 identity §2.5；**method 产出 node 的 method-derived**（仅结构可分节点，§3.4③）+
    edge）。fail-closed 由 `_assert_known_node_kind`（未知 raw node_kind → hard-fail）承担，非靠 channel 排除。

    blocker 3：卡级对每个**聚合源容器**整体 `model_validate`（trigger_conditions /
    workflow_operands / evidence_requirements 顶层 + 嵌套越界键 → ValidationError，覆盖未消费
    部分）。A.3 卡级 regime signature 闸；§2 `CardBindingRegistry` 跨源项多目标 + 重复源项闸。
    """
    # ---- blocker 2/3：每个**聚合源容器无条件整体 model_validate**（非只遍历会消费的 leaf、
    # 不 gated on truthiness/required）----
    # 旧代码 `and card.X`（真值判断）令空 dict `{}` 静默跳过校验（必填缺失/嵌套越界键漏）；
    # slot_role_map 旧只在 `required=true` 校验（required=false/缺 required 的越界项静默跳）。
    # 修法：三顶层容器**无条件** model_validate（空 dict 缺必填 → ValidationError）；slot_role_map
    # **逐条无条件** model_validate（含非必需槽位——带越界键 → extra=forbid 拒）。真卡 397/397 三
    # 容器全字段齐备、769 槽位全 required 各 5 字段 → 无条件校验不误拒（见交付报告全卡实测）。
    if isinstance(card.trigger_conditions, dict):
        TriggerConditionsDTO.model_validate(card.trigger_conditions)
    if isinstance(card.workflow_operands, dict):
        WorkflowOperandsDTO.model_validate(card.workflow_operands)
    if isinstance(card.evidence_requirements, dict):
        EvidenceRequirementsDTO.model_validate(card.evidence_requirements)
    for slot_ref in card.slot_role_map or []:
        if isinstance(slot_ref, dict):
            SlotRoleDTO.model_validate(slot_ref)

    registry = CardBindingRegistry()
    out: List[ObligationBlueprint] = []

    # ---- applicability（§5：scope-audit 义务，每卡一条）----
    # applicability 是九必存源容器之一（七字段全 required、进身份），**无条件**校验+派生：
    # 空 {}/缺失/非 dict → build_applicability_blueprint 内 ApplicabilityDTO.model_validate
    # 抛 ValidationError（fail-closed，不保留真值门；codex 终审阻断修复）。
    applicability = card.applicability
    out.append(
        build_applicability_blueprint(
            card,
            dict(applicability) if isinstance(applicability, dict) else {},
            fact_pack_meta,
            registry=registry,
        )
    )

    # ---- triggers ----
    trigger_items = (card.trigger_conditions or {}).get("items", []) or []
    for trigger in sorted(trigger_items, key=lambda x: str(_safe(x, "condition_id"))):
        if isinstance(trigger, dict):
            out.append(
                build_trigger_blueprint(
                    card, dict(trigger), fact_pack_meta, registry=registry
                )
            )

    # ---- slot roles（required）----
    for slot_ref in sorted(
        card.slot_role_map or [], key=lambda x: str(_safe(x, "slot_ref_id"))
    ):
        if isinstance(slot_ref, dict) and slot_ref.get("required"):
            out.append(
                build_slot_role_blueprint(
                    card, dict(slot_ref), fact_pack_meta, registry=registry
                )
            )

    # ---- thresholds（A.3 卡级 signature 一致性闸）----
    threshold_bps: List[ObligationBlueprint] = []
    for threshold in sorted(
        card.threshold_regimes or [], key=lambda x: str(_safe(x, "threshold_regime_id"))
    ):
        if isinstance(threshold, dict):
            threshold_bps.append(
                build_threshold_blueprint(
                    card, dict(threshold), fact_pack_meta, registry=registry
                )
            )
    check_threshold_regime_signatures(threshold_bps)
    out.extend(threshold_bps)

    # ---- workflow artifacts ----
    # blocker 1（入口级 fail-closed）：**不 pre-filter 空值**——空 artifact_id+artifact_key /
    # 空串 artifact_id 的 artifact item 照样送 builder → `_make_binding("artifact", …)` 逮空
    # 值 hard-fail `artifact_unresolved_hard_fail`（C.9：artifact 维不可 unresolved）。旧
    # `and (item.get("artifact_id") or item.get("artifact_key"))` 前置过滤会**静默跳过**空
    # artifact，令入口级反例不炸（只有直调 builder 才炸）——本入口级修法确保覆盖/严格入口都炸。
    for item in sorted(
        (card.workflow_operands or {}).get("artifacts", []) or [],
        key=lambda x: _stable_json_key(x),
    ):
        if isinstance(item, dict):
            out.append(
                build_workflow_artifact_blueprint(
                    card, dict(item), fact_pack_meta, registry=registry
                )
            )

    # ---- workflow deadlines（§2：每 deadline 一条 workflow_deadline blueprint）----
    for deadline in sorted(
        (card.workflow_operands or {}).get("deadlines", []) or [],
        key=lambda x: _stable_json_key(x),
    ):
        if isinstance(deadline, dict):
            out.append(
                build_workflow_deadline_blueprint(
                    card, dict(deadline), fact_pack_meta, registry=registry
                )
            )

    # ---- evidence requirements（三 bucket）----
    # blocker 1（入口级 fail-closed）：对**所有** evidence req（不分 required）**先做 artifact 引用
    # 完整性校验**（`_assert_evidence_artifact_integrity`：空/悬空 artifact → hard-fail），**再做
    # required 派生筛选**。旧代码只对 `required=True` 项建 blueprint（唯一到达 artifact gate 的路径），
    # `required=False` 的 `artifact_ids=[""]` 整项被 required 过滤跳过、绕过 artifact hard-fail
    # （覆盖入口 + 严格入口都不炸）。
    evidence_reqs = card.evidence_requirements or {}
    for bucket_name in sorted(evidence_reqs.keys()):
        reqs = evidence_reqs.get(bucket_name) or []
        if not isinstance(reqs, list):
            continue
        for req in sorted(reqs, key=lambda x: str(_safe(x, "evidence_requirement_id"))):
            if not isinstance(req, dict):
                continue
            _assert_evidence_artifact_integrity(card, req)  # blocker 1：不分 required 先炸空/悬空 artifact
            if req.get("required", True):
                out.append(
                    build_evidence_blueprint(
                        card, bucket_name, dict(req), fact_pack_meta, registry=registry
                    )
                )

    # ---- definitions ----
    for definition in sorted(
        card.definitions or [], key=lambda x: str(_safe(x, "definition_id"))
    ):
        if isinstance(definition, dict):
            out.append(
                build_definition_blueprint(
                    card, dict(definition), fact_pack_meta, registry=registry
                )
            )

    # ---- exceptions（真卡语料 0 条）----
    for exc in sorted(
        card.exceptions or [], key=lambda x: str(_safe(x, "exception_kind"))
    ):
        if isinstance(exc, dict):
            out.append(
                build_exception_blueprint(
                    card, dict(exc), fact_pack_meta, registry=registry
                )
            )

    # ---- obligation_graph（v4：全 node + method-derived + edge）----
    # 全 3 种 node_kind 放宽（普通/升级 node → predicate_kind=raw node_kind、spec=None，§3.1）；
    # raw-kind 闸 `_assert_known_node_kind` 在 `from_dict` 归一**之前**拒未知 raw node_kind（§3.1.1）；
    # method 产出 node **仅当结构上可分**（`_node_method_separable`：node 带 artifact_ids/deadline_ids
    # 等 v1 dedupe 区分键，真卡 5 卡）才额外建 method-derived blueprint（parts={"derived":"method"}，§3.4③）；
    # 不可分（真卡 2 卡，v1 必折叠）不建、method 子义务阶段二配回 node-main（否则 v2 净 2 ≠ v1 净 1）。
    graph = card.obligation_graph or {}
    for node in sorted(
        graph.get("nodes", []) or [],
        key=lambda x: str(_safe(x, "obligation_node_id")),
    ):
        if not isinstance(node, dict):
            continue
        _assert_known_node_kind(node)  # §3.1.1：raw node_kind fail-closed（from_dict 归一前）
        out.append(
            build_obligation_node_blueprint(
                card, dict(node), fact_pack_meta, registry=registry
            )
        )
        node_dto = ObligationNodeDTO.from_dict(dict(node))
        if _node_method_separable(card, node_dto):  # §3.4③：仅可分才建独立 method-derived
            out.append(
                build_method_derived_blueprint(
                    card, dict(node), fact_pack_meta, registry=registry
                )
            )
    # edge 审计三态（§3.4.3/§5.3.3）：dangling / unknown-relation 分身 / inactive-target 聚合
    # （`_card_edge_audit_specs` 静态分类，与 declare 五元组侧同源）。
    out.extend(
        derive_edge_audit_blueprints(card, fact_pack_meta, registry=registry)
    )

    registry.finalize()  # §2：卡级跨源项多目标闸（收尾）
    return out


def derive_run_blueprints(
    cards: List[Any], fact_pack_meta: Dict[str, Any]
) -> List[ObligationBlueprint]:
    """一批卡的**全 channel** v2 blueprint（运行级；§2 `RegimeSignatureRegistry` 跨卡 regime
    签名闸）。逐卡走 `derive_covered_card_blueprints`（v4 缺口消除后 STRICT ≡ 覆盖，普通/升级 node 与
    deadline 均已可表示、不再 fail-closed），再跨卡喂 `RegimeSignatureRegistry`：两卡同
    `threshold_regime_id` 异签名 → `threshold_regime_signature_conflict`（A.3 运行级）。
    """
    regime_registry = RegimeSignatureRegistry()
    out: List[ObligationBlueprint] = []
    for card in cards:
        bps = derive_covered_card_blueprints(card, fact_pack_meta)
        for bp in bps:
            regime_registry.record(bp.identity.source_predicate_spec)
        out.extend(bps)
    return out


def derive_covered_blueprints_from_bundle(
    bundle_path: Any, fact_pack_meta: Dict[str, Any]
) -> List[ObligationBlueprint]:
    """**blocker 6：Decimal 读径生产入口** —— 从 `rule_cards.json` 路径经 `load_identity_cards`
    （`parse_json_decimal` / `parse_float=Decimal`）读**原始词元**（数字落 int/Decimal，**绝不
    Python float**），再运行级覆盖派生。

    不接受**已被 v1 float 解析**的数值：v1 生产读径（`json.loads`）会把 `0.5` 解成二进制
    float → identity 入口 `_literal_value` / strict DTO 拒 float 会 hard-fail（13 卡 float 阈值
    在 v1 读径下断线）；本入口用 Decimal 读径取原始词元，13 卡 float 阈值派生正常。
    """
    from .rulecard_decimal_load import load_identity_cards

    cards = load_identity_cards(bundle_path)
    return derive_run_blueprints(cards, fact_pack_meta)


def _safe(item: Any, key: str) -> Any:
    return item.get(key) if isinstance(item, dict) else None


def _stable_json_key(obj: Any) -> str:
    try:
        return canonical_json(obj)
    except Exception:  # noqa: BLE001 — 排序键兜底（非契约路径）
        return str(obj)


# ===========================================================================
# v2 双键（A.5）便捷包装 —— 基于 blueprint 身份
# ===========================================================================


def blueprint_dedupe_key(bp: ObligationBlueprint) -> str:
    """dedupe_key_v2 ≡ 身份（不含 run；A.7/A.11 单一权威）。"""
    return bp.canonical_identity_hash


def blueprint_obligation_id(bp: ObligationBlueprint) -> str:
    """obligation_id_v2（A.5，含 run_envelope world/building，N1）。"""
    run_env = RunInstanceEnvelope(
        run_id=bp.provenance.run_id,
        world_id=bp.provenance.world_id,
        building_id=bp.provenance.building_id,
    )
    return compute_obligation_id_v2(bp.identity, run_env)


__all__ = [
    "BLUEPRINT_SCHEMA",
    "COVERED_CHANNELS",
    "CardBindingRegistry",
    "RegimeSignatureRegistry",
    "FormulaRegistryEntry",
    "build_threshold_blueprint",
    "build_trigger_blueprint",
    "build_slot_role_blueprint",
    "build_workflow_artifact_blueprint",
    "build_evidence_blueprint",
    "build_definition_blueprint",
    "build_exception_blueprint",
    "build_applicability_blueprint",
    "build_workflow_deadline_blueprint",
    "build_obligation_node_blueprint",
    "build_method_derived_blueprint",
    "build_edge_audit_blueprint",
    "derive_edge_audit_blueprints",
    "edge_audit_spec_source_item",
    "_card_edge_audit_specs",
    "check_threshold_regime_signatures",
    "MODEL_GAP_CHANNELS",
    "derive_card_blueprints",
    "derive_covered_card_blueprints",
    "derive_run_blueprints",
    "derive_covered_blueprints_from_bundle",
    "blueprint_dedupe_key",
    "blueprint_obligation_id",
]
