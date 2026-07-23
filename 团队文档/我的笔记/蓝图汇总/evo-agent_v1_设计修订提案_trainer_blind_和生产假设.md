# evo-agent v1 设计修订提案：trainer-blind 设计 bug + 生产场景假设

> 用户 2026-05-26 凌晨提的两个根本性疑问，本文档是 Part 1 调研 + Part 2 诊断 + Part 3 修订选项。**本文档不动 spec 不动 code，等用户拍方向后才有第二步。**
>
> 触发对话：用户原话——
>
> > "我现在发现了两个问题，一个是虚构了一些实验室不存在的情况，搞了什么上线之类的假设，但是我们现在是再实验室阶段，没有这些东西。另一个是有关优化器的逻辑，我觉得有点不太对劲，你在前向推理的阶段不能看到真值，不代表你在优化迭代阶段也不能根据真值来更新状态啊。"

---

## Part 1：调研（事实层）

### A. spec 里所有"trainer 不能读 raw W2"的硬约束

| spec 锚点 | 原文 quote | 性质 |
|---|---|---|
| **§1.2 E-004**（行 107） | "**raw evaluator truth 不反写。** evaluator 可读 W2 并产生 `EvalTruthReport`，但 raw truth **不进入 agent runtime、Skill、Policy 或 EvoMemoryStore**。**只有 broker 输出的 `SanitizedFeedbackPacket` 可进入 trainer**。" | 最高原则（E 级别）|
| §1.3 Authority Matrix（行 132） | "W2 truth comparison \| evaluator private store \| 不可见 \| 不可见"（"不可见"列只覆盖 Skill/Policy/LLM 三栏，**没列 trainer**）| 矩阵，留缝 |
| **§2.1.3 evo-trainer-visible**（行 178-194） | "evo-trainer-visible...**不允许读取 raw W2**。...trainer 可以使用 `metric_delta_bucket`、`family_recall_bucket`、`slot_deficit_bucket` 等 sanitized bucket，**不可使用每栋楼的 expected verdict**。" | 边界硬约束 |
| §2.1.4 sanitized-feedback-visible（行 196-209） | "sanitized-feedback-visible 是 `EvoFeedbackBroker` 输出的数据类别...它是 W2-derived 信息**唯一合法回流形态**。"（含 k-anon ≥10 runs / ≥3 buildings、rounding 0.05、delay ≥1 eval window）| 唯一合法通道 |
| §2.2 可见性矩阵（行 219） | "EvalTruthReport \| 禁止(agent) \| 禁止(verifier) \| 写/读(evaluator) \| **禁止(trainer)** \| 读入(broker)" | 矩阵硬约束 |
| §2.3.3 EvoPolicy 禁止字段（行 280-288） | "EvoPolicyVersion 禁止包含：...per_building_reward / per_run_w2_label" | 字段层禁止 |
| §2.5 凭证隔离（行 362-364） | "evo_trainer: deny: - evaluator_truth_store/raw" | 凭证层禁止 |
| §8.1 v1 重写原则（行 1614-1617） | "raw evaluator 不反写；sanitized feedback 经 EvoFeedbackBroker、pre_feedback_ingest_guard、EvoMemoryStore、trainer、gate 后，可间接影响下一版本 Skill/Policy。" | broker 章总纲 |
| §8.2（行 1650） | "该文件不得进入 EvoMemoryStore。Broker 只可读取它并输出 sanitized packet。" | EvalTruthReport raw 不入 store |
| **§8.4.3 F3 layer**（行 1731-1739） | "Evaluator 可在 private replay 中对 candidate Skill/Policy 计算 before/after；**公开给 trainer 的只有：pass/fail / aggregate delta bucket / confidence bucket / leakage pass / closure non-regression pass**。" | spec 隐隐承认要看真值，但**放在 evaluator 角色**而不是 trainer 角色 |
| §9.7.1 EvoPolicy training 输入（行 2204-2212） | trainer 输入清单只列 "ReplayCase / active Skill stats / closure diagnostics / report guard diagnostics / **sanitized feedback packets** / cost metrics / current policy config" | trainer 显式只接 sanitized |
| §9.11 audit log（行 2335-2347） | "raw_w2_access: false" 是 audit log 必填字段 | 审计层强制 |
| §11.9 adversarial probe（行 3041） | "Probe 特征**不可包括 raw W2**。audit 结果只输出 aggregate delta。" | 审计 probe 不接 raw W2 |
| §11.11 source independence audit（行 3069） | "Policy training input list 不含 raw W2 path" | release gate 硬条件 |

