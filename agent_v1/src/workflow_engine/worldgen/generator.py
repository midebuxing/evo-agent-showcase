"""Worldgen building-centric generator (T-17a + T-17b entry).

T-17a scope：building shell 生成（pure function 形态，T-17.6 决策）：
- archetype 抽样（T-17.2）—— 按 batch_config["archetype_distribution"] 分布
- BuildingContext 构造（T-17.3）—— 从 building_template_registry
- ComponentNode + LocationNode 列表（T-17.3）—— 从 component_type_registry / location_class_registry

T-17b scope：per-fragment 状态生成（pure function）：
- FragmentContext（按 fragment_template_registry 选模板；spec 04 §7 9 字段 reference-based contract）
- DriverState / MechanismState / ConditionState 每 fragment 一个
- DrainageState / UBWState / FireSafetyState 按 mechanism family 选择性生成
- RepairAssessmentState 每 fragment 一个（默认 placeholder）
- CoverageRelation 按 coverage_relation_registry 派生
- measurements 仍空（T-17c 才填）

**T-17a + T-17b 不替换现有 entry**：`hydration._build_worlds` 仍是 worldgen 主入口；
此模块仅新增、不删除任何 legacy。T-17d 收尾时切换 entry 并删 legacy。

设计口径：
- 全 pure function（T-17.6）：函数签名 `generate_X(input1, input2, ...) -> result`
- registry-driven（T-17.3）：所有结构数据来自 registries，无 hardcoded business data
- 工程辅助：`_archetype_component_plan` 是 hardcoded plan（T-09a 字段 component_graph_template_ids
  在 building_template_registry 当前为空 []，本模块用 hardcoded plan 占位；后续工单可把 plan
  移入 registry table）
"""

from __future__ import annotations

import math
import hashlib
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # 仅注解用（BatchGateStats 定义在 gates），避免运行时循环 import
    from workflow_engine.worldgen.gates import BatchGateStats

import workflow_engine.worldgen.checks  # noqa: F401  — T-22: registers C001-C022 gate checks
from workflow_engine.worldgen import rng_domains

# QA-Parallelize 2026-05-09: cross-building ProcessPool worker globals.
# 大 registries 一次性 pickle 到 worker 进程的 module-level globals（在 initializer 里），
# 后续每个 task 只传 building_index，避免 task-by-task 重复序列化大对象.
_WORKER_BATCH_CONFIG: Optional[Dict[str, Any]] = None
_WORKER_REGISTRIES: Optional[Any] = None  # RegistryBundle 但 forward ref 避免循环
_WORKER_SEED: int = 0
_WORKER_FRAGMENT_COUNT: int = 4


def _building_worker_init(
    batch_config: Dict[str, Any],
    registries: Any,
    seed: int,
    fragment_count: int,
) -> None:
    """ProcessPoolExecutor initializer — 把大 registries 装到 worker globals 一次."""
    global _WORKER_BATCH_CONFIG, _WORKER_REGISTRIES, _WORKER_SEED, _WORKER_FRAGMENT_COUNT
    _WORKER_BATCH_CONFIG = batch_config
    _WORKER_REGISTRIES = registries
    _WORKER_SEED = seed
    _WORKER_FRAGMENT_COUNT = fragment_count


def _building_worker_task(building_index: int) -> Any:
    """Task function: 在 worker 进程内调 generate_world_bundle (用 globals 避免重 pickle).

    P2 audit: 本 worker **不 wrap** ``audit_capture()`` — 入口是 ``generate_world_batch``
    (no-stats path), caller 不收 BatchGateStats 即不需 P2 audit trace. 若后续 ``generate_world_batch``
    扩展 stats 返回值, 此 worker 需自 set worker-local P2AuditAccumulator + 通过 stats.to_dict()
    跨进程 round-trip (见 W1 spec 07 §4 line 70-75 + p2_audit.py audit_capture docstring 跨进程示例).
    """
    return generate_world_bundle(
        batch_config=_WORKER_BATCH_CONFIG,
        registries=_WORKER_REGISTRIES,
        seed=_WORKER_SEED,
        building_index=building_index,
        fragment_count=_WORKER_FRAGMENT_COUNT,
    )

from workflow_engine.worldgen.constants import (
    DEFAULT_BATCH_RANDOM_SEED,
    GENERATOR_VERSION,
)
from workflow_engine.worldgen.noise_models import (
    apply_named_noise,
    apply_precision_rounding,
    get_noise_model_for_family,
)
# DEBT-030 C 组 / spec 07 §4 line 70 P2 inline clamp audit hook（ContextVar 全局，
# 跨 inline clip 位置共享 worker-local accumulator；ProcessPool worker 自家 set context）.
from workflow_engine.worldgen.p2_audit import (
    P2AuditAccumulator,
    audit_capture,
    get_p2_audit_context as _get_p2_audit_accumulator,
    CHECK_ID_COUNT_NONNEG_CLAMP as _CHECK_ID_COUNT_NONNEG_CLAMP,
    CHECK_ID_PRECISION_ROUNDING as _CHECK_ID_PRECISION_ROUNDING,
    CHECK_ID_TYPICAL_BOUNDS_CLIP as _CHECK_ID_TYPICAL_BOUNDS_CLIP,
)
from workflow_engine.worldgen.models import (
    BuildingContext,
    BuildingMetadata,
    WorldBundle,
    ComponentNode,
    ConditionState,
    CoverageRelation,
    DrainageState,
    DriverState,
    FireSafetyState,
    FragmentContext,
    LocationNode,
    MeasurementRecord,
    MechanismActivation,
    MechanismState,
    RegistryBundle,
    RegistryTable,
    RepairAssessmentState,
    UBWState,
)

# ---------- 子域模块 re-export（generator.py 拆分后保持向后兼容） ----------
# 共享底座 helper / 数学原语 / 采样原语 / registry 访问层（generator_base），以及
# 缺陷几何 / 排水 / 违建 / 消防 / 抽样链 子域 helper —— 全部 re-export，保证外部
# `from workflow_engine.worldgen.generator import X` 与旧 import 路径继续可用。
from workflow_engine.worldgen.generator_base import (
    _get_registry,
    _registry_records,
    _registry_index,
    _REGISTRY_LOOKUP_CACHE,
    _get_lookup_cache,
    _set_lookup_cache,
    _lookup_primary_condition_class_from_mechanism_family,
    _lookup_fire_component_class_from_component_type,
    _domain_of_component_type,
    _material_system_supports_rebar,
    _lookup_sampling_plan_record,
    _resolve_sampling_plan_intensity_params,
    _resolve_sampling_plan_total_count_clip,
    _parse_keyword_int,
    _weighted_choice,
    _sanitize_id_component,
    _sigmoid,
    _age_norm,
    _cover_norm,
    _ALLOWED_LOGNORMAL_MEAN_SEMANTICS,
    _resolve_lognormal_mu,
    _sample_lognormal_arith_mean,
    _sample_truncated_normal,
)
from workflow_engine.worldgen.generator_defect import (
    _CRACK_ACTIVATION_BIAS,
    _ALPHA_SERVICE_LOAD,
    _ALPHA_RESTRAINT,
    _ALPHA_WORKMANSHIP,
    _K_OPENING_BASE_MM,
    _K_OPENING_FROM_ACTIVATION_MM,
    _K_LENGTH_SCALE,
    _CRACK_WIDTH_HARD_CAP_MM,
    _CRACK_OPENING_HARD_FLOOR_MM,
    _CRACK_LENGTH_HARD_FLOOR_M,
    _CORROSION_BIAS,
    _BETA_CHLORIDE,
    _BETA_CARBONATION,
    _BETA_MOISTURE,
    _BETA_AGE,
    _BETA_COVER_PENALTY,
    _K_COVER_LOSS_BASE_MM,
    _K_COVER_LOSS_SCALE,
    _K_SPALL_AREA_SCALE,
    _REBAR_EXPOSURE_OFFSET_MM,
    _REBAR_SPACING_PROXY_M,
    _REBAR_EXPOSED_LENGTH_THRESHOLD_M,
    _REBAR_SECTION_LOSS_PER_CLASS,
    _REBAR_TYPE_PREVALENCE_DEFAULT,
    _REBAR_TYPE_PREVALENCE_BY_STRUCTURAL_ROLE,
    _REBAR_LOCATION_BY_FRAGMENT_SCOPE_AND_ROLE,
    _CORROSION_LOSS_TYPE_PREVALENCE_DEFAULT,
    _compute_crack_score,
    _compute_spall_score,
    _compute_detachment_score,
    _compute_crack_activation_score,
    _compute_crack_severity,
    _compute_primary_crack_opening_mm_true,
    _compute_primary_crack_length_m_true,
    _compute_corrosion_severity,
    _compute_delamination_severity,
    _compute_cover_loss_depth_mm,
    _compute_spall_patch_area_m2,
    _compute_rebar_exposed_length_m,
    _is_rebar_exposed_bool,
    _sample_rebar_type,
    _sample_rebar_location,
    _sample_corrosion_loss_type,
    _compute_rebar_section_loss_ratio_per_class,
)
from workflow_engine.worldgen.generator_drainage import (
    _compute_drainage_blockage_index,
    _compute_drainage_leakage_index,
    _compute_drainage_misconnection_present,
    _compute_drainage_public_health_risk_index,
    # DEBT-049 Phase3 U5 §2.1：drainage method_class 选取 + air/ball 物理观测
    _select_drainage_method_class,
    _air_test_qualifiers,
    _compute_air_test_pressure_loss_mmH2O,
    _compute_ball_test_pass,
    # DEBT-049 Phase3 U5 §2.1 S2.5 防死档：drainage 域 alteration 采样上界标定
    _DRAINAGE_DRIVER_ALTERATION_HI,
)
from workflow_engine.worldgen.generator_ubw import (
    _compute_ubw_alteration_score,
    _compute_ubw_subdivided_unit_sign_present,
    _compute_ubw_structural_impact_index,
)
from workflow_engine.worldgen.generator_fire import (
    _FIRE_COMPONENT_IMPORTANCE_WEIGHTS,
    _compute_fire_deficiency_score,
    _is_fire_deficiency_present,
    _compute_fire_severity_index,
)
from workflow_engine.worldgen.generator_sampling import (
    _K_CONDITION_TO_FSP_LOSS,
    _FSP_AGE_DECAY,
    _CORE_SAMPLE_RATE_PROXY,
    _CHAIN_FACADE_AREA_ARITH_MEAN_M2,
    _CHAIN_FACADE_AREA_SIGMA_LOG,
    _CHAIN_FACADE_AREA_CLIP_LO,
    _CHAIN_FACADE_AREA_CLIP_HI,
    _CHAIN_PLAN_INTENSITY_ARITH_MEAN,
    _CHAIN_PLAN_INTENSITY_SIGMA_LOG,
    _CHAIN_PLAN_INTENSITY_CLIP_LO,
    _CHAIN_PLAN_INTENSITY_CLIP_HI,
    _CHAIN_TOTAL_COUNT_LOWER,
    _CHAIN_TOTAL_COUNT_UPPER,
    _CHAIN_INSPECTED_RATIO_MEAN,
    _CHAIN_INSPECTED_RATIO_SIGMA,
    _CHAIN_INSPECTED_RATIO_CLIP_LO,
    _CHAIN_INSPECTED_RATIO_CLIP_HI,
    _FLOOR_RETILING_AREA_ARITH_MEAN_M2,
    _FLOOR_RETILING_AREA_SIGMA_LOG,
    _FLOOR_RETILING_AREA_CLIP_LO,
    _FLOOR_RETILING_AREA_CLIP_HI,
    _FLOOR_RETILING_INTENSITY_ARITH_MEAN,
    _FLOOR_RETILING_INTENSITY_SIGMA_LOG,
    _FLOOR_RETILING_INTENSITY_CLIP_LO,
    _FLOOR_RETILING_INTENSITY_CLIP_HI,
    _FLOOR_RETILING_TOTAL_COUNT_LOWER,
    _FLOOR_RETILING_TOTAL_COUNT_UPPER,
    _compute_visible_area_m2,
    _compute_true_inspected_ratio,
    _compute_check_count,
    _compute_pull_test_rate_per_25m2,
    _compute_test_strength_true,
    _compute_verification_failed,
    _compute_additional_after_failure_count,
    _compute_max_condition_severity,
    _compute_fsp_true,
    _compute_core_sample_count,
    _estimate_component_volume_m3,
    _compute_facade_total_repaired_area_m2,
    _compute_plan_intensity_tests_per_25m2,
    _compute_total_pull_test_count_per_facade,
    _compute_effective_pull_test_count_per_fragment,
    _compute_pull_test_rate_per_25m2_chain,
    _compute_inspected_area_ratio_per_fragment,
    _compute_inspected_area_m2_chain,
    _compute_ratio_covered_area_inspected_chain,
    _building_chain_seed_rng,
    # DEBT-049 Phase3 U5 §2.1a/§2.1b：drainage 地上地下判别 + air/ball 观测独立子流
    _drainage_is_underground,
    _drainage_airball_obs_rng,
    _compute_concrete_repair_depth_mm,
    _compute_fire_door_self_closing_delay_sec,
    _compute_pull_test_minimum_stress_n_per_mm2,
    _compute_hammer_tapping_grid_minimum,
    _compute_floor_full_retiling_area_m2,
    _compute_retiling_plan_intensity_tests_per_25m2,
    _compute_pull_test_count_per_floor_full_retiling,
    _is_assessment_fsp_below_required_safety,
)


# ---------- archetype + component plan ----------


_ARCHETYPE_CONFIGURATION_TAGS: Dict[str, List[str]] = {
    # T-30 pro 派活 (2026-05-12) BT 迁名后保留 mvp 5 个 archetype 的 tag 配置，其余 10 个新 BT_HK_* 走 fallback ["regular"]
    "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1": ["regular", "podium", "signboard_present"],
    "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1": ["podium", "drainage_complex"],
    "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1": ["regular", "canopy_present"],
    "BT_HK_UBW_PRONE_OLD_BLOCK_V1": ["regular", "canopy_present"],
    "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1": ["irregular", "canopy_present", "slope_adjacent"],
    "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1": ["regular", "podium"],
}


def _archetype_configuration_tags(template_id: str) -> List[str]:
    return list(_ARCHETYPE_CONFIGURATION_TAGS.get(template_id, ["regular"]))


# Per-archetype component plan (T-17a hardcoded placeholder).
# Each entry: (component_type, structural_role, location_class, exposure_zone, storey_band)
# 后续工单可把 plan 移入 building_template_registry.component_graph_template_ids 引用的
# component_graph_template registry table。
_BASE_COMPONENT_PLAN: List[Dict[str, str]] = [
    {"component_type": "external_wall", "structural_role": "secondary_load_bearing",
     "location_class": "external_wall", "exposure_zone": "exterior_weather", "storey_band": "mid_zone"},
    {"component_type": "structural_member", "structural_role": "primary_load_bearing",
     "location_class": "common_part", "exposure_zone": "interior_dry", "storey_band": "mid_zone"},
    {"component_type": "structural_member", "structural_role": "primary_load_bearing",
     "location_class": "transfer_floor", "exposure_zone": "interior_dry", "storey_band": "low_zone"},
    {"component_type": "drainage_stack", "structural_role": "service_component",
     "location_class": "pipe_duct", "exposure_zone": "interior_wet", "storey_band": "mid_zone"},
    {"component_type": "drainage_branch", "structural_role": "service_component",
     "location_class": "private_lane", "exposure_zone": "exterior_weather", "storey_band": "low_zone"},
    {"component_type": "fire_door", "structural_role": "non_load_bearing",
     "location_class": "escape_stair", "exposure_zone": "interior_dry", "storey_band": "mid_zone"},
]


_ARCHETYPE_EXTRA_COMPONENTS: Dict[str, List[Dict[str, str]]] = {
    # T-30 pro 派活 (2026-05-12) BT 迁名后保留 mvp 5 个 archetype 的 extra components，其余 10 个新 BT_HK_* 走 fallback (只用 _BASE_COMPONENT_PLAN，不加 extra)
    # LEGACY_RESIDENTIAL 1:N split：fire_door extra 归 BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1；unauthorized_structure extra 归 BT_HK_UBW_PRONE_OLD_BLOCK_V1
    "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1": [
        {"component_type": "signboard", "structural_role": "non_load_bearing",
         "location_class": "external_wall", "exposure_zone": "exterior_weather", "storey_band": "low_zone"},
        # spec 草案·DEBT-049 第一波 §3 贴砖案A。
        {"component_type": "wall_tile_finish", "structural_role": "finish_only",
         "location_class": "external_wall", "exposure_zone": "exterior_weather", "storey_band": "mid_zone"},
        {"component_type": "canopy", "structural_role": "non_load_bearing",
         "location_class": "podium_soffit", "exposure_zone": "exterior_weather", "storey_band": "low_zone"},
    ],
    "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1": [
        {"component_type": "drainage_branch", "structural_role": "service_component",
         "location_class": "service_void", "exposure_zone": "interior_wet", "storey_band": "low_zone"},
        {"component_type": "canopy", "structural_role": "non_load_bearing",
         "location_class": "podium_soffit", "exposure_zone": "exterior_weather", "storey_band": "low_zone"},
    ],
    "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1": [
        {"component_type": "fire_door", "structural_role": "non_load_bearing",
         "location_class": "common_part", "exposure_zone": "interior_dry", "storey_band": "mid_zone"},
        # spec 草案·DEBT-049 第一波 §3 贴砖案A。
        {"component_type": "wall_tile_finish", "structural_role": "finish_only",
         "location_class": "external_wall", "exposure_zone": "exterior_weather", "storey_band": "mid_zone"},
    ],
    "BT_HK_UBW_PRONE_OLD_BLOCK_V1": [
        {"component_type": "unauthorized_structure", "structural_role": "non_load_bearing",
         "location_class": "external_wall", "exposure_zone": "exterior_weather", "storey_band": "high_zone"},
    ],
    "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1": [
        {"component_type": "balcony_slab", "structural_role": "secondary_load_bearing",
         "location_class": "balcony_line", "exposure_zone": "exterior_weather", "storey_band": "mid_zone"},
        {"component_type": "parapet_wall", "structural_role": "non_load_bearing",
         "location_class": "roof_edge", "exposure_zone": "exterior_weather", "storey_band": "roof"},
    ],
    "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1": [
        {"component_type": "structural_member", "structural_role": "primary_load_bearing",
         "location_class": "podium_soffit", "exposure_zone": "exterior_weather", "storey_band": "low_zone"},
        {"component_type": "structural_member", "structural_role": "primary_load_bearing",
         "location_class": "transfer_floor", "exposure_zone": "interior_dry", "storey_band": "low_zone"},
    ],
}


def _archetype_component_plan(template_id: str) -> List[Dict[str, str]]:
    """Return per-archetype component plan (base + archetype-specific extras)."""
    return list(_BASE_COMPONENT_PLAN) + list(_ARCHETYPE_EXTRA_COMPONENTS.get(template_id, []))


# ---------- public functions ----------


def sample_archetype(
    batch_config: Dict[str, Any],
    registries: RegistryBundle,
    rng: random.Random,
) -> str:
    """Sample a building_template_id per batch_config['archetype_distribution'] (T-17.2).

    If distribution missing or sums to 0 → uniform random over registry templates.
    """
    templates = _registry_records(registries, "building_template_registry")
    if not templates:
        raise ValueError("building_template_registry is empty")
    template_ids = [record["building_template_id"] for record in templates]
    distribution = batch_config.get("archetype_distribution") if batch_config else None
    if not distribution:
        return rng.choice(template_ids)
    weights = [float(distribution.get(tid, 0.0)) for tid in template_ids]
    return _weighted_choice(template_ids, weights, rng)


def build_building_context(
    template_id: str,
    building_index: int,
    registries: RegistryBundle,
    rng: random.Random,
) -> Tuple[BuildingContext, BuildingMetadata]:
    """Build (BuildingContext, BuildingMetadata) from a building_template_registry record.

    W0-008 (2026-05-21)：返回值由 BuildingContext 拆为 tuple；BuildingContext 持 spec 04 §4
    的 8 字段 contract（给 W2 消费），BuildingMetadata 持 generator 内部 3 字段
    （building_template_id / building_name / unit_count），不入 W2 contract.
    """
    templates_by_id = _registry_index(registries, "building_template_registry", "building_template_id")
    template = templates_by_id.get(template_id)
    if template is None:
        raise ValueError(f"Building template {template_id!r} not in registry")
    storey_lo, storey_hi = template["storey_count_range"]
    storey_count = rng.randint(int(storey_lo), int(storey_hi))
    age_years = round(rng.uniform(5.0, 60.0), 1)
    unit_count = max(2, storey_count * rng.randint(2, 8))
    suffix = _sanitize_id_component(template_id.replace("BT_", "").replace("_V1", ""))
    building_id = f"BLD-{suffix}-{building_index:04d}"
    building = BuildingContext(
        building_id=building_id,
        building_use=template["building_use"],
        structure_type=template["structure_type"],
        age_years=age_years,
        storey_count=storey_count,
        primary_materials=list(template.get("primary_materials") or []),
        configuration_tags=_archetype_configuration_tags(template_id),
        occupancy_state="occupied",
    )
    metadata = BuildingMetadata(
        building_template_id=template_id,
        building_name=f"Building {building_index:04d}",
        unit_count=unit_count,
    )
    return building, metadata


