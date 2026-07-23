"""artifact alias map [v0.4-C-1] + fact binding 测试。

覆盖 spec §6.3.6 的 17 个精确绑定 + 8 个 NOT_MODELED + 未登记新 key 处理，
以及 §6.4 fact binding 索引 / canonicalization / 冲突。
"""

from __future__ import annotations

import pytest

from canonical_profile.profile import CanonicalProfileError
from evo_agent_baseline.closure.fact_binding import (
    FactIndex,
    canonical_json,
    conflict_status,
    parse_json_number,
    parse_value,
    values_equivalent,
)
from evo_agent_baseline.closure.obligation_deriver import (
    ARTIFACT_KEY_TO_SIDECAR_SLOT,
    ARTIFACT_KEYS_NOT_MODELED,
    W0_09_ARTIFACT_SLOTS,
    SchemaContractError,
    resolve_artifact_slot,
)
from .fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)


def _wf(**kw):
    """workflow_operands 全 7 字段容器（WorkflowOperandsDTO 必填），只填传入子字段。"""
    base = {
        "primary_actor": "",
        "primary_action": "",
        "recipients": [],
        "artifacts": [],
        "deadlines": [],
        "audiences": [],
        "method_keys_allowed": [],
    }
    base.update(kw)
    return base


def _art(artifact_key, artifact_id="A.auto", artifact_type=""):
    """WorkflowArtifactDTO 必填三字段（float 只读 artifact_key）。"""
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "artifact_key": artifact_key,
    }


# ===================================================================== #
# §6.3.6 [v0.4-C-1] artifact alias map 收口断言
# ===================================================================== #
def test_c1_alias_map_17_precise_bindings():
    """精确绑定恰 17 个。"""
    assert len(ARTIFACT_KEY_TO_SIDECAR_SLOT) == 17


def test_c1_not_modeled_8_keys():
    """NOT_MODELED 恰 8 个。"""
    assert len(ARTIFACT_KEYS_NOT_MODELED) == 8


def test_c1_two_groups_disjoint():
    """精确绑定与 NOT_MODELED 不相交。"""
    assert (
        set(ARTIFACT_KEY_TO_SIDECAR_SLOT) & ARTIFACT_KEYS_NOT_MODELED == set()
    )


def test_c1_total_25_keys():
    """两组合计 25 个 artifact_key。"""
    assert len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT) | ARTIFACT_KEYS_NOT_MODELED) == 25


def test_c1_each_slot_at_most_one_key():
    """每个 sidecar slot 至多被一个 artifact_key 绑定（无共享）。"""
    assert len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values())) == 17


def test_c1_binding_targets_are_real_slots():
    """所有绑定目标都是真实 W0_09 artifact slot。"""
    assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values()) <= W0_09_ARTIFACT_SLOTS


def test_c1_mbi1_mbi2_not_in_map():
    """form.mbi1 / form.mbi2 不入 map（sidecar slot 但无 artifact_key）。"""
    assert "form.mbi1" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
    assert "form.mbi2" not in ARTIFACT_KEY_TO_SIDECAR_SLOT


def test_resolve_artifact_slot_precise():
    """精确绑定 key 返回对应 slot。"""
    assert (
        resolve_artifact_slot("report.inspection") == "artifact.report.inspection"
    )
    assert (
        resolve_artifact_slot("report.test_result")
        == "artifact.record.test_or_material_witness"
    )


def test_resolve_artifact_slot_not_modeled_returns_none():
    """NOT_MODELED key 返回 None。"""
    assert resolve_artifact_slot("notice.ri_appointment") is None
    assert resolve_artifact_slot("record.site_visit_log") is None


def test_resolve_artifact_slot_unknown_raises():
    """未登记新 key → 抛 SchemaContractError。"""
    with pytest.raises(SchemaContractError):
        resolve_artifact_slot("brand.new.unregistered_key")


# ===================================================================== #
# §6.3.6 NOT_MODELED key 走 blocked + artifact_not_modeled_upstream
# ===================================================================== #
def test_not_modeled_artifact_blocked():
    """NOT_MODELED artifact_key → blocked + artifact_not_modeled_upstream。"""
    card = make_rule_card(
        workflow_operands=_wf(artifacts=[_art("proposal.supervision")])
    )
    # 即便 sidecar 里恰好有共用 slot 的事实也不得假 satisfied。
    facts = [
        make_fact(
            "F1",
            slot_id="artifact.record.supervision_log_sp1",
            value="present",
            carrier_type="sidecar_entry",
        )
    ]
    result = run_closure(
        make_rule_slice([card]), make_fact_pack(facts)
    )
    art = [
        o for o in result.obligation_set.obligations if o.kind == "artifact"
    ][0]
    assert art.closure_status == "blocked"
    assert art.blocked_reason_code == "artifact_not_modeled_upstream"
    # 关键：不读共用 slot 事实、不产假 satisfied。
    assert art.satisfaction_status == "unknown"


