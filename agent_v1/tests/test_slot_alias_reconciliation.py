"""数据对账：卡侧槽名 ⊆ 世界槽名 ∪ 别名键（2026-07-27）。

`slot_alias_policy` 只管"**已登记的别名怎么查**"，管不了"**表里缺条目**"。
静态扫描（`test_slot_alias_normalization_scan.py`）同样一条都看不见缺条目。
这个缺口只能靠数据对账盯：卡包声明要用的每一个语义槽，要么世界侧真的产出同名
事实，要么别名表里有一行把它落到世界侧名——两者皆无 ⇒ 该槽的义务**必然永远
不闭合**，而现象是一条毫无线索的 `unknown`。

## 输入（全部是真产物，不造假桩）

- 卡侧：卡包 `semantic_slot_registry_v1.json` 的 51 个 `slot_id`
  （＝卡包**声明**的语义槽词表；比 `rule_cards.json` 里实际被引用的 45 个更宽，
  正是要盯"声明了却接不上"这一类）。
- 世界侧：真实批 `baseline_batch_final_seed301` 的 30 份 `fact_pack.json` 里
  出现过的全部 `slot_id`（192 个）。批产物缺席时 skip——experiments 目录整体
  不入库，别在无产物的机器上假绿。
- 别名表：`projection_runtime_mapping_v1.json` 的 `slot_aliases`，经
  `slot_alias_policy.normalize_alias_map` 归一后的键集（含 `_note_*` 注释键；
  真别名见 mapping 文件）。

## 🔴 当前状态：xfail（已知 17 个缺项，非本次接线能修）

⚠️ **这不是"测试写坏了"，是真实缺口的登记**。三分类如下（甲乙丙的处置方式
根本不同，**不许一刀切补别名**）：

### 甲 · 真缺一行别名（4 个）——世界侧有对得上的名字，加一行就好

| 卡侧槽名 | 世界侧现名 |
|---|---|
| `defect.subdivided_unit_sign.present` | `subdivided_unit_sign.present` |
| `defect.ubw.present` | `ubw.present` |
| `investigation.fsp.below_required_safety` | `assessment.fsp.below_required_safety` |
| `repair.maintenance.required_before_next_cycle` | `maintenance.pre_next_cycle.required` |

（世界侧现名均已在本测试所用真实批里核过，不是猜的。）
✅ `defect.drainage.misconnection.present` → `drainage.misconnection.present`
已于 2026-07-28 补桥（phase_d 批实测世界侧 208 条；中文守则「排水系統錯誤接駁」）。

### 乙 · 🔴 禁简化为单名别名（5 个）——补一行单值别名会**造出假违规**

- `reporting.artifact.{signed,submitted,delivered}`：世界侧没有"某份文书被签署/
  呈交/送达"的单一事实；`artifact.*` 那一族是"文书存在"，`procedure.*.submitted`
  是"程序节点完成"。把三者随便挂到某个世界槽上，等于宣称"文书已签署"这种
  事实系统能证明——它不能。
- `actor.representative.qualified_for_assigned_role` 与
  `procedure.investigation.detailed.started`：这两个在 `slot_targets` 里登记的是
  **复合 `lookup_rule`**（多子句合取，含 `contains_requested_qualifier` 形态），
  语义是"由若干世界事实**推导**出来"，不是"改个名就是同一件事"。压成单名别名
  会让 §4.2.3 那条本该 unknown 的义务变成**假违规**。
  ⇒ 正解是走 `slot_targets` 派生通道，不是别名表。

### 丙 · 世界侧真无对应（8 个）——补别名无处可补，是供给侧/建模边界问题

`actor.ri.authorized_person_functions.assumed` /
`defect.cause.non_normal_deterioration` /
`procedure.minor_works.regulation_27.applies` /
`procedure.person.decides_to_proceed_with_investigation` /
`procedure.person.informed_of_ba_refusal` /
`procedure.investigation.proposal.refused_by_ba` /
`reporting.record.submitted` /
`scope.component.covered_by_large_attached_signboard`

其中「某人决定继续调查」「某人被告知 BA 拒绝」这类，世界模型只建"东西现在是
什么状态"、不建"谁做过什么"——**属于该由专业人员告知的"有故 unknown"**，不是
系统缺陷。别当供给侧缺口去补。

`scope.component.covered_by_large_attached_signboard`（2026-07-28）：曾有死别名指向
世界侧亦不存在的 `covered_by_large_signboard`；`scope.component.covered` 的
`obscuration_class=signboard` **不等于**守则 §3.3.2(J)(b)「展示面積多於40平方米
的靠牆招牌」——阈值轴 `area.signboard.display` 亦零事实。已删死别名，记为供给侧缺口。

## 诚实边界

1. 世界侧集合取自**这一个批**（30 栋、seed301）。换池/换 seed 后世界侧槽集合
   可能不同——本测试断言的是"卡包与这份世界产物之间"的对账，不是全宇宙结论。
2. `slot_aliases` 里有一个 `_note_record_maintained` 键，值是中文说明**不是槽名**
   （`normalize_alias_map` 对 str 值原样收下，故它混在 15 个键里）。它不会影响
   本对账（卡侧不会有这个名字），但**别把 15 当成"14 个真别名"以外的数**。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Set

import pytest

from evo_agent_baseline.slot_alias_policy import normalize_alias_map

AGENT_ROOT = Path(__file__).resolve().parents[1]
CARD_PACK = AGENT_ROOT / "regulations" / "rulecard_v2" / "mbis_cop_2023"
REAL_BATCH = AGENT_ROOT / "experiments" / "baseline_batch_final_seed301"

# 当前已知缺项（三分类见模块 docstring）。
GAP_ALIAS_MISSING = {  # 甲：真缺一行别名
    "defect.subdivided_unit_sign.present",
    "defect.ubw.present",
    "investigation.fsp.below_required_safety",
    "repair.maintenance.required_before_next_cycle",
}
GAP_NOT_A_RENAME = {  # 乙：禁简化为单名别名
    "reporting.artifact.signed",
    "reporting.artifact.submitted",
    "reporting.artifact.delivered",
    "actor.representative.qualified_for_assigned_role",
    "procedure.investigation.detailed.started",
}
GAP_WORLD_HAS_NONE = {  # 丙：世界侧真无对应
    "actor.ri.authorized_person_functions.assumed",
    "defect.cause.non_normal_deterioration",
    "procedure.minor_works.regulation_27.applies",
    "procedure.person.decides_to_proceed_with_investigation",
    "procedure.person.informed_of_ba_refusal",
    "procedure.investigation.proposal.refused_by_ba",
    "reporting.record.submitted",
    "scope.component.covered_by_large_attached_signboard",
}
# 丁：**世界侧已产出，只是对账锚批早于该槽落地**（2026-08-05 立，乙路 #30）
#
# 🔴 这一组与甲/乙/丙**性质完全不同**，不许混进去：它不是缺口，是**锚批陈旧**。
# `REAL_BATCH = baseline_batch_final_seed301` 是本对账的世界侧锚，而
# `procedure.investigation.detailed.intended` 是 2026-07-31 才加进 worldgen
# `sidecar_bool_slot_registry` 的（楼级、prevalence 0.32）。
# **实测两批并排**（本次亲跑，不是推断）：
#   - 锚批 `baseline_batch_final_seed301`：30 栋里 **0 栋**有该槽事实；
#   - 当前批 `wave1_closing_seed401_20260804`：30 栋里 **30 栋**都有（真 10 / 假 20）。
# ⇒ 「无处可落」在锚批上字面为真，在当前世界上为假。按甲/乙/丙任一分类都会写下
# 一句错话（既不是缺别名、也不是禁简化、更不是世界侧真无对应）。
#
# **该怎么消掉它**：把 `REAL_BATCH` 换成含该槽的批（属独立小案——换锚会同时移动
# 甲/乙/丙三组的判定基础，须逐项复核，不许顺手在本单里换）。
GAP_ANCHOR_BATCH_STALE = {
    "procedure.investigation.detailed.intended",
}
KNOWN_GAPS = (
    GAP_ALIAS_MISSING | GAP_NOT_A_RENAME | GAP_WORLD_HAS_NONE | GAP_ANCHOR_BATCH_STALE
)


def card_side_slots() -> Set[str]:
    """卡包声明的语义槽词表（`semantic_slot_registry_v1.json`）。"""
    doc = json.loads(
        (CARD_PACK / "semantic_slot_registry_v1.json").read_text(encoding="utf-8")
    )
    return {s["slot_id"] for s in doc["slots"] if s.get("slot_id")}


def alias_keys() -> Set[str]:
    """别名表键集（经统一入口归一，不复制第二份归一逻辑）。"""
    doc = json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    return set(normalize_alias_map(doc.get("slot_aliases") or {}))


def world_side_slots() -> Set[str]:
    """真实批 30 份 FactPack 里出现过的世界侧槽名。"""
    packs = sorted(REAL_BATCH.glob("buildings/*/runs/*/fact_pack.json"))
    if not packs:
        pytest.skip(f"真实批产物缺席（experiments 目录不入库）：{REAL_BATCH}")
    out: Set[str] = set()
    for p in packs:
        for f in json.loads(p.read_text(encoding="utf-8")).get("facts") or []:
            if f.get("slot_id"):
                out.add(f["slot_id"])
    return out


def test_inputs_are_real_and_nonempty() -> None:
    """自检：三份输入都真读到了东西——否则"对账通过"是空集假绿。"""
    world = world_side_slots()
    assert len(card_side_slots()) >= 40
    assert len(world) >= 100, f"世界侧只读到 {len(world)} 个槽，批产物多半没读全"
    assert len(alias_keys()) >= 10


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知 18 个卡侧槽名在**本对账锚批**上既不在世界侧、也没有别名行"
        "（甲 4 补别名 / 乙 5 禁简化 / 丙 8 世界侧真无对应 / "
        "丁 1 锚批陈旧——世界侧其实已产出，见 GAP_ANCHOR_BATCH_STALE 注释）"
        "——见模块 docstring 分类。修完后本条转 xpass，届时删掉 xfail 标记。"
    ),
)
def test_card_slots_covered_by_world_or_alias() -> None:
    """目标态：卡侧槽名集合 ⊆ 世界槽名 ∪ 别名键。"""
    uncovered = card_side_slots() - world_side_slots() - alias_keys()
    assert not uncovered, (
        f"{len(uncovered)} 个卡侧槽名无处可落（这些槽的义务结构上永远不闭合）：\n"
        + "\n".join(f"  {s}" for s in sorted(uncovered))
    )


def test_known_gap_inventory_is_exact() -> None:
    """缺口清单**逐项**锁死——双向都要报警。

    这条才是日常起作用的那条（上面那条 xfail 只标目标态）：
    - 新增缺项（有人往卡包加了接不上的槽）→ 报警；
    - 缺项被补上了却没更新清单 → 报警，逼着把 docstring 的三分类一起改。
    """
    uncovered = card_side_slots() - world_side_slots() - alias_keys()
    assert uncovered == KNOWN_GAPS, (
        "缺口清单与实测不符——\n"
        f"  新增（清单里没有）：{sorted(uncovered - KNOWN_GAPS)}\n"
        f"  已消失（清单该删）：{sorted(KNOWN_GAPS - uncovered)}"
    )


def test_group_alpha_targets_really_exist_in_world() -> None:
    """甲组"真缺一行别名"的断言必须有据：世界侧确实有那个对应名。

    没有这一条，甲组就只是我写在 docstring 里的断言；有了它，"加一行别名就能通"
    是可执行的事实。
    """
    world = world_side_slots()
    targets = {
        "defect.subdivided_unit_sign.present": "subdivided_unit_sign.present",
        "defect.ubw.present": "ubw.present",
        "investigation.fsp.below_required_safety": "assessment.fsp.below_required_safety",
        "repair.maintenance.required_before_next_cycle": "maintenance.pre_next_cycle.required",
    }
    assert set(targets) == GAP_ALIAS_MISSING
    missing = {c: w for c, w in targets.items() if w not in world}
    assert not missing, f"甲组这些「世界侧现名」在真实批里不存在，分类判错了：{missing}"


def _raw_slot_aliases() -> dict:
    doc = json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    return normalize_alias_map(doc.get("slot_aliases") or {})


def test_fixed_misconnection_alias_target_exists_in_world() -> None:
    """已补的错接别名：键→目标必须等于世界真名（锁死目标，不只锁键）。

    `test_known_gap_inventory_is_exact` 只查别名**键**是否覆盖卡侧名——
    目标改错一个字符仍绿。本条补那道闸。
    """
    aliases = _raw_slot_aliases()
    world = world_side_slots()
    assert aliases.get("defect.drainage.misconnection.present") == (
        "drainage.misconnection.present"
    )
    assert "drainage.misconnection.present" in world
    # 死桥已删：卡侧名不得再假装有桥。
    assert "scope.component.covered_by_large_attached_signboard" not in aliases


def test_misconnection_alias_reaches_fact_index_consumer() -> None:
    """生产者→消费者端到端：JSON 别名经 `slot_aliases_from_policy` 进 `FactIndex` 后，
    卡侧名 `defect.drainage.misconnection.present` 必须命中世界侧那 208 条事实。

    只查 JSON 有行 + 世界有目标槽 ≠ 消费者真用得上。本条走：
    磁盘 mapping → `slot_aliases_from_policy` → `FactIndex.canonical_slot` →
    `slot_index` 查找。无别名对照必须 miss。
    """
    from evo_agent_baseline.closure.fact_binding import FactIndex
    from evo_agent_baseline.contracts import FactPack
    from evo_agent_baseline.slot_alias_policy import slot_aliases_from_policy

    card_side = "defect.drainage.misconnection.present"
    world_side = "drainage.misconnection.present"
    mapping_doc = json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    # 与闭包验证器同一入口：retrieval_policy 包裹 projection_runtime_mapping_v1
    aliases = slot_aliases_from_policy(
        {"projection_runtime_mapping_v1": mapping_doc}
    )
    assert aliases.get(card_side) == world_side

    packs = sorted(REAL_BATCH.glob("buildings/*/runs/*/fact_pack.json"))
    if not packs:
        pytest.skip(f"真实批产物缺席（experiments 目录不入库）：{REAL_BATCH}")

    hit_with_alias = 0
    hit_without_alias = 0
    world_raw = 0
    for path in packs:
        fact_pack = FactPack.model_validate_json(path.read_text(encoding="utf-8"))
        world_raw += sum(
            1 for f in fact_pack.facts if f.slot_id == world_side
        )
        indexed = FactIndex(fact_pack, slot_aliases=aliases)
        canon = indexed.canonical_slot(card_side)
        assert canon == world_side
        hit_with_alias += len(indexed.slot_index.get(canon, []))

        bare = FactIndex(fact_pack, slot_aliases={})
        assert bare.canonical_slot(card_side) == card_side
        hit_without_alias += len(bare.slot_index.get(card_side, []))
        # 世界侧裸名在无别名时仍按自身入索引
        assert len(bare.slot_index.get(world_side, [])) == sum(
            1 for f in fact_pack.facts if f.slot_id == world_side
        )

    assert world_raw == 208, f"世界侧错接事实数变了：{world_raw}"
    assert hit_with_alias == 208, (
        f"经别名后卡侧名只命中 {hit_with_alias}/208——"
        "别名未进入 FactIndex 消费路径"
    )
    assert hit_without_alias == 0, (
        "无别名时卡侧名不该命中；若命中说明世界已改用卡侧名，本闸前提变了"
    )


def test_group_beta_are_composite_lookup_rules_not_renames() -> None:
    """乙组"禁简化"的两条复合 lookup_rule 断言必须有据。

    `reporting.artifact.{signed,submitted,delivered}` 三个不在 slot_targets 里
    （它们是"世界侧根本没有这种事实"，理由在 docstring），故只查另外两条。
    """
    doc = json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    slot_targets = doc.get("slot_targets") or {}
    for slot in (
        "actor.representative.qualified_for_assigned_role",
        "procedure.investigation.detailed.started",
    ):
        rule = (slot_targets.get(slot) or {}).get("lookup_rule") or {}
        clauses = rule.get("clauses") or []
        assert len(clauses) >= 2, (
            f"{slot} 在 slot_targets 里不是复合 lookup_rule（子句 {len(clauses)} 条），"
            "「禁简化为单名别名」这条理由要重判"
        )
