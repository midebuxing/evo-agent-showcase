"""法规卡派生链发布检查的缺失、过期与重建行为。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_rulecard_derived_release as release  # noqa: E402


def _expected() -> dict[str, dict]:
    return {name: {"name": name, "revision": 1} for name in release.ASSET_FILENAMES}


def test_release_check_rejects_missing_and_stale_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "expected_assets", _expected)
    for name, doc in _expected().items():
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / release.ASSET_FILENAMES[0]).unlink()
    (tmp_path / release.ASSET_FILENAMES[1]).write_text(
        json.dumps({"stale": True}), encoding="utf-8"
    )

    problems = release.release_problems(tmp_path)

    assert any("缺失" in problem and release.ASSET_FILENAMES[0] in problem
               for problem in problems)
    assert any("过期" in problem and release.ASSET_FILENAMES[1] in problem
               for problem in problems)


def test_rebuild_then_release_check_closes_all_three_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "expected_assets", _expected)

    release.rebuild(tmp_path)

    assert release.release_problems(tmp_path) == []
    assert {path.name for path in tmp_path.iterdir()} == set(release.ASSET_FILENAMES)


def test_release_check_detects_mutated_derived_asset(tmp_path, monkeypatch):
    """变异证据：发布检查通过后打坏任一派生物，检查必须立即转红。"""
    monkeypatch.setattr(release, "expected_assets", _expected)
    release.rebuild(tmp_path)
    target = tmp_path / release.ASSET_FILENAMES[2]
    target.write_text(json.dumps({"mutated": True}), encoding="utf-8")

    assert any("过期" in problem and target.name in problem
               for problem in release.release_problems(tmp_path))