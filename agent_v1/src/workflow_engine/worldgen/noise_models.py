"""Named noise models per spec 06 §14.

每个 noise model 是 (deterministic_value, slot_bounds, rng) -> noisy_value 的 pure function。
不依赖外部状态。

T-20 接入是后续工单：generator.py::_sample_value_for_slot 当前用 uniform within bounds，
T-20-接入工单后改用 noise model 包裹真值（spec 公式输出）+ family-specific noise。
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Literal, Optional, Tuple

NoiseModelId = Literal[
    "GEOM_REL_ABS_GAUSS",
    "RATIO_ABS_GAUSS",
    "COUNT_POISSON_ROUND",
    "TECH_REL_GAUSS",
    "BOOL_DERIVED_NOISELESS",
]

# spec 06 §14 参数表（rel_sigma / abs_sigma / clip）
NOISE_MODEL_PARAMS: Dict[str, Dict[str, Any]] = {
    "GEOM_REL_ABS_GAUSS": {
        "rel_sigma": 0.08,
        # abs_sigma slot-specific（按 slot.unit 决定），下面的 default 是 fallback
        "abs_sigma_default": {"mm": 0.05, "m": 0.005, "m2": 0.001},
        "clip_strategy": "slot_bounds",  # clip 到 slot.physical_bounds[0..1]
    },
    "RATIO_ABS_GAUSS": {
        "rel_sigma": 0.0,
        "abs_sigma_default": {"ratio": 0.03},
        "clip_strategy": "ratio_unit",  # [0, 1]
    },
    "COUNT_POISSON_ROUND": {
        "rel_sigma": 0.0,
        # Poisson abs_sigma=1 count 是 spec §14 描述（用 Poisson(λ=value) 抽样后取整 + clip(>=0)）
        "abs_sigma_default": {"count": 1.0},
        "clip_strategy": "non_negative_integer",
    },
    "TECH_REL_GAUSS": {
        "rel_sigma": 0.06,  # technical_validation / assessment 默认；assessment 走 0.05 由 family 选 model 时覆盖
        "abs_sigma_default": {},  # slot-specific
        "clip_strategy": "slot_bounds",
    },
    "BOOL_DERIVED_NOISELESS": {
        "rel_sigma": 0.0,
        "abs_sigma_default": {},
        "clip_strategy": "bool_passthrough",  # 不加 noise，直接通过
    },
}

# measurement_family -> noise_model_id 映射（spec 06 §14 行映射）
MEASUREMENT_FAMILY_TO_NOISE_MODEL: Dict[str, NoiseModelId] = {
    "defect_geometry": "GEOM_REL_ABS_GAUSS",        # spec 06 §14 行 1
    "coverage_sampling": "RATIO_ABS_GAUSS",          # spec 06 §14 行 2 (ratio family)
    "technical_validation": "TECH_REL_GAUSS",        # spec 06 §14 行 3
    "derived_risk_measurement": "TECH_REL_GAUSS",    # spec 06 §14 assessment family，用 rel=0.05 覆盖
    "boolean_assertion": "BOOL_DERIVED_NOISELESS",   # spec 06 §14 行 5 (bool derived)
}

# spec 06 §13 precision rounding 表
PRECISION_ROUNDING: Dict[str, Dict[str, float]] = {
    "geometry_width_mm": {"coarse": 0.10, "standard": 0.05, "fine": 0.01},
    "geometry_length_m": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
    "geometry_area_m2": {"coarse": 0.010, "standard": 0.001, "fine": 0.0005},
    "coverage_ratio": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
    "test_stress": {"coarse": 10.0, "standard": 1.0, "fine": 0.1},
    "thickness_depth_mm": {"coarse": 5.0, "standard": 1.0, "fine": 0.5},
    "assessment_ratio": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
    # integer / count 不做 rounding
}


def apply_noise_geom_rel_abs_gauss(
    deterministic_value: float,
    abs_sigma: float,
    bounds: Tuple[float, float],
    rng: random.Random,
) -> float:
    """spec 06 §14 GEOM_REL_ABS_GAUSS：v + N(0, max(rel*v, abs)) clipped to bounds."""
    rel = NOISE_MODEL_PARAMS["GEOM_REL_ABS_GAUSS"]["rel_sigma"]
    sigma = max(rel * abs(deterministic_value), abs_sigma)
    noisy = deterministic_value + rng.gauss(0.0, sigma)
    return _clip(noisy, bounds)


def apply_noise_ratio_abs_gauss(
    deterministic_value: float,
    rng: random.Random,
    abs_sigma: Optional[float] = None,
) -> float:
    """spec 06 §14 RATIO_ABS_GAUSS：v + N(0, abs_sigma=0.03) clipped to [0,1]."""
    sigma = abs_sigma if abs_sigma is not None else NOISE_MODEL_PARAMS["RATIO_ABS_GAUSS"]["abs_sigma_default"]["ratio"]
    noisy = deterministic_value + rng.gauss(0.0, sigma)
    return _clip(noisy, (0.0, 1.0))


def apply_noise_count_poisson_round(
    deterministic_value: float,
    rng: random.Random,
) -> int:
    """spec 06 §14 COUNT_POISSON_ROUND：Poisson(λ=v) clipped >= 0."""
    lam = max(deterministic_value, 0.0)
    if lam == 0.0:
        return 0
    return _poisson_sample(lam, rng)


def apply_noise_tech_rel_gauss(
    deterministic_value: float,
    abs_sigma: float,
    bounds: Tuple[float, float],
    rng: random.Random,
    rel_sigma_override: Optional[float] = None,
) -> float:
    """spec 06 §14 TECH_REL_GAUSS：v + N(0, max(rel*v, abs)) clipped to bounds.

    rel_sigma_override：assessment family 用 0.05 而非默认 0.06。
    """
    rel = rel_sigma_override if rel_sigma_override is not None else NOISE_MODEL_PARAMS["TECH_REL_GAUSS"]["rel_sigma"]
    sigma = max(rel * abs(deterministic_value), abs_sigma)
    noisy = deterministic_value + rng.gauss(0.0, sigma)
    return _clip(noisy, bounds)


def apply_noise_bool_passthrough(deterministic_value: bool) -> bool:
    """spec 06 §14 BOOL_DERIVED_NOISELESS：直接返回，不加 noise。"""
    return bool(deterministic_value)


def apply_precision_rounding(value: float, precision_key: str, precision_class: str = "standard") -> float:
    """spec 06 §13 precision rounding：按 family + class 规整到 step。

    precision_class ∈ {coarse, standard, fine}；precision_key 是 spec 表行键
    （geometry_width_mm / geometry_length_m / geometry_area_m2 / coverage_ratio /
     test_stress / thickness_depth_mm / assessment_ratio）。
    integer / count 不调本函数。
    """
    if precision_key not in PRECISION_ROUNDING:
        return value
    step = PRECISION_ROUNDING[precision_key].get(precision_class, PRECISION_ROUNDING[precision_key]["standard"])
    if step <= 0:
        return value
    return round(value / step) * step


# ---------- helpers ----------

def _clip(value: float, bounds: Tuple[float, float]) -> float:
    lo, hi = bounds
    return max(lo, min(hi, value))


def _poisson_sample(lam: float, rng: random.Random) -> int:
    """Knuth's Poisson sampler（lam 不大时高效，此处不超过 hundreds 量级）。"""
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def get_noise_model_for_family(measurement_family: str) -> NoiseModelId:
    """Return the named noise model for a measurement_family (spec 06 §14)."""
    return MEASUREMENT_FAMILY_TO_NOISE_MODEL.get(measurement_family, "TECH_REL_GAUSS")


