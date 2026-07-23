"""SCAN-level guardrail — spec 03 §3 cross-registry 自洽约束自动化.

把 spec 03 §3「跨表引用清单」中"必须注册"类约束转成 pytest assertion，
任何 registry 间的 slot_id / id 引用一旦指向未注册条目，CI 直接 fail。

cover 范围（spec 03 §3 共 21 条约束 - 全覆盖）：

资产空间域（line 89-94）：
- line 89: building_template_registry.component_graph_template_ids ⊆ component graph templates
- line 90: component_type_registry.material_compatibility ⊆ material_system_registry.material_system
- line 91: component_type_registry.allowed_location_classes ⊆ location_class_registry.location_class
- line 92: component_type_registry.allowed_mechanisms ⊆ mechanism_library_registry.mechanism_family
- line 93: fragment_template_registry.allowed_driver_profiles ⊆ latent_driver_registry.driver_id
- line 94: fragment_template_registry.allowed_mechanisms ⊆ mechanism_library_registry.mechanism_family

驱动测量域（line 95, 98-100, 102）：
- line 95: coverage_relation_registry.ratio_slot_id ⊆ measurement registries
- line 98: sampling_plan_registry.target_slot_ids ⊆ measurement registries
- line 99: verification_test_registry.required_measurements ⊆ measurement registries
- line 100: assessment_surrogate_registry.input_slots/output_slots ⊆ measurement registries
- line 102: risk_derivation_registry.input_measurement_slots ⊆ measurement registries

缺陷字典域（line 96, 97, 101）：
- line 96: defect_condition_taxonomy_registry.default_measurement_slots ⊆ measurement registries
- line 97: mechanism_library_registry.output_condition_classes ⊆ defect_condition_taxonomy.condition_class
- line 101: risk_derivation_registry.input_condition_classes ⊆ defect_condition_taxonomy.condition_class

派生风险域（line 103）：
- line 103: repair_outcome_registry.input_risk_flags ⊆ risk_derivation_registry.risk_flag_id

Projection / Sidecar（line 104-110）：
- line 104: normative_projection_registry.required_world_core_slots ⊆ sidecar_contract world_core slot universe
- line 105: normative_projection_registry.required_measurement_slots ⊆ measurement registries
- line 106: normative_projection_registry.required_qualifier_slots ⊆ sidecar_contract qualifier slot universe
- line 107: normative_projection_registry.required_sidecar_interfaces ⊆ sidecar interface universe
- line 108: sidecar_ownership_registry.joins_on ⊆ {world_id, building_id, fragment_id, component_id, slot_id}
- line 109/110: sidecar_measurement_registry.carrier_slot ⊆ sidecar_ownership_registry.sidecar_slot_id（line 110 lookup direction 在此并入）

历史背景：DEBT-025 closure (2026-05-07) — 三方对照审计后挖出 7 个 phantom slot
（无 spec 授权 + 无 MBIS 法规阈值 + generator 不产值），按路径 B 删后加此 guardrail
防 spec ↔ code drift 再发生。WG-3/WG-5 升级（2026-04-19，MVP 期）当时无 spec
可参照不构成违规；新版 spec 整理 sweep 不彻底是 phantom 的真实成因。

跑法：
  pytest agent_v1/tests/test_spec_consistency.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest  # noqa: E402

from workflow_engine.worldgen.registry import _build_registry_bundle  # noqa: E402


@pytest.fixture(scope="module")
def bundle():
    return _build_registry_bundle()


def _records(bundle, registry_id: str):
    for table in bundle.registries:
        if table.registry_id == registry_id:
            return list(table.records)
    return []


def _slot_ids(bundle, registry_id: str) -> Set[str]:
    return {r["slot_id"] for r in _records(bundle, registry_id) if r.get("slot_id")}


def _measurement_slot_universe(bundle) -> Set[str]:
    """Union of slot_ids across all measurement-bearing registries."""
    return (
        _slot_ids(bundle, "technical_measurement_registry")
        | _slot_ids(bundle, "sidecar_measurement_registry")
    )


# ---------- spec 03 §3 line 95 ----------

def test_coverage_relation_ratio_slot_must_be_registered(bundle):
    """spec 03 §3 line 95: coverage_relation_registry.ratio_slot_id must ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for cr in _records(bundle, "coverage_relation_registry"):
        slot_id = cr.get("ratio_slot_id") or ""
        if slot_id and slot_id not in measurement_slots:
            unbound.append((cr.get("coverage_relation_id"), slot_id))
    assert not unbound, (
        f"coverage_relation_registry refs unbound ratio_slot_id "
        f"(violates spec 03 §3 line 95): {unbound}"
    )


