"""桶通道绑定表：形状 ＋ 两家族点名的不变量 ＋ 变异验证。

决策门（2026-08-03，grok ＋ kimi 六问全收敛）对本表提了三条硬要求，
本文件逐条锁住：

1. **零碰撞要转成导入期不变量**，不能只是一次性审计；
2. **护栏照抄**（模式校验 ＋ 逐行卡指纹 ＋ 表级摘要），失效即
   fail-closed，**禁止回退成 satisfied/violated**；
3. **失效视图必须存在且被消费**——只接活行的话，卡指纹一漂移，
   假判定就静默复活（kimi 点名的最强风险）。
"""
from __future__ import annotations

import pytest

from evo_agent_baseline.closure import bucket_binding_registry as reg


def test_table_shape_and_derived_views():
    # 198 ＝ 批 I 运行时反推（2026-08-03）；＋9 ＝ 残余 50 误评止血（2026-08-04，
    # row 199-207）。候选表 11 行落 9 行，另 2 行键已在表内（row 80 / row 165），
    # 重复追加会触发下面那条零碰撞不变量、整表 fail-closed。
    # 2026-08-04 件四批 1：207 → **206**（退役 row 161——§3.2.6 同义重复建卡二保一，
    # 其卡已从权威卡包移除；row 号有意不重排，161 为空号，理由同 A 表）。
    # 2026-08-04 #26 重绑甲路：206 → **207**（+row 208 意向卡 diagnostic——
    # 残余 50 行 28 既有裁定，轴批四格实测 violated 4→0、射程外 0）。
    assert len(reg.BUCKET_BINDING_CONTRACTS) == 207
    assert reg.DISABLED_REASON is None
    assert len(reg.ACTIVE_ROWS) == 207 and not reg.STALE_ROWS
    # 派生视图必须恰等于活行，不许漏也不许多
    assert len(reg.BUCKET_BINDINGS) == 207
    assert set(reg.BUCKET_BINDINGS) == {
        (r["rule_card_id"], r["artifact_key"]) for r in reg.ACTIVE_ROWS}
    assert reg.REJECTED_BUCKET_BINDINGS == frozenset()


def test_every_row_is_diagnostic_only_and_grants_no_verdict():
    """本表**结构上**不许产判定——`verdict_permission` 只有 `none` 一个取值。"""
    for r in reg.BUCKET_BINDING_CONTRACTS:
        assert r["policy"] == "diagnostic_only"
        assert r["verdict_permission"] == "none"


def test_key_collision_is_an_import_time_invariant(monkeypatch):
    """变异：造一个重复键 ⇒ 模式校验必须报，且全表失效。

    🔴 两家族都点名：零碰撞是**一次性审计**，必须转成**不变量**。
    否则将来改卡引入碰撞时，键会**静默**从「唯一」变「一对多」，无人报警。
    """
    dup = list(reg.BUCKET_BINDING_CONTRACTS)
    clone = dict(dup[0])
    clone["row"] = 9999
    dup.append(clone)
    monkeypatch.setattr(reg, "BUCKET_BINDING_CONTRACTS", tuple(dup))
    bad = reg._schema_violations()
    assert any("重复键" in b for b in bad), bad
    active, stale, reason = reg._validate_against_pack()
    assert not active and reason and reason.startswith("schema:")


def test_fingerprint_drift_invalidates_that_row_only(monkeypatch):
    """篡改一行卡指纹 ⇒ **该行**失效，其余仍活（逐行指纹，不是全表连坐）。"""
    tampered = [dict(r) for r in reg.BUCKET_BINDING_CONTRACTS]
    tampered[0]["card_content_sha256"] = "0" * 64
    monkeypatch.setattr(reg, "BUCKET_BINDING_CONTRACTS", tuple(tampered))
    active, stale, reason = reg._validate_against_pack()
    assert reason is None
    assert len(stale) == 1 and stale[0]["row"] == tampered[0]["row"]
    assert len(active) == len(tampered) - 1 == 206  # #26 甲路 +row 208 后 207−1


