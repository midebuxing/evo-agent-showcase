"""worldgen 稳定键子随机流：域串登记表 ＋ 唯一构造入口（波次二 #22「rng 隔离 1a」）。

为什么要有这个模块
------------------
世界生成里多处「逐片段 / 逐槽」的抽样过去共用一条主随机流，于是：

- 某栋楼多一个片段 ⇒ 其后所有片段的量测全部移位（列表变长污染）；
- 改任何一张注册表的任何字段 ⇒ 整批 sidecar 重掷（种子曾挂在 `deterministic_key` 上）。

1a 全序把这些消费点各自换成**稳定键派生的子流**：种子只由「这次抽的是什么」决定
（域串 ＋ 世界 id ＋ 片段 id / 槽 id / 组合），不由「批里有多少东西、按什么顺序排」决定。

三条硬约束（都被本模块的构造入口结构化）
--------------------------------------
1. **种子必须是 `str`，不能是 `hash(str)`**：`hash()` 随 `PYTHONHASHSEED` 变，
   跨进程重放不稳。`random.Random(str)` 走内部 sha512，跨进程稳定。
   （同仓既有写法 `generator.py` 的 ctcov 子 rng 即此形；
   `generator_sampling._building_chain_seed_rng` 是 SHA-256 变体，同一原则。）
2. **域串必须互异**：两个不同阶段若共用域串，就退化成「所有片段共用一条流」——
   这是最阴的失败形态（键写错了但测试全绿）。故域串集中登记在本模块，
   导入时即做唯一性自检，撞名直接 `AssertionError`。
3. **键里不许出现批规模 / 序号**：`fragment_index` / 批内栋序 / `requested_count`
   一律不进键，否则「稳定键」只是把耦合换了个地方。

⛔ 反面清单（写新子流时别踩）
- ⛔ `random.Random(hash(...))` —— 见约束 1。
- ⛔ 裸 `fragment_id` 不带 `world_id` —— 片段 id 跨池会重名，不同池共享同一条流。
- ⛔ `fragment_index` / `enumerate` 序号入键 —— 那正是要治的「列表变长污染」。
"""

from __future__ import annotations

import hashlib
import random
from typing import Tuple

# ---------------------------------------------------------------------------
# 域串登记表：一个消费点一条，互异
# ---------------------------------------------------------------------------

# ⚠️ 曾经有过一条 `SIDECAR_BATCH = "w2rng.sidecar.batch.v1"`（1a-0 解绑时的批级 sidecar 流）。
#    1a-i′ 把 sidecar 四个消费点全部槽级化之后，**批级流不存在了**，故该域串一并删除——
#    留着它等于给「再造一条批级流」留个现成入口，而那正是 1a 全序要拆掉的东西。
#    1a-0 那一步的效应（惰性注册表变异对 sidecar 的影响 33.2% → 0）已在
#    `实施记录_rng隔离1a_20260805.md` §一 单独量过并存证。

# 1a-i：`generate_world_bundle` 的四个后置逐片段阶段
COVERAGE_RELATIONS = "w2rng.coverage_relations.v1"
COVERAGE_SAMPLING = "w2rng.coverage_sampling.v1"
TECHNICAL_VALIDATION = "w2rng.technical_validation.v1"
STRUCTURAL_ASSESSMENT = "w2rng.structural_assessment.v1"

# 1a-i'：sidecar 四个消费点（槽级；轴积点另加 combo 维）
SIDECAR_NUMERIC = "w2rng.sidecar.numeric.v1"
SIDECAR_BOOL_BUILDING = "w2rng.sidecar.bool.building.v1"
SIDECAR_BOOL_FRAGMENT = "w2rng.sidecar.bool.fragment.v1"
SIDECAR_AXIS_COMBO = "w2rng.sidecar.axis.v1"
# 期限锚楼级 duration 发射（期限锚供给案 2026-08-05）：独立追加步骤，槽级子流。
# 🔴 必须与 `SIDECAR_NUMERIC` **分开**：那条流按 (world, fragment, slot) 派生，
#    本步没有 fragment 维，共用域串会让键退化成 (world, slot) 与逐片段键混在同一
#    命名空间里——虽然实际不会撞（槽名互异），但那是靠"恰好不撞"，不是靠结构。
SIDECAR_DEADLINE_ANCHOR = "w2rng.sidecar.deadline_anchor.v1"

