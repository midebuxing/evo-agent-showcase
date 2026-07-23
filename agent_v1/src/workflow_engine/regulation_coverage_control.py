"""W2 法规映射层 coverage-controlled rejection（W2-007 批次 D 2026-05-21）.

按 W2 spec 11_coverage_controlled_rejection.md 全章 229 行整章实施.

实施位置（spec 11 §3.1）：W2 phase 3 输出 List[NormativeProjection] 之后、
W2 phase 4 batch 聚合（execute_projection_batch_v2）之前的 accept/reject filter.

3 类 over-sampling bucket（spec 11 §2）：
  - near_threshold：fragment 含 ≥1 项 ThresholdEval.regime_tag ∈
    {near_below, near_above, exact_threshold}
  - neighbor_family_overlap：matched_families 含 ≥2 个 applicability_score >= 0.5 的
    ProjectionFamilyEval，或 unknown_reason_code == multi_family_conflict
  - recoverable_missing：unknown_reason_code ∈ {binding_registry_gap / unit_incompatible /
    projection_binding_incompatible / measurement_family_unimplemented /
    method_class_unimplemented}，或 sidecar_join_status ∈ {partial, unavailable}

排除（不算 recoverable_missing；归 unrecoverable_unknown_control）：
  unknown_reason_code ∈ {no_known_family_match / coverage_unimplemented_domain /
  unsupported_material_system / unsupported_component_type / unsupported_damage_pattern /
  unsupported_location_context / sidecar_only_fact_pattern}

3 条硬约束（spec 11 §3.2 / §3.3 / §4）：
  1. per-sample rejection trace **不** 进 NormativeProjection 字段（NI-013）
  2. coverage target ratio **不作** evo-agent feature（NI-004）
  3. rejection reason **不回传** W1（NI-002 rule-blind）

baseline target ratio 数值与 accept/reject 算法细节为 spec 未规定的工程决策；
默认 profile CCP-MBIS-V1 写在 DEFAULT_COVERAGE_CONTROL_PROFILE，留 follow-up trace
（DEBT-031 gap 4 / target ratio 数值待 spec 明确）.

DEBT-044 修根（2026-06-11）——candidate 粒度 + 配额方向两处对齐 spec：
  1. candidate 粒度 = 楼级（一个 W1 candidate = 一栋 building world）：
     spec 11 §3.3 "外层编排重新请求一个新的 W1 candidate"——W1 的生成单元是
     building world，无单 fragment 重生成入口；楼内裁剪会把被接受楼的参考真值
     砍残（DEBT-044：每楼 4 candidate 砍剩 1，下游完整闭包核验无法进行）。
     accept/reject 以楼为单位：被接受的楼保留全部 fragment projection（真值完整），
     被拒的楼整楼不进 accepted batch。
  2. 配额方向 = 过采桶是地板不是天花板：spec 11 §2.1 唯一 worked example
     "已有 35% → reject 当前 far-threshold case"——rejection 落在 baseline
     （far-threshold）case 上，3 个过采桶永不因"超额"被截断；
     unrecoverable_unknown_control 是上限桶（spec 11 §2.3 "占比应控制"）；
     baseline_distribution 是削减池。
     旧实现把 target ratio 当 per-bucket 上限截断过采桶本身（方向反了），
     且配额按 ratio×N 设计为批级却被 per-building（N=4）调用，
     两层叠加 → 每楼 accepted 1 / rejected 3。

  批级主入口：apply_coverage_control_rejection_building_level（validation.py
  在收齐全部楼的全量 candidate 后调一次）。
  旧入口 apply_coverage_control_rejection 保签名/metadata 契约，语义改为
  "单楼（单 candidate）视角"：单楼调用没有批内分布可参照（spec 11 §1.2 原则二
  "按 batch 内 NormativeProjection 分布判断"），不做任何裁剪、全量接受 +
  出楼级分类 metadata。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

__all__ = [
    "BUCKET_NAMES",
    "BucketName",
    "EDGE_OVERSAMPLING_BUCKETS",
    "RECOVERABLE_UNKNOWN_REASON_CODES",
    "UNRECOVERABLE_UNKNOWN_REASON_CODES",
    "NEIGHBOR_OVERLAP_SCORE_THRESHOLD",
    "DEFAULT_COVERAGE_CONTROL_PROFILE",
    "DEFAULT_BUCKET_DEFINITION_VERSION",
    "classify_projection_buckets",
    "classify_building_primary_bucket",
    "is_near_threshold",
    "is_neighbor_family_overlap",
    "is_recoverable_missing",
    "is_unrecoverable_unknown",
    "apply_coverage_control_rejection",
    "apply_coverage_control_rejection_building_level",
    "build_coverage_control_metadata",
]


# spec 11 §3.2：5 个 bucket 名（含 baseline_distribution + unrecoverable_unknown_control 两个隐式 bucket）.
BUCKET_NAMES: Tuple[str, ...] = (
    "near_threshold",
    "neighbor_family_overlap",
    "recoverable_missing",
    "baseline_distribution",
    "unrecoverable_unknown_control",
)

try:
    from typing import Literal as _Literal
    BucketName = _Literal[
        "near_threshold",
        "neighbor_family_overlap",
        "recoverable_missing",
        "baseline_distribution",
        "unrecoverable_unknown_control",
    ]
except ImportError:  # pragma: no cover
    BucketName = str  # type: ignore


# spec 11 §2.3：recoverable_missing 是 binding 层 gap（理论可补 registry / alias / unit 转换）.
RECOVERABLE_UNKNOWN_REASON_CODES: Set[str] = {
    "binding_registry_gap",
    "unit_incompatible",
    "projection_binding_incompatible",
    "measurement_family_unimplemented",
    "method_class_unimplemented",
}

# spec 11 §2.3：unrecoverable 是设计/业务层不适用，不属 recoverable.
UNRECOVERABLE_UNKNOWN_REASON_CODES: Set[str] = {
    "no_known_family_match",
    "coverage_unimplemented_domain",
    "unsupported_material_system",
    "unsupported_component_type",
    "unsupported_damage_pattern",
    "unsupported_location_context",
    "sidecar_only_fact_pattern",
}

# spec 11 §2.2 配置化 threshold（spec 用语 "如阈值 0.5"，本处取 0.5 作 baseline）.
# ⏳ follow-up：等 spec / DEBT-031 gap 4 明确具体阈值数值再调.
NEIGHBOR_OVERLAP_SCORE_THRESHOLD: float = 0.5

# spec 11 §2.1：near_threshold regime_tag 3 enum.
NEAR_THRESHOLD_REGIME_TAGS: Set[str] = {
    "near_below",
    "near_above",
    "exact_threshold",
}

# spec 11 §2.3：recoverable sidecar_join_status 2 enum.
RECOVERABLE_SIDECAR_JOIN_STATUSES: Set[str] = {"partial", "unavailable"}

# spec 11 §1.1 / §2：3 个 over-sampling 桶（a8 §4 第五件 "过采" 三件）.
# DEBT-044 修根：这 3 桶是地板（floor）不是天花板——spec 11 §2.1 example
# "已有 35% → reject 当前 far-threshold case"，rejection 只落 baseline /
# unrecoverable，过采桶候选永不被截断.
EDGE_OVERSAMPLING_BUCKETS: Tuple[str, ...] = (
    "near_threshold",
    "neighbor_family_overlap",
    "recoverable_missing",
)


# spec 11 §3.2 / §3.1：default profile id + target ratio + bucket definition version.
# ⏳ follow-up：spec 没给具体数值，默认 profile 为工程占位，留 DEBT-031 gap 4 trace.
# - 默认 target ratio 取 a8 §4 第五件 "过采 near-threshold / neighbor-family overlap /
#   recoverable missing" 三类，按工程 baseline 设小目标占比（30% / 20% / 15%）；
#   baseline_distribution + unrecoverable_unknown_control 共 35%.
# - 数值随时可调，spec 11 §3.2 明确不暴露 internal target ratio 给 evo-agent.
DEFAULT_COVERAGE_CONTROL_PROFILE: Dict[str, Any] = {
    "coverage_control_profile_id": "CCP-MBIS-V1",
    "bucket_target_ratios": {
        "near_threshold": 0.30,
        "neighbor_family_overlap": 0.20,
        "recoverable_missing": 0.15,
        # baseline_distribution + unrecoverable_unknown_control 共 0.35.
        "baseline_distribution": 0.25,
        "unrecoverable_unknown_control": 0.10,
    },
    # LD-2 (2026-05-23)：原 `reject_priority_order` 配置键已移除——
    # apply_coverage_control_rejection 实现按 per-bucket 独立 quota 截断，
    # 不做跨 bucket 优先级拒绝（spec 11 §3 未要求具体算法），该键从未被读取。
}
# DEBT-044 修根（2026-06-11）bump v2：bucket 判定字段不变，但 metadata 候选计数
# 单位从 per-projection 改为 per-building（candidate = 楼，spec 11 §3.3）.
DEFAULT_BUCKET_DEFINITION_VERSION: str = "ccp.bucket.v2.2026-06-11"


# ---------- bucket 判定 helpers ----------


def is_near_threshold(projection: Dict[str, Any]) -> bool:
    """spec 11 §2.1：fragment 含 ≥1 项 ThresholdEval.regime_tag ∈
    {near_below, near_above, exact_threshold}.

    判定字段：matched_families[].threshold_evaluations[].regime_tag.
    """
    matched_families = projection.get("matched_families", []) or []
    for mf in matched_families:
        for thr in mf.get("threshold_evaluations", []) or []:
            if thr.get("regime_tag") in NEAR_THRESHOLD_REGIME_TAGS:
                return True
    return False


def is_neighbor_family_overlap(
    projection: Dict[str, Any],
    overlap_score_threshold: float = NEIGHBOR_OVERLAP_SCORE_THRESHOLD,
) -> bool:
    """spec 11 §2.2：matched_families 含 ≥2 个 applicability_score >= threshold
    的 ProjectionFamilyEval，或 unknown_reason_code == multi_family_conflict.
    """
    if projection.get("unknown_reason_code") == "multi_family_conflict":
        return True
    matched_families = projection.get("matched_families", []) or []
    high_score_count = 0
    for mf in matched_families:
        try:
            score = float(mf.get("applicability_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if score >= overlap_score_threshold:
            high_score_count += 1
            if high_score_count >= 2:
                return True
    return False


def is_recoverable_missing(projection: Dict[str, Any]) -> bool:
    """spec 11 §2.3：unknown_reason_code ∈ RECOVERABLE_UNKNOWN_REASON_CODES，
    或 sidecar_join_status ∈ {partial, unavailable}.

    注意：unrecoverable unknown 在调用方走 is_unrecoverable_unknown 分流，
    不进此 bucket（即使 sidecar_join_status=unavailable 但 unknown_reason_code
    属 unrecoverable 也归 unrecoverable_unknown_control 而非 recoverable_missing）.
    """
    code = projection.get("unknown_reason_code")
    if code in UNRECOVERABLE_UNKNOWN_REASON_CODES:
        return False
    if code in RECOVERABLE_UNKNOWN_REASON_CODES:
        return True
    sjs = projection.get("sidecar_join_status")
    if sjs in RECOVERABLE_SIDECAR_JOIN_STATUSES:
        return True
    return False


def is_unrecoverable_unknown(projection: Dict[str, Any]) -> bool:
    """spec 11 §2.3 反面：unrecoverable unknown 设计/业务层不适用，归
    `unrecoverable_unknown_control` bucket（spec 11 §3.2 隐式第 5 bucket）.
    """
    return projection.get("unknown_reason_code") in UNRECOVERABLE_UNKNOWN_REASON_CODES


def classify_projection_buckets(
    projection: Dict[str, Any],
    overlap_score_threshold: float = NEIGHBOR_OVERLAP_SCORE_THRESHOLD,
) -> List[str]:
    """单 projection 命中 bucket 列表（可命中多 bucket，spec 11 §2 未禁止 overlap）.

    ⏳ follow-up：spec 11 没说一 fragment 命中多 bucket 怎么算 quota——本实现 quota
    按 "primary bucket"（_pick_primary_bucket 优先级 near_threshold > neighbor_family_overlap
    > recoverable_missing > unrecoverable_unknown_control > baseline_distribution）；
    classify 仍返回完整 bucket list 给 audit 用.

    Returns:
        命中 bucket 名 list；至少含一个（unrecoverable_unknown_control 或
        baseline_distribution 兜底）.
    """
    buckets: List[str] = []
    if is_near_threshold(projection):
        buckets.append("near_threshold")
    if is_neighbor_family_overlap(projection, overlap_score_threshold):
        buckets.append("neighbor_family_overlap")
    if is_recoverable_missing(projection):
        buckets.append("recoverable_missing")
    if is_unrecoverable_unknown(projection):
        buckets.append("unrecoverable_unknown_control")
    if not buckets:
        buckets.append("baseline_distribution")
    return buckets


def _pick_primary_bucket(buckets: Iterable[str]) -> str:
    """quota 视角 primary bucket（优先 over-sampled 三类 > unrecoverable > baseline）.

    spec 11 §2 没明确多命中时归哪一桶；按 over-sampling 目的（near_threshold /
    neighbor_family_overlap / recoverable_missing 是 "过采" 三件 spec §1.1 line 26）
    取优先级 near_threshold > neighbor_family_overlap > recoverable_missing >
    unrecoverable_unknown_control > baseline_distribution.
    """
    priority = (
        "near_threshold",
        "neighbor_family_overlap",
        "recoverable_missing",
        "unrecoverable_unknown_control",
        "baseline_distribution",
    )
    bucket_set = set(buckets)
    for name in priority:
        if name in bucket_set:
            return name
    return "baseline_distribution"


def classify_building_primary_bucket(
    projections: List[Dict[str, Any]],
    overlap_score_threshold: float = NEIGHBOR_OVERLAP_SCORE_THRESHOLD,
) -> str:
    """DEBT-044 修根：楼级 primary bucket——楼内全部 fragment projection 命中桶
    取并集，再按 _pick_primary_bucket 优先级归一桶.

    candidate = 楼（spec 11 §3.3 "外层编排重新请求一个新的 W1 candidate"，
    W1 生成单元是 building world）；楼内任一 fragment 命中过采桶即把整楼
    归入该过采桶（过采意图：边界 case 所在的楼整楼保进 batch）.

    空 projections（楼无含 mechanism 的 fragment / 全 C025 reject）归
    baseline_distribution.
    """
    union: Set[str] = set()
    for proj in projections:
        union.update(classify_projection_buckets(proj, overlap_score_threshold))
    if not union:
        return "baseline_distribution"
    return _pick_primary_bucket(union)


# ---------- accept / reject filter ----------


def apply_coverage_control_rejection(
    projections: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """单楼（单 candidate）视角的 coverage control 入口——DEBT-044 修根后语义.

    输入是**一栋楼**的全量 fragment projection 列表（per-world 调用场景，
    即 build_normative_projections_for_world 的输出）。

    DEBT-044 修根（2026-06-11）：
      - 旧实现把批级配额（ratio × N）套在单楼 N=4 的列表上做 per-fragment 截断，
        每楼 4 candidate 砍剩 1（accepted 1 / rejected 3 全落 near_threshold 桶），
        被接受楼的参考真值残缺——违反 spec 11 §1.2 原则二 "按 batch 内
        NormativeProjection 分布判断"（单楼调用没有批内分布可参照）。
      - 新语义：单楼 = 单 candidate（spec 11 §3.3 candidate = W1 candidate =
        building world），不做任何楼内裁剪，全量接受 + 出楼级分类 metadata。
        批级真正的 accept/reject 走 apply_coverage_control_rejection_building_level
        （validation.py 收齐全部楼后调一次）。

    硬约束（不变）：
      - 不修改 projection 字段（spec 11 §1.2 原则一）.
      - rejection reason 不回传 W1（spec 11 §3.3）.
      - per-sample rejection trace 不进 NormativeProjection（spec 11 §3.2）.

    Args:
        projections: 一栋楼的 NormativeProjection dict 列表（model_dump 形式）.
        profile: coverage control profile（默认 DEFAULT_COVERAGE_CONTROL_PROFILE）.

    Returns:
        (accepted_projections, metadata_dict).
        - accepted_projections == 输入全量（保 W1 顺序，无楼内裁剪）.
        - metadata_dict 候选计数单位 = 楼（本楼 primary bucket 计 1）；
          字段同 CoverageControlBatchMetadata 6 字段契约（spec 11 §3.2）.
    """
    profile = profile or DEFAULT_COVERAGE_CONTROL_PROFILE

    if not projections:
        return [], build_coverage_control_metadata(
            profile=profile,
            raw_counts=Counter(),
            accepted_counts=Counter(),
            rejected_counts=Counter(),
        )

    primary = classify_building_primary_bucket(projections)
    raw_counts: Counter[str] = Counter({primary: 1})
    accepted_counts: Counter[str] = Counter({primary: 1})
    metadata = build_coverage_control_metadata(
        profile=profile,
        raw_counts=raw_counts,
        accepted_counts=accepted_counts,
        rejected_counts=Counter(),
    )
    # list() 拷贝防 caller 改列表本身；元素 dict 不拷贝也不修改（原则一）.
    return list(projections), metadata


def apply_coverage_control_rejection_building_level(
    per_world_candidates: List[Tuple[str, List[Dict[str, Any]]]],
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """spec 11 §3.1 批级 accept/reject filter 主入口（DEBT-044 修根后）.

    candidate 粒度 = 楼（spec 11 §3.3 "W2 丢弃当前 candidate，不写入 accepted
    batch / 外层编排重新请求一个新的 W1 candidate"——W1 生成单元是 building
    world）。被接受的楼保留**全部** fragment projection（参考真值完整）；
    被拒的楼整楼不进 accepted batch。

    算法（spec 11 §3 只给过采意图 + target ratio，跨桶具体算法是工程决策）：
      1. 每楼按 classify_building_primary_bucket 归一桶；
         记录 raw_candidate_bucket_counts（单位 = 楼）.
      2. 3 个过采桶（EDGE_OVERSAMPLING_BUCKETS）是地板：全量接受，永不截断
         （spec 11 §2.1 example "已有 35% → reject 当前 far-threshold case"，
         rejection 只落非过采候选）.
      3. unrecoverable_unknown_control 是上限桶（spec 11 §2.3 "unrecoverable
         unknown 占比应控制，避免 batch 全是死局 case"）：
         quota = min(raw, max(1, round(ratio × 楼总数)))，按输入顺序保头部.
      4. baseline_distribution 是削减池：削减到让每个**非空**过采桶在 accepted
         batch 中的占比 ≥ 其 target ratio（即 accepted 总数 ≤ min_e
         floor(count_e / ratio_e)）；无非空过采桶时不削减（没有过采压力时
         不销毁数据）。空过采桶的地板无法靠削减满足（候选不存在），跳过——
         补齐路径是 spec 11 §3.3 的 W1 重采样，由外层编排自行决定（本函数不实现，
         ⏳ 见 DEBT-031 gap 4）.
      5. 决策全程楼级、保输入顺序、确定性（同输入同输出）.

    硬约束（spec 11 §3.2 / §3.3 / §4）：
      - 不修改 projection 字段；不裁剪楼内 fragment.
      - rejection reason / bucket 信息不回传 W1（返回值只含 world_id 取舍结果，
        caller 不得把 bucket / ratio 传给 W1）.
      - per-sample rejection trace 不进 NormativeProjection.

    Args:
        per_world_candidates: [(world_id, 该楼全量 candidate projections), ...]，
            保 W1 batch 输入顺序.
        profile: coverage control profile（默认 DEFAULT_COVERAGE_CONTROL_PROFILE）.

    Returns:
        (accepted_world_ids, per_world_metadata, batch_metadata)
        - accepted_world_ids: 被接受楼的 world_id 列表（保输入顺序）.
        - per_world_metadata: world_id → 该楼 6 字段 metadata（候选计数单位 = 楼，
          本楼 raw 计 1、accepted/rejected 按取舍落 1；phase 4 聚合求和后即批级计数）.
        - batch_metadata: 批级 6 字段 metadata（= per-world 求和）.
    """
    profile = profile or DEFAULT_COVERAGE_CONTROL_PROFILE
    bucket_ratios: Dict[str, float] = dict(profile.get("bucket_target_ratios", {}))

    if not per_world_candidates:
        empty_meta = build_coverage_control_metadata(
            profile=profile,
            raw_counts=Counter(),
            accepted_counts=Counter(),
            rejected_counts=Counter(),
        )
        return [], {}, empty_meta

    # step 1：每楼归一桶（保输入顺序）.
    total_buildings = len(per_world_candidates)
    primary_per_idx: List[str] = []
    bucket_to_indices: Dict[str, List[int]] = defaultdict(list)
    for idx, (_world_id, candidates) in enumerate(per_world_candidates):
        primary = classify_building_primary_bucket(candidates)
        primary_per_idx.append(primary)
        bucket_to_indices[primary].append(idx)
    raw_counts: Counter[str] = Counter(primary_per_idx)

    accepted_idx_set: Set[int] = set()

    # step 2：过采桶是地板——全量接受.
    edge_kept_total = 0
    for bucket in EDGE_OVERSAMPLING_BUCKETS:
        indices = bucket_to_indices.get(bucket, [])
        accepted_idx_set.update(indices)
        edge_kept_total += len(indices)

    # step 3：unrecoverable_unknown_control 上限桶.
    unrec_indices = bucket_to_indices.get("unrecoverable_unknown_control", [])
    unrec_kept = 0
    if unrec_indices:
        unrec_ratio = float(bucket_ratios.get("unrecoverable_unknown_control", 0.0))
        unrec_quota = min(
            len(unrec_indices),
            max(1, int(round(unrec_ratio * total_buildings))),
        )
        accepted_idx_set.update(unrec_indices[:unrec_quota])
        unrec_kept = unrec_quota

    # step 4：baseline 削减池——满足非空过采桶地板.
    baseline_indices = bucket_to_indices.get("baseline_distribution", [])
    accepted_cap: Optional[int] = None
    for bucket in EDGE_OVERSAMPLING_BUCKETS:
        count_e = raw_counts.get(bucket, 0)
        ratio_e = float(bucket_ratios.get(bucket, 0.0))
        if count_e == 0 or ratio_e <= 0.0:
            continue  # 空桶 / 无目标比：地板无法满足（候选不存在）或无约束，跳过.
        cap_e = int(math.floor(count_e / ratio_e + 1e-9))
        accepted_cap = cap_e if accepted_cap is None else min(accepted_cap, cap_e)
    if accepted_cap is None:
        baseline_kept = len(baseline_indices)  # 无过采压力：不销毁数据.
    else:
        baseline_kept = max(0, min(
            len(baseline_indices),
            accepted_cap - edge_kept_total - unrec_kept,
        ))
    accepted_idx_set.update(baseline_indices[:baseline_kept])

    # step 5：保输入顺序输出 + 计数（单位 = 楼）.
    accepted_world_ids: List[str] = []
    accepted_counts: Counter[str] = Counter()
    rejected_counts: Counter[str] = Counter()
    per_world_metadata: Dict[str, Dict[str, Any]] = {}
    for idx, (world_id, _candidates) in enumerate(per_world_candidates):
        primary = primary_per_idx[idx]
        is_accepted = idx in accepted_idx_set
        if is_accepted:
            accepted_world_ids.append(world_id)
            accepted_counts[primary] += 1
        else:
            rejected_counts[primary] += 1
        per_world_metadata[world_id] = build_coverage_control_metadata(
            profile=profile,
            raw_counts=Counter({primary: 1}),
            accepted_counts=Counter({primary: 1} if is_accepted else {}),
            rejected_counts=Counter({} if is_accepted else {primary: 1}),
        )

    batch_metadata = build_coverage_control_metadata(
        profile=profile,
        raw_counts=raw_counts,
        accepted_counts=accepted_counts,
        rejected_counts=rejected_counts,
    )
    return accepted_world_ids, per_world_metadata, batch_metadata


def build_coverage_control_metadata(
    profile: Dict[str, Any],
    raw_counts: Counter,
    accepted_counts: Counter,
    rejected_counts: Counter,
) -> Dict[str, Any]:
    """spec 11 §3.2 `CoverageControlBatchMetadata` 6 字段 dataclass 构造.

    NI 注：public_report_note 不暴露 internal target ratio（spec 11 §3.2 + §4.2）；
    bucket counts 是 audit / 大汇报材料，不进 evo-agent feature pipeline.
    """
    profile_id = str(profile.get("coverage_control_profile_id", "CCP-MBIS-V1"))
    return {
        "coverage_control_profile_id": profile_id,
        "raw_candidate_bucket_counts": {
            bucket: int(raw_counts.get(bucket, 0)) for bucket in BUCKET_NAMES
        },
        "accepted_bucket_counts": {
            bucket: int(accepted_counts.get(bucket, 0)) for bucket in BUCKET_NAMES
        },
        "rejected_bucket_counts": {
            bucket: int(rejected_counts.get(bucket, 0)) for bucket in BUCKET_NAMES
        },
        "bucket_definition_version": DEFAULT_BUCKET_DEFINITION_VERSION,
        # spec 11 §3.2 / §4.2：public_report_note 只说做了边界覆盖控制，不暴露 internal target ratio.
        "public_report_note": (
            "batch coverage-controlled rejection applied; near-threshold / "
            "neighbor-family / recoverable-missing edge cases over-sampled; "
            "internal target ratios are not exposed."
        ),
    }
