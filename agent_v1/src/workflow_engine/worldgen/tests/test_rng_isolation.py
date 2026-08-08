"""波次二 #22「rng 隔离 1a」：稳定键子随机流的性质测试。

这些测试守的不是某个具体数值，而是**隔离本身**：

- T5：种子必须是 `str` 不能是 `hash(str)`（跨进程重放稳定性）
- T4：不同 (阶段, 世界, 片段) 拿到互不相同的流 —— 防「全都坍缩成一条流」
      （键写错但测试全绿是最阴的失败形态）
- T2：四个后置阶段对「片段列表变长」免疫 —— 这是 1a-i 要治的病本身
- T6：sidecar 槽级流对「注册表新增槽 / 轴积组合数变化」免疫 —— 1a-i′ 要治的病
- T1/T3：片段模板选择零消耗主 rng ＋ 追加模板的插入稳定性 —— 1a-ii 要治的病

⚠️ 反面纪律：这里**不复刻实现**（不在测试里重写一遍 shuffle 当基线）。
   老的 `test_default_off_consumes_no_extra_randomness` 就是那么写的，
   实现一改测试就红、而红的原因跟正确性无关。故一律断言**输出层不变式**。
"""

from __future__ import annotations

import os
import random
import subprocess
import sys

import pytest

from workflow_engine.worldgen import generator, rng_domains
from workflow_engine.worldgen.generator import (
    generate_coverage_relations,
    generate_coverage_sampling_measurements,
    generate_structural_assessment_measurements,
    generate_technical_validation_measurements,
    generate_world_bundle,
)
from workflow_engine.worldgen.registry import _build_registry_bundle


# ---------------------------------------------------------------------------
# T5 ⛔ hash()：跨进程重放稳定性
# ---------------------------------------------------------------------------
_PROBE = (
    "import random;"
    "k='w2rng.coverage_relations.v1|WB-X-0000-S00401|FRG-A-00';"
    "print(random.Random(k).random(), random.Random(hash(k)).random())"
)


def _probe_with_hashseed(value: str) -> tuple:
    env = dict(os.environ, PYTHONHASHSEED=value)
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, check=True, env=env,
        encoding="utf-8", errors="replace",
    ).stdout.split()
    return out[0], out[1]


def test_t5_str_seed_is_stable_across_pythonhashseed_but_hash_seed_is_not():
    """字符串种子跨 PYTHONHASHSEED 稳定；`hash(str)` 种子不稳 —— ⛔ 那条的实证。

    这是 1a 全序的地基：子流的键是字符串，重放（换进程、换机器、换跑批）必须同流。
    """
    str_a, hash_a = _probe_with_hashseed("0")
    str_b, hash_b = _probe_with_hashseed("12345")
    assert str_a == str_b, (
        "字符串种子跨 PYTHONHASHSEED 应稳定，实测 " f"{str_a} vs {str_b}"
    )
    assert hash_a != hash_b, (
        "本测试的前提是 `hash(str)` 跨 PYTHONHASHSEED 不稳；若这里相等，"
        "说明探针没生效（环境变量没传进去），T5 就成了空护栏"
    )


# ---------------------------------------------------------------------------
# T4 防坍缩：域串 / 世界 / 片段三个维度各自都要真的区分开
# ---------------------------------------------------------------------------
def test_t4_domains_are_registered_and_unique():
    assert len(set(rng_domains.ALL_DOMAINS)) == len(rng_domains.ALL_DOMAINS)
    # 四个后置阶段的域串必须互异 —— 共用即退化成一条流
    stage_domains = [
        rng_domains.COVERAGE_RELATIONS,
        rng_domains.COVERAGE_SAMPLING,
        rng_domains.TECHNICAL_VALIDATION,
        rng_domains.STRUCTURAL_ASSESSMENT,
    ]
    assert len(set(stage_domains)) == 4


