"""evaluator metrics（spec §8.4.1 ~ §8.4.4）。

把 agent 侧聚合产物（`AgentFamilyVerdict` + 原始 `Obligation`）与 W2 参考真值
（`TruthBundle`）对齐，算各项指标：

- §8.4.1 verdict metrics      —— expected_verdict_accuracy / pass_fail_macro_f1 /
                                 unknown_recall / not_applicable_accuracy /
                                 severity_weighted_accuracy
- §8.4.2 family / rule coverage —— family_recall / family_precision /
                                 rule_card_recall_proxy / slot_requirement_recall
- §8.4.3 threshold metrics    —— operator / value / observed / pass_bool / unit match
- §8.4.4 closure metrics      —— allow_stop precision/recall / open_when_reference_unknown /
                                 blocked_rate_by_reason / closed_violated_detection_rate

对齐粒度：W2 真值是 coarse family 粒度（`projections.projection_family`），
agent verdict 经 §8.3.2 crosswalk 升到 coarse family，再按
`(world_id, fragment_id, coarse_family)` 对齐。

§8.4.5 leakage 不在本模块——见 leakage_audit.py。

spec→code 单向：指标定义照 spec §8.4 表格，不自创指标。
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from evo_agent_baseline.contracts import ClosureValidationResult, Obligation
from evo_agent_baseline.eval.mapper import AgentFamilyVerdict
from evo_agent_baseline.eval.truth_loader import TruthBundle

# 数值容差比较的默认相对/绝对容差（spec §8.4.3 observed_value_tolerance_match
# "numeric tolerance 或 exact"；spec 未给定数值，取保守小容差）。
DEFAULT_NUMERIC_REL_TOL = 1e-6
DEFAULT_NUMERIC_ABS_TOL = 1e-9


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _safe_ratio(numer: float, denom: float) -> Optional[float]:
    """分母为 0 时返回 None（该指标不可算），否则返回比值。"""
    if denom == 0:
        return None
    return numer / denom


def _coarse_truth_verdict_map(truth: TruthBundle) -> Dict[Tuple[str, str, str], str]:
    """W2 真值：`(world_id, fragment_id, coarse_family)` → expected_verdict。

    `projections` 含 world_id / fragment_id / projection_family / expected_verdict。
    """
    proj = truth.projections
    needed = {"world_id", "fragment_id", "projection_family", "expected_verdict"}
    if not needed.issubset(proj.columns):
        return {}
    out: Dict[Tuple[str, str, str], str] = {}
    for _, row in proj[list(needed)].iterrows():
        wid, fid, fam, verdict = (
            row["world_id"],
            row["fragment_id"],
            row["projection_family"],
            row["expected_verdict"],
        )
        if isinstance(wid, str) and isinstance(fam, str) and isinstance(verdict, str):
            out[(wid, fid, fam)] = verdict
    return out


def _coarse_truth_severity_map(truth: TruthBundle) -> Dict[Tuple[str, str, str], str]:
    """W2 真值：`(world_id, fragment_id, coarse_family)` → severity_band。"""
    proj = truth.projections
    needed = {"world_id", "fragment_id", "projection_family", "severity_band"}
    if not needed.issubset(proj.columns):
        return {}
    out: Dict[Tuple[str, str, str], str] = {}
    for _, row in proj[list(needed)].iterrows():
        wid, fid, fam, sev = (
            row["world_id"],
            row["fragment_id"],
            row["projection_family"],
            row["severity_band"],
        )
        if isinstance(wid, str) and isinstance(fam, str):
            out[(wid, fid, fam)] = sev if isinstance(sev, str) else ""
    return out


# W2 expected_verdict 取值 → 与 agent family verdict 对齐用的归一化。
# W2 真值取值观察到 "fail"；spec §8.4 也提及 pass / unknown / not_applicable。
# agent verdict 取值见 mapper.FAMILY_VERDICT_VALUES。二者用同一词表直接 exact match。
def _normalize_verdict(v: Optional[str]) -> str:
    """verdict 归一化为小写裸字符串（容忍 None / 大小写差异）。"""
    if not isinstance(v, str):
        return ""
    return v.strip().lower()


# ---------------------------------------------------------------------------
# §8.4.1 verdict metrics
# ---------------------------------------------------------------------------


@dataclass
class VerdictMetrics:
    """spec §8.4.1 verdict metrics 结果。"""

    expected_verdict_accuracy: Optional[float]
    pass_fail_macro_f1: Optional[float]
    unknown_recall: Optional[float]
    not_applicable_accuracy: Optional[float]
    severity_weighted_accuracy: Optional[float]
    compared_pairs: int
    # 仅诊断：(agent_verdict, truth_verdict) 计数。
    confusion: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "expected_verdict_accuracy": self.expected_verdict_accuracy,
            "pass_fail_macro_f1": self.pass_fail_macro_f1,
            "unknown_recall": self.unknown_recall,
            "not_applicable_accuracy": self.not_applicable_accuracy,
            "severity_weighted_accuracy": self.severity_weighted_accuracy,
            "compared_pairs": self.compared_pairs,
            "confusion": self.confusion,
        }


def _macro_f1_pass_fail(pairs: List[Tuple[str, str]]) -> Optional[float]:
    """只在 pass/fail 子集上算 macro F1（spec §8.4.1 pass_fail_macro_f1）。

    pairs: (agent_verdict, truth_verdict)；只保留 truth ∈ {pass, fail} 的对。
    每个类（pass / fail）算 F1 再取宏平均。
    """
    subset = [
        (a, t) for a, t in pairs if t in {"pass", "fail"}
    ]
    if not subset:
        return None
    f1s: List[float] = []
    for cls in ("pass", "fail"):
        tp = sum(1 for a, t in subset if a == cls and t == cls)
        fp = sum(1 for a, t in subset if a == cls and t != cls)
        fn = sum(1 for a, t in subset if a != cls and t == cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        f1s.append(f1)
    return sum(f1s) / len(f1s)


def compute_verdict_metrics(
    agent_verdicts: Iterable[AgentFamilyVerdict],
    truth: TruthBundle,
) -> VerdictMetrics:
    """spec §8.4.1 —— agent family verdict vs W2 expected_verdict。

    对齐键 `(world_id, fragment_id, coarse_family)`；agent 侧用映射出的
    `coarse_family_id`（None 即未登记 crosswalk，跳过该 family，不计入分母）。
    """
    truth_verdict = _coarse_truth_verdict_map(truth)
    truth_severity = _coarse_truth_severity_map(truth)

    # severity_band → 权重（spec §8.4.1 severity_weighted_accuracy "按 severity_band
    # 加权"；spec 未给定权重，取按危险递增的整数权重，缺失/未知记 1）。
    severity_weight = {
        "minor": 1.0,
        "moderate": 2.0,
        "severe": 3.0,
        "emergency": 4.0,
    }

    pairs: List[Tuple[str, str]] = []
    confusion: Counter = Counter()
    weighted_hit = 0.0
    weighted_total = 0.0

    # fine→coarse 归约后再对齐（DEBT-046 修正②）：同一 (world, fragment, coarse) 的
    # 多个 fine 族 verdict 先按 lattice 归约成一个，再与 truth 比一次。否则 fine 切片
    # 的局部 pass 会被单独拿去跟 coarse 整族 truth 比，产生虚假 pass->fail
    # （实测 30 栋 13 例全属此类：如 investigation.*.method 切片 8 义务全 satisfied
    # 判 pass，coarse 整族里其它切片仍 unknown）。
    grouped: Dict[Tuple[str, Optional[str], str], List[str]] = {}
    for av in agent_verdicts:
        if av.coarse_family_id is None:
            continue
        key = (av.world_id, av.fragment_id, av.coarse_family_id)
        if key not in truth_verdict:
            continue
        grouped.setdefault(key, []).append(av.verdict)

    for key in sorted(grouped, key=lambda k: (k[0], k[1] or "", k[2])):
        a = _reduce_verdicts_lattice(grouped[key])
        if not a:
            continue
        t = _normalize_verdict(truth_verdict[key])
        pairs.append((a, t))
        confusion[f"{a}->{t}"] += 1
        w = severity_weight.get(truth_severity.get(key, ""), 1.0)
        weighted_total += w
        if a == t:
            weighted_hit += w

    n = len(pairs)
    exact_acc = _safe_ratio(sum(1 for a, t in pairs if a == t), n)

    macro_f1 = _macro_f1_pass_fail(pairs)

    # unknown_recall：W2 unknown 中被 agent 也判 unknown 的比例。
    unknown_truth = [(a, t) for a, t in pairs if t == "unknown"]
    unknown_recall = _safe_ratio(
        sum(1 for a, t in unknown_truth if a == "unknown"), len(unknown_truth)
    )

    # not_applicable_accuracy：W2 not_applicable 上的 exact match。
    na_truth = [(a, t) for a, t in pairs if t == "not_applicable"]
    na_acc = _safe_ratio(
        sum(1 for a, t in na_truth if a == t), len(na_truth)
    )

    severity_weighted = _safe_ratio(weighted_hit, weighted_total)

    return VerdictMetrics(
        expected_verdict_accuracy=exact_acc,
        pass_fail_macro_f1=macro_f1,
        unknown_recall=unknown_recall,
        not_applicable_accuracy=na_acc,
        severity_weighted_accuracy=severity_weighted,
        compared_pairs=n,
        confusion=dict(confusion),
    )


# ---------------------------------------------------------------------------
# DEBT-046 楼级对齐口径（过渡期主对齐层，用户 2026-07-02 拍板）
#
# 背景：agent 义务 `fragment_id` 当前从不填（spec 假设归属存在但未定义注入规则），
# §8.4.1 的 fragment 级精确对齐 compared_pairs 结构性为 0。过渡期把 truth 按
# `(world_id, coarse_family)` 聚合到楼级、与 agent 楼级 verdict 对齐——**双侧用
# 同一 verdict lattice 归约**（unknown 优先 → 任一 fail → 全 pass/na 细分），保证
# apples-to-apples；不用"族唯一性"当等价论证（codex 评审证伪了那条：agent 楼级
# verdict 聚合的义务宇宙 ≠ truth 单 fragment 的义务宇宙）。
# 本节为纯补充层：§8.4.1 fragment 级口径原样保留（将来闭包侧归属落地后回归主口径）。
# ---------------------------------------------------------------------------


def _reduce_verdicts_lattice(verdicts: Iterable[str]) -> str:
    """与 mapper §8.3.1 同序的 verdict 字符串归约（楼级聚合双侧共用）。

    unknown 优先（有任何判不了 → 楼级判不了）→ 任一 fail 为 fail →
    全 not_applicable 为 not_applicable → 否则 pass（pass 与 na 混合视作 pass：
    存在适用且通过的实例）。空输入返回 ""（调用方跳过）。
    """
    vs = [_normalize_verdict(v) for v in verdicts]
    vs = [v for v in vs if v]
    if not vs:
        return ""
    if any(v == "unknown" for v in vs):
        return "unknown"
    if any(v == "fail" for v in vs):
        return "fail"
    if all(v == "not_applicable" for v in vs):
        return "not_applicable"
    return "pass"


def _building_truth_verdict_map(truth: TruthBundle) -> Dict[Tuple[str, str], str]:
    """truth 逐 fragment verdict 聚合到楼级：`(world_id, coarse_family)` → verdict。"""
    per_fragment = _coarse_truth_verdict_map(truth)
    groups: Dict[Tuple[str, str], List[str]] = {}
    for (wid, _fid, fam), v in per_fragment.items():
        groups.setdefault((wid, fam), []).append(v)
    return {k: _reduce_verdicts_lattice(vs) for k, vs in groups.items()}


def _truth_family_fragment_counts(truth: TruthBundle) -> Dict[Tuple[str, str], int]:
    """`(world_id, coarse_family)` → truth 里该族 distinct fragment 数（对齐诊断用）。"""
    per_fragment = _coarse_truth_verdict_map(truth)
    frags: Dict[Tuple[str, str], set] = {}
    for (wid, fid, fam) in per_fragment:
        frags.setdefault((wid, fam), set()).add(fid)
    return {k: len(v) for k, v in frags.items()}


def aggregate_agent_building_verdicts(
    agent_verdicts: Iterable[AgentFamilyVerdict],
) -> Dict[Tuple[str, str], str]:
    """agent family verdict 聚合到楼级：`(world_id, coarse_family)` → verdict。

    跨 fine family / 跨 fragment（将来归属落地后）用同一 lattice 归约；
    coarse 未登记（crosswalk 缺）跳过，与 §8.4.1 口径一致。
    """
    groups: Dict[Tuple[str, str], List[str]] = {}
    for av in agent_verdicts:
        if av.coarse_family_id is None:
            continue
        groups.setdefault((av.world_id, av.coarse_family_id), []).append(av.verdict)
    return {k: _reduce_verdicts_lattice(vs) for k, vs in groups.items()}


def compute_building_verdict_metrics(
    agent_verdicts: Iterable[AgentFamilyVerdict],
    truth: TruthBundle,
) -> VerdictMetrics:
    """楼级对齐口径的 verdict metrics（结构复用 VerdictMetrics）。

    severity 权重取该 `(world, family)` 下各 fragment severity 的最大权重（保守）。
    """
    truth_building = _building_truth_verdict_map(truth)
    truth_severity = _coarse_truth_severity_map(truth)
    severity_weight = {
        "minor": 1.0,
        "moderate": 2.0,
        "severe": 3.0,
        "emergency": 4.0,
    }
    building_weight: Dict[Tuple[str, str], float] = {}
    for (wid, _fid, fam), sev in truth_severity.items():
        w = severity_weight.get(sev, 1.0)
        key = (wid, fam)
        building_weight[key] = max(building_weight.get(key, 1.0), w)

    agent_building = aggregate_agent_building_verdicts(agent_verdicts)

    pairs: List[Tuple[str, str]] = []
    confusion: Counter = Counter()
    weighted_hit = 0.0
    weighted_total = 0.0
    for key, a in agent_building.items():
        if key not in truth_building or not a:
            continue
        t = truth_building[key]
        if not t:
            continue
        pairs.append((a, t))
        confusion[f"{a}->{t}"] += 1
        w = building_weight.get(key, 1.0)
        weighted_total += w
        if a == t:
            weighted_hit += w

    n = len(pairs)
    unknown_truth = [(a, t) for a, t in pairs if t == "unknown"]
    na_truth = [(a, t) for a, t in pairs if t == "not_applicable"]
    return VerdictMetrics(
        expected_verdict_accuracy=_safe_ratio(
            sum(1 for a, t in pairs if a == t), n
        ),
        pass_fail_macro_f1=_macro_f1_pass_fail(pairs),
        unknown_recall=_safe_ratio(
            sum(1 for a, t in unknown_truth if a == "unknown"), len(unknown_truth)
        ),
        not_applicable_accuracy=_safe_ratio(
            sum(1 for a, t in na_truth if a == t), len(na_truth)
        ),
        severity_weighted_accuracy=_safe_ratio(weighted_hit, weighted_total),
        compared_pairs=n,
        confusion=dict(confusion),
    )


def compute_alignment_diagnostics(
    agent_verdicts: Iterable[AgentFamilyVerdict],
    truth: TruthBundle,
) -> Dict[str, Any]:
    """对齐分层诊断（不作主指标）：族唯一回退（N2）与歧义排除（N3）计数。

    N2 = agent 楼级 coarse verdict 里，truth 该族在该楼恰好 1 个 fragment（可无歧义
    回退对齐）的 pairs；N3 = truth 该族多 fragment（回退有歧义、不比）的 pairs。
    注意 N2 只是诊断——codex 评审指出楼级 verdict 与单 fragment 真值的义务宇宙不同，
    N2 不当等价主口径；且被 N3 排除的楼族构成有偏（非随机样本）。
    """
    counts = _truth_family_fragment_counts(truth)
    per_fragment_truth = _coarse_truth_verdict_map(truth)
    agent_building = aggregate_agent_building_verdicts(agent_verdicts)

    n2 = 0
    n3 = 0
    fallback_confusion: Counter = Counter()
    for (wid, fam), a in agent_building.items():
        c = counts.get((wid, fam))
        if not c or not a:
            continue
        if c == 1:
            n2 += 1
            t = ""
            for (twid, _fid, tfam), v in per_fragment_truth.items():
                if twid == wid and tfam == fam:
                    t = _normalize_verdict(v)
                    break
            if t:
                fallback_confusion[f"{a}->{t}"] += 1
        else:
            n3 += 1
    return {
        "family_unique_fallback_pairs": n2,
        "ambiguous_excluded_pairs": n3,
        "family_unique_fallback_confusion": dict(fallback_confusion),
    }


# ---------------------------------------------------------------------------
# §8.4.2 family / rule coverage
# ---------------------------------------------------------------------------


@dataclass
class CoverageMetrics:
    """spec §8.4.2 family / rule coverage 结果。"""

    family_recall: Optional[float]
    family_precision: Optional[float]
    rule_card_recall_proxy: Optional[float]
    slot_requirement_recall: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "family_recall": self.family_recall,
            "family_precision": self.family_precision,
            "rule_card_recall_proxy": self.rule_card_recall_proxy,
            "slot_requirement_recall": self.slot_requirement_recall,
        }


def _flatten_list_cell(cell: Any) -> List[str]:
    """parquet list-列单元格 → str 列表（容忍 None / numpy array / list）。"""
    if cell is None:
        return []
    try:
        items = list(cell)
    except TypeError:
        return []
    return [x for x in items if isinstance(x, str)]


def compute_coverage_metrics(
    agent_verdicts: Iterable[AgentFamilyVerdict],
    obligations: Iterable[Obligation],
    retrieved_rule_card_ids: Iterable[str],
    truth: TruthBundle,
) -> CoverageMetrics:
    """spec §8.4.2 —— family / rule / slot 覆盖。

    Args:
        agent_verdicts: agent 侧 family 聚合（已带 coarse_family_id）。
        obligations: agent 全部义务（取 slot_ids 算 slot 覆盖）。
        retrieved_rule_card_ids: agent 检索到的 rule_card_id 集合
            （来自 run_audit / retrieval_summary）。
        truth: W2 参考真值。
    """
    agent_list = list(agent_verdicts)
    obs_list = list(obligations)

    # ---- family recall / precision ----
    # W2 selected/matched family（coarse 粒度）：matched_families.family_id。
    truth_families: set = set()
    mf = truth.matched_families
    if "family_id" in mf.columns:
        truth_families = {
            f for f in mf["family_id"].tolist() if isinstance(f, str)
        }
    agent_coarse: set = {
        av.coarse_family_id for av in agent_list if av.coarse_family_id is not None
    }
    if truth_families:
        family_recall = _safe_ratio(
            len(agent_coarse & truth_families), len(truth_families)
        )
    else:
        family_recall = None
    if agent_coarse:
        family_precision = _safe_ratio(
            len(agent_coarse & truth_families), len(agent_coarse)
        )
    else:
        family_precision = None

    # ---- rule_card_recall_proxy ----
    # W2 matched rule_ids（matched_families.rule_ids）与 agent retrieved
    # rule_card_ids 的 overlap / W2 rule_ids 总数。
    w2_rule_ids: set = set()
    if "rule_ids" in mf.columns:
        for cell in mf["rule_ids"].tolist():
            w2_rule_ids.update(_flatten_list_cell(cell))
    agent_rule_ids = {r for r in retrieved_rule_card_ids if isinstance(r, str)}
    if w2_rule_ids:
        rule_recall = _safe_ratio(
            len(agent_rule_ids & w2_rule_ids), len(w2_rule_ids)
        )
    else:
        rule_recall = None

    # ---- slot_requirement_recall ----
    # W2 required_slots（projections.required_slots，coarse 粒度）被 agent
    # obligations 的 slot_ids 覆盖的比例。
    w2_required_slots: set = set()
    proj = truth.projections
    if "required_slots" in proj.columns:
        for cell in proj["required_slots"].tolist():
            w2_required_slots.update(_flatten_list_cell(cell))
    agent_slot_ids: set = set()
    for ob in obs_list:
        agent_slot_ids.update(ob.slot_ids)
        agent_slot_ids.update(ob.slot_ref_ids)
        # 口径修正 2026-06-11（依据 DEBT 下钻报告 杂物箱/slot_recall_drilldown.md
        # §二/§六 修1，主代理裁决 J9）：threshold 义务的 slot 身份记在
        # measure_keys（closure/obligation_deriver.py::evaluate_threshold 只写
        # measure_keys 不写 slot_ids），旧口径只数 slot_ids∪slot_ref_ids 导致
        # measurement 类真值 slot 结构性必丢（实测 3 栋楼 measurement 命中 0/43）。
        # 分子并入 measure_keys；历史跑批指标不回填。
        agent_slot_ids.update(ob.measure_keys)
    if w2_required_slots:
        slot_recall = _safe_ratio(
            len(agent_slot_ids & w2_required_slots), len(w2_required_slots)
        )
    else:
        slot_recall = None

    return CoverageMetrics(
        family_recall=family_recall,
        family_precision=family_precision,
        rule_card_recall_proxy=rule_recall,
        slot_requirement_recall=slot_recall,
    )


# ---------------------------------------------------------------------------
# §8.4.3 threshold metrics
# ---------------------------------------------------------------------------


@dataclass
class ThresholdMetrics:
    """spec §8.4.3 threshold metrics 结果。"""

    threshold_operator_match: Optional[float]
    threshold_value_match: Optional[float]
    observed_value_tolerance_match: Optional[float]
    threshold_pass_bool_match: Optional[float]
    unit_match: Optional[float]
    compared_pairs: int
    threshold_operator_hits: int
    threshold_operator_compared: int
    threshold_value_hits: int
    threshold_value_compared: int
    observed_value_hits: int
    observed_value_compared: int
    threshold_pass_bool_hits: int
    threshold_pass_bool_compared: int
    unit_hits: int
    unit_compared: int
    threshold_obligations: int
    threshold_obligations_missing_regime: int
    threshold_instance_pairs_unaligned: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "threshold_operator_match": self.threshold_operator_match,
            "threshold_value_match": self.threshold_value_match,
            "observed_value_tolerance_match": self.observed_value_tolerance_match,
            "threshold_pass_bool_match": self.threshold_pass_bool_match,
            "unit_match": self.unit_match,
            # codex 审查修正：此前键名 compared_pairs 与 VerdictMetrics 撞键，report.py
            # 平铺合并时把 verdict 的 N1 分母覆盖成 threshold 的 0——拆名根治。
            "threshold_compared_pairs": self.compared_pairs,
            "threshold_operator_hits": self.threshold_operator_hits,
            "threshold_operator_compared": self.threshold_operator_compared,
            "threshold_value_hits": self.threshold_value_hits,
            "threshold_value_compared": self.threshold_value_compared,
            "observed_value_hits": self.observed_value_hits,
            "observed_value_compared": self.observed_value_compared,
            "threshold_pass_bool_hits": self.threshold_pass_bool_hits,
            "threshold_pass_bool_compared": self.threshold_pass_bool_compared,
            "unit_hits": self.unit_hits,
            "unit_compared": self.unit_compared,
            "threshold_obligations": self.threshold_obligations,
            "threshold_obligations_missing_regime": self.threshold_obligations_missing_regime,
            "threshold_instance_pairs_unaligned": self.threshold_instance_pairs_unaligned,
        }


def _canonical_json(value_json: Optional[str]) -> Optional[str]:
    """把 JSON 字符串 canonical 化（排序键、去空白），用于 exact 比较。

    无法解析则原样返回（保留为字符串比较的回退）。
    """
    if value_json is None:
        return None
    if not isinstance(value_json, str):
        return json.dumps(value_json, sort_keys=True, separators=(",", ":"))
    try:
        return json.dumps(
            json.loads(value_json), sort_keys=True, separators=(",", ":")
        )
    except (json.JSONDecodeError, TypeError):
        return value_json.strip()


def _as_number(value_json: Optional[str]) -> Optional[float]:
    """尝试把 (JSON) 值解析为 float；非数值返回 None。"""
    if value_json is None:
        return None
    raw: Any = value_json
    if isinstance(value_json, str):
        try:
            raw = json.loads(value_json)
        except (json.JSONDecodeError, TypeError):
            try:
                raw = float(value_json)
            except ValueError:
                return None
    if isinstance(raw, bool):  # bool 是 int 子类，排除掉
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _numeric_or_exact_match(
    agent_json: Optional[str],
    truth_json: Optional[str],
    rel_tol: float = DEFAULT_NUMERIC_REL_TOL,
    abs_tol: float = DEFAULT_NUMERIC_ABS_TOL,
) -> bool:
    """spec §8.4.3 observed_value_tolerance_match —— numeric tolerance 或 exact。"""
    a_num = _as_number(agent_json)
    t_num = _as_number(truth_json)
    if a_num is not None and t_num is not None:
        return math.isclose(a_num, t_num, rel_tol=rel_tol, abs_tol=abs_tol)
    return _canonical_json(agent_json) == _canonical_json(truth_json)


def compute_threshold_metrics(
    obligations: Iterable[Obligation],
    truth: TruthBundle,
    threshold_regime_by_obligation_id: Optional[Dict[str, str]] = None,
) -> ThresholdMetrics:
    """spec §8.4.3 —— agent threshold obligations vs W2 threshold_evaluations。

    value/operator/unit 按 `(rule_id, threshold_regime_id, slot_id)` 对齐；
    observed/pass 再加入 projection_id，避免跨实例取值。closure 侧 regime 来自
    identity-v5 manifest 的显式映射；缺失时排除并计入 coverage 诊断。
    """
    th = truth.threshold_evaluations
    th_cols = set(th.columns)

    def normalized(value: Any) -> Any:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return value

    def add_unique(
        index: Dict[Tuple[str, ...], Dict[str, Any]],
        signatures: Dict[Tuple[str, ...], Tuple[Any, ...]],
        key: Tuple[str, ...],
        row: Dict[str, Any],
        signature: Tuple[Any, ...],
        label: str,
    ) -> None:
        previous = signatures.get(key)
        if previous is not None and previous != signature:
            raise ValueError(
                f"conflicting threshold truth rows for {label} key={key!r}: "
                f"{previous!r} != {signature!r}"
            )
        if previous is None:
            signatures[key] = signature
            index[key] = row

    # regime 级索引只审计静态阈值签名；同制度跨 projection 的实例值允许不同。
    truth_idx: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    truth_signatures: Dict[Tuple[str, ...], Tuple[Any, ...]] = {}
    instance_idx: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    instance_signatures: Dict[Tuple[str, ...], Tuple[Any, ...]] = {}
    ambiguous_instance_keys: set[Tuple[str, ...]] = set()
    required = {"rule_id", "threshold_regime_id", "slot_id"}
    if required.issubset(th_cols):
        for _, row in th.iterrows():
            item = row.to_dict()
            rid = item.get("rule_id")
            regime = item.get("threshold_regime_id")
            sid = item.get("slot_id")
            if not all(isinstance(x, str) and x for x in (rid, regime, sid)):
                continue
            key = (rid, regime, sid)
            static_signature = (
                normalized(item.get("operator")),
                _canonical_json(normalized(item.get("threshold_value_json"))),
                normalized(item.get("unit")),
            )
            add_unique(truth_idx, truth_signatures, key, item, static_signature, "regime")
            projection_id = item.get("projection_id")
            if isinstance(projection_id, str) and projection_id:
                instance_key = (projection_id, *key)
                instance_signature = static_signature + (
                    _canonical_json(normalized(item.get("observed_value_json"))),
                    normalized(item.get("pass_bool")),
                )
                if instance_key not in ambiguous_instance_keys:
                    previous = instance_signatures.get(instance_key)
                    if previous is None:
                        instance_signatures[instance_key] = instance_signature
                        instance_idx[instance_key] = item
                    elif previous != instance_signature:
                        # 同 projection 仍有多个实例值时无法唯一回连 closure，显式排除；
                        # 不把合法的实例变化误判成制度静态签名冲突，也不任选一行。
                        ambiguous_instance_keys.add(instance_key)
                        instance_idx.pop(instance_key, None)

    projection_by_scope: Dict[Tuple[str, str], str] = {}
    proj = truth.projections
    if {"world_id", "fragment_id", "projection_id"}.issubset(proj.columns):
        for _, row in proj.iterrows():
            world_id, fragment_id, projection_id = (
                row.get("world_id"), row.get("fragment_id"), row.get("projection_id")
            )
            if not all(isinstance(x, str) and x for x in (world_id, fragment_id, projection_id)):
                continue
            scope_key = (world_id, fragment_id)
            previous = projection_by_scope.get(scope_key)
            if previous is not None and previous != projection_id:
                raise ValueError(
                    f"conflicting projection mapping for scope={scope_key!r}: "
                    f"{previous!r} != {projection_id!r}"
                )
            projection_by_scope[scope_key] = projection_id

    op_hit = op_total = 0
    val_hit = val_total = 0
    obs_hit = obs_total = 0
    pass_hit = pass_total = 0
    unit_hit = unit_total = 0
    compared = 0
    threshold_obligations = 0
    missing_regime = 0
    missing_projection = 0
    regime_map = threshold_regime_by_obligation_id or {}

    for ob in obligations:
        if ob.kind != "threshold":
            continue
        threshold_obligations += 1
        regime = regime_map.get(ob.obligation_id)
        if not isinstance(regime, str) or not regime:
            missing_regime += 1
            continue
        rid = ob.source_rule_card_id
        # threshold 义务的 slot 身份记在 measure_keys（本文件上方注已明写、循环
        # 此前只读 slot_ids——第十一例"登记了没接线"，配对恒 0）；真值侧
        # threshold_evaluations.slot_id 即 measure 键词形，优先按它对齐。
        slot_candidates = (
            ob.measure_keys or ob.slot_ids or ob.slot_ref_ids or [None]
        )
        for sid in slot_candidates:
            if sid is None:
                continue
            tr = truth_idx.get((rid, regime, sid))
            if tr is None:
                continue
            compared += 1

            # operator
            if ob.operator is not None and tr.get("operator") is not None:
                op_total += 1
                if ob.operator == tr.get("operator"):
                    op_hit += 1

            # threshold value（canonical JSON exact）
            a_thr = ob.threshold_value_json
            t_thr = tr.get("threshold_value_json")
            if a_thr is not None and t_thr is not None:
                val_total += 1
                if _canonical_json(a_thr) == _canonical_json(t_thr):
                    val_hit += 1

            # observed/pass 是实例属性；没有唯一 projection 时不回退到制度粗键。
            projection_id = projection_by_scope.get((ob.world_id, ob.fragment_id or ""))
            instance_tr = (
                instance_idx.get((projection_id, rid, regime, sid))
                if projection_id is not None else None
            )
            if instance_tr is None and (
                ob.observed_value_json is not None or ob.comparator_result is not None
            ):
                missing_projection += 1

            # observed value（numeric tolerance 或 exact）
            a_obs = ob.observed_value_json
            t_obs = instance_tr.get("observed_value_json") if instance_tr else None
            if a_obs is not None and t_obs is not None:
                obs_total += 1
                if _numeric_or_exact_match(a_obs, t_obs):
                    obs_hit += 1

            # pass bool（agent comparator_result vs W2 pass_bool）
            a_pass = ob.comparator_result
            t_pass = instance_tr.get("pass_bool") if instance_tr else None
            if a_pass is not None and t_pass is not None:
                pass_total += 1
                if bool(a_pass) == bool(t_pass):
                    pass_hit += 1

            # unit（W2 threshold_evaluations 无 unit 列；用 basis_items 的 unit
            # 时再扩展。这里若 agent 有 unit 但真值无对应列，不计入分母）。
            t_unit = tr.get("unit")
            if ob.unit is not None and t_unit is not None:
                unit_total += 1
                if str(ob.unit).strip() == str(t_unit).strip():
                    unit_hit += 1

    return ThresholdMetrics(
        threshold_operator_match=_safe_ratio(op_hit, op_total),
        threshold_value_match=_safe_ratio(val_hit, val_total),
        observed_value_tolerance_match=_safe_ratio(obs_hit, obs_total),
        threshold_pass_bool_match=_safe_ratio(pass_hit, pass_total),
        unit_match=_safe_ratio(unit_hit, unit_total),
        compared_pairs=compared,
        threshold_operator_hits=op_hit,
        threshold_operator_compared=op_total,
        threshold_value_hits=val_hit,
        threshold_value_compared=val_total,
        observed_value_hits=obs_hit,
        observed_value_compared=obs_total,
        threshold_pass_bool_hits=pass_hit,
        threshold_pass_bool_compared=pass_total,
        unit_hits=unit_hit,
        unit_compared=unit_total,
        threshold_obligations=threshold_obligations,
        threshold_obligations_missing_regime=missing_regime,
        threshold_instance_pairs_unaligned=missing_projection,
    )


# ---------------------------------------------------------------------------
# §8.4.4 closure metrics
# ---------------------------------------------------------------------------


@dataclass
class ClosureMetrics:
    """spec §8.4.4 closure metrics 结果。"""

    allow_stop_precision: Optional[float]
    allow_stop_recall: Optional[float]
    open_when_reference_unknown_rate: Optional[float]
    blocked_rate_by_reason: Dict[str, float]
    closed_violated_detection_rate: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allow_stop_precision": self.allow_stop_precision,
            "allow_stop_recall": self.allow_stop_recall,
            "open_when_reference_unknown_rate": self.open_when_reference_unknown_rate,
            "blocked_rate_by_reason": self.blocked_rate_by_reason,
            "closed_violated_detection_rate": self.closed_violated_detection_rate,
        }


def compute_closure_metrics(
    closure_result: ClosureValidationResult,
    agent_verdicts: Iterable[AgentFamilyVerdict],
    truth: TruthBundle,
) -> ClosureMetrics:
    """spec §8.4.4 —— allow_stop / open-blocked 行为 vs W2 真值。

    Args:
        closure_result: agent 的 `ClosureValidationResult`（一次 run 整体）。
        agent_verdicts: agent family 聚合（用于按 family 比对 open/blocked）。
        truth: W2 参考真值。
    """
    av_list = list(agent_verdicts)
    truth_verdict = _coarse_truth_verdict_map(truth)

    # W2 该 run 是否"可评估"（有 pass/fail/not_applicable verdict）。
    evaluable_verdicts = {"pass", "fail", "not_applicable"}
    w2_evaluable_keys = {
        k for k, v in truth_verdict.items() if _normalize_verdict(v) in evaluable_verdicts
    }
    w2_unknown_keys = {
        k for k, v in truth_verdict.items() if _normalize_verdict(v) == "unknown"
    }
    has_w2_evaluable = len(w2_evaluable_keys) > 0

    summary = closure_result.closure_summary
    agent_allow_stop = bool(closure_result.allow_stop)
    agent_no_open_blocked = (summary.open_count == 0 and summary.blocked_count == 0)

    # allow_stop_precision：allow_stop=true 时是否 W2 可评估且 agent 无 open/blocked。
    # 单 run 粒度——分母是"agent allow_stop=true"事件数（0 或 1）。
    if agent_allow_stop:
        precision_hit = 1.0 if (has_w2_evaluable and agent_no_open_blocked) else 0.0
        allow_stop_precision: Optional[float] = precision_hit
    else:
        allow_stop_precision = None  # 本 run 没触发 allow_stop，不计 precision

    # allow_stop_recall：W2 pass/fail/not_applicable 中 agent allow_stop=true 比例。
    if has_w2_evaluable:
        allow_stop_recall: Optional[float] = 1.0 if agent_allow_stop else 0.0
    else:
        allow_stop_recall = None

    # open_when_reference_unknown_rate：W2 unknown 时 agent open/blocked 的比例。
    # 按 family 粒度算：W2 unknown 的 (w,f,coarse) 中，agent 同 family 判 unknown
    # （即含 open/blocked 义务）的比例。
    if w2_unknown_keys:
        agent_unknown_keys = {
            (av.world_id, av.fragment_id, av.coarse_family_id)
            for av in av_list
            if av.coarse_family_id is not None and av.verdict == "unknown"
        }
        open_when_unknown = _safe_ratio(
            len(w2_unknown_keys & agent_unknown_keys), len(w2_unknown_keys)
        )
    else:
        open_when_unknown = None

    # blocked_rate_by_reason：blocked reason 分布（占 total_obligations 的比例）。
    blocked_rate: Dict[str, float] = {}
    total_ob = summary.total_obligations
    if total_ob > 0:
        for reason, cnt in summary.blocked_reason_counts.items():
            blocked_rate[reason] = cnt / total_ob

    # closed_violated_detection_rate：W2 fail 中 agent closed+violated 检出比例。
    w2_fail_keys = {
        k for k, v in truth_verdict.items() if _normalize_verdict(v) == "fail"
    }
    if w2_fail_keys:
        # agent 在该 family closed 且检出 violated == family verdict "fail"。
        agent_fail_keys = {
            (av.world_id, av.fragment_id, av.coarse_family_id)
            for av in av_list
            if av.coarse_family_id is not None and av.verdict == "fail"
        }
        closed_violated_rate = _safe_ratio(
            len(w2_fail_keys & agent_fail_keys), len(w2_fail_keys)
        )
    else:
        closed_violated_rate = None

    return ClosureMetrics(
        allow_stop_precision=allow_stop_precision,
        allow_stop_recall=allow_stop_recall,
        open_when_reference_unknown_rate=open_when_unknown,
        blocked_rate_by_reason=blocked_rate,
        closed_violated_detection_rate=closed_violated_rate,
    )


__all__ = [
    "VerdictMetrics",
    "CoverageMetrics",
    "ThresholdMetrics",
    "ClosureMetrics",
    "compute_verdict_metrics",
    "compute_coverage_metrics",
    "compute_threshold_metrics",
    "compute_closure_metrics",
    "DEFAULT_NUMERIC_REL_TOL",
    "DEFAULT_NUMERIC_ABS_TOL",
]
