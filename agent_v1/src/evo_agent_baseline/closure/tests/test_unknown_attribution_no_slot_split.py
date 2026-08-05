"""`no_slot_declared` / `non_slot_handle` 结构兜底专项（验证器两码皆空时）。

v3 起：有验证器原因码时优先透传/分流，这两码只在两码皆空时作为最后手段。
判据纯结构：`has_slot_handle` 假 + `validator_reason_code is None` 时，
按 `has_obligation_node` 拆——有节点 → `no_slot_declared`；无节点 → `non_slot_handle`。
"""

from __future__ import annotations

from evo_agent_baseline.closure.tests.fixtures import (
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)
from evo_agent_baseline.closure.unknown_attribution import (
    UnknownObligationSnapshot,
    attribute_unknown_obligations,
)


def _snap(
    oid: str,
    *,
    has_obligation_node: bool,
    other_fact_handles=(),
    validator_reason_code=None,
    trigger_state: str = "not_evaluated",
) -> UnknownObligationSnapshot:
    return UnknownObligationSnapshot(
        obligation_id=oid,
        closure_status="open",
        fragment_id=None,
        canonical_slot_ids=(),
        declared_qualifiers=frozenset(),
        trigger_dependency_ids=(),
        depends_on_open_trigger=False,
        kind="action" if has_obligation_node else "artifact",
        action="inspect" if has_obligation_node else None,
        has_slot_handle=False,
        has_obligation_node=has_obligation_node,
        other_fact_handles=tuple(other_fact_handles),
        validator_reason_code=validator_reason_code,
        trigger_state=trigger_state,
    )


def test_graph_node_without_slot_stays_no_slot_declared_when_no_validator_code():
    mapping = attribute_unknown_obligations(
        [_snap("O.node", has_obligation_node=True)],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )
    attr = mapping["O.node"]
    assert attr.cause_code == "no_slot_declared"
    assert "义务图节点" in attr.explanation
    assert "不需要你补录资料" in attr.explanation


def test_non_node_without_slot_becomes_non_slot_handle_when_no_validator_code():
    mapping = attribute_unknown_obligations(
        [_snap("O.art", has_obligation_node=False, other_fact_handles=("artifact_ids",))],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )
    attr = mapping["O.art"]
    assert attr.cause_code == "non_slot_handle"
    assert "不是系统漏查了事实槽" in attr.explanation
    assert "文件/表格" in attr.explanation
    assert "不需要你补录资料" in attr.explanation
    assert "已对" not in attr.explanation
    assert "做过判断" not in attr.explanation


def test_validator_code_outranks_structural_noslot():
    """🔴 核心：有验证器码时不得落结构兜底。"""
    snap = _snap(
        "O",
        has_obligation_node=True,
        validator_reason_code="missing_satisfaction_binding",
    )
    attr = attribute_unknown_obligations(
        [snap],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O"]
    assert attr.cause_code == "missing_satisfaction_binding"
    assert attr.cause_code != "no_slot_declared"


def test_trigger_blocked_outranks_structural_noslot_and_passthrough():
    """卡级触发器 blocked → upstream_trigger_blocked，即使带着 missing_rule_edge。"""
    snap = _snap(
        "O",
        has_obligation_node=True,
        validator_reason_code="missing_rule_edge",
        trigger_state="blocked",
    )
    attr = attribute_unknown_obligations(
        [snap],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O"]
    assert attr.cause_code == "upstream_trigger_blocked"


def test_split_is_only_by_obligation_node_flag():
    """变异闸：故意把节点旗标弄反时，归属必须跟着变（证明旗标在判据里）。"""
    nodeish = _snap("O", has_obligation_node=True, other_fact_handles=("artifact_ids",))
    non_node = _snap("O", has_obligation_node=False, other_fact_handles=("artifact_ids",))
    a_node = attribute_unknown_obligations(
        [nodeish],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O"]
    a_non = attribute_unknown_obligations(
        [non_node],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O"]
    assert a_node.cause_code == "no_slot_declared"
    assert a_non.cause_code == "non_slot_handle"
    assert a_node.cause_code != a_non.cause_code


def test_end_to_end_validator_codes_outrank_structural_split():
    """端到端：有验证器码时走透传，不再落 no_slot_declared / non_slot_handle。"""
    node_card = make_rule_card(
        "RC.split.node",
        family_id="FAM.split",
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N.split",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                }
            ],
            "edges": [],
        },
    )
    art_card = make_rule_card(
        "RC.split.art",
        family_id="FAM.split2",
        workflow_operands={
            "primary_actor": "ri",
            "primary_action": "submit_form",
            "recipients": [],
            "artifacts": [
                {
                    "artifact_id": "A.split",
                    "artifact_type": "",
                    "artifact_key": "proposal.supervision",
                }
            ],
            "deadlines": [],
            "audiences": [],
            "method_keys_allowed": [],
        },
    )
    result = run_closure(
        make_rule_slice([node_card, art_card]), make_fact_pack([])
    )
    mapping = result.unknown_attribution_by_obligation_id
    by_id = {o.obligation_id: o for o in result.obligation_set.obligations}

    node_codes = {
        mapping[oid].cause_code
        for oid, o in by_id.items()
        if o.obligation_node_id and oid in mapping
    }
    art_codes = {
        mapping[oid].cause_code
        for oid, o in by_id.items()
        if (not o.obligation_node_id)
        and (o.artifact_ids or o.artifact_keys)
        and not (o.slot_ids or o.slot_ref_ids)
        and oid in mapping
    }
    assert "missing_satisfaction_binding" in node_codes
    assert "artifact_not_modeled_upstream" in art_codes
    assert "no_slot_declared" not in node_codes
    assert "non_slot_handle" not in art_codes


def test_mutation_flipping_node_flag_in_snapshot_builder_path():
    """变异验证：把快照上的 has_obligation_node 改坏 → 端到端断言必须红。"""
    lied = _snap("O.lied", has_obligation_node=True, other_fact_handles=("artifact_ids",))
    attr = attribute_unknown_obligations(
        [lied],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O.lied"]
    assert attr.cause_code == "no_slot_declared"
    lied2 = _snap("O.lied2", has_obligation_node=False)
    attr2 = attribute_unknown_obligations(
        [lied2],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
    )["O.lied2"]
    assert attr2.cause_code == "non_slot_handle"
