"""W0 + W1 + W2 共用 parquet 列存（column store）I/O — 全替换 v1 (2026-05-10).

替换 3 个 JSON bundle（>10× 压缩目标）：
- WorldgenWorldBundles.v2.json     -> 9 张 parquet 子表（在 directory 下）（W0+W1 输出）
- WorldgenSidecarRuntimeBundle.v2.json -> 3 张 parquet 子表（W1 sidecar 派生输出）
- WorldgenNormativeProjection.v2.json  -> 6 张 parquet 子表（**W2 法规映射层输出**，含 coverage_control_metadata）

Schema 由 W0 规格 15 parquet schema 定义；本模块是 pyarrow 实现工具，**W0 / W1 / W2 三层共用** parquet helper（list/struct pyarrow type 表达 + dict encoding 等）。

接口:
- write_world_bundles_parquet / read_world_bundles_parquet            （W0+W1 输出）
- write_sidecar_runtime_parquet / read_sidecar_runtime_parquet        （W1 sidecar 派生）
- write_normative_projection_parquet / read_normative_projection_parquet（**W2 工具，按 W2 规格 09 §1 NormativeProjection 输出契约**——本模块物理位置在 worldgen/ subdir 内是因为 W0/W1/W2 parquet 实现共享 pyarrow helper + schema 由 W0 规格 15 统一定义）

每个 directory 内部固定的 parquet 文件名见模块底部 _CONST_DIRS.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq


# -----------------------------------------------------------------------------
# JSON helpers — 用于嵌套 dict / 不规则结构 → string 列存储 (Decision B)
# -----------------------------------------------------------------------------


def _to_json(value: Any) -> Optional[str]:
    """嵌套结构 → JSON 串；None → None（保留 null 列语义）.

    sort_keys=True 不开 — 业务 dict 如 derived_outcomes 内键顺序由生成路径决定，
    强排序会破坏与 JSON dump 等价性（pydantic model_dump 也保留字段定义顺序）.
    """
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _from_json(value: Optional[str]) -> Any:
    """JSON 串 → 还原；None / 空串 → None."""
    if value is None or value == "":
        return None
    return json.loads(value)


# -----------------------------------------------------------------------------
# ZSTD 压缩参数（Decision G）
# -----------------------------------------------------------------------------
_PARQUET_KW = dict(compression="zstd", compression_level=3)


def _write_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, **_PARQUET_KW)


def _read_table(path: Path) -> pa.Table:
    return pq.read_table(path)


def _table_to_dicts(table: pa.Table) -> List[Dict[str, Any]]:
    """pyarrow.Table -> list[dict] with native Python types (preserves None)."""
    return table.to_pylist()


# =============================================================================
# 1. WorldBundles directory layout
# =============================================================================


_WB_FILES = {
    "meta": "worldgen_world_bundles_meta.parquet",
    "buildings": "buildings.parquet",
    "fragments": "fragments.parquet",
    "components": "components.parquet",
    "locations": "locations.parquet",
    "coverage_relations": "coverage_relations.parquet",
    "fragment_states": "fragment_states.parquet",
    "specialized_states": "specialized_states.parquet",
    "measurements": "measurements.parquet",
}


def write_world_bundles_parquet(out_dir: Path, payload: Dict[str, Any]) -> Path:
    """写整个 WorldBundles bundle 到 out_dir 下 9 个 parquet 文件.

    payload schema (与原 JSON 等价):
        {
          "version": ..., "generated_at": ..., "registry_bundle_hash": ...,
          "batch_config_hash": ..., "deterministic_key": ...,
          "buildings": [WorldBundle.model_dump(mode="json"), ...]
        }
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- meta ----
    meta_table = pa.table({
        "version": [payload.get("version")],
        "generated_at": [payload.get("generated_at")],
        "registry_bundle_hash": [payload.get("registry_bundle_hash")],
        "batch_config_hash": [payload.get("batch_config_hash")],
        "deterministic_key": [payload.get("deterministic_key")],
    })
    _write_table(meta_table, out_dir / _WB_FILES["meta"])

    buildings: List[Dict[str, Any]] = payload.get("buildings", [])

    # 每张表的列累积器
    bld_rows: List[Dict[str, Any]] = []
    frag_rows: List[Dict[str, Any]] = []
    comp_rows: List[Dict[str, Any]] = []
    loc_rows: List[Dict[str, Any]] = []
    cov_rows: List[Dict[str, Any]] = []
    fs_rows: List[Dict[str, Any]] = []  # fragment_states
    sp_rows: List[Dict[str, Any]] = []  # specialized_states
    msr_rows: List[Dict[str, Any]] = []

    for b_idx, bw in enumerate(buildings):
        world_id = bw["world_id"]
        b = bw["building"]
        # W0-008 (2026-05-21)：building_template_id / building_name / unit_count 由
        # building_metadata 字段承载（spec 04 §4 BuildingContext 收紧到 8 字段 contract）.
        # parquet schema 仍保留这 3 列以维持 spec 15 §4.2 行格式 + generator round-trip 重建 batch 所需.
        bm = bw.get("building_metadata") or {}
        bld_rows.append({
            "seq_no": b_idx,
            "world_id": world_id,
            "schema_version": bw.get("schema_version"),
            "generator_version": bw.get("generator_version"),
            "random_seed": bw.get("random_seed"),
            "building_id": b.get("building_id"),
            "building_template_id": bm.get("building_template_id"),
            "building_name": bm.get("building_name"),
            "building_use": b.get("building_use"),
            "structure_type": b.get("structure_type"),
            "age_years": b.get("age_years"),
            "storey_count": b.get("storey_count"),
            "unit_count": bm.get("unit_count"),
            "primary_materials": b.get("primary_materials") or [],
            "configuration_tags": b.get("configuration_tags") or [],
            "occupancy_state": b.get("occupancy_state"),
            # W1-004 顶层 derived_outcomes 字段（spec 8 §5 + §3.B）serialize 为 JSON 字符串
            "derived_outcomes_json": _to_json(bw.get("derived_outcomes") or {}),
        })

        for i, frag in enumerate(bw.get("fragments", [])):
            # W0-004 step 4 (2026-05-21)：fragments.parquet 收窄到 spec 04 §7 9 字段
            # reference-based contract + 2 索引（world_id / seq_no）+ coverage_relation_ids
            # 反向 join 索引（spec 15 §4.3）.物理上下文（has_rebar / cover_depth_mm /
            # material_system / structural_role / nominal_visible_area_m2 / nominal_length_m /
            # section_thickness_mm / surface_position / exposure_zone / fragment_scope /
            # component_type_id / building_metadata / *_graph_* / specialized_domains 等）已
            # 撤出本表，消费方按 spec 06 §0.1 reference 反查 components.parquet / locations.parquet /
            # buildings.parquet / 各专项域表.
            frag_rows.append({
                "world_id": world_id,
                "seq_no": i,
                "fragment_id": frag.get("fragment_id"),
                "fragment_template_id": frag.get("fragment_template_id"),
                "component_id": frag.get("component_id"),
                "location_id": frag.get("location_id"),
                "fragment_role": frag.get("fragment_role"),
                "fragment_area_m2": frag.get("fragment_area_m2"),
                "fragment_length_m": frag.get("fragment_length_m"),
                "in_scope": frag.get("in_scope"),
                "exclusion_reason": frag.get("exclusion_reason"),
                # spec 04 §7 9 字段外但仍是 fragment-level 反向 join 索引（spec 15 §4.3 表注）
                "coverage_relation_ids": frag.get("coverage_relation_ids") or [],
            })

        for i, comp in enumerate(bw.get("components", [])):
            # W0-004 step 4 (2026-05-21)：components.parquet 加 cover_depth_mm 列（spec 15 §4.4）；
            # RC 类型必填非 null，其他材质 null.
            comp_rows.append({
                "world_id": world_id,
                "seq_no": i,
                "component_id": comp.get("component_id"),
                "component_type": comp.get("component_type"),
                "parent_component_id": comp.get("parent_component_id"),
                "material_system": comp.get("material_system"),
                "structural_role": comp.get("structural_role"),
                "location_id": comp.get("location_id"),
                "geometry_proxy_json": _to_json(comp.get("geometry_proxy") or {}),
                "cover_depth_mm": comp.get("cover_depth_mm"),
                "access_class": comp.get("access_class"),
            })

        for i, loc in enumerate(bw.get("locations", [])):
            loc_rows.append({
                "world_id": world_id,
                "seq_no": i,
                "location_id": loc.get("location_id"),
                "location_class": loc.get("location_class"),
                "exposure_zone": loc.get("exposure_zone"),
                "storey_band": loc.get("storey_band"),
                "spatial_tags": loc.get("spatial_tags") or [],
            })

        for i, cov in enumerate(bw.get("coverage_relations", [])):
            cov_rows.append({
                "world_id": world_id,
                "seq_no": i,
                "coverage_id": cov.get("coverage_id"),
                "coverage_relation_type": cov.get("coverage_relation_type"),
                "target_fragment_id": cov.get("target_fragment_id"),
                "coverage_state": cov.get("coverage_state"),
                "covered_area_m2": cov.get("covered_area_m2"),
                "inspected_area_m2": cov.get("inspected_area_m2"),
                "obscuration_class": cov.get("obscuration_class"),
            })

        # fragment_states 合表 — drivers / mechanisms / conditions / repair_assessment
        for state_type, list_key, id_key in (
            ("driver", "drivers", "driver_id"),
            ("mechanism", "mechanisms", "mechanism_state_id"),
            ("condition", "conditions", "condition_id"),
            ("repair_assessment", "repair_assessment_states", "repair_assessment_id"),
        ):
            for i, item in enumerate(bw.get(list_key, [])):
                fs_rows.append({
                    "world_id": world_id,
                    "seq_no": i,
                    "state_type": state_type,
                    "state_id": item.get(id_key),
                    "fragment_id": item.get("fragment_id"),
                    "payload_json": _to_json(item),
                })

        # specialized_states 合表 — drainage / ubw / fire_safety
        for state_type, list_key, id_key in (
            ("drainage", "drainage_states", "drainage_id"),
            ("ubw", "ubw_states", "ubw_id"),
            ("fire_safety", "fire_safety_states", "fire_state_id"),
        ):
            for i, item in enumerate(bw.get(list_key, [])):
                sp_rows.append({
                    "world_id": world_id,
                    "seq_no": i,
                    "state_type": state_type,
                    "state_id": item.get(id_key),
                    "payload_json": _to_json(item),
                })

        for i, m in enumerate(bw.get("measurements", [])):
            msr_rows.append({
                "world_id": world_id,
                "seq_no": i,
                "measurement_id": m.get("measurement_id"),
                "target_ref": m.get("target_ref"),
                "measurement_family": m.get("measurement_family"),
                "slot_id": m.get("slot_id"),
                "value_num": m.get("value_num"),
                "value_bool": m.get("value_bool"),
                "value_enum": m.get("value_enum"),
                "unit": m.get("unit"),
                "precision_class": m.get("precision_class"),
                "method_class": m.get("method_class"),
                "sample_count": m.get("sample_count"),
                "confidence_index": m.get("confidence_index"),
                "derivation_refs": m.get("derivation_refs") or [],
                "derivation_mode": m.get("derivation_mode"),
                # DEBT-020 round5 sub-task 6: qualifiers dict → JSON 编码（pyarrow LIST struct 复杂；用 str）
                "qualifiers_json": _to_json(m.get("qualifiers") or {}),
                "upstream_refs": m.get("upstream_refs") or [],
                "origin_chain_refs": m.get("origin_chain_refs") or [],
                "derived_from_measurement_ids": m.get("derived_from_measurement_ids") or [],
                "notes": m.get("notes") or [],
            })

    # 写出每张子表（空表也写，下游统一 read 不会 KeyError）
    _write_table(_rows_to_table(bld_rows, _SCHEMA_BUILDINGS), out_dir / _WB_FILES["buildings"])
    _write_table(_rows_to_table(frag_rows, _SCHEMA_FRAGMENTS), out_dir / _WB_FILES["fragments"])
    _write_table(_rows_to_table(comp_rows, _SCHEMA_COMPONENTS), out_dir / _WB_FILES["components"])
    _write_table(_rows_to_table(loc_rows, _SCHEMA_LOCATIONS), out_dir / _WB_FILES["locations"])
    _write_table(_rows_to_table(cov_rows, _SCHEMA_COVERAGE), out_dir / _WB_FILES["coverage_relations"])
    _write_table(_rows_to_table(fs_rows, _SCHEMA_FRAGMENT_STATES), out_dir / _WB_FILES["fragment_states"])
    _write_table(_rows_to_table(sp_rows, _SCHEMA_SPECIALIZED), out_dir / _WB_FILES["specialized_states"])
    _write_table(_rows_to_table(msr_rows, _SCHEMA_MEASUREMENTS), out_dir / _WB_FILES["measurements"])

    return out_dir


