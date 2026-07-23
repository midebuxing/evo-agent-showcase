"""identity-v5 扁平化前来源绑定 —— `BoundObligation` + 来源令牌→五元组→catalog 蓝图关联
（现网键切换增补 §1，DEBT-054 最后一役步 4）。

**加性影子模式**（本模块不接 live 判定主链、不切活动键、不改判定语义）：

- **BoundObligation（§1.2）**：把一条 v1 求值态义务与其阶段一冻结身份（`ObligationBlueprint`）
  绑成一体，是活动键与去重的唯一输入单元。

- **来源令牌关联（§1.2/§1.3）**：node / edge 求值器内部**旁路登记**的 `SourceToken`（原始源标识，
  未反推）→ 本模块按**五元组** `(rule_card_id, scope.kind, scope.scope_id, source_channel,
  source_item_id)` 从 `IdentityBlueprintCatalog` 取**恰一** blueprint（`catalog.require` 未命中
  hard-fail，不 fail-open）。scope 段取 `token.scope_fid`（令牌自携冻结 scope，调用者不得补）；
  channel 段与 SID 由 `blueprint_state_eval.token_source_item`（**单一权威**，Path A/B 共用、复用
  blueprint 侧同一 SID 构造点）产出，杜绝漂移。

- **显式 fan-out 无例外（§1.2）**：一次源项求值产 N 条义务（node-main + artifact 子 + deadline 子 +
  method 子；edge 悬空/未知关系/inactive-target）→ N 个令牌、N 个一对一绑定（每条义务恰一身份）。
  node 内 artifact/deadline 子由 workflow_artifact / workflow_deadline channel 承载（§1.2）；method 子
  **可分** → 独立 method-derived 身份，**不可分** → 折回 node-main 身份（同 hash，去重时并 1）。

blind 红线（§12）：本模块**禁 import** `eval.*` / `TruthBundle` / `workflow_engine`；只在同包中立
身份/蓝图/catalog 模块间关联。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import Obligation

from .blueprint_state_eval import token_source_item
from .identity_blueprint_catalog import FiveTupleKey, IdentityBlueprintCatalog
from .identity_v2 import ObligationBlueprint, ObligationContractError
from .obligation_deriver import SourceToken


@dataclass(frozen=True)
class BoundObligation:
    """扁平化前来源令牌（§1.2）——v1 求值态义务 + 阶段一冻结身份，去重/编号唯一输入单元。"""

    obligation: Obligation
    blueprint: ObligationBlueprint


def _nodes_by_id(card: Any) -> Dict[str, Dict[str, Any]]:
    return {
        str(n.get("obligation_node_id")): n
        for n in (card.obligation_graph or {}).get("nodes", []) or []
        if isinstance(n, dict)
    }


def _norm_scope(fid: Optional[str]) -> Optional[str]:
    """归一 scope 标识（§1.4）：None/"" → None（building）；其它保留。"""
    return fid if fid else None


def token_five_tuple_key(
    card: Any,
    token: SourceToken,
    nodes_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> FiveTupleKey:
    """来源令牌 → 五元组关联键（§1.1/§1.4）。

    **scope 从令牌自身确定**（§1.4，codex 阻断 2 修订）：scope 段取 `token.scope_fid`（**调用者不得
    自由补 scope**——旧实现 scope 由调用者另传，FR-1 义务配 `scope_fid="FR-2"` 成功绑 FR-2 蓝图 =
    错误身份 fail-open）。channel 段与 SID 由 `token_source_item`（**单一权威**）产出——channel 参与键
    构造且校验 role↔channel 一致（`token_channel_mismatch`）、method node 缺失 hard-fail
    （`method_token_node_missing`），SID 复用 blueprint 侧同一构造点（杜绝漂移）。
    """
    rid = str(card.rule_card_id)
    scope_fid = token.scope_fid
    scope_kind = "building" if scope_fid is None else "fragment"
    scope_id = "" if scope_fid is None else str(scope_fid)
    channel, sid = token_source_item(card, token, nodes_by_id)
    return (rid, scope_kind, scope_id, channel, sid)


def bind_fanout_obligations(
    card: Any,
    obligations: List[Obligation],
    tokens: List[SourceToken],
    catalog: IdentityBlueprintCatalog,
    scope_fid: Optional[str],
) -> List[BoundObligation]:
    """把一次 node / edge 求值产出的义务与其来源令牌**一对一**绑定到 catalog 蓝图（§1.2）。

    - `len(obligations) == len(tokens)`（token[i] ↔ obligations[i]，求值器同序登记）——否则
      hard-fail `source_token_count_mismatch`（每条义务须恰一令牌，fan-out N 条各一）。
    - **三者一致闸（§1.4，codex 阻断 2 修订）**：逐义务校验 `token.scope_fid ↔ obligation.fragment_id ↔
      当前循环 scope_fid` 三者相等（归一后 None/""=building），任一不一致 → hard-fail
      `token_scope_mismatch`（FR-1 义务配 FR-2 scope → 炸，杜绝错误身份 fail-open）。
    - 逐令牌按五元组 `catalog.require` 取**恰一** blueprint（未命中 → `blueprint_association_miss`，
      不 fail-open、不合成无身份 pair）。
    """
    if len(obligations) != len(tokens):
        raise ObligationContractError(
            f"source_token_count_mismatch:{len(obligations)}!={len(tokens)}"
        )
    loop_scope = _norm_scope(scope_fid)
    nodes_by_id = _nodes_by_id(card)
    out: List[BoundObligation] = []
    for obl, tok in zip(obligations, tokens):
        # 三者一致闸：token 冻结 scope ↔ 义务 fragment_id ↔ 循环 scope（归一后须全等）。
        if not (_norm_scope(tok.scope_fid) == _norm_scope(obl.fragment_id) == loop_scope):
            raise ObligationContractError(
                f"token_scope_mismatch:token={tok.scope_fid!r}:"
                f"obligation={obl.fragment_id!r}:loop={scope_fid!r}"
            )
        key = token_five_tuple_key(card, tok, nodes_by_id)
        bp = catalog.require(key)  # 未命中 hard-fail（= unbound_live_obligation 前置拦截）
        out.append(BoundObligation(obligation=obl, blueprint=bp))
    return out


__all__ = [
    "BoundObligation",
    "token_five_tuple_key",
    "bind_fanout_obligations",
]
