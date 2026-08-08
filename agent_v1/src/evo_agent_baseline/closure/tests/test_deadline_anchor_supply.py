"""期限锚供给案（2026-08-05 决议）——判定侧验收断言 B1/B2/B3/B4/B5。

权威依据：`团队文档/我的笔记/决议_期限锚_20260805.md`。

## 本文件锁的是什么

1. **B1/B2（R1，同日语义反转）**：`evaluate_deadline` 的 `same_day_as` 分支原本走
   `_canon_truthy(observed)`。世界侧承载「同日送交」的是**已歷日数**（0 日＝合规），
   而 `_canon_truthy(0.0) is False` / `_canon_truthy(1.0) is True` ⇒
   合规判 violated、违规判 satisfied，**恰好相反**。
   现在没发作只因绑定先失败落 `missing_time_anchor`；**补供给即发作**。
   ⇒ 改判据为卡侧已登记的 `== 0` 数值比较（浮点/整数同形）。
   本文件的 B1/B2 用例在修前**必须红**（红先行，决议 §四.4）。

2. **B3（provenance 优先绑定 + 锚点回写）**：绑定必须先按
   `fact.provenance["time_anchor_key"] == deadline.time_anchor_key` 匹配；
   E1 实验实测（`实验_期限锚E1最小实验_20260805.md` §四墙③）——不这样做，
   `repair.prescribed.{started,completed}` 两个锚点经别名表归一后必然先命中
   **布尔闸槽**，`return facts[0]` 让第 3 级量表通道永不可达，
   共 156 条义务（603 的 25.9%）**任何纯供给动作都救不回**。
   同时钉死碰撞策略：同（作用域,锚）0 条→诚实 miss；恰 1 条→用；
   >1 条→`ambiguous_fact_binding`，**禁止 `facts[0]` 任取**（2026-07-27 病灶形状）。

3. **B4（丙类三锚禁供）**：`appointment.representative.supervision.made` /
   `investigation.detailed.commencement` / `repair.prescribed.started` 三锚
   **本单不供**（决议 §一.2）。禁供名单落成可被测试引用的模块级常量
   `FORBIDDEN_DEADLINE_ANCHOR_SUPPLY`，不靠文字纪律。

4. **B5（正对照）**：`inspection.prescribed.completed` 的 within-7-day 链路双向
   ——5 天 → satisfied、30 天 → violated，证明「锚点事实供上 ⇒ 确定判定」端到端通。
   ⚠️ 该锚点本身属挂起的 #5（决议 §一.5），本用例只用它当**机制正对照**，
   不代表本单给它供给。

B6（每（楼,锚）楼级行恰 1 行）是世界侧断言，落在
`workflow_engine/worldgen/tests/test_deadline_anchor_emission.py`。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    FORBIDDEN_DEADLINE_ANCHOR_SUPPLY,
    _bind_deadline_fact,
    evaluate_deadline,
)
from evo_agent_baseline.closure.validator import _normalize_alias_map

from .fixtures import BUILDING_ID, RUN_ID, WORLD_ID, make_fact, make_fact_pack, make_rule_card

_PACK_DIR = (
    pathlib.Path(__file__).resolve().parents[4]
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
)

_META = {"run_id": RUN_ID, "world_id": WORLD_ID, "building_id": BUILDING_ID}


def _load_json(name: str):
    return json.loads((_PACK_DIR / name).read_text(encoding="utf-8"))


def _alias_maps():
    mapping = _load_json("projection_runtime_mapping_v1.json")
    return (
        _normalize_alias_map(mapping.get("slot_aliases") or {}),
        _normalize_alias_map(mapping.get("measure_aliases") or {}),
    )


def _index(facts) -> FactIndex:
    slot_aliases, measure_aliases = _alias_maps()
    return FactIndex(
        make_fact_pack(list(facts)),
        slot_aliases=slot_aliases,
        measure_aliases=measure_aliases,
    )


def _anchored_fact(fact_id, anchor, value, *, slot_id="duration.x", qualifiers=None):
    """一条带 provenance 锚点回写的 sidecar duration 数值事实（世界侧供给形状）。"""
    return make_fact(
        fact_id,
        slot_id=slot_id,
        measure_key=slot_id,
        value=value,
        value_type="number",
        unit="day",
        carrier_type="sidecar_entry",
        qualifiers=qualifiers or {},
        provenance={"carrier_label": "SidecarEntry", "time_anchor_key": anchor},
    )


def _eval(deadline, facts):
    return evaluate_deadline(
        make_rule_card(), deadline, _index(facts), True, dict(_META)
    )


# --------------------------------------------------------------------- #
# B1 / B2：same_day_as 走 == 0 数值比较（浮点/整数同形）
# --------------------------------------------------------------------- #
_SAME_DAY_DL = {
    "deadline_id": "D-same-day",
    "relation": "same_day_as",
    "time_anchor_key": "repair.completion_report.submitted_to_ba",
}


@pytest.mark.parametrize("zero", [0, 0.0])
def test_b1_same_day_zero_is_satisfied(zero):
    """0 日送达＝同日＝合规。整数 0 与浮点 0.0 必须同形 satisfied。

    修前：`_canon_truthy(0)` / `_canon_truthy(0.0)` 都是 False → violated（诬告合规者）。
    """
    obl = _eval(
        _SAME_DAY_DL,
        [_anchored_fact("F0", _SAME_DAY_DL["time_anchor_key"], zero)],
    )
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == "satisfied", (
        f"observed={zero!r}（同日送达）必须 satisfied，实得 {obl.satisfaction_status}"
    )
    assert obl.comparator_result is True
    assert obl.operator == "=="


@pytest.mark.parametrize("late", [1, 1.0, 2, 3.0])
def test_b1_same_day_nonzero_is_violated(late):
    """次日及以后送达＝违规。

    修前：`_canon_truthy(1.0) is True` → satisfied（放过违规者）；
          `_canon_truthy(2.0) is None` → open/missing_time_anchor（该判而不判）。
    """
    obl = _eval(
        _SAME_DAY_DL,
        [_anchored_fact("F1", _SAME_DAY_DL["time_anchor_key"], late)],
    )
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == "violated", (
        f"observed={late!r}（非同日）必须 violated，实得 {obl.satisfaction_status}"
    )
    assert obl.comparator_result is False


def test_b1_same_day_boolean_is_not_a_verdict():
    """布尔值不再被当成同日判据——`same_day_as` 只吃数值时长。

    修前：布尔 True 走 truthy 通道判 satisfied，而世界侧根本没有「是否同日」这个布尔，
    那条通道只会吃到别的槽误绑进来的门状态 ⇒ 结构性错判。
    """
    fact = make_fact(
        "FB",
        slot_id="duration.x",
        measure_key="duration.x",
        value=True,
        value_type="boolean",
        carrier_type="sidecar_entry",
        provenance={"time_anchor_key": _SAME_DAY_DL["time_anchor_key"]},
    )
    obl = _eval(_SAME_DAY_DL, [fact])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "missing_time_anchor"


# --------------------------------------------------------------------- #
# B3：provenance 优先绑定 + 碰撞策略
# --------------------------------------------------------------------- #
def test_b3_provenance_channel_beats_alias_bridged_boolean_gate():
    """E1 墙③：锚名经别名表指向布尔闸槽时，provenance 通道必须先命中数值事实。

    `repair.prescribed.completed` --别名--> `procedure.repair.prescribed.completed`
    （世界侧是布尔门状态）。槽通道 `return facts[0]` 会先吃到那条布尔，
    量表通道永不可达 ⇒ 93 条义务任何供给都救不回。
    """
    gate = make_fact(
        "FG",
        slot_id="procedure.repair.prescribed.completed",
        measure_key="procedure.repair.prescribed.completed",
        value=True,
        value_type="boolean",
        carrier_type="sidecar_entry",
    )
    anchored = _anchored_fact(
        "FD",
        "repair.prescribed.completed",
        9.0,
        slot_id="duration.delivery.deadline.to_ba",
    )
    bound, status = _bind_deadline_fact(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 14,
            "time_anchor_key": "repair.prescribed.completed",
        },
        _index([gate, anchored]),
    )
    assert status is None
    assert bound is not None
    assert bound.fact_id == "FD", (
        f"provenance 通道未优先：绑到了 {bound.fact_id}（{bound.slot_id}）"
    )


def test_b3_zero_anchored_facts_is_honest_miss():
    """同（作用域,锚）0 条 → 诚实落 missing_time_anchor，不许退化到任取。"""
    obl = _eval(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 7,
            "time_anchor_key": "appointment.ri.made",
        },
        [_anchored_fact("F", "role.ri.terminated", 3.0)],
    )
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "missing_time_anchor"


def test_b3_multiple_anchored_facts_refuse_to_pick():
    """同（作用域,锚）>1 条 → `ambiguous_fact_binding`，禁止 `facts[0]`。

    2026-07-27 病灶的形状就是「多候选任取第一条」。碰撞必须外显。
    """
    obl = _eval(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 7,
            "time_anchor_key": "appointment.ri.made",
        },
        [
            _anchored_fact("FA", "appointment.ri.made", 3.0, qualifiers={"fragment_id": "FRG-A"}),
            _anchored_fact("FB", "appointment.ri.made", 20.0, qualifiers={"fragment_id": "FRG-B"}),
        ],
    )
    assert obl.closure_status == "blocked"
    assert obl.blocked_reason_code == "ambiguous_fact_binding"


def test_b3_bound_fact_carries_the_anchor_back():
    """锚点回写断言：绑上的事实自己必须声明本条 deadline 的锚点。"""
    anchor = "role.supervision_team.changed"
    obl = _eval(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 7,
            "time_anchor_key": anchor,
        },
        [_anchored_fact("F", anchor, 2.0)],
    )
    assert obl.evidence_fact_ids == ["F"]
    assert obl.satisfaction_status == "satisfied"


# --------------------------------------------------------------------- #
# B4：丙类三锚禁供（按锚点分组的诚实断言）
# --------------------------------------------------------------------- #
def test_b4_forbidden_anchor_list_is_exactly_the_three_adjudicated():
    """禁供名单是结构，不是文字纪律。三锚一个不多一个不少。"""
    assert set(FORBIDDEN_DEADLINE_ANCHOR_SUPPLY) == {
        "appointment.representative.supervision.made",
        "investigation.detailed.commencement",
        "repair.prescribed.started",
    }


def test_b4_forbidden_anchors_are_real_registry_anchors():
    """名单里的三条必须是锚点册里的真锚点（防手滑打错字导致禁供失效）。"""
    registry = _load_json("time_anchor_registry_v1.json")
    known = {a["time_anchor_key"] for a in registry["time_anchors"]}
    for anchor in FORBIDDEN_DEADLINE_ANCHOR_SUPPLY:
        assert anchor in known, f"禁供锚 {anchor!r} 不在锚点册里"


# 「世界侧注册表零声明丙类锚」的静态断言在
# `workflow_engine/worldgen/tests/test_deadline_anchor_emission.py::
#  test_c4_forbidden_anchors_are_not_declared_world_side`（同一张表、同一字段、
# 同一谓词——本文件早先的同名用例是同一面测了两遍，且跨包 import 违反
# 分层独立契约 layer-independence，2026-08-08 提交时被 import-linter 拦下后删除；
# 覆盖零损失，判定侧真正的闸是下面的求值器用例）。
@pytest.mark.parametrize("anchor", sorted(FORBIDDEN_DEADLINE_ANCHOR_SUPPLY))
def test_b4_forbidden_anchors_stay_unknown(anchor):
    """丙类锚点即使误供带锚 duration 事实，也不许产出确定判定。

    ⚠️ 判据边界（诚实）：闸堵的是**本单新开的 provenance 供给通道**，
    不是既有 slot/measure 老通道——堵老通道会改动现存 159 条丙类义务的
    `evidence_fact_ids` 与 notes（#15 今天经别名桥绑着一条布尔门状态行），
    与「不注入锚点事实时全链零扰动」的病原回归判据冲突。
    ⚠️ 措辞订正（official 审核 M3②，2026-08-05）：先前这里写「世界侧零声明由
    本文件的世界侧读表用例（已删，见上方注释——跨包 import 违反分层契约）与
    `worldgen/tests/test_deadline_anchor_emission.py` **双向**钉死」——**那不是双向**。
    那两条读的是**同一张注册表、同一个 `rule_card_threshold.time_anchor_key` 字段、
    同一个谓词**，是同一面测了两遍——判定侧那遍已删（分层契约），现只留世界侧一条。
    真正的两面是：**判定侧＝本用例**（求值器闸：误供带锚事实也不出确定判定）
    ＋ **世界侧＝`test_c4_forbidden_anchors_are_not_declared_world_side` 静态断言**（注册表零声明）。
    本用例的反向对照是 `test_b4_forbidden_gate_is_the_only_difference`
    （防「provenance 通道整个不工作」廉价通过）。
    """
    facts = [_anchored_fact("F", anchor, 3.0)]
    for relation, offset in (("before", 7), ("before", None), ("within", 7)):
        obl = _eval(
            {
                "deadline_id": "D1",
                "relation": relation,
                "offset_value": offset,
                "time_anchor_key": anchor,
            },
            facts,
        )
        assert obl.satisfaction_status == "unknown", (
            f"丙类锚 {anchor!r}（relation={relation}）产出了确定判定 "
            f"{obl.satisfaction_status}——禁供闸失效"
        )


def test_b4_forbidden_gate_is_the_only_difference():
    """反向对照：同样形状的事实，换成**非**丙类锚点就必须能判。

    没有这条，上面那组断言可能靠「provenance 通道整个不工作」廉价通过。
    """
    allowed = "appointment.ri.made"
    assert allowed not in FORBIDDEN_DEADLINE_ANCHOR_SUPPLY
    obl = _eval(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 7,
            "time_anchor_key": allowed,
        },
        [_anchored_fact("F", allowed, 3.0)],
    )
    assert obl.satisfaction_status == "satisfied"


# --------------------------------------------------------------------- #
# B5：正对照——within-7-day 链路双向
# --------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected", [(5.0, "satisfied"), (30.0, "violated")]
)
def test_b5_within_seven_day_roundtrip(value, expected):
    """`inspection.prescribed.completed` within 7 day：5 天 satisfied / 30 天 violated。"""
    anchor = "inspection.prescribed.completed"
    obl = _eval(
        {
            "deadline_id": "D1",
            "relation": "within",
            "offset_value": 7,
            "offset_unit": "day",
            "time_anchor_key": anchor,
        },
        [_anchored_fact("F", anchor, value)],
    )
    assert obl.closure_status == "closed"
    assert obl.satisfaction_status == expected
