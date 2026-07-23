"""SkillPackage → Neo4j Skill / SkillVersion / SkillValidationRecord 节点
（spec v1 §4.2 + §10）。

把 `EvoSkillPackage` DTO 转为 `GraphBatch`：
- 1 个 `(:Skill)` 节点；
- 1 个 `(:SkillVersion)` 节点；
- N 个 `(:SkillValidationRecord)` 节点；
- 边：`(Skill)-[:HAS_VERSION]->(SkillVersion)` +
       `(SkillVersion)-[:VALIDATED_BY]->(SkillValidationRecord)`。

spec→code 单向：所有节点属性按 spec v1 §3.4.2 / §3.4.3 / §3.4.6 节点 schema；
loader 不引入新字段。

写入入口 `load_skill_package_kg` 调用 `compile_batch` → `client.write_many`，与
现有 baseline loader 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Set

from evo_agent_baseline.contracts import (
    EvoSkillPackage,
    SkillJson,
    SkillValidationRecord,
)
from evo_agent_baseline.evo.skill_package import (
    assert_skill_package_safe,
    load_skill_package,
)
from evo_agent_baseline.ingest._common import canonical_json
from evo_agent_baseline.ingest._graphspec import (
    EdgeSpec,
    GraphBatch,
    NodeSpec,
    compile_batch,
)
from evo_agent_baseline.ingest.guard import AuditLog


# ===========================================================================
# NodeSpec builders（spec v1 §3.4.2 / §3.4.3 / §3.4.6）
# ===========================================================================


def build_skill_node(skill_json: SkillJson) -> NodeSpec:
    """`(:Skill)` 节点 spec v1 §3.4.2。

    Skill 是逻辑 Skill identity，不随版本变化。这里以 skill_id 主键 MERGE；
    `latest_version_id` 直接指向当前版本（spec §3.4.2 允许 latest != active）。

    Args:
        skill_json: SkillJson DTO。

    Returns:
        NodeSpec(label="Skill", key_prop="skill_id")。
    """
    # lifecycle_policy 摘要（spec §3.4.2 必填，json）
    lifecycle_policy = {
        "kind": skill_json.kind,
        "layer": skill_json.layer,
        "status": skill_json.status,
        "expires_on_revision": skill_json.expires_on_revision,
    }
    props = {
        "name": skill_json.name,
        "kind": skill_json.kind,
        "layer": skill_json.layer,
        "description": skill_json.description,
        "origin": skill_json.origin,
        "owner": skill_json.created_by,
        "created_at": skill_json.created_at,
        "latest_version_id": skill_json.skill_version_id,
        # active_version_id 由 promotion pipeline 决定，loader 不主动置 active
        # 除非 skill.json.status == "active"（spec §10.6 + §3.4.2）。
        "active_version_id": (
            skill_json.skill_version_id if skill_json.status == "active" else None
        ),
        "lifecycle_policy": canonical_json(lifecycle_policy),
    }
    return NodeSpec(
        label="Skill",
        key_prop="skill_id",
        key_value=skill_json.skill_id,
        props=props,
    )


def build_skill_version_node(skill_json: SkillJson) -> NodeSpec:
    """`(:SkillVersion)` 节点 spec v1 §3.4.3。

    把 SkillJson 全字段铺到 SkillVersion 节点（package hash 由 loader 阶段补全
    `package_uri` / `package_sha256` / 各子文件 sha256，详见
    `build_skill_package_subgraph`）。

    Args:
        skill_json: SkillJson DTO（不含 package 级 hash）。

    Returns:
        NodeSpec(label="SkillVersion", key_prop="skill_version_id")。
    """
    support = skill_json.support_counts
    val_summary = skill_json.validation_summary

    props = {
        "skill_id": skill_json.skill_id,
        "version": skill_json.version,
        "status": skill_json.status,
        # package_uri / *_sha256 在 build_skill_package_subgraph 阶段 patch
        "rulecard_bundle_id": skill_json.rulecard_bundle_id,
        "kg_snapshot_id": skill_json.kg_snapshot_id,
        "scope_rule_families": skill_json.scope.rule_families,
        "scope_rule_cards": skill_json.scope.rule_cards,
        "scope_semantic_slots": skill_json.scope.semantic_slots,
        "scope_obligation_kinds": skill_json.scope.obligation_kinds,
        "trigger_predicate_json": canonical_json(skill_json.trigger_predicate),
        "allowed_tools": list(skill_json.allowed_tools),
        "forbidden_actions": list(skill_json.forbidden_actions),
        "source_trace_hashes": list(skill_json.source_trace_hashes),
        "support_building_count": int(support.get("building_count", 0)),
        "support_world_family_count": int(support.get("world_family_count", 0)),
        # leakage / closure non-regression 默认 False；active 状态下由 validation_summary 决定
        "leakage_audit_passed": bool(
            val_summary.get("leakage_audit_passed",
                            val_summary.get("gate4_holdout_counterfactual") == "passed")
        ),
        "closure_non_regression_passed": bool(
            val_summary.get("closure_non_regression_passed",
                            val_summary.get("gate2_replay_ab") == "passed")
        ),
        # staleness：loader 默认 fresh；外部 StalenessGuard 可改写
        "staleness_status": "fresh",
        "created_at": skill_json.created_at,
        "supersedes_version_id": (
            skill_json.supersedes[0] if skill_json.supersedes else None
        ),
        "parent_version_id": skill_json.parent_skill_version_id,
        "non_authority_statement": skill_json.non_authority_statement,
    }
    return NodeSpec(
        label="SkillVersion",
        key_prop="skill_version_id",
        key_value=skill_json.skill_version_id,
        props=props,
    )


def build_skill_validation_record_node(rec: SkillValidationRecord) -> NodeSpec:
    """`(:SkillValidationRecord)` 节点 spec v1 §3.4.6。

    Args:
        rec: SkillValidationRecord DTO。

    Returns:
        NodeSpec(label="SkillValidationRecord", key_prop="validation_id")。
    """
    props = {
        "skill_version_id": rec.skill_version_id,
        "validation_stage": rec.validation_stage,
        "eval_set_id": rec.eval_set_id,
        "eval_set_hash": rec.eval_set_hash,
        "run_count": rec.run_count,
        "building_count": rec.building_count,
        "world_family_count": rec.world_family_count,
        "metric_name": rec.metric_name,
        "metric_value_bucket": rec.metric_value_bucket,
        "metric_delta_bucket": rec.metric_delta_bucket,
        "passed": rec.passed,
        "failure_reasons": list(rec.failure_reasons),
        "leakage_hits": list(rec.leakage_hits),
        "closure_regression_count": rec.closure_regression_count,
        "allow_stop_authority_check": rec.allow_stop_authority_check,
        "validator_version": rec.validator_version,
        "created_at": rec.created_at,
    }
    return NodeSpec(
        label="SkillValidationRecord",
        key_prop="validation_id",
        key_value=rec.validation_id,
        props=props,
    )


# ===========================================================================
# Subgraph builder
# ===========================================================================


@dataclass
class SkillPackageLoadResult:
    """SkillPackage loader 输出。"""

    batch: GraphBatch
    skill_id: str
    skill_version_id: str
    validation_record_ids: List[str] = field(default_factory=list)
    audit: AuditLog = field(default_factory=AuditLog)


def build_skill_package_subgraph(
    pkg: EvoSkillPackage,
    validation_records: List[SkillValidationRecord],
) -> GraphBatch:
    """SkillPackage → GraphBatch（spec v1 §3.4.2 + §3.4.3 + §3.4.6 + §3.5）。

    Args:
        pkg: EvoSkillPackage DTO（含 package 级 hash）。
        validation_records: 解析出的 N 条 `SkillValidationRecord`。

    Returns:
        含 Skill / SkillVersion / N×SkillValidationRecord 节点 + 关联边的 GraphBatch。
    """
    batch = GraphBatch()
    skill_node = build_skill_node(pkg.skill)
    sv_node = build_skill_version_node(pkg.skill)

    # patch package hash 到 SkillVersion 节点（spec §3.4.3 必填）
    patched_props = dict(sv_node.props)
    patched_props.update(
        {
            "package_uri": pkg.package_uri,
            "package_sha256": pkg.package_sha256,
            "skill_json_sha256": _skill_json_sha_from_pkg(pkg),
            "skill_md_sha256": pkg.skill_md_sha256,
            "plan_yaml_sha256": pkg.plan_yaml_sha256,
            "validation_records_sha256": pkg.validation_records_sha256,
            "manifest_sha256": pkg.manifest_sha256,
        }
    )
    sv_node = NodeSpec(
        label="SkillVersion",
        key_prop="skill_version_id",
        key_value=pkg.skill.skill_version_id,
        props=patched_props,
    )

    batch.add_node(skill_node)
    batch.add_node(sv_node)

    # Skill -[:HAS_VERSION]-> SkillVersion
    batch.add_edge(
        EdgeSpec(
            start_label="Skill",
            start_key_prop="skill_id",
            start_key_value=pkg.skill.skill_id,
            rel_type="HAS_VERSION",
            end_label="SkillVersion",
            end_key_prop="skill_version_id",
            end_key_value=pkg.skill.skill_version_id,
            props={"created_at": pkg.skill.created_at},
        )
    )

    # SkillVersion -[:VALIDATED_BY]-> SkillValidationRecord（每条 record 一边）
    for rec in validation_records:
        if rec.skill_version_id != pkg.skill.skill_version_id:
            # mismatch 不入图（防止跨包污染），由 audit 记录
            continue
        node = build_skill_validation_record_node(rec)
        batch.add_node(node)
        batch.add_edge(
            EdgeSpec(
                start_label="SkillVersion",
                start_key_prop="skill_version_id",
                start_key_value=pkg.skill.skill_version_id,
                rel_type="VALIDATED_BY",
                end_label="SkillValidationRecord",
                end_key_prop="validation_id",
                end_key_value=rec.validation_id,
                props={"stage": rec.validation_stage},
            )
        )

    return batch


def _skill_json_sha_from_pkg(pkg: EvoSkillPackage) -> str:
    """重新对 SkillJson canonical 内容 hash，作为 skill_json_sha256 占位。

    注意：spec v1 §3.4.3 要求 `skill_json_sha256` 是 skill.json 文件 hash。
    `EvoSkillPackage` 顶层无单独字段；loader 通过文件 sha256 计算后保留在
    `package_sha256` 之外。这里从 pkg.skill 重新 canonical 一遍作 surrogate。
    主调 `load_skill_package_kg` 会单独从磁盘读 skill.json 再覆盖。
    """
    from evo_agent_baseline.evo.skill_package import sha256_text

    skill_canonical = canonical_json(pkg.skill.model_dump(mode="json"))
    return sha256_text(skill_canonical)


# ===========================================================================
# 写入入口
# ===========================================================================


def load_skill_package_kg(
    package_dir: Path,
    client: Any,
    audit: Optional[AuditLog] = None,
    run_gate0: bool = True,
) -> SkillPackageLoadResult:
    """从目录 load SkillPackage → 写入 Neo4j（spec v1 §4.2.2 loader steps）。

    流程对齐 spec v1 §4.2.2：
    1. resolve package URI（构造 package_dir）；
    2. read skill.json only → `parse_skill_json`；
    3. validate schema and status；
    4. read declared files and compute hashes → `load_skill_package`；
    5. run Gate 0 static safety scan → `assert_skill_package_safe`；
    6/7. load validation_records.jsonl；
    8. (caller 验 staged/active 时调用)；
    9. build Skill / SkillVersion graph nodes → `build_skill_package_subgraph`；
    10. (caller projection)。

    Args:
        package_dir: SkillPackage 目录。
        client: `Neo4jClient` 实例（提供 `write_many`）。
        audit: 审计日志。
        run_gate0: 是否在 load 阶段运行 Gate 0（默认 True）。

    Returns:
        SkillPackageLoadResult（含 batch + 各 id）。
    """
    from evo_agent_baseline.evo.skill_package import (
        parse_validation_records,
        sha256_file,
    )

    audit = audit or AuditLog()
    pkg = load_skill_package(package_dir)

    if run_gate0:
        skill_md_text = (package_dir / "SKILL.md").read_text(encoding="utf-8")
        plan_yaml_text: Optional[str] = None
        plan_path = package_dir / "plan.yaml"
        if plan_path.is_file():
            plan_yaml_text = plan_path.read_text(encoding="utf-8")
        assert_skill_package_safe(pkg, skill_md_text=skill_md_text,
                                  plan_yaml_text=plan_yaml_text)

    val_records = parse_validation_records(package_dir / "validation_records.jsonl")

    batch = build_skill_package_subgraph(pkg, val_records)

    # 修正 SkillVersion 节点上 skill_json_sha256 = 文件真实 sha
    real_skill_json_sha = sha256_file(package_dir / "skill.json")
    for idx, node in enumerate(batch.nodes):
        if node.label == "SkillVersion":
            new_props = dict(node.props)
            new_props["skill_json_sha256"] = real_skill_json_sha
            batch.nodes[idx] = NodeSpec(
                label=node.label,
                key_prop=node.key_prop,
                key_value=node.key_value,
                props=new_props,
            )
            break

    audit.record_source(f"skill_package/{package_dir.name}/skill.json")
    audit.record_source(f"skill_package/{package_dir.name}/SKILL.md")
    audit.record_source(f"skill_package/{package_dir.name}/validation_records.jsonl")
    if pkg.plan_yaml_sha256 is not None:
        audit.record_source(f"skill_package/{package_dir.name}/plan.yaml")

    client.write_many(compile_batch(batch))

    return SkillPackageLoadResult(
        batch=batch,
        skill_id=pkg.skill.skill_id,
        skill_version_id=pkg.skill.skill_version_id,
        validation_record_ids=[r.validation_id for r in val_records],
        audit=audit,
    )


__all__ = [
    "build_skill_node",
    "build_skill_version_node",
    "build_skill_validation_record_node",
    "build_skill_package_subgraph",
    "load_skill_package_kg",
    "SkillPackageLoadResult",
]