# ---------- spec 03 §3 line 96 ----------

def test_defect_condition_default_measurement_slots_registered(bundle):
    """spec 03 §3 line 96: defect_condition_taxonomy.default_measurement_slots ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for record in _records(bundle, "defect_condition_taxonomy_registry"):
        for slot_id in record.get("default_measurement_slots", []) or []:
            if slot_id not in measurement_slots:
                unbound.append((record.get("condition_class"), slot_id))
    assert not unbound, (
        f"defect_condition_taxonomy refs unbound default_measurement_slots "
        f"(violates spec 03 §3 line 96): {unbound}"
    )


# ---------- spec 03 §3 line 98 ----------

def test_sampling_plan_target_slots_registered(bundle):
    """spec 03 §3 line 98: sampling_plan_registry.target_slot_ids ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for plan in _records(bundle, "sampling_plan_registry"):
        for slot_id in plan.get("target_slot_ids", []) or []:
            if slot_id not in measurement_slots:
                unbound.append((plan.get("sampling_plan_id"), slot_id))
    assert not unbound, (
        f"sampling_plan_registry refs unbound target_slot_ids "
        f"(violates spec 03 §3 line 98): {unbound}"
    )


# ---------- spec 03 §3 line 99 ----------

def test_verification_test_required_measurements_registered(bundle):
    """spec 03 §3 line 99: verification_test_registry.required_measurements ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for record in _records(bundle, "verification_test_registry"):
        for slot_id in record.get("required_measurements", []) or []:
            if slot_id not in measurement_slots:
                unbound.append((record.get("test_family_id"), slot_id))
    assert not unbound, (
        f"verification_test_registry refs unbound required_measurements "
        f"(violates spec 03 §3 line 99): {unbound}"
    )


# ---------- spec 03 §3 line 100 ----------

def test_assessment_surrogate_input_output_slots_registered(bundle):
    """spec 03 §3 line 100: assessment_surrogate_registry.input_slots/output_slots ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for record in _records(bundle, "assessment_surrogate_registry"):
        for field in ("input_slots", "output_slots"):
            for slot_id in record.get(field, []) or []:
                if slot_id not in measurement_slots:
                    unbound.append((record.get("assessment_family_id"), field, slot_id))
    assert not unbound, (
        f"assessment_surrogate_registry refs unbound slot "
        f"(violates spec 03 §3 line 100): {unbound}"
    )


# ---------- spec 03 §3 line 102 ----------

def test_risk_derivation_input_measurement_slots_registered(bundle):
    """spec 03 §3 line 102: risk_derivation_registry.input_measurement_slots ⊆ measurement registries."""
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for record in _records(bundle, "risk_derivation_registry"):
        for slot_id in record.get("input_measurement_slots", []) or []:
            if slot_id not in measurement_slots:
                unbound.append((record.get("risk_flag_id"), slot_id))
    assert not unbound, (
        f"risk_derivation_registry refs unbound input_measurement_slots "
        f"(violates spec 03 §3 line 102): {unbound}"
    )


# ---------- spec 03 §3 line 105（核心：DEBT-025 phantom 主犯）----------

