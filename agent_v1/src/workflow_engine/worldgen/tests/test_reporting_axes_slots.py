"""reporting 三根轴（呈交/送达/签署）世界侧补产的常驻护栏（规格 v1，2026-08-03）。

四个新槽 `reporting.artifact.{submitted,delivered,signed}` / `reporting.record.submitted`
带 `qualifier_axis_product`——采样器按轴积逐组合独立采样。本文件锁四件事：

1. **排最后纪律**：四槽 sampling_order（48-51）严格大于全部既有槽。
   ⚠️ 2026-08-05（波次二 #22「rng 隔离 1a-i′」）起**降级为遗留纪律**：
   它原本是「缺省等价」的判据（不插队 ⇒ 既有槽在**同一条** rng 流里的消费序列不变），
   现在每个槽 / 每个轴组合走独立子流，插不插队都不移位。
   保留它只为**上游可见性**（条件路径读的是已采槽的值），那是语义顺序不是流顺序。
2. **行为不变式（判据的本体，1a-i′ 之后唯一真判据）**：摘掉四条记录再采一次，
   既有槽输出**逐位相同**。（原来还钉种子；子流种子现在由
   `(world_id[, fragment_id], slot_id[, combo])` 决定，调用方传不进种子。）
3. **轴积真的展开**：每槽**楼级**产出行数 == 轴积组合数（呈交/送达/签署是整栋楼
   流程的事件，不随 fragment 变 ⇒ 只发楼级行），且每行 qualifiers 带对应组合
   （不是采了一条无限定符的兜底行）。
4. **角色取值全部在世界权威词表内**（对照表是显式的，登记里混进词表外取值要当场红）。
5. **旧 fragment 路径对轴积槽零产出**：旧采样器不认轴积，发出来的行必然无轴限定符
   ——宁可不发也不发错行（2026-08-03 审核门 grok 点名的静默退化）。
"""
from __future__ import annotations


import pytest

from workflow_engine.worldgen.tests.test_precondition_supplement_slots import (
    _bool_records,
)
from workflow_engine.worldgen.sidecar import (
    _sample_sidecar_bool_slots_for_building,
    _sample_sidecar_bool_slots_for_fragment,
)

AXIS_SLOTS = (
    "reporting.artifact.submitted",
    "reporting.artifact.delivered",
    "reporting.record.submitted",
    "reporting.artifact.signed",
)


def _axis_records():
    return [r for r in _bool_records() if r["slot_id"] in AXIS_SLOTS]


def test_axis_product_shape_is_locked():
    """🔴 **声明本体的硬锁**：四槽轴积逐槽格数 ＋ 合计 **24**。

    ## 为什么这条不是 `test_axis_expansion_one_row_per_combo_with_qualifiers` 的重复

    那一条拿**产出**比**声明**（`len(got) == len(product)`）——它锁的是
    「采样器忠实执行了声明」。**声明本身被改小／改大，它照样绿**。
    本条锁的是声明本体，缺了它，删掉一格轴积在本文件里**不会有任何测试转红**。
    （既有教训：闸显示 Passed ≠ 规则被检查。）

    ## 数字沿革

    - 2026-08-03 三根轴上线：合计 **23** 格。
    - 2026-08-05 #29 首版（替换路）：`reporting.record.submitted` 的 `ba` 换成 `bd`，
      仍 1 格 ⇒ 合计仍 23。**该路已被推翻**：那一格同时被 10 张卡消费，
      其中 6 张射程外卡写 `actor_role_key=ba`，删掉 `ba` 格会把它们打成
      `blocked/qualifier_conflict`。
    - 2026-08-05 #29 **甲案**（决策门裁定）：该槽 **并存 ba ＋ bd 两格**
      ⇒ 合计 **24**、每栋 **+1 行**。这是本件唯一的行数增量。

    🔴 `ba` 格的字典必须**逐字**保持并存之前的原样：子流种子由
    `(world_id, slot_id, combo)` 派生，`combo_key` 一字不差才谈得上「既有行不位移」。
    """
    per_slot = {r["slot_id"]: r["qualifier_axis_product"] for r in _axis_records()}
    counts = {k: len(v) for k, v in per_slot.items()}
    assert counts == {
        "reporting.artifact.submitted": 13,
        "reporting.artifact.delivered": 8,
        "reporting.record.submitted": 2,
        "reporting.artifact.signed": 1,
    }, counts
    assert sum(counts.values()) == 24, counts

    # 本件射程槽：两格并存、逐字锁死。
    record_submitted = per_slot["reporting.record.submitted"]
    assert {c["actor_role_key"] for c in record_submitted} == {"ba", "bd"}
    assert {"artifact_key": "record.inspection_log",
            "actor_role_key": "ba"} in record_submitted, record_submitted
    assert {"artifact_key": "record.inspection_log",
            "actor_role_key": "bd"} in record_submitted, record_submitted

    # R2 保护名单：`reporting.artifact.submitted` 的 13 格**全部仍是 ba**
    # （那些条款原文确为建築事務監督），且不含檢驗日誌载体。
    artifact_submitted = per_slot["reporting.artifact.submitted"]
    assert {c["actor_role_key"] for c in artifact_submitted} == {"ba"}
    assert "record.inspection_log" not in {
        c["artifact_key"] for c in artifact_submitted}