**核心观察**：spec 在 14 处独立位置把"trainer 不能看 raw W2"钉死。E-004 是最顶层原则，"E"是 evolution 序列，跟 §1.1 的 8 条最高原则同级，**不修订 E-004 这一切都动不了**。

### B. spec 里所有"生产部署"假设

| spec 锚点 | 原文 quote | 实验室是否需要 |
|---|---|---|
| **§1.2 E-009**（行 117） | "release 可回滚。每个 active SkillSet 与 EvoPolicyVersion 必须有 previous_active_ref、rollback_condition 与 canary metrics。触发 safety fail、closure regression、leakage fail、staleness fail 时自动回滚。" | **不需要**——git revert 解决 |
| §3.6.4 EvoPolicyVersion schema（行 727-763）含 `status` 状态机 + `previous_active_version_id` + `rollback_condition` | active/staged/quarantined/rolled_back 状态 | **过度**——只要二值 loaded/not |
| §3.6.6 EvoReleaseCard（行 801-818） | "ReleaseCard 必须有 canary_plan + rollout_pct + monitoring_window" | **不需要** |
| §8.6 延迟发布（行 1771-1784） | "W2-derived feedback 默认每 10 runs 或每日 eval window 发布一次，且**至少延迟一个 eval window**。" | **不需要**——实验室没"防 leak 信号被实时反推"的部署节奏 |
| §9.5 Skill promotion + §9.7.5 Policy promotion | "draft → candidate → staged → active" 7 态状态机 | **过度**——直接 git 版本管理 |
| **§9.8 Canary rollout**（行 2276-2294） | "canary: traffic_percent: 10 / min_runs: 20 / max_window_days: 2 / rollback_on: leakage_fail: any / closure_regression: any / ..." | **完全工业假设**——没生产 agent，没 % 灰度 |
| **§9.9 Rollback**（行 2296-2312） | rollback_id / artifact_type / trigger_run_id_hash / executed_at | **不需要** |
| §9.10 Batch scheduling（行 2314-2329） | "trace_ingest: after_each_run / feedback_broker_release: every_10_runs_or_daily / canary_start: next_production_window" + spec 自己也意识到："若没有 production traffic，可用 replay-only batch 模式" | spec 自己留了 escape hatch，但**默认是生产假设** |
| §9.12 Minimal v1 implementation path（行 2353-2362） | "v1 工程第一阶段必须实现：...7. release card；**8. rollback**" | rollback 列入必须项 |
| §11.12 成功判定（行 3083） | "improvement persists across **at least 3 release windows**" | "release window"是生产概念 |
| B.7 EvoMemoryStoreConfig（行 819-848） | `runtime_agent_direct_read=False` + `evaluator_raw_truth_read=False` 硬约束 | runtime/evaluator 多 agent 隔离假设——**实验室单机不需要** |

### C. code 端污染范围

