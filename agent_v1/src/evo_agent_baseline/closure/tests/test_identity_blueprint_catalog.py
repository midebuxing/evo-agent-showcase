"""identity-v5 `IdentityBlueprintCatalog` 单测（现网键切换增补 §5 / DEBT-054 步 2-3）。

覆盖验收：
- ① card_scopes 三情形（有 fragment 逐份物化 / 空 fragment building 回退 / 楼级卡）各正确物化
  + 双读径五元组 0 差。
- ② 三审计声明表逐条件（§5.3.1）。
- ③ catalog 双 sha256 跨机可复算（同输入同 hash；改 selected card set / card_scopes → hash 变；
  所选卡全 building 时 fragment 集变 → hash 不变）。

**加性影子**：本套只测 catalog 构建 + 双读径核对 + 双 sha256，不接 live 判定主链。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from evo_agent_baseline.contracts import RuleCardDTO, SemanticSlotDTO
from evo_agent_baseline.closure import identity_blueprint_catalog as CAT
from evo_agent_baseline.closure.identity_v2 import ObligationContractError
from evo_agent_baseline.ingest import rulecard_loader
from evo_agent_baseline.retrieval import pack_builder
from evo_agent_baseline.closure.tests.fixtures import (
    RUN_ID,
    WORLD_ID,
    BUILDING_ID,
    make_fact,
    make_fact_pack,
    make_rule_slice,
)

_META = {"run_id": RUN_ID, "world_id": WORLD_ID, "building_id": BUILDING_ID}


# =========================================================================== #
# 构造 helper：合法完整卡 dict + 写临时 bundle
# =========================================================================== #


def _full_card(
    rid: str,
    *,
    slot_role_map: Optional[List[Dict[str, Any]]] = None,
    trigger_items: Optional[List[Dict[str, Any]]] = None,
    trigger_logic: str = "all",
) -> Dict[str, Any]:
    return dict(
        rule_card_id=rid,
        source_document_id="DOC",
        source_section=[{"clause_id": f"{rid}.c1"}],
        source_quote=[{"source_quote_id": f"{rid}::q1", "quote_local_id": "q1"}],
        normalized_rule_text="t",
        family_id="FAM",
        neighbor_families=[],
        applicability={
            "regime": "mbis", "actors": [], "phase": "", "subject": "",
            "component_scope": [], "building_scope": [], "exclusions": [],
        },
        trigger_conditions={"logic": trigger_logic, "items": trigger_items or []},
        workflow_operands={
            "primary_actor": "", "primary_action": "", "recipients": [],
            "artifacts": [], "deadlines": [], "audiences": [],
            "method_keys_allowed": [],
        },
        slot_role_map=slot_role_map or [],
        threshold_regimes=[],
        exceptions=[],
        definitions=[],
        obligation_graph={},
        evidence_requirements={
            "for_matching": [], "for_submission": [], "for_completion": [],
        },
    )


def _trigger(cid: str, slot_ref_id: str = "sr1") -> Dict[str, Any]:
    return {
        "condition_id": cid, "predicate_kind": "slot",
        "operator": "==", "expected_value": True, "slot_ref_id": slot_ref_id,
    }


def _slot_ref(
    slot_ref_id: str, slot_id: str, *, qualifiers: Optional[Dict[str, Any]] = None,
    roles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "slot_ref_id": slot_ref_id, "slot_id": slot_id,
        "qualifiers": qualifiers or {}, "roles": roles or ["evidence"],
        "required": True,
    }


def _write_bundle(tmp_path: Path, cards: List[Dict[str, Any]], bundle_id: str = "BUND") -> Path:
    p = tmp_path / "rule_cards.json"
    p.write_text(
        json.dumps({"bundle_id": bundle_id, "cards": cards}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def _rule_slice(cards: List[Dict[str, Any]], semantic_slots: List[SemanticSlotDTO]):
    fcards = [RuleCardDTO(**c) for c in cards]
    rs = make_rule_slice(fcards)
    return rs.model_copy(update={"semantic_slots": semantic_slots}), fcards


# fragment 承载 slot（defect 域）+ 楼级 slot（general 域）。
_SLOTS = [
    SemanticSlotDTO(slot_id="d.defect", semantic_domain="defect"),
    SemanticSlotDTO(slot_id="g.general", semantic_domain="general"),
]


def _fragment_facts(fids: List[str]):
    return make_fact_pack([
        make_fact(f"f-{fid}", slot_id="d.defect", value="x",
                  carrier_type="fragment", carrier_id=fid,
                  qualifiers={"fragment_id": fid})
        for fid in fids
    ])


# =========================================================================== #
# 真语料 bundle
# =========================================================================== #


def _find_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = (base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
                / "rule_cards.json")
        if cand.exists():
            return cand
    return None


def _real_float_cards() -> List[RuleCardDTO]:
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


# =========================================================================== #
# catalog 基本契约 + 真语料 building scope 双读径 0 差
# =========================================================================== #


def test_catalog_schema_fields_and_real_corpus_building_scope():
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    fcards = _real_float_cards()
    assert len(fcards) == 397
    rule_slice = make_rule_slice(fcards)  # semantic_slots=[] → 无 fragment 承载
    fact_pack = make_fact_pack([])         # 空事实 → fragment 集空 → building 回退
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)

    # §5.1.1 冻结顶层字段。
    assert cat.catalog_schema == "identity_blueprint_catalog_v1"
    assert cat.obligation_identity_schema == "obligation_identity_v5"
    assert cat.canonical_profile_id == "mbis_canonical_v2"
    assert len(cat.bundle_sha256) == 64
    assert len(cat.identity_catalog_sha256) == 64
    assert len(cat.blueprints) == len(cat.index)

    # 全 building scope（空 fragment 集）。
    assert {bp.identity.scope.kind for bp in cat.blueprints} == {"building"}
    channels = {bp.identity.source_channel for bp in cat.blueprints}
    assert "applicability" in channels
    assert "trigger_aggregation_audit" in channels  # v5 新审计 channel
    assert "structural_scope_audit" not in channels  # building scope 不产结构审计

    # 双读径五元组 0 差（building scope）。
    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    assert fids == []
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


def test_catalog_reproducible_same_hash():
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    fcards = _real_float_cards()
    rs = make_rule_slice(fcards)
    fp = make_fact_pack([])
    a = CAT.build_identity_blueprint_catalog(p, rs, fp, _META)
    b = CAT.build_identity_blueprint_catalog(p, rs, fp, _META)
    assert a.bundle_sha256 == b.bundle_sha256
    assert a.identity_catalog_sha256 == b.identity_catalog_sha256


def test_trigger_aggregation_audit_any_identity_aligns_across_read_paths(tmp_path):
    """KG 往返的 any 卡与权威 bundle 生成相同聚合审计五元组。"""
    card = _full_card(
        "RC.any",
        trigger_items=[_trigger("c1")],
        trigger_logic="any",
    )
    rule_node = rulecard_loader.build_rule_card_node(card)
    trigger_batch = rulecard_loader.build_trigger_nodes(card)
    row = {
        "rule_card": rule_node.all_props(),
        "applicabilities": [],
        "trigger_conditions": [
            node.all_props()
            for node in trigger_batch.nodes
            if node.label == "TriggerCondition"
        ],
        "slot_refs": [],
        "thresholds": [],
        "measures": [],
        "time_anchors": [],
        "evidence_requirements": [],
        "obligation_nodes": [],
        "obligation_edges": [],
        "workflow_artifacts": [],
        "workflow_deadlines": [],
        "workflow_recipients": [],
        "source_quotes": [],
        "artifacts": [],
    }
    float_card = pack_builder.rule_card_dto_from_subgraph(row)
    rule_slice = make_rule_slice([float_card])
    fact_pack = make_fact_pack([])
    bundle_path = _write_bundle(tmp_path, [card])
    catalog = CAT.build_identity_blueprint_catalog(
        bundle_path, rule_slice, fact_pack, _META
    )

    declared = {
        key
        for key in CAT.declare_five_tuples(float_card, [], {})
        if key[3] == "trigger_aggregation_audit"
    }
    catalog_keys = {
        key for key in catalog.index if key[3] == "trigger_aggregation_audit"
    }

    assert float_card.trigger_conditions["logic"] == "any"
    assert declared == catalog_keys


# =========================================================================== #
# ① card_scopes 三情形
# =========================================================================== #


def _scope_channel_set(cat, rid):
    return sorted(
        (bp.identity.scope.kind, bp.identity.scope.scope_id, bp.identity.source_channel)
        for bp in cat.blueprints if bp.identity.source_rule_card_id == rid
    )


def test_card_scopes_case1_fragment_bearing_per_fragment(tmp_path):
    """情形①：fragment 承载卡 + 非空 fragment 集 → 逐 fragment 物化（fragment_id 进 hash）。"""
    card = _full_card(
        "RC.frag",
        slot_role_map=[_slot_ref("sr1", "d.defect",
                                 qualifiers={"component_type_key": "wall"},
                                 roles=["trigger"])],
        trigger_items=[_trigger("c1")],
    )
    p = _write_bundle(tmp_path, [card])
    rule_slice, fcards = _rule_slice([card], _SLOTS)
    fact_pack = _fragment_facts(["FR-1", "FR-2"])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)

    got = _scope_channel_set(cat, "RC.frag")
    # applicability 一条 building；覆盖 channel + 两审计逐 fragment。
    assert ("building", "", "applicability") in got
    for fid in ("FR-1", "FR-2"):
        assert ("fragment", fid, "slot_role") in got
        assert ("fragment", fid, "trigger") in got
        assert ("fragment", fid, "structural_scope_audit") in got
        assert ("fragment", fid, "trigger_aggregation_audit") in got
    # fragment_id 进 hash → 两 fragment 的 slot_role 蓝图哈希不同。
    hashes = {
        bp.identity.scope.scope_id: bp.canonical_identity_hash
        for bp in cat.blueprints
        if bp.identity.source_channel == "slot_role"
    }
    assert hashes["FR-1"] != hashes["FR-2"]

    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    assert fids == ["FR-1", "FR-2"]
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


def test_card_scopes_case2_empty_fragment_building_fallback(tmp_path):
    """情形②：fragment 承载卡 + 空 fragment 集 → building 回退（无 fragment 孤儿蓝图）。"""
    card = _full_card(
        "RC.frag",
        slot_role_map=[_slot_ref("sr1", "d.defect",
                                 qualifiers={"component_type_key": "wall"},
                                 roles=["trigger"])],
        trigger_items=[_trigger("c1")],
    )
    p = _write_bundle(tmp_path, [card])
    rule_slice, fcards = _rule_slice([card], _SLOTS)
    fact_pack = make_fact_pack([])  # 空事实 → fragment 集空
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)

    # 均只产 building scope 蓝图，无任何 fragment scope 蓝图（无孤儿）。
    assert {bp.identity.scope.kind for bp in cat.blueprints} == {"building"}
    assert not any(
        bp.identity.source_channel == "structural_scope_audit"
        for bp in cat.blueprints
    )  # building 回退不触发结构审计
    # trigger_aggregation_audit 在 building scope 声明（卡有 trigger）。
    assert any(
        bp.identity.source_channel == "trigger_aggregation_audit"
        and bp.identity.scope.kind == "building"
        for bp in cat.blueprints
    )

    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


def test_card_scopes_case3_building_card(tmp_path):
    """情形③：楼级卡（非 fragment 承载）→ 单趟 building scope（即便有 fragment 事实）。"""
    card = _full_card(
        "RC.bldg",
        slot_role_map=[_slot_ref("sr9", "g.general")],
        trigger_items=[_trigger("c9", slot_ref_id="sr9")],
    )
    p = _write_bundle(tmp_path, [card])
    rule_slice, fcards = _rule_slice([card], _SLOTS)
    fact_pack = _fragment_facts(["FR-1", "FR-2"])  # 有 fragment 事实但卡非 fragment 承载
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)

    assert {bp.identity.scope.kind for bp in cat.blueprints} == {"building"}
    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    assert fids == ["FR-1", "FR-2"]  # fragment 集非空但楼级卡走 [None]
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


# =========================================================================== #
# ② 三审计声明表（§5.3.1）
# =========================================================================== #


def test_audit_table_structural_only_real_fragment_and_nonempty_requirement(tmp_path):
    """结构审计：仅真 fragment scope 且 component_type_key ∨ location_class_key 要求集非空。"""
    # 要求集为空的 fragment 承载卡 → 不声明 structural。
    empty_req = _full_card(
        "RC.emptyreq",
        slot_role_map=[_slot_ref("sr1", "d.defect", roles=["trigger"])],  # 无 comp/loc 限定
        trigger_items=[_trigger("c1")],
    )
    p = _write_bundle(tmp_path, [empty_req])
    rule_slice, fcards = _rule_slice([empty_req], _SLOTS)
    fact_pack = _fragment_facts(["FR-1"])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)
    assert not any(
        bp.identity.source_channel == "structural_scope_audit" for bp in cat.blueprints
    )  # 要求集全空 → 结构审计永不声明
    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


def test_audit_table_trigger_agg_only_when_has_trigger(tmp_path):
    """trigger 聚合审计：卡有 ≥1 trigger item → 声明；无 trigger 卡 → 不声明。"""
    no_trigger = _full_card("RC.notrig", slot_role_map=[_slot_ref("sr1", "g.general")])
    p = _write_bundle(tmp_path, [no_trigger])
    rule_slice, fcards = _rule_slice([no_trigger], _SLOTS)
    fact_pack = make_fact_pack([])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)
    assert not any(
        bp.identity.source_channel == "trigger_aggregation_audit"
        for bp in cat.blueprints
    )  # 无 trigger → 聚合审计不声明
    fids = CAT.derive_fragment_ids(fact_pack)
    sd = CAT.derive_slot_domain(rule_slice)
    CAT.assert_catalog_dual_read_path_consistency(cat, fcards, fids, sd)


def test_audit_table_applicability_once_per_card(tmp_path):
    """applicability 审计：每卡恒 1 条 building scope（与 fragment 迭代无关）。"""
    card = _full_card(
        "RC.frag",
        slot_role_map=[_slot_ref("sr1", "d.defect",
                                 qualifiers={"component_type_key": "wall"},
                                 roles=["trigger"])],
        trigger_items=[_trigger("c1")],
    )
    p = _write_bundle(tmp_path, [card])
    rule_slice, fcards = _rule_slice([card], _SLOTS)
    fact_pack = _fragment_facts(["FR-1", "FR-2", "FR-3"])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)
    app = [bp for bp in cat.blueprints if bp.identity.source_channel == "applicability"]
    assert len(app) == 1
    assert app[0].identity.scope.kind == "building"


# =========================================================================== #
# ③ 双 sha256 复算 + 变更检测
# =========================================================================== #


def test_catalog_sha256_change_on_selected_card_set(tmp_path):
    """改 selected card set → identity_catalog_sha256 变；bundle_sha256 不变（同 bundle）。"""
    a = _full_card("RC.a", slot_role_map=[_slot_ref("sr1", "g.general")])
    b = _full_card("RC.b", slot_role_map=[_slot_ref("sr2", "g.general")])
    p = _write_bundle(tmp_path, [a, b])
    fp = make_fact_pack([])

    rs_ab, _ = _rule_slice([a, b], _SLOTS)
    rs_a, _ = _rule_slice([a], _SLOTS)
    cat_ab = CAT.build_identity_blueprint_catalog(p, rs_ab, fp, _META)
    cat_a = CAT.build_identity_blueprint_catalog(p, rs_a, fp, _META)

    assert cat_ab.bundle_sha256 == cat_a.bundle_sha256  # 同完整 bundle
    assert cat_ab.identity_catalog_sha256 != cat_a.identity_catalog_sha256  # 卡集变


def test_catalog_sha256_change_on_card_scopes(tmp_path):
    """改实际 card_scopes（fragment 集，作用于 fragment 承载卡）→ identity_catalog_sha256 变。"""
    card = _full_card(
        "RC.frag",
        slot_role_map=[_slot_ref("sr1", "d.defect",
                                 qualifiers={"component_type_key": "wall"},
                                 roles=["trigger"])],
        trigger_items=[_trigger("c1")],
    )
    p = _write_bundle(tmp_path, [card])
    rule_slice, _ = _rule_slice([card], _SLOTS)
    cat1 = CAT.build_identity_blueprint_catalog(
        p, rule_slice, _fragment_facts(["FR-1"]), _META
    )
    cat2 = CAT.build_identity_blueprint_catalog(
        p, rule_slice, _fragment_facts(["FR-1", "FR-2"]), _META
    )
    assert cat1.identity_catalog_sha256 != cat2.identity_catalog_sha256


def test_catalog_sha256_unchanged_all_building_fragment_set_varies(tmp_path):
    """所选卡全 building-scoped 时，fragment 集变化**不改** identity_catalog_sha256（§5.1）。"""
    card = _full_card("RC.bldg", slot_role_map=[_slot_ref("sr9", "g.general")])
    p = _write_bundle(tmp_path, [card])
    rule_slice, _ = _rule_slice([card], _SLOTS)
    cat_empty = CAT.build_identity_blueprint_catalog(
        p, rule_slice, make_fact_pack([]), _META
    )
    cat_frag = CAT.build_identity_blueprint_catalog(
        p, rule_slice, _fragment_facts(["FR-1", "FR-2"]), _META
    )
    # 楼级卡 card_scopes 恒 [None]，fragment 集变化不改 manifest → 同 hash。
    assert cat_empty.identity_catalog_sha256 == cat_frag.identity_catalog_sha256


# =========================================================================== #
# 硬失败闸
# =========================================================================== #


def test_card_set_mismatch_hardfail(tmp_path):
    """RuleSlice 卡不在 bundle → read_path_card_set_mismatch。"""
    a = _full_card("RC.a", slot_role_map=[_slot_ref("sr1", "g.general")])
    ghost = _full_card("RC.ghost", slot_role_map=[_slot_ref("sr2", "g.general")])
    p = _write_bundle(tmp_path, [a])  # bundle 只有 RC.a
    rule_slice, _ = _rule_slice([a, ghost], _SLOTS)  # slice 含 bundle 没有的 RC.ghost
    with pytest.raises(ObligationContractError, match="read_path_card_set_mismatch"):
        CAT.build_identity_blueprint_catalog(p, rule_slice, make_fact_pack([]), _META)


def test_require_miss_hardfail(tmp_path):
    """catalog.require 未命中五元组 → blueprint_association_miss（不 fail-open）。"""
    card = _full_card("RC.a", slot_role_map=[_slot_ref("sr1", "g.general")])
    p = _write_bundle(tmp_path, [card])
    rule_slice, _ = _rule_slice([card], _SLOTS)
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, make_fact_pack([]), _META)
    with pytest.raises(ObligationContractError, match="blueprint_association_miss"):
        cat.require(("RC.a", "building", "", "trigger", "no-such-sid"))


# ===========================================================================
# catalog 自洽闸（现网键切换增补 §5.1）：header 三字段 / index 完备 / sha256 重算
# ===========================================================================


def _built_catalog(tmp_path):
    card = _full_card("RC.a", slot_role_map=[_slot_ref("sr1", "g.general")])
    p = _write_bundle(tmp_path, [card])
    rule_slice, _ = _rule_slice([card], _SLOTS)
    fp = make_fact_pack([])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fp, _META)
    return cat, rule_slice, fp


def test_catalog_header_and_hash_gate_valid_passes(tmp_path):
    """合法 catalog 过 header/hash 自洽闸（§5.1，不抛）。"""
    cat, _, _ = _built_catalog(tmp_path)
    CAT.assert_catalog_header_and_hash(cat)  # 不抛


def test_catalog_header_mismatch_hardfail(tmp_path):
    """header 三字段任一 != 冻结常量 → catalog_header_mismatch（拦 header v4 / 错 profile）。"""
    cat, _, _ = _built_catalog(tmp_path)
    bad_schema = dataclasses.replace(cat, obligation_identity_schema="obligation_identity_v4")
    with pytest.raises(ObligationContractError, match="catalog_header_mismatch"):
        CAT.assert_catalog_header_and_hash(bad_schema)
    bad_profile = dataclasses.replace(cat, canonical_profile_id="mbis_canonical_vX")
    with pytest.raises(ObligationContractError, match="catalog_header_mismatch"):
        CAT.assert_catalog_header_and_hash(bad_profile)


def test_catalog_hash_mismatch_hardfail(tmp_path):
    """identity_catalog_sha256 与内容不符 → catalog_hash_mismatch（拦伪 hash）。"""
    cat, _, _ = _built_catalog(tmp_path)
    faked = dataclasses.replace(cat, identity_catalog_sha256="0" * 64)
    with pytest.raises(ObligationContractError, match="catalog_hash_mismatch"):
        CAT.assert_catalog_header_and_hash(faked)


def test_validate_building_closure_hardfails_faked_catalog(tmp_path):
    """伪 hash catalog 进 validate_building_closure 入口即 hard-fail（§5.1 闸生效于主入口）。"""
    from evo_agent_baseline.closure.validator import validate_building_closure

    cat, rule_slice, fp = _built_catalog(tmp_path)
    faked = dataclasses.replace(cat, identity_catalog_sha256="0" * 64)
    with pytest.raises(ObligationContractError, match="catalog_hash_mismatch"):
        validate_building_closure(rule_slice, fp, identity_blueprint_catalog=faked)


def test_catalog_index_not_anchored_to_blueprints_hardfail(tmp_path):
    """伪索引穿透闸（codex 019f7328 阻断 2 负测）：保持 blueprints/hash 不变，仅把
    index[key] 换成**同五元组但 immutable 翻转**的伪蓝图 → 旧闸（键集+自身五元组）通过、
    新闸（从 blueprints 重建期望索引+对象全等）必须 `index_not_anchored_to_blueprints`。"""
    cat, _, _ = _built_catalog(tmp_path)
    key, real_bp = next(iter(cat.index.items()))
    forged_bp = real_bp.model_copy(
        update={
            "immutable": real_bp.immutable.model_copy(
                update={"required": not real_bp.immutable.required}
            )
        }
    )
    assert forged_bp != real_bp  # 伪蓝图确实不同（immutable 翻转）
    forged_index = dict(cat.index)
    forged_index[key] = forged_bp
    forged_cat = dataclasses.replace(cat, index=forged_index)
    with pytest.raises(
        ObligationContractError, match="index_not_anchored_to_blueprints"
    ):
        CAT.assert_catalog_header_and_hash(forged_cat)
