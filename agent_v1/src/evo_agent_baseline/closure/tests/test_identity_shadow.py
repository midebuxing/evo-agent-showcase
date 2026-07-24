"""identity-v5 影子现网路径专项单测（现网键切换增补 §10 步 5/6，DEBT-054 最后一役）。

覆盖验收：
- **步 5 判定语义零改**：`validate_building_closure(shadow_sink=None)`（live）vs `shadow_sink=[]` 返回
  义务字节 + machine_report 逐字节相等（唯一差异 = 非确定性 `created_at` 时间戳，剔除后全等）。
- **步 6 专项完备**（397 卡全量 + fragment 展开 + 结构 NA + trigger 聚合 + node/edge 多产物）：
  每条 v1 义务 ↔ **恰一** `BoundObligation` ↔ v5 键（`len(bound)==pre_dedup`、无 unbound）；
  **无误合并**（v5 键分组后同组 canonical identity bytes 全等）；影子对账 allow_stop 零翻转、
  存在性零翻转、未归因状态差 = 0、v1 影子去重 == 判定权威、v5 过合并 = 0。

只用**已提交资源**（397 卡权威 bundle + 合成 FactPack）；30 楼真实事实对账见 `allow_stop_reconcile.py`
（run 目录 gitignore，非 pytest）。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from canonical_profile import canonical_json
from evo_agent_baseline.contracts import (
    FactAtom, FactPack, RuleCardDTO, RuleSlice, SemanticSlotDTO,
)
from evo_agent_baseline.closure.identity_blueprint_catalog import (
    build_identity_blueprint_catalog,
)
from evo_agent_baseline.closure.identity_shadow import (
    reconcile_shadow, run_shadow_closure,
)
from evo_agent_baseline.closure.tests.fixtures import (
    BUILDING_ID, RUN_ID, WORLD_ID, make_fact_pack, make_rule_slice,
)
from evo_agent_baseline.closure.validator import validate_building_closure

_META = {"run_id": RUN_ID, "world_id": WORLD_ID, "building_id": BUILDING_ID}


def _find_bundle() -> Path:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = (base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
                / "rule_cards.json")
        if cand.exists():
            return cand
    pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")


def _real_float_cards() -> List[RuleCardDTO]:
    data = json.loads(_find_bundle().read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


def _rule_slice_full(float_cards) -> RuleSlice:
    return make_rule_slice(float_cards)


# =========================================================================== #
# 通用断言：完备（一对一无 unbound）+ 无误合并（v5 组内 identity bytes 全等）
# =========================================================================== #


def _assert_complete_and_no_mismerge(run) -> Dict[str, int]:
    # 完备：每条 pre-dedup v1 义务恰一 BoundObligation（run_shadow_closure 未抛 = 无 unbound）。
    assert len(run.bound) == run.pre_dedup_count, "bound 数 != pre-dedup 义务数（有 unbound/多绑）"
    # 无误合并：同 canonical_identity_hash 组内 identity canonical bytes 全等。
    by_hash: Dict[str, str] = {}
    for b in run.bound:
        h = b.blueprint.canonical_identity_hash
        cb = canonical_json(b.blueprint.identity.model_dump())
        prev = by_hash.get(h)
        if prev is None:
            by_hash[h] = cb
        else:
            assert prev == cb, f"v5 键误合并：同 hash {h} 下 identity bytes 不等"
    return {"distinct_identities": len(by_hash)}


def _assert_reconcile_clean(rec: Dict[str, Any]) -> None:
    assert rec["allow_stop_flip"] is False, "allow_stop 翻转"
    assert rec["open_exist_flip"] is False, "open 存在性翻转"
    assert rec["blocked_exist_flip"] is False, "blocked 存在性翻转"
    assert rec["unexplained_status_diffs"] == 0, "存在未归因逐源状态差"
    assert rec["v5_shadow_matches_authoritative"] is True, "v5 影子去重 != 活动判定权威（live v5）"
    assert rec["v5_over_merge_groups"] == 0, "v5 过合并（合并了 v1 分开的义务）"


# =========================================================================== #
# 步 5：判定语义零改（shadow_sink=None live 路径字节不变）
# =========================================================================== #


def test_live_v5_deterministic_byte_identical_repeat():
    """现网键切换后 v5 活动路径**确定性**：同输入重复跑返回义务 + machine_report + identity_manifest
    逐字节相等（IT-004；唯一差异 = 非确定性 `created_at` 时间戳）。

    现网键切换后 `shadow_sink` 参数已并入活动绑定路径（登记机制转正），本测试改证 v5 活动路径本身
    幂等（同 catalog 同输入 → byte-identical 去重/编号/manifest）。
    """
    fcards = _real_float_cards()
    rs = _rule_slice_full(fcards)
    fp = make_fact_pack([])
    catalog = build_identity_blueprint_catalog(_find_bundle(), rs, fp, _META)

    r1 = validate_building_closure(rs, fp, identity_blueprint_catalog=catalog)
    r2 = validate_building_closure(rs, fp, identity_blueprint_catalog=catalog)

    # machine_report 逐字节相等（含 run_audit / identity_catalog_sha256）。
    assert (json.dumps(r1.machine_readable_report, sort_keys=True, ensure_ascii=False)
            == json.dumps(r2.machine_readable_report, sort_keys=True, ensure_ascii=False))
    # obligation_set 剔 created_at 后逐字节相等（含 identity_manifest / 版本字段）。
    d1 = r1.obligation_set.model_dump()
    d2 = r2.obligation_set.model_dump()
    assert [k for k in d1 if d1[k] != d2[k]] == ["created_at"], "差异不止 created_at（非确定性）"
    d1.pop("created_at"); d2.pop("created_at")
    assert (json.dumps(d1, sort_keys=True, ensure_ascii=False, default=str)
            == json.dumps(d2, sort_keys=True, ensure_ascii=False, default=str))
    # allow_stop / 计数 / v5 版本字段一字不动。
    assert r1.allow_stop == r2.allow_stop
    assert r1.closure_summary.model_dump() == r2.closure_summary.model_dump()
    assert r1.obligation_set.obligation_identity_schema == "obligation_identity_v5"
    assert len(r1.obligation_set.identity_manifest) == len(r1.obligation_set.obligations)


# =========================================================================== #
# 步 6：397 卡全量（building scope）—— 完备无 unbound + 无误合并 + 对账干净
# =========================================================================== #


def test_full_397_corpus_building_scope_complete_no_unbound():
    """397 卡全量 + 空 FactPack（building scope）：全覆盖 channel + applicability + node/edge fan-out
    每条义务恰一身份、无 unbound、无误合并；影子对账 allow_stop / 存在性 / 逐源状态零差。"""
    fcards = _real_float_cards()
    rs = _rule_slice_full(fcards)
    fp = make_fact_pack([])
    run = run_shadow_closure(_find_bundle(), rs, fp, _META)

    info = _assert_complete_and_no_mismerge(run)
    assert run.pre_dedup_count > 0
    # 覆盖度：全 397 卡各覆盖 channel 均现（非空转）。applicability 是**条件绑定**（仅
    # not_applicable/uncertain 时产），空 FactPack 下全卡 applicable → 不产，故不在本必现集
    # （applicability 绑定见 `test_applicability_na_bound_building_scope` + 30 楼真实对账）。
    channels = Counter(b.blueprint.identity.source_channel for b in run.bound)
    for ch in ("trigger", "slot_role", "threshold", "obligation_graph",
               "workflow_artifact", "evidence", "definition"):
        assert channels.get(ch, 0) > 0, f"覆盖 channel {ch} 缺（空转）"

    rec = reconcile_shadow(run)
    _assert_reconcile_clean(rec)
    assert rec["distinct_identities"] == info["distinct_identities"]


# =========================================================================== #
# 步 6 专项：合成场景（fragment 展开 / 结构 NA / trigger 聚合 / node-edge 多产物）
# =========================================================================== #


def _jval(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _fact(fid, *, slot_id=None, value=None, vt="string", qualifiers=None, provenance=None) -> FactAtom:
    return FactAtom(
        fact_id=fid, world_id=WORLD_ID, building_id=BUILDING_ID, carrier_type="sidecar_entry",
        carrier_id=BUILDING_ID, target_ref=None, slot_id=slot_id, measure_key=None,
        value_json=_jval(value), value_type=vt, unit=None, qualifiers=qualifiers or {},
        source_path="t", source_node_id=f"n-{fid}", provenance=provenance or {},
    )


def _fp(facts: List[FactAtom]) -> FactPack:
    si: Dict[str, List[str]] = {}
    ci: Dict[str, List[str]] = {}
    for f in facts:
        if f.slot_id:
            si.setdefault(f.slot_id, []).append(f.fact_id)
        if f.carrier_id:
            ci.setdefault(f.carrier_id, []).append(f.fact_id)
    return FactPack(run_id=RUN_ID, world_id=WORLD_ID, building_id=BUILDING_ID, facts=facts,
                    slot_index=si, measure_index={}, carrier_index=ci,
                    source_tables=["measurements.parquet", "sidecar_entries.parquet"])


def _card(rid, *, trigger=None, wf=None, slot_role_map=None, graph=None) -> Dict[str, Any]:
    return dict(
        rule_card_id=rid, source_document_id="DOC",
        source_section=[{"clause_id": f"{rid}.c1"}],
        source_quote=[{"source_quote_id": f"{rid}::q1", "quote_local_id": "q1"}],
        normalized_rule_text="t", family_id="FAM", neighbor_families=[],
        applicability={"regime": "mbis", "actors": [], "phase": "", "subject": "",
                       "component_scope": [], "building_scope": [], "exclusions": []},
        trigger_conditions=trigger or {"logic": "all", "items": []},
        workflow_operands=wf or {"primary_actor": "", "primary_action": "", "recipients": [],
                                 "artifacts": [], "deadlines": [], "audiences": [],
                                 "method_keys_allowed": []},
        slot_role_map=slot_role_map or [], threshold_regimes=[], exceptions=[], definitions=[],
        obligation_graph=graph or {"nodes": [], "edges": []},
        evidence_requirements={"for_matching": [], "for_submission": [], "for_completion": []},
    )


def _synthetic_slice(card_dicts, semantic_slots=None, retrieval_policy=None):
    cards = [RuleCardDTO(**c) for c in card_dicts]
    return cards, RuleSlice(
        run_id=RUN_ID, rulecard_bundle_id="B", candidate_rule_cards=cards, rule_families=[],
        semantic_slots=semantic_slots or [], measures=[], artifacts=[], time_anchors=[],
        source_quotes=[], retrieval_policy=retrieval_policy or {},
    )


def _write_bundle(tmp_path, card_dicts) -> Path:
    p = tmp_path / "rule_cards.json"
    p.write_text(json.dumps({"bundle_id": "B", "cards": card_dicts}, ensure_ascii=False),
                 encoding="utf-8")
    return p


_DEFECT_SLOT = [SemanticSlotDTO(slot_id="slot.defect.present", semantic_domain="defect")]


def test_fragment_expansion_per_fragment_scoped_identity(tmp_path):
    """fragment 承载卡 × 2 fragment 事实 → 逐 fragment 物化 scoped blueprint（fragment_id 进 hash）；
    每 fragment scope 各绑各身份、无 unbound、无误合并（两 fragment 义务异身份）。"""
    sr = [{"slot_ref_id": "sr01", "slot_id": "slot.defect.present", "qualifiers": {},
           "roles": ["state"], "required": True}]
    c = _card("RC.frag", slot_role_map=sr)
    facts = [
        _fact("f1", slot_id="slot.defect.present", value=True, vt="boolean",
              qualifiers={"fragment_id": "FR-1"}),
        _fact("f2", slot_id="slot.defect.present", value=True, vt="boolean",
              qualifiers={"fragment_id": "FR-2"}),
    ]
    cards, rs = _synthetic_slice([c], semantic_slots=_DEFECT_SLOT)
    run = run_shadow_closure(_write_bundle(tmp_path, [c]), rs, _fp(facts), _META)

    _assert_complete_and_no_mismerge(run)
    frag_scopes = {b.blueprint.identity.scope.scope_id for b in run.bound
                   if b.blueprint.identity.scope.kind == "fragment"}
    assert frag_scopes == {"FR-1", "FR-2"}, f"fragment scope 未逐份物化: {frag_scopes}"
    # 两 fragment 的 slot_role 义务异身份（fragment_id 进 canonical hash）。
    hashes = {b.blueprint.identity.scope.scope_id: b.blueprint.canonical_identity_hash
              for b in run.bound if b.blueprint.identity.source_channel == "slot_role"}
    assert hashes["FR-1"] != hashes["FR-2"]
    _assert_reconcile_clean(reconcile_shadow(run))


def test_structural_scope_audit_bound_at_incompatible_fragment(tmp_path):
    """DEBT-065 fragment 组件结构 NA：授权卡目标叶型与 fragment 单值身份可证排斥 → 该 fragment
    产 `structural_scope_audit` 义务、绑 fragment scope 结构审计蓝图（相容 fragment 不产该审计）。"""
    rp = {
        "projection_runtime_mapping_v1": {
            "qualifier_value_aliases": {"component_type_key": {"beam_raw": "beam", "column_raw": "column"}},
            "component_category_members": {}, "subject_component_crosswalk": {}},
        # DEBT-065:beam/column 作合成叶型;RC.struct 授权 beam,fragment FR-2(column)与 beam 可证排斥 → NA。
        "component_type_lattice": {"leaf_types": ["beam", "column"], "disjoint_pairs": [["beam", "column"]]},
        "exact_fragment_target_authorizations": {"RC.struct": "beam"},
    }
    sr = [{"slot_ref_id": "sr01", "slot_id": "slot.defect.present",
           "qualifiers": {"component_type_key": "beam"}, "roles": ["state"], "required": True}]
    c = _card("RC.struct", slot_role_map=sr)
    facts = [
        _fact("f1", slot_id="slot.defect.present", value=True, vt="boolean",
              qualifiers={"fragment_id": "FR-1", "component_type_key": "beam"}),
        _fact("f2", slot_id="slot.defect.present", value=True, vt="boolean",
              qualifiers={"fragment_id": "FR-2", "component_type_key": "column"}),
        # P1-1:genuine W0 身份来源(w0_component_identity 专用通道,每 fragment 恰一条)。
        _fact("id1", slot_id="w0_component_identity", value="beam", vt="string",
              qualifiers={"fragment_id": "FR-1", "canonical_component_type": "beam"},
              provenance={"channel": "w0_component_identity", "derivation": "fragment_component_projection"}),
        _fact("id2", slot_id="w0_component_identity", value="column", vt="string",
              qualifiers={"fragment_id": "FR-2", "canonical_component_type": "column"},
              provenance={"channel": "w0_component_identity", "derivation": "fragment_component_projection"}),
    ]
    cards, rs = _synthetic_slice([c], semantic_slots=_DEFECT_SLOT, retrieval_policy=rp)
    run = run_shadow_closure(_write_bundle(tmp_path, [c]), rs, _fp(facts), _META)

    _assert_complete_and_no_mismerge(run)
    struct = [b for b in run.bound
              if b.blueprint.identity.source_channel == "structural_scope_audit"]
    assert len(struct) == 1, "应恰 1 条结构 NA 审计（不容 fragment FR-2）"
    assert struct[0].blueprint.identity.scope.kind == "fragment"
    assert struct[0].blueprint.identity.scope.scope_id == "FR-2"
    # 相容 fragment（FR-1）正常产 slot_role 义务、不产结构审计。
    assert any(b.blueprint.identity.source_channel == "slot_role"
               and b.blueprint.identity.scope.scope_id == "FR-1" for b in run.bound)
    _assert_reconcile_clean(reconcile_shadow(run))


def test_trigger_aggregation_false_bound_to_audit(tmp_path):
    """trigger 聚合 false：卡触发器求值 false → 产 `trigger_aggregation_audit` 义务、绑聚合审计蓝图
    （身份 = logic + 成员 trigger SID 排序集 + scope，不与单条 trigger / applicability 蓝图撞身份）。"""
    tr = {"logic": "all", "items": [
        {"condition_id": "trg01", "predicate_kind": "slot", "slot_ref_id": "sr01",
         "operator": "==", "expected_value": True}]}
    sr = [{"slot_ref_id": "sr01", "slot_id": "slot.defect.present", "qualifiers": {},
           "roles": ["trigger"], "required": True}]
    c = _card("RC.trig", trigger=tr, slot_role_map=sr)
    facts = [_fact("f1", slot_id="slot.defect.present", value=False, vt="boolean",
                   qualifiers={"fragment_id": "FR-1"})]
    cards, rs = _synthetic_slice([c], semantic_slots=_DEFECT_SLOT)
    run = run_shadow_closure(_write_bundle(tmp_path, [c]), rs, _fp(facts), _META)

    _assert_complete_and_no_mismerge(run)
    agg = [b for b in run.bound
           if b.blueprint.identity.source_channel == "trigger_aggregation_audit"]
    assert len(agg) == 1, "应恰 1 条 trigger 聚合审计"
    # 聚合审计身份 != 成员 trigger 身份（不误合并）。
    trig = [b for b in run.bound if b.blueprint.identity.source_channel == "trigger"]
    assert len(trig) == 1
    assert (agg[0].blueprint.canonical_identity_hash
            != trig[0].blueprint.canonical_identity_hash)
    _assert_reconcile_clean(reconcile_shadow(run))


def test_applicability_na_bound_building_scope(tmp_path):
    """卡级 applicability not_applicable（regime != mbis）→ scope-audit 义务绑 applicability 蓝图
    （building scope，每卡恒一条声明、仅 NA/uncertain 时消费）。"""
    c = _card("RC.na")
    c["applicability"] = {"regime": "other", "actors": [], "phase": "", "subject": "",
                          "component_scope": [], "building_scope": [], "exclusions": []}
    cards, rs = _synthetic_slice([c])
    run = run_shadow_closure(_write_bundle(tmp_path, [c]), rs, _fp([]), _META)

    _assert_complete_and_no_mismerge(run)
    appl = [b for b in run.bound if b.blueprint.identity.source_channel == "applicability"]
    assert len(appl) == 1, "not_applicable 卡应产恰 1 条 applicability scope-audit"
    assert appl[0].blueprint.identity.scope.kind == "building"
    assert appl[0].blueprint.identity.scope.scope_id == ""
    _assert_reconcile_clean(reconcile_shadow(run))


def test_node_edge_multiproduct_all_bound_distinct(tmp_path):
    """node/edge 多产物：node fan-out（node-main + artifact 子 + deadline 子 + method 子）+ edge 审计
    每条义务恰一身份、无 unbound、无误合并（各子义务 + node-main 各异身份）。"""
    art = {"artifact_id": "A1", "artifact_type": "form", "artifact_key": "form.mbi4"}
    dl = {"deadline_id": "D1", "relation": "before", "time_anchor_key": "ta.x",
          "offset_value": 7, "offset_unit": "day"}
    wf = {"primary_actor": "", "primary_action": "", "recipients": [], "artifacts": [art],
          "deadlines": [dl], "audiences": [], "method_keys_allowed": ["*"]}
    nodes = [
        {"obligation_node_id": "n1", "node_kind": "obligation", "action": "select_repair_method",
         "actor": "a", "recipient_ids": [], "artifact_ids": ["A1"], "deadline_ids": ["D1"],
         "trigger_condition_ids": []},
        {"obligation_node_id": "n2", "node_kind": "obligation", "action": "submit",
         "actor": "a", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
         "trigger_condition_ids": []},
    ]
    edges = [{"source_node_id": "n1", "target_node_id": "n2", "relation": "if_failed_then",
              "obligation_edge_id": "e1"}]
    c = _card("RC.graph", wf=wf, graph={"nodes": nodes, "edges": edges})
    cards, rs = _synthetic_slice([c])
    run = run_shadow_closure(_write_bundle(tmp_path, [c]), rs, _fp([]), _META)

    _assert_complete_and_no_mismerge(run)
    channels = Counter(b.blueprint.identity.source_channel for b in run.bound)
    # node fan-out：obligation_graph（node-main×2 + method + edge 审计）+ workflow_artifact / deadline。
    assert channels["obligation_graph"] >= 3
    assert channels["workflow_artifact"] >= 1
    assert channels["workflow_deadline"] >= 1
    # method 子身份 != 其 node-main 身份（可分节点 n1 带 artifact_ids）。
    og = [b for b in run.bound if b.blueprint.identity.source_channel == "obligation_graph"]
    n1_ids = [b.blueprint.identity.source_item_id for b in og
              if b.blueprint.identity.obligation_node_id == "n1"]
    assert len(set(n1_ids)) == len(n1_ids), "n1 的多产物身份应互异（node-main vs method-derived）"
    _assert_reconcile_clean(reconcile_shadow(run))
