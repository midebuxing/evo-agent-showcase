"""灌库公用工具：parquet 读取、值规整、ID 工具（spec §3 / §4 内部支撑）。

本模块不对应 spec 单一章节，是各 loader 共享的底层工具：
- parquet 读取（pandas）+ numpy / NaN 规整为 Python 原生类型；
- canonical JSON（复用 kg.neo4j_client.canonical_json，避免环引入这里重导出）；
- ID 合成、稳定去重等。

spec→code 单向：本模块只承载 spec §3 / §4 多处复用的纯工具逻辑，不引入新规格。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

# 复用 kg 层的 canonical_json，保持全图序列化口径一致（spec §3.1 规则 3）。
from evo_agent_baseline.kg.neo4j_client import canonical_json  # noqa: F401  (re-export)


def normalize_value(value: Any) -> Any:
    """把 pandas / numpy 取出的单值规整为 JSON 友好的 Python 原生类型。

    处理：
    - numpy 标量 → Python int / float / bool / str；
    - numpy ndarray / pandas 序列 → list（递归规整元素）；
    - NaN / NaT / pandas NA → None；
    - 其余原样返回。

    Args:
        value: 任意从 parquet 单元格取出的值。

    Returns:
        JSON 友好的 Python 值。
    """
    # ndarray / list / tuple：逐元素递归。
    if isinstance(value, (list, tuple)):
        return [normalize_value(v) for v in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        # numpy ndarray 或 numpy 标量都支持 tolist()。
        converted = value.tolist()
        if isinstance(converted, list):
            return [normalize_value(v) for v in converted]
        return normalize_value(converted)
    # NaN / NaT：float('nan') 与自身不相等。
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    # pandas NA / NaT 检测（不强依赖 import pandas）。
    type_name = type(value).__name__
    if type_name in {"NaTType", "NAType"}:
        return None
    return value


def row_to_dict(row: Any) -> Dict[str, Any]:
    """把一行 pandas Series 转为规整后的 Python dict。

    Args:
        row: pandas Series（DataFrame 的一行）。

    Returns:
        列名 → 规整值 的 dict。
    """
    return {str(key): normalize_value(val) for key, val in row.items()}


def read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    """读取 parquet 文件为规整后的 dict 列表。

    Args:
        path: parquet 文件路径。

    Returns:
        每行一个 dict 的列表。
    """
    import pandas as pd

    frame = pd.read_parquet(path)
    return [row_to_dict(frame.iloc[i]) for i in range(len(frame))]


def opt_str(value: Any) -> Optional[str]:
    """规整为 Optional[str]：None / 空串 → None，其余 str()。

    Args:
        value: 任意值。

    Returns:
        非空字符串或 None。
    """
    value = normalize_value(value)
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def opt_float(value: Any) -> Optional[float]:
    """规整为 Optional[float]，无法转换返回 None。"""
    value = normalize_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def opt_int(value: Any) -> Optional[int]:
    """规整为 Optional[int]，无法转换返回 None。"""
    value = normalize_value(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_list(value: Any) -> List[Any]:
    """规整为 list：None → []，标量 → [标量]，list 原样。"""
    value = normalize_value(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_str_list(value: Any) -> List[str]:
    """规整为 list[str]，丢弃 None 元素。"""
    return [str(v) for v in as_list(value) if v is not None]


def stable_unique(items: List[Any]) -> List[Any]:
    """按首次出现顺序去重（stable unique）。

    spec §3.3.4 measurements 的 derivation_refs 合并要求 stable_unique。

    Args:
        items: 待去重列表。

    Returns:
        去重后保持原首现顺序的列表。
    """
    seen: set = set()
    result: List[Any] = []
    for item in items:
        key = item if isinstance(item, (str, int, float, bool)) else json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def shallow_extract(payload: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """从 payload 浅抽取指定 key（spec §3.3.1 派生列规则）。

    缺失的 key 填 None；不做任何推导。

    Args:
        payload: 源 dict。
        keys: 要抽取的 key 列表。

    Returns:
        {key: payload.get(key)} dict，缺失填 None。
    """
    return {key: normalize_value(payload.get(key)) for key in keys}


__all__ = [
    "canonical_json",
    "normalize_value",
    "row_to_dict",
    "read_parquet_rows",
    "opt_str",
    "opt_float",
    "opt_int",
    "as_list",
    "as_str_list",
    "stable_unique",
    "shallow_extract",
]
