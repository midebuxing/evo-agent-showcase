# -*- coding: utf-8 -*-
"""S1 绑定合同权威结构表（DEBT-083 第 10 步，codex 逐行批准 2026-08-02）。

**一张权威表、多份派生视图**（裁决原文形状）：
- 每行八要素合同的机器面：精确绑定 (rule_card_id, slot_ref_id)、限定符轴、
  聚合子、允许路径、政策（diagnostic_only / value_consumption）、
  **卡内容指纹**（机器护栏）。人读面（完整性前提/真假处置/中文正文依据）在
  `团队文档/我的笔记/DEBT083_S1绑定合同草案_20260802.md` 与裁决记录。
- 现表 **125 行＝诊断型授权 102＋值消费合同 23**（沿革：首批 1-36 诊断型＋
  行 37 A′值消费 §2.1.3(a)；A 批 65 行 2026-08-03 落表；残余 50 止血 +2 行
  2026-08-04 落表；c55 消费行 105-126 共 22 行 2026-08-04 落表；
  **件四批 1 退役 row 21** 2026-08-04——§3.2.6 重复建卡二保一，其卡被退役，
  该行的绑定对象已不存在，留着就是一条不会报警的死行）。
  🔴 **row 号有意不重排**（21 为空号）：`test_granularity_declaration` 把 c55
  声明行冻在 `range(105,127)`，重排会连带炸掉整批断言。
  诊断型只许选中合同指定的楼级聚合读数并经产物态许可闸
  落 `open/artifact_state_not_valid_evidence`，结构上不产 satisfied/violated。
- 丁组（原稿 38-43）仍未录入——待 S3 落地后重送决策门。

🔴 机器护栏（导入时执行）：逐行卡指纹与磁盘卡包实算指纹比对，**失配即该行
自动失效**（裁决：「若卡指纹…发生变化，本授权自动失效，须重新过决策门」）；
卡包不可读 ⇒ 全表失效（fail-closed），原因记 `DISABLED_REASON`。
扩表/改行必须重过决策门并重跑四门验收。

## 粒度声明字段 `granularity_declaration`（DEBT-085 件二**第一步·声明期**）

决策门 Q1 裁定载体＝**(b) 精确绑定表行字段**（(a) 全卡改 schema 重锚过重；
(c) 旁路撞 DEBT-072 红线「凡进判定必须走本体」）。可选字段，受控枚举
`{"building","fragment"}`，**键缺省＝未声明**。

- **声明期语义＝只登记不消费**：本字段今天**零运行时读者**（判定粒度仍由
  `validator._card_is_fragment_scoped` 的隐式判据决定，逐位不变）。
  Q2 裁定的两段式：第一步声明期未声明维持现状，**冻结点后才 fail-closed
  （未声明即拒判）**——那是第二步，不在本单。
- **同卡同质闸**（Q1 裁定「一卡内全部行声明同粒度，注册时机器校验、冲突
  拒载」）：见 `granularity_declaration_violations`，冲突 ⇒ 整表 fail-closed。
- 本次声明 22 行（c55 值消费 row 105-126，全填 `building`）；
  **row 37 不填**——它落在 `量测_DEBT085x27联合_20260804.md` §二的
  18 键共同待裁清单里（形状 B：卡楼级作用域但绑定含片段载体），
  详该行行内注释。
"""
from __future__ import annotations

import pathlib
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

NEGATIVE_AUTHORIZATION_CLAUSE = (
    "本授权仅允许按精确 (rule_card_id, slot_ref_id, allowed_path) 选择合同"
    "指定的楼级聚合读数，并据产物态许可闸给出 open/artifact_state_not_valid_"
    "evidence。本授权不授予该事实对 action、evidence、report_field 等不许可 "
    "kind 产生 satisfied 或 violated 的权力。报告存在不等于合同所述字段、"
    "动作或内容已经履行。若卡指纹、槽位、限定符、角色、允许路径、聚合来源、"
    "产物态许可集合或 evidence_kind 发生变化，本授权自动失效，须重新过决策门。"
)

