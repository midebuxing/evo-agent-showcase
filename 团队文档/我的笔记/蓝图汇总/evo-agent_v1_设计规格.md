我读完了 round-1 我自己回复 + 8 个基底目录，v1 spec 整本起草遵守 6 条原则，具体对应如下：原则 1 → **evo-agent blind 红线**：自进化链路不得让 agent、runtime prompt、OperationalSkill、Rule-Skills KG 或 EvoPolicy 看到 W2、expected verdict、NormativeProjection、basis item、W2 threshold truth；原则 2 → **deterministic backbone 不可移交**：allow_stop、closure_status、satisfaction_status 永远由 closure verifier 决定，Skill/Policy 只能影响检索、调度、报告组织与经验沉淀；原则 3 → **副驾驶定位**：agent 输出始终是辅助审查报告或闭包未完成说明，不给最终合规裁决；原则 4 → **spec→code 单向**：本 v1 spec 是工程实现权威，现有 baseline code 与 v1 冲突时改代码；原则 5 → **不屏蔽信息防护**：agent 可看完整 agent-visible 法规、rule_card、事实与阈值，防护依靠 hook、broker、gate、audit，而不是删减合法信息；原则 6 → **pro 工程估值是权威**：本文所有阈值、批量大小、promotion/retirement 条件、采样数、默认预算均为 v1 当前权威，不写“待专家确认”。  

# evo-agent v1 全量实现级设计规格

版本：v1.0  
日期：2026-05-23  
状态：evo-agent 完整实现级规格；从 baseline v0.4 升级为带运行期自进化的主规格。  
适用范围：香港 MBIS 场景下，基于双源 KG-RAG、deterministic closure verifier、LLM-as-brain agent runtime、EvoSkillPackage、EvoFeedbackBroker 与运行时 Scaling Law 实验框架的合规助手代理系统。  

---

# §0 Version, Scope, Terminology, Non-Goals

## §0.1 v1 与 v0.4 的关系

v1 继承 `evo-agent_baseline_设计规格_v0.4.md` 的 baseline 主体：双源 KG-RAG、Fact KG、RuleCard KG、deterministic closure verifier、`ComplianceAssessmentRun`、4 个手工 seed Skill、hook 防线、独立 evaluator、报告副驾驶定位。v1 的修订目标不是重写 baseline，而是在 baseline 之上把 round-1 已采纳的自进化机制落成可派工程的完整规格。

v1 的核心增量是三件事：  
1. **EvoRunTrace + Replay Buffer**：每次 run 的 agent-visible 过程、tool 调度、候选集、hook、closure 与报告产物进入可审计经验记忆层；  
2. **EvoSkillPackage + Skill Population Lifecycle**：Skill 从单个 `SKILL.md` 文件升级为机器可校验、可验证、可激活、可回滚、可淘汰的目录级容器；  
3. **EvoFeedbackBroker + EvoPolicyVersion**：evaluator 的 raw W2 真值不反写 agent，只有经盲化、聚合、延迟、审计的 `SanitizedFeedbackPacket` 可进入 evo trainer，并由 trainer 产出 versioned policy 和 gated Skill。

v1 不受当前 baseline 代码形态约束。当前 11 个 tool、4 个 seed Skill 文本、orchestrator 循环、hook 分层、目录路径，都是 v0.4 的实现选择；v1 可以要求新增模块、字段、tool、hook、schema 与测试。若实现与本规格冲突，工程以本规格为准。

## §0.2 范围

v1 覆盖以下系统边界：

- agent-visible 事实与规则载入；
- Rule-Skills KG 与 EvoMemoryStore 的 schema；
- SkillPackage loader、EvoPolicy loader 与 staleness guard；
- skill-aware retrieval、policy-aware ranking 与 verifier candidate universe floor；
- deterministic closure verifier 的 v1 instrumentation；
- agent runtime 的 prompt、tool、Skill 分层、hook 与报告契约；
- evaluator 与 EvoFeedbackBroker 的盲化反馈协议；
- Replay Buffer、Skill induction、Skill validation、EvoPolicy training、promotion、retirement 与 batch scheduling（v1.1 删除：rollback、canary——见 §0.6 修订 2 + §9.8 / §9.9 / §9.10）；
- Runtime Scaling Law 实验协议、指标、ablation 与泄漏审计；
- DTO schema、测试、发布 gate 与 v0.4 迁移路径。

v1 不覆盖 W0/W1/W2 数据生成层设计，不修改 worldgen、sidecar、NormativeProjection 或 expected verdict 的上游契约；这些输入已封口，v1 只消费。

## §0.3 关键术语

**agent-visible**：agent runtime、closure verifier、Skill runtime、policy-aware retrieval 可以读取的数据类别，包括 W0/W1 building facts、sidecar runtime facts（写图前丢弃 `projection_id`）、法规原文、rule_card v2、CoreSkills、active OperationalSkills、active EvoPolicy、closure result、hook audit、agent-owned per-run feedback。

**evaluator-only**：只有 evaluator private store 可读取的数据类别，包括 W2 `NormativeProjection`、`expected_verdict`、projection tables、threshold evaluations、basis items、per-run truth comparison、raw evaluator comments。

**evo-trainer-visible**：evo trainer 可读取的数据类别，包括 `EvoRunTrace`、Replay Buffer、closure-derived diagnostics、report guard diagnostics、SkillValidationRecord、active/candidate Skill metadata、SanitizedFeedbackPacket。evo trainer 不可读取 raw W2。

**sanitized-feedback-visible**：由 EvoFeedbackBroker 输出、可进入 EvoMemoryStore 的盲化反馈数据。它可以来自 W2-derived aggregate metric，但必须满足 batch size、k-anonymity、rounding、delay 与 forbidden-field scan。

**EvoRunTrace**：一次 `ComplianceAssessmentRun` 的可审计经验记录。它记录 agent-visible 输入、tool steps、candidate set hash、Skill invocation、policy decision、closure/report refs、hook results、cost、fallback 与 sanitized feedback refs，不记录 raw W2。

**EvoSkillPackage**：v1 Skill 的目录级容器。至少包含 `skill.json`、`SKILL.md`、`validation_records.jsonl`，routing/retrieval 类 Skill 必须包含 `plan.yaml`。`skill.json` 是机器权威源，`SKILL.md` 是 LLM-readable view。

**EvoPolicyVersion**：可加载到 runtime 的版本化策略配置，控制 tool 调度偏好、retrieval ranking 权重、candidate cutoff、Skill 激活排序、open obligation 深查顺序、报告模板选择、fallback 阈值。它不能修改 verifier 的 allow_stop 逻辑。

**EvoFeedbackBroker**：evaluator private store 与 evo trainer 之间的强制代理组件。它接收 `EvalTruthReport`，输出 `SanitizedFeedbackPacket`，并执行字段过滤、聚合、延迟、k-anonymity、rounding 与 W2 reconstruction audit。

**verifier candidate universe floor**：v1 检索不变量。Skill/Policy 可增加、重排、标注候选，但不得未经 deterministic coverage floor 削窄 closure verifier 的候选规则宇宙。所有 score>0 且未被 deterministic 规则排除的 rule candidates 必须进入 verifier candidate universe，或由 verifier-side expansion 补齐。

## §0.4 Non-Goals

v1 明确不做以下事项：

1. 不修改 W0/W1/W2 数据生成层，不新增或重写上游字段，不让 evo-agent 反向要求 worldgen 生成特定答案；
2. 不把 closure verifier 改成 LLM-driven，不让 LLM 或 Skill 决定 `allow_stop`、`closure_status`、`satisfaction_status`；
3. 不让 agent 输出最终合规裁决，不把报告变成审批决定；
4. 不把 evaluator raw truth、W2 expected verdict、basis item、projection 或 W2 threshold truth 写入 agent KG、Skill、prompt、report 或 EvoPolicy；
5. 不把自进化实现成单次 run 内 LLM 自改系统提示或自发布 Skill；所有演化产物必须经过 gate 与版本发布；
6. 不依赖屏蔽合法法规、阈值或事实来防泄漏；合法 agent-visible 信息完整可见；
7. 不继承旧设计中已废止的概念角色。以下名称只在本节作为禁止清单出现，v1 不使用其语义：`巡检员模拟`、`HiddenGold`、`latent case`、`observation 主链`、`QueryEpisode`。

## §0.5 v1 文档阅读口径

继承章节采用“继承 v0.4 §X，本节 v1 修订要点”写法。未在 v1 显式修改的 v0.4 约束继续有效；若 v0.4 与 v1 冲突，以 v1 为准。v1 中的数字阈值、枚举、字段名与生命周期状态为当前权威，工程实现不得替换为“经验值”或“临时值”。

## §0.6 v1.1 修订（2026-05-26，trainer-blind + 生产假设大改）

本节记录 2026-05-26 用户拍板的两项根本性修订，影响 §1.2 E-004 / E-009、§2.1.3 / §2.1.4、§2.2、§2.5、§3.6.4 / §3.6.6、§8.1 / §8.4.3 / §8.6、§9.5 / §9.7 / §9.8 / §9.9 / §9.10 / §9.11 / §9.12、§11.9 / §11.11 / §11.12。原 pro round-2 起草 v1 spec 时按工业级 robust agent 部署模板套了两条不合实验室阶段的假设，本次一并修订：

**修订 1：松 trainer-blind**。原 E-004 把"artifact 层 blind"（runtime / Skill / Policy artifact 不含 raw W2）与"trainer 工作流 blind"（trainer 不能读 raw W2）捆绑。机器学习常识 separation 明确：训练阶段看 ground truth 是天经地义，推理阶段不看才是 data leakage。v1 把两件事拆开：

- **保留**：artifact 层 blind——trainer 产出的 policy / Skill artifact 不得含 raw W2 token、case-specific truth value、per-building/per-run label。这是 audit 的真正落点。
- **保留**：runtime 层 blind——runtime agent 推理时不能读 W2 truth、不能 trigger truth read tool。
- **删除**：trainer 工作流 blind——trainer 自由读 `EvalTruthReport` raw + traces + observations，自由算 reward / loss / counterfactual。trainer 输出 artifact 时受前两条约束。

**修订 2：砍实验室阶段不需要的生产部署假设**。v1 实验室阶段（单机、无 production agent、无运维、无灰度概念）不需要 canary / rollback / status 7 态状态机 / release window / production traffic 假设。砍以下条目：

- §9.8 Canary rollout 整段删
- §9.9 Rollback 整段删
- §9.10 Batch scheduling 改为"实验脚本驱动"
- §9.7.5 / §9.5 promotion 状态机从 7 态简化为 `["draft", "active", "retired"]` 3 态
- §3.6.6 EvoReleaseCard 简化（保留 audit 必要字段，删 canary_plan / monitoring_window 等）
- §8.6 broker 延迟发布章节删
- §9.12 minimal v1 implementation path 第 7-8 项（release card / rollback）删
- §11.12 "3 release windows" 改为 "3 独立 ablation runs"
- §1.2 E-009 改写

砍掉的生产部署能力作为 v1.5 production deployment 章节备用，未来真到部署阶段时重新立 spec。

**实验产物兼容性**：实验 ①②③④⑤⑥⑦ 全部继续有效。实验 ⑥ broker audit summary 中 §11.9 adversarial probe / §11.10 counterfactual swap 的 audit 位置发生重定位（从 audit packet 改为 audit artifact），需要按新 §11.9 / §11.11 重跑 audit；其余 leakage 11 项判定不受影响。

**审计落点重定位**：原 §11.9 audit "sanitized packet 是否泄漏 raw W2"逻辑错位（包不是危险路径，artifact 才是）。v1.1 后 §11.9 改为 audit "policy / Skill artifact 是否含 raw W2 信号"。§11.11 source independence audit 同步修订字段。

**修订追溯**：完整修订调研、诊断、选项比较见 `团队文档/我的笔记/蓝图汇总/evo-agent_v1_设计修订提案_trainer_blind_和生产假设.md`（2026-05-26）。

### §0.6.1 全局状态映射规则（v1.1 → v1.0 旧引用的解读）

本次修订只精确改了 v1.0 中**显式定义状态机**的章节（§9.5 / §10.6 / §3.6.4 / §3.6.6）。spec 全文其它段落（§3.4.3 SkillVersion schema、§4 loader、§7 hooks、§9.1 总览伪代码、§9.4 Gate fail 行为等）若仍出现旧 7 态名（`candidate`、`staged`、`rolled_back`、`quarantined`）或 canary 相关条件，按以下**全局映射规则**解读：

| v1.0 旧引用 | v1.1 解读 |
|---|---|
| `draft` | 仍是 `draft`（trainer 工作区内的迭代态）|
| `candidate` | 视为仍是 `draft`（v1.1 把 v1.0 的"Gate 0/1 pass 后中间态"合进 draft）|
| `staged` | 视为仍是 `draft`（v1.1 无 canary，"等待 holdout / canary"状态不存在）|
| `active` | 仍是 `active`（Gate 0-4 全 pass 后，无中间过渡）|
| `quarantined` | 视为 `retired` + git revert（v1.1 无独立隔离态）|
| `rolled_back` | 视为不存在的状态（git revert 代替）|
| `retired` | 仍是 `retired` |
| "promote draft → candidate → staged → active" | 视为 "promote draft → active（须全 Gate 0-4 + leakage pass）" |
| "canary plan 存在" 作为 promotion 条件 | 视为不存在的条件（删）|
| "canary failure 自动 rollback" | 视为 "active 出 fail → 改 retired + git revert" |
| ReplayCase `purpose` enum 含 `canary` | v1.1 删 `canary`，purpose 改为 `skill_induction` / `skill_validation` / `policy_training` / `holdout` 四值 |

实现侧若发现 spec 旧 7 态字段仍有规定（如 `quarantine_reason` 字段），按 "v1.1 简化后该字段不再 required（保留 schema 兼容性，新建 artifact 不填）" 处理。后续 spec 维护时可逐字 patch；本次修订不阻塞 code 重构。

---

# §1 Principles + runtime evolution principles

## §1.1 继承 v0.4 §1.0 的八条原则

v1 继承 v0.4 §1.0 的八条最高优先级原则，并将原则 6 从“baseline 不带 evo，但留接口”修订为“v1 实现 evo，但 evo 不越过底线层”。

| # | v0.4 原则 | v1 继承 / 修订 |
|---:|---|---|
| 1 | 副驾驶定位 | 继承。所有报告为人工审查辅助材料，不输出最终裁决。 |
| 2 | 闭包验证属于合规助手代理本身 | 继承。closure verifier 是 runtime 底线层组件，不属于 W2。 |
| 3 | evo-agent blind | 继承并扩展到 Skill、Policy、Replay、Feedback、Trainer 全链路。 |
| 4 | W0/W1/W2 是已封口固定上游 | 继承。v1 不动数据生成层。 |
| 5 | 确定性底线层防幻觉 | 继承。`allow_stop` 只能由 deterministic verifier 输出。 |
| 6 | baseline 不带 evo，但留接口 | 修订。v1 启用 evo，但只优化检索、调度、报告组织、Skill 选择和经验沉淀。 |
| 7 | 旧设计资料只作参考 | 继承。废止术语不得进入 v1 概念模型。 |
| 8 | spec→code 单向 | 继承。本规格为实现权威。 |

## §1.2 Runtime evolution 子原则

v1 新增以下 runtime evolution 子原则，编号为 E-001 至 E-010。

**E-001：演化产物必须版本化。** Skill、Policy、Feedback packet、Replay set、release card 均必须有不可变 id、version、created_at、source hash 与 validation record。禁止原地覆盖 active artifact。

**E-002：LLM 只能起草，不可自证。** LLM 可以提出 candidate Skill、diagnostic hint 或 policy patch，但不能宣布其有效；有效性由 deterministic gate、replay、holdout、leakage audit、closure non-regression 与 release gate 决定。

**E-003：演化只能增加或重排 evidence search，不得隐藏规则。** Skill/Policy 可扩展 retrieval plan、调整排序、优先深查 open obligations、选择报告结构；不得缩小 verifier 规则宇宙，不得移除可适用 rule_card，不得改变 obligation derivation 语义。

**E-004：raw evaluator truth 不进入 runtime artifact，但可进入 trainer 工作流。** evaluator 可读 W2 并产生 `EvalTruthReport`。**artifact 层 blind**：runtime-loadable artifact（agent runtime 加载的 SkillPackage active subset、EvoPolicy active subset、agent KG、Fact KG、Rule-Skills KG、报告产物）不得含 raw W2 token、per-run truth label、per-building expected verdict、case-specific basis item ref。**trainer 工作流 blind 取消**：evo trainer 可直接读 `EvalTruthReport` raw、agent traces、observations、closure diagnostics，自由计算 reward / loss / counterfactual / before-after metric；trainer 产出的 candidate artifact 必须经 Gate 0 静态扫确认不含 raw W2 信号后才能 promote 为 active。`SanitizedFeedbackPacket` 角色降级为 runtime agent 可选的"历史趋势反馈接口"（runtime 想看跨 run 历史模式时可读 packet），不再是 trainer 信号源。

**E-005：agent-owned 反馈可细，runtime 可见的 W2-derived 反馈必须粗。** closure open/blocked reason、hook audit、report guard 是 agent-owned，可 per-run/per-obligation 使用。**W2-derived feedback 仅当对 runtime agent 暴露时**（如 broker 输出的 `SanitizedFeedbackPacket` 进入 runtime trend feedback 接口）必须满足 batch aggregate、k-anonymity、rounding 与延迟发布。**trainer 工作流内对 W2-derived 信息无此限制**，trainer 可直接读 raw `EvalTruthReport`（见 E-004）。

**E-006：所有 active OperationalSkill 必须可回放验证。** active Skill 必须有 source traces、validation records、staleness check、runtime activation stats 和 retirement rule。没有 validation 的 Skill 只能是 draft，不得加载到 runtime。

**E-007：CoreSkills 不由 evo loop 自动淘汰。** Layer 0 CoreSkills 是宪法层流程纪律；它们只能通过 spec revision 修改。Layer 1 OperationalSkills 可自动生成、验证、激活、淘汰。Layer 2 MetaSkills 在 v1 定义但默认禁用自动激活，任何变更 Skill generator 本身的能力只能经 spec revision 或 release gate 人工批准。

**E-008：学习曲线必须区分经验量与作弊信号。** 只有通过 leakage audit、schema audit、source audit、closure audit 的 effective trace 才计入 `E_runtime`。任何 invalid trace 不能用于 Skill induction、Policy training 或论文指标曲线。

**E-009：v1 实验室阶段不强制 canary / rollback / status 状态机；直接 git 版本管理。** v1 实验室阶段（单机、无 production agent、无持续运维）的 Skill / Policy 版本演进通过 git commit 推进 + `status` 简化为 `["draft", "active", "retired"]` 三态。`active` artifact 出现安全 fail / closure regression / leakage fail / staleness fail 时，直接 retire 并切回上一 git revision 的 active 版本；不要求 canary traffic percent、灰度 traffic 切流、rollback artifact id 等工业部署语义。本条仅 v1 实验室阶段适用；正式 production 部署时由 v1.5 production deployment 章节单独立条。

**E-010：报告不得引用训练信号。** 辅助报告可列 Skill invocation provenance，但不得引用 evaluator feedback、W2-derived aggregate metric 或 policy reward 作为建筑证据。

## §1.3 Authority Matrix

| 决策对象 | 唯一权威 | Skill/Policy 权限 | LLM（runtime）权限 | evo trainer 权限 |
|---|---|---|---|---|
| `allow_stop` | deterministic closure verifier | 无 | 无 | 无 |
| `closure_status` | deterministic closure verifier | 无 | 无 | 无 |
| `satisfaction_status` | deterministic closure verifier | 无 | 无 | 无 |
| rule candidate universe floor | deterministic retrieval + verifier expansion | 只能增加/排序 | 可请求解释，不可削弱 | 可在训练时分析，但产出的 policy 仍须保 floor |
| retrieval order | active EvoPolicy + active OperationalSkills | 可控制 | 可按 policy 调工具 | 训练时可优化排序权重 |
| report section organization | CoreSkill + report_structure Skill + report guard | 可控制 | 可生成 | 训练时可优化模板选择策略 |
| Skill promotion | Skill validation gates + Gate 0-4 + leakage audit | 产物候选 | 可起草 | **可读 raw W2 + traces 训练产生 candidate**；candidate 进 active 前必过 Gate 0 静态扫 |
| W2 truth comparison | evaluator private store | 不可见 | 不可见 | **可见**（E-004 修订后）；trainer 自由读 raw W2 truth、`EvalTruthReport`、per-run truth label |
| W2 信息进入 runtime artifact | 禁止 | 不允许 artifact 含 raw W2 | 不允许 LLM 输出含 raw W2 token | trainer 输出的 candidate artifact 必须经 Gate 0 静态扫确认不含 |
| sanitized feedback packet（broker 输出）| EvoFeedbackBroker + pre_feedback_ingest_guard | 可读取 packet（runtime trend feedback）| runtime LLM 可经 tool 看 packet trend，不读 raw | **不再是 trainer 的主信号源**；trainer 直接读 raw 即可，packet 只作 runtime 暴露通道 |

---

# §2 Data Visibility 4 类边界

## §2.1 四类可见性定义

v1 将 v0.4 的 agent-visible / evaluator-only 二分扩展为四类边界：`agent-visible`、`evaluator-only`、`evo-trainer-visible`、`sanitized-feedback-visible`。四类边界不是权限建议，而是 hard contract。任何数据对象必须声明一种主可见性；跨边界复制必须通过本节定义的 adapter 或 broker。

### §2.1.1 agent-visible

agent-visible 数据可以被 agent runtime、closure verifier、KG retrieval、CoreSkills、active OperationalSkills、report writer 读取。允许来源包括：

- W0/W1 WorldBundle 与 sidecar runtime facts，按 v0.4 allowlist 载入；
- sidecar facts 中除 `projection_id` 及其任何 hash/ref 变体以外的 agent-visible 行政事实；
- 法规原文 markdown；
- rule_card v2 bundle、family index、semantic slot registry、measure registry、artifact registry；
- Layer 0 CoreSkills；
- active Layer 1 OperationalSkills 的 `SKILL.md` rendering、safe `skill.json` subset 与 `plan.yaml` safe subset；
- active `EvoPolicyVersion` 的 runtime-safe subset；
- deterministic closure result、open/blocked reason、hook audit；
- agent-owned per-run diagnostics，如 missing_fact、missing_measurement、schema_contract_violation、report citation guard。

agent-visible 禁止字段继承 v0.4 Appendix A，并新增 feedback/skill/evo 相关禁止项。任何 agent-visible 对象不得含 `expected_verdict`、`projection_id`、`basis_items`、`EvalTruthReport`、`raw_metric_by_run`、`truth_label`、`w2_basis_ref`、`projection_family`、`matched_component_refs`、`matched_measurement_ids`、`coverage_status`、`pass_bool`（若来源 W2）、`regime_tag`（若来源 W2）。

### §2.1.2 evaluator-only

