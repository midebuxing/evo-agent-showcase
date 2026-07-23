"""regulation loader 测试：markdown → RegulationClause（spec §4.4 + §3.4.1）。

不依赖 Neo4j。测 markdown 切分、section_id 抽取、文档/clause 节点。
"""

from __future__ import annotations

from pathlib import Path

from evo_agent_baseline.ingest import regulation_loader


# ===========================================================================
# §4.4.1 section_id 抽取
# ===========================================================================
def test_extract_section_id_numeric() -> None:
    """标题含数字章节号 → 抽数字。"""
    assert regulation_loader.extract_section_id("2.1.3 涵蓋範圍", 0) == "2.1.3"
    assert regulation_loader.extract_section_id("3 檢驗及評估", 0) == "3"


def test_extract_section_id_numeric_with_paren() -> None:
    """标题含括号后缀 → 一并抽。"""
    assert regulation_loader.extract_section_id("2.1.3(o) 提交", 0) == "2.1.3(o)"


def test_extract_section_id_paren_only() -> None:
    """纯括号编号标题 → 带序号保唯一。"""
    sid = regulation_loader.extract_section_id("(C) 覆蓋層", 5)
    assert sid.startswith("(C)")
    assert "5" in sid


def test_extract_section_id_slug_fallback() -> None:
    """无章节号 → slug + 序号兜底。"""
    sid = regulation_loader.extract_section_id("前言", 0)
    assert "#0" in sid


# ===========================================================================
# §4.4.1 markdown 切分
# ===========================================================================
def test_split_markdown_clauses_basic() -> None:
    """基础切分：每个标题一个 clause，text 到下一标题前。"""
    md = "\n".join([
        "# Doc Title",
        "intro text",
        "## 1. Section One",
        "body of section one",
        "## 2. Section Two",
        "body of section two",
    ])
    clauses = regulation_loader.split_markdown_clauses(md, "DOC")
    assert len(clauses) == 3
    # H1。
    assert clauses[0].level == 1
    assert clauses[0].clause_id == "DOC::doc_title#0" or clauses[0].text == "intro text"
    # 第二个 clause 是 "1. Section One"。
    sec1 = clauses[1]
    assert sec1.section_id == "1"
    assert sec1.text == "body of section one"
    assert sec1.level == 2


def test_split_markdown_clauses_parent_hierarchy() -> None:
    """parent_clause_id 由标题层级推出。"""
    md = "\n".join([
        "# 3 Top",
        "",
        "## 3.1 Child",
        "child body",
        "### 3.1.1 Grandchild",
        "grandchild body",
    ])
    clauses = regulation_loader.split_markdown_clauses(md, "DOC")
    by_section = {c.section_id: c for c in clauses}
    # 3.1 的 parent 是 3。
    assert by_section["3.1"].parent_clause_id == by_section["3"].clause_id
    # 3.1.1 的 parent 是 3.1。
    assert by_section["3.1.1"].parent_clause_id == by_section["3.1"].clause_id


def test_split_markdown_duplicate_section_ids() -> None:
    """同一文档内重复 section_id → 去重保唯一。"""
    md = "\n".join([
        "## (A) 概要",
        "first",
        "## (A) 概要",
        "second",
    ])
    clauses = regulation_loader.split_markdown_clauses(md, "DOC")
    ids = [c.clause_id for c in clauses]
    assert len(ids) == len(set(ids)), "clause_id 必须唯一"


def test_sha256_text_stable() -> None:
    """text_hash 对同输入稳定。"""
    h1 = regulation_loader.sha256_text("hello")
    h2 = regulation_loader.sha256_text("hello")
    assert h1 == h2
    assert len(h1) == 64


def test_build_clause_node_fields() -> None:
    """RegulationClause 节点字段齐全。"""
    clause = regulation_loader.ClauseRecord(
        clause_id="DOC::2.1", section_id="2.1", document_id="DOC",
        heading="Section", level=2, text="body",
        text_hash=regulation_loader.sha256_text("body"),
    )
    node = regulation_loader.build_clause_node(clause)
    assert node.label == "RegulationClause"
    assert node.props["section_id"] == "2.1"
    assert node.props["level"] == 2
    assert node.props["page_start"] is None  # markdown 切分无页码


# ===========================================================================
# 端到端：真实法规 markdown
# ===========================================================================
def test_build_regulation_graph_real_mbis(regulation_markdown_dir: Path) -> None:
    """真实 MBIS_CoP_2023.md 端到端切分。"""
    path = regulation_markdown_dir / "MBIS_CoP_2023.md"
    result = regulation_loader.build_regulation_graph(path, "2026-05-23T00:00:00Z")
    assert result.document_ids == ["MBIS_CoP_2023"]
    assert result.clause_count > 0
    labels = {n.label for n in result.batch.nodes}
    assert "RegulationDocument" in labels
    assert "RegulationClause" in labels


def test_build_regulation_graph_dir_loads_four_docs(regulation_markdown_dir: Path) -> None:
    """真实法规目录加载 4 份已知法规（spec §4.4.2）。"""
    result = regulation_loader.build_regulation_graph_dir(
        regulation_markdown_dir, "2026-05-23T00:00:00Z"
    )
    assert set(result.document_ids) == {
        "MBIS_CoP_2023", "MBIS_MWIS_CoP_2012_Legacy",
        "MBIS_MWIS_Operation_Note", "PNBI10_CoP_2023",
    }
    # NEXT_CLAUSE / PARENT_OF / HAS_CLAUSE 边都应出现。
    rel_types = {e.rel_type for e in result.batch.edges}
    assert "HAS_CLAUSE" in rel_types
    assert "NEXT_CLAUSE" in rel_types
    assert "PARENT_OF" in rel_types
