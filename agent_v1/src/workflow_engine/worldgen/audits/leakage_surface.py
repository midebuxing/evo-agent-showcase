"""W1 leakage audit on surface (DEBT-030 audit 5).

W1 spec 01 §6 表第 4 行红线：
> Leakage audit on surface: W1 输出表层（measurement value / fragment surface tag）
> 无法反推 rule_family / threshold value.

设计
====
对每个 building 提取 surface feature dict（building age / fragment count / mechanism /
measurement / severity 等），用 W2 端给的 family label 训 logistic regression probe，
要求 ``probe_accuracy - prior_accuracy <= 0.05`` PASS.

probe 是 one-vs-rest binary classifier：取最高频 family 作正类（其他作负类），
prior_accuracy = majority class baseline.

logreg 实现独立精简版（不依赖 numpy/sklearn）+ per-feature z-score normalization
（解决不同 scale feature 数值不一致问题，跟 evo §11.9 audit 同 pattern 但
独立 helper 避免 worldgen ← evo 反向依赖）.

跨进程 / 跑批 CI 用法
=====================
release_batch 跑完后从 W2 projection 端拿 family label，对 W1 bundle 跑 audit::

    from workflow_engine.worldgen.audits import leakage_on_surface_audit
    payloads_with_labels = [(building_payload, family_label), ...]
    report = leakage_on_surface_audit(payloads_with_labels)
    assert report.passed, f"probe delta {report.delta:.3f} > threshold {report.threshold}"
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence, Tuple


PROBE_RANDOM_SEED: int = 1337
DEFAULT_THRESHOLD: float = 0.05


# ---------- surface feature extraction ----------


def extract_w1_surface_features(building_payload: Mapping[str, Any]) -> Dict[str, float]:
    """从一个 W1 building payload 提取 surface 数值特征 dict.

    surface 特征只读 W1 输出表层（structural / measurement / state distribution），
    不读任何 W2 信息（rule_family / threshold）。这是 audit 的核心约束：probe
    只能用 W1 surface 反推 family，证明 surface ≠ leak.
    """
    feats: Dict[str, float] = {}

    building = building_payload.get("building", {})
    feats["age_years"] = float(building.get("age_years", 0))
    feats["storey_count"] = float(building.get("storey_count", 0))
    feats["n_primary_materials"] = float(len(building.get("primary_materials", [])))
    feats["n_configuration_tags"] = float(len(building.get("configuration_tags", [])))

    fragments = building_payload.get("fragments", [])
    feats["n_fragments"] = float(len(fragments))
    feats["sum_fragment_area_m2"] = float(
        sum(f.get("fragment_area_m2", 0.0) or 0.0 for f in fragments)
    )

    components = building_payload.get("components", [])
    feats["n_components"] = float(len(components))

    drivers = building_payload.get("drivers", [])
    feats["n_drivers"] = float(len(drivers))

    mechanisms = building_payload.get("mechanisms", [])
    feats["n_mechanisms"] = float(len(mechanisms))
    if mechanisms:
        activations = [m.get("activation_score", 0.0) or 0.0 for m in mechanisms]
        feats["mean_activation_score"] = sum(activations) / len(activations)
        feats["max_activation_score"] = max(activations)
    else:
        feats["mean_activation_score"] = 0.0
        feats["max_activation_score"] = 0.0

    conditions = building_payload.get("conditions", [])
    feats["n_conditions"] = float(len(conditions))

    measurements = building_payload.get("measurements", [])
    feats["n_measurements"] = float(len(measurements))
    branch_counts: Counter = Counter()
    for m in measurements:
        b = m.get("measurement_family", "unknown")
        branch_counts[b] += 1
    for branch, count in branch_counts.items():
        feats[f"n_measurement_branch_{branch}"] = float(count)

    return feats


# ---------- pure-python logreg helper ----------


def _majority_class_accuracy(labels: Sequence[int]) -> float:
    if not labels:
        return 0.0
    counter = Counter(labels)
    return counter.most_common(1)[0][1] / len(labels)


def _holdout_split(
    n: int, holdout_ratio: float = 0.2, seed: int = PROBE_RANDOM_SEED,
) -> Tuple[List[int], List[int]]:
    """Deterministic train/test holdout split by shuffled index.

    DEBT-codex-finding-4 (2026-05-27): 之前 audit 用同一批样本训练 + 评估
    probe，Δ 包含样本内拟合偏差。改成 80/20 holdout——probe 在 train set 上
    拟合，仅在 test set 上报 accuracy & Δ。
    """
    rng = random.Random(seed)
    indices = list(range(n))
    rng.shuffle(indices)
    cut = max(1, int(round(n * (1.0 - holdout_ratio))))
    return indices[:cut], indices[cut:]


def _logreg_train(
    feature_dicts: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    *,
    seed: int = PROBE_RANDOM_SEED,
    epochs: int = 200,
    lr: float = 1.0,
) -> Tuple[Dict[str, float], float, Dict[str, float], Dict[str, float], List[str]]:
    """Train logreg + per-feature z-score normalization.

    Returns: (weights, bias, feat_mean, feat_std, feature_keys).
    """
    rng = random.Random(seed)
    feature_keys = sorted({k for d in feature_dicts for k in d})
    feat_mean: Dict[str, float] = {}
    feat_std: Dict[str, float] = {}
    n = len(feature_dicts)
    for k in feature_keys:
        vals = [float(d.get(k, 0.0)) for d in feature_dicts]
        mu = sum(vals) / n
        var = sum((v - mu) ** 2 for v in vals) / n
        feat_mean[k] = mu
        feat_std[k] = math.sqrt(var) if var > 1e-12 else 1.0

    def _norm(d: Mapping[str, float], k: str) -> float:
        return (float(d.get(k, 0.0)) - feat_mean[k]) / feat_std[k]

    weights = {k: rng.uniform(-0.01, 0.01) for k in feature_keys}
    bias = 0.0

    def sigmoid(z: float) -> float:
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    for _ in range(epochs):
        grad_w: Dict[str, float] = {k: 0.0 for k in feature_keys}
        grad_b = 0.0
        for feats, y in zip(feature_dicts, labels):
            z = bias + sum(weights[k] * _norm(feats, k) for k in feature_keys)
            p = sigmoid(z)
            err = p - float(y)
            for k in feature_keys:
                grad_w[k] += err * _norm(feats, k)
            grad_b += err
        n_samp = max(1, len(labels))
        for k in feature_keys:
            weights[k] -= lr * grad_w[k] / n_samp
        bias -= lr * grad_b / n_samp

    return weights, bias, feat_mean, feat_std, feature_keys


def _logreg_predict(
    feature_dicts: Sequence[Mapping[str, float]],
    *,
    weights: Mapping[str, float],
    bias: float,
    feat_mean: Mapping[str, float],
    feat_std: Mapping[str, float],
    feature_keys: Sequence[str],
) -> List[int]:
    def _norm(d: Mapping[str, float], k: str) -> float:
        return (float(d.get(k, 0.0)) - feat_mean[k]) / feat_std[k]

    def sigmoid(z: float) -> float:
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    preds: List[int] = []
    for feats in feature_dicts:
        z = bias + sum(weights[k] * _norm(feats, k) for k in feature_keys)
        preds.append(1 if sigmoid(z) >= 0.5 else 0)
    return preds


def _logreg_train_predict(
    feature_dicts: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    *,
    seed: int = PROBE_RANDOM_SEED,
    epochs: int = 200,
    lr: float = 1.0,
) -> List[int]:
    """Legacy同集 train+predict——仅保留单测/外部兼容；新 audit 路径走 holdout."""
    feature_keys = sorted({k for d in feature_dicts for k in d})
    if not feature_keys:
        majority = Counter(labels).most_common(1)[0][0] if labels else 0
        return [majority] * len(labels)
    weights, bias, feat_mean, feat_std, fkeys = _logreg_train(
        feature_dicts, labels, seed=seed, epochs=epochs, lr=lr
    )
    return _logreg_predict(
        feature_dicts,
        weights=weights, bias=bias,
        feat_mean=feat_mean, feat_std=feat_std,
        feature_keys=fkeys,
    )


# ---------- main audit ----------


@dataclass
class LeakageSurfaceReport:
    passed: bool
    threshold: float
    prior_accuracy: float
    probe_accuracy: float
    delta: float
    # n_samples: 总样本数（train+test，向后兼容字段）
    # DEBT-codex-finding-4: holdout split 后 audit 在 test set 报 Δ，
    # n_samples 仍报总集大小，新增 n_test_samples 报 test 集大小
    n_samples: int = 0
    n_test_samples: int = 0
    n_features: int = 0
    positive_family: str = ""
    n_positive: int = 0
    n_negative: int = 0
    feature_keys: List[str] = field(default_factory=list)
    notes: str = ""


def leakage_on_surface_audit(
    payloads_with_labels: Sequence[Tuple[Mapping[str, Any], str]],
    threshold: float = DEFAULT_THRESHOLD,
    seed: int = PROBE_RANDOM_SEED,
    epochs: int = 200,
    lr: float = 1.0,
) -> LeakageSurfaceReport:
    """W1 surface 反推 family leakage audit.

    参数
    ----
    payloads_with_labels: ``[(building_payload, family_label), ...]``
        每对一个 building；family_label 由 W2 端提供。
    threshold: probe delta 上限（默认 5pp，跟 evo §11.9 同口径）.

    设计：把 family label 转 binary（most-common family = 1，其余 = 0），
    跑 logreg probe；prior baseline = majority class accuracy.

    ``passed`` ⟺ ``probe_accuracy - prior_accuracy <= threshold``.
    """
    if len(payloads_with_labels) < 4:
        return LeakageSurfaceReport(
            passed=True,
            threshold=threshold,
            prior_accuracy=0.0,
            probe_accuracy=0.0,
            delta=0.0,
            n_samples=len(payloads_with_labels),
            notes=f"sample size {len(payloads_with_labels)} < 4，skip audit (insufficient data)",
        )

    payloads = [p for p, _ in payloads_with_labels]
    raw_labels = [l for _, l in payloads_with_labels]

    family_counts = Counter(raw_labels)
    positive_family, _ = family_counts.most_common(1)[0]
    labels = [1 if l == positive_family else 0 for l in raw_labels]

    if len(set(labels)) < 2:
        # 全是同一 family，audit 无意义直接 PASS
        return LeakageSurfaceReport(
            passed=True,
            threshold=threshold,
            prior_accuracy=1.0,
            probe_accuracy=1.0,
            delta=0.0,
            n_samples=len(labels),
            positive_family=positive_family,
            n_positive=len(labels),
            n_negative=0,
            notes="all samples share same family；audit degenerate to trivial pass",
        )

    feature_dicts = [extract_w1_surface_features(p) for p in payloads]
    feature_keys = sorted({k for d in feature_dicts for k in d})

    # DEBT-codex-finding-4 (2026-05-27): 之前 audit 在同一批样本上 train + 评估，
    # Δ 含样本内拟合偏差。改成 80/20 holdout split——probe 仅在 test set 上
    # 报 prior / probe / Δ。
    train_idx, test_idx = _holdout_split(
        len(payloads), holdout_ratio=0.2, seed=seed,
    )
    train_feats = [feature_dicts[i] for i in train_idx]
    train_labels = [labels[i] for i in train_idx]
    test_feats = [feature_dicts[i] for i in test_idx]
    test_labels = [labels[i] for i in test_idx]

    if not test_labels:
        return LeakageSurfaceReport(
            passed=True,
            threshold=threshold,
            prior_accuracy=0.0,
            probe_accuracy=0.0,
            delta=0.0,
            n_samples=len(labels),
            n_features=len(feature_keys),
            positive_family=positive_family,
            n_positive=sum(labels),
            n_negative=len(labels) - sum(labels),
            notes="holdout split produced empty test set; skip audit",
        )

    # train logreg on train split
    weights, bias, feat_mean, feat_std, fkeys = _logreg_train(
        train_feats, train_labels, seed=seed, epochs=epochs, lr=lr,
    )
    # 在 test set 上预测
    test_preds = _logreg_predict(
        test_feats,
        weights=weights, bias=bias,
        feat_mean=feat_mean, feat_std=feat_std,
        feature_keys=fkeys,
    )
    # prior = majority class baseline 也仅在 test set 上算
    prior = _majority_class_accuracy(test_labels)
    correct = sum(1 for p, y in zip(test_preds, test_labels) if p == y)
    probe_acc = correct / len(test_labels) if test_labels else 0.0
    delta = probe_acc - prior

    return LeakageSurfaceReport(
        passed=delta <= threshold,
        threshold=threshold,
        prior_accuracy=prior,
        probe_accuracy=probe_acc,
        delta=delta,
        n_samples=len(labels),  # 总集大小（保持向后兼容）
        n_test_samples=len(test_labels),  # test 集大小（DEBT-codex-finding-4）
        n_features=len(feature_keys),
        positive_family=positive_family,
        n_positive=sum(labels),  # 总集正样本数（向后兼容）
        n_negative=len(labels) - sum(labels),  # 总集负样本数（向后兼容）
        feature_keys=feature_keys,
        notes=(
            f"holdout 80/20 split (seed={seed}); train n={len(train_labels)} "
            f"test n={len(test_labels)}; delta reported on test set only "
            f"(DEBT-codex-finding-4 fix)"
        ),
    )


__all__ = [
    "DEFAULT_THRESHOLD",
    "LeakageSurfaceReport",
    "PROBE_RANDOM_SEED",
    "extract_w1_surface_features",
    "leakage_on_surface_audit",
]
