"""leakage_audit.py 单测（spec §8.4.5）。

验证 6 项 leakage metric 的检出，以及白名单（事实层共享字段）不误报。
"""

from __future__ import annotations

from evo_agent_baseline.eval.leakage_audit import (
    FORBIDDEN_KG_LABELS,
    FORBIDDEN_KG_PROPERTIES,
    audit_leakage,
)


def test_clean_run_has_no_leakage():
    """干净 run：所有输入合规 → any_leakage=False，6 项全 False。"""
    res = audit_leakage(
        run_audit={
            "agent_visible_sources": ["buildings.parquet", "rule_cards.json"],
            "forbidden_sources_loaded": [],
            "forbidden_source_check_passed": True,
        },
        kg_labels=["World", "Building", "Fragment", "Obligation"],
        kg_export={"world_id": "WB-1", "severity_band": "minor", "notes": "ok"},
        report_text="本楼宇外墙存在缺陷，建议跟进。",
    )
    assert res.any_leakage is False
    assert all(v is False for v in res.metrics_dict().values())


def test_forbidden_source_loaded_detected():
    """forbidden_sources_loaded 非空 → forbidden_source_loaded=True。"""
    res = audit_leakage(
        run_audit={"forbidden_sources_loaded": ["projections.parquet"]}
    )
    assert res.forbidden_source_loaded is True
    assert res.any_leakage is True


def test_w2_denylist_file_in_visible_sources_detected():
    """W2 denylist 文件混进 agent_visible_sources → forbidden_source_loaded=True。"""
    res = audit_leakage(
        run_audit={
            "agent_visible_sources": [
                "buildings.parquet",
                "matched_families.parquet",  # W2 denylist
            ]
        }
    )
    assert res.forbidden_source_loaded is True


def test_forbidden_source_check_passed_false_detected():
    """run_audit.forbidden_source_check_passed=False → 判泄漏。"""
    res = audit_leakage(run_audit={"forbidden_source_check_passed": False})
    assert res.forbidden_source_loaded is True


def test_forbidden_label_in_kg_detected():
    """agent KG 出现 forbidden label → forbidden_label_in_kg=True。"""
    res = audit_leakage(kg_labels=["World", "NormativeProjection"])
    assert res.forbidden_label_in_kg is True
    assert res.any_leakage is True


def test_all_forbidden_labels_recognized():
    """spec §2.2.3 全部 7 个禁用 label 都能被检出。"""
    for lbl in FORBIDDEN_KG_LABELS:
        res = audit_leakage(kg_labels=["World", lbl])
        assert res.forbidden_label_in_kg is True, f"未检出禁用 label {lbl}"


def test_forbidden_property_in_kg_detected():
    """agent KG props 出现 forbidden property → forbidden_property_in_kg=True。"""
    res = audit_leakage(
        kg_export={"node": {"expected_verdict": "fail", "world_id": "WB-1"}}
    )
    assert res.forbidden_property_in_kg is True


def test_forbidden_property_as_plain_list():
    """kg_export 为属性名列表形态也能审计。"""
    res = audit_leakage(kg_export=["world_id", "coverage_status", "notes"])
    assert res.forbidden_property_in_kg is True


def test_fact_layer_shared_fields_not_flagged():
    """spec §2.2.3 说明 1：world_id/fragment_id/severity_band 共享字段不误报。"""
    res = audit_leakage(
        kg_export=["world_id", "fragment_id", "severity_band", "building_id"]
    )
    assert res.forbidden_property_in_kg is False


def test_all_forbidden_properties_recognized():
    """spec §2.2.3 全部禁用属性名都能被检出。"""
    for prop in FORBIDDEN_KG_PROPERTIES:
        res = audit_leakage(kg_export=[prop])
        assert res.forbidden_property_in_kg is True, f"未检出禁用属性 {prop}"


def test_expected_verdict_text_leak_field_name():
    """报告直接出现 expected_verdict 字段名 → expected_verdict_text_leak=True。"""
    res = audit_leakage(
        report_text="根据 expected_verdict 字段判断本楼宇不合格。"
    )
    assert res.expected_verdict_text_leak is True


def test_expected_verdict_text_leak_projection_id():
    """报告出现 W2 projection id 形态串 → expected_verdict_text_leak=True。"""
    res = audit_leakage(
        report_text="参照 NP-WB-HK-OFFICE-0000-S00001-FRG-X-00 的判定结论。"
    )
    assert res.expected_verdict_text_leak is True


def test_basis_item_id_leak_in_report():
    """报告出现 W2 basis_id 形态串 → basis_item_id_leak=True。"""
    res = audit_leakage(report_text="依据 basis_abc123 给出结论。")
    assert res.basis_item_id_leak is True


def test_basis_item_id_leak_exact_match():
    """提供 known_basis_ids 时精确匹配命中 → basis_item_id_leak=True。"""
    res = audit_leakage(
        report_text="结论引用了 BI-XYZ-0007 这个标识。",
        known_basis_ids=["BI-XYZ-0007"],
    )
    assert res.basis_item_id_leak is True


def test_basis_item_id_leak_in_obligation_set():
    """obligation_set 里出现 basis_id 形态串 → basis_item_id_leak=True。"""
    res = audit_leakage(
        obligation_set_dict={"obligations": [{"notes": "see basis_deadbeef"}]}
    )
    assert res.basis_item_id_leak is True


def test_evaluator_store_access_detected():
    """agent credential 访问 evaluator store → evaluator_store_access=True。"""
    res = audit_leakage(evaluator_store_accessed_by_agent=True)
    assert res.evaluator_store_access is True
    assert res.any_leakage is True


def test_findings_record_metric_and_location():
    """findings 记录命中的 metric / detail / location，便于溯源。"""
    res = audit_leakage(kg_labels=["NormativeProjection"])
    assert len(res.findings) >= 1
    f = res.findings[0]
    assert f.metric == "forbidden_label_in_kg"
    assert f.detail == "NormativeProjection"
    assert f.location == "agent_kg"


def test_multiple_leakages_aggregate():
    """多类泄漏同时存在 → 各对应 metric 均为 True。"""
    res = audit_leakage(
        run_audit={"forbidden_sources_loaded": ["projections.parquet"]},
        kg_labels=["EvalTruth"],
        report_text="expected_verdict 泄漏。",
    )
    assert res.forbidden_source_loaded is True
    assert res.forbidden_label_in_kg is True
    assert res.expected_verdict_text_leak is True
    assert res.any_leakage is True
