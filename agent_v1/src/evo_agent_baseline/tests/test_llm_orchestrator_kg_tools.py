"""KG 检索 6 tool 单元测试（spec §7.5.2.2）。

直接调 module 级 `_tool_*` 函数（绕过 `run_llm_orchestration` 主循环）单测：

- inspect_obligation：obligation 在 closure_result.obligation_set 里
- lookup_clause：单条 RegulationClause 原文（Neo4j MATCH + truncate）
- lookup_rule_card：RuleCard 核心字段 + source_quotes + cited_clauses
- search_regulation：fulltext index `regulation_clause_text_ft` 查询
- query_fragment：Fragment 主体 + state_counts + conditions
- get_facts_by_slot：从 FactPack 筛 slot_id（不查 KG）

每个 tool 至少覆盖 happy / 找不到 / kg_client 缺 / strip_forbidden 三~四个 case。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from evo_agent_baseline.agent.llm_orchestrator import (
    LLMSessionState,
    _strip_forbidden,
    _tool_get_facts_by_slot,
    _tool_inspect_obligation,
    _tool_lookup_clause,
    _tool_lookup_rule_card,
    _tool_query_fragment,
    _tool_search_regulation,
)
from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    FactAtom,
    FactPack,
    Obligation,
    ObligationSet,
    RuleCardDTO,
    RuleFamilyDTO,
    RuleSlice,
)


# ===========================================================================
# 一、最小 fixture
# ===========================================================================

_RUN_ID = "CAR-KGTOOL"
_WORLD = "W-K"
_BUILDING = "B-K"


def _make_obligation(
    *,
    obligation_id: str = "OBL-fullid-1234567890ABCDEF",
    closure_status: str = "open",
    satisfaction_status: str = "unknown",
    open_reason_code: Optional[str] = "missing_fact",
) -> Obligation:
    return Obligation(
        obligation_id=obligation_id,
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        source_rule_card_id="RC-1",
        source_family_id="fam.x",
        kind="evidence",  # type: ignore[arg-type]
        closure_status=closure_status,  # type: ignore[arg-type]
        satisfaction_status=satisfaction_status,  # type: ignore[arg-type]
        open_reason_code=open_reason_code,  # type: ignore[arg-type]
    )


def _make_closure_with(obligations: List[Obligation]) -> ClosureValidationResult:
    closed = sum(1 for o in obligations if o.closure_status == "closed")
    opened = sum(1 for o in obligations if o.closure_status == "open")
    blocked = sum(1 for o in obligations if o.closure_status == "blocked")
    summary = ClosureSummary(
        total_obligations=len(obligations),
        closed_count=closed,
        open_count=opened,
        blocked_count=blocked,
        satisfied_count=0,
        violated_count=0,
        unknown_count=opened + blocked,
        not_applicable_count=0,
        open_reason_counts={},
        blocked_reason_counts={},
        rule_card_count=1,
        family_count=1,
        fragment_count=0,
        allow_stop=False,
        stop_reason="open_obligations_remain",
    )
    obligation_set = ObligationSet(
        obligation_set_id="OS-1",
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        created_at="2026-05-24T00:00:00Z",
        rulecard_bundle_id="rule_card_v2",
        verifier_version="vtest",
        obligations=obligations,
        derivation_policy={},
    )
    return ClosureValidationResult(
        run_id=_RUN_ID,
        obligation_set=obligation_set,
        closure_summary=summary,
        allow_stop=False,
        allow_report_generation=False,
        high_risk_items=[],
        machine_readable_report={},
    )


def _make_fact_pack_with(facts: List[FactAtom]) -> FactPack:
    slot_idx: Dict[str, List[str]] = {}
    measure_idx: Dict[str, List[str]] = {}
    carrier_idx: Dict[str, List[str]] = {}
    for f in facts:
        if f.slot_id:
            slot_idx.setdefault(f.slot_id, []).append(f.fact_id)
        if f.measure_key:
            measure_idx.setdefault(f.measure_key, []).append(f.fact_id)
        carrier_idx.setdefault(f.carrier_id, []).append(f.fact_id)
    return FactPack(
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        facts=facts,
        slot_index=slot_idx,
        measure_index=measure_idx,
        carrier_index=carrier_idx,
        source_tables=["buildings.parquet"],
    )


def _make_fact(
    *,
    fact_id: str,
    slot_id: Optional[str] = None,
    carrier_id: str = _BUILDING,
) -> FactAtom:
    return FactAtom(
        fact_id=fact_id,
        world_id=_WORLD,
        building_id=_BUILDING,
        carrier_type="building",
        carrier_id=carrier_id,
        target_ref=None,
        slot_id=slot_id,
        measure_key=None,
        value_json="42",
        value_type="number",
        unit="year",
        source_path="buildings.parquet",
        source_node_id=f"N-{fact_id}",
    )


def _make_state(
    *,
    closure_result: Optional[ClosureValidationResult] = None,
    fact_pack: Optional[FactPack] = None,
    kg_client: Optional[Any] = None,
) -> LLMSessionState:
    return LLMSessionState(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        fact_pack=fact_pack,
        rule_slice=None,
        closure_result=closure_result,
        kg_client=kg_client,
    )


# ===========================================================================
# 二、inspect_obligation
# ===========================================================================


def test_inspect_obligation_happy_full_id():
    """obligation 在 closure_result，传完整 id → 返回完整 JSON。"""
    obl = _make_obligation(obligation_id="OBL-FULLID-XYZ")
    state = _make_state(closure_result=_make_closure_with([obl]))

    result = _tool_inspect_obligation(state, {"obligation_id": "OBL-FULLID-XYZ"})
    payload = json.loads(result)
    assert payload["obligation_id"] == "OBL-FULLID-XYZ"
    assert payload["closure_status"] == "open"
    assert payload["satisfaction_status"] == "unknown"
    assert payload["open_reason_code"] == "missing_fact"


def test_inspect_obligation_prefix_match():
    """传入 12 字符前缀 → 匹配到完整 obligation。"""
    obl = _make_obligation(obligation_id="OBL-PREFIXMATCH-1234567890")
    state = _make_state(closure_result=_make_closure_with([obl]))

    # 取首 12 个字符
    prefix = "OBL-PREFIXMA"
    assert len(prefix) == 12
    result = _tool_inspect_obligation(state, {"obligation_id": prefix})
    payload = json.loads(result)
    assert payload["obligation_id"] == "OBL-PREFIXMATCH-1234567890"


def test_inspect_obligation_not_found():
    """传入不存在 id → error JSON。"""
    obl = _make_obligation(obligation_id="OBL-A")
    state = _make_state(closure_result=_make_closure_with([obl]))

    result = _tool_inspect_obligation(state, {"obligation_id": "OBL-NOSUCH"})
    payload = json.loads(result)
    assert "error" in payload


def test_inspect_obligation_empty_id_returns_error():
    obl = _make_obligation(obligation_id="OBL-A")
    state = _make_state(closure_result=_make_closure_with([obl]))

    result = _tool_inspect_obligation(state, {"obligation_id": ""})
    payload = json.loads(result)
    assert "error" in payload


def test_inspect_obligation_no_closure_returns_error():
    """closure_result None → error。"""
    state = _make_state(closure_result=None)
    result = _tool_inspect_obligation(state, {"obligation_id": "OBL-A"})
    payload = json.loads(result)
    assert "error" in payload


def test_inspect_obligation_strip_forbidden_is_applied():
    """直接验 _strip_forbidden：dict 含 expected_verdict 等被剥掉。

    Obligation Pydantic model 字段层不允许 expected_verdict，无法直接构造测
    leakage 路径。本 case 用 _strip_forbidden 直接验证防线行为（实现细节
    见 _tool_inspect_obligation 内部 `payload = _strip_forbidden(payload)`）。
    """
    payload = {
        "obligation_id": "OBL-A",
        "expected_verdict": "pass",
        "projection_id": "P-1",
        "projection_family": "F",
        "selected_family": "F",
        "basis_items": [{"x": 1}],
        "coverage_status": "covered",
        "kind": "evidence",
    }
    cleaned = _strip_forbidden(payload)
    assert "expected_verdict" not in cleaned
    assert "projection_id" not in cleaned
    assert "projection_family" not in cleaned
    assert "selected_family" not in cleaned
    assert "basis_items" not in cleaned
    assert "coverage_status" not in cleaned
    # 合法字段保留
    assert cleaned["obligation_id"] == "OBL-A"
    assert cleaned["kind"] == "evidence"


# ===========================================================================
# 三、lookup_clause
# ===========================================================================


def test_lookup_clause_happy():
    """mock Neo4jClient 返回一行 → 返回 JSON 含 heading / text。"""
    kg = MagicMock()
    kg.run.return_value = [
        {
            "document_id": "MBIS_CoP_2023",
            "clause_id": "MBIS_CoP_2023.5.2.3",
            "heading": "Pull-out test requirements",
            "section_id": "5.2.3",
            "level": 3,
            "text": "Each anchor shall be subjected to a pull-out test...",
        }
    ]
    state = _make_state(kg_client=kg)

    result = _tool_lookup_clause(state, {"clause_id": "MBIS_CoP_2023.5.2.3"})
    payload = json.loads(result)
    assert payload["clause_id"] == "MBIS_CoP_2023.5.2.3"
    assert payload["heading"] == "Pull-out test requirements"
    assert "pull-out" in payload["text"].lower()
    assert payload["resolved_via"] == "exact"


def test_lookup_clause_not_found():
    """mock 返回空 → error JSON。"""
    kg = MagicMock()
    kg.run.return_value = []
    state = _make_state(kg_client=kg)

    result = _tool_lookup_clause(state, {"clause_id": "no.such.clause"})
    payload = json.loads(result)
    assert "error" in payload


def test_lookup_clause_section_prefix_unique_hit():
    """精确未中后，2.1.3(o) 降级为 2.1.3 并唯一返回全文。"""
    kg = MagicMock()
    kg.run.side_effect = [
        [],
        [{
            "document_id": "MBIS_CoP_2023",
            "clause_id": "MBIS_CoP_2023::2.1.3_scope#0",
            "heading": "2.1.3 涵蓋範圍",
            "section_id": "2.1.3_scope#0",
            "level": 3,
            "text": "完整條文",
        }],
    ]
    state = _make_state(kg_client=kg)

    payload = json.loads(_tool_lookup_clause(state, {"clause_id": "2.1.3(o)"}))

    assert payload["resolved_via"] == "section_prefix"
    assert payload["text"] == "完整條文"
    assert kg.run.call_args_list[1].args[1] == {
        "section_prefix": "2.1.3", "app_prefix": None,
    }


def test_lookup_clause_section_prefix_multiple_candidates():
    """App 引用保留 App4 约束；多命中只回候选，不擅自选全文。"""
    kg = MagicMock()
    kg.run.side_effect = [
        [],
        [
            {"document_id": "DOC", "clause_id": "DOC::App4_2.2#a",
             "heading": "App4 2.2 A", "section_id": "a", "level": 2, "text": "A"},
            {"document_id": "DOC", "clause_id": "DOC::App4_2.2#b",
             "heading": "App4 2.2 B", "section_id": "b", "level": 2, "text": "B"},
        ],
    ]
    state = _make_state(kg_client=kg)

    payload = json.loads(_tool_lookup_clause(state, {"clause_id": "App4 2.2-2.3"}))

    assert payload["status"] == "ambiguous"
    assert payload["parsed"] == {"app_prefix": "app4", "section_prefix": "2.2"}
    assert len(payload["candidates"]) == 2
    assert all("text" not in candidate for candidate in payload["candidates"])


def test_lookup_clause_section_prefix_zero_hit_is_structured_miss():
    """可解析但无候选时返回结构化 miss，不抛异常。"""
    kg = MagicMock()
    kg.run.side_effect = [[], []]
    state = _make_state(kg_client=kg)

    payload = json.loads(_tool_lookup_clause(state, {"clause_id": "8.9.10(z)"}))

    assert payload["status"] == "miss"
    assert payload["resolved_via"] == "section_prefix"
    assert payload["reason"] == "no_clause_contains_section_prefix"


def test_lookup_clause_text_truncation():
    """mock 返回 text 长度 > 3000 → 末尾 '... [truncated]'。"""
    long_text = "X" * 5000
    kg = MagicMock()
    kg.run.return_value = [
        {
            "document_id": "MBIS_CoP_2023",
            "clause_id": "MBIS_CoP_2023.1.1.1",
            "heading": "Long",
            "section_id": "1.1.1",
            "level": 3,
            "text": long_text,
        }
    ]
    state = _make_state(kg_client=kg)

    result = _tool_lookup_clause(state, {"clause_id": "MBIS_CoP_2023.1.1.1"})
    payload = json.loads(result)
    # 实现行：if len(row["text"]) > 3000: row["text"] = row["text"][:3000] + "... [truncated]"
    assert payload["text"].endswith("[truncated]")
    assert len(payload["text"]) <= 3000 + len("... [truncated]")


def test_lookup_clause_kg_client_none():
    state = _make_state(kg_client=None)
    result = _tool_lookup_clause(state, {"clause_id": "any"})
    payload = json.loads(result)
    assert "error" in payload


def test_lookup_clause_empty_id():
    kg = MagicMock()
    state = _make_state(kg_client=kg)
    result = _tool_lookup_clause(state, {"clause_id": "   "})
    payload = json.loads(result)
    assert "error" in payload


# ===========================================================================
# 四、lookup_rule_card
# ===========================================================================


def test_lookup_rule_card_happy():
    """mock 返回 card + quotes + clauses → 完整 JSON 含 source_quotes / cited_clauses。"""
    kg = MagicMock()

    def _side_effect(cypher: str, params: Dict[str, Any] = None):
        if "RuleCard" in cypher and "HAS_SOURCE_QUOTE" not in cypher and "CITES_CLAUSE" not in cypher:
            # 主 card 查询
            return [
                {
                    "rule_card_id": "RC-1",
                    "family_id": "fam.x",
                    "phase": "inspection",
                    "subject": "anchor",
                    "regime": None,
                    "primary_actor": "QP",
                    "primary_action": "test",
                    "normalized_rule_text": "示例规则",
                    "source_document_id": "MBIS_CoP_2023",
                    "building_scope": None,
                    "component_scope": None,
                }
            ]
        if "HAS_SOURCE_QUOTE" in cypher:
            return [
                {
                    "sqid": "RC-1::Q1",
                    "text": "Original regulation text...",
                    "language": "en",
                    "page": 42,
                },
                {
                    "sqid": "RC-1::Q2",
                    "text": "原文中文译本...",
                    "language": "zh",
                    "page": 42,
                },
            ]
        if "CITES_CLAUSE" in cypher:
            return [
                {"clause_id": "MBIS_CoP_2023.5.2.3", "heading": "Pull-out test"},
            ]
        return []

    kg.run.side_effect = _side_effect
    state = _make_state(kg_client=kg)

    result = _tool_lookup_rule_card(state, {"rule_card_id": "RC-1"})
    payload = json.loads(result)
    assert payload["rule_card_id"] == "RC-1"
    assert payload["family_id"] == "fam.x"
    assert isinstance(payload["source_quotes"], list)
    assert len(payload["source_quotes"]) == 2
    assert isinstance(payload["cited_clauses"], list)
    assert payload["cited_clauses"][0]["clause_id"] == "MBIS_CoP_2023.5.2.3"


def test_lookup_rule_card_not_found():
    kg = MagicMock()
    kg.run.return_value = []  # 主 card 查询返回空
    state = _make_state(kg_client=kg)

    result = _tool_lookup_rule_card(state, {"rule_card_id": "RC-NOSUCH"})
    payload = json.loads(result)
    assert "error" in payload


def test_lookup_rule_card_kg_client_none():
    state = _make_state(kg_client=None)
    result = _tool_lookup_rule_card(state, {"rule_card_id": "RC-1"})
    payload = json.loads(result)
    assert "error" in payload


def test_lookup_rule_card_empty_id():
    kg = MagicMock()
    state = _make_state(kg_client=kg)
    result = _tool_lookup_rule_card(state, {"rule_card_id": ""})
    payload = json.loads(result)
    assert "error" in payload


# ===========================================================================
# 五、search_regulation
# ===========================================================================


def test_search_regulation_happy():
    """mock 返回 top-K hits → JSON 含 hits 数组。"""
    kg = MagicMock()
    kg.run.return_value = [
        {
            "clause_id": "MBIS_CoP_2023.5.2.3",
            "heading": "Pull-out test",
            "document_id": "MBIS_CoP_2023",
            "preview": "Each anchor shall be subjected to a pull-out test...",
            "score": 4.5,
        },
        {
            "clause_id": "MBIS_CoP_2023.5.2.4",
            "heading": "Test frequency",
            "document_id": "MBIS_CoP_2023",
            "preview": "Tests shall be performed every cycle...",
            "score": 3.1,
        },
    ]
    state = _make_state(kg_client=kg)

    result = _tool_search_regulation(state, {"query": "pull test", "top_k": 5})
    payload = json.loads(result)
    assert payload["query"] == "pull test"
    assert "hits" in payload
    assert len(payload["hits"]) == 2
    assert payload["hits"][0]["clause_id"] == "MBIS_CoP_2023.5.2.3"


def test_search_regulation_empty_query():
    kg = MagicMock()
    state = _make_state(kg_client=kg)
    result = _tool_search_regulation(state, {"query": "  "})
    payload = json.loads(result)
    assert "error" in payload


def test_search_regulation_kg_client_none():
    state = _make_state(kg_client=None)
    result = _tool_search_regulation(state, {"query": "anything"})
    payload = json.loads(result)
    assert "error" in payload


def test_search_regulation_top_k_zero_clamped_to_min():
    """top_k=0 → clamp 到 min_value=1（Codex finding #6 修复后语义）。

    旧实现 `int(args.get("top_k") or 5)` 把 0 当 falsy 短路成 default 5；
    新 `_parse_int_arg` 统一把 0 当合法整数 clamp 到 [1, 20]。
    """
    kg = MagicMock()
    kg.run.return_value = []
    state = _make_state(kg_client=kg)
    result = _tool_search_regulation(state, {"query": "x", "top_k": 0})
    payload = json.loads(result)
    # top_k=0 clamp 到 min_value=1
    assert payload["top_k"] == 1


def test_search_regulation_top_k_clamps_negative():
    """top_k=-3 → clamp 到 1。"""
    kg = MagicMock()
    kg.run.return_value = []
    state = _make_state(kg_client=kg)
    result = _tool_search_regulation(state, {"query": "x", "top_k": -3})
    payload = json.loads(result)
    assert payload["top_k"] == 1


def test_search_regulation_top_k_clamps_high():
    """top_k=21 → clamp 到 20。"""
    kg = MagicMock()
    kg.run.return_value = []
    state = _make_state(kg_client=kg)
    result = _tool_search_regulation(state, {"query": "x", "top_k": 21})
    payload = json.loads(result)
    assert payload["top_k"] == 20


# ===========================================================================
# 六、query_fragment
# ===========================================================================


def test_query_fragment_happy():
    """mock 返回 head row + state_counts + conditions → 完整 JSON。"""
    kg = MagicMock()

    def _side_effect(cypher: str, params: Dict[str, Any] = None):
        if "OF_COMPONENT" in cypher:
            # 主 head 查询
            return [
                {
                    "fragment_id": "FRAG-1",
                    "fragment_role": "external_wall",
                    "in_scope": True,
                    "exclusion_reason": None,
                    "building_id": _BUILDING,
                    "component_id": "C-1",
                    "component_type": "wall",
                    "location_class": "exterior",
                    "exposure_zone": "marine",
                }
            ]
        if "count(DISTINCT d)" in cypher:
            return [
                {
                    "driver_count": 1,
                    "mechanism_count": 2,
                    "condition_count": 1,
                    "repair_count": 0,
                }
            ]
        if "HAS_CONDITION" in cypher and "co.condition_id" in cypher:
            return [
                {
                    "condition_id": "CON-1",
                    "condition_class": "spalling",
                    "severity_band": "moderate",
                    "severity_index": 0.6,
                }
            ]
        return []

    kg.run.side_effect = _side_effect
    state = _make_state(kg_client=kg)

    result = _tool_query_fragment(state, {"fragment_id": "FRAG-1"})
    payload = json.loads(result)
    assert payload["fragment_id"] == "FRAG-1"
    assert payload["component_id"] == "C-1"
    # state_counts 嵌套结构
    assert "state_counts" in payload
    assert payload["state_counts"]["driver_count"] == 1
    # conditions 列表
    assert isinstance(payload["conditions"], list)
    assert payload["conditions"][0]["condition_id"] == "CON-1"


def test_query_fragment_not_found():
    kg = MagicMock()
    kg.run.return_value = []
    state = _make_state(kg_client=kg)

    result = _tool_query_fragment(state, {"fragment_id": "FRAG-NOSUCH"})
    payload = json.loads(result)
    assert "error" in payload


def test_query_fragment_kg_client_none():
    state = _make_state(kg_client=None)
    result = _tool_query_fragment(state, {"fragment_id": "FRAG-1"})
    payload = json.loads(result)
    assert "error" in payload


def test_query_fragment_empty_id():
    kg = MagicMock()
    state = _make_state(kg_client=kg)
    result = _tool_query_fragment(state, {"fragment_id": ""})
    payload = json.loads(result)
    assert "error" in payload


# ===========================================================================
# 七、get_facts_by_slot
# ===========================================================================


def test_get_facts_by_slot_happy():
    """fact_pack 含目标 slot 的 fact → 返回 facts 列表。"""
    f1 = _make_fact(fact_id="F-1", slot_id="slot.building.age")
    f2 = _make_fact(fact_id="F-2", slot_id="slot.other")
    f3 = _make_fact(fact_id="F-3", slot_id="slot.building.age")
    state = _make_state(fact_pack=_make_fact_pack_with([f1, f2, f3]))

    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.building.age", "top_k": 10})
    payload = json.loads(result)
    assert payload["slot_id"] == "slot.building.age"
    assert payload["fact_count"] == 2
    assert {item["fact_id"] for item in payload["facts"]} == {"F-1", "F-3"}


def test_get_facts_by_slot_nonexistent_slot():
    f1 = _make_fact(fact_id="F-1", slot_id="slot.building.age")
    state = _make_state(fact_pack=_make_fact_pack_with([f1]))

    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.nonexistent"})
    payload = json.loads(result)
    assert payload["fact_count"] == 0
    assert payload["facts"] == []


def test_get_facts_by_slot_top_k_zero_clamped_to_min():
    """top_k=0 → clamp 到 min_value=1（Codex finding #6 修复后语义）。

    旧实现 `int(args.get("top_k") or 10)` 把 0 当 falsy 短路成 default 10；
    新 `_parse_int_arg` 统一把 0 当合法整数 clamp 到 [min, max] —— 见
    `tests/test_llm_orchestrator_arg_validation.py::test_query_open_zero_limit_clamped_to_one`
    同样行为。
    """
    facts = [_make_fact(fact_id=f"F-{i}", slot_id="slot.x") for i in range(5)]
    state = _make_state(fact_pack=_make_fact_pack_with(facts))

    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.x", "top_k": 0})
    payload = json.loads(result)
    # top_k=0 clamp 到 1 → 顶多返回 1 条
    assert payload["fact_count"] == 1


def test_get_facts_by_slot_top_k_clamps_negative():
    """top_k=-1 → clamp 到 1。"""
    facts = [_make_fact(fact_id=f"F-{i}", slot_id="slot.x") for i in range(5)]
    state = _make_state(fact_pack=_make_fact_pack_with(facts))

    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.x", "top_k": -1})
    payload = json.loads(result)
    assert payload["fact_count"] == 1


def test_get_facts_by_slot_top_k_clamps_high():
    """top_k=51 → clamp 到 50。"""
    facts = [_make_fact(fact_id=f"F-{i}", slot_id="slot.x") for i in range(60)]
    state = _make_state(fact_pack=_make_fact_pack_with(facts))

    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.x", "top_k": 51})
    payload = json.loads(result)
    # 实现 clamp 到 50
    assert payload["fact_count"] == 50


def test_get_facts_by_slot_no_fact_pack_returns_error():
    """fact_pack=None → error。"""
    state = _make_state(fact_pack=None)
    result = _tool_get_facts_by_slot(state, {"slot_id": "slot.x"})
    payload = json.loads(result)
    assert "error" in payload


def test_get_facts_by_slot_empty_slot_id_returns_error():
    f1 = _make_fact(fact_id="F-1", slot_id="slot.x")
    state = _make_state(fact_pack=_make_fact_pack_with([f1]))
    result = _tool_get_facts_by_slot(state, {"slot_id": ""})
    payload = json.loads(result)
    assert "error" in payload


# ===========================================================================
# 八、_strip_forbidden 直接验证（spec §2.2.3 二次防线）
# ===========================================================================


def test_strip_forbidden_removes_all_w2_fields():
    """全列 9 个 forbidden 字段都被剥掉。"""
    payload = {
        "ok_field": "keep",
        "expected_verdict": "pass",
        "projection_id": "P",
        "projection_family": "F",
        "projection_status": "covered",
        "selected_family": "F",
        "basis_items": [{"x": 1}],
        "coverage_status": "ok",
        "raw_projection_ref_hash": "deadbeef",
        "projection_ref_hash": "cafe",
    }
    cleaned = _strip_forbidden(payload)
    for key in (
        "expected_verdict",
        "projection_id",
        "projection_family",
        "projection_status",
        "selected_family",
        "basis_items",
        "coverage_status",
        "raw_projection_ref_hash",
        "projection_ref_hash",
    ):
        assert key not in cleaned
    assert cleaned == {"ok_field": "keep"}


def test_strip_forbidden_empty_dict():
    assert _strip_forbidden({}) == {}


def test_strip_forbidden_no_forbidden_fields():
    payload = {"a": 1, "b": "x"}
    assert _strip_forbidden(payload) == payload


# ===========================================================================
# v4 模式下共享工具回执引导（copilot 终审四轮：不得残留 v3 自由文本引导）
# ===========================================================================


def test_lookup_clause_v4_mode_guidance_has_no_v3_text_coaching(monkeypatch):
    """v4 模式下 lookup_clause 回执不得出现"提交 text"式 v3 引导——
    模型照做会交 v3 形状、被 v4 闸拒绝并耗尽重试预算。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    kg = MagicMock()
    kg.run.return_value = [
        {
            "document_id": "MBIS_CoP_2023",
            "clause_id": "MBIS_CoP_2023.5.2.3",
            "heading": "Pull-out test requirements",
            "section_id": "5.2.3",
            "level": 3,
            "text": "Each anchor shall be subjected to a pull-out test...",
        }
    ]
    state = _make_state(kg_client=kg)
    payload = json.loads(_tool_lookup_clause(state, {"clause_id": "MBIS_CoP_2023.5.2.3"}))
    joined = " ".join(payload["next_actions"])
    assert "提交 text" not in joined
    assert "结构化字段" in joined


