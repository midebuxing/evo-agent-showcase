"""Unit tests for worldgen.models module.

Guards Pydantic model structure, defaults, and field contracts.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen.models import (
    BuildingMetadata,
    ConditionState,
    DerivedOutcomeState,
    DomainRecord,
    DrainageState,
    DriverState,
    FireSafetyState,
    FragmentContext,
    GraphEdge,
    GraphNode,
    ManifestationFlag,
    MeasurementRecord,
    MeasurementState,
    MechanismActivation,
    MechanismState,
    RegistryBundle,
    RegistryTable,
    RepairAssessmentState,
    SidecarRuntimeValue,
    SlotOwnershipEntry,
    StageArtifactRef,
    UBWState,
    ValidationCheck,
    WorldLifecycleState,
)


def _make_building_metadata() -> BuildingMetadata:
    """W0-005 (2026-05-21): BuildingMetadata 3 字段 generator 内部 metadata.

    legacy `LegacyFragmentBuildingMeta` 11 字段已删（FragmentRuntimeState 已合并到 FragmentContext，
    不再嵌套 building meta），测试 helper 仅返回 spec 04 §4 外 3 字段 generator 内部 metadata.
    """
    return BuildingMetadata(
        building_template_id="BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
        building_name="Test Tower",
        unit_count=192,
    )


def _make_fragment_context(fragment_id: str = "WG-001") -> FragmentContext:
    """W0-005 (2026-05-21): spec 04 §7 FragmentContext 9 字段 reference-based contract."""
    return FragmentContext(
        fragment_id=fragment_id,
        fragment_template_id="FT_TEST",
        component_id="CMP-WG-001",
        location_id="LOC-WG-001",
        fragment_role="inspection_target",
        fragment_area_m2=11.6,
        fragment_length_m=4.2,
        in_scope=True,
        exclusion_reason=None,
    )


def _make_test_building_world():
    """Return a generated WorldBundle for state-class tests (T-17h step 2)."""
    from workflow_engine.worldgen.generator import generate_world_batch
    from workflow_engine.worldgen.registry import _build_registry_bundle
    registries = _build_registry_bundle()
    return generate_world_batch(batch_config={}, registries=registries, count=1, seed=42)[0]


class ModelInstantiationTests(unittest.TestCase):
    """Guard all Pydantic model classes can be instantiated with minimal arguments."""

    def test_building_metadata_defaults(self) -> None:
        m = _make_building_metadata()
        self.assertEqual(m.building_template_id, "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1")
        self.assertEqual(m.building_name, "Test Tower")
        self.assertEqual(m.unit_count, 192)

    def test_graph_node_defaults(self) -> None:
        n = GraphNode(node_id="N-001", node_type="component", label="test node")
        self.assertEqual(n.node_id, "N-001")
        self.assertIsInstance(n.qualifiers, list)

    def test_graph_edge_defaults(self) -> None:
        e = GraphEdge(edge_id="E-001", relation="covers", source_id="N-001", target_id="N-002")
        self.assertEqual(e.relation, "covers")

    def test_domain_record(self) -> None:
        d = DomainRecord(record_id="DR-001", domain="drainage", kind="stack_segment", status="shared_stack")
        self.assertEqual(d.domain, "drainage")

    def test_fragment_context_defaults(self) -> None:
        fc = _make_fragment_context()
        self.assertEqual(fc.fragment_id, "WG-001")
        # W0-005: spec 04 §7 9 字段 reference-based contract
        self.assertEqual(fc.component_id, "CMP-WG-001")
        self.assertEqual(fc.location_id, "LOC-WG-001")
        self.assertEqual(fc.fragment_role, "inspection_target")
        self.assertEqual(fc.fragment_area_m2, 11.6)
        self.assertTrue(fc.in_scope)

    def test_driver_state(self) -> None:
        # DriverState has many required fields; use a real object from new WorldBundle pipeline
        bw = _make_test_building_world()
        ds = bw.drivers[0]
        self.assertIsInstance(ds.service_load_ratio, float)
        self.assertGreaterEqual(ds.service_load_ratio, 0.0)

    def test_mechanism_activation(self) -> None:
        ma = MechanismActivation(
            mechanism_id="MECH-001",
            mechanism_family="corrosion",
            activation_score=0.7,
        )
        self.assertEqual(ma.activation_score, 0.7)

    def test_mechanism_state(self) -> None:
        # MechanismState requires primary_mechanism_id; use a real object from new WorldBundle pipeline
        bw = _make_test_building_world()
        ms = bw.mechanisms[0]
        self.assertIsInstance(ms.mechanism_state_id, str)

    def test_manifestation_flag(self) -> None:
        f = ManifestationFlag(slot_id="defect.present", value=True)
        self.assertEqual(f.value, True)

    def test_derived_outcome_state_defaults(self) -> None:
        d = DerivedOutcomeState()
        self.assertIsInstance(d.risk_flags, dict)
        self.assertIsInstance(d.repair_flags, dict)
        self.assertIsInstance(d.verification_flags, dict)
        self.assertIsInstance(d.assessment_flags, dict)
        self.assertIsInstance(d.risk_index_values, dict)

    def test_ubw_state_defaults(self) -> None:
        u = UBWState()
        self.assertFalse(u.present)
        self.assertEqual(u.structural_impact, 0.0)

    def test_fire_safety_state_defaults(self) -> None:
        f = FireSafetyState()
        self.assertFalse(f.component_deficiency_present)
        self.assertEqual(f.fire_component_class, "unknown_fire_component")
        self.assertEqual(f.deficiency_class, "not_applicable")
        self.assertEqual(f.record_status_proxy, "physical_only")

    def test_drainage_state_defaults(self) -> None:
        d = DrainageState()
        self.assertEqual(d.public_health_risk_index, 0.0)

    def test_condition_state_defaults(self) -> None:
        d = ConditionState(
            condition_id="COND-001",
            fragment_id="WG-001",
            condition_class="crack",
            manifestation_flags=[],
            derived_outcomes=DerivedOutcomeState(),
        )
        self.assertEqual(d.severity_band, "moderate")
        self.assertIsInstance(d.condition_classes, list)

    def test_measurement_record_defaults(self) -> None:
        mr = MeasurementRecord(
            measurement_id="M-001",
            branch="defect_geometry_measurement",
            slot_id="spall_area_m2",
            value=0.08,
            unit="m2",
            derivation_mode="damage_downstream",
            upstream_refs=["WG-001"],
        )
        self.assertIsInstance(mr.notes, list)
        self.assertIsInstance(mr.origin_chain_refs, list)

    def test_measurement_state_defaults(self) -> None:
        ms = MeasurementState(measurement_state_id="MST-001")
        self.assertIsInstance(ms.defect_geometry_measurements, list)
        self.assertIsInstance(ms.coverage_sampling_measurements, list)

    def test_repair_assessment_state(self) -> None:
        ra = RepairAssessmentState(
            repair_assessment_id="RA-001",
            fragment_id="WG-001",
            repair_quality_index=0.7,
        )
        self.assertIsNone(ra.residual_risk_index)

    def test_building_world_random_seed(self) -> None:
        bw = _make_test_building_world()
        self.assertIsInstance(bw.random_seed, int)
        self.assertGreaterEqual(bw.random_seed, 0)

    def test_building_world_defaults(self) -> None:
        bw = _make_test_building_world()
        self.assertIsInstance(bw.world_id, str)
        self.assertIsInstance(bw.repair_assessment_states, list)
        self.assertIsInstance(bw.fragments, list)
        self.assertIsInstance(bw.measurements, list)

    def test_registry_table(self) -> None:
        rt = RegistryTable(
            registry_id="test_registry",
            ownership="worldgen",
            key_field="id",
            fields=[],
            records=[{"key": "val"}],
        )
        self.assertEqual(rt.registry_id, "test_registry")
        self.assertEqual(len(rt.records), 1)

    def test_registry_bundle_defaults(self) -> None:
        from workflow_engine.worldgen.constants import _utc_now_iso
        rb = RegistryBundle(generated_at=_utc_now_iso(), source_documents=[], registries=[])
        self.assertIsInstance(rb.registries, list)

    def test_slot_ownership_entry(self) -> None:
        e = SlotOwnershipEntry(
            slot_id="artifact.report.inspection",
            partition="sidecar",
            carrier="inspection_report",
        )
        self.assertEqual(e.partition, "sidecar")

    def test_sidecar_runtime_value(self) -> None:
        sv = SidecarRuntimeValue(
            slot_id="reporting.artifact.prepared",
            value=True,
            source_refs=["P-001"],
        )
        self.assertIsInstance(sv.qualifiers, dict)
        self.assertIsInstance(sv.notes, list)

    def test_validation_check(self) -> None:
        vc = ValidationCheck(check_id="test_check", passed=True, detail="all good")
        self.assertTrue(vc.passed)

    def test_stage_artifact_ref(self) -> None:
        sa = StageArtifactRef(stage_name="world_bundle", artifact_path="/tmp/out.json", record_count=120)
        self.assertEqual(sa.record_count, 120)

    # FullCoverageFrameworkBundle test removed (T-17h: OLD-only model class deleted)

    def test_world_lifecycle_state_instantiates(self) -> None:
        lc = WorldLifecycleState()
        self.assertIsInstance(lc, WorldLifecycleState)


class ModelFieldContractTests(unittest.TestCase):
    """Guard important field contracts."""

    def test_building_world_schema_version_default(self) -> None:
        bw = _make_test_building_world()
        self.assertIsInstance(bw.schema_version, str)
        self.assertEqual(bw.schema_version, "worldgen.fullcoverage.world.v1")

    def test_condition_state_derived_outcomes_is_mutable(self) -> None:
        d = DerivedOutcomeState()
        d.risk_flags["risk.building_safety.emergency"] = True
        self.assertTrue(d.risk_flags["risk.building_safety.emergency"])

    def test_repair_assessment_state_residual_risk_index_nullable(self) -> None:
        ra = RepairAssessmentState(
            repair_assessment_id="RA-001",
            fragment_id="WG-001",
            repair_quality_index=0.6,
            residual_risk_index=0.3,
        )
        self.assertEqual(ra.residual_risk_index, 0.3)
        ra2 = RepairAssessmentState(
            repair_assessment_id="RA-002",
            fragment_id="WG-001",
            repair_quality_index=0.6,
        )
        self.assertIsNone(ra2.residual_risk_index)


if __name__ == "__main__":
    unittest.main()