def test_projection_required_measurement_slots_registered(bundle):
    """spec 03 §3 line 105: normative_projection_registry.required_measurement_slots ⊆ measurement registries.

    NOTE: spec line 105 文字写"缺失时按 unknown / not_applicable / sidecar_missing"——但这条
    graceful degrade 是 runtime miss 的语义（slot 注册了但当次 building 没生成 value），
    不允许 registry-time miss（slot_id 根本不在 measurement_registry 注册）。
    DEBT-025 D025-X4 phantom 走的是 registry-time miss，应 reject。
    """
    measurement_slots = _measurement_slot_universe(bundle)
    unbound = []
    for proj in _records(bundle, "normative_projection_registry"):
        for slot_id in proj.get("required_measurement_slots", []) or []:
            if slot_id not in measurement_slots:
                unbound.append((proj.get("projection_registry_id"), slot_id))
    assert not unbound, (
        f"normative_projection_registry refs unbound required_measurement_slots "
        f"(violates spec 03 §3 line 105 registry-time invariant): {unbound}"
    )


# ---------- spec 03 §3 line 97 / 101 ----------

def test_mechanism_output_condition_classes_registered(bundle):
    """spec 03 §3 line 97: mechanism_library_registry.output_condition_classes ⊆ defect_condition_taxonomy."""
    condition_classes = {
        r["condition_class"] for r in _records(bundle, "defect_condition_taxonomy_registry")
        if r.get("condition_class")
    }
    unbound = []
    for mech in _records(bundle, "mechanism_library_registry"):
        for cc in mech.get("output_condition_classes", []) or []:
            if cc not in condition_classes:
                unbound.append((mech.get("mechanism_family"), cc))
    assert not unbound, (
        f"mechanism_library refs unbound output_condition_classes "
        f"(violates spec 03 §3 line 97): {unbound}"
    )


def test_risk_derivation_input_condition_classes_registered(bundle):
    """spec 03 §3 line 101: risk_derivation.input_condition_classes ⊆ defect_condition_taxonomy."""
    condition_classes = {
        r["condition_class"] for r in _records(bundle, "defect_condition_taxonomy_registry")
        if r.get("condition_class")
    }
    unbound = []
    for record in _records(bundle, "risk_derivation_registry"):
        for cc in record.get("input_condition_classes", []) or []:
            if cc not in condition_classes:
                unbound.append((record.get("risk_flag_id"), cc))
    assert not unbound, (
        f"risk_derivation refs unbound input_condition_classes "
        f"(violates spec 03 §3 line 101): {unbound}"
    )


# ---------- spec 03 §3 line 103 ----------

def test_repair_outcome_input_risk_flags_registered(bundle):
    """spec 03 §3 line 103: repair_outcome.input_risk_flags ⊆ risk_derivation.risk_flag_id."""
    risk_flag_ids = {
        r["risk_flag_id"] for r in _records(bundle, "risk_derivation_registry")
        if r.get("risk_flag_id")
    }
    unbound = []
    for record in _records(bundle, "repair_outcome_registry"):
        for fid in record.get("input_risk_flags", []) or []:
            if fid not in risk_flag_ids:
                unbound.append((record.get("repair_outcome_id"), fid))
    assert not unbound, (
        f"repair_outcome refs unbound input_risk_flags "
        f"(violates spec 03 §3 line 103): {unbound}"
    )


# ============================================================================
# 资产空间域 — spec 03 §3 line 89-94
# ============================================================================

# ---------- spec 03 §3 line 89 ----------

def test_building_template_component_graph_template_ids_registered(bundle):
    """spec 03 §3 line 89: building_template.component_graph_template_ids 必须能实例化至少 1 个 component.

    注：spec 没单独的 component_graph_template_registry。当前 component_graph_template_ids 字段
    全为 [] (开 list 留扩展)，没引用任何 phantom；仅做"非 phantom"验证（任何字符串 entry 都应可解析）。
    """
    unbound = []
    for record in _records(bundle, "building_template_registry"):
        for tid in record.get("component_graph_template_ids", []) or []:
            # 当前 spec 没指定 graph template registry；任何非空 string 引用都视为可疑
            # 留作未来 graph template registry 实施后细化
            if not isinstance(tid, str) or not tid:
                unbound.append((record.get("building_template_id"), tid))
    assert not unbound, (
        f"building_template refs malformed component_graph_template_ids "
        f"(violates spec 03 §3 line 89): {unbound}"
    )


# ---------- spec 03 §3 line 90 ----------

