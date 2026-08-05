"""DEBT 双向同步闸：跟踪表 §6 ↔ 技术与研究债.md 不许漂移。

**为什么要有这道闸**：项目明文纪律是「跟踪表 §6 DEBT 总览 ↔ 技术与研究债.md
DEBT-XXX 章节双向同步」，但它此前**只是一句话、没有任何机制**。
2026-07-27 实测：DEBT-075 有债文档章节、跟踪表无行——**在无人察觉的情况下漏了一天**，
而当天我还实现了它、仍没发现表里没它。同一条纪律当天又被我漏两次
（诊断只留在会话待办表、补完债文档忘了跟踪表）。

⇒ **靠纪律的东西会漏，靠结构的才守得住。** 这正是当天十二处修复的共同教训：
好的修法都是把纪律变成结构（`ObligationKind` 完全划分 + import 期断言、
原因码双向集合断言、静态扫描禁硬编码、真值判据固化成不变量）——它们不需要谁记得。

**这道闸只管「有没有」，不管「内容对不对」**：
- 跟踪表侧认表格行 `| 状态 | DEBT-0NN | ... |`
- 债文档侧认章节标题 `## DEBT-0NN｜...`
两侧编号集合必须完全相等。内容是否 stale 仍需人工复核（诚实边界）。
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TRACKING = _ROOT / "团队文档" / "我的笔记" / "项目跟踪表.md"
_DEBT = _ROOT / "团队文档" / "我的笔记" / "技术与研究债.md"

# 跟踪表 §6 的表格行：| 状态 | DEBT-0NN | 简述 | 备注 |
_ROW = re.compile(r"\|\s*DEBT-(\d{3})\s*\|")
# 债文档的章节标题：## DEBT-0NN｜标题（全角或半角竖线都收）
_SECTION = re.compile(r"^##\s*DEBT-(\d{3})[｜|]", re.M)


def _ids(path: pathlib.Path, pattern: re.Pattern[str]) -> set[str]:
    assert path.is_file(), f"找不到 {path}——文件被移动或改名了？"
    return set(pattern.findall(path.read_text(encoding="utf-8")))


def test_debt_ids_are_synced_both_ways() -> None:
    """两侧 DEBT 编号集合必须完全相等（双向同步纪律的机器化）。"""
    tracked = _ids(_TRACKING, _ROW)
    documented = _ids(_DEBT, _SECTION)

    only_tracked = sorted(tracked - documented)
    only_documented = sorted(documented - tracked)

    assert not only_tracked, (
        f"这些 DEBT 在跟踪表有行、债文档无章节：{['DEBT-' + x for x in only_tracked]}；"
        "请去 技术与研究债.md 补 `## DEBT-0NN｜...` 章节"
    )
    assert not only_documented, (
        f"这些 DEBT 在债文档有章节、跟踪表无行：{['DEBT-' + x for x in only_documented]}；"
        "请去 项目跟踪表.md §6 补一行（2026-07-27 就是这么抓到 DEBT-075 漏行的）"
    )


def test_both_sources_are_non_trivial() -> None:
    """防空闸：任一侧解析出 0 条即视为正则失效或文件结构变了。

    没有这条，上面那条在「两侧都解析成空集」时会假绿——
    本项目已多次栽在「测试全绿但根本没测到东西」上。
    """
    tracked = _ids(_TRACKING, _ROW)
    documented = _ids(_DEBT, _SECTION)
    assert len(tracked) >= 50, f"跟踪表只解析出 {len(tracked)} 条 DEBT，正则或表格式变了"
    assert len(documented) >= 50, f"债文档只解析出 {len(documented)} 条 DEBT，正则或标题格式变了"
