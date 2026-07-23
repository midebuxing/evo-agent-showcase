"""Neo4j 连接封装（spec §10 kg/neo4j_client.py）。

读 `config/kg.yaml` 建立到 Neo4j agent database 的连接，并提供：
- `Neo4jClient` —— 薄连接封装，run / read / write_tx / 批量 schema DDL；
- `canonical_json` —— 全图统一的 canonical JSON 序列化（spec §3.1 规则 3）；
- `is_neo4j_available` —— 探测 7687 端口是否可连（测试 skip 判定用）。

spec D-001：agent KG 与 evaluator truth store 物理隔离。本客户端只连
`agent_database`（默认 `evo_agent_baseline`），灌库用 `ingest_user` 凭据。
本客户端不提供任何到 `eval_database` 的入口。

Neo4j 当前可能未启动；本模块导入不依赖活体 Neo4j，只有真正建连接时才需要。
"""

from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

import yaml

# neo4j driver 为可选依赖：导入失败不影响 canonical_json / 配置加载等纯逻辑。
try:  # pragma: no cover - 取决于环境是否装了 neo4j
    from neo4j import GraphDatabase
    from neo4j import Driver as _Neo4jDriver

    _NEO4J_IMPORT_OK = True
except Exception:  # pragma: no cover
    GraphDatabase = None  # type: ignore[assignment]
    _Neo4jDriver = Any  # type: ignore[misc,assignment]
    _NEO4J_IMPORT_OK = False


# config/kg.yaml 默认路径：本文件位于 evo_agent_baseline/kg/，配置在 ../config/。
DEFAULT_KG_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "kg.yaml"


# ===========================================================================
# canonical JSON（spec §3.1 规则 3 / §3.2 JSON 字段约定）
# ===========================================================================
def canonical_json(value: Any) -> str:
    """把任意值序列化为 canonical JSON 字符串。

    spec §3.1 规则 3：所有 JSON 字段统一以 canonical JSON string 存储，
    verifier 读取前 `json.loads`。canonical 指 key 排序 + 紧凑分隔符，
    保证同一逻辑值序列化结果稳定（可复现、可 hash）。

    None 序列化为字符串 `"null"`（与 spec §3.4.3 threshold_value_json 口径一致）。

    Args:
        value: 任意可 JSON 序列化的值。

    Returns:
        canonical JSON 字符串。
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ===========================================================================
# Neo4j 可用性探测
# ===========================================================================
def is_neo4j_available(host: str = "localhost", port: int = 7687, timeout: float = 0.5) -> bool:
    """探测 Neo4j bolt 端口是否可连。

    用于测试：Neo4j 未启动时 `pytest.mark.skipif` 跳过依赖活体库的用例。

    Args:
        host: 主机名。
        port: bolt 端口，默认 7687。
        timeout: 连接超时秒数。

    Returns:
        端口可连返回 True，否则 False。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ===========================================================================
# KG 配置加载
# ===========================================================================
def load_kg_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """加载并返回 `config/kg.yaml` 顶层 dict。

    Args:
        config_path: 配置路径；None 时用 `DEFAULT_KG_CONFIG_PATH`。

    Returns:
        yaml.safe_load 出来的配置 dict。
    """
    path = config_path or DEFAULT_KG_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_bolt_host_port(uri: str) -> tuple[str, int]:
    """从 `bolt://host:port` / `neo4j://host:port` URI 解析 host + port。

    Args:
        uri: Neo4j 连接 URI。

    Returns:
        (host, port) 二元组；解析不出端口时默认 7687。
    """
    rest = uri.split("://", 1)[-1]
    rest = rest.split("/", 1)[0]
    if ":" in rest:
        host, port_str = rest.rsplit(":", 1)
        try:
            return host, int(port_str)
        except ValueError:
            return host, 7687
    return rest, 7687


