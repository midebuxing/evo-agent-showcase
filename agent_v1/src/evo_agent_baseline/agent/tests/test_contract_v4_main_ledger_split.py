"""报告契约 v4 的主视图 / 完整台账二层化契约。"""

from __future__ import annotations

from types import SimpleNamespace

from evo_agent_baseline.agent import report_writer as rw


def _obligation(
    obligation_id: str,
    *,
    closure_status: str,
    satisfaction_status: str,
    card_id: str,
    fragment_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        obligation_id=obligation_id,
        closure_status=closure_status,
        satisfaction_status=satisfaction_status,
        source_rule_card_id=card_id,
        source_clause_ids=["3.3.2(J)(b)"],
        fragment_id=fragment_id,
        component_id="CMP-TEST",
        kind="evidence",
        observed_value_json=False,
        threshold_value_json=True,
        expected_value_json=True,
        open_reason_code=(
            "slot_not_supplied" if closure_status == "open" else None
        ),
        blocked_reason_code=None,
        notes="逐条台账哨兵",
    )


def _result() -> SimpleNamespace:
    open_obligation = _obligation(
        "O-OPEN",
        closure_status="open",
        satisfaction_status="unknown",
        card_id="rc.open",
        fragment_id="FRG-BLD-TEST-WALL-01",
    )
    violated_obligation = _obligation(
        "O-VIOLATED",
        closure_status="closed",
        satisfaction_status="violated",
        card_id="rc.violated",
        fragment_id="FRG-BLD-TEST-WALL-02",
    )
    summary = SimpleNamespace(
        total_obligations=2,
        open_count=1,
        blocked_count=0,
        closed_count=1,
        satisfied_count=0,
        violated_count=1,
        unknown_count=1,
        not_applicable_count=0,
        stop_reason="open_obligations_remain",
        open_reason_counts={"slot_not_supplied": 1},
        blocked_reason_counts={},
    )
    attribution = SimpleNamespace(
        responsibility="professional_input_required",
        cause_code="slot_not_supplied",
        explanation="唯一归因解释哨兵",
        professional_action="提交现场检查记录。",
        responsible_slot_id="artifact.record.inspection_log",
        root_dependency_ids=[],
    )
    return SimpleNamespace(
        run_id="RUN-V4-SLIM",
        allow_stop=False,
        closure_summary=summary,
        obligation_set=SimpleNamespace(
            obligations=[open_obligation, violated_obligation],
            identity_manifest=[
                {
                    "obligation_id": "O-OPEN",
                    "canonical_identity_hash": "a" * 64,
                },
                {
                    "obligation_id": "O-VIOLATED",
                    "canonical_identity_hash": "b" * 64,
                },
            ],
        ),
        unknown_attribution_by_obligation_id={"O-OPEN": attribution},
        machine_readable_report={
            "building_id": "BLD-TEST",
            "open_items": [
                {
                    "obligation_id": "O-OPEN",
                    "source_rule_card_id": "rc.open",
                    "source_clause_ids": ["3.3.2(J)(b)"],
                    "fragment_id": "FRG-BLD-TEST-WALL-01",
                    "open_reason_code": "slot_not_supplied",
                }
            ],
            "blocked_items": [],
        },
        high_risk_items=[
            {
                "obligation_id": "O-VIOLATED",
                "source_family_id": "fam.v4.slim",
                "severity": "high",
                "reason": "额外风险说明哨兵",
            }
        ],
    )


def _render() -> str:
    return rw.render_contract_v2_report(
        _result(),
        world_id="WORLD-TEST",
        building_id="BLD-TEST",
        generated_at="2026-07-31T00:00:00Z",
        kg_snapshot_id="KGS-TEST",
        rulecard_bundle_id="RULES-TEST",
        fact_source_tables=["facts.parquet"],
        rule_families=[
            {
                "family": "fam.v4.slim",
                "rule_card_count": 2,
                "source_clauses": "§3.3.2(J)(b)",
            }
        ],
        analysis_markdown="### 模型分析要点\n\n- 模型分析正文哨兵。",
        analysis_is_llm=True,
        contract_version=4,
    )


