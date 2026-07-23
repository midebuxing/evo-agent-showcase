# Canonical slots 与 projection binding

W2 法规映射层 phase 3 `build_normative_projections_for_world` 主入口的核心依据，是 W0 静态资源层定义的两份资源：**canonical slot universe** + **normative_projection_registry**。本章列两份资源在 W2 端的实施级合约——5 类 `slot_class` 字段 schema + 16 family baseline 完整清单 + `normative_projection_registry` 11 字段 schema + `applicability_predicates` 评估时机 + 跟 rule_card v2 系统的 cross-ref 边界。

**与 W0 规格 08 全文的关系**：W0 规格 08 是 canonical_slot universe + `normative_projection_registry` 填表依据的原始来源（按 D-3 决策 W0 闭环后留 stub 引本章）；本章按 W2 端 projection binding 语义重新组织 + 补 16 family ↔ projection_registry record 的具体对应关系 + applicability_predicates 评估时机，**不重写** W0 规格 08 的 slot 全表（slot 全表读者请同时看 W0 规格 08 §2-§4）。

**与 rule_card v2 系统的关系**：按用户 2026-05-13 D-4 决策，W2 只描述消费契约（哪些字段、哪些 cross-ref），**不复写 rule_card v2 数据规格**——rule_card 端 `semantic_slot_registry_v1.json` 跟 W0 端 5 类 `slot_class` 是两套不同的 slot 分类系统，靠命名一致 + `projection_runtime_mapping_v1.json` 的 `slot_aliases` / `measure_aliases` 衔接（按 memory `feedback_slot_terminology.md`，详见 §5）。

## 1. Canonical slot universe — 5 类 `slot_class`

按 W0 规格 08 §1 + a4 §2.0：W0 端 canonical slot 分 5 类 `slot_class`，每类有独立字段 schema + W2 端消费时机。

### 1.1 5 类 `slot_class` 字段 schema 与 W2 端消费

| `slot_class` | 物理语义 | W2 端消费时机 | 进 `NormativeProjection` 哪个字段 |
|---|---|---|---|
| `world_truth_slot` | 建筑 / 构件 / 缺陷 / 风险 / 修葺结果**本身**——属世界真值；W1 worldgen core 或 derived layer 派生 | phase 3 主循环按 fragment 关联 `world.fragments` / `world.mechanisms` / `world.conditions` 等 W1 输出读 slot 值 | `required_world_core_slots` |
| `measurement_slot` | 比例 / 面积 / 数量 / 时间 / 应力 / 公式 / 采样率等**测量值**；**不应**伪装成 world truth（按 a4 §2.0 line 26 + W0 规格 08 §3 line 106 原则） | phase 3 主循环按 fragment 关联 `world.measurements` 读 W0 measurement slot；按 `sidecar_measurement_registry` 翻 unit / measurement_family 后读 sidecar 数值 slot | `required_measurement_slots` |
| `qualifier_slot` | 限定其他 slot / measure 的**分类信息**（如 `qual.component_type` / `qual.location_class` / `qual.work_category`）；按 taxonomy registry 派生 | phase 3 主循环通过 W1 输出的 `fragment.component_type_id` / `fragment.location_class_id` / sidecar `facts` 桶的 categorical value 间接读 | `required_qualifier_slots` |
| `artifact_requirement` | 报告 / 表格 / 日志 / 相片 / 图则 / 证书 / 声明等**工件证据**；sidecar 端 `artifact_requirement_state` 桶承载，不进 world truth | phase 3 主循环通过 `SidecarRuntimeBundle.artifact_requirement_state` 桶按 `qualifiers.fragment_id` 关联读 | `required_sidecar_interfaces`（合并 artifact + procedure 两类后填入） |
| `procedure_or_gate_requirement` | 委任 / 提名 / 通知 / 认可 / 开始 / 完成 / 送交 / 最终检验等**程序状态**；sidecar 端 `procedure_gate_state` / `supervision_runtime_state` / `completion_runtime_state` 桶承载 | phase 3 主循环通过 `SidecarRuntimeBundle` 对应三桶按 `qualifiers.fragment_id` 关联读 | `required_sidecar_interfaces`（同上） |

**命名约定**（按 W0 规格 08 §1 + C-I 决策）：本规格包统一采用 a4 canonical dot-notation（如 `ratio.covered_area.inspected` / `rate.pull_test.per_25m2` / `stress.pull_test.minimum`）作为 `slot_id` 主名；a12 underscore 实现侧名（如 `covered_area_ratio` / `pull_test_rate_per_25m2`）作为 legacy alias 保留，登记在各 measurement 类 registry entry 的 `aliases` 字段。新增 slot 必须按 a4 dot-notation 风格命名。

**为什么 measurement 不归 world truth**：a4 §2.0 line 26 + W0 规格 08 §3 line 106 明示——比例 / 面积 / 数量 / 时间 / 应力 / 公式 / 采样率等是**测量结果**，必须显式标 `measurement_slot`，避免下游消费方误把测量值跟世界真值混淆。这是 a4 → W0 → W2 三层一致的核心 slot 分类原则。

