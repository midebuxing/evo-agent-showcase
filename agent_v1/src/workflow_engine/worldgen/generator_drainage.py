"""Worldgen generator — 排水子域 surrogate helper（spec 06 §5）.

从 generator.py 拆出（纯代码重组，零改行为）。4 个排水 index 公式派生：
堵塞 / 渗漏 / 错接 / 公共卫生风险。

依赖底座（generator_base）：_sigmoid / _age_norm。
"""

from __future__ import annotations

import random

from workflow_engine.worldgen.models import DrainageState, DriverState
from workflow_engine.worldgen.generator_base import _age_norm, _sigmoid


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _compute_drainage_blockage_index(driver: DriverState, age_years: float) -> float:
    """spec 06 §5 blockage_index = clip(sigmoid(1.1*drainage_fault_propensity + 0.8*maintenance + 0.4*age - 0.9), 0, 1).

    W0-004 (2026-05-21)：DriverState 字段名 drainage_fault_propensity 已对齐 spec；
    age_years 来自 BuildingContext（spec 04 §4）。
    """
    age_norm = _age_norm(age_years)
    raw = (
        1.1 * driver.drainage_fault_propensity
        + 0.8 * driver.maintenance_deficit_index
        + 0.4 * age_norm
        - 0.9
    )
    return max(0.0, min(1.0, _sigmoid(raw)))


def _compute_drainage_leakage_index(driver: DriverState, age_years: float) -> float:
    """spec 06 §5 leakage_index = clip(sigmoid(0.8*age + 0.8*workmanship + 0.6*moisture - 1.0), 0, 1).

    W0-004: age_years 来自 BuildingContext（spec 04 §4）。
    """
    age_norm = _age_norm(age_years)
    raw = (
        0.8 * age_norm
        + 0.8 * driver.workmanship_deficit_index
        + 0.6 * driver.moisture_ingress_index
        - 1.0
    )
    return max(0.0, min(1.0, _sigmoid(raw)))


def _compute_drainage_misconnection_present(driver: DriverState) -> bool:
    """spec 06 §5 misconnection_present = sigmoid(1.2*workmanship + 1.0*alteration - 1.1) > 0.5."""
    raw = (
        1.2 * driver.workmanship_deficit_index
        + 1.0 * driver.alteration_propensity
        - 1.1
    )
    return _sigmoid(raw) > 0.5


def _compute_drainage_public_health_risk_index(
    blockage_index: float,
    leakage_index: float,
    misconnection_present: bool,
) -> float:
    """spec 06 §5 public_health_risk = clip(0.45*blockage + 0.35*leakage + 0.40*misconnection_bool, 0, 1)."""
    raw = (
        0.45 * blockage_index
        + 0.35 * leakage_index
        + 0.40 * (1.0 if misconnection_present else 0.0)
    )
    return max(0.0, min(1.0, raw))


# ============================================================================ #
# DEBT-049 Phase3 U5 §2.1：drainage method_class 确定性选取（P1-P4 总函数）+ air/ball 物理观测
# ============================================================================ #
# rule-blind：选取决策变量全是排水物理量（DrainageState 数值场 + segment_type），零法规知识；
# air/ball 生成压力损失/球通物理观测（非裸标签）。W0 不读 rule_cards/method_keys。
#
# 生效阈 0.5 硬冻结（misconnection 现码已按 sigmoid>0.5 阈值化；此处把同一 >0.5 生效闸统一施于
# leakage_index/blockage_index），改须走 spec revision + manifest（§2.1 note）。

# §2.1 生效阈（硬冻结）
_DRAINAGE_INDEX_ACTIVE_THRESHOLD = 0.5

