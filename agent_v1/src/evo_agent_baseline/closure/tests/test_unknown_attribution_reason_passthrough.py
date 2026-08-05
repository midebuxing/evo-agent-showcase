"""验证器原因码透传 + 规则顺序：码优先于结构兜底。

设计背景：
- 旧病灶：结构兜底 `no_slot_declared` 排在读验证器码之前，把上游触发器堵死等
  真实原因盖成「从未查过事实」。
- 修复：无槽句柄路径上，验证器码优先透传；两码皆空才落结构兜底。
- 另：`trigger_state == "blocked"` 单列 `upstream_trigger_blocked`。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.closure.unknown_attribution import (
    _PASSTHROUGH_CAUSE_CODES,
    SuppliedSlotPools,
    UnknownObligationSnapshot,
    attribute_unknown_obligations,
)

_NON_LISTED_CODES = ("schema_contract_violation", "internal_error", "unsupported_operator")


def _pools_supplied(*slots: str, qualifiers=frozenset()) -> SuppliedSlotPools:
    return SuppliedSlotPools(
        qual_all={s: (frozenset(qualifiers),) for s in slots},
        qual_unscoped={},
        qual_by_fragment={},
    )


def _snap(
    obligation_id: str = "O1",
    *,
    validator_reason_code=None,
    has_slot_handle: bool = True,
    has_obligation_node: bool = False,
    other_fact_handles=(),
    canonical_slot_ids=("some.slot",),
    declared_qualifiers=frozenset(),
    depends_on_open_trigger: bool = False,
    trigger_dependency_ids=(),
    trigger_state: str = "not_evaluated",
) -> UnknownObligationSnapshot:
    return UnknownObligationSnapshot(
        obligation_id=obligation_id,
        closure_status="open",
        fragment_id=None,
        canonical_slot_ids=tuple(canonical_slot_ids) if has_slot_handle else (),
        declared_qualifiers=frozenset(declared_qualifiers),
        trigger_dependency_ids=tuple(trigger_dependency_ids),
        depends_on_open_trigger=depends_on_open_trigger,
        kind="evidence",
        action="inspect",
        has_slot_handle=has_slot_handle,
        has_obligation_node=has_obligation_node,
        other_fact_handles=tuple(other_fact_handles),
        validator_reason_code=validator_reason_code,
        trigger_state=trigger_state,
    )


def _run(snaps, *, pools, status=None, deps=None):
    return attribute_unknown_obligations(
        snaps,
        closure_status_by_obligation_id=status or {},
        dependency_ids_by_obligation_id=deps or {},
        supplied_slot_pools=pools,
        responsibility_registry=None,
    )


def _fallback_snap(**kw) -> UnknownObligationSnapshot:
    """判据 1–5 全落空、直达兜底分支的快照（槽在世界里、限定符要求为空）。"""
    return _snap(**kw)


# ===================================================================== #
# 一、透传名单
# ===================================================================== #
@pytest.mark.parametrize("code", sorted(_PASSTHROUGH_CAUSE_CODES))
def test_listed_reason_code_is_passed_through_in_fallback(code):
    snap = _fallback_snap(validator_reason_code=code)
    mapping = _run([snap], pools=_pools_supplied("some.slot"))
    attr = mapping["O1"]
    assert attr.cause_code == code
    assert attr.validator_reason_code == code
    assert "不需要你补录资料" in attr.explanation
    assert f"`{code}`" in attr.explanation


@pytest.mark.parametrize("code", _NON_LISTED_CODES)
def test_non_listed_reason_code_stays_in_alarm_bucket(code):
    snap = _fallback_snap(validator_reason_code=code)
    mapping = _run([snap], pools=_pools_supplied("some.slot"))
    attr = mapping["O1"]
    assert attr.cause_code == "attribution_input_missing"
    assert attr.validator_reason_code == code


# ===================================================================== #
# 二、缺省等价：不传 validator_reason_code 时结构兜底仍可用
# ===================================================================== #
def _branches_without_code():
    return (
        _snap(
            "O.inherit",
            depends_on_open_trigger=True,
            trigger_dependency_ids=("R1",),
        ),
        _snap(
            "O.noslot",
            has_slot_handle=False,
            has_obligation_node=True,
            canonical_slot_ids=(),
        ),
        _snap(
            "O.mismatch",
            declared_qualifiers=frozenset({("defect_class_key", "hollowing")}),
        ),
        _snap("O.absent", canonical_slot_ids=("absent.slot",)),
        _fallback_snap(obligation_id="O.alarm"),
    )


def test_default_equivalence_when_reason_code_omitted():
    snaps = _branches_without_code()
    mapping = _run(
        list(snaps),
        pools=_pools_supplied(
            "some.slot", qualifiers=frozenset({("defect_class_key", "spalling")})
        ),
        status={"R1": "open"},
        deps={"O.inherit": ("R1",)},
    )
    assert mapping["O.inherit"].cause_code == "inherited_from_root"
    assert mapping["O.noslot"].cause_code == "no_slot_declared"
    assert mapping["O.mismatch"].cause_code == "qualifier_mismatch"
    assert mapping["O.absent"].cause_code == "slot_not_supplied"
    assert mapping["O.alarm"].cause_code == "attribution_input_missing"
    assert all(a.validator_reason_code is None for a in mapping.values())


# ===================================================================== #
# 三、🔴 验证器码优先于结构兜底（规则顺序硬闸）
# ===================================================================== #
def test_passthrough_outranks_structural_noslot_on_no_handle_path():
    """带着名单内的码、无槽句柄 → 必须透传，不得落 no_slot_declared。"""
    snap = _snap(
        "O.noslot",
        has_slot_handle=False,
        has_obligation_node=True,
        canonical_slot_ids=(),
        validator_reason_code="missing_satisfaction_binding",
    )
    mapping = _run([snap], pools=_pools_supplied("some.slot"))
    assert mapping["O.noslot"].cause_code == "missing_satisfaction_binding"


def test_mutation_structural_before_validator_would_steal():
    """变异验证：若把结构兜底重新排到验证器码之前，本断言描述的正确行为会红。

    本测试锁定「正确顺序下的期望」；下面 `test_order_invariant_docs_the_bug`
    用显式反序函数证明闸非空。
    """
    snap = _snap(
        "O",
        has_slot_handle=False,
        has_obligation_node=True,
        canonical_slot_ids=(),
        validator_reason_code="missing_artifact_evidence",
    )
    assert _run([snap], pools=None)["O"].cause_code == "missing_artifact_evidence"


def _attribute_with_structural_before_validator(snapshots, **kwargs):
    """故意反序：无槽句柄时先落结构兜底，无视验证器码（旧病灶复现）。"""
    from evo_agent_baseline.contracts import UnknownAttribution
    from evo_agent_baseline.closure import unknown_attribution as ua

    out = {}
    policy = kwargs.get("policy_version", ua.UNKNOWN_ATTRIBUTION_POLICY_VERSION)
    for snap in snapshots:
        if not snap.has_slot_handle:
            code = "no_slot_declared" if snap.has_obligation_node else "non_slot_handle"
            out[snap.obligation_id] = UnknownAttribution(
                obligation_id=snap.obligation_id,
                responsibility="system_unresolved",
                cause_code=code,
                explanation="MUTATION: structural first",
                root_dependency_ids=[],
                policy_version=policy,
                validator_reason_code=snap.validator_reason_code,
            )
            continue
        # 其余走真函数
        partial = ua.attribute_unknown_obligations([snap], **kwargs)
        out.update(partial)
    return out


def test_order_invariant_docs_the_bug():
    """把规则顺序改回去（结构兜底抢先）→ 与正确实现的归属必须不同（闸非空）。"""
    snap = _snap(
        "O",
        has_slot_handle=False,
        has_obligation_node=True,
        canonical_slot_ids=(),
        validator_reason_code="missing_satisfaction_binding",
    )
    kwargs = dict(
        closure_status_by_obligation_id={},
        dependency_ids_by_obligation_id={},
        supplied_slot_pools=None,
        responsibility_registry=None,
    )
    correct = attribute_unknown_obligations([snap], **kwargs)["O"].cause_code
    broken = _attribute_with_structural_before_validator([snap], **kwargs)["O"].cause_code
    assert correct == "missing_satisfaction_binding"
    assert broken == "no_slot_declared"
    assert correct != broken


# ===================================================================== #
# 四、透传不偷走有槽路径上的继承 / 限定符 / 未供给
# ===================================================================== #
def test_passthrough_does_not_steal_criteria_1_and_slot_axis():
    snaps = _branches_without_code()
    snaps = tuple(
        UnknownObligationSnapshot(
            **{**s.__dict__, "validator_reason_code": "missing_time_anchor"}
        )
        for s in snaps
    )
    mapping = _run(
        list(snaps),
        pools=_pools_supplied(
            "some.slot", qualifiers=frozenset({("defect_class_key", "spalling")})
        ),
        status={"R1": "open"},
        deps={"O.inherit": ("R1",)},
    )
    assert mapping["O.inherit"].cause_code == "inherited_from_root"
    # 无槽 + 有码 → 现在透传（这是故意的顺序修正）
    assert mapping["O.noslot"].cause_code == "missing_time_anchor"
    assert mapping["O.mismatch"].cause_code == "qualifier_mismatch"
    assert mapping["O.absent"].cause_code == "slot_not_supplied"
    assert mapping["O.alarm"].cause_code == "missing_time_anchor"


def test_passthrough_never_claims_professional_input():
    for code in sorted(_PASSTHROUGH_CAUSE_CODES):
        snap = _fallback_snap(validator_reason_code=code)
        attr = _run([snap], pools=_pools_supplied("some.slot"))["O1"]
        assert attr.responsibility == "system_unresolved"


def test_validator_reason_code_recorded_on_every_branch():
    snaps = _branches_without_code()
    codes = {
        "O.inherit": "depends_on_open_trigger",
        "O.noslot": "missing_satisfaction_binding",
        "O.mismatch": "qualifier_conflict",
        "O.absent": "missing_fact",
        "O.alarm": "missing_time_anchor",
    }
    snaps = tuple(
        UnknownObligationSnapshot(
            **{**s.__dict__, "validator_reason_code": codes[s.obligation_id]}
        )
        for s in snaps
    )
    mapping = _run(
        list(snaps),
        pools=_pools_supplied(
            "some.slot", qualifiers=frozenset({("defect_class_key", "spalling")})
        ),
        status={"R1": "open"},
        deps={"O.inherit": ("R1",)},
    )
    for oid, code in codes.items():
        assert mapping[oid].validator_reason_code == code, (
            f"{oid} 的 validator_reason_code 未照抄传入值"
        )


def test_upstream_trigger_blocked_outranks_slot_axis():
    """有槽 + 限定符会对不上，但 trigger_state=blocked → 仍归上游堵死。"""
    snap = _snap(
        "O",
        canonical_slot_ids=("some.slot",),
        declared_qualifiers=frozenset({("defect_class_key", "hollowing")}),
        validator_reason_code="missing_rule_edge",
        trigger_state="blocked",
    )
    mapping = _run(
        [snap],
        pools=_pools_supplied(
            "some.slot", qualifiers=frozenset({("defect_class_key", "spalling")})
        ),
    )
    assert mapping["O"].cause_code == "upstream_trigger_blocked"
