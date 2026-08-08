# -*- coding: utf-8 -*-
"""§4.2.3 修法测试群（2026-08-07 决议底稿_s423修法 五件；spec §6.3.10.4 修订同刀）。

覆盖三刀：
  · 第 1 件：`_node_satisfaction_slot_refs` 成员资格判定语义化（`"evidence" in roles`，
    书写顺序不承载判定——roles 顺序变异逐位不变）；
  · 第 2 件：禁止节点条件禁止四格＋形状闸（喂**双槽四格**输入——旧单测只喂一槽一事实，
    「读对了那个槽」与「只有一个槽可读」在该输入上不可区分，复现_s423 §4.5）；
  · 第 4 件：`_evaluate_evidence_by_slot` 逐槽管线＋逐槽贡献护栏（任一声明槽零贡献
    即拒判，两码分账；方向断言＝护栏只能实判→open/blocked）。

双形态钉死（第 2 件边界②）：prohibition 卡内＝解禁前件参与节点判定；
非 prohibition 卡＝照旧生成独立 prerequisite 义务行，两形态并存不互扰。
"""
from __future__ import annotations

from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)

REC = "procedure.investigation.proposal.recognized"
ST = "procedure.investigation.detailed.started"


def _srole(slot_ref_id, slot_id, *, roles=("evidence",), required=True,
           qualifiers=None):
    return {
        "slot_ref_id": slot_ref_id,
        "slot_id": slot_id,
        "roles": list(roles),
        "required": required,
        "qualifiers": qualifiers or {},
    }


def _prohib_card(*, sr02_roles=("prerequisite", "evidence"), extra_roles=None):
    """§4.2.3 同形双槽禁止卡：sr02=解禁前件（roles 含 prerequisite）、sr03=纯 evidence。"""
    srm = [
        _srole("SR02", REC, roles=sr02_roles),
        _srole("SR03", ST, roles=("evidence",)),
    ]
    for ref in extra_roles or []:
        srm.append(ref)
    return make_rule_card(
        slot_role_map=srm,
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1",
                "node_kind": "prohibition",
                "actor": "ri",
                "action": "conduct_detailed_investigation",
            }]
        },
    )


def _facts(rec, st):
    facts = []
    if rec is not None:
        facts.append(make_fact("F.rec", slot_id=REC, value=rec,
                               value_type="boolean"))
    if st is not None:
        facts.append(make_fact("F.st", slot_id=ST, value=st,
                               value_type="boolean", carrier_type="building"))
    return facts


def _obls(card, facts=None):
    return run_closure(
        make_rule_slice([card]), make_fact_pack(facts or [])
    ).obligation_set.obligations


def _node_row(obls, node_id="N1", kind="prohibition"):
    rows = [o for o in obls
            if o.obligation_node_id == node_id and o.kind == kind]
    assert len(rows) == 1, [
        (o.kind, o.closure_status, o.satisfaction_status) for o in rows]
    return rows[0]


# ===================================================================== #
# 第 2 件：条件禁止四格（真值表 × prohibition 面）
# ===================================================================== #
def test_cell_tt_started_and_recognized_satisfied():
    """(T,T)：已获认可才进行——法条允许的路径 → closed/satisfied（解禁）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=True, st=True)))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "satisfied"
    # 诚实边界：只证前件存在且为真，不得声称时序已验。
    assert "非时序核验" in (row.notes or "")
    assert "时序已验" not in (row.notes or "")
    # 双槽都进了满足绑定（sr02 不再被静默丢弃）。
    assert "SR02" in "|".join(row.slot_ref_ids or [])
    assert "SR03" in "|".join(row.slot_ref_ids or [])


def test_cell_tf_started_without_recognition_violated():
    """(T,F)：未获认可即进行 → closed/violated（防过纠正：正当违规不许修没）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=False, st=True)))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "violated"


def test_cell_ff_nothing_happened_satisfied():
    """(F,F)：什么都没发生 → closed/satisfied（¬started → satisfied 标准语义）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=False, st=False)))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "satisfied"


def test_cell_ft_recognized_not_started_satisfied():
    """(F,T)：获认可未进行 → closed/satisfied。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=True, st=False)))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "satisfied"


