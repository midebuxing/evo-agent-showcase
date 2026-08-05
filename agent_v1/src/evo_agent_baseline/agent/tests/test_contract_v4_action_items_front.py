"""报告契约 v4 消费者面：行动项前置 + 类型不相容部位过滤（工单 #14，2026-08-01）。

两道 consumer 修正共用本夹具：

- **A**：「需要你补充的资料」整节提到 `## 评估范围` 之前（v1 告知书 2026-07-30
  已做，v4 当时没同步——同一个改动只做了一半）；原位置只留一行指回，不重复渲染
  （重复会把 A 门重复行率顶过 5%，2026-07-31 v1 改造实测撞过一次）。
- **B**：行动项「涉及 N 处」剔掉与卡侧要求类型**显式互斥**（验证器作用域关系旁路
  `authorized_disjoint`）的部位；`same` / `category_compatible`（子型相容，
  如片段 external_wall 属于卡侧 external_component）与判不出关系的一律保留——
  缺省保守，绝不按「字符串不等」剔。被剔部位不静默消失，显式写剔除条数。
  纯呈现：义务状态、计数、台账逐位不变（B4）。
"""
from __future__ import annotations

from types import SimpleNamespace

from evo_agent_baseline.agent import report_writer as rw

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_WALL_FRAGMENT = "FRG-BLD-TEST-EXTERNAL-WALL-00-01"
_DRAIN_FRAGMENT = "FRG-BLD-TEST-DRAINAGE-BRANCH-04-04"


def _obligation(obligation_id: str, fragment_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        obligation_id=obligation_id,
        closure_status="open",
        satisfaction_status="unknown",
        source_rule_card_id="rc.signboard",
        source_clause_ids=["3.3.2(J)(b)"],
        fragment_id=fragment_id,
        component_id=None,
        kind="evidence",
        observed_value_json=None,
        threshold_value_json=None,
        expected_value_json=None,
        open_reason_code="missing_fact",
        blocked_reason_code=None,
        notes="",
    )


def _attribution(relation: str | None) -> SimpleNamespace:
    scope = None
    if relation is not None:
        scope = SimpleNamespace(
            card_component_type_keys=("external_wall",),
            fragment_component_type="external_wall",
            relation=relation,
            target_authorization_status="effective_authorization_present",
            relation_policy_version="scope_relation.v1|test",
        )
    return SimpleNamespace(
        responsibility="professional_input_required",
        cause_code="slot_not_supplied",
        explanation="归因解释哨兵",
        professional_action="提交现场量测记录。",
        responsible_slot_id="scope.component.covered_by_large_attached_signboard",
        root_dependency_ids=[],
        scope_relation=scope,
    )


def _result(relations: dict[str, str | None]) -> SimpleNamespace:
    obligations = [
        _obligation("O-WALL", _WALL_FRAGMENT),
        _obligation("O-DRAIN", _DRAIN_FRAGMENT),
    ]
    summary = SimpleNamespace(
        total_obligations=2,
        open_count=2,
        blocked_count=0,
        closed_count=0,
        satisfied_count=0,
        violated_count=0,
        unknown_count=2,
        not_applicable_count=0,
        stop_reason="open_obligations_remain",
        open_reason_counts={"missing_fact": 2},
        blocked_reason_counts={},
    )
    return SimpleNamespace(
        run_id="RUN-V4-WO14",
        allow_stop=False,
        closure_summary=summary,
        obligation_set=SimpleNamespace(obligations=obligations, identity_manifest=[]),
        unknown_attribution_by_obligation_id={
            oid: _attribution(relations.get(oid)) for oid in ("O-WALL", "O-DRAIN")
        },
        machine_readable_report={
            "building_id": "BLD-TEST",
            "open_items": [
                {
                    "obligation_id": ob.obligation_id,
                    "source_rule_card_id": ob.source_rule_card_id,
                    "source_clause_ids": ob.source_clause_ids,
                    "fragment_id": ob.fragment_id,
                    "open_reason_code": "missing_fact",
                }
                for ob in obligations
            ],
            "blocked_items": [],
        },
        high_risk_items=[],
    )


def _render_v4(relations: dict[str, str | None]) -> str:
    return rw.render_contract_v2_report(
        _result(relations),
        world_id="WORLD-TEST",
        building_id="BLD-TEST",
        generated_at="2026-08-01T00:00:00Z",
        analysis_markdown="",
        analysis_is_llm=False,
        contract_version=4,
    )


# ---------------------------------------------------------------------------
# A：行动项前置
# ---------------------------------------------------------------------------


def test_action_items_section_precedes_scope_section() -> None:
    """A1：行动项整节必须出现在 `## 评估范围` 之前（免责与未通过声明之后）。"""
    lines = _render_v4({"O-WALL": "same", "O-DRAIN": "same"}).splitlines()
    action_idx = lines.index("### 需要你补充的资料")
    scope_idx = lines.index("## 评估范围")
    notice_idx = lines.index("本次资料闭包验证未通过，不能生成完整辅助审查报告。")
    assert notice_idx < action_idx < scope_idx, (
        f"行动项在第 {action_idx + 1} 行、评估范围在第 {scope_idx + 1} 行——"
        "审查员要翻到诊断明细里才找到该做什么"
    )
    # A4：行动项之后、评估范围之前必须有分界说明
    divider = "> 以下为诊断明细。**若你只想知道该做什么，看完上面一节即可**。"
    divider_idx = lines.index(divider)
    assert action_idx < divider_idx < scope_idx


