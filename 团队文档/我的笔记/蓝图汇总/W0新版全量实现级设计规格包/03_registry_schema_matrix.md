# Registry Schema Matrix

## 1. Schema Matrix 总表

本文件列出 W0 19 张 registry 的实现级 schema matrix。字段均来自当前封口 spec 的 W0 registry 权威口径；`normative_projection_registry` 虽列在 W0 registry bundle 中，但其 projection binding 语义与 records 字段权威归 W2 `06_canonical_slots与projection_binding.md`。

**关于工程辅助字段**：本表“实现必备字段”列规定的是 spec 强制最小字段集。任何辅助字段不得成为跨包权威源；若辅助字段触及 `NormativeProjection` / family / threshold / unknown / basis 语义，以 W2 06 / 07 / 08 / 09 为准。

| Registry                               | 主键                       | 实现必备字段                                                                                                                         | 字段类型            | 关键约束                      | 枚举 / 允许值来源                     | 跨表引用                            |
| -------------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------- | ----------------------------- | ------------------------------------- | ----------------------------------- |
| `building_template_registry`         | `building_template_id`   | `building_use`,`structure_type`,`storey_count_range`,`primary_materials`,`component_graph_template_ids`                    | enum / list / range | storey range valid            | building / material / component enums | component graph                     |
| `component_type_registry`            | `component_type`         | `material_compatibility`,`default_structural_role`,`geometry_proxy_ranges`,`cover_depth_mm_range`,`allowed_location_classes`,`allowed_mechanisms` | list / enum / range | non-empty；`cover_depth_mm_range` 仅当 `material_compatibility` 含 reinforced_concrete 等 RC 材质时必填（RC-specific 物理参数取值域，对应 spec 04 §5 ComponentNode.cover_depth_mm 字段）；非 RC 材质类型为 null/缺省 | material / location / mechanism enums | material / location / mechanism     |
| `material_system_registry`           | `material_system`        | `material_class`,`supports_rebar`,`supports_finish_layer`,`compatible_defect_classes`                                        | enum / bool / list  | non-empty defects             | material / defect enums               | defect taxonomy                     |
| `location_class_registry`            | `location_class`         | `exposure_options`,`spatial_tags`,`accessibility_prior`,`coverage_relevance`                                                 | list / float / bool | prior `[0,1]`               | location enum                         | coverage relation                   |
| `fragment_template_registry`         | `fragment_template_id`   | `component_type`,`location_class`,`area_range`,`length_range`,`allowed_driver_profiles`,`allowed_mechanisms`             | enum / range / list | compatible component/location | component / location / mechanism      | driver / mechanism                  |
| `coverage_relation_registry`         | `coverage_relation_type` | `target_component_types`,`obscuration_classes`,`ratio_slot_id`,`default_inspection_ratio_range`                              | list / enum / range | ratio `[0,1]`               | component / location / measurement    | measurement registry                |
| `latent_driver_registry`             | `driver_profile_id`      | driver field ranges                                                                                                                  | ranges              | every range valid             | driver fields                         | fragment template                   |
| `mechanism_library_registry`         | `mechanism_family`       | `applicable_component_types`,`required_driver_fields`,`output_condition_classes`,`surrogate_id`                              | list / str          | output non-empty              | mechanism / condition enums           | surrogate                           |
| `defect_condition_taxonomy_registry` | `condition_class`        | `aliases`,`severity_model`,`default_measurement_slots`,`compatible_components`,`compatible_mechanisms`                     | list / enum         | canonical unique              | defect enum                           | component / mechanism / measurement |
| `technical_measurement_registry`     | `slot_id`                | `measurement_family`,`value_type`,`unit`,`physical_bounds`,`precision_steps`,`method_classes`,`aliases`,`recommended_distribution`,`recommended_mean`,`recommended_sigma`,`typical_bounds`,`distribution_source`                        | enum / range / list / list[str] | physical_bounds 物理硬上下界（hard clip）；typical_bounds = [typical_min, typical_max] 工程现实 5%/95% 实操区间，optional（缺则走中点 fallback）；`slot_id` 用 a4 dot-notation；`aliases` 列 a12 underscore legacy 名（C-I 决策） | measurement / method enums            | surrogate                           |
| `sampling_plan_registry`             | `sampling_plan_id`       | `plan_level`,`target_slot_ids`,`basis_area_slot`,`plan_intensity_distribution`,`total_count_formula`,`fragment_allocation_formula`,`coverage_ratio_slot`,`min_count_formula`,`interval_formula`,`notes`                           | enum / list / dict / expr / str         | formula parsable；plan_level ∈ {facade_or_floor_repair_package, fragment}；chain plan record 必填 plan_intensity_distribution + total_count_formula + fragment_allocation_formula（DEBT-020 round5 sub-task 2 chain_C_plus 授权，2026-05-10）；min_count_formula / interval_formula 兼容 a12 旧字段（optional）              | measurement slots（含 technical_measurement_registry chain input + derived A 类）                     | technical measurement；structural_assessment chain derive 路径               |
| `verification_test_registry`         | `test_family_id`         | `method_class`,`required_measurements`,`failure_rule`,`additional_test_formula`,`repair_work_categories`                   | enum / list / expr  | rule parsable                 | method / process enums                | measurement / repair                |
| `assessment_surrogate_registry`      | `assessment_family_id`   | `input_slots`,`output_slots`,`formula`,`physical_bounds`,`noise_model`                                                              | list / expr / range | formula parsable              | measurement slots                     | measurements                        |
| `risk_derivation_registry`           | `risk_flag_id`           | `input_condition_classes`,`input_measurement_slots`,`formula`,`thresholds`,`unknown_policy`                                | list / expr         | threshold valid               | condition / measurement               | condition / measurement             |
| `repair_outcome_registry`            | `repair_outcome_id`      | `input_risk_flags`,`input_verification_flags`,`output_flags`,`formula`                                                       | list / expr         | output non-empty              | risk / repair enums                   | risk / verification                 |
| `normative_projection_registry`      | `projection_registry_id`  | `projection_family`,`applicability_predicates`,`required_world_core_slots`,`required_measurement_slots`,`required_qualifier_slots`,`required_sidecar_interfaces`,`rule_ids`,`basis_template_ids`,`conflict_group` | list / expr         | no worldgen dependency；`required_*_slots` 4 类拆分（T-02 决策反向采纳 code 工程精度）；主键 + 关键字段命名按 spec 11/15/封口总则与 W2 06 records source-of-truth 对齐 | rule-side ids + slot ids              | measurement / world slots / sidecar |
| `sidecar_ownership_registry`         | `sidecar_slot_id`        | `sidecar_domain`,`carrier_type`,`joins_on`,`projection_consumable`                                                           | enum / list / bool  | no world truth fields         | sidecar enums                         | projection executor                 |
| `sidecar_measurement_registry`       | `slot_id`                | `measurement_family`,`value_type`,`unit`,`physical_bounds`,`precision_steps`,`carrier_domain`,`carrier_slot`,`rule_basis_refs`,`aliases`,`recommended_distribution`,`recommended_mean`,`recommended_sigma`,`typical_bounds`,`distribution_source` | enum / range / list / str / list[str] | physical_bounds 物理硬上下界；typical_bounds = [typical_min, typical_max] 实操区间，optional；carrier_domain ∈ {procedure, supervision, inspection_execution}; rule_basis_refs 非空；`slot_id` 用 a4 dot-notation；`aliases` 列 a12 legacy 名（C-I 决策） | duration / interval enums; carrier domain enum (procedure/supervision) | sidecar_ownership_registry, normative_projection_registry |

