"""责任归属登记表：权威数据闸 + 归因接线 + 变异验证。

🔴 §0.3 纪律的牙齿：把某个 `system_unresolved` 改成 `professional_input_required`
必须被 `validate_responsibility_registry` 拦住——不能只靠注释。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from evo_agent_baseline.closure.unknown_attribution import (
    APPROVED_PROFESSIONAL_INPUT_SLOTS,
    DEFAULT_RESPONSIBILITY_REGISTRY_PATH,
    ResponsibilityRegistryError,
    UnknownObligationSnapshot,
    attribute_unknown_obligations,
    flat_responsibility_maps,
    load_responsibility_registry,
    validate_responsibility_registry,
)
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)


def _empty_pools():
    from evo_agent_baseline.closure.unknown_attribution import SuppliedSlotPools

    return SuppliedSlotPools(qual_all={}, qual_unscoped={}, qual_by_fragment={})


def test_authority_registry_loads_with_exact_55_4_split():
    resp_map, action_map, doc = load_responsibility_registry()
    assert DEFAULT_RESPONSIBILITY_REGISTRY_PATH.is_file()
    assert len(doc["slots"]) == 59
    # 扁平表含运行时别名展开，故 ≥ 59
    assert len(resp_map) >= 59
    n_prof = sum(
        1
        for s, v in doc["slots"].items()
        if v["responsibility"] == "professional_input_required"
    )
    n_sys = sum(
        1
        for s, v in doc["slots"].items()
        if v["responsibility"] == "system_unresolved"
    )
    assert (n_sys, n_prof) == (55, 4)
    assert set(
        s
        for s, v in doc["slots"].items()
        if v["responsibility"] == "professional_input_required"
    ) == set(APPROVED_PROFESSIONAL_INPUT_SLOTS)
    # 用户复核改判：代表合格槽必须是系统侧
    assert (
        resp_map["actor.representative.qualified_for_assigned_role"]
        == "system_unresolved"
    )
    # 完整版字段保留
    sample = next(iter(doc["slots"].values()))
    assert {"responsibility", "reason", "professional_action", "confidence"} <= set(
        sample
    )
    # 四个 professional 槽都有可执行交件说明
    for slot in APPROVED_PROFESSIONAL_INPUT_SLOTS:
        assert action_map[slot]
        assert action_map[slot] == doc["slots"][slot]["professional_action"]


def test_registry_not_in_rulecard_manifest():
    """登记表故意不进卡包 manifest，避免变成契约违规。"""
    manifest = json.loads(
        (
            DEFAULT_RESPONSIBILITY_REGISTRY_PATH.parent / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    files = manifest.get("files") or {}
    assert "responsibility_registry" not in files
    assert "responsibility_registry_v1.json" not in files.values()


def test_mutation_flip_professional_to_system_fails_gate():
    """变异：把某个 professional 改成 system → 白名单「缺失」闸变红。"""
    _resp, _act, doc = load_responsibility_registry()
    mutant = copy.deepcopy(doc)
    victim = sorted(APPROVED_PROFESSIONAL_INPUT_SLOTS)[0]
    mutant["slots"][victim]["responsibility"] = "system_unresolved"
    mutant["slots"][victim]["professional_action"] = ""
    with pytest.raises(ResponsibilityRegistryError, match="缺失"):
        validate_responsibility_registry(mutant)


def test_mutation_flip_system_to_professional_fails_gate():
    """🔴 更要紧的变异：把某个 system 改成 professional → 越权闸变红。

    这是 §0.3「缺依据绝不默认成该你填」的牙齿——不能只写在注释里。
    """
    _resp, _act, doc = load_responsibility_registry()
    mutant = copy.deepcopy(doc)
    # 挑一个明确的系统侧槽
    victim = "reporting.artifact.prepared"
    assert doc["slots"][victim]["responsibility"] == "system_unresolved"
    mutant["slots"][victim]["responsibility"] = "professional_input_required"
    mutant["slots"][victim]["professional_action"] = "伪造的交件说明"
    with pytest.raises(ResponsibilityRegistryError, match="越权"):
        validate_responsibility_registry(mutant)


def test_mutation_empty_professional_action_fails_gate():
    _resp, _act, doc = load_responsibility_registry()
    mutant = copy.deepcopy(doc)
    victim = sorted(APPROVED_PROFESSIONAL_INPUT_SLOTS)[0]
    mutant["slots"][victim]["professional_action"] = "   "
    with pytest.raises(ResponsibilityRegistryError, match="professional_action 为空"):
        validate_responsibility_registry(mutant)


def test_runtime_alias_expanded_into_flat_map():
    """卡侧名经 canonical_slot 归一后仍能命中责任表。

    2026-07-29 改写：原版把**具体一对**别名写死
    （`covered_by_large_attached_signboard → covered_by_large_signboard`），
    而那条别名当天已从投影表删除（死桥，目标槽世界侧 0 条事实）
    ⇒ 断言随权威数据变更而失效，且它锁住的恰恰是一个**不该存在**的映射。

    诉求本身是对的（归一后必须仍能命中），所以改成断言**不变式**：
    登记表里每个键，凡在投影别名表里有别名，其别名都必须出现在扁平表里
    且责任/行动说明与本体一致。投影表增删别名时本条自动跟随。
    实测当前：登记表 59 键里 9 个有活别名，全覆盖。
    """
    from evo_agent_baseline.closure.unknown_attribution import (
        _RESPONSIBILITY_SLOT_RUNTIME_ALIASES,
    )

    resp_map, action_map, doc = load_responsibility_registry()
    checked = 0
    for slot_id in doc["slots"]:
        for alias in _RESPONSIBILITY_SLOT_RUNTIME_ALIASES.get(slot_id, ()):
            checked += 1
            assert alias in resp_map, f"归一名 {alias} 未进扁平表（{slot_id}）"
            assert resp_map[alias] == resp_map[slot_id]
            if slot_id in action_map:
                assert action_map.get(alias) == action_map[slot_id]
    assert checked >= 1, "投影表里一个登记表键的别名都没有——多半是真源读错了"


def test_attribute_uses_registry_for_slot_not_supplied():
    resp_map, action_map = flat_responsibility_maps(
        json.loads(DEFAULT_RESPONSIBILITY_REGISTRY_PATH.read_text(encoding="utf-8"))
    )
    slot = "scope.component.covered_by_large_attached_signboard"
    snap = UnknownObligationSnapshot(
        obligation_id="O.sign",
        closure_status="open",
        fragment_id=None,
        canonical_slot_ids=(slot,),
        declared_qualifiers=frozenset(),
        trigger_dependency_ids=(),
        depends_on_open_trigger=False,
        kind="evidence",
        action=None,
        has_slot_handle=True,
        has_obligation_node=True,
        validator_reason_code=None,
    )
    mapping = attribute_unknown_obligations(
        [snap],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=_empty_pools(),
        responsibility_registry=resp_map,
        professional_action_by_slot=action_map,
    )
    attr = mapping["O.sign"]
    assert attr.cause_code == "slot_not_supplied"
    assert attr.responsibility == "professional_input_required"
    assert attr.responsible_slot_id == slot
    assert attr.professional_action == action_map[slot]


def test_qualified_role_stays_system_even_with_registry():
    """用户改判：代表合格槽即使在表里也不得进 professional。"""
    resp_map, action_map = flat_responsibility_maps(
        json.loads(DEFAULT_RESPONSIBILITY_REGISTRY_PATH.read_text(encoding="utf-8"))
    )
    slot = "actor.representative.qualified_for_assigned_role"
    snap = UnknownObligationSnapshot(
        obligation_id="O.qual",
        closure_status="open",
        fragment_id=None,
        canonical_slot_ids=(slot,),
        declared_qualifiers=frozenset(),
        trigger_dependency_ids=(),
        depends_on_open_trigger=False,
        kind="evidence",
        action=None,
        has_slot_handle=True,
        has_obligation_node=True,
    )
    mapping = attribute_unknown_obligations(
        [snap],
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=_empty_pools(),
        responsibility_registry=resp_map,
        professional_action_by_slot=action_map,
    )
    assert mapping["O.qual"].responsibility == "system_unresolved"
    assert mapping["O.qual"].professional_action is None


def test_production_path_loads_registry():
    """批跑主链 `_compute_unknown_attribution_isolated` 真的接上了登记表。"""
    card = make_rule_card(
        "RC.resp.sign",
        family_id="FAM.resp",
        slot_role_map=[
            {
                "slot_ref_id": "sr1",
                "slot_id": "scope.component.covered_by_large_attached_signboard",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {},
            }
        ],
        evidence_requirements={
            "for_matching": [
                {
                    "evidence_requirement_id": "E1",
                    "kind": "evidence",
                    "required": True,
                    "description": "",
                    "artifact_ids": [],
                    "slot_ref_ids": ["sr1"],
                    "measure_keys": [],
                    "required_field_groups": [],
                }
            ],
            "for_submission": [],
            "for_completion": [],
        },
    )
    # 让义务带上 slot_ids（派生器通常会写；夹具路径靠 evidence 节点）
    result = run_closure(make_rule_slice([card]), make_fact_pack([]))
    audit = result.machine_readable_report["unknown_attribution_audit"]
    assert audit["responsibility_registry_present"] is True
    # 本夹具未必派生出该槽的 unknown；至少证明表已加载且未整批降级
    assert audit.get("degraded") is False


# ===================================================================== #
# 运行时别名表：只许镜像投影别名表，不许在代码里发明/复活映射
# ===================================================================== #
def test_runtime_aliases_must_exist_in_projection_table():
    """🔴 `_RESPONSIBILITY_SLOT_RUNTIME_ALIASES` 的每一条都必须在投影别名表里真实存在。

    为什么要这条闸（2026-07-29 实证）：该常量上线时带了一条
    `covered_by_large_attached_signboard → covered_by_large_signboard`，
    而这条别名**当天已从投影别名表删除**（目标槽世界侧 0 条事实、是死桥，
    删除理由见该表 `_note_deleted_large_signboard_alias`）。
    常量自己的注释写着「只登记已在投影别名表里存在的映射」，
    但**没有任何东西在对账**——于是代码把一个已裁定删掉的槽名又搬了回来。

    这与本项目反复踩的「两表之间没有任何东西在对账」是同一族
    （`sidecar_ownership_registry` 140 声明 vs `sidecar_bool_slot_registry` 46 实采）。

    空表是**合法且当前正确**的状态。
    """
    import json

    from evo_agent_baseline.closure.unknown_attribution import (
        _RESPONSIBILITY_SLOT_RUNTIME_ALIASES,
    )

    mapping_path = (
        Path(__file__).resolve().parents[4]
        / "regulations" / "rulecard_v2" / "mbis_cop_2023"
        / "projection_runtime_mapping_v1.json"
    )
    assert mapping_path.is_file(), f"投影映射表不存在：{mapping_path}"
    projection = json.loads(mapping_path.read_text(encoding="utf-8"))["slot_aliases"]

    orphans = []
    for src, aliases in _RESPONSIBILITY_SLOT_RUNTIME_ALIASES.items():
        declared = projection.get(src) or []
        declared = declared if isinstance(declared, list) else [declared]
        for alias in aliases:
            if alias not in declared:
                orphans.append(f"{src} → {alias}")
    assert not orphans, (
        "运行时别名表里有投影别名表中不存在的映射（代码复活了已删的名字）："
        + "; ".join(orphans)
    )
