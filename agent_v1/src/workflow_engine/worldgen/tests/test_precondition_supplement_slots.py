"""条款前件补槽（2026-07-31）的常驻护栏。

背景：33 张法规卡漏掉了条款自身的前件（「如…則須…」的「如」那半），对每栋楼无条件
开火。把前件映射回世界槽时发现两个前件世界侧根本没有对应槽，本组补的就是这两个：

  procedure.investigation.detailed.intended    ← MBIS_CoP_2023 §2.1.3(n) 的前件
  procedure.investigation.detailed.completed   ← MBIS_CoP_2023 §4.3.3(a) 的前件

本文件锁三件事，任何一件被改坏都要红：

1. **两槽在 sidecar_bool_slot_registry 里，且 sampling_order 严格排在全部既有槽之后。**
   ⚠️ 这一条自 2026-08-05（波次二 #22「rng 隔离 1a-i′」）起**降级为遗留纪律**：
   它原本是「缺省等价」的机器判据（采样曾按 (sampling_order, slot_id) 升序遍历**同一条**
   rng 流，排最后 ⇒ 不插队 ⇒ 既有槽消费序列不移位）。现在每个槽走
   `(域串, world_id[, fragment_id], slot_id)` 独立子流，**插不插队都不移位**。
   保留它的理由只剩一条：`sampling_order` 仍决定**上游可见性**
   （条件路径读的是「已采槽」的值），那是语义顺序、不是随机流顺序。

2. **行为不变式（比①更硬，且是 1a-i′ 之后唯一真判据）**：把两条新记录从入参里摘掉
   再采一次，既有槽的输出必须**逐位相同**。①是代理指标，②才是它要保的东西。

3. **语义裁定**：`.intended` 不得把 `procedure.investigation.intention_notified` 声明成
   自己的上游。§2.1.3(n) 的义务本体就是「以書面通知…其有意進行詳細調查」——notified 是
   本义务的**履行**，拿履行当前提 = 用结论当前提。同理 `.completed` 必须依赖
   `procedure.investigation.started`（已開始），而它自己的 prevalence 必须低于该上游。

⚠️ 诚实边界（2026-08-05 重写；旧版说「往注册表加记录必然换种子、整池必变」，
   那是 1a-0 解绑之前的事实，已作废）：本文件保的是「加这两个槽不动既有槽的值」。
   现在这条在**池级**也成立了——sidecar 子流不再挂 `deterministic_key`，
   加注册表记录不再重掷整批。**但仍有一个前提**：新槽不得出现在任何既有槽的
   `conditional_inputs` 里。条件路径把上游已采值喂进公式 ⇒ 上游一变，
   下游即便键稳、阈值 p 也变。「加槽 = 纯追加」只对不进上游表的新槽成立。
"""

from __future__ import annotations


import pytest

from workflow_engine.worldgen.registry import (
    BUILDING_READING_AGGREGATION,
    _build_registry_bundle,
    _build_sidecar_contract,
)
from workflow_engine.worldgen.sidecar import _sample_sidecar_bool_slots_for_building

INTENDED = "procedure.investigation.detailed.intended"
COMPLETED = "procedure.investigation.detailed.completed"
NEW_SLOTS = (INTENDED, COMPLETED)

# 2026-08-03 reporting 三根轴（sampling_order 48-51）排在本组两槽（46/47）**之后**。
# 本文件的不变量是「精确前件补槽不打乱**先于它们**的槽」——
# 后来者按同一条「排最后」纪律加入，天然在保护范围之外；
# 它们自己的同款不变量见 test_reporting_axes_slots.py。
LATER_AXIS_SLOTS = frozenset({
    "reporting.artifact.submitted", "reporting.artifact.delivered",
    "reporting.record.submitted", "reporting.artifact.signed",
})

# `.completed` 的直接上游（已開始）。`.completed` 的 prevalence 必须低于它。
COMPLETED_UPSTREAM = "procedure.investigation.started"
# `.intended` 的**下游履行**——绝不可反过来当它的上游。
INTENDED_DOWNSTREAM_FULFILMENT = "procedure.investigation.intention_notified"


def _bool_records():
    bundle = _build_registry_bundle()
    for registry in bundle.registries:
        if registry.registry_id == "sidecar_bool_slot_registry":
            return registry.records
    raise RuntimeError("sidecar_bool_slot_registry not found")


def _by_slot():
    return {r["slot_id"]: r for r in _bool_records()}


