"""DEBT-020 Round 6 + Round 7 sidecar conditional formulas (spec 06 §11.6 落地版).

45 个 sidecar bool / categorical slot 的 centered upstream conditional formula 定义.

公式 pattern (Round 6 §1.1)：
  bool: p = sigmoid(logit(anchor) + Σ coef_i * (upstream_i - upstream_expected_i))
  enum: logit_c = log(anchor_c) + Σ coef_ci * (upstream_i - upstream_expected_i)

Round 6 → Round 7 修订（必读）：
  - 3 个 anchor 数字修订（Round 7 §1）：
      procedure.investigation.proposal.submitted: 0.23 → 0.30 (COP §4.2.1)
      artifact.form.mbi2: 0.23 → 0.08 (COP §2.1.3(j) — temp RI nomination form, NOT investigation)
      artifact.proposal.detailed_investigation: 0.23 → 0.30 (COP §4.2.1)
  - MBI2 DAG 语义修订（Round 7 §0 + §4.3）：
      MBI2 移到 L1 intake_and_ri_layer (sampling_order=7) 不再在 L3
      MBI2 upstream 改成 procedure.temp_ri_nomination.completed (不是 investigation slot)
      detailed_investigation_proposal 不再 depends_on artifact.form.mbi2
  - 45 个 source label 全部精确化到 COP §x.y.z 引用（Round 7 §1 source_label_revised）

distribution_source: proagent_engineering_estimate_current_authority_round5_2026_05_10
"""

from __future__ import annotations

from typing import Any, Dict, List

from workflow_engine.worldgen.conditional_eval import HIDDEN_STATE_PRIOR_MEANS

DISTRIBUTION_SOURCE = "proagent_engineering_estimate_current_authority_round5_2026_05_10"

# Round 7 修订后的 marginal_anchor (45 项)
# Bool: float; enum: dict[class_name → prob]
MARGINAL_ANCHORS_ROUND7: Dict[str, Any] = {
    "procedure.ri.appointment.completed": 0.86,
    "artifact.form.mbi1": 0.95,
    "procedure.temp_ri_nomination.completed": 0.08,
    "procedure.temp_ri_nomination.terminated": 0.03,
    "procedure.ri_role.terminated": 0.06,
    "artifact.form.mbi5": 0.07,
    "artifact.form.mbi2": 0.08,  # Round 7 修订: 0.23 → 0.08
    "procedure.inspection.prescribed.completed": 0.74,
    "artifact.form.mbi3_or_mbi3a": 0.72,
    "artifact.record.inspection_log": 0.78,
    "artifact.report.inspection": 0.73,
    "artifact.photo.annotated": 0.70,
    "artifact.plan.annotated": 0.64,
    "procedure.investigation.intention_notified": 0.30,
    "artifact.notice.investigation_intention": 0.30,
    "procedure.investigation.proposal.submitted": 0.30,  # Round 7 修订: 0.23 → 0.30
    "artifact.proposal.detailed_investigation": 0.30,    # Round 7 修订: 0.23 → 0.30
    "procedure.investigation.proposal.recognized": 0.18,
    "procedure.investigation.started": 0.20,
    "procedure.supervision_representative.planned": 0.66,
    "procedure.supervision_team.submitted": 0.58,
    "procedure.supervision_team.changed": 0.12,
    "artifact.proposal.repair": 0.57,
    "procedure.rc.pre_notification_given": 0.50,
    "procedure.repair.prescribed.started": 0.55,
    "supervision.site_visit.performed": 0.80,
    "artifact.record.supervision_log_sp1": 0.61,
    "supervision.record.completed": 0.72,
    "supervision.record.retained": 0.68,
    "supervision.record.completed_and_retained": 0.62,
    "artifact.record.test_or_material_witness": 0.44,
    "artifact.certificate.material_or_product": 0.43,
    "artifact.record.nonconformity_sp2": 0.20,
    "procedure.repair.revision_required": 0.18,
    "artifact.proposal.repair_revision": 0.17,
    "procedure.repair.prescribed.completed": 0.42,
    "procedure.completed_work.final_inspection_performed": 0.40,
    "artifact.report.completion": 0.40,
    "artifact.form.mbi4": 0.39,
    "artifact.statement.scope_and_order_coverage": 0.58,
    "artifact.statement.extra_works_separated": 0.19,
    "fire_safety.upgrade_outstanding": 0.16,
    "qual.actor_role": {
        "registered_inspector": 0.58,
        "registered_contractor": 0.22,
        "building_authority": 0.10,
        "owner": 0.10,
    },
    "qual.method_class": {
        "visual_inspection": 0.34,
        "pull_test": 0.12,
        "hammer_tapping": 0.22,
        "drainage_cctv": 0.10,
        "water_test": 0.05,
        "smoke_test": 0.03,
        "material_test": 0.09,
        "self_closing_test": 0.05,
    },
    "qual.artifact_field_group": {
        "form_metadata": 0.22,
        "repair_proposal": 0.18,
        "supervision_record": 0.20,
        "completion_report": 0.12,
        "evidence_photo": 0.16,
        "evidence_plan": 0.12,
    },
}

