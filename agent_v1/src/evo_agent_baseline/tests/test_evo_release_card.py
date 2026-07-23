"""EvoReleaseCard DTO 测试（spec v1 §3.6.6 + §11.6 + §11.8 + B.8）。

覆盖：
- DTO 能从 §11.8 示例 dict 实例化（spec v1 line 2984-3001）；
- spec §11.6 / §9.7 release card 必须含字段（hard required）；
- spec v1 §11.6 ``没有 ReleaseCard 的 Skill / Policy 不能成为 scaling law
  论文曲线上的点`` → DTO 是发布门禁的元数据载体；
- artifact_type Literal 限定 3 类（skill / policy / skill_set）；
- 4 个 audit bool 字段必填（leakage / reconstruction / closure_non_regression /
  candidate_floor）；
- extra="forbid"：未声明字段必须被拒绝（spec→code 单向）。

**v1.1 修订（spec §0.6 修订 2 + §3.6.6）**：删除 ``rollback_condition`` /
``canary_plan`` 字段（实验室阶段用 git revert 回滚，无 canary 假设）。本测试
验证这两个字段已不存在；构造时传入它们应触发 ``extra='forbid'`` ValidationError。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evo_agent_baseline.contracts import EvoReleaseCard


# spec v1 §3.6.6 + §11.6 必填字段（v1.1 简化后；去掉 rollback_condition / canary_plan）
SPEC_V1_REQUIRED_FIELDS = {
    "release_card_id",
    "artifact_type",
    "artifact_version_id",
    "effective_trace_count",
    "n_valid_runs",
    "n_effective_traces",
    "n_active_skills",
    "n_effective_skills",
    "heldout_metric_summary",
    "ablation_delta",
    "leakage_audit_passed",
    "reconstruction_audit_passed",
    "closure_non_regression_passed",
    "candidate_floor_passed",
    "created_at",
}


def _minimal_payload() -> dict:
    """spec v1 §11.8 学习曲线示例（line 2984-3001）扩展为 DTO 完整 payload。

    v1.1 §0.6 修订 2：去掉 ``rollback_condition`` / ``canary_plan`` 字段。
    """
    return {
        "release_card_id": "ERC-policy.mbis.runtime.default.v1.2.0",
        "artifact_type": "policy",
        "artifact_version_id": "policy.mbis.runtime.default.v1.2.0",
        "effective_trace_count": 96.0,  # §11.8 N_effective_traces
        "n_valid_runs": 110,
        "n_effective_traces": 96,
        "n_active_skills": 14,
        "n_effective_skills": 9,
        "heldout_metric_summary": {
            "family_recall": 0.70,
            "slot_requirement_recall": 0.65,
            "blocked_rate": 0.32,
            "report_citation_coverage": 0.91,
        },
        "ablation_delta": {
            "full_evo_vs_baseline_static": {"family_recall": 0.20}
        },
        "leakage_audit_passed": True,
        "reconstruction_audit_passed": True,
        "closure_non_regression_passed": True,
        "candidate_floor_passed": True,
        "created_at": "2026-05-24T10:00:00Z",
    }


def test_evo_release_card_v1_1_rollback_condition_field_removed() -> None:
    """v1.1 §0.6 修订 2 + §3.6.6：``rollback_condition`` 字段已删除。

    构造时传入应触发 ``extra='forbid'`` ValidationError。
    """
    payload = _minimal_payload()
    payload["rollback_condition"] = {"max_blocked_rate": 0.5}
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_v1_1_canary_plan_field_removed() -> None:
    """v1.1 §0.6 修订 2 + §3.6.6：``canary_plan`` 字段已删除。

    构造时传入应触发 ``extra='forbid'`` ValidationError。
    """
    payload = _minimal_payload()
    payload["canary_plan"] = {"window_count": 3, "rollout_pct": 0.1}
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_instantiates_from_spec_example() -> None:
    """spec v1 §11.8 示例 dict → EvoReleaseCard 实例化通过."""
    card = EvoReleaseCard(**_minimal_payload())
    assert card.release_card_id == "ERC-policy.mbis.runtime.default.v1.2.0"
    assert card.artifact_type == "policy"
    assert card.effective_trace_count == pytest.approx(96.0)
    assert card.n_valid_runs == 110
    assert card.leakage_audit_passed is True


def test_evo_release_card_field_set_matches_spec_required() -> None:
    """DTO 字段集合应包含 spec v1 §11.6 + §9.7 所有必填字段。"""
    actual_fields = set(EvoReleaseCard.model_fields.keys())
    missing = SPEC_V1_REQUIRED_FIELDS - actual_fields
    assert not missing, f"DTO 缺 spec v1 必填字段: {missing}"


def test_evo_release_card_artifact_type_literal_enforced() -> None:
    """spec v1 §11.6 + B.8 artifact_type 必须是 skill/policy/skill_set 之一."""
    payload = _minimal_payload()
    payload["artifact_type"] = "unknown_type"
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_artifact_type_accepts_skill() -> None:
    payload = _minimal_payload()
    payload["artifact_type"] = "skill"
    payload["artifact_version_id"] = "skill.mbis.retrieval_macro.x.v1"
    card = EvoReleaseCard(**payload)
    assert card.artifact_type == "skill"


def test_evo_release_card_artifact_type_accepts_skill_set() -> None:
    payload = _minimal_payload()
    payload["artifact_type"] = "skill_set"
    card = EvoReleaseCard(**payload)
    assert card.artifact_type == "skill_set"


def test_evo_release_card_rejects_extra_fields() -> None:
    """spec→code 单向：model_config={'extra':'forbid'} 必须拦截未授权字段。"""
    payload = _minimal_payload()
    payload["unauthorized_field"] = "leak attempt"
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_audit_booleans_all_required() -> None:
    """spec v1 §11.6 / §13.3 release gate 要求 4 个 audit bool 全 True 才能 active。

    DTO 层不强制 True，但字段不能缺（缺字段 ValidationError）。
    """
    for missing_field in (
        "leakage_audit_passed",
        "reconstruction_audit_passed",
        "closure_non_regression_passed",
        "candidate_floor_passed",
    ):
        payload = _minimal_payload()
        del payload[missing_field]
        with pytest.raises(ValidationError):
            EvoReleaseCard(**payload)


def test_evo_release_card_failed_audit_still_constructs() -> None:
    """spec v1 §13.3 audit fail → release gate 拒绝 active；但 DTO 本身允许
    构造 failed card（rollback / quarantine 路径需要它）。
    """
    payload = _minimal_payload()
    payload["leakage_audit_passed"] = False
    card = EvoReleaseCard(**payload)
    assert card.leakage_audit_passed is False
    # caller 自行判定 active gating


def test_evo_release_card_effective_trace_count_float() -> None:
    """effective_trace_count 必须 float（spec §11.6 字段类型）."""
    payload = _minimal_payload()
    payload["effective_trace_count"] = "not-a-number"
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_n_effective_skills_int() -> None:
    """n_effective_skills 必须 int."""
    payload = _minimal_payload()
    payload["n_effective_skills"] = 9.7
    # pydantic v2 默认会拒绝 float→int 当值非整数
    with pytest.raises(ValidationError):
        EvoReleaseCard(**payload)


def test_evo_release_card_serializes_with_all_required_fields() -> None:
    """model_dump 输出应至少含所有 spec required 字段。"""
    card = EvoReleaseCard(**_minimal_payload())
    dumped = card.model_dump()
    for key in SPEC_V1_REQUIRED_FIELDS:
        assert key in dumped, f"序列化结果缺 {key}"
