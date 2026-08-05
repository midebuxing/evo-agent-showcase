"""🔴 判定不变性门 —— unknown 归因旁路**在任何情形下**都不得扰动判定面。

这条门是整个 unknown 归因设计的**安全根据**：归因是给专业人员看的解释层，判定权
仍然唯一属于确定性闭包验证器（CLAUDE.md 判定权红线）。故本文件先证明：

- 任意替换归因策略（含正常策略 / 全 professional / 空映射 / 垃圾映射 /
  **策略直接抛异常**）后，逐义务状态、`open_reason_code`、`blocked_reason_code`、
  汇总计数、`allow_stop` 必须**逐字一致**；
- 且比较器本身**不是空的**——变异对照证明它真能抓到违规（改一条义务状态 /
  改一个计数 / 改 allow_stop，比较器必须报差异）。

比较字段沿用 `agent_v1/scripts/compare_closure_invariance.py:27-36,50-67` 的判定面
定义，另加一层**全量深比**（除归因旁路字段与易变的 created_at 外逐字节相等）。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.closure import unknown_attribution
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)

# 与 compare_closure_invariance.py 同一套判定面语义键。
SEM_FIELDS = (
    "obligation_node_id", "fragment_id", "action", "actor", "kind",
    "closure_status", "open_reason_code", "blocked_reason_code",
    "satisfaction_status", "applicability_state",
)


# ===================================================================== #
# 判定面指纹 + 变异算子（比较器敏感性的证据）
# ===================================================================== #
def verdict_fingerprint(result) -> dict:
    """判定面指纹：逐义务语义键 + 汇总全部整数计数 + allow_stop / stop_reason。"""
    dump = result.model_dump(mode="json")
    obls = dump["obligation_set"]["obligations"]
    summary = dump["closure_summary"]
    return {
        "obligations": sorted(
            tuple(str(o.get(f)) for f in SEM_FIELDS) for o in obls
        ),
        "counts": {k: v for k, v in summary.items() if isinstance(v, int)},
        "open_reason_counts": summary["open_reason_counts"],
        "blocked_reason_counts": summary["blocked_reason_counts"],
        "allow_stop": dump["allow_stop"],
        "allow_report_generation": dump["allow_report_generation"],
        "stop_reason": summary["stop_reason"],
    }


def full_dump_modulo_attribution(result) -> dict:
    """全量深比基准：剔掉归因旁路字段与易变时间戳后的完整产物。"""
    dump = result.model_dump(mode="json")
    dump.pop("unknown_attribution_by_obligation_id", None)
    dump["machine_readable_report"].pop("unknown_attribution_audit", None)
    dump["obligation_set"].pop("created_at", None)
    return dump


def _scenario():
    """一个同时产出「继承型 / 缺槽 / 限定符范围外」三类 unknown 的合成场景。"""
    card_trigger = make_rule_card(
        "RC.attr.trigger",
        family_id="FAM.attr",
        trigger_conditions={
            "logic": "all",
            "items": [
                {
                    "condition_id": "C1",
                    "predicate_kind": "slot",
                    "slot_ref_id": "SR.trig",
                    "operator": "==",
                    "expected_value": True,
                }
            ],
        },
        slot_role_map=[
            {
                "slot_ref_id": "SR.trig",
                "slot_id": "scope.never.supplied",
                "roles": ["trigger"],
                "required": False,
                "qualifiers": {},
            },
            {
                "slot_ref_id": "SR.ev",
                "slot_id": "evidence.absent.slot",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {},
            },
        ],
        evidence_requirements={
            "for_matching": [
                {
                    "evidence_requirement_id": "ER1",
                    "kind": "evidence",
                    "required": True,
                    "description": "",
                    "artifact_ids": [],
                    "slot_ref_ids": ["SR.ev"],
                    "measure_keys": [],
                    "required_field_groups": [],
                }
            ],
            "for_submission": [],
            "for_completion": [],
        },
    )
    card_plain = make_rule_card(
        "RC.attr.plain",
        family_id="FAM.attr2",
        slot_role_map=[
            {
                "slot_ref_id": "SR.x",
                "slot_id": "defect.class.present",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {"defect_class_key": "hollowing"},
            }
        ],
        evidence_requirements={
            "for_matching": [
                {
                    "evidence_requirement_id": "ER2",
                    "kind": "evidence",
                    "required": True,
                    "description": "",
                    "artifact_ids": [],
                    "slot_ref_ids": ["SR.x"],
                    "measure_keys": [],
                    "required_field_groups": [],
                }
            ],
            "for_submission": [],
            "for_completion": [],
        },
    )
    # 没有任何事实槽句柄、只带 artifact 句柄的义务 —— 无触发器故不会被继承型抢先，
    # 正是"系统从未针对它查过任何事实槽"那一族的形状。
    card_artifact = make_rule_card(
        "RC.attr.artifact",
        family_id="FAM.attr3",
        workflow_operands={
            "primary_actor": "ri",
            "primary_action": "submit_form",
            "recipients": [],
            "artifacts": [
                {
                    "artifact_id": "A.attr",
                    "artifact_type": "",
                    "artifact_key": "proposal.supervision",
                }
            ],
            "deadlines": [],
            "audiences": [],
            "method_keys_allowed": [],
        },
    )
    facts = [
        # 世界侧**有** defect.class.present，但限定符不同 → 判定仍 unknown。
        make_fact(
            "F1",
            slot_id="defect.class.present",
            value=True,
            value_type="boolean",
            qualifiers={"defect_class_key": "spalling"},
        ),
    ]
    return (
        make_rule_slice([card_trigger, card_plain, card_artifact]),
        make_fact_pack(facts),
    )


# ===================================================================== #
# 一、比较器敏感性（先证明门不是空的）
# ===================================================================== #
def test_fingerprint_detects_obligation_status_mutation():
    """变异对照：改一条义务的 closure/satisfaction 状态 → 指纹必须变。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    base = verdict_fingerprint(result)

    mutated = result.model_copy(deep=True)
    target = next(
        o for o in mutated.obligation_set.obligations if o.closure_status == "open"
    )
    object.__setattr__(target, "closure_status", "closed")
    object.__setattr__(target, "satisfaction_status", "satisfied")
    object.__setattr__(target, "open_reason_code", None)
    assert verdict_fingerprint(mutated) != base


