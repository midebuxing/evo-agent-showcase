"""identity-v2 地基层单测（spec 草案 v4 Block A）。

覆盖：
- schema 判别式（CanonicalBinding / DeadlineBinding / PredicateSpecV1 /
  CanonicalObligationIdentity predicate_kind↔spec 一致性 / ObligationV2 source_operator audit）。
- A.6 层一：五类字段并 ≡ ObligationV2 全递归叶子集，两两不交。
- A.5 双哈希稳定性 + 跨楼不撞（N1）+ 碰撞后置四码。
- A.7 merge 格交换/结合/幂等属性测试 + B4 观测冲突→blocked 专项。
- A.9 blind 传递闭包 import 扫描（禁 eval / TruthBundle / threshold_evaluations / workflow_engine）。
"""

import ast
import itertools
import random
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from canonical_profile import canonical_json
from evo_agent_baseline.closure import identity_v2 as I


# =========================================================================== #
# 构造 helper
# =========================================================================== #


def mk_identity(**over):
    d = dict(
        identity_schema="obligation_identity_v5",
        canonical_profile_id="mbis_canonical_v2",
        source_rule_card_id="rc.x",
        kind="evidence",
        scope=I.ObligationScope(kind="building", scope_id=""),
        obligation_node_id="",
        obligation_edge_ids=(),
        actor="",
        action="",
        recipient_ids=(),
        slot_bindings=(),
        artifact_bindings=(),
        measure_bindings=(),
        deadline_bindings=(),
        time_anchor_bindings=(),
        source_channel="evidence",
        source_item_id=I.encode_source_item_id("evidence", "ev1", {"kind": "photo"}),
        predicate_kind="",
        source_predicate_spec=None,
        qualifiers=(),
    )
    d.update(over)
    return I.CanonicalObligationIdentity(**d)


def mk_threshold_spec(**over):
    d = dict(
        spec_schema="predicate_spec_v1",
        predicate_kind="threshold_literal",
        threshold_regime_id="rc.f.c1.t1",
        canonical_measure_key="measure.crack_width",
        source_operator="<=",
        literal_value_tag="decimal",
        literal_value_canonical="7",
        formula_id="",
        canonical_unit="mm",
        canonical_time_anchor_key="",
        threshold_qualifier_fingerprint=(),
        variable_bindings=(),
    )
    d.update(over)
    return I.PredicateSpecV1(**d)


def mk_state(**over):
    d = dict(
        closure_status="closed",
        satisfaction_status="satisfied",
        applicability_state="applicable",
        trigger_state="not_evaluated",
        depends_on_open_trigger=False,
        evaluated_comparator="",
        comparator_result=None,
        observed_value_json=None,
        evaluated_expected_value_json=None,
        open_reason_code=None,
        blocked_reason_code=None,
        merged_observation_bottom=(),
    )
    d.update(over)
    return I.ObligationStateV2(**d)


def mk_obligation(identity=None, state=None, env=None, immutable=None, prov=None, notes=""):
    identity = identity or mk_identity()
    state = state or mk_state()
    env = env or I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b1")
    spec_op = (
        identity.source_predicate_spec.source_operator
        if identity.source_predicate_spec
        else ""
    )
    immutable = immutable or I.ImmutablePayload(
        required=True, canonical_unit="", source_operator=spec_op
    )
    prov = prov or I.ObligationProvenanceV2(
        source_family_id="fam.x",
        slot_ref_ids=(),
        artifact_local_ids=(),
        trigger_dependency_ids=(),
        evidence_fact_ids=(),
        evidence_node_refs=(),
        source_clause_ids=(),
        source_quote_ids=(),
        workflow_recipient_ids=(),
    )
    h = I.compute_canonical_identity_hash(identity)
    oid = I.compute_obligation_id_v2(identity, env)
    return I.ObligationV2(
        obligation_identity_schema="obligation_identity_v5",
        obligation_id=oid,
        canonical_identity_hash=h,
        identity=identity,
        immutable=immutable,
        state=state,
        run_envelope=env,
        provenance=prov,
        notes=notes,
    )


# =========================================================================== #
# A.2.1 CanonicalBinding / DeadlineBinding 判别式
# =========================================================================== #


