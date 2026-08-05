"""结构 NA 两态拆分的口径锁定（2026-07-29 立）。

## 为什么拆

`wrong_structural_na` 这个状态存在的**唯一理由**是量「结构早退误杀了本该评估的条款」。
2026-07-29 实测：批 `phase_f_verify_seed301_20260729` 的 12 条里
**11 条其实是供给侧缺口**——卡要求 `location_class_key=['external']` 或
`component_type_key=fire_safety_component`，而本栋**根本没有该类片段**，
于是每个现存片段都被合法地判 NA。早退做对了，是世界没造那类东西。
⇒ 旧口径把 92% 的供给侧缺口记成系统的错，把这个指标该测的信号淹掉。

拆完：`structural_na_no_such_fragment` 11 ／ `wrong_structural_na` 1。
**两者都算漏，召回一格不动**（实测 any 0.7530／漏 574、all 0.7190／漏 653，
拆分前后逐位相同）。

## 🔴 这里锁的第一条最重要：证据只能取**片段级**

`_world_qualifier_index` 若扫全部事实就会错——`carrier_type == "building"` 的
事实携带远宽的 `component_type_key` 值域（某栋楼级事实里 16 种，含
`fire_safety_component`／`escape_route`／`cantilevered_canopy`），而该栋**片段**
只有 3 种。扫全部会把「楼级事实提到过这个类型」误当成「有这类片段」，
实测把 11 条里的 4 条错记成「早退误杀」。**状态名就叫 `no_such_fragment`，
证据不取片段级就是答非所问。**（写这条测试时我正是先写错、量出来才发现的。）

## 变异验证（写测试时实跑过）

- `_world_qualifier_index` 去掉 `carrier_type != "fragment"` 的过滤
  ⇒ `test_index_only_counts_fragment_carriers` 失败；
- `_structural_na_state` 的 `if wanted and not (wanted & ...)` 改成无条件返回
  `wrong_structural_na` ⇒ `test_missing_class_is_supply_side` 失败。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402


def _fact(carrier_type: str, **quals) -> dict:
    return {"carrier_type": carrier_type, "carrier_id": "X", "slot_id": "s",
            "qualifiers": quals}


def test_index_only_counts_fragment_carriers() -> None:
    """楼级事实提到的构件类**不算**「本栋有这类片段」。"""
    fp = {"facts": [
        _fact("fragment", component_type_key="drainage_component",
              location_class_key="common_pipe_duct"),
        _fact("building", component_type_key="fire_safety_component",
              location_class_key="external"),
    ]}
    idx = scorer._world_qualifier_index(fp)
    assert idx["component_type_key"] == {"drainage_component"}
    assert idx["location_class_key"] == {"common_pipe_duct"}
    assert "fire_safety_component" not in idx["component_type_key"], \
        "楼级事实的构件类被当成片段了——这正是 2026-07-29 栽过的那个坑"


def test_missing_class_is_supply_side_not_misfire() -> None:
    """卡要的构件类本栋无片段 ⇒ 供给侧，不是早退误杀。"""
    cards = {"rc.a": {"slot_role_map": [
        {"slot_id": "s", "roles": ["trigger"],
         "qualifiers": {"component_type_key": "fire_safety_component"}}]}}
    world = {"component_type_key": {"drainage_component"}, "location_class_key": set()}
    item = {"normative_item_id": "x", "expected_card_ids": ["rc.a"]}
    assert scorer._structural_na_state(item, {"rc.a"}, cards, world) \
        == "structural_na_no_such_fragment"


def test_present_class_still_counts_as_misfire() -> None:
    """本栋**有**该类片段却整项被判 NA ⇒ 真·误杀，要查早退。"""
    cards = {"rc.a": {"slot_role_map": [
        {"slot_id": "s", "roles": ["trigger"],
         "qualifiers": {"component_type_key": "drainage_component"}}]}}
    world = {"component_type_key": {"drainage_component"}, "location_class_key": set()}
    item = {"normative_item_id": "x", "expected_card_ids": ["rc.a"]}
    assert scorer._structural_na_state(item, {"rc.a"}, cards, world) \
        == "wrong_structural_na"


def test_card_without_class_qualifiers_stays_misfire() -> None:
    """卡不带构件类/位置类限定 ⇒ 无从判「没这类片段」，保守留在误杀档。"""
    cards = {"rc.a": {"slot_role_map": [{"slot_id": "s", "roles": ["trigger"]}]}}
    world = {"component_type_key": set(), "location_class_key": set()}
    item = {"normative_item_id": "x", "expected_card_ids": ["rc.a"]}
    assert scorer._structural_na_state(item, {"rc.a"}, cards, world) \
        == "wrong_structural_na"


def test_defaults_to_old_behaviour_without_index() -> None:
    """缺 cards_by_id / world_q 时保持旧行为——新能力必须缺省无副作用。"""
    item = {"normative_item_id": "x", "expected_card_ids": ["rc.a"]}
    assert scorer._structural_na_state(item, {"rc.a"}, None, None) == "wrong_structural_na"
    assert scorer._structural_na_state(item, {"rc.a"}, {"rc.a": {}}, None) \
        == "wrong_structural_na"


def test_both_states_are_missed_and_neither_is_covered() -> None:
    """拆分不许动召回：两态都在 MISSED，都不在 COVERED。"""
    for s in ("wrong_structural_na", "structural_na_no_such_fragment"):
        assert s in scorer.MISSED_STATES
        assert s not in scorer.COVERED_STATES
        assert s in scorer._STATE_STRENGTH, "新态没进强度表 ⇒ all 口径取最弱会当成 0"
