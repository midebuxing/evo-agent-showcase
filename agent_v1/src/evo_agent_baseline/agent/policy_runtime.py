"""evo-agent v1 EvoPolicy runtime loader / ranking applier / candidate cutoff。

spec v1 §7.4 + §3.6.4 + §5.4 + §5.5 落地：

- `load_active_policy(policy_id, ...)`：从 dict / 文件加载 active EvoPolicyVersion；
  过 `pre_policy_publish_guard`（即便已 active，再次校验是 hard safety net）。
- `apply_ranking_weights(base_signals, policy)`：把 policy.ranking_weights 应用到
  base_signals（dict[str, float]），返回 boost-adjusted scores。
- `apply_candidate_cutoff(ranked, policy)`：返回 (context_top_k, verifier_floor_set)；
  **verifier_floor_set 必须含所有 score>0 candidate**（spec v1 §5.5 不变量）。

evo-agent blind 红线：本模块不读 EvoMemoryStore raw 反馈；policy 是 active
agent-visible runtime-safe projection（spec §3.4.1）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from evo_agent_baseline.agent.hooks import (
    SecurityError,
    pre_policy_publish_guard,
)
from evo_agent_baseline.contracts import EvoPolicyVersion


# spec v1 Appendix B.4 candidate_cutoff_policy.verifier_floor 字面量
VERIFIER_FLOOR_LITERAL = "all_score_positive_not_deterministically_excluded"


def load_active_policy(
    policy_id: str,
    *,
    policy_dict: Optional[Dict[str, Any]] = None,
    policy_path: Optional[Path] = None,
    skip_publish_guard: bool = False,
    allow_non_active: bool = False,
) -> EvoPolicyVersion:
    """加载 active EvoPolicyVersion（spec v1 §3.6.4 + §9.5 v1.1 3 态状态机）。

    入参（二选一）：
    - policy_dict：已加载的 dict（优先）；
    - policy_path：JSON 文件路径。

    `skip_publish_guard=False` 时再过一次 `pre_policy_publish_guard`，确保 active
    policy 仍满足 publish constraints（防 KG 被改后 active policy 失效）。

    `allow_non_active`：默认 False，runtime 加载要求 ``status == "active"``。
    若需 bootstrap / 测试 / 校验未发布 policy 字段，调用方应改用
    :func:`load_policy_for_bootstrap`（或显式传 ``allow_non_active=True``）。

    Codex review 2026-05-27 A1[P1]：runtime 加载 ``status != "active"`` 是 spec
    违反 + 真实安全风险（未经五道 Gate 的 draft policy 进 runtime 等同越权）。
    """
    if policy_dict is None and policy_path is not None and Path(policy_path).exists():
        policy_dict = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    if policy_dict is None:
        raise ValueError("load_active_policy: 至少提供 policy_dict 或 policy_path")
    if not skip_publish_guard:
        # 二次防线：active policy 仍须满足 publish guard（spec §7.4.5）
        pre_policy_publish_guard(policy_dict)
    # Codex A1[P1]: runtime 强制 active-only（spec §9.5 v1.1 3 态状态机：
    # draft -> Gate 0-4 + leakage audit + candidate floor 全过 -> active）
    status = policy_dict.get("status")
    if not allow_non_active and status != "active":
        raise SecurityError(
            f"load_active_policy: policy status={status!r} 不可 runtime 加载"
            f"（仅 'active' 允许；draft / retired 必须先 promote 或 archived）。"
            f"若 bootstrap / test 场景需绕过，显式传 allow_non_active=True 或调用"
            f"load_policy_for_bootstrap()"
        )
    return EvoPolicyVersion(**policy_dict)


def load_policy_for_bootstrap(
    policy_id: str,
    *,
    policy_dict: Optional[Dict[str, Any]] = None,
    policy_path: Optional[Path] = None,
) -> EvoPolicyVersion:
    """Bootstrap / 测试场景加载任意 status 的 EvoPolicyVersion。

    用于 trainer 启动初始 baseline policy / 单测验证 schema / 调试。**不进入
    agent runtime**（runtime 入口 :func:`load_active_policy` 强制 active-only，
    Codex A1[P1] 修复）。

    依旧过 ``pre_policy_publish_guard`` 校验 schema 字段约束（防 candidate floor
    / verifier_floor 等字段非法）。
    """
    return load_active_policy(
        policy_id,
        policy_dict=policy_dict,
        policy_path=policy_path,
        skip_publish_guard=False,
        allow_non_active=True,
    )


def apply_ranking_weights(
    base_signals: Dict[str, float],
    policy: Optional[EvoPolicyVersion] = None,
) -> Dict[str, float]:
    """对 base_signals 应用 policy.ranking_weights，返回 boost-adjusted scores。

    入参：
    - base_signals：每路信号名 → 信号值（dict[str, float]），如
      `{"base_fulltext_score": 1.2, "skill_trigger_boost": 1.0}`；
    - policy：EvoPolicyVersion；缺省时按 spec v1 §5.4 默认权重。

    返回：每路信号名 → boost_adjusted_value（weight * signal）。

    spec v1 §5.4：weights bound [-2.0, 2.0]；超出由 pre_policy_publish_guard
    在加载时已拦截，本函数不再二次校验。
    """
    from evo_agent_baseline.retrieval.rule_retriever import (
        DEFAULT_V1_RANKING_WEIGHTS,
    )

    weights: Dict[str, float] = dict(DEFAULT_V1_RANKING_WEIGHTS)
    if policy is not None and policy.ranking_weights:
        weights.update({k: float(v) for k, v in policy.ranking_weights.items()})

    out: Dict[str, float] = {}
    for sig_name, sig_val in (base_signals or {}).items():
        w = weights.get(sig_name, 1.0)  # 未声明 weight 的信号默认 1.0
        try:
            out[sig_name] = float(sig_val) * w
        except (TypeError, ValueError):
            out[sig_name] = 0.0
    return out


def apply_candidate_cutoff(
    ranked: List[Tuple[str, float]],
    policy: Optional[EvoPolicyVersion] = None,
) -> Tuple[List[Tuple[str, float]], Set[str]]:
    """返回 (context_top_k, verifier_floor_set)（spec v1 §5.4 + §5.5）。

    - context_top_k：按 policy.candidate_cutoff_policy.context_top_k 截断的
      LLM context list（不影响 verifier）；
    - verifier_floor_set：所有 score>0 rule_card_id（**spec v1 §5.5 不变量：
      Skill / Policy 不可削窄此集合**；这里不接受任何 cutoff 削窄）。

    入参 ranked：[(rule_card_id, score), ...] 已按 score 降序。
    """
    # verifier floor = all score>0（spec v1 §5.5 不变量）
    verifier_floor: Set[str] = {rcid for rcid, score in ranked or [] if score > 0}

    # context_top_k cutoff（仅影响 LLM context）
    cutoff_policy = (
        policy.candidate_cutoff_policy
        if policy is not None and policy.candidate_cutoff_policy
        else {}
    ) or {}
    top_k = cutoff_policy.get("context_top_k")
    # spec v1 §5.5 verifier_floor literal check
    declared_floor = cutoff_policy.get("verifier_floor")
    if declared_floor and declared_floor != VERIFIER_FLOOR_LITERAL:
        # policy 已声明非法 floor 字面量 → 这是 publish guard 该拦截的；
        # 这里以 hard fail 兜底，绝不允许 verifier 削窄。
        raise SecurityError(
            f"apply_candidate_cutoff: candidate_cutoff_policy.verifier_floor="
            f"{declared_floor!r} 不是 '{VERIFIER_FLOOR_LITERAL}'"
            "（spec v1 §5.5 不变量：Skill / Policy 不可削窄 verifier candidate floor）"
        )

    if isinstance(top_k, int) and top_k > 0:
        context_list = list(ranked)[:top_k]
    else:
        context_list = list(ranked)

    return context_list, verifier_floor


__all__ = [
    "VERIFIER_FLOOR_LITERAL",
    "load_active_policy",
    "load_policy_for_bootstrap",
    "apply_ranking_weights",
    "apply_candidate_cutoff",
]
