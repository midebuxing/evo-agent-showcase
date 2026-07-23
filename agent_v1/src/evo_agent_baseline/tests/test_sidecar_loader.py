"""sidecar loader 测试：sidecar parquet → sidecar 节点（spec §4.2.8 + §3.3.5）。

不依赖 Neo4j。核心验证 evo-agent blind D-003：projection_id 绝不进图。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_agent_baseline.ingest import sidecar_loader
from evo_agent_baseline.ingest.guard import FORBIDDEN_AGENT_PROPERTIES, SecurityError


# ===========================================================================
# §4.2.8 projection_id 丢弃
# ===========================================================================
def test_build_sidecar_runtime_props_discards_projection_id() -> None:
    """sidecar_records 行带 projection_id，但 props 绝不含它（spec §4.2.8 / D-003）。"""
    row = {
        "runtime_id": "SCR-1", "world_id": "WB-1",
        "projection_id": "PROJ-secret-answer",  # 上游有，但必须丢弃
        "interface_ids": ["if-1"],
    }
    props = sidecar_loader.build_sidecar_runtime_props(row)
    assert "projection_id" not in props
    assert "raw_projection_ref_hash" not in props
    assert "projection_ref_hash" not in props
    # 安全字段保留。
    assert props["world_id"] == "WB-1"
    assert props["source_kind"] == "worldgen_sidecar"
    assert props["interface_ids"] == ["if-1"]


def test_build_sidecar_runtime_node_no_forbidden_props() -> None:
    """SidecarRuntimeRecord 节点不含任何禁止属性名。"""
    row = {
        "runtime_id": "SCR-1", "world_id": "WB-1",
        "projection_id": "PROJ-1", "interface_ids": [],
    }
    node = sidecar_loader.build_sidecar_runtime_node(row)
    leaked = set(node.all_props().keys()) & FORBIDDEN_AGENT_PROPERTIES
    assert not leaked


def test_build_sidecar_entry_synthesizes_id() -> None:
    """SidecarEntry 主键合成 runtime_id::entry_type::seq_no（spec §3.3.5）。"""
    row = {
        "runtime_id": "SCR-1", "entry_type": "facts", "seq_no": 3,
        "slot_id": "qual.actor_role", "value_json": '"building_authority"',
        "qualifiers_json": '{"fragment_id":"FRG-1"}',
    }
    node = sidecar_loader.build_sidecar_entry_node(row)
    assert node.key_value == "SCR-1::facts::3"
    assert node.props["slot_id"] == "qual.actor_role"


def test_build_sidecar_entry_recanonicalizes_json() -> None:
    """SidecarEntry 的 value_json / qualifiers_json 重新 canonicalize。"""
    row = {
        "runtime_id": "SCR-1", "entry_type": "facts", "seq_no": 0,
        "slot_id": "x", "value_json": '{"b": 2, "a": 1}',
        "qualifiers_json": '{"y": 1, "x": 0}',
    }
    node = sidecar_loader.build_sidecar_entry_node(row)
    # canonical = key 排序、紧凑。
    assert node.props["value_json"] == '{"a":1,"b":2}'
    assert node.props["qualifiers_json"] == '{"x":0,"y":1}'


# ===========================================================================
# 端到端：真实 sidecar seed
# ===========================================================================
def test_build_sidecar_graph_real_seed(worldgen_seed_dir: Path) -> None:
    """真实 sidecar seed 端到端 build_sidecar_graph。"""
    result = sidecar_loader.build_sidecar_graph(worldgen_seed_dir)
    assert len(result.runtime_ids) > 0
    assert result.entry_count > 0
    labels = {n.label for n in result.batch.nodes}
    assert "SidecarRuntimeRecord" in labels
    assert "SidecarEntry" in labels


def test_build_sidecar_graph_no_projection_id_leak(worldgen_seed_dir: Path) -> None:
    """真实 sidecar：任何节点都不泄露 projection_id（最高优先级 blind 红线）。"""
    result = sidecar_loader.build_sidecar_graph(worldgen_seed_dir)
    for node in result.batch.nodes:
        props = node.all_props()
        assert "projection_id" not in props, f"{node.label} 泄露 projection_id"
        assert "raw_projection_ref_hash" not in props
        leaked = set(props.keys()) & FORBIDDEN_AGENT_PROPERTIES
        assert not leaked, f"{node.label} 泄露禁止属性 {leaked}"


def test_sidecar_runtime_record_relations(worldgen_seed_dir: Path) -> None:
    """真实 sidecar：建 World-HAS_SIDECAR_RECORD + HAS_SIDECAR_ENTRY 边。"""
    result = sidecar_loader.build_sidecar_graph(worldgen_seed_dir)
    rel_types = {e.rel_type for e in result.batch.edges}
    assert "HAS_SIDECAR_RECORD" in rel_types
    assert "HAS_SIDECAR_ENTRY" in rel_types
    # 禁止关系不出现。
    assert "FOR_PROJECTION" not in rel_types


# ===========================================================================
# DEBT-034：building_ids 真过滤（building → world 双射反查）
# ===========================================================================
def _pick_one_world_and_building(worldgen_seed_dir: Path) -> tuple[str, str]:
    """从 buildings.parquet 取第一对 (world_id, building_id) 给 filter 测试用。"""
    from evo_agent_baseline.ingest._common import opt_str, read_parquet_rows

    for path in worldgen_seed_dir.rglob("buildings.parquet"):
        for row in read_parquet_rows(path):
            wid = opt_str(row.get("world_id"))
            bid = opt_str(row.get("building_id"))
            if wid and bid:
                return wid, bid
    pytest.skip("buildings.parquet 内无可用 (world_id, building_id) 对")


def test_build_sidecar_graph_building_ids_none_preserves_world_ids_behavior(
    worldgen_seed_dir: Path,
) -> None:
    """DEBT-034：building_ids=None 时行为完全不变（保留 world_ids 老路径）。

    确保新加的 building_ids 参数不引入回归：传 world_ids 子集时灌入的节点数
    与未引入 building_ids 参数前一致。
    """
    wid, _bid = _pick_one_world_and_building(worldgen_seed_dir)

    legacy_result = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, world_ids={wid}
    )
    new_result = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, world_ids={wid}, building_ids=None
    )
    # 节点/边数 + runtime_ids 都应一致。
    assert len(new_result.batch.nodes) == len(legacy_result.batch.nodes)
    assert len(new_result.batch.edges) == len(legacy_result.batch.edges)
    assert new_result.runtime_ids == legacy_result.runtime_ids
    assert new_result.entry_count == legacy_result.entry_count


def test_build_sidecar_graph_building_ids_filter_to_one_building(
    worldgen_seed_dir: Path,
) -> None:
    """DEBT-034：building_ids 指定 1 栋楼 → 只灌该 building 对应 world 的 sidecar。

    验证 (a) 节点数 << 全量；(b) 所有 SidecarRuntimeRecord 节点的 world_id
    都属于解析到的 world；(c) 与等价 world_ids filter 结果一致（双射前提下）。
    """
    wid, bid = _pick_one_world_and_building(worldgen_seed_dir)

    # 全量 baseline（无任何过滤）作上界对照。
    full = sidecar_loader.build_sidecar_graph(worldgen_seed_dir)
    filtered = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, building_ids={bid}
    )

    # (a) filter 后 << 全量。
    assert 0 < filtered.entry_count < full.entry_count
    assert len(filtered.batch.nodes) < len(full.batch.nodes)

    # (b) 所有 SidecarRuntimeRecord 节点都属于该 world。
    runtime_nodes = [
        n for n in filtered.batch.nodes if n.label == "SidecarRuntimeRecord"
    ]
    assert runtime_nodes  # 不能空
    for n in runtime_nodes:
        assert n.props["world_id"] == wid

    # (c) 跟"直接传等价 world_ids"应当等价（worldgen 1 world ↔ 1 building 双射）。
    via_world = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, world_ids={wid}
    )
    assert filtered.runtime_ids == via_world.runtime_ids
    assert filtered.entry_count == via_world.entry_count


def test_build_sidecar_graph_building_ids_no_match_yields_zero(
    worldgen_seed_dir: Path,
) -> None:
    """DEBT-034：building_ids 全部未命中 → 灌入 0 节点（不抛异常）。"""
    result = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, building_ids={"BLD-DEFINITELY-DOES-NOT-EXIST-XYZ-999"}
    )
    # 0 records + 0 entries。
    assert result.entry_count == 0
    assert len(result.runtime_ids) == 0
    runtime_nodes = [
        n for n in result.batch.nodes if n.label == "SidecarRuntimeRecord"
    ]
    assert runtime_nodes == []
    # audit 里有 unmatched warning。
    audit_warnings = " | ".join(result.audit.warnings)
    assert "DEBT-034" in audit_warnings
    assert "not found" in audit_warnings


def test_build_sidecar_graph_building_ids_intersect_with_world_ids(
    worldgen_seed_dir: Path,
) -> None:
    """DEBT-034：building_ids 与 world_ids 同时给 → 取交集。

    选 building B（对应 world W_B）+ world_ids={W_other}（不含 W_B）→ 交集空 → 0 节点。
    """
    wid_b, bid_b = _pick_one_world_and_building(worldgen_seed_dir)

    # 另找一个 world（不等于 wid_b）。
    from evo_agent_baseline.ingest._common import opt_str, read_parquet_rows

    wid_other: str | None = None
    for path in worldgen_seed_dir.rglob("buildings.parquet"):
        for row in read_parquet_rows(path):
            wid = opt_str(row.get("world_id"))
            if wid and wid != wid_b:
                wid_other = wid
                break
        if wid_other:
            break
    if wid_other is None:
        pytest.skip("seed 内只有 1 个 world，无法测交集 case")

    result = sidecar_loader.build_sidecar_graph(
        worldgen_seed_dir, world_ids={wid_other}, building_ids={bid_b}
    )
    # 交集为空 → 0 节点。
    assert result.entry_count == 0
    assert len(result.runtime_ids) == 0