def read_world_bundles_parquet(in_dir: Path) -> Dict[str, Any]:
    """从 parquet directory 还原回 WorldBundles 原 JSON dict (with `buildings` list).

    与原 JSON payload 等价：可直接 json.dumps 出与旧格式相同结构.
    """
    meta_t = _read_table(in_dir / _WB_FILES["meta"])
    meta = meta_t.to_pylist()[0] if meta_t.num_rows else {}

    bld_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["buildings"]))
    frag_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["fragments"]))
    comp_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["components"]))
    loc_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["locations"]))
    cov_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["coverage_relations"]))
    fs_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["fragment_states"]))
    sp_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["specialized_states"]))
    msr_rows = _table_to_dicts(_read_table(in_dir / _WB_FILES["measurements"]))

    bld_rows.sort(key=lambda r: r["seq_no"])

    # group children by world_id
    by_world_frags: Dict[str, List[Dict[str, Any]]] = {}
    for r in frag_rows:
        by_world_frags.setdefault(r["world_id"], []).append(r)
    by_world_comps: Dict[str, List[Dict[str, Any]]] = {}
    for r in comp_rows:
        by_world_comps.setdefault(r["world_id"], []).append(r)
    by_world_locs: Dict[str, List[Dict[str, Any]]] = {}
    for r in loc_rows:
        by_world_locs.setdefault(r["world_id"], []).append(r)
    by_world_covs: Dict[str, List[Dict[str, Any]]] = {}
    for r in cov_rows:
        by_world_covs.setdefault(r["world_id"], []).append(r)
    # fragment_states by (world, state_type)
    by_world_fs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in fs_rows:
        by_world_fs.setdefault((r["world_id"], r["state_type"]), []).append(r)
    by_world_sp: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in sp_rows:
        by_world_sp.setdefault((r["world_id"], r["state_type"]), []).append(r)
    by_world_msr: Dict[str, List[Dict[str, Any]]] = {}
    for r in msr_rows:
        by_world_msr.setdefault(r["world_id"], []).append(r)

    buildings: List[Dict[str, Any]] = []
    for bld_row in bld_rows:
        wid = bld_row["world_id"]
        # W0-008 (2026-05-21)：building 块只承载 spec 04 §4 BuildingContext 8 字段 contract；
        # building_template_id / building_name / unit_count 走 building_metadata 子块.
        building_block = {
            "building_id": bld_row["building_id"],
            "building_use": bld_row["building_use"],
            "structure_type": bld_row["structure_type"],
            "age_years": bld_row["age_years"],
            "storey_count": bld_row["storey_count"],
            "primary_materials": list(bld_row["primary_materials"] or []),
            "configuration_tags": list(bld_row["configuration_tags"] or []),
            "occupancy_state": bld_row["occupancy_state"],
        }
        building_metadata_block = {
            "building_template_id": bld_row["building_template_id"],
            "building_name": bld_row["building_name"],
            "unit_count": bld_row["unit_count"],
        }

        # fragments
        frags_sorted = sorted(by_world_frags.get(wid, []), key=lambda r: r["seq_no"])
        fragments_out = [_unpack_fragment_row(r) for r in frags_sorted]
        comps_sorted = sorted(by_world_comps.get(wid, []), key=lambda r: r["seq_no"])
        components_out = [_unpack_component_row(r) for r in comps_sorted]
        locs_sorted = sorted(by_world_locs.get(wid, []), key=lambda r: r["seq_no"])
        locations_out = [_unpack_location_row(r) for r in locs_sorted]
        covs_sorted = sorted(by_world_covs.get(wid, []), key=lambda r: r["seq_no"])
        coverage_out = [_unpack_coverage_row(r) for r in covs_sorted]
        # fragment states：按 type 分桶
        drivers_out = _unpack_state_rows(by_world_fs.get((wid, "driver"), []))
        mechanisms_out = _unpack_state_rows(by_world_fs.get((wid, "mechanism"), []))
        conditions_out = _unpack_state_rows(by_world_fs.get((wid, "condition"), []))
        repair_out = _unpack_state_rows(by_world_fs.get((wid, "repair_assessment"), []))
        drainage_out = _unpack_state_rows(by_world_sp.get((wid, "drainage"), []))
        ubw_out = _unpack_state_rows(by_world_sp.get((wid, "ubw"), []))
        fire_out = _unpack_state_rows(by_world_sp.get((wid, "fire_safety"), []))
        msrs_sorted = sorted(by_world_msr.get(wid, []), key=lambda r: r["seq_no"])
        measurements_out = [_unpack_measurement_row(r) for r in msrs_sorted]

        buildings.append({
            "schema_version": bld_row["schema_version"],
            "world_id": wid,
            "generator_version": bld_row["generator_version"],
            "random_seed": bld_row["random_seed"],
            "building": building_block,
            # W0-008 (2026-05-21)：BuildingMetadata（3 字段，generator 内部 state；
            # W0-002 2026-05-21 rename，原 `BuildingInternalMetadata`）
            # round-trip 还原.
            "building_metadata": building_metadata_block,
            "fragments": fragments_out,
            "components": components_out,
            "locations": locations_out,
            "coverage_relations": coverage_out,
            "drivers": drivers_out,
            "mechanisms": mechanisms_out,
            "conditions": conditions_out,
            "drainage_states": drainage_out,
            "ubw_states": ubw_out,
            "fire_safety_states": fire_out,
            "repair_assessment_states": repair_out,
            "measurements": measurements_out,
            # W1-004 顶层 derived_outcomes 字段 round-trip 还原
            "derived_outcomes": _from_json(bld_row.get("derived_outcomes_json")) or {},
        })

    return {
        "version": meta.get("version"),
        "generated_at": meta.get("generated_at"),
        "registry_bundle_hash": meta.get("registry_bundle_hash"),
        "batch_config_hash": meta.get("batch_config_hash"),
        "deterministic_key": meta.get("deterministic_key"),
        "buildings": buildings,
    }


