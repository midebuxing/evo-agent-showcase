"""灌库守卫测试：白/黑名单判定 + 启动 guard + 质量门（spec §2.2 + §4.7）。

不依赖 Neo4j。这是 evo-agent blind 红线的核心测试，重点验证：
- 显式点名 W2 黑名单文件 hard fail；
- 目录里有黑名单文件只 warning + 跳过；
- 禁止属性 scrub；
- 8 个灌库质量门。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evo_agent_baseline.ingest import guard


# ===========================================================================
# 白 / 黑名单常量
# ===========================================================================
def test_allowlist_has_12_tables() -> None:
    """spec §2.2.1 白名单 12 张表。"""
    assert len(guard.AGENT_WORLDGEN_ALLOWLIST) == 12


def test_denylist_has_6_tables() -> None:
    """spec §2.2.2 黑名单 6 张 W2 表。"""
    assert len(guard.AGENT_NORMATIVE_DENYLIST) == 6
    assert "projections.parquet" in guard.AGENT_NORMATIVE_DENYLIST
    assert "normative_projection_meta.parquet" in guard.AGENT_NORMATIVE_DENYLIST


def test_allow_and_deny_disjoint() -> None:
    """白名单与黑名单不相交。"""
    assert guard.AGENT_WORLDGEN_ALLOWLIST & guard.AGENT_NORMATIVE_DENYLIST == set()


def test_forbidden_properties_include_w2_fields() -> None:
    """spec §2.2.3 禁止属性名含 W2 核心字段。"""
    for name in ("expected_verdict", "projection_id", "coverage_status", "pass_bool"):
        assert name in guard.FORBIDDEN_AGENT_PROPERTIES


def test_world_id_not_forbidden() -> None:
    """spec §2.2.3 说明 1：world_id 是事实层原生字段，不在禁止之列。"""
    assert "world_id" not in guard.FORBIDDEN_AGENT_PROPERTIES
    assert "fragment_id" not in guard.FORBIDDEN_AGENT_PROPERTIES
    assert "severity_band" not in guard.FORBIDDEN_AGENT_PROPERTIES


def test_required_seed_skills_count() -> None:
    """spec §4.5：4 个必需 seed Skill。"""
    assert len(guard.REQUIRED_SEED_SKILL_IDS) == 4


# ===========================================================================
# §4.2.2 启动 guard
# ===========================================================================
def _make_run_dir(tmp_path: Path, table_names: list[str]) -> Path:
    """在 tmp 下建一个含指定 parquet 文件名的伪 run 目录。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in table_names:
        (run_dir / name).write_bytes(b"PARQ")  # 内容无所谓，guard 只看文件名
    return run_dir


def test_assert_agent_safe_input_ok(tmp_path: Path) -> None:
    """齐备 10 张必需表 → guard 通过。"""
    run_dir = _make_run_dir(tmp_path, sorted(guard.REQUIRED_AGENT_TABLES))
    audit = guard.assert_agent_safe_input(run_dir)
    assert audit.skipped_denylist_files == []


def test_assert_agent_safe_input_missing_required(tmp_path: Path) -> None:
    """缺必需表 → ContractError。"""
    tables = sorted(guard.REQUIRED_AGENT_TABLES)[:-1]  # 去掉一张
    run_dir = _make_run_dir(tmp_path, tables)
    with pytest.raises(guard.ContractError):
        guard.assert_agent_safe_input(run_dir)


def test_assert_agent_safe_input_denylist_present_only_warns(tmp_path: Path) -> None:
    """目录里有 W2 黑名单文件 → 只 warning + 跳过，不报错（spec §2.2.2）。"""
    tables = sorted(guard.REQUIRED_AGENT_TABLES) + ["projections.parquet"]
    run_dir = _make_run_dir(tmp_path, tables)
    audit = guard.assert_agent_safe_input(run_dir)  # 不应抛异常
    assert "projections.parquet" in audit.skipped_denylist_files
    assert any("projections.parquet" in w for w in audit.warnings)


