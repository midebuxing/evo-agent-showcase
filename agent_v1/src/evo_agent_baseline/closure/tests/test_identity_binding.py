"""identity-v5 扁平化前来源登记 + `BoundObligation` 单测（现网键切换增补 §1 / DEBT-054 步 4）。

覆盖验收 ④：
- 真卡 node/edge 求值**每条 v1 义务有且恰一来源令牌**（token 数 == 义务数，fan-out N 条各一）。
- 来源登记**不改义务字节**（source_sink 有/无两跑 model_dump 逐条 bytes 相等）。
- 每 `BoundObligation` 恰一 blueprint（token → 五元组 → `catalog.require`，无 unbound）。
- fan-out 无例外：node-main + artifact 子 + deadline 子 + method 子（可分独立身份 / 不可分折回
  node-main），edge 悬空/未知关系/inactive-target 各携各自令牌。

**加性影子**：source_sink=None（默认 live 路径）时零副作用、判定字节不变（本套 with/without 对照证）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from evo_agent_baseline.contracts import RuleCardDTO, SemanticSlotDTO
from evo_agent_baseline.closure import identity_binding as BIND
from evo_agent_baseline.closure import identity_blueprint_catalog as CAT
from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.identity_v2 import ObligationContractError
from evo_agent_baseline.closure.obligation_deriver import (
    SourceToken,
    evaluate_obligation_edges,
    evaluate_obligation_node,
)
from evo_agent_baseline.closure.schema import ObligationNodeDTO
from evo_agent_baseline.closure.tests.fixtures import (
    RUN_ID,
    WORLD_ID,
    BUILDING_ID,
    make_fact_pack,
    make_rule_slice,
)

_META = {"run_id": RUN_ID, "world_id": WORLD_ID, "building_id": BUILDING_ID}


def _find_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = (base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
                / "rule_cards.json")
        if cand.exists():
            return cand
    return None


def _real_float_cards() -> List[RuleCardDTO]:
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


def _bytes(obls) -> List[Dict[str, Any]]:
    return [o.model_dump() for o in obls]


# =========================================================================== #
# 全 397 真语料：node/edge fan-out 一对一 + 字节不变 + 无 unbound
# =========================================================================== #


def _build_real_catalog():
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    fcards = _real_float_cards()
    rule_slice = make_rule_slice(fcards)
    fact_pack = make_fact_pack([])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)
    return cat, fcards, FactIndex(fact_pack)


def test_real_corpus_node_edge_fanout_one_to_one_bound():
    """全 397 真卡（trigger_active=True 强制全 fan-out）：每条义务恰一令牌、恰一身份，无 unbound。"""
    cat, fcards, idx = _build_real_catalog()

    total_node = 0
    total_edge = 0
    method_tok = 0
    artifact_tok = 0
    deadline_tok = 0
    for card in fcards:
        graph = card.obligation_graph or {}
        node_obligations: Dict[str, List] = {}
        for raw in graph.get("nodes", []) or []:
            node_dto = ObligationNodeDTO.from_dict(dict(raw))
            tokens: List[SourceToken] = []
            out = evaluate_obligation_node(
                card, node_dto, idx, True, _META, source_sink=tokens
            )
            node_obligations[node_dto.obligation_node_id] = out
            # 每条义务恰一令牌（fan-out N 条各一）。
            assert len(tokens) == len(out), (
                f"token 数 != 义务数: {card.rule_card_id}/{node_dto.obligation_node_id}"
            )
            for t in tokens:
                method_tok += t.role == "method"
                artifact_tok += t.role == "artifact"
                deadline_tok += t.role == "deadline"
            # 每 BoundObligation 恰一 blueprint（无 unbound）。
            bound = BIND.bind_fanout_obligations(card, out, tokens, cat, None)
            assert len(bound) == len(out)
            for b in bound:
                assert b.blueprint is not None
            total_node += len(out)

        edges = graph.get("edges", []) or []
        if edges:
            etok: List[SourceToken] = []
            eout = evaluate_obligation_edges(
                card, edges, node_obligations, idx, _META, source_sink=etok
            )
            assert len(etok) == len(eout)
            ebound = BIND.bind_fanout_obligations(card, eout, etok, cat, None)
            assert len(ebound) == len(eout)
            total_edge += len(eout)

    # 覆盖度：真语料含 method / artifact / deadline / edge fan-out（非空转）。
    assert total_node > 0 and total_edge > 0
    # DEBT-049 Phase3 U4：七卡 action→conduct_validation_test → 各 node 追加 1 条 method 子义务令牌
    # → method_tok 7→14（+7）；deadline/artifact 令牌不受影响（v1 method_tok=7）。
    assert method_tok == 14 and deadline_tok == 25 and artifact_tok == 330


def test_source_registration_does_not_change_obligation_bytes():
    """来源登记不改义务字节：source_sink 有/无两跑，返回义务 model_dump 逐条 bytes 相等。"""
    _cat, fcards, idx = _build_real_catalog()
    checked_nodes = 0
    checked_edges = 0
    for card in fcards:
        graph = card.obligation_graph or {}
        node_obligations: Dict[str, List] = {}
        for raw in graph.get("nodes", []) or []:
            node_dto = ObligationNodeDTO.from_dict(dict(raw))
            with_sink: List[SourceToken] = []
            out_with = evaluate_obligation_node(
                card, node_dto, idx, True, _META, source_sink=with_sink
            )
            out_without = evaluate_obligation_node(card, node_dto, idx, True, _META)
            node_obligations[node_dto.obligation_node_id] = out_with
            assert _bytes(out_with) == _bytes(out_without)
            checked_nodes += 1
        edges = graph.get("edges", []) or []
        if edges:
            etok: List[SourceToken] = []
            e_with = evaluate_obligation_edges(
                card, edges, node_obligations, idx, _META, source_sink=etok
            )
            e_without = evaluate_obligation_edges(
                card, edges, node_obligations, idx, _META
            )
            assert _bytes(e_with) == _bytes(e_without)
            checked_edges += 1
    assert checked_nodes > 0 and checked_edges > 0


# =========================================================================== #
# fan-out 逐 role 显式检查（可分/不可分 method；node artifact/deadline 子）
# =========================================================================== #


def _full_card(rid, *, nodes, edges=None, method_keys=None, artifacts=None, deadlines=None):
    wf = {
        "primary_actor": "", "primary_action": "", "recipients": [],
        "artifacts": artifacts or [], "deadlines": deadlines or [], "audiences": [],
        "method_keys_allowed": method_keys or [],
    }
    return dict(
        rule_card_id=rid, source_document_id="DOC",
        source_section=[{"clause_id": f"{rid}.c1"}],
        source_quote=[{"source_quote_id": f"{rid}::q1", "quote_local_id": "q1"}],
        normalized_rule_text="t", family_id="FAM", neighbor_families=[],
        applicability={"regime": "mbis", "actors": [], "phase": "", "subject": "",
                       "component_scope": [], "building_scope": [], "exclusions": []},
        trigger_conditions={"logic": "all", "items": []},
        workflow_operands=wf, slot_role_map=[], threshold_regimes=[],
        exceptions=[], definitions=[],
        obligation_graph={"nodes": nodes, "edges": edges or []},
        evidence_requirements={"for_matching": [], "for_submission": [], "for_completion": []},
    )


def _gnode(nid, action):
    return {"obligation_node_id": nid, "node_kind": "obligation", "action": action,
            "actor": "a", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
            "trigger_condition_ids": []}


def _eval_edges_bound(tmp_path, rid, nodes, edges, sub):
    """建卡+catalog，评 node/edge（source_sink 登记令牌），绑定 → 返回 (eout, etok, ebound)。"""
    card_d = _full_card(rid, nodes=nodes, edges=edges)
    p = tmp_path / f"rc_{sub}.json"
    p.write_text(json.dumps({"bundle_id": "B", "cards": [card_d]}, ensure_ascii=False),
                 encoding="utf-8")
    fcard = RuleCardDTO(**card_d)
    cat = CAT.build_identity_blueprint_catalog(
        p, make_rule_slice([fcard]), make_fact_pack([]), _META
    )
    idx = FactIndex(make_fact_pack([]))
    node_obls: Dict[str, List] = {}
    for raw in nodes:
        nd = ObligationNodeDTO.from_dict(dict(raw))
        node_obls[nd.obligation_node_id] = evaluate_obligation_node(
            fcard, nd, idx, True, _META
        )
    etok: List[SourceToken] = []
    eout = evaluate_obligation_edges(fcard, edges, node_obls, idx, _META, source_sink=etok)
    assert len(etok) == len(eout)
    ebound = BIND.bind_fanout_obligations(fcard, eout, etok, cat, None)
    return eout, etok, ebound


def test_probe1_unknown_relation_two_avatars_distinct_identity(tmp_path):
    """探针①（codex 阻断 1）：未知 relation edge → source/target 两义务各绑各分身（两 hash 不同）。"""
    n1, n2 = _gnode("n01", "a"), _gnode("n02", "b")
    unk = {"source_node_id": "n01", "target_node_id": "n02", "relation": "weird_rel"}
    eout, etok, ebound = _eval_edges_bound(tmp_path, "RC.unk", [n1, n2], [unk], "unk")
    assert len(eout) == 2 and {t.member for t in etok} == {"source", "target"}
    assert all(t.role == "edge_unknown" for t in etok)
    hashes = [b.blueprint.canonical_identity_hash for b in ebound]
    assert hashes[0] != hashes[1], "source/target 两分身必须异身份（旧同 SID 会 v5 误合并）"


def test_probe2_inactive_target_aggregate_full_edge_set(tmp_path):
    """探针②（codex 阻断 1）：多 edge 同 target 聚合 → 身份含完整 edge 集；改**非最小** edge → bound hash 变。"""
    n1, n3 = _gnode("n01", "a"), _gnode("n03", "c")
    e1 = {"source_node_id": "n01", "target_node_id": "n03", "relation": "if_failed_then"}

    def agg_hash(second_src, sub):
        n_src = _gnode(second_src, "b")
        e2 = {"source_node_id": second_src, "target_node_id": "n03",
              "relation": "if_failed_then"}
        eout, etok, ebound = _eval_edges_bound(
            tmp_path, "RC.agg", [n1, n_src, n3], [e1, e2], sub
        )
        inact = [(o, t, b) for o, t, b in zip(eout, etok, ebound)
                 if t.role == "edge_inactive"]
        assert len(inact) == 1, f"应恰 1 条 inactive-target 义务: {[t.role for t in etok]}"
        assert len(inact[0][1].edge_ids) == 2, "令牌须携完整 edge 集（非 min）"
        return inact[0][2].blueprint.canonical_identity_hash

    # min edge 恒为 n01->n03；改**非最小** edge 的源（n02 → n02z）→ 聚合身份变。
    h_a = agg_hash("n02", "a")
    h_b = agg_hash("n02z", "b")
    assert h_a != h_b, "改非最小 edge 必须改聚合 bound 身份（旧 min(edge_ids) 丢其余身份）"


def test_probe3_fail_closed_scope_channel_method(tmp_path):
    """探针③（codex 阻断 2）：FR scope 错配 / channel 改串 / method node 缺失 三负测各 hard-fail。"""
    node = _gnode("n1", "submit")
    card_d = _full_card("RC.neg", nodes=[node])
    p = _write(tmp_path, [card_d])
    fcard = RuleCardDTO(**card_d)
    cat = CAT.build_identity_blueprint_catalog(
        p, make_rule_slice([fcard]), make_fact_pack([]), _META
    )
    idx = FactIndex(make_fact_pack([]))
    out = evaluate_obligation_node(
        fcard, ObligationNodeDTO.from_dict(dict(node)), idx, True, _META
    )

    # (a) FR scope 错配：token.scope_fid=FR-2 但义务/循环为 building → token_scope_mismatch。
    bad_scope = SourceToken("obligation_graph", "n1", "node", "FR-2")
    with pytest.raises(ObligationContractError, match="token_scope_mismatch"):
        BIND.bind_fanout_obligations(fcard, out[:1], [bad_scope], cat, None)

    # (b) channel 改串：role=node 但 channel=workflow_artifact → token_channel_mismatch。
    swapped = SourceToken("workflow_artifact", "n1", "node", None)
    with pytest.raises(ObligationContractError, match="token_channel_mismatch"):
        BIND.bind_fanout_obligations(fcard, out[:1], [swapped], cat, None)

    # (c) method node 缺失：role=method 指向卡中不存在 node → method_token_node_missing。
    missing = SourceToken("obligation_graph", "no_such_node", "method", None)
    with pytest.raises(ObligationContractError, match="method_token_node_missing"):
        BIND.bind_fanout_obligations(fcard, out[:1], [missing], cat, None)


def _write(tmp_path, cards):
    p = tmp_path / "rule_cards.json"
    p.write_text(json.dumps({"bundle_id": "B", "cards": cards}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_method_separable_vs_nonseparable_binding(tmp_path):
    """method 子义务：**可分** node（带 artifact_ids）→ 独立 method-derived 身份；
    **不可分** node（无 artifact/deadline）→ 折回 node-main 身份（同 hash）。"""
    # 可分 method node：action refine 到 method + 带 artifact_ids + 卡有 method_keys。
    sep_node = {
        "obligation_node_id": "n.sep", "node_kind": "obligation",
        "action": "select_repair_method",
        "actor": "a", "recipient_ids": [], "artifact_ids": ["A1"], "deadline_ids": [],
        "trigger_condition_ids": [],
    }
    # 不可分 method node：无 artifact/deadline。
    nonsep_node = {
        "obligation_node_id": "n.nonsep", "node_kind": "obligation",
        "action": "conduct_validation_test",
        "actor": "a", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
        "trigger_condition_ids": [],
    }
    art = {"artifact_id": "A1", "artifact_type": "form", "artifact_key": "form.mbi4"}
    card_d = _full_card(
        "RC.m", nodes=[sep_node, nonsep_node],
        method_keys=["*"], artifacts=[art],
    )
    p = _write(tmp_path, [card_d])
    fcard = RuleCardDTO(**card_d)
    rule_slice = make_rule_slice([fcard])
    fact_pack = make_fact_pack([])
    cat = CAT.build_identity_blueprint_catalog(p, rule_slice, fact_pack, _META)
    idx = FactIndex(fact_pack)

    # 可分 node：产 node-main + artifact 子 + method 子（method-derived 独立身份）。
    sep_tokens: List[SourceToken] = []
    sep_out = evaluate_obligation_node(
        fcard, ObligationNodeDTO.from_dict(dict(sep_node)), idx, True, _META,
        source_sink=sep_tokens,
    )
    assert len(sep_tokens) == len(sep_out)
    sep_bound = BIND.bind_fanout_obligations(fcard, sep_out, sep_tokens, cat, None)
    roles = [t.role for t in sep_tokens]
    assert "method" in roles and "artifact" in roles and "node" in roles
    # method 子的身份 != node-main 身份（可分 → 独立 method-derived）。
    node_main = next(b for b, t in zip(sep_bound, sep_tokens) if t.role == "node")
    method_sub = next(b for b, t in zip(sep_bound, sep_tokens) if t.role == "method")
    assert method_sub.blueprint.canonical_identity_hash != node_main.blueprint.canonical_identity_hash

    # 不可分 node：method 子折回 node-main 身份（同 hash）。
    ns_tokens: List[SourceToken] = []
    ns_out = evaluate_obligation_node(
        fcard, ObligationNodeDTO.from_dict(dict(nonsep_node)), idx, True, _META,
        source_sink=ns_tokens,
    )
    ns_bound = BIND.bind_fanout_obligations(fcard, ns_out, ns_tokens, cat, None)
    ns_node = next(b for b, t in zip(ns_bound, ns_tokens) if t.role == "node")
    ns_method = next(b for b, t in zip(ns_bound, ns_tokens) if t.role == "method")
    assert ns_method.blueprint.canonical_identity_hash == ns_node.blueprint.canonical_identity_hash


def test_token_contract_member_edge_ids_role_gated(tmp_path):
    """令牌契约收紧（codex 非阻断加固）：`member` 仅 edge_unknown、`edge_ids` 仅 edge_inactive；
    其它 role 携非空判别字段 → hard-fail（token_member_not_allowed / token_edge_ids_not_allowed）。"""
    from evo_agent_baseline.closure.blueprint_state_eval import token_source_item
    node = _gnode("n1", "submit")
    card_d = _full_card("RC.tok", nodes=[node])
    fcard = RuleCardDTO(**card_d)
    # node role 携 member → 炸。
    with pytest.raises(ObligationContractError, match="token_member_not_allowed"):
        token_source_item(
            fcard, SourceToken("obligation_graph", "n1", "node", None, member="source")
        )
    # node role 携 edge_ids → 炸。
    with pytest.raises(ObligationContractError, match="token_edge_ids_not_allowed"):
        token_source_item(
            fcard, SourceToken("obligation_graph", "n1", "node", None, edge_ids=("e1",))
        )
    # artifact role 携 member → 炸。
    with pytest.raises(ObligationContractError, match="token_member_not_allowed"):
        token_source_item(
            fcard, SourceToken("workflow_artifact", "A1", "artifact", None, member="x")
        )


def test_scope_mismatch_fr1_token_vs_fr2_loop(tmp_path):
    """scope 负测（codex 非阻断加固）：FR-1 义务 + FR-1 令牌 配 **FR-2 循环** scope → token_scope_mismatch
    （token/义务一致但与循环 scope 不符 → 绝不 fail-open 绑到错误 fragment 身份）。"""
    node = _gnode("n1", "submit")
    card_d = _full_card("RC.fr", nodes=[node])
    p = _write(tmp_path, [card_d])
    fcard = RuleCardDTO(**card_d)
    cat = CAT.build_identity_blueprint_catalog(
        p, make_rule_slice([fcard]), make_fact_pack([]), _META
    )
    idx = FactIndex(make_fact_pack([]))
    # 义务 fragment_id=FR-1（scope_meta 带 fragment_id）；令牌 scope_fid=FR-1（与义务一致）。
    fr1_meta = {**_META, "fragment_id": "FR-1"}
    out = evaluate_obligation_node(
        fcard, ObligationNodeDTO.from_dict(dict(node)), idx, True, fr1_meta
    )
    assert out[0].fragment_id == "FR-1"
    fr1_token = SourceToken("obligation_graph", "n1", "node", "FR-1")
    # 三者一致闸：token=FR-1 == obl=FR-1 != loop=FR-2 → hard-fail（不静默绑 FR-2 蓝图）。
    with pytest.raises(ObligationContractError, match="token_scope_mismatch"):
        BIND.bind_fanout_obligations(fcard, out[:1], [fr1_token], cat, "FR-2")


def test_bind_count_mismatch_hardfail(tmp_path):
    """token 数 != 义务数 → source_token_count_mismatch（不静默）。"""
    node = {
        "obligation_node_id": "n1", "node_kind": "obligation", "action": "submit",
        "actor": "a", "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
        "trigger_condition_ids": [],
    }
    card_d = _full_card("RC.x", nodes=[node])
    p = _write(tmp_path, [card_d])
    fcard = RuleCardDTO(**card_d)
    cat = CAT.build_identity_blueprint_catalog(
        p, make_rule_slice([fcard]), make_fact_pack([]), _META
    )
    idx = FactIndex(make_fact_pack([]))
    out = evaluate_obligation_node(
        fcard, ObligationNodeDTO.from_dict(dict(node)), idx, True, _META
    )
    with pytest.raises(ObligationContractError, match="source_token_count_mismatch"):
        BIND.bind_fanout_obligations(fcard, out, [], cat, None)  # 空 token 列表