def _select_material_system(
    component_type: str,
    primary_materials: List[str],
    component_type_index: Dict[str, Dict[str, Any]],
    rng: random.Random,
) -> str:
    """Pick a material_system compatible with component_type, preferring primary_materials."""
    type_record = component_type_index.get(component_type)
    if type_record is None:
        # fallback: first primary material
        return primary_materials[0] if primary_materials else "reinforced_concrete"
    compatibility = list(type_record.get("material_compatibility") or [])
    if not compatibility:
        return primary_materials[0] if primary_materials else "reinforced_concrete"
    intersection = [m for m in primary_materials if m in compatibility]
    if intersection:
        return rng.choice(intersection)
    return rng.choice(compatibility)


def _sample_geometry_proxy(
    component_type: str,
    component_type_index: Dict[str, Dict[str, Any]],
    rng: random.Random,
) -> Dict[str, Any]:
    """Sample geometry_proxy dict per component_type_registry.geometry_proxy_ranges."""
    type_record = component_type_index.get(component_type) or {}
    ranges = type_record.get("geometry_proxy_ranges") or {}
    geometry: Dict[str, Any] = {}
    for field, bounds in ranges.items():
        if isinstance(bounds, list) and len(bounds) == 2:
            lo, hi = float(bounds[0]), float(bounds[1])
            value = rng.uniform(lo, hi)
            if field.endswith("_mm"):
                geometry[field] = round(value, 1)
            else:
                geometry[field] = round(value, 2)
        else:
            geometry[field] = bounds
    if "visible_area_m2" not in geometry:
        geometry["visible_area_m2"] = 10.0  # safe default per spec 04 §5
    return geometry


def build_components(
    building: BuildingContext,
    building_template_id: str,
    registries: RegistryBundle,
    rng: random.Random,
) -> List[ComponentNode]:
    """Build components for a building per archetype plan + component_type_registry (T-17.3).

    Each plan entry → 1 ComponentNode with:
    - component_id `^CMP-...`
    - material_system 兼容 component_type 且优先 primary_materials 子集
    - geometry_proxy 从 component_type_registry.geometry_proxy_ranges 抽样
    - location_id 引用即将建立的 LocationNode（同一 location_class 共享 1 个 LocationNode）

    `parent_component_id` 当前一律 None（T-17a 不建组件层级）；后续工单可补。

    W0-008 (2026-05-21)：`building_template_id` 由 caller 显式传入（从
    `BuildingInternalMetadata.building_template_id` 取），不再从 BuildingContext 读取
    （spec 04 §4 收紧 contract）.
    """
    plan = _archetype_component_plan(building_template_id)
    component_type_index = _registry_index(registries, "component_type_registry", "component_type")
    # W0-004 step 3+5 (2026-05-21)：material_system_registry.supports_rebar gate cover_depth_mm
    # 非 null 条件（RC 材质必非 null，非 RC 必 null）；range 取 component_type_registry.cover_depth_mm_range.
    material_index = _registry_index(registries, "material_system_registry", "material_system")
    components: List[ComponentNode] = []
    location_id_by_class: Dict[str, str] = {}
    for index, entry in enumerate(plan):
        ctype = entry["component_type"]
        location_class = entry["location_class"]
        if location_class not in location_id_by_class:
            location_suffix = _sanitize_id_component(location_class)
            location_id_by_class[location_class] = (
                f"LOC-{building.building_id.replace('BLD-', '')}-{location_suffix}"
            )
        location_id = location_id_by_class[location_class]
        material_system = _select_material_system(
            ctype, building.primary_materials, component_type_index, rng
        )
        geometry = _sample_geometry_proxy(ctype, component_type_index, rng)
        component_id = (
            f"CMP-{building.building_id.replace('BLD-', '')}-{_sanitize_id_component(ctype)}-{index:02d}"
        )
        # W0-004 step 3+5 (2026-05-21)：cover_depth_mm 派生（spec 04 §5 + spec 03 §4.1）.
        # 仅 material_system 支持 rebar 时（即 RC 材质：reinforced_concrete /
        # prestressed_concrete / precast_concrete）从 component_type_registry.cover_depth_mm_range
        # 抽样；其他材质（金属 / pipe / 木 / 复合）必 null.
        cover_depth_mm: Optional[float] = None
        material_record = material_index.get(material_system) or {}
        if material_record.get("supports_rebar"):
            ctype_record = component_type_index.get(ctype) or {}
            cover_range = ctype_record.get("cover_depth_mm_range")
            if cover_range:
                lo, hi = float(cover_range[0]), float(cover_range[1])
                cover_depth_mm = round(rng.uniform(lo, hi), 1)
        components.append(
            ComponentNode(
                component_id=component_id,
                component_type=ctype,
                parent_component_id=None,
                material_system=material_system,
                structural_role=entry["structural_role"],
                location_id=location_id,
                geometry_proxy=geometry,
                cover_depth_mm=cover_depth_mm,
                access_class="fully_accessible",
            )
        )
    return components


def build_locations(
    components: List[ComponentNode],
    registries: RegistryBundle,
    rng: random.Random,
    plan: Optional[List[Dict[str, str]]] = None,
) -> List[LocationNode]:
    """Build LocationNodes for unique location_ids referenced by components (T-17.3).

    `plan` (optional) carries per-(location_class) exposure_zone / storey_band hints from the
    archetype plan; if absent, falls back to location_class_registry defaults.
    """
    location_class_index = _registry_index(registries, "location_class_registry", "location_class")
    plan_by_loc_class: Dict[str, Dict[str, str]] = {}
    if plan:
        for entry in plan:
            plan_by_loc_class.setdefault(entry["location_class"], entry)
    seen_ids: set = set()
    locations: List[LocationNode] = []
    for component in components:
        if component.location_id in seen_ids:
            continue
        seen_ids.add(component.location_id)
        # find corresponding location_class via plan order; fallback: scan plan entries
        location_class = _location_class_from_id(component.location_id)
        plan_entry = plan_by_loc_class.get(location_class)
        class_record = location_class_index.get(location_class) or {}
        if plan_entry:
            exposure_zone = plan_entry.get("exposure_zone") or _default_exposure(class_record, rng)
            storey_band = plan_entry.get("storey_band") or "mid_zone"
        else:
            exposure_zone = _default_exposure(class_record, rng)
            storey_band = "mid_zone"
        spatial_tags = list(class_record.get("spatial_tags") or [])
        locations.append(
            LocationNode(
                location_id=component.location_id,
                location_class=location_class,
                exposure_zone=exposure_zone,
                storey_band=storey_band,
                spatial_tags=spatial_tags,
            )
        )
    return locations


def _default_exposure(class_record: Dict[str, Any], rng: random.Random) -> str:
    options = class_record.get("exposure_options") or []
    if not options:
        return "interior_dry"
    canonical_map = {
        "outdoor": "exterior_weather",
        "exposed": "exterior_weather",
        "weather_facing": "exterior_weather",
        "rain_bearing": "exterior_weather",
        "internal": "interior_dry",
        "protected": "interior_dry",
        "humid": "interior_wet",
        "confined": "interior_wet",
        "semi_exposed": "exterior_weather",
        "sheltered": "interior_dry",
    }
    chosen = rng.choice(options)
    return canonical_map.get(chosen, "interior_dry")


def _location_class_from_id(location_id: str) -> str:
    """Recover location_class hint from sanitized location_id suffix.

    location_id format: `LOC-<building-suffix>-<class-suffix>`. We split on "-" and rebuild
    class suffix back to underscore form. This is brittle but acceptable for T-17a since plan
    is the source of truth.
    """
    parts = location_id.split("-")
    if len(parts) < 3:
        return "common_part"
    # everything past the building suffix; building suffix may itself contain dashes,
    # so we use a heuristic: the last contiguous all-letter segments are the class.
    candidate_segments: List[str] = []
    for segment in reversed(parts):
        if segment.isalpha():
            candidate_segments.append(segment.lower())
        else:
            if candidate_segments:
                break
    if not candidate_segments:
        return "common_part"
    candidate_segments.reverse()
    return "_".join(candidate_segments)


# ---------- T-17b: per-fragment state generators ----------


def _select_fragment_templates(
    building: BuildingContext,
    building_template_id: str,
    registries: RegistryBundle,
    *,
    world_id: str,
    target_count: int = 4,
    available_component_types: Optional[set] = None,
    ensure_component_type_coverage: bool = False,
) -> List[Dict[str, Any]]:
    """Pick `target_count` fragment templates compatible with this building.

    Strategy：先取 fragment_template_registry 中 building_template_id 匹配的模板；
    若不足 target_count，从 registry 其余模板中按 component_type 是否兼容 archetype 抽补。

    W0-008 (2026-05-21)：`building_template_id` 由 caller 显式传入（从
    `BuildingInternalMetadata.building_template_id` 取），不再从 BuildingContext 读取.

    🔴🔴 1a-ii 稳定化（波次二 #22，2026-08-05）：**两处 `rng.shuffle` 改成「按稳定键排序
    后取前 k」**，`rng` 形参一并删除 —— 本函数对主 rng 的消费**归零**。

    病：`rng.shuffle(整表)` ⇒ 表长一变，排列整体重来 ⇒ **选中的是另一批模板** ⇒
    片段身份全变。实测该表结构放大了这个病：15 张片段模板只覆盖 6 个
    `building_template_id`，而楼型注册表有 15 个 ⇒ **9/15 楼型 `primary` 为空、
    走下面 `:not primary` 的全表回退**（seed401 池 50 栋里 34 栋 ＝ 68% 属这 9 个楼型），
    于是它们 shuffle 的是**整张表**，加一张模板就 12→16 全排列重掷。

    改法（三线定稿的候选甲）：`sorted(..., key=stable_sort_key(域串, world_id, 模板 id))`。
    追加一张模板 ＝ 在这个序里插一个位置，**既有模板的相对序不变**；
    ⚠️ 但**不是「插入无影响」**：候选池 n→n+1 而取 k 不变，新模板的键排进前 k 时
    仍会挤掉一个既有的，概率 ＝ k/(n+1)（全表回退那 9 个楼型：k=4、n=15 ⇒ 25%，
    对比现状整表重排 ≈100%）。**别把它宣称成「加模板＝纯追加」。**

    ⚠️ 另一条须记：ctcov 的追加集 `covered = {t["component_type"] for t in chosen}`
    依赖 `chosen`，故本改动也会改 ctcov 的追加集。那是预期的（换池），不是不变量。
    """
    all_templates = _registry_records(registries, "fragment_template_registry")
    primary = [t for t in all_templates if t.get("building_template_id") == building_template_id]
    if not primary:
        primary = list(all_templates)

    def _template_key(template: Dict[str, Any]) -> bytes:
        return rng_domains.stable_sort_key(
            rng_domains.FRAGMENT_TEMPLATE_SELECT,
            world_id,
            str(template.get("fragment_template_id") or ""),
        )

    chosen: List[Dict[str, Any]] = []
    pool = sorted(primary, key=_template_key)
    for template in pool:
        chosen.append(template)
        if len(chosen) >= target_count:
            break
    # 不足时从 archetype-agnostic 池补。
    # EXP-012 前置修（补抽错绑现存病，UBW 模板已暴露）：补抽只收"楼内存在该
    # component_type"的模板——否则 _pick_component_for_fragment 回退任选组件，
    # 机制/条件相容性错绑（C005/C006 闪红）。available_component_types 未传时
    # 维持旧行为（兼容单测直调）。
    if len(chosen) < target_count:
        remaining = [t for t in all_templates if t not in chosen]
        if available_component_types is not None:
            remaining = [
                t for t in remaining
                if t.get("component_type") in available_component_types
            ]
        remaining = sorted(remaining, key=_template_key)
        for template in remaining:
            chosen.append(template)
            if len(chosen) >= target_count:
                break

    # 🔴 构件类完整性（2026-07-29，DEBT「验收③ 队列 1′」；**缺省关，开关不动 rng**）
    #
    # 病：片段是**模板驱动**的（每栋固定取 `target_count=4` 个模板），而
    # `_pick_component_for_fragment` 每个模板只挑**一个**组件。于是一栋楼里
    # 某个构件类可能一个片段都没有 —— 实测池内 `343 组件 / 200 片段`，
    # **172 个组件（50.1%）零片段**，121 个 (楼, 构件类) 格零片段。
    #
    # 后果：义务按片段求值，没有该类片段 ⇒ 针对该类的卡产不出作用域内义务 ⇒
    # 阅卷记「漏」。但那是**世界没把题出出来**，不是系统没答。自然实验：
    # 同一 (规范项, 构件类) 在有该类片段的楼上覆盖率 **99.5%**、没有的楼上 **0.0%**。
    #
    # ⚠️ 判据是「**楼内已存在的构件类**至少产一个片段」这条**组件层完整性规则**，
    #    **不是**「按漏掉的规范项补片段」——后者就是照误差清单造题。
    #    所以这里只看 `available_component_types`（世界自己有什么），
    #    **不读任何法规卡、不读真值**。
    #
    # ⚠️ 缺省 False：开着会追加模板 ⇒ 消耗 rng ⇒ 整个世界的随机流改变。
    #    开它必须配新池名，**不得原地改同一 seed 的语义**。
    #    注册表只有 12 个模板覆盖 8 种构件类，而 `component_type_registry` 有 19 种；
    #    `balcony_slab` / `parapet_wall` / `signboard` **无模板**，本开关对它们无能为力
    #    （须新写模板，属内容工作，另行处置）。
    #
    # 🔴🔴 追加**必须用独立子 rng**，绝不能碰主 `rng`（2026-07-29 实测栽过一次）。
    #    首版直接 `rng.randrange(...)` ⇒ 主 rng 状态被推进 ⇒ 而
    #    `_pick_component_for_fragment` 是在**主循环里**才取 rng ⇒
    #    **连原有那几个模板都绑到了不同的组件上**。实测批 H：
    #    **19/30 栋的原有片段整批消失**，于是「开 vs 关」不是单变量对照，
    #    而是「换了随机流、顺便类覆盖更好的另一个世界」——因果宣称不成立。
    #    改用子 rng 后，主 rng 状态不变 ⇒ 原有片段逐个保留，新增的纯属追加。
    if ensure_component_type_coverage and available_component_types:
        covered = {t.get("component_type") for t in chosen}
        for ctype in sorted(available_component_types - covered):
            candidates = [t for t in all_templates if t.get("component_type") == ctype]
            if candidates:
                sub_rng = random.Random(f"ctcov|{building_template_id}|{ctype}")
                chosen.append(candidates[sub_rng.randrange(len(candidates))])
    return chosen


def _pick_component_for_fragment(
    template: Dict[str, Any],
    components: List[ComponentNode],
    rng: random.Random,
) -> Optional[ComponentNode]:
    """Find a component matching template.component_type; fallback: any component."""
    target_type = template.get("component_type")
    candidates = [c for c in components if c.component_type == target_type]
    if not candidates:
        candidates = list(components)
    if not candidates:
        return None
    return rng.choice(candidates)


def _location_for_component(
    component: ComponentNode,
    locations: List[LocationNode],
) -> Optional[LocationNode]:
    for loc in locations:
        if loc.location_id == component.location_id:
            return loc
    return None


def generate_fragment(
    component: ComponentNode,
    template: Dict[str, Any],
    fragment_index: int,
    rng: random.Random,
) -> FragmentContext:
    """Build FragmentContext referencing an existing component (spec 04 §7 9 字段 reference-based contract).

    W0-005 (2026-05-21)：generator pipeline 内部全切到 spec 04 §7 FragmentContext 9 字段
    reference-based contract——物理上下文（material_system / structural_role / cover_depth_mm /
    geometry / exposure_zone / has_rebar 等）由消费方按 spec 06 §0.1 reference 反查路径，
    通过 `fragment.component_id → ComponentNode` / `fragment.location_id → LocationNode` 反查；
    不在 FragmentContext 自身扩 denormalized 物理 cache（删除 FragmentRuntimeState 中间层）.
    """
    area_lo, area_hi = template.get("area_range") or [1.0, 50.0]
    area = round(rng.uniform(float(area_lo), float(area_hi)), 2)
    length_range = template.get("length_range")
    fragment_length_m: Optional[float] = (
        round(rng.uniform(float(length_range[0]), float(length_range[1])), 2)
        if length_range
        else None
    )
    fragment_suffix = _sanitize_id_component(component.component_id.replace("CMP-", ""))
    fragment_id = f"FRG-{fragment_suffix}-{fragment_index:02d}"
    return FragmentContext(
        fragment_id=fragment_id,
        fragment_template_id=template["fragment_template_id"],
        component_id=component.component_id,
        location_id=component.location_id,
        fragment_role="inspection_target",
        fragment_area_m2=area,
        fragment_length_m=fragment_length_m,
        in_scope=True,
        exclusion_reason=None,
    )


def generate_driver(
    fragment: FragmentContext,
    building: BuildingContext,
    rng: random.Random,
    template: Optional[Dict[str, Any]] = None,
) -> DriverState:
    """Build DriverState — index values sampled in [0, 1] with archetype skew (spec 04 §9).

    T-17b stage：simple uniform sampling per index field. T-18 公式重写工单会用 spec 公式
    替换为 archetype + age 派生公式。

    DEBT-049 Phase3 U5 §2.1 S2.5 防死档（`template` 可选，缺省=旧行为、非 drainage 域字节不变）：
    drainage 域 fragment 的 alteration_propensity 采样上界由 `_DRAINAGE_DRIVER_ALTERATION_HI` 上调，
    使 misconnection（→§2.1 P1 smoke_test）注入率非零。**只改采样上界（`hi`）、不增删 rng 抽取次数**
    → 非 drainage fragment 逐字节不变、drainage fragment 的其后抽取（fire/repair）RNG 序列亦不移位，
    仅 alteration 值变（且该值在 drainage fragment 上仅喂 misconnection 公式，见常量处 isolation 论证）。
    """
    age_factor = min(1.0, building.age_years / 60.0)  # older → higher deterioration drivers

    def _bounded(lo: float, hi: float) -> float:
        return round(rng.uniform(lo, hi), 3)

    # drainage 域判别（specialized_domains 或 allowed_mechanisms 命中 drainage）。
    _is_drainage = bool(template) and (
        "drainage" in (template.get("specialized_domains") or [])
        or "drainage_fault" in (template.get("allowed_mechanisms") or [])
    )
    _alteration_hi = (
        _DRAINAGE_DRIVER_ALTERATION_HI if _is_drainage else (0.4 + 0.3 * age_factor)
    )

    driver_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    return DriverState(
        # W0-004 (2026-05-21)：spec 04 §9 DriverState 13 字段对齐——age_years 不在 driver
        # （从 BuildingContext 反查），drainage_fault_propensity 走单一字段。
        driver_id=f"DRV-{driver_suffix}",
        fragment_id=fragment.fragment_id,
        service_load_ratio=_bounded(0.3, 0.95),
        restraint_level=_bounded(0.2, 0.9),
        moisture_ingress_index=_bounded(0.0, 0.6 + 0.3 * age_factor),
        chloride_exposure_index=_bounded(0.0, 0.5 + 0.4 * age_factor),
        carbonation_index=_bounded(0.0, 0.3 + 0.5 * age_factor),
        workmanship_deficit_index=_bounded(0.0, 0.4),
        maintenance_deficit_index=_bounded(0.0, 0.3 + 0.5 * age_factor),
        drainage_fault_propensity=_bounded(0.0, 0.5),
        alteration_propensity=_bounded(0.0, _alteration_hi),  # DEBT-049 §2.1 S2.5 防死档
        fire_safety_deficit_index=_bounded(0.0, 0.3 + 0.4 * age_factor),
        repair_quality_index=_bounded(0.4, 0.95),
    )


# ---------- mechanism family → condition class ----------
# DEBT-030 D1 (2026-05-13): legacy inline mapping `_MECHANISM_FAMILY_TO_CONDITION` 已抽出到
# `_lookup_primary_condition_class_from_mechanism_family` (registry-driven, 见 §registry-driven
# lookup helpers). mechanism_library_registry.output_condition_classes 取第一条作 default.


