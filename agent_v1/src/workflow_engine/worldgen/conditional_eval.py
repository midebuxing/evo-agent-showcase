"""W0 conditional formula evaluator (spec 06 §11.6 — DEBT-020 Round 6 + Round 7 落地版).

sidecar_bool_slot_registry 的 `conditional_formula` 字段从 string placeholder 升级为
结构化 dict，按 fragment / building 物理状态 + 已采样 sidecar slot upstream conditional sample
bool / categorical slot.

支持四种 formula 类型：

1. Bool slot  (`type: sigmoid_linear`):
       p = sigmoid(bias + sum(coef_i * input_i))
       sample = rng.uniform() < p

   Schema:
       {
           "type": "sigmoid_linear",
           "bias": float,
           "terms": Dict[str, float],   # input_name → coefficient
       }

2. Enum / categorical slot  (`type: softmax_per_class`):
       logit_c = bias_c + sum(coef_ci * input_i)  for each class c
       p_c = exp(logit_c) / sum_d exp(logit_d)    (softmax normalize)
       sample = rng.choices(classes, weights=[p_c])[0]

   Schema:
       {
           "type": "softmax_per_class",
           "classes": {
               "<class_name_1>": {"bias": float, "terms": Dict[str, float]},
               "<class_name_2>": {...},
               ...
           },
       }

3. **Round 6 centered bool**  (`type: centered_sigmoid_linear`):
       p = sigmoid(logit(anchor) + sum(coef_i * (input_i - upstream_expected_i)))

   头端工程依赖 + 尾端贴 marginal anchor 双向锚点（DEBT-020 Round 6 §1.1).
   Schema:
       {
           "type": "centered_sigmoid_linear",
           "anchor": float,                      # marginal_anchor (Round 7)
           "upstream_expected": Dict[str, float], # input_name → 中心化基准
           "terms": Dict[str, float],            # input_name → coefficient
       }

4. **Round 6 centered enum**  (`type: centered_softmax_per_class`):
       logit_c = log(anchor_c) + sum(coef_ci * (input_i - upstream_expected_i)) for each class c
       p_c = softmax(logits)
       sample multinomial.

   Schema:
       {
           "type": "centered_softmax_per_class",
           "classes": {
               "<class_name_1>": {
                   "anchor": float,                     # class marginal_anchor
                   "upstream_expected": Dict[str, float],
                   "terms": Dict[str, float],
               },
               ...
           },
       }

约束（DEBT-020 Round 6 §1.1 + spec 06 §11.6.2 修订 2026-05-11）：
  - 输入可以是：
      A. W0 fragment / building 物理 state (driver / mechanism / condition / drainage /
         fire_safety / repair_assessment / 派生 building-level 聚合) — Round 6 H.* 隐状态
      B. 已采样的 sidecar slot value (按 sampling_order < 当前 slot 拓扑早于自己的 slot,
         spec 06 §11.6.7 DAG validity)
  - 不读 rule_card threshold
  - bool 输入按 0/1 进入 linear combination
  - 不嵌套 sigmoid / softmax；不允许 cross-feature interaction（>2 阶）；不允许 if-then-else
  - 缺失 input → 默认 0.0（避免 KeyError）

Fallback：conditional_formula 为 None / 缺失 / 类型不识别 → 退回 marginal prevalence path
（_sample_sidecar_bool_slots_for_fragment 内已处理）.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional

# 输入变量白名单——只允许 W0 fragment / building 物理 state（pre-Round 6 接入）.
# Round 6 + Round 7 在此基础上扩 H.* 隐状态 + sidecar slot upstream（动态拼装在
# ALLOWED_INPUTS 全集内）.
ALLOWED_PHYSICAL_INPUTS = frozenset({
    # building / driver
    "age_norm",
    "service_load_ratio",
    "restraint_level",
    "workmanship_deficit",
    "maintenance_deficit",
    "moisture_ingress_index",
    "chloride_exposure",
    # mechanism / condition severity
    "crack_severity_index",
    "spall_severity_index",
    "corrosion_severity_index",
    "delamination_severity_index",
    "detachment_severity_index",
    # drainage state
    "drainage_blockage_index",
    "drainage_leakage_index",
    "public_health_risk_index",
    # bool indicators (0/1)
    "defect_class_present",
    "ubw_alteration_present",
    "fire_safety_deficiency_present",
    # repair assessment
    "repair_quality_index",
    "fsp_structural_performance",
    # building-level aggregates
    "building_total_severity_max",
    "building_defect_count_norm",  # normalized to [0, 1] by /20 cap
})

# DEBT-020 Round 6 §1.2: H.* hidden state 名单（19 项 building/fragment/admin/repair 派生）.
# 这些隐状态由 sidecar.py::_build_round6_hidden_state_for_fragment 从 W0 generator 已采样
# 状态派生（fragment / building / driver / mechanism / drainage / fire_safety /
# ubw / repair_assessment）. 详见 sidecar.py 文档.
ALLOWED_HIDDEN_INPUTS = frozenset({
    "H.case_active",
    "H.age_old_score",
    "H.admin_discipline_score",
    "H.admin_instability_score",
    "H.document_maturity_score",
    "H.defect_present",
    "H.defect_uncertainty",
    "H.defect_severity_score",
    "H.repair_need",
    "H.repair_complexity_score",
    "H.contractor_mobilisation_need",
    "H.testing_need",
    "H.material_replacement_need",
    "H.nonconformity_risk",
    "H.repair_quality_score",
    "H.fire_safety_need",
    "H.ubw_extra_work",
    "H.drainage_issue",
    "H.fire_door_issue",
})

# DEBT-020 Round 6 §1.3 sampling_order: 45 个 sidecar slot id 名单——拓扑排序后允许引用
# 拓扑早于自己的 slot 作为 upstream input. spec 06 §11.6.7 DAG validity 在 build 时校验.
ALLOWED_SIDECAR_INPUTS = frozenset({
    # L1 intake_and_ri (Round 7 修订: artifact.form.mbi2 移到 L1 temp_ri_nomination 分支)
    "procedure.ri.appointment.completed",
    "artifact.form.mbi1",
    "procedure.temp_ri_nomination.completed",
    "procedure.temp_ri_nomination.terminated",
    "procedure.ri_role.terminated",
    "artifact.form.mbi5",
    "artifact.form.mbi2",  # Round 7 §0: temp RI nomination form (COP §2.1.3(j))
    # L2 prescribed_inspection
    "procedure.inspection.prescribed.completed",
    "artifact.form.mbi3_or_mbi3a",
    "artifact.record.inspection_log",
    "artifact.report.inspection",
    "artifact.photo.annotated",
    "artifact.plan.annotated",
    # L3 detailed_investigation (Round 7 §0: artifact.form.mbi2 已移走，剩 6 slot)
    "procedure.investigation.intention_notified",
    "artifact.notice.investigation_intention",
    "procedure.investigation.proposal.submitted",
    "artifact.proposal.detailed_investigation",
    "procedure.investigation.proposal.recognized",
    "procedure.investigation.started",
    # L4 repair_supervision
    "procedure.supervision_representative.planned",
    "procedure.supervision_team.submitted",
    "procedure.supervision_team.changed",
    "artifact.proposal.repair",
    "procedure.rc.pre_notification_given",
    "procedure.repair.prescribed.started",
    "supervision.site_visit.performed",
    "artifact.record.supervision_log_sp1",
    "supervision.record.completed",
    "supervision.record.retained",
    "supervision.record.completed_and_retained",
    "artifact.record.test_or_material_witness",
    "artifact.certificate.material_or_product",
    "artifact.record.nonconformity_sp2",
    "procedure.repair.revision_required",
    "artifact.proposal.repair_revision",
    # L5 completion
    "procedure.repair.prescribed.completed",
    "procedure.completed_work.final_inspection_performed",
    "artifact.report.completion",
    "artifact.form.mbi4",
    "artifact.statement.scope_and_order_coverage",
    "artifact.statement.extra_works_separated",
    # L6 statutory + qualifiers
    "fire_safety.upgrade_outstanding",
    "qual.actor_role",
    "qual.method_class",
    "qual.artifact_field_group",
})

# 全集白名单——Round 6 / Round 7 evaluator validate_formula 校验时用.
ALLOWED_INPUTS = ALLOWED_PHYSICAL_INPUTS | ALLOWED_HIDDEN_INPUTS | ALLOWED_SIDECAR_INPUTS


def _sigmoid(x: float) -> float:
    if x >= 0:
        e_neg = math.exp(-x)
        return 1.0 / (1.0 + e_neg)
    e_pos = math.exp(x)
    return e_pos / (1.0 + e_pos)


def _eval_linear(
    bias: float,
    terms: Dict[str, float],
    context: Dict[str, float],
) -> float:
    """bias + sum(coef * context[input_name])，缺失 input 默认 0.0."""
    raw = float(bias)
    for input_name, coef in terms.items():
        raw += float(coef) * float(context.get(input_name, 0.0))
    return raw


def _eval_centered_linear(
    anchor: float,
    intercept_fn,  # callable: anchor → float (logit or log)
    upstream_expected: Dict[str, float],
    terms: Dict[str, float],
    context: Dict[str, float],
) -> float:
    """DEBT-020 Round 6 centered upstream pattern:
        raw = intercept_fn(anchor) + Σ coef_i * (context[i] - upstream_expected[i])
    缺失 input 默认 0.0.
    """
    raw = float(intercept_fn(anchor))
    for input_name, coef in terms.items():
        upstream_val = float(context.get(input_name, 0.0))
        expected = float(upstream_expected.get(input_name, 0.0))
        raw += float(coef) * (upstream_val - expected)
    return raw


def compute_logit(p: float) -> float:
    """logit(p) = log(p / (1-p))，clip 防止 log(0) / log(inf) 溢出."""
    p = max(1e-12, min(1.0 - 1e-12, float(p)))
    return math.log(p / (1.0 - p))


def compute_log_anchor(p: float) -> float:
    """log(p)，clip 防 log(0)（softmax base bias 用）."""
    p = max(1e-12, float(p))
    return math.log(p)


def evaluate_bool_conditional(
    formula: Dict[str, Any],
    context: Dict[str, float],
    rng: random.Random,
) -> bool:
    """spec 06 §11.6 bool slot conditional sampler.

    支持两种 type：
      - "sigmoid_linear": p = sigmoid(bias + Σ coef * input)
      - "centered_sigmoid_linear" (DEBT-020 Round 6):
            p = sigmoid(logit(anchor) + Σ coef * (input - upstream_expected))

    Args:
        formula: 见 module docstring schema.
        context: input_name → numeric value
        rng: deterministic RNG

    Returns:
        bool sample.

    Raises:
        ValueError 如果 formula 结构不识别（caller 应在落 registry 时验证）.
    """
    ftype = formula.get("type")
    if ftype == "sigmoid_linear":
        raw = _eval_linear(formula.get("bias", 0.0), formula.get("terms", {}), context)
    elif ftype == "centered_sigmoid_linear":
        raw = _eval_centered_linear(
            formula.get("anchor", 0.5),
            compute_logit,
            formula.get("upstream_expected", {}),
            formula.get("terms", {}),
            context,
        )
    else:
        raise ValueError(
            f"Bool conditional_formula must be sigmoid_linear or centered_sigmoid_linear, "
            f"got {ftype!r}"
        )
    p = _sigmoid(raw)
    return rng.random() < p


def evaluate_enum_conditional(
    formula: Dict[str, Any],
    context: Dict[str, float],
    rng: random.Random,
) -> str:
    """spec 06 §11.6 enum slot conditional sampler.

    支持两种 type：
      - "softmax_per_class": logit_c = bias_c + Σ coef * input
      - "centered_softmax_per_class" (DEBT-020 Round 6):
            logit_c = log(anchor_c) + Σ coef_c * (input - upstream_expected_c)

    Args:
        formula: 见 module docstring schema.
        context: input_name → numeric value
        rng: deterministic RNG

    Returns:
        sampled class name (一个 enum_values 中的 str).
    """
    ftype = formula.get("type")
    classes = formula.get("classes") or {}
    if not classes:
        raise ValueError(f"{ftype} formula has no classes")
    # logits
    logits: Dict[str, float] = {}
    if ftype == "softmax_per_class":
        for class_name, class_formula in classes.items():
            logits[class_name] = _eval_linear(
                class_formula.get("bias", 0.0),
                class_formula.get("terms", {}),
                context,
            )
    elif ftype == "centered_softmax_per_class":
        for class_name, class_formula in classes.items():
            logits[class_name] = _eval_centered_linear(
                class_formula.get("anchor", 1.0 / max(len(classes), 1)),
                compute_log_anchor,
                class_formula.get("upstream_expected", {}),
                class_formula.get("terms", {}),
                context,
            )
    else:
        raise ValueError(
            f"Enum conditional_formula must be softmax_per_class or "
            f"centered_softmax_per_class, got {ftype!r}"
        )
    # softmax (subtract max for numerical stability)
    max_logit = max(logits.values())
    exp_logits = {c: math.exp(v - max_logit) for c, v in logits.items()}
    total = sum(exp_logits.values())
    probs = {c: e / total for c, e in exp_logits.items()}
    # sample by cumulative
    r = rng.random()
    cumsum = 0.0
    class_names = list(probs.keys())
    for class_name in class_names:
        cumsum += probs[class_name]
        if r < cumsum:
            return class_name
    return class_names[-1]  # numerical edge case fallback


# ---------- Round 6 高阶辅助 (centered upstream 直接调用，不走 dict schema) ----------


def evaluate_centered_bool_conditional(
    *,
    anchor: float,
    upstream_expected: Dict[str, float],
    terms: Dict[str, float],
    context: Dict[str, float],
    rng: random.Random,
) -> bool:
    """DEBT-020 Round 6 §1.1 bool centered upstream sampler:
        p = sigmoid(logit(anchor) + Σ coef * (input - upstream_expected))
    """
    raw = _eval_centered_linear(anchor, compute_logit, upstream_expected, terms, context)
    return rng.random() < _sigmoid(raw)


def evaluate_centered_enum_conditional(
    *,
    classes: Dict[str, Dict[str, Any]],
    context: Dict[str, float],
    rng: random.Random,
) -> str:
    """DEBT-020 Round 6 §1.1 enum centered upstream sampler:
        logit_c = log(anchor_c) + Σ coef * (input - upstream_expected)
    classes: {class_name: {anchor, upstream_expected, terms}}.
    """
    if not classes:
        raise ValueError("centered_enum: classes empty")
    logits: Dict[str, float] = {}
    for class_name, cfg in classes.items():
        logits[class_name] = _eval_centered_linear(
            cfg.get("anchor", 1.0 / len(classes)),
            compute_log_anchor,
            cfg.get("upstream_expected", {}),
            cfg.get("terms", {}),
            context,
        )
    max_logit = max(logits.values())
    exp_logits = {c: math.exp(v - max_logit) for c, v in logits.items()}
    total = sum(exp_logits.values())
    probs = {c: e / total for c, e in exp_logits.items()}
    r = rng.random()
    cumsum = 0.0
    names = list(probs.keys())
    for name in names:
        cumsum += probs[name]
        if r < cumsum:
            return name
    return names[-1]


def expected_marginal_bool(
    formula: Dict[str, Any],
    sample_contexts: list,
) -> float:
    """跨 sample_contexts 计算 E[P(true)]——用于 marginal consistency QA.

    支持 sigmoid_linear / centered_sigmoid_linear 两种 type.

    Args:
        formula: bool conditional formula
        sample_contexts: List[Dict[str, float]] — 一组 fragment context

    Returns:
        平均 P(true) across the population.
    """
    if not sample_contexts:
        return 0.0
    ftype = formula.get("type")
    total_p = 0.0
    for ctx in sample_contexts:
        if ftype == "centered_sigmoid_linear":
            raw = _eval_centered_linear(
                formula.get("anchor", 0.5),
                compute_logit,
                formula.get("upstream_expected", {}),
                formula.get("terms", {}),
                ctx,
            )
        else:
            # default sigmoid_linear
            raw = _eval_linear(formula.get("bias", 0.0), formula.get("terms", {}), ctx)
        total_p += _sigmoid(raw)
    return total_p / len(sample_contexts)


def expected_marginal_enum(
    formula: Dict[str, Any],
    sample_contexts: list,
) -> Dict[str, float]:
    """跨 sample_contexts 计算每 class 的 E[P(class=c)] —— marginal consistency QA.

    支持 softmax_per_class / centered_softmax_per_class 两种 type.
    """
    if not sample_contexts:
        return {}
    classes = formula.get("classes") or {}
    if not classes:
        return {}
    ftype = formula.get("type")
    sums: Dict[str, float] = {c: 0.0 for c in classes}
    for ctx in sample_contexts:
        logits: Dict[str, float] = {}
        for class_name, class_formula in classes.items():
            if ftype == "centered_softmax_per_class":
                logits[class_name] = _eval_centered_linear(
                    class_formula.get("anchor", 1.0 / len(classes)),
                    compute_log_anchor,
                    class_formula.get("upstream_expected", {}),
                    class_formula.get("terms", {}),
                    ctx,
                )
            else:
                # default softmax_per_class
                logits[class_name] = _eval_linear(
                    class_formula.get("bias", 0.0),
                    class_formula.get("terms", {}),
                    ctx,
                )
        max_logit = max(logits.values())
        exp_logits = {c: math.exp(v - max_logit) for c, v in logits.items()}
        total = sum(exp_logits.values())
        for c, e in exp_logits.items():
            sums[c] += e / total
    n = len(sample_contexts)
    return {c: s / n for c, s in sums.items()}


# ---------- formula 结构验证（落 registry 时调用） ----------


def validate_formula(formula: Optional[Dict[str, Any]]) -> None:
    """spec 06 §11.6 conditional_formula schema 验证.

    None / 缺失 → 直接 return（marginal-only fallback 合法）.
    Raises ValueError 如果结构不合法.

    支持 4 种 type：
      - sigmoid_linear / softmax_per_class (legacy, sub-task 3)
      - centered_sigmoid_linear / centered_softmax_per_class (DEBT-020 Round 6)
    """
    if formula is None:
        return
    if not isinstance(formula, dict):
        raise ValueError(f"conditional_formula must be dict or None, got {type(formula).__name__}")
    ftype = formula.get("type")
    if ftype == "sigmoid_linear":
        _validate_linear_block(formula, name="root")
    elif ftype == "centered_sigmoid_linear":
        _validate_centered_block(formula, name="root")
    elif ftype == "softmax_per_class":
        classes = formula.get("classes")
        if not isinstance(classes, dict) or not classes:
            raise ValueError("softmax_per_class.classes must be non-empty dict")
        for class_name, class_block in classes.items():
            if not isinstance(class_name, str):
                raise ValueError(f"class name must be str, got {type(class_name).__name__}")
            _validate_linear_block(class_block, name=f"classes.{class_name}")
    elif ftype == "centered_softmax_per_class":
        classes = formula.get("classes")
        if not isinstance(classes, dict) or not classes:
            raise ValueError("centered_softmax_per_class.classes must be non-empty dict")
        # anchor 加和应 ≈ 1.0
        anchor_sum = 0.0
        for class_name, class_block in classes.items():
            if not isinstance(class_name, str):
                raise ValueError(f"class name must be str, got {type(class_name).__name__}")
            _validate_centered_block(class_block, name=f"classes.{class_name}")
            anchor_sum += float(class_block.get("anchor", 0.0))
        if abs(anchor_sum - 1.0) > 1e-3:
            raise ValueError(
                f"centered_softmax_per_class anchor probabilities must sum to 1.0±0.001, "
                f"got {anchor_sum}"
            )
    else:
        raise ValueError(f"unknown conditional_formula type {ftype!r}")


def _validate_terms_dict(terms: Any, name: str) -> None:
    if not isinstance(terms, dict):
        raise ValueError(f"{name}.terms must be dict, got {type(terms).__name__}")
    for input_name, coef in terms.items():
        if not isinstance(input_name, str):
            raise ValueError(f"{name}.terms key must be str, got {type(input_name).__name__}")
        if input_name not in ALLOWED_INPUTS:
            raise ValueError(
                f"{name}.terms[{input_name!r}] not in ALLOWED_INPUTS whitelist"
                f" — extending whitelist requires spec 06 §11.6 amendment"
            )
        if not isinstance(coef, (int, float)) or isinstance(coef, bool):
            raise ValueError(f"{name}.terms[{input_name!r}] coef must be number, got {type(coef).__name__}")


def _validate_linear_block(block: Any, name: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{name} must be dict, got {type(block).__name__}")
    bias = block.get("bias", 0.0)
    if not isinstance(bias, (int, float)) or isinstance(bias, bool):
        raise ValueError(f"{name}.bias must be number, got {type(bias).__name__}")
    _validate_terms_dict(block.get("terms", {}), name=name)


def _validate_centered_block(block: Any, name: str) -> None:
    """DEBT-020 Round 6 centered upstream block: {anchor, upstream_expected, terms}."""
    if not isinstance(block, dict):
        raise ValueError(f"{name} must be dict, got {type(block).__name__}")
    anchor = block.get("anchor", None)
    if anchor is None:
        raise ValueError(f"{name}.anchor must be set (Round 6 centered formula required)")
    if not isinstance(anchor, (int, float)) or isinstance(anchor, bool):
        raise ValueError(f"{name}.anchor must be number, got {type(anchor).__name__}")
    if not (0.0 < float(anchor) <= 1.0):
        raise ValueError(f"{name}.anchor must be in (0, 1] (probability), got {anchor}")
    upstream_expected = block.get("upstream_expected", {})
    if not isinstance(upstream_expected, dict):
        raise ValueError(f"{name}.upstream_expected must be dict, got {type(upstream_expected).__name__}")
    for input_name, expected in upstream_expected.items():
        if not isinstance(input_name, str):
            raise ValueError(f"{name}.upstream_expected key must be str, got {type(input_name).__name__}")
        if input_name not in ALLOWED_INPUTS:
            raise ValueError(
                f"{name}.upstream_expected[{input_name!r}] not in ALLOWED_INPUTS whitelist"
            )
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            raise ValueError(
                f"{name}.upstream_expected[{input_name!r}] must be number, got {type(expected).__name__}"
            )
    _validate_terms_dict(block.get("terms", {}), name=name)


# ---------- context builder：从 W0 state 构造 evaluator 输入 ----------


def build_evaluator_context(
    *,
    age_years: Optional[float] = None,
    service_load_ratio: Optional[float] = None,
    restraint_level: Optional[float] = None,
    workmanship_deficit: Optional[float] = None,
    maintenance_deficit: Optional[float] = None,
    moisture_ingress_index: Optional[float] = None,
    chloride_exposure: Optional[float] = None,
    crack_severity_index: Optional[float] = None,
    spall_severity_index: Optional[float] = None,
    corrosion_severity_index: Optional[float] = None,
    delamination_severity_index: Optional[float] = None,
    detachment_severity_index: Optional[float] = None,
    drainage_blockage_index: Optional[float] = None,
    drainage_leakage_index: Optional[float] = None,
    public_health_risk_index: Optional[float] = None,
    defect_class_present: Optional[bool] = None,
    ubw_alteration_present: Optional[bool] = None,
    fire_safety_deficiency_present: Optional[bool] = None,
    repair_quality_index: Optional[float] = None,
    fsp_structural_performance: Optional[float] = None,
    building_total_severity_max: Optional[float] = None,
    building_defect_count: Optional[int] = None,
    hidden_state: Optional[Dict[str, float]] = None,
    sidecar_upstream: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """构造 evaluator context dict——所有参数 optional，缺失 → 0.0 (evaluator 默认).

    age_norm 自动 = clip(age_years / 50, 0, 1)；bool → 0/1 float；
    building_defect_count → /20 normalize to building_defect_count_norm.

    DEBT-020 Round 6 扩展：
      - hidden_state: H.* 19 项隐状态（caller 从 W0 generator state 派生）
      - sidecar_upstream: 已采样的 sidecar slot value (slot_id → 0/1/float),
        Round 6 §1.3 sampling_order 顺序由 sidecar.py 维护

    spec 06 §11.6 evaluator 仅消费此函数返回的 keys (即 ALLOWED_INPUTS 子集).
    未在白名单的 hidden_state / sidecar_upstream key 会被静默丢弃（caller 责任).
    """
    ctx: Dict[str, float] = {}
    if age_years is not None:
        ctx["age_norm"] = max(0.0, min(1.0, float(age_years) / 50.0))
    if service_load_ratio is not None:
        ctx["service_load_ratio"] = float(service_load_ratio)
    if restraint_level is not None:
        ctx["restraint_level"] = float(restraint_level)
    if workmanship_deficit is not None:
        ctx["workmanship_deficit"] = float(workmanship_deficit)
    if maintenance_deficit is not None:
        ctx["maintenance_deficit"] = float(maintenance_deficit)
    if moisture_ingress_index is not None:
        ctx["moisture_ingress_index"] = float(moisture_ingress_index)
    if chloride_exposure is not None:
        ctx["chloride_exposure"] = float(chloride_exposure)
    if crack_severity_index is not None:
        ctx["crack_severity_index"] = float(crack_severity_index)
    if spall_severity_index is not None:
        ctx["spall_severity_index"] = float(spall_severity_index)
    if corrosion_severity_index is not None:
        ctx["corrosion_severity_index"] = float(corrosion_severity_index)
    if delamination_severity_index is not None:
        ctx["delamination_severity_index"] = float(delamination_severity_index)
    if detachment_severity_index is not None:
        ctx["detachment_severity_index"] = float(detachment_severity_index)
    if drainage_blockage_index is not None:
        ctx["drainage_blockage_index"] = float(drainage_blockage_index)
    if drainage_leakage_index is not None:
        ctx["drainage_leakage_index"] = float(drainage_leakage_index)
    if public_health_risk_index is not None:
        ctx["public_health_risk_index"] = float(public_health_risk_index)
    if defect_class_present is not None:
        ctx["defect_class_present"] = 1.0 if defect_class_present else 0.0
    if ubw_alteration_present is not None:
        ctx["ubw_alteration_present"] = 1.0 if ubw_alteration_present else 0.0
    if fire_safety_deficiency_present is not None:
        ctx["fire_safety_deficiency_present"] = 1.0 if fire_safety_deficiency_present else 0.0
    if repair_quality_index is not None:
        ctx["repair_quality_index"] = float(repair_quality_index)
    if fsp_structural_performance is not None:
        ctx["fsp_structural_performance"] = float(fsp_structural_performance)
    if building_total_severity_max is not None:
        ctx["building_total_severity_max"] = max(0.0, min(1.0, float(building_total_severity_max)))
    if building_defect_count is not None:
        # /20 normalize as a coarse cap (跨 building 缺陷计数 0-20 是常态)
        ctx["building_defect_count_norm"] = max(0.0, min(1.0, float(building_defect_count) / 20.0))
    # Round 6 §1.2 hidden state H.*
    if hidden_state:
        for key, val in hidden_state.items():
            if key in ALLOWED_HIDDEN_INPUTS:
                ctx[key] = float(val)
    # Round 6 §1.3 已采样 sidecar slot upstream
    if sidecar_upstream:
        for slot_id, val in sidecar_upstream.items():
            if slot_id in ALLOWED_SIDECAR_INPUTS:
                # bool → 0/1, str (enum value) → 1.0 if non-empty else 0.0,
                # caller 自己负责传递 numeric/0-1 view; 这里只强制 cast
                if isinstance(val, bool):
                    ctx[slot_id] = 1.0 if val else 0.0
                elif isinstance(val, (int, float)):
                    ctx[slot_id] = float(val)
                elif isinstance(val, str):
                    # enum slot 当前 upstream 处理：non-empty str → 1.0, empty → 0.0
                    # 公式中按 (val - upstream_expected) 中心化，enum 一般不会被其他 slot 直接引用；
                    # qual.* enum slot 只出现在 qualifier 层（sampling_order 末尾），不作为
                    # 上游被引用，所以此分支保险用
                    ctx[slot_id] = 1.0 if val else 0.0
    return ctx


# ---------- Round 6 §1.2 hidden state H.* default prior means (sidecar.py 派生 fallback) ----------

HIDDEN_STATE_PRIOR_MEANS: Dict[str, float] = {
    "H.case_active": 0.96,
    "H.age_old_score": 0.55,
    "H.admin_discipline_score": 0.65,
    "H.admin_instability_score": 0.25,
    "H.document_maturity_score": 0.60,
    "H.defect_present": 0.72,
    "H.defect_uncertainty": 0.28,
    "H.defect_severity_score": 0.45,
    "H.repair_need": 0.58,
    "H.repair_complexity_score": 0.40,
    "H.contractor_mobilisation_need": 0.50,
    "H.testing_need": 0.44,
    "H.material_replacement_need": 0.43,
    "H.nonconformity_risk": 0.20,
    "H.repair_quality_score": 0.60,
    "H.fire_safety_need": 0.16,
    "H.ubw_extra_work": 0.19,
    "H.drainage_issue": 0.18,
    "H.fire_door_issue": 0.05,
}
