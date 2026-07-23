"""Unit tests for C001-C022 worldgen gate check functions (T-22).

Each of the 22 checks has at least one test.  Four additional tests cover
the P1 repair pass (_repair_p1_extents_and_flags).

Test isolation: each TestCase calls clear_check_registry() in setUp then
re-imports the checks module so that only the checks under test are registered.
For direct function tests we call the private check functions directly rather
than going through the gate machinery.
"""

from __future__ import annotations

import importlib
import unittest
from typing import Any, Dict, List

# Trigger registration (import-time side effect)
import workflow_engine.worldgen.checks  # noqa: F401

from workflow_engine.worldgen.checks import (
    _check_C001_GRAPH_NO_CYCLE,
    _check_C002_COMPONENT_LOCATION_EXISTS,
    _check_C003_FRAGMENT_COMPONENT_EXISTS,
    _check_C004_MATERIAL_COMPATIBLE,
    _check_C005_MECHANISM_COMPATIBLE,
    _check_C006_CONDITION_COMPATIBLE,
    _check_C007_EXTENT_AREA_BOUND,
    _check_C008_EXTENT_LENGTH_BOUND,
    _check_C009_REBAR_EXPOSURE_REQUIRES_REBAR,
    _check_C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT,
    _check_C011_FIRE_ONLY_ON_FIRE_COMPONENT,
    _check_C012_UBW_CARRIER_COMPATIBLE,
    _check_C013_RATIO_BOUND,
    _check_C014_COUNT_NONNEGATIVE,
    _check_C015_TECH_METHOD_COMPATIBLE,
    _check_C016_DERIVATION_REFS_NONEMPTY,
    _check_C017_GEOMETRY_MEAS_FROM_CONDITION,
    _check_C018_COVERAGE_MEAS_FROM_COVERAGE,
    _check_C019_TECH_MEAS_FROM_TEST_REPAIR,
    _check_C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT,
    _check_C021_REPAIR_REQUIRED_CONSISTENCY,
    _check_C022_VERIFICATION_FAIL_CONSISTENCY,
    _check_C027_FIRE_STATE_INTERNAL_CONSISTENCY,
    _check_C028_COVERAGE_VALUE_NONNEGATIVE,
    _check_C029_DERIVED_FLAG_NO_CONTRADICTION,
    _check_C030_AREA_NONNEGATIVE,
    _check_C031_LENGTH_NONNEGATIVE,
    _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META,
    _repair_p1_extents_and_flags,
)
from workflow_engine.worldgen.gates import Violation
from workflow_engine.worldgen.models import (
    BuildingContext,
    BuildingMetadata,
    ComponentNode,
    ConditionState,
    CoverageRelation,
    DrainageState,
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
    WorldBundle,
)


# ============================================================
# Test fixture helpers
# ============================================================


def _empty_registries() -> RegistryBundle:
    return RegistryBundle(generated_at="2025-01-01T00:00:00")


def _registries_with(
    registry_id: str,
    key_field: str,
    records: List[Dict[str, Any]],
) -> RegistryBundle:
    table = RegistryTable(
        registry_id=registry_id,
        ownership="worldgen",
        key_field=key_field,
        records=records,
    )
    return RegistryBundle(
        generated_at="2025-01-01T00:00:00",
        registries=[table],
    )


def _building() -> BuildingContext:
    # W0-008 (2026-05-21)：BuildingContext 收紧到 spec 04 §4 8 字段 contract；
    # building_template_id / building_name / unit_count 走 _building_internal_metadata.
    return BuildingContext(
        building_id="B001",
        building_use="residential",
        structure_type="rc_frame",
        age_years=30.0,
        storey_count=5,
        occupancy_state="occupied",
    )


def _building_internal_metadata() -> BuildingMetadata:
    return BuildingMetadata(
        building_template_id="T001",
        building_name="Test Building",
        unit_count=10,
    )


def _make_bundle(**kwargs) -> WorldBundle:
    return WorldBundle(
        world_id="WB-TEST001",
        building=_building(),
        building_metadata=_building_internal_metadata(),
        **kwargs,
    )


def _location(location_id: str = "L001") -> LocationNode:
    return LocationNode(
        location_id=location_id,
        location_class="external_wall",
        exposure_zone="marine",
        storey_band="mid_storey",
    )


def _component(
    component_id: str = "COMP001",
    component_type: str = "external_wall",
    location_id: str = "L001",
    parent_component_id: str | None = None,
    material_system: str = "rc_reinforced",
    structural_role: str = "load_bearing",
    access_class: str = "accessible",
    cover_depth_mm: float | None = 30.0,
) -> ComponentNode:
    # W0-004 step 6 (2026-05-21)：default cover_depth_mm=30.0 让 component 看似 RC（spec 04 §5
    # contract `material_system == reinforced_concrete` 时 cover_depth_mm 必非 null）；测试用
    # default 不强制 material_system 对齐，仅供 checks.py C009 `has_rebar` 派生使用.
    return ComponentNode(
        component_id=component_id,
        component_type=component_type,
        parent_component_id=parent_component_id,
        material_system=material_system,
        structural_role=structural_role,
        location_id=location_id,
        cover_depth_mm=cover_depth_mm,
        access_class=access_class,
    )


def _fragment(
    fragment_id: str = "FRAG001",
    component_id: str = "COMP001",
    location_id: str = "L001",
    fragment_area_m2: float = 10.0,
    fragment_length_m: float | None = 5.0,
) -> FragmentContext:
    """spec 04 §7 FragmentContext 9 字段 reference-based contract fixture helper.

    W0-002 (2026-05-21)：清理 legacy kwargs（component_type_id / has_rebar /
    nominal_visible_area_m2 / nominal_length_m）——旧字段已移到 ComponentNode /
    LocationNode（反查路径），fixture kwarg 接口收紧到 spec 9 字段；component_type /
    has_rebar / material_system 等物理参数走 _component fixture（spec 04 §5 ComponentNode）.
    """
    return FragmentContext(
        fragment_id=fragment_id,
        fragment_template_id="FT001",
        component_id=component_id,
        location_id=location_id,
        fragment_role="inspection_target",
        fragment_area_m2=fragment_area_m2,
        fragment_length_m=fragment_length_m,
        in_scope=True,
        exclusion_reason=None,
    )


def _mechanism(
    mechanism_state_id: str = "MS001",
    fragment_id: str = "FRAG001",
    mechanism_family: str = "structural_crack",
) -> MechanismState:
    return MechanismState(
        mechanism_state_id=mechanism_state_id,
        fragment_id=fragment_id,
        mechanism_family=mechanism_family,
        active=True,
        severity_index=0.5,
        primary_mechanism_id="PM001",
        activated_mechanisms=[
            MechanismActivation(
                mechanism_id="PM001",
                mechanism_family=mechanism_family,
                activation_score=0.5,
            )
        ],
    )


