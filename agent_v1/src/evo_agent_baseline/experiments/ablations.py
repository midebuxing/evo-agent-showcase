"""Ablation 设计（spec v1 §11.7）。

spec v1 §11.7 必须跑的 ablation：

| variant | 含义 |
|---------|------|
| ``baseline_static`` | v0.4 frozen，无 evo |
| ``trace_only`` | 记录 EvoRunTrace，不加载 Skill/Policy |
| ``policy_only`` | 加载 EvoPolicy，不加载 OperationalSkills |
| ``skill_only`` | 加载 OperationalSkills，使用 baseline policy |
| ``feedback_only_policy`` | 用 sanitized feedback 调 policy，不生成 Skill |
| ``full_evo`` | Replay + Skill + Policy + Feedback |
| ``full_evo_no_candidate_floor`` | 禁止发布；仅内部验证 candidate floor 必要性 |
| ``skill_disabled_<id>`` | 单 Skill attribution |

任务范围聚焦 5 个核心 ablation（spec v1 §11.7 前 4 个 + ``full_evo``）：

- baseline only
- baseline + EvoRunTrace only
- baseline + EvoPolicy only
- baseline + Skill only
- full evo

``full_evo_no_candidate_floor`` 通过 ``AblationConfig.no_candidate_floor=True``
表达，但 spec v1 §11.7 末段：``只能在隔离实验中跑，不能进入 production，
且结果不得作为 release gain``，因此 ``AblationResult.publishable=False``。

工程边界（项目原则 3）：本模块不修改 closure verifier；ablation 只切换
传给 ``evo_runner`` 的 component 开关，不影响 allow_stop 判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
)

from evo_agent_baseline.experiments.paired_runner import (
    DEFAULT_EQUAL_BUDGET,
    CaseRunner,
    PairedExperimentRunner,
    PairedResult,
)


# spec v1 §11.7 全部 variant 枚举（5 个必跑 + 3 个扩展）。
AblationVariant = Literal[
    "baseline_static",
    "trace_only",
    "policy_only",
    "skill_only",
    "feedback_only_policy",
    "full_evo",
    "full_evo_no_candidate_floor",
    "skill_disabled",
]


@dataclass
class AblationConfig:
    """spec v1 §11.7 单 variant 配置。

    字段：
        variant: AblationVariant 枚举。
        enable_trace_capture: 是否记录 EvoRunTrace；spec v1 §11.7
            ``trace_only`` 起即需为 True。
        enable_skill_runtime: 是否加载 active OperationalSkills；
            ``skill_only`` / ``full_evo`` / ``full_evo_no_candidate_floor`` = True。
        enable_policy_runtime: 是否加载 EvoPolicyVersion；
            ``policy_only`` / ``full_evo`` / ``full_evo_no_candidate_floor`` /
            ``feedback_only_policy`` = True。
        enable_feedback_broker: 是否消费 sanitized feedback；
            ``feedback_only_policy`` / ``full_evo`` = True。
        no_candidate_floor: spec v1 §11.7 ``full_evo_no_candidate_floor``
            专属；其他 variant 必须 False；True 时本配置 not publishable。
        disabled_skill_id: ``skill_disabled`` variant 专属；指定一个
            skill_id 被禁用，用于 single-skill attribution。
        notes: 自由文本备注（不写入任何 broker/feedback 输出）。
    """

    variant: AblationVariant
    enable_trace_capture: bool = False
    enable_skill_runtime: bool = False
    enable_policy_runtime: bool = False
    enable_feedback_broker: bool = False
    no_candidate_floor: bool = False
    disabled_skill_id: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        # spec v1 §11.7 ``full_evo_no_candidate_floor`` 只允许同名 variant
        if self.no_candidate_floor and self.variant != "full_evo_no_candidate_floor":
            raise ValueError(
                "no_candidate_floor=True 只允许 variant=full_evo_no_candidate_floor"
            )
        if self.variant == "skill_disabled" and not self.disabled_skill_id:
            raise ValueError("skill_disabled variant 必须提供 disabled_skill_id")

    @property
    def publishable(self) -> bool:
        """spec v1 §11.7 末段：``full_evo_no_candidate_floor`` 不可作为 release gain。"""
        return not self.no_candidate_floor


# spec v1 §11.7 5 个核心 variant 的默认配置注册表
DEFAULT_ABLATIONS: Dict[str, AblationConfig] = {
    "baseline_static": AblationConfig(
        variant="baseline_static",
        enable_trace_capture=False,
        enable_skill_runtime=False,
        enable_policy_runtime=False,
        enable_feedback_broker=False,
        notes="spec v1 §11.7 v0.4 frozen，无 evo 组件",
    ),
    "trace_only": AblationConfig(
        variant="trace_only",
        enable_trace_capture=True,
        enable_skill_runtime=False,
        enable_policy_runtime=False,
        enable_feedback_broker=False,
        notes="spec v1 §11.7 只采 trace，不加载 Skill/Policy",
    ),
    "policy_only": AblationConfig(
        variant="policy_only",
        enable_trace_capture=True,
        enable_skill_runtime=False,
        enable_policy_runtime=True,
        enable_feedback_broker=False,
        notes="spec v1 §11.7 加载 EvoPolicy，不加载 Skill",
    ),
    "skill_only": AblationConfig(
        variant="skill_only",
        enable_trace_capture=True,
        enable_skill_runtime=True,
        enable_policy_runtime=False,
        enable_feedback_broker=False,
        notes="spec v1 §11.7 加载 Skill，使用 baseline policy",
    ),
    "full_evo": AblationConfig(
        variant="full_evo",
        enable_trace_capture=True,
        enable_skill_runtime=True,
        enable_policy_runtime=True,
        enable_feedback_broker=True,
        notes="spec v1 §11.7 Replay + Skill + Policy + Feedback 全开",
    ),
}


def list_default_ablations() -> List[AblationConfig]:
    """spec v1 §11.7 5 个必跑 variant 的默认配置列表。"""
    return [
        DEFAULT_ABLATIONS["baseline_static"],
        DEFAULT_ABLATIONS["trace_only"],
        DEFAULT_ABLATIONS["policy_only"],
        DEFAULT_ABLATIONS["skill_only"],
        DEFAULT_ABLATIONS["full_evo"],
    ]


@dataclass
class AblationResult:
    """单 ablation 的执行结果。

    字段：
        config: 复制的 AblationConfig（便于回溯）。
        paired_results: 该 ablation 与 ``baseline_runner_ref`` 的 paired
            held-out 结果列表。
        publishable: 复制自 config.publishable；spec v1 §11.7 末段约束。
        aggregate_delta: 跨 case 的平均 delta（按 metric key 聚合）。
    """

    config: AblationConfig
    paired_results: List[PairedResult]
    publishable: bool
    aggregate_delta: Mapping[str, float]


def _aggregate_delta(results: Sequence[PairedResult]) -> Dict[str, float]:
    if not results:
        return {}
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for r in results:
        for k, v in r.delta.items():
            sums[k] = sums.get(k, 0.0) + v
            counts[k] = counts.get(k, 0) + 1
    return {k: sums[k] / counts[k] for k in sums}


def run_ablation(
    config: AblationConfig,
    paired_runner: PairedExperimentRunner,
    *,
    holdout_cases: Sequence[Mapping[str, Any]],
    baseline_runner_ref: CaseRunner,
    ablation_runner_factory: Callable[[AblationConfig], CaseRunner],
    model: str,
    kg_snapshot: str,
    rulecard_bundle: str,
    verifier_version: str,
    tool_budget: int = DEFAULT_EQUAL_BUDGET,
    run_mode: str = "deterministic",
    report_guard: str = "rg-v1",
) -> AblationResult:
    """执行单个 ablation：用 ``ablation_runner_factory(config)`` 生成 evo 侧
    runner，与 ``baseline_runner_ref`` 做 paired held-out。

    参数：
        config: AblationConfig 实例。
        paired_runner: 复用上层 PairedExperimentRunner（保种子一致）。
        holdout_cases: held-out 数据集（spec v1 §11.5 切分输出第 3 段）。
        baseline_runner_ref: 始终使用 v0.4 frozen baseline runner。
        ablation_runner_factory: 接收 config 并返回符合 ``CaseRunner`` 协议
            的 runner；工厂内部按 config 字段开关 trace/skill/policy/feedback
            组件。
        其他参数：spec v1 §11.6 8 项控制条件中除 evaluator 私域 metric 外
            的 7 项。

    返回：``AblationResult``，其中 ``publishable`` 复制自 config。
    """
    ablation_runner = ablation_runner_factory(config)
    paired_results = paired_runner.run_paired(
        holdout_cases,
        baseline_runner_ref,
        ablation_runner,
        model=model,
        kg_snapshot=kg_snapshot,
        rulecard_bundle=rulecard_bundle,
        verifier_version=verifier_version,
        tool_budget=tool_budget,
        run_mode=run_mode,
        report_guard=report_guard,
    )
    return AblationResult(
        config=config,
        paired_results=paired_results,
        publishable=config.publishable,
        aggregate_delta=_aggregate_delta(paired_results),
    )


__all__ = [
    "AblationVariant",
    "AblationConfig",
    "DEFAULT_ABLATIONS",
    "AblationResult",
    "list_default_ablations",
    "run_ablation",
]
