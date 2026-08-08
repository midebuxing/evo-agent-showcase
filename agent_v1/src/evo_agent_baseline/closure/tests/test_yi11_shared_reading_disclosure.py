# -*- coding: utf-8 -*-
"""乙11 三重保护的机器面（2026-08-05，`决议_33处置_20260805.md` §一.2）。

**案情**：`duration.delivery.repair_revision_proposal` 一条量同时承载
§2.1.3(p)（送交「該名由他人代為進行訂明修葺的人」）与 §2.1.3(q)（送交註冊承建商）
两个收件人——两条的**起算事件是同一个**（向建築事務監督呈交之日）、天数也相同
（同日＝0 日），世界侧只建了一条量。⇒ 「交了承建商没交业主」建模不出来，两支必然同判。

**为什么不闸掉**（与 #33 的性质区分，这是决议 §一.2 的承重论证）：

|  | #33 | 乙11 |
|---|---|---|
| 病 | 证据力**为零**的事实在解除义务 | 证据力**成立但分辨率不足** |
| 判定 | 无依据 ⇒ **必须闸掉** | 有依据 ⇒ **闸掉就是丢掉有依据的判定** |
| 处置 | 保护闸落 open | 保留判定 ＋ 结果层披露 |

**为什么不拆槽**（两种拆法都被驳回）：
- 拆法甲（两槽共用一锚）：同（作用域,锚）两条候选 ⇒ `_bind_deadline_fact` 落
  `blocked/ambiguous_fact_binding`，把该组现有确定判定全数打成 0、比不拆还差
  （冻结批 `wave1_closing_seed401_20260804` 实测该组确定判定 **12 条、全在 (q) 腿**
  ——旧记「60 条」已被审核门必修 3 证伪，勿再引）；
- 拆法乙（两槽两锚）：卡上 `recipients` 与 `deadlines` 是两个**无关联数组**，
  没有把某条期限系到某个收件人的结构 ⇒ **只改世界侧无效**，须先扩卡 schema，
  另加改两张卡 + 全量重建指纹 + 重算桶表 row 199 + 改三处硬编码常量。
  且要先定一个本体问题（同一起算事件能不能有两个锚名）。挂波次三。

**本文件锁的是三重保护里机器可查的那两重**（第三重＝预注册防重复计数，
落 `实施记录_33保护闸_20260805.md` 的预注册表，不在代码面）。
"""
from __future__ import annotations

import functools
import json

import pytest

import evo_agent_baseline.closure.obligation_deriver as od
from evo_agent_baseline.agent import report_writer as rw
from evo_agent_baseline.closure.fact_binding import FactIndex

from .fixtures import BUILDING_ID, make_fact, make_fact_pack, make_rule_card

CARD_P = ("rc.mbis.reporting.ri_procedural_notifications.ri.submit."
          "s2_1_3_p_revised_proposal_to_person_same_day.c01")
CARD_Q = ("rc.mbis.repair.prescribed_repair_inputs.ri.deliver."
          "s2_1_3_q_revised_proposal_to_rc_same_day.c01")


# ===================================================================== #
# 保护一：披露登记面
# ===================================================================== #

def test_both_legs_are_registered_for_disclosure():
    """两卡都必须在披露面上——只登记一条等于只披露一半。"""
    for cid in (CARD_P, CARD_Q):
        reg = rw.shared_reading_disclosure_for(cid)
        assert reg is not None, cid
        assert reg["group"] == "yi11_repair_revision_same_day"
    # 两条互指对方，不许自指（自指会让读者以为只有一条义务）
    assert "§2.1.3(q)" in rw.shared_reading_disclosure_for(CARD_P)["peer"]
    assert "§2.1.3(p)" in rw.shared_reading_disclosure_for(CARD_Q)["peer"]


