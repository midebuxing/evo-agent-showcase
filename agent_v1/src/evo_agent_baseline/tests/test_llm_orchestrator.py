"""LLM-as-brain 编排器主循环 + 叙述节闸单测（spec §7.5 + 报告契约 v2）。

测试 `run_llm_orchestration()` 的公共契约：

- spec §7.5.2 主流程 5 + KG 检索深入 6 共 11 tool 顺序编排；
- 报告契约 v2：submit_analysis 提交分析节 → narrative_guard 四检查 → 局部重试
  → 程序骨架 + 唯一槽位组合终稿 → 组合输出守卫；finalize_report 迁移别名兼容；
- spec §7.5.5 deterministic fallback（max_iterations / 未提交时强制 backbone
  + 确定性叙述模板）；
- spec §1.0 原则 1：deterministic backbone 不可被 LLM 覆盖；
- spec §2.2.3 blind 红线：tool 返回前 strip W2 forbidden 字段；
- stuck retry（无 tool_call / 无 text → 引导 + MAX_STUCK_RETRIES）。

测试策略（per 任务要求）：
- LLMClient 用 `MagicMock` 替身（绕过 openai SDK + 活体 Ollama 依赖）；
- retrieval_fn / closure_fn 用 lambda 返回 `_make_*` 最小合法 Pydantic 实例；
- Neo4jClient 用 `MagicMock`，`.run(cypher, params)` 配 side_effect 按 cypher
  关键字返回 mock 行；
- 不硬编码 tool 返回 dict shape（A 在加 next_actions hint）—— 改成 "key in result"。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from evo_agent_baseline.agent.llm_client import LLMConfig, LLMTurn, load_system_prompt
import evo_agent_baseline.agent.llm_orchestrator as llm_orchestrator_module
import evo_agent_baseline.agent.run_orchestrator as run_orchestrator_module
from evo_agent_baseline.agent.report_writer import (
    render_structured_narrative_points,
    build_narrative_evidence_pack,
)
from evo_agent_baseline.agent.run_orchestrator import RunOrchestrator
from evo_agent_baseline.agent.llm_orchestrator import (
    SUBMISSION_FORMAT_ERROR_CODES,
    LLMSessionState,
    _narrative_system_prompt,
    _set_fallback_reason,
    _execute_tool,
    narrative_guard,
    parse_synthesized_submission,
    run_llm_orchestration,
    validate_submission_payload,
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


@pytest.fixture
def tmp_path(request):
    """受限 Windows 沙箱下使用 workspace 内的测试目录。"""
    path = Path.cwd() / "杂物箱" / "pytest_v3_paths" / request.node.name
    path.mkdir(parents=True, exist_ok=True)
    return path


# ===========================================================================
# 一、最小合法 Pydantic 实例工厂（参考 test_agent_control.py 同款）
# ===========================================================================

_RUN_ID = "CAR-20260524T000000-llmorch"
_WORLD = "W-LLM-1"
_BUILDING = "B-LLM-1"


def _make_fact_pack(run_id: str = _RUN_ID) -> FactPack:
    fact = FactAtom(
        fact_id="F-1",
        world_id=_WORLD,
        building_id=_BUILDING,
        carrier_type="building",
        carrier_id=_BUILDING,
        target_ref=None,
        slot_id="slot.building.age",
        measure_key=None,
        value_json="42",
        value_type="number",
        unit="year",
        source_path="buildings.parquet",
        source_node_id="N-1",
    )
    return FactPack(
        run_id=run_id,
        world_id=_WORLD,
        building_id=_BUILDING,
        facts=[fact],
        slot_index={"slot.building.age": ["F-1"]},
        measure_index={},
        carrier_index={_BUILDING: ["F-1"]},
        source_tables=["buildings.parquet"],
    )


def _make_rule_slice(run_id: str = _RUN_ID) -> RuleSlice:
    card = RuleCardDTO(
        rule_card_id="RC-1",
        source_document_id="MBIS_CoP_2023",
        normalized_rule_text="示例规则文本。",
        family_id="mbis.test.family",
    )
    family = RuleFamilyDTO(
        family_id="mbis.test.family",
        family_name="测试族",
    )
    return RuleSlice(
        run_id=run_id,
        rulecard_bundle_id="rule_card_v2",
        candidate_rule_cards=[card],
        rule_families=[family],
        semantic_slots=[],
        measures=[],
        artifacts=[],
        time_anchors=[],
        source_quotes=[],
        retrieval_policy={},
    )


def _make_obligation(
    *,
    obligation_id: str = "OBL-1",
    closure_status: str = "closed",
    satisfaction_status: str = "satisfied",
    open_reason_code: Optional[str] = None,
    blocked_reason_code: Optional[str] = None,
    rule_card_id: str = "RC-1",
) -> Obligation:
    return Obligation(
        obligation_id=obligation_id,
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        source_rule_card_id=rule_card_id,
        source_family_id="mbis.test.family",
        kind="evidence",  # type: ignore[arg-type]
        closure_status=closure_status,  # type: ignore[arg-type]
        satisfaction_status=satisfaction_status,  # type: ignore[arg-type]
        open_reason_code=open_reason_code,  # type: ignore[arg-type]
        blocked_reason_code=blocked_reason_code,  # type: ignore[arg-type]
    )


def _make_closure_result(
    *,
    allow_stop: bool,
    obligations: Optional[List[Obligation]] = None,
    run_id: str = _RUN_ID,
) -> ClosureValidationResult:
    obligations = obligations or [_make_obligation(obligation_id="OBL-CLOSED-1")]
    closed = sum(1 for o in obligations if o.closure_status == "closed")
    opened = sum(1 for o in obligations if o.closure_status == "open")
    blocked = sum(1 for o in obligations if o.closure_status == "blocked")
    satisfied = sum(1 for o in obligations if o.satisfaction_status == "satisfied")
    violated = sum(1 for o in obligations if o.satisfaction_status == "violated")
    unknown = sum(1 for o in obligations if o.satisfaction_status == "unknown")
    na = sum(1 for o in obligations if o.satisfaction_status == "not_applicable")

    summary = ClosureSummary(
        total_obligations=len(obligations),
        closed_count=closed,
        open_count=opened,
        blocked_count=blocked,
        satisfied_count=satisfied,
        violated_count=violated,
        unknown_count=unknown,
        not_applicable_count=na,
        open_reason_counts={},
        blocked_reason_counts={},
        rule_card_count=1,
        family_count=1,
        fragment_count=0,
        allow_stop=allow_stop,
        stop_reason="ok" if allow_stop else "open_obligations_remain",
    )
    obligation_set = ObligationSet(
        obligation_set_id="OS-1",
        run_id=run_id,
        world_id=_WORLD,
        building_id=_BUILDING,
        created_at="2026-05-24T00:00:00Z",
        rulecard_bundle_id="rule_card_v2",
        verifier_version="vtest",
        obligations=obligations,
        derivation_policy={},
    )
    return ClosureValidationResult(
        run_id=run_id,
        obligation_set=obligation_set,
        closure_summary=summary,
        allow_stop=allow_stop,
        allow_report_generation=allow_stop,
        high_risk_items=[],
        machine_readable_report={},
    )


# ===========================================================================
# 二、Mock LLMClient 工具
# ===========================================================================


def _make_tool_call(
    name: str, arguments: Optional[Dict[str, Any]] = None, call_id: str = "call-1"
) -> Dict[str, Any]:
    """构造一个 LLMTurn.tool_calls 列表项（OpenAI function calling 协议形态）。"""
    return {
        "id": call_id,
        "name": name,
        "arguments_json": json.dumps(arguments or {}),
    }


def _make_turn(
    *,
    iteration: int = 0,
    text: str = "",
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    finish_reason: str = "tool_calls",
) -> LLMTurn:
    return LLMTurn(
        iteration=iteration,
        response_text=text,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
    )


class _ScriptedLLM:
    """脚本化 mock LLMClient：每次 chat() 按队列吐预制 LLMTurn。

    队列耗尽后重复最后一项（防 MAX_TOOL_ITERATIONS=16 时队列不够长）。
    `config` 暴露 max_tool_iterations，供 orchestrator 读取。
    `chats` 记录每次 chat 的入参，便于断言。
    """

    def __init__(
        self,
        turns: List[LLMTurn],
        max_iterations: int = 16,
    ) -> None:
        self._queue = list(turns)
        self.config = LLMConfig(max_tool_iterations=max_iterations)
        self.chats: List[Dict[str, Any]] = []

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        iteration: int = 0,
    ) -> LLMTurn:
        self.chats.append({"messages": list(messages), "tools": tools, "iteration": iteration})
        if not self._queue:
            # 空响应：触发 stuck 分支。
            return _make_turn(iteration=iteration, text="", tool_calls=[])
        if len(self._queue) == 1:
            # 最后一项重复使用（保证不下溢）。
            return self._queue[0]
        return self._queue.pop(0)


# ===========================================================================
# 三、共享 retrieval/closure stub
# ===========================================================================


def _default_retrieval(world_id: str, building_id: str, run_id: str):
    return _make_fact_pack(run_id), _make_rule_slice(run_id)


def _default_closure_allow_stop_true(rs, fp, cfg):
    return _make_closure_result(allow_stop=True)


def _default_closure_open(rs, fp, cfg):
    obligation = _make_obligation(
        obligation_id="OBL-OPEN-1",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    return _make_closure_result(allow_stop=False, obligations=[obligation])


def _payload(text="建议人工复核该重点项的证据链。", aliases=None):
    return {"points": [{"text": text, "evidence_aliases": aliases or ["O1"]}]}


def _open_state() -> LLMSessionState:
    state = LLMSessionState(world_id=_WORLD, building_id=_BUILDING, run_id=_RUN_ID)
    state.fact_pack = _make_fact_pack()
    state.rule_slice = _make_rule_slice()
    state.closure_result = _default_closure_open(None, None, None)
    state.evidence_pack = build_narrative_evidence_pack(
        state.closure_result, state.rule_slice, state.fact_pack
    )
    return state


def _status_state(obligations: List[Obligation]) -> LLMSessionState:
    state = LLMSessionState(world_id=_WORLD, building_id=_BUILDING, run_id=_RUN_ID)
    state.fact_pack = _make_fact_pack()
    state.rule_slice = _make_rule_slice()
    state.closure_result = _make_closure_result(
        allow_stop=all(item.closure_status == "closed" for item in obligations),
        obligations=obligations,
    )
    state.evidence_pack = build_narrative_evidence_pack(
        state.closure_result, state.rule_slice, state.fact_pack
    )
    return state


def _status_details(payload, state):
    rejection = next(
        (
            item
            for item in narrative_guard(payload, state)
            if item["code"] == "status_escalation"
        ),
        None,
    )
    return [] if rejection is None else rejection["detail"]


def _exec(payload, state=None, tool_name="submit_analysis"):
    return _execute_tool(
        tool_name=tool_name,
        args=payload,
        state=state or _open_state(),
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        verifier_config=None,
    )


def test_v4_submission_accepted_and_rendered_through_orchestrator(monkeypatch):
    """报告契约 v4 经 orchestrator 接纳,版本号为 4,accepted_payload 带 contract。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")  # v4 分派绑活动模式(copilot 审#1)
    state = _open_state()
    v4 = {"contract": "report_contract_v4",
          "points": [{"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
                      "selected_fact_aliases": [],
                      "review_action_code": "OBTAIN_MISSING_EVIDENCE"}]}
    text, _ = _exec(v4, state)
    result = json.loads(text)
    assert result["status"] == "analysis_received"
    assert result["report_contract_version"] == 4
    assert state.accepted_payload["contract"] == "report_contract_v4"
    assert state.accepted_payload["points"][0]["obligation_alias"] == "O1"


