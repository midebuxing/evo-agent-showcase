"""闭包验证器 spec §6.9 测试表 + allow_stop 规则 + 端到端推导。

覆盖 spec §6.9 列出的 9 个测试用例 + §6.5 allow_stop 全分支。
"""

from __future__ import annotations

import json

import pytest

from evo_agent_baseline.closure import (
    ForbiddenSourceError,
    validate_building_closure,
)
from evo_agent_baseline.closure.identity_v2 import ObligationContractError
from evo_agent_baseline.closure.validator import (
    PENDING_CARD_TRIGGER_PLACEHOLDER,
    backfill_trigger_dependency_ids,
    compute_allow_stop_and_reason,
    compute_obligation_id_v1,
    display_obligation_id,
)
from evo_agent_baseline.contracts import Obligation

from .fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)


# ===================================================================== #
# identity-v5 现网键切换：把松散测试卡补成严格 schema 合规的构造辅助。
# 只补 DTO 必填字段 / 换禁止字段的语义等价严格键；float 判定读的字段（slot_id 经
# slot_ref_id→slot_role_map 解析、expected_value、operator、measure_key、artifact_key、
# formula.expression 等）保持等值 → 判定语义不变。
# ===================================================================== #
def _wf(**kw):
    """workflow_operands 全 7 字段容器（WorkflowOperandsDTO 必填），只填传入子字段。"""
    base = {
        "primary_actor": "",
        "primary_action": "",
        "recipients": [],
        "artifacts": [],
        "deadlines": [],
        "audiences": [],
        "method_keys_allowed": [],
    }
    base.update(kw)
    return base


def _art(artifact_key, artifact_id="A.auto", artifact_type=""):
    """WorkflowArtifactDTO 必填三字段（float 只读 artifact_key）。"""
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "artifact_key": artifact_key,
    }


def _evreqs(matching=None, submission=None, completion=None):
    """evidence_requirements 三 bucket 容器（EvidenceRequirementsDTO 必填）。"""
    return {
        "for_matching": matching or [],
        "for_submission": submission or [],
        "for_completion": completion or [],
    }


def _evreq(rid, *, slot_ref_ids=None, kind="evidence", required=True):
    """EvidenceRequirementDTO 必填八字段（float 经 slot_ref_ids→slot_role_map 解引用）。"""
    return {
        "evidence_requirement_id": rid,
        "kind": kind,
        "required": required,
        "description": "",
        "artifact_ids": [],
        "slot_ref_ids": slot_ref_ids or [],
        "measure_keys": [],
        "required_field_groups": [],
    }


def _srole(slot_ref_id, slot_id, *, role="evidence", required=True, qualifiers=None):
    """SlotRoleDTO 必填五字段（roles 复数 + qualifiers）。float evaluate_slot_role 只对
    role=evidence（含默认）语义等价；此处仅用于 evidence 引用/触发器解引用（required=False
    时 float 不生成额外 slot_role 义务）。"""
    return {
        "slot_ref_id": slot_ref_id,
        "slot_id": slot_id,
        "roles": [role],
        "required": required,
        "qualifiers": qualifiers or {},
    }


def _thr(**kw):
    """threshold_regimes[] 一项：补 ThresholdRegimeDTO 必填（unit/qualifiers/source_quote_refs）。"""
    base = {"unit": "", "qualifiers": {}, "source_quote_refs": []}
    base.update(kw)
    return base


def _defn(definition_id, *, source_quote_refs=None):
    """DefinitionDTO 必填五字段（真实字段 term_key/definition_text/scope_note/
    source_quote_refs；DEBT-057 后 float evaluate_definition 与蓝图端均读取列表引用）。"""
    return {
        "definition_id": definition_id,
        "term_key": "",
        "definition_text": "",
        "scope_note": "",
        "source_quote_refs": source_quote_refs or [],
    }


# ===================================================================== #
# §6.9 test_blind_inputs —— RuleSlice / FactPack 含禁止字段 hard fail
# ===================================================================== #
def test_blind_inputs_factpack_forbidden_property():
    """FactPack provenance 含 expected_verdict → hard fail。"""
    fp = make_fact_pack([make_fact("F1", slot_id="s", value="v")])
    fp.facts[0].provenance = {"expected_verdict": "pass"}
    rs = make_rule_slice([make_rule_card()])
    with pytest.raises(ForbiddenSourceError):
        run_closure(rs, fp)


