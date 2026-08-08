# -*- coding: utf-8 -*-
"""S1 权威结构表与否定授权条款的机器护栏（逐行批准裁决 2026-08-02）。

面：①表形状（37 行/唯一键/派生视图口径）；②卡指纹护栏（篡改指纹 ⇒ 行自动
失效）；③**否定授权条款机器面**——诊断型绑定的产物态事实经两条路径都只能落
`open/artifact_state_not_valid_evidence`，值真值假都不产 satisfied/violated；
④A′子集与诊断集零交集、A′子集与 value_consumption_registry 恒等。
"""
from __future__ import annotations

from evo_agent_baseline.closure import binding_contract_registry as reg
from evo_agent_baseline.closure.value_consumption_registry import (
    VALUE_CONSUMPTION_AUTHORIZED_BINDINGS,
)
from evo_agent_baseline.closure.fact_binding import FactIndex
# ⚠️ 直接调 `_evaluate_node_slot_binding` 时，`base_kind` 必须等于
#    `refine_action_kind(node.node_kind, node.action)`——该函数有前置断言
#    （2026-08-03 审核门要求；下游对许可闸硬传 kind_from_action_refinement=True
#    正是基于「本通道 kind 必来自前缀猜测改类」这条不变量）。
#    本文件夹具 action="prepare_report" ⇒ 应传 "report_field"。
from evo_agent_baseline.closure.obligation_deriver import (
    _evaluate_node_slot_binding,
    evaluate_slot_role,
)
from evo_agent_baseline.closure.schema import ObligationNodeDTO
from .fixtures import BUILDING_ID, make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R", "world_id": "W", "building_id": BUILDING_ID}


# ---- ① 表形状 ----

def test_registry_shape_and_derived_views():
    # 🔴 2026-08-03 A 批落表：37 → **102**（追加 65 行，row 38-102）。
    # 这是**冻结登记数**，改它必须是「先量后冻」的结果，不是把断言改成实测值。
    # 本次依据：`落表料_A批65行_20260803.json` 65 行，
    # 出口码 49 非产物 ＋ 16 产物态，模式违规 0、零失效。
    # 2026-08-04 残余 50 止血 A 表段：102 → **104**（+2 行，row 103/104；
    # 原候选 3 行有 1 行撞唯一键闸——(s3_3_3_b, sr02) A 批已在，fail-closed 当场拦下）。
    # 2026-08-04 消费通道 c55 批：104 → **126**（+22 行值消费，row 105-126；
    # 依据＝`落表料_消费55乙类行_20260804.json` 22 行键唯一、31/31 行世界组合唯一命中、
    # 与既有 104 行零键碰撞；单元 36 挂角色矛盾案未落、甲事件锚 4 单元另立步）。
    # 2026-08-04 件四批 1：126 → **125**（退役 row 21——§3.2.6 同义重复建卡二保一，
    # 其卡 `…ri.review.s3_2_6_prepare_inspection_method_statement.c01` 已从权威卡包移除，
    # 该行的绑定对象不再存在；row 号**有意不重排**，21 为空号，
    # 因为 `test_granularity_declaration._DECLARED_ROWS_FROZEN` 冻在 range(105,127)）。
    assert len(reg.BINDING_CONTRACTS) == 125
    keys = {(r["rule_card_id"], r["slot_ref_id"]) for r in reg.BINDING_CONTRACTS}
    assert len(keys) == 125                                  # 唯一键（无碰撞）
    assert len(reg.ACTIVE_ROWS) == 125 and not reg.STALE_ROWS
    assert reg.DISABLED_REASON is None
    # 🔴 2026-08-05 #33 保护闸：c55 的 22 行（105-126）翻成 `diagnostic_only`
    # ＋耦合未证出口 ⇒ 值消费 23→**1**（只剩 row 37 先例）、诊断 102→**124**。
    # 依据：`决议_33处置_20260805.md` §一.1 ＋ `重核准记录_33保护闸_20260805.md`。
    # ⚠️ 这三个数是**冻结登记数**，改它必须是重核准的结果，不是把断言改成实测值。
    assert len(reg.VALUE_CONSUMPTION_BINDINGS) == 1          # 仅 row 37 先例
    assert reg.VALUE_CONSUMPTION_BINDINGS & reg.DIAGNOSTIC_ONLY_BINDINGS == frozenset()
    assert len(reg.DIAGNOSTIC_ONLY_BINDINGS) == 124   # 36+65+2 止血−退役 row 21 ＝102，＋#33 翻转 22
    assert len(reg.COUPLING_UNPROVEN_BINDINGS) == 22  # #33 射程，全在诊断集内
    assert reg.COUPLING_UNPROVEN_BINDINGS <= reg.DIAGNOSTIC_ONLY_BINDINGS
    # A 批 65 行把粗槽面从 4 扩到 21（2026-08-03）。这里**不逐一列举**，
    # 改锁两条不变量——列举一长串槽名只会让下次扩表时机械照抄，锁不住任何东西：
    #   ① 旧 4 个必须仍在（不许被新行挤掉）；
    #   ② 粗槽集必须恰等于表里出现过的 slot_id 集合（派生视图不许漏也不许多）。
    assert {"reporting.artifact.prepared", "artifact.report.inspection",
            "artifact.proposal.detailed_investigation",
            "procedure.inspection.prescribed.completed"} <= reg.COARSE_SLOTS
    assert reg.COARSE_SLOTS == {r["slot_id"] for r in reg.ACTIVE_ROWS}
    # 行 36（§7.2.2）裁决限定：只许槽位角色路径
    row36 = [r for r in reg.BINDING_CONTRACTS if r["row"] == 36][0]
    assert row36["allowed_paths"] == ["slot_role"]
    assert (row36["rule_card_id"], row36["slot_ref_id"]) not in reg.NODE_SLOT_BINDINGS