# 1a-ii：片段模板选择（键控排序，非 shuffle）
FRAGMENT_TEMPLATE_SELECT = "w2rng.fragment_template_select.v1"

ALL_DOMAINS: Tuple[str, ...] = (
    COVERAGE_RELATIONS,
    COVERAGE_SAMPLING,
    TECHNICAL_VALIDATION,
    STRUCTURAL_ASSESSMENT,
    SIDECAR_NUMERIC,
    SIDECAR_BOOL_BUILDING,
    SIDECAR_BOOL_FRAGMENT,
    SIDECAR_AXIS_COMBO,
    SIDECAR_DEADLINE_ANCHOR,
    FRAGMENT_TEMPLATE_SELECT,
)

# 约束 2 的结构化保证：导入即自检，撞名当场炸，不留给运行期静默共流。
assert len(set(ALL_DOMAINS)) == len(ALL_DOMAINS), (
    "worldgen rng 域串重复——两个消费点共用域串会让它们共享同一条随机流："
    f"{[d for d in ALL_DOMAINS if ALL_DOMAINS.count(d) > 1]}"
)


def stable_sort_key(domain: str, *parts: str) -> bytes:
    """按稳定键造一个**排序键**（不是随机流）。

    用途：需要「打乱但可复现」的地方，用「按稳定键排序后取前 k」代替 `rng.shuffle`。
    与 `sub_rng` 相比它更强：完全不消费任何随机流，且**列表变长时既有元素的相对序不变**
    （追加一个元素只是在这个序里插一个位置）。

    ⚠️ 诚实边界：这是「插入稳定」不是「插入无影响」——候选池变大而取的个数 k 不变，
    新元素的键若排进前 k 就会挤掉一个既有的。结构上不可能做到零位移。

    用 SHA-256 而非 `hash()`：同 `sub_rng` 的约束 1。
    """
    if domain not in ALL_DOMAINS:
        raise ValueError(
            f"未登记的 rng 域串 {domain!r}；新消费点必须先在 rng_domains.ALL_DOMAINS 登记"
        )
    for part in parts:
        if not isinstance(part, str):
            raise ValueError(
                f"稳定排序键的每一段都必须是 str，收到 {type(part).__name__}={part!r}"
            )
    return hashlib.sha256("|".join((domain, *parts)).encode("utf-8")).digest()


def sub_rng(domain: str, *parts: str) -> random.Random:
    """按稳定键造一条子随机流。

    键 = ``domain|part1|part2|...``，全部为 `str`；种子直接喂字符串
    （不做 `hash()`，见模块 docstring 约束 1）。

    Args:
        domain: 本模块登记的域串之一。
        *parts: 作用域标识（如 world_id / fragment_id / slot_id / 规范化 combo）。
            **不许**传批规模、序号、批内位置。

    Raises:
        ValueError: domain 未登记，或 parts 里出现非 str（防「不小心把 index 传进来」）。
    """
    if domain not in ALL_DOMAINS:
        raise ValueError(
            f"未登记的 rng 域串 {domain!r}；新消费点必须先在 rng_domains.ALL_DOMAINS 登记"
        )
    for part in parts:
        if not isinstance(part, str):
            raise ValueError(
                f"子 rng 键的每一段都必须是 str，收到 {type(part).__name__}={part!r}"
                "——序号/索引入键会把「列表变长污染」换个地方复发"
            )
    return random.Random("|".join((domain, *parts)))
