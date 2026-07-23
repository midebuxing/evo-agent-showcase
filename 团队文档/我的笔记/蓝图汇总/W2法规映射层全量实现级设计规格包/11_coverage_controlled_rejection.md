# Coverage-controlled rejection（W2 采样侧）

W2 法规映射层 phase 3 产出 NormativeProjection 之后，按 a8 §4 第五件**在 projection 之后做 accept/reject**——为 benchmark 覆盖与训练数据采集**过采** near-threshold / neighbor-family overlap / recoverable missing 三类边界 case。本章列 W2 端 coverage-controlled rejection 的设计原则 + 3 种 over-sampling 触发条件 + W2 端实施位置 + 跟 W1 / evo-agent 的边界（不掺合 observation mask 部分）。

**用户 2026-05-13 D-1 决策**：coverage-controlled rejection 归 **W2 法规映射层**，不归 evo-agent 训练侧。理由：

- W2 是法规消费层，合法消费 rule_card / `normative_projection_registry` 是 W2 本职（按 W2 规格 01 §3 + memory `feedback_rule_blind_only_w0_w1.md`）；coverage-controlled rejection 需要按 5-bin regime / neighbor-family / family 覆盖维度采样，必须读 `normative_projection_registry` 数据——而 W1 worldgen 受 rule-blind 红线约束**不读** rule_card 不知 family 边界（按 W1 规格 09 §1 line 15）
- coverage-controlled rejection 是 batch 生成时的 accept/reject 决策（在 projection 输出后），不是 evo-agent 训练侧采样器（evo-agent 收到的是已 over-sampled 数据）

**与本包其他章节的关系**：

- **5-bin regime 完整定义**：详见 `07_threshold_regime与冲突回退.md` §1（按 W0 规格 06 §15 锚定）；本章只引用
- **16 family + conflict_group 4 组**：详见 `06_canonical_slots与projection_binding.md` §2 + `07_threshold_regime与冲突回退.md` §4；本章只引用
- **recoverable missing 跟 unknown_reason_code 的关系**：详见 `08_unknown策略.md` §2（13 条 reason_code）+ §3（sidecar fallback）；本章只引用

**与 W1 规格 09 §1 的关系**：W1 规格 09 §1 line 15 已明示 coverage-controlled rejection "属法规映射层 + evo-agent 训练侧采样器，不在 W1 范围"——本章描述法规映射层（W2）端实施；evo-agent 训练侧采样器（如果存在）属 evo-agent 独立层，不在本章范围。

## 1. 设计原则

按 a8 §4 第五件 line 239-252 + 用户 2026-05-13 D-1 决策：

### 1.1 a8 §4 第五件原文核心

> 为了 benchmark 和训练覆盖，你们可以在 projection 之后做 accept/reject：
> * 过采 near-threshold
> * 过采 neighbor-family overlap
> * 过采 recoverable missing / unrecoverable unknown
>
> 但注意：这是 **采样控制** ，不是 **世界生成逻辑** 。
>
> 这样物理一致性和多样性并不矛盾：
> * 一致性来自 causal + constraints
> * 多样性来自 fragment 模板、driver 组合、多机理耦合、~~observation mask、counterfactual pairs~~

**注**：原文 line 252 含 "observation mask、counterfactual pairs"，按用户原则 09.md L5-L8 + L20-L25 + W2 规格 00 §3 砍除清单——observation 链全砍，**observation mask coverage 部分不进 W2 规格**（详见 §5）。

### 1.2 核心原则三条

**原则一：在 projection 之后做 accept/reject**

- W2 phase 3 已为每个 fragment 产出 NormativeProjection（含 `selected_family` / `threshold_evaluations` / `unknown_reason_code` / `coverage_status` 等字段）
- coverage-controlled rejection 是 NormativeProjection 输出**之后**的 accept/reject 决策——按 NormativeProjection 字段值判断是否 accept 当前 fragment 进入 batch 输出
- 不修改 NormativeProjection 字段本身（按本包 `01_设计原则与本体边界.md` §3.2 W2 端禁止写回 W1 输出 + W2 不修改 NormativeProjection 输出后字段）；只做"是否 accept"二元决策

**原则二：采样层控制，不是世界生成逻辑**

