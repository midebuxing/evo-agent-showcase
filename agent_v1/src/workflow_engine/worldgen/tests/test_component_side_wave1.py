"""组件侧三件冒烟（spec 草案·DEBT-049 第一波 §3）。"""

from __future__ import annotations

from workflow_engine.worldgen.registry import _build_registry_bundle, _defect_condition_records


def _templates():
    b = _build_registry_bundle()
    for r in b.registries:
        if r.registry_id == "fragment_template_registry":
            return r.records
    raise RuntimeError


def _component_types():
    b = _build_registry_bundle()
    for r in b.registries:
        if r.registry_id == "component_type_registry":
            return {rec["component_type"]: rec for rec in r.records}
    raise RuntimeError


def test_wall_tile_finish_type_registered() -> None:
    types = _component_types()
    rec = types["wall_tile_finish"]
    assert rec["component_class"] == "finish_system"
    assert "tile_finish" in rec["material_compatibility"]
    assert rec["cover_depth_mm_range"] is None


def test_new_templates_present_with_required_branches() -> None:
    by_id = {t["fragment_template_id"]: t for t in _templates()}
    tile = by_id["FT_TILE_FINISH_V1"]
    assert tile["component_type"] == "wall_tile_finish"
    assert "technical_validation_measurement" in tile["measurement_branches"]
    canopy = by_id["FT_CANOPY_ROOT_V1"]
    assert canopy["component_type"] == "canopy"
    assert canopy["allowed_mechanisms"] == ["corrosion_spall"]


def test_compat_tables_extended() -> None:
    recs = {r["condition_class"]: r for r in _defect_condition_records()}
    assert "canopy" in recs["DC_SPALL_REBAR"]["compatible_components"]
    for cls in ("DC_CRACK", "DC_HOLLOWING", "DC_DETACHMENT"):
        assert "wall_tile_finish" in recs[cls]["compatible_components"], cls
