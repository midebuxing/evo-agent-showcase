"""Missing #2 tests: build_normative_projections_for_world (spec 04 §16)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    MECHANISM_FAMILY_TO_PROJECTION_FAMILIES,
    build_normative_projections_for_world,
)
from workflow_engine.worldgen.generator import generate_world_bundle  # noqa: E402
from workflow_engine.worldgen.registry import _build_registry_bundle  # noqa: E402
from workflow_engine.worldgen.validation import (  # noqa: E402
    run_worldgenerator_fullcoverage_framework_v2,
)


class MechanismToProjectionFamilyMappingTests(unittest.TestCase):
    def test_all_8_mechanism_families_mapped(self) -> None:
        expected = {
            "structural_crack", "corrosion_spall", "moisture_detachment",
            "drainage_fault", "ubw_signal", "fire_safety_deficiency",
            "assessment_origin", "verification_origin",
        }
        self.assertEqual(set(MECHANISM_FAMILY_TO_PROJECTION_FAMILIES.keys()), expected)

    def test_all_target_families_non_empty(self) -> None:
        for family, targets in MECHANISM_FAMILY_TO_PROJECTION_FAMILIES.items():
            self.assertGreater(len(targets), 0, f"{family} has no target projection families")
            for target in targets:
                self.assertTrue(target.startswith("mbis."), f"{family} target {target} not mbis.*")


class BuildNormativeProjectionsForWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registries = _build_registry_bundle()

    def test_one_projection_per_fragment(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        # W2-007 (批次 D 2026-05-21)：默认走 coverage-controlled rejection filter
        # （spec 11 §3.1）；projection count <= fragment-with-mechanism count.
        # 关 filter 验"每 fragment 一 projection"上限不变.
        projections = build_normative_projections_for_world(
            world, self.registries, apply_coverage_control=False,
        )
        self.assertEqual(len(projections), len(world.mechanisms))

        # 开 filter 验 projection count <= fragment count（spec 11 §3.1 accept/reject filter）.
        filtered = build_normative_projections_for_world(world, self.registries)
        self.assertLessEqual(len(filtered), len(world.mechanisms))

    def test_projection_has_required_fields(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        projections = build_normative_projections_for_world(world, self.registries)
        for p in projections:
            self.assertIn("projection_id", p)
            self.assertIn("projection_family", p)
            self.assertIn("world_id", p)
            self.assertIn("selected_family", p)
            self.assertIn("projection_status", p)
            self.assertIn("matched_families", p)
            self.assertIn("required_world_core_slots", p)
            self.assertIn("severity_band", p)

    def test_world_id_matches(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        projections = build_normative_projections_for_world(world, self.registries)
        for p in projections:
            self.assertEqual(p["world_id"], world.world_id)

    def test_projection_status_valid(self) -> None:
        # W2-004 / spec 09 §2: projection_status 三态 covered / uncovered / conflict
        # （NO unknown / sidecar_missing / not_applicable）
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        projections = build_normative_projections_for_world(world, self.registries)
        valid_statuses = {"covered", "uncovered", "conflict"}
        for p in projections:
            self.assertIn(p["projection_status"], valid_statuses)

    def test_projection_id_unique(self) -> None:
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        projections = build_normative_projections_for_world(world, self.registries)
        ids = [p["projection_id"] for p in projections]
        self.assertEqual(len(ids), len(set(ids)))

    def test_projection_id_includes_world_id(self) -> None:
        # W2-011 / spec 09 §2: projection_id 三段格式 NP-<world_id>-<fragment_id>-<index>
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=4)
        projections = build_normative_projections_for_world(world, self.registries)
        for p in projections:
            self.assertTrue(
                p["projection_id"].startswith(f"NP-{world.world_id}-"),
                f"projection_id {p['projection_id']} 应以 NP-{world.world_id}- 开头",
            )

    def test_expected_verdict_present(self) -> None:
        # W2-001 / spec 09 §2: expected_verdict 必填 4 enum
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        projections = build_normative_projections_for_world(world, self.registries)
        valid_verdicts = {"pass", "fail", "unknown", "not_applicable"}
        for p in projections:
            self.assertIn("expected_verdict", p)
            self.assertIn(p["expected_verdict"], valid_verdicts)

    def test_fragment_id_present(self) -> None:
        # W2-002 / spec 09 §2: fragment_id 必填字段
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        projections = build_normative_projections_for_world(world, self.registries)
        for p in projections:
            self.assertIn("fragment_id", p)
            self.assertTrue(p["fragment_id"])

    def test_family_verdict_no_covered_enum(self) -> None:
        # W2-003 / spec 09 §4: matched_families[*].verdict ∈ {pass,fail,unknown,not_applicable}
        # （NO "covered" — covered 是 projection_status 取值，不是 verdict）
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0, fragment_count=10)
        projections = build_normative_projections_for_world(world, self.registries)
        valid_verdicts = {"pass", "fail", "unknown", "not_applicable"}
        for p in projections:
            for mf in p.get("matched_families", []):
                self.assertIn(mf["verdict"], valid_verdicts)
                self.assertNotEqual(mf["verdict"], "covered")

    def test_severity_band_present(self) -> None:
        # W0-006 / spec 04 §11: SeverityBand 5 enum（NO not_applicable）
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        projections = build_normative_projections_for_world(world, self.registries)
        valid_bands = {"none", "minor", "moderate", "severe", "emergency"}
        for p in projections:
            self.assertIn(p["severity_band"], valid_bands)


class V2EntryNormativeProjectionOutputTests(unittest.TestCase):
    """Missing #2 集成: v2 entry 输出 WorldgenNormativeProjection.v2.json."""

    def test_v2_entry_outputs_normative_projection_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=5, seed=42, fragment_count_per_building=4,
            )
            self.assertIn("normative_projection_path", result)
            output_path = Path(result["normative_projection_path"])
            self.assertTrue(output_path.exists())
            # 2026-05-10 全替换 parquet：directory 名 .v2.parquet
            self.assertEqual(output_path.name, "WorldgenNormativeProjection.v2.parquet")
            self.assertTrue(output_path.is_dir())

    def test_v2_entry_normative_projection_count_matches_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=5, seed=42, fragment_count_per_building=4,
            )
            # W2-007 (批次 D 2026-05-21)：spec 11 §3.1 coverage-controlled rejection filter
            # 在 build_normative_projections_for_world_with_coverage_control 内运行，
            # accepted projection 数 <= fragment 数（spec §3.1 accept/reject filter）.
            # 上限不变（不可能多于 fragment with mechanism 数）；下限 >= 1.
            self.assertGreaterEqual(result["normative_projection_count"], 1)
            self.assertLessEqual(
                result["normative_projection_count"], result["fragments_count"]
            )

    def test_v2_entry_normative_projection_json_structure(self) -> None:
        # 2026-05-10 全替换 parquet：用 read_normative_projection_parquet 还原
        from workflow_engine.worldgen.parquet_io import read_normative_projection_parquet
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=3, seed=42, fragment_count_per_building=4,
            )
            output_path = Path(result["normative_projection_path"])
            payload = read_normative_projection_parquet(output_path)
            self.assertIn("version", payload)
            self.assertIn("buildings", payload)
            self.assertEqual(len(payload["buildings"]), 3)
            for entry in payload["buildings"]:
                self.assertIn("world_id", entry)
                self.assertIn("projection_count", entry)
                self.assertIn("projections", entry)


if __name__ == "__main__":
    unittest.main()
