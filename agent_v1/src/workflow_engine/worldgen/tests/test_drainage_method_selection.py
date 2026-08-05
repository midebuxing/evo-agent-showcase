"""DEBT-049 Phase3 U5 §2.1：drainage method_class 选取（P1-P4 总函数）+ air/ball 物理观测 + is_underground。

覆盖验收（spec §5）：
- P1-P4 逐分支（smoke/water/air/ball/cctv）+ 优先级序（misconnection>leakage>blockage）。
- air/ball 生成公式（单调性 + bounds + is_underground 两压力档）。
- is_underground 确定性散列派生 + domain 隔离（不消费 RNG、与 airball 子流 domain-separated）。
- 端到端：air/ball 专用观测 record 的 slot/method_class/qualifiers；P1/P2 覆写既有 index 测量 method_class。
- RNG 隔离：既有测量序列零扰动（air/ball 走独立子流 → 同 seed 生成确定 + 既有 measurement_id 不移位）。
"""
from __future__ import annotations

import random

from workflow_engine.worldgen.models import (
    DrainageState,
    BuildingContext,
    FragmentContext,
    ComponentNode,
    MechanismState,
)
from workflow_engine.worldgen.registry import _build_registry_bundle
from workflow_engine.worldgen.generator import (
    generate_world_bundle,
    generate_structural_assessment_measurements,
)
from workflow_engine.worldgen.generator_drainage import (
    _select_drainage_method_class,
    _compute_air_test_pressure_loss_mmH2O,
    _compute_ball_test_pass,
    _air_test_qualifiers,
    BALL_PASS_THRESHOLD,
    AIR_LOSS_CAP_MMH2O,
)
from workflow_engine.worldgen.generator_sampling import (
    _drainage_is_underground,
    _drainage_airball_obs_rng,
    _building_chain_seed_rng,
)


def _d(**kw) -> DrainageState:
    base = dict(
        drainage_id="DRN-x", component_id="C", segment_type="soil_pipe",
        blockage_index=0.0, leakage_index=0.0, misconnection_present=False,
        is_underground=False,
    )
    base.update(kw)
    return DrainageState(**base)


# ---------------------------------------------------------------- P1-P4 总函数
def test_p1_misconnection_selects_smoke():
    assert _select_drainage_method_class(_d(misconnection_present=True)) == "smoke_test"


def test_p1_priority_over_leakage_and_blockage():
    # misconnection 优先级最高：即使 leakage/blockage 也超阈，仍取 smoke。
    d = _d(misconnection_present=True, leakage_index=0.9, blockage_index=0.9,
           segment_type="soil_pipe")
    assert _select_drainage_method_class(d) == "smoke_test"


def test_p2_leakage_selects_water():
    assert _select_drainage_method_class(_d(leakage_index=0.6)) == "water_test"


def test_p2_priority_over_blockage():
    d = _d(leakage_index=0.51, blockage_index=0.9, segment_type="soil_pipe")
    assert _select_drainage_method_class(d) == "water_test"


def test_p3a_blockage_soilpipe_selects_air():
    assert _select_drainage_method_class(
        _d(blockage_index=0.6, segment_type="soil_pipe")) == "air_test"


def test_p3b_blockage_branch_selects_ball():
    assert _select_drainage_method_class(
        _d(blockage_index=0.6, segment_type="branch_connection")) == "ball_test"


def test_p4_default_cctv():
    assert _select_drainage_method_class(_d()) == "drainage_cctv"


def test_threshold_is_strict_gt_half():
    # 恰 0.5 不生效（>0.5 才生效）→ 落 P4 cctv。
    assert _select_drainage_method_class(_d(leakage_index=0.5, blockage_index=0.5)) == "drainage_cctv"
    assert _select_drainage_method_class(_d(blockage_index=0.5001, segment_type="soil_pipe")) == "air_test"


# ---------------------------------------------------------------- air/ball 公式
def test_air_pressure_loss_bounds_and_monotone():
    rng = _drainage_airball_obs_rng("DRN-a")
    lo = _compute_air_test_pressure_loss_mmH2O(_d(leakage_index=0.0, blockage_index=0.0), rng)
    rng = _drainage_airball_obs_rng("DRN-a")
    hi = _compute_air_test_pressure_loss_mmH2O(_d(leakage_index=1.0, blockage_index=1.0), rng)
    assert 0.0 <= lo <= AIR_LOSS_CAP_MMH2O
    assert 0.0 <= hi <= AIR_LOSS_CAP_MMH2O
    assert hi > lo  # 缺陷越重压降越大


def test_air_qualifiers_two_bands():
    above = _air_test_qualifiers(False)
    under = _air_test_qualifiers(True)
    # 四字段（§2.1b + duration 档常量）：地面上 38/0/hold 3min；地下 100/25/window 5min。
    assert above == {
        "is_underground": False, "test_pressure_mmH2O": 38,
        "acceptable_drop_mmH2O": 0, "duration_min": 3,
    }
    assert under == {
        "is_underground": True, "test_pressure_mmH2O": 100,
        "acceptable_drop_mmH2O": 25, "duration_min": 5,
    }