## 2. Registry 填表约束

### 2.1 资产空间域

| Registry                       | 必填原因                                                               | 实现约束                                                                                       |
| ------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `building_template_registry` | 缺少 building metadata 会阻塞 scope / preinspection / reporting family | `storey_count_range`必须有效；`primary_materials`必须能被 `material_system_registry`支持 |
| `component_type_registry`    | MBIS scope、inspection、repair 都必须挂到构件                          | `allowed_location_classes`与 `allowed_mechanisms`不得为空                                  |
| `location_class_registry`    | location 是 scope、coverage、drainage、UBW 的关键 qualifier            | `accessibility_prior`必须在 `[0,1]`                                                        |
| `fragment_template_registry` | W0 判断单位是建筑片段                                                  | `component_type`与 `location_class`必须兼容                                                |
| `coverage_relation_registry` | external / structural covered-area inspection 需要 coverage relation   | ratio slot 必须在 `technical_measurement_registry`中存在                                     |

来源：`03_a11_权威旧蓝图.md`:L59-L80、L424-L434；`01_a12_权威旧蓝图.md`:L574-L582。

### 2.2 缺陷字典域

| Registry                               | 必填原因                                                                                                  | 实现约束                                                                         |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `defect_condition_taxonomy_registry` | 统一 crack / corrosion / spalling / hollowing / leak / blocked_path / misconnection / loose_fixing 等语汇 | `condition_class`canonical unique；必须列出 compatible components / mechanisms |
| `material_system_registry`           | 露筋、腐蚀、饰面脱落等均依赖材料能力                                                                      | `supports_rebar=false`时不得产生 rebar exposure truth                          |

来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L50-L68；`01_a12_权威旧蓝图.md`:L578-L585、L1596-L1602。

### 2.3 驱动测量域

| Registry                           | 必填原因                                                     | 实现约束                                          |
| ---------------------------------- | ------------------------------------------------------------ | ------------------------------------------------- |
| `latent_driver_registry`         | driver 是机制激活与严重度的父层                              | 每个 driver field range 必须有效                  |
| `technical_measurement_registry` | measurement slot、unit、physical_bounds、precision、method 均必须注册；DEBT-026 typical 分布字段（recommended_distribution / mean / sigma / typical_bounds / distribution_source）optional | `slot_id`是 `MeasurementRecord.slot_id`的外键 |
| `sampling_plan_registry`         | coverage ratio / count / interval 不来自 defect geometry；DEBT-020 round5 sub-task 2 复活后承载 chain_C_plus plan-level 数据（pull_test sampling plan + coverage inspection plan），让 `rate.pull_test.per_25m2` / `ratio.covered_area.inspected` 升 A 类后能跑 facade-level allocation 而非 per-fragment 直接采     | formula 必须可解析；target slot 必须存在；chain plan record 必填 plan_level + plan_intensity_distribution + total_count_formula + fragment_allocation_formula；plan_intensity_distribution dict 含 recommended_distribution / recommended_mean / recommended_sigma / typical_bounds 4 个 key（与 technical_measurement_registry typical 字段同义）          |

来源：`01_a12_权威旧蓝图.md`:L220-L253、L413-L475、L582-L587；`03_a11_权威旧蓝图.md`:L96-L110。

### 2.4 机理 / 派生 / 高阶评估域

| Registry                          | 必填原因                                                      | 实现约束                                                               |
| --------------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `mechanism_library_registry`    | mechanism 是 condition 的父层                                 | `output_condition_classes`不得为空；`surrogate_id`必须可路由到实现 |
| `risk_derivation_registry`      | risk flags 是由 world / measurement 派生的法规输入            | thresholds 必须有效；unknown_policy 必须声明                           |
| `repair_outcome_registry`       | repair / safe-until-next-cycle 不能由 artifact 直接替代       | output_flags 不得为空                                                  |
| `verification_test_registry`    | 附录四 / 五的 test rate、stress、failure follow-up 需要公式化 | failure_rule 是 free-text 表达式（见下 §2.4.1 评估契约）；additional_test_formula 必须可解析 |
| `assessment_surrogate_registry` | FSP / core sample 等 structural assessment 需要专门 surrogate | formula、physical_bounds、noise_model 必须存在                                  |

#### 2.4.1 `verification_test_registry.failure_rule` 评估契约

