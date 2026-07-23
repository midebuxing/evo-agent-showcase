"""W1 audits / held_out_split 测试 (DEBT-030 audit 3)."""

from __future__ import annotations

from typing import Dict, List

import pytest

from workflow_engine.worldgen.audits.held_out_split import (
    DEFAULT_RATIOS,
    EVOLVE_TRAIN,
    GATE_VALIDATION,
    HELD_OUT_TEST,
    HeldOutSplit,
    SplitAuditReport,
    held_out_family_split,
    validate_held_out_split,
)


# ---------------- helpers --------------------------------------------------


def _make_buildings_with_families(
    family_sizes: Dict[str, int],
) -> tuple[List[str], Dict[str, str]]:
    """构造 ``[building_ids]`` + ``{building_id → family_id}``."""
    building_ids: List[str] = []
    family_labels: Dict[str, str] = {}
    idx = 0
    for fam, size in family_sizes.items():
        for _ in range(size):
            bid = f"b{idx:04d}"
            building_ids.append(bid)
            family_labels[bid] = fam
            idx += 1
    return building_ids, family_labels


# ---------------- determinism + disjoint ----------------------------------


def test_split_deterministic_by_seed() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20}
    )
    s1 = held_out_family_split(buildings, labels, seed=42)
    s2 = held_out_family_split(buildings, labels, seed=42)
    assert s1.evolve_train_building_ids == s2.evolve_train_building_ids
    assert s1.gate_validation_building_ids == s2.gate_validation_building_ids
    assert s1.held_out_test_building_ids == s2.held_out_test_building_ids


def test_split_different_seeds_differ() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20}
    )
    s1 = held_out_family_split(buildings, labels, seed=0)
    s2 = held_out_family_split(buildings, labels, seed=1)
    assert set(s1.held_out_test_building_ids) != set(s2.held_out_test_building_ids)


def test_buildings_disjoint_across_splits() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    train = set(split.evolve_train_building_ids)
    val = set(split.gate_validation_building_ids)
    hold = set(split.held_out_test_building_ids)
    assert train & val == set()
    assert train & hold == set()
    assert val & hold == set()


def test_no_building_lost_in_split() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    assert split.all_building_ids() == set(buildings)


# ---------------- ratio + stratification ----------------------------------


def test_default_ratios_60_20_20() -> None:
    assert DEFAULT_RATIOS == (0.60, 0.20, 0.20)


def test_ratio_within_tolerance_on_large_batch() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 100, "B": 100, "C": 100, "D": 100, "E": 100}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    report = validate_held_out_split(split, labels)
    assert report.passed
    train_r, val_r, hold_r = report.actual_ratios
    assert abs(train_r - 0.60) <= 0.05
    assert abs(val_r - 0.20) <= 0.05
    assert abs(hold_r - 0.20) <= 0.05


def test_non_rare_family_stratified_across_splits() -> None:
    """每个 non-rare family 都应在三组各自有 ≥1 building."""
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    report = validate_held_out_split(split, labels)
    assert report.passed
    for split_name in (EVOLVE_TRAIN, GATE_VALIDATION, HELD_OUT_TEST):
        for fam in ("A", "B", "C", "D", "E"):
            assert report.family_distribution[split_name][fam] >= 1


# ---------------- rare family ---------------------------------------------


def test_rare_family_all_goes_to_holdout() -> None:
    """rare family (count < threshold) 全归 held_out_test."""
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20, "RARE": 2}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    hold = set(split.held_out_test_building_ids)
    rare_bids = [b for b, f in labels.items() if f == "RARE"]
    for b in rare_bids:
        assert b in hold


def test_rare_family_not_in_train_or_val() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20, "RARE": 2}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    train = set(split.evolve_train_building_ids)
    val = set(split.gate_validation_building_ids)
    rare_bids = [b for b, f in labels.items() if f == "RARE"]
    for b in rare_bids:
        assert b not in train
        assert b not in val


def test_rare_threshold_configurable() -> None:
    """rare_family_threshold=5 → family of 4 也归 holdout."""
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "RARE": 4}
    )
    split = held_out_family_split(
        buildings, labels, rare_family_threshold=5, seed=0
    )
    hold = set(split.held_out_test_building_ids)
    rare_bids = [b for b, f in labels.items() if f == "RARE"]
    for b in rare_bids:
        assert b in hold


def test_audit_reports_rare_families() -> None:
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "E": 20, "R1": 2, "R2": 1}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    report = validate_held_out_split(split, labels)
    assert "R1" in report.rare_families
    assert "R2" in report.rare_families
    assert "A" not in report.rare_families


# ---------------- audit fail paths -----------------------------------------


def test_audit_detects_overlapping_buildings() -> None:
    """构造一个 building 重复在 train + holdout，audit 必 fail."""
    buildings, labels = _make_buildings_with_families(
        {"A": 10, "B": 10, "C": 10, "D": 10}
    )
    split = held_out_family_split(buildings, labels, seed=0)
    # 故意污染
    bad_split = HeldOutSplit(
        evolve_train_building_ids=split.evolve_train_building_ids
        + split.held_out_test_building_ids[:1],
        gate_validation_building_ids=split.gate_validation_building_ids,
        held_out_test_building_ids=split.held_out_test_building_ids,
        ratios=split.ratios,
        seed=split.seed,
        rare_family_threshold=split.rare_family_threshold,
    )
    report = validate_held_out_split(bad_split, labels)
    assert not report.passed
    assert any("train ∩ holdout" in v for v in report.violations)


