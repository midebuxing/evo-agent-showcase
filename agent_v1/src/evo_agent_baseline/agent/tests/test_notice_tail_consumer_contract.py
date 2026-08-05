"""闭包未完成说明尾部的消费者契约（工单 #2）。"""
from __future__ import annotations

from types import SimpleNamespace

from evo_agent_baseline.agent import report_writer as rw


_INTERNAL_MARKERS = ("sources=[", "bucket=", "trigger aggregate blocked")


def _attr(
    responsibility: str,
    *,
    action: str = "",
    cause_code: str = "slot_not_supplied",
) -> SimpleNamespace:
    return SimpleNamespace(
        responsibility=responsibility,
        professional_action=action,
        responsible_slot_id="internal.slot",
        cause_code=cause_code,
        explanation="这条义务缺少核验所需资料。",
        root_dependency_ids=[],
    )


def _result(*, legacy_mapping: bool = False) -> SimpleNamespace:
    professional_card = "rc.test.professional.c01"
    system_card = "rc.test.system.c01"
    professional_obligation = SimpleNamespace(
        obligation_id="O-PRO",
        satisfaction_status="unknown",
        source_rule_card_id=professional_card,
        source_clause_ids=["3.3.2(J)(b)"],
    )
    system_obligation = SimpleNamespace(
        obligation_id="O-SYS",
        satisfaction_status="unknown",
        source_rule_card_id=system_card,
        source_clause_ids=["4.2.3"],
    )
    open_items = [
        {
            "obligation_id": "O-PRO",
            "source_rule_card_id": professional_card,
            "source_clause_ids": ["3.3.2(J)(b)"],
            "fragment_id": "FRG-BLD-TEST-WALL-01",
            "open_reason_code": "slot_not_supplied",
            "notes": "sources=[obligation_graph]; bucket=workflow; trigger aggregate blocked",
        },
        {
            "obligation_id": "O-SYS",
            "source_rule_card_id": system_card,
            "source_clause_ids": ["4.2.3"],
            "fragment_id": "FRG-BLD-TEST-WALL-02",
            "open_reason_code": "slot_not_supplied",
            "notes": "sources=[obligation_graph]; bucket=world; trigger aggregate blocked",
        },
    ]
    mapping = None if legacy_mapping else {
        "O-PRO": _attr(
            "professional_input_required",
            action="提交现场量测记录。",
        ),
        "O-SYS": _attr(
            "system_unresolved",
            action="系统侧项目不得向审查员索取。",
        ),
    }
    # 夹具须带真实 ClosureValidationResult 恒有的机器标识字段——
    # 文末「诊断信息」节（2026-08-04 审核门补回）会渲染它们，缺则 AttributeError/渲出 None。
    return SimpleNamespace(
        run_id="RUN-TEST",
        allow_stop=False,
        closure_summary=SimpleNamespace(
            open_count=2, blocked_count=0, stop_reason="closure_incomplete",
        ),
        machine_readable_report={
            "building_id": "BLD-TEST",
            "world_id": "WORLD-TEST",
            "stop_reason": "closure_incomplete",
            "open_items": open_items,
            "blocked_items": [],
        },
        obligation_set=SimpleNamespace(
            obligations=[professional_obligation, system_obligation]
        ),
        unknown_attribution_by_obligation_id=mapping,
    )


def _tail(markdown: str) -> str:
    return markdown.split("## 建议补充 / 检查资料", 1)[1]


def test_t1_tail_cross_references_only_professional_input_items() -> None:
    """T1/F1/F2：行动项只取专业人员责任，尾节不重复逐项清单。"""
    markdown = rw.render_incomplete_closure_notice(_result())
    action_section = markdown.split(
        "> 以下为诊断明细。", 1
    )[0]
    tail = _tail(markdown)

    assert "提交现场量测记录。" in action_section
    assert "系统侧项目不得向审查员索取。" not in action_section
    assert "共 1 项 / 1 条义务" in tail
    assert "其余 **1** 条未闭合项属**系统侧缺口**" in tail
    assert "rc.test." not in tail
    assert "提交现场量测记录。" not in tail


def test_t2_full_document_hides_internal_notes_even_in_legacy_fallback() -> None:
    """T2/F3：即使老产物走降级，notes 内部串也不得进入全文。"""
    markdown = rw.render_incomplete_closure_notice(
        _result(legacy_mapping=True)
    )
    for marker in _INTERNAL_MARKERS:
        assert marker not in markdown, f"消费者文档泄漏内部调试串：{marker}"