def test_canonical_binding_resolved_requires_key():
    with pytest.raises(ValidationError):
        I.CanonicalBinding(
            namespace="slot", resolution="resolved", local_ref="s1", canonical_key=""
        )


def test_canonical_binding_unresolved_forbids_key():
    with pytest.raises(ValidationError):
        I.CanonicalBinding(
            namespace="slot", resolution="unresolved", local_ref="s1", canonical_key="c"
        )


def test_canonical_binding_unresolved_needs_local_ref():
    with pytest.raises(ValidationError):
        I.CanonicalBinding(
            namespace="slot", resolution="unresolved", local_ref="", canonical_key=""
        )


def test_canonical_binding_frozen_and_extra_forbid():
    b = I.CanonicalBinding(
        namespace="slot", resolution="resolved", local_ref="s1", canonical_key="c"
    )
    with pytest.raises(ValidationError):
        I.CanonicalBinding(
            namespace="slot", resolution="resolved", local_ref="s1", canonical_key="c",
            extrafield="x",
        )
    with pytest.raises((TypeError, ValidationError)):
        b.canonical_key = "z"  # frozen


def test_deadline_binding_requires_relation():
    with pytest.raises(ValidationError):
        I.DeadlineBinding(
            namespace="deadline", resolution="resolved", local_ref="d1",
            canonical_key="time_anchor.completion", relation="",
            offset_value="7", offset_unit="day", time_anchor_key="time_anchor.completion",
        )


def test_deadline_binding_ok():
    d = I.DeadlineBinding(
        namespace="deadline", resolution="resolved", local_ref="d1",
        canonical_key="time_anchor.completion", relation="within",
        offset_value="7", offset_unit="day", time_anchor_key="time_anchor.completion",
    )
    assert d.relation == "within"


# =========================================================================== #
# A.2.3 PredicateSpecV1 判别式
# =========================================================================== #


def test_predicate_spec_threshold_literal_ok():
    s = mk_threshold_spec()
    assert s.predicate_kind == "threshold_literal"


def test_predicate_spec_threshold_missing_regime_id():
    with pytest.raises(ValidationError):
        mk_threshold_spec(threshold_regime_id="")


def test_predicate_spec_threshold_literal_forbids_formula_id():
    with pytest.raises(ValidationError):
        mk_threshold_spec(formula_id="formula.x")


def test_predicate_spec_threshold_formula_requires_formula_operator():
    # threshold_formula 须 formula_id 非空 + source_operator == 'formula'
    s = mk_threshold_spec(
        predicate_kind="threshold_formula", source_operator="formula",
        formula_id="formula.pull", literal_value_tag="none", literal_value_canonical="",
    )
    assert s.formula_id == "formula.pull"
    with pytest.raises(ValidationError):
        mk_threshold_spec(
            predicate_kind="threshold_formula", source_operator=">=",
            formula_id="formula.pull", literal_value_tag="none", literal_value_canonical="",
        )


def test_predicate_spec_non_threshold_clears_payload():
    s = I.PredicateSpecV1(
        spec_schema="predicate_spec_v1", predicate_kind="prohibition",
        threshold_regime_id="", canonical_measure_key="", source_operator="",
        literal_value_tag="none", literal_value_canonical="", formula_id="",
        canonical_unit="", canonical_time_anchor_key="",
        threshold_qualifier_fingerprint=(), variable_bindings=(),
    )
    assert s.predicate_kind == "prohibition"
    # 任一 threshold-scoped 载荷非空 → 报错
    with pytest.raises(ValidationError):
        I.PredicateSpecV1(
            spec_schema="predicate_spec_v1", predicate_kind="prohibition",
            threshold_regime_id="", canonical_measure_key="measure.x", source_operator="",
            literal_value_tag="none", literal_value_canonical="", formula_id="",
            canonical_unit="", canonical_time_anchor_key="",
            threshold_qualifier_fingerprint=(), variable_bindings=(),
        )


# =========================================================================== #
# A.2.4 CanonicalObligationIdentity predicate_kind ↔ spec 一致性（B1）
# =========================================================================== #


