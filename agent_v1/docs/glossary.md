# 术语表（glossary）

> 本项目黑话速查。每条 = 1-2 句中文定义 + 在代码/文档哪里出现。
> 看不懂某个词先查这里，再回去读源码或对应的 [`api/*_overview.md`](api/)。
>
> 配套导航：先跑 [`QUICKSTART.md`](QUICKSTART.md) → 看全局 [`ARCHITECTURE.md`](ARCHITECTURE.md) → 看各包细节
> [`api/evo_agent_baseline_overview.md`](api/evo_agent_baseline_overview.md) /
> [`api/workflow_engine_overview.md`](api/workflow_engine_overview.md) /
> [`api/research_kg_overview.md`](api/research_kg_overview.md)。

---

## 领域与项目代号

### MBIS

香港强制验楼计划（Mandatory Building Inspection Scheme），本项目的合规领域——
即"楼龄达标的建筑须依法定周期做强制检验并整改缺陷"这套制度。整个 evo-agent
就是围绕 MBIS 的**合规助手代理**搭的。出现在 [`README.md`](../README.md) 抬头、
[`api/evo_agent_baseline_overview.md`](api/evo_agent_baseline_overview.md) §1。

### evo-agent

项目代号，指整个"合规助手代理 + 运行时自进化研究系统"。四层架构（感知 / 认知 /
底线 / 进化）+ 评测旁路。运行体在 `evo_agent_baseline` 包，世界/真值生成在
`workflow_engine` 包。见 [`README.md`](../README.md)「四层架构 ↔ 代码包」表。

### 满血版 vs evo 探索版

研究里的两个对照系统。**满血版 baseline agent** = 固定不动、出第一阶段报告的参照系，
受 W0/W1/W2 + baseline 规格制约。**evo 探索版** = 我们实验的自进化版本，机制设计
（技能注入 / 闭包分批预算 / 家族排序等）自由、不受规格制约，但"学"必须真实（靠归纳
学来、非人为硬塞）。配对消融就是拿这两者比。见 [`QUICKSTART.md`](QUICKSTART.md) §5
假桩指标警告（区分哪条线是真实结果）。

**满血版精确定义（2026-07-08 用户拍板）**——"基线"一词的本体指 **LLM 档**：

- 大模型在环、工具箱可用且**必须真实调用**（`tool_call=0` 即废跑，035427 教训）；
- **"满血"= 闭包查询无预算、无分批、无翻页策略**——按需查询、每问全量答、次数不设限。
  预算/分批（`EVO_CLOSURE_QUERY_BUDGET`，实现在 `evo/closure_budget.py`）是探索版的
  差异化杠杆，满血版不碰；"满血"≠ 一口吞全库（单楼 FactPack+RuleSlice ≈ 2 MB JSON，
  本来也是喂闭包验证器的，不是喂大模型的）；
- 技能集固定、无归纳无进化；blind（不见 W2）；**判定权仍在确定性闭包验证器**（大模型
  只做工具调用与核验编排，不改判）；产出第一阶段报告。

**确定性档**（无 LLM 跑主链，EXP-011 批跑所用）不是基线本体，是**管线地板参照**：
验评测基建 + 给"无模型下界"。

**"基线完成"五道门**（缺一不算完成，防"管线通了就宣告完成"的措辞漂移）：
① 工具调用审计 `tool_call > 0` 且决策链落盘；② blind 审计过（不碰 W2、不 import `eval`）；
③ **verdict 有区分度**（非全 unknown；前置 = 供给侧解锁：DEBT-048 + 流程槽粒度决策 + 生成侧建模）；
④ 可复现（池 seed + commit + 库名三锚定）；⑤ 数字冻结存档（该版即论文引用的对照值）。
首跑载体 = EXP-008。EXP-011（2026-07）交付的是**基线前置基建**（三道断闸 + 四态阅卷管线），
不构成"基线完成"。

---

## 四层架构与数据生成层

### W0 / W1 / W2

数据生成（感知层）的三层，全在 `workflow_engine` 包：

- **W0**：资源 / 注册表定义层——19 张注册表 + sidecar 契约，所有结构数据来源。
- **W1**：实例生成层——按注册表 + 物理公式生成一批 building world（建筑实例），
  rule-blind（不读法规），产 `WorldBundle` + sidecar 派生 + parquet。
- **W2**：法规映射层——在 W1 输出上做 per-fragment 法规投影，产
  `NormativeProjection` 参考真值（给评测阅卷用，**不喂给 agent**）。

入口：`worldgen.validation.run_worldgenerator_fullcoverage_framework_v2`（一函数串
W0+W1+W2 共 7 步）。见 [`api/workflow_engine_overview.md`](api/workflow_engine_overview.md)
§1 / §3.1。

### NormativeProjection

