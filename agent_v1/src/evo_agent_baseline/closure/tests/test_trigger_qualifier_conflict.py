"""触发路径 qualifier_conflict 分账对齐（DEBT-049 Phase 3 U1，spec §3 分账对齐）。

`evaluate_trigger` 补 qualifier_conflict 分支：候选事实存在 + required qualifier 全灭 +
非结构不相容 → blocked/qualifier_conflict（镜像 `evaluate_slot_role`:667-675），从
open/missing_fact 重归账。覆盖：
  1. 重归账语义（候选存在+qualifier 全灭 → blocked/qualifier_conflict）
  2. 双路径同语义（trigger 与 slot-role 同输入同 reason_code）
  3. 出口优先序（DEBT-050 结构 NA 先于 qualifier_conflict）
  4. 供给缺口护栏（真缺 → 仍 open；qualifier 相容/空 → 不误 block）
  5. 四组传播矩阵（aggregate 值 / 下游存在性·状态 / 计数迁移 / stop_reason 变化
     + allow_stop 恒 False→False 守恒断言）
  6. 阶段二配对路径一致（复用同一 evaluator，double-path 同结论）

真语料重归账半径口径（codex 019f73df 建议固化,防误拿其它 run 得 19/23/25）：
- 基准 run = agent_v1/experiments/baseline_e2e_smoke_20260713_082642/runs/CAR-20260712T222645-37d39526
  （rule_slice.json + fact_pack.json,只读重放,不连 Neo4j）,直接 trigger 半径 = 22
  （open/missing_fact → blocked/qualifier_conflict）。同日 188 个 run 半径分布 5-28,非恒 22。
- 重放口径：对该 run 的每卡跑 evaluate_trigger（当前代码）,数 reason 迁移条数。
"""

from __future__ import annotations

from evo_agent_baseline.closure import blueprint_deriver as B
from evo_agent_baseline.closure import blueprint_state_eval as S
from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    aggregate_trigger_logic,
    evaluate_slot_role,
    evaluate_trigger,
    make_rule_not_applicable_by_trigger,
    trigger_state,
)
from evo_agent_baseline.closure.validator import summarize

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
KNOWN = {"structural_component", "drainage_component"}

# 非结构限定符（不落 DEBT-050 component/location NA 分支）——用于纯 qualifier 冲突形态。
CONFLICT_SLOT = "defect.class.present"
_GUARD: dict = {}  # summarize guard_result（forbidden_source_check_passed 默认 True）


def _trigger(slot_id=CONFLICT_SLOT, qualifiers=None, expected=True,
             op="==", cid="trg01"):
    return {
        "condition_id": cid, "predicate_kind": "slot", "slot_id": slot_id,
        "operator": op, "expected_value": expected,
        "qualifiers": {"defect_class_key": "crack"} if qualifiers is None
        else qualifiers,
    }


def _idx(facts):
    return FactIndex(make_fact_pack(facts))


def _fact_mismatch():
    """候选事实存在于 slot，但带不同 qualifier（required 一个都不匹配）。"""
    return make_fact("f-conf", slot_id=CONFLICT_SLOT, value=True,
                     value_type="boolean",
                     qualifiers={"defect_class_key": "corrosion"})


# --------------------------------------------------------------------------- #
# 1. 重归账语义 + 双路径同语义
# --------------------------------------------------------------------------- #
def test_candidate_present_qualifier_all_miss_reattributes_blocked() -> None:
    """候选存在+qualifier 全灭+非结构不相容 → blocked/qualifier_conflict（从 open/missing_fact 重归账）。"""
    o = evaluate_trigger(make_rule_card(), _trigger(), _idx([_fact_mismatch()]), META)
    assert (o.closure_status, o.satisfaction_status) == ("blocked", "unknown")
    assert o.blocked_reason_code == "qualifier_conflict"
    assert o.open_reason_code is None


def test_trigger_and_slot_role_same_input_same_semantics() -> None:
    """同 slot+qualifier+index：trigger 与 slot_role 同记 blocked/qualifier_conflict（分账语义一致）。"""
    facts = [_fact_mismatch()]
    o_trig = evaluate_trigger(make_rule_card(), _trigger(), _idx(facts), META)
    slot_ref = {"slot_ref_id": "sr01", "slot_id": CONFLICT_SLOT, "role": "trigger",
                "qualifiers": {"defect_class_key": "crack"}, "required": True}
    o_role = evaluate_slot_role(make_rule_card(), slot_ref, _idx(facts), True, META)
    assert o_trig.closure_status == o_role.closure_status == "blocked"
    assert (o_trig.blocked_reason_code == o_role.blocked_reason_code
            == "qualifier_conflict")


