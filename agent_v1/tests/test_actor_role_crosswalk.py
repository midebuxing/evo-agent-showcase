"""角色对照表：与**真实卡包**对齐 ＋ 断言有牙齿。

规格 §3.5 的验收判据之一是「**变异测试**：删掉对照表一项 ⇒ 加载必须**拒绝**，
不是警告」。本文件锁的就是这条，外加一条最重要的：
**对照表必须覆盖真实卡包里出现过的全部取值**——不是覆盖我以为的那些。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from workflow_engine.worldgen.actor_role_crosswalk import (
    CARD_TO_WORLD,
    FORBIDDEN_MERGED_TERMS,
    WORLD_ROLE_VOCABULARY,
    ActorRoleCrosswalkError,
    to_world_role,
    validate_crosswalk,
)

_CARDS = (pathlib.Path(__file__).resolve().parents[1] / "regulations"
          / "rulecard_v2" / "mbis_cop_2023" / "rule_cards.json")


def _card_role_values() -> list[str]:
    """递归扫真实卡包的 `qualifiers.actor_role_key`。

    ⚠️ 必须**递归**：这个键出现在多层嵌套里（slot_role_map / 触发器 /
    证据要求…），只看顶层会漏。
    """
    doc = json.loads(_CARDS.read_text(encoding="utf-8"))
    cards = doc["cards"] if isinstance(doc, dict) and "cards" in doc else doc
    out: list[str] = []

    def walk(o) -> None:
        if isinstance(o, dict):
            q = o.get("qualifiers")
            if isinstance(q, dict) and q.get("actor_role_key"):
                out.append(str(q["actor_role_key"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(cards)
    return out


def test_crosswalk_covers_every_value_in_the_real_card_pack():
    """对着**真实卡包**跑，不是对着我写死的清单跑。

    实测卡侧 **9** 个取值（2026-08-05 #29 落地后现算）：
    ba 18 / ri_rep_lvl1 10 / ri_rep_lvl2 10 / owner 5 / **bd 4** /
    person_for_whom_prescribed_repair_is_carried_out 4 / rc 2 / ri 2 /
    occupant_or_resident 1。

    沿革：#29 之前是 8 个取值、`ba 21`、无 `bd`。檢驗日誌五条平行款的收件人
    中文正文逐字写「呈交**屋宇署**」（bd），卡侧误写 `ba`（建築事務監督）；
    #29 把其中三条改值、第四条（§3.3.2(A)(c)）补键 ⇒ `ba 21→18`、`bd 0→4`。
    第五卡（§3.4.2(A)(b)）只改 `recipients.recipient_key`、不带限定符轴，
    **对本分布贡献 0**。
    """
    values = _card_role_values()
    assert values, "卡包里一个 actor_role_key 都没扫到？先查扫法，别让断言空过"
    validate_crosswalk(values)          # 不抛即通过
    assert set(values) <= set(CARD_TO_WORLD)


def test_missing_mapping_is_rejected_not_warned(monkeypatch):
    """变异：对照表少一项 ⇒ **必须抛**。

    降级为警告的后果：漏配的取值在运行时静默取不到事实，
    表现成「世界没供给」而不是「对照表漏了」，排障方向完全指错。
    """
    import workflow_engine.worldgen.actor_role_crosswalk as m
    shrunk = dict(CARD_TO_WORLD)
    shrunk.pop("rc")
    monkeypatch.setattr(m, "CARD_TO_WORLD", shrunk)
    with pytest.raises(ActorRoleCrosswalkError):
        m.validate_crosswalk(_card_role_values())


def test_target_outside_world_vocabulary_is_rejected(monkeypatch):
    """反向变异：对照指向世界词表里没有的取值 ⇒ 必须抛。"""
    import workflow_engine.worldgen.actor_role_crosswalk as m
    bad = dict(CARD_TO_WORLD)
    bad["rc"] = "registered_contractor_but_not_registered_anywhere"
    monkeypatch.setattr(m, "CARD_TO_WORLD", bad)
    with pytest.raises(ActorRoleCrosswalkError):
        m.validate_crosswalk(_card_role_values())


def test_merged_term_is_rejected(monkeypatch):
    """已裁定须拆的合并词若被指回来 ⇒ 必须抛。

    §2.1.3(r) 只点名「該名由他人代為進行訂明修葺的人」，没有「業主」；
    §3.6.3(b)「提醒業主及住戶」证明 owner 与 occupant 也是两方。
    """
    import workflow_engine.worldgen.actor_role_crosswalk as m
    bad = dict(CARD_TO_WORLD)
    bad["owner"] = next(iter(FORBIDDEN_MERGED_TERMS))
    monkeypatch.setattr(m, "CARD_TO_WORLD", bad)
    monkeypatch.setattr(
        m, "WORLD_ROLE_VOCABULARY",
        WORLD_ROLE_VOCABULARY | FORBIDDEN_MERGED_TERMS)   # 先绕过上一道，专测这道
    with pytest.raises(ActorRoleCrosswalkError):
        m.validate_crosswalk(_card_role_values())


def test_to_world_role_never_falls_back_to_the_raw_value():
    """取不到就抛，**绝不回退成原值**——回退会让「对照漏了」变成
    「世界里多了个没登记的取值」，正是这套机制要防的静默漂移。"""
    with pytest.raises(ActorRoleCrosswalkError):
        to_world_role("some_role_nobody_registered")
    assert to_world_role("owner") == "owner"


def test_ri_and_its_representatives_stay_distinct():
    """`ri`（本人）与 `ri_rep_lvl*`（代表）不可合并。

    §2.1.3(a)「須**親自**進行樓宇檢驗……惟註冊檢驗人員仍須就其代表所認明的
    欠妥範圍負上個人責任」——守则刻意区分的责任边界，合并会抹掉它。
    """
    assert to_world_role("ri") != to_world_role("ri_rep_lvl1")
    assert to_world_role("ri_rep_lvl1") != to_world_role("ri_rep_lvl2")
    for v in ("ri", "ri_rep_lvl1", "ri_rep_lvl2"):
        assert to_world_role(v) in WORLD_ROLE_VOCABULARY
