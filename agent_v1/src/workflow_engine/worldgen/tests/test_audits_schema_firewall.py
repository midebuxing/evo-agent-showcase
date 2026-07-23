"""W1 audits / schema_firewall 测试 (DEBT-030 audit 1)."""

from __future__ import annotations

from typing import List, Optional

import pytest
from pydantic import BaseModel, Field

from workflow_engine.worldgen.audits.schema_firewall import (
    FORBIDDEN_FIELD_TOKENS,
    FieldViolation,
    SchemaFirewallReport,
    WHITELIST_FIELDS,
    _collect_basemodel_classes,
    schema_firewall_audit,
)
from workflow_engine.worldgen.models import (
    SidecarRuntimeBundle,
    SidecarRuntimeRecord,
    WorldBundle,
)


# ---------------- Baseline pass --------------------------------------------


def test_baseline_pass() -> None:
    """当前 master HEAD 双顶层契约扫一遍必 pass."""
    report = schema_firewall_audit()
    assert report.passed, (
        "W1 schema firewall violations (master HEAD): "
        + "; ".join(f"{v.class_name}.{v.field_name}={v.matched_pattern}" for v in report.violations)
    )
    assert report.n_classes_scanned >= 20  # 当前 21 个，留 buffer
    assert report.n_fields_scanned >= 150  # 当前 192 个，留 buffer
    assert len(report.violations) == 0


def test_report_metadata_filled() -> None:
    report = schema_firewall_audit()
    assert report.forbidden_tokens == list(FORBIDDEN_FIELD_TOKENS)
    assert report.whitelist_entries == list(WHITELIST_FIELDS)


# ---------------- Forbidden token detection --------------------------------


class _LeakRuleFamily(BaseModel):
    """伪 model — 故意带 rule_family_id 字段。"""

    rule_family_id: str = ""


class _LeakThreshold(BaseModel):
    threshold_value: float = 0.0


class _LeakGold(BaseModel):
    gold_label: str = ""


class _LeakObservation(BaseModel):
    observation_id: str = ""


class _LeakVerdict(BaseModel):
    verdict: str = ""


class _LeakExpectedOutcome(BaseModel):
    expected_outcome_flag: bool = False


class _LeakRawW2(BaseModel):
    raw_w2_payload: str = ""


class _LeakReferenceVerdict(BaseModel):
    reference_verdict_summary: str = ""


class _LeakRuleCard(BaseModel):
    rule_card_ref: str = ""


class _LeakRuleId(BaseModel):
    rule_id: str = ""


class _LeakEvalTruth(BaseModel):
    eval_truth_label: str = ""


class _LeakW2Truth(BaseModel):
    w2_truth_score: float = 0.0


class _LeakThresholdId(BaseModel):
    threshold_id: str = ""


_LEAK_FIXTURES = [
    (_LeakRuleFamily, "rule_family_id"),
    (_LeakThreshold, "threshold_value"),
    (_LeakGold, "gold_label"),
    (_LeakObservation, "observation_id"),
    (_LeakVerdict, "verdict"),
    (_LeakExpectedOutcome, "expected_outcome_flag"),
    (_LeakRawW2, "raw_w2_payload"),
    (_LeakReferenceVerdict, "reference_verdict_summary"),
    (_LeakRuleCard, "rule_card_ref"),
    (_LeakRuleId, "rule_id"),
    (_LeakEvalTruth, "eval_truth_label"),
    (_LeakW2Truth, "w2_truth_score"),
    (_LeakThresholdId, "threshold_id"),
]


@pytest.mark.parametrize("model_cls,field_name", _LEAK_FIXTURES)
def test_detect_forbidden_token(model_cls, field_name) -> None:
    """每个伪 model 必须被检出 violation；matched_pattern 不强求精确顺序
    (短 token 可能先于长 token 命中，是诊断信息不是核心契约)."""
    report = schema_firewall_audit(root_classes=[model_cls])
    assert not report.passed
    assert len(report.violations) == 1
    v = report.violations[0]
    assert v.class_name == model_cls.__name__
    assert v.field_name == field_name
    assert v.matched_pattern in FORBIDDEN_FIELD_TOKENS


