"""补抽错绑前置修（EXP-012）。"""

from __future__ import annotations


def test_refill_filters_templates_without_matching_component() -> None:
    """EXP-012 前置修：补抽只收楼内存在 component_type 的模板（防错绑）。"""
    from workflow_engine.worldgen.generator import _select_fragment_templates
    import random

    class _B:  # BuildingContext 桩（函数体未用其字段）
        pass

    class _R:
        pass

    # 用假注册表桩：主池 1 条（匹配楼型），全池另有 1 条 canopy 模板
    import workflow_engine.worldgen.generator as G
    real = G._registry_records
    try:
        G._registry_records = lambda reg, name: [
            {"fragment_template_id": "FT_A", "building_template_id": "BT_X",
             "component_type": "external_wall"},
            {"fragment_template_id": "FT_CANOPY", "building_template_id": "BT_Y",
             "component_type": "canopy"},
        ]
        out = _select_fragment_templates(
            _B(), "BT_X", _R(), random.Random(1), target_count=2,
            available_component_types={"external_wall"},
        )
        types = [t["component_type"] for t in out]
        assert "canopy" not in types  # 楼内无 canopy → 补抽不得选它
        # 未传集合 → 旧行为（可补 canopy）
        out2 = _select_fragment_templates(
            _B(), "BT_X", _R(), random.Random(1), target_count=2,
        )
        assert len(out2) == 2
    finally:
        G._registry_records = real
