# ingest/ —— 数据灌入知识图谱（认知/进化层）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
把固定上游产物（worldgen parquet / 法规 markdown / rule_card / seed Skill）灌进 Neo4j agent 知识图谱。每个 loader 分两段：**纯转换段** `build_*_graph`（parquet/JSON → `GraphBatch`，不碰 Neo4j、可全量单测）+ **写入段** `load_*_kg`（`GraphBatch` → MERGE → `Neo4jClient.write_many`）。

## 入口
- `load_fact_kg(run_dir, client, kg_snapshot_id, loaded_at)` —— 在 `fact_loader.py`。事实侧主灌入口，跑批脚本调它。
- `load_rulecard_kg` / `load_regulation_kg` / `load_sidecar_kg` / `load_skill_kg` —— 各在同名 loader，法规-Skills 侧 / sidecar 侧灌入。
- `guard.assert_agent_safe_input(input_dir, ...)` —— 灌库前 blind 启动守卫，第一步就调。
- 对外稳定面看 `__init__.py` 的 `__all__`（各 `build_*_graph` / `load_*_kg` + `cypher_schema` + `guard`）。

## 改这块只需加载（按需，多数任务 2-3 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `fact_loader.py` | W0/W1 worldgen 9 张 parquet → 事实侧节点/边 | 改事实层灌库/节点映射 |
| `sidecar_loader.py` | SidecarRuntimeBundle → sidecar 子图（**含 blind 关键约束**）| 改 sidecar 灌库 |
| `regulation_loader.py` | 法规 markdown → `RegulationClause` 切分灌入 | 改法规原文切分/灌库 |
| `rulecard_loader.py` | rule_card v2 → 结构化子节点（禁整卡塞 JSON）| 改 rule_card 落图 |
| `skill_loader.py` | 4 个 baseline seed `SKILL.md` → Skill 节点 | 改 seed skill 灌库 |
| `skill_edge_loader.py` | `SkillVersion` 按 scope 6 维嵌边到法规侧节点 | 改技能→法规嵌边 |
| `guard.py` | 白/黑名单 + 禁止属性名 + 灌库质量门 G-001~G-008 | 改灌库守卫/质量门 |
| `cypher_schema.py` / `cypher_schema_evo.py` | Neo4j 约束/索引/全文索引 DDL（只生成字符串不执行）| 改 schema DDL |
| `_graphspec.py` | `NodeSpec`/`EdgeSpec`/`GraphBatch` + MERGE Cypher 生成 | 改图元素/写入契约 |
| `_common.py` | parquet 读取、值规整、ID 工具 | 改公用底层工具 |

## 红线 / 不变量（改这块绝不能破）
1. **blind 红线（最高优先）**：agent KG **只灌白名单事实源，绝不灌 W2 法规映射层**（`NormativeProjection` / `expected_verdict` / `projection_id`）。`guard.assert_agent_safe_input` 是第一道防线（黑名单文件显式传入则 hard fail）；`_graphspec` 编译期 `assert_node_blind_safe` 是第二道；`sidecar_loader` 的 `projection_id` 只许内存临时读、末尾断言不进 props。喂 W2 进 agent KG = agent 抄答案 = 违规。
2. **分层单向**：本包（认知/进化层）⊥ 感知层 `workflow_engine`，两包互不 import；agent runtime **不得 import `eval`**（评测旁路）。
3. **白/黑名单/禁止属性名逐条照搬 spec，不增不减**（spec→code 单向）；同名清单也落在 `config/guard.yaml`，两者必须一致（`assert_guard_config_consistent`）。
4. **写图只用 `MERGE` 幂等，禁止 `CREATE`**；DDL 全 `IF NOT EXISTS`。
5. **环境**：导入需 `PYTHONPATH=agent_v1/src`；Neo4j 走 `EVO_AGENT_NEO4J_*` 环境变量（库名 `neo4j`，**不读** `config/kg.yaml`）。

## 改完跑哪个测试
测试散在 `evo_agent_baseline/tests/`（无 ingest 专属子目录），点名本子系统的 9 个文件：
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\tests\test_fact_loader.py agent_v1\src\evo_agent_baseline\tests\test_sidecar_loader.py agent_v1\src\evo_agent_baseline\tests\test_regulation_loader.py agent_v1\src\evo_agent_baseline\tests\test_rulecard_loader.py agent_v1\src\evo_agent_baseline\tests\test_skill_loader.py agent_v1\src\evo_agent_baseline\tests\test_skill_edge_loader.py agent_v1\src\evo_agent_baseline\tests\test_guard.py agent_v1\src\evo_agent_baseline\tests\test_graphspec.py agent_v1\src\evo_agent_baseline\tests\test_cypher_schema.py -q
```
（`build_*_graph` 纯转换段无需活体 Neo4j，测试全覆盖；改完这几个必须全绿。）

## 常见任务 → 看哪个文件
- 改某张 parquet → 事实节点怎么映射 → `fact_loader.py`（改完核 `_graphspec` blind 断言）
- 加/改灌库白名单或黑名单 → `guard.py` + 同步 `config/guard.yaml`
- 改 rule_card 子节点/registry 落图 → `rulecard_loader.py`
- 改 Neo4j 约束/索引 → `cypher_schema.py`（v0.4 基线）或 `cypher_schema_evo.py`（v1 namespace，互补不重复）
- 改技能挂到法规哪个节点 → `skill_edge_loader.py`（scope 5 条嵌边）
- 同名坑：本块的 `build_fact_graph`（parquet→图）≠ 检索侧 `build_fact_pack`（组装 `FactPack`）；两处别导错。

## 不归这块的（别在这找）
- 执行 DDL / 真写 Neo4j 的驱动 → `kg/neo4j_client.py`（本块只生成语句/batch）
- 组装喂给闭包的 `FactPack` → `retrieval/pack_builder.py`
- 评测真值灌入 `eval_truth_loader`（spec §4.6）→ evaluator-only，不在本子系统，agent runtime 不 import
- 上游数据生成（parquet / 法规映射本身）→ `workflow_engine/`（感知层）
