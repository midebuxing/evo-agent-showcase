"""TraceCapture 单元测试（spec v1 §3.6.2 + §5.6 + §9.2 + Appendix A/B）。

覆盖 ≥10 case：
1. 初始化必须立即 hash world_id / building_id
2. trace_id 形如 `ERT-<run_id>-<8hex>`
3. capture_step 自增 seq；tool_input/output 只留 hash
4. capture_input_guard 写 input_guard_hash + 一个 input_guard step
5. capture_retrieval 写 fact_pack_hash / rule_slice_hash / candidate_universe_hash
6. capture_closure 不修改 closure_result（任务原则 3）
7. capture_report / capture_hooks 路径与 hash 正常
8. finalize → EvoRunTrace pydantic 校验通过、4 类 audit pass
9. forbidden_scan 拦 retrieval_summary 含 raw expected_verdict / W2 label
10. world_id_hash / building_id_hash 与 sha256(canonical_json) 一致
11. forbidden_scan 拦 report_ref = w2_*.json
12. source_visibility_audit 拦 report_ref 指向 evaluator_truth_store
13. candidate_floor_passed=False 当 candidate_universe_hash 缺失
14. EvoRunStep extra=forbid（schema_audit）
15. canonical_json_for_hash 同一对象 hash 一致（确定性）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    EvoRunStep,
    EvoRunTrace,
    FactAtom,
    FactPack,
    Obligation,
    ObligationSet,
    RuleCardDTO,
    RuleFamilyDTO,
    RuleSlice,
)
from evo_agent_baseline.evo.trace_capture import (
    FORBIDDEN_LABELS,
    FORBIDDEN_PHRASES,
    FORBIDDEN_PROPERTIES,
    TraceCapture,
    canonical_json_for_hash,
    sha256_hex,
)


# ---------- 工厂 ----------


def _make_fact_pack(run_id: str = "CAR-T-1") -> FactPack:
    atom = FactAtom(
        fact_id="F-1",
        world_id="W-1",
        building_id="B-1",
        carrier_type="building",
        carrier_id="B-1",
        target_ref=None,
        slot_id=None,
        measure_key=None,
        value_json="\"yes\"",
        value_type="string",
        unit=None,
        qualifiers={},
        confidence_index=0.9,
        source_path="agent_kg/buildings.parquet",
        source_node_id="N-1",
        provenance={},
    )
    return FactPack(
        run_id=run_id,
        world_id="W-1",
        building_id="B-1",
        facts=[atom],
        slot_index={"slot.a": ["F-1"]},
        measure_index={},
        carrier_index={"B-1": ["F-1"]},
        source_tables=["buildings.parquet"],
    )


def _make_rule_slice(run_id: str = "CAR-T-1") -> RuleSlice:
    fam = RuleFamilyDTO(
        family_id="mbis.reporting.inspection_report.ri.schema",
        family_name="RI schema",
    )
    card = RuleCardDTO(
        rule_card_id="card-1",
        source_document_id="MBIS_CoP_2023",
        normalized_rule_text="...",
        family_id=fam.family_id,
    )
    return RuleSlice(
        run_id=run_id,
        rulecard_bundle_id="mbis_cop_2023",
        candidate_rule_cards=[card],
        rule_families=[fam],
        semantic_slots=[],
        measures=[],
        artifacts=[],
        time_anchors=[],
        source_quotes=[],
        retrieval_policy={"topk": 80},
    )


def _make_closure_result(run_id: str = "CAR-T-1", allow_stop: bool = False) -> ClosureValidationResult:
    obl = Obligation(
        obligation_id="O-1",
        run_id=run_id,
        world_id="W-1",
        building_id="B-1",
        source_rule_card_id="card-1",
        source_family_id="mbis.reporting.inspection_report.ri.schema",
        kind="evidence",
        closure_status="closed",
        satisfaction_status="satisfied",
    )
    summary = ClosureSummary(
        total_obligations=1,
        closed_count=1,
        open_count=0,
        blocked_count=0,
        satisfied_count=1,
        violated_count=0,
        unknown_count=0,
        not_applicable_count=0,
        open_reason_counts={},
        blocked_reason_counts={},
        rule_card_count=1,
        family_count=1,
        fragment_count=1,
        allow_stop=allow_stop,
        stop_reason="ok" if allow_stop else "open_or_blocked",
    )
    obs = ObligationSet(
        obligation_set_id="OS-1",
        run_id=run_id,
        world_id="W-1",
        building_id="B-1",
        created_at="2026-05-24T00:00:00Z",
        rulecard_bundle_id="mbis_cop_2023",
        verifier_version="closure_v1.0",
        obligations=[obl],
        derivation_policy={},
    )
    return ClosureValidationResult(
        run_id=run_id,
        obligation_set=obs,
        closure_summary=summary,
        allow_stop=allow_stop,
        allow_report_generation=allow_stop,
        high_risk_items=[],
        machine_readable_report={},
    )


def _finalize_default(cap: TraceCapture) -> EvoRunTrace:
    return cap.finalize(
        active_skill_set_id="SS-test",
        active_skill_version_ids=["skill.test.v1"],
        evo_policy_version_id="policy.test.v1",
        agent_version="evo_agent_v1.0",
        verifier_version="closure_v1.0",
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="mbis_cop_2023",
        tool_call_count=2,
        llm_iterations_used=0,
        cost={"wall_ms": 100},
    )


# ---------- 测试 ----------


class TestInit:
    def test_init_hashes_ids_immediately(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        assert cap.world_id_hash == sha256_hex("W-1")
        assert cap.building_id_hash == sha256_hex("B-1")
        # hash 是 sha256 hex（64 字符 lowercase）
        assert len(cap.world_id_hash) == 64
        assert cap.world_id_hash.islower()

    def test_trace_id_format(self):
        cap = TraceCapture(run_id="CAR-XYZ", world_id="W-1", building_id="B-1")
        assert cap.trace_id.startswith("ERT-CAR-XYZ-")
        # sha8 后缀，共 8 字符
        suffix = cap.trace_id.split("-")[-1]
        assert len(suffix) == 8
        # 同 run_id → 同 trace_id（确定性）
        cap2 = TraceCapture(run_id="CAR-XYZ", world_id="W-2", building_id="B-2")
        assert cap.trace_id == cap2.trace_id

    def test_init_rejects_empty_ids(self):
        with pytest.raises(ValueError):
            TraceCapture(run_id="", world_id="W-1", building_id="B-1")
        with pytest.raises(ValueError):
            TraceCapture(run_id="CAR-1", world_id="", building_id="B-1")
        with pytest.raises(ValueError):
            TraceCapture(run_id="CAR-1", world_id="W-1", building_id="")


class TestCanonicalAndHash:
    def test_canonical_json_deterministic(self):
        a = {"b": 1, "a": [3, 2, 1]}
        b = {"a": [3, 2, 1], "b": 1}
        assert canonical_json_for_hash(a) == canonical_json_for_hash(b)
        assert sha256_hex(a) == sha256_hex(b)

    def test_world_id_hash_matches_sha256_canonical(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-42", building_id="B-42")
        # str 入参直接 hash str
        assert cap.world_id_hash == sha256_hex("W-42")


class TestCaptureStep:
    def test_seq_increments_and_step_id_format(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        s1 = cap.capture_step(stage="fact_retrieval")
        s2 = cap.capture_step(stage="rule_retrieval")
        assert s1.seq == 1
        assert s2.seq == 2
        assert s1.step_id.startswith("ERS-")
        assert s1.step_id.endswith("-0001")
        assert s2.step_id.endswith("-0002")

    def test_tool_input_output_hashed_not_raw(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        raw_input = {"world_id": "W-1", "secret": "topsecret"}
        raw_output = {"rows": 100, "first_row": {"sensitive": "data"}}
        step = cap.capture_step(
            stage="fact_retrieval",
            tool_name="kg_query",
            tool_input=raw_input,
            tool_output_summary=raw_output,
        )
        # raw 值不应出现在 step 中
        s_dict = step.model_dump()
        assert "topsecret" not in json.dumps(s_dict)
        assert "sensitive" not in json.dumps(s_dict)
        assert step.tool_input_hash is not None
        assert step.tool_output_summary_hash is not None
        # hash 是 sha256 hex
        assert len(step.tool_input_hash) == 64

    def test_step_extra_forbid(self):
        # EvoRunStep extra=forbid（spec Appendix B.2）
        with pytest.raises(ValidationError):
            EvoRunStep(
                step_id="ERS-x-1",
                trace_id="ERT-1",
                seq=1,
                stage="guard",
                created_at="2026-05-24T00:00:00Z",
                unauthorized_field="should_be_forbidden",  # type: ignore
            )


class TestCaptureRetrieval:
    def test_retrieval_summary_written(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        fp = _make_fact_pack()
        rs = _make_rule_slice()
        cap.capture_retrieval(fact_pack=fp, rule_slice=rs)
        # 内部状态已写
        assert cap._fact_pack_hash and len(cap._fact_pack_hash) == 64
        assert cap._rule_slice_hash and len(cap._rule_slice_hash) == 64
        assert cap._candidate_universe_hash and len(cap._candidate_universe_hash) == 64
        # retrieval_summary 含 fact_count + family_count（非 raw 内容）
        assert cap._retrieval_summary["fact_count"] == 1
        assert cap._retrieval_summary["rule_family_count"] == 1
        # 记了 2 个 step（fact + rule）
        stages = [s.stage for s in cap.steps]
        assert "fact_retrieval" in stages
        assert "rule_retrieval" in stages

    def test_candidate_universe_explicit(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        fp = _make_fact_pack()
        rs = _make_rule_slice()
        explicit = {"card-2", "card-1", "card-3"}  # set → sort_ascending
        cap.capture_retrieval(fact_pack=fp, rule_slice=rs, candidate_universe=explicit)
        # set 语义排序后 hash 一致
        assert cap._candidate_universe_hash == sha256_hex(sorted(explicit))


class TestCaptureClosure:
    def test_does_not_modify_closure_result(self):
        """任务原则 3：trace_capture 不能改 allow_stop。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cr = _make_closure_result(allow_stop=True)
        before_allow_stop = cr.allow_stop
        cap.capture_closure(cr)
        # closure_result 对象未变
        assert cr.allow_stop == before_allow_stop
        # cap 写了 closure_summary 镜像
        assert cap._closure_summary["allow_stop"] is True
        assert cap._closure_summary["total_obligations"] == 1


