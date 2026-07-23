"""KG-RAG 检索查询字符串测试（spec §5.3 + §5.4）。

不依赖 Neo4j：只校验 Cypher 查询字符串结构、参数构造、blind 安全。
"""

from __future__ import annotations

from evo_agent_baseline.kg import queries


def test_fact_queries_are_match_only() -> None:
    """Fact KG-RAG 查询都是只读 MATCH，不写图。"""
    fact_queries = [
        queries.FACT_BUILDING_SHELL,
        queries.FACT_FRAGMENT_SUBGRAPH,
        queries.FACT_CONDITIONS_STATES,
        queries.FACT_SPECIALIZED_STATES,
        queries.FACT_MANIFESTATION_FLAGS,
        queries.FACT_FRAGMENT_MEASUREMENTS,
        queries.FACT_COMPONENT_MEASUREMENTS,
        queries.FACT_CONDITION_MEASUREMENTS,
        queries.FACT_SIDECAR_ENTRIES,
    ]
    for q in fact_queries:
        assert "MATCH" in q
        assert "CREATE" not in q
        assert "MERGE" not in q
        assert "DELETE" not in q
        assert "SET " not in q


def test_rule_queries_are_match_only() -> None:
    """Rule KG-RAG 查询都是只读。"""
    rule_queries = [
        queries.RULE_SLOT_DRIVEN_CARDS,
        queries.RULE_MEASURE_DRIVEN_CARDS,
        queries.RULE_APPLICABILITY_BUILDING_SCOPE,
        queries.RULE_APPLICABILITY_COMPONENT_SCOPE,
        queries.RULE_GRAPH_EXPANSION,
        queries.RULE_FAMILIES_BY_ID,
    ]
    for q in rule_queries:
        assert "CREATE" not in q
        assert "MERGE" not in q
        assert "DELETE" not in q


def test_no_w2_labels_in_any_query() -> None:
    """所有检索查询绝不 MATCH W2 label（evo-agent blind，spec §2.2.3）。"""
    all_queries = [
        getattr(queries, name) for name in queries.__all__
        if isinstance(getattr(queries, name), str)
    ]
    forbidden = ["NormativeProjection", "ProjectionFamilyEval", "ThresholdEval",
                 "ExpectedVerdict", "ReportBasisItem"]
    for q in all_queries:
        for label in forbidden:
            assert f":{label}" not in q, f"查询出现禁止 W2 label {label}"


def test_no_w2_property_names_in_queries() -> None:
    """检索查询不引用 W2 禁止属性名。"""
    all_queries = [
        getattr(queries, name) for name in queries.__all__
        if isinstance(getattr(queries, name), str)
    ]
    for q in all_queries:
        assert "expected_verdict" not in q
        assert "projection_id" not in q
        assert "coverage_status" not in q


def test_building_shell_query_structure() -> None:
    """§5.3.1 building shell 查询：MATCH Building<-HAS_BUILDING-World。"""
    q = queries.FACT_BUILDING_SHELL
    assert "MATCH (b:Building {building_id: $building_id})" in q
    assert "HAS_BUILDING" in q
    assert "RETURN" in q


def test_graph_expansion_returns_all_substructures() -> None:
    """§5.4.3 graph expansion 取回原嵌套 DTO 所需全部子结构。"""
    q = queries.RULE_GRAPH_EXPANSION
    for piece in ("SlotRef", "RuleThreshold", "EvidenceRequirement",
                   "ObligationNode", "ObligationEdge", "TriggerCondition",
                   "SourceQuote", "WorkflowArtifact", "ExceptionDefinition"):
        assert piece in q, f"expansion 查询缺 {piece}"
    assert "[:HAS_DEFINITION]" in q
    assert "collect(DISTINCT definition) AS definitions" in q


def test_param_builders() -> None:
    """参数构造函数返回正确结构。"""
    assert queries.building_params("BLD-1") == {"building_id": "BLD-1"}
    assert queries.slot_params(["s1", "s2"]) == {"slot_ids": ["s1", "s2"]}
    assert queries.measure_params(["m1"]) == {"measure_keys": ["m1"]}
    abp = queries.applicability_building_params("mbis", ["t1"])
    assert abp == {"regime": "mbis", "building_scope_tags": ["t1"]}
    assert queries.expansion_params(["rc1"]) == {"candidate_rule_card_ids": ["rc1"]}
    ftp = queries.fulltext_params("query", 20)
    assert ftp == {"query_text": "query", "limit": 20}