def _unpack_fragment_row(r: Dict[str, Any]) -> Dict[str, Any]:
    # W0-004 step 4 (2026-05-21)：fragments.parquet 收窄到 spec 04 §7 9 字段 reference-based
    # contract（spec 15 §4.3）；物理上下文（has_rebar / cover_depth_mm / material_system /
    # structural_role / nominal_visible_area_m2 / nominal_length_m / section_thickness_mm /
    # surface_position / exposure_zone / fragment_scope / component_type_id / building_metadata /
    # *_graph_* / specialized_domains 等）已撤出本表，消费方按 spec 06 §0.1 reference 反查路径
    # 走 ComponentNode / LocationNode / BuildingContext / 各专项域表.
    # 注：coverage_relation_ids 是 parquet 列（spec 15 §4.3 反向 join 索引），但 FragmentContext
    # pydantic class 不持有该字段（spec 04 §7 9 字段 contract）；返回的 dict 不带此 key
    # （round-trip 与 model_dump 一致）.
    return {
        "fragment_id": r["fragment_id"],
        "fragment_template_id": r["fragment_template_id"],
        "component_id": r["component_id"],
        "location_id": r["location_id"],
        "fragment_role": r["fragment_role"],
        "fragment_area_m2": r["fragment_area_m2"],
        "fragment_length_m": r["fragment_length_m"],
        "in_scope": r["in_scope"],
        "exclusion_reason": r["exclusion_reason"],
    }


def _unpack_component_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "component_id": r["component_id"],
        "component_type": r["component_type"],
        "parent_component_id": r["parent_component_id"],
        "material_system": r["material_system"],
        "structural_role": r["structural_role"],
        "location_id": r["location_id"],
        "geometry_proxy": _from_json(r.get("geometry_proxy_json")) or {},
        # W0-004 step 4 (2026-05-21)：spec 04 §5 + spec 15 §4.4 加 cover_depth_mm 列
        "cover_depth_mm": r["cover_depth_mm"],
        "access_class": r["access_class"],
    }


def _unpack_location_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "location_id": r["location_id"],
        "location_class": r["location_class"],
        "exposure_zone": r["exposure_zone"],
        "storey_band": r["storey_band"],
        "spatial_tags": list(r["spatial_tags"] or []),
    }


def _unpack_coverage_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coverage_id": r["coverage_id"],
        "coverage_relation_type": r["coverage_relation_type"],
        "target_fragment_id": r["target_fragment_id"],
        "coverage_state": r["coverage_state"],
        "covered_area_m2": r["covered_area_m2"],
        "inspected_area_m2": r["inspected_area_m2"],
        "obscuration_class": r["obscuration_class"],
    }


def _unpack_state_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows_sorted = sorted(rows, key=lambda r: r["seq_no"])
    return [_from_json(r["payload_json"]) for r in rows_sorted]


