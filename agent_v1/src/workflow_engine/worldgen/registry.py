from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from workflow_engine.worldgen.constants import (
    DerivationMode,
    MeasurementBranch,
    PROJECT_ROOT,
    SlotPartition,
    SOURCE_DOCUMENTS,
    _utc_now_iso,
)
from workflow_engine.worldgen.models import (
    MeasurementRecord,
    RegistryBundle,
    RegistryTable,
    SidecarContract,
    SidecarInterfaceField,
    SidecarInterfaceSchema,
    SlotOwnershipEntry,
)
from workflow_engine.worldgen.round6_formulas import (
    ANCHOR_SOURCES_ROUND7,
    DISTRIBUTION_SOURCE as DEBT020_ROUND7_DISTRIBUTION_SOURCE,
    MARGINAL_ANCHORS_ROUND7,
    SAMPLING_ORDER_ROUND7,
    get_round6_round7_formulas,
)


def _projection_registry_records() -> List[Dict[str, Any]]:
    # `normative_projection_registry` 是 W2 法规映射层注册表（W0 规格 02 §1 第 7 分组注 1
    # + W0 规格 11 §4.4 + W2 规格 06 §3）：schema + records 业务依据归属 W2，records
    # 内容按 W2 规格 06 §2 16 family baseline + W0 规格 04 §17-§22 字段合约给出。
    # 本函数物理位置在 worldgen/registry.py 是因为 `_build_registry_bundle()` 加载
    # 所有 RegistryTable 时把 npr 也读进 registry_bundle 给下游消费方（worldgen
    # 跨层加载 W2 注册表 records 是 orchestrator 性质）。
    records = [
        {
            "projection_registry_id": "NP_RI_NOTIFICATIONS_V1",
            "projection_family": "mbis.procedure.ri_notifications_and_submissions",
            "required_world_core_slots": [],
            "required_measurement_slots": [],
            "required_qualifier_slots": [],
            "required_sidecar_interfaces": [
                "procedure_gate_sidecar",
                "inspection_report_sidecar",
                "completion_report_sidecar",
            ],
            "domain_buckets": ["structural_external", "coverage_sampling", "assessment"],
        },
        {
            "projection_registry_id": "NP_EXTERNAL_COMPONENTS_V1",
            "projection_family": "mbis.inspection.external_components",
            "required_world_core_slots": [
                "scope.component.covered",
                "scope.component.obscured_by_finish",
                "defect.class.present",
                "defect.moisture_or_leakage.present",
                "defect.detachment_or_loose_fixing.present",
                "defect.range.extends_into_private_premises",
                "repair.required",
            ],
            "required_measurement_slots": [
                # DEBT-025 closure 2026-05-07：删 phantom slot:
                # area.signboard.display / ratio.covered_area.inspected /
                # count.access_opening.required / area.finish_probe.sampled
                # （4 项无 spec 授权 + 无 MBIS 法规阈值 + generator 不产值）
                "ratio.external_wall_area.inspected",
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.location_class",
                "qual.defect_class",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["structural_external", "coverage_sampling"],
        },
        {
            "projection_registry_id": "NP_STRUCTURAL_COMPONENTS_V1",
            "projection_family": "mbis.inspection.structural_components",
            "required_world_core_slots": [
                "defect.class.present",
                "defect.hollowing.present",
                "defect.range.extends_into_private_premises",
                "risk.building_safety.emergency",
            ],
            "required_measurement_slots": [
                "ratio.covered_structure_area.inspected",
                "count.canopy.check_locations.minimum",
                "length.canopy.check_location.interval",
                "count.hammer_tapping.grid.minimum",
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.location_class",
                "qual.defect_class",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["structural_external", "technical_validation", "assessment"],
        },
        {
            "projection_registry_id": "NP_DRAINAGE_V1",
            "projection_family": "mbis.inspection.drainage",
            "required_world_core_slots": [
                "defect.drainage.misconnection.present",
                "defect.drainage.blockage.present",
                "defect.drainage.leakage.present",
                "risk.public_health.emergency",
                "risk.public_danger.present",
                "verification.test.failed",
            ],
            "required_measurement_slots": [
                # DEBT-025 closure 2026-05-07：删 phantom slot:
                # count.drainage.test_points.minimum / length.drainage.branch.interval
                # （2 项无 spec 授权 + 无 MBIS 法规阈值 + generator 不产值）
                "count.private_premises_access.floor_interval",
            ],
            "required_qualifier_slots": ["qual.location_class", "qual.method_class"],
            "required_sidecar_interfaces": ["procedure_gate_sidecar", "inspection_report_sidecar"],
            "domain_buckets": ["drainage", "coverage_sampling", "technical_validation"],
        },
        {
            "projection_registry_id": "NP_INVESTIGATION_GATE_V1",
            "projection_family": "mbis.investigation.gate_and_proposal",
            "required_world_core_slots": ["defect.cause_or_extent.uncertain"],
            "required_measurement_slots": [],
            "required_qualifier_slots": ["qual.component_type", "qual.method_class"],
            "required_sidecar_interfaces": ["procedure_gate_sidecar", "inspection_report_sidecar"],
            "domain_buckets": ["coverage_sampling", "assessment"],
        },
        # W2-005 (批次 C 2026-05-21)：spec 06 §2.1 row 5 + row 7 拆出 fire_safety / ubw 两条独立 records.
        # 原 NP_UBW_FIRE_V1（projection_family=mbis.inspection.ubw_and_fire_safety）合并 record
        # 是 NI-006 红线违反——spec 16 family baseline 要求 fire_safety / ubw 各自独立 family。
        # 拆分后两 records 仍同填 conflict_group="ubw_fire"（spec 07 §4.2 业务允许同时投影 distinct
        # component 时）.
        {
            "projection_registry_id": "NP_FIRE_SAFETY_V1",
            "projection_family": "mbis.inspection.fire_safety",
            "required_world_core_slots": [
                # spec 06 §2.1 row 5：fire_safety upgrade outstanding / risk.building_safety.emergency.
                # `fire_safety.upgrade_outstanding` 未在 W0 sidecar_contract world_core slot universe
                # 注册（仅有 defect.fire_safety.component_deficiency.present），按 spec 03 §3 line 104
                # registry-time invariant 用已注册 slot 表达"消防安全缺陷存在"的物理底座.
                "defect.fire_safety.component_deficiency.present",
                "defect.class.present",
                "risk.building_safety.emergency",
                "repair.required",
            ],
            "required_measurement_slots": [
                # 消防门自闭延时（fire_door.self_closing.delay_sec）跟随消防 family.
                "time.fire_door.self_closing.delay_sec",
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.defect_class",
                "qual.location_class",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["fire_safety"],
        },
        {
            "projection_registry_id": "NP_UBW_V1",
            "projection_family": "mbis.inspection.ubw",
            "required_world_core_slots": [
                # spec 06 §2.1 row 7：违建相关世界事实 + 紧急 / 公众危险风险.
                "defect.ubw.present",
                "defect.subdivided_unit_sign.present",
                "risk.building_safety.emergency",
                "risk.public_danger.present",
            ],
            "required_measurement_slots": [],
            "required_qualifier_slots": [
                "qual.location_class",
                "qual.defect_class",
            ],
            "required_sidecar_interfaces": [
                "inspection_report_sidecar",
                "procedure_gate_sidecar",
            ],
            "domain_buckets": ["ubw"],
        },
        # W2-005 (批次 C 2026-05-21)：补 spec 06 §2.1 row 9 结构评估 FSP 独立 family.
        {
            "projection_registry_id": "NP_INVESTIGATION_FSP_V1",
            "projection_family": "mbis.investigation.structural_assessment_fsp",
            "required_world_core_slots": [
                "investigation.fsp.below_required_safety",
                "risk.building_safety.emergency",
            ],
            "required_measurement_slots": [
                "ratio.fsp.structural_performance",
                "count.core_sample.minimum",
                "rate.core_sample.per_concrete_volume",
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.method_class",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["assessment", "technical_validation"],
        },
        # W2-005 (批次 C 2026-05-21)：补 spec 06 §2.1 row 10 修葺一般选择与分类独立 family.
        {
            "projection_registry_id": "NP_REPAIR_GENERAL_V1",
            "projection_family": "mbis.repair.general_selection_and_classification",
            "required_world_core_slots": [
                "repair.required",
                "repair.outcome.safe_until_next_cycle",
                "maintenance.pre_next_cycle.required",
            ],
            "required_measurement_slots": [],
            "required_qualifier_slots": [
                "qual.work_category",
                "qual.component_type",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["assessment"],
        },
        {
            "projection_registry_id": "NP_REPAIR_VALIDATION_V1",
            "projection_family": "mbis.repair.external_structural_validation",
            "required_world_core_slots": [
                "repair.required",
                "repair.outcome.safe_until_next_cycle",
                "maintenance.pre_next_cycle.required",
            ],
            "required_measurement_slots": [
                "rate.pull_test.per_25m2",
                "count.pull_test.per_repaired_facade",
                "count.pull_test.per_floor_full_retiling",
                "stress.pull_test.minimum",
                "count.pull_test.failed_cumulative",
                "count.pull_test.additional_after_failure",
                "length.rendering.total_thickness",
                "length.rendering.layer_thickness",
                "depth.patch_repair",
                "length.concrete_repair.depth",
                "duration.repair_mortar.test_age",
                "count.repair_mortar_specimens.per_strength_property",
                "ratio.rebar.section_loss",
                "length.mortar.application_layer_thickness",
                # Round2 retire: generic "ratio.chloride_content" 已退役（rule_card 0 引用，dead slot）.
                # 详见 round2 回复 suggested_followups #2 + DEBT-020 round2 closure 2026-05-09.
                "ratio.chloride_content.by_cement_weight",
            ],
            "required_qualifier_slots": ["qual.method_class", "qual.work_category", "qual.component_type"],
            "required_sidecar_interfaces": ["supervision_sidecar", "completion_report_sidecar"],
            "domain_buckets": ["technical_validation", "assessment"],
        },
        {
            "projection_registry_id": "NP_SUPERVISION_CONTROLS_V1",
            "projection_family": "mbis.supervision.ri_minimum_and_site_controls",
            "required_world_core_slots": ["risk.building_safety.emergency", "repair.required"],
            "required_measurement_slots": [],
            "required_qualifier_slots": ["qual.work_category", "qual.method_class"],
            "required_sidecar_interfaces": ["supervision_sidecar", "procedure_gate_sidecar", "completion_report_sidecar"],
            "domain_buckets": ["technical_validation", "assessment"],
        },
        {
            "projection_registry_id": "NP_REPORTING_INSPECTION_V1",
            "projection_family": "mbis.reporting.inspection_report",
            "required_world_core_slots": [
                "defect.class.present",
                "repair.required",
                "maintenance.pre_next_cycle.required",
            ],
            "required_measurement_slots": [
                # DEBT-025 closure 2026-05-07：删 phantom slot:
                # ratio.covered_area.inspected / count.access_opening.required
                # （2 项无 spec 授权 + 无 MBIS 法规阈值 + generator 不产值）
                "ratio.external_wall_area.inspected",
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.method_class",
                "qual.work_category",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar", "procedure_gate_sidecar"],
            "domain_buckets": ["structural_external", "coverage_sampling", "technical_validation"],
        },
        {
            "projection_registry_id": "NP_REPORTING_COMPLETION_V1",
            "projection_family": "mbis.reporting.completion_report",
            "required_world_core_slots": [
                "repair.outcome.safe_until_next_cycle",
                "maintenance.pre_next_cycle.required",
            ],
            "required_measurement_slots": [
                "stress.pull_test.minimum",
                "length.concrete_repair.depth",
                "ratio.rebar.section_loss",
                # Round2 retire: generic ratio.chloride_content 退役（rule_card 0 引用），如下游需引用
                # chloride 应改为 ratio.chloride_content.by_cement_weight.
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.method_class",
                "qual.work_category",
            ],
            "required_sidecar_interfaces": ["completion_report_sidecar", "supervision_sidecar"],
            "domain_buckets": ["technical_validation", "assessment"],
        },
        {
            "projection_registry_id": "NP_SCOPE_COVERAGE_PREINSPECTION_V1",
            "projection_family": "mbis.scope.coverage_and_preinspection",
            "required_world_core_slots": [
                "building.identity.basic",
                "building.metadata.occupancy_and_use",
                "building.metadata.configuration",
                "building.metadata.primary_materials",
                "scope.component.covered",
                "scope.component.obscured_by_finish",
            ],
            "required_measurement_slots": [],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.location_class",
            ],
            "required_sidecar_interfaces": ["inspection_report_sidecar"],
            "domain_buckets": ["structural_external", "coverage_sampling"],
        },
        {
            "projection_registry_id": "NP_REPAIR_FIRESAFETY_DRAINAGE_V1",
            "projection_family": "mbis.repair.fire_safety_and_drainage",
            "required_world_core_slots": [
                "repair.required",
                "maintenance.pre_next_cycle.required",
            ],
            "required_measurement_slots": [
                # DEBT-025 closure 2026-05-07：删 phantom slot:
                # count.drainage.test_points.minimum / length.drainage.branch.interval
                # （2 项无 spec 授权 + 无 MBIS 法规阈值 + generator 不产值）
                # 此 projection 现无 measurement 引用；basis 完全靠 world_core flag + sidecar
            ],
            "required_qualifier_slots": [
                "qual.component_type",
                "qual.method_class",
            ],
            "required_sidecar_interfaces": [
                "completion_report_sidecar",
                "inspection_report_sidecar",
            ],
            "domain_buckets": ["drainage", "fire_safety", "technical_validation"],
        },
        {
            "projection_registry_id": "NP_SUPERVISION_RC_CONTROLS_V1",
            "projection_family": "mbis.supervision.rc_controls",
            "required_world_core_slots": [],
            "required_measurement_slots": [],
            "required_qualifier_slots": ["qual.work_category"],
            "required_sidecar_interfaces": [
                "supervision_sidecar",
                "procedure_gate_sidecar",
            ],
            "domain_buckets": ["technical_validation"],
        },
    ]
    return _enrich_projection_registry_records(records)


_PROJECTION_SCHEMA_SUPPLEMENTS: Dict[str, Dict[str, Any]] = {
    "mbis.procedure.ri_notifications_and_submissions": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,
    },
    "mbis.inspection.external_components": {
        "basis_template_ids": ["threshold_compare", "bool_assertion"],
        "conflict_group": "structural_external_surface",
    },
    "mbis.inspection.structural_components": {
        "basis_template_ids": ["threshold_compare", "bool_assertion"],
        "conflict_group": "structural_external_surface",
    },
    "mbis.inspection.drainage": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": "drainage",
    },
    "mbis.investigation.gate_and_proposal": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,
    },
    # W2-005 (批次 C 2026-05-21)：spec 06 §2.1 row 5 / row 7 拆出独立 fire_safety / ubw entries.
    "mbis.inspection.fire_safety": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": "ubw_fire",
    },
    "mbis.inspection.ubw": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": "ubw_fire",
    },
    # W2-005 (批次 C 2026-05-21)：spec 06 §2.1 row 9 结构评估 FSP / row 10 修葺一般选择与分类.
    # FSP 跟 assessment_repair conflict_group 业务关联（spec 07 §4.2 校准注：
    # assessment_repair 因果链含 structural_assessment_deficit → repair_validation_failure）.
    "mbis.investigation.structural_assessment_fsp": {
        "basis_template_ids": ["threshold_compare", "bool_assertion"],
        "conflict_group": "assessment_repair",
    },
    "mbis.repair.general_selection_and_classification": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,  # spec 07 §4.2 标注：单独 family 不进 conflict_group
    },
    "mbis.repair.external_structural_validation": {
        "basis_template_ids": ["threshold_compare"],
        "conflict_group": "assessment_repair",
    },
    "mbis.supervision.ri_minimum_and_site_controls": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,
    },
    "mbis.reporting.inspection_report": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,
    },
    "mbis.reporting.completion_report": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,
    },
    "mbis.scope.coverage_and_preinspection": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,  # 待 T-23 决定归桶
    },
    "mbis.repair.fire_safety_and_drainage": {
        "basis_template_ids": ["threshold_compare", "bool_assertion"],
        "conflict_group": None,  # 待 T-23 决定是否进 drainage / ubw_fire 桶
    },
    "mbis.supervision.rc_controls": {
        "basis_template_ids": ["bool_assertion"],
        "conflict_group": None,  # sidecar-only family 暂不归桶
    },
}


