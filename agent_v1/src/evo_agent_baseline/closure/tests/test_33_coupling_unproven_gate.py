# -*- coding: utf-8 -*-
"""#33 保护闸（耦合未证拒判）的**三臂变异对照**（2026-08-05）。

权威依据：`团队文档/我的笔记/决议_33处置_20260805.md` §一.1 ／
`重核准记录_33保护闸_20260805.md`。

闸的裁定：四根 reporting 轴（`reporting.artifact.{submitted,delivered,signed}`
＋ `reporting.record.submitted`）在世界侧 `conditional_inputs=[]`、独立伯努利
采样、与程序闸零耦合 ⇒ 「产物存在 ⇒ 事件发生」世界不保证 ⇒ 射程内（A 表
rows 105-126，22 行 / 20 卡）**在耦合未证前不得产 satisfied**，统一落
`open + evidence_event_coupling_unproven`。

## 为什么必须是三臂而不是一臂

单测「翻转行不产 satisfied」会在两处骗过自己：

- **桶通道臂**：`_bucket_axis_value_consumption` **不读** `true_exit_mode`、
  True 时曾硬编码 `closed/satisfied`。它今天缺省关（`c55_bucket_value_consumption`
  默认 False），所以只测缺省态会全绿——而**开关打开当天闸就被绕过**。
  故本臂**显式把开关打开**再测。（官方线商议 §2.3 点名的绕过面。）
- **解封反演臂**：只证「现在不产 satisfied」无法区分「闸生效了」与
  「这条路本来就死了」。故必须证明**同一套夹具、同一条事实、只把行级声明换成
  「耦合已证」形状 ⇒ satisfied 回来**。没有这一臂，闸的阳性对照缺失。
"""
from __future__ import annotations

import pytest

import evo_agent_baseline.closure.obligation_deriver as od
from evo_agent_baseline.closure import binding_contract_registry as reg
from evo_agent_baseline.closure import bucket_binding_registry as breg
from evo_agent_baseline.closure.fact_binding import FactIndex

from .fixtures import BUILDING_ID, make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R", "world_id": "W", "building_id": BUILDING_ID}

GATE_CODE = "evidence_event_coupling_unproven"
GATE_EXIT = f"open/{GATE_CODE}"


# ===================================================================== #
# 零、表面：翻转集就是「能产 satisfied 的值消费行」，不是前缀近似
# ===================================================================== #

def test_flip_set_is_22_rows_20_cards_by_machine_criterion():
    """🔴 翻转集按**本体定义**枚举，不按 `reporting.artifact.*` 前缀。

    决议 §一.1 的本体定义＝「能产 satisfied 的 value_consumption 行」。
    括号里给的操作化写法 `slot ∈ reporting.artifact.*` 是一次**前缀偶然**：
    它漏掉 `reporting.record.submitted`（rows 123-126）——那是**第三根 report 轴**，
    世界侧形状逐字段同构（`conditional_inputs=[]` / `conditional_formula=None` /
    带 `qualifier_axis_product` / 无条件 prevalence 0.84），
    且 `worldgen/registry.py` 行内注释自己写着「其证据力未裁，**属 #33**」。
    按前缀执行会少闸 4 行。冻结批实测佐证：22 行射程 436 条 satisfied，
    18 行射程 424 条，差 12 恰是 rows 123-126（详重核准记录 §一）。
    """
    gated = [r for r in reg.BINDING_CONTRACTS
             if reg.coupling_unproven_exit_code(r) is not None]
    assert sorted(r["row"] for r in gated) == list(range(105, 127))
    assert len({r["rule_card_id"] for r in gated}) == 20
    assert {r["slot_id"] for r in gated} == {
        "reporting.artifact.submitted", "reporting.artifact.delivered",
        "reporting.artifact.signed", "reporting.record.submitted",
    }
    # 前缀判据会漏 4 行——把这条差异钉死，防将来有人「简化」回前缀写法。
    by_prefix = [r for r in gated
                 if str(r["slot_id"]).startswith("reporting.artifact.")]
    assert len(by_prefix) == 18
    assert len(gated) - len(by_prefix) == 4


