# -*- coding: utf-8 -*-
"""消费通道 c55 批（row 105-126）的守卫。

裁定档案：裁定_消费55_01-28 / 29-55；决议_消费55多引用与角色悬案_20260804.md。
锁四件事：①批形状与覆盖面 ②artifact_key 轴强制（模式①教训）
③四同文组自检（工单第 4 条：落地后不同解＝接线错）④单元 36 悬案不许静默落表。
"""
from __future__ import annotations

import copy

from evo_agent_baseline.closure import binding_contract_registry as reg

# 🔴 2026-08-05 #33 保护闸：选取判据从 `policy=="value_consumption"` 改成
# **row 号区间**（`决议_33处置_20260805.md` §一.1 ／ `重核准记录_33保护闸_20260805.md`）。
# 翻转后这 22 行的 policy 是 `diagnostic_only`，按老判据本文件会**选到空集**、
# 一半测试静默空过（另一半 IndexError）。row 区间是这批的稳定身份——
# 表注释明写「row 号有意不重排」，且 `test_granularity_declaration` 已把它冻在
# `range(105,127)`。
C55_ROWS = [r for r in reg.BINDING_CONTRACTS if 105 <= r["row"] <= 126]

_GATE_EXIT = f"open/{reg.COUPLING_UNPROVEN_REASON_CODE}"


def test_c55_batch_shape():
    """22 行、全活、全在 reporting 轴；**出口语义已由 #33 保护闸翻转**。

    沿革（保留，防旧结论复活）：落表时（2026-08-04）这批照 row 37 先例走
    `closed/satisfied` ＋ `observed_false_without_violation_basis` ＋
    `value_consumption_aprime`。2026-08-05 #33 裁定「耦合未证前不得产 satisfied」，
    四字段整批翻转；`true_exit_mode` 保留原值作解封留痕。
    """
    assert len(C55_ROWS) == 22
    active_keys = {(r["rule_card_id"], r["slot_ref_id"]) for r in reg.ACTIVE_ROWS}
    for r in C55_ROWS:
        assert (r["rule_card_id"], r["slot_ref_id"]) in active_keys, \
            f"row{r['row']} 未通过卡指纹校验——落了等于没落"
        assert r["slot_id"].startswith("reporting."), r["row"]
        assert r["policy"] == "diagnostic_only", r["row"]
        assert r["true_exit"] == r["false_exit"] == _GATE_EXIT, r["row"]
        assert r["verdict_permission"] == "none", r["row"]
        # 解封留痕：翻回时真值出口该是什么。
        assert r["true_exit_mode"] == "contract_satisfied", r["row"]


def test_c55_artifact_key_axis_is_schema_enforced():
    """变异：去掉任一行的 artifact_key 轴 ⇒ 模式校验拒（工单验收第 2 条）。

    直接调 _schema_violations 的判据函数面——把一行的轴改成 None 后
    必须出现违例条目；这锁的是「校验真的会拒」，不是「现表恰好都带」。

    🔴 2026-08-05：#33 翻转后这批的 policy 变成 diagnostic_only。若校验判据不
    同步扩到闸内行，本条强制项的适用人群会变成**空集**——判据筛不到任何人
    等于没有，而解封时缺轴就是过宽授权。故本测试改喂**闸内行**，
    正是那条扩展的反向对照。
    """
    rows = copy.deepcopy(reg.BINDING_CONTRACTS)
    victim = next(r for r in rows if 105 <= r["row"] <= 126)
    assert reg.coupling_unproven_exit_code(victim) is not None
    victim["qualifier_axis"] = None
    import evo_agent_baseline.closure.binding_contract_registry as mod
    orig = mod.BINDING_CONTRACTS
    try:
        mod.BINDING_CONTRACTS = rows
        bad = mod._schema_violations()
    finally:
        mod.BINDING_CONTRACTS = orig
    assert any("artifact_key" in b and f"row{victim['row']}" in b for b in bad), bad