BINDING_CONTRACTS: Tuple[Dict[str, Any], ...] = tuple(
[
    {
        "row": 1,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_1_b_test_results_or_coc_in_completion_report.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_1_b_test_results_or_coc_in_completion_report.c01.sr01",
        "qualifier_axis": "artifact_key=report.completion",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "93b70879bbd1c1051c7da741dbd04ee0a7d995c2b8f37973cc22aeba0baf4da1",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 2,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_2_concrete_cube_reports_in_completion_report.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_2_concrete_cube_reports_in_completion_report.c01.sr01",
        "qualifier_axis": "artifact_key=report.completion",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "4b871fd0981329f08142d2ab344020c4284075ccc7de25115ac49d5f955db455",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 3,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_2_mill_certificates_in_completion_report.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.sapp5_s1_2_mill_certificates_in_completion_report.c01.sr01",
        "qualifier_axis": "artifact_key=report.completion",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "fb75b3138d4133b2a1a5ebcca37f5eb770120fd4ae7b293ffdd7074c51dd285e",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 4,
        "rule_card_id": "rc.mbis.inspection.ubw_and_related_scope.ri.coverage.s3_7_1_c_look_for_signs_of_suspected_subdivision_of_flats.c01",
        "slot_ref_id": "rc.mbis.inspection.ubw_and_related_scope.ri.coverage.s3_7_1_c_look_for_signs_of_suspected_subdivision_of_flats.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "d9a26c6ef2e723d0fde3515c2c48b71c2305c8aaf98c17621be3c2c8723ebfbd",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 5,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_identify_unusual_construction_and_attention_items.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_identify_unusual_construction_and_attention_items.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "350b975062d4e83ae32b1ae164ced4c9f22dc79a6f37e47b75f78a3c3cf7e8a5",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 6,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_minor_works_plans_and_details.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_minor_works_plans_and_details.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "2cc8f6d831a0b0ee1e0eac773519463f369d1cbf33b5ce3a0c393e0f6dd1ca9f",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 7,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_s39c_plans_and_documents.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_s39c_plans_and_documents.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "cf3afeb4e24f725fb9f5405d233b45c65e1cd178847648fec8cc6a113da28ec1",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 8,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_understand_overall_building_design_and_construction.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_1_understand_overall_building_design_and_construction.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "0413bbed963b4d5dec88896a2beadb1c307c035729a806fc21f02cc01192e71c",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 9,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_2_fire_safety_upgrade_standard_after_fs_ordinances.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_2_fire_safety_upgrade_standard_after_fs_ordinances.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "2e9f7088467c6b4abb075a36d64175d665aa5af6d2da43045fbb8b6a292d709e",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 10,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_3_op_date_if_no_approved_plans.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_3_op_date_if_no_approved_plans.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "7f6fc630da333d94b517856d90590d0aa58c4d1c8e61f83f3c1d2999a7cabe60",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 11,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_a_occupation_permit_issue_date.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_a_occupation_permit_issue_date.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "a8f5e4a521767f9d45862ff710bc807e52d1bf7b3f4608abb9b0c7a04e282369",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 12,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_b_building_use.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_b_building_use.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "cf2c9104faa070a4acfb1dbf14d877e3446aec07496de18f0b8980ef7d90e6fe",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 13,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_c_approved_plans.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_c_approved_plans.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "f7d56bc1e59214efb068071087617fb1c4c648eda17f42be0dfe3e7eea9c9910",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 14,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_d_minor_works_plans_and_details.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_d_minor_works_plans_and_details.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "798bf60aa63020bef1032a8655852ec05e5aa8458493ad61e39af2b58144c29c",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 15,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_e_s39c_plans_and_documents.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_e_s39c_plans_and_documents.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "2ac6e5c4a1bd7f1ef76433c462903017b5556f5033faa89ee13427432f5b82ca",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 16,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_f_fire_safety_direction_status.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_f_fire_safety_direction_status.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "984ffafeed3f36585b4567ca90022aa27ef255e9d16c0531047e55fc42873791",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 17,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_f_fire_safety_ordinance_applicability.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_f_fire_safety_ordinance_applicability.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "72533d0c08386a6530b70dba8aa9841d1e1418d78b93d1217860f5a646a1683a",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 18,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_g_outstanding_statutory_investigation_orders.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_g_outstanding_statutory_investigation_orders.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "56611f969773810605379f669ef2891f06e8e0d708347945edcb4032cf07c6ea",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 19,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.sapp2_g_outstanding_statutory_repair_orders.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.sapp2_g_outstanding_statutory_repair_orders.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "6cd7085dd96b7536617fd0e0068a13f96f8c98b3e029dde36df1209ed5d5214b",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 20,
        "rule_card_id": "rc.mbis.preinspection.background.ri.review.s3_2_6.c01",
        "slot_ref_id": "rc.mbis.preinspection.background.ri.review.s3_2_6.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "0bbfd82e03c634b4bb0586f550873542759d43d64b863d96e53af88e91a200d8",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 22,
        "rule_card_id": "rc.mbis.inspection.drainage.ri.follow_up.s3_6_3_a_assess_hazard_sanitation_and_illegal_alterations.c01",
        "slot_ref_id": "rc.mbis.inspection.drainage.ri.follow_up.s3_6_3_a_assess_hazard_sanitation_and_illegal_alterations.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "09633f157080a8268dc334d65c041eee7983fa6e09b49f02654324bcb33853ce",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 23,
        "rule_card_id": "rc.mbis.inspection.drainage.ri.follow_up.s3_6_3_e_recommend_drainage_rectification_in_report.c01",
        "slot_ref_id": "rc.mbis.inspection.drainage.ri.follow_up.s3_6_3_e_recommend_drainage_rectification_in_report.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "152906f1b13fa639a760b35996eae26daaaa5b8b28521744e696fad5850385b4",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 24,
        "rule_card_id": "rc.mbis.inspection.fire_safety_components.ri.follow_up.s3_5_3_a_recommend_fire_safety_follow_up_and_repair_in_report.c01",
        "slot_ref_id": "rc.mbis.inspection.fire_safety_components.ri.follow_up.s3_5_3_a_recommend_fire_safety_follow_up_and_repair_in_report.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "c991efe07fa5443e1c65afde18ea19a1938c6bf83103c6e049c25eb051af4800",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 25,
        "rule_card_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_1_2_formulate_repair_proposals_for_all_defects.c01",
        "slot_ref_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_1_2_formulate_repair_proposals_for_all_defects.c01.sr02",
        "qualifier_axis": "artifact_key=proposal.repair",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "9c0c794db0c046ad40410387c88ba5cfd1ea9fc0cc17c8b26579db55581aaf24",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 26,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s1_cover_page.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s1_cover_page.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "a25de90ea0d51c31a4009dac3883c5450ff7d5a2ec63ba720b9c1abe16949ebb",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 27,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s3_building_information.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s3_building_information.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "e593adb73e98176299ea2d739b76a0806e82830d397c65e2cc3f631f0c944057",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 28,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s4_reference_documents.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s4_reference_documents.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "668c3130c3f89780a4fb30084e5471317960a05c427355c6d776fd5ac43b8e91",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 29,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s5_inspection_method_statement.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s5_inspection_method_statement.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "2ee5c2fc259468b8051d868ac3047e4568639654dd51dc731d7a9d374cfdd8a0",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 30,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s6_inspection_results.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s6_inspection_results.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "545ff44112848e58c23b5c13f06ddaf6794f32bfdc920247f9d26ab757d12e95",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 31,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s7_assessment.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s7_assessment.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "b298794120ccda3e3658c0c762cbeef379d56263bb08ea9ddd5d405766d3fdff",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 32,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s8_repair_proposal.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s8_repair_proposal.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "1ddf21d84a64c83989b369cafe896203761165123f4f1d9708b8430ff0e674ee",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 33,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.s7_2_6_mbis_repair_separation.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.s7_2_6_mbis_repair_separation.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "11d6644368cc37b44bec1ea7a6850696b762357b8950a74d679fc98e0ee8e9e0",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 34,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s6_outstanding_order_scope.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_s6_outstanding_order_scope.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "any_true",
        "allowed_paths": [
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "0f49ef71118569945ac96523facfbb3a10e7556e1cff5a85f396cf87828ee850",
        "slot_id": "reporting.artifact.prepared",
        "aggregation_source": "slot_target_fallback",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 35,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.proposal.s4_2_2_d_defect_summary.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.proposal.s4_2_2_d_defect_summary.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "8d2b7a6c51e76517046d33833043edfe76c8317df85decc9d6a13ab868483f0c",
        "slot_id": "artifact.proposal.detailed_investigation",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 36,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.submit.s7_2_2_submit_report_with_mbi3_certificate.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.submit.s7_2_2_submit_report_with_mbi3_certificate.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": [
            "slot_role"
        ],
        "policy": "diagnostic_only",
        "card_content_sha256": "9c6b2d117e8a0f8a0f9c1c2b51cb399327effa1c7395622191989df20668fa42",
        "slot_id": "artifact.report.inspection",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none"
    },
    {
        "row": 37,
        "rule_card_id": "rc.mbis.inspection.personal_conduct.ri.duty.s2_1_3_a_personally_conduct_inspection.c01",
        "slot_ref_id": "rc.mbis.inspection.personal_conduct.ri.duty.s2_1_3_a_personally_conduct_inspection.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "all_true",
        "allowed_paths": [
            "node_slot",
            "slot_role"
        ],
        # 🔴 2026-08-05 #33 保护闸落表后，**本行是全表唯一的 `value_consumption` 行**
        # （c55 的 22 行 105-126 已翻成耦合未证拒判）。本行不在 #33 射程：槽是
        # `procedure.inspection.prescribed.completed`，不是 reporting 轴；且
        # `true_exit_mode="caller_path"`，契约本就不直判 satisfied。
        "policy": "value_consumption",  # ← #33 射程外，有意保留
        "card_content_sha256": "bc54086cbf1c45a33fb80be6cfe401e6fc95992558e56e0d14130644ec63da0a",
        "slot_id": "procedure.inspection.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "closed/satisfied（沿用现状路径）",
        "false_exit": "open/observed_false_without_violation_basis",
        "verdict_permission": "value_consumption_aprime",
        "true_exit_mode": "caller_path",
        # 🔴 DEBT-085 件二·声明期：**本行不填 `granularity_declaration`
        # ——DEBT085×27 共同待裁**。
        # 依据一（清单）：本行键 `…s2_1_3_a_personally_conduct_inspection.c01.sr01`
        #   逐字落在 `量测_DEBT085x27联合_20260804.md` §二 OFF 格 18 键清单内
        #   （机读 `量测_DEBT085x27联合_20260804_数据.json`：形状
        #   `B_card_building_but_slot_fragment_carried`、`A表精确覆盖=true`）。
        # 依据二（世界实测，2026-08-04 复算 30 栋 fact_pack）：本行槽
        #   `procedure.inspection.prescribed.completed` 共 236 条事实＝
        #   **片段载体 206（sidecar_entry）／楼级载体 30（building）**
        #   ⇒ 「读数全是楼级」对本行**不成立**，不属「已可无争议声明」。
        # 声明期缺省＝维持现状，故不填是 no-op；待 18 键与 #27 共同裁定后再落。
    },
    # ==================================================================== #
    # A 批（2026-08-03 落表，65 行）：78 个 (槽,action) 组合逐条对**中文法规原文**
    # 裁定后，判「不符」的 58 个组合展开出的精确绑定。
    #
    # 语义与行 1-37 不同：这批是「**已裁定：该类读数不能确立本义务**」
    # （永久禁止据其判定，除非改接能确立义务的证据通道后重新裁定），
    # 而不是「尚未获裁定授权」。故出口走「丁」第二码
    # `diagnostic_binding_not_valid_evidence`（非产物读数 49 行）；
    # 产物态 16 行仍走 `artifact_state_not_valid_evidence`。
    # 🔴 实际分流由 `diagnostic_refusal_reason_code()` 按**事实分类器**做，
    # 本表两个 exit 字段**只作声明与审计**，运行时会核对二者一致（丁③④⑤）。
    #
    # 走完四道门：决策门（grok+kimi「该不该收窄」）→ 仲裁（cursor gpt「用哪个码」
    # → 第四条路「丁」）→ 审核门（kimi「代码对不对」）→
    # 落表前置门（grok+kimi「这批数据在运行时长什么样」）。
    # 最后一道是落表当天新开的：前三道**没有一道**看运行时形状，
    # 而正是它挡下了两个会当场坏事的错（aggregation_source 填 None ⇒ 整表熄火；
    # 16 行原始 artifact.* 被误标回退表来源 ⇒ src_ok 必假）。
    # ==================================================================== #
    {
        "row": 38,
        "rule_card_id": "rc.mbis.inspection.external_defects.ri.follow_up.s3_3_3_b.c01",
        "slot_ref_id": "rc.mbis.inspection.external_defects.ri.follow_up.s3_3_3_b.c01.sr02",
        "qualifier_axis": "component_type_key=external_component,risk_class_key=building_safety_emergency",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "2336b8ecfacf43f29a99032d894a886ae52f38476d688091a9a02551060dff5f",
        "slot_id": "risk.building_safety.emergency",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 39,
        "rule_card_id": "rc.mbis.inspection.structural_components.ri.record.s3_4_2_a_b_submit_structural_inspection_log.c02",
        "slot_ref_id": "rc.mbis.inspection.structural_components.ri.record.s3_4_2_a_b_submit_structural_inspection_log.c02.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "5fe2606dc8ba61de8f573fdb6ce131f32bc4f0600f29d947476c134348237d0e",
        "slot_id": "artifact.record.inspection_log",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 40,
        "rule_card_id": "rc.mbis.inspection.structural_defects.ri.follow_up.s3_4_3_b.c01",
        "slot_ref_id": "rc.mbis.inspection.structural_defects.ri.follow_up.s3_4_3_b.c01.sr02",
        "qualifier_axis": "component_type_key=structural_component,risk_class_key=building_safety_emergency",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "4e1cd31d94a640be80ea270b2dcfbe23596a6f6940ff02b49565afaf7a14dc97",
        "slot_id": "risk.building_safety.emergency",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 41,
        "rule_card_id": "rc.mbis.inspection.ubw_and_related_scope.ri.identify.s3_7_2_c_identify_and_inspect_section_39c_validated_ubw_and_defects.c01",
        "slot_ref_id": "rc.mbis.inspection.ubw_and_related_scope.ri.identify.s3_7_2_c_identify_and_inspect_section_39c_validated_ubw_and_defects.c01.sr02",
        "qualifier_axis": "component_type_key=ubw",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "e21eedaf583a55db2225817429209230c8120db0bfbe303b55df1a4aed3c7bf6",
        "slot_id": "defect.class.present",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 42,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.follow_up.s4_3_4_urgent_remedial_works_below_load_effect.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.follow_up.s4_3_4_urgent_remedial_works_below_load_effect.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "8589353d4ff3c3f1e47b9418bc38097f0adb6ac93dc269975bdc4bf1eb852607",
        "slot_id": "procedure.repair.prescribed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 43,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_apply_findings_personally.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_apply_findings_personally.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "13890a5854e803b9d8abc7d33993317e7efc2edadf9bc275d92f8cef5c153d1a",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 44,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_engage_suitable_specialist.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_engage_suitable_specialist.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "b3d7020287b21ad14722fe0239e60ed61a083365b02c8b41ac4c056d0081cde9",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 45,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_seek_specialist_input.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_seek_specialist_input.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "d665c258ba6df73f31eb17bc8174cf5d49e0f66260de7ca789963ce91c7471c9",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 46,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_supervise_specialist.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_1_4_supervise_specialist.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "17b93585bedc0a59cdd4f49e561d4c1ef3115526343dcb4c5122bb66fb2a81ec",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 47,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_2_b_concrete_condition_methods.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_2_b_concrete_condition_methods.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "fac154fdb8d27b56e9e490f1c97f049915b988a6c85320140ab72c87afbcad03",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 48,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_2_c_reinforcement_condition_methods.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_2_c_reinforcement_condition_methods.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a999ab7f8fb0171ac9746f38995d09040a3d99be8e366a9c043b33f44a9392ee",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 49,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_a_assess_safety_level_and_follow_up.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_a_assess_safety_level_and_follow_up.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "601d587dac07e6e8bc1b6d27c00805874b662aaab15db809c2cd637029020927",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 50,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_b_use_prevailing_standards.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_b_use_prevailing_standards.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "17918aa7d2987b6b32ef77062d597e80282b294a4ead9f1d4d8c22f926d827af",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 51,
        "rule_card_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_c_determine_fsp.c01",
        "slot_ref_id": "rc.mbis.investigation.detailed_investigation.ri.gate.s4_3_3_c_determine_fsp.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "c0cbf1b3511476f32fabb92f431646b8c550fc870c7b58d844f53031e219223e",
        "slot_id": "procedure.investigation.detailed.started",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 52,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_2_a_repair_all_cladding_defects.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_2_a_repair_all_cladding_defects.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "15ebe39f3f512d7b36a0e3eeb62488409f9c99b239e757eb32e15f55e24b3b88",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 53,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_2_c_replacement_panels_noncombustible.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_2_c_replacement_panels_noncombustible.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "23c4cab1d315c1cdde6b98709d89bdf88d5dc2e010cdba299ac06b5695c0ed92",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 54,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_3_reinstalled_fins_durable.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_3_reinstalled_fins_durable.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "041151134002a300a12e7e8dcfe87f54f86c049dfc89fbdcfb74bcaabf66691d",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 55,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_3_repair_or_replace_defective_fins.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_3_repair_or_replace_defective_fins.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "488b0368c6a772378bc730ea0f1fce2224fe0e35ecd7a1dd563f481e1def850b",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 56,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_4_a_replace_defective_curtain_wall_parts.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_4_a_replace_defective_curtain_wall_parts.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "c411addd743bb221c4ca22864debf107173584877b9d22bd9d2df56a863f5611",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 57,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_5_b_replacement_appendage_fixing_adequate.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_5_b_replacement_appendage_fixing_adequate.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a2fe57f4a4a4c97e7b31837f4a435ed5b0e7f32e799bb7f5591471ca42b9b619",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 58,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_a_remove_replace_defective_false_ceiling.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_a_remove_replace_defective_false_ceiling.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "cd898a9afb6f58abc8bc5cc609212f8f0624ada93f646c1331ca461819acdc2d",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 59,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_b_replace_all_defective_balustrade_parts.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_b_replace_all_defective_balustrade_parts.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "e14b010670462b5509f0341b9ddaa3c2e33f6c32d6440670abd1d8bc684d8b69",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 60,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_c_replace_defective_metal_gate_parts.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.repair.s5_3_6_c_replace_defective_metal_gate_parts.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "5b2f8db478c0fcf067b964748c9dc5402aab75154b459673122149975d3a9449",
        "slot_id": "procedure.repair.prescribed.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 61,
        "rule_card_id": "rc.mbis.repair.external_finish.ri.submit.s5_3_4_b_submit_replacement_material_certificates.c01",
        "slot_ref_id": "rc.mbis.repair.external_finish.ri.submit.s5_3_4_b_submit_replacement_material_certificates.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a61b41d632981e7e1d3e5e57ca2fd65c76d9fff4cb6750499dfb3e504ccce34e",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 62,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.follow_up.sapp4_s2_3_failed_pull_off_further_tests.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.follow_up.sapp4_s2_3_failed_pull_off_further_tests.c01.sr02",
        "qualifier_axis": "component_type_key=wall_tiles,method_key=pull_test",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "ccc20c2dd0ec2274e84050d04850c3fbfac8949d106532fb8ba3600328ba9645",
        "slot_id": "verification.test.performed",
        "aggregation_source": "code_derived_reading",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 63,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.follow_up.sapp5_s1_1_f_failed_patch_pull_off_further_tests.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.follow_up.sapp5_s1_1_f_failed_patch_pull_off_further_tests.c01.sr02",
        "qualifier_axis": "component_type_key=structural_component,method_key=pull_test",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "b268a647c3186d15a80e0ed09fa060c1add70e429743479dab44b5ac464f9a71",
        "slot_id": "verification.test.performed",
        "aggregation_source": "code_derived_reading",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 64,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_1_ensure_rc_repair_meets_bo_standard.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_1_ensure_rc_repair_meets_bo_standard.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "9dcffa67a692cf20b135bc5b07486328d96f8b5a712ffb08f3a4f69c42731339",
        "slot_id": "artifact.record.test_or_material_witness",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 65,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_a_a_remove_rust_and_protect_steel.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_a_a_remove_rust_and_protect_steel.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "cf8331babe335fc2a4ce099487582ff0032d36a131826ddc29c69025f299cb82",
        "slot_id": "artifact.record.test_or_material_witness",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 66,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_a_b_consider_replace_severely_corroded_member.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_a_b_consider_replace_severely_corroded_member.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "54cc0a26c7e15eec4e2c5551645efe58582f3bffec9370c9a668db986d235e7a",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 67,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_b_replace_corroded_bolts_and_rivets.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_b_replace_corroded_bolts_and_rivets.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "e023b6407236b7b69a68374f33f090a959ff1da5baf2af737cbeca411d0dd380",
        "slot_id": "verification.test.performed",
        "aggregation_source": "code_derived_reading",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 68,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_b_replace_corroded_bolts_and_rivets.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_b_replace_corroded_bolts_and_rivets.c01.sr03",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "e023b6407236b7b69a68374f33f090a959ff1da5baf2af737cbeca411d0dd380",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 69,
        "rule_card_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_c_restore_damaged_fireproofing_on_steel.c01",
        "slot_ref_id": "rc.mbis.repair.external_structural_validation.ri.verify.s5_4_2_c_restore_damaged_fireproofing_on_steel.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "0a8cf6ae44cd19a1203accf567d1cdbc191ed6863dae7b306882bd658c02661d",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 70,
        "rule_card_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_3_7_note_maintenance_components_in_report.c01",
        "slot_ref_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_3_7_note_maintenance_components_in_report.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "842f6a7546e9d91017b0945c919ca58fdd19b06987be84820c0c25188cfb47c6",
        "slot_id": "artifact.report.inspection",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 71,
        "rule_card_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_4_4_note_steel_maintenance_items_in_report.c01",
        "slot_ref_id": "rc.mbis.repair.general_selection_and_classification.ri.select.s5_4_4_note_steel_maintenance_items_in_report.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "c8a8f250b17542835098d937cdc8f03e581e2a63b76df543913d70bad2738177",
        "slot_id": "artifact.report.inspection",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 72,
        "rule_card_id": "rc.mbis.repair.materials.ri.ensure.s2_1_3_d_materials_properly_applied.c01",
        "slot_ref_id": "rc.mbis.repair.materials.ri.ensure.s2_1_3_d_materials_properly_applied.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "09b623c3819a662bc8b0c0e93af7b466630ac1e323f8ceee7751a15e39aad17f",
        "slot_id": "artifact.record.test_or_material_witness",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 73,
        "rule_card_id": "rc.mbis.reporting.completion_report.ri.schema.s5_4_2_a_d_mill_certificates_in_completion_report.c01",
        "slot_ref_id": "rc.mbis.reporting.completion_report.ri.schema.s5_4_2_a_d_mill_certificates_in_completion_report.c01.sr02",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "1ff99f99753468e53b6978168e8bef036904094e90e3ead82a398c178a16f7f4",
        "slot_id": "artifact.report.completion",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 74,
        "rule_card_id": "rc.mbis.reporting.completion_report.ri.schema.s5_4_2_a_d_mill_certificates_in_completion_report.c01",
        "slot_ref_id": "rc.mbis.reporting.completion_report.ri.schema.s5_4_2_a_d_mill_certificates_in_completion_report.c01.sr03",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "1ff99f99753468e53b6978168e8bef036904094e90e3ead82a398c178a16f7f4",
        "slot_id": "artifact.certificate.material_or_product",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 75,
        "rule_card_id": "rc.mbis.reporting.completion_report.ri.schema.sapp8_3_record_voluntary_removal_of_ubw_with_annotated_photos_and_marked_up_plans.c01",
        "slot_ref_id": "rc.mbis.reporting.completion_report.ri.schema.sapp8_3_record_voluntary_removal_of_ubw_with_annotated_photos_and_marked_up_plans.c01.sr02",
        "qualifier_axis": "component_type_key=ubw",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f8cf5aa4cb2c3f70784aa4f6198e3ed4d0ec510e3b8efbb056e84a8860090be9",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 76,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_f_record_defective_flat_entrance_door_with_adverse_fire_effect.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_f_record_defective_flat_entrance_door_with_adverse_fire_effect.c01.sr02",
        "qualifier_axis": "component_type_key=fire_safety_component,location_class_key=private_premises,risk_class_key=fire_safety_adverse_impact",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f7e1a7657f5693dc65b23ac756c2d6528626c5632e34cd9634b5f1caf0816697",
        "slot_id": "risk.fire_safety.adverse_impact",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 77,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_h_statement_if_fire_safety_upgrading_not_completed.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_h_statement_if_fire_safety_upgrading_not_completed.c01.sr02",
        "qualifier_axis": "component_type_key=fire_safety_component",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "4883c18f65abfd4e6b839f142a31a09f322c732889699f496567bf1f83ab4486",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 78,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_j_record_all_ubw_identified_including_those_obstructing_repair.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_j_record_all_ubw_identified_including_those_obstructing_repair.c01.sr02",
        "qualifier_axis": "component_type_key=ubw",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "496769601dde3612783bbb2262fb51b8490ec6885809263d82a7f2120ef38aba",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 79,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_k_report_on_signs_of_suspected_subdivision_of_flats.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_6_1_k_report_on_signs_of_suspected_subdivision_of_flats.c01.sr02",
        "qualifier_axis": "component_type_key=ubw",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "933fd4c2796795500a2d4fb9e3ad26a5cbde3addffe5b57ae3cc9e117d6a161d",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 80,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_8_2_distinguish_mbis_repair_works_from_additional_fire_safety_upgrading_works.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.sapp7_8_2_distinguish_mbis_repair_works_from_additional_fire_safety_upgrading_works.c01.sr02",
        "qualifier_axis": "component_type_key=fire_safety_component",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "4e733b40f7e5463f9c0aaa1ecc42b9684c2ebb6ed4a1da0486c392331c52d020",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 81,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.submit.s7_2_2_submit_report_with_mbi3_certificate.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.submit.s7_2_2_submit_report_with_mbi3_certificate.c01.sr03",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "9c6b2d117e8a0f8a0f9c1c2b51cb399327effa1c7395622191989df20668fa42",
        "slot_id": "artifact.form.mbi3_or_mbi3a",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/artifact_state_not_valid_evidence",
        "false_exit": "open/artifact_state_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 82,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_n_investigation_proposal_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_n_investigation_proposal_to_ba.c01.sr01",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a0c3e132c2102efd138c78c42032af770ca7e90fbdec7cc2399f13b31b857a72",
        "slot_id": "procedure.investigation.proposal.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 83,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_1_check_and_supervise_all_rectification_and_repair_works.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_1_check_and_supervise_all_rectification_and_repair_works.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "2b7ff7f88374076b1be3282c3c6e080d81741c4e85db91a8a48bc7c1586b5ab5",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 84,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_1_frequency_and_scope_not_less_than_appendix6.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_1_frequency_and_scope_not_less_than_appendix6.c01.sr02",
        "qualifier_axis": "actor_role_key=ri",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "e6231aba0c5ad2f5a541fe73a64cf54c6c303351e03f8076692170cc96cc897f",
        "slot_id": "supervision.site_visit.performed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 85,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_reported_and_new_defects_must_be_repaired_or_corrected.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_reported_and_new_defects_must_be_repaired_or_corrected.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a49b170a57f989e208a90f33ed2d6b0038f6d13ae49965bd1b10ee00cdd6429a",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 86,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervise_preparatory_works_to_minimum_standard.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervise_preparatory_works_to_minimum_standard.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "320c73e69a80498218464a32a21be579f102afaf6aff2caf7b1bd0bd2094f2a7",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 87,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervise_rectification_and_repair_to_minimum_standard.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervise_rectification_and_repair_to_minimum_standard.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "1e16364e442b8b14bda5a3dfc1affcd7da2745eeb2f70fb8c3fa036a7ba01c69",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 88,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervision_team_must_be_qualified_and_experienced.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_4_2_supervision_team_must_be_qualified_and_experienced.c01.sr04",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "6814e1dfc8dddd6522d01d1f4824bc75a7db4524fe6c8c252331d9c6df585b3b",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 89,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p1_ensure_repairs_follow_repair_proposal.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p1_ensure_repairs_follow_repair_proposal.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "93473bdf23d0c5992a54a33a16c15459c4cc6ad89ed61b40f4faa711f3ac60ec",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 90,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p2_assign_level1_representative.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p2_assign_level1_representative.c01.sr03",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "3332465987f5a6ebdcbb467b8fd5e30d470cf74a3b275c345fb2d1c6e2c18abc",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 91,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p2_assign_level2_representative.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p2_assign_level2_representative.c01.sr03",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f2d91df1744744d96b67c6f6d593463d6b42a6947e0bf80ff14a2d36dc15f0c5",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 92,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p6_compile_checklists_for_representatives.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p6_compile_checklists_for_representatives.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f5911125de72699667a3bdff34ea91faa25e26a425af9c55d6bdbadc4b5facef",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 93,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p6_register_all_inspected_items_as_inspection_records.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_p6_register_all_inspected_items_as_inspection_records.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "8116253938abf7e65380bf77a02c1122cdc83c212e6676afb96df10dc7b6cf2a",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 94,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level1_representative_t1_equivalent.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level1_representative_t1_equivalent.c01.sr03",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "cf451c63a98ad68f968334a23c1d77031984cfda657d1829291057dbe4d427b9",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 95,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level2_representative_t3_equivalent.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level2_representative_t3_equivalent.c01.sr03",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "8ea3aa84239c71b9a886c8f8faeffd159706a04c3ba0415b75c0b54c364bf2df",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 96,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level2_representative_topup_course_5_years.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl1_level2_representative_topup_course_5_years.c01.sr03",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "2e79ecfba498aed6b2643d74cb562f14e5fec3e3958adf7786dbe46c9f00b2b8",
        "slot_id": "supervision.record.completed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 97,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_level1_weekly.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_level1_weekly.c01.sr02",
        "qualifier_axis": "actor_role_key=ri_rep_lvl1",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "25fb8948deca25ddc704a77d51e95698153733eacbddbab6bb566b1b344546e1",
        "slot_id": "supervision.site_visit.performed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 98,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_level2_fortnightly.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_level2_fortnightly.c01.sr02",
        "qualifier_axis": "actor_role_key=ri_rep_lvl2",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "6e141456a1fef40afd9905a7c5433a66f7a33fb75634966398c899b59fffb344",
        "slot_id": "supervision.site_visit.performed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 99,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_ri_first_inspection_and_level2_proof_tests.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_ri_first_inspection_and_level2_proof_tests.c01.sr02",
        "qualifier_axis": "actor_role_key=ri",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "513f0fbd2399f4eb7a4117882ae01538438c756a46ad96729497aacb0357fbfc",
        "slot_id": "supervision.site_visit.performed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 100,
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_ri_first_inspection_and_level2_proof_tests.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.sapp6_tbl2_ri_first_inspection_and_level2_proof_tests.c01.sr03",
        "qualifier_axis": None,
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "513f0fbd2399f4eb7a4117882ae01538438c756a46ad96729497aacb0357fbfc",
        "slot_id": "verification.test.performed",
        "aggregation_source": "code_derived_reading",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 101,
        "rule_card_id": "rc.mbis.supervision.site_records.ri_team.keep.sapp6_p8_complete_records_contemporaneously.c01",
        "slot_ref_id": "rc.mbis.supervision.site_records.ri_team.keep.sapp6_p8_complete_records_contemporaneously.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f668090c8969628d6e54e1a5ab8a1a74b9649ecb3a18d2539fd699751375a4a2",
        "slot_id": "supervision.record.retained",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 102,
        "rule_card_id": "rc.mbis.supervision.site_records.ri_team.keep.sapp6_p8_retain_checklists_and_records_for_ba_inspection.c01",
        "slot_ref_id": "rc.mbis.supervision.site_records.ri_team.keep.sapp6_p8_retain_checklists_and_records_for_ba_inspection.c01.sr02",
        "qualifier_axis": "artifact_key=record.supervision_checklist",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "65be725763024d02f2bffe5e08df969f6254711521580248904e1e171e11d62c",
        "slot_id": "supervision.record.retained",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    # ==================================================================== #
    # 残余 50 止血·A 表 3 行（2026-08-04 落表）：复测后仍误评的 50 行逐条对中文
    # 原文裁定（两包引文 50/50 逐字）判「前件未核」的槽引用路径子集。
    # 机制：前件谓词被当满足操作数（false ⇒ violated 诬告、true ⇒ 复述前件）。
    # 处置依据：三方商议收敛「先乙止血」（grok+qwen，2026-08-04 凌晨）；
    # s2_1_3_n 意向族 2 组合缓议（真值前件口径未裁），不在本批。
    # ⚠️ 原候选 3 行落表时撞唯一键闸：(s3_3_3_b.c01, sr02) A 批 65 行已在（fail-closed
    # 当场拦下）——该卡残余误评走的是**桶通道**（B 表止血覆盖），槽引用路径已被 A 批
    # 收窄。故本段只落 **2 行**。
    # ==================================================================== #,
    {
        "row": 103,
        "rule_card_id": "rc.mbis.investigation.drainage.ri.follow_up.s4_4_3_arrange_urgent_action_or_report_ba_if_unable.c01",
        "slot_ref_id": "rc.mbis.investigation.drainage.ri.follow_up.s4_4_3_arrange_urgent_action_or_report_ba_if_unable.c01.sr01",
        "qualifier_axis": "component_type_key=drainage_component,location_class_key=public_access_private_lane",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "8eae451fe5f98bcce1a0a3f5154221137de22c892519f122815aeed72c094908",
        "slot_id": "scope.component.inspection_included",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    {
        "row": 104,
        "rule_card_id": "rc.mbis.inspection.structural_components.ri.coverage.s3_4_2_d_expose_concealed_elements_for_representative_assessment.c01",
        "slot_ref_id": "rc.mbis.inspection.structural_components.ri.coverage.s3_4_2_d_expose_concealed_elements_for_representative_assessment.c01.sr01",
        "qualifier_axis": "component_type_key=structural_component",
        "aggregator": "any_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "91b3147e830475d95ef6bbd7996e1ec27c3405f436a809200efad645c2a18c54",
        "slot_id": "scope.component.covered",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "n/a——诊断型不产判定，无完整性判据消费",
        "true_exit": "open/diagnostic_binding_not_valid_evidence",
        "false_exit": "open/diagnostic_binding_not_valid_evidence",
        "verdict_permission": "none",
    },
    # ==================================================================== #
    # 消费通道 c55 批（2026-08-04 落表，22 行，row 105-126）：三根 reporting 轴
    # （呈交/送达/签署）的 55 单元逐条对中文原文裁定后，乙 26＋甲日数 7 的授权行。
    # 裁定档案：裁定_消费55_01-28 / 29-55；多引用/悬案决议：
    # 决议_消费55多引用与角色悬案_20260804.md（单元 2 并入单元 1 两行、
    # 单元 34 落全副两引用、**单元 36 挂 §2.1.3(o)/(p) 角色矛盾案未落**）。
    # 甲事件锚 4 单元（32/33/35/46，双向行带终局判据）＝新机制另立实施步，不在本批。
    # 语义同 row 37 先例（A′值消费）：真→closed/satisfied、
    # 假→open/observed_false_without_violation_basis、绝不产 violated。
    # 🔴 本批每行 qualifier_axis 必含 artifact_key（模式①教训：无限定读数横跨
    # 7 个不相干条款）；模式校验对 row>37 的 value_consumption 行强制此项。
    # kind=artifact 的覆盖面须桶通道值消费钩（同文件 c55 钩）配合才转化。
    #
    # 🟢 粒度声明（DEBT-085 件二·第一步声明期，2026-08-04）：本批 22 行**全部
    # 声明 `granularity_declaration="building"`**，理由是世界侧读数无片段归属——
    # 2026-08-04 复算 `reporting_axes_seed401_20260803` 全 30 栋 fact_pack，
    # 本批四个槽合计 690 条事实，按 `validator._fact_frag` 同口径判**片段载体 0 条**：
    #   reporting.artifact.submitted 390 ／ .delivered 240 ／ .signed 30
    #   ／ reporting.record.submitted 30 —— carrier_type 全为 `sidecar_entry`，
    #   `qualifiers.fragment_id` 全空。
    # 且本批 22 键与 18 键共同待裁清单**零交集**（同日复算），故属「已可无
    # 争议声明」。声明期只登记不消费 ⇒ 判定面逐位不变。
    # ==================================================================== #
    {
        # c55 单元 47（甲日数） pattern4_artifact_false_weaker/pattern6_lead_in_required/pattern7_two_deadline_branches_one_obligation/has_precondition | 2.1.3(o)
        "row": 105,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_mbi3_to_supervising_ri_within_2m.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_mbi3_to_supervising_ri_within_2m.c01.sr01",
        "qualifier_axis": "artifact_key=form.mbi3_or_mbi3a",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f9b1ced837b227692e47acc1cc9ce90eb5e224f4013bee41ab1a3152871ccbcb",
        "slot_id": "reporting.artifact.delivered",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 13,14（乙） kind_artifact_asymmetry/no_trigger/same_card_two_legs | §2.1.3(r)
        "row": 106,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r_completion_report_to_person_same_day.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r_completion_report_to_person_same_day.c01.sr01",
        "qualifier_axis": "actor_role_key=person_for_whom_prescribed_repair_is_carried_out,artifact_key=report.completion",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "cf71b83b46f6720e2f7e9fb9960c700bfd8cbf9c74691d3b7a2924529dbe70e2",
        "slot_id": "reporting.artifact.delivered",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 15,16（乙） kind_artifact_asymmetry/no_trigger/same_card_two_legs | §2.1.3(r)
        "row": 107,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r_mbi4_to_person_same_day.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r_mbi4_to_person_same_day.c01.sr01",
        "qualifier_axis": "actor_role_key=person_for_whom_prescribed_repair_is_carried_out,artifact_key=form.mbi4",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "3c1b8a1e20d73f88fdbc6554536fba314bd880c3b55e53df8cfd63ae788e7c91",
        "slot_id": "reporting.artifact.delivered",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 41,42（乙） modality_adequacy_unverified/same_card_dual_channel | 7.2.3
        "row": 108,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.schema.s7_2_3_sign.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.schema.s7_2_3_sign.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "bfa7faf3570206ba4893a8d0e6716e1d87773b1fbc2fd42f287fb12d4d2d5d89",
        "slot_id": "reporting.artifact.signed",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 34（甲日数） pattern6_lead_in_required/conditional_downgrade | 2.1.3(o)
        "row": 109,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.submit.s2_1_3_o.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.submit.s2_1_3_o.c01.sr03",
        "qualifier_axis": "actor_role_key=ba,artifact_key=form.mbi3_or_mbi3a",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "5f139cd0bcf2dad6ca70aa8f44c98ed19bb1680542cdfaf963ab5184084519bb",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 34（甲日数） pattern6_lead_in_required/conditional_downgrade | 2.1.3(o)
        "row": 110,
        "rule_card_id": "rc.mbis.reporting.inspection_report.ri.submit.s2_1_3_o.c01",
        "slot_ref_id": "rc.mbis.reporting.inspection_report.ri.submit.s2_1_3_o.c01.sr02",
        "qualifier_axis": "actor_role_key=ba,artifact_key=report.inspection",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "5f139cd0bcf2dad6ca70aa8f44c98ed19bb1680542cdfaf963ab5184084519bb",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 20（乙） has_trigger/candidate_for_jia | §2.1.3(i)
        "row": 111,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_i.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_i.c01.sr02",
        "qualifier_axis": "actor_role_key=ba,artifact_key=notice.ri_appointment",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a977545c813ac2594f165310314609fb5b04430f0b451fc98e11e73cc642c7f8",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 51（甲日数） pattern6_lead_in_required/has_precondition/conditional_downgrade | 2.1.3(j)
        "row": 112,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_j.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_j.c01.sr02",
        "qualifier_axis": "actor_role_key=ba,artifact_key=notice.ri_temporary_nomination",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "fb4333de4ea8de37335aa1c7a9e39358a39ee38d47f574dc41f31f703fee1ffb",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 6（乙） no_trigger | §2.1.3(k)
        "row": 113,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_k_nomination_cessation_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_k_nomination_cessation_to_ba.c01.sr01",
        "qualifier_axis": "artifact_key=notice.temporary_ri_nomination_cessation",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "00774aed1ee498313c97f7d01f989d4ff228d03b6c02dc083368737af0611b40",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 7（乙） no_trigger | §2.1.3(l)
        "row": 114,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_l_ri_cessation_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_l_ri_cessation_to_ba.c01.sr01",
        "qualifier_axis": "artifact_key=notice.ri_cessation",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "43637f77cd54e70431e93fdf64554ddb73b7ed2f35a8853453556b4c475a05ee",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 8（乙） no_trigger/prospective_deadline_out_of_scope | §2.1.3(m)
        "row": 115,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_m_representative_intended_appointment_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_m_representative_intended_appointment_to_ba.c01.sr01",
        "qualifier_axis": "artifact_key=notice.representative_appointment_intended",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "86130fd93ebda8d6173e3c3d7d1ab77c673c05d14028f8bd2997fa440ed75ec6",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 9,48（乙） conjunction_half_covered/has_precondition/no_trigger/pattern6_lead_in_required | §2.1.3(n)
        "row": 116,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_n_investigation_intention_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_n_investigation_intention_to_ba.c01.sr01",
        "qualifier_axis": "artifact_key=notice.detailed_investigation_intention",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        # sha 更新（换池捆绑批 2026-08-05，乙路 #30）：卡新增 sr02（真前件槽
        # `procedure.investigation.detailed.intended`，roles=["trigger"]）＋一条卡级触发项。
        # 本行钉的仍是 **sr01**（证据通道逐字节未动）⇒ 八要素里只有卡指纹变，
        # 重核准记录 `重核准记录_换池捆绑_20260805.md`（写在刷指纹之前）。
        "card_content_sha256": "f6de95365997c74626851cf2f493f7a1a112126ab5ee1fc1af0d2c9872c45148",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 43（甲日数） pattern6_lead_in_required/conditional_downgrade | 2.1.3(o)
        "row": 117,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_mbi3_or_mbi3a_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_mbi3_or_mbi3a_to_ba.c01.sr02",
        "qualifier_axis": "artifact_key=form.mbi3_or_mbi3a",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f39f933105180f606d44f1214a51e924fe87469c509a293186211d8356bdfa0c",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 44,45（甲日数） pattern4_artifact_false_weaker/pattern6_lead_in_required/same_card_dual_channel | 2.1.3(o)
        "row": 118,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_report_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_o_report_to_ba.c01.sr02",
        "qualifier_axis": "artifact_key=report.inspection",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "93c27651c19475f89cc81193ac7c7064e8f0f292d99b1140c8425d7463ed1ad3",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 26,27（乙） candidate_for_jia/conjunction_half_covered/has_trigger/kind_artifact_asymmetry/same_card_two_legs | §2.1.3(p)
        "row": 119,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_p.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_p.c01.sr02",
        "qualifier_axis": "actor_role_key=ba,artifact_key=proposal.repair_revision",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "27e0992e7862e9040cbe4b28a9a8479ffcced6b51db58ec7484ba938a2abfaa6",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 1（乙；同卡同槽的单元 2 并入本行承载，见决议档） same_card_two_legs/has_trigger | §2.1.3(r)
        "row": 120,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r.c01.sr03",
        "qualifier_axis": "actor_role_key=ba,artifact_key=form.mbi4",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "2bdf17551c8c12025702d042b160811729cc0c550c269b820e45a9ea61fe8af3",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 1（乙；同卡同槽的单元 2 并入本行承载，见决议档） same_card_two_legs/has_trigger | §2.1.3(r)
        "row": 121,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_r.c01.sr02",
        "qualifier_axis": "actor_role_key=ba,artifact_key=report.completion",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "2bdf17551c8c12025702d042b160811729cc0c550c269b820e45a9ea61fe8af3",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 17,21（乙） kind_artifact_asymmetry/no_deadline_in_clause/no_trigger/same_card_two_legs | §2.1.3(s)
        "row": 122,
        "rule_card_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_s_mbi5_to_ba.c01",
        "slot_ref_id": "rc.mbis.reporting.ri_procedural_notifications.ri.submit.s2_1_3_s_mbi5_to_ba.c01.sr01",
        "qualifier_axis": "artifact_key=form.mbi5",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "87e3e1c9cea04efb21892dab6f8d7b15773086a370b26ebd000ba2414cf60716",
        "slot_id": "reporting.artifact.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 37,52（乙） conditional_downgrade/four_identical_group/pattern1_unqualified_span/same_card_dual_channel | 3.6.2(A)(d)
        "row": 123,
        "rule_card_id": "rc.mbis.inspection.drainage.ri.identify.s3_6_2_a_d_keep_and_submit_inspection_log.c01",
        "slot_ref_id": "rc.mbis.inspection.drainage.ri.identify.s3_6_2_a_d_keep_and_submit_inspection_log.c01.sr02",
        "qualifier_axis": "actor_role_key=bd,artifact_key=record.inspection_log",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "9c250a8f95eea7f09c307f40a562cbbaeb581ae33ae72891235ec75192ada09d",
        "slot_id": "reporting.record.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 38,53（乙） four_identical_group/pattern1_unqualified_span/same_card_dual_channel | 3.3.2(A)(c)
        "row": 124,
        "rule_card_id": "rc.mbis.inspection.external_components.ri.record.s3_3_2_a_c.c02",
        "slot_ref_id": "rc.mbis.inspection.external_components.ri.record.s3_3_2_a_c.c02.sr02",
        "qualifier_axis": "actor_role_key=bd,artifact_key=record.inspection_log",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "3dc294dea0ac935b89ea92dce75f703f8860fa64f6ad81c2464f1e54f548cdd1",
        "slot_id": "reporting.record.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 39,54（乙） card_name_overreach/four_identical_group/pattern1_unqualified_span/same_card_dual_channel | 3.5.2(A)(c)
        "row": 125,
        "rule_card_id": "rc.mbis.inspection.fire_safety_components.ri.follow_up.s3_5_2_a_c_keep_and_submit_daily_fire_safety_inspection_records.c01",
        "slot_ref_id": "rc.mbis.inspection.fire_safety_components.ri.follow_up.s3_5_2_a_c_keep_and_submit_daily_fire_safety_inspection_records.c01.sr02",
        "qualifier_axis": "actor_role_key=bd,artifact_key=record.inspection_log",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "f1c72ef1692c1b333574fac2ba9c7a1059f1b65239c5afda334ea605ed9d8534",
        "slot_id": "reporting.record.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
    {
        # c55 单元 40,55（乙） card_name_overreach/four_identical_group/pattern1_unqualified_span/same_card_dual_channel | 3.7.1(d)
        "row": 126,
        "rule_card_id": "rc.mbis.inspection.ubw_and_related_scope.ri.follow_up.s3_7_1_d_keep_and_submit_daily_ubw_inspection_records.c01",
        "slot_ref_id": "rc.mbis.inspection.ubw_and_related_scope.ri.follow_up.s3_7_1_d_keep_and_submit_daily_ubw_inspection_records.c01.sr02",
        "qualifier_axis": "actor_role_key=bd,artifact_key=record.inspection_log",
        "aggregator": "all_true",
        "allowed_paths": ["node_slot", "slot_role"],
        "policy": "diagnostic_only",
        "card_content_sha256": "a7a10dcc38910b661927ac02f7da2accc2eae63f1c53d84713f1be154151f772",
        "slot_id": "reporting.record.submitted",
        "aggregation_source": "building_reading_aggregation",
        "completeness_precondition": "全真才真：判 true 须非空完整输入；任一假即假；输入缺失或适用范围未定不生成聚合事实保持未知（已审规格冻结边界）",
        "true_exit": "open/evidence_event_coupling_unproven",
        "false_exit": "open/evidence_event_coupling_unproven",
        "verdict_permission": "none",
        # 沿革留痕（#33 保护闸 2026-08-05 翻转前的真值出口）：解封时翻回
        # policy=value_consumption + verdict_permission=value_consumption_aprime
        # + true_exit=closed/satisfied… + false_exit=open/observed_false_…。
        # 本字段在诊断行上零运行时读者，由 `_schema_violations` 的僵尸字段闸看住。
        "true_exit_mode": "contract_satisfied",
        "granularity_declaration": "building",
    },
])

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

# 判定许可依赖指纹（审核门二轮：许可集合变化须使授权自动失效）。
# 批准时冻结的产物态许可集合快照——导入时与活代码实算比对，失配 ⇒ 全部
# 诊断行失效（诊断出口语义依赖该集合的当时形状）。
LICENSE_DEPENDENCY_SHA256 = "a5f88a43ec91f67d59e33549ee34f8f9a10bed4853cf1c695df7c06d7f0848b9"

_ALLOWED_POLICIES = frozenset({"diagnostic_only", "value_consumption"})
# 🔴 第三档 `code_derived_reading`（2026-08-03 决策门乙案，grok+kimi 同解）：
# 检索层**确定性代码派生**的读数，载体不是楼级聚合行。
# 与 `building_reading_aggregation` 分开的理由是 `src_ok` **按 expected_src 分流**——
# 把 `test_performed_from_measurement` 塞进旧档等于对**所有** 65 行放开这个戳，
# 任何未来期望真楼级聚合行的绑定都会静默接受 measurement 载体的派生事实。
# 第三档是**按行 opt-in**，放宽只落在显式改档的那 4 行上。
_ALLOWED_AGG_SOURCES = frozenset(
    {"slot_target_fallback", "building_reading_aggregation",
     "code_derived_reading"})
_ALLOWED_PATHS = frozenset({"slot_role", "node_slot"})

# ---- DEBT-085 件二·声明期：判定粒度显式声明（受控枚举，两张表共用）----
# 🔴 定义只此一份。桶表（bucket_binding_registry）导入本常量与下面的校验器，
# **不许各写一套**——「同一假设散在多层」是本仓反复踩的坑。
GRANULARITY_DECLARATION_KEY = "granularity_declaration"
GRANULARITY_DECLARATION_VALUES = frozenset({"building", "fragment"})


def granularity_declaration_violations(rows, table: str):
    """粒度声明的枚举校验 ＋ 同卡同质校验（决策门 Q1）。

    - **键缺省＝未声明**，合法（声明期缺省语义＝维持现状）。
    - 键存在则值必须在枚举内；**显式 `None` 一律拒**——「已声明但为空」
      与「未声明」若同形，冻结点的 fail-closed 判据会退化成猜测。
    - 同一 `rule_card_id` 的**已声明**行必须同粒度；冲突即违例，
      而任何违例都让调用方整表 fail-closed（与本表既有爆炸半径同构）。

    入参 `rows` 是行字典可迭代；返回违例字符串清单（空＝通过）。
    跨表同卡冲突由桶表侧调用本函数时把两表行并起来喂（桶表可见 A 表，
    反向会成环）——残余不对称已写进 `团队文档/我的笔记/实施记录_件二声明期_20260804.md`。
    """
    bad = []
    by_card = {}
    for r in rows:
        if GRANULARITY_DECLARATION_KEY not in r:
            continue                                    # 未声明——合法
        v = r.get(GRANULARITY_DECLARATION_KEY)
        rid = r.get("row")
        # 跨表调用方会把 row 重贴成 "A表row124" 这类带表名的串（两表行号各自
        # 独立、裸行号读不出是哪张表）；此时不再叠 "row" 前缀。
        tag = f"{table} row{rid}" if isinstance(rid, int) else f"{table} {rid}"
        if v not in GRANULARITY_DECLARATION_VALUES:
            bad.append(f"{tag}: 非法粒度声明 {v!r}"
                       f"（受控枚举 {sorted(GRANULARITY_DECLARATION_VALUES)}）")
            continue
        by_card.setdefault(r.get("rule_card_id"), {}).setdefault(v, []).append(tag)
    for card, per_value in by_card.items():
        if len(per_value) > 1:
            detail = "；".join(f"{v}←{'/'.join(t)}" for v, t in sorted(per_value.items()))
            bad.append(f"同卡粒度声明冲突 {card}: {detail}"
                       "（决策门 Q1：一卡内全部行必须同粒度，冲突拒载）")
    return bad


_REQUIRED_FIELDS = (
    "row", "rule_card_id", "slot_ref_id", "slot_id", "aggregator",
    "allowed_paths", "policy", "card_content_sha256", "aggregation_source",
    "completeness_precondition", "true_exit", "false_exit",
    "verdict_permission",
)


def _current_license_sha() -> Optional[str]:
    """实算产物态许可集合指纹（唯一口径：canonical of 两集合排序清单）。"""
    try:
        from .applicability_v3 import canonical_hash
        from .obligation_deriver import (
            ARTIFACT_STATE_LICENSED_KINDS, ARTIFACT_STATE_UNLICENSED_KINDS,
        )
        return canonical_hash({
            "licensed": sorted(ARTIFACT_STATE_LICENSED_KINDS),
            "unlicensed": sorted(ARTIFACT_STATE_UNLICENSED_KINDS),
        })
    except Exception:  # noqa: BLE001
        return None


# #33 保护闸原因码（2026-08-05，`决议_33处置_20260805.md` §一.1 ／
# `重核准记录_33保护闸_20260805.md`）。
#
# 语义＝「耦合未证、根治后可解封」：世界记录到该产物的呈交/送达/签署状态为真，
# 但四根 reporting 轴（`reporting.artifact.{submitted,delivered,signed}` ＋
# `reporting.record.submitted`）在世界侧 `conditional_inputs=[]`、与程序闸零耦合、
# 独立伯努利采样 ⇒ 「产物存在 ⇒ 事件发生」这条推论世界不保证。
#
# 🔴 与上面两码**时效性不同，绝不合并**：那两码是逐条对中文原文裁定过的
# 「**永久**不能确立」；本码是「**暂时**未证」，补上世界侧条件依赖即可解封。
COUPLING_UNPROVEN_REASON_CODE = "evidence_event_coupling_unproven"

# 丁②：诊断行出口原因码的**窄枚举**——产物态用第一个，非产物读数用第二个，
# #33 耦合未证用第三个。
# 前两码的分流在 `obligation_deriver.diagnostic_refusal_reason_code`（看事实分类器）；
# 第三码**不由事实分类器分流**——同一条呈交轴读数在闸下是「耦合未证」、根治后是
# 「耦合已证」，**事实类型没变、变的是行的授权状态** ⇒ 只能由行级声明决定
# （见 `coupling_unproven_exit_code`）。本集合只保证表里写不出第四种码。
_DIAGNOSTIC_EXIT_REASON_CODES = frozenset({
    "artifact_state_not_valid_evidence",
    "diagnostic_binding_not_valid_evidence",
    COUPLING_UNPROVEN_REASON_CODE,
})


def coupling_unproven_exit_code(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """#33 保护闸的**唯一共享判据**：该授权行是否处于「耦合未证」拒判态。

    🔴 **两条通道必须同调这一个函数**（官方线商议 §2.3 的承重约束）：
    - A′/诊断通道 `obligation_deriver._diagnostic_contract_terminal`；
    - c55 桶通道 `obligation_deriver._bucket_axis_value_consumption`
      （它**不读** `true_exit_mode`、True 时曾硬编码 satisfied ⇒
      只闸 A′ 一侧＝把闸建在两个出口之一，桶开关打开当天即被绕过）。

    判据落在**行级声明**（`true_exit`/`false_exit` 同码为本码），不落在
    `verdict_permission`——那是本仓典型的「登记了没人消费」字段（判定路径零读者），
    挂上去会得到一个看起来生效、实际不生效的闸。

    返回原因码字符串＝该行被闸住；返回 None＝该行不在 #33 射程。
    形状不完整（只有一侧声明本码）时返回 None 并**不**在此报错——
    `_schema_violations` 已强制诊断行两出口必须相同，那里是唯一的报错口。
    """
    if not row:
        return None
    want = f"open/{COUPLING_UNPROVEN_REASON_CODE}"
    if str(row.get("true_exit") or "") != want:
        return None
    if str(row.get("false_exit") or "") != want:
        return None
    return COUPLING_UNPROVEN_REASON_CODE


def _schema_violations() -> List[str]:
    """导入期模式/枚举/重复键/政策出口校验（审核门二轮欠项③）。

    🔴 **爆炸半径：单行错 ⇒ 整表失效**（`_validate_against_pack` 见到任何
    schema 违例即返回「全表 stale ＋ 禁用原因」）。方向是对的——fail-closed
    比「跳过坏行、其余照跑」安全得多，后者会让一处手滑静默缩小收窄面。

    **这条风险已评估并接受**（2026-08-03 审核门要求留痕，不得默认继承）：
    - 评估时 36 行；A 批 65 行＋止血 2 行落表 104 行，c55 消费行 22 条落表后
      126 行，件四批 1 退役 row 21 后现 **125 行**，爆炸半径已逾三倍
      （风险形状不变：失效仍显式、仍是手写权威数据，接受理由继续成立）；
    - 但失效是**显式**的（`DISABLED_REASON` 落盘、消费侧走
      `_rejected_binding_refusal` 落 `blocked/schema_contract_violation`），
      **不是静默降级**；
    - 且表是**手写权威数据**，逐行经决策门裁定 —— 与其让一行错悄悄生效，
      不如整表停摆逼人来看。
    ⇒ 若将来表规模再上一个量级（数百行），应重新评估是否改成「按行隔离失效」，
    但那要求先有**逐行来源可追溯**的机制，现在没有。
    """
    bad: List[str] = []
    seen = set()
    for r in BINDING_CONTRACTS:
        for f in _REQUIRED_FIELDS:
            if not r.get(f) and r.get(f) != 0:
                bad.append(f"row{r.get('row')}: 缺字段 {f}")
        if "qualifier_axis" not in r:      # 键必须存在（值可为 None——行 37）
            bad.append(f"row{r.get('row')}: 缺 qualifier_axis 键")
        if r.get("aggregator") not in ("any_true", "all_true"):
            bad.append(f"row{r.get('row')}: 非法聚合子 {r.get('aggregator')!r}")
        key = (r.get("rule_card_id"), r.get("slot_ref_id"))
        if key in seen:
            bad.append(f"row{r.get('row')}: 重复键 {key}")
        seen.add(key)
        if r.get("policy") not in _ALLOWED_POLICIES:
            bad.append(f"row{r.get('row')}: 非法 policy {r.get('policy')!r}")
        if r.get("aggregation_source") not in _ALLOWED_AGG_SOURCES:
            bad.append(f"row{r.get('row')}: 非法聚合来源")
        if not set(r.get("allowed_paths") or []) <= _ALLOWED_PATHS:
            bad.append(f"row{r.get('row')}: 非法路径")
        if r.get("policy") == "diagnostic_only":
            # 丁④（2026-08-03 三方仲裁）：诊断行的出口字段**只作声明与审计**，
            # 不作执行指令；但必须被锁死，否则单行误填会与终止器分裂。
            t, f_ = str(r.get("true_exit") or ""), str(r.get("false_exit") or "")
            if r.get("verdict_permission") != "none":
                bad.append(f"row{r.get('row')}: 诊断型政策出口不一致")
            if t != f_:
                bad.append(f"row{r.get('row')}: 诊断型两出口必须相同")
            for e in (t, f_):
                st, _, rc = e.partition("/")
                if st != "open":
                    bad.append(f"row{r.get('row')}: 诊断型出口状态必须为 open，得 {st!r}")
                if rc not in _DIAGNOSTIC_EXIT_REASON_CODES:
                    bad.append(f"row{r.get('row')}: 诊断型出口原因码越界 {rc!r}")
        if (r.get("policy") == "value_consumption"
                and "observed_false_without_violation_basis"
                not in str(r.get("false_exit"))):
            bad.append(f"row{r.get('row')}: A′假值出口不一致")
        # c55 批强制项（2026-08-04 工单）：row>37 的值消费行必须带 artifact_key
        # 限定轴——模式①实证：无限定读数横跨 7 个不相干条款，缺轴即过宽授权。
        # row 37 先例（procedure 槽、非 reporting 轴）不受此约束。
        #
        # 🔴 2026-08-05 #33 保护闸：判据必须**同时覆盖被闸住的行**。
        # 翻转后那 22 行的 policy 变成 diagnostic_only，若判据只认 value_consumption，
        # 本条强制项的**适用人群会变成空集**——一条筛不到任何人的判据等于没有
        # （本仓记过的形状：判据必须在被筛人群上有意义）。而它们解封时要翻回值消费，
        # 那时缺轴就是过宽授权。故闸内行照样强制。
        _row_governs_value = (
            r.get("policy") == "value_consumption"
            or coupling_unproven_exit_code(r) is not None
        )
        if (_row_governs_value
                and isinstance(r.get("row"), int) and r["row"] > 37
                and "artifact_key=" not in str(r.get("qualifier_axis") or "")):
            bad.append(f"row{r.get('row')}: 值消费行缺 artifact_key 限定轴"
                       "（c55 强制项——无限定读数会横跨不相干条款）")
        # Q2 裁定（2026-08-04 决策门三线一致）：真值出口按显式字段分叉、不按
        # row 号——值消费行必须带受控枚举 true_exit_mode。
        if (r.get("policy") == "value_consumption"
                and r.get("true_exit_mode") not in ("caller_path",
                                                   "contract_satisfied")):
            bad.append(f"row{r.get('row')}: 值消费行 true_exit_mode 缺失或越界"
                       f"（得 {r.get('true_exit_mode')!r}）")
        # #33 保护闸（2026-08-05）：两条僵尸字段闸，防「登记了没人消费」复活。
        #
        # ①`true_exit_mode` 在诊断行上**零运行时读者**（`_value_consumption_contract`
        #   只对值消费集合内的行读它）。翻转集保留该字段是**有意的沿革留痕**
        #   （解封时照它翻回 `contract_satisfied`），但必须**只在被闸住时**允许存在
        #   ——否则任何一行手滑写成 diagnostic_only 而忘了改出口，就会留下一个
        #   看起来还在生效、实际早已断线的字段。
        # ②反向：带耦合未证出口的行**必须**是 diagnostic_only + verdict_permission=none。
        #   （前者由上面的 `_DIAGNOSTIC_EXIT_REASON_CODES` 闸兜住 value_consumption
        #   侧——值消费行的 false_exit 必须含 observed_false_…，写本码即违例；
        #   这里补的是显式判据，不依赖那条间接推理。）
        _cu = coupling_unproven_exit_code(r)
        if r.get("policy") == "diagnostic_only" and r.get("true_exit_mode") is not None:
            if _cu is None:
                bad.append(
                    f"row{r.get('row')}: 诊断行带 true_exit_mode 却未处于 #33 耦合"
                    f"未证态——该字段在诊断行上零读者，留着即僵尸字段"
                    f"（得 {r.get('true_exit_mode')!r}）")
            elif r.get("true_exit_mode") != "contract_satisfied":
                bad.append(
                    f"row{r.get('row')}: #33 闸住行的沿革 true_exit_mode 必须是"
                    f"解封时要翻回的 'contract_satisfied'（得 "
                    f"{r.get('true_exit_mode')!r}）")
        if _cu is not None and r.get("policy") != "diagnostic_only":
            bad.append(f"row{r.get('row')}: 耦合未证出口只许配 diagnostic_only"
                       f"（得 policy={r.get('policy')!r}）")
        if _cu is not None and r.get("verdict_permission") != "none":
            bad.append(f"row{r.get('row')}: 耦合未证行 verdict_permission 必须为 none")
    # DEBT-085 件二·声明期：粒度声明枚举 ＋ 同卡同质（决策门 Q1，冲突整表拒载）。
    bad.extend(granularity_declaration_violations(BINDING_CONTRACTS, "A表"))
    return bad


def _validate_against_pack() -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]
]:
    """机器护栏：模式校验 → 卡指纹逐行 → 许可依赖指纹。返回 (活, 失效, 禁用原因)。"""
    from .applicability_v3 import rulecard_content_digests

    schema_bad = _schema_violations()
    if schema_bad:
        return [], list(BINDING_CONTRACTS), f"schema:{schema_bad[:3]}"
    try:
        _pack, shas = rulecard_content_digests(_REPO_ROOT)
    except Exception as exc:  # noqa: BLE001 —— fail-closed 全表失效
        return [], list(BINDING_CONTRACTS), f"card_pack_unreadable:{exc}"
    if not shas:
        return [], list(BINDING_CONTRACTS), "card_pack_unreadable"
    lic = _current_license_sha()
    lic_ok = lic == LICENSE_DEPENDENCY_SHA256
    active, stale = [], []
    for r in BINDING_CONTRACTS:
        fp_ok = shas.get(r["rule_card_id"]) == r["card_content_sha256"]
        # 诊断行的出口语义依赖许可集合快照；许可集合漂移 ⇒ 诊断行失效。
        dep_ok = lic_ok or r["policy"] != "diagnostic_only"
        (active if fp_ok and dep_ok else stale).append(r)
    return active, stale, (None if lic_ok else "license_set_drift")


ACTIVE_ROWS, STALE_ROWS, DISABLED_REASON = _validate_against_pack()


def registry_digest() -> str:
    """权威表 canonical 摘要（批清单锚用）。"""
    from .applicability_v3 import canonical_hash
    return canonical_hash(list(BINDING_CONTRACTS))

# ---- 派生视图（只从活行派生；消费方不得绕过表自建集合）----
SCOPE_PRECISE_BINDINGS: Dict[Tuple[str, str], Dict[str, Any]] = {
    (r["rule_card_id"], r["slot_ref_id"]): r for r in ACTIVE_ROWS
}
SLOT_ROLE_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    k for k, r in SCOPE_PRECISE_BINDINGS.items()
    if "slot_role" in r["allowed_paths"])
NODE_SLOT_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    k for k, r in SCOPE_PRECISE_BINDINGS.items()
    if "node_slot" in r["allowed_paths"])
COARSE_SLOTS: FrozenSet[str] = frozenset(r["slot_id"] for r in ACTIVE_ROWS)
VALUE_CONSUMPTION_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    k for k, r in SCOPE_PRECISE_BINDINGS.items()
    if r["policy"] == "value_consumption")
DIAGNOSTIC_ONLY_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    k for k, r in SCOPE_PRECISE_BINDINGS.items()
    if r["policy"] == "diagnostic_only")
# #33 保护闸射程（2026-08-05）：耦合未证 ⇒ 结构上不产 satisfied。
# **只从活行派生**，与其它视图同规矩：消费方不得绕过表自建集合。
COUPLING_UNPROVEN_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    k for k, r in SCOPE_PRECISE_BINDINGS.items()
    if coupling_unproven_exit_code(r) is not None)
# 运行态拒绝视图（S1 实施审二轮欠项②）：失效行不许"消失后回退通用求值"——
# 求值路径命中本视图 ⇒ blocked/schema_contract_violation 拒绝判定。
# 全表禁用（模式违例/卡包不可读）时全部绑定入拒绝视图。
REJECTED_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    (r["rule_card_id"], r["slot_ref_id"]) for r in STALE_ROWS)