def test_gated_rows_are_diagnostic_and_carry_no_verdict_permission():
    for r in reg.BINDING_CONTRACTS:
        if reg.coupling_unproven_exit_code(r) is None:
            continue
        assert r["policy"] == "diagnostic_only", r["row"]
        assert r["verdict_permission"] == "none", r["row"]
        assert r["true_exit"] == r["false_exit"] == GATE_EXIT, r["row"]
        # 沿革留痕：解封时要翻回的真值出口模式。
        assert r["true_exit_mode"] == "contract_satisfied", r["row"]


def test_derived_view_matches_shared_predicate():
    assert reg.COUPLING_UNPROVEN_BINDINGS == frozenset(
        (r["rule_card_id"], r["slot_ref_id"]) for r in reg.ACTIVE_ROWS
        if reg.coupling_unproven_exit_code(r) is not None)
    # 闸与 A′ 互斥：被闸住的行绝不在值消费集合内。
    assert reg.COUPLING_UNPROVEN_BINDINGS & reg.VALUE_CONSUMPTION_BINDINGS \
        == frozenset()


def test_gate_predicate_refuses_half_declared_rows():
    """半边声明不成闸——只有一侧写本码时共享判据必须返回 None。

    （完整性由 `_schema_violations` 的「诊断行两出口必须相同」在导入期兜住；
    这里锁的是判据本身不许对残缺形状放行。）"""
    assert reg.coupling_unproven_exit_code(
        {"true_exit": GATE_EXIT, "false_exit": "open/artifact_state_not_valid_evidence"}
    ) is None
    assert reg.coupling_unproven_exit_code(
        {"true_exit": "closed/satisfied", "false_exit": GATE_EXIT}) is None
    assert reg.coupling_unproven_exit_code({}) is None
    assert reg.coupling_unproven_exit_code(None) is None


def test_schema_gate_rejects_gate_code_on_value_consumption_row(monkeypatch):
    """反向变异：把耦合未证出口写到值消费行上 ⇒ 模式违例（整表 fail-closed）。

    防的是「闸声明与政策分裂」——一行同时声称「据其判满足」与「耦合未证不判」。"""
    rows = [dict(r) for r in reg.BINDING_CONTRACTS]
    r37 = next(r for r in rows if r["row"] == 37)
    r37["true_exit"] = r37["false_exit"] = GATE_EXIT
    monkeypatch.setattr(reg, "BINDING_CONTRACTS", tuple(rows))
    bad = reg._schema_violations()
    assert any("耦合未证出口只许配 diagnostic_only" in b for b in bad), bad


def test_schema_gate_rejects_zombie_true_exit_mode(monkeypatch):
    """反向变异：诊断行带 `true_exit_mode` 却不在闸内 ⇒ 僵尸字段闸报违例。

    `true_exit_mode` 在诊断行上零运行时读者；留着而不被闸看住，正是本仓
    反复吃亏的「登记了没人消费」形状（`verdict_permission` 同病）。"""
    rows = [dict(r) for r in reg.BINDING_CONTRACTS]
    r38 = next(r for r in rows if r["row"] == 38)
    r38["true_exit_mode"] = "contract_satisfied"
    monkeypatch.setattr(reg, "BINDING_CONTRACTS", tuple(rows))
    bad = reg._schema_violations()
    assert any("僵尸字段" in b for b in bad), bad


# ===================================================================== #
# 一、A′ 臂：翻转行经 A′/诊断通道不产 satisfied
# ===================================================================== #

def _real_gated_row():
    """取一条**真实**翻转行（row 118，§2.1.3(o) 檢驗報告呈交建築事務監督）。

    刻意不用手搓的桩：闸的判据读的就是行级声明，用真行才能证明真表被闸住。"""
    return next(r for r in reg.BINDING_CONTRACTS if r["row"] == 118)


