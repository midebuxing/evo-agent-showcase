"""Threshold 评估 —— spec §6.3.5。

实现：
- COMPARATORS 比较器表（8 个运算符）。
- 单位规则（unit_mismatch / missing_measurement）。
- formula handler 白名单：spec §6.3.5 只对 `n^2-2n+3` 加 deterministic
  handler（pull test additional-after-failure），其余 formula → blocked +
  unsupported_formula。
- threshold fact binding 顺序（exact measure_key → alias → slot_id → sidecar
  numeric → sidecar measure target）。

确定性、无 LLM：不实现通用公式解释器。
"""

from __future__ import annotations

import json
import operator
from typing import Any, Dict, List, Optional, Tuple

from evo_agent_baseline.contracts import FactAtom

from .fact_binding import FactIndex, parse_json_number, parse_value

# --------------------------------------------------------------------- #
# §6.3.5 比较器
# --------------------------------------------------------------------- #
COMPARATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda observed, expected: observed in expected,
    "not_in": lambda observed, expected: observed not in expected,
}

# §6.3.5 formula handler 白名单：唯一允许的公式表达式（去空白后比对）。
ALLOWED_PULL_TEST_FORMULA = {"n^2-2n+3", "n**2-2*n+3"}
# pull test formula 的输入 / 输出 measure_key。
PULL_TEST_INPUT_MEASURE = "count.pull_test.failed_cumulative"
PULL_TEST_OUTPUT_MEASURE = "count.pull_test.additional_after_failure"


def canonicalize_unit(unit: Optional[str]) -> Optional[str]:
    """单位 canonicalization（spec §6.3.5 单位规则用）。

    去首尾空白、转小写。None / 空串归一为 None。
    baseline 不做单位换算，只做大小写 / 空白无关的相等判定。
    """
    if unit is None:
        return None
    s = str(unit).strip().lower()
    return s or None


def compare(observed: Any, op: str, expected: Any) -> Optional[bool]:
    """用比较器表对 observed / expected 求值（spec §6.3.5 compare）。

    op 不在 COMPARATORS → 返回 None（上层判 unsupported_operator）。
    类型不兼容（如数值比较器收到非数值）→ 返回 None（上层判 blocked）。
    """
    fn = COMPARATORS.get(op)
    if fn is None:
        return None
    try:
        result = fn(observed, expected)
    except TypeError:
        return None
    return bool(result)


class ThresholdBinding:
    """一次 threshold fact binding 的结果。

    status:
      - "bound"      命中 fact，fact 字段可用
      - "missing"    无命中 fact
      - "ambiguous"  多命中且值冲突
    """

    def __init__(
        self,
        status: str,
        facts: Optional[List[FactAtom]] = None,
        bind_path: str = "",
    ) -> None:
        self.status = status
        self.facts: List[FactAtom] = facts or []
        self.bind_path = bind_path  # 命中的绑定来源（用于 notes / 调试）

    @property
    def primary(self) -> Optional[FactAtom]:
        """代表 fact（用于取 unit / value）。"""
        return self.facts[0] if self.facts else None