`failure_rule` 字段是 **free-text 表达式**，不是结构化 `{slot, operator, threshold}` schema。本封口版明确保留 free-text 形态，理由如下（按 `verification_test_registry` 13 条 record 的 `failure_rule` 实际取值归纳）：

- **形态异构**：13 条 `failure_rule` 取值跨度大——既有可解析的 `slot 运算符 阈值 [+ or/and 组合]` 形态（如 `index.drainage.blockage > 0.5 or flag.drainage.misconnection_present == True`、`strength.pull_test.reported < stress.pull_test.minimum or repair_quality_index < 0.45`），也有含**算术运算**的（`thermal_anomaly_area > 0.20 * fragment_area`），还有**原子不可分谓词**（无 slot / 运算符 / 阈值可拆，如 `smoke_detected_at_unexpected_outlet`、`ball_fails_to_pass_within_time_limit`、`door_fails_to_close_completely`）。
- **算术 + 原子谓词无法用结构化 schema 表达**：结构化 `{slot, operator, threshold}` 三元组装不下"阈值侧带算术"与"整条规则是一个不可分谓词"两类，因此本封口版不强行结构化，保 free-text。

**评估契约**（给 code 评估 `failure_rule` 的 spec 依据）：

- `failure_rule` 中出现的可解析操作数，其 **slot 名优先引用已注册 measurement slot**（`technical_measurement_registry.slot_id`，dot-notation，如 `index.drainage.blockage` / `strength.pull_test.reported` / `time.fire_door.self_closing.delay_sec`）；非 dot-notation 的符号名（如 `hollow_sound_fraction` / `thermal_anomaly_area` / `pressure_loss_rate` / `moisture_reading` / `specimen_strength`）是该 test method 的语义占位符，code 评估时按对应 test family 语义解释。
- 允许运算符：`<` / `>` / `<=` / `>=` / `==`，顶层 `or` / `and` 组合；阈值侧允许字面量数值，也允许 `0.20 * fragment_area` 这类一阶算术。
- **符号阈值名**（如 `moderate_threshold` / `moisture_threshold_proxy` / `acceptable_threshold` / `required_minimum`）是占位常量，本封口版未给统一数值表；code 当前实现按 spec 06 §9 仅对 `VT_PULL_TEST_EXTERNAL_V1` 的 `failure_rule` 做结构化求值（`strength.pull_test.reported < stress.pull_test.minimum or repair_quality_index < 0.45`），其余 test family 的 `failure_rule` 求值待后续按 test method 物理语义补全；这属实现 follow-up，不是 spec 缺陷。
- `additional_test_formula`（与 `failure_rule` 不同字段）形态收敛，保持"必须可解析"约束不变（如 `additional_count = failure_count^2 - 2*failure_count + 3`）。

来源：`01_a12_权威旧蓝图.md`:L587-L591、L658-L673、L1363-L1445；`03_a11_权威旧蓝图.md`:L144-L157。

### 2.5 Projection / Sidecar

| Registry                          | 必填原因                                          | 实现约束                                                                                |
| --------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `normative_projection_registry` | 所有业务域必须经过法规投影绑定                    | 不得反向依赖 worldgen generation；只消费 world / measurement / qualifier / sidecar join |
| `sidecar_ownership_registry`    | artifact / procedure / supervision 必须有边界契约 | 不得包含 world truth 字段；必须声明 joins_on 与 projection_consumable                   |
| `sidecar_measurement_registry`  | sidecar 域内 measurement-性 slot（duration / interval / count）的 schema 不得混入 `technical_measurement_registry` | unit / physical_bounds 必须有效；carrier_domain ∈ {procedure, supervision, inspection_execution}；carrier_slot 必须先在 `sidecar_ownership_registry` 注册；rule_basis_refs 非空（B 类合规 slot 必须可追法规章节）；DEBT-026 typical 分布字段 optional |

来源：`01_a12_权威旧蓝图.md`:L591-L593、L1894-L1936；`06_a4_canonical_slot_universe_权威旧蓝图.md`:L216-L217。

## 3. 跨表引用清单

> **注**：`building_template_registry.component_graph_template_ids` 不在本清单 — T-30 pro 决策（详见 §4.8）保留该字段为预留位（全 entry 值 `[]`，无对应 `component_graph_template_registry`），按 "不抢先定义未存在的外键" 原则**不进活跃外键清单**。未来如增设 graph 表再加。