def _condition(
    condition_id: str = "COND001",
    fragment_id: str = "FRAG001",
    condition_class: str = "DC_CRACK",
    severity_band: str = "moderate",
    extent_area_m2: float | None = 3.0,
    extent_length_m: float | None = 2.0,
) -> ConditionState:
    return ConditionState(
        condition_id=condition_id,
        fragment_id=fragment_id,
        condition_class=condition_class,
        severity_band=severity_band,  # type: ignore[arg-type]
        extent_area_m2=extent_area_m2,
        extent_length_m=extent_length_m,
    )


def _repair_assessment(
    repair_assessment_id: str = "RA001",
    fragment_id: str = "FRAG001",
    repair_required: bool = False,
    verification_failed: bool = False,
) -> RepairAssessmentState:
    return RepairAssessmentState(
        repair_assessment_id=repair_assessment_id,
        fragment_id=fragment_id,
        repair_required=repair_required,
        verification_failed=verification_failed,
    )


def _measurement(
    measurement_id: str = "MEAS001",
    measurement_family: str = "defect_geometry_measurement",
    slot_id: str = "crack_width",
    target_ref: str = "COND001",
    derivation_refs: List[str] | None = None,
    value_num: float | None = 1.5,
    value_bool: bool | None = None,
    method_class: str | None = None,
    unit: str | None = None,
) -> MeasurementRecord:
    if derivation_refs is None:
        derivation_refs = [target_ref]
    return MeasurementRecord(
        measurement_id=measurement_id,
        target_ref=target_ref,
        measurement_family=measurement_family,  # type: ignore[arg-type]
        slot_id=slot_id,
        value_num=value_num,
        value_bool=value_bool,
        unit=unit,
        derivation_refs=derivation_refs,
        derivation_mode="damage_downstream",
        method_class=method_class,
    )


def _drainage_state(
    drainage_id: str = "DS001",
    component_id: str = "COMP001",
) -> DrainageState:
    return DrainageState(
        drainage_id=drainage_id,
        component_id=component_id,
    )


def _fire_state(
    fire_state_id: str = "FS001",
    component_id: str = "COMP001",
) -> FireSafetyState:
    return FireSafetyState(
        fire_state_id=fire_state_id,
        component_id=component_id,
    )


def _ubw_state(
    ubw_id: str = "UBW001",
    component_id: str = "COMP001",
) -> UBWState:
    return UBWState(
        ubw_id=ubw_id,
        component_id=component_id,
    )


# ============================================================
# C001 — Graph No Cycle
# ============================================================


class TestC001GraphNoCycle(unittest.TestCase):
    def _regs(self) -> RegistryBundle:
        return _empty_registries()

    def test_no_cycle_passes(self) -> None:
        # A → B → C (chain, no cycle)
        bundle = _make_bundle(
            components=[
                _component("A", parent_component_id=None),
                _component("B", parent_component_id="A"),
                _component("C", parent_component_id="B"),
            ]
        )
        violations = _check_C001_GRAPH_NO_CYCLE(bundle, self._regs())
        self.assertEqual(violations, [])

    def test_self_loop_detected(self) -> None:
        bundle = _make_bundle(
            components=[_component("A", parent_component_id="A")]
        )
        violations = _check_C001_GRAPH_NO_CYCLE(bundle, self._regs())
        self.assertTrue(any(v.check_id == "C001_GRAPH_NO_CYCLE" for v in violations))

    def test_two_node_cycle_detected(self) -> None:
        # A → B → A
        bundle = _make_bundle(
            components=[
                _component("A", parent_component_id="B"),
                _component("B", parent_component_id="A"),
            ]
        )
        violations = _check_C001_GRAPH_NO_CYCLE(bundle, self._regs())
        self.assertTrue(any(v.check_id == "C001_GRAPH_NO_CYCLE" for v in violations))


# ============================================================
# C002 — Component Location Exists
# ============================================================


class TestC002ComponentLocationExists(unittest.TestCase):
    def test_valid_location_passes(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", location_id="L001")],
        )
        vs = _check_C002_COMPONENT_LOCATION_EXISTS(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_missing_location_caught(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", location_id="L_MISSING")],
        )
        vs = _check_C002_COMPONENT_LOCATION_EXISTS(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C002_COMPONENT_LOCATION_EXISTS")
        self.assertEqual(vs[0].priority, "P0")


# ============================================================
# C003 — Fragment Component Exists
# ============================================================


class TestC003FragmentComponentExists(unittest.TestCase):
    def test_matching_type_passes(self) -> None:
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("FRAG001", component_id="COMP001")],
        )
        vs = _check_C003_FRAGMENT_COMPONENT_EXISTS(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_missing_type_caught(self) -> None:
        # W0-004 step 6 (2026-05-21)：C003 改为校验 `fragment.component_id` 引用存在性
        # （spec 04 §7 reference-based contract），原 `component_type_id` mismatch 的测试
        # 改为构造不存在的 component_id 触发 P0 reject.
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("FRAG001", component_id="COMP_MISSING")],
        )
        vs = _check_C003_FRAGMENT_COMPONENT_EXISTS(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C003_FRAGMENT_COMPONENT_EXISTS")
        self.assertEqual(vs[0].fragment_id, "FRAG001")


# ============================================================
# C004 — Material Compatible
# ============================================================


class TestC004MaterialCompatible(unittest.TestCase):
    def test_compatible_material_passes(self) -> None:
        regs = _registries_with(
            "component_type_registry",
            "component_type",
            [{"component_type": "external_wall", "material_compatibility": ["rc_reinforced"]}],
        )
        bundle = _make_bundle(
            components=[_component("C1", component_type="external_wall", material_system="rc_reinforced")],
        )
        vs = _check_C004_MATERIAL_COMPATIBLE(bundle, regs)
        self.assertEqual(vs, [])

    def test_incompatible_material_caught(self) -> None:
        regs = _registries_with(
            "component_type_registry",
            "component_type",
            [{"component_type": "external_wall", "material_compatibility": ["masonry"]}],
        )
        bundle = _make_bundle(
            components=[_component("C1", component_type="external_wall", material_system="rc_reinforced")],
        )
        vs = _check_C004_MATERIAL_COMPATIBLE(bundle, regs)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C004_MATERIAL_COMPATIBLE")

    def test_unknown_type_skipped(self) -> None:
        """Unknown component_type not in registry — C003 handles it; C004 skips."""
        bundle = _make_bundle(
            components=[_component("C1", component_type="unknown_type")],
        )
        vs = _check_C004_MATERIAL_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C005 — Mechanism Compatible
# ============================================================


class TestC005MechanismCompatible(unittest.TestCase):
    # W0-004 step 6 (2026-05-21)：component_type 走 `fragment.component_id → ComponentNode` 反查路径.
    def test_allowed_mechanism_passes(self) -> None:
        regs = _registries_with(
            "component_type_registry",
            "component_type",
            [{"component_type": "external_wall", "allowed_mechanisms": ["structural_crack"]}],
        )
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("F1", component_id="COMP001")],
            mechanisms=[_mechanism("MS1", fragment_id="F1", mechanism_family="structural_crack")],
        )
        vs = _check_C005_MECHANISM_COMPATIBLE(bundle, regs)
        self.assertEqual(vs, [])

    def test_disallowed_mechanism_caught(self) -> None:
        regs = _registries_with(
            "component_type_registry",
            "component_type",
            [{"component_type": "external_wall", "allowed_mechanisms": ["structural_crack"]}],
        )
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("F1", component_id="COMP001")],
            mechanisms=[_mechanism("MS1", fragment_id="F1", mechanism_family="drainage_fault")],
        )
        vs = _check_C005_MECHANISM_COMPATIBLE(bundle, regs)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C005_MECHANISM_COMPATIBLE")