def bind_measure(
    measure_key: str,
    qualifiers: Dict[str, Any],
    fact_index: FactIndex,
    measure_aliases: Optional[Dict[str, str]] = None,
) -> ThresholdBinding:
    """threshold fact binding（spec §6.3.5 fact binding 顺序，5 级）。

    1. exact measure_key
    2. projection_runtime_mapping_v1.measure_aliases alias
    3. measurement slot_id exact
    4. sidecar numeric entry exact（slot_id == measure_key 的 sidecar 行）
    5. sidecar measure target（measure_targets：carrier 内 measure_key 匹配）

    命中后用 §6.3.4 qualifier 子集匹配过滤。
    """
    from .obligation_deriver import qualifiers_match  # 局部导入避免环依赖

    aliases = dict(measure_aliases or {})

    def _filter_by_qualifiers(facts: List[FactAtom]) -> List[FactAtom]:
        if not qualifiers:
            return list(facts)
        return [f for f in facts if qualifiers_match(qualifiers, f.qualifiers)]

    # 1. exact measure_key
    canon = fact_index.canonical_measure(measure_key)
    facts = _filter_by_qualifiers(fact_index.measure_index.get(canon, []))
    if facts:
        return ThresholdBinding("bound", facts, "exact_measure_key")

    # 2. measure_aliases alias
    alias_target = aliases.get(measure_key)
    if alias_target:
        facts = _filter_by_qualifiers(
            fact_index.measure_index.get(
                fact_index.canonical_measure(alias_target), []
            )
        )
        if facts:
            return ThresholdBinding("bound", facts, "measure_alias")

    # 3. measurement slot_id exact（把 measure_key 当 slot_id 试）
    facts = _filter_by_qualifiers(
        [
            f
            for f in fact_index.slot_index.get(
                fact_index.canonical_slot(measure_key), []
            )
            if f.carrier_type == "measurement"
        ]
    )
    if facts:
        return ThresholdBinding("bound", facts, "measurement_slot")

    # 4. sidecar numeric entry exact（sidecar 行 slot_id == measure_key）
    facts = _filter_by_qualifiers(
        [
            f
            for f in fact_index.slot_index.get(
                fact_index.canonical_slot(measure_key), []
            )
            if f.carrier_type == "sidecar_entry"
        ]
    )
    if facts:
        return ThresholdBinding("bound", facts, "sidecar_numeric_entry")

    # 5. sidecar measure target（sidecar 行 measure_key 字段匹配）
    facts = _filter_by_qualifiers(
        [
            f
            for f in fact_index.measure_index.get(canon, [])
            if f.carrier_type == "sidecar_entry"
        ]
    )
    if facts:
        return ThresholdBinding("bound", facts, "sidecar_measure_target")

    return ThresholdBinding("missing")


# 评估结果类型：(closure_status, satisfaction_status, detail_dict)
# detail_dict 携带 open_reason_code / blocked_reason_code / observed_value_json /
# comparator_result / notes 等，供 obligation_deriver 填进 Obligation。
ThresholdEvalResult = Tuple[str, str, Dict[str, Any]]


