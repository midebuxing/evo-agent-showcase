# Surrogate、公式、噪声与 unknown 策略

## 0. 本文档层级归属

本文档覆盖两层内容：

1. **W0 静态资源层**：surrogate 公式（§1-§11）、噪声模型（§12-§14）、threshold regime（§15）— 静态资源定义，留本文件。
2. **法规映射层**：projection unknown reason codes（§16.3）、`not_applicable` 语义（§16.4）、sidecar 派生异常的 fallback 语义（§16.5）— 这些是 法规映射层在执行 projection 时的 fallback 输出，不是 W0 worldgen 本身输出。法规映射层 spec 包尚未建立（DEBT-018），暂留本文件。

**W1 实例生成层消费合约已迁出**（2026-05-12，DEBT-019 落地）：

| 本文件章节 | W1 包对应消费合约章节 |
|---|---|
| §12-§14 噪声模型（公式） | W1 spec [`06_测量噪声三层合约.md`](../W1实例生成流程全量实现级设计规格包/06_测量噪声三层合约.md) §1-§3 三层 + precision rounding + variance/offset/clip |
| §11.5 lognormal arithmetic_mean | W1 spec 06 §4 `mean_semantics` 三档 |
| §11.6 conditional formula evaluator | W1 spec 06 §6 sidecar 双路径 |
| §16.1-§16.2 worldgen-unknown 策略 | W1 spec [`07_约束与四级修复.md`](../W1实例生成流程全量实现级设计规格包/07_约束与四级修复.md) §5 P3 / not_applicable 边界 |

本文件 §1-§16 保留公式 / 模型本体；W1 阶段消费契约（三层 layer 划分 / precision 三档 / variance-offset-clip 三件 / distribution_source 4 层校准）见 W1 spec 06。

unknown 策略链条连续：W0 worldgen 生成 unknown subtype → 法规映射层 projection executor 读取该事实后执行 reason code 路由 → projection fallback。分开看会断链，所以法规映射层 unknown 策略（§16.3-§16.5）暂留本文件。

## 0.1 公式 fragment 物理上下文 reference-based contract

本文件 §3-§10.X 公式使用 fragment 维度的物理上下文（material_system / structural_role / cover_depth_mm / geometry / exposure / domain scope 等）时，按 spec 04 §7 `FragmentContext` 9 字段 reference-based contract（顶层封口总则 §2 line 27 背书）反查上游对象，**不**在 `FragmentContext` 自身扩 denormalized 物理 cache 字段。

引用约定（公式中出现的物理输入符号 → spec 自身 reference 反查路径）：

| 公式输入符号 | reference 反查路径 | 上游字段权威 |
|---|---|---|
| `cover_depth_mm` | `component = lookup_component(fragment.component_id); component.cover_depth_mm` | spec 04 §5 ComponentNode（RC-specific 物理参数，`material_system==reinforced_concrete` 时必填非 null）|
| `nominal_visible_area_m2` | `component.geometry_proxy.visible_area_m2` | spec 04 §5 ComponentNode `geometry_proxy` dict |
| `nominal_length_m` | spec 06 §3.2 crack surrogate / spec 06 §4 rebar/spall 公式：等价于 fragment 维度 `fragment.fragment_length_m`（spec 04 §7 9 字段之一） | spec 04 §7 FragmentContext |
| `material_system` | `component.material_system` | spec 04 §5 ComponentNode |
| `structural_role` | `component.structural_role` | spec 04 §5 ComponentNode |
| `has_rebar` | derive：`component.material_system == "reinforced_concrete"`（或 `component_type_registry[component.component_type].material_compatibility` 含 RC）；**不**作为独立字段 | spec 04 §5 ComponentNode + spec 03 §4.1 component_type_registry |
| `exposure_zone` | `location = lookup_location(component.location_id); location.exposure_zone` | spec 04 §6 LocationNode |
| `fragment_scope`（domain scope） | derive：`domain_of(component.component_type)`，通过 spec 03 §4.1 `component_type_registry[ct].allowed_mechanisms` 含 fire_safety_deficiency → fire_safety；含 drainage_* → drainage；含 structural mechanism → structural；外墙类 component_type → external 等；**不**作为独立字段 | spec 03 §4.1 component_type_registry |
| `surface_position` | `location.spatial_tags`（含 `facade / external_wall / roof / canopy` 等表面位置语义） | spec 04 §6 LocationNode `spatial_tags` |

公式正文为简洁起见保留物理输入符号名（如 `cover_depth_mm`），按本表读为 reference 反查结果；不要把这些符号误解为 `FragmentContext` 自身字段。

来源：spec 04 §7 reference-based contract + 顶层封口总则 §2 line 27（"`WorldBundle` / `BuildingContext` / `ComponentNode` / `LocationNode` / `FragmentContext` ... 字段权威源 spec 04 §§3-17"）。

## 1. 参数范围

### 1.1 Global configurable parameters

| 参数                             |           范围 |   默认值 | 依赖                   | source       | 来源                               |
| -------------------------------- | -------------: | -------: | ---------------------- | ------------ | ---------------------------------- |
| `severity_minor_max`           |  `[0.1,0.4]` | `0.33` | severity band          | expert_prior | `01_a12_权威旧蓝图.md`:L967-L980 |
| `severity_moderate_max`        | `[0.4,0.75]` | `0.66` | severity band          | expert_prior | 同上                               |
| `risk_emergency_threshold`     | `[0.7,0.95]` | `0.85` | risk flags             | expert_prior | 同上                               |
| `unknown_compatibility_max`    |  `[0.0,0.6]` | `0.45` | unknown fallback       | expert_prior | 同上                               |
| `geometry_noise_rel_default`   |   `[0,0.25]` | `0.08` | geometry measurement   | calibrated   | 同上                               |
| `coverage_noise_abs_default`   |   `[0,0.10]` | `0.03` | coverage measurement   | calibrated   | 同上                               |
| `technical_noise_rel_default`  |   `[0,0.20]` | `0.06` | validation measurement | calibrated   | 同上                               |
| `assessment_noise_rel_default` |   `[0,0.15]` | `0.05` | assessment measurement | calibrated   | 同上                               |
| `max_repair_iterations`        |     `[0,10]` |    `3` | constraint validator   | expert_prior | 同上                               |

### 1.2 Domain parameter groups

| Domain                | 参数                                   |           范围 |     默认 | 依赖                  | source          | 来源                               |
| --------------------- | -------------------------------------- | -------------: | -------: | --------------------- | --------------- | ---------------------------------- |
| structural / external | `k_crack_opening_scale`              |  `[0.1,3.0]` |  `1.2` | crack                 | physics_assumed | `01_a12_权威旧蓝图.md`:L983-L997 |
| structural / external | `k_spall_area_scale`                 | `[0.01,0.8]` | `0.18` | spall                 | physics_assumed | 同上                               |
| structural / external | `k_detachment_area_scale`            | `[0.01,0.8]` | `0.12` | detachment            | expert_prior    | 同上                               |
| drainage              | `k_blockage_from_maintenance`        |      `[0,2]` |  `0.9` | drainage              | physics_assumed | 同上                               |
| drainage              | `k_leakage_from_age`                 |      `[0,2]` |  `0.6` | drainage              | physics_assumed | 同上                               |
| UBW                   | `k_alteration_from_propensity`       |      `[0,2]` |  `1.0` | UBW                   | expert_prior    | 同上                               |
| fire-safety           | `k_deficiency_from_maintenance`      |      `[0,2]` |  `0.8` | fire-safety           | expert_prior    | 同上                               |
| coverage              | `k_accessibility_to_inspected_ratio` |      `[0,1]` |  `0.7` | access class          | calibrated      | 同上                               |
| technical validation  | `k_repair_quality_to_test_pass`      |      `[0,2]` |  `1.1` | repair                | physics_assumed | 同上                               |
| assessment            | `k_condition_to_fsp_loss`            |      `[0,1]` | `0.35` | structural assessment | physics_assumed | 同上                               |

### 1.3 Crack surrogate coefficients（DEBT-020 round5 sub-task 1，2026-05-10 落地）

§3.2 旧 seed crack surrogate 公式（`primary_crack_opening_mm_true` / `primary_crack_length_m_true`）所需 8 个系数。proagent (round5) 工程估值，当前封口 spec 采用 proagent 工程估值作为权威参数版本；后续如有实测或人工校准，只能通过新 provenance token 显式覆盖，不能把当前值标为 pending。

链路语义（Option ① true-then-noise，2026-05-10 用户拍板）：
- §3.2 公式输出 `primary_crack_opening_mm_true` / `primary_crack_length_m_true` 是**真值（true）**——纯几何派生，不含 measurement noise / observation tail。
- W0 measurement slot `crack_width_mm` / `crack_length_m` 的 reported 值 = `apply_named_noise(true, GEOM_REL_ABS_GAUSS)`（spec §14 noise model）；与 spall/rebar `cover_loss_depth_mm_true → reported`、`spall_patch_area_true_m2 → reported` 链路一致.
- 严重 crack tail（structural separation / through-crack 等）由 mechanism / structural assessment 分支表达，不在 crack surrogate 范围.

