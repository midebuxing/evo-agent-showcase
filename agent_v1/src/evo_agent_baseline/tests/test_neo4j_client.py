"""Neo4j 客户端测试（spec §10 kg/neo4j_client.py）。

不依赖 Neo4j：测 canonical_json、config 加载、bolt URI 解析、可用性探测。
建真实连接的测试需活体 Neo4j —— 用 neo4j_required 标记 skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_agent_baseline.kg import neo4j_client
from evo_agent_baseline.tests.conftest import neo4j_required


# ===========================================================================
# canonical_json
# ===========================================================================
def test_canonical_json_sorts_keys() -> None:
    """canonical_json key 排序、紧凑分隔符。"""
    assert neo4j_client.canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_canonical_json_null() -> None:
    """None → 字符串 "null"（spec §3.4.3 threshold_value_json 口径）。"""
    assert neo4j_client.canonical_json(None) == "null"


def test_canonical_json_nested_stable() -> None:
    """嵌套结构序列化稳定可复现。"""
    value = {"z": [3, 1], "a": {"y": 2, "x": 1}}
    out1 = neo4j_client.canonical_json(value)
    out2 = neo4j_client.canonical_json(value)
    assert out1 == out2
    assert out1 == '{"a":{"x":1,"y":2},"z":[3,1]}'


def test_canonical_json_unicode_preserved() -> None:
    """中文不转义（ensure_ascii=False）。"""
    assert "检验" in neo4j_client.canonical_json({"k": "检验"})


# ===========================================================================
# config 加载
# ===========================================================================
def test_load_kg_config_default() -> None:
    """默认加载 config/kg.yaml。"""
    config = neo4j_client.load_kg_config()
    assert "neo4j" in config
    assert config["neo4j"]["agent_database"] == "evo_agent_baseline"
    # spec D-001：agent / eval 两库分离。
    assert config["neo4j"]["eval_database"] == "evo_eval_truth"


def test_kg_config_default_path_exists() -> None:
    """DEFAULT_KG_CONFIG_PATH 指向真实文件。"""
    assert neo4j_client.DEFAULT_KG_CONFIG_PATH.is_file()


# ===========================================================================
# bolt URI 解析
# ===========================================================================
def test_parse_bolt_host_port() -> None:
    """bolt URI 解析 host + port。"""
    assert neo4j_client.parse_bolt_host_port("bolt://localhost:7687") == ("localhost", 7687)
    assert neo4j_client.parse_bolt_host_port("neo4j://host:7999") == ("host", 7999)
    # 无端口 → 默认 7687。
    assert neo4j_client.parse_bolt_host_port("bolt://localhost") == ("localhost", 7687)


def test_is_neo4j_available_returns_bool() -> None:
    """is_neo4j_available 返回 bool（不论 Neo4j 是否启动）。"""
    result = neo4j_client.is_neo4j_available()
    assert isinstance(result, bool)


# ===========================================================================
# 需活体 Neo4j 的测试
# ===========================================================================
@neo4j_required
def test_neo4j_client_connect() -> None:
    """活体 Neo4j：能建连接并跑 RETURN 1（需 7687 通 + 凭据）。"""
    # 注意：本测试仅在 Neo4j 启动时运行；凭据从环境/默认取。
    # baseline 阶段 Neo4j 未启动，本测试默认 skip。
    pytest.skip("需要配置 Neo4j 凭据；端口通但 baseline 未提供测试库凭据")