# Round 7 §1 anchor_source labels (精确化到 COP §x.y.z)
ANCHOR_SOURCES_ROUND7: Dict[str, str] = {
    "procedure.ri.appointment.completed":
        "MBIS_CoP_2023 §2.1.1 + §2.1.3(i) modality=shall + round4_baseline",
    "artifact.form.mbi1":
        "MBIS_CoP_2023 §2.1.3(i) + Appendix 10 modality=shall + round4_baseline",
    "procedure.temp_ri_nomination.completed":
        "MBIS_CoP_2023 §2.1.3(j) modality=shall_if_nominated + round4_baseline",
    "procedure.temp_ri_nomination.terminated":
        "MBIS_CoP_2023 §2.1.3(k) modality=shall_if_terminated + round4_baseline",
    "procedure.ri_role.terminated":
        "MBIS_CoP_2023 §2.1.3(l) modality=shall_if_role_terminated + round4_baseline",
    "artifact.form.mbi5":
        "MBIS_CoP_2023 §2.1.3(s) + Appendix 10 modality=shall_if_role_split + round4_baseline",
    "artifact.form.mbi2":
        "MBIS_CoP_2023 §2.1.3(j) + Appendix 10 modality=shall_if_temp_nomination "
        "+ round4_baseline_for_temp_RI_nomination",
    "procedure.inspection.prescribed.completed":
        "MBIS_CoP_2023 §2.1.3(a) + §3.1 modality=shall + round4_baseline",
    "artifact.form.mbi3_or_mbi3a":
        "MBIS_CoP_2023 §2.1.3(o) + §7.2.2 + Appendix 10 modality=shall + round4_baseline",
    "artifact.record.inspection_log":
        "MBIS_CoP_2023 Appendix 7 §6.1(a) modality=shall + round4_baseline",
    "artifact.report.inspection":
        "MBIS_CoP_2023 §7.2 + §2.1.3(o) modality=shall + round4_baseline",
    "artifact.photo.annotated":
        "MBIS_CoP_2023 Appendix 7 §6.1(c)-(d) modality=shall + round4_baseline",
    "artifact.plan.annotated":
        "MBIS_CoP_2023 Appendix 7 §6.1(d), §8.1(a) + §7.2.4 modality=shall_if_needed/should "
        "+ round4_baseline",
    "procedure.investigation.intention_notified":
        "MBIS_CoP_2023 §4.1 + §4.2.1 modality=shall_if_intends + round4_baseline",
    "artifact.notice.investigation_intention":
        "MBIS_CoP_2023 §4.2.1 modality=shall_if_intends + round4_baseline",
    "procedure.investigation.proposal.submitted":
        "MBIS_CoP_2023 §4.2.1-§4.2.2 modality=shall_if_intends "
        "+ round4_baseline_aligned_to_intention_notice",
    "artifact.proposal.detailed_investigation":
        "MBIS_CoP_2023 §4.2.1-§4.2.2 modality=shall_if_intends "
        "+ round4_baseline_aligned_to_intention_notice",
    "procedure.investigation.proposal.recognized":
        "MBIS_CoP_2023 §4.2.3 modality=shall/prohibition_gate + round4_baseline",
    "procedure.investigation.started":
        "MBIS_CoP_2023 §4.2.3 + §4.1.4 modality=shall_gate_with_exception/may_specialist "
        "+ round4_baseline",
    "procedure.supervision_representative.planned":
        "MBIS_CoP_2023 §2.1.3(m), §6.4.2-§6.4.3, Appendix 6 modality=may_plus_shall_if_appointed "
        "+ round4_baseline",
    "procedure.supervision_team.submitted":
        "MBIS_CoP_2023 §6.4.3-§6.4.4 + Appendix 6 Attachment A modality=may_or_shall_conditionally "
        "+ round4_baseline",
    "procedure.supervision_team.changed":
        "MBIS_CoP_2023 §6.4.6 modality=shall_if_changed + round4_baseline",
    "artifact.proposal.repair":
        "MBIS_CoP_2023 §5.1.2 + §7.2.4 + Appendix 7 §8.1 modality=shall_if_repair_required "
        "+ round4_baseline",
    "procedure.rc.pre_notification_given":
        "MBIS_CoP_2023 §6.5.2 modality=shall_if_repair_checks + round4_baseline",
    "procedure.repair.prescribed.started":
        "MBIS_CoP_2023 §5.1.4-§5.1.6 + Appendix 1 modality=shall_if_repair_required "
        "+ round4_baseline",
    "supervision.site_visit.performed":
        "MBIS_CoP_2023 §6.4.1 + Appendix 6 Table 2 modality=shall + round4_baseline",
    "artifact.record.supervision_log_sp1":
        "MBIS_CoP_2023 Appendix 6 para 6 + Attachment B modality=shall + round4_baseline",
    "supervision.record.completed":
        "MBIS_CoP_2023 Appendix 6 para 6-8 modality=shall + round4_baseline",
    "supervision.record.retained":
        "MBIS_CoP_2023 Appendix 6 para 8 modality=shall + round4_baseline",
    "supervision.record.completed_and_retained":
        "MBIS_CoP_2023 Appendix 6 para 6-8 modality=shall + derived_joint_prevalence "
        "+ round4_baseline",
    "artifact.record.test_or_material_witness":
        "MBIS_CoP_2023 Appendix 6 para 7 + Attachment D modality=shall_if_testing + round4_baseline",
    "artifact.certificate.material_or_product":
        "MBIS_CoP_2023 Appendix 8 §2(e) + Appendix 6 Attachment E modality=shall_if_material_used "
        "+ round4_baseline",
    "artifact.record.nonconformity_sp2":
        "MBIS_CoP_2023 Appendix 6 Attachment B/C modality=shall_if_nonconformity + round4_baseline",
    "procedure.repair.revision_required":
        "MBIS_CoP_2023 §2.1.3(p) + Appendix 8 §2(h) modality=shall_if_revision_required "
        "+ round4_baseline",
    "artifact.proposal.repair_revision":
        "MBIS_CoP_2023 §2.1.3(p) modality=shall_if_revision_required + round4_baseline",
    "procedure.repair.prescribed.completed":
        "MBIS_CoP_2023 §2.1.3(r) + §7.3.1 modality=shall_after_completion + round4_baseline",
    "procedure.completed_work.final_inspection_performed":
        "MBIS_CoP_2023 §6.4.8 modality=shall_before_completion_submission + round4_baseline",
    "artifact.report.completion":
        "MBIS_CoP_2023 §7.3.1-§7.3.3 + §2.1.3(r) modality=shall + round4_baseline",
    "artifact.form.mbi4":
        "MBIS_CoP_2023 §2.1.3(r) + §7.3.2 + Appendix 10 modality=shall + round4_baseline",
    "artifact.statement.scope_and_order_coverage":
        "MBIS_CoP_2023 §3.2.5 + Appendix 7 §6.1(i) + Appendix 8 §2(g) "
        "modality=shall_if_outstanding_order + round4_baseline",
    "artifact.statement.extra_works_separated":
        "MBIS_CoP_2023 §7.2.6 + Appendix 7 §8.2 modality=should_if_extra_works + round4_baseline",
    "fire_safety.upgrade_outstanding":
        "MBIS_CoP_2023 §3.2.4 + Appendix 7 §4(d), §6.1(h) modality=shall_if_applicable "
        "+ round4_baseline",
    "qual.actor_role":
        "MBIS_CoP_2023 §§2.1,2.2,4.2,6,7 actor universe + round4_baseline + engineering_role_mix",
    "qual.method_class":
        "MBIS_CoP_2023 §§3.3-3.6, §4.1.4, Appendix 5/6 method universe + round4_baseline "
        "+ engineering_method_mix",
    "qual.artifact_field_group":
        "MBIS_CoP_2023 Appendices 6,7,8,10 artifact field universe + round4_baseline "
        "+ engineering_artifact_field_mix",
}