| 系数 | 值 | 单位 | 范围 | source | 备注 |
|---|---:|---|---|---|---|
| `crack_activation_bias` | -2.00 | 无量纲（sigmoid 偏置）| `[-3.5, -1.0]` | proagent_engineering_estimate_current_authority_round5_2026_05_10 | 让无明显 driver 时 activation_score ≈ 0.12-0.25，避免裂缝默认主缺陷 |
| `alpha_service_load` | 2.00 | 无量纲 | `[0.5, 3.0]` | 同上 | service_load_ratio>0.55 后明显增敏；区分普通使用 vs 高荷载 |
| `alpha_restraint` | 1.30 | 无量纲 | `[0.5, 2.0]` | 同上 | RC 外墙 / 梁板交接 / 修补界面常见约束裂缝；略低于 service_load |
| `alpha_workmanship` | 1.00 | 无量纲 | `[0.5, 1.5]` | 同上 | workmanship 是放大项不是决定项；二级调制 |
| `k_opening_base_mm` | 0.06 | mm | `[0.05, 0.15]` | 同上 | 基线 hairline crack；高于 hard floor 0.05 但远低于普通可见 0.2-0.5 mm |
| `k_opening_from_activation_mm` | 0.95 | mm | `[0.5, 1.5]` | 同上 | severity 对 width 主尺度；与 round2 crack_width_mm typical_bounds 一致 |
| `k_length_scale` | 0.33 | 无量纲 ratio | `[0.2, 0.6]` | 同上 | severity 决定裂缝占 nominal_length 的比例；low ≈ 40%, severe ≈ 60-65% |
| `crack_width_hard_cap_mm` | 1.25 | mm | `[1.0, 2.0]` | 同上 | primary visible crack 上限；超出由 severe defect / structural assessment 表达 |

**Sanity scenarios**（proagent round5 sub-task 1 自验，1000-sample MC）：

| scenario | activation_score | severity | crack_width_true (mm) | crack_length_true (m) | crack_count |
|---|---|---|---|---|---|
| A: 年轻低荷低约束 (age=15, load=0.6, restraint=0.2, workmanship=0.3, moisture=0.1, length=3.0) | 0.21 | 0.20 | 0.30 | 1.35 | 1 |
| B: 中等楼龄 (age=45, load=0.85, restraint=0.6, workmanship=0.5, moisture=0.5, length=8.0) | 0.47 | 0.56 | 0.80 | 4.38 | 2 |
| C: 高龄高荷 (age=75, load=1.2, restraint=0.85, workmanship=0.8, moisture=0.85, length=15.0) | 0.77 | 0.83 | 1.25 (hard cap) | 9.47 | 3 |

**与 round2 distribution 对比**（MC 1000 active crack samples）：
- `primary_crack_opening_mm_true`: mean=0.58, p5=0.39, p95=0.82, max=1.08（vs round2 fallback typical=[0.05, 2.00]，arithmetic_mean=0.45）
- `primary_crack_length_m_true`: mean=2.12, p95=5.98（vs round2 fallback typical=[0.10, 12.00]，arithmetic_mean=1.60）
- p95 比 round2 fallback 窄是合理的——round2 是 observed（含 noise + severe tail），spec 06 §3.2 是 true（纯几何）；observed = true × (1 + noise) 才与 round2 对齐.

## 2. Mechanism surrogate 参数

| 参数                             | mechanism family              | 单调性                                                           |     噪声 | 边界      | 修复策略                     | 来源                                 |
| -------------------------------- | ----------------------------- | ---------------------------------------------------------------- | -------: | --------- | ---------------------------- | ------------------------------------ |
| `structural_load_score`        | load_crack                    | 对 `service_load_ratio`正                                      | `0.03` | `[0,1]` | clamp                        | `01_a12_权威旧蓝图.md`:L1002-L1016 |
| `restraint_crack_score`        | restraint_crack               | 对 `restraint_level`正                                         | `0.03` | `[0,1]` | clamp                        | 同上                                 |
| `corrosion_score`              | corrosion_spall               | 对 moisture / chloride / carbonation / age 正，对 cover depth 负 | `0.05` | `[0,1]` | clamp                        | 同上                                 |
| `delamination_score`           | hollowing_delamination        | 对 moisture / workmanship 正                                     | `0.05` | `[0,1]` | clamp                        | 同上                                 |
| `drainage_blockage_score`      | drainage_blockage             | 对 maintenance deficit 正                                        | `0.05` | `[0,1]` | clamp                        | 同上                                 |
| `drainage_misconnection_score` | drainage_misconnection        | 对 workmanship / alteration 正                                   | `0.04` | `[0,1]` | reject if non-drainage       | 同上                                 |
| `ubw_alteration_score`         | unauthorized_alteration       | 对 alteration_propensity 正                                      | `0.03` | `[0,1]` | clamp                        | 同上                                 |
| `fire_deficiency_score`        | fire_safety_deficiency        | 对 maintenance deficit 正                                        | `0.04` | `[0,1]` | reject if non-fire component | 同上                                 |
| `repair_failure_score`         | repair_validation_failure     | 对 repair_quality 负                                             | `0.04` | `[0,1]` | clamp                        | 同上                                 |
| `fsp_loss_score`               | structural_assessment_deficit | 对 severe condition 正                                           | `0.04` | `[0,1]` | clamp                        | 同上                                 |

## 3. 结构 / 外墙 condition surrogate

### 3.1 激活分数

```text
crack_score =
  sigmoid(1.4*service_load_ratio + 1.1*restraint_level + 0.6*workmanship_deficit - 1.0)

spall_score =
  sigmoid(1.2*moisture + 1.1*chloride + 0.8*carbonation + 0.5*age_norm - 1.2)

detachment_score =
  sigmoid(1.0*moisture + 0.8*workmanship_deficit + 0.5*maintenance_deficit - 0.8)

severity_index = max(active_scores)
```

来源：`01_a12_权威旧蓝图.md`:L1128-L1143。

### 3.2 旧 seed crack surrogate 公式保留为 geometry branch 参考

**链路语义（DEBT-020 round5 closure 2026-05-10）**：本节公式输出 `primary_crack_opening_mm_true` / `primary_crack_length_m_true` 是**真值（true）**——W0 measurement slot `crack_width_mm` / `crack_length_m` 的 reported 值 = `apply_named_noise(true, GEOM_REL_ABS_GAUSS)`（spec §14 noise model）。8 个系数授权见 §1.3。同 spall/rebar `cover_loss_depth_mm_true → reported` / `spall_patch_area_true_m2 → reported` 链路。


```text
age_norm = clip(age_years / 50.0, 0.0, 1.0)

activation_raw =
    crack_activation_bias
  + alpha_service_load * max(service_load_ratio - 0.55, 0.0)
  + alpha_restraint * restraint_level
  + alpha_workmanship * workmanship_deficit_index

crack_activation_score = clip(sigmoid(activation_raw), 0.0, 1.0)

crack_mechanism_kind =
  "load_induced" if service_load_ratio >= restraint_level + 0.15 else "restraint"

severity =
  clip(0.60*crack_activation_score + 0.20*age_norm + 0.20*moisture_ingress_index, 0.0, 1.0)

primary_crack_opening_mm_true =
  clip(k_opening_base_mm
       + k_opening_from_activation_mm * severity
       + 0.40*max(service_load_ratio - 0.70, 0.0)
       + 0.25*restraint_level,
       0.05,
       crack_width_hard_cap_mm)

primary_crack_length_m_true =
  clip(0.10 + nominal_length_m * (0.35 + k_length_scale * severity),
       0.05,
       nominal_length_m)

crack_count = 1 + int(severity >= 0.45) + int(severity >= 0.75)
```

来源：`02_a10_权威旧蓝图.md`:L668-L727。

Reject / repair：

| 类型   | 条件                                                                                 |
| ------ | ------------------------------------------------------------------------------------ |
| Reject | non-RC；activation_score < 0.35；nominal_length_m <= 0；crack_count == 0             |
| Repair | crack length clamp；reported width clamp；forced crack slice 中 crack_count 可修到 1 |

来源：`02_a10_权威旧蓝图.md`:L729-L744。

## 4. Rebar / spall surrogate

```text
age_norm = clip(age_years / 50.0, 0.0, 1.0)
cover_norm = clip(cover_depth_mm / 40.0, 0.0, 2.0)

corrosion_raw =
    corrosion_bias
  + beta_chloride * chloride_exposure_index
  + beta_carbonation * carbonation_index
  + beta_moisture * moisture_ingress_index
  + beta_age * age_norm
  + 0.80 * workmanship_deficit_index
  + 0.80 * maintenance_deficit_index
  - beta_cover_penalty * cover_norm

corrosion_severity_index = clip(sigmoid(corrosion_raw), 0.0, 1.0)

delamination_severity_index =
  clip(0.75*corrosion_severity_index
       + 0.15*moisture_ingress_index
       + 0.10*maintenance_deficit_index,
       0.0, 1.0)

cover_loss_depth_mm_true =
  clip(k_cover_loss_base_mm
       + k_cover_loss_scale * delamination_severity_index * cover_depth_mm,
       1.0,
       cover_depth_mm + 20.0)

spall_patch_area_true_m2 =
  clip(k_spall_area_scale
       * nominal_visible_area_m2
       * delamination_severity_index
       * (0.6 + 0.4*moisture_ingress_index),
       0.001,
       0.60*nominal_visible_area_m2)

exposure_potential_mm =
  max(0.0, cover_loss_depth_mm_true - cover_depth_mm + rebar_exposure_offset_mm)

rebar_exposed_length_true_m =
  clip((exposure_potential_mm / 10.0)
       * spall_patch_area_true_m2 / rebar_spacing_proxy_m,
       0.0,
       3.0*nominal_length_m)

rebar_exposed_bool_reported =
  rebar_exposed_length_m_reported >= rebar_exposed_length_threshold_m
```

来源：`02_a10_权威旧蓝图.md`:L884-L961。

Reject / repair：

| 类型   | 条件                                                                                                                                                |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reject | `component.material_system != reinforced_concrete`；`component.cover_depth_mm is null`（按 §0.1 reference 反查 ComponentNode 字段；`has_rebar` 由 material_system 等价 derive，不作为独立字段）；corrosion_severity_index < 0.40                                  |
| Repair | spall area clamp；cover loss depth clamp；rebar exposure requires sufficient spall area；`rebar_exposed_bool_reported`只能由 reported length 派生 |

来源：`02_a10_权威旧蓝图.md`:L963-L979。

## 5. Drainage surrogate