### 1.2 跨 slot_class 的 W2 端使用规则

- **`world_truth_slot` 是 projection 评估的事实底座**：phase 3 family conflict 解析时按 selected_family 的 `required_world_core_slots` 检查是否全部 ready，决定 `coverage_status` 字段（`world_core_ready` / `unsupported`）
- **`measurement_slot` 是 threshold 评估的入口**：phase 3 跨家族 threshold 查（`find_thresholds_for_slot_any_family`）按 W0 measurement slot 或 sidecar 数值 slot 的 `slot_id` 找 rule_card 端 threshold；详见本包 `07_threshold_regime与冲突回退.md`
- **`qualifier_slot` 跟 family 路由间接相关**：W2 当前 simplified family routing 主要用 `mechanism_family` + `component_type` 二维路由（详见 W2 规格 04 §5），`qualifier_slot` 作为 candidate family 的辅助条件由 `applicability_predicates` evaluator 评估（DEBT-031 gap 10 列代码 evaluator 缺失，详见本章 §6）
- **`artifact_requirement` + `procedure_or_gate_requirement` 都进 sidecar 5 桶**：按 W0 规格 09 §1.2 sidecar 边界契约，两类 slot 都不进 world truth、都靠 sidecar runtime bundle 承载、都进 `required_sidecar_interfaces` 字段（合并消费）

## 2. 16 family baseline 完整清单

按 W0 规格 08 §5 + a4 §3 line 168-190：W2 法规映射层 baseline 是 **16 个 family**，按 MBIS_CoP_2023 法规分支覆盖。

**用户 2026-05-13 决策（甲方案）**：维持 16 family 不为省事牺牲正确性。**spec 优先**——W0 规格 08 §5 baseline 16 family 是当前权威，**不按代码 13 entry 合并**（代码 `regulation_thresholds.py::_W0_FAMILY_TO_RULECARD_PREFIXES` 当前 13 entry 是 gap，登记 DEBT-031 gap 6）。

**⚠️ 跟 rule_card v2 端的关系（重要避坑）**：W2 端 16 coarse family 跟 rule_card 端 fine family 是 **1:N 的 coarse → fine 关系**——rule_card 端 `family_index.json` 含 **43 fine family**（2026-05-13 batch_08 补卡后；按 `phase.actor.subject.action_cluster` 切片），**397 张 rule_card** 主体在 `rule_cards.json`。**不要拿 `family_coverage_baseline_v1.json` 的 9 family 做对账**——那是 W0/worldgen 端覆盖就绪度 baseline，不是 rule_card 端全量 family 清单。完整 16 → 43 crosswalk 表 + 2026-05-13 batch_08 补卡（§5.1 / §5.2 / §5.5 / §6.5 四章 0 卡闭环）详见本包 [`_rule_card_v2现状注解.md`](_rule_card_v2现状注解.md)。

### 2.1 16 family 完整 5 类 slot 覆盖表

> **2026-05-14 扩展**：本表从原 4 列（family_id / 业务域 / 主要覆盖描述）扩展到 6 列，把 a4 §3 line 168-190 16 family × 5 类 slot 完整数据吸收进 spec 端（DEBT-031 gap 7b-i）。每 family 列 4 类 slot（world / measurement / qualifier / sidecar_interface）独立——给 §4 predicate 派生规则 + npr records 提供完整输入源。**a4 §3 原表把 sidecar 拆 artifact + procedure 两独立列**，本表按 W2 设计合并到 `required_sidecar_interfaces`（5 个抽象接口：`inspection_report_sidecar` / `procedure_gate_sidecar` / `supervision_sidecar` / `completion_report_sidecar` / `artifact_requirement_sidecar`，按 spec 02 §3 sidecar 5 桶映射）。

