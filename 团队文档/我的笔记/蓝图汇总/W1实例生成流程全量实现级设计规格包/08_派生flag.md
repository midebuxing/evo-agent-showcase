# Step 9 派生 Flag

> 跨包权威源与负向不变量见：`../_封口总则_字段权威源与负向不变量.md`。如本章与总则冲突，以总则和字段所属包权威章节为准。


W1 Step 9 `derive_risk_repair_verification_flags` 派生的 derived flags 集合。本节是 W0 spec 06 §11.X derived flag table 在 W1 阶段的合约整理 + 派生顺序细化。

## 1. 派生 flag 完整清单（9 条）

按 W0 spec 06 §11.X derived flag table（line 705-713）：

| Derived flag | input | 触发条件 | unknown_policy |
|---|---|---|---|
| `verification_test_failed` | test strength / rate / count | below proxy threshold | no test → `not_applicable` |
| `assessment_fsp_below_required_safety` | fsp ratio | `fsp < fsp_floor_proxy` | no assessment → `not_applicable` |
| `drainage_misconnection_present` | `DrainageState.connection_state` | `connection_state = misconnected` | no drainage → `not_applicable` |
| `ubw_present` | `UBWState.alteration_type` + `status_proxy` | `alteration_type != none AND authorization_status_proxy = unauthorized_like` | no UBW carrier → `false` |
| `subdivided_unit_sign_present` | `UBWState.subdivided_unit_sign_present` | `true` | no private premises → `not_applicable` |
| `fire_safety_deficiency_present` | `FireSafetyState.deficiency_present` | `true` | no fire component → `not_applicable` |
| `coverage_insufficient` | covered / inspected ratios | `reported_ratio < coverage_floor_proxy=0.35`（DEBT-013 closure）| no scope target → `not_applicable` |
| `defect_cause_or_extent_uncertain` | `ConditionState.uncertainty_flag` | `true` | default `false` |
| `family_uncovered` | projection selected unknown | `selected_family = unknown` | **属 法规映射层不在 W1**（projection layer flag）|

注：`family_uncovered` 实际是 法规映射层 flag，在 W1 不派生。

注：`verification_test_failed` 的 `failure_rule` 评估契约权威在 W0 spec 03 §2.4.1——W1 阶段 code 仅对 `VT_PULL_TEST_EXTERNAL_V1` 结构化求值，其余 test family `failure_rule` 求值是实现 follow-up（详见 §2 step 6）。

## 2. 派生顺序

按 a12 §13.1 派生顺序 + W0 spec 04 §17 derived_outcomes 字段：

```text
Step 9 派生顺序（建议串行执行）：

  1. coverage_insufficient
     └── 输入：W1 Step 6 输出的 ratio.covered_area.inspected / ratio.external_wall_area.inspected
     └── 阈值：coverage_floor_proxy = 0.35（DEBT-013 closure 2026-05-08）

  2. defect_cause_or_extent_uncertain
     └── 输入：W1 Step 2 输出的 ConditionState.uncertainty_flag

  3. drainage_misconnection_present
     └── 输入：W1 Step 3 输出的 DrainageState.connection_state

  4. ubw_present + subdivided_unit_sign_present
     └── 输入：W1 Step 4 输出的 UBWState

  5. fire_safety_deficiency_present
     └── 输入：W1 Step 5 输出的 FireSafetyState

  6. verification_test_failed
     └── 输入：W1 Step 7 输出的 technical_validation MeasurementRecord
     └── 阈值：verification_test_registry.failure_rule
     └── failure_rule 评估契约权威在 W0 spec 03 §2.4.1（free-text 形态 + 评估契约）。
         W1 阶段 code 现状：仅 VT_PULL_TEST_EXTERNAL_V1 的 failure_rule 走结构化求值
         （strength.pull_test.reported < stress.pull_test.minimum or repair_quality_index < 0.45），
         其余 test family 的 failure_rule 求值待后续按 test method 物理语义补全——
         这属实现 follow-up（W0 spec 03 §2.4.1 line 84 明文授权），不是 spec 缺陷。
         其他 family 当前回退 RepairAssessmentState bootstrap 输入，输出仍是 bool（非 silent drop）。

  7. assessment_fsp_below_required_safety
     └── 输入：W1 Step 8 输出的 ratio.fsp.structural_performance
     └── 阈值：fsp_floor_proxy（spec 06 §10 surrogate floor）

  8. risk_building_safety_emergency
     └── 输入：ConditionState (5 类 DC) + structural severity
     └── 详见 risk_derivation_registry::RISK_BUILDING_SAFETY_EMERGENCY_V1

  9. risk_public_health_emergency
     └── 输入：DrainageState (3 类 DC)
     └── 详见 risk_derivation_registry::RISK_PUBLIC_HEALTH_DRAINAGE_V1

  10. risk_public_danger_present
      └── 输入：ConditionState + UBWState + FireSafetyState (含 DC_DETACHMENT / DC_GLASS_BREAKAGE / DC_FIRE_DOOR_DEFICIENCY)
      └── 详见 risk_derivation_registry::RISK_PUBLIC_DANGER_UBW_V1

  11. repair_required
      └── 输入：risk_building_safety_emergency / risk_public_danger_present / verification_test_failed
      └── 详见 repair_outcome_registry::RO_REPAIR_REQUIRED_V1

  12. repair_outcome_safe_until_next_cycle
      └── 输入：risk_building_safety_emergency / verification_test_failed
      └── 详见 repair_outcome_registry::RO_SAFE_UNTIL_NEXT_CYCLE_V1

  13. maintenance_pre_next_cycle_required
      └── 输入：routine （no risk input；详见 repair_outcome_registry::RO_PRE_NEXT_CYCLE_MAINTENANCE_V1）
```

