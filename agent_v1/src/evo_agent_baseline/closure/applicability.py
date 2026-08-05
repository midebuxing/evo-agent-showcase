"""适用性评估 —— spec §6.3.2。

`evaluate_applicability(card, fact_pack)` 确定性判定一张 rule_card 是否适用于
当前建筑事实，输出 `ApplicabilityResult`（applicable / not_applicable /
uncertain）。

规则（spec §6.3.2）：
- regime != "mbis" → not_applicable
- building_scope 与 building facts 明确冲突 → not_applicable
- component_scope 非空且无任何 component/fragment 匹配 → not_applicable
- 所需 scope fact 缺失 → uncertain
- 否则 applicable

确定性、无 LLM：只读 RuleCardDTO.applicability 与 FactPack.facts。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import FactAtom, FactPack, RuleCardDTO

from .fact_binding import parse_value
from .schema import ApplicabilityResult


# 世界侧唯一按楼给出的**完整**组件类名册槽（worldgen `_emit_scope_declaration_rows`
# 产出；值＝该类是否在 `building_world.components` 全量列表里）。
_SCOPE_DECLARATION_SLOT = "scope.component.inspection_included"


def collect_building_component_classes(
    fact_pack: FactPack,
    component_type_aliases: Dict[str, Any],
) -> set[str]:
    """从楼内事实的受控身份来源收集规范组件类。

    三条来源共用同一张 ``component_type_key`` 别名表：

    1. ``slot_id == "component_type"`` 的显式组件类型值（保留既有语义）；
    2. 本身已被该表承认为组件类型词汇的 ``carrier_type``；
    3. **楼级范围声明行** ``scope.component.inspection_included`` 中**取值为真**
       的那些行的 ``qualifiers.component_type_key``（2026-07-28 加）。

    第二、三条只接纳别名表的键或值，避免把 ``building``、``measurement`` 等普通
    载体枚举误当组件类；因此这是受控映射，不含任何类型特例。

    🔴 **为什么必须有第三条（2026-07-28 世界池实证）**：
    前两条读的是**事实包里的事实**，而**事实包是对世界的采样、不是全量**。
    实测 ``BLD-…-RC-0007`` 在世界池 ``components.parquet`` 里有 **8 个组件、
    含 ``fire_door`` ×1**，而它的事实包只采到 **4 条** ``component_type`` 事实
    （drainage_stack / external_wall ×2 / structural_member）——``fire_door``
    **根本没被采样进去**。⇒ 前两条**系统性低报**楼级组件类。

    后果（修此条之前）：subject 词桥「楼内组件类与该 subject 的组件类集无交集
    ⇒ 整卡 not_applicable」大面积误杀——**19/30 栋**被判「无
    ``fire_safety_component`` 类」，47 张 §3.5 卡整卡不适用，
    在验收标准③ 阅卷里表现为 ``wrong_structural_na`` **静默漏判**。

    **为什么第三条只认这一个槽、且只认真值**：
    该槽按设计就是「RI 报告『检验范围』章节**逐组件类**声明涵盖与否」
    （见 ``workflow_engine/worldgen/sidecar.py`` 的 ``_emit_scope_declaration_rows``），
    其值是 ``ctype in present``，``present`` 取自 ``building_world.components``
    **全量**——**这是世界侧唯一按楼给出的完整组件类名册**。
    ⚠️ **不要**推广成「任意槽的 ``component_type_key`` 出现即产类」：
    ``ubw`` 在全批 30 栋的该槽上皆为 ``false``（僭建物不是「规定检验的构件类」，
    是 §3.7 的发现对象），放开真假之分会**误造 ubw 类**。
    ⚠️ 也**不要**只因限定符出现就产类——见上一条。
    """
    aliases = {
        str(raw): canonical
        for raw, canonical in (component_type_aliases or {}).items()
        if isinstance(canonical, str) and canonical
    }
    component_vocabulary = set(aliases) | set(aliases.values())
    out: set[str] = set()

    def _add(raw: Any, *, require_known: bool) -> None:
        if not isinstance(raw, str) or not raw:
            return
        if require_known and raw not in component_vocabulary:
            return
        out.add(aliases.get(raw, raw))

    for fact in fact_pack.facts:
        if fact.slot_id == "component_type":
            _add(parse_value(fact.value_json), require_known=False)
        _add(fact.carrier_type, require_known=True)
        if fact.slot_id == _SCOPE_DECLARATION_SLOT:
            # 只认真值：false 行的语义是「该类不在楼内」，不是「在但未纳入范围」。
            if parse_value(fact.value_json) is True:
                _add(
                    (fact.qualifiers or {}).get("component_type_key"),
                    require_known=True,
                )
    return out


def _as_list(value: Any) -> List[Any]:
    """把标量 / None / list 统一成 list。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _building_facts(fact_pack: FactPack) -> List[FactAtom]:
    """取 building 粒度事实。"""
    return [f for f in fact_pack.facts if f.carrier_type == "building"]


