"""Worldgen generator — 共享底座 helper（registry 访问 / 数学原语 / 采样原语）.

本模块是 generator.py 拆分后的公共底座层（纯代码重组，零改行为）：
- registry 访问层：_get_registry / _registry_records / _registry_index + lookup cache + 各 _lookup_*
- sampling_plan_registry lookup：_lookup_sampling_plan_record / _resolve_sampling_plan_*
- 数学原语：_sigmoid / _age_norm / _cover_norm
- 通用 helper：_weighted_choice / _sanitize_id_component / _parse_keyword_int
- 采样原语：_resolve_lognormal_mu / _sample_lognormal_arith_mean / _sample_truncated_normal

子域模块（generator_defect / generator_drainage / generator_ubw / generator_fire /
generator_sampling）从本模块 import 这些底座名字；generator.py 把全部底座名字 re-export，
保证外部 `from workflow_engine.worldgen.generator import X` 不断。
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional

from workflow_engine.worldgen.models import (
    RegistryBundle,
    RegistryTable,
)


# ---------- registry helpers ----------


def _get_registry(registries: RegistryBundle, registry_id: str) -> RegistryTable:
    for table in registries.registries:
        if table.registry_id == registry_id:
            return table
    raise ValueError(f"Registry {registry_id!r} not found in bundle")


def _registry_records(registries: RegistryBundle, registry_id: str) -> List[Dict[str, Any]]:
    return list(_get_registry(registries, registry_id).records)


def _registry_index(registries: RegistryBundle, registry_id: str, key_field: str) -> Dict[str, Dict[str, Any]]:
    return {record[key_field]: record for record in _registry_records(registries, registry_id)}


# ---------- registry lookup cache (DEBT-030 D1, 2026-05-13) ----------
# 用 id(registries) 当 key 把 mapping inline 抽出 registry lookup 后的 O(1) cache。
# RegistryBundle (pydantic BaseModel) 默认不可哈希，且整批 generation 内 registries 引用稳定
# (initializer 设进 _WORKER_REGISTRIES 后或单元测试单次构造)，所以用 id() 做 cache key。
# 当 id collide (旧对象被 GC 后新对象复用 id)，cache 拿到的字段语义相同 (registry schema 稳定)，
# 不会出错；不一致时下一次 lookup 自然重算。
_REGISTRY_LOOKUP_CACHE: Dict[int, Dict[str, Any]] = {}


def _get_lookup_cache(registries: RegistryBundle, cache_key: str) -> Any:
    """获取 registries 上 cache_key 对应的 lookup table；None 表示未建过。"""
    bucket = _REGISTRY_LOOKUP_CACHE.get(id(registries))
    if bucket is None:
        return None
    return bucket.get(cache_key)


def _set_lookup_cache(registries: RegistryBundle, cache_key: str, value: Any) -> None:
    """把 cache_key 的 lookup table 落到 registries 的 cache bucket。"""
    bucket = _REGISTRY_LOOKUP_CACHE.setdefault(id(registries), {})
    bucket[cache_key] = value


# ---------- registry-driven lookup helpers (DEBT-030 D1) ----------


def _lookup_primary_condition_class_from_mechanism_family(
    mechanism_family: str,
    registries: RegistryBundle,
) -> str:
    """spec 02 §2 / spec 03 §2.6: 从 mechanism_library_registry.output_condition_classes
    取该 family 的第一个 condition_class 作 default(主) condition.

    fallback: registry 没该 family 或 output_condition_classes 空时返回 ``DC_CRACK``
    (与 legacy `_MECHANISM_FAMILY_TO_CONDITION` 默认值一致, 保 backward compat).
    """
    cache_key = "mechanism_family_to_primary_condition"
    table: Optional[Dict[str, str]] = _get_lookup_cache(registries, cache_key)
    if table is None:
        table = {}
        for record in _registry_records(registries, "mechanism_library_registry"):
            family = record.get("mechanism_family")
            outputs = record.get("output_condition_classes") or []
            if family and outputs:
                # registry 同 family 多 mechanism_id 时取第一条 (a12 历史上 1:1, 现也是 1:1)
                if family not in table:
                    table[family] = outputs[0]
        _set_lookup_cache(registries, cache_key, table)
    return table.get(mechanism_family, "DC_CRACK")


def _lookup_fire_component_class_from_component_type(
    component_type: str,
    registries: RegistryBundle,
) -> str:
    """spec 02 §2 / spec 03 §2.2.1: 从 component_type_registry 找该 component_type 是否属
    fire_safety_component, 是则返回 component_type 自身 (FireSafetyState.fire_component_class
    枚举值 1:1 对应 5 种 fire-safety component_type), 否则返回 ``unknown_fire_component``.

    FireSafetyState.fire_component_class 枚举:
      {"fire_door", "fire_resisting_wall", "escape_route", "smoke_vent",
       "fire_service_installation", "unknown_fire_component"}
    与 component_type_registry 里 component_class=="fire_safety_component" 的 5 个 type 1:1
    (其它 component_type 走 unknown_fire_component fallback).
    """
    cache_key = "fire_safety_component_types"
    fire_types: Optional[set] = _get_lookup_cache(registries, cache_key)
    if fire_types is None:
        fire_types = set()
        for record in _registry_records(registries, "component_type_registry"):
            if record.get("component_class") == "fire_safety_component":
                ctype = record.get("component_type")
                if ctype:
                    fire_types.add(ctype)
        _set_lookup_cache(registries, cache_key, fire_types)
    if component_type in fire_types:
        return component_type
    return "unknown_fire_component"


def _domain_of_component_type(
    component_type: str,
    registries: RegistryBundle,
) -> str:
    """spec 06 §0.1 表 row "fragment_scope": derive `domain_of(component.component_type)` via
    spec 03 §4.1 `component_type_registry[ct].allowed_mechanisms`：

    - 含 `fire_safety_deficiency` → `fire_safety`
    - 含 `drainage_blockage` / `drainage_misconnection` / `drainage_fault` → `drainage`
    - 含 `unauthorized_alteration` / `ubw_signal` → `ubw`
    - 否则按 component_class 兜底：external/structural component → `structural` / `external`
    - 完全无信息 → `structural`（默认主域）.

    fallback: registry bundle 不含 component_type_registry 或没该 type → 返回 `structural`.
    cache: 同 registries 上重复查询 O(1).
    """
    cache_key = "component_type_domain"
    table: Optional[Dict[str, str]] = _get_lookup_cache(registries, cache_key)
    if table is None:
        table = {}
        try:
            records = _registry_records(registries, "component_type_registry")
        except ValueError:
            records = []
        for record in records:
            ctype = record.get("component_type")
            if not ctype:
                continue
            allowed = set(record.get("allowed_mechanisms") or [])
            component_class = str(record.get("component_class") or "")
            if "fire_safety_deficiency" in allowed or component_class == "fire_safety_component":
                domain = "fire_safety"
            elif any(m for m in allowed if "drainage" in m):
                domain = "drainage"
            elif any(m for m in allowed if "alteration" in m or "ubw" in m):
                domain = "ubw"
            elif "external" in component_class or "external" in ctype:
                domain = "external"
            else:
                domain = "structural"
            table[ctype] = domain
        _set_lookup_cache(registries, cache_key, table)
    return table.get(component_type, "structural")


def _material_system_supports_rebar(
    material_system: str,
    registries: RegistryBundle,
) -> bool:
    """spec 02 §2 / spec 03 §2.2.3: 从 material_system_registry.supports_rebar 字段读
    该 material_system 是否承载钢筋.

    fallback: registry 没该 material_system 时返回 False (按"未知材料不假设钢筋"原则,
    与 spec 03 §4.6 unknown_material 条目 supports_rebar=False 一致).
    """
    cache_key = "material_system_supports_rebar"
    table: Optional[Dict[str, bool]] = _get_lookup_cache(registries, cache_key)
    if table is None:
        table = {}
        try:
            records = _registry_records(registries, "material_system_registry")
        except ValueError:
            # 测试 / mock bundle 可能不含本 registry; 走 fallback (未知材料按 supports_rebar=False).
            records = []
        for record in records:
            mat = record.get("material_system")
            if mat:
                table[mat] = bool(record.get("supports_rebar", False))
        _set_lookup_cache(registries, cache_key, table)
    return table.get(material_system, False)


# ---------- sampling_plan_registry lookup (DEBT-030 D2, 2026-05-13) ----------
# DEBT-020 Round 5 sub-task 2 / 4 chain derive 的 plan 数据来源 registry.
# 解析的 plan_intensity_distribution dict 字段:
#   recommended_distribution / recommended_mean / recommended_sigma / typical_bounds
# (与 technical_measurement_registry typical 字段同义, spec 03 §2.3 §4.4).


def _lookup_sampling_plan_record(
    sampling_plan_id: str,
    registries: RegistryBundle,
) -> Optional[Dict[str, Any]]:
    """spec 03 §4.4 / spec 02 §2: 按 sampling_plan_id 取 sampling_plan_registry 的 plan record.

    fallback: registry bundle 不含 sampling_plan_registry 或没该 plan_id → 返回 None
    (caller 退到 hardcoded constants). cache: 同 registries 上重复查询 O(1).
    """
    cache_key = "sampling_plan_by_id"
    table: Optional[Dict[str, Dict[str, Any]]] = _get_lookup_cache(registries, cache_key)
    if table is None:
        table = {}
        try:
            records = _registry_records(registries, "sampling_plan_registry")
        except ValueError:
            # 测试 / mock bundle 可能不含本 registry; 走 fallback.
            records = []
        for record in records:
            plan_id = record.get("sampling_plan_id")
            if plan_id:
                table[plan_id] = record
        _set_lookup_cache(registries, cache_key, table)
    return table.get(sampling_plan_id)


def _resolve_sampling_plan_intensity_params(
    sampling_plan_id: str,
    registries: Optional[RegistryBundle],
    fallback_distribution: str,
    fallback_mean: float,
    fallback_sigma: float,
    fallback_clip_lo: float,
    fallback_clip_hi: float,
) -> Dict[str, Any]:
    """从 sampling_plan_registry 取 plan_intensity_distribution 4 字段.

    返回 dict:
      - "recommended_distribution" (str)
      - "recommended_mean" (float)
      - "recommended_sigma" (float)
      - "typical_bounds" (List[float, float])
    缺失 (registries None / plan_id 未找到 / 字段不全) 时返回 fallback hardcoded constants.
    """
    if registries is not None:
        record = _lookup_sampling_plan_record(sampling_plan_id, registries)
        if record is not None:
            intensity = record.get("plan_intensity_distribution") or {}
            distribution = intensity.get("recommended_distribution") or fallback_distribution
            mean = intensity.get("recommended_mean")
            sigma = intensity.get("recommended_sigma")
            typical = intensity.get("typical_bounds") or [fallback_clip_lo, fallback_clip_hi]
            if (
                mean is not None
                and sigma is not None
                and isinstance(typical, (list, tuple))
                and len(typical) == 2
            ):
                return {
                    "recommended_distribution": str(distribution),
                    "recommended_mean": float(mean),
                    "recommended_sigma": float(sigma),
                    "typical_bounds": [float(typical[0]), float(typical[1])],
                }
    return {
        "recommended_distribution": fallback_distribution,
        "recommended_mean": fallback_mean,
        "recommended_sigma": fallback_sigma,
        "typical_bounds": [fallback_clip_lo, fallback_clip_hi],
    }


def _resolve_sampling_plan_total_count_clip(
    sampling_plan_id: str,
    registries: Optional[RegistryBundle],
    fallback_lower: int,
    fallback_upper: int,
) -> tuple[int, int]:
    """从 sampling_plan_registry::total_count_formula 文本提取 round_clip 的 lower/upper.

    registry record 里 total_count_formula 是 string，含 `round_clip(..., lower=L, upper=U)` 模式;
    parse 不出 (registry 没 plan / 文本不匹配) 时退到 fallback hardcoded constants.

    保守解析：用最简单的 "lower=" / "upper=" 子串搜索 + int parse，避免引入 regex 依赖.
    """
    if registries is None:
        return (fallback_lower, fallback_upper)
    record = _lookup_sampling_plan_record(sampling_plan_id, registries)
    if record is None:
        return (fallback_lower, fallback_upper)
    formula = record.get("total_count_formula")
    if not isinstance(formula, str):
        return (fallback_lower, fallback_upper)
    lower_val = _parse_keyword_int(formula, "lower=", fallback_lower)
    upper_val = _parse_keyword_int(formula, "upper=", fallback_upper)
    return (lower_val, upper_val)


def _parse_keyword_int(text: str, keyword: str, fallback: int) -> int:
    """从文本里抽 `keyword<digits>` 模式的整数（无 regex 简版）.

    例如 _parse_keyword_int("round_clip(..., lower=1, upper=25)", "lower=", 0) -> 1.
    keyword 没出现/后面非数字 → fallback.
    """
    pos = text.find(keyword)
    if pos < 0:
        return int(fallback)
    start = pos + len(keyword)
    end = start
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == start:
        return int(fallback)
    try:
        return int(text[start:end])
    except ValueError:
        return int(fallback)


# ---------- sampling helpers ----------


def _weighted_choice(items: List[str], weights: List[float], rng: random.Random) -> str:
    """Sample one item from items by weights (sum may be 0 → uniform fallback)."""
    total = sum(weights)
    if total <= 0:
        return rng.choice(items)
    threshold = rng.uniform(0, total)
    cumulative = 0.0
    for item, weight in zip(items, weights):
        cumulative += weight
        if threshold <= cumulative:
            return item
    return items[-1]


def _sanitize_id_component(text: str) -> str:
    """Convert a string to ID-safe form: uppercase letters / digits / dashes only."""
    cleaned = []
    for char in text:
        if char.isalnum():
            cleaned.append(char.upper())
        else:
            cleaned.append("-")
    # collapse multiple dashes
    result: List[str] = []
    prev_dash = False
    for char in cleaned:
        if char == "-":
            if not prev_dash:
                result.append(char)
            prev_dash = True
        else:
            result.append(char)
            prev_dash = False
    return "".join(result).strip("-")


# ---------- spec 06 §3.1 surrogate formula primitives ----------


def _sigmoid(x: float) -> float:
    """Standard sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _age_norm(age_years: float) -> float:
    """spec 06 §3.2 age_norm = clip(age_years / 50.0, 0.0, 1.0)."""
    return max(0.0, min(1.0, age_years / 50.0))