def _bool_formula(
    anchor: float,
    sidecar_terms: Dict[str, float],
    hidden_terms: Dict[str, float],
    sidecar_anchors: Dict[str, float],
) -> Dict[str, Any]:
    """构造 centered_sigmoid_linear formula dict (Round 6 §1.1).

    sidecar_terms: {sidecar_slot_id: coef}
    hidden_terms: {H.x: coef}
    sidecar_anchors: 已采样 sidecar slot anchor 表（用于 upstream_expected lookup）
    """
    upstream_expected: Dict[str, float] = {}
    terms: Dict[str, float] = {}
    for slot_id, coef in sidecar_terms.items():
        terms[slot_id] = float(coef)
        upstream_expected[slot_id] = float(sidecar_anchors[slot_id])
    for h_key, coef in hidden_terms.items():
        terms[h_key] = float(coef)
        upstream_expected[h_key] = float(HIDDEN_STATE_PRIOR_MEANS[h_key])
    return {
        "type": "centered_sigmoid_linear",
        "anchor": float(anchor),
        "upstream_expected": upstream_expected,
        "terms": terms,
    }


def _enum_class(
    anchor: float,
    sidecar_terms: Dict[str, float],
    hidden_terms: Dict[str, float],
    sidecar_anchors: Dict[str, float],
) -> Dict[str, Any]:
    """构造 centered_softmax_per_class 单 class block."""
    upstream_expected: Dict[str, float] = {}
    terms: Dict[str, float] = {}
    for slot_id, coef in sidecar_terms.items():
        terms[slot_id] = float(coef)
        upstream_expected[slot_id] = float(sidecar_anchors[slot_id])
    for h_key, coef in hidden_terms.items():
        terms[h_key] = float(coef)
        upstream_expected[h_key] = float(HIDDEN_STATE_PRIOR_MEANS[h_key])
    return {
        "anchor": float(anchor),
        "upstream_expected": upstream_expected,
        "terms": terms,
    }


# Round 7 修订 sampling_order: MBI2 移到 L1 (从 16 改为 7)；
# 原 7-15 (inspection/intention) shift +1; 原 17 (proposal_detailed_investigation) 改为 16；
# 原 18-19 不变（recognized / started）; 原 20+ 不变.
# Round 7 §0 + §4.3 修订表：
#   L1 (1-7): RI appointment, MBI1, temp_ri_nom_completed, temp_ri_nom_terminated,
#             ri_role_terminated, MBI5, **MBI2 (新位置 7)**
#   L2 (8-13): inspection_completed, MBI3/3A, inspection_log, inspection_report,
#              photo_annotated, plan_annotated
#   L3 (14-19): intention_notified, notice_intention, proposal_submitted,
#               proposal_detailed_investigation, proposal_recognized, started
#   L4-L6 (20-45): unchanged from Round 6
SAMPLING_ORDER_ROUND7: Dict[str, int] = {
    # L1 intake_and_ri (Round 7: MBI2 加入此层)
    "procedure.ri.appointment.completed": 1,
    "artifact.form.mbi1": 2,
    "procedure.temp_ri_nomination.completed": 3,
    "procedure.temp_ri_nomination.terminated": 4,
    "procedure.ri_role.terminated": 5,
    "artifact.form.mbi5": 6,
    "artifact.form.mbi2": 7,  # Round 7 §0 修订: temp RI nomination form, 移到 L1
    # L2 prescribed_inspection
    "procedure.inspection.prescribed.completed": 8,
    "artifact.form.mbi3_or_mbi3a": 9,
    "artifact.record.inspection_log": 10,
    "artifact.report.inspection": 11,
    "artifact.photo.annotated": 12,
    "artifact.plan.annotated": 13,
    # L3 detailed_investigation (Round 7 §0: MBI2 已移走)
    "procedure.investigation.intention_notified": 14,
    "artifact.notice.investigation_intention": 15,
    "procedure.investigation.proposal.submitted": 16,
    "artifact.proposal.detailed_investigation": 17,
    "procedure.investigation.proposal.recognized": 18,
    "procedure.investigation.started": 19,
    # L4 repair_supervision
    "procedure.supervision_representative.planned": 20,
    "procedure.supervision_team.submitted": 21,
    "procedure.supervision_team.changed": 22,
    "artifact.proposal.repair": 23,
    "procedure.rc.pre_notification_given": 24,
    "procedure.repair.prescribed.started": 25,
    "supervision.site_visit.performed": 26,
    "artifact.record.supervision_log_sp1": 27,
    "supervision.record.completed": 28,
    "supervision.record.retained": 29,
    "supervision.record.completed_and_retained": 30,
    "artifact.record.test_or_material_witness": 31,
    "artifact.certificate.material_or_product": 32,
    "artifact.record.nonconformity_sp2": 33,
    "procedure.repair.revision_required": 34,
    "artifact.proposal.repair_revision": 35,
    # L5 completion
    "procedure.repair.prescribed.completed": 36,
    "procedure.completed_work.final_inspection_performed": 37,
    "artifact.report.completion": 38,
    "artifact.form.mbi4": 39,
    "artifact.statement.scope_and_order_coverage": 40,
    "artifact.statement.extra_works_separated": 41,
    # L6 statutory + qualifiers
    "fire_safety.upgrade_outstanding": 42,
    "qual.actor_role": 43,
    "qual.method_class": 44,
    "qual.artifact_field_group": 45,
}