evaluator-only 数据只能由 evaluator private store 读取，用于独立阅卷和 raw metric 计算。包括：

- `normative_projection_meta.parquet`
- `projections.parquet`
- `matched_families.parquet`
- `threshold_evaluations.parquet`
- `coverage_control_metadata.parquet`
- `basis_items.parquet`
- W2 `NormativeProjection`
- W2 `expected_verdict`
- per-run expected outcome comparison
- W2 threshold truth、basis item、projection coverage status
- `EvalTruthReport` raw file
- evaluator raw notes

evaluator-only 数据可以读取 agent artifacts；但 agent runtime、SkillPackage loader、EvoPolicy loader、EvoMemoryStore 默认读路径不得访问 evaluator-only store。若 evaluator 使用 Neo4j，必须使用独立 database 与独立 credential。若 evaluator 使用 parquet/DuckDB，路径不得传入 agent loader 配置。

### §2.1.3 evo-trainer-visible

evo-trainer-visible 是 v1 新增边界（v1.1 §0.6 修订后扩展）。它允许 evo trainer 读取跨 run 经验、agent traces、sanitized feedback、**以及 evaluator private store 中的 raw W2 truth**（包括 `EvalTruthReport`、per-run expected outcome、W2 threshold truth）。包括：

- `EvoRunTrace`
- Replay Buffer 中的 `ReplayCase`
- `ComplianceAssessmentRun` 的 v1 runtime metadata
- closure result refs、report refs、hook results、cost metrics
- `SkillValidationRecord`
- candidate SkillPackage
- active Skill metadata（v1.1 status 简化为 draft/active/retired，见 §3.6.4）
- active EvoPolicy metadata（同上）
- `SanitizedFeedbackPacket`（runtime trend feedback 接口；trainer 训练无需依赖）
- release evaluation card aggregate metrics
- policy/skill ablation aggregate result
- **`EvalTruthReport` raw**（v1.1 新增，evaluator private store 文件，trainer 可 mount 读取）
- **W2 NormativeProjection / projections / threshold_evaluations / basis_items**（v1.1 新增，trainer 可读用于 reward / loss 计算，但 artifact 输出受 Gate 0 静态扫约束）

trainer 训练过程内可自由使用上述任何信号计算 loss / reward / counterfactual / before-after metric。**trainer 输出的 candidate artifact**（candidate SkillPackage、candidate EvoPolicyVersion、candidate report template）必须再经 §9.4 Gate 0-4 + §11.11 source independence audit 验证不含 raw W2 token / case-specific truth value / per-run label，才能 promote 为 active 进入 agent-visible runtime。

**与 v1.0 区别**：v1.0 原本禁止 trainer 读 raw W2，要求 trainer 只能用 sanitized bucket。v1.1 取消该限制（见 §0.6 修订 1），原因：artifact 层 blind 与 trainer 工作流 blind 是两件事，前者是必要的（runtime 加载 artifact 不能作弊），后者是错误捆绑（trainer 看 ground truth 是 ML 监督学习常识）。

### §2.1.4 sanitized-feedback-visible

sanitized-feedback-visible 是 `EvoFeedbackBroker` 输出的数据类别（v1.1 角色降级，见下）。它必须满足：

- batch size ≥10 runs；
- 每个公开 cell 覆盖 ≥10 runs 且 ≥3 buildings；
- 反馈按 rule family、semantic slot class、obligation kind、error taxonomy 聚合；
- 数值四舍五入到 0.05 粒度，或使用 `low/medium/high` bucket；
- 不列 run_id 明细、不列 building_id 明细、不列 projection_id；
- 不包含 expected verdict、basis item、W2 threshold observed value、per-run missing item；
- 通过 `pre_feedback_ingest_guard`。

**v1.1 角色降级**：sanitized-feedback-visible 不再是 trainer 信号源（trainer 直接读 raw EvalTruthReport，见 §2.1.3）。它的剩余角色是 **runtime agent 可选的"历史趋势反馈接口"**——runtime LLM 想看跨 run 历史模式时可通过 tool 读取 packet。该接口在 v1.1 实验室阶段非必选实现；可保留 broker 代码作为接口契约，但 trainer 工作流不强制走 broker。**§8.6 延迟发布要求 v1.1 删除**（无 production traffic 防 leak 节奏需求）。**§11.9 reconstruction audit 重定位**：原本审 packet 是否泄漏 W2，v1.1 改为审 candidate artifact 是否泄漏 W2（见 §11.9 v1.1 修订）。

sanitized-feedback-visible 可以写入 EvoMemoryStore（仅当真启用 runtime trend feedback 接口时），但不得作为 Fact KG evidence、RuleCard clause 或 report evidence 被检索。

## §2.2 可见性矩阵

| 数据对象 | agent runtime | closure verifier | evaluator | evo trainer | feedback broker |
|---|---:|---:|---:|---:|---:|
| W0/W1 fact parquet allowlist | 读 | 读 | 读 | 通过 trace/ref 读 | 不需要 |
| sidecar `projection_id` 原值/hash | 禁止 | 禁止 | 可读上游但不得回写 | 禁止 | 禁止输出 |
| rule_card v2 | 读 | 读 | 读 | 读 | 可用于聚合标签映射 |
| regulation markdown | 读 | 读 | 读 | 读 | 不需要 |
| W2 projection tables | 禁止 | 禁止 | 读 | **读**（v1.1 修订，trainer 训练用）| 读入但不输出原文 |
| `EvalTruthReport` | 禁止 | 禁止 | 写/读 | **读**（v1.1 修订，trainer 直接读 raw 算 reward/loss）| 读入（v1.1 起 broker 不再是 trainer 主信号源）|
| `SanitizedFeedbackPacket` | 不直接读（runtime trend tool 可读）| 不读 | 可读 | 可读但**非主信号源**（v1.1 修订）| 写（角色降级，见 §2.1.4）|
| `EvoRunTrace` | runtime 写安全摘要 | closure refs | 可读 agent artifacts | 读 | 可读 trace metadata，不读 raw prompt |
| `EvoSkillPackage` draft/candidate | 不加载 | 不读 | 可审计 | 读写 | 不读 |
| `EvoSkillPackage` active（v1.1 status 仅 draft/active/retired）| 读 runtime-safe subset | provenance only | 可审计 | 读 | 不读 |
| `EvoPolicyVersion` active | 读 runtime-safe subset | 不读裁决规则 | 可审计 | 读写 | 不读 |
| **candidate artifact**（v1.1 显式行）| **禁止加载**（必过 Gate 0-4 + leakage audit 后 promote 才能 active）| 不读 | 可审计 | 写（trainer 输出） | 不读 |

## §2.3 禁止字段分类

### §2.3.1 agent-visible 禁止字段

继承 v0.4 §2.2.3 与 Appendix A，新增：

```text
EvalTruthReport
raw_eval_truth
raw_w2_metric
truth_label
expected_label
reference_outcome
w2_basis_ref
basis_item_id
projection_cell_id
per_run_confusion
raw_metric_by_run
w2_threshold_truth
w2_observed_value
w2_expected_operator
feedback_truth_comment
leaked_expected_verdict
```

### §2.3.2 SkillPackage 禁止字段

Skill 包任何文件禁止出现：

```text
expected_verdict
NormativeProjection
basis_items
projection_id
EvalTruthReport
truth_label
pass/fail answer pattern for a building
force allow_stop
override verifier
final decision
building_id literal
world_id literal
run_id literal
projection_id literal
```

`building_id literal`、`world_id literal`、`run_id literal` 指真实样本 id 或其可逆 hash；Skill 可引用抽象 scope，如 `rule_family=mbis.reporting.inspection_report.ri.schema`，不得引用单一建筑实例。

### §2.3.3 EvoPolicy 禁止字段

EvoPolicyVersion 禁止包含：

```text
rule_exclusion_list learned from evaluator
verifier_override
allow_stop_policy
satisfaction_status_override
expected_verdict_weight
truth_label_weight
per_building_reward
per_run_w2_label
```

Policy 可包含 `ranking_weights`、`tool_preferences`、`skill_activation_order`、`open_obligation_priority`，但必须保留 candidate universe floor。

### §2.3.4 Feedback Packet 禁止字段

SanitizedFeedbackPacket 禁止包含：

```text
run_id list
building_id list
world_id list
obligation_id with W2-derived truth
expected_verdict by case
basis item text
projection_id
exact W2 threshold result per case
raw confusion matrix cell with k<10 or buildings<3
free-text evaluator comment
```

## §2.4 边界转换协议

四类边界之间只允许以下转换（v1.1 修订）：

1. agent-visible runtime artifacts → EvoRunTrace：由 trace capture hook 写入，先过 forbidden scan 与 canonical hashing；
2. **evaluator-only → evo-trainer-visible（v1.1 修订）**：trainer 可在自己的工作进程中直接 mount/读取 evaluator private store 的 `EvalTruthReport` raw、W2 projection tables、basis items 用于训练；这条转换不经 broker，但仍受凭证隔离（trainer 不能写 evaluator store）+ trainer 输出的 candidate artifact 必经 Gate 0-4 + leakage audit；
3. evaluator-only `EvalTruthReport` → sanitized-feedback-visible：仅当需要对 runtime agent 暴露历史趋势反馈时走 EvoFeedbackBroker（v1.1 此路径变为**可选**，不再是强制反馈通道）；
4. evo-trainer-visible candidate Skill/Policy → agent-visible active artifact：经 §9.4 Gate 0-4 + §11 leakage audit；v1.1 后无 canary / release window 假设，artifact 通过 audit 即可 promote；
5. agent-visible active artifact → report provenance：只输出 Skill id/version、policy version 与 evidence retrieval role，不输出 feedback reason、不输出 W2 truth 引用。

任何其他转换必须 hard fail。尤其禁止 evaluator private store 直接写 KG、直接追加 prompt、直接修改 active Skill 文本、直接设置 active policy weight（trainer 写 candidate 后必过 Gate）。**runtime agent 进程禁止直接 mount evaluator store**（凭证隔离硬约束，见 §2.5）。

## §2.5 凭证与存储隔离

v1 要求至少三类 service account：

```yaml
credentials:
  agent_runtime:
    read:
      - agent_fact_kg
      - rule_card_kg
      - active_skill_store/runtime_safe
      - active_policy_store/runtime_safe
    write:
      - compliance_run_store
      - evo_trace_store/agent_partition
    deny:
      - evaluator_truth_store
      - raw_feedback_store

  evaluator:
    read:
      - evaluator_truth_store
      - agent_artifacts
      - compliance_run_store
    write:
      - eval_truth_report_store
      - feedback_broker_input
    deny:
      - active_skill_store/write
      - active_policy_store/write

  evo_trainer:
    read:
      - evo_trace_store
      - replay_buffer
      - sanitized_feedback_store
      - candidate_skill_store
      - evaluator_truth_store/raw       # v1.1 修订：trainer 可读 raw W2
      - w2_projection_tables             # v1.1 修订
      - eval_truth_report_store          # v1.1 修订
    write:
      - candidate_skill_store
      - candidate_policy_store
      - validation_record_store
    deny:
      - active_skill_store/write         # active artifact 只能通过 Gate 0-4 promote
      - active_policy_store/write
```

**v1.1 凭证修订背景**（§0.6 修订 1 落地）：evo_trainer 从 v1.0 的"deny evaluator_truth_store/raw"改为"allow"。原因：trainer 工作流读 W2 truth 是 ML 监督学习常识；防 leak 的真正约束在 trainer **输出**（candidate artifact 必过 Gate 0 + leakage audit），而非 trainer 输入。

凭证隔离仍是 hard security requirement，不得用"工程上同进程方便"合并：
- **agent_runtime** 仍 deny `evaluator_truth_store` + `raw_feedback_store`（runtime 推理时不接 truth，避免作弊）；
- **evo_trainer** 可读 truth，但 deny 写 `active_*_store`（candidate 必经 Gate 0-4 + leakage audit 才能 promote）；
- **evaluator** 仍 deny 写 `active_skill_store / active_policy_store`（评测员不能改 runtime）。

即使第一版实现用本地文件夹，也要用目录权限、配置路径与 guard 维护同等隔离。

---

# §3 Knowledge Model v1（Fact KG / RuleCard KG / Rule-Skills KG / EvoMemoryStore）

## §3.1 总览

v1 知识模型由四层组成：

1. **Fact KG**：继承 v0.4 §3.3，表示建筑、构件、位置、状态、measurement、sidecar runtime record 与 sidecar entry；
2. **RuleCard KG**：继承 v0.4 §3.4，表示法规原文、RuleCard、RuleFamily、SourceQuote、ApplicabilityPredicate、TriggerCondition、SlotRef、RuleThreshold、ObligationNode、ObligationEdge、EvidenceRequirement、registries；
3. **Rule-Skills KG**：从 v0.4 §3.5 的预留 schema 升级为 v1 核心，表示 Skill、SkillVersion、SkillTrigger、SkillActivation、SkillValidationRecord、SkillSet、SkillConflictRecord 与它们到 RuleCard/Slot/ObligationKind 的关系；
4. **EvoMemoryStore**：v1 新增，表示 EvoRunTrace、ReplayCase、EvoPolicy、EvoPolicyVersion、SanitizedFeedbackPacket、FeedbackCell、EvoReleaseCard、PolicyTrainingRun 等跨 run 演化对象。

Fact KG 与 RuleCard KG 是审查知识；Rule-Skills KG 是可加载操作策略；EvoMemoryStore 是学习与发布系统。三者可共用 Neo4j，也可分物理库；若共库，必须通过 label namespace 与权限控制隔离 evaluator-only 内容。v1 默认推荐：

```yaml
stores:
  agent_kg:
    contains:
      - Fact KG
      - RuleCard KG
      - active Rule-Skills KG runtime-safe projection
  evo_memory_store:
    contains:
      - EvoRunTrace
      - ReplayCase
      - Candidate SkillPackage metadata
      - SkillValidationRecord
      - EvoPolicyVersion
      - SanitizedFeedbackPacket
  evaluator_truth_store:
    contains:
      - raw W2 truth
      - EvalTruthReport
    accessible_by_agent: false
```

## §3.2 Fact KG 继承口径

Fact KG 继承 v0.4 §3.3 节点与关系，不在 v1 重写字段口径。关键继承点：

- `(:World)`、`(:Building)`、`(:Component)`、`(:Location)`、`(:Fragment)`、`(:CoverageRelation)`；
- `(:DriverState)`、`(:MechanismState)`、`(:MechanismActivation)`、`(:ConditionState)`、`(:ManifestationFlag)`、`(:RepairAssessmentState)`；
- `(:DrainageState)`、`(:UBWState)`、`(:FireSafetyState)`；
- `(:Measurement)`；
- `(:SidecarRuntimeRecord)`、`(:SidecarEntry)`。

v1 对 Fact KG 仅新增两个非语义字段用于 trace：

| 字段 | 类型 | 节点范围 | 说明 |
|---|---|---|---|
| `source_visibility` | string | all imported fact nodes | 固定为 `agent_visible_fact`；用于 forbidden source audit。 |
| `ingest_snapshot_id` | string | all imported fact nodes | 对应 `KGSnapshot.snapshot_id`，用于 replay 可复现。 |

这些字段不改变事实含义。Fact KG 仍禁止 `projection_id` 及其任何 hash/ref 变体，仍禁止 W2 labels/properties。

### §3.2.1 ManifestationFlag 派生协议（v1 新增）

**背景**：W0 数据生成层封口判定 `ConditionState.manifestation_flags` 字段为冗余，worldgen 不再产此字段；但 §3.2 继承 v0.4 的 `(:ManifestationFlag)` 节点定义，闭包验证器 FactPack 构建（§6.4.1）仍按 v0.4 §3.3.2 消费 `(:ManifestationFlag) -> FactAtom(slot_id=<defect/scope slot>)`。两端缺桥，需明确派生归属。

**派生归属**：`(:ManifestationFlag)` 节点由 `fact_loader` 在灌库阶段从 `ConditionState` 派生。`worldgen` 端保持不产 `manifestation_flags` 字段；`condition.payload_json` 不含此字段时，loader 按本协议派生。

**派生输入**：
- `condition.condition_classes: List[str]` — 缺陷类型代码集合（如 `DC_DRAINAGE_MISCONNECTION` / `DC_HOLLOWING` 等）；
- `fragment.in_scope: bool` — 来自 `(:Fragment)` 节点 `in_scope` 属性；
- `component.component_type: str` — 来自 `(:Component)` 节点 `component_type` 属性（通过 `fragment.component_id` 反查）。

**派生规则**（12 条；按 `slot_id` 字母序列出）：

| slot_id | value 派生 | 说明 |
|---|---|---|
| `defect.class.present` | `bool(condition_classes)` | 是否有任何 defect class |
| `defect.detachment_or_loose_fixing.present` | `bool({"DC_DETACHMENT","DC_LOOSE_FIXING"} & set(cc))` | |
| `defect.drainage.blockage.present` | `"DC_DRAINAGE_BLOCKAGE" in cc` if `component_type=="drainage_stack"` else `"not_applicable"` | domain-gated |
| `defect.drainage.leakage.present` | `"DC_DRAINAGE_LEAKAGE" in cc` if `component_type=="drainage_stack"` else `"not_applicable"` | domain-gated |
| `defect.drainage.misconnection.present` | `"DC_DRAINAGE_MISCONNECTION" in cc` if `component_type=="drainage_stack"` else `"not_applicable"` | domain-gated |
| `defect.fire_safety.component_deficiency.present` | `bool({"DC_FIRE_DOOR_DEFICIENCY","DC_FIRE_STOP_DEFICIENCY"} & set(cc))` | v1 简化：直接判 defect class，不再做 fire_component_type gating（W0 删此字段） |
| `defect.hollowing.present` | `"DC_HOLLOWING" in cc` | |
| `defect.moisture_or_leakage.present` | `bool({"DC_MOISTURE_STAINING","DC_LEAKAGE"} & set(cc))` | |
| `defect.subdivided_unit_sign.present` | `"DC_SUBDIVIDED_SIGN" in cc` if `component_type=="unauthorized_structure"` else `"not_applicable"` | domain-gated |
| `defect.ubw.present` | `"DC_UBW_PRESENT" in cc` | |
| `scope.component.excluded_from_scope` | `not fragment.in_scope` | |
| `scope.component.in_scope` | `fragment.in_scope` | |

（`cc` 是 `condition.condition_classes` 简写。）

**节点字段**（沿用 v0.4 §3.3.2）：
- `manifestation_flag_id = condition_id + "::" + slot_id + "::" + hash(qualifiers)`；
- `condition_id`、`world_id`、`slot_id`、`value_json = canonical_json(value)`、`qualifier_ids = canonical_json({"qual.component_type": component_type})`、`notes = ["derived_by_fact_loader_v1"]`。

**边**（沿用 v0.4 §3.3.2）：
- `(:ConditionState)-[:HAS_MANIFESTATION_FLAG]->(:ManifestationFlag)`；
- `(:ManifestationFlag)-[:REALIZES_SLOT]->(:SemanticSlot)` — 仅当 `slot_id` 存在于 rule_card SemanticSlot registry 时建立。

**已知不派生（v0.4 18 个 flag 中的 6 个）**：
- `scope.component.covered` / `covered_by_large_signboard` — 需要 `(:CoverageRelation)` 关联查询，v1 暂留；
- `scope.component.obscured_by_finish` / `obscured_by_services` — 依赖 W0 已删字段 `driver.coverage_feasibility_index` / `driver.obstruction_index`；
- `defect.range.extends_into_private_premises` — 依赖 W0 已删字段 `fragment.nominal_visible_area_m2`；
- `defect.cause_or_extent.uncertain` — 依赖 W0 已删字段，且语义可由 `condition.uncertainty_flag` 替代承担。

后续如 rule_card SemanticSlot registry 引用这 6 个 slot 中的任何一个，需补 W0 字段或定义替代派生路径，本协议同步扩展。

## §3.3 RuleCard KG 继承口径

RuleCard KG 继承 v0.4 §3.4 节点与关系，不修改 rule_card v2 schema。v1 只新增 Skill/Policy 可引用的稳定索引字段：

| 字段 | 类型 | 节点范围 | 说明 |
|---|---|---|---|
| `stable_ref` | string | RuleCard、RuleFamily、SemanticSlot、Measure、Artifact | 格式 `<label>:<id>@<bundle_id>`，用于 Skill scope 引用。 |
| `bundle_id` | string | all rule nodes | rulecard bundle id。 |
| `visibility` | string | all rule nodes | 固定 `agent_visible_rule`。 |

RuleThreshold 仍表示法规卡阈值，不是 W2 `ThresholdEval`。RuleCard KG 可以完整保留阈值 operator/value/formula；防泄漏不靠删阈值，而靠禁止 W2 expected result 进入 agent。

## §3.4 Rule-Skills KG 核心 schema

### §3.4.1 设计原则

Rule-Skills KG 是 v1 的运行期策略知识图。它不是事实 KG，也不是 evaluator truth store。Skill 节点描述“在什么结构化条件下，采取什么检索/路由/报告组织策略”；它不得描述“某建筑应判什么结果”。

Rule-Skills KG 中只有 `status in {"core","active"}` 且通过 staleness guard 的 SkillVersion 可投影到 agent runtime-safe view。`draft/candidate/staged/quarantined/retired` 版本默认只对 evo trainer 可见。

### §3.4.2 `(:Skill)`

`Skill` 是逻辑 Skill identity，不随版本变化。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `skill_id` | string | 是 | 稳定 id，格式 `skill.mbis.<kind>.<scope>.<goal>`，不含版本后缀。 |
| `name` | string | 是 | 可读名称，lowercase words 或中文短名均可，但不得含 building/run/world literal。 |
| `kind` | enum | 是 | `core_workflow`、`micro_routing`、`retrieval_macro`、`report_structure`、`diagnostic_hint`、`meta_disabled`。 |
| `layer` | enum | 是 | `L0_core`、`L1_operational`、`L2_meta_disabled`。 |
| `description` | string | 是 | 触发范围与安全边界，不超过 1024 字符。 |
| `origin` | enum | 是 | `manual_seed`、`evo_induced`、`spec_revision`。 |
| `owner` | string | 是 | `spec`、`evo_trainer`、`human_reviewer`。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `latest_version_id` | string | 是 | 指向最新版本，不等于 active 版本时允许。 |
| `active_version_id` | string/null | 否 | 当前 runtime active 版本；core Skill 可固定。 |
| `lifecycle_policy` | json | 是 | promotion、retirement、staleness 规则摘要。 |

约束：

```cypher
CREATE CONSTRAINT skill_id_unique IF NOT EXISTS
FOR (s:Skill) REQUIRE s.skill_id IS UNIQUE;

CREATE INDEX skill_kind_layer IF NOT EXISTS
FOR (s:Skill) ON (s.kind, s.layer);
```

### §3.4.3 `(:SkillVersion)`