```text
blockage_index =
  clip(sigmoid(1.1*drainage_fault_propensity
               + 0.8*maintenance_deficit
               + 0.4*age_norm
               - 0.9), 0, 1)

leakage_index =
  clip(sigmoid(0.8*age_norm
               + 0.8*workmanship_deficit
               + 0.6*moisture
               - 1.0), 0, 1)

misconnection_present =
  sigmoid(1.2*workmanship_deficit
          + 1.0*alteration_propensity
          - 1.1) > 0.5

public_health_risk_index =
  clip(0.45*blockage_index
       + 0.35*leakage_index
       + 0.40*misconnection_present,
       0, 1)
```

来源：`01_a12_权威旧蓝图.md`:L1192-L1206。

## 6. UBW surrogate

```text
alteration_score =
  sigmoid(1.2*alteration_propensity
          + 0.5*workmanship_deficit
          + 0.4*maintenance_deficit
          - 0.8)

subdivided_unit_sign_present =
  component.location has private_premises
  and alteration_type == subdivision
  and alteration_score > 0.45

structural_impact_index =
  clip(0.6*alteration_score
       + 0.3*(component.structural_role is load-bearing),
       0, 1)
```

来源：`01_a12_权威旧蓝图.md`:L1251-L1262。

## 7. Fire-safety surrogate

```text
deficiency_score =
  sigmoid(1.0*fire_safety_deficit_index
          + 0.7*maintenance_deficit
          - 0.7)

deficiency_present = deficiency_score > 0.45

severity_index =
  deficiency_score * component_importance_weight
```

来源：`01_a12_权威旧蓝图.md`:L1290-L1300。

## 8. Coverage / sampling measurement surrogate

### 8.1 a12 lineage 兼容公式（保留作 fallback / generic coverage measurement）

```text
visible_area = max(fragment_area - covered_area, 0)
true_inspected_ratio = inspected_area / max(fragment_area, eps)
reported_ratio = clip(true_inspected_ratio + Normal(0, noise), 0, 1)

check_count = ceil(fragment_length_m / interval_m)
```

来源：`01_a12_权威旧蓝图.md`:L1335-L1347。

### 8.2 `ratio.covered_area.inspected` chain_C_plus 链式派生（DEBT-020 round5 sub-task 2，2026-05-10）

链式派生授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L289-L300（## #2 Sub-task 2 coverage_inspection_plan）+ L375-L398（## #2 Sub-task 2 ratio.covered_area.inspected final_derivation）。

`ratio.covered_area.inspected`（已检查面积比率）原 round2 走 B 类 distribution fallback（typical_bounds=[0.10, 0.85]）；round5 升 A 类 chain derive，让上游 plan 数据透明可追：

```text
# Step 1: per-fragment truncated_normal 采样（plan-level data 落 sampling_plan_registry::coverage_inspection_plan）
inspected_area_ratio_per_fragment =
  sample_truncated_normal(mean=0.45, sigma=0.18, clip=[0.10, 0.85])

# Step 2: derive 已检查面积（A 类 chain derived slot）
inspected_area_m2 = inspected_area_ratio_per_fragment * fragment_area_m2

# Step 3: derive 已检查面积比率（A 类 chain derived slot）
ratio.covered_area.inspected =
  clip(inspected_area_m2 / max(fragment_area_m2, eps), 0.0, 1.0)
```

**Option C+ 选择理由**（per pro 设计 `回复.md`:L250-L255）：HK RC / MBIS 修葺验证中的 inspection covered/visible area 接近 RI 对当前 fragment 的可达性 / 遮挡 / finish removal / 代表性开口选择，适合 per-fragment ratio 直接采样；不需要 facade-level plan-allocation 链路（与 §9 pull_test 链路不同）。

**MC sanity baseline**（pro 设计 `回复.md`:L389-L392 自验，10000-sample MC）：
- `ratio.covered_area.inspected` mean ≈ 0.45, stdev ≈ 0.18, p5/p95 ≈ [0.15, 0.75]
- 与 round3 inspection_execution coverage ratio 同量级（语义不同：本 ratio 是 W0 technical coverage measurement，非 sidecar regulatory execution coverage；数值现实相近）

**输入 slot**（4 个 chain input + 2 个 chain derived，授权 spec 04 §17 + spec 03 §4.4 sampling_plan_registry::coverage_inspection_plan）：
- `inspected_area_ratio_per_fragment`（chain input；truncated_normal）
- `inspected_area_m2`（chain derived A 类；无 distribution）
- `ratio.covered_area.inspected`（chain derived A 类；公式 derive）

## 9. Technical validation measurement surrogate

### 9.1 a12 lineage 兼容公式（保留作 strength / verification_failed / additional_after_failure_count derive）

```text
test_strength_true =
  base_strength * (0.5 + repair_quality_index)

test_strength_reported =
  clip(test_strength_true * (1 + Normal(0, technical_rel_noise)), bounds)

verification_failed =
  test_strength_reported < required_strength_proxy
  or repair_quality_index < 0.45

additional_after_failure_count =
  failure_count * additional_multiplier
```

来源：`01_a12_权威旧蓝图.md`:L1379-L1395。

### 9.2 `rate.pull_test.per_25m2` chain_C_plus 链式派生（DEBT-020 round5 sub-task 2，2026-05-10）

链式派生授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L262-L301（## #2 Sub-task 2 pull_test_sampling_plan）+ L344-L373（## #2 Sub-task 2 rate.pull_test.per_25m2 final_derivation）。

a12 旧公式 `pull_test_rate_per_25m2 = sample_count / max(fragment_area / 25.0, eps)` 直接用 fragment 自身整数 `sample_count` derive rate；用户决策 2026-05-10 选 Option C+ chain_C_plus，原因（pro 设计 `回复.md`:L243-L255）：

> HK RC / MBIS 修葺验证中的 pull-test 数量通常按 facade、floor、repair package 或 retiling package 规划，不是每个 fragment 独立掷骰。工程师会先按修复面积、分散程度、失败复验和访问条件确定总 test count，再把测试点布到 representative locations。

旧公式问题：fragment_area 退化到 1m² 时 `1 / (1/25) = 25` 爆炸（pro 设计 `回复.md`:L425-L426 counterfactual scenario 2 已验证）。Option C+ 用 facade-level allocation chain，让小 fragment 的 effective_count 按 area share 分配（可非整数），代数等价于 facade-level rate，不依赖 fragment_area。

链式派生公式（plan-level data 落 sampling_plan_registry::pull_test_sampling_plan）：

```text
# Step 1: facade-level 立面修复总面积采样（building / facade seed RNG，一栋楼共享）
facade_total_repaired_area_m2 =
  sample_lognormal(arithmetic_mean=120, sigma_log=0.75, clip=[20, 500])

# Step 2: facade-level plan-intensity 采样（building / facade seed RNG）
plan_intensity_tests_per_25m2 =
  sample_lognormal(arithmetic_mean=1.25, sigma_log=0.35, clip=[0.50, 3.00])

# Step 3: facade-level total_count derive（按 plan_intensity * area share / 25.0，round + clip）
total_pull_test_count_per_facade =
  round_clip(plan_intensity_tests_per_25m2 * facade_total_repaired_area_m2 / 25.0,
             lower=1, upper=25)

# Step 4: per-fragment area-proportional 分配（chain derived A 类；可非整数，effective_count 概念）
effective_pull_test_count_per_fragment =
  total_pull_test_count_per_facade
  * fragment_repaired_area_m2
  / max(facade_total_repaired_area_m2, eps)

# Step 5: per-fragment rate derive（chain derived A 类）
rate.pull_test.per_25m2 =
  effective_pull_test_count_per_fragment
  / max(fragment_repaired_area_m2 / 25.0, eps)

# 代数等价（when allocation is area-proportional）：
# rate.pull_test.per_25m2 = total_pull_test_count_per_facade
#                          / max(facade_total_repaired_area_m2 / 25.0, eps)
# → 1m² fragment 不爆炸，因为 rate 与 fragment_area 解耦
```

**Option C+ 选择理由**（pro 设计 `回复.md`:L242-L256 + counterfactual scenario 3 `回复.md`:L428-L429）：
- `pull_test sample_count` 按 facade / floor / repair package 规划而非 per-fragment 独立掷骰
- 小 fragment（如 1m²）按 area share 分到的 effective_count 是 fraction（如 0.05），rate 仍 ≈ facade-level rate，不爆炸
- Option A（per-fragment 直接 sample_count）会让 1m² fragment rate=25 爆炸 → **不选**
- Option B / C 中间方案功能不全，C+ 是最终选择

**MC sanity baseline**（pro 设计 `回复.md`:L362-L367 自验，10000-sample MC）：
- `rate.pull_test.per_25m2` mean ≈ 1.25, stdev ≈ 0.45, p5/p95 ≈ [0.64, 2.10], min/max guarded ≈ [0.34, 3.43]
- 与 round2 reference `lognormal(mean=1.25, sigma_log=0.35, typical=[0.50, 3.00])` 一致：mean 对齐，p5/p95 落在 round2 typical 内

**fragment_repaired_area_m2 缺失代理**（pro 设计 `回复.md`:L412 假设 2 用户接受）：fragment 没有 repaired_area metadata 时用 `fragment_area_m2` 或 repair patch area 代理。

**fallback 路径（generator.py 实现细节）**：fragment 没有 repaired_area metadata 且 chain input 也无法采时，回退到 round2 distribution fallback（保持向后兼容）；详见 spec 06 §11.5 Path B fallback 行为。

**输入 slot**（4 chain input + 2 chain derived，授权 spec 04 §17 + spec 03 §4.4 sampling_plan_registry::pull_test_sampling_plan）：
- `facade_total_repaired_area_m2`（chain input；facade-level lognormal）
- `plan_intensity_tests_per_25m2`（chain input；facade-level lognormal）
- `total_pull_test_count_per_facade`（chain input；plan_derived_rounded_lognormal_intensity）
- `effective_pull_test_count_per_fragment`（chain derived A 类；无 distribution）
- `rate.pull_test.per_25m2`（chain derived A 类；公式 derive）

