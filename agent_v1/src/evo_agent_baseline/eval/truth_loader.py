"""W2 参考真值加载器（spec §8.2 reference_truth）。

evaluator 读 W2 `NormativeProjection` 参考真值是评测程序的本职（spec §8.1）：
evaluator 是独立阅卷程序、不是 agent，因此读 W2 真值不违反 evo-agent blind。
agent runtime 不得读取本模块的任何输入或产物（spec §8.6 / evaluator.yaml
`readable_by_agent: false`）。

输入 5 张 parquet（spec §8.2 reference_truth + evaluator.yaml `input_tables`）：
- `normative_projection_meta.parquet`  —— bundle / 版本元数据（1 行）
- `projections.parquet`                —— 每条 projection 的 expected_verdict / 必需 slot / severity
- `matched_families.parquet`           —— projection × family 的 verdict / applicability
- `threshold_evaluations.parquet`      —— 阈值比较真值（operator / 阈值 / 观测值 / pass_bool）
- `basis_items.parquet`                —— basis 明细（含 basis_id，用于 leakage 审计的禁词来源）

后端：evaluator.yaml `eval_truth_store.mode = duckdb_or_separate_neo4j`。
DuckDB 为可选加速后端；本机若无 DuckDB 则回退 pandas，二者读出的
`pandas.DataFrame` schema 一致（spec→code 单向：spec 未强制 DuckDB，
只要求 evaluator-only truth store）。

spec→code 单向：本模块不自创 W2 字段，只透传 parquet 既有列。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

# spec §8.2 reference_truth 五张表的标准文件名（与 evaluator.yaml input_tables 对齐）。
# coverage_control_metadata 是 evaluator.yaml input_tables 里的可选第 6 张，
# spec §8.2 的 reference_truth 块未列它，故按 optional 处理（缺失不报错）。
TRUTH_TABLE_FILES: Dict[str, str] = {
    "normative_projection_meta": "normative_projection_meta.parquet",
    "projections": "projections.parquet",
    "matched_families": "matched_families.parquet",
    "threshold_evaluations": "threshold_evaluations.parquet",
    "basis_items": "basis_items.parquet",
}
OPTIONAL_TRUTH_TABLE_FILES: Dict[str, str] = {
    "coverage_control_metadata": "coverage_control_metadata.parquet",
}


@dataclass
class TruthBundle:
    """一次评测可见的全部 W2 参考真值（spec §8.2 reference_truth）。

    每个字段是一张 parquet 读出的 `pandas.DataFrame`。
    `truth_dir` 记录来源目录，便于 evaluator 输出溯源。
    """

    truth_dir: str
    normative_projection_meta: pd.DataFrame
    projections: pd.DataFrame
    matched_families: pd.DataFrame
    threshold_evaluations: pd.DataFrame
    basis_items: pd.DataFrame
    coverage_control_metadata: Optional[pd.DataFrame] = None
    # 加载后端标记（"duckdb" / "pandas"），仅用于诊断/报告。
    backend: str = "pandas"
    loaded_tables: List[str] = field(default_factory=list)
    # DEBT-054 Block B.3：truth schema 版本（从 normative_projection_meta.truth_schema 读取）。
    # 旧 bundle 缺该列 = "truth_v1"（只读、不重算）；含 threshold_regime_id 增列的新 bundle
    # meta 写 "truth_v2_regime"。仅供溯源/版本分流，不参与 blind join。
    truth_schema: str = "truth_v1"

    def projection_family_index(self) -> Dict[str, str]:
        """projection_id → projection_family（W2 coarse family）的索引。

        W2 真值侧 `projections.projection_family` 与 `matched_families.family_id`
        都用 coarse family id（已对账：二者取值同集合）。
        """
        if "projection_id" not in self.projections.columns:
            return {}
        col = (
            "projection_family"
            if "projection_family" in self.projections.columns
            else "selected_family"
        )
        out: Dict[str, str] = {}
        for _, row in self.projections[["projection_id", col]].iterrows():
            pid = row["projection_id"]
            fam = row[col]
            if isinstance(pid, str) and isinstance(fam, str):
                out[pid] = fam
        return out


class TruthLoadError(RuntimeError):
    """W2 参考真值目录缺表 / 不可读时抛出。"""


def _resolve_table_path(truth_dir: str, filename: str) -> Optional[str]:
    """在 truth_dir 下定位某张表文件。

    兼容两种布局：
    1. 文件直接位于 truth_dir 下；
    2. truth_dir 是一个 `*.parquet` 目录（W2 ProjectionResults 多文件 parquet
       数据集形态，见 worldgen/parquet_io.py）—— 此时表文件就在该目录内。
    """
    direct = os.path.join(truth_dir, filename)
    if os.path.isfile(direct):
        return direct
    return None


def _load_one_with_duckdb(con, path: str) -> pd.DataFrame:
    """用 DuckDB 读单张 parquet 为 DataFrame（可选加速后端）。"""
    # 参数化路径，避免把路径拼进 SQL 文本。
    return con.execute(
        "SELECT * FROM read_parquet(?)", [path]
    ).fetch_df()


def load_truth_bundle(truth_dir: str, prefer_duckdb: bool = True) -> TruthBundle:
    """加载一个 W2 参考真值目录为 `TruthBundle`（spec §8.2）。

    Args:
        truth_dir: 含 5 张 parquet 的目录（W2 NormativeProjection 产出目录）。
        prefer_duckdb: True 时优先用 DuckDB 后端；本机无 DuckDB 自动回退 pandas。

    Raises:
        TruthLoadError: 目录不存在，或 5 张必需表有任一缺失。

    spec §8.3.2 / §8.5：若 W2 真值不可用，调用方应输出
    `evaluation_status="blocked_..."`，而非让 agent run 受影响。
    """
    if not os.path.isdir(truth_dir):
        raise TruthLoadError(f"W2 参考真值目录不存在: {truth_dir}")

    # 先解析所有必需表路径，缺一即报错（spec §8.2 reference_truth 五表齐全要求）。
    required_paths: Dict[str, str] = {}
    for key, filename in TRUTH_TABLE_FILES.items():
        path = _resolve_table_path(truth_dir, filename)
        if path is None:
            raise TruthLoadError(
                f"W2 参考真值缺表: {filename}（目录 {truth_dir}）"
            )
        required_paths[key] = path

    optional_paths: Dict[str, str] = {}
    for key, filename in OPTIONAL_TRUTH_TABLE_FILES.items():
        path = _resolve_table_path(truth_dir, filename)
        if path is not None:
            optional_paths[key] = path

    backend = "pandas"
    con = None
    if prefer_duckdb:
        try:  # DuckDB 可选——本机未装则回退 pandas（evaluator.yaml mode 允许二选一）。
            import duckdb  # type: ignore

            con = duckdb.connect(database=":memory:")
            backend = "duckdb"
        except Exception:
            con = None
            backend = "pandas"

    def _read(path: str) -> pd.DataFrame:
        if con is not None:
            return _load_one_with_duckdb(con, path)
        return pd.read_parquet(path)

    try:
        frames: Dict[str, pd.DataFrame] = {
            key: _read(path) for key, path in required_paths.items()
        }
        opt_frames: Dict[str, pd.DataFrame] = {
            key: _read(path) for key, path in optional_paths.items()
        }
    finally:
        if con is not None:
            con.close()

    loaded = sorted(list(frames.keys()) + list(opt_frames.keys()))
    return TruthBundle(
        truth_dir=truth_dir,
        normative_projection_meta=frames["normative_projection_meta"],
        projections=frames["projections"],
        matched_families=frames["matched_families"],
        threshold_evaluations=frames["threshold_evaluations"],
        basis_items=frames["basis_items"],
        coverage_control_metadata=opt_frames.get("coverage_control_metadata"),
        backend=backend,
        loaded_tables=loaded,
        truth_schema=_read_truth_schema(frames["normative_projection_meta"]),
    )


def _read_truth_schema(meta_df: pd.DataFrame) -> str:
    """从 normative_projection_meta 读 truth_schema 列；缺列/空 = "truth_v1"（legacy 只读）。"""
    if "truth_schema" not in meta_df.columns or len(meta_df) == 0:
        return "truth_v1"
    val = meta_df["truth_schema"].iloc[0]
    if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
        return "truth_v1"
    return str(val)


__all__ = [
    "TruthBundle",
    "TruthLoadError",
    "load_truth_bundle",
    "TRUTH_TABLE_FILES",
    "OPTIONAL_TRUTH_TABLE_FILES",
]