def _unpack_measurement_row(r: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "measurement_id": r["measurement_id"],
        "target_ref": r["target_ref"],
        "measurement_family": r["measurement_family"],
        "slot_id": r["slot_id"],
        "value_num": r["value_num"],
        "value_bool": r["value_bool"],
        "value_enum": r["value_enum"],
        "unit": r["unit"],
        "precision_class": r["precision_class"],
        "method_class": r["method_class"],
        "sample_count": r["sample_count"],
        "confidence_index": r["confidence_index"],
        "derivation_refs": list(r["derivation_refs"] or []),
        "derivation_mode": r["derivation_mode"],
        # DEBT-020 round5 sub-task 6: qualifiers JSON → dict (空 JSON {} → 空 dict)
        "qualifiers": _from_json(r.get("qualifiers_json")) or {},
        "upstream_refs": list(r["upstream_refs"] or []),
        "origin_chain_refs": list(r["origin_chain_refs"] or []),
        "derived_from_measurement_ids": list(r["derived_from_measurement_ids"] or []),
        "notes": list(r["notes"] or []),
    }
    # 还原 pydantic computed_field "value" — value_resolved() 等价（spec models.py value_resolved）
    if r["value_bool"] is not None:
        out["value"] = r["value_bool"]
    elif r["value_num"] is not None:
        out["value"] = r["value_num"]
    else:
        out["value"] = r["value_enum"]
    return out


# =============================================================================
# 2. Sidecar Runtime directory layout
# =============================================================================

_SC_FILES = {
    "meta": "sidecar_runtime_meta.parquet",
    "records": "sidecar_records.parquet",
    "entries": "sidecar_entries.parquet",
}

_SC_BUCKETS = (
    "facts", "runtime_markers", "artifact_requirement_state",
    "procedure_gate_state", "supervision_runtime_state", "completion_runtime_state",
)