def test_t3_missing_attribution_mapping_degrades_without_crashing() -> None:
    """T3/F5：None 与空映射都明确降级，并保留未闭合项清单。"""
    for mapping in (None, {}):
        result = _result(legacy_mapping=True)
        result.unknown_attribution_by_obligation_id = mapping
        markdown = rw.render_incomplete_closure_notice(result)
        tail = _tail(markdown)
        assert (
            "（本次结果未带归因映射，以下按未闭合项原样列出，"
            "其中部分可能属系统侧缺口。）"
        ) in tail
        assert "[§3.3.2(J)(b) / slot_not_supplied] 共 1 条待补充。" in tail
        assert "None" not in markdown


def test_t4_rule_reference_priority_merge_and_raw_id_fallback() -> None:
    """T4/G1-G3：义务条款优先、卡包次之、缺锚保留卡号，并按条款合并。"""
    assert rw._rule_reference(
        {"source_clause_ids": ["3.4.2(A)"]}, "rc.any"
    ) == "§3.4.2(A)"
    assert rw._rule_reference(
        {}, "rc.mbis.reporting.inspection_report.ri.submit.s2_1_3_o.c01"
    ) == "§2.1.3(o)"
    assert rw._rule_reference({}, "rc.unknown.keep-me.c01") == "rc.unknown.keep-me.c01"

    rendered = "\n".join(
        rw._render_unclosed_group_table(
            "open obligations（资料缺失，待补充）",
            [
                {
                    "obligation_id": "O1",
                    "source_rule_card_id": "rc.one",
                    "source_clause_ids": ["3.4.2(A)"],
                    "open_reason_code": "missing_fact",
                },
                {
                    "obligation_id": "O2",
                    "source_rule_card_id": "rc.two",
                    "source_clause_ids": ["3.4.2(A)"],
                    "open_reason_code": "missing_fact",
                },
            ],
            "open_reason_code",
        )
    )
    assert "2 条 / 1 个条款依据" in rendered
    assert "| 2 | §3.4.2(A) |" in rendered
    assert "rc.one" not in rendered and "rc.two" not in rendered


def test_t5_unknown_cause_table_leads_with_chinese_description() -> None:
    """T5/H1：中文说明居首，机器原因码只在末列小字保留。"""
    rendered = "\n".join(rw.render_unknown_attribution_section(_result()))
    assert "| 说明 | 条数 | 原因码 |" in rendered
    assert (
        "| 世界侧未供给该项数据 | 2 "
        "| <small><code>slot_not_supplied</code></small> |"
    ) in rendered
    assert "| `slot_not_supplied` |" not in rendered


def test_j2_action_header_and_item_counts_use_distinct_units() -> None:
    """J2：表头按义务计，条目按去重部位计，同一个词不再指两种单位。"""
    mapping = {
        "O1": _attr("professional_input_required", action="提交记录。"),
        "O2": _attr("professional_input_required", action="提交记录。"),
    }
    obligation_index = {
        "O1": {
            "source_clause_ids": ["3.3.2(J)(b)"],
            "fragment_id": "FRG-BLD-TEST-WALL-01",
        },
        "O2": {
            "source_clause_ids": ["3.3.2(J)(b)"],
            "fragment_id": "FRG-BLD-TEST-WALL-01",
        },
    }
    rendered = "\n".join(
        rw._render_professional_action_items(
            mapping,
            obligation_index=obligation_index,
            building_id="BLD-TEST",
        )
    )
    assert "共 **1 项**，涉及 **2 条义务**" in rendered
    assert "涉及 **1 处**：`WALL-01`" in rendered


def test_g4_translation_fields_never_supply_consumer_rule_text(monkeypatch) -> None:
    """G4：中文权威正文缺失时，不得回退到任何卡包派生译文。"""
    monkeypatch.setattr(rw.zh_authority, "zh_text_for_card", lambda _card_id: None)
    card = SimpleNamespace(
        rule_card_id="rc.translation.sentinel",
        source_quote=[{"text": "FORBIDDEN_SOURCE_QUOTE_SENTINEL"}],
        normalized_rule_text="FORBIDDEN_NORMALIZED_SENTINEL",
    )
    assert rw._first_quote_for_card(None, card) is None
