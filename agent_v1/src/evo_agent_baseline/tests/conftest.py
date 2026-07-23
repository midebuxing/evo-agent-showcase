"""evo-agent baseline 数据层测试公用 fixture（spec §11）。

提供：
- 真实数据源路径 fixture（worldgen parquet seed / 法规 markdown / rule_card v2）；
- Neo4j 可用性判定 —— 7687 不通则相关测试 skip（任务要求）。

不依赖 Neo4j 的测试覆盖：parquet→图节点转换、guard 白/黑名单判定、
Cypher DDL/查询字符串生成、FactPack/RuleSlice DTO 组装。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_agent_baseline.kg.neo4j_client import is_neo4j_available

# 仓库根 = 本文件向上 6 级：tests/ → evo_agent_baseline/ → src/ → agent_v1/ → 5993/
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENT_V1 = _REPO_ROOT / "agent_v1"


# Neo4j 未启动时跳过的标记（任务要求）。
neo4j_required = pytest.mark.skipif(
    not is_neo4j_available(),
    reason="Neo4j bolt 7687 不可连——跳过依赖活体 Neo4j 的测试",
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """仓库根目录。"""
    return _REPO_ROOT


@pytest.fixture(scope="session")
def worldgen_seed_dir() -> Path:
    """一个 worldgen parquet seed 目录（gen_seed_42）。"""
    path = (
        _AGENT_V1 / "experiments" / "qa_reports"
        / "release_batch_post_W0005_full_align" / "gen_seed_42"
    )
    if not path.is_dir():
        pytest.skip(f"worldgen seed dir not found: {path}")
    return path


@pytest.fixture(scope="session")
def regulation_markdown_dir() -> Path:
    """法规原文 markdown 目录。"""
    path = _AGENT_V1 / "regulations" / "markdown"
    if not path.is_dir():
        pytest.skip(f"regulation markdown dir not found: {path}")
    return path


@pytest.fixture(scope="session")
def rulecard_dir() -> Path:
    """rule_card v2 目录。"""
    path = _AGENT_V1 / "regulations" / "rulecard_v2" / "mbis_cop_2023"
    if not path.is_dir():
        pytest.skip(f"rulecard v2 dir not found: {path}")
    return path