def test_identity_threshold_channel_requires_matching_spec():
    spec = mk_threshold_spec()
    idn = mk_identity(
        source_channel="threshold", predicate_kind="threshold_literal",
        source_predicate_spec=spec, kind="threshold",
    )
    assert idn.predicate_kind == "threshold_literal"


def test_identity_threshold_channel_mismatch_kind():
    spec = mk_threshold_spec()
    with pytest.raises(ValidationError):
        mk_identity(
            source_channel="threshold", predicate_kind="threshold_formula",
            source_predicate_spec=spec,
        )


def test_identity_trigger_channel_forbids_spec():
    # B1：trigger 谓词不走 predicate_spec，spec 必须 None
    spec = mk_threshold_spec()
    with pytest.raises(ValidationError):
        mk_identity(
            source_channel="trigger", predicate_kind="measure", source_predicate_spec=spec,
        )
    ok = mk_identity(
        source_channel="trigger", predicate_kind="measure", source_predicate_spec=None,
    )
    assert ok.predicate_kind == "measure"


def test_identity_no_predicate_channel_requires_empty():
    with pytest.raises(ValidationError):
        mk_identity(source_channel="evidence", predicate_kind="threshold_literal")


def test_obligation_source_operator_audit():
    spec = mk_threshold_spec(source_operator="<=")
    idn = mk_identity(
        source_channel="threshold", predicate_kind="threshold_literal",
        source_predicate_spec=spec, kind="threshold",
    )
    # immutable.source_operator 与 spec 不一致 → audit 报错
    with pytest.raises(ValidationError):
        mk_obligation(
            identity=idn,
            immutable=I.ImmutablePayload(required=True, canonical_unit="mm", source_operator=">="),
        )
    # 一致 → ok
    o = mk_obligation(
        identity=idn,
        immutable=I.ImmutablePayload(required=True, canonical_unit="mm", source_operator="<="),
    )
    assert o.immutable.source_operator == "<="


# =========================================================================== #
# A.6 层一：五类字段并 ≡ 全递归叶子，两两不交
# =========================================================================== #


def _strip_optional(ann):
    if typing.get_origin(ann) is typing.Union:
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _leaf_paths(cls, prefix=""):
    out = set()
    for name, field in cls.model_fields.items():
        out |= _walk(field.annotation, prefix + name)
    return out


def _walk(ann, path):
    ann = _strip_optional(ann)
    if typing.get_origin(ann) is tuple:
        inner = _strip_optional(typing.get_args(ann)[0])
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return _leaf_paths(inner, path + "[].")
        return {path + "[]"}
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return _leaf_paths(ann, path + ".")
    return {path}


def _binding4(prefix):
    return {f"{prefix}[].{f}" for f in ("namespace", "resolution", "local_ref", "canonical_key")}


def _deadline8(prefix):
    return {
        f"{prefix}[].{f}"
        for f in (
            "namespace", "resolution", "local_ref", "canonical_key",
            "relation", "offset_value", "offset_unit", "time_anchor_key",
        )
    }


# 五类映射（spec A.6 层一表逐字段誊写）
_SPEC_SPEC = {
    "identity.source_predicate_spec.spec_schema",
    "identity.source_predicate_spec.predicate_kind",
    "identity.source_predicate_spec.threshold_regime_id",
    "identity.source_predicate_spec.canonical_measure_key",
    "identity.source_predicate_spec.source_operator",
    "identity.source_predicate_spec.literal_value_tag",
    "identity.source_predicate_spec.literal_value_canonical",
    "identity.source_predicate_spec.formula_id",
    "identity.source_predicate_spec.canonical_unit",
    "identity.source_predicate_spec.canonical_time_anchor_key",
    "identity.source_predicate_spec.threshold_qualifier_fingerprint[]",
    "identity.source_predicate_spec.variable_bindings[].symbol",
    "identity.source_predicate_spec.variable_bindings[].canonical_measure_key",
    "identity.source_predicate_spec.variable_bindings[].qualifier_fingerprint[]",
}

