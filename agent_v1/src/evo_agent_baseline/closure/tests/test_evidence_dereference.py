"""证据要求三通道解引用（2026-07-08 诊断修复：第八例"登记了没接线"）。

evaluate_evidence_requirement 此前：①artifact_ids 卡内局部编号（art01）不经本卡
workflow_operands.artifacts 注册表解引用 ②读不存在的 req['slot_ids'] 且不走
slot_role_map（死链）③无 measure_keys 通道。三修均为 spec §6.3.6 既有引用语义兑现。
"""

from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    evaluate_evidence_requirement,
)

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}


def _card(**over):
    base = dict(
        workflow_operands={"artifacts": [
            {"artifact_id": "art01", "artifact_type": "report",
             "artifact_key": "report.inspection"},
        ]},
        slot_role_map=[
            {"slot_ref_id": "RC.test.001.sr01",
             "slot_id": "procedure.report.submitted", "roles": ["evidence"],
             "qualifiers": {}, "required": True},
        ],
    )
    base.update(over)
    return make_rule_card(**base)


def test_artifact_id_dereferenced_via_card_registry() -> None:
    """art01 经本卡注册表解成 report.inspection 并实际绑定（此前 art01 当键直查
    → missing_artifact_mapping）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", slot_id="artifact.report.inspection", value=True,
                  value_type="boolean"),
    ]))
    o = evaluate_evidence_requirement(
        _card(), "for_submission",
        {"evidence_requirement_id": "e01", "artifact_ids": ["art01"]},
        idx, True, META,
    )
    assert o.blocked_reason_code != "missing_artifact_mapping"
    assert o.closure_status in ("closed", "open")  # 走进了 artifact 求值路径
    assert "report.inspection" in (o.artifact_keys or []) or o.closure_status == "closed"


def test_slot_ref_ids_dereferenced_via_slot_role_map() -> None:
    """slot_ref_ids 经 slot_role_map 解成 slot_id 并绑定（此前死链落
    missing_artifact_evidence）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", slot_id="procedure.report.submitted", value=True,
                  value_type="boolean"),
    ]))
    o = evaluate_evidence_requirement(
        _card(), "for_matching",
        {"evidence_requirement_id": "e01",
         "slot_ref_ids": ["RC.test.001.sr01"]},
        idx, True, META,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_measure_keys_channel_binds() -> None:
    """measure_keys 通道：测量在 → 证据在（此前无通道直落 no bindable ref）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", measure_key="ratio.covered_structure_area.inspected",
                  value=0.4, value_type="number"),
    ]))
    o = evaluate_evidence_requirement(
        _card(), "for_matching",
        {"evidence_requirement_id": "e01",
         "measure_keys": ["ratio.covered_structure_area.inspected"]},
        idx, True, META,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_measure_keys_missing_records_missing_measurement() -> None:
    idx = FactIndex(make_fact_pack([]))
    o = evaluate_evidence_requirement(
        _card(), "for_matching",
        {"evidence_requirement_id": "e01", "measure_keys": ["ratio.x"]},
        idx, True, META,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_measurement"


def test_all_refs_empty_still_missing_artifact_evidence() -> None:
    """三通道全空 → 维持 missing_artifact_evidence（源卡内容缺口的诚实兜底）。"""
    idx = FactIndex(make_fact_pack([]))
    o = evaluate_evidence_requirement(
        _card(), "for_matching", {"evidence_requirement_id": "e01"},
        idx, True, META,
    )
    assert o.open_reason_code == "missing_artifact_evidence"