def _axis_fact(row, value, fid="f-axis", extra_quals=None):
    """按**真实批形状**造轴事实（2026-08-04 轴批实测的形②）：
    `carrier_type=sidecar_entry` ＋ `granularity=building` ＋ 无 `fragment_id`。
    首版夹具喂契约期望形（building+aggregation）导致 925 条形状失配没被测出来
    ——本夹具是那次教训的落点，别改回去。"""
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",") if "=" in kv}
    quals["granularity"] = "building"
    quals["carrier_domain"] = "artifact"
    quals.update(extra_quals or {})
    return make_fact(fid, slot_id=row["slot_id"], value=value,
                     value_type="boolean", carrier_type="sidecar_entry",
                     carrier_id="SCR-BLD-T", qualifiers=quals, provenance={})


def _wire_aprime(monkeypatch, card, row, *, gated=True):
    """把夹具卡接到一条真实授权行上。

    `gated=False` ＝**解封反演形**：同一行、同一事实，只把行级声明翻回
    「耦合已证」（值消费 + contract_satisfied），闸应放行。
    """
    key = (card.rule_card_id, "RC.t.c01.sr01")
    wired = dict(row)
    if gated:
        vc, diag = frozenset(), frozenset({key})
    else:
        wired.update({
            "policy": "value_consumption",
            "verdict_permission": "value_consumption_aprime",
            "true_exit": "closed/satisfied（耦合已证——解封反演臂）",
            "false_exit": "open/observed_false_without_violation_basis",
            "true_exit_mode": "contract_satisfied",
        })
        vc, diag = frozenset({key}), frozenset()
    monkeypatch.setattr(od, "BINDING_COARSE_SLOTS", frozenset({row["slot_id"]}))
    monkeypatch.setattr(od, "SLOT_ROLE_AUTHORIZED_BINDINGS", frozenset({key}))
    monkeypatch.setattr(od, "NODE_SLOT_AUTHORIZED_BINDINGS", frozenset({key}))
    monkeypatch.setattr(od, "VALUE_CONSUMPTION_AUTHORIZED_BINDINGS", vc)
    monkeypatch.setattr(od, "DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS", diag)
    monkeypatch.setattr(od, "SCOPE_PRECISE_AUTHORIZED", {key: wired})
    monkeypatch.setattr(
        reg, "SCOPE_PRECISE_BINDINGS",
        {**reg.SCOPE_PRECISE_BINDINGS, key: wired})
    return wired


def _slot_ref(row):
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",") if "=" in kv}
    return {"slot_ref_id": "RC.t.c01.sr01", "slot_id": row["slot_id"],
            "roles": ["evidence"], "required": True, "qualifiers": quals}


@pytest.mark.parametrize("value", [True, False])
def test_arm_aprime_gated_row_never_satisfies(monkeypatch, value):
    """🔴 A′ 臂：翻转行真值假值都落 `open/evidence_event_coupling_unproven`。

    **真值一侧是本闸的全部意义**——翻转前它走 `contract_satisfied` 直判满足
    （冻结批 `wave1_closing_seed401_20260804` 实测 436 条）。"""
    row = _real_gated_row()
    card = make_rule_card()
    _wire_aprime(monkeypatch, card, row, gated=True)
    idx = FactIndex(make_fact_pack([_axis_fact(row, value)]))
    obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                authorized_scope_selection=True)
    assert obl.satisfaction_status == "unknown"
    assert obl.closure_status == "open"
    assert obl.open_reason_code == GATE_CODE
    assert obl.evidence_fact_ids == ["f-axis"]      # 证据照旧落盘、可回查
    assert "#33 保护闸" in str(obl.notes or "")
    # 真假两侧同码 ⇒ notes 必须把观测到的真假写出来，否则消费者信息比翻转前更粗
    assert ("读数为真" if value else "读数为假") in str(obl.notes or "")


