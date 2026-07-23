"""W2 归因组件一致化（DEBT-049 根治①，spec 草案 2026-07-08）。

codex CoP 裁定：缺陷类机制按组件 CoP 检查族归因（回归 3.1.2 五类），不再机制粗
fallback 把排水/消防 fragment 的缺陷投进 external_components。工作流机制/ubw_signal
保持机制驱动。
"""

from __future__ import annotations

from workflow_engine.regulation_projection_executor import (
    _pick_projection_family_for_fragment,
)

# projection_family_index 仅需族键存在（函数按 `family in index` 判）。
IDX = {
    "mbis.inspection.external_components": {},
    "mbis.inspection.structural_components": {},
    "mbis.inspection.drainage": {},
    "mbis.inspection.fire_safety": {},
    "mbis.inspection.ubw": {},
    "mbis.investigation.gate_and_proposal": {},
    "mbis.repair.external_structural_validation": {},
}


def _pick(mech, comp):
    return _pick_projection_family_for_fragment(mech, comp, IDX)


def test_drainage_crack_routes_to_drainage() -> None:
    """排水立管裂缝 → drainage（不再 external_components）——CoP 3.6。"""
    assert _pick("structural_crack", "drainage_stack") == "mbis.inspection.drainage"
    assert _pick("corrosion_spall", "drainage_branch") == "mbis.inspection.drainage"


def test_fire_door_defect_routes_to_fire_safety() -> None:
    """消防门缺陷 → fire_safety（不再 external_components）——CoP 3.5.3/表4。"""
    assert _pick("structural_crack", "fire_door") == "mbis.inspection.fire_safety"
    assert _pick("corrosion_spall", "fire_door") == "mbis.inspection.fire_safety"


def test_fire_deficiency_on_drainage_routes_by_component() -> None:
    """排水立管上的消防缺陷机制 → 按组件归 drainage（组件一致）。"""
    assert _pick("fire_safety_deficiency", "drainage_stack") == "mbis.inspection.drainage"


def test_external_wall_defect_stays_external() -> None:
    """外墙缺陷 → external_components（本就正确，回归一致后不变）。"""
    assert _pick("structural_crack", "external_wall") == "mbis.inspection.external_components"
    assert _pick("corrosion_spall", "canopy") == "mbis.inspection.external_components"


def test_structural_member_defect_stays_structural() -> None:
    assert _pick("structural_crack", "structural_member") == "mbis.inspection.structural_components"


def test_parapet_balcony_conservative_structural() -> None:
    """parapet/balcony 保守留 structural（spec §4 决策点1）。"""
    assert _pick("structural_crack", "parapet_wall") == "mbis.inspection.structural_components"
    assert _pick("structural_crack", "balcony_slab") == "mbis.inspection.structural_components"


def test_workflow_mechanisms_unchanged() -> None:
    """工作流机制保持机制驱动（不走组件路由）。"""
    assert _pick("assessment_origin", "external_wall") == "mbis.investigation.gate_and_proposal"
    assert _pick("assessment_origin", "structural_member") == "mbis.repair.external_structural_validation"
    assert _pick("verification_origin", "structural_member") == "mbis.repair.external_structural_validation"


def test_ubw_signal_unchanged() -> None:
    """ubw_signal 暂留机制驱动（UBW 跨组件，spec §4 决策点2）。"""
    assert _pick("ubw_signal", "fire_door") == "mbis.inspection.ubw"
    assert _pick("ubw_signal", "structural_member") == "mbis.inspection.ubw"


def test_unknown_component_falls_back_to_mechanism() -> None:
    """未知组件（无检查族映射）→ 回退机制映射（保守，不误路由）。"""
    assert _pick("structural_crack", "access_panel") == "mbis.inspection.external_components"


def test_family_absent_from_index_falls_through() -> None:
    """组件族不在 index → 回退机制映射（不返回不存在的族）。"""
    idx = {"mbis.inspection.external_components": {}}
    # drainage_stack 的 drainage 族不在 idx → 回退机制映射 structural_crack→external
    assert _pick_projection_family_for_fragment(
        "structural_crack", "drainage_stack", idx
    ) == "mbis.inspection.external_components"