## 10. Structural assessment measurement surrogate

```text
max_severity = max(condition.severity_index)

fsp_true =
  clip(1.20
       - k_condition_to_fsp_loss * max_severity
       - 0.10*age_norm,
       0, 2)

core_sample_count =
  ceil(component_volume_m3 * core_sample_rate_proxy)
```

来源：`01_a12_权威旧蓝图.md`:L1425-L1434。

实现注意：`ConditionState` 字段表未列 `severity_index`，但这里使用该字段；需在实现前确认来源。（来源：`01_a12_权威旧蓝图.md`:L280-L307、L1427-L1430）

## 9.X Missing-Formulas 升 A 类公式落地（DEBT-020 round5 sub-task 4，2026-05-10）

授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1232-L1546（## #4 Sub-task 4 — Missing-Formulas）。

7 个 B 类 measurement slot 升 A 类，按物理因果 derive；distribution_source 标 `proagent_engineering_estimate_current_authority_round5_2026_05_10`（当前权威，不阻塞落地；当前封口 spec 采用 proagent 工程估值作为权威参数版本；后续如有实测或人工校准，只能通过新 provenance token 显式覆盖，不能把当前值标为 pending）。3 个 B 类保留 round2 distribution（无稳定物理上游）。

### 9.X.1 `length.concrete_repair.depth`（升 A，`回复.md`:L1309-L1340）

```text
cover_deficit_factor = clip((30.0 - cover_depth_mm) / 30.0, 0.0, 1.0)

length.concrete_repair.depth =
  clip(cover_depth_mm
       + 8.0
       + 52.0 * spall_severity_index
       + 18.0 * corrosion_severity_index
       + 8.0 * cover_deficit_factor
       + 6.0 * max(chloride_exposure_index - 0.50, 0.0),
       5.0, 180.0)
```

Inputs（spec 04 §17 列表）：cover_depth_mm / spall_severity_index / corrosion_severity_index / chloride_exposure_index. cover_depth_mm 缺失（None）时取 25mm 代理。

MC sanity（容忍 ±10%）：mean=66, p5/p95=[20, 125]. consistency_with_round2: passed (round2 reference truncated_normal mean=65 σ=28).

### 9.X.2 `time.fire_door.self_closing.delay_sec`（升 A，`回复.md`:L1368-L1396）

```text
time.fire_door.self_closing.delay_sec =
  clip(2.0
       + 4.0 * maintenance_deficit
       + 2.0 * age_norm
       + 2.0 * moisture_ingress_index
       + 6.0 * fire_safety_deficiency_present,
       0.0, 60.0)
```

Applicability: `component.component_type == fire_door OR domain_of(component.component_type) == fire_safety`（按 §0.1 reference 反查：`fragment.component_id → ComponentNode.component_type`；`fragment_scope` 即 domain scope，由 spec 03 §4.1 `component_type_registry.allowed_mechanisms` 含 fire_safety_deficiency → fire_safety 派生）. MC sanity: mean=6.4, p5/p95=[2.0, 18.0]. consistency_with_round2: passed (round2 reference lognormal mean=6.5 σ=0.55).

### 9.X.3 `stress.pull_test.minimum`（升 A，`回复.md`:L1398-L1425）

```text
base_bond_strength_n_per_mm2 = 0.85

stress.pull_test.minimum =
  clip(base_bond_strength_n_per_mm2 * (0.45 + 0.95 * repair_quality_index)
       - 0.12 * moisture_ingress_index
       - 0.10 * workmanship_deficit,
       0.10, 2.50)
```

Inputs: repair_quality_index / moisture_ingress_index / workmanship_deficit. MC sanity: mean=0.78, p5/p95=[0.30, 1.35]. consistency_with_round2: passed (round2 reference truncated_normal mean=0.75 σ=0.30).

### 9.X.4 `count.hammer_tapping.grid.minimum`（升 A，`回复.md`:L1479-L1510）

```text
effective_tapping_area_m2 =
  max(nominal_visible_area_m2, fragment_area_m2 * 0.50)

grid_cell_area_m2 =
  clip(0.60
       - 0.15 * detachment_severity_index
       - 0.10 * spall_severity_index,
       0.35, 0.80)

count.hammer_tapping.grid.minimum =
  ceil_clip(effective_tapping_area_m2 / grid_cell_area_m2, lower=5, upper=150)
```

Inputs: nominal_visible_area_m2 / fragment_area_m2 / detachment_severity_index / spall_severity_index. MC sanity: mean=52, p5/p95=[12, 110]. consistency_with_round2: passed (round2 reference rounded_truncated_normal mean=50 σ=20).

### 9.X.5 `count.pull_test.per_repaired_facade`（升 A，`回复.md`:L1238-L1264）

复用 #2 sub-task 2 facade chain (spec 06 §9 chain Step 1-3)：

```text
plan_intensity_tests_per_25m2 = sample_lognormal(arithmetic_mean=1.25, sigma_log=0.35, clip=[0.50, 3.00])
facade_total_repaired_area_m2 = sample_lognormal(arithmetic_mean=120, sigma_log=0.75, clip=[20, 500])

count.pull_test.per_repaired_facade =
  round_clip(plan_intensity_tests_per_25m2 * facade_total_repaired_area_m2 / 25.0,
             lower=1, upper=25)
```

facade-level（一栋楼共享 building/facade seed RNG）。MC sanity: mean=5.9, p5/p95=[1, 16]. consistency_with_round2: passed (round2 reference rounded_truncated_normal mean=6.0 σ=3.0).

### 9.X.6 `count.pull_test.per_floor_full_retiling`（升 A，`回复.md`:L1266-L1292）

新 floor-level retiling chain（与 facade chain 同 schema 但 floor-level）：

```text
floor_full_retiling_area_m2 =
  sample_lognormal(arithmetic_mean=80, sigma_log=0.65, clip=[10, 400])

retiling_plan_intensity_tests_per_25m2 =
  sample_lognormal(arithmetic_mean=1.35, sigma_log=0.30, clip=[0.60, 3.00])

count.pull_test.per_floor_full_retiling =
  round_clip(retiling_plan_intensity * floor_full_retiling_area_m2 / 25.0,
             lower=1, upper=20)
```

Plan-level data 落 `sampling_plan_registry::floor_retiling_package`（spec 03 §4.X yaml）。MC sanity: mean=5.6, p5/p95=[2, 10]. consistency_with_round2: passed (round2 reference rounded_truncated_normal mean=5.5 σ=2.0).

### 9.X.7 3 个 B 类保留 round2 distribution

无稳定物理上游的 3 个 slot 保留 round2 distribution（pro 设计 `回复.md`:L1294-L1366 决策）：

| slot | round2 distribution | rationale |
|---|---|---|
| `count.repair_mortar_specimens.per_strength_property` | rounded_truncated_normal(mean=2.8, σ=0.9, typical=[1, 6]) | 实验室组样 / 材料批次 / 合同测试制度变量，与 fragment severity 弱相关；当前 W0 无 mortar batch / material lot 上游 |
| `length.mortar.application_layer_thickness` | truncated_normal(mean=14, σ=6, typical=[4, 35]) | 材料施工性 / 收缩 / 附着 / 工人分层施工习惯决定，severity 影响总修补深度但不应直接决定单层标称厚度 |
| `duration.repair_mortar.test_age` | discrete_mixture_rounded(mean=7.25, σ=1.05, typical=[5, 10]) | lab protocol / submission scheduling 离散流程变量，不由 fragment 物理状态派生 |

## 10.X RebarSectionLossExtend（DEBT-020 round5 sub-task 6，2026-05-10）

授权：`杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round5/回复.md`:L1671-L1865（## #6 Sub-task 6 — RebarSectionLossExtend）+ **用户决策修正版**（不扩 measure_registry qualifier dim，违反 W0 不为下游服务原则）。

### 10.X.1 物理 metadata 派生（fragment-level）

3 个 metadata 从 fragment 物理 state 自然派生，写进 `MeasurementRecord.qualifiers`（spec 04 §16 字段合约新增）：

**rebar_type** ∈ `{main_bar, stirrup, link, unspecified}`：物理类型，RI 锈蚀报告必然写。从 `component.structural_role` 派生 prevalence（按 §0.1 reference 反查路径 `fragment.component_id → ComponentNode.structural_role`，spec 04 §5 ComponentNode 表）：

```text
default prevalence (no role): main_bar 0.55 / stirrup 0.30 / link 0.15
primary_load_bearing:         main_bar 0.50 / stirrup 0.35 / link 0.15
secondary_load_bearing:       main_bar 0.55 / stirrup 0.30 / link 0.15
non_load_bearing:             main_bar 0.65 / stirrup 0.20 / link 0.15
service_component:            main_bar 0.60 / stirrup 0.25 / link 0.15
finish_only:                  main_bar 0.55 / stirrup 0.30 / link 0.15

rebar_type = sample_categorical(prevalence_by_role[component.structural_role])
# 等价于：sample_categorical(prevalence_by_role[lookup_component(fragment.component_id).structural_role])
```

**rebar_location** ∈ `{beam, column, slab, wall, stair, foundation}`：结构部位，RI 必然写"哪个构件的钢筋"。从 `domain_of(component.component_type) + component.structural_role` 派生候选集合（按 §0.1 reference 反查：`fragment.component_id → ComponentNode.component_type / structural_role`；`fragment_scope` 即 domain scope，由 spec 03 §4.1 `component_type_registry.allowed_mechanisms` 派生 — 见 §0.1 表）：

```text
structural_components + primary_load_bearing → {beam, column, wall}
structural_components + secondary_load_bearing → {beam, wall}
external + load_bearing → {wall, column}
structural + load_bearing → {beam, column, wall, slab}
drainage + service_component → {wall, foundation}
fire_safety + service_component → {wall}
fallback (unknown scope) → {wall} or {beam, column, wall, slab}

rebar_location = rng.choice(candidates)
```

