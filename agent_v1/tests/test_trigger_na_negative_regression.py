"""件③：负向回归门（终审登记形态，2026-08-02）。

断言三面（资产层常驻，不跑批）：
①负向行（127 RQ＋19 U 展开 191 行、146 组合）的六字段键**与授权资产零交集**；
②授权资产 172 行的 source_combo 全部 ∈ LP130、负向组合零混入；
③#274-276 预期零命中登记存在且这三组合**仍留在授权资产内**（终审明令不删）。
任何判据包/关系表/身份表变动后本测试自动复核——19 条 uncertain 永不静默变 NA
的运行时面由授权表零交集保证（不在表内结构上不可能命中授权路径）。
"""
import json
import pathlib

ASSET = (pathlib.Path(__file__).resolve().parents[1]
         / "experiments" / "_applicability_assets" / "gen_seed_301")


def _key(r):
    return (r["rule_card_id"], str(r.get("condition_id")), r["slot_ref_id"],
            r["required_component_type_key"], r["physical_leaf_identity"],
            r["raw_component_type"])


def _load(name):
    return json.loads((ASSET / name).read_text(encoding="utf-8"))


def test_negative_rows_disjoint_from_authorizations():
    auth = _load("trigger_structural_na_authorizations_v1.json")
    neg = _load("trigger_na_negative_regression_v1.json")
    auth_keys = {_key(r) for r in auth["rows"]}
    neg_keys = {_key(r) for r in neg["rows"]}
    assert len(auth_keys) == len(auth["rows"])          # 授权键无重复
    overlap = auth_keys & neg_keys
    assert not overlap, f"负向键混入授权表: {sorted(overlap)[:3]}"


def test_authorization_source_combos_are_lp_only():
    auth = _load("trigger_structural_na_authorizations_v1.json")
    neg = _load("trigger_na_negative_regression_v1.json")
    auth_combos = {r["source_combo_no"] for r in auth["rows"]}
    neg_combos = {r["source_combo_no"] for r in neg["rows"]}
    assert not (auth_combos & neg_combos), "同一组合同时出现在授权与负向资产"
    assert len(auth_combos) == 130
    assert len(auth["rows"]) == 172


def test_expected_zero_hit_registry_and_rows_kept():
    auth = _load("trigger_structural_na_authorizations_v1.json")
    neg = _load("trigger_na_negative_regression_v1.json")
    zh = {e["source_combo_no"] for e in neg.get("expected_zero_hit", [])}
    assert zh == {274, 275, 276}
    auth_combos = {r["source_combo_no"] for r in auth["rows"]}
    # 终审明令：三条良性零命中保留在授权资产内，不删不特例。
    assert zh <= auth_combos
    for e in neg["expected_zero_hit"]:
        assert e["zero_hit_reason"] == "preempted_by_existing_structural_na"
