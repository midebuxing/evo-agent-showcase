"""evo-agent baseline 灌库子包（spec §4）。

各 loader 把固定上游产物灌入 Neo4j agent KG：
- fact_loader.py        —— W0/W1 worldgen parquet → 事实侧 KG（spec §4.2 / §3.3）
- sidecar_loader.py     —— SidecarRuntimeBundle → sidecar 节点（spec §4.2.8 / §3.3.5）
- regulation_loader.py  —— 法规原文 markdown → RegulationClause（spec §4.4 / §3.4.1）
- rulecard_loader.py    —— rule_card v2 → 结构化子节点（spec §4.3 / §3.4）
- skill_loader.py       —— 4 个 baseline 手工 seed Skill（spec §4.5 / §3.5）
- guard.py              —— loader 启动守卫 + 白/黑名单 + 质量门（spec §2.2 / §4.7）
- cypher_schema.py      —— Neo4j constraints / indexes / fulltext（spec §3.7）

内部支撑模块（不对应 spec 单一章节）：
- _common.py            —— parquet 读取、值规整、ID 工具
- _graphspec.py         —— NodeSpec / EdgeSpec / GraphBatch + MERGE Cypher 生成

eval_truth_loader.py（spec §4.6）属 evaluator-only，不在数据层子代理范围。
"""

from evo_agent_baseline.ingest import cypher_schema, guard
from evo_agent_baseline.ingest.fact_loader import build_fact_graph, load_fact_kg
from evo_agent_baseline.ingest.regulation_loader import (
    build_regulation_graph_dir,
    load_regulation_kg,
)
from evo_agent_baseline.ingest.rulecard_loader import build_rulecard_graph, load_rulecard_kg
from evo_agent_baseline.ingest.sidecar_loader import build_sidecar_graph, load_sidecar_kg
from evo_agent_baseline.ingest.skill_loader import build_skill_graph, load_skill_kg

__all__ = [
    "cypher_schema",
    "guard",
    "build_fact_graph",
    "load_fact_kg",
    "build_sidecar_graph",
    "load_sidecar_kg",
    "build_regulation_graph_dir",
    "load_regulation_kg",
    "build_rulecard_graph",
    "load_rulecard_kg",
    "build_skill_graph",
    "load_skill_kg",
]
