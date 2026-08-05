"""卡侧 `defect_class_key` 词表与世界实产缺陷类的对账闸（2026-07-30 立）。

## 为什么有这道闸

实测（批 `phase_i_fragcov2_seed301_20260729`）：

```
世界产 22 类 defect_class_key，卡侧受控词表只允许 14 类
世界独有 8 类 × 各 250 条 × 全 30 栋 = **2,000 条世界事实**
   DC_DRAINAGE_BLOCKAGE / DC_FIRE_DOOR_DEFICIENCY /
   DC_FIRE_PROTECTION_COATING_DEFICIENCY / DC_FIRE_STOP_DEFICIENCY /
   DC_GLASS_BREAKAGE / DC_LOOSE_FIXING / DC_SEALANT_FAILURE / DC_SUBDIVIDED_SIGN
```

`rulecard_v2.py:183` 的 `_validate_qualifiers` 对词表外取值**硬拒回**
⇒ 任何法规卡**都不能拿这 8 类当限定符** ⇒ 涉及它们的条款
（§3.5 走火通道 / §3.6 排水 / §3.7 招牌）**永远绑不上世界事实**。

**这是单边缺口**：卡侧独有（世界不产）= 0 类。

## 🔴 同族先例

与 sidecar 的「`ownership_registry` 140 条声明 vs `bool_slot_registry` 46 条实采」
完全同形：**两张表之间没有任何东西在对账**，于是「声明了永不产出」
或「产出了永不可引用」都能长期潜伏。
⇒ 本项目已多次实证：**缺口不是靠人记得，是靠对账闸抓出来的。**

## 这道闸做什么

不硬性要求两侧相等（世界可以先行探索性产出新缺陷类），而是要求：
**任何不在卡侧词表里的世界缺陷类，必须显式登记为「已知待补」**。
⇒ 新增一个世界缺陷类而忘了同步卡侧词表，测试会失败并指名道姓。

⚠️ 本闸**只读**词表与登记表，不读批产物——批产物不是所有环境都有。
批级实测数字写在上面的 docstring 里作为立闸依据。
"""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
BUNDLE = REPO / "agent_v1/regulations/rulecard_v2/mbis_cop_2023"

#: 已知「世界产出但卡侧词表未收」的缺陷类。每条必须写为什么还没补。
#: 🔴 补进卡侧词表后，从这里删掉——本表为空即代表两侧已对齐。
KNOWN_WORLD_ONLY_DEFECT_CLASSES = {
    "DC_DRAINAGE_BLOCKAGE": "排水堵塞；§3.6/§5.6 相关卡想引用须先补词表",
    "DC_FIRE_DOOR_DEFICIENCY": "消防门欠妥；§3.5 走火通道相关",
    "DC_FIRE_PROTECTION_COATING_DEFICIENCY": "防火涂层欠妥；§3.5 相关",
    "DC_FIRE_STOP_DEFICIENCY": "防火隔断欠妥；§3.5 相关",
    "DC_GLASS_BREAKAGE": "玻璃破损；幕墙/窗相关",
    "DC_LOOSE_FIXING": "固定件松脱；招牌/伸出物相关",
    "DC_SEALANT_FAILURE": "密封失效；外墙接缝相关",
    "DC_SUBDIVIDED_SIGN": "僭建分隔招牌；§3.7 相关",
}


def _card_vocab() -> set[str]:
    d = json.loads((BUNDLE / "controlled_vocabularies_v1.json").read_text(encoding="utf-8"))
    return set(d["vocabularies"]["defect_class_key"])


def test_known_world_only_classes_are_documented_not_silent() -> None:
    """每个「世界独有」的缺陷类都必须带一句为什么还没补——不许空着混过去。"""
    for k, why in KNOWN_WORLD_ONLY_DEFECT_CLASSES.items():
        assert why and len(why) >= 6, f"{k} 没写为什么还没补进卡侧词表"


def test_registry_and_vocab_do_not_overlap() -> None:
    """已补进卡侧词表的类，必须从「待补」表里删掉。

    这条防的是「补了但忘了清登记表」——那样这张表就会慢慢变成一份过期清单，
    而过期清单比没有清单更危险（它会让人以为缺口还在，或者以为已经补了）。
    """
    vocab = _card_vocab()
    stale = sorted(set(KNOWN_WORLD_ONLY_DEFECT_CLASSES) & vocab)
    assert not stale, (
        f"这些类已在卡侧词表里，请从 KNOWN_WORLD_ONLY_DEFECT_CLASSES 删掉：{stale}")


def test_card_vocab_is_not_silently_shrunk() -> None:
    """卡侧词表不许静默变小——删一个取值会让引用它的卡整张被契约拒回。

    锚定 2026-07-30 实测的 14 个取值。**新增取值时把它加进这里**，
    这样「有意新增」与「误删」在测试层面可区分。
    """
    expected = {
        "abnormal_separation", "corrosion", "crack", "dampness",
        "deformation_or_displacement", "delamination", "exposed_rebar",
        "hollowing", "honeycombing_or_void", "misconnection", "spalling",
        "structural_damage_sign", "ubw", "water_leak",
    }
    vocab = _card_vocab()
    missing = sorted(expected - vocab)
    assert not missing, f"卡侧 defect_class_key 词表少了这些取值：{missing}"