def _component_facts(fact_pack: FactPack) -> List[FactAtom]:
    """取 component / fragment 粒度事实。"""
    return [
        f
        for f in fact_pack.facts
        if f.carrier_type in {"component", "fragment", "location"}
    ]


def _collect_slot_values(facts: List[FactAtom], slot_id: str) -> List[Any]:
    """从一组 fact 中按 slot_id 收集所有 observed 值。"""
    out: List[Any] = []
    for f in facts:
        # ⚠️ 未归一（卡侧 scope 键裸比世界侧 f.slot_id）：现语料三条 dict scope 路径
        # 全不触发（scope 键多为 regime/actors，上方已剔），故暂未接别名表；若未来
        # scope 出现槽名键，须先走 slot_alias_policy 正向归一（2026-07-27 注）。
        if f.slot_id == slot_id:
            out.append(parse_value(f.value_json))
    return out


def _scope_conflicts(scope: Dict[str, Any], facts: List[FactAtom]) -> Optional[str]:
    """检查 scope dict 与一组 fact 是否「明确冲突」。

    冲突定义：scope 限定某 slot 取值集合，事实里该 slot 有值，且观测值
    全部不在限定集合内 → 明确冲突，返回原因串；否则返回 None。
    「事实缺失」不算冲突（交由上层判 uncertain）。
    """
    for slot_id, allowed in scope.items():
        # ⚠️ 未归一：这里的 `slot_id` 是**卡侧 scope 字典的键**，往下经
        # `_collect_slot_values` 裸比世界侧 `f.slot_id`（未接 slot_alias_policy）。
        # 现语料不触发——卡包 scope 字典的键实测只有 regime/actors/actor 这几类
        # （下一行已全部 continue 掉），没有任何一个是槽名，故别名归一无从生效。
        # 若未来 scope 出现真槽名键，须先走 slot_alias_policy 正向归一（2026-07-27 注）。
        if slot_id in {"regime", "actors", "actor"}:
            continue
        allowed_set = _as_list(allowed)
        if not allowed_set:
            continue
        observed = _collect_slot_values(facts, slot_id)
        if not observed:
            continue
        if all(v not in allowed_set for v in observed):
            return (
                f"scope slot {slot_id!r} expects one of {allowed_set!r} "
                f"but building facts observed {observed!r}"
            )
    return None


