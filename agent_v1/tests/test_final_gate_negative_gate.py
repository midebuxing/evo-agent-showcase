# -*- coding: utf-8 -*-
"""负向回归硬门的变异面（第四轮条 6 三类＋第五轮四类假绿形状）。

第四轮点名（绿路之外必须红）：
①「错误命中正向编号」②「漏掉一个不确定组合」③「零命中行被删除」。
第五轮点名（假绿必须红）：
④分母随资产缩水（删负向行后 190/190 仍绿）⑤零命中"至少留一行"
（删 2 行组合中 1 行仍绿）⑥重复授权注记只解析第一条 ⑦收跑快照
不包住负向门（在重放脚本层，见 final_gate_replay.py，不在本模块测试面）。
"""
from __future__ import annotations

import importlib.util
import pathlib

_ng_path = (pathlib.Path(__file__).resolve().parents[1]
            / "scripts" / "final_gate_negative_gate.py")
_spec = importlib.util.spec_from_file_location("final_gate_negative_gate", _ng_path)
ng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ng)

CARDS = {"cards": [
    {"rule_card_id": "RC.a.c01",
     "trigger_conditions": {"items": [
         {"condition_id": "trg01", "slot_ref_id": "RC.a.c01.sr01",
          "qualifiers": {"component_type_key": "drainage_component"}}]},
     "slot_role_map": []},
    {"rule_card_id": "RC.z.c01",
     "trigger_conditions": {"items": [
         {"condition_id": "trg01", "slot_ref_id": "RC.z.c01.sr01",
          "qualifiers": {"component_type_key": "external_component"}}]},
     "slot_role_map": []},
]}

FRAG_LEAF = {"F1": "cantilevered_canopy", "F2": "structural_component",
             "F3": "drainage_component", "F4": "fire_safety_component",
             "F5": "fire_safety_component"}
FRAG_RAW = {"F1": "canopy", "F2": "beam", "F3": "drainage_stack",
            "F4": "fire_door", "F5": "fire_shutter"}

EXPECTED = {"neg_row_keys": 2, "neg_combos": 2, "u_combos": 1,
            "zero_hit_auth_rows": {274: 2}}    # 精确行数（对应 F4+F5 两键）

PREEMPT = ("structurally_unsatisfiable_qualifier: "
           "location_class_key='external' incompatible")


def _row(card="RC.a.c01", leaf="cantilevered_canopy", raw="canopy",
         combo=9, outcome="no_authorization"):
    return {"rule_card_id": card, "condition_id": "trg01",
            "slot_ref_id": f"{card}.sr01",
            "required_component_type_key": (
                "external_component" if card == "RC.z.c01" else "drainage_component"),
            "physical_leaf_identity": leaf, "raw_component_type": raw,
            "source_combo_no": combo, "expected_outcome": outcome}


NEG_ROWS = [
    _row(),                                                     # RQ, combo 9
    _row(leaf="structural_component", raw="beam",
         combo=50, outcome="unknown"),                          # U, combo 50
]
AUTH_ROWS = [
    {**_row(leaf="drainage_component", raw="drainage_stack", combo=1),
     "expected_outcome": None},                                 # 正向授权 combo 1
    {**_row(card="RC.z.c01", leaf="fire_safety_component", raw="fire_door",
            combo=274), "expected_outcome": None},              # 零命中行 A
    {**_row(card="RC.z.c01", leaf="fire_safety_component", raw="fire_shutter",
            combo=274), "expected_outcome": None},              # 零命中行 B
]
ZERO_HIT = [{"source_combo_no": 274,
             "zero_hit_reason": "preempted_by_existing_structural_na",
             "preempting_axis": "location_class_key"}]


def _obl(card="RC.a.c01", frag="F1", notes="", satis="unknown",
         closure="open", kind="trigger"):
    return {"kind": kind, "source_rule_card_id": card,
            "slot_ref_ids": [f"{card}.sr01"], "fragment_id": frag,
            "notes": notes, "satisfaction_status": satis,
            "closure_status": closure}


def _green_obligations():
    return [
        _obl(),                                                  # RQ 键，无注记
        _obl(frag="F2"),                                         # U 键，保持未知
        _obl(frag="F3", notes="authorized_structural_na: source_combo=1",
             satis="not_applicable", closure="closed"),          # 正向授权命中
        _obl(card="RC.z.c01", frag="F4", satis="not_applicable",
             closure="closed", notes=PREEMPT),                   # 零命中行 A 被截获
        _obl(card="RC.z.c01", frag="F5", satis="not_applicable",
             closure="closed", notes=PREEMPT),                   # 零命中行 B 被截获
    ]


def _run(obls, auth_rows=None, neg_rows=None, full=True, expected=None):
    trig_idx = ng.build_trigger_index(CARDS)
    return ng.run_negative_gate(
        obls,
        neg_rows if neg_rows is not None else NEG_ROWS,
        auth_rows if auth_rows is not None else AUTH_ROWS,
        ZERO_HIT, trig_idx, FRAG_LEAF, FRAG_RAW,
        require_full_coverage=full,
        expected=expected if expected is not None else EXPECTED)