def test_ball_pass_monotone_with_blockage():
    # blockage 越高越易 fail（pass=False）。用同一 rng 序列比较趋势（统计意义）。
    passes_low = sum(
        _compute_ball_test_pass(_d(blockage_index=0.1), random.Random(s)) for s in range(200)
    )
    passes_high = sum(
        _compute_ball_test_pass(_d(blockage_index=0.9), random.Random(s)) for s in range(200)
    )
    assert passes_low > passes_high


def test_ball_deterministic_boundary():
    # blockage 远低于阈 → 恒 pass；远高于阈 → 恒 fail（jitter 0.15 内）。
    assert _compute_ball_test_pass(_d(blockage_index=0.0), _drainage_airball_obs_rng("DRN-b")) is True
    assert _compute_ball_test_pass(_d(blockage_index=1.0), _drainage_airball_obs_rng("DRN-b")) is False


# ---------------------------------------------------------------- is_underground 散列
def test_is_underground_deterministic():
    assert _drainage_is_underground("DRN-xyz") == _drainage_is_underground("DRN-xyz")


def test_is_underground_distribution_near_35pct():
    ids = [f"DRN-{i:06d}" for i in range(5000)]
    frac = sum(_drainage_is_underground(x) for x in ids) / len(ids)
    assert 0.30 < frac < 0.40  # 冻结常量 35%（大样本靠拢）


def test_domain_separation_underground_vs_airball():
    # 两子流 domain 串不同 → 同 drainage_id 的 seed 不相关（不串扰立面级 chain）。
    did = "DRN-sep"
    ab = _drainage_airball_obs_rng(did).random()
    chain = _building_chain_seed_rng(did).random()
    assert ab != chain  # 极大概率不等（domain-separated）


# ---------------------------------------------------------------- 端到端生成
def test_end_to_end_air_records_and_override():
    registries = _build_registry_bundle()
    saw_air = False
    saw_water_override = False
    for i in range(60):
        w = generate_world_bundle({}, registries, seed=2000 + i, building_index=i, fragment_count=6)
        for m in w.measurements:
            if m.slot_id == "pressure.drainage.air_test.loss_mmH2O":
                saw_air = True
                assert m.method_class == "air_test"
                assert m.value_num is not None and 0.0 <= m.value_num <= 60.0
                assert set(m.qualifiers or {}) >= {"is_underground", "test_pressure_mmH2O", "acceptable_drop_mmH2O", "duration_min"}
            if m.slot_id in ("index.drainage.blockage", "index.drainage.leakage",
                             "flag.drainage.misconnection_present") and m.method_class == "water_test":
                saw_water_override = True
    assert saw_air, "air_test 专用观测 record 未在批内出现（供给不足→S2.5 调 W0 注入分布）"
    assert saw_water_override, "P2 water_test 覆写既有 index 测量 method_class 未出现"


def test_end_to_end_determinism_same_seed():
    registries = _build_registry_bundle()
    a = generate_world_bundle({}, registries, seed=2222, building_index=3, fragment_count=6)
    b = generate_world_bundle({}, registries, seed=2222, building_index=3, fragment_count=6)
    ka = [(m.measurement_id, m.slot_id, m.method_class, m.value_num, m.value_bool) for m in a.measurements]
    kb = [(m.measurement_id, m.slot_id, m.method_class, m.value_num, m.value_bool) for m in b.measurements]
    assert ka == kb


# ------------------------------ inactive-mechanism 补发回归（codex 终审 019f7513 阻断①）
# spec §2.1b 冻结「P3a/P3b 谓词命中 fragment 必须恰 1 条专用记录」。主循环 active guard 会跳过
# inactive-mechanism fragment，使其命中却零发射（air 缺 3 / ball 缺 2，全 inactive）。发射条件只看
# DrainageState 物理场、与 mechanism.active 解耦 → 补发循环覆盖。下列直调 generate_structural_
# assessment_measurements 构造 active=False 且 blockage>0.5 的 fragment，验证专用记录仍恰 1 条。

_DRN_COMPONENT_ID = "CMP-DRN-INACT-01"


def _inactive_drainage_mechanism(fragment_id: str) -> MechanismState:
    return MechanismState(
        mechanism_state_id="MST-DRN-INACT",
        fragment_id=fragment_id,
        mechanism_family="drainage_fault",
        active=False,  # 关键：inactive → 主循环 active guard 跳过
        severity_index=0.0,
        primary_mechanism_id="MCH-DRN-INACT",
        activated_mechanisms=[],
        drainage_fault_kind="none",
    )