def test_v4_free_text_field_rejected_through_orchestrator(monkeypatch):
    """核心安全属性:经 orchestrator 提交时,任何自由文本字段整篇拒绝——错释义无处藏。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    state = _open_state()
    v4 = {"contract": "report_contract_v4",
          "points": [{"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
                      "selected_fact_aliases": [],
                      "review_action_code": "OBTAIN_MISSING_EVIDENCE",
                      "text": "规则要求每周至少检查一次"}]}  # 试图注入规则语义
    text, _ = _exec(v4, state)
    result = json.loads(text)
    # 首次提交被拒(未耗尽)或耗尽兜底,两种都不接纳且带 additional_properties
    assert result.get("rejected") is True or result["status"].endswith("fallback")
    assert "additional_properties" in result.get("rejection_codes", [])
    assert state.accepted_payload is None


def test_v4_mode_rejects_v3_shaped_submission(monkeypatch):
    """致命防护(copilot 审#1):v4 模式下,v3 形状载荷(无 contract/有 text)不得
    漏到 v3 路径被接纳——否则自由文本 gloss 重入。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    state = _open_state()
    v3_shaped = {"points": [{"text": "规则要求每周检查", "evidence_aliases": ["O1"]}]}
    text, _ = _exec(v3_shaped, state)
    result = json.loads(text)
    # 走 v4 校验被拒(wrong_contract/缺字段),不接纳
    assert state.accepted_payload is None
    assert result.get("status") != "analysis_received"


def test_v4_mode_submit_directive_is_v4_not_v3(monkeypatch):
    """v4 模式下,闭包后提交引导必须是 v4（含 report_contract_v4/suggested_analysis_code），
    不得仍发 v3 的 text/evidence_aliases 指令（copilot 审#2：主循环引导曾仍 v3）。"""
    from evo_agent_baseline.agent.llm_orchestrator import _key_items_submit_directive
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    state = _open_state()
    directive = _key_items_submit_directive(state.evidence_pack)
    assert "report_contract_v4" in directive
    assert "suggested_analysis_code" in directive
    assert "evidence_aliases 已绑定" not in directive  # 不发 v3 措辞


def test_v3_path_unaffected_by_v4_dispatch():
    """无 contract 字段的 v3 提交仍走 v3 路径、版本号 3。"""
    state = _open_state()
    text, _ = _exec(_payload(), state)
    result = json.loads(text)
    assert result["status"] == "analysis_received"
    assert result["report_contract_version"] == 3


def test_format_error_enum_matches_frozen_list():
    # 精确冻结 19 个格式码的成员与顺序（tuple 比较），与 11 叙述拒码同规格——
    # 只用 len+set 会漏掉顺序漂移（顺序参与冻结/对账口径）。
    assert SUBMISSION_FORMAT_ERROR_CODES == (
        "invalid_json",
        "no_fence",
        "multi_fence",
        "bad_fence_language",
        "trailing_tokens",
        "duplicate_key",
        "root_not_object",
        "missing_points",
        "points_type",
        "empty_points",
        "too_many_points",
        "point_field_missing",
        "point_field_type",
        "text_too_long",
        "text_multiline",
        "alias_count",
        "alias_duplicate",
        "alias_in_text",
        "legacy_input_unsupported",
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("plain", "no_fence"),
        ("```JSON\n{}\n```", "bad_fence_language"),
        ("```json\n{]\n```", "invalid_json"),
        ("```json\n{} []\n```", "trailing_tokens"),
        ('```json\n{"points":[],"points":[]}\n```', "duplicate_key"),
        ("```json\n{}\n```\n```\n{}\n```", "multi_fence"),
    ],
)
def test_synthesized_parser_error_representatives(text, code):
    _, errors = parse_synthesized_submission(text)
    assert errors[0]["error_code"] == code
    assert set(errors[0]) == {"error_code", "json_pointer", "expected", "actual", "fix_hint"}
    assert text not in errors[0]["actual"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ([], "root_not_object"),
        ({}, "missing_points"),
        ({"points": "x"}, "points_type"),
        ({"points": []}, "empty_points"),
        ({"points": [_payload()["points"][0]] * 25}, "too_many_points"),
        ({"points": [{}]}, "point_field_missing"),
        ({"points": [{"text": 1, "evidence_aliases": ["O1"]}]}, "point_field_type"),
        ({"points": [{"text": "x" * 501, "evidence_aliases": ["O1"]}]}, "text_too_long"),
        ({"points": [{"text": "a\nb", "evidence_aliases": ["O1"]}]}, "text_multiline"),
        ({"points": [{"text": "x", "evidence_aliases": []}]}, "alias_count"),
        ({"points": [{"text": "引用 [O1] 与 R2", "evidence_aliases": ["O1"]}]}, "alias_in_text"),
    ],
)
def test_payload_error_representatives(payload, code):
    _, errors = validate_submission_payload(payload)
    assert code in {item["error_code"] for item in errors}
    assert len(errors) <= 5
    assert all("引用 [O1] 与 R2" not in item["actual"] for item in errors)


