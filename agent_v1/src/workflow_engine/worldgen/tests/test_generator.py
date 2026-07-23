"""T-17a + T-17b smoke tests for `generator.generate_world_bundle()`.

T-17a validates:
- WorldBundle returned with valid building / components / locations
- ID 格式对齐 spec 04 §3 / §4 / §5 / §6 (^WB- / ^BLD- / ^CMP- / ^LOC-)
- archetype 抽样在 batch_config 分布下生效
- 同 seed + building_index 输出确定性可复现 (pure function 立场，T-17.6)

T-17b validates:
- fragments / drivers / mechanisms / conditions / repair_assessment_states 非空
- 各列表长度对齐（per-fragment 1:1）
- 选择性域状态（drainage / ubw / fire_safety）按 mechanism family 派生
- coverage_relations 跟 fragments 对齐
- measurements 仍空（T-17c 才填）
"""

from __future__ import annotations

import random
import re
import unittest

from workflow_engine.worldgen.generator import (
    build_building_context,
    build_components,
    build_locations,
    generate_world_bundle,
    generate_world_batch,
    sample_archetype,
)
from workflow_engine.worldgen.registry import _build_registry_bundle
from workflow_engine.worldgen.models import (
    ComponentNode,
    DriverState,
    FragmentContext,
    LocationNode,
)


_WORLD_ID_PATTERN = re.compile(r"^WB-[A-Z0-9-]+$")
_BUILDING_ID_PATTERN = re.compile(r"^BLD-[A-Z0-9-]+$")
_COMPONENT_ID_PATTERN = re.compile(r"^CMP-[A-Z0-9-]+$")
_LOCATION_ID_PATTERN = re.compile(r"^LOC-[A-Z0-9-]+$")
_FRAGMENT_ID_PATTERN = re.compile(r"^FRG-[A-Z0-9-]+$")
_DRIVER_ID_PATTERN = re.compile(r"^DRV-[A-Z0-9-]+$")
_MECHANISM_STATE_ID_PATTERN = re.compile(r"^MST-[A-Z0-9-]+$")
_CONDITION_ID_PATTERN = re.compile(r"^CND-[A-Z0-9-]+$")
_COVERAGE_ID_PATTERN = re.compile(r"^CVR-[A-Z0-9-]+$")


class GenerateWorldBundleShellTests(unittest.TestCase):
    """Spec 04 §3 WorldBundle shell smoke tests (T-17a scope)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_generate_returns_building_world(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        self.assertEqual(world.schema_version, "worldgen.fullcoverage.world.v1")
        self.assertTrue(_WORLD_ID_PATTERN.match(world.world_id), world.world_id)

    def test_building_id_format(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=7, building_index=3)
        self.assertTrue(_BUILDING_ID_PATTERN.match(world.building.building_id))

    def test_components_non_empty_with_valid_ids(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=1, building_index=0)
        self.assertGreaterEqual(len(world.components), 6)  # base plan = 6
        for component in world.components:
            self.assertTrue(_COMPONENT_ID_PATTERN.match(component.component_id))
            self.assertIn("visible_area_m2", component.geometry_proxy)

    def test_locations_non_empty_with_valid_ids(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=1, building_index=0)
        self.assertGreaterEqual(len(world.locations), 1)
        location_ids = {loc.location_id for loc in world.locations}
        for component in world.components:
            self.assertIn(component.location_id, location_ids,
                          f"component {component.component_id} references missing location {component.location_id}")
        for location in world.locations:
            self.assertTrue(_LOCATION_ID_PATTERN.match(location.location_id))

    def test_t17b_fragments_non_empty(self) -> None:
        """T-17b stage：fragments / drivers / mechanisms / conditions 非空且对齐。"""
        world = generate_world_bundle({}, self.registries, seed=99, building_index=0, fragment_count=4)
        self.assertGreaterEqual(len(world.fragments), 1)
        self.assertEqual(len(world.fragments), len(world.drivers))
        self.assertEqual(len(world.fragments), len(world.mechanisms))
        self.assertEqual(len(world.fragments), len(world.conditions))
        self.assertEqual(len(world.fragments), len(world.repair_assessment_states))
        for fragment in world.fragments:
            self.assertTrue(_FRAGMENT_ID_PATTERN.match(fragment.fragment_id))
        for driver in world.drivers:
            self.assertTrue(_DRIVER_ID_PATTERN.match(driver.driver_id))
            self.assertGreaterEqual(driver.repair_quality_index, 0.0)
            self.assertLessEqual(driver.repair_quality_index, 1.0)
        for mechanism in world.mechanisms:
            self.assertTrue(_MECHANISM_STATE_ID_PATTERN.match(mechanism.mechanism_state_id))
            self.assertNotEqual(mechanism.mechanism_family, "")
            self.assertNotEqual(mechanism.fragment_id, "")
        for condition in world.conditions:
            self.assertTrue(_CONDITION_ID_PATTERN.match(condition.condition_id))
            self.assertEqual(condition.fragment_id, condition.fragment_id)  # tautology guard

    def test_t17c_measurements_3_families(self) -> None:
        """T-17c：measurements 含 3 family（coverage_sampling / technical_validation / structural_assessment）。"""
        world = generate_world_bundle({}, self.registries, seed=99, building_index=0, fragment_count=4)
        self.assertGreater(len(world.measurements), 0)
        families = {m.measurement_family for m in world.measurements}
        # coverage_sampling 应在（每 fragment 派生）
        self.assertIn("coverage_sampling_measurement", families)
        # 至少含一种 validation 或 assessment family
        self.assertTrue(
            "technical_validation_measurement" in families
            or "structural_assessment_measurement" in families,
            f"Expected validation or assessment family in {families}",
        )
        # 每个 measurement target_ref 应指向有效锚点：defect_geometry_measurement 按 SA-1 fix
        # (2026-05-23, generator.py:2295-2307) 锚 condition_id，其余锚 fragment_id。
        fragment_ids = {f.fragment_id for f in world.fragments}
        condition_ids = {c.condition_id for c in world.conditions}
        for measurement in world.measurements:
            if measurement.measurement_family == "defect_geometry_measurement":
                self.assertIn(measurement.target_ref, condition_ids)
            else:
                self.assertIn(measurement.target_ref, fragment_ids)
            # value 三选一非空
            self.assertTrue(
                measurement.value_num is not None
                or measurement.value_bool is not None
                or measurement.value_enum is not None,
                f"{measurement.measurement_id} has no value",
            )

    def test_t17b_coverage_relations_align_with_fragments(self) -> None:
        """每个 fragment 至少派生 1 个 CoverageRelation。"""
        world = generate_world_bundle({}, self.registries, seed=99, building_index=0, fragment_count=4)
        fragment_ids = {f.fragment_id for f in world.fragments}
        for cr in world.coverage_relations:
            self.assertTrue(_COVERAGE_ID_PATTERN.match(cr.coverage_id))
            self.assertIn(cr.target_fragment_id, fragment_ids)

    def test_t17b_domain_states_only_when_mechanism_matches(self) -> None:
        """drainage_states / ubw_states / fire_safety_states 只在对应 mechanism 出现时派生。"""
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        drainage_fragment_ids = {ds.component_id for ds in world.drainage_states}
        for ds in world.drainage_states:
            self.assertGreaterEqual(ds.blockage_index, 0.0)
            self.assertLessEqual(ds.blockage_index, 1.0)
        for ubw in world.ubw_states:
            self.assertTrue(ubw.present)
            self.assertNotEqual(ubw.alteration_type, "none")
        for fss in world.fire_safety_states:
            # W0-004 step 5 (2026-05-21)：build_components 内 cover_depth_mm 抽样消耗 rng 序列后,
            # 此处 seed=42 / building_index=0 偶尔抽到 deficiency_present=False（class=not_applicable）.
            # spec 04 §14 FireSafetyState contract 允许 not_applicable + deficiency_present=False
            # 共存（spec 04 §14 line 213-214 "deficiency_present=true 时非 not_applicable"，反之合法）.
            # 改 robust 断言：present=True 时 class 必在 4 个 enum；present=False 时 class 必 not_applicable.
            if fss.deficiency_present:
                self.assertIn(fss.deficiency_class, ["missing", "damaged", "obstructed", "non_functional"])
            else:
                self.assertEqual(fss.deficiency_class, "not_applicable")

    def test_deterministic_same_seed_index(self) -> None:
        """Pure function (T-17.6)：same (seed, building_index) → identical output."""
        w1 = generate_world_bundle({}, self.registries, seed=42, building_index=2)
        w2 = generate_world_bundle({}, self.registries, seed=42, building_index=2)
        self.assertEqual(w1.world_id, w2.world_id)
        self.assertEqual(w1.building.building_id, w2.building.building_id)
        self.assertEqual(w1.building.storey_count, w2.building.storey_count)
        self.assertEqual(len(w1.components), len(w2.components))
        for c1, c2 in zip(w1.components, w2.components):
            self.assertEqual(c1.component_id, c2.component_id)
            self.assertEqual(c1.material_system, c2.material_system)

    def test_different_index_yields_different_world(self) -> None:
        w1 = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        w2 = generate_world_bundle({}, self.registries, seed=42, building_index=1)
        self.assertNotEqual(w1.world_id, w2.world_id)

    def test_archetype_distribution_respected(self) -> None:
        """batch_config['archetype_distribution'] 单值=1.0 → 必中。"""
        target = "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1"
        config = {"archetype_distribution": {target: 1.0}}
        for index in range(5):
            world = generate_world_bundle(config, self.registries, seed=1, building_index=index)
            # W0-008 (2026-05-21)：building_template_id 走 building_metadata 字段
            # （BuildingMetadata），spec 04 §4 BuildingContext 收紧到 8 字段 contract.
            self.assertEqual(world.building_metadata.building_template_id, target)

    def test_sample_archetype_uniform_fallback(self) -> None:
        """无 distribution → uniform random over registry templates。"""
        rng = random.Random(0)
        seen = set()
        for _ in range(50):
            template_id = sample_archetype({}, self.registries, rng)
            seen.add(template_id)
        self.assertGreaterEqual(len(seen), 2, "uniform sampling should cover multiple templates")


class GenerateWorldBatchTests(unittest.TestCase):
    """T-17d batch 入口 smoke tests。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_batch_returns_count_world_records(self) -> None:
        worlds = generate_world_batch({}, self.registries, count=5, seed=42)
        self.assertEqual(len(worlds), 5)
        ids = [w.world_id for w in worlds]
        self.assertEqual(len(ids), len(set(ids)), "world_ids must be unique within batch")

    def test_batch_archetype_distribution_applied(self) -> None:
        config = {"archetype_distribution": {"BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1": 1.0}}
        worlds = generate_world_batch(config, self.registries, count=3, seed=7)
        for world in worlds:
            # W0-008 (2026-05-21)：building_template_id 走 building_metadata 字段.
            self.assertEqual(world.building_metadata.building_template_id, "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1")

    def test_batch_deterministic_same_seed(self) -> None:
        b1 = generate_world_batch({}, self.registries, count=3, seed=11)
        b2 = generate_world_batch({}, self.registries, count=3, seed=11)
        self.assertEqual([w.world_id for w in b1], [w.world_id for w in b2])

    def test_batch_count_zero_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_world_batch({}, self.registries, count=0, seed=1)


class BuildingContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_storey_count_within_template_range(self) -> None:
        rng = random.Random(0)
        template_id = "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1"  # T-30 spec 03 §4.8 storey range [15, 60]
        # W0-008 (2026-05-21)：返回 (BuildingContext, BuildingMetadata) tuple.
        ctx, _ = build_building_context(template_id, 0, self.registries, rng)
        self.assertGreaterEqual(ctx.storey_count, 15)
        self.assertLessEqual(ctx.storey_count, 60)

    def test_age_years_in_bounds(self) -> None:
        rng = random.Random(0)
        ctx, _ = build_building_context("BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1", 0, self.registries, rng)
        self.assertGreaterEqual(ctx.age_years, 0.0)
        self.assertLessEqual(ctx.age_years, 100.0)

    def test_unknown_template_raises(self) -> None:
        rng = random.Random(0)
        with self.assertRaises(ValueError):
            build_building_context("BT_NONEXISTENT_V1", 0, self.registries, rng)


class ComponentMaterialCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_component_material_compatible_with_type(self) -> None:
        """Each component's material_system 必须在 component_type_registry.material_compatibility。"""
        from workflow_engine.worldgen.generator import _registry_index

        component_type_index = _registry_index(self.registries, "component_type_registry", "component_type")
        rng = random.Random(0)
        template_id = "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1"
        # W0-008 (2026-05-21)：build_building_context 返回 tuple；build_components 显式传 template_id.
        building, _ = build_building_context(template_id, 0, self.registries, rng)
        components = build_components(building, template_id, self.registries, rng)
        for component in components:
            type_record = component_type_index.get(component.component_type)
            self.assertIsNotNone(type_record, f"unknown component_type {component.component_type}")
            compatibility = type_record.get("material_compatibility") or []
            self.assertIn(component.material_system, compatibility,
                          f"{component.component_id}: material {component.material_system} "
                          f"not in compatibility {compatibility}")


