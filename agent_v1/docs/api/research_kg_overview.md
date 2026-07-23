# 架构导航：`research_kg`

> 配套自动 API 参考（函数/类签名 + docstring + pydantic 字段表）：[`research_kg.md`](./research_kg.md)
>
> 本文是人工写的架构导航，目的是"读完知道这个包怎么用、入口在哪、别踩哪些坑"。聚焦代码 API，不复述设计规格。
> 设计背景可参考蓝图：`团队文档/我的笔记/蓝图汇总/W2法规映射层全量实现级设计规格包/`（法规映射侧）与 `evo-agent_baseline_设计规格_v0.4.md`。

---

## 1. 一句话定位

`research_kg` 是**研究侧的双源 KG-RAG 基线/检索栈**，用于对照实验：给一句缺陷描述（query），它做"链路分诊 → KG 检索召回最小规则/技能/触发器集 → 本地 LLM 抽取事实+选规则 → 闭包验证器核验"的端到端最小流程，产出可逐查询审计的报告。它在四层架构里**横跨"感知/认知"（检索召回 + LLM 抽取）和"底线"（复用 `workflow_engine` 的闭包验证器）两层**，本身是**对照基线**——不是进化层（evo-agent 自进化在 `evo_agent_baseline` 包），而是用来跟进化版/路由辅助版拉对比的固定参照系。

它与 W2 数据生成层的关系：W2 产参考真值，`research_kg` 是 agent 侧消费方；闭包验证不读 W2 的 `NormativeProjection`（保 blind），只用从 KG RuleCard 节点重建的规则条件做核验。

---

## 2. 子包 / 核心模块职责表

包是单层扁平结构（`__init__.py` 为空，无 re-export），6 个模块各自一职：

| 模块 | 职责（一行） |
| --- | --- |
| `loader.py` | 读 + 校验双源 KG 种子文件（building_fact_kg / rule_skill_kg 两侧 manifest+nodes+edges），可选挂载法规语料，返回顶层句柄 `DualSourceResearchKG` |
| `kg_retriever.py` | 链路分诊（正则关键词命中 crack/rebar_spall）+ 按 manifest 的 `mainline_chains` 定义召回该链路的最小 RuleCard/Skill/Trigger/FactPattern/FactFeature 集 |
| `baseline_config.py` | 本地 LLM 配置 `LocalLLMConfig`：强制 base_url 指向本机地址（127.0.0.1/localhost），拒绝远端代理；读 `.env` / 环境变量 |
| `baseline_runner.py` | **核心基线流水线**：query → 检索 → LLM 抽取事实+选规则 → 建 FactPack/RuleCard/seed_bridge → 调 `validate_closure` → `LocalBaselineReport` |
| `integrated_demo_runner.py` | 在 baseline 之上加 `routing_assisted` 路由辅助模式（触发器打分+保守路由收窄候选），并做两模式配对对比报告（含回归检测） |
| `regulation_corpus.py` | 从本地 PDF 法规源构建规范化语料（markdown/chunks/manifest），及加载已生成语料；`loader.py` 可选挂载它作并行证据语料 |

数据目录（非代码）：`agent_v1/research_kg/manifest.json` + `building_fact_kg/` + `rule_skill_kg/`，链路定义、bridge_nodes、source_of_truth 指针都在顶层 manifest。

---

## 3. 关键入口与数据流

### 三个对外入口（按使用频率）

1. **`baseline_runner.run_baseline(query, kg_dir=None, config=None) -> LocalBaselineReport`**
   一行跑通单查询基线。默认从 `agent_v1/research_kg/` 加载 KG。最常用入口。

2. **`baseline_runner.DualSourceBaselineRunner(kg, config).run(query)`**
   复用同一个已加载 KG 跑多条查询时用（`run_baseline` 每次都重新 load KG）。

3. **`integrated_demo_runner.write_phasee_comparison_artifacts(query_set_path=..., ...)`**
   跑整套查询集，输出 baseline / routing_assisted 两份结果 + 配对对比报告 JSON。命令行：`python -m research_kg.integrated_demo_runner --compare --query-set <path>`。

### 数据流（baseline 主链）