def test_t4_sub_rng_first_draw_differs_across_stage_world_fragment():
    """(阶段, world, fragment) 任一维不同 → 首抽不同。

    治的是最阴的失败形态：键写错（比如漏了 fragment_id）导致所有片段共用一条流，
    此时功能测试全绿、只有分布层能看出来。
    """
    draws = {}
    for domain in (
        rng_domains.COVERAGE_RELATIONS,
        rng_domains.COVERAGE_SAMPLING,
        rng_domains.TECHNICAL_VALIDATION,
        rng_domains.STRUCTURAL_ASSESSMENT,
    ):
        for world in ("WB-A-0000-S00401", "WB-A-0001-S00401", "WB-A-0000-S00402"):
            for frag in ("FRG-A-00", "FRG-A-01", "FRG-B-00"):
                key = (domain, world, frag)
                draws[key] = rng_domains.sub_rng(domain, world, frag).random()
    assert len(set(draws.values())) == len(draws), "存在两条子流首抽相同 —— 疑似键坍缩"


def test_t4_sub_rng_is_reproducible_for_the_same_key():
    a = rng_domains.sub_rng(rng_domains.COVERAGE_SAMPLING, "WB-A-0000-S00401", "FRG-A-00")
    b = rng_domains.sub_rng(rng_domains.COVERAGE_SAMPLING, "WB-A-0000-S00401", "FRG-A-00")
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_sub_rng_rejects_unregistered_domain_and_non_str_parts():
    with pytest.raises(ValueError):
        rng_domains.sub_rng("w2rng.never.registered.v1", "WB", "FRG")
    with pytest.raises(ValueError):
        # 序号入键 = 把「列表变长污染」换个地方复发，结构上拒掉
        rng_domains.sub_rng(rng_domains.COVERAGE_SAMPLING, "WB-A-0000-S00401", 3)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T2 四阶段对「片段列表变长」免疫
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def _world():
    registries = _build_registry_bundle()
    world = generate_world_bundle(
        batch_config={}, registries=registries, seed=401, building_index=0, fragment_count=4
    )
    assert len(world.fragments) >= 3, "本测试需要至少 3 个片段做「短列表 vs 长列表」对照"
    return world, registries


def _canon_measurements(records):
    return [
        (
            m.measurement_id, m.target_ref, m.slot_id, m.measurement_family,
            m.derivation_mode, m.value_num, m.value_bool, m.value_enum,
            m.unit, m.method_class, m.sample_count, m.confidence_index,
        )
        for m in records
    ]


def _canon_relations(records):
    return [
        (
            r.coverage_id, r.coverage_relation_type, r.target_fragment_id,
            r.coverage_state, r.covered_area_m2, r.inspected_area_m2, r.obscuration_class,
        )
        for r in records
    ]


# 🔴 对照形态用「**前插**」而不是「追加」——这是本测试是否为空护栏的分水岭。
#    旧码把主 rng 顺序穿过片段列表，**在末尾追加**不会移动前面的片段（它们先被消费），
#    故「追加」型对照在旧码上也会绿 ⇒ 测不出病。**前插**才逼出「同一片段在不同位置
#    必须拿到同一条流」这条真正的不变式。（同仓教训：测试跑在缺陷不可能显现的输入上。）
def _prefixed(world):
    """返回 (短列表, 前插后的长列表)：长列表 = [最后一个片段] ＋ 短列表。

    短列表取「除最后一个之外的全部」而非只取 2 个 —— 覆盖面越大，
    「值恰好没变」的巧合越难发生（本阶段有些 slot 的比例区间是退化的
    如 `[1.0, 1.0]`，只比 2 个片段时可能碰巧全同、护栏变空）。
    """
    short = list(world.fragments[:-1])
    return short, [world.fragments[-1]] + short


