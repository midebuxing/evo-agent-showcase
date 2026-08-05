"""Q1=(c)：unknown 作用域关系旁路的五道验收门。"""

from __future__ import annotations

from dataclasses import replace
from typing import get_args

import pytest

from evo_agent_baseline.agent.report_writer import (
    render_scope_relation_diagnostic_section,
    render_unknown_attribution_section,
)
from evo_agent_baseline.closure import unknown_attribution as ua
from evo_agent_baseline.closure.tests.fixtures import make_fact, make_rule_card, make_rule_slice, run_closure
from evo_agent_baseline.closure.tests.test_unknown_attribution_invariance import (
    _scenario,
    full_dump_modulo_attribution,
    verdict_fingerprint,
)
from evo_agent_baseline.contracts import (
    ScopeRelationKind,
    UnknownAttribution,
    UnknownCauseCode,
    UnknownScopeRelation,
)


def _relation_policy(*, authorization: bool = True):
    auth = {"RC.scope": "drainage_component"} if authorization else {}
    return ua.build_scope_relation_policy(
        make_rule_slice(
            [],
            retrieval_policy={
                "component_type_lattice": {
                    "version": "component_type_lattice.v1",
                    "leaf_types": [
                        "drainage_component",
                        "external_wall",
                        "fire_safety_component",
                    ],
                    "non_leaf_types": ["external_component"],
                    "subsumption": {"external_component": ["external_wall"]},
                    "disjoint_pairs": [["drainage_component", "external_wall"]],
                },
                "exact_fragment_target_authorizations": auth,
                "exact_fragment_target_authorizations_version": (
                    "exact_fragment_target_authorizations.v1"
                ),
            },
        )
    )


def _snapshot(
    *,
    obligation_id: str = "O.scope",
    card_types=("external_component",),
    fragment_type="external_wall",
):
    return ua.UnknownObligationSnapshot(
        obligation_id=obligation_id,
        closure_status="blocked",
        fragment_id="FRAG-1",
        canonical_slot_ids=(),
        declared_qualifiers=frozenset(),
        trigger_dependency_ids=(),
        depends_on_open_trigger=False,
        kind="action",
        action=None,
        card_component_type_keys=tuple(card_types),
        fragment_component_type=fragment_type,
    )


def _cause_fingerprint(result):
    return sorted(
        (
            obligation_id,
            attr.cause_code,
            attr.validator_reason_code,
            tuple(attr.root_dependency_ids),
        )
        for obligation_id, attr in (
            result.unknown_attribution_by_obligation_id or {}
        ).items()
    )


def _without_relation(mapping, snapshots, policy, **kwargs):
    return dict(mapping)


def test_gate_1_judgement_is_bitwise_invariant(monkeypatch):
    """第一道门：逐义务判定、汇总与 allow_stop 全部逐位不变。"""
    rule_slice, fact_pack = _scenario()
    baseline = run_closure(rule_slice, fact_pack)
    baseline_verdict = verdict_fingerprint(baseline)
    baseline_full = full_dump_modulo_attribution(baseline)

    monkeypatch.setattr(ua, "attach_scope_relations", _without_relation)
    variant = run_closure(rule_slice, fact_pack)

    assert verdict_fingerprint(variant) == baseline_verdict
    assert full_dump_modulo_attribution(variant) == baseline_full


def test_scope_relation_failure_is_isolated_from_judgement(monkeypatch):
    """关系旁路自身抛错时只降级身份诊断，不能中断或改变判定。"""
    rule_slice, fact_pack = _scenario()
    baseline = run_closure(rule_slice, fact_pack)

    def boom(*args, **kwargs):
        raise RuntimeError("关系旁路故意抛错")

    monkeypatch.setattr(ua, "attach_scope_relations", boom)
    variant = run_closure(rule_slice, fact_pack)

    assert verdict_fingerprint(variant) == verdict_fingerprint(baseline)
    assert full_dump_modulo_attribution(variant) == full_dump_modulo_attribution(
        baseline
    )
    assert _cause_fingerprint(variant) == _cause_fingerprint(baseline)
    assert all(
        attr.scope_relation is not None
        and attr.scope_relation.relation == "identity_unavailable"
        for attr in (variant.unknown_attribution_by_obligation_id or {}).values()
    )
    audit = variant.machine_readable_report["unknown_attribution_audit"]
    assert audit["scope_relation_degraded"] is True
    assert audit["scope_relation_conservation_passed"] is True

