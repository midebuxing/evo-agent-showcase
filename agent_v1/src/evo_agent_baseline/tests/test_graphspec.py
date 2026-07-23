"""图元素规格测试：NodeSpec / EdgeSpec → MERGE Cypher（spec §3.2 + §4.2.3）。

不依赖 Neo4j。验证 MERGE 语句生成、blind 检查、批编译顺序。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.ingest._graphspec import (
    EdgeSpec,
    GraphBatch,
    NodeSpec,
    compile_batch,
    edge_merge_cypher,
    node_merge_cypher,
)
from evo_agent_baseline.ingest.guard import SecurityError


def test_node_all_props_includes_key() -> None:
    """NodeSpec.all_props 含主键。"""
    node = NodeSpec("Building", "building_id", "BLD-1", {"age_years": 50})
    props = node.all_props()
    assert props["building_id"] == "BLD-1"
    assert props["age_years"] == 50


def test_node_merge_cypher_uses_merge() -> None:
    """节点编译为 MERGE 语句（spec §4.2.3 禁止 CREATE）。"""
    node = NodeSpec("World", "world_id", "WB-1", {"random_seed": 42})
    cypher, params = node_merge_cypher(node)
    assert cypher.startswith("MERGE (n:World {world_id: $key})")
    assert "SET n += $props" in cypher
    assert "CREATE " not in cypher
    assert params["key"] == "WB-1"
    assert params["props"]["world_id"] == "WB-1"


def test_edge_merge_cypher_uses_match_then_merge() -> None:
    """关系编译为 MATCH 端点 + MERGE 关系。"""
    edge = EdgeSpec(
        "World", "world_id", "WB-1",
        "HAS_BUILDING",
        "Building", "building_id", "BLD-1",
    )
    cypher, params = edge_merge_cypher(edge)
    assert "MATCH (a:World {world_id: $start})" in cypher
    assert "MATCH (b:Building {building_id: $end})" in cypher
    assert "MERGE (a)-[r:HAS_BUILDING]->(b)" in cypher
    assert params["start"] == "WB-1"
    assert params["end"] == "BLD-1"


def test_node_blind_check_rejects_forbidden_label() -> None:
    """禁止 W2 label 节点 → SecurityError。"""
    node = NodeSpec("NormativeProjection", "projection_id", "P-1", {})
    with pytest.raises(SecurityError):
        node_merge_cypher(node)


def test_node_blind_check_rejects_forbidden_property() -> None:
    """禁止属性名 → SecurityError。"""
    node = NodeSpec("Building", "building_id", "BLD-1", {"expected_verdict": "compliant"})
    with pytest.raises(SecurityError):
        node_merge_cypher(node)


def test_edge_blind_check_rejects_forbidden_property() -> None:
    """关系属性含禁止属性名 → SecurityError。"""
    edge = EdgeSpec(
        "Building", "building_id", "BLD-1",
        "HAS_X",
        "Component", "component_id", "CMP-1",
        {"projection_id": "P-1"},
    )
    with pytest.raises(SecurityError):
        edge_merge_cypher(edge)


def test_compile_batch_nodes_before_edges() -> None:
    """compile_batch 把节点排在关系前（保证 edge MATCH 命中端点）。"""
    batch = GraphBatch()
    batch.add_edge(EdgeSpec(
        "World", "world_id", "WB-1", "HAS_BUILDING",
        "Building", "building_id", "BLD-1",
    ))
    batch.add_node(NodeSpec("World", "world_id", "WB-1", {}))
    batch.add_node(NodeSpec("Building", "building_id", "BLD-1", {}))
    statements = compile_batch(batch)
    # 前两条是 MERGE 节点，最后一条是关系。
    assert statements[0][0].startswith("MERGE (n:")
    assert statements[1][0].startswith("MERGE (n:")
    assert "MERGE (a)-[r:HAS_BUILDING]" in statements[2][0]


def test_graph_batch_extend() -> None:
    """GraphBatch.extend 合并节点 + 关系。"""
    a = GraphBatch()
    a.add_node(NodeSpec("World", "world_id", "WB-1", {}))
    b = GraphBatch()
    b.add_node(NodeSpec("Building", "building_id", "BLD-1", {}))
    a.extend(b)
    assert len(a.nodes) == 2
    assert a.node_labels() == ["Building", "World"]
