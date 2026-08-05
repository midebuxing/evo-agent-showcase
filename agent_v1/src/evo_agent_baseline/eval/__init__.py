"""evo-agent baseline 评测闭环子包（spec §8 / §10）。

evaluator 读取 W2 NormativeProjection / expected_verdict 独立阅卷。
evaluator-only：agent runtime 不得 import 本子包，不得访问 evaluator truth store。

- truth_loader.py  —— evaluator-only，加载 W2 参考真值
- mapper.py        —— agent obligation → family verdict 映射 + fine→coarse crosswalk
- metrics.py       —— verdict / coverage / threshold / closure 指标
- leakage_audit.py —— 答案泄漏审计（spec §8.4.5）
- report.py        —— 离线评测报告（spec §8.5）
- family_crosswalk_v1.json —— W2 16 coarse → rule_card 44 fine 对照表（spec §8.3.2）
"""

from evo_agent_baseline.eval.leakage_audit import (
    LeakageAuditResult,
    LeakageFinding,
    audit_leakage,
)
from evo_agent_baseline.eval.mapper import (
    AgentFamilyVerdict,
    CrosswalkError,
    FamilyCrosswalk,
    aggregate_agent_family_verdicts,
    default_crosswalk_path,
    load_crosswalk,
)
from evo_agent_baseline.eval.metrics import (
    ClosureMetrics,
    CoverageMetrics,
    ThresholdMetrics,
    VerdictMetrics,
    compute_closure_metrics,
    compute_coverage_metrics,
    compute_threshold_metrics,
    compute_verdict_metrics,
)
from evo_agent_baseline.eval.report import (
    EvalInputs,
    evaluate_run,
    make_eval_run_id,
    write_eval_report,
)
from evo_agent_baseline.eval.truth_loader import (
    TruthBundle,
    TruthLoadError,
    load_truth_bundle,
)

__all__ = [
    # truth_loader
    "TruthBundle",
    "TruthLoadError",
    "load_truth_bundle",
    # mapper
    "AgentFamilyVerdict",
    "CrosswalkError",
    "FamilyCrosswalk",
    "aggregate_agent_family_verdicts",
    "default_crosswalk_path",
    "load_crosswalk",
    # metrics
    "VerdictMetrics",
    "CoverageMetrics",
    "ThresholdMetrics",
    "ClosureMetrics",
    "compute_verdict_metrics",
    "compute_coverage_metrics",
    "compute_threshold_metrics",
    "compute_closure_metrics",
    # leakage_audit
    "LeakageAuditResult",
    "LeakageFinding",
    "audit_leakage",
    # report
    "EvalInputs",
    "evaluate_run",
    "make_eval_run_id",
    "write_eval_report",
]