def test_action_items_rendered_once_with_pointer_at_original_location() -> None:
    """A2：行动项全篇只出现一次；unknown 归因节原位置留指回行。"""
    md = _render_v4({"O-WALL": "same", "O-DRAIN": "same"})
    assert md.count("### 需要你补充的资料") == 1, (
        "行动项节出现多次——文首已渲染时归因节必须 skip（重复会顶爆 A 门重复行率）"
    )
    pointer = "> 需要你补充的资料已提前列于文首。"
    assert md.count(pointer) == 1
    lines = md.splitlines()
    pointer_idx = lines.index(pointer)
    attribution_idx = next(
        i for i, line in enumerate(lines) if line.startswith("## unknown 归因")
    )
    assert attribution_idx < pointer_idx, "指回行必须留在 unknown 归因节内（原位置）"


def test_empty_action_items_keeps_empty_wording_at_front() -> None:
    """A3：无 professional_input_required 项时，空集文案仍在文首、不留裸标题。"""
    result = _result({"O-WALL": None, "O-DRAIN": None})
    for attr in result.unknown_attribution_by_obligation_id.values():
        attr.responsibility = "system_unresolved"
    md = rw.render_contract_v2_report(
        result,
        world_id="WORLD-TEST",
        building_id="BLD-TEST",
        generated_at="2026-08-01T00:00:00Z",
        analysis_markdown="",
        analysis_is_llm=False,
        contract_version=4,
    )
    assert md.count("### 需要你补充的资料") == 1
    lines = md.splitlines()
    empty_idx = next(
        i for i, line in enumerate(lines) if "本次没有需要你补充的资料" in line
    )
    assert empty_idx < lines.index("## 评估范围"), "空集文案位置仍须在文首"


# ---------------------------------------------------------------------------
# B：类型不相容部位过滤
# ---------------------------------------------------------------------------


def test_authorized_disjoint_fragment_filtered_with_explicit_count() -> None:
    """B1/B3：显式互斥部位被剔出列表，并显式写出剔除条数（不静默消失）。"""
    md = _render_v4({"O-WALL": "same", "O-DRAIN": "authorized_disjoint"})
    assert "`EXTERNAL-WALL-00-01`" in md
    assert "`DRAINAGE-BRANCH-04-04`" not in md, "显式互斥部位仍列在行动项里"
    assert "- 涉及 **1 处**" in md
    assert (
        "<sub>另有 1 处因构件类型与本条款不相容未列出（诊断见结果 JSON）</sub>" in md
    ), "被剔部位必须显式写明条数，不许静默消失"


def test_only_explicit_disjoint_is_filtered() -> None:
    """B2：只剔「显式互斥」——子型相容与判不出关系的一律保留（缺省保守）。"""
    result = _result({})
    kept_relations = (
        "same",
        "category_compatible",  # 卡侧 external_component ⊃ 片段 external_wall
        "different_unresolved",
        "card_unconstrained",
        "identity_unavailable",
        None,  # 老产物无旁路
    )
    for relation in kept_relations:
        result.unknown_attribution_by_obligation_id["O-WALL"] = _attribution(relation)
        incompatible = rw._type_incompatible_obligation_ids(result)
        assert "O-WALL" not in incompatible, (
            f"relation={relation} 被误剔——只有 authorized_disjoint 才许剔"
        )
    result.unknown_attribution_by_obligation_id["O-WALL"] = _attribution(
        "authorized_disjoint"
    )
    assert rw._type_incompatible_obligation_ids(result) == frozenset({"O-WALL"})

    # 渲染层复核：category_compatible 的部位必须仍然列出（字符串不等 ≠ 不相容）
    md = _render_v4({"O-WALL": "category_compatible", "O-DRAIN": "same"})
    assert "`EXTERNAL-WALL-00-01`" in md
    assert "不相容未列出" not in md


def test_judgement_fields_and_ledger_bit_identical_when_filtering() -> None:
    """B4：过滤只改呈现——权威计数、行动项义务计数、完整台账逐位不变。"""
    filtered = _render_v4({"O-WALL": "same", "O-DRAIN": "authorized_disjoint"})
    unfiltered = _render_v4({"O-WALL": "same", "O-DRAIN": None})

    authoritative_prefixes = (
        "- total:", "- open:", "- blocked:", "- closed:", "- satisfied:",
        "- violated:", "- unknown:", "- not_applicable:", "- allow_stop:",
        "- stop_reason:", "- open reason top-5:", "- blocked reason top-5:",
    )

    def authoritative_lines(md: str) -> list[str]:
        return [
            line for line in md.splitlines()
            if line.startswith(authoritative_prefixes)
        ]

    assert authoritative_lines(filtered) == authoritative_lines(unfiltered)

    # 行动项头部义务计数不变（按义务计，不按展示部位计）
    for md in (filtered, unfiltered):
        assert "共 **1 项**，涉及 **2 条义务**" in md
        # 被剔部位的义务仍在完整台账与结果对象里，一条不少
        assert "O-DRAIN" in md
        assert _DRAIN_FRAGMENT in md
