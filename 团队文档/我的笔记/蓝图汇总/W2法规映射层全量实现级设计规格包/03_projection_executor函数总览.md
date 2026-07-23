# W2 projection executor 函数总览

> 跨包权威源与负向不变量见：`../_封口总则_字段权威源与负向不变量.md`。如本章与总则冲突，以总则和字段所属包权威章节为准。


**编号粒度声明**：本文用一套 phase 编号（W2 phase 1-4），跟 W1 包"跨层粗粒度 Step 0-7 + 函数级 Step 1-9"两套编号不同。

| 编号粒度 | 用在哪 | 来源 | 含义 |
|---|---|---|---|
| **跨层粗粒度 Step 0-7**（5 大业务阶段）| 仅 §1 跨层位置图（cross-ref W1 包 03 §1）| W0 规格 05 §1 + a12 line 1828-1837 | 整个 `WorldGenerator` 跨 W0 / W1 / W2 三层的阶段性编号，W2 落在 Step 6（projection 评估）|
| **W2 phase 1-4 函数级**（本文 §2 总表 + §3 段间依赖 + §4 P0-P3 速查）| 本文主要章节 | W0 规格 05 §3.10 + a12 §13.3 整理 | W2 主链 4 个 phase + 对应主入口；W2 不像 W1 是 9 段串行链，而是"contract 编译（一次性）→ spec 编译（一次性）→ world 评估（per-world）→ batch 聚合（per-batch）"四 phase |

本文默认用 W2 phase 1-4 编号；§1 跨层位置用粗粒度 Step 0-7。

## 1. W2 跨层位置（粗粒度 Step 0-7）

W2 在 `WorldGenerator` 跨层链的位置：

```text
W0 静态资源层:
  Step 0. 加载 registry / formula / constraint / projection_registry / canonical_slot universe
  ─────────────────────────────────────
W1 实例生成流程层（详见 W1 包 03 §1）:
  Step 1. 实例化 world core
  Step 2. 派生 condition / drainage / UBW / fire-safety state
  Step 3. 派生 geometry / coverage / technical validation / assessment measurement
  Step 4. 验证并修复约束
  Step 5. 派生 risk / repair / verification / assessment flag
  ─────────────────────────────────────
W2 法规映射层（本包覆盖，对应 §2 W2 phase 1-4）:
  Step 6. 对一个具体 WorldBundle 跑 NormativeProjection
  Step 7. 停止；不复制 HiddenGold（HiddenGold 半段已砍）
```

跨层链来源：W0 规格 05 §1 + `01_a12_权威旧蓝图.md`:L1828-L1837；HiddenGold 删除依据：`09_用户原则说明.md`:L20-L25 + 用户 2026-05-13 D-2 决策。

**W2 跟 W1 的 phase 链差异**：W1 是 9 段串行函数链（一个 world 走完全部 9 段），W2 是 4 phase 但其中两段（contract 编译、spec 编译）是 **batch 启动前一次性**，剩下两段（world projection、batch 聚合）才按 batch 跑。原因：rule_card → projection contract / spec 的编译产物在整 batch 内不变，按 batch 启动时一次性编译写入 artifact 即可。

## 2. W2 主入口 + 子函数总表（W2 phase 1-4，本文后续章节默认用此粒度）

W2 主链含 **4 个主入口** + **6 个公开 helper** + **18 个内部 helper**；后续 §4 函数实施卡为每个主入口 + 公开 helper 各列一张实施卡，内部 helper 仅本节总览描述。

### 2.1 主入口 4 个

按 W2 phase 1-4 顺序：

| W2 phase | 主入口（spec 设计名）| 输入 | 输出 | 前置依赖 |
| ---: | --- | --- | --- | --- |
| 1 | `compile_projection_contract` | rule_card v2 bundle（manifest + 13 sub-file + projection_runtime_mapping）| `ProjectionContract.v1.json`（含 slot / measure 分区表 + alias 表 + result schema）| W0 资源已准备 + rule_card v2 bundle 物理存在 |
| 2 | `compile_projection_specs` | rule_card v2 bundle + phase 1 输出的 ProjectionContract | `ProjectionSpecs.v1.json`（family × card_specs 嵌套结构）| phase 1 已完 |
| 3 | `build_normative_projections_for_world` | `WorldBundle` + `RegistryBundle` + `SidecarRuntimeBundle` | `List[NormativeProjection]`（per-world per-fragment）| W1 已为该 world 输出 + phase 1/2 已 batch 启动前完成 |
| 4 | `execute_projection_batch_v2` | building_worlds 路径 + normative_projection 路径 + sidecar_runtime 路径 + output_dir | `RegulationProjectionSummary.v2.json` + `Results.v2.parquet` + `Samples.v2.json` | phase 3 已为全部 world 输出 |