def _active_drainage_mechanism(fragment_id: str) -> MechanismState:
    return MechanismState(
        mechanism_state_id="MST-DRN-ACT",
        fragment_id=fragment_id,
        mechanism_family="drainage_fault",
        active=True,
        severity_index=0.6,
        primary_mechanism_id="MCH-DRN-ACT",
        activated_mechanisms=[],
        drainage_fault_kind="blockage",
    )


def _drainage_fragment(fragment_id: str = "FRG-DRN-INACT-01") -> FragmentContext:
    return FragmentContext(
        fragment_id=fragment_id,
        fragment_template_id="FT_DRAINAGE",
        component_id=_DRN_COMPONENT_ID,
        location_id="LOC-DRN-01",
        fragment_role="inspection_target",
        fragment_area_m2=8.0,
        fragment_length_m=4.0,
        in_scope=True,
        exclusion_reason=None,
    )


def _drainage_component() -> ComponentNode:
    return ComponentNode(
        component_id=_DRN_COMPONENT_ID,
        component_type="drainage_stack",
        parent_component_id=None,
        material_system="reinforced_concrete",
        structural_role="non_load_bearing",
        location_id="LOC-DRN-01",
        geometry_proxy={"visible_area_m2": 8.0, "thickness_mm": 150.0},
        cover_depth_mm=25.0,
        access_class="fully_accessible",
    )


def _building_ctx() -> BuildingContext:
    return BuildingContext(
        building_id="BLD-DRN", building_use="residential", structure_type="rc_frame",
        age_years=45.0, storey_count=8, occupancy_state="occupied",
    )


def _run_assessment(mechanism: MechanismState, drainage: DrainageState):
    fragment = _drainage_fragment(mechanism.fragment_id)
    return generate_structural_assessment_measurements(
        building=_building_ctx(),
        fragments=[fragment],
        conditions=[],
        mechanisms=[mechanism],
        components_by_id={_DRN_COMPONENT_ID: _drainage_component()},
        registries=_build_registry_bundle(),
        world_id="WB-TEST-DRN-0001",
        drainage_by_fragment={fragment.fragment_id: drainage},
    )


def test_inactive_mechanism_air_hit_emits_exactly_one():
    fid = "FRG-DRN-INACT-AIR"
    ms = _run_assessment(
        _inactive_drainage_mechanism(fid),
        _d(drainage_id="DRN-inact-air", blockage_index=0.6, segment_type="soil_pipe"),
    )
    air = [m for m in ms if m.slot_id == "pressure.drainage.air_test.loss_mmH2O"]
    assert len(air) == 1, f"inactive-mechanism air 命中应恰 1 条专用记录，实得 {len(air)}"
    rec = air[0]
    assert rec.method_class == "air_test"
    assert rec.value_num is not None and 0.0 <= rec.value_num <= 60.0
    assert set(rec.qualifiers or {}) >= {
        "is_underground", "test_pressure_mmH2O", "acceptable_drop_mmH2O", "duration_min",
    }
    # inactive fragment 主循环零测量 → 专用记录 measurement_index=0（末位 -00）
    assert rec.measurement_id.endswith("-00")


def test_inactive_mechanism_ball_hit_emits_exactly_one():
    fid = "FRG-DRN-INACT-BALL"
    ms = _run_assessment(
        _inactive_drainage_mechanism(fid),
        _d(drainage_id="DRN-inact-ball", blockage_index=0.6, segment_type="branch_connection"),
    )
    ball = [m for m in ms if m.slot_id == "flag.drainage.ball_test.pass"]
    assert len(ball) == 1, f"inactive-mechanism ball 命中应恰 1 条专用记录，实得 {len(ball)}"
    rec = ball[0]
    assert rec.method_class == "ball_test"
    assert rec.value_bool is not None
    assert rec.measurement_id.endswith("-00")


def test_inactive_mechanism_no_predicate_no_emit():
    # blockage<=0.5 → P4 cctv 兜底，非 air/ball → 零专用记录（补发循环不误发）。
    ms = _run_assessment(
        _inactive_drainage_mechanism("FRG-DRN-INACT-CCTV"),
        _d(drainage_id="DRN-inact-cctv", blockage_index=0.3, segment_type="soil_pipe"),
    )
    assert not [m for m in ms if m.slot_id == "pressure.drainage.air_test.loss_mmH2O"]
    assert not [m for m in ms if m.slot_id == "flag.drainage.ball_test.pass"]


def test_active_mechanism_air_hit_no_double_emit():
    # active fragment 主循环已 emit；补发循环须跳过 → 仍恰 1 条（无重复发射）。
    fid = "FRG-DRN-ACT-AIR"
    ms = _run_assessment(
        _active_drainage_mechanism(fid),
        _d(drainage_id="DRN-act-air", blockage_index=0.6, segment_type="soil_pipe"),
    )
    air = [m for m in ms if m.slot_id == "pressure.drainage.air_test.loss_mmH2O"]
    assert len(air) == 1, f"active-mechanism air 命中应恰 1 条（补发循环不得重复），实得 {len(air)}"
