"""技能→法规 嵌边 loader 测试（rule-skills-kg-rag 嵌边落地）。

不依赖 Neo4j：用 mock 客户端验证
- scope 6 维 → 边类型 → 目标节点 映射表（5 嵌边 + obligation_kinds 不挂边）
- SkillJson 输入 → 正确的 EdgeSpec（起点 SkillVersion）
- 库内 record 输入：结构化 scope_* / 自由文本恢复 family_id / 空 scope 三路径
- 编译语句用 MERGE（幂等）+ MATCH 两端（防孤儿）
- dry_run 按边类型分计 would_create / missing_target，且只读不写
- load_skill_edges 跳过目标缺失的边、写入剩余
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from evo_agent_baseline.contracts import SkillJson, SkillScope
from evo_agent_baseline.ingest.skill_edge_loader import (
    SCOPE_EDGE_RULES,
    SCOPE_NON_EDGE_FIELDS,
    SkillScopeRef,
    build_skill_edge_batch,
    build_skill_edges,
    dry_run_skill_edges,
    format_dry_run_report,
    from_kg_record,
    from_skill_json,
    load_skill_edges,
)


# ===========================================================================
# mock 客户端
# ===========================================================================
class MockClient:
    """记录 read / write 调用的假桩客户端。

    `existing` 是「存在的法规节点集合」(label, key_value)；`read` 据此回 count。
    `write_many` 把收到的语句存入 `written`，绝不真连库。
    """

    def __init__(self, existing: set) -> None:
        self.existing = existing
        self.read_calls: List[Tuple[str, Dict[str, Any]]] = []
        self.written: List[Tuple[str, Dict[str, Any]]] = []

    def read(self, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.read_calls.append((cypher, params))
        # 从 cypher 抽 label（MATCH (n:Label {...）
        label = cypher.split(":", 1)[1].split(" ", 1)[0]
        val = params.get("val")
        return [{"c": 1 if (label, val) in self.existing else 0}]

    def write_many(self, statements: Any, batch_size: int = 500) -> None:
        self.written.extend(list(statements))


# ===========================================================================
# fixtures
# ===========================================================================
def _make_skill_json(**scope_kwargs: Any) -> SkillJson:
    """造一个最小合法 SkillJson，只关心 scope。"""
    return SkillJson(
        schema_version="1.0.0",
        skill_id="skill.test.macro.demo",
        skill_version_id="skill.test.macro.demo.v1",
        name="demo",
        kind="retrieval_macro",
        layer="L1_operational",
        description="demo skill for edge loader test",
        status="active",
        origin="manual_seed",
        version="1.0.0",
        scope=SkillScope(**scope_kwargs),
        forbidden_actions=[
            "override_verifier",
            "force_allow_stop",
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ],
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="rulecard_v2.mbis_cop_2023",
        created_by="tester",
        created_at="2026-06-17T00:00:00Z",
        non_authority_statement="non-authoritative; does not modify allow_stop.",
    )


# ===========================================================================
# 1. 映射表完整性
# ===========================================================================
def test_mapping_table_covers_five_edge_dims() -> None:
    """5 条嵌边规则覆盖 scope 5 维；obligation_kinds 不挂边。"""
    fields = {r.scope_field for r in SCOPE_EDGE_RULES}
    assert fields == {
        "rule_families",
        "rule_cards",
        "semantic_slots",
        "measure_keys",
        "artifact_keys",
    }
    assert "obligation_kinds" in SCOPE_NON_EDGE_FIELDS
    # 边类型 + 目标 label/key 与 schema 权威一致
    by_field = {r.scope_field: r for r in SCOPE_EDGE_RULES}
    assert by_field["rule_families"].rel_type == "APPLIES_TO"
    assert by_field["rule_families"].target_label == "RuleFamily"
    assert by_field["rule_families"].target_key_prop == "family_id"
    assert by_field["rule_cards"].rel_type == "APPLIES_TO_CARD"
    assert by_field["rule_cards"].target_key_prop == "rule_card_id"
    assert by_field["semantic_slots"].rel_type == "TARGETS_SLOT"
    assert by_field["semantic_slots"].target_key_prop == "slot_id"
    assert by_field["measure_keys"].rel_type == "TARGETS_MEASURE"
    assert by_field["measure_keys"].target_key_prop == "measure_key"
    assert by_field["artifact_keys"].rel_type == "TARGETS_ARTIFACT"
    assert by_field["artifact_keys"].target_key_prop == "artifact_key"


def test_mapping_rel_types_in_schema_authority() -> None:
    """所有边类型必须在 cypher_schema_evo 权威边名单里。"""
    from evo_agent_baseline.ingest import cypher_schema_evo

    authority = set(cypher_schema_evo.EVO_RELATIONSHIP_TYPES)
    for rule in SCOPE_EDGE_RULES:
        assert rule.rel_type in authority, f"{rule.rel_type} 不在 schema 权威边名单"


# ===========================================================================
# 2. SkillJson → EdgeSpec
# ===========================================================================
def test_build_edges_from_skill_json_all_dims() -> None:
    sj = _make_skill_json(
        rule_families=["mbis.inspection.drainage.ri.follow_up"],
        rule_cards=["rc-1"],
        semantic_slots=["drainage"],
        measure_keys=["ratio.covered_structure_area.inspected"],
        artifact_keys=["report.inspection"],
        obligation_kinds=["action", "evidence"],
    )
    edges = build_skill_edges(from_skill_json(sj))
    # 5 维各 1 个目标 → 5 条边；obligation_kinds 不产边
    assert len(edges) == 5
    rel_types = sorted(e.rel_type for e in edges)
    assert rel_types == [
        "APPLIES_TO",
        "APPLIES_TO_CARD",
        "TARGETS_ARTIFACT",
        "TARGETS_MEASURE",
        "TARGETS_SLOT",
    ]
    # 全部起点是 SkillVersion + 正确版本 id
    for e in edges:
        assert e.start_label == "SkillVersion"
        assert e.start_key_prop == "skill_version_id"
        assert e.start_key_value == "skill.test.macro.demo.v1"


def test_build_edges_dedup_and_skip_empty() -> None:
    sj = _make_skill_json(rule_families=["fam-a", "fam-a", "", "fam-b"])
    edges = build_skill_edges(from_skill_json(sj))
    targets = sorted(e.end_key_value for e in edges)
    assert targets == ["fam-a", "fam-b"]  # 去重 + 跳空


def test_obligation_kinds_never_produce_edges() -> None:
    sj = _make_skill_json(obligation_kinds=["action", "evidence", "threshold"])
    edges = build_skill_edges(from_skill_json(sj))
    assert edges == []


# ===========================================================================
# 3. 库内 record 三路径
# ===========================================================================
def test_from_kg_record_structured_scope() -> None:
    rec = {
        "skill_id": "sk-x",
        "skill_version_id": "sk-x.v1",
        "scope_rule_families": ["fam-1"],
        "scope_semantic_slots": ["slot-1"],
    }
    ref = from_kg_record(rec)
    assert ref.scope_source == "kg_scope_props"
    assert ref.scope.rule_families == ["fam-1"]
    assert ref.scope.semantic_slots == ["slot-1"]


def test_from_kg_record_text_recovered_family() -> None:
    rec = {
        "skill_id": "skill.mbis.drainage.misconnection_trigger.v1",
        "skill_version_id": "skill.mbis.drainage.misconnection_trigger.v1@v1",
        "evo_trigger": (
            "Building has drainage inspection (family: "
            "mbis.inspection.drainage.ri.follow_up) and the rule card references "
            "'defect.drainage.misconnection.present' in slot_ids."
        ),
    }
    ref = from_kg_record(rec)
    assert ref.scope_source == "kg_text_recovered"
    assert ref.scope.rule_families == ["mbis.inspection.drainage.ri.follow_up"]
    # 仅恢复 family，其余维度空
    assert ref.scope.semantic_slots == []


def test_from_kg_record_empty_scope() -> None:
    rec = {"skill_id": "mbis-fact-kg-retrieval", "skill_version_id": "mbis-fact-kg-retrieval"}
    ref = from_kg_record(rec)
    assert ref.scope_source == "empty"
    assert build_skill_edges(ref) == []


# ===========================================================================
# 4. 编译语句：MERGE 幂等 + MATCH 两端防孤儿
# ===========================================================================
def test_compiled_statements_use_merge_and_match() -> None:
    from evo_agent_baseline.ingest._graphspec import compile_batch

    sj = _make_skill_json(rule_families=["fam-1"])
    batch = build_skill_edge_batch([from_skill_json(sj)])
    stmts = compile_batch(batch)
    assert len(stmts) == 1
    cypher, params = stmts[0]
    assert "MERGE (a)-[r:APPLIES_TO]->(b)" in cypher
    # 两端均 MATCH（端点不存在则 MERGE 无命中，不建悬空节点）
    assert cypher.count("MATCH") == 2
    assert "MATCH (a:SkillVersion" in cypher
    assert "MATCH (b:RuleFamily" in cypher
    assert params["start"] == "skill.test.macro.demo.v1"
    assert params["end"] == "fam-1"


def test_idempotent_repeated_compile_same_statements() -> None:
    from evo_agent_baseline.ingest._graphspec import compile_batch

    sj = _make_skill_json(rule_families=["fam-1"], semantic_slots=["slot-1"])
    refs = [from_skill_json(sj)]
    first = compile_batch(build_skill_edge_batch(refs))
    second = compile_batch(build_skill_edge_batch(refs))
    # 同输入两次编译完全一致（MERGE 重入安全 → 幂等）
    assert first == second


# ===========================================================================
# 5. dry_run：分计 + 只读不写
# ===========================================================================
def test_dry_run_counts_would_create_and_missing() -> None:
    sj = _make_skill_json(
        rule_families=["fam-present", "fam-absent"],
        semantic_slots=["slot-present"],
    )
    client = MockClient(
        existing={
            ("RuleFamily", "fam-present"),
            ("SemanticSlot", "slot-present"),
            # fam-absent 不在 → missing
        }
    )
    result = dry_run_skill_edges([from_skill_json(sj)], client)

    assert result.skill_count == 1
    assert result.per_rel["APPLIES_TO"].would_create == 1
    assert result.per_rel["APPLIES_TO"].missing_target == 1
    assert result.per_rel["TARGETS_SLOT"].would_create == 1
    assert result.total_would_create == 2
    assert result.total_missing_target == 1
    # 缺失记 warning
    assert any("fam-absent" in w for w in result.audit.warnings)
    # dry_run 绝不写库
    assert client.written == []


def test_dry_run_report_lists_all_five_rel_types() -> None:
    sj = _make_skill_json(rule_families=["fam-1"])
    client = MockClient(existing={("RuleFamily", "fam-1")})
    result = dry_run_skill_edges([from_skill_json(sj)], client)
    report = format_dry_run_report(result)
    for rule in SCOPE_EDGE_RULES:
        assert rule.rel_type in report
        assert rule.target_label in report


def test_dry_run_caches_target_existence() -> None:
    # 两个技能引用同一 family → 只读探测应命中缓存（仅 1 次 read）
    sj1 = _make_skill_json(rule_families=["fam-shared"])
    sj2 = SkillJson(**{**sj1.model_dump(), "skill_version_id": "skill.test.macro.demo.v2"})
    client = MockClient(existing={("RuleFamily", "fam-shared")})
    dry_run_skill_edges([from_skill_json(sj1), from_skill_json(sj2)], client)
    fam_reads = [c for c in client.read_calls if c[1].get("val") == "fam-shared"]
    assert len(fam_reads) == 1


# ===========================================================================
# 6. load_skill_edges：跳过缺失目标、写入剩余
# ===========================================================================
def test_load_skips_missing_targets_and_writes_rest() -> None:
    sj = _make_skill_json(rule_families=["fam-present", "fam-absent"])
    client = MockClient(existing={("RuleFamily", "fam-present")})
    stats = load_skill_edges([from_skill_json(sj)], client)
    assert stats["written_edge_count"] == 1
    assert stats["skipped_missing_count"] == 1
    # 只写了存在目标的那条
    assert len(client.written) == 1
    _, params = client.written[0]
    assert params["end"] == "fam-present"


def test_load_without_skip_writes_all() -> None:
    sj = _make_skill_json(rule_families=["fam-x"])
    client = MockClient(existing=set())  # 目标都不存在
    stats = load_skill_edges([from_skill_json(sj)], client, skip_missing_targets=False)
    # 不预过滤 → 全写（MATCH 两端在真库里仍不会建悬空节点）
    assert stats["written_edge_count"] == 1
    assert stats["skipped_missing_count"] == 0
    assert len(client.written) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