### 2.2 公开 helper 6 个

per-fragment 评估和 alias 翻译公开 helper（W2 phase 3 内部 / 跨 phase 共用）：

| # | 公开 helper（spec 设计名）| 输入 | 输出 | 在哪 phase 用 |
|---|---|---|---|---|
| H1 | `evaluate_fragment_projection_candidates` | `fragment_id` + candidate family list + `conflict_group_id` + threshold eval inputs + extra unknown context | per-fragment 评估结果 dict（`selected_family_ids` / `unknown_reason_code` / `threshold_evaluations` / `projection_status`）| phase 3 |
| H2 | `load_runtime_mapping` | `bundle_dir`（rule_card v2 bundle 根目录）| 加载 `projection_runtime_mapping_v1.json` 为 dict（附 `mapping_path` 字段记录出处）| phase 1 / phase 2 |
| H3 | `resolve_family_conflict` | candidate family list + `conflict_group_id` | `(selected_family_ids, unknown_reason_code)` 元组 | phase 3 内 H1 调用 |
| H4 | `derive_unknown_reason_code` | trigger flag dict（13 个 priority 条件位）| 第一个满足 priority 的 reason_code 或 None | phase 3 内 H1 调用 |
| H5 | `build_threshold_evaluation` | `rule_id` + `slot_id` + `operator` + `threshold_value` + `observed_value` + `measurement_family` + `slot_unit` + `integer_compare` | `ThresholdEval`-compatible dict（含 `regime_tag` / `pass_bool`）| phase 3 内 H1 调用 |
| H6 | `compute_threshold_width` | `threshold` + `measurement_family` + `slot_unit` | width 浮点值（family 表 hit 优先 → unit fallback → 兜底 0）| phase 3 内 H5 调用 |

公开 helper 详细实施卡见本包 `04_函数实现规格卡.md`。

### 2.3 内部 helper 18 个（仅总览描述，详细实施不展开）

按职责分 5 类。**spec 端不列具体函数名 / 行号 / 实施完成度**（按 spec 不写代码现状原则）；本节仅列分类 + 职责，便于后续 cross-ref。

| # | 职责类 | spec 端语义描述 | 数量 |
|---|---|---|---|
| Cat A | rule_card → contract 编译 helper | rule_card bundle 内 per-card 字段编译（slot_role_map / threshold / trigger / evidence / workflow_operands deadlines / required_sidecar_interfaces 等）转换为 ProjectionContract / ProjectionSpec dict 结构 | 6 |
| Cat B | runtime mapping alias 翻译 helper | W0 端 `slot_id` / `measure_key` ↔ rule_card 端 `slot_id` / `measure_key` 双向 alias 查询，附 4 分桶（world_core / measurement / qualifier / sidecar_interface）分类 | 4 |
| Cat C | family / candidate 路由 helper | mechanism_family + component_type 单 target projection family 选择（F1 修正——单 target 设计）；按 severity 派生 applicability_score / required_slots_present | 2 |
| Cat D | threshold 评估底层 helper | 5-bin regime 分箱（far_below / near_below / exact_threshold / near_above / far_above + not_numeric 兜底）+ operator 评估（8 项 `<= / < / >= / > / == / != / in / not_in`）；含 EPS_EXACT 浮点精度处理 | 2 |
| Cat E | parquet / JSON I/O helper | phase 4 batch 输出三件套读写（building_worlds / normative_projection / sidecar_runtime 三类 v2 输入加载；Results.v2.parquet 写入；Summary / Samples JSON 写入）| 4 |

**注**：18 个内部 helper 中含 2 个常量表（CONFLICT_GROUPS / MECHANISM_FAMILY_TO_PROJECTION_FAMILIES）+ 1 个 component_type override 表（_COMPONENT_TYPE_FAMILY_OVERRIDES），spec 级不展开具体内容（spec 07 §4.1 列 4 个 conflict_group 的 selector 规则；其余按代码现状属实施层）。

### 2.4 命名映射边界