def write_sidecar_runtime_parquet(out_dir: Path, payload: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_table = pa.table({
        "version": [payload.get("version")],
        "generated_at": [payload.get("generated_at")],
        "source_documents": [payload.get("source_documents") or []],
    })
    _write_table(meta_table, out_dir / _SC_FILES["meta"])

    rec_rows: List[Dict[str, Any]] = []
    ent_rows: List[Dict[str, Any]] = []
    for r_idx, rec in enumerate(payload.get("records", [])):
        rec_rows.append({
            "seq_no": r_idx,
            "runtime_id": rec.get("runtime_id"),
            "world_id": rec.get("world_id"),
            "projection_id": rec.get("projection_id"),
            "interface_ids": rec.get("interface_ids") or [],
        })
        for bucket in _SC_BUCKETS:
            for i, entry in enumerate(rec.get(bucket, []) or []):
                ent_rows.append({
                    "runtime_id": rec.get("runtime_id"),
                    "seq_no": i,
                    "entry_type": bucket,
                    "slot_id": entry.get("slot_id"),
                    "value_json": _to_json(entry.get("value")),
                    "unit": entry.get("unit"),
                    "qualifiers_json": _to_json(entry.get("qualifiers") or {}),
                    "time_anchor_key": entry.get("time_anchor_key"),
                    "source_refs": entry.get("source_refs") or [],
                    "notes": entry.get("notes") or [],
                })

    _write_table(_rows_to_table(rec_rows, _SCHEMA_SC_RECORDS), out_dir / _SC_FILES["records"])
    _write_table(_rows_to_table(ent_rows, _SCHEMA_SC_ENTRIES), out_dir / _SC_FILES["entries"])
    return out_dir


def read_sidecar_runtime_parquet(in_dir: Path) -> Dict[str, Any]:
    meta_t = _read_table(in_dir / _SC_FILES["meta"])
    meta = meta_t.to_pylist()[0] if meta_t.num_rows else {}
    rec_rows = _table_to_dicts(_read_table(in_dir / _SC_FILES["records"]))
    ent_rows = _table_to_dicts(_read_table(in_dir / _SC_FILES["entries"]))

    rec_rows.sort(key=lambda r: r["seq_no"])
    by_runtime: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for e in ent_rows:
        rid = e["runtime_id"]
        by_runtime.setdefault(rid, {b: [] for b in _SC_BUCKETS})
        by_runtime[rid][e["entry_type"]].append(e)

    records: List[Dict[str, Any]] = []
    for rec in rec_rows:
        rid = rec["runtime_id"]
        rec_buckets = by_runtime.get(rid, {b: [] for b in _SC_BUCKETS})
        out_rec: Dict[str, Any] = {
            "runtime_id": rid,
            "world_id": rec["world_id"],
            "projection_id": rec["projection_id"],
            "interface_ids": list(rec["interface_ids"] or []),
        }
        for bucket in _SC_BUCKETS:
            entries_sorted = sorted(rec_buckets.get(bucket, []), key=lambda e: e["seq_no"])
            out_rec[bucket] = [
                {
                    "slot_id": e["slot_id"],
                    "value": _from_json(e["value_json"]),
                    "unit": e.get("unit"),
                    "qualifiers": _from_json(e["qualifiers_json"]) or {},
                    "time_anchor_key": e["time_anchor_key"],
                    "source_refs": list(e["source_refs"] or []),
                    "notes": list(e["notes"] or []),
                }
                for e in entries_sorted
            ]
        records.append(out_rec)

    return {
        "version": meta.get("version"),
        "generated_at": meta.get("generated_at"),
        "source_documents": list(meta.get("source_documents") or []),
        "records": records,
    }


# =============================================================================
# 3. Normative Projection directory layout
# =============================================================================

_NP_FILES = {
    "meta": "normative_projection_meta.parquet",
    "projections": "projections.parquet",
    "matched_families": "matched_families.parquet",
    "threshold_evaluations": "threshold_evaluations.parquet",
    # W2-007（批次 D 2026-05-21）：per-world CoverageControlBatchMetadata
    # （spec 11 §3.2 6 字段）持久化到独立子表；不污染 meta（单行 batch meta）或
    # projections 表（per-projection 列）.
    "coverage_control_metadata": "coverage_control_metadata.parquet",
    "basis_items": "basis_items.parquet",
}

# DEBT-054 Block B.3：schema 版本 bump（threshold_regime_id 增列后的 forward-only 版本）。
# 旧 bundle 缺字段 = 前一代（projection_v1 / truth_v1），只读、不重算（B.3 legacy 只读）。
# 版本号进 NP meta parquet 新增列 + 外置 append-only cohort manifest（B.5），不原地打标旧字节。
PROJECTION_SCHEMA_VERSION = "projection_v2_regime"
TRUTH_SCHEMA_VERSION = "truth_v2_regime"
# legacy sentinel（读回缺列时用；truth_loader 亦引用）。
LEGACY_TRUTH_SCHEMA_VERSION = "truth_v1"

# DEBT-054 Block B.5 profile 标签（forward-only 修，2026-07-14）：cohort manifest 的
# canonical_profile_id / identity_schema 必须记**真实非空标签**——原空串占位会令
# profile 变而 parquet 字节不变时 manifest_hash 不变，破 B.5 冻结保护（profile bump 应翻 hash）。
#   - canonical_profile_id = 顶层中立包 canonical_profile.CANONICAL_PROFILE_ID（分层允许消费顶层中立包）。
#   - identity_schema = 显式 pending 常量占位（Block A closure 两阶段身份未落地于 W2 侧、
#     且分层单向禁 import evo_agent_baseline.closure）；Block A 落地后由 orchestrator 透传真实
#     closure identity_schema 值，届时 manifest_hash 变——正是"identity bump → manifest 变"预期锁。
from canonical_profile import CANONICAL_PROFILE_ID  # noqa: E402 顶层中立契约层，分层允许
IDENTITY_SCHEMA_PENDING = "obligation_identity_v2_pending"


def write_normative_projection_parquet(out_dir: Path, payload: Dict[str, Any]) -> Path:
    # W2 法规映射层输出 parquet 工具。schema 按 W2 规格 09 §1 NormativeProjection 输出契约
    # 拆 5 张子表（meta / projections / matched_families / threshold_evaluations /
    # basis_items），具体字段见 W0 规格 15 §4 parquet schema W2 段。本函数物理位置在
    # worldgen/parquet_io.py 是因为 W0+W1+W2 三层 parquet 实现共享 pyarrow helper。
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_table = pa.table({
        "version": [payload.get("version")],
        "generated_at": [payload.get("generated_at")],
        "registry_bundle_hash": [payload.get("registry_bundle_hash")],
        "deterministic_key": [payload.get("deterministic_key")],
        # DEBT-054 Block B.3：schema 版本号进 meta（forward-only，缺列的旧 bundle = v1 只读）。
        "projection_schema": [payload.get("projection_schema", PROJECTION_SCHEMA_VERSION)],
        "truth_schema": [payload.get("truth_schema", TRUTH_SCHEMA_VERSION)],
    })
    _write_table(meta_table, out_dir / _NP_FILES["meta"])

    proj_rows: List[Dict[str, Any]] = []
    mf_rows: List[Dict[str, Any]] = []
    th_rows: List[Dict[str, Any]] = []
    bi_rows: List[Dict[str, Any]] = []

    for bld_entry in payload.get("buildings", []):
        wid = bld_entry["world_id"]
        for p_idx, proj in enumerate(bld_entry.get("projections", [])):
            pid = proj["projection_id"]
            proj_rows.append({
                "world_id": wid,
                "seq_no_in_world": p_idx,
                "projection_id": pid,
                "projection_registry_id": proj.get("projection_registry_id"),
                "projection_family": proj.get("projection_family"),
                # SA-2 fix (2026-05-23)：NormativeProjection 必填字段往返保全.
                "fragment_id": proj.get("fragment_id"),
                "expected_verdict": proj.get("expected_verdict"),
                "projection_version": proj.get("projection_version"),
                "selected_family": proj.get("selected_family"),
                "projection_status": proj.get("projection_status"),
                "required_slots": proj.get("required_slots") or [],
                "unknown_reason_code": proj.get("unknown_reason_code"),
                "sidecar_join_status": proj.get("sidecar_join_status"),
                "severity_band": proj.get("severity_band"),
                "required_world_core_slots": proj.get("required_world_core_slots") or [],
                "required_measurement_slots": proj.get("required_measurement_slots") or [],
                "required_qualifier_slots": proj.get("required_qualifier_slots") or [],
                "required_sidecar_interfaces": proj.get("required_sidecar_interfaces") or [],
                "matched_component_refs": proj.get("matched_component_refs") or [],
                "matched_measurement_ids": proj.get("matched_measurement_ids") or [],
                "coverage_status": proj.get("coverage_status"),
                "notes": proj.get("notes") or [],
            })
            for f_idx, mf in enumerate(proj.get("matched_families", [])):
                mf_rows.append({
                    "projection_id": pid,
                    "seq_no": f_idx,
                    "family_id": mf.get("family_id"),
                    "applicability_score": mf.get("applicability_score"),
                    "applicability_state": mf.get("applicability_state"),
                    "trigger_ids": mf.get("trigger_ids") or [],
                    "rule_ids": mf.get("rule_ids") or [],
                    "slot_role_map_json": _to_json(mf.get("slot_role_map") or {}),
                    "verdict": mf.get("verdict"),
                })
                for t_idx, thr in enumerate(mf.get("threshold_evaluations", [])):
                    # DEBT-054 Block B.2 ⑥ writer 端 non-empty hard-fail：
                    # from_pylist(schema=) 对缺键成 null（非 hard-fail），且生产 executor
                    # 绕 Pydantic 直 append dict——故须逐 row 显式断言 threshold_regime_id
                    # 非空/非 null，防"忘透传"静默落 null 进 v2 parquet。
                    regime_id = thr.get("threshold_regime_id")
                    if not regime_id:
                        raise ValueError(
                            "threshold_regime_id_null_in_parquet_row: "
                            f"projection_id={pid} family={mf.get('family_id')} "
                            f"seq_no={t_idx} 的 threshold_evaluation 缺非空 threshold_regime_id"
                        )
                    th_rows.append({
                        "projection_id": pid,
                        "family_id": mf.get("family_id"),
                        "family_seq_no": f_idx,
                        "seq_no": t_idx,
                        "rule_id": thr.get("rule_id"),
                        "threshold_regime_id": regime_id,
                        "slot_id": thr.get("slot_id"),
                        "operator": thr.get("operator"),
                        "threshold_value_json": _to_json(thr.get("threshold_value")),
                        "observed_value_json": _to_json(thr.get("observed_value")),
                        "regime_tag": thr.get("regime_tag"),
                        "pass_bool": thr.get("pass_bool"),
                    })
            for b_idx, bi in enumerate(proj.get("basis_items", [])):
                bi_rows.append({
                    "projection_id": pid,
                    "seq_no": b_idx,
                    "basis_kind": bi.get("basis_kind"),
                    "basis_id": bi.get("basis_id"),
                    "family_id": bi.get("family_id"),
                    "rule_id": bi.get("rule_id"),
                    "slot_id": bi.get("slot_id"),
                    "source_projection_id": bi.get("source_projection_id"),
                    "operator": bi.get("operator"),
                    "threshold_value_json": _to_json(bi.get("threshold_value")),
                    "unit": bi.get("unit"),
                    "regime_tag": bi.get("regime_tag"),
                    "expected_value_json": _to_json(bi.get("expected_value")),
                    "statement_code": bi.get("statement_code"),
                    "reason_code": bi.get("reason_code"),
                    "candidate_known_families": bi.get("candidate_known_families") or [],
                    "observed_value_json": _to_json(bi.get("observed_value")),
                    "pass_bool": bi.get("pass_bool"),
                    "source_ref": bi.get("source_ref"),
                })

    _write_table(_rows_to_table(proj_rows, _SCHEMA_PROJECTIONS), out_dir / _NP_FILES["projections"])
    _write_table(_rows_to_table(mf_rows, _SCHEMA_MATCHED_FAMILIES), out_dir / _NP_FILES["matched_families"])
    _write_table(_rows_to_table(th_rows, _SCHEMA_THRESHOLD_EVALS), out_dir / _NP_FILES["threshold_evaluations"])
    _write_table(_rows_to_table(bi_rows, _SCHEMA_BASIS_ITEMS), out_dir / _NP_FILES["basis_items"])

    # W2-007 (批次 D 2026-05-21)：per-world CoverageControlBatchMetadata 子表
    # （spec 11 §3.2 6 字段；不污染 NormativeProjection / projections / matched_families /
    # threshold_evaluations / basis_items 表）.
    ccm_rows: List[Dict[str, Any]] = []
    for bld_entry in payload.get("buildings", []):
        wid = bld_entry["world_id"]
        meta = bld_entry.get("coverage_control_metadata")
        if not meta:
            continue
        ccm_rows.append({
            "world_id": wid,
            "coverage_control_profile_id": meta.get("coverage_control_profile_id", ""),
            # bucket counts 用 JSON 字符串透传（避免 schema 强约束 5 个 bucket 名）.
            "raw_candidate_bucket_counts_json": _to_json(
                meta.get("raw_candidate_bucket_counts") or {}
            ),
            "accepted_bucket_counts_json": _to_json(
                meta.get("accepted_bucket_counts") or {}
            ),
            "rejected_bucket_counts_json": _to_json(
                meta.get("rejected_bucket_counts") or {}
            ),
            "bucket_definition_version": meta.get("bucket_definition_version", ""),
            "public_report_note": meta.get("public_report_note", ""),
        })
    _write_table(
        _rows_to_table(ccm_rows, _SCHEMA_COVERAGE_CONTROL_METADATA),
        out_dir / _NP_FILES["coverage_control_metadata"],
    )

    # DEBT-054 Block B.5：外置 append-only 双层 hash cohort manifest（forward-only）。
    # 记录本 cohort 全 parquet 文件字节+行数（tree_hash）+ schema/profile 标识（manifest_hash），
    # 供后续 evaluator/度量序列溯源；不原地打标旧字节、不重算冻结数字。
    # canonical_profile_id 记真实 profile（CANONICAL_PROFILE_ID）；identity_schema 记 pending
    # 常量占位（Block A 未落地，见 _write_cohort_manifest 内注）——二者均非空，profile/identity
    # bump 时 manifest_hash 必变（冻结保护成立）。
    _write_cohort_manifest(
        out_dir,
        payload,
        row_counts={
            _NP_FILES["meta"]: 1,
            _NP_FILES["projections"]: len(proj_rows),
            _NP_FILES["matched_families"]: len(mf_rows),
            _NP_FILES["threshold_evaluations"]: len(th_rows),
            _NP_FILES["basis_items"]: len(bi_rows),
            _NP_FILES["coverage_control_metadata"]: len(ccm_rows),
        },
    )
    return out_dir


def _write_cohort_manifest(
    out_dir: Path, payload: Dict[str, Any], row_counts: Dict[str, int]
) -> None:
    """B.5 helper：对刚落盘的 NP cohort 文件计算并追加 cohort manifest（append-only）。"""
    from workflow_engine.cohort_manifest import (
        COHORT_MANIFEST_FILENAME,
        append_cohort_manifest,
        compute_cohort_manifest,
        file_entry,
    )

    files = []
    for rel_name, row_count in sorted(row_counts.items()):
        abs_path = out_dir / rel_name
        if not abs_path.exists():
            continue
        files.append(file_entry(rel_name, abs_path, row_count))

    # DEBT-054 Block B.5 forward-only 修（2026-07-14）：profile 标签记真实非空值。
    # 调用方（orchestrator，如 validation.py）应显式在 payload 传 canonical_profile_id /
    # identity_schema；**键缺失**（未传）时回落 writer 边界常量（CANONICAL_PROFILE_ID /
    # IDENTITY_SCHEMA_PENDING，均非空）。**键存在但为空串**则 hard-fail——防再退化空标签
    # （空标签令 profile/identity bump 时字节不变、manifest_hash 不变，破 B.5 冻结保护）。
    canonical_profile_id = payload.get("canonical_profile_id")
    if canonical_profile_id is None:
        canonical_profile_id = CANONICAL_PROFILE_ID
    identity_schema = payload.get("identity_schema")
    if identity_schema is None:
        identity_schema = IDENTITY_SCHEMA_PENDING
    if not canonical_profile_id:
        raise ValueError(
            "canonical_profile_id_empty_at_cohort_manifest: cohort manifest 的 "
            "canonical_profile_id 不得为空串（Block B.5 冻结保护——空标签令 profile bump 不翻 manifest_hash）"
        )
    if not identity_schema:
        raise ValueError(
            "identity_schema_empty_at_cohort_manifest: cohort manifest 的 identity_schema "
            "不得为空串（Block B.5 冻结保护——空标签令 identity bump 不翻 manifest_hash）"
        )

    manifest = compute_cohort_manifest(
        files,
        identity_schema=identity_schema,
        truth_schema=payload.get("truth_schema", TRUTH_SCHEMA_VERSION),
        projection_schema=payload.get("projection_schema", PROJECTION_SCHEMA_VERSION),
        canonical_profile_id=canonical_profile_id,
        cohort_id=payload.get("cohort_id", payload.get("deterministic_key", "")) or "",
        config_anchors=payload.get("config_anchors")
        or {
            "registry_bundle_hash": payload.get("registry_bundle_hash"),
            "generated_at": payload.get("generated_at"),
            "version": payload.get("version"),
        },
    )
    append_cohort_manifest(out_dir / COHORT_MANIFEST_FILENAME, manifest)


def read_normative_projection_parquet(in_dir: Path) -> Dict[str, Any]:
    meta_t = _read_table(in_dir / _NP_FILES["meta"])
    meta = meta_t.to_pylist()[0] if meta_t.num_rows else {}
    proj_rows = _table_to_dicts(_read_table(in_dir / _NP_FILES["projections"]))
    mf_rows = _table_to_dicts(_read_table(in_dir / _NP_FILES["matched_families"]))
    th_rows = _table_to_dicts(_read_table(in_dir / _NP_FILES["threshold_evaluations"]))
    bi_rows = _table_to_dicts(_read_table(in_dir / _NP_FILES["basis_items"]))
    # W2-007 (批次 D 2026-05-21)：coverage_control_metadata 子表（可缺，老 batch 输出无此文件）.
    ccm_path = in_dir / _NP_FILES["coverage_control_metadata"]
    ccm_by_world: Dict[str, Dict[str, Any]] = {}
    if ccm_path.exists():
        ccm_rows = _table_to_dicts(_read_table(ccm_path))
        for c in ccm_rows:
            ccm_by_world[c["world_id"]] = {
                "coverage_control_profile_id": c.get("coverage_control_profile_id", ""),
                "raw_candidate_bucket_counts": _from_json(
                    c.get("raw_candidate_bucket_counts_json")
                ) or {},
                "accepted_bucket_counts": _from_json(
                    c.get("accepted_bucket_counts_json")
                ) or {},
                "rejected_bucket_counts": _from_json(
                    c.get("rejected_bucket_counts_json")
                ) or {},
                "bucket_definition_version": c.get("bucket_definition_version", ""),
                "public_report_note": c.get("public_report_note", ""),
            }

    # group threshold evals by (projection_id, family_id, family_seq_no)
    th_by_key: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}
    for t in th_rows:
        key = (t["projection_id"], t["family_id"], t["family_seq_no"])
        th_by_key.setdefault(key, []).append(t)

    mf_by_proj: Dict[str, List[Dict[str, Any]]] = {}
    for m in mf_rows:
        mf_by_proj.setdefault(m["projection_id"], []).append(m)

    bi_by_proj: Dict[str, List[Dict[str, Any]]] = {}
    for b in bi_rows:
        bi_by_proj.setdefault(b["projection_id"], []).append(b)

    proj_by_world: Dict[str, List[Dict[str, Any]]] = {}
    for p in proj_rows:
        proj_by_world.setdefault(p["world_id"], []).append(p)

    buildings: List[Dict[str, Any]] = []
    # 维持 world_id 在 projections 表里出现的首次顺序
    seen: List[str] = []
    seen_set: set = set()
    for p in proj_rows:
        if p["world_id"] not in seen_set:
            seen.append(p["world_id"])
            seen_set.add(p["world_id"])
    for wid in seen:
        projs = sorted(proj_by_world.get(wid, []), key=lambda r: r["seq_no_in_world"])
        out_projs: List[Dict[str, Any]] = []
        for p in projs:
            pid = p["projection_id"]
            mfs = sorted(mf_by_proj.get(pid, []), key=lambda r: r["seq_no"])
            mfs_out: List[Dict[str, Any]] = []
            for mf in mfs:
                key = (pid, mf["family_id"], mf["seq_no"])
                ths = sorted(th_by_key.get(key, []), key=lambda t: t["seq_no"])
                ths_out = [
                    {
                        "rule_id": t["rule_id"],
                        # DEBT-054 Block B.2 ⑥ readback：v2 bundle 有该列往返还原；
                        # legacy v1 bundle 缺列 → .get() 得 None（只读、不重算）。
                        "threshold_regime_id": t.get("threshold_regime_id"),
                        "slot_id": t["slot_id"],
                        "operator": t["operator"],
                        "threshold_value": _from_json(t["threshold_value_json"]),
                        "observed_value": _from_json(t["observed_value_json"]),
                        "regime_tag": t["regime_tag"],
                        "pass_bool": t["pass_bool"],
                    }
                    for t in ths
                ]
                mfs_out.append({
                    "family_id": mf["family_id"],
                    "applicability_score": mf["applicability_score"],
                    "applicability_state": mf["applicability_state"],
                    "trigger_ids": list(mf["trigger_ids"] or []),
                    "rule_ids": list(mf["rule_ids"] or []),
                    "slot_role_map": _from_json(mf["slot_role_map_json"]) or {},
                    "threshold_evaluations": ths_out,
                    "verdict": mf["verdict"],
                })
            bis = sorted(bi_by_proj.get(pid, []), key=lambda r: r["seq_no"])
            bis_out = [_unpack_basis_item_row(b) for b in bis]
            out_projs.append({
                "projection_id": pid,
                "projection_registry_id": p["projection_registry_id"],
                "projection_family": p["projection_family"],
                "world_id": wid,
                # SA-2 fix (2026-05-23)：NormativeProjection 必填字段往返还原.
                "fragment_id": p["fragment_id"],
                "expected_verdict": p["expected_verdict"],
                "projection_version": p["projection_version"],
                "matched_families": mfs_out,
                "selected_family": p["selected_family"],
                "projection_status": p["projection_status"],
                "required_slots": list(p["required_slots"] or []),
                "basis_items": bis_out,
                "unknown_reason_code": p["unknown_reason_code"],
                "sidecar_join_status": p["sidecar_join_status"],
                "severity_band": p["severity_band"],
                "required_world_core_slots": list(p["required_world_core_slots"] or []),
                "required_measurement_slots": list(p["required_measurement_slots"] or []),
                "required_qualifier_slots": list(p["required_qualifier_slots"] or []),
                "required_sidecar_interfaces": list(p["required_sidecar_interfaces"] or []),
                "matched_component_refs": list(p["matched_component_refs"] or []),
                "matched_measurement_ids": list(p["matched_measurement_ids"] or []),
                "coverage_status": p["coverage_status"],
                "notes": list(p["notes"] or []),
            })
        building_entry: Dict[str, Any] = {
            "world_id": wid,
            "projection_count": len(out_projs),
            "projections": out_projs,
        }
        # W2-007 (批次 D 2026-05-21)：coverage_control_metadata 反序列回 building 字段
        # （spec 11 §3.2 6 字段；老 batch 输出无此子表时跳过）.
        if wid in ccm_by_world:
            building_entry["coverage_control_metadata"] = ccm_by_world[wid]
        buildings.append(building_entry)

    return {
        "version": meta.get("version"),
        "generated_at": meta.get("generated_at"),
        "registry_bundle_hash": meta.get("registry_bundle_hash"),
        "deterministic_key": meta.get("deterministic_key"),
        "buildings": buildings,
    }


