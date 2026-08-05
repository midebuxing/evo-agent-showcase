"""DEBT-083 第 3 步：`fallback_reasons` 事实用途边界分流（2026-08-01，缺省关闭）。

spec 明文该组只解释未知/不适用、不得参与满足/违反判定；`pack_builder` 把它展成
普通槽事实（docstring 早写着不参与判定，下游从没执行）。分流＝判定绑定索引排除
`provenance.derived_outcome_group == "fallback_reasons"`，事实仍留包与 carrier 索引。

测试面：①缺省等价（不传/传 False 索引逐位不变）②分流后同槽真冲突消解为可判
③fallback 独占槽分流后按缺失处理（不是凭空判定）④解释面保留（facts + carrier_index）。
决策门边界：**不是**按来源分组判冲突（那被明拒）；判定性通道仍异值必须继续 ambiguous。
"""
from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_trigger

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}
SLOT = "risk.public_health.emergency"


def _risk_fact(value=True):
    return make_fact(
        "F-risk-01", slot_id=SLOT, value=value, value_type="boolean",
        carrier_type="condition", carrier_id="COND-01",
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": "risk_flags"},
    )


def _fallback_fact(value=False):
    return make_fact(
        "F-fb-01", slot_id=SLOT, value=value, value_type="boolean",
        carrier_type="condition", carrier_id="COND-01",
        provenance={"carrier_label": "ConditionState",
                    "derived_outcome_group": "fallback_reasons"},
    )


def _trigger():
    return {
        "condition_id": "trg01", "predicate_kind": "slot",
        "slot_id": SLOT, "operator": "==", "expected_value": True,
        "qualifiers": {},
    }


def test_default_off_index_identical() -> None:
    """缺省等价：不传 == 传 False，六索引逐位相同（含 fallback 行照常进判定索引）。"""
    facts = [_risk_fact(), _fallback_fact()]
    a = FactIndex(make_fact_pack(facts))
    b = FactIndex(make_fact_pack(facts), exclude_explanatory=False)
    for name in ("slot_index", "measure_index", "carrier_index",
                 "artifact_index", "method_index"):
        ia = {k: [f.fact_id for f in v] for k, v in getattr(a, name).items()}
        ib = {k: [f.fact_id for f in v] for k, v in getattr(b, name).items()}
        assert ia == ib, name
    assert [f.fact_id for f in a.slot_index[SLOT]] == ["F-risk-01", "F-fb-01"]


def test_split_resolves_cross_channel_conflict() -> None:
    """分流开：risk=true 与 fallback=false 的同槽身份冲突消解，触发器可判（比较真值）。

    对照（关）：两行异值 → conflict_status ambiguous → blocked/ambiguous_fact_binding。
    """
    facts = [_risk_fact(True), _fallback_fact(False)]
    off = evaluate_trigger(
        make_rule_card(), _trigger(),
        FactIndex(make_fact_pack(facts)), META)
    assert (off.closure_status, off.blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
    on = evaluate_trigger(
        make_rule_card(), _trigger(),
        FactIndex(make_fact_pack(facts), exclude_explanatory=True), META)
    assert (on.closure_status, on.satisfaction_status) == ("closed", "satisfied")
    assert on.evidence_fact_ids == ["F-risk-01"]     # 绑的是判定性事实，不是排除后任取


def test_fallback_only_slot_becomes_missing() -> None:
    """分流开 + 槽上只有 fallback 事实：按缺失处理（open/missing_fact），不凭空判定。"""
    on = evaluate_trigger(
        make_rule_card(), _trigger(),
        FactIndex(make_fact_pack([_fallback_fact()]), exclude_explanatory=True),
        META)
    assert (on.closure_status, on.open_reason_code) == ("open", "missing_fact")


def test_explanatory_face_preserved() -> None:
    """分流开：fallback 事实仍在 fact_pack.facts 与 carrier_index（解释面不受影响）。"""
    idx = FactIndex(make_fact_pack([_risk_fact(), _fallback_fact()]),
                    exclude_explanatory=True)
    assert any(f.fact_id == "F-fb-01" for f in idx.fact_pack.facts)
    assert any(f.fact_id == "F-fb-01" for f in idx.carrier_index["COND-01"])
    assert [f.fact_id for f in idx.slot_index[SLOT]] == ["F-risk-01"]


def test_adjudicative_channels_still_ambiguous() -> None:
    """决策门边界：分流后两个**判定性**通道仍异值 → 必须继续 ambiguous（不是按来源
    分组各自自洽——那被明拒）。"""
    facts = [
        _risk_fact(True),
        make_fact(
            "F-repair-01", slot_id=SLOT, value=False, value_type="boolean",
            carrier_type="condition", carrier_id="COND-01",
            provenance={"carrier_label": "ConditionState",
                        "derived_outcome_group": "repair_flags"},
        ),
    ]
    on = evaluate_trigger(
        make_rule_card(), _trigger(),
        FactIndex(make_fact_pack(facts), exclude_explanatory=True), META)
    assert (on.closure_status, on.blocked_reason_code) == (
        "blocked", "ambiguous_fact_binding")
