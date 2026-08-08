"""``eval/truth_generation_rules.py`` 单测 —— M14 ／ 步 A1.5 的验收半边。

工单点名的验收判据是两条：「断言在场」＋「删分支有回归测试钉住」
（``团队文档/我的笔记/换池批总工单_v1_20260806.md:111-116``）。
故本文件的重心不是覆盖率，而是：

1. 被 ``决议_真值落改_20260805.md`` §二裁删的 ``ELIF NOTIFIED`` 分支，
   **结构上回不来**——用 :func:`inspect.signature` 证明内核压根没有 notified 入口；
2. 内核自产的 reason **一个被禁槽名都不含**（这是 :func:`_cited_as_evidence`
   启发式之外的那条硬保证）；
3. :func:`verify_truth_face_invariants` 红绿两臂都验过——只验绿臂等于没验闸。
"""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from evo_agent_baseline.eval import truth_generation_rules as tgr
from evo_agent_baseline.eval.truth_generation_rules import (
    APPLICABLE_FALSE,
    APPLICABLE_PENDING,
    APPLICABLE_TRUE,
    Q2_ITEM_PREFIX,
    Q3_ANTECEDENT_SLOT,
    Q3_FORBIDDEN_EVIDENCE_SLOTS,
    Q3_ITEM_ID,
    Q3_PROXY_SLOT,
    q2_applicable,
    q2_reason,
    q3_applicable,
    verify_truth_face_invariants,
)

TRUTH_FILE = (
    pathlib.Path(tgr.__file__).resolve().parent
    / "applicable_normative_item_truth_v1.jsonl"
)


# ── 测试夹具 ──────────────────────────────────────────────────────────────


def _q2_row(building_id: str = "BLD-X", suffix: str = "cover_external_walls") -> dict:
    """按内核口径造一条合规 Q2 行。"""
    state, _ = q2_applicable()
    return {
        "building_id": building_id,
        "normative_item_id": Q2_ITEM_PREFIX + suffix,
        "applicable": tgr.encode_applicable(state),
        "reason": q2_reason("外牆"),
    }


def _q3_row(building_id: str, intended, proposal) -> dict:
    """按内核口径造一条合规 Q3 行。"""
    state, reason = q3_applicable(intended, proposal)
    return {
        "building_id": building_id,
        "normative_item_id": Q3_ITEM_ID,
        "applicable": tgr.encode_applicable(state),
        "reason": reason,
    }


# ── Q2 ────────────────────────────────────────────────────────────────────


def test_q2_is_unconditionally_true_at_circumstance_one() -> None:
    assert q2_applicable() == (APPLICABLE_TRUE, 1)


def test_q2_takes_no_argument_so_fragment_inventory_cannot_become_an_antecedent() -> None:
    """§3.1.1 没有可变前件 ⇒ 无参。有参就意味着有人能把「对象是否存在」喂进来。"""
    assert list(inspect.signature(q2_applicable).parameters) == []


def test_q2_reason_carries_circumstance_marker_and_no_forbidden_phrase() -> None:
    reason = q2_reason("訂明的伸出物")
    assert "（判据情形 1）" in reason
    assert tgr.FORBIDDEN_REASON_PHRASE not in reason
    assert not reason.startswith(tgr.FORBIDDEN_REASON_PREFIX)


# ── Q3 四分支 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("intended", "proposal", "expected"),
    [
        (True, True, APPLICABLE_TRUE),
        (True, None, APPLICABLE_TRUE),
        (True, False, APPLICABLE_TRUE),
        (False, True, APPLICABLE_FALSE),
        (False, None, APPLICABLE_FALSE),
        (False, False, APPLICABLE_FALSE),
        (None, True, APPLICABLE_TRUE),
        (None, False, APPLICABLE_PENDING),
        (None, None, APPLICABLE_PENDING),
    ],
)
def test_q3_branches(intended, proposal, expected) -> None:
    state, reason = q3_applicable(intended, proposal)
    assert state == expected
    assert reason


def test_q3_intended_overrides_proposal_in_both_directions() -> None:
    """前件槽在场时，建议书代理**不参与**判定——代理只是前件槽缺席时的回退。"""
    assert q3_applicable(False, True)[0] == APPLICABLE_FALSE
    assert q3_applicable(True, False)[0] == APPLICABLE_TRUE


def test_q3_rejects_non_tristate_inputs() -> None:
    """挡「非空字符串被真值判断当成真」这类静默退化。"""
    for bad in ("true", "false", 1, 0, "unknown_pending"):
        with pytest.raises(TypeError):
            q3_applicable(bad, None)
        with pytest.raises(TypeError):
            q3_applicable(None, bad)


# ── 🔴 钉死被裁删的 ELIF NOTIFIED 分支（工单点名验收） ────────────────────


