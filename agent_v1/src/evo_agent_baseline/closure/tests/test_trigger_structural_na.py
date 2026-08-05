"""触发器限定符结构不可满足 → NA（DEBT-050 修案·spec §6.3.3 增补，2026-07-08）。

codex 裁决（方案甲通过/乙否决）测试面：不相容判 NA 三形态、相容保持 missing
（供给缺口护栏）、已有绑定零覆盖、类目成员展开、身份/词表缺失回落、脏 T 护栏。
"""

from __future__ import annotations

import itertools

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_trigger

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
KNOWN = {"structural_component", "drainage_component", "external_wall",
         "cantilevered_canopy", "external_component", "wall_tiles"}
# DEBT-065:组件类型格叶集 + 显式排斥对(触发器级新判据用)。
_LEAF = ["external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"]
_DISJOINT = {frozenset(p) for p in itertools.combinations(_LEAF, 2)}


def _slot_trigger(**over):
    trig = {
        "condition_id": "trg01",
        "predicate_kind": "slot",
        "slot_id": "defect.class.present",
        "operator": "==",
        "expected_value": True,
        "qualifiers": {"defect_class_key": "structural_damage_sign",
                       "component_type_key": "structural_component"},
    }
    trig.update(over)
    return trig


def _empty_index():
    return FactIndex(make_fact_pack([]))


def test_incompatible_fragment_scope_na() -> None:
    """DEBT-065:触发器组件限定恒等于授权目标叶型 × fragment 叶身份可证排斥 → NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META,
        auth_target="cantilevered_canopy",
        w0_identity="drainage_component",
        lattice_disjoint=_DISJOINT,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert o.comparator_result is False
    assert "structurally_unsatisfiable_qualifier" in (o.notes or "")


def test_building_scope_component_na_abolished() -> None:
    """DEBT-065:组件维楼级结构 NA 废止——楼级(单值身份 None)→ 不早退,回落 missing。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META,
        auth_target="cantilevered_canopy",
        w0_identity=None,
        lattice_disjoint=_DISJOINT,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


KNOWN_LC = {"external", "common_part", "common_pipe_duct",
            "public_access_private_lane", "roof_or_platform"}


def test_incompatible_location_na() -> None:
    """②location 维度：卡要 private_lane、fragment location=common_pipe_duct → NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "location_class_key" in (o.notes or "")


def test_compatible_location_keeps_missing() -> None:
    """location 相容而事实缺 → 仍 missing_fact（供给缺口诚实）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "common_pipe_duct"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_location_unknown_scope_falls_back_missing() -> None:
    """作用域 location 未知（None）→ 不判 NA，保持 missing。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_location_classes=None, known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_location_dirty_value_falls_back_missing() -> None:
    """卡 location 脏值（不在已知宇宙）→ 不判 NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"location_class_key": "typo_location"}),
        _empty_index(), META,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"


def test_component_or_location_disjunction() -> None:
    """component 相容但 location 不相容 → 仍 NA（析取）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "drainage_component",
                                  "location_class_key": "public_access_private_lane"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
        scope_location_classes={"common_pipe_duct"},
        known_location_classes=KNOWN_LC,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "location_class_key" in (o.notes or "")


def test_compatible_scope_keeps_missing() -> None:
    """结构部位上要求 structural_component 而事实缺 → 仍 open/missing_fact（供给缺口诚实）。"""
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), _empty_index(), META,
        scope_component_types={"structural_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_category_member_not_na() -> None:
    """T 为类目且部位类型属 members（validator 预展开进相容集）→ 不 NA。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "external_component"}),
        _empty_index(), META,
        # validator 端 _with_categories 已把 external_component 并入外墙部位的相容集
        scope_component_types={"external_wall", "external_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_existing_binding_never_overridden() -> None:
    """已有绑定（即便与相容集矛盾）→ 走正常比较，结构判定绝不触发。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", slot_id="defect.class.present", value=True,
                  value_type="boolean",
                  qualifiers={"defect_class_key": "structural_damage_sign",
                              "component_type_key": "structural_component"}),
    ]))
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), idx, META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_scope_identity_unknown_falls_back_missing() -> None:
    """作用域身份未知（None）→ 判定关闭，保持 missing_fact。"""
    o = evaluate_trigger(
        make_rule_card(), _slot_trigger(), _empty_index(), META,
        scope_component_types=None, known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_unknown_t_value_falls_back_missing() -> None:
    """T 不在已知身份宇宙（卡端脏值）→ 不得推断 NA，回落 missing_fact。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "typo_component"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


def test_no_component_qualifier_unaffected() -> None:
    """无 component_type_key 限定的触发器（如 s4_3_1_a 单键）行为不变。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"defect_class_key": "crack"}),
        _empty_index(), META,
        scope_component_types={"drainage_component"},
        known_component_types=KNOWN,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_fact"


# ---------------------------------------------------------------------------
# 「乙」放宽档（2026-08-01，ct_disjoint_na_relaxed，缺省关闭）：
# req_ct 与 fragment 身份显式登记 disjoint 即 NA，不再要求 req_ct 恒等于授权目标。
# 同日 codex 审核门收紧：**限定符键须恰好只有 component_type_key**（多轴不翻）。
# 测试面：缺省等价（不传 flag 行为逐位不变）、缺省拒绝四形态（未登记/身份未知/
# 同型/多轴 全不翻）、归因标记只落在放宽档命中上（严档 NA 不带标记）。
# ---------------------------------------------------------------------------

def _mismatched_component_fact():
    """槽上有事实、component 是唯一不匹配轴 → 严档下 qualifier_conflict。"""
    return make_fact(
        "F-relax-01",
        slot_id="defect.class.present",
        value=True, value_type="boolean",
        qualifiers={"component_type_key": "external_wall"},
    )


def test_relaxed_default_off_keeps_qualifier_conflict() -> None:
    """缺省（不传 flag）：无授权 + 事实限定符不匹配 → 仍 blocked/qualifier_conflict。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        FactIndex(make_fact_pack([_mismatched_component_fact()])), META,
        auth_target=None,
        w0_identity="external_wall",
        lattice_disjoint=_DISJOINT,
    )
    assert (o.closure_status, o.blocked_reason_code) == ("blocked", "qualifier_conflict")
    assert "[relaxed_disjoint_na]" not in (o.notes or "")