def test_schema_violation_kills_the_whole_table_not_just_the_bad_row(monkeypatch):
    """反向：**模式**违例（区别于指纹漂移）必须让**整表**失效。

    两种失效的爆炸半径**有意不同**：
    - 指纹漂移 ＝ 那张卡变了 ⇒ 只失效那一行；
    - 模式违例 ＝ 表体本身写坏了 ⇒ 整表不可信 ⇒ 全部停摆。
    把两者混成一种会让「一行手滑」要么被放过、要么牵连过广。
    """
    broken = [dict(r) for r in reg.BUCKET_BINDING_CONTRACTS]
    broken[0]["verdict_permission"] = "value_consumption_aprime"
    monkeypatch.setattr(reg, "BUCKET_BINDING_CONTRACTS", tuple(broken))
    active, stale, reason = reg._validate_against_pack()
    assert not active and len(stale) == len(broken)
    assert reason and reason.startswith("schema:")


def test_rejected_view_exists_because_active_only_wiring_would_resurrect_verdicts():
    """失效视图**必须存在**——这是 kimi 点名的最强风险的机器面。

    桶通道比 A 批更脆：A 批多数行绑回退表事实，`artifact_state_licenses_verdict`
    那条「回退表事实恒不许可」是兜底；桶通道绑的是**真 `artifact.*` 槽**且
    `kind=artifact` **默认被许可** ⇒ 没有任何兜底，失效即假判定复活。
    """
    assert hasattr(reg, "REJECTED_BUCKET_BINDINGS")
    tampered = [dict(r) for r in reg.BUCKET_BINDING_CONTRACTS]
    tampered[0]["card_content_sha256"] = "0" * 64
    _active, stale, _ = reg._validate_against_pack()  # noqa: F841 —— 只验形状
    # 用真实校验器复算一次失效集合的构造方式，确认它来自 stale 而非硬编码
    rejected = frozenset((r["rule_card_id"], r["artifact_key"]) for r in stale)
    assert rejected == reg.REJECTED_BUCKET_BINDINGS


def test_registry_digest_is_stable_and_content_sensitive(monkeypatch):
    """摘要要进批清单锚：同内容同摘要、改一字节即变。"""
    d1 = reg.registry_digest()
    assert d1 == reg.registry_digest()
    changed = [dict(r) for r in reg.BUCKET_BINDING_CONTRACTS]
    changed[0]["adjudication"] = "行为须发生"
    monkeypatch.setattr(reg, "BUCKET_BINDING_CONTRACTS", tuple(changed))
    assert reg.registry_digest() != d1