def test_value_registry_derives_from_authority_table():
    assert VALUE_CONSUMPTION_AUTHORIZED_BINDINGS == reg.VALUE_CONSUMPTION_BINDINGS


def test_negative_authorization_clause_frozen():
    for must in ("楼级聚合读数", "artifact_state_not_valid_", "satisfied",
                 "violated", "自动失效", "重新过决策门"):
        assert must in reg.NEGATIVE_AUTHORIZATION_CLAUSE


# ---- ② 卡指纹护栏 ----

def test_fingerprint_guard_invalidates_tampered_row(monkeypatch):
    """篡改任一行卡指纹 ⇒ 该行失效（授权自动失效——裁决机器面）。"""
    tampered = [dict(r) for r in reg.BINDING_CONTRACTS]
    tampered[0]["card_content_sha256"] = "0" * 64
    monkeypatch.setattr(reg, "BINDING_CONTRACTS", tuple(tampered))
    active, stale, reason = reg._validate_against_pack()
    assert reason is None
    assert len(stale) == 1 and stale[0]["row"] == tampered[0]["row"]
    # 篡改 1 行 ⇒ 恰该行失效，其余全活（基数随表冻结数走：125−1）
    assert len(active) == len(reg.BINDING_CONTRACTS) - 1 == 124


# ---- ③ 否定授权条款机器面（诊断型绑定不产实判）----

def _product_state_rows(slot, value):
    """产物态布尔行（`slot_target_fallback` 派生锚），楼级带聚合标记。"""
    return [
        make_fact("f-agg", slot_id=slot, value=value, value_type="boolean",
                  carrier_type="building", carrier_id=BUILDING_ID,
                  qualifiers={"aggregation": "building",
                              "artifact_key": "report.completion"},
                  provenance={"derivation": "slot_target_fallback"}),
        make_fact("f-p1", slot_id=slot, value=not value, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1",
                  qualifiers={"artifact_key": "report.completion"},
                  provenance={"derivation": "slot_target_fallback"}),
    ]


def _gates(monkeypatch, card, slot, *, node=True,
           aggregation_source="slot_target_fallback",
           declared_exit="open/artifact_state_not_valid_evidence"):
    import evo_agent_baseline.closure.obligation_deriver as od
    key = (card.rule_card_id, "RC.t.c01.sr01")
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset({slot}))
    monkeypatch.setattr(od, "SLOT_ROLE_AUTHORIZED_BINDINGS", frozenset({key}))
    monkeypatch.setattr(od, "NODE_SLOT_AUTHORIZED_BINDINGS",
                        frozenset({key}) if node else frozenset())
    # 诊断型：绝不进 A′集合；终止规则消费诊断集＋合同行（聚合来源登记）。
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS",
                        frozenset({key}))
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED",
                        {key: {"aggregation_source": aggregation_source,
                               "policy": "diagnostic_only",
                               # 丁⑤（2026-08-03 三方仲裁）：合同行声明的出口只作
                               # 审计，但运行时**必核对**它与终止器实际出口一致；
                               # 桩里不带这两个字段 ⇒ 正确地 fail-closed 成 blocked。
                               "true_exit": declared_exit,
                               "false_exit": declared_exit}})