def build_round6_round7_formulas() -> Dict[str, Dict[str, Any]]:
    """构造 45 个 sidecar slot 的 Round 6 + Round 7 conditional_formula spec.

    返回：slot_id → {
        sampling_order, upstream_inputs (sidecar+hidden), conditional_formula (centered),
        marginal_anchor, anchor_source, alignment_check (placeholder, MC overrides),
        distribution_source, cop_section
    }
    """
    A = MARGINAL_ANCHORS_ROUND7  # short alias
    # H.* prior_means → 用作 hidden upstream_expected
    out: Dict[str, Dict[str, Any]] = {}

    # ============================================================
    # L1 intake_and_ri
    # ============================================================

    # 1. procedure.ri.appointment.completed (Round 6 §3.1 + Round 7 anchor 0.86 unchanged)
    out["procedure.ri.appointment.completed"] = {
        "sampling_order": 1,
        "upstream_inputs": {
            "hidden": ["H.case_active", "H.age_old_score", "H.admin_discipline_score"],
            "sidecar": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.ri.appointment.completed"],
            sidecar_terms={},
            hidden_terms={
                "H.case_active": 0.55,
                "H.age_old_score": 0.25,
                "H.admin_discipline_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.1 + §2.1.3(i)",
    }

    # 2. artifact.form.mbi1
    out["artifact.form.mbi1"] = {
        "sampling_order": 2,
        "upstream_inputs": {
            "sidecar": ["procedure.ri.appointment.completed"],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi1"],
            sidecar_terms={"procedure.ri.appointment.completed": 1.10},
            hidden_terms={"H.document_maturity_score": 0.30},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(i) + Appendix 10",
    }

    # 3. procedure.temp_ri_nomination.completed
    out["procedure.temp_ri_nomination.completed"] = {
        "sampling_order": 3,
        "upstream_inputs": {
            "sidecar": ["procedure.ri.appointment.completed"],
            "hidden": ["H.admin_instability_score", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.temp_ri_nomination.completed"],
            sidecar_terms={"procedure.ri.appointment.completed": 0.35},
            hidden_terms={
                "H.admin_instability_score": 0.80,
                "H.document_maturity_score": -0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(j)",
    }

    # 4. procedure.temp_ri_nomination.terminated
    out["procedure.temp_ri_nomination.terminated"] = {
        "sampling_order": 4,
        "upstream_inputs": {
            "sidecar": ["procedure.temp_ri_nomination.completed"],
            "hidden": ["H.admin_instability_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.temp_ri_nomination.terminated"],
            sidecar_terms={"procedure.temp_ri_nomination.completed": 1.20},
            hidden_terms={"H.admin_instability_score": 0.55},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(k)",
    }

    # 5. procedure.ri_role.terminated
    out["procedure.ri_role.terminated"] = {
        "sampling_order": 5,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "procedure.temp_ri_nomination.completed",
                "procedure.temp_ri_nomination.terminated",
            ],
            "hidden": ["H.admin_instability_score", "H.repair_complexity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.ri_role.terminated"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.30,
                "procedure.temp_ri_nomination.completed": 0.55,
                "procedure.temp_ri_nomination.terminated": 0.75,
            },
            hidden_terms={
                "H.admin_instability_score": 0.55,
                "H.repair_complexity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(l)",
    }

    # 6. artifact.form.mbi5
    out["artifact.form.mbi5"] = {
        "sampling_order": 6,
        "upstream_inputs": {
            "sidecar": [
                "procedure.temp_ri_nomination.completed",
                "procedure.temp_ri_nomination.terminated",
                "procedure.ri_role.terminated",
            ],
            "hidden": ["H.admin_instability_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi5"],
            sidecar_terms={
                "procedure.temp_ri_nomination.completed": 0.40,
                "procedure.temp_ri_nomination.terminated": 0.75,
                "procedure.ri_role.terminated": 0.90,
            },
            hidden_terms={"H.admin_instability_score": 0.35},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(s) + Appendix 10",
    }

    # 7. artifact.form.mbi2 (Round 7 §0 + §4.3: 移到 L1, 依赖 temp_ri_nomination)
    out["artifact.form.mbi2"] = {
        "sampling_order": 7,
        "upstream_inputs": {
            "sidecar": ["procedure.temp_ri_nomination.completed"],
            "hidden": ["H.admin_instability_score", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi2"],
            sidecar_terms={"procedure.temp_ri_nomination.completed": 1.10},
            hidden_terms={
                "H.admin_instability_score": 0.35,
                "H.document_maturity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(j) + Appendix 10",
    }

    # ============================================================
    # L2 prescribed_inspection
    # ============================================================

    # 8. procedure.inspection.prescribed.completed
    out["procedure.inspection.prescribed.completed"] = {
        "sampling_order": 8,
        "upstream_inputs": {
            "sidecar": ["procedure.ri.appointment.completed", "artifact.form.mbi1"],
            "hidden": [
                "H.defect_present",
                "H.document_maturity_score",
                "H.admin_discipline_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.inspection.prescribed.completed"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.55,
                "artifact.form.mbi1": 0.45,
            },
            hidden_terms={
                "H.defect_present": 0.30,
                "H.document_maturity_score": 0.30,
                "H.admin_discipline_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(a) + §3.1",
    }

    # 9. artifact.form.mbi3_or_mbi3a
    out["artifact.form.mbi3_or_mbi3a"] = {
        "sampling_order": 9,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "artifact.form.mbi1",
                "procedure.inspection.prescribed.completed",
            ],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi3_or_mbi3a"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.30,
                "artifact.form.mbi1": 0.30,
                "procedure.inspection.prescribed.completed": 1.05,
            },
            hidden_terms={"H.document_maturity_score": 0.35},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(o) + §7.2.2 + Appendix 10",
    }

    # 10. artifact.record.inspection_log
    out["artifact.record.inspection_log"] = {
        "sampling_order": 10,
        "upstream_inputs": {
            "sidecar": ["procedure.inspection.prescribed.completed"],
            "hidden": ["H.defect_present", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.record.inspection_log"],
            sidecar_terms={"procedure.inspection.prescribed.completed": 0.90},
            hidden_terms={
                "H.defect_present": 0.25,
                "H.document_maturity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 7 §6.1(a)",
    }

    # 11. artifact.report.inspection
    out["artifact.report.inspection"] = {
        "sampling_order": 11,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "artifact.form.mbi3_or_mbi3a",
                "artifact.record.inspection_log",
            ],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.report.inspection"],
            sidecar_terms={
                "procedure.inspection.prescribed.completed": 0.70,
                "artifact.form.mbi3_or_mbi3a": 0.55,
                "artifact.record.inspection_log": 0.35,
            },
            hidden_terms={"H.document_maturity_score": 0.25},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §7.2 + §2.1.3(o)",
    }

    # 12. artifact.photo.annotated
    out["artifact.photo.annotated"] = {
        "sampling_order": 12,
        "upstream_inputs": {
            "sidecar": ["artifact.record.inspection_log", "artifact.report.inspection"],
            "hidden": ["H.defect_present", "H.defect_severity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.photo.annotated"],
            sidecar_terms={
                "artifact.record.inspection_log": 0.45,
                "artifact.report.inspection": 0.55,
            },
            hidden_terms={
                "H.defect_present": 0.35,
                "H.defect_severity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 7 §6.1(c)-(d)",
    }

    # 13. artifact.plan.annotated
    out["artifact.plan.annotated"] = {
        "sampling_order": 13,
        "upstream_inputs": {
            "sidecar": ["artifact.report.inspection", "artifact.photo.annotated"],
            "hidden": ["H.defect_severity_score", "H.repair_complexity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.plan.annotated"],
            sidecar_terms={
                "artifact.report.inspection": 0.45,
                "artifact.photo.annotated": 0.25,
            },
            hidden_terms={
                "H.defect_severity_score": 0.35,
                "H.repair_complexity_score": 0.45,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 7 §6.1(d), §8.1(a) + §7.2.4",
    }

    # ============================================================
    # L3 detailed_investigation
    # ============================================================

    # 14. procedure.investigation.intention_notified
    out["procedure.investigation.intention_notified"] = {
        "sampling_order": 14,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
            ],
            "hidden": [
                "H.defect_uncertainty",
                "H.defect_severity_score",
                "H.admin_discipline_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.intention_notified"],
            sidecar_terms={
                "procedure.inspection.prescribed.completed": 0.45,
                "artifact.report.inspection": 0.40,
            },
            hidden_terms={
                "H.defect_uncertainty": 0.95,
                "H.defect_severity_score": 0.55,
                "H.admin_discipline_score": 0.15,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.1 + §4.2.1",
    }

    # 15. artifact.notice.investigation_intention
    out["artifact.notice.investigation_intention"] = {
        "sampling_order": 15,
        "upstream_inputs": {
            "sidecar": ["procedure.investigation.intention_notified"],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.notice.investigation_intention"],
            sidecar_terms={"procedure.investigation.intention_notified": 1.35},
            hidden_terms={"H.document_maturity_score": 0.30},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.2.1",
    }

    # 16. procedure.investigation.proposal.submitted (Round 7 anchor 0.30)
    out["procedure.investigation.proposal.submitted"] = {
        "sampling_order": 16,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.intention_notified",
                "artifact.notice.investigation_intention",
            ],
            "hidden": ["H.defect_uncertainty", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.proposal.submitted"],
            sidecar_terms={
                "procedure.investigation.intention_notified": 1.00,
                "artifact.notice.investigation_intention": 0.55,
            },
            hidden_terms={
                "H.defect_uncertainty": 0.55,
                "H.document_maturity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.2.1-§4.2.2",
    }

    # 17. artifact.proposal.detailed_investigation (Round 7 anchor 0.30, 不再 depends on MBI2)
    out["artifact.proposal.detailed_investigation"] = {
        "sampling_order": 17,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.intention_notified",
                "artifact.notice.investigation_intention",
                "procedure.investigation.proposal.submitted",
            ],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.proposal.detailed_investigation"],
            sidecar_terms={
                "procedure.investigation.intention_notified": 0.40,
                "artifact.notice.investigation_intention": 0.30,
                "procedure.investigation.proposal.submitted": 1.05,
            },
            hidden_terms={"H.document_maturity_score": 0.25},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.2.1-§4.2.2",
    }

    # 18. procedure.investigation.proposal.recognized
    out["procedure.investigation.proposal.recognized"] = {
        "sampling_order": 18,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.proposal.submitted",
                "artifact.proposal.detailed_investigation",
            ],
            "hidden": ["H.admin_discipline_score", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.proposal.recognized"],
            sidecar_terms={
                "procedure.investigation.proposal.submitted": 0.90,
                "artifact.proposal.detailed_investigation": 0.65,
            },
            hidden_terms={
                "H.admin_discipline_score": 0.30,
                "H.document_maturity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.2.3",
    }

    # 19. procedure.investigation.started
    out["procedure.investigation.started"] = {
        "sampling_order": 19,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.proposal.submitted",
                "procedure.investigation.proposal.recognized",
                "artifact.proposal.detailed_investigation",
            ],
            "hidden": ["H.defect_severity_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.started"],
            sidecar_terms={
                "procedure.investigation.proposal.submitted": 0.55,
                "procedure.investigation.proposal.recognized": 0.85,
                "artifact.proposal.detailed_investigation": 0.40,
            },
            hidden_terms={
                "H.defect_severity_score": 0.25,
                "H.admin_discipline_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §4.2.3 + §4.1.4",
    }

    # ============================================================
    # L4 repair_supervision
    # ============================================================

    # 20. procedure.supervision_representative.planned
    out["procedure.supervision_representative.planned"] = {
        "sampling_order": 20,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
            ],
            "hidden": [
                "H.repair_need",
                "H.defect_severity_score",
                "H.repair_complexity_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_representative.planned"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.25,
                "procedure.inspection.prescribed.completed": 0.45,
                "artifact.report.inspection": 0.30,
            },
            hidden_terms={
                "H.repair_need": 0.60,
                "H.defect_severity_score": 0.35,
                "H.repair_complexity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(m), §6.4.2-§6.4.3, Appendix 6",
    }

    # 21. procedure.supervision_team.submitted
    out["procedure.supervision_team.submitted"] = {
        "sampling_order": 21,
        "upstream_inputs": {
            "sidecar": [
                "procedure.supervision_representative.planned",
                "procedure.ri.appointment.completed",
            ],
            "hidden": [
                "H.admin_discipline_score",
                "H.document_maturity_score",
                "H.repair_complexity_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_team.submitted"],
            sidecar_terms={
                "procedure.supervision_representative.planned": 0.95,
                "procedure.ri.appointment.completed": 0.25,
            },
            hidden_terms={
                "H.admin_discipline_score": 0.30,
                "H.document_maturity_score": 0.25,
                "H.repair_complexity_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.4.3-§6.4.4 + Appendix 6 Attachment A",
    }

    # 22. procedure.supervision_team.changed
    out["procedure.supervision_team.changed"] = {
        "sampling_order": 22,
        "upstream_inputs": {
            "sidecar": ["procedure.supervision_team.submitted"],
            "hidden": ["H.admin_instability_score", "H.repair_complexity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_team.changed"],
            sidecar_terms={"procedure.supervision_team.submitted": 0.55},
            hidden_terms={
                "H.admin_instability_score": 0.65,
                "H.repair_complexity_score": 0.40,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.4.6",
    }

    # 23. artifact.proposal.repair
    out["artifact.proposal.repair"] = {
        "sampling_order": 23,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
                "artifact.plan.annotated",
                "artifact.photo.annotated",
            ],
            "hidden": ["H.repair_need", "H.defect_severity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.proposal.repair"],
            sidecar_terms={
                "procedure.inspection.prescribed.completed": 0.55,
                "artifact.report.inspection": 0.50,
                "artifact.plan.annotated": 0.25,
                "artifact.photo.annotated": 0.20,
            },
            hidden_terms={
                "H.repair_need": 0.65,
                "H.defect_severity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §5.1.2 + §7.2.4 + Appendix 7 §8.1",
    }

    # 24. procedure.rc.pre_notification_given
    out["procedure.rc.pre_notification_given"] = {
        "sampling_order": 24,
        "upstream_inputs": {
            "sidecar": ["artifact.proposal.repair", "procedure.supervision_team.submitted"],
            "hidden": ["H.contractor_mobilisation_need", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.rc.pre_notification_given"],
            sidecar_terms={
                "artifact.proposal.repair": 0.70,
                "procedure.supervision_team.submitted": 0.45,
            },
            hidden_terms={
                "H.contractor_mobilisation_need": 0.45,
                "H.admin_discipline_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.5.2",
    }

    # 25. procedure.repair.prescribed.started
    out["procedure.repair.prescribed.started"] = {
        "sampling_order": 25,
        "upstream_inputs": {
            "sidecar": [
                "artifact.proposal.repair",
                "procedure.rc.pre_notification_given",
                "procedure.supervision_team.submitted",
            ],
            "hidden": ["H.repair_need", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.repair.prescribed.started"],
            sidecar_terms={
                "artifact.proposal.repair": 0.80,
                "procedure.rc.pre_notification_given": 0.55,
                "procedure.supervision_team.submitted": 0.35,
            },
            hidden_terms={
                "H.repair_need": 0.55,
                "H.admin_discipline_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §5.1.4-§5.1.6 + Appendix 1",
    }

    # 26. supervision.site_visit.performed
    out["supervision.site_visit.performed"] = {
        "sampling_order": 26,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "procedure.repair.prescribed.started",
                "procedure.supervision_team.submitted",
            ],
            "hidden": ["H.defect_severity_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["supervision.site_visit.performed"],
            sidecar_terms={
                "procedure.inspection.prescribed.completed": 0.40,
                "procedure.repair.prescribed.started": 0.65,
                "procedure.supervision_team.submitted": 0.35,
            },
            hidden_terms={
                "H.defect_severity_score": 0.25,
                "H.admin_discipline_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.4.1 + Appendix 6 Table 2",
    }

    # 27. artifact.record.supervision_log_sp1
    out["artifact.record.supervision_log_sp1"] = {
        "sampling_order": 27,
        "upstream_inputs": {
            "sidecar": ["supervision.site_visit.performed", "procedure.supervision_team.submitted"],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.record.supervision_log_sp1"],
            sidecar_terms={
                "supervision.site_visit.performed": 0.85,
                "procedure.supervision_team.submitted": 0.50,
            },
            hidden_terms={"H.document_maturity_score": 0.30},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 6 + Attachment B",
    }

    # 28. supervision.record.completed
    out["supervision.record.completed"] = {
        "sampling_order": 28,
        "upstream_inputs": {
            "sidecar": ["supervision.site_visit.performed", "artifact.record.supervision_log_sp1"],
            "hidden": ["H.document_maturity_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["supervision.record.completed"],
            sidecar_terms={
                "supervision.site_visit.performed": 0.65,
                "artifact.record.supervision_log_sp1": 0.55,
            },
            hidden_terms={
                "H.document_maturity_score": 0.30,
                "H.admin_discipline_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 6-8",
    }

    # 29. supervision.record.retained
    out["supervision.record.retained"] = {
        "sampling_order": 29,
        "upstream_inputs": {
            "sidecar": ["supervision.record.completed", "artifact.record.supervision_log_sp1"],
            "hidden": ["H.document_maturity_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["supervision.record.retained"],
            sidecar_terms={
                "supervision.record.completed": 0.75,
                "artifact.record.supervision_log_sp1": 0.30,
            },
            hidden_terms={
                "H.document_maturity_score": 0.35,
                "H.admin_discipline_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 8",
    }

    # 30. supervision.record.completed_and_retained (joint flag, post-sample clamp 由 sidecar.py 处理)
    out["supervision.record.completed_and_retained"] = {
        "sampling_order": 30,
        "upstream_inputs": {
            "sidecar": ["supervision.record.completed", "supervision.record.retained"],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["supervision.record.completed_and_retained"],
            sidecar_terms={
                "supervision.record.completed": 0.95,
                "supervision.record.retained": 0.95,
            },
            hidden_terms={"H.document_maturity_score": 0.25},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 6-8",
    }

    # 31. artifact.record.test_or_material_witness
    out["artifact.record.test_or_material_witness"] = {
        "sampling_order": 31,
        "upstream_inputs": {
            "sidecar": ["procedure.repair.prescribed.started", "supervision.site_visit.performed"],
            "hidden": [
                "H.testing_need",
                "H.material_replacement_need",
                "H.repair_quality_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.record.test_or_material_witness"],
            sidecar_terms={
                "procedure.repair.prescribed.started": 0.55,
                "supervision.site_visit.performed": 0.40,
            },
            hidden_terms={
                "H.testing_need": 0.60,
                "H.material_replacement_need": 0.30,
                "H.repair_quality_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 7 + Attachment D",
    }

    # 32. artifact.certificate.material_or_product
    out["artifact.certificate.material_or_product"] = {
        "sampling_order": 32,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.started",
                "artifact.record.test_or_material_witness",
            ],
            "hidden": [
                "H.material_replacement_need",
                "H.fire_safety_need",
                "H.document_maturity_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.certificate.material_or_product"],
            sidecar_terms={
                "procedure.repair.prescribed.started": 0.40,
                "artifact.record.test_or_material_witness": 0.55,
            },
            hidden_terms={
                "H.material_replacement_need": 0.65,
                "H.fire_safety_need": 0.25,
                "H.document_maturity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 8 §2(e) + Appendix 6 Attachment E",
    }

    # 33. artifact.record.nonconformity_sp2
    out["artifact.record.nonconformity_sp2"] = {
        "sampling_order": 33,
        "upstream_inputs": {
            "sidecar": [
                "supervision.site_visit.performed",
                "artifact.record.test_or_material_witness",
            ],
            "hidden": [
                "H.nonconformity_risk",
                "H.defect_severity_score",
                "H.repair_complexity_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.record.nonconformity_sp2"],
            sidecar_terms={
                "supervision.site_visit.performed": 0.40,
                "artifact.record.test_or_material_witness": 0.45,
            },
            hidden_terms={
                "H.nonconformity_risk": 0.90,
                "H.defect_severity_score": 0.35,
                "H.repair_complexity_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 Attachment B/C",
    }

    # 34. procedure.repair.revision_required
    out["procedure.repair.revision_required"] = {
        "sampling_order": 34,
        "upstream_inputs": {
            "sidecar": [
                "artifact.proposal.repair",
                "artifact.record.nonconformity_sp2",
                "artifact.record.test_or_material_witness",
            ],
            "hidden": [
                "H.repair_complexity_score",
                "H.defect_severity_score",
                "H.admin_instability_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.repair.revision_required"],
            sidecar_terms={
                "artifact.proposal.repair": 0.45,
                "artifact.record.nonconformity_sp2": 0.75,
                "artifact.record.test_or_material_witness": 0.30,
            },
            hidden_terms={
                "H.repair_complexity_score": 0.55,
                "H.defect_severity_score": 0.35,
                "H.admin_instability_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(p) + Appendix 8 §2(h)",
    }

    # 35. artifact.proposal.repair_revision
    out["artifact.proposal.repair_revision"] = {
        "sampling_order": 35,
        "upstream_inputs": {
            "sidecar": ["procedure.repair.revision_required", "artifact.proposal.repair"],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.proposal.repair_revision"],
            sidecar_terms={
                "procedure.repair.revision_required": 1.05,
                "artifact.proposal.repair": 0.35,
            },
            hidden_terms={"H.document_maturity_score": 0.25},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(p)",
    }

    # ============================================================
    # L5 completion
    # ============================================================

    # 36. procedure.repair.prescribed.completed
    out["procedure.repair.prescribed.completed"] = {
        "sampling_order": 36,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.started",
                "procedure.repair.revision_required",
                "supervision.record.completed_and_retained",
            ],
            "hidden": ["H.repair_quality_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.repair.prescribed.completed"],
            sidecar_terms={
                "procedure.repair.prescribed.started": 0.85,
                "procedure.repair.revision_required": -0.45,
                "supervision.record.completed_and_retained": 0.35,
            },
            hidden_terms={
                "H.repair_quality_score": 0.55,
                "H.admin_discipline_score": 0.30,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(r) + §7.3.1",
    }

    # 37. procedure.completed_work.final_inspection_performed
    out["procedure.completed_work.final_inspection_performed"] = {
        "sampling_order": 37,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.completed",
                "supervision.site_visit.performed",
                "supervision.record.completed",
                "supervision.record.retained",
            ],
            "hidden": ["H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.completed_work.final_inspection_performed"],
            sidecar_terms={
                "procedure.repair.prescribed.completed": 1.00,
                "supervision.site_visit.performed": 0.30,
                "supervision.record.completed": 0.35,
                "supervision.record.retained": 0.30,
            },
            hidden_terms={"H.admin_discipline_score": 0.25},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.4.8",
    }

    # 38. artifact.report.completion
    out["artifact.report.completion"] = {
        "sampling_order": 38,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.completed",
                "procedure.completed_work.final_inspection_performed",
                "supervision.record.completed_and_retained",
            ],
            "hidden": ["H.document_maturity_score", "H.admin_discipline_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.report.completion"],
            sidecar_terms={
                "procedure.repair.prescribed.completed": 0.75,
                "procedure.completed_work.final_inspection_performed": 0.85,
                "supervision.record.completed_and_retained": 0.30,
            },
            hidden_terms={
                "H.document_maturity_score": 0.35,
                "H.admin_discipline_score": 0.20,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §7.3.1-§7.3.3 + §2.1.3(r)",
    }

    # 39. artifact.form.mbi4
    out["artifact.form.mbi4"] = {
        "sampling_order": 39,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.completed",
                "procedure.completed_work.final_inspection_performed",
                "artifact.report.completion",
            ],
            "hidden": ["H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi4"],
            sidecar_terms={
                "procedure.repair.prescribed.completed": 0.55,
                "procedure.completed_work.final_inspection_performed": 0.65,
                "artifact.report.completion": 0.85,
            },
            hidden_terms={"H.document_maturity_score": 0.30},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(r) + §7.3.2 + Appendix 10",
    }

    # 40. artifact.statement.scope_and_order_coverage
    out["artifact.statement.scope_and_order_coverage"] = {
        "sampling_order": 40,
        "upstream_inputs": {
            "sidecar": [
                "artifact.report.inspection",
                "artifact.proposal.repair",
                "artifact.report.completion",
                "artifact.plan.annotated",
            ],
            "hidden": ["H.repair_complexity_score", "H.document_maturity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.statement.scope_and_order_coverage"],
            sidecar_terms={
                "artifact.report.inspection": 0.30,
                "artifact.proposal.repair": 0.50,
                "artifact.report.completion": 0.35,
                "artifact.plan.annotated": 0.25,
            },
            hidden_terms={
                "H.repair_complexity_score": 0.35,
                "H.document_maturity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §3.2.5 + Appendix 7 §6.1(i) + Appendix 8 §2(g)",
    }

    # 41. artifact.statement.extra_works_separated
    out["artifact.statement.extra_works_separated"] = {
        "sampling_order": 41,
        "upstream_inputs": {
            "sidecar": [
                "artifact.proposal.repair",
                "procedure.repair.revision_required",
                "artifact.statement.scope_and_order_coverage",
            ],
            "hidden": ["H.ubw_extra_work", "H.repair_complexity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.statement.extra_works_separated"],
            sidecar_terms={
                "artifact.proposal.repair": 0.45,
                "procedure.repair.revision_required": 0.35,
                "artifact.statement.scope_and_order_coverage": 0.25,
            },
            hidden_terms={
                "H.ubw_extra_work": 0.95,
                "H.repair_complexity_score": 0.35,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §7.2.6 + Appendix 7 §8.2",
    }

    # ============================================================
    # L6 statutory + qualifiers
    # ============================================================

    # 42. fire_safety.upgrade_outstanding
    out["fire_safety.upgrade_outstanding"] = {
        "sampling_order": 42,
        "upstream_inputs": {
            "sidecar": ["artifact.report.inspection", "artifact.photo.annotated"],
            "hidden": [
                "H.fire_safety_need",
                "H.age_old_score",
                "H.admin_instability_score",
                "H.defect_severity_score",
            ],
        },
        "conditional_formula": _bool_formula(
            anchor=A["fire_safety.upgrade_outstanding"],
            sidecar_terms={
                "artifact.report.inspection": 0.20,
                "artifact.photo.annotated": 0.15,
            },
            hidden_terms={
                "H.fire_safety_need": 1.10,
                "H.age_old_score": 0.35,
                "H.admin_instability_score": 0.30,
                "H.defect_severity_score": 0.25,
            },
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §3.2.4 + Appendix 7 §4(d), §6.1(h)",
    }

    # 43. qual.actor_role (enum, 4 classes)
    actor_anchors = A["qual.actor_role"]
    out["qual.actor_role"] = {
        "sampling_order": 43,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "procedure.repair.prescribed.started",
                "procedure.repair.prescribed.completed",
                "procedure.rc.pre_notification_given",
                "supervision.site_visit.performed",
                "fire_safety.upgrade_outstanding",
                "artifact.report.completion",
                "procedure.ri_role.terminated",
            ],
            "hidden": ["H.admin_instability_score"],
        },
        "conditional_formula": {
            "type": "centered_softmax_per_class",
            "classes": {
                "registered_inspector": _enum_class(
                    anchor=actor_anchors["registered_inspector"],
                    sidecar_terms={
                        "procedure.ri.appointment.completed": 0.35,
                        "supervision.site_visit.performed": 0.25,
                        "artifact.report.completion": 0.15,
                    },
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "registered_contractor": _enum_class(
                    anchor=actor_anchors["registered_contractor"],
                    sidecar_terms={
                        "procedure.repair.prescribed.started": 0.55,
                        "procedure.rc.pre_notification_given": 0.40,
                        "procedure.repair.prescribed.completed": 0.25,
                    },
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "building_authority": _enum_class(
                    anchor=actor_anchors["building_authority"],
                    sidecar_terms={
                        "fire_safety.upgrade_outstanding": 0.50,
                        "artifact.report.completion": 0.25,
                    },
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "owner": _enum_class(
                    anchor=actor_anchors["owner"],
                    sidecar_terms={"procedure.ri_role.terminated": 0.20},
                    hidden_terms={"H.admin_instability_score": 0.30},
                    sidecar_anchors=A,
                ),
            },
        },
        "cop_section": "MBIS_CoP_2023 §§2.1,2.2,4.2,6,7",
    }

    # 44. qual.method_class (enum, 8 classes)
    method_anchors = A["qual.method_class"]
    out["qual.method_class"] = {
        "sampling_order": 44,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
                "procedure.repair.prescribed.started",
                "artifact.record.test_or_material_witness",
                "artifact.certificate.material_or_product",
                "fire_safety.upgrade_outstanding",
            ],
            "hidden": [
                "H.defect_present",
                "H.defect_severity_score",
                "H.testing_need",
                "H.material_replacement_need",
                "H.drainage_issue",
                "H.fire_door_issue",
            ],
        },
        "conditional_formula": {
            "type": "centered_softmax_per_class",
            "classes": {
                "visual_inspection": _enum_class(
                    anchor=method_anchors["visual_inspection"],
                    sidecar_terms={
                        "procedure.inspection.prescribed.completed": 0.25,
                        "artifact.report.inspection": 0.20,
                    },
                    hidden_terms={"H.defect_present": 0.15},
                    sidecar_anchors=A,
                ),
                "pull_test": _enum_class(
                    anchor=method_anchors["pull_test"],
                    sidecar_terms={
                        "procedure.repair.prescribed.started": 0.55,
                        "artifact.record.test_or_material_witness": 0.45,
                    },
                    hidden_terms={"H.testing_need": 0.35},
                    sidecar_anchors=A,
                ),
                "hammer_tapping": _enum_class(
                    anchor=method_anchors["hammer_tapping"],
                    sidecar_terms={"procedure.inspection.prescribed.completed": 0.35},
                    hidden_terms={"H.defect_severity_score": 0.35},
                    sidecar_anchors=A,
                ),
                "drainage_cctv": _enum_class(
                    anchor=method_anchors["drainage_cctv"],
                    sidecar_terms={},
                    hidden_terms={"H.drainage_issue": 0.90},
                    sidecar_anchors=A,
                ),
                "water_test": _enum_class(
                    anchor=method_anchors["water_test"],
                    sidecar_terms={},
                    hidden_terms={"H.drainage_issue": 0.65},
                    sidecar_anchors=A,
                ),
                "smoke_test": _enum_class(
                    anchor=method_anchors["smoke_test"],
                    sidecar_terms={},
                    hidden_terms={"H.drainage_issue": 0.55},
                    sidecar_anchors=A,
                ),
                "material_test": _enum_class(
                    anchor=method_anchors["material_test"],
                    sidecar_terms={
                        "artifact.record.test_or_material_witness": 0.45,
                        "artifact.certificate.material_or_product": 0.55,
                    },
                    hidden_terms={"H.material_replacement_need": 0.40},
                    sidecar_anchors=A,
                ),
                "self_closing_test": _enum_class(
                    anchor=method_anchors["self_closing_test"],
                    sidecar_terms={"fire_safety.upgrade_outstanding": 0.65},
                    hidden_terms={"H.fire_door_issue": 0.90},
                    sidecar_anchors=A,
                ),
            },
        },
        "cop_section": "MBIS_CoP_2023 §§3.3-3.6, §4.1.4, Appendix 5/6",
    }

    # 45. qual.artifact_field_group (enum, 6 classes)
    field_anchors = A["qual.artifact_field_group"]
    out["qual.artifact_field_group"] = {
        "sampling_order": 45,
        "upstream_inputs": {
            "sidecar": [
                "artifact.form.mbi1",
                "artifact.form.mbi2",
                "artifact.form.mbi3_or_mbi3a",
                "artifact.form.mbi4",
                "artifact.form.mbi5",
                "artifact.proposal.repair",
                "artifact.proposal.repair_revision",
                "artifact.record.supervision_log_sp1",
                "artifact.report.completion",
                "artifact.photo.annotated",
                "artifact.plan.annotated",
            ],
            "hidden": ["H.document_maturity_score", "H.repair_complexity_score"],
        },
        "conditional_formula": {
            "type": "centered_softmax_per_class",
            "classes": {
                "form_metadata": _enum_class(
                    anchor=field_anchors["form_metadata"],
                    sidecar_terms={
                        "artifact.form.mbi1": 0.20,
                        "artifact.form.mbi2": 0.15,
                        "artifact.form.mbi3_or_mbi3a": 0.15,
                        "artifact.form.mbi4": 0.15,
                        "artifact.form.mbi5": 0.15,
                    },
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "repair_proposal": _enum_class(
                    anchor=field_anchors["repair_proposal"],
                    sidecar_terms={
                        "artifact.proposal.repair": 0.55,
                        "artifact.proposal.repair_revision": 0.30,
                    },
                    hidden_terms={"H.repair_complexity_score": 0.20},
                    sidecar_anchors=A,
                ),
                "supervision_record": _enum_class(
                    anchor=field_anchors["supervision_record"],
                    sidecar_terms={"artifact.record.supervision_log_sp1": 0.55},
                    hidden_terms={"H.document_maturity_score": 0.20},
                    sidecar_anchors=A,
                ),
                "completion_report": _enum_class(
                    anchor=field_anchors["completion_report"],
                    sidecar_terms={
                        "artifact.report.completion": 0.60,
                        "artifact.form.mbi4": 0.25,
                    },
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "evidence_photo": _enum_class(
                    anchor=field_anchors["evidence_photo"],
                    sidecar_terms={"artifact.photo.annotated": 0.55},
                    hidden_terms={},
                    sidecar_anchors=A,
                ),
                "evidence_plan": _enum_class(
                    anchor=field_anchors["evidence_plan"],
                    sidecar_terms={"artifact.plan.annotated": 0.55},
                    hidden_terms={"H.repair_complexity_score": 0.20},
                    sidecar_anchors=A,
                ),
            },
        },
        "cop_section": "MBIS_CoP_2023 Appendices 6,7,8,10",
    }

    return out


# 缓存：模块 import 时一次性构造
_FORMULAS_CACHE: Dict[str, Dict[str, Any]] = {}


def get_round6_round7_formulas() -> Dict[str, Dict[str, Any]]:
    """单例 lookup（避免每次 build registry 重新构造）."""
    global _FORMULAS_CACHE
    if not _FORMULAS_CACHE:
        _FORMULAS_CACHE = build_round6_round7_formulas()
    return _FORMULAS_CACHE