def _unpack_basis_item_row(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "basis_kind": b["basis_kind"],
        "basis_id": b["basis_id"],
        "family_id": b["family_id"],
        "rule_id": b["rule_id"],
        "slot_id": b["slot_id"],
        "source_projection_id": b["source_projection_id"],
        "operator": b["operator"],
        "threshold_value": _from_json(b["threshold_value_json"]),
        "unit": b["unit"],
        "regime_tag": b["regime_tag"],
        "expected_value": _from_json(b["expected_value_json"]),
        "statement_code": b["statement_code"],
        "reason_code": b["reason_code"],
        "candidate_known_families": list(b["candidate_known_families"] or []),
        "observed_value": _from_json(b["observed_value_json"]),
        "pass_bool": b["pass_bool"],
        "source_ref": b["source_ref"],
    }


# =============================================================================
# 4. PyArrow schemas — explicit for empty-table compatibility
# =============================================================================

# 关键：空表 (rows=[]) 仍要写出 parquet 文件且字段类型固定，否则 read 时 schema 变 null type
# 所有 list<X> 必须显式声明 type，否则 pyarrow 会推断成 null

_S = pa.string()
_I = pa.int64()
_F = pa.float64()
_B = pa.bool_()
_LS = pa.list_(pa.string())


_SCHEMA_BUILDINGS = pa.schema([
    ("seq_no", _I),
    ("world_id", _S),
    ("schema_version", _S),
    ("generator_version", _S),
    ("random_seed", _I),
    ("building_id", _S),
    ("building_template_id", _S),
    ("building_name", _S),
    ("building_use", _S),
    ("structure_type", _S),
    ("age_years", _F),
    ("storey_count", _I),
    ("unit_count", _I),
    ("primary_materials", _LS),
    ("configuration_tags", _LS),
    ("occupancy_state", _S),
    # W1-004 顶层 derived_outcomes 字段（spec 8 §5 + §3.B）serialize 为 JSON 字符串
    ("derived_outcomes_json", _S),
])

