"""Integration test: parquet 全替换不破坏 deterministic_key 与 round-trip 等价 (2026-05-10).

测试范围:
  1. 100 building × seed=42 跑两次 → deterministic_key byte-identical
  2. 100 building × seed=42 写 parquet → 读出来 → 跟原 payload (从 model_dump) 完全等价
  3. parquet 路径下 execute_projection_batch_v2 输出与 JSON 路径下应一致（间接验证 reader 不丢字段）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.regulation_projection_executor import execute_projection_batch_v2  # noqa: E402
from workflow_engine.worldgen.parquet_io import (  # noqa: E402
    read_world_bundles_parquet,
    read_sidecar_runtime_parquet,
    read_normative_projection_parquet,
    write_world_bundles_parquet,
    write_sidecar_runtime_parquet,
    write_normative_projection_parquet,
)
from workflow_engine.worldgen.validation import (  # noqa: E402
    run_worldgenerator_fullcoverage_framework_v2,
)


class ParquetIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.run1 = Path(cls.tmp.name) / "run1"
        cls.run2 = Path(cls.tmp.name) / "run2"
        cls.gen_result1 = run_worldgenerator_fullcoverage_framework_v2(
            output_dir=cls.run1, count=100, seed=42, fragment_count_per_building=4,
        )
        cls.gen_result2 = run_worldgenerator_fullcoverage_framework_v2(
            output_dir=cls.run2, count=100, seed=42, fragment_count_per_building=4,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_deterministic_key_stable_across_runs(self) -> None:
        """同 seed 重跑 → deterministic_key 一致（说明 parquet 切换没破坏 hash 输入）."""
        self.assertEqual(
            self.gen_result1["deterministic_key"],
            self.gen_result2["deterministic_key"],
            "deterministic_key drifted between two identical runs after parquet migration",
        )

    def test_world_bundles_roundtrip_full_payload(self) -> None:
        """100 building 真数据：parquet write → read → 与原 dict 完全等价."""
        from workflow_engine.worldgen.generator import generate_world_batch
        from workflow_engine.worldgen.registry import _build_registry_bundle

        registries = _build_registry_bundle()
        building_worlds = generate_world_batch(
            batch_config={}, registries=registries, count=20, seed=42,
            fragment_count_per_building=4,
        )
        original_payload = {
            "version": "worldgen.fullcoverage.building_worlds.v2",
            "generated_at": "2026-04-26T00:00:00+00:00",
            "registry_bundle_hash": "x",
            "batch_config_hash": "y",
            "deterministic_key": "z",
            "buildings": [bw.model_dump(mode="json") for bw in building_worlds],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "wb_pq"
            write_world_bundles_parquet(out_dir, original_payload)
            restored = read_world_bundles_parquet(out_dir)
        self.assertEqual(
            restored, original_payload,
            "world bundles round-trip mismatch on 20-building real data",
        )

    def test_executor_results_identical_parquet_vs_json(self) -> None:
        """summary 输出在 parquet path 下应跟 JSON path 下数值一致."""
        # gen_result1 的 path 已经是 parquet directory (新代码默认输出)
        proj_dir_pq = Path(self.tmp.name) / "proj_pq"
        exec_pq = execute_projection_batch_v2(
            building_worlds_path=Path(self.gen_result1["building_worlds_path"]),
            normative_projection_path=Path(self.gen_result1["normative_projection_path"]),
            sidecar_runtime_path=Path(self.gen_result1["sidecar_runtime_bundle_path"]),
            output_dir=proj_dir_pq,
        )
        # 把 parquet 还原成 JSON dump 到临时位置，然后 exec 走 JSON path
        wb = read_world_bundles_parquet(Path(self.gen_result1["building_worlds_path"]))
        sc = read_sidecar_runtime_parquet(Path(self.gen_result1["sidecar_runtime_bundle_path"]))
        np_payload = read_normative_projection_parquet(
            Path(self.gen_result1["normative_projection_path"])
        )
        json_dir = Path(self.tmp.name) / "json_legacy"
        json_dir.mkdir()
        wb_json = json_dir / "wb.json"
        sc_json = json_dir / "sc.json"
        np_json = json_dir / "np.json"
        wb_json.write_text(json.dumps(wb), encoding="utf-8")
        sc_json.write_text(json.dumps(sc), encoding="utf-8")
        np_json.write_text(json.dumps(np_payload), encoding="utf-8")
        proj_dir_json = Path(self.tmp.name) / "proj_json"
        exec_json = execute_projection_batch_v2(
            building_worlds_path=wb_json,
            normative_projection_path=np_json,
            sidecar_runtime_path=sc_json,
            output_dir=proj_dir_json,
        )

        s_pq = json.loads(Path(exec_pq["summary_path"]).read_text(encoding="utf-8"))
        s_json = json.loads(Path(exec_json["summary_path"]).read_text(encoding="utf-8"))
        # 比较关键聚合字段（generated_at + path 字段会变，跳过）
        for k in (
            "buildings_count", "buildings_with_projections", "total_projections",
            "sidecar_records_count", "sidecar_missing_marker_count",
            "sidecar_join_status_distribution", "verdict_distribution",
            "family_hit_distribution", "family_status_breakdown",
            "unknown_reason_breakdown", "severity_band_distribution",
            "coverage_status_distribution", "threshold_regime_distribution",
            "threshold_pass_distribution",
        ):
            self.assertEqual(s_pq[k], s_json[k], f"summary field {k!r} mismatch parquet vs json")

    def test_parquet_directory_smaller_than_json(self) -> None:
        """100 building × 1 seed: parquet 总大小应显著小于等价 JSON dump 大小."""
        bw_dir = Path(self.gen_result1["building_worlds_path"])
        sc_dir = Path(self.gen_result1["sidecar_runtime_bundle_path"])
        np_dir = Path(self.gen_result1["normative_projection_path"])

        pq_total = sum(
            p.stat().st_size for d in (bw_dir, sc_dir, np_dir)
            for p in d.glob("*.parquet")
        )

        # 计算等价 JSON 大小（在内存里序列化测）
        wb = read_world_bundles_parquet(bw_dir)
        sc = read_sidecar_runtime_parquet(sc_dir)
        npp = read_normative_projection_parquet(np_dir)
        json_total = (
            len(json.dumps(wb, ensure_ascii=False).encode("utf-8"))
            + len(json.dumps(sc, ensure_ascii=False).encode("utf-8"))
            + len(json.dumps(npp, ensure_ascii=False).encode("utf-8"))
        )
        ratio = json_total / max(pq_total, 1)
        print(f"\n[Integration] parquet_total={pq_total/(1024**2):.2f}MB "
              f"json_total={json_total/(1024**2):.2f}MB ratio={ratio:.2f}x")
        # 100 building 的小样本一般 6-12x；release_batch (3000 building) 可达 15-25x
        self.assertGreater(ratio, 4.0, f"compression ratio {ratio:.2f}x is below 4x baseline")


if __name__ == "__main__":
    unittest.main()