def test_fingerprint_detects_reason_code_mutation():
    """变异对照：只改 open_reason_code（状态不动）→ 指纹必须变。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    base = verdict_fingerprint(result)

    mutated = result.model_copy(deep=True)
    target = next(
        o for o in mutated.obligation_set.obligations if o.open_reason_code
    )
    object.__setattr__(target, "open_reason_code", "null_observed_value")
    assert verdict_fingerprint(mutated) != base


def test_fingerprint_detects_summary_and_allow_stop_mutation():
    """变异对照：改汇总计数 / allow_stop → 指纹必须变。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    base = verdict_fingerprint(result)

    m1 = result.model_copy(deep=True)
    object.__setattr__(m1.closure_summary, "open_count", m1.closure_summary.open_count + 1)
    assert verdict_fingerprint(m1) != base

    m2 = result.model_copy(deep=True)
    object.__setattr__(m2, "allow_stop", not m2.allow_stop)
    assert verdict_fingerprint(m2) != base


# ===================================================================== #
# 二、判定不变性门本体
# ===================================================================== #
def _all_professional(snapshots, **kwargs):
    """违规意图最强的替代策略：全部谎称「需要专业人员提供」。"""
    from evo_agent_baseline.contracts import UnknownAttribution

    return {
        s.obligation_id: UnknownAttribution(
            obligation_id=s.obligation_id,
            responsibility="professional_input_required",
            cause_code="slot_not_supplied",
            explanation="替代策略",
            root_dependency_ids=[],
            policy_version="alt",
        )
        for s in snapshots
    }


def _empty_mapping(snapshots, **kwargs):
    return {}


def _garbage_mapping(snapshots, **kwargs):
    """返回与 unknown 集合完全不搭界的键（考验键集对齐）。"""
    from evo_agent_baseline.contracts import UnknownAttribution

    return {
        "NOT-AN-OBLIGATION": UnknownAttribution(
            obligation_id="NOT-AN-OBLIGATION",
            responsibility="professional_input_required",
            cause_code="slot_not_supplied",
            explanation="垃圾映射",
            root_dependency_ids=[],
            policy_version="alt",
        )
    }


