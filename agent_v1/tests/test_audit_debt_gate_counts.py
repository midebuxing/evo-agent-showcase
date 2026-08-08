# -*- coding: utf-8 -*-
"""G7 脚本四修回归测试。

防 DEBT-085 类误中（`决议_G7口径_20260808.md` 第 4 条）：
- 旧口径用裸子串匹配（「换池前」「前置」），91,516 字符节体吞并叙事 -> 误归 PRE_SWAP
- 新口径用登记驱动分类（gate_class: 显式标记），去裸子串匹配 -> DEBT-085 落 CARRIED

四修验证点：
1. 登记驱动分类：MUST_CLEAR 桶只认显式 gate_class 标记
2. 显式标记语法：gate_class: MUST_CLEAR_PRE_SWAP / MUST_CLEAR_BEFORE_CLOSE
3. 状态判据双源 ✅：双源不一致 -> STATUS_DISCREPANCY_PENDING
4. 小节边界修：按 ## 标题切节防吞并叙事
"""
from __future__ import annotations

import importlib.util
import pathlib
import textwrap

_root = pathlib.Path(__file__).resolve().parents[2]
_script_path = _root / "agent_v1" / "scripts" / "audit_debt_gate_counts.py"
_spec = importlib.util.spec_from_file_location("audit_debt_gate_counts", _script_path)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# 1. 登记驱动分类：MUST_CLEAR 桶只认显式 gate_class 标记
# ---------------------------------------------------------------------------