# §2.1 S2.5「防死档」标定：drainage 域 fragment 的错接/非法改动倾向（alteration_propensity）采样上界。
# 背景：generate_driver（T-17b 阶段）对全域 fragment 用同一套通用采样区间，alteration 上界仅
# 0.4+0.3·age_factor（≈0.4~0.7）；misconnection 公式 sigmoid(1.2·workmanship + 1.0·alteration − 1.1)>0.5
# 因 workmanship 亦被通用采样封顶 0.4 → 只在 w≈0.4 且 a≈0.7 的极角触发 → 实测 200 楼 misconnection≈0
# → §2.1 P1 smoke_test 供给实质死档。此常量把 **drainage 域 fragment** 的 alteration 上界上调，使
# misconnection（→smoke_test）注入率从 ~0 升到个位数百分比、S2.5 每方法非零可达。
# **drainage-isolated（零跨域涟漪）**：alteration 在 drainage fragment 上**仅**喂 misconnection 公式——
#   UBW 态只在 ubw_signal 机制生成、drainage fragment 用 drainage_fault 机制故无 UBW 态；drainage 机制
#   score 走占位 rng（不读 alteration）；condition severity 走 mechanism.severity_index（不读 alteration）。
#   故本上调**只**改 misconnection→smoke 供给，不动 blockage/leakage/air/ball/water/非 drainage 域。
# **rule-blind**：排水错接（misconnection）是 HK 旧楼真实高发缺陷（FT_DRAINAGE_MISCONNECTION_V1 模板本就
#   建模它），上调其物理注入倾向是物理真实性补全，**非**为让某卡闭合（W0 不读 rule_cards；method 选取仍是
#   §2.1 P1-P4 读物理态的总函数）。硬冻结、禁现场调参（改须走 spec revision + manifest）。
# 标定值 0.8（S2.5 四 seed 实测 seed 449-452 / N=200 定档）：§2.1 五方法（smoke/water/air/ball/cctv）
# + air 两压力档 seed 级全非零（smoke 21-36/seed），达「防死档」。**实测对照 0.8 vs 0.9 的 truth
# pass 带逐 seed 逐字节相同（22.5-24.4%）→ 本 misconnection 注入率常量对 truth 带无影响**（带由池
# 结构决定、非 misconnection 计数），故取更「小幅」的 0.8。truth 带 ~24% 在 20-40% 门内（历史 ~31%
# 是 pre-U5 旧 v11 池、spec 明记「不可比」，非回归基准）。
_DRAINAGE_DRIVER_ALTERATION_HI = 0.8

# §2.1b air 压力损失生成公式常量（硬冻结）；取值范围 [0, 60] mmH2O。
AIR_LOSS_BASE_MMH2O = 2.0
AIR_LOSS_GAIN_MMH2O = 45.0
AIR_LOSS_CAP_MMH2O = 60.0
AIR_LOSS_JITTER_MMH2O = 1.5

# §2.1b ball 球通生成公式常量（硬冻结）。
BALL_JITTER = 0.15
BALL_PASS_THRESHOLD = 0.65

# §2.1b air 两压力档（CoP §5.6.5(b)，由 is_underground 定死；acceptable_drop 是判 fail 容差）。
_AIR_TEST_PRESSURE_MMH2O_ABOVE_GROUND = 38
_AIR_TEST_ACCEPTABLE_DROP_MMH2O_ABOVE_GROUND = 0
_AIR_TEST_PRESSURE_MMH2O_UNDERGROUND = 100
_AIR_TEST_ACCEPTABLE_DROP_MMH2O_UNDERGROUND = 25
# §2.1b air 档 duration 档常量（CoP §5.6.5(b)：地面上 hold 3 min / 地下 window 5 min；spec §2.1b
# 分档参数表 + spec §2.1b note「test_pressure/duration 同为档常量」）。是类别/上下文档常量（非主
# 读数、不入 pass/fail 公式），与 test_pressure/acceptable_drop 同进 qualifiers 供审计/S2.5 一致性核。
# 统一进单一 qualifier 键 `duration_min`（上下带同键、保 qualifier 形状均匀）；语义区分（hold vs window）
# 由常量名承载。硬冻结、禁现场调参（须走 spec revision + manifest）。
_AIR_TEST_HOLD_DURATION_MIN_ABOVE_GROUND = 3
_AIR_TEST_WINDOW_DURATION_MIN_UNDERGROUND = 5