CATEGORY_IDENTITY = (
    {
        "obligation_identity_schema",
        "canonical_identity_hash",
        "identity.identity_schema",
        "identity.canonical_profile_id",
        "identity.source_rule_card_id",
        "identity.kind",
        "identity.scope.kind",
        "identity.scope.scope_id",
        "identity.obligation_node_id",
        "identity.obligation_edge_ids[]",
        "identity.actor",
        "identity.action",
        "identity.recipient_ids[]",
        "identity.source_channel",
        "identity.source_item_id",
        "identity.predicate_kind",
        "identity.qualifiers[]",
    }
    | _binding4("identity.slot_bindings")
    | _binding4("identity.artifact_bindings")
    | _binding4("identity.measure_bindings")
    | _binding4("identity.time_anchor_bindings")
    | _deadline8("identity.deadline_bindings")
    | _SPEC_SPEC
)

CATEGORY_IMMUTABLE = {
    "immutable.required",
    "immutable.canonical_unit",
    "immutable.source_operator",
}

CATEGORY_STATE = {
    "state.closure_status",
    "state.satisfaction_status",
    "state.applicability_state",
    "state.trigger_state",
    "state.depends_on_open_trigger",
    "state.evaluated_comparator",
    "state.comparator_result",
    "state.observed_value_json",
    "state.evaluated_expected_value_json",
    "state.open_reason_code",
    "state.blocked_reason_code",
    "state.merged_observation_bottom[]",
}

CATEGORY_PROVENANCE = {
    "obligation_id",
    "run_envelope.run_id",
    "run_envelope.world_id",
    "run_envelope.building_id",
    "provenance.source_family_id",
    "provenance.slot_ref_ids[]",
    "provenance.artifact_local_ids[]",
    "provenance.trigger_dependency_ids[]",
    "provenance.evidence_fact_ids[]",
    "provenance.evidence_node_refs[]",
    "provenance.source_clause_ids[]",
    "provenance.source_quote_ids[]",
    "provenance.workflow_recipient_ids[]",
}

CATEGORY_DERIVED = {"notes"}

_ALL_CATEGORIES = [
    CATEGORY_IDENTITY,
    CATEGORY_IMMUTABLE,
    CATEGORY_STATE,
    CATEGORY_PROVENANCE,
    CATEGORY_DERIVED,
]


def test_state_has_12_fields():
    assert len(CATEGORY_STATE) == 12
    assert len(I.ObligationStateV2.model_fields) == 12


def test_five_category_union_equals_all_leaves():
    leaves = _leaf_paths(I.ObligationV2)
    union = set().union(*_ALL_CATEGORIES)
    missing = leaves - union
    extra = union - leaves
    assert not missing, f"叶子未归类（母病断根闸）: {sorted(missing)}"
    assert not extra, f"归类含不存在叶子: {sorted(extra)}"


def test_five_categories_pairwise_disjoint():
    for a, b in itertools.combinations(_ALL_CATEGORIES, 2):
        assert not (a & b), f"类别相交: {sorted(a & b)}"


# =========================================================================== #
# A.5 双哈希稳定性 + 跨楼不撞（N1）
# =========================================================================== #


def test_identity_hash_stable_across_runs():
    idn = mk_identity()
    e1 = I.RunInstanceEnvelope(run_id="rA", world_id="w1", building_id="b1")
    e2 = I.RunInstanceEnvelope(run_id="rB", world_id="w1", building_id="b1")
    # canonical_identity_hash 不含 run → 跨 run 稳定
    assert I.compute_canonical_identity_hash(idn) == I.compute_canonical_identity_hash(idn)
    # obligation_id 含 run_envelope，但同 world/building 同 identity → 与 run_id 无关？
    # N1 只锁 world/building 进 hash；run_id 也在 envelope 内 → 不同 run_id 会不同 id。
    assert I.compute_obligation_id_v2(idn, e1) != I.compute_obligation_id_v2(idn, e2)


def test_obligation_id_cross_building_no_collision():
    idn = mk_identity()
    e_b1 = I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b1")
    e_b2 = I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b2")
    # 同 identity 同 run/world，仅楼不同 → obligation_id 不撞（N1）
    assert I.compute_obligation_id_v2(idn, e_b1) != I.compute_obligation_id_v2(idn, e_b2)
    # 而 canonical_identity_hash 楼间相同（身份不含 run 实例）
    assert I.compute_canonical_identity_hash(idn) == I.compute_canonical_identity_hash(idn)


