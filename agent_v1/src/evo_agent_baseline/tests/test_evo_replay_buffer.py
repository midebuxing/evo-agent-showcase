"""ReplayBuffer 单元测试（spec v1 §9.2）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_agent_baseline.contracts import EvoRunStep, EvoRunTrace
from evo_agent_baseline.evo.replay_buffer import ReplayBuffer


def _build_trace(
    idx: int,
    *,
    forbidden_scan: bool = True,
    source_visibility: bool = True,
    schema_audit: bool = True,
    candidate_universe_hash: str = "sha256:universe",
    closure_result_ref: str = "closure_ref",
    closed_count: int = 5,
    open_count: int = 1,
    blocked_count: int = 0,
    total: int = 6,
    open_reason: str = "missing_fact",
    rule_families: list = None,
    obligation_kinds: list = None,
    semantic_slot_classes: list = None,
    tool_count: int = 10,
    steps: list = None,
    building_id_hash: str = None,
    world_id_hash: str = None,
    active_skill_set_id: str = "SS-default",
) -> EvoRunTrace:
    cs = {
        "closed_count": closed_count,
        "open_count": open_count,
        "blocked_count": blocked_count,
        "total_obligations": total,
        "open_reason_counts": {open_reason: open_count} if open_count > 0 else {},
        "blocked_reason_counts": {},
        "rule_families": rule_families or ["mbis.reporting.x"],
        "obligation_kinds": obligation_kinds or ["report_field"],
        "semantic_slot_classes": semantic_slot_classes or ["artifact_evidence"],
    }
    return EvoRunTrace(
        trace_id=f"ERT-test-{idx:03d}",
        run_id=f"CAR-{idx:03d}",
        world_id_hash=world_id_hash or f"sha256:world_{idx % 3}",
        building_id_hash=building_id_hash or f"sha256:bld_{idx % 5}",
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
        agent_version="v1.0.0",
        verifier_version="v1.0.0",
        evo_policy_version_id="policy.mbis.runtime.default.v1.0.0",
        active_skill_set_id=active_skill_set_id,
        active_skill_version_ids=[],
        input_guard_hash="sha256:guard",
        retrieval_summary={
            "rule_families": rule_families or ["mbis.reporting.x"],
            "semantic_slot_classes": semantic_slot_classes or ["artifact_evidence"],
        },
        candidate_universe_hash=candidate_universe_hash,
        fact_pack_hash="sha256:facts",
        rule_slice_hash="sha256:rules",
        closure_result_ref=closure_result_ref,
        closure_summary=cs,
        report_ref=None,
        hook_results_hash="sha256:hooks",
        tool_call_count=tool_count,
        llm_iterations_used=3,
        cost={"tokens": 100},
        fallback_reason=None,
        steps=steps or [],
        sanitized_feedback_refs=[],
        trace_visibility="agent_visible_trace",
        forbidden_scan_passed=forbidden_scan,
        source_visibility_audit_passed=source_visibility,
        schema_audit_passed=schema_audit,
        candidate_floor_passed=True,
        created_at=f"2026-05-{idx % 28 + 1:02d}T00:00:00Z",
    )


# ---------------- 入库 / eligibility ----------------------------------------


def test_buffer_add_eligible_trace_returns_true():
    buf = ReplayBuffer()
    t = _build_trace(0)
    assert buf.add_trace(t) is True
    assert len(buf.list_eligible_traces()) == 1


def test_buffer_rejects_forbidden_scan_failed_trace():
    buf = ReplayBuffer()
    t = _build_trace(0, forbidden_scan=False)
    with pytest.raises(ValueError, match="forbidden_scan_passed=False"):
        buf.add_trace(t)


def test_buffer_keeps_ineligible_trace_but_not_in_eligible_list():
    buf = ReplayBuffer()
    t = _build_trace(0, source_visibility=False)
    assert buf.add_trace(t) is False  # ineligible
    assert len(buf.list_eligible_traces()) == 0
    assert len(buf.list_all_traces()) == 1


# ---------------- split ------------------------------------------------------


def test_buffer_splits_60_20_20_approximately():
    buf = ReplayBuffer()
    for i in range(100):
        buf.add_trace(_build_trace(i))
    splits = [buf.get_split(f"ERT-test-{i:03d}") for i in range(100)]
    train = sum(1 for s in splits if s == "evolve_train")
    val = sum(1 for s in splits if s == "gate_validation")
    held = sum(1 for s in splits if s == "held_out_test")
    # 比例 60/20/20，允许 ±15% 误差（hash 分布不严格均匀）
    assert 45 <= train <= 75
    assert 5 <= val <= 35
    assert 5 <= held <= 35
    # 总和守恒
    assert train + val + held == 100


def test_buffer_list_split_returns_eligible_only():
    buf = ReplayBuffer()
    for i in range(20):
        buf.add_trace(_build_trace(i))
    train_traces = buf.list_split("evolve_train")
    assert all(t.forbidden_scan_passed for t in train_traces)


# ---------------- failure pattern aggregate ---------------------------------


def test_buffer_aggregate_failure_patterns_groups_by_4tuple():
    buf = ReplayBuffer()
    # 7 个 trace，5 个共享同 (family, slot, kind, reason)
    for i in range(5):
        buf.add_trace(
            _build_trace(
                i,
                rule_families=["mbis.reporting.x"],
                obligation_kinds=["report_field"],
                semantic_slot_classes=["artifact_evidence"],
                open_reason="missing_artifact_evidence",
            )
        )
    for i in range(5, 7):
        buf.add_trace(
            _build_trace(
                i,
                rule_families=["mbis.escalation.y"],
                obligation_kinds=["action"],
                semantic_slot_classes=["actor"],
                open_reason="depends_on_open_trigger",
            )
        )
    patterns = buf.aggregate_failure_patterns()
    high_freq = (
        "mbis.reporting.x",
        "artifact_evidence",
        "report_field",
        "missing_artifact_evidence",
    )
    assert high_freq in patterns
    assert len(patterns[high_freq]) == 5


# ---------------- success pattern aggregate ---------------------------------


def test_buffer_aggregate_success_patterns_groups_by_skill_set_and_tools():
    buf = ReplayBuffer()
    for i in range(5):
        steps = [
            EvoRunStep(
                step_id=f"ERS-{i}-0",
                trace_id=f"ERT-test-{i:03d}",
                seq=0,
                stage="fact_retrieval",
                tool_name="retrieve_building_facts",
                created_at="2026-05-24T00:00:00Z",
            ),
            EvoRunStep(
                step_id=f"ERS-{i}-1",
                trace_id=f"ERT-test-{i:03d}",
                seq=1,
                stage="rule_retrieval",
                tool_name="retrieve_applicable_rules",
                created_at="2026-05-24T00:00:00Z",
            ),
        ]
        buf.add_trace(_build_trace(i, steps=steps, active_skill_set_id="SS-fast"))
    patterns = buf.aggregate_success_patterns()
    expected = ("SS-fast", "retrieve_building_facts", "retrieve_applicable_rules")
    assert expected in patterns
    assert len(patterns[expected]) == 5


# ---------------- freeze replay set -----------------------------------------


def test_buffer_freeze_and_get_replay_set():
    buf = ReplayBuffer()
    for i in range(5):
        buf.add_trace(_build_trace(i))
    h = buf.freeze_replay_set("RS-test", [f"ERT-test-{i:03d}" for i in range(5)])
    assert h.startswith("sha256:")
    traces = buf.get_replay_set("RS-test")
    assert len(traces) == 5


def test_buffer_freeze_rejects_unknown_trace_id():
    buf = ReplayBuffer()
    buf.add_trace(_build_trace(0))
    with pytest.raises(ValueError, match="未在 buffer"):
        buf.freeze_replay_set("RS-bad", ["ERT-test-000", "ERT-missing-999"])


def test_buffer_freeze_rejects_ineligible_trace():
    buf = ReplayBuffer()
    buf.add_trace(_build_trace(0, source_visibility=False))  # ineligible
    with pytest.raises(ValueError, match="非 eligible"):
        buf.freeze_replay_set("RS-bad", ["ERT-test-000"])


def test_buffer_get_unknown_replay_set_raises():
    buf = ReplayBuffer()
    with pytest.raises(KeyError):
        buf.get_replay_set("RS-nonexistent")


# ---------------- effective weight ------------------------------------------


def test_buffer_compute_effective_weight_eligible_no_novelty():
    buf = ReplayBuffer()
    t = _build_trace(0)
    w = buf.compute_effective_weight(t, has_feedback=False, coverage_class="common")
    assert w == 1.0


def test_buffer_compute_effective_weight_with_novelty_decay():
    buf = ReplayBuffer()
    t = _build_trace(0)
    # novelty_seen_count 给 100 次 → 1/sqrt(101) ≈ 0.0995；下限 0.2 兜底
    w = buf.compute_effective_weight(
        t,
        novelty_seen_count={
            ("mbis.reporting.x", "artifact_evidence", "report_field", "missing_fact"): 100
        },
        has_feedback=True,
        coverage_class="rare",
    )
    # novelty=0.2 × validity=1 × coverage=1.5 × feedback=1.2 = 0.36
    assert 0.30 < w < 0.40


def test_buffer_compute_effective_weight_ineligible_yields_zero():
    buf = ReplayBuffer()
    t = _build_trace(0, source_visibility=False)
    w = buf.compute_effective_weight(t)
    assert w == 0.0


# ---------------- filesystem backend ----------------------------------------


def test_buffer_filesystem_backend_writes_json(tmp_path: Path):
    buf = ReplayBuffer(backend="filesystem", store_dir=tmp_path)
    buf.add_trace(_build_trace(0))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_buffer_filesystem_requires_store_dir():
    with pytest.raises(ValueError, match="filesystem backend 必须给 store_dir"):
        ReplayBuffer(backend="filesystem")