def test_new_slots_registered_in_bool_registry() -> None:
    by_slot = _by_slot()
    for slot in NEW_SLOTS:
        assert slot in by_slot, f"{slot} 不在 sidecar_bool_slot_registry"
        rec = by_slot[slot]
        assert rec["value_type"] == "bool"
        assert isinstance(rec["prevalence"], float)
        # 🔴 2026-08-05 更新（决议_33处置_20260805.md §一.1「零边际成本段」）：
        # 原断言是 `conditional_formula is None`，用意是「Round6/7 overlay 只 patch
        # 它那 45 条，本组不在其中，被挂上公式说明误命中」。
        # 现在本组**有意**被第二道 overlay（`_apply_precondition_coupling_overlay`）
        # 装上真公式——它们原先是「声明了 `conditional_inputs` 却没有公式」的**死声明**，
        # 实际是独立伯努利，而 `.intended` 正是乙路 §2.1.3(n) 要接的前件槽。
        # 断言据此改成「必须**有**公式，且不是被 Round6/7 误命中的」。
        assert rec["conditional_formula"] is not None, (
            f"{slot} 又变回死声明了——声明了条件依赖却没有可执行公式")
        assert rec["distribution_source"] == (
            "proagent_engineering_estimate_precondition_coupling_20260805"), (
            f"{slot} 的公式来源不是死声明补公式那一批——查是不是被 Round6/7 误命中")


def test_new_slots_registered_in_ownership_map() -> None:
    """两表都要有：ownership 声明 + bool registry 实采。

    CLAUDE.md 记的「140 声明 vs 46 实采、两表之间没有任何东西在对账」就是只登一边的下场。
    """
    owned = {entry.slot_id for entry in _build_sidecar_contract().ownership_map}
    for slot in NEW_SLOTS:
        assert slot in owned, f"{slot} 未在 sidecar_contract.ownership_map 注册"


def test_later_axis_slots_are_actually_later() -> None:
    """豁免集的机器闸（grok 问题 4 遗留）：`LATER_AXIS_SLOTS` 的每个成员
    sampling_order 必须**严格大于**本组两槽——豁免的全部正当性就在「更晚」，
    这一条不上机器闸，将来往豁免集塞一个更早的槽就是静默打洞。"""
    by = _by_slot()
    new_max = max(by[s]["sampling_order"] for s in NEW_SLOTS)
    for slot in LATER_AXIS_SLOTS:
        assert slot in by, f"豁免集成员 {slot} 不在注册表"
        o = by[slot].get("sampling_order")
        assert o is not None and o > new_max, (
            f"{slot} order={o} 不晚于本组（max={new_max}）——豁免集被塞了更早的槽")


def test_new_slots_sampling_order_is_last() -> None:
    """两个新槽的 sampling_order 必须严格大于全部既有槽（缺省等价的机器判据）。"""
    records = _bool_records()
    others = [
        r["sampling_order"]
        for r in records
        if r["slot_id"] not in NEW_SLOTS
        and r["slot_id"] not in LATER_AXIS_SLOTS
        and r.get("sampling_order") is not None
    ]
    assert others, "既有槽一个 sampling_order 都没有，判据失去意义"
    max_other = max(others)
    by_slot = _by_slot()
    for slot in NEW_SLOTS:
        order = by_slot[slot].get("sampling_order")
        assert order is not None, f"{slot} 缺 sampling_order（会被排到 9999 兜底位，判据落空）"
        assert order > max_other, (
            f"{slot} 的 sampling_order={order} 未排在既有槽之后（既有最大={max_other}）"
            "——新槽一插队，其后所有既有槽的 rng 消费就整体位移"
        )
    # 没有既有槽用 None 兜底位（否则它会被排到新槽**之后**，判据同样落空）。
    assert all(
        r.get("sampling_order") is not None
        for r in records
        if r["slot_id"] not in NEW_SLOTS and r["slot_id"] not in LATER_AXIS_SLOTS
    ), "存在 sampling_order=None 的既有槽，它会被兜底排到 9999 即新槽之后"


