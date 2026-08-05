# -*- coding: utf-8 -*-
"""DEBT-083 第 5 步：逐槽授权作用域选择（缺省关闭）。

面：①缺省关闭逐位等价（授权槽照旧 ambiguous——1,538 病灶原样）；
②开启后授权槽绑楼级聚合行、ambiguous→consistent，审计注记带所选事实编号；
③开启后**登记外**的槽行为不变（逐槽授权不是通用规则——决策门分叉一）；
④开启后授权槽若无聚合行（只有互异部位行）仍 ambiguous（分级不造数据）。
"""
from __future__ import annotations

from evo_agent_baseline.closure.obligation_deriver import (
    SCOPE_SELECTION_AUTHORIZED_SLOTS,
    evaluate_slot_role,
)
from evo_agent_baseline.closure.fact_binding import FactIndex
from .fixtures import BUILDING_ID, make_fact, make_fact_pack, make_rule_card

SLOT = "procedure.repair.prescribed.started"      # 授权槽（任一真）
UNAUTH = "procedure.appointment.completed"        # 登记外流程槽

META = {"run_id": "R", "world_id": "W", "building_id": BUILDING_ID}


def _slot_ref(slot):
    return {"slot_ref_id": "RC.t.c01.sr01", "slot_id": slot,
            "roles": ["evidence"], "required": True, "qualifiers": {}}


