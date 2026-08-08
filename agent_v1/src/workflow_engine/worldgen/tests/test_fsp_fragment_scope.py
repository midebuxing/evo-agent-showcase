"""波次二 #31「1b fsp 解耦」：结构表现系数的作用域断言（2026-08-05 三线门定案）。

治的病：`populate_derived_flags` 曾拿**全楼** max severity 重算一个楼级 fsp 标量，
再把它发给**每一个** condition。后果有两重，第二重比第一重严重：

1. **非追加**——同栋加一个高严重度片段，既有构件的 fsp 派生族跟着翻。
2. **张冠李戴**——守则 §4.3.3(c) 把结构表现系数定义在**結構構件**上（该构件自身的
   極限狀態抗力／計算荷載效應之比），法规里不存在"全楼 FSP"。把最差构件的比值复制给
   结构达标的构件，再据 §4.3.4 对它签发「緊急補救工程＋立即向建築事務監督報告」，
   那是**错误的事实陈述**，不是"偏安全的估计"。（假 violated 是诬告。）

本文件是**语义层＋病原回归层**（边界层由 `scripts/verify_rng_isolation_pairing.py --step 1b`
的字节配对承担，两层缺一即漏：字节尺只答"哪里可以红"，不答"红出来的值对不对"）。

三条硬断言（与样本量无关，故不受池大小影响）：

- ① 有 `ratio.fsp.structural_performance` 量测的片段，其 `index.fsp.estimate` **逐值等于**该量测；
- ② `assessment.fsp.below_required_safety` 相对 1b 前**只许 True→False 单向翻转**；
- ③ 无该量测的片段**必须**落 `not_applicable` + `no_assessment`（1b 前是死分支，0/862 触发）。

⚠️ 关于 ② 的"1b 前"基线：这里**复刻了被删掉的那段旧公式**当反事实对照。
   这与 `test_rng_isolation.py` 顶上"不复刻实现"的纪律不冲突——复刻的是一段**已经删除、
   不会再演进**的历史代码，它正是"对照 HEAD 产物"这句验收要求在单测里的等价形式；
   如果改成断言当前实现，这条测试就退化成同义反复。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pytest

from workflow_engine.worldgen.generator import (
    _FSP_FLOOR_PROXY,
    _FSP_MEASUREMENT_SLOT_ID,
    generate_world_bundle,
    populate_derived_flags,
)
from workflow_engine.worldgen.generator_base import _age_norm
from workflow_engine.worldgen.registry import _build_registry_bundle

_FSP_FLAG = "assessment.fsp.below_required_safety"
_FSP_INDEX = "index.fsp.estimate"

# 多个 seed ＝ 属性测试的"输入分布"。单 seed 容易落在"恰好没变"的巧合上。
_SEEDS: Tuple[int, ...] = (42, 301, 401, 99, 7)


@pytest.fixture(scope="module")
def _registries():
    return _build_registry_bundle()


def _fsp_measurement_by_fragment(world) -> Dict[str, float]:
    """片段 → 该片段自身的 Step 8 结构表现系数量测值。"""
    out: Dict[str, float] = {}
    for m in world.measurements:
        if (
            m.slot_id == _FSP_MEASUREMENT_SLOT_ID
            and m.value_num is not None
            and m.value_enum != "not_applicable"
            and m.target_ref not in out
        ):
            out[m.target_ref] = float(m.value_num)
    return out


def _legacy_building_level_fsp(world) -> float:
    """1b 之前 `populate_derived_flags` 的那三行（已删除）——反事实基线。

    generator.py 旧码逐字：
        age_norm_value = _age_norm(world.building.age_years)
        max_severity = max((c.severity_index for c in world.conditions), default=0.0)
        fsp_estimate = max(0.0, min(2.0, 1.20 - 0.30 * max_severity - 0.10 * age_norm_value))
    """
    age_norm_value = _age_norm(world.building.age_years)
    max_severity = max((c.severity_index for c in world.conditions), default=0.0)
    return max(0.0, min(2.0, 1.20 - 0.30 * max_severity - 0.10 * age_norm_value))


# ---------------------------------------------------------------------------
# ① 有量测的片段：index.fsp.estimate 逐值等于该片段自身的量测
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", _SEEDS)
def test_index_fsp_estimate_equals_own_fragment_measurement(_registries, seed):
    world = generate_world_bundle(
        {}, _registries, seed=seed, building_index=0, fragment_count=10
    )
    measured = _fsp_measurement_by_fragment(world)
    checked = 0
    for condition in world.conditions:
        index_value = condition.derived_outcomes.risk_index_values.get(_FSP_INDEX)
        own = measured.get(condition.fragment_id)
        if own is None:
            # 无量测 ⇒ 该键必须缺席（Dict[str, float] 写不下 not_applicable，
            #          写默认值等于在数值通道里重犯"把没评估过伪装成评估过"）
            assert index_value is None, (
                f"{condition.fragment_id} 无 fsp 量测，却写出了 {_FSP_INDEX}={index_value}"
            )
            continue
        assert index_value == pytest.approx(round(own, 4)), (
            f"{condition.fragment_id} 的 {_FSP_INDEX}={index_value} "
            f"与本片段量测 {own} 不符 —— 派生层没在读 Step 8 的产物"
        )
        checked += 1
    assert checked > 0, "本 seed 一个带 fsp 量测的片段都没有，断言 ① 成了空护栏"


@pytest.mark.parametrize("seed", _SEEDS)
def test_flag_agrees_with_own_measurement_against_floor(_registries, seed):
    """派生 flag 本身也须等于「本片段量测 < fsp_floor_proxy」，不只是索引值对。"""
    world = generate_world_bundle(
        {}, _registries, seed=seed, building_index=0, fragment_count=10
    )
    measured = _fsp_measurement_by_fragment(world)
    for condition in world.conditions:
        own = measured.get(condition.fragment_id)
        flag = condition.derived_outcomes.assessment_flags.get(_FSP_FLAG)
        if own is None:
            continue
        assert flag is (own < _FSP_FLOOR_PROXY), (
            f"{condition.fragment_id}: 量测 {own} vs floor {_FSP_FLOOR_PROXY} "
            f"应得 {own < _FSP_FLOOR_PROXY}，实得 {flag}"
        )


# ---------------------------------------------------------------------------
# ② 单向性：相对 1b 前只许 True→False
# ---------------------------------------------------------------------------
def test_flag_flips_are_true_to_false_only(_registries):
    """反向翻转（旧 False → 新 True）在数学上不可能：

    片段 max severity ≤ 全楼 max severity 且楼龄同 ⇒ fsp_片段 ≥ fsp_楼级
    ⇒ `fsp < floor` 只可能由 True 变 False。出现一条反向即证明实现接错了片段。
    """
    forward = 0
    reverse: List[str] = []
    for seed in _SEEDS:
        world = generate_world_bundle(
            {}, _registries, seed=seed, building_index=0, fragment_count=10
        )
        legacy_fsp = _legacy_building_level_fsp(world)
        legacy_flag = legacy_fsp < _FSP_FLOOR_PROXY
        for condition in world.conditions:
            new_flag = condition.derived_outcomes.assessment_flags.get(_FSP_FLAG)
            if new_flag is True and legacy_flag is False:
                reverse.append(f"seed={seed} {condition.fragment_id}")
            elif new_flag is not True and legacy_flag is True:
                forward += 1
    assert not reverse, f"出现反向翻转（旧 False → 新 True），实现接错片段：{reverse[:5]}"
    assert forward > 0, (
        "抽样池里一条 True→False 都没有 —— 要么池太小、要么根本没改到，本断言成了空护栏"
    )


# ---------------------------------------------------------------------------
# ③ 无量测片段：not_applicable + no_assessment（1b 前的死分支）
# ---------------------------------------------------------------------------
def _strip_fsp_measurements(world, fragment_id: str):
    """去掉某片段的 fsp 量测 ＝ 造一个"没做过结构评估"的片段。

    真实池里这种片段本来就存在（三池分别 8/14/7 个），但它是否出现随 seed 漂；
    直接构造才能让断言 ③ 每次都真正跑到。
    """
    stripped = world.model_copy(deep=True)
    stripped.measurements = [
        m
        for m in stripped.measurements
        if not (m.target_ref == fragment_id and m.slot_id == _FSP_MEASUREMENT_SLOT_ID)
    ]
    return populate_derived_flags(stripped)


@pytest.mark.parametrize("seed", _SEEDS)
def test_fragment_without_assessment_lands_not_applicable(_registries, seed):
    world = generate_world_bundle(
        {}, _registries, seed=seed, building_index=0, fragment_count=10
    )
    measured = _fsp_measurement_by_fragment(world)
    target = next(
        (c.fragment_id for c in world.conditions if c.fragment_id in measured), None
    )
    assert target is not None, "本 seed 没有带 fsp 量测的片段，无从构造对照"

    after = _strip_fsp_measurements(world, target)
    hit = [c for c in after.conditions if c.fragment_id == target]
    assert hit, "构造后目标片段的 condition 不见了"
    for condition in hit:
        assert condition.derived_outcomes.assessment_flags.get(_FSP_FLAG) == "not_applicable", (
            f"{target} 无结构评估，flag 应为 not_applicable，实得 "
            f"{condition.derived_outcomes.assessment_flags.get(_FSP_FLAG)!r}"
        )
        assert (
            condition.derived_outcomes.fallback_reasons.get(_FSP_FLAG) == "no_assessment"
        ), "spec 06 §11 unknown_policy 的 no_assessment 原因码没落"
        assert _FSP_INDEX not in condition.derived_outcomes.risk_index_values, (
            "无评估的片段不许写出 index.fsp.estimate"
        )
    # 其余片段不受牵连（去掉一个片段的量测不是全楼事件）
    others = {
        c.fragment_id: c.derived_outcomes.risk_index_values.get(_FSP_INDEX)
        for c in after.conditions
        if c.fragment_id != target
    }
    for fragment_id, value in others.items():
        own = measured.get(fragment_id)
        if own is not None:
            assert value == pytest.approx(round(own, 4)), (
                f"去掉 {target} 的量测后，{fragment_id} 的 fsp 也变了 —— 又是楼级串扰"
            )


# ---------------------------------------------------------------------------
# 病原回归层：加片段对既有片段的 fsp 派生族零扰动（属性测试）
# ---------------------------------------------------------------------------
def _fsp_family(world) -> Dict[str, Tuple[object, object, object, object]]:
    """既有片段的 fsp 派生族快照：flag ＋ 索引值 ＋ 原因码 ＋ 同吃 fsp 的 row 1。"""
    return {
        c.fragment_id: (
            c.derived_outcomes.assessment_flags.get(_FSP_FLAG),
            c.derived_outcomes.risk_index_values.get(_FSP_INDEX),
            c.derived_outcomes.fallback_reasons.get(_FSP_FLAG),
            c.derived_outcomes.risk_flags.get("risk.building_safety.emergency"),
        )
        for c in world.conditions
    }


def _with_extra_fragment(world, severity: float, fsp_value: Optional[float]):
    """前插一个新片段（含 condition／可选 fsp 量测），再重跑派生层。

    🔴 用**前插**不是追加 —— 追加型对照在"顺序敏感但值正确"的实现上会绿（同仓教训：
    测试跑在缺陷不可能显现的输入上）。而对本病原（全楼 max）两种插法都会红，
    前插只是严格更强。

    新片段的 severity 取满值：旧码下它必然顶高全楼 max ⇒ 既有片段的 fsp 全部下移，
    这条测试在旧码上**必红**（已做坍缩变异对照，见实施记录）。
    """
    mutated = world.model_copy(deep=True)
    base_fragment = mutated.fragments[-1]
    base_condition = mutated.conditions[-1]

    new_fragment = base_fragment.model_copy(deep=True)
    new_fragment.fragment_id = base_fragment.fragment_id + "-EXTRA"
    new_condition = base_condition.model_copy(deep=True)
    new_condition.condition_id = base_condition.condition_id + "-EXTRA"
    new_condition.fragment_id = new_fragment.fragment_id
    new_condition.severity_index = severity

    mutated.fragments = [new_fragment] + list(mutated.fragments)
    mutated.conditions = [new_condition] + list(mutated.conditions)

    if fsp_value is not None:
        template = next(
            (m for m in mutated.measurements if m.slot_id == _FSP_MEASUREMENT_SLOT_ID),
            None,
        )
        if template is not None:
            extra = template.model_copy(deep=True)
            extra.measurement_id = template.measurement_id + "-EXTRA"
            extra.target_ref = new_fragment.fragment_id
            extra.value_num = fsp_value
            mutated.measurements = [extra] + list(mutated.measurements)
    return populate_derived_flags(mutated)


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize(
    "severity,fsp_value",
    [
        (1.0, 0.10),   # 新片段极差且自带量测
        (1.0, None),   # 新片段极差且**没做评估**（走 not_applicable 分支）
        (0.0, 1.90),   # 新片段完好——反方向也不许扰动
    ],
)
def test_adding_a_fragment_does_not_perturb_existing_fsp_family(
    _registries, seed, severity, fsp_value
):
    world = generate_world_bundle(
        {}, _registries, seed=seed, building_index=0, fragment_count=10
    )
    before = _fsp_family(world)
    after_world = _with_extra_fragment(world, severity, fsp_value)
    after = _fsp_family(after_world)

    for fragment_id, snapshot in before.items():
        assert after[fragment_id] == snapshot, (
            f"加一个片段之后 {fragment_id} 的 fsp 派生族变了：{snapshot} → {after[fragment_id]}"
            "（#31 病原：跨片段聚合）"
        )
