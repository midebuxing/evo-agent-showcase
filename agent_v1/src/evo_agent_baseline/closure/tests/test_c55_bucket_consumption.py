# -*- coding: utf-8 -*-
"""c55 桶通道值消费钩（工单 #20 第二步）的行为守卫。

授权面＝4 对（裁定 kind=artifact 判乙/甲日数 且已在桶表内：单元 26/44/53/54）。
六格：真→satisfied ／ 假→observed_false ／ 轴缺席→落回拒判老路（旧池零扰动）／
形状坏→blocked ／ 授权行失效→blocked ／ 未授权对→拒判不受影响（作用域不外溢）。
"""
from __future__ import annotations

import evo_agent_baseline.closure.obligation_deriver as od
from evo_agent_baseline.closure import bucket_binding_registry as breg
from evo_agent_baseline.closure.tests.test_binding_contract_registry import (
    META, FactIndex, make_fact, make_fact_pack, make_rule_card,
)


def _eligible_pairs():
    """全部可搭夹具的授权对（qwen 发现⑧：不许 frozenset 任取——排序定序）。"""
    return sorted(
        (cid, akey) for (cid, akey) in breg.C55_BUCKET_VALUE_CONSUMPTION
        if akey in od.ARTIFACT_KEY_TO_SIDECAR_SLOT)


def _authorized_pair():
    pairs = _eligible_pairs()
    assert pairs, "4 个授权对的 artifact_key 全不在存在轴映射表——夹具无法搭"
    cid, akey = pairs[0]
    return cid, akey, breg.C55_BUCKET_VALUE_CONSUMPTION[(cid, akey)]


def _axis_fact(row, value, fid="f-axis", extra_quals=None):
    """轴事实按**真实批形状**造（2026-08-04 轴批实测）：
    carrier=sidecar_entry ＋ granularity=building ＋ carrier_domain=artifact，
    **没有** aggregation 标记。首版夹具喂了契约期望形（building+aggregation），
    925 条 blocked/SCV 的形状失配因此没被测出来——本夹具就是那次教训的落点。"""
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",")}
    quals["granularity"] = "building"
    quals["carrier_domain"] = "artifact"
    quals.update(extra_quals or {})
    return make_fact(fid, slot_id=row["slot_id"], value=value,
                     value_type="boolean", carrier_type="sidecar_entry",
                     carrier_id="SCR-BLD-T", qualifiers=quals, provenance={})


def _eval(cid, akey, facts, kind="artifact", switch_on=True):
    """缺省开开关（方案甲下生产缺省是关——行为测试要测钩本体，显式开；
    缺省关的逐位等价由 test_switch_off_keeps_refusal 单独锁）。"""
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


# ===================================================================== #
# 🔴 2026-08-05 #33 保护闸落表：四个授权对**全部**落在翻转集内
# （rows 118/119/124/125），故本文件原来锁「真→satisfied ／ 假→observed_false」
# 的三格已被闸取代，改锁「两侧都落闸码」。
#
# ⚠️ 老语义**没有失去覆盖**：`test_33_coupling_unproven_gate.py` 的
# **解封反演臂**（`test_arm_unseal_counterfactual_bucket_channel`）把行级声明
# 翻回值消费后，桶通道必须恢复判满足——那是这三格的阳性对照。
# 若将来 #33 根治解封，把下面三格改回原样即可（原断言逐字留在注释里）。
#   原：真 ⇒ closed/satisfied ＋ notes 含「c55 桶消费」
#   原：假 ⇒ open/observed_false_without_violation_basis ＋ notes 含「不得读作」
#   原：形状坏（两行）⇒ blocked/schema_contract_violation
# ===================================================================== #

def test_axis_true_is_gated_by_33_not_satisfied():
    """真值一侧是 #33 闸的全部意义：翻转前这里判 satisfied（冻结批 436 条）。"""
    cid, akey, row = _authorized_pair()
    obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(row, True)])
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "evidence_event_coupling_unproven"
    assert "#33 保护闸" in str(obl.notes or "")
    assert "读数为真" in str(obl.notes or "")


