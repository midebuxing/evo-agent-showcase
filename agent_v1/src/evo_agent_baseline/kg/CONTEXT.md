# kg/ —— 知识图 Neo4j 接口层（认知层）门口卡

> 给 AI / 新人的"最小上下文卡"：改这块，**先读这张卡 + 下面点名的文件**就够，不用翻全仓。
> （引文件名+函数名，不引行号——行号会漂。）

## 这块干什么（一句话）
evo-agent 的 Neo4j 接口层：一个薄连接客户端 + 一套 KG-RAG 检索 Cypher 查询库。**本块只连接、只承载查询串，不做业务判定、不装配 DTO。** 执行结果交给 `retrieval/` 装配成 `FactPack`/`RuleSlice`。

## 入口
- `Neo4jClient`（在 `neo4j_client.py`）—— 薄连接封装：`.run` / `.read` / `write_tx` / `apply_schema`。灌库（`ingest/`）与检索（`retrieval/`）都靠它连库。`from_config` 从 `config/kg.yaml` 造实例。
- `queries` 模块（在 `queries.py`）—— 一堆 `FACT_*` / `RULE_*` Cypher 常量 + `building_params()` 等参数构造函数。检索侧 import 它拿查询串。
- 两者都在 `__init__.py` 的 `__all__` 里显式暴露（外加 `canonical_json` / `is_neo4j_available` / `load_kg_config`）——想知道"外面能用啥"看它。

## 改这块只需加载（按需，多数任务 1-2 个就够）
| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| `neo4j_client.py` | 连接封装 + `canonical_json`（全图统一序列化）+ `is_neo4j_available`（探 7687，测试 skip 用）+ `load_kg_config` | 改连库方式 / 序列化口径 |
| `queries.py` | §5.3 Fact 检索 + §5.4 Rule 检索的 Cypher 串 + 参数构造函数 | 加 / 改一条检索查询 |
| `../config/kg.yaml` | `from_config` 读的库名 / 三套凭据 / uri | 改生产连库目标 |
| `../contracts.py` | 查询结果最终装配成的公开 DTO（本块不产 DTO，只知道去向）| 想知道查询喂给谁 |

## 红线 / 不变量（改这块绝不能破）
1. **blind**：所有查询只 MATCH 事实侧（`Building`/`Fragment`/…）与法规-Skills 侧 label，**绝不触碰 W2 `NormativeProjection` / `expected_verdict` 等参考真值 label**。加查询前自查有没有勾到真值——勾到 = agent 抄答案 = 红线违规。
2. **两库物理隔离（spec D-001）**：本客户端只连 agent database，**不提供任何到 eval database 的入口**。评测真值库归 `eval/`，agent runtime 不碰。
3. **分层单向**：本块属认知/进化层 `evo_agent_baseline`，与感知层 `workflow_engine` 互不 import；也不 import `eval`（旁路阅卷）。
4. **只查不判**：本块不产 `allow_stop` / `closure_status` 等合规判定（那是 `closure/validator.py` 唯一权威），也不做适用性/义务派生。查询只取原始子图。
5. **canonical_json 稳定性**：key 排序 + 紧凑分隔符 + `None→"null"`，全图统一。改它会动 hash / 可复现性，牵连灌库与检索两侧。

## 改完跑哪个测试
```
$env:PYTHONPATH="agent_v1\src"
python -m pytest agent_v1\src\evo_agent_baseline\tests\test_neo4j_client.py agent_v1\src\evo_agent_baseline\tests\test_queries.py -q
```
（本子包无自带 tests 目录，用例在包级 `evo_agent_baseline/tests/`：`test_neo4j_client` 测序列化 / 配置 / URI 解析 / 探测；`test_queries` 测查询串。依赖活体 Neo4j 的用例靠 `neo4j_required` 自动 skip。）

## 常见任务 → 看哪个文件
- 加 / 改一条 KG-RAG 检索 → `queries.py`（加 `FACT_*` / `RULE_*` 常量 + 配套 `*_params` 函数；自查没勾 W2 label）
- 改连库方式 / 凭据 / 目标库 → `neo4j_client.py`（`from_config`）+ `../config/kg.yaml`
- 改全图序列化口径 → `neo4j_client.py`（`canonical_json`，改前想清楚灌库侧也用它）
- 查询结果怎么变成 `FactPack` / `RuleSlice` → 不在这块，去 `retrieval/pack_builder`

## 连库同名坑（务必分清两条路径）
**`config/kg.yaml` 与 `EVO_AGENT_NEO4J_*` 环境变量是两条并行的连库路径，库名不同，有意如此：**
- `Neo4jClient.from_config` **读 `config/kg.yaml`** → 生产 / spec D-001 目标，库名 `evo_agent_baseline`、三套独立凭据。
- `scripts/run_*.py`（dev 跑批工具）**不读 kg.yaml**，直接走 `EVO_AGENT_NEO4J_*` 环境变量 → 库名默认 `neo4j` / user `neo4j`（即根 `CLAUDE.md` 环境节说的那条）。

改 `kg.yaml` **不会**改脚本连的库；反之亦然。`__init__.py` / `neo4j_client.py` 顶部 docstring 只描述了 `from_config` 那条，别据此以为脚本也读 yaml。

## 不归这块的（别在这找）
- 查询结果 → DTO 装配（扁平子图还原 `FactPack`/`RuleSlice`）→ `retrieval/pack_builder`
- 往库里灌数据（schema DDL、fact / rule_card / sidecar / skill 边）→ `ingest/`
- 合规判定 / 义务派生 → `closure/`
- 评测真值库 / 阅卷 → `eval/`（本块不连它、不 import 它）