本章只定义 W2 projection executor 的 spec 级函数边界。实现命名、代码位置与迁移状态不构成 spec 权威源。


## 3. 段间依赖

```text
[Batch 启动前一次性]

  Phase 1 (compile_projection_contract)
     │
     ├──► 读 rule_card v2 bundle (manifest + 13 sub-file)
     ├──► 读 projection_runtime_mapping_v1.json (alias / partition / targets)
     │
     ▼ ProjectionContract.v1.json
  Phase 2 (compile_projection_specs)
     │
     ├──► 读 rule_card v2 bundle
     ├──► 接 Phase 1 输出 ProjectionContract
     ├──► 内部调 Cat A `_compiled_card_spec` per-card 编译
     │
     ▼ ProjectionSpecs.v1.json

[Batch 内 per-world 跑]

  Phase 3 (build_normative_projections_for_world)
     │
     ├──► 读 WorldBundle 主消费字段（FragmentContext / MechanismState / ConditionState / MeasurementRecord）
     ├──► 读 SidecarRuntimeBundle 5 桶 (procedure_gate / supervision_runtime / artifact_requirement / completion_runtime / facts)
     ├──► 读 RegistryBundle → normative_projection_registry + sidecar_measurement_registry
     │
     ├── per-fragment 主循环：
     │      ├── Cat C: 单 target family 路由 → candidate family list
     │      ├── 跨家族 threshold 查 (regulation_thresholds Cat E) → threshold_inputs
     │      ├── H1 evaluate_fragment_projection_candidates
     │      │      ├── H3 resolve_family_conflict → selected_family_ids
     │      │      ├── H5 build_threshold_evaluation × N → threshold_evaluations
     │      │      └── H4 derive_unknown_reason_code (若 selected_family 空)
     │      └── 构造 NormativeProjection (含 ProjectionFamilyEval × N + ReportBasisItem × N + severity_band 派生)
     │
     ▼ List[NormativeProjection]（per-world per-fragment）

[Batch 跑完后聚合]

  Phase 4 (execute_projection_batch_v2)
     │
     ├──► 读 building_worlds + normative_projection + sidecar_runtime v2 输入
     │
     ├── 8 类 counter 聚合：
     │      verdict / family_hit / family_status_breakdown /
     │      unknown_reason / severity_band / coverage_status /
     │      threshold_regime / threshold_pass
     │
     ▼ RegulationProjectionSummary.v2.json + RegulationProjectionResults.v2.parquet + RegulationProjectionSamples.v2.json
```

详细依赖图（含 W0 / W1 / rule_card v2 资源依赖 + 横向 cross-phase 数据流）见本包后续 `05_依赖图.md`（批次 D）。

## 4. 函数级 P0-P3 速查

P0-P3 优先级体系详见 W1 包 07 §1（W0 规格 07 §1 体系，W1 + W2 共用）；W2 端 P0-P3 触发跟 W1 端 P0-P2 触发**独立**——W2 阶段不再做 worldgen surrogate 修复（属 W1），只触发 P3 fallback（projection 层 unknown / not_applicable）；W2 端 P0 触发场景集中在 contract 编译 / spec 编译 / output schema 三类。

**W2 端 P0-P3 触发**：

| W2 phase | P0 reject 典型触发 | P3 fallback 典型触发 |
|---|---|---|
| Phase 1 contract 编译 | rule_card bundle manifest 不可读 / schema_version 不一致 / projection_runtime_mapping_v1.json 不存在 | — |
| Phase 2 spec 编译 | rule_card 字段缺 required slot / measure_key 在 measure_registry 不存在 | — |
| Phase 3 world projection | binding references missing registry slot（C023）/ threshold unit incompatible / basis_items 为空（C025 P0 reject projection，W0 规格 07 §2）| family conflict 无法解 → unknown / required slot 无 W0 或 sidecar 支持 → not_applicable / sidecar 派生失败 → unknown 含现有 13 条 reason_code 之一（按业务最贴近 `sidecar_only_fact_pattern` 扩义，详见本包 `08_unknown策略.md` §3）|
| Phase 4 batch 聚合 | output schema 不一致 / parquet 写入失败 | — |

**W2 端 3 条约束（C023 / C024 / C025）触发优先级**（详见本包 `07_threshold_regime与冲突回退.md`）：