# ============================================================
# C006 — Condition Compatible
# ============================================================


class TestC006ConditionCompatible(unittest.TestCase):
    # W0-004 step 6 (2026-05-21)：component_type 走 `fragment.component_id → ComponentNode` 反查路径.
    def test_compatible_condition_passes(self) -> None:
        regs = _registries_with(
            "defect_condition_taxonomy_registry",
            "condition_class",
            [{"condition_class": "DC_CRACK", "compatible_components": ["external_wall"]}],
        )
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("F1", component_id="COMP001")],
            conditions=[_condition("C1", fragment_id="F1", condition_class="DC_CRACK")],
        )
        vs = _check_C006_CONDITION_COMPATIBLE(bundle, regs)
        self.assertEqual(vs, [])

    def test_incompatible_condition_caught(self) -> None:
        regs = _registries_with(
            "defect_condition_taxonomy_registry",
            "condition_class",
            [{"condition_class": "DC_CRACK", "compatible_components": ["slab"]}],
        )
        bundle = _make_bundle(
            components=[_component("COMP001", component_type="external_wall")],
            fragments=[_fragment("F1", component_id="COMP001")],
            conditions=[_condition("C1", fragment_id="F1", condition_class="DC_CRACK")],
        )
        vs = _check_C006_CONDITION_COMPATIBLE(bundle, regs)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C006_CONDITION_COMPATIBLE")


# ============================================================
# C007 — Extent Area Bound (P1)
# ============================================================


class TestC007ExtentAreaBound(unittest.TestCase):
    def test_within_bound_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_area_m2=10.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_area_m2=5.0)],
        )
        vs = _check_C007_EXTENT_AREA_BOUND(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_exceeds_bound_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_area_m2=10.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_area_m2=15.0)],
        )
        vs = _check_C007_EXTENT_AREA_BOUND(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C007_EXTENT_AREA_BOUND")
        self.assertEqual(vs[0].priority, "P1")

    def test_none_extent_area_skipped(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_area_m2=10.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_area_m2=None)],
        )
        vs = _check_C007_EXTENT_AREA_BOUND(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C008 — Extent Length Bound (P1)
# ============================================================


class TestC008ExtentLengthBound(unittest.TestCase):
    def test_within_bound_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_length_m=5.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_length_m=3.0)],
        )
        vs = _check_C008_EXTENT_LENGTH_BOUND(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_exceeds_bound_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_length_m=5.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_length_m=8.0)],
        )
        vs = _check_C008_EXTENT_LENGTH_BOUND(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C008_EXTENT_LENGTH_BOUND")


# ============================================================
# C009 — Rebar Exposure Requires Rebar
# ============================================================


class TestC009RebarExposureRequiresRebar(unittest.TestCase):
    # W0-004 step 6 (2026-05-21)：C009 改用 `lookup_component(fragment.component_id).cover_depth_mm`
    # 判定 has_rebar；测试通过 _component(cover_depth_mm=...) 控制 RC / 非 RC 场景.
    def test_rebar_condition_with_rebar_passes(self) -> None:
        bundle = _make_bundle(
            components=[_component("COMP001", cover_depth_mm=30.0)],
            fragments=[_fragment("F1", component_id="COMP001")],
            conditions=[_condition("C1", fragment_id="F1", condition_class="DC_SPALL_REBAR")],
        )
        vs = _check_C009_REBAR_EXPOSURE_REQUIRES_REBAR(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_rebar_condition_without_rebar_caught(self) -> None:
        bundle = _make_bundle(
            components=[_component("COMP001", cover_depth_mm=None)],
            fragments=[_fragment("F1", component_id="COMP001")],
            conditions=[_condition("C1", fragment_id="F1", condition_class="DC_SPALL_REBAR")],
        )
        vs = _check_C009_REBAR_EXPOSURE_REQUIRES_REBAR(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C009_REBAR_EXPOSURE_REQUIRES_REBAR")

    def test_non_rebar_condition_ignores_has_rebar(self) -> None:
        bundle = _make_bundle(
            components=[_component("COMP001", cover_depth_mm=None)],
            fragments=[_fragment("F1", component_id="COMP001")],
            conditions=[_condition("C1", fragment_id="F1", condition_class="DC_CRACK")],
        )
        vs = _check_C009_REBAR_EXPOSURE_REQUIRES_REBAR(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C010 — Drainage Only on Drainage Component
# ============================================================


class TestC010DrainageOnlyOnDrainageComponent(unittest.TestCase):
    def test_drainage_component_passes(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", component_type="drainage_stack", location_id="L001")],
            drainage_states=[_drainage_state("DS1", component_id="COMP001")],
        )
        vs = _check_C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_non_drainage_component_caught(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", component_type="external_wall", location_id="L001")],
            drainage_states=[_drainage_state("DS1", component_id="COMP001")],
        )
        vs = _check_C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT")

    def test_unknown_component_caught(self) -> None:
        bundle = _make_bundle(
            drainage_states=[_drainage_state("DS1", component_id="NO_SUCH_COMPONENT")],
        )
        vs = _check_C010_DRAINAGE_ONLY_ON_DRAINAGE_COMPONENT(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)


# ============================================================
# C011 — Fire Only on Fire Component
# ============================================================


class TestC011FireOnlyOnFireComponent(unittest.TestCase):
    def test_fire_component_passes(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", component_type="fire_door", location_id="L001")],
            fire_safety_states=[_fire_state("FS1", component_id="COMP001")],
        )
        vs = _check_C011_FIRE_ONLY_ON_FIRE_COMPONENT(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_non_fire_component_caught(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", component_type="external_wall", location_id="L001")],
            fire_safety_states=[_fire_state("FS1", component_id="COMP001")],
        )
        vs = _check_C011_FIRE_ONLY_ON_FIRE_COMPONENT(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C011_FIRE_ONLY_ON_FIRE_COMPONENT")


# ============================================================
# C012 — UBW Carrier Compatible
# ============================================================


class TestC012UBWCarrierCompatible(unittest.TestCase):
    def test_known_carrier_passes(self) -> None:
        bundle = _make_bundle(
            locations=[_location("L001")],
            components=[_component("COMP001", location_id="L001")],
            ubw_states=[_ubw_state("UBW1", component_id="COMP001")],
        )
        vs = _check_C012_UBW_CARRIER_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_unknown_carrier_caught(self) -> None:
        bundle = _make_bundle(
            ubw_states=[_ubw_state("UBW1", component_id="NO_SUCH")],
        )
        vs = _check_C012_UBW_CARRIER_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C012_UBW_CARRIER_COMPATIBLE")

    def test_empty_component_id_skipped(self) -> None:
        bundle = _make_bundle(
            ubw_states=[_ubw_state("UBW1", component_id="")],
        )
        vs = _check_C012_UBW_CARRIER_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C013 — Ratio Bound (P2)
# ============================================================


class TestC013RatioBound(unittest.TestCase):
    def test_valid_ratio_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=0.75,
                )
            ],
        )
        vs = _check_C013_RATIO_BOUND(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_ratio_above_one_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=1.5,
                )
            ],
        )
        vs = _check_C013_RATIO_BOUND(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C013_RATIO_BOUND")
        self.assertEqual(vs[0].priority, "P2")

    def test_ratio_negative_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=-0.1,
                )
            ],
        )
        vs = _check_C013_RATIO_BOUND(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)


