"""allow_stop 逐楼精确现网对账（identity-v5 切 live 前只读验证，现网键切换增补 §10 步 7）。

**纯只读、加性、不接活路径、不切 live、不改 v1、不碰 Neo4j、不提交。** 不是 pytest 用例，是一次性对账
驱动：吃 EXP-008 冻结 LLM 批的落盘 fact_pack/rule_slice + 当前权威 397 卡 bundle，产逐楼对账表。

**精确现网 fragment / applicability / DEBT-050 路径（spec §9：旧楼级覆盖对账版已替换）**：经
`identity_shadow.run_shadow_closure` 调 `validate_building_closure(..., shadow_sink=...)` 拿**判定权威
v1 结果** + **逐义务 pre-dedup 五元组键**（主循环旁路登记，判定语义零改），每条 v1 义务经五元组绑定
run catalog 蓝图；再 `reconcile_shadow` 在**同一 pre-dedup 多重集**上按 v1 旧键 vs v5
`canonical_identity_hash` 新键去重对账（**只换键**，状态仍走 v1 `_merge_two`）。

逐楼验收（spec §10 步 7）：
  ① allow_stop 30/30 零翻转（v1 判定权威 vs v5 键去重后重算 allow_stop）；
  ② open/blocked 存在性零翻转；
  ③ 状态字段逐源零差（未归因差 = 0）；
  ④ v5 键 dedupe 相对 v1 的义务集差异逐条归因（v1 有损去重 / v5 过合并）。

Track A（保留）：HEAD v1 跑**落盘 stale** fact_pack+rule_slice vs 落盘 closure_summary——验现 HEAD v1 对
旧产物输出非扰动（identity-v5 加性零扰动的最终证明；差异按 DEBT-050 结构 NA 归因，残差应 0）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve()
while REPO.name and not (REPO / "agent_v1").exists():
    REPO = REPO.parent
BUNDLE = REPO / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023" / "rule_cards.json"

from evo_agent_baseline.contracts import FactPack, RuleCardDTO, RuleSlice
from evo_agent_baseline.closure.identity_blueprint_catalog import (
    build_identity_blueprint_catalog,
)
from evo_agent_baseline.closure.identity_shadow import (
    reconcile_shadow, run_shadow_closure,
)
from evo_agent_baseline.closure.validator import validate_building_closure


def load_float_cards() -> List[RuleCardDTO]:
    data = json.loads(BUNDLE.read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


def _rule_slice_current(disk_slice: RuleSlice, float_cards: List[RuleCardDTO]) -> RuleSlice:
    """当前 397 卡 + 落盘 rule_slice 的 registry/policy（bundle 级、卡无关）。"""
    return RuleSlice(
        run_id=disk_slice.run_id,
        rulecard_bundle_id=disk_slice.rulecard_bundle_id,
        candidate_rule_cards=float_cards,
        rule_families=disk_slice.rule_families,
        semantic_slots=disk_slice.semantic_slots,
        measures=disk_slice.measures,
        artifacts=disk_slice.artifacts,
        time_anchors=disk_slice.time_anchors,
        source_quotes=disk_slice.source_quotes,
        retrieval_policy=disk_slice.retrieval_policy,
    )


def reconcile_building(run_dir: Path, float_cards: List[RuleCardDTO]) -> Dict[str, Any]:
    fp = FactPack(**json.loads((run_dir / "fact_pack.json").read_text(encoding="utf-8")))
    disk_slice = RuleSlice(**json.loads((run_dir / "rule_slice.json").read_text(encoding="utf-8")))
    meta = {"run_id": fp.run_id, "world_id": fp.world_id, "building_id": fp.building_id}
    out: Dict[str, Any] = {"building_id": fp.building_id}

    # ---------- Track A：v5 活动路径跑 stale 落盘输入 vs 落盘 v1 closure_summary（DEBT-050 归因锚）----------
    # 现网键切换后无 v1 路径；Track A 改为「按原候选 ID 映射当前卡 → 建 catalog → 跑 v5 活动路径」，
    # 与落盘 v1 产物对比。**counts_match 预期 0/30**（v5 = 新键 + DEBT-050 fragment 结构 NA，本就与旧
    # v1 楼级产物计数不同）——如实标 DEBT-050 归因，非「非扰动」（加固①，codex 019f6e51）。
    # obligation_id 亦从 v1 拼串键切到 v5 身份哈希 → shared_id 交集恒近 0（不再做逐 id 状态对齐，改记
    # 交集规模作诊断）。
    disk = json.loads((run_dir / "closure_validation_result.json").read_text(encoding="utf-8"))
    disk_cs = disk["closure_summary"]
    # 按原候选 ID 映射当前卡：用落盘 rule_slice 的候选 ID 选当前 397 卡（同 ID 当前内容）。
    disk_cand_ids = {str(c.rule_card_id) for c in disk_slice.candidate_rule_cards}
    cur_by_id = {str(c.rule_card_id): c for c in float_cards}
    mapped_cards = [cur_by_id[i] for i in sorted(disk_cand_ids) if i in cur_by_id]
    rs_A = _rule_slice_current(disk_slice, mapped_cards)
    try:
        catA = build_identity_blueprint_catalog(BUNDLE, rs_A, fp, meta)
        headA = validate_building_closure(rs_A, fp, identity_blueprint_catalog=catA)
        hcs = headA.closure_summary.model_dump()
        keys = ("allow_stop", "total_obligations", "closed_count", "open_count", "blocked_count",
                "satisfied_count", "violated_count", "unknown_count", "not_applicable_count")
        disk_ids = {o["obligation_id"] for o in disk["obligation_set"]["obligations"]}
        head_ids = {o.obligation_id for o in headA.obligation_set.obligations}
        out["trackA"] = {
            "allow_stop_match": bool(disk_cs["allow_stop"]) == bool(hcs["allow_stop"]),
            # counts_match 预期 False（DEBT-050 归因；v5 楼级+fragment 结构 NA 与旧 v1 楼级产物不同）。
            "counts_match": all(disk_cs.get(k) == hcs.get(k) for k in keys),
            "counts_match_expected": False,
            "attribution": "DEBT-050 fragment structural NA + v5 identity-hash keys",
            "shared_obligation_id_overlap": len(disk_ids & head_ids),
        }
    except Exception as exc:  # noqa: BLE001
        out["trackA"] = {"error": f"{type(exc).__name__}: {exc}"}
    del disk  # 释放内存

    # ---------- Track B：精确现网 fragment 路径 v1(旧键) vs v5(新键) 影子对账 ----------
    rs_cur = _rule_slice_current(disk_slice, float_cards)
    unbound = 0
    try:
        run = run_shadow_closure(BUNDLE, rs_cur, fp, meta)
        out["trackB"] = reconcile_shadow(run)
    except Exception as exc:  # noqa: BLE001 —— 对账驱动：把 hard-fail（unbound/miss/collision）落盘归因
        unbound = 1
        out["trackB"] = {"error": f"{type(exc).__name__}: {exc}"}
    out["trackB_unbound_or_error"] = unbound
    return out


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(results)
    ok_track_b = [r for r in results if "error" not in r["trackB"]]
    allow_flip = sum(1 for r in ok_track_b if r["trackB"]["allow_stop_flip"])
    open_flip = sum(1 for r in ok_track_b if r["trackB"]["open_exist_flip"])
    blk_flip = sum(1 for r in ok_track_b if r["trackB"]["blocked_exist_flip"])
    unexplained = sum(r["trackB"]["unexplained_status_diffs"] for r in ok_track_b)
    v5_auth_match = sum(1 for r in ok_track_b if r["trackB"]["v5_shadow_matches_authoritative"])
    v1_lossy = sum(r["trackB"]["v1_lossy_merge_groups"] for r in ok_track_b)
    v5_over = sum(r["trackB"]["v5_over_merge_groups"] for r in ok_track_b)
    errors = [r["building_id"] for r in results if "error" in r["trackB"]]
    # Track A：现网键切换后为 DEBT-050 归因锚（counts_match 预期 0/30，不作放行门）。
    trackA_ok = [r for r in results if "error" not in r["trackA"]]
    trackA_allow_match = sum(1 for r in trackA_ok if r["trackA"]["allow_stop_match"])
    trackA_counts_match = sum(1 for r in trackA_ok if r["trackA"]["counts_match"])
    return {
        "buildings": n,
        "trackB_evaluated": len(ok_track_b),
        "trackB_errors": errors,
        "allow_stop_flips": allow_flip,
        "open_exist_flips": open_flip,
        "blocked_exist_flips": blk_flip,
        "unexplained_status_diffs": unexplained,
        "v5_shadow_matches_authoritative": f"{v5_auth_match}/{len(ok_track_b)}",
        "v1_lossy_merge_groups_total": v1_lossy,
        "v5_over_merge_groups_total": v5_over,
        "trackA_evaluated": len(trackA_ok),
        "trackA_allow_stop_match": f"{trackA_allow_match}/{len(trackA_ok)}",
        "trackA_counts_match_expected_0": f"{trackA_counts_match}/{len(trackA_ok)}",
    }


if __name__ == "__main__":
    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    only = sys.argv[2] if len(sys.argv) > 2 else None
    float_cards = load_float_cards()
    print(f"float_cards={len(float_cards)} buildings={len(manifest)}", flush=True)
    results = []
    for i, (bid, entry) in enumerate(sorted(manifest.items())):
        if only and only not in bid:
            continue
        rd = REPO / entry["run_dir"]
        r = reconcile_building(rd, float_cards)
        r["commit"] = entry["commit"]
        results.append(r)
        tb = r["trackB"]
        if "error" in tb:
            print(f"[{i+1:02d}] {bid}  Track B ERROR: {tb['error']}", flush=True)
            continue
        print(f"[{i+1:02d}] {bid}", flush=True)
        ta = r["trackA"]
        if "error" in ta:
            print(f"     A: ERROR {ta['error']}", flush=True)
        else:
            print(f"     A: allow_stop_match={ta['allow_stop_match']} "
                  f"counts_match={ta['counts_match']}(预期False,DEBT-050) "
                  f"id_overlap={ta['shared_obligation_id_overlap']}", flush=True)
        print(f"     B: allow_stop_flip={tb['allow_stop_flip']} open_flip={tb['open_exist_flip']} "
              f"blk_flip={tb['blocked_exist_flip']} unexplained_status={tb['unexplained_status_diffs']} "
              f"v5auth_match={tb['v5_shadow_matches_authoritative']}", flush=True)
        print(f"        auth open/blk/tot={tb['authoritative']['open']}/"
              f"{tb['authoritative']['blocked']}/{tb['authoritative']['total']} | "
              f"v1 open/blk/tot={tb['v1_shadow']['open']}/{tb['v1_shadow']['blocked']}/{tb['v1_shadow']['total']} | "
              f"v5 open/blk/tot={tb['v5_shadow']['open']}/{tb['v5_shadow']['blocked']}/{tb['v5_shadow']['total']} | "
              f"v1_lossy={tb['v1_lossy_merge_groups']} v5_over={tb['v5_over_merge_groups']} "
              f"identities={tb['distinct_identities']}", flush=True)
    summary = _summarize(results)
    outp = manifest_path.parent / "reconcile_results_v5.json"
    outp.write_text(json.dumps({"summary": summary, "buildings": results},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n==== SUMMARY ====", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    print(f"\nwrote {outp}  ({len(results)} buildings)", flush=True)
