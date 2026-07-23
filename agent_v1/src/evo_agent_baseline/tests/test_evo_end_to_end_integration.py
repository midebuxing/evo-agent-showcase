"""v1 集成测试：RunOrchestrator(evo_mode=True) 端到端跑通（spec v1 §3.6 + §5.6 + §9.2）。

mock LLM（用 deterministic 分支即可，evo_mode 钩走 deterministic 路径）+
真实 closure 验证器（用 mock closure_fn 返回合法 ClosureValidationResult）+
真实 trace_capture + mock ReplayBuffer。

覆盖 ≥5 case：
1. evo_mode=True：trace 完整 finalize，4 类 audit 全 pass
2. evo_mode=False：last_evo_trace 为 None（不破坏 baseline）
3. allow_stop 仍 deterministic（trace_capture 不能改）
4. skill_invocation_log 反映 Skill 触发（用 evo_active_skill_version_ids 注入）
5. leakage_audit 全 false（agent 侧产物没有 W2 字段）
6. ReplayBuffer.add_trace 在 audit pass 时被调用，audit fail 时被拒
7. blocked run（输入阶段拦截）不会写 trace（because 流程 short-circuit）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from evo_agent_baseline.agent.run_orchestrator import RunOrchestrator
from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    EvoRunTrace,
    FactAtom,
    FactPack,
    Obligation,
    ObligationSet,
    RuleCardDTO,
    RuleFamilyDTO,
    RuleSlice,
)
from evo_agent_baseline.evo.trace_capture import TraceCapture


# ---------- mock retrieval / closure ----------


def _make_fact_pack(run_id: str) -> FactPack:
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
        slot_index={},
        measure_index={},
        carrier_index={"B-1": ["F-1"]},
        source_tables=["buildings.parquet"],
    )


def _make_rule_slice(run_id: str) -> RuleSlice:
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


def _make_retrieval_fn():
    def _fn(world_id: str, building_id: str, run_id: str) -> Tuple[FactPack, RuleSlice]:
        return _make_fact_pack(run_id), _make_rule_slice(run_id)
    return _fn


def _make_closure_fn(allow_stop: bool = True):
    def _fn(rule_slice: RuleSlice, fact_pack: FactPack, config: Any) -> ClosureValidationResult:
        obl = Obligation(
            obligation_id="O-1",
            run_id=fact_pack.run_id,
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
            run_id=fact_pack.run_id,
            world_id="W-1",
            building_id="B-1",
            created_at="2026-05-24T00:00:00Z",
            rulecard_bundle_id="mbis_cop_2023",
            verifier_version="closure_v1.0",
            obligations=[obl],
            derivation_policy={},
        )
        return ClosureValidationResult(
            run_id=fact_pack.run_id,
            obligation_set=obs,
            closure_summary=summary,
            allow_stop=allow_stop,
            allow_report_generation=allow_stop,
            high_risk_items=[],
            machine_readable_report={},
        )
    return _fn


class MockReplayBuffer:
    """spec v1 §9.2 ReplayBuffer.add_trace 接口的最小 mock（F 代理负责真实实现）。"""

    def __init__(self) -> None:
        self.added: List[EvoRunTrace] = []
        self.rejected: List[EvoRunTrace] = []

    def add_trace(self, trace: EvoRunTrace) -> bool:
        # 按 spec v1 §9.2 eligible 条件再次门控（双保险）
        if not (
            trace.forbidden_scan_passed
            and trace.source_visibility_audit_passed
            and trace.schema_audit_passed
            and trace.candidate_floor_passed
        ):
            self.rejected.append(trace)
            return False
        self.added.append(trace)
        return True


# ---------- 集成测试 ----------


class TestEvoModeOnHappyPath:
    def test_full_pipeline_writes_complete_trace(self, tmp_path):
        rb = MockReplayBuffer()
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            agent_version="evo_agent_v1.0",
            verifier_version="closure_v1.0",
            rulecard_bundle_id="mbis_cop_2023",
            kg_snapshot_id="KGS-test",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=[
                "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"
            ],
            evo_policy_version_id="policy.mbis.runtime.default.v1.0.0",
            evo_replay_buffer=rb,
        )
        run = orch.run(world_id="W-1", building_id="B-1", persist=True)
        assert run.status == "report_ready"

        trace = orch.last_evo_trace
        assert trace is not None
        # 4 类 audit 全 pass
        assert trace.forbidden_scan_passed is True
        assert trace.source_visibility_audit_passed is True
        assert trace.schema_audit_passed is True
        assert trace.candidate_floor_passed is True
        assert trace.fallback_reason is None
        # 必填 hash 齐
        assert len(trace.world_id_hash) == 64
        assert len(trace.building_id_hash) == 64
        assert trace.fact_pack_hash and len(trace.fact_pack_hash) == 64
        assert trace.rule_slice_hash and len(trace.rule_slice_hash) == 64
        assert trace.candidate_universe_hash and len(trace.candidate_universe_hash) == 64
        # 默认走 deterministic 模式 → llm_iterations_used=0
        assert trace.llm_iterations_used == 0
        # ReplayBuffer 接到 1 条 trace
        assert len(rb.added) == 1
        assert len(rb.rejected) == 0
        assert orch.last_replay_buffer_accepted is True

    def test_trace_persisted_to_disk(self, tmp_path):
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
        )
        run = orch.run(world_id="W-1", building_id="B-1", persist=True)
        run_dir = tmp_path / "runs" / run.run_id
        trace_file = run_dir / "evo_run_trace.json"
        assert trace_file.exists()
        # round-trip 通过 pydantic 校验
        import json as _json
        d = _json.loads(trace_file.read_text(encoding="utf-8"))
        loaded = EvoRunTrace.model_validate(d)
        assert loaded.trace_id == orch.last_evo_trace.trace_id


class TestEvoModeOff:
    def test_baseline_behavior_unchanged_when_evo_mode_false(self, tmp_path):
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=False,
        )
        run = orch.run(world_id="W-1", building_id="B-1", persist=True)
        # baseline 行为完全一致：last_evo_trace 不写
        assert orch.last_evo_trace is None
        assert orch.last_replay_buffer_accepted is None
        assert run.status == "report_ready"


class TestAllowStopDeterministic:
    def test_allow_stop_decided_by_verifier_not_capture(self, tmp_path):
        """任务原则 3 + spec v1 §6：trace_capture 不影响 allow_stop。"""
        # 用 allow_stop=False 的 closure_fn → run.allow_stop 必须 False
        orch_false = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=False),
            runs_root=str(tmp_path / "runs_false"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
        )
        run_f = orch_false.run(world_id="W-1", building_id="B-1", persist=True)
        assert run_f.allow_stop is False
        # 同样的 evo_mode=True，allow_stop=True 的 closure_fn → run.allow_stop=True
        orch_true = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs_true"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
        )
        run_t = orch_true.run(world_id="W-1", building_id="B-1", persist=True)
        assert run_t.allow_stop is True
        # closure_summary 里的 allow_stop 与 run.allow_stop 完全一致
        assert (
            orch_false.last_evo_trace.closure_summary["allow_stop"]
            == run_f.allow_stop
        )
        assert (
            orch_true.last_evo_trace.closure_summary["allow_stop"]
            == run_t.allow_stop
        )


class TestSkillInvocationLog:
    def test_active_skill_version_ids_reflected_in_trace(self, tmp_path):
        skill_ids = [
            "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
            "skill.mbis.report_structure.incomplete_closure_notice.v1",
        ]
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-policy.mbis.runtime.default.v1.0.0-9f2a",
            evo_active_skill_version_ids=skill_ids,
            evo_policy_version_id="policy.mbis.runtime.default.v1.0.0",
        )
        run = orch.run(world_id="W-1", building_id="B-1", persist=True)
        trace = orch.last_evo_trace
        # active_skill_version_ids 全保留
        assert trace.active_skill_version_ids == skill_ids
        # active_skill_set_id 保留
        assert trace.active_skill_set_id.startswith("SS-policy.mbis.runtime")


class TestLeakageAudit:
    def test_no_w2_fields_in_trace(self, tmp_path):
        """spec v1 §2.3.1 + §8.4.5：trace 任何字段都不应含 W2 / expected_verdict / projection_id 等。"""
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
        )
        run = orch.run(world_id="W-1", building_id="B-1", persist=True)
        trace = orch.last_evo_trace
        # 用 leakage_audit 集合的 6 项概念逐一手工检查 trace dump
        import json as _json
        trace_text = _json.dumps(trace.model_dump(), ensure_ascii=False)
        # 6 项 leakage_audit 概念全 false（trace 内无任何 W2 字符串）
        forbidden_strings = [
            "NormativeProjection",
            "expected_verdict",
            "projection_id",
            "truth_label",
            "EvalTruthReport",
            "force allow_stop",
        ]
        for s in forbidden_strings:
            assert s not in trace_text, f"leakage_audit 6 项中 '{s}' 出现在 trace 里"
        # 同时 trace 自带 4 类 audit 全 pass
        assert trace.forbidden_scan_passed is True


class TestReplayBufferGating:
    def test_replay_buffer_accepts_clean_trace(self, tmp_path):
        rb = MockReplayBuffer()
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
            evo_replay_buffer=rb,
        )
        orch.run(world_id="W-1", building_id="B-1", persist=True)
        assert len(rb.added) == 1
        assert orch.last_replay_buffer_accepted is True

    def test_replay_buffer_rejects_when_pre_injected_trace_fails_audit(self, tmp_path):
        """注入污染的 TraceCapture：调用 capture_report 写 w2_*.json → forbidden_scan fail
        → ReplayBuffer 不应入库。"""
        rb = MockReplayBuffer()
        # 预先构造 TraceCapture，覆盖默认 capture_report 行为：手工塞污染 ref
        # 在 run() 跑完之前，evo_trace_capture 已是 orchestrator 内部状态，
        # 这里采用反向：传一个 pre-built capture，run() 跑完后我们再用它的 audit
        # 状态验证。
        pre_cap = TraceCapture(run_id="dummy", world_id="W-1", building_id="B-1")
        # 注入到 orch；run() 里会被重置 run_id 不一致……所以直接构造一个
        # 完整 capture 流程，绕过 orchestrator 仅测 trace 端：
        pre_cap.capture_retrieval(_make_fact_pack("dummy"), _make_rule_slice("dummy"))
        pre_cap.capture_closure(_make_closure_fn(allow_stop=True)(
            _make_rule_slice("dummy"), _make_fact_pack("dummy"), None
        ))
        # 污染 report ref → forbidden_scan fail
        pre_cap.capture_report("runs/dummy/w2_truth_dump.json")
        trace = pre_cap.finalize(
            active_skill_set_id="SS-test",
            active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
            agent_version="evo_agent_v1.0",
            verifier_version="closure_v1.0",
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            tool_call_count=2,
            llm_iterations_used=0,
        )
        assert trace.forbidden_scan_passed is False
        # MockReplayBuffer 双保险拒收
        accepted = rb.add_trace(trace)
        assert accepted is False
        assert len(rb.added) == 0
        assert len(rb.rejected) == 1


class TestBlockedRunDoesNotWriteTrace:
    def test_input_guard_block_short_circuits_trace(self, tmp_path):
        """输入阶段 SecurityError → run blocked → trace 未 finalize（不进 ReplayBuffer）。"""
        rb = MockReplayBuffer()
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
            evo_replay_buffer=rb,
        )
        # 用 raw_request 带禁止词触发 input_guard 拦截（"最终裁决" 是 spec
        # Appendix A.4 禁止短语，hooks.pre_run_input_guard 显式拦此类诉求）。
        run = orch.run(
            world_id="W-1",
            building_id="B-1",
            run_input={
                "world_id": "W-1",
                "building_id": "B-1",
                "raw_request": "给出最终裁决",
            },
            persist=True,
        )
        # 输入阶段拦截 → status 应是 blocked 或 failed
        assert run.status in {"blocked", "failed"}
        # trace 未 finalize → ReplayBuffer 空
        assert len(rb.added) == 0
        assert orch.last_evo_trace is None


class TestStepStagesRecorded:
    def test_all_main_stages_appear_in_steps(self, tmp_path):
        """spec v1 §3.6.2 stage enum：input_guard / fact_retrieval / rule_retrieval /
        closure_verification / report_generation / guard 主流程必有。"""
        orch = RunOrchestrator(
            retrieval_fn=_make_retrieval_fn(),
            closure_fn=_make_closure_fn(allow_stop=True),
            runs_root=str(tmp_path / "runs"),
            kg_snapshot_id="KGS-test",
            rulecard_bundle_id="mbis_cop_2023",
            evo_mode=True,
            evo_active_skill_set_id="SS-test",
            evo_active_skill_version_ids=["skill.test.v1"],
            evo_policy_version_id="policy.test.v1",
        )
        orch.run(world_id="W-1", building_id="B-1", persist=True)
        trace = orch.last_evo_trace
        stages = {s.stage for s in trace.steps}
        # 主流程 6 个 stage（input_guard / fact_retrieval / rule_retrieval /
        # closure_verification / report_generation / guard）至少 5 个出现
        expected = {
            "input_guard",
            "fact_retrieval",
            "rule_retrieval",
            "closure_verification",
            "report_generation",
            "guard",
        }
        assert expected.issubset(stages), f"missing stages: {expected - stages}"
