"""family_crosswalk_v1.json 完整性 / 一致性单测（spec §8.3.2）。

校验随包发布的 crosswalk 满足 spec §8.3.2 hard requirements，并和
family_index.json 的 43 个 canonical fine family_id 一一对应、不丢信息。
"""

from __future__ import annotations

import json
import os

import pytest

from evo_agent_baseline.eval.mapper import (
    CrosswalkError,
    default_crosswalk_path,
    load_crosswalk,
)

# family_index.json 路径（仓库内固定位置）。
_FAMILY_INDEX = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..",
        "regulations", "rulecard_v2", "mbis_cop_2023", "family_index.json",
    )
)


def _load_canonical_fine_ids() -> set:
    with open(_FAMILY_INDEX, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {f["family_id"] for f in data["families"]}


def _load_crosswalk_raw() -> dict:
    with open(default_crosswalk_path(), "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_crosswalk_loads_and_passes_hard_requirements():
    """spec §8.3.2 启动硬校验：schema_version / 16 coarse / fine 非空。"""
    cw = load_crosswalk(default_crosswalk_path())
    assert cw.schema_version == "family_crosswalk_v1"
    assert len(cw.coarse_family_ids) == 16
    assert len(set(cw.coarse_family_ids)) == 16
    # 每个 coarse 至少一个 fine 成员。
    for coarse, fines in cw.coarse_to_fine.items():
        assert fines, f"coarse {coarse} 的 fine_family_ids 为空"


def test_crosswalk_covers_all_43_canonical_fine_families():
    """43 个 canonical fine family 全部出现在 crosswalk（mappings + assignments）。"""
    canon = _load_canonical_fine_ids()
    assert len(canon) == 57, f"family_index.json 应有 57 family，实为 {len(canon)}"
    cw = load_crosswalk(default_crosswalk_path())

    # mappings 的 fine_family_ids 并集 == 44 canonical。
    union = set()
    for fines in cw.coarse_to_fine.values():
        union |= set(fines)
    assert union == canon, (
        f"mappings 覆盖与 canonical 不一致；"
        f"缺 {sorted(canon - union)}；多 {sorted(union - canon)}"
    )

    # fine_to_coarse（primary 归属）键集 == 44 canonical。
    assert set(cw.fine_to_coarse.keys()) == canon


def test_each_fine_family_has_exactly_one_primary_coarse():
    """每个 fine family 恰好一个 primary coarse（任务要求：归一个 primary）。"""
    cw = load_crosswalk(default_crosswalk_path())
    # fine_to_coarse 是 dict，键唯一即保证每 fine 唯一 primary。
    assert len(cw.fine_to_coarse) == 57  # 2026-07-28 补 64 张缺卡 → +9 fine family（44→53）
    for fine, coarse in cw.fine_to_coarse.items():
        assert coarse in cw.coarse_to_fine, f"{fine} 的 primary {coarse} 不是合法 coarse"
        # primary coarse 的 fine_family_ids 必须含该 fine。
        assert fine in cw.coarse_to_fine[coarse], (
            f"{fine} 的 primary 是 {coarse}，但未列入该 coarse 的 fine_family_ids"
        )


def test_secondary_coarse_assignments_are_consistent():
    """多对多次要归属不丢信息：secondary coarse 合法且其 fine_family_ids 含该 fine。"""
    cw = load_crosswalk(default_crosswalk_path())
    multi_count = 0
    for fine, secondaries in cw.fine_to_secondary.items():
        for sec in secondaries:
            multi_count += 1
            assert sec in cw.coarse_to_fine, f"{fine} 的 secondary {sec} 非法 coarse"
            assert fine in cw.coarse_to_fine[sec], (
                f"{fine} 次归 {sec}，但未列入该 coarse 的 fine_family_ids"
            )
            # secondary 不得等于 primary。
            assert sec != cw.fine_to_coarse[fine], (
                f"{fine} 的 secondary 与 primary 相同 ({sec})"
            )
    # §4 表已知至少 4 个多对多关系（scope.building / ri_procedural_notifications /
    # detailed_investigation.gate / .trigger / repair.drainage.repair / .validate）。
    assert multi_count >= 4, f"预期至少 4 条多对多次归属，实为 {multi_count}"


def test_every_listed_fine_is_primary_or_secondary_of_its_coarse():
    """coarse.fine_family_ids 里每个 fine，其 primary 或 secondary 必含该 coarse。"""
    cw = load_crosswalk(default_crosswalk_path())
    for coarse, fines in cw.coarse_to_fine.items():
        for fine in fines:
            is_primary = cw.fine_to_coarse.get(fine) == coarse
            is_secondary = coarse in cw.fine_to_secondary.get(fine, [])
            assert is_primary or is_secondary, (
                f"{fine} 列在 {coarse} 下，但既非其 primary 也非 secondary"
            )


def test_crosswalk_assignments_match_canonical_ids():
    """fine_family_assignments 共 43 条且 family_id 与 canonical 一一对应。"""
    raw = _load_crosswalk_raw()
    canon = _load_canonical_fine_ids()
    assignments = raw["fine_family_assignments"]
    ids = [a["fine_family_id"] for a in assignments]
    assert len(ids) == 57  # 2026-07-28 补 64 张缺卡 → +9 fine family（44→53）
    assert len(set(ids)) == 57, "fine_family_assignments 有重复"
    assert set(ids) == canon


def test_load_crosswalk_rejects_missing_file():
    """crosswalk 文件不存在时抛 CrosswalkError（spec §8.3.2 blocked 前置）。"""
    with pytest.raises(CrosswalkError):
        load_crosswalk(os.path.join(os.path.dirname(__file__), "no_such_crosswalk.json"))


def test_load_crosswalk_rejects_bad_schema(tmp_path):
    """schema_version 不符时抛 CrosswalkError。"""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "wrong", "mappings": []}), encoding="utf-8"
    )
    with pytest.raises(CrosswalkError):
        load_crosswalk(str(bad))


def test_load_crosswalk_rejects_wrong_coarse_count(tmp_path):
    """coarse 数 != 16 时抛 CrosswalkError。"""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": "family_crosswalk_v1",
                "mappings": [
                    {"coarse_family_id": "c1", "fine_family_ids": ["f1"]},
                ],
                "fine_family_assignments": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CrosswalkError):
        load_crosswalk(str(bad))


def test_load_crosswalk_rejects_empty_fine_list(tmp_path):
    """某 mapping 的 fine_family_ids 为空时抛 CrosswalkError。"""
    mappings = [
        {"coarse_family_id": f"c{i}", "fine_family_ids": ["f"]} for i in range(15)
    ]
    mappings.append({"coarse_family_id": "c15", "fine_family_ids": []})
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": "family_crosswalk_v1",
                "mappings": mappings,
                "fine_family_assignments": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CrosswalkError):
        load_crosswalk(str(bad))
