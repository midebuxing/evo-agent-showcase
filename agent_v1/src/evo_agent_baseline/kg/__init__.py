"""evo-agent baseline Neo4j 知识图子包（spec §3 / §10）。

- neo4j_client.py —— Neo4j 连接客户端（读 config/kg.yaml）+ canonical_json
- queries.py      —— §5.3 / §5.4 的 Cypher 检索语句库

跨模块共享的 DTO 定义统一在 `evo_agent_baseline.contracts`；
扁平子图 → rule_card v2 原嵌套 DTO 的还原逻辑在 `retrieval.pack_builder`
（与 FactPack / RuleSlice 装配同处一模块，spec §5.4.3 / §5.5 / §5.6）。
"""

from evo_agent_baseline.kg import queries
from evo_agent_baseline.kg.neo4j_client import (
    Neo4jClient,
    canonical_json,
    is_neo4j_available,
    load_kg_config,
)

__all__ = [
    "queries",
    "Neo4jClient",
    "canonical_json",
    "is_neo4j_available",
    "load_kg_config",
]
