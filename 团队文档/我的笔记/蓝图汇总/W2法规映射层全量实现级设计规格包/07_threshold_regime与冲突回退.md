# Threshold regime 与冲突回退

W2 法规映射层 phase 3 主循环对每个 fragment 评估 family 时，两件事并行：**(a) numeric / ordinal slot 走 5-bin threshold regime 评估生成 `ThresholdEval`**；**(b) 多 family 候选走 conflict_group 互斥规则解析单 family / multi family**。本章列两套机制的实施级合约 + 三条 P0/P3 输出契约约束（C023 / C024 / C025）的执行规则。

**与 W0 规格 06 §15 + W0 规格 07 §4 的关系**：W0 规格 06 §15 列 5-bin threshold regime 的核心 width 公式表（按 measurement_family 8 行），W0 规格 07 §4 列 family 互斥与冲突回退（按 conflict_group 4 组 + 5 种竞争处理）；本章按 W2 端 phase 3 执行顺序重新组织 + 补 W2 端约束 C023-C025 的强制检查点。W0 规格 06 / 07 物理迁出后留 stub 引本章。

**与本包其他章节的关系**：

- **`ThresholdEval` 字段合约**：详见 `09_输出契约_NormativeProjection.md` §3（W0 规格 04 §20 cross-ref）；本章不重写字段表
- **`unknown_reason_code` 13 枚举 + sidecar fallback**：详见 `08_unknown策略.md`；本章只在 §4 conflict 解析时引用 `multi_family_conflict`
- **`ReportBasisItem` 5 kind**：详见 `09_输出契约_NormativeProjection.md` §4；本章只在 §5 C025 约束引用

## 1. 5-bin threshold regime

按 W0 规格 06 §15 + a12 §11 + 勘探报告 §9.1：W2 phase 3 把每条 W0 measurement slot + sidecar 数值 slot 的测量值映射到 5-bin regime 之一，加 `not_numeric` 兜底共 **6 regime** 枚举。

### 1.1 6 regime 物理含义

| `regime_tag` | 物理含义 | 数值条件（按 `classify_threshold_regime` 实施版本，统一方向 `diff = observed - threshold`）|
|---|---|---|
| `far_below` | 测量值远低于阈值（差距超过 width）| `diff < 0` 且 `abs(diff) > width` |
| `near_below` | 测量值略低于阈值（差距 ≤ width）| `diff < 0` 且 `abs(diff) <= width` |
| `exact_threshold` | 测量值精确等于阈值 | `abs(observed - threshold) < EPS_EXACT`（float 路径）/ `int(round(obs)) == int(round(thr))`（integer_compare 路径）|
| `near_above` | 测量值略高于阈值（差距 ≤ width）| `diff > 0` 且 `diff <= width` |
| `far_above` | 测量值远高于阈值（差距超过 width）| `diff > 0` 且 `diff > width` |
| `not_numeric` | 非数值兜底 | measurement_family ∈ `{bool, boolean_assertion, enum, classification}` / 数值 coerce 失败 / operator ∈ `{in, not_in}` |

**a12 §11.1 旧伪代码 vs 代码实施方向差异**（按勘探报告 §12.3）：

- a12 §11.1 原文：`<= / <` 算 `value - threshold`，`>= / >` 算 `threshold - value`（方向标准化）
- 代码 `classify_threshold_regime`（L416-L465）：统一用 `obs_val - thr_val`，五档分支不翻转方向

两套规模化等价，叙述方向不同。**spec 优先**——本节按代码实施版本描述统一方向，a12 §11.1 出处行号引用但不复刻方向翻转细节。

### 1.2 关键不变量：`regime_tag` ≠ `pass_bool`

按 W0 规格 06 §15 line 1020 + a12 §11.1 line 1719-1722：`regime_tag` 跟 `pass_bool` **是两套独立维度**——

- **`regime_tag`** 描述测量值相对阈值的**位置**（5-bin + not_numeric）
- **`pass_bool`** 描述测量值是否**通过 operator 检验**
- 同一 `near_below` 在 `<=` 是 pass、在 `>=` 是 fail
- `exact_threshold` 是数值意义上"精确等"，**不是** pass/fail 判断
- 评估时两个维度分开派生：`regime_tag` 由 `classify_threshold_regime` 派生，`pass_bool` 由 `_evaluate_threshold_operator` 派生

