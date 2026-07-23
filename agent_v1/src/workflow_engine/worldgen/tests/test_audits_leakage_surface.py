"""W1 audits / leakage_surface 测试 (DEBT-030 audit 5)."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

import pytest

from workflow_engine.worldgen.audits.leakage_surface import (
    DEFAULT_THRESHOLD,
    LeakageSurfaceReport,
    _logreg_train_predict,
    _majority_class_accuracy,
    extract_w1_surface_features,
    leakage_on_surface_audit,
)


# ---------------- fixture builder ------------------------------------------


def _mk_building(
    b_idx: int,
    age: float = 30.0,
    n_frag: int = 5,
    n_meas: int = 20,
    storey: int = 8,
) -> Dict[str, Any]:
    return {
        "world_id": f"WB-{b_idx:04d}",
        "building": {
            "age_years": age,
            "storey_count": storey,
            "primary_materials": ["reinforced_concrete"],
            "configuration_tags": [],
        },
        "fragments": [
            {"fragment_id": f"F{i}", "fragment_area_m2": 30.0} for i in range(n_frag)
        ],
        "components": [{"component_id": f"C{i}"} for i in range(n_frag)],
        "drivers": [{"driver_id": f"D{i}"} for i in range(n_frag)],
        "mechanisms": [
            {"mechanism_id": f"M{i}", "activation_score": 0.5} for i in range(n_frag)
        ],
        "conditions": [],
        "measurements": [{"measurement_family": "structural"}] * n_meas,
    }


# ---------------- feature extraction ---------------------------------------


def test_extract_surface_features_returns_dict() -> None:
    p = _mk_building(0, age=42.0, n_frag=4, n_meas=15)
    feats = extract_w1_surface_features(p)
    assert isinstance(feats, dict)
    assert feats["age_years"] == 42.0
    assert feats["n_fragments"] == 4
    assert feats["n_measurements"] == 15
    assert feats["sum_fragment_area_m2"] == pytest.approx(4 * 30.0)
    assert feats["n_components"] == 4
    assert feats["n_drivers"] == 4
    assert feats["n_mechanisms"] == 4
    assert feats["mean_activation_score"] == 0.5
    assert feats["max_activation_score"] == 0.5


def test_extract_surface_features_empty_building() -> None:
    p = {"building": {}}
    feats = extract_w1_surface_features(p)
    assert feats["age_years"] == 0.0
    assert feats["n_fragments"] == 0.0
    assert feats["n_measurements"] == 0.0
    assert feats["mean_activation_score"] == 0.0


def test_extract_surface_features_no_w2_token_leak() -> None:
    """surface feature dict 不能含任何 rule_family / threshold 等 W2 token。"""
    p = _mk_building(0)
    feats = extract_w1_surface_features(p)
    for k in feats:
        assert "rule" not in k
        assert "threshold" not in k
        assert "verdict" not in k
        assert "gold" not in k
        assert "observation" not in k


# ---------------- logreg helper --------------------------------------------


def test_majority_class_accuracy_empty() -> None:
    assert _majority_class_accuracy([]) == 0.0


def test_majority_class_accuracy_balanced() -> None:
    assert _majority_class_accuracy([0, 1, 0, 1]) == 0.5


def test_majority_class_accuracy_skewed() -> None:
    assert _majority_class_accuracy([0, 0, 0, 1]) == 0.75


def test_logreg_fixed_seed_deterministic() -> None:
    feats = [{"x": float(i)} for i in range(20)]
    labels = [1 if i > 10 else 0 for i in range(20)]
    p1 = _logreg_train_predict(feats, labels, seed=42)
    p2 = _logreg_train_predict(feats, labels, seed=42)
    assert p1 == p2


def test_logreg_separable_data_high_accuracy() -> None:
    feats = [{"x": float(i)} for i in range(40)]
    labels = [1 if i > 20 else 0 for i in range(40)]
    preds = _logreg_train_predict(feats, labels)
    correct = sum(1 for p, y in zip(preds, labels) if p == y)
    assert correct / len(labels) > 0.85


# ---------------- main audit: independent (PASS) --------------------------


def _build_independent_batch(
    n: int = 100, seed: int = 42
) -> List[Tuple[Dict[str, Any], str]]:
    rng = random.Random(seed)
    families = ["fam_A", "fam_B", "fam_C"]
    out: List[Tuple[Dict[str, Any], str]] = []
    for i in range(n):
        p = _mk_building(
            i,
            age=rng.uniform(10, 80),
            n_frag=rng.randint(2, 8),
            n_meas=rng.randint(5, 30),
            storey=rng.randint(3, 15),
        )
        fam = rng.choice(families)  # label random independent of surface
        out.append((p, fam))
    return out


def test_independent_surface_label_pass() -> None:
    """surface ⊥ family label → probe 学不到信号 → PASS."""
    batch = _build_independent_batch(n=100, seed=42)
    report = leakage_on_surface_audit(batch)
    assert report.passed, f"delta={report.delta} prior={report.prior_accuracy} probe={report.probe_accuracy}"
    assert report.delta <= DEFAULT_THRESHOLD


# ---------------- main audit: strong leak (FAIL) --------------------------


def _build_leaky_batch(
    n: int = 100, seed: int = 42
) -> List[Tuple[Dict[str, Any], str]]:
    rng = random.Random(seed)
    out: List[Tuple[Dict[str, Any], str]] = []
    for i in range(n):
        age = rng.uniform(10, 80)
        p = _mk_building(
            i,
            age=age,
            n_frag=rng.randint(2, 8),
            n_meas=rng.randint(5, 30),
        )
        fam = "fam_OLD" if age > 45 else "fam_NEW"  # deterministic age→family
        out.append((p, fam))
    return out


def test_strong_leak_detected() -> None:
    """surface age 完全决定 family → probe accuracy 接近 1.0 → FAIL."""
    batch = _build_leaky_batch(n=100, seed=42)
    report = leakage_on_surface_audit(batch)
    assert not report.passed
    assert report.delta > DEFAULT_THRESHOLD
    assert report.probe_accuracy >= 0.85


# ---------------- edge cases -----------------------------------------------


def test_small_sample_skipped() -> None:
    """< 4 samples 直接 PASS with notes."""
    batch = [
        (_mk_building(0), "A"),
        (_mk_building(1), "B"),
        (_mk_building(2), "A"),
    ]
    report = leakage_on_surface_audit(batch)
    assert report.passed
    assert "skip" in report.notes.lower() or "insufficient" in report.notes.lower()


def test_all_same_family_trivial_pass() -> None:
    """全是同一 family，audit 无意义直接 PASS."""
    batch = [(_mk_building(i), "only_family") for i in range(10)]
    report = leakage_on_surface_audit(batch)
    assert report.passed
    assert "degenerate" in report.notes.lower() or "trivial" in report.notes.lower()


def test_threshold_configurable() -> None:
    """audit threshold 可以自定（更宽松或更严）."""
    batch = _build_leaky_batch(n=100, seed=42)
    # default threshold 0.05 → fail
    r1 = leakage_on_surface_audit(batch, threshold=0.05)
    assert not r1.passed
    # 假设设极宽 threshold=0.50 → pass (probe delta < 0.5)
    r2 = leakage_on_surface_audit(batch, threshold=0.95)
    assert r2.passed


# ---------------- determinism ----------------------------------------------


def test_audit_deterministic_by_seed() -> None:
    batch = _build_independent_batch(n=50, seed=42)
    r1 = leakage_on_surface_audit(batch, seed=999)
    r2 = leakage_on_surface_audit(batch, seed=999)
    assert r1.probe_accuracy == r2.probe_accuracy
    assert r1.delta == r2.delta


# ---------------- API shape -------------------------------------------------


def test_report_dataclass_shape() -> None:
    batch = _build_independent_batch(n=20, seed=42)
    report = leakage_on_surface_audit(batch)
    assert isinstance(report, LeakageSurfaceReport)
    assert isinstance(report.passed, bool)
    assert 0.0 <= report.prior_accuracy <= 1.0
    assert 0.0 <= report.probe_accuracy <= 1.0


def test_report_records_metadata() -> None:
    batch = _build_independent_batch(n=30, seed=42)
    report = leakage_on_surface_audit(batch)
    assert report.n_samples == 30
    assert report.n_features > 0
    assert report.positive_family in {"fam_A", "fam_B", "fam_C"}
    assert report.n_positive + report.n_negative == 30
    assert len(report.feature_keys) == report.n_features