# ============================================================
# C014 — Count Non-negative (P2)
# ============================================================


class TestC014CountNonnegative(unittest.TestCase):
    def test_valid_count_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement("M1", slot_id="crack_count", value_num=5.0)
            ],
        )
        vs = _check_C014_COUNT_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_negative_count_caught(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement("M1", slot_id="defect_count", value_num=-1.0)
            ],
        )
        vs = _check_C014_COUNT_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C014_COUNT_NONNEGATIVE")
        self.assertEqual(vs[0].priority, "P2")

    def test_non_integer_count_caught(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement("M1", slot_id="crack_count", value_num=2.7)
            ],
        )
        vs = _check_C014_COUNT_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)


# ============================================================
# C015 — Tech Method Compatible
# ============================================================


class TestC015TechMethodCompatible(unittest.TestCase):
    def test_tech_with_method_class_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_num=None,
                    value_bool=True,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C015_TECH_METHOD_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_tech_without_method_class_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_bool=True,
                    value_num=None,
                    method_class=None,
                )
            ],
        )
        vs = _check_C015_TECH_METHOD_COMPATIBLE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C015_TECH_METHOD_COMPATIBLE")


# ============================================================
# C016 — Derivation Refs Nonempty
# ============================================================


class TestC016DerivationRefsNonempty(unittest.TestCase):
    def test_nonempty_refs_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement("M1", derivation_refs=["COND001"])
            ],
        )
        vs = _check_C016_DERIVATION_REFS_NONEMPTY(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_empty_refs_caught(self) -> None:
        # Build measurement then forcibly clear derivation_refs to simulate invalid state
        meas = _measurement("M1")
        meas.derivation_refs = []
        meas.upstream_refs = []
        meas.origin_chain_refs = []
        meas.derived_from_measurement_ids = []
        bundle = _make_bundle(measurements=[meas])
        vs = _check_C016_DERIVATION_REFS_NONEMPTY(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C016_DERIVATION_REFS_NONEMPTY")


# ============================================================
# C017 — Geometry Measurement from Condition
# ============================================================


class TestC017GeometryMeasFromCondition(unittest.TestCase):
    def test_valid_target_passes(self) -> None:
        bundle = _make_bundle(
            conditions=[_condition("COND001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="defect_geometry_measurement",
                    target_ref="COND001",
                )
            ],
        )
        vs = _check_C017_GEOMETRY_MEAS_FROM_CONDITION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_wrong_target_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[_condition("COND001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="defect_geometry_measurement",
                    target_ref="FRAG999",  # not a condition id
                )
            ],
        )
        vs = _check_C017_GEOMETRY_MEAS_FROM_CONDITION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C017_GEOMETRY_MEAS_FROM_CONDITION")


# ============================================================
# C018 — Coverage Measurement from Coverage Relation
# ============================================================


class TestC018CoverageMeasFromCoverage(unittest.TestCase):
    def test_fragment_target_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("FRAG001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="FRAG001",
                    value_num=0.5,
                )
            ],
        )
        vs = _check_C018_COVERAGE_MEAS_FROM_COVERAGE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_unknown_target_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("FRAG001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="UNKNOWN_TARGET",
                    value_num=0.5,
                )
            ],
        )
        vs = _check_C018_COVERAGE_MEAS_FROM_COVERAGE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C018_COVERAGE_MEAS_FROM_COVERAGE")


# ============================================================
# C019 — Tech Measurement from Test/Repair
# ============================================================


class TestC019TechMeasFromTestRepair(unittest.TestCase):
    def test_fragment_target_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("FRAG001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="FRAG001",
                    value_bool=True,
                    value_num=None,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C019_TECH_MEAS_FROM_TEST_REPAIR(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_unknown_target_caught(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="UNKNOWN_TARGET",
                    value_bool=True,
                    value_num=None,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C019_TECH_MEAS_FROM_TEST_REPAIR(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C019_TECH_MEAS_FROM_TEST_REPAIR")


# ============================================================
# C020 — Assessment from Structural Component
# ============================================================


class TestC020AssessmentFromStructuralComponent(unittest.TestCase):
    def test_known_fragment_target_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("FRAG001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="structural_assessment_measurement",
                    target_ref="FRAG001",
                )
            ],
        )
        vs = _check_C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_unknown_target_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="structural_assessment_measurement",
                    target_ref="UNKNOWN_FRAG",
                )
            ],
        )
        vs = _check_C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT")

    def test_empty_target_ref_caught(self) -> None:
        """BC-1 回归：空 target_ref 的 structural_assessment_measurement 无法解析到
        已知 fragment_id，须判 C020 P0 违规（不得被 `meas.target_ref and` 短路跳过）."""
        bundle = _make_bundle(
            fragments=[_fragment("FRAG001")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="structural_assessment_measurement",
                    target_ref="",
                )
            ],
        )
        vs = _check_C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C020_ASSESSMENT_FROM_STRUCTURAL_COMPONENT")


# ============================================================
# C021 — Repair Required Consistency (P1)
# ============================================================