def test_duplicate_aliases_are_normalized_not_rejected():
    """重复别名确定性去重后放行；数量超限仍必须拒绝（闸不放水）。

    背景：同一别名列两遍不携带额外语义，要求模型手工去重考不出分析质量，
    只白耗有限的格式修复预算（2026-07-20 实证：某栋两次尝试都卡在
    alias_duplicate，内容其实在收敛）。故程序去重；但拆点是模型该做的语义
    判断，alias_count 超限仍拒绝。
    """
    payload = {"points": [{"text": "x", "evidence_aliases": ["O1", "R2", "O1"]}]}
    normalized, errors = validate_submission_payload(payload)
    assert errors == []
    assert normalized is not None
    # 去重保序，且真的写回了 payload
    assert payload["points"][0]["evidence_aliases"] == ["O1", "R2"]

    # 超过 8 个（去重后仍超）必须拒绝，不得被"顺手截断"放行
    too_many = {"points": [{"text": "x", "evidence_aliases":
                            [f"O{i}" for i in range(1, 11)]}]}
    _, errors = validate_submission_payload(too_many)
    assert "alias_count" in {e["error_code"] for e in errors}


def test_alias_in_text_hint_names_offending_tokens_and_current_bindings():
    """回执点名违规 token **并列出本点当前绑定**，但仍不回显模型原文。

    列出绑定是实证改动（收官批 PODIUM-0043 点23）：模型把相邻编号搞串
    （正文 O17、绑定 O24）后两次重试都没修对——旧回执只说"提及了未绑定的
    O17"、不给它看自己绑了什么，模型无从判断该改正文还是改绑定。
    绑定别名是已过 ^[ORF][0-9]+$ 校验的结构化值，列出不构成原文回显。
    """
    authored_text = "引用 [O1] 后比较 R2，并再次查看 O1。"
    _, errors = validate_submission_payload(_payload(authored_text))
    alias_error = next(item for item in errors if item["error_code"] == "alias_in_text")
    assert alias_error["fix_hint"] == (
        "text 提及了未绑定在本点的别名：R2；"
        "本点当前绑定：O1。请核对：若是 text 编号写错，"
        "改为绑定中的正确编号；仅当提及编号所指证据确属本点论据时，"
        "才把它加入 evidence_aliases，不得为通过校验而机械追加；"
        "二者皆非则从 text 中删去该编号。大小写变体须改正。"
    )
    assert authored_text not in alias_error["actual"]
    # 原文回显探测：正文里的散文词(如"引用")不得出现在回执中
    assert "引用" not in alias_error["fix_hint"]
    # 补绑定的指引必须带语义归属条件——不带条件的"把它加入"会诱导模型在错
    # 编号恰为另一条真实证据时机械追加过闸(2026-07-23 codex 审出)
    assert "确属本点论据" in alias_error["fix_hint"]
    # 三择完备:编号既非写错又不属本点论据时,"删除"分支必须在(复核轮审出)
    assert "删去该编号" in alias_error["fix_hint"]


def test_aliases_mentioned_in_text_must_be_an_exact_subset_of_point_bindings():
    payload = {
        "points": [
            {
                "text": "重点项 [O1] 缺失事实支持，对应规则卡 R1 仍需复核。",
                "evidence_aliases": ["O1", "R1"],
            }
        ]
    }
    normalized, errors = validate_submission_payload(payload)
    assert errors == []
    assert normalized == payload

    _, errors = validate_submission_payload(
        _payload("重点项 [O1] 还引用 R2。", aliases=["O1"])
    )
    alias_error = next(item for item in errors if item["error_code"] == "alias_in_text")
    assert "R2" in alias_error["fix_hint"]
    # 当前绑定按新契约随回执列出,帮模型区分"正文写错编号"与"绑定缺项"
    assert "本点当前绑定：O1" in alias_error["fix_hint"]


def test_empty_bindings_report_both_count_and_alias_errors_with_empty_receipt():
    """空绑定点：alias_count 与 alias_in_text 并报，回执绑定处显示（空）。

    两错并报而非吞并——模型须同时知道"数量不足"和"正文提及了谁"，
    只报其一会让另一半在下轮重试再撞一次，白耗格式修复预算。
    """
    payload = {"points": [{"text": "重点项 O1 缺失事实支持。", "evidence_aliases": []}]}
    _, errors = validate_submission_payload(payload)
    codes = {item["error_code"] for item in errors}
    assert {"alias_count", "alias_in_text"} <= codes
    alias_error = next(item for item in errors if item["error_code"] == "alias_in_text")
    assert "本点当前绑定：（空）" in alias_error["fix_hint"]


@pytest.mark.parametrize("variant", ["o1", "Ｏ１", "O１"])
def test_alias_variant_is_not_silently_normalized_to_bound_alias(variant):
    _, errors = validate_submission_payload(
        _payload(f"重点项 [{variant}] 需复核。", ["O1"])
    )
    alias_error = next(item for item in errors if item["error_code"] == "alias_in_text")
    assert variant in alias_error["fix_hint"]


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_text_rejects_unicode_line_and_paragraph_separators(separator):
    _, errors = validate_submission_payload(_payload(f"第一段{separator}第二段"))
    assert [item["error_code"] for item in errors] == ["text_multiline"]


def test_text_rejects_cf_as_existing_point_field_type_code():
    _, errors = validate_submission_payload(_payload("需要复\u200b核"))
    assert [item["error_code"] for item in errors] == ["point_field_type"]
    assert "不可见字符" in errors[0]["fix_hint"]


def test_both_submission_paths_accept_same_envelope_and_hash():
    direct_state = _open_state()
    text, finalized = _exec(_payload(), direct_state)
    assert finalized and json.loads(text)["status"] == "analysis_received"
    fenced = "```json\n" + json.dumps(_payload(), ensure_ascii=False) + "\n```"
    turns = [
        _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
        _make_turn(text=fenced, finish_reason="stop"),
    ]
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=_ScriptedLLM(turns, max_iterations=3),
    )
    assert result.accepted_via == "synthesized_json"
    assert result.accepted_point_count == 1
    assert result.accepted_payload_sha256 == direct_state.accepted_payload_sha256
    assert result.report_contract_version == 3


def test_true_tool_call_acceptance_and_deterministic_render_order():
    payload = {
        "points": [
            {"text": "先看 *风险*", "evidence_aliases": ["O1", "R1"]},
            {"text": "再做复核", "evidence_aliases": ["O1"]},
        ]
    }
    state = _open_state()
    _, finalized = _exec(payload, state)
    assert finalized
    rendered = render_structured_narrative_points(payload["points"], state.evidence_pack.alias_map)
    assert rendered.splitlines()[0].startswith(r"- 先看 \*风险\*（证据：[O1:")
    assert "、[R1:RC-1]）" in rendered
    assert rendered.splitlines()[1].startswith("- 再做复核")
    assert state.accepted_via == "tool_call"