def test_audit_detects_family_missing_from_holdout() -> None:
    """构造一个 non-rare family 完全没有 building 进 holdout，audit 必 fail."""
    # 模拟：family A 20 个全在 train，B/C/D 正常切
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20}
    )
    bad_split = HeldOutSplit(
        evolve_train_building_ids=tuple(b for b in buildings if labels[b] in ("A", "B")),
        gate_validation_building_ids=tuple(
            b for b in buildings if labels[b] == "C"
        )[:10],
        held_out_test_building_ids=tuple(
            b for b in buildings if labels[b] == "D"
        ),
        ratios=DEFAULT_RATIOS,
        seed=0,
        rare_family_threshold=3,
    )
    report = validate_held_out_split(bad_split, labels)
    assert not report.passed
    # A 全在 train, holdout 没 A → 报 "family 'A' ... 在 held_out 0 覆盖"
    assert any("'A'" in v and "held_out 0 覆盖" in v for v in report.violations)


def test_audit_detects_rare_family_leak_to_train() -> None:
    """rare family 漏到 train，audit 必 fail."""
    buildings, labels = _make_buildings_with_families(
        {"A": 20, "B": 20, "C": 20, "D": 20, "RARE": 2}
    )
    rare_bids = [b for b, f in labels.items() if f == "RARE"]
    bad_split = HeldOutSplit(
        evolve_train_building_ids=tuple([rare_bids[0]] + [b for b in buildings if labels[b] in ("A", "B")][:50]),
        gate_validation_building_ids=tuple(
            b for b in buildings if labels[b] == "C"
        )[:15],
        held_out_test_building_ids=tuple(
            [rare_bids[1]] + [b for b in buildings if labels[b] == "D"][:15]
        ),
        ratios=DEFAULT_RATIOS,
        seed=0,
        rare_family_threshold=3,
    )
    report = validate_held_out_split(bad_split, labels)
    assert not report.passed
    assert any("rare family 'RARE'" in v and "漏到 non-holdout" in v for v in report.violations)


def test_audit_detects_ratio_deviation() -> None:
    """构造比例严重偏离 (train 90%) 的 split，audit 必 fail."""
    buildings, labels = _make_buildings_with_families(
        {"A": 25, "B": 25, "C": 25, "D": 25}
    )
    # 90/5/5 split
    bad_split = HeldOutSplit(
        evolve_train_building_ids=tuple(buildings[:90]),
        gate_validation_building_ids=tuple(buildings[90:95]),
        held_out_test_building_ids=tuple(buildings[95:100]),
        ratios=DEFAULT_RATIOS,
        seed=0,
        rare_family_threshold=3,
    )
    report = validate_held_out_split(bad_split, labels, tolerance=0.05)
    assert not report.passed
    assert any("ratio" in v and "偏离目标" in v for v in report.violations)


# ---------------- parameter validation -------------------------------------


def test_ratios_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        held_out_family_split(
            ["b1", "b2"], {"b1": "A", "b2": "A"}, ratios=(0.5, 0.3, 0.3)
        )


def test_negative_ratio_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        held_out_family_split(
            ["b1", "b2"], {"b1": "A", "b2": "A"}, ratios=(1.1, -0.1, 0.0)
        )


# ---------------- API shape ------------------------------------------------


def test_split_dataclass_shape() -> None:
    buildings, labels = _make_buildings_with_families({"A": 10, "B": 10})
    split = held_out_family_split(buildings, labels, seed=0)
    assert isinstance(split, HeldOutSplit)
    assert isinstance(split.evolve_train_building_ids, tuple)
    assert isinstance(split.gate_validation_building_ids, tuple)
    assert isinstance(split.held_out_test_building_ids, tuple)


def test_report_dataclass_shape() -> None:
    buildings, labels = _make_buildings_with_families({"A": 30, "B": 30, "C": 30, "D": 30, "E": 30})
    split = held_out_family_split(buildings, labels, seed=0)
    report = validate_held_out_split(split, labels)
    assert isinstance(report, SplitAuditReport)
    assert isinstance(report.passed, bool)
    assert isinstance(report.violations, list)
    assert isinstance(report.family_distribution, dict)


def test_building_ids_for_dispatcher() -> None:
    buildings, labels = _make_buildings_with_families({"A": 20, "B": 20, "C": 20, "D": 20, "E": 20})
    split = held_out_family_split(buildings, labels, seed=0)
    assert split.building_ids_for(EVOLVE_TRAIN) == split.evolve_train_building_ids
    assert split.building_ids_for(GATE_VALIDATION) == split.gate_validation_building_ids
    assert split.building_ids_for(HELD_OUT_TEST) == split.held_out_test_building_ids
    with pytest.raises(ValueError, match="unknown split"):
        split.building_ids_for("invalid")


# ---------------- unknown family ------------------------------------------


def test_unknown_family_treated_as_separate_bucket() -> None:
    """family_labels 缺失的 building 视为 __unknown__ family."""
    buildings = ["b1", "b2", "b3", "b4", "b5"]
    labels = {"b1": "A", "b2": "A"}  # b3-5 缺失
    split = held_out_family_split(buildings, labels, seed=0)
    # 5 building 都应入 split
    assert split.all_building_ids() == set(buildings)