**corrosion_loss_type** ∈ `{uniform_corrosion, pitting, section_reduction, unspecified}`：锈蚀形式，RI 描述锈蚀必然说形式。从 driver state 物理因果派生：

```text
default prevalence: uniform_corrosion 0.65 / pitting 0.30 / section_reduction 0.05

# chloride 调制：每 0.1 chloride 把 5% 从 uniform 移到 pitting（local pitting 主因子）
pitting_boost = 0.5 * chloride_exposure_index  # max 0.5 boost
pitting_share = min(0.85, default_pitting + pitting_boost)
uniform_share = max(0.05, default_uniform - pitting_boost)

# severity 调制：高 severity (>0.65) → section_reduction 概率上升
if corrosion_severity_index > 0.65:
    sr_boost = 0.15 * (severity - 0.65) / 0.35
    section_reduction_share = min(0.30, default + sr_boost)
    uniform_share -= sr_boost

normalize → corrosion_loss_type = sample_categorical(adjusted_prevalence)
```

### 10.X.2 `ratio.rebar.section_loss` per-class lognormal derive

**用户决策方案 B**（不是方案 A multiplier，pro 原 `回复.md`:L1437-L1461 multiplier 设计被否决）：

```yaml
distribution_per_class:
  main_bar:
    arithmetic_mean: 0.07
    sigma_log: 0.75
    physical_bounds: [0.00, 0.50]
    typical_bounds: [0.00, 0.30]
    rationale: 主筋通常埋深较深，section loss 对结构安全敏感

  stirrup:
    arithmetic_mean: 0.11
    sigma_log: 0.80
    physical_bounds: [0.00, 0.50]
    typical_bounds: [0.00, 0.40]
    rationale: 箍筋/横向筋更靠保护层外缘，小直径同等腐蚀深度对应更高 section loss

  link:
    arithmetic_mean: 0.13
    sigma_log: 0.85
    physical_bounds: [0.00, 0.50]
    typical_bounds: [0.00, 0.45]
    rationale: link/tie 小直径、暴露和边角位置概率更高，右尾最重

  unspecified:
    arithmetic_mean: 0.09
    sigma_log: 0.75
    physical_bounds: [0.00, 0.50]
    typical_bounds: [0.00, 0.35]
    rationale: 保留 round2 aggregate fallback；旧数据和未标 rebar_type 的 record 使用
```

**lognormal mean 是 arithmetic_mean**（不是 median）——DEBT-028 footgun 防，用 `_sample_lognormal_arith_mean` helper。

物理因果调制（双向锚点对齐：物理头端 + per-class lognormal 尾端覆盖法规 escalation proxy 边界）：

```text
cover_deficit_factor = clip((25.0 - cover_depth_mm) / 25.0, 0.0, 1.0)

physical_drive =
    0.50  # baseline
  + 1.05 * corrosion_severity_index
  + 0.25 * chloride_exposure_index
  + 0.20 * moisture_ingress_index
  + 0.15 * cover_deficit_factor

physical_drive = clip(physical_drive, 0.4, 2.0)

# Sample lognormal with class-specific arith_mean + sigma
raw_class = sample_lognormal_arith_mean(
    arithmetic_mean = class_params.arith_mean,
    sigma_log = class_params.sigma_log,
    clip = [class_params.physical_lo, class_params.physical_hi]
)

# Driver factor 调制 class mean（baseline driver=1.0 时不调）
ratio.rebar.section_loss = clip(
    raw_class * (physical_drive / 1.0),
    class_params.physical_lo,
    class_params.physical_hi
)
```

**双向锚点对齐**：分布形状以物理因果 + per-class lognormal 共同决定，让 evo-agent 见到法规 escalation proxy 附近的 spread（main_bar > 0.20 / stirrup > 0.30 / link > 0.35 边界）。pro `回复.md`:L1859-L1862 counterfactual scenario A：main_bar mean 0.07 σ 0.75 有少量 >0.20 tail，stirrup mean 0.11 σ 0.80 有更明显 >0.30 tail，两者均非 1-bin 独占 5-bin 健康。

### 10.X.3 measurement output 携带 metadata

3 个物理 metadata 写进 `MeasurementRecord.qualifiers`（不扩 measure_registry qualifier dim）：

```text
qualifiers = {
    "rebar_type": rebar_type,                   # ∈ {main_bar, stirrup, link, unspecified}
    "rebar_location": rebar_location,           # ∈ {beam, column, slab, wall, stair, foundation}
    "corrosion_loss_type": corrosion_loss_type, # ∈ {uniform_corrosion, pitting, section_reduction, unspecified}
}
```

消费层（rule_card / projection executor / 分析层）可见物理上下文。**注意**：此 qualifiers 不是 measure_registry 的 qualifier dim 扩展（用户决策原则：不扩 qualifier dim，避免 W0 倒着为下游服务）。

### 10.X.4 applicability

`ratio.rebar.section_loss` derive 路径仅在以下条件触发：
- `component.material_system == "reinforced_concrete"`（按 §0.1 reference 反查：`fragment.component_id → ComponentNode.material_system`；`has_rebar` 不作为独立字段，由 material_system 等价 derive）
- driver_state 可用
- `mechanism.mechanism_family == "corrosion_spall"` OR `condition.severity_index >= 0.30`

不满足时不 emit（沿用原 fallback distribution Path B 路径）。

## 11. Derived flags

| flag                                     | 输入依赖                                           | 触发条件                                                                     | unknown / N/A                            | 来源                                 |
| ---------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------ |
| `risk_building_safety_emergency`       | severe structural condition, fsp ratio, UBW impact | `severity>=0.85 or fsp<0.75 or structural_impact>=0.85`                    | missing input ->`unknown`              | `01_a12_权威旧蓝图.md`:L1839-L1857 |
| `risk_public_health_emergency`         | drainage public_health_risk_index                  | `>=0.80`                                                                   | no drainage ->`not_applicable`         | 同上                                 |
| `risk_public_danger_present`           | detachment / spall / fire / UBW severity           | `max danger index >=0.70`                                                  | missing severity ->`unknown`           | 同上                                 |
| `repair_required`                      | condition severity, risk flags, verification fail  | `moderate+ condition or risk true or verification_failed`                  | no condition -> false                    | 同上                                 |
| `maintenance_pre_next_cycle_required`  | minor / moderate condition, repair not urgent      | `minor/moderate and not emergency`                                         | no condition -> false                    | 同上                                 |
| `repair_outcome_safe_until_next_cycle` | repair_quality, verification_failed, residual risk | `repair_quality>=0.65 and not verification_failed and risk<0.70`           | no repair ->`not_applicable`           | 同上                                 |
| `verification_test_failed`             | test strength / rate / count                       | below proxy threshold                                                        | no test ->`not_applicable`             | 同上                                 |
| `assessment_fsp_below_required_safety` | fsp ratio                                          | `fsp < fsp_floor_proxy`                                                    | no assessment ->`not_applicable`       | 同上                                 |
| `drainage_misconnection_present`       | `DrainageState.connection_state`                 | `connection_state=misconnected`                                            | no drainage ->`not_applicable`         | 同上                                 |
| `ubw_present`                          | `UBWState.alteration_type/status proxy`          | `alteration_type != none and authorization_status_proxy=unauthorized_like` | no UBW carrier -> false                  | 同上                                 |
| `subdivided_unit_sign_present`         | `UBWState.subdivided_unit_sign_present`          | true                                                                         | no private premises ->`not_applicable` | 同上                                 |
| `fire_safety_deficiency_present`       | `FireSafetyState.deficiency_present`             | true                                                                         | no fire component ->`not_applicable`   | 同上                                 |
| `coverage_insufficient`                | covered / inspected ratios                         | `reported_ratio < coverage_floor_proxy`                                    | no scope target ->`not_applicable`     | 同上                                 |
| `defect_cause_or_extent_uncertain`     | `ConditionState.uncertainty_flag`                | true                                                                         | default false                            | 同上                                 |
| `family_uncovered`                     | projection selected unknown                        | selected_family=unknown                                                      | N/A                                      | 同上                                 |

### 11.0 阈值符号数值锚定说明

§11 表触发条件用的阈值，多数已在 §1.1 Global parameters 表或本表触发条件列内显式给数值（如 `severity>=0.85` / `>=0.80` / `repair_quality>=0.65` 等，code 端 derived flag threshold 常量按这些 spec 数值对齐）。

唯一例外是 `assessment_fsp_below_required_safety` 的 `fsp_floor_proxy`：spec §1.1 / §10 / §11 均只给符号，未给具体数值——该阈值属**工程口径系数**（FSP 结构性能比的"安全下限"，跟 surrogate 公式系数同性质），归 **DEBT-021（surrogate 工程口径系数待 domain expert 校准）** trace。code 端 `_FSP_FLOOR_PROXY` 当前用工程口径值承载、不阻塞落地（按"pro/工程口径符合原则即当前权威"）；待 DEBT-021 校准后由 spec §1.1 显式补数值、code 回写对齐。

## 11.X 推导矛盾对清单（spec 04 §9 P0 reject 落地依据）

spec 04 §9 P0 reject 行写 "contradictory flags impossible to repair"——但 spec 没显式列哪些 pair 算 contradictory。本节按 **§11 触发条件公式 + `risk_derivation_registry` / `repair_outcome_registry` formula** 严格推导出 7 个矛盾对清单，作为 C029 P0 check 的实施依据。

**严格推导原则**：仅列从 spec 公式可直接推导、无 ambiguity 的矛盾对；模糊关系（如 safe_until_next_cycle vs 某 risk emergency — residual_risk 跟 risk emergency 触发不严格 1:1 map）不列。