W2 输出的**参考真值**——per-fragment 法规投影主输出对象（含 threshold 评估 / family
适用性 / unknown 归因等）。它是评测阅卷与审计材料，**不进 agent 的 feature 流水线**
（否则 agent 抄答案、违反 blind 红线）。定义在
`workflow_engine.regulation_projection_models`。见 workflow_engine overview §2.3 / §4 坑 5。

### family（家族）

法规家族——一组同类法规义务的归类。闭包验证按**家族覆盖**判定：每个家族要么被覆盖
（有适用规则被求值）要么算缺口。W0 端有自己的 family prefix（W2 投影按它匹配真阈值，
见 `regulation_thresholds.get_thresholds_for_w0_family`）；闭包侧按家族聚合 obligation。
评测里 agent 的细粒度裁决经 crosswalk 聚合到 family 维度比对真值
（`eval.aggregate_agent_family_verdicts`）。见两份 overview 多处。

### blind 红线

agent 运行时**绝不看 W2 参考真值**（`NormativeProjection` / `expected_verdict` 等），
防止抄答案。落点是 agent **输入侧**屏蔽：`agent` runtime 不得 import `eval` 子包、不碰
evaluator truth store；只有 `eval/` 评测旁路（离线阅卷）可见真值。注意：训练 / 阅卷看
真值是天经地义，红线只卡 agent 推理输入。守卫实现见 `agent/hooks.py`
（`post_retrieval_source_audit` 等）+ closure 的 `assert_no_forbidden_sources`。
见 evo_agent_baseline overview §3.3 / §6。

### 双源 KG-RAG

认知层的检索栈，从两路知识图谱检索：**事实侧**（建筑事实 KG → `FactPack`）+ **法规侧**
（rule_card / skill KG → `RuleSlice`）。主线实现在 `evo_agent_baseline.retrieval`
（`fact_retriever` / `rule_retriever` / `pack_builder`）；对照基线在 `research_kg`
（`loader` + `kg_retriever` + `baseline_runner`）。见 evo_agent_baseline overview §2 /
research_kg overview §1。

### 五路 KG（灌库顺序）

真实全链路灌库的固定顺序：`regulation → rulecard → fact → sidecar → skill`。唯一把这套
顺序编排好的入口是 `scripts/run_baseline_e2e_smoke.py`（建 schema → 5 路 loader）。
loader 在 `evo_agent_baseline.ingest`。见 [`QUICKSTART.md`](QUICKSTART.md) §3.3。

---

## 底线层：闭包验证

### closure / 闭包验证

确定性合规判定——底线层核心。给定规则切片 + 事实包，纯 Python（无 LLM、无 Neo4j）算出
每条义务的状态和**唯一权威的停止位**。入口
`validate_building_closure`（`closure/validator.py`，
`evo_agent_baseline.closure`）。注意这不是"核对报告引用真实性 / 语义一致性"——
它就是 `RuleSlice + FactPack → ClosureValidationResult`。见 evo_agent_baseline
overview §3.1 / §6。

> 同名消歧：`workflow_engine.closure_validator.validate_closure` 是另一个包的 baseline
> 台架轻量实现，**不是**底线层权威。谈"闭包验证器"默认指
> `validate_building_closure`。见 workflow_engine overview §6.3。

### FactPack（事实包）

闭包验证器的输入 DTO 之一。MBIS 事实包，含 slot / measure / carrier 三个倒排索引，由
检索装配阶段从 `FactAtom` 列表组装（`retrieval.pack_builder.build_fact_pack`）。定义在
`evo_agent_baseline.contracts`。

> ⚠️ `build_fact_pack` 在三个包各有同名/同义函数，签名语义都不同（本包 retrieval 侧 /
> `workflow_engine.nodes` / `research_kg` 私有 `_build_fact_pack`）。跨包引用务必写全限定
> 路径。见三份 overview 的「同名消歧」节。

### RuleSlice（规则切片）

闭包验证器的另一个输入 DTO。候选 rule_card 经检索打分排序后的切片，保留 rule_card v2
原嵌套 + registry 子 DTO。由 `retrieval.rule_retriever` / `retrieve_rule_slice` 产出。
定义在 `evo_agent_baseline.contracts`。

### obligation（义务）+ 三态

闭包验证器对每条法规义务求出的结果。**三态 = open / blocked / satisfied**：

- **open**：义务适用但事实不足以判定满足，未完成。
- **blocked**：求值被某前置条件挡住（缺字段、被禁源拦截等），无法判定。
- **satisfied**：义务被事实满足。

义务集 + `ClosureSummary` 由验证器内部固定顺序生成（applicability → triggers → slot
roles → thresholds → obligation graph → …）。`Obligation` 定义在 `contracts`，派生算子在
`closure/obligation_deriver.py`。见 evo_agent_baseline overview §3.1。

### allow_stop