def test_axis_slots_exist_and_order_last():
    recs = {r["slot_id"]: r for r in _axis_records()}
    assert set(recs) == set(AXIS_SLOTS), f"缺登记：{set(AXIS_SLOTS) - set(recs)}"
    others = [
        r.get("sampling_order")
        for r in _bool_records()
        if r["slot_id"] not in AXIS_SLOTS and r.get("sampling_order") is not None
    ]
    assert others
    for slot, r in recs.items():
        assert r.get("sampling_order") is not None, f"{slot} 缺 sampling_order"
        assert r["sampling_order"] > max(others), (
            f"{slot} 插队了（order={r['sampling_order']}，既有最大={max(others)}）"
            "——其后所有既有槽的 rng 消费会整体位移")
        assert r.get("qualifier_axis_product"), f"{slot} 缺轴积声明"


def _sample(recs, n_frag=3):
    # 1a-i′ 后采样由稳定键决定，seed 形参退役。
    fids = [f"FR{i}" for i in range(n_frag)]
    by_frag, building = _sample_sidecar_bool_slots_for_building(
        building_world_id="WB-reporting-axes-guard",
        fragment_ids=list(fids),
        sidecar_bool_slot_records=recs,
        per_fragment_contexts={fid: None for fid in fids},
        building_context=None,
    )
    rows = []
    for fid in fids:
        for bucket in sorted(by_frag[fid]):
            for v in by_frag[fid][bucket]:
                rows.append((fid, bucket, v.slot_id, v.value, dict(v.qualifiers)))
    for bucket in sorted(building):
        for v in building[bucket]:
            rows.append(("__BUILDING__", bucket, v.slot_id, v.value,
                         dict(v.qualifiers)))
    return rows


@pytest.mark.parametrize("n_frag", [1, 3])
def test_existing_slots_bitwise_unchanged_when_axis_slots_added(n_frag):
    """加轴槽 ⇒ 既有槽输出逐字节不变。

    🔴 1a-i′ 后这条从「纪律保证」升级成「结构保证」：过去它靠
    「新槽 `sampling_order` 排最后 ⇒ 不插队 ⇒ 共享 rng 流不移位」这条**人工纪律**，
    现在每个槽走 `(world_id[, fragment_id], slot_id)` 独立子流，插不插队都不移位。
    ⚠️ 因此原来那个 `seed` 参数化已无意义（子流种子不再来自调用方），
    改成按片段数参数化 —— 至少还在两个规模上验一遍。
    """
    records = _bool_records()
    without = [r for r in records if r["slot_id"] not in AXIS_SLOTS]
    baseline = [(a, b, c, d) for a, b, c, d, _ in _sample(without, n_frag=n_frag)]
    with_new = [(a, b, c, d) for a, b, c, d, _ in _sample(records, n_frag=n_frag)
                if c not in AXIS_SLOTS]
    assert with_new == baseline, "加入轴槽后既有槽输出位移"