def test_structured_render_expands_text_aliases_and_only_tails_supplements():
    state = _open_state()
    points = [
        {
            "text": "重点项 [O1] 缺失事实支持，应对照 R1 复核。",
            "evidence_aliases": ["O1", "R1"],
        },
        {
            "text": "重点项 [O1] 仍需补资料。",
            "evidence_aliases": ["O1", "R1"],
        },
    ]
    rendered = render_structured_narrative_points(points, state.evidence_pack.alias_map)
    first, second = rendered.splitlines()
    assert "[O1:OBL-OPEN-1]" in first
    assert "[R1:RC-1]" in first
    assert "（证据：" not in first
    assert second.endswith("（证据：[R1:RC-1]）")
    assert second.count("[O1:OBL-OPEN-1]") == 1


def test_structured_render_escapes_pseudo_expansion_as_literal_text():
    state = _open_state()
    points = [
        {"text": "不得采信 [O1:伪造ID] 形态。", "evidence_aliases": ["O1"]}
    ]
    normalized, errors = validate_submission_payload({"points": points})
    assert errors == []
    assert normalized is not None
    rendered = render_structured_narrative_points(points, state.evidence_pack.alias_map)
    assert r"\[O1:伪造ID\]" in rendered
    assert rendered.endswith("（证据：[O1:OBL-OPEN-1]）")


def test_meta_commentary_needs_task_context_not_domain_words():
    """shape2 锚点须是任务元语境，不能是合规正文高频歧义词。

    病（2026-07-20 A 批实测）：旧 shape2 = (要求/提示词/规则/禁词/格式) 与
    (按/不使用/避免/只能) **任意共现**即判元评论。但"规则/要求"是合规正文
    必然出现的词、"按"只是普通介词 → 等于禁止模型引述法规内容。实证某栋
    24 点中 23 点合格，仅第 4 点写"违反 R4 规则要求…须按《建筑物条例》标准
    执行"就整篇退回；A 批 3 栋各撞 3 次耗尽重试。

    修法（codex 决策门裁定"第四条路"）：锚点改为明确指向本次任务/输出的词。
    **不加自指主语约束**——汉语常省略主语，"须按提示词格式输出"是真元评论
    却无自指词，强加会确定性漏检。**保留整篇原子接纳**（规格冻结条款）。
    """
    from evo_agent_baseline.agent.llm_orchestrator import _meta_commentary_hits as hits

    # 真元评论必拦（含无主语祈使句——旧方案②会漏这一类）
    for text in (
        "我将按提示词要求输出分析，避免使用禁词。",      # 显式自指
        "须按提示词格式输出。",                          # 无主语祈使
        "只能使用该输出格式。",
        "正文中不要出现禁词。",
        "按系统指令只能提交对象信封。",                  # "对象信封"仍命中"信封"锚点
        "避免提及最终裁决。",                            # 判定结论词作语境
        "此处避免使用「合规」一词。",                    # 元语言式(shape3)
        # 2026-07-23 codex 审出的同义改写漏检，补锚点/行为词后必拦
        "我会按要求撰写以下分析。",                      # 自指+撰写(shape1)
        "根据上述指示，本文仅陈述证据缺口。",            # 上述指示+陈述(shape2)
        "依照前述约束，下面直接给出分析。",              # 前述约束+依照(shape2)
    ):
        assert hits(text), f"真元评论漏检: {text}"

    # 正常合规分析必过（A 批实测被误伤的原句 + 高频歧义表达）
    for text in (
        "完成报告提交状态为 false，违反 R4 规则要求修复工作须按《建筑物条例》标准执行，但 F1 显示报告未完成。",
        "阻塞义务 O23：规则 R21 要求按修复方案施工，但 supervision.record.completed 存在 qualifier_conflict。",
        "应避免违反规则要求。",
        "设备只能使用符合规定格式的记录。",   # 裸"合规"作子串会误伤，故锚点只收长判定词
        "本项不使用不符合标准要求的材料。",
        "按规定格式提交的完工报告缺失，需人工补充。",
        # 2026-07-23 codex 审出的领域碰撞误杀，修后必过
        "监测点列表应按楼层编号整理。",       # "点列表"排除项挡"点列"子串命中
        "建筑信封须按防水标准施工。",         # "建筑信封"排除项
        "设备只能遵循系统指令。",             # 已删"系统指令"锚点(楼宇设备语境撞车)
        "维修人员按系统提示操作设备。",       # 已删"系统提示"锚点
        # 复核轮(同日第二轮)审出的新增词表碰撞，修后必过
        "我方撰写的报告显示外墙存在渗水。",   # "我方"主语排除项挡"我"子串命中
        "上述指示灯应依照维护手册更换。",     # "指示灯"排除项挡"上述指示"
        "前述约束条件应依照建筑条例处理。",   # "约束条件"排除项挡"前述约束"
    ):
        assert not hits(text), f"正常合规分析被误伤: {text}"


def test_markdown_escape_is_minimal_but_still_blocks_structure():
    """转义集须最小：标识符里的 . _ - 不转义，但真结构字符仍必须挡住。

    背景：早前转义集过宽（含 . _ ( ) { } # + ! ~ -），把法规/槽位标识符打成
    `artifact\\.record\\.test\\_or\\_material\\_witness`，单份报告 534 处反斜杠，
    消费者一打开就撞到。收窄后仍须保证伪链接/伪强调/伪代码/行首伪结构不逃逸。
    """
    from evo_agent_baseline.agent.report_writer import _escape_markdown_text as esc

    # 标识符：零转义（可读性）
    for ident in (
        "artifact.record.test_or_material_witness",
        "rc.mbis.repair.drainage.ri.validate.s5_6_5.c01",
        "OBL-OPEN-1",
    ):
        assert esc(ident) == ident, f"标识符不应被转义: {ident}"

    # 行内真结构字符：必须转义
    for raw, must in (
        ("*伪强调*", "\\*"),
        ("[伪链接](x)", "\\["),
        ("`伪代码`", "\\`"),
        ("<script>", "\\<"),
        ("a|b", "\\|"),
        ("反斜杠\\本身", "\\\\"),
    ):
        assert must in esc(raw), f"结构字符必须转义: {raw}"

    # 行首结构标记：必须转义；同字符在行内不转义
    assert esc("# 伪标题").startswith("\\#")
    assert esc("- 伪列表").startswith("\\-")
    assert esc("1. 伪有序").startswith("\\1.")
    assert esc("中间-连字符 a+b x~y") == "中间-连字符 a+b x~y"


def test_format_state_machine_exhaustion_does_not_burn_narrative_budget():
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(text="not fenced", finish_reason="stop"),
            _make_turn(text="not fenced", finish_reason="stop"),
        ],
        max_iterations=4,
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=client,
    )
    assert result.submission_format_attempts == 2
    assert result.submission_format_repairs_used == 1
    assert len(result.submission_format_events) == 2
    assert result.llm_narrative_attempts == 0
    assert result.llm_narrative_rejection_codes == []
    assert result.narrative_fallback_reason == "submission_format_exhausted"


def test_content_audit_survives_later_format_exhaustion():
    state = _open_state()
    text, finalized = _exec(_payload(aliases=["O99"]), state)
    assert not finalized and "unresolved_alias" in text
    legacy_text, finalized = _exec({"analysis_markdown": "ignored"}, state)
    assert not finalized and "legacy_input_unsupported" in legacy_text
    _, finalized = _exec([], state)
    assert finalized
    assert state.narrative_attempts == 1
    assert state.narrative_rejection_codes == ["unresolved_alias"]
    assert state.narrative_fallback_reason == "submission_format_exhausted"