| # | `family_id`（业务域 / MBIS 锚） | `required_world_core_slots` | `required_measurement_slots` | `required_qualifier_slots` | `required_sidecar_interfaces`（含 artifact / procedure 业务说明）|
|---|---|---|---|---|---|
| 1 | `mbis.scope.coverage_and_preinspection`<br/>范围与预检（§1.3 / §3.1 / §3.2 / App2）| `building.identity.basic` / `building.metadata.*` / `scope.component.in_scope` / `scope.component.excluded_from_scope` / `scope.component.covered` / `scope.component.obscured_by_finish` | — | `qual.component_type` / `qual.location_class` | `inspection_report_sidecar`（reference document bundles + review statements）|
| 2 | `mbis.procedure.ri_notifications_and_submissions`<br/>程序通知与提交（§2.1.3）| — | `duration.notification.deadline` / `duration.submission.deadline` / `duration.delivery.deadline` | `qual.actor_role` | `procedure_gate_sidecar` / `inspection_report_sidecar` / `completion_report_sidecar`（MBI1-5 表单 + 委任 / 提名 / 提交 / 修葺里程碑：`procedure.ri.appointment.completed` / `procedure.temp_ri_nomination.*` / `procedure.inspection.prescribed.completed` / `procedure.repair.prescribed.*`）|
| 3 | `mbis.inspection.external_components`<br/>外构件检验（§3.3 / §5.3 / App4）| `scope.component.covered` / `scope.component.covered_by_large_signboard` / `defect.class.present` / `defect.range.extends_into_private_premises` / `risk.building_safety.emergency` / `repair.required` | `area.signboard.display` / `ratio.covered_area.inspected` / `ratio.external_wall_area.inspected` | `qual.component_type` / `qual.location_class` / `qual.defect_class` | `inspection_report_sidecar`（`artifact.record.inspection_log` + annotated photos / plans + 即时通知 + 报告里程碑）|
| 4 | `mbis.inspection.structural_components`<br/>结构构件检验（§3.4）| `defect.class.present` / `defect.range.extends_into_private_premises` / `risk.building_safety.emergency` | `ratio.covered_structure_area.inspected` / `count.canopy.check_locations.minimum` / `length.canopy.check_location.interval` | `qual.component_type` / `qual.defect_class` / `qual.location_class` | `inspection_report_sidecar`（`artifact.record.inspection_log` + representative records + detailed-investigation consideration trigger）|
| 5 | `mbis.inspection.fire_safety`<br/>消防安全检验（§3.5）| `defect.class.present` / `fire_safety.upgrade_outstanding` / `risk.building_safety.emergency` | — | `qual.component_type` / `qual.defect_class` / `qual.location_class` | `inspection_report_sidecar`（`artifact.record.inspection_log` + private-door deficiency record）|
| 6 | `mbis.inspection.drainage`<br/>排水检验（§3.6 / §4.4 / §5.6）| `defect.class.present` / `defect.drainage.misconnection.present` / `risk.public_health.emergency` / `risk.public_danger.present` / `repair.required` | `count.private_premises_access.floor_interval` | `qual.component_type` / `qual.location_class` / `qual.defect_class` / `qual.method_class` | `inspection_report_sidecar`（`artifact.record.inspection_log` + test records + emergency arrangement / BA report if no remedial action）|
| 7 | `mbis.inspection.ubw`<br/>违建检验（§3.7）| `defect.ubw.present` / `defect.subdivided_unit_sign.present` / `risk.building_safety.emergency` / `risk.public_danger.present` | — | `qual.location_class` / `qual.defect_class` | `inspection_report_sidecar`（UBW record tables + annotated photos / plans + immediate BA reporting for urgent / under-construction UBW）|
| 8 | `mbis.investigation.gate_and_proposal`<br/>调查门槛与建议（§4.1 / §4.2）| `defect.cause_or_extent.uncertain` | — | `qual.method_class` / `qual.component_type` | `procedure_gate_sidecar` / `inspection_report_sidecar`（`artifact.notice.investigation_intention` / `artifact.proposal.detailed_investigation` / annotated photos / plans + `procedure.investigation.intention_notified` / `proposal.submitted` / `proposal.recognized` / `started`）|
| 9 | `mbis.investigation.structural_assessment_fsp`<br/>结构评估 FSP（§4.3 / App3）| `investigation.fsp.below_required_safety` / `risk.building_safety.emergency` | `ratio.fsp.structural_performance` / `count.core_sample.minimum` / `rate.core_sample.per_concrete_volume` | `qual.component_type` / `qual.method_class` | `inspection_report_sidecar`（test reports + core sample records + BA immediate report if FSP inadequate）|
| 10 | `mbis.repair.general_selection_and_classification`<br/>修葺一般选择与分类（§5.1 / §5.2）| `repair.required` / `repair.outcome.safe_until_next_cycle` / `maintenance.pre_next_cycle.required` | — | `qual.work_category` / `qual.component_type` | `inspection_report_sidecar`（`artifact.proposal.repair` + classification statement + approval-and-consent sidecar procedures）|
| 11 | `mbis.repair.external_structural_validation`<br/>外构件结构修葺验证（§5.3 / §5.4 / App4 / App5）| `verification.test.failed` / `repair.outcome.safe_until_next_cycle` | `rate.pull_test.per_25m2` / `count.pull_test.per_repaired_facade` / `count.pull_test.per_floor_full_retiling` / `stress.pull_test.minimum` / `count.pull_test.additional_after_failure` / `length.rendering.total_thickness` / `length.rendering.layer_thickness` / `length.concrete_repair.depth` / `ratio.rebar.section_loss` / `length.mortar.application_layer_thickness` / `ratio.chloride_content.by_cement_weight` | `qual.component_type` / `qual.method_class` / `qual.work_category` | `supervision_sidecar` / `completion_report_sidecar`（material certificates + test records + completion evidence + repair completion milestones）|
| 12 | `mbis.repair.fire_safety_and_drainage`<br/>消防与排水修葺（§5.5 / §5.6）| `repair.required` / `maintenance.pre_next_cycle.required` | drainage validation tests (if modeled) | `qual.component_type` / `qual.method_class` / `qual.work_category` | `completion_report_sidecar` / `inspection_report_sidecar`（test records + material / product certificates）|
| 13 | `mbis.supervision.ri_minimum_and_site_controls`<br/>RI 监督最低 + 现场控制（§6.1-§6.4 / App6）| `risk.building_safety.emergency` | `duration.site_visit.interval` | `qual.actor_role` / `qual.method_class` / `qual.work_category` | `supervision_sidecar` / `procedure_gate_sidecar` / `completion_report_sidecar`（`artifact.record.supervision_log_sp1` / `artifact.record.nonconformity_sp2` + witnessed test / material records + `procedure.supervision_team.submitted` / `changed` / `procedure.completed_work.final_inspection_performed` / `supervision.site_visit.performed` / `supervision.record.completed_and_retained`）|
| 14 | `mbis.supervision.rc_controls`<br/>RC 控制（§6.5）| — | — | `qual.actor_role`（限定 `rc`）| `procedure_gate_sidecar`（`procedure.rc.pre_notification_given`）|
| 15 | `mbis.reporting.inspection_report`<br/>检验报告（§7.2 / App7）| `building.identity.basic` / `building.metadata.*` / `repair.required` / `maintenance.pre_next_cycle.required` / `defect.*` / `fire_safety.upgrade_outstanding` / `defect.ubw.present` / `defect.subdivided_unit_sign.present` | all inspection-phase test / sampling results | `qual.artifact_field_group` / `qual.component_type` / `qual.work_category` / `qual.method_class` | `inspection_report_sidecar` / `procedure_gate_sidecar`（`artifact.report.inspection` / `artifact.form.mbi3_or_mbi3a` + inspection log + annotated photos / plans + repair proposal + statements + `procedure.inspection.prescribed.completed`）|
| 16 | `mbis.reporting.completion_report`<br/>完工报告（§7.3 / App8）| `repair.outcome.safe_until_next_cycle` / `maintenance.pre_next_cycle.required` | all verification-test results | `qual.artifact_field_group` / `qual.component_type` / `qual.work_category` / `qual.method_class` | `completion_report_sidecar` / `supervision_sidecar`（`artifact.report.completion` / `artifact.form.mbi4` + material certificates + supervision records + repair photos / plans + statements + `procedure.repair.prescribed.completed` / `procedure.completed_work.final_inspection_performed`）|