def test_green_path_no_failures():
    res = _run(_green_obligations())
    assert res["failures"] == []
    assert res["stats"]["neg_rows_covered"] == "2/2"
    assert res["stats"]["u_combos_observed"] == "1/1"
    assert res["stats"]["zero_hit_detail"][274]["auth_rows_retained"] == 2
    assert res["stats"]["zero_hit_detail"][274]["preempt_evidence"] == 2


def test_mutation_wrong_hit_positive_number_fails():
    """四轮变异①：负向键上出现引用正向编号的授权注记 → 必须红。"""
    obls = _green_obligations()
    obls[0] = _obl(notes="authorized_structural_na: source_combo=1",
                   satis="not_applicable", closure="closed")
    res = _run(obls)
    assert any("负向键被授权" in f for f in res["failures"])


def test_mutation_missing_one_u_combo_fails():
    """四轮变异②：U 组合未被观测（覆盖硬断言开）→ 必须红。"""
    obls = [o for o in _green_obligations() if o["fragment_id"] != "F2"]
    res = _run(obls)
    assert any("U 组合未被观测" in f for f in res["failures"])
    assert any("覆盖不足" in f for f in res["failures"])


def test_mutation_zero_hit_rows_all_deleted_fails():
    """四轮变异③：零命中授权行全删 → 必须红（0 ≠ 登记 2）。"""
    auth_wo_274 = [r for r in AUTH_ROWS if r["source_combo_no"] != 274]
    res = _run(_green_obligations(), auth_rows=auth_wo_274)
    assert any("授权行数与裁定登记不符" in f and "0 ≠ 2" in f
               for f in res["failures"])


def test_mutation_zero_hit_partial_deletion_fails():
    """五轮假绿⑤：两行零命中组合删掉一行、仍留一行 → 必须红（1 ≠ 2）。"""
    auth_partial = [r for r in AUTH_ROWS
                    if not (r["source_combo_no"] == 274
                            and r["raw_component_type"] == "fire_shutter")]
    res = _run(_green_obligations(), auth_rows=auth_partial)
    assert any("授权行数与裁定登记不符" in f and "1 ≠ 2" in f
               for f in res["failures"])


def test_mutation_neg_asset_shrink_fails():
    """五轮假绿④：负向资产删一行、分母跟着缩 → 必须红（键数≠登记）。"""
    neg_shrunk = NEG_ROWS[:1]
    res = _run([o for o in _green_obligations() if o["fragment_id"] != "F2"],
               neg_rows=neg_shrunk)
    assert any("键数与裁定登记不符" in f for f in res["failures"])


def test_mutation_duplicate_auth_note_fails():
    """五轮假绿⑥：一条义务带两条授权注记（第二条编号错）→ 必须红。"""
    obls = _green_obligations()
    obls[2] = _obl(frag="F3",
                   notes="authorized_structural_na: source_combo=1 | "
                         "authorized_structural_na: source_combo=999",
                   satis="not_applicable", closure="closed")
    res = _run(obls)
    assert any("重复授权注记" in f for f in res["failures"])
    assert any("编号与该键授权行不符" in f for f in res["failures"])


def test_u_combo_entering_structural_na_fails():
    """U 键被结构不适用路径吞掉 → 必须红（保持未知是硬条件）。"""
    obls = _green_obligations()
    obls[1] = _obl(frag="F2", satis="not_applicable", closure="closed",
                   notes=PREEMPT)
    res = _run(obls)
    assert any("结构不适用路径" in f for f in res["failures"])
    assert any("未保持未知" in f for f in res["failures"])


def test_auth_note_number_mismatch_fails():
    """授权注记编号 ≠ 该键授权行编号（匹配器退化）→ 必须红。"""
    obls = _green_obligations()
    obls[2] = _obl(frag="F3", notes="authorized_structural_na: source_combo=2",
                   satis="not_applicable", closure="closed")
    res = _run(obls)
    assert any("编号与该键授权行不符" in f for f in res["failures"])


def test_no_coverage_requirement_skips_coverage_only():
    """覆盖硬断言关闭时：缺观测不红，但授权完整性仍硬。"""
    obls = [o for o in _green_obligations() if o["fragment_id"] != "F2"]
    res = _run(obls, full=False)
    assert res["failures"] == []
    obls[0] = _obl(notes="authorized_structural_na: source_combo=1",
                   satis="not_applicable", closure="closed")
    res2 = _run(obls, full=False)
    assert any("负向键被授权" in f for f in res2["failures"])


def test_production_expected_matches_registry():
    """生产登记常量的形状检查（数字权威在 276 组合裁定终表）。"""
    e = ng.PRODUCTION_EXPECTED
    assert e["neg_row_keys"] == 191 and e["neg_combos"] == 146
    assert e["u_combos"] == 19
    assert e["zero_hit_auth_rows"] == {274: 1, 275: 2, 276: 1}