def test_t2_coverage_relations_unaffected_by_prepending_a_fragment(_world):
    world, registries = _world
    cbi = {c.component_id: c for c in world.components}
    short, longer = _prefixed(world)
    a = generate_coverage_relations(
        world.building, world.components, short, cbi, registries, world_id=world.world_id
    )
    b = generate_coverage_relations(
        world.building, world.components, longer, cbi, registries, world_id=world.world_id
    )
    b_by_fragment = {r.target_fragment_id: r for r in b}
    for rel in a:
        other = b_by_fragment[rel.target_fragment_id]
        # ⚠️ 诚实边界：`coverage_id` = f"CVR-{片段后缀}-{fragment_index:02d}" **含列表位置**，
        #    前插会改它。抽样值层已隔离，**id 层未隔离**——这条残留耦合记在实施记录里，
        #    不在 1a 范围内（改 id 构造会动既有池的主键）。故这里比值不比 id。
        assert (
            rel.coverage_relation_type, rel.coverage_state, rel.covered_area_m2,
            rel.inspected_area_m2, rel.obscuration_class,
        ) == (
            other.coverage_relation_type, other.coverage_state, other.covered_area_m2,
            other.inspected_area_m2, other.obscuration_class,
        ), f"{rel.target_fragment_id} 的覆盖关系随列表位置变了"


def test_t2_coverage_sampling_unaffected_by_prepending_a_fragment(_world):
    world, registries = _world
    short, longer = _prefixed(world)
    a = generate_coverage_sampling_measurements(
        world.building, world.components, short, registries, world_id=world.world_id
    )
    b = generate_coverage_sampling_measurements(
        world.building, world.components, longer, registries, world_id=world.world_id
    )
    kept = {f.fragment_id for f in short}
    assert _canon_measurements(a) == _canon_measurements(
        [m for m in b if m.target_ref in kept]
    )


def test_t2_technical_validation_unaffected_by_prepending_a_fragment(_world):
    world, registries = _world
    short, longer = _prefixed(world)
    a = generate_technical_validation_measurements(
        world.building, short, world.conditions, registries, world_id=world.world_id
    )
    b = generate_technical_validation_measurements(
        world.building, longer, world.conditions, registries, world_id=world.world_id
    )
    kept = {f.fragment_id for f in short}
    assert _canon_measurements(a) == _canon_measurements(
        [m for m in b if m.target_ref in kept]
    )


def test_t2_structural_assessment_unaffected_by_prepending_a_fragment(_world):
    world, registries = _world
    cbi = {c.component_id: c for c in world.components}
    short, longer = _prefixed(world)
    # 🔴 DrainageState 锚 component_id 而非 fragment_id（spec 04 §12；sidecar.py LD-1 同坑），
    #    caller 侧要自己重建 fragment→state 索引。
    drainage_by_component = {d.component_id: d for d in world.drainage_states or []}
    drainage = {
        f.fragment_id: drainage_by_component[f.component_id]
        for f in world.fragments
        if f.component_id in drainage_by_component
    }
    drivers = {d.fragment_id: d for d in world.drivers}
    common = dict(
        conditions=world.conditions, mechanisms=world.mechanisms, components_by_id=cbi,
        registries=registries, world_id=world.world_id,
        drainage_by_fragment=drainage, drivers_by_fragment=drivers,
    )
    a = generate_structural_assessment_measurements(world.building, short, **common)
    b = generate_structural_assessment_measurements(world.building, longer, **common)
    # `target_ref` 对 defect_geometry 记录是 condition_id 而非 fragment_id，
    # 故按 condition→fragment 反查后再筛「属于前 2 个片段的记录」。
    frag_of_condition = {c.condition_id: c.fragment_id for c in world.conditions}
    kept = {f.fragment_id for f in short}

    def _belongs(record) -> bool:
        ref = record.target_ref
        return (frag_of_condition.get(ref, ref)) in kept

    assert _canon_measurements(a) == _canon_measurements([m for m in b if _belongs(m)])


# ---------------------------------------------------------------------------
# T6 sidecar 槽级流：加槽 / 改轴积组合数都不动既有值
# ---------------------------------------------------------------------------
def _sidecar_records(registry_id: str):
    bundle = _build_registry_bundle()
    for table in bundle.registries:
        if table.registry_id == registry_id:
            return [dict(r) for r in table.records]
    raise AssertionError(f"注册表 {registry_id} 不存在")


