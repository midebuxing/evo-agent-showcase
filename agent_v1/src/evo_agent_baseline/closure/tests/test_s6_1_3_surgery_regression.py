# -*- coding: utf-8 -*-
"""s6_1_3 手术（2026-08-04）的两条回归锁。

术式＝sr03 `required` true→false（**不删条目**）。grok 手术审核建议的防回归：
sr03 是该卡唯一的 `repair` 域槽引用，`_card_is_fragment_scoped` 靠它锚片段作用域
——将来谁「清理」这条 required=false 的条目，卡会静默塌成楼级
（阶段一实测：义务 34→10＋新增 19 条歧义绑定）。
"""
from __future__ import annotations

import json
import pathlib

_PACK = (pathlib.Path(__file__).resolve().parents[4] / "regulations"
         / "rulecard_v2" / "mbis_cop_2023" / "rule_cards.json")
_CARD_ID = ("rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
            "s6_1_3_comply_bo_and_provide_supervision.c01")


def _card():
    doc = json.loads(_PACK.read_text(encoding="utf-8"))
    return next(c for c in doc["cards"] if c["rule_card_id"] == _CARD_ID)


def test_sr03_stays_present_but_not_required():
    """sr03 必须**在**（作用域锚）且 required=false（关「存在即满足」求值）。

    删掉它＝作用域塌陷；改回 required=true＝34 条假 satisfied 复活。
    两个方向都在这里拦。"""
    card = _card()
    sr03 = [sr for sr in card["slot_role_map"]
            if sr.get("slot_id") == "repair.outcome.safe_until_next_cycle"]
    assert len(sr03) == 1, "sr03 被删——卡作用域会静默塌成楼级，去读手术记录"
    assert sr03[0].get("required") is False, \
        "sr03 required 被改回 true——34 条存在即满足假 satisfied 复活"


def test_card_remains_fragment_scoped_with_optional_sr03():
    """required=false 的槽引用仍参与作用域判定（本手术的语义前提）。"""
    from evo_agent_baseline.closure.blueprint_deriver import (
        _card_is_fragment_scoped,
    )
    from types import SimpleNamespace
    card = SimpleNamespace(slot_role_map=_card()["slot_role_map"])
    # slot_domain＝slot_id→semantic_domain 映射（源 rule_slice.semantic_slots）；
    # 这里只需 sr03 的槽落在片段域即可证「required=false 仍锚作用域」。
    slot_domain = {"repair.outcome.safe_until_next_cycle": "repair"}
    assert _card_is_fragment_scoped(card, slot_domain) is True