def generate_mechanism(
    fragment: FragmentContext,
    template: Dict[str, Any],
    driver: DriverState,
    rng: random.Random,
    age_years: float,
) -> MechanismState:
    """spec 06 §3.1: 从 driver 派生 crack/spall/detachment score 选 active mechanism.

    severity_index = max(active_scores)；mechanism_family 选 max score 对应；
    若 max < 0.35 则视为不活跃（spec §3.2 reject 规则），但仍登记主导 family。
    非结构域 mechanism（drainage_fault / ubw_signal / fire_safety_deficiency / assessment_origin）
    保留 placeholder logic（T-18c/d/e/g 工单 cover）。

    W0-004 (2026-05-21)：age_years 改从参数传入（BuildingContext.age_years），不从 driver 读。
    """
    allowed = list(template.get("allowed_mechanisms") or ["structural_crack"])
    age = _age_norm(age_years)

    # 计算 spec §3.1 三个 score
    crack_score = _compute_crack_score(driver)
    spall_score = _compute_spall_score(driver, age)
    detachment_score = _compute_detachment_score(driver)

    # 候选 score map（仅含 template 允许的 mechanism family）
    candidate_scores: Dict[str, float] = {}
    if "structural_crack" in allowed:
        candidate_scores["structural_crack"] = crack_score
    if "corrosion_spall" in allowed:
        candidate_scores["corrosion_spall"] = spall_score
    if "moisture_detachment" in allowed:
        candidate_scores["moisture_detachment"] = detachment_score
    # 非结构域 mechanism：placeholder（后续 T-18c/d/e/g cover）
    for family in allowed:
        if family not in candidate_scores:
            candidate_scores[family] = round(0.3 + 0.6 * rng.random(), 3)

    # 选 max score 的 mechanism family
    primary_family = max(candidate_scores, key=lambda k: candidate_scores[k])
    activation_score = round(candidate_scores[primary_family], 3)
    severity_index = max(candidate_scores.values())

    activations = [
        MechanismActivation(
            mechanism_id=f"MCH-{primary_family}-{fragment.fragment_id}",
            mechanism_family=primary_family,
            activation_score=activation_score,
            derived_from_driver_ids=[driver.driver_id],
        )
    ]
    mechanism_state_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    crack_kind = (
        "load_induced"
        if primary_family == "structural_crack" and driver.service_load_ratio >= driver.restraint_level + 0.15
        else "restraint" if primary_family == "structural_crack"
        else "none"
    )
    return MechanismState(
        mechanism_state_id=f"MST-{mechanism_state_suffix}",
        fragment_id=fragment.fragment_id,
        mechanism_family=primary_family,
        active=activation_score >= 0.35,  # spec §3.2 activation threshold
        severity_index=severity_index,
        cause_tags=[],  # validator fills from family
        primary_mechanism_id=activations[0].mechanism_id,
        activated_mechanisms=activations,
        crack_mechanism_kind=crack_kind,
        corrosion_active=primary_family == "corrosion_spall",
        delamination_active=primary_family == "moisture_detachment",
        drainage_fault_kind="active_blockage" if primary_family == "drainage_fault" else "none",
        ubw_signal_kind="alteration_present" if primary_family == "ubw_signal" else "none",
        fire_safety_deficiency_kind=(
            "component_deficiency" if primary_family == "fire_safety_deficiency" else "none"
        ),
        assessment_origin_kind="origin_present" if primary_family == "assessment_origin" else "none",
        verification_origin_kind="none",
    )


# spec 草案·DEBT-049 建模轮第一波 §1（2026-07-08 v2，codex 一审修正并入）：
# 机制阶段闸常数——锚定 generator_defect 严重度公式 [0,1] 取值域（勿与
# activation_score 活跃线混同）。engineering_estimate_DEBT049_20260708，低置信；
# 发射率验收带（锈蚀早期态 [10%,40%] / 位移态 [8%,30%]）由健康门实测，漂出即调。
_METAL_CORROSION_C_ACT = 0.35       # 锈蚀活跃线（corrosion_severity）
_METAL_CORROSION_D_SPALL = 0.50     # 剥落未成线（delamination_severity 上限；0.30→0.40→0.50 两轮标定：离线高估约2.6倍(固定保护层/楼龄所致)，seed218 实测合格分母 8.0% 仍带外，0.50 外推预期约 20%）
_DEFORMATION_LOAD_GATE = 0.85       # 超载线（service_load_ratio 实采上限 0.95）
_DEFORMATION_RESTRAINT_GATE = 0.80  # 高约束线（restraint_level）
_DEFORMATION_SEVERITY_GATE = 0.60   # 伴随严重度线（severity_index）
# DEBT-049 A1/A2 副缺陷类发射常数（engineering_estimate_DEBT049_20260708，低置信；
# 发射率由健康门实测，漂出即调）。A1 露筋闸=剥落露筋长度阈；A2 蜂窝/分离低率概率。
_REBAR_EXPOSED_SEVERITY_GATE = 0.50  # 露筋严重度线（严重剥落暴露主筋，DC_SPALL_REBAR上）
_HONEYCOMBING_RATE = 0.10          # 混凝土蜂窝/空洞发射率（施工缺陷，结构裂缝链上）
_ABNORMAL_SEPARATION_RATE = 0.15   # 毗邻分离发射率（限位移态语境，稀有）


def _defect_class_compatible_components(
    condition_class: str, registries: Optional[RegistryBundle]
) -> Optional[set]:
    """缺陷目录 compatible_components 反查（C006 单一权威，阶段闸组件闸用）。"""
    if registries is None:
        return None
    for registry in registries.registries:
        if registry.registry_id != "defect_condition_taxonomy_registry":
            continue
        for rec in registry.records:
            if rec.get("condition_class") == condition_class:
                comps = rec.get("compatible_components")
                return set(comps) if comps else None
    return None


def _all_taxonomy_condition_classes(registries: Optional[RegistryBundle]) -> set:
    """缺陷分类注册表全集（spec 草案·DEBT-049 第三波 件A：闭世界总声明的类宇宙）。"""
    if registries is None:
        return set()
    for registry in registries.registries:
        if registry.registry_id == "defect_condition_taxonomy_registry":
            return {
                str(r.get("condition_class"))
                for r in registry.records
                if r.get("condition_class")
            }
    return set()


def _fragment_reachable_condition_classes(
    allowed_mechanisms: List[str],
    component_type: str,
    registries: Optional[RegistryBundle],
) -> set:
    """per-fragment 可达缺陷类集（spec 草案·第一波 §2）。

    = 模板 allowed_mechanisms 各机制的发射分支可达输出类 ∩ 组件相容类（C006 目录）。
    发射分支可达 = 产出集第 1 条（主类）+ 阶段闸类（DC_METAL_CORROSION /
    DC_DEFORMATION_DISPLACEMENT，其所属机制在 allowed 集内时）。
    """
    if registries is None:
        return set()
    mech_by_family: Dict[str, Dict[str, Any]] = {}
    for registry in registries.registries:
        if registry.registry_id == "mechanism_library_registry":
            for rec in registry.records:
                fam = rec.get("mechanism_family")
                if fam:
                    mech_by_family[str(fam)] = rec
    reachable: set = set()
    for fam in allowed_mechanisms or []:
        rec = mech_by_family.get(str(fam))
        if not rec:
            continue
        outs = rec.get("output_condition_classes") or []
        if outs:
            reachable.add(str(outs[0]))  # 主类恒可达
        if fam == "corrosion_spall":
            reachable.add("DC_METAL_CORROSION")
        if fam == "structural_crack":
            reachable.add("DC_DEFORMATION_DISPLACEMENT")
    # 组件相容过滤（目录单一权威）
    out: set = set()
    for cls in reachable:
        compat = _defect_class_compatible_components(cls, registries)
        if compat is None or component_type in compat:
            out.add(cls)
    return out


def generate_condition(
    fragment: FragmentContext,
    component: ComponentNode,
    mechanism: MechanismState,
    driver: DriverState,
    rng: random.Random,
    age_years: float,
    registries: Optional[RegistryBundle] = None,
) -> ConditionState:
    """spec 06 §4 corrosion_spall mechanism 用 spec 公式派生 severity / extent；
    其它 mechanism family 用 mechanism.severity_index 简化派生。

    DEBT-030 D1 (2026-05-13): condition_class 通过 mechanism_library_registry 反查
    (`_lookup_primary_condition_class_from_mechanism_family`); registries 缺省时退到
    worker globals (`_WORKER_REGISTRIES`); 仍缺时返回 fallback DC_CRACK.

    W0-005 (2026-05-21)：spec 06 §0.1 reference 反查——`cover_depth_mm`/`material_system` 走
    `component`（spec 04 §5 ComponentNode），`fragment_length_m`/`fragment_area_m2` 走
    `fragment`（spec 04 §7 FragmentContext）.
    """
    effective_registries = registries if registries is not None else _WORKER_REGISTRIES
    if effective_registries is not None:
        condition_class = _lookup_primary_condition_class_from_mechanism_family(
            mechanism.mechanism_family, effective_registries
        )
    else:
        condition_class = "DC_CRACK"

    fragment_length_m = fragment.fragment_length_m or 0.0
    fragment_area_m2 = fragment.fragment_area_m2

    # corrosion_spall 路径用 spec §4 公式
    if mechanism.mechanism_family == "corrosion_spall":
        corrosion_severity = _compute_corrosion_severity(driver, component.cover_depth_mm, age_years)
        delamination_severity = _compute_delamination_severity(corrosion_severity, driver)
        cover_loss_mm = _compute_cover_loss_depth_mm(delamination_severity, component.cover_depth_mm)
        spall_area = _compute_spall_patch_area_m2(
            delamination_severity, driver.moisture_ingress_index, fragment_area_m2
        )
        rebar_length = _compute_rebar_exposed_length_m(
            cover_loss_mm, component.cover_depth_mm, spall_area, fragment_length_m
        )
        severity_index = corrosion_severity
        extent_area: Optional[float] = round(spall_area, 4)
        extent_length: Optional[float] = round(rebar_length, 4) if rebar_length > 0 else None
        depth_mm: Optional[float] = round(cover_loss_mm, 2) if cover_loss_mm is not None else None
        # 阶段闸①（spec 草案·第一波 §1.1）：锈蚀活跃而剥落未成 → 早期态
        # DC_METAL_CORROSION；组件闸走缺陷目录 compatible_components（C006 权威）。
        if (
            corrosion_severity >= _METAL_CORROSION_C_ACT
            and delamination_severity < _METAL_CORROSION_D_SPALL
        ):
            _compat = _defect_class_compatible_components(
                "DC_METAL_CORROSION", effective_registries
            )
            if _compat is not None and component.component_type in _compat:
                condition_class = "DC_METAL_CORROSION"
    else:
        # 其它 mechanism family 保留 mechanism.severity_index 派生（T-18c-g 工单替换）
        severity_index = mechanism.severity_index
        extent_area = round(fragment_area_m2 * rng.uniform(0.05, 0.5), 2) if mechanism.active else None
        extent_length = None
        depth_mm = None
        # 阶段闸②（spec 草案·第一波 §1.2）：荷载/约束裂缝链的位移态——超载或
        # 高约束+高严重度 → DC_DEFORMATION_DISPLACEMENT；组件闸同①。
        if mechanism.mechanism_family == "structural_crack":
            _load = float(getattr(driver, "service_load_ratio", 0.0) or 0.0)
            _restraint = float(getattr(driver, "restraint_level", 0.0) or 0.0)
            if _load >= _DEFORMATION_LOAD_GATE or (
                _restraint >= _DEFORMATION_RESTRAINT_GATE
                and severity_index >= _DEFORMATION_SEVERITY_GATE
            ):
                _compat = _defect_class_compatible_components(
                    "DC_DEFORMATION_DISPLACEMENT", effective_registries
                )
                if _compat is not None and component.component_type in _compat:
                    condition_class = "DC_DEFORMATION_DISPLACEMENT"

    if severity_index < 0.33:
        band = "minor"
    elif severity_index < 0.66:
        band = "moderate"
    else:
        band = "severe"

    # DEBT-049 A1/A2 副缺陷类发射（正例；全集负例另由检索侧派生管缺席态）。
    # 组件闸走缺陷目录 compatible_components（C006 权威，勿硬编码集合）。
    _secondary: List[str] = []

    def _emit_secondary(dc: str) -> None:
        _compat = _defect_class_compatible_components(dc, effective_registries)
        if _compat is not None and component.component_type in _compat and dc != condition_class:
            _secondary.append(dc)

    # A1：剥落暴露主筋——严重剥落（severity 高）暴露主筋，DC_REBAR_EXPOSED 与
    # DC_SPALL_REBAR 强相关分槽（rebar_length 公式此池恒 0，改严重度闸；物理：严重
    # 混凝土剥落暴露钢筋，CoP §3.4.2(A)(c)(iv)→(vi) 因果）。
    if (condition_class == "DC_SPALL_REBAR"
            and severity_index >= _REBAR_EXPOSED_SEVERITY_GATE):
        _emit_secondary("DC_REBAR_EXPOSED")
    # A2：混凝土施工期蜂窝/空洞——低率概率发射（施工缺陷、年龄无关）于结构混凝土。
    if (mechanism.mechanism_family == "structural_crack"
            and rng.random() < _HONEYCOMBING_RATE):
        _emit_secondary("DC_HONEYCOMBING_VOID")
    # A2：毗邻楼宇间不正常分离——限高约束/位移语境的稀有发射（勿泛化）。
    if (condition_class == "DC_DEFORMATION_DISPLACEMENT"
            and rng.random() < _ABNORMAL_SEPARATION_RATE):
        _emit_secondary("DC_ABNORMAL_SEPARATION")

    cond_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    return ConditionState(
        condition_id=f"CND-{cond_suffix}",
        fragment_id=fragment.fragment_id,
        mechanism_state_id=mechanism.mechanism_state_id,
        condition_class=condition_class,
        severity_band=band,
        severity_index=severity_index,
        extent_area_m2=extent_area if extent_area and extent_area > 0 else None,
        extent_length_m=extent_length,
        depth_mm=depth_mm,
        count=None,
        uncertainty_flag=mechanism.severity_index < 0.2,
        defect_condition_ids=[condition_class] + _secondary,
        condition_classes=[condition_class] + _secondary,
    )


def generate_drainage_state(
    fragment: FragmentContext,
    mechanism: MechanismState,
    component: ComponentNode,
    driver: DriverState,
    rng: random.Random,
    age_years: float,
) -> Optional[DrainageState]:
    """spec 06 §5: drainage 域 4 个 index 公式派生。

    仅 mechanism is drainage_fault 时生成。
    W0-004: age_years 来自 BuildingContext（spec 04 §4），不从 driver 读。
    """
    if mechanism.mechanism_family != "drainage_fault":
        return None
    drainage_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))

    blockage = round(_compute_drainage_blockage_index(driver, age_years), 3)
    leakage = round(_compute_drainage_leakage_index(driver, age_years), 3)
    misconnection = _compute_drainage_misconnection_present(driver)
    public_health = round(
        _compute_drainage_public_health_risk_index(blockage, leakage, misconnection), 3
    )

    segment_type = "soil_pipe" if "stack" in component.component_type else "branch_connection"
    drainage_id = f"DRN-{drainage_suffix}"
    return DrainageState(
        drainage_id=drainage_id,
        component_id=component.component_id,
        segment_type=segment_type,
        connection_state="misconnected" if misconnection else "correct",
        blockage_index=blockage,
        leakage_index=leakage,
        misconnection_present=misconnection,
        public_health_risk_index=public_health,
        # DEBT-049 Phase3 U5 §2.1a：地上/地下确定性散列派生（总函数，不消费 RNG，不读 segment_type）
        is_underground=_drainage_is_underground(drainage_id),
    )


def generate_ubw_state(
    fragment: FragmentContext,
    mechanism: MechanismState,
    component: ComponentNode,
    location: Optional[LocationNode],
    driver: DriverState,
    rng: random.Random,
) -> Optional[UBWState]:
    """spec 06 §6: UBW 域 3 个 index 公式派生.

    仅 mechanism is ubw_signal 时生成。
    """
    if mechanism.mechanism_family != "ubw_signal":
        return None
    ubw_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    alteration_options = [
        "canopy", "enclosure", "subdivision", "rooftop_structure", "external_signboard",
    ]
    alteration_type = rng.choice(alteration_options)
    auth_status = rng.choices(
        ["authorized_like", "unauthorized_like", "unknown_authorization"],
        weights=[0.2, 0.6, 0.2],
    )[0]

    alteration_score = _compute_ubw_alteration_score(driver)
    subdivided_sign = _compute_ubw_subdivided_unit_sign_present(
        location, alteration_type, alteration_score,
    )
    structural_impact = round(_compute_ubw_structural_impact_index(alteration_score, component), 3)

    return UBWState(
        ubw_id=f"UBW-{ubw_suffix}",
        component_id=component.component_id,
        alteration_type=alteration_type,
        authorization_status_proxy=auth_status,
        present=True,
        subdivided_unit_sign_present=subdivided_sign,
        structural_impact_index=structural_impact,
    )


def generate_fire_safety_state(
    fragment: FragmentContext,
    mechanism: MechanismState,
    component: ComponentNode,
    driver: DriverState,
    rng: random.Random,
    registries: Optional[RegistryBundle] = None,
) -> Optional[FireSafetyState]:
    """spec 06 §7: fire-safety 域 3 个 index 公式派生.

    DEBT-049 B2（codex CoP 裁定 2026-07-08，§3.5.1 检验范围含所有消防安全设施）：
    生成门槛从"机制==fire_safety_deficiency"改为"**组件是消防构件**"——消防门等消防
    构件的消防状态在检验时恒可评估（deficiency 布尔 true/false 由 driver 分数派生，
    机制无关），not_applicable 只应给非消防适用域。此修同时解决欠生成（多数 fire_door
    此前无消防态）+挂错组件（fire_safety_deficiency 机制落到非消防组件上生成假消防态）。

    DEBT-030 D1 (2026-05-13): fire_component_class 走 `component_type_registry.component_class`
    registry lookup (`_lookup_fire_component_class_from_component_type`);
    registries 缺省时退到 worker globals (`_WORKER_REGISTRIES`); 仍缺时返回
    fallback "unknown_fire_component".
    """
    fss_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    effective_registries = registries if registries is not None else _WORKER_REGISTRIES
    if effective_registries is not None:
        fire_component_class = _lookup_fire_component_class_from_component_type(
            component.component_type, effective_registries
        )
    else:
        fire_component_class = "unknown_fire_component"
    # DEBT-049 B2：非消防构件不生成消防态（消防适用域=消防构件）。
    if fire_component_class == "unknown_fire_component":
        return None

    deficiency_score = _compute_fire_deficiency_score(driver)
    deficiency_present = _is_fire_deficiency_present(deficiency_score)
    severity_index = round(
        _compute_fire_severity_index(deficiency_score, fire_component_class), 3
    )

    deficiency_class = (
        rng.choice(["missing", "damaged", "obstructed", "non_functional"])
        if deficiency_present else "not_applicable"
    )
    record_status = rng.choices(
        ["physical_only", "upgrade_record_outstanding", "unknown_record_status"],
        weights=[0.6, 0.3, 0.1],
    )[0]

    return FireSafetyState(
        fire_state_id=f"FSS-{fss_suffix}",
        component_id=component.component_id,
        fire_component_class=fire_component_class,
        deficiency_class=deficiency_class,
        deficiency_present=deficiency_present,
        severity_index=severity_index,
        record_status_proxy=record_status,
    )


def generate_repair_assessment_state(
    fragment: FragmentContext,
    condition: ConditionState,
    driver: DriverState,
    rng: random.Random,
) -> RepairAssessmentState:
    """Build RepairAssessmentState — Step 1 **bootstrap only**（占位）.

    W1-002 双轨消除：本函数仅给 RAS 提供初始占位值（fragment_id 关联 / repair_quality_index /
    residual_risk_index 由本函数算定）；4 个 bool 字段 (repair_required / verification_failed /
    maintenance_required / safe_until_next_cycle) 在 Step 9 ``populate_derived_flags`` 内**统一由
    spec 06 §11 derived flag 公式回写为最终权威**（spec 03 §3 段间依赖图 line 87 + spec 08 §2
    派生顺序）；本处 bool 初值仅在 derived flag 未触发回写前（fragment loop 中间态）短暂存在.
    """
    repair_required = condition.severity_index >= 0.4
    maintenance_required = 0.2 <= condition.severity_index < 0.5
    verification_failed = condition.severity_index >= 0.7 and rng.random() < 0.3
    safe_until_next_cycle = condition.severity_index < 0.5 if condition.severity_index else True
    repair_quality = driver.repair_quality_index if repair_required else None
    residual_risk = round(condition.severity_index * 0.6, 3) if condition.severity_index else None
    ras_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
    return RepairAssessmentState(
        repair_assessment_id=f"RAS-{ras_suffix}",
        fragment_id=fragment.fragment_id,
        repair_quality_index=repair_quality,
        repair_required=repair_required,
        maintenance_required=maintenance_required,
        verification_failed=verification_failed,
        safe_until_next_cycle=safe_until_next_cycle,
        residual_risk_index=residual_risk,
    )


