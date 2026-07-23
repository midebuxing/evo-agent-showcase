"""Regulation thresholds loader — 从权威 threshold_regime_index.json 加载真阈值数据.

替代 build_normative_projections_for_world 中 placeholder threshold (m.value_num * 1.5)。
按 W0 projection family（如 mbis.inspection.external_components）做 prefix 匹配，找出该 family
下所有 rule_card 的 threshold_regimes。

数据源（DEBT-056 前向修 2026-07-14）：权威派生索引
`agent_v1/regulations/rulecard_v2/mbis_cop_2023/threshold_regime_index.json`
（由 `rule_cards.json` 经 `derive_threshold_regime_index` 派生，41 regime，与 closure 侧同一份）。
取代旧 `reviewed_batches/batch_*/rule_cards_delta.jsonl` 快照——后者 README 自述
staging-not-runtime-source-of-truth（31 regime 旧快照），W2 读它即 bug（closure 侧与 W2 侧
阈值定义分家）。`derive_threshold_regime_index` 每条已内嵌 `family_id` / `rule_card_id`，
恰覆盖 `Threshold` dataclass；下游 `find_thresholds_for_slot_any_family` 等签名零改（drop-in）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THRESHOLD_REGIME_INDEX = (
    PROJECT_ROOT
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
    / "threshold_regime_index.json"
)


class ThresholdRegimeSourceError(RuntimeError):
    """权威 threshold_regime_index.json 缺失/字段非法时抛出（DEBT-056 前向修守卫）。"""


@dataclass
class Threshold:
    """spec 04 §20 ThresholdEval 输入端的真阈值数据."""

    threshold_regime_id: str
    rule_card_id: str
    family_id: str
    measure_key: str  # 对应 W0 measurement slot_id
    operator: str  # <= / < / >= / > / == / != / in / not_in / formula
    value: Any  # 数值 / bool / list / str；formula 型制度无 literal value（None）
    unit: Optional[str]
    qualifiers: Dict[str, Any]
    time_anchor_key: Optional[str]
    # DEBT-056 前向修（2026-07-14）：formula 型制度（operator=="formula"，如
    # count.pull_test.additional_after_failure，expected=n^2-2n+3）无 literal value，
    # 真语义在嵌套 formula DTO（expression + variables[]）。loader 完整携带、不丢；
    # 权威索引里非 formula 制度此字段为 None。跨侧签名比对（test）纳入本字段。
    formula: Optional[Dict[str, Any]] = None


@lru_cache(maxsize=1)
def load_all_thresholds(index_path: Optional[Path] = None) -> List[Threshold]:
    """从权威派生索引 threshold_regime_index.json 加载全部 threshold_regime.

    Cached——多次调用返回同一 list（启动时一次加载）。

    DEBT-056 前向修（2026-07-14）：源从 reviewed_batches 旧快照（31 regime）改为
    权威索引（41 regime，closure 侧同一份）。索引每条已内嵌 `family_id` / `rule_card_id`
    （`derive_threshold_regime_index` 加）；`Threshold` dataclass 逐字段读回。
    """
    path = index_path or DEFAULT_THRESHOLD_REGIME_INDEX
    thresholds: List[Threshold] = []
    if not path.exists():
        return thresholds

    text = path.read_text(encoding="utf-8-sig")
    doc = json.loads(text)
    for tr in doc.get("threshold_regimes", []) or []:
        regime_id = tr.get("threshold_regime_id", "")
        # B.2 ① 源 loader hard-fail：空串 threshold_regime_id 不再静默透传 ""。
        if not regime_id:
            raise ThresholdRegimeSourceError(
                "threshold_regime_id_missing_at_source: "
                f"权威索引 {path} 含空 threshold_regime_id 条目 {tr!r}"
            )
        thresholds.append(Threshold(
            threshold_regime_id=regime_id,
            rule_card_id=tr.get("rule_card_id", ""),
            family_id=tr.get("family_id", ""),
            measure_key=tr.get("measure_key", ""),
            operator=tr.get("operator", "=="),
            value=tr.get("value"),
            unit=tr.get("unit"),
            qualifiers=tr.get("qualifiers", {}) or {},
            time_anchor_key=tr.get("time_anchor_key"),
            # DEBT-056 前向修：完整携带 formula 字段（formula 型制度无 literal value）。
            formula=tr.get("formula"),
        ))
    return thresholds


# W0 projection family → rule_card family prefixes alias 映射
# rule_card 命名比 W0 更细（含 actor / action_cluster 后缀，部分名字也不同）。
# W0 spec 04 / 08 整合了多个 rule_card family 为单个 W0 family。
_W0_FAMILY_TO_RULECARD_PREFIXES: Dict[str, List[str]] = {
    "mbis.inspection.external_components": [
        "mbis.inspection.external_components",
        "mbis.inspection.covered_external_wall",  # rule_card 用此名
    ],
    "mbis.inspection.structural_components": [
        "mbis.inspection.structural_components",
    ],
    "mbis.inspection.drainage": [
        "mbis.inspection.drainage",
    ],
    # W2-006 (批次 C 2026-05-21)：跟 W2-005 / W2-006 拆分同步——fire_safety / ubw 各自独立
    # baseline family，不共用合并 entry；FSP 也独立 family（spec 06 §2.1 row 9）.
    "mbis.inspection.ubw": [
        "mbis.inspection.ubw",
    ],
    "mbis.inspection.fire_safety": [
        "mbis.inspection.fire_safety",
    ],
    "mbis.investigation.gate_and_proposal": [
        "mbis.investigation.gate_and_proposal",
    ],
    "mbis.investigation.structural_assessment_fsp": [
        "mbis.investigation.structural_assessment_fsp",
    ],
    "mbis.repair.general_selection_and_classification": [
        "mbis.repair.general_selection_and_classification",
    ],
    "mbis.repair.external_structural_validation": [
        "mbis.repair.external_structural_validation",
    ],
    "mbis.repair.fire_safety_and_drainage": [
        "mbis.repair.fire_safety_and_drainage",
    ],
    "mbis.supervision.ri_minimum_and_site_controls": [
        "mbis.supervision.ri_minimum_and_site_controls",
    ],
    "mbis.supervision.rc_controls": [
        "mbis.supervision.rc_controls",
    ],
    "mbis.reporting.inspection_report": [
        "mbis.reporting.inspection_report",
    ],
    "mbis.reporting.completion_report": [
        "mbis.reporting.completion_report",
    ],
    "mbis.procedure.ri_notifications_and_submissions": [
        "mbis.procedure.ri_notifications_and_submissions",
        "mbis.reporting.ri_procedural_notifications",  # rule_card 用此名
    ],
    "mbis.scope.coverage_and_preinspection": [
        "mbis.scope.coverage_and_preinspection",
        "mbis.scope.building",
    ],
}


def get_thresholds_for_w0_family(w0_family: str) -> List[Threshold]:
    """Find rule_card thresholds matching a W0 projection family.

    W0 family 通过 _W0_FAMILY_TO_RULECARD_PREFIXES 映射到 rule_card family prefixes
    （rule_card 命名比 W0 更细，部分名字不同；W0 spec 整合多个 rule_card family 为单个）。
    """
    all_thresholds = load_all_thresholds()
    prefixes = _W0_FAMILY_TO_RULECARD_PREFIXES.get(w0_family, [w0_family])
    return [t for t in all_thresholds if any(t.family_id.startswith(p) for p in prefixes)]


def find_threshold_for_slot(
    w0_family: str,
    slot_id: str,
) -> Optional[Threshold]:
    """Look up the first matching threshold for a W0 family + slot_id.

    Returns the first Threshold whose measure_key == slot_id and family_id starts with w0_family.
    None if no match.
    """
    family_thresholds = get_thresholds_for_w0_family(w0_family)
    for t in family_thresholds:
        if t.measure_key == slot_id:
            return t
    return None


def find_thresholds_for_slot(
    w0_family: str,
    slot_id: str,
) -> List[Threshold]:
    """Find ALL matching thresholds (some slots have multiple thresholds, e.g., different deadlines).

    Returns list of all Thresholds whose measure_key == slot_id and family_id starts with w0_family.
    """
    family_thresholds = get_thresholds_for_w0_family(w0_family)
    return [t for t in family_thresholds if t.measure_key == slot_id]


@lru_cache(maxsize=1)
def _thresholds_by_measure_key(index_path: Optional[Path] = None) -> Dict[str, List[Threshold]]:
    """QA-Parallelize 2026-05-09 perf fix：按 measure_key 索引所有 thresholds.

    Profile 显示 `find_thresholds_for_slot_any_family` 是 O(N) 每次调用 (348 条 rule_card
    threshold) × 100M+ 次（每 fragment × 每 measurement / sidecar slot），占 projection
    executor 84% 的 wall-clock. 改为按 measure_key 一次性建索引 → O(1) lookup.
    """
    index: Dict[str, List[Threshold]] = {}
    for t in load_all_thresholds(index_path):
        index.setdefault(t.measure_key, []).append(t)
    return index


def find_threshold_for_slot_any_family(slot_id: str) -> Optional[Threshold]:
    """spec 09 §1.2 (2026-05-09) helper for sidecar slot threshold lookup.

    背景：sidecar slot（如 `duration.notification.deadline`）的真阈值在 rule_card
    中归属 procedure / supervision / reporting 类 family；但 W0 的
    _pick_projection_family_for_fragment 每 fragment 只返回 1 个 mechanism-driven
    family（如 mbis.inspection.external_components）。所以按 candidate_family 查
    sidecar slot 阈值会 miss 所有 procedure / reporting 阈值。

    本函数跨家族查（任意 family 的 measure_key == slot_id 即可），让 sidecar slot
    的 distribution 真正进入 5-bin 评估。返回首个匹配；slot 有多阈值时调用方应改用
    find_thresholds_for_slot_any_family.

    QA-Parallelize 2026-05-09 perf：用 _thresholds_by_measure_key 索引 O(1) lookup.
    """
    matches = _thresholds_by_measure_key().get(slot_id)
    return matches[0] if matches else None


def find_thresholds_for_slot_any_family(slot_id: str) -> List[Threshold]:
    """find_threshold_for_slot_any_family 的 list 版本（slot 多阈值时用）.

    QA-Parallelize 2026-05-09 perf：用 _thresholds_by_measure_key 索引 O(1) lookup.
    """
    return list(_thresholds_by_measure_key().get(slot_id, []))