def test_relaxed_on_unauthorized_disjoint_flips_na() -> None:
    """开 flag：无授权但单轴 (req_ct, 身份) 显式 disjoint → NA，notes 带放宽档标记。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        FactIndex(make_fact_pack([_mismatched_component_fact()])), META,
        auth_target=None,
        w0_identity="external_wall",
        lattice_disjoint=_DISJOINT,
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert o.comparator_result is False
    assert "[relaxed_disjoint_na]" in (o.notes or "")


def test_relaxed_multi_axis_keeps_conflict() -> None:
    """开 flag 但限定符是多轴（组件+缺陷类）→ 审核门收紧：不翻，保持 qualifier_conflict。

    真实反例形状（审核门给出）：附录五 §2.3 环氧树脂卡法规前提是「如使用環氧樹脂」
    不是片段主身份——多轴命中在规格授权「组件轴独立且充分」之前一律不许 NA。
    """
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"defect_class_key": "structural_damage_sign",
                                  "component_type_key": "cantilevered_canopy"}),
        FactIndex(make_fact_pack([make_fact(
            "F-relax-02", slot_id="defect.class.present",
            value=True, value_type="boolean",
            qualifiers={"defect_class_key": "structural_damage_sign",
                        "component_type_key": "external_wall"},
        )])), META,
        auth_target=None,
        w0_identity="external_wall",
        lattice_disjoint=_DISJOINT,
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.blocked_reason_code) == ("blocked", "qualifier_conflict")
    assert "[relaxed_disjoint_na]" not in (o.notes or "")


def test_relaxed_same_type_keeps_original() -> None:
    """开 flag 但 req_ct == fragment 身份（同型）→ 不翻（此处事实缺 → missing_fact）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "external_wall"}),
        _empty_index(), META,
        auth_target=None,
        w0_identity="external_wall",
        lattice_disjoint=_DISJOINT,
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.open_reason_code) == ("open", "missing_fact")
    assert "[relaxed_disjoint_na]" not in (o.notes or "")


def test_relaxed_on_unregistered_pair_keeps_conflict() -> None:
    """开 flag 但 (req_ct, 身份) 未登记 disjoint → 缺省拒绝，保持 qualifier_conflict（不猜）。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        FactIndex(make_fact_pack([_mismatched_component_fact()])), META,
        auth_target=None,
        w0_identity="external_wall",
        lattice_disjoint=set(),          # 未登记任何排斥对
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.blocked_reason_code) == ("blocked", "qualifier_conflict")


def test_relaxed_on_identity_unknown_keeps_conflict() -> None:
    """开 flag 但 fragment 身份未知（None）→ 缺省拒绝，保持 qualifier_conflict。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        FactIndex(make_fact_pack([_mismatched_component_fact()])), META,
        auth_target=None,
        w0_identity=None,
        lattice_disjoint=_DISJOINT,
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.blocked_reason_code) == ("blocked", "qualifier_conflict")


def test_relaxed_missing_fact_shape_also_na() -> None:
    """槽整体无事实（missing_fact 形态）：flag 关保持 open，flag 开同样 NA——
    结构不可满足与「有事实但不匹配」在放宽档语义上是同一件事。"""
    kw = dict(
        auth_target=None, w0_identity="external_wall", lattice_disjoint=_DISJOINT,
    )
    off = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META, **kw,
    )
    assert (off.closure_status, off.open_reason_code) == ("open", "missing_fact")
    on = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META, ct_disjoint_na_relaxed=True, **kw,
    )
    assert (on.closure_status, on.satisfaction_status) == ("closed", "not_applicable")
    assert "[relaxed_disjoint_na]" in (on.notes or "")


