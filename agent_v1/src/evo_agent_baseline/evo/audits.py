"""Evo-agent v1 反推 / 反事实 / 泄漏审计（spec v1 §11.9 + §11.10 + §11.11 + §13）。

本模块三个函数：

| 函数 | spec 锚点 |
|------|----------|
| ``adversarial_reconstruction_audit`` | §11.9（v1.1 重定位）audit artifact 端 |
| ``counterfactual_swap_audit`` | §11.10 broker 输出单 case 敏感性 |
| ``leakage_audit_six_metrics`` | §13 v0.4 6 项 + evo 专属扩展（v1.1 字段重定位）|

工程边界（项目原则 2 + 3）：
- evo-agent blind：probe 特征 **不可** 含 raw W2；audit 输出 **不可**
  per-case 标签。本模块只做诊断，所有 raw W2 仅 evaluator private side
  访问，本模块通过 callable 注入 label 计算，自己不读 W2。
- allow_stop：本模块不影响 closure verifier。

probe 算法（spec §11.9）：``logistic regression / tree / small classifier，
固定 seed``。本实现使用 zero-dependency 的 majority-class baseline +
极简梯度下降 logistic regression（防止引入 sklearn 依赖）。

**v1.1 修订（spec §0.6 修订 1 + §11.9 + §11.11）**：

- §11.9 audit 焦点从 sanitized packet 改为 candidate artifact（trainer 输出的
  candidate SkillPackage / candidate EvoPolicyVersion）。理由：packet 不是危险
  路径（packet 即使有信号也只暴露给 runtime trend feedback 接口，且 broker 已
  rounding 抹平）；真正的危险路径是 trainer 用 raw W2 训出的 artifact 里残留
  case-specific signal —— artifact 一旦 promote 为 active 就会被 runtime 加载。
- §11.11 source independence audit 字段修订：原 "Policy training input list 不含
  raw W2 path" 改为 "artifact 输出不含 raw W2 token"（trainer 输入端 v1.1 允许
  读 raw，约束移至 trainer 输出端）。
- 接口保留向后兼容：``adversarial_reconstruction_audit`` 函数签名不变，
  features 提取实现保留 trace-focused 旧版作为过渡兼容；新代码建议把 candidate
  artifact 文本 + activation 轨迹拼成 trace-like 对象后再传入。
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)


# spec v1 §11.9 reconstruction audit 阈值
RECONSTRUCTION_DELTA_THRESHOLD: float = 0.05  # 5pp
# spec v1 §11.10 counterfactual swap 阈值
COUNTERFACTUAL_METRIC_THRESHOLD: float = 0.05
# probe 训练 seed（spec §11.9 fixed seed）
PROBE_RANDOM_SEED: int = 20260524


# ---------------------------------------------------------------------------
# §11.9 Adversarial Reconstruction Audit
# ---------------------------------------------------------------------------


def _extract_probe_features(
    trace: Any,
    feedback_packets: Sequence[Any],
) -> Dict[str, float]:
    """spec v1 §11.9 probe 特征清单：

    - rule family counts
    - open / blocked reason counts
    - Skill activations
    - policy version
    - feedback bucket categories

    **不** 包含 raw W2 字段（spec §11.9 ``Probe 特征不可包括 raw W2``）。

    **v1.1 注（spec §11.9 重定位完成 2026-05-26）**：v1.1 后 audit 焦点改为
    artifact 端，本 trace-focused 函数**保留作向后兼容**。新代码使用
    `_extract_artifact_probe_features(artifact, activation_trace)` +
    `adversarial_reconstruction_audit_artifact(artifact_trace_pairs, ...)`
    接受 (artifact, trace) pair 序列。
    """
    feats: Dict[str, float] = {}
    cs = getattr(trace, "closure_summary", {}) or {}
    for fam, cnt in (cs.get("rule_family_counts", {}) or {}).items():
        feats[f"family__{fam}"] = float(cnt)
    for reason, cnt in (cs.get("open_blocked_reasons", {}) or {}).items():
        feats[f"reason__{reason}"] = float(cnt)
    for skill_id in getattr(trace, "active_skill_version_ids", []) or []:
        feats[f"skill__{skill_id}"] = 1.0
    policy_id = getattr(trace, "evo_policy_version_id", None)
    if policy_id:
        feats[f"policy__{policy_id}"] = 1.0
    for pkt in feedback_packets:
        # 仅取 packet 的 aggregation_level / suggested_evo_action 等 bucket，
        # 不取 metric 数值（防止 packet 数值直接帮 probe 反推）
        agg = getattr(pkt, "aggregation_level", None)
        if agg:
            feats[f"pkt_agg__{agg}"] = feats.get(f"pkt_agg__{agg}", 0.0) + 1.0
        for cell in getattr(pkt, "cells", []) or []:
            if getattr(cell, "suppressed", False):
                continue
            action = getattr(cell, "suggested_evo_action", None)
            if action:
                feats[f"action__{action}"] = feats.get(f"action__{action}", 0.0) + 1.0
    return feats


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _flatten_dict_features(
    obj: Any,
    prefix: str,
    out: Dict[str, float],
    max_depth: int = 4,
) -> None:
    """把任意 dict/list/scalar 拍平成 feature dict（粗略，避免引 numpy/pandas）。

    - dict[str, X] → 每个 key 进 prefix；X 递归处理
    - list/tuple → 取长度 + 每个元素递归（前 16 个）
    - int/float → 直接当 feature value
    - str → token bag（剥 alphanumeric word）+ token 计数
    - bool → 0/1
    """
    if max_depth <= 0:
        return
    if isinstance(obj, bool):
        out[prefix] = 1.0 if obj else 0.0
        return
    if isinstance(obj, (int, float)):
        # 数值直接作 feature；NaN/inf 跳过
        try:
            v = float(obj)
            if v != v or v in (float("inf"), float("-inf")):
                return
            out[prefix] = v
        except (TypeError, ValueError):
            pass
        return
    if isinstance(obj, str):
        # 字符串 → 拆 token bag
        for tok in _TOKEN_RE.findall(obj.lower())[:64]:
            key = f"{prefix}__tok__{tok}"
            out[key] = out.get(key, 0.0) + 1.0
        return
    if isinstance(obj, dict):
        out[f"{prefix}__keys"] = float(len(obj))
        for k, v in list(obj.items())[:32]:
            _flatten_dict_features(v, f"{prefix}__{str(k)[:32]}", out, max_depth - 1)
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = list(obj)
        out[f"{prefix}__len"] = float(len(items))
        for i, v in enumerate(items[:16]):
            _flatten_dict_features(v, f"{prefix}__i{i}", out, max_depth - 1)
        return
    # 其它类型 → 跳过（不强 stringify，避免引入 obj id / 内存地址）


# spec §11.9 v1.1 audit：artifact 端 forbidden id-like 字段不提进 feature
# （避免 probe 用 id 反推 W2；spec §11.9 末"Probe 特征不可包括 raw W2"）
_ARTIFACT_FEATURE_BLOCKLIST: frozenset = frozenset({
    "skill_id", "skill_version_id", "policy_version_id", "policy_id",
    "created_at", "activated_at", "retired_at",
    "package_uri", "package_sha256", "skill_md_sha256", "plan_yaml_sha256",
    "validation_records_sha256", "manifest_sha256",
    "source_trace_hashes", "trained_on_replay_set_id",
    "trained_on_feedback_packet_ids", "trained_on_artifacts",
    "kg_snapshot_id", "rulecard_bundle_id",
})


def _artifact_to_feature_dict(artifact: Any) -> Dict[str, Any]:
    """把 artifact（pydantic model / dict）转成可拍平的 feature dict。

    剔除黑名单字段（id / sha / created_at 等——这些不是行为信号，是身份/时间戳）。
    """
    if hasattr(artifact, "model_dump"):
        try:
            d = artifact.model_dump()
        except Exception:
            d = {}
    elif hasattr(artifact, "__dict__"):
        d = dict(artifact.__dict__)
    elif isinstance(artifact, dict):
        d = dict(artifact)
    else:
        d = {"__raw__": str(artifact)[:128]}
    # 剔除黑名单字段（顶层 + nested skill 的同名字段）
    for k in _ARTIFACT_FEATURE_BLOCKLIST:
        d.pop(k, None)
    # SkillPackage 的话 nested skill 也清一遍
    if isinstance(d.get("skill"), dict):
        for k in _ARTIFACT_FEATURE_BLOCKLIST:
            d["skill"].pop(k, None)
    return d


# spec v1 §11.9 artifact 文本 token 化：alphanumeric word + 短词过滤
# `SKILL.md` / `plan.yaml` 文本本身不进 DTO（设计意图，见 evo/skill_package.py 注释
# "view 文本不入 DTO"），因此 audit 必须独立接收文本以构造 token features，
# 否则含 raw W2 token 的恶意 SKILL.md 文本可 bypass artifact-blocklist 审查。
_ARTIFACT_TEXT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_ARTIFACT_TEXT_TOKEN_MIN_LEN = 3
_ARTIFACT_TEXT_TOKEN_CAP_PER_SOURCE = 512


def _tokenize_artifact_text(text: str) -> Counter:
    """把 SKILL.md / plan.yaml 文本剥成 lowercase token 计数。

    过滤规则：
    - 仅保留 alphanumeric word（开头字母）；
    - 长度 < 3 字符的 token 丢弃（"is" / "a" / "in" 等噪声）；
    - 单 source 最多 cap 512 个 token，避免单文件爆 feature dim。
    """
    counter: Counter = Counter()
    if not text:
        return counter
    seen = 0
    for raw in _ARTIFACT_TEXT_TOKEN_RE.findall(text):
        tok = raw.lower()
        if len(tok) < _ARTIFACT_TEXT_TOKEN_MIN_LEN:
            continue
        counter[tok] += 1
        seen += 1
        if seen >= _ARTIFACT_TEXT_TOKEN_CAP_PER_SOURCE:
            break
    return counter


def _extract_artifact_probe_features(
    artifact: Any,
    activation_trace: Optional[Any] = None,
    *,
    skill_md_text: Optional[str] = None,
    plan_yaml_text: Optional[str] = None,
) -> Dict[str, float]:
    """spec v1 §11.9 v1.1 artifact-focused probe features（步骤 2 实现）。

    特征来源（按 spec §11.9 v1.1 重定位）：
    - artifact DTO 字段：SkillPackage ``skill.json`` 字段 / EvoPolicyVersion
      各 weight / threshold 字段；
    - artifact 关联文本：``SKILL.md`` 文本 token bag / ``plan.yaml`` 文本
      token bag（这两份文本设计上不进 DTO —— `evo/skill_package.py`
      `load_skill_package` 仅校验文本不入 DTO；因此 caller 必须显式把文本
      喂给本函数，否则 audit 漏一层）；
    - artifact 在 held-out run 上的 activation 轨迹（rule family counts /
      open-blocked reason counts / Skill activations / policy version）。

    **不**包含 raw W2 字段（spec §11.9 末）。黑名单字段（id / sha / timestamps
    等身份/时间戳类）也被剔除，避免 probe 用 id 反推 W2。

    工程边界（防扩散）：本函数 **不** 自己读 ``package_uri`` 指向的目录 ——
    实际 caller（promotion gate / audit harness）自己拿文本喂进来，audit
    模块保持 pure（无 IO）。

    参数：
        artifact: candidate SkillPackage / EvoPolicyVersion / 或 dict。
        activation_trace: 该 artifact 在某 held-out run 上的 EvoRunTrace
            （或 trace-like 对象）；可 None（仅 artifact 内容特征）。
        skill_md_text: ``SKILL.md`` 原文 string；caller 通过
            `evo.skill_package.parse_skill_md_view(skill_md_path)` 拿到后传入。
            None 时跳过 SKILL.md token 特征（向后兼容旧 caller）。
        plan_yaml_text: ``plan.yaml`` 原文 string；caller 用
            `Path(plan_yaml_path).read_text(encoding="utf-8")` 拿到后传入。
            None 时跳过 plan.yaml token 特征。

    返回：稀疏 feature dict（key str / value float）。
    """
    feats: Dict[str, float] = {}
    # 1. artifact 内容特征（DTO 字段）
    art_dict = _artifact_to_feature_dict(artifact)
    _flatten_dict_features(art_dict, prefix="art", out=feats, max_depth=4)
    # 2. SKILL.md 文本 token bag（spec §11.9 features 清单 "SKILL.md 文本"）
    if skill_md_text:
        for tok, cnt in _tokenize_artifact_text(skill_md_text).items():
            feats[f"skill_md__tok__{tok}"] = float(cnt)
    # 3. plan.yaml 文本 token bag（spec §11.9 features 清单 "plan.yaml 步骤"）
    if plan_yaml_text:
        for tok, cnt in _tokenize_artifact_text(plan_yaml_text).items():
            feats[f"plan_yaml__tok__{tok}"] = float(cnt)
    # 4. activation trace 特征（复用旧 trace-focused 逻辑，但只取 activation 行为）
    if activation_trace is not None:
        cs = getattr(activation_trace, "closure_summary", None) or {}
        if isinstance(cs, dict):
            for fam, cnt in (cs.get("rule_family_counts", {}) or {}).items():
                feats[f"trace_family__{fam}"] = float(cnt)
            for reason, cnt in (cs.get("open_blocked_reasons", {}) or {}).items():
                feats[f"trace_reason__{reason}"] = float(cnt)
        for skill_id in getattr(activation_trace, "active_skill_version_ids", []) or []:
            feats[f"trace_skill__{skill_id}"] = 1.0
        policy_id = getattr(activation_trace, "evo_policy_version_id", None)
        if policy_id:
            feats[f"trace_policy__{policy_id}"] = 1.0
    return feats


# 文本 provider 签名：``(index, artifact, trace) -> (skill_md_text, plan_yaml_text)``。
# 任一文本为 None 跳过该层 token 特征。caller 自己读文件（pure audit 模块不做 IO）。
ArtifactTextProvider = Callable[
    [int, Any, Optional[Any]], Tuple[Optional[str], Optional[str]]
]


def adversarial_reconstruction_audit_artifact(
    artifact_trace_pairs: Sequence[Tuple[Any, Optional[Any]]],
    prior_baseline_rate: float,
    *,
    label_provider: Optional[Callable[[Tuple[Any, Any]], int]] = None,
    private_labels: Optional[Sequence[int]] = None,
    text_provider: Optional[ArtifactTextProvider] = None,
    threshold: float = RECONSTRUCTION_DELTA_THRESHOLD,
) -> Tuple[bool, float]:
    """spec v1 §11.9 v1.1 artifact 端 reconstruction probe audit（步骤 2 实现）。

    与旧 `adversarial_reconstruction_audit`（trace-focused）的区别：
    - 输入是 ``(artifact, activation_trace)`` pair 序列，不是 raw trace
    - probe feature 提取 artifact DTO 字段 + ``SKILL.md`` 文本 token bag +
      ``plan.yaml`` 文本 token bag + activation 轨迹
    - label = 该 (artifact, trace) 上 W2 expected outcome（evaluator private side）

    流程：
        1. 对每个 ``(artifact_i, trace_i)``，可选地通过 ``text_provider`` 拿到
           该 artifact 的 ``SKILL.md`` / ``plan.yaml`` 文本，调
           `_extract_artifact_probe_features` 得稀疏 feature dict；
        2. label 来自 ``label_provider(pair)`` 或 ``private_labels`` 显式序列；
           本模块不读 raw W2，label 计算责任在 evaluator；
        3. 训 fixed-seed logistic regression（沿用 `_logreg_train_predict`）；
        4. 比较 ``probe_accuracy`` vs ``prior_baseline_rate``；
        5. 若 delta > threshold（默认 0.05），**artifact fail**，candidate 不能
           promote draft → active。

    工程边界（防扩散）：audit 模块本身不读 ``package_uri`` 指向的 SKILL.md /
    plan.yaml 文件。caller（promotion gate / audit harness）从 SkillPackage 拿
    ``package_uri``，调 `evo/skill_package.py::parse_skill_md_view()` +
    `parse_plan_yaml()` 读出文本后，通过 ``text_provider`` 喂进来。

    参数：
        artifact_trace_pairs: (artifact, activation_trace) 对序列。trace 可
            为 None（仅 artifact 内容 audit）。
        prior_baseline_rate: 多数类 prior accuracy（evaluator 给出）。
        label_provider: ``(pair) -> 0/1`` 标签函数；与 ``private_labels`` 互斥。
        private_labels: 与 pairs 等长的显式 label 序列。
        text_provider: 可选 ``(idx, artifact, trace) -> (skill_md_text,
            plan_yaml_text)``；返回 None 跳过对应 token 特征。不传 → SKILL.md /
            plan.yaml token 层不进 feature（向后兼容旧 caller，但风险：含
            raw W2 token 的恶意 SKILL.md 可 bypass artifact-blocklist 审查）。
        threshold: spec v1 §11.9 默认 0.05。

    返回：``(passed: bool, delta: float)``。

    异常：``ValueError`` 当 label 缺失 / 长度不匹配。
    """
    if label_provider is None and private_labels is None:
        raise ValueError(
            "必须提供 label_provider 或 private_labels；本模块不读 raw W2"
        )
    if label_provider is not None and private_labels is not None:
        raise ValueError("label_provider 与 private_labels 互斥，只能传其一")
    if private_labels is not None and len(private_labels) != len(artifact_trace_pairs):
        raise ValueError("private_labels 必须与 artifact_trace_pairs 等长")
    if not artifact_trace_pairs:
        return True, 0.0

    feature_dicts: List[Dict[str, float]] = []
    for idx, (art, trace) in enumerate(artifact_trace_pairs):
        md_text: Optional[str] = None
        plan_text: Optional[str] = None
        if text_provider is not None:
            md_text, plan_text = text_provider(idx, art, trace)
        feature_dicts.append(
            _extract_artifact_probe_features(
                art,
                trace,
                skill_md_text=md_text,
                plan_yaml_text=plan_text,
            )
        )
    if label_provider is not None:
        labels = [int(label_provider(pair)) for pair in artifact_trace_pairs]
    else:
        labels = [int(x) for x in private_labels]  # type: ignore[union-attr]

    preds = _logreg_train_predict(feature_dicts, labels)
    correct = sum(1 for p, y in zip(preds, labels) if p == y)
    probe_accuracy = correct / len(labels)
    delta = probe_accuracy - float(prior_baseline_rate)
    passed = delta <= threshold
    return passed, delta


def adversarial_reconstruction_audit_artifact_detailed(
    artifact_trace_pairs: Sequence[Tuple[Any, Optional[Any]]],
    prior_baseline_rate: float,
    *,
    label_provider: Optional[Callable[[Tuple[Any, Any]], int]] = None,
    private_labels: Optional[Sequence[int]] = None,
    text_provider: Optional[ArtifactTextProvider] = None,
    threshold: float = RECONSTRUCTION_DELTA_THRESHOLD,
) -> AdversarialAuditReport:
    """`adversarial_reconstruction_audit_artifact` 的 verbose 版。"""
    passed, delta = adversarial_reconstruction_audit_artifact(
        artifact_trace_pairs,
        prior_baseline_rate,
        label_provider=label_provider,
        private_labels=private_labels,
        text_provider=text_provider,
        threshold=threshold,
    )
    feature_keys: set = set()
    for idx, (art, trace) in enumerate(artifact_trace_pairs):
        md_text: Optional[str] = None
        plan_text: Optional[str] = None
        if text_provider is not None:
            md_text, plan_text = text_provider(idx, art, trace)
        for k in _extract_artifact_probe_features(
            art,
            trace,
            skill_md_text=md_text,
            plan_yaml_text=plan_text,
        ):
            feature_keys.add(k)
    return AdversarialAuditReport(
        passed=passed,
        probe_accuracy=delta + float(prior_baseline_rate),
        prior_accuracy=float(prior_baseline_rate),
        delta=delta,
        sample_count=len(artifact_trace_pairs),
        feature_count=len(feature_keys),
    )


def _majority_class_accuracy(labels: Sequence[int]) -> float:
    if not labels:
        return 0.0
    counter = Counter(labels)
    return counter.most_common(1)[0][1] / len(labels)


def _logreg_train_predict(
    feature_dicts: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    *,
    seed: int = PROBE_RANDOM_SEED,
    epochs: int = 200,
    lr: float = 1.0,
) -> List[int]:
    """极简 logistic regression：固定 seed，输入 sparse dict 特征 + 二值 label。

    返回每条样本的 predicted label。不依赖 numpy/sklearn。
    """
    rng = random.Random(seed)
    # 构建全局特征字典 index
    feature_keys = sorted({k for d in feature_dicts for k in d})
    if not feature_keys:
        # 无特征 → 全部预测多数类
        majority = Counter(labels).most_common(1)[0][0] if labels else 0
        return [majority] * len(labels)

    # Per-feature z-score normalization：让不同 scale 的 feature（如
    # `experiment_budgets=[8,16,32]` vs `ranking_weights=0.3-1.0`）在同一
    # 数值区间，避免 large-scale feature 主导初期 logit 让 sigmoid 饱和。
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
        # 数值稳定
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    for _ in range(epochs):
        # 简单 batch GD（小数据足够），feature 用 z-score normalized 值
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

    preds: List[int] = []
    for feats in feature_dicts:
        z = bias + sum(weights[k] * _norm(feats, k) for k in feature_keys)
        preds.append(1 if sigmoid(z) >= 0.5 else 0)
    return preds


@dataclass
class AdversarialAuditReport:
    """spec v1 §11.9 audit 输出。

    ``passed=False`` 时 spec §11.9 第 6 步：``合并 taxonomy、提高 k、增加 delay、
    减少 metric precision、suppress cells`` —— 这是下游运维动作，本模块只给
    诊断结果。
    """

    passed: bool
    probe_accuracy: float
    prior_accuracy: float
    delta: float
    sample_count: int
    feature_count: int

    def metrics_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "probe_accuracy": self.probe_accuracy,
            "prior_accuracy": self.prior_accuracy,
            "delta": self.delta,
            "sample_count": self.sample_count,
            "feature_count": self.feature_count,
        }


def adversarial_reconstruction_audit(
    agent_visible_traces: Sequence[Any],
    sanitized_feedback: Sequence[Any],
    prior_baseline_rate: float,
    *,
    label_provider: Optional[Callable[[Any], int]] = None,
    private_labels: Optional[Sequence[int]] = None,
    threshold: float = RECONSTRUCTION_DELTA_THRESHOLD,
) -> Tuple[bool, float]:
    """spec v1 §11.9 W2 reconstruction probe audit（v1.1 重定位至 artifact 端）。

    流程：
        1. 对每个 ``agent_visible_traces[i]`` 抽取 probe 特征（spec §11.9
           允许特征清单：rule family counts / reason counts / Skill activations
           / policy version / feedback bucket）；
        2. label 来自 evaluator private side（``label_provider(trace)`` 或
           ``private_labels``）；**本模块不读 raw W2**，label 计算责任在
           evaluator 上；
        3. 用固定 seed 的极简 logistic regression 训 + 预测；
        4. 比较 ``probe_accuracy`` 与 ``prior_baseline_rate``；
        5. 若 ``probe_accuracy - prior_baseline_rate > 0.05``（``threshold``），
           audit fail，返回 ``(False, delta)``。

    **v1.1 §11.9 重定位（spec §0.6 修订 1）**：audit 焦点从 sanitized packet
    改为 candidate artifact。新代码 caller 应传：
        - ``features``：candidate artifact 的可观测内容（Skill `skill.json`
          字段、`SKILL.md` 文本、`plan.yaml` 步骤、EvoPolicyVersion 各
          weight/threshold 字段）+ 该 artifact 在 held-out run 上的 activation
          轨迹（可用 trace-like 对象拼装）；
        - ``label``：在 evaluator private side 使用 held-out run 的 W2
          expected outcome。

    fail 后策略（spec §11.9 v1.1）：
        - 检查 artifact 文本是否含 forbidden token（应已由 Gate 0 拦住）；
        - 检查 ``ranking_weights`` / ``candidate_cutoff_policy`` 是否对某
          case-specific 维度赋了异常权重；
        - 重训练 trainer，加更强的 regularization；
        - 减少 trainer 输入的 raw W2 维度（不删 raw 访问，但限制 feature
          engineering 维度）。

    参数：
        agent_visible_traces: trace-like 对象序列（v1.1 后建议每个对象内嵌
            artifact 特征 + activation 轨迹；旧接口仍兼容 raw EvoRunTrace）。
        sanitized_feedback: SanitizedFeedbackPacket 序列（v1.1 后可选；
            artifact 端 audit 不强依赖 packet）。
        prior_baseline_rate: 多数类基线（evaluator 提供）。
        label_provider: ``(trace) -> 0/1`` 标签函数（evaluator private side）；
            ``private_labels`` 互斥。
        private_labels: 显式 label 序列；与 traces 等长。
        threshold: spec v1 §11.9 默认 0.05。

    返回：``(passed: bool, delta: float)``；``delta = probe_acc - prior_acc``。

    异常：``ValueError`` 当 label 缺失 / 长度不匹配。
    """
    if label_provider is None and private_labels is None:
        raise ValueError(
            "必须提供 label_provider 或 private_labels；本模块不读 raw W2"
        )
    if label_provider is not None and private_labels is not None:
        raise ValueError(
            "label_provider 与 private_labels 互斥，只能传其一"
        )
    if private_labels is not None and len(private_labels) != len(
        agent_visible_traces
    ):
        raise ValueError("private_labels 必须与 traces 等长")

    if not agent_visible_traces:
        return True, 0.0

    feature_dicts = [
        _extract_probe_features(t, sanitized_feedback) for t in agent_visible_traces
    ]
    if label_provider is not None:
        labels = [int(label_provider(t)) for t in agent_visible_traces]
    else:
        labels = [int(x) for x in private_labels]  # type: ignore[union-attr]

    preds = _logreg_train_predict(feature_dicts, labels)
    correct = sum(1 for p, y in zip(preds, labels) if p == y)
    probe_accuracy = correct / len(labels)
    delta = probe_accuracy - float(prior_baseline_rate)
    passed = delta <= threshold
    return passed, delta


def adversarial_reconstruction_audit_detailed(
    agent_visible_traces: Sequence[Any],
    sanitized_feedback: Sequence[Any],
    prior_baseline_rate: float,
    *,
    label_provider: Optional[Callable[[Any], int]] = None,
    private_labels: Optional[Sequence[int]] = None,
    threshold: float = RECONSTRUCTION_DELTA_THRESHOLD,
) -> AdversarialAuditReport:
    """``adversarial_reconstruction_audit`` 的 verbose 版，返回完整 report。"""
    passed, delta = adversarial_reconstruction_audit(
        agent_visible_traces,
        sanitized_feedback,
        prior_baseline_rate,
        label_provider=label_provider,
        private_labels=private_labels,
        threshold=threshold,
    )
    feature_keys = {
        k
        for t in agent_visible_traces
        for k in _extract_probe_features(t, sanitized_feedback)
    }
    return AdversarialAuditReport(
        passed=passed,
        probe_accuracy=delta + float(prior_baseline_rate),
        prior_accuracy=float(prior_baseline_rate),
        delta=delta,
        sample_count=len(agent_visible_traces),
        feature_count=len(feature_keys),
    )


# ---------------------------------------------------------------------------
# §11.10 Counterfactual Swap Audit
# ---------------------------------------------------------------------------


def _packet_text_signature(packet: Any) -> str:
    """提取 packet 的 deterministic 文本签名（用于 swap 后对比）。

    包含：``aggregation_level`` / cell ``dimension`` / ``metric_name`` /
    ``metric_bucket`` / ``delta_bucket`` / ``suppressed`` / ``suggested_evo_action``。
    **不** 包含 ``created_at`` / ``released_at`` / 任何 id（防止时间/uuid 漂移）。
    """
    parts: List[str] = []
    parts.append(str(getattr(packet, "aggregation_level", "")))
    for cell in getattr(packet, "cells", []) or []:
        dim = getattr(cell, "dimension", {}) or {}
        dim_str = "|".join(f"{k}={v}" for k, v in sorted(dim.items()))
        parts.append(
            f"cell:{dim_str}:{getattr(cell, 'metric_name', '')}:"
            f"{getattr(cell, 'metric_bucket', '')}:"
            f"{getattr(cell, 'delta_bucket', '')}:"
            f"sup={getattr(cell, 'suppressed', False)}:"
            f"act={getattr(cell, 'suggested_evo_action', '')}"
        )
    return "||".join(parts)


def _extract_metric_floats(packet: Any) -> Dict[Tuple[str, str], float]:
    """从 packet cell 中提 ``(dimension_signature, metric_name) -> metric_value``。

    ``metric_bucket`` 若是 ``"low"/"medium"/"high"`` 字符串则映射 0/0.5/1；
    若是 ``"0.05"`` 等 numeric string 则 float()；其余跳过。
    """
    bucket_map = {"low": 0.0, "medium": 0.5, "high": 1.0}
    out: Dict[Tuple[str, str], float] = {}
    for cell in getattr(packet, "cells", []) or []:
        if getattr(cell, "suppressed", False):
            continue
        dim = getattr(cell, "dimension", {}) or {}
        dim_sig = "|".join(f"{k}={v}" for k, v in sorted(dim.items()))
        bucket = getattr(cell, "metric_bucket", None)
        if bucket is None:
            continue
        if isinstance(bucket, str) and bucket in bucket_map:
            value = bucket_map[bucket]
        else:
            try:
                value = float(bucket)
            except (TypeError, ValueError):
                continue
        out[(dim_sig, str(getattr(cell, "metric_name", "")))] = value
    return out


def _new_case_specific_dimension(
    original_packet: Any, swapped_packet: Any
) -> bool:
    """判定 swap 后是否出现新的 case-specific dimension key（如 ``case_id`` /
    ``run_id`` / ``building_id``）。"""
    case_specific_keys = {
        "case_id",
        "run_id",
        "building_id",
        "trace_id",
        "obligation_id",
    }
    for pkt in (original_packet, swapped_packet):
        for cell in getattr(pkt, "cells", []) or []:
            dim = getattr(cell, "dimension", {}) or {}
            if case_specific_keys & set(dim.keys()):
                return True
    return False


def _new_free_text_hint(
    original_packet: Any, swapped_packet: Any
) -> bool:
    """判定 swap 前后是否出现新自由文本字段（spec §8.4 broker 不应输出 free text）。"""
    # SanitizedFeedbackPacket / FeedbackCell schema 不含 free-text 字段；
    # 这里检查是否有 dimension value 含 100 char+ 的字符串（典型自由文本指纹）
    for pkt in (original_packet, swapped_packet):
        for cell in getattr(pkt, "cells", []) or []:
            dim = getattr(cell, "dimension", {}) or {}
            for v in dim.values():
                if isinstance(v, str) and len(v) > 100:
                    return True
    return False


@dataclass
class CounterfactualSwapReport:
    """spec v1 §11.10 counterfactual swap 详细报告。"""

    passed: bool
    metric_delta: float
    no_new_case_specific_dimension: bool
    no_new_free_text_hint: bool
    swap_strategy: str

    def metrics_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "metric_delta": self.metric_delta,
            "no_new_case_specific_dimension": self.no_new_case_specific_dimension,
            "no_new_free_text_hint": self.no_new_free_text_hint,
            "swap_strategy": self.swap_strategy,
        }


def counterfactual_swap_audit(
    broker: Any,
    eval_truth_report: Mapping[str, Any],
    swap_strategy: Literal["swap_labels", "shuffle_batch_membership"],
    *,
    threshold: float = COUNTERFACTUAL_METRIC_THRESHOLD,
) -> bool:
    """spec v1 §11.10 counterfactual swap audit。

    流程：
        1. 用 ``broker.publish(eval_truth_report)`` 拿到原始 packet；
        2. 按 ``swap_strategy`` 在 evaluator private side 创建反事实
           ``eval_truth_report``：
           - ``swap_labels``：在同 aggregate bucket 内交换 W2 labels；
           - ``shuffle_batch_membership``：打乱 batch membership；
        3. 重跑 ``broker.publish(swapped_report)`` 拿到 swapped packet；
        4. 比较 unsuppressed cell metric 差与新维度 / 新自由文本。

    通过条件（spec §11.10）：
        - ``packet_delta_after_single_case_swap <= 0.05``
        - ``no_new_case_specific_dimension``
        - ``no_new_free_text_hint``

    参数：
        broker: 需实现 ``publish(eval_truth_report) -> SanitizedFeedbackPacket``
            的对象（H 代理在 ``evo/feedback_broker.py`` 落地实际 broker；
            本函数通过 duck-typing 调用）。
        eval_truth_report: 原始 raw EvalTruthReport（evaluator private side）。
            **本函数仅传递，不读字段**；broker 自己 sanitize。
        swap_strategy: ``swap_labels`` 或 ``shuffle_batch_membership``。
        threshold: spec v1 §11.10 默认 0.05。

    返回：``passed: bool``。

    异常：``ValueError`` 当 swap_strategy 非法 / broker 缺 publish。
    """
    if swap_strategy not in ("swap_labels", "shuffle_batch_membership"):
        raise ValueError(f"非法 swap_strategy: {swap_strategy}")
    if not hasattr(broker, "publish"):
        raise ValueError("broker 必须实现 publish(eval_truth_report)")

    original_packet = broker.publish(eval_truth_report)
    swapped_report = _swap_single_case(eval_truth_report, swap_strategy)
    swapped_packet = broker.publish(swapped_report)

    # 同 (dim_sig, metric_name) 上比较 numeric metric delta
    orig_metrics = _extract_metric_floats(original_packet)
    swap_metrics = _extract_metric_floats(swapped_packet)
    keys = set(orig_metrics) & set(swap_metrics)
    if not keys:
        max_delta = 0.0
    else:
        max_delta = max(abs(orig_metrics[k] - swap_metrics[k]) for k in keys)

    no_new_dim = not _new_case_specific_dimension(original_packet, swapped_packet)
    no_new_text = not _new_free_text_hint(original_packet, swapped_packet)
    passed = max_delta <= threshold and no_new_dim and no_new_text
    return passed


def counterfactual_swap_audit_detailed(
    broker: Any,
    eval_truth_report: Mapping[str, Any],
    swap_strategy: Literal["swap_labels", "shuffle_batch_membership"],
    *,
    threshold: float = COUNTERFACTUAL_METRIC_THRESHOLD,
) -> CounterfactualSwapReport:
    """verbose 版，返回完整 report。"""
    if swap_strategy not in ("swap_labels", "shuffle_batch_membership"):
        raise ValueError(f"非法 swap_strategy: {swap_strategy}")
    if not hasattr(broker, "publish"):
        raise ValueError("broker 必须实现 publish(eval_truth_report)")
    original_packet = broker.publish(eval_truth_report)
    swapped_report = _swap_single_case(eval_truth_report, swap_strategy)
    swapped_packet = broker.publish(swapped_report)
    orig_metrics = _extract_metric_floats(original_packet)
    swap_metrics = _extract_metric_floats(swapped_packet)
    keys = set(orig_metrics) & set(swap_metrics)
    max_delta = (
        max(abs(orig_metrics[k] - swap_metrics[k]) for k in keys) if keys else 0.0
    )
    no_new_dim = not _new_case_specific_dimension(original_packet, swapped_packet)
    no_new_text = not _new_free_text_hint(original_packet, swapped_packet)
    passed = max_delta <= threshold and no_new_dim and no_new_text
    return CounterfactualSwapReport(
        passed=passed,
        metric_delta=max_delta,
        no_new_case_specific_dimension=no_new_dim,
        no_new_free_text_hint=no_new_text,
        swap_strategy=swap_strategy,
    )


def _swap_single_case(
    eval_truth_report: Mapping[str, Any], strategy: str
) -> Dict[str, Any]:
    """在 evaluator private side 模拟单 case swap。

    eval_truth_report 形态：``{"cases": [{"case_id": ..., "label": ..., "bucket": ...}, ...]}``。
    只在内存中 deep copy + swap，不写盘。

    spec §11.10 第 2 步：``swap W2 labels within same aggregate bucket``。
    """
    cases = list(eval_truth_report.get("cases", []) or [])
    if len(cases) < 2:
        return dict(eval_truth_report)
    swapped = [dict(c) for c in cases]
    if strategy == "swap_labels":
        # 找同 bucket 的两 case 交换 label
        by_bucket: Dict[str, List[int]] = {}
        for idx, c in enumerate(swapped):
            by_bucket.setdefault(str(c.get("bucket", "__none__")), []).append(idx)
        for bucket, indices in by_bucket.items():
            if len(indices) >= 2:
                i, j = indices[0], indices[1]
                swapped[i]["label"], swapped[j]["label"] = (
                    swapped[j].get("label"),
                    swapped[i].get("label"),
                )
                break
    elif strategy == "shuffle_batch_membership":
        # 把第一个 case 的 bucket 改为最后一个 case 的 bucket
        if swapped:
            swapped[0]["bucket"] = swapped[-1].get("bucket")
    out = dict(eval_truth_report)
    out["cases"] = swapped
    return out


# ---------------------------------------------------------------------------
# §13 leakage audit：6 项 baseline + evo 专属扩展
# ---------------------------------------------------------------------------


# v0.4 / spec v1 §13.1 6 项 baseline leakage metric 名（保命名一致）
BASELINE_LEAKAGE_METRICS: Tuple[str, ...] = (
    "forbidden_source_loaded",
    "forbidden_label_in_kg",
    "forbidden_property_in_kg",
    "expected_verdict_text_leak",
    "basis_item_id_leak",
    "evaluator_store_access",
)

# spec v1 §13 evo 专属新增 metric 名
# v1.1 §11.11 修订：``policy_version_raw_w2_in_training_set`` 改名为
# ``policy_artifact_contains_raw_w2`` —— audit 焦点从 "trainer 输入有无 raw W2"
# 改为 "trainer 输出 artifact 是否含 raw W2 token"（trainer 输入端 v1.1 允许
# 读 raw，约束移至 artifact 端）。
EVO_LEAKAGE_METRICS: Tuple[str, ...] = (
    "broker_output_forbidden_field",
    "evo_memory_store_namespace_violation",
    "skill_package_forbidden_actions_hard5_missing",
    "policy_artifact_contains_raw_w2",
    "report_feedback_metric_leak",
)


def _scan_broker_output_forbidden_field(
    packets: Sequence[Any],
) -> bool:
    """spec v1 §13 evo 专属：broker output 若含 forbidden field（如 raw
    expected_verdict / basis_id / projection_id / run_id / building_id）→ fail。
    """
    forbidden_tokens = {
        "expected_verdict",
        "projection_id",
        "basis_id",
        "run_id",
        "building_id",
        "trace_id",
    }
    for pkt in packets:
        for cell in getattr(pkt, "cells", []) or []:
            dim = getattr(cell, "dimension", {}) or {}
            for k in dim.keys():
                if k in forbidden_tokens:
                    return True
    return False


def _scan_evo_memory_store_namespace(
    store_configs: Sequence[Any],
) -> bool:
    """spec v1 §13 evo 专属：EvoMemoryStoreConfig 必须
    ``runtime_agent_direct_read=False`` + ``evaluator_raw_truth_read=False``。"""
    for cfg in store_configs:
        if getattr(cfg, "runtime_agent_direct_read", False):
            return True
        if getattr(cfg, "evaluator_raw_truth_read", False):
            return True
    return False


def _scan_skill_package_forbidden_actions(skills: Sequence[Any]) -> bool:
    """spec v1 §10.2 + §9.4.1 Gate 0：SkillPackage ``forbidden_actions`` 必须
    含 5 个 hard 项（缺一即 fail）。"""
    required = {
        "override_verifier",
        "force_allow_stop",
        "emit_final_verdict",
        "read_evaluator_truth",
        "suppress_rule_candidate",
    }
    for skill in skills:
        actions = set(getattr(skill, "forbidden_actions", []) or [])
        if not required.issubset(actions):
            return True
    return False


def _scan_policy_artifact_raw_w2(policy_versions: Sequence[Any]) -> bool:
    """spec v1 §11.11（v1.1 修订）：审 EvoPolicyVersion **artifact 输出端**
    是否含 raw W2 token / case-specific truth value。

    **v1.1 §11.11 修订背景**：v1.0 这里审 trainer 输入路径（``trained_on_*``）
    是否含 raw W2 关键字；v1.1 取消该约束（trainer 输入端 v1.1 允许读 raw W2，
    见 §0.6 修订 1 + §2.5 凭证修订）。新审计落点改为 **artifact 输出端**：
    candidate / active EvoPolicyVersion artifact 的可观测字段（ranking_weights /
    candidate_cutoff_policy / 等）是否含 raw W2 token（如 ``expected_verdict`` /
    ``w2_truth`` / ``basis_item`` 字符串字面量）。

    审计范围：
        - ``ranking_weights`` 字段名（key）；
        - ``tool_preferences`` / ``skill_activation_order`` /
          ``open_obligation_priority`` / ``candidate_cutoff_policy`` /
          ``report_template_policy`` / ``fallback_thresholds``
          内任何嵌套字符串。

    返回 True = fail（artifact 含 raw W2 token）。
    """
    forbidden_tokens = (
        "expected_verdict",
        "raw_eval_truth",
        "w2_truth",
        "truth_label",
        "expected_label",
        "reference_outcome",
        "w2_basis_ref",
        "basis_item_id",
        "projection_cell_id",
        "w2_threshold_truth",
        "w2_observed_value",
        "w2_expected_operator",
        "leaked_expected_verdict",
        "feedback_truth_comment",
    )

    def _scan_obj(obj: Any) -> bool:
        if isinstance(obj, str):
            low = obj.lower()
            return any(t in low for t in forbidden_tokens)
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                if isinstance(k, str) and any(t in k.lower() for t in forbidden_tokens):
                    return True
                if _scan_obj(v):
                    return True
            return False
        if isinstance(obj, (list, tuple, set)):
            return any(_scan_obj(item) for item in obj)
        return False

    artifact_fields = (
        "ranking_weights",
        "tool_preferences",
        "skill_activation_order",
        "open_obligation_priority",
        "candidate_cutoff_policy",
        "report_template_policy",
        "fallback_thresholds",
        "validation_summary",
    )
    for pv in policy_versions:
        for field_name in artifact_fields:
            field_val = getattr(pv, field_name, None)
            if field_val is None:
                continue
            if _scan_obj(field_val):
                return True
    return False


def _scan_report_feedback_leak(reports: Sequence[str]) -> bool:
    """spec v1 §13.2.6：report 不得显示 feedback metric / expected verdict /
    basis item。本扫描查 reports 文本是否含 ``feedback_packet`` /
    ``expected_verdict`` / ``basis_id`` 字面 token。"""
    tokens = ("feedback_packet", "expected_verdict", "basis_id", "projection_id")
    for r in reports:
        if any(t in str(r).lower() for t in tokens):
            return True
    return False


def leakage_audit_six_metrics(
    eval_inputs: Mapping[str, Any],
) -> Dict[str, bool]:
    """spec v1 §13 leakage 复合审计：baseline 6 项 + evo 5 项扩展。

    输入 ``eval_inputs`` dict，键支持：

    - ``baseline_metrics``: dict[str, bool]，复用 v0.4 leakage_audit
      ``LeakageAuditResult.metrics_dict()`` 输出；缺失视作未审计 → True (fail)。
    - ``feedback_packets``: SanitizedFeedbackPacket 序列；用于
      ``broker_output_forbidden_field`` 扫描。
    - ``memory_store_configs``: EvoMemoryStoreConfig 序列；用于 namespace 扫描。
    - ``skills``: SkillJson 序列；用于 ``forbidden_actions`` 5 hard 项扫描。
    - ``policy_versions``: EvoPolicyVersion 序列；用于 training set 扫描。
    - ``reports``: report 文本序列；用于 feedback_metric leak 扫描。

    返回：dict[str, bool] 11 个 key（6 baseline + 5 evo），值 True = fail。

    spec v1 §13 ``release_gate``：任一 fail → release 不得 active。
    """
    baseline_metrics = eval_inputs.get("baseline_metrics", {}) or {}
    out: Dict[str, bool] = {}
    for k in BASELINE_LEAKAGE_METRICS:
        # baseline_metrics 中若没该 key，视为未审计 → 保守判 True (fail)
        out[k] = bool(baseline_metrics.get(k, True))

    out["broker_output_forbidden_field"] = _scan_broker_output_forbidden_field(
        eval_inputs.get("feedback_packets", []) or []
    )
    out["evo_memory_store_namespace_violation"] = _scan_evo_memory_store_namespace(
        eval_inputs.get("memory_store_configs", []) or []
    )
    out["skill_package_forbidden_actions_hard5_missing"] = (
        _scan_skill_package_forbidden_actions(eval_inputs.get("skills", []) or [])
    )
    # v1.1 §11.11 重定位：审 artifact 输出端而非 trainer 输入端
    out["policy_artifact_contains_raw_w2"] = _scan_policy_artifact_raw_w2(
        eval_inputs.get("policy_versions", []) or []
    )
    out["report_feedback_metric_leak"] = _scan_report_feedback_leak(
        eval_inputs.get("reports", []) or []
    )
    return out


__all__ = [
    "RECONSTRUCTION_DELTA_THRESHOLD",
    "COUNTERFACTUAL_METRIC_THRESHOLD",
    "PROBE_RANDOM_SEED",
    "BASELINE_LEAKAGE_METRICS",
    "EVO_LEAKAGE_METRICS",
    "AdversarialAuditReport",
    "ArtifactTextProvider",
    "CounterfactualSwapReport",
    "adversarial_reconstruction_audit",
    "adversarial_reconstruction_audit_artifact",
    "adversarial_reconstruction_audit_artifact_detailed",
    "adversarial_reconstruction_audit_detailed",
    "counterfactual_swap_audit",
    "counterfactual_swap_audit_detailed",
    "leakage_audit_six_metrics",
]