| 文件 | 行数 | 跟"trainer-blind"或"生产假设"耦合 |
|---|---|---|
| `evo/release_manager.py` | 248 | **全文耦合**——promote_skill / canary_rollout |
| `evo/rollback.py` | 135 | **全文耦合**——trigger_rollback |
| `evo/feedback_broker.py` | 506 | **全文耦合**——k-anonymity / rounding / release delay 全套 |
| `evo/policy_trainer.py` | 321 | **全文耦合**——`train_from_traces` 输入只接 sanitized feedback packet |
| `evo/audits.py` | ~700 | leakage 11 项含 `broker_output_forbidden_field` / `policy_version_raw_w2_in_training_set` / `evo_memory_store_namespace_violation` |
| `evo/skill_validation.py` | ~700 | Gate record `status` 状态机 |
| `evo/skill_package.py` + `skill_induction.py` | ~900 | candidate/draft/active 状态机 |
| `agent/skill_runtime.py` | ~200 | 只加载 `status="active"` Skill |
| `agent/policy_runtime.py` | ~150 | 只加载 `status="active"` Policy |
| `experiments/scaling_law.py` | ~600 | `effective_trace_count` 跟 `feedback_available_trace_ids` 绑定 |
| `contracts.py` 11 个 evo DTO | ~800 | 字段层固化 `trained_on_feedback_packet_ids` / `release_delay_window_count` / `status` Literal |
| tests/ 8 个 evo test 文件 | ~? | 测试硬编码以上字段 + 行为 |

**总污染量级**：约 **1500+ 行 code** 跟这两条假设耦合，等于 evo 子包 ≥30% 重写。

### D. 实验已暴露的现实信号

| 实验产物 | 暴露的事实 |
|---|---|
| **实验 ⑤**（LLM induction） | 3/3 LLM 真生成 SKILL.md；deterministic Gate 0/1 PASS；但跟 broker / promote / canary **全无交互**——直接 draft → Gate 0 → 输出文件，没走"上线"流程 |
| **实验 ⑥**（broker e2e + audit） | broker 4 agg level + adversarial probe **delta=0.000** + counterfactual swap **delta=0.0000**。**delta=0 的真正原因**：trainer-blind 把信息抹得太干净，probe 学 majority class 就 100% 准，根本无法"反推 truth"——也就**无法学到任何东西**。 |
| **实验 ⑦**（Gate 0 闭环） | 新 Gate 0 真拦得住 LLM 脱稿。但拦的是 **artifact 层** leak（SKILL.md 不能含 raw W2 token），**这正是用户疑问 2 提的"应该 audit 的地方"**——这条 audit 是对的，但它不需要 trainer-blind 撑腰 |
| **实验 ②** baseline vs evo paired | "paired metric delta 全 0" 因为 trainer 没学到东西 + Skill 没真发挥作用。这跟实验 ④ scaling demo 拿不到真信号是同源问题 |

---

## Part 2：诊断（论证层）

### 疑问 2 是真 bug，不是 user 误读

#### 机器学习常识 separation

```
┌─────────────────────────────────────────────────────┐
│ 训练阶段 (offline / trainer process)                │
│   - 输入：features + ground truth labels (FULL)     │
│   - 输出：generalized parameters                    │
│   - W2 truth 必须可见（监督信号没法绕开）           │
├─────────────────────────────────────────────────────┤
│ 推理阶段 (online / runtime agent)                   │
│   - 输入：features only（test set）                 │
│   - 输出：predictions                               │
│   - W2 truth 不可见（否则就是 data leakage）        │
├─────────────────────────────────────────────────────┤
│ 审计阶段 (artifact gate)                            │
│   - 审 artifact 不含 case-specific truth            │
│   - 审 runtime 不能 trigger truth read              │
└─────────────────────────────────────────────────────┘
```

这是 ML 行业 70 年的共识。SGD 训分类器，训练时看 label；推理时不看 label。**没人会说"训练时也不能看 label"**——那等于"训练时禁止训练"。

#### v1 spec 错在哪

E-004 第二句把两件事**捆绑**了：

> raw truth 不进入 agent runtime、Skill、Policy 或 EvoMemoryStore。**只有 broker 输出的 `SanitizedFeedbackPacket` 可进入 trainer**。

逐句拆：

- **"raw truth 不进入 runtime / Skill / Policy"** ✅ 正确——这是 artifact blind，保证下游 runtime 加载 artifact 后不会作弊
- **"raw truth 不进入 EvoMemoryStore"** ⚠️ 半对——Store 如果会被 runtime 读取就该 blind，但如果只是 trainer 工作区就不该 blind
- **"只有 sanitized packet 可进入 trainer"** ❌ 错——把 artifact-blind 错误推广到 trainer 工作流