def test_obligation_id_v2_rejects_non_v5():
    idn = mk_identity()
    env = I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b1")
    # 正常 v5 通过
    assert I.compute_obligation_id_v2(idn, env)
    # model_copy 绕 Literal 注入旧 v4 schema → guard 拒（A.8：入口拒非 v5）
    bad = idn.model_copy(update={"identity_schema": "obligation_identity_v4"})
    with pytest.raises(I.ObligationContractError):
        I.compute_obligation_id_v2(bad, env)
    # 伪造 v1 identity_schema（绕 Literal，用 dict 构造 hash 输入直接调不了；改测 guard 分支）
    class _FakeIdentity:
        identity_schema = "obligation_identity_v1"

        def model_dump(self):  # pragma: no cover - 不应到达
            return {}

    with pytest.raises(I.ObligationContractError):
        I.compute_obligation_id_v2(_FakeIdentity(), env)


def test_different_identity_different_hash():
    a = mk_identity(source_rule_card_id="rc.a")
    b = mk_identity(source_rule_card_id="rc.b")
    assert I.compute_canonical_identity_hash(a) != I.compute_canonical_identity_hash(b)


# =========================================================================== #
# v5 现网键切换增补 §3.4：两个控制审计 channel（无谓词类，落 else 分支）
# =========================================================================== #


def test_v5_audit_channels_accepted_no_predicate():
    """§3.4：structural_scope_audit / trigger_aggregation_audit 两 channel 无谓词类
    （predicate_kind=""、source_predicate_spec=None，落 `_predicate_kind_spec_consistency`
    else 分支）→ 构造通过、身份哈希稳定。"""
    struct = mk_identity(
        kind="scope_audit",
        scope=I.ObligationScope(kind="fragment", scope_id="FR-1"),
        source_channel="structural_scope_audit",
        source_item_id=I.encode_source_item_id(
            "structural_scope_audit", "structural_scope_audit", {"component_type_key": ["wall"]}
        ),
    )
    tagg = mk_identity(
        kind="scope_audit",
        source_channel="trigger_aggregation_audit",
        source_item_id=I.encode_source_item_id(
            "trigger_aggregation_audit", "trigger_aggregation_audit", {"logic": "all"}
        ),
    )
    assert struct.source_channel == "structural_scope_audit"
    assert tagg.source_channel == "trigger_aggregation_audit"
    # 无谓词类 → 哈希可算、schema 为 v5。
    assert I.compute_canonical_identity_hash(struct)
    assert struct.identity_schema == "obligation_identity_v5"


def test_v5_audit_channels_reject_nonempty_predicate():
    """两新 channel 属无谓词类：predicate_kind 非空 / spec 非 None → 构造 hard-fail
    （else 分支要求 pk=="" 且 spec is None）。"""
    with pytest.raises(ValidationError):
        mk_identity(
            source_channel="structural_scope_audit",
            kind="scope_audit",
            scope=I.ObligationScope(kind="fragment", scope_id="FR-1"),
            predicate_kind="threshold_literal",  # 非空 → else 分支拒
        )
    with pytest.raises(ValidationError):
        mk_identity(
            source_channel="trigger_aggregation_audit",
            kind="scope_audit",
            predicate_kind="",
            source_predicate_spec=mk_threshold_spec(),  # 非 None → else 分支拒
        )


# =========================================================================== #
# A.5 碰撞后置检查
# =========================================================================== #


def test_collision_postcheck_passes_clean_set():
    o1 = mk_obligation(identity=mk_identity(source_rule_card_id="rc.a"))
    o2 = mk_obligation(identity=mk_identity(source_rule_card_id="rc.b"))
    I.run_collision_postcheck([o1, o2])  # 不抛


def test_collision_postcheck_recompute_mismatch():
    o = mk_obligation()
    tampered = o.model_copy(update={"obligation_id": "deadbeefdeadbeefdeadbeef"})
    with pytest.raises(I.ObligationContractError) as exc:
        I.run_collision_postcheck([tampered])
    assert "recompute_mismatch" in str(exc.value)