| 引用方                                                           | 被引用方                                                                  | 约束                                                |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------- |
| `component_type_registry.material_compatibility`               | `material_system_registry.material_system`                              | component/material 不兼容为 P0 reject               |
| `component_type_registry.allowed_location_classes`             | `location_class_registry.location_class`                                | component 必须引用合法 location                     |
| `component_type_registry.allowed_mechanisms`                   | `mechanism_library_registry.mechanism_family`                           | active mechanism 必须兼容                           |
| `fragment_template_registry.allowed_driver_profiles`           | `latent_driver_registry.driver_profile_id`                              | fragment 必须能采样 driver                          |
| `fragment_template_registry.allowed_mechanisms`                | `mechanism_library_registry.mechanism_family`                           | mechanism selection 受 fragment 限制                |
| `coverage_relation_registry.ratio_slot_id`                     | `technical_measurement_registry.slot_id`                                | coverage measurement 必须注册                       |
| `defect_condition_taxonomy_registry.default_measurement_slots` | `technical_measurement_registry.slot_id`                                | condition 派生 measurement 必须有 slot contract     |
| `mechanism_library_registry.output_condition_classes`          | `defect_condition_taxonomy_registry.condition_class`                    | mechanism 输出必须是 canonical condition            |
| `sampling_plan_registry.target_slot_ids`                       | `technical_measurement_registry.slot_id`                                | sampling 输出 slot 必须注册                         |
| `verification_test_registry.required_measurements`             | `technical_measurement_registry.slot_id`                                | technical validation 输入输出必须注册               |
| `assessment_surrogate_registry.input_slots/output_slots`       | `technical_measurement_registry.slot_id`                                | assessment 输入输出必须注册                         |
| `risk_derivation_registry.input_condition_classes`             | `defect_condition_taxonomy_registry.condition_class`                    | risk 派生输入必须存在                               |
| `risk_derivation_registry.input_measurement_slots`             | `technical_measurement_registry.slot_id`                                | risk 派生 measurement 输入必须存在                  |
| `repair_outcome_registry.input_risk_flags`                     | `risk_derivation_registry.risk_flag_id`                                 | repair outcome 依赖 risk flags                      |
| `normative_projection_registry.required_world_core_slots`      | world truth slot ids                                                      | 缺失时按 unknown / not_applicable                       |
| `normative_projection_registry.required_measurement_slots`     | measurement slot ids（含 sidecar_measurement_registry slots）             | 缺失时按 unknown / not_applicable（sidecar 缺失旧口径已废止；封口版按 W2 `sidecar_join_status` + `unknown_reason_code=sidecar_only_fact_pattern` 处理） |
| `normative_projection_registry.required_qualifier_slots`       | qualifier slot ids                                                        | 缺失时按 unknown / not_applicable                       |
| `normative_projection_registry.required_sidecar_interfaces`    | sidecar interface ids（procedure / artifact / supervision sidecar）     | sidecar join 为 `partial` / `unavailable` 且影响法规映射时，按 W2 `sidecar_join_status` + `unknown_reason_code=sidecar_only_fact_pattern` / `not_applicable` 处理 |
| `sidecar_ownership_registry.joins_on`                          | `world_id`,`building_id`,`fragment_id`,`component_id`,`slot_id` | join key 必须稳定                                   |
| `sidecar_measurement_registry.carrier_slot`                    | `sidecar_ownership_registry.sidecar_slot_id`                              | sidecar measurement 必须先在 ownership registry 注册 carrier |
| `sidecar_measurement_registry.slot_id`                         | `normative_projection_registry.required_measurement_slots`                | projection 引用 sidecar measurement 时按 slot_id 解析       |

## 4. Registry entry skeleton 保留口径

以下 entry skeleton 直接来自 `a12`，用于固定三类 registry 的字段形状。由于它们不与新版过滤原则冲突，故完整纳入本规格包；后续不得删减字段，也不得扩展出任何 HiddenGold / gold-copy 语义。（来源：`01_a12_权威旧蓝图.md`:L596-L673；`09_用户原则说明.md`:L22-L25）

### 4.1 `component_type_registry`

```yaml
component_type_registry:
  rc_beam:
    material_compatibility: [reinforced_concrete]
    default_structural_role: primary_load_bearing
    geometry_proxy_ranges:
      length_m: [0.5, 12.0]
      visible_area_m2: [0.1, 30.0]
      thickness_mm: [150, 1200]
    cover_depth_mm_range: [20.0, 75.0]   # RC-specific 物理参数；RC 类型必填（梁通常 20-75mm 保护层）
    allowed_location_classes: [beam_soffit, beam_side, interior_common_part, exterior_facade]
    allowed_mechanisms: [load_crack, restraint_crack, corrosion_spall, delamination, repair_validation_failure]

  drainage_pipe:
    material_compatibility: [cast_iron, pvc, concrete_drain, unknown_material]
    default_structural_role: service_component
    geometry_proxy_ranges:
      length_m: [0.3, 200.0]
      visible_area_m2: [0.01, 20.0]
      thickness_mm: [1, 200]
    # cover_depth_mm_range 缺省（非 RC 材质，cover_depth_mm 落 null）
    allowed_location_classes: [pipe_duct, external_wall, underground, roof]
    allowed_mechanisms: [drainage_blockage, drainage_misconnection, drainage_leakage]

  fire_door:
    material_compatibility: [metal, timber, composite_material]
    default_structural_role: service_component
    geometry_proxy_ranges:
      length_m: [0.5, 3.0]
      visible_area_m2: [0.5, 10.0]
      thickness_mm: [20, 100]
    # cover_depth_mm_range 缺省（非 RC 材质，cover_depth_mm 落 null）
    allowed_location_classes: [escape_route, common_part]
    allowed_mechanisms: [fire_safety_deficiency]
```

### 4.2 `technical_measurement_registry`

DEBT-026 (2026-05-09) 字段拆分：`physical_bounds` 是物理硬上下界（hard clip 边界），`typical_bounds` 是工程现实 5%/95% 实操区间（采样 clip）。`recommended_distribution / recommended_mean / recommended_sigma / typical_bounds / distribution_source` 5 个字段 optional——缺则 `_sample_value_for_slot` 退回中点采样 fallback；齐则走 typical 分布采样路径（详见 spec 06 §11.5）。`distribution_source` 用于 provenance（如 `proagent_engineering_estimate_DEBT020_round2_2026_05_09`）。

```yaml
technical_measurement_registry:
  covered_area_ratio:
    measurement_family: coverage_sampling
    value_type: float
    unit: ratio
    physical_bounds: [0.0, 1.0]
    precision_steps: {coarse: 0.05, standard: 0.01, fine: 0.005}
    method_classes: [visual_inspection, plan_based_estimate]
    # DEBT-026 typical 分布参数（optional）
    recommended_distribution: null
    recommended_mean: null
    recommended_sigma: null
    typical_bounds: null
    distribution_source: null

  crack_width_mm:
    measurement_family: defect_geometry
    value_type: float
    unit: mm
    physical_bounds: [0.05, 3.0]
    precision_steps: {coarse: 0.1, standard: 0.05, fine: 0.01}
    method_classes: [visual_inspection, crack_gauge]
    recommended_distribution: lognormal
    recommended_mean: 0.45              # arithmetic median
    recommended_sigma: 0.75             # log-space sigma
    typical_bounds: [0.05, 2.00]        # 实操区间（采样 clip）
    distribution_source: proagent_engineering_estimate_DEBT020_round2_2026_05_09

  fsp_structural_performance_ratio:
    measurement_family: assessment
    value_type: float
    unit: ratio
    physical_bounds: [0.0, 2.0]
    precision_steps: {coarse: 0.05, standard: 0.01, fine: 0.005}
    method_classes: [structural_assessment]
    # A 类（spec 06 §10 公式 derive）→ typical 分布字段 null（不走 distribution）
    recommended_distribution: null
```