# spec 06 §14 slot-specific abs_sigma 表（按 unit + measurement_family 路由）
# spec 注 "abs_sigma 0.05mm / 0.005m / 0.001m²"（geometry 类）；ratio=0.03；count=1。
# technical_validation slot-specific——按 unit 类型给保守默认。
_ABS_SIGMA_BY_UNIT_AND_FAMILY: Dict[str, Dict[str, float]] = {
    # GEOM_REL_ABS_GAUSS（defect_geometry family）
    "GEOM_REL_ABS_GAUSS": {
        "mm": 0.05,           # spec §14 default
        "m": 0.005,           # spec §14 default
        "m2": 0.001,          # spec §14 default (m²)
        "m^2": 0.001,         # alias
        "_default": 0.005,    # fallback
    },
    # RATIO_ABS_GAUSS（coverage_sampling family）
    "RATIO_ABS_GAUSS": {
        "ratio": 0.03,        # spec §14
        "1": 0.03,            # alias
        "_default": 0.03,
    },
    # COUNT_POISSON_ROUND（count slots）
    "COUNT_POISSON_ROUND": {
        "count": 1.0,
        "_default": 1.0,
    },
    # TECH_REL_GAUSS（technical_validation / derived_risk_measurement family）
    "TECH_REL_GAUSS": {
        "mm": 0.5,            # technical thickness/depth coarser than geometry
        "m": 0.05,
        "m2": 0.01,
        "m^2": 0.01,
        "ratio": 0.02,
        "MPa": 0.5,           # stress
        "kPa": 50.0,
        "Pa": 5e4,
        "%": 0.5,
        "year": 1.0,          # duration in years
        "month": 1.0,
        "day": 1.0,
        "_default": 0.0,      # rel_sigma covers main; abs_sigma 0 fallback
    },
    # BOOL_DERIVED_NOISELESS — abs_sigma irrelevant
    "BOOL_DERIVED_NOISELESS": {
        "_default": 0.0,
    },
}