**来源**：a4 §3 L168-L190（5 类 slot 完整数据：world / measurement / qualifier / artifact / procedure 5 独立列）+ W0 规格 04 §17-§22 字段合约（验证 slot 引用合法）+ W0 规格 08 §5（family baseline）+ W2 规格 02 §3 sidecar 5 桶映射（artifact / procedure 合并到 `required_sidecar_interfaces`）。

### 2.2 16 family ↔ `normative_projection_registry` records 对应关系

W2 06 的正式权威是 §2.1 的 16 family baseline。`normative_projection_registry` records 的 projection binding 语义归 W2；W0 inventory 只作为 registry bundle 加载清单，不得替代本章 family baseline、predicate、rule、basis 或 conflict semantics。

若 inventory、历史实现侧映射或临时 crosswalk 与本章 16 family baseline 不一致，以本章和 W2 09 输出契约为准。

### 2.3 16 family baseline 的封口口径

当前 spec 权威是 16 family baseline。任何 9 family coverage baseline、13 entry simplified route、代码侧映射表或临时工程映射，都不得替代本章 §2 的 16 family。

rule_card v2 fine family 与 W2 16 coarse family 是 crosswalk 关系，不是一对一替代关系.


## 3. `normative_projection_registry` schema — 11 字段声明

> **归属**：normative_projection_registry 是 **W2 法规映射层注册表**（2026-05-13 用户拍板）。worldgen runtime 加载所有 RegistryTable 时把 npr records 也读进 registry_bundle（详见 W0 规格 02 §1 第 7 分组注 1），是跨层 orchestrator 性质——schema + records source-of-truth 在 W2 端。

按 W0 规格 11 §4.4 + W0 规格 03 §3.1 + 现役代码 `worldgen/registry.py::normative_projection_registry`（L1492-L1504 fields 列表）：`normative_projection_registry` schema 含 **11 字段**。

### 3.1 11 字段总表