def generate_coverage_relations(
    building: BuildingContext,
    components: List[ComponentNode],
    fragments: List[FragmentContext],
    components_by_id: Dict[str, ComponentNode],
    registries: RegistryBundle,
    *,
    world_id: str,
) -> List[CoverageRelation]:
    """Build CoverageRelation per fragment based on coverage_relation_registry (spec 04 §3 / §8).

    Picks 1 coverage_relation_type per fragment whose target `component.component_type` matches
    the relation's `target_component_types`. Fallback to CR_IN_SCOPE for non-matching cases.

    W0-005 (2026-05-21)：`component_type` 走 `components_by_id[fragment.component_id]`
    （spec 06 §0.1 reference 反查 + spec 04 §5 ComponentNode），不读 FragmentRuntimeState 自身 cache.

    🔴 1a-i（波次二 #22，2026-08-05）：本阶段**不再收主 rng**，改按
    `(域串, world_id, fragment_id)` 逐片段派生子流。删形参而非留着不用——
    「不消费主 rng」由此成为结构上不可能违反的事实，强于任何运行时断言。
    """
    cr_records = _registry_records(registries, "coverage_relation_registry")
    relations: List[CoverageRelation] = []
    for fragment_index, fragment in enumerate(fragments):
        # 键只吃「这次抽的是什么」——不吃批规模、不吃 fragment_index（那正是要治的病）。
        rng = rng_domains.sub_rng(
            rng_domains.COVERAGE_RELATIONS, world_id, fragment.fragment_id
        )
        component = components_by_id.get(fragment.component_id)
        component_type = component.component_type if component is not None else ""
        candidates = [
            r for r in cr_records
            if not r.get("target_component_types") or component_type in r.get("target_component_types", [])
        ]
        if not candidates:
            candidates = [r for r in cr_records if r.get("coverage_relation_id") == "CR_IN_SCOPE"]
        if not candidates:
            continue
        chosen_record = rng.choice(candidates)
        ratio_lo, ratio_hi = chosen_record.get("default_inspection_ratio_range") or [0.5, 1.0]
        inspected_ratio = rng.uniform(float(ratio_lo), float(ratio_hi))
        covered_area = round(fragment.fragment_area_m2 * inspected_ratio, 2)
        coverage_state = "covered" if inspected_ratio > 0.5 else "obscured"
        obscuration_classes = chosen_record.get("obscuration_classes") or ["none"]
        obscuration = obscuration_classes[0] if obscuration_classes else "none"
        cr_suffix = _sanitize_id_component(fragment.fragment_id.replace("FRG-", ""))
        relations.append(
            CoverageRelation(
                coverage_id=f"CVR-{cr_suffix}-{fragment_index:02d}",
                coverage_relation_type=chosen_record["relation_type"],
                target_fragment_id=fragment.fragment_id,
                coverage_state=coverage_state,
                covered_area_m2=fragment.fragment_area_m2,
                inspected_area_m2=covered_area,
                obscuration_class=obscuration,
            )
        )
    return relations


# ---------- T-17c (T-19 并入): measurement 3 family 生成器 ----------


def _registry_slot_records_by_family(
    registries: RegistryBundle,
    target_families: List[str],
) -> List[Dict[str, Any]]:
    """Filter technical_measurement_registry by slot.measurement_family ∈ target_families."""
    return [
        record for record in _registry_records(registries, "technical_measurement_registry")
        if record.get("measurement_family") in target_families
    ]


def _normalize_distribution_name(dist: str) -> str:
    """DEBT-026: 把 proagent 输出的 distribution 名字 normalize 到 canonical sampler name.

    proagent 倾向用更精确的语义名（"truncated_normal" / "rounded_truncated_normal" /
    "discrete_mixture_rounded" / "zero_inflated_lognormal" 等），但底层 sampler
    支持 5 类原型：normal / lognormal / uniform / triangular / bernoulli。

    映射规则（loss-of-fidelity 注：mixture / zero_inflated / beta 全部退化到 overall
    mean+sigma 单峰；真正 mixture 派生留待未来扩展）：
        truncated_normal                → normal（_sample_typical_distribution 自带 clip）
        rounded_truncated_normal        → normal（integer value_type 自动 round）
        mixture_truncated_normal        → normal（overall mean/sigma）
        discrete_mixture_rounded        → normal（discrete 退化为 normal + round）
        zero_inflated_discrete          → normal（zero inflation 损失）
        formula_mixture_discrete        → normal（公式细节损失）
        zero_inflated_lognormal         → lognormal（zero inflation 损失）
        log_normal / log-normal         → lognormal
        beta / beta_mixture             → normal（bounded shape 损失，clip 由 bounds 处理）
        bernoulli_as_float / bernoulli  → bernoulli（mean = Bernoulli p；返回 0.0 / 1.0）
    """
    d = (dist or "").strip().lower().replace("-", "_")
    if d in (
        "normal", "gaussian", "truncated_normal", "rounded_truncated_normal",
        "mixture_truncated_normal", "mixture_rounded_truncated_normal",
        "rounded_normal", "mixture_normal",
        "discrete_mixture_rounded", "zero_inflated_discrete", "formula_mixture_discrete",
        "beta", "beta_mixture",
    ):
        return "normal"
    if d in ("lognormal", "log_normal", "zero_inflated_lognormal"):
        return "lognormal"
    if d == "uniform":
        return "uniform"
    if d == "triangular":
        return "triangular"
    if d in ("bernoulli", "bernoulli_as_float"):
        return "bernoulli"
    return d  # 未知名直接 pass through，让下游 fallback 处理