def _flatten(buckets):
    return [
        (bucket, v.slot_id, v.value, tuple(sorted(v.qualifiers.items())))
        for bucket in sorted(buckets)
        for v in buckets[bucket]
    ]


def test_t6_numeric_slot_addition_is_a_pure_append():
    """sidecar 数值槽：加一条记录 ⇒ 既有槽的值一个都不动。"""
    from workflow_engine.worldgen.sidecar import _sample_sidecar_facts_for_fragment

    records = _sidecar_records("sidecar_measurement_registry")
    assert records, "注册表为空，断言会跑在空集合上"
    extra = dict(records[0])
    extra["slot_id"] = "duration.rngiso.probe_only"
    base = _sample_sidecar_facts_for_fragment("WB-T6", "FR0", records)
    # 🔴 前插不是追加（官方线审核 F2 实证）：追加做对照在坍缩变异下是绿的
    # ——顺序敏感的坏实现对"尾部加"恰好免疫；前插才逼出对键控的真依赖。
    with_extra = _sample_sidecar_facts_for_fragment("WB-T6", "FR0", [extra] + records)
    kept = [row for row in _flatten(with_extra) if row[1] != extra["slot_id"]]
    assert _flatten(base) == kept
    assert any(row[1] == extra["slot_id"] for row in _flatten(with_extra)), (
        "新槽没产出行 —— 上面的相等是因为「什么都没加」，护栏是空的"
    )


def test_t6_bool_slot_addition_is_a_pure_append():
    """sidecar bool 槽：加一条**不进任何既有槽 `conditional_inputs`** 的记录 ⇒ 既有值不动。

    ⚠️ 这条边界是真的：条件路径把上游已采值喂进公式，故给既有槽新增上游仍会改下游。
    这里刻意造一个「无下游」的新槽来验隔离本身。
    """
    from workflow_engine.worldgen.sidecar import _sample_sidecar_bool_slots_for_building

    records = _sidecar_records("sidecar_bool_slot_registry")
    plain = [r for r in records if not r.get("qualifier_axis_product")]
    assert plain, "没有非轴积槽可做模板"
    extra = dict(plain[0])
    extra["slot_id"] = "procedure.rngiso.probe_only"
    extra["conditional_formula"] = None  # 不吃上游，纯 marginal
    extra["conditional_inputs"] = []
    extra["sampling_order"] = 1  # 🔴 刻意排到**最前**：过去这会把其后所有槽整体移位
    fids = ["FR0", "FR1"]
    common = dict(
        building_world_id="WB-T6",
        fragment_ids=fids,
        per_fragment_contexts={f: None for f in fids},
        building_context=None,
    )
    a_frag, a_bld = _sample_sidecar_bool_slots_for_building(
        sidecar_bool_slot_records=records, **common
    )
    b_frag, b_bld = _sample_sidecar_bool_slots_for_building(
        sidecar_bool_slot_records=records + [extra], **common
    )
    for fid in fids:
        kept = [row for row in _flatten(b_frag[fid]) if row[1] != extra["slot_id"]]
        assert _flatten(a_frag[fid]) == kept, f"{fid}: 新槽插到最前后既有槽值变了"
    kept_bld = [row for row in _flatten(b_bld) if row[1] != extra["slot_id"]]
    assert _flatten(a_bld) == kept_bld, "新槽插到最前后楼级槽值变了"
    # 新槽落哪一边取决于它的 `granularity`（模板槽可能是楼级），两边一起查
    emitted = [
        row
        for buckets in [b_frag[f] for f in fids] + [b_bld]
        for row in _flatten(buckets)
        if row[1] == extra["slot_id"]
    ]
    assert emitted, "新槽没产出行 —— 护栏是空的"


