"""结构闸：卡的 (构件类 × 位置类) 组合在池内 0 次出现即报警。

被测的是 `audit_card_scope_combination_reachability.py`。

为什么需要这道闸（`补完总工单_238拆簇_20260807.md` §三.2 实证）：
`location_class_key` 的受控词表是**七个平行取值的扁平表**，
`closure/validator.py` 的 `_lc_na` 是**直接值判**、无类目层级。
卡上写了一个在世界里从不与该构件类共现的位置类 ⇒ 该卡在**每一个**该类片段上都发
`structurally_unsatisfiable_card_scope` 早退，**结构上永不激活且全链不报错**。
§4.4.1(b) 那张排水卡就是这么把 5 栋判成 `wrong_structural_na` 的。

三条判别力：
  1. **键集不是计数** —— 修好一条同时引进一条，计数不变，闸必须照红；
  2. **空作用域判失败** —— 扫不到池证据时「都不可达」是空真的；
  3. **只报告不改判** —— 闸不碰卡包、不碰判定。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_v1" / "scripts"))
sys.path.insert(0, str(ROOT / "agent_v1" / "src"))

import audit_card_scope_combination_reachability as gate  # noqa: E402


def _batch(root: Path, fragments: list[tuple[str, str, str]]) -> Path:
    """造一个最小批：`fragments` = [(楼, 构件类, 位置类), …]，每条一个片段。"""
    for i, (building, comp, loc) in enumerate(fragments):
        run = root / "buildings" / building / "runs" / "RUN-1"
        run.mkdir(parents=True, exist_ok=True)
        pack_path = run / "fact_pack.json"
        doc = (json.loads(pack_path.read_text(encoding="utf-8"))
               if pack_path.is_file() else {"facts": []})
        doc["facts"].append({
            "carrier_type": "fragment", "carrier_id": f"FRG-{building}-{i}",
            "slot_id": "fragment_role",
            "qualifiers": {"component_type_key": comp, "location_class_key": loc},
        })
        pack_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root


def _bundle(path: Path, roles: list[tuple[str, str, str, str]]) -> Path:
    """造一个最小卡包：`roles` = [(卡, 槽, 构件类, 位置类), …]。"""
    cards: dict[str, dict] = {}
    for card_id, slot_id, comp, loc in roles:
        card = cards.setdefault(card_id, {"rule_card_id": card_id, "slot_role_map": []})
        qualifiers = {}
        if comp:
            qualifiers["component_type_key"] = comp
        if loc:
            qualifiers["location_class_key"] = loc
        card["slot_role_map"].append({"slot_id": slot_id, "qualifiers": qualifiers})
    path.write_text(json.dumps({"cards": list(cards.values())}, ensure_ascii=False),
                    encoding="utf-8")
    return path


POOL = [("BLD-1", "drainage_component", "common_pipe_duct"),
        ("BLD-2", "structural_component", "common_part")]


def test_reachable_combo_is_not_reported(tmp_path: Path) -> None:
    result = gate.audit(
        _batch(tmp_path / "b", POOL),
        _bundle(tmp_path / "cards.json",
                [("rc.ok", "s1", "drainage_component", "common_pipe_duct")]))
    assert result["unreachable_slot_reference_count"] == 0
    assert result["vacuous_no_pool_evidence"] is False


def test_unreachable_combo_is_reported_and_reds(tmp_path: Path, capsys) -> None:
    """§4.4.1(b) 的形状：排水卡写 `common_part`，而世界的排水片段从不在 `common_part`。"""
    batch = _batch(tmp_path / "b", POOL)
    bundle = _bundle(tmp_path / "cards.json",
                     [("rc.bad", "scope.component.inspection_included",
                       "drainage_component", "common_part")])
    result = gate.audit(batch, bundle)
    assert result["unreachable_slot_reference_count"] == 1
    assert result["unreachable_by_combo"] == {
        "drainage_component|common_part": [
            {"rule_card_id": "rc.bad", "slot_id": "scope.component.inspection_included"}]}

    rc = gate.main(["--batch-root", str(batch), "--card-bundle", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 1, "基线外的不可达槽引用必须让闸非零退出"
    assert "门失败" in out
    assert "rc.bad" in out


def test_keyset_not_count_catches_a_one_for_one_swap(tmp_path: Path, monkeypatch) -> None:
    """🔴 判据是**键集**：修好一条同时引进一条，计数不变而闸照红。

    计数棚顶挡不住对调 —— 这正是本仓「归因守恒」用键集相等而非计数相等的理由。
    """
    batch = _batch(tmp_path / "b", POOL)
    monkeypatch.setattr(gate, "KNOWN_UNREACHABLE_BASELINE", frozenset({
        ("rc.old", "s1", "drainage_component", "common_part")}))

    healed_and_replaced = _bundle(
        tmp_path / "swap.json", [("rc.new", "s1", "drainage_component", "external")])
    result = gate.audit(batch, healed_and_replaced)
    assert result["unreachable_slot_reference_count"] == 1, "计数与基线相同"
    assert result["new_beyond_baseline"] == [
        ["rc.new", "s1", "drainage_component", "external"]]
    assert result["healed_vs_baseline"] == [
        ["rc.old", "s1", "drainage_component", "common_part"]]
    assert gate.main(["--batch-root", str(batch),
                      "--card-bundle", str(healed_and_replaced)]) == 1


def test_baseline_entry_alone_passes_but_says_so(tmp_path: Path, monkeypatch, capsys) -> None:
    """已登记的欠账不判红，但「通过」不许读成「无害」。"""
    batch = _batch(tmp_path / "b", POOL)
    monkeypatch.setattr(gate, "KNOWN_UNREACHABLE_BASELINE", frozenset({
        ("rc.known", "s1", "drainage_component", "common_part")}))
    bundle = _bundle(tmp_path / "cards.json",
                     [("rc.known", "s1", "drainage_component", "common_part")])
    rc = gate.main(["--batch-root", str(batch), "--card-bundle", str(bundle)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "没有新增" in out and "无害" in out


def test_empty_pool_evidence_is_a_failure_not_a_pass(tmp_path: Path, capsys) -> None:
    """🔴 空作用域＝空真通过，一律判失败。

    判例：`shadow_measure_applicability.py`
    「『没验到任何东西』不等于『验过了没问题』」。批崩掉导致 fact_pack 缺失时，
    「卡的组合全不可达」这个结论毫无内容，而它看起来像一批严重告警。
    """
    empty = tmp_path / "empty"
    (empty / "buildings").mkdir(parents=True)
    bundle = _bundle(tmp_path / "cards.json",
                     [("rc.a", "s1", "drainage_component", "common_pipe_duct")])
    result = gate.audit(empty, bundle)
    assert result["vacuous_no_pool_evidence"] is True
    assert gate.main(["--batch-root", str(empty), "--card-bundle", str(bundle)]) == 1
    assert "空真通过" in capsys.readouterr().out


def test_single_axis_slot_references_are_out_of_scope(tmp_path: Path) -> None:
    """只写了一根轴的槽引用不进本闸 —— 早退判据不同（`_ct_na` 另有其人），
    混进来会造出解释不了的告警。"""
    batch = _batch(tmp_path / "b", POOL)
    bundle = _bundle(tmp_path / "cards.json", [
        ("rc.comp_only", "s1", "nonexistent_component", ""),
        ("rc.loc_only", "s2", "", "nonexistent_location"),
    ])
    result = gate.audit(batch, bundle)
    assert result["card_slot_reference_count"] == 0
    assert result["unreachable_slot_reference_count"] == 0


def test_evidence_is_fragment_level_not_building_level(tmp_path: Path) -> None:
    """🔴 证据只能取**片段级**。

    楼级事实的 `component_type_key` 值域远宽于本栋实际片段；扫全部会把
    「楼级事实提过这个类型」误当成「有这类片段」，而早退判据看的恰恰是片段。
    """
    root = tmp_path / "b"
    run = root / "buildings" / "BLD-1" / "runs" / "RUN-1"
    run.mkdir(parents=True)
    (run / "fact_pack.json").write_text(json.dumps({"facts": [
        {"carrier_type": "fragment", "carrier_id": "FRG-1", "slot_id": "fragment_role",
         "qualifiers": {"component_type_key": "drainage_component",
                        "location_class_key": "common_pipe_duct"}},
        # 楼级事实提到 (drainage_component, common_part) —— **不得**被算进池组合
        {"carrier_type": "building", "carrier_id": "BLD-1", "slot_id": "whatever",
         "qualifiers": {"component_type_key": "drainage_component",
                        "location_class_key": "common_part"}},
    ]}, ensure_ascii=False), encoding="utf-8")
    bundle = _bundle(tmp_path / "cards.json",
                     [("rc.bad", "s1", "drainage_component", "common_part")])
    result = gate.audit(root, bundle)
    assert "drainage_component|common_part" in result["unreachable_by_combo"]


def test_combos_are_taken_per_fragment_not_per_building(tmp_path: Path) -> None:
    """组合按**同一片段内共现**取，不许跨片段配对。

    一栋楼里有 (排水, 管槽) 与 (結構, 公用部分) 两个片段，**不意味着**
    (排水, 公用部分) 在池里出现过 —— 跨片段配对会静默放行真正的死卡。
    """
    batch = _batch(tmp_path / "b", [("BLD-1", "drainage_component", "common_pipe_duct"),
                                    ("BLD-1", "structural_component", "common_part")])
    bundle = _bundle(tmp_path / "cards.json",
                     [("rc.bad", "s1", "drainage_component", "common_part")])
    assert gate.audit(batch, bundle)["unreachable_slot_reference_count"] == 1


# ── 落地基线的锚断言 ────────────────────────────────────────────────────────

def test_shipped_baseline_anchor_is_deliberate() -> None:
    """🔴 基线锚变动必须是有意的：改小了要有实证，改大了等于给死卡开后门。

    2026-08-07 在批 `poolv2_llm_seed401_20260806`（50 栋，池内 14 种组合）
    × 卡包 470 张上实测：卡侧两轴齐备的槽引用 51 条，其中
    **17 条 / 7 个组合 / 15 张卡在池内 0 次出现**。
    其中 `(drainage_component, common_part)` **9 条 / 7 张卡**——与
    `补完总工单_238拆簇_20260807.md` §三.2「共出现 9 处、分布在 7 张卡上」逐位相符。
    """
    baseline = gate.KNOWN_UNREACHABLE_BASELINE
    assert len(baseline) == 17

    drainage_common = {r for r in baseline if (r[2], r[3]) == ("drainage_component", "common_part")}
    assert len(drainage_common) == 9
    assert len({r[0] for r in drainage_common}) == 7
    assert any("s4_4_1_b_defective_underground_drain_trigger" in r[0] for r in drainage_common), \
        "§4.4.1(b) 那张卡是本闸的锚本体，掉了就说明基线被改过而没重取"

    assert len({(r[2], r[3]) for r in baseline}) == 7
    assert len({r[0] for r in baseline}) == 15


def test_axes_are_pinned_to_the_early_exit_predicate() -> None:
    """轴写死是有意的：本闸测的就是 `_lc_na` 用的那两个限定符，加轴等于换判据。"""
    assert gate.COMBO_AXES == ("component_type_key", "location_class_key")