| 约束 | 检查时机 | 失败时 |
|---|---|---|
| `C023_UNKNOWN_NO_RULE_IDS` | Phase 3 构造 ProjectionFamilyEval 时 | P3 — selected_family=unknown 时 rule_ids 必须清空 |
| `C024_KNOWN_SINGLE_CONFLICT_GROUP` | Phase 3 family conflict 解析时 | P3 — 同 conflict_group 不能多选 known family（除 selector 允许 multi 的特例）|
| `C025_BASIS_NONEMPTY` | Phase 3 构造 NormativeProjection 时 | P0 reject projection — basis_items 必须非空 |

## 5. 删除项（明确不在 W2 范围）

按 `09_用户原则说明.md` L20-L25 + 用户 2026-05-13 D-2 决策 + W0 规格 08 §9：

| 删除项 | 旧来源 | 替代设计 |
|---|---|---|
| HiddenGold 编译半段（thin_copy(NormativeProjection)）| a12 §7.10 后半 + a12 §13.3 后半 + a12 §14.3 HiddenGold 行 + W0 规格 07 §2 `C026_HIDDEN_GOLD_THIN_COPY` | 完整删除 — `NormativeProjection.basis_items` 字段独立非空（C025），不复制成 HiddenGold |
| `AdjudicationState` / `GoldLabeler` / `gold_route_action` / `acceptable_next_question_bundle_ids` / `expected_profile` | a9 §3.5 + a9 §4 Step 6 + a9 §2.2 第 3 角色 "adjudication source" | 完整删除 — adjudication 角色语义被 projection 自身吸收（rule_card v2 作 immutable rule snapshot 给 projection 提供 family / threshold / basis 信息）|
| `ObservationState` 主链 + `QueryEpisode` + observation mask coverage 部分 | a9 §3.3 / §3.4 + a8 §4 第五件中 observation mask 段 | 完整删除（用户砍巡检员模拟）；coverage_control 保留 near-threshold / neighbor-family overlap / recoverable missing 三项采样控制 |
| `compile_normative_projection_and_hidden_gold` 函数旧名（a12 §7.10）| a12 §7.10 | spec 级拆为 W2 phase 1 / 2 / 3 / 4 四个主入口（本文 §2.1）；HiddenGold 半段完整删除；W2 主入口物理实现归 W2 代码目录 |
| `sidecar_missing` projection fallback marker（旧概念黑名单）| a12 §14 + W0 规格 06 旧版 §8 | 2026-05-09 用户口径：sidecar bundle 由 worldgen sidecar 派生层同时生成，不存在缺失态；派生异常表现为 `unknown`（reason_code 沿用现有 13 条之一，`sidecar_only_fact_pattern` 扩义；2026-05-13 重审撤回原计划的 `sidecar_derivation_failed` 单独 reason_code）或 `not_applicable`（详见本包 `08_unknown策略.md` §3）|
| obligation_graph chain 评估 | a12 §1.3 / rule_card v2 `obligation_graph` 字段 | spec 级保留 rule_card 字段，**但 W2 当前 phase 范围**不消费 obligation chain；W2 当前停留在 single-card / single-fragment 评估，跨节点 obligation chain 评估属未来 W2+ extension，**不在本包范围**（详见本包 `01_设计原则与本体边界.md` §2.2 时序声明）|

## 6. 来源

- W2 跨层位置：W0 规格 05 §1 第 6-7 步（W2 物理迁出后 W0 留 stub）+ `01_a12_权威旧蓝图.md`:L1828-L1837
- 4 phase 主入口总表：W0 规格 05 §3.10 函数实施卡（W2 物理迁出后 W0 留 stub）+ a12 §7.10 前半（HiddenGold 半段砍）+ a12 §13.3 projection compile logic 伪代码（HiddenGold 半段砍）
- 公开 helper 6 个：勘探报告 §11.7 W2 端代码主流程函数清单总结
- 内部 helper 5 类分类：勘探报告 §11.1 - §11.6
- 段间依赖：W0 规格 05 §4 跨层依赖 + 勘探报告 §11.5 build_normative_projections_for_world 主 pipeline
- 函数级 P0-P3：W0 规格 07 §1 P0/P1/P2/P3 优先级体系 + W0 规格 07 §2 C023-C025 约束（详见本包 `07_threshold_regime与冲突回退.md`）
- 删除项：`09_用户原则说明.md` L20-L25 + 用户 2026-05-13 D-2 决策 + W0 规格 08 §9
