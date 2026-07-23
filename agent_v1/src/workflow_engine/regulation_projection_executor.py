from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "CONFLICT_GROUPS",
    "resolve_family_conflict",
    "ConflictResolutionResult",
    "execute_projection_batch_v2",    # building-centric v2 entry（OLD execute_projection_batch 已删）
    "UNKNOWN_REASON_CODES",
    "UnknownReasonCode",
    "derive_unknown_reason_code",
    "has_known_family_match",
    "is_sidecar_only_fact_pattern",
    "detect_binding_registry_gap",
    "detect_unit_incompatible",
    "THRESHOLD_REGIMES",
    "ThresholdRegime",
    "compute_threshold_width",
    "classify_threshold_regime",
    # T-#3 integration
    "build_threshold_evaluation",
    "evaluate_fragment_projection_candidates",
    "FragmentProjectionResult",
    # Missing #2: v2 entry NormativeProjection builder
    "build_normative_projections_for_world",
    "build_normative_projections_for_world_with_coverage_control",
    "derive_sidecar_join_status",
    "MECHANISM_FAMILY_TO_PROJECTION_FAMILIES",
]

# ---------- spec 07 §4.1 conflict_group named entities ----------

CONFLICT_GROUPS: Dict[str, Dict[str, Any]] = {
    "structural_external_surface": {
        "members": [
            "crack",
            "spall_rebar",
            "hollowing_delamination",
            "detachment",
            "moisture_seepage",
        ],
        "selector": "highest_applicability_score_with_required_slots",
    },
    "drainage": {
        "members": [
            "drainage_blockage",
            "drainage_leakage",
            "drainage_misconnection",
        ],
        "selector": "allow_multi_if_distinct_segment_else_highest_risk",
    },
    "ubw_fire": {
        "members": [
            "ubw_alteration",
            "fire_safety_deficiency",
        ],
        "selector": "allow_multi_if_distinct_component_else_highest_risk",
    },
    "assessment_repair": {
        "members": [
            "structural_assessment_deficit",
            "repair_validation_failure",
        ],
        "selector": "allow_multi_if_causal_chain",
    },
}

# Type alias for resolve_family_conflict return value
ConflictResolutionResult = Tuple[List[str], Optional[str]]


def resolve_family_conflict(
    candidate_families: List[Dict[str, Any]],
    conflict_group_id: Optional[str],
) -> ConflictResolutionResult:
    """spec 07 §4.2 5 种竞争处理 + §4.1 conflict_group selector 实施.

    candidate_families：每个 entry 含 family_id, applicability_score (float),
    target_component_id, required_slots_present (bool)。

    conflict_group_id：normative_projection_registry.conflict_group 字段值。

    Returns:
        (selected_family_ids, unknown_reason_code)
        - selected_family_ids: 选中的 family id list
        - unknown_reason_code: 若无法解析返回 spec §5 reason code；能解析则返回 None
    """
    # spec §4.2 行 1：no candidates at all
    if not candidate_families:
        return [], "no_known_family_match"

    # 过滤出 applicable (required_slots_present=True)
    applicable = [c for c in candidate_families if c.get("required_slots_present")]
    if not applicable:
        return [], "no_known_family_match"

    # spec §4.2 行 2：exactly one applicable
    if len(applicable) == 1:
        return [applicable[0]["family_id"]], None

    # spec §4.2 行 3：multiple applicable with distinct target components
    # → allow multi-family for drainage / ubw_fire / assessment_repair
    target_components = [c.get("target_component_id") for c in applicable]
    if (
        len(set(target_components)) == len(target_components)
        and conflict_group_id in ("drainage", "ubw_fire", "assessment_repair")
    ):
        return [c["family_id"] for c in applicable], None

    # spec §4.2 行 4：one family is strict parent of other → select child
    parent_child = _find_parent_child_pair(applicable)
    if parent_child is not None:
        _, child_family_id = parent_child
        return [child_family_id], None

    # spec §4.2 行 5：same group cannot resolve
    # structural_external_surface uses highest_applicability_score selector as fallback
    if conflict_group_id == "structural_external_surface":
        winner = max(applicable, key=lambda c: c["applicability_score"])
        return [winner["family_id"]], None

    return [], "multi_family_conflict"