详细 operator 8 项求值表见 `09_输出契约_NormativeProjection.md` §3.2 + W2 规格 04 §5 `evaluate_fragment_projection_candidates` 实施卡。

### 1.3 EPS_EXACT 浮点精度

按 a12 §11.3 + W0 规格 06 §15 line 1033：

| 路径 | EPS 规则 |
|---|---|
| 浮点（float）| `abs(observed - threshold) < 1e-9`（即 `_EXACT_THRESHOLD_EPSILON = 1e-9`，按 a12 §11.3 + 代码 L308 实施一致）|
| reported_measurement | rounding 后精确等（按 W0 规格 06 §13 三档 precision rounding） |
| 整数（integer_compare=True）| `int(round(obs)) == int(round(thr))` |

## 2. width 公式（每 measurement_family）

按 W0 规格 06 §15 line 1022-1030 + a12 §11.2 + 勘探报告 §9.1.2：`near_below` / `near_above` 半宽 width 按 measurement_family 派生。W2 端按 **family 表 hit 优先 → unit 推断 fallback → 兜底 0** 三档路由（`compute_threshold_width` 实施 L346-L403）。

### 2.1 spec-side family 表（a12 §11.2 字面）

| measurement_family | width 公式 | 默认值 |
|---|---|---|
| `geometry_length` / `geometry_width` / `geometry_depth` | `max(abs_min, 0.10 * threshold)` | `abs_min=0.05mm`（按 slot_unit）或 `0.01m`（按 slot_unit），`rel=0.10` |
| `geometry_area` | `max(0.01m², 0.20 * threshold)` | 例 spall `0.01m²` |
| `ratio` | `max(0.02, 0.10 * threshold)` | 0.02 |
| `count` | 固定 `1` | ±1 count |
| `rate` | `max(0.1, 0.10 * threshold)` | family-specific |
| `stress` | `max(1.0, 0.05 * threshold)` | unit-specific |
| `bool` / `boolean_assertion` | `not_numeric`（不参与数值分箱）| 0 |
| `enum` / `classification` | `not_numeric`（不参与数值分箱）| 0 |

### 2.2 实现侧近似不构成 spec 权威

width 公式以本章 spec-side 表为准。实现侧若有 unit fallback 或工程近似，不构成 spec 权威源，不能反向改变 threshold regime 语义.


### 2.3 width 公式来源 + spec ↔ code 一致性

| 公式段 | spec 来源 | code 实施位置 |
|---|---|---|
| §2.1 family 表 | W0 规格 06 §15 line 1022-1030 + a12 §11.2 | `compute_threshold_width` L346-L403 family 分支 |
| §2.2 unit fallback | DEBT-026 closure 2026-05-08（spec ↔ code 一致）| `_width_from_unit` L311-L343 |
| EPS_EXACT | a12 §11.3 + W0 规格 06 §15 line 1033 | `_EXACT_THRESHOLD_EPSILON = 1e-9` L308 |

spec ↔ code 一致：本节内容 spec 期望跟代码实施 1:1 对齐，无 gap。

## 3. ThresholdEval 字段合约

`ThresholdEval` 是 W2 phase 3 H5 `build_threshold_evaluation` 的输出，是 `ProjectionFamilyEval.threshold_evaluations` 内项的 dataclass。

**字段合约**详见 `09_输出契约_NormativeProjection.md` §3.1（按 W0 规格 04 §20 锚定，本章不重写字段表）。

**关键字段联动**：

- `regime_tag` 由 `classify_threshold_regime(observed, threshold, measurement_family, slot_unit, integer_compare)` 派生
- `pass_bool` 由 `_evaluate_threshold_operator(operator, observed, threshold, integer_compare)` 派生
- `slot_id` 是 W0 端 measurement / sidecar measurement slot_id（rule_card 端 `measure_key` 通过 `projection_runtime_mapping_v1.json::measure_aliases` 翻译为 W0 slot_id 后填入此字段）
- `rule_id` 是 rule_card v2 `rule_card_id`（从 `find_thresholds_for_slot_any_family` 返回的 `Threshold.rule_card_id` 取）

