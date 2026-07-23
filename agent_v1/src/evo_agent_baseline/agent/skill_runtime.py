"""evo-agent v1 active OperationalSkill runtime loader / trigger / resolver。

spec v1 §7.3 + §10.6 + §9.4 + §10.9 落地：

- `load_active_skills(skill_set_id, kg_snapshot_id, rulecard_bundle_id)`：
  从 KG / 文件系统加载 status in {core, active} 的 SkillJson；过
  `pre_skill_runtime_load_guard` + staleness。
- `match_triggered_skills(skills, context)`：trigger_predicate 求值。
- `resolve_skill_conflicts(triggered)`：spec v1 §10.9 conflict resolver
  （validation_score / staleness / trigger 具体性 / created_at）；top2 差距
  ≤0.05 走 union-of-retrieval。

本模块不依赖具体存储：active skill 加载提供两种入口——
1. 直接传入 SkillJson 列表（已由上游加载）；
2. 从 filesystem path 加载（开发场景）。

L2 MetaSkill 在 v1 production 禁加载（spec §7.3.3）；本模块在
`pre_skill_runtime_load_guard` 已拦截 L2_meta_disabled。

evo-agent blind 红线：本模块只读 SkillJson（agent-visible runtime-safe），不读
EvoMemoryStore / evaluator truth；不接受 W2 字段。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from evo_agent_baseline.agent.hooks import (
    SecurityError,
    pre_skill_runtime_load_guard,
)
from evo_agent_baseline.contracts import SkillJson


# spec v1 §10.9：conflict resolver top2 差距阈值
CONFLICT_RESOLVER_TIE_THRESHOLD = 0.05

# spec v1 §10.6 可加载 runtime 的状态
RUNTIME_LOADABLE_STATUSES = frozenset({"core", "active"})


@dataclass
class SkillActivationDecision:
    """Skill 触发后 conflict resolver 的 runtime-safe 决策。

    spec v1 §10.9：决策包含
    - selected：本 group 最终选用的 SkillJson（top）；
    - union_with：top2 差距 ≤0.05 时 union-of-retrieval 的 second SkillJson；
    - shadowed：被 shadow 的 SkillJson 列表（不参与执行，写 audit）。
    - scope_signature：本 group scope 标签（family/slot 组合）。
    """

    selected: SkillJson
    union_with: Optional[SkillJson] = None
    shadowed: Optional[List[SkillJson]] = None  # __post_init__ 兜底成 []
    scope_signature: str = ""

    def __post_init__(self) -> None:
        if self.shadowed is None:
            self.shadowed = []


# ===========================================================================
# load_active_skills
# ===========================================================================
def _coerce_skill(obj: Any) -> Optional[SkillJson]:
    """SkillJson / dict → SkillJson；解析失败返回 None（被 guard 后续拦截）。"""
    if isinstance(obj, SkillJson):
        return obj
    if isinstance(obj, dict):
        try:
            return SkillJson(**obj)
        except Exception:
            return None
    return None


def load_active_skills(
    skill_set_id: str,
    kg_snapshot_id: str,
    rulecard_bundle_id: str,
    *,
    skills_source: Optional[Iterable[Any]] = None,
    skills_dir: Optional[Path] = None,
) -> List[SkillJson]:
    """加载 active OperationalSkill 集合（spec v1 §7.3 + §7.4.3）。

    入参（二选一）：
    - skills_source：SkillJson 或 dict 列表（已由上游加载），优先；
    - skills_dir：filesystem 目录，包含 `<skill_dir>/skill.json` 子目录结构。

    所有加载到的 Skill 必须通过 `pre_skill_runtime_load_guard`：
    - status in {core, active}；
    - layer 非 L2_meta_disabled；
    - staleness_status='fresh'；
    - kg_snapshot_id / rulecard_bundle_id 匹配 runtime；
    - forbidden_actions 含 5 hard 项。

    spec v1 §7.4.3 失败处理：禁用该 Skill；若全部失败，返回空 list
    （caller 决定是否 fallback last known good SkillSet）。

    入参 `skill_set_id` 当前用作 audit hint，不参与 KG 查询（v1 baseline 没有
    SkillSet KG 实现；上游可直接传入 skills_source 控制本 set 内容）。
    """
    raw_skills: List[Any] = []
    if skills_source is not None:
        raw_skills = list(skills_source)
    elif skills_dir is not None and Path(skills_dir).exists():
        for skill_json_path in sorted(Path(skills_dir).rglob("skill.json")):
            try:
                raw_skills.append(json.loads(skill_json_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

    loaded: List[SkillJson] = []
    for raw in raw_skills:
        skill = _coerce_skill(raw)
        if skill is None:
            continue
        # 包装成 SkillPackage-like dict 给 hook
        pkg_dict = {
            "skill": skill.model_dump(),
            "staleness_status": "fresh",  # 默认；真实场景由 StalenessGuard 注入
        }
        # spec v1 §7.4.3 hard guard：失败即跳过该 Skill
        try:
            pre_skill_runtime_load_guard(
                pkg_dict,
                current_kg_snapshot_id=kg_snapshot_id,
                current_rulecard_bundle_id=rulecard_bundle_id,
            )
        except SecurityError:
            continue
        if skill.status not in RUNTIME_LOADABLE_STATUSES:
            continue
        loaded.append(skill)
    return loaded


# ===========================================================================
# match_triggered_skills
# ===========================================================================
def _eval_predicate_clause(clause: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """求值单个 trigger_predicate clause（spec v1 §3.4.4 DSL 子集）。

    支持 op：
    - eq / neq / in / nin / prefix / contains / gt / gte / lt / lte。

    clause 形如 `{"field": "open_reason_code", "op": "in",
    "value": ["missing_artifact_evidence"]}`。
    """
    field = clause.get("field")
    op = clause.get("op", "eq")
    expected = clause.get("value")
    if field is None:
        return False
    actual = context.get(field)
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "in":
        return actual in (expected or [])
    if op == "nin":
        return actual not in (expected or [])
    if op == "prefix":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    if op == "contains":
        return isinstance(actual, (list, tuple, set, str)) and expected in actual
    try:
        if op == "gt":
            return float(actual) > float(expected)
        if op == "gte":
            return float(actual) >= float(expected)
        if op == "lt":
            return float(actual) < float(expected)
        if op == "lte":
            return float(actual) <= float(expected)
    except (TypeError, ValueError):
        return False
    return False


def _eval_predicate(predicate: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """递归求值 trigger_predicate（{all/any/not, [clauses]} DSL）。

    无 all / any 时把整 dict 视为单 clause。spec v1 §3.4.4 trigger DSL 子集。
    """
    if not isinstance(predicate, dict):
        return False
    if "all" in predicate and isinstance(predicate["all"], list):
        return all(_eval_predicate(c, context) for c in predicate["all"])
    if "any" in predicate and isinstance(predicate["any"], list):
        return any(_eval_predicate(c, context) for c in predicate["any"])
    if "not" in predicate and isinstance(predicate["not"], dict):
        return not _eval_predicate(predicate["not"], context)
    # 单 clause
    if "field" in predicate or "op" in predicate:
        return _eval_predicate_clause(predicate, context)
    return False


def match_triggered_skills(
    skills: List[SkillJson],
    context: Dict[str, Any],
) -> List[SkillJson]:
    """对 active Skills 求 trigger_predicate，返回命中列表（保持稳定顺序）。

    入参 context 应至少包含以下 agent-visible keys（spec v1 §3.4.4）：
    - rule_family / rule_card_id（可选）；
    - scope_obligation_kind（可选）；
    - open_reason_code / blocked_reason_code（可选）；
    - artifact_key（可选）；
    - semantic_slot_id（可选）。

    顺序：按 (skill_id, version) 升序，conflict resolver 在下游决定优先级。
    """
    matched: List[SkillJson] = []
    for sk in skills or []:
        pred = sk.trigger_predicate or {}
        if _eval_predicate(pred, context):
            matched.append(sk)
    matched.sort(key=lambda s: (s.skill_id, s.version))
    return matched


# ===========================================================================
# resolve_skill_conflicts
# ===========================================================================
def _scope_signature(skill: SkillJson) -> str:
    """对 SkillJson scope 计算签名，用作 group_by_overlapping_scope key。

    spec v1 §10.9 group_by_overlapping_scope 算法的简化实现：
    用 (frozenset(rule_families), frozenset(scope_obligation_kinds)) 串联。
    """
    scope = skill.scope
    families = ",".join(sorted(scope.rule_families or []))
    kinds = ",".join(sorted(scope.obligation_kinds or []))
    artifacts = ",".join(sorted(scope.artifact_keys or []))
    slots = ",".join(sorted(scope.semantic_slots or []))
    return f"families=[{families}]|kinds=[{kinds}]|artifacts=[{artifacts}]|slots=[{slots}]"


def _validation_score(skill: SkillJson) -> float:
    """从 validation_summary 取 validation_score（默认 0.0）。"""
    summary = skill.validation_summary or {}
    val = summary.get("validation_score")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _staleness_freshness(skill: SkillJson) -> float:
    """SkillJson 不直接含 staleness_status 字段；从 validation_summary 取，默认 1.0=fresh。"""
    summary = skill.validation_summary or {}
    status = (summary.get("staleness_status") or "fresh").lower()
    mapping = {
        "fresh": 1.0,
        "stale_rule_bundle": 0.3,
        "stale_kg_snapshot": 0.3,
        "needs_revalidation": 0.0,
    }
    return mapping.get(status, 0.5)


def _trigger_specificity(skill: SkillJson) -> float:
    """trigger 具体性：scope 字段越多越具体（粗粒度估计）。"""
    scope = skill.scope
    return float(
        len(scope.rule_families or [])
        + len(scope.rule_cards or [])
        + len(scope.semantic_slots or [])
        + len(scope.obligation_kinds or [])
        + len(scope.artifact_keys or [])
    )


def _sort_key(skill: SkillJson) -> Tuple[float, float, float, str]:
    """spec v1 §10.9 key=(validation_score, staleness_freshness,
    trigger_specificity, created_at)；created_at 降序通过 negative-string 反转。
    """
    return (
        _validation_score(skill),
        _staleness_freshness(skill),
        _trigger_specificity(skill),
        skill.created_at or "",
    )


def resolve_skill_conflicts(
    triggered: List[SkillJson],
) -> List[SkillActivationDecision]:
    """spec v1 §10.9 conflict resolver。

    流程：
    1. group_by_overlapping_scope（按 _scope_signature）；
    2. 组内按 (validation_score, staleness, trigger_specificity, created_at) 降序；
    3. top1 与 top2 差距 ≥ 0.05 → 单选 top；否则 union-of-retrieval；
    4. 其余 shadowed。

    本函数不做 budget 估算（spec 中 union 若超 budget 退 core_fallback；
    v1 baseline 没有 tool budget 实时算力，留 trace 让上游决定）。
    """
    decisions: List[SkillActivationDecision] = []
    groups: Dict[str, List[SkillJson]] = {}
    for sk in triggered or []:
        groups.setdefault(_scope_signature(sk), []).append(sk)

    for sig, group in sorted(groups.items()):
        sorted_group = sorted(group, key=_sort_key, reverse=True)
        top = sorted_group[0]
        second = sorted_group[1] if len(sorted_group) > 1 else None
        shadowed = sorted_group[2:] if len(sorted_group) > 2 else []
        if second is None:
            decisions.append(
                SkillActivationDecision(
                    selected=top,
                    union_with=None,
                    shadowed=[],
                    scope_signature=sig,
                )
            )
        else:
            top_score = _validation_score(top)
            second_score = _validation_score(second)
            if top_score - second_score >= CONFLICT_RESOLVER_TIE_THRESHOLD:
                decisions.append(
                    SkillActivationDecision(
                        selected=top,
                        union_with=None,
                        shadowed=[second] + shadowed,
                        scope_signature=sig,
                    )
                )
            else:
                decisions.append(
                    SkillActivationDecision(
                        selected=top,
                        union_with=second,
                        shadowed=shadowed,
                        scope_signature=sig,
                    )
                )
    return decisions


__all__ = [
    "CONFLICT_RESOLVER_TIE_THRESHOLD",
    "RUNTIME_LOADABLE_STATUSES",
    "SkillActivationDecision",
    "load_active_skills",
    "match_triggered_skills",
    "resolve_skill_conflicts",
]