def _derive_applicability_predicates(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """W2-008 (批次 C 2026-05-21)：spec 06 §4.5 派生规则——按 required_*_slots 机械派生
    4 类 applicability_predicate dict（world / measurement / qualifier / sidecar_join）.

    spec §4.5.1 派生映射表：
      required_world_core_slots → world predicate（每 slot 1 条断言）
      required_measurement_slots → measurement predicate
      required_qualifier_slots → qualifier predicate
      required_sidecar_interfaces → sidecar_join predicate

    spec §4.5.4 简化原则：当前 spec §2.1 16 family 表只给 slot 引用清单，**不给值约束**，
    所有派生 predicate 默认走最弱断言（world `non_null` / measurement `exists` /
    qualifier `non_null` / sidecar_join `marker_present`）。具体 family 业务边界值约束
    待 spec §4.5.5 后续扩展（gap 10 联动）.
    """
    predicates: List[Dict[str, Any]] = []
    for slot_id in record.get("required_world_core_slots", []):
        predicates.append({
            "predicate_class": "world",
            "target_object": "WorldBundle",
            "target_path": slot_id,
            "assertion": "non_null",
            "assertion_args": {},
            "w2_readonly_note": "predicate 只读不写（spec 06 §4.2 W2 红线 1）",
        })
    for slot_id in record.get("required_measurement_slots", []):
        predicates.append({
            "predicate_class": "measurement",
            "target_object": "MeasurementRecord",
            "target_path": slot_id,
            "assertion": "exists",
            "assertion_args": {},
            "w2_readonly_note": "predicate 只读不写（spec 06 §4.2 W2 红线 1）",
        })
    for slot_id in record.get("required_qualifier_slots", []):
        predicates.append({
            "predicate_class": "qualifier",
            "target_object": "qualifier_slot",
            "target_path": slot_id,
            "assertion": "non_null",
            "assertion_args": {},
            "w2_readonly_note": "predicate 只读不写（spec 06 §4.2 W2 红线 1）",
        })
    for interface_id in record.get("required_sidecar_interfaces", []):
        predicates.append({
            "predicate_class": "sidecar_join",
            "target_object": "sidecar_runtime_bundle",
            "target_path": interface_id,
            "assertion": "marker_present",
            "assertion_args": {},
            "w2_readonly_note": "predicate 只读不写（spec 06 §4.2 W2 红线 1）",
        })
    return predicates


def _enrich_projection_registry_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for record in records:
        supplement = _PROJECTION_SCHEMA_SUPPLEMENTS.get(record["projection_family"], {})
        # W2-008 (批次 C 2026-05-21)：按 spec 06 §4.5 派生规则机械填 applicability_predicates，
        # 替代旧 placeholder "TBD: see MBIS family scope"。spec §4.5 4 类断言由
        # _derive_applicability_predicates 按 required_*_slots 派生.
        record["applicability_predicates"] = _derive_applicability_predicates(record)
        record["rule_ids"] = []
        record["basis_template_ids"] = supplement.get("basis_template_ids", ["bool_assertion"])
        record["conflict_group"] = supplement.get("conflict_group")
    return records


PROJECTION_REGISTRY_INDEX = {
    record["projection_registry_id"]: record for record in _projection_registry_records()
}

# T-17h: WORLD_PROFILE_SPECS removed (was OLD profile-based legacy generator data path).
# 旧路径 hydration._build_worlds 用 11 个 profile + base seed index 实现 fragment-centric
# 生成；T-17a-d minimal 切换到 building-centric registry-driven sampling。world_profile_specs.v1.json
# 移到杂物箱/垃圾箱/T-17h_legacy_data/。


# W0-004 (2026-05-21)：对齐 spec 04 §9 DriverState 13 字段合约 + spec 06 §5 drainage
# surrogate 公式 + spec 11 §2.6 mechanism required_driver_fields；删除 age_years
# (在 BuildingContext，spec 04 §4 line 79 "driver 可引用") 与 4 个 spec 未背书 cruft
# 字段 (obstruction_index / drainage_usage_intensity / blockage_propensity /
# coverage_feasibility_index)。drainage_fault_propensity 走单一字段（不拆）。
_DRIVER_FIELD_RANGES: Dict[str, List[float]] = {
    "service_load_ratio": [0.0, 1.5],
    "restraint_level": [0.0, 1.0],
    "moisture_ingress_index": [0.0, 1.0],
    "chloride_exposure_index": [0.0, 1.0],
    "carbonation_index": [0.0, 1.0],
    "workmanship_deficit_index": [0.0, 1.0],
    "maintenance_deficit_index": [0.0, 1.0],
    "drainage_fault_propensity": [0.0, 1.0],
    "alteration_propensity": [0.0, 1.0],
    "fire_safety_deficit_index": [0.0, 1.0],
    "repair_quality_index": [0.0, 1.0],
}


def _field_ranges(*field_names: str) -> Dict[str, List[float]]:
    return {field_name: _DRIVER_FIELD_RANGES[field_name] for field_name in field_names}


def _latent_driver_records() -> List[Dict[str, Any]]:
    return [
        {
            "driver_id": "DRV_STRUCTURAL_DETERIORATION_V1",
            "driver_family": "structural_deterioration",
            "supported_domains": ["external", "structural", "repair_validation"],
            "field_ranges": _field_ranges(
                "service_load_ratio",
                "restraint_level",
                "moisture_ingress_index",
                "chloride_exposure_index",
                "carbonation_index",
                "workmanship_deficit_index",
                "maintenance_deficit_index",
                "repair_quality_index",
            ),
            "notes": "Preserves the a10 crack and corrosion lineage.",
        },
        {
            "driver_id": "DRV_DRAINAGE_OPERATION_V1",
            "driver_family": "drainage_operation",
            "supported_domains": ["drainage"],
            "field_ranges": _field_ranges(
                "moisture_ingress_index",
                "workmanship_deficit_index",
                "maintenance_deficit_index",
                "drainage_fault_propensity",
            ),
            "notes": "Drainage operation driver (spec 06 §5 single drainage_fault_propensity field).",
        },
        {
            "driver_id": "DRV_ALTERATION_AND_FIRE_V1",
            "driver_family": "alteration_and_fire",
            "supported_domains": ["ubw", "fire_safety"],
            "field_ranges": _field_ranges(
                "workmanship_deficit_index",
                "maintenance_deficit_index",
                "alteration_propensity",
                "fire_safety_deficit_index",
            ),
            "notes": "Keeps physical fire-safety deficiency in world core and record status in sidecar.",
        },
    ]


_PRECISION_STEPS: Dict[str, Dict[str, float]] = {
    "geometry_width_mm": {"coarse": 0.10, "standard": 0.05, "fine": 0.01},
    "geometry_length_m": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
    "geometry_area_m2": {"coarse": 0.010, "standard": 0.001, "fine": 0.0005},
    "coverage_ratio": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
    "integer_count": {"coarse": 1.0, "standard": 1.0, "fine": 1.0},
    "test_stress": {"coarse": 10.0, "standard": 1.0, "fine": 0.1},
    "thickness_depth_mm": {"coarse": 5.0, "standard": 1.0, "fine": 0.5},
    "time_seconds": {"coarse": 1.0, "standard": 0.1, "fine": 0.01},
}


def _measurement_record(
    slot_id: str,
    measurement_family: str,
    value_type: str,
    unit: str,
    physical_bounds: List[Any],
    precision_key: Optional[str],
    method_classes: List[str],
    aliases: Optional[List[str]] = None,
    notes: str = "",
    # DEBT-026 (spec 04 §17 / spec 03 §4.2): typical 分布参数（optional；不传走中点采样 fallback）
    # physical_bounds = 物理可能极值（hard clip），下列字段定义"工程现实 typical 分布"
    recommended_distribution: Optional[str] = None,  # "normal" / "lognormal" / "uniform" / "triangular"
    recommended_mean: Optional[float] = None,         # normal / lognormal / triangular 必填
    recommended_sigma: Optional[float] = None,        # normal / lognormal 必填
    typical_bounds: Optional[List[Any]] = None,       # [typical_min, typical_max] 实操区间；uniform / triangular 必填；normal 可选作 generation 边界
    distribution_source: Optional[str] = None,        # source attribution（如 "proagent_engineering_estimate_current_authority_round5_2026_05_10"）
    # DEBT-028 修复（2026-05-11）：lognormal `recommended_mean` 语义显式标注，避免 generic path / chain derive 双语义陷阱
    mean_semantics: Optional[str] = None,             # "median"（缺省，lognormal generic 路径默认）/ "arithmetic_mean"（chain derive / per-class lognormal）
) -> Dict[str, Any]:
    return {
        "slot_id": slot_id,
        "measurement_family": measurement_family,
        "value_type": value_type,
        "unit": unit,
        "physical_bounds": physical_bounds,
        "precision_steps": _PRECISION_STEPS[precision_key] if precision_key else {},
        "method_classes": method_classes,
        "aliases": aliases or [],
        "notes": notes,
        # DEBT-026 字段（None 时 _sample_value_for_slot 退回中点 fallback）
        "recommended_distribution": recommended_distribution,
        "recommended_mean": recommended_mean,
        "recommended_sigma": recommended_sigma,
        "typical_bounds": typical_bounds,
        "distribution_source": distribution_source,
        # DEBT-028 字段（lognormal 用；None 默认按 median 解释）
        "mean_semantics": mean_semantics,
    }


def _technical_measurement_records() -> List[Dict[str, Any]]:
    return [
        # DEBT-020/026 round2 proagent (2026-05-09): 5 个 round2 distribution 落地（B 段 risk_derivation input + A.1 stress.pull_test.minimum）
        _measurement_record(
            "crack_width_mm", "defect_geometry", "float", "mm", [0.05, 3.0],
            "geometry_width_mm", ["visual_inspection", "crack_gauge"],
            notes="Defect geometry; damage-downstream measurement. Round2 bounds 5.0→3.0mm 收紧。",
            recommended_distribution="lognormal",
            recommended_mean=0.45, recommended_sigma=0.75,  # arithmetic_mean (pro round2 line 151); sigma_log
            typical_bounds=[0.05, 2.00],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11: pro round2 标 arith，老 W0 实现按 median 错跑被发现修
        ),
        _measurement_record(
            "crack_length_m", "defect_geometry", "float", "m", [0.05, 30.0],
            "geometry_length_m", ["visual_inspection", "tape_measure"],
            notes="Defect geometry; damage-downstream measurement. Round2 bounds 500→30m 收紧。",
            recommended_distribution="lognormal",
            recommended_mean=1.60, recommended_sigma=0.85,  # arithmetic_mean (pro round2 line 185); sigma_log
            typical_bounds=[0.10, 12.00],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11
        ),
        _measurement_record("spall_area_m2", "defect_geometry", "float", "m2", [0.001, "0.6*fragment_area"], "geometry_area_m2", ["visual_inspection", "area_estimate"], notes="Defect geometry; preserves a10 geometry lineage."),
        _measurement_record(
            "rebar_exposed_length_m", "defect_geometry", "float", "m", [0.0, 8.0],
            "geometry_length_m", ["visual_inspection", "tape_measure"],
            notes="Defect geometry; rebar exposure surrogate. Round2 bounds 500→8m 收紧；zero_inflated_lognormal → lognormal 退化（zero mass 信息损失）。",
            recommended_distribution="zero_inflated_lognormal",  # → lognormal in normalize
            recommended_mean=0.41, recommended_sigma=0.53,  # overall (zero+positive mixture) — 注：会按 lognormal arithmetic mean 解释，不完全准确
            typical_bounds=[0.00, 4.00],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09_alignment_marginal",
        ),
        _measurement_record(
            "rate.pull_test.per_25m2", "technical_validation", "float", "count/25m2", [0.25, 5.0],
            "coverage_ratio", ["pull_test"], ["pull_test_rate_per_25m2"],
            notes="Round2 bounds 20→5 收紧。proagent alignment=failed confidence=low：rule_card threshold ≤25 与 unit count/25m2 比较方向疑似错位（详见 round2 回复 self_check）。落地 distribution 但等待 rule_card binding 修正后才纳入 5-bin 健康度统计。",
            recommended_distribution="lognormal",
            recommended_mean=1.25, recommended_sigma=0.35,  # arithmetic_mean (pro round2 line 119); sigma_log
            typical_bounds=[0.50, 3.00],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09_alignment_failed_pending_rulecard_binding_fix",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11
        ),
        _measurement_record(
            "count.pull_test.per_repaired_facade", "technical_validation", "integer", "count", [0, 25],
            "integer_count", ["pull_test"], ["pull_test_count_per_repaired_facade"],
            notes="Round2 bounds 50→25 收紧；rounded_truncated_normal→normal + integer round。",
            recommended_distribution="rounded_truncated_normal",
            recommended_mean=6.0, recommended_sigma=3.0,
            typical_bounds=[1, 18],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "count.pull_test.per_floor_full_retiling", "technical_validation", "integer", "count", [0, 20],
            "integer_count", ["pull_test"], ["pull_test_count_per_floor_full_retiling"],
            notes="Round2 bounds 30→20 收紧。",
            recommended_distribution="rounded_truncated_normal",
            recommended_mean=5.5, recommended_sigma=2.0,
            typical_bounds=[1, 12],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "stress.pull_test.minimum", "technical_validation", "float", "N_per_mm2", [0.10, 2.50],
            "test_stress", ["pull_test"], ["pull_test_stress_minimum"],
            notes="Round2 bounds 100→2.5 N/mm2 收紧（旧 100 是粘结强度量级错误）。",
            recommended_distribution="truncated_normal",
            recommended_mean=0.75, recommended_sigma=0.30,
            typical_bounds=[0.20, 1.80],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "strength.pull_test.reported", "technical_validation", "float", "N_per_mm2", [0.10, 3.00],
            "test_stress", ["pull_test"], ["pull_test_strength_reported"],
            "Measured pull-test strength used by verification outcome derivation. Round2 bounds 100→3.0 N/mm2 收紧。",
            recommended_distribution="truncated_normal",
            recommended_mean=0.90, recommended_sigma=0.35,
            typical_bounds=[0.20, 2.20],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "count.pull_test.failed_cumulative", "technical_validation", "integer", "count", [0, 6],
            "integer_count", ["pull_test"], ["pull_test_failed_cumulative_count"],
            "Cumulative failed pull-test count used by additional-test formula thresholds. Round2 bounds 10→6；zero_inflated_discrete → normal 退化（zero mass 信息损失）。",
            recommended_distribution="zero_inflated_discrete",  # → normal in normalize
            recommended_mean=0.95, recommended_sigma=1.12,
            typical_bounds=[0, 5],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "count.pull_test.additional_after_failure", "technical_validation", "integer", "count", [0, 10],
            "integer_count", ["pull_test"], ["pull_test_additional_after_failure_count"],
            notes="formula_mixture_discrete (n^2-2n+3 + zero) → normal 退化。",
            recommended_distribution="formula_mixture_discrete",  # → normal in normalize
            recommended_mean=1.70, recommended_sigma=1.57,
            typical_bounds=[0, 6],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        # NOTE: length.rendering.* canonical names per rule_card (App4 1.3); legacy
        # length.plaster.* removed in DEBT-025 closure (2026-05-06). 见 audit_report.md
        # 关键差集 6——plaster vs rendering 经 user 审计判定为同物，统一用 rule_card 命名。
        _measurement_record(
            "length.rendering.total_thickness", "technical_validation", "float", "mm",
            [0.0, 100.0], "thickness_depth_mm", ["destructive_probe", "thickness_gauge"],
            ["plaster_total_thickness_mm", "rendering_total_thickness_mm"],
            "MBIS App4 1.3 批荡总厚度技术测量；rule_card threshold ≤20mm。",
            # DEBT-020/026 round1 proagent: HK RC 外墙批荡 3 层施工累计
            recommended_distribution="truncated_normal",
            recommended_mean=18.0, recommended_sigma=5.0,
            typical_bounds=[8.0, 30.0],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
        ),
        _measurement_record(
            "length.rendering.layer_thickness", "technical_validation", "float", "mm",
            [0.0, 100.0], "thickness_depth_mm", ["destructive_probe", "thickness_gauge"],
            ["plaster_layer_thickness_mm", "rendering_layer_thickness_mm"],
            "MBIS App4 1.3 批荡每层厚度技术测量；rule_card threshold ≤10mm。",
            # DEBT-020/026 round1 proagent: 单层 cement rendering 受可施工性 + 收缩约束
            recommended_distribution="truncated_normal",
            recommended_mean=7.2, recommended_sigma=2.2,
            typical_bounds=[3.0, 13.0],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
        ),
        _measurement_record(
            "depth.patch_repair", "technical_validation", "float", "mm",
            [0.0, 300.0], "thickness_depth_mm", ["destructive_probe", "cover_meter"],
            ["patch_repair_depth_mm"],
            "MBIS App5 1.1(a)(i) 修补深度技术测量；rule_card threshold <75mm 触发 patch repair 适用。",
            # DEBT-020/026 round1 proagent: 凿至 sound concrete + 保护层 + 钢筋背后清理
            recommended_distribution="truncated_normal",
            recommended_mean=55.0, recommended_sigma=18.0,
            typical_bounds=[20.0, 100.0],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
        ),
        _measurement_record(
            "length.concrete_repair.depth", "technical_validation", "float", "mm", [5.0, 180.0],
            "thickness_depth_mm", ["destructive_probe", "cover_meter"], ["concrete_repair_depth_mm"],
            notes="Generic concrete repair depth；与 depth.patch_repair 重叠语义但范围更广。Round2 bounds 300→180 收紧。",
            recommended_distribution="truncated_normal",
            recommended_mean=65.0, recommended_sigma=28.0,
            typical_bounds=[15.0, 140.0],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "duration.repair_mortar.test_age", "technical_validation", "integer", "day", [5, 14],
            "integer_count", ["material_test"], ["repair_mortar_test_age_days"],
            notes="Round2: discrete_mixture_rounded → normal 退化（多峰离散信息损失，但 mean=7.25 sigma=1.05 抓住主体）；value_type 由 float 改 integer（test age 是离散天数）；bounds 30→14 收紧。",
            recommended_distribution="discrete_mixture_rounded",  # → normal in normalize
            recommended_mean=7.25, recommended_sigma=1.05,
            typical_bounds=[5, 10],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "count.repair_mortar_specimens.per_strength_property", "technical_validation", "integer", "specimen", [1, 8],
            "integer_count", ["material_test"], ["repair_mortar_specimens_per_strength_property"],
            notes="Round2 bounds 20→8 收紧。",
            recommended_distribution="rounded_truncated_normal",
            recommended_mean=2.8, recommended_sigma=0.9,
            typical_bounds=[1, 6],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "ratio.rebar.section_loss", "technical_validation", "float", "ratio", [0.0, 0.50],
            "coverage_ratio", ["visual_inspection", "caliper", "cover_meter"], ["rebar_section_loss_ratio"],
            notes="Round2 bounds 1.0→0.50 收紧（>30% section loss 已属严重结构评估边界）。",
            recommended_distribution="lognormal",
            recommended_mean=0.09, recommended_sigma=0.75,  # arithmetic_mean (pro round2 line 503); sigma_log
            typical_bounds=[0.00, 0.35],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11
        ),
        _measurement_record(
            "length.mortar.application_layer_thickness", "technical_validation", "float", "mm", [2.0, 50.0],
            "thickness_depth_mm", ["destructive_probe", "thickness_gauge"], ["mortar_application_layer_thickness_mm"],
            notes="Round2 bounds 100→50 收紧（单层施工受收缩 / 附着限制）。",
            recommended_distribution="truncated_normal",
            recommended_mean=14.0, recommended_sigma=6.0,
            typical_bounds=[4.0, 35.0],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        # Round2 closure 2026-05-09: generic "ratio.chloride_content" 已退役.
        # 退役理由（proagent round2 回复 suggested_followups #2）：rule_card 0 条 threshold 引用，
        # 与 round1 显式 qualifier 版 ratio.chloride_content.by_cement_weight 重叠语义；
        # generic slot 是 dead code（无下游消费方）.
        # 历史 distribution（lognormal mean=0.0065 sigma=0.55 [0.0005, 0.0180]）见 git log.
        _measurement_record(
            "ratio.chloride_content.by_cement_weight", "technical_validation", "float", "%",
            [0.0, 5.0], "coverage_ratio", ["material_test"],
            ["chloride_content_by_cement_weight_pct"],
            "MBIS App5 1.2(a)(i) 按水泥重量计的氯离子含量；rule_card threshold >0.8% 触发 recasting 强制要求。",
            # DEBT-020/026 round1 proagent: HK 旧 RC spalling/corrosion 调查样本右偏长尾分布
            recommended_distribution="lognormal",
            recommended_mean=0.65, recommended_sigma=0.55,  # arithmetic_mean (pro round1 line 114); sigma_log
            typical_bounds=[0.05, 1.80],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11
        ),
        _measurement_record(
            "index.drainage.blockage", "technical_validation", "float", "ratio", [0.0, 1.0],
            "coverage_ratio", ["drainage_cctv", "visual_inspection"], ["drainage_blockage_index"],
            "Drainage blockage index for public-health risk derivation. Round2: beta → normal 退化（bounded shape 信息损失，clip 由 bounds 处理）。",
            recommended_distribution="beta",  # → normal in normalize
            recommended_mean=0.35, recommended_sigma=0.18,
            typical_bounds=[0.02, 0.85],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "index.drainage.leakage", "technical_validation", "float", "ratio", [0.0, 1.0],
            "coverage_ratio", ["drainage_cctv", "water_test"], ["drainage_leakage_index"],
            "Drainage leakage index for public-health risk derivation. Round2: beta → normal 退化。",
            recommended_distribution="beta",  # → normal in normalize
            recommended_mean=0.38, recommended_sigma=0.18,
            typical_bounds=[0.02, 0.90],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        _measurement_record(
            "flag.drainage.misconnection_present", "technical_validation", "bool", "ratio", [0.0, 1.0],
            "coverage_ratio", ["drainage_cctv", "smoke_test", "water_test"], ["drainage_misconnection_present"],
            "0/1 drainage misconnection indicator for public-health risk derivation."
            " Round2 schema fix (2026-05-09): value_type float→bool（旧版 schema 与语义错位，"
            " round2 proagent suggested_followups #5 修复）；recommended_mean=0.08 当 Bernoulli prevalence p。",
            recommended_distribution="bernoulli_as_float",  # → bernoulli in normalize
            recommended_mean=0.08, recommended_sigma=0.27,  # sigma 仅作 self_check 信息；bernoulli sampler 不用
            typical_bounds=[0, 1],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        # ---------- DEBT-049 Phase3 U5 §2.1b：air/ball 专用观测 slot（method_class 承载体）----------
        # measurement_family="drainage_method_observation" 是**专用 family**（不入 generate_
        # technical_validation_measurements 的 ["technical_validation","boolean_assertion"] 通用池
        # → 不被 rng.shuffle 扰动既有序列、不在错误 fragment 生成）；仅由 generate_structural_
        # assessment_measurements 内 §2.1 P3a/P3b 命中时经 _drainage_airball_obs_rng 显式 emit
        # （explicit-value 路径，无 distribution 采样；故不填 recommended_* / typical_bounds）。
        # method_class air_test/ball_test 由此扩入 technical_measurement_registry 的 method_class 并集
        # （19→21，接 verification_test_registry 现成 VT_DRAINAGE_AIR_TEST_V1/VT_DRAINAGE_BALL_TEST_V1
        # 物理定义）；emit 时 MeasurementRecord.measurement_family 显式给 "technical_validation_measurement"。
        _measurement_record(
            "pressure.drainage.air_test.loss_mmH2O", "drainage_method_observation", "float", "mmH2O", [0.0, 60.0],
            None, ["air_test"], ["drainage_air_test_pressure_loss_mmH2O"],
            notes="DEBT-049 Phase3 U5 §2.1b：drainage 空氣測試窗口内绝对压降（air_test 承载体）。"
            " CoP §5.6.5(b) / VT_DRAINAGE_AIR_TEST_V1 failure_rule（pressure_loss > acceptable_drop）；"
            " 档常量 test_pressure/acceptable_drop 由 is_underground 进 qualifiers。显式 value_num，无采样。",
        ),
        _measurement_record(
            "flag.drainage.ball_test.pass", "drainage_method_observation", "bool", None, [False, True],
            None, ["ball_test"], ["drainage_ball_test_pass"],
            notes="DEBT-049 Phase3 U5 §2.1b：drainage 球測試球通过与否（ball_test 承载体）。"
            " CoP §5.6.5(a) / VT_DRAINAGE_BALL_TEST_V1 failure_rule（ball_fails_to_pass_within_time_limit）；"
            " 显式 value_bool，无采样。",
        ),
        _measurement_record(
            "public_health_risk_index", "derived_risk_measurement", "float", "ratio", [0.0, 1.0],
            "coverage_ratio", ["formula"],
            notes="a12 drainage public-health risk index derived from blockage, leakage, and misconnection."
            " Round2 alignment=marginal confidence=low：临时 fallback；spec06 §11 派生公式落地后取消独立 distribution"
            "（详见 round2 回复 suggested_followups #3）。beta_mixture → normal 退化。",
            recommended_distribution="beta_mixture",  # → normal in normalize
            recommended_mean=0.38, recommended_sigma=0.22,
            typical_bounds=[0.05, 0.95],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09_alignment_marginal_temporary_until_derivation",
        ),
        _measurement_record(
            "count.hammer_tapping.grid.minimum", "coverage_sampling", "integer", "count", [5, 150],
            "integer_count", ["hammer_tapping"], ["hammer_tapping_grid_minimum"],
            notes="Round2 bounds 200→150 收紧；fragment-independent fallback，长期应由 fragment_area / unit_grid 派生（详见 round2 回复 suggested_followups #4）。",
            recommended_distribution="rounded_truncated_normal",
            recommended_mean=50.0, recommended_sigma=20.0,
            typical_bounds=[10, 120],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
        ),
        # SCAN guardrail closure 2026-05-07: 3 个 assessment family slot 由 spec 04 §17 已写
        # 但 _technical_measurement_records 漏实现；spec 03 §3 line 100 / 102 cross-registry
        # consistency test 暴露此 drift。详见 `tests/test_spec_consistency.py`。
        _measurement_record("ratio.fsp.structural_performance", "assessment", "float", "ratio", [0.0, 2.0], "coverage_ratio", ["formula"], ["fsp_structural_performance_ratio"], "MBIS §3.4.2 / §4.3 FSP 评估输出；assessment_surrogate_registry.AS_FSP_MEMBER_V1.output_slots + risk_derivation RISK_BUILDING_SAFETY_EMERGENCY_V1 input。"),
        _measurement_record("count.core_sample.minimum", "assessment", "integer", "count", [0, 1000], "integer_count", ["core_sample"], ["core_sample_count"], "MBIS concrete core assessment 抽样数；assessment_surrogate_registry output。"),
        _measurement_record("rate.core_sample.per_concrete_volume", "assessment", "float", "count/m3", [0.0, 100.0], "coverage_ratio", ["core_sample"], ["core_sample_rate_per_volume"], "MBIS concrete core assessment 抽样率（每立方米）。"),
        _measurement_record(
            "time.fire_door.self_closing.delay_sec", "technical_validation", "float", "s", [0.0, 60.0],
            "time_seconds", ["self_closing_test"], ["fire_door_self_closing_delay_sec"],
            notes="Round2 bounds 300→60s 收紧（300 是异常占位上界，工程现实远不到）。failure_rule >10s。",
            recommended_distribution="lognormal",
            recommended_mean=6.5, recommended_sigma=0.55,  # arithmetic_mean (pro round2 line 568); sigma_log
            typical_bounds=[1.0, 35.0],
            distribution_source="proagent_engineering_estimate_DEBT020_round2_2026_05_09",
            mean_semantics="arithmetic_mean",  # DEBT-028 fix 2026-05-11
        ),
        _measurement_record("verification.test.failed", "boolean_assertion", "bool", "bool", [False, True], None, ["pull_test", "drainage_cctv", "smoke_test", "water_test", "self_closing_test"], ["verification_test_failed"], "Technical validation boolean emitted by failed drainage or repair verification tests."),
        # ---------- DEBT-020 round5 sub-task 2 (2026-05-10) chain_C_plus 链式派生 slot ----------
        # 授权：spec 04 §17 + spec 03 §4.4 sampling_plan_registry yaml + spec 06 §8 / §9 chain 公式 +
        #      `杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L237-L431
        # 4 个 chain input slot：上游分布 / plan-level 数据；2 个 chain derived A 类 slot：无 distribution，由 chain 算出。
        # ratio.covered_area.inspected 同步从 spec 04 §17 cell"补建"为 registry slot（先前 spec 已列但 registry 漏建）。

        # B 类 chain input — 立面级修复总面积（building / facade seed RNG）
        _measurement_record(
            "facade_total_repaired_area_m2", "sampling_plan", "float", "m2", [20.0, 500.0],
            "geometry_area_m2", ["formula", "plan_record"], ["facade_repaired_area_m2"],
            notes="DEBT-020 round5 sub-task 2 chain input（立面级修复总面积；building/facade seed RNG，一栋楼共享）；"
            "spec 06 §9 chain Step 1。Plan-level data；不走 per-fragment 采样.",
            recommended_distribution="lognormal",
            recommended_mean=120.0, recommended_sigma=0.75,  # arithmetic_mean=120m², sigma_log
            typical_bounds=[40.0, 280.0],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
            mean_semantics="arithmetic_mean",  # DEBT-028 防 footgun（chain derive arith；generic path 也会按 arith 解释）
        ),
        # B 类 chain input — 立面级 plan-intensity tests/25m² (building/facade seed RNG)
        _measurement_record(
            "plan_intensity_tests_per_25m2", "sampling_plan", "float", "tests/25m2", [0.50, 3.00],
            "coverage_ratio", ["formula", "plan_record"], [],
            notes="DEBT-020 round5 sub-task 2 chain input（立面级 plan-intensity tests/25m²；building/facade seed RNG）；"
            "spec 06 §9 chain Step 2。",
            recommended_distribution="lognormal",
            # [S2.5-CALIB 2026-07-02] mean 1.25→1.9 与 pull_test_sampling_plan 的标定值对齐
            # （patch 只改了 plan 记录；本记录无 src 消费、纯声明，对齐防两处声明打架）。
            recommended_mean=1.9, recommended_sigma=0.35,  # arithmetic_mean=1.9 tests/25m², sigma_log
            typical_bounds=[0.50, 3.00],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
            mean_semantics="arithmetic_mean",  # DEBT-028 防 footgun
        ),
        # B 类 chain input — 立面级 total_pull_test_count（plan_derived_rounded_lognormal_intensity）
        # 注：这是 plan derived 中间量，由 facade_total_repaired_area_m2 + plan_intensity 共同 derive；落 typical
        # 分布字段是为了 round5 self-check / MC sanity 跑得动（pro 设计 self-check baseline）。
        _measurement_record(
            "total_pull_test_count_per_facade", "sampling_plan", "integer", "count", [0, 25],
            "integer_count", ["formula", "plan_record"], [],
            notes="DEBT-020 round5 sub-task 2 chain input（plan_derived_rounded_lognormal_intensity；spec 06 §9 chain Step 3）；"
            "公式 round_clip(plan_intensity * facade_total_repaired_area_m2 / 25.0, 1, 25)；mean≈5.9 typical=[1,16].",
            recommended_distribution="rounded_truncated_normal",
            recommended_mean=5.9, recommended_sigma=5.0,
            typical_bounds=[1, 16],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
        ),
        # B 类 chain input — per-fragment inspected area ratio（fragment seed RNG）
        _measurement_record(
            "inspected_area_ratio_per_fragment", "sampling_plan", "float", "ratio", [0.00, 1.00],
            "coverage_ratio", ["formula", "plan_record"], [],
            notes="DEBT-020 round5 sub-task 2 chain input（per-fragment truncated_normal 采样；spec 06 §8 chain Step 1）；"
            "fragment seed RNG.",
            recommended_distribution="truncated_normal",
            recommended_mean=0.45, recommended_sigma=0.18,
            typical_bounds=[0.10, 0.85],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
        ),
        # ---------- DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas chain input ----------
        # 授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1266-L1292
        # `count.pull_test.per_floor_full_retiling` 升 A 类 chain derive 需要 floor-level retiling
        # 总面积 + retiling plan_intensity；与 `pull_test_sampling_plan` 同 schema 但 floor-level.
        # B 类 chain input — floor-level retiling 总面积（building / floor seed RNG，一栋楼共享）
        _measurement_record(
            "floor_full_retiling_area_m2", "sampling_plan", "float", "m2", [10.0, 400.0],
            "geometry_area_m2", ["formula", "plan_record"], [],
            notes="DEBT-020 round5 sub-task 4 chain input（floor-level retiling 总面积；building/floor seed RNG，一栋楼共享）；"
            "spec 06 §9.X chain Step 1。Plan-level data；不走 per-fragment 采样.",
            recommended_distribution="lognormal",
            recommended_mean=80.0, recommended_sigma=0.65,  # arithmetic_mean=80m², sigma_log
            typical_bounds=[25.0, 200.0],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
            mean_semantics="arithmetic_mean",  # DEBT-028 防 footgun
        ),
        # B 类 chain input — floor-level retiling plan-intensity tests/25m² (building/floor seed RNG)
        _measurement_record(
            "retiling_plan_intensity_tests_per_25m2", "sampling_plan", "float", "tests/25m2", [0.60, 3.00],
            "coverage_ratio", ["formula", "plan_record"], [],
            notes="DEBT-020 round5 sub-task 4 chain input（floor-level retiling plan-intensity tests/25m²；building/floor seed RNG）；"
            "spec 06 §9.X chain Step 2。",
            recommended_distribution="lognormal",
            recommended_mean=1.35, recommended_sigma=0.30,  # arithmetic_mean=1.35 tests/25m², sigma_log
            typical_bounds=[0.60, 3.00],
            distribution_source="proagent_engineering_estimate_current_authority_round5_2026_05_10",
            mean_semantics="arithmetic_mean",  # DEBT-028 防 footgun
        ),

        # A 类 chain derived — 无 distribution，由 chain 算出（spec 06 §9 chain Step 4）
        _measurement_record(
            "effective_pull_test_count_per_fragment", "sampling_plan", "float", "count", [0.0, 25.0],
            "coverage_ratio", ["formula"], [],
            notes="DEBT-020 round5 sub-task 2 chain derived A 类（无 distribution；spec 06 §9 chain Step 4）；"
            "公式 total_pull_test_count_per_facade * fragment_repaired_area_m2 / max(facade_total_repaired_area_m2, eps)；"
            "可非整数（按 area share 分配；Option C+ 关键反爆炸保护）.",
        ),
        # A 类 chain derived — 无 distribution，由 chain 算出（spec 06 §8 chain Step 2）
        _measurement_record(
            "inspected_area_m2", "sampling_plan", "float", "m2", [0.0, 5000.0],
            "geometry_area_m2", ["formula"], [],
            notes="DEBT-020 round5 sub-task 2 chain derived A 类（无 distribution；spec 06 §8 chain Step 2）；"
            "公式 inspected_area_ratio_per_fragment * fragment_area_m2；上限受 fragment_area_m2 约束.",
        ),
        # A 类 chain derived — coverage ratio canonical name（spec 04 §17 line 261；spec 06 §8 chain Step 3）
        # 先前 spec 04 §17 已列 ratio.covered_area.inspected (a4 canonical)，但 registry 漏建（仅 ratio.external_wall_area.inspected
        # / ratio.covered_structure_area.inspected 在 sidecar inspection_execution 域）；本轮按 chain_C_plus 升 A 类同时补建.
        _measurement_record(
            "ratio.covered_area.inspected", "coverage_sampling", "float", "ratio", [0.0, 1.0],
            "coverage_ratio", ["visual_inspection", "plan_based_estimate"], ["covered_area_ratio"],
            notes="DEBT-020 round5 sub-task 2 升 A 类 chain derived（spec 06 §8 chain_C_plus，2026-05-10）；"
            "公式 clip(inspected_area_m2 / max(fragment_area_m2, eps), 0.0, 1.0)；MC sanity mean≈0.45 p5/p95≈[0.15,0.75].",
        ),
    ]


def _sampling_plan_records() -> List[Dict[str, Any]]:
    """DEBT-020 round5 sub-task 2 复活 2026-05-10：填充 chain_C_plus 链式派生 plan record.

    历史背景：DEBT-025 closure 2026-05-07 清空原 6 plan record（target_slot_ids 越界 sidecar
    inspection_execution 域 + 0 consumer + formula 非 evaluable）。

    DEBT-020 round5 sub-task 2 用户决策（2026-05-10）：
    - rate.pull_test.per_25m2 + ratio.covered_area.inspected 升 A 类，走 Option C+ 链式派生
    - 复活 sampling_plan_registry 存 facade 级计划数据
    - pull_test 走 facade 级密度分配；inspected_area 走 per-fragment 截断正态采样

    本 registry 现承载 plan-level data（chain_C_plus 选项；详见 spec 06 §8 §9 / spec 03 §4.4 yaml）。
    consumer：generator.py::generate_structural_assessment_measurements 的 chain derive 路径
    （`_compute_facade_total_repaired_area_m2` / `_compute_plan_intensity_tests_per_25m2` /
    `_compute_total_pull_test_count_per_facade` / `_compute_effective_pull_test_count_per_fragment` /
    `_compute_pull_test_rate_per_25m2_chain` / `_compute_inspected_area_ratio_per_fragment` /
    `_compute_ratio_covered_area_inspected_chain`）。

    授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L237-L431
    """
    return [
        {
            "sampling_plan_id": "pull_test_sampling_plan",
            "plan_level": "facade_or_floor_repair_package",
            "target_slot_ids": [
                "facade_total_repaired_area_m2",
                "total_pull_test_count_per_facade",
                "effective_pull_test_count_per_fragment",
                "rate.pull_test.per_25m2",
            ],
            "basis_area_slot": "facade_total_repaired_area_m2",
            # plan-intensity 分布参数（与 technical_measurement_registry typical 字段同义）
            # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] arithmetic mean 1.25→1.9（×1.52）,
            # sigma_log 不动；抬高拉力测试密度满足 >=1 test/25m² 阈值；模拟合规 93.4%。仅标定验证用。
            "plan_intensity_distribution": {
                "recommended_distribution": "lognormal",
                "recommended_mean": 1.9,          # arithmetic mean tests/25m² (S2.5: was 1.25)
                "recommended_sigma": 0.35,        # sigma_log
                "typical_bounds": [0.50, 3.00],
            },
            # spec 06 §9 chain Step 3
            "total_count_formula": (
                "plan_intensity = sample_lognormal(mean=1.25, sigma_log=0.35, clip=[0.50,3.00]); "
                "total_pull_test_count_per_facade = "
                "round_clip(plan_intensity * facade_total_repaired_area_m2 / 25.0, lower=1, upper=25)"
            ),
            # spec 06 §9 chain Step 4 — area-proportional allocation（关键反爆炸保护）
            "fragment_allocation_formula": (
                "effective_pull_test_count_per_fragment = "
                "total_pull_test_count_per_facade * fragment_repaired_area_m2 "
                "/ max(facade_total_repaired_area_m2, eps)"
            ),
            "coverage_ratio_slot": "rate.pull_test.per_25m2",
            "min_count_formula": None,   # a12 旧字段，chain plan 不用
            "interval_formula": None,    # a12 旧字段，chain plan 不用
            "notes": (
                "Option C+ chain: facade-level count plan-allocation; effective_count 可非整数; "
                "代数等价于 facade-level total_count / facade_area * 25.0; "
                "1m² fragment 不爆炸 rate=25; MC sanity mean≈1.25 p5/p95≈[0.64,2.10]."
            ),
        },
        {
            "sampling_plan_id": "coverage_inspection_plan",
            "plan_level": "fragment",
            "target_slot_ids": [
                "inspected_area_ratio_per_fragment",
                "inspected_area_m2",
                "ratio.covered_area.inspected",
            ],
            "basis_area_slot": "fragment_area_m2",
            "plan_intensity_distribution": {
                "recommended_distribution": "truncated_normal",
                "recommended_mean": 0.45,
                "recommended_sigma": 0.18,
                "typical_bounds": [0.10, 0.85],
            },
            # spec 06 §8 chain Step 1 — per-fragment truncated_normal sampling
            "total_count_formula": (
                "inspected_area_ratio_per_fragment = "
                "sample_truncated_normal(mean=0.45, sigma=0.18, clip=[0.10,0.85])"
            ),
            # spec 06 §8 chain Step 2 + 3 — derive ratio
            "fragment_allocation_formula": (
                "inspected_area_m2 = inspected_area_ratio_per_fragment * fragment_area_m2; "
                "ratio.covered_area.inspected = "
                "clip(inspected_area_m2 / max(fragment_area_m2, eps), 0.0, 1.0)"
            ),
            "coverage_ratio_slot": "ratio.covered_area.inspected",
            "min_count_formula": None,
            "interval_formula": None,
            "notes": (
                "Per-fragment truncated_normal 直接采样; 不需要 facade-level allocation; "
                "MC sanity ratio.covered_area.inspected mean≈0.45 p5/p95≈[0.15,0.75]."
            ),
        },
        # DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas plan record
        # 授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1266-L1292
        # 与 pull_test_sampling_plan 同 schema 但 floor-level（每楼层 retiling package）。
        {
            "sampling_plan_id": "floor_retiling_package",
            "plan_level": "floor_retiling_package",
            "target_slot_ids": [
                "floor_full_retiling_area_m2",
                "count.pull_test.per_floor_full_retiling",
            ],
            "basis_area_slot": "floor_full_retiling_area_m2",
            "plan_intensity_distribution": {
                "recommended_distribution": "lognormal",
                "recommended_mean": 1.35,         # arithmetic mean tests/25m²
                "recommended_sigma": 0.30,        # sigma_log
                "typical_bounds": [0.60, 3.00],
            },
            # spec 06 §9.X chain — floor-level total_count derive
            "total_count_formula": (
                "retiling_plan_intensity = sample_lognormal(mean=1.35, sigma_log=0.30, clip=[0.60,3.00]); "
                "count.pull_test.per_floor_full_retiling = "
                "round_clip(retiling_plan_intensity * floor_full_retiling_area_m2 / 25.0, lower=1, upper=20)"
            ),
            "fragment_allocation_formula": None,  # floor-level，不分配到 fragment
            "coverage_ratio_slot": None,
            "min_count_formula": None,
            "interval_formula": None,
            "notes": (
                "DEBT-020 round5 sub-task 4 floor retiling chain: floor-level lognormal plan_intensity "
                "+ retiling area → round_clip count [1, 20]. MC sanity mean≈5.6, p5/p95≈[2,10]."
            ),
        },
    ]


def _defect_condition_record(
    condition_class: str,
    defect_class: str,
    aliases: List[str],
    severity_model: str,
    default_measurement_slots: List[str],
    compatible_components: List[str],
    compatible_mechanisms: List[str],
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "condition_class": condition_class,
        "defect_class": defect_class,
        "aliases": aliases,
        "severity_model": severity_model,
        "default_measurement_slots": default_measurement_slots,
        "compatible_components": compatible_components,
        "compatible_mechanisms": compatible_mechanisms,
        "notes": notes,
    }


def _defect_condition_records() -> List[Dict[str, Any]]:
    return [
        _defect_condition_record(
            "DC_CRACK",
            "crack",
            ["crack", "cracking", "surface_crack"],
            "linear_extent",
            ["crack_width_mm", "crack_length_m"],
            ["external_wall", "structural_member", "parapet_wall", "balcony_slab", "wall_tile_finish"],
            ["structural_crack"],
        ),
        _defect_condition_record(
            "DC_SPALL_REBAR",
            "spall_rebar",
            ["spalling", "concrete_spall"],
            "corrosion_chain",
            ["spall_area_m2", "rebar_exposed_length_m", "ratio.rebar.section_loss"],
            # Round2 retire: generic ratio.chloride_content 已删；用 ratio.chloride_content.by_cement_weight
            ["external_wall", "structural_member", "canopy"],
            ["corrosion_spall"],
        ),
        # DEBT-049 A1（codex CoP 裁定 §3.4.2(A)(c)(iv)剥落 与 (vi)钢筋外露 分列）：
        # 露筋独立缺陷类，与 spall_rebar 强相关（剥落暴露主筋）但分槽输出；rebar_exposed_
        # length_m 量化支撑（已在 corrosion_spall 公式算）。
        _defect_condition_record(
            "DC_REBAR_EXPOSED",
            "rebar_exposed",
            ["exposed_rebar", "rebar_exposure", "bar_exposure"],
            "linear_extent",
            ["rebar_exposed_length_m", "ratio.rebar.section_loss"],
            ["external_wall", "structural_member", "canopy", "balcony_slab"],
            ["corrosion_spall"],
            "DEBT-049 A1：CoP §3.4.2(A)(c)(vi) 钢筋外露独立于剥落；§3.4.2(B)(d)(i) 凿开评估主筋锈蚀。",
        ),
        # DEBT-049 A2（codex CoP §3.4.2(A)(c)(vii) 混凝土空洞及蜂窝状）：勿映到 hollowing
        # （后者是敲击空鼓/脱层诊断态），独立混凝土施工缺陷。
        _defect_condition_record(
            "DC_HONEYCOMBING_VOID",
            "honeycombing_void",
            ["honeycombing_or_void", "honeycomb", "concrete_void"],
            "binary_present",
            [],
            ["structural_member", "balcony_slab", "parapet_wall", "external_wall"],
            ["structural_crack"],
            "DEBT-049 A2：CoP §3.4.2(A)(c)(vii) 混凝土空洞及呈蜂窝状；施工期缺陷、混凝土结构构件。",
        ),
        # DEBT-049 A2（codex CoP §3.4.2(A)(c)(ix) 毗邻楼宇间不正常地分离）：限"毗邻楼宇间/
        # 相邻结构分离"语境，勿泛化成任意裂缝/接缝分离。
        _defect_condition_record(
            "DC_ABNORMAL_SEPARATION",
            "abnormal_separation",
            ["abnormal_separation", "adjacent_building_separation"],
            "binary_present",
            [],
            ["structural_member", "external_wall"],
            ["structural_crack"],
            "DEBT-049 A2：CoP §3.4.2(A)(c)(ix) 毗邻楼宇间不正常分离；限相邻结构分离语境。",
        ),
        _defect_condition_record(
            "DC_HOLLOWING",
            "hollowing",
            ["hollowing", "hollow_sound", "delamination"],
            "composite_index",
            ["count.hammer_tapping.grid.minimum"],
            ["external_wall", "structural_member", "balcony_slab", "parapet_wall", "wall_tile_finish"],
            ["structural_crack", "assessment_origin"],
        ),
        _defect_condition_record(
            "DC_MOISTURE_STAINING",
            "moisture_staining",
            ["moisture_staining", "damp_patch", "water_stain"],
            "binary_present",
            [],
            ["external_wall", "structural_member", "parapet_wall", "balcony_slab"],
            ["structural_crack", "corrosion_spall"],
        ),
        _defect_condition_record(
            "DC_LEAKAGE",
            "leakage",
            ["leak", "water_leakage", "seepage", "waterproofing_failure"],
            "binary_present",
            [],
            ["drainage_stack", "drainage_branch", "external_wall", "balcony_slab"],
            ["drainage_fault", "structural_crack"],
            "T-06 合并 DC_WATERPROOFING_FAILURE 候选（防水层老化、破损、鼓起、搭接失败导致渗水）；MBIS §3.4.2(B), Appendix 5。",
        ),
        _defect_condition_record(
            "DC_DETACHMENT",
            "detachment",
            ["detachment", "loose_finish", "debonding", "delamination"],
            "linear_extent",
            ["spall_area_m2"],
            ["external_wall", "balcony_slab", "parapet_wall", "signboard", "canopy", "wall_tile_finish"],
            ["structural_crack", "assessment_origin"],
            "T-06 合并 DC_MASONRY_SULFATE_ATTACK 候选（砌石砌砖因可溶性硫酸盐和潮湿导致砂浆层膨胀劣化）；MBIS §5.4.3。",
        ),
        _defect_condition_record(
            "DC_LOOSE_FIXING",
            "loose_fixing",
            ["loose_fixing", "loose_fastener", "missing_fastener", "defective_fastener"],
            "binary_present",
            [],
            ["signboard", "canopy", "fire_door", "access_panel", "smoke_vent"],
            ["structural_crack", "fire_safety_deficiency"],
            "T-06 合并 DC_FASTENER_MISSING_OR_DEFECTIVE 候选（螺丝、铆钉、门铰、窗铰、喉码、锚栓缺漏或规格不足）；MBIS §3.3.2(E)-(I), §5.3.7, §5.6.4, MWIS §11.1.4-§11.1.9。",
        ),
        _defect_condition_record(
            "DC_DRAINAGE_MISCONNECTION",
            "drainage_misconnection",
            ["misconnection", "wrong_connection", "illegal_drainage_connection"],
            "binary_present",
            ["flag.drainage.misconnection_present"],
            ["drainage_stack", "drainage_branch", "floor_trap"],
            ["drainage_fault"],
        ),
        _defect_condition_record(
            "DC_DRAINAGE_BLOCKAGE",
            "drainage_blockage",
            ["blockage", "blocked_path", "blocked_drain", "obstruction"],
            "composite_index",
            ["index.drainage.blockage"],
            ["drainage_stack", "drainage_branch", "floor_trap"],
            ["drainage_fault"],
        ),
        _defect_condition_record(
            "DC_DRAINAGE_LEAKAGE",
            "drainage_leakage",
            ["drainage_leakage", "pipe_leakage", "drain_leak"],
            "binary_present",
            ["index.drainage.leakage"],
            ["drainage_stack", "drainage_branch", "floor_trap"],
            ["drainage_fault"],
        ),
        _defect_condition_record(
            "DC_UBW_PRESENT",
            "ubw_present",
            ["ubw", "unauthorized_building_work", "unauthorized_structure_present"],
            "binary_present",
            [],
            ["unauthorized_structure"],
            ["ubw_signal"],
        ),
        _defect_condition_record(
            "DC_SUBDIVIDED_SIGN",
            "subdivided_unit_sign",
            ["subdivided_unit_sign", "subdivision_indicator", "subdivided_premises_signal"],
            "count_threshold",
            [],
            ["unauthorized_structure"],
            ["ubw_signal"],
        ),
        _defect_condition_record(
            "DC_FIRE_DOOR_DEFICIENCY",
            "fire_door_deficiency",
            ["fire_door_deficiency", "defective_fire_door", "fire_door_closer_defect"],
            "binary_present",
            ["time.fire_door.self_closing.delay_sec"],
            ["fire_door", "smoke_vent"],
            ["fire_safety_deficiency"],
        ),
        _defect_condition_record(
            "DC_FIRE_STOP_DEFICIENCY",
            "fire_resisting_wall_deficiency",
            ["fire_stop_deficiency", "fire_resisting_wall_deficiency", "fire_compartment_defect"],
            "binary_present",
            [],
            ["fire_resisting_wall", "escape_route", "fire_service_installation"],
            ["fire_safety_deficiency"],
        ),
        _defect_condition_record(
            "DC_METAL_CORROSION",
            "metal_corrosion",
            ["metal_corrosion", "rusting", "steel_corrosion"],
            "corrosion_chain",
            # Round2 retire: generic ratio.chloride_content 已删；用 by_cement_weight 版替代
            ["ratio.rebar.section_loss"],
            ["structural_member", "drainage_stack", "signboard", "canopy", "fire_door", "access_panel"],
            ["corrosion_spall"],
            "MBIS §3.3.2(C)-(I), §3.4.2(A), §4.3.1, §5.4.2, §3.6.2；金属构件、钢结构、螺栓、铸铁/镀锌管、窗五金锈蚀（T-06 新增）。",
        ),
        _defect_condition_record(
            "DC_SEALANT_FAILURE",
            "sealant_failure",
            ["sealant_failure", "joint_sealant_failure", "weatherproof_sealant_failure"],
            "binary_present",
            [],
            ["external_wall", "access_panel", "balcony_slab", "parapet_wall"],
            ["structural_crack"],
            "MBIS §3.3.2(C), §3.3.2(E), §3.3.2(G), MWIS §10.5 / §11.1.10；密封剂老化、缺失、破损或密封接缝欠妥（T-06 新增）。",
        ),
        _defect_condition_record(
            "DC_GLASS_BREAKAGE",
            "glass_breakage",
            ["glass_breakage", "broken_glass", "glass_panel_damage"],
            "binary_present",
            [],
            ["access_panel", "fire_door", "smoke_vent"],
            ["structural_crack", "fire_safety_deficiency"],
            "MBIS §3.3.2(E), §3.3.2(G), §3.5.2(D), MWIS §11.1.2；玻璃嵌板破裂、缺漏或耐火玻璃损坏（T-06 新增）。",
        ),
        _defect_condition_record(
            "DC_DEFORMATION_DISPLACEMENT",
            "deformation_displacement",
            ["deformation", "displacement", "distortion", "misalignment"],
            "linear_extent",
            [],
            ["structural_member", "access_panel", "drainage_stack", "drainage_branch"],
            ["structural_crack", "drainage_fault"],
            "MBIS §3.4.2(A), §3.6.2, MWIS §10.6；构件变形、移位、弯曲、难以开关或不能关妥（T-06 新增）。",
        ),
        _defect_condition_record(
            "DC_FIRE_PROTECTION_COATING_DEFICIENCY",
            "fire_protection_coating_deficiency",
            ["fire_protection_coating_deficiency", "intumescent_coating_defect", "fire_coating_deficiency"],
            "binary_present",
            [],
            ["structural_member", "fire_resisting_wall"],
            ["fire_safety_deficiency"],
            "MBIS §5.4.2(C), §5.5.3；结构钢防火涂层损坏、厚度不足或与底层不兼容（T-06 新增）。",
        ),
    ]


def _sidecar_domain_for_slot(slot_id: str, partition: SlotPartition) -> str:
    if partition != "sidecar":
        return "boundary"
    if slot_id.startswith("artifact.report.completion"):
        return "completion"
    if slot_id.startswith("artifact.") or slot_id.startswith("reporting."):
        return "artifact"
    if slot_id.startswith("procedure."):
        return "procedure"
    if slot_id.startswith("supervision."):
        return "supervision"
    if slot_id == "duration.site_visit.interval":
        return "supervision"
    if slot_id.startswith("duration."):
        return "procedure"
    if slot_id.startswith("qual.") or slot_id.startswith("actor."):
        return "sidecar_qualifier"
    return "boundary"


def _joins_on_for_slot(slot_id: str, partition: SlotPartition, sidecar_domain: str) -> List[str]:
    if partition == "world_core":
        if slot_id.startswith("building."):
            return ["world_id", "building_id"]
        return ["world_id", "fragment_id", "component_id", "slot_id"]
    if partition == "measurement_family":
        return ["world_id", "fragment_id", "component_id", "slot_id"]
    if partition == "qualifier_taxonomy":
        return ["world_id", "slot_id"]
    if sidecar_domain in {"procedure", "supervision", "completion"}:
        return ["world_id", "building_id", "slot_id"]
    if sidecar_domain == "artifact":
        return ["world_id", "building_id", "fragment_id", "slot_id"]
    return ["world_id", "slot_id"]


def _sidecar_ownership_registry_record(entry: SlotOwnershipEntry) -> Dict[str, Any]:
    sidecar_domain = _sidecar_domain_for_slot(entry.slot_id, entry.partition)
    return {
        "sidecar_slot_id": entry.slot_id,
        "partition": entry.partition,
        "carrier": entry.carrier,
        "sidecar_domain": sidecar_domain,
        "carrier_type": sidecar_domain if entry.partition == "sidecar" else entry.partition,
        "joins_on": _joins_on_for_slot(entry.slot_id, entry.partition, sidecar_domain),
        "projection_consumable": True,
        "notes": entry.notes,
    }


def _build_registry_bundle() -> RegistryBundle:
    registries = [
        RegistryTable(
            registry_id="fragment_template_registry",
            ownership="world_core.fragment",
            key_field="fragment_template_id",
            fields=[
                "fragment_template_id",
                "building_template_id",
                "component_type",
                "location_class",
                "area_range",
                "length_range",
                "allowed_driver_profiles",
                "allowed_mechanisms",
                "measurement_branches",
                "specialized_domains",
            ],
            records=[
                {
                    # spec 草案·DEBT-049 第一波 §3：贴砖饰面 fragment（pull_off 链）。
                    "fragment_template_id": "FT_TILE_FINISH_V1",
                    "building_template_id": "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1",
                    "component_type": "wall_tile_finish",
                    "location_class": "external_wall",
                    "area_range": [2.0, 200.0],
                    "length_range": None,
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "technical_validation_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    # spec 草案·DEBT-049 第一波 §3：雨棚根部 fragment（s4_3_1_k 链）。
                    "fragment_template_id": "FT_CANOPY_ROOT_V1",
                    "building_template_id": "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
                    "component_type": "canopy",
                    "location_class": "podium_soffit",
                    "area_range": [1.0, 50.0],
                    "length_range": [1.0, 20.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["corrosion_spall"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_EXT_WALL_CRACK_COVERED_V1",
                    "building_template_id": "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
                    "component_type": "external_wall",
                    "location_class": "external_wall",
                    "area_range": [5.0, 500.0],
                    "length_range": None,
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall", "assessment_origin"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_DRAINAGE_MISCONNECTION_V1",
                    "building_template_id": "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1",
                    "component_type": "drainage_stack",
                    "location_class": "pipe_duct",
                    "area_range": [0.1, 20.0],
                    "length_range": [1.0, 100.0],
                    "allowed_driver_profiles": ["DRV_DRAINAGE_OPERATION_V1"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "measurement_branches": [
                        "coverage_sampling_measurement",
                        "technical_validation_measurement",
                    ],
                    "specialized_domains": ["drainage"],
                },
                {
                    "fragment_template_id": "FT_UBW_FIRE_SAFETY_V1",
                    "building_template_id": "BT_HK_UBW_PRONE_OLD_BLOCK_V1",
                    "component_type": "unauthorized_structure",
                    "location_class": "common_part",
                    "area_range": [1.0, 100.0],
                    "length_range": None,
                    "allowed_driver_profiles": ["DRV_ALTERATION_AND_FIRE_V1"],
                    "allowed_mechanisms": ["ubw_signal", "fire_safety_deficiency"],
                    "measurement_branches": ["coverage_sampling_measurement"],
                    "specialized_domains": ["ubw", "fire_safety"],
                },
                {
                    "fragment_template_id": "FT_RC_BEAM_SPALL_REPAIR_V1",
                    "building_template_id": "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
                    "component_type": "structural_member",
                    "location_class": "common_part",
                    "area_range": [0.5, 50.0],
                    "length_range": [0.5, 12.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["corrosion_spall", "assessment_origin"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "technical_validation_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_FACADE_MOISTURE_DETACHMENT_V1",
                    "building_template_id": "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1",
                    "component_type": "external_wall",
                    "location_class": "external_wall",
                    "area_range": [5.0, 300.0],
                    "length_range": None,
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_TRANSFER_BEAM_HOLLOWING_V1",
                    "building_template_id": "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1",
                    "component_type": "structural_member",
                    "location_class": "transfer_floor",
                    "area_range": [1.0, 50.0],
                    "length_range": [0.5, 12.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall", "assessment_origin"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                        "technical_validation_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_DRAINAGE_NETWORK_BLOCKAGE_V1",
                    "building_template_id": "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1",
                    "component_type": "drainage_stack",
                    "location_class": "service_void",
                    "area_range": [0.1, 20.0],
                    "length_range": [1.0, 50.0],
                    "allowed_driver_profiles": ["DRV_DRAINAGE_OPERATION_V1"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "measurement_branches": [
                        "coverage_sampling_measurement",
                        "technical_validation_measurement",
                    ],
                    "specialized_domains": ["drainage"],
                },
                {
                    # DEBT-049 Phase3 U5 §2.1（ball_test 结构性不可达修复，W0 物理真实性补全，rule-blind）：
                    # 前两张 drainage fragment template（MISCONNECTION/NETWORK_BLOCKAGE）均 component_type=
                    # drainage_stack → segment_type 派生（generator.py "stack" in component_type → soil_pipe）
                    # 恒 soil_pipe → §2.1 P3b（branch_connection → ball_test）永不触发。排水系统物理上本就含
                    # **支管连接**（branch connection 是真实构件、与立管并存），故补一张 component_type=
                    # drainage_branch 的 fragment template：drainage_fault 机制经此挂到 drainage_branch 组件 →
                    # segment_type 派生给 branch_connection → P3b 可达。**stack 为主 branch 为辅**（2 张 stack
                    # 模板 + 1 张 branch = 2:1）合物理比例。补的是物理构件多样性，**非为让某卡闭合**（W0 不读
                    # rule_cards/method_keys；method 选取仍由 §2.1 P1-P4 读排水物理量的总函数定）。drainage_branch
                    # 已在 component_type_registry（allowed_mechanisms=['drainage_fault']，C005 绿）+ DC_DRAINAGE_*
                    # compatible_components（C006 绿）+ MK_DRAINAGE_MISCONNECTION_V1.applicable_templates（下补）。
                    "fragment_template_id": "FT_DRAINAGE_BRANCH_BLOCKAGE_V1",
                    "building_template_id": "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1",
                    "component_type": "drainage_branch",
                    "location_class": "service_void",
                    "area_range": [0.1, 20.0],
                    "length_range": [1.0, 50.0],
                    "allowed_driver_profiles": ["DRV_DRAINAGE_OPERATION_V1"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "measurement_branches": [
                        "coverage_sampling_measurement",
                        "technical_validation_measurement",
                    ],
                    "specialized_domains": ["drainage"],
                },
                {
                    "fragment_template_id": "FT_ESCAPE_STAIR_FIRE_DEFICIENCY_V1",
                    "building_template_id": "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1",
                    "component_type": "fire_door",
                    "location_class": "escape_stair",
                    "area_range": [1.0, 20.0],
                    "length_range": None,
                    "allowed_driver_profiles": ["DRV_ALTERATION_AND_FIRE_V1"],
                    "allowed_mechanisms": ["fire_safety_deficiency", "ubw_signal"],
                    "measurement_branches": [
                        "coverage_sampling_measurement",
                        "technical_validation_measurement",
                    ],
                    "specialized_domains": ["ubw", "fire_safety"],
                },
                {
                    "fragment_template_id": "FT_REPAIR_PATCH_VALIDATION_V1",
                    "building_template_id": "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1",
                    "component_type": "structural_member",
                    "location_class": "podium_soffit",
                    "area_range": [1.0, 100.0],
                    "length_range": [0.5, 12.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["corrosion_spall", "assessment_origin"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "technical_validation_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
            ],
        ),
        RegistryTable(
            registry_id="latent_driver_registry",
            ownership="world_core.driver",
            key_field="driver_id",
            fields=["driver_id", "driver_family", "supported_domains", "field_ranges", "notes"],
            records=_latent_driver_records(),
        ),
        RegistryTable(
            registry_id="mechanism_library_registry",
            ownership="world_core.mechanism",
            key_field="mechanism_id",
            fields=["mechanism_id", "mechanism_family", "applicable_templates", "applicable_component_types", "required_driver_fields", "output_condition_classes", "surrogate_id", "notes"],
            records=[
                {
                    "mechanism_id": "MK_CRACK_RESTRAINT_CHAIN_V2",
                    "mechanism_family": "structural_crack",
                    "applicable_templates": ["FT_EXT_WALL_CRACK_COVERED_V1"],
                    "applicable_component_types": ["external_wall", "structural_member"],
                    "required_driver_fields": ["service_load_ratio", "restraint_level", "workmanship_deficit_index"],
                    "output_condition_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DEFORMATION_DISPLACEMENT"],
                    "surrogate_id": "structural_load_score",
                    "notes": "Extends a10 crack mechanism into covered-facade scope.",
                },
                {
                    "mechanism_id": "MK_CORROSION_SPALL_CHAIN_V2",
                    "mechanism_family": "corrosion_spall",
                    "applicable_templates": ["FT_RC_BEAM_SPALL_REPAIR_V1"],
                    "applicable_component_types": ["structural_member"],
                    "required_driver_fields": ["chloride_exposure_index", "carbonation_index", "moisture_ingress_index", "workmanship_deficit_index"],
                    "output_condition_classes": ["DC_SPALL_REBAR", "DC_DETACHMENT", "DC_METAL_CORROSION"],
                    "surrogate_id": "corrosion_score",
                    "notes": "Feeds both damage geometry and repair validation branches.",
                },
                {
                    "mechanism_id": "MK_DRAINAGE_MISCONNECTION_V1",
                    "mechanism_family": "drainage_fault",
                    "applicable_templates": ["FT_DRAINAGE_MISCONNECTION_V1", "FT_DRAINAGE_NETWORK_BLOCKAGE_V1", "FT_DRAINAGE_BRANCH_BLOCKAGE_V1"],
                    "applicable_component_types": ["drainage_stack", "drainage_branch"],
                    "required_driver_fields": ["drainage_fault_propensity", "maintenance_deficit", "workmanship_deficit_index"],
                    "output_condition_classes": ["DC_DRAINAGE_MISCONNECTION", "DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE"],
                    "surrogate_id": "drainage_misconnection_score",
                    "notes": "Introduces drainage network fault semantics.",
                },
                {
                    "mechanism_id": "MK_UNAUTHORIZED_ADDITION_V1",
                    "mechanism_family": "ubw_signal",
                    "applicable_templates": ["FT_UBW_FIRE_SAFETY_V1"],
                    "applicable_component_types": ["unauthorized_structure"],
                    "required_driver_fields": ["alteration_propensity", "workmanship_deficit_index", "maintenance_deficit"],
                    "output_condition_classes": ["DC_UBW_PRESENT", "DC_SUBDIVIDED_SIGN"],
                    "surrogate_id": "ubw_alteration_score",
                    "notes": "Carries UBW and subdivided-unit indicators.",
                },
                {
                    "mechanism_id": "MK_FIRE_DOOR_DEFICIENCY_V1",
                    "mechanism_family": "fire_safety_deficiency",
                    "applicable_templates": ["FT_UBW_FIRE_SAFETY_V1", "FT_ESCAPE_STAIR_FIRE_DEFICIENCY_V1"],
                    "applicable_component_types": ["fire_door", "fire_resisting_wall", "escape_route", "smoke_vent", "fire_service_installation", "unknown_fire_component"],
                    "required_driver_fields": ["fire_safety_deficit_index", "maintenance_deficit"],
                    "output_condition_classes": ["DC_FIRE_DOOR_DEFICIENCY", "DC_FIRE_STOP_DEFICIENCY"],
                    "surrogate_id": "fire_deficiency_score",
                    "notes": "Physical deficiency stays in world core.",
                },
                {
                    "mechanism_id": "MK_ASSESSMENT_UNDERSTRENGTH_V1",
                    "mechanism_family": "assessment_origin",
                    "applicable_templates": ["FT_EXT_WALL_CRACK_COVERED_V1", "FT_RC_BEAM_SPALL_REPAIR_V1", "FT_TRANSFER_BEAM_HOLLOWING_V1", "FT_REPAIR_PATCH_VALIDATION_V1"],
                    "applicable_component_types": ["external_wall", "structural_member"],
                    "required_driver_fields": ["service_load_ratio", "moisture_ingress_index", "chloride_exposure_index", "carbonation_index"],
                    "output_condition_classes": ["DC_CRACK", "DC_SPALL_REBAR", "DC_HOLLOWING"],
                    "surrogate_id": "fsp_loss_score",
                    "notes": "Supports FSP/core-sample branches without using rule thresholds.",
                },
            ],
        ),
        # measurement_surrogate_registry 已删（D02-5 决策）：
        # 该 registry 的 measurement_slots 字段（crack_width_mm / crack_length_m /
        # spall_area_m2 / rebar_exposed_length_m）已并入 technical_measurement_registry；
        # surrogate→mechanism 关联由 mechanism_library_registry.surrogate_id 字段承担。
        # ⚠️ npr 归属 W2（详见 W2 规格 06 §3 + W0 规格 02 §1 第 7 分组注 1）。
        # worldgen runtime 加载 npr records 是 orchestrator 性质（同
        # `run_worldgenerator_fullcoverage_framework_v2` 主入口跨 W0+W1+W2 三层编排），
        # schema 字段 + records 内容业务依据 source-of-truth 在 W2 端。
        RegistryTable(
            registry_id="normative_projection_registry",
            ownership="projection.binding",
            key_field="projection_registry_id",
            fields=[
                "projection_registry_id",
                "projection_family",
                "applicability_predicates",
                "required_world_core_slots",
                "required_measurement_slots",
                "required_qualifier_slots",
                "required_sidecar_interfaces",
                "rule_ids",
                "basis_template_ids",
                "conflict_group",
                "domain_buckets",
            ],
            records=_projection_registry_records(),
        ),
        RegistryTable(
            registry_id="building_template_registry",
            ownership="world_core.building",
            key_field="building_template_id",
            fields=["building_template_id", "building_use", "structure_type", "storey_count_range", "primary_materials", "component_graph_template_ids", "notes"],
            records=[
                # T-30 pro 派活 (2026-05-12) 替换 mvp 5 条野生为 15 条 HK archetype，spec 03 §4.8 收录
                {
                    "building_template_id": "BT_HK_TONG_LAU_MIXED_USE_MASONRY_V1",
                    "building_use": "composite",
                    "structure_type": "masonry",
                    "storey_count_range": [3, 8],
                    "primary_materials": ["clay_brick", "masonry_plaster", "plaster_finish", "timber_window", "cast_iron"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §1.3, §3.3, §3.4, §3.6, §3.7; old tong lau / masonry shop-house with residential upper floors.",
                },
                {
                    "building_template_id": "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1",
                    "building_use": "residential",
                    "structure_type": "rc_frame",
                    "storey_count_range": [5, 12],
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "tile_finish", "aluminium_window", "cast_iron"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.3, §3.4, §3.5, §3.6; 1950-1970s walkup residential blocks.",
                },
                {
                    "building_template_id": "BT_HK_MASS_HOUSING_RC_WALL_V1",
                    "building_use": "residential",
                    "structure_type": "rc_wall",
                    "storey_count_range": [8, 45],
                    "primary_materials": ["reinforced_concrete", "precast_concrete", "plaster_finish", "upvc_drainage", "steel_fire_doors"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.1.2, §3.4, §3.5, §3.6; public housing / HOS / high-density residential slab or tower blocks.",
                },
                {
                    "building_template_id": "BT_HK_PRIVATE_RESIDENTIAL_TOWER_RC_V1",
                    "building_use": "residential",
                    "structure_type": "rc_frame",
                    "storey_count_range": [20, 70],
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "aluminium_window", "upvc_drainage", "steel_fire_doors"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §1.3, §3.3, §3.4, §3.5, §3.6; modern private residential towers.",
                },
                {
                    "building_template_id": "BT_HK_NT_VILLAGE_LOWRISE_RC_V1",
                    "building_use": "residential",
                    "structure_type": "rc_frame",
                    "storey_count_range": [1, 3],
                    "primary_materials": ["reinforced_concrete", "concrete_drain", "plaster_finish", "aluminium_window", "metal_gate"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.3, §3.4, §3.6, §3.7; NT village house / lowrise residential edge scenarios.",
                },
                {
                    "building_template_id": "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
                    "building_use": "composite",
                    "structure_type": "rc_frame",
                    "storey_count_range": [15, 60],
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "tile_finish", "aluminium_window", "steel_fire_doors"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §1.3, §3.3, §3.4, §3.5; urban residential/commercial/F&B mixed-use towers (replaces mvp BT_MIXED_USE_TOWER_V1).",
                },
                {
                    "building_template_id": "BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1",
                    "building_use": "composite",
                    "structure_type": "rc_frame",
                    "storey_count_range": [3, 18],
                    "primary_materials": ["reinforced_concrete", "upvc_drainage", "cast_iron", "concrete_drain", "metal_gate"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.6.1, §3.6.2, §5.6.1-§5.6.5; podium / service-lane / pipe-duct / drainage-dominant composite (replaces mvp BT_PODIUM_WITH_SERVICE_LANES_V1).",
                },
                {
                    "building_template_id": "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1",
                    "building_use": "composite",
                    "structure_type": "rc_frame",
                    "storey_count_range": [15, 50],
                    "primary_materials": ["reinforced_concrete", "polymer_render", "aluminium_window", "curtain_wall_glazing", "stainless_steel_pipe"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.3.2(B)-(G), §3.4.2(A), §5.3, §5.4; coastal / high-exposure composite towers (replaces mvp BT_COASTAL_COMPOSITE_TOWER_V1).",
                },
                {
                    "building_template_id": "BT_HK_UBW_PRONE_OLD_BLOCK_V1",
                    "building_use": "composite",
                    "structure_type": "rc_frame",
                    "storey_count_range": [5, 20],
                    "primary_materials": ["reinforced_concrete", "cold_formed_steel", "metal", "timber", "upvc_drainage"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.5.2(E), §3.6.2(B), §3.7.1-§3.7.3; old blocks with rooftop/podium/external-wall additions or subdivided-unit signs.",
                },
                {
                    "building_template_id": "BT_HK_OFFICE_CURTAIN_WALL_STEEL_V1",
                    "building_use": "commercial",
                    "structure_type": "steel",
                    "storey_count_range": [15, 70],
                    "primary_materials": ["structural_steel_section", "intumescent_coating", "curtain_wall_glazing", "curtain_wall_aluminium_frame", "fire_rated_glass"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.3.1(a)(v), §3.3.2(G), §3.4, §3.5.2(D), §5.3.4, §5.4.2; glass curtain-wall office towers.",
                },
                {
                    "building_template_id": "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1",
                    "building_use": "commercial",
                    "structure_type": "composite_structure",
                    "storey_count_range": [20, 65],
                    "primary_materials": ["reinforced_concrete", "prestressed_concrete", "steel_transfer_beam", "cementitious_patch_mortar", "epoxy_resin_repair"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.4.1, §3.4.2(C), §4.3, §5.4.1, Appendix 5; transfer-plate office towers (replaces mvp BT_TRANSFER_PLATE_OFFICE_TOWER_V1; same primary key).",
                },
                {
                    "building_template_id": "BT_HK_COMMERCIAL_ASSEMBLY_MARKET_PODIUM_V1",
                    "building_use": "commercial",
                    "structure_type": "rc_frame",
                    "storey_count_range": [2, 12],
                    "primary_materials": ["reinforced_concrete", "fire_resistant_partition_wall", "steel_fire_doors", "fire_rated_glass", "metal_gate"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.5.1, §3.5.2(B)-(F), §5.5; commercial / assembly / market / cinema podium for fire-compartment scenarios.",
                },
                {
                    "building_template_id": "BT_HK_INDUSTRIAL_FACTORY_BLOCK_RC_V1",
                    "building_use": "industrial",
                    "structure_type": "rc_frame",
                    "storey_count_range": [5, 25],
                    "primary_materials": ["reinforced_concrete", "metal_louver_fin", "cast_iron", "galvanized_steel_pipe", "steel_fire_doors"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.4, §3.5.2(F), §3.6.2(B), §5.6; industrial / factory / creative-space conversion blocks.",
                },
                {
                    "building_template_id": "BT_HK_WAREHOUSE_LOGISTICS_STEEL_V1",
                    "building_use": "industrial",
                    "structure_type": "steel",
                    "storey_count_range": [1, 8],
                    "primary_materials": ["structural_steel_section", "intumescent_coating", "metal", "galvanized_steel_pipe", "metal_gate"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.4.1, §3.4.2(A), §3.5, §5.4.2; lowrise warehouse / logistics centres in steel structure.",
                },
                {
                    "building_template_id": "BT_HK_INSTITUTIONAL_RC_BLOCK_V1",
                    "building_use": "institutional",
                    "structure_type": "rc_frame",
                    "storey_count_range": [3, 25],
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "steel_fire_doors", "fire_resistant_partition_wall", "upvc_drainage"],
                    "component_graph_template_ids": [],
                    "notes": "MBIS §1.3, §3.1.2, §3.4, §3.5, §3.6; school / hospital / government / institutional buildings.",
                },
            ],
        ),
        RegistryTable(
            registry_id="component_type_registry",
            ownership="qualifier_taxonomy.asset",
            key_field="component_type",
            # W0-004 step 3 (2026-05-21)：加 `cover_depth_mm_range`（spec 03 §4.1 + spec 04 §5）.
            # RC 类型（material_compatibility 含 reinforced_concrete / prestressed_concrete /
            # precast_concrete 等）entry 填范围；非 RC 类型 entry 为 None（cover_depth_mm 必 null）.
            fields=["component_type", "component_class", "material_compatibility", "default_structural_role", "geometry_proxy_ranges", "cover_depth_mm_range", "allowed_location_classes", "allowed_mechanisms", "notes"],
            records=[
                {
                    "component_type": "external_wall",
                    "component_class": "external_component",
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "plaster_finish", "masonry_plaster", "polymer_render", "tile_finish", "stone_cladding", "aluminium_panel_cladding", "gfrc_panel", "paint_coating"],
                    "default_structural_role": "secondary_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [1.0, 50.0], "visible_area_m2": [1.0, 500.0], "thickness_mm": [100, 500]},
                    # RC-capable（外墙含 reinforced_concrete / plain_concrete）；外墙 RC 保护层一般 20-50mm（spec 04 §5 [10, 100] 范围内）
                    "cover_depth_mm_range": [20.0, 50.0],
                    "allowed_location_classes": ["external_wall"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall", "assessment_origin"],
                    "notes": "",
                },
                {
                    "component_type": "structural_member",
                    "component_class": "structural_component",
                    "material_compatibility": ["reinforced_concrete", "prestressed_concrete", "precast_concrete", "steel_transfer_beam", "structural_steel_section"],
                    "default_structural_role": "primary_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [0.5, 12.0], "visible_area_m2": [0.1, 50.0], "thickness_mm": [150, 1500]},
                    # RC-capable（梁/柱/transfer beam 等）；spec 03 §4.1 yaml rc_beam 例 [20.0, 75.0]
                    "cover_depth_mm_range": [20.0, 75.0],
                    "allowed_location_classes": ["common_part", "transfer_floor", "podium_soffit", "external_wall"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall", "assessment_origin"],
                    "notes": "",
                },
                {
                    "component_type": "signboard",
                    "component_class": "signboard",
                    "material_compatibility": ["metal", "aluminium_panel_cladding", "metal_anchor_fastener"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [0.5, 30.0], "visible_area_m2": [1.0, 200.0], "thickness_mm": [5, 100]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属招牌），cover_depth_mm 必 null
                    "allowed_location_classes": ["external_wall"],
                    "allowed_mechanisms": ["ubw_signal"],
                    "notes": "",
                },
                {
                    "component_type": "canopy",
                    "component_class": "canopy",
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "precast_concrete", "bituminous_membrane"],
                    "default_structural_role": "secondary_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [1.0, 20.0], "visible_area_m2": [2.0, 200.0], "thickness_mm": [80, 300]},
                    # RC-capable（canopy 含 RC / 预制混凝土）；外挑板常见 20-50mm
                    "cover_depth_mm_range": [20.0, 50.0],
                    "allowed_location_classes": ["external_wall", "podium_soffit"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "notes": "",
                },
                {
                    "component_type": "balcony_slab",
                    "component_class": "external_component",
                    "material_compatibility": ["reinforced_concrete", "tile_finish", "plaster_finish"],
                    "default_structural_role": "secondary_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [1.0, 8.0], "visible_area_m2": [2.0, 50.0], "thickness_mm": [100, 300]},
                    # RC-capable（balcony slab 含 RC）；20-50mm
                    "cover_depth_mm_range": [20.0, 50.0],
                    "allowed_location_classes": ["balcony_line", "external_wall"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "notes": "",
                },
                {
                    "component_type": "parapet_wall",
                    "component_class": "external_component",
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "masonry_plaster", "tile_finish", "plaster_finish"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [1.0, 50.0], "visible_area_m2": [1.0, 100.0], "thickness_mm": [100, 300]},
                    # RC-capable（parapet 含 RC / 素混凝土）；20-50mm
                    "cover_depth_mm_range": [20.0, 50.0],
                    "allowed_location_classes": ["roof_edge", "external_wall"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "notes": "",
                },
                {
                    "component_type": "access_panel",
                    "component_class": "inspection_access_component",
                    "material_compatibility": ["metal", "timber", "composite_material"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [0.3, 2.0], "visible_area_m2": [0.1, 4.0], "thickness_mm": [5, 50]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属 / 木 / 复合），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part", "external_wall", "pipe_duct"],
                    "allowed_mechanisms": ["ubw_signal"],
                    "notes": "",
                },
                {
                    "component_type": "drainage_stack",
                    "component_class": "drainage_component",
                    "material_compatibility": ["upvc_drainage", "pvc", "cast_iron", "galvanized_steel_pipe", "stainless_steel_pipe"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [1.0, 100.0], "visible_area_m2": [0.05, 10.0], "thickness_mm": [20, 300]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（pipe），cover_depth_mm 必 null（spec 03 §4.1 drainage_pipe 例）
                    "allowed_location_classes": ["pipe_duct", "external_wall", "service_void"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "notes": "",
                },
                {
                    "component_type": "drainage_branch",
                    "component_class": "drainage_component",
                    "material_compatibility": ["upvc_drainage", "pvc", "cast_iron", "concrete_drain", "hdpe_pipe", "vitrified_clay_pipe"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.5, 50.0], "visible_area_m2": [0.02, 5.0], "thickness_mm": [20, 200]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（pipe），cover_depth_mm 必 null
                    "allowed_location_classes": ["pipe_duct", "service_void", "private_lane"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "notes": "",
                },
                {
                    "component_type": "floor_trap",
                    "component_class": "drainage_component",
                    "material_compatibility": ["cast_iron", "upvc_drainage", "stainless_steel_pipe"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.1, 0.5], "visible_area_m2": [0.01, 0.5], "thickness_mm": [5, 50]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属 / pvc），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part", "private_premises", "pipe_duct"],
                    "allowed_mechanisms": ["drainage_fault"],
                    "notes": "",
                },
                {
                    "component_type": "fire_door",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["steel_fire_doors", "fire_resistant_glass_door", "fire_rated_glass", "metal", "timber", "composite_material"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.5, 3.0], "visible_area_m2": [0.5, 10.0], "thickness_mm": [20, 100]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（钢 / 木 / 复合），cover_depth_mm 必 null（spec 03 §4.1 fire_door 例）
                    "allowed_location_classes": ["escape_stair", "common_part"],
                    "allowed_mechanisms": ["fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "fire_resisting_wall",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["fire_resistant_partition_wall", "reinforced_concrete", "clay_brick", "intumescent_coating"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [1.0, 20.0], "visible_area_m2": [2.0, 100.0], "thickness_mm": [100, 400]},
                    # RC-capable（耐火墙含 RC 选项）；20-40mm（防火等级偏厚）
                    "cover_depth_mm_range": [20.0, 40.0],
                    "allowed_location_classes": ["common_part", "escape_stair"],
                    "allowed_mechanisms": ["fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "escape_route",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "tile_finish", "plaster_finish"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [2.0, 100.0], "visible_area_m2": [5.0, 500.0], "thickness_mm": [100, 300]},
                    # RC-capable（逃生通道墙地板含 RC）；20-40mm
                    "cover_depth_mm_range": [20.0, 40.0],
                    "allowed_location_classes": ["escape_stair", "common_part"],
                    "allowed_mechanisms": ["fire_safety_deficiency", "ubw_signal"],
                    "notes": "",
                },
                {
                    "component_type": "smoke_vent",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["metal", "aluminium_panel_cladding"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.3, 2.0], "visible_area_m2": [0.1, 5.0], "thickness_mm": [5, 50]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part", "escape_stair"],
                    "allowed_mechanisms": ["fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "fire_service_installation",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["metal", "stainless_steel_pipe", "upvc_drainage"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.5, 50.0], "visible_area_m2": [0.1, 20.0], "thickness_mm": [10, 200]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属 / pipe），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part", "escape_stair", "pipe_duct"],
                    "allowed_mechanisms": ["fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "unknown_fire_component",
                    "component_class": "fire_safety_component",
                    "material_compatibility": ["metal", "timber", "composite_material"],
                    "default_structural_role": "service_component",
                    "geometry_proxy_ranges": {"length_m": [0.1, 10.0], "visible_area_m2": [0.1, 50.0], "thickness_mm": [5, 200]},
                    "cover_depth_mm_range": None,  # 非 RC 材质（金属 / 木 / 复合），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part", "escape_stair"],
                    "allowed_mechanisms": ["fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "unauthorized_structure",
                    "component_class": "ubw",
                    "material_compatibility": ["metal", "timber", "composite_material", "cold_formed_steel", "reinforced_concrete"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [0.5, 20.0], "visible_area_m2": [1.0, 200.0], "thickness_mm": [5, 300]},
                    # RC-capable（僭建物含 RC 选项，少数）；保守 20-40mm
                    "cover_depth_mm_range": [20.0, 40.0],
                    "allowed_location_classes": ["external_wall", "roof", "common_part", "private_premises"],
                    "allowed_mechanisms": ["ubw_signal", "fire_safety_deficiency"],
                    "notes": "",
                },
                {
                    "component_type": "protective_render",
                    "component_class": "finish_system",
                    "material_compatibility": ["plaster_finish", "masonry_plaster", "polymer_render", "cementitious_patch_mortar", "paint_coating"],
                    "default_structural_role": "finish_only",
                    "geometry_proxy_ranges": {"length_m": [1.0, 50.0], "visible_area_m2": [1.0, 300.0], "thickness_mm": [5, 50]},
                    "cover_depth_mm_range": None,  # 饰面层非 RC（plaster / render / paint），cover_depth_mm 必 null
                    "allowed_location_classes": ["external_wall", "common_part"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "notes": "",
                },
                {
                    # spec 草案·DEBT-049 第一波 §3 贴砖案A（2026-07-08）：墙砖饰面
                    # 组件类，pull_off 验证义务对象（词表桥 wall_tile_finish→wall_tiles）。
                    "component_type": "wall_tile_finish",
                    "component_class": "finish_system",
                    "material_compatibility": ["tile_finish"],
                    "default_structural_role": "finish_only",
                    "geometry_proxy_ranges": {"length_m": [1.0, 50.0], "visible_area_m2": [1.0, 300.0], "thickness_mm": [5, 30]},
                    "cover_depth_mm_range": None,  # 饰面层非 RC，cover_depth_mm 必 null
                    "allowed_location_classes": ["external_wall", "common_part"],
                    "allowed_mechanisms": ["structural_crack"],
                    "notes": "engineering_estimate_DEBT049_20260708 低置信：几何范围沿 protective_render 先例。",
                },
            ],
        ),
        RegistryTable(
            registry_id="location_class_registry",
            ownership="qualifier_taxonomy.asset",
            key_field="location_class",
            fields=["location_class", "scope_class", "exposure_options", "spatial_tags", "accessibility_prior", "coverage_relevance", "notes"],
            records=[
                {"location_class": "common_part", "scope_class": "common_part", "exposure_options": ["internal", "protected"], "spatial_tags": ["common_part"], "accessibility_prior": 0.9, "coverage_relevance": True, "notes": ""},
                {"location_class": "private_premises", "scope_class": "private_premises", "exposure_options": ["internal", "protected"], "spatial_tags": ["private_premises"], "accessibility_prior": 0.3, "coverage_relevance": False, "notes": ""},
                {"location_class": "external_wall", "scope_class": "external_wall", "exposure_options": ["outdoor", "exposed", "weather_facing"], "spatial_tags": ["facade", "external_wall"], "accessibility_prior": 0.7, "coverage_relevance": True, "notes": ""},
                {"location_class": "roof", "scope_class": "roof", "exposure_options": ["outdoor", "exposed", "rain_bearing"], "spatial_tags": ["roof"], "accessibility_prior": 0.6, "coverage_relevance": True, "notes": ""},
                {"location_class": "balcony_line", "scope_class": "balcony_line", "exposure_options": ["outdoor", "semi_exposed"], "spatial_tags": ["facade", "balcony"], "accessibility_prior": 0.5, "coverage_relevance": True, "notes": ""},
                {"location_class": "roof_edge", "scope_class": "roof_edge", "exposure_options": ["outdoor", "exposed"], "spatial_tags": ["roof", "external_wall"], "accessibility_prior": 0.4, "coverage_relevance": True, "notes": ""},
                {"location_class": "podium_soffit", "scope_class": "podium_soffit", "exposure_options": ["outdoor", "sheltered"], "spatial_tags": ["canopy"], "accessibility_prior": 0.5, "coverage_relevance": True, "notes": ""},
                {"location_class": "transfer_floor", "scope_class": "transfer_floor", "exposure_options": ["internal", "protected"], "spatial_tags": ["common_part"], "accessibility_prior": 0.6, "coverage_relevance": True, "notes": ""},
                {"location_class": "pipe_duct", "scope_class": "service_space", "exposure_options": ["confined", "humid"], "spatial_tags": ["pipe_duct", "drainage_route"], "accessibility_prior": 0.4, "coverage_relevance": True, "notes": ""},
                {"location_class": "service_void", "scope_class": "service_space", "exposure_options": ["confined", "humid"], "spatial_tags": ["pipe_duct", "drainage_route"], "accessibility_prior": 0.3, "coverage_relevance": True, "notes": ""},
                {"location_class": "private_lane", "scope_class": "service_lane", "exposure_options": ["outdoor", "semi_exposed"], "spatial_tags": ["drainage_route"], "accessibility_prior": 0.7, "coverage_relevance": True, "notes": ""},
                {"location_class": "escape_stair", "scope_class": "egress_route", "exposure_options": ["internal", "protected"], "spatial_tags": ["common_part"], "accessibility_prior": 0.85, "coverage_relevance": True, "notes": ""},
            ],
        ),
        RegistryTable(
            registry_id="coverage_relation_registry",
            ownership="world_core.scope",
            key_field="coverage_relation_id",
            fields=["coverage_relation_id", "relation_type", "target_component_types", "obscuration_classes", "ratio_slot_id", "default_inspection_ratio_range", "notes"],
            records=[
                {"coverage_relation_id": "CR_IN_SCOPE", "relation_type": "scope.component.in_scope", "target_component_types": [], "obscuration_classes": ["none"], "ratio_slot_id": "", "default_inspection_ratio_range": [1.0, 1.0], "notes": ""},
                {"coverage_relation_id": "CR_EXCLUDED", "relation_type": "scope.component.excluded_from_scope", "target_component_types": [], "obscuration_classes": ["access_blocked", "unsafe_access"], "ratio_slot_id": "", "default_inspection_ratio_range": [0.0, 0.0], "notes": ""},
                {"coverage_relation_id": "CR_COVERED", "relation_type": "scope.component.covered", "target_component_types": ["signboard", "canopy", "external_wall", "parapet_wall", "balcony_slab", "structural_member", "wall_tile_finish"], "obscuration_classes": ["signboard"], "ratio_slot_id": "", "default_inspection_ratio_range": [0.0, 0.8], "notes": "DEBT-049 B1（codex CoP §3.3.2(J)(a) 被遮盖的外部及其他实体构件、§3.4.2(D) 其他被遮盖构件）：遮蔽范围广于 signboard/canopy，扩至外部/结构/实体构件；covered_by_large_signboard 保留 signboard 专项。"},
                {"coverage_relation_id": "CR_COVERED_BY_SIGNBOARD", "relation_type": "scope.component.covered_by_large_signboard", "target_component_types": ["signboard"], "obscuration_classes": ["signboard"], "ratio_slot_id": "", "default_inspection_ratio_range": [0.0, 0.6], "notes": ""},
                {
                    "coverage_relation_id": "CR_OBSCURED_BY_FINISH",
                    "relation_type": "scope.component.obscured_by_finish",
                    "target_component_types": ["external_wall", "structural_member"],
                    "obscuration_classes": ["finish_layer"],
                    "ratio_slot_id": "ratio.external_wall_area.inspected",
                    "default_inspection_ratio_range": [0.3, 1.0],
                    "notes": "DEBT-003 closed: measurement-only helper relation used to derive coverage ratios; not an adjudication fact.",
                },
                {
                    "coverage_relation_id": "CR_OBSCURED_BY_SERVICES",
                    "relation_type": "scope.component.obscured_by_services",
                    "target_component_types": ["drainage_stack", "drainage_branch"],
                    "obscuration_classes": ["access_blocked"],
                    "ratio_slot_id": "",
                    "default_inspection_ratio_range": [0.3, 1.0],
                    "notes": "DEBT-003 closed: measurement-only helper relation used to derive coverage ratios; not an adjudication fact.",
                },
                {"coverage_relation_id": "CR_EXTENDS_PRIVATE_PREMISES", "relation_type": "defect.range.extends_into_private_premises", "target_component_types": ["external_wall", "structural_member"], "obscuration_classes": ["private_premises"], "ratio_slot_id": "", "default_inspection_ratio_range": [0.0, 0.5], "notes": ""},
            ],
        ),
        RegistryTable(
            registry_id="material_system_registry",
            ownership="qualifier_taxonomy.material",
            key_field="material_system",
            fields=[
                "material_system",
                "material_class",
                "supports_rebar",
                "supports_finish_layer",
                "compatible_defect_classes",
                "aliases",
                "notes",
            ],
            records=[
                # concrete (4)
                {"material_system": "reinforced_concrete", "material_class": "concrete", "supports_rebar": True, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_SPALL_REBAR", "DC_HOLLOWING", "DC_DETACHMENT", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["rc", "r.c.", "reinforced_cement_concrete"], "notes": "MBIS §3.4.2(A), §4.3, §5.4.1, Appendix 5；结构构件、悬臂构件、转移构件及钢筋混凝土修葺核心材料。"},
                {"material_system": "plain_concrete", "material_class": "concrete", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_HOLLOWING", "DC_DETACHMENT"], "aliases": ["mass_concrete", "unreinforced_concrete"], "notes": "MBIS §3.4.1, §3.4.2(A), §5.6.3；用于非钢筋混凝土构件、排水井/明渠/沙井等混凝土实体修葺兜底。"},
                {"material_system": "prestressed_concrete", "material_class": "concrete", "supports_rebar": True, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_SPALL_REBAR", "DC_DETACHMENT"], "aliases": ["post_tensioned_concrete", "pre_tensioned_concrete", "prestressed_rc"], "notes": "MBIS §3.4.1, §3.4.2(A), §4.3；用于结构梁、板、转移构件等可能出现的预应力混凝土系统。"},
                {"material_system": "precast_concrete", "material_class": "concrete", "supports_rebar": True, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_SPALL_REBAR", "DC_HOLLOWING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["precast_rc", "precast_reinforced_concrete", "precast_concrete_panel"], "notes": "MBIS §3.3.2(C), §3.4.1, §5.3.2；覆盖预制混凝土覆盖层板、附属构件及结构预制构件。"},
                # finish (5)
                {"material_system": "plaster_finish", "material_class": "finish", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_HOLLOWING"], "aliases": ["cement_plaster", "plaster", "render_plaster"], "notes": "MBIS §3.3.1(a)(i), §3.3.2(B), §5.3.1, Appendix 4；外墙批荡及公用走廊/大堂饰面。"},
                {"material_system": "masonry_plaster", "material_class": "finish", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_HOLLOWING"], "aliases": ["plaster_on_masonry", "masonry_render", "unsupported_masonry_crack_plaster"], "notes": "MBIS §3.3.1(a)(i), §5.3.1；砌体基层上的批荡/抹灰饰面，保留 spec 中 unsupported_masonry_crack 语义。"},
                {"material_system": "polymer_render", "material_class": "finish", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_HOLLOWING"], "aliases": ["polymer_modified_render", "polymer_finish", "acrylic_render"], "notes": "MBIS §5.3.1, Appendix 4；作为外墙饰面/修葺用专利或聚合物改性饰面材料。"},
                {"material_system": "tile_finish", "material_class": "finish", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_HOLLOWING"], "aliases": ["wall_tile", "ceramic_tile", "tile_cladding_finish"], "notes": "MBIS §3.3.1(a)(i), §3.3.2(B), §5.3.1, Appendix 4；墙砖/瓦片饰面、拉拔测试对象。"},
                {"material_system": "paint_coating", "material_class": "finish", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT"], "aliases": ["paint_finish", "protective_paint", "decorative_coating"], "notes": "MBIS §5.3.1, §5.4.4；批荡/瓦片修葺后恢复原有饰面，及钢构件防护涂层维护的通用涂层入口。"},
                # masonry (3)
                {"material_system": "clay_brick", "material_class": "masonry", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["brickwork", "brick_masonry", "fired_clay_brick"], "notes": "MBIS §5.4.3；砌砖结构、砌体墙、分隔墙及相关实体构件。"},
                {"material_system": "concrete_block", "material_class": "masonry", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["blockwork", "cmu", "hollow_block", "aerated_concrete_block"], "notes": "MBIS §3.4.1, §5.4.3；砌体/分隔墙材料兜底，覆盖空心砖、混凝土砌块及加气混凝土砌块工程语义。"},
                {"material_system": "stone_masonry", "material_class": "masonry", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["rubble_masonry", "ashlar_masonry", "stonework"], "notes": "MBIS §5.4.3；砌石构筑物、硫酸盐侵蚀、局部重建或抗硫酸盐水泥修葺。"},
                # structural_steel (3)
                {"material_system": "structural_steel_section", "material_class": "structural_steel", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_STOP_DEFICIENCY", "DC_METAL_CORROSION", "DC_FIRE_PROTECTION_COATING_DEFICIENCY"], "aliases": ["structural_steel", "steel_section", "hot_rolled_steel"], "notes": "MBIS §3.4.2(A), §4.3.1, §5.4.2；结构钢构件、连接、焊接测试及防火保护。"},
                {"material_system": "steel_transfer_beam", "material_class": "structural_steel", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_STOP_DEFICIENCY", "DC_METAL_CORROSION", "DC_FIRE_PROTECTION_COATING_DEFICIENCY", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["transfer_steel_beam", "legacy_steel_transfer_beam"], "notes": "MBIS §3.4.2(C), §5.4.2；当前代码 legacy key，语义上是钢转移梁/构件材料系统而非纯材料名。"},
                {"material_system": "cold_formed_steel", "material_class": "structural_steel", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_UBW_PRESENT"], "aliases": ["light_gauge_steel", "cold_rolled_steel", "cfs"], "notes": "MBIS §3.3.1(a)(vi), §3.7；外墙附属物、支架、轻型僭建构筑物及金属支承系统。"},
                # metal_generic (3)
                {"material_system": "metal_anchor_fastener", "material_class": "metal_generic", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["fixing", "anchor", "metal_fixing", "metal_fastener", "bolt_screw_rivet"], "notes": "MBIS §3.3.2(C)-(I), §5.3.7, §5.6.4；覆盖锚固件、嵌固件、螺丝、螺栓、铆钉、喉码固定件。"},
                {"material_system": "metal_louver_fin", "material_class": "metal_generic", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["metal_louvre", "metal_louver", "metal_fin", "grille", "metal_grille"], "notes": "MBIS §3.3.1(a)(ii), §3.3.2(D), §5.3.3；鰭状饰件、栅档及金属百叶窗。"},
                {"material_system": "metal", "material_class": "metal_generic", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_DOOR_DEFICIENCY", "DC_UBW_PRESENT"], "aliases": ["generic_metal", "metal_generic", "unspecified_metal"], "notes": "Spec 03 fire_door material_compatibility legacy key；MBIS §3.3 外部金属附属物、§3.5 防火门、§3.7 僭建物兜底。"},
                # timber_composite (2)
                {"material_system": "timber", "material_class": "timber_composite", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_DOOR_DEFICIENCY", "DC_UBW_PRESENT"], "aliases": ["wood", "generic_timber", "unspecified_timber"], "notes": "Spec 03 fire_door material_compatibility legacy key；MBIS §3.5 防火门及 §3.7 僭建/附属构件材料兜底。"},
                {"material_system": "composite_material", "material_class": "timber_composite", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_DOOR_DEFICIENCY", "DC_UBW_PRESENT"], "aliases": ["composite", "frp_composite", "unspecified_composite"], "notes": "Spec 03 fire_door material_compatibility legacy key；覆盖复合防火门、复合面板、FRP/GRP 附属物等。"},
                # cladding_glazing (5)
                {"material_system": "stone_cladding", "material_class": "cladding_glazing", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_HOLLOWING", "DC_LOOSE_FIXING"], "aliases": ["stone_panel", "stone_covering", "stone_facing"], "notes": "MBIS §3.3.1(c)(i), §3.3.2(C), §5.3.2；公用走廊/大堂石材覆盖层及外墙覆盖层板。"},
                {"material_system": "curtain_wall_glazing", "material_class": "cladding_glazing", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_STOP_DEFICIENCY", "DC_GLASS_BREAKAGE", "DC_SEALANT_FAILURE", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["curtain_wall_glass", "glass_curtain_wall", "curtain_wall_panel_glazing"], "notes": "MBIS §3.3.1(a)(v), §3.3.2(G), §5.3.4；幕墙玻璃嵌板、渗漏、挡火物及锁闩/窗铰问题。"},
                {"material_system": "aluminium_panel_cladding", "material_class": "cladding_glazing", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_SEALANT_FAILURE"], "aliases": ["aluminum_panel_cladding", "aluminium_cladding", "metal_panel_cladding"], "notes": "MBIS §3.3.2(C), §5.3.2；金属覆盖层板、嵌板、接缝、锚固及金属架。"},
                {"material_system": "gfrc_panel", "material_class": "cladding_glazing", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING"], "aliases": ["grc_panel", "glass_fibre_reinforced_concrete_panel", "glass_fiber_reinforced_concrete_panel"], "notes": "MBIS §3.3.1(a)(vii), §3.3.2(C), §5.3.2；外部覆盖层/装饰构件中常见的 GRC/GFRC 面板系统。"},
                {"material_system": "glass_balustrade_panel", "material_class": "cladding_glazing", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_GLASS_BREAKAGE"], "aliases": ["glass_panel", "balustrade_glass", "guarding_glass_panel"], "notes": "MBIS §3.3.2(E), §3.3.2(G)；防护栏障、扶栏、护墙、栏杆及幕墙玻璃嵌板。"},
                # window_door (6)
                {"material_system": "aluminium_window", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_METAL_CORROSION", "DC_SEALANT_FAILURE", "DC_GLASS_BREAKAGE", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["aluminum_window", "aluminium_framed_window", "aluminum_framed_window"], "notes": "MWIS §8.3, §10.6, §11.1；当前代码 key，覆盖铝窗窗框、窗扇、窗铰、铆钉/螺丝及玻璃嵌板。"},
                {"material_system": "upvc_window", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING"], "aliases": ["pvc_window", "plastic_window"], "notes": "MWIS §8.3, §10.5, §11.1；非铝窗但属强制验窗覆盖的窗户材料系统。"},
                {"material_system": "timber_window", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING"], "aliases": ["wooden_window", "wood_window"], "notes": "MWIS §8.3, §10.5, §11.1；旧楼常见木窗系统，安全性缺陷以松脱、变形、渗漏为主。"},
                {"material_system": "steel_window", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_METAL_CORROSION", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["metal_window", "steel_framed_window"], "notes": "MWIS §8.3, §10.5, §11.1；旧式钢窗/金属窗框系统。"},
                {"material_system": "curtain_wall_aluminium_frame", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_LEAKAGE", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_FIRE_STOP_DEFICIENCY", "DC_SEALANT_FAILURE", "DC_METAL_CORROSION"], "aliases": ["curtain_wall_frame", "aluminum_curtain_wall_frame", "aluminium_curtain_wall_frame"], "notes": "MBIS §3.3.2(G), §5.3.4；幕墙铝框、可开启窗、锁闩把手、窗铰及挡火物接口。"},
                {"material_system": "metal_gate", "material_class": "window_door", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["manual_metal_gate", "electric_metal_gate", "metal_rolling_gate"], "notes": "MBIS §3.3.1(c)(ii), §3.3.2(I), §5.3.6；楼宇围墙/入口手动或电动金属闸。"},
                # fire_safety (5)
                {"material_system": "steel_fire_doors", "material_class": "fire_safety", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_FIRE_DOOR_DEFICIENCY", "DC_FIRE_STOP_DEFICIENCY", "DC_DETACHMENT", "DC_LOOSE_FIXING"], "aliases": ["steel_fire_door", "metal_fire_door", "fire_rated_steel_door"], "notes": "MBIS §3.5.2(D), §5.5.3；当前代码 key，防火门门铰、自闭装置、门扇及耐火效能不足。"},
                {"material_system": "fire_resistant_glass_door", "material_class": "fire_safety", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_FIRE_DOOR_DEFICIENCY", "DC_FIRE_STOP_DEFICIENCY", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_GLASS_BREAKAGE"], "aliases": ["fire_rated_glass_door", "fire_resistant_glazed_door"], "notes": "MBIS §3.5.2(D), §5.5.3；耐火玻璃门、玻璃嵌板及门五金。"},
                {"material_system": "fire_rated_glass", "material_class": "fire_safety", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_FIRE_DOOR_DEFICIENCY", "DC_FIRE_STOP_DEFICIENCY", "DC_DETACHMENT", "DC_LOOSE_FIXING", "DC_GLASS_BREAKAGE"], "aliases": ["fire_resistant_glass", "wired_glass_panel", "fire_glass"], "notes": "MBIS §3.5.2(D), §5.5.3；防火门或耐火结构中的耐火玻璃/金属丝网玻璃嵌板。"},
                {"material_system": "fire_resistant_partition_wall", "material_class": "fire_safety", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_FIRE_STOP_DEFICIENCY"], "aliases": ["fire_rated_partition", "fire_resisting_wall", "fire_compartment_wall"], "notes": "MBIS §3.5.2(D), §5.5.3；楼梯/防护门廊围封墙、防火间墙、楼层防火分隔。"},
                {"material_system": "intumescent_coating", "material_class": "fire_safety", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DETACHMENT", "DC_FIRE_STOP_DEFICIENCY", "DC_FIRE_PROTECTION_COATING_DEFICIENCY"], "aliases": ["intumescent_paint", "fire_protection_coating", "structural_steel_fire_coating"], "notes": "MBIS §5.4.2(C), §5.5.3；结构钢防火物料/涂层、底漆与钢底层兼容性。"},
                # drainage_pipe (8)
                {"material_system": "upvc_drainage", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["upvc_pipe", "uPVC", "rigid_pvc_drainage"], "notes": "MBIS §3.6.1, §3.6.2, §5.6.1；当前代码 key，公用排水管、反虹吸管、通风管及立管。"},
                {"material_system": "pvc", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["pvc_pipe", "pvc_drainage", "plastic_drainage_pipe"], "notes": "Spec 03 drainage_pipe material_compatibility legacy key；MBIS §5.6.1 对膠管耐用、不易燃、防紫外线、耐腐蚀等要求。"},
                {"material_system": "cast_iron", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["cast_iron_pipe", "ci_pipe"], "notes": "Spec 03 drainage_pipe material_compatibility legacy key；MBIS §3.6.2, §5.6.1 要求铸铁管内外涂层防锈。"},
                {"material_system": "concrete_drain", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION"], "aliases": ["concrete_pipe", "precast_concrete_pipe", "concrete_drainage_pipe"], "notes": "Spec 03 drainage_pipe material_compatibility legacy key；MBIS §5.6.2 明确提到预制混凝土喉管及柔性接头。"},
                {"material_system": "hdpe_pipe", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_DEFORMATION_DISPLACEMENT"], "aliases": ["hdpe_drainage", "high_density_polyethylene_pipe"], "notes": "MBIS §5.6.1；作为耐腐蚀膠管类公用排水/通风管材料系统。"},
                {"material_system": "vitrified_clay_pipe", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION"], "aliases": ["clay_pipe", "vcp", "vitrified_clay_drain"], "notes": "MBIS §5.6.2；地下排水管中陶土管/坚硬物料喉管及柔性接头。"},
                {"material_system": "galvanized_steel_pipe", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["galvanised_steel_pipe", "gi_pipe", "galvanized_iron_pipe"], "notes": "MBIS §3.6.2, §5.6.1；旧楼金属排水/通风管及喉码、螺栓、螺母防锈要求。"},
                {"material_system": "stainless_steel_pipe", "material_class": "drainage_pipe", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_DRAINAGE_BLOCKAGE", "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_LOOSE_FIXING", "DC_METAL_CORROSION"], "aliases": ["ss_pipe", "stainless_pipe", "stainless_steel_drainage_pipe"], "notes": "MBIS §5.6.1；作为耐腐蚀金属排水/通风管系统。"},
                # waterproofing_repair (5)
                {"material_system": "cementitious_patch_mortar", "material_class": "waterproofing_repair", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_HOLLOWING", "DC_DETACHMENT"], "aliases": ["repair_mortar", "patch_repair_mortar", "cementitious_repair_mortar"], "notes": "MBIS Appendix 5 §1.1, §1.1(e)；钢筋混凝土局部修补、保护层恢复、修补砂浆应用。"},
                {"material_system": "bituminous_membrane", "material_class": "waterproofing_repair", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["asphalt_membrane", "torch_on_membrane", "bitumen_waterproofing"], "notes": "MBIS §3.4.2(B), Appendix 5；悬臂簷篷防水层及修葺后防水恢复。"},
                {"material_system": "pu_waterproof_coating", "material_class": "waterproofing_repair", "supports_rebar": False, "supports_finish_layer": True, "compatible_defect_classes": ["DC_CRACK", "DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["polyurethane_waterproof_coating", "pu_coating", "liquid_applied_membrane"], "notes": "MBIS §3.4.2(B), §5.2；悬臂构筑物、外墙/天面平台渗漏相关防水涂膜系统。"},
                {"material_system": "epoxy_resin_repair", "material_class": "waterproofing_repair", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_CRACK", "DC_LEAKAGE", "DC_DETACHMENT"], "aliases": ["epoxy_injection", "epoxy_resin", "epoxy_crack_repair"], "notes": "MBIS Appendix 5 §2；钢筋混凝土裂缝高压注入环氧树脂或低黏度聚合物树脂修葺。"},
                {"material_system": "silicone_sealant", "material_class": "waterproofing_repair", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": ["DC_MOISTURE_STAINING", "DC_LEAKAGE", "DC_DETACHMENT", "DC_SEALANT_FAILURE"], "aliases": ["sealant", "weatherproof_sealant", "joint_sealant"], "notes": "MBIS §3.3.2(C), §3.3.2(E), §3.3.2(G), MWIS §10.5, §11.1.10；覆盖层、幕墙、栏障、窗框/窗铰孔洞的密封剂。"},
                # unknown (1)
                {"material_system": "unknown_material", "material_class": "unknown", "supports_rebar": False, "supports_finish_layer": False, "compatible_defect_classes": [], "aliases": ["unknown", "unspecified_material", "material_unknown"], "notes": "Spec 03 drainage_pipe material_compatibility fallback；不假设任何缺陷兼容性，避免污染 mechanism gating。"},
            ],
        ),
        RegistryTable(
            registry_id="defect_condition_taxonomy_registry",
            ownership="qualifier_taxonomy.defect_condition",
            key_field="condition_class",
            fields=[
                "condition_class",
                "defect_class",
                "aliases",
                "severity_model",
                "default_measurement_slots",
                "compatible_components",
                "compatible_mechanisms",
                "notes",
            ],
            records=_defect_condition_records(),
        ),
        RegistryTable(
            registry_id="technical_measurement_registry",
            ownership="measurement_family.technical_validation",
            key_field="slot_id",
            fields=[
                "slot_id",
                "measurement_family",
                "value_type",
                "unit",
                "physical_bounds",
                "precision_steps",
                "method_classes",
                "aliases",
                "notes",
                # DEBT-026 (spec 04 §17 / spec 03 §4.2) typical 分布参数
                "recommended_distribution",
                "recommended_mean",
                "recommended_sigma",
                "typical_bounds",
                "distribution_source",
            ],
            records=_technical_measurement_records(),
        ),
        RegistryTable(
            registry_id="sampling_plan_registry",
            ownership="measurement_family.coverage_sampling",
            key_field="sampling_plan_id",
            fields=[
                "sampling_plan_id",
                # DEBT-020 round5 sub-task 2 (2026-05-10) chain_C_plus 新增字段：
                # plan_level / plan_intensity_distribution / total_count_formula / fragment_allocation_formula
                # （授权 spec 03 §1 sampling_plan_registry schema matrix + spec 06 §8 §9 chain 公式）
                "plan_level",
                "target_slot_ids",
                "basis_area_slot",
                "plan_intensity_distribution",
                "total_count_formula",
                "fragment_allocation_formula",
                "coverage_ratio_slot",
                # a12 lineage 兼容字段（chain plan 留 None；future 其他 plan 类型可填）
                "min_count_formula",
                "interval_formula",
                "notes",
            ],
            records=_sampling_plan_records(),
        ),
        RegistryTable(
            registry_id="verification_test_registry",
            ownership="world_core.verification",
            key_field="test_family_id",
            fields=["test_family_id", "method_class", "required_measurements", "failure_rule", "additional_test_formula", "repair_work_categories", "notes"],
            records=[
                {
                    "test_family_id": "VT_VISUAL_INSPECTION_V1",
                    "method_class": "visual_inspection",
                    "required_measurements": ["crack_width_mm", "crack_length_m", "spall_area_m2"],
                    "failure_rule": "any_condition_severity >= moderate_threshold",
                    "additional_test_formula": "",
                    "repair_work_categories": ["external_structural_repair", "facade_validation"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_HAMMER_TAPPING_V1",
                    "method_class": "hammer_tapping",
                    "required_measurements": ["count.hammer_tapping.grid.minimum"],
                    "failure_rule": "hollow_sound_fraction > 0.30",
                    "additional_test_formula": "",
                    "repair_work_categories": ["external_structural_repair", "facade_validation"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_INFRARED_SCAN_V1",
                    "method_class": "infrared",
                    "required_measurements": ["spall_area_m2"],
                    "failure_rule": "thermal_anomaly_area > 0.20 * fragment_area",
                    "additional_test_formula": "",
                    "repair_work_categories": ["facade_validation"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_DRAINAGE_CCTV_V1",
                    "method_class": "CCTV",
                    "required_measurements": ["index.drainage.blockage", "index.drainage.leakage", "flag.drainage.misconnection_present"],
                    "failure_rule": "index.drainage.blockage > 0.5 or flag.drainage.misconnection_present == True",
                    "additional_test_formula": "",
                    "repair_work_categories": ["drainage_repair", "drainage_validation"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_PULL_TEST_EXTERNAL_V1",
                    "method_class": "pull_test",
                    "required_measurements": ["rate.pull_test.per_25m2", "stress.pull_test.minimum", "count.pull_test.failed_cumulative", "strength.pull_test.reported"],
                    "failure_rule": "strength.pull_test.reported < stress.pull_test.minimum or repair_quality_index < 0.45",
                    "additional_test_formula": "additional_count = failure_count^2 - 2*failure_count + 3",
                    "repair_work_categories": ["external_structural_repair", "facade_validation"],
                    "notes": "MBIS Appendix 4 §2.3 pull-test verification.",
                },
                {
                    "test_family_id": "VT_DRAINAGE_SMOKE_TEST_V1",
                    "method_class": "smoke_test",
                    "required_measurements": ["flag.drainage.misconnection_present"],
                    "failure_rule": "smoke_detected_at_unexpected_outlet",
                    "additional_test_formula": "",
                    "repair_work_categories": ["drainage_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_DRAINAGE_WATER_TEST_V1",
                    "method_class": "water_test",
                    "required_measurements": ["index.drainage.leakage", "flag.drainage.misconnection_present"],
                    "failure_rule": "index.drainage.leakage > 0.5 or flag.drainage.misconnection_present == True",
                    "additional_test_formula": "",
                    "repair_work_categories": ["drainage_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_DRAINAGE_AIR_TEST_V1",
                    "method_class": "air_test",
                    # DEBT-049 Phase3 U5 §2.1b：从旧 index.drainage.blockage 改指新增专用观测 slot
                    # （air_test 承载体，value_num=窗口内绝对压降 mmH2O）。RI 检查 C（checks.py:1093
                    # verification_test_registry.required_measurements → technical_measurement_registry.slot_id）
                    # 恒绿（新 slot 已在 technical_measurement_registry 登记）。
                    "required_measurements": ["pressure.drainage.air_test.loss_mmH2O"],
                    "failure_rule": "pressure_loss_rate > acceptable_threshold",
                    "additional_test_formula": "",
                    "repair_work_categories": ["drainage_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_DRAINAGE_BALL_TEST_V1",
                    "method_class": "ball_test",
                    # DEBT-049 Phase3 U5 §2.1b：从旧 index.drainage.blockage 改指新增专用观测 slot
                    # （ball_test 承载体，value_bool=球通过与否）。RI 检查 C 同上恒绿。
                    "required_measurements": ["flag.drainage.ball_test.pass"],
                    "failure_rule": "ball_fails_to_pass_within_time_limit",
                    "additional_test_formula": "",
                    "repair_work_categories": ["drainage_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_MOISTURE_METER_V1",
                    "method_class": "moisture_meter",
                    "required_measurements": ["index.drainage.leakage"],
                    "failure_rule": "moisture_reading > moisture_threshold_proxy",
                    "additional_test_formula": "",
                    "repair_work_categories": ["facade_validation", "drainage_validation"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_CHAIN_DRAG_V1",
                    "method_class": "chain_drag",
                    "required_measurements": ["count.hammer_tapping.grid.minimum"],
                    "failure_rule": "hollow_sound_fraction > 0.30",
                    "additional_test_formula": "",
                    "repair_work_categories": ["external_structural_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_FIRE_DOOR_CLOSER_TEST_V1",
                    "method_class": "self_closing_test",
                    "required_measurements": ["time.fire_door.self_closing.delay_sec"],
                    "failure_rule": "time.fire_door.self_closing.delay_sec > 10.0 or door_fails_to_close_completely",
                    "additional_test_formula": "",
                    "repair_work_categories": ["fire_safety_repair"],
                    "notes": "",
                },
                {
                    "test_family_id": "VT_REPAIR_MORTAR_TEST_V1",
                    "method_class": "material_test",
                    "required_measurements": ["duration.repair_mortar.test_age", "count.repair_mortar_specimens.per_strength_property"],
                    "failure_rule": "specimen_strength < required_minimum",
                    "additional_test_formula": "",
                    "repair_work_categories": ["concrete_repair", "patch_repair"],
                    "notes": "MBIS Appendix 4 §2.4 repair mortar test.",
                },
            ],
        ),
        RegistryTable(
            registry_id="assessment_surrogate_registry",
            ownership="measurement_family.structural_assessment",
            key_field="assessment_family_id",
            fields=["assessment_family_id", "input_slots", "output_slots", "formula", "physical_bounds", "noise_model", "notes"],
            records=[
                {
                    "assessment_family_id": "AS_FSP_MEMBER_V1",
                    "input_slots": [
                        "crack_width_mm",
                        "spall_area_m2",
                        "rebar_exposed_length_m",
                    ],
                    "output_slots": [
                        "ratio.fsp.structural_performance",
                        "count.core_sample.minimum",
                        "rate.core_sample.per_concrete_volume",
                    ],
                    "formula": "fsp_true = clip(1.20 - k_condition_to_fsp_loss * max_severity - 0.10*age_norm, 0, 2)",
                    "physical_bounds": [0.0, 2.0],
                    "noise_model": "TECH_REL_GAUSS",
                    "notes": "Owns the FSP/core-sample branch from a4/a11. spec 06 §10.",
                },
            ],
        ),
        RegistryTable(
            registry_id="risk_derivation_registry",
            ownership="world_core.derived_outcome",
            key_field="risk_flag_id",
            # T-09d (D03-1) schema 全量补齐：补 input_condition_classes / input_measurement_slots /
            # formula / thresholds / unknown_policy（spec 03 §1 + §2.4 + §4.3）
            fields=[
                "risk_flag_id",
                "output_slot_id",          # D03-4 工程辅助保留
                "input_condition_classes",
                "input_measurement_slots",
                "formula",
                "thresholds",
                "unknown_policy",
                "notes",
            ],
            records=[
                {
                    "risk_flag_id": "RISK_BUILDING_SAFETY_EMERGENCY_V1",
                    "output_slot_id": "risk.building_safety.emergency",
                    "input_condition_classes": [
                        "DC_CRACK", "DC_SPALL_REBAR", "DC_HOLLOWING", "DC_DETACHMENT",
                        "DC_DEFORMATION_DISPLACEMENT",  # T-06 新增
                    ],
                    "input_measurement_slots": [
                        "crack_width_mm", "spall_area_m2", "ratio.fsp.structural_performance",
                    ],
                    "formula": "severity_index >= 0.85 or fsp_structural_performance_ratio < 0.75 or structural_impact >= 0.85",
                    "thresholds": {"severity_index": 0.85, "fsp_ratio_min": 0.75, "structural_impact_min": 0.85},
                    "unknown_policy": "not_applicable_if_inputs_missing",
                    "notes": "MBIS §3.4.2 / §4.3 building-safety emergency derivation; spec 06 §11.",
                },
                {
                    "risk_flag_id": "RISK_PUBLIC_HEALTH_DRAINAGE_V1",
                    "output_slot_id": "risk.public_health.emergency",
                    "input_condition_classes": [
                        "DC_DRAINAGE_LEAKAGE", "DC_DRAINAGE_MISCONNECTION", "DC_DRAINAGE_BLOCKAGE",
                    ],
                    "input_measurement_slots": [],
                    "formula": "public_health_risk_index >= 0.80",
                    "thresholds": {"public_health_risk_index": 0.80},
                    "unknown_policy": "false_if_no_drainage_state",
                    "notes": "MBIS §3.6.2 drainage public-health emergency derivation; spec 06 §11.",
                },
                {
                    "risk_flag_id": "RISK_PUBLIC_DANGER_UBW_V1",
                    "output_slot_id": "risk.public_danger.present",
                    "input_condition_classes": [
                        "DC_DETACHMENT", "DC_SPALL_REBAR", "DC_FIRE_DOOR_DEFICIENCY",
                        "DC_UBW_PRESENT", "DC_GLASS_BREAKAGE",  # T-06 新增 DC_GLASS_BREAKAGE
                    ],
                    "input_measurement_slots": [],
                    "formula": "max_danger_index >= 0.70",
                    "thresholds": {"max_danger_index": 0.70},
                    "unknown_policy": "unknown_if_partial",
                    "notes": "MBIS §3.4 / §3.5 / §3.7 public-danger derivation; spec 06 §11.",
                },
            ],
        ),
        RegistryTable(
            registry_id="repair_outcome_registry",
            ownership="world_core.derived_outcome",
            key_field="repair_outcome_id",
            # T-09d (D03-1) schema 全量补齐：补 input_risk_flags / input_verification_flags /
            # output_flags / formula（spec 03 §1 + §2.4）
            fields=[
                "repair_outcome_id",
                "output_slot_id",          # D03-4 工程辅助保留
                "input_risk_flags",
                "input_verification_flags",
                "output_flags",
                "formula",
                "notes",
            ],
            records=[
                {
                    "repair_outcome_id": "RO_REPAIR_REQUIRED_V1",
                    "output_slot_id": "repair.required",
                    "input_risk_flags": ["RISK_BUILDING_SAFETY_EMERGENCY_V1", "RISK_PUBLIC_DANGER_UBW_V1"],
                    "input_verification_flags": ["verification_test_failed"],
                    "output_flags": ["repair.required"],
                    "formula": "moderate_or_above_condition or any(input_risk_flags) or verification_test_failed",
                    "notes": "MBIS §5.1.2 repair triggering; spec 06 §11.",
                },
                {
                    "repair_outcome_id": "RO_SAFE_UNTIL_NEXT_CYCLE_V1",
                    "output_slot_id": "repair.outcome.safe_until_next_cycle",
                    "input_risk_flags": ["RISK_BUILDING_SAFETY_EMERGENCY_V1"],
                    "input_verification_flags": ["verification_test_failed"],
                    "output_flags": ["repair.outcome.safe_until_next_cycle"],
                    "formula": "repair_quality_index >= 0.65 and not verification_test_failed and residual_risk < 0.70",
                    "notes": "MBIS §5.1.7 / §5.3.7 / §5.4.4 completion outcome; spec 06 §11.",
                },
                {
                    "repair_outcome_id": "RO_PRE_NEXT_CYCLE_MAINTENANCE_V1",
                    "output_slot_id": "maintenance.pre_next_cycle.required",
                    "input_risk_flags": [],
                    "input_verification_flags": [],
                    "output_flags": ["maintenance.pre_next_cycle.required"],
                    "formula": "(severity_band in ['minor', 'moderate']) and not any_emergency_risk_flag",
                    "notes": "MBIS §5.6 routine maintenance; spec 06 §11.",
                },
            ],
        ),
    ]

    # sidecar_ownership_registry — RegistryTable form of SidecarContract.ownership_map (T-05a).
    # SidecarContract.ownership_map is kept for backward-compatibility (double-write transition).
    # New fields (sidecar_domain / carrier_type / joins_on / projection_consumable) will be added in T-05b.
    _sidecar_ownership_records = [
        _sidecar_ownership_registry_record(entry)
        for entry in _build_sidecar_contract().ownership_map
    ]
    registries.append(
        RegistryTable(
            registry_id="sidecar_ownership_registry",
            ownership="sidecar_boundary.ownership",
            key_field="sidecar_slot_id",
            fields=[
                "sidecar_slot_id",
                "partition",
                "carrier",
                "sidecar_domain",
                "carrier_type",
                "joins_on",
                "projection_consumable",
                "notes",
            ],
            records=_sidecar_ownership_records,
        )
    )
    registries.append(
        RegistryTable(
            registry_id="sidecar_measurement_registry",
            ownership="sidecar_boundary.measurement",
            key_field="slot_id",
            fields=[
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
            records=[
                {
                    "slot_id": "duration.notification.deadline",
                    "measurement_family": "procedure_duration",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 30],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.ri.appointment.completed",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3"],
                    "aliases": [],
                    # DEBT-020 round3 proagent (2026-05-08): RI appointment / temporary nomination
                    # 通知是短周期行政动作；电子化或资料齐全时 0-2 day，常见 2-7 day，业主协调
                    # 或假期可拖到 8-14 day。rule_card threshold ≤7 day；distribution 跨 5/5 健康。
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 4.8→4.1, sigma 2.6→1.9
                    # 让评 ≤7day 的通知期限规则合规率上抬（模拟 96.3%）。仅为标定小批量验证用。
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.1,
                    "recommended_sigma": 1.9,
                    "typical_bounds": [0, 20],
                    "distribution_source": "proagent_engineering_estimate_DEBT020_round3_2026_05_08",
                },
                {
                    "slot_id": "duration.submission.deadline",
                    "measurement_family": "procedure_duration",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 30],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.investigation.proposal.submitted",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(p)", "MBIS COP 2023 §2.1.3(r)"],
                    "aliases": [],
                    # DEBT-020 round3 proagent (2026-05-08): mixture（40% revised proposal mean=5.5,
                    # sigma=1.8 + 60% completion report/MBI4 mean=11.0, sigma=3.0）→ overall normal
                    # mean=8.8 sigma=3.7（mixture 信息损失，但 5-bin 双阈值 ≤7 / ≤14 day 都跨 5/5）。
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 8.8→5.2, sigma 3.7→1.9
                    # 单峰均值下移（权宜，理想解是真 mixture + Level 条件化, DEBT-027）；模拟合规 88.6%。
                    "recommended_distribution": "mixture_rounded_truncated_normal",  # → normal in normalize
                    "recommended_mean": 5.2,
                    "recommended_sigma": 1.9,
                    "typical_bounds": [0, 25],
                    "distribution_source": "proagent_engineering_estimate_DEBT020_round3_2026_05_08",
                },
                {
                    "slot_id": "duration.delivery.deadline",
                    "measurement_family": "procedure_duration",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.repair.prescribed.completed",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(r) - completion report / MBI4 delivery"],
                    "aliases": [],
                    # DEBT-020 round5 sub-task 5 (2026-05-10): slot 拆分语义修正后 deprecated.
                    # 用户决策原文（直接引用，不得转述）：
                    #   "duration.delivery.deadline 混了兩件不同的事——向屋宇署提交報告的期限，和同日把
                    #   副本交給業主的動作。用同一個 slot 裝導致 5-bin 全部落在 far_above，不是分佈壞了，
                    #   是 slot 語義錯了。拆成兩個 slot：duration.delivery.deadline.to_person（同日送達業主）
                    #   和 duration.delivery.deadline.to_ba（完工後向屋宇署提交），舊的
                    #   duration.delivery.deadline 標 deprecated。"
                    # 用户硬约束：W0 只动 sidecar distribution，不动 rule_card threshold 数字；
                    # 拆完后 rule_card threshold（==0 day / <=14 day）需 rule_card team 查 MBIS COP 原文确认.
                    # 保留一个 release cycle backward-compatible alias，但不再被 rule_card 直接绑定.
                    "deprecated_at": "2026-05-10",
                    "replacement_slots": [
                        "duration.delivery.deadline.to_person",
                        "duration.delivery.deadline.to_ba",
                    ],
                    "deprecation_reason": (
                        "Mixed semantics conflate (1) completion report submission to BA "
                        "(repair-completion-anchored) with (2) same-day copy delivery to the prescribed-repair "
                        "person (BA-submission-anchored). Use replacement_slots; old slot kept as backward-"
                        "compatible alias for one release cycle and SHOULD NOT be bound by rule_card any longer."
                    ),
                    # 旧 distribution 保留（让 backward-compatible 跑过去 release cycle 不爆），
                    # 但 distribution_source 标 deprecated.
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证]
                    # ⚠ 本池两条 same_day 规则仍评本旧 slot ==0（接线债, 见 regulation_attribution_report
                    #   对象4 + debt045 §5.2: 理想解是规则改绑 .to_person, 属 W2 接线, 不在标定范围）。
                    # 标定权宜：把旧 slot 分布从单峰 normal(10.5) 改为零膨胀 π0=0.87（=当日送达合规率），
                    # 尾部 1-3 天 round-truncnorm(1.5,0.7)；在当前接线下等效抬升 ==0 规则合规率（模拟 87.1%）。
                    # 接线完成后本旧 slot 应整体退役, 此标定改动一并回退。
                    "recommended_distribution": "zero_inflated_discrete",
                    "recommended_mean": 10.5,   # 留旧值供 _has_typical_distribution 完备性判定（不再生效）
                    "recommended_sigma": 5.0,
                    "typical_bounds": [0, 35],
                    "calib_zero_prob": 0.87,
                    "calib_tail_mean": 1.5,
                    "calib_tail_sigma": 0.7,
                    "distribution_source": "S2_5_calibration_2026_06_17_DEBT045_over_deprecated_slot_pending_to_person_rewire",
                },
                # DEBT-020 round5 sub-task 5 (2026-05-10) — to_person split slot
                # 授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1571-L1597
                # DEBT-020 Round 7 §2 (2026-05-11): COP §2.1.3(r) 已读到原文确认 deadline 语义，
                # PENDING_RULECARD_TEAM_COP_VERIFICATION 升级为 COP-confirmed 值.
                # 原文 quote (MBIS_CoP_2023.md §2.1.3(r), L875):
                #   "在完成樓宇的修葺後14日內，監督樓宇修葺的註冊檢驗人員須向建築事務監督呈交完工報告
                #    及指明表格（表格 MBI4）的證明書。此等文件亦須於同日送交該名由他人代為進行訂明修葺
                #    的人;"
                {
                    "slot_id": "duration.delivery.deadline.to_person",
                    "measurement_family": "procedure_duration",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 14],
                    "precision_steps": {"coarse": 1, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "artifact.report_completion_or_mbi4.submitted_to_ba",
                    "rule_basis_refs": [
                        "MBIS_CoP_2023 §2.1.3(r) - completion report / MBI4 delivery to person",
                    ],
                    "aliases": ["duration.delivery.lag.to_person_after_ba_submission"],
                    # DEBT-020 Round 7 §2 confirmed: same_day_as / ==0 calendar day relative to
                    # BA submission date (NOT repair completion date). time_anchor =
                    # repair.completion_report_and_mbi4.submitted_to_ba.
                    "rule_card_threshold": {
                        "relation": "same_day_as",
                        "operator": "==",
                        "value": 0,
                        "unit": "calendar_day",
                        "time_anchor_key": "repair.completion_report_and_mbi4.submitted_to_ba",
                        "recipient_qualifier": {
                            "actor_role_key": "owner_or_person_for_whom_prescribed_repair_is_carried_out",
                        },
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(r)",
                    "semantic_note": (
                        "completion report / MBI4 已提交或签发给 BA 的同日, deliver copy / relevant document "
                        "to the person for whom prescribed repair is carried out. "
                        "Round 7 §2 已确认 anchor = BA submission date, NOT repair completion date."
                    ),
                    "recommended_distribution": "zero_inflated_discrete",  # → normal in normalize
                    "recommended_mean": 0.45,
                    "recommended_sigma": 1.15,
                    "typical_bounds": [0, 3],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                # DEBT-020 round5 sub-task 5 (2026-05-10) — to_ba split slot
                # 授权：`回复.md`:L1599-L1619
                # DEBT-020 Round 7 §2 (2026-05-11): COP §2.1.3(r) confirmed <= 14 day after
                # repair.prescribed.completed.
                {
                    "slot_id": "duration.delivery.deadline.to_ba",
                    "measurement_family": "procedure_duration",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.repair.prescribed.completed",
                    "rule_basis_refs": [
                        "MBIS_CoP_2023 §2.1.3(r) - completion report / MBI4 BA submission within 14 days after repair completion",
                    ],
                    "aliases": [],
                    # DEBT-020 Round 7 §2 confirmed: <=14 day after repair.prescribed.completed.
                    "rule_card_threshold": {
                        "measure_key": "duration.submission.deadline",
                        "operator": "<=",
                        "value": 14,
                        "unit": "day",
                        "time_anchor_key": "repair.prescribed.completed",
                        "recipient_qualifier": {
                            "actor_role_key": "ba",
                        },
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(r)",
                    "semantic_note": (
                        "prescribed repair completion 后，completion report / MBI4 提交 Building Authority 的 duration. "
                        "完工后整理测试记录、相片、签署和 completion package 常在 5-14 days；"
                        "大型修葺或记录滞后可到 15-30 days."
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 10.5,
                    "recommended_sigma": 5.0,
                    "typical_bounds": [0, 35],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                {
                    "slot_id": "duration.site_visit.interval",
                    "measurement_family": "supervision_interval",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [1, 30],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "supervision",
                    "carrier_slot": "supervision.site_visit.performed",
                    "rule_basis_refs": ["MBIS COP 2023 §6.4.1", "MBIS COP 2023 Appendix VI Table 2"],
                    "aliases": [],
                    # DEBT-020 round3 proagent (2026-05-08) + audit finding:
                    # rule_card 当前 measure_key=duration.site_visit.interval 的 threshold_regimes 为 0，
                    # 但 MBIS COP §6.4.1 + Appendix VI Table 2 明确：
                    #   Level 1 representative weekly inspection (≤7 day)
                    #   Level 2 representative fortnightly inspection (≤14 day)
                    # proagent 建议 rule_card 编辑团队补两条 qualifier threshold；详见 DEBT-027。
                    # distribution: mixture（60% Level 1 weekly mean=6.5 sigma=1.8 + 40% Level 2
                    # fortnightly mean=13.0 sigma=2.2）→ overall normal mean=9.1 sigma=3.7。
                    # mixture 信息损失，但 5-bin ≤7 / ≤14 day 双阈值都跨 5/5。
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 9.1→5.2, sigma 3.7→1.9
                    # 单峰均值下移（权宜，理想解是真 mixture + Level 条件化, DEBT-027）；模拟合规 88.2%。
                    "recommended_distribution": "mixture_rounded_truncated_normal",  # → normal in normalize
                    "recommended_mean": 5.2,
                    "recommended_sigma": 1.9,
                    "typical_bounds": [2, 21],
                    "distribution_source": "proagent_engineering_estimate_DEBT020_round3_2026_05_08_audit_finding_rulecard_missing_threshold",
                },
                # DEBT-025 closure (2026-05-06)：5 个 inspection-execution slot 入 sidecar
                # （非物理世界测量；rule_card 有阈值但 user 审计判定不应入 W0 technical_measurement）
                # 见 audit_report.md§关键差集 7 + AUDIT_20260506_missing_w0_slots.md§F2/W0_or_sidecar 表
                {
                    "slot_id": "ratio.external_wall_area.inspected",
                    "measurement_family": "inspection_coverage",
                    "value_type": "float",
                    "unit": "ratio",
                    "physical_bounds": [0.0, 1.0],
                    "precision_steps": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
                    "carrier_domain": "inspection_execution",
                    "carrier_slot": "inspection.external_wall.coverage_evidence",
                    "rule_basis_refs": ["MBIS COP 2023 §3.3.2(J)(c)"],
                    "aliases": ["external_wall_inspected_ratio"],
                    # DEBT-020/026 round1 proagent: RI 围绕代表性覆盖率执行
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 0.40→0.46, sigma
                    # 0.15→0.095, 下界 0.20→0.29（抬高代表性覆盖率合规面）；模拟合规 99.1%。
                    # ⚠ 下界抬到 0.29 后 5-bin far_below 档会变薄, 重投影后须重跑 regime 健康检查。
                    "recommended_distribution": "truncated_normal",
                    "recommended_mean": 0.46,
                    "recommended_sigma": 0.095,
                    "typical_bounds": [0.29, 0.75],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                {
                    "slot_id": "ratio.covered_structure_area.inspected",
                    "measurement_family": "inspection_coverage",
                    "value_type": "float",
                    "unit": "ratio",
                    "physical_bounds": [0.0, 1.0],
                    "precision_steps": {"coarse": 0.05, "standard": 0.01, "fine": 0.005},
                    "carrier_domain": "inspection_execution",
                    "carrier_slot": "inspection.structural.coverage_evidence",
                    "rule_basis_refs": ["MBIS COP 2023 §3.4.2(C)(a)", "MBIS COP 2023 §3.4.2(B)(a)"],
                    "aliases": ["covered_structure_inspected_ratio"],
                    # DEBT-020/026 round1 proagent: 双成分 mixture（covered/beam-slab + pure cantilever）
                    # 当前骨架 mixture_truncated_normal → normal(overall mean=0.55, sigma=0.25)
                    # 真 mixture 派生留待未来扩展（未实现 → loss of bimodal info）
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] 恢复声明过的质量点 mixture:
                    # 82% 质量点 1.0（纯悬臂 100% 全查, 符合 §3.4.2 法规预期）, 其余 18% 走连续成分
                    # truncnorm(0.56, 0.23)。这是 registry 注释里早已声明被坍缩的双峰形状的恢复, 非新形状。
                    # 模拟该 slot 合规 82.3%。上界 typical_bounds 保 1.00 让质量点过 clip。
                    "recommended_distribution": "mixture_truncated_normal",
                    "recommended_mean": 0.55,   # overall 均值留旧值供完备性判定（mixture 时不直接生效）
                    "recommended_sigma": 0.25,
                    "typical_bounds": [0.22, 1.00],
                    "calib_mass_point_prob": 0.82,
                    "calib_mass_point_value": 1.0,
                    "calib_component_mean": 0.56,
                    "calib_component_sigma": 0.23,
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                {
                    "slot_id": "count.canopy.check_locations.minimum",
                    "measurement_family": "inspection_plan",
                    "value_type": "int",
                    "unit": "count",
                    "physical_bounds": [0, 50],
                    "precision_steps": {"coarse": 1, "standard": 1, "fine": 1},
                    "carrier_domain": "inspection_execution",
                    "carrier_slot": "inspection.canopy.check_plan",
                    "rule_basis_refs": ["MBIS COP 2023 §3.4.2(B)(e)"],
                    "aliases": ["canopy_check_locations_minimum"],
                    # DEBT-020/026 round1 proagent: 独立 cantilever canopy 开口检查点常见 2-6
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 3.2→3.9, sigma
                    # 1.5→1.25（抬高检查点数量满足最小数量阈值）；模拟合规 97.3%。
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 3.9,
                    "recommended_sigma": 1.25,
                    "typical_bounds": [0, 10],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                {
                    "slot_id": "length.canopy.check_location.interval",
                    "measurement_family": "inspection_plan",
                    "value_type": "float",
                    "unit": "m",
                    "physical_bounds": [0.0, 100.0],
                    "precision_steps": {"coarse": 0.5, "standard": 0.1, "fine": 0.05},
                    "carrier_domain": "inspection_execution",
                    "carrier_slot": "inspection.canopy.check_plan",
                    "rule_basis_refs": ["MBIS COP 2023 §3.4.2(B)(e)"],
                    "aliases": ["canopy_check_location_interval_m"],
                    # DEBT-020/026 round1 proagent: 雨篷检查间距按工程实际 4-7m 排点
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 5.1→4.5, sigma
                    # 1.6→1.1（收紧检查间距满足间距上限阈值）；模拟合规 91.3%。
                    "recommended_distribution": "truncated_normal",
                    "recommended_mean": 4.5,
                    "recommended_sigma": 1.1,
                    "typical_bounds": [2.0, 10.0],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
                {
                    "slot_id": "count.private_premises_access.floor_interval",
                    "measurement_family": "inspection_plan",
                    "value_type": "int",
                    "unit": "floor",
                    "physical_bounds": [1, 50],
                    "precision_steps": {"coarse": 1, "standard": 1, "fine": 1},
                    "carrier_domain": "inspection_execution",
                    "carrier_slot": "inspection.private_premises.access_plan",
                    "rule_basis_refs": ["MBIS COP 2023 §3.6.2(A)(b)-(c)"],
                    "aliases": ["private_premises_access_floor_interval"],
                    # DEBT-020/026 round1 proagent: 私人处所抽样按 2-4 层间隔；mean=3 与 threshold=3
                    # 同——proagent self_check 解释为"工程抽样周期与监管线源于同一三层竖向代表性假设"
                    # [S2.5-CALIB 标定档 2026-06-17, DEBT-045 修法①验证] mean 3.0→2.3, sigma
                    # 1.2→0.85（收紧楼层抽样间隔满足上限阈值）；模拟合规 91.7%。
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 2.3,
                    "recommended_sigma": 0.85,
                    "typical_bounds": [1, 6],
                    "distribution_source": "proagent_engineering_estimate_current_authority_round5_2026_05_10",
                },
            ],
        )
    )
    # spec 02 §1 第 19 张 registry / spec 09 §1.2 (2026-05-09 修订):
    # sidecar_bool_slot_registry — sidecar 域 bool / categorical slot 生成 schema.
    # 与 sidecar_measurement_registry 平行（数值 vs bool 双路径）；ownership / partition / carrier
    # 仍在 sidecar_ownership_registry，本表只管 generation 参数（prevalence + conditional_formula）.
    #
    # DEBT-020 Round 6 + Round 7 落地（2026-05-11）：
    # 每个 sidecar bool/enum slot record 加 7 个新字段（centered upstream conditional 公式 +
    # DAG sampling_order + Round 7 anchor 修订 + COP 章节引用 + alignment_check）.
    # 详见 round6_formulas.py + spec 06 §11.6.
    # MBI2 DAG 修订（Round 7 §0）：artifact.form.mbi2 移到 L1 (sampling_order=7)，
    # depends_on procedure.temp_ri_nomination.completed (不是 detailed_investigation slot).
    registries.append(
        RegistryTable(
            registry_id="sidecar_bool_slot_registry",
            ownership="sidecar_boundary.bool",
            key_field="slot_id",
            fields=[
                "slot_id",
                "value_type",          # "bool" | "enum"
                "enum_values",         # list[str]; bool 时为 [false, true]（隐式）
                "prevalence",          # bool: float P(true); enum: list[float] multinomial 同 enum_values 长度
                "conditional_inputs",  # list[str]：W0 state slot_id；当前阶段 marginal-only 留空
                "conditional_formula", # dict | null: DEBT-020 Round 6 centered upstream pattern
                                       # ({type: centered_sigmoid_linear/centered_softmax_per_class,
                                       #   anchor, upstream_expected, terms})
                "carrier_domain",      # procedure / supervision / artifact / qualifier
                "source_attribution",
                "aliases",
                "notes",
                # DEBT-020 Round 6/7 新增字段（spec 06 §11.6.7）：
                "sampling_order",      # int 1-45: DAG topological order
                "upstream_inputs",     # {hidden: [H.x...], sidecar: [slot_id...]} for audit
                "marginal_anchor",     # bool: float, enum: dict[class, prob]
                "anchor_source",       # str: COP §x.y.z modality + round4_baseline label
                "alignment_check",     # dict: {monte_carlo_n, observed_marginal, delta, status}
                "distribution_source", # str: proagent_engineering_estimate_current_authority_round5_2026_05_10
                "cop_section",         # str: MBIS_CoP_2023 §x.y.z primary citation
            ],
            records=[
                # DEBT-020 round4 proagent (2026-05-09) — 45 条 records 全量落地.
                # source_attribution 统一标 proagent_engineering_estimate_DEBT020_round4_2026_05_09;
                # rule_leak_self_check 详见 round4 回复.md (counterfactual 1+2 + 判定不构成 Layer 4 leak).
                # ===== A. procedure / gate (17) =====
                {
                    "slot_id": "procedure.ri.appointment.completed",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.86,
                    "conditional_inputs": ["building.metadata.building_age_years", "scope.component.in_scope", "defect.class.present"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "RI appointment 是 MBIS 启动检验的常规前置；少量未落桶.",
                },
                {
                    "slot_id": "procedure.temp_ri_nomination.completed",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.08,
                    "conditional_inputs": ["procedure.ri_role.terminated", "procedure.ri.appointment.completed", "building.metadata.configuration"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "临时 RI 提名仅在主 RI 暂时不可用 / 项目交接时出现，低频.",
                },
                {
                    "slot_id": "procedure.temp_ri_nomination.terminated",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.03,
                    "conditional_inputs": ["procedure.temp_ri_nomination.completed", "procedure.ri.appointment.completed"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "临时提名终止 < temp 提名 completed; round4 confidence=low.",
                },
                {
                    "slot_id": "procedure.ri_role.terminated",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.06,
                    "conditional_inputs": ["procedure.ri.appointment.completed", "building.metadata.configuration", "scope.component.in_scope"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "主 RI 角色终止低频但非极端事件.",
                },
                {
                    "slot_id": "procedure.supervision_representative.planned",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.66,
                    "conditional_inputs": ["repair.required", "procedure.repair.prescribed.started", "defect.class.present", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "supervision representative 与 prescribed repair / 高风险工序相关.",
                },
                {
                    # [EXP-011 设计① 2026-07-02] 监督代表"已指派"状态（rule_card 触发器按
                    # actor_role_key=ri_rep_lvl1/lvl2 求值，此前完全未建模——DEBT-040 ①b）。
                    # none=未指派；lvl1/lvl2=指派等级（CoP §2.1.3(m) 委任前≥7 日通知 BA）。
                    # 发生率：planned 0.66 × 落实率≈0.83 ⇒ 指派≈0.55，lvl1:lvl2≈7:3——
                    # 工程估值【低置信待复核】。与 planned 的一致性由 sidecar 阶段钳制
                    # 保证（planned=False ⇒ none）。sampling_order 20.5 = planned(20) 之后。
                    "slot_id": "actor.representative.assigned_role",
                    "value_type": "enum",
                    "enum_values": ["none", "ri_rep_lvl1", "ri_rep_lvl2"],
                    "prevalence": [0.45, 0.385, 0.165],
                    "conditional_inputs": ["procedure.supervision_representative.planned"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "sampling_order": 20.5,
                    "source_attribution": "engineering_estimate_EXP011_20260702_low_confidence",
                    "aliases": [], "notes": "监督代表指派状态（等级枚举）；EXP-011 设计①。",
                },
                {
                    "slot_id": "procedure.supervision_team.submitted",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.58,
                    "conditional_inputs": ["repair.required", "procedure.supervision_representative.planned", "procedure.repair.prescribed.started"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "supervision team submitted 比 representative planned 更靠后.",
                },
                {
                    "slot_id": "procedure.supervision_team.changed",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.12,
                    "conditional_inputs": ["procedure.supervision_team.submitted", "procedure.ri_role.terminated", "procedure.repair.prescribed.started"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "监督团队变更通常来自人员调动 / 工程延期；普通项目稳定.",
                },
                {
                    "slot_id": "procedure.inspection.prescribed.completed",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.74,
                    "conditional_inputs": ["procedure.ri.appointment.completed", "scope.component.in_scope", "defect.class.present"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "release_batch 主要面向 MBIS 投影场景；多数已完成 prescribed inspection.",
                },
                {
                    "slot_id": "procedure.investigation.intention_notified",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.30,
                    "conditional_inputs": ["defect.cause_or_extent.uncertain", "defect.class.present", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Detailed investigation intention 仅在 cause/extent 不确定时触发.",
                },
                {
                    "slot_id": "procedure.investigation.proposal.submitted",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.23,
                    "conditional_inputs": ["procedure.investigation.intention_notified", "defect.cause_or_extent.uncertain", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "proposal submitted 略低于 intention notified（流程漏斗）.",
                },
                {
                    "slot_id": "procedure.investigation.proposal.recognized",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.18,
                    "conditional_inputs": ["procedure.investigation.proposal.submitted", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "proposal recognized 低于 submitted（等待/退回修改/未处理）.",
                },
                {
                    "slot_id": "procedure.investigation.started",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.20,
                    "conditional_inputs": ["procedure.investigation.proposal.recognized", "defect.cause_or_extent.uncertain", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "investigation started 与 recognized 接近，反映少量先行调查.",
                },
                {
                    "slot_id": "procedure.repair.revision_required",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.18,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "artifact.proposal.repair", "defect.class.present", "scope.component.covered"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Repair revision 由现场范围变化 / 测试结果触发；少量修订常见.",
                },
                {
                    "slot_id": "procedure.repair.prescribed.started",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.55,
                    "conditional_inputs": ["repair.required", "procedure.inspection.prescribed.completed", "artifact.proposal.repair", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Inspection-only / 等待审批 / 已开工修葺的混合; 0.55 marginal.",
                },
                {
                    "slot_id": "procedure.repair.prescribed.completed",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.42,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "repair.outcome.safe_until_next_cycle", "artifact.report.completion"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Repair completed 与 completion report 同量级.",
                },
                {
                    "slot_id": "procedure.completed_work.final_inspection_performed",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.40,
                    "conditional_inputs": ["procedure.repair.prescribed.completed", "artifact.report.completion", "artifact.form.mbi4"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Final inspection 略低于 repair completed（时间差）.",
                },
                {
                    "slot_id": "procedure.rc.pre_notification_given",
                    "granularity": "building",  # spec草案·流程槽粒度语义 2026-07-08：行政一次性事件楼级采样
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.50,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "procedure.supervision_team.submitted", "artifact.proposal.repair"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "RC pre-notification 与修葺开工 / 监督安排相关.",
                },
                # ===== B. supervision (4) =====
                {
                    "slot_id": "supervision.site_visit.performed",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.80,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "repair.required", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "supervision",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "RI site visit 是监督和记录链路的核心动作.",
                },
                {
                    "slot_id": "supervision.record.completed_and_retained",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.62,
                    "conditional_inputs": ["supervision.site_visit.performed", "supervision.record.completed", "supervision.record.retained"],
                    "conditional_formula": None, "carrier_domain": "supervision",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "聚合 flag = completed (0.72) × retained_given_completed (0.85). QA: 不应大于单项.",
                },
                {
                    "slot_id": "supervision.record.completed",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.72,
                    "conditional_inputs": ["supervision.site_visit.performed", "procedure.supervision_team.submitted", "artifact.record.supervision_log_sp1"],
                    "conditional_formula": None, "carrier_domain": "supervision",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Site visit 后多数会完成监督记录; 略低于 site_visit.performed.",
                },
                {
                    "slot_id": "supervision.record.retained",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.68,
                    "conditional_inputs": ["supervision.record.completed", "artifact.record.supervision_log_sp1", "procedure.repair.prescribed.completed"],
                    "conditional_formula": None, "carrier_domain": "supervision",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Record retained 比 completed 更依赖归档/交接.",
                },
                # ===== C. artifact / evidence (20) =====
                {
                    "slot_id": "artifact.form.mbi1",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.95,
                    "conditional_inputs": ["procedure.ri.appointment.completed", "scope.component.in_scope"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBI1 立项 form; 多数 MBIS fragment 已具备.",
                },
                {
                    "slot_id": "artifact.form.mbi2",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.23,
                    "conditional_inputs": ["procedure.investigation.proposal.submitted", "procedure.investigation.intention_notified", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBI2 与 investigation phase 相关; 与 proposal submitted 接近.",
                },
                {
                    "slot_id": "artifact.form.mbi3_or_mbi3a",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.72,
                    "conditional_inputs": ["procedure.inspection.prescribed.completed", "artifact.report.inspection", "procedure.ri.appointment.completed"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBI3/3A 与 inspection report 阶段绑定.",
                },
                {
                    "slot_id": "artifact.form.mbi4",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.39,
                    "conditional_inputs": ["procedure.repair.prescribed.completed", "artifact.report.completion", "procedure.completed_work.final_inspection_performed"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBI4 属 completion phase; 与 completion report 同量级.",
                },
                {
                    "slot_id": "artifact.form.mbi5",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.07,
                    "conditional_inputs": ["procedure.ri_role.terminated", "procedure.repair.prescribed.completed", "building.metadata.configuration"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBI5 特殊状态 form; round4 confidence=low.",
                },
                {
                    "slot_id": "artifact.notice.investigation_intention",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.30,
                    "conditional_inputs": ["procedure.investigation.intention_notified", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Investigation intention notice 与 intention_notified 同步.",
                },
                {
                    "slot_id": "artifact.proposal.detailed_investigation",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.23,
                    "conditional_inputs": ["procedure.investigation.proposal.submitted", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Detailed investigation proposal 文档与 procedure flag 同步.",
                },
                {
                    "slot_id": "artifact.proposal.repair",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.57,
                    "conditional_inputs": ["repair.required", "procedure.inspection.prescribed.completed", "procedure.repair.prescribed.started"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Repair proposal 略高于 repair started（方案先行）.",
                },
                {
                    "slot_id": "artifact.proposal.repair_revision",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.17,
                    "conditional_inputs": ["procedure.repair.revision_required", "artifact.proposal.repair", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Repair revision 文档略低于 procedure.repair.revision_required.",
                },
                {
                    "slot_id": "artifact.report.inspection",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.73,
                    "conditional_inputs": ["procedure.inspection.prescribed.completed", "artifact.form.mbi3_or_mbi3a", "defect.class.present"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Inspection report 是 prescribed inspection 主要输出.",
                },
                {
                    "slot_id": "artifact.report.completion",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.40,
                    "conditional_inputs": ["procedure.repair.prescribed.completed", "procedure.completed_work.final_inspection_performed", "artifact.form.mbi4"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Completion report 与 MBI4 / final inspection 同量级.",
                },
                {
                    "slot_id": "artifact.record.inspection_log",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.78,
                    "conditional_inputs": ["procedure.inspection.prescribed.completed", "artifact.report.inspection", "supervision.site_visit.performed"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Inspection log 略高于 report presence.",
                },
                {
                    "slot_id": "artifact.record.supervision_log_sp1",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.61,
                    "conditional_inputs": ["supervision.record.completed", "procedure.supervision_team.submitted", "procedure.repair.prescribed.started"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "SP1 监督日志 < site_visit.performed; > nonconformity_sp2.",
                },
                {
                    "slot_id": "artifact.record.nonconformity_sp2",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.20,
                    "conditional_inputs": ["supervision.site_visit.performed", "verification.test.failed", "procedure.repair.revision_required", "defect.class.present"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "SP2 不符合记录 < SP1（多数监督无 nonconformity）.",
                },
                {
                    "slot_id": "artifact.record.test_or_material_witness",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.44,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "strength.pull_test.reported", "artifact.certificate.material_or_product"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Test/material witness 与 pull test / 材料验收相关.",
                },
                {
                    "slot_id": "artifact.photo.annotated",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.70,
                    "conditional_inputs": ["defect.class.present", "artifact.report.inspection", "procedure.inspection.prescribed.completed"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Annotated photo 是缺陷记录常见证据.",
                },
                {
                    "slot_id": "artifact.plan.annotated",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.64,
                    "conditional_inputs": ["scope.component.in_scope", "artifact.report.inspection", "artifact.proposal.repair"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Annotated plan 略低于 photo（简单个案可用照片定位）.",
                },
                {
                    "slot_id": "artifact.certificate.material_or_product",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.43,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "artifact.proposal.repair", "artifact.record.test_or_material_witness"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Material/product certificate 与修葺材料使用率相关.",
                },
                {
                    "slot_id": "artifact.statement.scope_and_order_coverage",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.58,
                    "conditional_inputs": ["artifact.proposal.repair", "artifact.report.completion", "scope.component.in_scope"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Scope/order coverage 声明常见于 repair / completion package.",
                },
                {
                    "slot_id": "artifact.statement.extra_works_separated",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.19,
                    "conditional_inputs": ["artifact.proposal.repair", "procedure.repair.revision_required", "defect.ubw.present"],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "Extra works separated 仅在含改善 / UBW 工程时出现; round4 confidence=low.",
                },
                # ===== D. qualifier / categorical (3) =====
                {
                    "slot_id": "qual.actor_role",
                    "value_type": "enum",
                    "enum_values": ["registered_inspector", "registered_contractor", "building_authority", "owner"],
                    "prevalence": [0.58, 0.22, 0.10, 0.10],  # round4 微调（修葺阶段 RC 略多）
                    "conditional_inputs": ["procedure.repair.prescribed.started", "procedure.inspection.prescribed.completed", "artifact.form.mbi4"],
                    "conditional_formula": None, "carrier_domain": "qualifier",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "actor role multinomial: 58% RI / 22% RC / 10% BA / 10% owner.",
                },
                {
                    "slot_id": "qual.method_class",
                    "value_type": "enum",
                    "enum_values": ["visual_inspection", "pull_test", "hammer_tapping", "drainage_cctv", "water_test", "smoke_test", "material_test", "self_closing_test"],
                    "prevalence": [0.34, 0.12, 0.22, 0.10, 0.05, 0.03, 0.09, 0.05],
                    "conditional_inputs": ["defect.class.present", "defect.drainage.blockage.present", "defect.drainage.leakage.present", "defect.fire_safety.component_deficiency.present", "repair.required"],
                    "conditional_formula": None, "carrier_domain": "qualifier",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "MBIS 方法 mix: visual + hammer 主体, pull/material 修葺验证, drainage/fire 子集.",
                },
                {
                    "slot_id": "qual.artifact_field_group",
                    "value_type": "enum",
                    "enum_values": ["form_metadata", "repair_proposal", "supervision_record", "completion_report", "evidence_photo", "evidence_plan"],
                    "prevalence": [0.22, 0.18, 0.20, 0.12, 0.16, 0.12],
                    "conditional_inputs": ["artifact.form.mbi1", "artifact.proposal.repair", "artifact.record.supervision_log_sp1", "artifact.report.completion", "artifact.photo.annotated", "artifact.plan.annotated"],
                    "conditional_formula": None, "carrier_domain": "qualifier",
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "artifact 字段组 multinomial: form/supervision 高频, completion 仅完工阶段.",
                },
                # ===== E. fire_safety (1) =====
                {
                    "slot_id": "fire_safety.upgrade_outstanding",
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.16,
                    "conditional_inputs": ["building.metadata.building_age_years", "building.metadata.occupancy_and_use", "defect.fire_safety.component_deficiency.present", "risk.public_danger.present"],
                    "conditional_formula": None, "carrier_domain": "procedure",  # 长期可改 fire_safety_order
                    "source_attribution": "proagent_engineering_estimate_DEBT020_round4_2026_05_09",
                    "aliases": [], "notes": "BD statutory fire-safety upgrade order 是否仍 open; spec 09 §1.1.2 B 类; round4 confidence=low.",
                },
            ],
        )
    )

    # DEBT-020 Round 6 + Round 7 落地（2026-05-11）：把 round6_formulas 模块构造的
    # centered upstream conditional_formula + Round 7 anchor 修订 + sampling_order +
    # COP 章节引用 + alignment_check overlay 到 sidecar_bool_slot_registry 45 records.
    _apply_round6_round7_overlays(registries)

    return RegistryBundle(generated_at=_utc_now_iso(), source_documents=list(SOURCE_DOCUMENTS), registries=registries)


# DEBT-020 Round 7 §3 alignment_check (10000 MC, seed=20260511) 实测 delta < 0.05.
# 见 round6_formulas.py + DEBT-020 Round 7 §3 alignment_results.
# 这里的 observed_marginal 是 Round 7 §3 的 reference value；W0 实跑 sidecar 派生层时
# observed_marginal 会按 release batch 实际 fragment 群体 重新计算（通过
# sidecar.py:_run_alignment_check_for_release_batch 校验）.
_ROUND7_ALIGNMENT_REFERENCE: Dict[str, Dict[str, Any]] = {
    "procedure.ri.appointment.completed": {"observed": 0.8625, "delta": 0.0025},
    "artifact.form.mbi1": {"observed": 0.9460, "delta": -0.0040},
    "procedure.temp_ri_nomination.completed": {"observed": 0.0837, "delta": 0.0037},
    "procedure.temp_ri_nomination.terminated": {"observed": 0.0311, "delta": 0.0011},
    "procedure.ri_role.terminated": {"observed": 0.0606, "delta": 0.0006},
    "artifact.form.mbi5": {"observed": 0.0744, "delta": 0.0044},
    "artifact.form.mbi2": {"observed": 0.0835, "delta": 0.0035},
    "procedure.inspection.prescribed.completed": {"observed": 0.7360, "delta": -0.0040},
    "artifact.form.mbi3_or_mbi3a": {"observed": 0.7129, "delta": -0.0071},
    "artifact.record.inspection_log": {"observed": 0.7762, "delta": -0.0038},
    "artifact.report.inspection": {"observed": 0.7238, "delta": -0.0062},
    "artifact.photo.annotated": {"observed": 0.6943, "delta": -0.0057},
    "artifact.plan.annotated": {"observed": 0.6375, "delta": -0.0025},
    "procedure.investigation.intention_notified": {"observed": 0.2948, "delta": -0.0052},
    "artifact.notice.investigation_intention": {"observed": 0.3141, "delta": 0.0141},
    "procedure.investigation.proposal.submitted": {"observed": 0.3129, "delta": 0.0129},
    "artifact.proposal.detailed_investigation": {"observed": 0.3174, "delta": 0.0174},
    "procedure.investigation.proposal.recognized": {"observed": 0.2028, "delta": 0.0228},
    "procedure.investigation.started": {"observed": 0.2203, "delta": 0.0203},
    "procedure.supervision_representative.planned": {"observed": 0.6560, "delta": -0.0040},
    "procedure.supervision_team.submitted": {"observed": 0.5775, "delta": -0.0025},
    "procedure.supervision_team.changed": {"observed": 0.1204, "delta": 0.0004},
    "artifact.proposal.repair": {"observed": 0.5757, "delta": 0.0057},
    "procedure.rc.pre_notification_given": {"observed": 0.5036, "delta": 0.0036},
    "procedure.repair.prescribed.started": {"observed": 0.5467, "delta": -0.0033},
    "supervision.site_visit.performed": {"observed": 0.7937, "delta": -0.0063},
    "artifact.record.supervision_log_sp1": {"observed": 0.6047, "delta": -0.0053},
    "supervision.record.completed": {"observed": 0.7114, "delta": -0.0086},
    "supervision.record.retained": {"observed": 0.6671, "delta": -0.0129},
    "supervision.record.completed_and_retained": {"observed": 0.6075, "delta": -0.0125},
    "artifact.record.test_or_material_witness": {"observed": 0.4403, "delta": 0.0003},
    "artifact.certificate.material_or_product": {"observed": 0.4289, "delta": -0.0011},
    "artifact.record.nonconformity_sp2": {"observed": 0.2017, "delta": 0.0017},
    "procedure.repair.revision_required": {"observed": 0.1839, "delta": 0.0039},
    "artifact.proposal.repair_revision": {"observed": 0.1770, "delta": 0.0070},
    "procedure.repair.prescribed.completed": {"observed": 0.4170, "delta": -0.0030},
    "procedure.completed_work.final_inspection_performed": {"observed": 0.4094, "delta": 0.0094},
    "artifact.report.completion": {"observed": 0.4107, "delta": 0.0107},
    "artifact.form.mbi4": {"observed": 0.4030, "delta": 0.0130},
    "artifact.statement.scope_and_order_coverage": {"observed": 0.5792, "delta": -0.0008},
    "artifact.statement.extra_works_separated": {"observed": 0.1900, "delta": 0.0000},
    "fire_safety.upgrade_outstanding": {"observed": 0.1575, "delta": -0.0025},
    "qual.actor_role": {"max_abs_delta": 0.0073},
    "qual.method_class": {"max_abs_delta": 0.0069},
    "qual.artifact_field_group": {"max_abs_delta": 0.0102},
}


def _apply_round6_round7_overlays(registries: List[RegistryTable]) -> None:
    """DEBT-020 Round 6 + Round 7 落地 overlay：sidecar_bool_slot_registry 45 records 加 7 字段.

    每条 record 在 in-place patch:
      - conditional_formula: None → centered_sigmoid_linear / centered_softmax_per_class dict
      - sampling_order: 1-45 (Round 7 §0 修订: MBI2=7, 旧 16 移走)
      - upstream_inputs: {sidecar: [...], hidden: [H.x...]}
      - marginal_anchor: Round 7 §1 修订表（3 数值改, 42 不变）
      - anchor_source: Round 7 §1 source_label_revised (COP §x.y.z + modality)
      - alignment_check: Round 7 §3 MC reference (10000 sample, seed=20260511)
      - distribution_source: proagent_engineering_estimate_current_authority_round5_2026_05_10
      - cop_section: 主要 COP 引用

    spec 06 §11.6.7 DAG validity：每条 sidecar upstream 的 sampling_order 必须 < 当前 slot.
    """
    formulas = get_round6_round7_formulas()
    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            slot_id = record.get("slot_id")
            if not slot_id or slot_id not in formulas:
                continue
            spec = formulas[slot_id]
            anchor_value = MARGINAL_ANCHORS_ROUND7[slot_id]
            alignment = _ROUND7_ALIGNMENT_REFERENCE.get(slot_id, {})
            record["conditional_formula"] = spec["conditional_formula"]
            record["sampling_order"] = spec["sampling_order"]
            record["upstream_inputs"] = spec["upstream_inputs"]
            record["marginal_anchor"] = anchor_value
            record["anchor_source"] = ANCHOR_SOURCES_ROUND7[slot_id]
            record["alignment_check"] = {
                "monte_carlo_n": 10000,
                "seed": 20260511,
                "pass_threshold": 0.05,
                **alignment,
                "status": "passed_round7_mc",
            }
            record["distribution_source"] = DEBT020_ROUND7_DISTRIBUTION_SOURCE
            record["cop_section"] = spec["cop_section"]
            # Round 7 §1 anchor 修订对应的 prevalence 同步——marginal path fallback 也用新值
            if isinstance(anchor_value, dict):
                # enum: rebuild prevalence list per enum_values order
                enum_values = record.get("enum_values") or []
                if enum_values:
                    record["prevalence"] = [
                        float(anchor_value.get(ev, 0.0)) for ev in enum_values
                    ]
            else:
                record["prevalence"] = float(anchor_value)
            # marker source_attribution 升级到 Round 7
            record["source_attribution"] = (
                f"{record.get('source_attribution', '')} | "
                f"DEBT020_round7_centered_upstream_conditional_2026_05_11"
            ).strip(" |")


def _build_sidecar_contract() -> SidecarContract:
    ownership_map: List[SlotOwnershipEntry] = []

    def add_slots(slot_ids: List[str], partition: SlotPartition, carrier: str, notes: str = "") -> None:
        ownership_map.extend(
            SlotOwnershipEntry(slot_id=slot_id, partition=partition, carrier=carrier, notes=notes)
            for slot_id in slot_ids
        )

    add_slots(
        [
            "building.identity.basic",
            "building.metadata.occupancy_and_use",
            "building.metadata.configuration",
            "building.metadata.primary_materials",
            "scope.component.in_scope",
            "scope.component.excluded_from_scope",
            "scope.component.covered",
            "scope.component.covered_by_large_signboard",
            "scope.component.obscured_by_finish",
            "scope.component.obscured_by_services",
            "defect.class.present",
            "defect.range.extends_into_private_premises",
            "defect.cause_or_extent.uncertain",
            "defect.hollowing.present",
            "defect.moisture_or_leakage.present",
            "defect.detachment_or_loose_fixing.present",
            "defect.drainage.misconnection.present",
            "defect.drainage.blockage.present",
            "defect.drainage.leakage.present",
            "defect.ubw.present",
            "defect.subdivided_unit_sign.present",
            "defect.fire_safety.component_deficiency.present",
            "risk.building_safety.emergency",
            "risk.public_health.emergency",
            "risk.public_danger.present",
            "coverage.insufficient",
            "repair.required",
            "repair.outcome.safe_until_next_cycle",
            "maintenance.pre_next_cycle.required",
            "investigation.fsp.below_required_safety",
            "verification.test.failed",
        ],
        "world_core",
        "FragmentContext/ConditionState",
    )
    add_slots(
        [
            # DEBT-025 closure 2026-05-07：删 7 个 phantom slot:
            # area.signboard.display / ratio.covered_area.inspected /
            # count.access_opening.required / area.finish_probe.sampled /
            # count.drainage.test_points.minimum / length.drainage.branch.interval /
            # count.fire_door.sample.minimum
            # （7 项无 spec 04 §17 / 08 §3.1 完整授权 + 无 MBIS 法规阈值依据 + generator 不产值）
            "ratio.external_wall_area.inspected",
            "ratio.covered_structure_area.inspected",
            "count.canopy.check_locations.minimum",
            "length.canopy.check_location.interval",
            "count.private_premises_access.floor_interval",
            "ratio.fsp.structural_performance",
            "count.core_sample.minimum",
            "rate.core_sample.per_concrete_volume",
            "rate.pull_test.per_25m2",
            "count.pull_test.per_repaired_facade",
            "count.pull_test.per_floor_full_retiling",
            "stress.pull_test.minimum",
            "strength.pull_test.reported",
            "count.pull_test.failed_cumulative",
            "count.pull_test.additional_after_failure",
            "length.rendering.total_thickness",
            "length.rendering.layer_thickness",
            "depth.patch_repair",
            "length.concrete_repair.depth",
            "duration.repair_mortar.test_age",
            "count.repair_mortar_specimens.per_strength_property",
            "ratio.rebar.section_loss",
            "length.mortar.application_layer_thickness",
            # Round2 retire: generic ratio.chloride_content 已删
            "ratio.chloride_content.by_cement_weight",
            "count.hammer_tapping.grid.minimum",
            "time.fire_door.self_closing.delay_sec",
        ],
        "measurement_family",
        "MeasurementState",
    )
    add_slots(
        [
            "qual.component_type",
            "qual.location_class",
            "qual.defect_class",
            "qual.risk_class",
            "qual.method_class",
            "qual.work_category",
        ],
        "qualifier_taxonomy",
        "taxonomy_registry",
    )
    add_slots(
        [
            "artifact.notice.ri_appointment",
            "artifact.notice.ri_temporary_nomination",
            "artifact.form.mbi1",
            "artifact.form.mbi2",
            "artifact.form.mbi3_or_mbi3a",
            "artifact.form.mbi4",
            "artifact.form.mbi5",
            "artifact.notice.investigation_intention",
            "artifact.proposal.detailed_investigation",
            "artifact.proposal.supervision",
            "artifact.proposal.repair",
            "artifact.proposal.repair_revision",
            "artifact.report.inspection",
            "artifact.report.completion",
            "artifact.photo.annotated",
            "artifact.plan.annotated",
            "artifact.record.inspection_log",
            "artifact.record.site_visit_log",
            "artifact.record.supervision_log_sp1",
            "artifact.record.nonconformity_sp2",
            "artifact.report.test_result",
            "artifact.record.test_or_material_witness",
            "artifact.certificate.material_or_product",
            "artifact.statement.scope_and_order_coverage",
            "artifact.statement.extra_works_separated",
            "procedure.ri.appointment.completed",
            "procedure.temp_ri_nomination.completed",
            "procedure.temp_ri_nomination.terminated",
            "procedure.ri_role.terminated",
            "procedure.repair_supervising_ri.appointment.completed",
            "procedure.repair.revision_proposal.submitted_to_ba",
            "procedure.supervision_representative.planned",
            "procedure.supervision_team.submitted",
            "procedure.supervision_team.changed",
            "procedure.inspection.prescribed.completed",
            "procedure.investigation.intention_notified",
            "procedure.investigation.proposal.submitted",
            "procedure.investigation.proposal.recognized",
            "procedure.investigation.detailed.started",
            "procedure.investigation.started",
            "procedure.repair.revision_required",
            "procedure.repair.prescribed.started",
            "procedure.repair.prescribed.completed",
            "procedure.completed_work.final_inspection_performed",
            "procedure.rc.pre_notification_given",
            "duration.notification.deadline",
            "duration.submission.deadline",
            "duration.delivery.deadline",
            # DEBT-020 round5 sub-task 5 (2026-05-10) — 拆分后 2 个新 sidecar slot
            "duration.delivery.deadline.to_person",
            "duration.delivery.deadline.to_ba",
            # DEBT-020 round5 sub-task 5 — to_person carrier_slot (BA submission anchor，pro 推测)
            "artifact.report_completion_or_mbi4.submitted_to_ba",
            "duration.site_visit.interval",
            "actor.representative.assigned",
            "actor.representative.qualified_for_assigned_role",
            "reporting.artifact.prepared",
            "reporting.artifact.signed",
            "reporting.artifact.submitted",
            "reporting.artifact.delivered",
            "reporting.annotated_photo.present",
            "reporting.annotated_location_plan.present",
            "reporting.record.maintained",
            "reporting.record.submitted",
            "supervision.site_visit.performed",
            "supervision.record.completed",
            "supervision.record.retained",
            "supervision.record.completed_and_retained",
            # DEBT-025 closure 2026-05-07：4 个 inspection_execution carrier_slot
            # 由 sidecar_measurement_registry 5 个新加 inspection_coverage / inspection_plan
            # entry 引用（spec 09 §7.1）。SCAN guardrail line 109 强制 carrier_slot 在
            # ownership_map 注册，否则 cross-registry 引用 phantom。
            "inspection.external_wall.coverage_evidence",
            "inspection.structural.coverage_evidence",
            "inspection.canopy.check_plan",
            "inspection.private_premises.access_plan",
            "qual.actor_role",
            "qual.artifact_field_group",
            "fire_safety.upgrade_outstanding",
            "marker.artifact_required",
            "marker.procedure_required",
            "marker.supervision_required",
            "marker.no_sidecar_dependency",
            # spec 09 §1.2 修订（2026-05-09）：废止 marker.sidecar_missing.
            # sidecar bundle 由 worldgen 派生层同步生成，不存在缺失态；
            # 旧 marker 历史值见 git log；新 batch 不再 emit.
        ],
        "sidecar",
        "procedure/artifact/supervision sidecar",
        "Administrative, reporting, and supervision state remains outside world core.",
    )

    interface_schema = [
        SidecarInterfaceSchema(
            interface_id="inspection_report_sidecar",
            sidecar_domain="artifact",
            input_fields=[
                SidecarInterfaceField(
                    field_id="world_core_snapshot",
                    partition="world_core",
                    source_slot_ids=[
                        "building.identity.basic",
                        "building.metadata.occupancy_and_use",
                        "building.metadata.configuration",
                        "building.metadata.primary_materials",
                        "defect.class.present",
                        "defect.moisture_or_leakage.present",
                        "defect.detachment_or_loose_fixing.present",
                        "defect.fire_safety.component_deficiency.present",
                        "repair.required",
                        "maintenance.pre_next_cycle.required",
                    ],
                    target_slot_ids=[
                        "artifact.report.inspection",
                        "artifact.form.mbi3_or_mbi3a",
                        "artifact.proposal.repair",
                        "artifact.statement.scope_and_order_coverage",
                    ],
                    notes="World facts feed report authoring but remain separate from the artifact.",
                ),
                SidecarInterfaceField(
                    field_id="measurement_snapshot",
                    partition="measurement_family",
                    source_slot_ids=[
                        # DEBT-025 closure 2026-05-07：删 5 个 phantom slot
                        "ratio.external_wall_area.inspected",
                        "ratio.covered_structure_area.inspected",
                        "count.private_premises_access.floor_interval",
                        "ratio.fsp.structural_performance",
                    ],
                    target_slot_ids=[
                        "artifact.record.inspection_log",
                        "artifact.photo.annotated",
                        "artifact.plan.annotated",
                    ],
                    notes="Measured values are copied into report evidence, not owned there.",
                ),
            ],
            output_fields=[
                SidecarInterfaceField(
                    field_id="artifact_refs",
                    partition="sidecar",
                    source_slot_ids=[
                        "artifact.report.inspection",
                        "artifact.record.inspection_log",
                        "artifact.photo.annotated",
                        "artifact.plan.annotated",
                        "artifact.proposal.repair",
                    ],
                    target_slot_ids=[
                        "artifact.report.inspection",
                        "artifact.record.inspection_log",
                        "artifact.photo.annotated",
                        "artifact.plan.annotated",
                        "artifact.proposal.repair",
                    ],
                    notes="Sidecar emits refs that projections may bind to later.",
                )
            ],
            notes=["Supports investigation/reporting completeness families without polluting world truth."],
        ),
        SidecarInterfaceSchema(
            interface_id="procedure_gate_sidecar",
            sidecar_domain="procedure",
            input_fields=[
                SidecarInterfaceField(
                    field_id="risk_and_uncertainty_events",
                    partition="world_core",
                    source_slot_ids=[
                        "risk.building_safety.emergency",
                        "risk.public_health.emergency",
                        "risk.public_danger.present",
                        "defect.cause_or_extent.uncertain",
                    ],
                    target_slot_ids=[
                        "procedure.inspection.prescribed.completed",
                        "procedure.investigation.proposal.recognized",
                        "duration.notification.deadline",
                        "duration.submission.deadline",
                    ],
                    notes="Physical risk and uncertainty trigger procedural obligations but do not become one.",
                )
            ],
            output_fields=[
                SidecarInterfaceField(
                    field_id="gate_snapshot",
                    partition="sidecar",
                    source_slot_ids=[
                        "procedure.ri.appointment.completed",
                        "procedure.temp_ri_nomination.completed",
                        "procedure.investigation.intention_notified",
                        "procedure.investigation.proposal.submitted",
                        "procedure.investigation.proposal.recognized",
                        "procedure.investigation.detailed.started",
                        "procedure.repair.revision_required",
                        "duration.notification.deadline",
                        "duration.submission.deadline",
                        "duration.delivery.deadline",
                    ],
                    target_slot_ids=[
                        "procedure.ri.appointment.completed",
                        "procedure.temp_ri_nomination.completed",
                        "procedure.investigation.intention_notified",
                        "procedure.investigation.proposal.submitted",
                        "procedure.investigation.proposal.recognized",
                        "procedure.investigation.detailed.started",
                        "procedure.repair.revision_required",
                        "duration.notification.deadline",
                        "duration.submission.deadline",
                        "duration.delivery.deadline",
                    ],
                    notes="Procedural gates remain owned by the sidecar.",
                )
            ],
            notes=["Separates gate/deadline ownership from the world bundle."],
        ),
        SidecarInterfaceSchema(
            interface_id="supervision_sidecar",
            sidecar_domain="supervision",
            input_fields=[
                SidecarInterfaceField(
                    field_id="repair_validation_snapshot",
                    partition="measurement_family",
                    source_slot_ids=[
                        "rate.pull_test.per_25m2",
                        "count.pull_test.per_repaired_facade",
                        "count.pull_test.failed_cumulative",
                        "stress.pull_test.minimum",
                        "ratio.rebar.section_loss",
                        # Round2 retire: generic ratio.chloride_content 已删
                    ],
                    target_slot_ids=[
                        "artifact.record.supervision_log_sp1",
                        "artifact.record.nonconformity_sp2",
                        "artifact.record.test_or_material_witness",
                        "duration.site_visit.interval",
                    ],
                    notes="Validation facts seed supervision records without changing their ownership.",
                )
            ],
            output_fields=[
                SidecarInterfaceField(
                    field_id="supervision_refs",
                    partition="sidecar",
                    source_slot_ids=[
                        "procedure.supervision_representative.planned",
                        "procedure.supervision_team.submitted",
                        "procedure.supervision_team.changed",
                        "supervision.site_visit.performed",
                        "supervision.record.completed_and_retained",
                        "artifact.record.supervision_log_sp1",
                        "artifact.record.nonconformity_sp2",
                        "artifact.record.test_or_material_witness",
                        "duration.site_visit.interval",
                    ],
                    target_slot_ids=[
                        "procedure.supervision_representative.planned",
                        "procedure.supervision_team.submitted",
                        "procedure.supervision_team.changed",
                        "supervision.site_visit.performed",
                        "supervision.record.completed_and_retained",
                        "artifact.record.supervision_log_sp1",
                        "artifact.record.nonconformity_sp2",
                        "artifact.record.test_or_material_witness",
                        "duration.site_visit.interval",
                    ],
                    notes="Supervision outputs are returned as references only.",
                )
            ],
            notes=["Used for repair validation and completion supervision."],
        ),
        SidecarInterfaceSchema(
            interface_id="completion_report_sidecar",
            sidecar_domain="artifact",
            input_fields=[
                SidecarInterfaceField(
                    field_id="repair_outcomes",
                    partition="world_core",
                    source_slot_ids=[
                        "repair.required",
                        "repair.outcome.safe_until_next_cycle",
                        "maintenance.pre_next_cycle.required",
                        "verification.test.failed",
                    ],
                    target_slot_ids=[
                        "procedure.repair.prescribed.completed",
                        "procedure.completed_work.final_inspection_performed",
                        "artifact.report.completion",
                        "artifact.form.mbi4",
                    ],
                    notes="Completion report consumes outcomes while keeping milestones outside world core.",
                )
            ],
            output_fields=[
                SidecarInterfaceField(
                    field_id="completion_refs",
                    partition="sidecar",
                    source_slot_ids=[
                        "procedure.repair.prescribed.completed",
                        "procedure.completed_work.final_inspection_performed",
                        "artifact.report.completion",
                        "artifact.form.mbi4",
                        "artifact.certificate.material_or_product",
                        "artifact.statement.extra_works_separated",
                    ],
                    target_slot_ids=[
                        "procedure.repair.prescribed.completed",
                        "procedure.completed_work.final_inspection_performed",
                        "artifact.report.completion",
                        "artifact.form.mbi4",
                        "artifact.certificate.material_or_product",
                        "artifact.statement.extra_works_separated",
                    ],
                    notes="Projection later binds to this sidecar reference.",
                )
            ],
            notes=["Used by repair completion families."],
        ),
    ]
    return SidecarContract(generated_at=_utc_now_iso(), ownership_map=ownership_map, interface_schema=interface_schema)


# spec 草案·流程槽粒度语义（2026-07-08 定稿）：fragment 采样槽的"楼级读数"聚合语义，
# 单一来源双用：①sidecar 楼级槽跨粒度上游解析 ②生成侧楼级聚合行派生。
# supervision.* 三条为 final_inspection 上游解析用（engineering_estimate_20260708 低置信）。
BUILDING_READING_AGGREGATION: dict = {
    "procedure.inspection.prescribed.completed": "all_true",
    "procedure.repair.prescribed.completed": "all_true",
    "procedure.repair.prescribed.started": "any_true",
    "procedure.investigation.started": "any_true",
    "supervision.site_visit.performed": "any_true",
    "supervision.record.completed": "all_true",
    "supervision.record.retained": "all_true",
    # 证物文档槽（fail-fast 机器枚举三条边 + v8 批跑歧义下钻两槽，2026-07-08）：
    # 文档现实中楼级存在，任一部位记录带有=存在（any_true；engineering_estimate 低置信）。
    "artifact.proposal.repair": "any_true",
    "artifact.form.mbi4": "any_true",
    "artifact.report.completion": "any_true",
    "artifact.report.inspection": "any_true",
    "artifact.proposal.detailed_investigation": "any_true",
}

# 生成侧要落"楼级聚合行"的 fragment 槽——v8 批跑实证后扩到全聚合表的 bool 槽
# （文档/进度槽被楼级卡消费时同构歧义；聚合行 + §6.4.3 作用域分级 = 楼级唯一读数）。
AGGREGATE_ROW_SLOTS: tuple = tuple(sorted(BUILDING_READING_AGGREGATION))
