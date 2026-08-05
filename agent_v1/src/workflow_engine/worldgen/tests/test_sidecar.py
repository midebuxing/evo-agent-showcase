"""Unit tests for worldgen.sidecar 派生层 (spec 09 §1.2 修订 2026-05-09).

废止条目（不再有 test）：
    - W0-only / with-sidecar 双 mode
    - SidecarInput 外部注入
    - marker.sidecar_missing 占位 marker
    - worldgen-owned slot intrusion 检测
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class SidecarDerivationTests(unittest.TestCase):
    """spec 09 §1.2 sidecar 派生层 smoke + 采样行为 tests."""

    @classmethod
    def setUpClass(cls) -> None:
        from workflow_engine.worldgen.generator import generate_world_batch
        from workflow_engine.worldgen.registry import _build_registry_bundle

        cls.registries = _build_registry_bundle()
        cls.building_worlds = generate_world_batch(
            batch_config={}, registries=cls.registries, count=3, seed=42, fragment_count_per_building=4
        )

    def _build_bundle(self):
        from workflow_engine.worldgen.sidecar import _build_sidecar_runtime_bundle_for_buildings

        return _build_sidecar_runtime_bundle_for_buildings(
            self.building_worlds,
            registries=self.registries,
        )

    def test_returns_sidecar_runtime_bundle(self) -> None:
        from workflow_engine.worldgen.models import SidecarRuntimeBundle

        bundle = self._build_bundle()
        self.assertIsInstance(bundle, SidecarRuntimeBundle)

    def _fragment_records(self, bundle):
        """粒度两相分派（2026-07-08）后：fragment 记录（排除楼级 SCR-BLDG-*）。"""
        return [r for r in bundle.records if not r.runtime_id.startswith("SCR-BLDG-")]

    def _building_records(self, bundle):
        return [r for r in bundle.records if r.runtime_id.startswith("SCR-BLDG-")]

    def test_one_record_per_fragment(self) -> None:
        bundle = self._build_bundle()
        total_fragments = sum(len(bw.fragments) for bw in self.building_worlds)
        self.assertEqual(len(self._fragment_records(bundle)), total_fragments)
        # 粒度两相分派：每栋一条楼级记录（行政槽主行 + 聚合行）。
        self.assertEqual(len(self._building_records(bundle)), len(self.building_worlds))

    def test_no_sidecar_missing_marker(self) -> None:
        """spec 09 §1.2 修订：废止 marker.sidecar_missing；runtime_markers 应为空."""
        bundle = self._build_bundle()
        for record in bundle.records:
            marker_slots = [m.slot_id for m in record.runtime_markers]
            self.assertNotIn("marker.sidecar_missing", marker_slots)
            self.assertEqual(record.runtime_markers, [])

    def test_each_fragment_has_sampled_facts(self) -> None:
        """spec 09 §1.2：sidecar_measurement_registry 9 slot 应每 fragment 都派生."""
        bundle = self._build_bundle()
        for record in bundle.records:
            total_facts = (
                len(record.facts)
                + len(record.procedure_gate_state)
                + len(record.supervision_runtime_state)
                + len(record.artifact_requirement_state)
                + len(record.completion_runtime_state)
            )
            self.assertGreater(total_facts, 0, f"fragment {record.runtime_id} 无任何 sidecar fact")

    def test_inspection_execution_routes_to_supervision_bucket(self) -> None:
        """spec 09 §7.1：inspection_execution carrier_domain → supervision_runtime_state."""
        bundle = self._build_bundle()
        # Inspection_execution 5 个 slot id
        inspection_slot_ids = {
            "ratio.external_wall_area.inspected",
            "ratio.covered_structure_area.inspected",
            "count.canopy.check_locations.minimum",
            "length.canopy.check_location.interval",
            "count.private_premises_access.floor_interval",
        }
        for record in self._fragment_records(bundle):
            sup_slot_ids = {v.slot_id for v in record.supervision_runtime_state}
            # 每条 record 的 supervision 桶应至少包含一个 inspection_execution slot
            # （sidecar_measurement_registry 9 slot 全部走采样）
            common = sup_slot_ids & inspection_slot_ids
            self.assertGreater(len(common), 0,
                               f"fragment {record.runtime_id} supervision 桶未含 inspection 类 slot")

    def test_procedure_routes_to_procedure_gate_state(self) -> None:
        """sidecar_measurement_registry procedure carrier 3 slot → procedure_gate_state."""
        bundle = self._build_bundle()
        procedure_slot_ids = {
            "duration.notification.deadline",
            "duration.submission.deadline",
            "duration.delivery.deadline",
        }
        for record in self._fragment_records(bundle):
            proc_slot_ids = {v.slot_id for v in record.procedure_gate_state}
            common = proc_slot_ids & procedure_slot_ids
            self.assertGreater(len(common), 0,
                               f"fragment {record.runtime_id} procedure 桶为空")

    def test_supervision_carrier_in_supervision_bucket(self) -> None:
        bundle = self._build_bundle()
        supervision_carrier_slot = "duration.site_visit.interval"
        for record in self._fragment_records(bundle):
            sup_slot_ids = {v.slot_id for v in record.supervision_runtime_state}
            self.assertIn(supervision_carrier_slot, sup_slot_ids)

    def test_sample_value_within_bounds(self) -> None:
        """采样值应落在 sidecar_measurement_registry.physical_bounds 内."""
        from workflow_engine.worldgen.sidecar import _collect_sidecar_measurement_slots

        bundle = self._build_bundle()
        slot_records = _collect_sidecar_measurement_slots(self.registries)
        bounds_by_slot = {r["slot_id"]: r.get("physical_bounds") for r in slot_records}

        for record in bundle.records:
            all_values = (
                record.facts
                + record.procedure_gate_state
                + record.supervision_runtime_state
                + record.artifact_requirement_state
                + record.completion_runtime_state
            )
            for value in all_values:
                bounds = bounds_by_slot.get(value.slot_id)
                if not bounds or len(bounds) < 2 or not isinstance(value.value, (int, float)):
                    continue
                lo, hi = float(bounds[0]), float(bounds[1])
                self.assertGreaterEqual(float(value.value), lo,
                                        f"slot {value.slot_id} 采样值 {value.value} < lo={lo}")
                self.assertLessEqual(float(value.value), hi,
                                     f"slot {value.slot_id} 采样值 {value.value} > hi={hi}")

    def test_deterministic_with_same_rng_seed(self) -> None:
        """相同 rng seed 应产出相同采样结果."""
        from workflow_engine.worldgen.sidecar import _build_sidecar_runtime_bundle_for_buildings

        bundle1 = _build_sidecar_runtime_bundle_for_buildings(
            self.building_worlds, registries=self.registries,
        )
        bundle2 = _build_sidecar_runtime_bundle_for_buildings(
            self.building_worlds, registries=self.registries,
        )
        for r1, r2 in zip(bundle1.records, bundle2.records):
            v1_by_slot = {v.slot_id: v.value for v in r1.supervision_runtime_state}
            v2_by_slot = {v.slot_id: v.value for v in r2.supervision_runtime_state}
            self.assertEqual(v1_by_slot, v2_by_slot)

    def test_projection_ids_routed_to_records(self) -> None:
        from workflow_engine.worldgen.sidecar import _build_sidecar_runtime_bundle_for_buildings

        first_fragment_id = self.building_worlds[0].fragments[0].fragment_id
        projection_ids = {first_fragment_id: "PROJ-TEST-0001"}
        bundle = _build_sidecar_runtime_bundle_for_buildings(
            self.building_worlds,
            registries=self.registries,
            projection_ids_by_fragment=projection_ids,
        )
        target_record = next(r for r in bundle.records if r.projection_id == "PROJ-TEST-0001")
        self.assertEqual(target_record.world_id, self.building_worlds[0].world_id)

    def test_runtime_ids_unique_across_buildings(self) -> None:
        bundle = self._build_bundle()
        runtime_ids = [r.runtime_id for r in bundle.records]
        self.assertEqual(len(runtime_ids), len(set(runtime_ids)))

    def test_no_registries_returns_empty_buckets(self) -> None:
        """registries=None 时所有桶为空（仅供测试便利）."""
        from workflow_engine.worldgen.sidecar import _build_sidecar_runtime_bundle_for_buildings

        bundle = _build_sidecar_runtime_bundle_for_buildings(
            self.building_worlds, registries=None,
        )
        for record in bundle.records:
            self.assertEqual(record.facts, [])
            self.assertEqual(record.procedure_gate_state, [])
            self.assertEqual(record.supervision_runtime_state, [])

    # ---------- spec 09 §1.2 双路径：bool / categorical sampler tests ----------

    def test_bool_slot_appears_in_procedure_bucket(self) -> None:
        """sidecar_bool_slot_registry 的 procedure bool slot → procedure_gate_state."""
        bundle = self._build_bundle()
        # 已示例：procedure.ri.appointment.completed=0.85
        # 粒度两相分派（2026-07-08）：行政槽楼级一栋一抽，主行在楼级记录。
        for record in self._building_records(bundle):
            slot_ids = {v.slot_id for v in record.procedure_gate_state}
            self.assertIn("procedure.ri.appointment.completed", slot_ids)
        for record in self._fragment_records(bundle):
            slot_ids = {v.slot_id for v in record.procedure_gate_state}
            self.assertNotIn("procedure.ri.appointment.completed", slot_ids)

    def test_bool_slot_value_is_python_bool(self) -> None:
        """bool slot 采样值必须是 Python bool（True/False），不能是 float."""
        bundle = self._build_bundle()
        bool_slot_id = "procedure.ri.appointment.completed"
        for record in bundle.records:
            for v in record.procedure_gate_state:
                if v.slot_id == bool_slot_id:
                    self.assertIsInstance(v.value, bool)

    def test_artifact_bool_slot_appears_in_artifact_bucket(self) -> None:
        """sidecar_bool_slot_registry 的 artifact bool slot → artifact_requirement_state."""
        bundle = self._build_bundle()
        # 已示例：artifact.form.mbi1=0.95
        for record in self._fragment_records(bundle):
            slot_ids = {v.slot_id for v in record.artifact_requirement_state}
            self.assertIn("artifact.form.mbi1", slot_ids)

    def test_qualifier_categorical_slot_appears_in_facts(self) -> None:
        """qualifier carrier_domain=qualifier → facts 桶；enum 采样值在 enum_values 内."""
        bundle = self._build_bundle()
        # 已示例：qual.actor_role enum=[ri, rc, ba, owner]
        valid_actors = {
            "registered_inspector", "registered_contractor",
            "building_authority", "owner",
        }
        for record in self._fragment_records(bundle):
            for v in record.facts:
                if v.slot_id == "qual.actor_role":
                    self.assertIn(v.value, valid_actors)
                    break
            else:
                self.fail(f"fragment {record.runtime_id} 未含 qual.actor_role")

    def test_supervision_bool_slot_appears_in_supervision_bucket(self) -> None:
        bundle = self._build_bundle()
        for record in self._fragment_records(bundle):
            slot_ids = {v.slot_id for v in record.supervision_runtime_state}
            self.assertIn("supervision.site_visit.performed", slot_ids)

    def test_bool_marginal_prevalence_approximates_target(self) -> None:
        """跨较多 fragment 聚合 bool slot prevalence 应粗略接近目标 marginal P.

        Test 用 3 building × 4 fragment = 12 sample 较小，delta 放宽到 0.30；
        长跑 release_batch QA 才能精确验证 prevalence (~8000 samples).
        """
        from workflow_engine.worldgen.generator import generate_world_batch
        from workflow_engine.worldgen.sidecar import _build_sidecar_runtime_bundle_for_buildings

        # 加大 sample size 到 ~80 fragment
        big_worlds = generate_world_batch(
            batch_config={}, registries=self.registries, count=20, seed=42, fragment_count_per_building=4
        )
        bundle = _build_sidecar_runtime_bundle_for_buildings(
            big_worlds, registries=self.registries,
        )
        n_total = 0
        n_true = 0
        target_slot = "artifact.form.mbi1"
        target_p = 0.95
        for record in bundle.records:
            for v in record.artifact_requirement_state:
                if v.slot_id == target_slot:
                    n_total += 1
                    if v.value:
                        n_true += 1
        self.assertGreater(n_total, 50)
        actual_p = n_true / n_total
        self.assertAlmostEqual(actual_p, target_p, delta=0.15,
                               msg=f"empirical p={actual_p:.3f} target={target_p}")

    def test_index_state_by_fragment_does_not_collapse(self) -> None:
        """LD-1 回归：_index_state_by_fragment 必须正确重建 drainage / fire / ubw
        的 fragment→state 索引，不得因 fragment_scope 缺失静默坍缩为空 dict.

        旧 bug：W0-005 删 FragmentContext.fragment_scope 后，索引按已删字段过滤
        → matching 永远空 → drainage/fire/ubw 三域索引全空、sidecar 评估上下文丢失.
        """
        from workflow_engine.worldgen.generator import generate_world_batch
        from workflow_engine.worldgen.sidecar import _index_state_by_fragment

        worlds = generate_world_batch(
            batch_config={}, registries=self.registries, count=40, seed=99,
            fragment_count_per_building=6,
        )
        total_states = 0
        total_indexed = 0
        for w in worlds:
            mech_by_frag = {m.fragment_id: m for m in w.mechanisms}
            frags = list(w.fragments)
            for states, fam in (
                (w.drainage_states, "drainage_fault"),
                (w.fire_safety_states, "fire_safety_deficiency"),
                (w.ubw_states, "ubw_signal"),
            ):
                # DEBT-049 B2：fire 态改按组件生成，锚 component_id（非机制对齐）。
                if fam == "fire_safety_deficiency":
                    idx = _index_state_by_fragment(
                        states, frags, anchor_by_component_id=True)
                else:
                    idx = _index_state_by_fragment(
                        states, frags,
                        mechanisms_by_fragment=mech_by_frag,
                        trigger_mechanism_family=fam,
                    )
                # 索引 size 必须等于 state list size——不丢 state、不过映射.
                self.assertEqual(
                    len(idx), len(states),
                    msg=f"family={fam}: index size {len(idx)} != states {len(states)}",
                )
                # 每条索引：fragment.component_id 必须等于 state.component_id
                # （spec 04 §12/13/14 state 锚 component_id）.
                for fid, state in idx.items():
                    frag = next(f for f in frags if f.fragment_id == fid)
                    self.assertEqual(
                        frag.component_id, state.component_id,
                        msg=f"family={fam}: fragment {fid} component_id mismatch",
                    )
                total_states += len(states)
                total_indexed += len(idx)
        # sanity：40 世界 × 6 fragment 必然产出 >0 个三域 state.
        self.assertGreater(total_states, 0)
        self.assertEqual(total_states, total_indexed)


if __name__ == "__main__":
    unittest.main()