- coverage-controlled rejection **不修改 W1 worldgen 内部状态**（W1 worldgen 完全 rule-blind，不知道 family 边界 / threshold regime 分布）
- coverage-controlled rejection **不修改 W2 projection 评估逻辑**（projection 评估按 spec 走，不为采样目标动态调 family routing / threshold width 等）
- 实施定位是 **batch 级 accept/reject filter**——按 batch 内 NormativeProjection 分布判断是否 accept 当前 fragment（reject 时触发 W1 重新生成 fragment / 抛弃当前 fragment / batch 内重复采样某类 fragment）

**原则三：物理一致性来源 vs 多样性来源分开**

- **物理一致性**来自 W1 因果（fragment → driver → mechanism → condition → measurement 五层严格单向）+ constraints（hard schema + physical bounds + P0 reject，按 W1 规格 07）；W2 端 coverage-controlled rejection 不重做物理一致性检查
- **多样性**来自 fragment 模板（17 个 fragment_template）+ driver 组合（多 driver 同 fragment 多激活）+ 多机理耦合（同 fragment 多 condition / multi-DC overlay）；W2 端 coverage-controlled rejection 通过过采 near-threshold / neighbor-family / recoverable missing 强化多样性的 **边界覆盖**

## 2. 3 种 over-sampling 触发条件

按 a8 §4 第五件 + 按 W2 端 NormativeProjection 字段可派生的判定：

### 2.1 过采 near-threshold

**目的**：让 5-bin regime 的 `near_below` / `near_above` 区间充分覆盖（不让 batch 全是 `far_below` / `far_above` 远离阈值的 trivial case）

**判定字段**：`ProjectionFamilyEval.threshold_evaluations[].regime_tag`

**判定规则**：

- 当前 fragment 含至少一项 `ThresholdEval.regime_tag ∈ {near_below, near_above, exact_threshold}` → 标记为 near-threshold case
- accept/reject 决策：按 batch 内 near-threshold 占比目标过采（如目标 30% near-threshold，当前 batch 已有 25% → accept；已有 35% → reject 当前 far-threshold case）

**业务意义**：evo-agent 训练时 5-bin regime 的 `near_below` / `near_above` 区间是判别边界，过采能让模型在边界 case 上有更充足学习；详见 a8 §4 line 243。

### 2.2 过采 neighbor-family overlap

**目的**：让 multi-family 同时近似 cover 的世界充分覆盖（即多 family 在 projection 上同时成立或接近成立的 case，评估 family 互斥 / 路由的边界）

**判定字段**：`NormativeProjection.matched_families[]`（含 ProjectionFamilyEval 列表）+ `ProjectionFamilyEval.applicability_score`

**判定规则**：

- 当前 fragment 含 ≥ 2 个 `applicability_score >= threshold_neighbor_overlap`（如阈值 0.5）的 ProjectionFamilyEval → 标记为 neighbor-family overlap case
- 或当前 fragment 触发 `unknown_reason_code = multi_family_conflict`（按本包 `07_threshold_regime与冲突回退.md` §4.3 情况 5）→ 同样标记
- accept/reject 决策：按 batch 内 neighbor-family overlap 占比目标过采

**业务意义**：evo-agent 训练时 multi-family 边界 case 是 family 路由判别的关键样本；详见 a8 §4 line 244。

### 2.3 过采 recoverable missing

**目的**：让关键 slot 可补但当前缺的 case 充分覆盖（即"信息不足但可补"的 unknown case，而不是 unrecoverable unknown）

**判定字段**：`NormativeProjection.unknown_reason_code` + `NormativeProjection.coverage_status` + `NormativeProjection.sidecar_join_status`

**判定规则**：

- 当前 fragment 含 `unknown_reason_code ∈ {binding_registry_gap, unit_incompatible, projection_binding_incompatible, measurement_family_unimplemented, method_class_unimplemented}` → 标记为 recoverable missing（这些是 binding 层 gap，理论上可补 registry / alias / unit 转换）
- 或当前 fragment `sidecar_join_status ∈ {partial, unavailable}`（按本包 `09_输出契约_NormativeProjection.md` 3 枚举）→ 同样标记（sidecar 部分缺失或派生失败，可通过 sidecar 派生层修复）
- 排除 unrecoverable unknown：`unknown_reason_code ∈ {no_known_family_match, coverage_unimplemented_domain, unsupported_material_system, unsupported_component_type, unsupported_damage_pattern, unsupported_location_context, sidecar_only_fact_pattern}`——这些是设计 / 业务层不适用，不属 recoverable
- accept/reject 决策：按 batch 内 recoverable missing 占比目标过采

**业务意义**：evo-agent 训练时 recoverable missing case 让模型学到"信息可补但当前缺"的处理路径（如 follow-up 查询）；unrecoverable unknown 占比应控制（避免 batch 全是死局 case）。详见 a8 §4 line 245。

