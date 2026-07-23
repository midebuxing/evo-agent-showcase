"""泄漏检测（spec §8.4.5 leakage metrics）。

evo-agent blind 第二道防线在 evaluator 侧的体现：本模块审计 **agent 侧产物**
（run_audit / agent KG 导出 / 报告 markdown / obligation set）有没有混入 W2
参考真值字段。注意分工——evaluator 读 W2 真值是本职（spec §8.1），leakage_audit
的职责是查 **agent 这边** 有没有被污染，而不是限制 evaluator 自己。

spec §8.4.5 六项 leakage metric：

| metric | fail 条件 |
|---|---|
| forbidden_source_loaded   | run_audit 中 forbidden_sources_loaded 非空 |
| forbidden_label_in_kg     | agent database 出现 forbidden label |
| forbidden_property_in_kg  | agent database 出现 forbidden property |
| expected_verdict_text_leak| 报告直接引用 W2 expected_verdict 字段名或 projection id |
| basis_item_id_leak        | 报告出现 W2 basis_id |
| evaluator_store_access    | agent credential 访问 evaluator store |

任一 fail → 该 run 评测成绩作废，标 `invalid_due_to_answer_leakage`
（spec §8.4.5 末句 + evaluator.yaml `fail_on_leakage: true`）。

禁用 label / 属性名清单逐字取 spec §2.2.3；W2 denylist 文件取 spec §2.2.1 /
§2.3 / §2.4。

spec→code 单向：本模块不自创禁词，只照 spec §2.2.3 / §8.4.5。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- spec §2.2.3 agent KG 禁止 label（逐字） ---
FORBIDDEN_KG_LABELS: frozenset = frozenset(
    {
        "NormativeProjection",
        "ProjectionFamilyEval",
        "ThresholdEval",
        "ReportBasisItem",
        "ExpectedVerdict",
        "EvalProjection",
        "EvalTruth",
    }
)

# --- spec §2.2.3 agent KG 禁止属性名（逐字） ---
FORBIDDEN_KG_PROPERTIES: frozenset = frozenset(
    {
        # W2 reference truth / projection answer fields
        "expected_verdict",
        "selected_family",
        "projection_status",
        "basis_items",
        "unknown_reason_code",
        "regime_tag",
        "pass_bool",
        # W2 NormativeProjection 顶层字段
        "projection_id",
        "projection_registry_id",
        "projection_family",
        "projection_version",
        "required_world_core_slots",
        "required_measurement_slots",
        "required_qualifier_slots",
        "required_sidecar_interfaces",
        "matched_component_refs",
        "matched_measurement_ids",
        "coverage_status",
        # sidecar projection_id hash / ref 变体
        "raw_projection_ref_hash",
        "projection_ref_hash",
    }
)

# spec §2.2.3 说明 1：world_id / fragment_id / severity_band 是 W0/W1 事实层原生
# 字段，W2 复用同名不改变来源，**不算泄漏**。明确列为白名单避免误报。
FACT_LAYER_SHARED_FIELDS: frozenset = frozenset(
    {"world_id", "fragment_id", "severity_band", "building_id"}
)

# --- spec §2.2.1 / §2.3 / §2.4 W2 denylist 文件（evaluator-only，不得 agent 加载） ---
W2_DENYLIST_FILES: frozenset = frozenset(
    {
        "normative_projection_meta.parquet",
        "projections.parquet",
        "matched_families.parquet",
        "threshold_evaluations.parquet",
        "coverage_control_metadata.parquet",
        "basis_items.parquet",
    }
)

# 报告文本里直接出现即视为 expected_verdict 文本泄漏的关键 token（spec §8.4.5
# expected_verdict_text_leak "直接引用 W2 expected_verdict 字段名或 projection id"）。
_EXPECTED_VERDICT_TOKENS: Sequence[str] = (
    "expected_verdict",
    "normativeprojection",
    "projection_id",
    "projection_family",
    "projectionfamilyeval",
)
# W2 projection id 的形态（见真值 projection_id，如 NP-WB-...-S00001-FRG-...）。
_PROJECTION_ID_RE = re.compile(r"\bNP-[A-Za-z0-9_-]{4,}\b")
# W2 basis_id 的形态（basis_items.basis_id）。
_BASIS_ID_RE = re.compile(r"\bbasis[_-][A-Za-z0-9_-]{2,}\b", re.IGNORECASE)


@dataclass
class LeakageFinding:
    """单条泄漏命中记录。"""

    metric: str          # spec §8.4.5 的 metric 名
    detail: str          # 命中的具体内容（字段名 / token / 文件名 等）
    location: str        # 命中位置（run_audit / kg / report / obligation_set 等）


@dataclass
class LeakageAuditResult:
    """spec §8.4.5 leakage 审计结果。

    `any_leakage` 为 True 时，调用方应把该 run 评测标记为
    `invalid_due_to_answer_leakage`（spec §8.4.5）。
    `metrics` 是 6 项布尔指标（True = fail = 检出泄漏）。
    """

    forbidden_source_loaded: bool
    forbidden_label_in_kg: bool
    forbidden_property_in_kg: bool
    expected_verdict_text_leak: bool
    basis_item_id_leak: bool
    evaluator_store_access: bool
    findings: List[LeakageFinding] = field(default_factory=list)

    @property
    def any_leakage(self) -> bool:
        """6 项中任一 fail 即整体泄漏（spec §8.4.5）。"""
        return any(
            (
                self.forbidden_source_loaded,
                self.forbidden_label_in_kg,
                self.forbidden_property_in_kg,
                self.expected_verdict_text_leak,
                self.basis_item_id_leak,
                self.evaluator_store_access,
            )
        )

    def metrics_dict(self) -> Dict[str, bool]:
        """spec §8.5 evaluator 输出 `leakage_audit` 块用的 6 项布尔字典。"""
        return {
            "forbidden_source_loaded": self.forbidden_source_loaded,
            "forbidden_label_in_kg": self.forbidden_label_in_kg,
            "forbidden_property_in_kg": self.forbidden_property_in_kg,
            "expected_verdict_text_leak": self.expected_verdict_text_leak,
            "basis_item_id_leak": self.basis_item_id_leak,
            "evaluator_store_access": self.evaluator_store_access,
        }


def _iter_strings(obj: Any) -> Iterable[str]:
    """深度遍历任意嵌套结构，产出其中所有字符串（含 dict 的 key）。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from _iter_strings(item)


