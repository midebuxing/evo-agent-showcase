"""gap 清单·池无关结构层（P9 两层拆分，2026-08-06）。

案源：GAP_ANCHOR_BATCH_STALE——旧锚池人群维持「精确」缺口库存，
`.intended` 被报成新增缺项（`决议_换池前置_20260805.md` §二 P9）。

本层只断**架构关系**（注册表/别名/槽角色/允许路径之间的映射存在性），
不引任何池观察值——换池零影响，这正是拆层的意义：

- 池相关观察层在 `test_slot_alias_reconciliation.py`，对照
  `gap_observation_manifest`（生成器
  `agent_v1/scripts/build_gap_observation_manifest.py`）；
- 「`.intended` 到底缺不缺」在结构层的答案是**不缺**：卡侧语义登记表声明了它
  （角色 trigger），worldgen `sidecar_bool_slot_registry` 声明产出它——
  两端映射齐备，「缺」只是旧池的观察事实，归观察层记账。
  这类「池一换就假报」的形状从此被结构消化。

读者按行核对：本文件所有输入都是仓库内权威登记物（卡包 JSON、worldgen
注册表构建器），无一来自 experiments 批产物。
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

from build_gap_observation_manifest import (  # noqa: E402
    ALIAS_BRIDGE_CARD_SLOT,
    ALIAS_BRIDGE_WORLD_SLOT,
    BETA_COMPOSITE_LOOKUP_SLOTS,
    CARD_PACK,
    alias_keys,
    card_side_slots,
)

INTENDED = "procedure.investigation.detailed.intended"


def _mapping_doc() -> dict:
    import json

    return json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )


def test_registries_nonempty_and_digest_precondition() -> None:
    """结构输入自检：两份登记物非空，且槽名不含换行（成员摘要分帧前提）。"""
    card = card_side_slots()
    aliases = alias_keys()
    assert len(card) >= 40
    assert len(aliases) >= 10
    assert not [s for s in card | aliases if "\n" in s]


def test_misconnection_alias_row_exact() -> None:
    """已补桥别名：键→目标逐字符锁死（映射表内部关系，与池无关）。"""
    from evo_agent_baseline.slot_alias_policy import normalize_alias_map

    aliases = normalize_alias_map(_mapping_doc().get("slot_aliases") or {})
    assert aliases.get(ALIAS_BRIDGE_CARD_SLOT) == ALIAS_BRIDGE_WORLD_SLOT
    # 死桥已删：卡侧名不得再假装有桥（2026-07-28 裁定，见观察层沿革）。
    assert "scope.component.covered_by_large_attached_signboard" not in aliases
    # 桥的键必须真是卡侧声明过的名字——别名表不许桥接幽灵槽。
    assert ALIAS_BRIDGE_CARD_SLOT in card_side_slots()


def test_beta_slots_are_composite_lookup_rules() -> None:
    """乙组「禁简化为单名别名」的结构依据：slot_targets 里是复合 lookup_rule。"""
    slot_targets = _mapping_doc().get("slot_targets") or {}
    for slot in BETA_COMPOSITE_LOOKUP_SLOTS:
        rule = (slot_targets.get(slot) or {}).get("lookup_rule") or {}
        clauses = rule.get("clauses") or []
        assert len(clauses) >= 2, (
            f"{slot} 不是复合 lookup_rule（子句 {len(clauses)} 条），"
            "「禁简化为单名别名」这条理由要重判"
        )


def test_intended_mapping_exists_on_both_sides() -> None:
    """`.intended` 两端登记齐备，结构上**没有**缺口。

    - 卡侧：`semantic_slot_registry_v1.json` 声明该槽，允许角色含 trigger；
    - 世界侧：worldgen `sidecar_bool_slot_registry` 声明产出（bool、楼级）。

    「30 栋里 0 栋有事实」是旧池的观察值，归观察层 manifest 记账——
    在这里断言池观察就是把 GAP_ANCHOR_BATCH_STALE 的病灶重新焊回去。

    🔴 **2026-08-06 破封批拆掉一处残留耦合**：本条原来还断
    `GROUP_DELTA_ANCHOR_BATCH_STALE == {INTENDED}`——那是拿**观察层的分组成员**
    当结构层判据，正是拆层要消掉的东西。池 v2 上该槽已离开未覆盖集、丁组清空，
    这条断言随即假红，而它报的「失败」与本函数要证的结构命题毫无关系。
    ⇒ 只断两端登记，分组归属交给观察层
    （`test_slot_alias_reconciliation.py::test_delta_group_is_empty_and_says_why`）。
    """
    import json

    doc = json.loads(
        (CARD_PACK / "semantic_slot_registry_v1.json").read_text(encoding="utf-8")
    )
    by_id = {s.get("slot_id"): s for s in doc["slots"]}
    rec = by_id.get(INTENDED)
    assert rec is not None, f"{INTENDED} 不在卡侧语义登记表"
    assert "trigger" in (rec.get("allowed_roles") or []), (
        f"{INTENDED} 卡侧角色声明变了：{rec.get('allowed_roles')}"
    )

    sys.path.insert(0, str(AGENT_ROOT / "src"))
    from workflow_engine.worldgen.registry import _build_registry_bundle

    bundle = _build_registry_bundle()
    bool_records = None
    for registry in bundle.registries:
        if registry.registry_id == "sidecar_bool_slot_registry":
            bool_records = {r["slot_id"]: r for r in registry.records}
            break
    assert bool_records, "sidecar_bool_slot_registry 不在 worldgen 注册表束里"
    world_rec = bool_records.get(INTENDED)
    assert world_rec is not None, (
        f"{INTENDED} 不在 worldgen sidecar_bool_slot_registry——"
        "「锚批陈旧」定性的世界侧那半塌了"
    )
    assert world_rec["value_type"] == "bool"