def test_arm_aprime_gate_holds_on_every_gated_row(monkeypatch):
    """参数化到**全部 22 行**：不许只测迭代到的第一行。"""
    for row in [r for r in reg.BINDING_CONTRACTS
                if reg.coupling_unproven_exit_code(r) is not None]:
        card = make_rule_card()
        mp = pytest.MonkeyPatch()
        try:
            _wire_aprime(mp, card, row, gated=True)
            idx = FactIndex(make_fact_pack([_axis_fact(row, True)]))
            obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                        authorized_scope_selection=True)
            assert obl.satisfaction_status == "unknown", row["row"]
            assert obl.open_reason_code == GATE_CODE, row["row"]
        finally:
            mp.undo()


def test_arm_aprime_bad_shape_still_gated_not_blocked(monkeypatch):
    """形状坏（**同值**两行同轴）**仍落闸码，不升格 blocked**。

    裁定是「这类读数现在一律不能据以判满足」，与读数形状无关；
    把有意拒判渲染成 `schema_contract_violation` 会让专业审查员读成「系统坏了」。
    形状观察写进 notes 供漂移排障。

    ⚠️ 夹具必须用**同值**两行：异值两行在到达合同终止器**之前**就被
    `status=="ambiguous"` 截成 `blocked/ambiguous_fact_binding`
    （`_evaluate_node_slot_binding` 里歧义检查先于终止器）——那条路测不到本闸。
    （首版夹具正是喂了异值，两测同时变红才发现顺序；一并锁进下面那条测试。）"""
    row = _real_gated_row()
    card = make_rule_card()
    _wire_aprime(monkeypatch, card, row, gated=True)
    idx = FactIndex(make_fact_pack([
        _axis_fact(row, True, fid="f-a"), _axis_fact(row, True, fid="f-b")]))
    obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                authorized_scope_selection=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == GATE_CODE
    assert "读数形状非预期" in str(obl.notes or "")


def test_arm_aprime_conflicting_rows_blocked_before_gate(monkeypatch):
    """异值多行在闸**之前**被歧义闸截住 ⇒ blocked，同样不产 satisfied。

    锁的是通道顺序：歧义 → 合同终止器 → A′。顺序反了会让「候选不唯一」
    被闸码盖住，消费者读到的原因就错了。"""
    row = _real_gated_row()
    card = make_rule_card()
    _wire_aprime(monkeypatch, card, row, gated=True)
    idx = FactIndex(make_fact_pack([
        _axis_fact(row, True, fid="f-a"), _axis_fact(row, False, fid="f-b")]))
    obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"
    assert obl.satisfaction_status == "unknown"


# ===================================================================== #
# 二、桶通道臂：把 c55 开关打开，翻转行仍不产 satisfied
# ===================================================================== #

def _bucket_eval(cid, akey, facts, kind="artifact", switch_on=True):
    card = make_rule_card()
    if hasattr(card, "model_copy"):
        card = card.model_copy(update={"rule_card_id": cid})
    idx = FactIndex(make_fact_pack(facts),
                    c55_bucket_value_consumption=switch_on)
    return od.evaluate_artifact_obligation(
        card, akey, kind, idx, True, META, bucket="workflow_operands.artifacts")


def _existence_fact(akey, value=True):
    slot = od.ARTIFACT_KEY_TO_SIDECAR_SLOT[akey]
    return make_fact("f-exist", slot_id=slot, value=value, value_type="boolean",
                     carrier_type="building", carrier_id="BLD-T",
                     qualifiers={"artifact_key": akey, "aggregation": "building"},
                     provenance={})


def _bucket_pairs():
    return sorted((cid, akey) for (cid, akey) in breg.C55_BUCKET_VALUE_CONSUMPTION
                  if akey in od.ARTIFACT_KEY_TO_SIDECAR_SLOT)


