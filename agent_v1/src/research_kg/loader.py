"""DualSourceResearchKG minimal loader.

Reads the dual-source research KG seed files, validates structure,
and outputs a summary (dict or console).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from research_kg.regulation_corpus import RegulationCorpus, load_regulation_corpus


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_node(node: dict, idx: int, side: str) -> None:
    for key in ("node_id", "node_type", "label"):
        if key not in node:
            raise ValueError(f"{side} nodes[{idx}] missing required key: {key}")


def _validate_edge(edge: dict, idx: int, side: str, node_ids: Set[str]) -> None:
    for key in ("edge_id", "edge_type", "source", "target"):
        if key not in edge:
            raise ValueError(f"{side} edges[{idx}] missing required key: {key}")
    if edge["source"] not in node_ids:
        raise ValueError(
            f"{side} edges[{idx}] source '{edge['source']}' not found in nodes"
        )
    if edge["target"] not in node_ids:
        raise ValueError(
            f"{side} edges[{idx}] target '{edge['target']}' not found in nodes"
        )


def _validate_manifest(manifest: dict, side: str) -> None:
    for key in ("graph_name", "version", "node_types", "edge_types", "seed_files"):
        if key not in manifest:
            raise ValueError(f"{side} manifest missing required key: {key}")
    sf = manifest["seed_files"]
    for key in ("nodes", "edges"):
        if key not in sf:
            raise ValueError(f"{side} manifest.seed_files missing key: {key}")


# ---------------------------------------------------------------------------
# Single-side loader
# ---------------------------------------------------------------------------

class SubgraphSeed:
    """Loaded seed for one side of the dual-source KG."""

    def __init__(
        self,
        manifest: dict,
        nodes: List[dict],
        edges: List[dict],
        side: str,
    ) -> None:
        self.manifest = manifest
        self.nodes = nodes
        self.edges = edges
        self.side = side

    @property
    def graph_name(self) -> str:
        return self.manifest["graph_name"]

    @property
    def node_types(self) -> List[str]:
        return sorted({n["node_type"] for n in self.nodes})

    @property
    def edge_types(self) -> List[str]:
        return sorted({e["edge_type"] for e in self.edges})

    def summary(self) -> Dict[str, Any]:
        return {
            "graph_name": self.graph_name,
            "version": self.manifest["version"],
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_types": self.node_types,
            "edge_types": self.edge_types,
        }


def load_subgraph(base_dir: Path, side: str) -> SubgraphSeed:
    """Load and validate one side of the KG from *base_dir*."""
    manifest_path = base_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    _validate_manifest(manifest, side)

    nodes_path = base_dir / manifest["seed_files"]["nodes"]
    edges_path = base_dir / manifest["seed_files"]["edges"]

    nodes: List[dict] = _load_json(nodes_path)
    edges: List[dict] = _load_json(edges_path)

    if not isinstance(nodes, list):
        raise ValueError(f"{side} nodes file must be a JSON array")
    if not isinstance(edges, list):
        raise ValueError(f"{side} edges file must be a JSON array")

    node_ids: Set[str] = set()
    for idx, node in enumerate(nodes):
        _validate_node(node, idx, side)
        if node["node_id"] in node_ids:
            raise ValueError(f"{side} duplicate node_id: {node['node_id']}")
        node_ids.add(node["node_id"])

    edge_ids: Set[str] = set()
    for idx, edge in enumerate(edges):
        _validate_edge(edge, idx, side, node_ids)
        if edge["edge_id"] in edge_ids:
            raise ValueError(f"{side} duplicate edge_id: {edge['edge_id']}")
        edge_ids.add(edge["edge_id"])

    # Check declared node/edge types vs actual
    declared_node_types = set(manifest["node_types"])
    actual_node_types = {n["node_type"] for n in nodes}
    if not actual_node_types.issubset(declared_node_types):
        extra = actual_node_types - declared_node_types
        raise ValueError(f"{side} undeclared node_types in seed: {extra}")

    declared_edge_types = set(manifest["edge_types"])
    actual_edge_types = {e["edge_type"] for e in edges}
    if not actual_edge_types.issubset(declared_edge_types):
        extra = actual_edge_types - declared_edge_types
        raise ValueError(f"{side} undeclared edge_types in seed: {extra}")

    return SubgraphSeed(manifest=manifest, nodes=nodes, edges=edges, side=side)


# ---------------------------------------------------------------------------
# Dual-source loader
# ---------------------------------------------------------------------------

class DualSourceResearchKG:
    """Top-level handle for the loaded dual-source research KG."""

    def __init__(
        self,
        top_manifest: dict,
        building_fact: SubgraphSeed,
        rule_skill: SubgraphSeed,
        regulation_corpus: Optional[RegulationCorpus] = None,
    ) -> None:
        self.top_manifest = top_manifest
        self.building_fact = building_fact
        self.rule_skill = rule_skill
        self.regulation_corpus = regulation_corpus

    def summary(self) -> Dict[str, Any]:
        bf = self.building_fact.summary()
        rs = self.rule_skill.summary()
        chains = self.top_manifest.get("mainline_chains", {})
        summary = {
            "graph_name": self.top_manifest["graph_name"],
            "version": self.top_manifest["version"],
            "building_fact_kg": bf,
            "rule_skill_kg": rs,
            "bridge_nodes": self.top_manifest.get("bridge_nodes", []),
            "mainline_chains": {
                k: v["description"] for k, v in chains.items()
            },
            "total_nodes": bf["node_count"] + rs["node_count"],
            "total_edges": bf["edge_count"] + rs["edge_count"],
        }
        if self.regulation_corpus is not None:
            summary["regulation_corpus"] = self.regulation_corpus.summary()
            summary["regulation_bridge"] = self.top_manifest.get("regulation_bridge", {})
        return summary


def _resolve_external_asset_path(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    if candidate.exists():
        return candidate
    project_root = Path(__file__).resolve().parents[2]
    normalized_parts = [part for part in Path(relative_path).parts if part not in (".", "..")]
    fallback = project_root.joinpath(*normalized_parts).resolve()
    if fallback.exists():
        return fallback
    return candidate


def load_dual_source_kg(research_kg_dir: Path) -> DualSourceResearchKG:
    """Load, validate, and return the full dual-source research KG."""
    manifest_path = research_kg_dir / "manifest.json"
    top_manifest = _load_json(manifest_path)
    base_dir = manifest_path.parent

    for key in ("graph_name", "version", "subgraphs"):
        if key not in top_manifest:
            raise ValueError(f"Top manifest missing required key: {key}")

    subgraphs = top_manifest["subgraphs"]
    if "building_fact_kg" not in subgraphs or "rule_skill_kg" not in subgraphs:
        raise ValueError("Top manifest must declare building_fact_kg and rule_skill_kg subgraphs")

    bf_dir = base_dir / Path(subgraphs["building_fact_kg"]["path"]).parent
    rs_dir = base_dir / Path(subgraphs["rule_skill_kg"]["path"]).parent

    building_fact = load_subgraph(bf_dir, "BuildingFactKG")
    rule_skill = load_subgraph(rs_dir, "RuleSkillKG")
    regulation_corpus = None
    regulation_cfg = top_manifest.get("regulation_corpus")
    if regulation_cfg:
        if "path" not in regulation_cfg:
            raise ValueError("Top manifest regulation_corpus missing required key: path")
        regulation_corpus = load_regulation_corpus(
            _resolve_external_asset_path(base_dir, regulation_cfg["path"])
        )

    # Validate bridge nodes exist on both sides
    bridge_nodes = set(top_manifest.get("bridge_nodes", []))
    if bridge_nodes:
        bf_ids = {n["node_id"] for n in building_fact.nodes}
        rs_ids = {n["node_id"] for n in rule_skill.nodes}
        for bid in bridge_nodes:
            if bid not in bf_ids:
                raise ValueError(f"Bridge node '{bid}' not found in BuildingFactKG")
            if bid not in rs_ids:
                raise ValueError(f"Bridge node '{bid}' not found in RuleSkillKG")

    return DualSourceResearchKG(
        top_manifest=top_manifest,
        building_fact=building_fact,
        rule_skill=rule_skill,
        regulation_corpus=regulation_corpus,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import sys

    if len(sys.argv) > 1:
        kg_dir = Path(sys.argv[1])
    else:
        kg_dir = Path(__file__).resolve().parent.parent.parent / "research_kg"

    kg = load_dual_source_kg(kg_dir)
    summary = kg.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