## 4. Family 互斥与冲突回退

按 W0 规格 07 §4 + a12 §11.4 + 现役代码 `regulation_projection_executor.py::CONFLICT_GROUPS`（L37-L70）+ `resolve_family_conflict`（L76-L137）：W2 phase 3 H3 `resolve_family_conflict` 处理多 family 竞争。

### 4.1 4 个 conflict_group 定义

按 W0 规格 07 §4.1 line 83-88：

| `conflict_group` | members | selector | 业务语义 |
|---|---|---|---|
| `structural_external_surface` | `crack` / `spall_rebar` / `hollowing_delamination` / `detachment` / `moisture_seepage` | `highest_applicability_score_with_required_slots` | 外构件结构表面 5 种 mechanism 互斥（单 mechanism 主导 + applicability 最高者赢）|
| `drainage` | `drainage_blockage` / `drainage_leakage` / `drainage_misconnection` | `allow_multi_if_distinct_segment_else_highest_risk` | 排水缺陷允许同时 multi-family 投影（distinct segment 时），否则按风险最高 |
| `ubw_fire` | `ubw_alteration` / `fire_safety_deficiency` | `allow_multi_if_distinct_component_else_highest_risk` | 违建 + 消防允许同时 multi-family 投影（distinct component 时），否则按风险最高 |
| `assessment_repair` | `structural_assessment_deficit` / `repair_validation_failure` | `allow_multi_if_causal_chain` | 评估 + 修葺验证允许同时 multi-family 投影（因果链关联时）|

### 4.2 16 family ↔ conflict_group 映射（spec 优先 + 16 family 锚定）

按本包 `06_canonical_slots与projection_binding.md` §2 + W0 规格 11 §4.4：

| baseline family | 关联 conflict_group | spec ↔ spec 校准点 |
|---|---|---|
| `mbis.inspection.external_components` | `structural_external_surface` | — |
| `mbis.inspection.structural_components` | `structural_external_surface` | — |
| `mbis.inspection.drainage` | `drainage` | — |
| `mbis.inspection.fire_safety` | `ubw_fire` | **校准点**——baseline 独立 family 跟 `mbis.inspection.ubw` 共属一个 conflict_group `ubw_fire`，按业务允许同时投影（distinct component 时）|
| `mbis.inspection.ubw` | `ubw_fire` | **校准点**——同上；当前 W0 spec 11 §4.4 `NP_UBW_FIRE_V1` 合并 record 是 spec ↔ spec 错位（DEBT-031 gap 6 衍生修法①待补独立 records）|
| `mbis.investigation.gate_and_proposal` | （不在 4 conflict_group 内）| 单独 family，不涉及互斥 |
| `mbis.investigation.structural_assessment_fsp` | `assessment_repair` | **校准点**——baseline 独立 family（DEBT-031 gap 6 衍生修法②待补 record），与 `mbis.repair.external_structural_validation` 共属 `assessment_repair` 因果链 |
| `mbis.repair.general_selection_and_classification` | （不在 4 conflict_group 内）| 单独 family（DEBT-031 gap 6 衍生修法②待补 record）|
| `mbis.repair.external_structural_validation` | `assessment_repair` | — |
| `mbis.repair.fire_safety_and_drainage` | （不在 4 conflict_group 内）| 单独 family；不跟 `mbis.inspection.fire_safety` / `mbis.inspection.drainage` 共属 conflict_group（业务阶段不同：inspection vs repair）|
| `mbis.supervision.ri_minimum_and_site_controls` | （不在 4 conflict_group 内）| 单独 family |
| `mbis.supervision.rc_controls` | （不在 4 conflict_group 内）| 单独 family |
| `mbis.reporting.inspection_report` | （不在 4 conflict_group 内）| 单独 family |
| `mbis.reporting.completion_report` | （不在 4 conflict_group 内）| 单独 family |
| `mbis.scope.coverage_and_preinspection` | （不在 4 conflict_group 内）| 单独 family |
| `mbis.procedure.ri_notifications_and_submissions` | （不在 4 conflict_group 内）| 单独 family |