| # | 字段 | 类型 | 语义 | W2 端消费 |
|---|---|---|---|---|
| 1 | `projection_registry_id` | str (PK) | 注册表 primary key；形如 `NP_<FAMILY_NAME>_V1` | phase 3 fallback `NP_UNKNOWN_<fragment>` 引用 |
| 2 | `projection_family` | str | family 标识（16 family baseline 之一）| phase 3 `_projection_registry_lookup` 按此字段索引 records；selected_family 写入 `NormativeProjection.projection_family` |
| 3 | `applicability_predicates` | List[Dict] | predicate 评估表达式列表——按 world / measurement / qualifier / sidecar 4 类断言评估当前 fragment 是否 applicable；不得反控 worldgen（按 W0 规格 08 §6 + a9 §5.1）| **当前 W2 simplified routing 未消费**（DEBT-031 gap 7 + gap 10）——phase 3 用 `mechanism_family` + `component_type` 直接路由，绕开 applicability_predicates evaluator |
| 4 | `required_world_core_slots` | List[str] | 该 family 必备的 W0 core canonical slot（world_truth_slot 类）| phase 3 写入 `NormativeProjection.required_world_core_slots`；coverage_status 派生依据 |
| 5 | `required_measurement_slots` | List[str] | 该 family 必备的 W0 measurement / sidecar measurement slot（measurement_slot 类）| phase 3 写入 `NormativeProjection.required_measurement_slots`；跨家族 threshold 查的入口 |
| 6 | `required_qualifier_slots` | List[str] | 该 family 必备的 qualifier slot（qualifier_slot 类）| phase 3 写入 `NormativeProjection.required_qualifier_slots`；当前 simplified routing 主要通过 component_type 间接消费 |
| 7 | `required_sidecar_interfaces` | List[str] | 该 family 必备的 sidecar 接口（合并 artifact_requirement + procedure_or_gate_requirement 两类）| phase 3 写入 `NormativeProjection.required_sidecar_interfaces`；sidecar 5 桶映射入口 |
| 8 | `rule_ids` | List[str] | 该 family 关联的 rule_card_id 清单；W0 只引用，不生成 | phase 3 写入 `ProjectionFamilyEval.rule_ids`；按 C023 `UNKNOWN_NO_RULE_IDS` 约束——selected_family=unknown 时必须清空 |
| 9 | `basis_template_ids` | List[str] | basis 模板 id 清单（`threshold_compare` / `bool_assertion` / `family_uncovered`）| phase 3 构造 `ReportBasisItem.basis_kind` 时参考；本包 `09_输出契约_NormativeProjection.md` §4 列 5 kind |
| 10 | `conflict_group` | str | family 互斥分组 id（4 个枚举之一：`structural_external_surface` / `drainage` / `ubw_fire` / `assessment_repair`）| phase 3 `resolve_family_conflict` 路由 selector；详见 W2 规格 07 §3 |
| 11 | `domain_buckets` | List[str] | 该 family 关联的业务域桶（`structural_external` / `drainage` / `ubw` / `fire_safety` / `coverage_sampling` / `technical_validation` / `assessment` 等）| phase 4 batch 聚合按 domain bucket 分桶统计 |

**T-02 决策**（W0 规格 08 §6 + W0 规格 11 §4.4）：原 a12 spec `required_slots` 单字段拆为 4 类（字段 4-7），与代码 `regulation_projection_executor.py` + `_projection_registry_records()` 字段对齐。spec 反向采纳代码工程精细度（按 D03-3）。

### 3.2 `normative_projection_registry` records 权威

`normative_projection_registry` records 的 projection binding 语义归 W2。本 registry 可被 W0 registry bundle 编排加载，但 W0 不拥有 records 的 family / predicate / rule / basis / conflict semantics.


## 4. `applicability_predicates` 设计与评估时机

按 W0 规格 08 §6 + a12 §13.3 projection compile logic + a9 §2.3 可投影 / 不可投影边界：`applicability_predicates` 是 `normative_projection_registry` 第 3 字段，是 W2 端**family 路由的完整 evaluator**——评估当前 fragment 是否 applicable 于某 family。

### 4.1 predicate 4 类断言

按 W0 规格 08 §6 line 173 + a4 §3 line 168-190：predicate 评估按 4 类断言组合：

| predicate 类 | 评估对象 | 断言语义 |
|---|---|---|
| **world predicate** | `WorldBundle` 字段（`fragment.component_type_id` / `mechanism.mechanism_family` / `condition.condition_class` / 各种 derived flag）| 世界真相是否满足 family applicability 条件（如 family 要求 `defect.class.present=True`） |
| **measurement predicate** | W0 `MeasurementRecord` + sidecar 数值 slot | 测量值是否满足 family applicability 条件（如 family 要求 `ratio.external_wall_area.inspected >= 0.50`，或 measurement 必须存在不论值） |
| **qualifier predicate** | qualifier slot（`qual.component_type` / `qual.location_class` / `qual.work_category`）| 限定信息是否满足 family applicability 条件（如 family 要求 `qual.component_type ∈ {structural_member, balcony_slab, parapet_wall}`） |
| **sidecar join predicate** | sidecar 5 桶 join marker（`procedure_gate_state` / `supervision_runtime_state` / `artifact_requirement_state` / `completion_runtime_state` / `facts`）| sidecar 接口是否 join 上（如 family 要求 `procedure.ri.appointment.completed=True`） |

### 4.2 predicate 评估的 W2 端边界（只读 + 不反向作用 W1）

按本包 `10_禁止依赖.md` §2 W2 红线 + memory `feedback_rule_blind_only_w0_w1.md`：**rule-blind 红线只属 W0/W1 worldgen 层（W1 worldgen 不读法规反推世界），不延伸到 W2 端**——W2 法规映射层**合法消费**法规 + 世界 + 测量 + qualifier + sidecar 是 W2 本职工作。但 W2 端有**自身红线**约束 predicate 评估行为：