def test_legacy_inputs_are_format_errors_and_deprecated():
    state = _open_state()
    receipt, finalized = _exec({"analysis_markdown": "do not parse"}, state)
    assert not finalized
    body = json.loads(receipt)
    assert body["event"]["errors"][0]["error_code"] == "legacy_input_unsupported"
    assert state.submission_format_repairs_used == 1
    assert state.deprecated_tool_events
    state2 = _open_state()
    receipt2, _ = _exec({"report_markdown": "ignored"}, state2, "finalize_report")
    assert "legacy_input_unsupported" in receipt2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("无法依据现有资料做出最终裁决", []),
        ("尚未结案", []),
        ("可以结案", ["forbidden_phrase"]),
        ("本建筑已合规", ["forbidden_phrase"]),
        ("并非尚未结案", ["forbidden_phrase"]),
    ],
)
def test_rule2_polarity_cases(text, expected):
    state = _open_state()
    codes = [item["code"] for item in narrative_guard(_payload(text), state)]
    assert codes == expected


@pytest.mark.parametrize(
    "text",
    [
        "尚未结案，现已结案",
        "现已结案，尚未结案",
    ],
)
def test_rule2_final_status_checks_every_same_predicate_occurrence(text):
    state = _open_state()
    codes = [item["code"] for item in narrative_guard(_payload(text), state)]
    assert "forbidden_phrase" in codes


def test_rule2_branch_impersonation_only_on_open_branch():
    state = _open_state()
    assert "branch_inconsistent" in {
        item["code"] for item in narrative_guard(_payload("资料齐全"), state)
    }
    assert not narrative_guard(_payload("资料尚未齐全"), state)


@pytest.mark.parametrize(
    "text",
    [
        "尚未生成完整辅助审查报告，现已生成完整辅助审查报告",
        "现已生成完整辅助审查报告，尚未生成完整辅助审查报告",
    ],
)
def test_rule2_branch_status_checks_every_same_predicate_occurrence(text):
    state = _open_state()
    codes = [item["code"] for item in narrative_guard(_payload(text), state)]
    assert "branch_inconsistent" in codes


# ---------------------------------------------------------------------------
# 状态一致性闸（A 案 2026-07-13）：规则 A 降 advisory-only、规则 B 保硬拒。
# 规则 A 候选命中只在最终原子接纳后记 status_escalation_warning 审计，绝不产
# 拒码 / 不烧叙述预算 / 不触发确定性兜底；条件/否定/不确定/承认词不再消警。
# ---------------------------------------------------------------------------


def _advisory_events(payload, state):
    """跑内容层接纳，返回 (回执, 是否 finalize, pending 暂存审计)。

    advisory 在内容层只写入 state.pending_acceptance_audit_events（两阶段接纳的
    第一阶段）；组合终稿守卫的并入发生在 run_llm_orchestration，见 bug6 用例。
    """
    receipt, finalized = _exec(payload, state)
    return receipt, finalized, state.pending_acceptance_audit_events


def test_rule_a_candidate_never_produces_reject_code_or_burns_budget():
    """自查锚：规则 A 候选命中绝不产 status_escalation 拒码、载荷照常接纳。"""
    codes = [
        item["code"]
        for item in narrative_guard(_payload("该义务构成违规。", ["O1"]), _open_state())
    ]
    assert "status_escalation" not in codes
    receipt, finalized, _ = _advisory_events(
        _payload("该义务构成违规。", ["O1"]), _open_state()
    )
    assert finalized
    assert json.loads(receipt)["status"] == "analysis_received"


@pytest.mark.parametrize(
    ("text", "candidate"),
    [
        ("该义务构成违规。", "构成违规"),  # 硬词代表
        ("该义务违反要求。", "违反"),  # 硬词代表
        ("该义务未满足法定要求。", "未满足法定"),  # 规范宾语模式并入候选
        ("该项缺失测量数据。", "缺失"),  # 软词代表
        ("该项无法满足核验精度。", "无法满足"),  # 软词代表
    ],
)
def test_rule_a_advisory_records_warning_on_open_binding(text, candidate):
    """候选命中（硬词/软词各代表）+ 绑定 O 非全 violated → 记 advisory warning。"""
    receipt, finalized, pending = _advisory_events(_payload(text, ["O1"]), _open_state())
    assert finalized
    assert json.loads(receipt)["status"] == "analysis_received"
    assert pending == [
        {
            "event": "status_escalation_warning",
            "attempt_index": 1,
            "advisory_only": True,
            "details": [
                {
                    "point_index": 0,
                    "subtype": "status_escalation_advisory",
                    "advisory_only": True,
                    "candidate_hits": [candidate],
                    "obligation_statuses": {"O1": ["open"]},
                }
            ],
        }
    ]


def test_rule_a_advisory_suppressed_when_all_bound_obligations_violated():
    """全 violated → 断言违规自洽，不记 advisory（全violated→不记）。"""
    state = _status_state(
        [_make_obligation(obligation_id="OBL-V", satisfaction_status="violated")]
    )
    receipt, finalized, pending = _advisory_events(
        _payload("该义务违反要求。", ["O1"]), state
    )
    assert finalized
    assert pending == []


def test_rule_a_advisory_records_on_mixed_nonviolated_binding():
    """violated + open 混绑（非全 violated）→ 记 advisory，保留候选与状态。"""
    state = _status_state(
        [
            _make_obligation(obligation_id="OBL-V", satisfaction_status="violated"),
            _make_obligation(
                obligation_id="OBL-O",
                closure_status="open",
                satisfaction_status="unknown",
                open_reason_code="missing_fact",
            ),
        ]
    )
    receipt, finalized, pending = _advisory_events(
        _payload("相关义务未满足要求。", ["O1", "O2"]), state
    )
    assert finalized
    assert pending[0]["details"][0]["candidate_hits"] == ["未满足要求"]
    assert pending[0]["details"][0]["obligation_statuses"] == {
        "O1": ["violated"],
        "O2": ["open"],
    }


def test_rule_a_advisory_records_when_no_obligation_bound():
    """无 O 绑定（无状态权威可承认）→ 仍记 advisory（无O→记），状态映射为空。"""
    state = _status_state(
        [_make_obligation(obligation_id="OBL-V", satisfaction_status="violated")]
    )
    receipt, finalized, pending = _advisory_events(
        _payload("相关要求已违反。", ["R1"]), state
    )
    assert finalized
    assert pending[0]["details"][0]["candidate_hits"] == ["违反"]
    assert pending[0]["details"][0]["obligation_statuses"] == {}


def test_rule_a_advisory_not_recorded_when_payload_has_another_rejection():
    """载荷另有硬拒（unresolved_alias）→ 未接纳，advisory 不计（pending 空）。"""
    state = _open_state()
    receipt, finalized = _exec(_payload("缺失测量数据。", ["O999"]), state)
    assert not finalized
    assert json.loads(receipt)["rejection_codes"] == ["unresolved_alias"]
    assert state.pending_acceptance_audit_events == []
    assert state.submission_audit_events == []


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("若复核结果未达标，需补充。", "conditional"),  # 条件句不再消警
        ("该项并非未达标，需补充。", "negation"),  # 否定不再消警
        ("该项疑似未达标，需补充。", "uncertainty"),  # 不确定不再消警
        ("该义务处于开放状态且未达标，需补充。", "open_acknowledgement"),  # open承认词不再消警
    ],
)
def test_rule_a_advisory_no_longer_exempts_condition_negation_uncertainty_open(text, label):
    """回归锚（A 案取消消警豁免）：条件/否定/不确定/open承认词命中候选（`未达标`）
    时，规则 A 仍产 status_escalation_warning——锁死"不消警"行为，防将来偷偷加回
    这四类豁免逻辑而测试仍全绿。绑定 O 为 open（非全 violated），故必记 advisory。"""
    receipt, finalized, pending = _advisory_events(_payload(text, ["O1"]), _open_state())
    assert finalized, f"{label} 载荷应被接纳（advisory 不阻塞接纳）"
    assert json.loads(receipt)["status"] == "analysis_received"
    warnings = [e for e in pending if e["event"] == "status_escalation_warning"]
    assert len(warnings) == 1, f"{label} 候选命中必须产 advisory warning，不得被消警豁免"
    assert warnings[0]["advisory_only"] is True
    assert warnings[0]["details"][0]["candidate_hits"] == ["未达标"]
    assert warnings[0]["details"][0]["obligation_statuses"] == {"O1": ["open"]}


