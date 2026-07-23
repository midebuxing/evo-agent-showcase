"""W1 held-out family / neighbor-family split audit (DEBT-030 audit 3).

W1 spec 01 §6 表第 6 行红线 + evo-agent v1 spec §11.5 实验切分约束：
> Held-out family / neighbor-family split: 训练 / 评估 batch 按法规 family
> 分割时，W1 不应"看到"哪些 family 是 held-out.

切分契约（evo-agent v1 spec §11.5）::

    evolve_train:     60%
    gate_validation:  20%
    held_out_test:    20%

约束：
- building disjoint（三组 building_id 不重叠）
- fragment family stratified（每个 family 按比例切到三组）
- rare boundary 保证（rare family 全归 held_out）
- audit 函数返回 split 时不主动 leak family label——W1 worldgen 只消费
  ``building_id`` 集合，不消费 ``family_labels`` 参数

设计
====
``held_out_family_split`` 是 deterministic split utility（按 seed RNG 内部 shuffle）.
``validate_held_out_split`` 是 audit 函数检查 split 是否满足约束.

跨进程 / 跑批 CI 用法
=====================
release_batch 实验入口先做 split，把三个 building_id 集合喂给 worldgen / evo runner，
audit 在 split 后立刻调一次：

    split = held_out_family_split(buildings, family_labels, seed=0)
    report = validate_held_out_split(split, family_labels)
    assert report.passed, report.violations
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Set, Tuple


SplitName = str

EVOLVE_TRAIN: SplitName = "evolve_train"
GATE_VALIDATION: SplitName = "gate_validation"
HELD_OUT_TEST: SplitName = "held_out_test"

SPLIT_NAMES: Tuple[SplitName, SplitName, SplitName] = (
    EVOLVE_TRAIN,
    GATE_VALIDATION,
    HELD_OUT_TEST,
)
DEFAULT_RATIOS: Tuple[float, float, float] = (0.60, 0.20, 0.20)
DEFAULT_RARE_FAMILY_THRESHOLD: int = 3


@dataclass(frozen=True)
class HeldOutSplit:
    """spec §11.5 三段 split 结果。building_ids 三组保证 disjoint."""

    evolve_train_building_ids: Tuple[str, ...]
    gate_validation_building_ids: Tuple[str, ...]
    held_out_test_building_ids: Tuple[str, ...]
    ratios: Tuple[float, float, float]
    seed: int
    rare_family_threshold: int

    def all_building_ids(self) -> Set[str]:
        return (
            set(self.evolve_train_building_ids)
            | set(self.gate_validation_building_ids)
            | set(self.held_out_test_building_ids)
        )

    def building_ids_for(self, split: SplitName) -> Tuple[str, ...]:
        if split == EVOLVE_TRAIN:
            return self.evolve_train_building_ids
        if split == GATE_VALIDATION:
            return self.gate_validation_building_ids
        if split == HELD_OUT_TEST:
            return self.held_out_test_building_ids
        raise ValueError(f"unknown split name {split!r}")


@dataclass
class SplitAuditReport:
    passed: bool
    violations: List[str] = field(default_factory=list)
    n_buildings: int = 0
    n_families: int = 0
    rare_families: Tuple[str, ...] = ()
    actual_ratios: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    family_distribution: Dict[SplitName, Dict[str, int]] = field(default_factory=dict)
    tolerance: float = 0.0


def held_out_family_split(
    building_ids: Iterable[str],
    family_labels: Mapping[str, str],
    ratios: Tuple[float, float, float] = DEFAULT_RATIOS,
    rare_family_threshold: int = DEFAULT_RARE_FAMILY_THRESHOLD,
    seed: int = 0,
) -> HeldOutSplit:
    """按 family stratified 切 (evolve_train, gate_validation, held_out_test).

    参数
    ----
    building_ids: 待切分 building_id 集合.
    family_labels: ``building_id`` → ``family_id`` 映射.
        缺失 family 的 building 视为 ``"__unknown__"`` family.
    ratios: ``(train, val, holdout)`` 比例，必须正和 = 1.0 ± 1e-6.
    rare_family_threshold: family 总 building 数 < 该阈值视为 rare，
        全部归 ``held_out_test`` 保证 rare boundary 覆盖.
    seed: deterministic 随机种子.

    返回 ``HeldOutSplit``。三组 building_id 保证 disjoint。
    """
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError(f"ratios must sum to 1.0, got {sum(ratios)}")
    if any(r < 0 for r in ratios):
        raise ValueError(f"ratios must be non-negative, got {ratios}")

    train_r, val_r, hold_r = ratios
    rng = random.Random(seed)

    building_list = sorted(building_ids)  # determinism 入口
    family_to_buildings: Dict[str, List[str]] = {}
    for bid in building_list:
        fam = family_labels.get(bid, "__unknown__")
        family_to_buildings.setdefault(fam, []).append(bid)

    train_set: List[str] = []
    val_set: List[str] = []
    holdout_set: List[str] = []

    for family, members in sorted(family_to_buildings.items()):
        shuffled = list(members)
        rng.shuffle(shuffled)
        if len(members) < rare_family_threshold:
            # rare family 全归 holdout 保证 rare boundary 在 held_out 至少覆盖
            holdout_set.extend(shuffled)
            continue
        n = len(shuffled)
        n_train = int(round(n * train_r))
        n_val = int(round(n * val_r))
        # 保证最后 holdout 至少 1 个（rare-family 已上路；非 rare 这里也保兜底）
        n_hold = n - n_train - n_val
        if n_hold < 1:
            n_hold = 1
            if n_val > 0:
                n_val -= 1
            else:
                n_train -= 1
        train_set.extend(shuffled[:n_train])
        val_set.extend(shuffled[n_train : n_train + n_val])
        holdout_set.extend(shuffled[n_train + n_val :])

    return HeldOutSplit(
        evolve_train_building_ids=tuple(sorted(train_set)),
        gate_validation_building_ids=tuple(sorted(val_set)),
        held_out_test_building_ids=tuple(sorted(holdout_set)),
        ratios=ratios,
        seed=seed,
        rare_family_threshold=rare_family_threshold,
    )


def validate_held_out_split(
    split: HeldOutSplit,
    family_labels: Mapping[str, str],
    tolerance: float = 0.05,
) -> SplitAuditReport:
    """验证 split 满足 §11.5 约束.

    检查项：
    - building disjoint
    - 三组比例接近目标 ``split.ratios``（允许 ±tolerance）
    - rare family（count < threshold）全在 ``held_out_test``
    - non-rare family 在 ``held_out_test`` 至少有 1 个 building
    - non-rare family 在 ``evolve_train`` 至少有 1 个 building
    """
    violations: List[str] = []

    train_ids = set(split.evolve_train_building_ids)
    val_ids = set(split.gate_validation_building_ids)
    hold_ids = set(split.held_out_test_building_ids)

    # 1. building disjoint
    if train_ids & val_ids:
        violations.append(f"train ∩ val non-empty: {sorted(train_ids & val_ids)}")
    if train_ids & hold_ids:
        violations.append(f"train ∩ holdout non-empty: {sorted(train_ids & hold_ids)}")
    if val_ids & hold_ids:
        violations.append(f"val ∩ holdout non-empty: {sorted(val_ids & hold_ids)}")

    total = len(train_ids) + len(val_ids) + len(hold_ids)
    if total == 0:
        return SplitAuditReport(
            passed=len(violations) == 0,
            violations=violations,
            n_buildings=0,
            n_families=0,
            tolerance=tolerance,
        )

    actual = (
        len(train_ids) / total,
        len(val_ids) / total,
        len(hold_ids) / total,
    )

    # 2. 比例容差检查（small N 不强求）
    if total >= 20:
        for i, (a, tgt) in enumerate(zip(actual, split.ratios)):
            if abs(a - tgt) > tolerance:
                violations.append(
                    f"ratio[{SPLIT_NAMES[i]}] = {a:.3f} 偏离目标 {tgt:.3f}"
                    f" 超过容差 {tolerance:.3f}"
                )

    # 3. family-level 检查
    family_to_buildings: Dict[str, List[str]] = {}
    for bid in train_ids | val_ids | hold_ids:
        fam = family_labels.get(bid, "__unknown__")
        family_to_buildings.setdefault(fam, []).append(bid)

    rare_families: List[str] = []
    family_dist: Dict[SplitName, Dict[str, int]] = {n: {} for n in SPLIT_NAMES}

    for family, members in sorted(family_to_buildings.items()):
        in_train = [b for b in members if b in train_ids]
        in_val = [b for b in members if b in val_ids]
        in_hold = [b for b in members if b in hold_ids]
        family_dist[EVOLVE_TRAIN][family] = len(in_train)
        family_dist[GATE_VALIDATION][family] = len(in_val)
        family_dist[HELD_OUT_TEST][family] = len(in_hold)

        if len(members) < split.rare_family_threshold:
            rare_families.append(family)
            if in_train or in_val:
                violations.append(
                    f"rare family {family!r} ({len(members)} buildings) "
                    f"漏到 non-holdout split: train={len(in_train)} val={len(in_val)}"
                )
            continue
        # non-rare family
        if not in_hold:
            violations.append(
                f"family {family!r} ({len(members)} buildings) 在 held_out 0 覆盖 "
                f"(违反 rare boundary 覆盖红线)"
            )
        if not in_train:
            violations.append(
                f"family {family!r} ({len(members)} buildings) 在 evolve_train 0 覆盖 "
                f"(stratified 失败)"
            )

    return SplitAuditReport(
        passed=len(violations) == 0,
        violations=violations,
        n_buildings=total,
        n_families=len(family_to_buildings),
        rare_families=tuple(sorted(rare_families)),
        actual_ratios=actual,
        family_distribution=family_dist,
        tolerance=tolerance,
    )


__all__ = [
    "DEFAULT_RARE_FAMILY_THRESHOLD",
    "DEFAULT_RATIOS",
    "EVOLVE_TRAIN",
    "GATE_VALIDATION",
    "HELD_OUT_TEST",
    "HeldOutSplit",
    "SPLIT_NAMES",
    "SplitAuditReport",
    "held_out_family_split",
    "validate_held_out_split",
]