### 4.3 `risk_derivation_registry`

```yaml
risk_derivation_registry:
  risk_building_safety_emergency:
    input_condition_classes: [major_crack, severe_spall, structural_instability, severe_ubw_alteration]
    input_measurement_slots: [crack_width_mm, spall_area_m2, fsp_structural_performance_ratio]
    formula: "severity_index >= 0.85 or fsp_structural_performance_ratio < 0.75"
    thresholds: {severity_index: 0.85, fsp_ratio_min: 0.75}
    unknown_policy: not_applicable_if_inputs_missing

  risk_public_health_emergency:
    input_condition_classes: [drainage_leakage, drainage_misconnection, sewage_backflow]
    input_measurement_slots: []
    formula: "public_health_risk_index >= 0.80"
    thresholds: {public_health_risk_index: 0.80}
    unknown_policy: false_if_no_drainage_state
```

### 4.4 `sampling_plan_registry`（DEBT-020 round5 sub-task 2 复活，2026-05-10）

授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L237-L431（## #2 Sub-task 2 Option C+ 链式派生 chain_C_plus 完整 yaml schema）。

链式派生（chain_C_plus）= 立面级（facade-level）/ 楼层级（floor-level）plan 数据 → per-fragment area-proportional 分配（avoid small-fragment rate explosion 防小片段速率爆炸）。

```yaml
sampling_plan_registry:
  pull_test_sampling_plan:
    plan_level: facade_or_floor_repair_package
    target_slot_ids:
      - facade_total_repaired_area_m2
      - total_pull_test_count_per_facade
      - effective_pull_test_count_per_fragment
      - rate.pull_test.per_25m2
    basis_area_slot: facade_total_repaired_area_m2
    plan_intensity_distribution:
      recommended_distribution: lognormal
      recommended_mean: 1.25         # arithmetic mean tests/25m²
      recommended_sigma: 0.35        # sigma_log
      typical_bounds: [0.50, 3.00]
    total_count_formula: |
      plan_intensity = sample_lognormal(mean=1.25, sigma_log=0.35, clip=[0.50,3.00])
      total_pull_test_count_per_facade =
        round_clip(plan_intensity * facade_total_repaired_area_m2 / 25.0, lower=1, upper=25)
    fragment_allocation_formula: |
      effective_pull_test_count_per_fragment =
        total_pull_test_count_per_facade
        * fragment_repaired_area_m2
        / max(facade_total_repaired_area_m2, eps)
    coverage_ratio_slot: rate.pull_test.per_25m2
    notes: |
      Option C+ chain: facade-level count plan-allocation 给小 fragment 的 effective_count
      可为非整数，再除以 fragment_area/25.0 derive rate；代数等价于 facade-level
      total_count / facade_area * 25.0，所以 1m² fragment 不会爆炸 rate=25。MC sanity:
      rate.pull_test.per_25m2 mean≈1.25, p5/p95≈[0.64,2.10]（详见 spec 06 §9）。

  coverage_inspection_plan:
    plan_level: fragment
    target_slot_ids:
      - inspected_area_ratio_per_fragment
      - inspected_area_m2
      - ratio.covered_area.inspected
    basis_area_slot: fragment_area_m2
    plan_intensity_distribution:
      recommended_distribution: truncated_normal
      recommended_mean: 0.45
      recommended_sigma: 0.18
      typical_bounds: [0.10, 0.85]
    total_count_formula: |
      inspected_area_ratio_per_fragment =
        sample_truncated_normal(mean=0.45, sigma=0.18, clip=[0.10,0.85])
    fragment_allocation_formula: |
      inspected_area_m2 = inspected_area_ratio_per_fragment * fragment_area_m2
      ratio.covered_area.inspected =
        clip(inspected_area_m2 / max(fragment_area_m2, eps), 0.0, 1.0)
    coverage_ratio_slot: ratio.covered_area.inspected
    notes: |
      Per-fragment truncated_normal 直接采样；不需要 facade-level allocation。
      MC sanity: ratio.covered_area.inspected mean≈0.45, p5/p95≈[0.15,0.75]
      （详见 spec 06 §8）。

  # DEBT-020 round5 sub-task 4 (2026-05-10) Missing-Formulas plan record
  # 授权：`回复.md`:L1266-L1292
  floor_retiling_package:
    plan_level: floor_retiling_package
    target_slot_ids:
      - floor_full_retiling_area_m2
      - count.pull_test.per_floor_full_retiling
    basis_area_slot: floor_full_retiling_area_m2
    plan_intensity_distribution:
      recommended_distribution: lognormal
      recommended_mean: 1.35         # arithmetic mean tests/25m²
      recommended_sigma: 0.30        # sigma_log
      typical_bounds: [0.60, 3.00]
    total_count_formula: |
      retiling_plan_intensity = sample_lognormal(mean=1.35, sigma_log=0.30, clip=[0.60,3.00])
      count.pull_test.per_floor_full_retiling =
        round_clip(retiling_plan_intensity * floor_full_retiling_area_m2 / 25.0, lower=1, upper=20)
    fragment_allocation_formula: null  # floor-level, 不分配到 fragment
    notes: |
      DEBT-020 round5 sub-task 4 floor retiling chain：floor-level lognormal
      plan_intensity + retiling area → round_clip count [1, 20]。
      MC sanity: count.pull_test.per_floor_full_retiling mean≈5.6, p5/p95≈[2,10]
      （详见 spec 06 §X.X）。
```

### 4.5 `sidecar_measurement_registry`（DEBT-020 round5 sub-task 5 拆分，2026-05-10）

授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1548-L1668。

`duration.delivery.deadline` slot 拆为 2 个新 sidecar slot + 老 slot 标 deprecated：