class TestCaptureHooks:
    def test_hook_results_hashed(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        hooks = [
            {"guard": "pre_run_input_guard", "passed": True},
            {"guard": "post_retrieval_source_audit", "passed": True,
             "forbidden_sources_loaded": []},
            {"guard": "post_verifier_stop_gate", "allow_stop": False},
        ]
        cap.capture_hooks(hooks)
        assert cap._hook_results_hash and len(cap._hook_results_hash) == 64
        # 每个 hook 都记了一个 guard step
        guard_steps = [s for s in cap.steps if s.stage == "guard"]
        assert len(guard_steps) == 3


class TestFinalize:
    def test_full_capture_pipeline_passes_audits(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_input_guard({"guard": "pre_run_input_guard", "passed": True})
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        cap.capture_closure(_make_closure_result())
        cap.capture_report("runs/CAR-1/incomplete_closure_notice.md")
        cap.capture_hooks([{"guard": "post_verifier_stop_gate", "allow_stop": False}])
        trace = _finalize_default(cap)

        # schema 校验通过 + 4 类 audit 全 pass
        assert trace.forbidden_scan_passed is True
        assert trace.source_visibility_audit_passed is True
        assert trace.schema_audit_passed is True
        assert trace.candidate_floor_passed is True
        # 必填字段非空
        assert trace.trace_id == cap.trace_id
        assert trace.world_id_hash == cap.world_id_hash
        assert trace.building_id_hash == cap.building_id_hash
        # steps 完整
        assert len(trace.steps) == len(cap.steps)
        # trace_visibility 固定
        assert trace.trace_visibility == "agent_visible_trace"

    def test_candidate_floor_fail_when_no_retrieval(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        # 跳过 capture_retrieval → candidate_universe_hash 空 → fail
        cap.capture_hooks([{"guard": "noop"}])
        trace = _finalize_default(cap)
        assert trace.candidate_floor_passed is False
        # 但 schema 仍 pass（空字符串字段合法）
        assert trace.schema_audit_passed is True

    def test_trace_extra_forbid(self):
        """EvoRunTrace extra=forbid（spec Appendix B.2 / DTO 不允许额外字段）。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        trace = _finalize_default(cap)
        d = trace.model_dump()
        # 模型 round-trip 通过；加未授权字段后 validate 应 fail
        d["unauthorized_field"] = "leak"
        with pytest.raises(ValidationError):
            EvoRunTrace.model_validate(d)


class TestForbiddenScan:
    def test_forbidden_property_in_retrieval_summary(self):
        """spec Appendix A.2：retrieval_summary 含 expected_verdict → forbidden_scan fail。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        # 故意污染 retrieval_summary
        cap._retrieval_summary["expected_verdict"] = "compliant"
        trace = _finalize_default(cap)
        assert trace.forbidden_scan_passed is False
        findings = cap.audit_findings["forbidden_scan"]
        assert any(f["kind"] == "forbidden_property" for f in findings)

    def test_forbidden_label_in_closure_summary(self):
        """spec Appendix A.1：closure_summary 含 'NormativeProjection' 字符串 → fail。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        cap.capture_closure(_make_closure_result())
        cap._closure_summary["leaked_label"] = "NormativeProjection"
        trace = _finalize_default(cap)
        assert trace.forbidden_scan_passed is False
        findings = cap.audit_findings["forbidden_scan"]
        assert any(f["kind"] == "forbidden_label" for f in findings)

    def test_forbidden_file_ref_in_report(self):
        """spec Appendix A.3：report_ref 含 w2_*.json 文件名 → fail。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        cap.capture_report("runs/CAR-1/w2_truth_dump.json")
        trace = _finalize_default(cap)
        assert trace.forbidden_scan_passed is False
        findings = cap.audit_findings["forbidden_scan"]
        assert any(f["kind"] == "forbidden_file_prefix" for f in findings)

    def test_forbidden_phrase_in_summary(self):
        """spec Appendix A.4：summary 含 'force allow_stop' → fail。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        # 通过 closure_summary 注入禁语
        cap._closure_summary["debug_note"] = "force allow_stop manually"
        trace = _finalize_default(cap)
        assert trace.forbidden_scan_passed is False
        findings = cap.audit_findings["forbidden_scan"]
        assert any(f["kind"] == "forbidden_phrase" for f in findings)


class TestSourceVisibility:
    def test_evaluator_path_ref_fails(self):
        """spec v1 §2.5：report_ref 指向 evaluator_truth_store → fail。"""
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        cap.capture_report("evaluator_truth_store/leaked_report.md")
        trace = _finalize_default(cap)
        assert trace.source_visibility_audit_passed is False

    def test_agent_path_ref_passes(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_retrieval(_make_fact_pack(), _make_rule_slice())
        cap.capture_report("runs/CAR-1/incomplete_closure_notice.md")
        trace = _finalize_default(cap)
        assert trace.source_visibility_audit_passed is True


class TestCaptureInputGuard:
    def test_input_guard_hash_set_and_step_recorded(self):
        cap = TraceCapture(run_id="CAR-1", world_id="W-1", building_id="B-1")
        cap.capture_input_guard({"guard": "pre_run_input_guard", "passed": True})
        assert cap._input_guard_hash and len(cap._input_guard_hash) == 64
        # 同时记了一个 input_guard step（spec §3.6.2 stage enum）
        assert any(s.stage == "input_guard" for s in cap.steps)


class TestForbiddenConstantsLoaded:
    def test_forbidden_constants_non_empty(self):
        """spec Appendix A 禁止集合不能为空（防止 import-time 退化）。"""
        assert "NormativeProjection" in FORBIDDEN_LABELS
        assert "expected_verdict" in FORBIDDEN_PROPERTIES
        assert "force allow_stop" in FORBIDDEN_PHRASES
        # v1 新增的 EvalTruthReport
        assert "EvalTruthReport" in FORBIDDEN_LABELS
        # v1 新增的 truth_label
        assert "truth_label" in FORBIDDEN_PROPERTIES