def test_t6_axis_combo_addition_does_not_shift_existing_combos():
    """轴积槽：给某个槽的轴积**加一个组合** ⇒ 既有组合的值不动。

    这条直接对着波次二在册的 #29（BA→BD 改 `actor_role_key` 值域）。
    combo 维若不入键，同槽多组合共用一条流、按 `axis_product` 顺序推进 ⇒
    组合数一变其余全部移位；本测试就是那个失败形态的探测器。
    """
    from workflow_engine.worldgen.sidecar import _sample_sidecar_bool_slots_for_building

    records = _sidecar_records("sidecar_bool_slot_registry")
    axis_idx = next(
        (i for i, r in enumerate(records) if len(r.get("qualifier_axis_product") or []) > 1),
        None,
    )
    assert axis_idx is not None, "注册表里没有多组合的轴积槽，本测试失去对象"
    original = records[axis_idx]
    product = list(original["qualifier_axis_product"])
    new_combo = {**product[0], "actor_role_key": "rngiso_probe_role"}
    mutated = dict(original)
    # 🔴 插到**最前**，最大化「顺序耦合」的暴露面
    mutated["qualifier_axis_product"] = [new_combo] + product
    records_b = list(records)
    records_b[axis_idx] = mutated

    fids = ["FR0"]
    common = dict(
        building_world_id="WB-T6",
        fragment_ids=fids,
        per_fragment_contexts={f: None for f in fids},
        building_context=None,
    )
    _, a_bld = _sample_sidecar_bool_slots_for_building(
        sidecar_bool_slot_records=records, **common
    )
    _, b_bld = _sample_sidecar_bool_slots_for_building(
        sidecar_bool_slot_records=records_b, **common
    )
    slot = original["slot_id"]
    probe = "rngiso_probe_role"

    def _rows(buckets):
        return [
            row for row in _flatten(buckets)
            if row[1] == slot and not any(probe == v for _, v in row[3])
        ]

    assert _rows(a_bld), "轴槽一行都没产出，护栏是空的"
    assert _rows(a_bld) == _rows(b_bld), (
        "加一个轴组合后既有组合的值变了 —— combo 维没进子 rng 键"
    )


# ---------------------------------------------------------------------------
# T1 / T3 片段模板选择：零主 rng 消耗 ＋ 追加模板的插入稳定性
# ---------------------------------------------------------------------------
class _FakeTable:
    def __init__(self, registry_id, records):
        self.registry_id = registry_id
        self.records = records


class _FakeRegistries:
    def __init__(self, records):
        self.registries = [_FakeTable("fragment_template_registry", records)]


_TPL_TARGET = 4
_TPL_BASE = [
    {"fragment_template_id": f"FT_{i:02d}", "building_template_id": "BT_X",
     "component_type": "external_wall"}
    for i in range(12)
]
_TPL_NEW = {"fragment_template_id": "FT_NEW", "building_template_id": "BT_X",
            "component_type": "external_wall"}


def _select(records, world_id):
    return [
        t["fragment_template_id"]
        for t in generator._select_fragment_templates(
            None, "BT_X", _FakeRegistries(records), world_id=world_id,
            target_count=_TPL_TARGET,
        )
    ]


def test_t1_template_selection_consumes_no_main_rng_by_construction():
    """T1：`_select_fragment_templates` 收不到主 rng（形参已删）⇒ 结构上不可能消费。

    比「比调用前后 `rng.getstate()`」强：那条要求函数继续收一个它不用的参数。
    """
    import inspect

    sig = inspect.signature(generator._select_fragment_templates)
    assert "rng" not in sig.parameters
    with pytest.raises(TypeError):
        generator._select_fragment_templates(
            None, "BT_X", _FakeRegistries(_TPL_BASE), random.Random(1),  # type: ignore[misc]
        )


