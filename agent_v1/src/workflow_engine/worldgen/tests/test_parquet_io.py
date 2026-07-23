"""Round-trip equivalence tests for parquet_io (2026-05-10).

测试目标:
  parquet write → read → JSON dict 与原始 dict 完全等价（递归 dict 比较）.

核心 fixture: 抽取一个真实样本 building 的 JSON dict（覆盖 measurements/conditions/
ubw_states 等关键嵌套字段），保证 unit test 与生产数据形态一致.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_engine.worldgen.parquet_io import (
    write_world_bundles_parquet,
    read_world_bundles_parquet,
    write_sidecar_runtime_parquet,
    read_sidecar_runtime_parquet,
    write_normative_projection_parquet,
    read_normative_projection_parquet,
)


# ---------------------------- fixtures ----------------------------


def _sample_world_payload() -> dict:
    """覆盖关键字段：嵌套 dict / list / null / 多种 measurement 形态."""
    bw = {
        "schema_version": "worldgen.fullcoverage.world.v1",
        "world_id": "WB-TESTSEED-S00042",
        "generator_version": "worldgen.fullcoverage.framework.v2",
        "random_seed": 42,
        # W1-004 顶层 derived_outcomes 字段（spec 8 §5 + §3.B），fixture 用空 dict
        "derived_outcomes": {},
        # W0-008 (2026-05-21)：building 块只含 spec 04 §4 BuildingContext 8 字段 contract.
        "building": {
            "building_id": "BLD-TESTSEED",
            "building_use": "residential",
            "structure_type": "rc_wall",
            "age_years": 56.0,
            "storey_count": 8,
            "primary_materials": ["reinforced_concrete", "steel_fire_doors"],
            "configuration_tags": ["regular", "canopy_present"],
            "occupancy_state": "occupied",
        },
        # W0-008：generator 内部 metadata（3 字段），不入 W2 contract.
        "building_metadata": {
            "building_template_id": "BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1",
            "building_name": "Test Building",
            "unit_count": 32,
        },
        # W0-004 step 4 (2026-05-21)：fragments 收窄到 spec 04 §7 9 字段 reference-based
        # contract（spec 15 §4.3）；旧 denorm 字段 (has_rebar / cover_depth_mm / nominal_* /
        # material_system / structural_role / fragment_scope / surface_position / exposure_zone /
        # component_type_id / building_metadata / *_graph_* / specialized_domains) 撤出本表.
        # coverage_relation_ids 在 parquet 是反向 join 索引列，但 FragmentContext class 不持有，
        # 不进 model_dump，也不进 round-trip dict.
        "fragments": [
            {
                "fragment_id": "FRG-TEST-A-00",
                "fragment_template_id": "FT_RC_BEAM_SPALL_REPAIR_V1",
                "component_id": "CMP-TESTSEED-STRUCTURAL-MEMBER-00",
                "location_id": "LOC-TESTSEED-EXTERNAL-WALL",
                "fragment_role": "inspection_target",
                "fragment_area_m2": 34.14,
                "fragment_length_m": 4.71,
                "in_scope": True,
                "exclusion_reason": None,
            },
            {
                "fragment_id": "FRG-TEST-B-01",
                "fragment_template_id": "FT_UBW_FIRE_SAFETY_V1",
                "component_id": "CMP-TESTSEED-EXTERNAL-WALL-00",
                "location_id": "LOC-TESTSEED-EXTERNAL-WALL",
                "fragment_role": "adjacent_context",
                "fragment_area_m2": 99.78,
                "fragment_length_m": None,
                "in_scope": True,
                "exclusion_reason": None,
            },
        ],
        # W0-004 step 4 (2026-05-21)：spec 04 §5 + spec 15 §4.4 加 cover_depth_mm 列.
        "components": [
            {
                "component_id": "CMP-TESTSEED-EXTERNAL-WALL-00",
                "component_type": "external_wall",
                "parent_component_id": None,
                "material_system": "reinforced_concrete",
                "structural_role": "secondary_load_bearing",
                "location_id": "LOC-TESTSEED-EXTERNAL-WALL",
                "geometry_proxy": {"length_m": 24.56, "visible_area_m2": 276.24, "thickness_mm": 464.5},
                "cover_depth_mm": 30.0,
                "access_class": "fully_accessible",
            },
        ],
        "locations": [
            {
                "location_id": "LOC-TESTSEED-EXTERNAL-WALL",
                "location_class": "external_wall",
                "exposure_zone": "exterior_weather",
                "storey_band": "mid_zone",
                "spatial_tags": ["facade", "external_wall"],
            },
        ],
        "coverage_relations": [
            {
                "coverage_id": "CVR-TESTSEED-00",
                "coverage_relation_type": "scope.component.excluded_from_scope",
                "target_fragment_id": "FRG-TEST-B-01",
                "coverage_state": "obscured",
                "covered_area_m2": 99.78,
                "inspected_area_m2": 0.0,
                "obscuration_class": "access_blocked",
            },
        ],
        "drivers": [
            {"driver_id": "DRV-TEST-A-00", "age_years": 56.0, "service_load_ratio": 0.812,
             "restraint_level": 0.369, "moisture_ingress_index": 0.031, "chloride_exposure_index": 0.516,
             "carbonation_index": 0.203, "workmanship_deficit_index": 0.029, "maintenance_deficit_index": 0.241,
             "obstruction_index": 0.169, "drainage_usage_intensity": 0.792, "blockage_propensity": 0.091,
             "alteration_propensity": 0.169, "fire_safety_deficit_index": 0.242,
             "repair_quality_index": 0.698, "coverage_feasibility_index": 0.613},
        ],
        "mechanisms": [
            {"mechanism_state_id": "MST-TEST-A-00", "fragment_id": "FRG-TEST-A-00",
             "mechanism_family": "ubw_signal", "active": True, "severity_index": 0.672,
             "cause_tags": ["alteration"],
             "primary_mechanism_id": "MCH-ubw_signal-FRG-TEST-A-00",
             "activated_mechanisms": [
                 {"mechanism_id": "MCH-x", "mechanism_family": "ubw_signal",
                  "activation_score": 0.672, "derived_from_driver_ids": ["DRV-TEST-A-00"], "notes": []}
             ],
             "crack_mechanism_kind": "none", "corrosion_active": False,
             "delamination_active": False, "drainage_fault_kind": "none",
             "ubw_signal_kind": "alteration_present", "fire_safety_deficiency_kind": "none",
             "assessment_origin_kind": "none", "verification_origin_kind": "none"},
        ],
        "conditions": [
            {"condition_id": "CND-TEST-A-00", "fragment_id": "FRG-TEST-A-00",
             "mechanism_state_id": "MST-TEST-A-00", "condition_class": "DC_UBW_PRESENT",
             "severity_band": "severe", "severity_index": 0.672, "extent_area_m2": 7.92,
             "extent_length_m": None, "depth_mm": None, "count": None, "uncertainty_flag": False,
             "defect_condition_ids": ["DC_UBW_PRESENT"], "condition_classes": ["DC_UBW_PRESENT"],
             "manifestation_flags": [],
             "derived_outcomes": {
                 "risk_flags": {
                     "risk.building_safety.emergency": False,
                     "risk.public_health.emergency": "not_applicable",
                     "ubw.present": False,
                 },
                 "repair_flags": {"repair.required": True, "maintenance.pre_next_cycle.required": False},
                 "verification_flags": {"verification.test.failed": False},
                 "assessment_flags": {},
                 "risk_index_values": {"index.public_danger": 0.672},
             },
             "source_tags": []},
        ],
        "drainage_states": [],
        "ubw_states": [
            {"ubw_id": "UBW-TEST", "component_id": "CMP-TEST", "alteration_type": "subdivision",
             "authorization_status_proxy": "authorized_like", "present": True,
             "subdivided_unit_sign_present": False, "structural_impact_index": 0.228,
             "structural_impact": 0.228},
        ],
        "fire_safety_states": [],
        "repair_assessment_states": [
            {"repair_assessment_id": "RAS-TEST", "fragment_id": "FRG-TEST-A-00",
             "repair_quality_index": 0.698, "repair_required": True, "maintenance_required": False,
             "verification_failed": False, "safe_until_next_cycle": False,
             "residual_risk_index": 0.403, "notes": []},
        ],
        "measurements": [
            # numeric measurement (含 pydantic computed_field "value" 还原)
            # DEBT-020 round5 sub-task 6 (2026-05-10): qualifiers 字段加入 round-trip baseline
            {"measurement_id": "MSR-A-00", "target_ref": "FRG-TEST-A-00",
             "measurement_family": "coverage_sampling_measurement", "slot_id": "count.x.minimum",
             "value_num": 59.0, "value_bool": None, "value_enum": None,
             "unit": "count", "precision_class": "standard", "method_class": "hammer_tapping",
             "sample_count": 2, "confidence_index": 0.732,
             "derivation_refs": ["FRG-TEST-A-00"], "derivation_mode": "coverage_sampling_plan",
             "qualifiers": {},
             "upstream_refs": ["FRG-TEST-A-00"], "origin_chain_refs": ["FRG-TEST-A-00"],
             "derived_from_measurement_ids": [], "notes": [], "value": 59.0},
            # bool measurement (value_bool 路径)
            {"measurement_id": "MSR-B-01", "target_ref": "FRG-TEST-B-01",
             "measurement_family": "technical_validation_measurement", "slot_id": "test.passed",
             "value_num": None, "value_bool": True, "value_enum": None,
             "unit": None, "precision_class": "standard", "method_class": None,
             "sample_count": None, "confidence_index": 0.9,
             "derivation_refs": [], "derivation_mode": "technical_validation_plan",
             "qualifiers": {},
             "upstream_refs": [], "origin_chain_refs": [],
             "derived_from_measurement_ids": [], "notes": ["bool sample"], "value": True},
        ],
    }
    return {
        "version": "worldgen.fullcoverage.building_worlds.v2",
        "generated_at": "2026-04-26T00:00:00+00:00",
        "registry_bundle_hash": "test_rb_hash",
        "batch_config_hash": "test_bc_hash",
        "deterministic_key": "test_dk_hash",
        "buildings": [bw],
    }


def _sample_sidecar_payload() -> dict:
    return {
        "version": "worldgen.fullcoverage.sidecar_runtime.v2",
        "generated_at": "2026-04-26T00:00:00+00:00",
        "source_documents": ["doc1.md", "doc2.md"],
        "records": [
            {
                "runtime_id": "SCR-FRG-TEST-A-00",
                "world_id": "WB-TESTSEED-S00042",
                "projection_id": "",
                "interface_ids": [],
                "facts": [
                    {"slot_id": "qual.actor_role", "value": "building_authority", "unit": None,
                     "qualifiers": {"fragment_id": "FRG-TEST-A-00", "carrier_domain": "qualifier"},
                     "time_anchor_key": None,
                     "source_refs": ["WB-TESTSEED-S00042", "FRG-TEST-A-00"], "notes": ["sample"]},
                ],
                "runtime_markers": [],
                "artifact_requirement_state": [
                    {"slot_id": "artifact.form.mbi1", "value": True, "unit": None,
                     "qualifiers": {"fragment_id": "FRG-TEST-A-00", "carrier_domain": "artifact"},
                     "time_anchor_key": None,
                     "source_refs": ["WB-TESTSEED-S00042"], "notes": []},
                ],
                "procedure_gate_state": [
                    {"slot_id": "duration.notification.deadline", "value": 6.0, "unit": None,
                     "qualifiers": {"fragment_id": "FRG-TEST-A-00"},
                     "time_anchor_key": None, "source_refs": [], "notes": []},
                ],
                "supervision_runtime_state": [
                    {"slot_id": "duration.site_visit.interval", "value": 5.0, "unit": None,
                     "qualifiers": {"fragment_id": "FRG-TEST-A-00"},
                     "time_anchor_key": "T1",
                     "source_refs": ["X"], "notes": ["x"]},
                ],
                "completion_runtime_state": [],
            },
        ],
    }


def _sample_projection_payload() -> dict:
    return {
        "version": "worldgen.fullcoverage.normative_projection.v2",
        "generated_at": "2026-04-26T00:00:00+00:00",
        "registry_bundle_hash": "rb",
        "deterministic_key": "dk",
        "buildings": [
            {
                "world_id": "WB-TESTSEED-S00042",
                "projection_count": 1,
                "projections": [
                    {
                        "projection_id": "NP-FRG-TEST-A-00-00",
                        "projection_registry_id": "NP_TEST_V1",
                        "projection_family": "mbis.inspection.test",
                        "world_id": "WB-TESTSEED-S00042",
                        # SA-2: NormativeProjection 必填字段，须 parquet 往返保全.
                        "fragment_id": "FRG-TEST-A",
                        "expected_verdict": "pass",
                        "projection_version": "2.0.0",
                        "matched_families": [
                            {
                                "family_id": "mbis.inspection.test",
                                "applicability_score": 0.5,
                                "applicability_state": "applicable",
                                "trigger_ids": ["t1"],
                                "rule_ids": [],
                                "slot_role_map": {"slot_x": "role_y"},
                                "threshold_evaluations": [
                                    {"rule_id": "rc.t.c01",
                                     "threshold_regime_id": "rc.t.c01.t01",
                                     "slot_id": "duration.x",
                                     "operator": "==", "threshold_value": 7.0,
                                     "observed_value": 7.0, "regime_tag": "exact_threshold",
                                     "pass_bool": True},
                                    {"rule_id": "rc.t.c02",
                                     "threshold_regime_id": "rc.t.c02.t01",
                                     "slot_id": "list.in_test",
                                     "operator": "in", "threshold_value": ["a", "b"],
                                     "observed_value": "a", "regime_tag": "not_numeric",
                                     "pass_bool": True},
                                ],
                                # FamilyVerdict 4 enum（W2-003）；"covered" 已非法枚举.
                                "verdict": "pass",
                            },
                        ],
                        "selected_family": "mbis.inspection.test",
                        "projection_status": "covered",
                        "required_slots": ["a", "b"],
                        "basis_items": [
                            {"basis_kind": "threshold_compare", "basis_id": "b1", "family_id": "mbis.inspection.test",
                             "rule_id": "rc.t.c01", "slot_id": "duration.x", "source_projection_id": "",
                             "operator": "==", "threshold_value": 7.0, "unit": "day",
                             "regime_tag": "exact_threshold", "expected_value": None, "statement_code": None,
                             "reason_code": None, "candidate_known_families": [],
                             "observed_value": 7.0, "pass_bool": True, "source_ref": ""},
                            {"basis_kind": "bool_assertion", "basis_id": "b2", "family_id": "mbis.inspection.test",
                             "rule_id": "rc.t.c02", "slot_id": "test.passed", "source_projection_id": "",
                             "operator": None, "threshold_value": None, "unit": None, "regime_tag": None,
                             "expected_value": True, "statement_code": "S1", "reason_code": None,
                             "candidate_known_families": [], "observed_value": True, "pass_bool": True,
                             "source_ref": "x"},
                        ],
                        "unknown_reason_code": None,
                        "sidecar_join_status": "available",
                        "severity_band": "severe",
                        "required_world_core_slots": ["s1"],
                        "required_measurement_slots": ["m1"],
                        "required_qualifier_slots": ["q1", "q2"],
                        "required_sidecar_interfaces": ["i1"],
                        "matched_component_refs": ["c1"],
                        "matched_measurement_ids": ["m_id_1"],
                        "coverage_status": "world_core_ready",
                        "notes": [],
                    },
                ],
            },
        ],
    }


# ---------------------------- tests ----------------------------


def test_world_bundles_roundtrip(tmp_path: Path) -> None:
    payload = _sample_world_payload()
    out = write_world_bundles_parquet(tmp_path / "wb_pq", payload)
    assert out.is_dir()
    restored = read_world_bundles_parquet(out)
    assert restored == payload, _diff_msg("world_bundles", payload, restored)


def test_sidecar_runtime_roundtrip(tmp_path: Path) -> None:
    payload = _sample_sidecar_payload()
    out = write_sidecar_runtime_parquet(tmp_path / "sc_pq", payload)
    restored = read_sidecar_runtime_parquet(out)
    assert restored == payload, _diff_msg("sidecar", payload, restored)


def test_normative_projection_roundtrip(tmp_path: Path) -> None:
    payload = _sample_projection_payload()
    out = write_normative_projection_parquet(tmp_path / "np_pq", payload)
    restored = read_normative_projection_parquet(out)
    assert restored == payload, _diff_msg("projection", payload, restored)


def test_normative_projection_required_fields_roundtrip(tmp_path: Path) -> None:
    """SA-2 回归：fragment_id / expected_verdict（NormativeProjection 模型必填字段）
    parquet 往返必须无损，且还原后能重建合法 NormativeProjection."""
    from workflow_engine.regulation_projection_models import NormativeProjection

    payload = _sample_projection_payload()
    out = write_normative_projection_parquet(tmp_path / "np_required", payload)
    restored = read_normative_projection_parquet(out)
    proj_in = payload["buildings"][0]["projections"][0]
    proj_out = restored["buildings"][0]["projections"][0]
    # 字段无损
    assert proj_out["fragment_id"] == proj_in["fragment_id"] == "FRG-TEST-A"
    assert proj_out["expected_verdict"] == proj_in["expected_verdict"] == "pass"
    # 还原 dict 能重建合法 NormativeProjection（fragment_id / expected_verdict 无默认值，
    # 若 parquet 丢字段此处会 pydantic ValidationError）.
    rebuilt = NormativeProjection(**proj_out)
    assert rebuilt.fragment_id == "FRG-TEST-A"
    assert rebuilt.expected_verdict == "pass"


def test_empty_world_bundles(tmp_path: Path) -> None:
    """Empty buildings list — schema 不能崩."""
    payload = {
        "version": "worldgen.fullcoverage.building_worlds.v2",
        "generated_at": "2026-04-26T00:00:00+00:00",
        "registry_bundle_hash": "x",
        "batch_config_hash": "y",
        "deterministic_key": "z",
        "buildings": [],
    }
    out = write_world_bundles_parquet(tmp_path / "wb_empty", payload)
    restored = read_world_bundles_parquet(out)
    assert restored == payload


def test_compression_ratio_smoke(tmp_path: Path) -> None:
    """Smoke check：parquet output 比 JSON serialization 小."""
    # 复制 1 building 100 次，模拟批次
    base = _sample_world_payload()
    base_b = base["buildings"][0]
    base["buildings"] = []
    for i in range(100):
        bw = json.loads(json.dumps(base_b))  # deep copy
        bw["world_id"] = f"WB-TESTSEED-S{i:05d}"
        base["buildings"].append(bw)
    json_bytes = len(json.dumps(base, ensure_ascii=False).encode("utf-8"))
    out = write_world_bundles_parquet(tmp_path / "wb_compress", base)
    pq_bytes = sum(p.stat().st_size for p in out.glob("*.parquet"))
    assert pq_bytes < json_bytes, f"parquet ({pq_bytes}) NOT smaller than JSON ({json_bytes})"
    # 不强求 10x（small fixtures dict encoding 优势小），只要小就行
    print(f"[smoke] json={json_bytes/1024:.1f}KB parquet={pq_bytes/1024:.1f}KB ratio={json_bytes/pq_bytes:.2f}x")


# ------------------ DEBT-054 Block B threshold_regime_id ------------------


def test_threshold_regime_id_roundtrip(tmp_path: Path) -> None:
    """B.1/B.2 ⑥：threshold_regime_id 增列 emit→parquet→readback 逐字节保全."""
    payload = _sample_projection_payload()
    out = write_normative_projection_parquet(tmp_path / "np_regime", payload)
    restored = read_normative_projection_parquet(out)
    ths_in = payload["buildings"][0]["projections"][0]["matched_families"][0]["threshold_evaluations"]
    ths_out = restored["buildings"][0]["projections"][0]["matched_families"][0]["threshold_evaluations"]
    assert [t["threshold_regime_id"] for t in ths_out] == [t["threshold_regime_id"] for t in ths_in]
    assert ths_out[0]["threshold_regime_id"] == "rc.t.c01.t01"


def test_threshold_regime_id_empty_writer_hard_fail(tmp_path: Path) -> None:
    """B.2 ⑥ writer 端 non-empty hard-fail：空 threshold_regime_id 直接 raise（不静默落 null）."""
    payload = _sample_projection_payload()
    payload["buildings"][0]["projections"][0]["matched_families"][0][
        "threshold_evaluations"
    ][0]["threshold_regime_id"] = ""
    with pytest.raises(ValueError, match="threshold_regime_id_null_in_parquet_row"):
        write_normative_projection_parquet(tmp_path / "np_bad", payload)


def test_threshold_regime_id_missing_writer_hard_fail(tmp_path: Path) -> None:
    """键缺失（绕 Pydantic 直 append 的等价场景）→ writer hard-fail."""
    payload = _sample_projection_payload()
    del payload["buildings"][0]["projections"][0]["matched_families"][0][
        "threshold_evaluations"
    ][0]["threshold_regime_id"]
    with pytest.raises(ValueError, match="threshold_regime_id_null_in_parquet_row"):
        write_normative_projection_parquet(tmp_path / "np_missing", payload)


def test_cohort_manifest_emitted(tmp_path: Path) -> None:
    """B.5：NP writer 落盘外置 append-only cohort manifest（双层 hash + 文件清单）."""
    from workflow_engine.cohort_manifest import (
        COHORT_MANIFEST_FILENAME,
        read_cohort_manifest,
    )

    payload = _sample_projection_payload()
    out = write_normative_projection_parquet(tmp_path / "np_manifest", payload)
    entries = read_cohort_manifest(out / COHORT_MANIFEST_FILENAME)
    assert len(entries) == 1
    m = entries[0]
    assert m["tree_hash"] and m["manifest_hash"]
    assert m["truth_schema"] == "truth_v2_regime"
    assert m["projection_schema"] == "projection_v2_regime"
    listed = {f["path"] for f in m["files"]}
    assert "threshold_evaluations.parquet" in listed
    # append-only：二次写同目录 → 追加第二行，不覆盖。
    write_normative_projection_parquet(tmp_path / "np_manifest", payload)
    assert len(read_cohort_manifest(out / COHORT_MANIFEST_FILENAME)) == 2


# ------ DEBT-054 Block B.5 forward-only 修：cohort manifest 记真实非空 profile 标签 ------


def test_cohort_manifest_records_real_nonempty_profile_tags(tmp_path: Path) -> None:
    """B.5 forward-only 修：默认写入 cohort manifest 记真实非空 profile/identity 标签
    （非原空串占位）——空标签会令 profile bump 时字节不变、manifest_hash 不变、破冻结保护。"""
    from workflow_engine.cohort_manifest import (
        COHORT_MANIFEST_FILENAME,
        read_cohort_manifest,
    )
    from workflow_engine.worldgen.parquet_io import (
        CANONICAL_PROFILE_ID,
        IDENTITY_SCHEMA_PENDING,
    )

    payload = _sample_projection_payload()
    out = write_normative_projection_parquet(tmp_path / "np_tags", payload)
    m = read_cohort_manifest(out / COHORT_MANIFEST_FILENAME)[0]
    # 非空 + 记真实 profile（不再是空串占位）。
    assert m["canonical_profile_id"] == CANONICAL_PROFILE_ID != ""
    assert m["identity_schema"] == IDENTITY_SCHEMA_PENDING != ""


def test_profile_tag_change_flips_manifest_hash_via_real_writer(tmp_path: Path) -> None:
    """B.5 核心不变量（经真实 writer 路径，非直接调 hash 函数）：profile 标签变 →
    manifest_hash 变，即便 parquet 字节完全不变（tree_hash 恒定）。原空串占位会破此性质。"""
    from workflow_engine.cohort_manifest import (
        COHORT_MANIFEST_FILENAME,
        read_cohort_manifest,
    )

    payload = _sample_projection_payload()
    out_a = write_normative_projection_parquet(tmp_path / "prof_a", payload)
    m_a = read_cohort_manifest(out_a / COHORT_MANIFEST_FILENAME)[0]

    payload_b = _sample_projection_payload()
    # 用与当前默认（CANONICAL_PROFILE_ID）明确不同的合成探针标签——不硬编真实版本号，
    # 免得后续 profile bump 令探针与默认相撞（本次 v1→v2 bump 即撞过一次）。
    probe_tag = "mbis_canonical_probe_alt"
    assert probe_tag != m_a["canonical_profile_id"]  # 探针须异于当前默认 profile 标签
    payload_b["canonical_profile_id"] = probe_tag  # profile 标签变（parquet 字节不变）
    out_b = write_normative_projection_parquet(tmp_path / "prof_b", payload_b)
    m_b = read_cohort_manifest(out_b / COHORT_MANIFEST_FILENAME)[0]

    # parquet 字节完全相同（canonical_profile_id 不落任何 parquet 列，只进 manifest）。
    assert m_a["tree_hash"] == m_b["tree_hash"]
    # profile 标签变 → manifest_hash 必变（冻结保护成立）。
    assert m_a["manifest_hash"] != m_b["manifest_hash"]
    assert m_b["canonical_profile_id"] == probe_tag


def test_identity_schema_change_flips_manifest_hash_via_real_writer(tmp_path: Path) -> None:
    """B.5：identity_schema 标签变（Block A 落地后透传真实值场景）→ manifest_hash 变，字节不变。"""
    from workflow_engine.cohort_manifest import (
        COHORT_MANIFEST_FILENAME,
        read_cohort_manifest,
    )

    payload = _sample_projection_payload()
    out_a = write_normative_projection_parquet(tmp_path / "id_a", payload)
    m_a = read_cohort_manifest(out_a / COHORT_MANIFEST_FILENAME)[0]

    payload_b = _sample_projection_payload()
    payload_b["identity_schema"] = "obligation_identity_v2"  # Block A 落地透传真实值
    out_b = write_normative_projection_parquet(tmp_path / "id_b", payload_b)
    m_b = read_cohort_manifest(out_b / COHORT_MANIFEST_FILENAME)[0]

    assert m_a["tree_hash"] == m_b["tree_hash"]
    assert m_a["manifest_hash"] != m_b["manifest_hash"]


def test_empty_profile_tag_writer_hard_fail(tmp_path: Path) -> None:
    """B.5 writer 边界空串 hard-fail：显式传空 canonical_profile_id → raise（防再退化空标签）。"""
    payload = _sample_projection_payload()
    payload["canonical_profile_id"] = ""
    with pytest.raises(ValueError, match="canonical_profile_id_empty_at_cohort_manifest"):
        write_normative_projection_parquet(tmp_path / "empty_prof", payload)


def test_empty_identity_schema_writer_hard_fail(tmp_path: Path) -> None:
    """B.5 writer 边界空串 hard-fail：显式传空 identity_schema → raise。"""
    payload = _sample_projection_payload()
    payload["identity_schema"] = ""
    with pytest.raises(ValueError, match="identity_schema_empty_at_cohort_manifest"):
        write_normative_projection_parquet(tmp_path / "empty_id", payload)


# ---------------------------- helpers ----------------------------


def _diff_msg(label: str, expected: dict, actual: dict) -> str:
    """Compact diff output: first 1500 chars of canonical-json side-by-side."""
    e = json.dumps(expected, ensure_ascii=False, sort_keys=True)[:1500]
    a = json.dumps(actual, ensure_ascii=False, sort_keys=True)[:1500]
    return f"[{label}] roundtrip mismatch\nEXPECTED: {e}\n\nACTUAL: {a}"