| W2 红线 | 在 predicate 评估中的具体禁止 | 锚定来源 |
|---|---|---|
| 红线 1（不反向写回 W1 输出）| predicate 评估**不得**写回 `WorldBundle` / `SidecarRuntimeBundle` 字段 | 本包 `10_禁止依赖.md` §2 红线 1 |
| 红线 2（不派生新事实补 W1）| predicate 评估**不得**生成新的 W1 facts（必须基于已有 W1 输出，不补全 sidecar 派生失败场景）| 本包 `10_禁止依赖.md` §2 红线 2 |
| 红线 8（不消费 W1 内部派生过程）| predicate 评估**不得**调用 W0 surrogate / formula（surrogate 是 W1 派生层内部用，不是 W2 评估用）；**不得**读 W1 内部 distribution 参数 / `recommended_mean` / `recommended_sigma` / `physical_bounds` / `typical_bounds` / `mean_semantics` / `distribution_source` | 本包 `10_禁止依赖.md` §2 红线 8（evo-agent-blind 红线在 W2 端镜像）|
| 红线 6（不消费 evo-agent 训练数据）| predicate 评估**不得**反向读 evo-agent 评估 trace / Skills 库 / Rule-Skills KG-RAG / curriculum learning / replay buffer | 本包 `10_禁止依赖.md` §2 红线 6（evo-agent-blind 红线）|

**关键概念区分**（按 memory `feedback_rule_blind_only_w0_w1.md`）：

| 红线 | 方向 | 适用层 | 具体禁止 |
|---|---|---|---|
| **rule-blind 红线** | W1 ← rule（禁止 W1 读 rule 反推世界）| **W0/W1 worldgen 层** | worldgen 不读 rule_card threshold value 反推世界生成参数（防 evo-agent 训练数据泄漏）|
| **W2 红线 1**（不反向写回 W1）| W2 → W1（禁止 W2 写 W1）| **W2 法规映射层** | W2 评估时不修改 W1 输出 |
| **W2 红线 6 / 8**（evo-agent-blind 镜像）| W2 → evo-agent（禁止 W2 读 evo-agent）+ W2 内部 → evo-agent（禁止 W2 内部参数泄露给 evo-agent）| **W2 法规映射层** | W2 不消费 evo-agent 训练数据 + W2 内部 evaluator 参数不暴露 |

W2 端 predicate 评估**读** rule_card threshold value / family / predicate / basis 是**合法消费**（W2 本职），**不是 rule-blind 红线违反**。

### 4.3 评估时机

按 W0 规格 08 §7 projection compile logic 伪代码：

```text
for each binding in normative_projection_registry:
  evaluate applicability_predicates against world / measurement / qualifier / sidecar join markers
  → applicability_score ∈ [0, 1] + required_slots_present ∈ {True, False}
  evaluate required slots（world_core / measurement / qualifier / sidecar 4 类）
  build threshold_evaluations / basis_items
```

predicate 评估在 phase 3 主循环**单 fragment 内执行**：

1. **入口**：`_build_candidate_families_for_fragment(fragment_id, mechanism_family, component_type, severity_index, projection_family_index)`
2. **遍历**：`normative_projection_registry` records 按 `projection_family` 索引（`_projection_registry_lookup`）
3. **per family predicate 评估**：按 §4.1 4 类断言对当前 fragment 求值；返回 `(applicability_score, required_slots_present)` 二元组
4. **candidate 入选**：`required_slots_present=True` 进 candidate list；按 `applicability_score` 降序排序
5. **conflict 解析**：H3 `resolve_family_conflict(candidate_families, conflict_group_id)` 处理多 family 竞争（详见 W2 规格 07 §3）

### 4.4 full evaluator 与 simplified route 的关系

封口版 W2 以 `applicability_predicates` full evaluator 为 spec 权威。任何 simplified single-target routing 只能作为历史实现适配说明，不得作为 spec 语义替代。

每个 family 的 applicability 必须由 world predicate、measurement predicate、qualifier predicate、sidecar join predicate 四类断言共同决定；不得只用 `mechanism_family` + `component_type` 替代.


### 4.5 每 family 4 类 predicate 派生规则（2026-05-14 封口补充）

按 §4.1 4 类 predicate 设计 + §2.1 16 family 完整 5 类 slot 覆盖表，每 family 的 `applicability_predicates` 字段值按下面规则机械派生（spec → implementation 单向，implementation 不反推 spec）。

#### 4.5.1 派生映射表

| §2.1 表列 | → | §4.1 predicate 类 | 派生形态 |
|---|---|---|---|
| `required_world_core_slots` | → | **world predicate** | 每 slot 派生 1 条 `WorldBundle` 字段断言（slot 存在 / 值满足 family 业务边界）|
| `required_measurement_slots` | → | **measurement predicate** | 每 slot 派生 1 条 `MeasurementRecord` 字段断言（measurement 存在 / 值满足业务条件，不涉及 threshold 比较——threshold 走 phase 3 主循环 H5 `build_threshold_evaluation` 单独评估）|
| `required_qualifier_slots` | → | **qualifier predicate** | 每 slot 派生 1 条 qualifier 字段断言（qualifier 值 ∈ family 适用集合）|
| `required_sidecar_interfaces` | → | **sidecar join predicate** | 每 interface 派生 1 条 sidecar 5 桶 join marker 断言（marker 存在 / `_present=True`）|

