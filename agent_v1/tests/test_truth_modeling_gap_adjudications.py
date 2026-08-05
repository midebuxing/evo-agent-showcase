"""DEBT-080 裁定登记表的契约（2026-07-29 立）。

登记表 `eval/truth_modeling_gap_adjudications_v1.json` 是「哪些可疑真值项已经
逐条对中文正文裁定过」的权威记录。审计器据它把可疑项拆成「已裁定 / 未裁定」，
验收软项报的是**未裁定数**。

这里锁三条——每条都对应一种「登记表悄悄失效」的方式：

1. **登记的项必须真的在真值里**。写错一个 id 不会报错，只会让它永远匹配不上，
   于是那条可疑项一直算「未裁定」，而登记表看起来又是满的。
2. **裁定必须写依据、且 `reason_status` 只能取两值**。空依据的登记＝把待办
   标成已办，比不登记更糟。
3. **本表不得改动 verdict**。`verdict_holds` 必须恒真——若哪天有项要改
   `applicable`，那是改真值本身，须走另一条路径并留独立记录，不能藏在这张表里。
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "src/evo_agent_baseline/eval"
ADJ = EVAL / "truth_modeling_gap_adjudications_v1.json"
TRUTH = EVAL / "applicable_normative_item_truth_v1.jsonl"


def _doc() -> dict:
    return json.loads(ADJ.read_text(encoding="utf-8"))


def _truth_item_ids() -> set[str]:
    return {json.loads(ln)["normative_item_id"]
            for ln in TRUTH.read_text(encoding="utf-8").splitlines() if ln.strip()}


def test_every_adjudicated_item_exists_in_truth() -> None:
    known = _truth_item_ids()
    for it in _doc()["items"]:
        assert it["normative_item_id"] in known, \
            f"{it['normative_item_id']} 不在真值里——id 打错了，这条裁定永远匹配不上"


def test_each_adjudication_has_a_status_and_a_basis() -> None:
    for it in _doc()["items"]:
        assert it["reason_status"] in ("stands", "corrected"), it["normative_item_id"]
        assert it.get("basis", "").strip(), f"{it['normative_item_id']} 缺 basis"
        if it["reason_status"] == "corrected":
            assert it.get("corrected_on"), f"{it['normative_item_id']} 标了 corrected 但没写日期"


def test_registry_never_flips_a_verdict() -> None:
    """本表只裁 reason。任何 verdict 改动都不许藏在这里。"""
    for it in _doc()["items"]:
        assert it["verdict_holds"] is True, \
            f"{it['normative_item_id']} 想改 verdict——请走真值改动路径并单独留证"


def test_corrected_items_no_longer_assert_the_predicate_is_absent() -> None:
    """标 `corrected` 的项，真值 reason 里必须已带更正标记。

    防的是「登记表说改了、真值其实没改」这种两边不同步。
    只认更正标记，**不禁止引用旧说法**——引文是存档证据。
    """
    doc = _doc()
    corrected = {it["normative_item_id"] for it in doc["items"]
                 if it["reason_status"] == "corrected"}
    seen: dict[str, str] = {}
    for ln in TRUTH.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r["normative_item_id"] in corrected:
            seen[r["normative_item_id"]] = str(r.get("reason") or "")
    assert set(seen) == corrected, f"真值里找不到：{corrected - set(seen)}"
    for nid, reason in seen.items():
        assert "修正" in reason, f"{nid} 标了 corrected，但真值 reason 里没有更正标记"
