"""LLM orchestrator tool 参数边界校验（Codex review finding #9 落地）。

覆盖 finding #1 / #2 / #6 的 4 条防御性 patch：
    1. 非 dict args（list）→ _execute_tool 返回 JSON 错误，不抛
    2. 非 dict args（string）→ _execute_tool 返回 JSON 错误，不抛
    3. 非 int top_k（string "abc"）→ JSON 错误，不抛 ValueError
    4. 负 limit（-1）→ clamp 到 min_value=1，正常返回
    5. 超大 limit（10**9）→ clamp 到 max_value=200，正常返回

关键不变量（finding #1）：所有边界异常以 `{"error": ...}` JSON 形式返回给 LLM
重试，而不是冒泡到 RunOrchestrator 的 except 兜底变 run.status="failed"。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from evo_agent_baseline.agent.llm_orchestrator import (  # noqa: E402
    LLMSessionState,
    NARRATIVE_FALLBACK_REASONS,
    NARRATIVE_REJECTION_CODES,
    _OBLIGATION_NORMATIVE_OBJECTS,
    _OBLIGATION_SOFT_GAP_PREDICATES,
    _OBLIGATION_STATUS_ESCALATION_CANDIDATES,
    _OBLIGATION_VIOLATION_PREDICATES,
    _execute_tool,
    _parse_int_arg,
    _PARSE_INT_FAIL,
)
from evo_agent_baseline.contracts import (  # noqa: E402
    ClosureSummary,
    ClosureValidationResult,
    Obligation,
    ObligationSet,
)


def _make_session_with_closure() -> LLMSessionState:
    """构造一个带最小 closure_result 的 session（够 query_open_obligations 跑）。"""
    obligations = [
        Obligation(
            obligation_id="o" * 24,
            world_id="W-T",
            building_id="B-T",
            run_id="R-T",
            source_rule_card_id="RC-TEST",
            source_family_id="F-TEST",
            kind="threshold",
            slot_ids=["slot.crack_width"],
            measure_keys=["m.crack_width"],
            closure_status="open",
            satisfaction_status="unknown",
            open_reason_code="missing_fact",
        )
    ]
    obligation_set = ObligationSet(
        obligation_set_id="os-test",
        run_id="R-T",
        world_id="W-T",
        building_id="B-T",
        created_at="2026-01-01T00:00:00Z",
        rulecard_bundle_id="rcb-test",
        verifier_version="v1-test",
        obligations=obligations,
        derivation_policy={},
    )
    summary = ClosureSummary(
        total_obligations=1,
        closed_count=0,
        open_count=1,
        blocked_count=0,
        satisfied_count=0,
        violated_count=0,
        unknown_count=1,
        not_applicable_count=0,
        open_reason_counts={"missing_fact": 1},
        blocked_reason_counts={},
        rule_card_count=1,
        family_count=1,
        fragment_count=0,
        allow_stop=False,
        stop_reason="open_obligations_exist",
    )
    closure_result = ClosureValidationResult(
        run_id="R-T",
        obligation_set=obligation_set,
        closure_summary=summary,
        allow_stop=False,
        allow_report_generation=False,
        high_risk_items=[],
        machine_readable_report={},
    )
    return LLMSessionState(
        world_id="W-T",
        building_id="B-T",
        run_id="R-T",
        closure_result=closure_result,
    )


def _dummy_retrieval_fn(world_id: str, building_id: str, run_id: str):  # pragma: no cover
    raise AssertionError("retrieval_fn 不应被本测试触发")


def _dummy_closure_fn(rule_slice, fact_pack, config):  # pragma: no cover
    raise AssertionError("closure_fn 不应被本测试触发")


class TestFrozenV3Enums(unittest.TestCase):
    """v3 状态一致性闸连带冻结的拒码、兜底原因与义务词表。"""

    def test_narrative_rejection_codes_are_frozen_at_eleven(self) -> None:
        self.assertEqual(
            NARRATIVE_REJECTION_CODES,
            (
                "unresolved_alias",
                "fabricated_date",
                "wrong_building_id",
                "fake_obligation_id",
                "fake_rule_card_id",
                "fake_fact_id",
                "raw_evidence_id",
                "forbidden_phrase",
                "branch_inconsistent",
                "meta_commentary",
                "status_escalation",
            ),
        )

    def test_narrative_fallback_reasons_are_frozen_at_seven(self) -> None:
        self.assertEqual(
            NARRATIVE_FALLBACK_REASONS,
            (
                "no_analysis_submitted",
                "narrative_rejected_no_retry",
                "narrative_guard_exhausted",
                "combined_output_guard_rejected",
                "composed_guard_degraded",
                "submission_format_exhausted",
                "status_authority_ambiguous",
            ),
        )

    def test_obligation_candidate_component_predicates_are_frozen(self) -> None:
        # 规则 A 降 advisory 后，硬词/软词不再拆两层触发，但仍作为合并候选表的
        # 来源分量与冻结锚保留（顺序即合并去重顺序：硬词在前）。
        self.assertEqual(
            _OBLIGATION_VIOLATION_PREDICATES,
            (
                "缺失即违规",
                "构成违规",
                "未达标",
                "不达标",
                "不合格",
                "违反",
                "违背",
                "违规",
                "逾期",
                "超期",
            ),
        )
        self.assertEqual(
            _OBLIGATION_NORMATIVE_OBJECTS,
            ("法定", "法规", "规范", "规定", "标准", "要求", "义务"),
        )
        self.assertEqual(
            _OBLIGATION_SOFT_GAP_PREDICATES,
            (
                "无法满足",
                "缺失",
                "缺少",
                "尚缺",
                "欠缺",
                "未取得",
                "无法达到",
                "未满足",
                "不符合",
            ),
        )

    def test_status_escalation_candidate_table_is_frozen(self) -> None:
        # A 案合并后的单一候选表：硬词（10）+ 软词（9）去重、硬词在前。规则 A
        # 命中它只驱动 advisory 审计，绝不产拒码（拒码 status_escalation 归规则 B）。
        self.assertEqual(
            _OBLIGATION_STATUS_ESCALATION_CANDIDATES,
            (
                "缺失即违规",
                "构成违规",
                "未达标",
                "不达标",
                "不合格",
                "违反",
                "违背",
                "违规",
                "逾期",
                "超期",
                "无法满足",
                "缺失",
                "缺少",
                "尚缺",
                "欠缺",
                "未取得",
                "无法达到",
                "未满足",
                "不符合",
            ),
        )


class TestExecuteToolNonDictArgs(unittest.TestCase):
    """finding #1：非 dict 工具参数必须返回 JSON 错误，不抛 AttributeError。"""

    def test_list_args_returns_json_error_no_exception(self) -> None:
        """case 1：args = [] 不抛，返回 {"error": ...} 且 finalize_flag=False。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args=[],  # type: ignore[arg-type]
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertIn("error", parsed)
        self.assertIn("dict", parsed["error"])

    def test_string_args_returns_json_error_no_exception(self) -> None:
        """case 2：args = "x" 不抛，返回 {"error": ...}。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args="x",  # type: ignore[arg-type]
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertIn("error", parsed)

    def test_none_args_returns_json_error_no_exception(self) -> None:
        """case 2b：args = None（极端 JSON 形状）不抛，返回 {"error": ...}。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args=None,  # type: ignore[arg-type]
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertIn("error", parsed)

    def test_non_dict_args_for_finalize_report_also_safe(self) -> None:
        """finalize_report 也得拦，并允许格式回执先补齐最小证据包。"""
        state = _make_session_with_closure()
        retrieval_fn = lambda world_id, building_id, run_id: (
            SimpleNamespace(facts=[]),
            SimpleNamespace(candidate_rule_cards=[], source_quotes=[]),
        )
        result_text, finalize_flag = _execute_tool(
            tool_name="finalize_report",
            args=[1, 2, 3],  # type: ignore[arg-type]
            state=state,
            retrieval_fn=retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertIn("error", parsed)


class TestExecuteToolIntArgValidation(unittest.TestCase):
    """finding #2 + #6：非 int / 越界 int 参数必须返回 JSON 错误或被 clamp。"""

    def test_query_open_non_int_limit_returns_json_error(self) -> None:
        """case 3 类比：limit="abc" 不抛 ValueError，返回 {"error": ...}。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args={"limit": "abc"},
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertIn("error", parsed)
        self.assertIn("limit", parsed["error"])

    def test_query_open_negative_limit_clamped_not_failed(self) -> None:
        """case 4：limit=-1 被 clamp 到 1，正常返回 open_obligations 摘要。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args={"limit": -1},
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        # 不再含 "error"——是合法摘要
        self.assertNotIn("error", parsed)
        self.assertIn("open_obligations", parsed)
        # clamp 到 1 → 顶多返回 1 条
        self.assertLessEqual(len(parsed["open_obligations"]), 1)

    def test_query_open_huge_limit_clamped_not_failed(self) -> None:
        """case 5：limit=10**9 被 clamp 到 max_value=200，正常返回。"""
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args={"limit": 10**9},
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertNotIn("error", parsed)
        self.assertIn("open_obligations", parsed)

    def test_query_open_zero_limit_clamped_to_one(self) -> None:
        """补充：limit=0（边界）→ clamp 到 1 而非返回空错误部分结果。

        Codex finding #2 原话：'零值/负值/超大值均无拦截，返回错误部分结果'。
        此处验证修复后 0 被当作越下界 clamp 到 1。
        """
        state = _make_session_with_closure()
        result_text, finalize_flag = _execute_tool(
            tool_name="query_open_obligations",
            args={"limit": 0},
            state=state,
            retrieval_fn=_dummy_retrieval_fn,
            closure_fn=_dummy_closure_fn,
            verifier_config=None,
        )
        self.assertFalse(finalize_flag)
        parsed = json.loads(result_text)
        self.assertNotIn("error", parsed)
        # 至少返回 1 条（不是 0 条空 partial）
        self.assertEqual(len(parsed["open_obligations"]), 1)