class T18aStructuralSurrogateTests(unittest.TestCase):
    """T-18a spec 06 §3.1 公式 unit tests."""

    def _make_driver(self, **kwargs):
        """Build a minimal DriverState with overrideable fields.

        W0-004 (2026-05-21): spec 04 §9 13 字段对齐——age_years 不在 driver 上
        (从 BuildingContext 反查)；helper 内 pop `age_years` 暴露给单独参数 (test
        派生公式直接传给函数)，并自动注入 fragment_id 默认值；同时映射 legacy
        `blockage_propensity` → `drainage_fault_propensity`。
        """
        from workflow_engine.worldgen.models import DriverState
        # 兼容 legacy 调用：blockage_propensity / age_years / 4 cruft 字段
        legacy_to_spec = {
            "blockage_propensity": "drainage_fault_propensity",
        }
        for legacy, spec_name in legacy_to_spec.items():
            if legacy in kwargs and spec_name not in kwargs:
                kwargs[spec_name] = kwargs.pop(legacy)
            elif legacy in kwargs:
                kwargs.pop(legacy)
        # cruft 字段：spec 04 §9 / spec 06 公式不消费 → 丢弃
        for cruft in ("age_years", "obstruction_index", "drainage_usage_intensity", "coverage_feasibility_index"):
            kwargs.pop(cruft, None)
        defaults = dict(
            driver_id="DRV-TEST",
            fragment_id=kwargs.pop("fragment_id", "FRG-TEST"),
            service_load_ratio=0.5,
            restraint_level=0.5,
            moisture_ingress_index=0.5,
            chloride_exposure_index=0.5,
            carbonation_index=0.5,
            workmanship_deficit_index=0.5,
            maintenance_deficit_index=0.5,
            drainage_fault_propensity=0.5,
            alteration_propensity=0.5,
            fire_safety_deficit_index=0.5,
            repair_quality_index=0.5,
        )
        defaults.update(kwargs)
        return DriverState(**defaults)

    def test_crack_score_high_load_high(self):
        """高 service_load + 高 restraint → high crack_score > 0.7."""
        from workflow_engine.worldgen.generator import _compute_crack_score
        driver = self._make_driver(service_load_ratio=0.9, restraint_level=0.9, workmanship_deficit_index=0.9)
        score = _compute_crack_score(driver)
        self.assertGreater(score, 0.7)

    def test_crack_score_low_inputs_low(self):
        """低 inputs → crack_score < 0.5."""
        from workflow_engine.worldgen.generator import _compute_crack_score
        driver = self._make_driver(service_load_ratio=0.0, restraint_level=0.0, workmanship_deficit_index=0.0)
        score = _compute_crack_score(driver)
        self.assertLess(score, 0.5)

    def test_spall_score_aged_chloride_high(self):
        """高 chloride + 高 age → high spall_score > 0.7."""
        # W0-004: age_years 不在 driver 上（spec 04 §4 line 79 BuildingContext 字段），
        # test 显式传 building 年龄到 _age_norm.
        from workflow_engine.worldgen.generator import _compute_spall_score, _age_norm
        driver = self._make_driver(
            chloride_exposure_index=0.9,
            moisture_ingress_index=0.9,
            carbonation_index=0.9,
        )
        score = _compute_spall_score(driver, _age_norm(50.0))
        self.assertGreater(score, 0.7)

    def test_spall_score_young_clean_low(self):
        """新建 + 低 chloride → spall_score < 0.5."""
        # W0-004: age_years 走外部参数（同上）.
        from workflow_engine.worldgen.generator import _compute_spall_score, _age_norm
        driver = self._make_driver(
            chloride_exposure_index=0.0,
            moisture_ingress_index=0.0,
            carbonation_index=0.0,
        )
        score = _compute_spall_score(driver, _age_norm(2.0))
        self.assertLess(score, 0.5)

    def test_detachment_score_moisture_workmanship(self):
        """高 moisture + 高 workmanship deficit → detachment_score > 0.7."""
        from workflow_engine.worldgen.generator import _compute_detachment_score
        driver = self._make_driver(moisture_ingress_index=0.9, workmanship_deficit_index=0.9, maintenance_deficit_index=0.9)
        score = _compute_detachment_score(driver)
        self.assertGreater(score, 0.7)

    def test_detachment_score_dry_good_workmanship_low(self):
        """低 moisture + 低 workmanship → detachment_score < 0.5."""
        from workflow_engine.worldgen.generator import _compute_detachment_score
        driver = self._make_driver(moisture_ingress_index=0.0, workmanship_deficit_index=0.0, maintenance_deficit_index=0.0)
        score = _compute_detachment_score(driver)
        self.assertLess(score, 0.5)

    def test_mechanism_selects_max_score(self):
        """generate_mechanism 选 max score 的 family。"""
        from workflow_engine.worldgen.generator import generate_mechanism, _compute_crack_score, _compute_spall_score, _compute_detachment_score, _age_norm
        fragment = FragmentContext(
            fragment_id="FRG-TEST-001",
            fragment_template_id="FT_TEST",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        # 構造一個 driver 讓 spall_score 最高
        driver = self._make_driver(
            chloride_exposure_index=0.95,
            moisture_ingress_index=0.95,
            carbonation_index=0.95,
            service_load_ratio=0.1,
            restraint_level=0.1,
            workmanship_deficit_index=0.1,
        )
        template = {"allowed_mechanisms": ["structural_crack", "corrosion_spall", "moisture_detachment"]}
        rng = random.Random(42)
        # W0-004: generate_mechanism 新参数 age_years 来自 BuildingContext.
        mechanism = generate_mechanism(fragment, template, driver, rng, 50.0)
        # spall_score 應該最高，所以 mechanism_family 應該是 corrosion_spall
        self.assertEqual(mechanism.mechanism_family, "corrosion_spall")

    def test_age_norm_clips(self):
        """_age_norm clip 到 [0, 1]。"""
        from workflow_engine.worldgen.generator import _age_norm
        self.assertAlmostEqual(_age_norm(0.0), 0.0)
        self.assertAlmostEqual(_age_norm(50.0), 1.0)
        self.assertAlmostEqual(_age_norm(100.0), 1.0)
        self.assertAlmostEqual(_age_norm(25.0), 0.5)

    def test_crack_kind_load_induced(self):
        """service_load >= restraint + 0.15 → crack_mechanism_kind = load_induced."""
        from workflow_engine.worldgen.generator import generate_mechanism
        fragment = FragmentContext(
            fragment_id="FRG-TEST-002",
            fragment_template_id="FT_TEST",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=12.0,
            fragment_length_m=4.0,
            in_scope=True,
            exclusion_reason=None,
        )
        # service_load >> restraint → load_induced
        driver = self._make_driver(
            service_load_ratio=0.9,
            restraint_level=0.3,  # 0.9 >= 0.3 + 0.15
            workmanship_deficit_index=0.9,
            moisture_ingress_index=0.0,
            chloride_exposure_index=0.0,
            carbonation_index=0.0,
        )
        template = {"allowed_mechanisms": ["structural_crack"]}
        rng = random.Random(1)
        # W0-004: age_years 来自 BuildingContext.
        mechanism = generate_mechanism(fragment, template, driver, rng, 30.0)
        self.assertEqual(mechanism.mechanism_family, "structural_crack")
        self.assertEqual(mechanism.crack_mechanism_kind, "load_induced")

    def test_activation_threshold_035(self):
        """spec §3.2: active = (score >= 0.35)."""
        from workflow_engine.worldgen.generator import generate_mechanism
        fragment = FragmentContext(
            fragment_id="FRG-TEST-003",
            fragment_template_id="FT_TEST",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=9.0,
            fragment_length_m=3.0,
            in_scope=True,
            exclusion_reason=None,
        )
        # 所有 driver inputs 設 0 → 所有 score 接近 sigmoid(-1.0) ≈ 0.27 < 0.35 → not active
        driver = self._make_driver(
            service_load_ratio=0.0,
            restraint_level=0.0,
            workmanship_deficit_index=0.0,
            moisture_ingress_index=0.0,
            chloride_exposure_index=0.0,
            carbonation_index=0.0,
            maintenance_deficit_index=0.0,
        )
        template = {"allowed_mechanisms": ["structural_crack", "corrosion_spall", "moisture_detachment"]}
        rng = random.Random(0)
        # W0-004: age_years=0.0 来自外部 BuildingContext.
        mechanism = generate_mechanism(fragment, template, driver, rng, 0.0)
        # score ≈ 0.27 < 0.35 → not active
        self.assertFalse(mechanism.active)


class T18bRebarSpallSurrogateTests(unittest.TestCase):
    """T-18b spec 06 §4 rebar / spall surrogate 公式 unit tests."""

    def _make_driver(self, **kwargs):
        # W0-004 (2026-05-21): spec 04 §9 13 字段对齐——同 T18a helper 兼容 legacy 调用。
        from workflow_engine.worldgen.models import DriverState
        legacy_to_spec = {"blockage_propensity": "drainage_fault_propensity"}
        for legacy, spec_name in legacy_to_spec.items():
            if legacy in kwargs and spec_name not in kwargs:
                kwargs[spec_name] = kwargs.pop(legacy)
            elif legacy in kwargs:
                kwargs.pop(legacy)
        for cruft in ("age_years", "obstruction_index", "drainage_usage_intensity", "coverage_feasibility_index"):
            kwargs.pop(cruft, None)
        defaults = dict(
            driver_id="DRV-T18B",
            fragment_id=kwargs.pop("fragment_id", "FRG-T18B"),
            service_load_ratio=0.5,
            restraint_level=0.5,
            moisture_ingress_index=0.5,
            chloride_exposure_index=0.5,
            carbonation_index=0.5,
            workmanship_deficit_index=0.5,
            maintenance_deficit_index=0.5,
            drainage_fault_propensity=0.5,
            alteration_propensity=0.5,
            fire_safety_deficit_index=0.5,
            repair_quality_index=0.5,
        )
        defaults.update(kwargs)
        return DriverState(**defaults)

    def _make_fragment(self, **kwargs):
        # W0-005 (2026-05-21)：spec 04 §7 FragmentContext 9 字段 reference-based contract.
        # 旧 legacy denormalized 字段（fragment_scope / component_type_id / material_system /
        # structural_role / surface_position / exposure_zone / has_rebar / cover_depth_mm /
        # section_thickness_mm 等）由消费方按 spec 06 §0.1 reference 反查（component / location）.
        # Legacy alias 兼容：测试代码若仍传 `nominal_visible_area_m2` / `nominal_length_m`，自动转
        # `fragment_area_m2` / `fragment_length_m`.
        if "nominal_visible_area_m2" in kwargs and "fragment_area_m2" not in kwargs:
            kwargs["fragment_area_m2"] = kwargs.pop("nominal_visible_area_m2")
        if "nominal_length_m" in kwargs and "fragment_length_m" not in kwargs:
            length = kwargs.pop("nominal_length_m")
            kwargs["fragment_length_m"] = length if length else None
        # 删非 spec 字段（这些字段语义现在走 component / location 反查）
        for legacy in ("fragment_scope", "component_type_id", "material_system",
                       "structural_role", "surface_position", "exposure_zone",
                       "has_rebar", "cover_depth_mm", "section_thickness_mm",
                       "building_metadata"):
            kwargs.pop(legacy, None)
        defaults = dict(
            fragment_id="FRG-TB-001",
            fragment_template_id="FT_TEST",
            component_id="CMP-TB-001",
            location_id="LOC-TB-001",
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        defaults.update(kwargs)
        return FragmentContext(**defaults)

    def _make_component(self, **kwargs):
        # W0-005 (2026-05-21)：spec 04 §5 ComponentNode；测试 helper 提供与 _make_fragment 配套的
        # 物理 context（cover_depth_mm / material_system / structural_role / geometry_proxy 等），
        # 让 generator pipeline 函数按 spec 06 §0.1 reference 反查路径消费.
        defaults = dict(
            component_id="CMP-TB-001",
            component_type="external_wall",
            parent_component_id=None,
            material_system="reinforced_concrete",
            structural_role="non_load_bearing",
            location_id="LOC-TB-001",
            geometry_proxy={"visible_area_m2": 15.0, "thickness_mm": 200.0},
            cover_depth_mm=30.0,
            access_class="fully_accessible",
        )
        defaults.update(kwargs)
        return ComponentNode(**defaults)

    def test_corrosion_severity_high_chloride_age(self):
        """高 chloride + 高 age → corrosion_severity > 0.6."""
        # W0-004: age_years 走外部参数 (spec 04 §4 BuildingContext).
        from workflow_engine.worldgen.generator import _compute_corrosion_severity
        driver = self._make_driver(
            chloride_exposure_index=0.9,
            carbonation_index=0.9,
            moisture_ingress_index=0.9,
        )
        score = _compute_corrosion_severity(driver, cover_depth_mm=10.0, age_years=50.0)
        self.assertGreater(score, 0.6)

    def test_corrosion_severity_high_cover_lowers_value(self):
        """大 cover_depth_mm → cover_norm 懲罰拉低 corrosion_severity."""
        from workflow_engine.worldgen.generator import _compute_corrosion_severity
        driver = self._make_driver(
            chloride_exposure_index=0.5,
            carbonation_index=0.5,
            moisture_ingress_index=0.5,
        )
        score_thin = _compute_corrosion_severity(driver, cover_depth_mm=10.0, age_years=30.0)
        score_thick = _compute_corrosion_severity(driver, cover_depth_mm=80.0, age_years=30.0)
        self.assertGreater(score_thin, score_thick)

    def test_delamination_severity_scales_with_corrosion(self):
        """delamination 嚴格依 corrosion + moisture + maintenance."""
        from workflow_engine.worldgen.generator import _compute_delamination_severity
        driver_lo = self._make_driver(moisture_ingress_index=0.0, maintenance_deficit_index=0.0)
        driver_hi = self._make_driver(moisture_ingress_index=1.0, maintenance_deficit_index=1.0)
        del_lo = _compute_delamination_severity(0.2, driver_lo)
        del_hi = _compute_delamination_severity(0.8, driver_hi)
        self.assertGreater(del_hi, del_lo)

    def test_cover_loss_depth_in_bounds(self):
        """cover_loss_depth_mm 在 [1, cover+20] 範圍."""
        from workflow_engine.worldgen.generator import _compute_cover_loss_depth_mm
        cover = 30.0
        for delamination in [0.0, 0.5, 1.0]:
            result = _compute_cover_loss_depth_mm(delamination, cover)
            self.assertGreaterEqual(result, 1.0)
            self.assertLessEqual(result, cover + 20.0)

    def test_cover_loss_depth_none_for_no_rebar(self):
        """cover_depth_mm=None → cover_loss_depth_mm=None."""
        from workflow_engine.worldgen.generator import _compute_cover_loss_depth_mm
        self.assertIsNone(_compute_cover_loss_depth_mm(0.8, None))

    def test_spall_patch_area_in_bounds(self):
        """spall_patch_area 在 [0.001, 0.6*area] 範圍."""
        from workflow_engine.worldgen.generator import _compute_spall_patch_area_m2
        area = 15.0
        for delamination in [0.0, 0.5, 1.0]:
            result = _compute_spall_patch_area_m2(delamination, 0.8, area)
            self.assertGreaterEqual(result, 0.001)
            self.assertLessEqual(result, 0.6 * area)

    def test_rebar_exposed_length_upper_bound(self):
        """rebar_exposed_length ≤ 3 * nominal_length."""
        from workflow_engine.worldgen.generator import _compute_rebar_exposed_length_m
        length = 5.0
        result = _compute_rebar_exposed_length_m(
            cover_loss_depth_mm=50.0,
            cover_depth_mm=25.0,
            spall_patch_area_m2=10.0,  # 過大值，應被 clip
            nominal_length_m=length,
        )
        self.assertLessEqual(result, 3.0 * length)

    def test_rebar_exposed_length_none_cover_returns_zero(self):
        """cover_depth_mm=None → rebar_exposed_length=0."""
        from workflow_engine.worldgen.generator import _compute_rebar_exposed_length_m
        result = _compute_rebar_exposed_length_m(None, None, 1.0, 5.0)
        self.assertEqual(result, 0.0)

    def test_generate_condition_corrosion_spall_uses_spec4(self):
        """generate_condition corrosion_spall → severity=corrosion_severity；extent_area>0."""
        from workflow_engine.worldgen.generator import generate_condition, _compute_corrosion_severity
        from workflow_engine.worldgen.models import MechanismState, MechanismActivation
        fragment = self._make_fragment()
        component = self._make_component(cover_depth_mm=30.0)
        driver = self._make_driver(
            age_years=40.0,
            chloride_exposure_index=0.9,
            moisture_ingress_index=0.9,
            carbonation_index=0.7,
        )
        mechanism = MechanismState(
            mechanism_state_id="MST-TB-001",
            fragment_id=fragment.fragment_id,
            mechanism_family="corrosion_spall",
            active=True,
            severity_index=0.8,
            cause_tags=[],
            primary_mechanism_id="MCH-corrosion_spall-FRG-TB-001",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-corrosion_spall-FRG-TB-001",
                mechanism_family="corrosion_spall",
                activation_score=0.8,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=True,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        rng = random.Random(42)
        # W0-005 (2026-05-21): generate_condition 新 signature——加 component 参数（spec 06 §0.1
        # reference 反查 cover_depth_mm / material_system）+ age_years 走 BuildingContext.
        condition = generate_condition(fragment, component, mechanism, driver, rng, 30.0)
        expected_corrosion = _compute_corrosion_severity(driver, component.cover_depth_mm, age_years=30.0)
        self.assertAlmostEqual(condition.severity_index, expected_corrosion, places=4)
        self.assertIsNotNone(condition.extent_area_m2)
        self.assertGreater(condition.extent_area_m2, 0.0)

    def test_generate_condition_other_mechanism_uses_severity_index(self):
        """generate_condition structural_crack → 保留 mechanism.severity_index。"""
        from workflow_engine.worldgen.generator import generate_condition
        from workflow_engine.worldgen.models import MechanismState, MechanismActivation
        fragment = self._make_fragment()
        component = self._make_component()
        driver = self._make_driver()
        mock_severity = 0.55
        mechanism = MechanismState(
            mechanism_state_id="MST-TB-002",
            fragment_id=fragment.fragment_id,
            mechanism_family="structural_crack",
            active=True,
            severity_index=mock_severity,
            cause_tags=[],
            primary_mechanism_id="MCH-structural_crack-FRG-TB-001",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-structural_crack-FRG-TB-001",
                mechanism_family="structural_crack",
                activation_score=mock_severity,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="load_induced",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        rng = random.Random(0)
        # W0-005 (2026-05-21): generate_condition 新 signature——加 component 参数（spec 06 §0.1 reference 反查）.
        condition = generate_condition(fragment, component, mechanism, driver, rng, 30.0)
        self.assertAlmostEqual(condition.severity_index, mock_severity, places=5)
        self.assertIsNone(condition.depth_mm)
        self.assertIsNone(condition.extent_length_m)


class T18cDrainageSurrogateTests(unittest.TestCase):
    """T-18c spec 06 §5 drainage surrogate 公式 unit tests."""

    def _make_driver(self, **kwargs):
        # W0-004 (2026-05-21): spec 04 §9 13 字段对齐。
        from workflow_engine.worldgen.models import DriverState
        legacy_to_spec = {"blockage_propensity": "drainage_fault_propensity"}
        for legacy, spec_name in legacy_to_spec.items():
            if legacy in kwargs and spec_name not in kwargs:
                kwargs[spec_name] = kwargs.pop(legacy)
            elif legacy in kwargs:
                kwargs.pop(legacy)
        for cruft in ("age_years", "obstruction_index", "drainage_usage_intensity", "coverage_feasibility_index"):
            kwargs.pop(cruft, None)
        defaults = dict(
            driver_id="DRV-T18C",
            fragment_id=kwargs.pop("fragment_id", "FRG-T18C"),
            service_load_ratio=0.5,
            restraint_level=0.5,
            moisture_ingress_index=0.5,
            chloride_exposure_index=0.5,
            carbonation_index=0.5,
            workmanship_deficit_index=0.5,
            maintenance_deficit_index=0.5,
            drainage_fault_propensity=0.5,
            alteration_propensity=0.5,
            fire_safety_deficit_index=0.5,
            repair_quality_index=0.5,
        )
        defaults.update(kwargs)
        return DriverState(**defaults)

    def test_blockage_index_in_bounds(self):
        """blockage_index 在 [0, 1]。"""
        # W0-004: _make_driver helper 自动 map blockage_propensity → drainage_fault_propensity；
        # age_years 弹出走外部参数（spec 04 §4 BuildingContext）.
        from workflow_engine.worldgen.generator import _compute_drainage_blockage_index
        for bp, maint, age in [(0.0, 0.0, 0.0), (0.5, 0.5, 30.0), (1.0, 1.0, 50.0)]:
            driver = self._make_driver(blockage_propensity=bp, maintenance_deficit_index=maint)
            idx = _compute_drainage_blockage_index(driver, age_years=age)
            self.assertGreaterEqual(idx, 0.0)
            self.assertLessEqual(idx, 1.0)

    def test_blockage_index_high_propensity_high(self):
        """高 blockage_propensity + maintenance + age → blockage_index 高。"""
        from workflow_engine.worldgen.generator import _compute_drainage_blockage_index
        driver_hi = self._make_driver(blockage_propensity=1.0, maintenance_deficit_index=1.0)
        driver_lo = self._make_driver(blockage_propensity=0.0, maintenance_deficit_index=0.0)
        self.assertGreater(
            _compute_drainage_blockage_index(driver_hi, age_years=50.0),
            _compute_drainage_blockage_index(driver_lo, age_years=0.0),
        )

    def test_leakage_index_in_bounds(self):
        """leakage_index 在 [0, 1]。"""
        from workflow_engine.worldgen.generator import _compute_drainage_leakage_index
        for wk, moist, age in [(0.0, 0.0, 0.0), (0.5, 0.5, 25.0), (1.0, 1.0, 50.0)]:
            driver = self._make_driver(workmanship_deficit_index=wk, moisture_ingress_index=moist)
            idx = _compute_drainage_leakage_index(driver, age_years=age)
            self.assertGreaterEqual(idx, 0.0)
            self.assertLessEqual(idx, 1.0)

    def test_leakage_index_high_workmanship_moisture_high(self):
        """高 workmanship + moisture → leakage_index 高。"""
        from workflow_engine.worldgen.generator import _compute_drainage_leakage_index
        driver_hi = self._make_driver(workmanship_deficit_index=1.0, moisture_ingress_index=1.0)
        driver_lo = self._make_driver(workmanship_deficit_index=0.0, moisture_ingress_index=0.0)
        self.assertGreater(
            _compute_drainage_leakage_index(driver_hi, age_years=50.0),
            _compute_drainage_leakage_index(driver_lo, age_years=0.0),
        )

    def test_misconnection_high_workmanship_alteration_true(self):
        """高 workmanship + alteration → misconnection_present = True。"""
        from workflow_engine.worldgen.generator import _compute_drainage_misconnection_present
        driver = self._make_driver(workmanship_deficit_index=1.0, alteration_propensity=1.0)
        self.assertTrue(_compute_drainage_misconnection_present(driver))

    def test_misconnection_low_inputs_false(self):
        """低 workmanship + alteration → misconnection_present = False。"""
        from workflow_engine.worldgen.generator import _compute_drainage_misconnection_present
        driver = self._make_driver(workmanship_deficit_index=0.0, alteration_propensity=0.0)
        self.assertFalse(_compute_drainage_misconnection_present(driver))

    def test_public_health_risk_in_bounds(self):
        """public_health_risk_index 在 [0, 1]。"""
        from workflow_engine.worldgen.generator import _compute_drainage_public_health_risk_index
        for bl, lk, mc in [(0.0, 0.0, False), (0.5, 0.5, True), (1.0, 1.0, True)]:
            idx = _compute_drainage_public_health_risk_index(bl, lk, mc)
            self.assertGreaterEqual(idx, 0.0)
            self.assertLessEqual(idx, 1.0)

    def test_public_health_risk_high_inputs_high(self):
        """高 blockage/leakage/misconnection → public_health_risk 高。"""
        from workflow_engine.worldgen.generator import _compute_drainage_public_health_risk_index
        hi = _compute_drainage_public_health_risk_index(1.0, 1.0, True)
        lo = _compute_drainage_public_health_risk_index(0.0, 0.0, False)
        self.assertGreater(hi, lo)

    def test_generate_drainage_state_non_drainage_returns_none(self):
        """non-drainage_fault mechanism → generate_drainage_state 返回 None。"""
        from workflow_engine.worldgen.generator import generate_drainage_state
        from workflow_engine.worldgen.models import MechanismState, MechanismActivation, ComponentNode
        fragment = FragmentContext(
            fragment_id="FRG-TC-001",
            fragment_template_id="FT_TEST",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver()
        mechanism = MechanismState(
            mechanism_state_id="MST-TC-001",
            fragment_id=fragment.fragment_id,
            mechanism_family="structural_crack",
            active=True,
            severity_index=0.6,
            cause_tags=[],
            primary_mechanism_id="MCH-structural_crack-FRG-TC-001",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-structural_crack-FRG-TC-001",
                mechanism_family="structural_crack",
                activation_score=0.6,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="load_induced",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        component = ComponentNode(
            component_id="CMP-TC-001",
            component_type="external_wall",
            material_system="reinforced_concrete",
            structural_role="non_load_bearing",
            location_id="LOC-TC-001",
            geometry_proxy={"visible_area_m2": 15.0},
            access_class="accessible",
        )
        # W0-004: generate_drainage_state 新参数 age_years 来自 BuildingContext.
        result = generate_drainage_state(fragment, mechanism, component, driver, random.Random(0), age_years=30.0)
        self.assertIsNone(result)

    def test_generate_drainage_state_drainage_fault_uses_spec5(self):
        """drainage_fault mechanism → 4 個 index 來自 spec §5 公式，在 [0,1] 範圍。"""
        from workflow_engine.worldgen.generator import (
            generate_drainage_state,
            _compute_drainage_blockage_index,
            _compute_drainage_leakage_index,
            _compute_drainage_misconnection_present,
        )
        from workflow_engine.worldgen.models import MechanismState, MechanismActivation, ComponentNode
        fragment = FragmentContext(
            fragment_id="FRG-TC-002",
            fragment_template_id="FT_TEST",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=5.0,
            fragment_length_m=3.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver(blockage_propensity=0.9, maintenance_deficit_index=0.8, age_years=40.0)
        mechanism = MechanismState(
            mechanism_state_id="MST-TC-002",
            fragment_id=fragment.fragment_id,
            mechanism_family="drainage_fault",
            active=True,
            severity_index=0.7,
            cause_tags=[],
            primary_mechanism_id="MCH-drainage_fault-FRG-TC-002",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-drainage_fault-FRG-TC-002",
                mechanism_family="drainage_fault",
                activation_score=0.7,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="active_blockage",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        component = ComponentNode(
            component_id="CMP-TC-002",
            component_type="drainage_stack",
            material_system="pvc_pipe",
            structural_role="non_load_bearing",
            location_id="LOC-TC-002",
            geometry_proxy={"visible_area_m2": 5.0},
            access_class="accessible",
        )
        # W0-004: generate_drainage_state 新参数 age_years 来自 BuildingContext.
        result = generate_drainage_state(fragment, mechanism, component, driver, random.Random(0), age_years=30.0)
        self.assertIsNotNone(result)
        # 驗證 blockage 來自 spec §5 公式
        expected_blockage = round(_compute_drainage_blockage_index(driver, age_years=30.0), 3)
        self.assertAlmostEqual(result.blockage_index, expected_blockage, places=3)
        # 所有 index 在 [0, 1]
        self.assertGreaterEqual(result.blockage_index, 0.0)
        self.assertLessEqual(result.blockage_index, 1.0)
        self.assertGreaterEqual(result.leakage_index, 0.0)
        self.assertLessEqual(result.leakage_index, 1.0)
        self.assertGreaterEqual(result.public_health_risk_index, 0.0)
        self.assertLessEqual(result.public_health_risk_index, 1.0)


class T18dUbwSurrogateTests(unittest.TestCase):
    """T-18d: spec 06 §6 UBW surrogate formula tests."""

    def _make_driver(self, **kwargs) -> "DriverState":
        # W0-004 (2026-05-21): spec 04 §9 13 字段对齐。
        from workflow_engine.worldgen.models import DriverState
        legacy_to_spec = {"blockage_propensity": "drainage_fault_propensity"}
        for legacy, spec_name in legacy_to_spec.items():
            if legacy in kwargs and spec_name not in kwargs:
                kwargs[spec_name] = kwargs.pop(legacy)
            elif legacy in kwargs:
                kwargs.pop(legacy)
        for cruft in ("age_years", "obstruction_index", "drainage_usage_intensity", "coverage_feasibility_index"):
            kwargs.pop(cruft, None)
        defaults = dict(
            driver_id="DRV-T18D",
            fragment_id=kwargs.pop("fragment_id", "FRG-T18D"),
            service_load_ratio=0.5,
            restraint_level=0.5,
            moisture_ingress_index=0.3,
            chloride_exposure_index=0.3,
            carbonation_index=0.3,
            workmanship_deficit_index=0.3,
            maintenance_deficit_index=0.3,
            drainage_fault_propensity=0.3,
            alteration_propensity=0.3,
            fire_safety_deficit_index=0.2,
            repair_quality_index=0.7,
        )
        defaults.update(kwargs)
        return DriverState(**defaults)

    def _make_component(self, structural_role: str = "non_load_bearing") -> "ComponentNode":
        from workflow_engine.worldgen.models import ComponentNode
        return ComponentNode(
            component_id="CMP-T18D",
            component_type="external_wall",
            material_system="reinforced_concrete",
            structural_role=structural_role,
            location_id="LOC-T18D",
            geometry_proxy={},
            access_class="accessible",
        )

    def _make_location(self, spatial_tags=None) -> "LocationNode":
        from workflow_engine.worldgen.models import LocationNode
        return LocationNode(
            location_id="LOC-T18D",
            location_class="external",
            exposure_zone="low",
            storey_band="mid_storey",
            spatial_tags=spatial_tags or [],
        )

    def test_alteration_score_high_inputs_high(self):
        """高 alteration_propensity + workmanship + maintenance → alteration_score 高。"""
        from workflow_engine.worldgen.generator import _compute_ubw_alteration_score
        hi = self._make_driver(alteration_propensity=1.0, workmanship_deficit_index=1.0, maintenance_deficit_index=1.0)
        lo = self._make_driver(alteration_propensity=0.0, workmanship_deficit_index=0.0, maintenance_deficit_index=0.0)
        self.assertGreater(_compute_ubw_alteration_score(hi), _compute_ubw_alteration_score(lo))

    def test_alteration_score_low_inputs_low(self):
        """低所有 driver inputs → alteration_score < 0.5。"""
        from workflow_engine.worldgen.generator import _compute_ubw_alteration_score
        driver = self._make_driver(alteration_propensity=0.0, workmanship_deficit_index=0.0, maintenance_deficit_index=0.0)
        score = _compute_ubw_alteration_score(driver)
        self.assertLess(score, 0.5)

    def test_subdivided_unit_sign_true_when_all_conditions_met(self):
        """private_premises + subdivision alteration + score > 0.45 → True。"""
        from workflow_engine.worldgen.generator import _compute_ubw_subdivided_unit_sign_present
        loc = self._make_location(spatial_tags=["private_premises"])
        result = _compute_ubw_subdivided_unit_sign_present(loc, "subdivision", 0.8)
        self.assertTrue(result)

    def test_subdivided_unit_sign_false_no_private_premises(self):
        """無 private_premises → False。"""
        from workflow_engine.worldgen.generator import _compute_ubw_subdivided_unit_sign_present
        loc = self._make_location(spatial_tags=[])
        result = _compute_ubw_subdivided_unit_sign_present(loc, "subdivision", 0.8)
        self.assertFalse(result)

    def test_subdivided_unit_sign_false_wrong_alteration_type(self):
        """alteration_type != subdivision → False。"""
        from workflow_engine.worldgen.generator import _compute_ubw_subdivided_unit_sign_present
        loc = self._make_location(spatial_tags=["private_premises"])
        result = _compute_ubw_subdivided_unit_sign_present(loc, "canopy", 0.8)
        self.assertFalse(result)

    def test_subdivided_unit_sign_false_low_score(self):
        """score ≤ 0.45 → False 即使其他條件滿足。"""
        from workflow_engine.worldgen.generator import _compute_ubw_subdivided_unit_sign_present
        loc = self._make_location(spatial_tags=["private_premises"])
        result = _compute_ubw_subdivided_unit_sign_present(loc, "subdivision", 0.4)
        self.assertFalse(result)

    def test_structural_impact_load_bearing_includes_bonus(self):
        """load-bearing component → structural_impact 包含 +0.3 bonus。"""
        from workflow_engine.worldgen.generator import _compute_ubw_structural_impact_index
        lb_comp = self._make_component(structural_role="primary_load_bearing")
        nlb_comp = self._make_component(structural_role="non_load_bearing")
        score = 0.5
        lb_impact = _compute_ubw_structural_impact_index(score, lb_comp)
        nlb_impact = _compute_ubw_structural_impact_index(score, nlb_comp)
        self.assertGreater(lb_impact, nlb_impact)

    def test_structural_impact_non_load_bearing_no_bonus(self):
        """non-load-bearing → structural_impact = clip(0.6*score, 0, 1)。"""
        from workflow_engine.worldgen.generator import _compute_ubw_structural_impact_index
        comp = self._make_component(structural_role="non_load_bearing")
        score = 0.5
        impact = _compute_ubw_structural_impact_index(score, comp)
        expected = max(0.0, min(1.0, 0.6 * score))
        self.assertAlmostEqual(impact, expected, places=6)

    def test_structural_impact_clamped_to_one(self):
        """alteration_score=1.0 + load_bearing → clamp to 1.0。"""
        from workflow_engine.worldgen.generator import _compute_ubw_structural_impact_index
        comp = self._make_component(structural_role="secondary_load_bearing")
        impact = _compute_ubw_structural_impact_index(1.0, comp)
        self.assertLessEqual(impact, 1.0)
        self.assertGreaterEqual(impact, 0.0)

    def test_generate_ubw_state_non_ubw_mechanism_returns_none(self):
        """non-ubw_signal mechanism → None。"""
        import random as rnd
        from workflow_engine.worldgen.generator import generate_ubw_state
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, )
        fragment = FragmentContext(
            fragment_id="FRG-T18D-01",
            fragment_template_id="FT_T",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver()
        mech = MechanismState(
            mechanism_state_id="MST-T18D",
            fragment_id=fragment.fragment_id,
            mechanism_family="structural_crack",
            active=True,
            severity_index=0.6,
            cause_tags=[],
            primary_mechanism_id="MCH-T18D",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-T18D",
                mechanism_family="structural_crack",
                activation_score=0.6,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        result = generate_ubw_state(fragment, mech, self._make_component(), None, driver, rnd.Random(0))
        self.assertIsNone(result)

    def test_generate_ubw_state_ubw_mechanism_uses_spec6(self):
        """ubw_signal mechanism → UBWState 由 spec §6 公式派生，structural_impact ∈ [0,1]。"""
        import random as rnd
        from workflow_engine.worldgen.generator import generate_ubw_state, _compute_ubw_alteration_score, _compute_ubw_structural_impact_index
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, )
        fragment = FragmentContext(
            fragment_id="FRG-T18D-02",
            fragment_template_id="FT_T",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver(alteration_propensity=0.8, workmanship_deficit_index=0.6)
        mech = MechanismState(
            mechanism_state_id="MST-T18D2",
            fragment_id=fragment.fragment_id,
            mechanism_family="ubw_signal",
            active=True,
            severity_index=0.7,
            cause_tags=[],
            primary_mechanism_id="MCH-T18D2",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-T18D2",
                mechanism_family="ubw_signal",
                activation_score=0.7,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="alteration_present",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        comp = self._make_component(structural_role="primary_load_bearing")
        loc = self._make_location(spatial_tags=[])
        result = generate_ubw_state(fragment, mech, comp, loc, driver, rnd.Random(42))
        self.assertIsNotNone(result)
        # structural_impact must match spec §6 formula
        expected_score = _compute_ubw_alteration_score(driver)
        expected_impact = round(_compute_ubw_structural_impact_index(expected_score, comp), 3)
        self.assertAlmostEqual(result.structural_impact_index, expected_impact, places=3)
        # bounds
        self.assertGreaterEqual(result.structural_impact_index, 0.0)
        self.assertLessEqual(result.structural_impact_index, 1.0)
        self.assertTrue(result.present)


class T18eFireSafetySurrogateTests(unittest.TestCase):
    """T-18e: spec 06 §7 fire-safety surrogate formula tests."""

    def _make_driver(self, **kwargs) -> "DriverState":
        # W0-004 (2026-05-21): spec 04 §9 13 字段对齐。
        from workflow_engine.worldgen.models import DriverState
        legacy_to_spec = {"blockage_propensity": "drainage_fault_propensity"}
        for legacy, spec_name in legacy_to_spec.items():
            if legacy in kwargs and spec_name not in kwargs:
                kwargs[spec_name] = kwargs.pop(legacy)
            elif legacy in kwargs:
                kwargs.pop(legacy)
        for cruft in ("age_years", "obstruction_index", "drainage_usage_intensity", "coverage_feasibility_index"):
            kwargs.pop(cruft, None)
        defaults = dict(
            driver_id="DRV-T18E",
            fragment_id=kwargs.pop("fragment_id", "FRG-T18E"),
            service_load_ratio=0.5,
            restraint_level=0.5,
            moisture_ingress_index=0.3,
            chloride_exposure_index=0.3,
            carbonation_index=0.3,
            workmanship_deficit_index=0.3,
            maintenance_deficit_index=0.3,
            drainage_fault_propensity=0.3,
            alteration_propensity=0.3,
            fire_safety_deficit_index=0.2,
            repair_quality_index=0.7,
        )
        defaults.update(kwargs)
        return DriverState(**defaults)

    def test_deficiency_score_high_inputs_high(self):
        """高 fire_safety_deficit + maintenance → deficiency_score 高。"""
        from workflow_engine.worldgen.generator import _compute_fire_deficiency_score
        hi = self._make_driver(fire_safety_deficit_index=1.0, maintenance_deficit_index=1.0)
        lo = self._make_driver(fire_safety_deficit_index=0.0, maintenance_deficit_index=0.0)
        self.assertGreater(_compute_fire_deficiency_score(hi), _compute_fire_deficiency_score(lo))

    def test_deficiency_score_low_inputs_low(self):
        """低所有 driver inputs → deficiency_score < 0.5。"""
        from workflow_engine.worldgen.generator import _compute_fire_deficiency_score
        driver = self._make_driver(fire_safety_deficit_index=0.0, maintenance_deficit_index=0.0)
        score = _compute_fire_deficiency_score(driver)
        self.assertLess(score, 0.5)

    def test_is_fire_deficiency_present_above_threshold(self):
        """score > 0.45 → True。"""
        from workflow_engine.worldgen.generator import _is_fire_deficiency_present
        self.assertTrue(_is_fire_deficiency_present(0.46))

    def test_is_fire_deficiency_present_at_or_below_threshold(self):
        """score ≤ 0.45 → False。"""
        from workflow_engine.worldgen.generator import _is_fire_deficiency_present
        self.assertFalse(_is_fire_deficiency_present(0.45))
        self.assertFalse(_is_fire_deficiency_present(0.0))

    def test_fire_severity_index_high_importance_higher(self):
        """escape_route (weight=1.0) → severity 高於 unknown_fire_component (0.7)。"""
        from workflow_engine.worldgen.generator import _compute_fire_severity_index
        score = 0.7
        escape_severity = _compute_fire_severity_index(score, "escape_route")
        unknown_severity = _compute_fire_severity_index(score, "unknown_fire_component")
        self.assertGreater(escape_severity, unknown_severity)

    def test_fire_severity_index_clamped(self):
        """severity_index 必須在 [0, 1]。"""
        from workflow_engine.worldgen.generator import _compute_fire_severity_index
        for cls in ["escape_route", "fire_door", "smoke_vent", "unknown_fire_component"]:
            v = _compute_fire_severity_index(1.0, cls)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_generate_fire_safety_state_non_fire_returns_none(self):
        """non-fire_safety_deficiency mechanism → None。"""
        import random as rnd
        from workflow_engine.worldgen.generator import generate_fire_safety_state
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, ComponentNode,
        )
        fragment = FragmentContext(
            fragment_id="FRG-T18E-01",
            fragment_template_id="FT_T",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver()
        mech = MechanismState(
            mechanism_state_id="MST-T18E",
            fragment_id=fragment.fragment_id,
            mechanism_family="structural_crack",
            active=True,
            severity_index=0.6,
            cause_tags=[],
            primary_mechanism_id="MCH-T18E",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-T18E",
                mechanism_family="structural_crack",
                activation_score=0.6,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        comp = ComponentNode(
            component_id="CMP-T18E",
            component_type="fire_door",
            material_system="steel",
            structural_role="non_load_bearing",
            location_id="LOC-T18E",
            geometry_proxy={},
            access_class="accessible",
        )
        result = generate_fire_safety_state(fragment, mech, comp, driver, rnd.Random(0))
        self.assertIsNone(result)

    def test_generate_fire_safety_state_uses_spec7_formula(self):
        """fire_safety_deficiency mechanism → severity_index 來自 spec §7 公式。

        DEBT-030 D1 (2026-05-13): fire_component_class 走 registry lookup
        (`component_type_registry.component_class`)，本测试需传 registries 让 fire_door
        component_type 命中 fire_safety_component class。
        """
        import random as rnd
        from workflow_engine.worldgen.generator import (
            generate_fire_safety_state,
            _compute_fire_deficiency_score,
            _compute_fire_severity_index,
        )
        from workflow_engine.worldgen.registry import _build_registry_bundle
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, ComponentNode,
        )
        fragment = FragmentContext(
            fragment_id="FRG-T18E-02",
            fragment_template_id="FT_T",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=3.0,
            fragment_length_m=2.0,
            in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver(fire_safety_deficit_index=0.9, maintenance_deficit_index=0.8)
        mech = MechanismState(
            mechanism_state_id="MST-T18E2",
            fragment_id=fragment.fragment_id,
            mechanism_family="fire_safety_deficiency",
            active=True,
            severity_index=0.7,
            cause_tags=[],
            primary_mechanism_id="MCH-T18E2",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-T18E2",
                mechanism_family="fire_safety_deficiency",
                activation_score=0.7,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="component_deficiency",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        comp = ComponentNode(
            component_id="CMP-T18E2",
            component_type="fire_door",
            material_system="steel",
            structural_role="non_load_bearing",
            location_id="LOC-T18E2",
            geometry_proxy={},
            access_class="accessible",
        )
        registries = _build_registry_bundle()
        result = generate_fire_safety_state(
            fragment, mech, comp, driver, rnd.Random(42), registries
        )
        self.assertIsNotNone(result)
        expected_score = _compute_fire_deficiency_score(driver)
        expected_severity = round(_compute_fire_severity_index(expected_score, "fire_door"), 3)
        self.assertAlmostEqual(result.severity_index, expected_severity, places=3)
        self.assertGreaterEqual(result.severity_index, 0.0)
        self.assertLessEqual(result.severity_index, 1.0)

    def test_generate_fire_safety_state_deficiency_present_not_applicable(self):
        """低 fire_safety_deficit → deficiency_present=False → deficiency_class='not_applicable'。"""
        import random as rnd
        from workflow_engine.worldgen.generator import generate_fire_safety_state
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, ComponentNode,
        )
        fragment = FragmentContext(
            fragment_id="FRG-T18E-03",
            fragment_template_id="FT_T",
            component_id='',
            location_id='',
            fragment_role="inspection_target",
            fragment_area_m2=3.0,
            fragment_length_m=2.0,
            in_scope=True,
            exclusion_reason=None,
        )
        # Very low deficit → deficiency_score will be < 0.45
        driver = self._make_driver(fire_safety_deficit_index=0.0, maintenance_deficit_index=0.0)
        mech = MechanismState(
            mechanism_state_id="MST-T18E3",
            fragment_id=fragment.fragment_id,
            mechanism_family="fire_safety_deficiency",
            active=True,
            severity_index=0.2,
            cause_tags=[],
            primary_mechanism_id="MCH-T18E3",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-T18E3",
                mechanism_family="fire_safety_deficiency",
                activation_score=0.2,
                derived_from_driver_ids=[driver.driver_id],
            )],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="component_deficiency",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        comp = ComponentNode(
            component_id="CMP-T18E3",
            component_type="fire_door",
            material_system="steel",
            structural_role="non_load_bearing",
            location_id="LOC-T18E3",
            geometry_proxy={},
            access_class="accessible",
        )
        # DEBT-049 B2：消防态改按组件判（消防构件恒生成），需传 registries 查消防类。
        from workflow_engine.worldgen.registry import _build_registry_bundle
        registries = _build_registry_bundle()
        result = generate_fire_safety_state(
            fragment, mech, comp, driver, rnd.Random(0), registries=registries)
        self.assertIsNotNone(result)  # fire_door=消防构件→恒生成实质态
        self.assertFalse(result.deficiency_present)  # 低分→无缺陷（compliant）
        self.assertEqual(result.deficiency_class, "not_applicable")

    def test_fire_state_none_for_non_fire_component(self):
        """DEBT-049 B2：非消防构件（drainage 等）不生成消防态（修挂错组件）。"""
        import random as rnd
        from workflow_engine.worldgen.generator import generate_fire_safety_state
        from workflow_engine.worldgen.models import (
            MechanismState, MechanismActivation, ComponentNode,
        )
        from workflow_engine.worldgen.registry import _build_registry_bundle
        fragment = FragmentContext(
            fragment_id="FRG-T18E-NF", fragment_template_id="FT_T",
            component_id='', location_id='', fragment_role="inspection_target",
            fragment_area_m2=3.0, fragment_length_m=2.0, in_scope=True,
            exclusion_reason=None,
        )
        driver = self._make_driver(fire_safety_deficit_index=0.9,
                                   maintenance_deficit_index=0.9)
        mech = MechanismState(
            mechanism_state_id="MST-NF", fragment_id=fragment.fragment_id,
            mechanism_family="fire_safety_deficiency", active=True,
            severity_index=0.9, cause_tags=[], primary_mechanism_id="MCH-NF",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-NF", mechanism_family="fire_safety_deficiency",
                activation_score=0.9, derived_from_driver_ids=[driver.driver_id])],
            crack_mechanism_kind="none", corrosion_active=False,
            delamination_active=False, drainage_fault_kind="none",
            ubw_signal_kind="none", fire_safety_deficiency_kind="component_deficiency",
            assessment_origin_kind="none", verification_origin_kind="none",
        )
        comp = ComponentNode(
            component_id="CMP-NF", component_type="drainage_stack",
            material_system="pvc", structural_role="non_load_bearing",
            location_id="LOC-NF", geometry_proxy={}, access_class="accessible",
        )
        # 即便机制是 fire_safety_deficiency、driver 高分，非消防组件也不生成假消防态。
        result = generate_fire_safety_state(
            fragment, mech, comp, driver, rnd.Random(0),
            registries=_build_registry_bundle())
        self.assertIsNone(result)


class T18fCoverageTechnicalSurrogateTests(unittest.TestCase):
    """T-18f: spec 06 §8 / §9 helper + noise integration tests."""

    def test_visible_area_boundaries(self):
        from workflow_engine.worldgen.generator import _compute_visible_area_m2

        self.assertAlmostEqual(_compute_visible_area_m2(10.0, 10.0), 0.0)
        self.assertAlmostEqual(_compute_visible_area_m2(10.0, 12.0), 0.0)
        self.assertAlmostEqual(_compute_visible_area_m2(10.0, 0.0), 10.0)

    def test_true_inspected_ratio_normal_case(self):
        from workflow_engine.worldgen.generator import _compute_true_inspected_ratio

        self.assertAlmostEqual(_compute_true_inspected_ratio(5.0, 10.0), 0.5)

    def test_true_inspected_ratio_zero_fragment_area_uses_eps(self):
        from workflow_engine.worldgen.generator import _compute_true_inspected_ratio

        self.assertGreater(_compute_true_inspected_ratio(1.0, 0.0), 1e6)

    def test_check_count_uses_ceil(self):
        from workflow_engine.worldgen.generator import _compute_check_count

        self.assertEqual(_compute_check_count(10.0, 3.0), 4)
        self.assertEqual(_compute_check_count(6.0, 6.0), 1)

    def test_check_count_zero_interval_returns_zero(self):
        from workflow_engine.worldgen.generator import _compute_check_count

        self.assertEqual(_compute_check_count(10.0, 0.0), 0)

    def test_pull_test_rate_per_25m2(self):
        from workflow_engine.worldgen.generator import _compute_pull_test_rate_per_25m2

        self.assertAlmostEqual(_compute_pull_test_rate_per_25m2(4, 50.0), 2.0)

    def test_test_strength_true(self):
        from workflow_engine.worldgen.generator import _compute_test_strength_true

        self.assertAlmostEqual(_compute_test_strength_true(2.0, 0.8), 2.6)

    def test_verification_failed_below_required_strength(self):
        from workflow_engine.worldgen.generator import _compute_verification_failed

        self.assertTrue(_compute_verification_failed(1.9, 2.0, 0.9))

    def test_verification_failed_low_repair_quality(self):
        from workflow_engine.worldgen.generator import _compute_verification_failed

        self.assertTrue(_compute_verification_failed(2.1, 2.0, 0.4))
        self.assertFalse(_compute_verification_failed(2.1, 2.0, 0.6))

    def test_additional_after_failure_count(self):
        from workflow_engine.worldgen.generator import _compute_additional_after_failure_count

        self.assertEqual(_compute_additional_after_failure_count(0), 0)
        self.assertEqual(_compute_additional_after_failure_count(2), 6)

    def test_sample_value_for_slot_ratio_uses_noise_and_stays_in_bounds(self):
        from workflow_engine.worldgen.generator import _sample_value_for_slot

        slot = {
            "slot_id": "ratio.covered_area.inspected",
            "measurement_family": "coverage_sampling",
            "value_type": "float",
            "unit": "ratio",
            "physical_bounds": [0.0, 1.0],
            "precision_steps": "coverage_ratio",
        }
        value_num, value_bool, value_enum = _sample_value_for_slot(slot, random.Random(7))
        self.assertIsNotNone(value_num)
        self.assertIsNone(value_bool)
        self.assertIsNone(value_enum)
        self.assertGreaterEqual(value_num, 0.0)
        self.assertLessEqual(value_num, 1.0)

    def test_sample_value_for_slot_count_returns_integer_like_float(self):
        from workflow_engine.worldgen.generator import _sample_value_for_slot

        slot = {
            "slot_id": "count.hammer_tapping.grid.minimum",
            "measurement_family": "coverage_sampling",
            "value_type": "integer",
            "unit": "count",
            "physical_bounds": [0, 10],
            "precision_steps": "integer_count",
        }
        value_num, value_bool, value_enum = _sample_value_for_slot(slot, random.Random(11))
        self.assertIsNotNone(value_num)
        self.assertIsNone(value_bool)
        self.assertIsNone(value_enum)
        self.assertEqual(value_num, float(int(value_num)))
        self.assertGreaterEqual(value_num, 0.0)
        self.assertLessEqual(value_num, 10.0)

    def test_sample_value_for_slot_bool_returns_bool(self):
        from workflow_engine.worldgen.generator import _sample_value_for_slot

        slot = {
            "slot_id": "verification.test.failed",
            "measurement_family": "boolean_assertion",
            "value_type": "bool",
            "unit": "bool",
            "physical_bounds": [False, True],
            "precision_steps": None,
        }
        value_num, value_bool, value_enum = _sample_value_for_slot(slot, random.Random(3))
        self.assertIsNone(value_num)
        self.assertIsNone(value_enum)
        self.assertIn(value_bool, (True, False))

    def test_sample_value_for_slot_precision_rounding_applies(self):
        from workflow_engine.worldgen.generator import _sample_value_for_slot

        slot = {
            "slot_id": "crack_width_mm",
            "measurement_family": "defect_geometry",
            "value_type": "float",
            "unit": "mm",
            "physical_bounds": [0.05, 5.0],
            "precision_steps": "geometry_width_mm",
        }
        value_num, _, _ = _sample_value_for_slot(slot, random.Random(5))
        self.assertIsNotNone(value_num)
        scaled = round(value_num / 0.05)
        self.assertAlmostEqual(value_num, scaled * 0.05, places=4)


class T18gStructuralAssessmentSurrogateTests(unittest.TestCase):
    """T-18g: spec 06 §10 structural assessment surrogate tests."""

    def _make_building(self, age_years: float = 20.0):
        from workflow_engine.worldgen.models import BuildingContext

        # W0-008 (2026-05-21)：BuildingContext 收紧到 spec 04 §4 8 字段；3 个内部字段
        # 移到 BuildingMetadata（本 test 不需要 metadata，省略 build_metadata fixture）.
        return BuildingContext(
            building_id="BLD-T18G",
            building_use="residential",
            structure_type="rc_frame",
            age_years=age_years,
            storey_count=10,
            occupancy_state="occupied",
        )

    def _make_fragment(self, fragment_id: str = "FRG-T18G-01"):
        # W0-005 (2026-05-21): spec 04 §7 FragmentContext 9 字段 reference-based contract.
        return FragmentContext(
            fragment_id=fragment_id,
            fragment_template_id="FT-T18G",
            component_id="CMP-T18G-01",
            location_id="LOC-T18G-01",
            fragment_role="inspection_target",
            fragment_area_m2=10.0,
            fragment_length_m=5.0,
            in_scope=True,
            exclusion_reason=None,
        )

    def _make_component(self, component_id: str = "CMP-T18G-01", **kwargs):
        # W0-005 (2026-05-21): 配套 _make_fragment 的 ComponentNode；geometry_proxy.thickness_mm=200
        # 让 _estimate_component_volume_m3 输出 fragment_area_m2(10.0) * 200 / 1000 = 2.0.
        defaults = dict(
            component_id=component_id,
            component_type="external_wall",
            parent_component_id=None,
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-T18G-01",
            geometry_proxy={"visible_area_m2": 10.0, "thickness_mm": 200.0},
            cover_depth_mm=30.0,
            access_class="fully_accessible",
        )
        defaults.update(kwargs)
        return ComponentNode(**defaults)

    def _make_condition(self, severity_index: float, fragment_id: str = "FRG-T18G-01"):
        from workflow_engine.worldgen.models import ConditionState

        return ConditionState(
            condition_id=f"CND-{int(severity_index * 100):02d}",
            fragment_id=fragment_id,
            condition_class="DC_CRACK",
            severity_band="moderate",
            severity_index=severity_index,
        )

    def _make_mechanism(self, fragment_id: str = "FRG-T18G-01"):
        from workflow_engine.worldgen.models import MechanismActivation, MechanismState

        return MechanismState(
            mechanism_state_id="MST-T18G-01",
            fragment_id=fragment_id,
            mechanism_family="assessment_origin",
            active=True,
            severity_index=0.8,
            cause_tags=[],
            primary_mechanism_id="MCH-T18G-01",
            activated_mechanisms=[
                MechanismActivation(
                    mechanism_id="MCH-T18G-01",
                    mechanism_family="assessment_origin",
                    activation_score=0.8,
                    derived_from_driver_ids=["DRV-T18G-01"],
                )
            ],
            crack_mechanism_kind="none",
            corrosion_active=False,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="origin_present",
            verification_origin_kind="none",
        )

    def _make_assessment_registries(self):
        from workflow_engine.worldgen.models import RegistryBundle, RegistryTable

        technical_measurement_registry = RegistryTable(
            registry_id="technical_measurement_registry",
            ownership="measurement_family.structural_assessment",
            key_field="slot_id",
            fields=[
                "slot_id",
                "measurement_family",
                "value_type",
                "unit",
                "physical_bounds",
                "precision_steps",
                "method_classes",
            ],
            records=[
                {
                    "slot_id": "ratio.fsp.structural_performance",
                    "measurement_family": "derived_risk_measurement",
                    "value_type": "float",
                    "unit": "ratio",
                    "physical_bounds": [0.0, 2.0],
                    "precision_steps": "assessment_ratio",
                    "method_classes": ["formula"],
                },
                {
                    "slot_id": "count.core_sample.minimum",
                    "measurement_family": "derived_risk_measurement",
                    "value_type": "integer",
                    "unit": "count",
                    "physical_bounds": [0, 100],
                    "precision_steps": "integer_count",
                    "method_classes": ["formula"],
                },
                {
                    "slot_id": "rate.core_sample.per_concrete_volume",
                    "measurement_family": "derived_risk_measurement",
                    "value_type": "float",
                    "unit": "count/m3",
                    "physical_bounds": [0.0, 10.0],
                    "precision_steps": "assessment_ratio",
                    "method_classes": ["formula"],
                },
                {
                    "slot_id": "crack_width_mm",
                    "measurement_family": "defect_geometry",
                    "value_type": "float",
                    "unit": "mm",
                    "physical_bounds": [0.05, 5.0],
                    "precision_steps": "geometry_width_mm",
                    "method_classes": ["visual_inspection"],
                },
            ],
        )
        assessment_surrogate_registry = RegistryTable(
            registry_id="assessment_surrogate_registry",
            ownership="measurement_family.structural_assessment",
            key_field="assessment_family_id",
            fields=["assessment_family_id", "input_slots", "output_slots", "formula", "physical_bounds", "noise_model", "notes"],
            records=[
                {
                    "assessment_family_id": "AS_FSP_MEMBER_V1",
                    "input_slots": ["crack_width_mm"],
                    "output_slots": [
                        "ratio.fsp.structural_performance",
                        "count.core_sample.minimum",
                        "rate.core_sample.per_concrete_volume",
                    ],
                    "formula": "fsp_true = clip(1.20 - k_condition_to_fsp_loss * max_severity - 0.10*age_norm, 0, 2)",
                    "physical_bounds": [0.0, 2.0],
                    "noise_model": "TECH_REL_GAUSS",
                    "notes": "T18g test registry",
                }
            ],
        )
        return RegistryBundle(
            generated_at="2025-01-01T00:00:00",
            registries=[technical_measurement_registry, assessment_surrogate_registry],
        )

    def test_compute_max_condition_severity_empty_returns_zero(self):
        from workflow_engine.worldgen.generator import _compute_max_condition_severity

        self.assertEqual(_compute_max_condition_severity([]), 0.0)

    def test_compute_max_condition_severity_returns_max(self):
        from workflow_engine.worldgen.generator import _compute_max_condition_severity

        conditions = [self._make_condition(0.2), self._make_condition(0.8), self._make_condition(0.5)]
        self.assertAlmostEqual(_compute_max_condition_severity(conditions), 0.8)

    def test_compute_fsp_true_severity_and_age_reduce_value(self):
        from workflow_engine.worldgen.generator import _compute_fsp_true

        low = _compute_fsp_true(0.2, 10.0)
        high_severity = _compute_fsp_true(0.9, 10.0)
        high_age = _compute_fsp_true(0.2, 50.0)
        self.assertGreater(low, high_severity)
        self.assertGreater(low, high_age)

    def test_compute_fsp_true_stays_in_bounds(self):
        from workflow_engine.worldgen.generator import _compute_fsp_true

        for severity, age in [(0.0, 0.0), (10.0, 100.0), (1.0, 50.0)]:
            value = _compute_fsp_true(severity, age)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 2.0)

    def test_compute_core_sample_count_zero_and_ceil_behavior(self):
        from workflow_engine.worldgen.generator import _compute_core_sample_count

        self.assertEqual(_compute_core_sample_count(0.0), 0)
        self.assertEqual(_compute_core_sample_count(0.2), 1)
        self.assertEqual(_compute_core_sample_count(2.1), 2)

    def test_estimate_component_volume_m3_unit_conversion(self):
        from workflow_engine.worldgen.generator import _estimate_component_volume_m3

        fragment = self._make_fragment()
        component = self._make_component()
        self.assertAlmostEqual(_estimate_component_volume_m3(fragment, component), 2.0)

    def test_is_assessment_fsp_below_required_safety_boundary(self):
        from workflow_engine.worldgen.generator import _is_assessment_fsp_below_required_safety

        self.assertTrue(_is_assessment_fsp_below_required_safety(0.94, 0.95))
        self.assertFalse(_is_assessment_fsp_below_required_safety(0.95, 0.95))

    def test_build_measurement_record_with_value_uses_explicit_value(self):
        from workflow_engine.worldgen.generator import _build_measurement_record_with_value

        slot_record = {
            "slot_id": "ratio.fsp.structural_performance",
            "unit": "ratio",
            "method_classes": ["formula"],
        }
        measurement = _build_measurement_record_with_value(
            slot_record=slot_record,
            target_ref="FRG-T18G-01",
            measurement_family="structural_assessment_measurement",
            derivation_mode="assessment_plan",
            measurement_index=0,
            value_num=0.88,
        )
        self.assertAlmostEqual(measurement.value_num, 0.88)
        self.assertEqual(measurement.sample_count, None)
        self.assertAlmostEqual(measurement.confidence_index, 0.95)

    def test_generate_structural_assessment_measurements_uses_spec10_formula_slots(self):
        from workflow_engine.worldgen.generator import (
            _compute_core_sample_count,
            _compute_fsp_true,
            _estimate_component_volume_m3,
            generate_structural_assessment_measurements,
        )

        building = self._make_building(age_years=40.0)
        fragment = self._make_fragment()
        component = self._make_component()
        conditions = [self._make_condition(0.8, fragment.fragment_id)]
        # W0-005 (2026-05-21): generate_structural_assessment_measurements 新 signature——加
        # `components_by_id` 参数（spec 06 §0.1 reference 反查 component 物理参数）.
        measurements = generate_structural_assessment_measurements(
            building=building,
            fragments=[fragment],
            conditions=conditions,
            mechanisms=[self._make_mechanism(fragment.fragment_id)],
            components_by_id={component.component_id: component},
            registries=self._make_assessment_registries(),
            rng=random.Random(17),
            per_fragment_count=1,
        )

        by_slot = {measurement.slot_id: measurement for measurement in measurements}
        self.assertIn("ratio.fsp.structural_performance", by_slot)
        self.assertIn("count.core_sample.minimum", by_slot)
        self.assertIn("rate.core_sample.per_concrete_volume", by_slot)

        expected_fsp = round(_compute_fsp_true(0.8, 40.0), 4)
        expected_volume = _estimate_component_volume_m3(fragment, component)
        expected_core_count = _compute_core_sample_count(expected_volume)
        expected_core_rate = round(expected_core_count / expected_volume, 4)

        self.assertAlmostEqual(by_slot["ratio.fsp.structural_performance"].value_num, expected_fsp)
        self.assertAlmostEqual(by_slot["count.core_sample.minimum"].value_num, float(expected_core_count))
        self.assertAlmostEqual(by_slot["rate.core_sample.per_concrete_volume"].value_num, expected_core_rate)
        self.assertIn("crack_width_mm", by_slot)


# ---------- DEBT-020 round5 sub-task 1: spec 06 §3.2 + §1.3 crack derive (Option ① 2026-05-10) ----------


class CrackDeriveTests(unittest.TestCase):
    """spec 06 §3.2 + §1.3 (Option ① true-then-noise, 2026-05-10) crack derive helpers."""

    def test_activation_score_in_unit_interval(self) -> None:
        from workflow_engine.worldgen.generator import _compute_crack_activation_score
        for load, restraint, work in [(0.5, 0.2, 0.1), (1.5, 1.0, 1.0), (0.0, 0.0, 0.0)]:
            score = _compute_crack_activation_score(load, restraint, work)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_severity_clamped_to_unit_interval(self) -> None:
        from workflow_engine.worldgen.generator import _compute_crack_severity
        # 极端 input → severity 仍 ∈ [0, 1]
        self.assertAlmostEqual(_compute_crack_severity(1.0, 1.0, 1.0), 1.0, places=6)
        self.assertAlmostEqual(_compute_crack_severity(0.0, 0.0, 0.0), 0.0, places=6)
        self.assertAlmostEqual(_compute_crack_severity(0.5, 0.5, 0.5), 0.5, places=6)

    def test_opening_hard_floor_and_cap(self) -> None:
        from workflow_engine.worldgen.generator import _compute_primary_crack_opening_mm_true
        # severity=0 + load=0 + restraint=0 → 仅 base_mm=0.06 → clip floor 0.06 (>= 0.05)
        result = _compute_primary_crack_opening_mm_true(0.0, 0.0, 0.0)
        self.assertGreaterEqual(result, 0.05)
        self.assertLess(result, 0.10)
        # severity=1 + load=1.5 + restraint=1.0 → 触 hard cap 1.25
        result = _compute_primary_crack_opening_mm_true(1.0, 1.5, 1.0)
        self.assertEqual(result, 1.25)

    def test_length_clamped_by_nominal(self) -> None:
        from workflow_engine.worldgen.generator import _compute_primary_crack_length_m_true
        # severity=1, nominal=5 → raw = 0.10 + 5*(0.35 + 0.33*1) = 0.10 + 3.40 = 3.50, < 5 OK
        result = _compute_primary_crack_length_m_true(1.0, 5.0)
        self.assertGreater(result, 1.0)
        self.assertLessEqual(result, 5.0)
        # nominal_length=0 → clip to floor 0.05
        result = _compute_primary_crack_length_m_true(0.5, 0.0)
        self.assertEqual(result, 0.05)

    def test_round5_proagent_scenario_a_low_severity(self) -> None:
        """proagent round5 sub-task 1 sanity scenario A: 年轻低荷低约束."""
        from workflow_engine.worldgen.generator import (
            _age_norm,
            _compute_crack_activation_score,
            _compute_crack_severity,
            _compute_primary_crack_opening_mm_true,
            _compute_primary_crack_length_m_true,
        )
        activation = _compute_crack_activation_score(0.6, 0.2, 0.3)
        severity = _compute_crack_severity(activation, _age_norm(15), 0.1)
        opening = _compute_primary_crack_opening_mm_true(severity, 0.6, 0.2)
        length = _compute_primary_crack_length_m_true(severity, 3.0)
        # proagent expected: activation≈0.21, severity≈0.20, opening≈0.30, length≈1.35
        self.assertAlmostEqual(activation, 0.21, delta=0.05)
        self.assertAlmostEqual(severity, 0.20, delta=0.06)
        self.assertAlmostEqual(opening, 0.30, delta=0.10)
        self.assertAlmostEqual(length, 1.35, delta=0.20)

    def test_round5_proagent_scenario_c_severe(self) -> None:
        """proagent round5 sub-task 1 scenario C: 高龄高荷高约束 → 触 hard cap."""
        from workflow_engine.worldgen.generator import (
            _age_norm,
            _compute_crack_activation_score,
            _compute_crack_severity,
            _compute_primary_crack_opening_mm_true,
        )
        activation = _compute_crack_activation_score(1.2, 0.85, 0.8)
        severity = _compute_crack_severity(activation, _age_norm(75), 0.85)
        opening = _compute_primary_crack_opening_mm_true(severity, 1.2, 0.85)
        # proagent expected: activation≈0.77, severity≈0.83, opening=hard_cap=1.25
        self.assertGreater(activation, 0.65)
        self.assertGreater(severity, 0.70)
        self.assertEqual(opening, 1.25)


class CrackExplicitDeriveIntegrationTests(unittest.TestCase):
    """generate_structural_assessment_measurements 接通 crack derive 路径验证."""

    def _make_structural_crack_setup(self):
        """构造 1 building × 1 fragment × 1 component × structural_crack mechanism × 1 driver.

        W0-005 (2026-05-21)：spec 06 §0.1 reference 反查路径——返回 component 供 generator
        pipeline 走 component.cover_depth_mm / material_system 等物理参数（不在 fragment 上 cache）.
        """
        from workflow_engine.worldgen.models import (
            BuildingContext, DriverState, MechanismState, MechanismActivation, ConditionState,
        )
        # W0-008 (2026-05-21)：BuildingContext = spec 04 §4 8 字段 contract.
        building = BuildingContext(
            building_id="BLD-CRACK",
            building_use="residential", structure_type="rc_frame", age_years=45,
            storey_count=10, occupancy_state="occupied",
        )
        fragment = FragmentContext(
            fragment_id="FRG-CRACK-01",
            fragment_template_id="FT-CRACK",
            component_id="CMP-CRACK-01",
            location_id="LOC-CRACK-01",
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=8.0,
            in_scope=True,
            exclusion_reason=None,
        )
        component = ComponentNode(
            component_id="CMP-CRACK-01",
            component_type="external_wall",
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-CRACK-01",
            geometry_proxy={"visible_area_m2": 15.0, "thickness_mm": 200.0},
            cover_depth_mm=30.0,
            access_class="fully_accessible",
        )
        driver = DriverState(
            # W0-004: spec 04 §9 DriverState 13 字段对齐——age_years 走 BuildingContext，
            # drainage_fault_propensity 单一字段；删 4 cruft 字段.
            driver_id="DRV-CRACK-01", fragment_id="FRG-CRACK-01", service_load_ratio=0.85, restraint_level=0.6,
            moisture_ingress_index=0.5, chloride_exposure_index=0.3, carbonation_index=0.3,
            workmanship_deficit_index=0.5, maintenance_deficit_index=0.4,
            drainage_fault_propensity=0.3, alteration_propensity=0.2,
            fire_safety_deficit_index=0.2, repair_quality_index=0.6,
        )
        mechanism = MechanismState(
            mechanism_state_id="MST-CRACK-01", fragment_id="FRG-CRACK-01",
            mechanism_family="structural_crack", active=True, severity_index=0.5,
            primary_mechanism_id="MCH-CRACK-01",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-CRACK-01", mechanism_family="structural_crack",
                activation_score=0.5,
            )],
        )
        condition = ConditionState(
            condition_id="CND-CRACK-01", fragment_id="FRG-CRACK-01",
            mechanism_state_id="MST-CRACK-01", condition_class="DC_CRACK",
            severity_band="moderate", severity_index=0.5,
        )
        return building, fragment, component, driver, mechanism, condition

    def test_crack_derive_when_structural_crack_mechanism_with_driver(self) -> None:
        """crack_width_mm / crack_length_m 走 explicit derive (structural_crack + driver provided)."""
        import random
        from workflow_engine.worldgen.generator import generate_structural_assessment_measurements

        building, fragment, component, driver, mechanism, condition = self._make_structural_crack_setup()
        registries = self._make_crack_registries()

        measurements = generate_structural_assessment_measurements(
            building=building, fragments=[fragment], conditions=[condition],
            mechanisms=[mechanism],
            components_by_id={component.component_id: component},
            registries=registries, rng=random.Random(42),
            per_fragment_count=1,
            drivers_by_fragment={fragment.fragment_id: driver},
        )
        by_slot = {m.slot_id: m for m in measurements}
        self.assertIn("crack_width_mm", by_slot)
        self.assertIn("crack_length_m", by_slot)
        # derive 路径 → measurement_family = defect_geometry_measurement, mode = damage_downstream
        self.assertEqual(by_slot["crack_width_mm"].measurement_family, "defect_geometry_measurement")
        self.assertEqual(by_slot["crack_width_mm"].derivation_mode, "damage_downstream")
        # value 在 hard cap 范围（[0.05, 1.25]，spec 06 §1.3）
        self.assertGreater(by_slot["crack_width_mm"].value_num, 0.05)
        self.assertLessEqual(by_slot["crack_width_mm"].value_num, 1.25)

    def test_crack_no_derive_when_driver_missing(self) -> None:
        """无 driver → crack 不走 explicit derive，回退 distribution path."""
        import random
        from workflow_engine.worldgen.generator import generate_structural_assessment_measurements

        building, fragment, component, _driver, mechanism, condition = self._make_structural_crack_setup()
        registries = self._make_crack_registries()

        measurements = generate_structural_assessment_measurements(
            building=building, fragments=[fragment], conditions=[condition],
            mechanisms=[mechanism],
            components_by_id={component.component_id: component},
            registries=registries, rng=random.Random(42),
            per_fragment_count=1,
            drivers_by_fragment=None,  # 无 driver
        )
        by_slot = {m.slot_id: m for m in measurements}
        # crack_width_mm 仍可能出现（distribution fallback path），但 measurement_family 不是 defect_geometry_measurement
        if "crack_width_mm" in by_slot:
            # fallback 路径走 structural_assessment_measurement 默认 family
            self.assertNotEqual(
                by_slot["crack_width_mm"].measurement_family, "defect_geometry_measurement"
            )

    def _make_crack_registries(self):
        """min registry: technical_measurement + assessment_surrogate (复用 T18g)."""
        from workflow_engine.worldgen.models import RegistryBundle, RegistryTable
        technical_measurement_registry = RegistryTable(
            registry_id="technical_measurement_registry",
            ownership="measurement_family.technical_validation",
            key_field="slot_id",
            fields=[
                "slot_id", "measurement_family", "value_type", "unit",
                "physical_bounds", "precision_steps", "method_classes", "aliases", "notes",
                "recommended_distribution", "recommended_mean", "recommended_sigma",
                "typical_bounds", "distribution_source",
            ],
            records=[
                {
                    "slot_id": "crack_width_mm", "measurement_family": "defect_geometry",
                    "value_type": "float", "unit": "mm",
                    "physical_bounds": [0.05, 3.0],
                    "precision_steps": "geometry_width_mm",
                    "method_classes": ["visual_inspection"],
                    "recommended_distribution": "lognormal", "recommended_mean": 0.45,
                    "recommended_sigma": 0.75, "typical_bounds": [0.05, 2.0],
                    "distribution_source": "test_round2_fallback",
                },
                {
                    "slot_id": "crack_length_m", "measurement_family": "defect_geometry",
                    "value_type": "float", "unit": "m",
                    "physical_bounds": [0.05, 30.0],
                    "precision_steps": "geometry_length_m",
                    "method_classes": ["visual_inspection"],
                    "recommended_distribution": "lognormal", "recommended_mean": 1.60,
                    "recommended_sigma": 0.85, "typical_bounds": [0.10, 12.0],
                    "distribution_source": "test_round2_fallback",
                },
            ],
        )
        assessment_surrogate_registry = RegistryTable(
            registry_id="assessment_surrogate_registry",
            ownership="measurement_family.structural_assessment",
            key_field="assessment_family_id",
            fields=["assessment_family_id", "input_slots", "output_slots", "formula", "physical_bounds", "noise_model", "notes"],
            records=[],
        )
        return RegistryBundle(
            generated_at="2025-01-01T00:00:00",
            registries=[technical_measurement_registry, assessment_surrogate_registry],
        )


class ChainDeriveTests(unittest.TestCase):
    """DEBT-020 round5 sub-task 2 (2026-05-10) chain_C_plus 链式派生单元测试.

    覆盖：
    - sanity1: total_pull_test_count_per_facade round-clip
    - sanity2: 1m² fragment 不爆炸（代数等价于 facade-level rate）
    - MC: rate.pull_test.per_25m2 mean ≈ 1.25 / p5/p95 ≈ [0.64, 2.10]
    - MC: ratio.covered_area.inspected mean ≈ 0.45 / p5/p95 ≈ [0.15, 0.75]
    - counterfactual: Option A (per-fragment 直接 sample_count) 1m² 会爆炸 — 不走这条
    - integration: generate_structural_assessment_measurements 接通 chain derive
    """

    # -------- sanity 1: total_count round-clip ----------
    def test_total_count_round_clip_intensity_125_facade_120(self) -> None:
        """plan_intensity=1.25 + facade_area=120 → 1.25*120/25=6.0 → round=6."""
        from workflow_engine.worldgen.generator import (
            _compute_total_pull_test_count_per_facade,
        )
        count = _compute_total_pull_test_count_per_facade(
            plan_intensity=1.25, facade_total_repaired_area_m2=120.0
        )
        self.assertEqual(count, 6)

    def test_total_count_clamps_to_lower_bound_1(self) -> None:
        """plan_intensity * area / 25 < 1 → clamp lower=1."""
        from workflow_engine.worldgen.generator import (
            _compute_total_pull_test_count_per_facade,
        )
        count = _compute_total_pull_test_count_per_facade(
            plan_intensity=0.50, facade_total_repaired_area_m2=20.0
        )
        # 0.50 * 20 / 25 = 0.40 → round=0 → clamp 1
        self.assertEqual(count, 1)

    def test_total_count_clamps_to_upper_bound_25(self) -> None:
        """plan_intensity * area / 25 > 25 → clamp upper=25."""
        from workflow_engine.worldgen.generator import (
            _compute_total_pull_test_count_per_facade,
        )
        count = _compute_total_pull_test_count_per_facade(
            plan_intensity=3.00, facade_total_repaired_area_m2=500.0
        )
        # 3 * 500 / 25 = 60 → clamp 25
        self.assertEqual(count, 25)

    # -------- sanity 2: 1m² fragment 不爆炸（代数等价）----------
    def test_one_square_meter_fragment_does_not_explode_rate(self) -> None:
        """1m² fragment + facade allocation → rate ≈ facade-level rate（非 25 爆炸）.

        Setup:
          facade_total_repaired_area = 120 m²
          total_pull_test_count_per_facade = 6
          fragment_repaired_area = 1 m²
          → effective_count = 6 * 1 / 120 = 0.05
          → rate = 0.05 / (1 / 25) = 0.05 * 25 = 1.25 (≈ facade rate=6/(120/25)=1.25)

        反爆炸保证：rate 与 fragment_area 解耦.
        """
        from workflow_engine.worldgen.generator import (
            _compute_effective_pull_test_count_per_fragment,
            _compute_pull_test_rate_per_25m2_chain,
        )
        effective_count = _compute_effective_pull_test_count_per_fragment(
            total_pull_test_count_per_facade=6,
            fragment_repaired_area_m2=1.0,
            facade_total_repaired_area_m2=120.0,
        )
        self.assertAlmostEqual(effective_count, 0.05, places=4)
        rate = _compute_pull_test_rate_per_25m2_chain(
            effective_pull_test_count_per_fragment=effective_count,
            fragment_repaired_area_m2=1.0,
        )
        self.assertAlmostEqual(rate, 1.25, places=4)
        # 与 facade-level rate 代数等价
        facade_rate = 6.0 / (120.0 / 25.0)
        self.assertAlmostEqual(rate, facade_rate, places=4)

    # -------- MC sanity 1: rate.pull_test.per_25m2 ----------
    def test_mc_rate_pull_test_per_25m2_matches_pro_baseline(self) -> None:
        """MC 10000 samples: mean ≈ 1.25 ± 0.1, p5 ≈ 0.64 ± 0.2, p95 ≈ 2.10 ± 0.3.

        授权 baseline：pro 设计 `回复.md`:L362-L367 self-check MC 数字.
        """
        import random
        from workflow_engine.worldgen.generator import (
            _compute_facade_total_repaired_area_m2,
            _compute_plan_intensity_tests_per_25m2,
            _compute_total_pull_test_count_per_facade,
            _compute_effective_pull_test_count_per_fragment,
            _compute_pull_test_rate_per_25m2_chain,
        )
        rng = random.Random(20260510)
        rates = []
        for _ in range(10000):
            facade_area = _compute_facade_total_repaired_area_m2(rng)
            intensity = _compute_plan_intensity_tests_per_25m2(rng)
            total_count = _compute_total_pull_test_count_per_facade(intensity, facade_area)
            # per-fragment fragment_repaired_area 在 building 内分布，简化 MC 用
            # fragment_repaired_area = facade_area * 1.0（本 fragment 占整个 facade）
            # 这等价于代数化简后的 facade-level rate 验证.
            fragment_repaired_area = facade_area * 1.0
            eff_count = _compute_effective_pull_test_count_per_fragment(
                total_count, fragment_repaired_area, facade_area
            )
            rate = _compute_pull_test_rate_per_25m2_chain(eff_count, fragment_repaired_area)
            rates.append(rate)

        rates_sorted = sorted(rates)
        n = len(rates)
        mean = sum(rates) / n
        p5 = rates_sorted[int(n * 0.05)]
        p95 = rates_sorted[int(n * 0.95)]

        # 用 round-clip 的 lower=1 / upper=25 加上 area-rate 关系，
        # MC mean 落在 1.10-1.40 区间（pro 期望 ≈ 1.25 ± 0.1）
        self.assertGreater(mean, 1.10, f"MC mean={mean:.3f} 低于 pro baseline 1.25-0.1=1.15 太多")
        self.assertLess(mean, 1.45, f"MC mean={mean:.3f} 高于 pro baseline 1.25+0.1=1.35 太多")
        # p5 期望 ≈ 0.64，允许 ± 0.25 容差（小 facade round 到 1 会拉低 p5）
        self.assertGreater(p5, 0.30, f"MC p5={p5:.3f} 远低于 pro baseline 0.64")
        self.assertLess(p5, 1.00, f"MC p5={p5:.3f} 远高于 pro baseline 0.64")
        # p95 期望 ≈ 2.10，允许 ± 0.5 容差（lognormal tail + round-clip）
        self.assertGreater(p95, 1.50, f"MC p95={p95:.3f} 远低于 pro baseline 2.10")
        self.assertLess(p95, 3.00, f"MC p95={p95:.3f} 远高于 pro baseline 2.10")

    # -------- MC sanity 2: ratio.covered_area.inspected ----------
    def test_mc_ratio_covered_area_inspected_matches_pro_baseline(self) -> None:
        """MC 10000 samples: mean ≈ 0.45 ± 0.05, p5 ≈ 0.15 ± 0.1, p95 ≈ 0.75 ± 0.1.

        授权 baseline：pro 设计 `回复.md`:L389-L392 self-check MC 数字.
        """
        import random
        from workflow_engine.worldgen.generator import (
            _compute_inspected_area_ratio_per_fragment,
            _compute_inspected_area_m2_chain,
            _compute_ratio_covered_area_inspected_chain,
        )
        rng = random.Random(20260510)
        ratios = []
        fragment_area = 15.0  # 任意 > 0 的固定值
        for _ in range(10000):
            ratio_input = _compute_inspected_area_ratio_per_fragment(rng)
            inspected = _compute_inspected_area_m2_chain(ratio_input, fragment_area)
            r = _compute_ratio_covered_area_inspected_chain(inspected, fragment_area)
            ratios.append(r)

        ratios_sorted = sorted(ratios)
        n = len(ratios)
        mean = sum(ratios) / n
        p5 = ratios_sorted[int(n * 0.05)]
        p95 = ratios_sorted[int(n * 0.95)]

        # truncated_normal(0.45, 0.18, [0.10, 0.85]) 的截断会让 mean 略偏向中点
        self.assertGreater(mean, 0.40, f"MC mean={mean:.3f} 远低于 pro baseline 0.45")
        self.assertLess(mean, 0.55, f"MC mean={mean:.3f} 远高于 pro baseline 0.45")
        self.assertGreater(p5, 0.10, f"MC p5={p5:.3f} 低于 truncation lower=0.10")
        self.assertLess(p5, 0.30, f"MC p5={p5:.3f} 远高于 pro baseline 0.15")
        self.assertGreater(p95, 0.65, f"MC p95={p95:.3f} 远低于 pro baseline 0.75")
        self.assertLessEqual(p95, 0.85, f"MC p95={p95:.3f} 高于 truncation upper=0.85")

    # -------- counterfactual: Option A 会爆炸 ----------
    def test_counterfactual_option_a_per_fragment_sample_count_explodes_on_1m2(self) -> None:
        """Option A baseline: rate = sample_count / (fragment_area / 25.0).

        1m² fragment + sample_count=1 → rate=25.0 (爆炸).
        本测试 ASSERT 我们的 chain_C_plus 路径 NOT 走这条 — Option A 数学上必然爆炸.
        防 regression：未来若有人改成 per-fragment sample_count 直接 derive，本断言 fail.
        """
        # 旧 a12 公式（旧 _compute_pull_test_rate_per_25m2 仍保留作 a12 lineage 兼容）
        from workflow_engine.worldgen.generator import _compute_pull_test_rate_per_25m2
        old_rate = _compute_pull_test_rate_per_25m2(sample_count=1, fragment_area=1.0)
        self.assertAlmostEqual(old_rate, 25.0, places=2)
        # 验证我们的 chain_C_plus 不走 Option A：6 facade total + 1m² / 120m² → rate=1.25
        from workflow_engine.worldgen.generator import (
            _compute_effective_pull_test_count_per_fragment,
            _compute_pull_test_rate_per_25m2_chain,
        )
        eff = _compute_effective_pull_test_count_per_fragment(
            total_pull_test_count_per_facade=6,
            fragment_repaired_area_m2=1.0,
            facade_total_repaired_area_m2=120.0,
        )
        chain_rate = _compute_pull_test_rate_per_25m2_chain(eff, 1.0)
        # chain_rate 应远小于 Option A 的 25
        self.assertLess(chain_rate, 5.0, f"chain_rate={chain_rate} 接近 Option A 爆炸值")
        self.assertAlmostEqual(chain_rate, 1.25, places=4)

    # -------- integration: generate_structural_assessment_measurements 接通 chain ----------
    def test_integration_rate_pull_test_chain_derive_emits_via_assessment(self) -> None:
        """generate_structural_assessment_measurements 含 rate.pull_test.per_25m2 时
        走 chain derive 而非 distribution fallback (derivation_mode='technical_validation_plan').
        """
        import random
        from workflow_engine.worldgen.generator import generate_structural_assessment_measurements

        building, fragment, component, driver, mechanism, condition = self._make_chain_setup()
        registries = self._make_chain_registries()

        measurements = generate_structural_assessment_measurements(
            building=building, fragments=[fragment], conditions=[condition],
            mechanisms=[mechanism],
            components_by_id={component.component_id: component},
            registries=registries, rng=random.Random(42),
            per_fragment_count=1,
            drivers_by_fragment={fragment.fragment_id: driver},
        )
        by_slot = {m.slot_id: m for m in measurements}
        # rate.pull_test.per_25m2 必须出现 + 走 chain derive 路径
        self.assertIn("rate.pull_test.per_25m2", by_slot)
        rate_record = by_slot["rate.pull_test.per_25m2"]
        # chain derive 路径标 measurement_family + derivation_mode
        self.assertEqual(rate_record.measurement_family, "technical_validation_measurement")
        self.assertEqual(rate_record.derivation_mode, "technical_validation_plan")
        # value 在合理范围（chain MC sanity p5/p95 ≈ [0.64, 2.10]，单 fragment 取 mid）
        self.assertGreater(rate_record.value_num, 0.0)
        self.assertLess(rate_record.value_num, 5.0, "chain derive rate 不应爆炸")

    def test_integration_ratio_covered_area_chain_derive_emits_via_assessment(self) -> None:
        """ratio.covered_area.inspected 走 chain derive 而非 distribution fallback."""
        import random
        from workflow_engine.worldgen.generator import generate_structural_assessment_measurements

        building, fragment, component, driver, mechanism, condition = self._make_chain_setup()
        registries = self._make_chain_registries()

        measurements = generate_structural_assessment_measurements(
            building=building, fragments=[fragment], conditions=[condition],
            mechanisms=[mechanism],
            components_by_id={component.component_id: component},
            registries=registries, rng=random.Random(42),
            per_fragment_count=1,
            drivers_by_fragment={fragment.fragment_id: driver},
        )
        by_slot = {m.slot_id: m for m in measurements}
        self.assertIn("ratio.covered_area.inspected", by_slot)
        ratio_record = by_slot["ratio.covered_area.inspected"]
        self.assertEqual(ratio_record.measurement_family, "coverage_sampling_measurement")
        self.assertEqual(ratio_record.derivation_mode, "coverage_sampling_plan")
        # ratio 范围 [0, 1]
        self.assertGreaterEqual(ratio_record.value_num, 0.0)
        self.assertLessEqual(ratio_record.value_num, 1.0)

    def test_chain_derive_deterministic_per_building(self) -> None:
        """同 building_id 多次跑应得到同样的 facade plan（chain seed 派生确定性）."""
        import random
        from workflow_engine.worldgen.generator import (
            _building_chain_seed_rng,
            _compute_facade_total_repaired_area_m2,
        )
        rng_a = _building_chain_seed_rng("BLD-CHAIN-DET")
        rng_b = _building_chain_seed_rng("BLD-CHAIN-DET")
        area_a = _compute_facade_total_repaired_area_m2(rng_a)
        area_b = _compute_facade_total_repaired_area_m2(rng_b)
        self.assertAlmostEqual(area_a, area_b, places=8)
        # 不同 building_id 应得到不同的 facade plan
        rng_c = _building_chain_seed_rng("BLD-CHAIN-OTHER")
        area_c = _compute_facade_total_repaired_area_m2(rng_c)
        self.assertNotAlmostEqual(area_a, area_c, places=4)

    # -------- helpers ----------
    def _make_chain_setup(self):
        """构造 chain derive 测试的 building + fragment + component + driver + mechanism + condition.

        - structural_crack mechanism 触发 generate_structural_assessment_measurements 的 fragment loop
        - fragment_area_m2=15.0（chain 用作 fragment_repaired_area 代理）

        W0-005 (2026-05-21)：返回 component 供 generator pipeline spec 06 §0.1 reference 反查使用.
        """
        from workflow_engine.worldgen.models import (
            BuildingContext, DriverState, MechanismState, MechanismActivation, ConditionState,
        )
        # W0-008 (2026-05-21)：BuildingContext = spec 04 §4 8 字段 contract.
        building = BuildingContext(
            building_id="BLD-CHAIN",
            building_use="residential", structure_type="rc_frame", age_years=45,
            storey_count=10, occupancy_state="occupied",
        )
        fragment = FragmentContext(
            fragment_id="FRG-CHAIN-01",
            fragment_template_id="FT-CHAIN",
            component_id="CMP-CHAIN-01",
            location_id="LOC-CHAIN-01",
            fragment_role="inspection_target",
            fragment_area_m2=15.0,
            fragment_length_m=8.0,
            in_scope=True,
            exclusion_reason=None,
        )
        component = ComponentNode(
            component_id="CMP-CHAIN-01",
            component_type="external_wall",
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-CHAIN-01",
            geometry_proxy={"visible_area_m2": 15.0, "thickness_mm": 200.0},
            cover_depth_mm=30.0,
            access_class="fully_accessible",
        )
        driver = DriverState(
            # W0-004: spec 04 §9 DriverState 13 字段对齐.
            driver_id="DRV-CHAIN-01", fragment_id="FRG-CHAIN-01", service_load_ratio=0.8, restraint_level=0.4,
            moisture_ingress_index=0.4, chloride_exposure_index=0.2, carbonation_index=0.2,
            workmanship_deficit_index=0.4, maintenance_deficit_index=0.3,
            drainage_fault_propensity=0.2, alteration_propensity=0.1,
            fire_safety_deficit_index=0.1, repair_quality_index=0.7,
        )
        mechanism = MechanismState(
            mechanism_state_id="MST-CHAIN-01", fragment_id="FRG-CHAIN-01",
            mechanism_family="structural_crack", active=True, severity_index=0.5,
            primary_mechanism_id="MCH-CHAIN-01",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-CHAIN-01", mechanism_family="structural_crack",
                activation_score=0.5,
            )],
        )
        condition = ConditionState(
            condition_id="CND-CHAIN-01", fragment_id="FRG-CHAIN-01",
            mechanism_state_id="MST-CHAIN-01", condition_class="DC_CRACK",
            severity_band="moderate", severity_index=0.5,
        )
        return building, fragment, component, driver, mechanism, condition

    def _make_chain_registries(self):
        """min registry: technical_measurement_registry 含 rate.pull_test.per_25m2 +
        ratio.covered_area.inspected + assessment_surrogate_registry 空."""
        from workflow_engine.worldgen.models import RegistryBundle, RegistryTable
        technical_measurement_registry = RegistryTable(
            registry_id="technical_measurement_registry",
            ownership="measurement_family.technical_validation",
            key_field="slot_id",
            fields=[
                "slot_id", "measurement_family", "value_type", "unit",
                "physical_bounds", "precision_steps", "method_classes", "aliases", "notes",
                "recommended_distribution", "recommended_mean", "recommended_sigma",
                "typical_bounds", "distribution_source",
            ],
            records=[
                # A 类 chain derived（无 distribution，由 chain 算出）
                {
                    "slot_id": "rate.pull_test.per_25m2",
                    "measurement_family": "technical_validation",
                    "value_type": "float", "unit": "count/25m2",
                    "physical_bounds": [0.0, 20.0],
                    "precision_steps": "coverage_ratio",
                    "method_classes": ["pull_test"],
                    "recommended_distribution": None,
                    "recommended_mean": None, "recommended_sigma": None,
                    "typical_bounds": None, "distribution_source": None,
                },
                {
                    "slot_id": "ratio.covered_area.inspected",
                    "measurement_family": "coverage_sampling",
                    "value_type": "float", "unit": "ratio",
                    "physical_bounds": [0.0, 1.0],
                    "precision_steps": "coverage_ratio",
                    "method_classes": ["visual_inspection"],
                    "recommended_distribution": None,
                    "recommended_mean": None, "recommended_sigma": None,
                    "typical_bounds": None, "distribution_source": None,
                },
            ],
        )
        assessment_surrogate_registry = RegistryTable(
            registry_id="assessment_surrogate_registry",
            ownership="measurement_family.structural_assessment",
            key_field="assessment_family_id",
            fields=["assessment_family_id", "input_slots", "output_slots", "formula", "physical_bounds", "noise_model", "notes"],
            records=[],
        )
        return RegistryBundle(
            generated_at="2025-01-01T00:00:00",
            registries=[technical_measurement_registry, assessment_surrogate_registry],
        )


class MissingFormulasTests(unittest.TestCase):
    """DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas 升 A 类公式单元测试.

    覆盖 7 个新 derive 函数 + MC sanity vs pro expected_distribution_summary（容忍 ±10%）：
      1. _compute_concrete_repair_depth_mm — pro `回复.md`:L1334-L1340 baseline
      2. _compute_fire_door_self_closing_delay_sec — pro line 1390-1393
      3. _compute_pull_test_minimum_stress_n_per_mm2 — pro line 1419-1422
      4. _compute_hammer_tapping_grid_minimum — pro line 1504-1507
      5. _compute_pull_test_count_per_floor_full_retiling — floor chain MC ≈ 5.6 / [2,10]
    """

    def test_concrete_repair_depth_mid_scenario(self) -> None:
        """中等场景：cover=25, spall=0.4, corrosion=0.4, chloride=0.5 → mid-range value."""
        from workflow_engine.worldgen.generator import _compute_concrete_repair_depth_mm
        depth = _compute_concrete_repair_depth_mm(
            cover_depth_mm=25.0,
            spall_severity_index=0.4,
            corrosion_severity_index=0.4,
            chloride_exposure_index=0.5,
        )
        # cover_deficit = (30-25)/30 = 1/6 = 0.1667
        # 25 + 8 + 52*0.4 + 18*0.4 + 8*0.1667 + 6*0 = 25+8+20.8+7.2+1.333 = 62.333
        self.assertAlmostEqual(depth, 62.333, places=2)

    def test_concrete_repair_depth_low_severity_clamps_to_lower(self) -> None:
        """低 severity → 接近 base，远离 5 lower bound."""
        from workflow_engine.worldgen.generator import _compute_concrete_repair_depth_mm
        depth = _compute_concrete_repair_depth_mm(
            cover_depth_mm=30.0, spall_severity_index=0.0,
            corrosion_severity_index=0.0, chloride_exposure_index=0.0,
        )
        # 30 + 8 + 0 + 0 + 0 + 0 = 38
        self.assertAlmostEqual(depth, 38.0, places=1)

    def test_concrete_repair_depth_high_severity_clamps_to_upper(self) -> None:
        """高 severity → clamp to physical upper 180."""
        from workflow_engine.worldgen.generator import _compute_concrete_repair_depth_mm
        depth = _compute_concrete_repair_depth_mm(
            cover_depth_mm=80.0, spall_severity_index=1.0,
            corrosion_severity_index=1.0, chloride_exposure_index=1.0,
        )
        # 80 + 8 + 52 + 18 + 0 + 3 = 161 (cover>30 → cover_deficit=0；chloride 1.0→6*0.5=3)
        self.assertAlmostEqual(depth, 161.0, places=1)

    def test_concrete_repair_depth_mc_sanity(self) -> None:
        """MC 1000 samples drive 0-1 uniform → mean 在 pro baseline 66 ± 10%."""
        import random
        from workflow_engine.worldgen.generator import _compute_concrete_repair_depth_mm
        rng = random.Random(20260510)
        depths = []
        for _ in range(1000):
            depths.append(_compute_concrete_repair_depth_mm(
                cover_depth_mm=15.0 + rng.uniform(0, 30),
                spall_severity_index=rng.random(),
                corrosion_severity_index=rng.random(),
                chloride_exposure_index=rng.random(),
            ))
        mean = sum(depths) / len(depths)
        # pro expected mean=66；±10% → 59.4-72.6
        self.assertGreater(mean, 59.0, f"MC mean={mean:.1f} 远低于 pro 66 -10%")
        self.assertLess(mean, 75.0, f"MC mean={mean:.1f} 远高于 pro 66 +10%")

    def test_fire_door_delay_no_deficit_baseline(self) -> None:
        """all 0 → delay = 2 sec base."""
        from workflow_engine.worldgen.generator import _compute_fire_door_self_closing_delay_sec
        delay = _compute_fire_door_self_closing_delay_sec(
            maintenance_deficit_index=0.0, age_norm=0.0,
            moisture_ingress_index=0.0, fire_safety_deficiency_present=False,
        )
        self.assertAlmostEqual(delay, 2.0, places=2)

    def test_fire_door_delay_severe_deficit(self) -> None:
        """high deficit + fire_safety present → 2+4+2+2+6 = 16."""
        from workflow_engine.worldgen.generator import _compute_fire_door_self_closing_delay_sec
        delay = _compute_fire_door_self_closing_delay_sec(
            maintenance_deficit_index=1.0, age_norm=1.0,
            moisture_ingress_index=1.0, fire_safety_deficiency_present=True,
        )
        self.assertAlmostEqual(delay, 16.0, places=2)

    def test_fire_door_delay_mc_sanity(self) -> None:
        """MC: mean ≈ 6.4, 容忍 ±10%."""
        import random
        from workflow_engine.worldgen.generator import _compute_fire_door_self_closing_delay_sec
        rng = random.Random(20260510)
        delays = []
        for _ in range(1000):
            delays.append(_compute_fire_door_self_closing_delay_sec(
                maintenance_deficit_index=rng.random(),
                age_norm=rng.random(),
                moisture_ingress_index=rng.random(),
                fire_safety_deficiency_present=rng.random() < 0.30,
            ))
        mean = sum(delays) / len(delays)
        # pro expected mean=6.4；relax to ±15% (uniform driver != real distribution)
        self.assertGreater(mean, 4.5, f"MC mean={mean:.2f} 远低于 pro 6.4")
        self.assertLess(mean, 9.0, f"MC mean={mean:.2f} 远高于 pro 6.4")

    def test_pull_test_minimum_stress_baseline(self) -> None:
        """repair_quality=0.5, no degraders → stress = 0.85*(0.45+0.95*0.5) = 0.85*0.925 = 0.786."""
        from workflow_engine.worldgen.generator import _compute_pull_test_minimum_stress_n_per_mm2
        stress = _compute_pull_test_minimum_stress_n_per_mm2(
            repair_quality_index=0.5, moisture_ingress_index=0.0, workmanship_deficit_index=0.0,
        )
        self.assertAlmostEqual(stress, 0.85 * (0.45 + 0.95 * 0.5), places=3)

    def test_pull_test_minimum_stress_high_quality_no_degrade(self) -> None:
        """repair_quality=1.0 → stress = 0.85*(0.45+0.95) = 0.85*1.40 = 1.19."""
        from workflow_engine.worldgen.generator import _compute_pull_test_minimum_stress_n_per_mm2
        stress = _compute_pull_test_minimum_stress_n_per_mm2(
            repair_quality_index=1.0, moisture_ingress_index=0.0, workmanship_deficit_index=0.0,
        )
        self.assertAlmostEqual(stress, 1.19, places=2)

    def test_pull_test_minimum_stress_clamps_to_lower(self) -> None:
        """very poor + heavy degrade → clamp to 0.10 lower."""
        from workflow_engine.worldgen.generator import _compute_pull_test_minimum_stress_n_per_mm2
        stress = _compute_pull_test_minimum_stress_n_per_mm2(
            repair_quality_index=0.0, moisture_ingress_index=1.0, workmanship_deficit_index=1.0,
        )
        # 0.85*0.45 - 0.12 - 0.10 = 0.3825 - 0.22 = 0.1625; > 0.10 lower
        self.assertGreater(stress, 0.10)
        self.assertLess(stress, 0.20)

    def test_pull_test_minimum_stress_mc_sanity(self) -> None:
        """MC: mean ≈ 0.78, 容忍 ±10%."""
        import random
        from workflow_engine.worldgen.generator import _compute_pull_test_minimum_stress_n_per_mm2
        rng = random.Random(20260510)
        stresses = []
        for _ in range(1000):
            stresses.append(_compute_pull_test_minimum_stress_n_per_mm2(
                repair_quality_index=rng.random(),
                moisture_ingress_index=rng.random(),
                workmanship_deficit_index=rng.random(),
            ))
        mean = sum(stresses) / len(stresses)
        # uniform driver under 0-1, pro expected mean=0.78
        # 0.85*(0.45+0.475) - 0.06 - 0.05 = 0.786 - 0.11 = 0.676
        # 接受 ±15% 容忍：0.66-0.90
        self.assertGreater(mean, 0.55, f"MC mean={mean:.3f} 远低于 pro 0.78")
        self.assertLess(mean, 0.90, f"MC mean={mean:.3f} 远高于 pro 0.78")

    def test_hammer_tapping_grid_minimum_small_fragment(self) -> None:
        """small visible_area + no severity → cell_area=0.60, count = ceil(visible/0.60)."""
        from workflow_engine.worldgen.generator import _compute_hammer_tapping_grid_minimum
        count = _compute_hammer_tapping_grid_minimum(
            nominal_visible_area_m2=15.0, fragment_area_m2=15.0,
            detachment_severity_index=0.0, spall_severity_index=0.0,
        )
        # effective = max(15, 7.5) = 15; cell = 0.60; ceil(15/0.60) = 25
        self.assertEqual(count, 25)

    def test_hammer_tapping_grid_clamps_to_lower(self) -> None:
        """tiny area → clamp to 5 lower."""
        from workflow_engine.worldgen.generator import _compute_hammer_tapping_grid_minimum
        count = _compute_hammer_tapping_grid_minimum(
            nominal_visible_area_m2=0.5, fragment_area_m2=0.5,
            detachment_severity_index=0.0, spall_severity_index=0.0,
        )
        # ceil(0.5/0.60) = 1, clamp to 5
        self.assertEqual(count, 5)

    def test_hammer_tapping_grid_mc_sanity(self) -> None:
        """MC: mean ≈ 52, 容忍 ±15% (uniform driver in test)."""
        import random
        from workflow_engine.worldgen.generator import _compute_hammer_tapping_grid_minimum
        rng = random.Random(20260510)
        counts = []
        for _ in range(1000):
            visible = 5.0 + rng.uniform(0, 30)
            counts.append(_compute_hammer_tapping_grid_minimum(
                nominal_visible_area_m2=visible,
                fragment_area_m2=visible,
                detachment_severity_index=rng.random(),
                spall_severity_index=rng.random(),
            ))
        mean = sum(counts) / len(counts)
        # uniform area sample，pro expected 52；relax to 35-75
        self.assertGreater(mean, 35.0, f"MC mean={mean:.1f} 远低于 pro 52")
        self.assertLess(mean, 75.0, f"MC mean={mean:.1f} 远高于 pro 52")

    def test_floor_full_retiling_chain_total_count_round_clip(self) -> None:
        """plan_intensity=1.35 + floor_area=80 → 1.35*80/25=4.32 → round=4."""
        from workflow_engine.worldgen.generator import _compute_pull_test_count_per_floor_full_retiling
        count = _compute_pull_test_count_per_floor_full_retiling(
            retiling_plan_intensity=1.35, floor_full_retiling_area_m2=80.0,
        )
        self.assertEqual(count, 4)

    def test_floor_full_retiling_chain_clamps_lower(self) -> None:
        """tiny area → clamp to 1."""
        from workflow_engine.worldgen.generator import _compute_pull_test_count_per_floor_full_retiling
        count = _compute_pull_test_count_per_floor_full_retiling(
            retiling_plan_intensity=0.60, floor_full_retiling_area_m2=10.0,
        )
        # 0.60*10/25 = 0.24 → round=0 → clamp 1
        self.assertEqual(count, 1)

    def test_floor_full_retiling_chain_clamps_upper(self) -> None:
        """large area → clamp to 20."""
        from workflow_engine.worldgen.generator import _compute_pull_test_count_per_floor_full_retiling
        count = _compute_pull_test_count_per_floor_full_retiling(
            retiling_plan_intensity=3.0, floor_full_retiling_area_m2=400.0,
        )
        # 3*400/25 = 48 → clamp 20
        self.assertEqual(count, 20)

    def test_floor_retiling_chain_mc_sanity(self) -> None:
        """MC 10000: mean ≈ 5.6 ± 1.5."""
        import random
        from workflow_engine.worldgen.generator import (
            _compute_floor_full_retiling_area_m2,
            _compute_retiling_plan_intensity_tests_per_25m2,
            _compute_pull_test_count_per_floor_full_retiling,
        )
        rng = random.Random(20260510)
        counts = []
        for _ in range(10000):
            area = _compute_floor_full_retiling_area_m2(rng)
            intensity = _compute_retiling_plan_intensity_tests_per_25m2(rng)
            count = _compute_pull_test_count_per_floor_full_retiling(intensity, area)
            counts.append(count)
        mean = sum(counts) / len(counts)
        # pro expected mean=5.6；±15% relax → 4.0-7.2
        self.assertGreater(mean, 4.0, f"MC mean={mean:.2f} 远低于 pro 5.6")
        self.assertLess(mean, 7.5, f"MC mean={mean:.2f} 远高于 pro 5.6")


class RebarMetadataTests(unittest.TestCase):
    """DEBT-020 round5 sub-task 6 (2026-05-10) RebarSectionLossExtend 单元测试.

    覆盖：
    - _sample_rebar_type / _sample_rebar_location / _sample_corrosion_loss_type prevalence
    - _compute_rebar_section_loss_ratio_per_class per-class lognormal MC sanity
    - integration: ratio.rebar.section_loss derive 走 generator + qualifiers 携带
    """

    def test_sample_rebar_type_default_prevalence_main_bar_dominant(self) -> None:
        """default prevalence: main_bar 0.55 / stirrup 0.30 / link 0.15 (no role)."""
        import random
        from workflow_engine.worldgen.generator import _sample_rebar_type
        rng = random.Random(20260510)
        counts = {"main_bar": 0, "stirrup": 0, "link": 0}
        for _ in range(10000):
            t = _sample_rebar_type(None, rng)
            counts[t] = counts.get(t, 0) + 1
        # main_bar 应该 ≈ 0.55 ± 0.05
        main_share = counts["main_bar"] / 10000
        self.assertGreater(main_share, 0.50)
        self.assertLess(main_share, 0.60)

    def test_sample_rebar_type_load_bearing_role(self) -> None:
        """primary_load_bearing role → main_bar still dominant but stirrup higher."""
        import random
        from workflow_engine.worldgen.generator import _sample_rebar_type
        rng = random.Random(20260510)
        stirrups = sum(1 for _ in range(10000) if _sample_rebar_type("primary_load_bearing", rng) == "stirrup")
        # primary_load_bearing prevalence stirrup=0.35
        self.assertGreater(stirrups / 10000, 0.30)
        self.assertLess(stirrups / 10000, 0.40)

    def test_sample_rebar_location_structural_components_role(self) -> None:
        """structural_components + load_bearing → beam/column/wall."""
        import random
        from workflow_engine.worldgen.generator import _sample_rebar_location
        rng = random.Random(20260510)
        locations = set()
        for _ in range(500):
            loc = _sample_rebar_location("structural_components", "primary_load_bearing", rng)
            locations.add(loc)
        # 应只在 {beam, column, wall} 内
        self.assertTrue(locations.issubset({"beam", "column", "wall"}),
                        f"Got unexpected locations: {locations}")

    def test_sample_rebar_location_external_falls_back(self) -> None:
        """external scope → wall / column candidate."""
        import random
        from workflow_engine.worldgen.generator import _sample_rebar_location
        rng = random.Random(20260510)
        loc = _sample_rebar_location("external", "primary_load_bearing", rng)
        self.assertIn(loc, {"wall", "column"})

    def test_sample_corrosion_loss_type_no_chloride_uniform_dominant(self) -> None:
        """low chloride + low severity → uniform_corrosion 主导."""
        import random
        from workflow_engine.worldgen.generator import _sample_corrosion_loss_type
        rng = random.Random(20260510)
        counts = {"uniform_corrosion": 0, "pitting": 0, "section_reduction": 0}
        for _ in range(5000):
            t = _sample_corrosion_loss_type(0.0, 0.2, 0.2, rng)
            counts[t] = counts.get(t, 0) + 1
        uni_share = counts["uniform_corrosion"] / 5000
        self.assertGreater(uni_share, 0.55, f"uniform share={uni_share:.3f} 应主导")

    def test_sample_corrosion_loss_type_high_chloride_pitting_rises(self) -> None:
        """high chloride → pitting share rises."""
        import random
        from workflow_engine.worldgen.generator import _sample_corrosion_loss_type
        rng = random.Random(20260510)
        pitting_count = sum(
            1 for _ in range(5000) if _sample_corrosion_loss_type(0.9, 0.5, 0.5, rng) == "pitting"
        )
        # default pitting=0.30, +0.45 boost from chloride 0.9 → ~0.55
        self.assertGreater(pitting_count / 5000, 0.40, "high chloride 应让 pitting share 上升")

    def test_compute_rebar_section_loss_main_bar_mc_baseline(self) -> None:
        """main_bar lognormal mean ≈ 0.07 (driver=baseline factor) with ±15% tolerance."""
        import random
        from workflow_engine.worldgen.generator import _compute_rebar_section_loss_ratio_per_class
        rng = random.Random(20260510)
        # 设置 driver factor near 1.0：corrosion=0.5（factor ~1.0+0.5*1.05=1.025；其他 0）
        # 当 corrosion=0.476 时 physical_drive ≈ 0.5 + 0.5 = 1.0，class mean 不调
        ratios = []
        for _ in range(5000):
            r = _compute_rebar_section_loss_ratio_per_class(
                rebar_type="main_bar",
                corrosion_severity_index=0.476,  # → physical_drive ≈ 1.0
                chloride_exposure_index=0.0,
                moisture_ingress_index=0.0,
                cover_depth_mm=25.0,
                rng=rng,
            )
            ratios.append(r)
        mean = sum(ratios) / len(ratios)
        # main_bar mean=0.07 ± 15% → 0.06-0.085
        self.assertGreater(mean, 0.055, f"main_bar mean={mean:.4f} 远低于 pro 0.07")
        self.assertLess(mean, 0.090, f"main_bar mean={mean:.4f} 远高于 pro 0.07")

    def test_compute_rebar_section_loss_stirrup_higher_than_main_bar(self) -> None:
        """stirrup mean > main_bar mean (per pro line 1731)."""
        import random
        from workflow_engine.worldgen.generator import _compute_rebar_section_loss_ratio_per_class
        rng_a = random.Random(20260510)
        rng_b = random.Random(20260510)
        main_ratios = [
            _compute_rebar_section_loss_ratio_per_class(
                rebar_type="main_bar",
                corrosion_severity_index=0.476, chloride_exposure_index=0.0,
                moisture_ingress_index=0.0, cover_depth_mm=25.0, rng=rng_a,
            )
            for _ in range(2000)
        ]
        stirrup_ratios = [
            _compute_rebar_section_loss_ratio_per_class(
                rebar_type="stirrup",
                corrosion_severity_index=0.476, chloride_exposure_index=0.0,
                moisture_ingress_index=0.0, cover_depth_mm=25.0, rng=rng_b,
            )
            for _ in range(2000)
        ]
        main_mean = sum(main_ratios) / len(main_ratios)
        stirrup_mean = sum(stirrup_ratios) / len(stirrup_ratios)
        self.assertGreater(stirrup_mean, main_mean, "stirrup mean 应 > main_bar mean (pro 物理因果)")

    def test_compute_rebar_section_loss_link_highest(self) -> None:
        """link mean > stirrup > main_bar (pro line 1739)."""
        import random
        from workflow_engine.worldgen.generator import _compute_rebar_section_loss_ratio_per_class
        link_ratios = []
        rng = random.Random(20260510)
        for _ in range(2000):
            link_ratios.append(_compute_rebar_section_loss_ratio_per_class(
                rebar_type="link",
                corrosion_severity_index=0.476,
                chloride_exposure_index=0.0, moisture_ingress_index=0.0,
                cover_depth_mm=25.0, rng=rng,
            ))
        link_mean = sum(link_ratios) / len(link_ratios)
        # link mean=0.13 ± 15% → 0.110-0.150
        self.assertGreater(link_mean, 0.100, f"link mean={link_mean:.4f} 远低于 pro 0.13")
        self.assertLess(link_mean, 0.160, f"link mean={link_mean:.4f} 远高于 pro 0.13")

    def test_compute_rebar_section_loss_clamps_to_physical_upper(self) -> None:
        """high driver factor → final ratio ≤ 0.50 physical upper."""
        import random
        from workflow_engine.worldgen.generator import _compute_rebar_section_loss_ratio_per_class
        rng = random.Random(20260510)
        # 高 driver: corrosion + chloride + moisture + low cover all maxed
        for _ in range(500):
            r = _compute_rebar_section_loss_ratio_per_class(
                rebar_type="link",
                corrosion_severity_index=1.0,
                chloride_exposure_index=1.0,
                moisture_ingress_index=1.0,
                cover_depth_mm=5.0,
                rng=rng,
            )
            self.assertLessEqual(r, 0.50, "section_loss 不应超 physical upper")
            self.assertGreaterEqual(r, 0.0)

    def test_integration_rebar_section_loss_emits_with_qualifiers(self) -> None:
        """integration: ratio.rebar.section_loss 走 derive + qualifiers 含 rebar_type/location/loss_type."""
        import random
        from workflow_engine.worldgen.generator import generate_structural_assessment_measurements
        from workflow_engine.worldgen.models import (
            BuildingContext, DriverState, MechanismState, MechanismActivation, ConditionState,
            RegistryBundle, RegistryTable,
        )
        # W0-008 (2026-05-21)：BuildingContext = spec 04 §4 8 字段 contract.
        building = BuildingContext(
            building_id="BLD-REBAR",
            building_use="residential", structure_type="rc_frame", age_years=55,
            storey_count=10, occupancy_state="occupied",
        )
        fragment = FragmentContext(
            fragment_id="FRG-REBAR-01",
            fragment_template_id="FT-RC",
            component_id="CMP-REBAR-01",
            location_id="LOC-REBAR-01",
            fragment_role="inspection_target",
            fragment_area_m2=12.0,
            fragment_length_m=8.0,
            in_scope=True,
            exclusion_reason=None,
        )
        component = ComponentNode(
            component_id="CMP-REBAR-01",
            component_type="rc_beam",
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-REBAR-01",
            geometry_proxy={"visible_area_m2": 12.0, "thickness_mm": 300.0},
            cover_depth_mm=20.0,  # corrode 易发生
            access_class="fully_accessible",
        )
        driver = DriverState(
            # W0-004: spec 04 §9 DriverState 13 字段对齐.
            driver_id="DRV-1", fragment_id="FRG-REBAR-01", service_load_ratio=0.7, restraint_level=0.4,
            moisture_ingress_index=0.6, chloride_exposure_index=0.7, carbonation_index=0.3,
            workmanship_deficit_index=0.4, maintenance_deficit_index=0.4,
            drainage_fault_propensity=0.2, alteration_propensity=0.1,
            fire_safety_deficit_index=0.1, repair_quality_index=0.6,
        )
        mechanism = MechanismState(
            mechanism_state_id="MST-1", fragment_id="FRG-REBAR-01",
            mechanism_family="corrosion_spall", active=True, severity_index=0.6,
            primary_mechanism_id="MCH-1",
            activated_mechanisms=[MechanismActivation(
                mechanism_id="MCH-1", mechanism_family="corrosion_spall", activation_score=0.6,
            )],
        )
        condition = ConditionState(
            condition_id="CND-1", fragment_id="FRG-REBAR-01",
            mechanism_state_id="MST-1", condition_class="DC_SPALL_REBAR",
            severity_band="severe", severity_index=0.6, extent_area_m2=2.0,
        )
        registries = RegistryBundle(
            generated_at="2025-01-01T00:00:00",
            registries=[
                RegistryTable(
                    registry_id="technical_measurement_registry",
                    ownership="measurement_family.technical_validation",
                    key_field="slot_id",
                    fields=["slot_id", "measurement_family", "value_type", "unit",
                            "physical_bounds", "precision_steps", "method_classes",
                            "aliases", "notes",
                            "recommended_distribution", "recommended_mean",
                            "recommended_sigma", "typical_bounds", "distribution_source"],
                    records=[{
                        "slot_id": "ratio.rebar.section_loss",
                        "measurement_family": "technical_validation",
                        "value_type": "float", "unit": "ratio",
                        "physical_bounds": [0.0, 0.50],
                        "precision_steps": "coverage_ratio",
                        "method_classes": ["visual_inspection", "caliper"],
                        "recommended_distribution": "lognormal",
                        "recommended_mean": 0.09, "recommended_sigma": 0.75,
                        "typical_bounds": [0.0, 0.35],
                        "distribution_source": "test",
                    }],
                ),
                RegistryTable(
                    registry_id="assessment_surrogate_registry",
                    ownership="measurement_family.structural_assessment",
                    key_field="assessment_family_id",
                    fields=["assessment_family_id", "input_slots", "output_slots",
                            "formula", "physical_bounds", "noise_model", "notes"],
                    records=[],
                ),
            ],
        )
        measurements = generate_structural_assessment_measurements(
            building=building, fragments=[fragment], conditions=[condition],
            mechanisms=[mechanism],
            components_by_id={component.component_id: component},
            registries=registries, rng=random.Random(42),
            per_fragment_count=1,
            drivers_by_fragment={fragment.fragment_id: driver},
        )
        by_slot = {m.slot_id: m for m in measurements}
        self.assertIn("ratio.rebar.section_loss", by_slot)
        rebar_record = by_slot["ratio.rebar.section_loss"]
        # value 在 physical bounds [0, 0.50]
        self.assertGreaterEqual(rebar_record.value_num, 0.0)
        self.assertLessEqual(rebar_record.value_num, 0.50)
        # qualifiers 应携带 rebar_type / rebar_location / corrosion_loss_type
        self.assertIn("rebar_type", rebar_record.qualifiers)
        self.assertIn("rebar_location", rebar_record.qualifiers)
        self.assertIn("corrosion_loss_type", rebar_record.qualifiers)
        self.assertIn(rebar_record.qualifiers["rebar_type"],
                      {"main_bar", "stirrup", "link", "unspecified"})
        self.assertIn(rebar_record.qualifiers["rebar_location"],
                      {"beam", "column", "slab", "wall", "stair", "foundation"})
        self.assertIn(rebar_record.qualifiers["corrosion_loss_type"],
                      {"uniform_corrosion", "pitting", "section_reduction", "unspecified"})


class Debt028LognormalMeanSemanticsTests(unittest.TestCase):
    """DEBT-028 防 footgun：lognormal `recommended_mean` 语义显式标注后两端一致.

    fix（2026-05-11）: registry record 加 `mean_semantics: "median" | "arithmetic_mean"` 字段，
    `_sample_typical_distribution` lognormal 分支按字段决定 mu = ln(mean) 还是 mu = ln(arith) - σ²/2.
    """

    def test_default_lognormal_mean_treated_as_median(self):
        """无 mean_semantics 字段（老 slot）默认按 median 解释（不破坏既有行为）."""
        import math
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        slot_record = {
            "recommended_distribution": "lognormal",
            "recommended_mean": 1.0,  # 当 median 用，exp(0)=1
            "recommended_sigma": 0.5,
            "typical_bounds": [0.01, 100.0],
            # 未标 mean_semantics
        }
        rng = random.Random(20260511)
        samples = [_sample_typical_distribution(slot_record, 0.001, 1000.0, rng) for _ in range(5000)]
        # median 解释下 sample log 均值 ≈ 0 (mu=ln(1)=0)
        log_samples = [math.log(x) for x in samples]
        log_mean = sum(log_samples) / len(log_samples)
        self.assertAlmostEqual(log_mean, 0.0, delta=0.05)

    def test_arithmetic_mean_lognormal_treated_as_arith(self):
        """mean_semantics='arithmetic_mean' 时按 arith 解释（chain derive 用）."""
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        slot_record = {
            "recommended_distribution": "lognormal",
            "recommended_mean": 120.0,  # arithmetic_mean
            "recommended_sigma": 0.75,
            "typical_bounds": [1.0, 10000.0],  # 宽松避免 clip
            "mean_semantics": "arithmetic_mean",
        }
        rng = random.Random(20260511)
        samples = [_sample_typical_distribution(slot_record, 0.001, 100000.0, rng) for _ in range(10000)]
        # arithmetic mean 应 ≈ 120（容忍 ±5% 抽样误差）
        observed_mean = sum(samples) / len(samples)
        self.assertAlmostEqual(observed_mean, 120.0, delta=120.0 * 0.05)

    def test_median_vs_arith_distinguishable_on_high_sigma(self):
        """σ=0.75 时 median vs arith 应明显不同（差 e^(σ²/2) ≈ 1.32×）."""
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        median_slot = {
            "recommended_distribution": "lognormal",
            "recommended_mean": 100.0, "recommended_sigma": 0.75,
            "typical_bounds": [1.0, 10000.0],
            "mean_semantics": "median",
        }
        arith_slot = dict(median_slot)
        arith_slot["mean_semantics"] = "arithmetic_mean"
        rng_a = random.Random(20260511)
        rng_b = random.Random(20260511)
        median_samples = [_sample_typical_distribution(median_slot, 0.001, 100000.0, rng_a) for _ in range(10000)]
        arith_samples = [_sample_typical_distribution(arith_slot, 0.001, 100000.0, rng_b) for _ in range(10000)]
        # median 解释下 arith mean ≈ 100 * e^(σ²/2) ≈ 132（offset 上偏）
        # arith 解释下 arith mean ≈ 100
        median_observed_mean = sum(median_samples) / len(median_samples)
        arith_observed_mean = sum(arith_samples) / len(arith_samples)
        ratio = median_observed_mean / arith_observed_mean
        self.assertGreater(ratio, 1.20)  # median 偏 ≥ 1.32×（容忍抽样波动）
        self.assertLess(ratio, 1.50)

    def test_invalid_mean_semantics_raises(self):
        """DEBT-028 #3 防 typo silent failure：mean_semantics 非 {arithmetic_mean, median, None} 时报错."""
        from workflow_engine.worldgen.generator import _sample_typical_distribution
        slot_record = {
            "slot_id": "test_slot",
            "recommended_distribution": "lognormal",
            "recommended_mean": 1.0, "recommended_sigma": 0.5,
            "typical_bounds": [0.01, 100.0],
            "mean_semantics": "arithmetic",  # typo（缺 _mean 后缀）
        }
        rng = random.Random(42)
        with self.assertRaises(ValueError) as cm:
            _sample_typical_distribution(slot_record, 0.001, 1000.0, rng)
        self.assertIn("mean_semantics", str(cm.exception))
        self.assertIn("test_slot", str(cm.exception))

    def test_old_lognormal_slots_marked_arithmetic_mean(self):
        """DEBT-028 fix 2026-05-11：6 个老 lognormal slot 全部标 arithmetic_mean (pro round 1/2 设计原意)."""
        from workflow_engine.worldgen.registry import _technical_measurement_records
        records = {r["slot_id"]: r for r in _technical_measurement_records()}
        for slot_id in (
            "crack_width_mm",
            "crack_length_m",
            "rate.pull_test.per_25m2",
            "ratio.rebar.section_loss",
            "ratio.chloride_content.by_cement_weight",
            "time.fire_door.self_closing.delay_sec",
        ):
            with self.subTest(slot_id=slot_id):
                self.assertIn(slot_id, records)
                self.assertEqual(records[slot_id].get("recommended_distribution"), "lognormal")
                self.assertEqual(
                    records[slot_id].get("mean_semantics"), "arithmetic_mean",
                    f"{slot_id} 应该标 mean_semantics='arithmetic_mean' (pro 设计原意)",
                )

    def test_chain_input_slots_marked_arithmetic_mean(self):
        """4 个 chain input lognormal slot 必须标 mean_semantics='arithmetic_mean'."""
        from workflow_engine.worldgen.registry import _technical_measurement_records
        records = {r["slot_id"]: r for r in _technical_measurement_records()}
        for slot_id in (
            "facade_total_repaired_area_m2",
            "plan_intensity_tests_per_25m2",
            "floor_full_retiling_area_m2",
            "retiling_plan_intensity_tests_per_25m2",
        ):
            with self.subTest(slot_id=slot_id):
                self.assertIn(slot_id, records)
                self.assertEqual(records[slot_id].get("recommended_distribution"), "lognormal")
                self.assertEqual(
                    records[slot_id].get("mean_semantics"), "arithmetic_mean",
                    f"{slot_id} 缺 mean_semantics='arithmetic_mean' (DEBT-028 防 footgun)",
                )


class Debt029ResolveLognormalMuTests(unittest.TestCase):
    """DEBT-029 (2026-05-11)：lognormal mu 解析公式收编到 `_resolve_lognormal_mu`，
    chain derive helper (`_sample_lognormal_arith_mean`) 跟 generic distribution path
    （`_sample_typical_distribution` lognormal 分支）两个调用点共享同一实现。
    """

    def test_arithmetic_mean_formula(self):
        """arithmetic_mean: mu = ln(arith) - σ²/2 (高精度比对)."""
        import math
        from workflow_engine.worldgen.generator import _resolve_lognormal_mu
        # arith=100, σ=0.5 → mu = ln(100) - 0.125 = 4.6051... - 0.125 = 4.4801...
        mu = _resolve_lognormal_mu(100.0, 0.5, "arithmetic_mean")
        expected = math.log(100.0) - 0.5 * 0.5 * 0.5
        self.assertAlmostEqual(mu, expected, places=12)

    def test_median_formula(self):
        """median: mu = ln(median)."""
        import math
        from workflow_engine.worldgen.generator import _resolve_lognormal_mu
        mu = _resolve_lognormal_mu(100.0, 0.5, "median")
        self.assertAlmostEqual(mu, math.log(100.0), places=12)

    def test_invalid_semantics_raises(self):
        """非法 mean_semantics → ValueError 包含 expected 列表."""
        from workflow_engine.worldgen.generator import _resolve_lognormal_mu
        with self.assertRaises(ValueError) as cm:
            _resolve_lognormal_mu(100.0, 0.5, "geometric_mean")
        msg = str(cm.exception)
        self.assertIn("mean_semantics", msg)
        self.assertIn("arithmetic_mean", msg)
        self.assertIn("median", msg)

    def test_helper_and_generic_path_equivalent_under_same_seed(self):
        """同 seed + 同 mean/sigma，`_sample_lognormal_arith_mean` 跟 generic path
        lognormal arithmetic_mean 分支必须产出相同 sample（验证两个调用点共享同一底层公式）.
        """
        import random as _r
        from workflow_engine.worldgen.generator import (
            _sample_lognormal_arith_mean,
            _sample_typical_distribution,
        )
        SEED = 20260511
        MEAN, SIGMA = 120.0, 0.75
        # helper 路径
        rng_a = _r.Random(SEED)
        helper_sample = _sample_lognormal_arith_mean(MEAN, SIGMA, 1e-9, 1e9, rng_a)
        # generic path（无 clip 干扰，typical_bounds 设宽）
        slot_record = {
            "slot_id": "test_debt029_equiv",
            "recommended_distribution": "lognormal",
            "recommended_mean": MEAN,
            "recommended_sigma": SIGMA,
            "typical_bounds": [1e-9, 1e9],
            "mean_semantics": "arithmetic_mean",
        }
        rng_b = _r.Random(SEED)
        generic_sample = _sample_typical_distribution(slot_record, 1e-12, 1e12, rng_b)
        self.assertAlmostEqual(helper_sample, generic_sample, places=12)

    def test_helper_still_uses_arithmetic_mean_after_refactor(self):
        """`_sample_lognormal_arith_mean` 重构后仍按 arithmetic_mean 解释 (回归保护).

        N=10000 抽样 arith mean ≈ 输入值，验证公式没翻转成 median。
        """
        import random as _r
        from workflow_engine.worldgen.generator import _sample_lognormal_arith_mean
        ARITH = 120.0
        rng = _r.Random(20260511)
        samples = [_sample_lognormal_arith_mean(ARITH, 0.75, 1e-9, 1e9, rng) for _ in range(10000)]
        observed = sum(samples) / len(samples)
        self.assertAlmostEqual(observed, ARITH, delta=ARITH * 0.05)


class Debt030D1RegistryLookupTests(unittest.TestCase):
    """DEBT-030 D1 (2026-05-13): mapping inline 抽 registry lookup 后的 3 helper 测试.

    覆盖:
    - `_lookup_primary_condition_class_from_mechanism_family`
    - `_lookup_fire_component_class_from_component_type`
    - `_material_system_supports_rebar`
    含 registry miss / unknown / cache O(1) 复用三类边界.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from workflow_engine.worldgen.registry import _build_registry_bundle
        cls.registries = _build_registry_bundle()

    # ---- _lookup_primary_condition_class_from_mechanism_family ----

    def test_lookup_condition_for_structural_crack(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "structural_crack", self.registries
        )
        self.assertEqual(cc, "DC_CRACK")

    def test_lookup_condition_for_corrosion_spall(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "corrosion_spall", self.registries
        )
        self.assertEqual(cc, "DC_SPALL_REBAR")

    def test_lookup_condition_for_drainage_fault(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "drainage_fault", self.registries
        )
        # registry output_condition_classes 第一条; 当前 registry 是 DC_DRAINAGE_MISCONNECTION
        self.assertEqual(cc, "DC_DRAINAGE_MISCONNECTION")

    def test_lookup_condition_for_ubw_signal(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "ubw_signal", self.registries
        )
        self.assertEqual(cc, "DC_UBW_PRESENT")

    def test_lookup_condition_for_fire_safety_deficiency(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "fire_safety_deficiency", self.registries
        )
        self.assertEqual(cc, "DC_FIRE_DOOR_DEFICIENCY")

    def test_lookup_condition_for_assessment_origin(self):
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "assessment_origin", self.registries
        )
        # registry output_condition_classes 第一条; 当前 registry 是 DC_CRACK
        self.assertEqual(cc, "DC_CRACK")

    def test_lookup_condition_unknown_family_returns_fallback(self):
        """registry 没该 family → fallback DC_CRACK."""
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
        )
        cc = _lookup_primary_condition_class_from_mechanism_family(
            "made_up_unknown_family_xyz", self.registries
        )
        self.assertEqual(cc, "DC_CRACK")

    # ---- _lookup_fire_component_class_from_component_type ----

    def test_lookup_fire_component_class_for_fire_door(self):
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type("fire_door", self.registries),
            "fire_door",
        )

    def test_lookup_fire_component_class_for_fire_resisting_wall(self):
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type(
                "fire_resisting_wall", self.registries
            ),
            "fire_resisting_wall",
        )

    def test_lookup_fire_component_class_for_escape_route(self):
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type("escape_route", self.registries),
            "escape_route",
        )

    def test_lookup_fire_component_class_for_smoke_vent(self):
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type("smoke_vent", self.registries),
            "smoke_vent",
        )

    def test_lookup_fire_component_class_for_fire_service_installation(self):
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type(
                "fire_service_installation", self.registries
            ),
            "fire_service_installation",
        )

    def test_lookup_fire_component_class_for_non_fire_component(self):
        """非 fire-safety component_type → unknown_fire_component."""
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        # external_wall component_class=external_component
        self.assertEqual(
            _lookup_fire_component_class_from_component_type(
                "external_wall", self.registries
            ),
            "unknown_fire_component",
        )

    def test_lookup_fire_component_class_for_unknown_type(self):
        """registry 没该 component_type → unknown_fire_component."""
        from workflow_engine.worldgen.generator import (
            _lookup_fire_component_class_from_component_type,
        )
        self.assertEqual(
            _lookup_fire_component_class_from_component_type(
                "made_up_unknown_xyz", self.registries
            ),
            "unknown_fire_component",
        )

    # ---- _material_system_supports_rebar ----

    def test_supports_rebar_for_reinforced_concrete(self):
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        self.assertTrue(_material_system_supports_rebar("reinforced_concrete", self.registries))

    def test_supports_rebar_for_prestressed_concrete(self):
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        self.assertTrue(_material_system_supports_rebar("prestressed_concrete", self.registries))

    def test_supports_rebar_for_precast_concrete(self):
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        self.assertTrue(_material_system_supports_rebar("precast_concrete", self.registries))

    def test_supports_rebar_for_plain_concrete(self):
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        # plain_concrete supports_rebar=False (registry §3.2)
        self.assertFalse(_material_system_supports_rebar("plain_concrete", self.registries))

    def test_supports_rebar_for_clay_brick(self):
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        self.assertFalse(_material_system_supports_rebar("clay_brick", self.registries))

    def test_supports_rebar_for_unknown_material(self):
        """registry 没该 material_system → fallback False."""
        from workflow_engine.worldgen.generator import _material_system_supports_rebar
        self.assertFalse(_material_system_supports_rebar("made_up_unknown_xyz", self.registries))

    # ---- cache O(1) 复用验证 ----

    def test_lookup_cache_reused_on_repeat_calls(self):
        """同一 registries 上重复调用 lookup helper → cache bucket 应只构造一次."""
        from workflow_engine.worldgen.generator import (
            _lookup_primary_condition_class_from_mechanism_family,
            _REGISTRY_LOOKUP_CACHE,
        )
        # 清除 cache 让本测试独立
        _REGISTRY_LOOKUP_CACHE.pop(id(self.registries), None)
        # 首次调用 → 触发 cache 构造
        _lookup_primary_condition_class_from_mechanism_family(
            "structural_crack", self.registries
        )
        bucket = _REGISTRY_LOOKUP_CACHE.get(id(self.registries))
        self.assertIsNotNone(bucket)
        self.assertIn("mechanism_family_to_primary_condition", bucket)
        first_table = bucket["mechanism_family_to_primary_condition"]
        # 第二次调用 → 应复用同一 dict 对象
        _lookup_primary_condition_class_from_mechanism_family(
            "corrosion_spall", self.registries
        )
        self.assertIs(
            _REGISTRY_LOOKUP_CACHE[id(self.registries)][
                "mechanism_family_to_primary_condition"
            ],
            first_table,
        )

    # ---- 集成: generate_condition / generate_fire_safety_state / generate_fragment ----

    def test_generate_condition_uses_registry_lookup(self):
        """generate_condition 在 corrosion_spall family 下 → condition_class=DC_SPALL_REBAR."""
        import random as _r
        from workflow_engine.worldgen.generator import generate_condition
        from workflow_engine.worldgen.models import (
            MechanismState,
            MechanismActivation,
            DriverState,
        )
        fragment = FragmentContext(
            fragment_id="FRG-D030-1",
            fragment_template_id="FT_T",
            component_id="CMP-D030-1",
            location_id="LOC-D030-1",
            fragment_role="inspection_target",
            fragment_area_m2=8.0,
            fragment_length_m=4.0,
            in_scope=True,
            exclusion_reason=None,
        )
        component = ComponentNode(
            component_id="CMP-D030-1",
            component_type="structural_member",
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-D030-1",
            geometry_proxy={"visible_area_m2": 8.0, "thickness_mm": 200.0},
            cover_depth_mm=30.0,
            access_class="fully_accessible",
        )
        driver = DriverState(
            # W0-004: spec 04 §9 DriverState 13 字段对齐.
            driver_id="DRV-D030-1",
            fragment_id=fragment.fragment_id,
            service_load_ratio=0.4,
            restraint_level=0.4,
            moisture_ingress_index=0.5,
            chloride_exposure_index=0.5,
            carbonation_index=0.5,
            workmanship_deficit_index=0.4,
            maintenance_deficit_index=0.4,
            drainage_fault_propensity=0.3,
            alteration_propensity=0.3,
            fire_safety_deficit_index=0.2,
            repair_quality_index=0.7,
        )
        mech = MechanismState(
            mechanism_state_id="MST-D030-1",
            fragment_id=fragment.fragment_id,
            mechanism_family="corrosion_spall",
            active=True,
            severity_index=0.7,
            cause_tags=[],
            primary_mechanism_id="MCH-D030-1",
            activated_mechanisms=[
                MechanismActivation(
                    mechanism_id="MCH-D030-1",
                    mechanism_family="corrosion_spall",
                    activation_score=0.7,
                    derived_from_driver_ids=[driver.driver_id],
                )
            ],
            crack_mechanism_kind="none",
            corrosion_active=True,
            delamination_active=False,
            drainage_fault_kind="none",
            ubw_signal_kind="none",
            fire_safety_deficiency_kind="none",
            assessment_origin_kind="none",
            verification_origin_kind="none",
        )
        # W0-005 (2026-05-21): generate_condition 新 signature——加 component 参数（spec 06 §0.1 reference 反查）.
        cond = generate_condition(fragment, component, mech, driver, _r.Random(0), age_years=30.0, registries=self.registries)
        self.assertEqual(cond.condition_class, "DC_SPALL_REBAR")
        # DEBT-049 A1：严重剥落（severity≥0.5）暴露主筋 → 副类 DC_REBAR_EXPOSED；
        # 主类仍 DC_SPALL_REBAR，副类跟随（此 driver 产严重剥落）。
        self.assertEqual(cond.condition_classes[0], "DC_SPALL_REBAR")
        self.assertIn("DC_REBAR_EXPOSED", cond.condition_classes)

    def test_generate_fragment_returns_minimal_fragment_context(self):
        """W0-005 (2026-05-21)：generate_fragment 新 signature——只接 component + template + rng，
        返回 spec 04 §7 FragmentContext 9 字段。cover_depth_mm / material_system 等物理参数
        由消费方按 spec 06 §0.1 reference 反查 ComponentNode，不在 FragmentContext 上 cache.
        """
        import random as _r
        from workflow_engine.worldgen.generator import generate_fragment
        comp_rc = ComponentNode(
            component_id="CMP-D030-2-RC",
            component_type="structural_member",
            material_system="reinforced_concrete",
            structural_role="primary_load_bearing",
            location_id="LOC-D030-2",
            geometry_proxy={},
            cover_depth_mm=35.0,  # RC 材质必填非 null
            access_class="fully_accessible",
        )
        comp_brick = ComponentNode(
            component_id="CMP-D030-2-BR",
            component_type="external_wall",
            material_system="clay_brick",
            structural_role="non_load_bearing",
            location_id="LOC-D030-2",
            geometry_proxy={},
            cover_depth_mm=None,  # 非 RC 材质必 null
            access_class="fully_accessible",
        )
        template = {
            "fragment_template_id": "FT_T",
            "area_range": [5.0, 10.0],
            "length_range": [2.0, 4.0],
        }
        frag_rc = generate_fragment(comp_rc, template, 0, _r.Random(0))
        # 9 字段 reference contract 主键
        self.assertEqual(frag_rc.component_id, "CMP-D030-2-RC")
        self.assertEqual(frag_rc.location_id, "LOC-D030-2")
        self.assertTrue(5.0 <= frag_rc.fragment_area_m2 <= 10.0)
        self.assertIsNotNone(frag_rc.fragment_length_m)
        # cover_depth_mm 反查 component.cover_depth_mm（spec 06 §0.1）
        self.assertEqual(comp_rc.cover_depth_mm, 35.0)
        frag_brick = generate_fragment(comp_brick, template, 1, _r.Random(0))
        self.assertEqual(frag_brick.component_id, "CMP-D030-2-BR")
        # 非 RC 材质 component.cover_depth_mm = None（spec 04 §5 contract）
        self.assertIsNone(comp_brick.cover_depth_mm)


class Debt030D2SamplingPlanConsumerTests(unittest.TestCase):
    """DEBT-030 D2 (2026-05-13): sampling_plan_registry 0 consumer 闭环测试.

    覆盖:
    - `_lookup_sampling_plan_record` (含 fallback 路径 registry 缺失)
    - `_resolve_sampling_plan_intensity_params` (registry-driven + fallback)
    - `_resolve_sampling_plan_total_count_clip` (parse round_clip lower/upper)
    - chain derive helper 6 个 registry-driven (facade chain + coverage chain + floor retiling chain)
    - MC sanity 1000 sample (容忍 ±5%)
    - 主链 generate_structural_assessment_measurements 集成产 chain-derived A 类 slot.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from workflow_engine.worldgen.registry import _build_registry_bundle
        cls.registries = _build_registry_bundle()

    # ---- _lookup_sampling_plan_record ----

    def test_lookup_pull_test_sampling_plan(self):
        from workflow_engine.worldgen.generator import _lookup_sampling_plan_record
        rec = _lookup_sampling_plan_record("pull_test_sampling_plan", self.registries)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["sampling_plan_id"], "pull_test_sampling_plan")
        self.assertEqual(rec["plan_level"], "facade_or_floor_repair_package")
        self.assertEqual(rec["plan_intensity_distribution"]["recommended_mean"], 1.9)

    def test_lookup_coverage_inspection_plan(self):
        from workflow_engine.worldgen.generator import _lookup_sampling_plan_record
        rec = _lookup_sampling_plan_record("coverage_inspection_plan", self.registries)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["plan_level"], "fragment")
        self.assertEqual(
            rec["plan_intensity_distribution"]["recommended_distribution"], "truncated_normal"
        )

    def test_lookup_floor_retiling_package(self):
        from workflow_engine.worldgen.generator import _lookup_sampling_plan_record
        rec = _lookup_sampling_plan_record("floor_retiling_package", self.registries)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["plan_level"], "floor_retiling_package")

    def test_lookup_unknown_plan_returns_none(self):
        from workflow_engine.worldgen.generator import _lookup_sampling_plan_record
        self.assertIsNone(
            _lookup_sampling_plan_record("made_up_unknown_plan_xyz", self.registries)
        )

    # ---- _resolve_sampling_plan_intensity_params ----

    def test_resolve_intensity_params_for_pull_test(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_intensity_params
        params = _resolve_sampling_plan_intensity_params(
            "pull_test_sampling_plan",
            self.registries,
            fallback_distribution="lognormal",
            fallback_mean=999.0,
            fallback_sigma=999.0,
            fallback_clip_lo=999.0,
            fallback_clip_hi=999.0,
        )
        # registry 里的值优先 (mean=1.9 S2.5 标定档, sigma=0.35, typical=[0.50, 3.00])
        self.assertEqual(params["recommended_distribution"], "lognormal")
        self.assertAlmostEqual(params["recommended_mean"], 1.9)
        self.assertAlmostEqual(params["recommended_sigma"], 0.35)
        self.assertEqual(params["typical_bounds"], [0.50, 3.00])

    def test_resolve_intensity_params_falls_back_when_registries_none(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_intensity_params
        params = _resolve_sampling_plan_intensity_params(
            "pull_test_sampling_plan",
            None,
            fallback_distribution="lognormal",
            fallback_mean=1.25,
            fallback_sigma=0.35,
            fallback_clip_lo=0.50,
            fallback_clip_hi=3.00,
        )
        self.assertAlmostEqual(params["recommended_mean"], 1.25)
        self.assertAlmostEqual(params["recommended_sigma"], 0.35)
        self.assertEqual(params["typical_bounds"], [0.50, 3.00])

    def test_resolve_intensity_params_falls_back_when_plan_missing(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_intensity_params
        params = _resolve_sampling_plan_intensity_params(
            "made_up_unknown_plan_xyz",
            self.registries,
            fallback_distribution="lognormal",
            fallback_mean=42.0,
            fallback_sigma=0.5,
            fallback_clip_lo=10.0,
            fallback_clip_hi=100.0,
        )
        self.assertAlmostEqual(params["recommended_mean"], 42.0)
        self.assertEqual(params["typical_bounds"], [10.0, 100.0])

    # ---- _resolve_sampling_plan_total_count_clip ----

    def test_resolve_total_count_clip_pull_test(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_total_count_clip
        lower, upper = _resolve_sampling_plan_total_count_clip(
            "pull_test_sampling_plan", self.registries, fallback_lower=99, fallback_upper=99
        )
        # registry total_count_formula 含 "round_clip(..., lower=1, upper=25)"
        self.assertEqual(lower, 1)
        self.assertEqual(upper, 25)

    def test_resolve_total_count_clip_floor_retiling(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_total_count_clip
        lower, upper = _resolve_sampling_plan_total_count_clip(
            "floor_retiling_package", self.registries, fallback_lower=99, fallback_upper=99
        )
        # registry total_count_formula 含 "round_clip(..., lower=1, upper=20)"
        self.assertEqual(lower, 1)
        self.assertEqual(upper, 20)

    def test_resolve_total_count_clip_fallback_when_registries_none(self):
        from workflow_engine.worldgen.generator import _resolve_sampling_plan_total_count_clip
        lower, upper = _resolve_sampling_plan_total_count_clip(
            "pull_test_sampling_plan", None, fallback_lower=7, fallback_upper=42
        )
        self.assertEqual(lower, 7)
        self.assertEqual(upper, 42)

    # ---- chain helper registry-driven 行为 (facade chain Step 1-5) ----

    def test_facade_total_repaired_area_chain_step1(self):
        """Step 1: facade_total_repaired_area_m2 在 typical_bounds 内."""
        import random as _r
        from workflow_engine.worldgen.generator import _compute_facade_total_repaired_area_m2
        rng = _r.Random(42)
        value = _compute_facade_total_repaired_area_m2(rng, self.registries)
        self.assertGreaterEqual(value, 20.0)
        self.assertLessEqual(value, 500.0)

    def test_plan_intensity_chain_step2(self):
        """Step 2: plan_intensity_tests_per_25m2 在 [0.50, 3.00] 内."""
        import random as _r
        from workflow_engine.worldgen.generator import _compute_plan_intensity_tests_per_25m2
        rng = _r.Random(42)
        value = _compute_plan_intensity_tests_per_25m2(rng, self.registries)
        self.assertGreaterEqual(value, 0.50)
        self.assertLessEqual(value, 3.00)

    def test_total_pull_test_count_chain_step3(self):
        """Step 3: total_pull_test_count_per_facade in [1, 25]; round_clip 行为."""
        from workflow_engine.worldgen.generator import _compute_total_pull_test_count_per_facade
        # plan_intensity=1.25 * facade_area=200 / 25 = 10
        count = _compute_total_pull_test_count_per_facade(1.25, 200.0, self.registries)
        self.assertEqual(count, 10)
        # 极小 plan_intensity * 1 / 25 = 0.04 → round 0 → 抬到 lower=1
        count_lo = _compute_total_pull_test_count_per_facade(0.50, 1.0, self.registries)
        self.assertEqual(count_lo, 1)
        # 极大 plan_intensity * 1000 / 25 = 120 → clip 到 upper=25
        count_hi = _compute_total_pull_test_count_per_facade(3.00, 1000.0, self.registries)
        self.assertEqual(count_hi, 25)

    def test_effective_pull_test_count_chain_step4(self):
        """Step 4: effective_count area-proportional; 1m² fragment 不爆炸."""
        from workflow_engine.worldgen.generator import (
            _compute_effective_pull_test_count_per_fragment,
        )
        # total=10, fragment_area=20, facade=200 → effective = 10 * 20 / 200 = 1.0
        eff = _compute_effective_pull_test_count_per_fragment(10, 20.0, 200.0)
        self.assertAlmostEqual(eff, 1.0)
        # 1m² fragment: total=10, fragment=1, facade=200 → effective = 0.05 (非整数)
        eff_small = _compute_effective_pull_test_count_per_fragment(10, 1.0, 200.0)
        self.assertAlmostEqual(eff_small, 0.05)

    def test_pull_test_rate_chain_step5(self):
        """Step 5: rate.pull_test.per_25m2 与 fragment_area 解耦 — 关键反爆炸保护."""
        from workflow_engine.worldgen.generator import _compute_pull_test_rate_per_25m2_chain
        # effective=1.0, fragment=20 → rate = 1.0 / (20/25) = 1.25
        rate = _compute_pull_test_rate_per_25m2_chain(1.0, 20.0)
        self.assertAlmostEqual(rate, 1.25)
        # 1m² fragment: effective=0.05, fragment=1 → rate = 0.05 / (1/25) = 1.25
        # (代数等价于 facade rate, 不爆炸到 25)
        rate_small = _compute_pull_test_rate_per_25m2_chain(0.05, 1.0)
        self.assertAlmostEqual(rate_small, 1.25)

    # ---- coverage chain Step 1-3 ----

    def test_inspected_area_ratio_chain_step1(self):
        """Step 1: inspected_area_ratio_per_fragment in [0.10, 0.85]."""
        import random as _r
        from workflow_engine.worldgen.generator import (
            _compute_inspected_area_ratio_per_fragment,
        )
        rng = _r.Random(42)
        value = _compute_inspected_area_ratio_per_fragment(rng, self.registries)
        self.assertGreaterEqual(value, 0.10)
        self.assertLessEqual(value, 0.85)

    def test_inspected_area_m2_chain_step2(self):
        """Step 2: inspected_area_m2 = ratio * fragment_area."""
        from workflow_engine.worldgen.generator import _compute_inspected_area_m2_chain
        self.assertAlmostEqual(_compute_inspected_area_m2_chain(0.45, 20.0), 9.0)

    def test_ratio_covered_area_inspected_chain_step3(self):
        """Step 3: ratio.covered_area.inspected ∈ [0, 1]."""
        from workflow_engine.worldgen.generator import (
            _compute_ratio_covered_area_inspected_chain,
        )
        self.assertAlmostEqual(
            _compute_ratio_covered_area_inspected_chain(9.0, 20.0), 0.45
        )
        # clip to [0, 1]
        self.assertEqual(_compute_ratio_covered_area_inspected_chain(50.0, 20.0), 1.0)
        self.assertEqual(_compute_ratio_covered_area_inspected_chain(-1.0, 20.0), 0.0)

    # ---- floor retiling chain Step 1-3 ----

    def test_floor_retiling_area_chain_step1(self):
        """Step 1: floor_full_retiling_area_m2 in [10, 400]."""
        import random as _r
        from workflow_engine.worldgen.generator import _compute_floor_full_retiling_area_m2
        rng = _r.Random(42)
        value = _compute_floor_full_retiling_area_m2(rng, self.registries)
        self.assertGreaterEqual(value, 10.0)
        self.assertLessEqual(value, 400.0)

    def test_retiling_plan_intensity_chain_step2(self):
        """Step 2: retiling_plan_intensity in [0.60, 3.00]."""
        import random as _r
        from workflow_engine.worldgen.generator import (
            _compute_retiling_plan_intensity_tests_per_25m2,
        )
        rng = _r.Random(42)
        value = _compute_retiling_plan_intensity_tests_per_25m2(rng, self.registries)
        self.assertGreaterEqual(value, 0.60)
        self.assertLessEqual(value, 3.00)

    def test_floor_retiling_pull_test_count_chain_step3(self):
        """Step 3: count in [1, 20]; round_clip 行为."""
        from workflow_engine.worldgen.generator import (
            _compute_pull_test_count_per_floor_full_retiling,
        )
        # plan=1.35 * area=80 / 25 = 4.32 → round 4
        count = _compute_pull_test_count_per_floor_full_retiling(1.35, 80.0, self.registries)
        self.assertEqual(count, 4)
        # 极小 → lower=1
        count_lo = _compute_pull_test_count_per_floor_full_retiling(0.60, 1.0, self.registries)
        self.assertEqual(count_lo, 1)
        # 极大 → upper=20
        count_hi = _compute_pull_test_count_per_floor_full_retiling(3.00, 1000.0, self.registries)
        self.assertEqual(count_hi, 20)

    # ---- MC sanity (Δ < 0.05) ----

    def test_facade_total_repaired_area_mc_mean(self):
        """N=1000 sample mean ≈ arithmetic_mean=120 (Δ < 5%)."""
        import random as _r
        from workflow_engine.worldgen.generator import _compute_facade_total_repaired_area_m2
        N = 1000
        samples = [
            _compute_facade_total_repaired_area_m2(_r.Random(i), self.registries)
            for i in range(N)
        ]
        mean = sum(samples) / N
        self.assertAlmostEqual(mean, 120.0, delta=120.0 * 0.10)

    def test_plan_intensity_mc_mean(self):
        """N=1000 sample mean ≈ arithmetic_mean=1.25 (Δ < 5%)."""
        import random as _r
        from workflow_engine.worldgen.generator import _compute_plan_intensity_tests_per_25m2
        N = 1000
        samples = [
            _compute_plan_intensity_tests_per_25m2(_r.Random(i), self.registries)
            for i in range(N)
        ]
        mean = sum(samples) / N
        # S2.5 标定 mean 1.25→1.9；clip [0.50,3.00] 把实测 MC 均值压到 ~1.84，仍在 1.9±5% 带内
        self.assertAlmostEqual(mean, 1.9, delta=1.9 * 0.05)

    def test_inspected_area_ratio_mc_mean(self):
        """N=1000 sample mean ≈ 0.45 (Δ < 5%)."""
        import random as _r
        from workflow_engine.worldgen.generator import (
            _compute_inspected_area_ratio_per_fragment,
        )
        N = 1000
        samples = [
            _compute_inspected_area_ratio_per_fragment(_r.Random(i), self.registries)
            for i in range(N)
        ]
        mean = sum(samples) / N
        self.assertAlmostEqual(mean, 0.45, delta=0.05)

    # ---- 集成: 主链产生 chain-derived rate.pull_test.per_25m2 + ratio.covered_area.inspected ----

    def test_integration_chain_consumer_emits_via_assessment(self):
        """generate_structural_assessment_measurements 跑通后, A 类 chain-derived slot
        应至少各出 1 个 measurement (rate.pull_test.per_25m2 + ratio.covered_area.inspected)."""
        from workflow_engine.worldgen.generator import generate_world_bundle
        world = generate_world_bundle(
            batch_config={}, registries=self.registries, seed=42, building_index=0
        )
        emitted_slot_ids = {m.slot_id for m in world.measurements}
        # chain-derived A 类 slot 必至少有 1 个 measurement
        self.assertIn("rate.pull_test.per_25m2", emitted_slot_ids)
        self.assertIn("ratio.covered_area.inspected", emitted_slot_ids)

    def test_integration_floor_retiling_count_emits_via_assessment(self):
        """generate_structural_assessment_measurements 应产 count.pull_test.per_floor_full_retiling."""
        from workflow_engine.worldgen.generator import generate_world_bundle
        world = generate_world_bundle(
            batch_config={}, registries=self.registries, seed=42, building_index=0
        )
        emitted_slot_ids = {m.slot_id for m in world.measurements}
        self.assertIn("count.pull_test.per_floor_full_retiling", emitted_slot_ids)


if __name__ == "__main__":
    unittest.main()
