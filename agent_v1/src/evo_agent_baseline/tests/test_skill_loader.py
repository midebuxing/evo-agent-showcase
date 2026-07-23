"""skill loader 测试：Anthropic Skills 协议 SKILL.md → Skill KG（spec §4.5 + §7.2）。

不依赖 Neo4j。seed Skill 实际目录在 `agent/skills/`；本测试用 tmp 临时构造
4 个 seed Skill 目录验证 loader 逻辑 + G-008。

**[v0.4-E-2]**：协议从 `skill.yaml + content.md` 双文件迁到 `SKILL.md` 单文件
+ frontmatter (name + description) + markdown body。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evo_agent_baseline.ingest import skill_loader
from evo_agent_baseline.ingest.guard import REQUIRED_SEED_SKILL_IDS, QualityGateError


_SKILL_MD_TEMPLATE = """---
name: {name}
description: {description}
---

# {name}

## Instructions

Test procedure body.
"""


def _write_skill(seed_dir: Path, skill_id: str, description: str = "test skill desc") -> None:
    """在 seed_dir 下写一个 Anthropic Skills 协议 Skill 目录（SKILL.md 单文件）。"""
    skill_dir = seed_dir / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        _SKILL_MD_TEMPLATE.format(name=skill_id, description=description),
        encoding="utf-8",
    )


def _full_seed_dir(tmp_path: Path) -> Path:
    """构造含 4 个 baseline 必需 seed Skill 的目录。"""
    seed_dir = tmp_path / "skills_seed"
    seed_dir.mkdir()
    for skill_id in sorted(REQUIRED_SEED_SKILL_IDS):
        _write_skill(seed_dir, skill_id)
    return seed_dir


# ===========================================================================
# parse_skill_md —— frontmatter 解析
# ===========================================================================
def test_parse_skill_md_valid_frontmatter() -> None:
    """合规 SKILL.md → frontmatter dict + body markdown。"""
    text = (
        "---\n"
        "name: my-skill\n"
        "description: do X when Y\n"
        "---\n\n"
        "# My Skill\n\n"
        "Body.\n"
    )
    fm, body = skill_loader.parse_skill_md(text)
    assert fm == {"name": "my-skill", "description": "do X when Y"}
    assert body.startswith("# My Skill")


def test_parse_skill_md_no_frontmatter_returns_empty() -> None:
    """无 frontmatter → 返回 ({}, text)。"""
    fm, body = skill_loader.parse_skill_md("# Just markdown\n\nBody.")
    assert fm == {}
    assert body == "# Just markdown\n\nBody."


def test_parse_skill_md_unclosed_frontmatter_returns_empty() -> None:
    """frontmatter 无第二个 --- 闭合 → 返回 ({}, text)。"""
    fm, body = skill_loader.parse_skill_md("---\nname: foo\nbody without closing")
    assert fm == {}


# ===========================================================================
# build_skill_node —— Skill 节点字段
# ===========================================================================
def test_build_skill_node_fields() -> None:
    """Skill 节点字段：name / description 来自 frontmatter，其它来自 loader 默认值。"""
    fm = {"name": "mbis-fact-kg-retrieval", "description": "retrieve facts"}
    node = skill_loader.build_skill_node(fm, "# content body")
    assert node.label == "Skill"
    assert node.key_value == "mbis-fact-kg-retrieval"
    assert node.props["name"] == "mbis-fact-kg-retrieval"
    assert node.props["description"] == "retrieve facts"
    assert node.props["content_md"] == "# content body"
    assert node.props["allowed_in_baseline"] is True  # loader 默认值
    assert node.props["status"] == "manual_seed"  # loader 默认值
    assert node.props["origin"] == "manual"  # loader 默认值


# ===========================================================================
# build_skill_graph + G-008
# ===========================================================================
def test_build_skill_graph_four_seeds_pass(tmp_path: Path) -> None:
    """4 个 baseline seed Skill 全加载 → G-008 通过。"""
    seed_dir = _full_seed_dir(tmp_path)
    result = skill_loader.build_skill_graph(seed_dir)
    assert result.loaded_skill_ids == REQUIRED_SEED_SKILL_IDS
    assert result.baseline_allowed_skill_ids == REQUIRED_SEED_SKILL_IDS
    # Anthropic 协议下 baseline loader 不产 SkillTrigger 节点
    assert result.trigger_count == 0


def test_build_skill_graph_missing_seed_fails(tmp_path: Path) -> None:
    """少一个 seed Skill → G-008 QualityGateError。"""
    seed_dir = tmp_path / "skills_seed"
    seed_dir.mkdir()
    for skill_id in sorted(REQUIRED_SEED_SKILL_IDS)[:3]:
        _write_skill(seed_dir, skill_id)
    with pytest.raises(QualityGateError):
        skill_loader.build_skill_graph(seed_dir)


def test_load_one_skill_dir_missing_skill_md_returns_none(tmp_path: Path) -> None:
    """目录缺 SKILL.md → 跳过。"""
    seed_dir = tmp_path / "skills_seed"
    seed_dir.mkdir()
    empty_skill = seed_dir / "mbis-empty"
    empty_skill.mkdir()
    audit = skill_loader.AuditLog()
    result = skill_loader.load_one_skill_dir(empty_skill, audit)
    assert result is None
    assert any("missing SKILL.md" in w for w in audit.warnings)


def test_load_one_skill_dir_no_name_in_frontmatter(tmp_path: Path) -> None:
    """frontmatter 无 name → 跳过。"""
    seed_dir = tmp_path / "skills_seed"
    seed_dir.mkdir()
    skill_dir = seed_dir / "mbis-no-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: missing name\n---\nbody", encoding="utf-8"
    )
    audit = skill_loader.AuditLog()
    result = skill_loader.load_one_skill_dir(skill_dir, audit)
    assert result is None
    assert any("missing 'name'" in w for w in audit.warnings)