`SkillVersion` 是可验证、可加载的具体版本。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `skill_version_id` | string | 是 | `<skill_id>.v<major>.<minor>.<patch>` 或 `<skill_id>.v<major>`。 |
| `skill_id` | string | 是 | 父 Skill id。 |
| `version` | semver | 是 | 不允许原地覆盖。 |
| `status` | enum | 是 | **v1.1 简化为 4 态**：`core`、`draft`、`active`、`retired`（v1.0 旧 `candidate` / `staged` / `quarantined` 已删；按 §0.6.1 全局映射规则解读旧引用）。 |
| `package_uri` | string | 是 | SkillPackage 目录或 content-addressed URI。 |
| `package_sha256` | string | 是 | 目录 canonical hash。 |
| `skill_json_sha256` | string | 是 | `skill.json` canonical hash。 |
| `skill_md_sha256` | string | 是 | `SKILL.md` hash。 |
| `plan_yaml_sha256` | string/null | 否 | routing/retrieval 类必填。 |
| `rulecard_bundle_id` | string | 是 | 验证时绑定 bundle。 |
| `kg_snapshot_id` | string | 是 | 验证时绑定 KG snapshot。 |
| `scope_rule_families` | list[string] | 否 | Skill 适用 family。 |
| `scope_rule_cards` | list[string] | 否 | Skill 适用 card。 |
| `scope_semantic_slots` | list[string] | 否 | Skill 目标 slot。 |
| `scope_obligation_kinds` | list[string] | 否 | 目标 obligation kind。 |
| `trigger_predicate_json` | json | 是 | 只允许引用 agent-visible concepts。 |
| `allowed_tools` | list[string] | 是 | tool allowlist。 |
| `forbidden_actions` | list[string] | 是 | 至少含 `override_verifier`、`force_allow_stop`。 |
| `source_trace_hashes` | list[string] | 是 | candidate 及以上状态至少 5 个。 |
| `support_building_count` | int | 是 | candidate→staged 要求 ≥3，或 `support_world_family_count` ≥2。 |
| `support_world_family_count` | int | 是 | 见上。 |
| `validation_score` | float | 否 | 0-1，release gate 计算。 |
| `leakage_audit_passed` | bool | 是 | active 必须 true。 |
| `closure_non_regression_passed` | bool | 是 | active 必须 true。 |
| `staleness_status` | enum | 是 | `fresh`、`stale_rule_bundle`、`stale_kg_snapshot`、`needs_revalidation`。 |
| `created_at` | datetime | 是 | 版本创建时间。 |
| `activated_at` | datetime/null | 否 | active 时间。 |
| `retired_at` | datetime/null | 否 | retired 时间。 |
| `quarantine_reason` | string/null | 否 | **v1.1 deprecated**：v1.0 `quarantined` 状态已删；新建 artifact 不填，旧 artifact 兼容保留。 |
| `supersedes_version_id` | string/null | 否 | 取代版本。 |
| `parent_version_id` | string/null | 否 | 派生来源。 |

约束（v1.1 修订）：

- `status=active` 时，`leakage_audit_passed=true`、`closure_non_regression_passed=true`、`staleness_status=fresh`；
- `kind in {"micro_routing","retrieval_macro"}` 时必须有 `plan_yaml_sha256`；
- `source_trace_hashes` 不得为空；`draft` 可少于 5，`active` 必须 ≥5（v1.0 旧 `candidate/staged/active` 三个状态在 v1.1 合并为 `active`）；
- `support_building_count>=3 OR support_world_family_count>=2` 是 `active` 必要条件（v1.0 旧 `staged/active` 条件合并）；
- `package_uri` 中不得指向 evaluator truth store。

### §3.4.4 `(:SkillTrigger)`

SkillTrigger 表示 runtime 如何匹配 Skill。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `trigger_id` | string | 是 | `<skill_version_id>.trigger.<n>` |
| `skill_version_id` | string | 是 | 所属版本 |
| `trigger_kind` | enum | 是 | `rule_family`、`semantic_slot`、`obligation_kind`、`open_reason`、`blocked_reason`、`artifact_key`、`compound` |
| `pattern_json` | json | 是 | DSL，禁止 building/run/world literal |
| `priority` | int | 是 | 0-1000；越高越先触发 |
| `enabled` | bool | 是 | runtime load 前还需 staleness guard |
| `cooldown_policy_json` | json | 否 | 避免同 run 反复触发 |
| `max_activations_per_run` | int | 是 | 默认 3 |

示例：

```json
{
  "trigger_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1.trigger.1",
  "trigger_kind": "compound",
  "pattern_json": {
    "all": [
      {"field": "open_reason_code", "op": "in", "value": ["missing_artifact_evidence", "missing_sidecar_entry"]},
      {"field": "scope_obligation_kind", "op": "in", "value": ["artifact", "report_field", "evidence"]},
      {"field": "rule_family", "op": "prefix", "value": "mbis.reporting."}
    ]
  },
  "priority": 720,
  "enabled": true,
  "max_activations_per_run": 2
}
```

### §3.4.5 `(:SkillActivation)`

SkillActivation 是 runtime provenance，不是验证记录。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `activation_id` | string | 是 | `SA-<run_id>-<seq>` |
| `run_id` | string | 是 | 所属 run |
| `trace_id` | string | 是 | 所属 EvoRunTrace |
| `skill_version_id` | string | 是 | 激活版本 |
| `trigger_id` | string | 是 | 命中的 trigger |
| `trigger_context_hash` | string | 是 | 触发上下文 canonical hash |
| `activation_stage` | enum | 是 | `pre_retrieval`、`post_closure_deepening`、`pre_report` |
| `plan_step_ids` | list[string] | 否 | 执行的 plan steps |
| `tool_calls_added` | int | 是 | 增加 tool calls 数 |
| `candidate_refs_added` | int | 是 | 增加候选数 |
| `fallback_used` | bool | 是 | 是否回退 baseline |
| `guard_passed` | bool | 是 | pre_skill_runtime_load_guard 与 runtime guard pass |
| `created_at` | datetime | 是 | 激活时间 |

SkillActivation 可被 report provenance 引用，但 report 只显示 `skill_version_id`、`kind`、`retrieval_role`，不显示 source feedback。

### §3.4.6 `(:SkillValidationRecord)`

SkillValidationRecord 是 candidate/staged/active 的验证证据。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `validation_id` | string | 是 | `SVR-<skill_version_id>-<timestamp>-<hash>` |
| `skill_version_id` | string | 是 | 被验证版本 |
| `validation_stage` | enum | 是 | `gate0_static`、`gate1_schema_provenance`、`gate2_replay_ab`、`gate3_stability`、`gate4_holdout_counterfactual`、`release_gate` |
| `eval_set_id` | string | 是 | replay/holdout set id |
| `eval_set_hash` | string | 是 | set canonical hash |
| `run_count` | int | 是 | 样本数 |
| `building_count` | int | 是 | building 覆盖数 |
| `world_family_count` | int | 是 | world family 覆盖数 |
| `metric_name` | string | 是 | 枚举化 metric 名 |
| `metric_value_bucket` | string | 是 | 0.05 粒度或 bucket |
| `metric_delta_bucket` | string | 否 | 相对 baseline/current policy |
| `passed` | bool | 是 | 本 gate 是否通过 |
| `failure_reasons` | list[string] | 否 | 枚举，不含 raw evaluator note |
| `leakage_hits` | list[string] | 是 | 必须为空才能 active |
| `closure_regression_count` | int | 是 | active 必须 0 |
| `allow_stop_authority_check` | bool | 是 | 确认 allow_stop 仍来自 verifier |
| `created_at` | datetime | 是 | 验证时间 |
| `validator_version` | string | 是 | gate 实现版本 |

禁止自由文本 raw notes；若需要备注，只能用 `failure_reasons` 枚举。

### §3.4.7 `(:SkillSet)`

SkillSet 表示某个 runtime policy 加载的一组 SkillVersion。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `skill_set_id` | string | 是 | `SS-<policy_version_id>-<hash>` |
| `policy_version_id` | string | 是 | 关联 policy |
| `skill_version_ids` | list[string] | 是 | active/core skill versions |
| `core_skill_count` | int | 是 | Layer 0 数量 |
| `operational_skill_count` | int | 是 | active Layer 1 数量 |
| `created_at` | datetime | 是 | 构建时间 |
| `skill_set_hash` | string | 是 | canonical list hash |
| `load_guard_passed` | bool | 是 | pre_skill_runtime_load_guard 结果 |

### §3.4.8 `(:SkillConflictRecord)`

SkillConflictRecord 记录 active/staged Skill 的 scope 冲突。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `conflict_id` | string | 是 | `SCR-<hash>` |
| `skill_version_ids` | list[string] | 是 | 冲突版本 |
| `conflict_scope_json` | json | 是 | 重叠 trigger/scope |
| `resolver_action` | enum | 是 | `choose_higher_score`、`union_retrieval`、`fallback_core`、`quarantine_lower_score` |
| `score_gap` | float | 是 | top2 validation_score gap |
| `resolved_at` | datetime | 是 | 解析时间 |
| `runtime_safe` | bool | 是 | true 才可加载 |

规则：同 scope top2 `validation_score` 差距 ≥0.05 时选高分；差距 <0.05 时采用 union-of-retrieval 增广；若 union 超预算，fallback CoreSkill baseline；任何冲突都不得由 LLM 临场决定哪个结论正确。

## §3.5 Rule-Skills KG 关系

| 关系 | from → to | 属性 | 说明 |
|---|---|---|---|
| `(:Skill)-[:HAS_VERSION]->(:SkillVersion)` | Skill→SkillVersion | `created_at` | 版本关系 |
| `(:SkillVersion)-[:HAS_TRIGGER]->(:SkillTrigger)` | SkillVersion→SkillTrigger | 无 | 触发器 |
| `(:SkillVersion)-[:APPLIES_TO]->(:RuleFamily)` | SkillVersion→RuleFamily | `scope_weight` | 适用规则族 |
| `(:SkillVersion)-[:APPLIES_TO_CARD]->(:RuleCard)` | SkillVersion→RuleCard | `scope_weight` | 适用卡 |
| `(:SkillVersion)-[:TARGETS_SLOT]->(:SemanticSlot)` | SkillVersion→SemanticSlot | `target_role` | 目标 slot |
| `(:SkillVersion)-[:TARGETS_MEASURE]->(:Measure)` | SkillVersion→Measure | `target_role` | 目标 measure |
| `(:SkillVersion)-[:TARGETS_ARTIFACT]->(:Artifact)` | SkillVersion→Artifact | `target_role` | 目标 artifact |
| `(:SkillVersion)-[:VALIDATED_BY]->(:SkillValidationRecord)` | SkillVersion→SkillValidationRecord | `stage` | 验证记录 |
| `(:SkillVersion)-[:SUPERSEDES]->(:SkillVersion)` | 新→旧 | `reason` | 替代 |
| `(:SkillActivation)-[:INVOKED_SKILL]->(:SkillVersion)` | Activation→SkillVersion | 无 | runtime provenance |
| `(:SkillSet)-[:LOADS]->(:SkillVersion)` | SkillSet→SkillVersion | `load_order` | 加载集合 |
| `(:EvoPolicyVersion)-[:LOADS_SKILL_SET]->(:SkillSet)` | Policy→SkillSet | 无 | policy→skillset |

禁止关系：

- SkillVersion 不得连接到 evaluator-only 节点；
- SkillValidationRecord 不得连接到 raw EvalTruthReport；
- SkillTrigger 不得连接到 Building/World/Run 实例；
- SkillVersion 不得通过 relationship 表达“某结果应 satisfied/violated”。

## §3.6 EvoMemoryStore schema

### §3.6.1 `(:EvoRunTrace)`

EvoRunTrace 是跨 run 学习的主事实层。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `trace_id` | string | 是 | `ERT-<run_id>-<hash>` |
| `run_id` | string | 是 | ComplianceAssessmentRun id |
| `world_id_hash` | string | 是 | world_id canonical hash；trace 内可保留原 world_id 仅在 agent partition，trainer 默认用 hash |
| `building_id_hash` | string | 是 | building_id canonical hash |
| `kg_snapshot_id` | string | 是 | agent KG snapshot |
| `rulecard_bundle_id` | string | 是 | rulecard bundle |
| `agent_version` | string | 是 | runtime agent version |
| `verifier_version` | string | 是 | verifier version |
| `evo_policy_version_id` | string | 是 | active policy |
| `active_skill_set_id` | string | 是 | active SkillSet |
| `input_guard_hash` | string | 是 | input guard result canonical hash |
| `retrieval_summary_json` | json | 是 | candidate counts、fact counts、family counts |
| `candidate_universe_hash` | string | 是 | verifier candidate universe hash |
| `rule_slice_hash` | string | 是 | RuleSlice canonical hash |
| `fact_pack_hash` | string | 是 | FactPack canonical hash |
| `closure_result_ref` | string | 是 | closure artifact ref |
| `closure_summary_json` | json | 是 | open/blocked/closed counts 与 reason counts |
| `report_ref` | string/null | 否 | report/incomplete notice ref |
| `hook_results_hash` | string | 是 | hook results hash |
| `tool_call_count` | int | 是 | tool calls |
| `llm_iterations_used` | int | 是 | default max 16 |
| `cost_json` | json | 是 | token/time/tool cost |
| `fallback_reason` | string/null | 否 | fallback |
| `trace_visibility` | enum | 是 | `agent_visible_trace` |
| `forbidden_scan_passed` | bool | 是 | 必须 true 才入 Replay Buffer |
| `created_at` | datetime | 是 | 创建时间 |

EvoRunTrace 不直接存 raw prompt 大段文本；它存 canonical hash、摘要和 artifact ref。artifact ref 只能指向 agent-visible artifacts。

### §3.6.2 `(:EvoRunStep)`

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `step_id` | string | 是 | `ERS-<trace_id>-<seq>` |
| `trace_id` | string | 是 | 父 trace |
| `seq` | int | 是 | 顺序 |
| `stage` | enum | 是 | `input_guard`、`fact_retrieval`、`rule_retrieval`、`skill_activation`、`closure_verification`、`deep_lookup`、`report_generation`、`guard` |
| `tool_name` | string/null | 否 | tool call |
| `tool_input_hash` | string/null | 否 | canonical hash |
| `tool_output_summary_hash` | string/null | 否 | summary hash |
| `selected_skill_ids` | list[string] | 否 | 本步激活 Skill |
| `policy_decision_ref` | string/null | 否 | policy decision object |
| `candidate_set_hash` | string/null | 否 | 本步候选 |
| `guard_results_json` | json | 否 | guard summary |
| `created_at` | datetime | 是 | 时间 |

### §3.6.3 `(:ReplayCase)`

ReplayCase 是可用于 gate 和 training 的 trace 引用。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `replay_case_id` | string | 是 | `RC-<trace_id>-<purpose>` |
| `trace_id` | string | 是 | 来源 trace |
| `purpose` | enum | 是 | `skill_induction`、`skill_validation`、`policy_training`、`holdout`（**v1.1 删除 `canary`**——见 §0.6 修订 2）|
| `eligibility` | enum | 是 | `eligible`、`invalid_leakage`、`invalid_schema`、`invalid_forbidden_source`、`invalid_stale` |
| `novelty_score` | float | 是 | 0-1 |
| `coverage_weight` | float | 是 | 0-3 |
| `feedback_available` | bool | 是 | 是否有 sanitized feedback |
| `effective_trace_weight` | float | 是 | §11 公式使用 |
| `split` | enum | 是 | `evolve_train`、`gate_validation`、`held_out_test` |
| `created_at` | datetime | 是 | 创建时间 |

### §3.6.4 `(:EvoPolicy)` 与 `(:EvoPolicyVersion)`

`EvoPolicy` 是逻辑 policy family，`EvoPolicyVersion` 是可加载版本。

`EvoPolicy` 字段：

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `policy_id` | string | 是 | `policy.mbis.runtime.default` |
| `name` | string | 是 | 可读名 |
| `latest_version_id` | string | 是 | 最新版本 |
| `active_version_id` | string | 是 | 当前 active |
| `created_at` | datetime | 是 | 创建时间 |

`EvoPolicyVersion` 字段：

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `policy_version_id` | string | 是 | `policy.mbis.runtime.default.v1.0.0` |
| `policy_id` | string | 是 | 父 policy |
| `version` | semver | 是 | 版本 |
| `status` | enum | 是 | **v1.1 简化为 3 态**：`draft`、`active`、`retired`（去掉 candidate/staged/rolled_back，由 git 版本管理代替）|
| `ranking_weights_json` | json | 是 | policy-aware ranking 权重 |
| `tool_preferences_json` | json | 是 | tool 调度偏好 |
| `skill_activation_order_json` | json | 是 | Skill 触发排序 |
| `open_obligation_priority_json` | json | 是 | open/blocked 深查优先级 |
| `candidate_cutoff_policy_json` | json | 是 | 只可影响 context order，不可破坏 candidate floor |
| `report_template_policy_json` | json | 是 | report_structure 选择 |
| `fallback_thresholds_json` | json | 是 | fallback 条件 |
| `max_tool_iterations_default` | int | 是 | v1 实验室 default = 16 |
| `experiment_budgets` | list[int] | 是 | `[8,16,32]` 用于实验曲线 |
| `trained_on_replay_set_id` | string | 是 | training set |
| `trained_on_artifacts` | list[string] | 否 | **v1.1 新字段**：trainer 输入的任意 artifact ref（含 raw `EvalTruthReport` ref、replay set、trace set 等）；替代旧 `trained_on_feedback_packet_ids` |
| `trained_on_feedback_packet_ids` | list[string] | 否 | **v1.1 保留但不再硬约束**；trainer 不强制走 broker，packet 只在用 runtime trend feedback 时填 |
| `validation_summary_json` | json | 是 | Gate 0-4 + leakage audit summary |
| `created_at` | datetime | 是 | 创建 |
| `activated_at` | datetime/null | 否 | active 时间 |

**v1.1 删除字段**：原 `previous_active_version_id`（rollback ref）由 git history 代替，不再 schema 层维护。

### §3.6.5 `(:SanitizedFeedbackPacket)` 与 `(:FeedbackCell)`

`SanitizedFeedbackPacket` 是 broker 输出主对象。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `feedback_packet_id` | string | 是 | `SFP-<window>-<hash>` |
| `eval_window_id` | string | 是 | 评测窗口 |
| `source_eval_truth_report_hash` | string | 是 | raw report hash；不暴露 raw path |
| `aggregation_level` | enum | 是 | `batch_rule_family`、`batch_slot_class`、`batch_obligation_kind`、`batch_error_taxonomy` |
| `run_count` | int | 是 | ≥10 |
| `building_count` | int | 是 | ≥3 |
| `cell_count` | int | 是 | 输出 cell 数 |
| `rounding_policy` | string | 是 | `nearest_0.05` 或 bucket |
| `release_delay_window_count` | int | 否 | **v1.1 改为可选**（v1.0 强制 ≥1 是生产 traffic 假设，实验室阶段无意义；§8.6 整段删）|
| `forbidden_scan_passed` | bool | 是 | 必须 true |
| `k_anonymity_passed` | bool | 是 | 必须 true |
| `reconstruction_audit_passed` | bool | 是 | **v1.1 语义重定位**：原本审 packet 是否泄漏 W2，现改为审 trainer 输出 artifact 是否泄漏 W2（见 §11.9 v1.1 修订）；packet 本身的 reconstruction audit 字段保留供历史兼容 |
| `created_at` | datetime | 是 | 生成时间 |
| `released_at` | datetime | 是 | 发布时间 |

`FeedbackCell` 字段：

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `feedback_cell_id` | string | 是 | `SFP-...-cell-<n>` |
| `feedback_packet_id` | string | 是 | 父 packet |
| `dimension_json` | json | 是 | family/slot/obligation/error taxonomy，不含 case id |
| `metric_name` | string | 是 | 枚举 metric |
| `metric_bucket` | string | 是 | rounded/bucketed |
| `delta_bucket` | string/null | 否 | 相对 baseline/current |
| `run_count` | int | 是 | ≥10 |
| `building_count` | int | 是 | ≥3 |
| `suppressed` | bool | 是 | 不满足 k 时 true 且不输出 metric |
| `suggested_evo_action` | enum | 否 | `skill_induction_candidate`、`policy_weight_adjustment`、`report_guard_attention`、`none` |

### §3.6.6 `(:EvoReleaseCard)`

每次 policy/skill release 必须生成 release card（v1.1 简化）。

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `release_card_id` | string | 是 | `ERC-<artifact>-<version>` |
| `artifact_type` | enum | 是 | `skill`、`policy`、`skill_set` |
| `artifact_version_id` | string | 是 | 被发布 artifact |
| `effective_trace_count` | float | 是 | §11 `E_runtime` 分解值 |
| `active_skill_count` | int | 是 | 当前 active skills |
| `heldout_metric_summary_json` | json | 是 | held-out aggregate |
| `ablation_delta_json` | json | 是 | ablation 结果 |
| `leakage_audit_passed` | bool | 是 | 必须 true |
| `reconstruction_audit_passed` | bool | 是 | **v1.1 重定位**：审 artifact 是否泄漏 raw W2（见 §11.9 v1.1 修订），必须 true |
| `closure_non_regression_passed` | bool | 是 | 必须 true |
| `created_at` | datetime | 是 | 创建时间 |

**v1.1 删除字段**：原 `rollback_condition_json`（rollback 触发条件）已删——v1.1 实验室阶段用 git revert 回滚，不需要 schema 层维护回滚条件。原 canary 相关字段（v1.0 §9.8 引入）已未在本表出现，v1.1 不再补。

正式 production 部署阶段的 release card 字段（canary_plan / rollback_condition / monitoring_window 等）由 v1.5 production deployment 章节单独立条。

## §3.7 索引与约束

v1 必须增加以下索引：

```cypher
CREATE CONSTRAINT skill_version_id_unique IF NOT EXISTS
FOR (sv:SkillVersion) REQUIRE sv.skill_version_id IS UNIQUE;

CREATE CONSTRAINT trace_id_unique IF NOT EXISTS
FOR (t:EvoRunTrace) REQUIRE t.trace_id IS UNIQUE;

CREATE CONSTRAINT policy_version_id_unique IF NOT EXISTS
FOR (p:EvoPolicyVersion) REQUIRE p.policy_version_id IS UNIQUE;

CREATE CONSTRAINT feedback_packet_id_unique IF NOT EXISTS
FOR (s:SanitizedFeedbackPacket) REQUIRE s.feedback_packet_id IS UNIQUE;

CREATE INDEX skill_scope_family IF NOT EXISTS
FOR (sv:SkillVersion) ON (sv.status, sv.kind, sv.rulecard_bundle_id);

CREATE INDEX replay_split_eligibility IF NOT EXISTS
FOR (rc:ReplayCase) ON (rc.split, rc.eligibility, rc.purpose);

CREATE INDEX feedback_packet_window IF NOT EXISTS
FOR (s:SanitizedFeedbackPacket) ON (s.eval_window_id, s.aggregation_level);
```