## 3. W2 端实施位置

按 §1.2 原则二 + W2 phase 1-4 主链：coverage-controlled rejection 在 W2 phase 3（per-world projection）输出后、W2 phase 4（batch 聚合）之前。

### 3.1 实施流程

```text
W2 phase 3: build_normative_projections_for_world(world)
   ↓
   List[NormativeProjection]（per-world per-fragment）
   ↓
   ┌──────────────────────────────────┐
   │ coverage-controlled rejection      │ ← 本章实施位置
   │ accept/reject filter（按 §2 3 类）│
   └──────────────────────────────────┘
   ↓
   accept 的 NormativeProjection 进 batch；
   reject 的触发 W1 重新生成 fragment / 抛弃 / 重复采样
   ↓
W2 phase 4: execute_projection_batch_v2(building_worlds, normative_projection, sidecar_runtime)
   ↓
   Summary.v2.json + Results.v2.parquet + Samples.v2.json
```

### 3.2 输入 / 输出

| 项 | 内容 |
|---|---|
| 输入 | W2 phase 3 已生成的 `NormativeProjection` 列表 + W2 内部 coverage control profile |
| 内部判定 bucket | `near_threshold` / `neighbor_family_overlap` / `recoverable_missing` / `baseline_distribution` / `unrecoverable_unknown_control` |
| 输出到 batch | accepted `NormativeProjection` 列表 + batch 级 `CoverageControlBatchMetadata` |
| 不输出 | per-sample rejection trace 不进入 `NormativeProjection`；coverage target ratio 不作为 evo-agent feature；rejection reason 不回传 W1 |

`CoverageControlBatchMetadata` 字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `coverage_control_profile_id` | str | 如 `CCP-MBIS-V1` |
| `raw_candidate_bucket_counts` | Dict[str, int] | accept/reject 前各 bucket 候选计数 |
| `accepted_bucket_counts` | Dict[str, int] | accept 后各 bucket 计数 |
| `rejected_bucket_counts` | Dict[str, int] | reject 计数 |
| `bucket_definition_version` | str | bucket 定义版本 |
| `public_report_note` | str | 只说明 batch 已做边界覆盖控制，不暴露内部 target ratio |

该 metadata 只用于 batch audit / 大汇报解释，不作为 W1 生成参数，不作为 evo-agent 输入特征.


### 3.3 重采样路径

coverage-controlled rejection 只能在 W2 采样侧丢弃或接受 candidate projection。

允许：

- W2 丢弃当前 candidate，不写入 accepted batch。
- 外层编排重新请求一个新的 W1 candidate。

禁止：

- 把 `near_threshold` / `neighbor_family_overlap` / `recoverable_missing` / `unrecoverable_unknown_control` 传给 W1。
- 把 family id、rule id、threshold value、regime tag、unknown reason code、coverage target ratio 传给 W1。
- 让 W1 根据 W2 rejection 原因调整 fragment、driver、mechanism、measurement 分布。

因此，coverage control 不破坏 W1 rule-blind，也不让 W2 写回 W1 输出.

### 3.4 candidate 粒度澄清（2026-05-31 修订）

本章原文中 accept/reject 所作用的"candidate"在 §1.2/§3.1 的措辞偏 fragment 级、§3.3 的重采样路径偏样本级，存在两可。现澄清为：

**accept/reject 的决策单元 = 一栋楼（building world）的全部 fragment projection 整体取舍。**

- 被 accept 的楼，其全部 fragment 的 NormativeProjection 完整进入 batch（参考真值不缺 fragment）；
- 被 reject 的楼整体不进入 batch（可由外层编排请求新的 W1 candidate 补充，见 §3.3）；
- 楼的桶归属按其 fragment projection 的最高优先级桶判定（近阈值 > 邻族重叠 > 可补缺失 > 基线 > 不可补）；
- 过采桶（近阈值/邻族/可补缺失）为地板桶不削减；不可补 unknown 为上限桶；基线桶为削减池。

**修订背景**：原实现把楼内 4 条 fragment projection 按桶配额裁剪至 1 条，导致数据池每栋楼参考真值残缺（DEBT-044，2026-05-31 修复）。楼级取舍既满足 §1.2 原则一"不修改 NormativeProjection 字段、只做是否 accept 的二元决策"，也满足"被接受样本真值完整"这一参考真值的根本要求。