# W0-004 step 4 (2026-05-21)：spec 15 §4.3 fragments.parquet 收窄到 9 字段 reference-based
# contract + 2 索引（world_id / seq_no）+ coverage_relation_ids 反向 join 索引（fragment-level
# identifier 索引，非物理 denormalization）.物理上下文字段（has_rebar / cover_depth_mm /
# material_system 等）已撤出本表，消费方按 spec 06 §0.1 reference 反查 components.parquet /
# locations.parquet / 各专项域表.
_SCHEMA_FRAGMENTS = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("fragment_id", _S),
    ("fragment_template_id", _S),
    ("component_id", _S),
    ("location_id", _S),
    ("fragment_role", _S),
    ("fragment_area_m2", _F),
    ("fragment_length_m", _F),
    ("in_scope", _B),
    ("exclusion_reason", _S),
    ("coverage_relation_ids", _LS),
])

# W0-004 step 4 (2026-05-21)：spec 15 §4.4 + spec 04 §5 加 cover_depth_mm 列（RC-specific
# 物理参数，RC 类型必填非 null，其他材质 null）.
_SCHEMA_COMPONENTS = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("component_id", _S),
    ("component_type", _S),
    ("parent_component_id", _S),
    ("material_system", _S),
    ("structural_role", _S),
    ("location_id", _S),
    ("geometry_proxy_json", _S),
    ("cover_depth_mm", _F),
    ("access_class", _S),
])