def _iter_dict_keys(obj: Any) -> Iterable[str]:
    """深度遍历，只产出 dict 的 key（用于 KG props 属性名审计）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _iter_dict_keys(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from _iter_dict_keys(item)


def _audit_forbidden_source(
    run_audit: Optional[Dict[str, Any]], findings: List[LeakageFinding]
) -> bool:
    """spec §8.4.5 forbidden_source_loaded —— run_audit 中 forbidden_sources_loaded 非空。

    兼容多种字段名：`forbidden_sources_loaded` / `forbidden_sources` /
    `agent_visible_sources`（后者若含 W2 denylist 文件即泄漏，spec §2.4）。
    """
    if not run_audit:
        return False
    hit = False
    for key in ("forbidden_sources_loaded", "forbidden_sources"):
        vals = run_audit.get(key)
        if vals:
            for v in vals:
                findings.append(
                    LeakageFinding("forbidden_source_loaded", str(v), f"run_audit.{key}")
                )
            hit = True
    # agent_visible_sources 里若混入 W2 denylist 文件 —— spec §2.4 hard fail 条件。
    visible = run_audit.get("agent_visible_sources") or []
    for v in visible:
        if isinstance(v, str) and v in W2_DENYLIST_FILES:
            findings.append(
                LeakageFinding(
                    "forbidden_source_loaded",
                    v,
                    "run_audit.agent_visible_sources",
                )
            )
            hit = True
    # forbidden_source_check_passed 显式为 False 也算 fail。
    if run_audit.get("forbidden_source_check_passed") is False:
        findings.append(
            LeakageFinding(
                "forbidden_source_loaded",
                "forbidden_source_check_passed=false",
                "run_audit",
            )
        )
        hit = True
    return hit


def _audit_kg_labels(
    kg_labels: Optional[Iterable[str]], findings: List[LeakageFinding]
) -> bool:
    """spec §8.4.5 forbidden_label_in_kg —— agent database 出现 forbidden label。"""
    if not kg_labels:
        return False
    hit = False
    for lbl in kg_labels:
        if isinstance(lbl, str) and lbl in FORBIDDEN_KG_LABELS:
            findings.append(LeakageFinding("forbidden_label_in_kg", lbl, "agent_kg"))
            hit = True
    return hit


def _audit_kg_properties(
    kg_export: Any, findings: List[LeakageFinding]
) -> bool:
    """spec §8.4.5 forbidden_property_in_kg —— agent database 出现 forbidden property。

    `kg_export` 可以是属性名列表，也可以是节点/关系 props 的嵌套结构
    （此时只取 dict key 做属性名审计）。
    spec §2.2.3 说明 1：world_id / fragment_id / severity_band 同名共享，白名单放行。
    """
    if kg_export is None:
        return False
    if isinstance(kg_export, (list, tuple, set)) and all(
        isinstance(x, str) for x in kg_export
    ):
        candidate_keys: Iterable[str] = kg_export
    else:
        candidate_keys = _iter_dict_keys(kg_export)
    hit = False
    for key in candidate_keys:
        if key in FACT_LAYER_SHARED_FIELDS:
            continue
        if key in FORBIDDEN_KG_PROPERTIES:
            findings.append(
                LeakageFinding("forbidden_property_in_kg", key, "agent_kg")
            )
            hit = True
    return hit


def _audit_report_text(
    report_text: Optional[str], findings: List[LeakageFinding]
) -> tuple:
    """spec §8.4.5 expected_verdict_text_leak + basis_item_id_leak —— 报告文本审计。

    返回 (expected_verdict_text_leak, basis_item_id_leak)。
    """
    if not report_text:
        return (False, False)
    lowered = report_text.lower()
    ev_leak = False
    for token in _EXPECTED_VERDICT_TOKENS:
        if token in lowered:
            findings.append(
                LeakageFinding("expected_verdict_text_leak", token, "report")
            )
            ev_leak = True
    for m in _PROJECTION_ID_RE.findall(report_text):
        findings.append(
            LeakageFinding("expected_verdict_text_leak", m, "report")
        )
        ev_leak = True

    basis_leak = False
    for m in _BASIS_ID_RE.findall(report_text):
        findings.append(LeakageFinding("basis_item_id_leak", m, "report"))
        basis_leak = True
    return (ev_leak, basis_leak)


def _audit_basis_ids_in_obj(
    obj: Any, location: str, findings: List[LeakageFinding]
) -> bool:
    """在任意结构里查 W2 basis_id 形态字符串（spec §8.4.5 basis_item_id_leak）。"""
    hit = False
    for s in _iter_strings(obj):
        if _BASIS_ID_RE.search(s):
            for m in _BASIS_ID_RE.findall(s):
                findings.append(LeakageFinding("basis_item_id_leak", m, location))
                hit = True
    return hit


def audit_leakage(
    run_audit: Optional[Dict[str, Any]] = None,
    kg_labels: Optional[Iterable[str]] = None,
    kg_export: Any = None,
    report_text: Optional[str] = None,
    obligation_set_dict: Optional[Dict[str, Any]] = None,
    evaluator_store_accessed_by_agent: bool = False,
    known_basis_ids: Optional[Iterable[str]] = None,
) -> LeakageAuditResult:
    """对一次 agent run 的产物做 spec §8.4.5 全量泄漏审计。

    Args:
        run_audit: agent 的 `run_audit.json`（dict）。用于 forbidden_source_loaded。
        kg_labels: agent KG 中出现的 label 集合。用于 forbidden_label_in_kg。
        kg_export: agent KG 属性名列表或 props 嵌套结构。用于 forbidden_property_in_kg。
        report_text: agent 报告 markdown 全文。用于 expected_verdict / basis_id 文本泄漏。
        obligation_set_dict: agent `obligation_set.json`（dict）。也扫 basis_id 形态串。
        evaluator_store_accessed_by_agent: agent credential 是否访问过 evaluator
            store——由上层凭证审计判定（spec §8.4.5 evaluator_store_access）。
        known_basis_ids: 可选，W2 真值已知 basis_id 精确集合；提供时报告/义务集里
            出现其中任一即判 basis_item_id_leak（比正则更精确）。

    Returns:
        `LeakageAuditResult`；`any_leakage` 为 True 时该 run 评测作废。
    """
    findings: List[LeakageFinding] = []

    forbidden_source = _audit_forbidden_source(run_audit, findings)
    label_leak = _audit_kg_labels(kg_labels, findings)
    property_leak = _audit_kg_properties(kg_export, findings)
    ev_leak, basis_leak_text = _audit_report_text(report_text, findings)

    # obligation_set 里也扫 basis_id 形态串（agent 不应在义务里引用 W2 basis）。
    basis_leak_obs = False
    if obligation_set_dict is not None:
        basis_leak_obs = _audit_basis_ids_in_obj(
            obligation_set_dict, "obligation_set", findings
        )

    # 若提供了 W2 已知 basis_id 精确集合，做精确匹配（报告 + 义务集）。
    basis_leak_exact = False
    if known_basis_ids:
        known = {b for b in known_basis_ids if isinstance(b, str)}
        haystacks: List[tuple] = []
        if report_text:
            haystacks.append(("report", report_text))
        for loc, obj in (("obligation_set", obligation_set_dict),):
            if obj is not None:
                for s in _iter_strings(obj):
                    haystacks.append((loc, s))
        for loc, text in haystacks:
            for bid in known:
                if bid and bid in text:
                    findings.append(LeakageFinding("basis_item_id_leak", bid, loc))
                    basis_leak_exact = True

    basis_leak = basis_leak_text or basis_leak_obs or basis_leak_exact

    evaluator_access = bool(evaluator_store_accessed_by_agent)
    if evaluator_access:
        findings.append(
            LeakageFinding(
                "evaluator_store_access",
                "agent credential accessed evaluator store",
                "credential_audit",
            )
        )

    return LeakageAuditResult(
        forbidden_source_loaded=forbidden_source,
        forbidden_label_in_kg=label_leak,
        forbidden_property_in_kg=property_leak,
        expected_verdict_text_leak=ev_leak,
        basis_item_id_leak=basis_leak,
        evaluator_store_access=evaluator_access,
        findings=findings,
    )


__all__ = [
    "FORBIDDEN_KG_LABELS",
    "FORBIDDEN_KG_PROPERTIES",
    "FACT_LAYER_SHARED_FIELDS",
    "W2_DENYLIST_FILES",
    "LeakageFinding",
    "LeakageAuditResult",
    "audit_leakage",
]