def test_blind_inputs_ruleslice_forbidden_property():
    """RuleSlice retrieval_policy 含 projection_id → hard fail。"""
    fp = make_fact_pack([make_fact("F1", slot_id="s", value="v")])
    rs = make_rule_slice([make_rule_card()])
    rs.retrieval_policy = {"projection_id": "PRJ-1"}
    with pytest.raises(ForbiddenSourceError):
        run_closure(rs, fp)


def test_blind_inputs_forbidden_source_table():
    """source_tables 含 W2 表名 → hard fail。"""
    fp = make_fact_pack([make_fact("F1", slot_id="s", value="v")])
    fp.source_tables = ["projections.parquet"]
    rs = make_rule_slice([make_rule_card()])
    with pytest.raises(ForbiddenSourceError):
        run_closure(rs, fp)


def test_clean_inputs_pass_guard():
    """干净输入不触发禁止源守卫。"""
    fp = make_fact_pack([make_fact("F1", slot_id="s", value="v")])
    rs = make_rule_slice([make_rule_card()])
    result = run_closure(rs, fp)
    assert result.machine_readable_report["source_guard"][
        "forbidden_source_check_passed"
    ]


# ===================================================================== #
# §6.9 test_formula_json_preserved —— formula threshold 能读 formula_json
# ===================================================================== #
def test_formula_json_preserved():
    """threshold_regime 的 formula_json 不丢失，能被评估器读到。"""
    card = make_rule_card(
        threshold_regimes=[
            _thr(
                threshold_regime_id="TR1",
                operator="formula",
                measure_key="count.pull_test.additional_after_failure",
                formula={
                    "expression": "n^2 - 2n + 3",
                    "variables": [
                        {
                            "measure_key": "count.pull_test.failed_cumulative",
                            "symbol": "n",
                        }
                    ],
                },
            )
        ]
    )
    facts = [
        make_fact(
            "Fn",
            measure_key="count.pull_test.failed_cumulative",
            value=2,
            value_type="number",
            carrier_type="measurement",
        ),
        make_fact(
            "Fo",
            measure_key="count.pull_test.additional_after_failure",
            value=3,
            value_type="number",
            carrier_type="measurement",
        ),
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    thr = [
        o for o in result.obligation_set.obligations if o.kind == "threshold"
    ]
    assert len(thr) == 1
    # formula 被识别并走 handler（非 unsupported_formula）。
    assert thr[0].blocked_reason_code != "unsupported_formula"


# ===================================================================== #
# §6.9 test_formula_handler_pull_test —— n^2-2n+3 handler 确定值
# ===================================================================== #
def test_formula_handler_pull_test_satisfied():
    """n=2 → expected=2*2-2*2+3=3；observed=5>=3 → closed+satisfied。"""
    card = make_rule_card(
        threshold_regimes=[
            _thr(
                threshold_regime_id="TR1",
                operator="formula",
                measure_key="count.pull_test.additional_after_failure",
                formula={
                    "expression": "n^2 - 2n + 3",
                    "variables": [
                        {
                            "measure_key": "count.pull_test.failed_cumulative",
                            "symbol": "n",
                        }
                    ],
                },
            )
        ]
    )
    facts = [
        make_fact(
            "Fn",
            measure_key="count.pull_test.failed_cumulative",
            value=2,
            value_type="number",
            carrier_type="measurement",
        ),
        make_fact(
            "Fo",
            measure_key="count.pull_test.additional_after_failure",
            value=5,
            value_type="number",
            carrier_type="measurement",
        ),
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    thr = [o for o in result.obligation_set.obligations if o.kind == "threshold"][0]
    assert thr.closure_status == "closed"
    assert thr.satisfaction_status == "satisfied"
    assert json.loads(thr.expected_value_json) == 3


def test_formula_handler_pull_test_violated():
    """n=3 → expected=3*3-2*3+3=6；observed=4<6 → closed+violated。"""
    card = make_rule_card(
        threshold_regimes=[
            _thr(
                threshold_regime_id="TR1",
                operator="formula",
                measure_key="count.pull_test.additional_after_failure",
                formula={
                    "expression": "n**2 - 2*n + 3",
                    "variables": [
                        {
                            "measure_key": "count.pull_test.failed_cumulative",
                            "symbol": "n",
                        }
                    ],
                },
            )
        ]
    )
    facts = [
        make_fact(
            "Fn",
            measure_key="count.pull_test.failed_cumulative",
            value=3,
            value_type="number",
            carrier_type="measurement",
        ),
        make_fact(
            "Fo",
            measure_key="count.pull_test.additional_after_failure",
            value=4,
            value_type="number",
            carrier_type="measurement",
        ),
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    thr = [o for o in result.obligation_set.obligations if o.kind == "threshold"][0]
    assert thr.closure_status == "closed"
    assert thr.satisfaction_status == "violated"
    assert json.loads(thr.expected_value_json) == 6


def test_formula_unknown_blocked():
    """非白名单 formula → catalog 层 fail-closed 硬前置。

    identity-v5 现网键切换后：非法结构由 catalog 层 fail-closed 硬前置（旧 float 软 blocked
    路径活动流不可达）。
    """
    card = make_rule_card(
        threshold_regimes=[
            _thr(
                threshold_regime_id="TR1",
                operator="formula",
                measure_key="m.x",
                formula={
                    "expression": "3*x + 1",
                    "variables": [{"measure_key": "m.x", "symbol": "x"}],
                },
            )
        ]
    )
    with pytest.raises(ObligationContractError) as exc:
        run_closure(make_rule_slice([card]), make_fact_pack([]))
    assert "unsupported_formula" in str(exc.value)


# ===================================================================== #
# §6.9 test_obligation_node_derivation —— 每个 node 至少 1 条 obligation
# ===================================================================== #
def test_obligation_node_derivation():
    """obligation_graph.nodes[] 每个 node 至少生成一条 obligation。"""
    card = make_rule_card(
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N1",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                },
                {
                    "obligation_node_id": "N2",
                    "node_kind": "prohibition",
                    "actor": "ri",
                    "action": "skip_required_check",
                },
                {
                    "obligation_node_id": "N3",
                    "node_kind": "escalation",
                    "actor": "ri",
                    "action": "escalate_to_bd",
                },
            ]
        }
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    node_ids = {
        o.obligation_node_id
        for o in result.obligation_set.obligations
        if o.obligation_node_id
    }
    assert {"N1", "N2", "N3"} <= node_ids


# ===================================================================== #
# §6.9 test_obligation_edges —— 含 edge 的卡生成 edge obligations
# ===================================================================== #
def test_obligation_edges_inactive_target():
    """source 未违反 → if_failed_then target 未激活 → inactive audit obligation。"""
    card = make_rule_card(
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N1",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                },
                {
                    "obligation_node_id": "N2",
                    "node_kind": "escalation",
                    "actor": "ri",
                    "action": "escalate",
                },
            ],
            "edges": [
                {
                    "obligation_edge_id": "E1",
                    "source_node_id": "N1",
                    "target_node_id": "N2",
                    "relation": "if_failed_then",
                }
            ],
        }
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    edge_obls = [
        o for o in result.obligation_set.obligations if o.obligation_edge_ids
    ]
    assert len(edge_obls) >= 1
    assert any("inactive_by_obligation_edge" in o.notes for o in edge_obls)


def test_obligation_edges_unknown_relation_blocked():
    """未知 edge relation → source 与 target 均生成 blocked audit obligation。"""
    card = make_rule_card(
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N1",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "x",
                },
                {
                    "obligation_node_id": "N2",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "y",
                },
            ],
            "edges": [
                {
                    "obligation_edge_id": "E1",
                    "source_node_id": "N1",
                    "target_node_id": "N2",
                    "relation": "if_maybe_then",
                }
            ],
        }
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    blocked = [
        o
        for o in result.obligation_set.obligations
        if o.blocked_reason_code == "unsupported_obligation_edge_relation"
    ]
    assert len(blocked) == 2