#### 4.5.2 predicate 表达式语法（吸收 a10 line 478 / 497 / 522 示例）

每条 predicate 是 **dict 形态**（不是 a10 字符串形态——dict 形态便于代码 evaluate 不依赖 string parser）：

```text
{
    "predicate_class": "world" | "measurement" | "qualifier" | "sidecar_join",
    "target_object": "WorldBundle.fragments[fragment_id]" | "MeasurementRecord" | "qualifier_slot_id" | "sidecar_runtime_bundle.<bucket>",
    "target_path": "<dotted slot path>",
    "assertion": "exists" | "value_in" | "value_equals" | "non_null" | "marker_present",
    "assertion_args": <list | dict>,
    "w2_readonly_note": "predicate 只读不写（按 §4.2 W2 红线 1）",
}
```

#### 4.5.3 派生示例：`mbis.inspection.external_components`

按 §2.1 表 row 3 数据：

```text
applicability_predicates = [
    # world predicates（6 条，对应 required_world_core_slots）
    {"predicate_class": "world", "target_path": "scope.component.covered", "assertion": "value_equals", "assertion_args": {"value": True}},
    {"predicate_class": "world", "target_path": "scope.component.covered_by_large_signboard", "assertion": "non_null", "assertion_args": {}},
    {"predicate_class": "world", "target_path": "defect.class.present", "assertion": "value_equals", "assertion_args": {"value": True}},
    {"predicate_class": "world", "target_path": "defect.range.extends_into_private_premises", "assertion": "non_null", "assertion_args": {}},
    {"predicate_class": "world", "target_path": "risk.building_safety.emergency", "assertion": "non_null", "assertion_args": {}},
    {"predicate_class": "world", "target_path": "repair.required", "assertion": "non_null", "assertion_args": {}},

    # measurement predicates（3 条，对应 required_measurement_slots）
    {"predicate_class": "measurement", "target_path": "area.signboard.display", "assertion": "exists", "assertion_args": {}},
    {"predicate_class": "measurement", "target_path": "ratio.covered_area.inspected", "assertion": "exists", "assertion_args": {}},
    {"predicate_class": "measurement", "target_path": "ratio.external_wall_area.inspected", "assertion": "exists", "assertion_args": {}},

    # qualifier predicates（3 条，对应 required_qualifier_slots）
    {"predicate_class": "qualifier", "target_path": "qual.component_type", "assertion": "non_null", "assertion_args": {}},
    {"predicate_class": "qualifier", "target_path": "qual.location_class", "assertion": "non_null", "assertion_args": {}},
    {"predicate_class": "qualifier", "target_path": "qual.defect_class", "assertion": "non_null", "assertion_args": {}},

    # sidecar join predicates（1 条，对应 required_sidecar_interfaces）
    {"predicate_class": "sidecar_join", "target_path": "inspection_report_sidecar", "assertion": "marker_present", "assertion_args": {}},
]
```

#### 4.5.4 派生规则简化原则

- `non_null` / `exists` 是最弱断言（slot 字段在 WorldBundle / MeasurementRecord 内有记录）—— 适用绝大多数 slot；具体 family 业务边界（如"family 要求 component_type ∈ {external_wall, ...}"）由 `value_in` / `value_equals` 表达
- 当前 §2.1 16 family 表只给 slot 引用清单，**不给值约束**（如"component_type 必须是 external_wall"）—— 这类细粒度业务边界**留 §4.5.5 后续扩展**（按 MBIS 法规章节 + a4 §6 Worked Coverage Examples 进一步分析）
- 当前 spec 06 §4.5 给出 **基础派生规则**（slot 引用 → predicate dict）+ 1 family 完整示例（`external_components`）——其余 15 family 派生由 W2 端 helper 按本节规则机械执行（gap 7c）

#### 4.5.5 后续 spec 扩展点

按 §4.4 当前 simplified routing → §4.3 完整 evaluator 演进，本节 §4.5 给出**派生骨架**；完整 family-level 业务边界值约束（如每个 family 的 `qual.component_type` 适用集合 / `mechanism_family` 适用集合）**待 §2.1 表后续从 a4 §6 Worked Coverage Examples 进一步吸收业务规则**。本扩展点登记 DEBT-031 gap 10 联动——gap 10 evaluator 真正消费 applicability_predicates 时需要更细 predicate 数据。

## 5. 跟 rule_card v2 系统的 cross-ref 边界

按用户 2026-05-13 D-4 决策：W2 只描述消费契约不复写 rule_card v2 数据规格。本节列 W2 端 canonical slot 跟 rule_card v2 端 slot 系统的具体衔接路径。

### 5.1 两套 slot 系统的语义差异

