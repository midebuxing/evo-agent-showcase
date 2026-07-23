"""evaluator mapping（spec §8.3）。

两件事：
- §8.3.1 agent obligation → family verdict：对同一 `(world_id, fragment_id,
  family)` 聚合 agent `Obligation`，按 closure/satisfaction 规约出
  `agent_family_verdict`，再结合 applicability audit 细分 not_applicable。
- §8.3.2 fine family → W2 coarse family：用 `family_crosswalk_v1.json` 把
  agent 侧 fine family（`Obligation.source_family_id`）映射到 W2 coarse family，
  以便和 W2 真值（coarse 粒度）对齐。

crosswalk 是 evaluator 配置，不进入 agent KG / 检索上下文（spec §8.3.2 / O-006）。

spec→code 单向：聚合规约逐字照 spec §8.3.1 伪代码，不自创分支。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from evo_agent_baseline.contracts import Obligation

# §8.3.1 规约出的 family verdict 取值。
# pass_or_not_applicable 是中间态，经 applicability audit 再细分为 pass / not_applicable。
FAMILY_VERDICT_VALUES = (
    "unknown",
    "fail",
    "pass",
    "not_applicable",
)


# ---------------------------------------------------------------------------
# §8.3.2 crosswalk 加载
# ---------------------------------------------------------------------------


class CrosswalkError(RuntimeError):
    """crosswalk 缺失 / schema 不符 / hard requirement 不过时抛出。

    spec §8.3.2：crosswalk 缺失时 evaluator 不能给 family-level score，
    应输出 `evaluation_status="blocked_missing_crosswalk"`；调用方据此处理。
    """


@dataclass
class FamilyCrosswalk:
    """fine family → W2 coarse family 的对照表（spec §8.3.2）。

    `fine_to_coarse` 用每个 fine family 的 **primary** coarse 归属
    （crosswalk JSON 的 `fine_family_assignments[].primary_coarse_family_id`）；
    多对多的次要归属保留在 `fine_to_secondary` 不丢信息（见任务说明）。
    """

    schema_version: str
    source_note: str
    coarse_family_ids: List[str]
    fine_to_coarse: Dict[str, str]                  # fine -> primary coarse
    fine_to_secondary: Dict[str, List[str]]         # fine -> [secondary coarse...]
    coarse_to_fine: Dict[str, List[str]]            # coarse -> [全部 fine 成员...]

    def coarse_of(self, fine_family_id: str) -> Optional[str]:
        """fine family → primary coarse family；未登记返回 None。"""
        return self.fine_to_coarse.get(fine_family_id)


def load_crosswalk(path: str) -> FamilyCrosswalk:
    """加载并校验 `family_crosswalk_v1.json`（spec §8.3.2 hard requirements）。

    spec §8.3.2 启动硬校验：
        assert crosswalk.schema_version == "family_crosswalk_v1"
        assert len({m.coarse_family_id for m in mappings}) == 16
        assert all(m.fine_family_ids for m in mappings)
    """
    if not os.path.isfile(path):
        raise CrosswalkError(f"crosswalk 文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CrosswalkError(f"crosswalk 文件不可解析: {path} ({exc})") from exc

    schema_version = raw.get("schema_version")
    if schema_version != "family_crosswalk_v1":
        raise CrosswalkError(
            f"crosswalk schema_version 必须为 family_crosswalk_v1，实为 {schema_version!r}"
        )

    mappings = raw.get("mappings") or []
    coarse_ids = [m.get("coarse_family_id") for m in mappings]
    if len(set(coarse_ids)) != 16:
        raise CrosswalkError(
            f"crosswalk 必须含 16 个唯一 coarse_family_id，实为 {len(set(coarse_ids))}"
        )
    if not all(m.get("fine_family_ids") for m in mappings):
        raise CrosswalkError("crosswalk 每个 mapping 的 fine_family_ids 不得为空")

    coarse_to_fine: Dict[str, List[str]] = {
        m["coarse_family_id"]: list(m["fine_family_ids"]) for m in mappings
    }

    # primary / secondary 归属从 fine_family_assignments 取（权威的唯一归属来源）。
    assignments = raw.get("fine_family_assignments") or []
    fine_to_coarse: Dict[str, str] = {}
    fine_to_secondary: Dict[str, List[str]] = {}
    for a in assignments:
        fid = a.get("fine_family_id")
        primary = a.get("primary_coarse_family_id")
        if not isinstance(fid, str) or not isinstance(primary, str):
            raise CrosswalkError(f"crosswalk fine_family_assignments 条目非法: {a!r}")
        if primary not in coarse_to_fine:
            raise CrosswalkError(
                f"fine family {fid} 的 primary {primary} 不在 16 coarse 中"
            )
        fine_to_coarse[fid] = primary
        fine_to_secondary[fid] = list(a.get("secondary_coarse_family_ids") or [])

    return FamilyCrosswalk(
        schema_version=schema_version,
        source_note=raw.get("source_note", ""),
        coarse_family_ids=sorted(coarse_to_fine.keys()),
        fine_to_coarse=fine_to_coarse,
        fine_to_secondary=fine_to_secondary,
        coarse_to_fine=coarse_to_fine,
    )


def default_crosswalk_path() -> str:
    """随包发布的 `family_crosswalk_v1.json` 绝对路径。"""
    return os.path.join(os.path.dirname(__file__), "family_crosswalk_v1.json")


# ---------------------------------------------------------------------------
# §8.3.1 agent obligation → family verdict
# ---------------------------------------------------------------------------

# 聚合键：spec §8.3.1 "对同一 (world_id, fragment_id, family)"。
FamilyKey = Tuple[str, Optional[str], str]


@dataclass
class AgentFamilyVerdict:
    """一个 `(world_id, fragment_id, family)` 聚合出的 agent 判定（spec §8.3.1）。

    `family_id` 保留 agent 侧 fine family（`Obligation.source_family_id`）；
    `coarse_family_id` 是经 crosswalk 映射后的 W2 coarse family（未登记则 None）。
    """

    world_id: str
    fragment_id: Optional[str]
    family_id: str                       # agent 侧 fine family
    coarse_family_id: Optional[str]      # W2 coarse family（crosswalk 映射）
    verdict: str                         # FAMILY_VERDICT_VALUES 之一
    obligation_count: int
    obligation_ids: List[str] = field(default_factory=list)
    # 诊断用：聚合时观察到的 closure / satisfaction 取值集合。
    closure_statuses: List[str] = field(default_factory=list)
    satisfaction_statuses: List[str] = field(default_factory=list)


def _reduce_family_verdict(obligations: List[Obligation]) -> str:
    """spec §8.3.1 伪代码逐字实现 —— closure/satisfaction → family verdict。

    返回前两步的规约结果，可能是中间态 `pass_or_not_applicable`，
    由调用方再做 applicability audit 细分。
    """
    # if any(obligation.closure_status in {"open", "blocked"}): -> "unknown"
    if any(o.closure_status in {"open", "blocked"} for o in obligations):
        return "unknown"
    # elif any(obligation.satisfaction_status == "violated"): -> "fail"
    if any(o.satisfaction_status == "violated" for o in obligations):
        return "fail"
    # elif all(obligation.satisfaction_status in {"satisfied", "not_applicable"}):
    if all(
        o.satisfaction_status in {"satisfied", "not_applicable"} for o in obligations
    ):
        return "pass_or_not_applicable"
    # else: -> "unknown"
    return "unknown"


def _apply_applicability_audit(
    reduced_verdict: str, obligations: List[Obligation]
) -> str:
    """spec §8.3.1 applicability audit —— pass_or_not_applicable 细分。

    spec：
      - scope not_applicable → not_applicable
      - otherwise            → pass
    判据：family 内若存在 kind == "scope" 的义务且其
    `applicability_state == "not_applicable"`（或 `satisfaction_status ==
    "not_applicable"`），则整族 not_applicable，否则 pass。
    """
    if reduced_verdict != "pass_or_not_applicable":
        return reduced_verdict
    scope_obs = [o for o in obligations if o.kind == "scope"]
    scope_not_applicable = any(
        (o.applicability_state == "not_applicable")
        or (o.satisfaction_status == "not_applicable")
        for o in scope_obs
    )
    return "not_applicable" if scope_not_applicable else "pass"


def aggregate_agent_family_verdicts(
    obligations: Iterable[Obligation],
    crosswalk: Optional[FamilyCrosswalk] = None,
    exclude_kinds: Optional[set] = None,
) -> List[AgentFamilyVerdict]:
    """把 agent `Obligation` 列表聚合为 family-level verdict（spec §8.3.1 + §8.3.2）。

    Args:
        obligations: 一次 run 的全部义务（来自 `obligation_set.json`）。
        crosswalk: fine→coarse 对照表；None 时 `coarse_family_id` 留空
            （family-level 对齐需调用方另行处理，对应 spec §8.3.2
            `blocked_missing_crosswalk`）。

    聚合键 `(world_id, fragment_id, source_family_id)`，与 spec §8.3.1 一致。
    """
    groups: Dict[FamilyKey, List[Obligation]] = defaultdict(list)
    for ob in obligations:
        # 可核验子宇宙口径（2026-07-08 用户裁定门③选项3）：按 kind 剔除
        # spec 钦定无事实通道的义务类（专业判断/编排类动作）后再归约；
        # 全宇宙口径（exclude_kinds=None）原样保留为保守头条。
        if exclude_kinds and ob.kind in exclude_kinds:
            continue
        key: FamilyKey = (ob.world_id, ob.fragment_id, ob.source_family_id)
        groups[key].append(ob)

    results: List[AgentFamilyVerdict] = []
    for (world_id, fragment_id, family_id), obs in groups.items():
        reduced = _reduce_family_verdict(obs)
        verdict = _apply_applicability_audit(reduced, obs)
        coarse = crosswalk.coarse_of(family_id) if crosswalk is not None else None
        results.append(
            AgentFamilyVerdict(
                world_id=world_id,
                fragment_id=fragment_id,
                family_id=family_id,
                coarse_family_id=coarse,
                verdict=verdict,
                obligation_count=len(obs),
                obligation_ids=[o.obligation_id for o in obs],
                closure_statuses=sorted({o.closure_status for o in obs}),
                satisfaction_statuses=sorted({o.satisfaction_status for o in obs}),
            )
        )
    # 稳定排序，便于报告 diff。
    results.sort(key=lambda r: (r.world_id, r.fragment_id or "", r.family_id))
    return results


__all__ = [
    "FAMILY_VERDICT_VALUES",
    "CrosswalkError",
    "FamilyCrosswalk",
    "load_crosswalk",
    "default_crosswalk_path",
    "FamilyKey",
    "AgentFamilyVerdict",
    "aggregate_agent_family_verdicts",
]