| # | 矛盾对 | 推导依据 |
|---|---|---|
| 1 | `repair_required=True AND safe_until_next_cycle=True` | W1 spec 07 §2.4 字面例子；业务语义"要求修但下周期前安全"自相冲突 |
| 2 | `safe_until_next_cycle=True AND verification_test_failed=True` | `RO_SAFE_UNTIL_NEXT_CYCLE_V1` formula "NOT failed"；安全态前提是测试未失败 |
| 3 | `maintenance_pre_next_cycle_required=True AND risk_building_safety_emergency=True` | `RO_PRE_NEXT_CYCLE_MAINTENANCE_V1` formula "NOT any_emergency_risk"；maintenance 仅适用 non-emergency |
| 4 | `maintenance_pre_next_cycle_required=True AND risk_public_health_emergency=True` | 同上（public_health 是 emergency 级别）|
| 5 | `repair_required=False AND risk_building_safety_emergency=True` | `RO_REPAIR_REQUIRED_V1` input_risk 含 `RISK_BUILDING_SAFETY_EMERGENCY`；risk_emergency 必然触发 repair_required |
| 6 | `repair_required=False AND risk_public_danger_present=True` | `RO_REPAIR_REQUIRED_V1` input_risk 含 `RISK_PUBLIC_DANGER_UBW`；danger present 必然触发 repair_required |
| 7 | `repair_required=False AND verification_test_failed=True` | `RO_REPAIR_REQUIRED_V1` input_verif 含 `verification_test_failed`；test failed 必然触发 repair_required |

**舍弃的潜在矛盾对（不严格推导无法判定）**：

| 候选 | 舍弃理由 |
|---|---|
| `safe_until_next_cycle=True AND risk_building_safety_emergency=True` | safe 公式用 residual_risk<0.70 数值阈值，跟 risk_emergency 触发 (severity/fsp/structural_impact) 不严格 1:1 |
| `repair_required=False AND risk_public_health_emergency=True` | `RO_REPAIR_REQUIRED_V1` input_risk **不含** `RISK_PUBLIC_HEALTH_DRAINAGE`；public_health emergency 不必然触发 repair |
| `maintenance_pre_next_cycle_required=True AND risk_public_danger_present=True` | `risk.public_danger.present` 是 "present" 不是 "emergency" 级别；maintenance "NOT any_emergency_risk" 不明确把 danger present 包入 |

**消费方**：worldgen P0 check C029（详见 W0 spec 07 §2 C029 行 + W1 spec 07 §2.4）按本表 7 对逐一验证，任一对成立即 P0 reject。

**长期 trace**：本节由 DEBT-030 B 组 C029 矛盾对扩展 2026-05-12 闭环加入。若后续 `risk_derivation_registry` / `repair_outcome_registry` 加新 entry 或 formula 改动，应回头审视本表是否需要扩展（详见 `团队文档/我的笔记/技术与研究债.md` DEBT-030 trace）。

## 11.5 B 类 measurement typical 分布采样规则（DEBT-026 closure）

**背景**：DEBT-026 拆分前，`_sample_value_for_slot` 对所有 measurement slot 用 `(physical_lo + physical_hi) / 2` 中点采样 + 6% 相对噪声——~90% slot 实测 obs mean 精确等于 bounds 中点，跨 threshold 的 5-bin 健康度全部 100% far_above / far_below（详见 `技术与研究债.md` DEBT-026 诊断）。

**修订（2026-05-10，配合 spec 04 §17 字段拆分 + spec 03 §4.2 字段扩展）**：W0 measurement slot 分两类 generation 路径：

### A 类 slot — spec 公式 derive

A 类 slot 由 spec 06 §3-§10 公式按 fragment 物理状态 / driver / mechanism / condition 派生（如 `ratio.fsp.structural_performance` 走 §10 fsp_true 公式；`public_health_risk_index` / `index.drainage.blockage` / `index.drainage.leakage` / `flag.drainage.misconnection_present` 走 §5 drainage 公式；`rebar_exposed_length_m` / `spall_area_m2` 走 §4 rebar/spall 公式 limited to mechanism="corrosion_spall"）。

A 类 slot 在 `technical_measurement_registry` 不填 typical 分布字段（`recommended_distribution = null`）。`_sample_value_for_slot` **不**走分布采样路径——值由 generator.py 的 `_compute_*` 函数显式 derive，写入 `MeasurementRecord.measurement_value`。

### B 类 slot — typical 分布采样

B 类 slot 是无 spec 公式授权的 measurement（如 `crack_width_mm` / `length.rendering.total_thickness` / `count.pull_test.per_repaired_facade` / sidecar `duration.notification.deadline` 等）。

`_sample_value_for_slot` 双层 clip 规则：

1. **Path A（recommended_distribution 完备时）**：
   - 按 `recommended_distribution`（normal / lognormal / uniform / triangular / bernoulli）+ `recommended_mean` + `recommended_sigma` 采样 → `value`
   - **Clip 1**：clip 到 `typical_bounds = [typical_min, typical_max]`（工程现实 5%/95% 实操区间）
   - **Clip 2**：clip 到 `physical_bounds = [physical_lo, physical_hi]`（物理硬上下界，hard fail-safe）
   - 顺序：sample → typical clip → physical clip → precision rounding（§13）→ noise model（§14，仅 fallback path）

2. **Path B（fallback，typical 字段缺失时）**：
   - `value = (physical_lo + physical_hi) / 2`
   - + spec §14 named noise model（rel_sigma / abs_sigma per measurement_family）
   - 这是 DEBT-026 closure 前的 baseline 行为，仅作 backstop

### 字段授权链路

- `physical_bounds` 必填，授权见 `04_生成实例与法规映射参考真值字段合约.md` §17 表
- `typical_bounds` / `recommended_distribution` / `recommended_mean` / `recommended_sigma` / `distribution_source` 5 个字段授权见 `03_registry_schema_matrix.md` §4.2，optional——缺则走 Path B fallback
- `distribution_source` 用于 provenance（当前封口 spec 工程估值 / a4 / 后续实测校准等）；后续如有实测校准，以新 provenance token 显式覆盖

### Bool / Categorical slot 特殊路径

`flag.*` bool slot（`flag.drainage.misconnection_present` 等）含 `recommended_distribution = bernoulli` 时走 `BERNOULLI_PREVALENCE_SAMPLER`（§12 表）：`reported = (rng.uniform() < recommended_mean)`，`recommended_mean` 解释为 prevalence p ∈ [0,1]。bernoulli 不走 typical_bounds clip。

sidecar enum slot 走 `MULTINOMIAL_PREVALENCE_SAMPLER`（§12），授权见 `09_sidecar边界契约.md` §1.2（sidecar_bool_slot_registry）。

### 跨家族阈值查 helper（projection executor 端）

sidecar slot（如 `duration.notification.deadline`）的真阈值在 rule_card 中归属 `procedure / supervision / reporting` 类 family，但 W0 `_pick_projection_family_for_fragment` 每 fragment 只返回 1 个 mechanism-driven family，所以按 candidate_family 查 sidecar slot 阈值会 miss。`regulation_thresholds.find_threshold_for_slot_any_family` 跨家族查（任意 family 的 measure_key == slot_id），让 sidecar slot 的 distribution 真正进入 5-bin 评估。详见 `09_sidecar边界契约.md` §1.2。

## 11.6 sidecar bool / categorical slot conditional_formula evaluator（Round 6 + Round 7 已落地）

> **状态注（2026-05-11 更新 — DEBT-020 Round 6 + Round 7 落地版本）**：
>
> 本节定义的 evaluator framework + 45 条 conditional_formula **已全部落地并通过 10000 MC alignment validation**（45/45 slot delta < 0.05）。
>
> Round 6 设计（45 公式 + 6 layer DAG 拓扑 + sampling_order 1-45 + centered upstream pattern）：见 `杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round6/回复.md`。
> Round 7 修订（基于 MBIS COP 2023 原文复核）：见 `杂物箱/文件包/DEBT-020_distribution_reframing_proagent_round7/回复.md`。
>
> Round 7 关键修订（已落实）：
> 1. **3 个 anchor 数字修订**：
>    - `procedure.investigation.proposal.submitted`: 0.23 → 0.30 (COP §4.2.1)
>    - `artifact.form.mbi2`: 0.23 → 0.08 (COP §2.1.3(j) — temp RI nomination form, NOT investigation)
>    - `artifact.proposal.detailed_investigation`: 0.23 → 0.30 (COP §4.2.1)
> 2. **MBI2 DAG 语义修订**：MBI2 从 L3 detailed_investigation 移到 L1 intake_and_ri (sampling_order 16 → 7)；upstream_inputs 改成 `procedure.temp_ri_nomination.completed`；`artifact.proposal.detailed_investigation` 不再依赖 MBI2.
> 3. **45 个 source_label 全部精确化**到 `MBIS_CoP_2023 §x.y.z modality=shall + round4_baseline` 格式.
> 4. **Decision #5 DeliveryDeadline 阈值** rule_card_threshold 从 PENDING 升级到 COP §2.1.3(r) 确认值（to_ba: <=14 day after repair.prescribed.completed; to_person: same_day_as BA submission date）.
>
> 实现 entry：
> - 公式数据：`agent_v1/src/workflow_engine/worldgen/round6_formulas.py` (45 slot specs + DAG order)
> - Evaluator: `agent_v1/src/workflow_engine/worldgen/conditional_eval.py` (centered_sigmoid_linear / centered_softmax_per_class evaluator + ALLOWED_INPUTS 扩 H.* 19 + sidecar slot 45)
> - Sidecar 派生层入口: `agent_v1/src/workflow_engine/worldgen/sidecar.py:_sample_sidecar_bool_slots_for_fragment` (按 sampling_order 拓扑遍历 + sidecar_upstream 累积 + post-sample consistency clamp)
> - Hidden state 派生: `sidecar.py:_build_round6_hidden_state_for_fragment` (19 H.* 项 W0 state → prior 派生)
> - Registry overlay: `registry.py:_apply_round6_round7_overlays` (sidecar_bool_slot_registry 45 records 加 7 字段)

