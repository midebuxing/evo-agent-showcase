"""消费者文档：「你该做什么」必须排在最前（2026-07-30 立）。

## 为什么有这道闸

实测（批 `phase_i_fragcov2_seed301_20260729`，单栋）：

```
文档 47.7 KB / 496 行
对专业审查员**有行动价值**的：17 条义务 → 4 项行动
它们原先在**第 266 行**
前 235 行：未闭合项逐组穷举 + 13 个归因分节
   —— 讲的全是**系统自己哪里不知道**（5,071 条 = 99.7%）
```

审查员打开先看到 `run_id` / `allow_stop` / `stop_reason` 和
`artifact_state_not_valid_evidence` 这类原因码——**开发者语言**。
而他要问的只有一句：**「这栋楼我现在该去看什么、补什么」**。

⇒ 把行动项提到最前。**一条系统自述都没删**，只换顺序（实测 47.7 → 48.5 KB）。

## 🔴 这道闸锁的是「顺序」，不是「内容」

「系统对自己诚实」与「对使用者好用」是**两件事**。本项目此前 12 天只做到前者：
诊断轴建了大量闸（双轨判据 / 供给侧分账 / 量词口径 / 精确率侧 / 词表对账），
消费者轴只动过一次（2026-07-28 从 1078 KB 瘦到 36 KB）——
**那次优化的是字节数，不是有用性**：瘦身后行动项仍埋在第 266 行。

⇒ 本测试防的是「有人重排章节，行动项又沉下去」这种**静默回退**。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from evo_agent_baseline.agent import report_writer as rw
from evo_agent_baseline.contracts import ClosureValidationResult

REPO = pathlib.Path(__file__).resolve().parents[5]


def _load_any_incomplete_result(
    *, require_attribution: bool = False,
) -> ClosureValidationResult | None:
    """找一份真实的 allow_stop=False 产物；找不到就跳过（不是所有环境都有批产物）。

    `require_attribution=True` 时只收**带 unknown 归因映射**的产物。
    """
    for p in (REPO / "agent_v1/experiments").glob(
            "*/buildings/*/runs/*/closure_validation_result.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("allow_stop") is False:
            if require_attribution and not d.get("unknown_attribution_by_obligation_id"):
                # 归因功能 2026-07-27 才落地，仓库里大量早于它的产物归因映射为空，
                # 那些产物会让归因节走降级分支——用它们测「归因节里有什么」等于没测。
                continue
            try:
                return ClosureValidationResult.model_validate(d)
            except Exception:  # noqa: BLE001
                continue
    return None


def test_action_items_appear_before_diagnostics() -> None:
    """行动项必须出现在「未闭合项」诊断段**之前**。"""
    res = _load_any_incomplete_result()
    if res is None:
        import pytest
        pytest.skip("本环境无 allow_stop=False 的批产物")
    md = rw.render_incomplete_closure_notice(res)
    lines = md.splitlines()

    def first(pat: str) -> int | None:
        for i, l in enumerate(lines):
            if pat in l:
                return i
        return None

    act = first("需要你补充的资料")
    diag = first("## 未闭合项")
    assert act is not None, "文档里没有行动项一节"
    assert diag is not None, "文档里没有未闭合项一节"
    assert act < diag, (
        f"行动项在第 {act + 1} 行、诊断段在第 {diag + 1} 行——"
        "行动项必须在前，否则审查员要翻过几百行系统自述才找到该做什么")
    # 且必须足够靠前：审查员不该为了找它而滚屏
    assert act < 40, f"行动项在第 {act + 1} 行，太靠后（阈值 40 行内）"


def test_diagnostic_section_is_explicitly_marked_as_optional() -> None:
    """诊断段前必须有一句明确的分界——告诉审查员后面的内容不需要他补录。

    没有这句话，把行动项前置只是把噪声往后挪；审查员仍不知道
    「我是不是还得往下看」。
    """
    res = _load_any_incomplete_result()
    if res is None:
        import pytest
        pytest.skip("本环境无 allow_stop=False 的批产物")
    md = rw.render_incomplete_closure_notice(res)
    assert "看完上面一节即可" in md, "缺少「行动项看完即可」的分界说明"
    assert "不需要你补录" in md, "没说清后面的诊断内容不需要审查员补录"


def test_nothing_was_deleted_only_reordered() -> None:
    """只换顺序、不删内容——诊断各节必须仍在。

    这条防的是「为了让文档变短而砍掉系统自述」——那会牺牲诚实度换可读性，
    与本项目「有故 unknown 须说清为什么」的验收标准②直接冲突。
    """
    res = _load_any_incomplete_result()
    if res is None:
        import pytest
        pytest.skip("本环境无 allow_stop=False 的批产物")
    md = rw.render_incomplete_closure_notice(res)
    for section in ("## 未闭合项", "## unknown 归因", "open obligations"):
        assert section in md, f"诊断段 {section} 被删了——只许换顺序，不许删内容"


def _professional_attr(action: str, slot: str = "internal.slot") -> SimpleNamespace:
    return SimpleNamespace(
        responsibility="professional_input_required",
        professional_action=action,
        responsible_slot_id=slot,
    )


def test_action_item_shows_source_clause() -> None:
    """T1：消费者主视图必须明确给出法规依据。"""
    lines = rw._render_professional_action_items(
        {"o1": _professional_attr("提交检查记录。")},
        obligation_index={
            "o1": {
                "obligation_id": "o1",
                "source_clause_ids": ["3.3.2(J)(b)"],
                "fragment_id": None,
            }
        },
    )
    assert "- 依据：守则 §3.3.2(J)(b)" in lines


def test_internal_slot_is_not_in_consumer_view() -> None:
    """T2：内部槽编号不得混入消费者主视图。"""
    internal_slot = "scope.component.covered_by_large_attached_signboard"
    rendered = "\n".join(
        rw._render_professional_action_items(
            {"o1": _professional_attr("提交检查记录。", internal_slot)},
            obligation_index={
                "o1": {
                    "source_clause_ids": ["3.3.2(J)(b)"],
                    "fragment_id": None,
                }
            },
        )
    )
    assert internal_slot not in rendered
    assert "槽未标注" not in rendered


def test_fragment_prefix_is_removed_and_more_than_eight_is_explicit() -> None:
    """T3：用 10 个片段触发折叠，并锁住楼宇前缀剥离和总数文案。"""
    building_id = "BLD-HK-COASTAL-COMPOSITE-TOWER-RC-0007"
    building_fragment_prefix = "FRG-HK-COASTAL-COMPOSITE-TOWER-RC-0007-"
    mapping = {}
    obligation_index = {}
    for index in range(10):
        obligation_id = f"o{index}"
        mapping[obligation_id] = _professional_attr("提交现场检查记录。")
        obligation_index[obligation_id] = {
            "source_clause_ids": ["3.3.2(J)(b)"],
            "fragment_id": (
                f"{building_fragment_prefix}EXTERNAL-WALL-00-{index:02d}"
            ),
        }

    rendered = "\n".join(
        rw._render_professional_action_items(
            mapping,
            obligation_index=obligation_index,
            building_id=building_id,
        )
    )
    assert building_fragment_prefix not in rendered
    assert "`EXTERNAL-WALL-00-00`" in rendered
    assert "`EXTERNAL-WALL-00-07`" in rendered
    assert "`EXTERNAL-WALL-00-08`" not in rendered
    assert "…（共 10 处，完整清单见结果 JSON）" in rendered


def test_item_without_fragment_uses_unlocated_wording() -> None:
    """T4：无片段时只报告义务数，不伪造部位。"""
    rendered = "\n".join(
        rw._render_professional_action_items(
            {
                "o1": _professional_attr("提交书面通知。"),
                "o2": _professional_attr("提交书面通知。"),
            },
            obligation_index={
                "o1": {"source_clause_ids": ["4.2.3"], "fragment_id": None},
                "o2": {"source_clause_ids": ["4.2.3"], "fragment_id": None},
            },
        )
    )
    assert "涉及 **2 条义务**（未定位到具体部位）" in rendered
    assert "FRG-" not in rendered


def test_missing_obligation_index_degrades_without_crashing() -> None:
    """T5：义务索引缺省时明确降级，不出现 None 或内部槽占位。"""
    rendered = "\n".join(
        rw._render_professional_action_items(
            {"o1": _professional_attr("提交检查记录。")}
        )
    )
    assert "依据：（本项未标注条款，见结果 JSON）" in rendered
    assert "涉及 **1 条义务**（未定位到具体部位）" in rendered
    assert "None" not in rendered
    assert "槽未标注" not in rendered


def test_same_action_with_different_clauses_is_not_merged() -> None:
    """R5：相同行动跨条款时仍是两个消费者条目。"""
    action = "提交检查记录。"
    rendered = "\n".join(
        rw._render_professional_action_items(
            {
                "o1": _professional_attr(action),
                "o2": _professional_attr(action),
            },
            obligation_index={
                "o1": {"source_clause_ids": ["3.3.2(J)(b)"]},
                "o2": {"source_clause_ids": ["4.2.3"]},
            },
        )
    )
    assert "共 **2 项**，涉及 **2 条义务**" in rendered
    assert rendered.count(f"{action}**") == 2
    assert rendered.index("§3.3.2(J)(b)") < rendered.index("§4.2.3")


def test_action_items_section_appears_exactly_once() -> None:
    """🔴 行动项节在整份告知书里**只能出现一次**。

    这条是 2026-07-31 实测撞出来才补的：把行动项提到文首之后，
    `render_unknown_attribution_section` 里**原来那份还在**，于是同一份文档
    渲染了两遍完全相同的表——A 门重复行率 4.6% → 7.8%（判据 ≤5%），
    一个本来通过的子判据被这次「改进」改成了不通过。

    当时全部单测绿灯，因为它们都在问「新的那份对不对」，
    **没有一条问「旧的那份还在不在」**。同族信号已入册：
    「同一份产物里两处报同一批对象」。
    """
    # 🔴 必须 require_attribution=True：无归因的老产物会让归因节走降级分支，
    # 第二份行动项**根本不会渲染**——在那种输入上断言「只出现一次」恒真、等于没测。
    # （2026-07-31 变异验证当场抓到：不带这个参数时，把 skip_action_items 去掉，
    #   测试照样全绿。）
    result = _load_any_incomplete_result(require_attribution=True)
    if result is None:
        import pytest

        pytest.skip("本机没有带 unknown 归因映射的落盘产物")
    rendered = rw.render_incomplete_closure_notice(result)
    assert rendered.count("### 需要你补充的资料") == 1, (
        "行动项节出现了多次——文首已渲染时，归因节必须传 skip_action_items=True"
    )


def test_attribution_section_keeps_action_items_by_default() -> None:
    """缺省等价：不传 `skip_action_items` 的调用方（v3/v4 组合报告）行为不变。

    没有这条，上一条测试可以被「干脆把归因节里的行动项删掉」这种改法骗过去，
    而那样会让基线本体（满血 LLM 档）的报告**丢掉整节**。
    """
    result = _load_any_incomplete_result(require_attribution=True)
    if result is None:
        import pytest

        pytest.skip("本机没有带 unknown 归因映射的落盘产物")
    default = "\n".join(rw.render_unknown_attribution_section(result))
    skipped = "\n".join(
        rw.render_unknown_attribution_section(result, skip_action_items=True)
    )
    assert default.count("### 需要你补充的资料") == 1
    assert skipped.count("### 需要你补充的资料") == 0


def test_main_view_carries_no_runtime_hash() -> None:
    """🔴 主视图（折叠块之外）不得出现 24 位运行期哈希。

    消费者验收 A 门 `check_report_usability.py` 把它列为硬判据（=0），
    而本项目此前**没有任何单测查过这一条**——靠批级闸才发现单栋 10 个。

    10 个全部来自「继承根聚合」表的根义务 id 列（`_render_inherited_by_root`）。
    审查员要的是「哪条条款、连带几条、根因是什么」，不是运行期 id；
    逐条 id 在 `closure_validation_result.json` 里下钻。

    ⚠️ 判据只看**主视图**：折叠块（`<details>`）内的完整台账**允许**保留 id，
    那是机器下钻面，删掉会伤可追溯性。
    """
    import re

    # 🔴 require_attribution=True：合成夹具/老产物不产生「继承根聚合」表，
    # 在那种输入上「无哈希」恒真——今日已栽过一次（见 feedback 记忆）。
    result = _load_any_incomplete_result(require_attribution=True)
    if result is None:
        import pytest

        pytest.skip("本机没有带归因映射的落盘产物")
    lines = rw.render_incomplete_closure_notice(result).splitlines()
    main, depth = [], 0
    for line in lines:
        if "<details" in line:
            depth += 1
            continue
        if "</details" in line:
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            main.append(line)
    hash_re = re.compile(r"\b[0-9a-f]{24}\b")
    offenders = [l for l in main if hash_re.search(l)]
    assert not offenders, (
        f"主视图出现 {len(offenders)} 行运行期哈希（A 门硬判据要求 0）："
        f"{offenders[:2]}"
    )