def test_no_gate_class_marker_falls_to_carried() -> None:
    """无 gate_class 标记的 OPEN 债 -> CARRIED（划分读法），不落 MUST_CLEAR。"""
    result = mod.classify_debt(
        "DEBT-TEST-001",
        book_entry={
            "header": "测试债",
            "body": "这段正文提到换池前必须清零阻断前置，但没有 gate_class 标记。\n",
            "body_len": 30,
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["bucket"] == "CARRIED", (
        f"无 gate_class 标记的 OPEN 债应落 CARRIED，实际={result['bucket']}；"
        "旧口径裸子串匹配会误中「换池前」「前置」"
    )
    assert result["gate_class_marker"] is None


def test_bare_substring_does_not_trigger_pre_swap() -> None:
    """正文含「换池前」「前置」「必须清零」「阻断」等旧裸子串标记，但无 gate_class -> 不落 PRE_SWAP。

    这是 DEBT-085 误中的精确回归点：旧口径因这些裸子串命中叙事而误归 PRE_SWAP。
    """
    body_with_old_markers = textwrap.dedent("""\
    本债是 §6.1.3 解冻的前置。
    ### 换池捆绑审核关案
    换池前必须清零阻断 PRE_SWAP 的叙事...
    """)
    result = mod.classify_debt(
        "DEBT-085-REGRESSION",
        book_entry={
            "header": "判定粒度须显式声明",
            "body": body_with_old_markers,
            "body_len": len(body_with_old_markers),
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["bucket"] != "MUST_CLEAR_PRE_SWAP", (
        "裸子串匹配仍命中！旧口径 bug 复现：正文含「换池前」「前置」但无 gate_class 标记"
    )
    assert result["bucket"] == "CARRIED"


# ---------------------------------------------------------------------------
# 2. 显式标记语法：gate_class 标记被正确识别
# ---------------------------------------------------------------------------

def test_gate_class_pre_swap_marker() -> None:
    """有 gate_class: MUST_CLEAR_PRE_SWAP 标记 -> MUST_CLEAR_PRE_SWAP。"""
    body = "一些正文。\ngate_class: MUST_CLEAR_PRE_SWAP\n更多正文。\n"
    result = mod.classify_debt(
        "DEBT-TEST-PRE",
        book_entry={
            "header": "测试",
            "body": body,
            "body_len": len(body),
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["bucket"] == "MUST_CLEAR_PRE_SWAP"
    assert result["gate_class_marker"] == "MUST_CLEAR_PRE_SWAP"


def test_gate_class_before_close_marker() -> None:
    """有 gate_class: MUST_CLEAR_BEFORE_CLOSE 标记 -> MUST_CLEAR_BEFORE_CLOSE。"""
    body = "一些正文。\n  gate_class: MUST_CLEAR_BEFORE_CLOSE\n更多正文。\n"
    result = mod.classify_debt(
        "DEBT-TEST-BC",
        book_entry={
            "header": "测试",
            "body": body,
            "body_len": len(body),
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["bucket"] == "MUST_CLEAR_BEFORE_CLOSE"
    assert result["gate_class_marker"] == "MUST_CLEAR_BEFORE_CLOSE"


def test_gate_class_marker_must_be_own_line() -> None:
    """gate_class 标记须独占一行，内联不算。"""
    body = "正文 gate_class: MUST_CLEAR_PRE_SWAP 不是独占一行。\n"
    result = mod.classify_debt(
        "DEBT-TEST-INLINE",
        book_entry={
            "header": "测试",
            "body": body,
            "body_len": len(body),
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["bucket"] == "CARRIED", "内联 gate_class 不应被识别为标记"
    assert result["gate_class_marker"] is None


# ---------------------------------------------------------------------------
# 3. 状态判据双源 ✅：双源不一致 -> STATUS_DISCREPANCY_PENDING
# ---------------------------------------------------------------------------

def test_dual_source_discrepancy_goes_pending() -> None:
    """双源不一致（跟踪表 ✅ 但债册标题无 ✅）-> STATUS_DISCREPANCY_PENDING，不进 G7 桶。"""
    result = mod.classify_debt(
        "DEBT-TEST-DISC",
        book_entry={
            "header": "测试债（标题无 ✅）",
            "body": "正文有 gate_class: MUST_CLEAR_BEFORE_CLOSE\n",
            "body_len": 40,
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "✅",
            "tracking_status": "RESOLVED",
        },
    )
    assert result["bucket"] == "STATUS_DISCREPANCY_PENDING", (
        "双源不一致应落 STATUS_DISCREPANCY_PENDING，不进任何 G7 桶；"
        "旧口径会把它当 OPEN 充进 BEFORE_CLOSE 污染门读数"
    )
    assert result["discrepancy"] is True


def test_both_resolved_is_resolved() -> None:
    """两源都 ✅ -> RESOLVED。"""
    result = mod.classify_debt(
        "DEBT-TEST-RES",
        book_entry={
            "header": "✅ 已闭环的测试债",
            "body": "",
            "body_len": 0,
            "book_resolved": True,
        },
        tracking_entry={
            "tracking_emoji": "✅",
            "tracking_status": "RESOLVED",
        },
    )
    assert result["bucket"] == "RESOLVED"
    assert result["resolved"] is True


def test_both_open_is_open() -> None:
    """两源都 OPEN -> OPEN，正常进桶分类。"""
    body = "gate_class: MUST_CLEAR_PRE_SWAP\n"
    result = mod.classify_debt(
        "DEBT-TEST-OPEN",
        book_entry={
            "header": "测试债",
            "body": body,
            "body_len": len(body),
            "book_resolved": False,
        },
        tracking_entry={
            "tracking_emoji": "⏳",
            "tracking_status": "OPEN",
        },
    )
    assert result["resolved"] is False
    assert result["discrepancy"] is False
    assert result["bucket"] == "MUST_CLEAR_PRE_SWAP"


# ---------------------------------------------------------------------------
# 4. 小节边界修：按 ## 标题切节防吞并叙事
# ---------------------------------------------------------------------------

def test_section_boundary_stops_at_any_h2() -> None:
    """节体在下一个 ## 标题（任意 ## 标题，不只是 ## DEBT-）处截止。

    旧口径按下一个 `## DEBT-` 切节，会吞并中间的非 DEBT 的 `##` 叙事节
    （DEBT-085 旧口径实测 91,516 字符）。
    """
    text = textwrap.dedent("""\
    ## DEBT-999｜边界测试

    这是 DEBT 节体。

    ### 子节
    子节内容。

    ## 非债叙事节（应被切断）

    这段不应出现在 DEBT 节体里。

    ## DEBT-998｜下一条债
    下一条债的内容。
    """)
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(text)
        f.flush()
        path = pathlib.Path(f.name)
    try:
        debts = mod.parse_debt_book(path)
        body = debts["DEBT-999"]["body"]
        assert "非债叙事节" not in body, (
            "节体吞并了非 DEBT 的 ## 叙事节！小节边界修未生效"
        )
        assert "子节内容" in body, "节体应包含 ### 子节"
    finally:
        path.unlink()


def test_debt_085_not_in_pre_swap_on_real_book() -> None:
    """用真实债册验证：DEBT-085 不落 MUST_CLEAR_PRE_SWAP。

    这是端到端回归：真实 91,516 字符节体（旧口径）含「换池前」「前置」叙事，
    新口径下应落 CARRIED（因无 gate_class 标记）。
    """
    if not mod.DEBT_BOOK.exists():
        import pytest
        pytest.skip("债册文件不存在")
    book = mod.parse_debt_book(mod.DEBT_BOOK)
    tracking = mod.parse_tracking_table(mod.TRACKING_TABLE)
    result = mod.classify_debt("DEBT-085", book.get("DEBT-085"), tracking.get("DEBT-085"))
    assert result["bucket"] != "MUST_CLEAR_PRE_SWAP", (
        "DEBT-085 仍误中 MUST_CLEAR_PRE_SWAP！四修未生效"
    )
    assert result["bucket"] in ("CARRIED", "STATUS_DISCREPANCY_PENDING"), (
        f"DEBT-085 应落 CARRIED 或 STATUS_DISCREPANCY_PENDING，实际={result['bucket']}"
    )


# ---------------------------------------------------------------------------
# 5. compute_counts：四计数结构正确
# ---------------------------------------------------------------------------

def test_compute_counts_separates_discrepancy() -> None:
    """compute_counts 把 STATUS_DISCREPANCY_PENDING 从四计数中分离。"""
    debts = [
        {"debt_id": "D1", "resolved": True, "bucket": "RESOLVED"},
        {"debt_id": "D2", "resolved": False, "bucket": "STATUS_DISCREPANCY_PENDING", "discrepancy": True},
        {"debt_id": "D3", "resolved": False, "bucket": "CARRIED",
         "missing_elements": ["排除范围"], "has_active_consumer": False},
        {"debt_id": "D4", "resolved": False, "bucket": "CARRIED",
         "missing_elements": [], "has_active_consumer": True},
        {"debt_id": "D5", "resolved": False, "bucket": "MUST_CLEAR_PRE_SWAP"},
        {"debt_id": "D6", "resolved": False, "bucket": "MUST_CLEAR_BEFORE_CLOSE"},
    ]
    result = mod.compute_counts(debts)
    assert result["counts"]["MUST_CLEAR_PRE_SWAP"] == 1
    assert result["counts"]["MUST_CLEAR_BEFORE_CLOSE"] == 1
    assert result["counts"]["CARRIED_DEBT_WITHOUT_SCOPE_EXCLUSION"] == 1
    assert result["counts"]["CARRIED_DEBT_WITH_ACTIVE_CONSUMER"] == 1
    assert result["discrepancy_count"] == 1
    assert result["discrepancy_ids"] == ["D2"]
