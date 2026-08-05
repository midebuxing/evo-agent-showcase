"""DEBT-083 哨兵边界（codex 裁决分叉一「甲」＋新增方案「丁」，2026-08-02）。

甲（非判定事实分类器，三条件全满足才算非判定）：
  1. `derived_outcome_group` ∈ {risk_flags, repair_flags, verification_flags,
     assessment_flags} 且值 == "not_applicable"；
  2. 同 carrier_id 同 slot_id 有 fallback_reasons 伴随行；
  3. 伴随行原因码 ∈ 冻结集合（规格 06 §11 + 三方对账表 §4）。
消费面（触发器/槽角色/证物/节点绑定）：非判定 → closed + not_applicable 带
`non_adjudicative_sentinel: reason=<码>`；裸哨兵 → blocked +
schema_contract_violation 带 `bare_sentinel_without_fallback_companion`。

丁（消灭双轨求值）：roles 含 "trigger" 且 slot_ref_id 被 trigger_conditions
引用的槽角色义务镜像同 (卡, slot_ref_id, 作用域) 真触发器结果。

全部挂既有开关 `exclude_fallback_reasons_facts`（FactIndex 侧 `exclude_explanatory`），
缺省 False＝行为逐位不变。变异面（裁决点名三类）：①伴随行 ②开关常开 ③同字符串
合法枚举不得被全局字符串规则误杀（本文件测试 3 钉住）。
"""
from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    evaluate_evidence_requirement,
    evaluate_slot_role,
    evaluate_trigger,
)

