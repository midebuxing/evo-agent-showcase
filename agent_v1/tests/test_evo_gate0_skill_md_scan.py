"""Test Gate 0 SKILL.md 正文扫描扩展（实验 ⑤ finding，spec v1 §9.4.1）。

覆盖：
    1. clean SKILL.md → Gate 0 PASS
    2. SKILL.md 含 BLD-XX-... building literal → leakage_hit
    3. SKILL.md 含 WB-... world bundle literal → leakage_hit
    4. SKILL.md 含 "override verifier" 短语 → leakage_hit
    5. SKILL.md 缺 non-authority 短语 → failure_reasons
    6. SKILL.md sha 跟 pkg.skill_md_sha256 不一致 → failure_reasons
    7. 不传 skill_md_text（向后兼容）→ 与旧行为一致
"""
from __future__ import annotations

import hashlib

import pytest

from evo_agent_baseline.contracts import (
    EvoSkillPackage,
    SkillJson,
    SkillScope,
)
from evo_agent_baseline.evo.skill_validation import run_gate0_static


_CLEAN_SKILL_MD = """# DrainageCoverageSkill

## Purpose
该技能用于辅助排水覆盖率义务的检索 / 路由，不做最终判定。

## Trigger
当 closure 出现 missing_artifact_evidence + drainage slot 时触发。

## Allowed actions
inspect_obligation / retrieve_building_facts / retrieve_applicable_rules

## Retrieval / routing plan
按 rule_family 拉取候选规则 + 按 semantic slot 反查 artifact key。

## Fallback
若 retrieval 失败，退回 core skill 处理。

## Safety and authority boundary
本 skill does not modify allow_stop, closure_status, or satisfaction_status；
verifier 仍是唯一权威。

## Do not
1. 不得绕过 verifier
2. 不得断言任何合规裁决
3. 不得读 evaluator W2 truth
"""


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_pkg(skill_md_text: str, extra_skill_fields: dict | None = None) -> EvoSkillPackage:
    skill_kwargs = dict(
        schema_version="1.0.0",
        skill_id="skill.test.gate0_scan",
        skill_version_id="skill.test.gate0_scan@1",
        name="gate0-scan-test",
        kind="retrieval_macro",
        layer="L1_operational",
        description="Test skill for Gate 0 SKILL.md scan extension.",
        # v1.1 §0.6 修订 2 + §10.6：3 态简化；按 §0.6.1 全局映射规则，
        # 旧 "staged" 视为 "draft"（Gate 0 测试 fixture，未必走 active 路径）
        status="draft",
        origin="manual_seed",
        version="1",
        scope=SkillScope(
            rule_families=["mbis.test"],
            semantic_slots=["drainage"],
            obligation_kinds=["action"],
        ),
        forbidden_actions=[
            "override_verifier",
            "force_allow_stop",
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ],
        kg_snapshot_id="KGS-test",
        rulecard_bundle_id="rulecard_v2.test",
        created_by="test_evo_gate0_skill_md_scan",
        created_at="2026-05-26T00:00:00Z",
        non_authority_statement=(
            "This skill does not modify allow_stop, closure_status, or "
            "satisfaction_status; verifier remains the sole authority."
        ),
    )
    if extra_skill_fields:
        skill_kwargs.update(extra_skill_fields)
    return EvoSkillPackage(
        package_schema_version="1.0.0",
        package_uri="evo://test/gate0_scan",
        package_sha256=_sha("pkg-placeholder"),
        skill=SkillJson(**skill_kwargs),
        skill_md_sha256=_sha(skill_md_text),
        validation_records_sha256=_sha("[]"),
        manifest_sha256=_sha("{}"),
    )


def test_clean_skill_md_passes_gate0():
    pkg = _make_pkg(_CLEAN_SKILL_MD)
    rec = run_gate0_static(pkg, skill_md_text=_CLEAN_SKILL_MD)
    assert rec.passed, (rec.failure_reasons, rec.leakage_hits)


