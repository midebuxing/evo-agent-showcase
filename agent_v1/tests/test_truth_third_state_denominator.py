"""真值第三态 `unknown_pending` 的分母处置口径锁定（2026-08-05，#25 真值落改案）。

## 红先行探针（本文件的存在理由）

`决议_真值落改_20260805.md` §三.2 要求：`unknown_pending` **不进**召回分母、
**不进**精确率分母、单独计数出报表。

落改前实测（本文件首版即为此写）：`score_clause_coverage.py:851` 是
`if item["applicable"]:` ——**Python 真值判断而非 `is True`**。非空字符串
`"unknown_pending"` 恒真 ⇒ 第三态被**静默**计进召回分母 D，不报任何错、
不留任何痕迹，只是把召回拉低。`:960` 的 `_item_by_key` 同形。

⇒ `test_pending_row_stays_out_of_recall_denominator` 在旧代码上必红
（`applicable_item_count == 2`、`applicable_item_recall == 0.5`），
修后转绿（`1` / `1.0` / `pending_item_count == 1`）。
这条红是本案「不许先落数据后改代码」的机械凭证，**留作回归**。

## 为什么必须用 `score_building` 而不是复制判据

本仓成例（`_group_gate_layer` 的 docstring）：内联逻辑 + 复制式测试 = 假的变异验证。
故本文件一律走生产函数，不在测试里重写真值判断。

## 变异验证（写测试时实跑过）

- 把 `_truth_applicable_state` 的 `is True` 改回 `if item["applicable"]`
  ⇒ `test_pending_row_stays_out_of_recall_denominator` 失败
- 把第三态并进 `else`（精确率侧）分支
  ⇒ `test_pending_row_stays_out_of_precision_denominator` 失败
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

BUILDING = "BLD-TEST-THIRD-STATE-0001"
CARD_OK = "rc.test.third_state.covered"
FRAG = "FRG-TEST-THIRD-STATE-01"

#: 真值第三态的**唯一**合法编码（schema 为 boolean ∪ const "unknown_pending"）。
PENDING = "unknown_pending"


def _row(normative_item_id: str, applicable, expected_card_ids: list[str]) -> dict:
    return {
        "schema_version": "applicable_normative_item_truth_v1",
        "world_id": "WB-TEST-THIRD-STATE-0001-S00301",
        "building_id": BUILDING,
        "normative_item_id": normative_item_id,
        "source_clause_id": "2.1.3(n)",
        "scope_type": "building",
        "scope_id": BUILDING,
        "applicable": applicable,
        "modality_zh": "shall",
        "conditionality": "trigger_conditioned",
        "reason": "测试造具（判据情形 2）",
        "expected_card_ids": expected_card_ids,
        "zh_source_excerpt": "測試",
    }


ITEM_TRUE = "mbis.test.third_state.applicable_true"
ITEM_FALSE = "mbis.test.third_state.applicable_false"
ITEM_PENDING = "mbis.test.third_state.pending"


@pytest.fixture
def building_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("third_state_batch")
    bdir = root / "buildings" / BUILDING
    run = bdir / "runs" / "RUN-TEST"
    run.mkdir(parents=True)
    (run / "fact_pack.json").write_text(json.dumps({
        "facts": [
            {"carrier_type": "fragment", "carrier_id": FRAG, "slot_id": "fragment_role",
             "qualifiers": {"component_type_key": "external_wall"}},
        ]
    }), encoding="utf-8")
    (run / "rule_slice.json").write_text(json.dumps({
        "candidate_rule_cards": [{"rule_card_id": CARD_OK}],
    }), encoding="utf-8")
    (run / "obligation_set.json").write_text(json.dumps({
        "obligations": [
            {"obligation_id": "OB-1", "source_rule_card_id": CARD_OK,
             "kind": "action", "scope_type": "building", "scope_id": BUILDING,
             "applicability_state": "applicable",
             "satisfaction_status": "satisfied", "closure_status": "closed"},
        ]
    }), encoding="utf-8")
    return bdir


@pytest.fixture
def items() -> list[dict]:
    """三行真值，每态一行。

    第三态那行**故意不给期望卡**（`not_modeled` ⇒ 若被误收进分母必然记漏），
    这样「静默进分母」不只是数字变大，而是直接把召回从 1.0 拉到 0.5——
    与旧代码的真实危害同形。
    """
    return [
        _row(ITEM_TRUE, True, [CARD_OK]),
        _row(ITEM_FALSE, False, [CARD_OK]),
        _row(ITEM_PENDING, PENDING, []),
    ]


@pytest.fixture
def result(building_dir, items) -> dict:
    return scorer.score_building(building_dir, items, {CARD_OK})


# ── 红先行探针：第三态不得进召回分母 ───────────────────────────────────


def test_pending_row_stays_out_of_recall_denominator(result):
    """🔴 本案红先行探针。旧代码上 `applicable_item_count == 2` 必红。"""
    assert result["applicable_item_count"] == 1, (
        "第三态被计进召回分母 D——`score_clause_coverage.py` 的真值判断"
        "把非空字符串 'unknown_pending' 当成了「适用」。"
        f"实得 applicable_item_count={result['applicable_item_count']}，期望 1。"
    )
    assert result["missed_applicable_item_count"] == 0
    assert result["applicable_item_recall"] == 1.0, (
        "第三态静默进分母会拉低召回且无任何提示——本项目记过的"
        "「关键配置静默退化」族。"
    )


def test_pending_row_stays_out_of_precision_denominator(result):
    """第三态也不得落进精确率侧反向闸（分母 ＝ `applicable is False` 的行数）。

    ⚠️ 该分母**不是常数**：它是真值文件自身的属性，随每次真值落改变化
    （本案落改后 443 → 423，`443` 是**落改前**的历史值，已作废——#25 审核门必须修 4）。
    故本断言只锁「三行合成真值里恰有 1 行 `applicable is False`」这个**结构关系**，
    不锁任何全库计数。
    """
    total_exclusion_checks = sum(result["structural_exclusion_checks"].values())
    assert total_exclusion_checks == 1, (
        "精确率侧分母只收 `applicable is False` 的行。"
        f"实得 {total_exclusion_checks} 条，期望 1（仅 ITEM_FALSE）。"
    )


def test_pending_row_is_counted_separately(result):
    """第三态必须单独计数出报表——否则挂起量增长会静默缩小分母。"""
    assert result["pending_item_count"] == 1, (
        "挂起量未单独出报表：分母变小而没人看得见，等于洗分母。"
    )


def test_pending_row_appears_in_per_item_with_pending_marker(result):
    """逐行明细不得丢掉第三态（既不评分也不能消失）。"""
    by_item = {r["normative_item_id"]: r for r in result["items"]}
    assert set(by_item) == {ITEM_TRUE, ITEM_FALSE, ITEM_PENDING}
    pending_row = by_item[ITEM_PENDING]
    assert pending_row["state"] is None
    assert pending_row["is_missed"] is False
    assert pending_row.get("truth_pending") is True
    assert "structural_exclusion_check" not in pending_row


def test_true_and_false_rows_unchanged(result):
    """回归：前两态的处置一个字节不动。"""
    by_item = {r["normative_item_id"]: r for r in result["items"]}
    assert by_item[ITEM_TRUE]["state"] is not None
    assert by_item[ITEM_TRUE]["is_missed"] is False
    assert by_item[ITEM_FALSE]["state"] is None
    assert "structural_exclusion_check" in by_item[ITEM_FALSE]
    assert by_item[ITEM_FALSE].get("truth_pending") is not True


# ── 判据本身的源码级锁：不许退回真值判断 ─────────────────────────────


def test_truth_judgement_is_identity_not_truthiness():
    """源码级断言：真值三态判据必须走 `is True` / `is False` 语义。

    锁这条是因为「退回 `if item['applicable']`」不会报错、不会红别的测试，
    只会让第三态重新静默进分母。
    """
    import inspect

    src = inspect.getsource(scorer._truth_applicable_state)
    assert "is True" in src, "真值判断必须用 `is True`，不许用 Python 真值判断"
    assert PENDING in src, "第三态编码必须出现在判据里"
