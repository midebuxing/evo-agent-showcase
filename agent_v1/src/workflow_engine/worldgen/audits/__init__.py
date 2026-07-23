"""W1 输出反作弊 / 反泄漏 audit 套件（DEBT-030 解除条件）.

W1 spec 01 §6 "反作弊 / 反泄漏机制（W1 输出审计红线）" 列 6 项 audit；
现役（DEBT-020 Audit2）已有 2 项：``_counterfactual_audit.py`` /
``_profile_switch_audit.py``。本子包补齐剩 5 项：

- ``schema_firewall``         — 字段名禁止 token 静态扫
- ``projection_rule_use``     — worldgen / sidecar 主代码不读 rule_card 静态扫
- ``round_trip_parse``        — bundle 写出 / 重读 byte-identical
- ``leakage_surface``         — surface tags 反推 rule_family probe
- ``held_out_split``          — family / building stratified split utility

落地 release_batch CI 跑（spec / 跟踪表 §6 DEBT-030 解除条件 #1）.
"""

from workflow_engine.worldgen.audits.held_out_split import (
    DEFAULT_RARE_FAMILY_THRESHOLD,
    DEFAULT_RATIOS,
    EVOLVE_TRAIN,
    GATE_VALIDATION,
    HELD_OUT_TEST,
    HeldOutSplit,
    SPLIT_NAMES,
    SplitAuditReport,
    held_out_family_split,
    validate_held_out_split,
)
from workflow_engine.worldgen.audits.projection_rule_use import (
    FORBIDDEN_IMPORT_PREFIXES,
    ImportViolation,
    ProjectionRuleUseReport,
    WHITELIST_IMPORTS,
    projection_rule_use_audit,
)
from workflow_engine.worldgen.audits.leakage_surface import (
    DEFAULT_THRESHOLD,
    LeakageSurfaceReport,
    PROBE_RANDOM_SEED,
    extract_w1_surface_features,
    leakage_on_surface_audit,
)
from workflow_engine.worldgen.audits.round_trip_parse import (
    BundleKind,
    BundleRoundTripResult,
    RoundTripAuditReport,
    round_trip_parse_audit,
    round_trip_parse_audit_from_json,
)
from workflow_engine.worldgen.audits.schema_firewall import (
    FORBIDDEN_FIELD_TOKENS,
    FieldViolation,
    SchemaFirewallReport,
    WHITELIST_FIELDS,
    schema_firewall_audit,
)

__all__ = [
    "BundleKind",
    "BundleRoundTripResult",
    "DEFAULT_RARE_FAMILY_THRESHOLD",
    "DEFAULT_RATIOS",
    "DEFAULT_THRESHOLD",
    "EVOLVE_TRAIN",
    "FORBIDDEN_FIELD_TOKENS",
    "FORBIDDEN_IMPORT_PREFIXES",
    "FieldViolation",
    "GATE_VALIDATION",
    "HELD_OUT_TEST",
    "HeldOutSplit",
    "ImportViolation",
    "LeakageSurfaceReport",
    "PROBE_RANDOM_SEED",
    "ProjectionRuleUseReport",
    "RoundTripAuditReport",
    "SPLIT_NAMES",
    "SchemaFirewallReport",
    "SplitAuditReport",
    "WHITELIST_FIELDS",
    "WHITELIST_IMPORTS",
    "extract_w1_surface_features",
    "held_out_family_split",
    "leakage_on_surface_audit",
    "projection_rule_use_audit",
    "round_trip_parse_audit",
    "round_trip_parse_audit_from_json",
    "schema_firewall_audit",
    "validate_held_out_split",
]