def test_started_missing_open_never_violated():
    """被禁事实缺 → open/unknown（unknown 不定罪，绝不 violated）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=True, st=None)))
    assert row.closure_status == "open"
    assert row.satisfaction_status == "unknown"


def test_started_true_prereq_missing_null_observed_value():
    """started 真而前件缺 → open + null_observed_value（诚实拒判，不回退 violated）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=None, st=True)))
    assert row.closure_status == "open"
    assert row.satisfaction_status == "unknown"
    assert row.open_reason_code == "null_observed_value"


def test_started_false_prereq_missing_still_satisfied():
    """¬started → satisfied 与前件可得性无关（禁止义务标准语义）。"""
    row = _node_row(_obls(_prohib_card(), _facts(rec=None, st=False)))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "satisfied"


# ===================================================================== #
# 第 1 件：roles 顺序变异——顺序无语义（复现 A 行变异的反向钉死）
# ===================================================================== #
def test_roles_order_mutation_verdicts_bitwise_identical():
    """只调换 sr02 roles 书写顺序（不改任何值）→ 四格判定逐位不变。"""
    cells = [(True, True), (False, True), (False, False), (True, False),
             (None, True), (True, None)]
    for rec, st in cells:
        a = _node_row(_obls(
            _prohib_card(sr02_roles=("prerequisite", "evidence")),
            _facts(rec, st)))
        b = _node_row(_obls(
            _prohib_card(sr02_roles=("evidence", "prerequisite")),
            _facts(rec, st)))
        assert (
            a.closure_status, a.satisfaction_status,
            a.open_reason_code, a.blocked_reason_code,
        ) == (
            b.closure_status, b.satisfaction_status,
            b.open_reason_code, b.blocked_reason_code,
        ), (rec, st)


# ===================================================================== #
# 第 2 件：形状闸（缺省拒绝）
# ===================================================================== #
def test_shape_gate_two_pure_evidence_slots_refused():
    """两个纯 evidence 槽 → open + missing_satisfaction_binding（缺省拒绝）。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR01", "ev.alpha", roles=("evidence",)),
            _srole("SR02", "ev.beta", roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1", "node_kind": "prohibition",
                "actor": "ri", "action": "do_forbidden_thing",
            }]
        },
    )
    facts = [
        make_fact("F1", slot_id="ev.alpha", value=True, value_type="boolean"),
        make_fact("F2", slot_id="ev.beta", value=True, value_type="boolean"),
    ]
    row = _node_row(_obls(card, facts))
    assert row.closure_status == "open"
    assert row.open_reason_code == "missing_satisfaction_binding"
    assert "prohibition_shape_gate" in (row.notes or "")


def test_shape_gate_two_prerequisite_slots_refused():
    """恰一纯 evidence ＋ 两个 prerequisite 槽 → 缺省拒绝。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR01", "pre.alpha", roles=("prerequisite", "evidence")),
            _srole("SR02", "pre.beta", roles=("prerequisite", "evidence")),
            _srole("SR03", ST, roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1", "node_kind": "prohibition",
                "actor": "ri", "action": "do_forbidden_thing",
            }]
        },
    )
    facts = [
        make_fact("F1", slot_id="pre.alpha", value=True, value_type="boolean"),
        make_fact("F2", slot_id="pre.beta", value=True, value_type="boolean"),
        make_fact("F3", slot_id=ST, value=True, value_type="boolean"),
    ]
    row = _node_row(_obls(card, facts))
    assert row.closure_status == "open"
    assert row.open_reason_code == "missing_satisfaction_binding"
    assert "prohibition_shape_gate" in (row.notes or "")