def _all_no_slot_declared(snapshots, **kwargs):
    """把每条都判成 `no_slot_declared`（第五个码同样不得扰动判定面）。"""
    from evo_agent_baseline.contracts import UnknownAttribution

    return {
        s.obligation_id: UnknownAttribution(
            obligation_id=s.obligation_id,
            responsibility="system_unresolved",
            cause_code="no_slot_declared",
            explanation="替代策略：全判未接线",
            root_dependency_ids=[],
            policy_version="alt",
        )
        for s in snapshots
    }


def _boom(snapshots, **kwargs):
    raise RuntimeError("归因策略故意炸")


@pytest.mark.parametrize(
    "strategy",
    [
        None,
        _all_professional,
        _all_no_slot_declared,
        _empty_mapping,
        _garbage_mapping,
        _boom,
    ],
    ids=[
        "baseline",
        "all_professional",
        "all_no_slot_declared",
        "empty",
        "garbage",
        "raises",
    ],
)
def test_verdict_invariant_under_any_attribution_strategy(monkeypatch, strategy):
    """🔴 判定不变性门：任意替换归因策略，判定面逐字一致。"""
    rule_slice, fact_pack = _scenario()
    baseline = run_closure(rule_slice, fact_pack)
    base_fp = verdict_fingerprint(baseline)
    base_full = full_dump_modulo_attribution(baseline)

    if strategy is not None:
        monkeypatch.setattr(
            unknown_attribution, "attribute_unknown_obligations", strategy
        )
    variant = run_closure(rule_slice, fact_pack)

    assert verdict_fingerprint(variant) == base_fp
    assert full_dump_modulo_attribution(variant) == base_full


def test_attribution_never_degrades_to_professional_on_failure(monkeypatch):
    """策略炸掉时必须落 `system_unresolved / attribution_input_missing` 并报警。

    绝不许退成「需要你提供」——对专业人员谎称"这该你填"而实际是系统坏了更有害。
    """
    rule_slice, fact_pack = _scenario()
    monkeypatch.setattr(unknown_attribution, "attribute_unknown_obligations", _boom)
    result = run_closure(rule_slice, fact_pack)

    mapping = result.unknown_attribution_by_obligation_id
    assert mapping, "场景必须产出 unknown 义务，否则本门无效"
    assert all(a.responsibility == "system_unresolved" for a in mapping.values())
    assert all(a.cause_code == "attribution_input_missing" for a in mapping.values())
    audit = result.machine_readable_report["unknown_attribution_audit"]
    assert audit["degraded"] is True
    assert audit["attribution_input_missing_alarm"] == len(mapping)
    assert audit["backfilled_count"] == len(mapping)


def test_garbage_mapping_keys_are_dropped_not_trusted(monkeypatch):
    """垃圾键被丢弃、缺的补兜底 —— 守恒门恒成立。"""
    rule_slice, fact_pack = _scenario()
    monkeypatch.setattr(
        unknown_attribution, "attribute_unknown_obligations", _garbage_mapping
    )
    result = run_closure(rule_slice, fact_pack)
    mapping = result.unknown_attribution_by_obligation_id
    assert "NOT-AN-OBLIGATION" not in mapping
    audit = result.machine_readable_report["unknown_attribution_audit"]
    assert audit["dropped_extra_count"] == 1


def test_no_slot_declared_split_out_of_alarm_bucket():
    """无事实槽句柄的 unknown 不得落进报警桶（有码则透传，无码则结构拆分）。

    v3：有验证器码时优先透传；两码皆空才落 no_slot_declared / non_slot_handle。
    报警桶里不得再混入「没绑槽」这种可名可数的原因。
    """
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    mapping = result.unknown_attribution_by_obligation_id
    by_id = {o.obligation_id: o for o in result.obligation_set.obligations}

    no_handle_ids = [
        oid
        for oid, o in by_id.items()
        if o.satisfaction_status == "unknown"
        and not (o.slot_ids or o.slot_ref_ids)
        and oid in mapping
        and mapping[oid].cause_code != "inherited_from_root"
    ]
    assert no_handle_ids, "场景必须产出至少一条没绑事实槽的 unknown，否则本测试无效"
    for oid in no_handle_ids:
        attr = mapping[oid]
        assert attr.responsibility == "system_unresolved"
        assert attr.cause_code != "attribution_input_missing", (
            "没绑槽的义务落入报警桶——报警语义被稀释"
        )
        assert "不需要你补录" in attr.explanation

    # 报警桶里不得再混入"没绑槽"这种可名可数的原因。
    alarm = [k for k, a in mapping.items() if a.cause_code == "attribution_input_missing"]
    for oid in alarm:
        assert by_id[oid].slot_ids or by_id[oid].slot_ref_ids, (
            "attribution_input_missing 桶里混进了没绑槽的义务——报警语义被稀释"
        )