def _cover_norm(cover_depth_mm: Optional[float]) -> float:
    """spec 06 §4 cover_norm = clip(cover_depth_mm / 40.0, 0.0, 2.0).

    cover_depth_mm 为 None（has_rebar=False）时返回 0.0（无 rebar 约束）。
    """
    if cover_depth_mm is None:
        return 0.0
    return max(0.0, min(2.0, cover_depth_mm / 40.0))


# ---------- 采样原语（被 generator_defect / generator_sampling / slot 取值共用） ----------

_ALLOWED_LOGNORMAL_MEAN_SEMANTICS = ("arithmetic_mean", "median")


def _resolve_lognormal_mu(
    mean: float,
    sigma_log: float,
    mean_semantics: str,
) -> float:
    """根据 mean_semantics 把 (mean, sigma_log) 转 lognormal underlying mu 参数.

    DEBT-028 / DEBT-029 (2026-05-11)：唯一的 lognormal mu 解析点，
    避免 chain derive helper 跟 generic distribution path 两处独立实现漂移。

    - "arithmetic_mean"（pro 设计标准 / chain derive 标准）：
        arithmetic_mean = exp(mu + sigma^2/2) → mu = ln(arith) - sigma^2/2
    - "median"（旧 W0 行为 / 向后兼容）：
        median = exp(mu) → mu = ln(median)

    两种语义在 sigma 大时差 exp(sigma^2/2) 倍（sigma=0.75 偏 1.32×）。
    非法值 raise，禁止 typo 静默通过。
    """
    sigma = float(sigma_log)
    log_arith = math.log(max(float(mean), 1e-9))
    if mean_semantics == "arithmetic_mean":
        return log_arith - 0.5 * sigma * sigma
    if mean_semantics == "median":
        return log_arith
    raise ValueError(
        f"Invalid mean_semantics={mean_semantics!r}; "
        f"expected one of {list(_ALLOWED_LOGNORMAL_MEAN_SEMANTICS)}."
    )


