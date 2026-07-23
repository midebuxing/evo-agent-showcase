"""identity-v2 阶段二求值器验收 —— 逐义务状态等价 + merge_states≡_merge_two + 组装/去重/碰撞。

**本单元核心价值 = allow_stop 零漂移地基**：

1. **逐义务状态等价（覆盖 channel）**：对每条**真派生义务**（构造卡子集 + 全 397 真语料），
   断言阶段二 `ObligationStateV2.closure_status/satisfaction_status/open_reason_code/
   blocked_reason_code/comparator_result` 与 v1 同源 `Obligation` **逐条一致**（不一致清单应空）。
   等价性由构造保证（v2 状态 = v1 verdict 无判定重打包）；本测试守护重打包无丢字段/无误译，
   且验证 v1 全语料所有 operator/reason_code 经映射器不触 ValidationError。

2. **merge 验收契约（诚实化，blocker 2 / 修 overclaim）= 判定投影等价 + reason 一般发散、advisory
   层可达**：v2 `merge_states` 是 **order-independent** committed 契约（A.7，不可动），v1 `_merge_two`
   是 **order-dependent** 生产语义。断言：**判定投影**（closure_status + satisfaction_status，
   = allow_stop 地基）在**生产 `_merge_two` 真语义**（非改序 helper）下全 reason 序表 cross-product
   **字节等价**（0 mismatch）；reason_code 选择在合并**异 reason** 时**一般发散**（全 v1-可构造序表
   实测 106 处，含 25 处 advisory tier 非保守）——**旧「恰 2 对保守漂移」overclaim 已删**。**旧「生产
   不可达」声称亦已删——被 codex 证伪**：identity 不含 FactIndex 快照 ⟹ 同 (scope, identity) 可来自
   **不同事实快照**产**异 reason**（活代码反例：同 evidence blueprint 两快照产 `missing_measurement` /
   `missing_required_field_group`，送 finalize 合并成功、reason 漂移）。故 reason 漂移**可达**、落点仅
   **advisory 层**（reason_code + 高风险 tier → 报告排序 + 人工复核提示），**不入 allow_stop、不改判定
   投影**。真语料当前 2310 组全 singleton（无多成员组），**不演任何真实 merge**——它是事实快照、**不证**
   漂移不可达。**不声称完整 12 字段 state 等价**——验收落点是 allow_stop 地基 + 判定投影等价，reason/tier
   的 advisory 漂移登记为已知限制。v2 另有 B4 观测冲突→blocked（⊥）是**严格更保守**的附加闸（v1 无、
   方向与零漂移一致：v2 blocked ⟹ ¬allow_stop）。

3. **组装 + 去重/碰撞**：`assemble_obligation_v2` 冻结身份 + 阶段二状态；`finalize_obligations_v2`
   分组合并 + 发布前 `run_collision_postcheck`。

4. **applicability 隔离**：据实报的 DTO/求值器类型缺陷 → 隔离，不接阶段二状态。

加性：只调用 v1 `evaluate_*`/`aggregate_trigger_logic`（读语义），不改 v1 判定路径。
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import ValidationError

from evo_agent_baseline.contracts import Obligation, RuleCardDTO
from evo_agent_baseline.closure import blueprint_deriver as B
from evo_agent_baseline.closure import blueprint_state_eval as S
from evo_agent_baseline.closure import identity_v2 as I
from evo_agent_baseline.closure import obligation_deriver as D
from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.rulecard_decimal_load import load_identity_cards
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
)
from evo_agent_baseline.closure.validator import (
    _merge_two,
    compute_allow_stop_and_reason,
    dedupe_key_v1 as v1_dedupe_key,
    find_high_risk_items,
    sort_and_dedupe_obligations_v1 as sort_and_dedupe_obligations,
)

_META = {"run_id": "R-st-001", "world_id": "WB-st-001", "building_id": "BLD-st-001"}


def _index(facts: Optional[List] = None) -> FactIndex:
    return FactIndex(make_fact_pack(facts or []))


# =========================================================================== #
# 源子结构构造器（strict DTO 需全必填字段）
# =========================================================================== #


def _th(**kw) -> Dict[str, Any]:
    d = dict(
        threshold_regime_id="t.1", measure_key="measure.crack_width", operator="<=",
        unit="mm", qualifiers={}, source_quote_refs=[], value=7,
    )
    d.update(kw)
    return d


def _slot_role(**kw) -> Dict[str, Any]:
    d = dict(
        slot_ref_id="sr1", slot_id="repair.required", qualifiers={},
        roles=["evidence"], required=True,
    )
    d.update(kw)
    return d


def _trigger(**kw) -> Dict[str, Any]:
    d = dict(condition_id="c.1", predicate_kind="slot", operator="==",
             expected_value=True, slot_ref_id="sr1")
    d.update(kw)
    return d


def _evidence(**kw) -> Dict[str, Any]:
    d = dict(
        evidence_requirement_id="ev1", kind="photo", required=True, description="",
        artifact_ids=[], slot_ref_ids=[], measure_keys=[], required_field_groups=[],
    )
    d.update(kw)
    return d


def _wf_artifact(**kw) -> Dict[str, Any]:
    d = dict(artifact_id="A1", artifact_type="form", artifact_key="form.mbi4")
    d.update(kw)
    return d


def _workflow(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "primary_actor": "", "primary_action": "", "recipients": [],
        "artifacts": artifacts, "deadlines": [], "audiences": [],
        "method_keys_allowed": [],
    }


# =========================================================================== #
# 状态等价断言核心
# =========================================================================== #

# ObligationStateV2 逐字段 ↔ v1 Obligation 的等价投影（本模块契约）。
_STATE_EQUIV_FIELDS = (
    "closure_status",
    "satisfaction_status",
    "applicability_state",
    "trigger_state",
    "depends_on_open_trigger",
    "comparator_result",
    "observed_value_json",
    "open_reason_code",
    "blocked_reason_code",
)


def _state_mismatches(o: Obligation, st: I.ObligationStateV2) -> List[str]:
    """返回 v2 state 与 v1 obligation 不一致的字段清单（应为空）。"""
    out: List[str] = []
    for f in _STATE_EQUIV_FIELDS:
        if getattr(o, f) != getattr(st, f):
            out.append(f"{f}: v1={getattr(o, f)!r} != v2={getattr(st, f)!r}")
    # expected_value_json → evaluated_expected_value_json（改名字段）
    if o.expected_value_json != st.evaluated_expected_value_json:
        out.append(
            f"expected_value_json: v1={o.expected_value_json!r} "
            f"!= v2.evaluated_expected_value_json={st.evaluated_expected_value_json!r}"
        )
    # operator → evaluated_comparator（同语义映射，仅 8 比较器保留，其余 → ""）
    expected_comp = o.operator if o.operator in S._V2_COMPARATORS else ""
    if expected_comp != st.evaluated_comparator:
        out.append(
            f"operator→evaluated_comparator: v1={o.operator!r} → 期望 {expected_comp!r} "
            f"!= v2={st.evaluated_comparator!r}"
        )
    return out


def _assert_pair_equiv(p: S.PairedObligationV2) -> None:
    mm = _state_mismatches(p.v1_obligation, p.obligation_v2.state)
    assert not mm, f"[{p.channel}] 状态不一致: {mm}"


# =========================================================================== #
# 1. 逐义务状态等价 —— 覆盖 channel 各 verdict 分支（构造卡子集）
# =========================================================================== #


def test_threshold_state_equivalence_all_branches():
    """threshold：satisfied / violated / open(missing) / blocked(unit_mismatch) / formula 各分支等价。"""
    card = make_rule_card("rc.th")
    cases = [
        # (facts, expected closure, expected satisfaction)
        ([make_fact("f", measure_key="measure.crack_width", value=5, value_type="number", unit="mm")],
         "closed", "satisfied"),
        ([make_fact("f", measure_key="measure.crack_width", value=9, value_type="number", unit="mm")],
         "closed", "violated"),
        ([], "open", "unknown"),
        ([make_fact("f", measure_key="measure.crack_width", value=5, value_type="number", unit="cm")],
         "blocked", "unknown"),
    ]
    for facts, exp_cl, exp_sat in cases:
        fi = _index(facts)
        th = _th(threshold_regime_id="rc.th.t01")
        o = D.evaluate_threshold(card, dict(th), fi, True, _META)
        bp = B.build_threshold_blueprint(card, dict(th), _META)
        v2 = S.assemble_obligation_v2(bp, o)
        assert (o.closure_status, o.satisfaction_status) == (exp_cl, exp_sat)
        _assert_pair_equiv(S.PairedObligationV2("threshold", bp, o, v2))


def test_threshold_formula_state_equivalence():
    """threshold formula：satisfied(观测达标) + open(缺输入) 分支等价；operator→evaluated_comparator 映射正确。"""
    th = {
        "threshold_regime_id": "rc.f.t01",
        "measure_key": "count.pull_test.additional_after_failure",
        "operator": "formula", "unit": "test", "qualifiers": {}, "source_quote_refs": [],
        "value": None,
        "formula": {"expression": "n^2 - 2n + 3",
                    "variables": [{"symbol": "n", "measure_key": "count.pull_test.failed_cumulative"}]},
    }
    card = make_rule_card("rc.f", threshold_regimes=[th])
    # satisfied：n=3 → expected 6，observed 10 >= 6
    fi = _index([
        make_fact("f1", measure_key="count.pull_test.failed_cumulative", value=3, value_type="number"),
        make_fact("f2", measure_key="count.pull_test.additional_after_failure", value=10, value_type="number"),
    ])
    o = D.evaluate_threshold(card, dict(th), fi, True, _META)
    bp = B.build_threshold_blueprint(card, dict(th), _META)
    v2 = S.assemble_obligation_v2(bp, o)
    assert (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")
    assert o.operator == ">="  # threshold_eval 覆写
    assert v2.state.evaluated_comparator == ">="  # 运行时比较器保留
    _assert_pair_equiv(S.PairedObligationV2("threshold", bp, o, v2))

    # open：缺输入度量 → operator 停留 "formula"（未达比较）→ evaluated_comparator=""
    o2 = D.evaluate_threshold(card, dict(th), _index([]), True, _META)
    v2b = S.assemble_obligation_v2(bp, o2)
    assert o2.closure_status == "open"
    assert o2.operator == "formula"
    assert v2b.state.evaluated_comparator == ""  # "formula" 非 8 比较器 → 未评估哨兵
    _assert_pair_equiv(S.PairedObligationV2("threshold", bp, o2, v2b))


def test_trigger_state_equivalence_slot_and_measure():
    """trigger：slot true/false/missing + measure 各分支等价。"""
    card = make_rule_card("rc.tr", slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="defect.present")])
    # slot true → closed+satisfied
    tr = _trigger(condition_id="c1", slot_ref_id="sr1", operator="==", expected_value=True)
    for facts, exp_cl, exp_sat in [
        ([make_fact("f", slot_id="defect.present", value=True, value_type="boolean")], "closed", "satisfied"),
        ([make_fact("f", slot_id="defect.present", value=False, value_type="boolean")], "closed", "not_applicable"),
        ([], "open", "unknown"),
    ]:
        fi = _index(facts)
        o = D.evaluate_trigger(card, dict(tr), fi, _META)
        bp = B.build_trigger_blueprint(card, dict(tr), _META)
        v2 = S.assemble_obligation_v2(bp, o)
        assert (o.closure_status, o.satisfaction_status) == (exp_cl, exp_sat)
        _assert_pair_equiv(S.PairedObligationV2("trigger", bp, o, v2))

    # measure trigger
    mtr = {"condition_id": "c2", "predicate_kind": "measure", "operator": ">=",
           "expected_value": 5, "measure_key": "measure.crack_width"}
    fi = _index([make_fact("f", measure_key="measure.crack_width", value=8, value_type="number")])
    o = D.evaluate_trigger(card, dict(mtr), fi, _META)
    bp = B.build_trigger_blueprint(card, dict(mtr), _META)
    _assert_pair_equiv(S.PairedObligationV2("trigger", bp, o, S.assemble_obligation_v2(bp, o)))


def test_slot_role_state_equivalence():
    """slot_role：satisfied(有事实) / open(缺事实) / blocked(qualifier_conflict) 分支等价。"""
    card = make_rule_card("rc.sr")
    sr = _slot_role(slot_ref_id="sr1", slot_id="repair.required")
    for facts, exp_cl in [
        ([make_fact("f", slot_id="repair.required", value=True, value_type="boolean")], "closed"),
        ([], "open"),
    ]:
        fi = _index(facts)
        o = D.evaluate_slot_role(card, dict(sr), fi, True, _META)
        bp = B.build_slot_role_blueprint(card, dict(sr), _META)
        assert o.closure_status == exp_cl
        _assert_pair_equiv(S.PairedObligationV2("slot_role", bp, o, S.assemble_obligation_v2(bp, o)))

    # qualifier_conflict → blocked
    srq = _slot_role(slot_ref_id="sr2", slot_id="repair.required",
                     qualifiers={"component_type_key": "beam"})
    fi = _index([make_fact("f", slot_id="repair.required", value=True, value_type="boolean",
                           qualifiers={"component_type_key": "column"})])
    o = D.evaluate_slot_role(card, dict(srq), fi, True, _META)
    bp = B.build_slot_role_blueprint(card, dict(srq), _META)
    assert o.closure_status == "blocked" and o.blocked_reason_code == "qualifier_conflict"
    _assert_pair_equiv(S.PairedObligationV2("slot_role", bp, o, S.assemble_obligation_v2(bp, o)))


def test_slot_role_trigger_inheritance_equivalence():
    """slot_role：trigger_active=open/blocked 继承分支等价（depends_on_open_trigger/trigger_state 携带）。"""
    card = make_rule_card("rc.inh")
    sr = _slot_role(slot_ref_id="sr1", slot_id="repair.required")
    fi = _index([])
    # trigger open 继承
    o_open = D.evaluate_slot_role(card, dict(sr), fi, "open", _META)
    bp = B.build_slot_role_blueprint(card, dict(sr), _META)
    v2 = S.assemble_obligation_v2(bp, o_open)
    assert o_open.closure_status == "open" and o_open.depends_on_open_trigger
    assert v2.state.depends_on_open_trigger and v2.state.trigger_state == "open"
    _assert_pair_equiv(S.PairedObligationV2("slot_role", bp, o_open, v2))
    # trigger blocked 继承
    o_blk = D.evaluate_slot_role(card, dict(sr), fi, "blocked", _META)
    v2b = S.assemble_obligation_v2(bp, o_blk)
    assert o_blk.closure_status == "blocked" and o_blk.trigger_state == "blocked"
    _assert_pair_equiv(S.PairedObligationV2("slot_role", bp, o_blk, v2b))


def test_workflow_artifact_state_equivalence():
    """workflow_artifact：satisfied(present) / violated(absent) / blocked(not_modeled) 分支等价。"""
    card = make_rule_card("rc.wa", workflow_operands=_workflow([_wf_artifact(artifact_id="A1", artifact_key="form.mbi4")]))
    slot = D.ARTIFACT_KEY_TO_SIDECAR_SLOT["form.mbi4"]
    for facts, exp_sat in [
        ([make_fact("f", slot_id=slot, value="present", carrier_type="sidecar_entry")], "satisfied"),
        ([make_fact("f", slot_id=slot, value="absent", carrier_type="sidecar_entry")], "violated"),
    ]:
        fi = _index(facts)
        item = _wf_artifact(artifact_id="A1", artifact_key="form.mbi4")
        o = D.evaluate_artifact_obligation(card, "form.mbi4", "artifact", fi, True, _META,
                                           artifact_id="A1", bucket="workflow_operands.artifacts")
        bp = B.build_workflow_artifact_blueprint(card, dict(item), _META)
        assert o.closure_status == "closed" and o.satisfaction_status == exp_sat
        _assert_pair_equiv(S.PairedObligationV2("workflow_artifact", bp, o, S.assemble_obligation_v2(bp, o)))

    # not_modeled key → blocked（用 evidence 蓝图承载不建模 key，因 workflow 蓝图 canonicalize 会拒未登记；
    # 此处用登记但 NOT_MODELED 的 key）
    nm_key = "notice.ri_appointment"  # ∈ ARTIFACT_KEYS_NOT_MODELED
    card2 = make_rule_card("rc.wanm", workflow_operands=_workflow([_wf_artifact(artifact_id="A2", artifact_key=nm_key)]))
    fi = _index([])
    o = D.evaluate_artifact_obligation(card2, nm_key, "artifact", fi, True, _META,
                                       artifact_id="A2", bucket="workflow_operands.artifacts")
    bp = B.build_workflow_artifact_blueprint(card2, _wf_artifact(artifact_id="A2", artifact_key=nm_key), _META)
    assert o.closure_status == "blocked" and o.blocked_reason_code == "artifact_not_modeled_upstream"
    _assert_pair_equiv(S.PairedObligationV2("workflow_artifact", bp, o, S.assemble_obligation_v2(bp, o)))


def test_evidence_state_equivalence():
    """evidence：slot 通道(satisfied) / measure 通道(satisfied) / open(缺引用) 分支等价。"""
    card = make_rule_card(
        "rc.ev",
        slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="repair.required")],
    )
    # slot 通道
    req_slot = _evidence(evidence_requirement_id="e1", slot_ref_ids=["sr1"])
    fi = _index([make_fact("f", slot_id="repair.required", value=True, value_type="boolean")])
    o = D.evaluate_evidence_requirement(card, "for_matching", dict(req_slot), fi, True, _META)
    bp = B.build_evidence_blueprint(card, "for_matching", dict(req_slot), _META)
    assert o.closure_status == "closed"
    _assert_pair_equiv(S.PairedObligationV2("evidence", bp, o, S.assemble_obligation_v2(bp, o)))

    # measure 通道
    req_m = _evidence(evidence_requirement_id="e2", measure_keys=["measure.crack_width"])
    fi = _index([make_fact("f", measure_key="measure.crack_width", value=5, value_type="number")])
    o = D.evaluate_evidence_requirement(card, "for_matching", dict(req_m), fi, True, _META)
    bp = B.build_evidence_blueprint(card, "for_matching", dict(req_m), _META)
    _assert_pair_equiv(S.PairedObligationV2("evidence", bp, o, S.assemble_obligation_v2(bp, o)))

    # required_field_groups 缺失 → open
    req_g = _evidence(evidence_requirement_id="e3", required_field_groups=["grp.x"])
    o = D.evaluate_evidence_requirement(card, "for_matching", dict(req_g), _index([]), True, _META)
    bp = B.build_evidence_blueprint(card, "for_matching", dict(req_g), _META)
    assert o.closure_status == "open" and o.open_reason_code == "missing_required_field_group"
    _assert_pair_equiv(S.PairedObligationV2("evidence", bp, o, S.assemble_obligation_v2(bp, o)))


def test_definition_state_equivalence():
    """definition：closed(有事实/引用) 分支等价。"""
    card = make_rule_card(
        "rc.def",
        definitions=[{"definition_id": "d01", "term_key": "ri_supervision_team",
                      "definition_text": "t", "scope_note": "s", "source_quote_refs": ["sq01"]}],
    )
    defn = card.definitions[0]
    # DEBT-057 后 v1 与蓝图端均保留 source_quote_refs 全部引用；有 quote → closed+satisfied。
    o = D.evaluate_definition(card, dict(defn), _index([]), _META)
    bp = B.build_definition_blueprint(card, dict(defn), _META)
    _assert_pair_equiv(S.PairedObligationV2("definition", bp, o, S.assemble_obligation_v2(bp, o)))


def test_exception_state_equivalence():
    """exception：triggered→not_applicable / not-triggered→satisfied / missing→open 分支等价。"""
    card = make_rule_card("rc.exc")
    exc = {"slot_id": "defect.excluded", "exception_kind": "exclusion", "qualifiers": {}}
    for facts, exp_cl, exp_sat in [
        ([make_fact("f", slot_id="defect.excluded", value=True, value_type="boolean")], "closed", "not_applicable"),
        ([make_fact("f", slot_id="defect.excluded", value=False, value_type="boolean")], "closed", "satisfied"),
        ([], "open", "unknown"),
    ]:
        fi = _index(facts)
        o = D.evaluate_exception(card, dict(exc), fi, _META)
        bp = B.build_exception_blueprint(card, dict(exc), _META)
        assert (o.closure_status, o.satisfaction_status) == (exp_cl, exp_sat)
        _assert_pair_equiv(S.PairedObligationV2("exception", bp, o, S.assemble_obligation_v2(bp, o)))


def test_prohibition_node_state_equivalence():
    """obligation_graph prohibition node：violated(禁止事实真) / satisfied(假) / open(缺) 分支等价。"""
    card = make_rule_card("rc.pn")
    node = {"obligation_node_id": "n01", "node_kind": "prohibition", "actor": "ri",
            "action": "unauthorized.work", "recipient_ids": [], "artifact_ids": [],
            "deadline_ids": [], "trigger_condition_ids": []}
    for facts, exp_sat in [
        ([make_fact("f", slot_id="unauthorized.work", value=True, value_type="boolean")], "violated"),
        ([make_fact("f", slot_id="unauthorized.work", value=False, value_type="boolean")], "satisfied"),
    ]:
        fi = _index(facts)
        node_out = D.evaluate_obligation_node(
            card, D.ObligationNodeDTO.from_dict(dict(node)), fi, True, _META)
        bp = B.build_obligation_node_blueprint(card, dict(node), _META)
        o0 = node_out[0]
        assert o0.closure_status == "closed" and o0.satisfaction_status == exp_sat
        _assert_pair_equiv(S.PairedObligationV2("obligation_graph", bp, o0, S.assemble_obligation_v2(bp, o0)))


def test_obligation_edge_state_equivalence_target_inactive():
    """obligation_graph edge：target 未激活 → escalation closed+not_applicable，按 edge_id 配对等价。"""
    # 两 prohibition node + 一 if_failed_then edge；source 无违反 → target 未激活 → NA audit。
    node1 = {"obligation_node_id": "n01", "node_kind": "prohibition", "actor": "ri",
             "action": "act.a", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
             "trigger_condition_ids": []}
    node2 = {"obligation_node_id": "n02", "node_kind": "prohibition", "actor": "ri",
             "action": "act.b", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
             "trigger_condition_ids": []}
    edge = {"source_node_id": "n01", "target_node_id": "n02", "relation": "if_failed_then"}
    card = make_rule_card("rc.edge", obligation_graph={"nodes": [node1, node2], "edges": [edge]})
    # source 事实为假（不违反）→ 不激活 target。
    fi = _index([make_fact("f", slot_id="act.a", value=False, value_type="boolean")])
    pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
    edge_pairs = [p for p in pairs if p.blueprint.identity.predicate_kind == "obligation_edge"]
    assert edge_pairs, "target 未激活应产 edge escalation NA audit 配对"
    for p in edge_pairs:
        assert p.v1_obligation.closure_status == "closed"
        assert p.v1_obligation.satisfaction_status == "not_applicable"
        _assert_pair_equiv(p)


# =========================================================================== #
# 2. 全 397 真语料逐义务状态等价（不一致清单应空 + 映射器全语料不炸）
# =========================================================================== #


def _find_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = (base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
                / "rule_cards.json")
        if cand.exists():
            return cand
    return None


def _load_cards_float() -> List[RuleCardDTO]:
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


def _load_cards_decimal() -> List[RuleCardDTO]:
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    return load_identity_cards(p)


def _real_corpus_pairs() -> List[S.PairedObligationV2]:
    """全 397 真卡经**统一 run 级入口**（消费阶段一已过闸 Decimal blueprint + float 卡 v1 evaluate）。

    identity 走 Decimal 读径（`derive_covered_blueprints_from_bundle`：float 阈值卡不断线 + run 级
    `RegimeSignatureRegistry` 跨卡签名闸 + 卡级全闸），judgement 走 float 卡（v1 生产读径：Decimal 卡
    不序列化失败）；按 (rule_card_id, channel, source_item_id) 关联（sid 数值无关，跨 Decimal/float
    稳定）。空事实索引 → 主产 open/blocked + 覆盖 obligation_graph node **与 edge**（edge 条件产出：
    真语料 4 edge → trigger 下游 1 条 inactive-target 义务）。守护映射器对全语料 operator/reason_code
    不触 ValidationError。
    """
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    fcards = _load_cards_float()
    return S.evaluate_covered_run_obligations_v2(p, fcards, _index([]), _META)


def test_real_corpus_per_obligation_state_equivalence_empty_list():
    """全 397 真语料逐覆盖义务（含 edge channel）：v2 状态 vs v1 verdict **逐条一致**（不一致清单应空）。"""
    fcards = _load_cards_float()
    assert len(fcards) == 397, f"真语料卡数应精确 397: {len(fcards)}"
    pairs = _real_corpus_pairs()
    # v4 精确 2310 = 1884 旧覆盖 + 400 普通/升级 node-main + 25 workflow_deadline + 1 edge
    # （inactive-target）。method 子义务未配对：7 method 卡皆有 card trigger、空事实 → trigger open →
    # node 提前返回、node_out 不含 method 子义务（§5.3 控制流）——故空事实门槛 method 分支不演（净集等价
    # 由带事实的 test_method_net_equivalence_finalize_not_pair_projection 专测，§3.4③）。**入口合一净 key
    # 总数 2306**（v1 dedupe 折 4 条同 key）见 test_entry_unification_v1_net_equals_v2_net_per_card_all_397。
    assert len(pairs) == 2310, (
        f"真派生配对数应精确 2310（v4：全 node + deadline + edge）: {len(pairs)}"
    )
    mismatches: List[str] = []
    for p in pairs:
        mm = _state_mismatches(p.v1_obligation, p.obligation_v2.state)
        if mm:
            mismatches.append(f"{p.channel}/{p.blueprint.canonical_identity_hash[:10]}: {mm}")
    assert not mismatches, (
        f"逐义务状态不一致 {len(mismatches)} 条（应空）:\n"
        + "\n".join(mismatches[:20])
    )
    # 覆盖度：多 channel + 多 closure_status（非空转）；v4 obligation_graph 全 node + workflow_deadline。
    channels = {p.channel for p in pairs}
    closures = {p.v1_obligation.closure_status for p in pairs}
    assert {
        "trigger", "slot_role", "threshold", "workflow_artifact", "workflow_deadline",
        "evidence", "definition", "obligation_graph",
    } <= channels
    assert "open" in closures  # 空索引主产 open
    # node **分 predicate_kind 计**（v4 全 node）：396 obligation + 4 escalation + 1 prohibition + 1 edge。
    pk_count: Dict[str, int] = {}
    for p in pairs:
        if p.channel == "obligation_graph":
            pk_count[p.blueprint.identity.predicate_kind] = (
                pk_count.get(p.blueprint.identity.predicate_kind, 0) + 1
            )
    assert pk_count.get("prohibition") == 1, f"prohibition node 配对应精确 1: {pk_count}"
    assert pk_count.get("obligation") == 396, f"普通 node 配对应精确 396: {pk_count}"
    assert pk_count.get("escalation") == 4, f"升级 node 配对应精确 4: {pk_count}"
    assert pk_count.get("obligation_edge") == 1, f"edge 义务配对应精确 1: {pk_count}"
    # workflow_deadline：25 卡各 1 独立 deadline 义务（node 携带 deadline 子不单独配对，§5.1）。
    deadline_pairs = [p for p in pairs if p.channel == "workflow_deadline"]
    assert len(deadline_pairs) == 25, f"workflow_deadline 配对应精确 25: {len(deadline_pairs)}"
    # edge channel 逐义务状态等价（精确 2310 内、0 mismatch）：edge 是 inactive-target closed+NA。
    edge_pairs = [p for p in pairs if p.blueprint.identity.predicate_kind == "obligation_edge"]
    for p in edge_pairs:
        assert p.v1_obligation.closure_status == "closed"
        assert p.v1_obligation.satisfaction_status == "not_applicable"
        assert not _state_mismatches(p.v1_obligation, p.obligation_v2.state)
    print(f"[corpus equiv] pairs={len(pairs)} channels={sorted(channels)} closures={sorted(closures)}")


def test_real_corpus_state_covers_closed_and_blocked_with_facts():
    """全语料补充：注入通用满足性事实令部分义务闭合/违反 → 覆盖 closed/satisfied/violated 分支等价。

    （空索引主产 open；本例给 artifact present/absent 事实令 workflow_artifact 闭合，
    确保 closed+satisfied 与 closed+violated 分支也进逐义务等价验证。）
    """
    fcards = _load_cards_float()
    dcards = _load_cards_decimal()
    # 所有已建模 artifact slot 置 present，令 workflow_artifact 闭合。
    facts = []
    for i, (k, slot) in enumerate(D.ARTIFACT_KEY_TO_SIDECAR_SLOT.items()):
        facts.append(make_fact(f"af{i}", slot_id=slot, value="present", carrier_type="sidecar_entry"))
    fi = _index(facts)
    seen_closed = seen_satisfied = 0
    mismatches: List[str] = []
    for fc, dc in zip(fcards, dcards):
        f_arts = (fc.workflow_operands or {}).get("artifacts", []) or []
        d_arts = (dc.workflow_operands or {}).get("artifacts", []) or []
        for fa, da in zip(f_arts, d_arts):
            if not isinstance(fa, dict):
                continue
            key = D._extract_artifact_key(fa)
            if not key:
                continue
            o = D.evaluate_artifact_obligation(
                fc, key, "artifact", fi, True, _META,
                artifact_id=fa.get("artifact_id"), bucket="workflow_operands.artifacts")
            bp = B.build_workflow_artifact_blueprint(dc, dict(da), _META)
            v2 = S.assemble_obligation_v2(bp, o)
            mm = _state_mismatches(o, v2.state)
            if mm:
                mismatches.append(f"{bp.canonical_identity_hash[:10]}: {mm}")
            if o.closure_status == "closed":
                seen_closed += 1
            if o.satisfaction_status == "satisfied":
                seen_satisfied += 1
    assert not mismatches, f"闭合分支状态不一致（应空）:\n" + "\n".join(mismatches[:20])
    assert seen_closed > 0 and seen_satisfied > 0, "未覆盖 closed/satisfied（事实注入无效）"


# =========================================================================== #
# 3. merge_states ≡ _merge_two（同输出态）
# =========================================================================== #

_CLOSURE_CASES = [
    ("closed", "satisfied", None, None),
    ("closed", "violated", None, None),
    ("closed", "not_applicable", None, None),
    ("open", "unknown", "missing_fact", None),
    ("open", "unknown", "missing_measurement", None),
    ("blocked", "unknown", None, "ambiguous_fact_binding"),
    ("blocked", "unknown", None, "unit_mismatch"),
]


def _mk_v1(cl: str, sat: str, orc: Optional[str], brc: Optional[str], **over) -> Obligation:
    base = dict(
        obligation_id="PENDING", run_id="r1", world_id="w1", building_id="b1",
        source_rule_card_id="rc.m", source_family_id="fam.m", kind="threshold",
        closure_status=cl, satisfaction_status=sat,
        open_reason_code=orc, blocked_reason_code=brc,
    )
    base.update(over)
    return Obligation(**base)


# 完整 state 逐字段等价投影（含 reason_code；merge 等价须逐字段，非只 closure/satisfaction）。
_MERGE_STATE_FIELDS = (
    "closure_status",
    "satisfaction_status",
    "open_reason_code",
    "blocked_reason_code",
)
def _full_state(s: I.ObligationStateV2) -> tuple:
    return tuple(getattr(s, f) for f in _MERGE_STATE_FIELDS)


def _v1_reason_literals(field: str) -> set:
    """v1 `Obligation.<field>` 可构造的 reason Literal 集（剔 Optional 的 None）。"""
    import typing
    inner = typing.get_args(Obligation.model_fields[field].annotation)[0]  # 剥 Optional
    return set(typing.get_args(inner))


# 全 reason 序表 merge cases：3 closed + **v1-可构造** open/blocked reason 全码（旧 `_CLOSURE_CASES`
# 只含每 closure 2 码，故旧测误得「恰 2 对」；此处跨完整序表暴露一般发散）。
_V1_OPEN_REASONS = _v1_reason_literals("open_reason_code")
_V1_BLOCKED_REASONS = _v1_reason_literals("blocked_reason_code")
_OPEN_REASON_CODES = [c for c in I.OPEN_REASON_ORDER if c in _V1_OPEN_REASONS]
_BLOCKED_REASON_CODES = [c for c in I.BLOCKED_REASON_ORDER if c in _V1_BLOCKED_REASONS]
_FULL_MERGE_CASES = (
    [("closed", "satisfied", None, None),
     ("closed", "violated", None, None),
     ("closed", "not_applicable", None, None)]
    + [("open", "unknown", c, None) for c in _OPEN_REASON_CODES]
    + [("blocked", "unknown", None, c) for c in _BLOCKED_REASON_CODES]
)


def _tier_of(code: str, closure: str) -> Optional[str]:
    """activate `find_high_risk_items` 实测某 reason 的 advisory 高风险 tier（None=不入表）。"""
    o = _mk_v1(closure, "unknown",
               code if closure == "open" else None,
               code if closure == "blocked" else None)
    items = find_high_risk_items([o.model_copy(update={"obligation_id": "X"})])
    return items[0]["severity"] if items else None


def test_merge_projection_byte_equiv_over_full_reason_tables():
    """判定投影（closure_status + satisfaction_status = allow_stop 地基）在**生产 `_merge_two` 真语义**
    下、跨**全 v1-可构造 reason 序表** cross-product 逐组**字节等价**（0 mismatch）。

    **不用改序 helper**——直接 RAW `_merge_two`（order-dependent）比对 `merge_states`
    （order-independent，committed 契约）。旧测只跑 7-case（每 closure 2 reason），此处跨完整序表
    （24 case = 3 closed + 8 open + 13 blocked，576 组）仍 0 投影漂移 → allow_stop 地基等价。
    """
    proj_mismatch: List[str] = []
    for a in _FULL_MERGE_CASES:
        for b in _FULL_MERGE_CASES:
            oa, ob = _mk_v1(*a), _mk_v1(*b)
            v1 = _merge_two(oa, ob)  # 生产真语义（RAW，无改序）
            v2 = I.merge_states(
                [S.obligation_to_state_v2(oa), S.obligation_to_state_v2(ob)]
            )
            if (v1.closure_status, v1.satisfaction_status) != (
                v2.closure_status, v2.satisfaction_status
            ):
                proj_mismatch.append(
                    f"{a[:1]+a[2:]}+{b[:1]+b[2:]}: "
                    f"v1={(v1.closure_status, v1.satisfaction_status)} "
                    f"v2={(v2.closure_status, v2.satisfaction_status)}"
                )
    assert not proj_mismatch, (
        "判定投影（closure+satisfaction）在生产 _merge_two 真语义下不一致（应空）:\n"
        + "\n".join(proj_mismatch[:20])
    )


def test_merge_reason_selection_diverges_in_general_not_two_pairs():
    """**修 overclaim**：merge_states vs _merge_two 的 reason 选择在合并**异 reason** 时**一般发散**
    （非旧登记『恰 2 对保守漂移』）——诚实登记核对活代码。

    跨全 v1-可构造 reason 序表实测 reason 方向发散：
      - 总数 == `PHASE_TWO_REASON_DRIFT["measured_directional_divergences"]`（106；28 open + 78 blocked）；
      - 旧「2 对」是其**真子集**（⊊，非全部）——直接证「恰 2 对」双重失真；
      - **25 处 advisory tier 非保守**（merge_states 选更低 tier）——证「保守」亦失真，反例
        `missing_required_field_group`[medium] → `depends_on_open_trigger`[low]。
    """
    reason_drift: set = set()      # {(closure, v1_reason, v2_reason)}
    open_cnt = blocked_cnt = 0
    nonconservative: List[tuple] = []
    _rank = {"high": 3, "medium": 2, "low": 1, None: 0}
    # 只在**同 closure 异 reason** 合并上量 reason 发散（跨 closure 的 reason 由投影字段决定、另测）。
    for closure, codes, field in (
        ("open", _OPEN_REASON_CODES, "open_reason_code"),
        ("blocked", _BLOCKED_REASON_CODES, "blocked_reason_code"),
    ):
        for ca in codes:
            for cb in codes:
                if ca == cb:
                    continue
                oa = _mk_v1(closure, "unknown",
                            ca if closure == "open" else None,
                            ca if closure == "blocked" else None)
                ob = _mk_v1(closure, "unknown",
                            cb if closure == "open" else None,
                            cb if closure == "blocked" else None)
                v1 = _merge_two(oa, ob)  # order-dependent → primary=a
                v2 = I.merge_states(
                    [S.obligation_to_state_v2(oa), S.obligation_to_state_v2(ob)]
                )
                v1r, v2r = getattr(v1, field), getattr(v2, field)
                if v1r != v2r:
                    reason_drift.add((closure, v1r, v2r))
                    if closure == "open":
                        open_cnt += 1
                    else:
                        blocked_cnt += 1
                    if _rank[_tier_of(v2r, closure)] < _rank[_tier_of(v1r, closure)]:
                        nonconservative.append((closure, v1r, v2r))

    spec = S.PHASE_TWO_REASON_DRIFT
    # ① 一般发散：总数与登记一致（活代码核对，防回退 overclaim）。
    assert len(reason_drift) == spec["measured_directional_divergences"] == 106, (
        f"reason 方向发散实测={len(reason_drift)} 登记={spec['measured_directional_divergences']}"
    )
    assert open_cnt == spec["measured_open_divergences"] == 28
    assert blocked_cnt == spec["measured_blocked_divergences"] == 78
    # ② 旧「2 对」是真子集（⊊）——直接证「恰 2 对」失真（远非全部）。
    legacy = set(spec["legacy_overclaim_pairs"])
    assert legacy < reason_drift, "旧 2 对应是发散的真子集（⊊），证『恰 2 对』overclaim 失真"
    assert len(reason_drift) > 2
    # ③ 「保守」亦失真：25 处 advisory tier 非保守（含 medium→low 反例）。
    assert len(nonconservative) == spec["measured_nonconservative_tier"] == 25
    assert ("open", "missing_required_field_group", "depends_on_open_trigger") in set(
        nonconservative
    ), "应含 medium→low 非保守反例"


def test_real_corpus_finalize_groups_all_singleton_does_not_prove_unreachability():
    """**事实快照（诚实化，blocker 2）**：真语料 397 卡经统一 run 级入口 → 按 finalize 分组键
    `(scope, canonical_identity_hash)` 分组，实测**当前语料 2310 组全 singleton**（max_group_size==1）。

    **此为事实快照、非不可达证明**（旧测把 singleton 空转误当「生产不可达」，overclaim 已删）：当前
    语料无多成员组 ⟹ 真语料**不演任何真实 merge** ⟹ 验不了任何跨 reason 合并。identity **不含 FactIndex
    快照**，故「同 identity ⟹ 同事实 ⟹ 同 reason」**不成立**——多快照异 reason 合并**可达**（见姊妹测试
    `test_multisnapshot_same_identity_advisory_reason_drift_reachable`）。本测试只诚实记录「当前语料无
    多成员组」，**不**据此声称漂移不可达。
    """
    pairs = _real_corpus_pairs()
    members: Dict[tuple, List[tuple]] = {}
    for pr in pairs:
        o = pr.obligation_v2
        key = (o.run_envelope.run_id, o.run_envelope.world_id,
               o.run_envelope.building_id, o.canonical_identity_hash)
        members.setdefault(key, []).append(
            (o.state.open_reason_code, o.state.blocked_reason_code)
        )
    max_size = max(len(v) for v in members.values())
    multi = sum(1 for v in members.values() if len(v) > 1)
    # 事实快照：当前语料全 singleton（不演真实 merge），**不**作不可达证明。
    assert max_size == 1, f"当前语料应全 singleton（事实快照）: max_group_size={max_size}"
    assert multi == 0
    assert len(members) == len(pairs) == 2310
    # 诚实登记与活代码一致：漂移**可达**、仅落 advisory 层（非旧「生产不可达」）。
    assert S.PHASE_TWO_REASON_DRIFT["reachability"] == "reachable_advisory_only"
    assert S.PHASE_TWO_REASON_DRIFT["nature"] == "general_divergence_reachable_advisory_only"
    assert "production_reachability" not in S.PHASE_TWO_REASON_DRIFT  # 旧「不可达」键已删
    print(
        f"[corpus singleton fact] pairs={len(pairs)} groups={len(members)} "
        f"max_group_size={max_size} multi_member_groups={multi} "
        f"(事实快照，不证不可达)"
    )


def test_multisnapshot_same_identity_advisory_reason_drift_reachable():
    """**blocker 2 核心：多快照同身份异 reason 合并可达 = 登记的 advisory 层漂移（非生产不可达）**。

    codex 反例（活代码，非合成 state 注入）：同一 evidence blueprint（同 run/scope/identity），两个
    **合法 FactIndex 快照**分别产异 reason——
      · 快照 B（field group 在、measure 缺）→ v1 `missing_measurement`（open, obs=None）；
      · 快照 A（field group 缺）→ v1 `missing_required_field_group`（open, obs=None）。
    两者 closure=open、`merged_observation_bottom=()`（无 ⊥）、同 canonical_identity_hash。送生产合并入口
    `finalize_obligations_v2`：
      ① 合并**成功**（此为已知 advisory 漂移，**非** hard-fail）；
      ② merged closure_status/satisfaction 与 v1 `_merge_two` **逐字段等价**（判定投影不漂 = allow_stop
         地基稳）；
      ③ reason 落 v2 `merge_states` **max-by-rank**（`missing_required_field_group` rank5 >
         `missing_measurement` rank2）、与 v1 order-dependent primary（=首参 `missing_measurement`）
         **不同** → **显式断言这就是登记的 advisory 层 reason 漂移**（reason_code/高风险 tier 只影响报告
         排序与人工复核提示，不入 allow_stop 公式）。

    此测试直证「生产不可达」为伪：identity 不含事实快照，同 (scope,identity) 可来自异快照产异 reason，
    且经公开 finalize 入口可达。
    """
    card = make_rule_card(
        "rc.snap",
        slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="repair.required")],
    )
    # 同一 evidence requirement：field group + measure 双通道 → 依快照产异 reason（同一蓝图身份）。
    req = _evidence(
        evidence_requirement_id="ev.snap",
        required_field_groups=["grp.x"],
        measure_keys=["measure.crack_width"],
    )
    bp = B.build_evidence_blueprint(card, "for_matching", dict(req), _META)

    # 快照 B（首参）：field group 在、measure 缺 → missing_measurement。
    fi_b = _index([make_fact("fg", slot_id="qual.artifact_field_group",
                             value="grp.x", value_type="string")])
    o_b = D.evaluate_evidence_requirement(card, "for_matching", dict(req), fi_b, True, _META)
    # 快照 A（次参）：field group 缺（给无关 measure 事实）→ missing_required_field_group。
    fi_a = _index([make_fact("m", measure_key="measure.crack_width", value=5, value_type="number")])
    o_a = D.evaluate_evidence_requirement(card, "for_matching", dict(req), fi_a, True, _META)

    assert (o_b.closure_status, o_b.open_reason_code) == ("open", "missing_measurement")
    assert (o_a.closure_status, o_a.open_reason_code) == ("open", "missing_required_field_group")
    assert o_b.observed_value_json is None and o_a.observed_value_json is None  # 无 ⊥

    v2_b = S.assemble_obligation_v2(bp, o_b)
    v2_a = S.assemble_obligation_v2(bp, o_a)
    assert v2_b.canonical_identity_hash == v2_a.canonical_identity_hash  # 同 (scope, identity)

    # ① 合并成功（非 hard-fail）——多快照异 reason 成员合并**可达**、是已知 advisory 漂移。
    fin = S.finalize_obligations_v2([v2_b, v2_a])
    assert len(fin) == 1
    merged = fin[0].state

    # ② 判定投影（closure + satisfaction）与生产 v1 `_merge_two` **逐字段等价**（allow_stop 地基不漂）。
    v1 = _merge_two(o_b, o_a)  # 同序：order-dependent primary=首参 o_b
    assert (merged.closure_status, merged.satisfaction_status) == (
        v1.closure_status, v1.satisfaction_status) == ("open", "unknown")

    # ③ reason 落 v2 max-by-rank、与 v1 primary **不同** → 显式登记的 advisory 层漂移。
    assert v1.open_reason_code == "missing_measurement"                # v1 order-dependent primary
    assert merged.open_reason_code == "missing_required_field_group"   # v2 max-by-rank (5 > 2)
    assert merged.open_reason_code != v1.open_reason_code, (
        "登记的 advisory 层 reason 漂移（多快照异 reason 合并可达，非生产不可达）"
    )
    # advisory 漂移不入 allow_stop：reason 不同但同为 open（open 计数不变）→ allow_stop 不受影响。
    assert S.PHASE_TWO_REASON_DRIFT["reason_code_enters_allow_stop"] is False
    # 判定投影等价**限定**在无观测冲突合并（codex 终审 019f69f8：B4 观测冲突场景会改判定投影
    # 与 allow_stop、严格更保守——独立登记 PHASE_TWO_B4_OBSERVATION_CONFLICT，非全局无条件 True）。
    assert (
        S.PHASE_TWO_REASON_DRIFT["judgement_projection_byte_equiv"]
        == "true_iff_no_observation_conflict"
    )
    assert S.PHASE_TWO_REASON_DRIFT["reachability"] == "reachable_advisory_only"
    # B4 独立已知差异登记：可达、严格更保守、会改判定投影与 allow_stop（绝不放松停机）。
    assert S.PHASE_TWO_B4_OBSERVATION_CONFLICT["reachable"] is True
    assert S.PHASE_TWO_B4_OBSERVATION_CONFLICT["changes_judgement_projection"] is True
    assert S.PHASE_TWO_B4_OBSERVATION_CONFLICT["changes_allow_stop"] is True
    assert (
        S.PHASE_TWO_B4_OBSERVATION_CONFLICT["direction"] == "strictly_more_conservative"
    )
    print(
        f"[multisnapshot advisory drift] v1_reason={v1.open_reason_code} "
        f"v2_reason={merged.open_reason_code} closure/sat=(open,unknown) 等价; reason 漂移=advisory"
    )


def test_true_duplicate_merge_preserves_reason():
    """真重复合并保 reason（生产合并语义，对照 merge_states 一般发散仅在**异 reason** 时出现）：

    同蓝图身份 + **同事实** 两次求值 → 同 v1 verdict = 同 reason → finalize 合并成 1 条、reason 不漂。
    （此路对照多快照异 reason 合并：同事实 ⟹ 同 reason 不漂；异快照可产异 reason，见姊妹测试
    `test_multisnapshot_same_identity_advisory_reason_drift_reachable`——「同 identity ⟹ 同事实」不成立。）
    """
    card = make_rule_card("rc.dupreason", threshold_regimes=[_th(threshold_regime_id="rc.dupreason.t01")])
    th = _th(threshold_regime_id="rc.dupreason.t01")
    bp = B.build_threshold_blueprint(card, dict(th), _META)
    o1 = D.evaluate_threshold(card, dict(th), _index([]), True, _META)
    o2 = D.evaluate_threshold(card, dict(th), _index([]), True, _META)
    assert o1.open_reason_code == o2.open_reason_code is not None  # 同事实 ⟹ 同 reason
    v2s = [S.assemble_obligation_v2(bp, o1), S.assemble_obligation_v2(bp, o2)]
    assert v2s[0].canonical_identity_hash == v2s[1].canonical_identity_hash  # 同身份
    fin = S.finalize_obligations_v2(v2s)
    assert len(fin) == 1  # 真重复合并成一条
    assert fin[0].state.open_reason_code == o1.open_reason_code  # reason 保持、不漂


def test_merge_states_equiv_symmetry_and_idempotent():
    """merge 交换律（closure+satisfaction 任意序）+ **完整 state 幂等** merge(a,a)==a（v1/v2 同）。"""
    for a in _CLOSURE_CASES:
        # 幂等：**完整 state** merge(a,a)==a（v1 & v2 逐字段等于 a 本身，非只 closure/satisfaction）。
        oa = _mk_v1(*a)
        sa = S.obligation_to_state_v2(oa)
        v1_aa = _merge_two(oa, oa)
        v2_aa = I.merge_states([sa, sa])
        for f in _MERGE_STATE_FIELDS:
            assert getattr(v1_aa, f) == getattr(sa, f), f"v1 merge(a,a) 非幂等 {f}: {a}"
            assert getattr(v2_aa, f) == getattr(sa, f), f"v2 merge(a,a) 非幂等 {f}: {a}"
        for b in _CLOSURE_CASES:
            ob = _mk_v1(*b)
            m_ab = _merge_two(oa, ob)
            m_ba = _merge_two(ob, oa)
            assert (m_ab.closure_status, m_ab.satisfaction_status) == (
                m_ba.closure_status, m_ba.satisfaction_status)
            sb = S.obligation_to_state_v2(ob)
            # v2 完整 state 交换（含 reason_code；max-by-rank order-independent）。
            assert _full_state(I.merge_states([sa, sb])) == _full_state(
                I.merge_states([sb, sa])
            )


def test_merge_states_observation_bottom_is_strictly_more_conservative():
    """v2 B4 ⊥→blocked 是**严格更保守**附加闸（v1 无）：观测冲突 → v2 blocked（¬allow_stop 方向）。

    同 closure=closed 两义务观测值分歧：v1 _merge_two 取 primary 观测保 closed；v2 merge_states
    落 ⊥ → blocked。方向与零漂移一致（v2 更保守，绝不比 v1 更松）；本单元不接活路径故不影响
    v1 allow_stop。
    """
    a = S.obligation_to_state_v2(_mk_v1("closed", "satisfied", None, None, observed_value_json="1"))
    b = S.obligation_to_state_v2(_mk_v1("closed", "satisfied", None, None, observed_value_json="2"))
    m = I.merge_states([a, b])
    assert m.closure_status == "blocked" and m.blocked_reason_code == "ambiguous_merged_observation"
    # v1 对应：取 primary 保 closed（证明这是 v2 附加保守，非 v1 语义漂移）
    v1_m = _merge_two(
        _mk_v1("closed", "satisfied", None, None, observed_value_json="1"),
        _mk_v1("closed", "satisfied", None, None, observed_value_json="2"),
    )
    assert v1_m.closure_status == "closed"


# =========================================================================== #
# 4. 组装 + 去重 + 碰撞后置
# =========================================================================== #


def test_finalize_dedupes_same_identity_and_merges_state():
    """finalize：同身份多条（同蓝图身份、异状态）→ 合并成一条 + merge_states 保守取值 + 碰撞后置通过。

    同一 threshold 源项冻结同一蓝图身份；两次求值 open(空索引=missing_measurement) / blocked(单位
    不符=unit_mismatch)——两者观测值均 None（无 ⊥）。finalize 分组合并：closure 保守序
    blocked>open>closed → blocked 胜。
    """
    card = make_rule_card("rc.dd", threshold_regimes=[_th(threshold_regime_id="rc.dd.t01")])
    th = _th(threshold_regime_id="rc.dd.t01")  # unit=mm
    bp = B.build_threshold_blueprint(card, dict(th), _META)
    o_open = D.evaluate_threshold(card, dict(th), _index([]), True, _META)  # open+missing_measurement
    o_blocked = D.evaluate_threshold(
        card, dict(th),
        _index([make_fact("f", measure_key="measure.crack_width", value=5, value_type="number", unit="cm")]),
        True, _META,
    )  # blocked+unit_mismatch（观测在单位闸前早退 → observed=None，与 o_open 一致，无 ⊥）
    assert o_open.closure_status == "open" and o_blocked.closure_status == "blocked"
    assert o_open.observed_value_json is None and o_blocked.observed_value_json is None
    v2s = [S.assemble_obligation_v2(bp, o_open), S.assemble_obligation_v2(bp, o_blocked)]
    assert v2s[0].canonical_identity_hash == v2s[1].canonical_identity_hash  # 同身份
    fin = S.finalize_obligations_v2(v2s)
    assert len(fin) == 1  # 合并成一条
    assert fin[0].state.closure_status == "blocked"  # 保守序：blocked > open
    # 再跑一次 postcheck（发布前挂点已内置，重复调用应通过）
    I.run_collision_postcheck(fin)


def test_finalize_cross_building_no_collision():
    """finalize：同身份跨楼 → obligation_id 不撞、各自成条（N1）。"""
    card = make_rule_card("rc.xb", threshold_regimes=[_th(threshold_regime_id="rc.xb.t01")])
    th = _th(threshold_regime_id="rc.xb.t01")
    obs = []
    for bld in ("BLD-A", "BLD-B"):
        meta = {**_META, "building_id": bld}
        o = D.evaluate_threshold(card, dict(th), _index([]), True, meta)
        bp = B.build_threshold_blueprint(card, dict(th), meta)
        obs.append(S.assemble_obligation_v2(bp, o))
    fin = S.finalize_obligations_v2(obs)
    assert len(fin) == 2
    assert fin[0].obligation_id != fin[1].obligation_id
    assert fin[0].canonical_identity_hash == fin[1].canonical_identity_hash


def test_assemble_scope_mismatch_hard_fails():
    """组装：蓝图 scope ≠ v1 义务 scope（误配对）→ hard-fail（不静默）。"""
    card = make_rule_card("rc.mis", threshold_regimes=[_th(threshold_regime_id="rc.mis.t01")])
    th = _th(threshold_regime_id="rc.mis.t01")
    o = D.evaluate_threshold(card, dict(th), _index([]), True, {**_META, "building_id": "BLD-X"})
    bp = B.build_threshold_blueprint(card, dict(th), {**_META, "building_id": "BLD-Y"})
    with pytest.raises(I.ObligationContractError, match="blueprint_obligation_scope_mismatch"):
        S.assemble_obligation_v2(bp, o)


def test_obligation_v2_identity_frozen_from_blueprint():
    """组装：ObligationV2 身份/immutable/hash 全取自蓝图（阶段一冻结），state 来自 v1。"""
    card = make_rule_card("rc.fz", threshold_regimes=[_th(threshold_regime_id="rc.fz.t01")])
    th = _th(threshold_regime_id="rc.fz.t01")
    o = D.evaluate_threshold(card, dict(th), _index([]), True, _META)
    bp = B.build_threshold_blueprint(card, dict(th), _META)
    v2 = S.assemble_obligation_v2(bp, o)
    assert v2.identity == bp.identity
    assert v2.immutable == bp.immutable
    assert v2.canonical_identity_hash == bp.canonical_identity_hash
    assert v2.obligation_identity_schema == I.IDENTITY_SCHEMA
    # source_operator audit（ObligationV2 model_validator）通过
    assert v2.immutable.source_operator == v2.identity.source_predicate_spec.source_operator


# =========================================================================== #
# 5. 卡级驱动 + trigger 聚合控制流
# =========================================================================== #


def test_driver_trigger_false_skips_downstream():
    """驱动忠实 v1 控制流：trigger 聚合 False → 只产 trigger 配对、跳过下游（无 downstream 状态）。"""
    # trigger 期望 True 但事实 False → trigger closed+not_applicable → aggregate(all)=False
    card = make_rule_card(
        "rc.tf",
        slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="defect.present")],
        trigger_conditions={"logic": "all", "items": [_trigger(condition_id="c1", slot_ref_id="sr1",
                                                               operator="==", expected_value=True)]},
        threshold_regimes=[_th(threshold_regime_id="rc.tf.t01")],
    )
    fi = _index([make_fact("f", slot_id="defect.present", value=False, value_type="boolean")])
    pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
    channels = {p.channel for p in pairs}
    assert channels == {"trigger"}, f"trigger False 应跳过下游，仅剩 trigger: {channels}"
    for p in pairs:
        _assert_pair_equiv(p)


def test_driver_trigger_true_evaluates_downstream():
    """驱动：trigger 聚合 True → 下游 slot_role/threshold 均求值配对且状态等价。"""
    card = make_rule_card(
        "rc.tt",
        slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="defect.present")],
        trigger_conditions={"logic": "all", "items": [_trigger(condition_id="c1", slot_ref_id="sr1",
                                                               operator="==", expected_value=True)]},
        threshold_regimes=[_th(threshold_regime_id="rc.tt.t01")],
    )
    fi = _index([make_fact("f", slot_id="defect.present", value=True, value_type="boolean")])
    pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
    channels = {p.channel for p in pairs}
    assert {"trigger", "slot_role", "threshold"} <= channels
    for p in pairs:
        _assert_pair_equiv(p)
    # 便捷入口产 finalize 后的 ObligationV2 列表
    finals = S.evaluate_covered_card_v2(card, fi, _META)
    assert finals and all(isinstance(o, I.ObligationV2) for o in finals)
    I.run_collision_postcheck(finals)


def test_driver_reuses_v1_evaluate_verbatim():
    """驱动**逐字复用** v1 evaluate_*：驱动内 v1 义务 == 外部直调 evaluate_X（同参数）byte-identical。"""
    card = make_rule_card(
        "rc.rw",
        slot_role_map=[_slot_role(slot_ref_id="sr1", slot_id="repair.required")],
        threshold_regimes=[_th(threshold_regime_id="rc.rw.t01")],
    )
    fi = _index([make_fact("f", slot_id="repair.required", value=True, value_type="boolean")])
    pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
    for p in pairs:
        if p.channel == "slot_role":
            direct = D.evaluate_slot_role(card, _slot_role(slot_ref_id="sr1", slot_id="repair.required"),
                                          fi, True, _META)
            assert p.v1_obligation.model_dump() == direct.model_dump()
        if p.channel == "threshold":
            direct = D.evaluate_threshold(card, _th(threshold_regime_id="rc.rw.t01"), fi, True, _META)
            assert p.v1_obligation.model_dump() == direct.model_dump()


# =========================================================================== #
# 5b. 核心架构：阶段二消费阶段一已过闸 blueprint（继承闸，不重建绕过）—— blocker 1&2
# =========================================================================== #


def test_phase_two_inherits_duplicate_regime_gate():
    """阶段二对**重复 threshold_regime_id** 卡继承阶段一闸 → hard-fail（不再 registry=None 重建绕过）。

    同卡两 threshold 同 regime_id → 同 source_item_id → 阶段一 `CardBindingRegistry.record_source_item`
    `duplicate_source_item:threshold` hard-fail；阶段二经 `derive_covered_card_blueprints` 取 blueprint
    时即继承此 hard-fail（旧 registry=None 逐项重建则静默接受）。
    """
    card = make_rule_card(
        "rc.dupreg",
        threshold_regimes=[_th(threshold_regime_id="SAME", value=7),
                           _th(threshold_regime_id="SAME", value=9)],
    )
    with pytest.raises(I.ObligationContractError, match="duplicate_source_item"):
        S.evaluate_covered_card_obligations_v2(card, _index([]), _META)


def test_phase_two_inherits_empty_applicability_gate():
    """阶段二对**空 applicability** 卡继承阶段一 fail-closed → hard-fail（旧阶段二从不建 applicability 蓝图）。

    空 `applicability={}` → 阶段一 `build_applicability_blueprint` 内 `ApplicabilityDTO.model_validate({})`
    缺 7 必填字段 → pydantic ValidationError；阶段二经 `derive_covered_card_blueprints` 继承此 hard-fail。
    """
    card = make_rule_card("rc.emptyap", applicability={})
    with pytest.raises(ValidationError, match="ApplicabilityDTO"):
        S.evaluate_covered_card_obligations_v2(card, _index([]), _META)


def test_phase_two_external_blueprint_raw_node_kind_gate_hard_fails():
    """**blocker 3 负测**：阶段二**外供 blueprint** 入口（`blueprints=`）绕过 `derive_covered_card_blueprints`
    内的 raw-kind 闸——补守。合法 blueprint 集 + raw `node_kind=brand_new` 的 float card → node 消费路径
    在 `from_dict` 归一**之前** `_assert_known_node_kind` hard-fail `unknown_node_kind`（否则 brand_new 被
    `from_dict` 归一 obligation 静默接受，母病断根被绕过）。

    合法卡与 brand 卡**结构相同**（仅 node_kind 异）→ 双读径清单 SID 一致（node SID 用 node_id 非 node_kind、
    brand_new refine→action 非 method 无 method SID）→ `_assert_card_read_path_consistency` 先过，随后由
    node 循环 raw-kind 闸拦（证补守生效、非 consistency 误报）。"""
    valid_node = {"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
                  "action": "conduct_x", "recipient_ids": [], "artifact_ids": [],
                  "deadline_ids": [], "trigger_condition_ids": []}
    valid_card = make_rule_card("rc.b3ext", obligation_graph={"nodes": [valid_node], "edges": []})
    bps = B.derive_covered_card_blueprints(valid_card, _META)  # 合法过闸 blueprint 集
    # 结构相同、仅 node_kind=brand_new 的 float card（float 语义卡，非 Decimal）
    brand_node = dict(valid_node, node_kind="brand_new_kind")
    brand_card = make_rule_card("rc.b3ext", obligation_graph={"nodes": [brand_node], "edges": []})
    # 外供合法 blueprint（旧路径绕闸）→ 补守后 node 消费路径 raw-kind 闸 hard-fail
    with pytest.raises(I.ObligationContractError, match="unknown_node_kind"):
        S.evaluate_covered_card_obligations_v2(brand_card, _index([]), _META, blueprints=bps)
    # 对照：不传 blueprints=（走 derive 内闸）亦 hard-fail（既有闸，未绕过）
    with pytest.raises(I.ObligationContractError, match="unknown_node_kind"):
        S.evaluate_covered_card_obligations_v2(brand_card, _index([]), _META)


def test_phase_two_unified_entry_all_397_no_serialization_or_rejection():
    """全 397 卡（Decimal identity + float evaluate）经**统一 run 级入口**：无序列化失败/无 strict 拒。

    统一入口 `evaluate_covered_run_obligations_v2` 内部：identity 走 Decimal 读径
    （`derive_covered_blueprints_from_bundle`，13 float 阈值卡不断线）、judgement 走 float 卡
    （v1 生产读径，5 Decimal 卡不序列化失败）。全 2310 pair assemble 成功；finalize（去重+碰撞
    后置）全集无 hard-fail —— 证明「同一卡同时送 v1 求值与 Decimal-only builder」的旧断线已根治。
    """
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    fcards = _load_cards_float()
    assert len(fcards) == 397
    pairs = S.evaluate_covered_run_obligations_v2(p, fcards, _index([]), _META)
    assert len(pairs) == 2310
    assert all(isinstance(pr.obligation_v2, I.ObligationV2) for pr in pairs)
    # Decimal identity 与 float judgement 混——全 assemble 无序列化异常（源自 identity bytes 计算）。
    finals = S.finalize_obligations_v2([pr.obligation_v2 for pr in pairs])
    assert len(finals) == 2310  # 跨卡身份唯一，无 dedupe 逃逸
    I.run_collision_postcheck(finals)


# =========================================================================== #
# 5c. blocker 5：碰撞后置——真 hash collision 折叠【前】 hard-fail（非被 merge 擦除）
# =========================================================================== #


def test_collision_same_hash_diff_identity_hard_fails_before_merge():
    """`[合法, 非法同 hash]`（同 canonical_identity_hash 异 identity = 真 collision）→ finalize 折叠**前**
    hard-fail，非被 `merge_obligations` 擦除第二身份后 postcheck 静默通过。

    旧序（先按 hash 合并再 postcheck）：merge 取 first.identity、擦除非法第二身份 → postcheck 只见
    merged 单条、recompute 自洽 → 静默通过（第二身份丢失、检不出）。修法在折叠**前**按 canonical
    identity bytes 验单射 → 同 hash 异 identity 折叠前即 `identity_hash_collision_pre_merge` hard-fail。
    """
    card1 = make_rule_card("rc.k1", threshold_regimes=[_th(threshold_regime_id="rc.k1.t01")])
    card2 = make_rule_card("rc.k2", threshold_regimes=[_th(threshold_regime_id="rc.k2.t01")])
    th1 = _th(threshold_regime_id="rc.k1.t01")
    th2 = _th(threshold_regime_id="rc.k2.t01")
    o1 = D.evaluate_threshold(card1, dict(th1), _index([]), True, _META)
    o2 = D.evaluate_threshold(card2, dict(th2), _index([]), True, _META)
    bp1 = B.build_threshold_blueprint(card1, dict(th1), _META)
    bp2 = B.build_threshold_blueprint(card2, dict(th2), _META)
    v_legal = S.assemble_obligation_v2(bp1, o1)
    v_other = S.assemble_obligation_v2(bp2, o2)
    assert v_legal.canonical_identity_hash != v_other.canonical_identity_hash  # 真身份不同
    # 伪造 collision：identity 保留 card2 的（异 identity），canonical_identity_hash 篡改为 card1 的。
    forged = v_other.model_copy(
        update={"canonical_identity_hash": v_legal.canonical_identity_hash}
    )
    with pytest.raises(I.ObligationContractError, match="identity_hash_collision_pre_merge"):
        S.finalize_obligations_v2([v_legal, forged])
    # 对照：同身份合法去重仍折叠成一条（不误伤）。
    o1b = D.evaluate_threshold(card1, dict(th1), _index([]), True, _META)
    v_legal_dup = S.assemble_obligation_v2(bp1, o1b)
    assert len(S.finalize_obligations_v2([v_legal, v_legal_dup])) == 1


# =========================================================================== #
# 5d. blocker 1：双读径关联**先双向校验再配对**（各反例 hard-fail，证双向非单向）
# =========================================================================== #


def _load_raw_cards() -> List[Dict[str, Any]]:
    """真语料 rule_cards.json 的原始 dict 列表（供构造双读径反例：改 float 侧不改 blueprint 侧）。"""
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    return json.loads(p.read_text(encoding="utf-8"))["cards"]


def _mk_float(cards_raw: List[Dict[str, Any]]) -> List[RuleCardDTO]:
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in cards_raw]


def _run_dual(fcards: List[RuleCardDTO]):
    """跑统一 run 级入口：blueprint 侧恒取真 bundle（不受 float 侧篡改影响）。"""
    return S.evaluate_covered_run_obligations_v2(_find_bundle(), fcards, _index([]), _META)


def _first_threshold_card_idx(raw: List[Dict[str, Any]]) -> int:
    return next(i for i, c in enumerate(raw) if c.get("threshold_regimes"))


def test_dual_read_path_fewer_float_cards_hard_fails():
    """**少** float 卡（blueprint 侧多一卡）→ `read_path_card_set_mismatch`（blueprint_only 非空）。

    旧单向 `by_card.get(...,[])`：漏的卡其 blueprint 被静默吞、pairs 少几条不炸（1885→1881）。
    """
    raw = _load_raw_cards()
    with pytest.raises(I.ObligationContractError, match="read_path_card_set_mismatch") as ei:
        _run_dual(_mk_float(raw[:-1]))
    assert "blueprint_only=[" in str(ei.value)


def test_dual_read_path_extra_float_card_hard_fails():
    """**多** float 卡（float 侧多一卡，blueprint 侧无）→ `read_path_card_set_mismatch`（float_only 非空）。"""
    raw = _load_raw_cards()
    extra = copy.deepcopy(raw[0])
    extra["rule_card_id"] = "SYNTH.NOT.IN.BUNDLE"
    with pytest.raises(I.ObligationContractError, match="read_path_card_set_mismatch") as ei:
        _run_dual(_mk_float(raw + [extra]))
    assert "float_only=['SYNTH.NOT.IN.BUNDLE']" in str(ei.value)


def test_dual_read_path_duplicate_float_card_hard_fails():
    """**重复** float 卡 → `duplicate_float_card`（旧单向：同卡评两次，pairs 翻倍不炸 1885→1895）。"""
    raw = _load_raw_cards()
    with pytest.raises(I.ObligationContractError, match="duplicate_float_card"):
        _run_dual(_mk_float(raw + [raw[0]]))


def test_dual_read_path_float_drops_threshold_hard_fails():
    """float 侧**删一阈值**（卡仍在集内）→ blueprint 该阈值成孤儿 → `obligation_association_orphan`。

    旧单向：float 侧不评该阈值，其 blueprint 静默不配对，pairs 少一条不炸（1885→1884）。
    """
    raw = _load_raw_cards()
    idx = _first_threshold_card_idx(raw)
    mutated = copy.deepcopy(raw)
    mutated[idx]["threshold_regimes"] = mutated[idx]["threshold_regimes"][:-1]
    with pytest.raises(I.ObligationContractError, match="obligation_association_orphan:threshold"):
        _run_dual(_mk_float(mutated))


def test_dual_read_path_float_adds_unbacked_source_item_hard_fails():
    """float 侧**多声明一源项**（blueprint 无此身份）→ `blueprint_association_miss`。

    float 卡加一 novel threshold_regime_id；blueprint 侧（真 bundle）无 → float 声明找不到已过闸
    blueprint → hard-fail（不 fail-open 静默产无身份 pair）。
    """
    raw = _load_raw_cards()
    idx = _first_threshold_card_idx(raw)
    mutated = copy.deepcopy(raw)
    novel = copy.deepcopy(mutated[idx]["threshold_regimes"][0])
    novel["threshold_regime_id"] = "NOVEL.REGIME.NOT.IN.BUNDLE"
    mutated[idx]["threshold_regimes"].append(novel)
    with pytest.raises(I.ObligationContractError, match="blueprint_association_miss:threshold"):
        _run_dual(_mk_float(mutated))


def test_dual_read_path_duplicate_same_source_item_hard_fails():
    """**blocker 1 核心负测**：float 侧**重复声明同一源项**（同 threshold_regime_id 原样加两次，
    **非**新增不同 ID）→ `duplicate_source_item_in_read_path`（multiset 保多重性、配对前检测重复键）。

    旧 set 折叠掩盖多重性：`_declared_covered_source_items` 用 set → 重复键折成一条、双向差不炸；
    eval 循环却按多重性对**同一 blueprint** 双配对 → pairs 1885→1886 静默过（无 hard-fail）。修法用
    multiset（list 保多重性）+ 配对前重复键闸，令此重复在配对**前** hard-fail。
    """
    raw = _load_raw_cards()
    idx = _first_threshold_card_idx(raw)
    mutated = copy.deepcopy(raw)
    dup = copy.deepcopy(mutated[idx]["threshold_regimes"][0])  # 同 threshold_regime_id 原样复制
    mutated[idx]["threshold_regimes"].append(dup)
    with pytest.raises(
        I.ObligationContractError, match="duplicate_source_item_in_read_path:threshold"
    ):
        _run_dual(_mk_float(mutated))


def test_declared_covered_source_items_is_multiset_preserving_multiplicity():
    """`_declared_covered_source_items` 返回 **multiset（list 保多重性）**、非 set 折叠：

    同卡两 threshold 同 regime_id → 同 (channel, source_item_id) 键出现**两次**（旧 set 折成一条）。
    直接内省证 multiset：list 长度 = 声明数、重复键计数 ≥2（证 set→list 修法落地）。
    """
    card = make_rule_card(
        "rc.ms",
        threshold_regimes=[_th(threshold_regime_id="rc.ms.t01"),
                           _th(threshold_regime_id="rc.ms.t01", value=9)],
    )
    items = S._declared_covered_source_items(card)
    assert isinstance(items, list)  # multiset，非 set
    key = ("threshold", B._encode_source_item_id("threshold", "rc.ms.t01"))
    assert items.count(key) == 2  # 多重性保留（set 会折成 1）


def test_index_blueprints_duplicate_key_hard_fails():
    """`_index_blueprints` **重复 (channel, source_item_id) 键报错不覆盖** → `duplicate_blueprint_key`。

    旧代码后者静默覆盖前者、擦除一条已过闸 blueprint 身份而不留痕。
    """
    card = make_rule_card("rc.idx", threshold_regimes=[_th(threshold_regime_id="rc.idx.t01")])
    th = _th(threshold_regime_id="rc.idx.t01")
    bp = B.build_threshold_blueprint(card, dict(th), _META)
    with pytest.raises(I.ObligationContractError, match="duplicate_blueprint_key"):
        S._index_blueprints(card, [bp, bp])  # 同 (channel, sid) 键两次


def test_dual_read_path_normal_397_still_exact_2310():
    """正常 397 卡双向校验通过、仍精确 2310 pair（v4；双向校验不误伤真语料）。"""
    raw = _load_raw_cards()
    pairs = _run_dual(_mk_float(raw))
    assert len(pairs) == 2310


def test_card_level_entry_multiset_gate_duplicate_source_item_hard_fails():
    """**blocker 1 补漏核心负测**：card 级公开入口传 `blueprints=` 亦执行 run 级**同一** multiset 闸。

    旧 card 级入口 `evaluate_covered_card_obligations_v2(..., blueprints=<已过闸集>)` 只建 blueprint
    索引（`_index_blueprints`）不跑 multiset 一致性闸：float 卡**重复声明同一源项**被 eval 循环按多重性
    对**同一 blueprint** 双配对（base_pairs→+1）、再被 `finalize_obligations_v2` 静默折回（同身份去重
    折回 base）——重复源项无痕吞掉（codex 实测 base=10→dup=11→折回 10）。修法在 card 级入口补
    `_assert_card_read_path_consistency` → 重复源项在配对**前** hard-fail（走 run 级同一判据）。

    本测试直走 card 级入口传 `blueprints=`（**绕过** run 级 `evaluate_covered_run_obligations_v2` 的
    run 级前置闸），证 card 级闸**独立生效**、非只 run 级。
    """
    # 合法单阈值卡 → 阶段一过闸 blueprint 集（单源项）。
    card1 = make_rule_card("rc.clg", threshold_regimes=[_th(threshold_regime_id="rc.clg.t01")])
    bps = B.derive_covered_card_blueprints(card1, _META)

    # 对照：正常单阈值卡走 card 级入口传 blueprints= → 成功、不误伤（正常路径 base pairs）。
    ok = S.evaluate_covered_card_obligations_v2(card1, _index([]), _META, blueprints=bps)
    base = len(ok)
    assert base >= 1

    # 反例：同 threshold_regime_id **原样复制两份**（重复源项，非新增不同 ID）走**同一 card 级入口**。
    card_dup = make_rule_card(
        "rc.clg",
        threshold_regimes=[_th(threshold_regime_id="rc.clg.t01"),
                           _th(threshold_regime_id="rc.clg.t01", value=9)],
    )
    with pytest.raises(
        I.ObligationContractError, match="duplicate_source_item_in_read_path:threshold"
    ):
        S.evaluate_covered_card_obligations_v2(card_dup, _index([]), _META, blueprints=bps)


# =========================================================================== #
# 6. applicability 隔离（据实报缺陷）
# =========================================================================== #


def test_applicability_isolated_from_state_channels():
    """applicability 隔离：不在覆盖 channel、驱动不产 applicability 状态、缺陷据实登记。"""
    assert "applicability" not in S.COVERED_STATE_CHANNELS
    assert "applicability" in S.ISOLATED_STATE_CHANNELS
    # 缺陷登记完整（症状/处置/不对称三节）
    for k in ("symptom", "disposition", "asymmetry"):
        assert k in S.APPLICABILITY_TYPE_DEFECT and S.APPLICABILITY_TYPE_DEFECT[k]
    # 驱动对含 applicability 的卡不产 applicability 状态
    card = make_rule_card("rc.ap")
    pairs = S.evaluate_covered_card_obligations_v2(card, _index([]), _META)
    assert all(p.blueprint.identity.source_channel != "applicability" for p in pairs)


def test_applicability_dto_evaluator_type_defect_is_real():
    """据实证缺陷真实存在：ApplicabilityDTO.building_scope=List[str]，evaluate_applicability 按 dict 处理。"""
    from evo_agent_baseline.closure.source_dtos import ApplicabilityDTO
    import typing
    # DTO 声明 List[str]
    ann = ApplicabilityDTO.model_fields["building_scope"].annotation
    assert typing.get_origin(ann) is list
    # evaluate_applicability 对 list 形 building_scope 走 isinstance(dict) 门控 → 静默跳过规则 2
    from evo_agent_baseline.closure.applicability import evaluate_applicability
    from evo_agent_baseline.closure.tests.fixtures import make_fact_pack as _mfp
    card = make_rule_card("rc.apd", applicability={
        "regime": "mbis", "actors": [], "phase": "", "subject": "",
        "component_scope": [], "building_scope": ["nonexistent_slot"], "exclusions": [],
    })
    # list 形 building_scope → isinstance(dict) False → 规则 2 不触发 → 不因 building_scope 判 NA
    res = evaluate_applicability(card, _mfp([]))
    assert res.state in {"applicable", "uncertain"}  # 绝不因 list scope 判 not_applicable


# =========================================================================== #
# 6b. v4 缺口增补：入口合一门槛（v1 净义务 ↔ v2 配对净义务逐卡零差）
# =========================================================================== #


def _v1_covered_obligations(card, fi, meta):
    """v1 **覆盖 channel** 义务（镜像 `validate_building_closure` 覆盖部分、去 scope/trigger-NA 合成审计）：
    trigger → slot_role → threshold → 全 node（extend 完整 node_out：含 artifact/deadline/method 子）→
    edge → workflow_artifact → workflow_deadline → evidence → exception → definition。trigger 控制流
    与 `evaluate_covered_card_obligations_v2` 同（聚合 False → 只 trigger、不产合成 NA audit）。"""
    obls = []
    tc = card.trigger_conditions or {}
    tres = []
    for tr in sorted(tc.get("items") or [], key=lambda x: str((x or {}).get("condition_id"))):
        if isinstance(tr, dict):
            o = D.evaluate_trigger(card, dict(tr), fi, meta)
            obls.append(o); tres.append(o)
    ta = D.aggregate_trigger_logic(tc.get("logic", "all"), tres)
    if ta is False:
        return obls
    for sr in sorted(card.slot_role_map or [], key=lambda x: str((x or {}).get("slot_ref_id"))):
        if isinstance(sr, dict) and sr.get("required"):
            obls.append(D.evaluate_slot_role(card, dict(sr), fi, ta, meta))
    for th in sorted(card.threshold_regimes or [], key=lambda x: str((x or {}).get("threshold_regime_id"))):
        if isinstance(th, dict):
            obls.append(D.evaluate_threshold(card, dict(th), fi, ta, meta, None))
    graph = card.obligation_graph or {}
    node_obls = {}
    for n in sorted(graph.get("nodes") or [], key=lambda x: str((x or {}).get("obligation_node_id"))):
        if not isinstance(n, dict):
            continue
        dto = D.ObligationNodeDTO.from_dict(dict(n))
        out = D.evaluate_obligation_node(card, dto, fi, ta, meta)
        obls.extend(out); node_obls[dto.obligation_node_id] = out
    obls.extend(D.evaluate_obligation_edges(card, graph.get("edges") or [], node_obls, fi, meta))
    obls.extend(D.derive_workflow_artifact_obligations(card, fi, ta, meta))
    obls.extend(D.derive_workflow_deadline_obligations(card, fi, ta, meta))
    er = card.evidence_requirements or {}
    for b in sorted(er.keys()):
        reqs = er.get(b) or []
        if not isinstance(reqs, list):
            continue
        for req in sorted(reqs, key=lambda x: str((x or {}).get("evidence_requirement_id"))):
            if isinstance(req, dict) and req.get("required", True):
                obls.append(D.evaluate_evidence_requirement(card, b, dict(req), fi, ta, meta))
    for exc in sorted(card.exceptions or [], key=lambda x: D._stable_key(x)):
        if isinstance(exc, dict):
            obls.append(D.evaluate_exception(card, dict(exc), fi, meta))
    for d in sorted(card.definitions or [], key=lambda x: D._stable_key(x)):
        if isinstance(d, dict):
            obls.append(D.evaluate_definition(card, dict(d), fi, meta))
    return obls


def test_entry_unification_v1_net_equals_v2_net_per_card_all_397():
    """**入口合一门槛（§9 充要验收）**：全 397 卡 v1 最终净义务（覆盖 channel `sort_and_dedupe` 后集）
    ↔ v2 阶段二配对净义务（各 pair 的 v1 义务 `dedupe_key` 集）**逐卡零差**（dedupe_key 集合相等），
    **总净 key 数硬断言 == 2306**（非 >0；加固：门槛总数锚定，防漂）。

    node 携带的 artifact/deadline 子（v1 `node_out[1:]`）在 v1 `sort_and_dedupe` 折入独立
    workflow_artifact / workflow_deadline 义务（v2 配对的正是这些独立义务）。空事实索引下 7 method 卡皆有
    trigger → trigger open → node 提前返回、无 method 子（§5.3），故本门槛不演 method 折叠；method 净集
    等价（可分 2⇄2 / 不可分 1⇄1，§3.4③）由带事实的 `test_method_net_equivalence_finalize_not_pair_projection`
    专测（比较 finalize 产出，非本处 pair 投影）。总净 2306（2310 pairs 内 v1 dedupe 折 4 条同 key）。"""
    fcards = _load_cards_float()
    assert len(fcards) == 397
    fi = _index([])
    pairs = _real_corpus_pairs()
    v2_by_card: Dict[str, set] = {}
    for pr in pairs:
        v2_by_card.setdefault(pr.v1_obligation.source_rule_card_id, set()).add(
            v1_dedupe_key(pr.v1_obligation)
        )

    total_v1 = total_v2 = 0
    mismatch: List[str] = []
    for card in fcards:
        v1_net = sort_and_dedupe_obligations(_v1_covered_obligations(card, fi, _META))
        v1_keys = {v1_dedupe_key(o) for o in v1_net}
        v2_keys = v2_by_card.get(card.rule_card_id, set())
        total_v1 += len(v1_keys); total_v2 += len(v2_keys)
        if v1_keys != v2_keys:
            mismatch.append(
                f"{card.rule_card_id}: v1-only={sorted(v1_keys - v2_keys)[:2]} "
                f"v2-only={sorted(v2_keys - v1_keys)[:2]}"
            )
    assert not mismatch, (
        f"入口合一门槛逐卡零差被破（{len(mismatch)} 卡有差，应 0）:\n" + "\n".join(mismatch[:10])
    )
    assert total_v1 == total_v2 == 2306, (
        f"入口合一门槛总净 key 数应精确 2306: v1={total_v1} v2={total_v2}"
    )
    print(f"[entry-unification gate] cards=397 v1_net_keys={total_v1} v2_pair_keys={total_v2} diff_cards=0")


# =========================================================================== #
# 6c. v4 method 子义务控制流五分支（§5.3）+ deadline 节点↔独立 dedup 等价（§4.1）
# =========================================================================== #


def _method_card(rid, *, trigger=None, dangling_recipient=False):
    wo = _workflow([])
    wo["method_keys_allowed"] = ["pull_test"]
    if dangling_recipient:
        wo["recipients"] = [{"recipient_id": "rcpt01", "recipient_type": "ba",
                             "recipient_key": "recipient.ba", "delivery_mode": "submit"}]
    node = {"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
            "action": "conduct_validation_test",
            "recipient_ids": (["rcpt99"] if dangling_recipient else []),
            "artifact_ids": [], "deadline_ids": [], "trigger_condition_ids": []}
    kwargs = dict(workflow_operands=wo, obligation_graph={"nodes": [node], "edges": []})
    if trigger == "slot":
        kwargs["slot_role_map"] = [_slot_role(slot_ref_id="sr1", slot_id="defect.present")]
        kwargs["trigger_conditions"] = {"logic": "all", "items": [
            _trigger(condition_id="c1", slot_ref_id="sr1", operator="==", expected_value=True)]}
    elif trigger == "measure":
        kwargs["trigger_conditions"] = {"logic": "all", "items": [
            {"condition_id": "c1", "predicate_kind": "measure", "operator": ">=",
             "expected_value": 5, "measure_key": "measure.crack_width", "unit": "mm"}]}
    return make_rule_card(rid, **kwargs), node


def test_method_control_flow_five_branches():
    """§5.3 控制流五分支：阶段二**仅当 node_out 实际含 method 子义务才配对**——True 配对 / open / blocked
    提前返回不配对无 miss / False node 不产义务 / dangling 提前返回。

    `_method_card` 的 node **无区分键（非可分，§3.4③）** → 不建独立 method-derived、method 子（若产出）
    **配回 node-main blueprint**（SID=node SID）。故 method 子配对由 **v1 义务**（kind=method + method-derivation
    notes）辨识，非 method SID（不可分节点无 method SID blueprint）。"""
    def _method_pairs(card, fi):
        pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)  # 不抛 miss = 通过
        # method 子 pair 按 **v1 义务** 辨识（不可分节点配回 node-main bp，无独立 method SID）。
        mp = [p for p in pairs if p.channel == "obligation_graph"
              and p.v1_obligation.kind == "method"
              and "method derivation" in (p.v1_obligation.notes or "")]
        S.finalize_obligations_v2([p.obligation_v2 for p in pairs])  # 组装/去重不炸（同 hash merge）
        return pairs, mp

    # ① True：无 trigger（聚合 True）→ node 产 method 子 → 配对（配回 node-main，不可分）
    card, node = _method_card("rc.m.true")
    pairs, mp = _method_pairs(card, _index([]))
    assert len(mp) == 1, "trigger True：method 子应配对"
    assert mp[0].v1_obligation.kind == "method"
    assert "method derivation" in (mp[0].v1_obligation.notes or "")
    # 不可分：method 子配回 node-main（同 node SID），非独立 method-derived SID
    assert mp[0].blueprint.identity.source_item_id == S._encode_source_item_id("obligation_graph", "n01", {})

    # ② open：slot trigger 无事实 → trigger open → node 提前返回、node_out 无 method 子 → 不配对、无 miss
    card, node = _method_card("rc.m.open", trigger="slot")
    pairs, mp = _method_pairs(card, _index([]))
    assert mp == [], "trigger open：method 子不配对（node 提前返回）"

    # ③ blocked：measure trigger 单位不符 → trigger blocked → node 提前返回 → 不配对、无 miss
    card, node = _method_card("rc.m.blocked", trigger="measure")
    fi = _index([make_fact("m", measure_key="measure.crack_width", value=8, value_type="number", unit="cm")])
    pairs, mp = _method_pairs(card, fi)
    assert mp == [], "trigger blocked：method 子不配对（node 提前返回）"

    # ④ False：slot trigger 事实 False → 聚合 False → node 循环整体跳过 → 仅 trigger 配对
    card, node = _method_card("rc.m.false", trigger="slot")
    fi = _index([make_fact("f", slot_id="defect.present", value=False, value_type="boolean")])
    pairs, mp = _method_pairs(card, fi)
    assert {p.channel for p in pairs} == {"trigger"}
    assert mp == []

    # ⑤ dangling：无 trigger、悬空 recipient → node 提前返回 blocked → 不配对；node-main 仍配对（blocked）
    card, node = _method_card("rc.m.dangling", dangling_recipient=True)
    pairs, mp = _method_pairs(card, _index([]))
    assert mp == [], "dangling：method 子不配对（node 提前返回）"
    nid = S._encode_source_item_id("obligation_graph", "n01", {})
    node_main = [p for p in pairs if p.channel == "obligation_graph"
                 and p.blueprint.identity.source_item_id == nid]
    assert node_main and node_main[0].v1_obligation.closure_status == "blocked"


def test_method_net_equivalence_finalize_not_pair_projection():
    """§3.4③ blocker 1 核心探针：**比较 `finalize_obligations_v2` 产出**（非 pair 的 v1_dedupe_key 集
    投影）证 method 净集等价。**带事实 fixture 令 method 子义务真产出**（无 card trigger →
    trigger_active=True → node 不提前返回 → v1 追加 method 子）——修 codex 逮的「全 397 空事实门槛 7 method
    卡 trigger-open 根本没进 method 分支」假绿灯。

    - **可分（5 卡代表，node 带 artifact_ids）**：node-main 与 method-derived 两 blueprint 异 hash →
      `finalize_obligations_v2` **保 2** → v2 净 2 == v1 净 2（method-kind）。
    - **不可分（2 卡代表，node 无区分键）**：**不建独立 method-derived**、method 子配回 node-main → 两
      ObligationV2 同 hash → `finalize_obligations_v2` **merge 成 1** → v2 净 1 == v1 净 1。旧 masking
      建两异身份 → finalize 保 2（v2 净 2 ≠ v1 净 1）——本测试**直接比 finalize 计数**故逮之。"""
    from evo_agent_baseline.closure.schema import ObligationNodeDTO as _NDTO
    fi = _index([])  # 空事实但无 card trigger → trigger_active=True → method 子真产出

    def _og_finalize(card):
        pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
        finals = S.finalize_obligations_v2([p.obligation_v2 for p in pairs])
        og_finals = [f for f in finals if f.identity.source_channel == "obligation_graph"]
        return pairs, og_finals

    # (a) 可分：node 带 artifact_ids（v1 dedupe 区分键）→ method 子 ≠ 主
    wo_a = _workflow([_wf_artifact(artifact_id="A1", artifact_key="form.mbi4")])
    wo_a["method_keys_allowed"] = ["pull_test"]
    node_a = {"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
              "action": "conduct_validation_test", "recipient_ids": [], "artifact_ids": ["A1"],
              "deadline_ids": [], "trigger_condition_ids": []}
    card_a = make_rule_card("rc.mdiff", workflow_operands=wo_a,
                            obligation_graph={"nodes": [node_a], "edges": []})
    pairs_a, og_finals_a = _og_finalize(card_a)
    assert any(p.v1_obligation.kind == "method" and "method derivation" in (p.v1_obligation.notes or "")
               for p in pairs_a), "可分：method 子义务应真产出（非空转假绿灯）"
    assert len(og_finals_a) == 2, f"可分 v2 finalize obligation_graph 应净 2: {len(og_finals_a)}"
    v1_out_a = D.evaluate_obligation_node(card_a, _NDTO.from_dict(dict(node_a)), fi, True, _META)
    v1_method_a = {v1_dedupe_key(o) for o in v1_out_a if o.kind == "method"}
    assert len(v1_method_a) == 2, f"可分 v1 method-kind 净应 2: {len(v1_method_a)}"
    assert len(og_finals_a) == len(v1_method_a) == 2  # v2 净 2 == v1 净 2

    # (b) 不可分：node 无 artifact/deadline → method 子 = 主 dedupe_key（v1 必折叠）
    wo_b = _workflow([]); wo_b["method_keys_allowed"] = ["pull_test"]
    node_b = {"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
              "action": "conduct_validation_test", "recipient_ids": [], "artifact_ids": [],
              "deadline_ids": [], "trigger_condition_ids": []}
    card_b = make_rule_card("rc.mfold", workflow_operands=wo_b,
                            obligation_graph={"nodes": [node_b], "edges": []})
    pairs_b, og_finals_b = _og_finalize(card_b)
    og_pairs_b = [p for p in pairs_b if p.channel == "obligation_graph"]
    # 阶段二产 2 个 obligation_graph pair（node-main + method 子，都配回 node-main bp）——但 **finalize 折 1**
    assert len(og_pairs_b) == 2, "不可分：node-main + method 子 两 pair（配回 node-main bp）"
    assert len({p.obligation_v2.canonical_identity_hash for p in og_pairs_b}) == 1, \
        "不可分：两 pair 同 canonical_identity_hash（method 子配回 node-main，非独立 method-derived）"
    assert len(og_finals_b) == 1, (
        f"不可分 v2 finalize obligation_graph 应 merge 成净 1（非 pair 投影 / 旧 masking 建两异身份=2）: "
        f"{len(og_finals_b)}"
    )
    v1_out_b = D.evaluate_obligation_node(card_b, _NDTO.from_dict(dict(node_b)), fi, True, _META)
    v1_method_b = {v1_dedupe_key(o) for o in v1_out_b if o.kind == "method"}
    assert len(v1_method_b) == 1, f"不可分 v1 method-kind 净应折 1: {len(v1_method_b)}"
    assert len(og_finals_b) == len(v1_method_b) == 1  # v2 净 1 == v1 净 1
    # 不可分不建独立 method-derived blueprint（§3.4③）
    bps_b = B.derive_covered_card_blueprints(card_b, _META)
    msid_b = S._method_sid(node_b)
    assert not any(bp.identity.source_item_id == msid_b for bp in bps_b), \
        "不可分：不建独立 method-derived blueprint"
    print(f"[method net-equiv] 可分 v2_finalize_og={len(og_finals_a)}==v1={len(v1_method_a)}; "
          f"不可分 v2_finalize_og={len(og_finals_b)}==v1={len(v1_method_b)}（pairs={len(og_pairs_b)}，finalize 折 1）")


def test_node_deadline_sub_folds_with_independent_deadline():
    """§4.1 deadline 1:1：node 携带 deadline 子（v1 `node_out` 内）与独立 deadline 义务同 dedupe_key →
    v1 `sort_and_dedupe` 折 1；v2 只配独立 deadline（node deadline 子不单独配对）+ node-main（内嵌
    DeadlineBinding），net 等价。"""
    wo = _workflow([])
    wo["deadlines"] = [{"deadline_id": "ddl01", "relation": "within", "offset_value": 7,
                        "offset_unit": "day", "time_anchor_key": "inspection.prescribed.completed"}]
    node = {"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
            "action": "submit_report", "recipient_ids": [], "artifact_ids": [],
            "deadline_ids": ["ddl01"], "trigger_condition_ids": []}
    card = make_rule_card("rc.ndlfold", workflow_operands=wo,
                          obligation_graph={"nodes": [node], "edges": []})
    fi = _index([])
    # v2：workflow_deadline 恰 1 配对 + node-main 1；node deadline 子不单独配对
    pairs = S.evaluate_covered_card_obligations_v2(card, fi, _META)
    wd = [p for p in pairs if p.channel == "workflow_deadline"]
    assert len(wd) == 1
    # v1 净：node deadline 子 + 独立 deadline 折成 1 条 deadline 义务
    v1_net = sort_and_dedupe_obligations(_v1_covered_obligations(card, fi, _META))
    v1_deadline = [o for o in v1_net if o.kind == "deadline"]
    assert len(v1_deadline) == 1, "v1 node deadline 子 + 独立 deadline → 折 1"
    # 门槛：本卡 v1 净 keys == v2 pair keys
    v2_keys = {v1_dedupe_key(p.v1_obligation) for p in pairs}
    assert {v1_dedupe_key(o) for o in v1_net} == v2_keys


# =========================================================================== #
# 7. blind 红线（新模块传递闭包禁 eval/workflow_engine/TruthBundle）
# =========================================================================== #

_SRC_ROOT = Path(S.__file__).resolve().parents[2]  # agent_v1/src
_FORBIDDEN_MODULE_PREFIXES = ("evo_agent_baseline.eval", "workflow_engine")
_FORBIDDEN_NAMES = ("TruthBundle", "threshold_evaluations")
_FIRST_PARTY = ("canonical_profile", "evo_agent_baseline", "workflow_engine", "research_kg")


def _module_to_path(mod: str) -> Optional[Path]:
    rel = mod.replace(".", "/")
    a = _SRC_ROOT / (rel + ".py")
    b = _SRC_ROOT / rel / "__init__.py"
    return a if a.exists() else (b if b.exists() else None)


def _resolve_relative(cur_mod: str, level: int, module: Optional[str]) -> str:
    parts = cur_mod.split(".")
    base = parts[: len(parts) - level]
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _collect_imports(path: Path, cur_mod: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module)
                for alias in node.names:
                    names.add(alias.name)
            elif node.level > 0:
                mods.add(_resolve_relative(cur_mod, node.level, node.module))
                for alias in node.names:
                    names.add(alias.name)
    return mods, names


def _transitive(start):
    seen, all_mods, all_names, reached = set(), set(), set(), []
    queue = list(start)
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = _module_to_path(mod)
        if path is None:
            continue
        reached.append(mod)
        mods, names = _collect_imports(path, mod)
        all_mods |= mods
        all_names |= names
        for m in mods:
            if m.startswith(_FIRST_PARTY) and m not in seen:
                queue.append(m)
    return reached, all_mods, all_names


def test_blind_scan_state_eval_clean():
    """blind：blueprint_state_eval 传递闭包禁 import eval/workflow_engine/TruthBundle。"""
    start = ["evo_agent_baseline.closure.blueprint_state_eval"]
    assert _module_to_path(start[0]) is not None, "src 根解析错（空转风险）"
    reached, all_mods, all_names = _transitive(start)
    for dep in (
        "evo_agent_baseline.closure.blueprint_state_eval",
        "evo_agent_baseline.closure.identity_v2",
        "evo_agent_baseline.closure.blueprint_deriver",
        "evo_agent_baseline.closure.obligation_deriver",
    ):
        assert dep in reached, f"blind 扫描未跑到依赖 {dep}（空转/相对 import 未跟进）"
    offending = {
        m for m in all_mods
        if any(m == p or m.startswith(p + ".") for p in _FORBIDDEN_MODULE_PREFIXES)
    }
    assert not offending, f"blind 违规 import 模块: {sorted(offending)}"
    assert not (set(all_names) & set(_FORBIDDEN_NAMES)), "blind 违规 import 名"