def test_single_pure_evidence_prohibition_unchanged():
    """无前件槽的单槽禁止卡＝原行为逐位不变：truthy→violated、falsy→satisfied。"""
    card = make_rule_card(
        slot_role_map=[_srole("SR.only", ST, roles=("evidence",))],
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1", "node_kind": "prohibition",
                "actor": "ri", "action": "conduct_detailed_investigation",
            }]
        },
    )
    row_t = _node_row(_obls(card, [make_fact(
        "F1", slot_id=ST, value=True, value_type="boolean")]))
    assert (row_t.closure_status, row_t.satisfaction_status) == (
        "closed", "violated")
    row_f = _node_row(_obls(card, [make_fact(
        "F1", slot_id=ST, value=False, value_type="boolean")]))
    assert (row_f.closure_status, row_f.satisfaction_status) == (
        "closed", "satisfied")


# ===================================================================== #
# 第 2 件边界②：双形态并存不互扰
# ===================================================================== #
def test_dual_form_prerequisite_row_still_produced_in_prohibition_card():
    """prohibition 卡内：sr02 自身的 prerequisite 义务行继续产出（形态甲）。"""
    obls = _obls(_prohib_card(), _facts(rec=True, st=True))
    prereq_rows = [o for o in obls if o.kind == "prerequisite"]
    assert prereq_rows, "sr02 自身的 prerequisite 义务行不见了——双形态互扰"
    assert any(REC in (o.slot_ids or []) for o in prereq_rows)


def test_dual_form_non_prohibition_pure_prerequisite_not_a_channel():
    """非 prohibition 卡：纯 prerequisite 槽照旧不进节点满足通道（形态乙）。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR01", "pre.gate", roles=("prerequisite",)),
            _srole("SR02", "ev.done", roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1", "node_kind": "obligation",
                "actor": "ri", "action": "perform_inspection",
            }]
        },
    )
    facts = [
        make_fact("F1", slot_id="pre.gate", value=False, value_type="boolean"),
        make_fact("F2", slot_id="ev.done", value=True, value_type="boolean"),
    ]
    row = _node_row(_obls(card, facts), kind="action")
    # 纯 prerequisite 槽不作正向满足通道：节点只按 ev.done 判 satisfied，
    # pre.gate=false 不把节点拖成 violated。
    assert (row.closure_status, row.satisfaction_status) == (
        "closed", "satisfied")
    assert "SR01" not in "|".join(row.slot_ref_ids or [])


def test_first_item_multirole_evidence_joins_non_prohibition_conjunction():
    """第 1 件：非 prohibition 卡的 [prerequisite,evidence] 槽按 evidence 成员资格
    进入合取（roles 顺序无关）；该槽 false → 节点 violated（普通合取语义）。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR01", "qual.ok", roles=("prerequisite", "evidence")),
            _srole("SR02", "ev.done", roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [{
                "obligation_node_id": "N1", "node_kind": "obligation",
                "actor": "ri", "action": "perform_inspection",
            }]
        },
    )
    both_true = [
        make_fact("F1", slot_id="qual.ok", value=True, value_type="boolean"),
        make_fact("F2", slot_id="ev.done", value=True, value_type="boolean"),
    ]
    row = _node_row(_obls(card, both_true), kind="action")
    assert (row.closure_status, row.satisfaction_status) == (
        "closed", "satisfied")
    assert "SR01" in "|".join(row.slot_ref_ids or [])
    qual_false = [
        make_fact("F1", slot_id="qual.ok", value=False, value_type="boolean"),
        make_fact("F2", slot_id="ev.done", value=True, value_type="boolean"),
    ]
    row2 = _node_row(_obls(card, qual_false), kind="action")
    assert (row2.closure_status, row2.satisfaction_status) == (
        "closed", "violated")