def test_deleted_notified_branch_cannot_be_expressed_structurally() -> None:
    """内核签名里没有 notified 类形参 ⇒ 反推**没有入口**，不是「被规则禁止」。

    `决议_真值落改_20260805.md` §二：`procedure.investigation.intention_notified`
    是独立采样布尔，「已通知」不蕴含「有意」，故 `ELIF NOTIFIED is true ->
    applicable=true` 会对 `intended=false ∧ notified=true` 的栋造假 true。
    """
    params = set(inspect.signature(q3_applicable).parameters)
    assert params == {"intended", "proposal_any_true"}
    assert not [p for p in params if "notif" in p.lower()]


def test_notified_true_but_evidence_absent_lands_unknown_pending() -> None:
    """回归：被删分支当年判 true 的那一类栋，现内核判 unknown_pending。

    构造的是「notified=true ∧ 前件槽缺席 ∧ 建议书缺席」——notified 之所以不出现在
    调用里，正是因为它已经不是判据；这一栋在旧规则下会命中 `ELIF NOTIFIED`。
    """
    for proposal in (False, None):
        state, reason = q3_applicable(None, proposal)
        assert state == APPLICABLE_PENDING
        assert "双缺" in reason


# ── reason 口径 ───────────────────────────────────────────────────────────


def test_q3_true_reasons_cite_an_authorized_positive_evidence() -> None:
    """true 分支必须引前件槽或建议书代理；引代理时必须显式声明 any_true 量词。"""
    by_intended = q3_applicable(True, None)[1]
    assert Q3_ANTECEDENT_SLOT in by_intended

    by_proposal = q3_applicable(None, True)[1]
    assert Q3_PROXY_SLOT in by_proposal
    assert "any_true" in by_proposal


@pytest.mark.parametrize(
    ("intended", "proposal"),
    [(True, None), (False, None), (None, True), (None, None)],
)
def test_q3_reasons_never_cite_forbidden_slots_nor_forbidden_phrase(
    intended, proposal
) -> None:
    """全分支硬保证：内核自产 reason 里被禁槽名**零出现**（不是「出现但被排除」）。"""
    reason = q3_applicable(intended, proposal)[1]
    assert tgr.FORBIDDEN_REASON_PHRASE not in reason
    for token in Q3_FORBIDDEN_EVIDENCE_SLOTS:
        assert token not in reason
    assert "procedure.investigation.intention_notified" not in reason


def test_q3_reasons_all_carry_circumstance_two() -> None:
    for intended, proposal in [(True, None), (False, None), (None, True), (None, None)]:
        assert "（判据情形 2）" in q3_applicable(intended, proposal)[1]


# ── verify_truth_face_invariants：绿臂 ───────────────────────────────────


def test_invariants_green_arm() -> None:
    rows = [
        _q2_row("BLD-A", "cover_external_walls"),
        _q2_row("BLD-A", "cover_prescribed_projections"),
        _q3_row("BLD-A", True, None),
        _q3_row("BLD-B", False, None),
        _q3_row("BLD-C", None, True),
        _q3_row("BLD-D", None, None),
    ]
    assert verify_truth_face_invariants(rows) == []


def test_invariants_green_arm_with_world_recompute() -> None:
    world = {
        "BLD-A": (True, None),
        "BLD-B": (False, None),
        "BLD-C": (None, True),
        "BLD-D": (None, None),
    }
    rows = [_q3_row(bid, *inputs) for bid, inputs in world.items()]
    assert verify_truth_face_invariants(rows, world) == []


def test_invariants_ignore_rows_outside_q2_q3_scope() -> None:
    """射程外的行一个都不判——包括那些合法点名被禁槽的别族行。"""
    alien = {
        "building_id": "BLD-A",
        "normative_item_id": "mbis.cop2023.s4_2_3.no_di_before_ba_endorsement",
        "applicable": True,
        "reason": (
            "世界确实产出意向谓词（`artifact.notice.investigation_intention` 取真、"
            "`procedure.investigation.intention_notified` 取真）。"
        ),
    }
    assert verify_truth_face_invariants([alien]) == []


# ── verify_truth_face_invariants：红臂 ───────────────────────────────────


def test_invariants_red_arm_q2_false_is_caught() -> None:
    row = _q2_row()
    row["applicable"] = False
    violations = verify_truth_face_invariants([row])
    assert len(violations) == 1
    assert "Q2 族 applicable 必须为 true" in violations[0]


def test_invariants_red_arm_reason_citing_notified_as_evidence_is_caught() -> None:
    row = _q3_row("BLD-A", True, None)
    row["reason"] = (
        "适用依据＝§2.1.3(n) 的前件 P：有意進行詳細調查。"
        "`procedure.investigation.intention_notified` 本楼取真 ⇒ P 成立 ⇒ 适用。"
        "（判据情形 2）"
    )
    violations = verify_truth_face_invariants([row])
    assert len(violations) == 1
    assert "把被禁槽当依据用" in violations[0]


