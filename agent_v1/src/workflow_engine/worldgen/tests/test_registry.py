"""Unit tests for worldgen.registry module.

Guards registry record counts, profile specs, bundle structure, and sidecar contract.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen.registry import (
    PROJECTION_REGISTRY_INDEX,
    _build_registry_bundle,
    _build_sidecar_contract,
    _projection_registry_records,
)


class RegistryRecordTests(unittest.TestCase):
    """Guard projection registry record counts and structure."""

    def test_projection_registry_records_count(self) -> None:
        # W2-005 批次 C 2026-05-21：spec 06 §2.1 16 family baseline 落地——
        # 拆 NP_UBW_FIRE_V1 合并 record 为 fire_safety + ubw 独立 records，
        # 补 structural_assessment_fsp + repair.general_selection_and_classification.
        records = _projection_registry_records()
        self.assertEqual(len(records), 16)

    def test_projection_registry_records_have_required_fields(self) -> None:
        records = _projection_registry_records()
        for record in records:
            with self.subTest(record=record.get("projection_registry_id", "?")):
                self.assertIn("projection_registry_id", record)
                self.assertIn("projection_family", record)
                self.assertIn("required_sidecar_interfaces", record)
                self.assertIn("domain_buckets", record)

    def test_projection_registry_index_keys(self) -> None:
        self.assertIsInstance(PROJECTION_REGISTRY_INDEX, dict)
        self.assertGreater(len(PROJECTION_REGISTRY_INDEX), 0)
        for key, val in PROJECTION_REGISTRY_INDEX.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(val, dict)

    def test_projection_registry_index_count(self) -> None:
        # W2-005 批次 C 2026-05-21：spec 06 §2.1 16 family baseline.
        self.assertEqual(len(PROJECTION_REGISTRY_INDEX), 16)

    def test_projection_registry_ids_consistent(self) -> None:
        records = _projection_registry_records()
        record_ids = {r["projection_registry_id"] for r in records}
        index_ids = set(PROJECTION_REGISTRY_INDEX.keys())
        self.assertEqual(record_ids, index_ids)


# WorldProfileSpecsTests removed (T-17h: WORLD_PROFILE_SPECS is OLD-only legacy)


class RegistryBundleTests(unittest.TestCase):
    """Guard _build_registry_bundle() output structure."""

    def setUp(self) -> None:
        self.bundle = _build_registry_bundle()

    def test_bundle_has_19_registries(self) -> None:
        # spec 02 §1: 6 大资源域 + Sidecar 边界契约 4 张 = 19 张 registry.
        # 2026-05-09 修订：增设 sidecar_bool_slot_registry (spec 09 §1.2 双路径).
        self.assertEqual(len(self.bundle.registries), 19)

    def test_bundle_version_string(self) -> None:
        self.assertIsInstance(self.bundle.version, str)
        self.assertTrue(len(self.bundle.version) > 0)

    def test_bundle_source_documents(self) -> None:
        self.assertIsInstance(self.bundle.source_documents, list)
        self.assertGreater(len(self.bundle.source_documents), 0)

    def test_bundle_registry_ids_unique(self) -> None:
        ids = [r.registry_id for r in self.bundle.registries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_bundle_registries_have_records(self) -> None:
        for reg in self.bundle.registries:
            with self.subTest(registry_id=reg.registry_id):
                self.assertIsInstance(reg.records, list)

    def test_sidecar_measurement_registry_present(self) -> None:
        registry = next(
            (reg for reg in self.bundle.registries if reg.registry_id == "sidecar_measurement_registry"),
            None,
        )
        self.assertIsNotNone(registry)
        if registry is None:
            return
        self.assertEqual(registry.ownership, "sidecar_boundary.measurement")
        self.assertEqual(registry.key_field, "slot_id")
        self.assertEqual(
            registry.fields,
            [
                "slot_id",
                "measurement_family",
                "value_type",
                "unit",
                "physical_bounds",
                "precision_steps",
                "carrier_domain",
                "carrier_slot",
                "rule_basis_refs",
                "aliases",
                # DEBT-026 (spec 04 §17 / spec 03 §4.2) typical 分布参数
                "recommended_distribution",
                "recommended_mean",
                "recommended_sigma",
                "typical_bounds",
                "distribution_source",
            ],
        )
        # DEBT-020 round5 sub-task 5 (2026-05-10): duration.delivery.deadline 拆分为 to_person + to_ba
        # 旧 slot 标 deprecated 但保留一个 release cycle backward-compatible alias.
        # 总条数 9 → 11（+2 split slots，旧 slot 仍在）.
        # 期限锚供给案 (2026-08-05)：+8 楼级 duration 槽 ⇒ 11 → 19.
        self.assertEqual(len(registry.records), 19)
        self.assertEqual(
            {record["slot_id"] for record in registry.records},
            {
                "duration.notification.deadline",
                "duration.submission.deadline",
                "duration.delivery.deadline",  # deprecated alias
                # DEBT-020 round5 sub-task 5 — split into 2 new sidecar slots
                "duration.delivery.deadline.to_person",
                "duration.delivery.deadline.to_ba",
                "duration.site_visit.interval",
                # DEBT-025 closure (2026-05-06)：5 个 inspection-execution slot
                "ratio.external_wall_area.inspected",
                "ratio.covered_structure_area.inspected",
                "count.canopy.check_locations.minimum",
                "length.canopy.check_location.interval",
                "count.private_premises_access.floor_interval",
                # 期限锚供给案 (2026-08-05)：甲类 7 个新槽 + 乙 #11 第 8 个，
                # 全部 granularity=building、走独立追加的楼级发射步骤（形态 C）。
                # 逐条中文守则依据与「不在这里的锚点」清单见 registry.py 的块注释。
                "duration.notification.appointment_ri.to_ba",
                "duration.notification.nomination_temp_ri.to_ba",
                "duration.notification.nomination_temp_ri_terminated.to_ba",
                "duration.notification.role_ri_terminated.to_ba",
                "duration.submission.repair_revision.to_ba",
                "duration.notification.appointment_supervising_ri.to_ba",
                "duration.notification.supervision_team_changed.to_ba",
                "duration.delivery.repair_revision_proposal",
            },
        )


    def test_material_system_registry_present(self) -> None:
        registry = next(r for r in self.bundle.registries if r.registry_id == "material_system_registry")
        self.assertEqual(registry.key_field, "material_system")
        self.assertEqual(len(registry.records), 50)
        material_systems = {r["material_system"] for r in registry.records}
        self.assertIn("reinforced_concrete", material_systems)
        self.assertIn("steel_fire_doors", material_systems)
        self.assertIn("upvc_drainage", material_systems)
        self.assertIn("unknown_material", material_systems)

    def test_defect_condition_taxonomy_t06_extension(self) -> None:
        registry = next(r for r in self.bundle.registries if r.registry_id == "defect_condition_taxonomy_registry")
        condition_classes = {r["condition_class"] for r in registry.records}
        for new_dc in ["DC_METAL_CORROSION", "DC_SEALANT_FAILURE", "DC_GLASS_BREAKAGE",
                       "DC_DEFORMATION_DISPLACEMENT", "DC_FIRE_PROTECTION_COATING_DEFICIENCY",
                       # DEBT-049 A1/A2 新增独立结构缺陷类
                       "DC_REBAR_EXPOSED", "DC_HONEYCOMBING_VOID", "DC_ABNORMAL_SEPARATION"]:
            self.assertIn(new_dc, condition_classes)
        self.assertEqual(len(registry.records), 22)  # DEBT-049 A1/A2 +3


class ChainDeriveSlotRegistryTests(unittest.TestCase):
    """DEBT-020 round5 sub-task 2 (2026-05-10) chain_C_plus 链式派生 slot registry 验证.

    覆盖：
    - 4 个 chain input slot 进入 technical_measurement_registry：
        facade_total_repaired_area_m2 / plan_intensity_tests_per_25m2 /
        total_pull_test_count_per_facade / inspected_area_ratio_per_fragment
    - 2 个 chain derived A 类 slot（无 distribution，标 None）：
        effective_pull_test_count_per_fragment / inspected_area_m2
    - rate.pull_test.per_25m2 + ratio.covered_area.inspected 升 A 类（chain derive 路径）
    - sampling_plan_registry 复活含 2 plan record：
        pull_test_sampling_plan / coverage_inspection_plan
    """

    def setUp(self) -> None:
        self.bundle = _build_registry_bundle()
        self.tech_registry = next(
            r for r in self.bundle.registries if r.registry_id == "technical_measurement_registry"
        )
        self.tech_records_by_id = {r["slot_id"]: r for r in self.tech_registry.records}
        self.sampling_plan_registry = next(
            r for r in self.bundle.registries if r.registry_id == "sampling_plan_registry"
        )
        self.plan_records_by_id = {
            r["sampling_plan_id"]: r for r in self.sampling_plan_registry.records
        }

    def test_4_chain_input_slots_present_in_technical_registry(self) -> None:
        """4 个 chain input slot 进入 technical_measurement_registry."""
        chain_input_slots = [
            "facade_total_repaired_area_m2",
            "plan_intensity_tests_per_25m2",
            "total_pull_test_count_per_facade",
            "inspected_area_ratio_per_fragment",
        ]
        for slot_id in chain_input_slots:
            with self.subTest(slot_id=slot_id):
                self.assertIn(slot_id, self.tech_records_by_id, f"chain input {slot_id} missing from technical_measurement_registry")
                rec = self.tech_records_by_id[slot_id]
                # 必须含 typical 分布参数（B 类 chain input）
                self.assertIsNotNone(rec.get("recommended_distribution"))
                self.assertIsNotNone(rec.get("recommended_mean"))

    def test_facade_total_repaired_area_m2_distribution_aligned_with_pro_design(self) -> None:
        """facade_total_repaired_area_m2 ~ lognormal(arithmetic_mean=120, sigma_log=0.75) clip [20,500]."""
        rec = self.tech_records_by_id["facade_total_repaired_area_m2"]
        self.assertEqual(rec["recommended_distribution"], "lognormal")
        self.assertEqual(rec["recommended_mean"], 120.0)
        self.assertEqual(rec["recommended_sigma"], 0.75)
        self.assertEqual(rec["physical_bounds"], [20.0, 500.0])

    def test_plan_intensity_distribution_aligned_with_pro_design(self) -> None:
        """plan_intensity_tests_per_25m2 ~ lognormal(arithmetic_mean=1.9, sigma_log=0.35) clip [0.50, 3.00]（S2.5 标定档，DEBT-045 修法①）."""
        rec = self.tech_records_by_id["plan_intensity_tests_per_25m2"]
        self.assertEqual(rec["recommended_distribution"], "lognormal")
        self.assertEqual(rec["recommended_mean"], 1.9)
        self.assertEqual(rec["recommended_sigma"], 0.35)
        self.assertEqual(rec["physical_bounds"], [0.50, 3.00])

    def test_inspected_area_ratio_distribution_aligned_with_pro_design(self) -> None:
        """inspected_area_ratio_per_fragment ~ truncated_normal(0.45, 0.18) clip [0.10, 0.85]."""
        rec = self.tech_records_by_id["inspected_area_ratio_per_fragment"]
        self.assertEqual(rec["recommended_distribution"], "truncated_normal")
        self.assertEqual(rec["recommended_mean"], 0.45)
        self.assertEqual(rec["recommended_sigma"], 0.18)
        self.assertEqual(rec["typical_bounds"], [0.10, 0.85])

    def test_2_chain_derived_a_class_slots_no_distribution(self) -> None:
        """2 个 chain derived A 类 slot：recommended_distribution 必须为 None.

        A 类 = spec 06 公式 derive；B 类 = typical 分布采样。详见 spec 04 §17 / spec 06 §11.5.
        """
        derived_a_slots = ["effective_pull_test_count_per_fragment", "inspected_area_m2"]
        for slot_id in derived_a_slots:
            with self.subTest(slot_id=slot_id):
                self.assertIn(slot_id, self.tech_records_by_id, f"chain derived A 类 {slot_id} missing")
                rec = self.tech_records_by_id[slot_id]
                self.assertIsNone(
                    rec.get("recommended_distribution"),
                    f"{slot_id} 是 A 类 chain derived，不应有 distribution",
                )

    def test_rate_pull_test_per_25m2_present_for_chain_routing(self) -> None:
        """rate.pull_test.per_25m2 仍在 registry（升 A 后由 chain derive 路径填值）.

        注意：本 round 不删 round2 distribution 字段（作为 fallback path 兼容；
        chain derive 路径优先，distribution Path B 仅在 chain 数据缺失时 fallback）.
        """
        self.assertIn("rate.pull_test.per_25m2", self.tech_records_by_id)

    def test_ratio_covered_area_inspected_present_in_technical_registry(self) -> None:
        """ratio.covered_area.inspected 进入 technical_measurement_registry（chain derived A 类）.

        spec 04 §17 line 261 已列此 a4 canonical slot；DEBT-020 round5 sub-task 2 同步补建.
        """
        self.assertIn("ratio.covered_area.inspected", self.tech_records_by_id)
        rec = self.tech_records_by_id["ratio.covered_area.inspected"]
        # A 类 chain derived → 无 distribution
        self.assertIsNone(rec.get("recommended_distribution"))
        self.assertEqual(rec["physical_bounds"], [0.0, 1.0])

    def test_sampling_plan_registry_revived_with_chain_plan_records(self) -> None:
        """sampling_plan_registry 复活后含 chain plan record.

        历史：
          - DEBT-025 closure 2026-05-07 清空原 6 plan；
          - DEBT-020 round5 sub-task 2 复活 2026-05-10 (2 plan): pull_test + coverage_inspection;
          - DEBT-020 round5 sub-task 4 落地 2026-05-10 (+1 plan): floor_retiling_package.
        """
        self.assertEqual(len(self.sampling_plan_registry.records), 3)
        self.assertIn("pull_test_sampling_plan", self.plan_records_by_id)
        self.assertIn("coverage_inspection_plan", self.plan_records_by_id)
        # DEBT-020 round5 sub-task 4: floor-level retiling chain
        self.assertIn("floor_retiling_package", self.plan_records_by_id)

    def test_pull_test_sampling_plan_chain_c_plus_schema(self) -> None:
        """pull_test_sampling_plan 含 plan_level + plan_intensity_distribution + chain formulas."""
        plan = self.plan_records_by_id["pull_test_sampling_plan"]
        self.assertEqual(plan["plan_level"], "facade_or_floor_repair_package")
        self.assertEqual(plan["basis_area_slot"], "facade_total_repaired_area_m2")
        self.assertEqual(plan["coverage_ratio_slot"], "rate.pull_test.per_25m2")
        # chain target slots（4 个；spec 06 §9 chain Step 1-5）
        self.assertEqual(
            set(plan["target_slot_ids"]),
            {
                "facade_total_repaired_area_m2",
                "total_pull_test_count_per_facade",
                "effective_pull_test_count_per_fragment",
                "rate.pull_test.per_25m2",
            },
        )
        # plan_intensity_distribution dict
        intensity = plan["plan_intensity_distribution"]
        self.assertEqual(intensity["recommended_distribution"], "lognormal")
        self.assertEqual(intensity["recommended_mean"], 1.9)
        self.assertEqual(intensity["recommended_sigma"], 0.35)
        self.assertEqual(intensity["typical_bounds"], [0.50, 3.00])
        # chain formulas 必须含
        self.assertIn("plan_intensity", plan["total_count_formula"])
        self.assertIn("effective_pull_test_count_per_fragment", plan["fragment_allocation_formula"])

    def test_coverage_inspection_plan_chain_schema(self) -> None:
        """coverage_inspection_plan: per-fragment truncated_normal sampling chain."""
        plan = self.plan_records_by_id["coverage_inspection_plan"]
        self.assertEqual(plan["plan_level"], "fragment")
        self.assertEqual(plan["basis_area_slot"], "fragment_area_m2")
        self.assertEqual(plan["coverage_ratio_slot"], "ratio.covered_area.inspected")
        self.assertEqual(
            set(plan["target_slot_ids"]),
            {
                "inspected_area_ratio_per_fragment",
                "inspected_area_m2",
                "ratio.covered_area.inspected",
            },
        )
        # truncated_normal 分布
        intensity = plan["plan_intensity_distribution"]
        self.assertEqual(intensity["recommended_distribution"], "truncated_normal")
        self.assertEqual(intensity["recommended_mean"], 0.45)
        self.assertEqual(intensity["recommended_sigma"], 0.18)
        self.assertEqual(intensity["typical_bounds"], [0.10, 0.85])

    def test_sampling_plan_registry_fields_extended_with_chain_keys(self) -> None:
        """sampling_plan_registry.fields 已扩展含 chain_C_plus 字段."""
        chain_required_fields = {
            "plan_level",
            "plan_intensity_distribution",
            "total_count_formula",
            "fragment_allocation_formula",
        }
        registry_fields = set(self.sampling_plan_registry.fields)
        self.assertTrue(
            chain_required_fields.issubset(registry_fields),
            f"sampling_plan_registry.fields 缺少 chain 字段: {chain_required_fields - registry_fields}",
        )
        # 兼容 a12 旧字段也应保留
        self.assertIn("min_count_formula", registry_fields)
        self.assertIn("interval_formula", registry_fields)


class SidecarContractTests(unittest.TestCase):
    """Guard _build_sidecar_contract() output structure."""

    def setUp(self) -> None:
        self.contract = _build_sidecar_contract()

    def test_contract_is_sidecar_contract_model(self) -> None:
        from workflow_engine.worldgen.models import SidecarContract
        self.assertIsInstance(self.contract, SidecarContract)

    def test_contract_has_ownership_map(self) -> None:
        # ownership_map maps slot_id to SlotOwnershipEntry
        self.assertIsInstance(self.contract.ownership_map, list)
        self.assertGreater(len(self.contract.ownership_map), 0)

    def test_contract_ownership_entries_have_slot_ids(self) -> None:
        for entry in self.contract.ownership_map:
            with self.subTest(slot_id=entry.slot_id):
                self.assertIsInstance(entry.slot_id, str)
                self.assertIsInstance(entry.partition, str)

    def test_contract_ownership_slot_ids_unique(self) -> None:
        slot_ids = [e.slot_id for e in self.contract.ownership_map]
        self.assertEqual(len(slot_ids), len(set(slot_ids)))

    def test_contract_has_interface_schema(self) -> None:
        # interface_schema is a list of SidecarInterfaceSchema objects
        self.assertIsInstance(self.contract.interface_schema, list)
        self.assertGreater(len(self.contract.interface_schema), 0)

    def test_contract_interface_schema_has_fields(self) -> None:
        for schema in self.contract.interface_schema:
            with self.subTest(interface_id=schema.interface_id):
                self.assertIsInstance(schema.input_fields, list)
                self.assertIsInstance(schema.output_fields, list)


class DeliverySplitTests(unittest.TestCase):
    """DEBT-020 round5 sub-task 5 (2026-05-10) DeliveryDeadlineSemantic split 单元测试.

    覆盖：
    - 2 个新 sidecar slot 注册成功（duration.delivery.deadline.to_person + to_ba）
    - 老 slot duration.delivery.deadline 仍可查（backward-compatible alias）
    - deprecated marker 存在（deprecated_at + replacement_slots + deprecation_reason）
    - rule_card_threshold 字段标 PENDING_RULECARD_TEAM_COP_VERIFICATION（不动 rule_card 数字）
    - new slots 有 distribution（pro 设计 + DEBT-021 pending source）
    """

    def setUp(self) -> None:
        self.bundle = _build_registry_bundle()
        self.sidecar_registry = next(
            r for r in self.bundle.registries if r.registry_id == "sidecar_measurement_registry"
        )
        self.records_by_id = {r["slot_id"]: r for r in self.sidecar_registry.records}

    def test_new_to_person_slot_registered(self) -> None:
        self.assertIn("duration.delivery.deadline.to_person", self.records_by_id)

    def test_new_to_ba_slot_registered(self) -> None:
        self.assertIn("duration.delivery.deadline.to_ba", self.records_by_id)

    def test_old_slot_still_present(self) -> None:
        """duration.delivery.deadline 保留为 backward-compatible alias 一个 release cycle."""
        self.assertIn("duration.delivery.deadline", self.records_by_id)

    def test_old_slot_marked_deprecated(self) -> None:
        """老 slot 必须标 deprecated_at + replacement_slots + deprecation_reason."""
        old = self.records_by_id["duration.delivery.deadline"]
        self.assertIn("deprecated_at", old)
        self.assertEqual(old["deprecated_at"], "2026-05-10")
        self.assertIn("replacement_slots", old)
        self.assertEqual(
            set(old["replacement_slots"]),
            {"duration.delivery.deadline.to_person", "duration.delivery.deadline.to_ba"},
        )
        self.assertIn("deprecation_reason", old)
        # 必须解释 mixed semantics
        self.assertIn("Mixed", old["deprecation_reason"])

    def test_to_person_slot_has_cop_confirmed_threshold(self) -> None:
        """DEBT-020 Round 7 §2 (2026-05-11): rule_card_threshold 由 PENDING 升级为 COP-confirmed:
        same_day_as / ==0 calendar day relative to BA submission date (NOT repair completion).

        🔴 2026-08-05 R5 对齐（期限锚供给案决议 §四.2）：本条原来锁的两个值都是错的一方——
        - `unit` 原锁 `"calendar_day"`，卡侧写 `"day"`；
        - `time_anchor_key` 原锁 `repair.completion_report_and_mbi4.submitted_to_ba`，
          该字符串**不在** `time_anchor_registry_v1.json` 的 19 条锚点册里，是世界侧孤儿；
          卡侧对应的真锚点是 `repair.completion_report.submitted_to_ba`。
        两处在 provenance 绑定通道接上之前都不承载任何东西，接上之后失配是**静默**的
        （绑不上只落 missing_time_anchor，看起来像「世界没供」），故与接线同批改。
        再犯由 `worldgen/tests/test_deadline_anchor_emission.py` 的静态闸挡。
        """
        slot = self.records_by_id["duration.delivery.deadline.to_person"]
        threshold = slot.get("rule_card_threshold")
        self.assertIsInstance(threshold, dict, "Round 7: rule_card_threshold should be dict")
        self.assertEqual(threshold.get("relation"), "same_day_as")
        self.assertEqual(threshold.get("operator"), "==")
        self.assertEqual(threshold.get("value"), 0)
        self.assertEqual(threshold.get("unit"), "day")
        self.assertEqual(
            threshold.get("time_anchor_key"),
            "repair.completion_report.submitted_to_ba",
        )
        # 🔴 2026-08-03 按裁定更新：原断言锁的是合并词
        # `owner_or_person_for_whom_prescribed_repair_is_carried_out`——那是**拆之前
        # 的旧断言**。§2.1.3(r) 只点名「該名由他人代為進行訂明修葺的人」一方，
        # `owner_or_` 前缀无依据（裁定：`规格_reporting三根轴世界侧补产_v1_20260803.md` §3.6）。
        self.assertEqual(
            threshold.get("recipient_qualifier", {}).get("actor_role_key"),
            "person_for_whom_prescribed_repair_is_carried_out",
        )
        self.assertEqual(slot.get("cop_section"), "MBIS_CoP_2023 §2.1.3(r)")

    def test_to_ba_slot_has_cop_confirmed_threshold(self) -> None:
        """DEBT-020 Round 7 §2: to_ba threshold 由 PENDING 升级为 COP-confirmed:
        <= 14 day after repair.prescribed.completed."""
        slot = self.records_by_id["duration.delivery.deadline.to_ba"]
        threshold = slot.get("rule_card_threshold")
        self.assertIsInstance(threshold, dict, "Round 7: rule_card_threshold should be dict")
        self.assertEqual(threshold.get("measure_key"), "duration.submission.deadline")
        self.assertEqual(threshold.get("operator"), "<=")
        self.assertEqual(threshold.get("value"), 14)
        self.assertEqual(threshold.get("unit"), "day")
        self.assertEqual(threshold.get("time_anchor_key"), "repair.prescribed.completed")
        self.assertEqual(
            threshold.get("recipient_qualifier", {}).get("actor_role_key"), "ba"
        )
        self.assertEqual(slot.get("cop_section"), "MBIS_CoP_2023 §2.1.3(r)")

    def test_to_person_slot_distribution(self) -> None:
        """to_person ~ zero_inflated_discrete (pro 设计)；day0 weight ~0.75 → mean=0.45 sigma=1.15.
        Round 7 (2026-05-11) 升级 distribution_source."""
        slot = self.records_by_id["duration.delivery.deadline.to_person"]
        self.assertEqual(slot["physical_bounds"], [0, 14])
        self.assertEqual(slot["recommended_mean"], 0.45)
        self.assertEqual(slot["recommended_sigma"], 1.15)
        self.assertEqual(slot["typical_bounds"], [0, 3])
        self.assertEqual(
            slot["distribution_source"],
            "proagent_engineering_estimate_current_authority_round5_2026_05_10",
        )

    def test_to_ba_slot_distribution(self) -> None:
        """to_ba ~ rounded_truncated_normal (pro 设计)；mean=10.5 sigma=5.0 typical=[0,35].
        Round 7 (2026-05-11) 升级 distribution_source."""
        slot = self.records_by_id["duration.delivery.deadline.to_ba"]
        self.assertEqual(slot["physical_bounds"], [0, 60])
        self.assertEqual(slot["recommended_distribution"], "rounded_truncated_normal")
        self.assertEqual(slot["recommended_mean"], 10.5)
        self.assertEqual(slot["recommended_sigma"], 5.0)
        self.assertEqual(slot["typical_bounds"], [0, 35])
        self.assertEqual(
            slot["distribution_source"],
            "proagent_engineering_estimate_current_authority_round5_2026_05_10",
        )

    def test_old_slot_distribution_source_marked_deprecated(self) -> None:
        """老 slot distribution_source 应标 deprecated_replaced_by_to_person_and_to_ba."""
        old = self.records_by_id["duration.delivery.deadline"]
        self.assertIn("deprecated", old.get("distribution_source", "").lower())

    def test_to_person_carrier_slot_in_ownership_map(self) -> None:
        """to_person 的 carrier_slot artifact.report_completion_or_mbi4.submitted_to_ba
        必须先在 sidecar_ownership_registry 注册（spec 03 §3 cross-registry consistency）.
        """
        slot = self.records_by_id["duration.delivery.deadline.to_person"]
        carrier_slot = slot["carrier_slot"]
        self.assertEqual(carrier_slot, "artifact.report_completion_or_mbi4.submitted_to_ba")
        contract = _build_sidecar_contract()
        owned_ids = {entry.slot_id for entry in contract.ownership_map}
        self.assertIn(carrier_slot, owned_ids,
                      f"to_person carrier_slot {carrier_slot} 未在 ownership_map 注册")


if __name__ == "__main__":
    unittest.main()
