# 架构导航：`evo_agent_baseline`

> 本文是**人工**架构导航，补在自动 API 参考之上。逐函数签名 / docstring / pydantic 字段表见自动参考：
> [`evo_agent_baseline.md`](./evo_agent_baseline.md)（由 `scripts/gen_api_docs.py` AST 抽取，重跑见该文件抬头）。
>
> 设计背景（本文不复述规格，只导航）：
> - baseline 总规格：`团队文档/我的笔记/蓝图汇总/evo-agent_baseline_设计规格_v0.4.md`
> - evo v1 总规格：`团队文档/我的笔记/蓝图汇总/evo-agent_v1_设计规格.md`
> - W2 法规映射层规格包：`团队文档/我的笔记/蓝图汇总/W2法规映射层全量实现级设计规格包/`
>
> 读完本文你应当知道：这个包在四层架构里干嘛、入口在哪、典型调用怎么串、哪些是稳定对外面、哪些坑别踩。

---

## 1. 一句话定位

`evo_agent_baseline` 是 evo-agent 四层架构里**「认知层 + 底线层 + 进化层」的代码实体**：它实现了香港 MBIS 场景下的**合规助手代理（compliance assistant agent）运行时**——
LLM 当大脑做工具编排与自然语言报告，但**所有合规判定（`allow_stop` / `closure_status` / `satisfaction_status`）由确定性闭包验证器锁死，LLM 不可改**；
外加一套独立的**评测闭环**（读 W2 参考真值离线阅卷）和一套**进化层**（trace 捕获 → replay → 技能归纳 / 策略训练 → 五道 Gate 发布）。

放进四层架构看：

| 四层架构 | 本包对应 |
|---------|---------|
| 感知层（数据/世界生成 W0/W1） | **不在本包**（在 `workflow_engine` / worldgen） |
| 认知层（LLM 大脑 + 双源 KG-RAG） | `agent/` + `retrieval/` + `kg/` + `ingest/` |
| 底线层（确定性闭包验证 + blind 红线 hook） | `closure/` + `agent/hooks.py` |
| 进化层（自进化：trace→replay→技能/策略→发布） | `evo/` + `experiments/` |
| 评测（旁路，读 W2 真值阅卷，**agent runtime 不得 import**） | `eval/` |

跨层共享契约统一定义在 `contracts.py`（唯一 DTO 中心）。

---

## 2. 子包 / 核心模块职责表

| 子包 / 模块 | 职责（一行） |
|------------|------------|
| `contracts.py` | **唯一公开 DTO / enum 中心**：`FactPack` / `RuleSlice` / `Obligation` / `ClosureValidationResult` / `ComplianceAssessmentRun` + evo 侧 `EvoRunTrace` / `SkillJson` / `EvoPolicyVersion` 等。字段名 / 类型 / 默认值是跨模块稳定契约。 |
| `ingest/` | 各路灌库器：W0/W1 parquet→事实 KG、sidecar、法规原文 markdown、rule_card v2、4 个 seed Skill；含 loader 守卫 `guard.py` + Cypher schema。 |
| `ingest/_common.py`、`ingest/_graphspec.py` | 内部支撑：parquet 读取 / 值规整 / ID 工具；`NodeSpec`/`EdgeSpec`/`GraphBatch` + MERGE Cypher 生成（无对应单一规格章节）。 |
| `kg/` | Neo4j 连接客户端（读 `config/kg.yaml`）+ `canonical_json` + `queries.py`（检索 Cypher 语句库）。 |
| `retrieval/` | 双源 KG-RAG 检索：`fact_retriever`（建筑事实→`FactPack`）、`rule_retriever`（候选 rule_card 打分排序→`RuleSlice`）、`pack_builder`（扁平子图还原 DTO + 组装两个 pack）。 |
| `closure/` | **确定性闭包验证器**（底线层核心）：纯 DTO 入、纯 Python、无 LLM、无 Neo4j。`validator` 主入口 + `applicability`/`fact_binding`/`threshold_eval`/`obligation_deriver` 子算子。 |
| `agent/` | agent 三层控制体系：`run_orchestrator`（11 步编排）、`llm_orchestrator`（LLM tool-use 主循环）、`llm_client`（OpenAI 兼容封装）、`hooks`（5 个 hard blind 守卫）、`report_writer`（确定性报告渲染）、`policy_runtime`/`skill_runtime`（evo runtime 应用面）。 |
| `eval/` | **evaluator-only 评测闭环**：`truth_loader`（读 W2 真值）、`mapper`（agent verdict→family + fine→coarse crosswalk）、`metrics`（verdict/coverage/threshold/closure 四组指标）、`leakage_audit`（答案泄漏审计）、`report`（离线评测报告）。**agent runtime 不得 import 本子包。** |
| `evo/` | 进化层：`trace_capture`（捕获 `EvoRunTrace`）、`replay_buffer`（ReplayCase 容器 + eligibility）、`skill_induction`（模式→draft SkillPackage）、`policy_trainer`（trace→draft policy）、`skill_validation`（技能验证记录）、`skill_package`/`skill_package_loader`（SkillPackage 读写 + sha256 + 灌库）、`feedback_broker`（raw 真值→sanitized packet，v1.1 已降级为可选 runtime trend 接口）、`audits`（reconstruction probe / counterfactual swap / 11 项 leakage 复合审计）。 |
| `experiments/` | 实验协议：`paired_runner`（paired held-out + 数据集分层切分）、`ablations`（5 个核心消融 variant）、`scaling_law`（运行时 Scaling Law 6 个指标 + 误差曲线拟合）、`run_registry`/`ExperimentRun`（实验归档）。 |
| `config/` | 运行配置 yaml（`kg` / `guard` / `evaluator`）；无逻辑代码，各模块按需读。 |
| `tests/`、各子包 `tests/` | 单元测试。 |