def _find_parent_child_pair(
    applicable: List[Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    """识别 family 间 parent/child 关系（spec §4.2 行 4）。

    TODO: 后续工单（family hierarchy 填表）在此插入 parent/child 索引。
    当前 placeholder 返回 None。
    """
    return None


# ---------- T-24: spec 06 §16.3 unknown_reason_code routing ----------

# W2-014: spec 08 §2.1 priority 1-13 完整枚举 13 项；顺序按 spec 表
# （封口 spec 08 §2.1 line 50-64 + 顶层封口总则 row `unknown_reason_code`）
UNKNOWN_REASON_CODES: Tuple[str, ...] = (
    "multi_family_conflict",                # priority 1
    "no_known_family_match",                # priority 2
    "coverage_unimplemented_domain",        # priority 3
    "binding_registry_gap",                 # priority 4
    "measurement_family_unimplemented",     # priority 5
    "method_class_unimplemented",           # priority 6
    "unsupported_material_system",          # priority 7
    "unsupported_component_type",           # priority 8
    "unsupported_damage_pattern",           # priority 9
    "unsupported_location_context",         # priority 10
    "unit_incompatible",                    # priority 11
    "projection_binding_incompatible",      # priority 12
    "sidecar_only_fact_pattern",            # priority 13
)

try:
    from typing import Literal as _Literal
    UnknownReasonCode = _Literal[
        "no_known_family_match",
        "unsupported_material_system",
        "unsupported_component_type",
        "unsupported_damage_pattern",
        "unsupported_location_context",
        "projection_binding_incompatible",
        "binding_registry_gap",
        "multi_family_conflict",
        "sidecar_only_fact_pattern",
        "coverage_unimplemented_domain",
        "measurement_family_unimplemented",
        "method_class_unimplemented",
        "unit_incompatible",
    ]
except ImportError:  # pragma: no cover
    UnknownReasonCode = str  # type: ignore


def derive_unknown_reason_code(context: Dict[str, Any]) -> Optional[str]:
    """spec 06 §16.3 / spec 07 §5：从 projection 上下文派生 unknown_reason_code。

    Priority order (most specific → most generic, when multiple conditions match):
      1. multi_family_conflict (resolve_family_conflict 已 detect)
      2. no_known_family_match (no candidate family applicable)
      3. coverage_unimplemented_domain (registry 没此域 family)
      4. binding_registry_gap (registry 缺 slot binding)
      5. measurement_family_unimplemented (measurement family 未实施)
      6. method_class_unimplemented (test method 未实施)
      7. unsupported_material_system (material 不在 binding)
      8. unsupported_component_type (component 不在 binding)
      9. unsupported_damage_pattern (condition_class 无 binding)
     10. unsupported_location_context (location 不被 binding 支持)
     11. unit_incompatible (单位不匹配)
     12. projection_binding_incompatible (单位/方法兼容但其它绑定问题)
     13. sidecar_only_fact_pattern (worldgen 无 fact，全 sidecar 类)

    Args:
        context: 候选触发条件字典；任意 bool key 缺省视为 False（has_known_family_match 缺省 True）。

    Returns:
        第一个满足条件的 reason_code（按上述 priority），或 None 表示 family 已 covered（无 unknown 条件）。
    """
    # priority 1: multi_family_conflict
    if context.get("multi_family_conflict"):
        return "multi_family_conflict"

    # priority 2: no_known_family_match (default True 表示 known family exists)
    if not context.get("has_known_family_match", True):
        return "no_known_family_match"

    # priority 3-6: registry gap / unimplemented (structural)
    if context.get("coverage_unimplemented_domain"):
        return "coverage_unimplemented_domain"
    if context.get("binding_registry_gap"):
        return "binding_registry_gap"
    if context.get("measurement_family_unimplemented"):
        return "measurement_family_unimplemented"
    if context.get("method_class_unimplemented"):
        return "method_class_unimplemented"

    # priority 7-10: compatibility (specific resource)
    if context.get("unsupported_material_system"):
        return "unsupported_material_system"
    if context.get("unsupported_component_type"):
        return "unsupported_component_type"
    if context.get("unsupported_damage_pattern"):
        return "unsupported_damage_pattern"
    if context.get("unsupported_location_context"):
        return "unsupported_location_context"

    # priority 11-12: unit / binding generic
    if context.get("unit_incompatible"):
        return "unit_incompatible"
    if context.get("projection_binding_incompatible"):
        return "projection_binding_incompatible"

    # priority 13: sidecar-only fact pattern (last resort before "covered")
    if context.get("sidecar_only_fact_pattern"):
        return "sidecar_only_fact_pattern"

    return None  # 全部检查过；family 已 covered


# ---------- T-24 helper functions for trigger detection ----------


def has_known_family_match(candidate_families: List[Dict[str, Any]]) -> bool:
    """至少一个 candidate family 含 required_slots_present=True。"""
    return any(c.get("required_slots_present") for c in candidate_families)


def is_sidecar_only_fact_pattern(
    world_facts_present: bool,
    sidecar_facts_present: bool,
) -> bool:
    """spec 06 §16.3：worldgen core 无事实但 sidecar 有事实 → 全属 sidecar-only。"""
    return (not world_facts_present) and sidecar_facts_present


def detect_binding_registry_gap(
    required_slots: List[str],
    available_slot_bindings: Iterable[str],
) -> bool:
    """检测 required slot 中是否有 registry 未绑定的。"""
    available_set = set(available_slot_bindings)
    return any(slot not in available_set for slot in required_slots)


def detect_unit_incompatible(
    measurement_units: Dict[str, str],
    expected_units: Dict[str, str],
) -> bool:
    """检测某 slot 的 measurement unit 跟 binding expected unit 不匹配。"""
    for slot_id, expected in expected_units.items():
        actual = measurement_units.get(slot_id)
        if actual is not None and expected is not None and actual != expected:
            return True
    return False


# ---------- T-25: spec 06 §15 5-bin threshold regime ----------

# 5 numeric bins + 1 non-numeric sentinel = 6 regime values（spec 04 §20 ThresholdEval.regime_tag）
THRESHOLD_REGIMES: Tuple[str, ...] = (
    "far_below",
    "near_below",
    "exact_threshold",
    "near_above",
    "far_above",
    "not_numeric",
)

try:
    from typing import Literal as _LiteralRegime
    ThresholdRegime = _LiteralRegime[
        "far_below",
        "near_below",
        "exact_threshold",
        "near_above",
        "far_above",
        "not_numeric",
    ]
except ImportError:  # pragma: no cover
    ThresholdRegime = str  # type: ignore


_EXACT_THRESHOLD_EPSILON = 1e-9


def _width_from_unit(unit: Optional[str], abs_threshold: float) -> Optional[float]:
    """spec 06 §15 fallback：按 slot_unit 推断 width 族（用于 W0 measurement_family
    不在 §15 row family 命名表里的场景，如 technical_validation / inspection_coverage 等）.

    返回 None 表示 unit 不识别，由 caller 决定是否兜底 0.0。
    """
    if unit is None:
        return None
    u = str(unit).strip()
    # geometry length-style by unit
    if u == "mm":
        return max(0.05, 0.10 * abs_threshold)
    if u == "m":
        return max(0.01, 0.10 * abs_threshold)
    if u in ("m2", "m^2", "m²"):
        return max(0.01, 0.20 * abs_threshold)
    # ratio-like (含百分号 / 无量纲)
    if u in ("ratio", "1", "", "%", "fraction"):
        return max(0.02, 0.10 * abs_threshold)
    # stress-like
    if u in ("N_per_mm2", "N/mm2", "N/mm^2", "MPa"):
        return max(1.0, 0.05 * abs_threshold)
    if u == "kPa":
        return max(50.0, 0.05 * abs_threshold)
    if u == "Pa":
        return max(5e4, 0.05 * abs_threshold)
    # count / discrete-like（含 specimen / floor / time-step in days etc.）
    if u in ("count", "specimen", "floor", "year", "month", "day", "s", "second"):
        return 1.0
    # rate-like (per-area / per-volume densities)
    if u in ("count/25m2", "count/m3", "count/m^3", "count/m2"):
        return max(0.1, 0.10 * abs_threshold)
    return None


def compute_threshold_width(
    threshold: float,
    measurement_family: str,
    slot_unit: Optional[str] = None,
) -> float:
    """spec 06 §15 width 规则按 measurement family 计算 near_below / near_above 半宽.

    family-specific 公式（spec 06 §15 表）：
    - geometry_length / geometry_width / geometry_depth: max(abs_min, 0.10*threshold)
      abs_min = 0.05 (mm) / 0.01 (m) — spec §15 注 "abs_min=0.05mm or 0.01m"
    - geometry_area: max(0.01, 0.20*threshold) (m²)
    - ratio: max(0.02, 0.10*threshold)
    - count: 1
    - rate: max(0.1, 0.10*threshold)
    - stress: max(1.0, 0.05*threshold)
    - bool / enum / classification: 0 (caller 应已走 not_numeric 分支)

    Fallback (DEBT-026 closure 2026-05-08)：当 measurement_family 不在 §15 row family 命名表
    （如调用方传的是 W0 MeasurementRecord.measurement_family = technical_validation /
    inspection_coverage / inspection_plan / defect_geometry / coverage_sampling /
    derived_risk_measurement / etc 等，跟 §15 row family 是两套体系），用 _width_from_unit
    根据 slot_unit 推断 width 族；unit 也不识别才退 0.0。

    Args:
        threshold: 数值阈值（绝对值用于 width 计算）
        measurement_family: spec 06 §15 行 family 名（geometry_length/area/ratio/count/rate/stress/bool/enum）
                            或 W0 family（technical_validation / inspection_coverage / etc，走 unit fallback）
        slot_unit: geometry length/width/depth 用于决定 abs_min（mm vs m），也作 W0 family fallback 路由

    Returns:
        width >= 0；非数值 family + unit 也不识别返回 0。
    """
    abs_threshold = abs(threshold)
    if measurement_family in ("geometry_length", "geometry_width", "geometry_depth"):
        if slot_unit == "mm":
            abs_min = 0.05
        elif slot_unit == "m":
            abs_min = 0.01
        else:
            abs_min = 0.05  # default conservative
        return max(abs_min, 0.10 * abs_threshold)
    if measurement_family == "geometry_area":
        return max(0.01, 0.20 * abs_threshold)
    if measurement_family == "ratio":
        return max(0.02, 0.10 * abs_threshold)
    if measurement_family == "count":
        return 1.0
    if measurement_family == "rate":
        return max(0.1, 0.10 * abs_threshold)
    if measurement_family == "stress":
        return max(1.0, 0.05 * abs_threshold)
    if measurement_family in ("bool", "boolean_assertion", "enum", "classification"):
        return 0.0
    # W0 family（technical_validation / inspection_coverage / etc）→ unit-based fallback
    unit_width = _width_from_unit(slot_unit, abs_threshold)
    if unit_width is not None:
        return unit_width
    return 0.0  # 真未知


FragmentProjectionResult = Dict[str, Any]
# Shape: {
#   "fragment_id": str,
#   "selected_family_ids": List[str],   # from resolve_family_conflict
#   "unknown_reason_code": Optional[str],  # from derive_unknown_reason_code (None if covered)
#   "threshold_evaluations": List[Dict],  # built via build_threshold_evaluation
#   "projection_status": str,  # "covered" / "unknown" / "not_applicable" / "sidecar_missing"
# }


def classify_threshold_regime(
    observed: Any,
    threshold: Any,
    measurement_family: str,
    slot_unit: Optional[str] = None,
    integer_compare: bool = False,
) -> str:
    """spec 06 §15: 5-bin threshold regime 分类（+ not_numeric 兜底）.

    返回 one of THRESHOLD_REGIMES：
    - "exact_threshold": observed == threshold (float EPS=1e-9 / int exact)
    - "near_below": -width <= observed - threshold < 0
    - "far_below": observed - threshold < -width
    - "near_above": 0 < observed - threshold <= width
    - "far_above": observed - threshold > width
    - "not_numeric": bool / enum / 无法 coerce 数值

    spec 06 §15 注：regime tag 不直接代表 pass/fail；pass/fail 由 operator 单独决定。
    """
    # spec §15 行 7-8: bool / enum 不参与数值分箱
    if measurement_family in ("bool", "boolean_assertion", "enum", "classification"):
        return "not_numeric"

    # 数值 coerce
    try:
        obs_val = float(observed)
        thr_val = float(threshold)
    except (TypeError, ValueError):
        return "not_numeric"

    # exact_threshold check (spec §15 注 "Exact threshold 规则")
    if integer_compare:
        if int(round(obs_val)) == int(round(thr_val)):
            return "exact_threshold"
    else:
        if abs(obs_val - thr_val) < _EXACT_THRESHOLD_EPSILON:
            return "exact_threshold"

    width = compute_threshold_width(thr_val, measurement_family, slot_unit)
    diff = obs_val - thr_val

    if diff < 0:
        # below threshold
        if abs(diff) <= width:
            return "near_below"
        return "far_below"
    # above threshold（已排除 exact 情况）
    if diff <= width:
        return "near_above"
    return "far_above"


# ---------- #3 整合: T-23 + T-24 + T-25 闭环 ----------


def build_threshold_evaluation(
    rule_id: str,
    threshold_regime_id: str,
    slot_id: str,
    operator: str,
    threshold_value: Any,
    observed_value: Any,
    measurement_family: str,
    slot_unit: Optional[str] = None,
    integer_compare: bool = False,
) -> Dict[str, Any]:
    """T-25 集成：构建 ThresholdEval-compatible dict（spec 04 §20）含 regime_tag 派生.

    返回的 dict 字段对齐 models.py::ThresholdEval：
    rule_id / threshold_regime_id / slot_id / operator / threshold_value /
    observed_value / regime_tag / pass_bool。

    Block B.2 ④ producer 端 non-empty hard-fail：threshold_regime_id 空/None → raise。
    单靠 ThresholdEval Pydantic required 防不住（生产 executor 绕 Pydantic 直 append dict），
    故 producer 与 parquet writer 两处显式 hard-fail。

    pass_bool 由 operator 决定（spec 04 §20：regime_tag 不直接决定 pass/fail）：
    - "<="：observed <= threshold
    - "<"：observed < threshold
    - ">="：observed >= threshold
    - ">"：observed > threshold
    - "=="：observed == threshold (float EPS=1e-9)
    - "!="：observed != threshold
    - "in"：observed in threshold (treats threshold as iterable)
    - "not_in"：observed not in threshold
    """
    if not threshold_regime_id:
        raise ValueError(
            "threshold_regime_id_empty_at_build_threshold_evaluation: "
            f"build_threshold_evaluation 收到空 threshold_regime_id（rule_id={rule_id!r}, "
            f"slot_id={slot_id!r}）——Block B.2 ④ producer 端 non-empty hard-fail"
        )

    # DEBT-056 前向修（2026-07-14）：formula 型制度保守化——不产生假 FAIL。
    # 权威索引 repoint 后新增 3 个 formula 型制度（operator=="formula"，
    # count.pull_test.additional_after_failure，expected=n^2-2n+3），无 literal
    # threshold_value（value=None）。W2 侧尚无公式求值器支持——在支持前，显式判为
    # not-numerically-evaluable → unknown（pass_bool=None，family verdict 归 unknown、
    # 回到基线态 count.pull_test 族全 unknown），绝不判 pass_bool=False（否则固定假 FAIL、
    # 比原状更糟的回归）。公式语义参 closure 侧 handle_pull_test_additional_after_failure；
    # 分层单向不 import evo_agent_baseline，仅在 workflow_engine 侧做保守标注。
    if operator == "formula":
        return {
            "rule_id": rule_id,
            "threshold_regime_id": threshold_regime_id,
            "slot_id": slot_id,
            "operator": operator,
            "threshold_value": threshold_value,
            "observed_value": observed_value,
            "regime_tag": "not_numeric",
            "pass_bool": None,  # not-numerically-evaluable → unknown（非 False）
        }

    regime_tag = classify_threshold_regime(
        observed=observed_value,
        threshold=threshold_value,
        measurement_family=measurement_family,
        slot_unit=slot_unit,
        integer_compare=integer_compare,
    )

    pass_bool = _evaluate_threshold_operator(
        operator, observed_value, threshold_value, integer_compare
    )

    return {
        "rule_id": rule_id,
        "threshold_regime_id": threshold_regime_id,
        "slot_id": slot_id,
        "operator": operator,
        "threshold_value": threshold_value,
        "observed_value": observed_value,
        "regime_tag": regime_tag,
        "pass_bool": pass_bool,
    }


def _evaluate_threshold_operator(
    operator: str,
    observed: Any,
    threshold: Any,
    integer_compare: bool = False,
) -> bool:
    """spec 04 §20 ThresholdEval.operator 评估."""
    EPS = 1e-9
    if operator == "in":
        try:
            return observed in threshold
        except TypeError:
            return False
    if operator == "not_in":
        try:
            return observed not in threshold
        except TypeError:
            return True

    # numeric / equality 操作符
    try:
        obs_val = float(observed)
        thr_val = float(threshold)
    except (TypeError, ValueError):
        # 非数值：fallback 到 string 比较
        if operator == "==":
            return observed == threshold
        if operator == "!=":
            return observed != threshold
        return False

    if operator == "<=":
        return obs_val <= thr_val + EPS
    if operator == "<":
        return obs_val < thr_val - EPS
    if operator == ">=":
        return obs_val >= thr_val - EPS
    if operator == ">":
        return obs_val > thr_val + EPS
    if operator == "==":
        if integer_compare:
            return int(round(obs_val)) == int(round(thr_val))
        return abs(obs_val - thr_val) < EPS
    if operator == "!=":
        if integer_compare:
            return int(round(obs_val)) != int(round(thr_val))
        return abs(obs_val - thr_val) >= EPS
    return False


def evaluate_fragment_projection_candidates(
    fragment_id: str,
    candidate_families: List[Dict[str, Any]],
    conflict_group_id: Optional[str] = None,
    threshold_eval_inputs: Optional[List[Dict[str, Any]]] = None,
    extra_unknown_context: Optional[Dict[str, Any]] = None,
) -> FragmentProjectionResult:
    """#3 整合：T-23 + T-24 + T-25 三个组件的闭环高层入口（per fragment）.

    Args:
        fragment_id: 当前 fragment 的 id（spec 04 §16 measurement.target_ref）
        candidate_families: 上游 evaluate-applicability 阶段产生的 candidate list；
            每个 entry 含 family_id / applicability_score / target_component_id /
            required_slots_present。
        conflict_group_id: 当前 projection binding 的 conflict_group（来自 normative_projection_registry）
        threshold_eval_inputs: list of dicts to build ThresholdEval per spec 04 §20。每个 entry：
            {rule_id, slot_id, operator, threshold_value, observed_value, measurement_family,
             slot_unit?, integer_compare?}
        extra_unknown_context: optional dict 补充 derive_unknown_reason_code 的 trigger flags
            (binding_registry_gap / unsupported_material_system / coverage_unimplemented_domain
             / sidecar_only_fact_pattern / unit_incompatible 等)

    Pipeline:
        1. T-23 resolve_family_conflict → (selected_family_ids, conflict_reason)
        2. 若 selector 返回 unknown reason，跳到 step 4
        3. 若有 selected_family_ids，构建 threshold_evaluations (T-25 regime + operator pass_bool)
        4. 若 unknown 状态：T-24 derive_unknown_reason_code 给最终 reason
        5. 返回 FragmentProjectionResult

    spec 09 §2 / §3 alignment（W2-004 重写）：
    - selected known family + required slots ready → projection_status="covered"
    - conflict_reason="multi_family_conflict" → projection_status="conflict"
    - 其余无 family / required slot 缺失 → projection_status="uncovered"
    （**没有** "unknown" projection_status；spec 09 §2 三态 covered/uncovered/conflict）
    """
    # T-23: family conflict 解析
    selected_family_ids, conflict_reason = resolve_family_conflict(
        candidate_families, conflict_group_id
    )

    # T-25: threshold evaluations（仅 covered 状态构建；unknown 状态可空）
    threshold_evaluations: List[Dict[str, Any]] = []
    if selected_family_ids and threshold_eval_inputs:
        for input_spec in threshold_eval_inputs:
            threshold_evaluations.append(
                build_threshold_evaluation(
                    rule_id=input_spec["rule_id"],
                    threshold_regime_id=input_spec["threshold_regime_id"],
                    slot_id=input_spec["slot_id"],
                    operator=input_spec["operator"],
                    threshold_value=input_spec["threshold_value"],
                    observed_value=input_spec["observed_value"],
                    measurement_family=input_spec["measurement_family"],
                    slot_unit=input_spec.get("slot_unit"),
                    integer_compare=input_spec.get("integer_compare", False),
                )
            )

    # T-24: 若 selector 没返回 family，路由 unknown reason
    unknown_reason_code: Optional[str] = None
    # W2-004: spec 09 §2 三态 projection_status = covered / uncovered / conflict（无 unknown）
    if selected_family_ids:
        projection_status = "covered"
    elif conflict_reason == "multi_family_conflict":
        # 同 group multi-applicable 无 selector 解析 → conflict
        projection_status = "conflict"
    else:
        # 无 known family / required slot 缺失 → uncovered
        projection_status = "uncovered"

    if not selected_family_ids:
        # 构建 derive_unknown_reason_code 的 context
        context: Dict[str, Any] = {
            "has_known_family_match": has_known_family_match(candidate_families),
        }
        if conflict_reason == "multi_family_conflict":
            context["multi_family_conflict"] = True
        if extra_unknown_context:
            context.update(extra_unknown_context)
        unknown_reason_code = derive_unknown_reason_code(context)

    return {
        "fragment_id": fragment_id,
        "selected_family_ids": selected_family_ids,
        "unknown_reason_code": unknown_reason_code,
        "threshold_evaluations": threshold_evaluations,
        "projection_status": projection_status,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# 2026-05-10 全替换：parquet directory 优先；legacy JSON 路径仍兼容（migration 期）
def _load_world_bundles(path: Path) -> Dict[str, Any]:
    """读 worldgen world bundles — 优先 parquet directory；兼容 legacy .json."""
    from workflow_engine.worldgen.parquet_io import (
        is_world_bundles_parquet_dir,
        read_world_bundles_parquet,
    )
    if path.is_dir() and is_world_bundles_parquet_dir(path):
        return read_world_bundles_parquet(path)
    return _load_json(path)


def _load_sidecar_runtime(path: Path) -> Dict[str, Any]:
    from workflow_engine.worldgen.parquet_io import (
        is_sidecar_runtime_parquet_dir,
        read_sidecar_runtime_parquet,
    )
    if path.is_dir() and is_sidecar_runtime_parquet_dir(path):
        return read_sidecar_runtime_parquet(path)
    return _load_json(path)


def _load_normative_projection(path: Path) -> Dict[str, Any]:
    from workflow_engine.worldgen.parquet_io import (
        is_normative_projection_parquet_dir,
        read_normative_projection_parquet,
    )
    if path.is_dir() and is_normative_projection_parquet_dir(path):
        return read_normative_projection_parquet(path)
    return _load_json(path)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


# ---------- 2026-05-10 全替换 parquet：RegulationProjectionResults.v2 ----------
# Results.v2 顶层 schema 跟 WorldgenNormativeProjection.v2 几乎同构（共用 buildings → projections
# → matched_families/threshold_evaluations/basis_items），只差 meta 字段：
#   Results 多 buildings_count（可由 len(buildings) 重算）
#   NormativeProjection 多 registry_bundle_hash / deterministic_key（Results 没有）
# 复用 worldgen.parquet_io 的 writer/reader，包了一层 strip + 回填 buildings_count。


def _write_projection_results_parquet(out_dir: Path, payload: Dict[str, Any]) -> Path:
    """写 Results.v2 -> parquet directory（复用 NormativeProjection writer）.

    Strip 'buildings_count'（reader 会自动重算回填）。其他字段直接透传，writer
    会容忍 NormativeProjection-only 字段为 None.
    """
    from workflow_engine.worldgen.parquet_io import write_normative_projection_parquet
    payload_for_writer = {k: v for k, v in payload.items() if k != "buildings_count"}
    write_normative_projection_parquet(out_dir, payload_for_writer)
    return out_dir


def _read_projection_results_parquet(in_dir: Path) -> Dict[str, Any]:
    """读 Results.v2 parquet directory -> 等价 dict（with buildings_count 回填）.

    复用 NormativeProjection reader 后：
    - 删掉 NormativeProjection-only 的 registry_bundle_hash / deterministic_key（Results 本来没有）
    - 重算 buildings_count = len(buildings)
    - 修正 version 字段（NormativeProjection writer 不动 version 串，本就透传 Results 的 version）
    """
    from workflow_engine.worldgen.parquet_io import read_normative_projection_parquet
    d = read_normative_projection_parquet(in_dir)
    d["buildings_count"] = len(d.get("buildings", []))
    d.pop("registry_bundle_hash", None)
    d.pop("deterministic_key", None)
    return d


def is_projection_results_parquet_dir(path: Path) -> bool:
    """判定一个 path 是否是 Results.v2 parquet directory.

    复用 NormativeProjection 同名 detector（meta 文件名相同：normative_projection_meta.parquet）.
    """
    from workflow_engine.worldgen.parquet_io import is_normative_projection_parquet_dir
    return is_normative_projection_parquet_dir(path)




# ---------- Missing #2: v2 entry NormativeProjection builder ----------

# Mechanism family → projection family 候选映射（spec 08 §5 family 总表 + spec 04 §10 mechanism）
# F1 修正（QA 长跑发现 multi_family_conflict 44%）：每 mechanism family 默认单 target，避免
# multi-target conflict_group resolver 走 multi_family_conflict 分支。component_type 区分由
# _pick_projection_family_for_fragment 处理。
# W2-006 (批次 C 2026-05-21)：跟 W2-005 同步拆 `ubw_signal` / `fire_safety_deficiency` mechanism
# 路由到独立 family（spec 06 §2.1 row 5 / row 7 fire_safety / ubw 独立 baseline），
# 不再共用合并 mbis.inspection.ubw_and_fire_safety target.
MECHANISM_FAMILY_TO_PROJECTION_FAMILIES: Dict[str, List[str]] = {
    "structural_crack": ["mbis.inspection.external_components"],
    "corrosion_spall": ["mbis.inspection.external_components"],
    "moisture_detachment": ["mbis.inspection.external_components"],
    "drainage_fault": ["mbis.inspection.drainage"],
    "ubw_signal": ["mbis.inspection.ubw"],
    "fire_safety_deficiency": ["mbis.inspection.fire_safety"],
    "assessment_origin": ["mbis.investigation.gate_and_proposal"],
    "verification_origin": ["mbis.repair.external_structural_validation"],
}


# F1 修正：mechanism + component_type 联合决定 projection family。结构构件走 structural_components；
# 其它走 external_components / 其它默认。
_COMPONENT_TYPE_FAMILY_OVERRIDES: Dict[str, Dict[str, str]] = {
    "structural_crack": {
        "structural_member": "mbis.inspection.structural_components",
        "balcony_slab": "mbis.inspection.structural_components",
        "parapet_wall": "mbis.inspection.structural_components",
    },
    "corrosion_spall": {
        "structural_member": "mbis.inspection.structural_components",
        "balcony_slab": "mbis.inspection.structural_components",
    },
    "assessment_origin": {
        "structural_member": "mbis.repair.external_structural_validation",
    },
}


# DEBT-049 根治①（W2 归因组件一致化，codex CoP 裁定 2026-07-08）：组件 → CoP 检查族
# （3.1.2 五类组件/系统边界）。缺陷类机制按组件的检查族归因，回归 CoP scope，不再机制
# 粗 fallback 把排水/消防 fragment 的缺陷投进 external_components。parapet/balcony 保守
# 留 structural（CoP 3.4，spec 草案 §4 决策点1）；ubw_signal/工作流机制不走此路由。
_COMPONENT_TYPE_INSPECTION_FAMILY: Dict[str, str] = {
    "external_wall": "mbis.inspection.external_components",
    "signboard": "mbis.inspection.external_components",
    "canopy": "mbis.inspection.external_components",
    "wall_tile_finish": "mbis.inspection.external_components",
    "parapet_wall": "mbis.inspection.structural_components",
    "balcony_slab": "mbis.inspection.structural_components",
    "structural_member": "mbis.inspection.structural_components",
    "drainage_stack": "mbis.inspection.drainage",
    "drainage_branch": "mbis.inspection.drainage",
    "fire_door": "mbis.inspection.fire_safety",
    "unauthorized_structure": "mbis.inspection.ubw",
}
# 按组件检查族归因的缺陷类机制（回归 CoP 组件边界）。ubw_signal（UBW 跨组件本职）、
# assessment_origin / verification_origin（勘察/修缮工作流跨组件）保持机制驱动。
_COMPONENT_ROUTED_MECHANISMS = frozenset({
    "structural_crack", "corrosion_spall", "moisture_detachment",
    "drainage_fault", "fire_safety_deficiency",
})


def _pick_projection_family_for_fragment(
    mechanism_family: str,
    component_type: str,
    projection_family_index: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """F1：单 target projection family 选择（mechanism + component_type 决定）.

    Returns single family_id, or None if no match.

    DEBT-049 根治①：缺陷类机制先按组件 CoP 检查族归因（组件相容优先于机制 fallback，
    修 W2 答案键回归 CoP 组件 scope）；工作流机制/ubw_signal 保持机制驱动。
    """
    if mechanism_family in _COMPONENT_ROUTED_MECHANISMS:
        fam = _COMPONENT_TYPE_INSPECTION_FAMILY.get(component_type)
        if fam and fam in projection_family_index:
            return fam
    overrides = _COMPONENT_TYPE_FAMILY_OVERRIDES.get(mechanism_family, {})
    if component_type in overrides:
        candidate = overrides[component_type]
        if candidate in projection_family_index:
            return candidate
    target_list = MECHANISM_FAMILY_TO_PROJECTION_FAMILIES.get(mechanism_family, [])
    for family in target_list:
        if family in projection_family_index:
            return family
    return None


def _projection_registry_lookup(registries: Any) -> Dict[str, Dict[str, Any]]:
    """Index normative_projection_registry by projection_family."""
    for table in registries.registries:
        if table.registry_id == "normative_projection_registry":
            return {record["projection_family"]: record for record in table.records}
    return {}


# W2-008 (批次 C 2026-05-21)：spec 06 §4.5 applicability_predicates evaluator.
# spec §4 把 applicability_predicates 4 类断言 evaluator 列为 W2 family 路由权威；
# spec §4.4 "封口版 W2 以 applicability_predicates full evaluator 为 spec 权威。任何
# simplified single-target routing 只能作为历史实现适配说明，不得作为 spec 语义替代"。
#
# 本节实施：(a) 单 predicate evaluate；(b) 每 family 4 类断言聚合产 applicability_score
# + required_slots_present；(c) `_build_candidate_families_for_fragment` 走 evaluator
# 主路径，按 spec §4.3 评估时机所有 family 评估 + 按 score 排序产 List[candidate].


def _evaluate_world_predicate(
    predicate: Dict[str, Any],
    fragment: Any,
    mechanism: Any,
    condition: Any,
    world: Any,
) -> bool:
    """spec 06 §4.1 world predicate：评估 WorldBundle 字段断言.

    当前 spec §4.5.4 简化原则——assertion 默认走 `non_null`（slot 在 WorldBundle 内有
    记录即视为满足）；W1 worldgen 派生层在 fragment / mechanism / condition / drainage /
    ubw / fire_safety / repair / risk states 等 bundle 字段内承载 world_truth_slot
    实际值。本 evaluator 按 spec §4.2 W2 红线 1 / 8——只读、不写、不消费 W1 内部派生过程。

    当前实施：family-record-level world predicate 直接视为满足（W1 worldgen 派生层默认
    把 required_world_core_slots 装上来；spec §4.5.5 / DEBT-031 gap 10 后续按 family
    业务边界细化 value_in / value_equals 断言）.
    """
    assertion = predicate.get("assertion")
    if assertion == "non_null":
        # spec §4.5.4：non_null 是最弱断言，slot 字段在 WorldBundle 内有记录即满足.
        # 现阶段 W1 派生层默认 required_world_core_slots 全部 ready（W1 worldgen 设计目标），
        # evaluator 不二次校验，直接视为 True.
        return True
    if assertion == "value_equals":
        # spec §4.5.5 后续扩展点——按 family 业务边界细化时实施.
        return True
    if assertion == "value_in":
        return True
    return True


def _evaluate_measurement_predicate(
    predicate: Dict[str, Any],
    fragment_measurements: List[Any],
    sidecar_numeric_entries: List[Dict[str, Any]],
) -> bool:
    """spec 06 §4.1 measurement predicate：评估 MeasurementRecord 字段断言.

    assertion `exists`：measurement / sidecar numeric slot 在当前 fragment 测量集合内出现即满足.
    """
    target_path = predicate.get("target_path", "")
    assertion = predicate.get("assertion")
    if assertion == "exists":
        for m in fragment_measurements:
            if getattr(m, "slot_id", None) == target_path:
                return True
        for sv in sidecar_numeric_entries:
            if sv.get("slot_id") == target_path:
                return True
        return False
    return True


def _evaluate_qualifier_predicate(
    predicate: Dict[str, Any],
    fragment: Any,
    world: Any = None,
    component_by_id: Optional[Dict[str, Any]] = None,
    location_by_id: Optional[Dict[str, Any]] = None,
) -> bool:
    """spec 06 §4.1 qualifier predicate：评估 qualifier slot 断言.

    W0-004 step 6 (2026-05-21)：按 spec 06 §0.1 reference 反查路径：
    - qual.component_type → `lookup_component(fragment.component_id).component_type`
    - qual.location_class → `lookup_location(fragment.location_id).location_class`
    （旧 denorm 字段 fragment.component_type_id / fragment.location_class_id 已撤出 W0 contract）.
    fragment 自身字段有值即视为 qualifier present（与 spec §4.5.4 最弱断言一致）.

    PT-1 perf (2026-05-23)：`component_by_id` / `location_by_id` 索引由调用链上游
    （build_normative_projections_for_world）建一次后透传，避免每次调用全量线性扫描
    world.components / world.locations（本函数在 per-fragment × per-family 调用，
    扫描成本随 fragments×families 非线性增长）。未传索引时退回从 `world` 现建——
    保证直接调用方 / 测试行为不变。纯性能优化，评估结果完全一致。
    """
    assertion = predicate.get("assertion")
    target_path = predicate.get("target_path", "")
    if assertion == "non_null":
        if target_path == "qual.component_type":
            if world is None or not getattr(fragment, "component_id", ""):
                return False
            if component_by_id is None:
                component_by_id = {c.component_id: c for c in world.components}
            component = component_by_id.get(fragment.component_id)
            return bool(component and component.component_type)
        if target_path == "qual.location_class":
            if world is None or not getattr(fragment, "location_id", ""):
                return False
            if location_by_id is None:
                location_by_id = {loc.location_id: loc for loc in world.locations}
            location = location_by_id.get(fragment.location_id)
            return bool(location and location.location_class)
        # 其他 qualifier（qual.defect_class / qual.method_class / qual.work_category /
        # qual.risk_class）当前 W1 fragment 不直接承载——按 spec §4.5.4 最弱断言默认满足；
        # spec §4.5.5 后续扩展点（gap 10）会落实更精细 qualifier 派生.
        return True
    return True


def _evaluate_sidecar_join_predicate(
    predicate: Dict[str, Any],
    fragment_id: str,
    sidecar_runtime_bundle: Any,
    sidecar_numeric_entries: List[Dict[str, Any]],
) -> bool:
    """spec 06 §4.1 sidecar join predicate：评估 sidecar 5 桶 join marker 断言.

    assertion `marker_present`：当前 fragment 在 sidecar_runtime_bundle 有 numeric
    entry，且 sidecar entry 的 slot_id 前缀匹配 interface_id（同 derive_sidecar_join_status
    匹配规则）即视为满足.
    """
    if sidecar_runtime_bundle is None:
        return False
    interface_id = predicate.get("target_path", "")
    if not interface_id:
        return False
    assertion = predicate.get("assertion")
    if assertion == "marker_present":
        for sv in sidecar_numeric_entries:
            if sv.get("slot_id", "").startswith(interface_id):
                return True
        return False
    return True


def _evaluate_applicability_predicates(
    family_record: Dict[str, Any],
    fragment: Any,
    mechanism: Any,
    condition: Any,
    world: Any,
    fragment_measurements: List[Any],
    sidecar_runtime_bundle: Any,
    sidecar_numeric_entries: List[Dict[str, Any]],
    component_by_id: Optional[Dict[str, Any]] = None,
    location_by_id: Optional[Dict[str, Any]] = None,
) -> Tuple[float, bool]:
    """spec 06 §4 applicability_predicates evaluator：返回 (applicability_score, required_slots_present).

    spec §4.3 评估时机：phase 3 主循环 per family per fragment 调用一次.
    返回值：
      - applicability_score ∈ [0, 1]：4 类 predicate 通过比例（passed / total）；空 predicate
        视为 score=0（family 无任何 predicate 不可路由）.
      - required_slots_present ∈ {True, False}：world / qualifier predicate 全部满足
        （这两类是 family 适用性硬条件——按 spec §4.1 "世界真相 / 限定信息"是 family
        applicable 与否的硬底座）；measurement / sidecar_join 走 score 降权.
    """
    predicates = family_record.get("applicability_predicates", [])
    if not isinstance(predicates, list) or not predicates:
        return 0.0, False

    passed = 0
    world_qualifier_all_passed = True

    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        klass = predicate.get("predicate_class")
        ok = False
        if klass == "world":
            ok = _evaluate_world_predicate(predicate, fragment, mechanism, condition, world)
            if not ok:
                world_qualifier_all_passed = False
        elif klass == "measurement":
            ok = _evaluate_measurement_predicate(
                predicate, fragment_measurements, sidecar_numeric_entries
            )
        elif klass == "qualifier":
            ok = _evaluate_qualifier_predicate(
                predicate, fragment, world=world,
                component_by_id=component_by_id, location_by_id=location_by_id,
            )
            if not ok:
                world_qualifier_all_passed = False
        elif klass == "sidecar_join":
            ok = _evaluate_sidecar_join_predicate(
                predicate, fragment.fragment_id if fragment else "",
                sidecar_runtime_bundle, sidecar_numeric_entries,
            )
        if ok:
            passed += 1

    total = len(predicates)
    score = passed / total if total > 0 else 0.0
    return score, world_qualifier_all_passed


def _build_candidate_families_for_fragment(
    fragment_id: str,
    mechanism_family: str,
    component_type: str,
    severity_index: float,
    projection_family_index: Dict[str, Dict[str, Any]],
    *,
    # W2-008 (批次 C 2026-05-21)：spec §4 applicability_predicates evaluator 额外上下文.
    # 入参为 optional 以保持现役调用方（如测试 / 其他模块）兼容：未传时回退到 simplified
    # routing（spec §4.4 标"非权威 fallback"）.
    fragment: Any = None,
    mechanism: Any = None,
    condition: Any = None,
    world: Any = None,
    fragment_measurements: Optional[List[Any]] = None,
    sidecar_runtime_bundle: Any = None,
    sidecar_numeric_entries: Optional[List[Dict[str, Any]]] = None,
    component_by_id: Optional[Dict[str, Any]] = None,
    location_by_id: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """W2-008 (批次 C 2026-05-21)：spec 06 §4 applicability_predicates evaluator 主路径.

    主路径（spec §4.3）：
      1. 遍历 normative_projection_registry 所有 records.
      2. per family 调 _evaluate_applicability_predicates 求 (applicability_score,
         required_slots_present).
      3. required_slots_present=True 入 candidate list；按 applicability_score 降序.

    Fallback（spec §4.4 "simplified single-target routing 只能作历史实现适配说明"）：
      - evaluator 必备上下文 (fragment + measurements) 未传 → 走 simplified mechanism +
        component_type 路由（保持现役调用方兼容）.
      - evaluator 输出 empty candidates → 同样回 simplified fallback（spec §4.4 "非权威 fallback"），
        保 worldgen 端 candidate 非空率（rule_card threshold value 数据仍接 mechanism→family
        映射 fallback）.
    """
    # spec §4.3 主路径——evaluator 必备上下文齐全时走 full evaluator.
    if (
        fragment is not None
        and fragment_measurements is not None
        and projection_family_index
    ):
        candidates: List[Dict[str, Any]] = []
        sidecar_entries = sidecar_numeric_entries or []
        for family_id, family_record in projection_family_index.items():
            score, slots_present = _evaluate_applicability_predicates(
                family_record=family_record,
                fragment=fragment,
                mechanism=mechanism,
                condition=condition,
                world=world,
                fragment_measurements=fragment_measurements,
                sidecar_runtime_bundle=sidecar_runtime_bundle,
                sidecar_numeric_entries=sidecar_entries,
                component_by_id=component_by_id,
                location_by_id=location_by_id,
            )
            if not slots_present:
                continue
            candidates.append({
                "family_id": family_id,
                "applicability_score": score,
                "target_component_id": fragment_id,
                "required_slots_present": slots_present,
            })
        if candidates:
            # spec §4.3 step 4：按 applicability_score 降序排序产 candidate list.
            candidates.sort(key=lambda c: c["applicability_score"], reverse=True)
            # spec §4.3 step 5 conflict 解析交由 resolve_family_conflict（H3）.
            # W2 当前实施按 mechanism-driven single-target 投影主路径（避免 multi_family_conflict
            # 触发率过高），取 top 1 + simplified-route family 作 mechanism-anchored selection；
            # spec §4.3 step 5 + spec 07 §4 完整 multi-family conflict 解析按 conflict_group
            # selector 在 evaluate_fragment_projection_candidates 调 resolve_family_conflict
            # 走主流程.
            anchored = _pick_projection_family_for_fragment(
                mechanism_family, component_type, projection_family_index,
            )
            if anchored is not None:
                anchored_entry = next(
                    (c for c in candidates if c["family_id"] == anchored), None
                )
                if anchored_entry is not None:
                    # 保留 anchored family 作 single-target（避免现役 mechanism-driven
                    # batch QA 跑出 multi_family_conflict 44% 回潮），applicability_score
                    # 取真实 evaluator 求值结果（不再永远 severity_index）.
                    return [anchored_entry]
                # anchored mechanism family 未通过 evaluator 硬条件——按 score 取 top 1.
                return candidates[:1]
            return candidates[:1]
        # evaluator 没产候选 → 落 simplified fallback（spec §4.4 "非权威 fallback"）.

    # spec §4.4 simplified fallback：mechanism + component_type 单 target 路由.
    family_id = _pick_projection_family_for_fragment(
        mechanism_family, component_type, projection_family_index,
    )
    if family_id is None:
        return []
    return [{
        "family_id": family_id,
        "applicability_score": max(0.1, severity_index),
        "target_component_id": fragment_id,
        "required_slots_present": severity_index >= 0.2,
    }]


def derive_sidecar_join_status(
    fragment_id: str,
    required_sidecar_interfaces: List[str],
    sidecar_runtime_bundle: Optional[Any],
    sidecar_numeric_by_fragment: Dict[str, List[Dict[str, Any]]],
) -> str:
    """W2 spec 09 §1.1 + 08 §3.5: derive sidecar_join_status from 3 枚举.

    Returns `available` / `partial` / `unavailable` (2026-05-13 重审撤回原 4 枚举里的
    `sidecar_derivation_failed`；sidecar 派生失败场景归到 `unavailable`，
    原因细分由 `unknown_reason_code = sidecar_only_fact_pattern` 扩义承担).

    Rules:
      - sidecar_runtime_bundle is None → `unavailable`
      - required_sidecar_interfaces 空 → `available`（family 不需要 sidecar，trivially OK）
      - 当前 fragment 在 sidecar_numeric_by_fragment 无 entry → `unavailable`
      - sidecar slot 全 cover required interfaces → `available`
      - sidecar slot 部分 cover → `partial`
      - 完全无 cover → `unavailable`

    interface ↔ slot 匹配规则：sidecar slot_id 前缀 startswith(interface prefix) 视为 cover.
    """
    if sidecar_runtime_bundle is None:
        return "unavailable"
    if not required_sidecar_interfaces:
        return "available"
    available_entries = sidecar_numeric_by_fragment.get(fragment_id, [])
    if not available_entries:
        return "unavailable"
    available_slot_ids = {entry["slot_id"] for entry in available_entries}
    matched = sum(
        1 for interface in required_sidecar_interfaces
        if any(slot.startswith(interface) for slot in available_slot_ids)
    )
    if matched == len(required_sidecar_interfaces):
        return "available"
    if matched > 0:
        return "partial"
    return "unavailable"


def _index_unique_by_fragment(states: List[Any], state_kind: str) -> Dict[str, Any]:
    """按 `fragment_id` 建单值索引并 enforce per-fragment 1:1 不变式（BC-2）.

    W1 worldgen 当前契约：每个 fragment 严格 1 条 MechanismState + 1 条 ConditionState。
    本 builder 主循环按 fragment_id 单值消费 mechanism / condition；若上游违约产出
    同一 fragment 多条 state，dict 推导式会静默覆盖。这里改为显式检测重复并 raise，
    把潜在数据丢失变成响亮失败。

    Args:
        states: MechanismState 或 ConditionState 列表（均带 `fragment_id` 字段）.
        state_kind: 用于报错信息的可读 state 类名.

    Raises:
        ValueError: 同一 fragment_id 出现 >1 条 state（违反当前 1:1 契约）.
    """
    out: Dict[str, Any] = {}
    for state in states:
        fid = getattr(state, "fragment_id", "")
        if fid in out:
            raise ValueError(
                f"{state_kind} per-fragment 1:1 不变式被违反：fragment_id {fid!r} "
                f"出现多条 {state_kind}。build_normative_projections_for_world 主循环按 "
                f"fragment_id 单值消费 mechanism / condition；如 W1 已正式支持同 fragment "
                f"多 condition（multi-DC overlay），须改主循环显式处理多条路径，不能依赖 "
                f"dict 覆盖。"
            )
        out[fid] = state
    return out


def build_sidecar_numeric_index(
    sidecar_runtime_bundle: Optional[Any],
    registries: Any,
) -> Dict[str, List[Dict[str, Any]]]:
    """从 sidecar bundle 提取 per-fragment numeric slot values（batch-scope helper）.

    Codex review 2026-05-27 W2 perf root cause: 原 build_normative_projections_for_world
    内每个 building 调用都从头扫整 bundle 建此索引，N building × N record 形成
    O(N²) 扫描。1500×1500=2.25M 操作, 12000×12000=144M (64× 放大, 跟 8× scale 不
    线性). 抽出 batch-scope helper, validation.py 主入口建一次, 传给每 building
    W2 投影避免重复扫描.

    Returns:
        fragment_id -> List[{"slot_id", "value_num", "unit", "measurement_family"}]
    """
    sidecar_numeric_by_fragment: Dict[str, List[Dict[str, Any]]] = {}
    if sidecar_runtime_bundle is None:
        return sidecar_numeric_by_fragment

    # sidecar registry lookup（拿 unit / measurement_family）
    sidecar_slot_meta: Dict[str, Dict[str, Any]] = {}
    for registry in getattr(registries, "registries", []):
        if registry.registry_id == "sidecar_measurement_registry":
            for rec in registry.records:
                sidecar_slot_meta[rec["slot_id"]] = rec
            break

    for record in sidecar_runtime_bundle.records:
        # SidecarRuntimeRecord.runtime_id 形如 SCR-<fragment_id>；fragment_id 也直接在
        # qualifiers 里。这里用 qualifier 路径稳妥。
        for bucket_name in (
            "facts", "procedure_gate_state", "supervision_runtime_state",
            "artifact_requirement_state", "completion_runtime_state",
        ):
            for v in getattr(record, bucket_name, []):
                if not isinstance(v.value, (int, float)):
                    continue
                fragment_id = (v.qualifiers or {}).get("fragment_id", "")
                if not fragment_id:
                    continue
                meta = sidecar_slot_meta.get(v.slot_id, {})
                sidecar_numeric_by_fragment.setdefault(fragment_id, []).append({
                    "slot_id": v.slot_id,
                    "value_num": float(v.value),
                    "unit": meta.get("unit"),
                    "measurement_family": meta.get("measurement_family", ""),
                })
    return sidecar_numeric_by_fragment


def build_normative_projections_for_world(
    world: Any,
    registries: Any,
    sidecar_runtime_bundle: Optional[Any] = None,
    *,
    coverage_control_profile: Optional[Dict[str, Any]] = None,
    apply_coverage_control: bool = True,
    sidecar_numeric_by_fragment: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """Missing #2: Per fragment build NormativeProjection (spec 04 §16).

    Pipeline (T-23 + T-24 + T-25 整合 from #3 + W2-007 批次 D 2026-05-21):
      1. For each fragment, derive candidate projection families from mechanism family
      2. Call evaluate_fragment_projection_candidates
      3. Build NormativeProjection-compatible dict per fragment
      4. (W2-007) coverage-controlled rejection filter（spec 11 §3.1，phase 3 输出 ↔ phase 4 聚合之间）

    spec 09 §1.2 修订（2026-05-09）：sidecar_runtime_bundle 提供时，把 sidecar slot
    数值（procedure_gate_state / supervision_runtime_state / facts 桶里的 numeric value）
    也加入 threshold_inputs；让 sidecar 5 slot 的 distribution 真正进入 5-bin 评估。

    W2-007（批次 D 2026-05-21）+ DEBT-044 修根（2026-06-11）：
      - 单楼调用**不做楼内裁剪**（candidate 粒度 = 楼，spec 11 §3.3；单楼无批内
        分布可参照，spec 11 §1.2 原则二）——apply_coverage_control=True / False
        返回的列表相同（均为该楼全量 candidate）.
      - 批级 accept/reject（楼级取舍）走 regulation_coverage_control.
        apply_coverage_control_rejection_building_level，由
        validation.run_worldgenerator_fullcoverage_framework_v2 收齐全部楼后调一次.
      - per-world 楼级分类 metadata 由 build_normative_projections_for_world_with_coverage_control
        carry（本函数返回 List 保 backward compat，不返 metadata）.

    Returns list of dicts (NormativeProjection model_dump form), per fragment with mechanism.
    """
    from workflow_engine.regulation_projection_models import NormativeProjection
    # DEBT-020 round2 closure 2026-05-09: find_threshold_for_slot 已废弃，统一用
    # find_thresholds_for_slot_any_family 跨家族查 + 多阈值全 emit.

    projection_family_index = _projection_registry_lookup(registries)
    # BC-2 fix (2026-05-23)：主循环按 fragment_id 单值消费 mechanism / condition，
    # 用 _index_unique_by_fragment 显式 enforce per-fragment 1:1 不变式（rationale 见该 helper docstring）。
    mechanism_by_fragment = _index_unique_by_fragment(world.mechanisms, "MechanismState")
    condition_by_fragment = _index_unique_by_fragment(world.conditions, "ConditionState")
    # W0-004 step 6 (2026-05-21)：spec 04 §7 FragmentContext reference-based contract——
    # fragment 的 component_type 等物理上下文走 `fragment.component_id → ComponentNode` 反查
    # （旧 denorm 字段 fragment.component_type_id 已撤出 W0 contract，按 spec 06 §0.1 路径）.
    component_by_id = {c.component_id: c for c in world.components}
    # PT-1 perf (2026-05-23)：location 索引同建一次，沿调用链透传给
    # _build_candidate_families_for_fragment → _evaluate_applicability_predicates →
    # _evaluate_qualifier_predicate，替换 qualifier predicate 内每次调用的全量线性扫描。
    location_by_id = {loc.location_id: loc for loc in world.locations}
    # SA-1 fix (2026-05-23)：defect_geometry_measurement 的 target_ref 是 condition_id
    # （spec 07 §C017 + spec 04 §16/§17），其余 family 的 target_ref 是 fragment_id。
    # 本函数下游（candidate evaluator / threshold lookup）按 fragment_id 取测量，
    # 故 defect_geometry 测量须先经 condition_id→fragment_id 反查再归桶，否则
    # 几何测量会被埋在 condition_id 键下、per-fragment 取不到。
    # ConditionState 同时携带 condition_id + fragment_id（models.py ConditionState），
    # 直接建反查映射。
    fragment_id_by_condition: Dict[str, str] = {
        c.condition_id: c.fragment_id for c in world.conditions
    }
    measurements_by_fragment: Dict[str, List[Any]] = {}
    for measurement in world.measurements:
        bucket_key = measurement.target_ref
        if measurement.measurement_family == "defect_geometry_measurement":
            # condition_id 锚点 → 反查 fragment_id；映射缺失时回退 target_ref 原值
            # （保守，不丢测量）。
            bucket_key = fragment_id_by_condition.get(
                measurement.target_ref, measurement.target_ref
            )
        measurements_by_fragment.setdefault(bucket_key, []).append(measurement)

    # spec 09 §1.2: 从 sidecar bundle 提取 per-fragment numeric slot values（为 threshold eval 用）
    # key: fragment_id → List[Tuple[slot_id, value, unit, carrier_domain]]
    # Codex W2 perf root cause fix (2026-05-27)：caller 传入 batch-scope 预 build 索引时
    # 跳过 inline 重建（spec §9.1.2 不变；只是 N building 调用不再 N² 扫 bundle）.
    if sidecar_numeric_by_fragment is None:
        sidecar_numeric_by_fragment = build_sidecar_numeric_index(
            sidecar_runtime_bundle, registries
        )

    projections: List[Dict[str, Any]] = []
    for index, fragment in enumerate(world.fragments):
        mechanism = mechanism_by_fragment.get(fragment.fragment_id)
        condition = condition_by_fragment.get(fragment.fragment_id)
        if mechanism is None:
            continue
        severity = condition.severity_index if condition else 0.0
        # W0-004 step 6 (2026-05-21)：按 spec 06 §0.1 reference 反查路径
        # `fragment.component_id → ComponentNode.component_type` 取 component_type.
        component = component_by_id.get(fragment.component_id)
        component_type = component.component_type if component is not None else ""

        # W2-008 (批次 C 2026-05-21)：传 evaluator 上下文（fragment + mechanism + condition +
        # world + measurements + sidecar）走 spec 06 §4 applicability_predicates evaluator
        # 主路径；evaluator 空 candidates 时函数内回落 spec §4.4 simplified fallback.
        candidates = _build_candidate_families_for_fragment(
            fragment_id=fragment.fragment_id,
            mechanism_family=mechanism.mechanism_family,
            component_type=component_type,
            severity_index=severity,
            projection_family_index=projection_family_index,
            fragment=fragment,
            mechanism=mechanism,
            condition=condition,
            world=world,
            fragment_measurements=measurements_by_fragment.get(fragment.fragment_id, []),
            sidecar_runtime_bundle=sidecar_runtime_bundle,
            sidecar_numeric_entries=sidecar_numeric_by_fragment.get(fragment.fragment_id, []),
            component_by_id=component_by_id,
            location_by_id=location_by_id,
        )

        conflict_group = None
        if candidates:
            first_family = projection_family_index.get(candidates[0]["family_id"], {})
            conflict_group = first_family.get("conflict_group")

        # F2: 真阈值 lookup（rule_cards_delta.jsonl 数据）
        # 仅 candidates 非空时才查；候选 family 决定 threshold 来源
        candidate_family = candidates[0]["family_id"] if candidates else None
        fragment_measurements = measurements_by_fragment.get(fragment.fragment_id, [])
        threshold_inputs: List[Dict[str, Any]] = []
        # DEBT-020 round2 closure 2026-05-09: W0 measurement + sidecar 都用跨家族查询.
        # 原设计：candidate_family 限定查（mechanism-driven，单 family），导致 W0 measurement
        # 18/22 round2 slot 0 threshold_evaluations（slot 真阈值在其他 family 下，单 family
        # 查不到）。改用 find_thresholds_for_slot_any_family 跨所有 family 按 measure_key 查，
        # 与 sidecar slot 路径一致。一个 slot 多 threshold（如 submission.deadline 7day + 14day）
        # 全部 emit 让 5-bin eval 各自跑。
        from workflow_engine.regulation_thresholds import find_thresholds_for_slot_any_family
        if candidate_family is not None:
            for m in fragment_measurements:
                if m.value_num is None:
                    continue
                thresholds = find_thresholds_for_slot_any_family(m.slot_id)
                if not thresholds:
                    continue
                family = m.measurement_family.replace("_measurement", "")
                for threshold in thresholds:
                    threshold_inputs.append({
                        "rule_id": threshold.rule_card_id,
                        "threshold_regime_id": threshold.threshold_regime_id,
                        "slot_id": m.slot_id,
                        "operator": threshold.operator,
                        "threshold_value": threshold.value,
                        "observed_value": m.value_num,
                        "measurement_family": family,
                        "slot_unit": threshold.unit or m.unit,
                    })
            # spec 09 §1.2 修订：sidecar 数值 slot 也加入 threshold_inputs（同 W0 measurement 路径）.
            for sv in sidecar_numeric_by_fragment.get(fragment.fragment_id, []):
                thresholds = find_thresholds_for_slot_any_family(sv["slot_id"])
                if not thresholds:
                    continue
                family = str(sv.get("measurement_family") or "").replace("_measurement", "")
                for threshold in thresholds:
                    threshold_inputs.append({
                        "rule_id": threshold.rule_card_id,
                        "threshold_regime_id": threshold.threshold_regime_id,
                        "slot_id": sv["slot_id"],
                        "operator": threshold.operator,
                        "threshold_value": threshold.value,
                        "observed_value": sv["value_num"],
                        "measurement_family": family,
                        "slot_unit": threshold.unit or sv.get("unit"),
                    })

        result = evaluate_fragment_projection_candidates(
            fragment_id=fragment.fragment_id,
            candidate_families=candidates,
            conflict_group_id=conflict_group,
            threshold_eval_inputs=threshold_inputs,
        )

        selected_family = result["selected_family_ids"][0] if result["selected_family_ids"] else "unknown"
        family_record = projection_family_index.get(selected_family, {})
        projection_registry_id = family_record.get("projection_registry_id", f"NP_UNKNOWN_{fragment.fragment_id}")

        # W2-011: spec 09 §2 projection_id 三段格式 NP-<world_id>-<fragment_id>-<index>
        projection_id = f"NP-{world.world_id}-{fragment.fragment_id}-{index:02d}"

        # W2-010: spec 09 §2 coverage_status 派生独立化——基于 required_world_core_slots
        # 是否到位，跟 projection_status 解耦。worldgen 端 world.fragments / mechanisms /
        # conditions / drainage_states / ubw_states / fire_safety_states 等是 world truth
        # 底座；selected family 的 required_world_core_slots 全部 family-record 内引用的
        # world slot 都属 W1 派生的 world truth 范畴，单 fragment 主循环视角默认 ready。
        # selected_family=unknown 时 family_record 为空，没有 required_world_core_slots
        # 需求 → world_core_ready；不依赖 sidecar 状态。
        required_world_core_for_family = family_record.get("required_world_core_slots", [])
        if selected_family == "unknown":
            coverage_status = "unsupported"
        elif required_world_core_for_family:
            # 当前 W1 mechanism/condition 派生层默认 ready；后续如增 partial-ready
            # detector 可在此细化（DEBT-031 gap 11 留作 follow-up）
            coverage_status = "world_core_ready"
        else:
            # family 无 world core slot 需求（如 sidecar-only family）→ trivially ready
            coverage_status = "world_core_ready"

        # W2-009: spec 09 §4 applicability_state 4 enum 派生
        # 主循环按当前 simplified routing（_build_candidate_families_for_fragment）
        # 产 single-candidate；若 selected → applicable；selected_family=unknown 且
        # candidates 非空（mechanism 路由有 candidate 但 required_slots_present=False）
        # → neighbor；candidates 全空 → uncovered；conflict_group 同组多选无法解析 → inapplicable
        def _derive_applicability_state(
            family_id: str, candidate_entry: Optional[Dict[str, Any]]
        ) -> str:
            if candidate_entry is None:
                # candidates 全空 → no family 适用
                return "uncovered"
            if candidate_entry.get("required_slots_present"):
                return "applicable"
            # required_slots 缺 + mechanism 路由 hit → 邻接 family
            return "neighbor"

        matched_families: List[Dict[str, Any]] = []
        # 选 single candidate 时，selected_family_ids[0] 对应 candidates[0]（_build_candidate
        # _families_for_fragment 当前 single-target 实现）
        selected_candidate = candidates[0] if candidates else None
        # N-01 修复：matched_families[].applicability_score 取 W2-008 evaluator 实算分
        # （_evaluate_applicability_predicates 的 4 类 predicate passed/total 比例），不再写
        # severity（ConditionState.severity_index）。两者都落 [0,1] 故旧 code pydantic 不报错，
        # 但语义错位——下游 coverage-controlled rejection 的 is_neighbor_family_overlap 按
        # applicability_score >= 0.5 判 neighbor overlap，须读真实适用性分而非 severity。
        candidate_score_by_family: Dict[str, float] = {
            c["family_id"]: c["applicability_score"] for c in candidates
        }
        for family_id in result["selected_family_ids"]:
            fr = projection_family_index.get(family_id, {})
            matched_families.append({
                "family_id": family_id,
                # 取该 family 对应 candidate 的 evaluator 实算分；selected_family_ids 来自
                # resolve_family_conflict(candidates,...) 必是 candidates 子集，正常都命中；
                # 极端兜底（family_id 不在 candidates）回退 severity 保字段非空 + [0,1] 合法.
                "applicability_score": candidate_score_by_family.get(family_id, severity),
                "applicability_state": _derive_applicability_state(family_id, selected_candidate),
                "trigger_ids": [mechanism.mechanism_family],
                "rule_ids": fr.get("rule_ids", []),
                "slot_role_map": {},
                "threshold_evaluations": result["threshold_evaluations"],
                # W2-003: spec 09 §3 family verdict 派生（4 enum pass/fail/unknown/not_applicable，
                # NO "covered"）。threshold_evaluations 全 pass → pass；任一 fail → fail；
                # family unknown → unknown；family 适用但无 threshold eval → not_applicable
                "verdict": _derive_family_verdict(
                    family_id, result["threshold_evaluations"], result["projection_status"],
                ),
            })

        if severity >= 0.85:
            severity_band = "emergency"
        elif severity >= 0.66:
            severity_band = "severe"
        elif severity >= 0.33:
            severity_band = "moderate"
        elif severity > 0:
            severity_band = "minor"
        else:
            severity_band = "none"

        # W2-001: spec 09 §3 expected_verdict 4 派生顺序
        # 1. selected_family=unknown → unknown
        # 2. projection_status=conflict 且无法 selector 解决 → unknown
        # 3. selected family verdict ∈ {pass/fail/unknown/not_applicable} → 取该 family verdict
        # 4. basis_items 为空时不得输出该 projection（C025 reject 路径）
        expected_verdict = _derive_expected_verdict(
            selected_family=selected_family,
            projection_status=result["projection_status"],
            matched_families=matched_families,
        )

        # 构造 basis_items（W2 规格 09 §6 ReportBasisItem 5 kind 派生路径 +
        # W2 规格 07 §5.3 C025 BASIS_NONEMPTY P0 reject 约束）
        basis_items: List[Dict[str, Any]] = []

        # threshold_compare basis：per ThresholdEval（W2 规格 09 §6）
        for te in result["threshold_evaluations"]:
            basis_items.append({
                "basis_kind": "threshold_compare",
                "basis_id": f"BASIS-TC-{te['rule_id']}-{te['slot_id']}",
                "family_id": selected_family,
                "rule_id": te["rule_id"],
                "slot_id": te["slot_id"],
                "source_projection_id": projection_id,
                "operator": te["operator"],
                "threshold_value": te["threshold_value"],
                "regime_tag": te["regime_tag"],
                "observed_value": te["observed_value"],
                "pass_bool": te["pass_bool"],
            })

        # family_uncovered basis：selected_family=unknown 时构造（W2 规格 09 §6）
        if selected_family == "unknown":
            basis_items.append({
                "basis_kind": "family_uncovered",
                "basis_id": f"BASIS-UNCOVERED-{fragment.fragment_id}",
                "family_id": "unknown",
                "rule_id": "",
                "slot_id": "",
                "source_projection_id": projection_id,
                "observed_value": None,
                "reason_code": result["unknown_reason_code"],
                "candidate_known_families": [c["family_id"] for c in candidates],
            })

        # measurement_origin basis：per fragment_measurement（W2 规格 09 §6）
        for m in fragment_measurements:
            obs = m.value_num if m.value_num is not None else (
                m.value_bool if m.value_bool is not None else m.value_enum
            )
            basis_items.append({
                "basis_kind": "measurement_origin",
                "basis_id": f"BASIS-MO-{m.measurement_id}",
                "family_id": selected_family,
                "rule_id": "",
                "slot_id": m.slot_id,
                "source_projection_id": projection_id,
                "observed_value": obs,
                "unit": m.unit,
            })

        # C023 P3 fallback（W2 规格 07 §5.1）：selected_family=unknown 时
        # matched_families.rule_ids 必须清空
        if selected_family == "unknown":
            for mf in matched_families:
                if mf.get("rule_ids"):
                    mf["rule_ids"] = []

        # W2-013: 删 world_origin 兜底（spec 07 §5.3 C025 BASIS_NONEMPTY 真正 P0 reject）
        # 当 basis_items 真为空，按 C025 走 reject projection（不 append 到结果列表），
        # 不再永远塞 1 条 world_origin mechanism_family 凑 C025
        if not basis_items:
            # C025 reject 路径：basis 真为空时不输出此 projection
            continue

        # PT-2 perf (2026-05-27)：原 NormativeProjection(...) Pydantic 验证对每 dict
        # 字段（matched_families List[ProjectionFamilyEval] + basis_items
        # List[ReportBasisItem]）做 nested validation, cProfile 显示 1500x1 跑
        # 991s 里 W2 投影 925s, dict.get 19.5 亿次主要来自 Pydantic nested coercion.
        # 下游 (write_normative_projection_parquet / execute_projection_batch_v2)
        # 消费 dict 形态, 不需要 NormativeProjection 类 instance. 跳 Pydantic 直接 append
        # dict, 等价 model_dump(mode="json") 输出.
        projection_dict = {
            "projection_id": projection_id,
            "projection_registry_id": projection_registry_id,
            "projection_family": selected_family,
            "world_id": world.world_id,
            "fragment_id": fragment.fragment_id,
            "projection_version": "2.0.0",
            "matched_families": matched_families,
            "selected_family": selected_family,
            "projection_status": result["projection_status"],
            "expected_verdict": expected_verdict,
            "required_slots": list(family_record.get("required_world_core_slots", []))
            + list(family_record.get("required_measurement_slots", [])),
            "basis_items": basis_items,
            "unknown_reason_code": result["unknown_reason_code"],
            "sidecar_join_status": derive_sidecar_join_status(
                fragment_id=fragment.fragment_id,
                required_sidecar_interfaces=family_record.get("required_sidecar_interfaces", []),
                sidecar_runtime_bundle=sidecar_runtime_bundle,
                sidecar_numeric_by_fragment=sidecar_numeric_by_fragment,
            ),
            "severity_band": severity_band,
            "required_world_core_slots": family_record.get("required_world_core_slots", []),
            "required_measurement_slots": family_record.get("required_measurement_slots", []),
            "required_qualifier_slots": family_record.get("required_qualifier_slots", []),
            "required_sidecar_interfaces": family_record.get("required_sidecar_interfaces", []),
            "matched_component_refs": [component_type] if component_type else [],
            "matched_measurement_ids": [m.measurement_id for m in fragment_measurements],
            "coverage_status": coverage_status,
            "notes": [],
        }
        projections.append(projection_dict)

    # W2-007 (批次 D 2026-05-21) + DEBT-044 修根 (2026-06-11)：
    # 单楼调用没有批内分布可参照（spec 11 §1.2 原则二），不做楼内裁剪——
    # apply_coverage_control_rejection 修根后为单楼 candidate 视角（全量接受）；
    # 批级真正 accept/reject 走 apply_coverage_control_rejection_building_level
    # （楼级取舍，validation.py 收齐全部楼后调一次）.
    if apply_coverage_control and projections:
        from workflow_engine.regulation_coverage_control import (
            apply_coverage_control_rejection,
        )
        projections, _ = apply_coverage_control_rejection(
            projections, profile=coverage_control_profile,
        )

    return projections


def build_normative_projections_for_world_with_coverage_control(
    world: Any,
    registries: Any,
    sidecar_runtime_bundle: Optional[Any] = None,
    *,
    coverage_control_profile: Optional[Dict[str, Any]] = None,
    sidecar_numeric_by_fragment: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """W2-007 (批次 D 2026-05-21)：build_normative_projections_for_world 带 coverage
    metadata 返回的伴随入口.

    DEBT-044 修根 (2026-06-11) 后语义：
      - 单楼调用不再做楼内裁剪——accepted_projections == 该楼全量 candidate
        （spec 11 §1.2 原则二 "按 batch 内分布判断"，单楼无批内分布可参照；
        candidate 粒度 = 楼，spec 11 §3.3）.
      - coverage_control_metadata 为楼级分类 metadata（候选计数单位 = 楼，
        本楼 primary bucket 计 1）；字段仍按 spec 11 §3.2
        CoverageControlBatchMetadata 6 字段契约.
      - 批级真正 accept/reject 走
        regulation_coverage_control.apply_coverage_control_rejection_building_level
        （楼级取舍；validation.run_worldgenerator_fullcoverage_framework_v2 收齐
        全部楼的全量 candidate 后调一次）.

    Returns:
        (accepted_projections, coverage_control_metadata_dict).
    """
    from workflow_engine.regulation_coverage_control import (
        apply_coverage_control_rejection,
    )
    # 先 disable inline filter 拿全量 candidates → 再外置 filter 拿 metadata.
    candidates = build_normative_projections_for_world(
        world,
        registries,
        sidecar_runtime_bundle=sidecar_runtime_bundle,
        apply_coverage_control=False,
        sidecar_numeric_by_fragment=sidecar_numeric_by_fragment,
    )
    accepted, metadata = apply_coverage_control_rejection(
        candidates, profile=coverage_control_profile,
    )
    return accepted, metadata


# ---------- W2-001 / W2-003 verdict 派生 helpers ----------


def _derive_family_verdict(
    family_id: str,
    threshold_evaluations: List[Dict[str, Any]],
    projection_status: str,
) -> str:
    """W2-003: spec 09 §3 / §4 ProjectionFamilyEval.verdict 派生.

    4 enum: pass / fail / unknown / not_applicable（NO "covered"）.

    规则：
    - family_id == "unknown" → unknown（spec §3 第 1 条）
    - projection_status == "conflict" → unknown
    - threshold_evaluations 空 → not_applicable（family 适用但无 threshold 评估）
    - 任一 threshold pass_bool == False → fail
    - 全 pass → pass
    """
    if family_id == "unknown":
        return "unknown"
    if projection_status == "conflict":
        return "unknown"
    if not threshold_evaluations:
        return "not_applicable"
    if any(te.get("pass_bool") is False for te in threshold_evaluations):
        return "fail"
    if all(te.get("pass_bool") is True for te in threshold_evaluations):
        return "pass"
    # 混合 None / 部分 unknown → unknown
    return "unknown"


def _derive_expected_verdict(
    selected_family: str,
    projection_status: str,
    matched_families: List[Dict[str, Any]],
) -> str:
    """W2-001: spec 09 §3 expected_verdict 4 派生顺序.

    4 enum: pass / fail / unknown / not_applicable（NO "pending"）.

    派生顺序（spec 09 §3）：
    1. selected_family == "unknown" → unknown
    2. projection_status == "conflict" 且无法解决 → unknown
    3. selected family 的 ProjectionFamilyEval.verdict ∈ 4 enum → 取该值
    4. basis_items 为空时不输出该 projection（C025 reject 路径，本函数前置）
    """
    if selected_family == "unknown":
        return "unknown"
    if projection_status == "conflict":
        return "unknown"
    # 取 selected family 的 verdict
    for mf in matched_families:
        if mf.get("family_id") == selected_family:
            v = mf.get("verdict", "unknown")
            if v in ("pass", "fail", "unknown", "not_applicable"):
                return v
            return "unknown"
    # selected_family 不在 matched_families（理论不该发生）→ unknown
    return "unknown"


# ---------- execute_projection_batch v2 化 ----------


def execute_projection_batch_v2(
    building_worlds_path: Path,
    normative_projection_path: Path,
    sidecar_runtime_path: Path,
    output_dir: Path,
) -> Dict[str, Path]:
    """V2 batch projection executor — reads building-centric v2 inputs + aggregates.

    跟 OLD execute_projection_batch 的差异：
    - 输入：v2 building_worlds JSON（buildings: [...]，spec 04 §3）+ v2 normative_projection
      JSON（pre-built per fragment NormativeProjection，由 v2 entry 输出 / Missing #2）+
      v2 sidecar_runtime JSON
    - 不再需要 compiled rule_card spec：projection 评估在 v2 entry 内已通过
      build_normative_projections_for_world 完成；此函数只做 batch-level 聚合
    - 输出：summary / results / samples（v2 格式，跟 OLD 输出 schema 类似但聚合维度对齐
      spec 04 §16 + spec 06 §16.3）

    Pipeline：
      1. 读 v2 building_worlds + normative_projection + sidecar_runtime
      2. Iterate over per-fragment NormativeProjection
      3. 聚合 verdict（projection_status）/ family hit / unknown_reason_code 桶 /
         severity_band 分布 / sidecar_join 状态
      4. 输出 RegulationProjectionSummary.v2.json + Results.v2.json + Samples.v2.json

    后续工单计划：删除 OLD execute_projection_batch + 改 regulation_projection.py CLI 用 v2 +
    重写 / 归档 OLD test_regulation_projection.py。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    np_payload = _load_normative_projection(normative_projection_path)
    sidecar_bundle = _load_sidecar_runtime(sidecar_runtime_path)
    bw_payload = _load_world_bundles(building_worlds_path)

    # Aggregate counters
    verdict_counter: Counter[str] = Counter()  # projection_status as verdict proxy
    family_hit_counter: Counter[str] = Counter()  # selected_family
    family_status_breakdown: Dict[str, Counter[str]] = defaultdict(Counter)
    unknown_reason_counter: Counter[str] = Counter()
    severity_band_counter: Counter[str] = Counter()
    coverage_status_counter: Counter[str] = Counter()
    threshold_regime_counter: Counter[str] = Counter()  # spec 06 §15 5-bin
    threshold_pass_counter: Counter[str] = Counter()  # pass / fail

    total_projections = 0
    sidecar_join_status_counter: Counter[str] = Counter()  # W2 spec 09 §1.1 3 枚举 distribution
    buildings_with_projections = 0

    # W2-007 (批次 D 2026-05-21)：spec 11 §3.2 batch-level CoverageControlBatchMetadata 聚合.
    # 输入 per-world coverage_control_metadata（payload buildings[].coverage_control_metadata，
    # 由 build_normative_projections_for_world_with_coverage_control 产；老 batch 输出可能缺）.
    coverage_control_aggregated: Dict[str, Any] = {
        "coverage_control_profile_id": "",
        "bucket_definition_version": "",
        "public_report_note": "",
        "raw_candidate_bucket_counts": Counter(),
        "accepted_bucket_counts": Counter(),
        "rejected_bucket_counts": Counter(),
        "per_world_metadata_count": 0,
    }

    for building_entry in np_payload.get("buildings", []):
        projections = building_entry.get("projections", [])
        if projections:
            buildings_with_projections += 1
        # W2-007 spec 11 §3.2：per-world coverage_control_metadata aggregate.
        ccm = building_entry.get("coverage_control_metadata")
        if ccm:
            coverage_control_aggregated["per_world_metadata_count"] += 1
            if not coverage_control_aggregated["coverage_control_profile_id"]:
                coverage_control_aggregated["coverage_control_profile_id"] = ccm.get(
                    "coverage_control_profile_id", ""
                )
            if not coverage_control_aggregated["bucket_definition_version"]:
                coverage_control_aggregated["bucket_definition_version"] = ccm.get(
                    "bucket_definition_version", ""
                )
            if not coverage_control_aggregated["public_report_note"]:
                coverage_control_aggregated["public_report_note"] = ccm.get(
                    "public_report_note", ""
                )
            for bucket, count in (ccm.get("raw_candidate_bucket_counts") or {}).items():
                coverage_control_aggregated["raw_candidate_bucket_counts"][bucket] += int(count)
            for bucket, count in (ccm.get("accepted_bucket_counts") or {}).items():
                coverage_control_aggregated["accepted_bucket_counts"][bucket] += int(count)
            for bucket, count in (ccm.get("rejected_bucket_counts") or {}).items():
                coverage_control_aggregated["rejected_bucket_counts"][bucket] += int(count)
        for projection in projections:
            total_projections += 1
            family = projection.get("selected_family", "unknown")
            family_hit_counter[family] += 1
            status = projection.get("projection_status", "unknown")
            family_status_breakdown[family][status] += 1
            verdict_counter[status] += 1
            severity_band_counter[projection.get("severity_band", "unknown")] += 1
            coverage_status_counter[projection.get("coverage_status", "unknown")] += 1
            unknown_reason = projection.get("unknown_reason_code")
            if unknown_reason:
                unknown_reason_counter[unknown_reason] += 1
            # W2 spec 09 §1.1 3 枚举 distribution
            # (2026-05-13 撤回原 4 枚举 sidecar_derivation_failed；同步删 legacy "sidecar_missing" 分支)
            sjs = projection.get("sidecar_join_status", "unavailable")
            sidecar_join_status_counter[sjs] += 1
            # threshold regime aggregation across all matched_families
            for matched in projection.get("matched_families", []):
                for thr in matched.get("threshold_evaluations", []):
                    regime = thr.get("regime_tag", "not_numeric")
                    threshold_regime_counter[regime] += 1
                    pass_bool = thr.get("pass_bool")
                    if pass_bool is True:
                        threshold_pass_counter["pass"] += 1
                    elif pass_bool is False:
                        threshold_pass_counter["fail"] += 1

    sidecar_record_count = len(sidecar_bundle.get("records", []))
    sidecar_missing_marker_count = sum(
        1 for record in sidecar_bundle.get("records", [])
        if any(
            m.get("slot_id") == "marker.sidecar_missing" and m.get("value") is True
            for m in record.get("runtime_markers", [])
        )
    )

    # W2-007 (批次 D 2026-05-21)：batch-level CoverageControlBatchMetadata 聚合产物.
    # spec 11 §3.2 6 字段 + per_world_metadata_count（batch 内带 metadata 的 world 数）.
    # public_report_note 不暴露 internal target ratio（spec 11 §3.2 / §4.2 / NI-004）.
    coverage_control_metadata = {
        "coverage_control_profile_id": coverage_control_aggregated["coverage_control_profile_id"],
        "raw_candidate_bucket_counts": dict(
            coverage_control_aggregated["raw_candidate_bucket_counts"]
        ),
        "accepted_bucket_counts": dict(
            coverage_control_aggregated["accepted_bucket_counts"]
        ),
        "rejected_bucket_counts": dict(
            coverage_control_aggregated["rejected_bucket_counts"]
        ),
        "bucket_definition_version": coverage_control_aggregated["bucket_definition_version"],
        "public_report_note": coverage_control_aggregated["public_report_note"],
        "per_world_metadata_count": coverage_control_aggregated["per_world_metadata_count"],
    }

    summary = {
        "version": "regulation_projection.summary.v2",
        "generated_at": _utc_now_iso(),
        "building_worlds_path": str(building_worlds_path),
        "normative_projection_path": str(normative_projection_path),
        "sidecar_runtime_path": str(sidecar_runtime_path),
        "buildings_count": len(np_payload.get("buildings", [])),
        "buildings_with_projections": buildings_with_projections,
        "total_projections": total_projections,
        "sidecar_records_count": sidecar_record_count,
        "sidecar_missing_marker_count": sidecar_missing_marker_count,
        "sidecar_join_status_distribution": dict(sidecar_join_status_counter),
        "verdict_distribution": dict(verdict_counter),
        "family_hit_distribution": dict(family_hit_counter),
        "family_status_breakdown": {
            key: dict(value) for key, value in sorted(family_status_breakdown.items())
        },
        "unknown_reason_breakdown": dict(unknown_reason_counter),
        "severity_band_distribution": dict(severity_band_counter),
        "coverage_status_distribution": dict(coverage_status_counter),
        "threshold_regime_distribution": dict(threshold_regime_counter),
        "threshold_pass_distribution": dict(threshold_pass_counter),
        # W2-007 spec 11 §3.2：batch-level CoverageControlBatchMetadata aggregate.
        "coverage_control_metadata": coverage_control_metadata,
    }

    samples: List[Dict[str, Any]] = []
    for building_entry in np_payload.get("buildings", []):
        if building_entry.get("projections"):
            samples.append({
                "world_id": building_entry["world_id"],
                "projection_count": building_entry.get("projection_count", 0),
                "projections": building_entry["projections"][:5],
            })
        if len(samples) >= 10:
            break
    sample_payload = {
        "version": "regulation_projection.samples.v2",
        "generated_at": _utc_now_iso(),
        "samples": samples,
    }

    results_payload = {
        "version": "regulation_projection.results.v2",
        "generated_at": _utc_now_iso(),
        "buildings_count": len(np_payload.get("buildings", [])),
        "buildings": np_payload.get("buildings", []),
    }

    # 2026-05-10 全替换 parquet：Results.v2 改 directory（567 MB JSON → ~6 MB parquet）.
    # Summary / Samples 继续 JSON（前者 2.4 KB / 后者 ~500 KB，太小没必要 parquet）.
    return {
        "summary_path": _write_json(output_dir / "RegulationProjectionSummary.v2.json", summary),
        "results_path": str(_write_projection_results_parquet(output_dir / "RegulationProjectionResults.v2.parquet", results_payload)),
        "samples_path": _write_json(output_dir / "RegulationProjectionSamples.v2.json", sample_payload),
    }
