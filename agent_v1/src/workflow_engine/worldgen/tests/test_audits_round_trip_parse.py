"""W1 audits / round_trip_parse 测试 (DEBT-030 audit 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_engine.worldgen.audits.round_trip_parse import (
    BundleRoundTripResult,
    RoundTripAuditReport,
    _short_diff,
    round_trip_parse_audit,
    round_trip_parse_audit_from_json,
)
from workflow_engine.worldgen.tests.test_parquet_io import (
    _sample_projection_payload,
    _sample_sidecar_payload,
    _sample_world_payload,
)


# ---------------- baseline pass --------------------------------------------


def test_world_payload_round_trip_pass(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        world_payload=_sample_world_payload(), tmp_dir=tmp_path
    )
    assert report.passed, [r.diff_summary for r in report.results if not r.passed]
    assert len(report.results) == 1
    assert report.results[0].bundle_kind == "world"
    assert report.results[0].passed


def test_sidecar_payload_round_trip_pass(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        sidecar_payload=_sample_sidecar_payload(), tmp_dir=tmp_path
    )
    assert report.passed
    assert report.results[0].bundle_kind == "sidecar"


def test_projection_payload_round_trip_pass(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        projection_payload=_sample_projection_payload(), tmp_dir=tmp_path
    )
    assert report.passed
    assert report.results[0].bundle_kind == "projection"


def test_three_bundles_round_trip_all_pass(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        world_payload=_sample_world_payload(),
        sidecar_payload=_sample_sidecar_payload(),
        projection_payload=_sample_projection_payload(),
        tmp_dir=tmp_path,
    )
    assert report.passed
    kinds = [r.bundle_kind for r in report.results]
    assert "world" in kinds
    assert "sidecar" in kinds
    assert "projection" in kinds


# ---------------- record count ---------------------------------------------


def test_n_top_records_reported(tmp_path: Path) -> None:
    world = _sample_world_payload()
    report = round_trip_parse_audit(world_payload=world, tmp_dir=tmp_path)
    n_b = len(world["buildings"])
    assert report.results[0].n_top_records == n_b


# ---------------- diff helper ----------------------------------------------


def test_diff_helper_identical_returns_none() -> None:
    a = {"x": 1, "y": [1, 2, {"z": "a"}]}
    b = {"x": 1, "y": [1, 2, {"z": "a"}]}
    assert _short_diff(a, b) is None


def test_diff_helper_type_mismatch() -> None:
    msg = _short_diff({"x": 1}, {"x": "1"}, path="root")
    assert msg and "type mismatch" in msg
    assert "x" in msg


def test_diff_helper_value_mismatch() -> None:
    msg = _short_diff({"x": 1}, {"x": 2})
    assert msg and "value mismatch" in msg
    assert "x" in msg


def test_diff_helper_key_set_differ() -> None:
    msg = _short_diff({"a": 1, "b": 2}, {"a": 1, "c": 3})
    assert msg and "key sets differ" in msg


def test_diff_helper_list_len_differ() -> None:
    msg = _short_diff([1, 2, 3], [1, 2])
    assert msg and "list len" in msg


def test_diff_helper_nested_path_reported() -> None:
    msg = _short_diff(
        {"buildings": [{"world": {"deterministic_key": "abc"}}]},
        {"buildings": [{"world": {"deterministic_key": "xyz"}}]},
    )
    assert msg and "deterministic_key" in msg


# ---------------- silent mutation detection --------------------------------


def test_audit_detects_silent_mutation_via_modified_payload() -> None:
    """模拟 silent mutation 场景验 _short_diff 能 catch
    （实际的 silent mutation 是 writer/reader bug；这里直接构造已 diff 的 b）."""
    a = _sample_world_payload()
    b = json.loads(json.dumps(a))
    # mutate any leaf field; reader bug 会导致 a ≠ b
    b["buildings"][0]["world_id"] = "WB-MUTATED"
    diff = _short_diff(a, b)
    assert diff is not None
    assert "world_id" in diff


# ---------------- empty / partial inputs -----------------------------------


def test_no_payload_returns_empty_report(tmp_path: Path) -> None:
    report = round_trip_parse_audit(tmp_dir=tmp_path)
    assert report.passed  # 0 result, no fail
    assert len(report.results) == 0


def test_missing_tmp_dir_raises() -> None:
    with pytest.raises(ValueError, match="tmp_dir"):
        round_trip_parse_audit(world_payload=_sample_world_payload())


# ---------------- JSON entry -----------------------------------------------


def test_round_trip_audit_from_json(tmp_path: Path) -> None:
    """便利 entry 从 JSON 文件读 payload."""
    world_file = tmp_path / "world.json"
    world_file.write_text(json.dumps(_sample_world_payload()), encoding="utf-8")
    sidecar_file = tmp_path / "sidecar.json"
    sidecar_file.write_text(json.dumps(_sample_sidecar_payload()), encoding="utf-8")
    work_dir = tmp_path / "work"

    report = round_trip_parse_audit_from_json(
        world_json_path=world_file,
        sidecar_json_path=sidecar_file,
        tmp_dir=work_dir,
    )
    assert report.passed
    assert len(report.results) == 2


# ---------------- API shape ------------------------------------------------


def test_report_dataclass_shape(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        world_payload=_sample_world_payload(), tmp_dir=tmp_path
    )
    assert isinstance(report, RoundTripAuditReport)
    assert isinstance(report.passed, bool)
    assert all(isinstance(r, BundleRoundTripResult) for r in report.results)


def test_result_dataclass_fields(tmp_path: Path) -> None:
    report = round_trip_parse_audit(
        world_payload=_sample_world_payload(), tmp_dir=tmp_path
    )
    r = report.results[0]
    assert r.bundle_kind == "world"
    assert r.passed is True
    assert r.n_top_records > 0
    assert r.diff_summary is None


def test_tmp_dir_created_if_missing(tmp_path: Path) -> None:
    new_dir = tmp_path / "nonexistent_yet"
    assert not new_dir.exists()
    report = round_trip_parse_audit(
        world_payload=_sample_world_payload(), tmp_dir=new_dir
    )
    assert report.passed
    assert new_dir.exists()