def test_invariants_red_arm_exclusion_sentence_is_not_a_violation() -> None:
    """对照：同一个槽名写在**排除句**里就不该报——否则判据在人群上命中 100%。"""
    row = _q3_row("BLD-A", True, None)
    row["reason"] += (
        "⚠️ 亦不得以 `artifact.notice.investigation_intention` 代理「通知已作出」"
        "（决议 §三.1）。"
    )
    assert verify_truth_face_invariants([row]) == []


def test_invariants_red_arm_q2_missing_circumstance_marker_is_caught() -> None:
    row = _q2_row()
    row["reason"] = "适用依据＝该条款自己的作用域谓词，无条件适用。"
    violations = verify_truth_face_invariants([row])
    assert len(violations) == 1
    assert "情形标记必须恒为 1" in violations[0]


def test_invariants_red_arm_forbidden_phrase_is_caught() -> None:
    row = _q3_row("BLD-A", True, None)
    row["reason"] += "本楼查无此对象，判不适用。"
    violations = verify_truth_face_invariants([row])
    assert any("含禁语" in v for v in violations)


def test_invariants_red_arm_world_recompute_mismatch_is_caught() -> None:
    row = _q3_row("BLD-A", None, None)          # 内核判 unknown_pending
    row["applicable"] = True                     # 人手改成 true
    violations = verify_truth_face_invariants([row], {"BLD-A": (None, None)})
    assert any("Q3 复算不一致" in v for v in violations)


def test_invariants_red_arm_illegal_applicable_encoding_is_caught() -> None:
    row = _q2_row()
    row["applicable"] = "true"                   # 字符串 "true" 不是 schema 形态
    violations = verify_truth_face_invariants([row])
    assert any("applicable 取值非法" in v for v in violations)


# ── 现存真值文件（旧池 S00301）现实对照 ──────────────────────────────────
#
# 说明：这份文件锚在旧池、换池后一行都不会被消费（底稿 :360-361），
# 这里跑它只为一件事——**证明内核的判据与 #25 落改后的既有事实对得上**，
# 顺带把对不上的地方钉在纸上。


def _load_scoped_rows() -> tuple[list[dict], list[dict]]:
    rows = [
        json.loads(line)
        for line in TRUTH_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    q2 = [r for r in rows if str(r["normative_item_id"]).startswith(Q2_ITEM_PREFIX)]
    q3 = [r for r in rows if r["normative_item_id"] == Q3_ITEM_ID]
    return q2, q3


def test_existing_truth_file_q2_rows_satisfy_the_kernel() -> None:
    """Q2 全族（40 行）在 #25 落改后已合规——含两种情形标记承载形态。"""
    q2, _ = _load_scoped_rows()
    assert len(q2) == 40
    assert verify_truth_face_invariants(q2) == []


def test_existing_truth_file_q3_rows_have_only_the_known_l2508_violation() -> None:
    """现实发现：Q3 十行里恰有 **1 行**把被禁槽当依据用，且是唯一一行。

    该行＝L2508（``BLD-HK-MASS-HOUSING-RC-WALL-0009``），#25 落改把它列为
    「唯一现文合规行、一个字节都不动」（``apply_truth_landing_25_20260805.py`` 的
    ``Q3_UNTOUCHED``）——但那只核了 **applicable 值**：它的值 true 恰好也能由合法的
    建议书代理分支得出，于是没被翻。**它的 reason 却是照被裁删的 `ELIF NOTIFIED`
    分支写的**：「`procedure.investigation.intention_notified` 本楼 1 条取真 ⇒ P 成立
    ⇒ 适用」。值对、依据错。

    这条测试**钉住数量**：再多一行就红。真去修 L2508 时，本测试与下面那条 xfail
    要同批改。
    """
    _, q3 = _load_scoped_rows()
    assert len(q3) == 10
    violations = verify_truth_face_invariants(q3)
    assert len(violations) == 1, violations
    assert "MASS-HOUSING-RC-WALL-0009" in violations[0]
    assert "把被禁槽当依据用" in violations[0]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "记录性 xfail：旧池真值文件 Q3 族尚有 1 行（L2508 / …WALL-0009）reason 建立在"
        "被 `决议_真值落改_20260805.md` §二裁删的 ELIF NOTIFIED 分支上。#25 落改按"
        "「applicable 值已正确」把它排除在射程外，未核 reason 依据。修 L2508 属 #25 射程外的"
        "新决策点（改的是既有裁定行的依据文本），须另案请示，不在步 A1.5 授权内——"
        "故此处如实记为 xfail，不放宽断言。修好后本条会 XPASS（strict）而变红，逼人来改。"
    ),
)
def test_existing_truth_file_q2_q3_scope_is_fully_clean() -> None:
    q2, q3 = _load_scoped_rows()
    assert verify_truth_face_invariants(q2 + q3) == []