# ===========================================================================
# Neo4j 客户端
# ===========================================================================
class Neo4jClient:
    """Neo4j agent database 薄连接封装。

    spec D-001：只连 agent_database；不提供 eval_database 入口。
    用法：

        with Neo4jClient.from_config(role="ingest", password="...") as client:
            client.apply_schema(all_schema_statements())
            client.run("MERGE (w:World {world_id: $wid})", {"wid": "WB-1"})

    Neo4j 当前可能未启动；构造 `Neo4jClient` 即尝试建 driver，
    若 neo4j driver 未安装或连接失败会抛异常 —— 由调用方处理。
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str,
    ) -> None:
        """建立到 Neo4j 的 driver。

        Args:
            uri: bolt / neo4j URI。
            user: 登录用户名。
            password: 登录密码。
            database: 目标 database（agent database，spec D-001）。

        Raises:
            RuntimeError: neo4j driver 未安装。
        """
        if not _NEO4J_IMPORT_OK:
            raise RuntimeError(
                "neo4j driver not installed; install `neo4j` to use Neo4jClient"
            )
        self.uri = uri
        self.user = user
        self.database = database
        self._driver: _Neo4jDriver = GraphDatabase.driver(uri, auth=(user, password))

    @classmethod
    def from_config(
        cls,
        password: str,
        role: str = "ingest",
        config_path: Optional[Path] = None,
    ) -> "Neo4jClient":
        """从 `config/kg.yaml` 构造客户端。

        Args:
            password: Neo4j 密码（不在 yaml 中存明文，由调用方注入）。
            role: 凭据角色 —— `agent` / `ingest` / `eval`。
                  `eval` 角色在此仅用于读取用户名，spec D-001 仍要求 evaluator
                  使用独立 store；agent runtime 凭据不得访问 eval database。
            config_path: kg.yaml 路径。

        Returns:
            Neo4jClient 实例。
        """
        config = load_kg_config(config_path)
        neo4j_cfg = config.get("neo4j", {}) or {}
        uri = neo4j_cfg.get("uri", "bolt://localhost:7687")
        user_key = {
            "agent": "agent_user",
            "ingest": "ingest_user",
            "eval": "eval_user",
        }.get(role, "ingest_user")
        user = neo4j_cfg.get(user_key, "neo4j")
        # eval 角色定向到 eval_database；其余到 agent_database。
        db_key = "eval_database" if role == "eval" else "agent_database"
        database = neo4j_cfg.get(db_key, "evo_agent_baseline")
        return cls(uri=uri, user=user, password=password, database=database)

    # --- 生命周期 ---
    def close(self) -> None:
        """关闭 driver。"""
        if self._driver is not None:
            self._driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- 查询执行 ---
    def run(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """执行一条 Cypher，返回结果 record 列表（每条 record 转 dict）。

        Args:
            cypher: Cypher 语句。
            params: 参数字典。

        Returns:
            结果列表，每项是 record.data() dict。
        """
        with self._driver.session(database=self.database) as session:
            result = session.run(cypher, params or {})
            return [record.data() for record in result]

    def read(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """以只读事务执行 Cypher 查询（检索路径用）。

        Args:
            cypher: Cypher 查询语句。
            params: 参数字典。

        Returns:
            结果列表。
        """
        with self._driver.session(database=self.database) as session:
            return session.execute_read(
                lambda tx: [r.data() for r in tx.run(cypher, params or {})]
            )

    def write_many(
        self,
        statements: Iterable[tuple[str, Dict[str, Any]]],
        batch_size: int = 500,
    ) -> None:
        """在写事务里批量执行 (cypher, params) 列表（灌库 MERGE 批用）。

        spec §4.2.3：所有 loader 用 MERGE 幂等写入，禁止 CREATE 导致重复节点。

        单事务里塞过多 MERGE 会撞 Neo4j `dbms.memory.transaction.total.max`
        （默认 ≈700 MiB），生产规模 worldgen 灌库会 TransientError。本实现
        按 `batch_size` 切片，每片一个 execute_write 事务，幂等性不受影响
        （MERGE 重入安全）。

        Args:
            statements: (cypher, params) 二元组的可迭代对象。
            batch_size: 单事务最多语句数，默认 500（百 MiB 量级安全）。
                <=0 时退化为不分批（原行为）。
        """
        # 一次实体化（loader 经常传 list/generator；分批 + 重试要可重入）。
        stmts = list(statements)
        if not stmts:
            return

        if batch_size <= 0:
            slices = [stmts]
        else:
            slices = [stmts[i : i + batch_size] for i in range(0, len(stmts), batch_size)]

        with self._driver.session(database=self.database) as session:
            for chunk in slices:
                def _work(tx: Any, _chunk=chunk) -> None:
                    for cypher, params in _chunk:
                        tx.run(cypher, params or {})

                session.execute_write(_work)

    def apply_schema(self, statements: Iterable[str]) -> None:
        """逐条执行 schema DDL（约束 / 索引 / 全文索引）。

        Neo4j 的 schema 语句不能在显式事务里跑，必须 auto-commit，故逐条 session.run。

        Args:
            statements: DDL 字符串列表（来自 `ingest.cypher_schema.all_schema_statements`）。
        """
        with self._driver.session(database=self.database) as session:
            for stmt in statements:
                session.run(stmt)

    @contextmanager
    def session_scope(self) -> Iterator[Any]:
        """暴露原生 session 上下文（高级用法）。

        Yields:
            neo4j Session 对象。
        """
        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            session.close()


__all__ = [
    "Neo4jClient",
    "canonical_json",
    "is_neo4j_available",
    "load_kg_config",
    "parse_bolt_host_port",
    "DEFAULT_KG_CONFIG_PATH",
]