若使用文件/DuckDB 而非 Neo4j，必须提供等价 uniqueness check 和 lookup index。

## §3.8 Canonical JSON 与 Hash 规则

所有 hash 字段使用 canonical JSON：

- UTF-8；
- object key 按 Unicode codepoint 升序；
- list 保持语义顺序；若 list 是 set 语义，写入前排序；
- datetime 使用 UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`；
- float 保留 6 位小数；
- 不写 null 字段，除非 schema 要求显式 null；
- hash 使用 SHA-256，hex lowercase。

示例：

```json
{
  "candidate_universe_hash": "sha256:3a4f...",
  "canonicalization": {
    "sort_keys": true,
    "drop_null_unless_required": true,
    "datetime": "utc_iso8601",
    "float_precision": 6
  }
}
```



---

# §4 Ingestion + SkillPackage loader + EvoPolicy loader + staleness guard

## §4.1 继承 v0.4 loader 思路

v1 继承 v0.4 §4 的灌库设计：agent fact loader 只读 allowlist，跳过并审计 denylist；rule_card loader 读取 manifest、rule_cards、family_index 与 registries；regulation loader 解析 markdown clause；evaluator truth loader 独立读取 W2。v1 新增三类 loader：

1. `SkillPackageLoader`：读取、解析、验证、投影 `EvoSkillPackage`；
2. `EvoPolicyLoader`：读取 active `EvoPolicyVersion` 与关联 SkillSet；
3. `StalenessGuard`：在 runtime load 前检查 rulecard bundle、KG snapshot、verifier version、SkillPackage hash 与 validation record 是否仍新鲜。

loader 的顺序固定：

```text
1. Fact KG loader
2. RuleCard KG loader
3. CoreSkill loader
4. Candidate/active SkillPackage loader
5. EvoPolicy loader
6. StalenessGuard
7. Runtime-safe projection build
```

任何步骤发现 evaluator-only path 或 forbidden field，整个 load hard fail，不能降级为 warning。

## §4.2 SkillPackageLoader

### §4.2.1 输入

`SkillPackageLoader` 接收目录或 content-addressed package：

```text
skills/
  skill.mbis.retrieval_macro.artifact_evidence_gap.v1/
    skill.json
    SKILL.md
    plan.yaml
    validation_records.jsonl
    README.optional.md
```

必需文件：

| 文件 | 必需条件 | 说明 |
|---|---|---|
| `skill.json` | 必需 | 机器权威源 |
| `SKILL.md` | 必需 | LLM-readable view，由 `skill.json` 与人工/LLM 文本生成 |
| `validation_records.jsonl` | 必需 | 至少记录 Gate 0/1；candidate 及以上必须有完整 gate 记录 |
| `plan.yaml` | `micro_routing`、`retrieval_macro` 必需 | 可回放 action plan |

loader 不允许读取同目录外相对路径，如 `../evaluator_truth`。package 内所有文件 canonical hash 进入 `SkillVersion`。

### §4.2.2 loader steps

```text
1. resolve package URI
2. read skill.json only
3. validate schema and status
4. read declared files and compute hashes
5. run Gate 0 static safety scan
6. run Gate 1 schema/provenance scan
7. load validation_records.jsonl
8. if status in staged/active/core, verify Gate 2-4 records exist and pass
9. build Skill / SkillVersion / SkillTrigger graph nodes
10. build runtime-safe projection
```

loader 不在 load 阶段运行 replay；replay 是 §9 的 validation pipeline。但 loader 必须拒绝缺少 replay pass record 的 staged/active Skill。

### §4.2.3 Gate 实现挂点

5 Gate 的完整规则在 §9.4 定义；loader 负责 Gate 0/1 的本地复验，并核验 Gate 2-4 record。

| Gate | loader 行为 | 失败处理 |
|---|---|---|
| Gate 0 Static Safety | 重新扫描 package 全文件 | hard fail，status 改 `quarantined` |
| Gate 1 Schema/Provenance | 解析 skill.json/plan.yaml、检查 source_trace_hashes、scope refs | hard fail |
| Gate 2 Replay A/B | 核验 validation record 与 eval_set_hash | 缺失或 failed 则不能 staged/active |
| Gate 3 Stability | 核验 K=5 稳定记录 | 缺失或 failed 则不能 active |
| Gate 4 Holdout/Counterfactual | 核验 holdout 与 counterfactual record | 缺失或 failed 则不能 active |

### §4.2.4 runtime-safe projection

runtime-safe projection 是 agent runtime 可读取的 Skill 子集：

```json
{
  "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
  "kind": "retrieval_macro",
  "description": "When reporting/artifact obligations remain open due to missing artifact evidence, expand artifact-sidecar lookup before report generation.",
  "trigger_predicate": {"...": "..."},
  "allowed_tools": ["query_open_obligations", "inspect_obligation", "retrieve_building_facts"],
  "plan_ref": "plan.yaml#runtime_safe",
  "non_authority_statement": "This skill only changes retrieval order and does not affect allow_stop."
}
```

projection 不含 source feedback packet id、metric delta、W2-derived validation notes、building ids 或 run ids。

## §4.3 EvoPolicyLoader

`EvoPolicyLoader` 读取一个 active `EvoPolicyVersion`，并构造 runtime policy context。必需字段：

```yaml
policy_version_id: policy.mbis.runtime.default.v1.0.0
status: active
max_tool_iterations_default: 16
experiment_budgets: [8, 16, 32]
ranking_weights:
  base_fulltext_score: 1.00
  graph_neighbor_boost: 0.35
  skill_trigger_boost: 0.30
  open_reason_priority_boost: 0.25
  stale_penalty: -1.00
candidate_cutoff_policy:
  context_top_k: 80
  verifier_floor: all_score_positive_not_deterministically_excluded
```

loader 必须检查：

- `status=active`；
- `validation_summary.closure_non_regression_passed=true`；
- `validation_summary.leakage_audit_passed=true`；
- `candidate_cutoff_policy.verifier_floor` 未被关闭；
- 关联 SkillSet 的 `load_guard_passed=true`；
- `previous_active_version_id` 存在，除非这是 bootstrap policy；
- policy 不含 forbidden fields。

若 policy load fail，runtime 回退到 last known good policy；若没有 last known good，回退 CoreSkill baseline policy。

## §4.4 StalenessGuard

staleness guard 在每次 runtime 启动和每次 release 前运行。它检查：

| 检查项 | fresh 条件 | stale 处理 |
|---|---|---|
| `rulecard_bundle_id` | 与当前 RuleCard KG bundle 一致 | Skill disabled，排队 revalidation |
| `kg_snapshot_id` | 与当前 replay/validation 允许 snapshot 范围一致 | staged/active 降为 needs_revalidation |
| `verifier_version` | 与 validation record 中 verifier major version 一致 | 重新跑 Gate 2-4 |
| `package_sha256` | 与 SkillVersion 记录一致 | hash mismatch hard quarantine |
| `plan_yaml_sha256` | 与记录一致 | hard quarantine |
| `validation_record_hash` | 与 release card 一致 | hard quarantine |
| `policy_validation_summary` | 与 active policy artifact hash 一致 | rollback |

staleness guard 的默认规则：

```python
fresh = (
    skill.rulecard_bundle_id == current.rulecard_bundle_id
    and skill.staleness_status == "fresh"
    and skill.package_sha256 == compute_package_hash(skill.package_uri)
    and skill.validation_summary.closure_non_regression_passed
    and skill.validation_summary.leakage_audit_passed
)
```

stale 不等于删除。stale Skill 保留审计记录，但 runtime 不加载。

## §4.5 Ingestion audit artifacts

每次 load 生成：

```json
{
  "loader_run_id": "LOAD-20260523T203000Z-abc123",
  "kg_snapshot_id": "KGS-v1-20260523",
  "rulecard_bundle_id": "rulecard_v2.mbis_cop_2023",
  "skill_packages_seen": 18,
  "skill_packages_loaded_runtime": 7,
  "skill_packages_quarantined": 1,
  "active_policy_version_id": "policy.mbis.runtime.default.v1.0.0",
  "forbidden_hits": [],
  "staleness_disabled": ["skill.mbis.micro_routing.old_bundle.v1"],
  "passed": true
}
```

audit artifact 写入 evo memory store，不写入 evaluator truth store。

---

# §5 Runtime Retrieval + ComplianceAssessmentRun v1

## §5.1 ComplianceAssessmentRun v1 schema 扩展

v1 继承 v0.4 §5.1 `ComplianceAssessmentRun`，新增 evo 字段：

```python
class ComplianceAssessmentRunV1(ComplianceAssessmentRun):
    run_type: Literal["evo_building_review"]
    evo_policy_version_id: str
    active_skill_set_id: str
    active_skill_version_ids: List[str]
    trace_ref: Optional[str]
    skill_invocation_summary: Dict[str, Any]
    tool_budget_policy: Dict[str, Any]
    fallback_reason: Optional[str]
    llm_iteration_ceiling: int = 16
    runtime_mode: Literal["production", "replay", "canary", "ablation"]
    feedback_batch_ref: Optional[str]
    candidate_universe_hash: Optional[str]
    fact_pack_hash: Optional[str]
    rule_slice_hash: Optional[str]
```

`ComplianceAssessmentRun` 是业务 run 主表；`EvoRunTrace` 是演化记忆层。run 可被删除或归档，但 trace 的 canonical hash 与 release card 记录必须保留。

## §5.2 v1 运行流程

```text
1. pre_run_input_guard
2. load active EvoPolicyVersion
3. load active SkillSet with pre_skill_runtime_load_guard
4. retrieve building shell and fact subgraph
5. retrieve initial rule candidates
6. apply skill-aware retrieval augmentation
7. apply policy-aware ranking for context order
8. enforce verifier candidate universe floor
9. build FactPack + RuleSlice
10. run deterministic closure verifier
11. if open/blocked remain, apply allowed deep lookup priority
12. rerun closure if new facts/rules added
13. post_verifier_stop_gate
14. generate auxiliary report or incomplete closure notice
15. pre_output_language_guard
16. capture EvoRunTrace
```

LLM 可以在 step 6/11 中选择 tool 调用，但必须在 active policy 和 active Skill 的 allowed tool bounds 内。tool iteration ceiling 默认 16；实验可用 8/16/32，但同一 paired comparison 必须同预算。

## §5.3 Skill-aware retrieval interface

Skill-aware retrieval 是一个 deterministic + LLM-guided hybrid 层。接口：

```python
def retrieve_with_skills(
    run_context: RunContext,
    fact_query: FactQuery,
    rule_query: RuleQuery,
    active_skill_set: SkillSet,
    evo_policy: EvoPolicyVersion,
) -> RetrievalAugmentationResult:
    ...
```

返回：

```json
{
  "base_rule_candidates": ["rc1", "rc2"],
  "base_fact_candidates": ["fact1", "fact2"],
  "skill_activations": [
    {
      "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
      "trigger_id": "...",
      "activation_stage": "post_closure_deepening",
      "added_queries": [
        {"tool": "retrieve_building_facts", "query_template": "artifact.sidecar.by_artifact_key"}
      ],
      "added_candidate_refs": ["sidecar_entry:..."]
    }
  ],
  "augmented_rule_candidates": ["rc1", "rc2", "rc3"],
  "augmented_fact_candidates": ["fact1", "fact2", "fact3"],
  "guard_results": {"passed": true}
}
```

Skill 不得删除 `base_rule_candidates` 或 `base_fact_candidates`；只可追加、标注、排序。若 Skill plan 试图排除候选，runtime hard fail 并禁用该 Skill。

## §5.4 Policy-aware ranking

v1 ranking 用加权分数决定 LLM context order，不决定 verifier candidate floor。

默认公式：

```text
score(candidate) =
  1.00 * base_fulltext_score
+ 0.35 * graph_neighbor_boost
+ 0.30 * skill_trigger_boost
+ 0.25 * open_reason_priority_boost
+ 0.20 * artifact_slot_match_boost
+ 0.15 * recent_policy_success_boost
- 1.00 * stale_or_guard_penalty
```

每项定义：

- `base_fulltext_score`：v0.4 fulltext/keyword retrieval score；
- `graph_neighbor_boost`：与已匹配 rule family、slot、artifact、measure 的 graph 邻近度；
- `skill_trigger_boost`：active Skill trigger 命中；
- `open_reason_priority_boost`：当前 closure open/blocked reason 指向该候选；
- `artifact_slot_match_boost`：artifact/sidecar mapping 对齐；
- `recent_policy_success_boost`：来自 active policy 的 aggregate sanitized success，不含 per-run truth；
- `stale_or_guard_penalty`：staleness 或 guard warning。

Policy 可调权重，但必须满足：

```text
0 <= positive weights <= 2.0
-2.0 <= penalties <= 0
candidate_floor enabled
```

## §5.5 Verifier candidate universe floor

### §5.5.1 不变量

`VerifierCandidateUniverse` 必须满足：

```text
U_verifier =
  deterministic_expand(
    all_rule_candidates_with_score_positive
    ∪ all_rule_candidates_selected_by_base_retrieval
    ∪ all_rule_candidates_added_by_active_skills
    ∪ all_rule_cards_required_by_neighbor_family_edges
  )
  - deterministic_exclusions
```

其中 `deterministic_exclusions` 只能包括：

- rulecard bundle 版本不匹配；
- applicability predicate deterministic false；
- schema invalid card；
- duplicate canonical card；
- forbidden source detected。

Skill/Policy 不能新增 exclusion reason。LLM 不能说“这条规则不重要所以不送 verifier”。

### §5.5.2 不变量证明口径

每次 run 记录：

```json
{
  "base_candidate_hash": "sha256:...",
  "skill_added_candidate_hash": "sha256:...",
  "neighbor_expansion_hash": "sha256:...",
  "deterministic_exclusion_hash": "sha256:...",
  "verifier_candidate_universe_hash": "sha256:..."
}
```

审计条件：

```python
assert base_candidates <= verifier_universe | deterministic_exclusions
assert skill_added_candidates <= verifier_universe | deterministic_exclusions
assert not policy_exclusion_reasons
assert not llm_exclusion_reasons
```

若不变量失败，`allow_stop=false`，`stop_reason=verifier_candidate_floor_violation`，报告只能输出 incomplete closure notice。

## §5.6 Trace capture hook

Trace capture 在每个 runtime stage 写 `EvoRunStep`。capture 原则：

- raw prompt 不入 trace；存 prompt template id 与 hash；
- tool input/output 存 canonical hash 与安全摘要；
- candidate set 存 ids 与 hash，若 ids 是 building-specific，trainer 默认读取 hash 和 taxonomy；
- closure summary 可存 open/blocked reason counts；
- report text ref 可存，report guard pass 后进入 agent artifact；
- forbidden scan 必须在 trace finalization 前运行。

示例：

```json
{
  "trace_id": "ERT-CAR-20260523T182806-0776a1ce-44c1",
  "run_id": "CAR-20260523T182806-0776a1ce",
  "evo_policy_version_id": "policy.mbis.runtime.default.v1.0.0",
  "active_skill_set_id": "SS-policy.mbis.runtime.default.v1.0.0-9f2a",
  "closure_summary_json": {
    "closed_count": 2,
    "open_count": 13,
    "blocked_count": 810,
    "open_reason_counts": {
      "missing_fact": 7,
      "missing_measurement": 3,
      "missing_time_anchor": 2,
      "missing_artifact_evidence": 1
    },
    "blocked_reason_counts": {
      "missing_rule_edge": 678,
      "schema_contract_violation": 126,
      "missing_artifact_mapping": 3,
      "ambiguous_fact_binding": 3
    }
  },
  "forbidden_scan_passed": true
}
```

---

# §6 Deterministic Closure Verifier

## §6.1 继承 v0.4 §6

v1 基本继承 v0.4 §6 的闭包验证器：`ObligationSet`、`Obligation`、`ClosureSummary`、`ClosureValidationResult`、obligation derivation、fact binding、threshold evaluation、artifact/evidence obligations、deadline obligations、open/blocked reason、`allow_stop` 规则均不改变。核心不变量仍是：

```python
allow_stop = (
    open_count == 0
    and blocked_count == 0
    and schema_validation_passed
    and forbidden_source_check_passed
)
```

`violated_count > 0` 不导致 `allow_stop=false`；它表示证据闭合但显示疑似未满足，应进入辅助报告的人工审查风险项。

## §6.2 v1 instrumentation fields

v1 只给 verifier 输出新增 provenance/instrumentation，不改判定逻辑。

`Obligation` 可新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_skill_ids` | list[string] | 哪些 Skill 帮助检索到 evidence；不影响 status。 |
| `retrieval_gap_category` | string/null | deterministic diagnostic，如 `artifact_mapping_gap`。 |
| `binding_diagnostics` | json | fact binding 诊断。 |
| `targetable_by_skill` | bool | 是否可被 retrieval/report Skill 改善；不影响 allow_stop。 |

`ClosureValidationResult` 新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `candidate_universe_hash` | string | verifier candidate universe canonical hash。 |
| `rule_slice_hash` | string | RuleSlice hash。 |
| `fact_pack_hash` | string | FactPack hash。 |
| `skill_invocation_ids` | list[string] | 本次 closure 前触发过的 SkillActivation。 |
| `skill_augmented_retrieval_used` | bool | 是否使用 Skill 增广检索。 |
| `policy_version_id` | string | active policy。 |
| `verifier_authority_check` | json | allow_stop/status 是否全由 verifier 生成。 |

`ClosureSummary` 新增：

```json
{
  "verifier_candidate_floor_passed": true,
  "source_visibility_audit_passed": true,
  "skill_policy_non_authority_passed": true
}
```

## §6.3 Skill/Policy 不影响 verifier authority 的不变量

v1 明确禁止：

- Skill 修改 obligation kind 枚举；
- Skill 修改 threshold comparator；
- Policy 修改 `allow_stop` 公式；
- LLM 在 closure 后改写 status；
- evaluator feedback 直接影响单次 closure result。

Skill/Policy 可以影响：

- 哪些 agent-visible facts 更早被检索；
- 哪些 rule cards 在 context 中排序更高；
- open/blocked obligations 的深查顺序；
- report 中如何组织 citation 与人工复核建议。

若 runtime 发现 Skill/Policy 产物包含 verifier override 字段，`pre_policy_publish_guard` 或 `pre_skill_runtime_load_guard` 必须 hard fail。

## §6.4 Deterministic repeatability

在相同 `kg_snapshot_id`、`rulecard_bundle_id`、`fact_pack_hash`、`rule_slice_hash`、`verifier_version` 下，closure verifier 输出必须 bitwise-stable。LLM 非确定性不得影响 verifier 结果；若 LLM 影响了 FactPack/RuleSlice 的构造，变化必须通过 trace hash 与 candidate floor 审计可解释。

---

# §7 Agent Runtime: Prompt / Tools / CoreSkills / OperationalSkills / Hooks / Report Contract

## §7.1 Prompt 继承与 v1 修订

v1 继承 v0.4 §7.1 system prompt 的副驾驶纪律，新增 evo runtime 指令：

1. 你可以使用 active OperationalSkills 改善检索和报告组织；
2. 你不得将 Skill 当作法规或事实来源；
3. 你不得根据 Skill 或 evaluator feedback 推断最终合规结论；
4. 你必须把 closure verifier 的 `allow_stop` 作为是否生成完整报告的唯一开关；
5. 你不得请求或引用 W2、NormativeProjection、expected verdict、basis items；
6. 你不得在当前 run 中生成或修改 Skill；候选 Skill 只能由 post-run evo trainer 起草和 gate。

prompt 中必须包含非权威声明：

```text
OperationalSkills are retrieval and reporting aids only. They do not define legal obligations, do not override rule_card content, and do not determine allow_stop, closure_status, or satisfaction_status.
```

## §7.2 Tool interface v1

v1 继承 v0.4 的 11 个 baseline tool 作为最小 tool set。v1 可以新增以下 tool 或 orchestrator internal function；工程可实现为 tool，也可实现为 runtime service，但契约一致：

| tool / service | 可见性 | 说明 |
|---|---|---|
| `retrieve_active_skills` | agent-visible runtime-safe | 返回 active Skill triggers 与 safe descriptions。 |
| `apply_retrieval_plan` | agent-visible | 执行 `plan.yaml` 中声明的 retrieval plan。 |
| `explain_skill_invocation` | agent-visible | 返回某 SkillActivation 的 provenance safe summary。 |
| `get_active_policy` | agent-visible runtime-safe | 返回 policy runtime subset。 |
| `capture_evo_trace_step` | internal | 写 EvoRunStep。 |
| `query_replay_diagnostics` | evo-trainer-visible | trainer 用，不给 runtime agent。 |

新增 tool 禁止访问 evaluator truth store。任何 tool 返回 payload 都必须过 `post_retrieval_source_audit` 或等价 source audit。

## §7.3 Skill 分层

### §7.3.1 Layer 0 CoreSkills

Layer 0 CoreSkills 是宪法层流程纪律。v1 继承 v0.4 的 4 个 seed Skill 并把 status 设为 `core`：

1. `skill.mbis.building_assessment_workflow`
2. `skill.mbis.fact_kg_retrieval`
3. `skill.mbis.rule_obligation_derivation`
4. `skill.mbis.auxiliary_report_writer`

CoreSkills 特征：

- origin=`manual_seed` 或 `spec_revision`；
- status=`core`；
- 不由 evo loop 自动淘汰；
- 不由 LLM 自动改写；
- 可通过 spec revision 更新；
- 只规定流程、检索纪律、报告格式、闭包边界；
- 不包含 W2 或 final verdict。

### §7.3.2 Layer 1 OperationalSkills

Layer 1 是自进化主体。允许 kind：

- `micro_routing`
- `retrieval_macro`
- `report_structure`
- `diagnostic_hint`

OperationalSkill 可自动进入 draft/candidate/staged/active/retired/quarantined 生命周期，但必须通过 §9 和 §10 gates。OperationalSkill 权限：

| kind | 可影响 | 不可影响 |
|---|---|---|
| `micro_routing` | Skill 激活排序、tool 优先级、open reason 深查顺序 | verifier candidate floor、status |
| `retrieval_macro` | 增加检索 query、追加 fact/rule candidates | 删除 candidates、改 threshold |
| `report_structure` | 报告章节结构、citation grouping | 报告结论、allow_stop |
| `diagnostic_hint` | open/blocked 解释、人工复核建议组织 | closure result |

### §7.3.3 Layer 2 MetaSkills

Layer 2 MetaSkills 描述“如何生成/评估 Skill 或 Policy”的元策略。v1 定义该层，但默认 `status=meta_disabled`，不允许自动 active。任何 Layer 2 变更必须经 spec revision 或 release gate 的人工批准，并且不能在 runtime agent 内执行。v1 工程必须实现对 Layer 2 的拒绝加载：

```python
if skill.layer == "L2_meta_disabled" and runtime_mode == "production":
    raise SkillLoadError("Layer 2 MetaSkills are not runtime-loadable in v1")
```

这样保留长期结构，但不开放自修改 Skill generator 本身。