def _main_view(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    first_detail = lines.index("<details>")
    return lines[:first_detail]


def test_v4_main_view_is_bounded_and_contains_required_sections() -> None:
    """首个折叠块前不超过 250 行，且消费者必需信息全部可见。"""
    main_lines = _main_view(_render())
    main = "\n".join(main_lines)

    assert len(main_lines) <= 250
    required = (
        "- satisfied: 0",
        "- violated: 1",
        "程序计数：violated = 1，high_risk = 1。",
        "### 需要你补充的资料",
        "### 未闭合项聚合概览（按规则卡 × 原因码，主视图）",
        "## 未闭合原因与补充资料建议（模型生成）",
        "模型分析正文哨兵",
    )
    for text in required:
        assert text in main, f"主视图缺少必备内容：{text}"


def test_v4_every_itemized_ledger_stays_complete_inside_details() -> None:
    """逐条内容一条不少，且所有逐条哨兵都位于折叠块内。"""
    lines = _render().splitlines()
    depth = 0
    depth_by_line: list[int] = []
    for line in lines:
        if line == "<details>":
            depth += 1
        depth_by_line.append(depth)
        if line == "</details>":
            depth -= 1
    assert depth == 0, "折叠块未配对"

    sentinels = (
        "fam.v4.slim",
        "O-OPEN",
        "O-VIOLATED",
        "唯一归因解释哨兵",
        "额外风险说明哨兵",
        "## 法规引用与证据（程序辑录）",
        "疑似未满足义务",
        "b" * 64,
    )
    for sentinel in sentinels:
        hits = [
            depth_by_line[index]
            for index, line in enumerate(lines)
            if sentinel in line
        ]
        assert hits, f"完整台账丢失哨兵：{sentinel}"
        assert all(hit > 0 for hit in hits), f"逐条哨兵泄漏到主视图：{sentinel}"

    expected_summaries = (
        "family 明细表",
        "未闭合项完整台账",
        "unknown 归因逐项说明",
        "疑似未满足完整台账",
        "额外高风险项完整台账",
        "法规引用与证据完整台账",
        "逐条复核清单",
        "展示编号 → obligation_id → canonical_identity_hash 映射",
    )
    summaries = [line for line in lines if line.startswith("<summary>")]
    for label in expected_summaries:
        assert any(label in summary for summary in summaries), f"缺折叠台账：{label}"


def test_v4_authoritative_counts_titles_and_disclaimer_are_unchanged() -> None:
    """二层化只改呈现位置，不得改权威计数、标题、免责或九项骨架。"""
    markdown = _render()
    lines = markdown.splitlines()
    authoritative_lines = (
        "- total: 2",
        "- open: 1",
        "- blocked: 0",
        "- closed: 1",
        "- satisfied: 0",
        "- violated: 1",
        "- unknown: 1",
        "- not_applicable: 0",
        "- allow_stop: False",
        "- stop_reason: open_obligations_remain",
        "程序计数：violated = 1，high_risk = 1。"
        "下表所列为闭包验证显示的疑似未满足项，建议人工复核；"
        "本表不构成最终不合规结论。",
    )
    for expected in authoritative_lines:
        assert lines.count(expected) == 1, f"权威行被改写、丢失或重复：{expected}"

    assert lines[0] == "# MBIS 闭包未完成说明（非最终裁决）"
    assert rw._DISCLAIMER in lines[2]
    skeleton = (
        "## 评估范围",
        "## 权威闭包概览",
        "## 未闭合项",
        "## unknown 归因（这些项为什么还没有结论）",
        "## 疑似未满足 / 高风险项",
        "## 法规引用与证据（程序辑录）",
        "## 未闭合原因与补充资料建议（模型生成）",
        "## 人工复核提示",
    )
    for heading in skeleton:
        assert lines.count(heading) == 1, f"报告骨架标题异常：{heading}"
    assert "PDF/打印导出前须先展开全部折叠块" in markdown
