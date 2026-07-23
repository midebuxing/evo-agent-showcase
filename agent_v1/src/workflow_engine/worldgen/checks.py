"""C001-C032 worldgen gate check functions (spec 07 §2) — T-22.

注：C023-C025 属 W2 法规映射层 NormativeProjection-level 约束（W2 规格 07 §5），由
`regulation_projection_executor` inline gate 执行，不在本模块；C026（HiddenGold thin copy）
已删。本模块实际注册 worldgen 端 P0/P1/P2/REPAIR 各级 check。

Import-time side effect: registers checks into gates.py P0/P1/P2/REPAIR lists.
generator.py 頂部加 ``import workflow_engine.worldgen.checks  # noqa: F401``
以觸發注冊。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from workflow_engine.worldgen.gates import (
    RepairAction,
    Violation,
    register_p0_check,
    register_p1_check,
    register_p2_check,
    register_p1_repair,
)
from workflow_engine.worldgen.models import (
    RegistryBundle,
    WorldBundle,
)


# ---------- registry helpers ----------


def _registry_index(
    registries: RegistryBundle,
    registry_id: str,
    key_field: str,
) -> Dict[str, Dict[str, Any]]:
    """Return dict keyed by key_field for the named registry table."""
    for table in registries.registries:
        if table.registry_id == registry_id:
            return {rec[key_field]: rec for rec in table.records if rec.get(key_field)}
    return {}


# ---------- component type classification helpers ----------

_DRAINAGE_COMPONENT_KEYWORDS = frozenset({"drain", "pipe", "trap", "sewer", "gully"})

_FIRE_COMPONENT_KEYWORDS = frozenset({"fire", "escape", "smoke", "sprinkler"})


def _is_drainage_component_type(component_type: str) -> bool:
    ct = component_type.lower()
    return any(kw in ct for kw in _DRAINAGE_COMPONENT_KEYWORDS)


def _is_fire_component_type(component_type: str) -> bool:
    ct = component_type.lower()
    return any(kw in ct for kw in _FIRE_COMPONENT_KEYWORDS)


# ============================================================
# P0 CHECKS — hard violation triggers entire building resample
# ============================================================


@register_p0_check
def _check_C001_GRAPH_NO_CYCLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C001: component parent_component_id 圖不得有環（DFS）."""
    parent_map: Dict[str, Optional[str]] = {
        c.component_id: c.parent_component_id for c in world_bundle.components
    }
    reported: Set[str] = set()
    violations: List[Violation] = []
    for start in parent_map:
        visited: Set[str] = set()
        current: Optional[str] = start
        while current is not None:
            if current in visited:
                if current not in reported:
                    reported.add(current)
                    violations.append(
                        Violation(
                            check_id="C001_GRAPH_NO_CYCLE",
                            priority="P0",
                            detail=f"Cycle detected involving component {current!r}",
                        )
                    )
                break
            visited.add(current)
            current = parent_map.get(current)
    return violations