def test_four_identical_groups_resolve_identically():
    """四同文组（单元 37-40 与 52-55）落地后必须同解——不同解＝接线错。

    同组各卡的条文逐字相同（檢驗日誌呈交屋宇署），故行的实质语义字段
    （槽、轴、聚合、政策、出口、许可）必须逐字一致；卡指纹当然各不相同。
    组成员按裁定文档模式三：37-40＝§3.6.2(A)(d) 同文四卡，52-55＝同形四卡。
    """
    slot = "reporting.record.submitted"
    group = [r for r in C55_ROWS if r["slot_id"] == slot]
    # 八个四同文单元＝**同四张卡的两种 kind**（37-40 evidence ＋ 52-55 artifact），
    # 表键不含 kind ⇒ 去重后恰 4 行、每行承载 2 单元（首跑我按 8 行断言，
    # 被实测纠正——单元数与行数不同层，别混）。
    assert len(group) == 4, [r["row"] for r in group]
    semantic = {(r["aggregator"], tuple(r["allowed_paths"]), r["policy"],
                 r["true_exit"], r["false_exit"], r["verdict_permission"])
                for r in group}
    assert len(semantic) == 1, f"四同文组出现不同解：{semantic}"
    # 轴串**有意分开断言**。沿革（保留，防旧结论复活）：
    # 首跑时四行并不同形——row 124（s3_3_2_a_c.c02）卡侧引用**缺** `actor_role_key`，
    # 另三行是 `actor_role_key=ba`。当时本注释写着「届时本断言红，
    # **去修卡而不是改断言**」——2026-08-05 的 #29 正是那个场景，且**确实是去修了卡**：
    #   ① `ba` 是错译：五条平行款（§3.3.2(A)(c) / §3.4.2(A)(b) / §3.5.2(A)(c) /
    #      §3.6.2(A)(d) / §3.7.1(d)）中文正文**逐字同文**，均写「呈交**屋宇署**」
    #      ＝ Buildings Department ＝ `bd`，不是建築事務監督（`ba`）；
    #   ② row 124 的缺键**补上了**（`actor_role_key=bd`），四行由此真正同形。
    # ⇒ 本断言从「三 ba ＋ 一缺键」改成「四行全 bd」，是卡与世界两侧同批换掉之后的
    #    **新事实**，不是把断言迁就实现。世界侧 `reporting.record.submitted` 轴积
    #    同批加出 bd 格——⚠️ 不是 1→1 替换：该组合被 10 张卡消费（射程外 6 张合法 ba），
    #    甲案并存（轴积 1→2，ba 格保留），详 `复核_29甲案_*_20260805.md`。
    #    本断言只看 A 表四行的轴串，与 ba 格存续无关。
    # 🔴 纪律不变：若将来这条再红，仍然先问「是不是卡错了」，再考虑改断言。
    axes = sorted(r["qualifier_axis"] for r in group)
    assert axes == [
        "actor_role_key=bd,artifact_key=record.inspection_log",
        "actor_role_key=bd,artifact_key=record.inspection_log",
        "actor_role_key=bd,artifact_key=record.inspection_log",
        "actor_role_key=bd,artifact_key=record.inspection_log",
    ], axes


def test_unit36_role_case_not_silently_landed():
    """单元 36（s2_1_3_o_documents_to_person）挂 §2.1.3(o)/(p) 角色矛盾案，
    未裁前不得有任何值消费行——收件人键缺失会错吃 rc 送达读数
    （决议_消费55多引用与角色悬案_20260804.md）。角色案了结后落表时，
    连同本测试一起按新裁定更新。"""
    card = ("rc.mbis.reporting.ri_procedural_notifications.ri.submit."
            "s2_1_3_o_documents_to_person_within_7d.c01")
    assert not [r for r in C55_ROWS if r["rule_card_id"] == card]