#### 用一个例子说清

实验 ⑥ 数据：
- 10 traces，全 blocked/open，task_pass_rate 真值散布在 [0.1, 0.4] 之间
- broker.ingest 把 rate rounding 到 0.05 桶 + 把 building_id 抽掉 + 按 rule_family 聚合
- trainer 看到的是 `{rule_family: mbis.X, slot: drainage, metric_bucket: 0.20, run_count: 10}` 这种粗粒度 cell
- trainer 学到："drainage slot 整体 0.20 → 应该加 retrieval weight"
- 学到的 policy 部署后：对所有 drainage slot 加 weight，无差别加权

**问题**：失去了"哪些 case 是 0.4 / 哪些是 0.1"的对比信号。Policy 没法学"在 X 条件下加 weight 更多 / 在 Y 条件下减 weight"——它**只能学全局平均**。

**正确做法**：
- Trainer 看 raw：`run_1: rate=0.42, family=X, slot=drainage, blocked_reason=missing_artifact_evidence`，`run_2: rate=0.11, family=X, slot=drainage, blocked_reason=missing_measurement`
- Trainer 学到"missing_artifact_evidence 时 rate 高 / missing_measurement 时 rate 低 → 应该按 blocked_reason 区分加 weight"
- 输出的 policy 是 `if blocked_reason=missing_artifact_evidence then weight+=0.1 else weight+=0.02`
- 这个 policy artifact **不含**任何 run_id / building_id / 具体 rate 值——它是 generalized rule

这就是 artifact-blind ≠ trainer-blind 的区别。

### 疑问 1（生产场景）也是真问题

不需要论证太多——spec 自己在 §9.10 行 2329 就承认"若没有 production traffic，可用 replay-only batch 模式"。但 spec **默认是生产假设**，等于让我们这种实验室阶段的项目背着 30% 不会被触发的 code 跑。

实证：实验 ①~⑦ **没有一个**走 promote_skill → canary_rollout → rollback 链路。所有 skill 测试都是直接 `assert_skill_package_safe` + `run_gate0_static` + 输出。release_manager.py / rollback.py 整个文件 **0 真实使用场景**，只有单元测试。

### Spec 设计困境的根源

我读 spec 时观察到 §8.4.3 F3 layer（行 1731-1739）暴露了 spec 自己的纠结：

> "Evaluator 可在 private replay 中对 candidate Skill/Policy 计算 before/after；公开给 trainer 的只有 pass/fail / aggregate delta bucket / confidence bucket / leakage pass / closure non-regression pass。"

**spec 知道训练时需要看真值，但把"看真值"硬塞给了 evaluator 角色**——让 evaluator 跑 replay + 算 before/after + 把 bucket 告诉 trainer。这是 spec 在不修 E-004 前提下的妥协方案。

效果是：trainer 退化成"只能调 weight ±0.05"的弱算法（见 §9.7.3 v1 默认 trainer 伪代码 + policy_trainer.py 实现），因为它没拿到能学的信号。

---

## Part 3：修订选项（决策层）

### 选项 A：最小动作——只松"trainer 看 truth"（推荐）

**核心动作**：把 E-004 第二句"只有 broker 输出的 `SanitizedFeedbackPacket` 可进入 trainer"删掉/改写。让 trainer 自由接 W2 truth，但 trainer **输出的 artifact** 必须经 Gate 审查不含 raw W2 信号。

