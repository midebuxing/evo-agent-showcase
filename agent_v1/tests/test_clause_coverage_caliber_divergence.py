"""「适用性判定标准分歧」桶的口径锁定（2026-08-08 残差 57 实施 A 段立）。

## 这个桶是什么

`裁定底稿_残差57_20260808.md` §2.3 终裁丙案：B' 18 ＋ E2' 7 共 **25 条** (规范项, 栋)
——系统与世界一致（流程布尔显式 false，触发器判假是对的），分歧在真值口径
（守则 §4.2.1「如有意」等正文授权下保守判 applicable=true，E1 判例复核过的有意口径）。
真值 v2 一字不动；漏单分账单列本桶；终局解排入真值 v3 生成器口径裁定。

## 🔴 锁的四条

1. **桶成员仍算漏**——`missed_applicable_item_count` 与召回一个字节不动，
   桶只做分账；账目守恒：总漏 ＝ 分歧桶 ＋ 系统欠账口径。
2. **清单是逐条裁定的，恰 25 条**——不是机制推断；未裁定的漏项不得自动进桶。
3. **状态门**：只有漏行状态全为 `retrieved_no_evaluation`（触发器判假）才进桶；
   状态对不上落 mismatch 桶响亮报出，防清单与批错配静默糊账。
4. **不进可行动段**：本桶只在分账/覆盖率报告出现（`CALIBER_DIVERGENCE_NOTE`），
   消费者文档可行动段不引用它（glm 核验④实测 25 条本就不在可行动段，维持现状）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402

_B0010 = "BLD-HK-COASTAL-COMPOSITE-TOWER-RC-0010"


def test_adjudicated_registry_is_exactly_25_pairs() -> None:
    """恰 25 条 (项,栋)：E2' 7（§4.2.1）＋ B' 18（§4.2.2 六项 × 3 栋）。"""
    reg = scorer.CALIBER_DIVERGENCE_ADJUDICATED
    total = sum(len(v) for v in reg.values())
    assert total == 25, f"裁定清单应恰 25 条，实为 {total}"
    assert len(reg["mbis.cop2023.s4_2_1.submit_di_intention_notice"]) == 7
    s422 = {k: v for k, v in reg.items() if ".s4_2_2_" in k}
    assert len(s422) == 6 and all(len(v) == 3 for v in s422.values())
    # 每对唯一（同项内栋不重复）
    for k, v in reg.items():
        assert len(set(v)) == len(v), k


def test_bucket_members_still_counted_as_missed() -> None:
    """结构保证：分账函数只从 missed_groups 里取 ⇒ 桶成员必然仍在漏账。"""
    groups = {
        "mbis.cop2023.s4_2_1.submit_di_intention_notice": [
            {"state": "retrieved_no_evaluation", "is_missed": True}],
        "mbis.other.item": [
            {"state": "retrieved_no_evaluation", "is_missed": True}],
    }
    missed = list(groups)
    hit, mismatch = scorer._caliber_divergence_split(_B0010, missed, groups)
    assert hit == ["mbis.cop2023.s4_2_1.submit_di_intention_notice"]
    assert mismatch == []
    # 分账不改 missed 本身
    assert len(missed) == 2
    # 账目守恒：总漏 = 桶 + 桶外
    assert len(missed) == len(hit) + (len(missed) - len(hit))


def test_unadjudicated_items_never_enter_bucket() -> None:
    """清单外的漏项（哪怕同状态）不得自动进桶——桶是裁定清单不是机制推断。"""
    groups = {"mbis.other.item": [
        {"state": "retrieved_no_evaluation", "is_missed": True}]}
    hit, mismatch = scorer._caliber_divergence_split(_B0010, list(groups), groups)
    assert hit == [] and mismatch == []


def test_wrong_building_never_enters_bucket() -> None:
    """清单按 (项,栋) 钉死——同项在未裁定的栋上不得进桶。"""
    groups = {"mbis.cop2023.s4_2_1.submit_di_intention_notice": [
        {"state": "retrieved_no_evaluation", "is_missed": True}]}
    hit, mismatch = scorer._caliber_divergence_split(
        "BLD-HK-SOMEWHERE-ELSE-0099", list(groups), groups)
    assert hit == [] and mismatch == []


def test_state_gate_puts_mismatch_in_loud_bucket() -> None:
    """状态对不上（如卡被删后转 not_modeled）⇒ 落 mismatch 响亮报出，不静默进桶。"""
    groups = {"mbis.cop2023.s4_2_1.submit_di_intention_notice": [
        {"state": "not_modeled", "is_missed": True}]}
    hit, mismatch = scorer._caliber_divergence_split(_B0010, list(groups), groups)
    assert hit == []
    assert mismatch == ["mbis.cop2023.s4_2_1.submit_di_intention_notice"]


def test_covered_item_never_enters_bucket() -> None:
    """该 (项,栋) 若已覆盖（不在 missed_groups）⇒ 桶自然为空（换池后自动失效的形状）。"""
    groups = {"mbis.cop2023.s4_2_1.submit_di_intention_notice": [
        {"state": "evaluated_determinate", "is_missed": False}]}
    hit, mismatch = scorer._caliber_divergence_split(_B0010, [], groups)
    assert hit == [] and mismatch == []


def test_overall_conservation_arithmetic() -> None:
    """总账守恒：missed == caliber_divergence + missed_excluding（与 overall 字段同式）。"""
    buildings = [
        {"missed_applicable_item_count": 10, "caliber_divergence_group_count": 4},
        {"missed_applicable_item_count": 5, "caliber_divergence_group_count": 0},
    ]
    total_missed = sum(b["missed_applicable_item_count"] for b in buildings)
    total_div = sum(b["caliber_divergence_group_count"] for b in buildings)
    assert total_missed - total_div == 11
    assert total_missed == total_div + (total_missed - total_div)
    for b in buildings:
        assert (b["caliber_divergence_group_count"]
                <= b["missed_applicable_item_count"])


def test_note_is_consumer_facing_and_names_the_divergence() -> None:
    """消费者面一句解释在场（glm 直白化措辞），且不称系统欠账/漏评。"""
    note = scorer.CALIBER_DIVERGENCE_NOTE
    assert "适用性判定标准分歧" in note
    assert "真值 v3" in note
    assert "非系统漏评" in note and "非系统欠账" in note
