"""measure 型触发谓词（spec §6.3.3 增补案 2026-07-08 定稿）。

绑定复用 §6.3.5 阈值机器全 5 级（sidecar 兜底档实证为覆盖率键唯一居所），
bind_path 落 notes 供审计；缺量记 missing_measurement 与 slot 侧分账。
"""

from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_trigger

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}


def _measure_trigger(**over):
    trig = {
        "condition_id": "trg02",
        "predicate_kind": "measure",
        "measure_key": "ratio.covered_structure_area.inspected",
        "operator": ">=",
        "expected_value": 0.3,
        "qualifiers": {},
        "unit": None,
    }
    trig.update(over)
    return trig


def test_measure_trigger_true_via_sidecar_binding() -> None:
    """sidecar 载体测量命中（第 4/5 级）→ 比较真 → closed+satisfied。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", measure_key="ratio.covered_structure_area.inspected",
                  value=0.45, value_type="number", carrier_type="sidecar_entry"),
    ]))
    o = evaluate_trigger(make_rule_card(), _measure_trigger(), idx, META)
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")
    assert o.comparator_result is True
    assert "bind_path=" in (o.notes or "")  # codex 合议验收：sidecar 命中可审计


def test_measure_trigger_false() -> None:
    """比较假 → closed+not_applicable（trigger false 语义，下游不激活）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", measure_key="ratio.covered_structure_area.inspected",
                  value=0.1, value_type="number"),
    ]))
    o = evaluate_trigger(make_rule_card(), _measure_trigger(), idx, META)
    assert (o.closure_status, o.satisfaction_status) == ("closed", "not_applicable")


def test_measure_trigger_missing_records_missing_measurement() -> None:
    """无量可绑 → open/missing_measurement（与 slot 侧 missing_fact 分账）。"""
    idx = FactIndex(make_fact_pack([]))
    o = evaluate_trigger(make_rule_card(), _measure_trigger(), idx, META)
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_measurement"
    # codex 钻 2026-07-08：bind 失败也须带卡端比较值（审计完整性）。
    assert o.threshold_value_json is not None


def test_measure_trigger_alias_binding() -> None:
    """measure_aliases 桥（第 2 级）对触发器同样生效。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", measure_key="canonical.key", value=0.5,
                  value_type="number"),
    ]))
    o = evaluate_trigger(
        make_rule_card(), _measure_trigger(measure_key="card.raw.key"),
        idx, META, measure_aliases={"card.raw.key": "canonical.key"},
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")


def test_measure_trigger_qualifier_filter_strict() -> None:
    """限定符不匹配的事实不入绑定 → 缺量（codex 合议验收：防 sidecar 误绑）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", measure_key="ratio.covered_structure_area.inspected",
                  value=0.45, value_type="number",
                  qualifiers={"component_type_key": "drainage_component"}),
    ]))
    o = evaluate_trigger(
        make_rule_card(),
        _measure_trigger(qualifiers={"component_type_key": "structural_component"}),
        idx, META,
    )
    assert o.closure_status == "open"
    assert o.open_reason_code == "missing_measurement"


def test_measure_trigger_missing_measure_key_blocked() -> None:
    """缺 measure_key → blocked/schema_contract_violation。"""
    idx = FactIndex(make_fact_pack([]))
    o = evaluate_trigger(
        make_rule_card(), _measure_trigger(measure_key=None), idx, META,
    )
    assert o.closure_status == "blocked"
    assert o.blocked_reason_code == "schema_contract_violation"


def test_slot_trigger_unaffected() -> None:
    """slot 谓词路径行为不变（回归护栏）。"""
    idx = FactIndex(make_fact_pack([
        make_fact("f1", slot_id="procedure.x.done", value=True,
                  value_type="boolean"),
    ]))
    o = evaluate_trigger(
        make_rule_card(),
        {"condition_id": "trg01", "predicate_kind": "slot",
         "slot_id": "procedure.x.done", "operator": "==",
         "expected_value": True},
        idx, META,
    )
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")