def test_gate_2_existing_causes_are_bitwise_invariant(monkeypatch):
    """第二道门：既有原因码、验证器码与根依赖逐位不变。"""
    rule_slice, fact_pack = _scenario()
    baseline = run_closure(rule_slice, fact_pack)
    baseline_causes = _cause_fingerprint(baseline)

    monkeypatch.setattr(ua, "attach_scope_relations", _without_relation)
    variant = run_closure(rule_slice, fact_pack)

    assert _cause_fingerprint(variant) == baseline_causes
    assert set(get_args(ScopeRelationKind)).isdisjoint(
        set(get_args(UnknownCauseCode))
    )


def test_gate_3_relation_conservation_equals_unknown_total():
    """第三道门：六类关系计数之和严格等于 unknown 总数。"""
    mapping = {
        f"O.{index}": UnknownAttribution(
            obligation_id=f"O.{index}",
            responsibility="system_unresolved",
            cause_code="attribution_input_missing",
            explanation="测试",
            root_dependency_ids=[],
            policy_version="unknown_attribution.v3",
        )
        for index in range(6)
    }
    snapshots = (
        _snapshot(obligation_id="O.0", card_types=("external_wall",)),
        _snapshot(obligation_id="O.1"),
        _snapshot(obligation_id="O.2", card_types=("drainage_component",)),
        _snapshot(obligation_id="O.3", card_types=("fire_safety_component",)),
        _snapshot(obligation_id="O.4", card_types=()),
        _snapshot(obligation_id="O.5", fragment_type=None),
    )
    attached = ua.attach_scope_relations(
        mapping,
        snapshots,
        _relation_policy(),
        rule_card_ids_by_obligation_id={"O.2": "RC.scope"},
    )
    audit = ua.summarize_attribution(attached)

    assert sum(audit["scope_relation_counts"].values()) == len(mapping)
    assert audit["scope_relation_missing_count"] == 0
    assert audit["scope_relation_conservation_passed"] is True
    assert set(audit["scope_relation_counts"]) == {
        "same",
        "category_compatible",
        "authorized_disjoint",
        "different_unresolved",
        "card_unconstrained",
        "identity_unavailable",
    }


def test_gate_4_parent_category_matches_external_wall():
    """第四道门：external_component × external_wall 必为类目相容。"""
    relation = ua.classify_scope_relation(
        _snapshot(),
        _relation_policy(),
        rule_card_id="RC.other",
    )
    assert relation.relation == "category_compatible"


@pytest.mark.parametrize(
    ("snapshot", "policy", "card_id", "expected"),
    [
        (
            _snapshot(card_types=("drainage_component",)),
            _relation_policy(authorization=False),
            "RC.scope",
            "different_unresolved",
        ),
        (
            _snapshot(card_types=("structural_component",)),
            replace(
                _relation_policy(),
                authorized_targets=(("RC.scope", "structural_component"),),
                disjoint_pairs=frozenset(
                    {frozenset(("structural_component", "external_wall"))}
                ),
            ),
            "RC.scope",
            "different_unresolved",
        ),
        (
            _snapshot(
                card_types=("drainage_component",),
                fragment_type="fire_safety_component",
            ),
            _relation_policy(),
            "RC.scope",
            "different_unresolved",
        ),
        (
            _snapshot(fragment_type=None),
            _relation_policy(),
            "RC.scope",
            "identity_unavailable",
        ),
    ],
)
def test_gate_5_default_rejects_without_complete_evidence(
    snapshot, policy, card_id, expected
):
    """第五道门：授权、叶型、互斥或身份任一证据不足都不得授权互斥。"""
    relation = ua.classify_scope_relation(
        snapshot,
        policy,
        rule_card_id=card_id,
    )
    assert relation.relation == expected
    assert relation.relation != "authorized_disjoint"


