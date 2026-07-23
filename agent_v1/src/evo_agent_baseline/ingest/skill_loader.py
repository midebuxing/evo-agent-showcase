"""skill loader：4 个 baseline 手工 seed Skill → Skill KG（spec §4.5 + §3.5 + §7.2）。

**[v0.4-E-2]** 协议从自创 `skill.yaml + content.md` 双文件切到 Anthropic
[Agent Skills 协议](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
单 `SKILL.md`（frontmatter `name + description` 2 字段 + markdown 正文）。
目录格式：`<skill_seed_dir>/<name>/SKILL.md`，name 小写连字符。

实现的 spec 章节：
- §3.5 Skill 节点 schema（SkillTrigger 在 Anthropic 协议下不再使用，留作图
  schema 但 baseline loader 不再产）；
- §4.5 skill loader：4 个必需 seed Skill、目录格式、SKILL.md 正文入
  Skill.content_md、frontmatter description 入 Skill.description；
- §4.7 G-008 seed skills 质量门；
- §7.2.0 协议要点 + §7.2.1-§7.2.4 4 个 baseline Skill。

约束（spec §4.5 / D-005）：
- baseline 必须加载 4 个手工 seed Skill；
- baseline 不允许 Skill 修改 verifier 输出，不允许 Skill 读 evaluator-only
  truth（agent runtime 侧约束；loader 不赋予额外权限）；
- Anthropic Skills 协议下 Skill 不直接管"触发"，由 description 语义匹配；
  baseline 把 `allowed_in_baseline=True` 默认所有 loader-loaded Skill 都允许，
  权限由 §7.3 hook + §7.5 tool interface 控制。

seed Skill 内容是 agent-visible（spec §2.1 baseline Skill KG agent 可见），
不受 evo-agent blind 约束；但仍走 `_graphspec` 的禁止属性 / label 二次检查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from evo_agent_baseline.ingest._common import canonical_json, opt_str
from evo_agent_baseline.ingest._graphspec import EdgeSpec, GraphBatch, NodeSpec
from evo_agent_baseline.ingest.guard import (
    REQUIRED_SEED_SKILL_IDS,
    AuditLog,
    gate_g008_seed_skills,
    raise_if_failed,
)


@dataclass
class SkillLoadResult:
    """skill loader 灌库结果。"""

    batch: GraphBatch
    loaded_skill_ids: Set[str] = field(default_factory=set)
    baseline_allowed_skill_ids: Set[str] = field(default_factory=set)
    trigger_count: int = 0
    audit: AuditLog = field(default_factory=AuditLog)


def parse_skill_md(text: str) -> tuple[Dict[str, Any], str]:
    """解析 Anthropic Skills 协议的 SKILL.md（frontmatter + 正文）。

    协议格式：
        ---
        name: my-skill
        description: ...
        ---
        # body markdown

    Args:
        text: SKILL.md 全文。

    Returns:
        (frontmatter_dict, body_markdown)。frontmatter 缺失时返回 ({}, text)。
    """
    if not text.startswith("---"):
        return {}, text
    # 找第二个 --- 分隔
    rest = text[3:]  # 跳第一个 ---（含可能的换行）
    sep_idx = rest.find("\n---")
    if sep_idx < 0:
        return {}, text  # 没闭合 frontmatter
    fm_text = rest[:sep_idx]
    body = rest[sep_idx + 4 :].lstrip("\n")  # 跳过 "\n---" + 后续换行
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(fm, dict):
        return {}, text
    return fm, body


def build_skill_node(frontmatter: Dict[str, Any], content_md: str) -> NodeSpec:
    """SKILL.md frontmatter + body → (:Skill) 节点（spec §3.5 + §7.2）。

    Anthropic Skills 协议：frontmatter 仅 `name` + `description` 必需；其它
    自创字段（status / origin / version / allowed_in_baseline）已废弃。
    baseline loader 内部仍把 status / origin / allowed_in_baseline 保留为
    Skill 节点属性，但全部由 loader 自带默认值（不再来自 frontmatter）。

    Args:
        frontmatter: SKILL.md frontmatter dict（Anthropic 协议）。
        content_md: SKILL.md 正文 markdown。

    Returns:
        Skill NodeSpec。skill_id = frontmatter.name。
    """
    skill_id = opt_str(frontmatter.get("name"))
    props = {
        "name": skill_id,
        "description": opt_str(frontmatter.get("description")),
        "status": "manual_seed",  # baseline loader 默认（spec §7.2.0）
        "origin": "manual",  # 同上
        "version": opt_str(frontmatter.get("version")),  # Anthropic 协议可选
        "allowed_in_baseline": True,  # baseline loader 加载 = 默认允许
        "content_md": content_md,
        "notes": "",
    }
    return NodeSpec("Skill", "skill_id", skill_id, props)


def load_one_skill_dir(skill_dir: Path, audit: AuditLog) -> Optional[GraphBatch]:
    """加载单个 seed Skill 目录（Anthropic Skills 协议 `<name>/SKILL.md`）。

    Args:
        skill_dir: 单个 Skill 目录，应含 SKILL.md。
        audit: 审计记录器。

    Returns:
        该 Skill 的 GraphBatch；SKILL.md 缺失 / 解析失败时返回 None。
    """
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.is_file():
        audit.warn(f"skill: {skill_dir.name} missing SKILL.md, skipped")
        return None
    raw = skill_md_path.read_text(encoding="utf-8")
    frontmatter, body = parse_skill_md(raw)
    skill_id = opt_str(frontmatter.get("name"))
    if skill_id is None:
        audit.warn(
            f"skill: {skill_dir.name}/SKILL.md frontmatter missing 'name', skipped"
        )
        return None
    if skill_id != skill_dir.name:
        audit.warn(
            f"skill: {skill_dir.name}/SKILL.md 'name'={skill_id!r} mismatches "
            f"dir name {skill_dir.name!r}（Anthropic 协议要求一致）"
        )
    if not opt_str(frontmatter.get("description")):
        audit.warn(
            f"skill: {skill_id} SKILL.md frontmatter missing 'description'"
        )

    batch = GraphBatch()
    batch.add_node(build_skill_node(frontmatter, body))
    audit.record_source(f"skills_seed/{skill_dir.name}/SKILL.md")
    return batch


def build_skill_graph(
    skill_seed_dir: Path,
    audit: Optional[AuditLog] = None,
) -> SkillLoadResult:
    """把 skills_seed 目录下全部 seed Skill 转换为 GraphBatch（纯转换，不写 Neo4j）。

    G-008：要求 4 个 baseline 必需 seed Skill 全部加载且 allowed_in_baseline=true。

    Args:
        skill_seed_dir: skills_seed 目录（其下每个子目录是一个 Skill）。
        audit: 审计记录器。

    Returns:
        SkillLoadResult。

    Raises:
        QualityGateError: G-008 不通过。
    """
    audit = audit or AuditLog()
    result = SkillLoadResult(batch=GraphBatch(), audit=audit)

    if not skill_seed_dir.is_dir():
        audit.warn(f"skill: seed dir {skill_seed_dir} not found")
    else:
        for child in sorted(skill_seed_dir.iterdir()):
            if not child.is_dir():
                continue
            sub = load_one_skill_dir(child, audit)
            if sub is None:
                continue
            result.batch.extend(sub)
            for node in sub.nodes:
                if node.label == "Skill":
                    result.loaded_skill_ids.add(node.key_value)
                    if node.props.get("allowed_in_baseline"):
                        result.baseline_allowed_skill_ids.add(node.key_value)
                elif node.label == "SkillTrigger":
                    result.trigger_count += 1

    # G-008：4 个必需 seed Skill 全量加载校验。
    raise_if_failed(gate_g008_seed_skills(
        result.loaded_skill_ids, result.baseline_allowed_skill_ids
    ))
    return result


def load_skill_kg(
    skill_seed_dir: Path,
    client: Any,
    audit: Optional[AuditLog] = None,
) -> SkillLoadResult:
    """把 Skill KG 写入 Neo4j（spec §4.5）。

    Args:
        skill_seed_dir: skills_seed 目录。
        client: `Neo4jClient` 实例。
        audit: 审计记录器。

    Returns:
        SkillLoadResult（已写入）。
    """
    from evo_agent_baseline.ingest._graphspec import compile_batch

    result = build_skill_graph(skill_seed_dir, audit)
    client.write_many(compile_batch(result.batch))
    return result


__all__ = [
    "REQUIRED_SEED_SKILL_IDS",
    "SkillLoadResult",
    "parse_skill_md",
    "build_skill_node",
    "load_one_skill_dir",
    "build_skill_graph",
    "load_skill_kg",
]