class TestC021RepairRequiredConsistency(unittest.TestCase):
    def test_severe_condition_with_repair_required_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            conditions=[_condition("C1", fragment_id="F1", severity_band="severe")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", repair_required=True)],
        )
        vs = _check_C021_REPAIR_REQUIRED_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_severe_condition_without_repair_required_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            conditions=[_condition("C1", fragment_id="F1", severity_band="severe")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", repair_required=False)],
        )
        vs = _check_C021_REPAIR_REQUIRED_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C021_REPAIR_REQUIRED_CONSISTENCY")
        self.assertEqual(vs[0].priority, "P1")

    def test_emergency_condition_without_repair_required_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            conditions=[_condition("C1", fragment_id="F1", severity_band="emergency")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", repair_required=False)],
        )
        vs = _check_C021_REPAIR_REQUIRED_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)

    def test_moderate_condition_does_not_trigger(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            conditions=[_condition("C1", fragment_id="F1", severity_band="moderate")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", repair_required=False)],
        )
        vs = _check_C021_REPAIR_REQUIRED_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C022 — Verification Fail Consistency (P1)
# ============================================================


class TestC022VerificationFailConsistency(unittest.TestCase):
    def test_failing_meas_with_flag_set_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", verification_failed=True)],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_bool=False,
                    value_num=None,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C022_VERIFICATION_FAIL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_failing_meas_without_flag_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", verification_failed=False)],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_bool=False,
                    value_num=None,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C022_VERIFICATION_FAIL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C022_VERIFICATION_FAIL_CONSISTENCY")

    def test_passing_meas_does_not_trigger(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", verification_failed=False)],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_bool=True,
                    value_num=None,
                    method_class="visual_inspection",
                )
            ],
        )
        vs = _check_C022_VERIFICATION_FAIL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C027 — Fire State Internal Consistency (2026-05-12, DEBT-030 B 组)
# ============================================================


class TestC027FireStateInternalConsistency(unittest.TestCase):
    """C027: fire_state.deficiency_present=False 但 deficiency_class != 'not_applicable' → P0.

    spec 04 §5 P0 reject 行: 'deficiency_present=false but deficiency_class non-null'.
    """

    def test_consistent_not_applicable_passes(self) -> None:
        # deficiency_present=False AND deficiency_class='not_applicable' (default) → 合规
        bundle = _make_bundle(
            fire_safety_states=[
                FireSafetyState(
                    fire_state_id="FS1",
                    component_id="COMP001",
                    deficiency_present=False,
                    deficiency_class="not_applicable",
                )
            ],
        )
        vs = _check_C027_FIRE_STATE_INTERNAL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_present_true_with_real_class_passes(self) -> None:
        # deficiency_present=True AND deficiency_class='missing' (non-not_applicable) → 合规
        bundle = _make_bundle(
            fire_safety_states=[
                FireSafetyState(
                    fire_state_id="FS1",
                    component_id="COMP001",
                    deficiency_present=True,
                    deficiency_class="missing",
                )
            ],
        )
        vs = _check_C027_FIRE_STATE_INTERNAL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_inconsistent_false_with_real_class_caught(self) -> None:
        # deficiency_present=False BUT deficiency_class='damaged' → P0 violation
        bundle = _make_bundle(
            fire_safety_states=[
                FireSafetyState(
                    fire_state_id="FS1",
                    component_id="COMP001",
                    deficiency_present=False,
                    deficiency_class="damaged",
                )
            ],
        )
        vs = _check_C027_FIRE_STATE_INTERNAL_CONSISTENCY(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C027_FIRE_STATE_INTERNAL_CONSISTENCY")
        self.assertEqual(vs[0].priority, "P0")


# ============================================================
# C028 — Coverage Value Nonnegative (2026-05-12, DEBT-030 B 组)
# ============================================================


class TestC028CoverageValueNonnegative(unittest.TestCase):
    """C028: coverage_sampling_measurement.value_num < 0 → P0 reject.

    spec 04 §6 P0 reject 行: 'negative area'. 严于 C013 P2 ratio bound.
    """

    def test_positive_value_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=0.5,
                )
            ],
        )
        vs = _check_C028_COVERAGE_VALUE_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_zero_value_passes(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=0.0,
                )
            ],
        )
        vs = _check_C028_COVERAGE_VALUE_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_negative_value_caught(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="coverage_sampling_measurement",
                    target_ref="F1",
                    value_num=-0.1,
                )
            ],
        )
        vs = _check_C028_COVERAGE_VALUE_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C028_COVERAGE_VALUE_NONNEGATIVE")
        self.assertEqual(vs[0].priority, "P0")

    def test_non_coverage_family_ignored(self) -> None:
        # technical_validation 类型的负值不进 C028（只验 coverage_sampling family）
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="technical_validation_measurement",
                    target_ref="F1",
                    value_num=-1.0,
                )
            ],
        )
        vs = _check_C028_COVERAGE_VALUE_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C029 — Derived Flag No Contradiction (2026-05-12, DEBT-030 B 组)
# ============================================================


def _condition_with_derived_flags(
    condition_id: str = "COND001",
    fragment_id: str = "FRAG001",
    risk_flags: Dict[str, Any] | None = None,
    repair_flags: Dict[str, Any] | None = None,
    verification_flags: Dict[str, Any] | None = None,
    assessment_flags: Dict[str, Any] | None = None,
) -> ConditionState:
    """helper for C029 Pair 2-7 tests — build ConditionState 并填充 derived_outcomes 子 dict.

    OutcomeFlagValue 三态：True (bool) / False (bool) / "not_applicable" / "unknown" (str)。
    各 dict value 直接用 dot-delimited keys（如 "repair.required" / "verification.test.failed"
    匹配 generator.py L3145-L3166 return dict 结构）.
    """
    c = ConditionState(
        condition_id=condition_id,
        fragment_id=fragment_id,
        condition_class="DC_CRACK",
        severity_band="moderate",
    )
    if risk_flags:
        c.derived_outcomes.risk_flags.update(risk_flags)
    if repair_flags:
        c.derived_outcomes.repair_flags.update(repair_flags)
    if verification_flags:
        c.derived_outcomes.verification_flags.update(verification_flags)
    if assessment_flags:
        c.derived_outcomes.assessment_flags.update(assessment_flags)
    return c