from .fixtures import (
    jval,
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
SLOT_HEALTH = "risk.public_health.emergency"
SLOT_REPAIR_SAFE = "repair.outcome.safe_until_next_cycle"
SLOT_DEFICIENCY = "deficiency_class"
SLOT_DANGER = "risk.public_danger.present"

COND = "COND-01"


def _sentinel(fact_id="F-sen-01", slot=SLOT_HEALTH, group="risk_flags",
              carrier=COND):
    """哨兵行：判定四组之一 + 值 "not_applicable"。"""
    return make_fact(
        fact_id, slot_id=slot, value="not_applicable", value_type="string",
        carrier_type="condition", carrier_id=carrier,
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": group},
    )


def _companion(reason="no_drainage", fact_id="F-fb-01", slot=SLOT_HEALTH,
               carrier=COND):
    """伴随行：fallback_reasons 组，值即原因码（同 carrier 同 slot）。"""
    return make_fact(
        fact_id, slot_id=slot, value=reason, value_type="string",
        carrier_type="condition", carrier_id=carrier,
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": "fallback_reasons"},
    )


def _bool_flag(value=True, fact_id="F-bool-01", slot=SLOT_DANGER,
               group="risk_flags", carrier=COND):
    return make_fact(
        fact_id, slot_id=slot, value=value, value_type="boolean",
        carrier_type="condition", carrier_id=carrier,
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": group},
    )


def _slot_ref(slot=SLOT_HEALTH, ref_id="sr01", roles=("trigger",)):
    return {
        "slot_ref_id": ref_id, "slot_id": slot, "roles": list(roles),
        "required": True, "qualifiers": {},
    }


def _trigger_item(slot=SLOT_HEALTH, ref_id="sr01", cond_id="c01", expected=True):
    # 真卡契约（TriggerConditionsDTO extra=forbid）：item 只经 slot_ref_id 引用
    # slot_role_map 解析 slot_id，不许直写 slot_id。
    return {
        "condition_id": cond_id, "predicate_kind": "slot",
        "slot_ref_id": ref_id,
        "operator": "==", "expected_value": expected, "qualifiers": {},
    }


def _card_with_trigger(slot=SLOT_HEALTH, expected=True):
    return make_rule_card(
        slot_role_map=[_slot_ref(slot)],
        trigger_conditions={"logic": "all", "items": [_trigger_item(slot, expected=expected)]},
    )


def _index_on(facts):
    return FactIndex(make_fact_pack(facts), exclude_explanatory=True)


# --------------------------------------------------------------------- #
# 测试 1：哨兵+伴随（原因在集合）→ 触发器/槽角色/证物 NA 带原因 notes
# --------------------------------------------------------------------- #
def test_sentinel_with_companion_trigger_na() -> None:
    obl = evaluate_trigger(
        _card_with_trigger(), _trigger_item(),
        _index_on([_sentinel(), _companion()]), META)
    assert (obl.closure_status, obl.satisfaction_status) == (
        "closed", "not_applicable")
    assert obl.comparator_result is False          # 同现有结构 NA 形态
    assert "non_adjudicative_sentinel: reason=no_drainage" in obl.notes
    assert obl.evidence_fact_ids == ["F-sen-01"]


def test_sentinel_with_companion_slot_role_na() -> None:
    card = _card_with_trigger()
    obl = evaluate_slot_role(
        card, _slot_ref(), _index_on([_sentinel(), _companion()]), True, META)
    assert (obl.closure_status, obl.satisfaction_status) == (
        "closed", "not_applicable")
    assert "non_adjudicative_sentinel: reason=no_drainage" in obl.notes


def test_form_b_repair_safe_evidence_na_and_boolean_untouched() -> None:
    """形态 B 专条（裁决分叉二本批部分）：36 条
    `repair.outcome.safe_until_next_cycle` 证物经分类器自然落 NA（无需单独代码）；
    存量 true/false 布尔证物语义一律不动。"""
    card = make_rule_card()
    req = {"evidence_requirement_id": "er01", "slot_ids": [SLOT_REPAIR_SAFE],
           "required": True}
    # 哨兵（伴随 no_repair）→ NA。
    obl = evaluate_evidence_requirement(
        card, "for_matching", dict(req),
        _index_on([
            _sentinel(slot=SLOT_REPAIR_SAFE, group="repair_flags"),
            _companion("no_repair", slot=SLOT_REPAIR_SAFE),
        ]), True, META)
    assert (obl.closure_status, obl.satisfaction_status) == (
        "closed", "not_applicable")
    assert "non_adjudicative_sentinel: reason=no_repair" in obl.notes
    # 存量布尔 false → violated（现状语义不动）、true → satisfied。
    obl_false = evaluate_evidence_requirement(
        card, "for_matching", dict(req),
        _index_on([_bool_flag(False, slot=SLOT_REPAIR_SAFE, group="repair_flags")]),
        True, META)
    assert (obl_false.closure_status, obl_false.satisfaction_status) == (
        "closed", "violated")
    obl_true = evaluate_evidence_requirement(
        card, "for_matching", dict(req),
        _index_on([_bool_flag(True, fact_id="F-bool-02", slot=SLOT_REPAIR_SAFE,
                              group="repair_flags")]),
        True, META)
    assert (obl_true.closure_status, obl_true.satisfaction_status) == (
        "closed", "satisfied")


# --------------------------------------------------------------------- #
# 测试 2：裸哨兵 → blocked + schema_contract_violation（不许猜成不适用）
# --------------------------------------------------------------------- #
def test_bare_sentinel_without_companion_blocked() -> None:
    obl = evaluate_trigger(
        _card_with_trigger(), _trigger_item(),
        _index_on([_sentinel()]), META)
    assert (obl.closure_status, obl.blocked_reason_code) == (
        "blocked", "schema_contract_violation")
    assert "bare_sentinel_without_fallback_companion" in obl.notes


def test_bare_sentinel_companion_on_other_carrier_blocked() -> None:
    """条件 2 的「同载体同槽」钉住：伴随行在别的 carrier 上 = 无伴随行。"""
    obl = evaluate_trigger(
        _card_with_trigger(), _trigger_item(),
        _index_on([_sentinel(), _companion(carrier="COND-99")]), META)
    assert (obl.closure_status, obl.blocked_reason_code) == (
        "blocked", "schema_contract_violation")
    assert "bare_sentinel_without_fallback_companion" in obl.notes


def test_bare_sentinel_slot_role_blocked() -> None:
    obl = evaluate_slot_role(
        _card_with_trigger(), _slot_ref(),
        _index_on([_sentinel()]), True, META)
    assert (obl.closure_status, obl.blocked_reason_code) == (
        "blocked", "schema_contract_violation")
    assert "bare_sentinel_without_fallback_companion" in obl.notes


# --------------------------------------------------------------------- #
# 测试 3：同字符串但 derived_outcome_group 不在四组 → 不受影响
# （钉住「禁全局字符串黑名单」：邻接通道 deficiency_class 形态不得误杀）
# --------------------------------------------------------------------- #
def test_same_string_outside_four_groups_unaffected() -> None:
    fact = make_fact(
        "F-def-01", slot_id=SLOT_DEFICIENCY, value="not_applicable",
        value_type="string", carrier_type="condition", carrier_id=COND,
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": "fire_state_fields"},
    )
    card = _card_with_trigger(SLOT_DEFICIENCY, expected="not_applicable")
    obl = evaluate_trigger(
        card, _trigger_item(SLOT_DEFICIENCY, expected="not_applicable"),
        _index_on([fact]), META)
    # 正常比较通道："not_applicable" == "not_applicable" → satisfied，
    # 既不被判 NA 也不被判裸哨兵。
    assert (obl.closure_status, obl.satisfaction_status) == (
        "closed", "satisfied")
    assert "non_adjudicative_sentinel" not in obl.notes
    assert "bare_sentinel" not in obl.notes


# --------------------------------------------------------------------- #
# 测试 4：原因码不在冻结集合 → 按裸哨兵处理
# --------------------------------------------------------------------- #
def test_reason_code_outside_frozen_set_treated_as_bare() -> None:
    obl = evaluate_trigger(
        _card_with_trigger(), _trigger_item(),
        _index_on([_sentinel(), _companion("no_condition")]), META)
    assert (obl.closure_status, obl.blocked_reason_code) == (
        "blocked", "schema_contract_violation")
    assert "bare_sentinel_without_fallback_companion" in obl.notes


# --------------------------------------------------------------------- #
# 测试 5（丁）：同 slot_ref 真触发器判 NA 时槽角色义务必须同判；
# 真触发器判 satisfied 时槽角色义务镜像 satisfied
# --------------------------------------------------------------------- #
def _dual_track_card():
    return make_rule_card(
        "RC.sentinel.dual",
        slot_role_map=[
            _slot_ref(SLOT_HEALTH, "sr01"),
            _slot_ref(SLOT_DANGER, "sr02"),
        ],
        # logic=any：c02 satisfied 撑起聚合 True，槽角色才会被求值——
        # 正是双轨产 satisfied 副本的结构条件。
        trigger_conditions={"logic": "any", "items": [
            _trigger_item(SLOT_HEALTH, "sr01", "c01", expected=True),
            _trigger_item(SLOT_DANGER, "sr02", "c02", expected=True),
        ]},
    )


def _dual_track_facts():
    return [
        _sentinel(), _companion(),                 # sr01：哨兵+伴随 → 触发器 NA
        _bool_flag(True, slot=SLOT_DANGER),        # sr02：干净 true → satisfied
    ]


def test_dual_track_slot_role_mirrors_trigger_na() -> None:
    result = run_closure(
        make_rule_slice([_dual_track_card()]),
        make_fact_pack(_dual_track_facts()),
        exclude_fallback_reasons_facts=True,
    )
    obls = result.obligation_set.obligations
    sr01 = [o for o in obls if o.slot_ref_ids == ["sr01"]]
    # 真触发器义务 + 槽角色义务各一，**不许再出 satisfied 副本**。
    assert len(sr01) == 2
    assert all(o.closure_status == "closed" for o in sr01)
    assert all(o.satisfaction_status == "not_applicable" for o in sr01)
    assert not any(o.satisfaction_status == "satisfied"
                   for o in obls if SLOT_HEALTH in o.slot_ids)
    # 镜像证据：槽角色副本自身求值从不写 operator/expected_value_json，
    # 只有镜像真触发器结果才会带上。
    assert all(o.operator == "==" for o in sr01)
    assert all(o.comparator_result is False for o in sr01)
    assert any("non_adjudicative_sentinel: reason=no_drainage" in o.notes
               for o in sr01)


def test_dual_track_slot_role_mirrors_trigger_satisfied() -> None:
    result = run_closure(
        make_rule_slice([_dual_track_card()]),
        make_fact_pack(_dual_track_facts()),
        exclude_fallback_reasons_facts=True,
    )
    obls = result.obligation_set.obligations
    sr02 = [o for o in obls if o.slot_ref_ids == ["sr02"]]
    assert len(sr02) == 2
    assert all((o.closure_status, o.satisfaction_status)
               == ("closed", "satisfied") for o in sr02)
    assert all(o.operator == "==" for o in sr02)
    assert all(o.expected_value_json == jval(True) for o in sr02)
    assert all(o.comparator_result is True for o in sr02)
    # 丁护栏②（codex 终审）：镜像副本必须携来源触发器引用（slot_ref 键——
    # 义务号去重时会重算，不可作引用键），报告层据此折叠/标「一致性副本」。
    mirrors = [o for o in sr02 if "consistency_mirror_of=" in (o.notes or "")]
    assert len(mirrors) == 1
    ref = mirrors[0].notes.split("consistency_mirror_of=")[1].split(";")[0].strip()
    assert ref == "trigger_slot_ref:sr02"
    originals = [o for o in sr02
                 if o is not mirrors[0] and o.kind == "trigger"]
    assert originals and originals[0].satisfaction_status == "satisfied"


def test_dual_track_multi_trigger_ref_blocks_mirror() -> None:
    """丁护栏①（codex 终审）：同 slot_ref_id 被多个触发项引用 → 镜像显式阻断
    （blocked/schema_contract_violation + dual_track_multi_trigger_ref），
    绝不静默取 condition_id 排序后的第一个。"""
    card = make_rule_card(
        slot_role_map=[_slot_ref(SLOT_DANGER, ref_id="sr01")],
        # 两个触发项引用同一 slot_ref（期望都为 True——保证聚合为 True、
        # 槽角色循环真的会跑；expected 不同会把聚合杀成 False 使本测试空转）。
        trigger_conditions={"logic": "all", "items": [
            _trigger_item(SLOT_DANGER, ref_id="sr01", cond_id="c01", expected=True),
            _trigger_item(SLOT_DANGER, ref_id="sr01", cond_id="c02", expected=True),
        ]},
    )
    result = run_closure(
        make_rule_slice([card]),
        make_fact_pack([_bool_flag(True)]),
        exclude_fallback_reasons_facts=True,
    )
    obls = result.obligation_set.obligations
    blocked = [o for o in obls
               if "dual_track_multi_trigger_ref" in (o.notes or "")]
    assert blocked, [(o.kind, o.notes) for o in obls if o.slot_ref_ids == ["sr01"]]
    assert all(
        (o.closure_status, o.blocked_reason_code)
        == ("blocked", "schema_contract_violation")
        for o in blocked
    )
    # 且没有任何镜像副本从多义 ref 上产出
    assert not any("consistency_mirror_of=" in (o.notes or "") for o in obls)


# --------------------------------------------------------------------- #
# 测试 6：开关缺省关闭 → 以上全部输入下行为与现状逐位相同
# --------------------------------------------------------------------- #
def test_action_node_all_sentinel_bindings_merge_na() -> None:
    """第五漏网口（2026-08-02 第三门层 2 抓出 18 条后补）：action 节点的满足绑定
    全部是哨兵 NA 时，合并不得按「非违反即满足」判 satisfied——须 closed +
    not_applicable 并继承哨兵标记。开关关闭时旧行为不变（同输入 ambiguous 阻塞）。"""
    node = {"obligation_node_id": "n01", "node_kind": "obligation",
            "actor": "ri", "action": "repair_outcome_check",
            "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
            "trigger_condition_ids": []}
    card = make_rule_card(
        slot_role_map=[_slot_ref(SLOT_REPAIR_SAFE, ref_id="sr-ev",
                                 roles=("evidence",))],
        obligation_graph={"nodes": [node], "edges": []},
    )
    facts = [
        _sentinel(slot=SLOT_REPAIR_SAFE, group="repair_flags"),
        _companion(reason="no_repair", slot=SLOT_REPAIR_SAFE),
    ]

    from evo_agent_baseline.closure.obligation_deriver import (
        evaluate_obligation_node,
    )
    idx_on = FactIndex(make_fact_pack(facts), exclude_explanatory=True)
    actions_on = evaluate_obligation_node(card, node, idx_on, True, META)
    assert any(
        (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")
        and "non_adjudicative_sentinel" in (o.notes or "")
        for o in actions_on
    ), [(o.kind, o.closure_status, o.satisfaction_status, o.notes)
        for o in actions_on]
    # 哨兵下绝不许出现 satisfied
    assert not any(o.satisfaction_status == "satisfied" for o in actions_on)

    # 开关关：同输入不产 satisfied 也不产 NA（两行异值 → ambiguous 阻塞，旧行为）
    idx_off = FactIndex(make_fact_pack(facts))
    actions_off = evaluate_obligation_node(card, node, idx_off, True, META)
    assert not any(o.satisfaction_status == "satisfied" for o in actions_off)
    assert not any(
        "non_adjudicative_sentinel" in (o.notes or "") for o in actions_off)


def test_default_off_trigger_slot_role_evidence_unchanged() -> None:
    facts = [_sentinel(), _companion()]
    idx = FactIndex(make_fact_pack(facts))        # 缺省 = 关
    # 现状：fallback 行留在判定索引 → 同槽异值 → ambiguous。
    trig = evaluate_trigger(_card_with_trigger(), _trigger_item(), idx, META)
    assert (trig.closure_status, trig.blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
    role = evaluate_slot_role(_card_with_trigger(), _slot_ref(), idx, True, META)
    assert (role.closure_status, role.blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
    ev = evaluate_evidence_requirement(
        make_rule_card(), "for_matching",
        {"evidence_requirement_id": "er01", "slot_ids": [SLOT_HEALTH],
         "required": True},
        idx, True, META)
    assert (ev.closure_status, ev.blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
    for o in (trig, role, ev):
        assert "non_adjudicative_sentinel" not in o.notes
        assert "bare_sentinel" not in o.notes


def test_default_off_bare_sentinel_unchanged() -> None:
    """缺省关：裸哨兵走原比较路径（"not_applicable" == True → False → NA），
    不产 schema_contract_violation、不带哨兵 notes。"""
    obl = evaluate_trigger(
        _card_with_trigger(), _trigger_item(),
        FactIndex(make_fact_pack([_sentinel()])), META)
    assert (obl.closure_status, obl.satisfaction_status) == (
        "closed", "not_applicable")
    assert obl.comparator_result is False
    assert "non_adjudicative_sentinel" not in obl.notes
    assert "bare_sentinel" not in obl.notes


def test_default_off_dual_track_unchanged() -> None:
    """缺省关：无双轨复用——c01 同槽异值 ambiguous → 聚合 blocked →
    槽角色走继承（missing_rule_edge），无镜像字段、无哨兵 notes。"""
    result = run_closure(
        make_rule_slice([_dual_track_card()]),
        make_fact_pack(_dual_track_facts()),
    )
    obls = result.obligation_set.obligations
    sr01 = [o for o in obls if o.slot_ref_ids == ["sr01"]]
    assert len(sr01) == 2
    trig_obl = [o for o in sr01 if o.operator == "=="]
    role_obl = [o for o in sr01 if o.operator is None]
    assert len(trig_obl) == 1 and len(role_obl) == 1
    assert (trig_obl[0].closure_status, trig_obl[0].blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
    assert (role_obl[0].closure_status, role_obl[0].blocked_reason_code) == (
        "blocked", "missing_rule_edge")
    for o in obls:
        assert "non_adjudicative_sentinel" not in o.notes
        assert "dual_track_reuse_miss" not in o.notes