def test_component_type_material_compatibility_registered(bundle):
    """spec 03 §3 line 90: component_type.material_compatibility ⊆ material_system_registry.material_system."""
    material_systems = {
        r["material_system"] for r in _records(bundle, "material_system_registry")
        if r.get("material_system")
    }
    unbound = []
    for record in _records(bundle, "component_type_registry"):
        for material in record.get("material_compatibility", []) or []:
            if material not in material_systems:
                unbound.append((record.get("component_type"), material))
    assert not unbound, (
        f"component_type refs unbound material_compatibility "
        f"(violates spec 03 §3 line 90): {unbound}"
    )


# ---------- spec 03 §3 line 91 ----------

def test_component_type_allowed_location_classes_registered(bundle):
    """spec 03 §3 line 91: component_type.allowed_location_classes ⊆ location_class_registry.location_class."""
    location_classes = {
        r["location_class"] for r in _records(bundle, "location_class_registry")
        if r.get("location_class")
    }
    unbound = []
    for record in _records(bundle, "component_type_registry"):
        for loc in record.get("allowed_location_classes", []) or []:
            if loc not in location_classes:
                unbound.append((record.get("component_type"), loc))
    assert not unbound, (
        f"component_type refs unbound allowed_location_classes "
        f"(violates spec 03 §3 line 91): {unbound}"
    )


def _mechanism_families(bundle):
    return {
        r["mechanism_family"] for r in _records(bundle, "mechanism_library_registry")
        if r.get("mechanism_family")
    }


# ---------- spec 03 §3 line 92 ----------

def test_component_type_allowed_mechanisms_registered(bundle):
    """spec 03 §3 line 92: component_type.allowed_mechanisms ⊆ mechanism_library.mechanism_family."""
    mechanisms = _mechanism_families(bundle)
    unbound = []
    for record in _records(bundle, "component_type_registry"):
        for mech in record.get("allowed_mechanisms", []) or []:
            if mech not in mechanisms:
                unbound.append((record.get("component_type"), mech))
    assert not unbound, (
        f"component_type refs unbound allowed_mechanisms "
        f"(violates spec 03 §3 line 92): {unbound}"
    )


# ---------- spec 03 §3 line 93 ----------

def test_fragment_template_allowed_driver_profiles_registered(bundle):
    """spec 03 §3 line 93: fragment_template.allowed_driver_profiles ⊆ latent_driver_registry.driver_id."""
    driver_ids = {
        r["driver_id"] for r in _records(bundle, "latent_driver_registry")
        if r.get("driver_id")
    }
    unbound = []
    for record in _records(bundle, "fragment_template_registry"):
        for driver in record.get("allowed_driver_profiles", []) or []:
            if driver not in driver_ids:
                unbound.append((record.get("fragment_template_id"), driver))
    assert not unbound, (
        f"fragment_template refs unbound allowed_driver_profiles "
        f"(violates spec 03 §3 line 93): {unbound}"
    )


# ---------- spec 03 §3 line 94 ----------

def test_fragment_template_allowed_mechanisms_registered(bundle):
    """spec 03 §3 line 94: fragment_template.allowed_mechanisms ⊆ mechanism_library.mechanism_family."""
    mechanisms = _mechanism_families(bundle)
    unbound = []
    for record in _records(bundle, "fragment_template_registry"):
        for mech in record.get("allowed_mechanisms", []) or []:
            if mech not in mechanisms:
                unbound.append((record.get("fragment_template_id"), mech))
    assert not unbound, (
        f"fragment_template refs unbound allowed_mechanisms "
        f"(violates spec 03 §3 line 94): {unbound}"
    )


# ============================================================================
# Projection-side — spec 03 §3 line 104, 106, 107
# ============================================================================

def _sidecar_contract_slots_by_partition(partition: str):
    """从 sidecar_contract.ownership_map 取某 partition 的 slot universe."""
    from workflow_engine.worldgen.registry import _build_sidecar_contract  # noqa: PLC0415
    contract = _build_sidecar_contract()
    return {
        entry.slot_id for entry in contract.ownership_map
        if entry.partition == partition
    }


# ---------- spec 03 §3 line 104 ----------