def get_abs_sigma_for_slot(
    slot_record: Dict[str, Any],
    noise_model_id: Optional[NoiseModelId] = None,
) -> float:
    """spec 06 §14 slot-specific abs_sigma 路由.

    根据 slot_record.unit + 对应 noise model 返回 abs_sigma；
    不提供 noise_model_id 时按 slot_record.measurement_family 自动派生。

    Args:
        slot_record: technical_measurement_registry record（含 measurement_family / unit）
        noise_model_id: 可选 noise model 显式指定；不给时自动派生

    Returns:
        abs_sigma >= 0；slot 没记录的 unit 走对应 noise model 的 _default。
    """
    if noise_model_id is None:
        noise_model_id = get_noise_model_for_family(
            slot_record.get("measurement_family", "")
        )
    sigma_table = _ABS_SIGMA_BY_UNIT_AND_FAMILY.get(noise_model_id, {})
    if not sigma_table:
        return 0.0
    unit = slot_record.get("unit") or "_default"
    return float(sigma_table.get(unit, sigma_table.get("_default", 0.0)))


def apply_named_noise(
    noise_model_id: NoiseModelId,
    deterministic_value: Any,
    bounds: Tuple[float, float],
    abs_sigma: float = 0.0,
    rng: Optional[random.Random] = None,
    rel_sigma_override: Optional[float] = None,
) -> Any:
    """Dispatch entry：按 noise_model_id 调对应函数。"""
    if rng is None:
        rng = random.Random()
    if noise_model_id == "GEOM_REL_ABS_GAUSS":
        return apply_noise_geom_rel_abs_gauss(float(deterministic_value), abs_sigma, bounds, rng)
    if noise_model_id == "RATIO_ABS_GAUSS":
        return apply_noise_ratio_abs_gauss(float(deterministic_value), rng, abs_sigma if abs_sigma else None)
    if noise_model_id == "COUNT_POISSON_ROUND":
        return apply_noise_count_poisson_round(float(deterministic_value), rng)
    if noise_model_id == "TECH_REL_GAUSS":
        return apply_noise_tech_rel_gauss(float(deterministic_value), abs_sigma, bounds, rng, rel_sigma_override)
    if noise_model_id == "BOOL_DERIVED_NOISELESS":
        return apply_noise_bool_passthrough(bool(deterministic_value))
    raise ValueError(f"Unknown noise_model_id: {noise_model_id}")