@register_p0_check
def _check_C002_COMPONENT_LOCATION_EXISTS(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C002: component.location_id 必須解析到已知 location."""
    location_ids = {loc.location_id for loc in world_bundle.locations}
    violations: List[Violation] = []
    for component in world_bundle.components:
        if component.location_id not in location_ids:
            violations.append(
                Violation(
                    check_id="C002_COMPONENT_LOCATION_EXISTS",
                    priority="P0",
                    detail=(
                        f"Component {component.component_id!r} references"
                        f" unknown location {component.location_id!r}"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C003_FRAGMENT_COMPONENT_EXISTS(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C003: fragment.component_id 必須引用 bundle 中存在的 ComponentNode.

    W0-004 step 6 (2026-05-21)：spec 04 §7 FragmentContext reference-based contract 用
    `component_id` 主键直接引用 component；旧 denorm 字段 `component_type_id` 已撤出 W0
    contract，按 spec 06 §0.1 reference 反查路径 `fragment.component_id → ComponentNode.component_type`
    判定 component_type 存在性.
    """
    component_ids = {c.component_id for c in world_bundle.components}
    violations: List[Violation] = []
    for fragment in world_bundle.fragments:
        if fragment.component_id not in component_ids:
            violations.append(
                Violation(
                    check_id="C003_FRAGMENT_COMPONENT_EXISTS",
                    priority="P0",
                    detail=(
                        f"Fragment {fragment.fragment_id!r} component_id"
                        f" {fragment.component_id!r} has no matching component"
                    ),
                    fragment_id=fragment.fragment_id,
                )
            )
    return violations


@register_p0_check
def _check_C004_MATERIAL_COMPATIBLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C004: component.material_system 必須在 component_type_registry.material_compatibility."""
    component_type_index = _registry_index(
        registries, "component_type_registry", "component_type"
    )
    violations: List[Violation] = []
    for component in world_bundle.components:
        record = component_type_index.get(component.component_type)
        if record is None:
            continue  # unknown type — C003 負責
        compatibility: List[str] = record.get("material_compatibility") or []
        if compatibility and component.material_system not in compatibility:
            violations.append(
                Violation(
                    check_id="C004_MATERIAL_COMPATIBLE",
                    priority="P0",
                    detail=(
                        f"Component {component.component_id!r} material"
                        f" {component.material_system!r} not in {compatibility}"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C005_MECHANISM_COMPATIBLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C005: mechanism.mechanism_family 必須在對應 fragment 組件 allowed_mechanisms.

    W0-004 step 6 (2026-05-21)：按 spec 06 §0.1 reference 反查路径 `fragment.component_id →
    ComponentNode.component_type` 取 component type（旧 denorm 字段 `component_type_id` 已撤出
    W0 contract）.
    """
    component_type_index = _registry_index(
        registries, "component_type_registry", "component_type"
    )
    fragment_by_id = {f.fragment_id: f for f in world_bundle.fragments}
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for mechanism in world_bundle.mechanisms:
        fragment = fragment_by_id.get(mechanism.fragment_id)
        if fragment is None:
            continue
        component = component_by_id.get(fragment.component_id)
        if component is None:
            continue
        record = component_type_index.get(component.component_type)
        if record is None:
            continue
        allowed: List[str] = record.get("allowed_mechanisms") or []
        if allowed and mechanism.mechanism_family not in allowed:
            violations.append(
                Violation(
                    check_id="C005_MECHANISM_COMPATIBLE",
                    priority="P0",
                    detail=(
                        f"Mechanism {mechanism.mechanism_state_id!r} family"
                        f" {mechanism.mechanism_family!r} not allowed"
                        f" for component_type {component.component_type!r}"
                    ),
                    fragment_id=mechanism.fragment_id,
                )
            )
    return violations


@register_p0_check
def _check_C006_CONDITION_COMPATIBLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C006: condition_class 必須在 defect_condition_taxonomy_registry.compatible_components.

    W0-004 step 6 (2026-05-21)：按 spec 06 §0.1 reference 反查路径 `fragment.component_id →
    ComponentNode.component_type` 取 component type.
    """
    defect_index = _registry_index(
        registries, "defect_condition_taxonomy_registry", "condition_class"
    )
    fragment_by_id = {f.fragment_id: f for f in world_bundle.fragments}
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for condition in world_bundle.conditions:
        record = defect_index.get(condition.condition_class)
        if record is None:
            continue  # 無約束定義，跳過
        compatible: List[str] = record.get("compatible_components") or []
        if not compatible:
            continue
        fragment = fragment_by_id.get(condition.fragment_id)
        if fragment is None:
            continue
        component = component_by_id.get(fragment.component_id)
        if component is None:
            continue
        if component.component_type not in compatible:
            violations.append(
                Violation(
                    check_id="C006_CONDITION_COMPATIBLE",
                    priority="P0",
                    detail=(
                        f"Condition {condition.condition_id!r} class"
                        f" {condition.condition_class!r} incompatible with"
                        f" component_type {component.component_type!r}"
                    ),
                    fragment_id=condition.fragment_id,
                )
            )
    return violations


@register_p0_check
def _check_C009_REBAR_EXPOSURE_REQUIRES_REBAR(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C009: 鋼筋外露條件需要對應 ComponentNode 支持鋼筋（material_system 支持 RC，cover_depth_mm 非 null）.

    W0-004 step 6 (2026-05-21)：按 spec 06 §0.1 reference 反查路径
    `has_rebar = (lookup_component(fragment.component_id).material_system in RC) or (cover_depth_mm is not null)`
    判定（旧 denorm 字段 `has_rebar` 已撤出 W0 contract）.
    """
    _REBAR_CONDITION_CLASSES = frozenset({"DC_SPALL_REBAR", "DC_REBAR_EXPOSED"})
    fragment_by_id = {f.fragment_id: f for f in world_bundle.fragments}
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for condition in world_bundle.conditions:
        if condition.condition_class not in _REBAR_CONDITION_CLASSES:
            continue
        fragment = fragment_by_id.get(condition.fragment_id)
        if fragment is None:
            continue
        component = component_by_id.get(fragment.component_id)
        if component is None:
            continue
        # has_rebar derive：spec 06 §0.1 reference 反查路径——cover_depth_mm 非 null 即 RC 材质
        # 且 cover 已派生（spec 04 §5 contract：`material_system == reinforced_concrete` 时
        # cover_depth_mm 必非 null）.
        has_rebar = component.cover_depth_mm is not None
        if not has_rebar:
            violations.append(
                Violation(
                    check_id="C009_REBAR_EXPOSURE_REQUIRES_REBAR",
                    priority="P0",
                    detail=(
                        f"Condition {condition.condition_id!r} is rebar exposure"
                        f" but fragment {fragment.fragment_id!r} component"
                        f" {component.component_id!r} has no rebar (material_system="
                        f"{component.material_system!r}, cover_depth_mm=None)"
                    ),
                    fragment_id=fragment.fragment_id,
                )
            )
    return violations


@register_p0_check
def _check_C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C010: DrainageState.component_id 必須引用排水類組件."""
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for ds in world_bundle.drainage_states:
        component = component_by_id.get(ds.component_id)
        if component is None:
            violations.append(
                Violation(
                    check_id="C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT",
                    priority="P0",
                    detail=(
                        f"DrainageState {ds.drainage_id!r} references"
                        f" unknown component {ds.component_id!r}"
                    ),
                )
            )
            continue
        if not _is_drainage_component_type(component.component_type):
            violations.append(
                Violation(
                    check_id="C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT",
                    priority="P0",
                    detail=(
                        f"DrainageState {ds.drainage_id!r} on"
                        f" non-drainage component {component.component_type!r}"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C011_FIRE_ONLY_ON_FIRE_COMPONENT(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C011: FireSafetyState.component_id 必須引用消防類組件."""
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for fss in world_bundle.fire_safety_states:
        component = component_by_id.get(fss.component_id)
        if component is None:
            violations.append(
                Violation(
                    check_id="C011_FIRE_ONLY_ON_FIRE_COMPONENT",
                    priority="P0",
                    detail=(
                        f"FireSafetyState {fss.fire_state_id!r} references"
                        f" unknown component {fss.component_id!r}"
                    ),
                )
            )
            continue
        if not _is_fire_component_type(component.component_type):
            violations.append(
                Violation(
                    check_id="C011_FIRE_ONLY_ON_FIRE_COMPONENT",
                    priority="P0",
                    detail=(
                        f"FireSafetyState {fss.fire_state_id!r} on"
                        f" non-fire component {component.component_type!r}"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C012_UBW_CARRIER_COMPATIBLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C012: UBWState.component_id（若非空）必須解析到已知 component."""
    component_by_id = {c.component_id: c for c in world_bundle.components}
    violations: List[Violation] = []
    for ubw in world_bundle.ubw_states:
        if ubw.component_id and ubw.component_id not in component_by_id:
            violations.append(
                Violation(
                    check_id="C012_UBW_CARRIER_COMPATIBLE",
                    priority="P0",
                    detail=(
                        f"UBWState {ubw.ubw_id!r} references"
                        f" unknown carrier component {ubw.component_id!r}"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C015_TECH_METHOD_COMPATIBLE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C015: technical_validation measurement 必須有 method_class."""
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family == "technical_validation_measurement":
            if not meas.method_class:
                violations.append(
                    Violation(
                        check_id="C015_TECH_METHOD_COMPATIBLE",
                        priority="P0",
                        detail=(
                            f"Measurement {meas.measurement_id!r} is"
                            " technical_validation but has no method_class"
                        ),
                    )
                )
    return violations


@register_p0_check
def _check_C016_DERIVATION_REFS_NONEMPTY(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C016: measurement.derivation_refs 不得為空."""
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if not meas.derivation_refs:
            violations.append(
                Violation(
                    check_id="C016_DERIVATION_REFS_NONEMPTY",
                    priority="P0",
                    detail=f"Measurement {meas.measurement_id!r} has empty derivation_refs",
                )
            )
    return violations


@register_p0_check
def _check_C017_GEOMETRY_MEAS_FROM_CONDITION(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C017: defect_geometry_measurement.target_ref 必須解析到 condition_id."""
    condition_ids = {c.condition_id for c in world_bundle.conditions}
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family == "defect_geometry_measurement":
            if meas.target_ref not in condition_ids:
                violations.append(
                    Violation(
                        check_id="C017_GEOMETRY_MEAS_FROM_CONDITION",
                        priority="P0",
                        detail=(
                            f"Measurement {meas.measurement_id!r} defect_geometry"
                            f" target_ref {meas.target_ref!r} not in conditions"
                        ),
                    )
                )
    return violations


@register_p0_check
def _check_C018_COVERAGE_MEAS_FROM_COVERAGE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C018: coverage_sampling_measurement.target_ref 必須解析到 fragment_id 或 coverage_id."""
    fragment_ids = {f.fragment_id for f in world_bundle.fragments}
    coverage_ids = {cr.coverage_id for cr in world_bundle.coverage_relations}
    valid_targets = fragment_ids | coverage_ids
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family == "coverage_sampling_measurement":
            if meas.target_ref not in valid_targets:
                violations.append(
                    Violation(
                        check_id="C018_COVERAGE_MEAS_FROM_COVERAGE",
                        priority="P0",
                        detail=(
                            f"Measurement {meas.measurement_id!r} coverage_sampling"
                            f" target_ref {meas.target_ref!r} not in fragments/coverages"
                        ),
                    )
                )
    return violations


@register_p0_check
def _check_C019_TECH_MEAS_FROM_TEST_REPAIR(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C019: technical_validation_measurement.target_ref 必須解析到 fragment_id 或 repair_assessment_id."""
    fragment_ids = {f.fragment_id for f in world_bundle.fragments}
    repair_ids = {
        r.repair_assessment_id for r in world_bundle.repair_assessment_states
    }
    valid_targets = fragment_ids | repair_ids
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family == "technical_validation_measurement":
            if meas.target_ref not in valid_targets:
                violations.append(
                    Violation(
                        check_id="C019_TECH_MEAS_FROM_TEST_REPAIR",
                        priority="P0",
                        detail=(
                            f"Measurement {meas.measurement_id!r} technical_validation"
                            f" target_ref {meas.target_ref!r} not in fragments/repair_assessments"
                        ),
                    )
                )
    return violations


@register_p0_check
def _check_C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C020: structural_assessment_measurement.target_ref 必須解析到已知 fragment_id."""
    fragment_ids = {f.fragment_id for f in world_bundle.fragments}
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family == "structural_assessment_measurement":
            # BC-1 fix (2026-05-23)：去掉 `meas.target_ref and` 短路 guard——
            # 空 target_ref 无法解析到已知 fragment_id，按 spec 07 §C020
            # "必须解析到已知 fragment_id" 应判 P0 违规（与 C017 空串自然落入违规一致）。
            if meas.target_ref not in fragment_ids:
                violations.append(
                    Violation(
                        check_id="C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT",
                        priority="P0",
                        detail=(
                            f"Measurement {meas.measurement_id!r} structural_assessment"
                            f" target_ref {meas.target_ref!r} not in fragments"
                        ),
                    )
                )
    return violations


# ---------- C027-C029 新增 P0 checks (2026-05-12, DEBT-030 B 组真缺) ----------


@register_p0_check
def _check_C027_FIRE_STATE_INTERNAL_CONSISTENCY(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C027: fire_safety_state 字段内部一致性 — deficiency_present=False 但 deficiency_class != 'not_applicable' → P0.

    spec 04 §5 P0 reject 行: 'deficiency_present=false but deficiency_class non-null'.
    fire_safety_state 字段内部一致性: 若 deficiency_present=False，则 deficiency_class 必须是 'not_applicable'。
    """
    violations: List[Violation] = []
    for fss in world_bundle.fire_safety_states:
        if fss.deficiency_present is False and fss.deficiency_class != "not_applicable":
            violations.append(
                Violation(
                    check_id="C027_FIRE_STATE_INTERNAL_CONSISTENCY",
                    priority="P0",
                    detail=(
                        f"FireSafetyState {fss.fire_state_id!r} has"
                        f" deficiency_present=False but deficiency_class={fss.deficiency_class!r}"
                        f" (must be 'not_applicable')"
                    ),
                )
            )
    return violations


@register_p0_check
def _check_C028_COVERAGE_VALUE_NONNEGATIVE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C028: coverage_sampling_measurement value_num 必須 ≥ 0 — 負值 P0 reject.

    spec 04 §6 P0 reject 行: 'negative area'. 严于 C013 P2 ratio bound（[0,1] advisory），
    负值是 P0 logic 错误（area / count / length 等都不该为负）。
    """
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family != "coverage_sampling_measurement":
            continue
        if meas.value_num is None:
            continue
        if meas.value_num < 0:
            violations.append(
                Violation(
                    check_id="C028_COVERAGE_VALUE_NONNEGATIVE",
                    priority="P0",
                    detail=(
                        f"Measurement {meas.measurement_id!r} coverage_sampling"
                        f" value_num={meas.value_num} is negative"
                    ),
                )
            )
    return violations


# ---------- C029 矛盾对扩展 helpers (2026-05-12, DEBT-030 B 组 C029 矛盾对 7 对完整闭环) ----------
#
# OutcomeFlagValue = Union[bool, Literal["not_applicable", "unknown"]] (constants.py L52).
# 派生 flag value 三态：True (bool) / False (bool) / "not_applicable" / "unknown" (str).
#
# 判定规则 (W0 spec 06 §11.X 7 对矛盾对推导依据)：
#   - `_flag_is_true(v)`        : 严格 True（不含 truthy 字符串；"unknown" / "not_applicable" 不算）
#   - `_flag_is_not_true(v)`    : 严格 False（用于 Pair 5/6/7 的 "repair_required=False" 一侧；
#                                  "unknown" / "not_applicable" 不算 — 仅 explicit False 才构成矛盾）


def _flag_is_true(value: Any) -> bool:
    """严格判定 OutcomeFlagValue 为 True。不含 "unknown" / "not_applicable" 字符串。"""
    return value is True


def _flag_is_explicit_false(value: Any) -> bool:
    """严格判定 OutcomeFlagValue 为 False。仅 explicit False 才算；
    "unknown" / "not_applicable" 不构成矛盾的一侧（无信息态）。
    """
    return value is False


# spec 06 §11.X 7 对矛盾对完整清单（dot-delimited flag keys per generator.py L3145-L3166 return dict）.
# 每对格式: (flag_key_A, predicate_A, flag_key_B, predicate_B, description)
#   - flag_key_X      — 在 condition.derived_outcomes.{X_flags} 里取的 dot-delimited key
#   - flag_key_X.0    — 子 dict 名 ("risk_flags" / "repair_flags" / "verification_flags")
#   - flag_key_X.1    — 该 dict 里的 key
#   - predicate_X     — _flag_is_true / _flag_is_explicit_false
#   - description     — 报告用文字描述（matches spec 06 §11.X 表格行）
#
# Pair 1 仍走 RepairAssessmentState state-level 路径（见上方独立 loop），保留现实现.
# Pair 2-7 走 condition.derived_outcomes per-condition 路径.
_CONDITION_LEVEL_CONTRADICTION_PAIRS = (
    # Pair 2: safe_until_next_cycle=True AND verification_test_failed=True
    (
        ("repair_flags", "repair.outcome.safe_until_next_cycle"),
        _flag_is_true,
        ("verification_flags", "verification.test.failed"),
        _flag_is_true,
        "safe_until_next_cycle=True AND verification_test_failed=True",
    ),
    # Pair 3: maintenance_pre_next_cycle_required=True AND risk_building_safety_emergency=True
    (
        ("repair_flags", "maintenance.pre_next_cycle.required"),
        _flag_is_true,
        ("risk_flags", "risk.building_safety.emergency"),
        _flag_is_true,
        "maintenance_pre_next_cycle_required=True AND risk_building_safety_emergency=True",
    ),
    # Pair 4: maintenance_pre_next_cycle_required=True AND risk_public_health_emergency=True
    (
        ("repair_flags", "maintenance.pre_next_cycle.required"),
        _flag_is_true,
        ("risk_flags", "risk.public_health.emergency"),
        _flag_is_true,
        "maintenance_pre_next_cycle_required=True AND risk_public_health_emergency=True",
    ),
    # Pair 5: repair_required=False AND risk_building_safety_emergency=True
    (
        ("repair_flags", "repair.required"),
        _flag_is_explicit_false,
        ("risk_flags", "risk.building_safety.emergency"),
        _flag_is_true,
        "repair_required=False AND risk_building_safety_emergency=True",
    ),
    # Pair 6: repair_required=False AND risk_public_danger_present=True
    (
        ("repair_flags", "repair.required"),
        _flag_is_explicit_false,
        ("risk_flags", "risk.public_danger.present"),
        _flag_is_true,
        "repair_required=False AND risk_public_danger_present=True",
    ),
    # Pair 7: repair_required=False AND verification_test_failed=True
    (
        ("repair_flags", "repair.required"),
        _flag_is_explicit_false,
        ("verification_flags", "verification.test.failed"),
        _flag_is_true,
        "repair_required=False AND verification_test_failed=True",
    ),
)


def _get_derived_flag(condition, dict_name: str, key: str) -> Any:
    """从 condition.derived_outcomes.{dict_name} 取 dot-delimited key.

    返回 None 表示 key 不存在；OutcomeFlagValue 本身可能是 bool 或 str ("not_applicable" / "unknown")。
    """
    derived = condition.derived_outcomes
    sub_dict = getattr(derived, dict_name, None)
    if sub_dict is None:
        return None
    return sub_dict.get(key)


@register_p0_check
def _check_C029_DERIVED_FLAG_NO_CONTRADICTION(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C029: 派生 flag 互斥 — spec 06 §11.X 7 对矛盾对（含义见该节）.

    spec 04 §9 P0 reject 行: 'contradictory flags impossible to repair'.

    Pair 1: repair_required=True AND safe_until_next_cycle=True （走 RepairAssessmentState state-level，
            因 RepairAssessmentState 字段在 W0 spec 04 §9 是 fragment-level 单 record）.
    Pair 2-7: 走 condition.derived_outcomes per-condition 路径（generator.py `_compute_derived_flags_for_condition`
              return dict 写入 condition.derived_outcomes）。同一 fragment 多 condition 各 condition 各自检查.

    OutcomeFlagValue = Union[bool, Literal["not_applicable", "unknown"]]：仅 explicit True / False 才构成
    矛盾的一侧；"not_applicable" / "unknown" (无信息态) 不算 (避免 false positive).
    """
    violations: List[Violation] = []

    # ----- Pair 1: RepairAssessmentState state-level (保留现实现) -----
    for repair in world_bundle.repair_assessment_states:
        if repair.repair_required and repair.safe_until_next_cycle:
            violations.append(
                Violation(
                    check_id="C029_DERIVED_FLAG_NO_CONTRADICTION",
                    priority="P0",
                    detail=(
                        f"RepairAssessmentState {repair.repair_assessment_id!r} has"
                        " contradictory flags: repair_required=True AND safe_until_next_cycle=True"
                    ),
                    fragment_id=repair.fragment_id,
                )
            )

    # ----- Pair 2-7: condition.derived_outcomes per-condition -----
    for condition in world_bundle.conditions:
        for (
            (dict_a, key_a),
            pred_a,
            (dict_b, key_b),
            pred_b,
            description,
        ) in _CONDITION_LEVEL_CONTRADICTION_PAIRS:
            val_a = _get_derived_flag(condition, dict_a, key_a)
            val_b = _get_derived_flag(condition, dict_b, key_b)
            if val_a is None or val_b is None:
                continue  # flag 未填，跳过（generator 没派生过 = 没办法判矛盾）
            if pred_a(val_a) and pred_b(val_b):
                violations.append(
                    Violation(
                        check_id="C029_DERIVED_FLAG_NO_CONTRADICTION",
                        priority="P0",
                        detail=(
                            f"Condition {condition.condition_id!r} has"
                            f" contradictory derived flags: {description}"
                        ),
                        fragment_id=condition.fragment_id,
                    )
                )

    return violations


# ============================================================
# P1 CHECKS — repairable (trigger repair pass before accept)
# ============================================================


@register_p1_check
def _check_C007_EXTENT_AREA_BOUND(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C007: condition.extent_area_m2 ≤ fragment.fragment_area_m2.

    W0-004 step 6 (2026-05-21)：spec 04 §7 FragmentContext 9 字段 contract 用 `fragment_area_m2`
    （旧 denorm 字段 `nominal_visible_area_m2` 已撤出 W0 contract）.
    """
    fragment_by_id = {f.fragment_id: f for f in world_bundle.fragments}
    violations: List[Violation] = []
    for condition in world_bundle.conditions:
        if condition.extent_area_m2 is None:
            continue
        fragment = fragment_by_id.get(condition.fragment_id)
        if fragment is None:
            continue
        if condition.extent_area_m2 > fragment.fragment_area_m2:
            violations.append(
                Violation(
                    check_id="C007_EXTENT_AREA_BOUND",
                    priority="P1",
                    detail=(
                        f"{condition.condition_id}:{fragment.fragment_area_m2}"
                    ),
                    fragment_id=condition.fragment_id,
                )
            )
    return violations


@register_p1_check
def _check_C008_EXTENT_LENGTH_BOUND(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C008: condition.extent_length_m ≤ fragment.fragment_length_m.

    W0-004 step 6 (2026-05-21)：spec 04 §7 FragmentContext 9 字段 contract 用 `fragment_length_m`
    （旧 denorm 字段 `nominal_length_m` 已撤出 W0 contract）；fragment_length_m 可为 null
    （spec 04 §7 #7），按 "上限缺失则跳过" 处理.
    """
    fragment_by_id = {f.fragment_id: f for f in world_bundle.fragments}
    violations: List[Violation] = []
    for condition in world_bundle.conditions:
        if condition.extent_length_m is None:
            continue
        fragment = fragment_by_id.get(condition.fragment_id)
        if fragment is None:
            continue
        if fragment.fragment_length_m is None:
            continue
        if condition.extent_length_m > fragment.fragment_length_m:
            violations.append(
                Violation(
                    check_id="C008_EXTENT_LENGTH_BOUND",
                    priority="P1",
                    detail=f"{condition.condition_id}:{fragment.fragment_length_m}",
                    fragment_id=condition.fragment_id,
                )
            )
    return violations


@register_p1_check
def _check_C021_REPAIR_REQUIRED_CONSISTENCY(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C021: severe/emergency condition → 對應 repair_assessment_state.repair_required=True."""
    _TRIGGER_BANDS = frozenset({"severe", "emergency"})
    repair_by_fragment = {r.fragment_id: r for r in world_bundle.repair_assessment_states}
    violations: List[Violation] = []
    for condition in world_bundle.conditions:
        if condition.severity_band not in _TRIGGER_BANDS:
            continue
        repair = repair_by_fragment.get(condition.fragment_id)
        if repair is None:
            continue
        if not repair.repair_required:
            violations.append(
                Violation(
                    check_id="C021_REPAIR_REQUIRED_CONSISTENCY",
                    priority="P1",
                    detail=repair.repair_assessment_id,
                    fragment_id=condition.fragment_id,
                )
            )
    return violations


@register_p1_check
def _check_C022_VERIFICATION_FAIL_CONSISTENCY(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C022: value_bool=False 的 technical_validation measurement → verification_failed=True."""
    repair_by_fragment = {r.fragment_id: r for r in world_bundle.repair_assessment_states}
    # Collect fragment_ids that have at least one failing technical validation measurement
    failing_fragment_ids: Set[str] = set()
    for meas in world_bundle.measurements:
        if meas.measurement_family != "technical_validation_measurement":
            continue
        if meas.value_bool is False:
            failing_fragment_ids.add(meas.target_ref)
    violations: List[Violation] = []
    for fragment_id in failing_fragment_ids:
        repair = repair_by_fragment.get(fragment_id)
        if repair is None:
            continue
        if not repair.verification_failed:
            violations.append(
                Violation(
                    check_id="C022_VERIFICATION_FAIL_CONSISTENCY",
                    priority="P1",
                    detail=repair.repair_assessment_id,
                    fragment_id=fragment_id,
                )
            )
    return violations


# ============================================================
# P2 CHECKS — advisory warnings (do not block acceptance)
# ============================================================


@register_p2_check
def _check_C013_RATIO_BOUND(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C013: coverage_sampling_measurement.value_num 必須在 [0, 1]."""
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if meas.measurement_family != "coverage_sampling_measurement":
            continue
        if meas.value_num is not None and not (0.0 <= meas.value_num <= 1.0):
            violations.append(
                Violation(
                    check_id="C013_RATIO_BOUND",
                    priority="P2",
                    detail=(
                        f"Measurement {meas.measurement_id!r}"
                        f" ratio value {meas.value_num} out of [0,1]"
                    ),
                )
            )
    return violations


@register_p2_check
def _check_C014_COUNT_NONNEGATIVE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C014: slot_id 含 "count" 的 measurement value_num 必須 ≥ 0 且為整數."""
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if "count" not in meas.slot_id:
            continue
        if meas.value_num is None:
            continue
        if meas.value_num < 0:
            violations.append(
                Violation(
                    check_id="C014_COUNT_NONNEGATIVE",
                    priority="P2",
                    detail=(
                        f"Measurement {meas.measurement_id!r}"
                        f" count value {meas.value_num} is negative"
                    ),
                )
            )
        elif meas.value_num != round(meas.value_num):
            violations.append(
                Violation(
                    check_id="C014_COUNT_NONNEGATIVE",
                    priority="P2",
                    detail=(
                        f"Measurement {meas.measurement_id!r}"
                        f" count value {meas.value_num} is not an integer"
                    ),
                )
            )
    return violations


# ---------- C030-C031 P2 checks (2026-05-12, DEBT-030 B 组半缺补) ----------


def _is_area_measurement(meas) -> bool:
    """area-性 measurement 判定：slot_id 含 "area" 或 unit == "m2" (或别名)."""
    slot_lower = (meas.slot_id or "").lower()
    unit_lower = (meas.unit or "").lower()
    if "area" in slot_lower:
        return True
    # m2 / m^2 / sq_m 等 area unit 别名
    if unit_lower in {"m2", "m^2", "sq_m", "square_meter", "square_meters"}:
        return True
    return False


def _is_length_measurement(meas) -> bool:
    """length-性 measurement 判定：slot_id 含 "length" 或 unit 是 length（非 area） unit.

    注意：必须先排除 area unit "m2"，免得跟 C030 重复触发。
    """
    slot_lower = (meas.slot_id or "").lower()
    unit_lower = (meas.unit or "").lower()
    if "length" in slot_lower:
        return True
    # 纯 length unit（不含 m2 / m^2）
    if unit_lower in {"m", "meter", "meters", "mm", "millimeter", "millimeters", "cm"}:
        return True
    return False


@register_p2_check
def _check_C030_AREA_NONNEGATIVE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C030: area-性 measurement value_num 必須 ≥ 0 (P2 advisory / clamp).

    spec 07 §2.3 Measurement-level "area `≥ 0`". 严于 C028 P0 negative coverage area 的"alarm 但不阻塞"层；
    跨 measurement_family 都验（不只 coverage_sampling），slot_id 含 "area" 或 unit 是 m2 触发。
    """
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if not _is_area_measurement(meas):
            continue
        if meas.value_num is None:
            continue
        if meas.value_num < 0:
            violations.append(
                Violation(
                    check_id="C030_AREA_NONNEGATIVE",
                    priority="P2",
                    detail=(
                        f"Measurement {meas.measurement_id!r}"
                        f" area value {meas.value_num} (slot={meas.slot_id!r}, unit={meas.unit!r})"
                        f" is negative"
                    ),
                )
            )
    return violations


@register_p2_check
def _check_C031_LENGTH_NONNEGATIVE(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C031: length-性 measurement value_num 必須 ≥ 0 (P2 advisory / clamp).

    spec 07 §2.3 Measurement-level "length `≥ 0`". 跨 measurement_family 都验，
    slot_id 含 "length" 或 unit 是 m / mm / cm 触发。area unit (m2) 不进 C031 (走 C030)。
    """
    violations: List[Violation] = []
    for meas in world_bundle.measurements:
        if not _is_length_measurement(meas):
            continue
        # 排除 area-性（如 slot_id 同时含 length 和 area）避免与 C030 重复
        if _is_area_measurement(meas):
            continue
        if meas.value_num is None:
            continue
        if meas.value_num < 0:
            violations.append(
                Violation(
                    check_id="C031_LENGTH_NONNEGATIVE",
                    priority="P2",
                    detail=(
                        f"Measurement {meas.measurement_id!r}"
                        f" length value {meas.value_num} (slot={meas.slot_id!r}, unit={meas.unit!r})"
                        f" is negative"
                    ),
                )
            )
    return violations


# ---------- C032 P0 meta-audit (2026-05-12, DEBT-030 B 组半缺补) ----------


# Registry-to-registry FK descriptors per W0 spec 03 §3 跨表引用清单.
# 仅列既有 C 编号未专门覆盖的 FK（C002-C020 已专门验的不入此列表，避免重复报）.
#
# Format: (ref_registry, ref_field, target_registry, target_key_field, is_list)
#   ref_registry          — 引用方 registry_id
#   ref_field             — 引用方 record 中存外键的字段名
#   target_registry       — 被引用方 registry_id
#   target_key_field      — 被引用方 primary_key field name
#   is_list               — True 表示 ref_field 是 list[FK]；False 表示单值 FK
_CROSS_REGISTRY_FK_DESCRIPTORS = (
    # component_type_registry.allowed_location_classes → location_class_registry.location_class
    ("component_type_registry", "allowed_location_classes", "location_class_registry", "location_class", True),
    # fragment_template_registry.allowed_driver_profiles → latent_driver_registry.driver_profile_id
    ("fragment_template_registry", "allowed_driver_profiles", "latent_driver_registry", "driver_profile_id", True),
    # fragment_template_registry.allowed_mechanisms → mechanism_library_registry.mechanism_family
    ("fragment_template_registry", "allowed_mechanisms", "mechanism_library_registry", "mechanism_family", True),
    # coverage_relation_registry.ratio_slot_id → technical_measurement_registry.slot_id
    ("coverage_relation_registry", "ratio_slot_id", "technical_measurement_registry", "slot_id", False),
    # defect_condition_taxonomy_registry.default_measurement_slots → technical_measurement_registry.slot_id
    ("defect_condition_taxonomy_registry", "default_measurement_slots", "technical_measurement_registry", "slot_id", True),
    # mechanism_library_registry.output_condition_classes → defect_condition_taxonomy_registry.condition_class
    ("mechanism_library_registry", "output_condition_classes", "defect_condition_taxonomy_registry", "condition_class", True),
    # sampling_plan_registry.target_slot_ids → technical_measurement_registry.slot_id
    ("sampling_plan_registry", "target_slot_ids", "technical_measurement_registry", "slot_id", True),
    # verification_test_registry.required_measurements → technical_measurement_registry.slot_id
    ("verification_test_registry", "required_measurements", "technical_measurement_registry", "slot_id", True),
    # assessment_surrogate_registry.input_slots → technical_measurement_registry.slot_id
    ("assessment_surrogate_registry", "input_slots", "technical_measurement_registry", "slot_id", True),
    # assessment_surrogate_registry.output_slots → technical_measurement_registry.slot_id
    ("assessment_surrogate_registry", "output_slots", "technical_measurement_registry", "slot_id", True),
    # risk_derivation_registry.input_condition_classes → defect_condition_taxonomy_registry.condition_class
    ("risk_derivation_registry", "input_condition_classes", "defect_condition_taxonomy_registry", "condition_class", True),
    # risk_derivation_registry.input_measurement_slots → technical_measurement_registry.slot_id
    ("risk_derivation_registry", "input_measurement_slots", "technical_measurement_registry", "slot_id", True),
    # repair_outcome_registry.input_risk_flags → risk_derivation_registry.risk_flag_id
    ("repair_outcome_registry", "input_risk_flags", "risk_derivation_registry", "risk_flag_id", True),
    # sidecar_measurement_registry.carrier_slot → sidecar_ownership_registry.sidecar_slot_id
    ("sidecar_measurement_registry", "carrier_slot", "sidecar_ownership_registry", "sidecar_slot_id", False),
)


@register_p0_check
def _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(
    world_bundle: WorldBundle,
    registries: RegistryBundle,
) -> List[Violation]:
    """C032: registry-to-registry 跨表引用完整性 meta-audit.

    按 W0 spec 03 §3 跨表引用清单遍历 14 条 FK descriptor，不重复 C002-C020 已覆盖的
    world_bundle→registry FK，仅兜底 registry→registry 引用完整性。target 不存在则 P0 reject.
    """
    violations: List[Violation] = []
    # 缓存 target registry 的 key set
    target_keys_cache: Dict[str, Set[str]] = {}

    def _get_target_keys(target_registry: str, target_key_field: str) -> Set[str]:
        cache_key = f"{target_registry}.{target_key_field}"
        if cache_key not in target_keys_cache:
            target_table = None
            for t in registries.registries:
                if t.registry_id == target_registry:
                    target_table = t
                    break
            if target_table is None:
                target_keys_cache[cache_key] = set()
            else:
                target_keys_cache[cache_key] = {
                    rec[target_key_field]
                    for rec in target_table.records
                    if rec.get(target_key_field)
                }
        return target_keys_cache[cache_key]

    for (
        ref_registry,
        ref_field,
        target_registry,
        target_key_field,
        is_list,
    ) in _CROSS_REGISTRY_FK_DESCRIPTORS:
        # 找 ref registry table
        ref_table = None
        for t in registries.registries:
            if t.registry_id == ref_registry:
                ref_table = t
                break
        if ref_table is None:
            continue  # ref registry 没加载，跳过（不是 C032 的责任）
        # target registry 不存在 → 即便有 ref 也无法验，单独报一次
        target_keys = _get_target_keys(target_registry, target_key_field)
        for rec in ref_table.records:
            ref_value = rec.get(ref_field)
            if ref_value is None:
                continue
            # 取 ref record 的 primary_key（用 ref_table.key_field）
            ref_pk = rec.get(ref_table.key_field, "<unknown>")
            if is_list:
                if not isinstance(ref_value, (list, tuple)):
                    continue
                for fk in ref_value:
                    if fk and fk not in target_keys:
                        violations.append(
                            Violation(
                                check_id="C032_CROSS_REGISTRY_FOREIGN_KEY_META",
                                priority="P0",
                                detail=(
                                    f"{ref_registry}[{ref_pk!r}].{ref_field}={fk!r}"
                                    f" not found in {target_registry}.{target_key_field}"
                                ),
                            )
                        )
            else:
                if ref_value not in target_keys:
                    violations.append(
                        Violation(
                            check_id="C032_CROSS_REGISTRY_FOREIGN_KEY_META",
                            priority="P0",
                            detail=(
                                f"{ref_registry}[{ref_pk!r}].{ref_field}={ref_value!r}"
                                f" not found in {target_registry}.{target_key_field}"
                            ),
                        )
                    )
    return violations


# ============================================================
# P1 REPAIR — pure function, returns new WorldBundle
# ============================================================


@register_p1_repair
def _repair_p1_extents_and_flags(
    wb: WorldBundle,
    violations: List[Violation],
) -> Tuple[WorldBundle, List[RepairAction]]:
    """Repair C007 / C008 / C021 / C022 P1 violations (spec 07 §1 repair pass).

    - C007: clamp condition.extent_area_m2 ≤ fragment.fragment_area_m2
    - C008: clamp condition.extent_length_m ≤ fragment.fragment_length_m
    - C021: set repair_assessment_state.repair_required = True
    - C022: set repair_assessment_state.verification_failed = True

    W0-004 step 6 (2026-05-21)：clamp 上界改用 spec 04 §7 FragmentContext 9 字段 contract
    （fragment_area_m2 / fragment_length_m）；旧 denorm 字段（nominal_visible_area_m2 /
    nominal_length_m）已撤出 W0 contract.
    DEBT-030 C 组 / spec 07 §4 line 68：返回 (new_bundle, repair_actions)；每条修复都登 audit
    trace。"不允许 silent 修复" — repair_actions 里 before/after value 用于事后核对.
    """
    _HANDLED = frozenset(
        {
            "C007_EXTENT_AREA_BOUND",
            "C008_EXTENT_LENGTH_BOUND",
            "C021_REPAIR_REQUIRED_CONSISTENCY",
            "C022_VERIFICATION_FAIL_CONSISTENCY",
        }
    )
    if not any(v.check_id in _HANDLED for v in violations):
        return wb, []

    repaired = wb.model_copy(deep=True)
    actions: List[RepairAction] = []

    fragment_by_id = {f.fragment_id: f for f in repaired.fragments}

    c007_frags = {v.fragment_id for v in violations if v.check_id == "C007_EXTENT_AREA_BOUND" and v.fragment_id}
    c008_frags = {v.fragment_id for v in violations if v.check_id == "C008_EXTENT_LENGTH_BOUND" and v.fragment_id}
    c021_frags = {v.fragment_id for v in violations if v.check_id == "C021_REPAIR_REQUIRED_CONSISTENCY" and v.fragment_id}
    c022_frags = {v.fragment_id for v in violations if v.check_id == "C022_VERIFICATION_FAIL_CONSISTENCY" and v.fragment_id}

    for condition in repaired.conditions:
        fragment = fragment_by_id.get(condition.fragment_id)
        if fragment is None:
            continue
        if condition.fragment_id in c007_frags and condition.extent_area_m2 is not None:
            before_value = condition.extent_area_m2
            clamped = min(before_value, fragment.fragment_area_m2)
            if clamped != before_value:
                condition.extent_area_m2 = clamped
                actions.append(
                    RepairAction(
                        check_id="C007_EXTENT_AREA_BOUND",
                        fragment_id=condition.fragment_id,
                        detail="clamp extent_area_m2 to fragment.fragment_area_m2",
                        before_value=before_value,
                        after_value=clamped,
                    )
                )
        if (
            condition.fragment_id in c008_frags
            and condition.extent_length_m is not None
            and fragment.fragment_length_m is not None
        ):
            before_value = condition.extent_length_m
            clamped = min(before_value, fragment.fragment_length_m)
            if clamped != before_value:
                condition.extent_length_m = clamped
                actions.append(
                    RepairAction(
                        check_id="C008_EXTENT_LENGTH_BOUND",
                        fragment_id=condition.fragment_id,
                        detail="clamp extent_length_m to fragment.fragment_length_m",
                        before_value=before_value,
                        after_value=clamped,
                    )
                )

    for repair in repaired.repair_assessment_states:
        if repair.fragment_id in c021_frags and not repair.repair_required:
            before_value = repair.repair_required
            repair.repair_required = True
            actions.append(
                RepairAction(
                    check_id="C021_REPAIR_REQUIRED_CONSISTENCY",
                    fragment_id=repair.fragment_id,
                    detail="set repair_assessment_state.repair_required = True",
                    before_value=before_value,
                    after_value=True,
                )
            )
        if repair.fragment_id in c022_frags and not repair.verification_failed:
            before_value = repair.verification_failed
            repair.verification_failed = True
            actions.append(
                RepairAction(
                    check_id="C022_VERIFICATION_FAIL_CONSISTENCY",
                    fragment_id=repair.fragment_id,
                    detail="set repair_assessment_state.verification_failed = True",
                    before_value=before_value,
                    after_value=True,
                )
            )

    return repaired, actions