**校准说明**：上表 3 个"校准点"是 spec ↔ spec 校准点，按用户 2026-05-13 决策甲方案（维持 16 family）+ 按业务允许 conflict_group 跨独立 family（如 `ubw_fire` conflict_group 含 baseline 独立 2 family `mbis.inspection.fire_safety` + `mbis.inspection.ubw`）；W2 spec 包闭环后子代理触发 W0 spec 11 修订封口任务拆 `NP_UBW_FIRE_V1` 为独立 records，但 `conflict_group` 字段仍同时填 `ubw_fire`。

### 4.3 5 种多 family 竞争处理

按 W0 规格 07 §4.2 line 92-99：

| 情况 | 处理 | 出现的代码分支 |
|---|---|---|
| 1. no known family applicable | `selected_family_ids = []` + reason `no_known_family_match` | `resolve_family_conflict` 行 1-2（candidates 空 / required_slots_present 全 False）|
| 2. exactly one applicable in conflict group | `selected_family_ids = [<that family>]` + reason None | `resolve_family_conflict` 行 3（applicable 长度 1）|
| 3. multiple applicable + distinct target components | allow multi-family projection；`selected_family_ids = [<all>]` + reason None | `resolve_family_conflict` 行 4-5（distinct target + conflict_group ∈ {drainage / ubw_fire / assessment_repair}）|
| 4. one family is strict parent of other | select child family；`selected_family_ids = [<child>]` + reason None | `_find_parent_child_pair` 当前返回 None（family hierarchy 后续封口任务填表，placeholder）|
| 5. same group cannot resolve | `selected_family_ids = []` + reason `multi_family_conflict`；structural_external_surface 例外走 `highest_applicability_score` 降级 fallback | `resolve_family_conflict` 行 6-7（structural_external_surface fallback）+ 行 8（兜底） |

### 4.4 selector 详细语义

按 §4.1 4 selector 各自的物理判定：

- **`highest_applicability_score_with_required_slots`**（`structural_external_surface`）：applicable list 按 `applicability_score` 降序排，取最高；`required_slots_present` 必须 True；多个 tie 时取首
- **`allow_multi_if_distinct_segment_else_highest_risk`**（`drainage`）：按 `target_component_id`（drainage segment）是否 distinct 决定 multi vs single；非 distinct 时按 risk 最高（业务上由 `applicability_score` 间接代表）
- **`allow_multi_if_distinct_component_else_highest_risk`**（`ubw_fire`）：同上，按 component 是否 distinct
- **`allow_multi_if_causal_chain`**（`assessment_repair`）：按 family 间是否存在因果链关联（如 assessment_deficit → repair_validation_failure）决定 multi vs single；当前 W2 simplified routing 跟 distinct target 等价处理（因果链 evaluator 后续封口任务）

## 5. W2 端约束 C023 / C024 / C025

按 W0 规格 07 §2 L57-L59（W2 物理迁出后 W0 留 stub）+ a12 §11.3-§11.5：W2 端 NormativeProjection 输出契约含 **3 条 P0/P3 强制约束**。

### 5.1 C023 `UNKNOWN_NO_RULE_IDS`【P3】

| 项 | 内容 |
|---|---|
| **断言** | `selected_family = unknown` 时 `ProjectionFamilyEval.rule_ids` 必须为空 list `[]` |
| **检查时机** | phase 3 构造 `ProjectionFamilyEval` 时（在 `build_normative_projections_for_world` 内 matched_families 构建段） |
| **触发优先级** | **P3 fallback**——unknown 状态 clear rule_ids（不 reject，按 spec 优先 fallback）|
| **物理含义** | unknown 状态不挂任何具体 rule_id，避免下游误以为 family 已 covered；保持 unknown 跟 known 输出语义清晰断开 |
| **触发场景** | family conflict 解析返回 `unknown_reason_code` 非空时，对应 ProjectionFamilyEval 的 `rule_ids` 应清空 |
| **来源** | W0 规格 07 §2 L57 + a12 §11.3 L1615-L1616 |

### 5.2 C024 `KNOWN_SINGLE_CONFLICT_GROUP`【P3】