**背景**：DEBT-020 Round4 给 ~45 个 sidecar bool / categorical slot 定了 marginal `prevalence`；Round5 sub-task 3 原计划补 `conditional_formula`，让 prevalence 按 fragment 物理 state 条件采样（如 `procedure.investigation.intention_notified` 在无 defect / 低 severity fragment 上概率接近 0，在 severe crack / spall 时接近 1）。本节定义 conditional_formula 的 schema、可用输入白名单、采样语义.

实现：[`agent_v1/src/workflow_engine/worldgen/conditional_eval.py`](../../../../agent_v1/src/workflow_engine/worldgen/conditional_eval.py) + [`sidecar.py::_sample_sidecar_bool_slots_for_fragment`](../../../../agent_v1/src/workflow_engine/worldgen/sidecar.py).

### 11.6.1 公式 schema（结构化 dict，非 free-form 字符串）

支持 **4 种 type**（前 2 种 legacy sub-task 3, 后 2 种 DEBT-020 Round 6 落地版）：

**Bool slot — sigmoid_linear** (legacy)：

```yaml
conditional_formula:
  type: sigmoid_linear
  bias: 1.05                    # float
  terms:                        # input_name → coefficient
    defect_class_present: 0.45
    age_norm: 0.20
```

采样：`p = sigmoid(bias + Σ coef_i * context[input_i])`

**Bool slot — centered_sigmoid_linear** (Round 6 落地版，45 slot 全用)：

```yaml
conditional_formula:
  type: centered_sigmoid_linear
  anchor: 0.86                                # marginal_anchor (Round 7 修订)
  upstream_expected:                          # 中心化基准
    H.case_active: 0.96
    H.age_old_score: 0.55
    H.admin_discipline_score: 0.65
  terms:                                      # input_name → coefficient
    H.case_active: 0.55
    H.age_old_score: 0.25
    H.admin_discipline_score: 0.30
```

采样：`p = sigmoid(logit(anchor) + Σ coef_i * (input_i - upstream_expected_i))`

头端工程依赖（centered upstream 去中心化上游）+ 尾端贴 marginal anchor 双向锚点（DEBT-020 Round 6 §1.1 + Round 7 §1）.

**Categorical / enum slot — softmax_per_class** (legacy)：略.

**Categorical / enum slot — centered_softmax_per_class** (Round 6 落地版)：

```yaml
conditional_formula:
  type: centered_softmax_per_class
  classes:
    registered_inspector:
      anchor: 0.58
      upstream_expected:
        procedure.ri.appointment.completed: 0.86
        supervision.site_visit.performed: 0.80
      terms:
        procedure.ri.appointment.completed: 0.35
        supervision.site_visit.performed: 0.25
    # ... 其他 class
```

采样：`logit_c = log(anchor_c) + Σ coef_ci * (input_i - upstream_expected_i)`, softmax → multinomial.

**所有 anchor 加和必须 ≈ 1.0**（validate_formula 强制 ±0.001 容差）.

### 11.6.2 可用输入白名单（`ALLOWED_INPUTS`）

不读 rule_card threshold / family / projection_id——保持 rule-blind. 全集 86 项分 3 类：

**A. Physical W0 state (22 项, ALLOWED_PHYSICAL_INPUTS)**：

| 类别 | 输入 |
|---|---|
| Driver / building | `age_norm`（=clip(age_years/50, 0, 1)）/ `service_load_ratio` / `restraint_level` / `workmanship_deficit` / `maintenance_deficit` / `moisture_ingress_index` / `chloride_exposure` |
| Mechanism / condition | `crack_severity_index` / `spall_severity_index` / `corrosion_severity_index` / `delamination_severity_index` / `detachment_severity_index` |
| Drainage state | `drainage_blockage_index` / `drainage_leakage_index` / `public_health_risk_index` |
| Bool indicator (0/1) | `defect_class_present` / `ubw_alteration_present` / `fire_safety_deficiency_present` |
| Repair / assessment | `repair_quality_index` / `fsp_structural_performance` |
| Building-level aggregate | `building_total_severity_max`（max severity_index across fragments）/ `building_defect_count_norm`（=count/20 cap [0,1]）|

**B. Hidden state H.* (19 项, ALLOWED_HIDDEN_INPUTS) — Round 6 §1.2**：

`H.case_active` / `H.age_old_score` / `H.admin_discipline_score` / `H.admin_instability_score` / `H.document_maturity_score` / `H.defect_present` / `H.defect_uncertainty` / `H.defect_severity_score` / `H.repair_need` / `H.repair_complexity_score` / `H.contractor_mobilisation_need` / `H.testing_need` / `H.material_replacement_need` / `H.nonconformity_risk` / `H.repair_quality_score` / `H.fire_safety_need` / `H.ubw_extra_work` / `H.drainage_issue` / `H.fire_door_issue`

派生 entry：`sidecar.py:_build_round6_hidden_state_for_fragment` 从 W0 generator 已采样 fragment / driver / mechanism / drainage / fire_safety / ubw / repair_assessment 状态派生；缺数据 fallback 到 `HIDDEN_STATE_PRIOR_MEANS`.

**C. Sidecar slot upstream (45 项, ALLOWED_SIDECAR_INPUTS) — Round 6 §1.3**：

45 个 sidecar bool/enum slot id 全部允许作为下游 slot 的 upstream input，**但仅限 sampling_order 早于自己的 slot**（spec 06 §11.6.7 DAG validity）.

新增 input 需扩相应 ALLOWED_*_INPUTS 子集 + 同步本节表，并修订 spec 06 §11.6.2.

### 11.6.3 采样路径分支（spec 09 §1.2 sidecar 派生层）

```text
for slot in sidecar_bool_slot_registry.records:
    if slot.conditional_formula is not None and evaluator_context is not None:
        → 走 conditional path（spec 06 §11.6.1）
    else:
        → 走 marginal path（按 slot.prevalence 采）
```

`evaluator_context` 由 `sidecar.py::_build_evaluator_context_for_fragment` 从 WorldBundle 各 list（drivers / mechanisms / conditions / drainage_states / fire_safety_states / ubw_states / repair_assessment_states）按 fragment_id / scope_filter 重建.

### 11.6.4 落地约束（schema validation）

`conditional_eval.validate_formula(formula)` 在 registry build 时运行（spec 03 §4.2 sidecar_bool_slot_registry 完备性 audit），保证：

- `type` ∈ {`sigmoid_linear`, `softmax_per_class`, `centered_sigmoid_linear`, `centered_softmax_per_class`} 之一
- `bias` (legacy) 是 number；`anchor` (centered) ∈ (0, 1]
- `terms` 所有 input_name ∈ `ALLOWED_INPUTS` 白名单
- `upstream_expected` (centered) 所有 input_name ∈ `ALLOWED_INPUTS` 白名单
- `terms` / `upstream_expected` 所有 value 是 number
- enum centered_softmax_per_class: 所有 class anchor 加和 ≈ 1.0 ± 0.001
- 缺失 input 在采样时按 0.0 默认（context 不强求所有字段都填）

### 11.6.5 marginal consistency QA

`expected_marginal_bool(formula, sample_contexts)` / `expected_marginal_enum(...)` 用于 release_batch QA 验证：跨整个 fragment 群体边缘化后，conditional formula 的 E[P(true)] 应贴近 marginal_anchor ± 0.05.

DEBT-020 Round 7 §3 已用 10000 MC (seed=20260511) 验证 45 slot 全 PASS（max delta 0.0228 for `procedure.investigation.proposal.recognized`，远小于 0.05 阈值）；详见 `agent_v1/src/workflow_engine/worldgen/registry.py:_ROUND7_ALIGNMENT_REFERENCE` + `tests/test_round6_round7_alignment.py`.

差距过大（如 ±0.15 以上）→ 改设计假设（hidden state 派生 / upstream_expected 默认值 / 公式形式 / Round 7 anchor），不调 coefficient 凑数字（DEBT-020 Round 7 §0 用户硬约束）.

### 11.6.6 与 rule-blind 原则的关系

conditional formula 只读 W0 物理 state + H.* hidden state + 已采样 sidecar slot upstream（`ALLOWED_INPUTS` 白名单强制），**不读 rule_card threshold value / family / evidence role**；DEBT-020 Round 7 §4.2 scenario_5 验证：rule_card threshold 删除 / 修改 → 45 公式输出不变.

### 11.6.7 DAG validity（Round 6 §1.2 + Round 7 §0 修订）

45 个 sidecar bool/enum slot 按 sampling_order 1-45 拓扑排序采样，每个 slot 的 `upstream_inputs.sidecar` 必须 sampling_order < 当前 slot.

DAG 6 layer 拓扑：
```
L1 intake_and_ri (1-7):    RI appointment, MBI1, temp_ri_nom_completed, temp_ri_nom_terminated,
                            ri_role_terminated, MBI5, **MBI2 (Round 7 修订: temp RI nomination form)**
L2 prescribed_inspection (8-13): inspection_completed, MBI3/3A, inspection_log,
                                  inspection_report, photo_annotated, plan_annotated
L3 detailed_investigation (14-19): intention_notified, notice_intention,
                                    proposal_submitted, proposal_detailed_investigation,
                                    proposal_recognized, started
                                    (Round 7 §0 修订: MBI2 已移走)
L4 repair_supervision (20-35): supervision_representative_planned ...
                                repair_revision artifact
L5 completion (36-41): repair_completed ... extra_works_separated
L6 statutory + qualifiers (42-45): fire_safety_outstanding, qual.actor_role,
                                     qual.method_class, qual.artifact_field_group
```

Round 7 §0 关键修订：`artifact.form.mbi2` 从 L3 detailed_investigation (sampling_order 16, 旧版) 移到 L1 intake_and_ri (sampling_order 7)，因为 COP §2.1.3(j) + Appendix 10 明确 MBI2 是 temporary RI nomination form 而非 detailed investigation form. 旧版把 MBI2 放在 detailed_investigation branch 导致语义错误.