---

## 3. 关键入口与典型数据流

### 3.1 一次合规评估（认知层 + 底线层主链）

对外最稳的高层入口是 `agent.run_orchestrator.RunOrchestrator`。它把一次建筑评估串成规格的 11 步，**检索与闭包通过依赖注入**（callable）传入，便于单测换 mock、真实集成换真实子模块。

数据流（确定性模式，`llm_mode=False`）：

```
RunOrchestrator.run(world_id, building_id)
  └─ pre_run_input_guard            (hooks，hard：缺字段/W2 路径/求最终裁决 → 拦)
  └─ retrieval_fn(world_id, building_id, run_id)
        ├─ retrieve_fact_pack(client, run_id, building_id)        → FactPack
        └─ retrieve_rule_slice(client, run_id, fact_pack, bundle) → RuleSlice
  └─ post_retrieval_source_audit(fact_pack, rule_slice)  (hard：DTO 不得含 W2 字段)
  └─ closure_fn(rule_slice, fact_pack, config)
        = validate_building_closure(...)                  → ClosureValidationResult
  └─ post_verifier_stop_gate                              (hard：allow_stop 锁死，LLM/编排都不能改)
  └─ report_writer.write_report(result)
        allow_stop=True  → auxiliary_review_report.md
        allow_stop=False → incomplete_closure_notice.md
  └─ pre_output_language_guard                            (hard：禁「最终不合规」等话术)
  └─ persist run artifacts → ComplianceAssessmentRun
```

`FactPack`（事实包，含三个倒排索引 slot/measure/carrier）+ `RuleSlice`（规则切片，保留 rule_card v2 原嵌套 + registry 子 DTO）是闭包验证器的**唯一输入**。验证器内部生成顺序固定：applicability → triggers → slot roles → thresholds → obligation graph → evidence → exceptions → definitions → sort/dedupe，产出 `Obligation` 集合 + `ClosureSummary` + **唯一权威的 `allow_stop`**。

便捷适配器 `retrieval.make_retrieval_fn(client, rulecard_bundle_id)` 把 DATA 侧的两个检索函数闭包成编排器期望的 `RetrievalFn = (world_id, building_id, run_id) -> (FactPack, RuleSlice)`。

### 3.2 LLM-as-brain 模式

`llm_mode=True` 时，编排器把检索/闭包/报告交给 `agent.llm_orchestrator.run_llm_orchestration` 的 LLM tool-use 主循环驱动（5 个工具：`retrieve_building_facts` / `retrieve_applicable_rules` / `run_closure_verification` / `query_open_obligations` / `finalize_report`）。
**关键不变量**：LLM 只控制工具调度顺序 + 写报告；`allow_stop` 仍由 deterministic verifier 决定；即使 LLM 拒绝调闭包，编排器在 finalize 前会强制跑一次 verifier。每次 tool 返回过 `post_retrieval_source_audit`，最终报告过 `pre_output_language_guard`。

### 3.3 评测闭环（旁路，读 W2 真值）

```
eval.report.evaluate_run(EvalInputs)
  ├─ load_truth_bundle(...)                  → TruthBundle（W2 NormativeProjection / expected_verdict）
  ├─ aggregate_agent_family_verdicts(...)    → AgentFamilyVerdict（经 fine→coarse crosswalk）
  ├─ compute_verdict / coverage / threshold / closure_metrics(...)
  └─ audit_leakage(...)                      → 答案泄漏审计
  → write_eval_report(...)  spec §8.5 评测 JSON
```

`compute_coverage_metrics(agent_verdicts, obligations, retrieved_rule_card_ids, truth)` 等四个 `compute_*_metrics` 是评测主算子。**`agent` runtime 与 `eval` 子包严格隔离**：runtime 不 import `eval`，不碰 evaluator truth store——这是 blind 红线（训练/阅卷可见真值天经地义，落点是 agent 输入侧屏蔽）。

