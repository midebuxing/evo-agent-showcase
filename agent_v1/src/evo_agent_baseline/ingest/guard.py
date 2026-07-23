"""灌库守卫：白名单 / 黑名单 + 灌库质量门（spec §2.2 + §4.7）。

本模块是 evo-agent blind 红线（最高优先级）的第一 / 第二道实现防线：
- §2.2.1 白名单 `AGENT_WORLDGEN_ALLOWLIST` —— agent fact loader 允许读的 12 张表；
- §2.2.2 黑名单 `AGENT_NORMATIVE_DENYLIST` —— W2 法规映射层 6 张表，绝不进 agent KG；
- §2.2.3 禁止属性名 `FORBIDDEN_AGENT_PROPERTIES` —— 写图前必须 scrub 检查；
- §4.2.2 启动 guard `assert_agent_safe_input` —— 输入目录里有黑名单文件记 warning 并跳过，
  调用方显式把黑名单文件传进来则 hard fail；
- §4.7 灌库质量门 G-001 ~ G-008。

spec→code 单向：白 / 黑名单与禁止属性名清单逐条照搬 spec，不增不减。
guard 配置同时落在 `config/guard.yaml`，本模块以 spec 文本为权威硬编码常量，
两者必须一致（见 `assert_guard_config_consistent`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

# ===========================================================================
# §2.2.1 agent fact loader 白名单
# ===========================================================================
AGENT_WORLDGEN_ALLOWLIST: Set[str] = {
    "worldgen_world_bundles_meta.parquet",
    "buildings.parquet",
    "fragments.parquet",
    "components.parquet",
    "locations.parquet",
    "coverage_relations.parquet",
    "fragment_states.parquet",
    "specialized_states.parquet",
    "measurements.parquet",
    "sidecar_runtime_meta.parquet",
    "sidecar_records.parquet",
    "sidecar_entries.parquet",
}

# §4.2.1 必需表（白名单中去掉两个 optional 表）。
# optional：worldgen_world_bundles_meta.parquet / sidecar_runtime_meta.parquet。
REQUIRED_AGENT_TABLES: Set[str] = {
    "buildings.parquet",
    "fragments.parquet",
    "components.parquet",
    "locations.parquet",
    "coverage_relations.parquet",
    "fragment_states.parquet",
    "specialized_states.parquet",
    "measurements.parquet",
    "sidecar_records.parquet",
    "sidecar_entries.parquet",
}
OPTIONAL_AGENT_TABLES: Set[str] = {
    "worldgen_world_bundles_meta.parquet",
    "sidecar_runtime_meta.parquet",
}

# ===========================================================================
# §2.2.2 agent fact loader 黑名单（W2 法规映射层 parquet）
# ===========================================================================
AGENT_NORMATIVE_DENYLIST: Set[str] = {
    "normative_projection_meta.parquet",
    "projections.parquet",
    "matched_families.parquet",
    "threshold_evaluations.parquet",
    "coverage_control_metadata.parquet",
    "basis_items.parquet",
}

# ===========================================================================
# §2.2.3 agent KG 禁止 label
# ===========================================================================
FORBIDDEN_AGENT_LABELS: Set[str] = {
    "NormativeProjection",
    "ProjectionFamilyEval",
    "ThresholdEval",      # 仅当来源是 W2 threshold_evaluations
    "ReportBasisItem",    # 仅当来源是 W2 basis_items
    "ExpectedVerdict",
    "EvalProjection",
    "EvalTruth",
}

# ===========================================================================
# §2.2.3 agent KG 禁止属性名（blind 第二道防线）
# ===========================================================================
# 注意 spec §2.2.3 说明 1：world_id / fragment_id / severity_band 是 W0/W1 事实层
# 原生字段，W2 复用同名不改变事实层来源，不在禁止之列。
FORBIDDEN_AGENT_PROPERTIES: Set[str] = {
    # W2 reference truth / projection answer fields
    "expected_verdict",
    "selected_family",
    "projection_status",
    "basis_items",
    "unknown_reason_code",
    "regime_tag",         # 仅当来源是 W2 输出；rule_card threshold source 不用此字段名
    "pass_bool",          # 仅当来源是 W2 输出；verifier 可用 comparator_result
    # W2 NormativeProjection 顶层字段
    "projection_id",
    "projection_registry_id",
    "projection_family",
    "projection_version",
    "required_world_core_slots",
    "required_measurement_slots",
    "required_qualifier_slots",
    "required_sidecar_interfaces",
    "matched_component_refs",
    "matched_measurement_ids",
    "coverage_status",
    # sidecar projection_id 的任何 hash / ref 变体
    "raw_projection_ref_hash",
    "projection_ref_hash",
}

# §4.5 / D-005 + §7.2.0 [v0.4-E-2]：baseline 必须加载的 4 个 seed Skill。
# v0.4 集成阶段从 `skill.mbis.<snake_case>` 切到 Anthropic Skills 协议命名
# `mbis-<kebab-case>`（小写连字符，≤64 字符）。
REQUIRED_SEED_SKILL_IDS: Set[str] = {
    "mbis-building-assessment-workflow",
    "mbis-fact-kg-retrieval",
    "mbis-rule-obligation-derivation",
    "mbis-auxiliary-report-writer",
}


# blind 红线异常统一定义在包根 errors.py（与 agent.hooks 共用同一类，确保本层抛的
# SecurityError 能被编排层 except 捕获、不跨层漏接）。
from evo_agent_baseline.errors import SecurityError  # noqa: E402,F401  re-export


class ContractError(Exception):
    """固定上游契约被违反（缺必需表 / 缺必需子结构等）。"""


class SchemaContractError(Exception):
    """schema 契约违反（如 rule_card 出现 spec 未登记的新 artifact_key）。"""


# ===========================================================================
# 审计记录器
# ===========================================================================
@dataclass
class AuditLog:
    """灌库审计记录器。

    记录跳过的黑名单文件、warning、以及 provenance 所需的来源清单。
    `ComplianceAssessmentRun.input_guard_result` 与 §2.4 provenance 从这里取数。
    """

    warnings: List[str] = field(default_factory=list)
    skipped_denylist_files: List[str] = field(default_factory=list)
    agent_visible_sources: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        """记录一条 warning（不中断灌库）。"""
        self.warnings.append(message)

    def warn_skipped(self, skipped: Iterable[str]) -> None:
        """记录被跳过的黑名单文件（spec §4.2.2 audit.warn_skipped）。"""
        for name in sorted(skipped):
            if name not in self.skipped_denylist_files:
                self.skipped_denylist_files.append(name)
            self.warn(f"skipped W2 denylist file (not loaded into agent KG): {name}")

    def record_source(self, name: str) -> None:
        """登记一个 agent-visible 来源文件（spec §2.4 provenance）。"""
        if name not in self.agent_visible_sources:
            self.agent_visible_sources.append(name)

    def to_provenance(self) -> Dict[str, object]:
        """导出为 §2.4 provenance 片段。"""
        return {
            "agent_visible_sources": list(self.agent_visible_sources),
            "evaluator_only_sources_seen_and_skipped": list(self.skipped_denylist_files),
            "forbidden_source_check_passed": True,
            "warnings": list(self.warnings),
        }


# ===========================================================================
# §4.2.2 启动 guard
# ===========================================================================
def assert_agent_safe_input(
    run_dir: Path,
    explicit_targets: Optional[Set[str]] = None,
    audit: Optional[AuditLog] = None,
) -> AuditLog:
    """agent fact loader 启动 guard（spec §4.2.2）。

    行为（严格照 spec）：
    1. 扫描 `run_dir` 下所有 `*.parquet`；
    2. 与黑名单求交集，存在则记 audit warning 并跳过（不报错）；
    3. 若调用方 `explicit_targets` 显式包含黑名单文件 —— hard fail（SecurityError）；
    4. 任一必需 agent-visible 表缺失 —— ContractError。

    Args:
        run_dir: 灌库输入目录（gen_seed_<N>/ 或其 parquet 子目录）。
        explicit_targets: 调用方显式点名要加载的文件名集合；None 表示未显式点名。
        audit: 复用的审计记录器；None 时新建。

    Returns:
        AuditLog（含跳过的黑名单文件 / warning）。

    Raises:
        SecurityError: 显式 target 命中黑名单。
        ContractError: 缺必需表。
    """
    audit = audit or AuditLog()
    files = {p.name for p in run_dir.glob("*.parquet")}

    # 第 3 步：显式点名黑名单文件 —— hard fail。
    if explicit_targets:
        leaked = explicit_targets & AGENT_NORMATIVE_DENYLIST
        if leaked:
            raise SecurityError(
                f"agent loader cannot read normative projection tables: {sorted(leaked)}"
            )

    # 第 2 步：目录里出现黑名单文件 —— 记 warning 并跳过。
    forbidden = files & AGENT_NORMATIVE_DENYLIST
    audit.warn_skipped(forbidden)

    # 第 4 步：必需表缺失检查。
    for table in sorted(REQUIRED_AGENT_TABLES):
        if table not in files:
            raise ContractError(f"missing required agent-visible table: {table}")

    return audit


def is_agent_visible_table(filename: str) -> bool:
    """文件名是否在 agent 白名单内。"""
    return filename in AGENT_WORLDGEN_ALLOWLIST


def is_normative_denylist_table(filename: str) -> bool:
    """文件名是否在 W2 黑名单内。"""
    return filename in AGENT_NORMATIVE_DENYLIST


# ===========================================================================
# §4.7 G-002 禁止属性 scrub
# ===========================================================================
def scrub_forbidden_properties(props: Dict[str, object], node_label: str) -> Dict[str, object]:
    """写图前对节点 / 关系属性做禁止属性名检查（spec §4.7 G-002）。

    任一属性 key 命中 `FORBIDDEN_AGENT_PROPERTIES` —— 立即 hard fail。
    这是 blind 第二道防线：即便上游 parquet 带了 W2 字段、loader 漏过滤，
    也在写图前被拦住。

    Args:
        props: 待写入 Neo4j 的属性 dict。
        node_label: 节点 label（仅用于报错信息定位）。

    Returns:
        原 props（未命中则原样返回）。

    Raises:
        SecurityError: 命中禁止属性名。
    """
    leaked = set(props.keys()) & FORBIDDEN_AGENT_PROPERTIES
    if leaked:
        raise SecurityError(
            f"G-002: agent KG node :{node_label} carries forbidden W2 property "
            f"name(s) {sorted(leaked)} — evo-agent blind violation"
        )
    return props


def assert_label_allowed(label: str) -> None:
    """检查节点 label 是否被 §2.2.3 禁止（spec §4.7 隐含约束）。

    Raises:
        SecurityError: label 命中 `FORBIDDEN_AGENT_LABELS`。
    """
    if label in FORBIDDEN_AGENT_LABELS:
        raise SecurityError(
            f"G-002: forbidden W2 label :{label} must not appear in agent KG"
        )


# ===========================================================================
# §4.7 灌库质量门
# ===========================================================================
@dataclass
class QualityGateResult:
    """灌库质量门检查结果。"""

    gate_id: str
    passed: bool
    detail: str = ""


class QualityGateError(Exception):
    """灌库质量门 hard fail（spec §4.7）。"""

    def __init__(self, result: QualityGateResult) -> None:
        self.result = result
        super().__init__(f"{result.gate_id} hard fail: {result.detail}")


def gate_g001_denylist_table(explicit_targets: Optional[Set[str]]) -> QualityGateResult:
    """G-001：agent loader 显式读取 W2 黑名单表则 hard fail。"""
    if explicit_targets:
        leaked = explicit_targets & AGENT_NORMATIVE_DENYLIST
        if leaked:
            return QualityGateResult(
                "G-001", False, f"explicit denylist tables requested: {sorted(leaked)}"
            )
    return QualityGateResult("G-001", True)


def gate_g002_forbidden_property(node_label: str, props: Dict[str, object]) -> QualityGateResult:
    """G-002：agent KG 写入禁止属性名则 hard fail。"""
    leaked = set(props.keys()) & FORBIDDEN_AGENT_PROPERTIES
    if leaked:
        return QualityGateResult(
            "G-002", False, f":{node_label} carries forbidden props {sorted(leaked)}"
        )
    return QualityGateResult("G-002", True)


def gate_g003_rulecard_child_completeness(
    rule_card_id: str,
    has_applicability: bool,
    has_obligation_node: bool,
) -> QualityGateResult:
    """G-003：RuleCard 缺 ApplicabilityPredicate 或 ObligationNode 子结构则 hard fail。"""
    if not has_applicability:
        return QualityGateResult(
            "G-003", False, f"RuleCard {rule_card_id} missing ApplicabilityPredicate"
        )
    if not has_obligation_node:
        return QualityGateResult(
            "G-003", False, f"RuleCard {rule_card_id} missing ObligationNode"
        )
    return QualityGateResult("G-003", True)


def gate_g004_threshold_formula_preservation(
    threshold_regime_id: str,
    operator: Optional[str],
    upstream_has_formula: bool,
    formula_json: Optional[str],
) -> QualityGateResult:
    """G-004：operator='formula' 且上游有 formula 时 formula_json 为空则 hard fail。"""
    if operator == "formula" and upstream_has_formula:
        if formula_json is None or formula_json == "" or formula_json == "null":
            return QualityGateResult(
                "G-004", False,
                f"RuleThreshold {threshold_regime_id} lost upstream formula",
            )
    return QualityGateResult("G-004", True)


def gate_g005_obligation_edge_preservation(
    rule_card_id: str,
    upstream_edge_count: int,
    loaded_edge_count: int,
) -> QualityGateResult:
    """G-005：上游 obligation_graph.edges 非空但未落 ObligationEdge 则 hard fail。"""
    if upstream_edge_count > 0 and loaded_edge_count == 0:
        return QualityGateResult(
            "G-005", False,
            f"RuleCard {rule_card_id} had {upstream_edge_count} upstream edges, loaded 0",
        )
    return QualityGateResult("G-005", True)


def gate_g006_sidecar_projection_scrub(
    runtime_id: str,
    sidecar_props: Dict[str, object],
) -> QualityGateResult:
    """G-006：SidecarRuntimeRecord props 含 projection_id 或 hash 变体则 hard fail。"""
    banned = {"projection_id", "raw_projection_ref_hash", "projection_ref_hash"}
    leaked = set(sidecar_props.keys()) & banned
    if leaked:
        return QualityGateResult(
            "G-006", False,
            f"SidecarRuntimeRecord {runtime_id} not scrubbed: {sorted(leaked)}",
        )
    return QualityGateResult("G-006", True)


def gate_g007_source_quote_key(
    rule_card_id: str,
    source_quote_props: Dict[str, object],
) -> QualityGateResult:
    """G-007：SourceQuote 不含 source_quote_id 则 hard fail。"""
    if not source_quote_props.get("source_quote_id"):
        return QualityGateResult(
            "G-007", False, f"SourceQuote under {rule_card_id} missing source_quote_id"
        )
    return QualityGateResult("G-007", True)


def gate_g008_seed_skills(loaded_skill_ids: Set[str], baseline_allowed: Set[str]) -> QualityGateResult:
    """G-008：4 个 baseline seed Skill 任一未加载或 allowed_in_baseline=false 则 hard fail。"""
    missing = REQUIRED_SEED_SKILL_IDS - loaded_skill_ids
    if missing:
        return QualityGateResult(
            "G-008", False, f"required seed skills not loaded: {sorted(missing)}"
        )
    not_allowed = REQUIRED_SEED_SKILL_IDS - baseline_allowed
    if not_allowed:
        return QualityGateResult(
            "G-008", False, f"required seed skills with allowed_in_baseline=false: {sorted(not_allowed)}"
        )
    return QualityGateResult("G-008", True)


def raise_if_failed(result: QualityGateResult) -> QualityGateResult:
    """若质量门未通过则抛 `QualityGateError`，否则原样返回。"""
    if not result.passed:
        raise QualityGateError(result)
    return result


def assert_guard_config_consistent(guard_config: Dict[str, object]) -> None:
    """校验 `config/guard.yaml` 与本模块硬编码常量一致（spec→code 单向自检）。

    若两者漂移，说明 spec 转写出现分歧，立即 hard fail。

    Args:
        guard_config: 已 yaml.safe_load 的 guard.yaml 顶层 dict。

    Raises:
        ContractError: 配置与 spec 硬编码不一致。
    """
    ingestion = guard_config.get("ingestion", {}) or {}
    cfg_allow = set(ingestion.get("allow_agent_tables", []) or [])
    cfg_deny = set(ingestion.get("deny_agent_tables", []) or [])
    cfg_forbidden = set(ingestion.get("forbidden_agent_properties", []) or [])

    if cfg_allow != AGENT_WORLDGEN_ALLOWLIST:
        raise ContractError(
            f"guard.yaml allow_agent_tables drifted from spec §2.2.1: "
            f"diff={cfg_allow ^ AGENT_WORLDGEN_ALLOWLIST}"
        )
    if cfg_deny != AGENT_NORMATIVE_DENYLIST:
        raise ContractError(
            f"guard.yaml deny_agent_tables drifted from spec §2.2.2: "
            f"diff={cfg_deny ^ AGENT_NORMATIVE_DENYLIST}"
        )
    if cfg_forbidden != FORBIDDEN_AGENT_PROPERTIES:
        raise ContractError(
            f"guard.yaml forbidden_agent_properties drifted from spec §2.2.3: "
            f"diff={cfg_forbidden ^ FORBIDDEN_AGENT_PROPERTIES}"
        )


__all__ = [
    "AGENT_WORLDGEN_ALLOWLIST",
    "REQUIRED_AGENT_TABLES",
    "OPTIONAL_AGENT_TABLES",
    "AGENT_NORMATIVE_DENYLIST",
    "FORBIDDEN_AGENT_LABELS",
    "FORBIDDEN_AGENT_PROPERTIES",
    "REQUIRED_SEED_SKILL_IDS",
    "SecurityError",
    "ContractError",
    "SchemaContractError",
    "AuditLog",
    "assert_agent_safe_input",
    "is_agent_visible_table",
    "is_normative_denylist_table",
    "scrub_forbidden_properties",
    "assert_label_allowed",
    "QualityGateResult",
    "QualityGateError",
    "gate_g001_denylist_table",
    "gate_g002_forbidden_property",
    "gate_g003_rulecard_child_completeness",
    "gate_g004_threshold_formula_preservation",
    "gate_g005_obligation_edge_preservation",
    "gate_g006_sidecar_projection_scrub",
    "gate_g007_source_quote_key",
    "gate_g008_seed_skills",
    "raise_if_failed",
    "assert_guard_config_consistent",
]