def test_axis_false_also_gated_same_code_but_note_keeps_the_side():
    """假值一侧同码——诊断行两出口必须相同（丁④）。

    🔴 这是本次实施相对官方线「假值一侧不动」建议的**已登记偏离**
    （`重核准记录_33保护闸_20260805.md` §四.2）：翻 policy 就必然共用一个码。
    诚实代价＝假值侧信息变粗；补偿＝notes 必须把真假写出来，
    否则消费者读到的比翻转前更少。本断言就是那条补偿的锁。"""
    cid, akey, row = _authorized_pair()
    obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(row, False)])
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "evidence_event_coupling_unproven"
    assert "读数为假" in str(obl.notes or "")


def test_axis_absent_falls_back_to_refusal_old_pools_unperturbed():
    """轴事实缺席（旧池常态）⇒ 落回既有拒判——本钩对旧池必须零扰动。"""
    cid, akey, _row = _authorized_pair()
    obl = _eval(cid, akey, [_existence_fact(akey)])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert "c55 桶消费" not in str(obl.notes or "")


def test_axis_shape_violation_still_gated_shape_recorded_in_notes():
    """两行同轴读数（形状坏）⇒ **仍落闸码**，形状观察进 notes。

    #33 的裁定是「这类读数现在一律不能据以判满足」，与读数形状无关；
    把有意拒判渲染成 `schema_contract_violation` 会让专业审查员读成「系统坏了」。
    形状闸本身的覆盖由解封反演臂维持
    （`test_33_coupling_unproven_gate::test_arm_unseal_counterfactual_restores_shape_guards`）。"""
    cid, akey, row = _authorized_pair()
    obl = _eval(cid, akey, [
        _existence_fact(akey),
        _axis_fact(row, True, fid="f-axis-1"),
        _axis_fact(row, False, fid="f-axis-2"),
    ])
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "evidence_event_coupling_unproven"
    assert "读数形状非预期" in str(obl.notes or "")


def test_rejected_authorization_blocks_not_reverts(monkeypatch):
    """授权在案但行失效 ⇒ blocked——不许把「授权失效」伪装成「从未授权」。"""
    cid, akey, row = _authorized_pair()
    monkeypatch.setattr(breg, "C55_BUCKET_VC_REJECTED",
                        frozenset({(cid, akey)}))
    monkeypatch.setattr(breg, "C55_BUCKET_VALUE_CONSUMPTION",
                        {k: v for k, v in breg.C55_BUCKET_VALUE_CONSUMPTION.items()
                         if k != (cid, akey)})
    obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(row, True)])
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert "授权" in str(obl.notes or "")


def test_fragment_level_sidecar_row_is_rejected_shape():
    """碎片级 sidecar 行（带 fragment_id）不是楼级读数——形状闸必须拒。

    这是扩形（sidecar_entry+granularity=building 形②）的防过宽负测：
    审核工单点名「sidecar 分行会不会有非楼级行混入」，答案靠这道闸。"""
    cid, akey, row = _authorized_pair()
    obl = _eval(cid, akey, [
        _existence_fact(akey),
        _axis_fact(row, True, extra_quals={"fragment_id": "FRG-BLD-T-X-01"}),
    ])
    # 命中授权对但唯一候选是碎片行 ⇒ #33 闸下仍不产 satisfied（首要不变量），
    # 形状违例改由 notes 可见化（2026-08-05 起；原断言＝blocked/SCV）。
    # **绝不**把碎片行当楼级读数消费成 satisfied——那才是扩形过宽。
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "evidence_event_coupling_unproven"
    assert "读数形状非预期" in str(obl.notes or "")
    assert obl.satisfaction_status == "unknown"