def evaluate_threshold_comparison(
    threshold: Dict[str, Any],
    fact_index: FactIndex,
    measure_aliases: Optional[Dict[str, str]] = None,
) -> ThresholdEvalResult:
    """评估单个 threshold regime（spec §6.3.5）。

    threshold 是 rule_card threshold_regimes[] 的一项 dict，读其中
    measure_key / operator / value / unit / qualifiers / time_anchor_key /
    formula(_json) 字段。

    返回 (closure_status, satisfaction_status, detail)。
    """
    op = threshold.get("operator")
    qualifiers: Dict[str, Any] = dict(threshold.get("qualifiers") or {})
    detail: Dict[str, Any] = {}

    # ---- operator == "formula" 走白名单 handler ----
    if op == "formula":
        return _evaluate_formula(threshold, fact_index, measure_aliases)

    # ---- operator 不支持 ----
    if op not in COMPARATORS:
        detail["blocked_reason_code"] = "unsupported_operator"
        detail["notes"] = f"operator {op!r} not in COMPARATORS"
        return ("blocked", "unknown", detail)

    measure_key = threshold.get("measure_key")
    if not measure_key:
        # 无 measure_key 无法绑定事实。
        detail["blocked_reason_code"] = "schema_contract_violation"
        detail["notes"] = "threshold_regime missing measure_key"
        return ("blocked", "unknown", detail)

    # 卡端比较值先落 detail（codex 钻 2026-07-08：bind 失败早退此前不写值，
    # 义务 threshold_value_json=null 丢审计信息——病族第十二例迷你款）。
    _expected = threshold.get("value")
    detail["expected_value_json"] = json.dumps(_expected, ensure_ascii=False)
    detail["threshold_value_json"] = detail["expected_value_json"]

    binding = bind_measure(measure_key, qualifiers, fact_index, measure_aliases)
    detail["bind_path"] = binding.bind_path

    # ---- 缺失事实 ----
    if binding.status == "missing":
        detail["open_reason_code"] = "missing_measurement"
        detail["notes"] = f"no fact bound for measure_key={measure_key!r}"
        return ("open", "unknown", detail)

    # ---- 多命中且值冲突 ----
    if binding.status == "ambiguous":
        detail["blocked_reason_code"] = "ambiguous_fact_binding"
        detail["notes"] = (
            f"conflicting facts bound for measure_key={measure_key!r}"
        )
        return ("blocked", "unknown", detail)

    fact = binding.primary
    detail["evidence_fact_ids"] = [f.fact_id for f in binding.facts]

    # ---- 单位规则（spec §6.3.5）----
    t_unit = canonicalize_unit(threshold.get("unit"))
    f_unit = canonicalize_unit(fact.unit)
    if t_unit and f_unit and t_unit != f_unit:
        detail["blocked_reason_code"] = "unit_mismatch"
        detail["unit"] = threshold.get("unit")
        detail["notes"] = (
            f"threshold unit {threshold.get('unit')!r} != fact unit {fact.unit!r}"
        )
        return ("blocked", "unknown", detail)
    if t_unit and not f_unit:
        detail["open_reason_code"] = "missing_measurement"
        detail["notes"] = "threshold requires unit but fact has no unit"
        return ("open", "unknown", detail)

    # ---- observed 值 ----
    observed = parse_value(fact.value_json)
    detail["observed_value_json"] = fact.value_json
    if observed is None:
        detail["open_reason_code"] = "null_observed_value"
        detail["notes"] = "observed value is null"
        return ("open", "unknown", detail)

    expected = threshold.get("value")
    detail["expected_value_json"] = json.dumps(expected, ensure_ascii=False)
    detail["threshold_value_json"] = json.dumps(expected, ensure_ascii=False)

    # in / not_in 的 expected 必须是容器。
    if op in {"in", "not_in"} and not isinstance(expected, (list, tuple, set)):
        detail["blocked_reason_code"] = "schema_contract_violation"
        detail["notes"] = f"operator {op!r} requires list value"
        return ("blocked", "unknown", detail)

    result = compare(observed, op, expected)
    if result is None:
        # 类型不兼容（如数值比较器收到非数值）。
        detail["blocked_reason_code"] = "unsupported_operator"
        detail["notes"] = (
            f"comparison failed: observed={observed!r} {op} expected={expected!r}"
        )
        return ("blocked", "unknown", detail)

    detail["comparator_result"] = result
    if result:
        return ("closed", "satisfied", detail)
    return ("closed", "violated", detail)


def _evaluate_formula(
    threshold: Dict[str, Any],
    fact_index: FactIndex,
    measure_aliases: Optional[Dict[str, str]] = None,
) -> ThresholdEvalResult:
    """formula handler 分发（spec §6.3.5 formula handler 白名单）。

    只有 `n^2-2n+3` pull test additional-after-failure 公式被实现；
    其余一律 blocked + unsupported_formula。
    """
    detail: Dict[str, Any] = {}
    formula = _load_formula(threshold)
    if formula is None:
        detail["blocked_reason_code"] = "unsupported_formula"
        detail["notes"] = "operator=formula but no parseable formula present"
        return ("blocked", "unknown", detail)

    expression = str(formula.get("expression", "")).replace(" ", "")
    if expression in ALLOWED_PULL_TEST_FORMULA:
        return handle_pull_test_additional_after_failure(
            threshold, formula, fact_index, measure_aliases
        )

    # 任何其他 formula。
    detail["blocked_reason_code"] = "unsupported_formula"
    detail["notes"] = f"formula expression {expression!r} not in whitelist"
    return ("blocked", "unknown", detail)


