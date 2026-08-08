"""期限锚供给案（2026-08-05 决议）——世界侧发射与静态闸。

权威依据：`团队文档/我的笔记/决议_期限锚_20260805.md`。

## 本文件锁的是什么

- **C4 静态闸**：注册表里任何 `rule_card_threshold.time_anchor_key` 必须是
  `time_anchor_registry_v1.json`（19 条）的成员。R5 那类错名
  （`repair.completion_report_and_mbi4.submitted_to_ba`，世界侧孤儿字符串）
  **必须由测试抓，不能靠注意力**——它在 provenance 绑定通道接上之前不承载任何东西，
  接上之后失配是**静默**的（绑不上，落 `missing_time_anchor`，看起来像"世界没供"）。

- **B6（形态 C 的承重前置）**：期限 duration 槽逐（楼,锚）**楼级行恰 1 行**。
  形态 C ＝「不打 `aggregation` 标记的普通楼级事实」，其合法性依赖唯一性
  （`复核_发射形态C_qwen_20260805.md` §四5：「同楼同槽多行 ＋ 无限定符消费者」
  才是需要标记消歧的场景）。红了本单回退形态 A。

  🔴 **射程订正（official 审核 M1，2026-08-05）**：B6 原来只调楼级发射器
  ⇒ 只看得见 `granularity=="building"` 的 8 条，而注册表带锚条目实际是 **10 条**
  ——碎片粒度的 `duration.delivery.deadline.to_ba` / `.to_person` **结构上不在射程内**，
  **而乙12 翻车的恰恰就是这 2 条**（60/60 落 `ambiguous_fact_binding`）。
  乙12 是靠位移量化偶然撞出来的，不是靠这道闸；不扩射程，同形状将来会静默复发。
  现在射程 = **注册表全部带锚条目（现算，不硬编码条数）**。

  🔴 **乙12 甲案落地（换池捆绑批 2026-08-05）后本文件的断言形状变了**：
  `.to_person`（三线全票甲）与 `.to_ba`（本批一并裁，同属 §2.1.3(r) 楼级行政事件）
  都已改 `granularity="building"` ⇒ **碎片粒度带锚条目归零**，
  原「碎片粒度 2 条记录性断言」按其自注（「乙12 甲案落地时该改断言而非回滚裁定」）
  翻成楼级硬断言，并入 `test_b6_one_building_row_per_anchor` 的射程；
  留下 `test_b6_no_fragment_granularity_anchored_slots_remain` 钉住"不许退回碎片粒度"。

- **形态 C 本身**：新槽发射的行必须 `granularity="building"`、
  **不带 `aggregation` 标记**（打了会被 `validator._fragment_index` 排除，
  E1 实验 A3 臂全批 0/107 脱离）、`source_refs` 只有 world_id（无 fragment 戳）。

- **禁供闸**：丙类三锚（决议 §一.2）在世界侧一条都不许声明。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from workflow_engine.worldgen.registry import _build_registry_bundle
from workflow_engine.worldgen.sidecar import (
    DEADLINE_ANCHOR_DURATION_SLOTS,
    _sample_building_deadline_anchor_facts,
    _sample_sidecar_facts_for_fragment,
)

_PACK_DIR = (
    pathlib.Path(__file__).resolve().parents[4]
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
)


def _registry_anchors() -> set:
    data = json.loads(
        (_PACK_DIR / "time_anchor_registry_v1.json").read_text(encoding="utf-8")
    )
    return {a["time_anchor_key"] for a in data["time_anchors"]}


def _threshold_anchor_records():
    """注册表里全部带 `rule_card_threshold.time_anchor_key` 的条目（**全部 registry**）。"""
    bundle = _build_registry_bundle()
    out = []
    for table in bundle.registries:
        for record in table.records:
            anchor = (record.get("rule_card_threshold") or {}).get("time_anchor_key")
            if anchor:
                out.append((table.registry_id, str(record.get("slot_id")), str(anchor)))
    return out


def _measurement_records():
    """`sidecar_measurement_registry` 的全部条目。"""
    bundle = _build_registry_bundle()
    for table in bundle.registries:
        if table.registry_id == "sidecar_measurement_registry":
            return list(table.records)
    return []


def _anchored_records_by_granularity():
    """带锚的 measurement 条目按粒度二分 → `(楼级, 碎片级)`。

    🔴 **条数一律现算，不写死**（official 审核 M1）：原来 B6 与反向闸都锚在
    「8」这个楼级条目数上，于是碎片粒度的两条带锚槽整个消失也不会红。
    下次再往注册表加带锚条目时，这里自动把它纳入射程。
    """
    building, fragment = [], []
    for record in _measurement_records():
        anchor = (record.get("rule_card_threshold") or {}).get("time_anchor_key")
        if not anchor:
            continue
        if str(record.get("granularity") or "fragment") == "building":
            building.append(record)
        else:
            fragment.append(record)
    return building, fragment


# --------------------------------------------------------------------- #
# C4 静态闸
# --------------------------------------------------------------------- #
def test_c4_every_registry_time_anchor_is_in_the_registry_of_anchors():
    """世界侧声明的每个锚点都必须在锚点册 19 条里（R5 那类孤儿名的机器判据）。"""
    known = _registry_anchors()
    assert len(known) == 19, f"锚点册条数变了（{len(known)}），本闸的前提须复核"
    bad = [
        (rid, slot, anchor)
        for rid, slot, anchor in _threshold_anchor_records()
        if anchor not in known
    ]
    assert not bad, (
        f"世界侧声明了锚点册里没有的锚名：{bad}。"
        "锚名失配在绑定通道上是**静默**的——绑不上只会落 missing_time_anchor，"
        "看起来像「世界没供」。"
    )


def test_c4_anchor_declarations_are_not_empty():
    """反向闸：闸本身要在非空集合上有意义（否则恒绿等于没测）。

    🔴 **下限口径订正（official 审核 M1）**：原来写死 `>= 8`，那是**楼级**条目数，
    而带锚条目实际 10 条 ⇒ 两条碎片级带锚槽整个消失也不会红。
    现在改成「与从注册表现算的全部带锚条目数一致」，加条目自动跟着涨。

    第二条断言（全部带锚条目都住在 `sidecar_measurement_registry` 里）不是同义反复：
    它挡的是「有人把带锚条目加到别的 registry 表里」——那样的条目没有任何发射器覆盖，
    B6 与下面的发射覆盖闸都看不见它。
    """
    records = _threshold_anchor_records()
    building, fragment = _anchored_records_by_granularity()
    expected = len(building) + len(fragment)

    assert len(records) == expected, (
        f"全部 registry 里有 {len(records)} 条锚点声明，但 "
        f"`sidecar_measurement_registry` 里只有 {expected} 条 ⇒ "
        "有带锚条目落在别的表里，没有任何发射路径覆盖它，B6 结构上看不见"
    )
    assert expected >= 8, (
        f"带锚条目只剩 {expected} 条（楼级 {len(building)} ／ 碎片级 {len(fragment)}），"
        "静态闸筛的人群过小，判据失去意义"
    )


def test_c4_r5_orphan_anchor_name_is_gone():
    """R5：孤儿锚名 `..._and_mbi4...` 不许再出现在任何注册表条目里。"""
    orphans = [
        (rid, slot, anchor)
        for rid, slot, anchor in _threshold_anchor_records()
        if "_and_mbi4" in anchor
    ]
    assert not orphans, f"R5 孤儿锚名复活：{orphans}"


def test_c4_forbidden_anchors_are_not_declared_world_side():
    """丙类三锚（决议 §一.2）世界侧零声明。

    ⚠️ 三锚字面量与权威常量的同步说明：权威名单是
    `evo_agent_baseline.closure.obligation_deriver.FORBIDDEN_DEADLINE_ANCHOR_SUPPLY`，
    但跨包 import 违反分层独立契约（layer-independence，2026-08-08 被
    import-linter 拦下），故此处持字面量副本。防漂移的锚在判定侧：
    `closure/tests/test_deadline_anchor_supply.py::
     test_b4_forbidden_anchor_list_is_exactly_the_three_adjudicated`
    以同一组字面量钉死常量集合——改任何一侧都会先撞那条集合相等断言。
    主防线仍是判定侧求值器闸（误供带锚事实也不出确定判定），本断言是纵深。
    """
    forbidden = {
        "appointment.representative.supervision.made",
        "investigation.detailed.commencement",
        "repair.prescribed.started",
    }
    declared = [
        (rid, slot, anchor)
        for rid, slot, anchor in _threshold_anchor_records()
        if anchor in forbidden
    ]
    assert not declared, f"丙类禁供锚被世界侧登记：{declared}"


# --------------------------------------------------------------------- #
# 楼级发射清单（形态 C）
# --------------------------------------------------------------------- #
def test_building_deadline_slots_are_exactly_the_building_granularity_ones():
    """楼级期限槽清单 = 注册表里 `granularity=="building"` 的 duration 条目。"""
    bundle = _build_registry_bundle()
    expected = set()
    for table in bundle.registries:
        if table.registry_id != "sidecar_measurement_registry":
            continue
        for record in table.records:
            if str(record.get("granularity") or "fragment") == "building":
                expected.add(str(record.get("slot_id")))
    assert expected, "注册表里一个楼级 duration 槽都没有——供给没落地"
    assert set(DEADLINE_ANCHOR_DURATION_SLOTS) == expected


#: 碎片路径取样用的固定碎片 id（数量即「该栋碎片数」，记录性断言拿它当期望行数）
_FRAGMENT_IDS = ("FR-TEST-01", "FR-TEST-02", "FR-TEST-03", "FR-TEST-04")


def _emit_building(world_id="WB-TEST-0001"):
    """🔴 只覆盖**楼级**发射路径（`granularity=="building"` 的条目）。

    名字里的 `building` 是承重的：M1 那次漏掉碎片粒度的两条带锚槽，
    直接原因就是这个辅助当时叫 `_emit()`、看起来像"全部发射"。
    带锚条目的**全集**要走 `_emit_all_anchored_rows()`。
    """
    buckets = {
        "facts": [],
        "procedure_gate_state": [],
        "supervision_runtime_state": [],
        "artifact_requirement_state": [],
        "completion_runtime_state": [],
    }
    _sample_building_deadline_anchor_facts(world_id, _measurement_records(), buckets)
    return [v for values in buckets.values() for v in values]


def _emit_fragments(world_id="WB-TEST-0001", fragment_ids=_FRAGMENT_IDS):
    """覆盖**碎片**发射路径（`_sample_sidecar_facts_for_fragment`，逐碎片一轮）。

    碎片路径同样回写 `time_anchor_key`（`sidecar.py` 的 `_registry_time_anchor_key`），
    「回填两例外」就落在这条路径上。
    """
    rows = []
    records = _measurement_records()
    for fragment_id in fragment_ids:
        buckets = _sample_sidecar_facts_for_fragment(world_id, fragment_id, records)
        rows.extend(v for values in buckets.values() for v in values)
    return rows


def _emit_all_anchored_rows(world_id="WB-TEST-0001"):
    """两条发射路径产出的**带锚**行全集。"""
    rows = list(_emit_building(world_id)) + list(_emit_fragments(world_id))
    return [r for r in rows if r.time_anchor_key]


def test_b6_scope_covers_every_anchored_registry_entry():
    """🔴 M1 射程闸：注册表里每个带锚条目都必须真被某条发射路径产出。

    这条是 B6 的**射程保证**，不是 B6 本身。没有它，B6 只要不调某条路径，
    那条路径上的带锚槽就是真空的——2026-08-05 官方线审核抓到的正是这个形状
    （B6 只调楼级发射器 ⇒ 结构上看不见带锚行总体的 20%，
    而乙12 翻车的恰恰是那 20%）。

    两个方向都要红：
    - 注册表加了带锚条目而没有发射器产出它 → `declared - emitted` 非空；
    - 发射器回写了注册表没登记的锚（或「回填两例外」被撤掉）→ 集合不等。
    """
    declared = {slot for _, slot, _ in _threshold_anchor_records()}
    emitted = {row.slot_id for row in _emit_all_anchored_rows()}
    assert emitted == declared, (
        f"带锚条目与实际发射出带锚行的槽对不上：\n"
        f"  登记未发射 = {sorted(declared - emitted)}\n"
        f"  发射未登记 = {sorted(emitted - declared)}\n"
        "B6 只能看见发射得出来的东西；对不上就说明有带锚槽在射程之外。"
    )


def test_b6_one_building_row_per_anchor():
    """🔴 B6 承重前置（**楼级条目**）：每（楼,锚）楼级行恰 1 行。红则本单回退形态 A。

    射程 = 注册表里 `granularity=="building"` 的带锚条目（现算），
    并断言楼级发射器把它们**一条不落**地发出来——防「少发一条也照样绿」。
    """
    building, _ = _anchored_records_by_granularity()
    assert building, "注册表里一条楼级带锚条目都没有——本硬断言的前提变了，须复核"

    rows = _emit_building()
    assert rows, "楼级期限锚发射一行都没有"
    assert {row.slot_id for row in rows} == {str(r["slot_id"]) for r in building}, (
        "楼级发射器产出的槽集合 ≠ 注册表楼级带锚条目集合"
    )

    by_anchor = {}
    for row in rows:
        by_anchor.setdefault(row.time_anchor_key, []).append(row.slot_id)
    for anchor, slots in sorted(by_anchor.items()):
        assert len(slots) == 1, (
            f"锚点 {anchor!r} 发了 {len(slots)} 行楼级事实（{slots}）——"
            "形态 C 的合法性依赖逐（楼,锚）唯一，红了回退形态 A"
        )


#: 乙12 甲案（换池捆绑批 2026-08-05）把这两条从碎片粒度改成楼级粒度。
#: 点名写死是承重的：B6 主断言的射程是「现算的楼级带锚条目」，若有人把这两条
#: 悄悄退回碎片粒度，主断言只会**少验两条**而不会红——正是 M1 抓到的那个形状。
_YI12_PROMOTED_TO_BUILDING = (
    "duration.delivery.deadline.to_ba",
    "duration.delivery.deadline.to_person",
)


def test_b6_no_fragment_granularity_anchored_slots_remain():
    """🔴 乙12 甲案落地后的**楼级硬断言**（取代原碎片粒度记录性断言）。

    原记录性断言钉的是乙12 翻车的形状：这两条槽没有 `granularity` 键
    ⇒ 默认碎片粒度 ⇒ 每栋 = 该栋碎片数行，而它们的义务是**楼级作用域**、
    楼级索引看得见碎片行 ⇒ 同（作用域,锚）候选 >1 ⇒ `_bind_deadline_fact`
    碰撞策略触发 ⇒ 落 `blocked / ambiguous_fact_binding`（实测 60/60，零确定判定）。
    那条断言自注写明「乙12 甲案落地时该改断言而非回滚裁定」——本条就是那次改写。

    两个方向都要红：
    - 带锚条目里又出现碎片粒度的 → 有人加了新碎片带锚条目，或把这两条退回去；
    - 这两条不在楼级带锚集合里 → 粒度声明被撤，B6 主断言会**静默少验两条**。
    """
    building, fragment = _anchored_records_by_granularity()
    assert not fragment, (
        f"带锚条目里仍有碎片粒度的：{sorted(str(r['slot_id']) for r in fragment)}。"
        "乙12 甲案后带锚条目应全部是楼级——碎片粒度带锚槽会让楼级作用域义务"
        "看到多行同锚，落 blocked/ambiguous_fact_binding"
    )
    building_slots = {str(r["slot_id"]) for r in building}
    missing = [s for s in _YI12_PROMOTED_TO_BUILDING if s not in building_slots]
    assert not missing, (
        f"乙12 甲案射程两槽 {missing} 不在楼级带锚集合里——粒度声明被撤，"
        "B6 主断言会静默少验它们"
    )

    # 反向：碎片发射路径对这两条一行都不许再产出（`sidecar.py` 楼级槽直接 continue）。
    frag_rows = [r for r in _emit_fragments()
                 if r.slot_id in _YI12_PROMOTED_TO_BUILDING]
    assert not frag_rows, (
        f"碎片路径仍在发射楼级槽：{sorted({r.slot_id for r in frag_rows})}——"
        "楼级行与碎片行并存正是 glm 当初担心的双候选形态，那才会真的破坏 #8"
    )
    # 正向：楼级路径逐（楼,槽）恰 1 行（主断言按锚点验，这里按槽再钉一次）。
    bld_rows = [r for r in _emit_building()
                if r.slot_id in _YI12_PROMOTED_TO_BUILDING]
    assert sorted(r.slot_id for r in bld_rows) == sorted(_YI12_PROMOTED_TO_BUILDING), (
        f"楼级路径对乙12 两槽产出 {sorted(r.slot_id for r in bld_rows)}，期望各恰 1 行"
    )


def test_form_c_rows_carry_no_aggregation_marker():
    """形态 C：楼级原生行政事件**不打** `aggregation` 标记。

    打了会被 `validator._fragment_index` 排除（E1 实验 A3 臂全批 0/107 脱离），
    且语义上是错用——把行政事件虚报成「碎片读数的派生聚合」。
    """
    for row in _emit_building():
        assert "aggregation" not in (row.qualifiers or {}), (
            f"{row.slot_id} 打了 aggregation 标记——碎片作用域会看不见它"
        )
        assert row.qualifiers.get("granularity") == "building"
        assert "fragment_id" not in (row.qualifiers or {})


def test_form_c_rows_are_building_scoped_refs():
    """`source_refs` 只有 world_id ⇒ 落地成 `fragment_id=None` 的楼级事实。"""
    world_id = "WB-TEST-0002"
    for row in _emit_building(world_id):
        assert row.source_refs == [world_id]


def test_every_emitted_row_declares_a_known_anchor():
    """发射出来的每一行都必须自报一个锚点册里的锚点（provenance 回写的源头）。"""
    known = _registry_anchors()
    for row in _emit_building():
        assert row.time_anchor_key in known, (
            f"{row.slot_id} 回写了锚点册外的锚名 {row.time_anchor_key!r}"
        )


def test_emission_is_deterministic_per_world():
    """同一 world_id 两次发射逐值相同（槽级子 rng 的确定性）。"""
    a = [(r.slot_id, r.value) for r in _emit_building("WB-TEST-0003")]
    b = [(r.slot_id, r.value) for r in _emit_building("WB-TEST-0003")]
    assert a == b


def test_emission_differs_across_worlds():
    """不同 world_id 取到不同样本（反向闸：不是常量占位）。"""
    a = [r.value for r in _emit_building("WB-TEST-0004")]
    b = [r.value for r in _emit_building("WB-TEST-0005")]
    assert a != b, "两栋楼取到逐值相同的期限时长——采样没起作用"


@pytest.mark.parametrize("world_id", ["WB-A", "WB-B", "WB-C"])
def test_emitted_values_are_within_physical_bounds(world_id):
    """采样值落在注册表声明的物理边界内。"""
    bundle = _build_registry_bundle()
    bounds = {}
    for table in bundle.registries:
        if table.registry_id != "sidecar_measurement_registry":
            continue
        for record in table.records:
            bounds[str(record.get("slot_id"))] = record.get("physical_bounds")
    for row in _emit_building(world_id):
        low, high = bounds[row.slot_id]
        assert low <= row.value <= high, (
            f"{row.slot_id} 采到 {row.value}，越出物理边界 [{low}, {high}]"
        )