```yaml
sidecar_measurement_registry:
  duration.delivery.deadline:
    deprecated_at: 2026-05-10
    replacement_slots:
      - duration.delivery.deadline.to_person
      - duration.delivery.deadline.to_ba
    deprecation_reason: |
      Mixed semantics conflate (1) completion report submission to BA
      (repair-completion-anchored) with (2) same-day copy delivery to the
      prescribed-repair person (BA-submission-anchored). Use replacement_slots;
      old slot kept as backward-compatible alias for one release cycle and
      SHOULD NOT be bound by rule_card any longer.
    distribution_source: deprecated_replaced_by_to_person_and_to_ba_DEBT020_round5_sub_task_5_2026_05_10
    # 旧 distribution 保留作 backward-compat baseline（不再被 rule_card 绑定）

  duration.delivery.deadline.to_person:
    measurement_family: procedure_duration
    value_type: int
    unit: day
    physical_bounds: [0, 14]
    carrier_domain: procedure
    carrier_slot: artifact.report_completion_or_mbi4.submitted_to_ba
    rule_basis_refs:
      - "MBIS COP 2023 §2.1.3(r) - completion report / MBI4 delivery (text wording PENDING_RULECARD_TEAM_COP_VERIFICATION)"
    aliases: [duration.delivery.lag.to_person_after_ba_submission]
    rule_card_threshold: PENDING_RULECARD_TEAM_COP_VERIFICATION
    semantic_note: |
      completion report / MBI4 已提交或签发给 BA 的同日，deliver copy / relevant
      document to the person for whom prescribed repair is carried out.
      不应从 repair completion 起算.
    recommended_distribution: zero_inflated_discrete  # → normal in normalize
    recommended_mean: 0.45
    recommended_sigma: 1.15
    typical_bounds: [0, 3]
    distribution_source: proagent_engineering_estimate_current_authority_round5_2026_05_10

  duration.delivery.deadline.to_ba:
    measurement_family: procedure_duration
    value_type: int
    unit: day
    physical_bounds: [0, 60]
    carrier_domain: procedure
    carrier_slot: procedure.repair.prescribed.completed
    rule_basis_refs:
      - "MBIS COP 2023 §2.1.3(r) - BA submission deadline (text wording PENDING_RULECARD_TEAM_COP_VERIFICATION)"
    rule_card_threshold: PENDING_RULECARD_TEAM_COP_VERIFICATION
    semantic_note: |
      prescribed repair completion 后，completion report / MBI4 提交 BA 的 duration.
      完工后整理测试记录、相片、签署和 completion package 常在 5-14 days；
      大型修葺或记录滞后可到 15-30 days.
    recommended_distribution: rounded_truncated_normal
    recommended_mean: 10.5
    recommended_sigma: 5.0
    typical_bounds: [0, 35]
    distribution_source: proagent_engineering_estimate_current_authority_round5_2026_05_10
```

**用户硬约束**（不得违反）：W0 端**只动 sidecar distribution**，**不动 rule_card threshold 数字**——`rule_card_threshold` 字段标 `PENDING_RULECARD_TEAM_COP_VERIFICATION`；rule_card team 跟进 3 个动作（改 measure_key / 补 to_ba rule / 停老 aggregate）**不在 sub-task 5 范围**。`carrier_slot` 必须先在 `sidecar_ownership_registry` 注册（spec 03 §3 cross-registry consistency）：`artifact.report_completion_or_mbi4.submitted_to_ba` 已加入 ownership_map。

---

### 4.6 `material_system_registry`（T-06 派活全量补述，2026-05-06）

授权：`杂物箱/文件包/T-06_material_system_registry_proagent/回复.md`（pro 给的 50 条 entry 全表 + 11 material_class 枚举 + 8 个 defect_class 拓展候选）。

**Schema**：

```yaml
material_system_registry:
  primary_key: material_system   # str, e.g. "reinforced_concrete"
  required_fields:
    - material_class             # enum，见下方 material_class 枚举表
    - supports_rebar             # bool — 是否承载钢筋（concrete 类内的 reinforced/prestressed/precast = true，其他都 false）
    - supports_finish_layer      # bool — 是否可作为饰面层载体
    - compatible_defect_classes  # list[str] — 该 material 可能产生的 defect class（来源：defect_condition_taxonomy_registry primary_key）
    - aliases                    # list[str] — legacy 名 / 同义词
  extension_fields:
    - notes                      # str — 法规章节引用 + 使用场景说明
```

**material_class 枚举**（11 类，T-06 段 2）：

| material_class | entries 数 | 说明 |
|---|---|---|
| `concrete` | 4 | reinforced_concrete / plain_concrete / prestressed_concrete / precast_concrete（含钢筋的 supports_rebar=true）|
| `masonry` | 3 | clay_brick / concrete_block / stone_masonry |
| `structural_steel` | 3 | structural_steel_section / steel_transfer_beam / cold_formed_steel |
| `metal_generic` | 3 | metal_anchor_fastener / metal_louver_fin / metal（legacy）|
| `timber_composite` | 2 | timber / composite_material |
| `finish` | 5 | plaster_finish / masonry_plaster / polymer_render / tile_finish / paint_coating（supports_finish_layer=true）|
| `cladding_glazing` | 5 | stone_cladding / curtain_wall_glazing / aluminium_panel_cladding / gfrc_panel / glass_balustrade_panel |
| `window_door` | 6 | aluminium_window / upvc_window / timber_window / steel_window / curtain_wall_aluminium_frame / metal_gate |
| `fire_safety` | 5 | steel_fire_doors / fire_resistant_glass_door / fire_rated_glass / fire_resistant_partition_wall / intumescent_coating |
| `drainage_pipe` | 8 | upvc_drainage / pvc / cast_iron / concrete_drain / hdpe_pipe / vitrified_clay_pipe / galvanized_steel_pipe / stainless_steel_pipe |
| `waterproofing_repair` | 5 | bituminous_membrane / pu_waterproof_coating / epoxy_resin_repair / silicone_sealant / cementitious_patch_mortar |
| `unknown` | 1 | unknown_material（fallback，不假设任何 defect 兼容）|
| **合计** | **50** | — |