def test_collision_postcheck_dedupe_escape():
    # 同 scope 同 identity 两条未合并 → dedupe_escape
    o = mk_obligation()
    with pytest.raises(I.ObligationContractError) as exc:
        I.run_collision_postcheck([o, o])
    assert "dedupe_escape" in str(exc.value)


def test_collision_postcheck_obligation_id_not_injective():
    # 同 obligation_id 挂不同 identity（人为篡改 identity 但保留 id）
    o1 = mk_obligation(identity=mk_identity(source_rule_card_id="rc.a"))
    # 用 o1 的 id + o2 的 identity（不同），且 canonical_identity_hash 改为与 identity 匹配
    other = mk_identity(source_rule_card_id="rc.b")
    o2 = o1.model_copy(
        update={
            "identity": other,
            "canonical_identity_hash": I.compute_canonical_identity_hash(other),
        }
    )
    # o2.obligation_id 仍是 o1 的 → recompute 会先 mismatch；为专测 injective，
    # 构造两条 recompute 自洽但共享 id 的对象不可能（id 由 identity 派生）。
    # 故 injective 违规实际由 recompute_mismatch 先兜住 —— 断言仍 hard-fail。
    with pytest.raises(I.ObligationContractError):
        I.run_collision_postcheck([o1, o2])


# =========================================================================== #
# A.7 merge 格：交换 / 结合 / 幂等 + B4
# =========================================================================== #


def _state_bytes(s):
    return canonical_json(s.model_dump())


def _random_state(rng):
    """生成**内部一致**的随机 state（closure↔satisfaction/reason 约束成立）。

    真实义务经 v1 validator 保证内部一致（open→satisfaction=unknown+open_reason 等），
    故 `merge_states([x]) == x`（x 为一致 state 的固定点）；标量字段自由变动以驱动
    合并时 agreement-or-bottom 的 ⊥→blocked 路径。
    """
    cs = rng.choice(["open", "blocked", "closed"])
    if cs == "closed":
        satis = rng.choice(["satisfied", "violated", "not_applicable"])
        orc, brc = None, None
    elif cs == "open":
        satis = "unknown"
        orc = rng.choice(["missing_fact", "applicability_uncertain", "missing_measurement"])
        brc = None
    else:  # blocked
        satis = "unknown"
        orc = None
        brc = rng.choice(["unit_mismatch", "unsupported_operator", "qualifier_conflict"])
    return mk_state(
        closure_status=cs,
        satisfaction_status=satis,
        applicability_state=rng.choice(["applicable", "not_applicable", "uncertain"]),
        trigger_state=rng.choice(
            ["active", "inactive", "open", "blocked", "not_evaluated"]
        ),
        depends_on_open_trigger=rng.choice([True, False]),
        evaluated_comparator=rng.choice(["<=", ">=", "", "=="]),
        comparator_result=rng.choice([True, False, None]),
        observed_value_json=rng.choice([None, "1", "2"]),
        evaluated_expected_value_json=rng.choice([None, "9", "10"]),
        open_reason_code=orc,
        blocked_reason_code=brc,
    )


def test_merge_states_commutative_associative_idempotent():
    rng = random.Random(20260714)
    for _ in range(120):
        n = rng.randint(1, 5)
        states = [_random_state(rng) for _ in range(n)]
        base = _state_bytes(I.merge_states(states))
        # 交换：任意排列 bytes 一致
        for _ in range(4):
            perm = states[:]
            rng.shuffle(perm)
            assert _state_bytes(I.merge_states(perm)) == base
        # 结合：左折 pairwise == n-ary
        acc = states[0]
        for s in states[1:]:
            acc = I.merge_states([acc, s])
        assert _state_bytes(acc) == base
        # 幂等：merge(x,x) == x
        for s in states:
            assert _state_bytes(I.merge_states([s, s])) == _state_bytes(s)


def test_b4_conflicting_observation_forces_blocked():
    a = mk_state(closure_status="closed", satisfaction_status="satisfied", observed_value_json="1")
    b = mk_state(closure_status="closed", satisfaction_status="satisfied", observed_value_json="2")
    m = I.merge_states([a, b])
    assert m.closure_status == "blocked"
    assert m.blocked_reason_code == "ambiguous_merged_observation"
    assert "observed_value_json" in m.merged_observation_bottom
    assert m.satisfaction_status == "unknown"
    # 交换序结论一致
    assert _state_bytes(I.merge_states([a, b])) == _state_bytes(I.merge_states([b, a]))