**留案**：fragment 级 reject + W1 真重采样补齐循环（reject 一个 fragment 即请求 W1 重新生成该楼对应 fragment）作为方案乙留案，依赖 W1 编排增加重采样入口（DEBT-031 gap 4），如需启用须另立工单。

> 修订记录：2026-05-31 夜间自主裁决（用户授权全自动），裁决理由与实施细节见 实验记录/_夜间自主_根上欠账总攻_20260531.md 裁决 J1/J17 与 技术与研究债.md DEBT-044。


## 4. 跟 W1 / evo-agent 的边界

### 4.1 跟 W1 的边界

W1 不运行 coverage-controlled rejection，也不接收 W2 的法规侧 rejection 原因。W1 只负责按 W0/W1 spec 生成新的 candidate。

### 4.2 跟 evo-agent 的边界

evo-agent 后续看到的是已采样的具体 W2 输出，不应看到 W2 内部 coverage target ratio、rejection priority、bucket target 或未接受 candidate 的 trace。

可以对外报告 batch aggregate：例如 accepted batch 中 near-threshold / neighbor-family / recoverable-missing 的覆盖已经被控制；但不得把这些内部采样控制参数作为训练输入特征。

### 4.3 跟 Closure Verifier / 人类巡检的边界

coverage-controlled rejection 只控制数据分布，不改变 `expected_verdict` 语义，不生成最终人工决定.


## 5. 砍除内容

按用户原则 09.md L5-L8 + L20-L25 + W2 规格 00 §3 砍除清单：

### 5.1 observation mask coverage 部分（完整删除）

a8 §4 第五件原文 line 252 含：

> 多样性来自 fragment 模板、driver 组合、多机理耦合、**observation mask、counterfactual pairs**

a8 §4 line 382 + 后续章节涉及 "observation mask 直接由 rule id 决定" 等观察层 coverage 设计，**整段不进 W2 规格**——

| 砍除对象 | 原文位置 | 砍除依据 |
|---|---|---|
| observation mask coverage | a8 §4 line 252 + line 382 后续 | 用户原则 09.md L5-L8：新版系统准备删除巡检员模拟整块功能；observation / evidence / episode 候选删除 |
| counterfactual pairs 在 W2 端实施 | a8 §4 line 252 | 用户原则 09.md L7：HiddenGold / adjudication / benchmark gold 倾向删除；counterfactual pairs 在 evo-agent 训练侧可能保留，**不在 W2 范围** |

**保留**：near-threshold + neighbor-family overlap + recoverable missing 三类 over-sampling（业务上独立于 observation 链，可保留）。

### 5.2 不引入 HiddenGold / ObservationState / QueryEpisode / AdjudicationState

按 W2 规格 00 §3 砍除清单：

- **HiddenGold 不进 coverage-controlled rejection**——不为了 benchmark 配对生成 HiddenGold thin copy
- **ObservationState 不进 coverage-controlled rejection**——不按 observation mask 做 coverage 控制
- **QueryEpisode 不进 coverage-controlled rejection**——不按 query / follow-up 路径做采样
- **AdjudicationState 不进 coverage-controlled rejection**——不按 gold route action / acceptable next question 做采样

## 6. 封口正文边界

本章只定义 W2 coverage-controlled rejection 的 spec 语义。实现状态与工程推进记录不进入封口正文。


## 7. 来源

- coverage-controlled rejection 设计原则：a8 §4 第五件 line 239-252
- 3 种 over-sampling 触发条件：a8 §4 line 243-245
- 采样层控制 vs 世界生成逻辑分开：a8 §4 line 247 + W2 规格 00 §1
- 用户 2026-05-13 D-1 决策：coverage-controlled rejection 归 W2 不归 evo-agent
- W2 端实施位置（projection 之后 batch 聚合之前）：a8 §4 line 241 + W2 规格 03 §1 跨层位置
- 跟 W1 边界（W1 不读 rule_card 不知 family 边界）：W1 规格 09 §1 line 15 + W1 规格 01 §5 rule-blind 红线
- 跟 evo-agent 边界：W2 规格 00 §4.4 + memory `feedback_project_macro_and_evo_agent.md`
- 砍除 observation mask coverage 部分：用户原则 09.md L5-L8 + L20-L25 + W2 规格 00 §3 砍除清单
- 不引入 HiddenGold / ObservationState / QueryEpisode / AdjudicationState：W2 规格 00 §3 砍除清单（用户 2026-05-13 D-2 决策）
- DEBT-031 gap 4：`团队文档/我的笔记/技术与研究债.md` DEBT-031 子表