def test_c55_keys_flow_into_coupling_unproven_view():
    """派生视图接线：#33 翻转后 22 个键全部进 `COUPLING_UNPROVEN_BINDINGS`，
    且**全部退出** `VALUE_CONSUMPTION_BINDINGS`（后者回到 row 37 一键）。

    （原名 `…flow_into_value_consumption_view`，2026-08-05 随翻转改名——
    留着旧名字会让「这批还在值消费视图里」这个已被推翻的结论继续读起来成立。）"""
    keys = {(r["rule_card_id"], r["slot_ref_id"]) for r in C55_ROWS}
    assert keys == set(reg.COUPLING_UNPROVEN_BINDINGS)
    assert keys & reg.VALUE_CONSUMPTION_BINDINGS == set()
    assert len(reg.VALUE_CONSUMPTION_BINDINGS) == 1


def _c55_key_and_row():
    """取一个 c55 键（排序定序，qwen 发现⑧同款纪律）。"""
    rows = sorted(C55_ROWS, key=lambda r: r["row"])
    r = rows[0]
    return (r["rule_card_id"], r["slot_ref_id"]), r


def _axis_fact_for(row, value):
    from evo_agent_baseline.closure.tests.test_binding_contract_registry import (
        make_fact,
    )
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",")}
    quals["granularity"] = "building"
    quals["carrier_domain"] = "artifact"
    return make_fact("f-ax", slot_id=row["slot_id"], value=value,
                     value_type="boolean", carrier_type="sidecar_entry",
                     carrier_id="SCR-BLD-T", qualifiers=quals, provenance={})


def test_c55_rows_no_longer_enter_the_aprime_contract():
    """🔴 #33 翻转后 c55 行**不再进 A′ 值消费契约**——该函数对它们恒返 None。

    取代原 `test_aprime_contract_{true,false}_returns_…_for_c55_rows` 两测：
    那两条锁的是「真 ⇒ 契约直判 satisfied ／ 假 ⇒ observed_false」，
    正是 #33 裁定要拆掉的两个出口（冻结批 `wave1_closing_seed401_20260804`
    实测 436 条 satisfied 出自这条路）。行为面的新守卫在
    `test_33_coupling_unproven_gate.py` 三臂里，含**解封反演臂**——
    翻回值消费声明后这两个出口必须原样回来，故老语义没有失去覆盖。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    from evo_agent_baseline.closure.tests.test_binding_contract_registry import (
        META, make_rule_card,
    )
    key, row = _c55_key_and_row()
    card = make_rule_card()
    if hasattr(card, "model_copy"):
        card = card.model_copy(update={"rule_card_id": key[0]})
    for value in (True, False):
        ob = od._value_consumption_contract(
            card, META, "evidence", {}, [_axis_fact_for(row, value)],
            use_scope=True, binding_key=key)
        assert ob is None, value      # 不在 A′ 射程 ⇒ 该函数第一行就返 None


def test_row37_true_exit_mode_stays_caller_path():
    """row 37 先例语义不变：true_exit_mode=caller_path，真值仍返 None 走现状路径。"""
    row37 = [r for r in reg.BINDING_CONTRACTS if r["row"] == 37][0]
    assert row37["true_exit_mode"] == "caller_path"


def test_row37_true_returns_none_caller_path_behavior():
    """row 37 行为锁（glm/grok 补审）：caller_path 真值仍返 None 走现状路径——
    契约分叉不许挤掉先例语义（字段测试之外的行为面）。"""
    import evo_agent_baseline.closure.obligation_deriver as od
    from evo_agent_baseline.closure.tests.test_binding_contract_registry import (
        META, make_fact, make_rule_card,
    )
    row37 = [r for r in reg.BINDING_CONTRACTS if r["row"] == 37][0]
    key = (row37["rule_card_id"], row37["slot_ref_id"])
    f = make_fact("f-37", slot_id=row37["slot_id"], value=True,
                  value_type="boolean", carrier_type="building",
                  carrier_id="BLD-T",
                  qualifiers={"aggregation": "building"}, provenance={})
    card = make_rule_card()
    if hasattr(card, "model_copy"):
        card = card.model_copy(update={"rule_card_id": key[0]})
    assert od._value_consumption_contract(
        card, META, "evidence", {}, [f], use_scope=True, binding_key=key) is None