### 3.4 进化层闭环

```
RunOrchestrator(evo_mode=True, evo_trace_capture=TraceCapture(...))
  └─ 各阶段 cap.capture_step / capture_retrieval / capture_closure / capture_report
  └─ cap.finalize(...) → EvoRunTrace（4 类 audit：forbidden_scan / source_visibility / schema / candidate_floor）
  └─ ReplayBuffer.add_trace(trace)            (forbidden_scan_passed=False 直接拒)
        ├─ aggregate_failure_patterns(...)    触发 A（重复失败）
        └─ aggregate_success_patterns(...)    触发 B（重复成功）
  ├─ evo.skill_induction → draft EvoSkillPackage（4 文件 + manifest 4 sha256，status=draft）
  └─ evo.policy_trainer.EvoPolicyTrainer.train_from_traces(...) → draft EvoPolicyVersion
        ↓ 五道 Gate（含 §11.9 artifact 端 reconstruction probe / §11.10 counterfactual swap）
        ↓ Gate 全过 → promote draft → active
  → runtime 应用面：
        policy_runtime.load_active_policy / apply_ranking_weights / apply_candidate_cutoff
        skill_runtime.load_active_skills / match_triggered_skills / resolve_skill_conflicts
```

**进化层不可逾越的不变量**：Skill / Policy 只影响 retrieval ranking + tool 顺序 + report 结构，**绝不**改 `allow_stop` / `closure_status` / `satisfaction_status`；`apply_candidate_cutoff` 的 `verifier_floor_set` 必须含所有 `score>0` 候选（不允许任何 cutoff 削窄 verifier 确定性候选全集）。

---

## 4. 公开 API 面（稳定对外 vs 内部实现）

判据：看各子包 `__init__.py` 的 `__all__` 再导出（re-export）即视为稳定对外面；`_前缀` 模块 / 未再导出的 helper 视为内部实现。

### 稳定对外（`__init__.py` re-export）

- **`evo_agent_baseline.contracts`**（顶层 `__init__.__all__` 唯一项）：所有跨模块 DTO / enum。最稳的一面，改字段牵一发动全身。
- **`closure`**：`validate_building_closure`（主入口）、`VerifierConfig`、`ApplicabilityResult`/`HighRiskItem`/`ObligationNodeDTO`/`ObligationEdgeDTO`、`ForbiddenSourceError` + `assert_no_forbidden_sources`、`compute_obligation_id`/`display_obligation_id`/`find_high_risk_items`/`sort_and_dedupe_obligations`/`summarize`/`build_machine_report`。
- **`retrieval`**：`retrieve_fact_pack`、`retrieve_rule_slice`、`make_retrieval_fn`、`pack_builder`（模块）。
- **`kg`**：`Neo4jClient`、`canonical_json`、`is_neo4j_available`、`load_kg_config`、`queries`（模块）。
- **`ingest`**：每路 loader 的 `build_*_graph` + `load_*_kg`（fact / sidecar / regulation / rulecard / skill）、`cypher_schema`、`guard`（模块）。
- **`eval`**：`TruthBundle`/`load_truth_bundle`、`AgentFamilyVerdict`/`aggregate_agent_family_verdicts`/`FamilyCrosswalk`/`load_crosswalk`、四个 `compute_*_metrics` + 对应 Metrics dataclass、`audit_leakage`/`LeakageAuditResult`、`EvalInputs`/`evaluate_run`/`write_eval_report`。
- **`evo`**：当前只 re-export `skill_package`、`skill_package_loader` 两个模块；其余（`feedback_broker`/`replay_buffer`/`skill_induction`/`skill_validation`/`policy_trainer`/`audits`/`trace_capture`）需直接 `from evo_agent_baseline.evo.<mod> import ...` 显式导入（`evo/__init__.py` 注释明确这些「由后续阶段填充」）。

### 内部实现 / 子模块级（不在 `__init__` re-export，按需直导）

- `agent/` 子包 `__init__.py` **不 re-export 任何符号**：用 `RunOrchestrator` / `run_llm_orchestration` / hooks / `policy_runtime` / `skill_runtime` 都要写全路径 `from evo_agent_baseline.agent.<mod> import ...`。
- `closure` 的 `obligation_deriver` / `fact_binding` / `applicability` / `threshold_eval` / `schema` 是验证器内部算子，正常只通过 `validate_building_closure` 间接用，不直接调。
- `retrieval.pack_builder` 的 `build_fact_pack` / `build_rule_slice` / `*_from_*` 系列是装配 helper，正常由 `retrieve_*` 调用；直接用要自己保证 blind（`assert_dto_blind_safe`）。
- `ingest/_common.py`、`ingest/_graphspec.py`：`_` 前缀，纯内部。
- `experiments/`：脚本级入口（`PairedExperimentRunner` / `run_ablation` / scaling_law 6 函数 / `ExperimentRun`），由 `scripts/run_*.py` 调，不算库 API。