**代表性 entry 示例**（每 material_class 取 1）：

```yaml
material_system_registry:

  # concrete 类（结构核心）
  reinforced_concrete:
    material_class: concrete
    supports_rebar: true
    supports_finish_layer: false
    compatible_defect_classes:
      - DC_CRACK
      - DC_MOISTURE_STAINING
      - DC_LEAKAGE
      - DC_SPALL_REBAR
      - DC_HOLLOWING
      - DC_DETACHMENT
    aliases: [rc, r.c., reinforced_cement_concrete]
    notes: "MBIS §3.4.2(A), §4.3, §5.4.1, Appendix 5"

  # masonry 类
  clay_brick:
    material_class: masonry
    supports_rebar: false
    supports_finish_layer: false
    compatible_defect_classes: [DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT, DC_LOOSE_FIXING]
    aliases: [brick, burnt_clay_brick]
    notes: "MBIS §5.4.3"

  # finish 类
  plaster_finish:
    material_class: finish
    supports_rebar: false
    supports_finish_layer: true
    compatible_defect_classes: [DC_CRACK, DC_HOLLOWING, DC_DETACHMENT, DC_MOISTURE_STAINING]
    aliases: [plaster, cement_plaster, rendering]
    notes: "MBIS §3.3.2(B), App 4 §1.3"

  # drainage_pipe 类
  cast_iron:
    material_class: drainage_pipe
    supports_rebar: false
    supports_finish_layer: false
    compatible_defect_classes: [DC_DRAINAGE_LEAKAGE, DC_DRAINAGE_BLOCKAGE, DC_METAL_CORROSION]
    aliases: [ci, cast_iron_pipe]
    notes: "MBIS §3.6 drainage; cast iron 排水立管/支管常见"

  # fire_safety 类
  steel_fire_doors:
    material_class: fire_safety
    supports_rebar: false
    supports_finish_layer: false
    compatible_defect_classes: [DC_FIRE_DOOR_DEFICIENCY, DC_METAL_CORROSION, DC_FASTENER_MISSING_OR_DEFECTIVE]
    aliases: [steel_fire_door, fire_rated_steel_door]
    notes: "MBIS §3.7 / §5.4.2; 防火门主要材料"

  # unknown 类
  unknown_material:
    material_class: unknown
    supports_rebar: false
    supports_finish_layer: false
    compatible_defect_classes: []   # 不假设
    aliases: [unknown, unspecified_material, material_unknown]
    notes: "fallback；不主动触发 defect compatibility"
```

**全 50 条 entry 见**：`11_registry_entries_inventory.md` §2.2 + T-06 派活 `回复.md` 段 1（L5-L767 完整 yaml）。

---

### 4.7 `defect_condition_taxonomy_registry`（T-06 拓展 8 条，2026-05-06）

授权：`杂物箱/文件包/T-06_material_system_registry_proagent/回复.md` 段 3 (L872-L890)。

**T-06 拓展 8 条**（5 新增 + 3 合并候选）—— 用于补齐 MBIS 法规边界（spec 08 §2.2 canonical 14 条不在此列表，见 `11_registry_entries_inventory.md` §2.1）：

**新增 5 条**（spec 08 §2.2 没列，但 MBIS 法规原文支持，T-06 派活补齐）：

```yaml
defect_condition_taxonomy_registry:

  DC_METAL_CORROSION:
    aliases: [metal_corrosion, rusting, steel_corrosion]
    severity_model: corrosion_chain
    default_measurement_slots: [ratio.rebar.section_loss]
    compatible_components: [structural_member, drainage_stack, signboard, canopy, fire_door, access_panel]
    compatible_mechanisms: [corrosion_spall]
    notes: "MBIS §3.3.2(C)-(I), §3.4.2(A), §4.3.1, §5.4.2, §3.6.2 — 金属构件锈蚀"

  DC_SEALANT_FAILURE:
    aliases: [sealant_failure, joint_seal_defect]
    severity_model: workmanship_chain
    default_measurement_slots: [length.crack.opening]
    compatible_components: [external_wall, signboard, canopy]
    compatible_mechanisms: [workmanship_deficit]
    notes: "MBIS §3.3.2(C)/(E)/(G), MWIS §10.5 / §11.1.10"

  DC_GLASS_BREAKAGE:
    aliases: [glass_breakage, broken_glass_pane]
    severity_model: workmanship_chain
    default_measurement_slots: [count.glass_pane.broken]
    compatible_components: [signboard, balcony_slab, fire_door, window_assembly]
    compatible_mechanisms: [workmanship_deficit]
    notes: "MBIS §3.3.2(E)/(G), §3.5.2(D), MWIS §11.1.2"

  DC_DEFORMATION_DISPLACEMENT:
    aliases: [deformation_displacement, deflection, misalignment]
    severity_model: structural_chain
    default_measurement_slots: [length.crack.opening, ratio.fsp.structural_performance]
    compatible_components: [structural_member, balcony_slab, signboard, drainage_stack, window_assembly]
    compatible_mechanisms: [load_crack, restraint_crack]
    notes: "MBIS §3.4.2(A), §3.6.2, MWIS §10.6 — 变形/位移/弯曲"

  DC_FIRE_PROTECTION_COATING_DEFICIENCY:
    aliases: [fire_protection_coating_deficiency, intumescent_failure]
    severity_model: fire_safety_chain
    default_measurement_slots: [length.coating.thickness.deficit]
    compatible_components: [structural_member, fire_resisting_wall]
    compatible_mechanisms: [fire_safety_deficiency]
    notes: "MBIS §5.4.2(C), §5.5.3 — 防火涂层失效"
```

**合并候选 3 条**（T-06 建议作为 alias 合并到已有 canonical DC_*，写进 `aliases` 字段）：

