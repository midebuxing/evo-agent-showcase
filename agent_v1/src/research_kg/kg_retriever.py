"""KG Retriever - minimal retrieval from the local DualSourceResearchKG."""
from __future__ import annotations

import re
from typing import List, Sequence

from research_kg.loader import DualSourceResearchKG


# ---------------------------------------------------------------------------
# Chain detection keywords
# ---------------------------------------------------------------------------

_CRACK_KEYWORDS = re.compile(
    r"裂缝|裂纹|crack|crack_width|缝宽",
    re.IGNORECASE,
)
_REBAR_SPALL_KEYWORDS = re.compile(
    r"钢筋|外露|露筋|剥落|spall|rebar|脱落|混凝土剥|spalling",
    re.IGNORECASE,
)


class RetrievalResult:
    """Result of one KG retrieval."""

    def __init__(
        self,
        matched_chain: str,
        rule_cards: List[dict],
        skills: List[dict],
        triggers: List[dict],
        fact_patterns: List[dict],
        fact_features: List[dict],
    ) -> None:
        self.matched_chain = matched_chain
        self.rule_cards = rule_cards
        self.skills = skills
        self.triggers = triggers
        self.fact_patterns = fact_patterns
        self.fact_features = fact_features

    def filter_rule_cards(self, selected_ids: List[str]) -> "RetrievalResult":
        id_set = set(selected_ids)
        filtered = [rc for rc in self.rule_cards if rc["node_id"] in id_set]
        return RetrievalResult(
            matched_chain=self.matched_chain,
            rule_cards=filtered,
            skills=self.skills,
            triggers=self.triggers,
            fact_patterns=self.fact_patterns,
            fact_features=self.fact_features,
        )

    def summary(self) -> dict:
        return {
            "matched_chain": self.matched_chain,
            "rule_card_ids": [rc["node_id"] for rc in self.rule_cards],
            "skill_ids": [sk["node_id"] for sk in self.skills],
            "trigger_ids": [tr["node_id"] for tr in self.triggers],
            "fact_pattern_ids": [fp["node_id"] for fp in self.fact_patterns],
        }


def _nodes_by_ids(nodes: List[dict], ids: Sequence[str]) -> List[dict]:
    id_set = set(ids)
    return [n for n in nodes if n["node_id"] in id_set]


def _collect_graph_skill_ids(
    *,
    nodes: List[dict],
    edges: List[dict],
    chain: str,
) -> List[str]:
    chain_aliases = {chain}
    if chain == "unknown":
        chain_aliases.add("unknown_chain")
    chain_node_ids = {
        node["node_id"]
        for node in nodes
        if node["node_type"] == "Chain"
        and (
            node.get("properties", {}).get("chain_id") in chain_aliases
            or node["node_id"] in {f"CHAIN-{alias}" for alias in chain_aliases}
        )
    }
    return sorted(
        {
            edge["target"]
            for edge in edges
            if edge["edge_type"] == "CHAIN_HAS_SKILL"
            and edge["source"] in chain_node_ids
        }
    )


def detect_chain(query: str) -> str:
    """Detect which mainline chain the query belongs to."""
    has_crack = bool(_CRACK_KEYWORDS.search(query))
    has_rebar_spall = bool(_REBAR_SPALL_KEYWORDS.search(query))

    if has_rebar_spall:
        return "rebar_spall_chain"
    if has_crack:
        return "crack_chain"
    return "unknown"


def retrieve_from_kg(
    kg: DualSourceResearchKG,
    query: str,
) -> RetrievalResult:
    """Retrieve the minimal Rule/Skill/Trigger set for a detected chain."""
    chain = detect_chain(query)
    chains = kg.top_manifest.get("mainline_chains", {})
    rs_nodes = kg.rule_skill.nodes
    rs_edges = kg.rule_skill.edges
    bf_nodes = kg.building_fact.nodes
    graph_skill_ids = _collect_graph_skill_ids(nodes=rs_nodes, edges=rs_edges, chain=chain)

    if chain not in chains:
        return RetrievalResult(
            matched_chain=chain,
            rule_cards=[],
            skills=_nodes_by_ids(rs_nodes, graph_skill_ids),
            triggers=[],
            fact_patterns=[],
            fact_features=[],
        )

    chain_def = chains[chain]
    rule_card_ids = chain_def.get("rule_cards", [])
    skill_id = chain_def.get("skill")
    trigger_id = chain_def.get("trigger")
    fp_id = chain_def.get("fact_pattern")

    rule_cards = _nodes_by_ids(rs_nodes, rule_card_ids)
    skill_ids = sorted(set(([skill_id] if skill_id else []) + graph_skill_ids))
    skills = _nodes_by_ids(rs_nodes, skill_ids)
    triggers = _nodes_by_ids(rs_nodes, [trigger_id] if trigger_id else [])
    fact_patterns = _nodes_by_ids(rs_nodes, [fp_id] if fp_id else [])

    trigger_node = triggers[0] if triggers else None
    feature_ids: List[str] = []
    if trigger_node:
        feature_ids = trigger_node.get("properties", {}).get("required_feature_ids", [])
    fact_features = _nodes_by_ids(bf_nodes, feature_ids)

    return RetrievalResult(
        matched_chain=chain,
        rule_cards=rule_cards,
        skills=skills,
        triggers=triggers,
        fact_patterns=fact_patterns,
        fact_features=fact_features,
    )