def test_arm_bucket_authorized_pairs_still_connect_not_rejected():
    """🔴 连接判据是**身份**不是政策：翻转后四个授权对仍连得上活行。

    若连接判据仍只接 `policy=="value_consumption"`，四对会全部落进
    `C55_BUCKET_VC_REJECTED` ⇒ 求值器出 `blocked/schema_contract_violation`
    ＋文案「授权失效/缺失」——**把一次经决策门裁定的有意收紧，在产物里
    伪装成系统故障**。"""
    assert len(breg.C55_BUCKET_VALUE_CONSUMPTION) == 4
    assert breg.C55_BUCKET_VC_REJECTED == frozenset()
    assert sorted(r["row"] for r in breg.C55_BUCKET_VALUE_CONSUMPTION.values()) \
        == [118, 119, 124, 125]
    for r in breg.C55_BUCKET_VALUE_CONSUMPTION.values():
        assert reg.coupling_unproven_exit_code(r) == GATE_CODE, r["row"]


@pytest.mark.parametrize("value", [True, False])
def test_arm_bucket_switch_on_gate_still_holds(value):
    """🔴 桶通道臂：**显式打开** `c55_bucket_value_consumption` 再测。

    这一格是官方线点名的绕过面——`_bucket_axis_value_consumption` 不读
    `true_exit_mode`、True 时曾硬编码 `closed/satisfied`。只闸 A′ 一侧的话，
    本测在开关打开当天变红。"""
    pairs = _bucket_pairs()
    assert pairs, "四个授权对的 artifact_key 全不在存在轴映射表——夹具无法搭"
    for cid, akey in pairs:
        row = breg.C55_BUCKET_VALUE_CONSUMPTION[(cid, akey)]
        obl = _bucket_eval(cid, akey,
                           [_existence_fact(akey), _axis_fact(row, value)],
                           switch_on=True)
        assert obl.satisfaction_status == "unknown", (cid, akey, value)
        assert obl.closure_status == "open", (cid, akey, value)
        assert obl.open_reason_code == GATE_CODE, (cid, akey, value)
        assert "#33 保护闸" in str(obl.notes or "")


def test_arm_bucket_axis_absent_still_falls_back_untouched():
    """轴未供给 ⇒ 闸之前就返回 None，落回既有拒判老路（旧池零扰动不变）。"""
    cid, akey = _bucket_pairs()[0]
    obl = _bucket_eval(cid, akey, [_existence_fact(akey)], switch_on=True)
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert "#33 保护闸" not in str(obl.notes or "")


# ===================================================================== #
# 三、解封反演臂：耦合已证的行形状 ⇒ 闸放行
# ===================================================================== #

@pytest.mark.parametrize("value,expect", [
    (True, ("closed", "satisfied", None)),
    (False, ("open", "unknown", "observed_false_without_violation_basis")),
])
def test_arm_unseal_counterfactual_lets_verdict_through(monkeypatch, value, expect):
    """🔴 解封反演臂（**先写死预期，再验**）。

    同一条真实行、同一条真实形状的事实，**只把行级声明翻回「耦合已证」**
    （`policy=value_consumption` + `true_exit_mode=contract_satisfied`）：
    - 真 ⇒ `closed/satisfied`
    - 假 ⇒ `open/observed_false_without_violation_basis`（绝不产 violated）

    这一臂证明的是**闸在起作用**，而不是「这条路本来就死了」。缺了它，
    上面两臂全绿也可能只是别的原因让 satisfied 出不来。
    """
    want_closure, want_sat, want_code = expect
    row = _real_gated_row()
    card = make_rule_card()
    _wire_aprime(monkeypatch, card, row, gated=False)
    idx = FactIndex(make_fact_pack([_axis_fact(row, value)]))
    obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                authorized_scope_selection=True)
    assert obl.closure_status == want_closure
    assert obl.satisfaction_status == want_sat
    assert obl.open_reason_code == want_code
    assert obl.satisfaction_status != "violated"
    assert "#33 保护闸" not in str(obl.notes or "")


