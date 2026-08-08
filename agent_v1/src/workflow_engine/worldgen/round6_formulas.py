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
    # 🔴 A1.6 补裁（2026-08-06，审核门必须修 A）：原串写 `derived_joint_prevalence`，
    # 指的是「completed 0.72 × retained_given_completed 0.85 = 0.62」那条推导——
    # **它已在本步被明确否掉**（0.62 结构不可达，可达上界 P(both)=0.5212；且 0.85 是
    # 无出处的工程比值）。声明值改成 0.39 之后来源串若不同步，注册表就会「值是 0.39、
    # 来源说的是一条会得出 0.62 的推导」，即本项目反复点名的「静态说明与实值脱节」。
    # 现声明值＝**钳制后实现边际**，出自闭式四因子推导，输入全部是注册表已声明参数：
    #   P(retained|completed) = sigmoid(logit(0.68) + 0.75×(1−0.72)) = 0.723876
    #   P(both)               = 0.72 × 0.723876                      = 0.521191
    #   P(采样真|both)        = sigmoid(logit(0.62) + 0.95×0.28 + 0.95×0.32) = 0.742604
    #   实现边际              = 0.521191 × 0.742604 = 0.3870 → 0.39
    # 推导本体与裁定理由见本文件 `POST_CLAMP_REALIZED_MARGINALS` 段。
    "supervision.record.completed_and_retained":
        "MBIS_CoP_2023 Appendix 6 para 6-8 modality=shall "
        "+ post_clamp_realized_marginal_closed_form_A16_20260806 "
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
SAMPLING_ORDER_ROUND7: Dict[str, float] = {  # #38 改锚后 mbi5=25.7，值域含非整数
    # L1 intake_and_ri (Round 7: MBI2 加入此层)
    "procedure.ri.appointment.completed": 1,
    "artifact.form.mbi1": 2,
    "procedure.temp_ri_nomination.completed": 3,
    "procedure.temp_ri_nomination.terminated": 4,
    "procedure.ri_role.terminated": 5,
    # #38 改锚（换池批步 A1.4，2026-08-06）：mbi5 由 L1 order 6 移到 25.7——
    # 正确依赖是槽 4 事件（repair_supervising_ri.appointment.completed，
    # order 25.5，池 v2 供给侧新槽：修葺开工(25)后、监督活动(26+)前委任），
    # mbi5 必须在其后采样；同时 mbi5 的唯一下游 qual.artifact_field_group(45)
    # 要求 mbi5 < 45（构造期 DAG 硬闸 `_validate_sidecar_sampling_dag` 实抓过
    # 一次 45.7 的违例——别再往后挪）。原 6 号位空出不回填（整表平移会挪动
    # 全部 39 个后续槽的序号，churn 远大于收益）；连续性断言改锚见
    # test_round6_round7_conditional.DAGConsistencyTests。
    "artifact.form.mbi5": 25.7,
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


# ===================================================================== #
# 池 v2 供给侧新槽（#38，换池批步 A1.3/A1.4，2026-08-06）
# ===================================================================== #
#
# 授权：`决议_38裁定_20260806.md` §二（登记先行、采样随池 v2、分布授权随批）＋
# `技术与研究债.md`「#38 换池批供给侧项」＋`换池批总工单_v1_20260806.md` A1.3/A1.4。
#
# 🔴 分布参数纪律：下表 anchor 与各公式系数原为**结构占位的工程推导值**（同表比值
# 反推，46/47 号槽先例同法），**未经分布授权门**——A1.3 明写「分布参数走 A1.6
# 不代拟」。
# ✅ 2026-08-06 A1.6 落地（`决议_A16裁定_20260806.md` §二）：三槽参数已裁——
#   槽 2 `supervision.nonconformity.found`                    = 0.22（两线一致，确认占位值）
#   槽 3 `procedure.repair.revision_proposal.submitted_to_ba` = 0.17（随 #12 终值联动；
#        乙路下 #12 anchor 留 0.18 ⇒ 0.18 × 0.9444 = 0.17，原占位恰好成立。
#        ⚠️ 公式中心化基 `upstream_expected["procedure.repair.revision_required"]`
#        必须与 #12 终值同步，见下方 ③ 段——落值时两处一起动）
#   槽 4 `procedure.repair_supervising_ri.appointment.completed` = 0.075（稀有锚四条论证成立）
# 三槽 `distribution_source` 随之由 PLACEHOLDER 换实值（见
# `POOL_V2_SUPPLY_DISTRIBUTION_SOURCE`）；门检判据＝分布来源表零 PLACEHOLDER
# （工单 A1.6/D3）。池生成（步 B）在 A3 封存之后，结构上不可能带占位参数出池。
#
# 采样序（全表现值域 1-45 整数 ＋ 20.5 ＋ 46-51，本组取非整避让）：
#   槽 2 supervision.nonconformity.found        = 32.5（> site_visit 26 / test_witness 31；< sp2 33）
#   槽 3 procedure.repair.revision_proposal.submitted_to_ba = 34.5（> revision_required 34）
#   槽 4 procedure.repair_supervising_ri.appointment.completed = 25.5
#        （> prescribed.started 25 等全部上游；< 监督活动 26+——委任先于该 RI 到场监督）
#   （mbi5 随之移 25.7：> 槽 4，且 < 其唯一下游 qual.artifact_field_group 45；
#    见 SAMPLING_ORDER_ROUND7 注——45.7 首版被 DAG 硬闸当场拦下）

# A1.6 分布授权门通过后的来源串（2026-08-06）。
# 命名按官方线 §三 裁定：**去 `from_proagent` 署名歧义**——比值推导是本批的结构
# 估计，不是 proagent 出品（期限锚八槽写 `from_proagent` 是因为估计真来自
# proagent DEBT-020，本组没有那个来历，照抄就是伪造署名）。
POOL_V2_SUPPLY_DISTRIBUTION_SOURCE = (
    "pool_v2_supply_structural_ratio_on_round5_base"
    "_A16_authorized_20260806_mc_caliber_implementation_baseline"
)

# mbi5 / sp2：**槽不新、公式被 #38 改锚**，边际锚未动（0.07 / 0.20）。
# A1.6 MC 实测两槽在原锚上过阈（见实施记录），故按「改锚公式重新授权」记，
# 与三新槽的「结构比值首次授权」区分——两件事共用一个串会丢失来历。
POOL_V2_REWIRED_DISTRIBUTION_SOURCE = (
    "proagent_engineering_estimate_current_authority_round5_2026_05_10"
    "_pool_v2_rewired_formula_A16_reauthorized_20260806_mc_caliber_implementation_baseline"
)

# 三新槽采样序单源（registry.py G 组记录与 DAG 测试都从这里取，防双账本漂移）。
POOL_V2_SUPPLY_SAMPLING_ORDERS: Dict[str, float] = {
    "supervision.nonconformity.found": 32.5,
    "procedure.repair.revision_proposal.submitted_to_ba": 34.5,
    "procedure.repair_supervising_ri.appointment.completed": 25.5,
}

# anchor 推导（同表比值法，46/47 先例；全部待授权门裁定，见上）：
#   槽 2 = sp2 记录 0.20 ÷ 最保守事件→文书比值 0.9286（mbi4/repair.completed）
#          = 0.2154 → 0.22（「发现」是「记录」的上游，发现 ≥ 记录）
#   槽 3 = revision_required 0.18 × 同表文书履行比值 0.9444
#          （proposal.repair_revision/revision_required）= 0.17（glm 起点：
#          流行率取 revision_required 子集，`技术与研究债.md:10324`）
#   槽 4 = mbi5 0.07 ÷ 0.9286 = 0.0754 → 0.075（MBI5 表单是槽 4 事件的法定文书）
POOL_V2_SUPPLY_ANCHORS: Dict[str, float] = {
    "supervision.nonconformity.found": 0.22,
    "procedure.repair.revision_proposal.submitted_to_ba": 0.17,
    "procedure.repair_supervising_ri.appointment.completed": 0.075,
}

# Round6/7 overlay 射程内、本批公式被改锚的两槽——overlay 给它们盖
# `POOL_V2_REWIRED_DISTRIBUTION_SOURCE`（A1.6 前是 PLACEHOLDER：分布随公式改动
# 而失据，授权门重估前不得冒充 Round 7 档位；A1.6 MC 实测两槽在原锚上过阈后换实值）。
POOL_V2_REWIRED_OVERLAY_SLOTS = frozenset({
    "artifact.form.mbi5",
    "artifact.record.nonconformity_sp2",
})


# ===================================================================== #
# A1.6 分布授权（`决议_A16裁定_20260806.md`，2026-08-06）
# ===================================================================== #

# 🔴 口径分界句（决议 §一.1 钉死，官方线 §一.4 定文本）。
# 写进被授权槽的 `semantic_note`，防「门④ pass」被读成「分布真实」。
A16_MC_CALIBER_BOUNDARY_NOTE = (
    "A1.6 分布授权（决议_A16裁定_20260806 §一.1）：本槽 anchor 与中心化 "
    "upstream_expected ＝ MC 口径（rerun_distribution_mc.CONTEXT_CALIBER "
    "＋ fragments_per_building=4）下的**实现一致性基准**，不是真实分布声明。"
    "门④ pass ≠ 真实池分布符合工程预期——后者以换池批 D 步实测为准；"
    "真实池与本基准的偏离属 #37 已知问题（DEBT-086）。"
)

# 🔴 MC 口径的每栋碎片数（决议 §四钉参）。承重：全部 any_true/all_true 聚合期望
# 都是 k 的函数，中心化 expected 的推导与门检 MC 必须用同一个 k。
# ⚠️ 诚实边界：生产池的每栋碎片数是分布而不是常数 4，与本常数的偏离归换池批
# D 步实测对照（决议 §四同款注）。
MC_CALIBER_FRAGMENTS_PER_BUILDING = 4

# 🔴 A1.6 补裁（决议 §三「fail 者逐槽当场补裁」，已知 ≥1 例）：
# `supervision.record.completed_and_retained` 的**钳制后实现边际**。
#
# 病灶：该槽是联合旗标，`sidecar._apply_clamps` 在采样后强制
# `value ∧ (completed ∧ retained)`（钳制随 2026-07-07 粒度两相分派引入，
# 徽章 `stale_reason=granularity_split_lost_terms` 说的就是这件事）。
# 声明的 0.62 出自「completed 0.72 × retained_given_completed 0.85」，
# 而生成器自己的耦合给不出 0.85：
#     P(retained|completed) = sigmoid(logit(0.68) + 0.75×(1−0.72)) = 0.7239
#     ⇒ 可达上界 P(both)   = 0.72 × 0.7239                        = 0.5212
# **0.62 > 0.5212 ⇒ 声明的边际结构上不可达**（不是标定偏差，是无解）。
# 闭式实现边际（全部输入均为注册表已声明参数，零观测回写）：
#     P(采样真|both) = sigmoid(logit(0.62) + 0.95×(1−0.72) + 0.95×(1−0.68)) = 0.7426
#     实现边际       = 0.5212 × 0.7426 = 0.3870 → **0.39**
# （诊断 MC n=10000 实测 0.3867、独立探针 n=12000 实测 0.3784，用于**验证**推导，
#  不是取值来源。）
#
# 裁定理由（为什么改联合旗标的声明，而不是改 retained 的耦合）：
#   ① `retained` 的边际 0.68 与耦合 0.75 都是 Round 7 档、且 A1.6 MC 各自过阈，
#      动它们要连带改两个槽的分布及其下游（final_inspection 同时读这两个），
#      射程远超 A1.6；
#   ② 联合旗标是**派生量**，其值由分量决定，不可独立声明；
#   ③ 0.85 这个比值是无出处的工程比值（`derived_joint_prevalence`），
#      证据力弱于两个分量槽自身的锚。
#
# 🔴 结构后果（如实记，不掩盖）：本槽实现边际 0.39 **小于** 其分量合取
# P(both)=0.52 —— 即「两项都做了、联合旗标仍为假」约占 13 个百分点。
# 名字（completed_and_retained）说它就是合取，多出来的那层独立伯努利因此是
# **语义冗余**。去掉那层＝改采样器（键控子流下不移位，但属结构改动），
# 超出 A1.6「重估分布参数」射程，登记为待裁项，不在本步动。
#
# ⚠️ 本表只改 `marginal_anchor` / `prevalence`（＝声明的实现边际），
# **不改公式内部的 centering anchor**（仍取 `MARGINAL_ANCHORS_ROUND7` 的 0.62，
# 那是钳制前的中心）。对被钳制的槽，这两个量按构造就不相等；把它们焊成一个数
# 正是本槽长期对不上的原因。
POST_CLAMP_REALIZED_MARGINALS: Dict[str, float] = {
    "supervision.record.completed_and_retained": 0.39,
}

# A1.6 授权集：口径分界句 ＋ 来源串加注的射程。
# ＝ 决议 §一 的 13 槽 ∪ 乙路改中心化的槽 ∪ 补裁槽 ∪ 原 PLACEHOLDER 五槽。
# （乙路成员由 registry 侧**机械枚举**得出，不在这里硬编码——见
#  `_apply_a16_building_aggregation_centering`；本表只管「来源串要不要加注」。）
A16_ANNOTATED_ROUND7_SLOTS = frozenset({
    # 决议 §一：13 槽（7 纯 H 保声明值不动 ＋ 6 接线槽改中心化）
    "procedure.ri.appointment.completed",
    "procedure.temp_ri_nomination.completed",
    "procedure.temp_ri_nomination.terminated",
    "procedure.ri_role.terminated",
    "procedure.investigation.intention_notified",
    "procedure.investigation.proposal.submitted",
    "procedure.investigation.proposal.recognized",
    "procedure.supervision_representative.planned",
    "procedure.supervision_team.submitted",
    "procedure.supervision_team.changed",
    "procedure.rc.pre_notification_given",
    "procedure.repair.revision_required",
    "procedure.completed_work.final_inspection_performed",
    # 决议 §三 补裁
    "supervision.record.completed_and_retained",
})

A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX = (
    "_A16_mc_caliber_implementation_baseline_20260806"
)


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
    # #37（决议_37修法_20260805 §一.2）：楼级槽。H.admin_discipline_score 无楼级
    # 对应量 ⇒ 删项（乙形，中心化模式下均值回 anchor）；H.case_active / H.age_old_score
    # 有楼级恒等映射（building_context 三键，sidecar.py）⇒ 保留（甲的退化形）。
    out["procedure.ri.appointment.completed"] = {
        "sampling_order": 1,
        "upstream_inputs": {
            "hidden": ["H.case_active", "H.age_old_score"],
            "sidecar": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.ri.appointment.completed"],
            sidecar_terms={},
            hidden_terms={
                "H.case_active": 0.55,
                "H.age_old_score": 0.25,
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
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.temp_ri_nomination.completed"] = {
        "sampling_order": 3,
        "upstream_inputs": {
            "sidecar": ["procedure.ri.appointment.completed"],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.temp_ri_nomination.completed"],
            sidecar_terms={"procedure.ri.appointment.completed": 0.35},
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(j)",
    }

    # 4. procedure.temp_ri_nomination.terminated
    # #37：楼级槽，H 项无楼级对应量 ⇒ 删（乙形；可忽略档也修，清单必须能归零）。
    out["procedure.temp_ri_nomination.terminated"] = {
        "sampling_order": 4,
        "upstream_inputs": {
            "sidecar": ["procedure.temp_ri_nomination.completed"],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.temp_ri_nomination.terminated"],
            sidecar_terms={"procedure.temp_ri_nomination.completed": 1.20},
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(k)",
    }

    # 5. procedure.ri_role.terminated
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.ri_role.terminated"] = {
        "sampling_order": 5,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "procedure.temp_ri_nomination.completed",
                "procedure.temp_ri_nomination.terminated",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.ri_role.terminated"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.30,
                "procedure.temp_ri_nomination.completed": 0.55,
                "procedure.temp_ri_nomination.terminated": 0.75,
            },
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(l)",
    }

    # 6. artifact.form.mbi5 —— #38 改锚已落（换池批步 A1.4，2026-08-06）
    # §2.1.3(s) 的 MBI5 锚在「监督 RI ≠ 检验 RI」（role split，cf. §6.4.3/6.4.4）：
    # 正确依赖＝`procedure.repair_supervising_ri.appointment.completed`（槽 4 事件，
    # 换池批步 A1.3 补实采，order 25.5）。旧锚 admin-churn 三项
    # （ri_role.terminated 0.90 / temp_ri_nomination.completed 0.40 / .terminated 0.75
    # ＋ H.admin_instability_score 0.35）系语义错挂，已删——churn 对「另聘监督 RI」的
    # 影响改经槽 4 事件中介（见 build_pool_v2_supply_slot_specs 槽 4 公式）。
    # DAG 重排：sampling_order 6 → 25.7（> 槽 4 的 25.5；< 唯一下游
    # qual.artifact_field_group 的 45——构造期 DAG 硬闸看住这条边）。
    # ⚠️ 本公式分布未经授权门：档位随 45/45 stale 徽章走 MC 重跑＋分布授权门重估
    # （`换池批总工单_v1_20260806.md` A1.6/D1-D3），distribution_source 由 overlay
    # 标 PLACEHOLDER（POOL_V2_REWIRED_OVERLAY_SLOTS）。
    out["artifact.form.mbi5"] = {
        "sampling_order": SAMPLING_ORDER_ROUND7["artifact.form.mbi5"],
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair_supervising_ri.appointment.completed",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.form.mbi5"],
            sidecar_terms={
                # 表单强跟随事件（事件→其法定文书，同表 mbi4/report.completion 形）。
                "procedure.repair_supervising_ri.appointment.completed": 0.90,
            },
            hidden_terms={},
            sidecar_anchors={**A, **POOL_V2_SUPPLY_ANCHORS},
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(s) + §6.4.3-§6.4.4 + Appendix 10",
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
    # #37：楼级槽。H.defect_uncertainty / H.admin_discipline_score 无楼级对应量
    # ⇒ 删；H.defect_severity_score 走楼级恒等映射（building_total_severity_max）⇒ 保留。
    # 两个 sidecar 项（碎片级）经丙路 conditional_inputs 同步后按声明聚合真实解析。
    out["procedure.investigation.intention_notified"] = {
        "sampling_order": 14,
        "upstream_inputs": {
            "sidecar": [
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
            ],
            "hidden": ["H.defect_severity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.intention_notified"],
            sidecar_terms={
                "procedure.inspection.prescribed.completed": 0.45,
                "artifact.report.inspection": 0.40,
            },
            hidden_terms={"H.defect_severity_score": 0.55},
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
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.investigation.proposal.submitted"] = {
        "sampling_order": 16,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.intention_notified",
                "artifact.notice.investigation_intention",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.proposal.submitted"],
            sidecar_terms={
                "procedure.investigation.intention_notified": 1.00,
                "artifact.notice.investigation_intention": 0.55,
            },
            hidden_terms={},
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
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.investigation.proposal.recognized"] = {
        "sampling_order": 18,
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.proposal.submitted",
                "artifact.proposal.detailed_investigation",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.investigation.proposal.recognized"],
            sidecar_terms={
                "procedure.investigation.proposal.submitted": 0.90,
                "artifact.proposal.detailed_investigation": 0.65,
            },
            hidden_terms={},
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
    # #37：楼级槽（Δ 最大者 −0.1525）。H.repair_need / H.repair_complexity_score
    # 无楼级对应量 ⇒ 删；H.defect_severity_score 走楼级恒等映射 ⇒ 保留。
    out["procedure.supervision_representative.planned"] = {
        "sampling_order": 20,
        "upstream_inputs": {
            "sidecar": [
                "procedure.ri.appointment.completed",
                "procedure.inspection.prescribed.completed",
                "artifact.report.inspection",
            ],
            "hidden": ["H.defect_severity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_representative.planned"],
            sidecar_terms={
                "procedure.ri.appointment.completed": 0.25,
                "procedure.inspection.prescribed.completed": 0.45,
                "artifact.report.inspection": 0.30,
            },
            hidden_terms={"H.defect_severity_score": 0.35},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(m), §6.4.2-§6.4.3, Appendix 6",
    }

    # 21. procedure.supervision_team.submitted
    # #37：楼级槽，三个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.supervision_team.submitted"] = {
        "sampling_order": 21,
        "upstream_inputs": {
            "sidecar": [
                "procedure.supervision_representative.planned",
                "procedure.ri.appointment.completed",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_team.submitted"],
            sidecar_terms={
                "procedure.supervision_representative.planned": 0.95,
                "procedure.ri.appointment.completed": 0.25,
            },
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §6.4.3-§6.4.4 + Appendix 6 Attachment A",
    }

    # 22. procedure.supervision_team.changed
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.supervision_team.changed"] = {
        "sampling_order": 22,
        "upstream_inputs": {
            "sidecar": ["procedure.supervision_team.submitted"],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.supervision_team.changed"],
            sidecar_terms={"procedure.supervision_team.submitted": 0.55},
            hidden_terms={},
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
    # #37：楼级槽，两个 H 项均无楼级对应量 ⇒ 全删（乙形）。
    out["procedure.rc.pre_notification_given"] = {
        "sampling_order": 24,
        "upstream_inputs": {
            "sidecar": ["artifact.proposal.repair", "procedure.supervision_team.submitted"],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.rc.pre_notification_given"],
            sidecar_terms={
                "artifact.proposal.repair": 0.70,
                "procedure.supervision_team.submitted": 0.45,
            },
            hidden_terms={},
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

    # 33. artifact.record.nonconformity_sp2 —— #38 槽 2 主案改随（换池批步 A1.3）
    # 附錄六第 6 段的真前件是「发现不一致事项」这一事件；记录只是其法定文书。
    # 池 v2 起因果结构显式化：记录 ~ f(发现)——原三个 H.* 驱动
    # （nonconformity_risk 0.90 / defect_severity 0.35 / repair_complexity 0.30）
    # 整体移入发现事件槽 `supervision.nonconformity.found`（order 32.5，
    # build_pool_v2_supply_slot_specs），本记录经它中介；site_visit 保留
    # （记录成于监督到场过程）。原直连 test_witness 0.45 同样改经发现槽中介。
    # ⚠️ 分布未经授权门：distribution_source 由 overlay 标 PLACEHOLDER
    # （POOL_V2_REWIRED_OVERLAY_SLOTS），MC 重跑＋授权门重估后换实值。
    out["artifact.record.nonconformity_sp2"] = {
        "sampling_order": 33,
        "upstream_inputs": {
            "sidecar": [
                "supervision.nonconformity.found",
                "supervision.site_visit.performed",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["artifact.record.nonconformity_sp2"],
            sidecar_terms={
                # 记录强跟随发现事件（事件→其法定文书，同表 mbi4/report.completion 形）
                "supervision.nonconformity.found": 0.90,
                "supervision.site_visit.performed": 0.40,
            },
            hidden_terms={},
            sidecar_anchors={**A, **POOL_V2_SUPPLY_ANCHORS},
        ),
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 6 + Attachment B/C",
    }

    # 34. procedure.repair.revision_required
    # #37：楼级槽。H.repair_complexity_score / H.admin_instability_score 无楼级
    # 对应量 ⇒ 删；H.defect_severity_score 走楼级恒等映射 ⇒ 保留。
    # 两个 nonconformity/witness 项（碎片级）经丙路同步后按 any_true 聚合解析。
    out["procedure.repair.revision_required"] = {
        "sampling_order": 34,
        "upstream_inputs": {
            "sidecar": [
                "artifact.proposal.repair",
                "artifact.record.nonconformity_sp2",
                "artifact.record.test_or_material_witness",
            ],
            "hidden": ["H.defect_severity_score"],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.repair.revision_required"],
            sidecar_terms={
                "artifact.proposal.repair": 0.45,
                "artifact.record.nonconformity_sp2": 0.75,
                "artifact.record.test_or_material_witness": 0.30,
            },
            hidden_terms={"H.defect_severity_score": 0.35},
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
    # #37：楼级槽，唯一 H 项无楼级对应量 ⇒ 删（乙形）。三个 supervision 项
    # （碎片级）经丙路同步后按声明聚合（all_true×2 / any_true）真实解析。
    out["procedure.completed_work.final_inspection_performed"] = {
        "sampling_order": 37,
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.completed",
                "supervision.site_visit.performed",
                "supervision.record.completed",
                "supervision.record.retained",
            ],
            "hidden": [],
        },
        "conditional_formula": _bool_formula(
            anchor=A["procedure.completed_work.final_inspection_performed"],
            sidecar_terms={
                "procedure.repair.prescribed.completed": 1.00,
                "supervision.site_visit.performed": 0.30,
                "supervision.record.completed": 0.35,
                "supervision.record.retained": 0.30,
            },
            hidden_terms={},
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


# ===================================================================== #
# 死声明补公式（2026-08-05，`决议_33处置_20260805.md` §一.1 的「零边际成本段」）
# ===================================================================== #
#
# 案情：运行时（**Round6/7 overlay 之后**，别读源码字面）`sidecar_bool_slot_registry`
# 52 条里有 **3 条**「声明了 `conditional_inputs` 却没有 `conditional_formula`」
# ——声明了不执行，等于没声明，实际是独立伯努利。三条是：
#   ① actor.representative.assigned_role      (enum, order 20.5, fragment)
#   ② procedure.investigation.detailed.intended (bool, order 46, **building**)
#   ③ procedure.investigation.detailed.completed(bool, order 47, fragment)
# 其中 ② 正是乙路（#30）§2.1.3(n) 要接的那个前件槽——照现状落等于把一个
# 「与自己声明的三个上游零耦合」的槽接成规范前件。
#
# 🔴🔴 **落公式前实测发现的承重约束（比「补上公式」这件事本身更重要）**：
# `conditional_eval._eval_centered_linear:239` 对**缺失的 input 默认取 0.0**，
# **不抛异常、不走 fallback**。⇒ 公式里写一个求值上下文里根本不存在的键，
# 结果**不是**「回退边际」，而是**静默按 0.0 参与中心化**——得到一个偏移过的
# 常数概率。**那比死声明更糟**：死声明至少诚实地等于边际，错键公式看起来在
# 条件化、实际在按一个错误常数采样，且没有任何报警。
#
# 逐槽实测哪些上游**真的**解析得到（见 `test_precondition_coupling_formulas.py`
# 的结构闸，那条闸把这件事从「要记得」变成「机器保证」）：
#
# | 槽 | 粒度 | 求值上下文 | 声明上游可用性 |
# |---|---|---|---|
# | ① | fragment | 完整 fragment ctx（物理 + H.* + sidecar 上游） | `procedure.supervision_representative.planned` **可用**（order 20 楼级槽，广播到碎片） |
# | ② | **building** | **只有 3 个键** ＋ 可解析的 sidecar 上游 | 三个声明上游**一个都不可用**：`defect.cause_or_extent.uncertain` / `defect.class.present` 只在 fragment ctx 里（且键名不同），`risk.building_safety.emergency` **整个求值上下文里根本不存在** |
# | ③ | fragment | 完整 fragment ctx | `procedure.investigation.started`(19) / `procedure.investigation.proposal.recognized`(18) **可用**；`defect.cause_or_extent.uncertain` 的真实键是隐状态 `H.defect_uncertainty` |
#
# ⇒ **② 的三个声明上游全部换掉**，换成楼级真实可得的量；①③ 保留语义、
# 把键名换成求值器认得的真名。`conditional_inputs` 同批改成**真名**，
# 让「声明」与「执行」一致——留着对不上的旧名字，就是把这个坑埋回去。
#
# **参数档位**：全部工程估计档（`PRECONDITION_COUPLING_DISTRIBUTION_SOURCE`），
# **不是** Round 7 那种过了 10,000 样本 MC 对齐闸的档。系数取保守值
# （明显小于耦合正例 `artifact.notice.investigation_intention` 的 1.35），
# 目的是**建立方向正确的耦合**而不是精确标定强度；边际漂移由
# `test_precondition_coupling_formulas.py` 的 MC 实测断言看住。
# DAG 合法性：每个 sidecar 上游的 sampling_order 均严格小于本槽（20<20.5、
# 14/18<46、18/19<47），已实测核过。

PRECONDITION_COUPLING_DISTRIBUTION_SOURCE = (
    "proagent_engineering_estimate_precondition_coupling_20260805"
)


def build_precondition_coupling_formulas() -> Dict[str, Dict[str, Any]]:
    """3 个死声明槽的条件公式（工程估计档）。

    返回 {slot_id: {conditional_formula, conditional_inputs, upstream_inputs,
                    anchor_source}}——**刻意不带 `sampling_order` / `prevalence`**：
    这批不进 Round6/7 overlay，绝不改动既有采样序与边际锚
    （改序会挪动 DAG 拓扑，代价远大于本段要解决的问题）。
    """
    A = MARGINAL_ANCHORS_ROUND7
    out: Dict[str, Dict[str, Any]] = {}

    # ① actor.representative.assigned_role（enum 三档：none / lvl1 / lvl2）
    # 语义：监督代表**已规划**时才谈得上指派层级；未规划时既有
    # `_apply_clamps` 已单向钳制成 none，本公式补的是**规划为真时层级如何分布**
    # ——钳制只压住了「不该有的」，没有让「该有的」跟着上游动。
    _role_anchor = {"none": 0.45, "ri_rep_lvl1": 0.385, "ri_rep_lvl2": 0.165}
    out["actor.representative.assigned_role"] = {
        "conditional_inputs": ["procedure.supervision_representative.planned"],
        "upstream_inputs": {
            "sidecar": ["procedure.supervision_representative.planned"],
            "hidden": [],
        },
        "anchor_source": (
            "MBIS_CoP_2023 §2.1.3(m), §6.4.2-§6.4.3 modality=may_plus_shall_if_appointed"
            " | engineering_estimate_EXP011_20260702_low_confidence"
        ),
        "conditional_formula": {
            "type": "centered_softmax_per_class",
            "classes": {
                # 规划为真 ⇒ none 下降、两个层级上升（方向由守则语义定，
                # 强度取保守值）。
                "none": _enum_class(
                    anchor=_role_anchor["none"],
                    sidecar_terms={"procedure.supervision_representative.planned": -0.90},
                    hidden_terms={}, sidecar_anchors=A,
                ),
                "ri_rep_lvl1": _enum_class(
                    anchor=_role_anchor["ri_rep_lvl1"],
                    sidecar_terms={"procedure.supervision_representative.planned": 0.55},
                    hidden_terms={}, sidecar_anchors=A,
                ),
                "ri_rep_lvl2": _enum_class(
                    anchor=_role_anchor["ri_rep_lvl2"],
                    sidecar_terms={"procedure.supervision_representative.planned": 0.35},
                    hidden_terms={}, sidecar_anchors=A,
                ),
            },
        },
    }

    # ② procedure.investigation.detailed.intended（**楼级**，order 46）
    #
    # 🔴 两道约束同时收窄，最后只剩两个合法上游：
    #
    # **约束一（可得性，实测）**：三个声明上游全部在楼级取不到——
    # `defect.cause_or_extent.uncertain` / `defect.class.present` 只在 fragment
    # 上下文里（且真名不同），`risk.building_safety.emergency` **整个求值上下文里
    # 根本不存在**。
    #
    # **约束二（语义，既有裁定，比可得性更硬）**：
    # `test_precondition_supplement_slots.py::test_intended_does_not_depend_on_its_own_fulfilment`
    # 明令 `.intended` **不得**把 `procedure.investigation.intention_notified` 当上游——
    # §2.1.3(n) 的义务本体就是「以書面通知…其**有意**進行詳細調查」，
    # notified 是本义务的**履行**，拿履行当前提＝**用结论当前提**。
    # ⚠️ 该裁定同样排除 `procedure.investigation.proposal.submitted`(16) /
    # `.recognized`(18)：它们在因果链上比 notified **更靠后**（打算 → 通知 →
    # 呈交建議書 → 獲認可），拿它们当「打算」的前提是同一个错误、只是更深一层。
    # （首版我用了 notified + recognized，被上述常驻测试当场拦下——
    # 这条注释就是那次拦截的落点，别再往回改。）
    #
    # ⇒ 合法且可得的只剩「**因果先于「打算」**且楼级取得到」的两个：
    #   · `procedure.inspection.prescribed.completed`(order 8，在 BRA 内 ⇒ 楼级可聚合)
    #     ——訂明檢驗做完才谈得上「要不要再做詳細調查」，是真前驱；
    #   · `building_total_severity_max`——楼级上下文实有的键，是被换掉的
    #     `defect.*` / `risk.*` 三个声明上游在**楼级**唯一诚实的替代量
    #     （缺陷越重越可能打算做詳細調查）。
    # 刻意**不用** `building_defect_count`：它在楼级上下文里是**未归一化的原始计数**
    # （0-20+），塞进中心化线性项会让系数的量纲含义失控。
    out["procedure.investigation.detailed.intended"] = {
        "conditional_inputs": [
            "procedure.inspection.prescribed.completed",
            "building_total_severity_max",
        ],
        "upstream_inputs": {
            "sidecar": ["procedure.inspection.prescribed.completed"],
            "building_context": ["building_total_severity_max"],
        },
        "anchor_source": (
            "MBIS_CoP_2023 §4.1 + §4.3 modality=shall_if_intends"
            " | engineering_estimate_precondition_gap_20260731"
        ),
        "conditional_formula": {
            "type": "centered_sigmoid_linear",
            "anchor": 0.32,
            "upstream_expected": {
                "procedure.inspection.prescribed.completed":
                    float(A["procedure.inspection.prescribed.completed"]),
                # 楼级最大缺陷严重度的先验均值。⚠️ 这是**工程估计**，不是实测
                # 分布的矩——取 0.45 与 `H.defect_severity_score` 的先验一致，
                # 保持同一量纲上的可比性。
                "building_total_severity_max": 0.45,
            },
            "terms": {
                "procedure.inspection.prescribed.completed": 0.85,
                "building_total_severity_max": 0.90,
            },
        },
    }

    # ③ procedure.investigation.detailed.completed（fragment，order 47）
    # 语义：詳細調查**已完成**必然在「已开始」之后；建議書獲認可是其上游程序门；
    # 缺陷成因不确定度用真实键 `H.defect_uncertainty`（声明里写的
    # `defect.cause_or_extent.uncertain` 在求值上下文里不存在这个名字）。
    out["procedure.investigation.detailed.completed"] = {
        "conditional_inputs": [
            "procedure.investigation.started",
            "procedure.investigation.proposal.recognized",
            "H.defect_uncertainty",
        ],
        "upstream_inputs": {
            "sidecar": [
                "procedure.investigation.started",
                "procedure.investigation.proposal.recognized",
            ],
            "hidden": ["H.defect_uncertainty"],
        },
        "anchor_source": (
            "MBIS_CoP_2023 §4.3.3(a) modality=shall | "
            "engineering_estimate_precondition_gap_20260731_ratio_derived"
        ),
        "conditional_formula": _bool_formula(
            anchor=0.15,
            sidecar_terms={
                "procedure.investigation.started": 1.20,
                "procedure.investigation.proposal.recognized": 0.50,
            },
            hidden_terms={"H.defect_uncertainty": 0.45},
            sidecar_anchors=A,
        ),
    }
    return out


_PRECONDITION_CACHE: Dict[str, Dict[str, Any]] = {}


def get_precondition_coupling_formulas() -> Dict[str, Dict[str, Any]]:
    """单例 lookup（与 Round6/7 同款缓存纪律）."""
    global _PRECONDITION_CACHE
    if not _PRECONDITION_CACHE:
        _PRECONDITION_CACHE = build_precondition_coupling_formulas()
    return _PRECONDITION_CACHE


# ===================================================================== #
# 池 v2 供给侧三新槽的条件公式（#38，换池批步 A1.3；常量表见文件上部
# POOL_V2_SUPPLY_* 段，分布纪律同处声明——全部 PLACEHOLDER 待授权门）
# ===================================================================== #


def build_pool_v2_supply_slot_specs() -> Dict[str, Dict[str, Any]]:
    """#38 三新槽的公式 spec（结构落码；参数占位待 A1.6 分布授权门）。

    返回 {slot_id: {conditional_formula, conditional_inputs, upstream_inputs,
                    anchor_source, cop_section}}——与死声明补公式同款形状；
    `sampling_order` / `prevalence` / `granularity` 由 registry 记录本体持有
    （overlay 不动采样序，46/47 号槽先例）。

    可得性纪律（#37 病灶的机器教训，逐槽核过）：
    - 槽 2（fragment）：完整 fragment ctx——site_visit(26)/test_witness(31) 上游
      广播可得，H.* 三项 fragment 派生可得；
    - 槽 3（building）：唯一上游 revision_required(34) 是楼级槽，楼级缓存可得；
    - 槽 4（building，order 25.5）：prescribed.started(25) 是 fragment 槽但
      BUILDING_READING_AGGREGATION 已声明 any_true；ri_role.terminated(5) /
      temp_ri_nomination.terminated(4) 是楼级槽。🔴 刻意**不用**
      H.admin_instability_score——楼级求值上下文没有它，写进去就是 #37 那病
      （缺键静默按 0.0 中心化）。
    """
    A = {**MARGINAL_ANCHORS_ROUND7, **POOL_V2_SUPPLY_ANCHORS}
    P = POOL_V2_SUPPLY_ANCHORS
    out: Dict[str, Dict[str, Any]] = {}

    # 槽 2 主案：发现不一致事项（附錄六第 6 段真前件；命名按工单 A1.3 例名落定）。
    # 条件依赖＝近名真槽 sp2 的**现行活依赖全集**（`技术与研究债.md:10292-10297`
    # 「引依赖以 registry 实取为准」——实取即 overlay 后的公式 term 集：
    # site_visit + test_witness + H.* 三项；决议引的四项里 `verification.test.failed`
    # 与 `defect.class.present` 不在求值器 sidecar 白名单、`revision_required`(34)
    # 在本槽之后会成环，均不可表达，以实取集落码并留授权门复核）。
    out["supervision.nonconformity.found"] = {
        "conditional_inputs": [
            "supervision.site_visit.performed",
            "artifact.record.test_or_material_witness",
            "H.nonconformity_risk",
            "H.defect_severity_score",
            "H.repair_complexity_score",
        ],
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
        "anchor_source": (
            "MBIS_CoP_2023 Appendix 6 para 6 modality=shall_if_nonconformity_found"
            " | pool_v2_supply_structural_estimate_20260806_pending_authorization"
        ),
        "conditional_formula": _bool_formula(
            anchor=P["supervision.nonconformity.found"],
            sidecar_terms={
                # 继承 sp2 原公式的驱动结构（记录的驱动本就是发现的驱动）
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
        "cop_section": "MBIS_CoP_2023 Appendix 6 para 6 + Attachment C",
    }

    # 槽 3：修葺建議修訂已呈交建築事務監督（仅乙#11 期限锚 carrier，
    # **不登记 trigger 角色**——工单 A1.3③）。呈交 ⊂ 修訂被要求：
    # 流行率取 revision_required 子集（glm 起点，`技术与研究债.md:10324-10325`）。
    out["procedure.repair.revision_proposal.submitted_to_ba"] = {
        "conditional_inputs": ["procedure.repair.revision_required"],
        "upstream_inputs": {
            "sidecar": ["procedure.repair.revision_required"],
            "hidden": [],
        },
        "anchor_source": (
            "MBIS_CoP_2023 §2.1.3(p)-(q) modality=shall_if_revision_required"
            " | pool_v2_supply_structural_estimate_20260806_pending_authorization"
        ),
        "conditional_formula": _bool_formula(
            anchor=P["procedure.repair.revision_proposal.submitted_to_ba"],
            sidecar_terms={"procedure.repair.revision_required": 0.90},
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(p)-(q)",
    }

    # 槽 4：另聘监督 RI 委任完成（§2.1.3(s)/§6.4.3——监督 RI ≠ 检验 RI 情形）。
    # 「防同一 RI 情形误生成」（glm 约束）：本世界不建模 RI 身份，槽本身就是
    # 「另一名」情形的标记；同/异 RI 的世界内判别量只有行政更替事件
    # （ri_role.terminated / temp_ri_nomination.terminated）——正耦合只挂它们
    # ＋修葺已开工（委任发生于修葺监督语境），anchor 取稀有档 0.075，
    # 保证非更替、非修葺楼几乎不出真值。
    out["procedure.repair_supervising_ri.appointment.completed"] = {
        "conditional_inputs": [
            "procedure.repair.prescribed.started",
            "procedure.ri_role.terminated",
            "procedure.temp_ri_nomination.terminated",
        ],
        "upstream_inputs": {
            "sidecar": [
                "procedure.repair.prescribed.started",
                "procedure.ri_role.terminated",
                "procedure.temp_ri_nomination.terminated",
            ],
            "hidden": [],
        },
        "anchor_source": (
            "MBIS_CoP_2023 §2.1.3(s) + §6.4.3-§6.4.4 modality=shall_if_another_ri"
            " | pool_v2_supply_structural_estimate_20260806_pending_authorization"
        ),
        "conditional_formula": _bool_formula(
            anchor=P["procedure.repair_supervising_ri.appointment.completed"],
            sidecar_terms={
                "procedure.repair.prescribed.started": 0.60,
                "procedure.ri_role.terminated": 0.90,
                "procedure.temp_ri_nomination.terminated": 0.40,
            },
            hidden_terms={},
            sidecar_anchors=A,
        ),
        "cop_section": "MBIS_CoP_2023 §2.1.3(s) + §6.4.3-§6.4.4",
    }
    return out


_POOL_V2_SUPPLY_CACHE: Dict[str, Dict[str, Any]] = {}


def get_pool_v2_supply_slot_specs() -> Dict[str, Dict[str, Any]]:
    """单例 lookup（与 Round6/7 同款缓存纪律）."""
    global _POOL_V2_SUPPLY_CACHE
    if not _POOL_V2_SUPPLY_CACHE:
        _POOL_V2_SUPPLY_CACHE = build_pool_v2_supply_slot_specs()
    return _POOL_V2_SUPPLY_CACHE
