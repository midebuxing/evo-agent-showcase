"""机制阶段闸（spec 草案·DEBT-049 建模轮第一波 §1，2026-07-08 v2）。"""

from __future__ import annotations

import random

from workflow_engine.worldgen.generator import (
    _defect_class_compatible_components,
    generate_condition,
)
from workflow_engine.worldgen.registry import _build_registry_bundle


def _bundle():
    return _build_registry_bundle()


class _Frag:
    fragment_id = "FRG-T-STRUCT-01-01"
    fragment_length_m = 4.0
    fragment_area_m2 = 10.0


class _Comp:
    component_id = "CMP-T"
    component_type = "structural_member"
    cover_depth_mm = 30.0
    material_system = "reinforced_concrete"


class _Mech:
    mechanism_state_id = "MEC-T"
    mechanism_family = "structural_crack"
    severity_index = 0.7
    active = True


class _Drv:
    driver_id = "DRV-T"
    moisture_ingress_index = 0.5
    chloride_exposure_index = 0.5
    carbonation_depth_ratio = 0.5
    thermal_cycle_index = 0.3
    service_load_ratio = 0.9   # ≥0.85 超载闸
    restraint_level = 0.5
    maintenance_deficit_index = 0.5


def test_deformation_gate_fires_on_overload() -> None:
    cond = generate_condition(_Frag(), _Comp(), _Mech(), _Drv(),
                              random.Random(1), 30.0, _bundle())
    assert cond.condition_class == "DC_DEFORMATION_DISPLACEMENT"


def test_deformation_gate_respects_component_compat() -> None:
    comp = _Comp(); comp.component_type = "external_wall"  # 目录不相容
    cond = generate_condition(_Frag(), comp, _Mech(), _Drv(),
                              random.Random(1), 30.0, _bundle())
    assert cond.condition_class == "DC_CRACK"


def test_deformation_gate_quiet_below_thresholds() -> None:
    drv = _Drv(); drv.service_load_ratio = 0.5; drv.restraint_level = 0.5
    cond = generate_condition(_Frag(), _Comp(), _Mech(), drv,
                              random.Random(1), 30.0, _bundle())
    assert cond.condition_class == "DC_CRACK"


def test_compat_lookup_reads_catalog() -> None:
    compat = _defect_class_compatible_components(
        "DC_DEFORMATION_DISPLACEMENT", _bundle())
    assert compat and "structural_member" in compat


def test_generatable_absent_classes_reachable_set() -> None:
    """件2：可达集 = 模板机制主类+闸类 ∩ 组件相容，减实际出现类。"""
    from workflow_engine.worldgen.generator import (
        _fragment_reachable_condition_classes,
    )
    b = _bundle()
    # structural_member + structural_crack：主类 DC_CRACK + 闸类 DEFORMATION 均相容
    r = _fragment_reachable_condition_classes(["structural_crack"], "structural_member", b)
    assert "DC_CRACK" in r and "DC_DEFORMATION_DISPLACEMENT" in r
    # external_wall：DEFORMATION 目录不相容 → 只剩主类
    r2 = _fragment_reachable_condition_classes(["structural_crack"], "external_wall", b)
    assert "DC_CRACK" in r2 and "DC_DEFORMATION_DISPLACEMENT" not in r2


def test_taxonomy_full_set_covers_all_registry_classes() -> None:
    """第三波件A：分类全集 = defect_condition_taxonomy_registry 全部条目。"""
    from workflow_engine.worldgen.generator import _all_taxonomy_condition_classes
    all_cls = _all_taxonomy_condition_classes(_bundle())
    assert "DC_CRACK" in all_cls and "DC_METAL_CORROSION" in all_cls
    # 目录不相容/机制不可达的类也在全集内（闭世界总声明的核心差异）
    assert "DC_DRAINAGE_BLOCKAGE" in all_cls
    assert len(all_cls) >= 15
    assert _all_taxonomy_condition_classes(None) == set()


def test_class_reachability_audit_three_states() -> None:
    """第三波件A A.4：审计台账三态（generated/可达未生成/不可达）+ 样本。"""
    from types import SimpleNamespace as NS
    from workflow_engine.worldgen.validation import build_class_reachability_audit
    bw = NS(
        building=NS(building_template_id="BT_X"),
        components=[NS(component_id="C1", component_type="structural_member")],
        fragments=[NS(fragment_id="FR1", component_id="C1")],
        conditions=[NS(
            fragment_id="FR1",
            condition_class="DC_CRACK",
            condition_classes=["DC_CRACK"],
            generatable_absent_classes=["DC_DEFORMATION_DISPLACEMENT"],
            absent_condition_classes=["DC_DEFORMATION_DISPLACEMENT",
                                      "DC_DRAINAGE_BLOCKAGE"],
        )],
    )
    audit = build_class_reachability_audit([bw])
    by_cls = {e["condition_class"]: e for e in audit["entries"]}
    assert by_cls["DC_CRACK"]["status"] == "generated"
    assert by_cls["DC_DEFORMATION_DISPLACEMENT"]["status"] == "reachable_not_generated"
    assert by_cls["DC_DRAINAGE_BLOCKAGE"]["status"] == "unreachable"
    assert by_cls["DC_CRACK"]["sample_fragment_ids"] == ["FR1"]
    assert audit["summary_cell_counts"] == {
        "generated": 1, "reachable_not_generated": 1, "unreachable": 1}
