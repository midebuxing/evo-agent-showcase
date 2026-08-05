"""别名归一统一入口（2026-07-27，别名归一三咬后的收口）。

卡侧槽名与世界侧槽名存在命名分叉（如卡侧 `repair.prescribed.started` vs
世界侧 `procedure.repair.prescribed.started`），权威对照在卡包
`projection_runtime_mapping_v1.json` 的 `slot_aliases` / `measure_aliases` 段。
本模块是该对照的**唯一归一入口**：

- 只依赖 `contracts`（实际只吃 dict / 属性对象），不 import closure / retrieval /
  ingest，故闭包、检索、脚本三方顶层 import 均无环（分层单向红线不破）。
- **两个视图**（缺一不可）：
  1. 正向单值 ``normalize_alias_map``：卡侧名 → 世界侧名
     （即 `fact_binding.FactIndex.canonical_slot` 的语义）；
  2. 反向多值展开 ``reverse_alias_index``：世界侧名 → 候选卡侧名集合
     （多张飞侧卡可共用同一世界槽，单值映射反过来不够用——检索侧病灶必需）。

⚠️ 与 `canonical_profile` 的身份哈希归一是**两种不同的 "canonical"**，勿混放。
⚠️ 本模块只管"已登记的别名怎么查"，**管不了"表里缺条目"**——那是数据问题，
   由对账测试（`agent_v1/tests/test_slot_alias_reconciliation.py`）盯。
"""

from __future__ import annotations

from typing import Any, Dict, Set

__all__ = [
    "normalize_alias_map",
    "slot_aliases_from_policy",
    "measure_aliases_from_policy",
    "reverse_alias_index",
    "card_slot_candidates",
]


def normalize_alias_map(aliases: Any) -> Dict[str, str]:
    """别名表归一为 {orig: canonical} 单值映射（正向视图）。

    自 `closure/validator.py` 搬入（DEBT-040 修复语义保持不变）：
    projection_runtime_mapping_v1 的值是**列表**（如
    `{"repair.prescribed.started": ["procedure.repair.prescribed.started"]}`），
    `str(v)` 会把列表搅成 "['procedure...']" 垃圾键、canonical 查找必 miss。
    这里 str 直取、list 取首个非空 str（v1 实际均为单元素列表；多元素取首并忽略其余，
    与 canonical_slot 单值语义一致）。
    """
    if not isinstance(aliases, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in aliases.items():
        canon: str | None = None
        if isinstance(v, str) and v:
            canon = v
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item:
                    canon = item
                    break
        if canon is not None:
            out[str(k)] = canon
    return out


def slot_aliases_from_policy(policy: Any) -> Dict[str, str]:
    """从 retrieval_policy（dict）取正向 slot 别名表（spec §6.4.2 canonical_slot 用）。

    合并语义（codex 评审硬化，自 validator 搬入、行为不变）：mapping 的
    slot_aliases 为基底，policy 顶层 `slot_aliases` 按键覆盖——不再"顶层非空即
    整表遮蔽 mapping"（那会让新映射静默失效）。
    """
    if not isinstance(policy, dict):
        return {}
    mapping = policy.get("projection_runtime_mapping_v1") or {}
    merged: Dict[str, Any] = {}
    if isinstance(mapping.get("slot_aliases"), dict):
        merged.update(mapping["slot_aliases"])
    top_level = policy.get("slot_aliases")
    if isinstance(top_level, dict):
        merged.update(top_level)
    return normalize_alias_map(merged)


def measure_aliases_from_policy(policy: Any) -> Dict[str, str]:
    """从 retrieval_policy（dict）取 projection_runtime_mapping_v1.measure_aliases。

    spec §6.3.5 fact binding 第 2 级用此别名表。policy 无此键时返回空。
    """
    if not isinstance(policy, dict):
        return {}
    mapping = policy.get("projection_runtime_mapping_v1") or {}
    return normalize_alias_map(mapping.get("measure_aliases") or {})


def reverse_alias_index(aliases: Dict[str, str]) -> Dict[str, Set[str]]:
    """反向多值展开视图：世界侧名 → 候选卡侧名集合。

    输入为正向单值表（`normalize_alias_map` 的产物，{卡侧名: 世界侧名}）。
    多张卡侧名可映射到同一世界侧名，故反视图必须是**集合**——单值反转会
    静默丢掉其它候选（这正是"单值映射反过来不够用"的病灶）。

    注：从归一后的单值表构建，故 raw 列表第 2 项起的被截断值不在此视图内
    （与正向视图同源，v1 实际均为单元素列表）。
    """
    out: Dict[str, Set[str]] = {}
    for card_side, world_side in aliases.items():
        out.setdefault(world_side, set()).add(card_side)
    return out


def card_slot_candidates(
    world_slot: str, reverse_index: Dict[str, Set[str]]
) -> Set[str]:
    """世界侧槽名 → 查询卡侧时应试的名字集合（含世界侧名自身）。

    卡侧既可能用别名键、也可能直接与世界侧同名，故候选 = 反向展开的卡侧名
    ∪ {世界侧名自身}。
    """
    return set(reverse_index.get(world_slot, set())) | {world_slot}


# ---------------------------------------------------------------------- #
# 🔴 2026-07-27 终审 P2 连带：本函数原在 `closure/fact_binding.py`，而检索侧
# (`fact_retriever.py:1499`) import 它 ⇒ `retrieval → closure` 反向依赖，
# 违反规格 v0.4:4739。它是**零内部依赖的纯函数**，故移入本中立模块。
# （该违规由 commit `882759c` 引入，非本轮新增，但同属一条红线故一并清。）
# ---------------------------------------------------------------------- #
def build_method_canonical_map(method_aliases: Any) -> Dict[str, str]:
    """method 别名 grouped raw ``{canonical: [alias, ...]}`` → 运行态展开表 ``{alias: canonical}``。

    DEBT-049 Phase3 U2（链②别名传输）。method 维度 canonical 落 **key 侧**（卡端 CoP
    词，如 ``cctv_survey``），与 slot/measure 别名（canonical 落 value 侧）**方向相反**——
    故 **不能复用** closure 的 ``_normalize_alias_map``（那取列表首项 + 方向 ``{key→首项}``：
    对 grouped raw 会把 canonical 映到某别名并丢弃其余别名）。本建表器做**反转 + 全展开**：

    - identity 自映射：``canonical → canonical``（保 ``canonical_method(x)=表.get(x,x)`` 下
      canonical 自身亦命中）；
    - 每 canonical 的每 alias：``alias → canonical``；
    - ``_`` 前缀键（``_note`` 等注释）跳过。

    例：``{"cctv_survey": ["drainage_cctv", "CCTV"]}`` →
    ``{"cctv_survey": "cctv_survey", "drainage_cctv": "cctv_survey", "CCTV": "cctv_survey"}``。
    四方法暗部署 ``{"air_test": [], ...}`` → 纯 identity ``{"air_test": "air_test", ...}``。
    """
    out: Dict[str, str] = {}
    if not isinstance(method_aliases, dict):
        return out
    for canonical, aliases in method_aliases.items():
        if not isinstance(canonical, str) or not canonical or canonical.startswith("_"):
            continue
        out[canonical] = canonical  # identity 自映射
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias:
                    out[alias] = canonical
    return out