**spec 修订量**：
- §1.2 E-004 改写（保留第一句 artifact blind，删第二句 trainer blind）
- §1.3 Authority Matrix 加一行 "trainer access"
- §2.1.3 evo-trainer-visible 重写（允许读 W2）
- §2.2 可见性矩阵 trainer 列改"读"
- §2.3.3 EvoPolicy 禁止字段保留（artifact 层禁止）
- §2.5 凭证隔离 evo_trainer 加 evaluator_truth_store/raw 到 allowlist
- §8.1 重写"raw evaluator 不反写"为"raw evaluator 不进入 runtime / Skill / Policy artifact，但 trainer 可读"
- §8.4.3 F3 layer 删（evaluator 不需要替 trainer 算 before/after）
- §9.7.1 trainer 输入加 "EvalTruthReport (raw)"
- §9.11 audit log `raw_w2_access` 字段语义改为 "artifact_contains_raw_w2"
- §11.9 adversarial probe 重新定位——probe 现在审 **artifact**，不再审 packet
- §11.11 source independence audit `Policy training input list 不含 raw W2 path` 改为 `Policy artifact output 不含 raw W2 token`

**code 修订量**：
- `contracts.py`: `EvoPolicyVersion.trained_on_feedback_packet_ids` 改 `trained_on_artifacts: List[str]`（可引 raw W2）
- `policy_trainer.py`: `train_from_traces` 输入加 `eval_truth_reports` 参数
- `audits.py`: `_scan_policy_training_raw_w2` 删除（因 trainer 输入允许 raw）；新增 `_scan_policy_artifact_raw_w2`（审 artifact 输出）
- `feedback_broker.py`: **保留**但角色降级——broker 不再是 trainer 信号源，改为 "runtime agent 可选的历史趋势反馈接口"（或干脆暂时不接 runtime，留 spec 不删）

**生产场景假设**：**本选项不动**——canary/rollback/status 状态机保留（避免 scope 蔓延）

**优点**：
- 修订面小（spec 改 12 处 / code 改 4 文件）
- 实验 ⑥ broker e2e 实验产物**仍然有效**（broker 还在，只是不当主信号源）
- 实验 ①②③④⑤⑦ 都不动
- E-004 改写是局部小手术，不破坏 spec 其他章节互引
- **解决用户疑问 2**（trainer-blind bug）

**缺点**：
- **不解决用户疑问 1**（生产场景假设）——canary/rollback/状态机 ~600 行 code 仍然零使用
- spec 内还有 evaluator → trainer 的中间层（§8.4.3 删除后由谁负责算 metric？需要 spec 补一条 "trainer 自己算 metric"）

**工作量级**：spec **中改**（约 12 处 / 200-400 字增删）+ code **小重构**（约 4 文件 / 100-200 行 diff）+ 写新 leakage test

---

### 选项 B：综合动作——松 trainer-blind + 砍生产假设

在选项 A 基础上**加**砍掉生产部署假设：

**额外 spec 修订**：
- §1.2 E-009（release 可回滚）改为 "v1 实验室阶段不要求 canary/rollback；artifact 直接替换 + git 版本管理。生产部署阶段单独提案。"
- §3.6.4 EvoPolicyVersion `status` 简化为 `Literal["draft", "active", "retired"]`
- §3.6.6 EvoReleaseCard 整段删或大幅简化（保留 release_card_id + artifact_version_id + leakage_audit_passed 等核心字段）
- §8.6 延迟发布章节删（broker 已降级）
- §9.5 Skill promotion 7 态状态机简化
- §9.7.5 Policy promotion 同上
- §9.8 Canary rollout **整段删**
- §9.9 Rollback **整段删**
- §9.10 Batch scheduling 改为 "实验脚本驱动"
- §9.12 Minimal v1 implementation path 第 7-8 项删
- §11.12 "3 release windows" 改为 "3 独立 ablation runs"

**额外 code 修订**：
- `release_manager.py` 248 行：**整文件废弃**（或简化为 50 行的"load + save artifact"）
- `rollback.py` 135 行：**整文件废弃**（或保留 stub 接 git 版本）
- `skill_validation.py` 状态机简化
- `skill_runtime.py` 加载逻辑改为 "load all not-retired"
- `policy_runtime.py` 同上
- tests/ 8 个 evo test 适配

**优点**：
- **同时解决两个疑问**
- 砍掉 ~600 行无场景 code，evo 子包变薄
- spec 跟实验室阶段真实匹配