def test_b4_bottom_absorbing():
    a = mk_state(observed_value_json="1")
    b = mk_state(observed_value_json="2")
    m1 = I.merge_states([a, b])  # observed → ⊥
    c = mk_state(observed_value_json="1")
    m2 = I.merge_states([m1, c])  # ⊥ 吸收：仍 ⊥
    assert "observed_value_json" in m2.merged_observation_bottom
    assert m2.closure_status == "blocked"


def test_b4_monotonic_never_relaxes_allow_stop():
    # ⊥→blocked 只会抬状态：closed 组冲突 → blocked（allow_stop 更难）
    a = mk_state(closure_status="closed", observed_value_json="1")
    b = mk_state(closure_status="closed", observed_value_json="2")
    assert I.merge_states([a, b]).closure_status == "blocked"


def test_merge_agreement_keeps_value():
    a = mk_state(observed_value_json="5", comparator_result=True)
    b = mk_state(observed_value_json="5", comparator_result=True)
    m = I.merge_states([a, b])
    assert m.observed_value_json == "5"
    assert m.comparator_result is True
    assert m.merged_observation_bottom == ()


def test_merge_max_by_rank_closure():
    a = mk_state(closure_status="closed")
    b = mk_state(closure_status="open", satisfaction_status="unknown", open_reason_code="missing_fact")
    assert I.merge_states([a, b]).closure_status == "open"
    c = mk_state(closure_status="blocked", satisfaction_status="unknown", blocked_reason_code="unit_mismatch")
    assert I.merge_states([b, c]).closure_status == "blocked"


def test_merge_open_reason_max_rank():
    a = mk_state(closure_status="open", satisfaction_status="unknown", open_reason_code="missing_fact")
    b = mk_state(
        closure_status="open", satisfaction_status="unknown",
        open_reason_code="applicability_uncertain",
    )
    # applicability_uncertain(7) > missing_fact(1)
    assert I.merge_states([a, b]).open_reason_code == "applicability_uncertain"


def test_merge_unknown_reason_code_hard_fail():
    a = mk_state(closure_status="open", satisfaction_status="unknown", open_reason_code="bogus_code")
    b = mk_state(closure_status="open", satisfaction_status="unknown", open_reason_code="missing_fact")
    with pytest.raises(I.ObligationContractError):
        I.merge_states([a, b])


# --- 全 ObligationV2 合并 --- #


def test_merge_obligations_immutable_conflict():
    idn = mk_identity()
    o1 = mk_obligation(identity=idn, immutable=I.ImmutablePayload(required=True, canonical_unit="mm", source_operator=""))
    o2 = mk_obligation(identity=idn, immutable=I.ImmutablePayload(required=False, canonical_unit="mm", source_operator=""))
    with pytest.raises(I.ObligationContractError) as exc:
        I.merge_obligations([o1, o2])
    assert "immutable" in str(exc.value)


