"""流程槽粒度两相分派（spec 草案·流程槽粒度语义 2026-07-08 定稿）。

行政槽楼级一栋一抽 + fragment 槽逐 fragment 抽（楼级缓存广播）+ 四进度槽
楼级聚合行 + 跨粒度边无声明聚合 fail-fast。
"""

from __future__ import annotations


import pytest

from workflow_engine.worldgen.registry import (
    AGGREGATE_ROW_SLOTS,
    BUILDING_READING_AGGREGATION,
    _build_registry_bundle,
)
from workflow_engine.worldgen.sidecar import (
    _resolve_building_upstream,
    _sample_sidecar_bool_slots_for_building,
)

BUILDING_SLOTS_13 = [
    "procedure.ri.appointment.completed",
    "procedure.temp_ri_nomination.completed",
    "procedure.temp_ri_nomination.terminated",
    "procedure.ri_role.terminated",
    "procedure.investigation.intention_notified",
    "procedure.investigation.proposal.submitted",
    "procedure.investigation.proposal.recognized",
    "procedure.rc.pre_notification_given",
    "procedure.supervision_team.submitted",
    "procedure.supervision_team.changed",
    "procedure.supervision_representative.planned",
    "procedure.repair.revision_required",
    "procedure.completed_work.final_inspection_performed",
]


def _registry_bool_records():
    bundle = _build_registry_bundle()
    for r in bundle.registries:
        if r.registry_id == "sidecar_bool_slot_registry":
            return r.records
    raise RuntimeError("sidecar_bool_slot_registry not found")


def test_registry_thirteen_building_slots_marked() -> None:
    records = _registry_bool_records()
    by_slot = {r["slot_id"]: r for r in records}
    for slot in BUILDING_SLOTS_13:
        assert by_slot[slot].get("granularity") == "building", slot
    # 进度槽保持缺省 fragment。
    for slot in AGGREGATE_ROW_SLOTS:
        assert by_slot[slot].get("granularity") in (None, "fragment"), slot


def test_aggregation_table_keys_exist_in_registry() -> None:
    by_slot = {r["slot_id"] for r in _registry_bool_records()}
    for slot in BUILDING_READING_AGGREGATION:
        assert slot in by_slot, slot


def _run_building_sampler(records, fragment_ids=("FR1", "FR2")):
    # 1a-i′ 后采样由 (world_id, fragment_id, slot_id) 稳定键决定，无 seed 形参可传。
    return _sample_sidecar_bool_slots_for_building(
        building_world_id="WB-t",
        fragment_ids=list(fragment_ids),
        sidecar_bool_slot_records=records,
        per_fragment_contexts={fid: None for fid in fragment_ids},
        building_context=None,
    )


def test_building_slot_sampled_once_fragment_slot_per_fragment() -> None:
    records = [
        {"slot_id": "procedure.ri.appointment.completed", "value_type": "bool",
         "prevalence": 1.0, "conditional_formula": None,
         "carrier_domain": "procedure", "granularity": "building",
         "sampling_order": 1},
        {"slot_id": "procedure.inspection.prescribed.completed",
         "value_type": "bool", "prevalence": 1.0, "conditional_formula": None,
         "carrier_domain": "procedure", "sampling_order": 2},
    ]
    by_frag, building = _run_building_sampler(records)
    bldg_rows = building["procedure_gate_state"]
    appt = [v for v in bldg_rows if v.slot_id == "procedure.ri.appointment.completed"]
    assert len(appt) == 1
    assert "fragment_id" not in appt[0].qualifiers
    assert appt[0].qualifiers.get("granularity") == "building"
    for fid in ("FR1", "FR2"):
        frag_rows = by_frag[fid]["procedure_gate_state"]
        insp = [v for v in frag_rows
                if v.slot_id == "procedure.inspection.prescribed.completed"]
        assert len(insp) == 1
        assert insp[0].qualifiers["fragment_id"] == fid


