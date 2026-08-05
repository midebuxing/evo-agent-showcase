# -*- coding: utf-8 -*-
"""DEBT-083 聚合读数强验的负面面（二轮审核点名：零行/缺槽必须报违例）。"""
from __future__ import annotations

import importlib.util
import pathlib

from evo_agent_baseline.closure.tests.fixtures import make_fact

_path = (pathlib.Path(__file__).resolve().parents[1]
         / "scripts" / "debt083_agg_check.py")
_spec = importlib.util.spec_from_file_location("debt083_agg_check", _path)
agg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agg)

STARTED = "procedure.repair.prescribed.started"
COMPLETED = "procedure.inspection.prescribed.completed"


def _agg_row(slot, value, fid="a1", marked=True, vt="boolean"):
    return make_fact(fid, slot_id=slot, value=value, value_type=vt,
                     carrier_type="building", carrier_id="BLD-X",
                     qualifiers={"aggregation": "building"} if marked else {})


def _part(slot, value, fid):
    return make_fact(fid, slot_id=slot, value=value, value_type="boolean",
                     carrier_type="sidecar_entry", carrier_id=f"FRG-{fid}")


def _green_facts():
    return [
        _agg_row(STARTED, True, "a1"),
        _part(STARTED, True, "s1"), _part(STARTED, False, "s2"),
        _agg_row(COMPLETED, False, "a2"),
        _part(COMPLETED, True, "c1"), _part(COMPLETED, False, "c2"),
    ]


def test_green_no_violations():
    _, v = agg.check_agg_slots(_green_facts(), "B")
    assert v == []


def test_slot_entirely_absent_is_violation():
    facts = [f for f in _green_facts() if f.slot_id != COMPLETED]
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == COMPLETED and x[2] == "授权槽整槽缺席" for x in v)


def test_parts_present_but_zero_agg_rows_is_violation():
    """二轮审核点名形状：有部位行但楼级聚合行为零 → 必须报违例。"""
    facts = [f for f in _green_facts() if f.fact_id != "a2"]
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == COMPLETED and x[2] == "楼级聚合行数非恰一" and x[3] == 0
               for x in v)


def test_multiple_agg_rows_is_violation():
    facts = _green_facts() + [_agg_row(STARTED, True, "a3")]
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == STARTED and x[2] == "楼级聚合行数非恰一" and x[3] == 2
               for x in v)


def test_missing_marker_is_violation():
    facts = [f for f in _green_facts() if f.fact_id != "a1"]
    facts.append(_agg_row(STARTED, True, "a1", marked=False))
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == STARTED and x[2] == "缺聚合标记" for x in v)


def test_nonbool_value_is_violation():
    facts = [f for f in _green_facts() if f.fact_id != "a1"]
    facts.append(_agg_row(STARTED, "yes", "a1", vt="string"))
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == STARTED and x[2] == "值域非布尔" for x in v)


def test_recompute_mismatch_is_violation():
    facts = [f for f in _green_facts() if f.fact_id != "a2"]
    facts.append(_agg_row(COMPLETED, True, "a2"))   # 部位含 False，全真应为 False
    _, v = agg.check_agg_slots(facts, "B")
    assert any(x[1] == COMPLETED and x[2] == "与重算不符" for x in v)