def evaluate_applicability(
    card: RuleCardDTO,
    fact_pack: FactPack,
    *,
    subject_component_crosswalk: Optional[Dict[str, Any]] = None,
    building_component_classes: Optional[set] = None,
) -> ApplicabilityResult:
    """适用性评估主函数（spec §6.3.2）。

    card.applicability 是 rule_card v2 透传的 dict；本函数读其中的
    regime / building_scope / component_scope / building_use / component_type /
    location_class / spatial_tags 等键，按 spec §6.3.2 五条规则逐一判定。

    DEBT-047：rule_card v2 的 `component_scope` 实为自由文本列表（旧实现
    isinstance(dict) 收窄导致规则 3 对全库静默跳过）。规则 3 的机器可判实现改走
    subject 词桥（`subject_component_crosswalk`：卡 subject → component_type_key 集，
    行政/流程类 subject 刻意不在表内=不做组件过滤）对照楼内组件类集
    （`building_component_classes`，rule 词汇）。两参数缺省 None → 跳过词桥
    （向后兼容既有调用/测试）。
    """
    applicability: Dict[str, Any] = dict(card.applicability or {})
    matched_facts: List[str] = []
    reasons: List[str] = []

    building_facts = _building_facts(fact_pack)
    component_facts = _component_facts(fact_pack)

    # ---- 规则 1：regime != "mbis" → not_applicable ----
    regime = applicability.get("regime")
    if regime is not None and str(regime).lower() != "mbis":
        reasons.append(f"regime={regime!r} is not 'mbis'")
        return ApplicabilityResult(
            state="not_applicable", matched_facts=[], reasons=reasons
        )

    # ---- 规则 2：building_scope 与 building facts 明确冲突 → not_applicable ----
    building_scope = applicability.get("building_scope") or {}
    if isinstance(building_scope, dict) and building_scope:
        conflict = _scope_conflicts(building_scope, building_facts)
        if conflict is not None:
            reasons.append(f"building_scope conflict: {conflict}")
            return ApplicabilityResult(
                state="not_applicable", matched_facts=[], reasons=reasons
            )

    # ---- 规则 3-词桥（DEBT-047，spec §6.3.2 规则 3 的机器可判实现）----
    # 卡 subject 在词桥表内（组件绑定类）且其 component_type_key 集与楼内组件类集
    # 无交集 → 整卡 not_applicable（如消防卡 × 无消防组件的楼）。
    subject = applicability.get("subject")
    if (
        subject_component_crosswalk
        and building_component_classes is not None
        and isinstance(subject, str)
        and subject in subject_component_crosswalk
    ):
        wanted = {
            str(x)
            for x in (subject_component_crosswalk.get(subject) or [])
            if isinstance(x, str) and x
        }
        if wanted and not (wanted & building_component_classes):
            reasons.append(
                f"subject={subject!r} 所需组件类 {sorted(wanted)} 楼内不存在"
            )
            return ApplicabilityResult(
                state="not_applicable", matched_facts=[], reasons=reasons
            )
        if wanted & building_component_classes:
            matched_facts.append(f"subject_bridge:{subject}")

    # ---- 规则 3：component_scope 非空且无任何 component/fragment 匹配 → not_applicable ----
    component_scope = applicability.get("component_scope") or {}
    component_scope_nonempty = isinstance(component_scope, dict) and bool(
        component_scope
    )
    if component_scope_nonempty:
        matched, scope_facts_present = _match_component_scope(
            component_scope, component_facts
        )
        matched_facts.extend(matched)
        if scope_facts_present and not matched:
            reasons.append(
                "component_scope is non-empty but no component/fragment fact matched"
            )
            return ApplicabilityResult(
                state="not_applicable", matched_facts=[], reasons=reasons
            )

    # ---- 规则 4：所需 scope fact 缺失 → uncertain ----
    missing = _missing_required_scope_facts(
        applicability, building_facts, component_facts
    )
    if missing:
        reasons.append(
            "required scope fact(s) missing: " + ", ".join(sorted(missing))
        )
        return ApplicabilityResult(
            state="uncertain", matched_facts=matched_facts, reasons=reasons
        )

    # ---- 规则 5：否则 applicable ----
    reasons.append("all applicability checks passed")
    return ApplicabilityResult(
        state="applicable", matched_facts=matched_facts, reasons=reasons
    )


def _match_component_scope(
    component_scope: Dict[str, Any], component_facts: List[FactAtom]
) -> tuple[List[str], bool]:
    """检查 component_scope 是否被任一 component/fragment fact 命中。

    返回 (命中的 fact_id 列表, scope 相关 fact 是否出现过)。
    `scope_facts_present=False` 表示连判定所需的 fact 都没有 —— 此时不能
    判 not_applicable（应留给 uncertain）。
    """
    matched: List[str] = []
    scope_facts_present = False
    for slot_id, allowed in component_scope.items():
        if slot_id in {"regime", "actors", "actor"}:
            continue
        allowed_set = _as_list(allowed)
        for f in component_facts:
            # ⚠️ 未归一（同 _collect_slot_values 注）：卡侧 component_scope 键裸比
            # 世界侧 f.slot_id，现语料该 dict 路径不触发；触发前须先归一（2026-07-27 注）。
            if f.slot_id != slot_id:
                continue
            scope_facts_present = True
            observed = parse_value(f.value_json)
            if not allowed_set or observed in allowed_set:
                matched.append(f.fact_id)
    return matched, scope_facts_present


def _missing_required_scope_facts(
    applicability: Dict[str, Any],
    building_facts: List[FactAtom],
    component_facts: List[FactAtom],
) -> List[str]:
    """收集「声明为必需但事实缺失」的 scope slot。

    applicability.required_scope_slots（若有）列出判定适用性必须先有的 slot；
    任一 slot 在 building+component 事实里都找不到 → 计入缺失。
    spec §6.3.2 未给该键的精确名，故只在显式提供时启用（见交付报告决策点 D-2）。
    """
    required_slots = _as_list(applicability.get("required_scope_slots"))
    if not required_slots:
        return []
    # ⚠️ 未归一：required_scope_slots（卡侧名）与世界侧 f.slot_id 裸比；该键现语料
    # 从未提供（上方显式提供才启用），故未触发；启用前须先归一（2026-07-27 注）。
    all_slot_ids = {
        f.slot_id for f in building_facts + component_facts if f.slot_id
    }
    return [str(s) for s in required_slots if s not in all_slot_ids]


__all__ = [
    "collect_building_component_classes",
    "evaluate_applicability",
    "ApplicabilityResult",
]