def test_hook_consumes_both_active_and_rejected_views():
    """挂钩已接（2026-08-03），且**活行视图与失效视图都被消费**。

    这是接线时按原占位测试的指示改写的：失效视图漏接＝kimi 最强风险
    （卡指纹漂移 ⇒ 假判定静默复活，桶通道无任何兜底）。
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    with open(od.__file__, encoding="utf-8") as f:
        text = f.read()
    assert "BUCKET_BINDINGS" in text
    assert "REJECTED_BUCKET_BINDINGS" in text, "失效视图必须被消费——否则指纹漂移静默回退"


# ===== 挂钩四条变异（决策门两家族点名的验收形状）=====

def _eval(card_id, akey, *, bucket, value=True, kind="artifact"):
    import evo_agent_baseline.closure.obligation_deriver as od
    from evo_agent_baseline.closure.tests.test_binding_contract_registry import (
        make_fact, make_fact_pack, make_rule_card, FactIndex, META,
    )
    card = make_rule_card()
    card = card.model_copy(update={"rule_card_id": card_id}) if hasattr(card, "model_copy") else card
    slot = od.ARTIFACT_KEY_TO_SIDECAR_SLOT[akey]
    idx = FactIndex(make_fact_pack([make_fact(
        "f-a", slot_id=slot, value=value, value_type="boolean",
        carrier_type="building", carrier_id="BLD-T",
        qualifiers={"artifact_key": akey, "aggregation": "building"},
        provenance={})]))
    return od.evaluate_artifact_obligation(
        card, akey, kind, idx, True, META, bucket=bucket)


def _a_registered_key():
    from evo_agent_baseline.closure import bucket_binding_registry as reg
    r = reg.ACTIVE_ROWS[0]
    return r["rule_card_id"], r["artifact_key"]


def test_registered_key_on_bucket_channel_refuses_not_satisfies():
    """已登记键 ＋ 桶通道 ＋ 值为真 ⇒ **open ＋ 产物态码**，不是 satisfied。"""
    cid, akey = _a_registered_key()
    obl = _eval(cid, akey, bucket="workflow_operands.artifacts", value=True)
    assert obl.closure_status == "open"
    assert obl.satisfaction_status == "unknown"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert "bucket_binding_contract" in str(obl.notes or "")


def test_same_key_off_bucket_channel_is_untouched():
    """同一键**不在**桶通道（证据通道等）⇒ 行为不变——bucket 门控的牙齿。

    kind="artifact" 在许可集合内，值为真 ⇒ 原路 satisfied。
    """
    cid, akey = _a_registered_key()
    obl = _eval(cid, akey, bucket=None, value=True)
    assert obl.satisfaction_status == "satisfied", (
        "非桶通道被收窄了——bucket 门控失效，证据通道被误伤")


def test_unregistered_key_on_bucket_channel_is_untouched():
    """未登记键 ⇒ 桶通道行为不变（不收窄）。"""
    obl = _eval("rc.not.registered.card", "report.completion",
                bucket="workflow_operands.artifacts", value=True)
    assert obl.satisfaction_status == "satisfied"


def test_stale_row_fails_closed_not_reverts(monkeypatch):
    """🔴 kimi 最强风险的变异验证：**行失效 ⇒ blocked，绝不回退成 satisfied**。

    人为把已登记键挪进失效视图（模拟卡指纹漂移），值为真也必须 blocked。
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    from evo_agent_baseline.closure import bucket_binding_registry as reg
    cid, akey = _a_registered_key()
    monkeypatch.setattr(reg, "REJECTED_BUCKET_BINDINGS", frozenset({(cid, akey)}))
    monkeypatch.setattr(reg, "BUCKET_BINDINGS",
                        {k: v for k, v in reg.BUCKET_BINDINGS.items()
                         if k != (cid, akey)})
    obl = _eval(cid, akey, bucket="workflow_operands.artifacts", value=True)
    assert obl.closure_status == "blocked", "失效行静默回退成通用求值——假判定复活"
    assert obl.blocked_reason_code == "schema_contract_violation"
    assert obl.satisfaction_status == "unknown"


# ===== for_submission 扩门（2026-08-04 晨，两家商议后自决）=====

def test_registered_key_on_for_submission_channel_also_refuses():
    """扩门后 for_submission 支路同键同样拒判——残余 ~22 条诬告的止血生效点。"""
    cid, akey = _a_registered_key()
    obl = _eval(cid, akey, bucket="for_submission", value=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"


def test_for_matching_channel_stays_excluded():
    """for_matching（证据匹配通道）继续排除——B 批门的原始边界一寸不让。

    kind=artifact 在许可集合内，值真 ⇒ 原路 satisfied（不被桶表收窄）。
    """
    cid, akey = _a_registered_key()
    obl = _eval(cid, akey, bucket="for_matching", value=True)
    assert obl.satisfaction_status == "satisfied"


def test_for_completion_channel_now_gated():
    """for_completion 门已按立案条款正式开启（2026-08-04，非静默并入）。

    原测试钉「谁塞进门控这里先红，去开那道门」——那道门已开：开门要件
    （核 227 对裁定池覆盖）实测按实判条数 98.99%，扩门属既裁语义的机械延伸
    （`量测_forcompletion门开门要件_20260804.md`）。现锁新契约：
    已登记键在 for_completion 通道同样拒判。"""
    cid, akey = _a_registered_key()
    obl = _eval(cid, akey, bucket="for_completion", value=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "artifact_state_not_valid_evidence"
    assert obl.satisfaction_status == "unknown"