@pytest.mark.parametrize("n_fragments", [1, 5])
def test_existing_slots_bitwise_unchanged_when_new_slots_added(n_fragments: int) -> None:
    """行为不变式：摘掉两条新记录，既有槽输出逐位相同。

    这是 sampling_order 判据真正要保的东西——判据是代理，本条是本体。

    ⚠️ 2026-08-05：原来按 `seed` 参数化（3 个种子）。1a-i′ 之后子流种子由
    `(world_id, fragment_id, slot_id)` 决定、调用方传不进种子，那个参数化变成
    「同一件事跑三遍」的空护栏 ⇒ 改按片段数参数化，至少还在两个规模上验。
    """
    records = _bool_records()
    without_new = [r for r in records if r["slot_id"] not in NEW_SLOTS]
    fragment_ids = [f"FR{i}" for i in range(n_fragments)]

    def sample(recs):
        by_frag, building = _sample_sidecar_bool_slots_for_building(
            building_world_id="WB-precondition-guard",
            fragment_ids=list(fragment_ids),
            sidecar_bool_slot_records=recs,
            per_fragment_contexts={fid: None for fid in fragment_ids},
            building_context=None,
        )
        out = []
        for fid in fragment_ids:
            for bucket in sorted(by_frag[fid]):
                for value in by_frag[fid][bucket]:
                    out.append((fid, bucket, value.slot_id, value.value))
        for bucket in sorted(building):
            for value in building[bucket]:
                out.append(("__BUILDING__", bucket, value.slot_id, value.value))
        return out

    # 2026-08-03：比较面排除 LATER_AXIS_SLOTS——它们 sampling_order 48-51 在本组
    # 两槽（46/47）**之后**，值依赖 46/47 的 rng 消费，被影响是设计使然；
    # 本不变量的保护对象是**先于** 46 的槽。后来者自己的同款不变量另有测试。
    baseline = [row for row in sample(without_new) if row[2] not in LATER_AXIS_SLOTS]
    with_new = [row for row in sample(records)
                if row[2] not in NEW_SLOTS and row[2] not in LATER_AXIS_SLOTS]
    assert with_new == baseline, (
        "加入新槽后既有槽输出发生位移——sampling_order 没有排在最后，"
        "或采样循环的排序键被改了"
    )
    # 同时确认新槽确实产出了行（否则上面那条会因为「新槽什么都没采」而假过）。
    produced = {row[2] for row in sample(records) if row[2] in NEW_SLOTS}
    assert produced == set(NEW_SLOTS), f"新槽未产出：{set(NEW_SLOTS) - produced}"


def test_intended_does_not_depend_on_its_own_fulfilment() -> None:
    """§2.1.3(n) 的义务本体是「以書面通知…其有意進行詳細調查」。

    intention_notified 是该义务的履行；把它当 `.intended` 的上游 = 用结论当前提。
    """
    rec = _by_slot()[INTENDED]
    inputs = rec.get("conditional_inputs") or []
    assert INTENDED_DOWNSTREAM_FULFILMENT not in inputs, (
        f"{INTENDED} 把自身义务的履行 {INTENDED_DOWNSTREAM_FULFILMENT} 声明成了上游"
    )
    assert INTENDED not in (
        _by_slot()[INTENDED_DOWNSTREAM_FULFILMENT].get("conditional_inputs") or []
    ), "反向依赖也不许——两槽之间不得成环"


def test_completed_depends_on_started_and_is_rarer() -> None:
    """§4.3.3(a)「根據詳細調查的結果」：有结果 ⊂ 已开始，故依赖成立且发生率更低。"""
    by_slot = _by_slot()
    rec = by_slot[COMPLETED]
    inputs = rec.get("conditional_inputs") or []
    assert COMPLETED_UPSTREAM in inputs, f"{COMPLETED} 未声明上游 {COMPLETED_UPSTREAM}"
    # 所有声明的 sidecar 上游必须先采（spec 06 §11.6.7 DAG validity）。
    for up in inputs:
        up_rec = by_slot.get(up)
        if up_rec is None:
            continue  # 物理 world_core 槽，不在本表内，不受 DAG 序约束
        assert up_rec["sampling_order"] < rec["sampling_order"], (
            f"{COMPLETED} 的上游 {up} sampling_order 反了"
        )
    assert rec["prevalence"] < by_slot[COMPLETED_UPSTREAM]["prevalence"], (
        f"{COMPLETED} 的 prevalence {rec['prevalence']} 不低于上游 "
        f"{COMPLETED_UPSTREAM} 的 {by_slot[COMPLETED_UPSTREAM]['prevalence']}"
    )


def test_completed_has_declared_building_reading() -> None:
    """`.completed` 是 fragment 采样槽，楼级读数必须有声明的聚合语义。

    没声明的话，任何楼级槽把它列为 conditional_input 都会撞
    `_resolve_building_upstream` 的 fail-fast。`.intended` 是楼级槽，不得进该表。
    """
    assert BUILDING_READING_AGGREGATION.get(COMPLETED) == "any_true"
    assert COMPLETED not in {"", None}
    by_slot = _by_slot()
    assert by_slot[COMPLETED].get("granularity") in (None, "fragment")
    assert by_slot[INTENDED].get("granularity") == "building"
    assert INTENDED not in BUILDING_READING_AGGREGATION, (
        "楼级槽不得进楼级聚合表（它本来就一栋一行）"
    )
