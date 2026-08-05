"""可行动四要素的第四个：「提供了会怎样」（2026-08-03 立）。

## 为什么有这道闸

一条对专业审查员真正可行动的项，至少要有四样：

| 要素 | 2026-08-03 前 |
|---|---|
| 哪栋楼 / 哪个部位 | ✅ 「涉及 5 处：`EXTERNAL-WALL-00-00`…」 |
| 哪条守则 | ✅ 「依据：守则 §3.3.2(J)(b)」 |
| 要提供什么 | ✅ 「提交现场量测记录，并附标注展示面积…」 |
| **提供了会怎样** | ❌ **全批零条** |

实测（批 `phase_i_fragcov2_seed301_20260729`，全 30 栋）：
`professional_input_required` **488 条**，四要素**全齐 278（57%）/ 缺一 210（43%）**，
而缺的那一个**永远是第四个**。后果：审查员看完知道要交什么，
**但不知道交了能换来什么**，于是这份报告对他不产生优先级——
四项待补摆在一起，他没有依据决定先做哪个。

## 第四要素怎么算（唯一诚实且可算的口径）

反向索引 `root_dependency_ids`：谁把这条义务列为根依赖。
批 I 实测 488 条待补项里 **229 条（47%）** 有下游在等，最多一条带 7 个。
⇒ 「补这一项，连带解开 N 条」既真实又正好是排优先级需要的信息。

## 🔴 措辞红线（本文件锁的核心）

只许写「**解除阻塞并重新求值**」，**绝不许写「补了就会判合规 / 就会满足」**。

解除本项阻塞**不蕴含**该义务随后能得出确定判定——它可能还有别的缺口。
对审查员承诺一个我们保证不了的结果，与本轮正在修的「假合格」
（拿「文件存在」证「内容载明」）**是同一种不诚实**，只是换了个位置。

`test_no_outcome_promise_in_wording` 逐条扫渲染结果，命中承诺性措辞即红。
"""
from __future__ import annotations

import json
import pathlib
import re
from types import SimpleNamespace

import pytest

from evo_agent_baseline.agent import report_writer as rw

REPO = pathlib.Path(__file__).resolve().parents[5]

# 承诺「结果」的措辞——一条都不许出现在行动项里。
_FORBIDDEN_PROMISE = re.compile(
    r"(就会|即可|将会|便会|从而)?(判为?合规|判定为?合规|变成合规|"
    r"满足该义务|义务即满足|判为?满足|变成 ?satisfied|closed)"
)


def _load_attribution_case():
    """找一份带 `professional_input_required` 的真实产物；找不到就跳过。"""
    for p in (REPO / "agent_v1/experiments").glob(
            "*/buildings/*/runs/*/closure_validation_result.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        mp = d.get("unknown_attribution_by_obligation_id") or {}
        if any(v.get("responsibility") == "professional_input_required"
               for v in mp.values() if isinstance(v, dict)):
            return d
    return None


def _render(doc):
    mp = doc.get("unknown_attribution_by_obligation_id") or {}
    objs = {k: SimpleNamespace(**v) for k, v in mp.items()}
    mr = doc.get("machine_readable_report") or {}
    idx = rw._index_unclosed_obligations(
        mr.get("open_items") or [], mr.get("blocked_items") or [])
    return rw._render_professional_action_items(
        objs, obligation_index=idx, building_id=str(mr.get("building_id") or ""))


@pytest.fixture(scope="module")
def rendered():
    doc = _load_attribution_case()
    if doc is None:
        pytest.skip("本环境没有带 professional_input_required 的批产物")
    return _render(doc), doc


def test_every_action_item_states_what_supplying_it_achieves(rendered):
    """每一项都必须有第四要素——「补录后：…」这一行，一项都不能漏。"""
    lines, _ = rendered
    titles = [ln for ln in lines if re.match(r"^\*\*\d+\. ", ln)]
    fourth = [ln for ln in lines if ln.startswith("- 补录后：")]
    assert titles, "夹具里没有行动项，本测无意义"
    assert len(fourth) == len(titles), (
        f"{len(titles)} 项行动，只有 {len(fourth)} 项写了「补录后」——有项漏了第四要素")


def test_downstream_count_matches_root_dependency_reverse_index(rendered):
    """「连带解开 N 条」必须等于反向索引实算值，不许是估计或常量。"""
    lines, doc = rendered
    mp = doc.get("unknown_attribution_by_obligation_id") or {}
    downstream = {}
    for v in mp.values():
        for root in (v.get("root_dependency_ids") or []):
            downstream[str(root)] = downstream.get(str(root), 0) + 1
    expected_total = sum(
        downstream.get(str(oid), 0) for oid, v in mp.items()
        if v.get("responsibility") == "professional_input_required")
    rendered_total = sum(
        int(m.group(1))
        for ln in lines
        for m in [re.search(r"连带解开 \*\*(\d+) 条\*\*", ln)] if m)
    assert rendered_total == expected_total, (
        f"渲染出的连带条数 {rendered_total} ≠ 反向索引实算 {expected_total}")


def test_no_outcome_promise_in_wording(rendered):
    """🔴 措辞红线：不许承诺补录后会得到确定判定。

    解除阻塞 ≠ 能判出结果。承诺一个保证不了的结果，
    与「拿文件存在证内容载明」是同一种不诚实。
    """
    lines, _ = rendered
    offenders = [ln for ln in lines if _FORBIDDEN_PROMISE.search(ln)]
    assert not offenders, f"行动项出现承诺性措辞：{offenders}"


def test_zero_downstream_falls_back_to_weaker_wording():
    """无下游时必须回落到弱表述，**不能**凭空写「连带解开 0 条」。

    构造两项：一项有下游、一项没有。
    """
    mp = {
        "OB-root": SimpleNamespace(
            responsibility="professional_input_required",
            professional_action="提交甲资料", root_dependency_ids=[]),
        "OB-lonely": SimpleNamespace(
            responsibility="professional_input_required",
            professional_action="提交乙资料", root_dependency_ids=[]),
        "OB-dep1": SimpleNamespace(
            responsibility="system_unresolved",
            professional_action=None, root_dependency_ids=["OB-root"]),
        "OB-dep2": SimpleNamespace(
            responsibility="system_unresolved",
            professional_action=None, root_dependency_ids=["OB-root"]),
    }
    lines = rw._render_professional_action_items(mp)
    text = "\n".join(lines)
    assert "并连带解开 **2 条**" in text, "有下游的那项没算出连带数"
    assert "连带解开 **0 条**" not in text, "无下游时不许写「连带解开 0 条」"
    weak = [ln for ln in lines if ln.startswith("- 补录后：") and "连带" not in ln]
    assert weak, "无下游的那项没有回落到弱表述"


def test_mutation_removing_reverse_index_loses_the_number():
    """反向变异验证：拿掉 `root_dependency_ids` 后，「连带解开」必须消失。

    没有变异验证的测试可能什么都没测（本项目既有教训）。
    """
    mp = {
        "OB-root": SimpleNamespace(
            responsibility="professional_input_required",
            professional_action="提交甲资料", root_dependency_ids=[]),
        "OB-dep1": SimpleNamespace(
            responsibility="system_unresolved",
            professional_action=None, root_dependency_ids=[]),  # ← 变异点
    }
    text = "\n".join(rw._render_professional_action_items(mp))
    assert "连带解开" not in text, (
        "拿掉根依赖后仍渲染出连带数 ⇒ 那个数不是从反向索引来的")
