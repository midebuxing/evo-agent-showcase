"""B 门(权威完整性)脚本 `agent_v1/scripts/check_report_authority.py` 的行为测试。

覆盖 copilot 终审四/五轮审出的假绿灯病灶:
- 无采纳叙述(合法回退)= 空核明示,计数仍验,不算失败;
- 缺 run_audit / audit 称接纳但载荷缺失或为空 = 产物硬伤,判失败;
- audit 版本与载荷形状矛盾 = 产物硬伤,判失败;
- 全批零绑定 = main 非零退出,不宣绿。
"""
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_report_authority.py"
_spec = importlib.util.spec_from_file_location("check_report_authority", _SCRIPT)
cra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cra)


def _sha(payload_inner):
    """与生成端 _payload_sha256 同口径的载荷哈希（测试用）。"""
    import hashlib
    return hashlib.sha256(json.dumps(
        payload_inner, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


_OB = {
    "obligation_id": "o1",
    "source_rule_card_id": "r1",
    "closure_status": "open",
    "satisfaction_status": "unknown",
    "evidence_fact_ids": ["f1"],
}
_SUMMARY = {
    "total_obligations": 1, "open_count": 1, "blocked_count": 0,
    "closed_count": 0, "satisfied_count": 0, "violated_count": 0,
    "unknown_count": 1, "not_applicable_count": 0,
}


def _mk_building(tmp_path, *, audit=None, payload=None, run_name="CAR-1"):
    bdir = tmp_path / "buildings" / "B-1"
    rdir = bdir / "runs" / run_name
    rdir.mkdir(parents=True)
    (rdir / "closure_validation_result.json").write_text(
        json.dumps({"obligation_set": {"obligations": [_OB]},
                    "closure_summary": _SUMMARY}),
        encoding="utf-8",
    )
    if audit is not None:
        (rdir / "run_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    if payload is not None:
        (rdir / "accepted_payload.json").write_text(json.dumps(payload), encoding="utf-8")
    return str(bdir)


def test_legit_fallback_is_vacuous_pass_with_flag(tmp_path):
    """audit 明说未接纳 = 合法回退:计数仍验、绑定空核明示,不判失败。"""
    b = _mk_building(tmp_path, audit={"llm_narrative_accepted": False})
    r = cra.check_building(b)
    assert r["passed"] is True
    assert r["no_accepted_narrative"] is True
    assert r["bind_total"] == 0
    assert r["integrity_bad"] == []


def test_missing_audit_is_integrity_failure(tmp_path):
    """缺 run_audit = 产物硬伤,不得静默按 0/0 通过(终审四轮#2)。"""
    b = _mk_building(tmp_path, audit=None)
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("run_audit" in m for m in r["integrity_bad"])


def test_accepted_but_payload_missing_is_integrity_failure(tmp_path):
    b = _mk_building(tmp_path, audit={"llm_narrative_accepted": True})
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("accepted_payload" in m for m in r["integrity_bad"])


def test_accepted_but_empty_payload_is_integrity_failure(tmp_path):
    """audit 称接纳但载荷空(无 payload/points)→ 硬伤失败(终审五轮高#1:
    曾按 0/0 静默通过)。"""
    b = _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": True, "narrative_alias_map": {}},
        payload={"payload": {}},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("载荷为空" in m for m in r["integrity_bad"])


def test_version_shape_conflict_is_integrity_failure(tmp_path):
    """audit 标契约 4 但载荷是 v3 自由文本形状 → 硬伤失败(终审五轮高#1)。"""
    b = _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": True, "report_contract_version": 4,
               "narrative_alias_map": {"O1": "o1"}},
        payload={"payload": {"points": [
            {"text": "自由文本", "evidence_aliases": ["O1"]}]}},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("版本与形状矛盾" in m for m in r["integrity_bad"])


_VALID_V4_INNER = {"contract": "report_contract_v4", "points": [
    {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
     "selected_fact_aliases": ["F1"],
     "review_action_code": "OBTAIN_MISSING_EVIDENCE"}]}


def _valid_audit(**over):
    # narrative_alias_map 含 R 条目——真实 run_audit 的 alias_map 由证据包构建器
    # 写入,O/R/F 三类别名齐全(投影核对靠 R 映射验报告引文归属)。
    audit = {"llm_narrative_accepted": True, "report_contract_version": 4,
             "narrative_alias_map": {"O1": "o1", "F1": "f1", "R1": "r1"},
             "accepted_payload_sha256": _sha(_VALID_V4_INNER),
             "accepted_point_count": 1}
    audit.update(over)
    return audit


def test_valid_v4_run_passes_with_bindings(tmp_path):
    b = _mk_building_with_report(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
        report_text=_mk_v4_report([("O1", "R1")]),
    )
    r = cra.check_building(b)
    assert r["passed"] is True
    assert r["bind_total"] == 2 and r["bind_ok"] == 2


def test_non_bool_accepted_flag_is_integrity_failure(tmp_path):
    """接纳旗标缺失/非布尔 → 硬伤失败,不得默认当未接纳空核假绿
    (2026-07-23 codex 审 E-5.9 钉出)。"""
    b = _mk_building(tmp_path, audit={"report_contract_version": 4})
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("非布尔" in m for m in r["integrity_bad"])
    assert r["no_accepted_narrative"] is False  # 不得混同合法回退


def test_payload_sha_mismatch_is_integrity_failure(tmp_path):
    """载荷被改动(SHA 与接纳时刻不符)→ 硬伤失败(E-5.4④ 消费端纵深校验)。"""
    tampered = json.loads(json.dumps(_VALID_V4_INNER))
    tampered["points"][0]["selected_fact_aliases"] = []  # 接纳后被改
    b = _mk_building(
        tmp_path,
        audit=_valid_audit(),  # sha 仍是原载荷的
        payload={"payload": tampered},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("sha256 不符" in m for m in r["integrity_bad"])


def test_point_count_mismatch_is_integrity_failure(tmp_path):
    b = _mk_building(
        tmp_path,
        audit=_valid_audit(accepted_point_count=5),
        payload={"payload": _VALID_V4_INNER},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("point_count 不符" in m for m in r["integrity_bad"])


def test_missing_payload_sha_in_audit_is_integrity_failure(tmp_path):
    """audit 缺 SHA → 接纳载荷无法核真伪,硬伤失败(未知不得放行)。"""
    audit = _valid_audit()
    del audit["accepted_payload_sha256"]
    b = _mk_building(tmp_path, audit=audit, payload={"payload": _VALID_V4_INNER})
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("缺 accepted_payload_sha256" in m for m in r["integrity_bad"])


def test_latest_run_is_chosen_not_earliest_triple(tmp_path):
    """选最新 run(消费者读的就是它),不回头找更早的三件套(终审四轮#2)。"""
    # 旧 run(CAR-1):三件套齐全且可通过;新 run(CAR-2):缺 audit(硬伤)。
    _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": False},
        run_name="CAR-1",
    )
    b = _mk_building(tmp_path, audit=None, run_name="CAR-2")
    r = cra.check_building(b)
    # 必须选 CAR-2(最新)并因缺 audit 判失败,而非退回 CAR-1 假绿
    assert r["passed"] is False
    assert any("run_audit" in m for m in r["integrity_bad"])


def test_main_all_vacuous_batch_exits_nonzero(tmp_path, capsys):
    """全批零绑定(哪怕每栋都是合法回退)→ 非零退出,不宣绿(终审四轮#2)。"""
    _mk_building(tmp_path, audit={"llm_narrative_accepted": False})
    rc = cra.main(["--batch-root", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr()
    assert "全批零绑定" in out.out + out.err


def test_main_all_skipped_batch_exits_nonzero(tmp_path, capsys):
    """全部栋无 closure 产物 = 零核验,非零退出(终审四轮#2)。"""
    (tmp_path / "buildings" / "B-1" / "runs").mkdir(parents=True)
    rc = cra.main(["--batch-root", str(tmp_path)])
    assert rc == 2


def test_malformed_v4_point_with_free_text_is_integrity_failure(tmp_path):
    """v4 载荷点带自由文本 text 字段 → 硬伤失败(终审六轮高#1:仅凭 contract
    标记判 v4 时,畸形载荷曾可绑定通过、掩盖自由散文重入)。"""
    b = _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": True, "report_contract_version": 4,
               "narrative_alias_map": {"O1": "o1"}},
        payload={"payload": {"contract": "report_contract_v4", "points": [
            {"obligation_alias": "O1", "text": "自由散文"}]}},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("非契约形状" in m for m in r["integrity_bad"])


def test_accepted_run_missing_audit_version_is_integrity_failure(tmp_path):
    """audit 称接纳但缺报告契约版本 → 硬伤失败(终审六轮高#1:未知版本不得放行)。"""
    b = _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": True,
               "narrative_alias_map": {"O1": "o1", "F1": "f1"}},
        payload={"payload": {"contract": "report_contract_v4", "points": [
            {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
             "selected_fact_aliases": ["F1"],
             "review_action_code": "OBTAIN_MISSING_EVIDENCE"}]}},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("版本" in m for m in r["integrity_bad"])


def test_v4_top_level_extra_field_is_integrity_failure(tmp_path):
    """v4 载荷顶层塞契约外字段(如 rule_summary 自由文本)→ 硬伤失败
    (终审七轮高#1:只查逐点时顶层自由文本可假绿)。"""
    b = _mk_building(
        tmp_path,
        audit={"llm_narrative_accepted": True, "report_contract_version": 4,
               "narrative_alias_map": {"O1": "o1", "F1": "f1"}},
        payload={"payload": {"contract": "report_contract_v4",
                             "rule_summary": "规则要求每周检查",
                             "points": [
            {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
             "selected_fact_aliases": ["F1"],
             "review_action_code": "OBTAIN_MISSING_EVIDENCE"}]}},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("顶层含契约外字段" in m for m in r["integrity_bad"])


def test_non_dict_payload_is_integrity_failure_not_crash(tmp_path):
    """载荷非对象(null/list)→ 按空载荷硬伤失败,不崩(终审七轮同类病防护)。"""
    for bad in ([], None):
        b = _mk_building(
            tmp_path / str(type(bad).__name__),
            audit={"llm_narrative_accepted": True, "report_contract_version": 4},
            payload={"payload": bad},
        )
        r = cra.check_building(b)
        assert r["passed"] is False
        assert any("载荷为空" in m for m in r["integrity_bad"])


# ---- manifest 清单锁定(codex 审阻断#3:零缺失/零多余/权威 run 锚定) ----


def _mk_manifest(tmp_path, building_ids):
    (tmp_path / "batch_manifest.json").write_text(
        json.dumps({"building_ids": building_ids}), encoding="utf-8")


def _mk_eval_report(bdir, run_id="CAR-1"):
    (Path(bdir) / "eval_report.json").write_text(
        json.dumps({"agent_run_id": run_id}), encoding="utf-8")


def test_manifest_missing_planned_building_fails_batch(tmp_path, capsys):
    """manifest 计划栋无产物目录 → 批级失败(零缺失)。"""
    b = _mk_building(tmp_path, audit=_valid_audit(), payload={"payload": _VALID_V4_INNER})
    _mk_eval_report(b)
    _mk_manifest(tmp_path, ["B-1", "B-2"])  # B-2 无目录
    rc = cra.main(["--batch-root", str(tmp_path), "--verbose"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "缺失" in out


def test_manifest_extra_directory_fails_batch(tmp_path, capsys):
    """目录不在 manifest 计划内 → 批级失败(零多余,陈旧目录不得混入)。"""
    b = _mk_building(tmp_path, audit=_valid_audit(), payload={"payload": _VALID_V4_INNER})
    _mk_eval_report(b)
    extra = tmp_path / "buildings" / "B-STALE" / "runs" / "CAR-9"
    extra.mkdir(parents=True)
    _mk_manifest(tmp_path, ["B-1"])
    rc = cra.main(["--batch-root", str(tmp_path), "--verbose"])
    assert rc == 1
    assert "多余" in capsys.readouterr().out


def test_manifest_anchors_run_by_eval_report(tmp_path):
    """有 manifest 时按顶层 eval_report.agent_run_id 锚定权威 run:指向的 run 缺
    closure → 硬伤失败,不得退回"最新 closure run"绕检。"""
    b = _mk_building(tmp_path, audit=_valid_audit(), payload={"payload": _VALID_V4_INNER})
    _mk_eval_report(b, run_id="CAR-GONE")  # 指向不存在的 run
    _mk_manifest(tmp_path, ["B-1"])
    rc = cra.main(["--batch-root", str(tmp_path)])
    assert rc == 1


def test_manifest_missing_eval_report_fails(tmp_path):
    """有 manifest 但栋顶层 eval_report 缺失 → 无法锚定权威 run,硬伤失败。"""
    _mk_building(tmp_path, audit=_valid_audit(), payload={"payload": _VALID_V4_INNER})
    _mk_manifest(tmp_path, ["B-1"])
    rc = cra.main(["--batch-root", str(tmp_path)])
    assert rc == 1


def test_manifest_valid_batch_passes(tmp_path):
    """清单+锚定齐全的正常批 → 通过。"""
    b = _mk_building_with_report(
        tmp_path, audit=_valid_audit(), payload={"payload": _VALID_V4_INNER},
        report_text=_mk_v4_report([("O1", "R1")]))
    _mk_eval_report(b)
    _mk_manifest(tmp_path, ["B-1"])
    rc = cra.main(["--batch-root", str(tmp_path)])
    assert rc == 0


# ---- 报告投影核对（codex 聚合审核阻断#2/#3 整改 2026-07-23）----


def _mk_v4_report(entries=None):
    """生成最小合法 v4 报告文本。entries = [(O别名, R别名), ...]。"""
    if entries is None:
        entries = [("O1", "R1")]
    n = len(entries)
    pairs_str = "、".join(f"[{o}/{r}]" for o, r in entries)
    lines = [
        "<!-- report contract v4 -->",
        f"### G1｜证据缺口｜{n} 项",
        f"- 义务入口：{pairs_str}",
        "- 状态 / 原因 / 动作：未闭合；缺少证据；建议人工复核。",
        "",
        "<details>",
        f"<summary>展开 {n} 项的所选证据与法规原文</summary>",
        "",
    ]
    for o, r in entries:
        lines.append(f"#### [{o}/{r}]")
        lines.append("- 现有证据：示例证据。")
        lines.append(f"- 法规依据：[{r}] 「条文」")
        lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def _mk_building_with_report(tmp_path, *, audit=None, payload=None,
                              report_text=None, run_name="CAR-1"):
    """与 _mk_building 相同但额外写入报告文件。"""
    bdir = _mk_building(tmp_path, audit=audit, payload=payload, run_name=run_name)
    if report_text is not None:
        rdir = Path(bdir) / "runs" / run_name
        (rdir / "incomplete_closure_notice.md").write_text(
            report_text, encoding="utf-8")
    return bdir


def test_projection_valid_report_passes(tmp_path):
    """正常批带正确报告文件 → 投影核对通过。"""
    b = _mk_building_with_report(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
        report_text=_mk_v4_report([("O1", "R1")]),
    )
    r = cra.check_building(b)
    assert r["passed"] is True
    assert r["integrity_bad"] == []


def test_projection_missing_o_in_report_fails(tmp_path):
    """报告漏 O（入口/明细少一项）→ 投影核对失败。"""
    # 载荷有 O1,但报告只有 O99(不在载荷中)
    report = _mk_v4_report([("O99", "R99")])
    b = _mk_building_with_report(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
        report_text=report,
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("O 集合与载荷不符" in m for m in r["integrity_bad"])


def test_projection_wrong_r_mapping_fails(tmp_path):
    """报告 R 错配（O 挂了别的义务的 R）→ 投影核对失败。"""
    # 报告用 [O1/R99] 但 amap R99→wrong_rule, 义务 O1 的 source_rule_card_id=r1
    report = _mk_v4_report([("O1", "R99")])
    audit = _valid_audit(
        narrative_alias_map={"O1": "o1", "F1": "f1", "R1": "r1", "R99": "wrong_rule"})
    b = _mk_building_with_report(
        tmp_path,
        audit=audit,
        payload={"payload": _VALID_V4_INNER},
        report_text=report,
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("R 错配" in m for m in r["integrity_bad"])


def test_projection_missing_regulation_line_fails(tmp_path):
    """明细块缺法规依据行 → 投影核对失败。"""
    # 手工构造一份缺 - 法规依据： 行的报告
    report_lines = [
        "<!-- report contract v4 -->",
        "### G1｜证据缺口｜1 项",
        "- 义务入口：[O1/R1]",
        "- 状态 / 原因 / 动作：未闭合；缺少证据；建议人工复核。",
        "",
        "<details>",
        "<summary>展开 1 项的所选证据与法规原文</summary>",
        "",
        "#### [O1/R1]",
        "- 现有证据：示例证据。",
        # 注意：故意不写 - 法规依据： 行
        "",
        "</details>",
        "",
    ]
    b = _mk_building_with_report(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
        report_text="\n".join(report_lines),
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("法规依据" in m for m in r["integrity_bad"])


def test_projection_no_report_file_fails(tmp_path):
    """权威 run 无报告文件 → 投影核对失败（不静默跳过）。"""
    b = _mk_building(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("无报告文件" in m for m in r["integrity_bad"])



def test_projection_entry_r_mismatch_fails(tmp_path):
    """入口 [O1/R99] 但明细 [O1/R1] → 入口 R 也要验,错配失败
    (codex 复审二轮:原只验明细对,入口错 R 曾可通过)。"""
    report = _mk_v4_report([("O1", "R1")]).replace(
        "- 义务入口：[O1/R1]", "- 义务入口：[O1/R99]")
    b = _mk_building_with_report(
        tmp_path,
        audit=_valid_audit(),
        payload={"payload": _VALID_V4_INNER},
        report_text=report,
    )
    r = cra.check_building(b)
    assert r["passed"] is False
    assert any("R 错配" in m for m in r["integrity_bad"])
