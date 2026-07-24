"""closure 测试用 fixture 构造器。

自造最小 FactPack / RuleSlice / RuleCardDTO，覆盖 spec §6.9 各测试路径。
所有构造器接受关键字覆盖默认，避免每个测试重复样板。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import (
    FactAtom,
    FactPack,
    RuleCardDTO,
    RuleSlice,
)

RUN_ID = "R-test-001"
WORLD_ID = "WB-test-001"
BUILDING_ID = "BLD-test-001"
BUNDLE_ID = "BUND-test-001"


def jval(value: Any) -> str:
    """把 Python 值序列化为 canonical JSON 串（FactAtom.value_json 用）。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_fact(
    fact_id: str,
    *,
    slot_id: Optional[str] = None,
    measure_key: Optional[str] = None,
    value: Any = None,
    value_type: str = "string",
    carrier_type: str = "sidecar_entry",
    carrier_id: str = BUILDING_ID,
    unit: Optional[str] = None,
    qualifiers: Optional[Dict[str, Any]] = None,
    target_ref: Optional[str] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> FactAtom:
    """构造一条 FactAtom。"""
    return FactAtom(
        fact_id=fact_id,
        world_id=WORLD_ID,
        building_id=BUILDING_ID,
        carrier_type=carrier_type,
        carrier_id=carrier_id,
        target_ref=target_ref,
        slot_id=slot_id,
        measure_key=measure_key,
        value_json=jval(value),
        value_type=value_type,
        unit=unit,
        qualifiers=qualifiers or {},
        source_path="test/path",
        source_node_id=f"node-{fact_id}",
        provenance=provenance or {},
    )


def make_fact_pack(facts: Optional[List[FactAtom]] = None) -> FactPack:
    """从一组 fact 构造 FactPack（自动建倒排索引）。"""
    facts = facts or []
    slot_index: Dict[str, List[str]] = {}
    measure_index: Dict[str, List[str]] = {}
    carrier_index: Dict[str, List[str]] = {}
    for f in facts:
        if f.slot_id:
            slot_index.setdefault(f.slot_id, []).append(f.fact_id)
        if f.measure_key:
            measure_index.setdefault(f.measure_key, []).append(f.fact_id)
        if f.carrier_id:
            carrier_index.setdefault(f.carrier_id, []).append(f.fact_id)
    return FactPack(
        run_id=RUN_ID,
        world_id=WORLD_ID,
        building_id=BUILDING_ID,
        facts=facts,
        slot_index=slot_index,
        measure_index=measure_index,
        carrier_index=carrier_index,
        source_tables=["measurements.parquet", "sidecar_entries.parquet"],
    )


def make_rule_card(
    rule_card_id: str = "RC.test.001",
    *,
    family_id: str = "FAM.test",
    applicability: Optional[Dict[str, Any]] = None,
    trigger_conditions: Optional[Dict[str, Any]] = None,
    workflow_operands: Optional[Dict[str, Any]] = None,
    slot_role_map: Optional[List[Dict[str, Any]]] = None,
    threshold_regimes: Optional[List[Dict[str, Any]]] = None,
    exceptions: Optional[List[Dict[str, Any]]] = None,
    definitions: Optional[List[Dict[str, Any]]] = None,
    obligation_graph: Optional[Dict[str, Any]] = None,
    evidence_requirements: Optional[Dict[str, Any]] = None,
    source_quote: Optional[List[Dict[str, Any]]] = None,
) -> RuleCardDTO:
    """构造一张 RuleCardDTO，applicability 默认 mbis（七字段全备，满足 identity-v2 的
    strict `ApplicabilityDTO` ingress；空列表/空串对 `evaluate_applicability` 行为等价于
    旧 `{"regime":"mbis"}`——building_scope/component_scope 空 → 跳过、subject "" 不入词桥）。

    trigger_conditions / workflow_operands / evidence_requirements 默认为**全字段齐备的空容器**
    （非裸 `{}`），镜像真卡 397/397 全带完整容器结构：blocker 2 的入口级**无条件整体
    model_validate** 要求这些容器全字段在位（空 dict 缺必填 → ValidationError）；空列表对 v1 派生
    与 `evaluate_*` 行为等价于旧 `{}`（`.get(...) or []` 两者同），故仅补齐 strict ingress、不改
    v1 语义。测试需触发"缺必填"反例时显式传 `trigger_conditions={}` 等覆盖默认。"""
    return RuleCardDTO(
        rule_card_id=rule_card_id,
        source_document_id="MBIS_CoP_2023",
        source_section=[{"clause_id": f"{rule_card_id}.clause.1"}],
        source_quote=source_quote
        or [{"source_quote_id": f"{rule_card_id}::q1", "quote_local_id": "q1"}],
        normalized_rule_text="test rule text",
        family_id=family_id,
        applicability=applicability
        if applicability is not None
        else {
            "regime": "mbis",
            "actors": [],
            "phase": "",
            "subject": "",
            "component_scope": [],
            "building_scope": [],
            "exclusions": [],
        },
        trigger_conditions=trigger_conditions
        if trigger_conditions is not None
        else {"logic": "all", "items": []},
        workflow_operands=workflow_operands
        if workflow_operands is not None
        else {
            "primary_actor": "",
            "primary_action": "",
            "recipients": [],
            "artifacts": [],
            "deadlines": [],
            "audiences": [],
            "method_keys_allowed": [],
        },
        slot_role_map=slot_role_map or [],
        threshold_regimes=threshold_regimes or [],
        exceptions=exceptions or [],
        definitions=definitions or [],
        obligation_graph=obligation_graph or {},
        evidence_requirements=evidence_requirements
        if evidence_requirements is not None
        else {"for_matching": [], "for_submission": [], "for_completion": []},
    )


def make_rule_slice(
    cards: Optional[List[RuleCardDTO]] = None,
    *,
    retrieval_policy: Optional[Dict[str, Any]] = None,
) -> RuleSlice:
    """从一组 card 构造 RuleSlice。"""
    return RuleSlice(
        run_id=RUN_ID,
        rulecard_bundle_id=BUNDLE_ID,
        candidate_rule_cards=cards or [],
        rule_families=[],
        semantic_slots=[],
        measures=[],
        artifacts=[],
        time_anchors=[],
        source_quotes=[],
        retrieval_policy=retrieval_policy or {},
    )


def catalog_for_slice(rule_slice: RuleSlice, fact_pack: FactPack, meta=None):
    """从 RuleSlice 的内存卡（合成测试无磁盘 bundle）建 identity catalog（现网键切换增补 §5.2）。

    卡 → bundle JSON 文本 → Decimal 读径 scope-aware 生成（与生产同一构造点）。合成卡
    `semantic_slots=[]` → 楼级 scope（无 fragment），与判定读径同源。
    """
    from evo_agent_baseline.closure.identity_blueprint_catalog import (
        build_identity_blueprint_catalog_from_text,
    )

    bundle_text = json.dumps(
        {
            "bundle_id": rule_slice.rulecard_bundle_id or BUNDLE_ID,
            "cards": [c.model_dump(mode="json") for c in rule_slice.candidate_rule_cards],
        },
        ensure_ascii=False,
    )
    if meta is None:
        meta = {
            "run_id": fact_pack.run_id,
            "world_id": fact_pack.world_id,
            "building_id": fact_pack.building_id,
        }
    return build_identity_blueprint_catalog_from_text(
        bundle_text, rule_slice, fact_pack, meta
    )


def run_closure(rule_slice: RuleSlice, fact_pack: FactPack, config=None, **kwargs):
    """测试用 `validate_building_closure` 包装：自动建 identity catalog（现网键切换增补 §5.2 必填入参）后调。

    转发 config + skill_invocation_ids / policy_version_id / pre_dedup_out 等 keyword。
    """
    from evo_agent_baseline.closure.validator import validate_building_closure

    catalog = catalog_for_slice(rule_slice, fact_pack)
    return validate_building_closure(
        rule_slice, fact_pack, config, identity_blueprint_catalog=catalog, **kwargs
    )
