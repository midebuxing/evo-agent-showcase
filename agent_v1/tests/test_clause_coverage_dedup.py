"""验收标准③评分脚本的分母去重口径锁定（2026-07-27 立）。

为什么有这个测试：真值文件里同一 (楼, 规范性原子项) 会被记在两个作用域上
（`fragment` 行 + `component_class` 行），三元组主键 `(building_id,
normative_item_id, scope_id)` 不冲突，所以**看不出重复**，但分母把同一条义务
数了两次。已知 4 对，全在 TOWER-0008 上。

去重口径：分母按 `(building_id, normative_item_id)` 去重，组内
「**任一作用域漏了则整组算漏**」。这里锁定两件事：

1. 同项跨双作用域**不重复计入分母**（两行 → 一个分母单位）。
2. 「一个作用域覆盖了、另一个作用域漏了」**仍然被算成漏**，即门槛不被去重放松。
   这条是关键——去重若按"任一覆盖即算覆盖"聚合，就会把真实漏单洗掉。

外加锁定：逐行信息不丢（`scope_row_count` / `missed_scope_row_count` 仍按作用域计）。
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

BUILDING = "BLD-TEST-DEDUP-0001"
ITEM = "mbis.cop2023.sX.dual_scope_item"
CARD_COVERED = "rc.test.covered"
CARD_MISSED = "rc.test.missed"
FRAG_OK = "FRG-TEST-OK-01"
FRAG_BAD = "FRG-TEST-BAD-01"


def _truth_row(scope_type: str, scope_id: str, normative_item_id: str = ITEM,
               expected_card_ids: list[str] | None = None) -> dict:
    return {
        "schema_version": "applicable_normative_item_truth_v1",
        "world_id": "WB-TEST-DEDUP-0001-S00301",
        "building_id": BUILDING,
        "normative_item_id": normative_item_id,
        "source_clause_id": "3.4.2(B)(a)",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "applicable": True,
        "modality_zh": "shall",
        "conditionality": "unconditional",
        "reason": "测试造具",
        "expected_card_ids": expected_card_ids if expected_card_ids is not None else [CARD_COVERED],
        "zh_source_excerpt": "測試",
    }


@pytest.fixture
def batch(tmp_path_factory):
    """两个片段：FRAG_OK 有确定求值，FRAG_BAD 只被检索到、无任何求值记录。

    两个片段的 component_type_key 同为 cantilevered_canopy，故
    component_class 作用域会同时匹配到两者。
    """
    root = tmp_path_factory.mktemp("dedup_batch")
    run = root / "buildings" / BUILDING / "runs" / "CAR-TEST"
    run.mkdir(parents=True)
    (run / "fact_pack.json").write_text(json.dumps({
        "facts": [
            {"carrier_type": "fragment", "carrier_id": FRAG_OK, "slot_id": "fragment_role",
             "qualifiers": {"component_type_key": "cantilevered_canopy"}},
            {"carrier_type": "fragment", "carrier_id": FRAG_BAD, "slot_id": "fragment_role",
             "qualifiers": {"component_type_key": "cantilevered_canopy"}},
        ]
    }), encoding="utf-8")
    (run / "rule_slice.json").write_text(json.dumps({
        "candidate_rule_cards": [{"rule_card_id": CARD_COVERED}, {"rule_card_id": CARD_MISSED}]
    }), encoding="utf-8")
    (run / "obligation_set.json").write_text(json.dumps({
        "obligations": [
            {"source_rule_card_id": CARD_COVERED, "fragment_id": FRAG_OK,
             "satisfaction_status": "satisfied", "closure_status": "closed", "kind": "action"},
        ]
    }), encoding="utf-8")
    return root


def _score(batch, rows):
    return scorer.score_building(batch / "buildings" / BUILDING, rows,
                                 {CARD_COVERED, CARD_MISSED})


def test_dual_scope_item_counted_once_in_denominator(batch):
    """同一原子项记在 fragment + component_class 两个作用域 → 分母只算一次。"""
    rows = [
        _truth_row("fragment", FRAG_OK),
        _truth_row("component_class", "cantilevered_canopy"),
    ]
    res = _score(batch, rows)
    assert res["scope_row_count"] == 2, "逐行计数应仍看到两行"
    assert res["applicable_item_count"] == 1, "分母必须按 (楼, 原子项) 去重"
    assert res["covered_count"] == 1
    assert res["missed_applicable_item_count"] == 0
    assert res["applicable_item_recall"] == 1.0
    assert ITEM in res["multi_scope_items"]


def test_missed_in_one_scope_still_counts_as_missed(batch):
    """一个作用域覆盖了、另一个作用域漏了 —— 整组仍算漏，门槛不被去重放松。

    FRAG_OK 行：期望卡有确定求值 → 覆盖。
    FRAG_BAD 行：期望卡换成只进检索、无求值 → `retrieved_no_evaluation`（漏）。
    """
    rows = [
        _truth_row("fragment", FRAG_OK, expected_card_ids=[CARD_COVERED]),
        _truth_row("fragment", FRAG_BAD, expected_card_ids=[CARD_MISSED]),
    ]
    per_scope = {r["scope_id"]: None for r in rows}
    res = _score(batch, rows)
    for item in res["items"]:
        per_scope[item["scope_id"]] = item["state"]

    assert per_scope[FRAG_OK] == "evaluated_determinate"
    assert per_scope[FRAG_BAD] == "retrieved_no_evaluation"
    assert res["scope_row_count"] == 2
    assert res["missed_scope_row_count"] == 1, "逐行漏单必须保留「漏在哪个作用域」"
    assert res["applicable_item_count"] == 1, "两行仍是同一原子项，分母一次"
    assert res["missed_applicable_item_count"] == 1, "任一作用域漏 → 整组算漏"
    assert res["covered_count"] == 0
    assert res["gate_pass"] is False, "去重口径绝不能让这种情形过门"
    assert {m["scope_id"] for m in res["missed_items"]} == {FRAG_BAD}


def test_gate_semantics_unchanged_by_dedup(batch):
    """去重只改分母与比率，不改过门语义：全行覆盖 ⟺ 组级漏单为 0。"""
    all_covered = [
        _truth_row("fragment", FRAG_OK),
        _truth_row("component_class", "cantilevered_canopy"),
    ]
    assert _score(batch, all_covered)["gate_pass"] is True

    with_one_miss = all_covered + [
        _truth_row("fragment", FRAG_BAD, normative_item_id="mbis.cop2023.sY.other",
                   expected_card_ids=[CARD_MISSED]),
    ]
    res = _score(batch, with_one_miss)
    assert res["applicable_item_count"] == 2
    assert res["missed_applicable_item_count"] == 1
    assert res["gate_pass"] is False


def test_distinct_items_are_not_merged(batch):
    """不同原子项即便落在同一作用域，也各占一个分母单位（去重键不含 scope）。"""
    rows = [
        _truth_row("fragment", FRAG_OK, normative_item_id="mbis.cop2023.sA.one"),
        _truth_row("fragment", FRAG_OK, normative_item_id="mbis.cop2023.sB.two"),
    ]
    res = _score(batch, rows)
    assert res["applicable_item_count"] == 2
    assert res["multi_scope_items"] == {}
