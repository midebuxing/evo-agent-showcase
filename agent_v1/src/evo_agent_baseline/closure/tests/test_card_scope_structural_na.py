"""卡 fragment 级组件结构不相容早退(DEBT-065 第一波:正向授权可证排斥)。

判据从旧"词表值集空交=互斥"改为 v2.2 §3.1:授权表取该卡单目标叶型,fragment 取单值
W0 身份,二者显式登记于 disjoint_pairs 才早退(kind=scope NA)。缺省拒绝:未授权/身份
未知/非叶/未登记排斥 → 不早退(不产未证成 NA)。

历史(DEBT-050 件乙,已废止):曾以"卡 component 限定与 fragment 组件身份词表值无交集"
早退,codex 穷尽裁定该判据无证明责任基础(词表四轴混装),乙案降调、本周期改正向授权。
"""
from __future__ import annotations

import itertools

from evo_agent_baseline.contracts import RuleSlice, SemanticSlotDTO

from .fixtures import (
    BUNDLE_ID, RUN_ID, make_fact, make_fact_pack, make_rule_card, run_closure,
)

SCOPE_SLOT = "scope.component.inspection_included"
CARD_ID = "RC.fire.001"
_LEAF = ["external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"]
_LATTICE = {
    "leaf_types": _LEAF,
    "disjoint_pairs": [sorted(p) for p in itertools.combinations(sorted(_LEAF), 2)],
}


def _policy(auth=None):
    policy = {
        "projection_runtime_mapping_v1": {
            "qualifier_value_aliases": {
                "component_type_key": {
                    "external_wall": "external_wall",
                    "fire_safety_component": "fire_safety_component",
                    "structural_member": "structural_component",
                }
            },
        },
        "component_type_lattice": _LATTICE,
    }
    if auth is not None:
        policy["exact_fragment_target_authorizations"] = auth
    return policy


def _slice(card, auth=None):
    return RuleSlice(
        run_id=RUN_ID, rulecard_bundle_id=BUNDLE_ID,
        candidate_rule_cards=[card], rule_families=[],
        semantic_slots=[SemanticSlotDTO(slot_id=SCOPE_SLOT, semantic_domain="scope")],
        measures=[], artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy=_policy(auth),
    )


def _frag_fact(frag, ct):
    """fragment 的 W0 组件身份专用原子(slot_id=='w0_component_identity' + provenance channel,
    模拟检索器 enrich 从原始 Fragment→Component 生成的身份原子)。"""
    return make_fact(
        f"w0id-{frag}", slot_id="w0_component_identity", value=ct,
        carrier_type="fragment", carrier_id=frag,
        qualifiers={"fragment_id": frag, "component_id": f"comp-{frag}", "canonical_component_type": ct},
        provenance={"channel": "w0_component_identity", "derivation": "fragment_component_projection"},
    )


def _id_atom(frag, ct, fid_suffix="2"):
    """同 fragment 的第二条身份原子(测多来源 dup)。"""
    return make_fact(
        f"w0id{fid_suffix}-{frag}", slot_id="w0_component_identity", value=ct,
        carrier_type="fragment", carrier_id=frag,
        qualifiers={"fragment_id": frag, "component_id": f"comp{fid_suffix}-{frag}", "canonical_component_type": ct},
        provenance={"channel": "w0_component_identity", "derivation": "fragment_component_projection"},
    )


def _card(component_type_key="fire_safety_component"):
    roles = [{
        "slot_ref_id": "sr01", "slot_id": SCOPE_SLOT,
        "roles": ["definition_reference"], "required": True,
        "qualifiers": ({"component_type_key": component_type_key} if component_type_key else {}),
    }]
    return make_rule_card(rule_card_id=CARD_ID, slot_role_map=roles)


def _obls(card, facts, auth=None):
    return run_closure(_slice(card, auth), make_fact_pack(facts)).obligation_set.obligations


def _early_exit(obls, frag):
    return [o for o in obls if o.fragment_id == frag and o.kind == "scope"
            and o.satisfaction_status == "not_applicable"
            and "structurally_unsatisfiable_card_scope" in (o.notes or "")]


def test_authorized_disjoint_identity_early_exit() -> None:
    """授权目标叶型 × fragment 叶身份 可证排斥 → 早退(fire_safety 授权卡 vs 外墙 fragment)。"""
    obls = _obls(
        _card("fire_safety_component"),
        [_frag_fact("FR-WALL", "external_wall")],
        auth={CARD_ID: "fire_safety_component"},
    )
    assert _early_exit(obls, "FR-WALL")
    assert not any(o.blocked_reason_code == "qualifier_conflict" for o in obls)