def test_assert_agent_safe_input_explicit_denylist_hard_fail(tmp_path: Path) -> None:
    """显式点名 W2 黑名单文件 → SecurityError hard fail（spec §2.2.2 / §4.2.2）。"""
    tables = sorted(guard.REQUIRED_AGENT_TABLES)
    run_dir = _make_run_dir(tmp_path, tables)
    with pytest.raises(guard.SecurityError):
        guard.assert_agent_safe_input(
            run_dir, explicit_targets={"projections.parquet"}
        )


def test_is_agent_visible_table() -> None:
    """白名单判定。"""
    assert guard.is_agent_visible_table("buildings.parquet")
    assert not guard.is_agent_visible_table("projections.parquet")


def test_is_normative_denylist_table() -> None:
    """黑名单判定。"""
    assert guard.is_normative_denylist_table("threshold_evaluations.parquet")
    assert not guard.is_normative_denylist_table("fragments.parquet")


# ===========================================================================
# 禁止属性 scrub
# ===========================================================================
def test_scrub_forbidden_properties_pass() -> None:
    """干净 props → 原样返回。"""
    props = {"world_id": "WB-1", "severity_band": "high"}
    assert guard.scrub_forbidden_properties(props, "ConditionState") == props


def test_scrub_forbidden_properties_fail() -> None:
    """含 expected_verdict → SecurityError。"""
    props = {"world_id": "WB-1", "expected_verdict": "compliant"}
    with pytest.raises(guard.SecurityError):
        guard.scrub_forbidden_properties(props, "Building")


def test_assert_label_allowed_fail() -> None:
    """W2 label → SecurityError。"""
    with pytest.raises(guard.SecurityError):
        guard.assert_label_allowed("NormativeProjection")


def test_assert_label_allowed_pass() -> None:
    """事实层 label → 通过。"""
    guard.assert_label_allowed("Building")
    guard.assert_label_allowed("RuleCard")


# ===========================================================================
# §4.7 质量门
# ===========================================================================
def test_gate_g001_denylist() -> None:
    """G-001：显式黑名单 → fail。"""
    assert guard.gate_g001_denylist_table(None).passed
    assert guard.gate_g001_denylist_table({"buildings.parquet"}).passed
    assert not guard.gate_g001_denylist_table({"projections.parquet"}).passed


def test_gate_g002_forbidden_property() -> None:
    """G-002：禁止属性 → fail。"""
    assert guard.gate_g002_forbidden_property("Building", {"world_id": "x"}).passed
    assert not guard.gate_g002_forbidden_property(
        "Building", {"projection_id": "x"}
    ).passed


def test_gate_g003_rulecard_child_completeness() -> None:
    """G-003：缺 ApplicabilityPredicate / ObligationNode → fail。"""
    assert guard.gate_g003_rulecard_child_completeness("rc.1", True, True).passed
    assert not guard.gate_g003_rulecard_child_completeness("rc.1", False, True).passed
    assert not guard.gate_g003_rulecard_child_completeness("rc.1", True, False).passed


def test_gate_g004_threshold_formula_preservation() -> None:
    """G-004：operator=formula 且上游有 formula 但 formula_json 空 → fail。"""
    assert guard.gate_g004_threshold_formula_preservation(
        "t1", "formula", True, '{"expression":"n"}'
    ).passed
    assert not guard.gate_g004_threshold_formula_preservation(
        "t1", "formula", True, None
    ).passed
    # 非 formula operator 不受约束。
    assert guard.gate_g004_threshold_formula_preservation("t1", "<=", False, None).passed


def test_gate_g005_obligation_edge_preservation() -> None:
    """G-005：上游有 edges 但落 0 → fail。"""
    assert guard.gate_g005_obligation_edge_preservation("rc.1", 0, 0).passed
    assert guard.gate_g005_obligation_edge_preservation("rc.1", 2, 2).passed
    assert not guard.gate_g005_obligation_edge_preservation("rc.1", 2, 0).passed


