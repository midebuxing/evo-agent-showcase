"""真值「情形 N」标记全覆盖 + 跨楼一致性自检。

口径（2026-07-27 裁定）：
- 每一条 reason 必须显式带「情形 1/2/3」或「判据情形 1/2/3」；
- 同一 normative_item_id 在全部楼栋用同一情形号（硬冲突=0）；
- 情形 1 的定义＝恒适用 ⇒ 不得出现 applicable=false。
  若当前有反例，标 xfail 并列清单，不为让测试绿而改 verdict。

## 2026-08-05 补第三态处理（#25 真值落改案，决议 §三.2）

`applicable` 扩三态后（boolean ∪ `"unknown_pending"`），原
`test_circumstance_1_never_applicable_false:90` 用的 `is False`
**第三态一条都不触发** ⇒ 两线复核同点：第三态在三条一致性断言里**全部逃逸**。
故本文件加两条：
- `test_applicable_values_are_within_three_states`：取值域硬闸（顶掉「schema 不在
  主链、扩枚举时 schema 与实际取值静默分家」——本仓已记过的形状）；
- `test_circumstance_1_never_pending`：情形 1＝恒适用，同样不得挂起
  （只把 `is False` 抄一遍改成 `== "unknown_pending"` 是不够的，
  必须连「取值域」一起锁，否则打错字的第四态照样逃逸）。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

CIRC_RE = re.compile(r"(?:判据)?情形\s*([123])")

#: 真值 `applicable` 的三态取值域（与 schema `oneOf: [boolean, const]` 同源）。
PENDING = "unknown_pending"
LEGAL_APPLICABLE_VALUES = (True, False, PENDING)

_TRUTH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "evo_agent_baseline"
    / "eval"
    / "applicable_normative_item_truth_v1.jsonl"
)


def _load_rows():
    return [
        json.loads(line)
        for line in _TRUTH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _extract_circ(reason: str) -> str | None:
    m = CIRC_RE.search(reason or "")
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def truth_rows():
    rows = _load_rows()
    assert rows, "真值文件为空"
    return rows


def test_every_reason_has_circumstance_marker(truth_rows):
    """主验收：情形标记行覆盖率 100%。"""
    missing = [
        {
            "world_id": r["world_id"],
            "normative_item_id": r["normative_item_id"],
            "reason_head": (r.get("reason") or "")[:120],
        }
        for r in truth_rows
        if _extract_circ(r.get("reason") or "") is None
    ]
    assert missing == [], (
        f"有 {len(missing)} 条 reason 缺少「情形 N」标记，示例：{missing[:5]}"
    )


def test_same_item_same_circumstance_across_buildings(truth_rows):
    """同一 normative_item_id 全库情形号一致（硬冲突=0）。"""
    by_item: dict[str, set[str]] = defaultdict(set)
    for r in truth_rows:
        circ = _extract_circ(r.get("reason") or "")
        if circ is not None:
            by_item[r["normative_item_id"]].add(circ)
    hard = {nid: sorted(cs) for nid, cs in by_item.items() if len(cs) > 1}
    assert hard == {}, f"情形硬冲突 {len(hard)} 项：{hard}"


def test_circumstance_1_never_applicable_false(truth_rows):
    """情形 1＝恒适用，不得出现 applicable=false。

    若本断言失败：把反例列入冲突清单另开单修 verdict，不要为绿测改真值。
    """
    conflicts = [
        {
            "world_id": r["world_id"],
            "building_id": r["building_id"],
            "normative_item_id": r["normative_item_id"],
            "scope_type": r["scope_type"],
            "scope_id": r["scope_id"],
        }
        for r in truth_rows
        if _extract_circ(r.get("reason") or "") == "1" and r.get("applicable") is False
    ]
    # 当前期望：无反例。若未来出现，改为 pytest.xfail 并在 docstring 列清单。
    assert conflicts == [], (
        f"情形 1 却 applicable=false 共 {len(conflicts)} 条：{conflicts[:20]}"
    )


def test_applicable_values_are_within_three_states(truth_rows):
    """`applicable` 取值域硬闸（2026-08-05 扩三态后新增）。

    🔴 schema 校验**不在主链**（全仓无一处按 `.schema.json` 校验真值文件），
    所以扩枚举时「schema 说三态、文件里冒出第四态」是会静默发生的。
    这条断言就是那道缺失的闸——它比抄一遍 `is False` 重要得多。
    """
    illegal = [
        {
            "world_id": r["world_id"],
            "normative_item_id": r["normative_item_id"],
            "applicable": r.get("applicable"),
            "type": type(r.get("applicable")).__name__,
        }
        for r in truth_rows
        if not any(r.get("applicable") is v or r.get("applicable") == v
                   for v in LEGAL_APPLICABLE_VALUES)
    ]
    assert illegal == [], (
        f"`applicable` 取值越出三态共 {len(illegal)} 条（合法：True / False / "
        f"{PENDING!r}）：{illegal[:20]}"
    )


def test_circumstance_1_never_pending(truth_rows):
    """情形 1＝恒适用 ⇒ 不得挂起。

    第三态在原三条断言里全部逃逸（`is False` 不触发），本条补上。
    "恒适用"与"判不了"在语义上直接冲突：若真出现，是情形号标错，不是真值该挂起。
    """
    conflicts = [
        {
            "world_id": r["world_id"],
            "building_id": r["building_id"],
            "normative_item_id": r["normative_item_id"],
            "scope_type": r["scope_type"],
            "scope_id": r["scope_id"],
        }
        for r in truth_rows
        if _extract_circ(r.get("reason") or "") == "1"
        and r.get("applicable") == PENDING
    ]
    assert conflicts == [], (
        f"情形 1 却 applicable={PENDING} 共 {len(conflicts)} 条：{conflicts[:20]}"
    )
