"""图元素规格：NodeSpec / EdgeSpec + MERGE Cypher 生成（spec §3.2 / §4.2.3）。

loader 的灌库逻辑分两段：
1. 纯转换段 —— parquet / JSON → `NodeSpec` / `EdgeSpec` 列表（不依赖 Neo4j，可单测）；
2. 写入段 —— `GraphBatch` → MERGE (cypher, params) → `Neo4jClient.write_many`。

这样 spec §3 的「parquet → 图节点转换逻辑」可在没有活体 Neo4j 时全量单测，
符合任务要求。

spec §4.2.3：所有 loader 用 `MERGE` 幂等写入，禁止 `CREATE`。
spec §3.2：节点 label PascalCase，关系 type UPPER_SNAKE_CASE，属性 snake_case。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from evo_agent_baseline.ingest.guard import (
    FORBIDDEN_AGENT_LABELS,
    FORBIDDEN_AGENT_PROPERTIES,
    SecurityError,
)


@dataclass(frozen=True)
class NodeSpec:
    """一个图节点的规格。

    Attributes:
        label: 节点 label（PascalCase）。
        key_prop: 主键属性名（用于 MERGE 的匹配键）。
        key_value: 主键值。
        props: 其余属性（不含主键；MERGE 后 SET）。
    """

    label: str
    key_prop: str
    key_value: Any
    props: Dict[str, Any] = field(default_factory=dict)

    def all_props(self) -> Dict[str, Any]:
        """返回含主键的完整属性 dict。"""
        merged = dict(self.props)
        merged[self.key_prop] = self.key_value
        return merged


@dataclass(frozen=True)
class EdgeSpec:
    """一条图关系的规格。

    Attributes:
        start_label: 起点 label。
        start_key_prop: 起点主键属性名。
        start_key_value: 起点主键值。
        rel_type: 关系 type（UPPER_SNAKE_CASE）。
        end_label: 终点 label。
        end_key_prop: 终点主键属性名。
        end_key_value: 终点主键值。
        props: 关系属性（可空）。
    """

    start_label: str
    start_key_prop: str
    start_key_value: Any
    rel_type: str
    end_label: str
    end_key_prop: str
    end_key_value: Any
    props: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphBatch:
    """一批待写入的节点 + 关系。

    loader 的纯转换段产出 `GraphBatch`；写入段把它编译为 MERGE 语句。
    """

    nodes: List[NodeSpec] = field(default_factory=list)
    edges: List[EdgeSpec] = field(default_factory=list)

    def add_node(self, node: NodeSpec) -> None:
        """追加一个节点。"""
        self.nodes.append(node)

    def add_edge(self, edge: EdgeSpec) -> None:
        """追加一条关系。"""
        self.edges.append(edge)

    def extend(self, other: "GraphBatch") -> None:
        """并入另一个 batch。"""
        self.nodes.extend(other.nodes)
        self.edges.extend(other.edges)

    def node_labels(self) -> List[str]:
        """返回 batch 内出现的全部 label（去重，排序）。"""
        return sorted({n.label for n in self.nodes})


def assert_node_blind_safe(node: NodeSpec) -> NodeSpec:
    """对 NodeSpec 做 evo-agent blind 检查（spec §2.2.3 + §4.7 G-002）。

    label 命中禁止 label、或属性 key 命中禁止属性名 —— 立即 hard fail。
    这是写图前最后一道防线。

    Args:
        node: 待检查节点。

    Returns:
        原 node。

    Raises:
        SecurityError: label 或属性命中禁止清单。
    """
    if node.label in FORBIDDEN_AGENT_LABELS:
        raise SecurityError(
            f"G-002: forbidden W2 label :{node.label} in agent KG"
        )
    leaked = set(node.all_props().keys()) & FORBIDDEN_AGENT_PROPERTIES
    if leaked:
        raise SecurityError(
            f"G-002: node :{node.label} carries forbidden W2 property {sorted(leaked)}"
        )
    return node


def node_merge_cypher(node: NodeSpec) -> Tuple[str, Dict[str, Any]]:
    """把一个 NodeSpec 编译为 MERGE Cypher + 参数（spec §4.2.3）。

    生成形如：
        MERGE (n:Label {key_prop: $key}) SET n += $props

    Args:
        node: 节点规格。

    Returns:
        (cypher, params) 二元组。
    """
    assert_node_blind_safe(node)
    cypher = (
        f"MERGE (n:{node.label} {{{node.key_prop}: $key}}) "
        f"SET n += $props"
    )
    params = {"key": node.key_value, "props": node.all_props()}
    return cypher, params


def edge_merge_cypher(edge: EdgeSpec) -> Tuple[str, Dict[str, Any]]:
    """把一条 EdgeSpec 编译为 MERGE Cypher + 参数（spec §4.2.3）。

    生成形如：
        MATCH (a:StartLabel {start_key: $start})
        MATCH (b:EndLabel {end_key: $end})
        MERGE (a)-[r:REL_TYPE]->(b) SET r += $props

    用 MATCH 而非 MERGE 两端节点：节点应已由对应 NodeSpec 先建好；
    若端点不存在，关系不建（spec 多处「找不到则记 warning 不建悬空节点」口径）。

    Args:
        edge: 关系规格。

    Returns:
        (cypher, params) 二元组。
    """
    leaked = set(edge.props.keys()) & FORBIDDEN_AGENT_PROPERTIES
    if leaked:
        raise SecurityError(
            f"G-002: relation :{edge.rel_type} carries forbidden W2 property {sorted(leaked)}"
        )
    cypher = (
        f"MATCH (a:{edge.start_label} {{{edge.start_key_prop}: $start}}) "
        f"MATCH (b:{edge.end_label} {{{edge.end_key_prop}: $end}}) "
        f"MERGE (a)-[r:{edge.rel_type}]->(b) "
        f"SET r += $props"
    )
    params = {
        "start": edge.start_key_value,
        "end": edge.end_key_value,
        "props": dict(edge.props),
    }
    return cypher, params


def compile_batch(batch: GraphBatch) -> List[Tuple[str, Dict[str, Any]]]:
    """把整个 GraphBatch 编译为 (cypher, params) 列表，节点在前关系在后。

    节点先于关系保证 `edge_merge_cypher` 的 MATCH 能命中端点。

    Args:
        batch: 待编译批次。

    Returns:
        (cypher, params) 列表，可直接喂 `Neo4jClient.write_many`。
    """
    statements: List[Tuple[str, Dict[str, Any]]] = []
    for node in batch.nodes:
        statements.append(node_merge_cypher(node))
    for edge in batch.edges:
        statements.append(edge_merge_cypher(edge))
    return statements


__all__ = [
    "NodeSpec",
    "EdgeSpec",
    "GraphBatch",
    "assert_node_blind_safe",
    "node_merge_cypher",
    "edge_merge_cypher",
    "compile_batch",
]