def test_no_slot_declared_survives_missing_slot_pools():
    """缺能力快照时：无槽路径仍能说清（透传或结构兜底），不得 silently 丢。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    snaps, status_by_id, deps_by_id = unknown_attribution.build_unknown_snapshots(
        result.obligation_set.obligations,
        canonical_slot=lambda s: s,
        qualifiers_by_slot_ref=unknown_attribution.build_slot_ref_qualifiers(rule_slice),
    )
    mapping = unknown_attribution.attribute_unknown_obligations(
        snaps,
        closure_status_by_obligation_id=status_by_id,
        dependency_ids_by_obligation_id=deps_by_id,
        supplied_slot_pools=None,
        responsibility_registry=None,
    )
    no_handle = [s for s in snaps if not s.has_slot_handle]
    assert no_handle, "场景须含无槽句柄 unknown"
    for s in no_handle:
        assert mapping[s.obligation_id].cause_code != "attribution_input_missing"
    assert all(a.responsibility == "system_unresolved" for a in mapping.values())


def test_conservation_holds_across_all_five_cause_codes():
    """守恒门：所有 code 的条数之和 == unknown 义务总数（一条不多、一条不少）。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    mapping = result.unknown_attribution_by_obligation_id
    unknown_ids = {
        o.obligation_id
        for o in result.obligation_set.obligations
        if o.satisfaction_status == "unknown"
    }
    assert set(mapping) == unknown_ids
    audit = result.machine_readable_report["unknown_attribution_audit"]
    assert sum(audit["cause_code_counts"].values()) == len(unknown_ids)
    # 允许的码 = 核心轴 + 透传名单 + 上游堵死分流
    from evo_agent_baseline.closure.unknown_attribution import _PASSTHROUGH_CAUSE_CODES

    allowed = {
        "inherited_from_root",
        "upstream_trigger_blocked",
        "no_slot_declared",
        "non_slot_handle",
        "qualifier_mismatch",
        "slot_not_supplied",
        "attribution_input_missing",
        *_PASSTHROUGH_CAUSE_CODES,
    }
    assert set(audit["cause_code_counts"]) <= allowed


# ===================================================================== #
# 三、结构隔离：归因策略拿不到可变权威对象
# ===================================================================== #
def test_snapshot_is_frozen_and_carries_no_authority_object():
    """快照是 frozen dataclass 且只含基本值 —— 策略结构上改不了义务。"""
    import dataclasses

    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    snaps, status_by_id, deps_by_id = unknown_attribution.build_unknown_snapshots(
        result.obligation_set.obligations, canonical_slot=lambda s: s
    )
    assert snaps
    snap = snaps[0]
    assert dataclasses.is_dataclass(snap)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.closure_status = "closed"  # type: ignore[misc]
    for value in dataclasses.asdict(snap).values():
        assert isinstance(value, (str, bool, tuple, frozenset, type(None)))
    assert all(isinstance(v, str) for v in status_by_id.values())
    assert all(isinstance(v, tuple) for v in deps_by_id.values())


def test_compute_allow_stop_signature_has_no_attribution_param():
    """`compute_allow_stop_and_reason` 签名不得混入归因参数（设计红线 2）。"""
    import inspect

    from evo_agent_baseline.closure.validator import compute_allow_stop_and_reason

    params = list(inspect.signature(compute_allow_stop_and_reason).parameters)
    assert params == [
        "open_count",
        "blocked_count",
        "violated_count",
        "schema_validation_passed",
        "forbidden_source_check_passed",
    ]


def test_no_eval_import_in_attribution_module():
    """blind 红线：归因模块不得 import eval 侧任何东西。"""
    import pathlib

    src = pathlib.Path(unknown_attribution.__file__).read_text(encoding="utf-8")
    assert "eval." not in src.replace("evaluate", "")
    assert "from ..eval" not in src
    assert "import eval" not in src
