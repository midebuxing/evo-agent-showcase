"""DEBT-096 案甲：角色感知限定符读取验收（决议_debt096_20260808.md，两线全票）。

裁定：trigger 与 definition_reference 角色的限定符参与卡的结构早退；evidence 与
prerequisite 角色不得收窄整卡适用（法理＝件乙定稿 v2 escape hatch 首次真实触发
＋s423 prerequisite 先例）。修法＝案甲：_card_qualifier_values 剔
roles ⊆ {evidence, prerequisite} 的槽；多角色/未知角色缺省参与。零卡改动、零指纹。
影响面：恰 1 张卡（sapp7_6_1_f）集合变--305 组反坍缩；其余 29 卡零变动。

本文件验收三件事：
1. blueprint_deriver._card_qualifier_values 角色感知逐角色单测；
2. 双径一致性（validator 闭包行为 ↔ blueprint_deriver 直接调用）；
3. 变异对照（evidence 被剔 -> 不早退；换 definition_reference -> 保留 -> 早退，
   等价「把 evidence 角色放回并集 ⇒ sapp7_6_1_f 卡 305 组重新坍缩应红」）。
"""
from __future__ import annotations

from evo_agent_baseline.contracts import RuleSlice, SemanticSlotDTO
from evo_agent_baseline.closure import blueprint_deriver as B

from .fixtures import (
    BUNDLE_ID, RUN_ID, make_fact, make_fact_pack, make_rule_card, run_closure,
)

SCOPE_SLOT = "risk.fire_safety.adverse_impact"  # risk 域 -> fragment-scoped
CARD_ID = "RC.debt096.001"
LC = "location_class_key"


def _sr(ref_id="sr01", roles=("evidence",), lc="private_premises"):
    return {
        "slot_ref_id": ref_id, "slot_id": SCOPE_SLOT,
        "roles": list(roles), "required": True,
        "qualifiers": {LC: lc} if lc else {},
    }


def _card(roles=("evidence",), lc="private_premises"):
    return make_rule_card(rule_card_id=CARD_ID, slot_role_map=[_sr(roles=roles, lc=lc)])


def _policy():
    return {
        "projection_runtime_mapping_v1": {
            "qualifier_value_aliases": {
                LC: {
                    "private_premises": "private_premises",
                    "common_part": "common_part",
                },
            },
        },
    }


def _slice(card):
    return RuleSlice(
        run_id=RUN_ID, rulecard_bundle_id=BUNDLE_ID,
        candidate_rule_cards=[card], rule_families=[],
        semantic_slots=[SemanticSlotDTO(slot_id=SCOPE_SLOT, semantic_domain="risk")],
        measures=[], artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy=_policy(),
    )


def _frag_lc(frag, lc):
    return make_fact(
        f"flc-{frag}", slot_id=SCOPE_SLOT, value=True, value_type="boolean",
        carrier_type="fragment", carrier_id=frag,
        qualifiers={"fragment_id": frag, LC: lc},
    )


def _lc_na(obls, frag):
    """location 轴结构早退 NA 义务。"""
    return [
        o for o in obls
        if o.fragment_id == frag and o.kind == "scope"
        and o.satisfaction_status == "not_applicable"
        and "location_class_key" in (o.notes or "")
    ]


# =========================================================================== #
# 1. blueprint_deriver 角色感知逐角色单测
# =========================================================================== #


def test_evidence_role_excluded():
    """evidence 角色槽的限定符不参与（被剔）。"""
    assert B._card_qualifier_values(_card(("evidence",)), LC) == set()


def test_prerequisite_role_excluded():
    """prerequisite 角色槽的限定符不参与（被剔）。"""
    assert B._card_qualifier_values(_card(("prerequisite",)), LC) == set()


def test_evidence_prerequisite_pure_subset_excluded():
    """evidence+prerequisite 纯子集被剔。"""
    assert B._card_qualifier_values(_card(("evidence", "prerequisite")), LC) == set()


def test_trigger_role_retained():
    """trigger 角色槽的限定符保留。"""
    assert B._card_qualifier_values(_card(("trigger",)), LC) == {"private_premises"}