| 维度 | W0 端 5 类 `slot_class` | rule_card v2 端 `semantic_slot_registry_v1.json` |
|---|---|---|
| **定义来源** | a4 §2.0 / W0 规格 08 §1 | rule_card v2 数据系统自身（`agent_v1/regulations/rulecard_v2/mbis_cop_2023/semantic_slot_registry_v1.json`）|
| **分类维度** | 按事实属性分（world truth / measurement / qualifier / artifact / procedure 5 类）| 按 semantic domain 分（scope / defect / risk / repair / verification / procedure / artifact / etc）+ `allowed_roles`（trigger / evidence / definition_reference）|
| **数量** | 5 类 | rule_card 端 ~300 个 semantic slot（`semantic_slot_registry_v1.json` 主体）|
| **绑定关系** | 每个 W0 canonical `slot_id` 属 5 类之一 | 每个 rule_card 端 `slot_ref_id` 跟 W0 端 `slot_id` 通过 `slot_role_map.slot_id` 字段绑定（rule_card 端 `slot_ref_id` 是 W0 端 `slot_id` 的引用 + role 限定 + qualifier 限定）|

**关键差异**（按 memory `feedback_slot_terminology.md`）：W0 端 slot 跟 rule_card 端 semantic_slot 是**两套不同分类系统**——W0 端 5 类是事实属性维度，rule_card 端是法规消费维度；衔接靠**命名一致** + `projection_runtime_mapping_v1.json` 的 `slot_aliases` / `measure_aliases` 双向 alias 机制。

### 5.2 W2 端 alias 翻译路径

按 W2 规格 02 §4.5 + 现役代码 `regulation_projection_contract.py::_slot_aliases` (L43) + `_measure_aliases` (L47)：

| 翻译方向 | 入口 | 触发时机 |
|---|---|---|
| W0 `slot_id` → rule_card `slot_id` alias | `projection_runtime_mapping_v1.json::slot_aliases` dict[str, list[str]] | W2 phase 1 `compile_projection_contract` 编译 rule_card bundle 时使用 |
| W0 `measure_key` → rule_card `measure_key` alias | `projection_runtime_mapping_v1.json::measure_aliases` dict[str, list[str]] | 同上 |
| W0 `slot_id` → sidecar bundle owning interface + lookup rule | `projection_runtime_mapping_v1.json::slot_targets` dict[str, object] | W2 phase 3 sidecar runtime lookup 阶段使用（指 sidecar slot 应该到哪个 sidecar bundle 找 + 查询规则）|

**示例 alias**（按勘探报告 §10.4.3）：

- `slot_aliases`: `"defect.range.uncertain": ["defect.cause_or_extent.uncertain"]`（W0 端 dot-notation 主名 → rule_card 端 alias）
- `slot_aliases`: `"scope.component.covered_by_large_attached_signboard": ["scope.component.covered_by_large_signboard"]`（W0 端新版名 → rule_card 端旧名 alias）
- `measure_aliases`: `"depth.patch_repair": ["length.concrete_repair.depth"]`（W0 端 measure key → rule_card 端 alias）

### 5.3 W2 不复写 rule_card 数据规格

按 D-4 决策 + 用户原则 `feedback_rulecard_specialist_is_translator.md`：

- W2 spec **不复写** `semantic_slot_registry_v1.json` 字段 schema（rule_card 端 slot 系统由 rule_card 团队维护）
- W2 spec **不复写** `measure_registry_v1.json` 字段 schema（rule_card 端 measure 系统由 rule_card 团队维护）
- W2 spec **不复写** rule_card 顶层字段 schema（含 `slot_role_map` / `threshold_regimes` / `applicability` / `trigger_conditions` 等，由 rule_card 团队维护）
- W2 spec **只描述消费契约**——W2 端通过哪些字段、哪些路径、哪些 alias 消费 rule_card 数据；rule_card 数据规格本身是另一套独立 spec（按勘探报告 §12.4 备忘清单，是否独立 spec 待 rule_card team 主动需要或项目阶段触发时再立项）

## 6. 封口正文边界

本章只定义 W2 projection binding 的 spec 语义。实现状态、历史差异跟踪与 import audit 不进入封口正文。


## 7. 来源

- canonical slot universe 5 类 `slot_class` + 字段 schema：W0 规格 08 §1 + a4 §2.0 L16-L26
- 16 family baseline 完整清单：W0 规格 08 §5 + a4 §3 L168-L190（用户 2026-05-13 决策甲方案）
- `normative_projection_registry` 11 字段 schema：W0 规格 11 §4.4 + W0 规格 03 §3.1 + W0 规格 08 §6 填表依据
- `applicability_predicates` 设计：W0 规格 08 §6 + a12 §13.3 projection compile logic + a9 §2.3 可投影边界
- W2 端 predicate 评估边界（只读 + 不反向作用 W1，跟 rule-blind 红线正交）：本包 `10_禁止依赖.md` §2 W2 红线 1 / 6 / 8 + 本章 §4.2 + memory `feedback_rule_blind_only_w0_w1.md`
- 跟 rule_card v2 cross-ref 边界：用户 2026-05-13 D-4 决策 + memory `feedback_rulecard_specialist_is_translator.md` + 勘探报告 §10
- slot 系统两套差异：memory `feedback_slot_terminology.md` + 勘探报告 §10.4.1-§10.4.3
- DEBT-031 gap 6 / gap 7 / gap 10：`团队文档/我的笔记/技术与研究债.md` DEBT-031 子表