def test_safe_lookalike_fields_not_flagged() -> None:
    """合法字段含 family / id 等 substring 不被误伤."""

    class _SafeMechanismFamily(BaseModel):
        mechanism_family: str = ""  # 含 family 但不是 rule_family
        measurement_family: str = ""  # 同上
        component_id: str = ""  # 含 _id 但不是 rule_id
        fragment_id: str = ""

    report = schema_firewall_audit(root_classes=[_SafeMechanismFamily])
    assert report.passed, [
        f"{v.class_name}.{v.field_name} matched {v.matched_pattern}"
        for v in report.violations
    ]


# ---------------- Whitelist ------------------------------------------------


def test_whitelist_exempts_projection_id_on_sidecar_record() -> None:
    """SidecarRuntimeRecord.projection_id 是 W1→W2 外键合法字段，
    必须在 whitelist 中跳过 token 扫."""
    assert ("SidecarRuntimeRecord", "projection_id", _whitelist_reason()) in WHITELIST_FIELDS


def _whitelist_reason() -> str:
    for c, f, reason in WHITELIST_FIELDS:
        if c == "SidecarRuntimeRecord" and f == "projection_id":
            return reason
    return ""


def test_whitelist_actually_applied_in_audit() -> None:
    """直接扫 SidecarRuntimeRecord 也不应该报 projection_id (whitelist 生效)."""
    report = schema_firewall_audit(root_classes=[SidecarRuntimeRecord])
    # SidecarRuntimeRecord 含 projection_id 字段；如果 whitelist 没生效会报 fail
    projection_id_violations = [
        v for v in report.violations if v.field_name == "projection_id"
    ]
    assert projection_id_violations == []


def test_whitelist_can_be_overridden_to_force_fail() -> None:
    """显式传空 whitelist，audit 应该把 projection_id 报 fail (验证 whitelist 机制本身)."""
    report = schema_firewall_audit(
        root_classes=[SidecarRuntimeRecord],
        whitelist=[],
        forbidden_tokens=[r"\bprojection"],
    )
    projection_id_violations = [
        v for v in report.violations if v.field_name == "projection_id"
    ]
    assert len(projection_id_violations) == 1


# ---------------- Nested traversal -----------------------------------------


def test_collect_basemodel_recursive() -> None:
    """收集器从 WorldBundle / SidecarRuntimeBundle 必须能展开到所有嵌套子 class."""
    classes = _collect_basemodel_classes([WorldBundle, SidecarRuntimeBundle])
    names = {c.__name__ for c in classes}
    # WorldBundle 树预期含的：
    for expected in ("WorldBundle", "BuildingContext", "ComponentNode", "FragmentContext", "MeasurementRecord"):
        assert expected in names, f"missing {expected} in nested collection"
    # SidecarRuntimeBundle 树预期含的：
    for expected in ("SidecarRuntimeBundle", "SidecarRuntimeRecord", "SidecarRuntimeValue"):
        assert expected in names, f"missing {expected} in nested collection"


class _Leaf(BaseModel):
    threshold_value: float = 0.0


class _Middle(BaseModel):
    leaf: _Leaf = Field(default_factory=_Leaf)
    leaves: List[_Leaf] = Field(default_factory=list)
    opt_leaf: Optional[_Leaf] = None


class _Root(BaseModel):
    mid: _Middle = Field(default_factory=_Middle)


def test_nested_violation_found() -> None:
    """嵌套 List / Optional 中的 BaseModel 子类也要被扫到."""
    report = schema_firewall_audit(root_classes=[_Root])
    leaf_violations = [v for v in report.violations if v.class_name == "_Leaf"]
    assert len(leaf_violations) == 1
    assert leaf_violations[0].field_name == "threshold_value"


# ---------------- API surface ----------------------------------------------


def test_report_dataclass_fields_present() -> None:
    report = schema_firewall_audit()
    assert isinstance(report, SchemaFirewallReport)
    assert isinstance(report.violations, list)
    assert isinstance(report.passed, bool)
    assert report.n_classes_scanned > 0
    assert report.n_fields_scanned > 0


def test_violation_dataclass_shape() -> None:
    report = schema_firewall_audit(root_classes=[_LeakVerdict])
    v = report.violations[0]
    assert isinstance(v, FieldViolation)
    assert v.class_name == "_LeakVerdict"
    assert v.field_name == "verdict"
