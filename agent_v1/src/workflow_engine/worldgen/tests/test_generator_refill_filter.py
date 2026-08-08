"""补抽错绑前置修（EXP-012）。"""

from __future__ import annotations


def test_refill_filters_templates_without_matching_component() -> None:
    """EXP-012 前置修：补抽只收楼内存在 component_type 的模板（防错绑）。"""
    from workflow_engine.worldgen.generator import _select_fragment_templates

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
            _B(), "BT_X", _R(), world_id="WB-TEST-REFILL", target_count=2,
            available_component_types={"external_wall"},
        )
        types = [t["component_type"] for t in out]
        assert "canopy" not in types  # 楼内无 canopy → 补抽不得选它
        # 未传集合 → 旧行为（可补 canopy）
        out2 = _select_fragment_templates(
            _B(), "BT_X", _R(), world_id="WB-TEST-REFILL", target_count=2,
        )
        assert len(out2) == 2
    finally:
        G._registry_records = real


def test_fallback_filters_templates_without_matching_component() -> None:
    """#23 L3 连带修（2026-08-06）：全表回退半边与补抽同一把「楼内存在该类」过滤。

    镜像上面的补抽测试：`building_template_id` 不匹配任何模板 ⇒ primary 为空 ⇒
    走全表回退（`generator.py` `_select_fragment_templates` 的 `if not primary` 臂）。
    此前该臂唯一守卫是金丝雀脚本（不在 pytest 收集范围），本测试补 pytest 半边
    （审核门 2026-08-06 建议项 3）。

    ⚠️ 本测试确实咬在回退臂上：若只短路回退过滤，全表两条模板在首轮就取满
    `target_count=2`，补抽臂不再执行、救不回来 ⇒ canopy 进结果 ⇒ 红（已红先行实证）。
    """
    from workflow_engine.worldgen.generator import _select_fragment_templates

    class _B:  # BuildingContext 桩（函数体未用其字段）
        pass

    class _R:
        pass

    import workflow_engine.worldgen.generator as G
    real = G._registry_records
    try:
        G._registry_records = lambda reg, name: [
            {"fragment_template_id": "FT_A", "building_template_id": "BT_X",
             "component_type": "external_wall"},
            {"fragment_template_id": "FT_CANOPY", "building_template_id": "BT_Y",
             "component_type": "canopy"},
        ]
        # BT_Z 无 primary 绑定 ⇒ 全表回退；楼内只有 external_wall
        out = _select_fragment_templates(
            _B(), "BT_Z", _R(), world_id="WB-TEST-FALLBACK", target_count=2,
            available_component_types={"external_wall"},
        )
        types = [t["component_type"] for t in out]
        assert "canopy" not in types  # 楼内无 canopy → 回退不得选它
        assert types == ["external_wall"]  # 过滤非空 → 只剩楼内类（补抽臂同受滤，不回填）
        # 未传集合 → 旧行为（全表回退可含 canopy，兼容单测直调）
        out2 = _select_fragment_templates(
            _B(), "BT_Z", _R(), world_id="WB-TEST-FALLBACK", target_count=2,
        )
        assert len(out2) == 2
    finally:
        G._registry_records = real