def test_legacy_building_aggregate_shape_still_recognized():
    """形①（building+aggregation=building）仍是合法形——row 37 先例的形不许被扩形挤掉。

    #33 闸下判定结果是 open+闸码（不再 satisfied），故本测改锁**形状被认出来**
    ——notes 里出现真假读数（而非「形状非预期」）即证明形① 仍走共享判据
    `_is_building_axis_reading` 的第一支。原断言 `satisfaction_status=="satisfied"`
    的阳性对照在解封反演臂。"""
    cid, akey, row = _authorized_pair()
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",")}
    quals["aggregation"] = "building"
    legacy = make_fact("f-axis-legacy", slot_id=row["slot_id"], value=True,
                       value_type="boolean", carrier_type="building",
                       carrier_id="BLD-T", qualifiers=quals, provenance={})
    obl = _eval(cid, akey, [_existence_fact(akey), legacy])
    assert obl.open_reason_code == "evidence_event_coupling_unproven"
    assert "读数为真" in str(obl.notes or "")
    assert "读数形状非预期" not in str(obl.notes or "")


def test_unauthorized_bucket_pair_still_refuses_even_with_axis_fact():
    """作用域不外溢：桶表内但**不在 4 对授权面**的键，即便世界有轴读数
    也维持拒判——9 对重定基单元不许被本钩顺手转化。"""
    pair = next(k for k in breg.BUCKET_BINDINGS
                if k not in breg.C55_BUCKET_VC_AUTHORIZED_PAIRS
                and k[1] in od.ARTIFACT_KEY_TO_SIDECAR_SLOT)
    cid, akey = pair
    fake_row = {"slot_id": "reporting.artifact.submitted",
                "qualifier_axis": f"artifact_key={akey}"}
    obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(fake_row, True)])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert obl.satisfaction_status == "unknown"


def test_switch_off_keeps_refusal_bitwise():
    """🔴 方案甲核心：开关缺省关时，即便轴读数为真也维持既有拒判——
    钩缺省不生效＝逐位等价于不落钩（揭膜源不触发）。"""
    cid, akey, row = _authorized_pair()
    obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(row, True)],
                switch_on=False)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert "c55 桶消费" not in str(obl.notes or "")


def test_factindex_switch_defaults_off():
    """FactIndex 缺省不带开关——生产批不显式开就是关（批配置下发才开）。"""
    idx = FactIndex(make_fact_pack([]))
    assert idx.c55_bucket_value_consumption is False


def test_mapping_frozen_four_pairs_to_expected_rows():
    """映射冻结（kimi 发现三）：授权面恰 4 对、各连预期行、拒绝侧空。"""
    m = breg.C55_BUCKET_VALUE_CONSUMPTION
    assert len(m) == 4 and breg.C55_BUCKET_VC_REJECTED == frozenset()
    rows = sorted(r["row"] for r in m.values())
    assert rows == [118, 119, 124, 125]


def test_all_eligible_pairs_are_gated_none_converts_to_satisfied():
    """4 对参数化行为测（kimi 发现三后半）：不许只测迭代到的第一对。

    2026-08-05：原断言 `satisfaction_status == "satisfied"`；四对全部落在
    #33 翻转集内（rows 118/119/124/125）⇒ 现在四对都必须被闸住。"""
    pairs = _eligible_pairs()
    assert len(pairs) >= 2, f"可搭夹具的授权对过少：{pairs}"
    for cid, akey in pairs:
        row = breg.C55_BUCKET_VALUE_CONSUMPTION[(cid, akey)]
        obl = _eval(cid, akey, [_existence_fact(akey), _axis_fact(row, True)])
        assert obl.satisfaction_status == "unknown", (cid, akey)
        assert obl.open_reason_code == "evidence_event_coupling_unproven", (cid, akey)


def test_registry_digest_sensitive_to_pairs_only_change(monkeypatch):
    """grok 补审发现③：只改授权四对、不动表体，摘要也必须变（锚敏感轴专测）。"""
    d1 = breg.registry_digest()
    monkeypatch.setattr(
        breg, "C55_BUCKET_VC_AUTHORIZED_PAIRS",
        frozenset(list(breg.C55_BUCKET_VC_AUTHORIZED_PAIRS)[:-1]))
    assert breg.registry_digest() != d1