def test_gate_g006_sidecar_projection_scrub() -> None:
    """G-006：SidecarRuntimeRecord props 含 projection_id → fail。"""
    assert guard.gate_g006_sidecar_projection_scrub("SCR-1", {"world_id": "x"}).passed
    assert not guard.gate_g006_sidecar_projection_scrub(
        "SCR-1", {"projection_id": "x"}
    ).passed
    assert not guard.gate_g006_sidecar_projection_scrub(
        "SCR-1", {"raw_projection_ref_hash": "abc"}
    ).passed


def test_gate_g007_source_quote_key() -> None:
    """G-007：SourceQuote 缺 source_quote_id → fail。"""
    assert guard.gate_g007_source_quote_key("rc.1", {"source_quote_id": "rc.1::sq01"}).passed
    assert not guard.gate_g007_source_quote_key("rc.1", {"text": "x"}).passed


def test_gate_g008_seed_skills() -> None:
    """G-008：4 个 seed Skill 全加载且 allowed_in_baseline → pass。"""
    full = set(guard.REQUIRED_SEED_SKILL_IDS)
    assert guard.gate_g008_seed_skills(full, full).passed
    # 少一个。
    assert not guard.gate_g008_seed_skills(set(list(full)[:3]), full).passed
    # 全加载但有的 allowed_in_baseline=false。
    assert not guard.gate_g008_seed_skills(full, set(list(full)[:3])).passed


def test_raise_if_failed() -> None:
    """raise_if_failed：fail 结果抛 QualityGateError。"""
    ok = guard.QualityGateResult("G-X", True)
    assert guard.raise_if_failed(ok) is ok
    bad = guard.QualityGateResult("G-Y", False, "bad")
    with pytest.raises(guard.QualityGateError):
        guard.raise_if_failed(bad)


# ===========================================================================
# spec→code 单向自检
# ===========================================================================
def test_guard_config_consistent_with_spec() -> None:
    """config/guard.yaml 与 spec 硬编码常量一致（spec→code 单向）。

    2026-05-23 集成阶段：地基代理初版 config 缺 4 个 forbidden property
    （projection_registry_id / projection_family / projection_version / projection_ref_hash），
    集成时补齐。本测试现直接断言 config 与硬编码 `FORBIDDEN_AGENT_PROPERTIES` 一致。
    blind 红线运行时走硬编码常量、不依赖 config，但 config 与 spec 一致是 spec→code 单向要求。
    """
    config_path = (
        Path(__file__).resolve().parent.parent / "config" / "guard.yaml"
    )
    with open(config_path, "r", encoding="utf-8") as fh:
        guard_config = yaml.safe_load(fh)
    guard.assert_guard_config_consistent(guard_config)


def test_forbidden_properties_full_spec_coverage() -> None:
    """硬编码 FORBIDDEN_AGENT_PROPERTIES 必须含 spec §2.2.3 全部 15 项。

    spec §2.2.3 列：
    - W2 reference truth / projection answer fields (7)
    - W2 NormativeProjection 顶层字段 (10)
    - sidecar projection_id hash 变体 (2)
    去除 world_id / fragment_id / severity_band 等事实层原生字段后共 24 项。
    """
    spec_required = {
        "expected_verdict", "selected_family", "projection_status", "basis_items",
        "unknown_reason_code", "regime_tag", "pass_bool",
        "projection_id", "projection_registry_id", "projection_family",
        "projection_version", "required_world_core_slots",
        "required_measurement_slots", "required_qualifier_slots",
        "required_sidecar_interfaces", "matched_component_refs",
        "matched_measurement_ids", "coverage_status",
        "raw_projection_ref_hash", "projection_ref_hash",
    }
    missing = spec_required - guard.FORBIDDEN_AGENT_PROPERTIES
    assert not missing, f"硬编码漏 spec §2.2.3 禁止属性 {missing}"


def test_audit_log_to_provenance() -> None:
    """AuditLog → §2.4 provenance 片段。"""
    audit = guard.AuditLog()
    audit.record_source("buildings.parquet")
    audit.warn_skipped(["projections.parquet"])
    prov = audit.to_provenance()
    assert "buildings.parquet" in prov["agent_visible_sources"]
    assert "projections.parquet" in prov["evaluator_only_sources_seen_and_skipped"]
    assert prov["forbidden_source_check_passed"] is True
