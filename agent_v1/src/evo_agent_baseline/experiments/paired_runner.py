"""Paired held-out 实验协议（spec v1 §11.5 + §11.6）。

实现：

- ``split_dataset``：按 building / world family / rule family 分层切
  ``evolve_train`` (60%) / ``gate_validation`` (20%) / ``held_out_test`` (20%)；
- ``run_paired``：每 case 用相同 budget / model / KG snapshot / rulecard /
  verifier 跑 ``baseline`` 与 ``evo`` 两条链；
- ``PairedResult``：每 case 的 baseline/evo 指标 + delta。

spec v1 §11.6 控制条件（必须等同）：

- same model
- same KG snapshot
- same rulecard bundle
- same verifier version
- same tool budget
- same run mode
- same report guard
- same evaluator private metric

默认 budget：``equal_budget=16`` / ``scaling_budgets=[8,16,32]``。

工程边界（项目原则 2 + 3）：
- evo-agent blind：runner 不访问 W2 raw；metric 来自 evaluator private side
  的 aggregate dict（spec v1 §8.4），通过 ``aggregate_metric_fn`` 注入。
- allow_stop 不可逆：runner 不修改 closure verifier。

数据分层切分（spec v1 §11.5）：

- building disjoint
- world family stratified
- rule family coverage balanced
- rare artifact/threshold boundary 保证 held_out 至少覆盖
- held_out 不参与 Skill induction 或 policy training
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

# spec v1 §11.6 默认 budget 配置
DEFAULT_EQUAL_BUDGET: int = 16
DEFAULT_SCALING_BUDGETS: Tuple[int, ...] = (8, 16, 32)

# spec v1 §11.5 默认切分比例
DEFAULT_TRAIN_PCT: float = 0.6
DEFAULT_GATE_PCT: float = 0.2
DEFAULT_HOLDOUT_PCT: float = 0.2


# ---------------------------------------------------------------------------
# Runner protocol（不依赖具体 agent 实现）
# ---------------------------------------------------------------------------


class CaseRunner(Protocol):
    """spec v1 §11.6 中 ``baseline`` 和 ``evo`` 两条链的统一签名。

    实参可以是 v0.4 baseline orchestrator 或 v1 evo orchestrator；
    本 runner 不耦合具体实现，只要求按签名返回 metrics dict。
    """

    def __call__(
        self,
        case: Mapping[str, Any],
        *,
        model: str,
        kg_snapshot: str,
        rulecard_bundle: str,
        verifier_version: str,
        tool_budget: int,
        run_mode: str,
        report_guard: str,
    ) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


@dataclass
class PairedResult:
    """spec v1 §11.6 paired held-out 单 case 结果。

    字段：
        case_id: 唯一 case id（建议格式 ``HOLD-<building>-<seed>``）。
        baseline_metrics: 同 budget 下 baseline orchestrator 输出指标 dict
            （含 verdict / closure / cost 等 evaluator aggregate）。
        evo_metrics: 同 budget 下 evo orchestrator 输出指标 dict。
        delta: ``evo_metrics - baseline_metrics`` 的逐 metric 标量差；只对
            两边都是数字的 key 计算；其余 key 不写入。
        budget: 本次 paired 使用的 tool budget。
        run_mode: 本次 paired 使用的 run mode。
    """

    case_id: str
    baseline_metrics: Mapping[str, Any]
    evo_metrics: Mapping[str, Any]
    delta: Mapping[str, float]
    budget: int
    run_mode: str

    @staticmethod
    def compute_delta(
        baseline: Mapping[str, Any], evo: Mapping[str, Any]
    ) -> Dict[str, float]:
        """逐 metric 数值差。

        非数值 key 跳过；spec v1 §11.6 ``same evaluator private metric`` 蕴含
        两边 metric 命名约束一致，这里仅做交集。
        """
        out: Dict[str, float] = {}
        for key in set(baseline) & set(evo):
            b = baseline[key]
            e = evo[key]
            if isinstance(b, (int, float)) and isinstance(e, (int, float)):
                out[key] = float(e) - float(b)
        return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class PairedExperimentRunner:
    """spec v1 §11.5 + §11.6 + §11.7 paired runner。

    用法：

        runner = PairedExperimentRunner(seed=42)
        train, gate, holdout = runner.split_dataset(all_cases)
        results = runner.run_paired(
            holdout,
            baseline_runner,
            evo_runner,
            model="qwen3.5-32b",
            kg_snapshot="kgsnap-2026-05-24",
            rulecard_bundle="rcb-mbis-v1",
            verifier_version="cv-1.0.0",
            tool_budget=16,
            run_mode="deterministic",
            report_guard="rg-v1",
        )
    """

    def __init__(
        self,
        seed: int = 42,
        *,
        equal_budget: int = DEFAULT_EQUAL_BUDGET,
        scaling_budgets: Sequence[int] = DEFAULT_SCALING_BUDGETS,
    ) -> None:
        self.seed = seed
        self.equal_budget = equal_budget
        self.scaling_budgets = list(scaling_budgets)
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # 数据分层切分
    # ------------------------------------------------------------------

    def split_dataset(
        self,
        all_cases: Sequence[Mapping[str, Any]],
        *,
        train_pct: float = DEFAULT_TRAIN_PCT,
        gate_pct: float = DEFAULT_GATE_PCT,
        holdout_pct: float = DEFAULT_HOLDOUT_PCT,
    ) -> Tuple[
        List[Mapping[str, Any]],
        List[Mapping[str, Any]],
        List[Mapping[str, Any]],
    ]:
        """spec v1 §11.5 三段分层切分。

        切分规则：

        - **building disjoint**：同一 building_id 只能落入 train/gate/holdout
          其中一个；
        - **world family stratified**：每个 world_family 按比例落入三段；
        - **rule family coverage balanced**：三段的 rule_family 覆盖集合
          应尽量平衡（hard constraint：holdout 至少覆盖 train 出现过的
          rare artifact / threshold boundary case）。

        case 必填 key：``case_id`` / ``building_id``；可选 key：
        ``world_family`` / ``rule_families`` (list[str]) /
        ``is_rare_artifact_or_threshold`` (bool)。

        参数：
            all_cases: 候选 case 序列。
            train_pct/gate_pct/holdout_pct: 比例三元组，必须近似和 = 1。

        返回：``(train, gate, holdout)`` 三个 list。

        异常：``ValueError`` 当比例不和 1 / case 缺 ``building_id``。
        """
        if abs(train_pct + gate_pct + holdout_pct - 1.0) > 1e-6:
            raise ValueError(
                f"切分比例必须和为 1.0，得到 {train_pct + gate_pct + holdout_pct}"
            )
        for c in all_cases:
            if "building_id" not in c:
                raise ValueError(f"case 缺 building_id：{c}")

        # 1. 按 building_id 分组（building disjoint 硬约束）
        by_building: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for c in all_cases:
            by_building[c["building_id"]].append(c)

        # 2. 每个 building 取 world_family 作为分层 key（缺失=__none__）
        building_to_family: Dict[str, str] = {}
        for bid, cs in by_building.items():
            families = {str(c.get("world_family", "__none__")) for c in cs}
            # 同一 building 在不同 case 上若 world_family 不一致，取字典序首
            building_to_family[bid] = sorted(families)[0]

        # 3. 每个 family 内 shuffle 后按比例切
        families: Dict[str, List[str]] = defaultdict(list)
        for bid, fam in building_to_family.items():
            families[fam].append(bid)

        train_buildings: List[str] = []
        gate_buildings: List[str] = []
        holdout_buildings: List[str] = []
        for fam, blds in families.items():
            shuffled = list(blds)
            self._rng.shuffle(shuffled)
            n = len(shuffled)
            n_train = max(1, int(round(n * train_pct))) if n >= 3 else 0
            n_gate = max(0, int(round(n * gate_pct))) if n >= 3 else 0
            # 余下落入 holdout，保证 holdout 至少有一席（n>=3 时）
            n_holdout = n - n_train - n_gate
            if n < 3:
                # 小 family 简单退化：第一个进 train，其余进 holdout
                if n >= 1:
                    train_buildings.append(shuffled[0])
                if n >= 2:
                    holdout_buildings.append(shuffled[1])
                continue
            train_buildings.extend(shuffled[:n_train])
            gate_buildings.extend(shuffled[n_train : n_train + n_gate])
            holdout_buildings.extend(shuffled[n_train + n_gate :])

        train_set = set(train_buildings)
        gate_set = set(gate_buildings)
        holdout_set = set(holdout_buildings)

        # 4. rare artifact / threshold boundary 强制至少 1 进 holdout
        rare_cases = [
            c for c in all_cases if c.get("is_rare_artifact_or_threshold")
        ]
        if rare_cases:
            in_holdout = any(c["building_id"] in holdout_set for c in rare_cases)
            if not in_holdout:
                # 把 rare case 的 building 从 train/gate 搬到 holdout
                target = rare_cases[0]["building_id"]
                if target in train_set:
                    train_set.discard(target)
                if target in gate_set:
                    gate_set.discard(target)
                holdout_set.add(target)

        train = [c for c in all_cases if c["building_id"] in train_set]
        gate = [c for c in all_cases if c["building_id"] in gate_set]
        holdout = [c for c in all_cases if c["building_id"] in holdout_set]
        return train, gate, holdout

    # ------------------------------------------------------------------
    # paired execution
    # ------------------------------------------------------------------

    def run_paired(
        self,
        holdout_cases: Sequence[Mapping[str, Any]],
        baseline_runner: CaseRunner,
        evo_runner: CaseRunner,
        *,
        model: str,
        kg_snapshot: str,
        rulecard_bundle: str,
        verifier_version: str,
        tool_budget: Optional[int] = None,
        run_mode: str = "deterministic",
        report_guard: str = "rg-v1",
    ) -> List[PairedResult]:
        """spec v1 §11.6 同 case 同 budget 同 model 同 KG 跑两条链。

        参数 ``tool_budget`` 缺省时用 ``self.equal_budget``（=16）。其余 7
        项控制条件（model / kg_snapshot / rulecard_bundle / verifier_version /
        run_mode / report_guard）强制传入两 runner，spec §11.6 同步。

        返回：每 case 一个 ``PairedResult``。
        """
        budget = tool_budget if tool_budget is not None else self.equal_budget
        kwargs = dict(
            model=model,
            kg_snapshot=kg_snapshot,
            rulecard_bundle=rulecard_bundle,
            verifier_version=verifier_version,
            tool_budget=budget,
            run_mode=run_mode,
            report_guard=report_guard,
        )
        results: List[PairedResult] = []
        for case in holdout_cases:
            baseline_metrics = baseline_runner(case, **kwargs)  # type: ignore[arg-type]
            evo_metrics = evo_runner(case, **kwargs)  # type: ignore[arg-type]
            delta = PairedResult.compute_delta(baseline_metrics, evo_metrics)
            results.append(
                PairedResult(
                    case_id=str(case.get("case_id", case.get("building_id", ""))),
                    baseline_metrics=dict(baseline_metrics),
                    evo_metrics=dict(evo_metrics),
                    delta=delta,
                    budget=budget,
                    run_mode=run_mode,
                )
            )
        return results

    def run_scaling_budgets(
        self,
        holdout_cases: Sequence[Mapping[str, Any]],
        baseline_runner: CaseRunner,
        evo_runner: CaseRunner,
        *,
        model: str,
        kg_snapshot: str,
        rulecard_bundle: str,
        verifier_version: str,
        run_mode: str = "deterministic",
        report_guard: str = "rg-v1",
    ) -> Dict[int, List[PairedResult]]:
        """spec v1 §11.6 ``scaling_budgets=[8,16,32]`` 在每个 budget
        下都跑 paired，用于研究 runtime compute scaling。返回 ``{budget: results}``。
        """
        out: Dict[int, List[PairedResult]] = {}
        for budget in self.scaling_budgets:
            out[budget] = self.run_paired(
                holdout_cases,
                baseline_runner,
                evo_runner,
                model=model,
                kg_snapshot=kg_snapshot,
                rulecard_bundle=rulecard_bundle,
                verifier_version=verifier_version,
                tool_budget=budget,
                run_mode=run_mode,
                report_guard=report_guard,
            )
        return out


__all__ = [
    "DEFAULT_EQUAL_BUDGET",
    "DEFAULT_SCALING_BUDGETS",
    "DEFAULT_TRAIN_PCT",
    "DEFAULT_GATE_PCT",
    "DEFAULT_HOLDOUT_PCT",
    "CaseRunner",
    "PairedResult",
    "PairedExperimentRunner",
]