def test_t3_adding_a_template_is_insertion_stable_with_predicted_eviction_count():
    """T3：追加一张模板 ⇒ (a) 未被挤掉的模板相对序不变 (b) 被挤掉的楼数 == 预测值。

    🔴 (b) 是**精确可预测的断言，不是统计判据**：新模板的稳定键若排进该楼的前 k，
    就恰好挤掉一个既有模板，否则一个都不动。预测直接从键序算，
    与被测函数的实现无关（只共用 `stable_sort_key`）。

    ⚠️ 同时钉住诚实边界：这是「插入稳定」不是「插入无影响」——
    候选池 n→n+1 而取 k 不变，结构上不可能零位移。若某次改动让挤掉数变成 0，
    那多半是新模板根本没进候选池（护栏变空），故下面同时断言「挤掉数 > 0」。
    """
    worlds = [f"WB-T3-{i:04d}-S00401" for i in range(200)]

    def _key(tpl_id: str, world_id: str):
        return rng_domains.stable_sort_key(
            rng_domains.FRAGMENT_TEMPLATE_SELECT, world_id, tpl_id
        )

    predicted_evictions = 0
    for world_id in worlds:
        before = _select(_TPL_BASE, world_id)
        after = _select(_TPL_BASE + [_TPL_NEW], world_id)

        # (a) 未被挤掉的模板保持相对序
        kept = [t for t in after if t != _TPL_NEW["fragment_template_id"]]
        assert kept == [t for t in before if t in set(kept)], (
            f"{world_id}: 未被挤掉的模板相对序变了 {before} → {after}"
        )

        # (b) 预测：新模板的键是否排进前 k
        ranked = sorted(
            [t["fragment_template_id"] for t in _TPL_BASE] + [_TPL_NEW["fragment_template_id"]],
            key=lambda tid: _key(tid, world_id),
        )
        new_in_top_k = _TPL_NEW["fragment_template_id"] in ranked[:_TPL_TARGET]
        assert new_in_top_k == (_TPL_NEW["fragment_template_id"] in after), (
            f"{world_id}: 新模板是否入选与键序预测不符"
        )
        if new_in_top_k:
            predicted_evictions += 1

    # 解析预期 ≈ k/(n+1) = 4/13 ≈ 30.8%；这里只断言「非零且不是全部」——
    # 具体比例是键的性质，不是本函数要保的不变式（写死它等于把哈希输出当规格）。
    assert 0 < predicted_evictions < len(worlds), (
        f"挤掉楼数 {predicted_evictions}/{len(worlds)} 落在极端值上——"
        "要么新模板从没进候选池（护栏变空），要么整表每次都重排（稳定化失效）"
    )


def test_t2_stage_functions_no_longer_accept_a_main_rng(_world):
    """删形参的结构化保证：四阶段收不到主 rng ⇒ 「不消费主 rng」不可能被违反。

    比任何运行时 `rng.getstate()` 断言都强 —— 后者要求函数继续收一个它不用的参数。
    """
    world, registries = _world
    cbi = {c.component_id: c for c in world.components}
    with pytest.raises(TypeError):
        generate_coverage_relations(  # type: ignore[call-arg]
            world.building, world.components, world.fragments, cbi, registries,
            random.Random(1),
        )


def test_t4_sidecar_domain_keys_include_final_dimension():
    """官方线审核 F1：sidecar 四个域串的键漏掉最后一维（slot_id/combo）时
    既有 15 条测试一条不红——本测试补这个洞：同 (world, 槽) 不同 combo /
    同 (world) 不同 slot_id 的子流首抽必须互异。"""
    from workflow_engine.worldgen import rng_domains
    # 轴积点：combo 维参与键（符号实取：rng_domains.sub_rng / SIDECAR_AXIS_COMBO）
    a = rng_domains.sub_rng(rng_domains.SIDECAR_AXIS_COMBO, "WB-X",
                            "reporting.artifact.submitted",
                            "actor_role_key=ba|artifact_key=report.inspection")
    b = rng_domains.sub_rng(rng_domains.SIDECAR_AXIS_COMBO, "WB-X",
                            "reporting.artifact.submitted",
                            "actor_role_key=rc|artifact_key=report.inspection")
    assert a.random() != b.random(), "combo 维没进键——#29 改轴会移位其余 combo"
    # 槽级点：slot_id 维参与键
    c = rng_domains.sub_rng(rng_domains.SIDECAR_BOOL_BUILDING, "WB-X", "slot.alpha")
    d = rng_domains.sub_rng(rng_domains.SIDECAR_BOOL_BUILDING, "WB-X", "slot.beta")
    assert c.random() != d.random(), "slot_id 维没进键——同栋各槽共用一条子流"