def test_gate_5_duplicate_and_missing_w0_identity_are_unavailable():
    """第五道门：身份只能来自唯一 W0 专用原子，重复或缺席都不可用。"""
    genuine = make_fact(
        "W0.1",
        slot_id="w0_component_identity",
        value="external_wall",
        qualifiers={"fragment_id": "FRAG-1"},
        provenance={"channel": "w0_component_identity"},
    )
    duplicate = make_fact(
        "W0.2",
        slot_id="w0_component_identity",
        value="external_wall",
        qualifiers={"fragment_id": "FRAG-1"},
        provenance={"channel": "w0_component_identity"},
    )
    ordinary = make_fact(
        "F.ordinary",
        slot_id="other.slot",
        value=True,
        value_type="boolean",
        qualifiers={
            "fragment_id": "FRAG-2",
            "component_type_key": "external_wall",
        },
    )
    identities = ua.build_fragment_component_type_map(
        [genuine, duplicate, ordinary]
    )
    assert identities["FRAG-1"] is None
    assert "FRAG-2" not in identities
    for fragment_id in ("FRAG-1", "FRAG-2"):
        relation = ua.classify_scope_relation(
            _snapshot(fragment_type=identities.get(fragment_id)),
            _relation_policy(),
            rule_card_id="RC.scope",
        )
        assert relation.relation == "identity_unavailable"

    unconstrained_and_missing = ua.classify_scope_relation(
        _snapshot(card_types=(), fragment_type=None),
        _relation_policy(),
        rule_card_id="RC.scope",
    )
    assert unconstrained_and_missing.relation == "identity_unavailable"


def test_card_component_reader_covers_all_three_card_locations():
    """卡侧构件类型沿用统一读取器，覆盖槽、阈值与触发条件。"""
    card = make_rule_card(
        "RC.reader",
        slot_role_map=[
            {
                "slot_ref_id": "SR.1",
                "slot_id": "slot.1",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {"component_type_key": "external_wall"},
            }
        ],
        threshold_regimes=[
            {
                "threshold_regime_id": "TR.1",
                "qualifiers": {"component_type_key": "drainage_component"},
            }
        ],
        trigger_conditions={
            "logic": "all",
            "items": [
                {
                    "condition_id": "C.1",
                    "predicate_kind": "slot",
                    "slot_ref_id": "SR.1",
                    "operator": "==",
                    "expected_value": True,
                    "qualifiers": {
                        "component_type_key": "fire_safety_component"
                    },
                }
            ],
        },
    )
    found = ua.build_card_component_type_key_map(make_rule_slice([card]))
    assert found["RC.reader"] == (
        "drainage_component",
        "external_wall",
        "fire_safety_component",
    )


def test_report_is_independent_conservative_and_contains_no_forbidden_wording():
    """报告保留既有原因，并把关系轴单列为保守诊断。"""
    rule_slice, fact_pack = _scenario()
    result = run_closure(rule_slice, fact_pack)
    mapping = dict(result.unknown_attribution_by_obligation_id or {})
    assert len(mapping) >= 2
    for index, (obligation_id, attr) in enumerate(mapping.items()):
        relation = (
            UnknownScopeRelation(
                card_component_type_keys=("drainage_component",),
                fragment_component_type="external_wall",
                relation="authorized_disjoint",
                target_authorization_status="effective_authorization_present",
                relation_policy_version="scope_relation.v1|test",
            )
            if index == 0
            else UnknownScopeRelation(
                card_component_type_keys=("external_component",),
                fragment_component_type="external_wall",
                relation="category_compatible",
                target_authorization_status="effective_authorization_absent",
                relation_policy_version="scope_relation.v1|test",
            )
        )
        mapping[obligation_id] = attr.model_copy(
            update={"scope_relation": relation}
        )
    updated = result.model_copy(
        update={"unknown_attribution_by_obligation_id": mapping}
    )
    section = "\n".join(render_scope_relation_diagnostic_section(updated))

    assert "## 作用域关系诊断" in section
    assert "状态仍为未知，判定未改变" in section
    assert "类目相容" in section
    assert "经授权且显式互斥" in section
    assert "当前直接阻塞机制仍为" in section
    assert "规格、召回及漏项审查" in section
    forbidden = (
        "不该" + "被评",
        "本卡" + "不适用",
        "无需" + "评估",
        "系统判断正确" + "只是标签错",
        "已" + "解决",
    )
    assert all(word not in section for word in forbidden)

    full_section = "\n".join(render_unknown_attribution_section(updated))
    assert "| 说明 | 条数 | 原因码 |" in full_section
    assert full_section.count("## 作用域关系诊断") == 1
    cause_counts = {}
    for attr in mapping.values():
        cause_counts[attr.cause_code] = cause_counts.get(attr.cause_code, 0) + 1
    for cause_code, expected_count in cause_counts.items():
        matching_lines = [
            line
            for line in full_section.splitlines()
            if f"<code>{cause_code}</code>" in line
        ]
        assert len(matching_lines) == 1
        assert f"| {expected_count} |" in matching_lines[0]