---

## 5. 同名消歧（务必看，别用错）

包内入口名与 `workflow_engine`（W1/W2 数据生成侧）有两处撞名。两侧是**完全不同的对象**，导错包会静默拿到错类型。

### 5.1 `build_fact_pack`

| | `evo_agent_baseline.retrieval.pack_builder.build_fact_pack` | `workflow_engine.nodes.build_fact_pack` |
|---|---|---|
| 签名 | `(run_id, world_id, building_id, facts: List[FactAtom], source_tables) -> FactPack` | `(*, case_id, phase, description, case_dir: Path) -> FactPack` |
| `FactPack` 是谁 | **本包 `contracts.FactPack`**：MBIS 事实包，含 slot/measure/carrier 三个倒排索引 | **`workflow_engine` 的另一个 `FactPack`**：case 维度，`facts` 是 `FactItem` 列表，无倒排索引 |
| 用途 | 把已抽好的 `FactAtom` 列表装配成闭包验证器输入 | W1/W2 case 流程从 description 抽 observer/code-action facts |
| 何时用 | 检索装配阶段（认知层） | 数据生成 / case 编排（感知层，**不属本包**） |

→ 本包合规评估链一律用 `from evo_agent_baseline.retrieval.pack_builder import build_fact_pack`（或经 `retrieve_fact_pack` 间接）。看到 `case_id` / `phase` / `case_dir` 参数说明拿错成了 `workflow_engine` 的。

### 5.2 `evaluate_trigger` vs `evaluate_trigger_specs`

不是真同名（一个 `_specs` 后缀），但语义易混，且分属两侧：

| | `evo_agent_baseline.closure.obligation_deriver.evaluate_trigger` | `workflow_engine.fact_trigger_contract.evaluate_trigger_specs` |
|---|---|---|
| 签名 | `(card: RuleCardDTO, trigger: Dict, fact_index: FactIndex, fact_pack_meta) -> Obligation` | `(*, trigger_specs: List[SeedTriggerSpec], matched_feature_ids, matched_pattern_ids) -> List[Dict]` |
| 返回 | **单条 `Obligation`**（一个 trigger condition item 的四态求值结果） | **dict 列表**（每个 seed trigger spec 是否 matched + missing/blocked 明细） |
| 所属层 | 底线层闭包验证器内部算子（§6.3.3） | W1 感知层 seed trigger 匹配（**不属本包**） |
| 配套 | 同模块 `aggregate_trigger_logic` 做 card-level 四态聚合 | — |

→ 本包闭包侧只有 `evaluate_trigger`（单 `Obligation`）；要 batch 的 trigger spec 匹配是 W1 的事，不在本包。

### 5.3 顺带提醒：`SecurityError` 多处定义

`agent.hooks.SecurityError`、`ingest.guard.SecurityError`、`retrieval.pack_builder`（import 复用）等多处出现同名 blind 红线异常。语义一致（检出 W2 / 禁止字段时抛），但**不是同一个类对象**，跨模块 `except SecurityError` 捕获要注意 import 来源；编排器最终把它归一为 `stop_reason=forbidden_reference_truth_detected` / `status=blocked`。

---

## 6. 别踩的坑（速查）

- **闭包验证器只吃 `FactPack` + `RuleSlice`，绝不吃 W2 `NormativeProjection` / `expected_verdict`**——否则 agent 等于抄答案，违反 blind 红线。参考真值只在 `eval/` 旁路阅卷用。
- **`allow_stop` / `closure_status` / `satisfaction_status` 是确定性验证器唯一权威**：LLM、编排器、Skill、Policy 都不能改写。`policy_runtime.apply_candidate_cutoff` 的 `verifier_floor_set` 不许削窄。
- **`agent` runtime 不得 import `eval`**，也不碰 evaluator truth store（`config/evaluator.yaml` 是 evaluator-only）。
- **`agent/__init__.py` 与大部分 `evo` 子模块不在 `__init__` re-export**：用 `RunOrchestrator` / `EvoPolicyTrainer` / `ReplayBuffer` / hooks 等都要写全模块路径。
- **跑批结果别只看 high-level 指标**：`evaluation_status=completed` / `valid=True` 不代表实验有效，必下钻 `closure_summary` 的 `blocked_reason_counts` / `open_reason_counts` 分布（历史上字段名错位让 98% obligation blocked 但顶层指标全 PASS，潜伏多日）。
- **导入前置**：本包导入需 `PYTHONPATH=agent_v1\src`。