def test_status_rule_b_rejects_mixed_satisfied_binding_even_in_contrast_wording():
    state = _status_state(
        [
            _make_obligation(obligation_id="OBL-V", satisfaction_status="violated"),
            _make_obligation(obligation_id="OBL-S", satisfaction_status="satisfied"),
        ]
    )
    # v3 key_items currently focus violated/open/blocked; inject the direct O alias
    # to exercise the defensive satisfied-status path without changing pack selection.
    state.evidence_pack.alias_map["O2"] = "OBL-S"
    payload = _payload("对照来看，两项应分别记录。", ["O1", "O2"])
    details = _status_details(payload, state)
    assert [item["subtype"] for item in details] == ["mixed_satisfied_binding"]
    assert details[0]["hint"] == "拆点或按状态分组绑定"


def test_status_rule_b_burns_narrative_budget_and_keeps_atomic_rejection():
    """规则 B（satisfied 混绑）继续硬拒 status_escalation、烧叙述预算、原子不接纳。"""
    state = _status_state(
        [
            _make_obligation(obligation_id="OBL-V", satisfaction_status="violated"),
            _make_obligation(obligation_id="OBL-S", satisfaction_status="satisfied"),
        ]
    )
    state.evidence_pack.alias_map["O2"] = "OBL-S"
    receipt, finalized = _exec(_payload("两项应分别记录。", ["O1", "O2"]), state)
    assert not finalized
    body = json.loads(receipt)
    assert body["rejection_codes"] == ["status_escalation"]
    assert state.narrative_attempts == 1
    assert state.accepted_payload is None
    assert state.pending_acceptance_audit_events == []


# ---------------------------------------------------------------------------
# bug6：advisory 审计的两阶段原子接纳（内容层暂存 → 终局守卫全过才并入）。
# ---------------------------------------------------------------------------


def _advisory_e2e_run(monkeypatch=None, guard_failures=0):
    """驱动一次 e2e：closure → 提交含候选词的载荷（缺失/open）。

    guard_failures>0 时脚本化 pre_output_language_guard 前 N 次抛错，模拟组合终稿
    守卫撤销接纳；0 则用真守卫（skeleton 通过，advisory 应并入）。
    """
    if monkeypatch is not None and guard_failures:
        calls = 0

        def scripted_guard(text):
            nonlocal calls
            calls += 1
            if calls <= guard_failures:
                raise llm_orchestrator_module.OutputGuardError("forced composition failure")
            return {"guard": "pre_output_language_guard", "passed": True}

        monkeypatch.setattr(
            llm_orchestrator_module, "pre_output_language_guard", scripted_guard
        )
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(
                tool_calls=[
                    _make_tool_call(
                        "submit_analysis", _payload("缺失测量数据，需补充。", ["O1"])
                    )
                ]
            ),
        ],
        max_iterations=3,
    )
    return run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=client,
    )


def test_advisory_merges_exactly_once_on_terminal_acceptance():
    """组合守卫全过、终局 LLM 接纳 → advisory 恰好并入一次，pending 清空。"""
    result = _advisory_e2e_run()
    assert result.llm_narrative_accepted is True
    events = [
        event
        for event in result.state.submission_audit_events
        if event["event"] == "status_escalation_warning"
    ]
    assert len(events) == 1
    assert events[0]["advisory_only"] is True
    assert events[0]["details"][0]["candidate_hits"] == ["缺失"]
    assert result.state.pending_acceptance_audit_events == []


def test_advisory_dropped_when_combined_guard_rejects_acceptance(monkeypatch):
    """内容层接纳但组合守卫失败 → 终态无 status_escalation_warning（pending 已清）。"""
    result = _advisory_e2e_run(monkeypatch, guard_failures=1)
    assert result.llm_narrative_accepted is False
    assert result.narrative_fallback_reason == "combined_output_guard_rejected"
    assert all(
        event["event"] != "status_escalation_warning"
        for event in result.state.submission_audit_events
    )
    assert result.state.pending_acceptance_audit_events == []


def test_advisory_dropped_on_second_stage_degradation(monkeypatch):
    """二次降级（composed_guard_degraded）同样撤销接纳 → 无 advisory warning。"""
    result = _advisory_e2e_run(monkeypatch, guard_failures=2)
    assert result.llm_narrative_accepted is False
    assert result.narrative_fallback_reason == "composed_guard_degraded"
    assert all(
        event["event"] != "status_escalation_warning"
        for event in result.state.submission_audit_events
    )
    assert result.state.pending_acceptance_audit_events == []


def test_outer_stop_gate_failure_strips_terminal_acceptance_audit(monkeypatch):
    """bug6 外层泄漏核心回归锚：内层接纳（advisory 已并入 submission_audit_events、
    accepted_via/sha 已落）后，外层 `post_verifier_stop_gate` 抛错使 run 终态降为
    非接纳 → `_record_orchestrator_exception_narrative_audit` 必须同步清掉
    advisory 审计与接纳指纹（原子接纳），run_audit 不得残留 status_escalation_warning
    或 accepted_via/sha/point_count。"""

    def _boom_stop_gate(closure_result):
        raise RuntimeError("forced outer stop_gate failure")

    monkeypatch.setattr(
        run_orchestrator_module, "post_verifier_stop_gate", _boom_stop_gate
    )
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(
                tool_calls=[
                    _make_tool_call(
                        "submit_analysis", _payload("缺失测量数据，需补充。", ["O1"])
                    )
                ]
            ),
        ],
        max_iterations=3,
    )
    orchestrator = RunOrchestrator(
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_mode=True,
        llm_client=client,
    )
    captured: Dict[str, Any] = {}

    def _capture_failure(run, run_audit):
        captured.update(run_audit)

    orchestrator._persist_failure = _capture_failure

    run = orchestrator.run(world_id=_WORLD, building_id=_BUILDING, persist=True)

    # 外层异常收尾把 run 判为 failed（非接纳终态）。
    assert run.status == "failed"
    assert captured["llm_narrative_accepted"] is False
    assert captured["narrative_fallback_reason"] == "orchestrator_exception"
    # 接纳指纹三字段与非接纳一致，全部 None。
    assert captured["accepted_via"] is None
    assert captured["accepted_payload_sha256"] is None
    assert captured["accepted_point_count"] is None
    # advisory（advisory_only 的 status_escalation_warning）必须被剥离干净。
    assert all(
        event["event"] != "status_escalation_warning"
        for event in captured.get("submission_audit_events", [])
    )


