"""构件类型的受控包含匹配契约（DEBT-076 裁定）。

契约：

    卡侧要求 K 与世界事实 W 匹配 ⟺ W == K
                                或 W 经**权威登记**的 `is_a` 关系**单向**推出 K

四条限制（codex 决策门明确，缺一不可）：
1. 只认显式登记的关系——不得按名称相似／单复数／字符串前缀猜；
2. **方向单向**：世界具体类型 → 卡侧上位类型；**反向不成立**
   （"某个外部构件"不能证明它一定是外墙）；
3. **缺省拒绝**：`subsumption` 未提供或关系未登记 → 不匹配；
4. 状态概念（`ubw` / `covered_component`）不在类型轴上，不进 `subsumption`。
"""
from __future__ import annotations

from evo_agent_baseline.closure.obligation_deriver import qualifiers_match

# 与人裁关系表一致的最小登记：结构构件 ⊇ {簷篷, 轉移構築物}；外部構件 ⊇ {外牆, 飾面}
SUB = {"structural_component": ["cantilevered_canopy", "transfer_structure"],
       "external_component": ["external_wall", "wall_tiles"]}


def _m(card_val, world_val, sub=SUB):
    return qualifiers_match({"component_type_key": card_val},
                            {"component_type_key": world_val}, sub)


def test_exact_match_still_works():
    assert _m("external_wall", "external_wall")


def test_world_descendant_matches_card_ancestor():
    """世界给具体类型、卡要上位类型 → 匹配（这是本次放宽的全部内容）。

    依据 §3.4.1(b)(vi)「懸臂式伸出構築物」属結構構件檢驗項目。
    """
    assert _m("structural_component", "cantilevered_canopy")
    assert _m("external_component", "external_wall")


def test_reverse_direction_must_not_match():
    """🔴 反向不成立——"某个结构构件"不能证明它一定是簷篷。

    若允许反向，所有只针对簷篷的条款会被错误扩大到全部结构构件。
    """
    assert not _m("cantilevered_canopy", "structural_component")
    assert not _m("external_wall", "external_component")


def test_unregistered_relation_defaults_to_deny():
    """🔴 缺省拒绝：关系未登记即不匹配（不许按名字相似猜）。"""
    assert not _m("structural_component", "drainage_component")
    assert not _m("structural_component", "fire_safety_component")
    # 名字很像也不行
    assert not _m("external_component", "external_component_extra")


def test_no_subsumption_provided_is_strict():
    """🔴 不传 `subsumption` 时行为与改动前等价（严格相等）。"""
    assert not _m("structural_component", "cantilevered_canopy", sub=None)
    assert not _m("structural_component", "cantilevered_canopy", sub={})
    assert _m("external_wall", "external_wall", sub=None)


def test_multilevel_ancestor_matches():
    """规格措辞是「后代 → 祖先」而非「叶 → 父」——多级须成立。"""
    multi = {"a_top": ["b_mid"], "b_mid": ["c_leaf"]}
    assert qualifiers_match({"component_type_key": "a_top"},
                            {"component_type_key": "c_leaf"}, multi), "多级祖先未匹配"


def test_only_component_type_key_is_relaxed():
    """🔴 放宽**只对 `component_type_key` 一个键**，别的键仍严格相等。"""
    assert not qualifiers_match(
        {"location_class_key": "structural_component"},
        {"location_class_key": "cantilevered_canopy"}, SUB), "别的键也被放宽了"


def test_other_keys_still_conjunctive():
    """多键时仍是合取：类型能推出、但别的键不符 → 整体不匹配。"""
    assert not qualifiers_match(
        {"component_type_key": "structural_component", "location_class_key": "external"},
        {"component_type_key": "cantilevered_canopy", "location_class_key": "internal"},
        SUB)


def test_state_concepts_are_not_in_subsumption():
    """状态概念（ubw / covered_component）不该出现在人裁关系表的 `is_a` 里。

    依据：§3.7.1(b) 僭建物涵蓋「經改動及加建的結構構件」「經改動的外牆」——
    它是「經改動／加建」这个**状态轴**，与各构件类型**交叉**而非包含。
    """
    import json
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2"
         / "mbis_cop_2023" / "component_type_relations_v1.json")
    if not p.is_file():
        import pytest
        pytest.skip("关系表未生成")
    doc = json.loads(p.read_text(encoding="utf-8"))
    for r in doc["relations"]:
        if r.get("relation") != "is_a":
            continue
        for side in (r.get("child"), r.get("parent")):
            assert side not in {"ubw", "covered_component"}, (
                f"状态概念 {side} 被登记进 is_a —— 它不在类型轴上")
