"""identity 专用 rule_cards.json 读径（fail-closed 连贯设计 §3 / C.8 Decimal ingress）。

**为什么单独一条读径**：义务身份 v2 的 literal 阈值须走 Decimal ingress（`0.1` 原始词元
→ `Decimal("0.1")`，非二进制 float 噪声）。生产灌库/W2/闭包主链/v1 判定用的
`ingest/rulecard_loader.py` **不动**（避全局爆炸半径）；identity 派生（`blueprint_deriver`）
**另开**本读径，用 `parse_json_decimal`（`parse_float=Decimal`）读同一 `rule_cards.json`，
使数字词元落 int / Decimal（**绝不 float**）→ `_literal_value` 的「float 入口必炸」闸只在
真有 Python float 漏入时触发（本读径结构上不产 float）。

**读径产物**：`RuleCardDTO`（`threshold_regimes` / `slot_role_map` / `trigger_conditions`
等为透传 dict，Decimal 数字原样保留——`contracts.RuleCardDTO` 的这些字段是 `List[dict]`
/ `dict`，pydantic 不强转其内部数字，实测 Decimal 保真）。

blind 红线（A.9）：本模块**禁 import** `eval.*` / `TruthBundle` / `threshold_evaluations`
/ `workflow_engine`；只 import 中立 `canonical_profile`（parse_json_decimal）+ 同包契约。
不 import `ingest/rulecard_loader.py`（避把生产读径耦合进 identity 读径）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from canonical_profile import parse_json_decimal

from evo_agent_baseline.contracts import RuleCardDTO


def parse_cards_json_decimal(text: str) -> List[Dict[str, Any]]:
    """`rule_cards.json` 文本 → 卡 dict 列表（数字词元用 Decimal，绝不 float，C.8）。

    外层结构 `{bundle_id, cards}`；本函数只解析并返回 `cards`（不改结构、不做业务校验）。
    非有限数字（NaN/Infinity）由 `parse_json_decimal` 直接 hard-fail（C.8）。
    """
    data = parse_json_decimal(text)
    if not isinstance(data, dict) or "cards" not in data:
        raise ValueError("rule_cards.json 外层结构须含 'cards'")
    cards = data["cards"]
    if not isinstance(cards, list):
        raise ValueError("rule_cards.json 'cards' 须为列表")
    return cards


def load_identity_cards_from_text(text: str) -> List[RuleCardDTO]:
    """从 `rule_cards.json` **文本**构造 identity 派生用 `RuleCardDTO` 列表（Decimal 保真）。

    `neighbor_families` 归一为空列表（loader 端 `as_str_list` 归一；identity 派生不消费
    neighbor_families，置空避免 dict 元素触发 RuleCardDTO 校验）。数字词元保持 int/Decimal。
    """
    cards = parse_cards_json_decimal(text)
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in cards]


def load_identity_cards(path: Path) -> List[RuleCardDTO]:
    """从 `rule_cards.json` 路径读并构造 identity 派生用 `RuleCardDTO` 列表（Decimal 保真）。"""
    return load_identity_cards_from_text(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "parse_cards_json_decimal",
    "load_identity_cards",
    "load_identity_cards_from_text",
]