class TestC029DerivedFlagNoContradiction(unittest.TestCase):
    """C029: 派生 flag 互斥 — spec 06 §11.X 7 对矛盾对.

    spec 04 §9 P0 reject 行: 'contradictory flags impossible to repair'.

    Pair 1: RepairAssessmentState state-level (3 既有 test method 保留 / Pair 1 测试).
    Pair 2-7: condition.derived_outcomes per-condition (6 组新增 test method).
    """

    # ---------- Pair 1: RepairAssessmentState state-level (保留现实现) ----------

    def test_required_only_passes(self) -> None:
        bundle = _make_bundle(
            repair_assessment_states=[
                RepairAssessmentState(
                    repair_assessment_id="RA1",
                    fragment_id="F1",
                    repair_required=True,
                    safe_until_next_cycle=None,
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_safe_only_passes(self) -> None:
        bundle = _make_bundle(
            repair_assessment_states=[
                RepairAssessmentState(
                    repair_assessment_id="RA1",
                    fragment_id="F1",
                    repair_required=False,
                    safe_until_next_cycle=True,
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_both_true_caught(self) -> None:
        bundle = _make_bundle(
            repair_assessment_states=[
                RepairAssessmentState(
                    repair_assessment_id="RA1",
                    fragment_id="F1",
                    repair_required=True,
                    safe_until_next_cycle=True,
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C029_DERIVED_FLAG_NO_CONTRADICTION")
        self.assertEqual(vs[0].priority, "P0")
        self.assertEqual(vs[0].fragment_id, "F1")

    # ---------- Pair 2: safe_until_next_cycle=True AND verification_test_failed=True ----------

    def test_pair2_safe_and_test_failed_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.outcome.safe_until_next_cycle": True},
                    verification_flags={"verification.test.failed": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn("safe_until_next_cycle=True AND verification_test_failed=True", vs[0].detail)
        self.assertEqual(vs[0].priority, "P0")
        self.assertEqual(vs[0].fragment_id, "F1")

    def test_pair2_safe_only_passes(self) -> None:
        # negative: 仅 safe=True，verification_test_failed=False
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.outcome.safe_until_next_cycle": True},
                    verification_flags={"verification.test.failed": False},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair2_boundary_unknown_passes(self) -> None:
        # boundary: "unknown" / "not_applicable" 不构成矛盾（无信息态）
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.outcome.safe_until_next_cycle": "not_applicable"},
                    verification_flags={"verification.test.failed": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Pair 3: maintenance_pre_next_cycle_required=True AND risk_building_safety_emergency=True ----------

    def test_pair3_maintenance_and_building_emergency_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"maintenance.pre_next_cycle.required": True},
                    risk_flags={"risk.building_safety.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn(
            "maintenance_pre_next_cycle_required=True AND risk_building_safety_emergency=True",
            vs[0].detail,
        )
        self.assertEqual(vs[0].priority, "P0")

    def test_pair3_maintenance_only_passes(self) -> None:
        # negative: 只 maintenance=True, 无 emergency
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"maintenance.pre_next_cycle.required": True},
                    risk_flags={"risk.building_safety.emergency": False},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair3_boundary_missing_flag_passes(self) -> None:
        # boundary: flag 未填 → 跳过（generator 没派生过）
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    risk_flags={"risk.building_safety.emergency": True},
                    # repair_flags 没填
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Pair 4: maintenance_pre_next_cycle_required=True AND risk_public_health_emergency=True ----------

    def test_pair4_maintenance_and_public_health_emergency_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"maintenance.pre_next_cycle.required": True},
                    risk_flags={"risk.public_health.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn(
            "maintenance_pre_next_cycle_required=True AND risk_public_health_emergency=True",
            vs[0].detail,
        )

    def test_pair4_no_maintenance_passes(self) -> None:
        # negative
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"maintenance.pre_next_cycle.required": False},
                    risk_flags={"risk.public_health.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair4_boundary_not_applicable_public_health_passes(self) -> None:
        # boundary: public_health "not_applicable" (drainage 不在 fragment) — 无矛盾
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"maintenance.pre_next_cycle.required": True},
                    risk_flags={"risk.public_health.emergency": "not_applicable"},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Pair 5: repair_required=False AND risk_building_safety_emergency=True ----------

    def test_pair5_no_repair_and_building_emergency_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.building_safety.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn(
            "repair_required=False AND risk_building_safety_emergency=True",
            vs[0].detail,
        )

    def test_pair5_repair_required_true_passes(self) -> None:
        # negative: repair.required=True → 不矛盾（risk emergency 触发 repair）
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": True},
                    risk_flags={"risk.building_safety.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair5_boundary_repair_unknown_passes(self) -> None:
        # boundary: repair.required="unknown" → 不是 explicit False，不算矛盾
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": "unknown"},
                    risk_flags={"risk.building_safety.emergency": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Pair 6: repair_required=False AND risk_public_danger_present=True ----------

    def test_pair6_no_repair_and_public_danger_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.public_danger.present": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn(
            "repair_required=False AND risk_public_danger_present=True",
            vs[0].detail,
        )

    def test_pair6_no_repair_and_no_danger_passes(self) -> None:
        # negative
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.public_danger.present": False},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair6_boundary_danger_unknown_passes(self) -> None:
        # boundary: danger="unknown" — 不是 explicit True，不算矛盾
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.public_danger.present": "unknown"},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Pair 7: repair_required=False AND verification_test_failed=True ----------

    def test_pair7_no_repair_and_test_failed_caught(self) -> None:
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    verification_flags={"verification.test.failed": True},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertIn(
            "repair_required=False AND verification_test_failed=True",
            vs[0].detail,
        )

    def test_pair7_no_repair_and_test_passes(self) -> None:
        # negative
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    verification_flags={"verification.test.failed": False},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_pair7_boundary_test_not_applicable_passes(self) -> None:
        # boundary: verification "not_applicable" (无 test 触发) — 不算矛盾
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    verification_flags={"verification.test.failed": "not_applicable"},
                )
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(vs, [])

    # ---------- Cross-Pair: 多 condition 各自检查 (不跨 condition) ----------

    def test_multi_condition_each_checked_independently(self) -> None:
        """同一 fragment 多 condition 时每 condition 各自检查（不跨 condition）.

        c1 Pair 5 命中（no_repair + building_emergency） — 应报 1 次；
        c2 Pair 6 命中（no_repair + public_danger） — 应报 1 次；
        合计 2 violations.
        """
        bundle = _make_bundle(
            conditions=[
                _condition_with_derived_flags(
                    condition_id="C1",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.building_safety.emergency": True},
                ),
                _condition_with_derived_flags(
                    condition_id="C2",
                    fragment_id="F1",
                    repair_flags={"repair.required": False},
                    risk_flags={"risk.public_danger.present": True},
                ),
            ],
        )
        vs = _check_C029_DERIVED_FLAG_NO_CONTRADICTION(bundle, _empty_registries())
        self.assertEqual(len(vs), 2)
        details = sorted(v.detail for v in vs)
        self.assertIn("'C1'", details[0])
        self.assertIn("'C2'", details[1])


# ============================================================
# C030 — Area Nonnegative (2026-05-12, DEBT-030 B 组半缺补)
# ============================================================


class TestC030AreaNonnegative(unittest.TestCase):
    """C030: area-性 measurement (slot_id 含 "area" 或 unit=="m2") value_num < 0 → P2.

    spec 07 §2.3 Measurement-level "area `≥ 0`". 跨 measurement_family 都验.
    """

    def test_positive_area_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    measurement_family="defect_geometry_measurement",
                    slot_id="spall_area_m2",
                    value_num=2.5,
                    unit="m2",
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_zero_area_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="spall_area_m2",
                    value_num=0.0,
                    unit="m2",
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_negative_area_via_slot_id_caught(self) -> None:
        # slot_id 含 "area" → 触发，即便 unit 未填
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="extent_area_m2",
                    value_num=-0.5,
                    unit=None,
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C030_AREA_NONNEGATIVE")
        self.assertEqual(vs[0].priority, "P2")

    def test_negative_area_via_unit_caught(self) -> None:
        # slot_id 不含 "area" 但 unit=="m2" → 触发
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="patch_extent",
                    value_num=-1.2,
                    unit="m2",
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C030_AREA_NONNEGATIVE")

    def test_non_area_measurement_ignored(self) -> None:
        # 既无 "area" 子串也非 m2 unit → 不进 C030
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="crack_width",
                    value_num=-0.5,
                    unit="mm",
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_none_value_ignored(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="spall_area_m2",
                    value_num=None,
                    unit="m2",
                )
            ],
        )
        vs = _check_C030_AREA_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C031 — Length Nonnegative (2026-05-12, DEBT-030 B 组半缺补)
# ============================================================


class TestC031LengthNonnegative(unittest.TestCase):
    """C031: length-性 measurement (slot_id 含 "length" 或 unit=="m"/"mm"/"cm") value_num < 0 → P2.

    spec 07 §2.3 Measurement-level "length `≥ 0`". 跨 measurement_family 都验.
    """

    def test_positive_length_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="rebar_exposed_length_m",
                    value_num=1.5,
                    unit="m",
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_zero_length_passes(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="rebar_exposed_length_m",
                    value_num=0.0,
                    unit="m",
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_negative_length_via_slot_id_caught(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="crack_length_m",
                    value_num=-2.0,
                    unit=None,
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C031_LENGTH_NONNEGATIVE")
        self.assertEqual(vs[0].priority, "P2")

    def test_negative_length_via_unit_caught(self) -> None:
        # unit 是 mm 但 slot_id 不含 "length" → 也触发
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="crack_width",
                    value_num=-0.3,
                    unit="mm",
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C031_LENGTH_NONNEGATIVE")

    def test_area_unit_not_treated_as_length(self) -> None:
        # unit=="m2" 是 area，不应进 C031（走 C030）
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="patch_extent",
                    value_num=-1.0,
                    unit="m2",
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])

    def test_non_length_measurement_ignored(self) -> None:
        bundle = _make_bundle(
            measurements=[
                _measurement(
                    "M1",
                    slot_id="strength_ratio",
                    value_num=-0.5,
                    unit="ratio",
                )
            ],
        )
        vs = _check_C031_LENGTH_NONNEGATIVE(bundle, _empty_registries())
        self.assertEqual(vs, [])


# ============================================================
# C032 — Cross-Registry Foreign Key Meta-Audit (2026-05-12, DEBT-030 B 组半缺补)
# ============================================================


class TestC032CrossRegistryForeignKeyMeta(unittest.TestCase):
    """C032: registry-to-registry FK 完整性 meta-audit (P0).

    spec 03 §3 跨表引用清单. 仅兜底现 C 编号未专门覆盖的 14 条 FK descriptor.
    """

    def _two_table_registries(
        self,
        table_a: RegistryTable,
        table_b: RegistryTable,
    ) -> RegistryBundle:
        return RegistryBundle(
            generated_at="2025-01-01T00:00:00",
            registries=[table_a, table_b],
        )

    def test_valid_fk_passes_via_mechanism_library_to_taxonomy(self) -> None:
        # mechanism_library_registry.output_condition_classes → defect_condition_taxonomy_registry.condition_class
        mech_table = RegistryTable(
            registry_id="mechanism_library_registry",
            ownership="worldgen",
            key_field="mechanism_family",
            records=[
                {"mechanism_family": "corrosion_spall", "output_condition_classes": ["DC_SPALL_REBAR"]},
            ],
        )
        taxo_table = RegistryTable(
            registry_id="defect_condition_taxonomy_registry",
            ownership="worldgen",
            key_field="condition_class",
            records=[
                {"condition_class": "DC_SPALL_REBAR", "compatible_components": ["external_wall"]},
            ],
        )
        regs = self._two_table_registries(mech_table, taxo_table)
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        self.assertEqual(vs, [])

    def test_invalid_fk_via_mechanism_library_caught(self) -> None:
        # output_condition_classes 引用了 taxonomy 中不存在的 condition_class
        mech_table = RegistryTable(
            registry_id="mechanism_library_registry",
            ownership="worldgen",
            key_field="mechanism_family",
            records=[
                {
                    "mechanism_family": "corrosion_spall",
                    "output_condition_classes": ["DC_NONEXISTENT_CLASS"],
                },
            ],
        )
        taxo_table = RegistryTable(
            registry_id="defect_condition_taxonomy_registry",
            ownership="worldgen",
            key_field="condition_class",
            records=[
                {"condition_class": "DC_SPALL_REBAR", "compatible_components": ["external_wall"]},
            ],
        )
        regs = self._two_table_registries(mech_table, taxo_table)
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].check_id, "C032_CROSS_REGISTRY_FOREIGN_KEY_META")
        self.assertEqual(vs[0].priority, "P0")
        self.assertIn("DC_NONEXISTENT_CLASS", vs[0].detail)

    def test_invalid_fk_via_repair_outcome_to_risk_derivation_caught(self) -> None:
        # repair_outcome_registry.input_risk_flags → risk_derivation_registry.risk_flag_id
        repair_table = RegistryTable(
            registry_id="repair_outcome_registry",
            ownership="worldgen",
            key_field="repair_outcome_id",
            records=[
                {
                    "repair_outcome_id": "RO_REPAIR_REQUIRED_V1",
                    "input_risk_flags": ["risk.building_safety.emergency", "risk.NONEXISTENT"],
                },
            ],
        )
        risk_table = RegistryTable(
            registry_id="risk_derivation_registry",
            ownership="worldgen",
            key_field="risk_flag_id",
            records=[
                {"risk_flag_id": "risk.building_safety.emergency"},
            ],
        )
        regs = self._two_table_registries(repair_table, risk_table)
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        # 只有 1 条 invalid FK (risk.NONEXISTENT) → 1 violation
        self.assertEqual(len(vs), 1)
        self.assertIn("risk.NONEXISTENT", vs[0].detail)

    def test_invalid_scalar_fk_via_coverage_relation_caught(self) -> None:
        # coverage_relation_registry.ratio_slot_id (scalar) → technical_measurement_registry.slot_id
        cov_table = RegistryTable(
            registry_id="coverage_relation_registry",
            ownership="worldgen",
            key_field="coverage_relation_id",
            records=[
                {
                    "coverage_relation_id": "CR1",
                    "ratio_slot_id": "ratio.unknown.slot",
                },
            ],
        )
        tech_table = RegistryTable(
            registry_id="technical_measurement_registry",
            ownership="worldgen",
            key_field="slot_id",
            records=[
                {"slot_id": "ratio.covered_area.inspected"},
            ],
        )
        regs = self._two_table_registries(cov_table, tech_table)
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        self.assertEqual(len(vs), 1)
        self.assertIn("ratio.unknown.slot", vs[0].detail)

    def test_missing_ref_registry_does_not_crash(self) -> None:
        # 只有 target registry，没有 ref registry → 不报 violation 不 crash
        taxo_table = RegistryTable(
            registry_id="defect_condition_taxonomy_registry",
            ownership="worldgen",
            key_field="condition_class",
            records=[{"condition_class": "DC_SPALL_REBAR"}],
        )
        regs = RegistryBundle(generated_at="2025-01-01T00:00:00", registries=[taxo_table])
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        # 没 ref registry，没 FK 要查，应返回 []（不该 crash 也不该误报）
        self.assertEqual(vs, [])

    def test_empty_registries_passes(self) -> None:
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), _empty_registries())
        self.assertEqual(vs, [])

    def test_multiple_invalid_fks_all_reported(self) -> None:
        # 同一 ref record list 中多个 FK 都 invalid → 多 violation
        mech_table = RegistryTable(
            registry_id="mechanism_library_registry",
            ownership="worldgen",
            key_field="mechanism_family",
            records=[
                {
                    "mechanism_family": "corrosion_spall",
                    "output_condition_classes": ["DC_BAD_1", "DC_BAD_2"],
                },
            ],
        )
        taxo_table = RegistryTable(
            registry_id="defect_condition_taxonomy_registry",
            ownership="worldgen",
            key_field="condition_class",
            records=[{"condition_class": "DC_SPALL_REBAR"}],
        )
        regs = self._two_table_registries(mech_table, taxo_table)
        vs = _check_C032_CROSS_REGISTRY_FOREIGN_KEY_META(_make_bundle(), regs)
        self.assertEqual(len(vs), 2)
        details = [v.detail for v in vs]
        self.assertTrue(any("DC_BAD_1" in d for d in details))
        self.assertTrue(any("DC_BAD_2" in d for d in details))


# ============================================================
# P1 Repair Tests
# ============================================================


class TestP1RepairExtentsAndFlags(unittest.TestCase):
    """Tests for _repair_p1_extents_and_flags (C007/C008/C021/C022)."""

    def _make_c007_violation(self, fragment_id: str) -> Violation:
        return Violation(
            check_id="C007_EXTENT_AREA_BOUND",
            priority="P1",
            detail="test",
            fragment_id=fragment_id,
        )

    def _make_c008_violation(self, fragment_id: str) -> Violation:
        return Violation(
            check_id="C008_EXTENT_LENGTH_BOUND",
            priority="P1",
            detail="test",
            fragment_id=fragment_id,
        )

    def _make_c021_violation(self, fragment_id: str) -> Violation:
        return Violation(
            check_id="C021_REPAIR_REQUIRED_CONSISTENCY",
            priority="P1",
            detail="RA1",
            fragment_id=fragment_id,
        )

    def _make_c022_violation(self, fragment_id: str) -> Violation:
        return Violation(
            check_id="C022_VERIFICATION_FAIL_CONSISTENCY",
            priority="P1",
            detail="RA1",
            fragment_id=fragment_id,
        )

    def test_c007_repair_clamps_extent_area(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_area_m2=10.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_area_m2=20.0)],
        )
        repaired, actions = _repair_p1_extents_and_flags(
            bundle, [self._make_c007_violation("F1")]
        )
        self.assertIsNot(repaired, bundle)  # pure function: returns new object
        self.assertAlmostEqual(repaired.conditions[0].extent_area_m2, 10.0)
        # original unchanged
        self.assertAlmostEqual(bundle.conditions[0].extent_area_m2, 20.0)
        # DEBT-030 C 组：audit trace 记录修复事实
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].check_id, "C007_EXTENT_AREA_BOUND")
        self.assertEqual(actions[0].fragment_id, "F1")
        self.assertAlmostEqual(actions[0].before_value, 20.0)
        self.assertAlmostEqual(actions[0].after_value, 10.0)

    def test_c008_repair_clamps_extent_length(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_length_m=5.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_length_m=12.0)],
        )
        repaired, actions = _repair_p1_extents_and_flags(
            bundle, [self._make_c008_violation("F1")]
        )
        self.assertAlmostEqual(repaired.conditions[0].extent_length_m, 5.0)
        # DEBT-030 C 组：audit trace
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].check_id, "C008_EXTENT_LENGTH_BOUND")
        self.assertAlmostEqual(actions[0].before_value, 12.0)
        self.assertAlmostEqual(actions[0].after_value, 5.0)

    def test_c021_repair_sets_repair_required(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", repair_required=False)],
        )
        repaired, actions = _repair_p1_extents_and_flags(
            bundle, [self._make_c021_violation("F1")]
        )
        self.assertTrue(repaired.repair_assessment_states[0].repair_required)
        self.assertFalse(bundle.repair_assessment_states[0].repair_required)
        # DEBT-030 C 组：audit trace
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].check_id, "C021_REPAIR_REQUIRED_CONSISTENCY")
        self.assertEqual(actions[0].before_value, False)
        self.assertEqual(actions[0].after_value, True)

    def test_c022_repair_sets_verification_failed(self) -> None:
        bundle = _make_bundle(
            fragments=[_fragment("F1")],
            repair_assessment_states=[_repair_assessment("RA1", fragment_id="F1", verification_failed=False)],
        )
        repaired, actions = _repair_p1_extents_and_flags(
            bundle, [self._make_c022_violation("F1")]
        )
        self.assertTrue(repaired.repair_assessment_states[0].verification_failed)
        self.assertFalse(bundle.repair_assessment_states[0].verification_failed)
        # DEBT-030 C 组：audit trace
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].check_id, "C022_VERIFICATION_FAIL_CONSISTENCY")
        self.assertEqual(actions[0].before_value, False)
        self.assertEqual(actions[0].after_value, True)

    def test_irrelevant_violations_return_same_bundle(self) -> None:
        bundle = _make_bundle()
        irrelevant = [Violation(check_id="C999_UNKNOWN", priority="P1", detail="x")]
        result, actions = _repair_p1_extents_and_flags(bundle, irrelevant)
        self.assertIs(result, bundle)
        # DEBT-030 C 组：无修复发生 actions list 空
        self.assertEqual(actions, [])

    def test_c007_no_repair_when_within_bounds_no_action_logged(self) -> None:
        """DEBT-030 C 组：when before == after（已在 bounds 内），不记 spurious action."""
        bundle = _make_bundle(
            fragments=[_fragment("F1", fragment_area_m2=10.0)],
            conditions=[_condition("C1", fragment_id="F1", extent_area_m2=5.0)],
        )
        repaired, actions = _repair_p1_extents_and_flags(
            bundle, [self._make_c007_violation("F1")]
        )
        # 已在 bounds 内（5 < 10），不应记修复动作
        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
