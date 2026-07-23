# evo-agent v1

香港强制验楼（MBIS）场景的**合规助手代理 + 运行时自进化研究系统**。LLM 当大脑做工具编排和写报告，但**所有合规判定由确定性闭包验证器锁死、LLM 不可改**；外加一套读参考真值离线阅卷的评测闭环，和一套"跑得越多越会"的进化层（trace → 归纳技能/训练策略 → 五道 Gate 发布）。研究主线是把 Scaling Law 延伸到运行阶段（运行时自进化）。

## 新人从这里开始（按顺序读）

1. **想跑起来** → [`docs/QUICKSTART.md`](docs/QUICKSTART.md)：环境前置、第一次跑（零依赖 mock 路径，已实测）、真实全链路、脚本矩阵、假桩指标警告、死代码清单。
2. **想看懂架构/代码** → 三篇人工架构导航（先读这三篇，胜过直接翻 8 万行源码）：
   - [`docs/api/evo_agent_baseline_overview.md`](docs/api/evo_agent_baseline_overview.md) —— 认知/底线/进化 + 评测
   - [`docs/api/workflow_engine_overview.md`](docs/api/workflow_engine_overview.md) —— W0/W1/W2 数据生成 + 法规投影
   - [`docs/api/research_kg_overview.md`](docs/api/research_kg_overview.md) —— 对照用的双源 KG-RAG 检索基线
3. **逐函数签名/字段** → [`docs/api/index.md`](docs/api/index.md)（AST 自动抽取，可重跑 `python scripts/gen_api_docs.py`）。
4. **跑实验/归档** → [`docs/experiments/README.md`](docs/experiments/README.md)。

## 四层架构 ↔ 代码包

| 层 | 职责 | 代码落点 |
|---|---|---|
| 感知层 | W0/W1 数据生成、W2 法规投影（产参考真值） | `src/workflow_engine/worldgen/` + `regulation_projection_*` |
| 认知层 | LLM 大脑 + 双源 KG-RAG 检索 | `src/evo_agent_baseline/agent/` `retrieval/` `kg/` `ingest/` |
| 底线层 | **确定性闭包验证**（`allow_stop` 唯一权威）+ blind 红线 | `src/evo_agent_baseline/closure/` + `agent/hooks.py` |
| 进化层 | trace → replay → 技能归纳/策略训练 → 五道 Gate | `src/evo_agent_baseline/evo/` `experiments/` |
| 评测（旁路） | 读 W2 真值离线阅卷（agent runtime 不得 import） | `src/evo_agent_baseline/eval/` |

## 目录速览

- `src/evo_agent_baseline/` `src/workflow_engine/` `src/research_kg/` —— **三个活包**（前两个是主线，research_kg 是对照基线）。
- `scripts/` —— 当前主线脚本（`run_*.py`、`gen_api_docs.py` 等），用途见 QUICKSTART 脚本矩阵。
- `docs/` —— 本项目技术文档（api / experiments / quickstart）。
- `experiments/` —— 实验产物 + 索引。

## ⚠️ 死代码勿动（早期 MVP 残留）

下面这些是第一版 MVP 遗留，**已不在主线、不进 API 文档、勿照其接线**（保留只为不断旧测试）：
- 源码包：`src/knowledge_base/`、`src/domain_tools/`、`src/workflow_engine/{nodes,graph,state}.py`（LangGraph MVP）
- 顶层入口脚本：`app.py`、`main.py`、`build_kg_mvp.py`、`inspect_db.py`、`verify_*.py`、`run_phase*.py`、`run_experiment_ab.py` 等
- 旧版自述：[`README_legacy_mvp.md`](README_legacy_mvp.md)（历史存档，**别照它跑**——它讲的 `app.py` / `streamlit` / `agent_mvp/` 那套已废弃）

> 判据：`evo_agent_baseline` 和 `scripts/` 对上述 MVP 包的 import = 0 处。
