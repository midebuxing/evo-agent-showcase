"""#25 真值落改案的**冻结断言**（2026-08-05）。

权威依据：`团队文档/我的笔记/决议_真值落改_20260805.md`。
落改脚本：`agent_v1/scripts/apply_truth_landing_25_20260805.py`（A1-A10 先验后写）。

## 这个文件锁什么

落改脚本只在**落改那一刻**跑一次。本文件把其中**跨时间仍然成立**的那几条
（A5/A6/A7/A8/A9）搬成常驻断言，防止后续有人悄悄改回去或悄悄改多。

## 🔴 A8 是本文件的核心：把「没修的 24 行」冻成一条会被看住的账

全库「`applicable is True` 且 reason 自述判不适用」的自相矛盾行，落改前 **28** 行
（7 个规范项 × 完全相同的 4 栋楼，行号 543-546／571-574／587-598／599-602／615-618）。

本案**只授权修其中 4 行**（L599-602，即 §2.1.3(n) 那一项）——登记表只点名了这四行。
其余 **24 行**横跨 §2.1.3 的 (a)/(g)/(k)/(l)/(m)/(p) 六项，
**没有任何一条口径被裁定过**；决定「是值错还是理由错」需要逐条款的前件模型，
那是新的语义裁定，不是执行既有裁定 ⇒ **自决方向＝自造判据**。

故期望值冻在 **24**：
- 变小 ⇒ 有人在没有口径的情况下自决修了（**不许**）；
- 变大 ⇒ 有人又造出了新的同形矛盾（本案 §2.4 警告过的形状：
  只翻 `applicable` 不动 reason ⇒ 矛盾行 28→43）。

两个方向都必须当场红。若决策门将来批准扩到 28 行全修，**改这个常数是那次落改的一部分**。

## 诚实边界

本文件不证明那 29 行**改对了**——「改对了」由 Q2/Q3 口径裁定与两线复核负责，
本文件只保证「改完之后没人再动它」。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_EVAL = (Path(__file__).resolve().parents[1] / "src" / "evo_agent_baseline" / "eval")
_TRUTH = _EVAL / "applicable_normative_item_truth_v1.jsonl"
_SCHEMA = _EVAL / "applicable_normative_item_truth_v1.schema.json"

PENDING = "unknown_pending"
Q3_ITEM_ID = "mbis.cop2023.s2_1_3_n.notify_ba_investigation_intention"
CIRC_RE = re.compile(r"(?:判据)?情形\s*([123])")

#: A5 预注册期望值（落改脚本里的同一组常数；两处不一致即说明有人只改了一边）
EXPECT_DISTRIBUTION = {"true": 2343, "false": 423, PENDING: 4}
EXPECT_TOTAL_LINES = 2770
#: A8 冻结值。改它必须伴随一次获授权的落改，见本文件 docstring。
EXPECT_CONTRADICTION_ROWS = 24


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    out = [json.loads(ln) for ln in _TRUTH.read_text(encoding="utf-8").splitlines()
           if ln.strip()]
    assert out, "真值文件为空"
    return out


def _circ(reason: str) -> str | None:
    m = CIRC_RE.search(reason or "")
    return m.group(1) if m else None


def _is_contradiction(rec: dict) -> bool:
    """「值 True／理由自述判不适用」——与落改脚本 `_is_contradiction` 同源判据。"""
    if rec.get("applicable") is not True:
        return False
    reason = rec.get("reason") or ""
    return "判不适用" in reason or reason.startswith("排除依据")


# ── A8：射程外 24 行冻结（本文件核心） ────────────────────────────────


def test_a8_contradiction_rows_frozen_at_24(rows):
    """🔴 变小＝自决修了无口径的行；变大＝又造出了新的同形矛盾。两向都必须红。"""
    hits = [
        {
            "building_id": r["building_id"],
            "source_clause_id": r["source_clause_id"],
            "normative_item_id": r["normative_item_id"],
        }
        for r in rows if _is_contradiction(r)
    ]
    assert len(hits) == EXPECT_CONTRADICTION_ROWS, (
        f"自相矛盾行 {len(hits)} ≠ 冻结值 {EXPECT_CONTRADICTION_ROWS}。"
        f"变小＝在无口径的情况下自决修了（不许）；变大＝造出了新的同形矛盾。"
        f"前 5 条：{hits[:5]}"
    )


def test_a8_residual_contradictions_are_all_outside_s2_1_3_n(rows):
    """射程内那 4 行（§2.1.3(n)）必须已清零——剩下的 24 行全在射程外六项上。"""
    residual_items = sorted({r["normative_item_id"] for r in rows if _is_contradiction(r)})
    assert Q3_ITEM_ID not in residual_items, (
        f"§2.1.3(n) 仍有自相矛盾行——本案授权修的 4 行没修干净：{residual_items}")
    assert len(residual_items) == 6, (
        f"射程外矛盾项应恰为 §2.1.3 的 (a)/(g)/(k)/(l)/(m)/(p) 六项，"
        f"实得 {len(residual_items)} 项：{residual_items}")


# ── A5：全库三态分布 ─────────────────────────────────────────────────


def test_a5_applicable_distribution_frozen(rows):
    dist = {"true": 0, "false": 0, PENDING: 0}
    for r in rows:
        v = r.get("applicable")
        if v is True:
            dist["true"] += 1
        elif v is False:
            dist["false"] += 1
        elif v == PENDING:
            dist[PENDING] += 1
        else:
            pytest.fail(f"applicable 取值非法 {v!r} @ {r['normative_item_id']}")
    assert len(rows) == EXPECT_TOTAL_LINES
    assert dist == EXPECT_DISTRIBUTION, f"三态分布漂移：实得 {dist}"
    assert sum(dist.values()) == EXPECT_TOTAL_LINES


# ── A6 / A7：两个落改族的族内自洽 ──────────────────────────────────


def test_a6_s3_1_1_family_all_true_and_circumstance_1(rows):
    """§3.1.1 族 40 行全 true、情形全 1。

    Q2 口径：条款唯一写出的前件是「被選定為目標樓宇」（本批恒真）；
    「伸出物／招牌」是被涵蓋範圍的列举项，不是前件。
    """
    fam = [r for r in rows if r["source_clause_id"] == "3.1.1"]
    assert len(fam) == 40, f"§3.1.1 族应为 4 项 × 10 栋 = 40 行，实得 {len(fam)}"
    bad_value = [r["normative_item_id"] for r in fam if r["applicable"] is not True]
    assert bad_value == [], f"§3.1.1 族出现非 true 行：{bad_value}"
    bad_circ = [(r["building_id"], r["normative_item_id"], _circ(r["reason"]))
                for r in fam if _circ(r["reason"]) != "1"]
    assert bad_circ == [], f"§3.1.1 族情形号不为 1：{bad_circ}"


def test_a7_s2_1_3_n_family_six_true_four_pending(rows):
    """§2.1.3(n) 族：true 6 / unknown_pending 4 / false 0。"""
    fam = [r for r in rows if r["normative_item_id"] == Q3_ITEM_ID]
    assert len(fam) == 10, f"§2.1.3(n) 族应为 1 项 × 10 栋 = 10 行，实得 {len(fam)}"
    counts = {
        "true": sum(1 for r in fam if r["applicable"] is True),
        "false": sum(1 for r in fam if r["applicable"] is False),
        PENDING: sum(1 for r in fam if r["applicable"] == PENDING),
    }
    assert counts == {"true": 6, "false": 0, PENDING: 4}, f"族内分布漂移：{counts}"


def test_q3_pending_rows_are_exactly_the_four_proposal_absent_buildings(rows):
    """挂起的 4 栋必须恰是建议书 0/5 的那四栋。

    🔴 **锚池**（2026-08-05 审核门必须修 1）：这四栋来自批
    `baseline_batch_final_seed301`（世界池
    `agent_v1/experiments/qa_reports/_reanchor_50x1_seed301/gen_seed_301`）的
    fact_pack 对账，两线复核在**该池上** 10/10 吻合。
    本断言不读批产物，故它永远绿——但它冻住的是一个**只在该池上为真**的事实：
    同标签的 `_fragcov2_50x1_seed301` 池（批 `phase_i_fragcov2_seed301_20260729`）上
    这四栋的建议书全部在场、而判 true 的 0033 反而缺席（十栋 5 栋反号）。
    ⇒ 换池后本断言与真值文件都必须重锚，不是「测试绿了就说明真值对」。
    """
    pending = sorted(r["building_id"] for r in rows
                     if r["normative_item_id"] == Q3_ITEM_ID
                     and r["applicable"] == PENDING)
    assert pending == [
        "BLD-HK-COMMERCIAL-ASSEMBLY-MARKET-PODIUM-0002",
        "BLD-HK-MASS-HOUSING-RC-WALL-0006",
        "BLD-HK-MIXED-USE-HIGHRISE-TOWER-RC-0008",
        "BLD-HK-NT-VILLAGE-LOWRISE-RC-0028",
    ], f"挂起楼集合与建议书缺席楼不符：{pending}"


def test_q3_reasons_exclude_the_notice_artifact_slot(rows):
    """🔴 决议 §三.1：`artifact.notice.investigation_intention` 不得作证据。

    这条排除必须**写在真值 reason 里**（官方线抓的是文档层缺口）——
    口径只活在裁定文档里、不落在数据自述里，下一个人照样会用它。
    """
    fam = [r for r in rows if r["normative_item_id"] == Q3_ITEM_ID]
    changed = [r for r in fam if r["applicable"] is True or r["applicable"] == PENDING]
    missing = [r["building_id"] for r in changed
               if "artifact.notice.investigation_intention" not in (r["reason"] or "")]
    # L2508（0009）是本案唯一不动的行，其 reason 走的是旧的正向推理文本。
    missing = [b for b in missing if not b.endswith("0009")]
    assert missing == [], (
        f"以下栋的 §2.1.3(n) reason 未显式排除 notice 槽：{missing}")


def test_q3_reasons_declare_their_evidence_pool(rows):
    """🔴 审核门必须修 1：写死世界计数的 reason 必须自己点名锚池。

    九行 Q3 reason 把 `artifact.proposal.detailed_investigation` 的取真计数
    写进了权威数据自述，而该计数**只在 `_reanchor` 池上成立**。不点名批/池 ⇒
    下一个人拿最新批（如 `_fragcov2`）一核就会得出「真值错了」——官方线审核时
    就真走了这条弯路。故把「锚在哪个池」做成断言，不许再被改回无锚版本。
    """
    fam = [r for r in rows if r["normative_item_id"] == Q3_ITEM_ID]
    changed = [r for r in fam
               if r["applicable"] is True or r["applicable"] == PENDING]
    # L2508（0009）是本案唯一不动的行，reason 走旧的正向推理文本、不含世界计数。
    changed = [r for r in changed if not r["building_id"].endswith("0009")]
    assert len(changed) == 9, f"Q3 落改行应为 9 行，实得 {len(changed)}"
    missing = [r["building_id"] for r in changed
               if "baseline_batch_final_seed301" not in (r["reason"] or "")
               or "不可跨池引用" not in (r["reason"] or "")]
    assert missing == [], (
        f"以下栋的 §2.1.3(n) reason 未声明证据锚池：{missing}")


# ── A9：schema 校验接上主链 ───────────────────────────────────────────


def test_a9_every_row_conforms_to_schema(rows):
    """🔴 这道校验此前**不在主链**（全仓无一处按 `.schema.json` 校验真值）。

    扩枚举时「schema 说三态、文件里冒出第四态」正是会静默发生的形状，本条补上。
    """
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    required = schema.get("required") or list(props)
    errs: list[str] = []
    for i, r in enumerate(rows, start=1):
        for k in required:
            if k not in r:
                errs.append(f"L{i} 缺字段 {k}")
        if schema.get("additionalProperties") is False:
            errs.extend(f"L{i} 多余字段 {k}" for k in r if k not in props)
        for k in ("scope_type", "modality_zh", "conditionality"):
            allowed = props.get(k, {}).get("enum")
            if allowed and r.get(k) not in allowed:
                errs.append(f"L{i} {k}={r.get(k)!r} 越出枚举")
    assert errs == [], f"schema 违规 {len(errs)} 条：{errs[:10]}"


def test_schema_applicable_declares_three_states():
    """schema 自身必须声明三态（boolean ∪ const 字符串），不许退回纯 boolean。"""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    spec = schema["properties"]["applicable"]
    assert "oneOf" in spec, "schema 的 applicable 已退回单一 type，第三态会静默失去约束"
    consts = [b.get("const") for b in spec["oneOf"] if "const" in b]
    types = [b.get("type") for b in spec["oneOf"] if "type" in b]
    assert PENDING in consts and "boolean" in types, f"三态声明不完整：{spec['oneOf']}"