## §7.4 v1 Hooks

v1 继承 v0.4 五个 hard hook：

- `pre_run_input_guard`
- `pre_retrieval_query_guard`
- `post_retrieval_source_audit`
- `post_verifier_stop_gate`
- `pre_output_language_guard`

**v1.1 hook 适用范围补充**（修订自代理 B Codex review #5 / spec 调研提案 2026-05-26）：

- **`pre_retrieval_query_guard` 必须在 LLM 提供的任何字符串 query 下发到 KG / fulltext 索引 / Cypher / 任何检索后端之前调用，无工具豁免**。这覆盖 `retrieve_rule_slice` / `retrieve_building_facts` / `search_regulation` / `lookup_clause` / `get_facts_by_slot` / 任何接受 LLM 文本 query 的工具或后端。豁免条件不存在；fulltext 全文搜索类工具也不豁免（LLM 可能在 query 里写 `expected_verdict` / `W2 truth` 探测 W2 字段，guard 必须拦）。
- `post_retrieval_source_audit` 必须在 retrieval payload 返回 LLM 之前调用，覆盖所有 retrieval 工具，无豁免。
- `pre_run_input_guard` 在 run 启动时调用，对 building_id / world_id / 任何 input 字段扫禁字。
- `post_verifier_stop_gate` 在 closure verifier 输出后调用，验证 `allow_stop` 由 verifier 唯一决定。
- `pre_output_language_guard` 在 LLM 报告输出前调用，扫报告文本禁字（含 `expected_verdict` / `W2 truth` / verdict-like phrase 等）。

v1 新增六个 evo hard hook。

### §7.4.1 `pre_skill_candidate_guard`

时机：LLM/trainer 起草 SkillPackage 后、写入 candidate store 前。  
输入：SkillPackage directory。  
输出：guard result。  
hard checks：

- package 全文件 forbidden scan；
- 禁止 W2 labels/properties/files；
- 禁止 building/world/run/projection literal；
- 禁止 verdict-like strategy；
- 禁止 override verifier/force allow_stop；
- 检查 `kind` 在 v1 四类允许范围；
- 检查 source trace 数量与可见性；
- 检查 `SKILL.md` 是否包含 non-authority statement。

失败处理：Skill 不进入 candidate；写 quarantine artifact。

### §7.4.2 `post_skill_validation_audit`

时机：Gate 2-4 replay/holdout 完成后。  
输入：SkillValidationRecord set。  
hard checks：

- Gate 0-4 均存在；
- closure regression count = 0；
- leakage hits = []；
- stability K=5 pass；
- holdout pass；
- validation notes 无自由文本 W2 泄漏；
- metric bucket 不含 per-run truth。

失败处理：不允许 staged/active。

### §7.4.3 `pre_skill_runtime_load_guard`

时机：runtime 加载 SkillSet 前。  
hard checks：

- status in `core/active`；
- staleness_status=`fresh`；
- package hash 与记录一致；
- rulecard bundle 与 KG snapshot compatible；
- Layer 2 not loadable；
- conflict resolver 已产生 runtime-safe decision；
- allowed_tools 均在 runtime tool allowlist；
- forbidden_actions 完整。

失败处理：禁用该 Skill；若禁用导致 SkillSet 无效，回退 last known good SkillSet。

### §7.4.4 `pre_feedback_ingest_guard`

时机：broker 输出 packet 写入 EvoMemoryStore 前。  
hard checks：

- run_count ≥10；
- 每个 unsuppressed cell building_count ≥3；
- rounding policy 为 nearest_0.05 或 bucket；
- release_delay_window_count ≥1；
- 无 run_id/building_id/world_id 明细；
- forbidden scan pass；
- reconstruction audit pass。

失败处理：packet 不发布；相关 trainer job fail。

### §7.4.5 `pre_policy_publish_guard`

时机：candidate policy 发布 staged/active 前。  
hard checks：

- candidate floor enabled；
- no verifier override；
- no allow_stop policy；
- no per-run reward；
- closure non-regression pass；
- leakage audit pass；
- rollback ref 存在；
- canary plan 存在；
- skill set load guard pass。

失败处理：policy 不能 active；若 staged 已有，则 quarantine。

### §7.4.6 `post_evo_writeback_audit`

时机：任何 Skill/Policy/Feedback/Trace 写入 EvoMemoryStore 或 Rule-Skills KG 后。  
hard checks：

- 新节点/边 label 在 allowed namespace；
- 无 evaluator-only fields；
- 无 forbidden relationship to evaluator truth；
- runtime-safe projection 不含 validation metric details；
- fact/rule KG 未被 feedback 节点污染。

失败处理：回滚本次 write transaction；触发 security incident artifact。

## §7.5 Hook event order

```text
pre_run_input_guard
pre_skill_runtime_load_guard
pre_retrieval_query_guard
post_retrieval_source_audit
post_verifier_stop_gate
pre_output_language_guard
trace_finalization_scan
post_evo_writeback_audit
```

Skill/feedback/policy 的离线链路：

```text
pre_feedback_ingest_guard
pre_skill_candidate_guard
post_skill_validation_audit
pre_policy_publish_guard
post_evo_writeback_audit
```

## §7.6 Report Contract v1

v1 继承 v0.4 报告结构：`allow_stop=true` 才能生成完整辅助审查报告；`allow_stop=false` 只能生成闭包未完成说明。v1 新增 `skill_invocation_disclosure` 字段。

### §7.6.1 完整报告新增字段

```yaml
skill_invocation_disclosure:
  statement: "以下 Skill 仅用于检索排序、证据补查或报告组织，不构成法规义务或最终裁决依据。"
  active_policy_version_id: "policy.mbis.runtime.default.v1.0.0"
  skill_invocations:
    - skill_version_id: "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"
      kind: "retrieval_macro"
      activation_stage: "post_closure_deepening"
      retrieval_role: "补查 artifact / sidecar evidence"
      affected_obligation_kinds: ["artifact", "report_field"]
```

禁止：

- 写入 feedback packet id；
- 写入 evaluator metric；
- 写入 W2 expected verdict；
- 写入“该 Skill 判断本项 satisfied/violated”。

### §7.6.2 incomplete closure notice

若 `allow_stop=false`，报告必须包含：

- open obligations summary；
- blocked obligations summary；
- deterministic reason counts；
- recommended human data completion actions；
- Skill invocation disclosure（如有），但只说明“曾用于补查，仍未闭合”。

禁止用 Skill 或 LLM 推测最终结果。

---

# §8 Evaluation and Feedback Broker

## §8.1 v1 重写原则（v1.1 再修订）

v0.4 §8 的"evaluator 不反写"在 v1.0 修订为"raw evaluator 不反写；sanitized feedback 经 broker 后可进入 trainer"。v1.1 进一步修订为：

```text
artifact 层 blind：runtime-loadable artifact（active Skill/Policy/agent KG/Fact KG）
                  不得含 raw W2 token、case-specific truth；
trainer 工作流自由读 raw W2：trainer 可直接 mount evaluator private store 的
                                  EvalTruthReport、W2 projection tables 算 reward/loss；
EvoFeedbackBroker 角色：从"trainer 信号源"降级为"runtime agent 可选的历史趋势反馈接口"。
artifact 离开 trainer 进入 active runtime 前，必过 §9.4 Gate 0-4 + §11 leakage audit。
```

**v1.1 修订背景**（§0.6 修订 1）：v1.0 把"artifact 层 blind"与"trainer 工作流 blind"错误捆绑。机器学习常识 separation：训练阶段看 ground truth 是天经地义（监督信号没法绕开），推理阶段不看才是 data leakage。v1.1 把两件事拆开：约束 artifact 输出 + runtime 输入，不约束 trainer 工作流输入。

**禁止旁路**仅适用于以下两条路径（artifact 与 runtime 层）：
- evaluator → agent runtime 直接写：禁止（runtime credential 无 evaluator_truth_store/raw 访问权，见 §2.5）；
- evaluator → active Skill / active Policy artifact 直接写：禁止（必经 trainer + Gate 0-4 promote）。

**取消的 v1.0 禁止路径**（v1.1 后允许）：
- evaluator private store → evo trainer 进程直接 mount 读取：v1.1 允许（trainer credential 已加 evaluator_truth_store/raw 到 read allowlist，见 §2.5）。

## §8.2 EvalTruthReport

Evaluator 在 private store 中生成 `EvalTruthReport`。它可以包含 raw W2 comparison，但永远 evaluator-only。

示例 private schema：

```json
{
  "eval_truth_report_id": "ETR-EW-20260523-001",
  "eval_window_id": "EW-20260523-001",
  "source_w2_bundle_id": "W2-...",
  "runs_evaluated": ["CAR-..."],
  "per_run_results": [
    {
      "run_id": "CAR-...",
      "expected_verdict": "violated",
      "projection_refs": ["..."],
      "basis_item_refs": ["..."],
      "family_comparison": {"...": "..."},
      "threshold_comparison": {"...": "..."}
    }
  ],
  "raw_metrics": {
    "macro_f1": 0.71,
    "family_recall": {"...": 0.60}
  }
}
```

该文件不得进入 EvoMemoryStore。Broker 只可读取它并输出 sanitized packet。

## §8.3 EvoFeedbackBroker 输入输出

Broker 输入：

- `EvalTruthReport` hash/path（private）；
- agent artifacts refs；
- metric taxonomy config；
- aggregation window config；
- k-anonymity config；
- release delay config。

Broker 输出：

- `SanitizedFeedbackPacket`；
- suppressed cell audit；
- reconstruction audit summary；
- forbidden scan result；
- broker log hash。

Broker 不输出 raw report path；只输出 raw report hash 用于审计。

## §8.4 三层反馈颗粒度

### §8.4.1 Layer F1：agent-owned per-run feedback

来源：

- closure open/blocked reason；
- schema validation fail；
- forbidden source audit；
- report citation coverage；
- unsupported claim scan；
- tool budget/cost；
- candidate floor violation。

颗粒度：可 per-run、per-obligation、per-rule_card。  
可进入 agent runtime：是，因其不来自 W2。  
示例：

```json
{
  "feedback_type": "agent_owned_closure_diagnostic",
  "run_id": "CAR-...",
  "obligation_id": "obl-...",
  "open_reason_code": "missing_measurement",
  "source_rule_card_id": "rc.mbis.inspection.structural_components.ri.coverage...",
  "suggested_action": "retrieve measurements for required measure_key and target component scope"
}
```

### §8.4.2 Layer F2：W2-derived batch aggregate feedback

来源：EvalTruthReport aggregate。  
颗粒度：batch-level only。  
约束：

- batch ≥10 runs；
- cell ≥10 runs and ≥3 buildings；
- no run/building/obligation id；
- rounded 0.05 或 bucket；
- delay ≥1 eval window；
- no raw basis.

示例：

```json
{
  "aggregation_level": "batch_slot_class",
  "dimension": {
    "semantic_slot_class": "artifact_evidence",
    "obligation_kind": "report_field"
  },
  "metric_name": "slot_requirement_recall_delta",
  "metric_bucket": "low",
  "delta_bucket": "-0.10",
  "suggested_evo_action": "skill_induction_candidate"
}
```

### §8.4.3 Layer F3（v1.1 删除）

**v1.0 内容**：evaluator 替 trainer 在 private replay 上算 candidate Skill/Policy 的 before/after，把 bucket 反馈给 trainer。

**v1.1 删除原因**：v1.0 设这一层是因为 trainer 不能读 raw W2，所以必须借 evaluator 算 before/after。v1.1 §0.6 修订后 trainer 可直接读 raw W2 算 before/after，本 F3 layer 不再需要。

**v1.1 后的 candidate validation 路径**：trainer 自己在 replay set 上对 candidate Skill/Policy 跑 paired evaluation → Gate 2 Replay A/B（§9.4.3）→ Gate 4 Holdout / Counterfactual（§9.4.5）→ §11.9 reconstruction audit（审 artifact）。Evaluator 只负责生成 `EvalTruthReport`，不再代算 before/after。

## §8.5 k-anonymity 与 suppression

Broker 对每个 feedback cell 执行：

```python
cell_releasable = (
    cell.run_count >= 10
    and cell.building_count >= 3
    and not contains_forbidden_fields(cell)
)
```

若不满足：

- 优先合并到更粗 taxonomy；
- 仍不满足则 `suppressed=true`；
- suppressed cell 只记录 suppression reason，不输出 metric；
- suppressed cell 不得用于 Skill induction。

## §8.6 延迟发布（v1.1 删除）

**v1.0 内容**：W2-derived feedback 至少延迟一个 eval window 发布，packet 不列本窗口 run_id。

**v1.1 删除原因**：延迟发布是为生产 traffic 假设服务（防 leak 信号被实时反推），实验室阶段（单机、无 production agent、无持续 traffic）无此节奏。v1.1 后 broker 输出 packet 不强制 delay；运行什么节奏由实验脚本决定。

正式 production 部署阶段（v1.5）按需要重新引入延迟发布。

## §8.7 四类盲化证据

每个 feedback release 必须生成以下证据。

### §8.7.1 静态证据

- packet schema 无 forbidden field；
- packet text scan 无 forbidden phrases；
- packet cell 满足 k-anonymity；
- no raw ids；
- no free-text evaluator comment。

### §8.7.2 动态证据

- runtime credential 无 evaluator store 权限；
- trainer credential 无 raw W2 path；
- broker logs 显示 raw report 只在 broker 进程读取；
- post_evo_writeback_audit pass。

### §8.7.3 统计证据（v1.1 重定位）

**v1.1 修订**：原 §8.7.3 运行 W2 reconstruction probe 审 "sanitized feedback packet 是否泄漏 W2"。v1.1 后该审计落点改为 audit **candidate artifact**（trainer 输出的 candidate SkillPackage / candidate EvoPolicyVersion），逻辑在 §11.9。

**v1.1 后的 §8.7.3 静态证据**：仅当真启用 broker → runtime trend feedback 接口时，扫描 packet 文本 + cell 不含 forbidden field、不含 per-run id；其他 statistical evidence 责任移至 §11.9 audit artifact。

### §8.7.4 因果证据

Skill/Policy 提升必须在 held-out paired evaluation 中体现为 retrieval/coverage/report 改善；禁用相关 Skill/Policy 后提升应下降。若提升只出现在 feedback batch 内，且 held-out 不提升，则判定 overfit，不发布。

**v1.1 备注**：本条仍生效——held-out paired evaluation 是 trainer 自己跑的（不再借 evaluator F3 算）。trainer 可直接读 raw W2 算 metric，但 metric 是否真泛化仍由 held-out paired evaluation 决定（artifact 端约束）。

## §8.8 Broker pseudocode（v1.1 简化）

```python
def broker_release(eval_truth_report, eval_window, taxonomy):
    """v1.1：broker 仅当对 runtime agent 暴露历史趋势反馈时启用。
    trainer 工作流不再走 broker（trainer 直接读 raw EvalTruthReport）。
    """
    raw = read_private(eval_truth_report)
    cells = aggregate(raw, taxonomy)

    released = []
    for cell in cells:
        cell = remove_ids(cell)
        cell = round_metrics(cell, policy="nearest_0.05")
        if cell.run_count < 10 or cell.building_count < 3:
            merged = try_merge_to_coarser_taxonomy(cell)
            if not merged or merged.run_count < 10 or merged.building_count < 3:
                released.append(suppressed_cell(cell))
                continue
            cell = merged
        assert not contains_forbidden_fields(cell)
        released.append(cell)

    packet = build_packet(released)
    # v1.1 删除：assert packet.release_delay_window_count >= 1（§8.6 删）
    # v1.1 删除：assert reconstruction_probe(packet).delta_accuracy <= 0.05
    #            原 packet 端 reconstruction audit 改为 artifact 端审计，见 §11.9
    assert pre_feedback_ingest_guard(packet).passed
    return packet
```

## §8.9 Feedback 不得进入报告

报告 writer 的 retrieval namespace 不包含 SanitizedFeedbackPacket。若 LLM 输出引用“evaluator feedback”“batch score”“expected verdict trend”，`pre_output_language_guard` 必须拦截并要求重写。



---

# §9 Evolution Loop Main Chapter

## §9.1 总览（v1.1 简化）

v1 的 evolution loop 是 run 后的版本化发布系统，不是单次 run 内 LLM 自我改写。主链路（v1.1 简化后）：

```text
ComplianceAssessmentRun
  → EvoRunTrace
  → ReplayCase eligibility
  → agent-owned diagnostics + SanitizedFeedbackPacket（v1.1 packet 角色降级，
    trainer 不再依赖；可选保留用于 runtime trend feedback）
  → Skill induction / Policy training（v1.1 trainer 直接读 raw EvalTruthReport
    + W2 projection tables 算 reward/loss）
  → Skill validation Gate 0-4 / Policy validation
  → active SkillSet / EvoPolicyVersion（v1.1 简化：通过全部 Gate 即 active，
    无 staged/canary 中间态）
  → next ComplianceAssessmentRun
```

v1.1 修订点：
- 删除 v1.0 旧 `staged release → canary → active` 中间态——`draft → Gate 0-4 全 pass → active`，无 canary（spec §0.6 修订 2 / §9.8 / §9.9 / §10.6）
- broker 角色降级：v1.0 是 trainer 唯一信号源；v1.1 trainer 直接读 raw W2，broker 改为 runtime trend feedback 可选接口（§0.6 修订 1 / §2.1.4 / §8.1）
- artifact 离开 trainer 进 active 前必过 Gate 0-4 + §11 leakage audit，audit 焦点是 artifact 端而非 packet 端（§11.9 重定位）

该链路 runtime 端仍遵守 blind 红线：agent runtime 不接 raw W2，runtime-loadable artifact（active Skill / Policy）不含 raw W2 token。**trainer 工作流允许读 raw W2**（v1.1 §0.6 修订 1），但 trainer 输出的 candidate artifact 必经 Gate 0 静态扫确认。

## §9.2 Replay Buffer 协议

### §9.2.1 Replay Buffer 定义

Replay Buffer 是 `ReplayCase` 的集合。一个 trace 进入 buffer 前必须满足：

```python
eligible = (
    trace.forbidden_scan_passed
    and trace.source_visibility_audit_passed
    and trace.schema_audit_passed
    and trace.candidate_universe_hash is not None
    and trace.closure_result_ref is not None
)
```

不合格 trace 保留审计，但 `eligibility != eligible`，不能用于 Skill induction、Policy training 或 release metric。

### §9.2.2 Replay split

每个 eligible trace 进入固定 split：

| split | 用途 | 默认比例 |
|---|---|---:|
| `evolve_train` | Skill induction、policy training | 60% |
| `gate_validation` | Gate 2 replay A/B、policy candidate validation | 20% |
| `held_out_test` | 最终 held-out 指标与论文曲线 | 20% |

split 按 building/world family/rule family 分层，避免同一 building 同时出现在 evolve_train 与 held_out_test。若数据量小于 50 runs，仍保持 held_out_test 至少 10 runs；不足则暂停 active promotion，只允许 draft/candidate。

### §9.2.3 ReplayCase weight

每个 ReplayCase 计算：

```text
effective_trace_weight =
  validity_i × novelty_i × coverage_weight_i × feedback_available_i
```

- `validity_i`：eligible=1，否则 0；
- `novelty_i`：新 rule family/slot/open reason 组合为 1.0，重复组合按 `1/sqrt(1+n_seen)` 衰减，下限 0.2；
- `coverage_weight_i`：普通 case=1.0，罕见 artifact/threshold boundary/high-risk family=1.5，极罕见且通过 audit=2.0，最高 3.0；
- `feedback_available_i`：有 sanitized feedback=1.2，无=1.0。

Replay Buffer 生成 `replay_set_id` 与 canonical hash，所有 gate 引用 hash，不引用可变查询。

## §9.3 Skill induction 算法

Skill induction 由 evo trainer 运行。输入：

- eligible replay cases；
- closure open/blocked reason distribution；
- SkillActivation success/failure stats；
- sanitized feedback cells；
- active Skill coverage gaps；
- policy diagnostics。

输出：draft `EvoSkillPackage`。

### §9.3.1 自生成触发条件

满足任一条件可生成 draft：

**触发 A：重复失败。**

```python
same_pattern_count >= 5
and (building_count >= 3 or world_family_count >= 2)
```

pattern 维度：

```text
(rule_family, semantic_slot_class, obligation_kind, open_reason_code/blocked_reason_code)
```

示例：`mbis.reporting.* + artifact_evidence + report_field + missing_artifact_evidence`。

**触发 B：重复成功。**

某个 tool 序列、retrieval plan 或 Skill activation pattern 在 ≥5 个 eligible runs 中，相对 current policy：

```text
open_plus_blocked_delta <= -5%
OR median_tool_calls_delta <= -15%
```

且 closure non-regression。

**触发 C：盲化评价缺口。**

SanitizedFeedbackPacket 的 batch-level cell 显示某类能力低于目标线：

```text
feedback_cell.run_count >= 10
and feedback_cell.building_count >= 3
and feedback_cell.suggested_evo_action == "skill_induction_candidate"
```

### §9.3.2 Draft 生成

draft 生成只允许使用以下上下文：

- replay pattern aggregate；
- agent-owned example summaries；
- safe source trace hashes；
- rule family / slot / obligation taxonomy；
- sanitized feedback bucket；
- active Skill conflicts/coverage；
- CoreSkill policy statements。

禁止使用：

- raw W2；
- per-run expected verdict；
- building literal；
- evaluator raw comments；
- basis item text；
- projection ids。

draft 生成 prompt 必须包含：

```text
Write a retrieval/routing/reporting Skill only. Do not encode outcome rules. Do not decide compliance. Do not override closure verifier. Use abstract rule/slot/obligation scope only.
```

### §9.3.3 Draft 输出约束

draft 必须产出完整 SkillPackage：

```text
skill.json
SKILL.md
plan.yaml           # required for micro_routing/retrieval_macro
validation_records.jsonl
```

draft status=`draft`，`source_trace_hashes` 可少于 5；但不能 promotion。

## §9.4 Skill validation 5 Gate

### §9.4.1 Gate 0：Static Safety Gate

目的：防泄漏、防裁决越权、防实例记忆。

检查：

1. package 全文件 forbidden field scan；
2. W2 file/path/label/property scan；
3. verdict-like phrase scan；
4. verifier override phrase scan；
5. building/world/run/projection literal scan；
6. `SKILL.md` 是否包含 non-authority statement；
7. `skill.json.kind` 是否在允许枚举；
8. `allowed_tools` 是否为 runtime allowlist 子集；
9. `forbidden_actions` 是否至少包含：
   - `override_verifier`
   - `force_allow_stop`
   - `emit_final_verdict`
   - `read_evaluator_truth`
   - `suppress_rule_candidate`

失败即 quarantined。Gate 0 无 soft fail。

### §9.4.2 Gate 1：Schema / Provenance Gate

目的：确保 Skill 可解析、可追溯、可安全触发。

检查：