def test_arm_unseal_counterfactual_restores_shape_guards(monkeypatch):
    """解封后**形状闸必须回来**：同值两行同轴 ⇒ blocked/schema_contract_violation。

    闸期内形状违例只记 notes 不升格（见 `test_arm_aprime_bad_shape_still_gated`），
    故形状闸的覆盖靠本测维持——不许因为闸落了就让形状判据失去测试。
    ⚠️ 同样必须用**同值**两行（异值先被歧义闸截走，测不到形状闸）。"""
    row = _real_gated_row()
    card = make_rule_card()
    _wire_aprime(monkeypatch, card, row, gated=False)
    idx = FactIndex(make_fact_pack([
        _axis_fact(row, True, fid="f-a"), _axis_fact(row, True, fid="f-b")]))
    obl = od.evaluate_slot_role(card, _slot_ref(row), idx, True, META,
                                authorized_scope_selection=True)
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"


def test_arm_unseal_counterfactual_bucket_channel(monkeypatch):
    """解封反演臂的桶通道半边：翻回值消费声明 ⇒ 桶通道恢复判满足。"""
    cid, akey = _bucket_pairs()[0]
    row = dict(breg.C55_BUCKET_VALUE_CONSUMPTION[(cid, akey)])
    row.update({"policy": "value_consumption",
                "true_exit": "closed/satisfied（耦合已证——解封反演臂）",
                "false_exit": "open/observed_false_without_violation_basis"})
    monkeypatch.setattr(breg, "C55_BUCKET_VALUE_CONSUMPTION", {(cid, akey): row})
    obl = _bucket_eval(cid, akey, [_existence_fact(akey), _axis_fact(row, True)],
                       switch_on=True)
    assert obl.satisfaction_status == "satisfied"
    assert "c55 桶消费" in str(obl.notes or "")


# ===================================================================== #
# 四、消费者面：新码进四处文案，且文案对真假两侧都为真
# ===================================================================== #

def test_new_code_registered_in_all_consumer_surfaces():
    """十处登记面（2026-08-06 审核门必修 1 由九处扩到十处）。

    第十处 `od._NODE_OPEN_REASON_RANK` 正是漏登被抓的那张表：node 通道多子绑定
    合并按它取最强 open 码，漏登 ⇒ `.get(code, -1)` ⇒ 闸码被任何已登记码静默盖掉。
    """
    from evo_agent_baseline.contracts import OpenReasonCode, UnknownCauseCode
    from typing import get_args
    from evo_agent_baseline.agent import report_contract_v4 as rc4
    from evo_agent_baseline.agent import report_writer as rw
    from evo_agent_baseline.closure import unknown_attribution as ua
    from evo_agent_baseline.closure import identity_v2 as idv2

    assert GATE_CODE in get_args(OpenReasonCode)
    assert GATE_CODE in get_args(UnknownCauseCode)
    assert GATE_CODE in rc4.REASON_CODE_SPEC
    assert GATE_CODE in rc4._OPEN_REASONS
    assert GATE_CODE in rw._UNKNOWN_CAUSE_LABELS
    assert GATE_CODE in rw._UNKNOWN_CAUSE_ORDER
    assert GATE_CODE in ua._PASSTHROUGH_CAUSE_CODES
    assert GATE_CODE in ua._PASSTHROUGH_EXPLANATIONS
    assert GATE_CODE in idv2.OPEN_REASON_ORDER
    assert GATE_CODE in od._NODE_OPEN_REASON_RANK   # 十处之十（必修 1 补登）


