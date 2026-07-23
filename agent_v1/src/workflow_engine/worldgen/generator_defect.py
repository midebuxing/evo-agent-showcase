"""Worldgen generator — 缺陷几何子域 surrogate helper（crack / spall / corrosion / detachment / rebar）.

从 generator.py 拆出（纯代码重组，零改行为）。spec 06 §3.2 / §4 surrogate 公式 helper：
裂缝活化/严重度/开口/长度、锈蚀/分层/保护层失/起壳面积/钢筋暴露、钢筋类型/位置/锈蚀形式/截面失采样。

依赖底座（generator_base）：_sigmoid / _age_norm / _cover_norm / _sample_lognormal_arith_mean。
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional

from workflow_engine.worldgen.models import (
    ComponentNode,
    DriverState,
    LocationNode,
)
from workflow_engine.worldgen.generator_base import (
    _age_norm,
    _cover_norm,
    _sample_lognormal_arith_mean,
    _sigmoid,
)


def _compute_crack_score(driver: DriverState) -> float:
    """spec 06 §3.1 crack_score = sigmoid(1.4*service_load + 1.1*restraint + 0.6*workmanship - 1.0)."""
    raw = (
        1.4 * driver.service_load_ratio
        + 1.1 * driver.restraint_level
        + 0.6 * driver.workmanship_deficit_index
        - 1.0
    )
    return _sigmoid(raw)


def _compute_spall_score(driver: DriverState, age_norm: float) -> float:
    """spec 06 §3.1 spall_score = sigmoid(1.2*moisture + 1.1*chloride + 0.8*carbonation + 0.5*age_norm - 1.2)."""
    raw = (
        1.2 * driver.moisture_ingress_index
        + 1.1 * driver.chloride_exposure_index
        + 0.8 * driver.carbonation_index
        + 0.5 * age_norm
        - 1.2
    )
    return _sigmoid(raw)


def _compute_detachment_score(driver: DriverState) -> float:
    """spec 06 §3.1 detachment_score = sigmoid(1.0*moisture + 0.8*workmanship + 0.5*maintenance - 0.8)."""
    raw = (
        1.0 * driver.moisture_ingress_index
        + 0.8 * driver.workmanship_deficit_index
        + 0.5 * driver.maintenance_deficit_index
        - 0.8
    )
    return _sigmoid(raw)


# ---------- spec 06 §3.2 crack surrogate helpers (DEBT-020 round5 sub-task 1) ----------
# 8 个系数授权见 spec 06 §1.3（proagent_engineering_estimate_current_authority_round5_2026_05_10）.
# 输出 *_true 是真值；reported crack_width_mm / crack_length_m 由下游 GEOM_REL_ABS_GAUSS 加噪.

_CRACK_ACTIVATION_BIAS = -2.00
_ALPHA_SERVICE_LOAD = 2.00
_ALPHA_RESTRAINT = 1.30
_ALPHA_WORKMANSHIP = 1.00

_K_OPENING_BASE_MM = 0.06
_K_OPENING_FROM_ACTIVATION_MM = 0.95
_K_LENGTH_SCALE = 0.33
_CRACK_WIDTH_HARD_CAP_MM = 1.25

_CRACK_OPENING_HARD_FLOOR_MM = 0.05
_CRACK_LENGTH_HARD_FLOOR_M = 0.05


def _compute_crack_activation_score(
    service_load_ratio: float,
    restraint_level: float,
    workmanship_deficit: float,
) -> float:
    """spec 06 §3.2 activation_raw = bias + alpha_load*max(load-0.55,0) + alpha_restraint*restraint + alpha_workmanship*workmanship → sigmoid clip."""
    activation_raw = (
        _CRACK_ACTIVATION_BIAS
        + _ALPHA_SERVICE_LOAD * max(service_load_ratio - 0.55, 0.0)
        + _ALPHA_RESTRAINT * restraint_level
        + _ALPHA_WORKMANSHIP * workmanship_deficit
    )
    return max(0.0, min(1.0, _sigmoid(activation_raw)))


def _compute_crack_severity(
    activation_score: float,
    age_norm: float,
    moisture_ingress_index: float,
) -> float:
    """spec 06 §3.2 severity = clip(0.60*activation + 0.20*age_norm + 0.20*moisture, 0, 1)."""
    return max(0.0, min(1.0, 0.60 * activation_score + 0.20 * age_norm + 0.20 * moisture_ingress_index))


def _compute_primary_crack_opening_mm_true(
    severity: float,
    service_load_ratio: float,
    restraint_level: float,
) -> float:
    """spec 06 §3.2 primary_crack_opening_mm_true = clip(k_base + k_act*severity + 0.40*max(load-0.70,0) + 0.25*restraint, 0.05, hard_cap)."""
    raw = (
        _K_OPENING_BASE_MM
        + _K_OPENING_FROM_ACTIVATION_MM * severity
        + 0.40 * max(service_load_ratio - 0.70, 0.0)
        + 0.25 * restraint_level
    )
    return max(_CRACK_OPENING_HARD_FLOOR_MM, min(_CRACK_WIDTH_HARD_CAP_MM, raw))


def _compute_primary_crack_length_m_true(
    severity: float,
    nominal_length_m: float,
) -> float:
    """spec 06 §3.2 primary_crack_length_m_true = clip(0.10 + nominal*(0.35 + k_length*severity), 0.05, nominal_length)."""
    raw = 0.10 + max(nominal_length_m, 0.0) * (0.35 + _K_LENGTH_SCALE * severity)
    return max(_CRACK_LENGTH_HARD_FLOOR_M, min(max(nominal_length_m, _CRACK_LENGTH_HARD_FLOOR_M), raw))


# ---------- spec 06 §4 rebar / spall surrogate helpers ----------

_CORROSION_BIAS = -1.0
_BETA_CHLORIDE = 1.4
_BETA_CARBONATION = 0.8
_BETA_MOISTURE = 1.1
_BETA_AGE = 0.8
_BETA_COVER_PENALTY = 1.2

_K_COVER_LOSS_BASE_MM = 2.0
_K_COVER_LOSS_SCALE = 0.6

_K_SPALL_AREA_SCALE = 0.10

_REBAR_EXPOSURE_OFFSET_MM = 5.0
_REBAR_SPACING_PROXY_M = 0.20
_REBAR_EXPOSED_LENGTH_THRESHOLD_M = 0.10


def _compute_corrosion_severity(
    driver: DriverState, cover_depth_mm: Optional[float], age_years: float
) -> float:
    """spec 06 §4 corrosion_severity_index = clip(sigmoid(corrosion_raw), 0, 1).

    W0-004: age_years 来自 BuildingContext（spec 04 §4 line 79 "driver 可引用"），
    不在 DriverState 上重复存。
    """
    age_norm = _age_norm(age_years)
    cover_n = _cover_norm(cover_depth_mm)
    raw = (
        _CORROSION_BIAS
        + _BETA_CHLORIDE * driver.chloride_exposure_index
        + _BETA_CARBONATION * driver.carbonation_index
        + _BETA_MOISTURE * driver.moisture_ingress_index
        + _BETA_AGE * age_norm
        + 0.80 * driver.workmanship_deficit_index
        + 0.80 * driver.maintenance_deficit_index
        - _BETA_COVER_PENALTY * cover_n
    )
    return max(0.0, min(1.0, _sigmoid(raw)))


def _compute_delamination_severity(corrosion_severity_index: float, driver: DriverState) -> float:
    """spec 06 §4 delamination = clip(0.75*corrosion + 0.15*moisture + 0.10*maintenance, 0, 1)."""
    raw = (
        0.75 * corrosion_severity_index
        + 0.15 * driver.moisture_ingress_index
        + 0.10 * driver.maintenance_deficit_index
    )
    return max(0.0, min(1.0, raw))


def _compute_cover_loss_depth_mm(
    delamination_severity_index: float, cover_depth_mm: Optional[float]
) -> Optional[float]:
    """spec 06 §4 cover_loss_depth_mm = clip(base + scale*delamination*cover, 1, cover+20).

    cover_depth_mm 为 None → 返回 None（没 rebar，无意义）。
    """
    if cover_depth_mm is None:
        return None
    raw = _K_COVER_LOSS_BASE_MM + _K_COVER_LOSS_SCALE * delamination_severity_index * cover_depth_mm
    return max(1.0, min(cover_depth_mm + 20.0, raw))


def _compute_spall_patch_area_m2(
    delamination_severity_index: float,
    moisture_ingress_index: float,
    nominal_visible_area_m2: float,
) -> float:
    """spec 06 §4 spall_patch_area = clip(scale*area*delamination*(0.6+0.4*moisture), 0.001, 0.6*area)."""
    raw = (
        _K_SPALL_AREA_SCALE
        * nominal_visible_area_m2
        * delamination_severity_index
        * (0.6 + 0.4 * moisture_ingress_index)
    )
    return max(0.001, min(0.60 * nominal_visible_area_m2, raw))


def _compute_rebar_exposed_length_m(
    cover_loss_depth_mm: Optional[float],
    cover_depth_mm: Optional[float],
    spall_patch_area_m2: float,
    nominal_length_m: float,
) -> float:
    """spec 06 §4 rebar_exposed_length = clip((exposure_potential/10)*spall_area/spacing, 0, 3*length)."""
    if cover_loss_depth_mm is None or cover_depth_mm is None:
        return 0.0
    exposure_potential_mm = max(0.0, cover_loss_depth_mm - cover_depth_mm + _REBAR_EXPOSURE_OFFSET_MM)
    raw = (exposure_potential_mm / 10.0) * spall_patch_area_m2 / max(_REBAR_SPACING_PROXY_M, 1e-6)
    return max(0.0, min(3.0 * max(nominal_length_m, 0.1), raw))


def _is_rebar_exposed_bool(rebar_exposed_length_m: float) -> bool:
    """spec 06 §4 rebar_exposed_bool = (length >= threshold)."""
    return rebar_exposed_length_m >= _REBAR_EXPOSED_LENGTH_THRESHOLD_M


# ---------- DEBT-020 round5 sub-task 6 (2026-05-10) RebarSectionLossExtend helpers ----------
# 授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1671-L1865
# 用户决策修正版：不扩 measure_registry qualifier dim（违反 W0 不为下游服务原则）；
# 改加 3 个 fragment 物理 metadata（rebar_type / rebar_location / corrosion_loss_type）+
# per-class lognormal section_loss derive（不是 multiplier 方案）.

# Per-class lognormal 分布参数（pro `回复.md`:L1714-L1747）
_REBAR_SECTION_LOSS_PER_CLASS: Dict[str, Dict[str, float]] = {
    "main_bar": {
        "arith_mean": 0.07,
        "sigma_log": 0.75,
        "physical_lo": 0.0,
        "physical_hi": 0.50,
        "typical_lo": 0.0,
        "typical_hi": 0.30,
    },
    "stirrup": {
        "arith_mean": 0.11,
        "sigma_log": 0.80,
        "physical_lo": 0.0,
        "physical_hi": 0.50,
        "typical_lo": 0.0,
        "typical_hi": 0.40,
    },
    "link": {
        "arith_mean": 0.13,
        "sigma_log": 0.85,
        "physical_lo": 0.0,
        "physical_hi": 0.50,
        "typical_lo": 0.0,
        "typical_hi": 0.45,
    },
    "unspecified": {
        "arith_mean": 0.09,
        "sigma_log": 0.75,
        "physical_lo": 0.0,
        "physical_hi": 0.50,
        "typical_lo": 0.0,
        "typical_hi": 0.35,
    },
}

# rebar_type prevalence default（pro `回复.md`:L1709-L1712）；
# 不同 fragment_scope 上 prevalence 应该不同（如 column → main_bar + stirrup 都常见；slab → main_bar + link）.
_REBAR_TYPE_PREVALENCE_DEFAULT: Dict[str, float] = {
    "main_bar": 0.55,
    "stirrup": 0.30,
    "link": 0.15,
}

# Fragment-scope-conditional rebar_type prevalence（按 structural_role 调整：
#   load_bearing column / beam → main_bar 主导
#   slab → main_bar + link 同等
#   wall / non_structural → main_bar 主导但 stirrup 较少）
_REBAR_TYPE_PREVALENCE_BY_STRUCTURAL_ROLE: Dict[str, Dict[str, float]] = {
    "primary_load_bearing": {"main_bar": 0.50, "stirrup": 0.35, "link": 0.15},
    "secondary_load_bearing": {"main_bar": 0.55, "stirrup": 0.30, "link": 0.15},
    "non_load_bearing": {"main_bar": 0.65, "stirrup": 0.20, "link": 0.15},
    "service_component": {"main_bar": 0.60, "stirrup": 0.25, "link": 0.15},
    "finish_only": {"main_bar": 0.55, "stirrup": 0.30, "link": 0.15},
}


def _sample_rebar_type(
    structural_role: Optional[str],
    rng: random.Random,
) -> str:
    """spec 06 §X.X (sub-task 6) physical metadata 派生：rebar_type ∈ {main_bar, stirrup, link, unspecified}.

    从 fragment.structural_role 派生 prevalence（pro `回复.md`:L1709-L1712 default + 按 role 调制）.
    RI 锈蚀报告物理上必然写"哪种钢筋"（load-bearing 钢筋构造决定），所以本 metadata 不是为
    rule_card 服务，是 RI 真实数据的物理对应.
    """
    role = str(structural_role or "").lower() if structural_role else ""
    prevalence = _REBAR_TYPE_PREVALENCE_BY_STRUCTURAL_ROLE.get(
        role, _REBAR_TYPE_PREVALENCE_DEFAULT
    )
    types = list(prevalence.keys())
    weights = [prevalence[t] for t in types]
    return rng.choices(types, weights=weights, k=1)[0]


# rebar_location 候选（候选 A：候选 B 用 metadata only，不作为 primary qualifier）
_REBAR_LOCATION_BY_FRAGMENT_SCOPE_AND_ROLE: Dict[str, Dict[str, List[str]]] = {
    # fragment_scope → structural_role → list of plausible locations
    "structural_components": {
        "primary_load_bearing": ["beam", "column", "wall"],
        "secondary_load_bearing": ["beam", "wall"],
        "non_load_bearing": ["wall"],
        "service_component": ["beam", "wall"],
    },
    "external": {
        "primary_load_bearing": ["wall", "column"],
        "secondary_load_bearing": ["wall"],
        "non_load_bearing": ["wall"],
    },
    "structural": {
        "primary_load_bearing": ["beam", "column", "wall", "slab"],
        "secondary_load_bearing": ["beam", "wall", "slab"],
        "non_load_bearing": ["wall", "slab"],
    },
    "drainage": {"service_component": ["wall", "foundation"]},
    "fire_safety": {"service_component": ["wall"]},
}


def _sample_rebar_location(
    fragment_scope: Optional[str],
    structural_role: Optional[str],
    rng: random.Random,
) -> str:
    """spec 06 §X.X (sub-task 6) physical metadata 派生：rebar_location.

    候选 A 启用：location ∈ {beam, column, slab, wall, stair, foundation}（结构部位，
    RI 必然写"哪个构件的钢筋"）；从 fragment.fragment_scope + structural_role 派生候选集合.
    """
    scope = str(fragment_scope or "").lower()
    role = str(structural_role or "").lower()
    candidates = _REBAR_LOCATION_BY_FRAGMENT_SCOPE_AND_ROLE.get(scope, {}).get(role)
    if not candidates:
        # fallback（按 scope 推测候选）
        if "structural" in scope:
            candidates = ["beam", "column", "wall", "slab"]
        elif "external" in scope or "facade" in scope:
            candidates = ["wall", "column"]
        elif "stair" in scope:
            candidates = ["stair"]
        else:
            candidates = ["wall"]
    return rng.choice(candidates)


# corrosion_loss_type prevalence default（pro `回复.md`:L1768-L1771）；
# driver state（chloride_exposure / moisture_ingress 等）影响分布
_CORROSION_LOSS_TYPE_PREVALENCE_DEFAULT: Dict[str, float] = {
    "uniform_corrosion": 0.65,
    "pitting": 0.30,
    "section_reduction": 0.05,
}


def _sample_corrosion_loss_type(
    chloride_exposure_index: float,
    moisture_ingress_index: float,
    corrosion_severity_index: float,
    rng: random.Random,
) -> str:
    """spec 06 §X.X (sub-task 6) physical metadata 派生：corrosion_loss_type.

    enum ∈ {uniform_corrosion, pitting, section_reduction, unspecified}.
    物理因果调制 prevalence：
      - chloride_exposure 高 → pitting 概率上升（氯离子驱动局部腐蚀）
      - corrosion_severity 高 → section_reduction 概率上升（深度腐蚀失材）
      - 普通湿气 → uniform_corrosion 主导
    RI 报告必然描述锈蚀形式，本 metadata 不是为 rule_card 服务.
    """
    base = dict(_CORROSION_LOSS_TYPE_PREVALENCE_DEFAULT)
    # 物理调制
    chloride = max(0.0, min(1.0, float(chloride_exposure_index)))
    severity = max(0.0, min(1.0, float(corrosion_severity_index)))
    # chloride 主调 pitting：每 0.1 chloride 把 5% 从 uniform 移到 pitting
    pitting_boost = 0.5 * chloride  # max 0.5 boost
    base["pitting"] = min(0.85, base["pitting"] + pitting_boost)
    base["uniform_corrosion"] = max(0.05, base["uniform_corrosion"] - pitting_boost)
    # severity 主调 section_reduction：高 severity 时 section_reduction 概率上升
    if severity > 0.65:
        sr_boost = 0.15 * (severity - 0.65) / 0.35
        base["section_reduction"] = min(0.30, base["section_reduction"] + sr_boost)
        base["uniform_corrosion"] = max(0.05, base["uniform_corrosion"] - sr_boost)
    # 归一化
    total = sum(base.values())
    if total > 0:
        for k in base:
            base[k] /= total
    types = list(base.keys())
    weights = [base[t] for t in types]
    return rng.choices(types, weights=weights, k=1)[0]


def _compute_rebar_section_loss_ratio_per_class(
    rebar_type: str,
    corrosion_severity_index: float,
    chloride_exposure_index: float,
    moisture_ingress_index: float,
    cover_depth_mm: Optional[float],
    rng: random.Random,
) -> float:
    """spec 06 §X.X (sub-task 6) per-class lognormal section_loss derive — 用户决策方案 B.

    设计要求（用户决策原则）：
      1. 不用 multiplier 方案 A（pro 原 `回复.md`:L1437-L1461）
      2. 物理因果（头端） + per-class lognormal（尾端覆盖法规 escalation proxy 边界）
      3. lognormal mean 是 arithmetic_mean（DEBT-028 footgun 防）
      4. 物理 driver multiplier 调制最终 ratio

    实现：
      base = 物理因果驱动 base section_loss（corrosion / chloride / moisture / cover）
      lognormal sample with class-specific mean/sigma → quantile 映射到 base 周围
      具体：sample lognormal_class，再用 driver_factor 调制（factor near 1 时分布以 class mean 为主）
    """
    cls = rebar_type if rebar_type in _REBAR_SECTION_LOSS_PER_CLASS else "unspecified"
    params = _REBAR_SECTION_LOSS_PER_CLASS[cls]

    # 物理 driver factor（base ~ 0.5-1.5，让 driver 状态调制 class 分布的 location，
    # 不动 distribution shape）
    cover = float(cover_depth_mm) if cover_depth_mm is not None else 25.0
    cover_deficit_factor = max(0.0, min(1.0, (25.0 - cover) / 25.0))
    physical_drive = (
        0.50  # baseline (no severity at all → halve class mean)
        + 1.05 * float(corrosion_severity_index)
        + 0.25 * float(chloride_exposure_index)
        + 0.20 * float(moisture_ingress_index)
        + 0.15 * cover_deficit_factor
    )
    # physical_drive in [0.5, 2.15] approx; clip to [0.4, 2.0] to avoid extreme tails
    physical_drive = max(0.4, min(2.0, physical_drive))

    # Sample lognormal with class-specific arith_mean + sigma; multiply by physical_drive / 1.0
    # （物理 baseline 1.0 = class mean；高 driver → class mean 上调；低 driver → 下调）
    raw_class = _sample_lognormal_arith_mean(
        arithmetic_mean=float(params["arith_mean"]),
        sigma_log=float(params["sigma_log"]),
        clip_lo=float(params["physical_lo"]),
        clip_hi=float(params["physical_hi"]),
        rng=rng,
    )
    # physical_drive / baseline_drive (1.0) — class mean 在 driver=1 时未调，driver 偏移调高低
    baseline_drive = 1.0
    adjusted = raw_class * (physical_drive / baseline_drive)
    # final clip 到 physical bounds [0, 0.50]
    return max(float(params["physical_lo"]), min(float(params["physical_hi"]), adjusted))