def test_dirty_skill_md_with_building_literal_fails():
    dirty = _CLEAN_SKILL_MD + "\n\n（示例 building: BLD-HK-12345 排水覆盖率 0.8）"
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("BLD-" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_dirty_skill_md_with_world_bundle_literal_fails():
    dirty = _CLEAN_SKILL_MD + "\n\n（trace 来自 WB-2026-001）"
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("WB-" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_dirty_skill_md_with_override_phrase_fails():
    dirty = _CLEAN_SKILL_MD.replace(
        "verifier 仍是唯一权威。",
        "skill may override verifier when confidence is high.",
    )
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("override_phrase" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_skill_md_missing_non_authority_phrase_fails():
    dirty = _CLEAN_SKILL_MD.replace(
        "本 skill does not modify allow_stop, closure_status, or satisfaction_status；",
        "本 skill 关注 retrieval 完整性；",
    ).replace("verifier 仍是唯一权威。", "")
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any(
        "missing_non_authority_statement_in_skill_md" in f for f in rec.failure_reasons
    ), rec.failure_reasons


def test_skill_md_sha_mismatch_fails():
    pkg = _make_pkg(_CLEAN_SKILL_MD)
    tampered = _CLEAN_SKILL_MD + "\n额外篡改内容\n"
    rec = run_gate0_static(pkg, skill_md_text=tampered)
    assert not rec.passed
    assert any("skill_md_sha_mismatch" in f for f in rec.failure_reasons), rec.failure_reasons


def test_no_skill_md_text_backward_compat():
    """旧调用方式不传 skill_md_text → 走旧行为（只校验 skill.json 字段层）。"""
    pkg = _make_pkg(_CLEAN_SKILL_MD)
    rec = run_gate0_static(pkg)
    assert rec.passed, (rec.failure_reasons, rec.leakage_hits)


def test_clean_skill_md_with_runtime_tool_allowlist():
    """允许 + skill_md_text 同时通过，覆盖参数组合。"""
    pkg_with_tool = _make_pkg(
        _CLEAN_SKILL_MD,
        extra_skill_fields={"allowed_tools": ["inspect_obligation"]},
    )
    rec = run_gate0_static(
        pkg_with_tool,
        skill_md_text=_CLEAN_SKILL_MD,
        runtime_tool_allowlist=["inspect_obligation", "retrieve_building_facts"],
    )
    assert rec.passed, (rec.failure_reasons, rec.leakage_hits)


def test_placeholder_building_literal_also_caught():
    """实验 ⑤⑦ 实测：LLM 容易在 'Do not' 列表写 BLD-HK-... 占位示例；新模式应拦。"""
    dirty = _CLEAN_SKILL_MD + "\n\n（示例：BLD-HK-... 是 building 占位）"
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("BLD-" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_placeholder_world_bundle_literal_also_caught():
    """同上：WB-... 占位也应拦。"""
    dirty = _CLEAN_SKILL_MD + "\n\n（示例：WB-... 是 world bundle 占位）"
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("WB-" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_baseline_building_pattern_still_works():
    """旧 baseline 命名（building_42）保留覆盖。"""
    dirty = _CLEAN_SKILL_MD + "\n\nDebug: building_42 missing drainage data"
    pkg = _make_pkg(dirty)
    rec = run_gate0_static(pkg, skill_md_text=dirty)
    assert not rec.passed
    assert any("building_" in h and "@skill_md" in h for h in rec.leakage_hits), rec.leakage_hits


def test_non_authority_phrase_robust_to_backticks_and_quotes():
    """实验 ⑦ 实测：LLM 写 `不会修改 \\`allow_stop\\`` 带 backtick；剥 backtick / 引号
    后短语匹配应仍稳。"""
    cn_text = """# DrainageSkill
## Purpose
辅助排水检索。

## Trigger
排水覆盖缺。

## Allowed actions
inspect_obligation

## Retrieval / routing plan
查 fact。

## Fallback
回 core。

## Safety and authority boundary
此技能不会修改 `allow_stop`、`closure_status` 或 `satisfaction_status`。

## Do not
1. 不绕开 verifier
2. 不读 W2
3. 不裁决
"""
    pkg = _make_pkg(cn_text)
    rec = run_gate0_static(pkg, skill_md_text=cn_text)
    # 不应该 failure_reasons 里含 missing_non_authority_statement_in_skill_md
    assert not any(
        "missing_non_authority_statement_in_skill_md" in f for f in rec.failure_reasons
    ), rec.failure_reasons