def test_open_reason_rank_tables_agree_in_relative_direction():
    """🔴 必修 1 的防再漂闸：两张 open 码序表对同码对的相对方向必须一致。

    病灶形状（2026-08-06 官方审核门抓出）：`identity_v2.OPEN_REASON_ORDER` 给
    `evidence_event_coupling_unproven` 记 13（最高），而
    `obligation_deriver._NODE_OPEN_REASON_RANK` 漏登 ⇒ `.get(code, -1)` 取 −1，
    比表内最低的 `null_observed_value`(0) 还低——同一个码在两张合并序表里
    **方向相反**，多子绑定节点上闸码会被任何已登记 open 码静默盖掉
    （冻结批可见风险面 31 条）。

    锁三条：
    ① 键集相等——新增 open 码必须双表同登（前四个新增码 9-12 的既有先例）；
    ② 本闸码在两表都是严格最大（「取新最大值」先例）；
    ③ 任意同码对的相对方向（大小关系的符号）两表一致。已知例外冻结为
       #33 之前既有的一组三对——`missing_measurement` / `missing_artifact_evidence`
       / `missing_time_anchor` 三码在两表的内部次序恰好相反
       （node 表 4/3/2 ＝ measurement > artifact_evidence > time_anchor；
       identity 表 2/3/4 反向）。修它会改既有 merge 结果，属另案；
       本清单只许随真实修复收缩，新增分歧即红。
    """
    from evo_agent_baseline.closure import identity_v2 as idv2

    node = od._NODE_OPEN_REASON_RANK
    ident = idv2.OPEN_REASON_ORDER
    # ① 双表同登
    assert set(node) == set(ident), set(node) ^ set(ident)
    # ② 本闸码两表都是严格最大
    assert node[GATE_CODE] == max(node.values())
    assert ident[GATE_CODE] == max(ident.values())
    assert sum(1 for v in node.values() if v == node[GATE_CODE]) == 1
    assert sum(1 for v in ident.values() if v == ident[GATE_CODE]) == 1
    # ③ 同码对相对方向一致（冻结的既有例外之外零分歧）
    _KNOWN_PREEXISTING_DISAGREEMENTS = frozenset({
        frozenset({"missing_measurement", "missing_artifact_evidence"}),
        frozenset({"missing_measurement", "missing_time_anchor"}),
        frozenset({"missing_artifact_evidence", "missing_time_anchor"}),
    })
    codes = sorted(node)
    disagreements = set()
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            sign_node = (node[a] > node[b]) - (node[a] < node[b])
            sign_ident = (ident[a] > ident[b]) - (ident[a] < ident[b])
            if sign_node != sign_ident:
                disagreements.add(frozenset({a, b}))
    assert disagreements <= _KNOWN_PREEXISTING_DISAGREEMENTS, (
        "两张 open 码序表出现新的方向分歧（会让一张表的胜者在另一张表被盖掉）："
        f"{sorted(sorted(p) for p in disagreements - _KNOWN_PREEXISTING_DISAGREEMENTS)}"
    )


def test_consumer_copy_stays_within_adjudicated_boundary():
    """🔴 文案边界三条（照 `diagnostic_binding_not_valid_evidence` 的教训写）。

    ①不许写成「不可核验」——越界（耦合建起来就能判）；
    ②不许写成「文件不存在」——真值侧读数恰恰为真，那是事实错误；
    ③本码覆盖真假两侧，故文案里不许出现只对单侧为真的断言。
    """
    from evo_agent_baseline.agent import report_contract_v4 as rc4
    from evo_agent_baseline.agent import report_writer as rw
    from evo_agent_baseline.closure import unknown_attribution as ua

    texts = [
        rc4.REASON_CODE_SPEC[GATE_CODE]["zh"],
        rw._UNKNOWN_CAUSE_LABELS[GATE_CODE],
        ua._PASSTHROUGH_EXPLANATIONS[GATE_CODE],
    ]
    for t in texts:
        assert "不可核验" not in t
        assert "永久" not in t
        assert "文件不存在" not in t and "没有该文件" not in t
        # 只对真值侧为真的断言（「查到了文件」）不许出现
        assert "查到了文件" not in t
    # 该说的必须说到：事件语义 ＋ 交专业人员核实
    joined = "".join(texts)
    assert "事件" in joined
    assert "核实" in joined
    assert rc4.REASON_CODE_SPEC[GATE_CODE]["analysis"] == "MODELING_GAP"
    assert "MANUAL_VERIFY" in rc4.REASON_CODE_SPEC[GATE_CODE]["actions"]