def _slot_ref(slot):
    return {"slot_ref_id": "RC.t.c01.sr01", "slot_id": slot,
            "roles": ["evidence"], "required": True,
            "qualifiers": {"artifact_key": "report.completion"}}


def test_diagnostic_binding_slot_role_never_produces_verdict(monkeypatch):
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot)
    for value in (True, False):
        idx = FactIndex(make_fact_pack(_product_state_rows(slot, value)))
        obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                                 authorized_scope_selection=True)
        assert obl.satisfaction_status == "unknown", value
        assert obl.closure_status == "open"
        assert obl.open_reason_code == "artifact_state_not_valid_evidence"
        assert obl.evidence_fact_ids == ["f-agg"]   # 分级确实选中了聚合行


def test_diagnostic_binding_node_path_never_produces_verdict(monkeypatch):
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot)
    node = ObligationNodeDTO.from_dict({
        "obligation_node_id": "n1", "node_kind": "duty",
        "actor": "ri", "action": "prepare_report",
    })
    for value in (True, False):
        idx = FactIndex(make_fact_pack(_product_state_rows(slot, value)))
        obl = _evaluate_node_slot_binding(
            card, node, "report_field", _slot_ref(slot), idx, META,
            authorized_scope_selection=True)
        assert obl.satisfaction_status == "unknown", value
        assert obl.closure_status == "open"
        assert obl.open_reason_code == "artifact_state_not_valid_evidence"


def test_probe1_license_set_mutation_cannot_unlock_verdict(monkeypatch):
    """审核门反向探针①：把 evidence 移入许可集合——诊断绑定仍必须落诊断码
    （终止规则先于许可闸，出口由合同锁定）。首版此探针实测滑成 satisfied。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot)
    monkeypatch.setattr(
        od, "ARTIFACT_STATE_LICENSED_KINDS",
        od.ARTIFACT_STATE_LICENSED_KINDS | frozenset({"evidence"}))
    monkeypatch.setattr(
        od, "ARTIFACT_STATE_UNLICENSED_KINDS",
        od.ARTIFACT_STATE_UNLICENSED_KINDS - frozenset({"evidence"}))
    idx = FactIndex(make_fact_pack(_product_state_rows(slot, True)))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert "diagnostic_contract_terminal" in str(obl.notes or "")


def test_probe2_derivation_rename_cannot_unlock_verdict(monkeypatch):
    """审核门反向探针②：聚合行派生标记被改名——聚合来源与合同登记不符 ⇒
    拒绝式失败，绝不 satisfied。首版此探针实测滑成 satisfied。"""
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot)
    rows = _product_state_rows(slot, True)
    rows[0] = make_fact("f-agg", slot_id=slot, value=True, value_type="boolean",
                        carrier_type="building", carrier_id=BUILDING_ID,
                        qualifiers={"aggregation": "building",
                                    "artifact_key": "report.completion"},
                        provenance={"derivation": "renamed_derivation"})
    idx = FactIndex(make_fact_pack(rows))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.satisfaction_status == "unknown"
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert "聚合身份或来源与合同登记不符" in str(obl.notes or "")


def test_probe3_sentinel_cannot_intercept_diagnostic_binding(monkeypatch):
    """二轮阻断①：节点路径哨兵先于诊断终止会把诊断绑定截成
    closed/not_applicable——现须诊断终止**先于**哨兵（两路径优先级唯一）。
    用恒命中的哨兵桩证明：诊断绑定仍落诊断码，哨兵摸不到。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot)

    def _always_sentinel(card_, meta_, kind_, common_, bound_, idx_):
        return od._new_obligation(
            card_, meta_, kind_, "closed", "not_applicable",
            **{**common_, "notes": "non_adjudicative_sentinel"})

    monkeypatch.setattr(od, "_sentinel_short_circuit", _always_sentinel)
    node = ObligationNodeDTO.from_dict({
        "obligation_node_id": "n1", "node_kind": "duty",
        "actor": "ri", "action": "prepare_report",
    })
    idx = FactIndex(make_fact_pack(_product_state_rows(slot, True)))
    obl = _evaluate_node_slot_binding(
        card, node, "report_field", _slot_ref(slot), idx, META,
        authorized_scope_selection=True)
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert obl.satisfaction_status == "unknown"
    assert "non_adjudicative_sentinel" not in str(obl.notes or "")


