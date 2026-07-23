"""分批闭包预算（EVO_CLOSURE_QUERY_BUDGET）差异机制核心算法。

== 这是什么 ==
skills-evo 实验里真正拉开"探索版 vs 满血版"差距的差异杠杆，**不是** LLM 工具
调用上限（max_tool_iterations），而是「闭包查询轮数预算 + skill 家族排序」：

- 满血版（资源充足天花板）：一次 ``validate_building_closure`` 全判全部家族，
  family_recall 天花板 = 1.0。
- evo 探索版：agent 多轮调 ``run_closure_verification``，每轮只推进一批家族
  （分批返回、不一次全给），受轮数预算约束；最终 closure_result 只覆盖 agent
  实际翻到的家族。覆盖家族 ∩ W2 真值家族 / W2 真值家族 = family_recall，受翻页
  深度 + 家族排序影响。
- skill 价值落点：active skill 的 ``scope.rule_families``（fine 家族）经
  family_crosswalk 映射出 anchor coarse；排序时每个 anchor coarse 选 1 个代表
  fine 提到队首（coarse 级 set-cover 去冗余）→ 预算内优先覆盖更多高价值 coarse
  → family_recall 提升。无 active skill / crosswalk 缺失 → 纯字典序（baseline /
  trace_only / policy_only 行为不变）。

诚实声明：闭包计算本身是确定性纯 Python（非实验瓶颈），全量在内部首次算一次
缓存（天花板客观存在）；分批模拟的是「受限预算内 agent 确认覆盖了多少家族」
（LLM 工具调用轮数才是受限资源）。family 锚点最终须由 skill induction 学来，
本模块只负责"给定锚点 fine 家族后如何排序 + 分批推进"。

== 为什么抽出来 ==
此前这套算法只活在 gitignored 草稿 ``杂物箱/run_paired_real_pipeline.py`` 的
patch C（module-level monkey-patch ``_llm_orch._execute_tool``）里，命脉不进版本库
就不可复现。本模块把核心算法忠实提炼成纯函数 + 显式状态控制器，进 src 可测可复现。

== 与草稿 / wave-3 完整接线的关系 ==
- 本模块只是"保命"：搬出算法 + 确定性测试，**不接主编排**。
- 草稿 patch C 通过 monkey-patch 偷塞分批状态到 ``LLMSessionState``
  （``state._closure_full`` / ``_closure_family_order`` / ``_closure_covered_families``
  / ``_closure_rounds`` 等动态属性）。本模块的 :class:`PagedClosureController`
  **显式持有**这些状态，不往会话状态偷塞字段。
- 真正把控制器接进 ``agent/llm_orchestrator.py`` 的 ``_execute_tool`` 主循环，
  替换草稿那套 monkey-patch，是 wave-3 完整方案的事，本次不动现有 src。

依赖（签名已核）：
- ``eval.mapper``：``FamilyCrosswalk.coarse_of(fine) -> Optional[str]`` /
  ``load_crosswalk`` / ``default_crosswalk_path``
- ``closure.validator.summarize(obligations, guard_result, schema_validation_passed=True)
  -> ClosureSummary``
- ``contracts``：``ClosureValidationResult``（pydantic v2，``.model_copy(update=)`` /
  ``.obligation_set.obligations`` / ``obligation.source_family_id`` /
  ``.high_risk_items``）、``SkillScope.rule_families``
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from evo_agent_baseline.contracts import ClosureValidationResult


# ---------------------------------------------------------------------------
# 1) skill 关注家族汇总（草稿 _skill_relevant_families，:1868-1877）
# ---------------------------------------------------------------------------
def skill_relevant_families(active_skills: List[Any]) -> Set[str]:
    """汇总 active skills 的 ``scope.rule_families``（fine family_id 集合）。

    每个 skill 的 ``scope.rule_families`` 是 induction 学来的关注 fine 家族；这里
    并集成集合。无 skill / 无 scope / 空列表 → 空集（退化到字典序）。
    """
    fams: Set[str] = set()
    for sk in active_skills or []:
        scope = getattr(sk, "scope", None)
        if scope is None:
            continue
        for fam in (getattr(scope, "rule_families", None) or []):
            fams.add(str(fam))
    return fams


# ---------------------------------------------------------------------------
# 2) coarse 级 set-cover 去冗余排序（草稿 _order_families_skill_aware，:2136-2161）
# ---------------------------------------------------------------------------
def order_families_set_cover(
    family_ids: List[str],
    skill_families: Set[str],
    crosswalk: Any,
) -> List[str]:
    """coarse 级 set-cover 家族排序（EXP-008 确定性闭环验证的正确 skill 机制）。

    机制：``skill_families``（fine）经 ``crosswalk.coarse_of`` 映射出 anchor coarse
    （induction 学来的高价值 coarse）；排序时遍历字典序的全部 fine 家族，每个
    anchor coarse 只选**第一个**遇到的 fine 当代表提到队首（去冗余），同 anchor
    coarse 的冗余 fine 与非 anchor fine 一起排到代表之后 → budget 内覆盖更多不同的
    高价值 coarse。

    为何 set-cover 而非简单 partition-to-front：后者在固定 budget 下零和（把 N 个同
    coarse 的 fine 全提前只覆盖 1 个 coarse、挤掉别的高价值 coarse），且锚点 fine
    楼型特定不泛化。set-cover 每 coarse 留 1 代表，预算花在"覆盖更多不同 coarse"上。

    退化：``skill_families`` 为空 / ``crosswalk`` 为 None / 锚点 coarse 全空 → 纯
    family_id 字典序（baseline / trace_only / policy_only 行为不变）。

    本函数不就地改入参，返回新 list；内部对 ``family_ids`` 先做 ``sorted(key=str)``
    保证确定性（同 anchor coarse 的代表是字典序最小的那个 fine）。
    """
    if not skill_families or crosswalk is None:
        return sorted(family_ids, key=str)

    anchor_coarse = {crosswalk.coarse_of(f) for f in skill_families}
    anchor_coarse.discard(None)
    if not anchor_coarse:
        return sorted(family_ids, key=str)

    seen: Set[Optional[str]] = set()
    reps: List[str] = []
    others: List[str] = []
    for f in sorted(family_ids, key=str):
        c = crosswalk.coarse_of(str(f))
        if c in anchor_coarse and c not in seen:
            reps.append(f)  # 该 anchor coarse 的代表 fine（去冗余）
            seen.add(c)
        else:
            others.append(f)
    return reps + others


# ---------------------------------------------------------------------------
# 3) 子集重建（草稿 _rebuild_closure_subset，:2164-2182）
# ---------------------------------------------------------------------------
def rebuild_closure_subset(
    full_result: ClosureValidationResult,
    subset_obligations: List[Any],
    *,
    coverage_complete: bool = True,
) -> ClosureValidationResult:
    """用「已覆盖家族」的 obligation 子集重建 ``ClosureValidationResult``。

    从全量 result ``model_copy`` 出新 result（不改原全量缓存），复用
    ``closure.validator.summarize`` 按子集重算 ``closure_summary``；
    ``high_risk_items`` 过滤到已覆盖家族。

    ``coverage_complete``：本子集是否已覆盖全部待判家族。**False 时强制
    ``allow_stop=False``**（``stop_reason=paged_closure_incomplete``）——分批未走完时
    未访问家族可能含 open/blocked，绝不能因"已覆盖子集恰好全清"（甚至空子集）就报
    可停，违背 allow_stop 唯一权威（只有全覆盖且全清才可停）。默认 True：直接调用者
    自负完整性判断；分批控制器 :class:`PagedClosureController` 会按实际覆盖传 False。

    guard 固定为 ``forbidden_source_check_passed=True``：全量首次算时已过 forbidden
    source guard，子集只是其子集，不引入新违规来源。
    """
    from evo_agent_baseline.closure.validator import summarize as _summarize_obls

    guard = {"forbidden_source_check_passed": True}
    new_summary = _summarize_obls(
        subset_obligations, guard, schema_validation_passed=True
    )
    # 分批未覆盖全部家族 → 子集再干净（甚至空）也不可停：防 advance 在未访问家族前
    # 就允许出报告（Codex HIGH-1）。
    allow_stop = bool(new_summary.allow_stop) and coverage_complete
    if new_summary.allow_stop and not coverage_complete:
        new_summary = new_summary.model_copy(
            update={"allow_stop": False, "stop_reason": "paged_closure_incomplete"}
        )
    new_obl_set = full_result.obligation_set.model_copy(
        update={"obligations": list(subset_obligations)}
    )
    covered = {str(getattr(o, "source_family_id", "")) for o in subset_obligations}
    hr = [
        h
        for h in full_result.high_risk_items
        if str(h.get("source_family_id", "")) in covered
    ]
    return full_result.model_copy(
        update={
            "obligation_set": new_obl_set,
            "closure_summary": new_summary,
            "allow_stop": allow_stop,
            "allow_report_generation": allow_stop,
            "high_risk_items": hr,
        }
    )


# ---------------------------------------------------------------------------
# 4) 分批预算推进控制器（草稿 patch C 状态机，:2216-2260；状态从偷塞
#    LLMSessionState 改为本类显式持有）
# ---------------------------------------------------------------------------
class PagedClosureController:
    """闭包分批预算推进控制器：显式持有分批状态，按轮数预算逐批推进家族覆盖。

    一个建筑一个控制器实例。首次 :meth:`advance` 缓存全量 result、用
    :func:`order_families_set_cover` 排家族序、初始化分批状态；之后每次 advance
    推进 ``batch_families`` 个未覆盖家族、重建子集 result；轮数用尽后 advance
    返回当前子集 + ``budget_exhausted=True``、不再推进。

    与草稿差异：草稿把 ``_closure_full`` / ``_closure_family_order`` /
    ``_closure_covered_families`` / ``_closure_rounds`` 当动态属性塞进
    ``LLMSessionState``；本类把它们作为实例属性显式持有，不污染会话状态。

    参数
    ----
    skill_families:
        active skill 关注的 fine 家族集合（见 :func:`skill_relevant_families`）。
    crosswalk:
        fine→coarse 对照表（``FamilyCrosswalk``）；None → set-cover 退化字典序。
    query_budget:
        轮数预算（最多几次 advance 真正推进）。对应 ``EVO_CLOSURE_QUERY_BUDGET``。
    batch_families:
        每轮覆盖几个家族。对应 ``EVO_CLOSURE_BATCH_FAMILIES``（草稿默认 3）。
    """

    def __init__(
        self,
        *,
        skill_families: Optional[Set[str]] = None,
        crosswalk: Any = None,
        query_budget: int = 2,
        batch_families: int = 3,
    ) -> None:
        self.skill_families: Set[str] = set(skill_families or set())
        self.crosswalk = crosswalk
        self.query_budget = int(query_budget)
        self.batch_families = max(1, int(batch_families))

        # 分批状态（首次 advance 初始化）
        self._full: Optional[ClosureValidationResult] = None
        self._fam_to_obls: Dict[str, List[Any]] = {}
        self.family_order: List[str] = []
        self.covered_families: List[str] = []
        self.rounds: int = 0
        # 最近一次 advance 重建出的子集 result（预算用尽前为 None 也会补空子集）
        self.current_result: Optional[ClosureValidationResult] = None

    # -- 内部：首次缓存全量 + 排家族序 + 初始化状态 --------------------------
    def _init_from_full(self, full: ClosureValidationResult) -> None:
        self._full = full
        fam_to_obls: Dict[str, List[Any]] = {}
        for o in full.obligation_set.obligations:
            fam_to_obls.setdefault(str(o.source_family_id), []).append(o)
        self._fam_to_obls = fam_to_obls
        self.family_order = order_families_set_cover(
            list(fam_to_obls.keys()), self.skill_families, self.crosswalk
        )
        self.covered_families = []
        self.rounds = 0

    @property
    def exhausted(self) -> bool:
        """轮数预算是否已用尽（已 advance 满 ``query_budget`` 轮）。"""
        return self.rounds >= self.query_budget

    def _paging_summary(self, *, exhausted: bool) -> Dict[str, Any]:
        """分批进度摘要 dict（草稿 _summarize_paged_closure 的 closure_paging 块 +
        当前子集统计；不含 LLM next_actions 文案，那是编排层的事）。"""
        total = len(self.family_order)
        covered = len(self.covered_families)
        summary = self.current_result.closure_summary if self.current_result else None
        return {
            "total_obligations": summary.total_obligations if summary else 0,
            "family_count": summary.family_count if summary else 0,
            "allow_stop": (
                self.current_result.allow_stop if self.current_result else False
            ),
            "closure_paging": {
                "covered_families": covered,
                "total_families": total,
                "remaining_families": total - covered,
                "rounds_used": self.rounds,
                "round_budget": self.query_budget,
                "batch_families_per_round": self.batch_families,
                "budget_exhausted": exhausted,
            },
        }

    def advance(
        self, full_result: ClosureValidationResult
    ) -> Tuple[Optional[ClosureValidationResult], Dict[str, Any]]:
        """推进一批家族覆盖，返回 ``(subset_result, paging_summary_dict)``。

        - 首次：缓存 ``full_result``、排家族序、初始化分批状态。后续调用沿用首次
          缓存的全量（``full_result`` 入参被忽略，与草稿一致——全量只算一次）。
        - 预算未用尽：推进 ``batch_families`` 个未覆盖家族、重建子集 result、轮数 +1。
        - 预算已用尽：不再推进，若还没有子集就补一个空子集，返回
          ``budget_exhausted=True``。

        返回的 ``subset_result`` 即 ``self.current_result``（只覆盖已确认家族的
        obligation）；``paging_summary_dict`` 含 ``closure_paging`` 进度块。
        """
        if self._full is None:
            self._init_from_full(full_result)

        # 预算用尽：不推进，确保至少有一个子集 result。一轮都没推进过 → 空覆盖、
        # 绝不可停（coverage_complete=False）。
        if self.exhausted:
            if self.current_result is None:
                self.current_result = rebuild_closure_subset(
                    self._full, [], coverage_complete=False
                )
            return self.current_result, self._paging_summary(exhausted=True)

        # 推进一批未覆盖家族
        remaining = [
            f for f in self.family_order if f not in self.covered_families
        ]
        batch = remaining[: self.batch_families]
        self.covered_families.extend(batch)
        self.rounds += 1

        subset_obls = [
            o
            for f in self.covered_families
            for o in self._fam_to_obls.get(f, [])
        ]
        # 是否已覆盖全部待判家族——未全覆盖时 rebuild 会强制 allow_stop=False。
        fully_covered = bool(self.family_order) and len(self.covered_families) >= len(
            self.family_order
        )
        self.current_result = rebuild_closure_subset(
            self._full, subset_obls, coverage_complete=fully_covered
        )
        return self.current_result, self._paging_summary(exhausted=False)
