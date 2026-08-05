"""卡侧 `actor_role_key` 取值 → 世界侧权威词表的**显式对照**，带导入期硬断言。

## 这是什么、为什么要它

决策门（2026-08-03，grok ＋ 其走量线两家族）裁 **C**：
**世界词表保持唯一权威，卡侧取值经显式对照映射进来，
且「卡里出现过的每个取值必须有像」——缺一个就拒绝加载，不是警告。**

### 为什么不是「直接把卡短词写进世界事实」（B）

因为两侧对同一现实做了**不同切分**，不是拼写差异：

- 世界侧**曾**登记**合并词** `owner_or_person_for_whom_prescribed_repair_is_carried_out`
  （`registry.py` 那处已于 2026-08-03 按裁定拆成 `person_for_whom_...`，
  合并词现只剩在下方 `FORBIDDEN_MERGED_TERMS` 里当报警器）；
- 卡侧是**拆开的两个值**：`owner` 与 `person_for_whom_prescribed_repair_is_carried_out`。

直接写卡短词，世界里就会同时存在合并态与拆分态两套表达，**而没有任何东西在对账**
——本项目已记在册的坑（ownership 登记 140 条 vs 实采 46 条，两表之间无人对账）。

### 合并词本身是错的（已对中文原文核实）

守则把这些角色**分别点名**：

- §3.6.3(b)「須立即通知建築事務監督，並提醒**業主及住戶**」
  ——同句并列，`owner` 与 `occupant_or_resident` 是两方；
- §2.1.3(r)「此等文件亦須於同日送交**該名由他人代為進行訂明修葺的人**」
  ——只点这一方，**没有「業主」**；世界那条登记的槽名也叫 `to_person`。

⇒ `owner_or_` 这个前缀**没有依据**，属世界侧登记与它**自己引的条文**不符。
（全仓 `actor_role_key` 登记只有 2 处，另一处 `to_ba → ba` 正确 ⇒ 1/2 错。）

### `ri` 与 `ri_rep_lvl*` 不可混

§2.1.3(a)「須**親自**進行樓宇檢驗……其代表可協助確認欠妥之處的範圍，
**惟註冊檢驗人員仍須就其代表所認明的欠妥範圍負上個人責任**」
——本人与代表是守则刻意区分的**责任边界**，合并会抹掉它。

## 边界

本模块**只做对照与断言**，不产事实、不改生成器。
生成器改动是**另一步**（会换池 seed），见
`团队文档/我的笔记/规格_reporting三根轴世界侧补产_v1_20260803.md`。

## 定位（2026-08-04 明确——审核门「接线或降级」二选一，选**降级**并给依据）

本模块是**构建/测试期护栏**，设计上没有运行时消费者，这不是欠账：
- 世界侧轴积采样**直接用世界权威词表**产事实（`ba`/`owner`/`rc`/…），
  卡侧引用值与世界值同词 ⇒ 运行时**不存在需要映射的时刻**；
- 本表的职责是把「卡侧出现过的每个取值 ⊆ 世界词表」这条断言**钉在测试里**
  （`test_actor_role_crosswalk.py` 对真实卡包跑）＋ 把已裁定须拆的合并词
  （`FORBIDDEN_MERGED_TERMS`）挡在登记外。
- 若将来卡侧引入与世界词表不同名的短词，届时再把 `to_world_role()` 接进绑定层
  ——那是新需求，不是本模块现在的缺口。
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List


class ActorRoleCrosswalkError(ValueError):
    """对照表与卡侧取值对不上——**拒绝加载**，不降级为警告。"""


# 世界侧权威词表（拆开合并词后的目标形态）。
# 🔴 `owner` 与 `person_for_whom_prescribed_repair_is_carried_out` 是**两个**取值：
# 合并词已按中文原文裁定为错，须拆（见模块 docstring）。
WORLD_ROLE_VOCABULARY: FrozenSet[str] = frozenset({
    # 执行方
    "ri",                 # 註冊檢驗人員**本人**
    "ri_rep_lvl1",        # 其代表（第一级）
    "ri_rep_lvl2",        # 其代表（第二级）
    # 相对方
    "ba",                 # 建築事務監督（Building Authority）
    # 🔴 `bd` 与 `ba` 是**两个不同的收件人实体，不是拼写变体**（#29，2026-08-05）：
    # 守则对「檢驗日誌」的呈交对象逐字写「呈交**屋宇署**」（§3.3.2(A)(c) / §3.4.2(A)(b) /
    # §3.5.2(A)(c) / §3.6.2(A)(d) / §3.7.1(d) 五条平行款逐字同文），
    # 而 §2.1.3 全族 / §7.2.2 等条款写的是「建築事務監督」。
    # ⇒ 加 `bd` 是**纠正错译**，`ba` 必须留在词表（大量条款收件人确为建築事務監督）。
    "bd",                 # 屋宇署（Buildings Department）
    "owner",              # 業主
    "person_for_whom_prescribed_repair_is_carried_out",   # 由他人代為進行訂明修葺的人
    "occupant_or_resident",   # 住戶
    "rc",                 # 註冊承建商
})

# 卡侧取值 → 世界侧取值。
# 当前**一一对应**（拆开合并词之后就不再需要多对一），
# 但保留这张表是因为：①两侧词表的演化速率不同；
# ②将来若某个卡侧值确实要映到别的世界值，改这里比改事实生成器安全。
CARD_TO_WORLD: Dict[str, str] = {
    "ba": "ba",
    "bd": "bd",
    "ri": "ri",
    "ri_rep_lvl1": "ri_rep_lvl1",
    "ri_rep_lvl2": "ri_rep_lvl2",
    "owner": "owner",
    "person_for_whom_prescribed_repair_is_carried_out":
        "person_for_whom_prescribed_repair_is_carried_out",
    "occupant_or_resident": "occupant_or_resident",
    "rc": "rc",
}

# 已知**必须拆**的历史合并词：出现即报错，不许静默沿用。
FORBIDDEN_MERGED_TERMS: FrozenSet[str] = frozenset({
    "owner_or_person_for_whom_prescribed_repair_is_carried_out",
})


def validate_crosswalk(card_role_values: List[str]) -> None:
    """断言：卡里出现过的**每一个** `actor_role_key` 取值都必须有像。

    🔴 **缺一个就抛**，不是警告——本项目既有教训「关键配置静默退化是一个 bug 族」：
    降级为警告时，漏配的取值会在运行时静默取不到事实，
    表现为「世界没供给」而非「对照表漏了」，**排障方向完全指错**。

    Args:
        card_role_values: 从 `rule_cards.json` 递归扫出的全部
            `qualifiers.actor_role_key` 取值（可含重复）。
    """
    values = sorted(set(str(v) for v in card_role_values if v))
    missing = [v for v in values if v not in CARD_TO_WORLD]
    if missing:
        raise ActorRoleCrosswalkError(
            f"卡侧 actor_role_key 取值在对照表里没有像：{missing}；"
            f"对照表现有键={sorted(CARD_TO_WORLD)}。"
            "补对照或补世界词表后再跑——不得跳过。"
        )
    bad_targets = sorted(
        {v for v in CARD_TO_WORLD.values() if v not in WORLD_ROLE_VOCABULARY})
    if bad_targets:
        raise ActorRoleCrosswalkError(
            f"对照表指向了不在世界词表里的取值：{bad_targets}")
    merged = sorted(FORBIDDEN_MERGED_TERMS & set(CARD_TO_WORLD.values()))
    if merged:
        raise ActorRoleCrosswalkError(
            f"对照表仍指向已裁定须拆的合并词：{merged}"
            "（§2.1.3(r) 只点名一方，`owner_or_` 前缀无依据）")


def to_world_role(card_value: str) -> str:
    """卡侧取值 → 世界侧取值。取不到就抛，**绝不回退成原值**。

    回退成原值会让「对照漏了」变成「世界里多了个没登记的取值」，
    正是本模块要防的那种静默漂移。
    """
    try:
        return CARD_TO_WORLD[str(card_value)]
    except KeyError:
        raise ActorRoleCrosswalkError(
            f"卡侧 actor_role_key={card_value!r} 无对照；"
            "先过 validate_crosswalk 再用") from None


__all__ = [
    "ActorRoleCrosswalkError",
    "WORLD_ROLE_VOCABULARY",
    "CARD_TO_WORLD",
    "FORBIDDEN_MERGED_TERMS",
    "validate_crosswalk",
    "to_world_role",
]
