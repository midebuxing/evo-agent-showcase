"""供给侧缺口分账的口径锁定（2026-07-29 立）。

## 为什么有这个分账

义务按**片段**求值。构件类作用域的项，若本栋根本没有该类的检验场景片段，
卡就产不出任何在作用域内的义务 ⇒ 落 `retrieved_no_evaluation`。
但那是**世界没把题出出来**，不是系统没答。

实测（批 `phase_f_verify_seed301_20260729`）：同一 (规范项, 构件类) 既出现在
「有该类片段」楼、又出现在「没有」楼的 38 个格里——
有片段 185 行覆盖率 **99.5%** ／ 无片段 143 行覆盖率 **0.0%**。
知识图谱侧佐证：343 个组件里 **172 个（50.1%）没有任何片段**。

## 🔴 这里锁的三条，每条都对应一个我真犯过或差点犯的错

1. **供给侧仍算漏，召回一格不动。**
   真值的立场是「片段清单是抽样产物、不作适用性判据」，这个立场站得住；
   把它移出分子 = 让独立真值迁就系统的建模缺口，两边一起错而指标显示一致。
   ⇒ 新状态必须在 `MISSED_STATES` 里。

2. **上界与召回同单位、且上界不是召回。**
   `state_counts` 按**作用域行**计，分母 `applicable_item_count` 按**去重组**计。
   拿行数去减组数分母就是混单位——写这段时我第一版正是这么写的，改了才对。
   ⇒ 锁 `supply_side_gap_count` 来自组级字段，且 ≤ 漏组数。

3. **判据只用事实包能看见的东西。**
   阅卷器不许连数据库。更细的三分（本栋有组件无片段 131 / 本栋无该组件 12 /
   池词汇表无此类 183）要查知识图谱，属分析层。
   ⇒ 阅卷器的判据严格是「本栋无该类片段」这个可机械复核的事实。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402


def test_supply_side_states_still_count_as_missed() -> None:
    """供给侧缺口**仍是漏**——绝不能移出分子。"""
    for state in scorer.SUPPLY_SIDE_STATES:
        assert state in scorer.MISSED_STATES, f"{state} 被移出 MISSED_STATES 了"
        assert state not in scorer.COVERED_STATES


def test_component_class_without_fragment_is_labelled_supply_side() -> None:
    item = {
        "normative_item_id": "mbis.test.cc",
        "source_clause_id": "X",
        "scope_type": "component_class",
        "scope_id": "curtain_wall",
        "applicable": True,
        "expected_card_ids": ["rc.a"],
    }
    bundle = {"rc.a"}
    frag_comp = {"FRG-1": "external_wall"}          # 本栋只有外墙片段，没有幕墙
    got = scorer._classify_item(item, [], bundle, bundle, frag_comp)
    assert got == "supply_side_no_fragment_of_class"


def test_component_class_with_fragment_is_not_labelled_supply_side() -> None:
    """本栋**有**该类片段却仍无评估 ⇒ 是别的原因，不许贴供给侧标签。"""
    item = {
        "normative_item_id": "mbis.test.cc",
        "source_clause_id": "X",
        "scope_type": "component_class",
        "scope_id": "external_wall",
        "applicable": True,
        "expected_card_ids": ["rc.a"],
    }
    bundle = {"rc.a"}
    frag_comp = {"FRG-1": "external_wall"}
    got = scorer._classify_item(item, [], bundle, bundle, frag_comp)
    assert got == "retrieved_no_evaluation"


def test_building_scope_never_gets_supply_side_label() -> None:
    """楼级项没有「构件类」这个轴，不该落供给侧态。"""
    item = {
        "normative_item_id": "mbis.test.b",
        "source_clause_id": "X",
        "scope_type": "building",
        "scope_id": "BLD-1",
        "applicable": True,
        "expected_card_ids": ["rc.a"],
    }
    bundle = {"rc.a"}
    got = scorer._classify_item(item, [], bundle, bundle, {"FRG-1": "external_wall"})
    assert got not in scorer.SUPPLY_SIDE_STATES


def test_upper_bound_is_computed_in_group_units_and_never_replaces_recall() -> None:
    """上界与召回同单位（去重组），且分子不变——上界只能靠**缩小分母**变大。

    这条防的是「悄悄把供给侧算成覆盖」：那样分子会变，实测能立刻看出来。
    """
    buildings = [
        {"applicable_item_count": 10, "covered_count": 6,
         "missed_applicable_item_count": 4, "supply_side_gap_group_count": 3},
        {"applicable_item_count": 10, "covered_count": 8,
         "missed_applicable_item_count": 2, "supply_side_gap_group_count": 1},
    ]
    tot_a = sum(b["applicable_item_count"] for b in buildings)
    tot_c = sum(b["covered_count"] for b in buildings)
    tot_s = sum(b["supply_side_gap_group_count"] for b in buildings)
    recall = tot_c / tot_a
    upper = tot_c / (tot_a - tot_s)
    assert recall == 14 / 20
    assert upper == 14 / 16              # 分子不变，只缩分母
    assert upper > recall
    # 供给侧组数不得超过漏组数——超了说明单位混了（行数混进组数）
    for b in buildings:
        assert b["supply_side_gap_group_count"] <= b["missed_applicable_item_count"]


def test_scorer_does_not_import_a_database_client() -> None:
    """阅卷器不许依赖数据库——细分账属分析层，不进阅卷。"""
    src = (SCRIPTS / "score_clause_coverage.py").read_text(encoding="utf-8")
    for forbidden in ("neo4j", "GraphDatabase", "Neo4jClient"):
        assert forbidden not in src, f"阅卷器里出现了 {forbidden}"
