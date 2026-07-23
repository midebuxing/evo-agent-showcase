"""evaluator 输出报告（spec §8.5）。

把 truth_loader / mapper / metrics / leakage_audit 串成一次完整评测，产出
spec §8.5 规定的 evaluator 输出 JSON：

```json
{
  "eval_run_id": "EVAL-...",
  "agent_run_id": "CAR-...",
  "world_id": "WB-...",
  "building_id": "BLD-...",
  "valid": true,
  "invalid_reasons": [],
  "metrics": { ... },
  "per_fragment_results": [],
  "leakage_audit": { ... }
}
```

关键规则：
- spec §8.4.5 / evaluator.yaml `fail_on_leakage: true`：任一 leakage fail →
  `valid=false`，`invalid_reasons` 含 `invalid_due_to_answer_leakage`，
  该 run 评测成绩作废。
- spec §8.3.2：crosswalk 缺失 → `evaluation_status="blocked_missing_crosswalk"`，
  不能给 family-level score；agent run 不受影响。
- spec §8.6：evaluator 不反写 agent KG，本模块只产离线 JSON。

spec→code 单向：输出字段照 spec §8.5 样例，不自创。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from evo_agent_baseline.contracts import ClosureValidationResult, Obligation
from evo_agent_baseline.eval.leakage_audit import LeakageAuditResult, audit_leakage
from evo_agent_baseline.eval.mapper import (
    AgentFamilyVerdict,
    CrosswalkError,
    FamilyCrosswalk,
    aggregate_agent_family_verdicts,
    default_crosswalk_path,
    load_crosswalk,
)
from evo_agent_baseline.eval.metrics import (
    compute_alignment_diagnostics,
    compute_building_verdict_metrics,
    compute_closure_metrics,
    compute_coverage_metrics,
    compute_threshold_metrics,
    compute_verdict_metrics,
)
from evo_agent_baseline.eval.truth_loader import TruthBundle


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def make_eval_run_id(agent_run_id: str, when: Optional[str] = None) -> str:
    """生成 `EVAL-<timestamp>-<hash>` 形式的 eval_run_id（spec §8.5）。"""
    when = when or _now_iso()
    digest = hashlib.sha1(f"{agent_run_id}|{when}".encode("utf-8")).hexdigest()[:8]
    ts = when.replace(":", "").replace("-", "").replace(".", "")[:15]
    return f"EVAL-{ts}-{digest}"


@dataclass
class EvalInputs:
    """一次评测所需的全部输入（agent 侧产物 + W2 真值）。

    spec §8.2 evaluator 输入：agent_outputs（closure_validation_result /
    obligation_set / report / run_audit）+ reference_truth（W2 5 表）。
    """

    agent_run_id: str
    world_id: str
    building_id: str
    closure_result: ClosureValidationResult
    truth: TruthBundle
    # agent 检索到的 rule_card_id（来自 run_audit / retrieval_summary）。
    retrieved_rule_card_ids: List[str]
    # leakage 审计输入（均可选；缺省视为无泄漏证据）。
    run_audit: Optional[Dict[str, Any]] = None
    kg_labels: Optional[List[str]] = None
    kg_export: Any = None
    report_text: Optional[str] = None
    obligation_set_dict: Optional[Dict[str, Any]] = None
    evaluator_store_accessed_by_agent: bool = False
    # identity-v5 manifest 的 evaluator 侧投影；不复制进扁平 Obligation DTO。
    threshold_regime_by_obligation_id: Optional[Dict[str, str]] = None

    def __post_init__(self) -> None:
        if self.threshold_regime_by_obligation_id is not None:
            return
        mapping: Dict[str, str] = {}
        for item in self.closure_result.obligation_set.identity_manifest:
            obligation_id = item.get("obligation_id")
            identity = item.get("identity") or {}
            predicate = identity.get("source_predicate_spec") or {}
            regime = predicate.get("threshold_regime_id")
            if (
                isinstance(obligation_id, str)
                and obligation_id
                and isinstance(regime, str)
                and regime
            ):
                mapping[obligation_id] = regime
        self.threshold_regime_by_obligation_id = mapping


def _build_per_fragment_results(
    agent_verdicts: List[AgentFamilyVerdict],
    truth: TruthBundle,
) -> List[Dict[str, Any]]:
    """spec §8.5 per_fragment_results —— 按 fragment 列出 agent vs W2 verdict。"""
    # W2 真值 (world,fragment,coarse) -> expected_verdict
    proj = truth.projections
    truth_map: Dict[tuple, str] = {}
    if {"world_id", "fragment_id", "projection_family", "expected_verdict"}.issubset(
        proj.columns
    ):
        for _, row in proj.iterrows():
            truth_map[
                (row["world_id"], row["fragment_id"], row["projection_family"])
            ] = row["expected_verdict"]

    out: List[Dict[str, Any]] = []
    for av in agent_verdicts:
        key = (av.world_id, av.fragment_id, av.coarse_family_id)
        expected = truth_map.get(key) if av.coarse_family_id is not None else None
        out.append(
            {
                "world_id": av.world_id,
                "fragment_id": av.fragment_id,
                "fine_family_id": av.family_id,
                "coarse_family_id": av.coarse_family_id,
                "agent_family_verdict": av.verdict,
                "reference_expected_verdict": expected,
                "verdict_match": (
                    None
                    if expected is None
                    else (str(av.verdict).lower() == str(expected).lower())
                ),
                "obligation_count": av.obligation_count,
            }
        )
    return out


def evaluate_run(
    inputs: EvalInputs,
    crosswalk: Optional[FamilyCrosswalk] = None,
    crosswalk_path: Optional[str] = None,
) -> Dict[str, Any]:
    """对一次 agent run 跑完整评测，返回 spec §8.5 evaluator 输出 JSON（dict）。

    Args:
        inputs: agent 侧产物 + W2 真值。
        crosswalk: 已加载的 fine→coarse 对照表；None 时按 `crosswalk_path`
            （缺省随包路径）加载。
        crosswalk_path: crosswalk JSON 路径。

    crosswalk 缺失 / 非法 → 返回 `evaluation_status="blocked_missing_crosswalk"`，
    仍输出 leakage_audit（leakage 审计不依赖 crosswalk）；agent run 不受影响
    （spec §8.3.2）。
    """
    closure = inputs.closure_result
    obligations: List[Obligation] = list(closure.obligation_set.obligations)

    eval_run_id = make_eval_run_id(inputs.agent_run_id)

    # ---- leakage 审计先做（spec §8.4.5；不依赖 crosswalk / 真值对齐） ----
    known_basis_ids: List[str] = []
    bi = inputs.truth.basis_items
    if "basis_id" in bi.columns:
        known_basis_ids = [b for b in bi["basis_id"].tolist() if isinstance(b, str)]
    leakage: LeakageAuditResult = audit_leakage(
        run_audit=inputs.run_audit,
        kg_labels=inputs.kg_labels,
        kg_export=inputs.kg_export,
        report_text=inputs.report_text,
        obligation_set_dict=inputs.obligation_set_dict,
        evaluator_store_accessed_by_agent=inputs.evaluator_store_accessed_by_agent,
        known_basis_ids=known_basis_ids,
    )

    base: Dict[str, Any] = {
        "eval_run_id": eval_run_id,
        "agent_run_id": inputs.agent_run_id,
        "world_id": inputs.world_id,
        "building_id": inputs.building_id,
        "evaluated_at": _now_iso(),
        "truth_source_dir": inputs.truth.truth_dir,
        "truth_backend": inputs.truth.backend,
    }

    # ---- crosswalk 加载（spec §8.3.2 hard requirement） ----
    if crosswalk is None:
        try:
            crosswalk = load_crosswalk(crosswalk_path or default_crosswalk_path())
        except CrosswalkError as exc:
            # spec §8.3.2：crosswalk 缺失 → blocked，不给 family-level score。
            base.update(
                {
                    "evaluation_status": "blocked_missing_crosswalk",
                    "valid": not leakage.any_leakage,
                    "invalid_reasons": (
                        ["invalid_due_to_answer_leakage"]
                        if leakage.any_leakage
                        else []
                    ),
                    "crosswalk_error": str(exc),
                    "metrics": {},
                    "per_fragment_results": [],
                    "leakage_audit": leakage.metrics_dict(),
                    "leakage_findings": [
                        f.__dict__ for f in leakage.findings
                    ],
                }
            )
            return base

    # ---- §8.3.1 + §8.3.2：agent obligation → family verdict（升 coarse） ----
    agent_verdicts: List[AgentFamilyVerdict] = aggregate_agent_family_verdicts(
        obligations, crosswalk
    )

    # ---- §8.4 各类 metrics ----
    verdict_m = compute_verdict_metrics(agent_verdicts, inputs.truth)
    coverage_m = compute_coverage_metrics(
        agent_verdicts,
        obligations,
        inputs.retrieved_rule_card_ids,
        inputs.truth,
    )
    threshold_m = compute_threshold_metrics(
        obligations,
        inputs.truth,
        inputs.threshold_regime_by_obligation_id,
    )
    closure_m = compute_closure_metrics(closure, agent_verdicts, inputs.truth)

    # ---- DEBT-046 楼级对齐口径（过渡期主对齐层）+ 分层诊断计数 ----
    # fragment 级精确对齐（§8.4.1 平铺键）原样保留；楼级口径独立嵌套，两套口径
    # 分开计数、口径透明（fragment_exact=N1 / family_unique_fallback=N2 /
    # ambiguous_excluded=N3 / building_level=N4）。
    building_verdict_m = compute_building_verdict_metrics(agent_verdicts, inputs.truth)
    alignment_diag = compute_alignment_diagnostics(agent_verdicts, inputs.truth)

    metrics: Dict[str, Any] = {
        **verdict_m.as_dict(),
        **coverage_m.as_dict(),
        **threshold_m.as_dict(),
        **closure_m.as_dict(),
        "building_level_verdict_metrics": building_verdict_m.as_dict(),
        "alignment_pair_counts": {
            "fragment_exact": verdict_m.compared_pairs,
            "family_unique_fallback": alignment_diag["family_unique_fallback_pairs"],
            "ambiguous_excluded": alignment_diag["ambiguous_excluded_pairs"],
            "building_level": building_verdict_m.compared_pairs,
        },
        "family_unique_fallback_confusion": alignment_diag[
            "family_unique_fallback_confusion"
        ],
    }

    # ---- 可核验子宇宙口径（2026-07-08 用户裁定门③选项3；eval 侧新增，判定权/
    # allow_stop/全宇宙口径零改动）----
    # 归约宇宙剔除 kind='action'（spec §6.3.10.4 专业判断/编排类动作——真值不打分
    # 且多数无事实绑定通道）；嵌套命名防平铺撞键（DEBT-048 教训）。
    agent_verdicts_verifiable = aggregate_agent_family_verdicts(
        obligations, crosswalk, exclude_kinds={"action"}
    )
    verdict_verifiable_m = compute_verdict_metrics(
        agent_verdicts_verifiable, inputs.truth
    )
    building_verifiable_m = compute_building_verdict_metrics(
        agent_verdicts_verifiable, inputs.truth
    )
    metrics["verifiable_subuniverse"] = {
        "fragment_level": verdict_verifiable_m.as_dict(),
        "building_level": building_verifiable_m.as_dict(),
    }

    # ---- valid / invalid_reasons（spec §8.4.5） ----
    invalid_reasons: List[str] = []
    if leakage.any_leakage:
        invalid_reasons.append("invalid_due_to_answer_leakage")
    valid = len(invalid_reasons) == 0

    base.update(
        {
            "evaluation_status": "completed",
            "valid": valid,
            "invalid_reasons": invalid_reasons,
            "crosswalk_schema_version": crosswalk.schema_version,
            "metrics": metrics,
            "per_fragment_results": _build_per_fragment_results(
                agent_verdicts, inputs.truth
            ),
            "leakage_audit": leakage.metrics_dict(),
            "leakage_findings": [f.__dict__ for f in leakage.findings],
            "agent_family_verdict_count": len(agent_verdicts),
        }
    )
    return base


def write_eval_report(report: Dict[str, Any], out_path: str) -> str:
    """把 evaluator 输出 JSON 落盘（spec §8.6：仅离线报告，不反写 agent KG）。"""
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return out_path


__all__ = [
    "EvalInputs",
    "make_eval_run_id",
    "evaluate_run",
    "write_eval_report",
]
