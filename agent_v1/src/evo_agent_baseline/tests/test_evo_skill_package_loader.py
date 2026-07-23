"""evo-agent v1 SkillPackage loader 测试（spec v1 §3.4 + §3.6 + §3.7 + §4.2 + §9.4.1 + §10）。

不依赖 Neo4j：覆盖
- skill.json schema 解析 valid / invalid（5 hard forbidden_actions 缺失）
- SKILL.md non-authority statement 解析
- plan.yaml 解析 + 禁止动作
- validation_records.jsonl 解析
- EvoSkillPackage 装配 + 4 sha256 + manifest_sha256
- Gate 0 静态安全（含 scope 含 building literal 反例 + verdict-like 反例）
- NodeSpec / GraphBatch 边数 / 边类型
- cypher_schema_evo：约束 ≥15 条、含 Skill.skill_id unique、含 SkillVersion / EvoRunTrace 主键约束
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from evo_agent_baseline.contracts import (
    EvoSkillPackage,
    SkillJson,
    SkillValidationRecord,
)
from evo_agent_baseline.evo.skill_package import (
    HARD_FORBIDDEN_ACTIONS,
    assert_skill_package_safe,
    load_skill_package,
    parse_plan_yaml,
    parse_skill_json,
    parse_skill_md_view,
    parse_validation_records,
)
from evo_agent_baseline.evo.skill_package_loader import (
    build_skill_node,
    build_skill_package_subgraph,
    build_skill_validation_record_node,
    build_skill_version_node,
)
from evo_agent_baseline.ingest import cypher_schema_evo
from evo_agent_baseline.ingest.guard import SecurityError


# ---------------------------------------------------------------------------
# fixtures：定位示范包目录
# ---------------------------------------------------------------------------

# tests/ → evo_agent_baseline/ → agent/skills_l1_examples/...
_EXAMPLE_PKG = (
    Path(__file__).resolve().parent.parent
    / "agent"
    / "skills_l1_examples"
    / "mbis-artifact-evidence-gap-v1"
)


@pytest.fixture(scope="module")
def example_pkg_dir() -> Path:
    assert _EXAMPLE_PKG.is_dir(), f"missing example package dir: {_EXAMPLE_PKG}"
    return _EXAMPLE_PKG


@pytest.fixture(scope="module")
def example_skill_json_dict(example_pkg_dir: Path) -> Dict[str, Any]:
    return json.loads((example_pkg_dir / "skill.json").read_text(encoding="utf-8"))


# ===========================================================================
# 1. skill.json schema valid
# ===========================================================================
def test_parse_skill_json_valid(example_pkg_dir: Path) -> None:
    skill = parse_skill_json(example_pkg_dir / "skill.json")
    assert isinstance(skill, SkillJson)
    assert skill.skill_id == "skill.mbis.retrieval_macro.artifact_evidence_gap"
    assert skill.skill_version_id == "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"
    assert skill.kind == "retrieval_macro"
    assert skill.layer == "L1_operational"
    assert skill.status == "active"
    # 5 hard forbidden_actions 全在
    for action in HARD_FORBIDDEN_ACTIONS:
        assert action in skill.forbidden_actions


# ===========================================================================
# 2. skill.json 缺 hard forbidden_actions → ValueError
# ===========================================================================
def test_parse_skill_json_missing_hard_forbidden_actions(
    tmp_path: Path, example_skill_json_dict: Dict[str, Any]
) -> None:
    bad = copy.deepcopy(example_skill_json_dict)
    # 故意删 emit_final_verdict 与 read_evaluator_truth（2 项 hard）
    bad["forbidden_actions"] = [
        a for a in bad["forbidden_actions"]
        if a not in {"emit_final_verdict", "read_evaluator_truth"}
    ]
    bad_path = tmp_path / "skill.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden_actions missing hard items"):
        parse_skill_json(bad_path)


# ===========================================================================
# 3. SKILL.md 无 non-authority statement → ValueError
# ===========================================================================
def test_parse_skill_md_view_missing_non_authority(tmp_path: Path) -> None:
    bad_md = tmp_path / "SKILL.md"
    bad_md.write_text(
        "# bad skill\n\n## Purpose\nDo a thing.\n\n## Trigger\nWhen X.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-authority"):
        parse_skill_md_view(bad_md)


def test_parse_skill_md_view_valid(example_pkg_dir: Path) -> None:
    text = parse_skill_md_view(example_pkg_dir / "SKILL.md")
    assert "artifact evidence gap retrieval macro" in text
    assert "non-authoritative" in text.lower() or "does not modify allow_stop" in text.lower()


# ===========================================================================
# 4. plan.yaml 解析 + 禁止动作反例
# ===========================================================================
def test_parse_plan_yaml_valid(example_pkg_dir: Path) -> None:
    plan = parse_plan_yaml(example_pkg_dir / "plan.yaml")
    assert plan["plan_id"] == "artifact_evidence_gap"
    assert isinstance(plan["steps"], list)
    assert len(plan["steps"]) == 3


def test_parse_plan_yaml_forbidden_action(tmp_path: Path) -> None:
    bad = tmp_path / "plan.yaml"
    bad.write_text(
        "plan_id: bad\nversion: 1\nsteps:\n  - step_id: s1\n    action: set_allow_stop\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbidden action"):
        parse_plan_yaml(bad)


# ===========================================================================
# 5. validation_records.jsonl 解析
# ===========================================================================
def test_parse_validation_records(example_pkg_dir: Path) -> None:
    recs = parse_validation_records(example_pkg_dir / "validation_records.jsonl")
    assert len(recs) == 3
    stages = {r.validation_stage for r in recs}
    assert stages == {"gate0_static", "gate1_schema_provenance", "gate2_replay_ab"}
    for r in recs:
        assert isinstance(r, SkillValidationRecord)
        assert r.passed is True
        assert r.leakage_hits == []
        assert r.closure_regression_count == 0
        assert r.allow_stop_authority_check is True


# ===========================================================================
# 6. load_skill_package on 示范 dir → 4 sha256 + manifest_sha256
# ===========================================================================
def test_load_skill_package_example(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    assert isinstance(pkg, EvoSkillPackage)
    assert pkg.package_schema_version == "1.0.0"
    assert pkg.package_sha256.startswith("sha256:")
    assert pkg.skill_md_sha256.startswith("sha256:")
    assert pkg.plan_yaml_sha256 is not None  # retrieval_macro 必有
    assert pkg.plan_yaml_sha256.startswith("sha256:")
    assert pkg.validation_records_sha256.startswith("sha256:")
    assert pkg.manifest_sha256.startswith("sha256:")
    # 4 sha 都不同
    shas = {
        pkg.package_sha256,
        pkg.skill_md_sha256,
        pkg.plan_yaml_sha256,
        pkg.validation_records_sha256,
        pkg.manifest_sha256,
    }
    assert len(shas) == 5


def test_load_skill_package_micro_routing_missing_plan_yaml_fails(
    tmp_path: Path, example_skill_json_dict: Dict[str, Any]
) -> None:
    """micro_routing / retrieval_macro 缺 plan.yaml 必须 hard fail（spec v1 §4.2.1）。"""
    bad_skill = copy.deepcopy(example_skill_json_dict)
    bad_skill["kind"] = "micro_routing"
    (tmp_path / "skill.json").write_text(json.dumps(bad_skill), encoding="utf-8")
    (tmp_path / "SKILL.md").write_text(
        "# x\nThis skill is non-authoritative; it does not modify allow_stop.\n",
        encoding="utf-8",
    )
    (tmp_path / "validation_records.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="requires plan.yaml"):
        load_skill_package(tmp_path)


# ===========================================================================
# 7. assert_skill_package_safe on 示范 → pass
# ===========================================================================
def test_assert_skill_package_safe_example(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    skill_md = (example_pkg_dir / "SKILL.md").read_text(encoding="utf-8")
    plan_yaml = (example_pkg_dir / "plan.yaml").read_text(encoding="utf-8")
    # 不抛即通过
    assert_skill_package_safe(pkg, skill_md_text=skill_md, plan_yaml_text=plan_yaml)


# ===========================================================================
# 8. assert_skill_package_safe scope 含 building literal → SecurityError
# ===========================================================================
def test_assert_skill_package_safe_building_literal_in_scope(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    # 篡改 scope.rule_families：注入 building_0012 literal
    mutated_skill = pkg.skill.model_copy(deep=True)
    mutated_skill.scope.rule_families = list(mutated_skill.scope.rule_families) + ["building_0012.special"]
    mutated_pkg = pkg.model_copy(update={"skill": mutated_skill})
    with pytest.raises(SecurityError, match="building_"):
        assert_skill_package_safe(mutated_pkg)


# ===========================================================================
# 9. assert_skill_package_safe verdict-like phrase 反例 → SecurityError
# ===========================================================================
def test_assert_skill_package_safe_verdict_phrase_in_description(
    example_pkg_dir: Path,
) -> None:
    pkg = load_skill_package(example_pkg_dir)
    # 注入"最终裁决"到 description
    mutated_skill = pkg.skill.model_copy(deep=True)
    mutated_skill.description = mutated_skill.description + " 给出最终裁决。"
    mutated_pkg = pkg.model_copy(update={"skill": mutated_skill})
    with pytest.raises(SecurityError, match="最终裁决"):
        assert_skill_package_safe(mutated_pkg)


# ===========================================================================
# 10. build_skill_node / build_skill_version_node / build_skill_validation_record_node
# ===========================================================================
def test_build_skill_node_fields(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    node = build_skill_node(pkg.skill)
    assert node.label == "Skill"
    assert node.key_prop == "skill_id"
    assert node.key_value == "skill.mbis.retrieval_macro.artifact_evidence_gap"
    assert node.props["name"] == "artifact evidence gap retrieval macro"
    assert node.props["kind"] == "retrieval_macro"
    assert node.props["layer"] == "L1_operational"
    # status="active" → active_version_id == skill_version_id
    assert node.props["active_version_id"] == "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"
    assert node.props["latest_version_id"] == "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"


def test_build_skill_version_node_fields(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    node = build_skill_version_node(pkg.skill)
    assert node.label == "SkillVersion"
    assert node.key_prop == "skill_version_id"
    assert node.key_value == "skill.mbis.retrieval_macro.artifact_evidence_gap.v1"
    assert node.props["skill_id"] == "skill.mbis.retrieval_macro.artifact_evidence_gap"
    assert node.props["status"] == "active"
    assert node.props["rulecard_bundle_id"] == "rulecard_v2.mbis_cop_2023"
    assert node.props["kg_snapshot_id"] == "KGS-v1-20260523"
    # leakage / closure 来自 validation_summary
    assert node.props["leakage_audit_passed"] is True
    assert node.props["closure_non_regression_passed"] is True
    # support_counts
    assert node.props["support_building_count"] == 3
    assert node.props["support_world_family_count"] == 2
    assert len(node.props["source_trace_hashes"]) == 5
    # 5 hard forbidden 全保留
    for a in HARD_FORBIDDEN_ACTIONS:
        assert a in node.props["forbidden_actions"]


def test_build_skill_validation_record_node(example_pkg_dir: Path) -> None:
    recs = parse_validation_records(example_pkg_dir / "validation_records.jsonl")
    node = build_skill_validation_record_node(recs[0])
    assert node.label == "SkillValidationRecord"
    assert node.key_prop == "validation_id"
    assert node.props["validation_stage"] == "gate0_static"
    assert node.props["passed"] is True


# ===========================================================================
# 11. build_skill_package_subgraph 边数与节点数
# ===========================================================================
def test_build_skill_package_subgraph_counts(example_pkg_dir: Path) -> None:
    pkg = load_skill_package(example_pkg_dir)
    recs = parse_validation_records(example_pkg_dir / "validation_records.jsonl")
    batch = build_skill_package_subgraph(pkg, recs)

    # 节点：1 Skill + 1 SkillVersion + 3 SkillValidationRecord = 5
    assert len(batch.nodes) == 5
    labels = sorted([n.label for n in batch.nodes])
    assert labels == ["Skill", "SkillValidationRecord", "SkillValidationRecord",
                      "SkillValidationRecord", "SkillVersion"]
    # 边：1 HAS_VERSION + 3 VALIDATED_BY = 4
    assert len(batch.edges) == 4
    rel_types = sorted([e.rel_type for e in batch.edges])
    assert rel_types == ["HAS_VERSION", "VALIDATED_BY", "VALIDATED_BY", "VALIDATED_BY"]


# ===========================================================================
# 12. cypher_schema_evo：约束数 ≥15、含 Skill.skill_id unique constraint
# ===========================================================================
def test_cypher_schema_evo_constraint_count() -> None:
    """spec v1 §3.4 + §3.6：v1 evo namespace 至少 15 条约束 + 索引合计 ≥15。"""
    statements = cypher_schema_evo.all_evo_schema_statements()
    assert len(statements) >= 15, f"got {len(statements)} statements"
    # 约束数本身要求
    assert len(cypher_schema_evo.EVO_CONSTRAINTS) >= 15, (
        f"got {len(cypher_schema_evo.EVO_CONSTRAINTS)} constraints"
    )


def test_cypher_schema_evo_contains_skill_id_unique() -> None:
    """spec v1 §3.4.2：Skill.skill_id 必须 UNIQUE。"""
    stmts = cypher_schema_evo.all_evo_schema_statements()
    found = any(
        "Skill" in s and "skill_id" in s and "UNIQUE" in s
        for s in stmts
    )
    assert found, "missing Skill.skill_id UNIQUE constraint"


def test_cypher_schema_evo_contains_skill_version_unique() -> None:
    """spec v1 §3.4.3 / §3.7：SkillVersion.skill_version_id 必须 UNIQUE。"""
    stmts = cypher_schema_evo.all_evo_schema_statements()
    found = any(
        "SkillVersion" in s and "skill_version_id" in s and "UNIQUE" in s
        for s in stmts
    )
    assert found, "missing SkillVersion.skill_version_id UNIQUE constraint"


def test_cypher_schema_evo_contains_core_evo_nodes() -> None:
    """spec v1 §3.6 / §3.7：EvoRunTrace / EvoPolicyVersion / SanitizedFeedbackPacket
    / ReplayCase / FeedbackCell / EvoReleaseCard 主键 UNIQUE。"""
    stmts_joined = " ".join(cypher_schema_evo.all_evo_schema_statements())
    for label, key in [
        ("EvoRunTrace", "trace_id"),
        ("EvoPolicyVersion", "policy_version_id"),
        ("SanitizedFeedbackPacket", "feedback_packet_id"),
        ("ReplayCase", "replay_case_id"),
        ("FeedbackCell", "feedback_cell_id"),
        ("EvoReleaseCard", "release_card_id"),
        ("SkillActivation", "activation_id"),
        ("SkillValidationRecord", "validation_id"),
    ]:
        assert label in stmts_joined and key in stmts_joined, (
            f"missing {label}.{key} UNIQUE"
        )


def test_cypher_schema_evo_indexes_have_expected_keys() -> None:
    """spec v1 §3.7：必须含 skill_scope_family / replay_split_eligibility /
    feedback_packet_window 三条核心索引。"""
    stmts = cypher_schema_evo.all_evo_schema_statements()
    joined = " ".join(stmts)
    assert "skill_scope_family" in joined
    assert "replay_split_eligibility" in joined
    assert "feedback_packet_window" in joined


def test_cypher_schema_evo_all_idempotent() -> None:
    """spec §4.2.3：所有 DDL 都带 IF NOT EXISTS。"""
    for stmt in cypher_schema_evo.all_evo_schema_statements():
        assert "IF NOT EXISTS" in stmt, f"DDL 缺 IF NOT EXISTS: {stmt}"


def test_cypher_schema_evo_relationship_types_listed() -> None:
    """spec v1 §3.5：清单含 APPLIES_TO / TARGETS / ACTIVATES / VALIDATED_BY /
    SUPERSEDES / LOADED_BY_POLICY 等关键边类型。"""
    rels = set(cypher_schema_evo.EVO_RELATIONSHIP_TYPES)
    expected = {
        "APPLIES_TO",
        "TARGETS",
        "ACTIVATES",
        "VALIDATED_BY",
        "SUPERSEDES",
        "LOADED_BY_POLICY",
        "HAS_VERSION",
    }
    missing = expected - rels
    assert not missing, f"missing rel types: {missing}"
