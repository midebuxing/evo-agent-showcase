# retrieval/ —— 双源 KG-RAG 检索（认知层）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
双源检索 + 装配：事实侧 Fact KG-RAG 从 Neo4j 取建筑事实子图 → `FactPack`；法规侧 Rule KG-RAG 取候选 rule_card 打分排序 → `RuleSlice`。**只负责"检索 + 组装两个 DTO"，不做任何合规判定**——判定归 `closure/`。

## 入口
- `make_retrieval_fn(client, rulecard_bundle_id) -> RetrievalFn` —— 在 `__init__.py`。工厂，闭包捕获 `Neo4jClient` + bundle id，返回 `(world_id, building_id, run_id) -> (FactPack, RuleSlice)`，正好对齐编排器（`agent/llm_orchestrator.py`）注入的 `retrieval_fn`。**外部接线走这一个。**
- 两个源侧原语：`retrieve_fact_pack(client, run_id, building_id)`（`fact_retriever.py`）、`retrieve_rule_slice(client, run_id, fact_pack, rulecard_bundle_id, ...)`（`rule_retriever.py`）。
- 调用方 `rulecard_bundle_id` 标签的**单一权威来源**：`rulecard_bundle_identity.py`（读磁盘权威卡包自声明 `bundle_id`，2026-07-27 统一；历史上三个调用面三个值，别再复制常量）。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `fact_retriever.py` | 事实侧：跑 `kg.queries` 的 Cypher → `FactAtom` 列表 → `FactPack`；哪些字段展成 fact（`_*_FACT_FIELDS`）| 改事实检索/哪些字段进 FactPack |
| `rule_retriever.py` | 法规侧：候选卡信号 → `SCORE_WEIGHTS` 打分排序 → graph expansion → `RuleSlice`；`retrieve_rule_slice_with_skills` 是 skill-aware 变体 | 改候选检索/打分/verifier 候选集 |
| `pack_builder.py` | 扁平节点/子图 → DTO 还原 + 组装：`build_fact_pack` / `build_rule_slice` / `assert_dto_blind_safe` | 改 DTO 装配/嵌套还原/blind 收口 |
| `../contracts.py` | 公开 DTO：`FactPack`/`RuleSlice`/`FactAtom`/`RuleCardDTO` 等 | 看输入输出长什么样（只读相关类）|

`__init__.py` 用 `__all__` 暴露稳定对外面（`make_retrieval_fn`/`retrieve_fact_pack`/`retrieve_rule_slice`/`pack_builder`）——想知道"外面能用啥"看它。

## 红线 / 不变量（改这块绝不能破）
1. **blind（事实侧）**：Fact KG-RAG 只查事实侧 label（World/Building/Fragment/Measurement/SidecarEntry…），**绝不查 W2 `NormativeProjection`/`expected_verdict`**；DTO 严禁携带禁止属性名，`pack_builder.assert_dto_blind_safe` 是收口检查，违规抛 `SecurityError`（`ingest.guard`）。喂真值 = agent 抄答案。
2. **rule-blind 红线只属 W0/W1**：rule_card 检索是 baseline 本职，**不受 blind 约束**——别把 worldgen 端红线错套到这里（见记忆 `feedback_rule_blind_only_w0_w1`）；但取回 DTO 仍过 `assert_dto_blind_safe`。
3. **不产判定**：排名只影响 LLM context 顺序，**不影响闭包验证器的确定性候选全集**（verifier 候选集 = 所有 `score>0` 且 applicability 未排除的卡）；给了 cutoff 也强制 candidate universe floor。allow_stop/合规结论一律归 `closure/`。
4. **分层单向**：属认知层 `evo_agent_baseline`，⊥ 感知层 `workflow_engine`（互不 import）；不 import `eval/`。
5. **环境**：导入需 `PYTHONPATH=agent_v1/src`；Neo4j 走 `EVO_AGENT_NEO4J_*` 环境变量（库名 `neo4j`，不读 `config/kg.yaml`）。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\tests\test_retrievers.py agent_v1\src\evo_agent_baseline\tests\test_skill_aware_retrieval.py -q
```
（`test_retrievers` 覆盖两条检索链 + DTO 装配；`test_skill_aware_retrieval` 覆盖 skill-aware 排序 + verifier floor 不变量。改这块这两个必须全绿。）

## 常见任务 → 看哪个文件
- 改"哪些字段展成 FactAtom" → `fact_retriever.py` 的 `_*_FACT_FIELDS`
- 改候选卡打分权重/排序 → `rule_retriever.py` 的 `SCORE_WEIGHTS`
- 改扁平子图→原嵌套 DTO 还原 → `pack_builder.py` 的 builder 函数
- 接编排器/换依赖注入 → `__init__.py` 的 `make_retrieval_fn`
- **同名坑**：`build_fact_pack`（本块 `pack_builder`，装 DTO）是根 CLAUDE.md 点名的跨包同名——别跟别处同名函数导混；`retrieve_rule_slice`（v0.4）≠ `retrieve_rule_slice_with_skills`（skill-aware 变体）。

## 不归这块的（别在这找）
- 合规判定 / allow_stop / 义务派生 → `closure/`（`validate_building_closure`）
- Cypher 查询定义 → `kg/queries`（本块只调用）
- 灌库 / DTO 属性白名单守卫 → `ingest/`（`FORBIDDEN_AGENT_PROPERTIES` / `SecurityError` 定义处）
- W2 参考真值生成 → `workflow_engine/regulation_projection_*`