def _mixed_rows(slot):
    """楼级聚合行 1 条 + 互异部位行 2 条（1,538 病灶的最小再现）。"""
    return [
        make_fact("f-agg", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="building", carrier_id=BUILDING_ID),
        make_fact("f-p1", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1"),
        make_fact("f-p2", slot_id=slot, value=False, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-2"),
    ]


def _patch_gates(monkeypatch, card, *, slots, with_binding=True):
    """S1 三重门测试补丁：粗门槽＋槽位角色精确绑定（权威表派生视图）。
    with_binding 时同步补 SCOPE_PRECISE（S3 通用层按它判"已登记"）。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    key = (card.rule_card_id, "RC.t.c01.sr01")
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset(slots))
    monkeypatch.setattr(
        od, "SLOT_ROLE_AUTHORIZED_BINDINGS",
        frozenset({key}) if with_binding else frozenset())
    if with_binding:
        monkeypatch.setattr(
            od, "SCOPE_PRECISE_AUTHORIZED",
            {key: {"policy": "value_consumption",
                   "aggregation_source": "building_reading_aggregation"}})


def _eval(slot, facts, *, enabled, monkeypatch=None, with_binding=True):
    idx = FactIndex(make_fact_pack(facts))
    card = make_rule_card()
    if monkeypatch is not None:
        _patch_gates(monkeypatch, card, slots={slot}, with_binding=with_binding)
    return evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                              authorized_scope_selection=enabled)


def test_registry_is_exactly_two_slots():
    assert SCOPE_SELECTION_AUTHORIZED_SLOTS == {
        "procedure.repair.prescribed.started",
        "procedure.inspection.prescribed.completed",
    }


def test_default_off_stays_ambiguous():
    obl = _eval(SLOT, _mixed_rows(SLOT), enabled=False)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"
    assert "authorized_scope_selection" not in str(obl.notes or "")


def test_enabled_binds_building_aggregate(monkeypatch):
    obl = _eval(SLOT, _mixed_rows(SLOT), enabled=True, monkeypatch=monkeypatch)
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == "satisfied"
    assert obl.evidence_fact_ids == ["f-agg"]
    assert obl.observed_value_json == "true"
    notes = str(obl.notes or "")
    assert "authorized_scope_selection: selected=f-agg" in notes
    assert "excluded_by_scope=2" in notes


def test_enabled_does_not_touch_unauthorized_slot(monkeypatch):
    """粗门外的槽即使开启也保持 ambiguous——逐槽授权不是通用规则。
    （补丁只给 SLOT 开门，UNAUTH 槽在粗门外。）"""
    import evo_agent_baseline.closure.obligation_deriver as od
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset({SLOT}))
    obl = _eval(UNAUTH, _mixed_rows(UNAUTH), enabled=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"
    assert "authorized_scope_selection" not in str(obl.notes or "")


def test_enabled_without_aggregate_row_stays_ambiguous(monkeypatch):
    """无聚合行时分级选不出唯一读数——保持 ambiguous，不造数据。"""
    rows = [f for f in _mixed_rows(SLOT) if f.fact_id != "f-agg"]
    obl = _eval(SLOT, rows, enabled=True, monkeypatch=monkeypatch)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"


def test_enabled_but_binding_not_registered_stays_off(monkeypatch):
    """三重门：槽在粗门内但精确绑定不在登记 ⇒ 不启用（防未裁绑定放开）。"""
    obl = _eval(SLOT, _mixed_rows(SLOT), enabled=True,
                monkeypatch=monkeypatch, with_binding=False)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"


# ---- A′裁决：绑定级值消费授权（2026-08-02 决策门；审核门收窄版）----

def _agg_fact(slot, value, *, marked=True, value_type="boolean", fid="f-agg"):
    quals = {"aggregation": "building"} if marked else {}
    return make_fact(fid, slot_id=slot, value=value, value_type=value_type,
                     carrier_type="building", carrier_id=BUILDING_ID,
                     qualifiers=quals)


def _mixed_rows_value(slot, agg_value, **agg_kw):
    rows = _mixed_rows(slot)
    rows[0] = _agg_fact(slot, agg_value, **agg_kw)
    return rows


def _eval_value_authorized(monkeypatch, agg_value, *, registered=True,
                           rows=None, **agg_kw):
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    if registered:
        monkeypatch.setattr(
            od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS",
            frozenset({(card.rule_card_id, "RC.t.c01.sr01")}))
    slot = "procedure.inspection.prescribed.completed"
    _patch_gates(monkeypatch, card, slots={slot})
    if rows is None:
        rows = _mixed_rows_value(slot, agg_value, **agg_kw)
    idx = FactIndex(make_fact_pack(rows))
    return evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                              authorized_scope_selection=True)


def test_value_authorized_false_goes_open_not_satisfied(monkeypatch):
    """门③拦下的形状：聚合值假不得判 satisfied——A′裁 open+新码，绝无 violated。"""
    obl = _eval_value_authorized(monkeypatch, False)
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "observed_false_without_violation_basis"
    assert obl.evidence_fact_ids == ["f-agg"]
    assert obl.observed_value_json == "false"
    assert "程序不判违反" in str(obl.notes or "")


def test_value_authorized_true_stays_satisfied(monkeypatch):
    obl = _eval_value_authorized(monkeypatch, True)
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == "satisfied"


def test_unregistered_binding_hits_aggregate_guard(monkeypatch):
    """S3 甲′通用层（取代旧"维持现状"预期）：登记外绑定消费**带标记楼级聚合行**
    不得产实判 → open+binding_requires_adjudication_authorization。
    （"存量 400 布尔证物不整体翻转"不受影响——那些是无标记的部位产物行，
    通用层只看 aggregation=building 标记。）"""
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    # 通用层射程已收窄到 S3 裁定边界（遮蔽目标集合）——用射程内槽测。
    slot = "supervision.record.completed"
    _patch_gates(monkeypatch, card, slots={slot})          # 开粗门＋slot_role
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {})  # 未登记
    idx = FactIndex(make_fact_pack(_mixed_rows_value(slot, False)))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "unauthorized_aggregate_guard" in str(obl.notes or "")


def test_guard_catches_agg_row_not_first(monkeypatch):
    """边界单首轮否决形状②：楼级标记行**不在首位**时护栏仍须拦
    （首版只查 `bound[0]`，与裁决原文"任一楼级聚合读数"不符）。

    🔴 **本测试直接调 `_unauthorized_aggregate_guard`、手搓 bound**，不走
    `evaluate_slot_role`——经求值链构造的版本测不出差异（变异不转红）。

    ⚠️ **定性边界（二轮审核门纠正，别再写强了）**：观测是
    「批 I **前 5 栋**、探针挂护栏入口：调用 7,074 次，无聚合行 6,982／
    单行即聚合行 92／**多行且聚合行非首位 0 次**」。
    这只证明**该样本内零行为差异**，**证不了"当前求值链结构上不可达"**
    ——未授权绑定的 `_use_scope` 为假时不一定先经作用域塌缩。
    故 any-row 的正确定性是：**「按裁决原文（"任一楼级聚合读数"）对齐的
    防御性硬化，且在已观测样本上零行为差异」**，不是"修好了正在漏的口"，
    也不是"结构不可能"。本测试锁的是防御语义本身（变异转红已验）。
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    slot = "supervision.record.completed"
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {})
    bound = [
        make_fact("p1", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1"),
        make_fact("p2", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-2"),
        _agg_fact(slot, True, fid="f-agg-last"),
    ]
    obl = od._unauthorized_aggregate_guard(
        card, META, "evidence", {"notes": ""}, bound,
        enabled=True, binding_key=(card.rule_card_id, "RC.t.c01.sr01"))
    assert obl is not None, "聚合行非首位时护栏必须拦（any-row 语义）"
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "unauthorized_aggregate_guard" in str(obl.notes or "")


def test_guard_passes_when_no_agg_row_anywhere(monkeypatch):
    """对照：整个绑定集合都无楼级标记 ⇒ 护栏放行（不得误伤纯部位行绑定）。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    slot = "supervision.record.completed"
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {})
    bound = [
        make_fact("p1", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1"),
        make_fact("p2", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-2"),
    ]
    assert od._unauthorized_aggregate_guard(
        card, META, "evidence", {"notes": ""}, bound,
        enabled=True, binding_key=(card.rule_card_id, "RC.t.c01.sr01")) is None


def test_real_trigger_is_not_exempt_from_aggregate_guard(monkeypatch):
    """🔴 二轮审核门纠正的边界：**真触发器不豁免**。

    首版按 `kind == "trigger"` 整类豁免，理由是"转 open 会扰动 allow_stop"
    ——该理由被驳回且驳得对：**会扰动 allow_stop 恰恰证明它有判定后果**，
    不构成豁免。真正参与卡激活的触发器若消费楼级聚合读数而无合同，
    整类豁免会让它逃过合同检查。
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    slot = "supervision.record.completed"
    _patch_gates(monkeypatch, card, slots={slot})
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {})
    ref = dict(_slot_ref(slot), roles=["trigger"])
    idx = FactIndex(make_fact_pack([_agg_fact(slot, True)]))
    obl = evaluate_slot_role(card, ref, idx, True, META,
                             authorized_scope_selection=True,
                             is_consistency_mirror=False)
    assert obl.kind == "trigger"
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "unauthorized_aggregate_guard" in str(obl.notes or "")


def test_consistency_mirror_is_exempt_from_aggregate_guard(monkeypatch):
    """对照：**一致性镜像副本**豁免——它不是独立法规判断，而是复用真触发器
    的求值结果（validator 求值后覆盖状态并写 `consistency_mirror_of=`），
    对它再独立裁定一次是重复计数。批 I 实测形状：0028/0029 两栋 18 条
    inspection_report 模式卡的镜像行。

    ⚠️ 镜像标记由 validator 在求值**之后**才写进 notes，本层看不到，
    故判据由调用方前置计算传入；validator 侧那段计算与镜像覆盖条件同源。
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    card = make_rule_card()
    slot = "supervision.record.completed"
    _patch_gates(monkeypatch, card, slots={slot})
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {})
    ref = dict(_slot_ref(slot), roles=["trigger"])
    idx = FactIndex(make_fact_pack([_agg_fact(slot, True)]))
    obl = evaluate_slot_role(card, ref, idx, True, META,
                             authorized_scope_selection=True,
                             is_consistency_mirror=True)
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == "satisfied"
    assert "unauthorized_aggregate_guard" not in str(obl.notes or "")


def test_mirror_exemption_predicate_matches_actual_mirror_condition():
    """🔴 回归：豁免判据必须与 validator 里**实际发生镜像覆盖**的那一支等价。

    我首版把判据写成「slot_ref 被 `trigger_conditions` 引用」就豁免，
    漏了「**且真能取到来源触发器**（`_trigger_by_slot_ref.get(id) is not None`）」
    ——`None` 是"同 slot_ref 多触发项"的哨兵，那一支走的是
    `dual_track_multi_trigger_ref` 阻断、**不写镜像标记**。
    后果：批 I 实测放过 **938 条**触发器实判（530 条消费派生
    `slot_target_fallback` 行 + 408 条消费原生 `procedure_gate_state` 行），
    它们被护栏豁免却拿不到镜像标记，扫描器照抓 ⇒ 两处口径漂移当场显形。

    本测试用源码文本锁住两处条件同源（判据分处两个函数、无法在单元层
    直接比对求值结果，故锁文本；两处任一改动都会在此转红）。
    """
    import inspect
    from evo_agent_baseline.closure import validator as v
    src = inspect.getsource(v.validate_building_closure)
    assert "_mirror_now" in src
    # 豁免判据必须包含"取得到来源触发器"这一合取项
    assert "_trigger_by_slot_ref.get(_sr_id_pre) is not None" in src, (
        "镜像豁免判据漏了 `_src is not None` 合取项——会放过"
        "「被引用但取不到来源」的触发器实判")
    # 且必须与实际镜像覆盖支的四个条件同源
    for cond in ("exclude_fallback_reasons_facts", "trigger_active is True",
                 "_trigger_ref_ids"):
        assert cond in src


def test_value_authorized_missing_marker_refuses(monkeypatch):
    """审核门探针形状①：楼级行但缺 aggregation=building 标记 → 拒绝式失败，
    既不给新原因码也不许滑进「存在即满足」。"""
    obl = _eval_value_authorized(monkeypatch, False, marked=False)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert "值授权绑定拒绝判定" in str(obl.notes or "")


def test_value_authorized_null_value_refuses(monkeypatch):
    """审核门探针形状②：聚合值为 null → 拒绝，不得判 satisfied。"""
    obl = _eval_value_authorized(monkeypatch, None, value_type="null")
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_value_authorized_string_value_refuses(monkeypatch):
    """审核门探针形状③：聚合值为字符串 "false" → 拒绝，不得判 satisfied。"""
    obl = _eval_value_authorized(monkeypatch, "false", value_type="string")
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_value_authorized_numeric_value_refuses(monkeypatch):
    obl = _eval_value_authorized(monkeypatch, 1, value_type="number")
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_value_authorized_multiple_agg_rows_refuse(monkeypatch):
    """多行楼级聚合（同值故 conflict_status=consistent 本会滑过）→ 拒绝。"""
    slot = "procedure.inspection.prescribed.completed"
    rows = [_agg_fact(slot, True), _agg_fact(slot, True, fid="f-agg2")]
    obl = _eval_value_authorized(monkeypatch, None, rows=rows)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert "行数=2" in str(obl.notes or "")


def test_value_authorized_no_agg_row_same_value_parts_refuses(monkeypatch):
    """二轮审核探针：无楼级行＋两条**同值**假部位行（conflict=consistent）——
    首版凭「有无楼级行」放行导致整体绕过 A′滑进存在即满足；现须拒绝。"""
    slot = "procedure.inspection.prescribed.completed"
    rows = [
        make_fact("p1", slot_id=slot, value=False, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1"),
        make_fact("p2", slot_id=slot, value=False, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-2"),
    ]
    obl = _eval_value_authorized(monkeypatch, None, rows=rows)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert obl.satisfaction_status == "unknown"


def test_value_authorized_single_part_row_refuses(monkeypatch):
    """单条部位行（一致绑定但非楼级聚合）→ 同样拒绝。"""
    slot = "procedure.inspection.prescribed.completed"
    rows = [make_fact("p1", slot_id=slot, value=True, value_type="boolean",
                      carrier_type="sidecar_entry", carrier_id="FRG-1")]
    obl = _eval_value_authorized(monkeypatch, None, rows=rows)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_evidence_channel_aggregate_false_goes_pending_not_violated(monkeypatch):
    """边界单首轮否决形状①的反向测试：证据要求通道（slot 直绑、无 slot_ref
    身份 ⇒ 结构上不可能命中精确合同表）绑到楼级聚合**假值**行时，实判必须
    转待裁码——RC-0048 首轮实测该行被判 violated，正是"找不到有效精确合同
    仍产实判"的漏口。"""
    from evo_agent_baseline.closure.obligation_deriver import (
        _evaluate_evidence_by_slot,
    )
    card = make_rule_card()
    slot = "supervision.record.completed"
    idx = FactIndex(make_fact_pack([_agg_fact(slot, False)]))
    obl = _evaluate_evidence_by_slot(
        card, "evidence", [slot], {"notes": "bucket=for_matching"}, idx, META,
        authorized_scope_selection=True)
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "evidence_channel_aggregate_guard" in str(obl.notes or "")


def test_evidence_channel_default_off_unchanged(monkeypatch):
    """开关关闭时证据通道逐位不变（存量行为回归护栏）。"""
    from evo_agent_baseline.closure.obligation_deriver import (
        _evaluate_evidence_by_slot,
    )
    card = make_rule_card()
    slot = "supervision.record.completed"
    idx = FactIndex(make_fact_pack([_agg_fact(slot, False)]))
    obl = _evaluate_evidence_by_slot(
        card, "evidence", [slot], {"notes": "bucket=for_matching"}, idx, META,
        authorized_scope_selection=False)
    assert "evidence_channel_aggregate_guard" not in str(obl.notes or "")
    assert obl.open_reason_code != "binding_requires_adjudication_authorization"


def _evidence_card_and_pack(slot):
    """一张只带 evidence_requirement（走 slot_ref 通道）的卡 + 一条楼级聚合假值行。

    用于端到端覆盖「开关穿透」——上面两条证据通道测试直调
    `_evaluate_evidence_by_slot`，测的是**护栏本体**；本组测的是**接线**。
    """
    ref = {"slot_ref_id": "RC.t.c01.sr01", "slot_id": slot,
           "roles": ["evidence"], "required": True, "qualifiers": {}}
    card = make_rule_card(
        slot_role_map=[ref],
        evidence_requirements={
            "for_matching": [{
                "evidence_requirement_id": "er01", "kind": "inspection_record",
                "required": True, "description": "t", "artifact_ids": [],
                "slot_ref_ids": ["RC.t.c01.sr01"], "measure_keys": [],
                "required_field_groups": [],
            }],
            "for_submission": [], "for_completion": [],
        })
    return card, make_fact_pack([_agg_fact(slot, False)])


def test_switch_threading_evidence_requirement_level():
    """🔴 接线覆盖②：`evaluate_evidence_requirement` → `_evaluate_evidence_by_slot`
    的下传。变异实测：删掉这处下传时，直调式测试**全绿**（抓不住）。"""
    from evo_agent_baseline.closure.obligation_deriver import (
        evaluate_evidence_requirement,
    )
    slot = "supervision.record.completed"
    card, pack = _evidence_card_and_pack(slot)
    req = card.evidence_requirements["for_matching"][0]
    obl = evaluate_evidence_requirement(
        card, "for_matching", dict(req), FactIndex(pack), True, META,
        authorized_scope_selection=True)
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "evidence_channel_aggregate_guard" in str(obl.notes or "")


def test_switch_threading_validator_level():
    """🔴 接线覆盖①：`validate_building_closure` → `evaluate_evidence_requirement`
    的传递。变异实测：把 validator 那处改成硬编码 False 时，直调式测试
    与上一条**都绿**（抓不住）——这正是"只测生产者等于没测"的形状。"""
    from .fixtures import make_rule_slice, run_closure
    slot = "supervision.record.completed"
    card, pack = _evidence_card_and_pack(slot)
    res = run_closure(make_rule_slice([card]), pack,
                      authorized_scope_selection=True)
    hits = [o for o in res.obligation_set.obligations
            if "evidence_channel_aggregate_guard" in str(o.notes or "")]
    assert hits, "开关未穿透到证据要求通道（validator 侧接线断了）"
    assert all(o.open_reason_code == "binding_requires_adjudication_authorization"
               for o in hits)


def test_switch_threading_validator_level_default_off():
    """对照：缺省关闭时不得触发（防上一条靠"恒真"通过）。"""
    from .fixtures import make_rule_slice, run_closure
    slot = "supervision.record.completed"
    card, pack = _evidence_card_and_pack(slot)
    res = run_closure(make_rule_slice([card]), pack)
    assert not [o for o in res.obligation_set.obligations
                if "evidence_channel_aggregate_guard" in str(o.notes or "")]


def test_production_value_registry_shape():
    """生产登记形状冻结（先量后冻）。

    沿革：A′ 首批恰 row 37 一键（「授权过宽不通过」裁决）；2026-08-04 c55 批
    +22 键（55 单元逐条裁定，`裁定_消费55_*`）→ 现 23。row 37 必须仍在
    （c55 落表不许挤掉先例），且 22 新键全在 reporting 轴（qwen 审核发现②
    修正——本测试当时只冻 row 37，落表后套红被审出漏改）。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    row37 = (
        "rc.mbis.inspection.personal_conduct.ri.duty."
        "s2_1_3_a_personally_conduct_inspection.c01",
        "rc.mbis.inspection.personal_conduct.ri.duty."
        "s2_1_3_a_personally_conduct_inspection.c01.sr01",
    )
    keys = od.VALUE_CONSUMPTION_AUTHORIZED_BINDINGS
    assert row37 in keys
    assert len(keys) == 23
    from evo_agent_baseline.closure import binding_contract_registry as reg
    for k in keys - {row37}:
        assert reg.SCOPE_PRECISE_BINDINGS[k]["slot_id"].startswith("reporting.")
