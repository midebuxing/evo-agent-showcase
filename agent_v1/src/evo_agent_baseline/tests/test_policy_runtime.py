"""policy_runtime 测试（Codex review 2026-05-27 A1[P1] 修复覆盖）."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from evo_agent_baseline.agent.hooks import SecurityError
from evo_agent_baseline.agent.policy_runtime import (
    VERIFIER_FLOOR_LITERAL,
    load_active_policy,
    load_policy_for_bootstrap,
)


# ---------------- fixture --------------------------------------------------


def _valid_policy(status: str = "active") -> Dict[str, Any]:
    """构造 schema 合法的 EvoPolicyVersion dict（contracts.py B.4 必填字段）。"""
    return {
        "policy_id": "policy.mbis.runtime.default",
        "policy_version_id": f"EPV-policy.mbis.runtime.default-{status}-0001",
        "version": "1.0.0",
        "status": status,
        "ranking_weights": {
            "base_fulltext_score": 1.0,
            "skill_trigger_boost": 0.5,
        },
        "candidate_cutoff_policy": {
            "context_top_k": 80,
            "verifier_floor": VERIFIER_FLOOR_LITERAL,
        },
        "trained_on_replay_set_id": "RS-0001",
        "trained_on_artifacts": [],
        "created_at": "2026-05-27T00:00:00Z",
    }


# ---------------- A1[P1]: runtime 强制 active-only --------------------------


def test_load_active_policy_accepts_active() -> None:
    p = load_active_policy("policy.mbis.runtime.default", policy_dict=_valid_policy("active"))
    assert p.status == "active"


def test_load_active_policy_rejects_draft() -> None:
    """Codex A1[P1]: runtime 加载 draft policy 是 spec 违反（未过 5 道 Gate）."""
    with pytest.raises(SecurityError, match="status='draft'"):
        load_active_policy(
            "policy.mbis.runtime.default", policy_dict=_valid_policy("draft")
        )


def test_load_active_policy_rejects_retired() -> None:
    with pytest.raises(SecurityError, match="status='retired'"):
        load_active_policy(
            "policy.mbis.runtime.default", policy_dict=_valid_policy("retired")
        )


def test_load_active_policy_allow_non_active_bypass() -> None:
    """bootstrap 场景显式传 allow_non_active=True 应放行。"""
    p = load_active_policy(
        "policy.mbis.runtime.default",
        policy_dict=_valid_policy("draft"),
        allow_non_active=True,
    )
    assert p.status == "draft"


# ---------------- bootstrap loader ----------------------------------------


def test_load_policy_for_bootstrap_accepts_draft() -> None:
    p = load_policy_for_bootstrap(
        "policy.mbis.runtime.default", policy_dict=_valid_policy("draft")
    )
    assert p.status == "draft"


def test_load_policy_for_bootstrap_accepts_active() -> None:
    p = load_policy_for_bootstrap(
        "policy.mbis.runtime.default", policy_dict=_valid_policy("active")
    )
    assert p.status == "active"


def test_load_policy_for_bootstrap_still_runs_publish_guard() -> None:
    """bootstrap 仍跑 pre_policy_publish_guard 校验 schema 字段约束."""
    bad = _valid_policy("draft")
    bad["candidate_cutoff_policy"]["verifier_floor"] = "DISABLED"  # 违反不变量
    with pytest.raises(SecurityError):
        load_policy_for_bootstrap("policy.mbis.runtime.default", policy_dict=bad)
