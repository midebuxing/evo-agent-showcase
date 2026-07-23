"""cypher_schema DDL 生成测试（spec §3.7）。

不依赖 Neo4j：只校验 DDL 字符串清单完整、幂等、命名规范。
"""

from __future__ import annotations

from evo_agent_baseline.ingest import cypher_schema


def test_constraint_count_matches_spec() -> None:
    """spec §3.7.1 共 26 条唯一性约束。"""
    assert len(cypher_schema.CONSTRAINTS) == 26


def test_btree_index_count_matches_spec() -> None:
    """spec §3.7.2 共 17 条 B 树索引。"""
    assert len(cypher_schema.BTREE_INDEXES) == 17


def test_fulltext_index_count_matches_spec() -> None:
    """spec §3.7.3 共 3 条全文索引。"""
    assert len(cypher_schema.FULLTEXT_INDEXES) == 3


def test_all_ddl_idempotent() -> None:
    """所有 schema DDL 都带 IF NOT EXISTS（spec §4.2.3 幂等要求）。"""
    for stmt in cypher_schema.all_schema_statements():
        assert "IF NOT EXISTS" in stmt, f"DDL 缺 IF NOT EXISTS: {stmt}"


def test_constraints_are_create_constraint() -> None:
    """约束语句以 CREATE CONSTRAINT 开头。"""
    for stmt in cypher_schema.CONSTRAINTS:
        assert stmt.startswith("CREATE CONSTRAINT ")


def test_fulltext_uses_on_each() -> None:
    """全文索引用 ON EACH 语法。"""
    for stmt in cypher_schema.FULLTEXT_INDEXES:
        assert "FULLTEXT INDEX" in stmt
        assert "ON EACH" in stmt


def test_all_schema_statements_total() -> None:
    """all_schema_statements 默认 = 约束 + B 树 + 全文（不含向量索引）。"""
    total = cypher_schema.all_schema_statements()
    assert len(total) == 26 + 17 + 3
    # 默认不含向量索引。
    assert all("VECTOR INDEX" not in s for s in total)


def test_vector_index_optional() -> None:
    """include_vector_index=True 时附加 1 条向量索引（spec §3.7.4）。"""
    with_vector = cypher_schema.all_schema_statements(include_vector_index=True)
    assert len(with_vector) == 26 + 17 + 3 + 1
    assert any("VECTOR INDEX rule_card_embedding_idx" in s for s in with_vector)


def test_no_forbidden_w2_labels_in_schema() -> None:
    """schema DDL 不得给任何 W2 label 建约束 / 索引（spec §2.2.3）。"""
    forbidden = ["NormativeProjection", "ProjectionFamilyEval", "ExpectedVerdict"]
    for stmt in cypher_schema.all_schema_statements(include_vector_index=True):
        for label in forbidden:
            assert f":{label}" not in stmt, f"schema 出现禁止 W2 label {label}: {stmt}"