**缺点**：
- **修订面大**——spec 改 ~25 处 / code 改 ~8 文件 / ~600 行删除
- 部分实验产物失效（实验 ⑥ broker audit summary 部分指标需重算）
- 后期真到生产部署阶段还要重写——但 spec 可以另立 v1.5 production deployment 章节

**工作量级**：spec **大改**（~25 处修订）+ code **中重构**（~600 行删除 + 部分接口改造）

---

### 选项 C：维持现状 + 写 disclaimer

不动 spec 不动 code，在 spec 顶部加一段 "v1 实验室阶段 disclaimer"：
- "本 spec 写于工业部署假设下，实验室阶段 §8 broker 延迟、§9.8 canary、§9.9 rollback、§9.10 scheduler 等条款**不强制执行**，可用 minimal stub"
- "trainer-blind 在 v1 实验室阶段保留，但已知**会显著限制 trainer 学习能力**；待第一次 paired metric 显示 evo<baseline 时按选项 A 修订"

**优点**：
- 0 修改
- 保留 spec 完整性（万一以后真到生产部署阶段，spec 现成）

**缺点**：
- 不解决任何问题
- 实验 ②④ paired metric 全 0 的问题继续存在
- 持续制造"spec 说一套 / 实际跑一套"的认知负担

---

## Part 4：推荐 + 决策候选

### 我的推荐

**选项 A**（最小动作，先松 trainer-blind）。理由：

1. **疑问 2 比疑问 1 优先级高**——trainer-blind 是真实卡住实验 ②④ paired metric 的元凶，不修就没法做有意义的 evo 学习曲线实验（论文一级目标）
2. **疑问 1 砍生产假设的边际价值低**——code 跑得通、单元测试 PASS，"无用 code"是技术债但不是 blocker
3. **选项 A 修订面可控**——12 处 spec / 4 个 code 文件 / 一次 commit 能完成
4. **选项 A 跟实验 ①~⑦ 兼容**——已发布的实验产物不需要重跑
5. 砍生产假设可以**等评估完选项 A 效果后**再单独提案

### 等用户拍

请用户拍：

- [ ] **选项 A** — 只松 trainer-blind，砍生产假设留待后续
- [ ] **选项 B** — 同时松 trainer-blind + 砍生产假设（一次大改）
- [ ] **选项 C** — 维持现状 + 加 disclaimer
- [ ] **其它** — 你想到的别的方向（告诉我）

---

## ⏳ 留下的尾巴

1. **代理 B 在另一份调研里发现** `code/SKILL.md` 引用 spec 节号大面积漂移（如 `§7.5.2 / §7.3.6 / §1.0 原则 8` 等 v1 spec 不存在的节号）。本提案没处理这条，属独立 gap。若选项 A/B 落地，建议**一次性同步**修引用。
2. **v0.4 spec 原文未核**——v1 spec 多处说"继承 v0.4 §X"，代理 B 没核 v0.4 spec。本提案的"E-004 顶层原则"判断是基于 v1 spec 原文，若 v0.4 spec 对 trainer-blind 有更原始的论证（比如安全模型论证），需追核 v0.4 才能拍 spec 修订是否破坏继承链。
3. **CoreSkills / OperationalSkills / MetaSkills 三层架构是否受影响**——选项 A 主要动 E-004 + §8 + §9.7，没动 §7.3 Skill 分层。但 §7.3.2 OperationalSkill 描述里"由 evo loop 自动生成 / 验证 / 激活 / 淘汰"假设 evo loop 走完整 promote → active → retire 流程，**砍生产假设（选项 B）时需要 review §7.3 措辞**。
4. **scaling law 论文一级目标 vs 实验室成熟度**：spec §11.6 paired held-out 实验协议假设有多个 release window 跑 3 次以上验证 improvement persist。选项 A 不动这条，但实验 ④ scaling demo 已经暴露"没有真 release 窗口"的现实——这条 spec 跟实验室能跑的真实条件错位，**未来跑论文级实验时迟早要处理**。
5. **本提案没动 v1 spec 文件**——只新建本 markdown。等用户拍方向后再分两步：(a) spec 修订工单 (b) code 重构工单。
