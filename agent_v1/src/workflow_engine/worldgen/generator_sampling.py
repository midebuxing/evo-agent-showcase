"""Worldgen generator — 抽样计划 / chain 派生子域 helper（spec 06 §8 / §9 / §10 + DEBT-020 chain）.

从 generator.py 拆出（纯代码重组，零改行为）。覆盖：
- coverage / sampling（§8）：visible_area / true_inspected_ratio / check_count
- technical validation（§9）：pull_test_rate / test_strength / verification_failed / additional_after_failure
- structural assessment（§10）：max_condition_severity / fsp_true / core_sample_count / component_volume
- DEBT-020 round5 chain_C_plus 链式派生：facade / plan_intensity / total / effective / inspected ratio chain
- floor-level retiling chain（sub-task 4）
- Missing-Formulas 升 A 类 derive：concrete_repair_depth / fire_door_delay / pull_test_min_stress / hammer_tapping_grid
- building chain seed RNG
- assessment fsp below safety flag

依赖底座（generator_base）：_age_norm / _resolve_sampling_plan_intensity_params /
_resolve_sampling_plan_total_count_clip / _sample_lognormal_arith_mean / _sample_truncated_normal。
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import List, Optional

from workflow_engine.worldgen.models import (
    ComponentNode,
    ConditionState,
    FragmentContext,
    RegistryBundle,
)
from workflow_engine.worldgen.generator_base import (
    _age_norm,
    _resolve_sampling_plan_intensity_params,
    _resolve_sampling_plan_total_count_clip,
    _sample_lognormal_arith_mean,
    _sample_truncated_normal,
)


# spec 06 §8 coverage / sampling surrogate helpers


def _compute_visible_area_m2(fragment_area: float, covered_area: float) -> float:
    """spec 06 §8 visible_area = max(fragment_area - covered_area, 0)."""
    return max(fragment_area - covered_area, 0.0)


def _compute_true_inspected_ratio(inspected_area: float, fragment_area: float) -> float:
    """spec 06 §8 true_inspected_ratio = inspected_area / max(fragment_area, eps)."""
    return inspected_area / max(fragment_area, 1e-9)


def _compute_check_count(fragment_length_m: float, interval_m: float) -> int:
    """spec 06 §8 check_count = ceil(fragment_length_m / interval_m)."""
    if interval_m <= 0:
        return 0
    return max(1, int(math.ceil(fragment_length_m / interval_m)))


# spec 06 §9 technical validation surrogate helpers


def _compute_pull_test_rate_per_25m2(sample_count: int, fragment_area: float) -> float:
    """spec 06 §9 pull_test_rate_per_25m2 = sample_count / max(fragment_area / 25.0, eps)."""
    return sample_count / max(fragment_area / 25.0, 1e-9)


def _compute_test_strength_true(base_strength: float, repair_quality_index: float) -> float:
    """spec 06 §9 test_strength_true = base_strength * (0.5 + repair_quality_index)."""
    return base_strength * (0.5 + repair_quality_index)


def _compute_verification_failed(
    test_strength_reported: float,
    required_strength_proxy: float,
    repair_quality_index: float,
) -> bool:
    """spec 06 §9 verification_failed = (reported < required) or (repair_quality < 0.45)."""
    return test_strength_reported < required_strength_proxy or repair_quality_index < 0.45


def _compute_additional_after_failure_count(
    failure_count: int, additional_multiplier: int = 3
) -> int:
    """spec 06 §9 additional_after_failure_count = failure_count * multiplier."""
    return max(0, failure_count * additional_multiplier)


# spec 06 §10 structural assessment surrogate helpers


def _compute_max_condition_severity(conditions: List[ConditionState]) -> float:
    """spec 06 §10 max_severity = max(condition.severity_index)."""
    if not conditions:
        return 0.0
    return max(condition.severity_index for condition in conditions)


_K_CONDITION_TO_FSP_LOSS = 0.30
_FSP_AGE_DECAY = 0.10


def _compute_fsp_true(
    max_severity: float,
    age_years: float,
) -> float:
    """spec 06 §10 fsp_true = clip(1.20 - k*max_severity - 0.10*age_norm, 0, 2)."""
    age_norm = _age_norm(age_years)
    raw = 1.20 - _K_CONDITION_TO_FSP_LOSS * max_severity - _FSP_AGE_DECAY * age_norm
    return max(0.0, min(2.0, raw))


_CORE_SAMPLE_RATE_PROXY = 0.5


def _compute_core_sample_count(component_volume_m3: float) -> int:
    """spec 06 §10 core_sample_count = ceil(component_volume_m3 * core_sample_rate_proxy)."""
    if component_volume_m3 <= 0:
        return 0
    return max(1, int(math.ceil(component_volume_m3 * _CORE_SAMPLE_RATE_PROXY)))


def _estimate_component_volume_m3(
    fragment: FragmentContext, component: ComponentNode
) -> float:
    """Estimate component volume by visible area * section thickness (mm -> m).

    W0-005 (2026-05-21)：spec 06 §0.1 reference 反查—— `fragment.fragment_area_m2`（spec 04 §7）
    与 `component.geometry_proxy["thickness_mm"]`（spec 04 §5 ComponentNode）.
    """
    thickness_mm = float(component.geometry_proxy.get("thickness_mm") or 0.0)
    return fragment.fragment_area_m2 * thickness_mm / 1000.0


# ---------- DEBT-020 round5 sub-task 2 (2026-05-10) chain_C_plus 链式派生函数 ----------
# 授权：spec 06 §8 + §9 chain 公式 + spec 04 §17 chain input/derived slot 字段合约
#       + `杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L237-L431
#
# 链路（pull_test）：
#   facade-level (building/facade seed RNG):
#     facade_total_repaired_area_m2 ~ lognormal(arithmetic_mean=120, sigma_log=0.75, clip=[20,500])
#     plan_intensity_tests_per_25m2 ~ lognormal(arithmetic_mean=1.25, sigma_log=0.35, clip=[0.50,3.00])
#     total_pull_test_count_per_facade = round_clip(intensity * facade_area / 25, 1, 25)
#   per-fragment:
#     effective_pull_test_count_per_fragment = total_facade_count * frag_repaired_area / facade_area
#     rate.pull_test.per_25m2 = effective_count / max(frag_repaired_area / 25, eps)
#
# 链路（covered_area inspected）：
#   per-fragment (fragment seed RNG):
#     inspected_area_ratio_per_fragment ~ truncated_normal(0.45, 0.18, clip=[0.10, 0.85])
#     inspected_area_m2 = ratio * fragment_area_m2
#     ratio.covered_area.inspected = clip(inspected_area_m2 / fragment_area_m2, 0, 1)


# Chain plan-level constants（必须与 spec 04 §17 + spec 06 §9 + sampling_plan_registry 同步）
_CHAIN_FACADE_AREA_ARITH_MEAN_M2 = 120.0
_CHAIN_FACADE_AREA_SIGMA_LOG = 0.75
_CHAIN_FACADE_AREA_CLIP_LO = 20.0
_CHAIN_FACADE_AREA_CLIP_HI = 500.0

_CHAIN_PLAN_INTENSITY_ARITH_MEAN = 1.25
_CHAIN_PLAN_INTENSITY_SIGMA_LOG = 0.35
_CHAIN_PLAN_INTENSITY_CLIP_LO = 0.50
_CHAIN_PLAN_INTENSITY_CLIP_HI = 3.00

_CHAIN_TOTAL_COUNT_LOWER = 1
_CHAIN_TOTAL_COUNT_UPPER = 25

_CHAIN_INSPECTED_RATIO_MEAN = 0.45
_CHAIN_INSPECTED_RATIO_SIGMA = 0.18
_CHAIN_INSPECTED_RATIO_CLIP_LO = 0.10
_CHAIN_INSPECTED_RATIO_CLIP_HI = 0.85


def _compute_facade_total_repaired_area_m2(
    building_seed_rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> float:
    """spec 06 §9 chain Step 1：facade-level 立面修复总面积（一栋楼共享 building/facade seed RNG）.

    DEBT-030 D2 (2026-05-13): 试 read sampling_plan_registry::pull_test_sampling_plan 的
    basis_area_slot 对应 facade_total_repaired_area_m2 slot 的 distribution; registry 没 plan
    record 时退 hardcoded constants lognormal(arithmetic_mean=120 m², sigma_log=0.75) clip [20, 500].

    facade_total_repaired_area_m2 不是 plan_intensity 自身 (那是 step 2)，而是 basis_area_slot
    指向的 technical_measurement_registry slot;chain helper 这里直接保留 hardcoded constants
    (spec 04 §17 chain input slot, 该 slot 的 distribution 走自己 technical_measurement_registry
    typical 字段；本 helper 是 chain entry point，不替代 slot-level distribution path).
    """
    return _sample_lognormal_arith_mean(
        arithmetic_mean=_CHAIN_FACADE_AREA_ARITH_MEAN_M2,
        sigma_log=_CHAIN_FACADE_AREA_SIGMA_LOG,
        clip_lo=_CHAIN_FACADE_AREA_CLIP_LO,
        clip_hi=_CHAIN_FACADE_AREA_CLIP_HI,
        rng=building_seed_rng,
    )


def _compute_plan_intensity_tests_per_25m2(
    building_seed_rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> float:
    """spec 06 §9 chain Step 2：facade-level plan-intensity tests/25m²（building/facade seed RNG）.

    DEBT-030 D2 (2026-05-13): registry-driven — read sampling_plan_registry::pull_test_sampling_plan
    的 plan_intensity_distribution 4 字段 (recommended_distribution / mean / sigma /
    typical_bounds);  registry 没该 plan_id 时退到 hardcoded constants lognormal(1.25, 0.35)
    clip [0.50, 3.00].
    """
    params = _resolve_sampling_plan_intensity_params(
        sampling_plan_id="pull_test_sampling_plan",
        registries=registries,
        fallback_distribution="lognormal",
        fallback_mean=_CHAIN_PLAN_INTENSITY_ARITH_MEAN,
        fallback_sigma=_CHAIN_PLAN_INTENSITY_SIGMA_LOG,
        fallback_clip_lo=_CHAIN_PLAN_INTENSITY_CLIP_LO,
        fallback_clip_hi=_CHAIN_PLAN_INTENSITY_CLIP_HI,
    )
    return _sample_lognormal_arith_mean(
        arithmetic_mean=params["recommended_mean"],
        sigma_log=params["recommended_sigma"],
        clip_lo=params["typical_bounds"][0],
        clip_hi=params["typical_bounds"][1],
        rng=building_seed_rng,
    )


def _compute_total_pull_test_count_per_facade(
    plan_intensity: float,
    facade_total_repaired_area_m2: float,
    registries: Optional[RegistryBundle] = None,
) -> int:
    """spec 06 §9 chain Step 3：plan_derived_rounded_lognormal_intensity.

    DEBT-030 D2 (2026-05-13): registry-driven — read sampling_plan_registry::pull_test_sampling_plan
    的 total_count_formula round_clip lower/upper; registry 没该 plan_id 时退 hardcoded [1, 25].

    total_pull_test_count_per_facade = round_clip(plan_intensity * facade_area / 25.0, 1, 25).
    """
    lower, upper = _resolve_sampling_plan_total_count_clip(
        sampling_plan_id="pull_test_sampling_plan",
        registries=registries,
        fallback_lower=_CHAIN_TOTAL_COUNT_LOWER,
        fallback_upper=_CHAIN_TOTAL_COUNT_UPPER,
    )
    raw_count = plan_intensity * facade_total_repaired_area_m2 / 25.0
    return max(lower, min(upper, int(round(raw_count))))


def _compute_effective_pull_test_count_per_fragment(
    total_pull_test_count_per_facade: float,
    fragment_repaired_area_m2: float,
    facade_total_repaired_area_m2: float,
) -> float:
    """spec 06 §9 chain Step 4：area-proportional 分配（A 类 chain derived，无 distribution）.

    effective_pull_test_count_per_fragment =
      total_pull_test_count_per_facade * fragment_repaired_area_m2 / max(facade_total_repaired_area_m2, eps).

    Option C+ 关键反爆炸保护：可非整数（按 area share 分配）.
    """
    return float(total_pull_test_count_per_facade) * float(fragment_repaired_area_m2) / max(
        float(facade_total_repaired_area_m2), 1e-9
    )


def _compute_pull_test_rate_per_25m2_chain(
    effective_pull_test_count_per_fragment: float,
    fragment_repaired_area_m2: float,
) -> float:
    """spec 06 §9 chain Step 5：rate derive（A 类 chain derived，无 distribution）.

    rate.pull_test.per_25m2 =
      effective_pull_test_count_per_fragment / max(fragment_repaired_area_m2 / 25.0, eps).

    代数等价：rate = total_pull_test_count_per_facade / max(facade_total_repaired_area_m2 / 25.0, eps).
    → 1m² fragment 不爆炸（与 fragment_area 解耦）.
    """
    return float(effective_pull_test_count_per_fragment) / max(
        float(fragment_repaired_area_m2) / 25.0, 1e-9
    )


def _compute_inspected_area_ratio_per_fragment(
    rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> float:
    """spec 06 §8 chain Step 1：per-fragment inspected_area_ratio（fragment seed RNG）.

    DEBT-030 D2 (2026-05-13): registry-driven — read sampling_plan_registry::coverage_inspection_plan
    的 plan_intensity_distribution (truncated_normal mean=0.45 sigma=0.18 typical=[0.10, 0.85]);
    registry 没该 plan_id 时退 hardcoded constants.
    """
    params = _resolve_sampling_plan_intensity_params(
        sampling_plan_id="coverage_inspection_plan",
        registries=registries,
        fallback_distribution="truncated_normal",
        fallback_mean=_CHAIN_INSPECTED_RATIO_MEAN,
        fallback_sigma=_CHAIN_INSPECTED_RATIO_SIGMA,
        fallback_clip_lo=_CHAIN_INSPECTED_RATIO_CLIP_LO,
        fallback_clip_hi=_CHAIN_INSPECTED_RATIO_CLIP_HI,
    )
    return _sample_truncated_normal(
        mean=params["recommended_mean"],
        sigma=params["recommended_sigma"],
        clip_lo=params["typical_bounds"][0],
        clip_hi=params["typical_bounds"][1],
        rng=rng,
    )


def _compute_inspected_area_m2_chain(
    inspected_area_ratio_per_fragment: float,
    fragment_area_m2: float,
) -> float:
    """spec 06 §8 chain Step 2：inspected_area_m2 = ratio * fragment_area（A 类 chain derived）."""
    return float(inspected_area_ratio_per_fragment) * float(fragment_area_m2)


def _compute_ratio_covered_area_inspected_chain(
    inspected_area_m2: float,
    fragment_area_m2: float,
) -> float:
    """spec 06 §8 chain Step 3：ratio.covered_area.inspected derive（A 类 chain derived）.

    clip(inspected_area_m2 / max(fragment_area_m2, eps), 0.0, 1.0).
    """
    raw_ratio = float(inspected_area_m2) / max(float(fragment_area_m2), 1e-9)
    return max(0.0, min(1.0, raw_ratio))


def _building_chain_seed_rng(building_id: str) -> random.Random:
    """从 building_id 派生 deterministic RNG，让 facade-level chain 数据一栋楼共享.

    对同一 building_id（同一立面），多次调用得到同样的 facade_total_repaired_area /
    plan_intensity → total_pull_test_count_per_facade 是稳定的，per-fragment 分配
    才有意义。chain seed 与 fragment seed 解耦.

    DEBT-codex-finding-2 (2026-05-27): 用 SHA-256 替代 Python ``hash()``——
    后者每个解释器进程加盐不同，导致跨进程 / 跨跑批不可复现，违反 spec T-17.6。
    """
    payload = f"CHAIN_FACADE_PLAN_v1:{building_id}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**31)
    return random.Random(seed)


# ---------- DEBT-049 Phase3 U5 §2.1a/§2.1b drainage 地上地下判别 + air/ball 观测子流 ----------
# 两者复用 _building_chain_seed_rng 同一 SHA-256 口径（int.from_bytes(digest[:8],"big")），
# 但走**独立 domain 串**（DRAINAGE_UNDERGROUND_v1: / DRAINAGE_AIRBALL_OBS_v1:）——与立面级
# CHAIN_FACADE_PLAN_v1: 及 fragment seed 三处 domain-separated、互不串扰，既有随机序列零扰动。
# is_underground 为总函数（不消费 RNG），air/ball 观测数值抖动走 airball 子流（不碰 caller 的
# fragment/generic rng）。散列常量（35/0.5/公式常量）硬冻结、禁现场调参（须走 spec revision + manifest）。

_DRAINAGE_UNDERGROUND_PCT = 35  # §2.1a 地下占比%（硬冻结；改须走 spec revision + manifest）


def _drainage_is_underground(drainage_id: str) -> bool:
    """§2.1a 地上/地下判别（确定性散列派生，总函数，不消费 RNG）。

    ``SHA256("DRAINAGE_UNDERGROUND_v1:"+drainage_id)[:8] → big-endian uint64 → %100 < 35``。
    不读取 ``segment_type``（散列独立轴，与 stack/branch 正交轴分离，供 air 两压力档可达）。
    """
    payload = f"DRAINAGE_UNDERGROUND_v1:{drainage_id}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (bucket % 100) < _DRAINAGE_UNDERGROUND_PCT


def _drainage_airball_obs_rng(drainage_id: str) -> random.Random:
    """§2.1b air/ball 观测数值抖动的独立 domain-separated 子流。

    照 ``_building_chain_seed_rng`` 同一 SHA-256 口径、domain 串 ``DRAINAGE_AIRBALL_OBS_v1:``。
    **不复用立面级 chain RNG**（复用会消费同一 RNG 序列、扰动其后 facade-chain 抽样字节流）；
    只作用于 air 的 ``pressure_loss_mmH2O`` jitter 与 ball 的 ``ball_fail_score`` jitter。
    """
    payload = f"DRAINAGE_AIRBALL_OBS_v1:{drainage_id}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**31)
    return random.Random(seed)


# ---------- DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas 升 A 类 derive helpers ----------
# 授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1232-L1546
# 7 个 B 类 slot 升 A 类（spec 04 §17 + spec 06 §X.X 公式 derive）：
#   - length.concrete_repair.depth (line 1309-1340)
#   - time.fire_door.self_closing.delay_sec (line 1368-1396)
#   - stress.pull_test.minimum (line 1398-1425)
#   - count.hammer_tapping.grid.minimum (line 1479-1510)
#   - count.pull_test.per_repaired_facade (line 1238-1264) — 复用 #2 chain
#   - count.pull_test.per_floor_full_retiling (line 1266-1292) — 新 floor-level chain
#   - ratio.rebar.section_loss (line 1427-1477) — 实现在 sub-task 6 (per-class lognormal)


def _compute_concrete_repair_depth_mm(
    cover_depth_mm: Optional[float],
    spall_severity_index: float,
    corrosion_severity_index: float,
    chloride_exposure_index: float,
) -> float:
    """spec 06 §X.X (DEBT-020 round5 sub-task 4): length.concrete_repair.depth derive.

    公式（pro `回复.md`:L1314-L1328 逐字翻译）：
      cover_deficit_factor = clip((30 - cover) / 30, 0, 1)
      length.concrete_repair.depth =
        clip(cover + 8 + 52*spall + 18*corrosion + 8*cover_deficit + 6*max(chloride - 0.5, 0), 5, 180)

    Inputs (spec 04 §17 列表)：cover_depth_mm / spall_severity_index / corrosion_severity_index /
    chloride_exposure_index. cover_depth_mm 缺失（None）时取 mid 25mm 代理（fragment 物理无 cover 数据时
    fallback；driver chloride / corrosion 仍主导）.

    MC sanity (容忍 ±10%)：mean=66, p5/p95=[20, 125].
    """
    cover = float(cover_depth_mm) if cover_depth_mm is not None else 25.0
    cover_deficit_factor = max(0.0, min(1.0, (30.0 - cover) / 30.0))
    raw = (
        cover
        + 8.0
        + 52.0 * float(spall_severity_index)
        + 18.0 * float(corrosion_severity_index)
        + 8.0 * cover_deficit_factor
        + 6.0 * max(float(chloride_exposure_index) - 0.50, 0.0)
    )
    return max(5.0, min(180.0, raw))


def _compute_fire_door_self_closing_delay_sec(
    maintenance_deficit_index: float,
    age_norm: float,
    moisture_ingress_index: float,
    fire_safety_deficiency_present: bool,
) -> float:
    """spec 06 §X.X (DEBT-020 round5 sub-task 4): time.fire_door.self_closing.delay_sec derive.

    公式（pro `回复.md`:L1373-L1383）：
      delay_sec = clip(2 + 4*maintenance + 2*age_norm + 2*moisture + 6*fire_safety_def, 0, 60)

    Applicability: component_type == fire_door OR fragment_scope == fire_safety
    （caller 端按 mechanism / component 判断；本 helper 不强制 applicability check）.

    MC sanity: mean=6.4, p5/p95=[2.0, 18.0].
    """
    raw = (
        2.0
        + 4.0 * float(maintenance_deficit_index)
        + 2.0 * float(age_norm)
        + 2.0 * float(moisture_ingress_index)
        + 6.0 * (1.0 if fire_safety_deficiency_present else 0.0)
    )
    return max(0.0, min(60.0, raw))


def _compute_pull_test_minimum_stress_n_per_mm2(
    repair_quality_index: float,
    moisture_ingress_index: float,
    workmanship_deficit_index: float,
) -> float:
    """spec 06 §X.X (DEBT-020 round5 sub-task 4): stress.pull_test.minimum derive.

    公式（pro `回复.md`:L1404-L1414）：
      base = 0.85
      stress = clip(base * (0.45 + 0.95 * repair_quality)
                    - 0.12 * moisture
                    - 0.10 * workmanship,
                    0.10, 2.50)

    MC sanity: mean=0.78, p5/p95=[0.30, 1.35].
    """
    base = 0.85
    raw = (
        base * (0.45 + 0.95 * float(repair_quality_index))
        - 0.12 * float(moisture_ingress_index)
        - 0.10 * float(workmanship_deficit_index)
    )
    return max(0.10, min(2.50, raw))


def _compute_hammer_tapping_grid_minimum(
    nominal_visible_area_m2: float,
    fragment_area_m2: float,
    detachment_severity_index: float,
    spall_severity_index: float,
) -> int:
    """spec 06 §X.X (DEBT-020 round5 sub-task 4): count.hammer_tapping.grid.minimum derive.

    公式（pro `回复.md`:L1485-L1498）：
      effective_area = max(visible, fragment * 0.50)
      cell_area = clip(0.60 - 0.15 * detachment - 0.10 * spall, 0.35, 0.80)
      count = ceil_clip(effective / cell_area, 5, 150)

    MC sanity: mean=52, p5/p95=[12, 110].
    """
    effective_area = max(float(nominal_visible_area_m2), float(fragment_area_m2) * 0.50)
    cell_area = max(
        0.35,
        min(
            0.80,
            0.60
            - 0.15 * float(detachment_severity_index)
            - 0.10 * float(spall_severity_index),
        ),
    )
    raw_count = math.ceil(effective_area / max(cell_area, 1e-9))
    return max(5, min(150, int(raw_count)))


# ---------- floor-level retiling chain helpers (sub-task 4: count.pull_test.per_floor_full_retiling) ----------

_FLOOR_RETILING_AREA_ARITH_MEAN_M2 = 80.0
_FLOOR_RETILING_AREA_SIGMA_LOG = 0.65
_FLOOR_RETILING_AREA_CLIP_LO = 10.0
_FLOOR_RETILING_AREA_CLIP_HI = 400.0

_FLOOR_RETILING_INTENSITY_ARITH_MEAN = 1.35
_FLOOR_RETILING_INTENSITY_SIGMA_LOG = 0.30
_FLOOR_RETILING_INTENSITY_CLIP_LO = 0.60
_FLOOR_RETILING_INTENSITY_CLIP_HI = 3.00

_FLOOR_RETILING_TOTAL_COUNT_LOWER = 1
_FLOOR_RETILING_TOTAL_COUNT_UPPER = 20


def _compute_floor_full_retiling_area_m2(
    building_seed_rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> float:
    """spec 06 §X.X (sub-task 4) chain Step 1: floor-level retiling 总面积.

    DEBT-030 D2 (2026-05-13): floor_full_retiling_area_m2 是 basis_area_slot (technical_measurement_registry
    chain input slot), 该 slot 自己 distribution 走 typical 字段; 本 helper 是 chain entry point,
    维持 hardcoded constants lognormal(80, 0.65) clip [10, 400] (与 spec 11_inventory §4.1 一致).
    Building/floor seed RNG 共享，让同一 building 多次调用得到稳定 retiling area.
    """
    return _sample_lognormal_arith_mean(
        arithmetic_mean=_FLOOR_RETILING_AREA_ARITH_MEAN_M2,
        sigma_log=_FLOOR_RETILING_AREA_SIGMA_LOG,
        clip_lo=_FLOOR_RETILING_AREA_CLIP_LO,
        clip_hi=_FLOOR_RETILING_AREA_CLIP_HI,
        rng=building_seed_rng,
    )


def _compute_retiling_plan_intensity_tests_per_25m2(
    building_seed_rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> float:
    """spec 06 §X.X (sub-task 4) chain Step 2: floor-level plan-intensity tests/25m².

    DEBT-030 D2 (2026-05-13): registry-driven — read sampling_plan_registry::floor_retiling_package
    的 plan_intensity_distribution (lognormal mean=1.35 sigma=0.30 typical=[0.60, 3.00]);
    registry 没该 plan_id 时退 hardcoded constants.
    """
    params = _resolve_sampling_plan_intensity_params(
        sampling_plan_id="floor_retiling_package",
        registries=registries,
        fallback_distribution="lognormal",
        fallback_mean=_FLOOR_RETILING_INTENSITY_ARITH_MEAN,
        fallback_sigma=_FLOOR_RETILING_INTENSITY_SIGMA_LOG,
        fallback_clip_lo=_FLOOR_RETILING_INTENSITY_CLIP_LO,
        fallback_clip_hi=_FLOOR_RETILING_INTENSITY_CLIP_HI,
    )
    return _sample_lognormal_arith_mean(
        arithmetic_mean=params["recommended_mean"],
        sigma_log=params["recommended_sigma"],
        clip_lo=params["typical_bounds"][0],
        clip_hi=params["typical_bounds"][1],
        rng=building_seed_rng,
    )


def _compute_pull_test_count_per_floor_full_retiling(
    retiling_plan_intensity: float,
    floor_full_retiling_area_m2: float,
    registries: Optional[RegistryBundle] = None,
) -> int:
    """spec 06 §X.X (sub-task 4) chain Step 3: count.pull_test.per_floor_full_retiling derive.

    DEBT-030 D2 (2026-05-13): registry-driven — read sampling_plan_registry::floor_retiling_package
    的 total_count_formula round_clip lower/upper; registry 没 plan 时退 hardcoded [1, 20].

    count = round_clip(intensity * floor_retiling_area / 25.0, 1, 20).
    """
    lower, upper = _resolve_sampling_plan_total_count_clip(
        sampling_plan_id="floor_retiling_package",
        registries=registries,
        fallback_lower=_FLOOR_RETILING_TOTAL_COUNT_LOWER,
        fallback_upper=_FLOOR_RETILING_TOTAL_COUNT_UPPER,
    )
    raw_count = float(retiling_plan_intensity) * float(floor_full_retiling_area_m2) / 25.0
    return max(lower, min(upper, int(round(raw_count))))


def _is_assessment_fsp_below_required_safety(
    fsp_true: float,
    fsp_floor_proxy: float = 0.95,
) -> bool:
    """spec 06 §11 derived flag: fsp < floor proxy."""
    return fsp_true < fsp_floor_proxy
