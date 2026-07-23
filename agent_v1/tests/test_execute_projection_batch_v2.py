"""execute_projection_batch_v2 tests — v2 化批量 projection executor."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import (  # noqa: E402
    _read_projection_results_parquet,
    execute_projection_batch_v2,
)
from workflow_engine.worldgen.validation import (  # noqa: E402
    run_worldgenerator_fullcoverage_framework_v2,
)


class ExecuteProjectionBatchV2Tests(unittest.TestCase):
    """v2 batch executor 端到端 + aggregation 验证."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.gen_dir = Path(cls.tmp.name) / "gen"
        cls.proj_dir = Path(cls.tmp.name) / "proj"
        # 先跑 v2 entry 产生 building_worlds + sidecar + normative_projection
        cls.gen_result = run_worldgenerator_fullcoverage_framework_v2(
            output_dir=cls.gen_dir, count=8, seed=42, fragment_count_per_building=4,
        )
        # 跑 v2 batch executor
        cls.exec_result = execute_projection_batch_v2(
            building_worlds_path=Path(cls.gen_result["building_worlds_path"]),
            normative_projection_path=Path(cls.gen_result["normative_projection_path"]),
            sidecar_runtime_path=Path(cls.gen_result["sidecar_runtime_bundle_path"]),
            output_dir=cls.proj_dir,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_three_output_files_emitted(self) -> None:
        for key in ("summary_path", "results_path", "samples_path"):
            self.assertIn(key, self.exec_result)
            self.assertTrue(Path(self.exec_result[key]).exists())

    def test_summary_v2_version_string(self) -> None:
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], "regulation_projection.summary.v2")

    def test_summary_buildings_count_matches(self) -> None:
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["buildings_count"], 8)
        self.assertGreater(payload["total_projections"], 0)

    def test_summary_aggregates_verdict_distribution(self) -> None:
        """spec 04 §16 projection_status 聚合."""
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertIn("verdict_distribution", payload)
        # verdict_distribution 总和等于 total_projections
        self.assertEqual(
            sum(payload["verdict_distribution"].values()),
            payload["total_projections"],
        )

    def test_summary_aggregates_family_hits(self) -> None:
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertIn("family_hit_distribution", payload)
        # 至少有 1 个 selected_family
        self.assertGreater(len(payload["family_hit_distribution"]), 0)

    def test_summary_severity_band_distribution(self) -> None:
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertIn("severity_band_distribution", payload)
        # 总和等于 total_projections
        self.assertEqual(
            sum(payload["severity_band_distribution"].values()),
            payload["total_projections"],
        )

    def test_summary_threshold_regime_aggregated(self) -> None:
        """spec 06 §15 5-bin regime 聚合."""
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertIn("threshold_regime_distribution", payload)
        # threshold regime 应是 spec §15 6 个 bin 之一
        valid_regimes = {
            "far_below", "near_below", "exact_threshold",
            "near_above", "far_above", "not_numeric",
        }
        for regime in payload["threshold_regime_distribution"]:
            self.assertIn(regime, valid_regimes)

    def test_summary_no_sidecar_missing_markers(self) -> None:
        """spec 09 §1.2 (2026-05-09 修订)：废止 marker.sidecar_missing；count 应为 0.

        旧行为："W0-only sidecar bundle 应全部含 sidecar_missing marker"——已废止。
        sidecar bundle 由 worldgen 派生层同步生成，不存在缺失态。
        """
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["sidecar_missing_marker_count"], 0)
        self.assertGreater(payload["sidecar_records_count"], 0)

    def test_results_v2_contains_buildings(self) -> None:
        # 2026-05-10 全替换 parquet：results_path 现在是 directory，用 reader 还原 dict.
        results_path = Path(self.exec_result["results_path"])
        self.assertTrue(results_path.is_dir(), f"results_path 应是 parquet directory: {results_path}")
        payload = _read_projection_results_parquet(results_path)
        self.assertEqual(payload["version"], "regulation_projection.results.v2")
        self.assertEqual(payload["buildings_count"], 8)
        self.assertEqual(len(payload["buildings"]), 8)

    def test_samples_v2_capped_at_10(self) -> None:
        payload = json.loads(Path(self.exec_result["samples_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], "regulation_projection.samples.v2")
        self.assertLessEqual(len(payload["samples"]), 10)

    def test_samples_have_world_id_and_projections(self) -> None:
        payload = json.loads(Path(self.exec_result["samples_path"]).read_text(encoding="utf-8"))
        for sample in payload["samples"]:
            self.assertIn("world_id", sample)
            self.assertIn("projections", sample)
            self.assertIn("projection_count", sample)
            self.assertLessEqual(len(sample["projections"]), 5)

    def test_unknown_reason_breakdown_only_listed_codes(self) -> None:
        """spec 06 §16.3 13 项 unknown_reason_code 之外不该有别的 reason."""
        payload = json.loads(Path(self.exec_result["summary_path"]).read_text(encoding="utf-8"))
        valid_reasons = {
            "no_known_family_match", "unsupported_material_system",
            "unsupported_component_type", "unsupported_damage_pattern",
            "unsupported_location_context", "projection_binding_incompatible",
            "binding_registry_gap", "multi_family_conflict",
            "sidecar_only_fact_pattern", "coverage_unimplemented_domain",
            "measurement_family_unimplemented", "method_class_unimplemented",
            "unit_incompatible",
        }
        for reason in payload["unknown_reason_breakdown"]:
            self.assertIn(reason, valid_reasons)


if __name__ == "__main__":
    unittest.main()