def test_obligation_edges_missing_target():
    """edge 引用不存在 node → blocked + missing_obligation_edge_target。"""
    card = make_rule_card(
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N1",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "x",
                }
            ],
            "edges": [
                {
                    "obligation_edge_id": "E1",
                    "source_node_id": "N1",
                    "target_node_id": "NX",
                    "relation": "if_failed_then",
                }
            ],
        }
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    assert any(
        o.blocked_reason_code == "missing_obligation_edge_target"
        for o in result.obligation_set.obligations
    )


# ===================================================================== #
# §6.9 test_for_matching_evidence —— for_matching bucket 被消费
# ===================================================================== #
def test_for_matching_evidence_consumed():
    """evidence_requirements.for_matching bucket 必须生成 obligation。"""
    card = make_rule_card(
        slot_role_map=[_srole("SR.match", "evidence.match.slot", required=False)],
        evidence_requirements=_evreqs(
            matching=[_evreq("ER1", slot_ref_ids=["SR.match"])]
        ),
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    # for_matching bucket → kind=evidence。
    ev = [
        o
        for o in result.obligation_set.obligations
        if o.kind == "evidence" and "for_matching" in o.notes
    ]
    assert len(ev) == 1


def test_all_three_evidence_buckets_consumed():
    """for_matching / for_submission / for_completion 三 bucket 全消费。"""
    card = make_rule_card(
        slot_role_map=[
            _srole("SR.match", "s.match", required=False),
            _srole("SR.submit", "s.submit", required=False),
            _srole("SR.complete", "s.complete", required=False),
        ],
        evidence_requirements=_evreqs(
            matching=[_evreq("ER1", slot_ref_ids=["SR.match"])],
            submission=[_evreq("ER2", slot_ref_ids=["SR.submit"])],
            completion=[_evreq("ER3", slot_ref_ids=["SR.complete"])],
        ),
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    buckets = set()
    for o in result.obligation_set.obligations:
        for b in ("for_matching", "for_submission", "for_completion"):
            if b in o.notes:
                buckets.add(b)
    assert buckets == {"for_matching", "for_submission", "for_completion"}


# ===================================================================== #
# §6.9 test_artifact_alias_map —— report.inspection 绑 sidecar artifact.* slot
# ===================================================================== #
def test_artifact_alias_map_report_inspection_satisfied():
    """report.inspection artifact_key truthy fact → closed + satisfied。"""
    card = make_rule_card(
        workflow_operands=_wf(artifacts=[_art("report.inspection", artifact_id="A1")])
    )
    facts = [
        make_fact(
            "F1",
            slot_id="artifact.report.inspection",
            value="present",
            carrier_type="sidecar_entry",
        )
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    art = [o for o in result.obligation_set.obligations if o.kind == "artifact"][0]
    assert art.closure_status == "closed"
    assert art.satisfaction_status == "satisfied"
    assert art.slot_ids == ["artifact.report.inspection"]


def test_artifact_alias_map_falsy_violated():
    """artifact fact falsy → closed + violated。"""
    card = make_rule_card(
        workflow_operands=_wf(artifacts=[_art("report.completion")])
    )
    facts = [
        make_fact("F1", slot_id="artifact.report.completion", value="absent")
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    art = [o for o in result.obligation_set.obligations if o.kind == "artifact"][0]
    assert art.closure_status == "closed"
    assert art.satisfaction_status == "violated"


def test_artifact_alias_map_missing_open():
    """artifact fact 缺失 → open + missing_artifact_evidence。"""
    card = make_rule_card(
        workflow_operands=_wf(artifacts=[_art("form.mbi4")])
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    art = [o for o in result.obligation_set.obligations if o.kind == "artifact"][0]
    assert art.closure_status == "open"
    assert art.open_reason_code == "missing_artifact_evidence"


# ===================================================================== #
# §6.9 test_deterministic_repeatability —— 同输入两次 byte-identical
# ===================================================================== #
def _rich_card():
    """一张涵盖多义务源的卡，用于可复现性测试。

    trigger 用 bool expected_value（严格 TriggerItemDTO expected_value ∈
    {bool,int,Decimal}，不容字符串），配 F1 布尔事实使触发器满足 → 下游各源义务照常
    生成（保持覆盖丰度）；仅可复现性/稳定 id 断言，判定值不入断言。
    """
    return make_rule_card(
        rule_card_id="RC.rich.001",
        trigger_conditions={
            "logic": "all",
            "items": [
                {
                    "condition_id": "C1",
                    "predicate_kind": "slot",
                    "slot_ref_id": "SR.trig",
                    "operator": "==",
                    "expected_value": True,
                }
            ],
        },
        slot_role_map=[
            _srole("SR.trig", "scope.building_use", role="trigger", required=False),
            _srole("SR1", "evidence.x", role="evidence", required=True),
            _srole("SR.m", "s.m", required=False),
        ],
        threshold_regimes=[
            _thr(
                threshold_regime_id="TR1",
                operator=">=",
                measure_key="m.depth",
                value=10,
                unit="mm",
            )
        ],
        workflow_operands=_wf(
            artifacts=[_art("report.inspection")],
            deadlines=[
                {
                    "deadline_id": "D1",
                    "relation": "within",
                    "time_anchor_key": "anchor.rich",
                    "offset_value": 30,
                    "offset_unit": "day",
                }
            ],
        ),
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N1",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "submit_report",
                }
            ]
        },
        evidence_requirements=_evreqs(
            matching=[_evreq("ER1", slot_ref_ids=["SR.m"])]
        ),
        definitions=[_defn("D.term")],
    )


def test_deterministic_repeatability():
    """同一输入两次运行 obligation_set 序列化结果 byte-identical（IT-004）。"""
    facts = [
        make_fact(
            "F1",
            slot_id="scope.building_use",
            value=True,
            value_type="boolean",
            carrier_type="building",
        ),
        make_fact("F2", slot_id="evidence.x", value="present"),
        make_fact(
            "F3",
            measure_key="m.depth",
            value=12,
            value_type="number",
            unit="mm",
            carrier_type="measurement",
        ),
        make_fact("F4", slot_id="artifact.report.inspection", value="present"),
        make_fact(
            "F5",
            slot_id="duration.submission.deadline",
            value=20,
            value_type="number",
            carrier_type="sidecar_entry",
        ),
    ]

    def _run():
        rs = make_rule_slice([_rich_card()])
        fp = make_fact_pack(
            [
                make_fact(
                    f.fact_id,
                    slot_id=f.slot_id,
                    measure_key=f.measure_key,
                    value=json.loads(f.value_json),
                    value_type=f.value_type,
                    unit=f.unit,
                    carrier_type=f.carrier_type,
                )
                for f in facts
            ]
        )
        return run_closure(rs, fp)

    r1 = _run()
    r2 = _run()
    dump1 = r1.obligation_set.model_dump_json(exclude={"created_at"})
    dump2 = r2.obligation_set.model_dump_json(exclude={"created_at"})
    assert dump1 == dump2
    # obligation_id 也应稳定。
    ids1 = [o.obligation_id for o in r1.obligation_set.obligations]
    ids2 = [o.obligation_id for o in r2.obligation_set.obligations]
    assert ids1 == ids2


# ===================================================================== #
# §6.5 allow_stop 规则
# ===================================================================== #
def test_allow_stop_all_closed_satisfied():
    """无 open/blocked/violated → allow_stop=true。"""
    ok, reason = compute_allow_stop_and_reason(0, 0, 0, True, True)
    assert ok is True
    assert reason == "all_applicable_obligations_closed_and_satisfied"


def test_allow_stop_violated_does_not_block():
    """violated>0 但无 open/blocked → 仍 allow_stop=true（spec §6.5.1 重点）。"""
    ok, reason = compute_allow_stop_and_reason(0, 0, 3, True, True)
    assert ok is True
    assert reason == (
        "all_applicable_obligations_closed_with_violations_for_human_review"
    )


def test_allow_stop_open_blocks():
    """open>0 → allow_stop=false。"""
    ok, reason = compute_allow_stop_and_reason(2, 0, 0, True, True)
    assert ok is False
    assert reason == "open_obligations_remain"


def test_allow_stop_blocked_blocks():
    """blocked>0 → allow_stop=false。"""
    ok, reason = compute_allow_stop_and_reason(0, 1, 0, True, True)
    assert ok is False
    assert reason == "blocked_obligations_remain"


def test_allow_stop_forbidden_source():
    """forbidden source check 失败 → allow_stop=false。"""
    ok, reason = compute_allow_stop_and_reason(0, 0, 0, True, False)
    assert ok is False
    assert reason == "forbidden_reference_truth_detected"


def test_allow_stop_schema_fail():
    """schema 校验失败 → allow_stop=false。"""
    ok, reason = compute_allow_stop_and_reason(0, 0, 0, False, True)
    assert ok is False
    assert reason == "schema_validation_failed"


def test_allow_report_generation_equals_allow_stop():
    """spec §6.5.3：allow_report_generation == allow_stop。"""
    card = make_rule_card(
        slot_role_map=[_srole("SR1", "missing.slot", role="evidence", required=True)]
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    assert result.allow_report_generation == result.allow_stop
    # 该 slot fact 缺失 → open → allow_stop false。
    assert result.allow_stop is False


# ===================================================================== #
# §6.7 obligation_id
# ===================================================================== #
def test_obligation_id_deterministic():
    """同字段 obligation 计算出相同 obligation_id。"""
    card = make_rule_card()
    r1 = run_closure(make_rule_slice([card]), make_fact_pack([]))
    r2 = run_closure(make_rule_slice([card]), make_fact_pack([]))
    o1 = r1.obligation_set.obligations
    o2 = r2.obligation_set.obligations
    assert [o.obligation_id for o in o1] == [o.obligation_id for o in o2]
    # id 长度 24（spec §6.7 [:24]）。
    for o in o1:
        assert len(o.obligation_id) == 24


def test_display_obligation_id_format():
    """Display ID 格式 OBL-<short>-<kind>-<hash8>。"""
    card = make_rule_card(
        rule_card_id="RC.test.001",
        slot_role_map=[_srole("SR1", "s", role="evidence", required=True)],
    )
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    o = result.obligation_set.obligations[0]
    disp = display_obligation_id(o)
    assert disp.startswith("OBL-")
    assert o.kind in disp


# ===================================================================== #
# machine_readable_report 结构（§6.6.3）
# ===================================================================== #
def test_machine_report_structure():
    """machine_readable_report 含 spec §6.6.3 规定的全部键，无 W2 字段。"""
    card = make_rule_card()
    result = run_closure(
        make_rule_slice([card]), make_fact_pack([])
    )
    rpt = result.machine_readable_report
    for key in (
        "run_id",
        "world_id",
        "building_id",
        "allow_stop",
        "stop_reason",
        "closure_summary",
        "rule_slice_summary",
        "obligations",
        "high_risk_items",
        "open_items",
        "blocked_items",
        "violated_items",
        "source_guard",
    ):
        assert key in rpt, f"missing key {key}"
    # 禁止 W2 字段。
    blob = json.dumps(rpt)
    assert "expected_verdict" not in blob
    assert "projection_status" not in blob
    assert "basis_items" not in blob


# ===================================================================== #
# §6.3.3 trigger_dependency_ids 二次回填 pass
# ===================================================================== #
def _make_obligation(
    obligation_id: str,
    *,
    source_rule_card_id: str,
    kind: str = "trigger",
    depends_on_open_trigger: bool = False,
    trigger_dependency_ids: list = None,
    closure_status: str = "closed",
    satisfaction_status: str = "satisfied",
) -> Obligation:
    """构造一条最小 Obligation 测回填逻辑。

    closure_status="open" 时按 contracts 不变式补 open_reason_code；
    closure_status="closed" 默认 satisfied / not_applicable / violated 之一。
    """
    open_reason = None
    if closure_status == "open":
        open_reason = (
            "depends_on_open_trigger" if depends_on_open_trigger else "missing_fact"
        )
    return Obligation(
        obligation_id=obligation_id,
        run_id="R-test",
        world_id="WB-test",
        building_id="BLD-test",
        source_rule_card_id=source_rule_card_id,
        source_family_id="FAM.test",
        kind=kind,
        depends_on_open_trigger=depends_on_open_trigger,
        trigger_dependency_ids=trigger_dependency_ids or [],
        trigger_state="open" if depends_on_open_trigger else "not_evaluated",
        closure_status=closure_status,
        satisfaction_status=satisfaction_status,
        open_reason_code=open_reason,
    )


def test_backfill_skips_obligation_without_depends_on_open_trigger():
    """depends_on_open_trigger=False → 不动 trigger_dependency_ids。"""
    obl = _make_obligation(
        "OBL-A",
        source_rule_card_id="RC.1",
        depends_on_open_trigger=False,
        trigger_dependency_ids=["original_value_should_remain"],
    )
    backfill_trigger_dependency_ids([obl], {})
    assert obl.trigger_dependency_ids == ["original_value_should_remain"]


def test_backfill_resolves_condition_id_to_runtime_obligation_id():
    """trigger_dependency_ids 含 condition_id → 解析为对应 trigger 的运行时 obligation_id。"""
    trig = _make_obligation(
        "TRIG-RUNTIME-ID-1",
        source_rule_card_id="RC.1",
        kind="trigger",
        closure_status="open",
        satisfaction_status="unknown",
    )
    downstream = _make_obligation(
        "DOWN-1",
        source_rule_card_id="RC.1",
        kind="action",
        depends_on_open_trigger=True,
        trigger_dependency_ids=["condition_A"],
        closure_status="open",
        satisfaction_status="unknown",
    )
    provenance = {("RC.1", "condition_A", ""): trig}
    backfill_trigger_dependency_ids([trig, downstream], provenance)
    assert downstream.trigger_dependency_ids == ["TRIG-RUNTIME-ID-1"]


def test_backfill_expands_card_placeholder_to_all_card_triggers():
    """trigger_dependency_ids 含占位 `__card_trigger__` → 展开为该卡所有 trigger 的 obligation_id。"""
    trig_a = _make_obligation(
        "TRIG-A", source_rule_card_id="RC.1", kind="trigger",
        closure_status="open", satisfaction_status="unknown",
    )
    trig_b = _make_obligation(
        "TRIG-B", source_rule_card_id="RC.1", kind="trigger",
        closure_status="open", satisfaction_status="unknown",
    )
    other_card_trig = _make_obligation(
        "TRIG-OTHER", source_rule_card_id="RC.2", kind="trigger",
        closure_status="open", satisfaction_status="unknown",
    )
    downstream = _make_obligation(
        "DOWN-1",
        source_rule_card_id="RC.1",
        kind="action",
        depends_on_open_trigger=True,
        trigger_dependency_ids=[PENDING_CARD_TRIGGER_PLACEHOLDER],
        closure_status="open",
        satisfaction_status="unknown",
    )
    provenance = {
        ("RC.1", "cA", ""): trig_a,
        ("RC.1", "cB", ""): trig_b,
        ("RC.2", "cX", ""): other_card_trig,  # 别卡 trigger 不应被展开进 downstream
    }
    backfill_trigger_dependency_ids([trig_a, trig_b, other_card_trig, downstream], provenance)
    # 占位符展开为 RC.1 的两个 trigger（排序去重），不含 RC.2 的
    assert downstream.trigger_dependency_ids == ["TRIG-A", "TRIG-B"]


def test_backfill_falls_back_when_condition_id_not_in_provenance():
    """provenance 找不到对应 condition_id → 保留原值，不破"非空"不变式。"""
    downstream = _make_obligation(
        "DOWN-1",
        source_rule_card_id="RC.1",
        kind="action",
        depends_on_open_trigger=True,
        trigger_dependency_ids=["unknown_condition"],
        closure_status="open",
        satisfaction_status="unknown",
    )
    backfill_trigger_dependency_ids([downstream], {})
    assert downstream.trigger_dependency_ids == ["unknown_condition"]


def test_backfill_dedupes_repeated_references():
    """同 condition_id 出现多次 → 去重后只保留一份。"""
    trig = _make_obligation(
        "TRIG-X", source_rule_card_id="RC.1", kind="trigger",
        closure_status="open", satisfaction_status="unknown",
    )
    downstream = _make_obligation(
        "DOWN-1",
        source_rule_card_id="RC.1",
        kind="action",
        depends_on_open_trigger=True,
        trigger_dependency_ids=["cA", "cA", PENDING_CARD_TRIGGER_PLACEHOLDER],
        closure_status="open",
        satisfaction_status="unknown",
    )
    provenance = {("RC.1", "cA", ""): trig}
    backfill_trigger_dependency_ids([trig, downstream], provenance)
    assert downstream.trigger_dependency_ids == ["TRIG-X"]


def test_backfill_preserves_obligation_id_stability():
    """回填只改 trigger_dependency_ids，不应影响 compute_obligation_id 结果。"""
    trig = _make_obligation(
        "TRIG-Y", source_rule_card_id="RC.1", kind="trigger",
        closure_status="open", satisfaction_status="unknown",
    )
    downstream = _make_obligation(
        "DOWN-1",
        source_rule_card_id="RC.1",
        kind="action",
        depends_on_open_trigger=True,
        trigger_dependency_ids=["cA"],
        closure_status="open",
        satisfaction_status="unknown",
    )
    id_before = compute_obligation_id_v1(downstream)
    provenance = {("RC.1", "cA", ""): trig}
    backfill_trigger_dependency_ids([trig, downstream], provenance)
    id_after = compute_obligation_id_v1(downstream)
    assert id_before == id_after, "回填 trigger_dependency_ids 不应影响 obligation_id（spec §6.7）"


def test_placeholder_constant_matches_deriver_hardcoded_string():
    """validator.PENDING_CARD_TRIGGER_PLACEHOLDER 必须等于 obligation_deriver 里硬编码的占位串。

    obligation_deriver.py 多处用字面量 "__card_trigger__"；如果将来要改名，
    两边必须同步，否则回填 pass 找不到该占位、下游 obligation 永远卡在占位串。
    """
    # obligation_deriver.py 内的占位用法（硬编码字符串）。
    from evo_agent_baseline.closure import obligation_deriver
    src = inspect_source = open(obligation_deriver.__file__, "r", encoding="utf-8").read()
    assert PENDING_CARD_TRIGGER_PLACEHOLDER in src, (
        "obligation_deriver.py 不再含占位常量字面量；要么改 PENDING_CARD_TRIGGER_PLACEHOLDER 同步，"
        "要么改 obligation_deriver 引入该常量"
    )


def test_e2e_validator_resolves_trigger_dependency_to_runtime_id_when_trigger_open():
    """端到端：构造 trigger 取 fact 缺失（→ open）+ obligation_graph node 下游 → trigger_dependency_ids 应是 trigger 的运行时 obligation_id，不含占位 / condition_id。"""
    # trigger 用 slot 但 fact_pack 没有对应 fact → trigger=open
    # 用支持的 operator "==" 让 trigger 走到 slot fact 绑定 → missing → open。
    trigger_conditions = {
        "logic": "all",
        "items": [
            {
                "condition_id": "trig_cond_X",
                "predicate_kind": "slot",
                "slot_ref_id": "SR.missing",
                "operator": "==",
                "expected_value": True,
            }
        ],
    }
    # obligation_graph 一个 node 引用同 condition_id，依赖该 trigger
    obligation_graph = {
        "nodes": [
            {
                "obligation_node_id": "node_1",
                "node_kind": "obligation",
                "trigger_condition_ids": ["trig_cond_X"],
            }
        ],
        "edges": [],
    }
    card = make_rule_card(
        rule_card_id="RC.trigger_open_test",
        trigger_conditions=trigger_conditions,
        slot_role_map=[_srole("SR.missing", "slot.missing", role="trigger", required=False)],
        obligation_graph=obligation_graph,
    )
    fp = make_fact_pack([])  # 空 fact_pack → trigger 找不到 slot fact → open
    rs = make_rule_slice([card])
    result = run_closure(rs, fp)

    # 找出 trigger obligation 和下游 action obligation
    trigs = [o for o in result.obligation_set.obligations if o.kind == "trigger"]
    assert len(trigs) == 1, f"应有 1 条 trigger obligation，实际 {len(trigs)}"
    trig_id = trigs[0].obligation_id

    downstreams = [
        o for o in result.obligation_set.obligations if o.depends_on_open_trigger
    ]
    assert downstreams, "应该有至少一条下游 obligation 因 trigger=open 而 depends_on_open_trigger=True"

    for d in downstreams:
        # 回填后：trigger_dependency_ids 全是运行时 obligation_id
        assert d.trigger_dependency_ids, "depends_on_open_trigger=True 时 trigger_dependency_ids 不得空"
        assert PENDING_CARD_TRIGGER_PLACEHOLDER not in d.trigger_dependency_ids, (
            f"回填后不应残留占位串，实际 {d.trigger_dependency_ids}"
        )
        # 不应残留 condition_id（"trig_cond_X" 是设计时 id，应被替换为运行时 id）
        assert "trig_cond_X" not in d.trigger_dependency_ids, (
            f"回填后不应残留 condition_id，实际 {d.trigger_dependency_ids}"
        )
        # 应包含 trigger 的运行时 id
        assert trig_id in d.trigger_dependency_ids, (
            f"下游 obligation 应指向 trigger 运行时 id {trig_id}，实际 {d.trigger_dependency_ids}"
        )
