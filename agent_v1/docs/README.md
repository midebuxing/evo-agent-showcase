# evo-agent v1 文档索引（docs/）

本目录是 evo-agent v1 的项目技术文档。下面按**新人导航顺序**串起来——从上往下读即可。
项目整体定位 + 四层架构 ↔ 代码包表，见仓库内 [`../README.md`](../README.md)。

## 按顺序读

1. **[`QUICKSTART.md`](QUICKSTART.md) —— 先跑起来**
   环境前置、PYTHONPATH、第一次跑（零依赖 mock 路径，已实测）、真实全链路四步、脚本矩阵、
   假桩指标警告、死代码清单。装好环境、跑通冒烟从这里开始。

2. **[`ARCHITECTURE.md`](ARCHITECTURE.md) —— 看全局**
   三包 × 四层 × W0/W1/W2 的端到端鸟瞰总图（mermaid）+ 一栋楼从数据生成到出报告/评测/
   进化反馈的完整链路文字说明。先建立全局图，再钻各包。

3. **[`api/evo_agent_baseline_overview.md`](api/evo_agent_baseline_overview.md) ·
   [`api/workflow_engine_overview.md`](api/workflow_engine_overview.md) ·
   [`api/research_kg_overview.md`](api/research_kg_overview.md) —— 看各包细节**
   三篇人工架构导航（认知/底线/进化+评测 · W0/W1/W2 数据生成+法规投影 · 对照用双源
   KG-RAG 基线）。先读这三篇，胜过直接翻 8 万行源码。

4. **逐函数 API 参考（不入库，用时现跑生成）**
   `python scripts/gen_api_docs.py` 从代码 AST 现生成 `api/index.md` + 三个包参考
   （每模块函数/类签名 + docstring + pydantic 字段表）。属构建产物、不进版本库。

5. **[`glossary.md`](glossary.md) —— 查黑话**
   术语速查：MBIS / closure / obligation 三态 / slot（两套含义消歧）/ family / W0-W2 /
   evo / blind 红线 / allow_stop / FactPack / RuleSlice / NormativeProjection /
   EVO_CLOSURE_QUERY_BUDGET 等。读源码被黑话淹没时回查这里。

6. **跑实验 + 读懂指标 → [`QUICKSTART.md`](QUICKSTART.md) §6**
   怎么安全跑出评测、读懂 verdict/coverage/threshold/closure 四组指标、run 目录产物速览。

7. **归档约定 → [`experiments/README.md`](experiments/README.md)**
   实验产物的统一归档约定：目录结构、`run_meta.json` 元数据、机器可读索引、新脚本怎么接入
   归档工厂（`run_registry`）。