def _typical_min_max(slot_record: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """DEBT-026 (spec 04 §17): 解构 typical_bounds 复合字段为 (min, max)；缺则 (None, None)."""
    tb = slot_record.get("typical_bounds")
    if isinstance(tb, (list, tuple)) and len(tb) >= 2:
        return tb[0], tb[1]
    return None, None


def _has_typical_distribution(slot_record: Dict[str, Any]) -> bool:
    """DEBT-026 (spec 04 §17): 检查 slot 是否定义了 recommended distribution 参数.

    完备性判定（按 normalized distribution 名）：
        - normal / lognormal: 必须 recommended_mean + recommended_sigma
        - uniform: 必须 typical_bounds[min, max]
        - triangular: 必须 mean + typical_bounds
    任一字段缺失则退回 fallback 中点采样路径。

    支持 alias（详见 _normalize_distribution_name）：
        truncated_normal / rounded_truncated_normal / mixture_truncated_normal → normal
    """
    raw = slot_record.get("recommended_distribution")
    if not raw:
        return False
    dist = _normalize_distribution_name(str(raw))
    mean = slot_record.get("recommended_mean")
    sigma = slot_record.get("recommended_sigma")
    tmin, tmax = _typical_min_max(slot_record)
    if dist in ("normal", "lognormal"):
        return mean is not None and sigma is not None
    if dist == "uniform":
        return tmin is not None and tmax is not None
    if dist == "triangular":
        return mean is not None and tmin is not None and tmax is not None
    if dist == "bernoulli":
        # Bernoulli 把 mean 解释为 p，sigma 不强求（自动 sqrt(p*(1-p))）
        return mean is not None
    return False  # 未知 distribution 名 → fallback


def _sample_typical_distribution(
    slot_record: Dict[str, Any],
    physical_lo: float,
    physical_hi: float,
    rng: random.Random,
) -> float:
    """DEBT-026 (spec 04 §17 + spec 06 §11.5): 按 recommended distribution 采样 typical value.

    采样后 clip 到 typical_bounds 实操区间，再 clip 到 (physical_lo, physical_hi) hard bounds.

    distribution name 通过 _normalize_distribution_name 标准化，支持 truncated_normal /
    rounded_truncated_normal / mixture_truncated_normal alias。
    """
    raw = str(slot_record["recommended_distribution"])
    dist = _normalize_distribution_name(raw)
    mean = slot_record.get("recommended_mean")
    sigma = slot_record.get("recommended_sigma")
    tmin, tmax = _typical_min_max(slot_record)

    # [S2.5-CALIB 2026-06-17, DEBT-045 修法①验证] 真采样分支（两个被
    # _normalize_distribution_name 坍缩为单峰 normal 的形状）。诊断报告 §5.1/§5.4 指出
    # zero_inflated_discrete / 质量点 mixture 本是 registry 注释里声明过、被采样器坍缩掉的
    # 分布形状；恢复真采样是标定的前提，不是发明新形状。仅当 slot_record 显式带对应形状
    # 参数字段时启用，否则 fall through 到 normal（向后兼容，不影响其它 slot）。
    raw_lower = raw.strip().lower().replace("-", "_")
    if raw_lower == "zero_inflated_discrete" and slot_record.get("calib_zero_prob") is not None:
        # 零膨胀：以概率 π0 取 0（如"当日送达"），否则从尾部 rounded_truncated_normal 采样。
        zero_prob = float(slot_record["calib_zero_prob"])
        if rng.random() < zero_prob:
            value = 0.0
        else:
            tail_mean = float(slot_record.get("calib_tail_mean", mean if mean is not None else 1.0))
            tail_sigma = float(slot_record.get("calib_tail_sigma", sigma if sigma is not None else 1.0))
            value = rng.gauss(tail_mean, tail_sigma)
            # int value_type 的 round 由下游统一处理；此处先保证尾部不取 0（避免与质量点混淆）。
            value = max(value, 0.0)
    elif raw_lower in ("mixture_truncated_normal", "mixture_rounded_truncated_normal") and (
        slot_record.get("calib_mass_point_prob") is not None
    ):
        # 质量点 mixture：以概率 p 取质量点值（如纯悬臂全查 ratio=1.0），否则从连续成分采样。
        mass_prob = float(slot_record["calib_mass_point_prob"])
        if rng.random() < mass_prob:
            value = float(slot_record.get("calib_mass_point_value", 1.0))
        else:
            comp_mean = float(slot_record.get("calib_component_mean", mean if mean is not None else 0.5))
            comp_sigma = float(slot_record.get("calib_component_sigma", sigma if sigma is not None else 0.2))
            value = rng.gauss(comp_mean, comp_sigma)
    elif dist == "normal":
        value = rng.gauss(float(mean), float(sigma))
    elif dist == "lognormal":
        # DEBT-028 / DEBT-029 修复（2026-05-11）：mean 语义由 `mean_semantics` 显式标注，
        # mu 解析委托 `_resolve_lognormal_mu`（与 chain derive helper 共享同一公式实现）。
        # - "arithmetic_mean"（chain derive / pro round 设计标准）：mu = ln(arith) - σ²/2
        # - "median" 或缺省（向后兼容）：mu = ln(median)
        # 两种语义在 σ 大时差 e^(σ²/2) 倍（σ=0.75 偏 1.32×）。
        # 缺省 → "median"；非法 typo → raise（_resolve_lognormal_mu 内置防御）。
        raw_mean_semantics = slot_record.get("mean_semantics")
        mean_semantics = raw_mean_semantics if raw_mean_semantics is not None else "median"
        sigma_log = float(sigma)
        try:
            log_mu = _resolve_lognormal_mu(mean, sigma_log, mean_semantics)
        except ValueError as exc:
            raise ValueError(
                f"{exc} (slot_id={slot_record.get('slot_id', '?')!r})"
            ) from exc
        value = rng.lognormvariate(log_mu, sigma_log)
    elif dist == "uniform":
        value = rng.uniform(float(tmin), float(tmax))
    elif dist == "triangular":
        value = rng.triangular(float(tmin), float(tmax), float(mean))
    elif dist == "bernoulli":
        # mean 直接当 Bernoulli prevalence p；rng.random() < p → 1.0 否则 0.0
        # 用于 0/1 indicator（如 flag.drainage.misconnection_present）
        p = max(0.0, min(1.0, float(mean)))
        value = 1.0 if rng.random() < p else 0.0
    else:
        # 不应该到这里（_has_typical_distribution 已检查），保险 fallback 中点
        value = (physical_lo + physical_hi) / 2.0

    # Clip 1: typical_bounds 实操区间（如有）
    sample_lo = float(tmin) if tmin is not None else physical_lo
    sample_hi = float(tmax) if tmax is not None else physical_hi
    # DEBT-030 C 组 / spec 07 §4 line 70：双阶 clip P2 inline clamp audit hook
    slot_id_for_audit = slot_record.get("slot_id")
    after_t = max(sample_lo, min(sample_hi, value))
    if after_t != value:
        acc = _get_p2_audit_accumulator()
        if acc is not None:
            acc.record(
                check_id=_CHECK_ID_TYPICAL_BOUNDS_CLIP,
                before=value,
                after=after_t,
                slot_id=slot_id_for_audit,
            )
    value = after_t
    # Clip 2: physical_bounds hard 边界
    after_p = max(physical_lo, min(physical_hi, value))
    if after_p != value:
        acc = _get_p2_audit_accumulator()
        if acc is not None:
            acc.record(
                check_id=_CHECK_ID_TYPICAL_BOUNDS_CLIP,
                before=value,
                after=after_p,
                slot_id=slot_id_for_audit,
            )
    value = after_p
    return value


def _sample_value_for_slot(
    slot_record: Dict[str, Any],
    rng: random.Random,
) -> Tuple[Optional[float], Optional[bool], Optional[str]]:
    """Sample slot value——DEBT-026 后双路径（spec 04 §17 + spec 06 §11.5）：

    Path A（推荐）：slot_record 含 recommended_distribution + 完整参数 →
        按工程现实 typical 分布采样（normal / lognormal / uniform / triangular），
        clip 到 typical_bounds → 再 clip 到 physical_bounds。
    Path B（fallback，DEBT-026 baseline）：physical_bounds 中点 + spec §14 noise model。

    physical_bounds 中含表达式（如 "0.6*fragment_area"）时回退到固定数值（fragment 上下文不传入此函数）。
    """
    value_type = slot_record.get("value_type")
    bounds = slot_record.get("physical_bounds") or []
    if value_type == "bool":
        # spec 09 §1.2 / round2 suggested_followups #5: bool slot 含 bernoulli
        # distribution 时按 prevalence 采；否则 50% baseline.
        if _has_typical_distribution(slot_record):
            raw_dist = str(slot_record.get("recommended_distribution") or "")
            dist = _normalize_distribution_name(raw_dist)
            if dist == "bernoulli":
                mean = slot_record.get("recommended_mean")
                p = max(0.0, min(1.0, float(mean)))
                return None, bool(rng.random() < p), None
            # 其他 distribution 类型对 bool 没意义 → fallback 50%
        deterministic_bool = rng.random() < 0.5
        noisy_bool = apply_named_noise(
            "BOOL_DERIVED_NOISELESS",
            deterministic_bool,
            (0.0, 1.0),
            rng=rng,
        )
        return None, bool(noisy_bool), None

    lo: float = 0.0
    hi: float = 1.0
    if len(bounds) >= 2:
        try:
            lo = float(bounds[0])
        except (TypeError, ValueError):
            lo = 0.0
        try:
            hi = float(bounds[1])
        except (TypeError, ValueError):
            hi = max(lo + 1.0, 1.0)

    # DEBT-026 Path A: 走 recommended distribution
    if _has_typical_distribution(slot_record):
        value = _sample_typical_distribution(slot_record, lo, hi, rng)
    else:
        # Path B fallback: 中点 + named noise model（spec 06 §14）
        deterministic_value = (lo + hi) / 2.0
        measurement_family = str(slot_record.get("measurement_family") or "")
        noise_model_id = (
            "COUNT_POISSON_ROUND"
            if value_type == "integer"
            else get_noise_model_for_family(measurement_family)
        )
        value = float(apply_named_noise(
            noise_model_id=noise_model_id,
            deterministic_value=deterministic_value,
            bounds=(lo, hi),
            abs_sigma=0.0,
            rng=rng,
        ))

    # DEBT-030 C 组 / spec 07 §4 line 70：P2 inline clamp audit hook 入口
    slot_id_for_audit = slot_record.get("slot_id")

    if value_type == "integer":
        before_int = float(value)
        value_int = int(round(before_int))
        # 非负 + bounds 截断 (COUNT_NONNEG_CLAMP)
        clamped_int = max(int(lo), min(int(hi), value_int))
        if float(clamped_int) != before_int:
            acc = _get_p2_audit_accumulator()
            if acc is not None:
                acc.record(
                    check_id=_CHECK_ID_COUNT_NONNEG_CLAMP,
                    before=before_int,
                    after=float(clamped_int),
                    slot_id=slot_id_for_audit,
                )
        return float(clamped_int), None, None

    # DEBT-026 closure 2026-05-09 fix: precision_steps 兼容 dict / string 两种 schema：
    # - dict（生产代码）：registry.py::_measurement_record 构造时把 _PRECISION_STEPS[key] expand
    #   成 {"coarse": ..., "standard": ..., "fine": ...}；sidecar 字面量也是 dict
    # - string key（test fixtures）：直接传 PRECISION_ROUNDING 表 key（如 "geometry_width_mm"），
    #   走 apply_precision_rounding 路径
    # 旧代码 `apply_precision_rounding(value, str(dict), "standard")` 把 dict 转 str 当 key
    # 查表 → key 不命中 → rounding 被跳过（precision rounding 一直没生效，DEBT-026 收尾时发现）。
    precision_steps = slot_record.get("precision_steps")
    value = float(value)
    before_prec = value
    if isinstance(precision_steps, dict):
        step = precision_steps.get("standard")
        if step and float(step) > 0:
            step_f = float(step)
            value = round(value / step_f) * step_f
    elif isinstance(precision_steps, str) and precision_steps:
        value = float(apply_precision_rounding(value, precision_steps, "standard"))
    # DEBT-030 C 组：PRECISION_ROUNDING audit (value 真发生变化才计)
    if value != before_prec:
        acc = _get_p2_audit_accumulator()
        if acc is not None:
            acc.record(
                check_id=_CHECK_ID_PRECISION_ROUNDING,
                before=before_prec,
                after=value,
                slot_id=slot_id_for_audit,
            )
    # 末段 physical_bounds 兜底 clip
    before_final = value
    value = max(lo, min(hi, value))
    if value != before_final:
        acc = _get_p2_audit_accumulator()
        if acc is not None:
            acc.record(
                check_id=_CHECK_ID_TYPICAL_BOUNDS_CLIP,
                before=before_final,
                after=value,
                slot_id=slot_id_for_audit,
            )
    return round(value, 4), None, None


def _build_measurement_record_for_slot(
    slot_record: Dict[str, Any],
    target_ref: str,
    measurement_family: str,
    derivation_mode: str,
    measurement_index: int,
    rng: random.Random,
) -> "MeasurementRecord":
    """Construct one MeasurementRecord from a registry slot definition."""
    value_num, value_bool, value_enum = _sample_value_for_slot(slot_record, rng)
    method_classes = list(slot_record.get("method_classes") or [])
    method_class = method_classes[0] if method_classes else None
    measurement_id = (
        f"MSR-{_sanitize_id_component(target_ref)}-{_sanitize_id_component(slot_record['slot_id'])}-{measurement_index:02d}"
    )
    sample_count = rng.randint(1, 5) if value_num is not None else None
    return MeasurementRecord(
        measurement_id=measurement_id,
        target_ref=target_ref,
        measurement_family=measurement_family,
        slot_id=slot_record["slot_id"],
        value_num=value_num,
        value_bool=value_bool,
        value_enum=value_enum,
        unit=slot_record.get("unit"),
        precision_class="standard",
        method_class=method_class,
        sample_count=sample_count,
        confidence_index=round(rng.uniform(0.6, 0.95), 3),
        derivation_refs=[target_ref],
        derivation_mode=derivation_mode,
    )


def _build_measurement_record_with_value(
    slot_record: Dict[str, Any],
    target_ref: str,
    measurement_family: str,
    derivation_mode: str,
    measurement_index: int,
    value_num: Optional[float] = None,
    value_bool: Optional[bool] = None,
    value_enum: Optional[str] = None,
    qualifiers: Optional[Dict[str, Any]] = None,
    method_class_override: Optional[str] = None,
) -> "MeasurementRecord":
    """Construct one MeasurementRecord with explicit value (skip noise sampling).

    DEBT-020 round5 sub-task 6 (2026-05-10): qualifiers 携带 fragment 物理 metadata
    （如 rebar_type / rebar_location / corrosion_loss_type），让消费层能看到物理上下文.

    DEBT-049 Phase3 U5 §2.1b: `method_class_override` 非 None 时覆写 slot `method_classes[0]`
    兜底（P1/P2 smoke/water 覆写既有 drainage index/flag 测量的 method_class；总函数选取，无随机）。
    """
    method_classes = list(slot_record.get("method_classes") or [])
    method_class = method_class_override if method_class_override else (
        method_classes[0] if method_classes else None
    )
    measurement_id = (
        f"MSR-{_sanitize_id_component(target_ref)}-{_sanitize_id_component(slot_record['slot_id'])}-{measurement_index:02d}"
    )
    return MeasurementRecord(
        measurement_id=measurement_id,
        target_ref=target_ref,
        measurement_family=measurement_family,
        slot_id=slot_record["slot_id"],
        value_num=value_num,
        value_bool=value_bool,
        value_enum=value_enum,
        unit=slot_record.get("unit"),
        precision_class="standard",
        method_class=method_class,
        sample_count=None,
        confidence_index=0.95,
        derivation_refs=[target_ref],
        derivation_mode=derivation_mode,
        qualifiers=dict(qualifiers) if qualifiers else {},
    )


def _emit_drainage_airball_observation(
    fragment: "FragmentContext",
    drainage: "DrainageState",
    technical_slot_index: Dict[str, Any],
    selected_method: str,
    measurement_index: int,
) -> Optional["MeasurementRecord"]:
    """DEBT-049 Phase3 U5 §2.1b：P3a(air)/P3b(ball) 专用观测 emit——谓词命中即返 **恰 1 条** record。

    发射条件只看 DrainageState 物理场（``selected_method`` 由 ``_select_drainage_method_class``
    对 blockage_index/segment_type 的总函数选取给出），**与 mechanism.active 解耦**——inactive
    mechanism 的 drainage fragment 谓词命中同样发射（spec §2.1b 冻结「命中 fragment 必须恰 1 条
    专用记录」）。观测数值抖动走独立 domain-separated 子流 ``_drainage_airball_obs_rng(drainage_id)``，
    不消费 caller 的 rng（既有 fragment/generic/facade-chain 抽样序列零扰动）。air/ball 因 segment_type
    单值互斥，每 fragment 至多 1 条。slot 缺失或 method 非 air/ball 时返 None（caller 不 append）。
    """
    airball_rng = _drainage_airball_obs_rng(drainage.drainage_id)
    if selected_method == "air_test":
        air_slot = technical_slot_index.get("pressure.drainage.air_test.loss_mmH2O")
        if air_slot is None:
            return None
        return _build_measurement_record_with_value(
            slot_record=air_slot,
            target_ref=fragment.fragment_id,
            measurement_family="technical_validation_measurement",
            derivation_mode="technical_validation_plan",
            measurement_index=measurement_index,
            value_num=_compute_air_test_pressure_loss_mmH2O(drainage, airball_rng),
            qualifiers=_air_test_qualifiers(drainage.is_underground),
        )
    if selected_method == "ball_test":
        ball_slot = technical_slot_index.get("flag.drainage.ball_test.pass")
        if ball_slot is None:
            return None
        return _build_measurement_record_with_value(
            slot_record=ball_slot,
            target_ref=fragment.fragment_id,
            measurement_family="technical_validation_measurement",
            derivation_mode="technical_validation_plan",
            measurement_index=measurement_index,
            value_bool=_compute_ball_test_pass(drainage, airball_rng),
        )
    return None


def generate_coverage_sampling_measurements(
    building: BuildingContext,
    components: List[ComponentNode],
    fragments: List[FragmentContext],
    registries: RegistryBundle,
    *,
    world_id: str,
    per_fragment_count: int = 2,
) -> List[MeasurementRecord]:
    """spec 03 Step 6 / spec 04 §16 coverage_sampling measurement family
    (derivation_mode='coverage_sampling_plan'; W1-015 docstring 替换 T-19 历史工单编号).

    For each fragment, sample `per_fragment_count` coverage_sampling slots from registry.

    🔴 1a-i（波次二 #22）：改逐片段子流，主 rng 形参已删。见
    `generate_coverage_relations` 同款说明。
    """
    slot_pool = _registry_slot_records_by_family(registries, ["coverage_sampling"])
    if not slot_pool:
        return []
    measurements: List[MeasurementRecord] = []
    for fragment in fragments:
        rng = rng_domains.sub_rng(
            rng_domains.COVERAGE_SAMPLING, world_id, fragment.fragment_id
        )
        chosen = list(slot_pool)
        rng.shuffle(chosen)
        for index, slot_record in enumerate(chosen[:per_fragment_count]):
            measurements.append(
                _build_measurement_record_for_slot(
                    slot_record=slot_record,
                    target_ref=fragment.fragment_id,
                    measurement_family="coverage_sampling_measurement",
                    derivation_mode="coverage_sampling_plan",
                    measurement_index=index,
                    rng=rng,
                )
            )
    return measurements


def generate_technical_validation_measurements(
    building: BuildingContext,
    fragments: List[FragmentContext],
    conditions: List[ConditionState],
    registries: RegistryBundle,
    *,
    world_id: str,
    per_fragment_count: int = 2,
) -> List[MeasurementRecord]:
    """spec 03 Step 7 / spec 04 §16 technical_validation + boolean_assertion measurement family
    (derivation_mode='technical_validation_plan'; W1-015 docstring 替换 T-19 历史工单编号).

    For each fragment with verification-relevant condition, sample `per_fragment_count` slots.

    🔴 1a-i（波次二 #22）：改逐片段子流，主 rng 形参已删。子流建在两条分支**之前**——
    本阶段的分支不对称（`condition is None or severity < 0.2` 走 not_applicable 路径、
    该路径不消费 rng 造值），过去这正是「某片段严重度跨过 0.2 ⇒ 其后所有片段量测移位」
    的第二重耦合来源；键控子流后该耦合结构上消失。
    """
    slot_pool = _registry_slot_records_by_family(registries, ["technical_validation", "boolean_assertion"])
    if not slot_pool:
        return []
    condition_by_fragment = {c.fragment_id: c for c in conditions}
    measurements: List[MeasurementRecord] = []
    for fragment in fragments:
        rng = rng_domains.sub_rng(
            rng_domains.TECHNICAL_VALIDATION, world_id, fragment.fragment_id
        )
        condition = condition_by_fragment.get(fragment.fragment_id)
        # W1-003 / spec 10 §6 silent fallback 红线 + spec 07 §2.3 公式输入缺时输出 `not_applicable`
        # 不 silently drop：fragment 没有 condition 或 severity 过低（< 0.2，无 verification 必要）时，
        # 仍 emit 一条 `not_applicable` measurement record 保 audit trace（不再 silent continue）.
        if condition is None or condition.severity_index < 0.2:
            chosen = list(slot_pool)
            rng.shuffle(chosen)
            for index, slot_record in enumerate(chosen[:per_fragment_count]):
                reason = (
                    "no_condition"
                    if condition is None
                    else f"severity_below_verification_threshold(severity={condition.severity_index:.3f}<0.2)"
                )
                measurements.append(
                    _build_measurement_record_with_value(
                        slot_record=slot_record,
                        target_ref=fragment.fragment_id,
                        measurement_family="technical_validation_measurement",
                        derivation_mode="technical_validation_plan",
                        measurement_index=index,
                        value_enum="not_applicable",
                        qualifiers={"not_applicable_reason": reason},
                    )
                )
            continue
        chosen = list(slot_pool)
        rng.shuffle(chosen)
        for index, slot_record in enumerate(chosen[:per_fragment_count]):
            measurements.append(
                _build_measurement_record_for_slot(
                    slot_record=slot_record,
                    target_ref=fragment.fragment_id,
                    measurement_family="technical_validation_measurement",
                    derivation_mode="technical_validation_plan",
                    measurement_index=index,
                    rng=rng,
                )
            )
    return measurements


def generate_structural_assessment_measurements(
    building: BuildingContext,
    fragments: List[FragmentContext],
    conditions: List[ConditionState],
    mechanisms: List[MechanismState],
    components_by_id: Dict[str, ComponentNode],
    registries: RegistryBundle,
    *,
    world_id: str,
    per_fragment_count: int = 2,
    drainage_by_fragment: Optional[Dict[str, "DrainageState"]] = None,
    drivers_by_fragment: Optional[Dict[str, "DriverState"]] = None,
) -> List[MeasurementRecord]:
    """spec 03 Step 8 / spec 04 §16 structural_assessment measurement family
    (defect_geometry + derived_risk_measurement，derivation_mode='damage_downstream' /
    'assessment_plan'; W1-015 docstring 替换 T-19 历史工单编号).

    For each fragment with active mechanism, sample defect_geometry / derived_risk slots.

    DEBT-020 round2 closure 2026-05-09 (#3 接通)：`public_health_risk_index` 走 spec 06 §5
    `_compute_drainage_public_health_risk_index` derive 路径（值已在 DrainageState 落 line 1164）；
    通过 `derivation_mode='surrogate_driven'` 显式 emit，不走 `_sample_value_for_slot` distribution
    路径。`drainage_by_fragment` (dict[fragment_id, DrainageState]) 由 caller 在 fragment loop 内
    构造并传入；fragment 无 drainage 时跳过 explicit derive，回退到 distribution.

    W0-005 (2026-05-21)：物理上下文走 spec 06 §0.1 reference 反查 ——
    `cover_depth_mm` / `material_system` / `structural_role` / `component_type` 走
    `components_by_id[fragment.component_id]`（spec 04 §5 ComponentNode），
    `fragment_length_m` / `fragment_area_m2` 走 `fragment`（spec 04 §7 FragmentContext）；
    has_rebar 走 `_material_system_supports_rebar(component.material_system, registries)`
    （spec 03 §4.6 material_system_registry.supports_rebar 权威）.
    """
    slot_pool = _registry_slot_records_by_family(registries, ["defect_geometry", "derived_risk_measurement"])
    technical_slot_index = _registry_index(registries, "technical_measurement_registry", "slot_id")
    formula_slot_records: List[Dict[str, Any]] = []
    seen_formula_slot_ids: set[str] = set()
    for table in registries.registries:
        if table.registry_id != "assessment_surrogate_registry":
            continue
        for record in table.records:
            for slot_id in record.get("output_slots") or []:
                slot_id_lower = str(slot_id).lower()
                if "fsp" not in slot_id_lower and "core_sample" not in slot_id_lower:
                    continue
                slot_record = technical_slot_index.get(slot_id)
                if slot_record is None or slot_id in seen_formula_slot_ids:
                    continue
                formula_slot_records.append(slot_record)
                seen_formula_slot_ids.add(slot_id)

    # DEBT-020 round2 #3 + 后续接通 (2026-05-09)：A 类 slot 加入 explicit formula 路径
    # 严格按 spec→code 单向原则核查后纳入：
    #   spec 06 §5 drainage 4 个：blockage / leakage / misconnection / public_health_risk_index
    #   spec 06 §4 rebar/spall 2 个：rebar_exposed_length_m / spall_area_m2
    #   spec 06 §1.3 + §3.2 crack 2 个：crack_width_mm / crack_length_m (round5 sub-task 1, 2026-05-10)
    #   spec 06 §8 §9 chain_C_plus 2 个：rate.pull_test.per_25m2 / ratio.covered_area.inspected
    #     (round5 sub-task 2, 2026-05-10) — Option C+ 链式派生
    for derive_slot_id in (
        "public_health_risk_index",
        "index.drainage.blockage",
        "index.drainage.leakage",
        "flag.drainage.misconnection_present",
        "rebar_exposed_length_m",
        "spall_area_m2",
        "crack_width_mm",
        "crack_length_m",
        # DEBT-020 round5 sub-task 2 chain_C_plus
        "rate.pull_test.per_25m2",
        "ratio.covered_area.inspected",
        # DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas 升 A 类 derive
        "length.concrete_repair.depth",
        "time.fire_door.self_closing.delay_sec",
        "stress.pull_test.minimum",
        "count.hammer_tapping.grid.minimum",
        "count.pull_test.per_repaired_facade",
        "count.pull_test.per_floor_full_retiling",
        # DEBT-020 round5 sub-task 6 (2026-05-10) RebarSectionLossExtend per-class lognormal
        "ratio.rebar.section_loss",
    ):
        if derive_slot_id in seen_formula_slot_ids:
            continue
        derive_slot_record = technical_slot_index.get(derive_slot_id)
        if derive_slot_record is not None:
            formula_slot_records.append(derive_slot_record)
            seen_formula_slot_ids.add(derive_slot_id)

    if not slot_pool and not formula_slot_records:
        return []
    mechanism_by_fragment = {m.fragment_id: m for m in mechanisms}
    conditions_by_fragment: Dict[str, List[ConditionState]] = {}
    for condition in conditions:
        conditions_by_fragment.setdefault(condition.fragment_id, []).append(condition)
    drainage_by_fragment = drainage_by_fragment or {}
    drivers_by_fragment = drivers_by_fragment or {}

    # ---------- DEBT-020 round5 sub-task 2 chain_C_plus 立面级 plan 数据（一栋楼共享）----------
    # 授权：spec 06 §9 chain Step 1-3 + sampling_plan_registry::pull_test_sampling_plan
    # DEBT-030 D2 (2026-05-13): chain helper 现走 registries 反查 sampling_plan_registry
    # plan_intensity_distribution / total_count_formula round_clip;
    # registries 缺失时退 hardcoded constants.
    # building seed RNG 通过 _building_chain_seed_rng(building.building_id) 派生，
    # 让同一立面（同一 building_id）多次调用得到稳定的 facade plan 数据；
    # 与 fragment seed RNG 解耦.
    building_chain_rng = _building_chain_seed_rng(building.building_id)
    facade_total_repaired_area_m2 = _compute_facade_total_repaired_area_m2(
        building_chain_rng, registries
    )
    plan_intensity_tests_per_25m2 = _compute_plan_intensity_tests_per_25m2(
        building_chain_rng, registries
    )
    total_pull_test_count_per_facade = _compute_total_pull_test_count_per_facade(
        plan_intensity_tests_per_25m2, facade_total_repaired_area_m2, registries
    )

    # ---------- DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas chain ----------
    # facade-level pull_test count for repaired_facade slot — 复用 facade chain；
    # floor-level retiling chain for per_floor_full_retiling slot — 独立 building seed RNG.
    # 授权：spec 06 §9.X + sampling_plan_registry::floor_retiling_package
    # DEBT-030 D2 (2026-05-13): registry-driven 同 facade chain.
    floor_retiling_area_m2 = _compute_floor_full_retiling_area_m2(
        building_chain_rng, registries
    )
    retiling_plan_intensity = _compute_retiling_plan_intensity_tests_per_25m2(
        building_chain_rng, registries
    )
    pull_test_count_per_floor_full_retiling = _compute_pull_test_count_per_floor_full_retiling(
        retiling_plan_intensity, floor_retiling_area_m2, registries
    )

    measurements: List[MeasurementRecord] = []
    for fragment in fragments:
        mechanism = mechanism_by_fragment.get(fragment.fragment_id)
        if mechanism is None or not mechanism.active:
            continue

        # W0-005 (2026-05-21)：spec 06 §0.1 reference 反查—— component / location 物理上下文显式 lookup.
        component = components_by_id.get(fragment.component_id)
        if component is None:
            continue  # 无法定位 component → 跳过本 fragment（reference contract 主键不应该缺失）
        # 🔴 1a-i（波次二 #22）：逐片段子流，建在**两个 guard 之后**——被跳过的片段
        # 不建无用子流，也让「哪些片段被跳过」不再影响其余片段拿到哪条流
        # （本阶段的 guard 极不对称：inactive mechanism / 缺 component 的片段零消费，
        #  过去它们的存在与否会整体移位后续片段的抽样）。
        rng = rng_domains.sub_rng(
            rng_domains.STRUCTURAL_ASSESSMENT, world_id, fragment.fragment_id
        )
        fragment_area_m2 = fragment.fragment_area_m2
        fragment_length_m = fragment.fragment_length_m or 0.0
        cover_depth_mm = component.cover_depth_mm
        component_type = component.component_type
        structural_role = component.structural_role
        # W0-005 (2026-05-21)：spec 06 §0.1 表 row `has_rebar`——derive：
        # `component.material_system == "reinforced_concrete"` OR
        # `material_system_registry[component.material_system].supports_rebar`；不作为独立字段.
        # 优先用 `_material_system_supports_rebar` registry lookup；registry 缺失退到字面量判断
        # （含 reinforced/prestressed/precast concrete 家族，与 spec 03 §4.6 supports_rebar 一致）.
        has_rebar = (
            _material_system_supports_rebar(component.material_system, registries)
            or component.material_system in (
                "reinforced_concrete", "prestressed_concrete", "precast_concrete",
            )
        )

        fragment_measurement_index = 0
        emitted_formula_slot_ids: set[str] = set()

        fragment_conditions = conditions_by_fragment.get(fragment.fragment_id, [])
        max_severity = _compute_max_condition_severity(fragment_conditions)
        fsp_true = _compute_fsp_true(max_severity, building.age_years)
        component_volume_m3 = _estimate_component_volume_m3(fragment, component)
        core_sample_count = _compute_core_sample_count(component_volume_m3)
        core_sample_rate = (
            core_sample_count / max(component_volume_m3, 1e-9)
            if component_volume_m3 > 0
            else 0.0
        )

        # 取本 fragment 的 first condition（generator 当前 1:1 fragment ↔ condition）
        first_condition = fragment_conditions[0] if fragment_conditions else None

        # DEBT-049 Phase3 U5 §2.1：本 fragment 的 drainage method_class 确定性选取（总函数，无随机）。
        # 一次算好复用：P1/P2(smoke/water) 覆写既有 drainage index/flag 测量的 method_class；
        # P3a/P3b(air/ball) 保 drainage index 测量的 drainage_cctv 兜底不覆写、改 emit 专用观测 slot；
        # P4(cctv) 兜底本就 drainage_cctv、无须覆写。
        drainage_for_method = drainage_by_fragment.get(fragment.fragment_id)
        selected_drainage_method = (
            _select_drainage_method_class(drainage_for_method)
            if drainage_for_method is not None
            else None
        )
        # 仅 smoke/water 覆写既有 index/flag 测量的 method_class；air/ball/cctv 不覆写（保 drainage_cctv）。
        drainage_method_override = (
            selected_drainage_method
            if selected_drainage_method in ("smoke_test", "water_test")
            else None
        )

        for slot_record in formula_slot_records:
            slot_id = str(slot_record["slot_id"])
            slot_id_lower = slot_id.lower()
            explicit_value_num: Optional[float] = None
            explicit_value_bool: Optional[bool] = None
            # 默认 family / mode 与 fsp/core_sample 一致（assessment_plan）
            explicit_family: str = "structural_assessment_measurement"
            explicit_mode: str = "assessment_plan"
            # DEBT-020 round5 sub-task 6 (2026-05-10): 物理 metadata 携带 (rebar_type 等)
            # 仅 ratio.rebar.section_loss 路径填；其他 slot 保持空 dict.
            explicit_qualifiers: Optional[Dict[str, Any]] = None
            # DEBT-049 Phase3 U5 §2.1b: 仅三条 drainage index/flag slot 在 P1/P2 时覆写 method_class。
            explicit_method_class_override: Optional[str] = None

            if "fsp" in slot_id_lower:
                explicit_value_num = round(fsp_true, 4)
            elif "rate.core_sample" in slot_id_lower:
                explicit_value_num = round(core_sample_rate, 4)
            elif "core_sample" in slot_id_lower:
                explicit_value_num = float(core_sample_count)
            elif slot_id == "public_health_risk_index":
                # spec 06 §5 _compute_drainage_public_health_risk_index 已在 DrainageState 落 line 1164
                drainage = drainage_by_fragment.get(fragment.fragment_id)
                if drainage is not None:
                    explicit_value_num = round(float(drainage.public_health_risk_index), 4)
            elif slot_id == "index.drainage.blockage":
                # spec 06 §5 blockage_index 已在 DrainageState 落
                drainage = drainage_by_fragment.get(fragment.fragment_id)
                if drainage is not None:
                    explicit_value_num = round(float(drainage.blockage_index), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
                    explicit_method_class_override = drainage_method_override  # DEBT-049 §2.1b
            elif slot_id == "index.drainage.leakage":
                # spec 06 §5 leakage_index 已在 DrainageState 落
                drainage = drainage_by_fragment.get(fragment.fragment_id)
                if drainage is not None:
                    explicit_value_num = round(float(drainage.leakage_index), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
                    explicit_method_class_override = drainage_method_override  # DEBT-049 §2.1b
            elif slot_id == "flag.drainage.misconnection_present":
                # spec 06 §5 misconnection_present 已在 DrainageState 落（bool）
                drainage = drainage_by_fragment.get(fragment.fragment_id)
                if drainage is not None:
                    explicit_value_bool = bool(drainage.misconnection_present)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
                    explicit_method_class_override = drainage_method_override  # DEBT-049 §2.1b
            elif slot_id == "rebar_exposed_length_m":
                # spec 06 §4 rebar_exposed_length_m 仅在 mechanism="corrosion_spall" 路径走 derive
                # （generator.py:1086-1099 用 _compute_rebar_exposed_length_m 严格 spec 公式 derive，
                # 写入 ConditionState.extent_length_m）；其他 mechanism 路径的 extent_length_m 是 ad-hoc
                # 派生（rng.uniform 系数无 spec 授权），不能走 derive 路径，跳过 fallback distribution
                if (
                    mechanism.mechanism_family == "corrosion_spall"
                    and first_condition is not None
                    and first_condition.extent_length_m is not None
                ):
                    explicit_value_num = round(float(first_condition.extent_length_m), 4)
                    explicit_family = "defect_geometry_measurement"
                    explicit_mode = "damage_downstream"
            elif slot_id == "spall_area_m2":
                # spec 06 §4 spall_patch_area_m2 同上限定 corrosion_spall
                if (
                    mechanism.mechanism_family == "corrosion_spall"
                    and first_condition is not None
                    and first_condition.extent_area_m2 is not None
                ):
                    explicit_value_num = round(float(first_condition.extent_area_m2), 4)
                    explicit_family = "defect_geometry_measurement"
                    explicit_mode = "damage_downstream"
            elif slot_id == "crack_width_mm":
                # spec 06 §3.2 + §1.3 (DEBT-020 round5 sub-task 1, 2026-05-10):
                # primary_crack_opening_mm_true derive；仅 mechanism="structural_crack" 路径走 derive.
                # Option ① true-then-noise 链路：本节输出 true 值；reported = true + GEOM_REL_ABS_GAUSS noise
                # 当前与 spall/rebar 一致暂不接 noise 包装（uniform geometry noise refactor 留 DEBT-021 / 后续）.
                driver = drivers_by_fragment.get(fragment.fragment_id)
                if (
                    mechanism.mechanism_family == "structural_crack"
                    and driver is not None
                ):
                    activation = _compute_crack_activation_score(
                        driver.service_load_ratio,
                        driver.restraint_level,
                        driver.workmanship_deficit_index,
                    )
                    age_norm_val = _age_norm(building.age_years)
                    severity = _compute_crack_severity(activation, age_norm_val, driver.moisture_ingress_index)
                    crack_width_true = _compute_primary_crack_opening_mm_true(
                        severity,
                        driver.service_load_ratio,
                        driver.restraint_level,
                    )
                    explicit_value_num = round(float(crack_width_true), 4)
                    explicit_family = "defect_geometry_measurement"
                    explicit_mode = "damage_downstream"
            elif slot_id == "crack_length_m":
                # spec 06 §3.2 + §1.3: primary_crack_length_m_true derive
                driver = drivers_by_fragment.get(fragment.fragment_id)
                if (
                    mechanism.mechanism_family == "structural_crack"
                    and driver is not None
                ):
                    activation = _compute_crack_activation_score(
                        driver.service_load_ratio,
                        driver.restraint_level,
                        driver.workmanship_deficit_index,
                    )
                    age_norm_val = _age_norm(building.age_years)
                    severity = _compute_crack_severity(activation, age_norm_val, driver.moisture_ingress_index)
                    crack_length_true = _compute_primary_crack_length_m_true(
                        severity,
                        fragment_length_m,
                    )
                    explicit_value_num = round(float(crack_length_true), 4)
                    explicit_family = "defect_geometry_measurement"
                    explicit_mode = "damage_downstream"
            elif slot_id == "rate.pull_test.per_25m2":
                # DEBT-020 round5 sub-task 2 chain_C_plus (spec 06 §9 chain Step 4 + 5)：
                # facade-level total_count → per-fragment area-proportional effective_count → rate.
                # 用户决策（2026-05-10 假设 2 接受）：fragment_repaired_area_m2 缺失时
                # 用 fragment.fragment_area_m2 代理（spec 04 §7 FragmentContext）.
                # fallback 路径：facade plan 退化（area<=0）时跳过 → 走 distribution Path B.
                fragment_repaired_area = float(fragment_area_m2)
                if (
                    fragment_repaired_area > 0.0
                    and facade_total_repaired_area_m2 > 0.0
                ):
                    effective_count = _compute_effective_pull_test_count_per_fragment(
                        total_pull_test_count_per_facade,
                        fragment_repaired_area,
                        facade_total_repaired_area_m2,
                    )
                    rate_value = _compute_pull_test_rate_per_25m2_chain(
                        effective_count, fragment_repaired_area
                    )
                    explicit_value_num = round(float(rate_value), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            elif slot_id == "ratio.covered_area.inspected":
                # DEBT-020 round5 sub-task 2 chain_C_plus (spec 06 §8 chain Step 1-3)：
                # per-fragment truncated_normal sample → inspected_area_m2 → ratio derive.
                # 用 fragment seed RNG（外层 rng 即 fragment-loop scope）保持 per-fragment 独立性.
                # fallback 路径：fragment_area<=0 时跳过 → 走 distribution Path B.
                fragment_area = float(fragment_area_m2)
                if fragment_area > 0.0:
                    # DEBT-030 D2 (2026-05-13): registry-driven chain helper.
                    inspected_ratio = _compute_inspected_area_ratio_per_fragment(rng, registries)
                    inspected_area = _compute_inspected_area_m2_chain(
                        inspected_ratio, fragment_area
                    )
                    ratio_value = _compute_ratio_covered_area_inspected_chain(
                        inspected_area, fragment_area
                    )
                    explicit_value_num = round(float(ratio_value), 4)
                    explicit_family = "coverage_sampling_measurement"
                    explicit_mode = "coverage_sampling_plan"
            # ---------- DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas 升 A 类 derive ----------
            elif slot_id == "length.concrete_repair.depth":
                # spec 06 §X.X derive: cover_depth + spall + corrosion + chloride 物理因果.
                # W0-005: cover_depth_mm 走 component.cover_depth_mm（spec 06 §0.1 reference 反查）.
                driver = drivers_by_fragment.get(fragment.fragment_id)
                if driver is not None and first_condition is not None:
                    spall_severity = first_condition.severity_index if mechanism.mechanism_family == "corrosion_spall" else 0.0
                    corrosion_severity = _compute_corrosion_severity(driver, cover_depth_mm, building.age_years)
                    depth_value = _compute_concrete_repair_depth_mm(
                        cover_depth_mm,
                        spall_severity,
                        corrosion_severity,
                        driver.chloride_exposure_index,
                    )
                    explicit_value_num = round(float(depth_value), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            elif slot_id == "time.fire_door.self_closing.delay_sec":
                # spec 06 §X.X derive: applicability 仅在 component 是 fire_door 类时生效.
                # W0-005: component_type 走 component.component_type（spec 06 §0.1 reference 反查），
                # 删除旧 `fragment.fragment_scope` 兜底 substring 检查（fragment_scope 旧实现 = location.
                # location_class，location_class enum 中无 "fire_safety" 字符串 → 旧检查永远 False，
                # 不携带任何 spec 授权 fallback 路径）.
                driver = drivers_by_fragment.get(fragment.fragment_id)
                applicable = "fire_door" in (component_type or "").lower()
                if applicable and driver is not None:
                    age_norm_val = _age_norm(building.age_years)
                    fire_def_present = driver.fire_safety_deficit_index >= 0.45
                    delay_value = _compute_fire_door_self_closing_delay_sec(
                        driver.maintenance_deficit_index,
                        age_norm_val,
                        driver.moisture_ingress_index,
                        fire_def_present,
                    )
                    explicit_value_num = round(float(delay_value), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            elif slot_id == "stress.pull_test.minimum":
                # spec 06 §X.X derive: repair_quality + moisture + workmanship 物理因果
                driver = drivers_by_fragment.get(fragment.fragment_id)
                if driver is not None:
                    stress_value = _compute_pull_test_minimum_stress_n_per_mm2(
                        driver.repair_quality_index,
                        driver.moisture_ingress_index,
                        driver.workmanship_deficit_index,
                    )
                    explicit_value_num = round(float(stress_value), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            elif slot_id == "count.hammer_tapping.grid.minimum":
                # spec 06 §X.X derive: 几何因果（visible / fragment area + cell size）.
                # W0-005: visible / fragment area 都走 fragment.fragment_area_m2（spec 04 §7 FragmentContext）.
                if fragment_area_m2 > 0.0:
                    detachment_severity = (
                        first_condition.severity_index
                        if first_condition is not None
                        and mechanism.mechanism_family == "moisture_detachment"
                        else 0.0
                    )
                    spall_severity = (
                        first_condition.severity_index
                        if first_condition is not None
                        and mechanism.mechanism_family == "corrosion_spall"
                        else 0.0
                    )
                    grid_count = _compute_hammer_tapping_grid_minimum(
                        fragment_area_m2,
                        fragment_area_m2,  # fragment_area_m2 代理
                        detachment_severity,
                        spall_severity,
                    )
                    explicit_value_num = float(grid_count)
                    explicit_family = "coverage_sampling_measurement"
                    explicit_mode = "coverage_sampling_plan"
            elif slot_id == "count.pull_test.per_repaired_facade":
                # spec 06 §X.X derive: 复用 #2 facade chain plan
                # plan_intensity_tests_per_25m2 + facade_total_repaired_area_m2 → round_clip
                if facade_total_repaired_area_m2 > 0.0:
                    # facade-level total_count，已在 building chain 算好；本 fragment 共享 facade 计划
                    explicit_value_num = float(total_pull_test_count_per_facade)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            elif slot_id == "count.pull_test.per_floor_full_retiling":
                # spec 06 §X.X derive: floor-level retiling chain
                if floor_retiling_area_m2 > 0.0:
                    explicit_value_num = float(pull_test_count_per_floor_full_retiling)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
            # ---------- DEBT-020 round5 sub-task 6 (2026-05-10) RebarSectionLossExtend per-class lognormal ----------
            elif slot_id == "ratio.rebar.section_loss":
                # 用户决策方案 B (per-class lognormal + 物理因果调制)；不走 multiplier 方案 A.
                # 派生 rebar_type / rebar_location / corrosion_loss_type 物理 metadata 写进 measurement.qualifiers.
                # applicability: has_rebar + (corrosion_spall mechanism OR rebar exposure 相关 condition).
                # W0-005: has_rebar 走 material_system_registry.supports_rebar；
                # structural_role / cover_depth_mm / component_type 走 component（spec 06 §0.1 reference 反查）.
                # 旧 `fragment_scope` 参数走 component_type（spec 06 §0.1 表："domain_of(component.component_type)"），
                # _sample_rebar_location 接受字符串描述其分类语义，传 component_type 保持等价（rebar_location
                # 仅按"external_wall / column / beam"模式分类）.
                driver = drivers_by_fragment.get(fragment.fragment_id)
                if (
                    has_rebar
                    and driver is not None
                    and (
                        mechanism.mechanism_family == "corrosion_spall"
                        or (first_condition is not None and first_condition.severity_index >= 0.30)
                    )
                ):
                    rebar_type = _sample_rebar_type(structural_role, rng)
                    fragment_domain = _domain_of_component_type(component_type, registries)
                    rebar_location = _sample_rebar_location(
                        fragment_domain, structural_role, rng
                    )
                    corrosion_severity = _compute_corrosion_severity(driver, cover_depth_mm, building.age_years)
                    loss_type = _sample_corrosion_loss_type(
                        driver.chloride_exposure_index,
                        driver.moisture_ingress_index,
                        corrosion_severity,
                        rng,
                    )
                    section_loss = _compute_rebar_section_loss_ratio_per_class(
                        rebar_type=rebar_type,
                        corrosion_severity_index=corrosion_severity,
                        chloride_exposure_index=driver.chloride_exposure_index,
                        moisture_ingress_index=driver.moisture_ingress_index,
                        cover_depth_mm=cover_depth_mm,
                        rng=rng,
                    )
                    explicit_value_num = round(float(section_loss), 4)
                    explicit_family = "technical_validation_measurement"
                    explicit_mode = "technical_validation_plan"
                    # 物理 metadata 写进 measurement.qualifiers（消费层可见物理上下文）
                    explicit_qualifiers = {
                        "rebar_type": rebar_type,
                        "rebar_location": rebar_location,
                        "corrosion_loss_type": loss_type,
                    }

            if explicit_value_num is None and explicit_value_bool is None:
                continue
            # SA-1 fix (2026-05-23)：defect_geometry_measurement 锚点必须是 condition_id
            # （spec 07 §C017_GEOMETRY_MEAS_FROM_CONDITION + spec 04 §16 target_ref
            # "fragment / component / condition id" + §17 crack/spall/rebar geometry slot
            # 来源列 "crack condition" / "spall condition"）。其他 family（technical_validation
            # / structural_assessment / coverage_sampling）锚 fragment_id 不变。
            # 4 个 defect_geometry slot（rebar_exposed_length_m / spall_area_m2 /
            # crack_width_mm / crack_length_m）的 derive 分支均在本 fragment 唯一 condition
            # （generator 当前 1:1 fragment↔condition）作用域内；first_condition 缺失时
            # 无法满足 C017，跳过该记录（不 emit C017-违规记录）。
            if explicit_family == "defect_geometry_measurement":
                if first_condition is None:
                    continue
                explicit_target_ref = first_condition.condition_id
            else:
                explicit_target_ref = fragment.fragment_id
            # DEBT-020 round5 sub-task 6: explicit_qualifiers 仅 ratio.rebar.section_loss 路径携带；
            # 其他 slot 显式无 qualifiers 时 None 保持空 dict default.
            qualifiers_payload = explicit_qualifiers if explicit_qualifiers else {}
            measurements.append(
                _build_measurement_record_with_value(
                    slot_record=slot_record,
                    target_ref=explicit_target_ref,
                    measurement_family=explicit_family,
                    derivation_mode=explicit_mode,
                    measurement_index=fragment_measurement_index,
                    value_num=explicit_value_num,
                    value_bool=explicit_value_bool,
                    qualifiers=qualifiers_payload,
                    method_class_override=explicit_method_class_override,  # DEBT-049 §2.1b
                )
            )
            emitted_formula_slot_ids.add(slot_id)
            fragment_measurement_index += 1

        chosen = list(slot_pool)
        rng.shuffle(chosen)
        generic_count = 0
        for slot_record in chosen:
            if slot_record.get("slot_id") in emitted_formula_slot_ids:
                continue
            family = slot_record.get("measurement_family")
            derivation_mode = (
                "damage_downstream" if family == "defect_geometry" else "assessment_plan"
            )
            measurements.append(
                _build_measurement_record_for_slot(
                    slot_record=slot_record,
                    target_ref=fragment.fragment_id,
                    measurement_family="structural_assessment_measurement",
                    derivation_mode=derivation_mode,
                    measurement_index=fragment_measurement_index,
                    rng=rng,
                )
            )
            fragment_measurement_index += 1
            generic_count += 1
            if generic_count >= per_fragment_count:
                break

        # ---------- DEBT-049 Phase3 U5 §2.1b: P3a(air)/P3b(ball) 专用观测 emit（active 路径）----------
        # **放在本 fragment 所有既有测量之后 append**——既有 formula/generic 测量的 measurement_index
        # 与 measurement_id 逐字节不变（air/ball 只做纯追加，不移位既有记录）。命中即 emit **恰 1 条**
        # 专用观测 record（发射逻辑见 `_emit_drainage_airball_observation`）。观测数值抖动走独立
        # domain-separated 子流——不消费 caller 的 rng（既有抽样序列零扰动）。既有 drainage index/flag
        # 测量在 air/ball 情形保 drainage_cctv 兜底不覆写（drainage_method_override 为 None）。
        # **inactive-mechanism 的命中 fragment 由本函数末尾补发循环覆盖**（active guard 上跳过，见下）。
        if selected_drainage_method in ("air_test", "ball_test") and drainage_for_method is not None:
            airball_record = _emit_drainage_airball_observation(
                fragment,
                drainage_for_method,
                technical_slot_index,
                selected_drainage_method,
                fragment_measurement_index,
            )
            if airball_record is not None:
                measurements.append(airball_record)
                fragment_measurement_index += 1

    # ---------- DEBT-049 Phase3 U5 §2.1b fix（codex 终审 019f7513）：inactive-mechanism 补发 ----------
    # 主循环开头 active guard(`if mechanism is None or not mechanism.active: continue`) + component
    # 缺失 guard 会跳过 inactive-mechanism / 缺 component 的 fragment，使其 air/ball 谓词命中却零发射
    # （终审复算 S2.5 四 seed：air 命中 62 实发 59 / ball 命中 31 实发 29，缺 5 全 inactive）。spec
    # §2.1b 冻结「P3a/P3b 命中 fragment 必须恰 1 条专用记录」，发射条件只看 DrainageState 物理场、
    # 与 mechanism.active 解耦——故此处补发主循环跳过的 fragment：谓词命中即 emit **恰 1 条**，
    # measurement_index=0（该 fragment 主循环零测量、专用记录为其首条且唯一，measurement_id 不撞）。
    # air/ball 走同一独立 domain-separated 子流（不消费 caller rng）→ 既有序列/记录逐字节不变、纯追加。
    # 主循环已处理的 fragment（active mechanism 且 component 就位）在此跳过、避免重复发射。
    for fragment in fragments:
        mechanism = mechanism_by_fragment.get(fragment.fragment_id)
        component = components_by_id.get(fragment.component_id)
        if mechanism is not None and mechanism.active and component is not None:
            continue  # 主循环已 emit（含 air/ball），不重复
        drainage_for_method = drainage_by_fragment.get(fragment.fragment_id)
        if drainage_for_method is None:
            continue
        selected_drainage_method = _select_drainage_method_class(drainage_for_method)
        if selected_drainage_method not in ("air_test", "ball_test"):
            continue
        airball_record = _emit_drainage_airball_observation(
            fragment,
            drainage_for_method,
            technical_slot_index,
            selected_drainage_method,
            measurement_index=0,
        )
        if airball_record is not None:
            measurements.append(airball_record)
    return measurements


# ---------- spec 06 §11 14 个 derived flag 派生 ----------
# （W1-010：实际派生 14 个 flag——spec 08 §1 共 9 行，其中 family_uncovered 属 W2 法规映射层不在
# W1 派生；spec 02 §2 派生顺序列 1-13 加 14 defect.cause_or_extent.uncertain，详见 spec 08 §1.）

# spec 06 §11 阈值常量 (derived flag 派生阈值)
# -------------------------------------------
# W1-006 follow-up（2026-05-22 复核）：原注释说"spec 未给数值/工程口径暂定"有误。逐个核对
# spec 06 §11 Derived flags 表 + spec 06 §1.1 Global configurable parameters 表 + spec 11
# inventory §5.1/§5.2 registry entry thresholds 后确认——下列 11 个常量里 8 个 spec 已明定
# 数值（只加 spec 出处注释，不改值）；2 个偏离 spec severity band（_REPAIR_SEVERITY_THRESHOLD /
# _MAINTENANCE_SEVERITY_UPPER）已按 spec 改值；_MAINTENANCE_SEVERITY_LOWER 改为 minor band 下界。
# 唯 _FSP_FLOOR_PROXY 无 spec 锚定数值（spec 06 §11 row 8 / W1 spec 08 §2 step 7 只给符号
# fsp_floor_proxy，spec 06 §10 仅给 fsp 公式不给 floor 值），暂留工程值并标 surface follow-up.

# spec 06 §11 row 1 risk_building_safety_emergency `severity>=0.85 or fsp<0.75 or
# structural_impact>=0.85`；与 spec 11 inventory §5.1 RISK_BUILDING_SAFETY_EMERGENCY_V1
# thresholds={severity:0.85, fsp:0.75, structural_impact:0.85} 一致.
_RISK_BUILDING_SAFETY_SEVERITY_THRESHOLD = 0.85
_RISK_BUILDING_SAFETY_FSP_THRESHOLD = 0.75
_RISK_BUILDING_SAFETY_STRUCTURAL_IMPACT_THRESHOLD = 0.85
# spec 06 §11 row 2 risk_public_health_emergency `>=0.80`；spec 11 inventory §5.1
# RISK_PUBLIC_HEALTH_DRAINAGE_V1 threshold={public_health_risk_index:0.80}.
_RISK_PUBLIC_HEALTH_THRESHOLD = 0.80
# spec 06 §11 row 3 risk_public_danger_present `max danger index >=0.70`；spec 11
# inventory §5.1 RISK_PUBLIC_DANGER_UBW_V1 threshold={max_danger_index:0.70}.
_RISK_PUBLIC_DANGER_THRESHOLD = 0.70
# spec 06 §11 row 4 repair_required 触发 `moderate+ condition`（spec 11 inventory §5.2
# RO_REPAIR_REQUIRED_V1 formula `moderate_or_above_condition or ...`）——"moderate 及以上"
# 即 severity_band moderate 起点；按 W2 spec 00 severity_band 表 moderate = severity>=0.33.
# W1-006 修订 2026-05-22：原值 0.40 偏离 band 边界，改用 spec 06 §1.1 severity_minor_max=0.33.
_REPAIR_SEVERITY_THRESHOLD = 0.33
# spec 06 §11 row 5 maintenance_pre_next_cycle_required 触发 `minor/moderate and not
# emergency`（spec 11 inventory §5.2 RO_PRE_NEXT_CYCLE_MAINTENANCE_V1 formula
# `severity in [minor,moderate] and not any_emergency_risk`）——窗口 = severity_band
# minor∪moderate。按 W2 spec 00 severity_band 表 minor = severity>0、moderate 上界 =
# severe 起点 severity_moderate_max=0.66（spec 06 §1.1）。W1-006 修订 2026-05-22：原
# 0.20/0.50 无 spec 锚定，LOWER 改 0.0（配下方 `<` 严格比较 = minor band 下界 severity>0），
# UPPER 改 spec 06 §1.1 severity_moderate_max=0.66.
_MAINTENANCE_SEVERITY_LOWER = 0.0
_MAINTENANCE_SEVERITY_UPPER = 0.66
# spec 06 §11 row 6 repair_outcome_safe_until_next_cycle `repair_quality>=0.65 and not
# verification_failed and risk<0.70`；spec 11 inventory §5.2 RO_SAFE_UNTIL_NEXT_CYCLE_V1
# formula `repair_quality>=0.65 and not failed and residual_risk<0.70`.
_REPAIR_QUALITY_THRESHOLD = 0.65
_REPAIR_RESIDUAL_RISK_THRESHOLD = 0.70
# spec 06 §11 row 8 assessment_fsp_below_required_safety `fsp < fsp_floor_proxy`——spec
# 仅给符号 fsp_floor_proxy，spec 06 §10 / §1.1 / spec 11 inventory 均未给 floor 数值。
# W1-006 surface follow-up 2026-05-22：0.95 是工程口径暂定值，待 spec 06 §10/§11 显式补
# fsp_floor_proxy 数值后回写。
_FSP_FLOOR_PROXY = 0.95
# W1-001 / DEBT-013 closure 2026-05-08：spec 08 §1 row 7 + §2 step 1 明定 0.35（已 spec 授权）.
_COVERAGE_FLOOR_PROXY = 0.35


def _fragment_id_from_domain_id(domain_id: str, prefix: str) -> str:
    """从 DRN-XYZ / UBW-XYZ / FSS-XYZ 恢复 FRG-XYZ（domain id 跟 fragment id 同 suffix）."""
    suffix = domain_id[len(prefix):] if domain_id.startswith(prefix) else domain_id
    return f"FRG-{suffix}"


def _build_per_fragment_state_lookup(world: WorldBundle) -> Dict[str, Dict[str, Any]]:
    """构建 per fragment 状态查询表（mechanism / drainage / ubw / fire / repair_assessment / measurements）."""
    lookup: Dict[str, Dict[str, Any]] = {}
    for fragment in world.fragments:
        lookup[fragment.fragment_id] = {
            "fragment": fragment,
            "mechanism": None,
            "drainage": None,
            "ubw": None,
            "fire": None,
            "repair_assessment": None,
            "measurements": [],
        }
    for mechanism in world.mechanisms:
        if mechanism.fragment_id in lookup:
            lookup[mechanism.fragment_id]["mechanism"] = mechanism
    for drainage in world.drainage_states:
        fid = _fragment_id_from_domain_id(drainage.drainage_id, "DRN-")
        if fid in lookup:
            lookup[fid]["drainage"] = drainage
    for ubw in world.ubw_states:
        fid = _fragment_id_from_domain_id(ubw.ubw_id, "UBW-")
        if fid in lookup:
            lookup[fid]["ubw"] = ubw
    for fire in world.fire_safety_states:
        fid = _fragment_id_from_domain_id(fire.fire_state_id, "FSS-")
        if fid in lookup:
            lookup[fid]["fire"] = fire
    for repair in world.repair_assessment_states:
        if repair.fragment_id in lookup:
            lookup[repair.fragment_id]["repair_assessment"] = repair
    for measurement in world.measurements:
        if measurement.target_ref in lookup:
            lookup[measurement.target_ref]["measurements"].append(measurement)
    return lookup


# 🔴 1b（波次二 #31）：spec 08 §2 step 7 明写 `assessment_fsp_below_required_safety`
#    的输入是 **W1 Step 8 输出的 `ratio.fsp.structural_performance`**（逐片段量测），
#    Step 8 已在 `:2129-2130` 逐片段算好并在 `:2173-2174` 落盘。派生层只负责**读**它，
#    不得自己重算——尤其不得拿全楼 max severity 重算一个楼级标量再发给每个构件
#    （守则 §4.3.3(c) 把结构表现系数定义在**結構構件**上，法规里不存在"全楼 FSP"）。
_FSP_MEASUREMENT_SLOT_ID = "ratio.fsp.structural_performance"


def _lookup_fragment_fsp_measurement(
    measurements: List[MeasurementRecord],
) -> Optional[float]:
    """取该片段自身的 Step 8 结构表现系数量测；无量测返回 None（⇒ no_assessment 路线）。

    入参是 `_build_per_fragment_state_lookup` 按 `measurement.target_ref == fragment_id`
    收好的**本片段**量测列表，故此处不再做作用域过滤。
    W1-003 的 not_applicable 占位记录（`value_enum == "not_applicable"`、`value_num` 空）
    不算"做过评估"，与 `verification.test.failed` 的 `valid_tv` 判据同口径。
    """
    for measurement in measurements:
        if (
            measurement.slot_id == _FSP_MEASUREMENT_SLOT_ID
            and measurement.value_num is not None
            and measurement.value_enum != "not_applicable"
        ):
            return float(measurement.value_num)
    return None


def _compute_max_danger_index(condition: ConditionState, drainage, ubw, fire) -> float:
    """spec 06 §11 max danger index = max over (detachment / spall / fire / ubw / drainage severity)."""
    candidates: List[float] = [condition.severity_index]
    if drainage is not None:
        candidates.append(max(drainage.blockage_index, drainage.leakage_index, drainage.public_health_risk_index))
    if ubw is not None:
        candidates.append(ubw.structural_impact_index)
    if fire is not None:
        candidates.append(fire.severity_index)
    return max(candidates) if candidates else 0.0


def _compute_derived_flags_for_condition(
    condition: ConditionState,
    fragment: FragmentContext,
    mechanism: Optional[MechanismState],
    drainage: Optional[DrainageState],
    ubw: Optional[UBWState],
    fire: Optional[FireSafetyState],
    repair_assessment: Optional[RepairAssessmentState],
    measurements: List[MeasurementRecord],
    building: BuildingContext,
    fsp_estimate: Optional[float],
) -> Dict[str, Dict[str, Any]]:
    """spec 06 §11 派生 14 个 derived flag (W1-010).

    🔴 作用域（1b / 波次二 #31，2026-08-05 三线门定案）：本函数**全部输入都是片段级**。
    `condition` / `drainage` / `ubw` / `fire` / `repair_assessment` / `measurements`
    由 `_build_per_fragment_state_lookup` 按 `fragment_id` 取；`fsp_estimate` 是
    **该片段自己**的 `ratio.fsp.structural_performance` 量测（无量测时为 None）。
    过去 `fsp_estimate` 是调用方拿全楼 max severity 重算的楼级标量——那是唯一一处
    跨片段输入，已在 1b 移除。**别再往这里塞任何楼级聚合量**：它会让"加一个片段"
    改掉既有构件的判定（非追加），并把最差处的事实张冠李戴到达标构件上。

    spec 08 §1 共 9 行 derived flag table，其中 family_uncovered 属 W2 法规映射层不在 W1 派生；
    spec 08 §2 派生顺序步骤 1-13 加 14 defect.cause_or_extent.uncertain 列出 14 条派生项.
    返回 5 个 sub-dict：risk_flags / repair_flags / verification_flags / assessment_flags /
    fallback_reasons. family_uncovered 不在此派生（projection executor 阶段判定）.

    DEBT-030 C 组 / spec 07 §4 line 68：每处 ``value if condition else "not_applicable"``
    同步登 fallback_reasons[flag_slot_id] = <reason_code>，reason code 按 spec 06 §11
    unknown_policy 列 verbatim：no_drainage / no_repair / no_test / no_assessment /
    no_private_premises / no_fire_component / no_scope_target.
    """
    # DEBT-030 C 组 audit trace：fallback_reasons 累积 per-flag not_applicable / unknown 原因.
    fallback_reasons: Dict[str, str] = {}
    severity = condition.severity_index
    structural_impact = ubw.structural_impact_index if ubw is not None else 0.0
    drainage_health = drainage.public_health_risk_index if drainage is not None else 0.0
    max_danger = _compute_max_danger_index(condition, drainage, ubw, fire)

    # 1b：`fsp_estimate` 为 None ＝ 本片段**没做过结构评估**（无 Step 8 量测）。
    # row 8 走 not_applicable + no_assessment（见下）；row 1 的 `fsp < 0.75` 分项则按
    # spec §10 的 fsp_true 初值 1.20 取值 ⇒ 该析取项恒不触发——"没评估过"不得被当成
    # "评估过且不合格"（这正是 1b 要根除的那类伪装）。
    fsp = fsp_estimate if fsp_estimate is not None else 1.20  # spec §10 default fsp_true initial
    repair_quality = (
        repair_assessment.repair_quality_index
        if repair_assessment is not None and repair_assessment.repair_quality_index is not None
        else 0.0
    )
    residual_risk = (
        repair_assessment.residual_risk_index
        if repair_assessment is not None and repair_assessment.residual_risk_index is not None
        else 0.0
    )
    repair_required_input = (
        repair_assessment.repair_required if repair_assessment is not None else False
    )
    verification_failed_input = (
        repair_assessment.verification_failed if repair_assessment is not None else False
    )

    # spec §11 row 1: risk_building_safety_emergency
    # 🔴 1b：本行的 `fsp` 与 row 8 同源，故也随之从楼级改成片段级（官方线令同批改，
    #    否则同一个 fsp 在同一个函数里同时有两个作用域）。
    risk_building_safety_emergency = (
        severity >= _RISK_BUILDING_SAFETY_SEVERITY_THRESHOLD
        or fsp < _RISK_BUILDING_SAFETY_FSP_THRESHOLD
        or structural_impact >= _RISK_BUILDING_SAFETY_STRUCTURAL_IMPACT_THRESHOLD
    )

    # spec §11 row 2: risk_public_health_emergency (drainage-only)
    if drainage is not None:
        risk_public_health_emergency: Any = drainage_health >= _RISK_PUBLIC_HEALTH_THRESHOLD
    else:
        risk_public_health_emergency = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no drainage -> not_applicable"
        fallback_reasons["risk.public_health.emergency"] = "no_drainage"

    # spec §11 row 3: risk_public_danger_present
    risk_public_danger_present = max_danger >= _RISK_PUBLIC_DANGER_THRESHOLD

    # spec §11 row 4: repair_required (severity moderate+ or risk true or verification failed)
    repair_required = (
        severity >= _REPAIR_SEVERITY_THRESHOLD
        or risk_building_safety_emergency
        or (isinstance(risk_public_health_emergency, bool) and risk_public_health_emergency)
        or risk_public_danger_present
        or verification_failed_input
        or repair_required_input
    )

    # spec §11 row 5: maintenance_pre_next_cycle_required
    # 窗口 = severity_band minor∪moderate（W2 spec 00 severity_band 表）：minor 是 severity>0
    # 严格下界（band none = severity==0 排除），moderate 上界 = severe 起点 0.66 严格上界.
    maintenance_pre_next_cycle_required = (
        _MAINTENANCE_SEVERITY_LOWER < severity < _MAINTENANCE_SEVERITY_UPPER
        and not risk_building_safety_emergency
    )

    # spec §11 row 6: repair_outcome_safe_until_next_cycle
    if repair_assessment is not None and repair_required_input:
        repair_outcome_safe_until_next_cycle: Any = (
            repair_quality >= _REPAIR_QUALITY_THRESHOLD
            and not verification_failed_input
            and residual_risk < _REPAIR_RESIDUAL_RISK_THRESHOLD
        )
    else:
        repair_outcome_safe_until_next_cycle = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no repair -> not_applicable"
        fallback_reasons["repair.outcome.safe_until_next_cycle"] = "no_repair"

    # W1-005 / spec 08 §2 step 6 verification_test_failed 派生入口切到 measurement+failure_rule.
    # 当前实现 cover spec 06 §9 pull_test failure_rule (见 `_compute_verification_failed`):
    #   strength.pull_test.reported < stress.pull_test.minimum or repair_quality_index < 0.45
    # 优先级：
    #   (1) 有 technical_validation_measurement 且包含 strength.pull_test.reported +
    #       stress.pull_test.minimum slot 真值 → 套用 _compute_verification_failed
    #   (2) 仅有 technical_validation_measurement 但 measurement 全部 value_enum="not_applicable"
    #       (W1-003 silent skip fallback emit 的占位 record) → "not_applicable" + no_test
    #   (3) 有 technical_validation_measurement 但无 pull_test slot → fallback 到 RAS bootstrap 输入,
    #       并标 fallback_reason 提示其他 failure_rule family 解析待补
    #   (4) 全无 technical_validation_measurement → "not_applicable" + no_test
    tv_measurements = [m for m in measurements if m.measurement_family == "technical_validation_measurement"]
    # 区分有效 measurement vs W1-003 not_applicable 占位
    valid_tv = [m for m in tv_measurements if m.value_enum != "not_applicable"]
    if not tv_measurements:
        verification_test_failed: Any = "not_applicable"
        fallback_reasons["verification.test.failed"] = "no_test"
    elif not valid_tv:
        verification_test_failed = "not_applicable"
        fallback_reasons["verification.test.failed"] = "no_test"
    else:
        pull_reported = next(
            (m.value_num for m in valid_tv if m.slot_id == "strength.pull_test.reported" and m.value_num is not None),
            None,
        )
        pull_required = next(
            (m.value_num for m in valid_tv if m.slot_id == "stress.pull_test.minimum" and m.value_num is not None),
            None,
        )
        if pull_reported is not None and pull_required is not None:
            repair_quality_for_rule = repair_quality if repair_quality is not None else 0.0
            verification_test_failed = _compute_verification_failed(
                test_strength_reported=float(pull_reported),
                required_strength_proxy=float(pull_required),
                repair_quality_index=float(repair_quality_for_rule),
            )
        else:
            # W1-005 follow-up：其他 failure_rule family (visual / hammer_tapping / drainage CCTV
            # 等) 公式解析待补；暂回退到 RAS bootstrap 输入作 best-effort.
            # 注：未写 fallback_reasons (那只标 not_applicable 路径)，本路径仍输出 bool.
            verification_test_failed = verification_failed_input

    # spec §11 row 8: assessment_fsp_below_required_safety
    # 🔴 1b：`fsp_estimate is None` 这条分支在 1b 之前是**死分支**（三池 862 个 condition
    #    里 0 条触发）——因为调用方总能算出一个楼级 max，哪怕本片段根本没做结构评估。
    #    改读片段量测后它第一次真正生效。
    if fsp_estimate is not None:
        assessment_fsp_below_required_safety: Any = fsp < _FSP_FLOOR_PROXY
    else:
        assessment_fsp_below_required_safety = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no assessment -> not_applicable"
        fallback_reasons["assessment.fsp.below_required_safety"] = "no_assessment"

    # spec §11 row 9: drainage_misconnection_present
    if drainage is not None:
        drainage_misconnection_present: Any = drainage.misconnection_present
    else:
        drainage_misconnection_present = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no drainage -> not_applicable"
        fallback_reasons["drainage.misconnection.present"] = "no_drainage"

    # spec §11 row 10: ubw_present
    ubw_present = (
        ubw is not None
        and ubw.alteration_type != "none"
        and ubw.authorization_status_proxy == "unauthorized_like"
    )

    # spec §11 row 11: subdivided_unit_sign_present
    if ubw is not None:
        subdivided_unit_sign_present: Any = ubw.subdivided_unit_sign_present
    else:
        subdivided_unit_sign_present = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no private premises -> not_applicable"
        fallback_reasons["subdivided_unit_sign.present"] = "no_private_premises"

    # spec §11 row 12: fire_safety_deficiency_present
    if fire is not None:
        fire_safety_deficiency_present: Any = fire.deficiency_present
    else:
        fire_safety_deficiency_present = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no fire component -> not_applicable"
        fallback_reasons["fire_safety.deficiency.present"] = "no_fire_component"

    # spec §11 row 13: coverage_insufficient
    coverage_ratios = [
        m.value_num for m in measurements
        if m.measurement_family == "coverage_sampling_measurement" and m.value_num is not None
    ]
    if coverage_ratios:
        coverage_insufficient: Any = any(r < _COVERAGE_FLOOR_PROXY for r in coverage_ratios)
    else:
        coverage_insufficient = "not_applicable"
        # DEBT-030 C 组：spec 06 §11 unknown_policy "no scope target -> not_applicable"
        fallback_reasons["coverage.insufficient"] = "no_scope_target"

    # spec §11 row 14: defect_cause_or_extent_uncertain
    defect_cause_or_extent_uncertain = condition.uncertainty_flag

    # 分类到 4 个 derived_outcomes 字段 + fallback_reasons (DEBT-030 C 组)
    return {
        "risk_flags": {
            "risk.building_safety.emergency": risk_building_safety_emergency,
            "risk.public_health.emergency": risk_public_health_emergency,
            "risk.public_danger.present": risk_public_danger_present,
            "drainage.misconnection.present": drainage_misconnection_present,
            "ubw.present": ubw_present,
            "subdivided_unit_sign.present": subdivided_unit_sign_present,
            "fire_safety.deficiency.present": fire_safety_deficiency_present,
            "coverage.insufficient": coverage_insufficient,
        },
        "repair_flags": {
            "repair.required": repair_required,
            "maintenance.pre_next_cycle.required": maintenance_pre_next_cycle_required,
            "repair.outcome.safe_until_next_cycle": repair_outcome_safe_until_next_cycle,
        },
        "verification_flags": {
            "verification.test.failed": verification_test_failed,
        },
        "assessment_flags": {
            "assessment.fsp.below_required_safety": assessment_fsp_below_required_safety,
            "defect.cause_or_extent.uncertain": defect_cause_or_extent_uncertain,
        },
        # DEBT-030 C 组 / spec 06 §11 unknown_policy 列 verbatim：per-flag fallback 原因码
        "fallback_reasons": fallback_reasons,
    }


def populate_derived_flags(world: WorldBundle) -> WorldBundle:
    """spec 06 §11 派生 14 个 flag 填充到每个 condition 的 derived_outcomes（pure function；W1-010）.

    返回新 WorldBundle（不动 input）。每个 ConditionState 的 derived_outcomes 4 个 dict 字段被填入；
    W1-002 同时在本函数内回写 RAS 4 个 bool 字段 (Step 9 真值权威)；W1-004 在本函数末填顶层
    WorldBundle.derived_outcomes (A 类 6 个综合派生 flag 汇总).
    """
    if not world.conditions:
        return world

    state_lookup = _build_per_fragment_state_lookup(world)

    # 🔴 1b（波次二 #31，2026-08-05 三线门全票定案）：此处**不再自算 fsp**。
    #    旧实现是：
    #        age_norm_value = _age_norm(world.building.age_years)
    #        max_severity = max((c.severity_index for c in world.conditions), default=0.0)
    #        fsp_estimate = clip(1.20 - 0.30*max_severity - 0.10*age_norm_value)
    #    ——拿**全楼** max severity 重算一个楼级标量，再发给**每一个** condition。
    #    三条判据判定它是实现偏离而非语义选项：
    #      ① 守则 §4.3.3(a)(c)/§4.3.4 三处连写「結構構件」，FSP 是构件级的抗力/荷载比值，
    #         法规里不存在"全楼 FSP"；把最差构件的比值复制给达标构件，据此签发
    #         「緊急補救工程＋立即向建築事務監督報告」，是错误的事实陈述而非保守估计。
    #      ② spec 08 §2 step 7 / §1 表明写输入 = W1 Step 8 的 `ratio.fsp.structural_performance`。
    #      ③ 那个正确的值 **Step 8 已逐片段算好并落盘**（`:2129-2130` → `:2173-2174`），
    #         本改动零新公式、零新系数、零新注册表，只是让派生层去读它本该读的值。
    #    副产品：片段级 fsp 只依赖本片段 condition＋楼龄，故"加一个片段"不再改动既有
    #    片段的 fsp 派生族（#31 那条非追加通道随之消失）。因果方向别写反——不是为了
    #    让验收变绿才改语义，是改回正确作用域之后非追加性作为副产品消失。
    new_world = world.model_copy(deep=True)
    # W1-002: RAS 双轨消除——Step 9 派生公式为最终权威，Step 1 bootstrap 仅占位.
    # 用 fragment_id → RAS 索引，便于派生后回写 4 个字段 (repair_required / verification_failed
    # / maintenance_required / safe_until_next_cycle)；spec 03 §3 line 87 / spec 04 §9 contract.
    ras_by_fragment: Dict[str, RepairAssessmentState] = {
        ras.fragment_id: ras for ras in new_world.repair_assessment_states
    }
    for index, condition in enumerate(new_world.conditions):
        ctx = state_lookup.get(condition.fragment_id, {})
        # 1b：该片段自身的 Step 8 量测；无量测 → None → row 8 落 not_applicable + no_assessment
        fragment_fsp = _lookup_fragment_fsp_measurement(ctx.get("measurements", []))
        flags = _compute_derived_flags_for_condition(
            condition=condition,
            fragment=ctx.get("fragment"),
            mechanism=ctx.get("mechanism"),
            drainage=ctx.get("drainage"),
            ubw=ctx.get("ubw"),
            fire=ctx.get("fire"),
            repair_assessment=ctx.get("repair_assessment"),
            measurements=ctx.get("measurements", []),
            building=new_world.building,
            fsp_estimate=fragment_fsp,
        )
        condition.derived_outcomes.risk_flags.update(flags["risk_flags"])
        condition.derived_outcomes.repair_flags.update(flags["repair_flags"])
        condition.derived_outcomes.verification_flags.update(flags["verification_flags"])
        condition.derived_outcomes.assessment_flags.update(flags["assessment_flags"])
        # DEBT-030 C 组：spec 06 §11 unknown_policy fallback 原因码填入 audit 通道
        condition.derived_outcomes.fallback_reasons.update(flags.get("fallback_reasons", {}))
        # 同步 risk_index_values（continuous，spec §11 一些 flag 派生过程中可记录）
        condition.derived_outcomes.risk_index_values["index.public_danger"] = round(
            _compute_max_danger_index(condition, ctx.get("drainage"), ctx.get("ubw"), ctx.get("fire")),
            4,
        )
        # 🔴 1b：`index.fsp.estimate` 写**该片段自己**的量测值。无量测时**不写这个键**
        #    ——`risk_index_values` 是 Dict[str, float]，写不下 "not_applicable"；而写一个
        #    编造的默认值等于在数值通道里重犯"把没评估过伪装成评估过"。键缺席 ＝ 没评估过，
        #    与同一 condition 上的 `fallback_reasons["assessment.fsp.below_required_safety"]
        #    == "no_assessment"` 互为佐证。
        #    ⚠️ 无量测时**显式 pop**：本函数其余字段都走 `.update()`（键恒被写、旧值必被盖），
        #    只有这一个键是有条件写的。不 pop 的话，在一个已填过 derived_outcomes 的世界上
        #    重跑（本函数是纯函数、契约上允许重跑）会留下上一轮的陈值，输出就不再只由输入决定。
        #    生产主链只调一次、字典是空的，故这一行零行为差异——它守的是重跑语义。
        if fragment_fsp is not None:
            condition.derived_outcomes.risk_index_values["index.fsp.estimate"] = round(fragment_fsp, 4)
        else:
            condition.derived_outcomes.risk_index_values.pop("index.fsp.estimate", None)

        # W1-002: Step 9 真实公式回写到 RAS 同名字段；bool 化 not_applicable→False（RAS 字段 schema 不
        # 支持 enum 值，按 spec 8 §2 step 11/12/13 unknown_policy "no scope → not_applicable" 仅作
        # derived flag 表达，RAS bool 字段保持 False 语义 = "未触发"）.
        ras = ras_by_fragment.get(condition.fragment_id)
        if ras is not None:
            repair_required_val = flags["repair_flags"].get("repair.required")
            maintenance_val = flags["repair_flags"].get("maintenance.pre_next_cycle.required")
            safe_val = flags["repair_flags"].get("repair.outcome.safe_until_next_cycle")
            verification_val = flags["verification_flags"].get("verification.test.failed")
            ras.repair_required = bool(repair_required_val) if isinstance(repair_required_val, bool) else False
            ras.maintenance_required = bool(maintenance_val) if isinstance(maintenance_val, bool) else False
            # safe_until_next_cycle 是 Optional[bool]：not_applicable 时落 None 而不是 False，保字段语义
            ras.safe_until_next_cycle = safe_val if isinstance(safe_val, bool) else None
            ras.verification_failed = bool(verification_val) if isinstance(verification_val, bool) else False

    # W1-004 / spec 08 §5 + §3.A：A 类综合派生类 6 个 flag 汇总到顶层 WorldBundle.derived_outcomes.
    # 多 condition 汇总语义：取 OR（任一 condition 触发即 True，全 not_applicable 则 not_applicable）;
    # B 类 8 个业务直通类 flag 数据 spec 8 §3.B 明定从对应 State 字段消费，不在 derived_outcomes 重派.
    a_class_flag_paths = {
        "risk.building_safety.emergency": ("risk_flags", "risk.building_safety.emergency"),
        "risk.public_health.emergency": ("risk_flags", "risk.public_health.emergency"),
        "risk.public_danger.present": ("risk_flags", "risk.public_danger.present"),
        "repair.required": ("repair_flags", "repair.required"),
        "repair.outcome.safe_until_next_cycle": ("repair_flags", "repair.outcome.safe_until_next_cycle"),
        "maintenance.pre_next_cycle.required": ("repair_flags", "maintenance.pre_next_cycle.required"),
    }
    aggregated: Dict[str, Any] = {}
    for flag_id, (bucket, key) in a_class_flag_paths.items():
        any_true = False
        any_bool = False
        for condition in new_world.conditions:
            container = getattr(condition.derived_outcomes, bucket, {})
            val = container.get(key)
            if isinstance(val, bool):
                any_bool = True
                if val:
                    any_true = True
                    break
        if any_true:
            aggregated[flag_id] = True
        elif any_bool:
            aggregated[flag_id] = False
        else:
            aggregated[flag_id] = "not_applicable"
    new_world.derived_outcomes = aggregated
    return new_world


# ---------- T-17a + T-17b + T-17c entry ----------


def generate_world_bundle(
    batch_config: Dict[str, Any],
    registries: RegistryBundle,
    seed: int = DEFAULT_BATCH_RANDOM_SEED,
    building_index: int = 0,
    fragment_count: int = 4,
) -> WorldBundle:
    """T-17a + T-17b + T-17c entry: generate full WorldBundle (shell + states + measurements).

    Pure function (T-17.6): no side effects on inputs, deterministic given (batch_config, seed,
    building_index, fragment_count, registries hash).

    W1-007 follow-up：spec 02 §1 入口图描述的概念 signature 为
    ``generate_world_bundle(archetype_id, seed, config, registries) → WorldBundle``，
    code 当前是 batch-level entry (内部 sample archetype, 含 building_index / fragment_count 实施
    参数)；sidecar 派生由 ``validation.py`` 主入口外层并行调 (`_build_sidecar_runtime_bundle_
    for_buildings`)，没在本函数内.
    保持 code 现有 batch 入口不动 (兼容现网调用)；如未来要暴露 spec 描述的 per-instance
    `(archetype_id, seed, config, registries) → (WorldBundle, SidecarRuntimeBundle)` 入口，作为新
    function 加上，不破坏本签名.

    spec 04 §3 alignment：
    - building (BuildingContext) ✓
    - components (1..N) ✓
    - locations (1..N) ✓
    - fragments (1..N) ✓ (T-17b)
    - drivers / mechanisms / conditions ✓ (T-17b, 1 per fragment)
    - drainage_states / ubw_states / fire_safety_states ✓ (T-17b, 选择性按 mechanism family)
    - repair_assessment_states ✓ (T-17b, 1 per fragment, placeholder severity)
    - coverage_relations ✓ (T-17b, 1 per fragment via coverage_relation_registry)
    - measurements ✓ (T-17c, 3 family: coverage_sampling / technical_validation / structural_assessment)

    **P2 audit context — caller 责任 (W1 spec 07 §4 line 70-75)**:
        本函数 **不自动 wrap** ``audit_capture()`` context manager. 如 caller 需要 P2 修复 audit
        trace（aggregate summary + bounded sample，按 spec 07 §4 line 70），**必须自己显式 wrap**::

            from workflow_engine.worldgen.p2_audit import audit_capture
            with audit_capture() as acc:
                bundle = generate_world_bundle(...)
            # acc.summaries: Dict[check_id, P2ClampSummary]

        不 wrap **不会 raise** — P2 inline clip 会 silently 跳过 record（``_get_p2_audit_accumulator``
        ctxvar 返回 None → fast path 跳过）。这是 spec 边界设计选择（spec 07 §4 line 75：
        "由 docstring warning 提示，不 raise"）.

        ``generate_world_batch_with_stats`` 已自动 wrap audit_capture，**通过该入口的 caller 无需关心**;
        单独调用 ``generate_world_bundle`` / 任何绕过 batch 入口的路径（如 test fixture 直接构造、
        debug 入口、子流程）请按需 wrap.
    """
    # Deterministic per (seed, building_index) — combine into hashable string seed
    rng = random.Random(f"{seed}-{building_index}")
    template_id = sample_archetype(batch_config or {}, registries, rng)
    building, building_metadata = build_building_context(template_id, building_index, registries, rng)
    plan = _archetype_component_plan(template_id)
    components = build_components(building, template_id, registries, rng)
    locations = build_locations(components, registries, rng, plan=plan)
    suffix = _sanitize_id_component(template_id.replace("BT_", "").replace("_V1", ""))
    world_id = f"WB-{suffix}-{building_index:04d}-S{seed % 100000:05d}"

    # W0-005 (2026-05-21)：generator pipeline 全切到 spec 04 §7 FragmentContext 9 字段
    # reference-based contract——`component_id` / `location_id` 主键反查通过 components_by_id /
    # locations_by_id O(1) lookup 避免反复扫描列表.
    components_by_id: Dict[str, ComponentNode] = {c.component_id: c for c in components}
    locations_by_id: Dict[str, LocationNode] = {loc.location_id: loc for loc in locations}

    # T-17b: per-fragment 状态生成
    fragment_templates = _select_fragment_templates(
        building, template_id, registries, world_id=world_id, target_count=fragment_count,
        available_component_types={c.component_type for c in components},
        # 缺省 False；开它须配新池名（会改随机流）。见 `_select_fragment_templates` 长注释。
        ensure_component_type_coverage=bool(
            (batch_config or {}).get("ensure_component_type_coverage", False)),
    )
    fragments: List[FragmentContext] = []
    drivers: List[DriverState] = []
    mechanisms: List[MechanismState] = []
    conditions: List[ConditionState] = []
    drainage_states: List[DrainageState] = []
    drainage_by_fragment_id: Dict[str, DrainageState] = {}  # DEBT-020 round2 #3: 给 measurement 派生层用
    ubw_states: List[UBWState] = []
    fire_safety_states: List[FireSafetyState] = []
    repair_assessment_states: List[RepairAssessmentState] = []
    for fragment_index, template in enumerate(fragment_templates):
        component = _pick_component_for_fragment(template, components, rng)
        if component is None:
            continue
        location = _location_for_component(component, locations)
        fragment = generate_fragment(component, template, fragment_index, rng)
        driver = generate_driver(fragment, building, rng, template)  # DEBT-049 §2.1 S2.5 防死档：drainage 域 alteration 标定
        mechanism = generate_mechanism(fragment, template, driver, rng, building.age_years)
        condition = generate_condition(
            fragment, component, mechanism, driver, rng, building.age_years, registries
        )
        # spec 草案·第一波 §2：闭世界负例——per-fragment 可达而未出现的缺陷类。
        _reachable = _fragment_reachable_condition_classes(
            template.get("allowed_mechanisms") or [], component.component_type, registries
        )
        _present = set(condition.condition_classes or []) | {condition.condition_class}
        condition.generatable_absent_classes = sorted(_reachable - _present)
        # spec 草案·DEBT-049 第三波 件A（闭世界总声明）：全集缺席 = 分类注册表
        # 全集 − 实际类（W0 按构造完备，未生成即不存在）；可达集字段保留供
        # ClassReachabilityAudit 三态区分（generated/可达未生成/不可达）。
        condition.absent_condition_classes = sorted(
            _all_taxonomy_condition_classes(registries) - _present
        )
        repair_state = generate_repair_assessment_state(fragment, condition, driver, rng)
        fragments.append(fragment)
        drivers.append(driver)
        mechanisms.append(mechanism)
        conditions.append(condition)
        repair_assessment_states.append(repair_state)
        drainage = generate_drainage_state(fragment, mechanism, component, driver, rng, building.age_years)
        if drainage is not None:
            drainage_states.append(drainage)
            drainage_by_fragment_id[fragment.fragment_id] = drainage
        ubw = generate_ubw_state(fragment, mechanism, component, location, driver, rng)
        if ubw is not None:
            ubw_states.append(ubw)
        fire = generate_fire_safety_state(
            fragment, mechanism, component, driver, rng, registries
        )
        if fire is not None:
            fire_safety_states.append(fire)
    # 🔴 1a-i（波次二 #22，2026-08-05）：以下四个后置阶段**不再收主 rng**，
    # 各自按 `(域串, world_id, fragment_id)` 逐片段派生子流。
    # 病因：这四段过去在主 rng 上顺序穿线，于是「某栋楼多一个片段」会让其后所有
    # 既有片段的量测全部移位（实测甲-a：保留 200/200 键却翻判 78）——
    # 加片段不是纯追加，任何「加了什么就量什么」的对照都不成立。
    coverage_relations = generate_coverage_relations(
        building, components, fragments, components_by_id, registries, world_id=world_id
    )

    # T-17c (T-19 并入): measurement 3 family 生成
    measurements: List[MeasurementRecord] = []
    measurements.extend(
        generate_coverage_sampling_measurements(
            building, components, fragments, registries, world_id=world_id
        )
    )
    measurements.extend(
        generate_technical_validation_measurements(
            building, fragments, conditions, registries, world_id=world_id
        )
    )
    drivers_by_fragment_id: Dict[str, DriverState] = {
        fragment.fragment_id: drivers[idx]
        for idx, fragment in enumerate(fragments)
        if idx < len(drivers)
    }
    measurements.extend(
        generate_structural_assessment_measurements(
            building, fragments, conditions, mechanisms, components_by_id, registries,
            world_id=world_id,
            drainage_by_fragment=drainage_by_fragment_id,  # DEBT-020 round2 #3: public_health_risk_index 走 derive 路径
            drivers_by_fragment=drivers_by_fragment_id,  # DEBT-020 round5 sub-task 1: crack_width/length derive 用
        )
    )

    world = WorldBundle(
        schema_version="worldgen.fullcoverage.world.v1",
        world_id=world_id,
        generator_version=GENERATOR_VERSION,
        random_seed=seed,
        building=building,
        building_metadata=building_metadata,
        fragments=fragments,
        components=components,
        locations=locations,
        coverage_relations=coverage_relations,
        drivers=drivers,
        mechanisms=mechanisms,
        conditions=conditions,
        drainage_states=drainage_states,
        ubw_states=ubw_states,
        fire_safety_states=fire_safety_states,
        repair_assessment_states=repair_assessment_states,
        measurements=measurements,
    )

    # spec 06 §11 派生 14 个 derived flag 填充到 condition.derived_outcomes (W1-010 注释修正)
    world = populate_derived_flags(world)

    return world


# ---------- T-17d: batch 入口 ----------


def write_progress_file(
    progress_file: str,
    seed: int,
    completed: int,
    total: int,
    started_at: float,
    phase: str = "generating",
) -> None:
    """atomic write progress JSON (write to .tmp + rename 防部分写).

    phase: "generating" (Step 2 building 主循环) / "finalizing"
    (Step 3-7 sidecar+projection+parquet)。前者占大头，后者数秒级.
    """
    import json as _json
    from datetime import datetime as _dt
    elapsed = time.time() - started_at
    rate = (completed / elapsed * 60.0) if elapsed > 0 else 0.0
    remaining = max(0, total - completed)
    eta = (remaining / rate * 60.0) if rate > 0 else 0.0
    payload = {
        "seed": seed,
        "completed": completed,
        "total": total,
        "phase": phase,
        "started_at": _dt.fromtimestamp(started_at).isoformat(timespec="seconds"),
        "elapsed_s": round(elapsed, 1),
        "rate_per_min": round(rate, 1),
        "eta_s": round(eta, 1),
        "timestamp": _dt.now().isoformat(timespec="seconds"),
    }
    p = Path(progress_file)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def generate_world_batch(
    batch_config: Dict[str, Any],
    registries: RegistryBundle,
    count: int,
    seed: int = DEFAULT_BATCH_RANDOM_SEED,
    fragment_count_per_building: int = 4,
    apply_gate: bool = False,
    max_retries: int = 3,
    building_workers: int = 1,
    progress_file: Optional[str] = None,
    progress_interval: int = 50,
) -> List[WorldBundle]:
    """T-17d entry: generate a batch of `count` WorldBundle instances (spec 04 §3 building-centric).

    Pure function (T-17.6): deterministic given (batch_config, count, seed, registries hash).

    Each WorldBundle 由 generate_world_bundle(building_index=i) 产生（i ∈ [0, count)），
    archetype 按 batch_config['archetype_distribution'] 抽样。

    T-21 gate (apply_gate=True)：每栋调 apply_gate_with_retry，P0 violation 触发整 building
    resample（T-21.2，外层 retry budget=max_retries）；P1 violation 触发 repair（T-21.3 pure
    function）；P2 violation 仅 warning 不阻塞。reject 的 building 不进 batch（统计调
    generate_world_batch_with_stats 获取 BatchGateStats）。

    QA-Parallelize 2026-05-09 (`building_workers`)：
        - 1 (默认): 串行 list comprehension（兼容旧行为）
        - >=2: ProcessPoolExecutor 跨 building 并行；每 building deterministic seed
          `f"{seed}-{building_index}"` 不变；registries 通过 initializer 一次性传入 worker globals.
        - apply_gate=True 路径暂不并行（gate retry 复杂；后续单独并行化）.

    T-17 全段已完成。剩余 T-22 工单实施 spec 07 §2 C001-C026 各级 check 函数。
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    progress_started_at = time.time()

    if not apply_gate:
        # P2 audit: 本入口 **不 wrap** audit_capture — 仅返回 WorldBundle list, 无 BatchGateStats
        # 接收点 (spec 07 §4 line 75 边界: caller 不收 stats 即无需 P2 trace).
        # 若需 P2 audit 请改用 generate_world_batch_with_stats (该函数已自动 wrap).
        if building_workers <= 1:
            out: List[WorldBundle] = []
            for index in range(count):
                out.append(
                    generate_world_bundle(
                        batch_config=batch_config,
                        registries=registries,
                        seed=seed,
                        building_index=index,
                        fragment_count=fragment_count_per_building,
                    )
                )
                # progress hook: 每 progress_interval building 或最后一栋写 progress JSON
                if progress_file and (
                    (index + 1) % progress_interval == 0 or (index + 1) == count
                ):
                    write_progress_file(
                        progress_file, seed, index + 1, count, progress_started_at
                    )
            # Step 2 主循环完成 — 标 finalizing phase 给 monitor。caller orchestrator
            # (validation.py Step 3-7 + execute_projection_batch_v2) 跑后续期间显示 FINALIZING.
            if progress_file:
                write_progress_file(
                    progress_file, seed, count, count, progress_started_at, phase="finalizing"
                )
            return out
        # 跨 building 并行
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(
            max_workers=building_workers,
            initializer=_building_worker_init,
            initargs=(batch_config, registries, seed, fragment_count_per_building),
        ) as ex:
            results: List[WorldBundle] = []
            chunksize = max(1, count // (building_workers * 8))
            for i, wb in enumerate(
                ex.map(_building_worker_task, range(count), chunksize=chunksize)
            ):
                results.append(wb)
                if progress_file and (
                    (i + 1) % progress_interval == 0 or (i + 1) == count
                ):
                    write_progress_file(
                        progress_file, seed, i + 1, count, progress_started_at
                    )
            if progress_file:
                write_progress_file(
                    progress_file, seed, count, count, progress_started_at, phase="finalizing"
                )
            return results

    # T-21 gated path
    # P2 audit: gated path 同样 **不 wrap** audit_capture — caller 接 List[WorldBundle], 无 stats
    # 出口。需 P2 trace 用 generate_world_batch_with_stats（spec 07 §4 line 75 边界）.
    from workflow_engine.worldgen.gates import apply_gate_with_retry

    accepted: List[WorldBundle] = []
    for index in range(count):
        def _gen(retry_idx: int, _index: int = index) -> WorldBundle:
            # Same building_index baseline; perturb seed for retry to ensure resample diversity
            return generate_world_bundle(
                batch_config=batch_config,
                registries=registries,
                seed=seed + retry_idx * 100003,  # T-21.2: 整 building resample (different seed branch)
                building_index=_index,
                fragment_count=fragment_count_per_building,
            )

        passed_wb, _result = apply_gate_with_retry(
            generator_fn=_gen,
            registries=registries,
            max_retries=max_retries,
        )
        if passed_wb is not None:
            accepted.append(passed_wb)
    return accepted


def generate_world_batch_with_stats(
    batch_config: Dict[str, Any],
    registries: RegistryBundle,
    count: int,
    seed: int = DEFAULT_BATCH_RANDOM_SEED,
    fragment_count_per_building: int = 4,
    max_retries: int = 3,
) -> Tuple[List[WorldBundle], "BatchGateStats"]:
    """T-21.6: generate batch with gate + return BatchGateStats（spec 07 健康度指标）.

    每栋 building 走 apply_gate_with_retry：通过则 accepted；不通过则 record reject_reason。
    与 generate_world_batch(apply_gate=True) 唯一区别：本函数返回统计对象。

    DEBT-030 C 组 / spec 07 §4 line 70: per-build audit_capture context 收 P2 inline clamp
    aggregate summary → batch_stats.p2_clamp_summaries 合并（per check_id count + max/mean
    magnitude + 前 K=20 sample detail）.
    """
    from workflow_engine.worldgen.gates import (
        BatchGateStats,
        apply_gate_with_retry,
    )

    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    accepted: List[WorldBundle] = []
    stats = BatchGateStats()
    for index in range(count):
        def _gen(retry_idx: int, _index: int = index) -> WorldBundle:
            return generate_world_bundle(
                batch_config=batch_config,
                registries=registries,
                seed=seed + retry_idx * 100003,
                building_index=_index,
                fragment_count=fragment_count_per_building,
            )

        # DEBT-030 C 组：per-build audit_capture context — generate 阶段所有 P2 inline clamp
        # 写入此 accumulator；exit 后 merge 进 batch stats.
        with audit_capture() as build_accumulator:
            passed_wb, result = apply_gate_with_retry(
                generator_fn=_gen,
                registries=registries,
                max_retries=max_retries,
            )
        if passed_wb is not None:
            accepted.append(passed_wb)
            stats.record_accepted()
            # DEBT-030 C 组 / spec 07 §4 line 69：P1 修复 audit trace 累加 per-check_id 计数
            if result.repair_actions:
                stats.record_repair_actions(result.repair_actions)
            # DEBT-030 C 组 / spec 07 §4 line 70：P2 inline clamp aggregate summary merge
            stats.record_p2_clamps_from_accumulator(build_accumulator)
        else:
            stats.record_rejected(result.reject_reason or "unknown_reject")
    return accepted, stats