- `skill.json` 符合 Appendix B schema；
- `plan.yaml` 符合 §10 plan DSL；
- trigger predicate 只引用 agent-visible fields；
- scope 引用的 rule family / rule card / slot / measure / artifact 在当前 bundle 存在；
- candidate 及以上 `source_trace_hashes >= 5`；
- candidate 及以上 `support_building_count >=3 OR support_world_family_count >=2`；
- source traces 均 eligible；
- validation_records 不含 raw evaluator note；
- package hash 可复现。

失败：保持 draft 或 quarantine；不得 candidate/staged。

### §9.4.3 Gate 2：Replay A/B Gate

目的：证明 Skill 在冻结 replay set 上不回退。

流程：

```text
for each replay case in gate_validation set:
  run baseline/current policy without candidate Skill
  run same policy + candidate Skill
  compare closure, retrieval, report guard, cost
```

通过条件：

- leakage audit 0 hits；
- forbidden source audit 0 hits；
- closure regression count = 0；
- closed case satisfaction comparator 一致率 = 100%；
- `allow_stop` authority check = 100%；
- open+blocked 总数不得增加；
- 若 Skill 声称效率提升：median tool calls 至少下降 15%；
- 若 Skill 声称覆盖提升：目标 slot/artifact/evidence coverage 至少提升 5%；
- candidate universe floor pass 100%。

Gate 2 metric 只写 aggregate/bucket。

### §9.4.4 Gate 3：Stability Gate

目的：抵抗 LLM orchestration 随机性。

流程：同一 replay batch 运行 K=5 次。若 temperature=0 仍必须做 5 次以覆盖 tool ordering nondeterminism。

通过条件：

- closure summary 5/5 一致；
- allow_stop 5/5 一致且由 verifier 产生；
- report guard 5/5 pass；
- Skill activation 不产生无限循环；
- median tool calls 方差不超过 20%；
- forbidden scan 5/5 pass。

### §9.4.5 Gate 4：Holdout / Counterfactual Gate

目的：防过拟合。

holdout 切分：

- building disjoint；
- world family 分层；
- rule family 分层。

counterfactual tests：

1. fact order shuffle；
2. query paraphrase；
3. non-essential fact removal；
4. equivalent rule context order shuffle；
5. sanitized feedback cell removal；
6. inactive Skill conflict injection。

通过条件：

- holdout closure non-regression；
- target metric 不低于 current policy；
- no building/run literal dependency；
- counterfactual 后不产生 verdict-like output；
- W2 reconstruction probe 不超过 5pp 提升；
- report unsupported claim rate 不上升。

### §9.4.6 Gate record canonical form

每个 gate 写一行 JSONL：

```json
{
  "validation_id": "SVR-skill.mbis.retrieval_macro.artifact_evidence_gap.v1-gate2-20260523",
  "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
  "validation_stage": "gate2_replay_ab",
  "eval_set_id": "RS-gate-validation-20260523",
  "eval_set_hash": "sha256:...",
  "run_count": 40,
  "building_count": 12,
  "world_family_count": 4,
  "metric_name": "target_artifact_evidence_coverage_delta",
  "metric_delta_bucket": "+0.05",
  "passed": true,
  "failure_reasons": [],
  "leakage_hits": [],
  "closure_regression_count": 0,
  "allow_stop_authority_check": true,
  "validator_version": "skill_gate_v1.0"
}
```

## §9.5 Skill promotion（v1.1 简化）

**v1.1 状态机**：

```text
draft
  --Gate0+Gate1+Gate2+Gate3+Gate4 pass and source_trace_hashes>=5-->
active
  --retirement 条件满足-->
retired
```

**v1.1 promotion 条件**（简化为单一 gate 集合）：

| From | To | 条件 |
|---|---|---|
| draft | active | Gate 0/1/2/3/4 全 pass；≥5 source traces；≥3 buildings 或 ≥2 world families；release card pass；conflict resolver pass |
| active | retired | retirement 条件满足（见 §9.6.2 Soft retirement）|

**v1.1 删除的旧状态**：`candidate`、`staged`、`rolled_back`、`quarantined`。

- `candidate` / `staged` 中间态：v1.0 把 Gate 0-4 拆成两步通过两个中间态，v1.1 合成一步——所有 Gate 必须全 pass 才能 active；任一 Gate fail 就保持 draft（不进任何中间态）。
- `rolled_back`：v1.0 用于 canary 失败后保留版本元信息；v1.1 无 canary，回滚靠 git revert active → 改回上一版本，无需独立 status。
- `quarantined`：v1.0 用于"出 active 后发现 leakage 立即下线"。v1.1 实验室阶段直接把出问题的 active 改 retired 并 git revert，不需要独立隔离态。

Promotion 写入 Rule-Skills KG 与 EvoReleaseCard。**v1.1 不再要求 canary rollout**。

## §9.6 Skill retirement

### §9.6.1 Immediate quarantine

以下条件立即 quarantine：

- leakage audit fail；
- W2 forbidden token/path 出现在 package/runtime trace；
- closure regression；
- Skill 暗示 final verdict 或 allow_stop 权威；
- package hash mismatch；
- stale rulecard bundle 且无法 revalidate；
- building/run/projection literal dependency；
- runtime infinite loop；
- candidate floor violation。

### §9.6.2 Soft retirement

满足任一条件进入 retirement review，自动 retired：

- 最近 50 次 eligible activation median benefit ≤0；
- 连续 3 个 eval batch 无正收益；
- eligible_count ≥200 且 activation_rate <1%；
- fallback_to_baseline_rate >60%；
- 被新版本 supersede 且新版本 holdout 更优；
- staleness 超过 2 个 rulecard bundle release window。

retired 不删除，只是不加载。历史保留用于论文曲线与审计。

## §9.7 EvoPolicy training 算法

### §9.7.1 输入（v1.1 修订）

- ReplayCase evolve_train set；
- active Skill stats；
- closure diagnostics；
- report guard diagnostics；
- **`EvalTruthReport` raw**（v1.1 新增，trainer 直接读 evaluator private store 算 reward/loss/counterfactual/before-after）；
- **W2 projection tables raw**（v1.1 新增）；
- sanitized feedback packets（v1.1 可选，仅当 runtime trend feedback 接口启用时填）；
- cost metrics；
- current policy config。

### §9.7.2 输出

Candidate `EvoPolicyVersion`，字段见 §3.6.4。

### §9.7.3 v1 默认 trainer

v1 默认 trainer 是 deterministic batch rule trainer，不要求机器学习模型。步骤：

```python
def train_policy(replay_cases, feedback_packets, current_policy):
    p = copy(current_policy)

    # 1. open/blocked reason priority
    reason_counts = aggregate_open_blocked_reasons(replay_cases)
    p.open_obligation_priority = rank_by_frequency_and_fixability(reason_counts)

    # 2. skill activation ordering
    stats = aggregate_skill_activation_stats(replay_cases)
    p.skill_activation_order = sort_by(validation_score, median_benefit, staleness)

    # 3. retrieval weights
    deficits = aggregate_feedback_deficits(feedback_packets)
    for deficit in deficits:
        adjust_weight(p.ranking_weights, mapped_feature(deficit), step=0.05)

    # 4. cost fallback
    if median_tool_calls_increase(p) > 15%:
        tighten_deep_lookup_budget(p)

    # 5. enforce bounds
    enforce_candidate_floor(p)
    enforce_weight_bounds(p, min=-2.0, max=2.0)

    return candidate_policy(p)
```

weight step 固定 0.05；单次 policy version 对同一 weight 调整不超过 ±0.20，避免震荡。

### §9.7.4 Policy validation（v1.1 删 canary）

Candidate policy 必须通过：

- replay A/B：open+blocked 不增加，closure non-regression；
- held-out paired eval：目标 aggregate metric 不下降；
- tool cost：median tool calls 不增加超过 15%，除非 coverage 提升 ≥5%；
- leakage audit（含 §11.9 artifact 端 reconstruction probe）；
- candidate floor audit；
- SkillSet load audit。

**v1.1 删除**：`canary plan`（实验室阶段无 traffic 切流）。

### §9.7.5 Policy promotion（v1.1 简化）

**v1.1 状态机**：

```text
draft
  --replay A/B pass + held-out pass + leakage audit pass + candidate floor pass-->
active
  --retirement 条件满足-->
retired
```

**v1.1 promotion 条件**：所有 §9.7.4 validation 项全 pass 即从 draft 直接 active。

**v1.1 删除的旧状态**：`candidate`（中间态合并到 draft）+ `staged`（中间态合并到 active 前一刻）+ `rolled_back`（git revert 代替）。

**v1.1 删除**：`canary pass + rollback ref present`（无 canary、git history 代替 rollback ref）。

## §9.8 Canary rollout（v1.1 删除）

**v1.0 内容**：新 Skill/Policy active 前按 10% traffic_percent 灰度，触发 rollback_on 条件自动回滚。

**v1.1 删除原因**：实验室阶段（单机、无 production agent、无 traffic 切流概念）不存在 canary 语义。Skill/Policy 通过 §9.7.5 validation 后直接 active；出问题 git revert。

正式 production 部署阶段（v1.5）按需要重新引入 canary rollout，含 traffic_percent、min_runs、rollback_on 条件等。

## §9.9 Rollback（v1.1 删除）

**v1.0 内容**：rollback artifact 含 rollback_id / from_version / to_version / trigger / executed_at 等字段，状态机加 `rolled_back` / `quarantined` 态。

**v1.1 删除原因**：实验室阶段回滚 = `git revert` + `git push` + 重新 load active artifact。不需要独立 rollback artifact schema、不需要 `rolled_back` status、不需要 trigger 字段。出问题的 artifact 直接 retired（见 §9.5 v1.1 简化状态机），git history 保留完整版本演进。

正式 production 部署阶段（v1.5）按需要重新引入 rollback artifact 与状态机。

## §9.10 Batch scheduling（v1.1 改为实验脚本驱动）

**v1.0 内容**：scheduler 跑 after_each_run / nightly / next_production_window 等节奏。

**v1.1 修订**：实验室阶段无 production traffic、无 nightly 自动化运维需求。所有 evo loop 节奏由实验脚本（如 `scripts/run_evo_batch_experiment.py` / `scripts/run_evo_induction_experiment.py`）显式驱动。脚本何时跑 trace ingest、何时跑 induction、何时跑 policy training、何时 promote artifact，都由实验设计者按需安排。

**v1.1 留存的 minimal scheduling 契约**（实验脚本必须保证的顺序，不必自动化）：

1. trace ingest 必须在 candidate skill induction 之前（induction 需要 trace）；
2. Gate 0-4 必须在 promote draft → active 之前；
3. held-out paired eval 必须在 Gate 4 / §11.9 audit 之内；
4. retirement 检测可在任何时刻人工触发或在实验结尾批量跑。

正式 production 部署阶段（v1.5）按需要重新引入 cron-style scheduler。

## §9.11 Evolution audit log（v1.1 字段重定位）

每次 evolution job 生成：

```json
{
  "evo_job_id": "EJOB-20260523-skill-induction-001",
  "job_type": "skill_induction",
  "input_replay_set_hash": "sha256:...",
  "input_feedback_packet_ids": ["SFP-..."],
  "input_eval_truth_report_hashes": ["sha256:..."],
  "outputs": ["skill.mbis.retrieval_macro.artifact_evidence_gap.v1"],
  "forbidden_scan_passed": true,
  "credential_profile": "evo_trainer",
  "raw_w2_access": true,
  "artifact_contains_raw_w2": false,
  "completed_at": "2026-05-23T22:00:00Z"
}
```

**v1.1 字段修订**：
- 原 `raw_w2_access: false`（v1.0 trainer 禁读 raw W2）→ v1.1 改为 `raw_w2_access: true`（trainer 自由读 raw W2 是 v1.1 设计意图）；
- 新增 `artifact_contains_raw_w2: bool`（**v1.1 新硬约束**）：必须 false，由 §11.9 audit 落地——trainer 输出的 candidate artifact 经 Gate 0 静态扫 + reconstruction probe 后确认；
- 新增 `input_eval_truth_report_hashes: list[string]`（trainer 这次训练用了哪些 raw W2 report，便于审计追溯）。

Audit log 是 release gate 必需输入。

## §9.12 Minimal v1 implementation path（v1.1 砍 7-8）

v1.1 工程第一阶段必须实现：

1. EvoRunTrace capture；
2. ReplayCase eligibility；
3. EvoFeedbackBroker packet（v1.1 实现保留但角色降级为 runtime trend feedback 接口，trainer 工作流不依赖）；
4. EvoSkillPackage Gate 0-4；
5. active SkillSet loader；
6. EvoPolicyVersion loader；
7. ~~release card~~（v1.1 简化，仅保留 EvoReleaseCard schema 核心字段，无 canary/rollback ref）；
8. ~~rollback~~（v1.1 删除，用 git revert 代替）。

**v1.1 必须项简化**：项目核心实现是 1-6；项 7 EvoReleaseCard schema 仍要落地（leakage_audit_passed / closure_non_regression_passed 等字段是 release gate 必要凭证），但不要求 canary_plan / rollback_condition；项 8 整段砍。

在 1-6 未完成前，不得宣称 evo-agent v1 active。

正式 production 部署阶段（v1.5）按需要重新引入项 7 完整版 + 项 8。

---

# §10 Skill Package Protocol

## §10.1 EvoSkillPackage 目录结构

标准目录：

```text
skill.mbis.<kind>.<scope>.<goal>.v<major>/
  skill.json
  SKILL.md
  plan.yaml
  validation_records.jsonl
  package_manifest.json
```

可选文件：

```text
examples.safe.jsonl
conflicts.json
CHANGELOG.md
```

禁止文件：

```text
eval_truth_report.json
w2_*.json
basis_items.*
projections.parquet
threshold_evaluations.parquet
raw_feedback_notes.*
```

`package_manifest.json` 示例：

```json
{
  "package_schema_version": "1.0.0",
  "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
  "files": {
    "skill.json": "sha256:...",
    "SKILL.md": "sha256:...",
    "plan.yaml": "sha256:...",
    "validation_records.jsonl": "sha256:..."
  },
  "package_sha256": "sha256:..."
}
```

## §10.2 `skill.json` 完整字段表

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `schema_version` | string | 是 | v1 为 `1.0.0` |
| `skill_id` | string | 是 | 无版本后缀 |
| `skill_version_id` | string | 是 | 含版本 |
| `name` | string | 是 | 3-80 chars；不得含实例 id |
| `kind` | enum | 是 | `micro_routing` / `retrieval_macro` / `report_structure` / `diagnostic_hint` |
| `layer` | enum | 是 | L1 为 `L1_operational`；CoreSkill 单独导入 |
| `description` | string | 是 | ≤1024 chars |
| `status` | enum | 是 | 7 态之一 |
| `origin` | enum | 是 | `evo_induced` / `manual_seed` / `spec_revision` |
| `version` | semver | 是 | 不可回退覆盖 |
| `parent_skill_version_id` | string/null | 否 | 可空 |
| `supersedes` | list[string] | 否 | 被替代版本 |
| `scope.rule_families` | list[string] | 否 | 抽象 family |
| `scope.rule_cards` | list[string] | 否 | 稳定 rule_card ids |
| `scope.semantic_slots` | list[string] | 否 | slot ids |
| `scope.measure_keys` | list[string] | 否 | measure keys |
| `scope.artifact_keys` | list[string] | 否 | artifact keys |
| `scope.obligation_kinds` | list[string] | 否 | obligation kinds |
| `trigger_predicate` | object | 是 | DSL |
| `action_plan_ref` | string/null | 否 | `plan.yaml` ref |
| `allowed_tools` | list[string] | 是 | runtime allowlist subset |
| `forbidden_actions` | list[string] | 是 | 必含 5 个 hard forbidden |
| `guardrails` | object | 是 | non-authority, blind, fallback |
| `source_trace_hashes` | list[string] | 是 | candidate+ ≥5 |
| `support_counts.trace_count` | int | 是 | candidate+ ≥5 |
| `support_counts.building_count` | int | 是 | staged+ ≥3 或 world_family≥2 |
| `support_counts.world_family_count` | int | 是 | staged+ ≥2 替代条件 |
| `validation_summary` | object | 是 | gate pass summary |
| `activation_stats` | object | 是 | active 后更新 |
| `kg_snapshot_id` | string | 是 | 验证 snapshot |
| `rulecard_bundle_id` | string | 是 | 绑定 bundle |
| `expires_on_revision` | object | 是 | staleness |
| `created_by` | string | 是 | `evo_trainer` |
| `created_at` | datetime | 是 | UTC |
| `non_authority_statement` | string | 是 | 明确不改 verifier |

示例：

```json
{
  "schema_version": "1.0.0",
  "skill_id": "skill.mbis.retrieval_macro.artifact_evidence_gap",
  "skill_version_id": "skill.mbis.retrieval_macro.artifact_evidence_gap.v1",
  "name": "artifact evidence gap retrieval macro",
  "kind": "retrieval_macro",
  "layer": "L1_operational",
  "description": "Expand artifact and sidecar evidence lookup when reporting or evidence obligations remain open due to missing artifact evidence.",
  "status": "candidate",
  "origin": "evo_induced",
  "version": "1.0.0",
  "parent_skill_version_id": null,
  "supersedes": [],
  "scope": {
    "rule_families": ["mbis.reporting.*"],
    "rule_cards": [],
    "semantic_slots": ["reporting.artifact.submitted", "reporting.artifact.present"],
    "measure_keys": [],
    "artifact_keys": ["report.inspection", "form.mbi3_or_mbi3a"],
    "obligation_kinds": ["artifact", "evidence", "report_field"]
  },
  "trigger_predicate": {
    "all": [
      {"field": "open_reason_code", "op": "in", "value": ["missing_artifact_evidence", "missing_sidecar_entry"]},
      {"field": "obligation_kind", "op": "in", "value": ["artifact", "evidence", "report_field"]}
    ]
  },
  "action_plan_ref": "plan.yaml#artifact_evidence_gap",
  "allowed_tools": ["query_open_obligations", "inspect_obligation", "retrieve_building_facts", "retrieve_applicable_rules"],
  "forbidden_actions": ["override_verifier", "force_allow_stop", "emit_final_verdict", "read_evaluator_truth", "suppress_rule_candidate"],
  "guardrails": {
    "non_authority": true,
    "blind": true,
    "fallback_to_core_on_guard_fail": true
  },
  "source_trace_hashes": ["sha256:aaa", "sha256:bbb", "sha256:ccc", "sha256:ddd", "sha256:eee"],
  "support_counts": {"trace_count": 5, "building_count": 3, "world_family_count": 2},
  "validation_summary": {"gate0": "passed", "gate1": "passed"},
  "activation_stats": {"eligible_count": 0, "activation_count": 0, "median_benefit": null},
  "kg_snapshot_id": "KGS-v1-20260523",
  "rulecard_bundle_id": "rulecard_v2.mbis_cop_2023",
  "expires_on_revision": {"rulecard_bundle_change": true, "verifier_major_change": true},
  "created_by": "evo_trainer",
  "created_at": "2026-05-23T22:30:00Z",
  "non_authority_statement": "This skill only changes retrieval order and evidence lookup. It never determines allow_stop, closure_status, satisfaction_status, or final compliance."
}
```

## §10.3 `SKILL.md` 契约

`SKILL.md` 是 LLM-readable view，必须包含：

```markdown
# <name>

## Purpose
...

## Trigger
...

## Allowed actions
...

## Retrieval / routing plan
...

## Fallback
...

## Safety and authority boundary
This Skill does not decide compliance, does not override the closure verifier, and does not access evaluator-only data.

## Do not
- Do not emit final verdict.
- Do not force allow_stop.
- Do not suppress rule candidates.
- Do not use evaluator truth.
```

`SKILL.md` 不得比 `skill.json` 扩权。若冲突，以 `skill.json` 为准，并 gate fail。

## §10.4 `plan.yaml` DSL

`plan.yaml` 只允许声明检索/路由/报告组织动作。

示例：

```yaml
plan_id: artifact_evidence_gap
version: 1
steps:
  - step_id: inspect_open_obligation
    action: call_tool
    tool: inspect_obligation
    input:
      obligation_id: "{{open_obligation.obligation_id}}"
    save_as: obligation_detail

  - step_id: retrieve_sidecar_artifact_entries
    action: call_tool
    tool: retrieve_building_facts
    input:
      filters:
        carrier_type: sidecar_entry
        artifact_keys: "{{obligation_detail.artifact_keys}}"
        semantic_slots: "{{obligation_detail.slot_ids}}"
    append_candidates: true

  - step_id: retrieve_neighbor_rule_cards
    action: call_tool
    tool: retrieve_applicable_rules
    input:
      rule_families: "{{obligation_detail.source_family_id}}"
      neighbor_expansion: true
    append_candidates: true

fallback:
  on_guard_fail: "disable_skill_for_run"
  on_tool_error: "return_to_core_workflow"
limits:
  max_tool_calls_added: 3
  max_candidates_added: 50
authority:
  can_modify_verifier_inputs: false
  can_remove_candidates: false
  can_set_allow_stop: false
```

Allowed actions：

- `call_tool`
- `append_candidates`
- `reorder_context`
- `add_report_section_hint`
- `emit_diagnostic_hint`

Forbidden actions：

- `remove_candidate`
- `set_allow_stop`
- `set_closure_status`
- `set_satisfaction_status`
- `read_evaluator_truth`
- `write_fact_kg`
- `write_rule_card_kg`
- `emit_final_verdict`

## §10.5 四类 kind 契约

### §10.5.1 `micro_routing`

用途：在已知 trigger 下调整 tool/Skill 顺序。  
必须包含：trigger predicate、priority、allowed tool order。  
不得新增复杂 multi-step retrieval。  
典型收益：减少无效 tool calls、优先深查高频 open reason。

### §10.5.2 `retrieval_macro`

用途：定义可回放的多步检索计划。  
必须包含 `plan.yaml`。  
允许追加 fact/rule candidates。  
不得删除候选。  
典型收益：提高 artifact/slot/measurement evidence coverage。

### §10.5.3 `report_structure`

用途：报告章节、citation grouping、risk item grouping。  
只能在 `allow_stop=true` 或 incomplete notice 模板内组织文本。  
不得改变 closure summary。  
不得写最终裁决。

### §10.5.4 `diagnostic_hint`

用途：解释 open/blocked reason，给人工复核建议模板。  
可引用 closure reason 与 rule/slot/fact refs。  
不得引用 evaluator feedback。  
不得建议“应判 pass/fail”。

## §10.6 生命周期状态机（v1.1 简化为 3 态 + core）

```text
core
draft → active → retired
```

状态定义：

| 状态 | 可见性 | 可加载 runtime | 说明 |
|---|---|---:|---|
| `core` | agent-visible | 是 | Layer 0 CoreSkills（v1.1 与 §10.5 一致，CoreSkills 走 spec revision 修改，不进 evo loop）|
| `draft` | evo-trainer | 否 | 初稿；可少于 5 traces；trainer 仍在迭代 / Gate 未全 pass |
| `active` | agent-visible runtime-safe | 是 | Gate0-4 全 pass + release card pass + conflict resolver pass |
| `retired` | audit only | 否 | 正常淘汰（§9.6.2）或安全 fail 后人工 retire（§9.6.1）|