## 3. 派生标志数据归属（W0 资源 cross-ref）

派生标志按业务语义归属分两类存放（按 W0 规格 02 §1.1 派生风险域职责边界，2026-05-13 加）：

### A. 综合派生类（6 个，risk / repair 标志）— 数据存放 W0 派生风险域注册表

依赖多个业务核心层 + 多个测量 / 条件作输入做复合判定的标志：

- `risk_derivation_registry` 3 条条目（详见 W0 规格 11_inventory §5.1）
  - `risk.building_safety.emergency`
  - `risk.public_health.emergency`
  - `risk.public_danger.present`
- `repair_outcome_registry` 3 条条目（详见 W0 规格 11_inventory §5.2）
  - `repair.required`
  - `repair.outcome.safe_until_next_cycle`
  - `maintenance.pre_next_cycle.required`

字段定义见 W0 规格 04 字段合约 + 规格 03 §2.4 + 规格 11_inventory §5。

### B. 业务核心层直通类（8 个）— 数据存放各业务核心层 State 字段 + 派生规则在规格 06 §11 文档描述

单业务核心层内部派生的标志，无综合阈值 / 多输入逻辑：

| 标志 | 业务核心层 | 数据所在 State 字段 |
|---|---|---|
| `drainage.misconnection.present` | 排水核心 | `DrainageState.connection_state` |
| `ubw.present` | 僭建核心 | `UBWState.alteration_type` + `authorization_status_proxy` |
| `subdivided_unit_sign.present` | 僭建核心 | `UBWState.subdivided_unit_sign_present` |
| `fire_safety.deficiency.present` | 消防核心 | `FireSafetyState.deficiency_present` |
| `verification.test.failed` | 测量域 | 测试强度 / 比率 / 计数 vs 代理阈值（规格 06 §11 描述）|
| `assessment.fsp.below_required_safety` | 测量域 | `fsp_structural_performance_ratio` vs `fsp_floor_proxy`（规格 06 §11 描述）|
| `coverage.insufficient` | 测量域 | covered / inspected 比例 vs `coverage_floor_proxy`（规格 06 §11 描述）|
| `defect.cause_or_extent.uncertain` | 条件核心 | `ConditionState.uncertainty_flag` |

派生规则全表见 W0 规格 06 §11；法规消费契约见 W0 规格 08 normative_projection 章节。

### 拆分原则来源

a12 §13.2 派生标志表格的"依赖层"列隐含给出此业务语义归属拆分 —— 综合派生类依赖多个核心层 + 派生层综合判定，业务直通类依赖单一业务核心层内部字段。W0 规格 02 §1.1 把这条隐含原则明示出来，W1 引用。两类标志最终都被法规映射层 projection executor 消费（按 `normative_projection_registry::required_world_core_slots` 字段引用），消费方相同，存放方式按业务语义分。

## 4. T-06 拓展条目对派生 flag 的影响

T-06 派活拓展的 5 条新增 `DC_*`（DC_METAL_CORROSION / DC_SEALANT_FAILURE / DC_GLASS_BREAKAGE / DC_DEFORMATION_DISPLACEMENT / DC_FIRE_PROTECTION_COATING_DEFICIENCY）部分作为 risk 派生输入：

- `risk.building_safety.emergency` 输入加了 `DC_DEFORMATION_DISPLACEMENT`
- `risk.public_danger.present` 输入加了 `DC_GLASS_BREAKAGE`

详见 W0 spec 11_inventory §5.1 + spec 03 §4.7 T-06 拓展 entry。

## 5. derived flag 输出去向

W1 Step 9 派生 flag 写入 `WorldBundle`：

- 按 W0 spec 04 §1.1.10-§1.1.13 字段合约（DrainageState / UBWState / FireSafetyState / RepairAssessmentState）+ `WorldBundle.derived_outcomes` 字段
- 写出后由 法规映射层 Step 10 projection executor 读（按 `normative_projection_registry::required_world_core_slots` 字段引用）

## 6. 来源

- W0 spec 06 §11.X derived flag table（line 705-713）
- a12 §13.1 派生顺序 + §13.2 Derived flags
- W0 spec 11_inventory §5.1 risk_derivation / §5.2 repair_outcome 全 entry
- T-06 拓展 trace（W0 spec 03 §4.7 + 11_inventory §2.1）
- DEBT-013 closure 2026-05-08 coverage_floor_proxy=0.35
- DEBT-012 closure 2026-05-12 public_health_risk_index 走 DrainageState 不走 measurement_map
