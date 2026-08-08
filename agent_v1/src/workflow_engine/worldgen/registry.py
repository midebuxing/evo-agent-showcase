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
    A16_ANNOTATED_ROUND7_SLOTS,
    A16_MC_CALIBER_BOUNDARY_NOTE,
    A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX,
    ANCHOR_SOURCES_ROUND7,
    DISTRIBUTION_SOURCE as DEBT020_ROUND7_DISTRIBUTION_SOURCE,
    MARGINAL_ANCHORS_ROUND7,
    MC_CALIBER_FRAGMENTS_PER_BUILDING,
    POOL_V2_REWIRED_DISTRIBUTION_SOURCE,
    POOL_V2_REWIRED_OVERLAY_SLOTS,
    POOL_V2_SUPPLY_DISTRIBUTION_SOURCE,
    POOL_V2_SUPPLY_SAMPLING_ORDERS,
    POST_CLAMP_REALIZED_MARGINALS,
    PRECONDITION_COUPLING_DISTRIBUTION_SOURCE,
    SAMPLING_ORDER_ROUND7,
    get_pool_v2_supply_slot_specs,
    get_precondition_coupling_formulas,
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
            "Cumulative failed pull-test count used by additional-test formula thresholds. Round2 bounds 10→6。"
            "分布标签 2026-08-06 由 zero_inflated_discrete 撤为 rounded_truncated_normal（撤标签裁定见下方注释）："
            "本条从未配 calib_zero_prob，零膨胀分支从未生效，实际一直按 normal(0.95,1.12) 采、clip[0,5]、round；"
            "0 值占比是 clip 派生结果，不是被授权的 π0。",
            # 🔴 标签修正（商议结果_glm_calib裁定_20260806 §三 候选②，零采样影响）：原写
            # `zero_inflated_discrete`，但本条**没有** `calib_zero_prob`
            # ⇒ `_sample_typical_distribution` 的零膨胀分支（generator.py:1577）根本不进，
            # 实际就是按 `normal` 采的。按 `.to_person` 先例（决议_分布授权_20260805 §二.1，
            # registry.py 同族条目）撤标签——留着标签会让下一个读者得出「本条有零膨胀」这个
            # 错误结论（`.to_person` 已因此错过一次）。
            # 两个名字都被 `_normalize_distribution_name` 映射到 `normal` ⇒ 采样值逐字节相同
            # （2026-08-06 实测：同 seed 20000 次采样 repr 字节全等、rng 终态相同、无首处失配；
            # 且本槽在 `technical_measurement_registry`，不走 sidecar 的 `distribution=<名字>`
            # 发射串 ⇒ 连 notes 文本副作用都没有）。
            # ⚠️ 撤标签**不预判「该不该补零膨胀」**：本槽物理上「合格楼 failed=0」是真质量点，
            # 零膨胀在物理上有道理，但那属另裁（决议_A16裁定_20260806 §三「须入冻结窗口另裁」，
            # 补值＝激活 generator.py:1577 分支＝世界分布实质变更）。撤标签只诚实标注「当前没有」。
            recommended_distribution="rounded_truncated_normal",
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
            # #23 L3（2026-08-06）：+transfer_structure（§3.4 結構構件裂縫）、
            # +external_appendage/false_ceiling_common_area（structural_crack 链主发射类：
            # 錨栓/吊挂系统裂縫）、+external_wall_finish（§5.3.1 批盪裂縫，沿 wall_tile_finish 先例）。
            ["external_wall", "structural_member", "parapet_wall", "balcony_slab", "wall_tile_finish",
             "transfer_structure", "external_appendage", "false_ceiling_common_area", "external_wall_finish"],
            ["structural_crack"],
        ),
        _defect_condition_record(
            "DC_SPALL_REBAR",
            "spall_rebar",
            ["spalling", "concrete_spall"],
            "corrosion_chain",
            ["spall_area_m2", "rebar_exposed_length_m", "ratio.rebar.section_loss"],
            # Round2 retire: generic ratio.chloride_content 已删；用 ratio.chloride_content.by_cement_weight
            # #23 L3：+transfer_structure（RC 轉移板/樑剝落，§3.4.2 同鏈）。
            ["external_wall", "structural_member", "canopy", "transfer_structure"],
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
            # #23 L3：+transfer_structure（FT_TRANSFER_BEAM_HOLLOWING 先例同鏈）、
            # +external_wall_finish（批盪空鼓，沿 wall_tile_finish 先例）。
            ["external_wall", "structural_member", "balcony_slab", "parapet_wall", "wall_tile_finish",
             "transfer_structure", "external_wall_finish"],
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
            # #23 L3：+external_appendage/false_ceiling_common_area（鬆脫/脫落，§5.3.5-§5.3.6）、
            # +external_wall_finish（批盪剝落，§5.3.1，沿 wall_tile_finish 先例）。
            ["external_wall", "balcony_slab", "parapet_wall", "signboard", "canopy", "wall_tile_finish",
             "external_appendage", "false_ceiling_common_area", "external_wall_finish"],
            ["structural_crack", "assessment_origin"],
            "T-06 合并 DC_MASONRY_SULFATE_ATTACK 候选（砌石砌砖因可溶性硫酸盐和潮湿导致砂浆层膨胀劣化）；MBIS §5.4.3。",
        ),
        _defect_condition_record(
            "DC_LOOSE_FIXING",
            "loose_fixing",
            ["loose_fixing", "loose_fastener", "missing_fastener", "defective_fastener"],
            "binary_present",
            [],
            # #23 L3：+external_appendage（§5.3.5(b) 錨栓）、+false_ceiling_common_area（吊挂件）。
            ["signboard", "canopy", "fire_door", "access_panel", "smoke_vent",
             "external_appendage", "false_ceiling_common_area"],
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
            # #23 L3：+transfer_structure（鋼轉移樑鏽蝕，阶段闸①可达）。
            ["structural_member", "drainage_stack", "signboard", "canopy", "fire_door", "access_panel",
             "transfer_structure"],
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
            # #23 L3：+transfer_structure（結構位移）、+external_appendage（支架變形/移位，
            # §5.3.5 拆除重裝的典型觸因）、+false_ceiling_common_area（下垂變形，§5.3.6(a)）。
            ["structural_member", "access_panel", "drainage_stack", "drainage_branch",
             "transfer_structure", "external_appendage", "false_ceiling_common_area"],
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
                # ── 验收③ 队列 1′ 甲-b（2026-07-29）：补上三类**池里实存却无模板**的构件 ──
                #
                # 病：`component_type_registry` 有 19 类，而片段模板只覆盖 8 类。
                # `balcony_slab` / `parapet_wall` / `signboard` 在池里**各有 5 个真实组件**
                # （分别落在沿海复合塔 ×5、沿海复合塔 ×5、混合用途高层 ×5），
                # 但没有任何模板 ⇒ **从来产不出片段** ⇒ 针对这些构件类的卡产不出
                # 作用域内义务 ⇒ 阅卷记漏（实测 15 个 (楼,构件类) 格）。
                #
                # ⚠️ 判据仍是「**楼内已存在的构件类**至少产一个片段」这条组件层完整性规则，
                #    **不是**「按漏掉的规范项补模板」。三类都在守则正文里被明文纳入检验范围：
                #      · 露台   §3.4.2(B)(a)「簷篷及**露台**等懸臂式伸出構築物均存在高風險，須予以檢驗」
                #      · 護牆   结构构件清单「(ix) 防護欄障、扶欄、**護牆**及欄杆」；
                #               另 §3.x「經改動的外牆或**護牆**」
                #      · 招牌   §1.3「…以及**豎設在樓宇上的招牌**」明列入强制验楼范围
                #
                # 取值全部取自池里这些组件的**实测**属性（面积/长度/位置类），不是编的：
                #   balcony_slab  balcony_line   5.2–46.0 m²  1.1–7.6 m
                #   parapet_wall  roof_edge     30.3–65.7 m² 12.3–35.6 m
                #   signboard     external_wall 23.5–160.3 m² 12.2–28.3 m
                {
                    "fragment_template_id": "FT_BALCONY_SLAB_V1",
                    "building_template_id": "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1",
                    "component_type": "balcony_slab",
                    "location_class": "balcony_line",
                    "area_range": [5.0, 50.0],
                    "length_range": [1.0, 8.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["corrosion_spall", "structural_crack"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    "fragment_template_id": "FT_PARAPET_WALL_V1",
                    "building_template_id": "BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1",
                    "component_type": "parapet_wall",
                    "location_class": "roof_edge",
                    "area_range": [30.0, 70.0],
                    "length_range": [12.0, 36.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "structural_assessment_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    # 招牌：守则把它与「僭建物」放在同一治理面（§1.3 明列入范围；
                    # §3.4.2(B)(c) 另有「豎設於簷篷之上…的僭建物」），故除结构劣化外
                    # 允许 ubw 机制；specialized_domains 带 ubw 以接僭建物专项状态。
                    "fragment_template_id": "FT_SIGNBOARD_V1",
                    "building_template_id": "BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1",
                    "component_type": "signboard",
                    "location_class": "external_wall",
                    "area_range": [20.0, 170.0],
                    "length_range": [12.0, 30.0],
                    "allowed_driver_profiles": [
                        "DRV_STRUCTURAL_DETERIORATION_V1",
                        "DRV_ALTERATION_AND_FIRE_V1",
                    ],
                    "allowed_mechanisms": ["corrosion_spall", "ubw_signal"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                    ],
                    "specialized_domains": ["ubw"],
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
                # ── #23 L3 四张新片段模板（无模板则新组件永不产片段＝加了等于没加）──
                {
                    # 轉移構築物（§3.4.2(C)(a)：可能被假天花等覆蓋板遮蓋，須檢驗
                    # 至少 30% 被遮蓋的構件 ⇒ coverage_sampling 分支承重）。
                    "fragment_template_id": "FT_TRANSFER_STRUCTURE_COVERED_V1",
                    "building_template_id": "BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1",
                    "component_type": "transfer_structure",
                    "location_class": "transfer_floor",
                    "area_range": [10.0, 120.0],
                    "length_range": [3.0, 30.0],
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
                    # 外牆附屬物（§3.3.1(a)(vi)；§5.3.5 拆除重裝／錨栓安裝於結構構件）。
                    "fragment_template_id": "FT_EXTERNAL_APPENDAGE_V1",
                    "building_template_id": "BT_HK_PRIVATE_RESIDENTIAL_TOWER_RC_V1",
                    "component_type": "external_appendage",
                    "location_class": "external_wall",
                    "area_range": [0.5, 12.0],
                    "length_range": [0.5, 6.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    # 公用走廊及大堂假天花（§3.3.1(c)(i)；§5.3.6(a) 拆除及／或更換）。
                    "fragment_template_id": "FT_FALSE_CEILING_COMMON_V1",
                    "building_template_id": "BT_HK_COMMERCIAL_ASSEMBLY_MARKET_PODIUM_V1",
                    "component_type": "false_ceiling_common_area",
                    "location_class": "common_part",
                    "area_range": [5.0, 120.0],
                    "length_range": [2.0, 25.0],
                    "allowed_driver_profiles": ["DRV_STRUCTURAL_DETERIORATION_V1"],
                    "allowed_mechanisms": ["structural_crack"],
                    "measurement_branches": [
                        "defect_geometry_measurement",
                        "coverage_sampling_measurement",
                    ],
                    "specialized_domains": [],
                },
                {
                    # 外牆飾面·批盪類（§3.3.1(a)(i)；§5.3.1 拆除重裝＋附錄四技术标准）。
                    "fragment_template_id": "FT_EXTERNAL_WALL_FINISH_V1",
                    "building_template_id": "BT_HK_TONG_LAU_MIXED_USE_MASONRY_V1",
                    "component_type": "external_wall_finish",
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
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "tile_finish", "aluminium_window", "cast_iron", "metal"],  # #23 L3：+metal（external_appendage 金屬支架供給）
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.3, §3.4, §3.5, §3.6; 1950-1970s walkup residential blocks.",
                },
                {
                    "building_template_id": "BT_HK_MASS_HOUSING_RC_WALL_V1",
                    "building_use": "residential",
                    "structure_type": "rc_wall",
                    "storey_count_range": [8, 45],
                    "primary_materials": ["reinforced_concrete", "precast_concrete", "plaster_finish", "upvc_drainage", "steel_fire_doors", "metal"],  # #23 L3：+metal（external_appendage 金屬支架供給）
                    "component_graph_template_ids": [],
                    "notes": "MBIS §3.1.2, §3.4, §3.5, §3.6; public housing / HOS / high-density residential slab or tower blocks.",
                },
                {
                    "building_template_id": "BT_HK_PRIVATE_RESIDENTIAL_TOWER_RC_V1",
                    "building_use": "residential",
                    "structure_type": "rc_frame",
                    "storey_count_range": [20, 70],
                    "primary_materials": ["reinforced_concrete", "plaster_finish", "aluminium_window", "upvc_drainage", "steel_fire_doors", "metal"],  # #23 L3：+metal（external_appendage 金屬支架供給）
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
                    # #23 L2：+stone_cladding / glass_balustrade_panel——两值此前无任何楼型声明
                    # ⇒ 世界结构上永不产出；钉 COASTAL 因 parapet_wall 组件只在本楼型生成
                    # （generator._ARCHETYPE_EXTRA_COMPONENTS 硬编码，钉别处=加了等于没加第四形态）。
                    "primary_materials": ["reinforced_concrete", "polymer_render", "aluminium_window", "curtain_wall_glazing", "stainless_steel_pipe", "stone_cladding", "glass_balustrade_panel"],
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
                    "primary_materials": ["reinforced_concrete", "fire_resistant_partition_wall", "steel_fire_doors", "fire_rated_glass", "metal_gate", "metal"],  # #23 L3：+metal（false_ceiling 金屬吊架供給）
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
                    # #23 L2（决议_23路线_20260805 §一.1，配方固化在 canary_scope_conjunction_probe.py
                    # 的 L2_MATERIAL_COMPATIBILITY_ADDITIONS）：+curtain_wall_glazing /
                    # curtain_wall_aluminium_frame / metal_louver_fin / metal_gate ＋
                    # 砌体本体三值 clay_brick / concrete_block / stone_masonry（§5.4.3；
                    # 唯一砌体楼型 TONG_LAU 的 primary_materials 早已声明 clay_brick）。
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "plaster_finish", "masonry_plaster", "polymer_render", "tile_finish", "stone_cladding", "aluminium_panel_cladding", "gfrc_panel", "paint_coating", "curtain_wall_glazing", "curtain_wall_aluminium_frame", "metal_louver_fin", "metal_gate", "clay_brick", "concrete_block", "stone_masonry"],
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
                    # #23 L2：+glass_balustrade_panel（§5.3.6(b) 栏板/栏杆承载；
                    # parapet_wall 组件只在 COASTAL 楼型生成，来源钉在该楼型 primary_materials）。
                    "material_compatibility": ["reinforced_concrete", "plain_concrete", "masonry_plaster", "tile_finish", "plaster_finish", "glass_balustrade_panel"],
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
                # ── #23 L3 四个新组件类（决议_23路线_20260805 §一.1，甲路纪律）──
                {
                    # 轉移構築物（§3.4.1(b)(vii)；§3.4.2(C)(a) 轉移板及轉移樑…須檢驗
                    # 至少 30% 被遮蓋的構件，页 28）。真值 9 行的唯一纯建模缺口。
                    "component_type": "transfer_structure",
                    "component_class": "structural_component",
                    "material_compatibility": ["reinforced_concrete", "prestressed_concrete", "precast_concrete", "steel_transfer_beam", "structural_steel_section"],
                    "default_structural_role": "primary_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [3.0, 30.0], "visible_area_m2": [10.0, 150.0], "thickness_mm": [300, 2500]},
                    # RC-capable（轉移板/樑）；沿 structural_member 先例 [20, 75]
                    "cover_depth_mm_range": [20.0, 75.0],
                    "allowed_location_classes": ["transfer_floor", "podium_soffit"],
                    "allowed_mechanisms": ["structural_crack", "corrosion_spall", "assessment_origin"],
                    "notes": "engineering_estimate_23L3_20260806 低置信：几何范围沿 structural_member 先例放大到转移层构件量级。",
                },
                {
                    # 外牆附屬物（§3.3.1(a)(vi) 金屬支架、遮篷、花槽、支承屋宇裝備裝置
                    # 的構築物、晾衣架等，页 19；§5.3.5 修葺，页 46）。
                    "component_type": "external_appendage",
                    "component_class": "external_component",
                    "material_compatibility": ["metal", "timber", "composite_material"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [0.5, 6.0], "visible_area_m2": [0.5, 12.0], "thickness_mm": [3, 100]},
                    "cover_depth_mm_range": None,  # 非 RC（金属/木/复合支架类），cover_depth_mm 必 null
                    "allowed_location_classes": ["external_wall"],
                    "allowed_mechanisms": ["structural_crack"],
                    "notes": "engineering_estimate_23L3_20260806 低置信：附屬物以錨栓安裝於結構構件上（§5.3.5(b)），欠妥形态经 structural_crack 链发射（裂缝/變形位移）。",
                },
                {
                    # 公用走廊及大堂假天花（§3.3.1(c)(i)，页 19；§5.3.6(a) 欠妥的假天花板
                    # 須予以拆除及／或更換，页 47）。
                    "component_type": "false_ceiling_common_area",
                    "component_class": "external_component",
                    "material_compatibility": ["plaster_finish", "metal", "composite_material", "timber"],
                    "default_structural_role": "non_load_bearing",
                    "geometry_proxy_ranges": {"length_m": [2.0, 30.0], "visible_area_m2": [5.0, 150.0], "thickness_mm": [5, 60]},
                    "cover_depth_mm_range": None,  # 非 RC（吊挂板材），cover_depth_mm 必 null
                    "allowed_location_classes": ["common_part"],
                    "allowed_mechanisms": ["structural_crack"],
                    "notes": "engineering_estimate_23L3_20260806 低置信：吊挂系统欠妥经 structural_crack 链发射（裂缝/變形下垂）。",
                },
                {
                    # 外牆飾面·批盪類（§3.3.1(a)(i) 牆磚或瓦片、批盪及覆蓋層等外牆飾面，
                    # 页 19；§5.3.1 批盪及瓦片修葺，页 45）。瓦片类已有 wall_tile_finish
                    # 专项，本类承载批盪/油漆/聚合物批盪的非瓦片飾面半边。
                    "component_type": "external_wall_finish",
                    "component_class": "finish_system",
                    "material_compatibility": ["plaster_finish", "polymer_render", "masonry_plaster", "paint_coating"],
                    "default_structural_role": "finish_only",
                    "geometry_proxy_ranges": {"length_m": [1.0, 50.0], "visible_area_m2": [1.0, 300.0], "thickness_mm": [5, 50]},
                    "cover_depth_mm_range": None,  # 饰面层非 RC，cover_depth_mm 必 null
                    "allowed_location_classes": ["external_wall", "common_part"],
                    "allowed_mechanisms": ["structural_crack"],
                    "notes": "engineering_estimate_23L3_20260806 低置信：几何范围沿 protective_render 先例；与 protective_render（W0 休眠、无组件计划）的区分＝本类进生成计划承载 §5.3.1 真值作用域。",
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
                {"coverage_relation_id": "CR_COVERED", "relation_type": "scope.component.covered", "target_component_types": ["signboard", "canopy", "external_wall", "parapet_wall", "balcony_slab", "structural_member", "wall_tile_finish", "transfer_structure", "external_wall_finish"], "obscuration_classes": ["signboard"], "ratio_slot_id": "", "default_inspection_ratio_range": [0.0, 0.8], "notes": "DEBT-049 B1（codex CoP §3.3.2(J)(a) 被遮盖的外部及其他实体构件、§3.4.2(D) 其他被遮盖构件）：遮蔽范围广于 signboard/canopy，扩至外部/结构/实体构件；covered_by_large_signboard 保留 signboard 专项。#23 L3（2026-08-06）：+transfer_structure（§3.4.2(C)(a) 轉移板及轉移樑可能被假天花等覆蓋板遮蓋、須檢驗至少 30% 被遮蓋的構件——本类的 coverage 轴是其真值条款的承重面）＋external_wall_finish（沿 wall_tile_finish 先例）。"},
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
                    # 🔴 乙12 甲案（换池捆绑批 2026-08-05；三线全票甲：
                    # `审核结果_{official,qwen,glm}_期限锚实施_20260805.md`）：
                    # 「同日送交完工報告副本」是**楼级一次性行政事件**（spec §3.1 形），
                    # 逐碎片抽是历史建模走样。改楼级前每栋发 7–8 行，#12 的 60 条
                    # **楼级作用域**义务在主 fact_index 里看到多行同锚 ⇒ 碰撞策略触发
                    # ⇒ 60/60 落 `blocked / ambiguous_fact_binding`、零确定判定。
                    # 改楼级后逐（楼,锚）恰 1 行 ⇒ 命中唯一 ⇒ 绑得上。
                    # ⚠️ 这是**换池级**改动（本槽行数与取值都变），故只许随换池批落。
                    "granularity": "building",
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
                    # BA submission date (NOT repair completion date).
                    # 🔴 R5 对齐（期限锚供给案 2026-08-05，决议 §四.2）：锚名原写
                    # `repair.completion_report_and_mbi4.submitted_to_ba` —— 该字符串
                    # **不在** `time_anchor_registry_v1.json` 的 19 条锚点册里，是世界侧孤儿；
                    # 卡侧 15 个锚点全部在册，其中对应的一条是
                    # `repair.completion_report.submitted_to_ba`。错的是世界侧这一方，故改这里
                    # （registry.py 是世界侧代码、不是权威卡包，不触发卡指纹链重建）。
                    # 该字段在 provenance 绑定通道接上之前不承载任何东西，接上之后失配是**静默**的
                    # ⇒ 改名与接线同一步落，并由 `worldgen/tests/test_deadline_anchor_emission.py`
                    # 的静态闸（全部 time_anchor_key ∈ 锚点册）挡住再犯，不靠注意力。
                    # 同批对齐 `unit`：世界侧原写 `calendar_day`、卡侧写 `day`；
                    # 通道接上前该不一致隐形，接上后会立刻变成判据分歧。
                    "rule_card_threshold": {
                        "relation": "same_day_as",
                        "operator": "==",
                        "value": 0,
                        "unit": "day",
                        "time_anchor_key": "repair.completion_report.submitted_to_ba",
                        "recipient_qualifier": {
                            # 🔴 2026-08-03 拆合并词：原值 `owner_or_person_for_whom_...`
                            # 的 `owner_or_` 前缀**无依据**——本条自己引的 §2.1.3(r)
                            # 只点名「該名由他人代為進行訂明修葺的人」一方，没有「業主」，
                            # 槽名本身也叫 `to_person`。裁定出处：
                            # `团队文档/我的笔记/规格_reporting三根轴世界侧补产_v1_20260803.md` §3.6
                            # （对中文正文逐字核过）。合并词现只存在于
                            # `actor_role_crosswalk.FORBIDDEN_MERGED_TERMS`（出现即报错）。
                            "actor_role_key": "person_for_whom_prescribed_repair_is_carried_out",
                        },
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(r)",
                    "semantic_note": (
                        "completion report / MBI4 已提交或签发给 BA 的同日, deliver copy / relevant document "
                        "to the person for whom prescribed repair is carried out. "
                        "Round 7 §2 已确认 anchor = BA submission date, NOT repair completion date."
                        "\n📌 **口径（乙12 甲案落地后重述，决议_分布授权 §二.1）**："
                        "实测 P(值=0)=0.5161 现在是**每栋楼的合规率**（n=30 ⇒ 期望 15.5 栋合规 ／ "
                        "14.5 栋违规）；改楼级**之前**的 107/206 是**每行占比**，且那 206 行"
                        "从未产出过任何判定（60 条义务全落 `ambiguous_fact_binding`）。"
                        "⛔ 绝不能把「每碎片 52%」乘起来当楼级合规率（0.52⁷≈1%）——"
                        "碎片行本来就不是这个事件的合法模型，那正是甲案要修的东西。"
                        "\n📌 **参数一个不改**：0.45/1.15 描述的是「**一次**同日送交事件的已歷日數」，"
                        "与一栋楼抽几次无关；0.5161 是 clip+round 的**派生结果**，不是被授权的 π0。"
                    ),
                    # 🔴 标签修正（决议_分布授权 §二.1，零采样影响）：原写
                    # `zero_inflated_discrete`，但本条**没有** `calib_zero_prob`
                    # ⇒ `_sample_typical_distribution` 的零膨胀分支根本不进，
                    # 实际就是按 `normal` 采的。留着这个标签会让下一个读者第二次得出
                    # 「本条有 π0=0.52 的零膨胀」这个错误结论（2026-08-05 草案 Q2 已因此错过一次）。
                    # 两个名字都被 `_normalize_distribution_name` 映射到 `normal` ⇒ 采样值逐字节相同；
                    # 唯一副作用是发射行 notes 里的 `distribution=<名字>` 文本变化。
                    "recommended_distribution": "rounded_truncated_normal",
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
                    # 🔴 与 `.to_person` **同批楼级化**（换池捆绑批 2026-08-05 裁定）：
                    # 两槽同属 §2.1.3(r) 的楼级一次性行政事件（呈交完工報告及 MBI4 ／
                    # 同日送交副本），留半个同类错位没有道理（qwen 审核建议、glm 同意）。
                    # ⚠️ glm 曾以「#8 碎片作用域会同时看到楼级行 + 本碎片行 ⇒ 命中 2 条
                    # ⇒ ambiguous」反对——**该理由在代码上不成立**（官方线证伪）：
                    # `sidecar.py` 对 `granularity=="building"` 的数值槽**直接跳过逐片段路径**
                    # ⇒ 改楼级后根本不存在碎片行；碎片索引按 `fragment_id in (None, fid)` 过滤，
                    # 只会看到那 1 条楼级行 ⇒ 命中 1 条 ⇒ 照样绑得上。
                    # 附带收益：#8 的 93 条碎片作用域义务改绑同一条楼级行后，
                    # **每栋内判定一致**（原先逐碎片独立采样，机制上允许同一栋楼同一个
                    # 「送交 BA」事件跨碎片判出不一致）。
                    "granularity": "building",
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
                # ============================================================ #
                # 期限锚 duration 槽（期限锚供给案，2026-08-05，决议 §四.3）
                # ============================================================ #
                # 权威依据：`团队文档/我的笔记/决议_期限锚_20260805.md`。
                #
                # **量的定义（八条统一）**：「自 `rule_card_threshold.time_anchor_key`
                # 所指的锚点事件发生起，至本条义务所要求的动作实际完成为止，已歷的日历日数」。
                # 这正是 sidecar numeric duration 能表达的量——中文守则原文的起算措辞是
                # 「…**後** N 日內」（过去事件 ⇒ 已歷时长），不是「…前 N 日」（未来事件的提前量，
                # 那类见 `FORBIDDEN_DEADLINE_ANCHOR_SUPPLY` 丙类禁供）。
                #
                # **粒度＝building（形态 C）**：这八个都是**楼级一次性行政事件**
                # （委任 / 提名 / 終止 / 呈交 / 送交），不随部位变。
                # 🔴 声明 `granularity: "building"` ⇒ 走 `sidecar.py` 的
                # `_sample_building_deadline_anchor_facts` 独立追加步骤，
                # 逐（楼,锚）**恰 1 行**、`qualifiers` 只带 `carrier_domain` + `granularity`，
                # **绝不打 `aggregation` 标记**。
                # 打了标记的后果是实测过的（E1 实验 A3 臂，全批 30 栋）：
                # `validator._fragment_index` 按 §3.2 设计把带标记的行排除出碎片索引，
                # 碎片作用域的期限义务 **107/107 一条都救不回**。
                # 且语义上打标记本身就是错用——聚合标记的语义是「派生聚合读数不得冒充
                # 部位原值」，行政事件根本没有可被冒充的部位原值
                # （`复核_发射形态C_{official,qwen}_20260805.md` 两线复核「不违背」）。
                #
                # **分布已授权定稿**（`团队文档/我的笔记/决议_分布授权_20260805.md` §一，
                # 2026-08-05 两线商议合成；换池捆绑批同批落）。占位标
                # `PLACEHOLDER_pending_distribution_authorization_20260805` 已全部撤除。
                #
                # 🔴 **档位＝工程估计，不是标定、不是实测**：
                # 本组合规率（通知/呈交族 ≈85%）继承自 DEBT-020 round3 对同族行政通知时长的
                # 工程估计，**不反映香港真实合规率**，也**不是标定目标**——本组槽不进 5-bin
                # 投影层（层一实测 `threshold pass_bool` 逐行差异 0/6707），故
                # `duration.notification.deadline` 的 S2.5 标定档（4.1/1.9，模拟 96.3%）
                # **对本组不适用**（照抄它在 n=30 下「六个通知槽至少一槽整批零违规」概率 0.90，
                # 违反「分布须覆盖合规与违规两侧」约束）。该 85% 唯一承担的功能是
                # **让合规与违规两侧在 n=30 的楼级样本里都有代表**（P(整批零违规)=0.008）。
                #
                # `physical_bounds` **本次一律不动**（甲类 [0,60] ／ 乙11 [0,30]）：
                # 采样先 clip 到 `typical_bounds` 再 clip 到 physical，typical 上界 20 < 30
                # ⇒ 两种 physical 上界对采样值逐字节无差别。
                # 🔴 **前提（官方审核门 2026-08-05 补，别删）**：上面这句「零采样影响」
                # **只在本组八槽仍走 Clip 路径（Path A）时成立**，不是无条件的机制性质——
                # 成立条件＝条目同时有 `recommended_distribution` ＋ mean ＋ **sigma**。
                # 一旦谁删掉一个 `sigma`（或写成未知分布名），`generator.py:1647` 判假
                # **改走 Path B**：`deterministic_value = (lo + hi) / 2.0`，而 lo/hi 就是
                # **physical**（L1613 ／ L1636-1644）——**完全绕过 `typical_bounds` clip**。
                # 官方线反事实实测（抽掉 sigma）：[0,60] 出 [32,33,30,29,…]、[0,30] 出
                # [16,16,15,14,…] —— **两界结果完全不同**。且 30 日与 15 日同在 ≤7 日阈值的
                # 违规侧 ⇒ **不报错、不改判定方向、但值分布已静默失真**（「关键配置静默退化」族）。
                # 同形兜底还有 L1564-1566 的未知分布名分支。当前八槽三字段齐备 ⇒ Path B 不可达。
                # ⚠️ 另：physical_bounds 还有个**非采样消费者**——静态闸
                # `test_deadline_anchor_emission.py::test_emitted_values_are_within_physical_bounds`
                # 直接拿它当断言上界，取 [0,60] 使该闸宽了一倍。当前恒过、不构成不一致，
                # 但严格讲「零影响」只对**采样值**成立，对**闸的紧度**不成立。
                # ⚠️ 决议 §一表的「typical / physical」列把 physical 写成 [0,30]，与同决议
                # 委托的逐槽替换文本（官方线商议 §六「physical_bounds 全部不动」）不一致；
                # 按委托条款取后者，差异对采样零影响（记于实施记录）。
                #
                # **不在这里的锚点**（别当遗漏）：
                # - #5 `inspection.prescribed.completed` / #6 `inspection.report.submitted_to_ba`
                #   —— §2.1.3(o) 四卡簇挂裁定（决议 §一.5）：`evaluate_deadline` 不读
                #   `offset_unit`（#6 是全部 25 条 deadline 里唯一的「個月」），且原文
                #   「以較早者為準」是双锚 min 语义、`deadlines` 契约无此形状——
                #   单供 #6 而 #15 无供给 ＝ 双锚降单锚 ＝ 造假 satisfied。
                # - #8 `repair.prescribed.completed` / #12 `repair.completion_report.submitted_to_ba`
                #   —— 复用既有槽 `duration.delivery.deadline.to_ba` / `.to_person`
                #   （两槽的 `rule_card_threshold.time_anchor_key` 早已登记，
                #   本单只把该登记回写进发射的载体，不新增条目、不改既有采样）。
                # - 丙类三锚 —— 见 `FORBIDDEN_DEADLINE_ANCHOR_SUPPLY`。
                {
                    # 甲 #1 ── §2.1.3(i) L858：「於獲委任日期後7日內，以指明的表格
                    # （表格MBI1）通知建築事務監督其已獲委任為註冊檢驗人員；」
                    "slot_id": "duration.notification.appointment_ri.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.ri.appointment.completed",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(i)"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "appointment.ri.made",
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(i)",
                    "semantic_note": (
                        "自 RI 獲委任之日起，至以表格 MBI1 通知建築事務監督為止的已歷日數。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 甲 #2 ── §2.1.3(j)：「於提名日期後7日內」
                    "slot_id": "duration.notification.nomination_temp_ri.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.temp_ri_nomination.completed",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(j)"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "nomination.temporary_ri.made",
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(j)",
                    "semantic_note": (
                        "自臨時註冊檢驗人員獲提名之日起，至通知建築事務監督為止的已歷日數。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 甲 #3 ── §2.1.3(k)：「於終止提名日期後7日內」
                    "slot_id": "duration.notification.nomination_temp_ri_terminated.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.temp_ri_nomination.terminated",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(k)"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "nomination.temporary_ri.terminated",
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(k)",
                    "semantic_note": (
                        "自終止臨時註冊檢驗人員提名之日起，至通知建築事務監督為止的已歷日數。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 甲 #4 ── §2.1.3(l)：「於終止擔任註冊檢驗人員日期後7日內」
                    "slot_id": "duration.notification.role_ri_terminated.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.ri_role.terminated",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(l)"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "role.ri.terminated",
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(l)",
                    "semantic_note": (
                        "自終止擔任註冊檢驗人員之日起，至通知建築事務監督為止的已歷日數。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 甲 #7 ── §2.1.3(p)：「須於該事情顯露或該情況發生後7日內」
                    "slot_id": "duration.submission.repair_revision.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.repair.revision_required",
                    "rule_basis_refs": ["MBIS COP 2023 §2.1.3(p)"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "repair.revision_need.exposed",
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(p)",
                    "semantic_note": (
                        "自需要修訂修葺建議的事情顯露／情況發生之日起，"
                        "至向建築事務監督呈交修訂建議為止的已歷日數。"
                        "分布归**呈交族**（决议 §一）：取既有 `duration.submission.deadline` "
                        "注释里早已声明、被 `_normalize_distribution_name` 坍缩掉的 "
                        "revised-proposal 成分（mean 5.5 / sigma 1.8，语义逐字对应），"
                        "**不是第七个新工程估值**；模拟 P(≤7 日)=0.8671。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 5.5,
                    "recommended_sigma": 1.8,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_submission_family_revised_proposal_component",
                },
                {
                    # 甲 #9 ── §6.4.4 L1861：「獲委任的註冊檢驗人員須在有關委任的日期後
                    # 7天內，通知建築事務監督已獲委任，並呈交監督建議…」
                    "slot_id": "duration.notification.appointment_supervising_ri.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.repair_supervising_ri.appointment.completed",
                    "rule_basis_refs": ["MBIS COP 2023 §6.4.4"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "appointment.repair_supervising_ri.made",
                    },
                    "cop_section": "MBIS_CoP_2023 §6.4.4",
                    "semantic_note": (
                        "自監督樓宇修葺的註冊檢驗人員獲委任之日起，"
                        "至通知建築事務監督並呈交監督建議為止的已歷日數。"
                        "⚠️ **归族边界例**（决议 §一表注）：守则原文一个期限盖住「通知」＋"
                        "「呈交監督建議」两个动作，约束动作其实是后者，故归呈交族也说得通。"
                        "本条按槽名前缀与守则动词首项归**通知族**；两档实测合规率 "
                        "0.8510 vs 0.8671（n=30 期望违规 4.47 vs 3.99），**该分歧不承重**。"
                        "⚠️ glm 线提的 3.5/1.6「监督流程更紧」系工程直觉发明的区分，**不采**。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 甲 #10 ── §6.4.6 L1865：「註冊檢驗人員須以書面方式通知建築事務監督
                    # 有關更換其監督人員隊伍的事宜(於作出變更當日後的7天內)…」
                    "slot_id": "duration.notification.supervision_team_changed.to_ba",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 60],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.supervision_team.changed",
                    "rule_basis_refs": ["MBIS COP 2023 §6.4.6"],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "within",
                        "operator": "<=",
                        "value": 7,
                        "unit": "day",
                        "time_anchor_key": "role.supervision_team.changed",
                    },
                    "cop_section": "MBIS_CoP_2023 §6.4.6",
                    "semantic_note": (
                        "自作出監督人員隊伍變更當日起，至以書面通知建築事務監督為止的已歷日數。"
                        "⚠️ **归族边界例**（与甲9 同批裁定）：本条与甲9 同属「監督流程」一线，"
                        "按槽名前缀与守则动词归**通知族**；glm 线的 3.5/1.6 区分系工程直觉"
                        "发明，**不采**（不发明规范）。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 4.8,
                    "recommended_sigma": 2.6,
                    "typical_bounds": [0, 20],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_from_proagent_DEBT020_round3_notification_family_pre_S2_5",
                },
                {
                    # 乙 #11 ── §2.1.3(p)「該建議亦須於**同日**送交該名由他人代為進行
                    # 訂明修葺的人」／(q)「須於**向建築事務監督呈交的同一日**，送交註冊承建商」
                    #
                    # 🔴 决议 §一.3 吸收 qwen 洞：#11 **世界侧原本没有承载槽**。
                    # ⚠️ 措辞订正（official 审核 M3①，2026-08-05 实取核实）：先前这里写
                    # 「只有布尔门 `procedure.repair.revision_proposal.submitted_to_ba`」，
                    # 那是**把一个不产出的东西陈述成存在的**——该槽当时只在
                    # `_build_sidecar_contract` 的 ownership_map 登记（`carrier_slot` FK
                    # 完整性所需），不在 `sidecar_bool_slot_registry` 实采清单里。
                    # ✅ 2026-08-06 换池批步 A1.3（#38 槽 3/槽 4）已补实采：本槽与
                    # #9 的 `procedure.repair_supervising_ri.appointment.completed` 均已
                    # 进 bool registry（G 组记录，order 34.5 / 45.4），「声明了永不产出」
                    # 自此关闭——首采随池 v2 生成（步 B），分布待 A1.6 授权门。
                    # `duration.delivery.deadline{,.to_person}` 承载的是 §2.1.3(r)
                    # 完工报告语义，**不能拿来判 (p)/(q) 的修訂建議書同日送交**——那是另一个行政事件。
                    #
                    # 计数口径（official 审核 M4③，与实施记录 §五.1 统一）：本单新增注册表
                    # 条目共 **8 条**（甲类真正需要新槽的 7 条 ＋ 本条乙 #11），本条是这 8 条里的
                    # 第 8 条。**不是「甲 8 之外新增的第 9 条」**——那个说法把挂起的 #6 也算进了
                    # 甲类、且 #8 复用既有 `.to_ba` 不需新槽，故「甲 8」这个基数本身就不成立。
                    #
                    # ⚠️ 已知简化（尾巴，须进分布授权草案）：(p) 的收件人是「該名由他人代為
                    # 進行訂明修葺的人」、(q) 是「註冊承建商」，是**两个收件人**；
                    # 而 B6 要求逐（楼,锚）恰 1 行，故本单以**一条量**承载两支。
                    # 若将来要分收件人判，须拆成两个槽 + 两个锚点，属规则扩展另案。
                    #
                    # ⚠️ `== 0` 的判据来源：(p)/(q) 两张卡 `threshold_regimes=[]`，
                    # 卡侧**没有**登记阈值。判据来自 **deadline relation 的结构性常量**
                    # ——「同日」的唯一数值读法就是差 0 日（不构成发明规范）。
                    # 该常量在 `evaluate_deadline` 的 `same_day_as` 分支显式写进 obligation notes，
                    # 不静默硬编码。
                    "slot_id": "duration.delivery.repair_revision_proposal",
                    "measurement_family": "procedure_duration",
                    "granularity": "building",
                    "value_type": "int",
                    "unit": "day",
                    "physical_bounds": [0, 30],
                    "precision_steps": {"coarse": 5, "standard": 1, "fine": 1},
                    "carrier_domain": "procedure",
                    "carrier_slot": "procedure.repair.revision_proposal.submitted_to_ba",
                    "rule_basis_refs": [
                        "MBIS COP 2023 §2.1.3(p)",
                        "MBIS COP 2023 §2.1.3(q)",
                    ],
                    "aliases": [],
                    "rule_card_threshold": {
                        "relation": "same_day_as",
                        "operator": "==",
                        "value": 0,
                        "unit": "day",
                        "time_anchor_key": "repair.revision_proposal.submitted_to_ba",
                        "threshold_source": (
                            "deadline_relation_structural_constant "
                            "(same_day_as ⇒ elapsed == 0 day); "
                            "卡侧 (p)/(q) threshold_regimes 为空，非卡侧登记值"
                        ),
                    },
                    "cop_section": "MBIS_CoP_2023 §2.1.3(p)(q)",
                    "semantic_note": (
                        "自向建築事務監督呈交修訂修葺建議之日起，"
                        "至把該建議送交下游收件人（(p) 該名由他人代為進行訂明修葺的人／"
                        "(q) 註冊承建商）為止的已歷日數；守則要求同日，即 0 日。"
                        "\n🔴 **本槽以一条量承载 §2.1.3(p)/(q) 两个收件人，两支永远同判，"
                        "「交了承建商没交业主」这类真实偏差不可建模**——属建模保真度缺口"
                        "（非捏造判定：两支的判定仍由同一条真实量决定）。解法＝拆两锚两槽，"
                        "属规则扩展另案（决议 §二.3；已登记技术与研究债）。"
                        "\n📌 **0 值占比 ≈0.5161 是派生结果，不是被授权的参数**："
                        "参数只有 mean 0.45 / sigma 1.15（与 `.to_person` 逐字段相同，"
                        "承载同一类量「同日送交的已歷日數」，新增假设 0 个）；"
                        "0.5161 由 clip+round 派生，尾部 1:0.305 / 2:0.140 / 3:0.038 单调衰减。"
                        "**不写 `zero_inflated_discrete`**：不补 `calib_zero_prob` 则标签是装饰"
                        "（代码走同一条正态分支），补上 π0=0.52 则实测 P(0)=0.5568、尾部双峰化"
                        "——两种写法都会让「授权的 π0」与「实际 0 值占比」对不上。"
                        "⛔ 弃用槽 `duration.delivery.deadline` 的 88.8% / π0=0.87 一律不引。"
                    ),
                    "recommended_distribution": "rounded_truncated_normal",
                    "recommended_mean": 0.45,
                    "recommended_sigma": 1.15,
                    "typical_bounds": [0, 3],
                    "distribution_source": "engineering_estimate_deadline_anchor_authorization_2026_08_05_same_day_shape_aligned_to_duration_delivery_deadline_to_person",
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
                    "aliases": [],
                    # 🔴 A1.6 补裁（2026-08-06，审核门必须修 A）：原 notes 写的
                    # 「completed (0.72) × retained_given_completed (0.85)」正是本步
                    # **明确否掉**的那条 0.62 推导。`prevalence` 已由
                    # `POST_CLAMP_REALIZED_MARGINALS` 覆盖成 0.39，notes 不同步
                    # ⇒ **注册表内部自相矛盾**：值是 0.39，而两个来源字段讲的是一条
                    # 会得出 0.62 的推导。改它的正当性在两条：①文档准确性（读这条
                    # 记录的人不该被一条已撤回的来历误导）；②`notes` 是 registry
                    # 记录的一部分 ⇒ 进 `registry_bundle_hash` ⇒ 属被 A3 封存的
                    # 权威内容，错的来历会被封进锚里。
                    # ⚠️ **不是**因为它会进产物行（2026-08-06 双线终审实测纠正）：
                    # `sidecar.py` 各发射点的 `notes=` 全是硬编码字面量，`_emit`
                    # 不读 `slot_record["notes"]`，`parquet_io` 只写
                    # `registry_bundle_hash` 不写 records。别再把「随 `_emit` 进
                    # 产物行」当理由——那句是编的，已在此撤回。
                    "notes": (
                        "聚合 flag；声明值＝钳制后实现边际 0.39（A1.6 补裁 2026-08-06）。"
                        "闭式四因子推导，输入全部是注册表已声明参数："
                        "P(retained|completed)=0.723876 → P(both)=0.72×0.723876=0.521191 "
                        "→ P(采样真|both)=0.742604 → 0.521191×0.742604=0.3870。"
                        "旧「completed 0.72 × retained_given_completed 0.85 = 0.62」推导已撤回："
                        "0.62 结构不可达（可达上界 P(both)=0.5212），且 0.85 是无出处工程比值。"
                        "公式内部中心化基仍取 0.62（钳制前的中心），与本声明值按构造不相等。"
                        "QA: 不应大于单项."
                    ),
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
                    # #38 改锚已落（换池批步 A1.4，2026-08-06；原「待修标记」清除）：
                    # §2.1.3(s) 的 MBI5 锚在「监督 RI ≠ 检验 RI」（role split），旧锚
                    # admin-churn 系语义错挂——真依赖已改为
                    # `procedure.repair_supervising_ri.appointment.completed`（槽 4，
                    # G 组记录 order 25.5 补实采），mbi5 sampling_order 6 → 25.7。
                    # 本行 conditional_inputs 仍是**死文本**（`_apply_round6_round7_
                    # overlays` 用公式 term 键集整体改写，#37 丙路同步行），活公式见
                    # round6_formulas.py mbi5 条目；分布待授权门重估
                    # （distribution_source 由 overlay 标 PLACEHOLDER）。
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
                # ===== C2. reporting 三根轴（呈交/送达/签署，2026-08-03 规格 v1）=====
                # 🔴 与 C 段的 20 个 artifact.* 槽**不同构的一点**：这四槽带
                # `qualifier_axis_product`——采样器按轴积逐组合独立采样，每组合
                # 一条事实（qualifiers 带 artifact_key ＋ actor_role_key）。
                # 轴积从卡侧 45 处引用实取（拒绝拍脑袋），角色取值全部来自
                # `actor_role_crosswalk.WORLD_ROLE_VOCABULARY`（合并词已拆）。
                # ⚠️ 只补状态布尔，不补时限（决策门 Q2=C）；加槽即换池（Q3=C）。
                {
                    "slot_id": "reporting.artifact.submitted",
                    "granularity": "building",
                    "sampling_order": 48,
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.87,
                    "conditional_inputs": [],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_reporting_axes_20260803",
                    "aliases": [], "notes": "已呈交给某方（MBIS 下呈交对象均为建築事務監督）。",
                    "qualifier_axis_product": [
                        {"artifact_key": k, "actor_role_key": "ba"}
                        for k in [
                            "report.inspection", "form.mbi3_or_mbi3a",
                            "notice.ri_appointment", "notice.ri_temporary_nomination",
                            "proposal.repair_revision", "report.completion",
                            "form.mbi4", "proposal.supervision", "form.mbi5",
                            "notice.temporary_ri_nomination_cessation",
                            "notice.ri_cessation",
                            "notice.representative_appointment_intended",
                            "notice.detailed_investigation_intention",
                        ]
                    ],
                },
                {
                    "slot_id": "reporting.artifact.delivered",
                    "granularity": "building",
                    "sampling_order": 49,
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.78,
                    "conditional_inputs": [],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_reporting_axes_20260803",
                    "aliases": [], "notes": "已送达给某方（角色按条款各异，组合从卡实取）。",
                    "qualifier_axis_product": [
                        {"artifact_key": "record.inspection_log", "actor_role_key": "owner"},
                        {"artifact_key": "record.inspection_log", "actor_role_key": "occupant_or_resident"},
                        {"artifact_key": "report.inspection", "actor_role_key": "rc"},
                        {"artifact_key": "report.inspection", "actor_role_key": "owner"},
                        {"artifact_key": "form.mbi3_or_mbi3a", "actor_role_key": "rc"},
                        # §2.1.3(q)：修葺建議修訂须于向監督呈交同日送交註冊承建商
                        {"artifact_key": "proposal.repair_revision", "actor_role_key": "rc"},
                        # §2.1.3(r)：完工報告及 MBI4 同日送交該名由他人代為進行訂明修葺的人
                        {"artifact_key": "report.completion",
                         "actor_role_key": "person_for_whom_prescribed_repair_is_carried_out"},
                        {"artifact_key": "form.mbi4",
                         "actor_role_key": "person_for_whom_prescribed_repair_is_carried_out"},
                    ],
                },
                {
                    "slot_id": "reporting.record.submitted",
                    "granularity": "building",
                    "sampling_order": 50,
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.84,
                    "conditional_inputs": [],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_reporting_axes_20260803",
                    "aliases": [],
                    # 🔴 本槽**同时服务两组收件人**（#29 甲案，2026-08-05 决策门裁定）。
                    #
                    # 守则文本本身就是这个形状，不是接线的意外——同一节 §3.6.2 内部即两个收件人：
                    #   · (A)(d) 檢驗日誌「呈交**屋宇署**」；
                    #   · (B) 引出句「並向**建築事務監督**報告」。
                    # 全文计数佐证：`屋宇署` 30 处 / `建築事務監督` 102 处，用法有清晰分野。
                    #
                    # 实测：引用本槽 `{artifact_key=record.inspection_log}` 的卡**共 10 张**——
                    #   bd（屋宇署）4 张＝五条平行款中的 §3.3.2(A)(c) / §3.5.2(A)(c) /
                    #                    §3.6.2(A)(d) / §3.7.1(d)（逐字同文，#29 已改）；
                    #   ba（建築事務監督）6 张＝§3.6.2(B)(a) / §3.6.2(B)(b) / §3.6.3(b) /
                    #                    §4.4.3（原文确为建築事務監督，**不该改**）
                    #                    ＋ §3.6.3(c) 两卡（原文写屋宇署，挂 #29b 独立语义裁定）。
                    #
                    # ⚠️ 此处**曾**写过一句「全库没有任何卡要求『檢驗日誌呈交建築事務監督』，
                    # 保留 ba 组合＝造一条无卡消费的空事实」——**该前提已实测证伪并作废**
                    # （底稿 §4.2 同步已加作废注记）。删掉 ba 格不是「不造空事实」，
                    # 而是**删掉上面 6 张卡正在读的那条事实**，会把它们打成
                    # `blocked/qualifier_conflict`——即把一个**证据力**问题误记成**供给缺口**。
                    #
                    # 🔴 ba 格只为保持那 6 张射程外卡的既有供给态；**其证据力未裁，属 #33**。
                    # 那 6 张卡在 A′ 值消费授权表里**零行** ⇒ 本格结构上无 satisfied 出口
                    # （见 `test_ba_bd_recipient_alignment.py` 的零行断言＋变异对照）。
                    "notes": "檢驗日誌／檢驗記錄已呈交。本槽同时服务屋宇署(bd)与"
                             "建築事務監督(ba)两组收件人：bd 对应 §3.3.2(A)(c) / "
                             "§3.4.2(A)(b) / §3.5.2(A)(c) / §3.6.2(A)(d) / §3.7.1(d) "
                             "五条平行款（原文逐字「呈交屋宇署」）；ba 对应 §3.6.2(B) / "
                             "§3.6.3(b) / §4.4.3 等（原文逐字「建築事務監督」）。",
                    "qualifier_axis_product": [
                        # 🔴 ba 格**逐字保持 #29 之前的原样**：`sub_rng` 是纯键派生、
                        # 键里带 combo_key（`sidecar.py` 轴积分支 → `rng_domains.sub_rng`），
                        # 键一字不差才谈得上「既有行不位移」。别调整键序或写法。
                        {"artifact_key": "record.inspection_log", "actor_role_key": "ba"},
                        # bd 格＝#29 本体（五条平行款的正确收件人）。
                        # 追加一格**不位移任何其它抽样**（各组合独立键控子流），
                        # 代价＝每栋 +1 行。⚠️ 底稿 §4.4 末段算的「+14 行／+7.53%」是
                        # 「两个槽都加 bd」那一档，**与本处（单槽 +1 行）差一个数量级，别错引**。
                        {"artifact_key": "record.inspection_log", "actor_role_key": "bd"},
                    ],
                },
                {
                    "slot_id": "reporting.artifact.signed",
                    "granularity": "building",
                    "sampling_order": 51,
                    "value_type": "bool", "enum_values": [],
                    "prevalence": 0.93,
                    "conditional_inputs": [],
                    "conditional_formula": None, "carrier_domain": "artifact",
                    "source_attribution": "proagent_engineering_estimate_reporting_axes_20260803",
                    "aliases": [], "notes": "已簽署（§7.2.3；无角色维度）。",
                    "qualifier_axis_product": [
                        {"artifact_key": "report.inspection"},
                    ],
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
                # ===== G. 池 v2 供给侧新槽（#38，换池批步 A1.3，2026-08-06）=====
                # 授权：`决议_38裁定_20260806.md` §二「登记先行、采样随池 v2、分布授权
                # 随批」＋`技术与研究债.md`「#38 换池批供给侧项」＋总工单 A1.3。
                # 公式由 `_apply_pool_v2_supply_overlay` 从
                # `round6_formulas.build_pool_v2_supply_slot_specs` 灌入（fail-closed，
                # 死声明补公式同款纪律）。🔴 三槽 prevalence 与公式系数是结构占位的
                # 工程推导值（同表比值法，46/47 号槽先例），**未经分布授权门**——
                # distribution_source 由 overlay 标 PLACEHOLDER，A1.6 门检
                # （分布来源表零 PLACEHOLDER）裁定后换实值。采样序取非整避让
                # （32.5 / 34.5 / 25.5），不平移既有 1-45 与 46-51。
                {
                    # #38 槽 2 主案：附錄六第 6 段「发现不一致事项」事件——
                    # sp2 记录（order 33）的真前件；发现是隐变量的历史至此结束。
                    # granularity 缺省 fragment：发现发生在到场监督的具体部位，
                    # 与 site_visit / sp2 家族同粒度；楼级读数经
                    # BUILDING_READING_AGGREGATION["supervision.nonconformity.found"]
                    # = any_true 聚合（任一部位发现即楼级成立，与 sp2 同语义）。
                    "slot_id": "supervision.nonconformity.found",
                    "value_type": "bool", "enum_values": [],
                    # 0.22 = sp2 记录 0.20 ÷ 最保守事件→文书比值 0.9286（占位待授权）
                    "prevalence": 0.22,
                    "conditional_inputs": ["supervision.site_visit.performed", "artifact.record.test_or_material_witness", "H.nonconformity_risk", "H.defect_severity_score", "H.repair_complexity_score"],
                    "conditional_formula": None, "carrier_domain": "supervision",
                    "sampling_order": POOL_V2_SUPPLY_SAMPLING_ORDERS["supervision.nonconformity.found"],
                    "source_attribution": "pool_v2_supply_structural_estimate_20260806_pending_authorization",
                    "cop_section": "MBIS_CoP_2023 Appendix 6 para 6 + Attachment C",
                    "aliases": [],
                    "notes": (
                        "監督期間發現不一致事項（附錄六第 6 段）；sp2 不符合記錄的真前件事件。"
                        "override（sapp6_p6 卡）自過渡態 verification.test.failed 改綁本槽。"
                    ),
                },
                {
                    # #38 槽 3：修葺建議修訂已呈交建築事務監督。仅作乙#11 期限锚
                    # `duration.delivery.repair_revision_proposal` 的 carrier /
                    # time_anchor_key，**不登记 trigger 角色**（主案已把适用层移到
                    # `procedure.repair.revision_required`）。行政一次性事件，楼级。
                    "slot_id": "procedure.repair.revision_proposal.submitted_to_ba",
                    "granularity": "building",
                    "value_type": "bool", "enum_values": [],
                    # 0.17 = revision_required 0.18 × 同表文书履行比值 0.9444（占位待授权；
                    # glm 起点＝revision_required(0.1839) 子集）
                    "prevalence": 0.17,
                    "conditional_inputs": ["procedure.repair.revision_required"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "sampling_order": POOL_V2_SUPPLY_SAMPLING_ORDERS["procedure.repair.revision_proposal.submitted_to_ba"],
                    "source_attribution": "pool_v2_supply_structural_estimate_20260806_pending_authorization",
                    "cop_section": "MBIS_CoP_2023 §2.1.3(p)-(q)",
                    "aliases": [],
                    "notes": (
                        "修葺建議修訂已呈交建築事務監督（§2.1.3(p)-(q) 同日限体）；"
                        "仅乙#11 期限锚 carrier，不作 trigger——(p)/(q) 适用层锚在 revision_required。"
                    ),
                },
                {
                    # #38 槽 4：另聘（≠检验 RI 的）修葺监督 RI 委任完成——§2.1.3(s)/
                    # §6.4.3。甲#9 期限锚 `duration.notification.appointment_supervising_ri
                    # .to_ba` 以本槽为 carrier；mbi5 表单公式（order 25.7）依赖本槽。
                    # 序 25.5＝修葺开工(25)后、监督活动(26+)前——委任先于该 RI 到场。
                    # 「防同一 RI 情形误生成」：世界不建模 RI 身份，槽真值本身即
                    # 「另一名」情形标记；正耦合只挂行政更替事件（同/异 RI 的世界内
                    # 唯一判别量）＋修葺已开工，anchor 稀有档——非更替、非修葺楼
                    # 几乎不出真值（§6.4.3 对照）。行政一次性事件，楼级。
                    "slot_id": "procedure.repair_supervising_ri.appointment.completed",
                    "granularity": "building",
                    "value_type": "bool", "enum_values": [],
                    # 0.075 = mbi5 0.07 ÷ 0.9286（MBI5 是本事件的法定文书；占位待授权）
                    "prevalence": 0.075,
                    "conditional_inputs": ["procedure.repair.prescribed.started", "procedure.ri_role.terminated", "procedure.temp_ri_nomination.terminated"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "sampling_order": POOL_V2_SUPPLY_SAMPLING_ORDERS["procedure.repair_supervising_ri.appointment.completed"],
                    "source_attribution": "pool_v2_supply_structural_estimate_20260806_pending_authorization",
                    "cop_section": "MBIS_CoP_2023 §2.1.3(s) + §6.4.3-§6.4.4",
                    "aliases": [],
                    "notes": (
                        "由另一名註冊檢驗人員監督訂明修葺的委任已完成（§2.1.3(s)）；"
                        "甲#9 期限锚 carrier；mbi5 表单的正确依赖（#38 改锚）。"
                    ),
                },
                # ===== F. 条款前件补槽（2026-07-31，缺省等价追加）=====
                # 背景：33 张法规卡漏掉了条款自身的前件（「如…則須…」的「如」那半），
                # 对每栋楼无条件开火。把前件映射回世界槽时发现两个前件世界侧无槽——
                # 本组补的就是这两个。**卡侧接线不在本次范围**（新槽当前无消费者）。
                #
                # 为什么 sampling_order 必须比全部既有槽大（46/47 > 既有 max 45）：
                # sidecar 采样按 (sampling_order, slot_id) 升序遍历同一条 rng 流
                # （sidecar.py `ordered_records`）。排在最后 ⇒ 既有 45+1 个槽的
                # rng 消费序列逐位不变。**注意这只保住「同一条 rng 流内的相对顺序」**：
                # sidecar 子 rng 的种子是 deterministic_key（validation.py），而
                # deterministic_key ← registry_bundle_hash ← 整个 registry 内容，
                # 故往本表加记录必然换种子、既有槽的**取值**仍会整体改变。
                # 世界核心（generate_world_batch）按 `seed` 独立播种，不受影响。
                #
                # 两条记录都走 marginal 路径（conditional_formula=None，与
                # actor.representative.assigned_role 同）：Round6/7 overlay 只 patch
                # MARGINAL_ANCHORS_ROUND7 键集内的 45 条，本组不在其中，故
                # sampling_order / prevalence 由本记录自己写死、不会被 overlay 覆盖。
                {
                    # MBIS_CoP_2023 §2.1.3(n)（中文正文 page 14）：
                    # 「以書面通知建築事務監督其有意進行詳細調查，並呈交有關建議給建築事務監督認可」
                    # ⇒ 义务本体 = 通知 + 呈交；前件 = 「有意進行詳細調查」本身。
                    # 🔴 不可拿 procedure.investigation.intention_notified 当它的前件：
                    #    那是本义务的**履行**（已书面通知），拿履行当前提 = 用结论当前提。
                    #    也不可拿 procedure.investigation.started（已开始 ≠ 有意）。
                    "slot_id": "procedure.investigation.detailed.intended",
                    "granularity": "building",  # 行政一次性事件，与 intention_notified /
                                                # proposal.submitted / proposal.recognized 同粒度
                    "value_type": "bool", "enum_values": [],
                    # prevalence 依据（本表内比值反推，非凭空取值）：
                    #   「有意」是「已書面通知有意」的上游，通知履行率 <100% ⇒ intended > notified(0.30)。
                    #   本表既有 5 组「事件 → 其法定文书」比值：
                    #     mbi4/repair.completed=0.9286、report.completion/repair.completed=0.9524、
                    #     proposal.repair_revision/repair.revision_required=0.9444、
                    #     mbi3/inspection.completed=0.9730、mbi2/temp_nomination=1.0000
                    #   （mbi1/ri.appointment=1.1047 本身不自洽，排除）。取最保守的 0.9286 反推：
                    #     0.30 / 0.9286 = 0.3231 → 0.32（隐含通知履行率 0.30/0.32 = 93.8%）。
                    "prevalence": 0.32,
                    # 与 intention_notified 同一组物理驱动（意图源于欠妥成因/范围不确定）。
                    # 三者都是 world_core 物理槽，不是 sidecar bool 槽 ⇒ 楼级上游解析返回
                    # None、不触发跨粒度 fail-fast；DAG「上游 order < 本槽」对物理输入不适用。
                    "conditional_inputs": ["defect.cause_or_extent.uncertain", "defect.class.present", "risk.building_safety.emergency"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "sampling_order": 46,
                    "source_attribution": "engineering_estimate_precondition_gap_20260731_ratio_derived_from_in_table_document_compliance",
                    "cop_section": "MBIS_CoP_2023 §2.1.3(n)",
                    "aliases": [],
                    "notes": (
                        "註冊檢驗人員「有意進行詳細調查」的意图状态；§2.1.3(n) 通知/呈交义务的前件。"
                        "与 procedure.investigation.intention_notified（该义务的履行）严格区分。"
                        "prevalence 0.32 = notified 0.30 ÷ 本表最保守的事件→文书比值 0.9286；工程估值。"
                    ),
                },
                {
                    # MBIS_CoP_2023 §4.3.3(a)（中文正文 page 41）：
                    # 「註冊檢驗人員須根據詳細調查的結果進行評估，以確定有關結構構件的安全水平，
                    #   並提出相應的跟行動。」
                    # ⇒ 前件 = 「已有詳細調查的結果」。世界此前只有「已開始」，无「已有结果」。
                    "slot_id": "procedure.investigation.detailed.completed",
                    # granularity 缺省 = fragment：詳細調查针对具体结构构件做，结果按部位存在；
                    # 与直接上游 procedure.investigation.started、以及
                    # procedure.repair.prescribed.completed / inspection.prescribed.completed 同粒度。
                    # 楼级读数由 BUILDING_READING_AGGREGATION[.completed]="any_true" 提供聚合行。
                    "value_type": "bool", "enum_values": [],
                    # prevalence 依据：本表**唯一**的同族 started→completed 对是
                    #   procedure.repair.prescribed.started 0.55 → .completed 0.42，比值 0.7636。
                    #   套到 procedure.investigation.started 0.20：0.20 × 0.7636 = 0.1527 → 0.15。
                    #   满足「低于其上游」（0.15 < 0.20）。
                    "prevalence": 0.15,
                    "conditional_inputs": ["procedure.investigation.started", "procedure.investigation.proposal.recognized", "defect.cause_or_extent.uncertain"],
                    "conditional_formula": None, "carrier_domain": "procedure",
                    "sampling_order": 47,
                    "source_attribution": "engineering_estimate_precondition_gap_20260731_ratio_derived_from_in_table_started_completed_pair",
                    "cop_section": "MBIS_CoP_2023 §4.3.3(a)",
                    "aliases": [],
                    "notes": (
                        "詳細調查已完成／結果已得出；§4.3.3(a)「根據詳細調查的結果進行評估」的前件。"
                        "与 procedure.investigation.started（已開始 ≠ 有結果）严格区分。"
                        "prevalence 0.15 = started 0.20 × 本表唯一 started→completed 比值 0.7636；工程估值。"
                    ),
                },
            ],
        )
    )

    # DEBT-020 Round 6 + Round 7 落地（2026-05-11）：把 round6_formulas 模块构造的
    # centered upstream conditional_formula + Round 7 anchor 修订 + sampling_order +
    # COP 章节引用 + alignment_check overlay 到 sidecar_bool_slot_registry 45 records.
    _apply_round6_round7_overlays(registries)

    # 死声明补公式（2026-08-05，决议_33处置_20260805.md §一.1 零边际成本段）。
    # 🔴 顺序必须在 Round6/7 overlay **之后**：那一轮按 slot_id 命中才 patch，
    # 本轮的 3 个槽不在它的 45 条射程内，两轮零交集（有交集即违例，闸在
    # `_apply_precondition_coupling_overlay` 里）。
    _apply_precondition_coupling_overlay(registries)

    # 池 v2 供给侧三新槽公式（#38，换池批步 A1.3，2026-08-06）——同款 fail-closed。
    _apply_pool_v2_supply_overlay(registries)

    # A1.6 乙路：楼级消费者读碎片级上游时中心化基改取聚合后期望
    # （决议_A16裁定_20260806 §一.2）。🔴 顺序必须在**全部**公式 overlay 之后
    # ——它按 slot_id 机械枚举现存公式，跑在前面就会漏掉后落的那批
    # （#33 的 `.intended` 与 #38 的槽 4 都是本 overlay 的成员）。
    _apply_a16_building_aggregation_centering(registries)

    # 生成器自检（换池批步 A1.4 验收；spec 06 §11.6.7 DAG validity）：
    # 此前该校验只存在于注释与测试（`conditional_eval.py:147` 的「build 时校验」
    # 是不实陈述——2026-08-06 勘察坐实），DAG 重排批把它焊成构造期硬闸。
    _validate_sidecar_sampling_dag(registries)

    return RegistryBundle(generated_at=_utc_now_iso(), source_documents=list(SOURCE_DOCUMENTS), registries=registries)


# DEBT-020 Round 7 §3 alignment_check (10000 MC, seed=20260511) 实测 delta < 0.05.
# 见 round6_formulas.py + DEBT-020 Round 7 §3 alignment_results.
# 这里的 observed_marginal 是 Round 7 §3 的 reference value。
# ⚠️ 2026-08-06（#37）：原注释声称「W0 实跑时会按 release batch 重新计算（通过
# sidecar.py:_run_alignment_check_for_release_batch 校验）」——**该函数全仓不存在**
# （量化与两线商议独立复核，唯一命中即注释本身），没有任何运行时机制会把过期
# 徽章报出来，已删。真复检器记债不实施（归分布授权流水线远期，
# 决议_37修法_20260805 §一.5）。下表 observed 是 2026-05-11 MC 的历史参考值：
# 2026-07-07 粒度两相分派（7a82118）后即过期，45 条徽章已整体降级
# `stale_round7_mc_granularity_split`（见 `_apply_round6_round7_overlays`）；
# MC 重跑归换池批（sidecar 重采样后、W2 投影前），通过后按新档位名重盖。
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


# ===================================================================== #
# A1.6 分布授权门 MC 重跑徽章（2026-08-06）
# ===================================================================== #
#
# 授权：`决议_A16裁定_20260806.md` §三「32 走 MC 后自动重盖（fail 者逐槽当场补裁）」
# ＋ §四 MC 实跑规格；实测见 `实施记录_A16落地_20260806.md` §三。
#
# 与 `_ROUND7_ALIGNMENT_REFERENCE` 的**三点不同**（每点都是有意的）：
# 1. **跑在生产两相分派编排器上**（`_sample_sidecar_bool_slots_for_building`），
#    楼级槽只见楼级可得集、碎片上游按 `BUILDING_READING_AGGREGATION` 聚合——
#    这正是 2026-05-11 那次 MC 缺的那一半，也是 45/45 徽章整体过期的原因；
# 2. **口径显式登记**（下方 `_A16_MC_BADGE_HEADER`）：`seed_tag` 取代旧 `seed`
#    整数（工具是键控子流，种子是字符串标签）；新增 `fragments_per_building`
#    ——k 承重，聚合期望是 k 的函数，不记 k 的徽章无从复现；
# 3. **状态名带池身份**：`passed_pool_v2_mc_20260806`，不复用
#    `passed_round7_mc`——那是另一个上下文里的另一次实验，同名会让下一个人
#    以为徽章没换过。
#
# 🔴 诚实边界（三条，别被「45/45 全绿」读成「分布真实」）：
# ① 本徽章证明的是**实现一致性**（代码按 registry 的声明在采样），
#    不是「真实池分布符合工程预期」——后者归换池批 D 步实测（决议 §一.1 分界句）；
# ② `fragments_per_building=4` 是 MC 口径常数，生产池的每栋碎片数是**分布**；
# ③ 三个 #33 死声明补公式槽与三个 #38 新槽**同批过了这次 MC 但不写徽章**
#    ——沿用 `_apply_precondition_coupling_overlay` 的既有纪律（那两轮 overlay
#    从设计上就不写 `alignment_check`）。属**少声明**、不属虚报；要给它们发徽章
#    得先改那两轮 overlay 的纪律，超出 A1.6 射程，已入停下事项。
_A16_MC_BADGE_HEADER: Dict[str, Any] = {
    "monte_carlo_n": 10000,
    "seed_tag": "mc_gate_poolv2_20260806",
    "fragments_per_building": 4,
    "pass_threshold": 0.05,
    "status": "passed_pool_v2_mc_20260806",
    "context_caliber": (
        "hidden=prior_means; physical=absent(0.0, legacy-MC caliber); "
        "building_context=neutral; dispatcher=production two-phase"
    ),
}

# 逐槽 observed / delta：**由 `rerun_distribution_mc.py` 的门检跑报告机器生成**
# （`杂物箱/备份_A16落地_20260806/mc产物/`），不是手抄。
_A16_POOL_V2_MC_ALIGNMENT: Dict[str, Dict[str, Any]] = {
    "artifact.certificate.material_or_product": {"observed": 0.4352, "delta": 0.0052},
    "artifact.form.mbi1": {"observed": 0.9468, "delta": -0.0032},
    "artifact.form.mbi2": {"observed": 0.0832, "delta": 0.0032},
    "artifact.form.mbi3_or_mbi3a": {"observed": 0.7097, "delta": -0.0103},
    "artifact.form.mbi4": {"observed": 0.3932, "delta": 0.0032},
    "artifact.form.mbi5": {"observed": 0.073, "delta": 0.003},
    "artifact.notice.investigation_intention": {"observed": 0.3173, "delta": 0.0173},
    "artifact.photo.annotated": {"observed": 0.6947, "delta": -0.0053},
    "artifact.plan.annotated": {"observed": 0.6399, "delta": -0.0001},
    "artifact.proposal.detailed_investigation": {"observed": 0.315, "delta": 0.015},
    "artifact.proposal.repair": {"observed": 0.5657, "delta": -0.0043},
    "artifact.proposal.repair_revision": {"observed": 0.178, "delta": 0.008},
    "artifact.record.inspection_log": {"observed": 0.7751, "delta": -0.0049},
    "artifact.record.nonconformity_sp2": {"observed": 0.2084, "delta": 0.0084},
    "artifact.record.supervision_log_sp1": {"observed": 0.6036, "delta": -0.0064},
    "artifact.record.test_or_material_witness": {"observed": 0.4411, "delta": 0.0011},
    "artifact.report.completion": {"observed": 0.3841, "delta": -0.0159},
    "artifact.report.inspection": {"observed": 0.72, "delta": -0.01},
    "artifact.statement.extra_works_separated": {"observed": 0.1951, "delta": 0.0051},
    "artifact.statement.scope_and_order_coverage": {"observed": 0.5715, "delta": -0.0085},
    "fire_safety.upgrade_outstanding": {"observed": 0.1598, "delta": -0.0002},
    "procedure.completed_work.final_inspection_performed": {"observed": 0.3935, "delta": -0.0065},
    "procedure.inspection.prescribed.completed": {"observed": 0.739, "delta": -0.001},
    "procedure.investigation.intention_notified": {"observed": 0.3003, "delta": 0.0003},
    "procedure.investigation.proposal.recognized": {"observed": 0.1906, "delta": 0.0106},
    "procedure.investigation.proposal.submitted": {"observed": 0.3104, "delta": 0.0104},
    "procedure.investigation.started": {"observed": 0.2168, "delta": 0.0168},
    "procedure.rc.pre_notification_given": {"observed": 0.5022, "delta": 0.0022},
    "procedure.repair.prescribed.completed": {"observed": 0.4039, "delta": -0.0161},
    "procedure.repair.prescribed.started": {"observed": 0.5462, "delta": -0.0038},
    "procedure.repair.revision_required": {"observed": 0.1896, "delta": 0.0096},
    "procedure.ri.appointment.completed": {"observed": 0.8623, "delta": 0.0023},
    "procedure.ri_role.terminated": {"observed": 0.0629, "delta": 0.0029},
    "procedure.supervision_representative.planned": {"observed": 0.6538, "delta": -0.0062},
    "procedure.supervision_team.changed": {"observed": 0.1203, "delta": 0.0003},
    "procedure.supervision_team.submitted": {"observed": 0.5778, "delta": -0.0022},
    "procedure.temp_ri_nomination.completed": {"observed": 0.0811, "delta": 0.0011},
    "procedure.temp_ri_nomination.terminated": {"observed": 0.0308, "delta": 0.0008},
    "qual.actor_role": {"observed": {"registered_inspector": 0.5767, "registered_contractor": 0.2243, "building_authority": 0.1019, "owner": 0.0971}, "max_class_delta": 0.0043},
    "qual.artifact_field_group": {"observed": {"form_metadata": 0.2208, "repair_proposal": 0.1814, "supervision_record": 0.1985, "completion_report": 0.1223, "evidence_photo": 0.1572, "evidence_plan": 0.1199}, "max_class_delta": 0.0028},
    "qual.method_class": {"observed": {"visual_inspection": 0.3335, "pull_test": 0.1258, "hammer_tapping": 0.2163, "drainage_cctv": 0.0971, "water_test": 0.0495, "smoke_test": 0.0301, "material_test": 0.0947, "self_closing_test": 0.0532}, "max_class_delta": 0.0066},
    "supervision.record.completed": {"observed": 0.7108, "delta": -0.0092},
    "supervision.record.completed_and_retained": {"observed": 0.382, "delta": -0.008},
    "supervision.record.retained": {"observed": 0.6734, "delta": -0.0066},
    "supervision.site_visit.performed": {"observed": 0.7923, "delta": -0.0077},
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
            # #37 丙路一行同步（决议_37修法_20260805 §一.1）：`conditional_inputs`
            # 改写为公式真实 term 键集（sidecar ＋ hidden）。生产楼级采样只读
            # `conditional_inputs` 决定解析哪些上游（sidecar.py:_sample_sidecar_
            # bool_slots_for_building），`upstream_inputs` 全仓零运行时消费者；
            # 两份清单对不上正是 #37 两个半（H.* 缺键 ＋ 11 条非 H 缺键）都能长期
            # 潜伏的共同结构原因。#33 的 `_apply_precondition_coupling_overlay`
            # 从一开始就同步（可行形反证），这里补齐。4 条未声明的楼级间依赖
            # （ri_role.terminated×2 / supervision_representative.planned /
            # supervision_team.submitted）也由本行一并声明。
            record["conditional_inputs"] = (
                list(spec["upstream_inputs"].get("sidecar", []))
                + list(spec["upstream_inputs"].get("hidden", []))
            )
            record["marginal_anchor"] = anchor_value
            record["anchor_source"] = ANCHOR_SOURCES_ROUND7[slot_id]
            # 徽章沿革（两段，别删前一段——它解释了为什么会有第二段）：
            # ① #37（2026-08-06 上午，决议_37修法 §一.3）：45/45 整体降级
            #    `stale_round7_mc_granularity_split`。2026-05-11 那次 MC 跑在全
            #    fragment 粒度、全 term 可得的上下文；2026-07-07 粒度两相分派
            #    （7a82118）把 13 槽搬到楼级（改的不止均值，还有「逐碎片各抽 →
            #    一栋一抽广播」的楼内相关结构），传递闭包实测 45/45 带徽章槽全部
            #    在受影响集内——徽章不是伪造，是**过期**。
            # ② A1.6（2026-08-06，决议_A16裁定 §三＋§四）：MC 在生产两相编排器上
            #    重跑（n=10000, k=4, seed_tag=mc_gate_poolv2_20260806），55 槽
            #    54 判全 pass ⇒ 45 条按新档位名重盖，见 `_A16_POOL_V2_MC_ALIGNMENT`。
            # 🔴 重盖是**逐槽有实测**才盖：`_A16_POOL_V2_MC_ALIGNMENT` 缺该槽即
            # 落回 stale（fail-open 会把「没测」写成「测过了」，那是徽章装饰的
            # 原始形态——`count.pull_test` 那条反装饰闸抓的就是同一个病）。
            a16 = _A16_POOL_V2_MC_ALIGNMENT.get(slot_id)
            if a16 is not None:
                record["alignment_check"] = {**_A16_MC_BADGE_HEADER, **a16}
            else:
                record["alignment_check"] = {
                    "monte_carlo_n": 10000,
                    "seed": 20260511,
                    "pass_threshold": 0.05,
                    **alignment,
                    "status": "stale_round7_mc_granularity_split",
                    "stale_since": "2026-07-07",
                    "stale_reason": "granularity_split_lost_terms",
                }
            # #38 改锚两槽（mbi5 / sp2，换池批步 A1.3/A1.4）：公式已改、分布失据，
            # A1.6 前标 PLACEHOLDER 逼分布授权门重估（门检＝零 PLACEHOLDER），
            # 不得冒充 Round 7 MC 档位；A1.6 MC 实测两槽在原锚上过阈后换实值。
            # 其余槽：A1.6 授权集（决议 §一 13 槽 ＋ §三 补裁槽）在 Round 5 原串上
            # **加注**（官方线 §一.4：乙路下来源保持原串＋加注，不换串——换串会把
            # 「参数从哪来」这个来历抹掉）；未被 A1.6 触及的槽照旧。
            if slot_id in POOL_V2_REWIRED_OVERLAY_SLOTS:
                record["distribution_source"] = POOL_V2_REWIRED_DISTRIBUTION_SOURCE
                record["semantic_note"] = A16_MC_CALIBER_BOUNDARY_NOTE
            elif slot_id in A16_ANNOTATED_ROUND7_SLOTS:
                record["distribution_source"] = (
                    DEBT020_ROUND7_DISTRIBUTION_SOURCE
                    + A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX
                )
                record["semantic_note"] = A16_MC_CALIBER_BOUNDARY_NOTE
            else:
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
            # A1.6 补裁（决议 §三）：被 `_apply_clamps` 钳制的槽，**声明的实现边际**
            # 与公式内部的 centering anchor 按构造不相等——推导与裁定理由见
            # `round6_formulas.POST_CLAMP_REALIZED_MARGINALS` 段。
            # 只覆盖 `marginal_anchor` / `prevalence`（门检④ 与产物读这两个），
            # `conditional_formula["anchor"]` 保持钳制前的中心不动。
            realized = POST_CLAMP_REALIZED_MARGINALS.get(str(slot_id))
            if realized is not None:
                record["marginal_anchor"] = float(realized)
                record["prevalence"] = float(realized)
            # marker source_attribution 升级到 Round 7
            record["source_attribution"] = (
                f"{record.get('source_attribution', '')} | "
                f"DEBT020_round7_centered_upstream_conditional_2026_05_11"
            ).strip(" |")


class PreconditionCouplingOverlayError(RuntimeError):
    """死声明补公式 overlay 的 fail-closed 违例（构造期即炸，不静默降级）。"""


def _apply_precondition_coupling_overlay(registries: List[RegistryTable]) -> None:
    """给 3 个「声明了条件依赖却无公式」的槽装上真公式（工程估计档）。

    与 `_apply_round6_round7_overlays` 的**四点不同**（每点都是有意的）：
    1. **不动 `sampling_order`**——改序会挪 DAG 拓扑，代价远大于本段要解决的问题；
    2. **不动 `prevalence` / `marginal_anchor`**——本段建立的是条件依赖，不重新标定边际；
    3. **不写 `alignment_check`**——这批没过 10,000 样本 MC 对齐闸，写了就是伪造档位。
       档位由 `distribution_source` 如实声明为工程估计；边际漂移由测试实测看住；
    4. **同批改写 `conditional_inputs` 成求值器认得的真名**——旧名字里有
       `risk.building_safety.emergency` 这种**整个求值上下文里根本不存在**的键，
       而 `_eval_centered_linear` 对缺失键**静默取 0.0**（不抛异常、不回退），
       留着旧名字＝把「声明与执行不一致」这个坑原样埋回去。

    fail-closed：三种情形直接抛（构造期炸，比运行期静默错好）——
    ①与 Round6/7 射程有交集（说明该槽本该走那一轮）；②目标槽不在注册表；
    ③目标槽已经有公式（说明上游改了而本表没跟）。
    """
    formulas = get_precondition_coupling_formulas()
    r6_slots = set(get_round6_round7_formulas())
    overlap = r6_slots & set(formulas)
    if overlap:
        raise PreconditionCouplingOverlayError(
            f"死声明补公式与 Round6/7 射程重叠：{sorted(overlap)}"
            "——重叠槽应走 Round6/7 那一轮，不该在此重复 patch")
    patched: set = set()
    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            slot_id = record.get("slot_id")
            spec = formulas.get(str(slot_id or ""))
            if spec is None:
                continue
            if record.get("conditional_formula") is not None:
                raise PreconditionCouplingOverlayError(
                    f"{slot_id} 已带公式——上游变了而本表没跟，拒绝覆盖")
            record["conditional_formula"] = spec["conditional_formula"]
            # 声明与执行对齐：换成求值器真认得的键名（见 docstring 第 4 点）。
            record["conditional_inputs"] = list(spec["conditional_inputs"])
            record["upstream_inputs"] = spec["upstream_inputs"]
            record["anchor_source"] = spec["anchor_source"]
            record["distribution_source"] = PRECONDITION_COUPLING_DISTRIBUTION_SOURCE
            record["source_attribution"] = (
                f"{record.get('source_attribution', '')} | "
                f"{PRECONDITION_COUPLING_DISTRIBUTION_SOURCE}"
            ).strip(" |")
            patched.add(str(slot_id))
    missing = set(formulas) - patched
    if missing:
        raise PreconditionCouplingOverlayError(
            f"死声明补公式的目标槽不在 sidecar_bool_slot_registry：{sorted(missing)}")


class PoolV2SupplyOverlayError(RuntimeError):
    """池 v2 供给侧公式 overlay 的 fail-closed 违例（构造期即炸，不静默降级）。"""


def _apply_pool_v2_supply_overlay(registries: List[RegistryTable]) -> None:
    """给 #38 三新槽（G 组记录）装上条件公式（换池批步 A1.3，2026-08-06）。

    与死声明补公式同款纪律：**不动 `sampling_order` / `prevalence` /
    `granularity`**（由 G 组记录本体持有）；fail-closed 三情形——
    ①与 Round6/7 或死声明补公式射程有交集；②目标槽不在注册表；
    ③目标槽已带公式（上游改了而本表没跟）。
    分布纪律见 `round6_formulas.py` POOL_V2_SUPPLY_* 段：三槽参数已由
    A1.6 分布授权门裁定（决议_A16裁定_20260806 §二），`distribution_source`
    由 PLACEHOLDER 换实值并挂口径分界句。
    """
    formulas = get_pool_v2_supply_slot_specs()
    prior_scopes = set(get_round6_round7_formulas()) | set(
        get_precondition_coupling_formulas()
    )
    overlap = prior_scopes & set(formulas)
    if overlap:
        raise PoolV2SupplyOverlayError(
            f"池 v2 供给侧公式与既有 overlay 射程重叠：{sorted(overlap)}"
            "——重叠槽应走既有那一轮，不该在此重复 patch")
    patched: set = set()
    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            slot_id = record.get("slot_id")
            spec = formulas.get(str(slot_id or ""))
            if spec is None:
                continue
            if record.get("conditional_formula") is not None:
                raise PoolV2SupplyOverlayError(
                    f"{slot_id} 已带公式——上游变了而本表没跟，拒绝覆盖")
            record["conditional_formula"] = spec["conditional_formula"]
            record["conditional_inputs"] = list(spec["conditional_inputs"])
            record["upstream_inputs"] = spec["upstream_inputs"]
            record["anchor_source"] = spec["anchor_source"]
            record["distribution_source"] = POOL_V2_SUPPLY_DISTRIBUTION_SOURCE
            record["semantic_note"] = A16_MC_CALIBER_BOUNDARY_NOTE
            patched.add(str(slot_id))
    missing = set(formulas) - patched
    if missing:
        raise PoolV2SupplyOverlayError(
            f"池 v2 供给侧公式的目标槽不在 sidecar_bool_slot_registry：{sorted(missing)}")


class BuildingAggregationCenteringError(RuntimeError):
    """A1.6 楼级聚合中心化 overlay 的 fail-closed 违例（构造期即炸）。"""


def _aggregated_reading_expectation(
    fragment_marginal: float, aggregation: str, k: int
) -> float:
    """碎片级槽被楼级消费者读到时的**聚合读数期望**（独立近似，k 钉 MC 口径）。

    `any_true`  ⇒ 1 − (1 − p)^k       （任一碎片为真即楼级为真）
    `all_true`  ⇒ p^k                 （全部碎片为真才算楼级为真）
    """
    p = float(fragment_marginal)
    if aggregation == "any_true":
        return 1.0 - (1.0 - p) ** k
    if aggregation == "all_true":
        return p ** k
    raise BuildingAggregationCenteringError(
        f"未知聚合语义 {aggregation!r}——BUILDING_READING_AGGREGATION 只认 "
        "any_true / all_true")


def _apply_a16_building_aggregation_centering(
    registries: List[RegistryTable],
) -> Dict[str, Dict[str, float]]:
    """A1.6 乙路：楼级消费者读碎片级上游时，中心化基改取**聚合后期望**。

    （`决议_A16裁定_20260806.md` §一.2 ＋ 官方线 §1.3 乙路。）

    🔴 病灶（不是标定偏差，是公式假设与运行时供给对不上）：
    `round6_formulas._bool_formula` 把 `upstream_expected[slot]` 一律填成该上游的
    **碎片级边际锚**。但楼级槽读到的不是碎片值，是
    `sidecar._resolve_building_upstream` 按 `BUILDING_READING_AGGREGATION` 归约出的
    **整栋读数**——`any_true` 下 k=4 会把 0.20 读成 0.59、`all_true` 下把 0.74 读成
    0.30。中心化基取错 ⇒ 中心化项不再以 0 为中心 ⇒ 楼级槽的实现边际系统性偏离
    自己的 anchor。这与 #37「公式引用楼级取不到的键、静默按 0.0 中心化」是同族
    病，只是这一半从来没被登记过（#37 量化只登记了缺键那一半）。

    🔴 成员**机械枚举**，不硬编码槽名单（官方线 §1.3 明令：不得假定恰好等于
    决议点名的那 6 个接线槽）。判据逐条：
      · 消费者 `granularity == "building"` 且带 `conditional_formula`；
      · 上游键在本注册表内、`granularity != "building"`（即碎片级）；
      · 该上游在 `BUILDING_READING_AGGREGATION` 里有声明的聚合语义
        （没有声明的键 `_resolve_building_upstream` 直接返回 None ⇒ 是缺键问题，
         归 #37，不归本 overlay）。
    枚举实测结果（2026-08-06 落地时）：**9 个消费者 / 16 条上游边**——比决议点名的
    6 个接线槽多 3 个：`procedure.rc.pre_notification_given`（量化按「H 缺键」分类算
    纯 H 槽，但它读 `artifact.proposal.repair` 这个碎片级上游，同病）、
    `procedure.investigation.detailed.intended`（#33 补的槽，根本不在那 13 个里）、
    `procedure.repair_supervising_ri.appointment.completed`（#38 槽 4，官方线 §三
    已单独点出 +0.24 logit）。⇒ 「纯 H / 接线」那条分界线量的是**缺键**，
    与本偏差族的分界线**不是同一条轴**。

    ⚠️ anchor 一个不动（决议 §一.2「禁任何槽取 MC 观测当锚」）：本 overlay 只改
    中心化常数，不改任何 `marginal_anchor` / `prevalence` / `terms` 系数。

    ⚠️ 独立近似的诚实边界：同栋碎片共享楼级上下文与 H.*，实际聚合读数带栋内相关，
    与独立式有残差。落地时实测（探针 n=3000 栋）残差最大 0.022
    （`artifact.proposal.detailed_investigation` 解析 0.7599 vs 实测 0.7377），
    余项 <0.01；残差由门检 MC 的 0.05 阈吸收，未吸收掉的走决议 §三 逐槽补裁。

    返回：{消费者槽: {上游键: 新 expected}}——供审计与测试断言取用。
    """
    granularity: Dict[str, str] = {}
    anchors: Dict[str, float] = {}
    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            sid = str(record.get("slot_id") or "")
            if not sid:
                continue
            granularity[sid] = str(record.get("granularity") or "fragment")
            anchor = record.get("marginal_anchor")
            if anchor is None:
                anchor = record.get("prevalence")
            if isinstance(anchor, (int, float)):
                anchors[sid] = float(anchor)

    k = MC_CALIBER_FRAGMENTS_PER_BUILDING
    rewritten: Dict[str, Dict[str, float]] = {}

    def _patch_block(consumer: str, block: Dict[str, Any]) -> None:
        expected = block.get("upstream_expected")
        if not isinstance(expected, dict):
            return
        for key in list(expected):
            if key.startswith("H.") or key not in granularity:
                continue  # 隐状态 / 楼级上下文键，不经聚合
            if granularity[key] == "building":
                continue  # 楼级上游直读，中心化基＝其自身 anchor，本就正确
            aggregation = BUILDING_READING_AGGREGATION.get(key)
            if aggregation is None:
                continue  # 无聚合声明 ⇒ 解析不到，属 #37 缺键，不归本 overlay
            if key not in anchors:
                raise BuildingAggregationCenteringError(
                    f"{consumer} 的碎片级上游 {key} 无数值 anchor，无法推导聚合期望")
            new_value = _aggregated_reading_expectation(anchors[key], aggregation, k)
            expected[key] = new_value
            rewritten.setdefault(consumer, {})[key] = new_value

    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            sid = str(record.get("slot_id") or "")
            if granularity.get(sid) != "building":
                continue
            formula = record.get("conditional_formula")
            if not isinstance(formula, dict):
                continue
            classes = formula.get("classes")
            if isinstance(classes, dict):  # centered_softmax_per_class
                for block in classes.values():
                    if isinstance(block, dict):
                        _patch_block(sid, block)
            else:
                _patch_block(sid, formula)
            # 被本 overlay 真改过中心化的槽**一律**挂口径分界句——判据是「有没有被改」
            # 而不是「在不在某张名单里」。名单会漏（`_apply_round6_round7_overlays`
            # 的 `A16_ANNOTATED_ROUND7_SLOTS` 就漏了 #33 的 `.intended`：它被 A1.6
            # 改了中心化，却不在决议点名的 13 槽里）；这行让「改了 = 标了」按构造成立。
            if sid in rewritten:
                record["semantic_note"] = A16_MC_CALIBER_BOUNDARY_NOTE
    return rewritten


class SidecarSamplingDagError(RuntimeError):
    """spec 06 §11.6.7 DAG validity 构造期违例（换池批步 A1.4 焊入）。"""


def _validate_sidecar_sampling_dag(registries: List[RegistryTable]) -> None:
    """构造期 DAG 硬闸：带公式槽的 sidecar 上游必须先于本槽采样。

    判据（spec 06 §11.6.7）：对 `sidecar_bool_slot_registry` 中**带
    `conditional_formula` 且带 `sampling_order`** 的每条记录，其
    `conditional_inputs` 里凡是本注册表内的槽（即 sidecar 上游；物理键 /
    H.* 不在表内、由各自上下文承载，不适用本判据），必须满足
    `上游.sampling_order` 非空且 **严格小于** 本槽——否则采样时上游未采、
    值缺席，`_eval_centered_linear` 会**静默按 0.0 中心化**（#37 病灶同形）。

    历史：`_apply_round6_round7_overlays` docstring 与 `conditional_eval.py:147`
    一直声称「build 时校验」，实际全仓只有测试级检查（2026-08-06 勘察坐实）；
    换池批 DAG 重排（mbi5 6→25.7——45.7 是被本闸当场拦下的首版错值——
    与三新槽插序）把它焊成生产 fail-fast。
    """
    order_by_slot: Dict[str, Any] = {}
    formula_records: List[Dict[str, Any]] = []
    for registry in registries:
        if registry.registry_id != "sidecar_bool_slot_registry":
            continue
        for record in registry.records:
            slot_id = str(record.get("slot_id") or "")
            if not slot_id:
                continue
            order_by_slot[slot_id] = record.get("sampling_order")
            if record.get("conditional_formula") is not None:
                formula_records.append(record)
    violations: List[str] = []
    for record in formula_records:
        my_order = record.get("sampling_order")
        if my_order is None:
            continue  # marginal 序兜底 9999，无上游先后约束可判
        for up_id in record.get("conditional_inputs") or []:
            if up_id not in order_by_slot:
                continue  # 物理键 / H.* / 楼级上下文键：不在本表，判据不适用
            up_order = order_by_slot[up_id]
            if up_order is None or float(up_order) >= float(my_order):
                violations.append(
                    f"{record.get('slot_id')}({my_order}) ← {up_id}({up_order})"
                )
    if violations:
        raise SidecarSamplingDagError(
            "sidecar 采样 DAG 违例（上游未先于本槽采样）：" + "; ".join(violations)
        )


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
            # 2026-07-31 条款前件补槽（sidecar_bool_slot_registry F 组）：
            # 与 detailed.started 不同，这两个是**真采样**的（bool registry 里有记录），
            # 不是只在 ownership 里挂个名（CLAUDE.md「140 声明 vs 46 实采」那类空头声明）。
            "procedure.investigation.detailed.intended",
            "procedure.investigation.detailed.completed",
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
            # 期限锚 duration 槽（期限锚供给案 2026-08-05）——8 条新增，全部楼级发射。
            # 它们是**真采样**的（sidecar_measurement_registry 里有完整记录 +
            # `granularity: "building"`），不是只在 ownership 里挂个名的空头声明
            # （CLAUDE.md「140 声明 vs 46 实采」那类）。
            "duration.notification.appointment_ri.to_ba",
            "duration.notification.nomination_temp_ri.to_ba",
            "duration.notification.nomination_temp_ri_terminated.to_ba",
            "duration.notification.role_ri_terminated.to_ba",
            "duration.submission.repair_revision.to_ba",
            "duration.notification.appointment_supervising_ri.to_ba",
            "duration.notification.supervision_team_changed.to_ba",
            "duration.delivery.repair_revision_proposal",
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
            # #38 槽 2（池 v2 供给侧，2026-08-06）：真采样（bool registry G 组），
            # 非空头声明；sp2 记录与 sapp6_p6 override 的真前件事件槽。
            "supervision.nonconformity.found",
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
                        # 2026-07-31 条款前件补槽（§2.1.3(n) / §4.3.3(a)）。
                        "procedure.investigation.detailed.intended",
                        "procedure.investigation.detailed.completed",
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
                        # 2026-07-31 条款前件补槽（§2.1.3(n) / §4.3.3(a)）。
                        "procedure.investigation.detailed.intended",
                        "procedure.investigation.detailed.completed",
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
    # 2026-07-31 条款前件补槽：与直接上游 procedure.investigation.started 同粒度
    # （fragment 采样）、同聚合语义（任一部位有詳細調查結果即楼级成立）。
    # 登记它有两个作用：①楼级消费者拿得到聚合读数；②将来任何楼级槽把它列为
    # conditional_input 时不会撞上 _resolve_building_upstream 的「无聚合声明」fail-fast。
    # 聚合是从已采样值算的，不消费 rng。
    "procedure.investigation.detailed.completed": "any_true",
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
    # #37 丙路裁定三条（决议_37修法_20260805 §一.1，engineering_estimate 低置信，
    # 与上方既有 artifact.* 五条同族同档）：文档存在态，任一部位记录带有＝楼级存在。
    # 后两条 coef 为正（+0.75/+0.30，「有不符合记录 ⇒ 更可能要修订」），取 all_true
    # 会读成「全部部位都有不符合记录才算有」，与 coef 正号语义相反——故排除 all_true。
    "artifact.notice.investigation_intention": "any_true",
    "artifact.record.nonconformity_sp2": "any_true",
    "artifact.record.test_or_material_witness": "any_true",
    # #38 槽 2（池 v2 供给侧，2026-08-06）：任一部位发现不一致事项＝楼级成立
    # （与 sp2 同语义同档；正 coef 语义排除 all_true，5008-5011 行同理）。
    "supervision.nonconformity.found": "any_true",
}

# 生成侧要落"楼级聚合行"的 fragment 槽——v8 批跑实证后扩到全聚合表的 bool 槽
# （文档/进度槽被楼级卡消费时同构歧义；聚合行 + §6.4.3 作用域分级 = 楼级唯一读数）。
AGGREGATE_ROW_SLOTS: tuple = tuple(sorted(BUILDING_READING_AGGREGATION))