def test_unknown_artifact_key_blocked_missing_mapping():
    """rule_card 出现未登记新 key → catalog 层 fail-closed 硬前置。

    identity-v5 现网键切换后：非法结构由 catalog 层 fail-closed 硬前置（旧 float 软 blocked
    路径活动流不可达）。
    """
    card = make_rule_card(
        workflow_operands=_wf(artifacts=[_art("weird.unregistered_artifact")])
    )
    with pytest.raises(CanonicalProfileError) as exc:
        run_closure(make_rule_slice([card]), make_fact_pack([]))
    assert "unknown_artifact_key" in str(exc.value)


def test_all_17_precise_keys_resolve():
    """17 个精确绑定 key 全部能 resolve 到 slot（不抛、不 None）。"""
    for key in ARTIFACT_KEY_TO_SIDECAR_SLOT:
        slot = resolve_artifact_slot(key)
        assert slot is not None
        assert slot.startswith("artifact.")


def test_all_8_not_modeled_keys_resolve_none():
    """8 个 NOT_MODELED key 全部 resolve 到 None。"""
    for key in ARTIFACT_KEYS_NOT_MODELED:
        assert resolve_artifact_slot(key) is None


# ===================================================================== #
# §6.4.1 fact indexes
# ===================================================================== #
def test_fact_index_builds_all_indexes():
    """FactIndex 把 fact 展进 slot / measure / carrier / artifact / method 索引。"""
    facts = [
        make_fact("F1", slot_id="s.a", value="x"),
        make_fact(
            "F2", measure_key="m.b", value=1, value_type="number",
            carrier_type="measurement",
        ),
        make_fact("F3", slot_id="artifact.report.inspection", value="present"),
        make_fact(
            "F4", slot_id="s.c", value="y", qualifiers={"method_class": "tap_test"}
        ),
    ]
    idx = FactIndex(make_fact_pack(facts))
    assert "s.a" in idx.slot_index
    assert "m.b" in idx.measure_index
    assert "artifact.report.inspection" in idx.artifact_index
    assert "tap_test" in idx.method_index
    # carrier 索引按 carrier_id 归并。
    assert idx.carrier_index


def test_fact_index_canonical_slot_alias():
    """slot_aliases 把原始 slot_id 归一到 canonical。"""
    facts = [make_fact("F1", slot_id="raw.slot", value="v")]
    idx = FactIndex(
        make_fact_pack(facts), slot_aliases={"raw.slot": "canon.slot"}
    )
    # fact 进 canonical key。
    assert "canon.slot" in idx.slot_index
    assert idx.canonical_slot("raw.slot") == "canon.slot"


def test_fact_index_canonical_measure_alias():
    """measure_aliases 归一。"""
    facts = [
        make_fact(
            "F1", measure_key="raw.m", value=1, value_type="number",
            carrier_type="measurement",
        )
    ]
    idx = FactIndex(
        make_fact_pack(facts), measure_aliases={"raw.m": "canon.m"}
    )
    assert "canon.m" in idx.measure_index
    assert idx.canonical_measure("raw.m") == "canon.m"


# ===================================================================== #
# §6.4.2 canonicalization / 值解析
# ===================================================================== #
def test_canonical_json_key_sorted():
    """canonical_json 对象 key 排序、去空白。"""
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_parse_value():
    """parse_value 解析各类型。"""
    assert parse_value('"hello"') == "hello"
    assert parse_value("42") == 42
    assert parse_value("true") is True
    assert parse_value("null") is None
    assert parse_value(None) is None


def test_parse_json_number():
    """parse_json_number 只接受数值。"""
    assert parse_json_number("3.5") == 3.5
    assert parse_json_number("10") == 10.0
    assert parse_json_number('"abc"') is None
    assert parse_json_number("true") is None  # bool 不算数值


# ===================================================================== #
# §6.4.4 conflict handling / equivalence
# ===================================================================== #
def test_values_equivalent_numeric_tolerance():
    """数值容差内视为等价。"""
    assert values_equivalent(1.0, 1.0 + 1e-12) is True
    assert values_equivalent(1.0, 1.5) is False


def test_values_equivalent_object():
    """object 按 canonical JSON 相等。"""
    assert values_equivalent({"a": 1, "b": 2}, {"b": 2, "a": 1}) is True


def test_conflict_status_three_states():
    """conflict_status 三态。"""
    f_a = make_fact("F1", slot_id="s", value="x")
    f_b = make_fact("F2", slot_id="s", value="x")
    f_c = make_fact("F3", slot_id="s", value="y")
    assert conflict_status([]) == "missing"
    assert conflict_status([f_a, f_b]) == "consistent"
    assert conflict_status([f_a, f_c]) == "ambiguous"


# ===================================================================== #
# §6.4.3 target scoping
# ===================================================================== #
def test_target_scoping_fragment_priority():
    """fragment 专属事实优先于 building-level。"""
    facts = [
        make_fact(
            "Fbld", slot_id="s.x", value="building_val", carrier_type="building",
            carrier_id="BLD-test-001",
        ),
        make_fact(
            "Ffrag", slot_id="s.x", value="frag_val", carrier_type="fragment",
            carrier_id="FRAG-1",
        ),
    ]
    idx = FactIndex(make_fact_pack(facts))
    candidates = idx.slot_index["s.x"]
    scoped = idx.scoped_facts(candidates, fragment_id="FRAG-1")
    assert len(scoped) == 1
    assert scoped[0].fact_id == "Ffrag"