# ===================================================================== #
# 第 4 件：逐槽贡献护栏（evidence requirement 通道）
# ===================================================================== #
def _multi_slot_req_card():
    return make_rule_card(
        slot_role_map=[
            _srole("SR01", "ev.alpha", roles=("evidence",)),
            _srole("SR02", "ev.beta", roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [
                {"obligation_node_id": "N1", "node_kind": "obligation",
                 "actor": "ri", "action": "perform_inspection"},
                {"obligation_node_id": "N2", "node_kind": "obligation",
                 "actor": "ri", "action": "keep_records"},
            ]
        },
        evidence_requirements={
            "for_matching": [],
            "for_submission": [],
            "for_completion": [{
                "evidence_requirement_id": "RC.test.001.e01",
                "kind": "record_check",
                "required": True,
                "description": "two-slot completion record",
                "artifact_ids": [],
                "slot_ref_ids": ["SR01", "SR02"],
                "measure_keys": [],
                "required_field_groups": [],
            }],
        },
    )


def _req_row(obls):
    rows = [o for o in obls
            if "RC.test.001.e01" in (o.evidence_node_refs or [])]
    assert len(rows) == 1, [
        (o.kind, o.closure_status, o.satisfaction_status) for o in rows]
    return rows[0]


def test_per_slot_guard_missing_slot_names_it():
    """任一声明槽世界零候选 → open + missing_artifact_evidence，notes 点名缺槽
    ——旧行为拿剩余槽冒充完整判据产实判（复现 §4.4：无任何一处检查逐槽贡献）。"""
    facts = [make_fact("F1", slot_id="ev.alpha", value=True,
                       value_type="boolean")]
    row = _req_row(_obls(_multi_slot_req_card(), facts))
    assert row.closure_status == "open"
    assert row.open_reason_code == "missing_artifact_evidence"
    assert "ev.beta" in (row.notes or "")
    assert row.satisfaction_status == "unknown"


def test_per_slot_guard_qualifier_filtered_empty_blocked():
    """有候选但限定符滤空 → blocked + qualifier_conflict（sapp6 410 条同形）。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR01", "sup.visit", roles=("evidence",),
                   qualifiers={"actor_role_key": "ri"}),
            _srole("SR02", "ver.test", roles=("evidence",)),
        ],
        obligation_graph={
            "nodes": [
                {"obligation_node_id": "N1", "node_kind": "obligation",
                 "actor": "ri", "action": "perform_inspection"},
                {"obligation_node_id": "N2", "node_kind": "obligation",
                 "actor": "ri", "action": "keep_records"},
            ]
        },
        evidence_requirements={
            "for_matching": [],
            "for_submission": [],
            "for_completion": [{
                "evidence_requirement_id": "RC.test.001.e01",
                "kind": "supervision_control_record",
                "required": True,
                "description": "site visit by ri + verification test",
                "artifact_ids": [],
                "slot_ref_ids": ["SR01", "SR02"],
                "measure_keys": [],
                "required_field_groups": [],
            }],
        },
    )
    facts = [
        # sup.visit 有事实但不带 actor_role_key ⇒ 滤空（世界/卡限定符不对齐）。
        make_fact("F1", slot_id="sup.visit", value=True, value_type="boolean"),
        make_fact("F2", slot_id="ver.test", value=True, value_type="boolean"),
    ]
    row = _req_row(_obls(card, facts))
    assert row.closure_status == "blocked"
    assert row.blocked_reason_code == "qualifier_conflict"
    assert "sup.visit" in (row.notes or "")
    assert row.satisfaction_status == "unknown"


def test_per_slot_guard_cross_slot_disagreement_blocked_not_verdict():
    """跨槽值不一致（载体 rank 不同）→ blocked/ambiguous_fact_binding。
    旧行为：合池后分级把高 rank 整槽剔除、拿残存槽出实判（复现 F 行 0026 决定性证据）。"""
    facts = [
        make_fact("F1", slot_id="ev.alpha", value=True, value_type="boolean",
                  carrier_type="building"),
        make_fact("F2", slot_id="ev.beta", value=False, value_type="boolean",
                  carrier_type="sidecar_entry"),
    ]
    row = _req_row(_obls(_multi_slot_req_card(), facts))
    assert row.closure_status == "blocked"
    assert row.blocked_reason_code == "ambiguous_fact_binding"
    assert row.satisfaction_status == "unknown"


def test_per_slot_guard_all_contribute_and_agree_merge_unchanged():
    """全部声明槽各有贡献且取值一致 → 进入合并判定（合并语义本刀不改）。"""
    facts = [
        make_fact("F1", slot_id="ev.alpha", value=True, value_type="boolean",
                  carrier_type="building"),
        make_fact("F2", slot_id="ev.beta", value=True, value_type="boolean",
                  carrier_type="sidecar_entry"),
    ]
    row = _req_row(_obls(_multi_slot_req_card(), facts))
    assert row.closure_status == "closed"
    assert row.satisfaction_status == "satisfied"
    assert {"F1", "F2"} <= set(row.evidence_fact_ids or [])


def test_per_slot_guard_slot_internal_conflict_blocked():
    """槽内值冲突 → blocked + ambiguous_fact_binding（槽内先于合并层查）。"""
    facts = [
        make_fact("F1", slot_id="ev.alpha", value=True, value_type="boolean"),
        make_fact("F1b", slot_id="ev.alpha", value=False, value_type="boolean"),
        make_fact("F2", slot_id="ev.beta", value=True, value_type="boolean"),
    ]
    row = _req_row(_obls(_multi_slot_req_card(), facts))
    assert row.closure_status == "blocked"
    assert row.blocked_reason_code == "ambiguous_fact_binding"
    assert "ev.alpha" in (row.notes or "")


# ===================================================================== #
# 🔴 生产口径主路径：门/闸产的 open 码在四格里**原样交回**
# （2026-08-07 官方线审核门必修 3）
#
# 为什么单列：replay50 与金丝雀**都是闸关口径**（`authorized_scope_selection=False`）
# 跑的，而**真批默认闸开**（`run_baseline_batch.py` `scope_selection=
# not args.no_authorized_scope_selection`）⇒ 生产口径下四格判定走的正是
# `_PROHIBITION_VALUE_OPEN_CODES` 白名单的「非取值类 open 码 → return None →
# 闸码由 opened 合并原样带出」这条分支，而首版 19 条测试**一条都没覆盖它**。
# 误改后果：楼级聚合待裁闸的原因码会被 `null_observed_value` 顶掉——
# **等于悄悄改掉待裁闸语义，且全绿**。
# ===================================================================== #
_GATE_CODE = "binding_requires_adjudication_authorization"


def _gated_facts(*, gate_on_prereq: bool):
    """把闸装在指定一侧：楼级聚合读数 ＋ 该绑定未登记 → `_unauthorized_aggregate_guard`。"""
    agg = {"aggregation": "building"}
    return [
        make_fact("F.rec", slot_id=REC, value=True, value_type="boolean",
                  qualifiers=agg if gate_on_prereq else None),
        make_fact("F.st", slot_id=ST, value=True, value_type="boolean",
                  carrier_type="building",
                  qualifiers=None if gate_on_prereq else agg),
    ]


def _gated_node_row(*, gate_on_prereq: bool):
    obls = run_closure(
        make_rule_slice([_prohib_card()]),
        make_fact_pack(_gated_facts(gate_on_prereq=gate_on_prereq)),
        authorized_scope_selection=True,      # ← 真批默认口径
    ).obligation_set.obligations
    return _node_row(obls)


def test_gate_code_on_prerequisite_returned_verbatim():
    """前件被楼级聚合待裁闸压住 → 节点 open 且**闸码逐字保留**，不许被取值码顶掉。"""
    row = _gated_node_row(gate_on_prereq=True)
    assert row.closure_status == "open"
    assert row.satisfaction_status == "unknown"
    # 🔴 逐字：一旦白名单被误改成「闸码也算取值不可判」，这里会变成 null_observed_value
    assert row.open_reason_code == _GATE_CODE
    assert row.open_reason_code != "null_observed_value"
    # 四格分支不许在闸码上留自己的注脚（说明确实是交回主流程，不是本分支判的）
    assert "prohibition_conditional: 被禁事实为真而解禁前件缺" not in (row.notes or "")


def test_gate_code_on_prohibited_fact_returned_verbatim():
    """被禁事实侧被同一闸压住 → 同样原样交回（`evid` 未 closed 即出四格射程）。"""
    row = _gated_node_row(gate_on_prereq=False)
    assert row.closure_status == "open"
    assert row.satisfaction_status == "unknown"
    assert row.open_reason_code == _GATE_CODE
    assert row.open_reason_code != "null_observed_value"