# --------------------------------------------------------------------------- #
# 2. 出口优先序 + 供给缺口护栏
# --------------------------------------------------------------------------- #
def test_structural_na_precedes_qualifier_conflict() -> None:
    """候选存在 + 触发器授权目标叶型与 fragment 身份可证排斥 → 仍 closed/not_applicable。

    DEBT-065 结构 NA 出口在 qualifier_conflict 分支**之前**判定（出口优先序守恒）：
    此处 conflict 条件（候选非空+qualifier 全灭）亦成立，但结构 NA 先命中。
    """
    import itertools
    _leaf = ["external_wall", "fire_safety_component", "drainage_component",
             "cantilevered_canopy", "wall_tiles"]
    _disjoint = {frozenset(p) for p in itertools.combinations(_leaf, 2)}
    facts = [make_fact("f", slot_id=CONFLICT_SLOT, value=True, value_type="boolean",
                       qualifiers={"component_type_key": "drainage_component"})]
    o = evaluate_trigger(
        make_rule_card(),
        _trigger(qualifiers={"component_type_key": "cantilevered_canopy"}),
        _idx(facts), META,
        auth_target="cantilevered_canopy",
        w0_identity="drainage_component",
        lattice_disjoint=_disjoint,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
    assert "structurally_unsatisfiable_qualifier" in (o.notes or "")
    assert o.blocked_reason_code is None


def test_no_candidate_stays_open_missing_fact() -> None:
    """槽无候选事实（真缺）→ 仍 open/missing_fact，不误判 qualifier_conflict（护栏：仅候选存在时重归账）。"""
    o = evaluate_trigger(make_rule_card(), _trigger(), _idx([]), META)
    assert o.closure_status == "open" and o.open_reason_code == "missing_fact"
    assert o.blocked_reason_code is None


def test_empty_qualifier_candidate_present_not_reattributed() -> None:
    """trigger 无 qualifier（候选存在）→ 正常比较 closed/satisfied，不进 conflict 分支。"""
    o = evaluate_trigger(
        make_rule_card(), _trigger(qualifiers={}),
        _idx([make_fact("f", slot_id=CONFLICT_SLOT, value=True,
                        value_type="boolean")]), META)
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_matching_qualifier_closes_satisfied() -> None:
    """候选带 matching qualifier → 正常求值 closed/satisfied（不误 block）。"""
    facts = [make_fact("f", slot_id=CONFLICT_SLOT, value=True, value_type="boolean",
                       qualifiers={"defect_class_key": "crack"})]
    o = evaluate_trigger(make_rule_card(), _trigger(), _idx(facts), META)
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


# --------------------------------------------------------------------------- #
# 3. 四组传播矩阵 —— 改动前后 cohort 状态构造器
# --------------------------------------------------------------------------- #
def _open_trigger():
    """改前形态：候选存在+qualifier 全灭在旧语义下落 open/missing_fact——此处用真缺复现 open 态。"""
    return evaluate_trigger(make_rule_card(), _trigger(cid="chg"), _idx([]), META)


def _blocked_trigger():
    """改后形态：候选存在+qualifier 全灭 → blocked/qualifier_conflict。"""
    return evaluate_trigger(make_rule_card(), _trigger(cid="chg"),
                            _idx([_fact_mismatch()]), META)


def _false_trigger():
    """另一 trigger=False（closed/not_applicable）。"""
    return evaluate_trigger(
        make_rule_card(), _trigger(slot_id="slot.other", qualifiers={}, cid="oth"),
        _idx([make_fact("f", slot_id="slot.other", value=False,
                        value_type="boolean")]), META)


def _true_trigger():
    """另一 trigger=True（closed/satisfied）。"""
    return evaluate_trigger(
        make_rule_card(), _trigger(slot_id="slot.other", qualifiers={}, cid="oth"),
        _idx([make_fact("f", slot_id="slot.other", value=True,
                        value_type="boolean")]), META)


def _downstream(trigger_active):
    """缺事实的下游 required slot role（继承 card-level trigger 聚合态）。"""
    sr = {"slot_ref_id": "d1", "slot_id": "downstream.slot", "role": "prerequisite",
          "qualifiers": {}, "required": True}
    return evaluate_slot_role(make_rule_card(), sr, _idx([]), trigger_active, META)


def test_cohort_state_constructors_sane() -> None:
    """cohort 四态构造器四态正确（矩阵前置）。"""
    assert trigger_state(_open_trigger()) == "open"
    assert trigger_state(_blocked_trigger()) == "blocked"
    assert trigger_state(_false_trigger()) is False
    assert trigger_state(_true_trigger()) is True


def test_matrix_all_false_aggregate_open_to_blocked() -> None:
    """①②组 logic=all + 另一 trigger False：aggregate 改前 [False,open]→False；改后 [False,blocked]→blocked。"""
    before = aggregate_trigger_logic("all", [_false_trigger(), _open_trigger()])
    after = aggregate_trigger_logic("all", [_false_trigger(), _blocked_trigger()])
    assert before is False
    assert after == "blocked"


def test_matrix_any_true_aggregate_active_to_blocked() -> None:
    """③④组 logic=any + 另一 trigger True：aggregate 改前 [True,open]→True(active)；改后 [True,blocked]→blocked（blocked 短路优先于 any）。"""
    before = aggregate_trigger_logic("any", [_true_trigger(), _open_trigger()])
    after = aggregate_trigger_logic("any", [_true_trigger(), _blocked_trigger()])
    assert before is True
    assert after == "blocked"


def test_matrix_downstream_active_to_blocked_inheritance() -> None:
    """③→④ 下游义务：卡级 True(active) 下正常求值(open/missing_fact) → blocked 下继承 blocked/missing_rule_edge。"""
    d_active = _downstream(True)
    d_blocked = _downstream("blocked")
    assert d_active.closure_status == "open" and d_active.open_reason_code == "missing_fact"
    assert not d_active.depends_on_open_trigger
    assert (d_blocked.closure_status == "blocked"
            and d_blocked.blocked_reason_code == "missing_rule_edge")


def test_matrix_downstream_open_aggregate_depends_on_open() -> None:
    """卡级 aggregate=open 时下游继承 open/depends_on_open_trigger（继承分支覆盖）。"""
    d = _downstream("open")
    assert d.closure_status == "open" and d.depends_on_open_trigger
    assert d.open_reason_code == "depends_on_open_trigger"


def test_matrix_allow_stop_invariant_false_to_false() -> None:
    """四组 allow_stop 守恒断言：改前改后恒 False→False（直接 trigger 自身两态均非 satisfied）。"""
    s_all_before = summarize(
        [_false_trigger(), _open_trigger(),
         make_rule_not_applicable_by_trigger(make_rule_card(), [], META)], _GUARD)
    s_all_after = summarize([_false_trigger(), _blocked_trigger()], _GUARD)
    s_any_before = summarize(
        [_true_trigger(), _open_trigger(), _downstream(True)], _GUARD)
    s_any_after = summarize(
        [_true_trigger(), _blocked_trigger(), _downstream("blocked")], _GUARD)
    for s in (s_all_before, s_all_after, s_any_before, s_any_after):
        assert s.allow_stop is False
    # stop_reason 从 open 型 → blocked 型（open==0 后 blocked 型上位）。
    assert s_all_before.stop_reason == "open_obligations_remain"
    assert s_all_after.stop_reason == "blocked_obligations_remain"
    assert s_any_before.stop_reason == "open_obligations_remain"
    assert s_any_after.stop_reason == "blocked_obligations_remain"


def test_matrix_counts_migration_open_minus1_blocked_plus1() -> None:
    """直接 cohort 内计数迁移守恒：open −1 / blocked +1（qualifier_conflict 新增量 == open→blocked 迁移量）。"""
    before = summarize([_false_trigger(), _open_trigger()], _GUARD)
    after = summarize([_false_trigger(), _blocked_trigger()], _GUARD)
    assert after.open_count == before.open_count - 1
    assert after.blocked_count == before.blocked_count + 1
    assert before.open_reason_counts.get("missing_fact", 0) == 1
    assert after.blocked_reason_counts.get("qualifier_conflict", 0) == 1
    assert after.open_reason_counts.get("missing_fact", 0) == 0


# --------------------------------------------------------------------------- #
# 4. 阶段二配对路径一致（double-path：复用同一 evaluator）
# --------------------------------------------------------------------------- #
def test_phase2_paired_path_qualifier_conflict_equivalence() -> None:
    """双路径一致：阶段二配对路径（blueprint_state_eval 复用同一 evaluate_trigger）对 qualifier_conflict 与 v1 活路径同结论。"""
    card = make_rule_card("rc.qc", slot_role_map=[
        {"slot_ref_id": "sr1", "slot_id": CONFLICT_SLOT, "roles": ["trigger"],
         "required": False, "qualifiers": {"defect_class_key": "crack"}},
    ])
    tr = {"condition_id": "c1", "predicate_kind": "slot", "operator": "==",
          "expected_value": True, "slot_ref_id": "sr1"}
    fi = _idx([_fact_mismatch()])
    o = evaluate_trigger(card, dict(tr), fi, META)
    assert o.closure_status == "blocked" and o.blocked_reason_code == "qualifier_conflict"
    bp = B.build_trigger_blueprint(card, dict(tr), META)
    v2 = S.assemble_obligation_v2(bp, o)
    # 阶段二 state 投影须与 v1 判定字节一致。
    assert v2.state.closure_status == "blocked"
    assert v2.state.blocked_reason_code == "qualifier_conflict"
    assert v2.state.open_reason_code is None