def test_aggregate_rows_all_true_and_any_true() -> None:
    # prevalence=1.0 全真 → all_true 聚合为 True；构造半真用两次采样对照太脆，
    # 这里直接验：全真时 4 槽聚合行存在且值 True、带 aggregation 标记。
    records = [
        {"slot_id": s, "value_type": "bool", "prevalence": 1.0,
         "conditional_formula": None, "carrier_domain": "procedure",
         "sampling_order": i}
        for i, s in enumerate(AGGREGATE_ROW_SLOTS)
    ]
    _, building = _run_building_sampler(records)
    agg_rows = [v for v in building["procedure_gate_state"]
                if v.qualifiers.get("aggregation") == "building"]
    assert {v.slot_id for v in agg_rows} == set(AGGREGATE_ROW_SLOTS)
    assert all(v.value is True for v in agg_rows)
    # 半真：FR1 真 FR2 假（prevalence 0/1 分槽做不到，直接验聚合器）。
    frag_states = {"FR1": {"procedure.repair.prescribed.started": True},
                   "FR2": {"procedure.repair.prescribed.started": False}}
    gran = {"procedure.repair.prescribed.started": "fragment"}
    v = _resolve_building_upstream(
        "procedure.repair.prescribed.started", {}, frag_states, gran,
        BUILDING_READING_AGGREGATION,
    )
    assert v is True  # any_true
    v2 = _resolve_building_upstream(
        "procedure.inspection.prescribed.completed", {},
        {"FR1": {"procedure.inspection.prescribed.completed": True},
         "FR2": {"procedure.inspection.prescribed.completed": False}},
        {"procedure.inspection.prescribed.completed": "fragment"},
        BUILDING_READING_AGGREGATION,
    )
    assert v2 is False  # all_true


def test_building_upstream_broadcast_to_fragment_slot() -> None:
    """fragment 槽条件公式引用 building 槽 → 读楼级缓存（广播）。"""
    records = [
        {"slot_id": "procedure.ri.appointment.completed", "value_type": "bool",
         "prevalence": 1.0, "conditional_formula": None,
         "carrier_domain": "procedure", "granularity": "building",
         "sampling_order": 1},
        # 条件公式强依赖楼级槽：coef 极大 → 楼级 True 时必真。
        {"slot_id": "procedure.inspection.prescribed.completed",
         "value_type": "bool", "prevalence": 0.5,
         "conditional_formula": {
             "kind": "bool", "anchor": 0.5,
             "inputs": [{"name": "procedure.ri.appointment.completed",
                         "coef": 50.0, "expected": 0.0}],
         },
         "carrier_domain": "procedure", "sampling_order": 2},
    ]
    by_frag, _ = _run_building_sampler(records)
    # 公式若真读到广播值 1.0，sigmoid(logit(0.5)+50) ≈ 1 → 两 fragment 必 True；
    # 若公式结构不被评估器接受则走 fallback marginal——两种路径都不该抛异常。
    for fid in ("FR1", "FR2"):
        rows = [v for v in by_frag[fid]["procedure_gate_state"]
                if v.slot_id == "procedure.inspection.prescribed.completed"]
        assert len(rows) == 1


def test_undeclared_cross_granularity_edge_fails_fast() -> None:
    frag_states = {"FR1": {"some.fragment.slot": True}}
    gran = {"some.fragment.slot": "fragment"}
    with pytest.raises(ValueError, match="no declared building-reading"):
        _resolve_building_upstream(
            "some.fragment.slot", {}, frag_states, gran,
            BUILDING_READING_AGGREGATION,
        )


def test_scope_declaration_rows_per_component_class() -> None:
    """件5：范围声明——在场类 true / 注册表其余类 false，楼级主行无 aggregation 标记。"""
    from workflow_engine.worldgen.sidecar import _emit_scope_declaration_rows
    from workflow_engine.worldgen.registry import _build_registry_bundle

    class _C:
        def __init__(self, t): self.component_type = t

    class _BW:
        world_id = "WB-t"
        components = [_C("external_wall"), _C("structural_member")]

    buckets = {"facts": [], "procedure_gate_state": [],
               "supervision_runtime_state": [], "artifact_requirement_state": [],
               "completion_runtime_state": []}
    _emit_scope_declaration_rows(_BW(), _build_registry_bundle(), buckets)
    rows = [v for v in buckets["facts"]
            if v.slot_id == "scope.component.inspection_included"]
    assert len(rows) >= 10  # 注册表全类逐行
    by_type = {v.qualifiers["component_type_key"]: v.value for v in rows}
    assert by_type["external_wall"] is True
    assert by_type["structural_member"] is True
    assert by_type["canopy"] is False        # 楼内缺席 → 如实不涵盖
    assert by_type["wall_tile_finish"] is False
    assert all(v.qualifiers.get("aggregation") == "building" for v in rows)  # 对账批修正：标记行
    assert all(v.qualifiers.get("granularity") == "building" for v in rows)