def _sample_lognormal_arith_mean(
    arithmetic_mean: float,
    sigma_log: float,
    clip_lo: float,
    clip_hi: float,
    rng: random.Random,
) -> float:
    """Sample lognormal where `arithmetic_mean` 是分布的算术均值（不是 median）.

    DEBT-029 后：薄包装，委托 `_resolve_lognormal_mu` 做 mean→mu 转换；
    chain derive 调用方（facade_area / plan_intensity / retiling / rebar 等）签名不变。
    """
    sigma = float(sigma_log)
    mu = _resolve_lognormal_mu(arithmetic_mean, sigma, "arithmetic_mean")
    value = rng.lognormvariate(mu, sigma)
    return max(clip_lo, min(clip_hi, value))


def _sample_truncated_normal(
    mean: float,
    sigma: float,
    clip_lo: float,
    clip_hi: float,
    rng: random.Random,
    max_resamples: int = 50,
) -> float:
    """Truncated normal: 在 [clip_lo, clip_hi] 内重采，最多 max_resamples 次后 hard clip."""
    for _ in range(max_resamples):
        value = rng.gauss(float(mean), float(sigma))
        if clip_lo <= value <= clip_hi:
            return value
    # 超过重采上限，hard clip mean
    return max(clip_lo, min(clip_hi, float(mean)))
