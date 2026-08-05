"""sidecar loader：SidecarRuntimeBundle parquet → sidecar 节点（spec §3.3.5 + §4.2.8）。

把 sidecar 3 张 parquet（sidecar_runtime_meta / sidecar_records / sidecar_entries）
灌入事实侧 KG 的 sidecar 子图。

evo-agent blind 关键约束（spec D-003 / §3.3.5 / §4.2.8）：
- `sidecar_records.parquet.projection_id` 只允许 loader 在内存中临时读取；
- 写入 Neo4j 的 props **绝不**包含 `projection_id` 或其任何 hash 变体；
- `build_sidecar_runtime_props` 末尾断言 `projection_id` / `raw_projection_ref_hash`
  不在 props 中（spec §4.2.8 代码块）。

`SidecarEntry` 主键 `sidecar_entry_id = runtime_id + "::" + entry_type + "::" + seq_no`
（实测 sidecar_entries.parquet 无独立 entry id 列，必须合成）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from evo_agent_baseline.ingest._common import (
    as_str_list,
    canonical_json,
    opt_int,
    opt_str,
    read_parquet_rows,
)
from evo_agent_baseline.ingest._graphspec import EdgeSpec, GraphBatch, NodeSpec
from evo_agent_baseline.ingest.guard import (
    AuditLog,
    SecurityError,
    gate_g006_sidecar_projection_scrub,
    raise_if_failed,
)

# DEBT-034 闭环：building_ids 真过滤靠 buildings.parquet 的 building → world 双射
# （worldgen 每个 world 一栋 Building，见 fact_loader.py L776-780 `building_by_world`
# 一一映射假设）。sidecar parquet 本身不含 building_id 字段（实测：
# `sidecar_records` 只有 runtime_id/world_id/interface_ids；`sidecar_entries`
# source_refs 只含 WB-/FRG- 前缀不含 BLD-），所以最稳健的做法是在 loader 内部
# 把 building_ids 解析为 world_ids 子集，再走现成的 world_ids 过滤路径。

# §4.2.8 / §3.3.5：禁止出现在 SidecarRuntimeRecord props 的字段。
_BANNED_SIDECAR_PROPS: Set[str] = {
    "projection_id",
    "raw_projection_ref_hash",
    "projection_ref_hash",
}


@dataclass
class SidecarLoadResult:
    """sidecar loader 灌库结果。"""

    batch: GraphBatch
    runtime_ids: Set[str] = field(default_factory=set)
    entry_count: int = 0
    audit: AuditLog = field(default_factory=AuditLog)


def build_sidecar_runtime_props(row: Dict[str, Any]) -> Dict[str, Any]:
    """sidecar_records.parquet 行 → SidecarRuntimeRecord props（spec §4.2.8）。

    row 在 parquet 中带 projection_id，但 agent KG 绝不接收它。
    本函数严格照 spec §4.2.8 代码块：只取 4 个安全字段，末尾断言无 projection_id。

    Args:
        row: sidecar_records.parquet 一行。

    Returns:
        安全的 SidecarRuntimeRecord props（不含主键 runtime_id）。

    Raises:
        SecurityError: props 意外含 projection_id / hash 变体。
    """
    props = {
        "world_id": opt_str(row.get("world_id")),
        "interface_ids": as_str_list(row.get("interface_ids")),
        "source_kind": "worldgen_sidecar",   # 固定值
    }
    # spec §4.2.8 断言：写图前 projection_id / hash 绝不在 props 中。
    leaked = set(props.keys()) & _BANNED_SIDECAR_PROPS
    if leaked:
        raise SecurityError(
            f"G-006: SidecarRuntimeRecord props leaked {sorted(leaked)} — "
            "projection_id must be discarded before write (spec D-003)"
        )
    assert "projection_id" not in props
    assert "raw_projection_ref_hash" not in props
    return props


def build_sidecar_runtime_node(row: Dict[str, Any]) -> NodeSpec:
    """sidecar_records.parquet 行 → (:SidecarRuntimeRecord) 节点（spec §3.3.5）。

    runtime_id 作主键；projection_id 字段被丢弃，不进图。
    """
    runtime_id = opt_str(row.get("runtime_id"))
    props = build_sidecar_runtime_props(row)
    # G-006 质量门：再过一次禁止属性检查。
    raise_if_failed(gate_g006_sidecar_projection_scrub(runtime_id or "", props))
    return NodeSpec("SidecarRuntimeRecord", "runtime_id", runtime_id, props)


def build_sidecar_entry_node(row: Dict[str, Any]) -> NodeSpec:
    """sidecar_entries.parquet 行 → (:SidecarEntry) 节点（spec §3.3.5）。

    sidecar_entry_id = runtime_id + "::" + entry_type + "::" + seq_no
    （实测 parquet 无独立 entry id 列，必须合成）。

    Args:
        row: sidecar_entries.parquet 一行。

    Returns:
        SidecarEntry NodeSpec。
    """
    runtime_id = opt_str(row.get("runtime_id"))
    entry_type = opt_str(row.get("entry_type"))
    seq_no = opt_int(row.get("seq_no"))
    sidecar_entry_id = f"{runtime_id}::{entry_type}::{seq_no}"

    # value_json / qualifiers_json：上游已是 JSON 字符串，re-canonicalize 统一口径。
    value_json = _recanonicalize(opt_str(row.get("value_json")), default="null")
    qualifiers_json = _recanonicalize(opt_str(row.get("qualifiers_json")), default="{}")

    props = {
        "runtime_id": runtime_id,
        "world_id": opt_str(row.get("world_id")),
        "entry_type": entry_type,
        "slot_id": opt_str(row.get("slot_id")),
        "value_json": value_json,
        "unit": opt_str(row.get("unit")),
        "qualifiers_json": qualifiers_json,
        "time_anchor_key": opt_str(row.get("time_anchor_key")),
        "source_refs": as_str_list(row.get("source_refs")),
        "notes": as_str_list(row.get("notes")),
    }
    return NodeSpec("SidecarEntry", "sidecar_entry_id", sidecar_entry_id, props)


def _recanonicalize(raw: Optional[str], default: str) -> str:
    """把上游 JSON 字符串重新 canonicalize；解析失败用 default。

    sidecar_entries 的 value_json / qualifiers_json 上游已是 JSON 字符串，
    re-parse + canonical_json 保证与全图序列化口径一致（spec §3.1 规则 3）。
    """
    if raw is None:
        return default
    try:
        import json as _json

        return canonical_json(_json.loads(raw))
    except (ValueError, TypeError):
        return default


def _resolve_building_to_world_ids(
    run_dir: Path,
    building_ids: Set[str],
    audit: AuditLog,
) -> Set[str]:
    """从 buildings.parquet 反查 building_ids → world_ids（DEBT-034 真过滤辅助）。

    worldgen 每个 world 对应一栋 Building（1:1 双射，fact_loader.py 同假设）。
    sidecar parquet 本身不含 building_id 字段，所以 building 层过滤必须借
    fact 表反查。返回的 world_id 集合若与传入的 world_ids 共存，由调用方做交集。

    Args:
        run_dir: 灌库输入目录（含 buildings.parquet）。
        building_ids: 用户指定的 building_id 集合（已知非空）。
        audit: 审计记录器（用于记录未命中建筑）。

    Returns:
        匹配到的 world_id 集合；未命中任何 building 时返回空 set
        （上层应据此过滤掉所有 records，灌入 0 节点）。
    """
    buildings_path = _find_table(run_dir, "buildings.parquet")
    if buildings_path is None:
        audit.warn(
            "DEBT-034: buildings.parquet not found, building_ids filter "
            "cannot be applied -> treating as empty match"
        )
        return set()

    matched: Set[str] = set()
    matched_buildings: Set[str] = set()
    for row in read_parquet_rows(buildings_path):
        bid = opt_str(row.get("building_id"))
        wid = opt_str(row.get("world_id"))
        if bid is None or wid is None:
            continue
        if bid in building_ids:
            matched.add(wid)
            matched_buildings.add(bid)

    unmatched = building_ids - matched_buildings
    if unmatched:
        audit.warn(
            f"DEBT-034: building_ids not found in buildings.parquet: "
            f"{sorted(unmatched)[:5]}{'...' if len(unmatched) > 5 else ''}"
        )
    return matched


def build_sidecar_graph(
    run_dir: Path,
    world_ids: Optional[Set[str]] = None,
    audit: Optional[AuditLog] = None,
    building_ids: Optional[Set[str]] = None,
) -> SidecarLoadResult:
    """把 sidecar 输出目录转换为 sidecar 子图 GraphBatch（纯转换，不写 Neo4j）。

    Args:
        run_dir: 灌库输入目录（含 WorldgenSidecarRuntimeBundle.v2.parquet/）。
        world_ids: 事实侧已加载的 world id 集合；用于建 World-HAS_SIDECAR_RECORD 边。
            None 表示不限制（仍按 record.world_id 建边）。
        audit: 审计记录器。
        building_ids: 可选 building 级真过滤（DEBT-034 闭环新增）。
            None = 不按 building 过滤（保留 world_ids 现有行为）；
            非空 set = 在 loader 内部反查 buildings.parquet 解析到 world_ids 子集，
            与 `world_ids` 参数（若也给了）做交集后再过滤 records + entries。
            sidecar parquet 本身不含 building_id 字段，靠 worldgen 1 world ↔ 1 building
            双射回填。building_ids 全部未命中时灌入 0 节点。

    Returns:
        SidecarLoadResult。
    """
    audit = audit or AuditLog()
    result = SidecarLoadResult(batch=GraphBatch(), audit=audit)

    # --- DEBT-034：building_ids → world_ids 反查 + 与传入 world_ids 取交集 ---
    effective_world_ids: Optional[Set[str]] = world_ids
    if building_ids is not None:
        building_world_ids = _resolve_building_to_world_ids(
            run_dir, building_ids, audit
        )
        if world_ids is None:
            effective_world_ids = building_world_ids
        else:
            effective_world_ids = world_ids & building_world_ids
        audit.warn(
            f"DEBT-034: building_ids filter active "
            f"(buildings_in={len(building_ids)}, "
            f"worlds_resolved={len(building_world_ids)}, "
            f"effective_worlds={len(effective_world_ids)})"
        )

    # --- sidecar_runtime_meta.parquet（optional）---
    meta_path = _find_table(run_dir, "sidecar_runtime_meta.parquet")
    if meta_path is not None:
        audit.record_source("sidecar_runtime_meta.parquet")
    else:
        audit.warn("sidecar_runtime_meta.parquet not found (optional)")

    # --- sidecar_records.parquet → SidecarRuntimeRecord ---
    # spec §4.2 + smoke 友好：effective_world_ids 非 None 时，按 world_id 过滤入图
    # （None 仍保持原行为 = 全量）。entries 表无 world_id 字段，靠 runtime_id 二级过滤。
    accepted_runtime_ids: Optional[Set[str]] = (
        set() if effective_world_ids is not None else None
    )
    records_path = _find_table(run_dir, "sidecar_records.parquet")
    if records_path is not None:
        audit.record_source("sidecar_records.parquet")
        for row in read_parquet_rows(records_path):
            runtime_id = opt_str(row.get("runtime_id"))
            if runtime_id is None:
                continue
            world_id = opt_str(row.get("world_id"))
            if effective_world_ids is not None and world_id not in effective_world_ids:
                continue
            if accepted_runtime_ids is not None:
                accepted_runtime_ids.add(runtime_id)
            node = build_sidecar_runtime_node(row)
            result.batch.add_node(node)
            result.runtime_ids.add(runtime_id)
            # World-HAS_SIDECAR_RECORD->SidecarRuntimeRecord。
            if world_id:
                result.batch.add_edge(EdgeSpec(
                    "World", "world_id", world_id,
                    "HAS_SIDECAR_RECORD",
                    "SidecarRuntimeRecord", "runtime_id", runtime_id,
                ))
    else:
        audit.warn("sidecar_records.parquet not found")

    # --- sidecar_entries.parquet → SidecarEntry + 桥接边 ---
    entries_path = _find_table(run_dir, "sidecar_entries.parquet")
    if entries_path is not None:
        audit.record_source("sidecar_entries.parquet")
        for row in read_parquet_rows(entries_path):
            runtime_id = opt_str(row.get("runtime_id"))
            if runtime_id is None:
                continue
            if accepted_runtime_ids is not None and runtime_id not in accepted_runtime_ids:
                continue
            node = build_sidecar_entry_node(row)
            result.batch.add_node(node)
            result.entry_count += 1
            entry_id = node.key_value
            # SidecarRuntimeRecord-HAS_SIDECAR_ENTRY->SidecarEntry。
            result.batch.add_edge(EdgeSpec(
                "SidecarRuntimeRecord", "runtime_id", runtime_id,
                "HAS_SIDECAR_ENTRY",
                "SidecarEntry", "sidecar_entry_id", entry_id,
            ))
            slot_id = node.props.get("slot_id")
            time_anchor_key = node.props.get("time_anchor_key")
            # 桥接边（spec §3.3.5 / §3.6.2）：端点不存在时写入期 MATCH 不命中即不建。
            # ⚠️ 未归一（2026-07-27 注，同 fact_loader.py 的 REALIZES_SLOT）：
            # `slot_id` 取自 sidecar 记录＝**世界侧名**，`SemanticSlot.slot_id` 是
            # **卡侧名**，命中别名表的槽这两条桥边结构上不存在。当前无消费者
            # （闭包读 FactPack、检索读 SlotRef），故是死边、不改行为；接线消费前
            # 必须先过 slot_alias_policy 正向归一。
            # `REALIZES_MEASURE` 同理，且它拿 slot_id 当 measure_key 用，另需过
            # measure_aliases。
            if slot_id:
                result.batch.add_edge(EdgeSpec(
                    "SidecarEntry", "sidecar_entry_id", entry_id,
                    "REALIZES_SLOT",
                    "SemanticSlot", "slot_id", slot_id,
                ))
                result.batch.add_edge(EdgeSpec(
                    "SidecarEntry", "sidecar_entry_id", entry_id,
                    "REALIZES_MEASURE",
                    "Measure", "measure_key", slot_id,
                ))
            if time_anchor_key:
                result.batch.add_edge(EdgeSpec(
                    "SidecarEntry", "sidecar_entry_id", entry_id,
                    "USES_TIME_ANCHOR",
                    "TimeAnchor", "time_anchor_key", time_anchor_key,
                ))
            # SOURCED_FROM：source_refs 可解析到 Fragment/Component/Building 时建边。
            for ref in node.props.get("source_refs", []):
                _add_sourced_from_edges(result.batch, entry_id, ref)
    else:
        audit.warn("sidecar_entries.parquet not found")

    return result


def _add_sourced_from_edges(batch: GraphBatch, entry_id: str, ref: str) -> None:
    """为 sidecar entry 的一个 source_ref 加 SOURCED_FROM 边（spec §3.3.5）。

    ref 可能是 Fragment / Component / Building id；写入期对每个候选 label
    都建一条 MATCH-MERGE，只有真实存在的端点会落边。
    """
    for label, key_prop in (
        ("Fragment", "fragment_id"),
        ("Component", "component_id"),
        ("Building", "building_id"),
    ):
        batch.add_edge(EdgeSpec(
            "SidecarEntry", "sidecar_entry_id", entry_id,
            "SOURCED_FROM",
            label, key_prop, ref,
        ))


def _find_table(run_dir: Path, table_name: str) -> Optional[Path]:
    """在 run_dir 下递归找指定 parquet（与 fact_loader 同口径）。"""
    direct = run_dir / table_name
    if direct.is_file():
        return direct
    for match in sorted(run_dir.rglob(table_name)):
        if match.is_file():
            return match
    return None


def load_sidecar_kg(
    run_dir: Path,
    client: Any,
    world_ids: Optional[Set[str]] = None,
    audit: Optional[AuditLog] = None,
    building_ids: Optional[Set[str]] = None,
) -> SidecarLoadResult:
    """把 sidecar 子图写入 Neo4j（spec §4.2）。

    Args:
        run_dir: 灌库输入目录。
        client: `Neo4jClient` 实例。
        world_ids: 事实侧已加载的 world id 集合。
        audit: 审计记录器。
        building_ids: 可选 building 级真过滤（DEBT-034）。详 `build_sidecar_graph`。

    Returns:
        SidecarLoadResult（已写入）。
    """
    from evo_agent_baseline.ingest._graphspec import compile_batch

    result = build_sidecar_graph(
        run_dir, world_ids=world_ids, audit=audit, building_ids=building_ids
    )
    client.write_many(compile_batch(result.batch))
    return result


__all__ = [
    "SidecarLoadResult",
    "build_sidecar_runtime_props",
    "build_sidecar_runtime_node",
    "build_sidecar_entry_node",
    "build_sidecar_graph",
    "load_sidecar_kg",
]

