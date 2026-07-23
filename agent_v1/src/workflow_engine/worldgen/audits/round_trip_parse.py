"""W1 round-trip parse audit (DEBT-030 audit 4).

W1 spec 01 §6 表第 3 行红线：
> Round-trip parse check: W1 输出 + 重读 → projection 结果一致（无 silent mutation）.

设计
====
对 3 类 bundle payload（``world_bundles`` / ``sidecar_runtime`` /
``normative_projection``）做 parquet write → read → byte-identical compare。
任何字段不一致即 fail（捕捉 schema 漂移 / silent type coercion / 丢字段）.

跟 ``test_parquet_io.py`` 中已有的 fixture-level round-trip 测试互补：测试在
unit 层固定 sample payload；本 audit 接受 caller 传入 payload，可以用来跑
release_batch CI（write_world_bundles_parquet 用同一组 payload 跟 release 跑
的 batch 比对）.

跨进程 / 跑批 CI 用法
=====================
release_batch 跑完后立刻 audit（也可以构造 minimal fixture 当 smoke）::

    from workflow_engine.worldgen.audits import round_trip_parse_audit
    report = round_trip_parse_audit(
        world_payload=...,
        sidecar_payload=...,
        projection_payload=...,
        tmp_dir=Path("/tmp/audit_xyz"),
    )
    assert report.passed, [r.diff_summary for r in report.results if not r.passed]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from workflow_engine.worldgen.parquet_io import (
    read_normative_projection_parquet,
    read_sidecar_runtime_parquet,
    read_world_bundles_parquet,
    write_normative_projection_parquet,
    write_sidecar_runtime_parquet,
    write_world_bundles_parquet,
)


BundleKind = Literal["world", "sidecar", "projection"]


@dataclass
class BundleRoundTripResult:
    bundle_kind: BundleKind
    passed: bool
    n_top_records: int
    diff_summary: Optional[str] = None


@dataclass
class RoundTripAuditReport:
    passed: bool
    results: List[BundleRoundTripResult] = field(default_factory=list)
    tmp_dir: Optional[Path] = None


def _short_diff(a: Any, b: Any, path: str = "") -> Optional[str]:
    """递归对比 a / b。返回第一条不同的 path + 摘要，None 表示完全相同."""
    if type(a) is not type(b):
        return f"{path or '<root>'}: type mismatch {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        keys_a = set(a.keys())
        keys_b = set(b.keys())
        if keys_a != keys_b:
            only_a = sorted(keys_a - keys_b)
            only_b = sorted(keys_b - keys_a)
            return (
                f"{path or '<root>'}: key sets differ"
                + (f" only_in_a={only_a}" if only_a else "")
                + (f" only_in_b={only_b}" if only_b else "")
            )
        for k in sorted(keys_a):
            sub = _short_diff(a[k], b[k], f"{path}.{k}" if path else str(k))
            if sub:
                return sub
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path or '<root>'}: list len {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            sub = _short_diff(x, y, f"{path}[{i}]")
            if sub:
                return sub
        return None
    if a != b:
        a_repr = repr(a)[:50]
        b_repr = repr(b)[:50]
        return f"{path or '<root>'}: value mismatch {a_repr} vs {b_repr}"
    return None


def _count_top_records(payload: Dict[str, Any], kind: BundleKind) -> int:
    """payload 顶层主纪录数（用作 audit 报告诊断信息）."""
    if kind == "world":
        return len(payload.get("buildings", []))
    if kind == "sidecar":
        return len(payload.get("records", []))
    if kind == "projection":
        return len(payload.get("buildings", []))
    return 0


def _round_trip_one(
    kind: BundleKind,
    payload: Dict[str, Any],
    tmp_dir: Path,
) -> BundleRoundTripResult:
    if kind == "world":
        out_dir = write_world_bundles_parquet(tmp_dir / "wb_pq", payload)
        restored = read_world_bundles_parquet(out_dir)
    elif kind == "sidecar":
        out_dir = write_sidecar_runtime_parquet(tmp_dir / "sc_pq", payload)
        restored = read_sidecar_runtime_parquet(out_dir)
    elif kind == "projection":
        out_dir = write_normative_projection_parquet(tmp_dir / "np_pq", payload)
        restored = read_normative_projection_parquet(out_dir)
    else:
        raise ValueError(f"unknown bundle kind {kind!r}")

    n_records = _count_top_records(payload, kind)
    diff = _short_diff(payload, restored)
    return BundleRoundTripResult(
        bundle_kind=kind,
        passed=diff is None,
        n_top_records=n_records,
        diff_summary=diff,
    )


def round_trip_parse_audit(
    world_payload: Optional[Dict[str, Any]] = None,
    sidecar_payload: Optional[Dict[str, Any]] = None,
    projection_payload: Optional[Dict[str, Any]] = None,
    tmp_dir: Optional[Path] = None,
) -> RoundTripAuditReport:
    """对传入的 bundle payload 跑 write→read→assert == round-trip audit.

    每种 payload 可独立传或不传（缺则跳过该 kind）.
    """
    if tmp_dir is None:
        raise ValueError("tmp_dir must be provided (audit writes parquet to disk)")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    results: List[BundleRoundTripResult] = []
    if world_payload is not None:
        results.append(_round_trip_one("world", world_payload, tmp_dir))
    if sidecar_payload is not None:
        results.append(_round_trip_one("sidecar", sidecar_payload, tmp_dir))
    if projection_payload is not None:
        results.append(_round_trip_one("projection", projection_payload, tmp_dir))

    return RoundTripAuditReport(
        passed=all(r.passed for r in results),
        results=results,
        tmp_dir=tmp_dir,
    )


def round_trip_parse_audit_from_json(
    world_json_path: Optional[Path] = None,
    sidecar_json_path: Optional[Path] = None,
    projection_json_path: Optional[Path] = None,
    tmp_dir: Optional[Path] = None,
) -> RoundTripAuditReport:
    """便利函数：从 JSON 文件读 payload 跑 audit（release_batch CI 常用 entry）."""

    def _load(p: Optional[Path]) -> Optional[Dict[str, Any]]:
        if p is None:
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    return round_trip_parse_audit(
        world_payload=_load(world_json_path),
        sidecar_payload=_load(sidecar_json_path),
        projection_payload=_load(projection_json_path),
        tmp_dir=tmp_dir,
    )


__all__ = [
    "BundleKind",
    "BundleRoundTripResult",
    "RoundTripAuditReport",
    "round_trip_parse_audit",
    "round_trip_parse_audit_from_json",
]