def test_probe4_rejected_binding_refuses_not_falls_back(monkeypatch):
    """二轮阻断②：许可漂移使诊断行失效后，绑定不许"消失回退通用求值"
    （首版探针实测滑成 closed/satisfied）——现须 blocked/schema。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    key = (card.rule_card_id, "RC.t.c01.sr01")
    # 模拟漂移后的真实状态：行失效 ⇒ 活视图空、拒绝视图含该键；许可集合已被改。
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset())
    monkeypatch.setattr(od, "SLOT_ROLE_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "NODE_SLOT_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "REJECTED_AUTHORIZED_BINDINGS", frozenset({key}))
    monkeypatch.setattr(
        od, "ARTIFACT_STATE_LICENSED_KINDS",
        od.ARTIFACT_STATE_LICENSED_KINDS | frozenset({"evidence"}))
    monkeypatch.setattr(
        od, "ARTIFACT_STATE_UNLICENSED_KINDS",
        od.ARTIFACT_STATE_UNLICENSED_KINDS - frozenset({"evidence"}))
    idx = FactIndex(make_fact_pack(_product_state_rows(slot, True)))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert "授权绑定已失效" in str(obl.notes or "")
    assert obl.satisfaction_status == "unknown"


def test_probe5_table_disabled_aprime_false_refuses(monkeypatch):
    """二轮阻断③：全表失效后 A′绑定输入假值不许回退成 satisfied——
    须 blocked/schema（节点路径同验）。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    slot = "procedure.inspection.prescribed.completed"
    card = make_rule_card()
    key = (card.rule_card_id, "RC.t.c01.sr01")
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset())
    monkeypatch.setattr(od, "SLOT_ROLE_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "NODE_SLOT_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", frozenset())
    monkeypatch.setattr(od, "REJECTED_AUTHORIZED_BINDINGS", frozenset({key}))
    rows = [
        make_fact("f-agg", slot_id=slot, value=False, value_type="boolean",
                  carrier_type="building", carrier_id=BUILDING_ID,
                  qualifiers={"aggregation": "building"}),
    ]
    idx = FactIndex(make_fact_pack(rows))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    node = ObligationNodeDTO.from_dict({
        "obligation_node_id": "n1", "node_kind": "duty",
        "actor": "ri", "action": "inspect",
    })
    obl2 = _evaluate_node_slot_binding(
        card, node, "action", _slot_ref(slot), idx, META,
        authorized_scope_selection=True)
    assert obl2.closure_status == "blocked"
    assert obl2.blocked_reason_code == "schema_contract_violation"


def test_schema_gap_aggregator_and_axis(monkeypatch):
    """二轮欠项③形状：非法聚合子/缺 qualifier_axis 键 → 全表失效。"""
    bad1 = [dict(r) for r in reg.BINDING_CONTRACTS]
    bad1[0]["aggregator"] = "nonsense"
    monkeypatch.setattr(reg, "BINDING_CONTRACTS", tuple(bad1))
    active, stale, reason = reg._validate_against_pack()
    assert not active and str(reason).startswith("schema:")
    bad2 = [dict(r) for r in reg.BINDING_CONTRACTS]
    del bad2[0]["qualifier_axis"]
    monkeypatch.setattr(reg, "BINDING_CONTRACTS", tuple(bad2))
    active, stale, reason = reg._validate_against_pack()
    assert not active and "qualifier_axis" in str(reason)


def test_license_dependency_fingerprint_matches_live_sets():
    """许可依赖指纹与活代码实算一致（漂移时导入期已让诊断行失效）。"""
    assert reg._current_license_sha() == reg.LICENSE_DEPENDENCY_SHA256
    assert reg.DISABLED_REASON is None


def test_node_path_binding_not_in_node_view_stays_ambiguous(monkeypatch):
    """行 36 形状：绑定只授权槽位角色路径 ⇒ 节点路径不分级、保持现状。"""
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, node=False)
    node = ObligationNodeDTO.from_dict({
        "obligation_node_id": "n1", "node_kind": "duty",
        "actor": "ri", "action": "prepare_report",
    })
    rows = [
        make_fact("f-p1", slot_id=slot, value=True, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-1",
                  qualifiers={"artifact_key": "report.completion"}),
        make_fact("f-p2", slot_id=slot, value=False, value_type="boolean",
                  carrier_type="sidecar_entry", carrier_id="FRG-2",
                  qualifiers={"artifact_key": "report.completion"}),
    ]
    idx = FactIndex(make_fact_pack(rows))
    obl = _evaluate_node_slot_binding(
        card, node, "report_field", _slot_ref(slot), idx, META,
        authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"


# ===== 丁⑤ 变异验证：声明出口与终止器实际出口不一致必须拒绝式失败 =====
# 🔴 「加了闸」不等于「闸会响」——本项目既有教训要求新闸必做变异验证。
def test_declared_exit_mismatch_fails_closed(monkeypatch):
    """把合同行的声明出口改成另一个合法诊断码，终止器必须 blocked，不得回退通用求值。"""
    slot = "reporting.artifact.prepared"
    card = make_rule_card()
    _gates(monkeypatch, card, slot,
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    for value in (True, False):
        idx = FactIndex(make_fact_pack(_product_state_rows(slot, value)))
        obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                                 authorized_scope_selection=True)
        # 事实是产物态 ⇒ 实际出口是 artifact_state_...，与声明的另一码不符
        assert obl.closure_status == "blocked", value
        assert obl.blocked_reason_code == "schema_contract_violation"
        assert obl.satisfaction_status == "unknown"


def test_non_artifact_reading_gets_the_other_diagnostic_code():
    """非产物读数走另一个码，且 notes 不得称其为 artifact-state（仲裁判丙的决定性理由）。

    🔴 首版这条测试**跑在不可能显现的输入上**：我复用了 `_product_state_rows`，
    它无条件盖 `derivation="slot_target_fallback"`（第三锚）⇒ 无论槽名叫什么都仍被
    分类成产物态。真正的非产物读数必须三锚全不沾：无 artifact 载体域、槽不在
    `W0_09_ARTIFACT_SLOTS`、来源不是回退表。
    """
    from evo_agent_baseline.closure.obligation_deriver import (
        diagnostic_refusal_reason_code, _artifact_state_refusal,
        is_artifact_state_fact,
        ARTIFACT_STATE_OPEN_REASON, DIAGNOSTIC_BINDING_OPEN_REASON,
    )
    facts = [make_fact("f-proc", slot_id="procedure.investigation.detailed.started",
                       value=True, value_type="boolean",
                       carrier_type="building", carrier_id=BUILDING_ID,
                       qualifiers={"aggregation": "building"}, provenance={})]
    assert not any(is_artifact_state_fact(f) for f in facts), "三锚必须全不沾"
    assert diagnostic_refusal_reason_code(facts) == DIAGNOSTIC_BINDING_OPEN_REASON
    obl = _artifact_state_refusal(make_rule_card(), META, "evidence", {}, facts)
    assert obl.open_reason_code == DIAGNOSTIC_BINDING_OPEN_REASON
    assert obl.open_reason_code != ARTIFACT_STATE_OPEN_REASON
    assert "artifact-state" not in str(obl.notes or "")
    # 反向：产物态事实仍走旧码（分流不能一刀切成新码）
    assert diagnostic_refusal_reason_code(
        _product_state_rows("reporting.artifact.prepared", True)
    ) == ARTIFACT_STATE_OPEN_REASON


def test_every_production_diagnostic_row_declares_the_exit_its_facts_will_take():
    """每一行诊断绑定的**声明出口**必须与它的事实类别一致——按行分两类断言。

    🔴 2026-08-03 拆成两半（原先是「全部诊断行都必须绑产物态槽」）。
    原断言在「表里只有产物态行」时成立，它的 docstring 自述是
    **「往表里加非产物行时的报警器」**——A 批 49 行非产物落表后它必红。
    **那声报警是因决策而响，不是事故**：加非产物行正是「丁」路的目的。
    ⇒ 保留它的防漂移价值，但按行分类：

    - **产物态行**（槽 ∈ `W0_09_ARTIFACT_SLOTS` 或来源＝回退表）
      ⇒ 必须声明旧码 `artifact_state_not_valid_evidence`；
    - **非产物行** ⇒ 必须声明新码 `diagnostic_binding_not_valid_evidence`。

    两类都由 `diagnostic_refusal_reason_code()` 在运行时按**事实分类器**分流，
    本测试锁的是**声明与那个分流一致**——不一致会被丁⑤ 在运行时 fail-closed，
    但那太晚了，应该在这里先炸。

    🔴 2026-08-05 加**第三类**（#33 保护闸，`重核准记录_33保护闸_20260805.md`）。
    翻转集 22 行（rows 105-126）也是 `diagnostic_only`，但它们的原因码
    **不由事实分类器分流**——同一条呈交轴读数在闸下是「耦合未证」、根治后是
    「耦合已证」，**事实类型一个字没变、变的是行的授权状态**，分类器结构上答不出。
    故它们是**声明驱动**的，求值器读行级声明直出该码
    （`_diagnostic_contract_terminal` 里的共享判据先行）。
    ⇒ 本测试对这 22 行改锁**另一条不变量**：它们必须恰好等于闸的派生视图，
    且两出口同为闸码。分类器那条断言对它们不适用（套上去必假）。
    """
    from evo_agent_baseline.closure.obligation_deriver import (
        DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS, W0_09_ARTIFACT_SLOTS,
        ARTIFACT_STATE_OPEN_REASON, DIAGNOSTIC_BINDING_OPEN_REASON,
    )
    gate_exit = f"open/{reg.COUPLING_UNPROVEN_REASON_CODE}"
    rows = [reg.SCOPE_PRECISE_BINDINGS[k] for k in DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS]
    assert rows, "断言不能跑在空集合上"
    seen_artifact = seen_plain = 0
    gated_keys = set()
    for k in DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS:
        r = reg.SCOPE_PRECISE_BINDINGS[k]
        if reg.coupling_unproven_exit_code(r) is not None:
            # 第三类：声明驱动，分类器不参与。
            assert r["true_exit"] == r["false_exit"] == gate_exit, r["row"]
            gated_keys.add(k)
            continue
        slot, src = r["slot_id"], r["aggregation_source"]
        is_artifact = (slot in W0_09_ARTIFACT_SLOTS
                       or src == "slot_target_fallback")
        want = (ARTIFACT_STATE_OPEN_REASON if is_artifact
                else DIAGNOSTIC_BINDING_OPEN_REASON)
        assert r["true_exit"] == f"open/{want}", (
            f"row{r['row']} 槽={slot} 来源={src} 声明={r['true_exit']}，应为 open/{want}")
        assert r["true_exit"] == r["false_exit"], f"row{r['row']} 两出口必须相同"
        if is_artifact:
            seen_artifact += 1
        else:
            seen_plain += 1
    # 三类都要有样本，否则断言可能在空的一侧空过（本项目既有教训）。
    assert seen_artifact > 0, "产物态行一个都没有？表构成变了，先查"
    assert seen_plain > 0, "非产物行一个都没有？表构成变了，先查"
    # 第三类必须恰等于闸的派生视图——不许出现「声明了闸码但没进视图」的漏网行。
    assert gated_keys == set(reg.COUPLING_UNPROVEN_BINDINGS)
    assert len(gated_keys) == 22



# ===== 形状闸分档 ＋ 来源白名单：正反变异（2026-08-03 决策门落地）=====
# 🔴 「套件全绿」不等于新分支被走到——本项目既有教训（测试跑在缺陷不可能显现的
# 输入上）。这四条各钉一个分支，且每条都配了反向。

def _rows(slot, *specs):
    """按 (carrier_type, aggregation, derivation) 造事实行。"""
    out = []
    for i, (carrier, agg, deriv) in enumerate(specs):
        q = {"artifact_key": "report.completion"}
        if agg:
            q["aggregation"] = agg
        out.append(make_fact(f"f-{i}", slot_id=slot, value=True, value_type="boolean",
                             carrier_type=carrier, carrier_id=BUILDING_ID,
                             qualifiers=q, provenance={"derivation": deriv} if deriv else {}))
    return out


def test_src_whitelist_accepts_registered_lookup_rule_derivation(monkeypatch):
    """`slot_target_lookup_rule` 是**登记在册**的派生通道，必须放行。

    实测误伤面 66.7%：`building_reading_aggregation` 通道 1,080 个（行×栋）对里
    720 对带这个戳。原判据「非回退表 ⇒ derivation 必须为空」会把它们全判成
    契约坏了 ⇒ 对审查员说「模式契约违例」，而系统没坏。
    """
    slot = "procedure.investigation.detailed.started"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="building_reading_aggregation",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(
        _rows(slot, ("building", "building", "slot_target_lookup_rule"))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "diagnostic_binding_not_valid_evidence"


def test_src_whitelist_still_rejects_fallback_derivation_on_world_channel(monkeypatch):
    """反向：回退表派生混进 `building_reading_aggregation` 行 ⇒ **必须拒**（防通道串味）。"""
    slot = "procedure.investigation.detailed.started"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="building_reading_aggregation",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(
        _rows(slot, ("building", "building", "slot_target_fallback"))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_shape_gate_relaxes_only_when_world_has_no_building_aggregate(monkeypatch):
    """世界本无楼级聚合行（唯一行是 sidecar 载体）⇒ 走宽松分支，落 open ＋ 诊断码。

    并且**必须留痕**：notes 里要写明证据载体，让「放宽」在产物里可见。
    """
    slot = "procedure.investigation.proposal.submitted"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="building_reading_aggregation",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(_rows(slot, ("sidecar_entry", None, None))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "open", obl.blocked_reason_code
    assert obl.open_reason_code == "diagnostic_binding_not_valid_evidence"
    assert "形状闸宽松分支" in str(obl.notes or ""), "放宽必须留痕，不许静默生效"
    assert "sidecar_entry" in str(obl.notes or "")


def test_code_derived_reading_accepts_registered_stamp_on_registered_carrier(monkeypatch):
    """第三档正向：登记戳 ＋ 登记载体 ⇒ 放行，落 open ＋ 诊断码，且留痕写明载体。

    🔴 这条是审核门 grok 点名的欠项——第三档此前只靠批重放验收，
    `closure/tests` 对 `code_derived_reading` 零命中，回归面弱于桶通道。

    第三档**不走** `marked`／`has_building_aggregate` 分档：它的事实本就不是楼级
    聚合行（`derive_verification_performed_facts` 从量测行拷贝载体）⇒ 套那套判据必假。
    形状约束整个改由「戳 ∧ 载体」承担，故这两条测试就是该档**唯一**的常驻牙齿。
    """
    slot = "verification.test.performed"        # 生产表 row 62/63/67/100 用的槽
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="code_derived_reading",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(
        _rows(slot, ("measurement", None, "test_performed_from_measurement"))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "open", obl.blocked_reason_code
    assert obl.open_reason_code == "diagnostic_binding_not_valid_evidence"
    assert obl.satisfaction_status == "unknown"
    assert "代码派生读数通道" in str(obl.notes or ""), "宽松分支必须留痕"
    assert "measurement" in str(obl.notes or "")


def test_code_derived_reading_rejects_registered_stamp_on_wrong_carrier(monkeypatch):
    """第三档反向（载体核对的牙齿）：戳对、**载体不是登记的 measurement** ⇒ 拒。

    登记载体是必须项不是建议项：那座桥从量测行**拷贝** `carrier_type`，
    **载体漂移即语义漂移**。只核戳不核载体 ⇒ 将来桥改从别的载体拷，这道校验静默失效。
    """
    slot = "verification.test.performed"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="code_derived_reading",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(
        _rows(slot, ("building", "building", "test_performed_from_measurement"))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert obl.satisfaction_status == "unknown"
    assert "聚合身份或来源与合同登记不符" in str(obl.notes or "")


def test_shape_gate_stays_strict_when_a_building_aggregate_exists(monkeypatch):
    """反向：世界**产了**楼级聚合行但不唯一 ⇒ 严检照旧生效，必须拒。

    这一条是分档的牙齿：放宽只对「结构上不可能」的情形，
    **不对「本该唯一却漂移成多条」的情形**——后者正是 `marked` 要报警的事。
    """
    slot = "supervision.record.completed"
    card = make_rule_card()
    _gates(monkeypatch, card, slot, aggregation_source="building_reading_aggregation",
           declared_exit="open/diagnostic_binding_not_valid_evidence")
    idx = FactIndex(make_fact_pack(_rows(
        slot, ("building", "building", None), ("building", "building", None))))
    obl = evaluate_slot_role(card, _slot_ref(slot), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code in ("schema_contract_violation",
                                       "ambiguous_fact_binding")

