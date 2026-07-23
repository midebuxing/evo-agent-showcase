"""evo-agent baseline 确定性闭包验证器子包（spec §6）。

闭包验证器是 agent runtime 的底线层组件：
输入 RuleSlice + FactPack，输出 ClosureValidationResult；
禁止输入 NormativeProjection / expected_verdict 等 W2 参考真值。
确定性、无 LLM 调用、无 Neo4j 依赖 —— 输入纯 DTO，纯 Python。

模块：
- schema.py            —— 闭包内部专用小类型（公开 schema 在 contracts.py）
- fact_binding.py      —— fact 索引、canonicalization、target scoping、冲突处理（§6.4）
- applicability.py     —— 适用性评估（§6.3.2）
- threshold_eval.py    —— 阈值比较器 + 单位规则 + formula handler（§6.3.5）
- obligation_deriver.py—— 各义务源 → Obligation 推导（§6.3.3~§6.3.10）
- validator.py         —— 主入口 + helpers + allow_stop + obligation_id（§6.5~§6.7）
"""

from .schema import (
    ApplicabilityResult,
    HighRiskItem,
    ObligationEdgeDTO,
    ObligationNodeDTO,
    VerifierConfig,
)
from .validator import (
    ForbiddenSourceError,
    assert_no_forbidden_sources,
    build_machine_report,
    compute_obligation_id,
    display_obligation_id,
    find_high_risk_items,
    sort_and_dedupe_obligations,
    summarize,
    validate_building_closure,
)

__all__ = [
    "validate_building_closure",
    "VerifierConfig",
    "ApplicabilityResult",
    "HighRiskItem",
    "ObligationNodeDTO",
    "ObligationEdgeDTO",
    "ForbiddenSourceError",
    "assert_no_forbidden_sources",
    "compute_obligation_id",
    "display_obligation_id",
    "find_high_risk_items",
    "sort_and_dedupe_obligations",
    "summarize",
    "build_machine_report",
]