def test_relaxed_flag_integration_via_validate_building_closure() -> None:
    """入口集成（2026-08-01 codex 审核门小缺口②）：主链 `validate_building_closure`
    的 `trigger_ct_disjoint_na` ①缺省(不传)与显式 False **逐位等价**；②显式 True 时
    无授权+单轴 disjoint 的 fragment 触发器经主链翻 NA 并带放宽档标记，
    楼级（身份 None）同一触发器不翻。"""
    import itertools as _it

    from evo_agent_baseline.contracts import RuleSlice, SemanticSlotDTO
    from evo_agent_baseline.closure.applicability_v3 import ApplicabilityBundle

    from .fixtures import BUNDLE_ID, RUN_ID, run_closure

    # 契约面：TriggerItemDTO 无 slot_id 字段（extra_forbidden），触发器经 slot_ref_id
    # 引用 slot_role_map（spec §6.3.3），限定符由角色表条目携带（map_qualifiers 路径）。
    card = make_rule_card(
        rule_card_id="RC.relax.int01",
        slot_role_map=[{
            "slot_ref_id": "sr01", "slot_id": "defect.class.present",
            "roles": ["trigger"], "required": False,
            "qualifiers": {"component_type_key": "cantilevered_canopy"},
        }],
        trigger_conditions={"logic": "all", "items": [{
            "condition_id": "trg01", "predicate_kind": "slot",
            "operator": "==", "expected_value": True,
            "slot_ref_id": "sr01",
        }]},
    )
    rs = RuleSlice(
        run_id=RUN_ID, rulecard_bundle_id=BUNDLE_ID,
        candidate_rule_cards=[card], rule_families=[],
        semantic_slots=[SemanticSlotDTO(
            slot_id="defect.class.present", semantic_domain="defect")],
        measures=[], artifacts=[], time_anchors=[], source_quotes=[],
        retrieval_policy={},
    )
    fp = make_fact_pack([make_fact(
        "f-relax-int", slot_id="defect.class.present",
        value=True, value_type="boolean",
        carrier_type="fragment", carrier_id="FR-WALL",
        qualifiers={"component_type_key": "external_wall",
                    "fragment_id": "FR-WALL"},
    )])
    bundle = ApplicabilityBundle(
        bundle_sha256="t", leaf_types=frozenset(_LEAF),
        disjoint_pairs=frozenset(
            frozenset(p) for p in _it.combinations(sorted(_LEAF), 2)),
        card_targets={},                                   # 无授权（缺省拒绝面）
        fragment_identities={"FR-WALL": "external_wall"},
    )

    def rows(res):
        return [(o.kind, o.fragment_id or "", str(o.closure_status),
                 str(o.satisfaction_status), str(o.blocked_reason_code or ""),
                 str(o.notes or ""))
                for o in res.obligation_set.obligations]

    off_default = run_closure(rs, fp, applicability_bundle=bundle)
    off_explicit = run_closure(rs, fp, applicability_bundle=bundle,
                               trigger_ct_disjoint_na=False)
    on = run_closure(rs, fp, applicability_bundle=bundle,
                     trigger_ct_disjoint_na=True)

    # ①缺省 == 显式 False：主链义务集逐位等价（缺省等价在入口层成立）。
    assert rows(off_default) == rows(off_explicit)

    def trig(res, frag):
        return [o for o in res.obligation_set.obligations
                if o.kind == "trigger" and (o.fragment_id or "") == frag]

    t_off = trig(off_default, "FR-WALL")
    assert t_off and any(
        o.blocked_reason_code == "qualifier_conflict" for o in t_off)
    # ②开关经主链传到 fragment 触发器：翻 NA + 放宽档标记
    # （注意 trig() 也会捞到聚合审计行——按标记精确取翻转行）。
    t_on = trig(on, "FR-WALL")
    flipped = [o for o in t_on if "[relaxed_disjoint_na]" in (o.notes or "")]
    assert flipped and (flipped[0].closure_status,
                        flipped[0].satisfaction_status) == (
        "closed", "not_applicable")
    # 翻转触发器聚合为 False ⇒ 主链产出「下游跳过」审计（下游传导在入口层可见）。
    assert any("action obligations skipped" in (o.notes or "") for o in t_on)
    # 放宽档标记全批只落在那一个 fragment 触发器上（楼级不翻的护栏由单元测试
    # test_relaxed_on_identity_unknown_keeps_conflict 盖住；本夹具楼级不产触发器行）。
    all_marked = [o for o in on.obligation_set.obligations
                  if "[relaxed_disjoint_na]" in (o.notes or "")]
    assert len(all_marked) == 1 and (all_marked[0].fragment_id or "") == "FR-WALL"


def test_relaxed_strict_path_has_no_relaxed_marker() -> None:
    """严档（授权恒等判据）命中时即便 flag 开，notes 也不得带放宽档标记——
    归因标记只许落在「放宽档才翻」的义务上，否则重放分账会虚高。"""
    o = evaluate_trigger(
        make_rule_card(),
        _slot_trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _empty_index(), META,
        auth_target="cantilevered_canopy",
        w0_identity="drainage_component",
        lattice_disjoint=_DISJOINT,
        ct_disjoint_na_relaxed=True,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "structurally_unsatisfiable_qualifier" in (o.notes or "")
    assert "[relaxed_disjoint_na]" not in (o.notes or "")
