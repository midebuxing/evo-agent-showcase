import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))

from workflow_engine.rulecard_v2 import (  # noqa: E402
    collect_rulecard_bundle_violations,
    load_rulecard_bundle,
    rebuild_derived_indexes,
    validate_rulecard_bundle,
)


BUNDLE_DIR = PROJECT_ROOT / "regulations" / "rulecard_v2" / "mbis_cop_2023"


class RuleCardV2BundleTests(unittest.TestCase):
    def test_coverage_assets_are_declared_and_parseable(self) -> None:
        manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        for key in (
            "coverage_baseline",
            "family_coverage_baseline",
            "coverage_gap_audit",
        ):
            self.assertIn(key, files)
            parsed = json.loads((BUNDLE_DIR / files[key]).read_text(encoding="utf-8"))
            self.assertIn("schema_version", parsed)

    def test_load_summary_counts(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        summary = bundle.summary()
        self.assertEqual(summary["bundle_id"], "rulecard_v2.mbis_cop_2023")
        # 2026-07-28 补 72 张缺卡（DEBT 缺卡落库）后的精确锚：
        #   卡 398 → 470（+72）／族 44 → 57（+13 新细族）
        #   语义槽 51 → 66（+15，其中 12 个用了此前白名单外的词根，见 SLOT_ID_RE）
        #   卡内槽引用 167 → 190（+23）
        # 其余四项未变，说明补卡没有引入新量表/新证物/新时间锚/新阈值机制。
        # 2026-08-04 件四批 1：卡 470 → 469（§3.2.6 同义重复建卡二保一，退役
        # `…ri.review.s3_2_6_prepare_inspection_method_statement.c01`）。
        # **族 57 / 槽 190 / regime 41 / 语义槽 66 全部不变**是当时的关键判据：
        # 退役卡的两个槽分别还被另外 64 / 193 张卡引用，其族还剩 22 张卡 ⇒ 无孤儿、无空族。
        # 2026-08-05 换池捆绑批·乙路 #30：**语义槽 66 → 67、卡内槽引用 190 → 191**
        #   ——意向卡 `…s2_1_3_n_investigation_intention_to_ba.c01` 接真前件槽
        #   `procedure.investigation.detailed.intended`（`allowed_roles=["trigger"]`）：
        #   语义槽登记 +1、该卡 `slot_role_map` 新增 sr02 ⇒ slot_index 多一个
        #   （slot_id, 空限定符, roles=["trigger"]）桶。**卡数 469 与族 57 不变**
        #   （不增删卡、不动 `family_id`）；regime 41 / 量表 28 / 证物 25 / 时间锚 19
        #   同样不变——乙路不引入新量表、新证物、新时间锚、新阈值机制。
        # 2026-08-06 #38 八槽裁定（决议_38裁定_20260806）：**语义槽 67 → 73（+6）**
        #   ——override 前件槽补登记（P5 对账闸 A1 债清账）：5 个世界实采名
        #   （ri_role.terminated / supervision_representative.planned /
        #     supervision_team.changed / temp_ri_nomination.terminated /
        #     repair_supervising_ri.appointment.completed，末者登记先行、采样随池 v2）
        #   ＋ 1 个槽3 改绑目标世界名（procedure.repair.revision_required，
        #     与卡登记名 repair.proposal.revision_required 经 slot_aliases 桥接、
        #     是两个字符串）。certificate 槽只加 trigger 角色不增条目。
        #   **卡 470 / 族 57 / 卡内槽引用 192 全部不变**——#38 不动任何卡
        #   （override 表与登记表均不在卡指纹射程内）。
        self.assertEqual(summary["family_count"], 57)
        self.assertEqual(summary["rule_card_count"], 470)  # 2026-08-05 #23 补 §5.4.3(b) masonry 缺卡 469→470
        self.assertEqual(summary["semantic_slot_registry_count"], 74)  # 2026-08-06 #38 67→73；换池批步 A1.3 槽2 主案（supervision.nonconformity.found）73→74
        self.assertEqual(summary["measure_registry_count"], 28)
        self.assertEqual(summary["artifact_registry_count"], 25)
        self.assertEqual(summary["time_anchor_registry_count"], 19)
        # 2026-08-05 #23 masonry 卡引用 defect.class.present（新限定符组合
        # dampness×external_wall）⇒ slot_index 桶 191→192。
        # 2026-08-07 卡包合流：95 卡删无授权 trigger（收走纯触发槽桶）＋8 卡删
        # location 限定（桶按限定符组合分裂合并）＋7 卡加析取 ⇒ 192→187
        # （`rulecard_v2 rebuild` 实测；出处 `重核准记录_卡包合流_20260807.md`）。
        # 2026-08-07 DEBT-095 甲案：`s3_6_2_a_b_to_c…` 的 `location_class_key`
        # `private_premises`→`common_pipe_duct` 三处同改，其 `sr01` 所在桶
        # (scope.component.inspection_included, {drainage_component, private_premises})
        # **并入同族先例卡 `s3_6_1_c` 早已存在的 common_pipe_duct 桶** ⇒ 187→186
        # （净减一桶、无新增桶；实测差集只有那一个键；
        #  出处 `重核准记录_debt095甲案_20260807.md`）。
        self.assertEqual(summary["slot_count"], 186)
        self.assertEqual(summary["threshold_regime_count"], 41)
        self.assertEqual(summary["definition_count"], 1)
        self.assertEqual(summary["exception_count"], 0)

    @unittest.expectedFailure
    def test_validate_bundle_passes(self) -> None:
        """🔴 **预期失败**：3 张卡 `slot_role_map` 为空，卡包当前确实违反自身契约。

        为什么用 expectedFailure 而不是留一个普通的红：
        - 真正的闸是下面 `test_collect_violations_lists_empty_slot_role_maps`
          （断言违规恰好是那 3 条、一条不多），本条只是它的冗余投影；
        - 留普通红会持续污染信号，久了没人再看；
        - `expectedFailure` 在卡修好后会变成 **unexpected success**（报错），
          自动提醒把本装饰器和批跑闸的豁免一起摘掉。

        语义裁定**已完成**（`团队文档/我的笔记/裁定_三张空slot_role_map卡_20260729.md`）：
        §3.1.4「須確定嚴重欠妥」= 该有满足通道（世界侧 `risk.public_danger.present`
        等已实产）；§4.1.3「**可能需要**進行詳細調查」= may，**根本不该是义务节点**；
        §2.1.3(h)「須全面遵從《建築物條例》」= 总括性外部引用，本系统内无满足谓词。
        后两条的处置是**改建模**，不是补 `slot_role_map`——
        为了过闸编一个映射会把 may 变成事实上的 shall，比留着空更糟。
        """
        bundle = validate_rulecard_bundle(BUNDLE_DIR)
        self.assertEqual(bundle.manifest["schema_version"], "2.1.0")

    def test_collect_violations_lists_empty_slot_role_maps(self) -> None:
        """一次列出全部契约违规——不得遇错即停只报第一条。

        2026-08-07 卡包合流事务后基线 3 → **16**：13 张卡按裁定删除无正文授权的
        trigger（其 slot_role_map 原本只有那一行触发器槽引 → 删后为空，属裁定的
        机械后果；授权链 `重核准记录_卡包合流_20260807.md`）。豁免表与本数联动：
        `run_baseline_batch.RULECARD_CONTRACT_EXEMPTIONS`。
        """
        violations = collect_rulecard_bundle_violations(BUNDLE_DIR)
        empty_ids = [
            card["rule_card_id"]
            for card in load_rulecard_bundle(BUNDLE_DIR).cards
            if not card.get("slot_role_map")
        ]
        expected = {f"{cid}.slot_role_map must not be empty" for cid in empty_ids}
        self.assertEqual(len(empty_ids), 18)  # 2026-08-08 残差57A：+2（三卡删 trigger，其中 2 卡 map 转空）
        self.assertEqual(set(violations), expected)
        self.assertEqual(len(violations), 18)  # 2026-08-08 残差57A 同步

    def test_rebuilt_indexes_match_stored_indexes(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        derived = rebuild_derived_indexes(bundle.cards)
        self.assertEqual(bundle.slot_index, derived["slot_index"])
        self.assertEqual(bundle.threshold_regime_index, derived["threshold_regime_index"])
        self.assertEqual(
            bundle.exception_definition_index,
            derived["exception_definition_index"],
        )

    def test_gate_card_uses_prerequisite_not_exception(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        gate_card = next(
            card
            for card in bundle.cards
            if card["rule_card_id"]
            == "rc.mbis.investigation.detailed_investigation.ri.gate.s4_2_3.c01"
        )
        gate_roles = {
            item["slot_id"]: set(item["roles"]) for item in gate_card["slot_role_map"]
        }
        self.assertIn(
            "prerequisite",
            gate_roles["procedure.investigation.proposal.recognized"],
        )
        self.assertEqual(gate_card["exceptions"], [])

    def test_cards_use_canonical_normalized_slot_and_measure_names(self) -> None:
        bundle = load_rulecard_bundle(BUNDLE_DIR)
        forbidden_slot_roots = ("admin.", "measurement.", "work.", "state.")
        for card in bundle.cards:
            for mapping in card["slot_role_map"]:
                self.assertFalse(mapping["slot_id"].startswith(forbidden_slot_roots))
                self.assertFalse(mapping["slot_id"].endswith(("_at", "_ts")))
            for threshold in card["threshold_regimes"]:
                self.assertNotIn("measure", threshold)
                self.assertIn("measure_key", threshold)


if __name__ == "__main__":
    unittest.main()


# ===== 已停用的阈值旁路(DEBT-072) =====
from evo_agent_baseline.ingest import threshold_sidecar as _ts  # noqa: E402


def test_threshold_sidecar_is_disabled_experiment(monkeypatch):
    """已停用附件只能保持无运行时效果；任何旧开关尝试都明确拒绝。"""
    import pytest as _p
    monkeypatch.delenv(_ts.ENV_FLAG, raising=False)
    assert _ts.enabled() is False
    monkeypatch.setenv(_ts.ENV_FLAG, "1")
    with _p.raises(_ts.ThresholdSidecarError, match="停用|unsupported_experiment"):
        _ts.enabled()

def test_backfilled_thresholds_are_all_already_in_authoritative_index():
    """严格按量表、算子和值对账：4/5 精确重复，剩余一条不得伪称重复。"""
    import json as _j
    import pathlib as _pl
    _REG = _pl.Path(__file__).resolve().parents[1] / "regulations"
    idx = _j.loads((_REG / "rulecard_v2" / "mbis_cop_2023"
                    / "threshold_regime_index.json").read_text(encoding="utf-8"))
    items = idx.get("threshold_regimes") or idx
    items = items if isinstance(items, list) else list(items.values())
    have = {
        (t.get("measure_key"), t.get("operator"), str(t.get("value")))
        for t in items
    }
    side_p = (_REG / "rulecard_v2" / "mbis_cop_2023"
              / "rulecard_threshold_sidecar_v1.json")
    if not side_p.is_file():
        import pytest as _p
        _p.skip("裁定记录未生成（派生物）")
    side = _j.loads(side_p.read_text(encoding="utf-8"))
    mine = [t for t in side["thresholds"]
            if t.get("role") == "obligation_threshold" and t.get("measure_key")]
    exact = [
        t for t in mine
        if (t["measure_key"], t["operator"], str(t["number"])) in have
    ]
    mismatch = [
        (t["measure_key"], t["operator"], str(t["number"]))
        for t in mine if t not in exact
    ]
    assert len(mine) == 5
    assert len(exact) == 4
    assert mismatch == [
        ("ratio.covered_structure_area.inspected", "==", "1.0")
    ], "算子差异若改变，须重新裁定停用理由，不能机械更新计数"

def test_two_sidecars_reconcile_against_each_other(monkeypatch):
    """🔴 跨附件契约:阈值附件的 `source_zh` 必须在中文权威源里**逐字可查**。

    两个附件是**分别**从同一份中文原文建的（`build_rulecard_zh_sidecar.py` 与
    `build_threshold_sidecar.py`），此前从未互相对账——而"生产者→消费者接口只测生产者
    自身等于没测"是本项目反复踩的坑（见记忆 `feedback_green_tests_hide_broken_wiring`）。

    对不上意味着两者之一的定位/裁定错了，**必须在灌库前拦住**：阈值一旦进图，
    它就以"来自中文原文"的名义参与合规判定，而那句中文可能根本不在那张卡的条款里。
    """
    import os
    import pathlib
    from evo_agent_baseline.ingest import zh_authority as _za
    side = (pathlib.Path(__file__).resolve().parents[1] / "regulations"
            / "rulecard_v2" / "mbis_cop_2023" / "rulecard_threshold_sidecar_v1.json")
    if not side.is_file():
        import pytest as _p
        _p.skip("阈值附件未生成(派生物)")
    monkeypatch.setenv("EVO_ZH_AUTHORITY", "1")
    _za.reset_cache() if hasattr(_za, "reset_cache") else None

    def _norm(t: str) -> str:
        return (t or "").replace(" ", "").replace("　", "").replace("\n", "")

    # 附件已降级为**裁定记录**(status=deferred)，`load_sidecar` 会因 schema 改名而拒收——
    # 这正是预期行为。本测试只核"裁定里的中文原句在权威中文源里逐字可查"，故直读 JSON。
    doc = json.loads(side.read_text(encoding="utf-8"))
    by_card = {}
    for t in doc.get("thresholds") or []:
        by_card.setdefault(t["rule_card_id"], []).append(t)
    checked = 0
    for cid, regimes in by_card.items():
        zh = _za.zh_text_for_card(cid)
        assert zh, f"中文权威源缺卡 {cid} —— 两附件覆盖面不一致"
        for r in regimes:
            assert _norm(r["source_zh"]) in _norm(zh), (
                f"卡 {cid} 的阈值 source_zh 在中文权威源里查不到逐字原句；"
                f"两附件之一定位错了")
            checked += 1
    assert checked > 0, "一条都没检查到，测试是空真的"