def _load_formula(threshold: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 threshold 取 formula dict。

    spec §5.6 要求 3：formula 从 RuleThreshold.formula_json 还原。本函数同时
    接受已解析的 `formula` dict 与 `formula_json` 字符串两种透传形态。
    """
    raw = threshold.get("formula")
    if isinstance(raw, dict):
        return raw
    raw_json = threshold.get("formula_json")
    if isinstance(raw_json, dict):
        return raw_json
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            parsed = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def handle_pull_test_additional_after_failure(
    threshold: Dict[str, Any],
    formula: Dict[str, Any],
    fact_index: FactIndex,
    measure_aliases: Optional[Dict[str, str]] = None,
) -> ThresholdEvalResult:
    """pull test additional-after-failure 公式 handler（spec §6.3.5）。

    expected = n^2 - 2n + 3，n = count.pull_test.failed_cumulative；
    observed = count.pull_test.additional_after_failure；
    判定 observed >= expected。

    n 缺失 / observed 缺失 → open + missing_measurement。
    """
    detail: Dict[str, Any] = {"bind_path": "formula_pull_test"}

    expression = str(formula.get("expression", "")).replace(" ", "")
    if expression not in ALLOWED_PULL_TEST_FORMULA:
        detail["blocked_reason_code"] = "unsupported_formula"
        detail["notes"] = f"unexpected expression {expression!r}"
        return ("blocked", "unknown", detail)

    qualifiers: Dict[str, Any] = dict(threshold.get("qualifiers") or {})

    # 绑定 n。
    n_binding = bind_measure(
        PULL_TEST_INPUT_MEASURE, qualifiers, fact_index, measure_aliases
    )
    if n_binding.status == "missing":
        detail["open_reason_code"] = "missing_measurement"
        detail["notes"] = f"missing input measure {PULL_TEST_INPUT_MEASURE}"
        return ("open", "unknown", detail)
    if n_binding.status == "ambiguous":
        detail["blocked_reason_code"] = "ambiguous_fact_binding"
        detail["notes"] = f"conflicting facts for {PULL_TEST_INPUT_MEASURE}"
        return ("blocked", "unknown", detail)
    n_value = parse_json_number(n_binding.primary.value_json)
    if n_value is None:
        detail["open_reason_code"] = "null_observed_value"
        detail["notes"] = f"{PULL_TEST_INPUT_MEASURE} value not numeric"
        return ("open", "unknown", detail)
    n = int(n_value)
    expected = n * n - 2 * n + 3
    detail["expected_value_json"] = json.dumps(expected)
    detail["threshold_value_json"] = json.dumps(expected)

    # 绑定 observed。
    obs_binding = bind_measure(
        PULL_TEST_OUTPUT_MEASURE, qualifiers, fact_index, measure_aliases
    )
    if obs_binding.status == "missing":
        detail["open_reason_code"] = "missing_measurement"
        detail["notes"] = f"missing output measure {PULL_TEST_OUTPUT_MEASURE}"
        return ("open", "unknown", detail)
    if obs_binding.status == "ambiguous":
        detail["blocked_reason_code"] = "ambiguous_fact_binding"
        detail["notes"] = f"conflicting facts for {PULL_TEST_OUTPUT_MEASURE}"
        return ("blocked", "unknown", detail)
    observed = parse_json_number(obs_binding.primary.value_json)
    detail["observed_value_json"] = obs_binding.primary.value_json
    detail["evidence_fact_ids"] = [
        f.fact_id for f in n_binding.facts + obs_binding.facts
    ]
    if observed is None:
        detail["open_reason_code"] = "null_observed_value"
        detail["notes"] = f"{PULL_TEST_OUTPUT_MEASURE} value not numeric"
        return ("open", "unknown", detail)

    result = observed >= expected
    detail["comparator_result"] = result
    detail["operator"] = ">="
    if result:
        return ("closed", "satisfied", detail)
    return ("closed", "violated", detail)


__all__ = [
    "COMPARATORS",
    "ALLOWED_PULL_TEST_FORMULA",
    "PULL_TEST_INPUT_MEASURE",
    "PULL_TEST_OUTPUT_MEASURE",
    "canonicalize_unit",
    "compare",
    "ThresholdBinding",
    "bind_measure",
    "evaluate_threshold_comparison",
    "handle_pull_test_additional_after_failure",
]