- `DC_WATERPROOFING_FAILURE` → alias of `DC_LEAKAGE`（MBIS §3.4.2(B), Appendix 5 — 防水层老化/破损/搭接失败导致渗水）
- `DC_MASONRY_SULFATE_ATTACK` → alias of `DC_DETACHMENT`（MBIS §5.4.3 — 砌石/砌砖硫酸盐侵蚀致砂浆层膨胀）
- `DC_FASTENER_MISSING_OR_DEFECTIVE` → alias of `DC_LOOSE_FIXING`（MBIS §3.3.2(E)-(I), §5.3.7, §5.6.4, MWIS §11.1.4-§11.1.9 — 螺丝/铆钉/锚栓缺漏或欠妥）

**全 19 条 entry**（14 canonical + 5 新增）+ 别名映射见：`11_registry_entries_inventory.md` §2.1。

---

### 4.8 `building_template_registry`（T-30 派活全量补述，2026-05-12）

授权：`杂物箱/文件包/T-30_building_template_registry_proagent/回复.md`（pro 给的 15 条 HK archetypal building 全量 entry + 5 条旧 BT_* 迁移声明 + component_graph_template_ids 决策）。

**Schema**：

```yaml
building_template_registry:
  primary_key: building_template_id   # str, 命名 BT_HK_<ARCHETYPE>_<STRUCTURE>_V1
  required_fields:
    - building_use                    # enum: residential / commercial / composite / industrial / institutional
    - structure_type                  # enum: rc_frame / rc_wall / masonry / steel / composite_structure
    - storey_count_range              # [int, int] — HK 楼宇实际形态有锚点（非 [1,100] 万能值）
    - primary_materials               # list[str] — 必须来自 material_system_registry 50 条主键
    - component_graph_template_ids    # list[str] — 当前全 `[]`（无独立 component_graph_template_registry，按 pro 决策选项 a 保守留空）
  extension_fields:
    - notes                           # str — MBIS 法规章节 + HK archetype 描述
```

**15 条 entry 按 use × structure_type 矩阵分布**（pro 段 2）：

| 类别 | entry 数 | 代表 |
|---|---|---|
| `residential` | 5 | 唐楼 (masonry) / 旧 walk-up (rc_frame) / 公屋公居 (rc_wall) / 私人塔楼 (rc_frame) / 村屋 (rc_frame) |
| `composite` | 4 | 混合用途高层 / 裙楼排水 / 沿海塔楼 / UBW-prone 旧楼 |
| `commercial` | 3 | 幕墙办公 (steel) / 转移板办公 (composite_structure) / 商场街市裙楼 |
| `industrial` | 2 | RC 工厂 / 钢仓库 |
| `institutional` | 1 | 校舍 / 医疗 / 政府办公 |

**代表性 entry 示例**（每 building_use 取 1）：

```yaml
building_template_registry:

  # residential
  BT_HK_PRIVATE_RESIDENTIAL_TOWER_RC_V1:
    building_use: residential
    structure_type: rc_frame
    storey_count_range: [20, 70]
    primary_materials: [reinforced_concrete, plaster_finish, aluminium_window, upvc_drainage, steel_fire_doors]
    component_graph_template_ids: []
    notes: "MBIS §1.3, §3.3, §3.4, §3.5, §3.6；现代私人住宅塔楼，覆盖外墙、悬挑构件、结构构件、防火门及竖向排水系统。"

  # composite
  BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1:
    building_use: composite
    structure_type: rc_frame
    storey_count_range: [3, 18]
    primary_materials: [reinforced_concrete, upvc_drainage, cast_iron, concrete_drain, metal_gate]
    component_graph_template_ids: []
    notes: "MBIS §3.6.1, §3.6.2, §5.6.1-§5.6.5；含平台、后巷、服务管槽及公用排水接驳的裙楼/综合体，覆盖 D2 排水主导场景。"

  # commercial
  BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1:
    building_use: commercial
    structure_type: composite_structure
    storey_count_range: [20, 65]
    primary_materials: [reinforced_concrete, prestressed_concrete, steel_transfer_beam, cementitious_patch_mortar, epoxy_resin_repair]
    component_graph_template_ids: []
    notes: "MBIS §3.4.1, §3.4.2(C), §4.3, §5.4.1, Appendix 5；含转移板/转移梁的商业或办公塔楼，覆盖结构评估、修葺及验证测试场景。"

  # industrial
  BT_HK_WAREHOUSE_LOGISTICS_STEEL_V1:
    building_use: industrial
    structure_type: steel
    storey_count_range: [1, 8]
    primary_materials: [structural_steel_section, intumescent_coating, metal, galvanized_steel_pipe, metal_gate]
    component_graph_template_ids: []
    notes: "MBIS §3.4.1, §3.4.2(A), §3.5, §5.4.2；低层仓库/物流中心，覆盖结构钢、金属围护、消防保护及大型金属闸。"

  # institutional
  BT_HK_INSTITUTIONAL_RC_BLOCK_V1:
    building_use: institutional
    structure_type: rc_frame
    storey_count_range: [3, 25]
    primary_materials: [reinforced_concrete, plaster_finish, steel_fire_doors, fire_resistant_partition_wall, upvc_drainage]
    component_graph_template_ids: []
    notes: "MBIS §1.3, §3.1.2, §3.4, §3.5, §3.6；校舍、医疗、政府或机构楼宇，覆盖公用部分、结构构件、防火分区、逃生楼梯及排水系统。"
```

**全 15 条 entry + 迁移声明**（旧 5 条 BT_* → 新 5 条 BT_HK_* 1:1 映射 + 9 条 fragment_template 外键迁移建议）见：`11_registry_entries_inventory.md` §1.1 + `T-30_building_template_registry_proagent/回复.md` 段 1-3。

**component_graph_template_ids 决策**（pro 段 4 选项 a）：当前 W0 无独立 `component_graph_template_registry`，component graph 由 `component_type_registry` + `fragment_template_registry` 隐式表达；本表不抢先定义未存在的外键，全 entry 保留 `[]`。未来如增设 graph 表，可按 `CG_HK_<ARCHETYPE>_<DOMAIN>_V1` 命名。

---