```
query (str)
  │
  ▼  detect_chain()  正则命中 crack / rebar_spall / unknown
retrieve_from_kg(kg, query) ──► RetrievalResult
  │   （按 manifest.mainline_chains[chain] 取 rule_cards/skill/trigger/fact_pattern；
  │     trigger.properties.required_feature_ids 再去 building_fact 侧取 fact_features）
  ▼
_build_extraction_prompt() ──► _call_llm(config, prompt)  本地 LLM（Ollama 原生 API 或 OpenAI 兼容）
  │
  ▼  _parse_llm_response()  容错解析 JSON（剥 markdown 围栏）
{extracted_facts, selected_rule_ids, reasoning}
  │
  ├─► _build_fact_pack()  抽取事实 ──► FactPack
  ├─► _normalize_selected_rule_ids()  把 LLM 选的 id 对齐到检索到的 RuleCard node_id
  │      └─ 选中 → filter_rule_cards()；空/未命中 → 回退全部规则(fallback_all)
  ├─► _build_rule_cards_for_closure()  KG 节点 → evidence_schema.RuleCard
  └─► _build_seed_rule_bridge()  从 trigger 的 required_pattern/feature_ids 建 seed_rule_bridge
  ▼
workflow_engine.closure_validator.validate_closure(rule_cards, fact_pack, seed_rule_bridge)
  ▼
ClosureValidationResult（allow_stop / obligations / unmet_obligations）
  ▼
LocalBaselineReport.to_dict() / to_json()   含 chain_status + closure_summary
```

unknown 链路 / LLM 调用失败 / 闭包异常都有**早退分支**，分别写不同的 `chain_status`（`not_matched` / `llm_error` / `closure_error` / `success`）和 `error` 字段——不抛异常给调用方，靠报告字段下钻。**复盘跑批别只看 `success`，要看 `chain_status` 和 `closure_summary` 分布。**

### routing_assisted 模式增量（`integrated_demo_runner`）

在 baseline 选规则之后插入一段**保守路由覆盖层**：用 `match_fact_pack`（fact→feature/pattern 命中）+ `TriggerRanker`（先验/特征/模式加权打分）排触发器，仅当 top-1 触发器"有 pattern 信号支撑 + 落在已检索链路内"时才用它收窄候选规则；任一保护条件不满足就回退 baseline。路由的可解释决策码记在 `routing_summary.route_reason`（如 `pattern_backed_top1_within_retrieved_chain` / `no_pattern_signal` / `top_trigger_outside_retrieved_chain`）。配对对比报告会做**回归检测**（baseline 能闭包但 routing 退化 = regression）。

---

## 4. 公开 API 面

`__init__.py` **为空**——没有包级 `__all__`、没有 re-export。所以"对外稳定面"是按惯例（命名 + 是否被跨模块导入）划分的，而非语言强制：

**稳定对外接口**（建议从模块路径直接 import，签名相对稳定）：

| 符号 | 模块 | 用途 |
| --- | --- | --- |
| `run_baseline` | `baseline_runner` | 单查询基线便捷函数 |
| `DualSourceBaselineRunner` / `LocalBaselineReport` | `baseline_runner` | 复用 KG 的运行器 + 报告对象 |
| `LocalLLMConfig` | `baseline_config` | 本地 LLM 配置 |
| `load_dual_source_kg` / `DualSourceResearchKG` | `loader` | 加载 KG + 顶层句柄 |
| `retrieve_from_kg` / `detect_chain` / `RetrievalResult` | `kg_retriever` | 检索 + 分诊 |
| `IntegratedDemoRunner` / `write_phasee_comparison_artifacts` / `build_phasee_comparison_report` / `load_demo_query_set` | `integrated_demo_runner` | 路由辅助 + 配对对比 |
| `build_regulation_corpus` / `load_regulation_corpus` / `RegulationCorpus` | `regulation_corpus` | 法规语料构建/加载 |

**内部实现**（前缀 `_`，**不要从外部依赖，签名随时可变**）：`baseline_runner` 里的 `_call_llm` / `_build_extraction_prompt` / `_build_fact_pack` / `_build_rule_cards_for_closure` / `_build_seed_rule_bridge` / `_normalize_selected_rule_ids` / `_parse_llm_response`。注意：`integrated_demo_runner` **跨模块 import 了这一串下划线函数**复用——这是包内默契耦合，不是公开契约；改这些函数签名要同步改 `integrated_demo_runner` 的 import 块（`baseline_runner.py:117-201` ↔ `integrated_demo_runner.py:10-18`）。