def test_axis_expansion_one_row_per_combo_with_qualifiers():
    """轴积真的展开：**楼级**每组合恰一行，且每行带组合限定符。

    呈交/送达/签署是整栋楼流程的事件，不随 fragment 变 ⇒ 只发楼级行
    （首版测试预期「×fragment 数」是照普通槽写的，语义定型后改为楼级）。
    ⚠️ 断言不许跑在空集合上：先确认每槽都有产出。
    """
    records = _bool_records()
    combos = {r["slot_id"]: r["qualifier_axis_product"] for r in _axis_records()}
    rows = [r for r in _sample(records, n_frag=3) if r[2] in AXIS_SLOTS]
    assert rows, "轴槽一行都没产出"
    assert all(r[0] == "__BUILDING__" for r in rows), "轴行必须全部是楼级"
    for slot, product in combos.items():
        got = [r for r in rows if r[2] == slot]
        assert len(got) == len(product), (
            f"{slot}: 行数 {len(got)} ≠ 组合数 {len(product)}")
        seen = {tuple(sorted(
            (k, v) for k, v in q.items()
            if k in ("artifact_key", "actor_role_key"))) for *_, q in got}
        want = {tuple(sorted((k, str(v)) for k, v in c.items())) for c in product}
        assert seen == want, f"{slot}: 产出组合 ≠ 声明轴积"


def test_legacy_fragment_path_emits_nothing_for_axis_slots():
    """旧 fragment 采样器喂轴积记录 ⇒ **产出为零行**。

    旧路径不读 `qualifier_axis_product`，若照常采样会发一条**无轴限定符**的单行：
    「report.inspection 已呈交」与「form.mbi4 已呈交」被压成同一条布尔，
    且**不报错**。主管线走楼级编排器不受影响，但单测／旧调用直接调这个函数
    会拿到错误语义 ⇒ 宁可不发也不发错行。

    ⚠️ 反向对照同时钉住「跳过的是轴积槽、不是把整个旧路径关掉」：
    同一批记录里的非轴槽必须照常产出（否则这条测试在「旧路径全哑」时也会绿）。
    """
    axis_recs = _axis_records()
    assert axis_recs, "断言不能跑在空集合上"
    buckets = _sample_sidecar_bool_slots_for_fragment(
        building_world_id="WB-legacy-path-guard",
        fragment_id="FR0",
        sidecar_bool_slot_records=axis_recs,
    )
    rows = [v for vs in buckets.values() for v in vs]
    assert rows == [], f"旧路径对轴积槽发了 {len(rows)} 行（必然无轴限定符）"

    # 反向：非轴槽在同一函数里照常产出 ⇒ 上面的零不是「函数整个哑了」。
    other_recs = [r for r in _bool_records() if r["slot_id"] not in AXIS_SLOTS]
    other = _sample_sidecar_bool_slots_for_fragment(
        building_world_id="WB-legacy-path-guard",
        fragment_id="FR0",
        sidecar_bool_slot_records=other_recs,
    )
    assert [v for vs in other.values() for v in vs], "旧路径对普通槽也没产出——对照失效"


def test_axis_role_values_are_all_in_world_vocabulary():
    """登记里的角色取值必须全部来自世界权威词表（含拆开后的两个词）。"""
    from workflow_engine.worldgen.actor_role_crosswalk import WORLD_ROLE_VOCABULARY
    for r in _axis_records():
        for combo in r["qualifier_axis_product"]:
            role = combo.get("actor_role_key")
            if role is not None:
                assert role in WORLD_ROLE_VOCABULARY, (
                    f"{r['slot_id']} 的角色 {role!r} 不在世界词表——"
                    "别绕过对照表往登记里塞新词")