def test_registered_cards_exist_in_the_authoritative_pack():
    """🔴 登记的卡号必须真在权威卡包里——卡号笔误会让披露永不触发，
    而「永不触发」在产物里长得跟「没这个问题」一模一样。"""
    import json
    from evo_agent_baseline.rulecard_assets import DEFAULT_AUTHORITATIVE_BUNDLE_PATH
    # `DEFAULT_AUTHORITATIVE_BUNDLE_PATH` 已经指到 rule_cards.json 本体（非目录）。
    pack = json.loads(DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8"))
    ids = {c["rule_card_id"] for c in pack["cards"]}
    for cid in rw._SHARED_READING_DISCLOSURES:
        assert cid in ids, f"披露登记引用了卡包里不存在的卡：{cid}"


def test_disclosure_group_has_text_and_stays_within_boundary():
    """措辞边界：披露的是**分辨率**，不是可信度。

    不许写成「判定不可信 / 系统未能判定 / 不可核验」——那会把一条**有依据**
    的判定说成无依据，是另一个方向的失真（与 #33 闸码的边界正好相反，别互抄）。"""
    for group in {r["group"] for r in rw._SHARED_READING_DISCLOSURES.values()}:
        text = rw._SHARED_READING_GROUP_TEXT[group]
        assert text
        for forbidden in ("不可信", "不可核验", "系统未能判定", "无法判定"):
            assert forbidden not in text, (group, forbidden)
        assert "无法区分" in text and "分别" in text


# ===================================================================== #
# 保护二：同源 `evidence_fact_ids` 契约（咬生产求值路径）
# ===================================================================== #
#
# 2026-08-06 审核门必修 2 **整体重写**：原版 `test_two_legs_must_share_identical_
# evidence_fact_ids` 只比较测试自己造的两个桩对象——两个属性都是测试写死的
# 字面量，两条断言在任何实现下恒真，零行生产代码参与（「生产者→消费者接口
# 只测生产者自身等于没测」的更极端版本：连生产者都没测）。已废弃。
#
# 现版三层，全部咬真实资产或真实求值器：
#   ① 权威卡包层——两卡的期限声明必须仍是「同一锚点、同一 relation」：
#      有人拆锚/拆槽而不走波次三流程，这里先红；
#   ② 生产求值层——真实 `evaluate_deadline` 对两腿实跑，`evidence_fact_ids`
#      必须绑到同一条事实；同一条读数 ⇒ 两支必然同判（披露文案的机器面）；
#   ③ 反向臂——锚点被拆开时证据必须分叉：若生产绑定器短路成「不看本条期限
#      自己的锚点、任取一条」（2026-07-27 `facts[0]` 病灶形状），本臂当场红。

ANCHOR = "repair.revision_proposal.submitted_to_ba"
SHARED_SLOT = "duration.delivery.repair_revision_proposal"
META = {"run_id": "R", "world_id": "W", "building_id": BUILDING_ID}


@functools.lru_cache(maxsize=None)
def _real_deadlines():
    """从权威卡包实取两卡的期限声明（不手抄——卡包漂移时测试要跟着红）。"""
    from evo_agent_baseline.rulecard_assets import DEFAULT_AUTHORITATIVE_BUNDLE_PATH
    pack = json.loads(DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8"))
    by_id = {c["rule_card_id"]: c for c in pack["cards"]}
    out = {}
    for cid in (CARD_P, CARD_Q):
        deadlines = (by_id[cid].get("workflow_operands") or {}).get("deadlines") or []
        assert len(deadlines) == 1, (cid, deadlines)
        out[cid] = deadlines[0]
    return out


def _card(cid):
    card = make_rule_card()
    return card.model_copy(update={"rule_card_id": cid}) \
        if hasattr(card, "model_copy") else card


def _duration_fact(fid, value, anchor=ANCHOR):
    """按世界侧 sidecar duration 行形状造读数：provenance 回写锚点
    （`_bind_deadline_fact` 级 0 读的就是生产者自己的这条登记）。"""
    return make_fact(fid, slot_id=SHARED_SLOT, value=value, value_type="number",
                     carrier_type="sidecar_entry", carrier_id="SCR-BLD-Y",
                     qualifiers={"granularity": "building"},
                     provenance={"time_anchor_key": anchor})


def test_authoritative_pack_declares_one_shared_anchor_for_both_legs():
    """① 卡包层：两腿在权威卡包里就是同一锚点、同一 relation。

    这是「两支必然同判」的结构性根据；拆锚（拆法乙）不走波次三流程直接改卡包，
    本测先红——同源性从机器可查变不可查的第一步就被拦住。"""
    dls = _real_deadlines()
    assert dls[CARD_P]["relation"] == dls[CARD_Q]["relation"] == "same_day_as"
    assert dls[CARD_P]["time_anchor_key"] \
        == dls[CARD_Q]["time_anchor_key"] == ANCHOR


@pytest.mark.parametrize("value,want", [
    (0, ("closed", "satisfied")),
    (1, ("closed", "violated")),
])
def test_two_legs_bind_the_same_fact_in_production_path(value, want):
    """🔴 ② 生产求值层：真实 `evaluate_deadline` 下两腿 `evidence_fact_ids` 同源。

    同一条读数进真实求值器，两腿必须绑到**同一条** fact 并给出**相同**判定
    ——披露文案写的「必然同判」在生产路径上机器可查。预期先写死再验
    （same_day_as ⇒ 已歷时长==0 判 satisfied、非 0 判 violated）。"""
    fact = _duration_fact("f-shared", value)
    idx = FactIndex(make_fact_pack([fact]))
    dls = _real_deadlines()
    obls = [
        od.evaluate_deadline(_card(cid), dict(dls[cid]), idx, True, META)
        for cid in (CARD_P, CARD_Q)
    ]
    for o in obls:
        assert o.evidence_fact_ids == ["f-shared"]
        assert (o.closure_status, o.satisfaction_status) == want
    assert obls[0].evidence_fact_ids == obls[1].evidence_fact_ids
    assert obls[0].satisfaction_status == obls[1].satisfaction_status


def test_split_anchors_diverge_evidence_in_production_path():
    """🔴 ③ 反向臂：锚点拆开 ⇒ 证据必须分叉、判定可以不同。

    这一臂锁判据的区分度（原版桩测正是死在没有它咬生产代码）：
    - 生产绑定器若短路成「不看本条期限自己的锚点、任取一条」
      （2026-07-27 全批 225/225 塌缩到同一条事实的病灶形状），
      两腿会绑到同一条事实 ⇒ 本臂的分叉断言当场红；
    - 它同时证明②里的「同源」是锚点同一的**结果**而不是测试夹具的恒真：
      同一套夹具、只把 (q) 腿锚点换名，同源就消失。"""
    split_anchor = ANCHOR + ".split_for_contract_arm"
    dls = _real_deadlines()
    dq = dict(dls[CARD_Q])
    dq["time_anchor_key"] = split_anchor
    idx = FactIndex(make_fact_pack([
        _duration_fact("f-p", 0),
        _duration_fact("f-q", 1, anchor=split_anchor),
    ]))
    p = od.evaluate_deadline(_card(CARD_P), dict(dls[CARD_P]), idx, True, META)
    q = od.evaluate_deadline(_card(CARD_Q), dq, idx, True, META)
    assert p.evidence_fact_ids == ["f-p"]
    assert q.evidence_fact_ids == ["f-q"]
    assert p.evidence_fact_ids != q.evidence_fact_ids
    assert (p.satisfaction_status, q.satisfaction_status) \
        == ("satisfied", "violated")


def test_same_anchor_two_readings_blocks_both_legs_identically():
    """同锚两条候选 ⇒ 两腿一起 `blocked/ambiguous_fact_binding`（拒绝任取）。

    这是拆法甲（两槽共用一锚）被驳回的机器面：拆完同（作用域,锚）两条候选，
    该组现有确定判定全数变 blocked，比不拆还差（文件头案情表）。"""
    idx = FactIndex(make_fact_pack([
        _duration_fact("f-a", 0), _duration_fact("f-b", 0),
    ]))
    dls = _real_deadlines()
    for cid in (CARD_P, CARD_Q):
        o = od.evaluate_deadline(_card(cid), dict(dls[cid]), idx, True, META)
        assert o.closure_status == "blocked", cid
        assert o.blocked_reason_code == "ambiguous_fact_binding", cid


# —— 渲染层桩（只喂 `render_shared_reading_disclosure_section`，它按属性读；
#    保护二的同源契约不再用桩，见上）——

def _mk(oid, card, fact_ids):
    class _Ob:
        obligation_id = oid
        source_rule_card_id = card
        satisfaction_status = "satisfied"
        evidence_fact_ids = fact_ids
    return _Ob()


def test_disclosure_section_renders_both_legs_and_says_verify_separately():
    obs = [_mk("o-p", CARD_P, ["f1"]), _mk("o-q", CARD_Q, ["f1"])]
    lines = rw.render_shared_reading_disclosure_section(
        obs, {"o-p": "O-0001", "o-q": "O-0002"})
    body = "\n".join(lines)
    assert rw._SHARED_READING_SECTION_TITLE in body
    assert "O-0001" in body and "O-0002" in body
    assert CARD_P in body and CARD_Q in body
    # 给专业人员的行动项必须在场
    assert "分别" in body and "核实" in body
    # 判定**保留**——不许把当前判定藏起来
    assert "satisfied" in body


def test_disclosure_section_is_empty_when_cards_absent():
    """未命中登记卡 ⇒ 不占版面（消费者轴：别给没关系的读者加噪声）。"""
    assert rw.render_shared_reading_disclosure_section(
        [_mk("o-x", "rc.mbis.other.card.c01", ["f9"])], {}) == []
    assert rw.render_shared_reading_disclosure_section([], {}) == []


def test_disclosure_renders_only_the_legs_present_in_this_run():
    """只出现一条腿时也要披露（另一条可能因适用性未生成）——
    但清单里只列在场的那条，不许凭登记表编一条本次不存在的义务。"""
    lines = rw.render_shared_reading_disclosure_section(
        [_mk("o-p", CARD_P, ["f1"])], {"o-p": "O-0001"})
    body = "\n".join(lines)
    assert body
    assert CARD_P in body
    assert f"- [O" in body and CARD_Q not in body.split("——")[0]
