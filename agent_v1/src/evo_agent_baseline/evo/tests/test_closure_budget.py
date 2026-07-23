"""确定性单测：分批闭包预算核心算法（evo/closure_budget.py）。

不跑 LLM、不连 Neo4j —— 用 eval/tests/_fixtures 造真 Obligation /
ClosureValidationResult，直接驱动纯函数 + PagedClosureController，验证：

- 测 A（无 skill 退字典序）：``order_families_set_cover`` 空 skill / 无 crosswalk
  → 纯 family_id 字典序。
- 测 B（set-cover 去冗余排序）：skill 关注某 coarse → 该 coarse 仅 1 个代表 fine
  提到队首，同 coarse 的冗余 fine 排到非 anchor 之后。
- 测 C（无 skill 状态机 + 预算）：每轮推进 1 批、子集 family_count / obligation
  递增、预算用尽挡住末位家族、``exhausted`` 翻 True。
- 测 D（端到端 family_recall）：字典序下目标家族排末位、预算覆盖不到 → recall 低；
  skill 提首 → 覆盖到 → recall 高（同预算下机制核心）。

测 A/B/D 用真实 fine family id（在 ``family_crosswalk_v1.json`` 里）走真 crosswalk
映射 fine→coarse；测 C 用三个独立家族验证纯状态机（不依赖 crosswalk）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from evo_agent_baseline.eval.mapper import (
    default_crosswalk_path,
    load_crosswalk,
)
from evo_agent_baseline.eval.tests._fixtures import (
    make_closure_result,
    make_obligation,
)
from evo_agent_baseline.evo.closure_budget import (
    PagedClosureController,
    order_families_set_cover,
    rebuild_closure_subset,
    skill_relevant_families,
)


# --- 真实 fine family id（在 family_crosswalk_v1.json 中，走真 fine→coarse 映射）---
S_COV = "mbis.inspection.structural_components.ri.coverage"   # coarse: structural_components
S_ID = "mbis.inspection.structural_defects.ri.identify"       # 同 coarse(structural)
S_FU = "mbis.inspection.structural_defects.ri.follow_up"      # 同 coarse(structural)
E_REC = "mbis.inspection.external_components.ri.record"        # coarse: external_components

# 测 D：F_PRE 字典序排末位（'p' > 'e' > 's' 里它 'mbis.preinspection...' 排最后？
# 实际字典序由全串决定，下方用断言锚定 W2 真值家族 = F_PRE 的 coarse）。
F_EXT = "mbis.inspection.external_components.ri.record"          # coarse: external_components
F_STRUCT = "mbis.inspection.structural_components.ri.coverage"   # coarse: structural_components
F_PRE = "mbis.preinspection.background.ri.review"               # coarse: scope.coverage_and_preinspection
COARSE_PRE = "mbis.scope.coverage_and_preinspection"            # F_PRE 的 primary coarse


def _crosswalk():
    return load_crosswalk(default_crosswalk_path())


def _mock_skill(*families):
    """占位 skill：仅持 scope.rule_families（PagedClosureController / 排序函数只读这个）。"""
    return SimpleNamespace(scope=SimpleNamespace(rule_families=list(families)))


# ===========================================================================
# 测 A：无 skill / 无 crosswalk → 字典序（草稿 _order_families_skill_aware 退化分支）
# ===========================================================================
def test_order_no_skill_falls_back_to_lexicographic():
    fams = [S_COV, S_ID, S_FU, E_REC]
    cw = _crosswalk()
    # 空 skill 集
    assert order_families_set_cover(fams, set(), cw) == sorted(fams)
    # 有 skill 但 crosswalk 缺失
    assert order_families_set_cover(fams, {S_COV}, None) == sorted(fams)


# ===========================================================================
# 测 B：coarse 级 set-cover 去冗余排序（草稿 _order_families_skill_aware 主分支）
# ===========================================================================
def test_order_set_cover_dedup_puts_one_rep_per_anchor_coarse():
    fams = [S_COV, S_ID, S_FU, E_REC]
    cw = _crosswalk()
    # skill 关注 structural coarse（经 S_COV 的 fine 映射）
    order = order_families_set_cover(fams, {S_COV}, cw)

    assert order[0] == S_COV, f"structural 代表应提到队首，实得 {order}"
    # 去冗余：同 coarse(structural) 的冗余 fine 排到非 anchor(E_REC) 之后
    assert order.index(E_REC) < order.index(S_ID), f"冗余 fine 应排到非 anchor 后，实得 {order}"
    assert order.index(E_REC) < order.index(S_FU), f"去冗余失败，实得 {order}"
    # 不丢家族
    assert set(order) == set(fams)


def test_skill_relevant_families_union():
    sk1 = _mock_skill(S_COV, E_REC)
    sk2 = _mock_skill(F_PRE)
    assert skill_relevant_families([sk1, sk2]) == {S_COV, E_REC, F_PRE}
    # 无 skill / 无 scope → 空集
    assert skill_relevant_families([]) == set()
    assert skill_relevant_families([SimpleNamespace(scope=None)]) == set()


# ===========================================================================
# 测 C：无 skill 状态机 + 预算（草稿 patch C _paged_execute_tool 状态机）
# ===========================================================================
FAM_A, FAM_B, FAM_C = "fam.A", "fam.B", "fam.C"


def _build_full_abc():
    """全量 closure：famA(2 obl: 1 open+1 closed) / famB(1 closed) / famC(1 open)。"""
    obls = [
        make_obligation(
            "o1", source_family_id=FAM_A, closure_status="open",
            satisfaction_status="unknown", open_reason_code="missing_artifact_evidence",
        ),
        make_obligation(
            "o2", source_family_id=FAM_A, closure_status="closed",
            satisfaction_status="satisfied",
        ),
        make_obligation(
            "o3", source_family_id=FAM_B, closure_status="closed",
            satisfaction_status="satisfied",
        ),
        make_obligation(
            "o4", source_family_id=FAM_C, closure_status="open",
            satisfaction_status="unknown", open_reason_code="missing_artifact_evidence",
        ),
    ]
    return make_closure_result(obls)


def test_paged_controller_no_skill_budget_state_machine():
    full = _build_full_abc()
    # 无 skill / 无 crosswalk → 字典序 fam.A < fam.B < fam.C；预算 2 轮 × 每轮 1 家族
    ctl = PagedClosureController(
        skill_families=set(), crosswalk=None, query_budget=2, batch_families=1
    )

    # 第 1 轮：覆盖 fam.A（2 obl）
    r1, p1 = ctl.advance(full)
    assert p1["closure_paging"]["covered_families"] == 1, p1
    assert p1["family_count"] == 1, f"调1 子集应 1 家族，实得 {p1['family_count']}"
    assert p1["total_obligations"] == 2, f"famA 应 2 obl，实得 {p1['total_obligations']}"
    assert p1["closure_paging"]["budget_exhausted"] is False
    assert ctl.exhausted is False

    # 第 2 轮：再覆盖 fam.B（+1 closed obl）
    r2, p2 = ctl.advance(full)
    assert p2["closure_paging"]["covered_families"] == 2, p2
    assert p2["family_count"] == 2, p2["family_count"]
    assert p2["total_obligations"] == 3, f"famA+famB 应 3 obl，实得 {p2['total_obligations']}"

    # 第 3 轮：预算用尽，不再推进，famC 被挡在外
    r3, p3 = ctl.advance(full)
    assert p3["closure_paging"]["budget_exhausted"] is True, "调3 应预算用尽"
    assert p3["closure_paging"]["covered_families"] == 2, "预算用尽不应再推进"
    assert ctl.exhausted is True
    assert set(ctl.covered_families) == {FAM_A, FAM_B}, ctl.covered_families
    # famC 的 open obligation 没进子集 → 子集仍只 3 obl
    assert r3.closure_summary.total_obligations == 3
    assert r3.closure_summary.family_count == 2


def test_rebuild_closure_subset_recomputes_summary():
    full = _build_full_abc()
    # 只取 famB 的 obligation（1 closed satisfied）
    fam_b_obls = [
        o for o in full.obligation_set.obligations
        if o.source_family_id == FAM_B
    ]
    sub = rebuild_closure_subset(full, fam_b_obls)
    assert sub.closure_summary.total_obligations == 1
    assert sub.closure_summary.family_count == 1
    assert sub.closure_summary.open_count == 0
    # famB 全 closed satisfied → allow_stop 应 True（重算 summary）
    assert sub.allow_stop is True
    assert sub.allow_report_generation is True
    # 空子集 → 0 obl
    empty = rebuild_closure_subset(full, [])
    assert empty.closure_summary.total_obligations == 0
    assert empty.closure_summary.family_count == 0


# ===========================================================================
# 测 D：端到端 family_recall（真 crosswalk fine→coarse；skill 把 recall 从 0 拉到 1）
# ===========================================================================
def _build_full_real():
    return make_closure_result([
        make_obligation(
            "e1", source_family_id=F_EXT, closure_status="open",
            satisfaction_status="unknown", open_reason_code="missing_artifact_evidence",
        ),
        make_obligation(
            "s1", source_family_id=F_STRUCT, closure_status="closed",
            satisfaction_status="satisfied",
        ),
        make_obligation(
            "p1", source_family_id=F_PRE, closure_status="open",
            satisfaction_status="unknown", open_reason_code="missing_artifact_evidence",
        ),
    ])


def _coarse_set_after_budget(skill_families, *, budget=2, batch=1):
    """跑 budget×batch 轮分批，返回最终覆盖到的 fine 家族经 crosswalk 映射的 coarse 集。"""
    cw = _crosswalk()
    full = _build_full_real()
    ctl = PagedClosureController(
        skill_families=skill_families, crosswalk=cw,
        query_budget=budget, batch_families=batch,
    )
    last = None
    for _ in range(budget):
        last, _summary = ctl.advance(full)
    covered_fine = {
        str(o.source_family_id) for o in last.obligation_set.obligations
    }
    covered_coarse = {cw.coarse_of(f) for f in covered_fine}
    covered_coarse.discard(None)
    return covered_fine, covered_coarse, sorted(ctl.covered_families)


def test_end_to_end_family_recall_skill_lifts_from_zero():
    """W2 真值家族(coarse) = F_PRE 的 coarse。字典序下 F_PRE 排末位、预算 2 覆盖不到
    → 真值 coarse 不在覆盖集（recall=0）；skill 关注 F_PRE → set-cover 提首 → 覆盖到
    → 真值 coarse 进覆盖集（recall=1）。family_recall = |覆盖∩真值|/|真值| 的代理验证。"""
    cw = _crosswalk()
    # 前提锚定：三个 fine 各属不同 coarse，且 F_PRE 的 primary coarse = COARSE_PRE
    assert cw.coarse_of(F_PRE) == COARSE_PRE, "fixture 假设 F_PRE→COARSE_PRE 已失效，请核 crosswalk"
    c_ext, c_struct = cw.coarse_of(F_EXT), cw.coarse_of(F_STRUCT)
    assert len({c_ext, c_struct, COARSE_PRE}) == 3, "三 fine 应属 3 个不同 coarse"

    truth_coarse = {COARSE_PRE}

    # 无 skill：字典序 → F_PRE('mbis.preinspection...') 字典序排在 inspection.* 之后，
    # 预算 2 覆盖前 2 个（external / structural），漏掉 F_PRE。
    fine_no, coarse_no, cov_no = _coarse_set_after_budget(set())
    recall_no = len(coarse_no & truth_coarse) / len(truth_coarse)

    # 有 skill 关注 F_PRE：set-cover 把 F_PRE 代表提首 → 预算内必覆盖到。
    fine_sk, coarse_sk, cov_sk = _coarse_set_after_budget({F_PRE})
    recall_sk = len(coarse_sk & truth_coarse) / len(truth_coarse)

    assert recall_no == 0.0, f"无 skill 应漏掉真值家族 coarse，覆盖={cov_no} coarse={coarse_no}"
    assert recall_sk == 1.0, f"skill 应覆盖到真值家族 coarse，覆盖={cov_sk} coarse={coarse_sk}"
    assert recall_sk > recall_no, f"skill 应提升 family_recall：无={recall_no} 有={recall_sk}"


# ===========================================================================
# 回归（Codex HIGH-1）：分批未覆盖全部家族时绝不可 allow_stop
# ===========================================================================
def test_partial_coverage_never_allows_stop():
    """已覆盖子集恰好全清、但还有家族没看 → allow_stop 必须 False。

    否则会在未访问家族（可能含 open/blocked）前就允许出报告，违背 allow_stop
    唯一权威（只有全覆盖且全清才可停）。"""
    full = make_closure_result([
        make_obligation(
            "c1", source_family_id="fam.clean", closure_status="closed",
            satisfaction_status="satisfied",
        ),
        make_obligation(
            "p1", source_family_id="fam.open", closure_status="open",
            satisfaction_status="unknown", open_reason_code="missing_artifact_evidence",
        ),
    ])
    # 字典序 fam.clean < fam.open；预算 1 轮 × 1 家族 → 只覆盖 fam.clean（全清），fam.open 未访问
    ctl = PagedClosureController(
        skill_families=set(), crosswalk=None, query_budget=1, batch_families=1
    )
    r1, p1 = ctl.advance(full)
    assert set(ctl.covered_families) == {"fam.clean"}
    assert p1["closure_paging"]["remaining_families"] == 1
    assert r1.allow_stop is False, "分批未走完、子集恰好全清，allow_stop 必须 False（HIGH-1 回归）"
    assert r1.allow_report_generation is False
    assert r1.closure_summary.allow_stop is False
    assert r1.closure_summary.stop_reason == "paged_closure_incomplete"


def test_zero_budget_empty_coverage_never_allows_stop():
    """预算 0（一轮没推进）→ 空覆盖子集 allow_stop 必须 False。

    空 obligation 集 summarize 天然 allow_stop=True，绝不能当成可停。"""
    full = make_closure_result([
        make_obligation(
            "c1", source_family_id="fam.clean", closure_status="closed",
            satisfaction_status="satisfied",
        ),
    ])
    ctl = PagedClosureController(
        skill_families=set(), crosswalk=None, query_budget=0, batch_families=1
    )
    r, _p = ctl.advance(full)
    assert ctl.exhausted is True
    assert r.allow_stop is False, "空覆盖绝不可停（HIGH-1 回归）"
    assert r.allow_report_generation is False


def test_full_clean_coverage_allows_stop():
    """对照：分批走完全部家族且全清 → allow_stop 应 True（覆盖完整时不误杀）。"""
    full = make_closure_result([
        make_obligation(
            "c1", source_family_id="fam.a", closure_status="closed",
            satisfaction_status="satisfied",
        ),
        make_obligation(
            "c2", source_family_id="fam.b", closure_status="closed",
            satisfaction_status="satisfied",
        ),
    ])
    ctl = PagedClosureController(
        skill_families=set(), crosswalk=None, query_budget=3, batch_families=1
    )
    last = None
    for _ in range(2):  # 2 家族、2 轮覆盖全
        last, _p = ctl.advance(full)
    assert set(ctl.covered_families) == {"fam.a", "fam.b"}
    assert last.allow_stop is True, "全覆盖且全清应允许停机"


if __name__ == "__main__":  # 允许直接 python 跑（确定性自检）
    raise SystemExit(pytest.main([__file__, "-q"]))