闭包验证器输出的**唯一权威停止位**——告诉系统"这栋楼的合规核验是否可以收尾"。
**LLM、编排器、技能、策略都不能改写**它。即使 LLM-as-brain 模式下 LLM 拒绝调闭包，
编排器在 finalize 前也会强制跑一次验证器取 `allow_stop`。在 `agent/hooks.py` 的
`post_verifier_stop_gate` 锁死。见 evo_agent_baseline overview §3.1 / §3.2 / §6。

### closure_status / satisfaction_status

与 `allow_stop` 同属"确定性验证器唯一权威"的判定字段，LLM / 编排 / 技能 / 策略均不可
改写。`closure_status` 描述整栋楼闭包是否完成，`satisfaction_status` 描述义务满足态。
进化层 Skill / Policy 只能影响检索排序 + 工具顺序 + 报告结构，**绝不**改这三个字段。
见 evo_agent_baseline overview §3.4 / §6。

### Gate 0-4（五道 Gate）

进化层发布门——draft 技能 / 策略要连过五道闸才能 promote 成 active。含 artifact 端
reconstruction probe（重建探针）/ counterfactual swap（反事实对换）等审计。Gate 全过 →
draft 升 active。见 evo_agent_baseline overview §3.4。

---

## 认知层与编排

### RunOrchestrator

对外最稳的高层入口（认知层 + 底线层主链编排器）：把一次建筑评估串成规格的 11 步，
检索与闭包通过**依赖注入**（callable）传入，便于单测换假桩、集成换真实子模块。
`run(world_id, building_id, ...)`。在
`evo_agent_baseline.agent.run_orchestrator`（要写全模块路径，`agent/__init__.py` 不
re-export）。见 evo_agent_baseline overview §3.1、[`QUICKSTART.md`](QUICKSTART.md) §3.3。

### slot（两套互斥含义，说时必须消歧）

本项目"slot"有**两套独立定义，靠命名一致衔接**，说的时候要明示哪端：

- **W0 端**：按 `worldgen/registry.py` 定 **5 类 slot**（资源/数据生成侧）。
- **rule_card 端**：`semantic_slot` + `measure_registry` 定 **2 类 slot**（法规消费侧）。

二者各自独立定义，不要混为一谈。`FactPack` 的倒排索引里也有 slot 维度（事实侧）。
说 slot 默认要带前缀讲清是哪端。见 workflow_engine overview §2.1（registry）+
evo_agent_baseline overview §2（contracts / FactPack）。

---

## 进化层

### evo / skills-evo

**evo** = 进化层（自进化）：trace 捕获 → replay → 技能归纳 / 策略训练 → 五道 Gate
发布 → 注入回认知层。代码在 `evo_agent_baseline.evo` + `experiments`。
**skills-evo** = 其中的技能进化闭环：运行时靠**归纳**学技能（不是人为硬塞），自适应改进
工具调用决策（检索排序 + 工具调度顺序）。研究主线把 Scaling Law 延伸到运行阶段
（跑得越多越会）就是靠它。见 [`README.md`](../README.md) 抬头、evo_agent_baseline
overview §3.4。

### EVO_CLOSURE_QUERY_BUDGET

skills-evo 制造 baseline ↔ evo **真正差异的杠杆**——闭包查询的**分批轮数预算** +
**skill 家族排序**。即 evo 版靠"分批查闭包 + 按学到的家族优先级排序候选"省轮次/调对
顺序，而非靠改 `allow_stop`（那是红线）。

> ⚠️ 目前它只在 gitignored 草稿 `杂物箱/run_paired_real_pipeline.py`（论文真 LLM 跑批用
> 的也是这个草稿），是**待晋升的关键模块**，尚未进主线 `src/`。别记混成
> `max_tool_iterations`（那是 5 变体一视同仁砍调用，不是差异杠杆）。见
> [`QUICKSTART.md`](QUICKSTART.md) §3.2 脚注。

---

## 对照基线（不在主链）

### research_kg

研究侧的双源 KG-RAG **对照基线/检索栈**：query → 链路分诊 → KG 检索召回 → 本地 LLM
抽事实+选规则 → 闭包验证。它是**固定参照系**（跟进化版/路由辅助版拉对比），**不是**
进化层、**不在主链上**。横跨"感知/认知"（检索+抽取）和"底线"（复用闭包验证器）两层。
入口 `research_kg.baseline_runner.run_baseline`。见
[`api/research_kg_overview.md`](api/research_kg_overview.md) §1。

---

## 实验与假桩

### 假桩 / mock 指标

部分脚本产的是 **mock / 硬编码合成数字**，是跑通框架用的占位，**不能当真实实验结果引用**
（如 `run_evo_full_experiments.py` 的 `aggregate_delta=+0.07`、`run_evo_scaling_demo.py`
的自指拟合）。真实 evo 结果走 `run_evo_batch_experiment.py`（真 LLM + 真闭包）→
`run_evo_llm_paired.py`，论文级数据见 `实验记录/EXP-NNN`。见
[`QUICKSTART.md`](QUICKSTART.md) §5。