def test_definition_reference_role_retained():
    """definition_reference 角色槽的限定符保留。"""
    assert B._card_qualifier_values(_card(("definition_reference",)), LC) == {"private_premises"}


def test_multi_role_with_trigger_retained():
    """多角色含 trigger -> 保留（不是纯 evidence/prerequisite 子集）。"""
    assert B._card_qualifier_values(_card(("evidence", "trigger")), LC) == {"private_premises"}


def test_empty_roles_default_retained():
    """roles 空 -> 缺省参与（保留）。"""
    assert B._card_qualifier_values(_card((), lc="private_premises"), LC) == {"private_premises"}


def test_trigger_item_qualifier_retained():
    """trigger_conditions.items 自带 qualifiers 不受角色过滤（本就是 trigger 角色）。"""
    card = make_rule_card(
        rule_card_id=CARD_ID,
        slot_role_map=[_sr(roles=("evidence",), lc=None)],
        trigger_conditions={"logic": "all", "items": [
            {
                "condition_id": "c1", "predicate_kind": "slot", "operator": "==",
                "expected_value": True, "slot_ref_id": "sr01",
                "qualifiers": {LC: "private_premises"},
            },
        ]},
    )
    # evidence 槽 lc=None -> 无 lc；trigger item 自带 lc 保留
    assert B._card_qualifier_values(card, LC) == {"private_premises"}


# =========================================================================== #
# 2. 双径一致性（validator 闭包行为 ↔ blueprint_deriver 直接调用）
# =========================================================================== #


def test_dual_path_evidence_excluded_both_sides():
    """evidence 角色：blueprint 侧返回空集，validator 侧不早退（反坍缩）。

    等价 sapp7_6_1_f：evidence 槽带 lc=private_premises，fragment lc=common_part
    （无交集）。改前 _card_lc 含 private_premises -> 早退（坍缩）；
    改后剔 evidence -> _card_lc 空 -> 不早退（反坍缩）。
    """
    frag = "FR-D96-EV"
    card = _card(("evidence",))
    facts = [_frag_lc(frag, "common_part")]
    # blueprint 侧
    assert B._card_qualifier_values(card, LC) == set()
    # validator 侧（不传 applicability_bundle -> component 轴不早退，只测 location 轴）
    obls = run_closure(_slice(card), make_fact_pack(facts)).obligation_set.obligations
    assert not _lc_na(obls, frag)


def test_dual_path_def_ref_retained_both_sides():
    """definition_reference 角色：blueprint 侧保留，validator 侧早退（仍坍缩）。

    变异对照：同卡同 fragment，仅 roles 从 evidence 换成 definition_reference ->
    限定符回到并集 -> 重新坍缩。这就是「把 evidence 角色放回并集 ⇒ sapp7_6_1_f
    卡 305 组重新坍缩应红」的等价验收。
    """
    frag = "FR-D96-DR"
    card = _card(("definition_reference",))
    facts = [_frag_lc(frag, "common_part")]
    # blueprint 侧
    assert B._card_qualifier_values(card, LC) == {"private_premises"}
    # validator 侧
    obls = run_closure(_slice(card), make_fact_pack(facts)).obligation_set.obligations
    assert _lc_na(obls, frag)


# =========================================================================== #
# 3. 变异对照（同一 fragment 配置，evidence -> 不早退；def_ref -> 早退）
# =========================================================================== #


def test_variant_evidence_vs_def_ref_collapse():
    """变异对照核心：同一 fragment 配置，evidence 角色卡不早退（反坍缩），
    definition_reference 角色卡早退（仍坍缩）。两者除 roles 外逐字段相同。"""
    frag = "FR-D96-VAR"
    facts = [_frag_lc(frag, "common_part")]
    ev_obls = run_closure(
        _slice(_card(("evidence",))), make_fact_pack(facts)
    ).obligation_set.obligations
    dr_obls = run_closure(
        _slice(_card(("definition_reference",))), make_fact_pack(facts)
    ).obligation_set.obligations
    assert not _lc_na(ev_obls, frag)
    assert _lc_na(dr_obls, frag)