def _select_drainage_method_class(drainage: DrainageState) -> str:
    """§2.1 P1-P4 确定性优先级阶梯（first-match-wins 总函数，无随机）。

    返回单值 method_class ∈ {smoke_test, water_test, air_test, ball_test, drainage_cctv}：
      P1  misconnection_present == True                              → smoke_test  （§5.6.5(d) 通煙）
      P2  否则 leakage_index > 0.5                                   → water_test  （§5.6.5(c) 水測）
      P3a 否则 blockage_index > 0.5 且 segment_type=="soil_pipe"     → air_test    （§5.6.5(b) 空氣，立管气密）
      P3b 否则 blockage_index > 0.5 且 segment_type=="branch_connection" → ball_test （§5.6.5(a) 球測，支管）
      P4  否则（三缺陷均未生效）                                     → drainage_cctv（§5.6.5(e) CCTV）

    多缺陷共现由优先级序确定性消解（misconnection > leakage > blockage）。
    """
    if drainage.misconnection_present:
        return "smoke_test"
    if drainage.leakage_index > _DRAINAGE_INDEX_ACTIVE_THRESHOLD:
        return "water_test"
    if drainage.blockage_index > _DRAINAGE_INDEX_ACTIVE_THRESHOLD:
        if drainage.segment_type == "soil_pipe":
            return "air_test"
        if drainage.segment_type == "branch_connection":
            return "ball_test"
    return "drainage_cctv"


def _air_test_qualifiers(is_underground: bool) -> dict:
    """§2.1b air 档常量（进 MeasurementRecord.qualifiers 作类别/上下文 metadata，非主读数）。

    四字段：is_underground / test_pressure_mmH2O / acceptable_drop_mmH2O / duration_min。
    duration_min 为档常量（地面上 hold 3 min，地下 window 5 min，CoP §5.6.5(b)）——非 pass/fail
    公式输入，仅审计/S2.5 一致性核用。
    """
    if is_underground:
        return {
            "is_underground": True,
            "test_pressure_mmH2O": _AIR_TEST_PRESSURE_MMH2O_UNDERGROUND,
            "acceptable_drop_mmH2O": _AIR_TEST_ACCEPTABLE_DROP_MMH2O_UNDERGROUND,
            "duration_min": _AIR_TEST_WINDOW_DURATION_MIN_UNDERGROUND,
        }
    return {
        "is_underground": False,
        "test_pressure_mmH2O": _AIR_TEST_PRESSURE_MMH2O_ABOVE_GROUND,
        "acceptable_drop_mmH2O": _AIR_TEST_ACCEPTABLE_DROP_MMH2O_ABOVE_GROUND,
        "duration_min": _AIR_TEST_HOLD_DURATION_MIN_ABOVE_GROUND,
    }


def _compute_air_test_pressure_loss_mmH2O(
    drainage: DrainageState, rng: random.Random
) -> float:
    """§2.1b air 主读数（窗口内绝对压降，float，value_num）——压降随缺陷严重度单调上升。

    ``defect_drive = clip(0.6*leakage_index + 0.4*blockage_index, 0, 1)``；
    ``pressure_loss = round(clip(BASE + GAIN*defect_drive + jitter, 0, CAP), 2)``。
    rng = _drainage_airball_obs_rng(drainage_id)（独立 domain-separated 子流）。
    """
    defect_drive = _clip01(0.6 * drainage.leakage_index + 0.4 * drainage.blockage_index)
    jitter = rng.uniform(-AIR_LOSS_JITTER_MMH2O, AIR_LOSS_JITTER_MMH2O)
    value = AIR_LOSS_BASE_MMH2O + AIR_LOSS_GAIN_MMH2O * defect_drive + jitter
    return round(max(0.0, min(AIR_LOSS_CAP_MMH2O, value)), 2)


def _compute_ball_test_pass(drainage: DrainageState, rng: random.Random) -> bool:
    """§2.1b ball 主读数（球通过与否，bool，value_bool）——球通随堵塞上升越易失败。

    ``ball_fail_score = clip(blockage_index + jitter, 0, 1)``；
    ``pass = ball_fail_score < BALL_PASS_THRESHOLD``。
    rng = _drainage_airball_obs_rng(drainage_id)（独立 domain-separated 子流）。
    """
    jitter = rng.uniform(-BALL_JITTER, BALL_JITTER)
    ball_fail_score = _clip01(drainage.blockage_index + jitter)
    return bool(ball_fail_score < BALL_PASS_THRESHOLD)