| 项 | 内容 |
|---|---|
| **断言** | 同一 `conflict_group` 内不能多选 known family（除 conflict_group ∈ {`drainage`, `ubw_fire`, `assessment_repair`} 的 distinct target / causal_chain selector 特例 — 详见 §4.3 情况 3）|
| **检查时机** | phase 3 family conflict 解析时（H3 `resolve_family_conflict` 内部判断 distinct target / parent-child 时）|
| **触发优先级** | **P3 fallback**——同组多选触发 `conflict_reason = multi_family_conflict`；selector 允许 multi 的情况下不算违反 |
| **物理含义** | family 互斥规则的执行约束，确保 conflict_group 维度的输出一致；防止 spec 设计的互斥规则被 silent 绕过 |
| **触发场景** | `resolve_family_conflict` 行 8 兜底（同组 multiple applicable 但 selector 不允许 multi）|
| **来源** | W0 规格 07 §2 L58 + a12 §11.4 L1616-L1617 |

### 5.3 C025 `BASIS_NONEMPTY`【P0】

| 项 | 内容 |
|---|---|
| **断言** | `NormativeProjection.basis_items` 必须非空（1..N）|
| **检查时机** | phase 3 构造 `NormativeProjection` 时（输出前的 gate 检查）|
| **触发优先级** | **P0 reject projection**——basis_items 为空时该 NormativeProjection 输出失败 |
| **物理含义** | projection 的"参考真值"必须可追溯到具体依据（不接受空依据的 verdict 输出）；这是 HiddenGold 砍除后的替代约束——HiddenGold 砍后 basis_items 担当唯一可追溯依据 |
| **触发场景** | (a) `threshold_compare` basis 派生失败（无 threshold_evaluations 输出）；(b) `bool_assertion` basis 缺失；(c) `family_uncovered` basis 兜底未构造；(d) world_origin / measurement_origin basis 兜底未构造 |
| **basis 5 kind 要求** | 至少含一项 `threshold_compare` / `bool_assertion` / `family_uncovered` / `world_origin` / `measurement_origin`（5 kind 详见 `09_输出契约_NormativeProjection.md` §4）|
| **来源** | W0 规格 07 §2 L59 + a12 §11.5 L1617-L1618 |

### 5.4 已删除的 HiddenGold 相关约束

按 W0 规格 07 §3 + 用户原则 09.md L20-L25 + 用户 2026-05-13 D-2 决策：

- `C026_HIDDEN_GOLD_THIN_COPY` 已删除（HiddenGold 砍除后该约束失意义）
- 替代要求：C025 BASIS_NONEMPTY 必须满足（basis_items 不再复制到 HiddenGold，直接独立非空）

## 6. 封口正文边界

本章只定义 threshold regime、conflict group、C023-C025 的 spec 语义。历史实现侧状态、实现侧历史对照、工程推进路径不进入封口正文.


## 7. 来源

- 5-bin threshold regime 设计：W0 规格 06 §15 + a12 §11.1 / §11.3 + 勘探报告 §9.1
- width 公式按 measurement_family：W0 规格 06 §15 line 1022-1030 + a12 §11.2 + 勘探报告 §9.1.2
- code-side unit fallback：DEBT-026 closure 2026-05-08
- EPS_EXACT 浮点精度：a12 §11.3 + W0 规格 06 §15 line 1033
- `ThresholdEval` 字段合约 cross-ref：W0 规格 04 §20 + 本包 `09_输出契约_NormativeProjection.md` §3
- conflict_group 4 组 + selector：W0 规格 07 §4.1 + a12 §11.4 L1624-L1642
- 5 种多 family 竞争处理：W0 规格 07 §4.2 + a12 §11.4 L1644-L1659
- C023 / C024 / C025 三条约束：W0 规格 07 §2 L57-L59 + a12 §11.3-§11.5
- 16 family ↔ conflict_group 映射 spec ↔ spec 校准点：用户 2026-05-13 决策甲方案 + 本包 `06_canonical_slots与projection_binding.md` §2.2
- DEBT-031 gap 1 / gap 6 / gap 9：`团队文档/我的笔记/技术与研究债.md` DEBT-031 子表