def test_duplicate_obligation_id_conflict_uses_internal_fallback_without_budget():
    state = _status_state(
        [
            _make_obligation(
                obligation_id="DEBT-054",
                closure_status="closed",
                satisfaction_status="violated",
            ),
            _make_obligation(
                obligation_id="DEBT-054",
                closure_status="open",
                satisfaction_status="unknown",
                open_reason_code="missing_fact",
            ),
        ]
    )
    receipt, finalized = _exec(_payload("建议分别核对状态来源。", ["O1"]), state)
    body = json.loads(receipt)
    assert finalized
    assert body["narrative_fallback_reason"] == "status_authority_ambiguous"
    assert state.narrative_attempts == 0
    assert state.narrative_rejection_codes == []
    assert state.accepted_payload is None
    assert state.submission_audit_events == [
        {
            "event": "status_authority_ambiguous",
            "attempt_index": 1,
            "details": [
                {
                    "point_index": 0,
                    "obligation_id": "DEBT-054",
                    "aliases": ["O1"],
                    "statuses": ["open", "violated"],
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    "text",
    [
        "我将避免输出额外内容",
        "按提示词要求只能使用该格式",
        "‘结案’一词不在本段使用",
    ],
)
def test_meta_commentary_three_shapes_report_only_meta(text):
    state = _open_state()
    codes = [item["code"] for item in narrative_guard(_payload(text), state)]
    assert codes == ["meta_commentary"]


def test_rule1_leak_and_antifabrication_redlines():
    state = _open_state()
    assert "forbidden_phrase" in {
        x["code"] for x in narrative_guard(_payload("字段 expected_verdict 不应出现"), state)
    }
    assert "fabricated_date" in {
        x["code"] for x in narrative_guard(_payload("请于2031-01-02前复核"), state)
    }
    assert "wrong_building_id" in {
        x["code"] for x in narrative_guard(_payload("复核 BLD-OTHER-9999"), state)
    }


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("字段 expected_**verdict** 不应出现", "forbidden_phrase"),
        ("字段 expected_\u200bverdict 不应出现", "forbidden_phrase"),
        ("请于2031\u201001\u201002前复核", "fabricated_date"),
        ("请于２０３１－０１－０２前复核", "fabricated_date"),
        ("请于2031年1月2日前复核", "fabricated_date"),
        ("复核 BLD-**OTHER**-9999", "wrong_building_id"),
    ],
)
def test_rule1_safety_scan_view_closes_unicode_and_markdown_bypasses(text, code):
    state = _open_state()
    codes = [item["code"] for item in narrative_guard(_payload(text), state)]
    assert code in codes


def test_prompt_sample_uses_uncopyable_placeholder_aliases():
    """反照抄（EXP-013 首批 15/15 样例照抄实证）：样例只用永不分配的
    O0/R0 占位别名并明示不可照抄；真实别名（O1 起）不得出现在样例里。"""
    state = _open_state()
    base_prompt = load_system_prompt()
    prompt = _narrative_system_prompt(base_prompt, state.evidence_pack)
    assert prompt == base_prompt.rstrip() + "\n"
    assert '"evidence_aliases":["O0"]' in prompt
    assert '"evidence_aliases":["O0","R0"]' in prompt
    assert '"evidence_aliases":["O1"]' not in prompt
    assert "不可照抄" in prompt
    assert "O0" not in (state.evidence_pack.alias_map or {})
    assert "提交前逐点自查清单" not in prompt
    assert "禁词枚举" not in prompt

    fences = re.findall(r"```(?:json)?\n[\s\S]*?\n```", prompt)
    assert len(fences) == 1
    parsed, parse_errors = parse_synthesized_submission(fences[0])
    assert not parse_errors
    normalized, validation_errors = validate_submission_payload(parsed)
    assert not validation_errors
    assert normalized == parsed


def test_format_receipt_includes_model_visible_pack_and_actionable_hint():
    state = LLMSessionState(world_id=_WORLD, building_id=_BUILDING, run_id=_RUN_ID)
    receipt, finalized = _exec({"points": []}, state)
    body = json.loads(receipt)
    assert not finalized
    assert body["status"] == "submission_format_error"
    assert body["narrative_evidence_pack"]["key_items"]
    assert body["narrative_evidence_pack"]["key_items"][0]["alias"] == "O1"
    # 顶层 fix_hint 必须**点名具体位置**并带该位置的修法（泛泛一句无法告诉模型
    # 第几点要改什么；2026-07-20 实证：模型只修被点名的点，漏掉未点名的）。
    assert body["fix_hint"].startswith("逐条修正以下位置后整篇重交：")
    assert "/points" in body["fix_hint"]
    assert body["event"]["errors"][0]["fix_hint"] in body["fix_hint"]
    assert body["repair_budget_consumed"] is False
    assert state.submission_format_repairs_used == 0


def test_v4_mode_format_receipt_reports_v4_and_v4_example(monkeypatch):
    """v4 模式下格式层回执（v4 分派之前拦截的遗留/解析失败路径）必须报
    version 4 并给 v4 形状样例——报 3 + v3 样例会教模型交错误形状。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    state = LLMSessionState(world_id=_WORLD, building_id=_BUILDING, run_id=_RUN_ID)
    receipt, finalized = _exec({"analysis_markdown": "遗留输入"}, state)
    body = json.loads(receipt)
    assert not finalized
    assert body["status"] == "submission_format_error"
    assert body["report_contract_version"] == 4
    example = body["example"]
    assert example["contract"] == "report_contract_v4"
    pt = example["points"][0]
    assert set(pt) == {"obligation_alias", "analysis_code",
                       "selected_fact_aliases", "review_action_code"}
    assert "text" not in pt and "evidence_aliases" not in pt


def test_synthesized_format_feedback_is_named_format_receipt():
    empty_fence = '```json\n{"points":[]}\n```'
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(text=empty_fence, finish_reason="stop"),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", _payload())]),
        ],
        max_iterations=4,
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=client,
    )
    feedback = "\n".join(
        str(message.get("content", ""))
        for message in client.chats[2]["messages"]
        if message.get("role") == "user"
    )
    assert result.llm_narrative_accepted
    assert "以下是格式层回执" in feedback
    assert "被叙述节闸拒绝" not in feedback


def test_b_directive_injected_once_with_key_item_alias_summary_anchors():
    payload = _payload()
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", payload)]),
        ],
        max_iterations=4,
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=client,
    )
    final_messages = client.chats[-1]["messages"]
    directives = [
        str(message.get("content", ""))
        for message in final_messages
        if "下一条只输出 JSON 点列（提交）" in str(message.get("content", ""))
    ]
    assert len(directives) == 1
    directive = directives[0]
    assert "不要交空 points；先为每个重点项写一点再提交" in directive
    assert "每点最多绑 8 个别名，条目多就拆点" in directive
    assert "本次 key_items 别名与一行摘要清单" in directive
    assert "O1 | category=open | kind=evidence | reason=missing_fact" in directive
    assert "可绑定别名=O1,R1" in directive
    assert "提及 token 必须属于本点 evidence_aliases" in directive
    assert result.accepted_via == "tool_call"


def test_empty_points_does_not_spend_substantive_format_repair_budget():
    state = _open_state()
    for _ in range(2):
        receipt, finalized = _exec({"points": []}, state)
        assert not finalized
        assert json.loads(receipt)["repair_budget_consumed"] is False
    assert state.submission_format_attempts == 2
    assert state.submission_format_repairs_used == 0

    receipt, finalized = _exec([], state)
    assert not finalized
    assert json.loads(receipt)["repair_budget_consumed"] is True
    assert state.submission_format_repairs_used == 1

    _, finalized = _exec(_payload(), state)
    assert finalized
    assert state.narrative_attempts == 1


def test_alias_map_empty_run_uses_template_without_invitation():
    client = _ScriptedLLM(
        [_make_turn(tool_calls=[_make_tool_call("run_closure_verification")])], max_iterations=3
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_allow_stop_true,
        llm_client=client,
    )
    assert result.llm_narrative_attempts == 0
    assert result.submission_format_attempts == 0
    assert result.accepted_via is None
    assert result.narrative_fallback_reason == "no_analysis_submitted"


def test_contract_version_frozen_against_midrun_env_flip(monkeypatch):
    """契约版本在会话创建时冻结：运行中环境从 v4 翻回 v3，v4 会话仍必须拒绝
    v3 形状载荷（copilot 终审五轮致命#1：各路径重读环境时 v3 自由文本会被
    接纳而终稿标 v4，突破核心红线）。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    state = _open_state()
    assert state.contract_version == 4
    # 会话进行中环境翻回 v3（进程级配置漂移）
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "")
    receipt, finalized = _exec(_payload(), state)  # v3 形状提交
    body = json.loads(receipt)
    # 必须走 v4 闸拒绝（wrong_contract），绝不能被 v3 路径接纳
    assert state.accepted_payload is None
    assert body.get("rejected") is True
    assert body["report_contract_version"] == 4
    assert "wrong_contract" in body["rejection_codes"]


