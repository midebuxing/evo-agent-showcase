"""中立版本化 canonical profile（Block C，spec 草案 v4 §C.0-C.9）。

跨层唯一交汇契约层：measure/slot/artifact/unit/formula/qualifier/deadline 七维
canonical registry + Decimal ingress + NFC + in/not_in 排序 + qualifier 八键
namespace 映射 + canonical_json 确定性序列化。

分层红线（附录 C 依赖 DAG）：本包**不 import** `evo_agent_baseline.closure` /
`workflow_engine` / `evo_agent_baseline.eval` 任一侧；两侧（及旁路 evaluator）
向下 import 本包。故本包是真正中立的顶层包（sibling to evo_agent_baseline /
workflow_engine），而非嵌在 closure/ 下——否则 workflow_engine 侧（Block B，
Phase 1）消费它会构成 workflow_engine → evo_agent_baseline 的跨包 import，破
CLAUDE.md「两包互不 import」红线。

Phase 0 = 地基层：实现全套 C.0-C.9 机制 + 代表性种子 registry 内容；真实全量
registry 内容填充属 Phase 1（spec「落地顺序」Block B/C）。
"""

from __future__ import annotations

from canonical_profile.profile import (
    CANONICAL_PROFILE_ID,
    CanonResult,
    CanonicalProfileError,
    CanonicalRegistry,
    QUALIFIER_NAMESPACE,
    canonical_decimal_str,
    canonical_json,
    canonicalize_artifact,
    canonicalize_deadline,
    canonicalize_formula,
    canonicalize_measure,
    canonicalize_qualifier,
    canonicalize_slot,
    canonicalize_unit,
    in_not_in_sort,
    is_empty_source_value,
    nfc,
    parse_json_decimal,
    qualifier_fingerprint,
    sha256_hex_24,
)

__all__ = [
    "CANONICAL_PROFILE_ID",
    "CanonResult",
    "CanonicalProfileError",
    "CanonicalRegistry",
    "QUALIFIER_NAMESPACE",
    "canonical_decimal_str",
    "canonical_json",
    "canonicalize_artifact",
    "canonicalize_deadline",
    "canonicalize_formula",
    "canonicalize_measure",
    "canonicalize_qualifier",
    "canonicalize_slot",
    "canonicalize_unit",
    "in_not_in_sort",
    "is_empty_source_value",
    "nfc",
    "parse_json_decimal",
    "qualifier_fingerprint",
    "sha256_hex_24",
]