def test_get_facts_by_slot_empty_v4_mode_no_report_writing_coaching(monkeypatch):
    """v4 模式下 slot 无 fact 的回执不得叫模型"在报告里写明"——v4 模型不写报告。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    f1 = _make_fact(fact_id="F-1", slot_id="slot.building.age")
    state = _make_state(fact_pack=_make_fact_pack_with([f1]))
    payload = json.loads(_tool_get_facts_by_slot(state, {"slot_id": "slot.nonexistent"}))
    joined = " ".join(payload["next_actions"])
    assert "报告里写明" not in joined
    assert "结构化字段" in joined
    assert "不要编造" in joined


def test_get_facts_by_slot_hit_v4_mode_no_free_prose_value_coaching(monkeypatch):
    """v4 模式下命中分支不得叫模型把具体值"原样作分析论据"——v4 四字段
    无法表达自由撰写（copilot 终审五轮中#3：新测试曾只盖空结果分支）。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    f1 = _make_fact(fact_id="F-1", slot_id="slot.building.age")
    state = _make_state(fact_pack=_make_fact_pack_with([f1]))
    payload = json.loads(_tool_get_facts_by_slot(state, {"slot_id": "slot.building.age"}))
    assert payload["fact_count"] == 1
    joined = " ".join(payload["next_actions"])
    assert "原样作分析论据" not in joined
    assert "F 别名" in joined