`loader._validate_*` / `loader._resolve_external_asset_path` / `kg_retriever._collect_graph_skill_ids` 等也是私有，仅本模块用。

---

## 5. 同名消歧（务必看清，别 import 错）

### 5.1 `build_fact_pack` —— 三处同名，签名/语义完全不同

| 位置 | 签名要点 | 是谁 |
| --- | --- | --- |
| `research_kg.baseline_runner._build_fact_pack`（**私有，带下划线**） | `(query, extracted_facts: dict, chain) -> FactPack` | 本包内部：把 LLM 抽取的事实字典转 FactPack，`case_id=f"phaseD-baseline-{chain}"` |
| `workflow_engine.nodes.build_fact_pack`（公开，kw-only） | `(*, case_id, phase, description, case_dir) -> FactPack` | 另一栈：按 phase A/B... 从 case 目录抽观察者事实 |
| `evo_agent_baseline.retrieval.pack_builder.build_fact_pack`（公开） | `(run_id, world_id, building_id, facts: List[FactAtom], source_tables) -> FactPack` | 进化基线侧：从 `FactAtom` 列表组装 FactPack + 三个倒排索引 |

→ 本包的那个是**私有下划线** `_build_fact_pack`，别跟另外两个公开 `build_fact_pack` 混。要"从结构化事实建 FactPack"且在 `research_kg` 语境下，用本包私有的；其它两个是别的栈的入口。

### 5.2 `evaluate_trigger_specs` vs `evaluate_trigger` —— 不同栈，别替换

| 符号 | 位置 | 签名 | 语义 |
| --- | --- | --- | --- |
| `evaluate_trigger_specs`（**本包通过它做路由**） | `workflow_engine.fact_trigger_contract` | `(trigger_specs, matched_feature_ids, matched_pattern_ids) -> List[dict]` | 批量评估 seed trigger specs 对一组已命中 feature/pattern 的硬匹配，返回每个 trigger 的命中/缺失项 |
| `evaluate_trigger`（单数，**不是本包用的**） | `evo_agent_baseline.closure.obligation_deriver` | `(card, trigger, fact_index, fact_pack_meta) -> Obligation` | 进化基线闭包侧：评估单个 trigger condition item，产 Obligation 三态 |

→ `integrated_demo_runner` 用的是**复数 `evaluate_trigger_specs`**（路由打分用），跟进化栈的单数 `evaluate_trigger`（闭包派生 Obligation）毫无关系，别因名字像就互换。

### 5.3 `main` —— 两处包内同名

`research_kg.loader.main()`（无参，打印 KG summary）与 `research_kg.integrated_demo_runner.main(argv)`（argparse 入口）。命令行跑 demo 用后者；前者只是 loader 自检打印。包外还有多处 `main`（见自动参考的 ⚠️ 标注），都是各自模块的 CLI 入口，互不相干。

---

## 6. 踩坑提示

- **不要跑灌库类实验脚本来"验证"本包**——会污染 Neo4j、错位 seed。语法检查用 `python -m py_compile`，命令行入口靠 argparse 在连服务前就能 `--help`。
- **本地 LLM 是硬约束**：`LocalLLMConfig` 强制 base_url 指向 127.0.0.1/localhost，远端会直接抛 `RuntimeError`。跑前要先起本地推理服务（Ollama / LM Studio / vLLM）。无服务时 `run()` 不崩——走 `llm_error` 早退分支，报告里 `chain_status` 标 `llm_error`。
- **链路分诊是正则关键词**，不是语义匹配。`detect_chain` 只认 crack / rebar_spall 两条链的中英关键词，命不中就 `unknown` 早退。新增链路要改 `kg_retriever._CRACK_KEYWORDS` / `_REBAR_SPALL_KEYWORDS` + manifest 的 `mainline_chains`。
- **闭包不读 W2 参考真值**（保 blind）：规则条件是从 KG RuleCard 节点 `properties.conditions` 重建的，不消费 `NormativeProjection`。
- `import` 路径需要 `PYTHONPATH=agent_v1\src`（Windows PowerShell：`$env:PYTHONPATH = "agent_v1\src"`）。