_SCHEMA_LOCATIONS = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("location_id", _S),
    ("location_class", _S),
    ("exposure_zone", _S),
    ("storey_band", _S),
    ("spatial_tags", _LS),
])

_SCHEMA_COVERAGE = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("coverage_id", _S),
    ("coverage_relation_type", _S),
    ("target_fragment_id", _S),
    ("coverage_state", _S),
    ("covered_area_m2", _F),
    ("inspected_area_m2", _F),
    ("obscuration_class", _S),
])

_SCHEMA_FRAGMENT_STATES = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("state_type", _S),
    ("state_id", _S),
    ("fragment_id", _S),
    ("payload_json", _S),
])

_SCHEMA_SPECIALIZED = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("state_type", _S),
    ("state_id", _S),
    ("payload_json", _S),
])

_SCHEMA_MEASUREMENTS = pa.schema([
    ("world_id", _S),
    ("seq_no", _I),
    ("measurement_id", _S),
    ("target_ref", _S),
    ("measurement_family", _S),
    ("slot_id", _S),
    ("value_num", _F),
    ("value_bool", _B),
    ("value_enum", _S),
    ("unit", _S),
    ("precision_class", _S),
    ("method_class", _S),
    ("sample_count", _I),
    ("confidence_index", _F),
    ("derivation_refs", _LS),
    ("derivation_mode", _S),
    # DEBT-020 round5 sub-task 6 (2026-05-10): qualifiers 携带 fragment 物理 metadata
    # （rebar_type / rebar_location / corrosion_loss_type）。dict[str, Any] → JSON string 编解.
    ("qualifiers_json", _S),
    ("upstream_refs", _LS),
    ("origin_chain_refs", _LS),
    ("derived_from_measurement_ids", _LS),
    ("notes", _LS),
])

_SCHEMA_SC_RECORDS = pa.schema([
    ("seq_no", _I),
    ("runtime_id", _S),
    ("world_id", _S),
    ("projection_id", _S),
    ("interface_ids", _LS),
])

_SCHEMA_SC_ENTRIES = pa.schema([
    ("runtime_id", _S),
    ("seq_no", _I),
    ("entry_type", _S),
    ("slot_id", _S),
    ("value_json", _S),
    ("unit", _S),
    ("qualifiers_json", _S),
    ("time_anchor_key", _S),
    ("source_refs", _LS),
    ("notes", _LS),
])

_SCHEMA_PROJECTIONS = pa.schema([
    ("world_id", _S),
    ("seq_no_in_world", _I),
    ("projection_id", _S),
    ("projection_registry_id", _S),
    ("projection_family", _S),
    # SA-2 fix (2026-05-23)：fragment_id / expected_verdict 是 NormativeProjection
    # 模型必填字段（W2-002 / W2-001，regulation_projection_models.py，no-default），
    # 原 schema 漏列导致 parquet 往返后这两个法规投影必需语义丢失。
    ("fragment_id", _S),
    ("expected_verdict", _S),  # 4 enum pass/fail/unknown/not_applicable
    ("projection_version", _S),
    ("selected_family", _S),
    ("projection_status", _S),
    ("required_slots", _LS),
    ("unknown_reason_code", _S),
    ("sidecar_join_status", _S),
    ("severity_band", _S),
    ("required_world_core_slots", _LS),
    ("required_measurement_slots", _LS),
    ("required_qualifier_slots", _LS),
    ("required_sidecar_interfaces", _LS),
    ("matched_component_refs", _LS),
    ("matched_measurement_ids", _LS),
    ("coverage_status", _S),
    ("notes", _LS),
])

_SCHEMA_MATCHED_FAMILIES = pa.schema([
    ("projection_id", _S),
    ("seq_no", _I),
    ("family_id", _S),
    ("applicability_score", _F),
    ("applicability_state", _S),
    ("trigger_ids", _LS),
    ("rule_ids", _LS),
    ("slot_role_map_json", _S),
    ("verdict", _S),
])

_SCHEMA_THRESHOLD_EVALS = pa.schema([
    ("projection_id", _S),
    ("family_id", _S),
    ("family_seq_no", _I),
    ("seq_no", _I),
    ("rule_id", _S),
    # DEBT-054 Block B.1：规则卡制度键增列（required；⊥ regime_tag 观测分箱）。
    ("threshold_regime_id", _S),
    ("slot_id", _S),
    ("operator", _S),
    ("threshold_value_json", _S),
    ("observed_value_json", _S),
    ("regime_tag", _S),
    ("pass_bool", _B),
])

_SCHEMA_BASIS_ITEMS = pa.schema([
    ("projection_id", _S),
    ("seq_no", _I),
    ("basis_kind", _S),
    ("basis_id", _S),
    ("family_id", _S),
    ("rule_id", _S),
    ("slot_id", _S),
    ("source_projection_id", _S),
    ("operator", _S),
    ("threshold_value_json", _S),
    ("unit", _S),
    ("regime_tag", _S),
    ("expected_value_json", _S),
    ("statement_code", _S),
    ("reason_code", _S),
    ("candidate_known_families", _LS),
    ("observed_value_json", _S),
    ("pass_bool", _B),
    ("source_ref", _S),
])


# W2-007 (批次 D 2026-05-21)：spec 11 §3.2 CoverageControlBatchMetadata 6 字段 schema.
# bucket counts 用 JSON 字符串透传（避免 5 个 bucket 名 schema 强约束 + parquet null 兼容）.
_SCHEMA_COVERAGE_CONTROL_METADATA = pa.schema([
    ("world_id", _S),
    ("coverage_control_profile_id", _S),
    ("raw_candidate_bucket_counts_json", _S),
    ("accepted_bucket_counts_json", _S),
    ("rejected_bucket_counts_json", _S),
    ("bucket_definition_version", _S),
    ("public_report_note", _S),
])


# =============================================================================
# Common helper: rows[dict] -> pa.Table with explicit schema
# =============================================================================


def _rows_to_table(rows: List[Dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """Convert list[dict] -> pyarrow Table 用显式 schema, 兼容空 rows 与 null 列.

    pa.Table.from_pylist(rows, schema=schema) 直接接受空 list。
    """
    return pa.Table.from_pylist(rows, schema=schema)


# =============================================================================
# Convenience: detect whether a path is parquet directory or legacy JSON file
# =============================================================================


def is_world_bundles_parquet_dir(path: Path) -> bool:
    return path.is_dir() and (path / _WB_FILES["meta"]).exists()


def is_sidecar_runtime_parquet_dir(path: Path) -> bool:
    return path.is_dir() and (path / _SC_FILES["meta"]).exists()


def is_normative_projection_parquet_dir(path: Path) -> bool:
    return path.is_dir() and (path / _NP_FILES["meta"]).exists()