def test_merge_obligations_mixed_scope_hard_fail():
    idn = mk_identity()
    o1 = mk_obligation(identity=idn, env=I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b1"))
    o2 = mk_obligation(identity=idn, env=I.RunInstanceEnvelope(run_id="r1", world_id="w1", building_id="b2"))
    with pytest.raises(I.ObligationContractError) as exc:
        I.merge_obligations([o1, o2])
    assert "mixed_scope" in str(exc.value)


def test_merge_obligations_provenance_union_and_bytes_order_invariant():
    idn = mk_identity()
    p1 = I.ObligationProvenanceV2(
        source_family_id="fam.x", slot_ref_ids=("s2", "s1"), artifact_local_ids=(),
        trigger_dependency_ids=(), evidence_fact_ids=("f1",), evidence_node_refs=(),
        source_clause_ids=("c1",), source_quote_ids=(), workflow_recipient_ids=(),
    )
    p2 = I.ObligationProvenanceV2(
        source_family_id="fam.x", slot_ref_ids=("s3",), artifact_local_ids=("a1",),
        trigger_dependency_ids=(), evidence_fact_ids=("f2",), evidence_node_refs=(),
        source_clause_ids=("c1", "c2"), source_quote_ids=(), workflow_recipient_ids=(),
    )
    o1 = mk_obligation(identity=idn, prov=p1, notes="n1")
    o2 = mk_obligation(identity=idn, prov=p2, notes="n2")
    m12 = I.merge_obligations([o1, o2])
    m21 = I.merge_obligations([o2, o1])
    assert canonical_json(m12.model_dump()) == canonical_json(m21.model_dump())
    assert m12.provenance.slot_ref_ids == ("s1", "s2", "s3")
    assert m12.provenance.source_clause_ids == ("c1", "c2")


def test_merge_obligations_depends_on_trigger_projection():
    # depends_on_open_trigger true 但合并后 trigger_dependency_ids 空 → 置 false
    idn = mk_identity()
    st = mk_state(closure_status="open", satisfaction_status="unknown",
                  open_reason_code="depends_on_open_trigger", depends_on_open_trigger=True)
    o = mk_obligation(identity=idn, state=st)
    m = I.merge_obligations([o])
    assert m.state.depends_on_open_trigger is False


# =========================================================================== #
# A.9 blind 传递闭包 import 扫描
# =========================================================================== #

_SRC_ROOT = Path(I.__file__).resolve().parents[2]  # .../agent_v1/src（parents[3]=agent_v1 会令 _module_to_path 全 None → 空转）
_FORBIDDEN_MODULE_PREFIXES = (
    "evo_agent_baseline.eval",
    "workflow_engine",
)
_FORBIDDEN_NAMES = ("TruthBundle", "threshold_evaluations")
_FIRST_PARTY_PREFIXES = ("canonical_profile", "evo_agent_baseline", "workflow_engine", "research_kg")


def _module_to_path(mod: str):
    rel = mod.replace(".", "/")
    cand_mod = _SRC_ROOT / (rel + ".py")
    cand_pkg = _SRC_ROOT / rel / "__init__.py"
    if cand_mod.exists():
        return cand_mod
    if cand_pkg.exists():
        return cand_pkg
    return None


def _collect_imports(path: Path):
    """返回 (imported_module_strings, imported_names)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.add(node.module)
                for alias in node.names:
                    names.add(alias.name)
    return mods, names


def _transitive_first_party(start_modules):
    seen = set()
    queue = list(start_modules)
    all_mods = set()
    all_names = set()
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = _module_to_path(mod)
        if path is None:
            continue
        mods, names = _collect_imports(path)
        all_mods |= mods
        all_names |= names
        for m in mods:
            if m.startswith(_FIRST_PARTY_PREFIXES) and m not in seen:
                queue.append(m)
    return seen, all_mods, all_names


def test_blind_transitive_import_scan():
    start = ["evo_agent_baseline.closure.identity_v2", "canonical_profile", "canonical_profile.profile"]
    # 防空转：起点模块路径必须解析（parents 根写错 → _module_to_path 全 None → 空扫）。
    assert _module_to_path("evo_agent_baseline.closure.identity_v2") is not None, "src 根解析错（空转）"
    reachable, all_mods, all_names = _transitive_first_party(start)
    # 传递闭包内任一模块的 import 均不得命中禁用前缀
    offending_mods = {
        m for m in all_mods if any(m == p or m.startswith(p + ".") for p in _FORBIDDEN_MODULE_PREFIXES)
    }
    assert not offending_mods, f"blind 违规 import 模块: {sorted(offending_mods)}"
    offending_names = {n for n in all_names if n in _FORBIDDEN_NAMES}
    assert not offending_names, f"blind 违规 import 名: {sorted(offending_names)}"
    # 确保确实扫到了 identity_v2（防空扫）
    assert "evo_agent_baseline.closure.identity_v2" in reachable


def test_blind_scanner_would_catch_violation(tmp_path):
    # 自检：扫描器对含 eval import 的文件确实报警
    f = tmp_path / "bad_mod.py"
    f.write_text("from evo_agent_baseline.eval.truth_loader import TruthBundle\n", encoding="utf-8")
    mods, names = _collect_imports(f)
    assert any(m.startswith("evo_agent_baseline.eval") for m in mods)
    assert "TruthBundle" in names
