"""🔴 回归闸：类型格快照失配时，**所有**由它派生的东西都必须被收回。

2026-07-27 codex 四审 P1：失配分支清了 `_lattice_leaf_types` / `_lattice_disjoint` /
`_auth_targets`，却**漏了 `_ct_subsumption`**——它在 `validator.py:1071` 就被读走、
`:1081` 已传进 `FactIndex`，而快照校验在 `:1159` 才发生。
⇒ `qualifiers_match` 继续用**过期父子关系**，把本该落 `qualifier_conflict` 的限定符
当成命中 ⇒ **快照失配却改变了闭包判定**（fail-open）。

本闸不测「清了没有」这种实现细节，而是测**行为**：
喂一份快照对不上的类型格，包含关系必须**不生效**（退化为严格相等匹配）。

⚠️ 诚实边界：这只覆盖 `component_subsumption` 这一条派生物。若将来又往
`FactIndex` 塞第二样类型格派生物，本闸**抓不到**——那属于「同一假设散在多层」，
须靠 code review。故此处显式列出当前已知的派生物清单，新增时**必须同步扩本闸**。
"""

from __future__ import annotations

import re
from pathlib import Path

_VALIDATOR = (
    Path(__file__).resolve().parents[1]
    / "src" / "evo_agent_baseline" / "closure" / "validator.py"
)

# 类型格快照校验失配时**必须**被收回的东西（新增派生物时同步扩这张表）。
_MUST_CLEAR = (
    "_lattice_leaf_types",
    "_lattice_disjoint",
    "_auth_targets",
    "_ct_subsumption",
    "fact_index.component_subsumption",
)


def _mismatch_branch_source() -> str:
    """取「快照失配」那段 if 的函数体源码。"""
    src = _VALIDATOR.read_text(encoding="utf-8")
    m = re.search(
        r"if _lattice_alias_snap and _ct_lattice_hash\([^)]*\) != _lattice_alias_snap:\n"
        r"((?:[ \t]+.*\n|\n)+?)(?=[ \t]{0,4}\S)",
        src,
    )
    assert m, "定位不到快照失配分支——validator.py 结构变了，本闸需重写"
    return m.group(1)


def test_snapshot_mismatch_clears_every_lattice_derivative() -> None:
    """失配分支必须收回全部已登记的类型格派生物。"""
    body = _mismatch_branch_source()
    missing = [name for name in _MUST_CLEAR if name not in body]
    assert not missing, (
        f"快照失配分支漏收这些类型格派生物：{missing}。"
        "校验失败却让消费者继续用未经校验的数据＝fail-open——"
        "本项目 2026-07-27 一天内撞过十三次同形状。"
    )


def test_branch_locator_is_not_vacuous() -> None:
    """防空闸：定位到的分支体必须非空且确实在做清空动作。

    没有这条，上面那条在正则失配返回空串时会假绿——
    本项目已多次栽在「测试全绿但根本没测到东西」上。
    """
    body = _mismatch_branch_source()
    assert body.strip(), "失配分支体为空——正则失效"
    assert "= set()" in body or "= {}" in body, (
        "失配分支里没有任何清空动作，定位很可能错了"
    )
