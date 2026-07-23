"""W2-007 (批次 D 2026-05-21) + DEBT-044 修根 (2026-06-11) tests：
spec 11 coverage-controlled rejection 整章实施.

DEBT-044 修根后语义：
  - candidate 粒度 = 楼（spec 11 §3.3 candidate = W1 candidate = building world）；
    被接受楼保留全部 fragment projection（参考真值完整），禁止楼内裁剪.
  - 过采 3 桶是地板不是天花板（spec 11 §2.1 example rejection 落 far-threshold/
    baseline case）；unrecoverable_unknown_control 是上限桶；baseline 是削减池.
  - 批级主入口 apply_coverage_control_rejection_building_level；
    旧入口 apply_coverage_control_rejection 改单楼视角（全量接受 + 楼级分类 metadata）.

覆盖：
  - 3 个 bucket 判定 helpers（near_threshold / neighbor_family_overlap / recoverable_missing）
  - 第 5 bucket unrecoverable_unknown_control 分流
  - classify_building_primary_bucket 楼级归桶
  - apply_coverage_control_rejection 单楼视角（无楼内裁剪）
  - apply_coverage_control_rejection_building_level 批级楼级取舍（地板/上限/削减池）
  - CoverageControlBatchMetadata 6 字段（spec 11 §3.2）
  - 集成 build_normative_projections_for_world（filter 开/关输出一致）
  - 集成 build_normative_projections_for_world_with_coverage_control 返 (list, metadata)
  - 集成 validation v2：每栋被接受楼保留全部 fragment 的 projection（DEBT-044 回归锁）
  - 集成 execute_projection_batch_v2 batch-level metadata 聚合
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from workflow_engine.regulation_coverage_control import (  # noqa: E402
    BUCKET_NAMES,
    DEFAULT_COVERAGE_CONTROL_PROFILE,
    EDGE_OVERSAMPLING_BUCKETS,
    NEIGHBOR_OVERLAP_SCORE_THRESHOLD,
    RECOVERABLE_UNKNOWN_REASON_CODES,
    UNRECOVERABLE_UNKNOWN_REASON_CODES,
    apply_coverage_control_rejection,
    apply_coverage_control_rejection_building_level,
    build_coverage_control_metadata,
    classify_building_primary_bucket,
    classify_projection_buckets,
    is_near_threshold,
    is_neighbor_family_overlap,
    is_recoverable_missing,
    is_unrecoverable_unknown,
)
from workflow_engine.regulation_projection_executor import (  # noqa: E402
    build_normative_projections_for_world,
    build_normative_projections_for_world_with_coverage_control,
    execute_projection_batch_v2,
)
from workflow_engine.regulation_projection_models import (  # noqa: E402
    CoverageControlBatchMetadata,
)
from workflow_engine.worldgen.generator import generate_world_bundle  # noqa: E402
from workflow_engine.worldgen.registry import _build_registry_bundle  # noqa: E402
from workflow_engine.worldgen.validation import (  # noqa: E402
    run_worldgenerator_fullcoverage_framework_v2,
)


def _make_projection(
    *,
    projection_id: str = "NP-T-W-F-00",
    regime_tags=None,
    family_scores=None,
    unknown_reason_code=None,
    sidecar_join_status: str = "available",
):
    """构造 NormativeProjection dict（minimum fields for bucket 判定）."""
    matched_families = []
    if family_scores is None:
        family_scores = [0.7]
    for idx, score in enumerate(family_scores):
        family_id = f"family_{idx}"
        threshold_evaluations = []
        if regime_tags and idx == 0:
            for tag in regime_tags:
                threshold_evaluations.append({
                    "rule_id": f"R{idx}",
                    "threshold_regime_id": f"R{idx}.t01",
                    "slot_id": f"slot_{idx}",
                    "operator": "<=",
                    "threshold_value": 1.0,
                    "observed_value": 0.5,
                    "regime_tag": tag,
                    "pass_bool": True,
                })
        matched_families.append({
            "family_id": family_id,
            "applicability_score": score,
            "applicability_state": "applicable",
            "trigger_ids": [],
            "rule_ids": [],
            "slot_role_map": {},
            "threshold_evaluations": threshold_evaluations,
            "verdict": "pass",
        })
    return {
        "projection_id": projection_id,
        "matched_families": matched_families,
        "unknown_reason_code": unknown_reason_code,
        "sidecar_join_status": sidecar_join_status,
    }


# ---------- bucket 判定 helpers tests（spec 11 §2）----------


class BucketHelperNearThresholdTests(unittest.TestCase):
    def test_near_below_hit(self):
        p = _make_projection(regime_tags=["near_below"])
        self.assertTrue(is_near_threshold(p))

    def test_near_above_hit(self):
        p = _make_projection(regime_tags=["near_above"])
        self.assertTrue(is_near_threshold(p))

    def test_exact_threshold_hit(self):
        p = _make_projection(regime_tags=["exact_threshold"])
        self.assertTrue(is_near_threshold(p))

    def test_far_below_miss(self):
        p = _make_projection(regime_tags=["far_below"])
        self.assertFalse(is_near_threshold(p))

    def test_far_above_miss(self):
        p = _make_projection(regime_tags=["far_above"])
        self.assertFalse(is_near_threshold(p))

    def test_empty_threshold_evaluations_miss(self):
        p = _make_projection()
        self.assertFalse(is_near_threshold(p))


class BucketHelperNeighborFamilyOverlapTests(unittest.TestCase):
    def test_two_high_score_families_hit(self):
        # 2 families 都 >= 0.5
        p = _make_projection(family_scores=[0.7, 0.6])
        self.assertTrue(is_neighbor_family_overlap(p))

    def test_one_high_one_low_miss(self):
        p = _make_projection(family_scores=[0.7, 0.3])
        self.assertFalse(is_neighbor_family_overlap(p))

    def test_three_high_score_families_hit(self):
        p = _make_projection(family_scores=[0.7, 0.6, 0.55])
        self.assertTrue(is_neighbor_family_overlap(p))

    def test_multi_family_conflict_unknown_reason_hit(self):
        # spec 11 §2.2 第 2 条：unknown_reason_code == multi_family_conflict 也命中
        p = _make_projection(
            family_scores=[0.3], unknown_reason_code="multi_family_conflict"
        )
        self.assertTrue(is_neighbor_family_overlap(p))

    def test_threshold_boundary_miss(self):
        # 阈值边界（0.5 == 0.5 是 >= 命中）
        p = _make_projection(family_scores=[0.5, 0.5])
        self.assertTrue(is_neighbor_family_overlap(p))

    def test_configurable_threshold(self):
        # spec 11 §2.2 "阈值 0.5" 提示是配置化的；用更高 threshold 验证
        p = _make_projection(family_scores=[0.55, 0.55])
        self.assertFalse(is_neighbor_family_overlap(p, overlap_score_threshold=0.7))


class BucketHelperRecoverableMissingTests(unittest.TestCase):
    def test_binding_registry_gap_hit(self):
        p = _make_projection(unknown_reason_code="binding_registry_gap")
        self.assertTrue(is_recoverable_missing(p))

    def test_unit_incompatible_hit(self):
        p = _make_projection(unknown_reason_code="unit_incompatible")
        self.assertTrue(is_recoverable_missing(p))

    def test_measurement_family_unimplemented_hit(self):
        p = _make_projection(unknown_reason_code="measurement_family_unimplemented")
        self.assertTrue(is_recoverable_missing(p))

    def test_method_class_unimplemented_hit(self):
        p = _make_projection(unknown_reason_code="method_class_unimplemented")
        self.assertTrue(is_recoverable_missing(p))

    def test_projection_binding_incompatible_hit(self):
        p = _make_projection(unknown_reason_code="projection_binding_incompatible")
        self.assertTrue(is_recoverable_missing(p))

    def test_sidecar_partial_hit(self):
        p = _make_projection(sidecar_join_status="partial")
        self.assertTrue(is_recoverable_missing(p))

    def test_sidecar_unavailable_hit(self):
        p = _make_projection(sidecar_join_status="unavailable")
        self.assertTrue(is_recoverable_missing(p))

    def test_sidecar_available_miss(self):
        p = _make_projection(sidecar_join_status="available")
        self.assertFalse(is_recoverable_missing(p))

    def test_unrecoverable_unknown_excluded(self):
        # spec 11 §2.3：unrecoverable unknown 即使 sidecar=unavailable 也不算 recoverable
        p = _make_projection(
            unknown_reason_code="no_known_family_match",
            sidecar_join_status="unavailable",
        )
        self.assertFalse(is_recoverable_missing(p))

    def test_unsupported_material_excluded(self):
        p = _make_projection(unknown_reason_code="unsupported_material_system")
        self.assertFalse(is_recoverable_missing(p))

    def test_sidecar_only_fact_pattern_excluded(self):
        # sidecar_only_fact_pattern 属 unrecoverable，不算 recoverable
        p = _make_projection(unknown_reason_code="sidecar_only_fact_pattern")
        self.assertFalse(is_recoverable_missing(p))


class BucketHelperUnrecoverableUnknownTests(unittest.TestCase):
    def test_no_known_family_match_hit(self):
        p = _make_projection(unknown_reason_code="no_known_family_match")
        self.assertTrue(is_unrecoverable_unknown(p))

    def test_coverage_unimplemented_domain_hit(self):
        p = _make_projection(unknown_reason_code="coverage_unimplemented_domain")
        self.assertTrue(is_unrecoverable_unknown(p))

    def test_sidecar_only_fact_pattern_hit(self):
        p = _make_projection(unknown_reason_code="sidecar_only_fact_pattern")
        self.assertTrue(is_unrecoverable_unknown(p))

    def test_recoverable_excluded(self):
        p = _make_projection(unknown_reason_code="binding_registry_gap")
        self.assertFalse(is_unrecoverable_unknown(p))

    def test_no_unknown_excluded(self):
        p = _make_projection()
        self.assertFalse(is_unrecoverable_unknown(p))


class BucketClassificationTests(unittest.TestCase):
    def test_baseline_distribution_fallback(self):
        # 普通 normal case：不命中前 4 类，归 baseline_distribution
        p = _make_projection()
        buckets = classify_projection_buckets(p)
        self.assertEqual(buckets, ["baseline_distribution"])

    def test_near_threshold_only(self):
        p = _make_projection(regime_tags=["near_below"])
        self.assertEqual(classify_projection_buckets(p), ["near_threshold"])

    def test_multi_bucket_hit(self):
        # 同时命中 near_threshold + neighbor_family_overlap
        p = _make_projection(
            regime_tags=["near_below"], family_scores=[0.7, 0.6],
        )
        buckets = classify_projection_buckets(p)
        self.assertIn("near_threshold", buckets)
        self.assertIn("neighbor_family_overlap", buckets)

    def test_classify_returns_subset_of_bucket_names(self):
        p = _make_projection(
            regime_tags=["near_below"], family_scores=[0.7, 0.6],
            unknown_reason_code="binding_registry_gap",
        )
        buckets = classify_projection_buckets(p)
        for b in buckets:
            self.assertIn(b, BUCKET_NAMES)


# ---------- 单楼视角 filter tests（DEBT-044 修根后语义）----------


class CoverageControlFilterTests(unittest.TestCase):
    """apply_coverage_control_rejection 单楼（单 candidate）视角：
    无楼内裁剪、全量接受、metadata 候选计数单位 = 楼."""

    def test_empty_input(self):
        accepted, metadata = apply_coverage_control_rejection([])
        self.assertEqual(accepted, [])
        self.assertEqual(metadata["coverage_control_profile_id"], "CCP-MBIS-V1")
        # 全 bucket count 0
        for b in BUCKET_NAMES:
            self.assertEqual(metadata["raw_candidate_bucket_counts"][b], 0)
            self.assertEqual(metadata["accepted_bucket_counts"][b], 0)
            self.assertEqual(metadata["rejected_bucket_counts"][b], 0)

    def test_single_world_call_accepts_all(self):
        # DEBT-044 回归锁：单楼调用没有批内分布可参照（spec 11 §1.2 原则二），
        # 不做任何楼内裁剪——3 条全 baseline projection 全量接受.
        # （旧 bug：批级配额 ratio×N 套在单楼上，3 条砍剩 1.）
        projs = [_make_projection(projection_id=f"NP-{i}") for i in range(3)]
        accepted, metadata = apply_coverage_control_rejection(projs)
        self.assertEqual(len(accepted), 3)
        self.assertEqual(accepted, projs)
        # 楼级计数：本楼 primary bucket = baseline_distribution 计 1、零拒绝.
        self.assertEqual(metadata["raw_candidate_bucket_counts"]["baseline_distribution"], 1)
        self.assertEqual(metadata["accepted_bucket_counts"]["baseline_distribution"], 1)
        for b in BUCKET_NAMES:
            self.assertEqual(metadata["rejected_bucket_counts"][b], 0)

    def test_over_sampled_buckets_kept(self):
        # 10 条 projection：1 near_threshold + 9 baseline（同一楼）.
        # 楼级 primary bucket 取并集后按优先级归 near_threshold；全量接受.
        projs = [_make_projection(projection_id="NP-NT", regime_tags=["near_below"])]
        for i in range(9):
            projs.append(_make_projection(projection_id=f"NP-BL-{i}"))
        accepted, metadata = apply_coverage_control_rejection(projs)
        self.assertEqual(metadata["raw_candidate_bucket_counts"]["near_threshold"], 1)
        self.assertEqual(metadata["accepted_bucket_counts"]["near_threshold"], 1)
        # DEBT-044：单楼 10 条全保留，不裁剪.
        self.assertEqual(len(accepted), 10)

    def test_filter_does_not_mutate_input(self):
        # spec 11 §1.2 原则一：不修改 NormativeProjection 字段
        original = _make_projection(regime_tags=["near_below"])
        original_copy = json.loads(json.dumps(original))
        apply_coverage_control_rejection([original])
        self.assertEqual(original, original_copy)

    def test_metadata_has_all_six_fields(self):
        # spec 11 §3.2 CoverageControlBatchMetadata 6 字段
        projs = [_make_projection()]
        _, metadata = apply_coverage_control_rejection(projs)
        self.assertIn("coverage_control_profile_id", metadata)
        self.assertIn("raw_candidate_bucket_counts", metadata)
        self.assertIn("accepted_bucket_counts", metadata)
        self.assertIn("rejected_bucket_counts", metadata)
        self.assertIn("bucket_definition_version", metadata)
        self.assertIn("public_report_note", metadata)

    def test_metadata_no_target_ratio_in_public_note(self):
        # spec 11 §3.2 + §4.2 / NI-004：public_report_note 不暴露 internal target ratio
        projs = [_make_projection()]
        _, metadata = apply_coverage_control_rejection(projs)
        note = metadata["public_report_note"]
        # 不应含具体数值（如 "0.30" / "30%"）
        self.assertNotIn("0.30", note)
        self.assertNotIn("30%", note)
        self.assertNotIn("0.20", note)

    def test_metadata_is_valid_pydantic_model(self):
        # CoverageControlBatchMetadata pydantic 模型可接受 metadata dict
        projs = [_make_projection()]
        _, metadata = apply_coverage_control_rejection(projs)
        model = CoverageControlBatchMetadata(**metadata)
        self.assertEqual(model.coverage_control_profile_id, "CCP-MBIS-V1")

    def test_custom_profile_id(self):
        custom_profile = dict(DEFAULT_COVERAGE_CONTROL_PROFILE)
        custom_profile["coverage_control_profile_id"] = "CCP-TEST-V2"
        projs = [_make_projection()]
        _, metadata = apply_coverage_control_rejection(projs, profile=custom_profile)
        self.assertEqual(metadata["coverage_control_profile_id"], "CCP-TEST-V2")

    def test_bucket_counts_sum_consistency(self):
        # raw = accepted + rejected
        projs = [
            _make_projection(projection_id=f"NP-{i}", regime_tags=["near_below"])
            for i in range(3)
        ] + [
            _make_projection(projection_id=f"NP-BL-{i}")
            for i in range(5)
        ]
        _, metadata = apply_coverage_control_rejection(projs)
        for bucket in BUCKET_NAMES:
            raw = metadata["raw_candidate_bucket_counts"][bucket]
            accepted = metadata["accepted_bucket_counts"][bucket]
            rejected = metadata["rejected_bucket_counts"][bucket]
            self.assertEqual(raw, accepted + rejected, f"bucket {bucket} 不平衡")


# ---------- 批级楼级取舍 tests（DEBT-044 修根主入口，spec 11 §3.1 / §3.3）----------


def _make_building(world_id: str, kind: str, n_projections: int = 4):
    """构造一栋楼的 (world_id, projections) candidate 条目.

    kind ∈ {near, baseline, unrecoverable}.
    """
    projs = []
    for i in range(n_projections):
        if kind == "near":
            projs.append(_make_projection(
                projection_id=f"NP-{world_id}-{i}", regime_tags=["near_below"],
            ))
        elif kind == "unrecoverable":
            projs.append(_make_projection(
                projection_id=f"NP-{world_id}-{i}",
                unknown_reason_code="no_known_family_match",
            ))
        else:
            projs.append(_make_projection(projection_id=f"NP-{world_id}-{i}"))
    return (world_id, projs)


class ClassifyBuildingPrimaryBucketTests(unittest.TestCase):
    def test_any_near_fragment_marks_building_near(self):
        # 楼内 1 near + 3 baseline fragment → 楼归 near_threshold（取并集按优先级）
        _, projs = _make_building("W0", "baseline", n_projections=3)
        projs.append(_make_projection(projection_id="NP-W0-NT", regime_tags=["near_below"]))
        self.assertEqual(classify_building_primary_bucket(projs), "near_threshold")

    def test_all_baseline_building(self):
        _, projs = _make_building("W0", "baseline")
        self.assertEqual(classify_building_primary_bucket(projs), "baseline_distribution")

    def test_empty_projections_baseline(self):
        self.assertEqual(classify_building_primary_bucket([]), "baseline_distribution")


class BuildingLevelCoverageControlTests(unittest.TestCase):
    def test_empty_batch(self):
        accepted_ids, per_world, batch_meta = (
            apply_coverage_control_rejection_building_level([])
        )
        self.assertEqual(accepted_ids, [])
        self.assertEqual(per_world, {})
        for b in BUCKET_NAMES:
            self.assertEqual(batch_meta["raw_candidate_bucket_counts"][b], 0)

    def test_all_near_batch_fully_accepted(self):
        # DEBT-044 方向修正锁：过采桶是地板不是天花板（spec 11 §2.1 example
        # rejection 落 far-threshold/baseline case）——全 near 批次零拒绝.
        # （旧 bug：near 桶被 ratio 0.30 当上限截断，5 楼只留 round(0.3*5) 楼.）
        batch = [_make_building(f"W{i}", "near") for i in range(5)]
        accepted_ids, _, batch_meta = (
            apply_coverage_control_rejection_building_level(batch)
        )
        self.assertEqual(accepted_ids, [f"W{i}" for i in range(5)])
        self.assertEqual(batch_meta["raw_candidate_bucket_counts"]["near_threshold"], 5)
        self.assertEqual(batch_meta["accepted_bucket_counts"]["near_threshold"], 5)
        self.assertEqual(sum(batch_meta["rejected_bucket_counts"].values()), 0)

    def test_baseline_shed_to_satisfy_near_floor(self):
        # 1 near + 9 baseline，near target ratio 0.30：
        # accepted 总数上限 = floor(1 / 0.3) = 3 → 1 near + 头 2 栋 baseline，
        # 削减 7 栋 baseline（rejection 只落 baseline，spec 11 §2.1）.
        batch = [_make_building("W-NT", "near")]
        batch += [_make_building(f"W-BL-{i}", "baseline") for i in range(9)]
        accepted_ids, _, batch_meta = (
            apply_coverage_control_rejection_building_level(batch)
        )
        self.assertEqual(accepted_ids, ["W-NT", "W-BL-0", "W-BL-1"])
        self.assertEqual(batch_meta["accepted_bucket_counts"]["near_threshold"], 1)
        self.assertEqual(batch_meta["accepted_bucket_counts"]["baseline_distribution"], 2)
        self.assertEqual(batch_meta["rejected_bucket_counts"]["baseline_distribution"], 7)
        self.assertEqual(batch_meta["rejected_bucket_counts"]["near_threshold"], 0)
        # near 在 accepted batch 占比 1/3 >= 0.30（过采地板达成）
        self.assertGreaterEqual(1 / len(accepted_ids), 0.30)

    def test_all_baseline_batch_no_shedding(self):
        # 无过采桶候选 → 无过采压力 → 不销毁数据（全量接受）.
        batch = [_make_building(f"W{i}", "baseline") for i in range(10)]
        accepted_ids, _, _ = apply_coverage_control_rejection_building_level(batch)
        self.assertEqual(len(accepted_ids), 10)

    def test_unrecoverable_cap(self):
        # 全 unrecoverable 批次：上限桶 quota = min(10, max(1, round(0.10*10))) = 1
        # （spec 11 §2.3 "unrecoverable unknown 占比应控制，避免 batch 全是死局 case"）
        batch = [_make_building(f"W{i}", "unrecoverable") for i in range(10)]
        accepted_ids, _, batch_meta = (
            apply_coverage_control_rejection_building_level(batch)
        )
        self.assertEqual(accepted_ids, ["W0"])
        self.assertEqual(
            batch_meta["accepted_bucket_counts"]["unrecoverable_unknown_control"], 1
        )
        self.assertEqual(
            batch_meta["rejected_bucket_counts"]["unrecoverable_unknown_control"], 9
        )

    def test_mixed_batch_floor_cap_shed(self):
        # 2 near + 4 baseline + 4 unrecoverable（共 10 楼）：
        #   unrec quota = min(4, max(1, round(0.10*10))) = 1
        #   accepted 上限 = floor(2 / 0.3) = 6 → baseline 保 6 - 2 - 1 = 3
        # → accepted = 2 near + 3 baseline + 1 unrec = 6 楼.
        batch = [_make_building(f"W-NT-{i}", "near") for i in range(2)]
        batch += [_make_building(f"W-BL-{i}", "baseline") for i in range(4)]
        batch += [_make_building(f"W-UR-{i}", "unrecoverable") for i in range(4)]
        accepted_ids, _, batch_meta = (
            apply_coverage_control_rejection_building_level(batch)
        )
        self.assertEqual(len(accepted_ids), 6)
        self.assertEqual(batch_meta["accepted_bucket_counts"]["near_threshold"], 2)
        self.assertEqual(batch_meta["accepted_bucket_counts"]["baseline_distribution"], 3)
        self.assertEqual(
            batch_meta["accepted_bucket_counts"]["unrecoverable_unknown_control"], 1
        )
        # near 占比 2/6 >= 0.30
        self.assertGreaterEqual(2 / len(accepted_ids), 0.30)

    def test_edge_buckets_never_rejected(self):
        # 过采 3 桶候选永不被拒（地板语义），任意混合批次下成立.
        batch = [_make_building(f"W-NT-{i}", "near") for i in range(7)]
        batch += [_make_building(f"W-BL-{i}", "baseline") for i in range(3)]
        _, _, batch_meta = apply_coverage_control_rejection_building_level(batch)
        for bucket in EDGE_OVERSAMPLING_BUCKETS:
            self.assertEqual(
                batch_meta["rejected_bucket_counts"][bucket], 0,
                f"过采桶 {bucket} 不应有 rejection（spec 11 §2.1）",
            )

    def test_accepted_order_preserved(self):
        batch = [_make_building(f"W{i}", "near") for i in range(4)]
        accepted_ids, _, _ = apply_coverage_control_rejection_building_level(batch)
        self.assertEqual(accepted_ids, ["W0", "W1", "W2", "W3"])

    def test_per_world_metadata_complete_and_consistent(self):
        # 每楼都有 6 字段 metadata；楼级计数 raw==1 且 raw=accepted+rejected；
        # 批级 metadata == per-world 求和.
        batch = [_make_building("W-NT", "near")]
        batch += [_make_building(f"W-BL-{i}", "baseline") for i in range(9)]
        accepted_ids, per_world, batch_meta = (
            apply_coverage_control_rejection_building_level(batch)
        )
        self.assertEqual(set(per_world.keys()), {wid for wid, _ in batch})
        sum_raw = {b: 0 for b in BUCKET_NAMES}
        sum_acc = {b: 0 for b in BUCKET_NAMES}
        sum_rej = {b: 0 for b in BUCKET_NAMES}
        for wid, meta in per_world.items():
            for fld in (
                "coverage_control_profile_id", "raw_candidate_bucket_counts",
                "accepted_bucket_counts", "rejected_bucket_counts",
                "bucket_definition_version", "public_report_note",
            ):
                self.assertIn(fld, meta)
            self.assertEqual(sum(meta["raw_candidate_bucket_counts"].values()), 1)
            for b in BUCKET_NAMES:
                raw = meta["raw_candidate_bucket_counts"][b]
                acc = meta["accepted_bucket_counts"][b]
                rej = meta["rejected_bucket_counts"][b]
                self.assertEqual(raw, acc + rej, f"world {wid} bucket {b} 不平衡")
                sum_raw[b] += raw
                sum_acc[b] += acc
                sum_rej[b] += rej
        self.assertEqual(sum_raw, batch_meta["raw_candidate_bucket_counts"])
        self.assertEqual(sum_acc, batch_meta["accepted_bucket_counts"])
        self.assertEqual(sum_rej, batch_meta["rejected_bucket_counts"])

    def test_does_not_mutate_or_trim_projections(self):
        # spec 11 §1.2 原则一 + DEBT-044：不修改 projection 字段、不裁剪楼内列表.
        batch = [_make_building("W0", "near"), _make_building("W1", "baseline")]
        snapshot = json.loads(json.dumps([projs for _, projs in batch]))
        apply_coverage_control_rejection_building_level(batch)
        self.assertEqual([projs for _, projs in batch], snapshot)


# ---------- 集成 build_normative_projections_for_world tests ----------


class BuildNormativeProjectionsFilterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registries = _build_registry_bundle()

    def test_filter_disabled_returns_all(self):
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        projections = build_normative_projections_for_world(
            world, self.registries, apply_coverage_control=False,
        )
        # 关 filter：projection 数 == fragment with mechanism 数
        self.assertEqual(len(projections), len(world.mechanisms))

    def test_filter_on_off_identical_for_single_world(self):
        # DEBT-044 回归锁：单楼调用禁止楼内裁剪——filter 开/关输出完全一致
        # （candidate 粒度 = 楼，spec 11 §3.3；批级取舍走 building_level 入口）.
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        with_filter = build_normative_projections_for_world(world, self.registries)
        without_filter = build_normative_projections_for_world(
            world, self.registries, apply_coverage_control=False,
        )
        self.assertEqual(len(with_filter), len(without_filter))
        self.assertEqual(
            [p["projection_id"] for p in with_filter],
            [p["projection_id"] for p in without_filter],
        )

    def test_with_coverage_control_returns_tuple(self):
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        accepted, metadata = build_normative_projections_for_world_with_coverage_control(
            world, self.registries,
        )
        self.assertIsInstance(accepted, list)
        self.assertIsInstance(metadata, dict)
        self.assertIn("coverage_control_profile_id", metadata)

    def test_with_coverage_control_metadata_counts_consistent(self):
        # DEBT-044 修根后：候选计数单位 = 楼（单楼调用 raw/accepted 各计 1），
        # accepted projections == 该楼全量 candidate（无楼内裁剪）.
        world = generate_world_bundle({}, self.registries, seed=42, building_index=0)
        accepted, metadata = build_normative_projections_for_world_with_coverage_control(
            world, self.registries,
        )
        candidates = build_normative_projections_for_world(
            world, self.registries, apply_coverage_control=False,
        )
        self.assertEqual(len(accepted), len(candidates))
        self.assertEqual(sum(metadata["raw_candidate_bucket_counts"].values()), 1)
        self.assertEqual(sum(metadata["accepted_bucket_counts"].values()), 1)
        self.assertEqual(sum(metadata["rejected_bucket_counts"].values()), 0)


# ---------- 集成 validation v2 + execute_projection_batch_v2 metadata 聚合 ----------


class V2BatchCoverageControlIntegrationTests(unittest.TestCase):
    def test_validation_v2_carries_coverage_metadata_per_world(self):
        # spec 11 §3.1：validation v2 调 _with_coverage_control 入口，
        # 每 world payload 含 coverage_control_metadata 字段
        from workflow_engine.worldgen.parquet_io import (
            read_normative_projection_parquet,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=3, seed=42, fragment_count_per_building=4,
            )
            np_path = Path(result["normative_projection_path"])
            payload = read_normative_projection_parquet(np_path)
            buildings = payload.get("buildings", [])
            self.assertGreater(len(buildings), 0)
            for b in buildings:
                self.assertIn("coverage_control_metadata", b)
                ccm = b["coverage_control_metadata"]
                self.assertIn("coverage_control_profile_id", ccm)
                self.assertIn("raw_candidate_bucket_counts", ccm)
                self.assertIn("accepted_bucket_counts", ccm)
                self.assertIn("rejected_bucket_counts", ccm)
                self.assertIn("bucket_definition_version", ccm)
                self.assertIn("public_report_note", ccm)

    def test_accepted_buildings_keep_complete_fragment_truth(self):
        # DEBT-044 回归锁（修根验收主测试）：每栋被接受楼保留**全部** fragment
        # 的 projection——禁止楼内裁剪。
        # 旧 bug：每楼 W1 产 4 fragment、W2 投影产 4 条 candidate，filter 砍剩 1
        # （accepted 1 / rejected 3 全落 near_threshold 桶）→ 数据池每楼真值残缺。
        # 修后（2026-06-11 实测 count=3 / seed=42 / fragment_count_per_building=4）：
        # 3 楼全接受、每楼 4 条 projection、4 个 distinct fragment_id。
        from workflow_engine.worldgen.parquet_io import (
            read_normative_projection_parquet,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=3, seed=42, fragment_count_per_building=4,
            )
            payload = read_normative_projection_parquet(
                Path(result["normative_projection_path"])
            )
            buildings = payload.get("buildings", [])
            self.assertEqual(len(buildings), 3)
            for b in buildings:
                projections = b.get("projections", [])
                distinct_fragments = {p.get("fragment_id") for p in projections}
                # 楼级取舍：要么整楼接受（全部 fragment 的 projection 在场）、
                # 要么整楼拒绝（0 条）——绝不出现部分 fragment 被砍.
                if projections:
                    self.assertEqual(
                        len(projections), 4,
                        f"world {b['world_id']} 被接受但 projection 残缺"
                        f"（{len(projections)}/4，DEBT-044 楼内裁剪复发）",
                    )
                    self.assertEqual(
                        len(distinct_fragments), 4,
                        f"world {b['world_id']} projection 未覆盖全部 4 个 fragment",
                    )
            # 本配置下全 near 批次零拒绝（过采桶是地板）：3 楼全接受.
            accepted_buildings = [b for b in buildings if b.get("projections")]
            self.assertEqual(len(accepted_buildings), 3)

    def test_execute_projection_batch_v2_aggregates_metadata(self):
        # spec 11 §3.1：execute_projection_batch_v2 phase 4 聚合 per-world metadata
        # 产 batch-level CoverageControlBatchMetadata 写 summary
        with tempfile.TemporaryDirectory() as tmp:
            result = run_worldgenerator_fullcoverage_framework_v2(
                output_dir=Path(tmp), count=3, seed=42, fragment_count_per_building=4,
            )
            batch_out = Path(tmp) / "batch_v2"
            batch_out.mkdir(parents=True, exist_ok=True)
            outputs = execute_projection_batch_v2(
                building_worlds_path=Path(result["building_worlds_path"]),
                normative_projection_path=Path(result["normative_projection_path"]),
                sidecar_runtime_path=Path(result["sidecar_runtime_bundle_path"]),
                output_dir=batch_out,
            )
            summary_path = Path(outputs["summary_path"])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertIn("coverage_control_metadata", summary)
            ccm = summary["coverage_control_metadata"]
            self.assertEqual(ccm["coverage_control_profile_id"], "CCP-MBIS-V1")
            self.assertGreaterEqual(ccm["per_world_metadata_count"], 1)
            # 至少有 1 个 bucket 计数（accepted 不可能全 0 假设 worldgen 产 mechanism > 0）
            accepted_sum = sum(ccm["accepted_bucket_counts"].values())
            self.assertGreater(accepted_sum, 0)


# ---------- 硬约束 / NI 红线 tests（spec 11 §3.2 / §3.3 / §4）----------


class CoverageControlHardConstraintsTests(unittest.TestCase):
    def test_no_rejection_trace_in_normative_projection(self):
        # spec 11 §3.2 / NI-013：per-sample rejection trace 不进 NormativeProjection 字段
        registries = _build_registry_bundle()
        world = generate_world_bundle({}, registries, seed=42, building_index=0)
        projections = build_normative_projections_for_world(world, registries)
        # NormativeProjection 不应含 rejection_reason / bucket_label / coverage_quota 等字段
        forbidden_fields = {
            "rejection_reason", "bucket_label", "coverage_quota",
            "coverage_target_ratio", "near_threshold_priority",
            "coverage_control_metadata",  # batch-level metadata 不应进 per-projection
        }
        for p in projections:
            for fld in forbidden_fields:
                self.assertNotIn(fld, p, f"projection 不应含 {fld}（spec 11 §3.2）")

    def test_recoverable_codes_set_matches_spec(self):
        # spec 11 §2.3 第一条：recoverable 5 个 reason code
        expected = {
            "binding_registry_gap",
            "unit_incompatible",
            "projection_binding_incompatible",
            "measurement_family_unimplemented",
            "method_class_unimplemented",
        }
        self.assertEqual(RECOVERABLE_UNKNOWN_REASON_CODES, expected)

    def test_unrecoverable_codes_set_matches_spec(self):
        # spec 11 §2.3 排除项：unrecoverable 7 个 reason code
        expected = {
            "no_known_family_match",
            "coverage_unimplemented_domain",
            "unsupported_material_system",
            "unsupported_component_type",
            "unsupported_damage_pattern",
            "unsupported_location_context",
            "sidecar_only_fact_pattern",
        }
        self.assertEqual(UNRECOVERABLE_UNKNOWN_REASON_CODES, expected)

    def test_recoverable_unrecoverable_disjoint(self):
        # 集合互不相交
        self.assertEqual(
            RECOVERABLE_UNKNOWN_REASON_CODES & UNRECOVERABLE_UNKNOWN_REASON_CODES,
            set(),
        )

    def test_recoverable_unrecoverable_cover_12_of_13(self):
        # spec 08 §2.1 共 13 个 unknown_reason_code；spec 11 §2.3 把其中 12 个分到
        # recoverable (5) + unrecoverable (7) 两堆。multi_family_conflict (priority 1)
        # 是 neighbor_family_overlap bucket 的触发条件，不算 recoverable/unrecoverable.
        from workflow_engine.regulation_projection_executor import UNKNOWN_REASON_CODES
        all_codes = set(UNKNOWN_REASON_CODES)
        classified = RECOVERABLE_UNKNOWN_REASON_CODES | UNRECOVERABLE_UNKNOWN_REASON_CODES
        self.assertEqual(all_codes - classified, {"multi_family_conflict"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
