"""组件类型格 + 精确目标授权:共享本体消费侧判定逻辑(DEBT-065 第一波)。

依据 spec 草案 v2.2 §2.2/§2.3/§2.5/§3.1/§3.2。本模块是**纯判定逻辑**,不碰 validator
判定路径、不改 rule_slice_hash——validator 判据接线时消费本模块(那才是原子红线步)。

架构定位:类型格是共享本体(排斥关系),非 W0(W0 rule-blind)。互斥仅在 W0 生成模型内
成立,不外推现实本体。合规判定权仍唯一属 validate_building_closure,本模块只提供判据。

三阶段异常(v2.2 §1.1):
- ingest hard-fail(LatticeIngestError):schema/重复卡/非法 evidence/双快照失配/disjoint
  不全/两类 bundle 失配/违反单目标或非叶目标 —— 资产损坏,批不启动。
- 条目级失效(stale):rule_card_id 不存在 / 指纹或修订失配 —— authorized_target 返回 None。
- runtime 保守关闭:资产整体缺席 —— 调用方取不到资产时全部不早退(本模块不涉及,属加载方)。
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

_EVIDENCE_KINDS = frozenset({"slot_role_map", "threshold_regimes", "trigger_conditions"})


class LatticeIngestError(ValueError):
    """资产结构损坏 → ingest 阶段整包拒绝(v2.2 §1.1 hard-fail)。"""


def canonical_hash(obj) -> str:
    """v2.2 §2.2 规范哈希:排序键 + 紧凑分隔 + UTF-8,不 ASCII 转义。"""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_disjoint_pair_shapes(raw_disjoint) -> List[FrozenSet[str]]:
    """disjoint 对形状校验(§2.3②):每对恰二元——拒自反(坍缩成单元素)与多单元素。

    抽成独立函数供两处复用:本模块 `load_component_lattice`(共享本体 ingest)
    与 `applicability_v3.load_bundle`(独立适用性包加载边界)——同一校验不复制
    第二份(2026-07-27 护栏缺口 2:后者此前缺这道,自反对会让 early_exit 在
    target == identity 时假阳性早退)。
    """
    pairs: List[FrozenSet[str]] = []
    for p in raw_disjoint:
        fs = frozenset(p)
        if len(fs) != 2:
            raise LatticeIngestError(f"disjoint 含自反或非二元对: {p}")
        pairs.append(fs)
    return pairs


def _assert_subsumption_acyclic(subsumption: Dict[str, FrozenSet[str]]) -> None:
    """subsumption 有向环检测(任意长度;二元环只是它的特例)。

    2026-07-27 护栏缺口 1:原实现只拒二元环(A⇄B),A→B→C→A 会被接受,
    祖先遍历(obligation_deriver)会把环上类型当有效祖先 ⇒ 错误绑定事实。
    沿 parent→member 边做三色 DFS,发现回边即 hard-fail(同 LatticeIngestError 路径)。
    """
    _WHITE, _GRAY, _BLACK = 0, 1, 2
    color: Dict[str, int] = {p: _WHITE for p in subsumption}

    def _visit(node: str, stack: List[str]) -> None:
        color[node] = _GRAY
        stack.append(node)
        for nxt in subsumption.get(node, ()):
            if nxt not in subsumption:
                continue  # 叶成员无出边
            c = color[nxt]
            if c == _GRAY:
                cycle = stack[stack.index(nxt):] + [nxt]
                raise LatticeIngestError(f"subsumption 成环: {' → '.join(cycle)}")
            if c == _WHITE:
                _visit(nxt, stack)
        stack.pop()
        color[node] = _BLACK

    for parent in subsumption:
        if color[parent] == _WHITE:
            _visit(parent, [])


def card_fingerprint_v1(card_obj: dict) -> str:
    """card_fingerprint.v1 = 哈希原始 rule_cards.json 单卡对象(非 KG 重建 DTO)。"""
    return canonical_hash(card_obj)


@dataclass(frozen=True)
class ComponentLattice:
    leaf_types: FrozenSet[str]
    non_leaf_types: FrozenSet[str]
    subsumption: Dict[str, FrozenSet[str]]
    disjoint_pairs: FrozenSet[FrozenSet[str]]
    vocabulary_snapshot_sha256: str
    alias_mapping_version: Optional[str]
    alias_mapping_snapshot_sha256: str
    rulecard_bundle_id: Optional[str]

    def provable_disjoint(self, target_type: str, fragment_identity: str) -> bool:
        """(目标, fragment 身份) 是否可证互斥。仅叶×叶、且显式登记于 disjoint_pairs 才为真。

        禁传递闭包、禁"未登记=互斥":未在 disjoint_pairs 中 → False(不早退)。
        """
        if target_type not in self.leaf_types or fragment_identity not in self.leaf_types:
            return False
        if target_type == fragment_identity:
            return False
        return frozenset((target_type, fragment_identity)) in self.disjoint_pairs


@dataclass(frozen=True)
class _AuthEntry:
    rule_card_id: str
    target: str
    authoring_revision: object
    interpretation_revision: object
    card_content_sha256: str


@dataclass(frozen=True)
class Authorization:
    by_id: Dict[str, _AuthEntry]

    def authorized_target(self, card_obj: dict) -> Optional[str]:
        """返回该卡的精确目标叶型;无有效条目(未授权/stale)→ None(缺省拒绝,不早退)。

        stale 条件(v2.2 §1.1 条目级):卡不存在于表 / 四字段任一失配。
        """
        entry = self.by_id.get(card_obj.get("rule_card_id"))
        if entry is None:
            return None
        version = card_obj.get("version") or {}
        if (
            entry.authoring_revision != version.get("authoring_revision")
            or entry.interpretation_revision != version.get("interpretation_revision")
            or entry.card_content_sha256 != card_fingerprint_v1(card_obj)
        ):
            return None  # stale_card_binding
        return entry.target


def load_component_lattice(
    data: dict, vocab_domain: List[str], alias_map: dict, expected_bundle_id: str,
) -> ComponentLattice:
    """从资产 dict 构造 ComponentLattice,执行 v2.2 §2.3 完整性校验(违反 → hard-fail)。

    P1-3:expected_bundle_id 必填非空,校验 rulecard_bundle_id 非空且精确相等——他卡包形成
    的叶型/排斥关系不得用于当前卡包;缺失/空/失配 → hard-fail(不得经 None 绕过)。
    """
    if not expected_bundle_id:
        raise LatticeIngestError("load_component_lattice 需非空 expected_bundle_id(P1-3 配套校验)")
    if not data.get("rulecard_bundle_id"):
        raise LatticeIngestError("lattice 缺 rulecard_bundle_id(P1-3 配套校验)")
    if data.get("rulecard_bundle_id") != expected_bundle_id:
        raise LatticeIngestError(
            f"lattice bundle {data.get('rulecard_bundle_id')} 与卡包 {expected_bundle_id} 失配"
        )
    try:
        leaf = frozenset(data["leaf_types"])
        non_leaf = frozenset(data["non_leaf_types"])
        raw_disjoint = data["disjoint_pairs"]
        subsumption = {k: frozenset(v) for k, v in (data.get("subsumption") or {}).items()}
    except (KeyError, TypeError) as exc:
        raise LatticeIngestError(f"lattice schema 损坏: {exc}") from exc

    # 断言 A:词表二分(§2.3⑥)
    domain = set(vocab_domain)
    if leaf | non_leaf != domain:
        raise LatticeIngestError(
            f"断言A失败: leaf∪non_leaf 未穷尽词表值域, 差集={(leaf | non_leaf) ^ domain}"
        )
    if leaf & non_leaf:
        raise LatticeIngestError(f"断言A失败: leaf/non_leaf 相交 {leaf & non_leaf}")

    # disjoint:C(leaf,2) 全覆盖 + 对称(frozenset 天然)+ 无自反(§2.3②)
    # 形状校验(恰二元/无自反)与 applicability_v3 加载边界共用同一函数,不复制第二份。
    pairs = set(validate_disjoint_pair_shapes(raw_disjoint))
    # 🔴 2026-07-26（DEBT-076）：原断言 `pairs != expected` ⇒ 要求 disjoint_pairs
    # **恰好等于**叶的 C(n,2)。那锁死了「互斥只能在叶之间」这个旧假设，而裁定明确要求
    # **支持跨层互斥**——实测 20,368 次配对冲突里大量是跨层（卡要 `structural_component`、
    # 世界给 `drainage_component`），叶×叶全组合永远表达不了。
    # 改为「叶全组合是**子集**（下界，词表结构决定，必须全覆盖）」；
    # 跨层对是**人裁关系表**追加的，属正当扩充。
    # ⚠️ 仍然拒绝**缺**叶对——那说明类型格生成有问题，不是扩充。
    expected = {frozenset(c) for c in itertools.combinations(leaf, 2)}
    missing = expected - pairs
    if missing:
        raise LatticeIngestError(
            f"disjoint_pairs 缺 {len(missing)} 组叶×叶互斥对（叶集 C(n,2) 必须全覆盖）")
    for fs in pairs - expected:
        a, b = tuple(fs)
        if a not in (leaf | non_leaf) or b not in (leaf | non_leaf):
            raise LatticeIngestError(f"跨层互斥对含词表外类型: {sorted(fs)}")

    # subsumption:父∈non_leaf,成员∈词表值域（**可为非叶——允许多级**）
    for parent, members in subsumption.items():
        if parent not in non_leaf:
            raise LatticeIngestError(f"subsumption 父类 {parent} 非 non_leaf")
        # 🔴 2026-07-26（DEBT-076）：原断言 `members <= leaf` 锁死了单级假设。
        # 实例：`transfer_structure`（非叶）is_a `structural_component`，依据
        # §3.4.1(b)(vii) 結構構件檢驗項目明列「轉移構築物」。裁定明确允许多级
        # （规格措辞是「**后代 → 祖先**」而非「叶 → 父」）。
        # 这是同一旧假设在本仓的**第三处**（另两处：生成器 disjoint 自动全组合、
        # 类型格测试的 == 断言）——**同一个假设散在三处，改一处不够。**
        outside = members - (leaf | non_leaf)
        if outside:
            raise LatticeIngestError(f"subsumption 成员 {outside} 不在词表值域")
        if parent in members:
            raise LatticeIngestError(f"subsumption 自反: {parent}")

    # 全图有向环检测(任意长度)——替代原二元环逐对检查(只拒 A⇄B、放过 A→B→C→A)。
    _assert_subsumption_acyclic(subsumption)

    # 双快照哈希与当前源资产一致(§2.3①,漂移 → hard-fail)
    vocab_hash = canonical_hash(sorted(domain))
    if data.get("vocabulary_snapshot_sha256") != vocab_hash:
        raise LatticeIngestError("vocabulary_snapshot_sha256 与当前词表失配")
    alias_hash = canonical_hash(alias_map)
    if data.get("alias_mapping_snapshot_sha256") != alias_hash:
        raise LatticeIngestError("alias_mapping_snapshot_sha256 与当前别名映射失配")

    return ComponentLattice(
        leaf_types=leaf,
        non_leaf_types=non_leaf,
        subsumption=subsumption,
        disjoint_pairs=frozenset(pairs),
        vocabulary_snapshot_sha256=vocab_hash,
        alias_mapping_version=data.get("alias_mapping_version"),
        alias_mapping_snapshot_sha256=alias_hash,
        rulecard_bundle_id=data.get("rulecard_bundle_id"),
    )


def _card_component_values(card: dict) -> set:
    """收集卡内所有位置(slot_role_map/threshold_regimes/trigger_conditions)的 component_type_key。"""
    values = set()
    for slot in card.get("slot_role_map", []) or []:
        q = (slot.get("qualifiers") or {}).get("component_type_key")
        if q:
            values.add(q)
    for reg in card.get("threshold_regimes", []) or []:
        q = (reg.get("qualifiers") or {}).get("component_type_key")
        if q:
            values.add(q)
    tc = card.get("trigger_conditions", {}) or {}
    for item in (tc.get("items", []) if isinstance(tc, dict) else []):
        q = (item.get("qualifiers") or {}).get("component_type_key")
        if q:
            values.add(q)
    return values


def _card_evidence_locators(card: dict):
    """卡内可被 evidence 引用的定位符集合:slot_ref_id / threshold_regime_id / condition_id。"""
    slot_refs = {s.get("slot_ref_id") for s in (card.get("slot_role_map", []) or [])}
    slot_refs |= {r.get("threshold_regime_id") for r in (card.get("threshold_regimes", []) or [])}
    tc = card.get("trigger_conditions", {}) or {}
    cond_ids = {i.get("condition_id") for i in (tc.get("items", []) if isinstance(tc, dict) else [])}
    return slot_refs, cond_ids


def load_authorizations(
    data: dict, expected_bundle_id: str, leaf_types: FrozenSet[str],
    cards_by_id: Optional[Dict[str, dict]] = None,
) -> Authorization:
    """从授权表 dict 构造 Authorization,执行 v2.2 §2.5 结构校验(违反 → hard-fail)。

    结构级 hard-fail:bundle 失配 / 重复 rule_card_id / 非单叶目标 / 非法 evidence。
    P1-4:cards_by_id 提供时逐项校验 evidence 引用在卡内真实存在 + 每卡单组件值。
    指纹与修订的 stale 判定延到 authorized_target 调用时(需卡对象)。
    """
    if data.get("rulecard_bundle_id") != expected_bundle_id:
        raise LatticeIngestError(
            f"授权表顶层 bundle {data.get('rulecard_bundle_id')} 与卡包 {expected_bundle_id} 失配"
        )
    by_id: Dict[str, _AuthEntry] = {}
    for e in data.get("entries") or []:
        rid = e.get("rule_card_id")
        if not rid:
            raise LatticeIngestError("授权条目缺 rule_card_id")
        if rid in by_id:
            raise LatticeIngestError(f"授权条目 rule_card_id 重复: {rid}")
        targets = e.get("exact_fragment_target_types") or []
        if len(targets) != 1 or targets[0] not in leaf_types:
            raise LatticeIngestError(f"{rid} 非单叶目标: {targets}")
        evidence = e.get("evidence") or []
        if not evidence:
            raise LatticeIngestError(f"{rid} evidence 为空")
        for ev in evidence:
            if ev.get("kind") not in _EVIDENCE_KINDS:
                raise LatticeIngestError(f"{rid} evidence kind 非法: {ev.get('kind')}")
            if not (ev.get("slot_ref_id") or ev.get("condition_id")):
                raise LatticeIngestError(f"{rid} evidence 无定位")
        # P1-4:卡在场时校验 evidence 引用存在性 + 每卡单组件值。
        if cards_by_id is not None and rid in cards_by_id:
            card = cards_by_id[rid]
            slot_refs, cond_ids = _card_evidence_locators(card)
            for ev in evidence:
                ref, cid = ev.get("slot_ref_id"), ev.get("condition_id")
                if ref and ref not in slot_refs:
                    raise LatticeIngestError(f"{rid} evidence slot_ref_id {ref} 卡内不存在")
                if cid and cid not in cond_ids:
                    raise LatticeIngestError(f"{rid} evidence condition_id {cid} 卡内不存在")
            cvals = _card_component_values(card)
            if len(cvals) > 1:
                raise LatticeIngestError(f"{rid} 卡内多组件值 {cvals}(违反每卡单组件值不变量)")
        binding = e.get("card_version_binding") or {}
        by_id[rid] = _AuthEntry(
            rule_card_id=rid,
            target=targets[0],
            authoring_revision=binding.get("authoring_revision"),
            interpretation_revision=binding.get("interpretation_revision"),
            card_content_sha256=binding.get("card_content_sha256"),
        )
    return Authorization(by_id=by_id)
