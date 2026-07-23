"""Evo 反推 / 反事实 / 泄漏审计测试（spec v1 §11.9 + §11.10 + §13）。

覆盖：
- adversarial reconstruction：
  - probe 信号过强（label 与单一特征强相关）→ delta>0.05 → passed=False；
  - probe 信号不存在（label 与特征独立）→ passed=True；
  - label_provider 与 private_labels 互斥校验；
  - 必须提供 label 校验；
  - 空 traces 提早返；
- counterfactual swap：
  - dumb broker（输出与输入无关）→ swap 后 packet 不变 → passed=True；
  - leaky broker（label swap 导致 cell metric 大变）→ passed=False；
  - 非法 strategy 抛错；
  - broker 缺 publish 抛错；
- leakage_audit_six_metrics：
  - baseline 6 项全 pass + evo 5 项全 pass；
  - missing baseline_metrics → 保守 fail；
  - broker output 含 expected_verdict dimension → fail；
  - EvoMemoryStore namespace 违规 → fail；
  - SkillPackage forbidden_actions 缺 5 hard 项 → fail；
  - PolicyVersion training set 含 W2 路径 → fail；
  - report 含 feedback_packet token → fail。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

import pytest

from evo_agent_baseline.evo.audits import (
    BASELINE_LEAKAGE_METRICS,
    EVO_LEAKAGE_METRICS,
    PROBE_RANDOM_SEED,
    adversarial_reconstruction_audit,
    adversarial_reconstruction_audit_artifact,
    adversarial_reconstruction_audit_artifact_detailed,
    adversarial_reconstruction_audit_detailed,
    counterfactual_swap_audit,
    counterfactual_swap_audit_detailed,
    leakage_audit_six_metrics,
)
from evo_agent_baseline.evo.audits import _extract_artifact_probe_features


# ---------------------------------------------------------------------------
# 简易 trace / packet / skill / policy / cell fixture
# ---------------------------------------------------------------------------


@dataclass
class _MockTrace:
    trace_id: str
    closure_summary: Dict[str, Any] = field(default_factory=dict)
    active_skill_version_ids: List[str] = field(default_factory=list)
    evo_policy_version_id: str = "policy.mbis.runtime.default.v1.0.0"


@dataclass
class _MockCell:
    dimension: Dict[str, str] = field(default_factory=dict)
    metric_name: str = "family_recall_delta"
    metric_bucket: str = "0.0"
    delta_bucket: str = None
    suppressed: bool = False
    suggested_evo_action: str = "none"


@dataclass
class _MockPacket:
    feedback_packet_id: str = "SFP-A"
    aggregation_level: str = "batch_rule_family"
    cells: List[_MockCell] = field(default_factory=list)


@dataclass
class _MockSkill:
    forbidden_actions: List[str] = field(default_factory=list)


@dataclass
class _MockPolicy:
    """v1.1 §11.11 修订：audit 焦点从 trainer 输入路径改为 artifact 输出字段。

    mock policy 暴露 artifact 端可观测字段（ranking_weights / tool_preferences /
    等）供 ``_scan_policy_artifact_raw_w2`` 扫描；trainer 输入端字段
    （``trained_on_replay_set_id`` / ``trained_on_feedback_packet_ids`` /
    新增 ``trained_on_artifacts``）保留供 schema 完整性测试，但不再触发 fail。
    """

    trained_on_replay_set_id: str = "rs-clean"
    trained_on_feedback_packet_ids: List[str] = field(default_factory=list)
    trained_on_artifacts: List[str] = field(default_factory=list)
    ranking_weights: dict = field(default_factory=dict)
    tool_preferences: dict = field(default_factory=dict)
    skill_activation_order: dict = field(default_factory=dict)
    open_obligation_priority: dict = field(default_factory=dict)
    candidate_cutoff_policy: dict = field(default_factory=dict)
    report_template_policy: dict = field(default_factory=dict)
    fallback_thresholds: dict = field(default_factory=dict)
    validation_summary: dict = field(default_factory=dict)


@dataclass
class _MockStoreConfig:
    runtime_agent_direct_read: bool = False
    evaluator_raw_truth_read: bool = False


# ---------------------------------------------------------------------------
# Adversarial reconstruction audit
# ---------------------------------------------------------------------------


def test_adversarial_audit_independent_features_passes() -> None:
    """label 与 trace 特征独立（label 随机切换） → probe 无信号 → delta 小."""
    # 12 trace，6 个一致同特征模式，label 交替 → 独立
    traces = []
    labels = []
    for i in range(12):
        t = _MockTrace(
            trace_id=f"T{i}",
            closure_summary={"rule_family_counts": {"structural": 1}},
        )
        traces.append(t)
        labels.append(i % 2)  # 0/1/0/1...
    prior = 0.5  # 多数类
    passed, delta = adversarial_reconstruction_audit(
        traces, [], prior_baseline_rate=prior, private_labels=labels
    )
    # probe 无法在独立 label 上 >0.5+0.05 = 0.55
    assert passed is True
    assert delta <= 0.05


def test_adversarial_audit_strong_signal_fails() -> None:
    """label 与单一特征完全相关 → probe 高 accuracy → delta>0.05 → fail."""
    traces = []
    labels = []
    for i in range(20):
        label = 1 if i < 10 else 0
        labels.append(label)
        # 关键：family count 完全决定 label
        family = "fam_A" if label == 1 else "fam_B"
        traces.append(
            _MockTrace(
                trace_id=f"T{i}",
                closure_summary={"rule_family_counts": {family: 1}},
            )
        )
    prior = 0.5
    passed, delta = adversarial_reconstruction_audit(
        traces, [], prior_baseline_rate=prior, private_labels=labels
    )
    # 简单 logreg 应能学到完美分类 → delta ≈ 0.5
    assert passed is False
    assert delta > 0.05


def test_adversarial_audit_requires_some_label_source() -> None:
    """必须提供 label_provider 或 private_labels（不能直接读 W2）。"""
    with pytest.raises(ValueError, match="必须提供 label_provider"):
        adversarial_reconstruction_audit(
            [_MockTrace("T1")], [], prior_baseline_rate=0.5
        )


def test_adversarial_audit_mutually_exclusive_label_sources() -> None:
    with pytest.raises(ValueError, match="互斥"):
        adversarial_reconstruction_audit(
            [_MockTrace("T1")],
            [],
            prior_baseline_rate=0.5,
            label_provider=lambda t: 1,
            private_labels=[1],
        )


def test_adversarial_audit_label_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="等长"):
        adversarial_reconstruction_audit(
            [_MockTrace("T1"), _MockTrace("T2")],
            [],
            prior_baseline_rate=0.5,
            private_labels=[1],
        )


def test_adversarial_audit_empty_traces_passes() -> None:
    """空 traces 提早返 True / delta=0."""
    passed, delta = adversarial_reconstruction_audit(
        [], [], prior_baseline_rate=0.5, private_labels=[]
    )
    assert passed is True
    assert delta == 0.0


def test_adversarial_audit_detailed_report_includes_metrics() -> None:
    traces = [_MockTrace(f"T{i}") for i in range(5)]
    labels = [0, 0, 0, 1, 1]
    report = adversarial_reconstruction_audit_detailed(
        traces, [], prior_baseline_rate=0.6, private_labels=labels
    )
    assert report.sample_count == 5
    d = report.metrics_dict()
    assert set(d.keys()) == {
        "passed",
        "probe_accuracy",
        "prior_accuracy",
        "delta",
        "sample_count",
        "feature_count",
    }


# ---------------------------------------------------------------------------
# Counterfactual swap audit
# ---------------------------------------------------------------------------


class _DumbBroker:
    """spec §11.10 通过条件下的合规 broker：输出与单 case 无关。"""

    def publish(self, eval_truth_report: Mapping[str, Any]) -> _MockPacket:
        return _MockPacket(
            cells=[
                _MockCell(
                    dimension={"semantic_slot_class": "artifact_evidence"},
                    metric_bucket="low",
                )
            ]
        )


class _LeakyBroker:
    """非合规 broker：cell 含 case_id dimension（spec §13 应被识别为 fail）。"""

    def publish(self, eval_truth_report: Mapping[str, Any]) -> _MockPacket:
        # 每次调用根据 first case label 切换 metric_bucket → swap 后会变
        first = (eval_truth_report.get("cases") or [{}])[0]
        bucket = "high" if first.get("label") == 1 else "low"
        return _MockPacket(
            cells=[
                _MockCell(
                    dimension={"case_id": str(first.get("case_id", "?"))},
                    metric_bucket=bucket,
                )
            ]
        )


def test_counterfactual_swap_dumb_broker_passes() -> None:
    """合规 broker 输出与单 case 无关 → swap 后 packet 不变 → pass."""
    report = {
        "cases": [
            {"case_id": "C1", "label": 1, "bucket": "B1"},
            {"case_id": "C2", "label": 0, "bucket": "B1"},
        ]
    }
    passed = counterfactual_swap_audit(_DumbBroker(), report, "swap_labels")
    assert passed is True


def test_counterfactual_swap_leaky_broker_fails_by_new_dimension() -> None:
    """leaky broker 输出含 case_id dimension → no_new_case_specific_dimension=False → fail."""
    report = {
        "cases": [
            {"case_id": "C1", "label": 1, "bucket": "B1"},
            {"case_id": "C2", "label": 0, "bucket": "B1"},
        ]
    }
    passed = counterfactual_swap_audit(_LeakyBroker(), report, "swap_labels")
    assert passed is False


def test_counterfactual_swap_leaky_broker_detailed_metric_delta() -> None:
    """leaky broker 在 swap label 后 metric_bucket 从 high 变 low → delta = 1.0 > 0.05."""
    report = {
        "cases": [
            {"case_id": "C1", "label": 1, "bucket": "B1"},
            {"case_id": "C2", "label": 0, "bucket": "B1"},
        ]
    }
    detailed = counterfactual_swap_audit_detailed(
        _LeakyBroker(), report, "swap_labels"
    )
    # cell dimension 在 swap 前后不同（case_id 改了），所以 (dim, metric) key
    # 几乎不会重合 → metric_delta = 0；但 new_case_specific_dimension=True 触发 fail
    assert detailed.passed is False
    assert detailed.no_new_case_specific_dimension is False


def test_counterfactual_swap_invalid_strategy_raises() -> None:
    with pytest.raises(ValueError, match="非法 swap_strategy"):
        counterfactual_swap_audit(
            _DumbBroker(), {"cases": []}, "random_strategy"  # type: ignore[arg-type]
        )


def test_counterfactual_swap_broker_missing_publish_raises() -> None:
    class _NoPublish:
        pass

    with pytest.raises(ValueError, match="必须实现 publish"):
        counterfactual_swap_audit(_NoPublish(), {"cases": []}, "swap_labels")


def test_counterfactual_swap_shuffle_strategy_works() -> None:
    """``shuffle_batch_membership`` 策略也可执行。"""
    report = {
        "cases": [
            {"case_id": "C1", "label": 1, "bucket": "B1"},
            {"case_id": "C2", "label": 0, "bucket": "B2"},
        ]
    }
    passed = counterfactual_swap_audit(
        _DumbBroker(), report, "shuffle_batch_membership"
    )
    assert passed is True


# ---------------------------------------------------------------------------
# leakage_audit_six_metrics（baseline 6 项 + evo 5 项）
# ---------------------------------------------------------------------------


def test_leakage_audit_baseline_all_pass_keys_present() -> None:
    """baseline_metrics 全 False（pass） + 无 evo 输入 → 11 个 key 都返."""
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
        }
    )
    for k in BASELINE_LEAKAGE_METRICS:
        assert k in out
    for k in EVO_LEAKAGE_METRICS:
        assert k in out


def test_leakage_audit_missing_baseline_metric_conservative_fail() -> None:
    """baseline_metrics 缺 ``forbidden_label_in_kg`` → 保守 fail=True."""
    out = leakage_audit_six_metrics(
        {"baseline_metrics": {"forbidden_source_loaded": False}}
    )
    # 缺失 key 都 True (fail)
    assert out["forbidden_label_in_kg"] is True
    # 提供 key 是 False
    assert out["forbidden_source_loaded"] is False


def test_leakage_audit_broker_output_with_expected_verdict_fails() -> None:
    """broker cell dimension 含 ``expected_verdict`` 字面 → fail."""
    pkt = _MockPacket(
        cells=[
            _MockCell(
                dimension={"expected_verdict": "pass"},
                metric_bucket="low",
            )
        ]
    )
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "feedback_packets": [pkt],
        }
    )
    assert out["broker_output_forbidden_field"] is True


def test_leakage_audit_evo_memory_store_runtime_read_fails() -> None:
    """EvoMemoryStoreConfig.runtime_agent_direct_read=True → fail."""
    cfg = _MockStoreConfig(runtime_agent_direct_read=True)
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "memory_store_configs": [cfg],
        }
    )
    assert out["evo_memory_store_namespace_violation"] is True


def test_leakage_audit_skill_missing_hard_forbidden_action_fails() -> None:
    """SkillPackage forbidden_actions 缺 5 hard 项之一（缺 force_allow_stop）→ fail."""
    skill = _MockSkill(
        forbidden_actions=[
            "override_verifier",
            # 缺 force_allow_stop
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ]
    )
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "skills": [skill],
        }
    )
    assert out["skill_package_forbidden_actions_hard5_missing"] is True


def test_leakage_audit_skill_with_all_five_hard_forbidden_passes() -> None:
    skill = _MockSkill(
        forbidden_actions=[
            "override_verifier",
            "force_allow_stop",
            "emit_final_verdict",
            "read_evaluator_truth",
            "suppress_rule_candidate",
        ]
    )
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "skills": [skill],
        }
    )
    assert out["skill_package_forbidden_actions_hard5_missing"] is False


def test_leakage_audit_policy_artifact_with_raw_w2_token_fails() -> None:
    """v1.1 §11.11 重定位：审 artifact 输出端字段是否含 raw W2 token。

    v1.0 旧版本审 trainer 输入路径（``trained_on_replay_set_id`` 含
    ``projections.parquet`` → fail）。v1.1 §0.6 修订 1 取消该约束（trainer 输入
    端 v1.1 允许读 raw W2），audit 焦点移至 artifact 输出字段。

    本测试用 ``ranking_weights`` 字段含 ``expected_verdict`` token 模拟 trainer
    输出 candidate artifact 残留 case-specific W2 信号的情况。
    """
    pol = _MockPolicy(
        ranking_weights={"expected_verdict_score": 0.5},
    )
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "policy_versions": [pol],
        }
    )
    assert out["policy_artifact_contains_raw_w2"] is True


def test_leakage_audit_policy_trainer_input_with_w2_path_does_not_fail() -> None:
    """v1.1 §0.6 修订 1：trainer 输入端 ``trained_on_*`` 含 raw W2 路径关键字
    不再触发 audit fail（trainer 工作流 blind 取消）。

    审计落点移至 artifact 输出端；trainer 自由读 raw W2 是 v1.1 设计意图
    （spec §9.7.1 + §2.5 凭证修订）。
    """
    pol = _MockPolicy(
        trained_on_replay_set_id="rs-with-projections.parquet",
        trained_on_artifacts=[
            "eval_truth_report:ETR-001:sha256:abc",
            "w2_artifact:projections.parquet:sha256:def",
        ],
    )
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "policy_versions": [pol],
        }
    )
    # v1.1：trainer 输入端含 raw W2 路径关键字不再触发 fail；
    # artifact 输出端（ranking_weights 等）干净，audit 通过。
    assert out["policy_artifact_contains_raw_w2"] is False


def test_leakage_audit_report_with_feedback_packet_token_fails() -> None:
    """report 文本含 ``feedback_packet`` → spec §13.2.6 fail."""
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "reports": ["报告引用 feedback_packet SFP-AAA 的 metric"],
        }
    )
    assert out["report_feedback_metric_leak"] is True


def test_leakage_audit_clean_inputs_all_evo_metrics_false() -> None:
    """全 clean 输入 → evo 5 项全 False（pass）."""
    out = leakage_audit_six_metrics(
        {
            "baseline_metrics": {k: False for k in BASELINE_LEAKAGE_METRICS},
            "feedback_packets": [_MockPacket(cells=[_MockCell()])],
            "memory_store_configs": [_MockStoreConfig()],
            "skills": [
                _MockSkill(
                    forbidden_actions=[
                        "override_verifier",
                        "force_allow_stop",
                        "emit_final_verdict",
                        "read_evaluator_truth",
                        "suppress_rule_candidate",
                    ]
                )
            ],
            "policy_versions": [_MockPolicy()],
            "reports": ["合规摘要，无敏感 token"],
        }
    )
    for k in EVO_LEAKAGE_METRICS:
        assert out[k] is False, f"clean input 下 {k} 不应 fail"


# ---------------------------------------------------------------------------
# B1 修复：artifact audit 接受 SKILL.md / plan.yaml 文本
# spec v1 §11.9 features 清单要求 SKILL.md 文本 + plan.yaml 步骤进 feature；
# 防 含 W2 truth token 的恶意 SKILL.md bypass artifact-blocklist 审查。
# ---------------------------------------------------------------------------


@dataclass
class _MockArtifact:
    """mock SkillPackage / EvoPolicyVersion artifact，最小 DTO 形态。"""

    artifact_id: str = "skill.test.v1"
    skill_kind: str = "micro_routing"
    ranking_weights: dict = field(default_factory=dict)


def test_extract_artifact_features_without_text_skips_token_layers() -> None:
    """不传 SKILL.md / plan.yaml 文本 → token 层 feature 为空（向后兼容）."""
    feats = _extract_artifact_probe_features(_MockArtifact())
    assert not any(k.startswith("skill_md__tok__") for k in feats)
    assert not any(k.startswith("plan_yaml__tok__") for k in feats)


def test_extract_artifact_features_with_skill_md_text_adds_tokens() -> None:
    """传 SKILL.md 文本 → 出现 ``skill_md__tok__<token>`` features."""
    md = "This skill reorders retrieval candidates. non-authoritative."
    feats = _extract_artifact_probe_features(
        _MockArtifact(), skill_md_text=md
    )
    # alphanumeric word + len>=3 后应至少捕到 reorders / retrieval / candidates
    assert "skill_md__tok__reorders" in feats
    assert "skill_md__tok__retrieval" in feats
    assert "skill_md__tok__candidates" in feats


def test_extract_artifact_features_with_plan_yaml_text_adds_tokens() -> None:
    """传 plan.yaml 文本 → 出现 ``plan_yaml__tok__<token>`` features."""
    plan = "plan_id: P1\nsteps:\n  - action: select_candidate\n"
    feats = _extract_artifact_probe_features(
        _MockArtifact(), plan_yaml_text=plan
    )
    assert "plan_yaml__tok__plan_id" in feats
    assert "plan_yaml__tok__steps" in feats
    assert "plan_yaml__tok__select_candidate" in feats


def test_extract_artifact_features_filters_short_tokens() -> None:
    """长度 < 3 的 token（如 ``is``, ``a``, ``in``）丢弃."""
    md = "a is in the skill"  # 仅 ``the`` / ``skill`` 长度 >= 3
    feats = _extract_artifact_probe_features(
        _MockArtifact(), skill_md_text=md
    )
    assert "skill_md__tok__the" in feats
    assert "skill_md__tok__skill" in feats
    assert "skill_md__tok__a" not in feats
    assert "skill_md__tok__is" not in feats
    assert "skill_md__tok__in" not in feats


def test_artifact_audit_malicious_skill_md_with_rule_family_token_fails() -> None:
    """B1 核心 fail case：含 ``rule_family_id`` token 的恶意 SKILL.md。

    场景：trainer 在 SKILL.md 文本里残留 case-specific W2 信号（rule_family_id
    在恶意 / leaky package 中按 label 直接写进文本）。audit 应该捕到文本 token
    与 label 强相关 → probe accuracy 远超 prior baseline → fail。

    模拟方式：
    - 12 个 artifact，按 label 在 SKILL.md 文本中嵌入不同 ``rule_family_id``
      字面 token（``mbis_envelope`` vs ``mbis_egress``）；
    - 不传 text_provider → audit 只看 DTO 字段，label 与 artifact 内容独立
      → 应当 pass（控制组）；
    - 传 text_provider → audit 看到文本 token，能完美分类 label → fail（关键断言）。
    """
    arts: list = []
    labels: list = []
    md_texts: dict = {}
    for i in range(12):
        label = i % 2
        labels.append(label)
        art = _MockArtifact(artifact_id=f"skill.test.v1.{i}")
        arts.append(art)
        # 模拟 trainer 在 SKILL.md 里残留 rule_family_id token
        # （应该被 audit 捕到，证明文本 token 进入 feature）
        family_token = "mbis_envelope_family" if label == 1 else "mbis_egress_family"
        md_texts[i] = (
            f"This skill operates on rule family rule_family_id "
            f"{family_token}. The retrieval ordering is reranked. "
            f"non-authoritative."
        )
    pairs = [(a, None) for a in arts]
    prior = 0.5

    # 控制组：不传 text_provider → audit 看不到 SKILL.md 文本 → 应当 pass
    passed_no_text, delta_no_text = adversarial_reconstruction_audit_artifact(
        pairs, prior, private_labels=labels
    )
    assert passed_no_text is True, (
        "控制组：audit 未接 SKILL.md 文本时，label 与 DTO 字段独立应 pass"
    )

    # 关键断言：传 text_provider 后 audit 看到文本 token → probe 完美分类 → fail
    def _provider(idx: int, _art, _trace):
        return md_texts[idx], None

    passed_with_text, delta_with_text = adversarial_reconstruction_audit_artifact(
        pairs, prior, private_labels=labels, text_provider=_provider
    )
    assert passed_with_text is False, (
        "B1 关键断言：含 rule_family_id token 的恶意 SKILL.md 文本应使 audit fail"
    )
    assert delta_with_text > 0.05, (
        f"probe delta={delta_with_text} 应远超 threshold=0.05"
    )


def test_artifact_audit_plan_yaml_text_with_rule_family_token_fails() -> None:
    """同 B1 场景，但泄漏 token 在 ``plan.yaml`` 文本而非 SKILL.md。

    覆盖 plan.yaml token 层也能驱动 audit fail，证明两层文本均进 feature。
    """
    arts: list = []
    labels: list = []
    plan_texts: dict = {}
    for i in range(12):
        label = i % 2
        labels.append(label)
        arts.append(_MockArtifact(artifact_id=f"skill.test.v1.{i}"))
        # plan.yaml 步骤里残留 family-discriminating token
        family_token = "mbis_envelope_family" if label == 1 else "mbis_egress_family"
        plan_texts[i] = (
            f"plan_id: P{i}\n"
            f"steps:\n"
            f"  - action: select_for_{family_token}\n"
        )
    pairs = [(a, None) for a in arts]
    prior = 0.5

    def _provider(idx: int, _art, _trace):
        return None, plan_texts[idx]

    passed, delta = adversarial_reconstruction_audit_artifact(
        pairs, prior, private_labels=labels, text_provider=_provider
    )
    assert passed is False
    assert delta > 0.05


def test_artifact_audit_detailed_counts_text_features() -> None:
    """detailed 版 ``feature_count`` 应当把文本 token 层计入."""
    arts = [_MockArtifact(artifact_id=f"a{i}") for i in range(4)]
    labels = [0, 0, 1, 1]
    pairs = [(a, None) for a in arts]

    # 不传 text → feature_count 仅来自 DTO 字段
    rep_no_text = adversarial_reconstruction_audit_artifact_detailed(
        pairs, 0.5, private_labels=labels
    )
    base_count = rep_no_text.feature_count

    # 传 text → feature_count 必涨（多了 SKILL.md token features）
    md_text = "retrieval reorders candidates non-authoritative behavior."

    def _provider(idx: int, _art, _trace):
        return md_text, None

    rep_with_text = adversarial_reconstruction_audit_artifact_detailed(
        pairs, 0.5, private_labels=labels, text_provider=_provider
    )
    assert rep_with_text.feature_count > base_count, (
        "传 SKILL.md 文本后 feature_count 应增长（token bag 入特征）"
    )


def test_load_skill_package_texts_drives_audit_fail(tmp_path) -> None:
    """端到端：用 `load_skill_package_texts` 从磁盘读 SKILL.md 文本喂 audit。

    验证 helper（caller 侧桥接）真能驱动 audit 看到磁盘上的 SKILL.md token。
    """
    from evo_agent_baseline.evo.skill_package import load_skill_package_texts

    # 构造两个 mock package_uri 目录，SKILL.md 含不同 family token
    md_template = (
        "This skill reorders retrieval. non-authoritative.\n"
        "rule family {family_token} is targeted.\n"
    )
    packages: list = []
    labels: list = []
    for i in range(12):
        label = i % 2
        labels.append(label)
        family_token = "mbis_envelope_family" if label == 1 else "mbis_egress_family"
        pkg_dir = tmp_path / f"pkg_{i}"
        pkg_dir.mkdir()
        (pkg_dir / "SKILL.md").write_text(
            md_template.format(family_token=family_token), encoding="utf-8"
        )
        # 用一个 minimal mock package 对象（仅 package_uri 字段被 helper 用到）
        @dataclass
        class _MockPackage:
            package_uri: str

        packages.append(_MockPackage(package_uri=pkg_dir.as_posix()))

    arts = [_MockArtifact(artifact_id=f"a{i}") for i in range(12)]
    pairs = [(a, None) for a in arts]

    def _provider(idx: int, _art, _trace):
        texts = load_skill_package_texts(packages[idx])
        return texts["skill_md_text"], texts["plan_yaml_text"]

    passed, delta = adversarial_reconstruction_audit_artifact(
        pairs, 0.5, private_labels=labels, text_provider=_provider
    )
    assert passed is False, (
        "load_skill_package_texts 应正确把磁盘上的恶意 SKILL.md 文本送入 audit"
    )
    assert delta > 0.05