post-sample consistency clamp:
- `supervision.record.completed_and_retained` 不应 > min(completed, retained)
- 单 fragment Bernoulli 上理论可能 > min；`sidecar.py:_sample_sidecar_bool_slots_for_fragment` 在采样时 in-place clamp.

## 12. 测量噪声模型

| noise model                | 公式语义                                                                           | 来源                                 |
| -------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------ |
| `GEOM_REL_ABS_GAUSS`     | `reported = round(clip(true*(1+N(0,rel_sigma)) + N(0,abs_sigma), lo, hi), step)` | `01_a12_权威旧蓝图.md`:L1531-L1549 |
| `RATIO_ABS_GAUSS`        | `reported = round(clip(true + N(0,abs_sigma), 0, 1), step)`                      | 同上                                 |
| `COUNT_POISSON_ROUND`    | `reported = max(0, round(true + Poisson(lambda_noise)-lambda_noise))`            | 同上                                 |
| `TECH_REL_GAUSS`         | `reported = round(clip(true*(1+N(0,rel_sigma)), lo, hi), step)`                  | 同上                                 |
| `BOOL_DERIVED_NOISELESS` | `reported_bool = comparator(reported_numeric, threshold)`                        | 同上                                 |
| `ENUM_NOISELESS`         | `reported_enum = canonical_enum`                                                 | 同上                                 |
| `BERNOULLI_PREVALENCE_SAMPLER` | `reported_bool = (rng.uniform() < prevalence_p)`，输入 `prevalence_p ∈ [0, 1]` 来自 `sidecar_bool_slot_registry.prevalence` 或 `technical_measurement_registry.recommended_distribution=bernoulli_as_float` 的 `recommended_mean`。无附加 noise（prevalence 本身已含群体行为变异） | spec 09 §1.2 (2026-05-09 修订) sidecar 派生层 + DEBT-020 round2 closure（`flag.drainage.misconnection_present` 等 0/1 indicator slot）|
| `MULTINOMIAL_PREVALENCE_SAMPLER` | `reported_enum = rng.choices(enum_values, weights=prevalence_list)`，输入 `prevalence_list` 长度 = `enum_values` 长度 + 总和 = 1.00；来自 `sidecar_bool_slot_registry.prevalence`（list[float]）。无附加 noise | spec 09 §1.2 (2026-05-09 修订) sidecar 派生层 categorical / qualifier slot（`qual.actor_role` / `qual.method_class` / `qual.artifact_field_group`）|

## 13. Precision rounding

| measurement family   |       coarse |     standard |          fine | 来源                                 |
| -------------------- | -----------: | -----------: | ------------: | ------------------------------------ |
| geometry width mm    |   `0.10mm` |   `0.05mm` |    `0.01mm` | `01_a12_权威旧蓝图.md`:L1551-L1563 |
| geometry length m    |    `0.05m` |    `0.01m` |    `0.005m` | 同上                                 |
| geometry area m²    | `0.010m²` | `0.001m²` | `0.0005m²` | 同上                                 |
| coverage ratio       |     `0.05` |     `0.01` |     `0.005` | 同上                                 |
| count                |      integer |      integer |       integer | 同上                                 |
| test stress          |  `10 unit` |   `1 unit` |  `0.1 unit` | 同上                                 |
| thickness / depth mm |      `5mm` |      `1mm` |     `0.5mm` | 同上                                 |
| assessment ratio     |     `0.05` |     `0.01` |     `0.005` | 同上                                 |

## 14. Variance / offset / clip

| measurement family         | rel_sigma |                                    abs_sigma | clip                   | noise model                               | 来源                                 |
| -------------------------- | --------: | -------------------------------------------: | ---------------------- | ----------------------------------------- | ------------------------------------ |
| geometry-derived           |  `0.08` | slot-specific:`0.05mm / 0.005m / 0.001m²` | slot bounds            | `GEOM_REL_ABS_GAUSS`                    | `01_a12_权威旧蓝图.md`:L1564-L1573 |
| coverage / rate / sampling |     `0` |                 `0.03 ratio`or `1 count` | `[0,1]`or count >= 0 | `RATIO_ABS_GAUSS / COUNT_POISSON_ROUND` | 同上                                 |
| technical validation       |  `0.06` |                                slot-specific | slot bounds            | `TECH_REL_GAUSS`                        | 同上                                 |
| assessment                 |  `0.05` |                                        `0` | assessment bounds      | `TECH_REL_GAUSS`                        | 同上                                 |
| bool derived               |     `0` |                                        `0` | bool                   | `BOOL_DERIVED_NOISELESS`                | 同上                                 |

## 15. Threshold regime

```text
far_below / near_below / exact_threshold / near_above / far_above
```

`far_below / near_below / exact / near_above / far_above` 是相对于数值阈值本身，不直接代表 pass/fail；pass/fail 由 operator 单独决定。（来源：`01_a12_权威旧蓝图.md`:L1697-L1723）

| measurement family              | width 规则                       | 默认                                     | 来源                                 |
| ------------------------------- | -------------------------------- | ---------------------------------------- | ------------------------------------ |
| geometry length / width / depth | `max(abs_min, rel*threshold)`  | `abs_min=0.05mm or 0.01m`,`rel=0.10` | `01_a12_权威旧蓝图.md`:L1724-L1736 |
| area                            | `max(0.01m², 0.20*threshold)` | e.g. spall `0.01m²`                   | 同上                                 |
| ratio                           | `max(0.02, 0.10*threshold)`    | `0.02`                                 | 同上                                 |
| count                           | `1`                            | ±1 count                                | 同上                                 |
| rate                            | `max(0.1,0.10*threshold)`      | family-specific                          | 同上                                 |
| stress                          | `max(1.0,0.05*threshold)`      | unit-specific                            | 同上                                 |
| bool                            | `not_numeric`                  | no regime                                | 同上                                 |
| enum / classification           | `not_numeric`                  | no regime                                | 同上                                 |

Exact threshold 规则：float 在 rounding 前 `1e-9`；reported measurement 要 rounding 后 exactly equal；integer 为 `value == threshold`。（来源：`01_a12_权威旧蓝图.md`:L1737-L1744）

## 16. Unknown 策略

### 16.1 Unknown 不是兜底垃圾桶

**原则来源**：旧 a10 蓝图阶段（即已废弃的 seed v1 范围实现，详见 `00_术语表与名词解释.md`）立下的"unknown 必须显式枚举、不能笼统"原则。a10 的 seed v1 实现本身已被 a12 全量覆盖取代，新版不再使用；但这条原则作为**unknown 设计准则**继承到新版。（来源：`02_a10_权威旧蓝图.md`:L1098-L1102）

a10 seed v1 当年只允许两种明确 unknown subtype：`unsupported_masonry_crack`、`moisture_surface_anomaly`。**这两个子型只是当年范围内的具体案例，不是新版规定的 unknown 全集**——a12 全量覆盖后允许更多 subtype，但仍必须显式登记，不得笼统兜底。

新版扩展后，`unknown` 的含义是：

* worldgen 宇宙中存在事实；
* 但当前 normative family set 无法稳定投影；
* 或该事实属于 sidecar-only / uncovered domain；
* 或 registry / binding / unit / method 不能支持该 projection。

来源：`03_a11_权威旧蓝图.md`:L35-L42；`01_a12_权威旧蓝图.md`:L1661-L1691。

### 16.2 Unknown surrogate

```text
age_norm = clip(age_years / 50.0, 0.0, 1.0)

unknown_raw =
    unknown_score_bias
  + u_moisture_weight * moisture_ingress_index
  + u_restraint_weight * restraint_level
  + 0.40 * age_norm

unsupported_severity_index = clip(sigmoid(unknown_raw), 0.0, 1.0)

subtype =
  "unsupported_masonry_crack"
  if material_system in {"masonry_plaster","plaster_finish"} and restraint_level >= 0.30
  else "moisture_surface_anomaly"
```

来源：`02_a10_权威旧蓝图.md`:L1138-L1156。

Unknown reject / repair：

| 类型   | 条件                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reject | unsupported masonry crack 却是 RC；crack-like subtype 误满足 known crack compatibility；moisture anomaly 生成 spall / rebar exposure 字段         |
| Repair | anomaly area 超界时 clamp；crack-like subtype crack_count==0 时置为 1；若误满足 known family applicability 则 reject 重采，不做 projection 层修补 |

来源：`02_a10_权威旧蓝图.md`:L1207-L1221。

### 16.3 Projection unknown reason codes（已迁出 W2 包）

`unknown_reason_code` 完整枚举 + priority 派生 + detector helpers — **已于 2026-05-13 物理迁出到** W2 规格 [`08_unknown策略.md`](../W2法规映射层全量实现级设计规格包/08_unknown策略.md) §2（**13 条完整枚举** + priority 派生公式 + detector helpers 4 条）。本节作 stub 引 W2，DEBT-018 落地步骤 2。

### 16.4 `not_applicable`（已迁出 W2 包）

`not_applicable` 语义 + unknown / not_applicable / fallback 三态边界 — **已于 2026-05-13 物理迁出到** W2 规格 [`08_unknown策略.md`](../W2法规映射层全量实现级设计规格包/08_unknown策略.md) §1（三态语义对照表）+ §4（不在 W2 范围的 fallback，含 W1 派生 `not_applicable`、W0 surrogate unknown subtype、evo-agent / rule_card v2 各自 fallback 边界）。本节作 stub 引 W2，DEBT-018 落地步骤 2。

### 16.5 sidecar 派生异常口径

sidecar 派生异常不新增 unknown reason code，不输出 `sidecar_derivation_failed`。

W2 端统一处理为：

- sidecar 部分可用：`sidecar_join_status=partial`
- sidecar 不可用：`sidecar_join_status=unavailable`
- 若需要 unknown reason：`unknown_reason_code=sidecar_only_fact_pattern`

W0 不定义 W2 unknown reason priority，也不维护 sidecar fallback enum.

