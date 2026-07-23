"""Cohort manifest — B.5 外置 append-only 双层 hash（DEBT-054 Phase 0 授权 v4 Block B.5）。

冻结数字红线："schema/profile bump 不原地打标"——本模块产出**外置** append-only manifest，
记录 cohort（一组产物 parquet 文件）的 `tree_hash`（文件字节+行数）与 `manifest_hash`
（覆盖 schema/profile 标识 + tree_hash）。任一文件字节变 → tree_hash 变 → manifest_hash 变；
任一 schema/profile 标识变（即便字节不变）→ manifest_hash 变。两条路径都锁死。

B.5 公式：
    tree_hash    = sha256(canonical_json(sorted(
                       [{path, sha256, size, row_count} for each file], key=path)))
    manifest_hash = sha256(canonical_json({
                       tree_hash, identity_schema, truth_schema, projection_schema,
                       canonical_profile_id, cohort_id, config_anchors}))

分层红线：本模块 **不 import** `evo_agent_baseline.*`（尤其 closure/eval），只处理 W2 侧
产物文件哈希与 schema 标识；`identity_schema` / `canonical_profile_id` 由调用方传入
（Block A/C 落地后由 closure 侧填，未落地时传空串占位——W2 emit 契约层不阻塞）。

append-only：`append_cohort_manifest` 只追加一行 JSON（jsonl），从不原地改旧字节。
legacy reader 只读、无 in-place mutation API。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


COHORT_MANIFEST_FILENAME = "cohort_manifest.jsonl"


def canonical_json(value: Any) -> str:
    """确定性序列化：键排序、UTF-8、无多余空白（B.5 / C.8 canonical_json 口径）。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_entry(rel_path: str, abs_path: Path, row_count: Optional[int]) -> Dict[str, Any]:
    """单文件 tree_hash 叶子条目：{path, sha256, size, row_count}。"""
    raw = abs_path.read_bytes()
    return {
        "path": rel_path,
        "sha256": _sha256_hex(raw),
        "size": len(raw),
        "row_count": row_count,
    }


def compute_tree_hash(files: Sequence[Mapping[str, Any]]) -> str:
    """B.5 tree_hash：对 file entry 列表按 path 排序后 canonical_json 再 sha256。"""
    ordered = sorted(
        (
            {
                "path": f["path"],
                "sha256": f["sha256"],
                "size": f["size"],
                "row_count": f.get("row_count"),
            }
            for f in files
        ),
        key=lambda item: item["path"],
    )
    return _sha256_hex(canonical_json(ordered).encode("utf-8"))


def compute_cohort_manifest(
    files: Sequence[Mapping[str, Any]],
    *,
    identity_schema: str,
    truth_schema: str,
    projection_schema: str,
    canonical_profile_id: str,
    cohort_id: str,
    config_anchors: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """B.5 双层 hash：返回含 tree_hash + manifest_hash + 全字段的 manifest dict。

    `identity_schema` / `canonical_profile_id` 未落地（Block A/C 前）传空串占位——
    manifest_hash 仍闭合（空串是确定性输入），后续这两字段填实值会令 manifest_hash 变，
    正是"profile/identity bump → manifest 变"的预期锁。
    """
    anchors = dict(config_anchors or {})
    tree_hash = compute_tree_hash(files)
    manifest_core = {
        "tree_hash": tree_hash,
        "identity_schema": identity_schema,
        "truth_schema": truth_schema,
        "projection_schema": projection_schema,
        "canonical_profile_id": canonical_profile_id,
        "cohort_id": cohort_id,
        "config_anchors": anchors,
    }
    manifest_hash = _sha256_hex(canonical_json(manifest_core).encode("utf-8"))
    return {
        **manifest_core,
        "manifest_hash": manifest_hash,
        # cohort_manifest_sha（= manifest_hash）供 metric series 引用（附录 metric series 契约）。
        "cohort_manifest_sha": manifest_hash,
        "files": [
            {
                "path": f["path"],
                "sha256": f["sha256"],
                "size": f["size"],
                "row_count": f.get("row_count"),
            }
            for f in sorted(files, key=lambda item: item["path"])
        ],
    }


def append_cohort_manifest(manifest_path: Path, manifest: Mapping[str, Any]) -> Path:
    """append-only 追加一行 JSON（jsonl）；从不原地改旧字节。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(manifest)
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return manifest_path


def read_cohort_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    """只读：返回 manifest jsonl 的全部条目（append 顺序）。缺文件 → 空列表。"""
    if not manifest_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        out.append(json.loads(raw_line))
    return out


__all__ = [
    "COHORT_MANIFEST_FILENAME",
    "canonical_json",
    "file_entry",
    "compute_tree_hash",
    "compute_cohort_manifest",
    "append_cohort_manifest",
    "read_cohort_manifest",
]