def test_projection_required_world_core_slots_registered(bundle):
    """spec 03 §3 line 104: projection.required_world_core_slots ⊆ sidecar_contract world_core slot universe."""
    world_core_slots = _sidecar_contract_slots_by_partition("world_core")
    unbound = []
    for proj in _records(bundle, "normative_projection_registry"):
        for slot_id in proj.get("required_world_core_slots", []) or []:
            if slot_id not in world_core_slots:
                unbound.append((proj.get("projection_registry_id"), slot_id))
    assert not unbound, (
        f"projection refs unbound required_world_core_slots "
        f"(violates spec 03 §3 line 104): {unbound}"
    )


# ---------- spec 03 §3 line 106 ----------

def test_projection_required_qualifier_slots_registered(bundle):
    """spec 03 §3 line 106: projection.required_qualifier_slots ⊆ sidecar_contract qualifier_taxonomy slot universe."""
    qualifier_slots = _sidecar_contract_slots_by_partition("qualifier_taxonomy")
    unbound = []
    for proj in _records(bundle, "normative_projection_registry"):
        for slot_id in proj.get("required_qualifier_slots", []) or []:
            if slot_id not in qualifier_slots:
                unbound.append((proj.get("projection_registry_id"), slot_id))
    assert not unbound, (
        f"projection refs unbound required_qualifier_slots "
        f"(violates spec 03 §3 line 106): {unbound}"
    )


# ---------- spec 03 §3 line 107 ----------

def test_projection_required_sidecar_interfaces_registered(bundle):
    """spec 03 §3 line 107: projection.required_sidecar_interfaces ⊆ sidecar_contract.interface_schema.interface_id."""
    from workflow_engine.worldgen.registry import _build_sidecar_contract  # noqa: PLC0415
    contract = _build_sidecar_contract()
    interface_ids = {schema.interface_id for schema in contract.interface_schema}
    unbound = []
    for proj in _records(bundle, "normative_projection_registry"):
        for iface in proj.get("required_sidecar_interfaces", []) or []:
            if iface not in interface_ids:
                unbound.append((proj.get("projection_registry_id"), iface))
    assert not unbound, (
        f"projection refs unbound required_sidecar_interfaces "
        f"(violates spec 03 §3 line 107): {unbound}"
    )


# ============================================================================
# Sidecar-side — spec 03 §3 line 108, 109/110
# ============================================================================

# ---------- spec 03 §3 line 108 ----------

def test_sidecar_ownership_joins_on_in_canonical_keys(bundle):
    """spec 03 §3 line 108: sidecar_ownership.joins_on ⊆ canonical join keys.

    canonical join keys = {world_id, building_id, fragment_id, component_id, slot_id}（spec 09 §2）。
    """
    canonical_keys = {"world_id", "building_id", "fragment_id", "component_id", "slot_id"}
    unbound = []
    for record in _records(bundle, "sidecar_ownership_registry"):
        for key in record.get("joins_on", []) or []:
            if key not in canonical_keys:
                unbound.append((record.get("sidecar_slot_id"), key))
    assert not unbound, (
        f"sidecar_ownership refs non-canonical joins_on key "
        f"(violates spec 03 §3 line 108): {unbound}"
    )


# ---------- spec 03 §3 line 109/110 ----------

def test_sidecar_measurement_carrier_slot_registered(bundle):
    """spec 03 §3 line 109: sidecar_measurement.carrier_slot ⊆ sidecar_ownership.sidecar_slot_id.

    line 110 (sidecar_measurement.slot_id ↔ projection lookup direction) 在此并入：carrier 必须先注册。
    """
    sidecar_slot_ids = {
        r["sidecar_slot_id"] for r in _records(bundle, "sidecar_ownership_registry")
        if r.get("sidecar_slot_id")
    }
    unbound = []
    for record in _records(bundle, "sidecar_measurement_registry"):
        carrier_slot = record.get("carrier_slot")
        if carrier_slot and carrier_slot not in sidecar_slot_ids:
            unbound.append((record.get("slot_id"), carrier_slot))
    assert not unbound, (
        f"sidecar_measurement refs unbound carrier_slot in sidecar_ownership_registry "
        f"(violates spec 03 §3 line 109): {unbound}"
    )