def test_v4_mode_fallback_report_is_still_versioned_v4(monkeypatch):
    """v4 模式下模型未提交 → 确定性回退稿仍标 v4（版本按活动契约在 run 开始冻结）。
    copilot 终审四轮审出：按接纳载荷倒推会把 v4 模式回退稿降标 v3，
    审计/report kind/离线重渲染全被误归入 v3。"""
    monkeypatch.setenv("EVO_REPORT_CONTRACT", "v4")
    client = _ScriptedLLM(
        [_make_turn(tool_calls=[_make_tool_call("run_closure_verification")])], max_iterations=3
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_allow_stop_true,
        llm_client=client,
    )
    assert result.llm_narrative_accepted is False
    assert result.narrative_fallback_reason == "no_analysis_submitted"
    assert result.report_contract_version == 4
    assert "report contract v4" in result.report_markdown


def test_hash_is_compact_sorted_utf8_sha256():
    import hashlib

    payload, errors = validate_submission_payload(_payload("  建议复核。  "))
    assert not errors
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    state = _open_state()
    _exec(_payload("  建议复核。  "), state)
    assert state.accepted_payload_sha256 == expected


def test_run_orchestrator_passes_all_v3_submission_audit_fields():
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", _payload())]),
        ],
        max_iterations=3,
    )
    captured = {}
    orchestrator = RunOrchestrator(
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_mode=True,
        llm_client=client,
    )

    def capture(**kwargs):
        captured.update(kwargs["run_audit"])

    orchestrator._persist_artifacts = capture
    orchestrator.run(world_id=_WORLD, building_id=_BUILDING, persist=True)
    assert captured["report_contract_version"] == 3
    assert captured["submission_format_attempts"] == 1
    assert captured["submission_format_repairs_used"] == 0
    assert captured["submission_format_events"] == []
    assert captured["accepted_via"] == "tool_call"
    assert captured["accepted_point_count"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", captured["accepted_payload_sha256"])


def test_format_failure_raw_payload_is_persisted_as_explicitly_rejected_artifact(tmp_path):
    rejected_raw = "  模型编造但未接纳 O99\n第二行也未接纳  "
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(text=rejected_raw, finish_reason="stop"),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", _payload())]),
        ],
        max_iterations=4,
    )
    orchestrator = RunOrchestrator(
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_mode=True,
        llm_client=client,
        runs_root=str(tmp_path),
    )
    run = orchestrator.run(world_id=_WORLD, building_id=_BUILDING, persist=True)
    run_dir = tmp_path / run.run_id
    rejected_path = run_dir / "submission_format_rejected_raw_attempt_1.txt"
    assert rejected_path.read_bytes() == rejected_raw.encode("utf-8")
    assert rejected_raw not in (run_dir / "run_audit.json").read_text(encoding="utf-8")
    assert rejected_raw not in (run_dir / "incomplete_closure_notice.md").read_text(
        encoding="utf-8"
    )


def test_nonaccepted_run_removes_stale_accepted_payload_from_reused_run_dir(
    tmp_path, monkeypatch
):
    frozen_now = "2026-07-13T00:00:00Z"
    monkeypatch.setattr(run_orchestrator_module, "_utc_now_iso", lambda: frozen_now)

    accepted_client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", _payload())]),
        ],
        max_iterations=3,
    )
    accepted_run = RunOrchestrator(
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_mode=True,
        llm_client=accepted_client,
        runs_root=str(tmp_path),
    ).run(world_id=_WORLD, building_id=_BUILDING, persist=True)
    accepted_path = tmp_path / accepted_run.run_id / "accepted_payload.json"
    assert accepted_path.is_file()

    rejected_submission = _make_turn(
        tool_calls=[_make_tool_call("submit_analysis", _payload(aliases=["O99"]))]
    )
    nonaccepted_client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            rejected_submission,
            rejected_submission,
            rejected_submission,
        ],
        max_iterations=4,
    )
    nonaccepted_run = RunOrchestrator(
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_mode=True,
        llm_client=nonaccepted_client,
        runs_root=str(tmp_path),
    ).run(world_id=_WORLD, building_id=_BUILDING, persist=True)

    assert nonaccepted_run.run_id == accepted_run.run_id
    assert not accepted_path.exists()


def test_format_repair_can_recover_to_acceptance():
    state = _open_state()
    receipt, finalized = _exec([], state)
    assert not finalized and "submission_format_error" in receipt
    _, finalized = _exec(_payload(), state)
    assert finalized
    assert state.submission_format_attempts == 2
    assert state.submission_format_repairs_used == 1
    assert state.narrative_attempts == 1
    assert state.accepted_via == "tool_call"


def test_content_retry_validates_format_each_time_then_accepts_atomically():
    state = _open_state()
    _, finalized = _exec(_payload(aliases=["O99"]), state)
    assert not finalized
    _, finalized = _exec(_payload(), state)
    assert finalized
    assert state.submission_format_attempts == 2
    assert state.submission_format_repairs_used == 0
    assert state.narrative_attempts == 2
    assert state.accepted_payload == _payload()


def test_content_retry_exhaustion_keeps_format_budget_unused():
    state = _open_state()
    for expected_finalized in (False, False, True):
        _, finalized = _exec(_payload(aliases=["O99"]), state)
        assert finalized is expected_finalized
    assert state.submission_format_attempts == 3
    assert state.submission_format_repairs_used == 0
    assert state.narrative_attempts == 3
    assert state.narrative_fallback_reason == "narrative_guard_exhausted"
    assert state.accepted_payload is None


def test_fallback_reason_priority_is_monotonic():
    state = _open_state()
    _set_fallback_reason(state, "submission_format_exhausted")
    _set_fallback_reason(state, "combined_output_guard_rejected")
    _set_fallback_reason(state, "submission_format_exhausted")
    assert state.narrative_fallback_reason == "combined_output_guard_rejected"
    _set_fallback_reason(state, "composed_guard_degraded")
    _set_fallback_reason(state, "combined_output_guard_rejected")
    assert state.narrative_fallback_reason == "composed_guard_degraded"


@pytest.mark.parametrize(
    ("guard_failures", "fallback_reason"),
    [
        (1, "combined_output_guard_rejected"),
        (2, "composed_guard_degraded"),
    ],
)
def test_composition_guard_fallback_clears_terminal_acceptance_audit(
    monkeypatch, guard_failures, fallback_reason
):
    calls = 0

    def scripted_guard(text):
        nonlocal calls
        calls += 1
        if calls <= guard_failures:
            raise llm_orchestrator_module.OutputGuardError("forced composition failure")
        return {"guard": "pre_output_language_guard", "passed": True}

    monkeypatch.setattr(llm_orchestrator_module, "pre_output_language_guard", scripted_guard)
    client = _ScriptedLLM(
        [
            _make_turn(tool_calls=[_make_tool_call("run_closure_verification")]),
            _make_turn(tool_calls=[_make_tool_call("submit_analysis", _payload())]),
        ],
        max_iterations=3,
    )
    result = run_llm_orchestration(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_id=_RUN_ID,
        retrieval_fn=_default_retrieval,
        closure_fn=_default_closure_open,
        llm_client=client,
    )
    assert result.llm_narrative_accepted is False
    assert result.narrative_fallback_reason == fallback_reason
    assert result.accepted_via is None
    assert result.accepted_point_count is None
    assert result.accepted_payload_sha256 is None
    assert result.state.accepted_via is None
    assert result.state.accepted_payload is None
    assert result.state.accepted_payload_sha256 is None
