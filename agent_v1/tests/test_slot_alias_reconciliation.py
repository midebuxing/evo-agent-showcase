"""数据对账·池相关观察层：卡侧槽名 ⊆ 世界槽名 ∪ 别名键（P9 两层拆分版，2026-08-06）。

`slot_alias_policy` 只管"**已登记的别名怎么查**"，管不了"**表里缺条目**"。
缺条目只能靠数据对账盯：卡包声明的每个语义槽，要么世界侧真产同名事实，要么
别名表有一行落到世界侧名——两者皆无 ⇒ 该槽义务**必然永远不闭合**，现象是一条
毫无线索的 `unknown`。

## 🔴 P9 两层拆分（案源 GAP_ANCHOR_BATCH_STALE，决议_换池前置_20260805.md §二 P9）

旧版把「精确缺口清单」硬编码在本文件里，锚批一陈旧就报假缺口——
`.intended` 在旧锚池 30 栋里 0 栋有事实、当前池 30/30 栋都有，
`test_known_gap_inventory_is_exact` 却把它报成"新增缺项"。故拆两层：

- **池无关结构层** `test_gap_inventory_structural.py`：只断注册表/别名/槽角色/
  允许路径的架构关系，换池零影响；
- **池相关观察层**（本文件）：对照 `gap_observation_manifest`（生成器
  `agent_v1/scripts/build_gap_observation_manifest.py`）——观察值、甲乙丙丁
  分类、池身份五件套全在 manifest 里，本文件**不再硬编码清单**。

**换池流程**：池 v2 → 逐项复核分类（生成器内嵌分类对不上会硬失败）→ 生成
**新** manifest 文件（文件名随批名变，旧 manifest 留档并排、禁原位重锚）→
把下面 `MANIFEST_PATH` 指到新文件。旧版模块 docstring 里甲乙丙丁的逐项裁定
理由已整体搬进生成器 docstring 与 `实施记录_P9gap拆层_20260806.md`。

## 双向报警语义（继承自旧 `test_known_gap_inventory_is_exact`）

- 新增缺项（有人往卡包加了接不上的槽）→ 实测未覆盖集 ≠ manifest → 红；
- 缺项被补上却没重建 manifest → 同样红，逼着走"复核分类 → 重建 manifest"。

## 诚实边界

1. 世界侧集合取自 manifest 钉住的**那一个批**；本文件断言的是"卡包与这份
   世界产物之间"的对账，不是全宇宙结论。
2. 批产物（experiments 不入库）缺席时池重算类测试 skip；manifest 本身是
   prereg 白名单内的小 JSON（入库），缺席按**失败**处理——它是契约不是产物。
3. `slot_aliases` 里的 `_note_*` 键值是中文说明不是槽名，混在键集里但不影响
   对账（卡侧不会有这种名字）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Set

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

from build_gap_observation_manifest import (  # noqa: E402
    ALIAS_BRIDGE_CARD_SLOT,
    ALIAS_BRIDGE_WORLD_SLOT,
    CARD_PACK,
    alias_keys,
    card_side_slots,
    member_set_sha256,
)

# 观察层对照的指定 manifest（换池后生成新文件并把这一行指过去；旧文件留档并排）。
# 2026-08-06 换池批破封批：由旧锚池 `baseline_batch_final_seed301` 指到池 v2
# 满血批。旧 manifest 文件留在同目录并排，不删不改（禁原位重锚）。
MANIFEST_PATH = (
    AGENT_ROOT
    / "experiments"
    / "prereg"
    / "gap_observation_manifest_poolv2_llm_seed401_20260806.json"
)
GROUP_KEYS = (
    "alpha_alias_missing",
    "beta_not_a_rename",
    "gamma_world_has_none",
    "delta_anchor_batch_stale",
)


def _manifest() -> dict:
    assert MANIFEST_PATH.is_file(), (
        f"gap_observation_manifest 缺席（它是入库契约不是批产物，缺席即失败）：\n"
        f"  {MANIFEST_PATH}\n"
        "  生成：python agent_v1/scripts/build_gap_observation_manifest.py"
    )
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _batch_dir(manifest: dict) -> Path:
    return REPO_ROOT / manifest["pool_identity"]["batch_dir"]


def _packs(manifest: dict) -> list[Path]:
    batch = _batch_dir(manifest)
    packs = sorted(batch.glob("buildings/*/runs/*/fact_pack.json"))
    if not packs:
        pytest.skip(f"真实批产物缺席（experiments 目录不入库）：{batch}")
    return packs


def _world_side_slots(manifest: dict) -> Set[str]:
    out: Set[str] = set()
    for p in _packs(manifest):
        for f in json.loads(p.read_text(encoding="utf-8")).get("facts") or []:
            if f.get("slot_id"):
                out.add(f["slot_id"])
    return out


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(c in "0123456789abcdef" for c in value)
    )


def test_manifest_five_identity_anchors_present() -> None:
    """池身份五件套逐件在场且形态对——缺任何一件，观察值就是无锚数字。"""
    m = _manifest()
    assert m.get("schema_version") == "gap_observation_manifest_v1"
    ident = m["pool_identity"]
    # ① 池目录
    assert ident.get("worldgen_run_dir"), "五件套①缺失：worldgen_run_dir"
    # ② 池内容哈希
    assert _is_hex(ident.get("pool_content_sha256"), 64), (
        "五件套②缺失或形态错：pool_content_sha256"
    )
    # ③ 生成配置哈希
    gen = ident.get("generation_config") or {}
    assert gen.get("file") and _is_hex(gen.get("sha256"), 64), (
        "五件套③缺失或形态错：generation_config"
    )
    # ④ 工作树哈希（生成 manifest 那一刻的代码状态锚）
    tree = ident.get("worktree_state") or {}
    assert _is_hex(tree.get("code_state_sha256"), 64), (
        "五件套④缺失或形态错：worktree_state.code_state_sha256"
    )
    assert _is_hex(tree.get("git_commit"), 40)
    # ⑤ 每组成员集合摘要
    groups = m["observation"]["groups"]
    assert tuple(sorted(groups)) == tuple(sorted(GROUP_KEYS)), (
        f"组集合变了：{sorted(groups)}——分类结构动过必须走复核重建，不许顺手改"
    )
    for key in GROUP_KEYS:
        assert _is_hex(groups[key].get("member_set_sha256"), 64), (
            f"五件套⑤缺失或形态错：groups[{key}].member_set_sha256"
        )


def test_group_digests_recompute_and_partition() -> None:
    """成员摘要必须由成员复算得出，且四组不重叠、并集＝未覆盖集。

    这条就是防"原位重锚/手改一条摘要"的闸：manifest 里任何一条
    member_set_sha256 被改动（或成员被增删而摘要没跟着走生成器）都红。
    """
    m = _manifest()
    obs = m["observation"]
    union: Set[str] = set()
    total = 0
    for key in GROUP_KEYS:
        group = obs["groups"][key]
        members = group["members"]
        assert group["member_count"] == len(members)
        assert group["member_set_sha256"] == member_set_sha256(members), (
            f"groups[{key}] 摘要与成员不符——manifest 被手改过或生成器没跑"
        )
        assert not (union & set(members)), f"组 {key} 与其它组有重叠成员"
        union |= set(members)
        total += len(members)
    assert total == len(union)
    assert union == set(obs["uncovered_slots"])
    assert obs["uncovered_count"] == len(obs["uncovered_slots"])
    assert obs["uncovered_set_sha256"] == member_set_sha256(obs["uncovered_slots"])


def test_uncovered_set_matches_manifest_on_pool() -> None:
    """对账主闸（旧 `test_known_gap_inventory_is_exact` 的观察层化）：

    在 manifest 钉住的批上重算 卡侧 − 世界 − 别名，必须逐项等于 manifest。
    双向报警：新增缺项红；缺项已消失而 manifest 没重建也红。
    """
    m = _manifest()
    uncovered = card_side_slots() - _world_side_slots(m) - alias_keys()
    recorded = set(m["observation"]["uncovered_slots"])
    assert uncovered == recorded, (
        "实测未覆盖集与 manifest 不符——\n"
        f"  新增（manifest 里没有）：{sorted(uncovered - recorded)}\n"
        f"  已消失（该走复核重建流程）：{sorted(recorded - uncovered)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "目标态：未覆盖集清零。当前 manifest（池 v2 满血批）记 **12 项**"
        "（甲4 补别名 / 乙1 禁简化 / 丙7 世界侧真无对应 / 丁0 锚批陈旧）。"
        "沿革：旧锚池 baseline_batch_final_seed301 记 19/20 项；换池后 8 槽"
        "因世界侧真产出而离开未覆盖集（逐槽裁定与 50/50 栋发射证据见 manifest "
        "的 `departed_from_uncovered`），丁组随之清空。"
        "全清后本条转 xpass，届时删 xfail 标记并重建 manifest。"
    ),
)
def test_card_slots_covered_by_world_or_alias() -> None:
    """目标态：卡侧槽名集合 ⊆ 世界槽名 ∪ 别名键。"""
    m = _manifest()
    uncovered = card_side_slots() - _world_side_slots(m) - alias_keys()
    assert not uncovered, (
        f"{len(uncovered)} 个卡侧槽名无处可落（这些槽的义务结构上永远不闭合）：\n"
        + "\n".join(f"  {s}" for s in sorted(uncovered))
    )


def test_alpha_world_targets_exist_in_pool() -> None:
    """甲组"真缺一行别名"必须有据：manifest 所记世界侧现名在该池真实存在。"""
    m = _manifest()
    group = m["observation"]["groups"]["alpha_alias_missing"]
    targets = group["world_side_targets"]
    assert set(targets) == set(group["members"])
    world = _world_side_slots(m)
    missing = {c: w for c, w in targets.items() if w not in world}
    assert not missing, f"甲组「世界侧现名」在批里不存在，分类判错了：{missing}"


def test_delta_group_is_empty_and_says_why() -> None:
    """丁组（锚批陈旧）在池 v2 上**是空集**，且 manifest 必须说清这是兑现不是空白。

    案源沿革：旧锚池里丁组唯一成员是 `procedure.investigation.detailed.intended`，
    旧 manifest 写死过新池预期「该槽应从未覆盖集消失，丁组随之清空」。
    池 v2 重建后它确已离组 ⇒ 丁组空。

    🔴 空集必须带解释：只留一个 `[]`，下一个读者分不清「已兑现清空」与
    「这一组还没人填」——后者会让「锚批陈旧」这个分类静默失效，
    而那正是 GAP_ANCHOR_BATCH_STALE 立案要防的那句错话。
    """
    m = _manifest()
    group = m["observation"]["groups"]["delta_anchor_batch_stale"]
    assert group["members"] == [], f"丁组在池 v2 上应为空集：{group['members']}"
    assert group["member_count"] == 0
    expectation = group["new_pool_expectation"]
    assert "已兑现" in expectation, "丁组空集必须写明是「预期已兑现」而非「未填」"
    assert "procedure.investigation.detailed.intended" in expectation, (
        "必须点名是哪个槽离的组，否则沿革断了"
    )


def test_departed_slots_are_really_supplied_by_the_world() -> None:
    """离组 8 槽必须**世界侧真产出**，不是被别名表盖掉的。

    🔴 这条是「离组」这件事的唯一实质证据。`uncovered = 卡侧 − 世界 − 别名`，
    所以往别名表补一行同样能让槽离开未覆盖集——那是把缺口盖住，不是补上供给。
    故这里逐槽复算：①在世界槽集合里；②在多少栋上真的发射（>0）。
    """
    m = _manifest()
    departed = m["observation"]["departed_from_uncovered"]
    assert departed["member_count"] == 8, (
        f"离组槽数与裁定表不符：{departed['member_count']}"
    )
    world = _world_side_slots(m)
    aliases = alias_keys()
    per_slot_buildings: dict[str, set[str]] = {s: set() for s in departed["slots"]}
    for p in _packs(m):
        for f in json.loads(p.read_text(encoding="utf-8")).get("facts") or []:
            slot = f.get("slot_id")
            if slot in per_slot_buildings:
                per_slot_buildings[slot].add(p.parents[2].name)
    for slot, record in departed["slots"].items():
        assert slot in world, f"{slot} 被记为已离组，却不在世界槽集合里"
        assert record["in_world_slot_set"] is True
        assert slot not in aliases, (
            f"{slot} 同时出现在别名键里——离组理由可能是别名盖住，须重判"
        )
        assert record["adjudication"], f"{slot} 缺逐项裁定"
        assert len(per_slot_buildings[slot]) == record[
            "observed_buildings_with_slot"
        ], f"{slot} 发射栋数与 manifest 不符"
        assert record["observed_buildings_with_slot"] > 0, (
            f"{slot} 记为世界侧已产出，实测 0 栋发射"
        )


def test_departed_slots_are_disjoint_from_current_groups() -> None:
    """离组表与甲乙丙丁四组不得有交集——同一个槽不能既在组里又已离组。"""
    m = _manifest()
    groups = m["observation"]["groups"]
    still_classified = {
        member for key in GROUP_KEYS for member in groups[key]["members"]
    }
    departed = set(m["observation"]["departed_from_uncovered"]["slots"])
    assert not (still_classified & departed), (
        f"这些槽既在分类组里、又被记为已离组：{sorted(still_classified & departed)}"
    )
    assert not (departed & set(m["observation"]["uncovered_slots"])), (
        "已离组的槽仍出现在未覆盖集里"
    )


def test_world_inputs_nonempty() -> None:
    """观察输入自检：世界侧真读到了东西——否则"对账通过"是空集假绿。

    （卡侧/别名的非空自检在结构层 `test_gap_inventory_structural.py`。）
    """
    m = _manifest()
    world = _world_side_slots(m)
    assert len(world) >= 100, f"世界侧只读到 {len(world)} 个槽，批产物多半没读全"
    assert m["observation"]["world_side_slot_count"] == len(world)


def test_misconnection_alias_reaches_fact_index_consumer() -> None:
    """生产者→消费者端到端：JSON 别名经 `slot_aliases_from_policy` 进 `FactIndex`
    后，卡侧名必须命中世界侧全部错接事实；事实条数对照 manifest（不再硬编码）。

    只查 JSON 有行 + 世界有目标槽 ≠ 消费者真用得上。本条走：
    磁盘 mapping → `slot_aliases_from_policy` → `FactIndex.canonical_slot` →
    `slot_index` 查找。无别名对照必须 miss。
    """
    from evo_agent_baseline.closure.fact_binding import FactIndex
    from evo_agent_baseline.contracts import FactPack
    from evo_agent_baseline.slot_alias_policy import slot_aliases_from_policy

    m = _manifest()
    bridge = m["observation"]["alias_bridge_observations"][ALIAS_BRIDGE_CARD_SLOT]
    assert bridge["world_slot"] == ALIAS_BRIDGE_WORLD_SLOT
    expected_count = bridge["fact_count"]
    assert expected_count > 0, "manifest 桥观察值为 0——池里根本没有错接事实？"

    mapping_doc = json.loads(
        (CARD_PACK / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    # 与闭包验证器同一入口：retrieval_policy 包裹 projection_runtime_mapping_v1
    aliases = slot_aliases_from_policy({"projection_runtime_mapping_v1": mapping_doc})
    assert aliases.get(ALIAS_BRIDGE_CARD_SLOT) == ALIAS_BRIDGE_WORLD_SLOT

    hit_with_alias = 0
    hit_without_alias = 0
    world_raw = 0
    for path in _packs(m):
        fact_pack = FactPack.model_validate_json(path.read_text(encoding="utf-8"))
        world_raw += sum(
            1 for f in fact_pack.facts if f.slot_id == ALIAS_BRIDGE_WORLD_SLOT
        )
        indexed = FactIndex(fact_pack, slot_aliases=aliases)
        canon = indexed.canonical_slot(ALIAS_BRIDGE_CARD_SLOT)
        assert canon == ALIAS_BRIDGE_WORLD_SLOT
        hit_with_alias += len(indexed.slot_index.get(canon, []))

        bare = FactIndex(fact_pack, slot_aliases={})
        assert bare.canonical_slot(ALIAS_BRIDGE_CARD_SLOT) == ALIAS_BRIDGE_CARD_SLOT
        hit_without_alias += len(bare.slot_index.get(ALIAS_BRIDGE_CARD_SLOT, []))
        # 世界侧裸名在无别名时仍按自身入索引
        assert len(bare.slot_index.get(ALIAS_BRIDGE_WORLD_SLOT, [])) == sum(
            1 for f in fact_pack.facts if f.slot_id == ALIAS_BRIDGE_WORLD_SLOT
        )

    assert world_raw == expected_count, (
        f"世界侧错接事实数与 manifest 不符：{world_raw} != {expected_count}"
    )
    assert hit_with_alias == expected_count, (
        f"经别名后卡侧名只命中 {hit_with_alias}/{expected_count}——"
        "别名未进入 FactIndex 消费路径"
    )
    assert hit_without_alias == 0, (
        "无别名时卡侧名不该命中；若命中说明世界已改用卡侧名，本闸前提变了"
    )
