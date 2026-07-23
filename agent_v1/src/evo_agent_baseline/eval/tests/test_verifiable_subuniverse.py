"""可核验子宇宙口径（2026-07-08 用户裁定门③选项3）。"""

from __future__ import annotations

from evo_agent_baseline.contracts import Obligation
from evo_agent_baseline.eval.mapper import aggregate_agent_family_verdicts


def _ob(kind, closure, satisfaction, fam="mbis.repair.x.f1", oid="o1"):
    return Obligation(
        obligation_id=oid, run_id="R1", world_id="W1", building_id="B1",
        source_rule_card_id="rc.x", source_family_id=fam,
        kind=kind, closure_status=closure, satisfaction_status=satisfaction,
        fragment_id="FR1",
        open_reason_code="missing_fact" if closure == "open" else None,
    )


def test_action_open_excluded_family_becomes_determinate() -> None:
    """全宇宙：action open 压 unknown；可核验子宇宙：剔除后 satisfied → pass。"""
    obs = [
        _ob("action", "open", "unknown", oid="o1"),
        _ob("threshold", "closed", "satisfied", oid="o2"),
        _ob("evidence", "closed", "satisfied", oid="o3"),
    ]
    full = aggregate_agent_family_verdicts(obs)
    assert full[0].verdict == "unknown"
    ver = aggregate_agent_family_verdicts(obs, exclude_kinds={"action"})
    assert ver[0].verdict == "pass"


def test_violated_survives_in_verifiable_universe() -> None:
    obs = [
        _ob("action", "open", "unknown", oid="o1"),
        _ob("threshold", "closed", "violated", oid="o2"),
    ]
    ver = aggregate_agent_family_verdicts(obs, exclude_kinds={"action"})
    assert ver[0].verdict == "fail"


def test_action_only_family_drops_out() -> None:
    """全是 action 的家族在子宇宙口径下不出 verdict（分母诚实收缩）。"""
    obs = [_ob("action", "open", "unknown", oid="o1")]
    assert aggregate_agent_family_verdicts(obs, exclude_kinds={"action"}) == []