class TestParseIntArgHelper(unittest.TestCase):
    """直接测 _parse_int_arg helper，确保 clamp / 解析行为正确。"""

    def test_default_when_key_missing(self) -> None:
        self.assertEqual(_parse_int_arg({}, "k", 5, min_value=1, max_value=20), 5)

    def test_default_clamped_to_min_when_default_too_small(self) -> None:
        # 防御：调用方传了荒唐 default
        self.assertEqual(_parse_int_arg({}, "k", -5, min_value=1, max_value=20), 1)

    def test_default_clamped_to_max_when_default_too_large(self) -> None:
        self.assertEqual(_parse_int_arg({}, "k", 999, min_value=1, max_value=20), 20)

    def test_int_within_range(self) -> None:
        self.assertEqual(_parse_int_arg({"k": 7}, "k", 5, min_value=1, max_value=20), 7)

    def test_int_below_min_clamped(self) -> None:
        self.assertEqual(
            _parse_int_arg({"k": -100}, "k", 5, min_value=1, max_value=20), 1
        )

    def test_int_above_max_clamped(self) -> None:
        self.assertEqual(
            _parse_int_arg({"k": 9999}, "k", 5, min_value=1, max_value=20), 20
        )

    def test_string_number_parsed(self) -> None:
        # LLM 偶尔传字符串数字 "7"，跟整数 7 等价
        self.assertEqual(_parse_int_arg({"k": "7"}, "k", 5, min_value=1, max_value=20), 7)

    def test_string_nonnumber_returns_fail(self) -> None:
        self.assertIs(
            _parse_int_arg({"k": "abc"}, "k", 5, min_value=1, max_value=20),
            _PARSE_INT_FAIL,
        )

    def test_float_truncated_and_clamped(self) -> None:
        self.assertEqual(_parse_int_arg({"k": 7.9}, "k", 5, min_value=1, max_value=20), 7)

    def test_float_nan_returns_fail(self) -> None:
        self.assertIs(
            _parse_int_arg({"k": float("nan")}, "k", 5, min_value=1, max_value=20),
            _PARSE_INT_FAIL,
        )

    def test_bool_rejected(self) -> None:
        # bool 虽是 int 子类但 LLM 传 True/False 当数字属于异常意图
        self.assertIs(
            _parse_int_arg({"k": True}, "k", 5, min_value=1, max_value=20),
            _PARSE_INT_FAIL,
        )

    def test_list_value_returns_fail(self) -> None:
        self.assertIs(
            _parse_int_arg({"k": [1, 2]}, "k", 5, min_value=1, max_value=20),
            _PARSE_INT_FAIL,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
