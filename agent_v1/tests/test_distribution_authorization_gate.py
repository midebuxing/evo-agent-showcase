"""分布授权门检器（A1.6）三收集器的形状与当前已知态（换池批步 A，2026-08-06）。

分工：本文件钉**门检器答对不对**（收集器语义＋当前登记态画像），不钉「门过没过」
——门过与否是换池批 A1.6 时序位的裁定产物（重采样＋MC 后），不是测试断言。
画像断言在裁定落地时**应当**跟着变：PLACEHOLDER 5→0、stale 45→0 都会让这里红，
红了就来改画像并在实施记录里归因——这正是「静默换参照系」的防呆。
"""
from __future__ import annotations

import sys
from pathlib import Path

_AGENT_V1 = Path(__file__).resolve().parents[1]
_SCRIPTS = _AGENT_V1 / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_distribution_authorization_gate as gate  # noqa: E402


def _bundle():
    bundle, bundle_hash = gate.build_bundle_with_hash()
    return bundle, bundle_hash


BUNDLE, BUNDLE_HASH = _bundle()


def test_placeholder_set_is_empty_after_a16_authorization():
    """① 画像改锚（A1.6 落地，2026-08-06）：PLACEHOLDER **5 → 0**。

    归因（`实施记录_A16落地_20260806.md` §2.4/§2.5）：原 5 条＝#38 三新槽
    ＋两改锚槽（mbi5/sp2）。三新槽参数经决议 §二 裁定（0.22/0.17/0.075）、
    两改锚槽经 A1.6 MC 在原锚上实测过阈，来源串全部换实值。
    **本断言的方向不许放松**：改回「允许若干条 PLACEHOLDER」＝把占位参数放行进池。
    """
    placeholders = gate.collect_placeholder_sources(BUNDLE)
    assert placeholders == [], (
        f"分布来源表出现 PLACEHOLDER：{placeholders}"
        "——A1.6 之后任何新占位都必须走一次分布授权门，不得直接进池")


def test_zero_inflated_violations_cleared_by_label_withdrawal():
    """② 反标签装饰闸：违例 **1 → 0**（撤标签裁定落地，2026-08-06）。

    画像改锚归因（`商议结果_glm_calib裁定_20260806.md` §三 裁候选②
    ＋`实施记录_calib撤标签与重封存_20260806.md`）：唯一违例
    `count.pull_test.failed_cumulative` 的 `recommended_distribution` 由
    `zero_inflated_discrete` 撤为 `rounded_truncated_normal`。

    **撤标签不是为过门放宽判据**——它把标签改成当前真实行为：本条从未配
    `calib_zero_prob` ⇒ `generator.py:1577` 的零膨胀分支从未进过，实际一直按
    `normal(0.95,1.12)` 采。同形先例＝`duration.delivery.deadline.to_person`
    （`决议_分布授权_20260805` §二.1，同样撤标签）。零采样影响三重实测：
    ①`_normalize_distribution_name` 两名字同映射 `normal`；②同 seed 2 万次采样
    repr 字节全等、rng 终态相同；③MC 重跑（n=10000×4，同 seed_tag）`slots` 段逐位相同。

    ⚠️ 撤标签**不预判「该不该补零膨胀」**：本槽物理上「合格楼 failed=0」是真质量点，
    补零膨胀属另裁（决议_A16裁定 §三「须入冻结窗口另裁」，补值＝分布实质变更）。
    本断言守的是「registry 里不得再出现带标签却无 calib 参数的条目」这条不变量本身。"""
    violations = gate.collect_zero_inflated_violations(BUNDLE)
    assert violations == [], f"仍有标签装饰条目：{violations}"


def test_stale_badges_cleared_by_a16_mc_rerun():
    """③ 画像改锚（A1.6 落地，2026-08-06）：stale 徽章 **45 → 0**。

    归因（`实施记录_A16落地_20260806.md` §四.1）：45 条 `stale_round7_mc_
    granularity_split` 由 A1.6 门检跑（生产两相编排器／n=10000／k=4／
    seed_tag=mc_gate_poolv2_20260806，54 判全 pass）逐槽重盖为
    `passed_pool_v2_mc_20260806`。
    """
    stale = gate.collect_stale_badges(BUNDLE)
    assert stale == [], f"仍有 stale 徽章：{stale[:5]}"


def test_a16_badges_carry_the_new_caliber_and_cover_all_45():
    """③ 配套：重盖后的徽章必须带**可复现口径**，且恰覆盖原 45 条。

    旧徽章只记 `seed` 整数，而重跑器是**键控子流**（种子是字符串标签）、
    聚合期望是 `fragments_per_building` 的函数——两个字段缺一，徽章就复现不出来。
    """
    badged = {}
    for registry in BUNDLE.registries:
        for record in registry.records:
            check = record.get("alignment_check") or {}
            if str(check.get("status") or "") == "passed_pool_v2_mc_20260806":
                badged[str(record.get("slot_id"))] = check
    assert len(badged) == 45, f"A1.6 徽章数 {len(badged)}，应为 45"
    for slot, check in badged.items():
        assert check.get("seed_tag") == "mc_gate_poolv2_20260806", slot
        assert check.get("fragments_per_building") == 4, slot
        assert check.get("monte_carlo_n") == 10000, slot
        assert "observed" in check, slot


def test_mc_report_check_catches_registry_drift(tmp_path):
    """④ 时序违约检测：报告 registry 态与当前不一致必须报出来。"""
    report = tmp_path / "mc.json"
    report.write_text(
        '{"registry_bundle_hash": "deadbeef", "slots": {}}', encoding="utf-8"
    )
    problems = gate.check_mc_report(report, BUNDLE_HASH)
    assert any("时序违约" in p for p in problems)
    # 一致且全 pass ⇒ 零问题
    report.write_text(
        '{"registry_bundle_hash": "%s", "slots": {"x": {"pass": true}}}'
        % BUNDLE_HASH,
        encoding="utf-8",
    )
    assert gate.check_mc_report(report, BUNDLE_HASH) == []
    # 存在 pass=false 槽 ⇒ 报出
    report.write_text(
        '{"registry_bundle_hash": "%s", "slots": {"x": {"pass": false}}}'
        % BUNDLE_HASH,
        encoding="utf-8",
    )
    assert any("未过" in p for p in gate.check_mc_report(report, BUNDLE_HASH))