**v1.1 删除状态**（与 §9.5 Skill promotion / §3.6.4 EvoPolicyVersion status 一致）：
- `candidate`：v1.0 用于 Gate 0/1 pass 后的中间态；v1.1 合并到 draft（trainer 内部状态，不进 spec 状态机）；
- `staged`：v1.0 用于 canary 期；v1.1 无 canary；
- `quarantined`：v1.0 用于安全 fail 后的隔离态；v1.1 实验室阶段直接走 retired + git revert，无需独立隔离态。

状态转换必须写 `SkillValidationRecord` 或 lifecycle event。

**v1.1 注**：原 7 态状态机是 production deployment 假设；v1.1 实验室阶段简化为 3 态符合实际工作流（draft 迭代 → 通过 Gate 全集 → active）。

## §10.7 Naming 规范

`skill_id`：

```text
skill.mbis.<kind>.<scope>.<goal>
```

`skill_version_id`：

```text
skill.mbis.<kind>.<scope>.<goal>.v<major>
```

命名要求：

- lowercase；
- `.` 分层；
- 不含 building/world/run id；
- 不含 verdict/pass/fail/satisfied/violated 结果词；
- scope 用 rule family、slot class、artifact family、open reason taxonomy；
- goal 用 retrieval/routing/report/diagnostic 目标。

合法：

```text
skill.mbis.retrieval_macro.artifact_evidence_gap
skill.mbis.micro_routing.missing_measurement.deep_lookup
skill.mbis.report_structure.open_obligation_citation_grouping
```

非法：

```text
skill.mbis.fail_case.coastal_tower_0012
skill.mbis.expected_verdict.predictor
skill.mbis.force_allow_stop.reporting
```

## §10.8 Quality gate 写作要求

Skill 描述必须回答四问：

1. 何时触发；
2. 做什么；
3. 为什么安全；
4. 何时放弃。

描述长度 ≤1024 chars。`SKILL.md` 总长度建议 ≤2000 words。每个 Skill 必须有 fallback。每个 Skill 必须明确：

```text
This Skill is non-authoritative and cannot decide compliance.
```

## §10.9 Conflict resolution 算法

输入：所有 trigger 命中的 active SkillVersion。  
输出：runtime-safe ordered Skill list。

算法：

```python
def resolve_skill_conflicts(skills):
    groups = group_by_overlapping_scope(skills)
    result = []
    for group in groups:
        sorted_group = sort(
            group,
            key=(validation_score, staleness_freshness, trigger_specificity, created_at),
            descending=True
        )
        top, second = sorted_group[0], sorted_group[1] if len(sorted_group)>1 else None
        if second is None:
            result.append(top)
        elif top.validation_score - second.validation_score >= 0.05:
            result.append(top)
            mark_shadowed(second)
        else:
            union = build_union_retrieval_plan([top, second])
            if union.estimated_tool_calls <= budget.remaining:
                result.append(union)
            else:
                result.append(core_fallback_for_scope(group.scope))
    return result
```

不允许 LLM 根据“哪个 Skill 看起来更对”选择结论。冲突解析只决定检索计划，不决定 status。

## §10.10 Activation stats

active Skill 每次 eligible trigger 更新：

| 字段 | 更新规则 |
|---|---|
| `eligible_count` | trigger predicate match 即 +1 |
| `activation_count` | runtime 实际执行 +1 |
| `fallback_count` | fallback +1 |
| `median_benefit` | 最近 50 次 open+blocked/tool/citation 综合收益 |
| `last_activated_at` | 更新时间 |
| `guard_fail_count` | guard fail +1 |

benefit 计算：

```text
benefit =
  0.5 * normalized_open_blocked_reduction
+ 0.3 * target_coverage_gain
+ 0.2 * tool_cost_saving
- 1.0 * any_regression
```

若 `any_regression=1`，该 activation 计负收益。

## §10.11 SkillPackage 示例目录片段

```markdown
# artifact evidence gap retrieval macro

## Purpose
Use this retrieval macro when artifact or report-field obligations remain open because required artifact evidence was not found in sidecar entries or fact KG.

## Trigger
- open_reason_code is missing_artifact_evidence or missing_sidecar_entry
- obligation kind is artifact, evidence, or report_field
- rule family is in MBIS reporting or submission families

## Allowed actions
- inspect open obligations
- retrieve sidecar artifact entries
- retrieve neighbor rule cards
- append candidates

## Fallback
If any guard fails, disable this Skill for the run and continue with CoreSkills.

## Safety and authority boundary
This Skill only expands retrieval. It does not decide compliance, does not set allow_stop, and does not override the closure verifier.
```



---

# §11 Runtime Scaling Law + Experiment Protocol

## §11.1 论文对接口径

v1 将论文核心定义为：在训练后运行阶段，agent 的能力随 blind-valid experience、validated skill population、replay/evaluation compute、feedback bandwidth 与 rule-skill coverage 增长而改善。训练时 Scaling Law 的资源轴是参数、训练数据与训练 compute；运行时 Scaling Law 的资源轴是：

- `N_valid_runs`：通过 visibility/source/schema audit 的 run 数；
- `N_effective_traces`：按 novelty、coverage、feedback 权重计算的有效经验量；
- `N_active_skills`：active 且未 stale 的 OperationalSkills；
- `N_effective_skills`：最近 50 次 eligible activation 中 median benefit >0 的 active Skill；
- `N_replay_cases`：可用于 gate/training 的 replay cases；
- `C_replay_compute`：离线 replay/gate 计算；
- `C_runtime_tool_budget`：每 run tool/iteration budget；
- `G_rule_skill_coverage`：Rule-Skills KG 对 rule family/slot/obligation kind 的覆盖；
- `B_sanitized_feedback_bandwidth`：满足 k-anonymity 的 feedback cells 数与发布频率。

## §11.2 Effective Trace 定义

一个 trace 是 effective trace，当且仅当：

```python
effective = (
    trace.forbidden_scan_passed
    and trace.source_visibility_audit_passed
    and trace.schema_audit_passed
    and trace.candidate_floor_passed
    and trace.raw_w2_access == False
    and replay_case.eligibility == "eligible"
)
```

effective trace 不等于 raw run。raw run 可失败、泄漏、stale、schema invalid；这些 run 可用于审计，但不能用于学习曲线。

## §11.3 `E_runtime` 公式

v1 定义：

```text
E_runtime = Σ_i validity_i × novelty_i × coverage_weight_i × feedback_available_i
```

其中：

```text
validity_i ∈ {0,1}
novelty_i ∈ [0.2,1.0]
coverage_weight_i ∈ [1.0,3.0]
feedback_available_i ∈ {1.0,1.2}
```

计算细则：

- `validity_i=1`：trace 通过 leakage/source/schema/candidate floor audit；否则 0；
- `novelty_i=1/sqrt(1+n_seen(pattern))`，下限 0.2；
- `pattern=(rule_family, semantic_slot_class, obligation_kind, open_or_blocked_reason)`；
- `coverage_weight_i=1.5` 用于 rare artifact/threshold/high-risk family；`2.0-3.0` 用于极罕见且 release gate 指定的 coverage gap；
- `feedback_available_i=1.2` 当 trace 属于已发布 SanitizedFeedbackPacket 的 aggregate window；否则 1.0。

`E_runtime` 每个 policy release 重新计算，并写入 EvoReleaseCard。

## §11.4 三类指标

### §11.4.1 合规任务质量指标

这些指标由 evaluator private side 计算，只向论文/发布卡输出 aggregate，不进入 agent runtime。

| 指标 | 定义 |
|---|---|
| `verdict_macro_f1` | pass/fail/unknown/not_applicable aggregate F1 |
| `severity_weighted_accuracy` | 高风险 family 权重更高的 aggregate accuracy |
| `family_recall` | agent 报告/closure 覆盖 W2 relevant family 的 aggregate recall |
| `family_precision` | agent 触达 family 中与 reference relevant 对齐的 aggregate precision |
| `slot_requirement_recall` | required semantic slots 被 agent closure 覆盖比例 |
| `threshold_alignment` | operator/value/observed comparator 与 reference aggregate 对齐 |
| `artifact_evidence_alignment` | artifact evidence required/observed aggregate 对齐 |

这些指标绝不 per-run 反写。

### §11.4.2 Closure 质量指标

这些指标由 agent-owned closure artifacts 计算，可细粒度进入 trainer。

| 指标 | 定义 |
|---|---|
| `allow_stop_precision_proxy` | allow_stop=true 时 open/blocked=0 且 guard pass；需 evaluator aggregate 校验 |
| `open_count` | open obligations |
| `blocked_count` | blocked obligations |
| `open_blocked_by_reason` | reason counts |
| `evidence_coverage_rate` | obligations with evidence_fact_ids |
| `candidate_floor_pass_rate` | candidate universe floor pass |
| `closure_non_regression` | compared to previous policy no worsening |
| `schema_contract_pass_rate` | verifier schema pass |

### §11.4.3 Evo 特有指标

| 指标 | 定义 |
|---|---|
| `skill_attributable_delta` | 启用/禁用某 Skill 的 paired delta |
| `evo_gain_vs_static_baseline` | full evo 相对 v0.4 frozen baseline 的 held-out gain |
| `experience_efficiency` | 每 10 effective traces 带来的 metric gain |
| `skill_activation_precision` | eligible activation 中产生正收益比例 |
| `skill_half_life` | Skill 从 active 到 retired 的 median window |
| `policy_version_improvement_rate` | active policy release 中 positive held-out delta 比例 |
| `tool_cost_per_closed_obligation` | tool calls / closed obligations |
| `report_citation_coverage` | report claims with source refs |
| `feedback_blindness_pass_rate` | feedback packets passing blind audits |
| `w2_reconstruction_probe_delta` | probe 相对 prior 的 accuracy delta，必须 ≤5pp |

## §11.5 实验切分

数据生成层固定，W0/W1/W2 不变。实验分层切分：

```text
evolve_train: 60%
gate_validation: 20%
held_out_test: 20%
```

切分约束：

- building disjoint；
- world family stratified；
- rule family coverage balanced；
- rare artifact/threshold boundary 保证 held_out 至少覆盖；
- held_out 不参与 Skill induction 或 policy training；
- evaluator raw W2 只在 private side 使用。

## §11.6 Paired held-out 实验协议

每个 held-out case 至少跑：

1. `static_baseline_v0.4`；
2. `evo_v1_current_policy`；
3. ablation variants。

控制条件：

- same model；
- same KG snapshot；
- same rulecard bundle；
- same verifier version；
- same tool budget；
- same run mode；
- same report guard；
- same evaluator private metric.

默认预算比较：

```yaml
budgets:
  equal_budget: 16
  scaling_budgets: [8, 16, 32]
```

equal_budget 用于证明策略提升；scaling_budgets 用于研究 runtime compute scaling。

## §11.7 Ablation 设计

必须跑以下 ablation：

| variant | 含义 |
|---|---|
| `baseline_static` | v0.4 frozen，无 evo |
| `trace_only` | 记录 trace，不加载 Skill/Policy |
| `policy_only` | 加载 EvoPolicy，不加载 OperationalSkills |
| `skill_only` | 加载 OperationalSkills，使用 baseline policy |
| `feedback_only_policy` | 使用 sanitized feedback 调 policy，不生成 Skill |
| `full_evo` | Replay + Skill + Policy + Feedback |
| `full_evo_no_candidate_floor` | 禁止发布；仅内部验证 candidate floor 必要性，不可作为合法 release |
| `skill_disabled_<id>` | 单 Skill attribution |

`full_evo_no_candidate_floor` 只能在隔离实验中跑，不能进入 production，且结果不得作为 release gain。

## §11.8 学习曲线规范

每个 release point 记录：

```json
{
  "release_id": "ERC-policy.mbis.runtime.default.v1.2.0",
  "E_runtime": 124.6,
  "N_valid_runs": 110,
  "N_effective_traces": 96,
  "N_active_skills": 14,
  "N_effective_skills": 9,
  "C_replay_compute": {"cases": 240, "runs": 480},
  "heldout_metrics": {
    "family_recall": 0.70,
    "slot_requirement_recall": 0.65,
    "blocked_rate": 0.32,
    "report_citation_coverage": 0.91
  },
  "leakage_audit_passed": true,
  "w2_reconstruction_probe_delta": 0.02
}
```

曲线至少包括：

- metric vs raw run count；
- metric vs `E_runtime`；
- cost per closed obligation vs `E_runtime`;
- active/effective skill count vs metric；
- ablation deltas over release versions。

拟合形式可记录：

```text
Error(E) = A × E^-α + β
Cost(E) = C × E^-γ + δ
```

v1 不要求预设 α/γ，但要求记录足够数据以拟合。

## §11.9 Adversarial Reconstruction Audit（v1.1 重定位）

**目标（v1.1 修订）**：证明 trainer 输出的 candidate artifact（candidate SkillPackage、candidate EvoPolicyVersion）**不携带可被 runtime 反推 W2 truth 的信号**。

**v1.1 修订背景**（§0.6 修订 1）：v1.0 把 audit 焦点放在"sanitized packet 是否泄漏 W2"，但 packet 不是危险路径（packet 即使有信号也只暴露给 runtime trend feedback 接口，且 broker 已 rounding 抹平）。真正的危险路径是 trainer 用 raw W2 训出的 candidate artifact 里残留 case-specific signal——artifact 一旦 promote 为 active 就会被 runtime 加载，相当于 runtime 间接看到 W2。v1.1 把 audit 焦点搬到 artifact 端。

流程：

1. 构建 probe dataset：
   - **features**：candidate artifact 的可观测内容（Skill `skill.json` 字段、`SKILL.md` 文本、`plan.yaml` 步骤、EvoPolicyVersion 各 weight/threshold 字段）+ 该 artifact 在 held-out run 上的 activation/影响轨迹；
   - **label**：在 evaluator private side 使用 held-out run 的 W2 expected outcome；
2. 训练简单 probe：logistic regression / tree / small classifier，固定 seed；
3. 比较 `prior_accuracy` 与 `probe_accuracy`；
4. 若 `probe_accuracy - prior_accuracy > 0.05`，**artifact fail**，不能 promote draft → active；
5. fail 后策略：
   - 检查 artifact 文本是否含 forbidden token（应已由 Gate 0 静态扫拦住）；
   - 检查 ranking_weights / candidate_cutoff_policy 是否对某 case-specific 维度赋了异常权重；
   - 重训练 trainer，加更强的 regularization；
   - 减少 trainer 输入的 raw W2 维度（不删 raw 访问，但限制 feature engineering 维度）。

Probe 特征**仍**不可包括 raw W2（probe 是 audit 工具，不是 trainer）。audit 结果只输出 aggregate delta。

**v1.1 删除**：原 §11.9 流程第 6 步"合并 taxonomy、提高 k、增加 delay、减少 metric precision、suppress cells"——这些是 packet 层手段，v1.1 后 audit 不再针对 packet，故无意义。

**v1.1 §11.9 实现现状（2026-05-26 闭环完成）**：v1.1 §11.9 重定位**两步全部落地**：

- **步骤 1（已完成 commit `df70349`）**：spec / docstring / leakage metric 改名（`policy_version_raw_w2_in_training_set` → `policy_artifact_contains_raw_w2`），audit 框架声明"焦点改到 artifact"。
- **步骤 2（已完成 commit 待 push）**：`evo_agent_baseline.evo.audits` 新增 `_extract_artifact_probe_features(artifact, activation_trace)` + `adversarial_reconstruction_audit_artifact(artifact_trace_pairs, ...)` API：
  - artifact 特征提取：SkillPackage / EvoPolicyVersion 内容 token 化（剥 alphanumeric word）+ flatten dict（递归 4 层）+ id/sha/timestamp 黑名单
  - activation trace 特征：rule family counts / open-blocked reason counts / Skill activations / policy version
  - probe：固定 seed logistic regression + per-feature z-score normalization（解决 `experiment_budgets=[8,16,32]` vs `ranking_weights=0.3-1.0` 数值尺度不一致问题）
  - 旧 trace-focused API（`_extract_probe_features` + `adversarial_reconstruction_audit`）保留作向后兼容
- **闭环验证**：`agent_v1/scripts/run_evo_artifact_audit_experiment.py` 跑通——trainer 真训出 candidate policy（含 raw `EvalTruthReport` hash 写入 `trained_on_artifacts`），artifact-端 audit 对干净 candidate `delta=+0.000 / passed=True`；故意 inject `expected_verdict_pass_boost` / `w2_truth_label_match` 等 spec §2.3.3 EvoPolicy 禁止字段后，**audit 拦下 `delta=+0.500 / passed=False`** ← 区分能力实证。

**实验 ⑥ 与实验 ⑧ 的对比**：
- 实验 ⑥（步骤 2 未完成时跑）：focus on packet/trace，delta=0.000 是伪信号
- 实验 ⑧（步骤 2 完成后跑，本节描述的 audit pipeline）：focus on candidate artifact 字段，**delta 真反映 artifact 是否含 W2 信号**（poison sanity 拦下证实）

**未来 polish**（不阻塞 v1.1）：
- 论文级实验：当前 sample 数（10 trace × 5 重复 = 50/50）够小规模 PoC，论文级需要 100+ unique trace + label balance
- 更鲁棒 probe：当前用 zero-dep 极简 logreg，未来可换 sklearn LR / tree-based 在 high-dim 场景更稳
- artifact feature 扩展：当前只覆盖 SkillPackage + EvoPolicyVersion，未来加 `plan.yaml` 步骤序列特征 + `SKILL.md` 文本 n-gram

## §11.10 Counterfactual Swap Audit

目标：证明 broker 输出不对单 case truth 敏感。

流程：

1. 在 evaluator private side 创建两个 synthetic aggregate views；
2. swap W2 labels within same aggregate bucket；
3. rerun broker；
4. 比较 packet text/hash；
5. 若 single-case swap 导致 unsuppressed cell metric 改变超过 0.05 或出现新细粒度 hint，fail。

通过条件：

```python
packet_delta_after_single_case_swap <= 0.05
and no_new_case_specific_dimension
and no_new_free_text_hint
```

## §11.11 Source Independence Audit（v1.1 字段修订）

对每个 release：

- **agent runtime logs 证明未访问 evaluator store**（v1.1 仍生效——runtime 端 blind 红线不动）；
- SkillPackage source traces 均 eligible；
- **artifact 输出不含 raw W2 token**（v1.1 替换原"Policy training input list 不含 raw W2 path"——v1.1 允许 trainer 输入 raw，只约束 trainer 输出）；
- Feedback packets 均 broker-signed（仅当用 runtime trend feedback 接口时；v1.1 trainer 不依赖 broker）；
- report outputs 无 feedback/evaluator references。

**v1.1 删除**：原 "Policy training input list 不含 raw W2 path"。v1.1 trainer credential 已允许读 evaluator_truth_store/raw（§2.5），audit log 字段 `raw_w2_access` 默认值改为 true（§9.11），故本条 audit 改为审 artifact 输出端而非 trainer 输入端。

## §11.12 成功判定（v1.1 release windows → ablation runs）

evo-agent v1.1 比 baseline 强的判定：

```text
full_evo held-out metrics > static_baseline
and closure_non_regression_passed
and leakage_audit_passed
and reconstruction_probe_delta <= 0.05  # v1.1: probe 现在审 artifact，见 §11.9
and candidate_floor_passed
and improvement persists across at least 3 独立 ablation runs（不同 seed / 不同 building split / 不同 trace window）
```

**v1.1 修订**：原 "improvement persists across at least 3 release windows" 是生产 traffic 假设；实验室阶段无连续 release window 概念。改为 "**3 独立 ablation runs**"——实验脚本跑 paired baseline vs evo 时跑至少 3 次（变 seed / 变 building split / 变 trace window 子集），确认 improvement 是稳定的而非偶然采样。

若某次 ablation 提升但其他 ablation 消失，记录为 transient，不计入 scaling curve positive point。

---

# §12 Module Layout + Implementation Conformance

## §12.1 v1 模块

继承 v0.4 §10 代码路径，v1 新增模块建议：

```text
evo_agent/
  contracts.py
  agent/
    orchestrator.py
    hooks.py
    report_writer.py
    skill_runtime.py
    policy_runtime.py
  closure/
    verifier.py
  kg/
    fact_loader.py
    rulecard_loader.py
    skill_graph_loader.py
  evo/
    trace_capture.py
    replay_buffer.py
    feedback_broker.py
    skill_package_loader.py
    skill_induction.py
    skill_validation.py
    policy_trainer.py
    release_manager.py
    rollback.py
    audits.py
  eval/
    evaluator.py
    truth_store.py
  experiments/
    paired_runner.py
    ablations.py
    scaling_law.py
```

## §12.2 code follows spec

工程实现必须遵守：

- DTO 字段以 Appendix B 为准；
- forbidden list 以 Appendix A 为准；
- gate 数字以 §9/§10 为准；
- candidate floor 不得关闭；
- runtime default tool iteration ceiling =16；
- experiment budgets = [8,16,32]；
- k-anonymity = ≥10 runs and ≥3 buildings；
- metric rounding = 0.05。

代码中若出现未授权字段，必须先修 spec，再落 code。不得以“代码已实现”为理由修改 spec 约束。

## §12.3 配置文件建议

```yaml
runtime:
  default_policy_version: policy.mbis.runtime.default.v1.0.0
  max_tool_iterations: 16
  allow_operational_skills: true
  allow_layer2_metaskills: false

evo:
  min_source_traces_for_candidate: 5
  min_support_buildings: 3
  min_support_world_families: 2
  feedback_batch_min_runs: 10
  feedback_cell_min_runs: 10
  feedback_cell_min_buildings: 3
  metric_rounding: 0.05
  stability_k: 5
```

---

# §13 Acceptance Tests + Security Tests + Release Gates

## §13.1 继承 v0.4 测试

继承 v0.4 §11：

- safe ingestion；
- building assessment run；
- evaluator blind scoring；
- deterministic repeatability；
- report guard；
- closure verifier unit tests。

v1 所有新增测试必须在这些 baseline 测试通过后执行。

## §13.2 Evo 专属验收测试

### §13.2.1 Skill gate test

输入一个合法 SkillPackage 和多个非法 SkillPackage。必须验证：

- 合法 Skill 通过 Gate 0/1；
- 含 W2 字段的 Skill fail；
- 含 building_id literal 的 Skill fail；
- 含 `force allow_stop` 的 Skill fail；
- 缺 source traces 的 candidate fail；
- 缺 plan.yaml 的 retrieval_macro fail；
- status active 但缺 Gate 2-4 record fail。

### §13.2.2 Feedback broker test

构造 raw EvalTruthReport fixture，验证：