def test_unauthorized_card_no_early_exit() -> None:
    """卡不在授权表(缺省拒绝)→ 不早退,即使身份与卡限定排斥。"""
    obls = _obls(
        _card("fire_safety_component"),
        [_frag_fact("FR-WALL", "external_wall")],
        auth=None,
    )
    assert not _early_exit(obls, "FR-WALL")


def test_authorized_compatible_identity_no_early_exit() -> None:
    """授权目标 × 同叶身份(不排斥)→ 不早退(消防授权卡 vs 消防 fragment)。"""
    obls = _obls(
        _card("fire_safety_component"),
        [_frag_fact("FR-FIRE", "fire_safety_component")],
        auth={CARD_ID: "fire_safety_component"},
    )
    assert not _early_exit(obls, "FR-FIRE")


def test_non_leaf_identity_no_early_exit() -> None:
    """fragment 身份非叶型(structural_component)→ 不早退(非叶不参与可证排斥)。"""
    obls = _obls(
        _card("fire_safety_component"),
        [_frag_fact("FR-STRUCT", "structural_component")],  # 非叶身份
        auth={CARD_ID: "fire_safety_component"},
    )
    assert not _early_exit(obls, "FR-STRUCT")


def test_identity_unknown_no_early_exit() -> None:
    """fragment 无 component 事实 → 身份未知 → 不早退(§3.0 保守)。"""
    frag_fact = make_fact(
        "f-noct", slot_id="defect.class.present", value=True, value_type="boolean",
        carrier_type="fragment", carrier_id="FR-NOCT",
        qualifiers={"fragment_id": "FR-NOCT"},
    )
    obls = _obls(_card("fire_safety_component"), [frag_fact], auth={CARD_ID: "fire_safety_component"})
    assert not _early_exit(obls, "FR-NOCT")


def test_multi_value_identity_no_early_exit() -> None:
    """同 fragment 多条身份原子(多来源)→ dup → 单值身份不成立 → 不早退(§3.0)。"""
    facts = [_frag_fact("FR-MULTI", "external_wall"), _id_atom("FR-MULTI", "drainage_component")]
    obls = _obls(_card("fire_safety_component"), facts, auth={CARD_ID: "fire_safety_component"})
    assert not _early_exit(obls, "FR-MULTI")


def test_no_lattice_asset_conservative_no_early_exit() -> None:
    """policy 无组件类型格资产 → runtime 保守关闭组件结构早退(不早退)。"""
    card = _card("fire_safety_component")
    slc = RuleSlice(
        run_id=RUN_ID, rulecard_bundle_id=BUNDLE_ID,
        candidate_rule_cards=[card], rule_families=[],
        semantic_slots=[SemanticSlotDTO(slot_id=SCOPE_SLOT, semantic_domain="scope")],
        measures=[], artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy={"exact_fragment_target_authorizations": {CARD_ID: "fire_safety_component"}},
    )
    obls = run_closure(slc, make_fact_pack([_frag_fact("FR-WALL", "external_wall")])).obligation_set.obligations
    assert not _early_exit(obls, "FR-WALL")


def test_incidental_component_qualifier_not_identity() -> None:
    """P1-1 红线:普通事实(非 slot_id=='component_type')携带的 component_type_key 不得被
    误认作身份。defect 事实带 external_wall 但无 genuine 身份来源 → 不早退(旧 _frag_ct 近似
    会把它当身份→与授权 fire_safety 排斥→错早退=未证成 NA)。"""
    defect_fact = make_fact(
        "df", slot_id="defect.class.present", value=True, value_type="boolean",
        carrier_type="fragment", carrier_id="FR-INCID",
        qualifiers={"fragment_id": "FR-INCID", "component_type_key": "external_wall"},
    )
    obls = _obls(_card("fire_safety_component"), [defect_fact], auth={CARD_ID: "fire_safety_component"})
    assert not _early_exit(obls, "FR-INCID")


def test_same_value_multi_source_not_folded() -> None:
    """P1-1 红线:同值多来源不得 set 折叠成假'单值身份'。两条 slot_id=='component_type'
    事实(均 external_wall)→ count==2 → 身份不成立 → 不早退。"""
    facts = [_frag_fact("FR-DUP", "external_wall"), _id_atom("FR-DUP", "external_wall")]
    obls = _obls(_card("fire_safety_component"), facts, auth={CARD_ID: "fire_safety_component"})
    assert not _early_exit(obls, "FR-DUP")
