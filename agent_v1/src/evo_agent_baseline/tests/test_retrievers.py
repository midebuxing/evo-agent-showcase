"""Fact / Rule KG-RAG 检索器测试（spec §5.3 + §5.4）。

不依赖 Neo4j：用 FakeNeo4jClient 喂预置查询结果，验证检索编排、
§5.4.4 排序打分、verifier 候选集选取、FactPack / RuleSlice 装配。
"""

from __future__ import annotations

from typing import Any, Dict, List

from evo_agent_baseline.contracts import FactPack, RuleSlice
from evo_agent_baseline.kg import queries
from evo_agent_baseline.retrieval import fact_retriever, rule_retriever
from evo_agent_baseline.retrieval.rule_retriever import CandidateSignals


class FakeNeo4jClient:
    """假 Neo4j 客户端：按 Cypher 字符串匹配返回预置结果。

    不连真实 Neo4j；只供检索器单测用。
    """

    def __init__(self, responses: Dict[str, List[Dict[str, Any]]]) -> None:
        """responses: Cypher 查询字符串 → 结果 record dict 列表。"""
        self._responses = responses

    def read(self, cypher: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """返回该 Cypher 的预置结果，未注册的返回空列表。"""
        return self._responses.get(cypher, [])


# ===========================================================================
# §5.4.4 排序打分
# ===========================================================================
def test_candidate_signals_score_formula() -> None:
    """CandidateSignals.score 严格按 §5.4.4 公式。"""
    sig = CandidateSignals(
        rule_card_id="rc.1",
        exact_slot_hit_count=2,            # 2 * 5.0 = 10
        exact_measure_hit_count=1,         # 1 * 4.0 = 4
        applicability_match_count=1,       # 1 * 2.0 = 2
        source_clause_fulltext_score=2.0,  # 2.0 * 1.5 = 3
        neighbor_family_hit_count=1,       # 1 * 1.0 = 1
        explicit_exclusion_match_count=1,  # 1 * -3.0 = -3
    )
    assert sig.score() == 10 + 4 + 2 + 3 + 1 - 3


def test_rank_candidates_descending() -> None:
    """rank_candidates 按分数降序、同分按 id 升序。"""
    signals = {
        "rc.b": CandidateSignals("rc.b", exact_slot_hit_count=1),  # 5.0
        "rc.a": CandidateSignals("rc.a", exact_slot_hit_count=2),  # 10.0
        "rc.c": CandidateSignals("rc.c", exact_slot_hit_count=1),  # 5.0
    }
    ranked = rule_retriever.rank_candidates(signals)
    assert ranked[0][0] == "rc.a"  # 最高分
    # 同分 5.0：rc.b、rc.c 按 id 升序。
    assert [cid for cid, _ in ranked[1:]] == ["rc.b", "rc.c"]


def test_select_verifier_candidates_score_gt_0() -> None:
    """verifier 候选集 = score>0 且未明确排除（spec §5.4.4）。"""
    signals = {
        "rc.hit": CandidateSignals("rc.hit", exact_slot_hit_count=1),     # 5.0 > 0
        "rc.zero": CandidateSignals("rc.zero"),                            # 0.0
        "rc.excluded": CandidateSignals(
            "rc.excluded", exact_slot_hit_count=2,
            explicit_exclusion_match_count=1,                              # 明确排除
        ),
    }
    selected = rule_retriever.select_verifier_candidates(signals)
    assert selected == ["rc.hit"]   # zero 与 excluded 都剔除


# ===========================================================================
# Fact KG-RAG 检索器
# ===========================================================================
def test_facts_from_raw_basic() -> None:
    """facts_from_raw 把承载节点字段展为 FactAtom。"""
    raw = fact_retriever.FactRetrievalRaw()
    raw.world = {"world_id": "WB-1"}
    raw.building = {"building_id": "BLD-1", "building_use": "industrial",
                    "storey_count": 16}
    raw.measurements = [{
        "measurement_id": "MSR-1", "slot_id": "test.slot",
        "value_json": "0.5", "qualifiers_json": "{}",
    }]
    atoms = fact_retriever.facts_from_raw(raw)
    # building_use + storey_count + measurement = 3 facts。
    fact_ids = {a.fact_id for a in atoms}
    assert "BLD-1::building_use" in fact_ids
    assert "BLD-1::storey_count" in fact_ids
    assert "MSR-1" in fact_ids


def test_retrieve_fact_pack_with_fake_client() -> None:
    """retrieve_fact_pack 端到端（FakeNeo4jClient）→ FactPack。"""
    responses = {
        queries.FACT_BUILDING_SHELL: [{
            "world": {"world_id": "WB-1"},
            "building": {"building_id": "BLD-1", "building_use": "industrial"},
        }],
        queries.FACT_FRAGMENT_SUBGRAPH: [{
            "fragment": {"fragment_id": "FRG-1", "fragment_role": "facade"},
            "component": None, "location": None,
        }],
        queries.FACT_SIDECAR_ENTRIES: [{
            "runtime_id": "SCR-1",
            "sidecar_entry": {
                "sidecar_entry_id": "SCR-1::facts::0", "slot_id": "qual.x",
                "value_json": "true", "qualifiers_json": "{}",
            },
        }],
    }
    client = FakeNeo4jClient(responses)
    pack = fact_retriever.retrieve_fact_pack(client, "RUN-1", "BLD-1")
    assert isinstance(pack, FactPack)
    assert pack.world_id == "WB-1"
    assert pack.building_id == "BLD-1"
    # building_use + fragment_role + sidecar entry 都成 fact。
    assert len(pack.facts) >= 3
    assert "qual.x" in pack.slot_index


# ===========================================================================
# Rule KG-RAG 检索器
# ===========================================================================
def test_collect_candidate_signals() -> None:
    """collect_candidate_signals 汇总 slot / measure / applicability 命中。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={"slot.a": ["F1"]}, measure_index={"measure.x": ["F2"]},
        carrier_index={}, source_tables=[],
    )
    responses = {
        queries.RULE_SLOT_DRIVEN_CARDS: [
            {"rule_card_id": "rc.1", "slot_hits": 2},
        ],
        queries.RULE_MEASURE_DRIVEN_CARDS: [
            {"rule_card_id": "rc.1", "threshold_hits": 1},
        ],
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [
            {"rule_card_id": "rc.1", "family_id": "fam.1"},
        ],
    }
    client = FakeNeo4jClient(responses)
    signals = rule_retriever.collect_candidate_signals(
        client, pack, regime="mbis", building_scope_tags=["tag1"]
    )
    sig = signals["rc.1"]
    assert sig.exact_slot_hit_count == 2
    assert sig.exact_measure_hit_count == 1
    assert sig.applicability_match_count == 1


def test_retrieve_rule_slice_end_to_end() -> None:
    """retrieve_rule_slice 端到端（FakeNeo4jClient）→ RuleSlice。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={"procedure.x": ["F1"]}, measure_index={},
        carrier_index={}, source_tables=[],
    )
    expansion_row = {
        "rule_card": {
            "rule_card_id": "rc.1", "source_document_id": "MBIS_CoP_2023",
            "normalized_rule_text": "t", "family_id": "fam.1",
            "primary_actor": "ri", "primary_action": "submit",
            "method_keys_allowed": [], "neighbor_families": [],
            "version_authoring_revision": "1.0.0",
            "version_interpretation_revision": 1, "provenance_json": "{}",
        },
        "applicabilities": [], "trigger_conditions": [], "slot_refs": [],
        "thresholds": [], "measures": [], "time_anchors": [],
        "evidence_requirements": [], "obligation_nodes": [], "obligation_edges": [],
        "workflow_artifacts": [], "workflow_deadlines": [], "workflow_recipients": [],
        "source_quotes": [], "artifacts": [],
    }
    responses = {
        queries.RULE_SLOT_DRIVEN_CARDS: [{"rule_card_id": "rc.1", "slot_hits": 1}],
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [],
        queries.RULE_GRAPH_EXPANSION: [expansion_row],
        queries.RULE_FAMILIES_BY_ID: [
            {"rule_family": {"family_id": "fam.1", "family_name": "Fam One"}},
        ],
    }
    client = FakeNeo4jClient(responses)
    rule_slice = rule_retriever.retrieve_rule_slice(
        client, "RUN-1", pack, "bundle-1", regime="mbis",
    )
    assert isinstance(rule_slice, RuleSlice)
    assert len(rule_slice.candidate_rule_cards) == 1
    assert rule_slice.candidate_rule_cards[0].rule_card_id == "rc.1"
    assert len(rule_slice.rule_families) == 1
    # §5.4.4：retrieval_policy 必须记录 cutoff policy。
    assert "candidate_cutoff_policy" in rule_slice.retrieval_policy
    assert "score_weights" in rule_slice.retrieval_policy


def test_retrieve_rule_slice_excludes_zero_score() -> None:
    """score=0 的卡不进 verifier 候选集，也不出现在 RuleSlice（§5.4.4）。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={}, measure_index={}, carrier_index={}, source_tables=[],
    )
    # applicability 命中但 0 hit 的卡：applicability_match_count=1 → score=2.0>0。
    # 这里构造一张完全无命中的场景：无 slot / measure / applicability。
    responses = {
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [],
        queries.RULE_GRAPH_EXPANSION: [],
    }
    client = FakeNeo4jClient(responses)
    rule_slice = rule_retriever.retrieve_rule_slice(
        client, "RUN-1", pack, "bundle-1",
    )
    assert rule_slice.candidate_rule_cards == []
    assert rule_slice.retrieval_policy["verifier_candidate_count"] == 0