- batch <10 不发布；
- cell buildings <3 suppress；
- metric rounding 到 0.05；
- run_id/building_id 被移除；
- raw basis text 不出现；
- release delay <1 fail；
- reconstruction probe delta >5pp fail。

### §13.2.3 W2 reconstruction audit test

给定 sanitized feedback 与 trace features，probe accuracy delta 必须 ≤0.05。测试必须包含一个故意泄漏 per-run label 的 bad packet，确保 audit 能 fail。

### §13.2.4 Candidate floor violation test（v1.1 改名 + 重写）

**v1.1 修订**（§0.6 修订 2）：v1.0 原名 "Policy rollback test"，依赖 canary / rollback artifact / `rolled_back` / `quarantined` 状态，全部已删（见 §0.6.1 映射规则）。实验室阶段 active 出 fail 走 git revert 不走运行时 rollback 流程。本测试改为单点验证 candidate floor violation 拦截能力。

发布 candidate policy，注入 candidate floor violation，验证：

- `pre_policy_publish_guard` fail；
- active policy 未替换（保留旧 active，不发生 promotion）；
- failed candidate status 不进 active（保持 draft 或人工 retire；v1.1 不再产 `rolled_back` / `quarantined` artifact）。

### §13.2.5 Candidate universe floor test

构造 base retrieval 10 张 rule_card、Skill 增加 3 张、Policy context top_k 只选 5 张。verifier universe 必须包含 base 10 + added 3 + neighbor expansion minus deterministic exclusions。若少于此集合，closure fail。

### §13.2.6 Report skill disclosure test

报告必须显示 Skill 非权威 disclosure；不得显示 feedback metric、expected verdict、basis item。含“最终裁决”断言的输出必须被拦截；“非最终裁决”免责声明允许。

## §13.3 Release gate 流程（v1.1 简化为 8 步）

**v1.1 修订**（§0.6 修订 2）：v1.0 第 8 步 "rollback target exists" + 第 9 步 "canary plan exists" 依赖已删的 canary/rollback 概念。实验室阶段 active 出 fail 走 git revert（不要求 release 前预声明 rollback target），无灰度部署（不要求 canary plan）。

发布 active artifact 前必须完成：

```text
1. schema validation pass
2. forbidden scan pass
3. Gate 0-4 pass
4. held-out paired eval pass
5. reconstruction audit pass（v1.1 §11.9 改 audit artifact）
6. candidate floor audit pass
7. release card generated
8. post_evo_writeback_audit pass
```

任何一步 fail，不得 active。

## §13.4 Definition of Done v1（v1.1 删 rollback）

**v1.1 修订**（§0.6 修订 2）：v1.0 列 "能 rollback" 作为 DoD 一项，依赖 §9.9 rollback 章节已删。实验室阶段用 git revert 代替，不作为工程 DoD 检查项。

v1 工程完成标准：

- 能从 v0.4 baseline artifacts 生成 EvoRunTrace；
- 能发布至少一个 active retrieval_macro Skill；
- 能发布一个 active EvoPolicyVersion；
- 能通过 feedback broker 生成 sanitized packet；
- 能跑 paired baseline vs evo held-out；
- 能生成 release card；
- 所有 blind/security tests pass；
- report 始终副驾驶定位；
- closure verifier deterministic repeatability pass。

---

# Appendix A Forbidden Labels/Properties/Files/Phrases v1

## A.1 禁止 labels

继承 v0.4 Appendix A，新增：

```text
EvalTruthReport
RawEvalTruth
W2Truth
W2BasisItem
W2ThresholdTruth
ExpectedOutcome
ReferenceVerdict
ProjectionAnswer
RawFeedback
PerRunConfusion
```

v0.4 已禁 labels 继续有效：

```text
NormativeProjection
ProjectionFamilyEval
ThresholdEval
ReportBasisItem
ExpectedVerdict
EvalProjection
EvalTruth
```

## A.2 禁止 properties

```text
expected_verdict
selected_family
projection_status
basis_items
unknown_reason_code
regime_tag
pass_bool
projection_id
projection_registry_id
projection_family
projection_version
required_world_core_slots
required_measurement_slots
required_qualifier_slots
required_sidecar_interfaces
matched_component_refs
matched_measurement_ids
coverage_status
raw_projection_ref_hash
projection_ref_hash
truth_label
expected_label
reference_outcome
w2_basis_ref
basis_item_id
projection_cell_id
per_run_confusion
raw_metric_by_run
w2_threshold_truth
w2_observed_value
feedback_truth_comment
```

## A.3 禁止 files

```text
normative_projection_meta.parquet
projections.parquet
matched_families.parquet
threshold_evaluations.parquet
coverage_control_metadata.parquet
basis_items.parquet
eval_truth_report.json
raw_eval_truth.json
raw_feedback_notes.json
w2_*.json
```

## A.4 禁止 phrases

```text
最终裁决
最终合规
最终不合规
结案
本建筑已合规
本建筑不合规
according to expected_verdict
based on NormativeProjection
force allow_stop
override verifier
expected verdict says
W2 says
```

否定式免责声明允许，例如“非最终裁决”“不构成最终合规裁决”。

## A.5 废止术语禁止进入概念模型

以下名称只作为 legacy 禁止清单保留，不得作为 v1 对象、节点、模块或章节语义：

```text
巡检员模拟
HiddenGold
latent case
observation 主链
QueryEpisode
```

---

# Appendix B DTO Schemas

## B.1 Canonical JSON 口径

所有 DTO canonical serialization：

```yaml
encoding: utf-8
object_key_order: unicode_codepoint_ascending
datetime: utc_iso8601_seconds
float_precision: 6
drop_null_unless_required: true
list_order:
  semantic_order_lists: preserve
  set_semantic_lists: sort_ascending
hash: sha256_hex_lowercase
```

DTO 不允许额外字段；实现中 Pydantic/TypeScript/Rust schema 均应设置 `extra=forbid` 或等价策略。

## B.2 EvoRunTrace DTO

```python
class EvoRunTrace(BaseModel):
    trace_id: str
    run_id: str
    world_id_hash: str
    building_id_hash: str
    kg_snapshot_id: str
    rulecard_bundle_id: str
    agent_version: str
    verifier_version: str
    evo_policy_version_id: str
    active_skill_set_id: str
    active_skill_version_ids: List[str]
    input_guard_hash: str
    retrieval_summary: Dict[str, Any]
    candidate_universe_hash: str
    fact_pack_hash: str
    rule_slice_hash: str
    closure_result_ref: str
    closure_summary: Dict[str, Any]
    report_ref: Optional[str]
    hook_results_hash: str
    tool_call_count: int
    llm_iterations_used: int
    cost: Dict[str, Any]
    fallback_reason: Optional[str]
    steps: List[EvoRunStep]
    sanitized_feedback_refs: List[str]
    trace_visibility: Literal["agent_visible_trace"]
    forbidden_scan_passed: bool
    source_visibility_audit_passed: bool
    schema_audit_passed: bool
    candidate_floor_passed: bool
    created_at: str
```

字段约束：

| 字段 | 约束 |
|---|---|
| `trace_id` | `ERT-<run_id>-<hash>` |
| `world_id_hash` / `building_id_hash` | trainer 默认只读 hash |
| `llm_iterations_used` | ≤ policy max，production default ≤16 |
| `forbidden_scan_passed` | false 时不得进入 Replay Buffer |
| `steps` | 按 seq 升序 |

`EvoRunStep`：

```python
class EvoRunStep(BaseModel):
    step_id: str
    trace_id: str
    seq: int
    stage: Literal[
        "input_guard",
        "fact_retrieval",
        "rule_retrieval",
        "skill_activation",
        "closure_verification",
        "deep_lookup",
        "report_generation",
        "guard"
    ]
    tool_name: Optional[str]
    tool_input_hash: Optional[str]
    tool_output_summary_hash: Optional[str]
    selected_skill_ids: List[str]
    policy_decision_ref: Optional[str]
    candidate_set_hash: Optional[str]
    guard_results: Dict[str, Any]
    created_at: str
```

示例：

```json
{
  "trace_id": "ERT-CAR-20260523T182806-0776a1ce-a1b2",
  "run_id": "CAR-20260523T182806-0776a1ce",
  "world_id_hash": "sha256:...",
  "building_id_hash": "sha256:...",
  "kg_snapshot_id": "KGS-v1-20260523",
  "rulecard_bundle_id": "rulecard_v2.mbis_cop_2023",
  "agent_version": "evo_agent_v1.0",
  "verifier_version": "closure_v1.0",
  "evo_policy_version_id": "policy.mbis.runtime.default.v1.0.0",
  "active_skill_set_id": "SS-policy.mbis.runtime.default.v1.0.0-a9",
  "active_skill_version_ids": ["skill.mbis.retrieval_macro.artifact_evidence_gap.v1"],
  "input_guard_hash": "sha256:...",
  "retrieval_summary": {"fact_count": 515, "candidate_rule_card_count": 129},
  "candidate_universe_hash": "sha256:...",
  "fact_pack_hash": "sha256:...",
  "rule_slice_hash": "sha256:...",
  "closure_result_ref": "runs/CAR-.../closure_validation_result.json",
  "closure_summary": {"open_count": 13, "blocked_count": 810},
  "report_ref": "runs/CAR-.../llm_incomplete_closure_notice.md",
  "hook_results_hash": "sha256:...",
  "tool_call_count": 10,
  "llm_iterations_used": 6,
  "cost": {"wall_ms": 120000, "tool_calls": 10},
  "fallback_reason": null,
  "steps": [],
  "sanitized_feedback_refs": [],
  "trace_visibility": "agent_visible_trace",
  "forbidden_scan_passed": true,
  "source_visibility_audit_passed": true,
  "schema_audit_passed": true,
  "candidate_floor_passed": true,
  "created_at": "2026-05-23T20:00:00Z"
}
```

## B.3 EvoSkillPackage DTO

```python
class EvoSkillPackage(BaseModel):
    package_schema_version: Literal["1.0.0"]
    package_uri: str
    package_sha256: str
    skill: SkillJson
    skill_md_sha256: str
    plan_yaml_sha256: Optional[str]
    validation_records_sha256: str
    manifest_sha256: str
```

`SkillJson`：

```python
class SkillJson(BaseModel):
    schema_version: Literal["1.0.0"]
    skill_id: str
    skill_version_id: str
    name: str
    kind: Literal["micro_routing","retrieval_macro","report_structure","diagnostic_hint"]
    layer: Literal["L1_operational"]
    description: str
    status: Literal["draft","candidate","staged","active","quarantined","retired"]
    origin: Literal["evo_induced","manual_seed","spec_revision"]
    version: str
    parent_skill_version_id: Optional[str]
    supersedes: List[str]
    scope: SkillScope
    trigger_predicate: Dict[str, Any]
    action_plan_ref: Optional[str]
    allowed_tools: List[str]
    forbidden_actions: List[str]
    guardrails: Dict[str, Any]
    source_trace_hashes: List[str]
    support_counts: Dict[str, int]
    validation_summary: Dict[str, Any]
    activation_stats: Dict[str, Any]
    kg_snapshot_id: str
    rulecard_bundle_id: str
    expires_on_revision: Dict[str, bool]
    created_by: str
    created_at: str
    non_authority_statement: str
```

`SkillScope`：

```python
class SkillScope(BaseModel):
    rule_families: List[str] = []
    rule_cards: List[str] = []
    semantic_slots: List[str] = []
    measure_keys: List[str] = []
    artifact_keys: List[str] = []
    obligation_kinds: List[str] = []
```

Validation rules：

- `description` ≤1024 chars；
- candidate/staged/active: `len(source_trace_hashes)>=5`；
- staged/active: `support_counts["building_count"]>=3 or support_counts["world_family_count"]>=2`；
- active: `validation_summary.gate0..gate4 == "passed"`；
- `forbidden_actions` contains hard five；
- no extra fields.

## B.4 EvoPolicyVersion DTO

```python
class EvoPolicyVersion(BaseModel):
    policy_version_id: str
    policy_id: str
    version: str
    status: Literal["draft","candidate","staged","active","rolled_back","retired"]
    ranking_weights: Dict[str, float]
    tool_preferences: Dict[str, Any]
    skill_activation_order: Dict[str, Any]
    open_obligation_priority: Dict[str, Any]
    candidate_cutoff_policy: Dict[str, Any]
    report_template_policy: Dict[str, Any]
    fallback_thresholds: Dict[str, Any]
    max_tool_iterations_default: int
    experiment_budgets: List[int]
    trained_on_replay_set_id: str
    trained_on_feedback_packet_ids: List[str]
    validation_summary: Dict[str, Any]
    previous_active_version_id: Optional[str]
    rollback_condition: Dict[str, Any]
    created_at: str
    activated_at: Optional[str]
```

Constraints:

- `max_tool_iterations_default=16` for production unless spec revision；
- `experiment_budgets=[8,16,32]`；
- ranking weights between -2.0 and 2.0；
- candidate floor enabled；
- no `allow_stop_policy` field；
- no per-run reward.

Example:

```json
{
  "policy_version_id": "policy.mbis.runtime.default.v1.0.0",
  "policy_id": "policy.mbis.runtime.default",
  "version": "1.0.0",
  "status": "active",
  "ranking_weights": {
    "base_fulltext_score": 1.0,
    "graph_neighbor_boost": 0.35,
    "skill_trigger_boost": 0.30,
    "open_reason_priority_boost": 0.25,
    "artifact_slot_match_boost": 0.20,
    "recent_policy_success_boost": 0.15,
    "stale_or_guard_penalty": -1.0
  },
  "tool_preferences": {"deep_lookup_after_open": true},
  "skill_activation_order": {"resolver": "validation_score_then_specificity"},
  "open_obligation_priority": {"missing_artifact_evidence": 0.9, "missing_measurement": 0.8},
  "candidate_cutoff_policy": {
    "context_top_k": 80,
    "verifier_floor": "all_score_positive_not_deterministically_excluded"
  },
  "report_template_policy": {"default": "mbis_auxiliary_report_v1"},
  "fallback_thresholds": {"max_added_tool_calls_per_skill": 3},
  "max_tool_iterations_default": 16,
  "experiment_budgets": [8, 16, 32],
  "trained_on_replay_set_id": "RS-evolve-train-20260523",
  "trained_on_feedback_packet_ids": ["SFP-EW-20260523-001"],
  "validation_summary": {
    "leakage_audit_passed": true,
    "closure_non_regression_passed": true,
    "candidate_floor_passed": true
  },
  "previous_active_version_id": null,
  "rollback_condition": {"leakage_fail": "any", "closure_regression": "any"},
  "created_at": "2026-05-23T20:00:00Z",
  "activated_at": "2026-05-23T20:30:00Z"
}
```

## B.5 SanitizedFeedbackPacket DTO

```python
class SanitizedFeedbackPacket(BaseModel):
    feedback_packet_id: str
    eval_window_id: str
    source_eval_truth_report_hash: str
    aggregation_level: Literal[
        "batch_rule_family",
        "batch_slot_class",
        "batch_obligation_kind",
        "batch_error_taxonomy"
    ]
    run_count: int
    building_count: int
    cell_count: int
    rounding_policy: Literal["nearest_0.05","bucket_low_medium_high"]
    release_delay_window_count: int
    cells: List[FeedbackCell]
    forbidden_scan_passed: bool
    k_anonymity_passed: bool
    reconstruction_audit_passed: bool
    created_at: str
    released_at: str
```

`FeedbackCell`：

```python
class FeedbackCell(BaseModel):
    feedback_cell_id: str
    feedback_packet_id: str
    dimension: Dict[str, str]
    metric_name: str
    metric_bucket: str
    delta_bucket: Optional[str]
    run_count: int
    building_count: int
    suppressed: bool
    suppression_reason: Optional[str]
    suggested_evo_action: Optional[Literal[
        "skill_induction_candidate",
        "policy_weight_adjustment",
        "report_guard_attention",
        "none"
    ]]
```

Constraints:

- packet `run_count>=10`；
- packet `building_count>=3`；
- unsuppressed cell `run_count>=10 and building_count>=3`；
- no raw ids；
- no free text evaluator comments；
- metric bucket rounded 0.05 or enum.

## B.6 SkillValidationRecord DTO

```python
class SkillValidationRecord(BaseModel):
    validation_id: str
    skill_version_id: str
    validation_stage: Literal[
        "gate0_static",
        "gate1_schema_provenance",
        "gate2_replay_ab",
        "gate3_stability",
        "gate4_holdout_counterfactual",
        "release_gate"
    ]
    eval_set_id: str
    eval_set_hash: str
    run_count: int
    building_count: int
    world_family_count: int
    metric_name: str
    metric_value_bucket: str
    metric_delta_bucket: Optional[str]
    confidence_bucket: Optional[Literal["low","medium","high"]]
    passed: bool
    failure_reasons: List[str]
    leakage_hits: List[str]
    closure_regression_count: int
    allow_stop_authority_check: bool
    validator_version: str
    created_at: str
```

Constraints:

- active requires all gate records passed；
- leakage_hits must be empty；
- closure_regression_count=0；
- notes/free_text fields not allowed。

## B.7 EvoMemoryStore DTO

`EvoMemoryStore` 是逻辑 store 配置 DTO：

```python
class EvoMemoryStoreConfig(BaseModel):
    store_id: str
    backend: Literal["neo4j","duckdb","filesystem","postgres"]
    visibility: Literal["evo_trainer_visible"]
    contains: List[Literal[
        "EvoRunTrace",
        "ReplayCase",
        "EvoPolicyVersion",
        "EvoSkillPackageMetadata",
        "SkillValidationRecord",
        "SanitizedFeedbackPacket",
        "EvoReleaseCard"
    ]]
    forbidden_labels: List[str]
    forbidden_properties: List[str]
    write_audit_required: bool
    runtime_agent_direct_read: bool
    evaluator_raw_truth_read: bool
```

Default:

```json
{
  "store_id": "evo_memory_store_v1",
  "backend": "neo4j",
  "visibility": "evo_trainer_visible",
  "contains": [
    "EvoRunTrace",
    "ReplayCase",
    "EvoPolicyVersion",
    "EvoSkillPackageMetadata",
    "SkillValidationRecord",
    "SanitizedFeedbackPacket",
    "EvoReleaseCard"
  ],
  "forbidden_labels": ["EvalTruthReport", "NormativeProjection", "ExpectedVerdict"],
  "forbidden_properties": ["expected_verdict", "basis_items", "projection_id"],
  "write_audit_required": true,
  "runtime_agent_direct_read": false,
  "evaluator_raw_truth_read": false
}
```

## B.8 ReleaseCard DTO

```python
class EvoReleaseCard(BaseModel):
    release_card_id: str
    artifact_type: Literal["skill","policy","skill_set"]
    artifact_version_id: str
    effective_trace_count: float
    n_valid_runs: int
    n_effective_traces: int
    n_active_skills: int
    n_effective_skills: int
    heldout_metric_summary: Dict[str, Any]
    ablation_delta: Dict[str, Any]
    leakage_audit_passed: bool
    reconstruction_audit_passed: bool
    closure_non_regression_passed: bool
    candidate_floor_passed: bool
    rollback_condition: Dict[str, Any]
    canary_plan: Dict[str, Any]
    created_at: str
```

---

# Appendix C Baseline Compatibility + Migration Plan

## C.1 v0.4 直接继承

直接继承：

- v0.4 §1.0 原则；
- v0.4 §2 agent/evaluator 隔离；
- v0.4 §3 Fact KG 与 RuleCard KG；
- v0.4 §4 fact/rule/regulation loader；
- v0.4 §5 KG-RAG 基本流程；
- v0.4 §6 deterministic closure verifier；
- v0.4 §7 CoreSkills 与 report guard；
- v0.4 §8 evaluator 独立阅卷指标；
- v0.4 Appendix A forbidden baseline list。

## C.2 字段扩展

`ComplianceAssessmentRun` 新增：

```text
evo_policy_version_id
active_skill_set_id
active_skill_version_ids
trace_ref
skill_invocation_summary
tool_budget_policy
fallback_reason
llm_iteration_ceiling
runtime_mode
feedback_batch_ref
candidate_universe_hash
fact_pack_hash
rule_slice_hash
```

`ClosureValidationResult` 新增 instrumentation：

```text
candidate_universe_hash
fact_pack_hash
rule_slice_hash
skill_invocation_ids
skill_augmented_retrieval_used
policy_version_id
verifier_authority_check
```

`Skill` 从 v0.4 预留 schema 扩展为 `Skill` + `SkillVersion` + `SkillTrigger` + `SkillActivation` + `SkillValidationRecord` + `SkillSet`。

## C.3 重命名与 deprecate

- v0.4 `manual_seed/candidate/validated/retired` 迁移为 v1 7 态；`validated` 拆为 `staged/active`；
- v0.4 `allowed_in_baseline` 对 CoreSkill 固定 true，对 OperationalSkill 删除，改用 `status=active`；
- v0.4 Skill `content_md` 不再是权威源，迁移为 SkillPackage `SKILL.md` rendering；
- v0.4 §9 “为 evo 预留的接口”废止为预留章节，升级为 v1 §9/§10 正式机制。

## C.4 迁移 checklist

1. 从 v0.4 baseline artifacts 生成初始 `ComplianceAssessmentRunV1`；
2. 生成 bootstrap `EvoPolicyVersion policy.mbis.runtime.default.v1.0.0`；
3. 将 4 个 seed Skill 迁移为 Layer 0 CoreSkills，status=`core`；
4. 建立 Rule-Skills KG constraints/indexes；
5. 建立 EvoMemoryStore；
6. 实现 trace capture 并对 baseline run 回填 `EvoRunTrace`；
7. 实现 SkillPackageLoader 与 Gate 0/1；
8. 实现 replay runner 与 Gate 2-4；
9. 实现 EvoFeedbackBroker；
10. 实现 PolicyTrainer 与 ReleaseManager；
11. 实现 rollback；
12. 跑 §13 acceptance tests；
13. 生成第一张 EvoReleaseCard；
14. 只在 release gate 全过后启用 active OperationalSkills。

## C.5 Bootstrap policy

Bootstrap policy 代表“v1 runtime 但尚未学习”的初始状态：

```yaml
policy_version_id: policy.mbis.runtime.default.v1.0.0
status: active
operational_skills_enabled: false
core_skills_enabled: true
candidate_floor: enabled
max_tool_iterations_default: 16
ranking_weights:
  base_fulltext_score: 1.0
  graph_neighbor_boost: 0.35
  skill_trigger_boost: 0.0
```

当第一个 OperationalSkill 通过 gate 后，发布 `policy.mbis.runtime.default.v1.1.0`，开启对应 SkillSet。

## C.6 迁移验收

迁移完成必须证明：

- v0.4 baseline run 在 v1 bootstrap policy 下 closure result 不回退；
- no W2 fields in agent KG / EvoMemoryStore；
- 4 CoreSkills 可加载；
- active policy 可加载；
- trace 可写；
- evaluator raw report 不反写；
- report 仍为辅助审查报告；
- all v0.4 tests + v1 tests pass。

---

# End of evo-agent v1 spec
