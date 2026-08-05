"""evo-agent baseline agent 三层控制体系单测（spec §7 + §5.2）。

覆盖：
- hooks.py 五个 hard hook 的 guard 逻辑（含 blind 红线拦截）；
- report_writer.py allow_stop 两种模板；
- run_orchestrator.py 用 mock retrieval/closure 跑完整 §5.2 流程。

retrieval / closure 子模块由其他代理并行实现，本测试一律用 stub/mock：
- retrieval stub 产 FactPack + RuleSlice；
- closure stub 产 ClosureValidationResult。
真实集成留给后续整合，不在本测试范围。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evo_agent_baseline.contracts import (
    ClosureSummary,
    ClosureValidationResult,
    ComplianceAssessmentRun,
    FactAtom,
    FactPack,
    Obligation,
    ObligationSet,
    RuleCardDTO,
    RuleFamilyDTO,
    RuleSlice,
)

from evo_agent_baseline.agent.hooks import (
    AGENT_FORBIDDEN_LABELS,
    AGENT_FORBIDDEN_PROPERTIES,
    FORBIDDEN_OUTPUT_PHRASES,
    OUTPUT_NEGATION_PREFIXES,
    OutputGuardError,
    SecurityError,
    post_retrieval_source_audit,
    post_verifier_stop_gate,
    pre_output_language_guard,
    pre_retrieval_query_guard,
    pre_run_input_guard,
)
from evo_agent_baseline.agent.report_writer import (
    build_narrative_evidence_pack,
    render_authoritative_closure_overview,
    render_auxiliary_review_report,
    render_incomplete_closure_notice,
    write_report,
)
from evo_agent_baseline.agent.run_orchestrator import RunOrchestrator


# ===========================================================================
# 一、测试夹具——构造合法的 FactPack / RuleSlice / ClosureValidationResult
# ===========================================================================

_RUN_ID = "CAR-20260523T000000-deadbeef"
_WORLD = "W-TEST-1"
_BUILDING = "B-TEST-1"


def _make_fact_pack(run_id: str = _RUN_ID) -> FactPack:
    """最小合法 FactPack——一条建筑级事实原子。"""
    fact = FactAtom(
        fact_id="F-1",
        world_id=_WORLD,
        building_id=_BUILDING,
        carrier_type="building",
        carrier_id=_BUILDING,
        target_ref=None,
        slot_id="slot.building.age",
        measure_key=None,
        value_json="42",
        value_type="number",
        unit="year",
        source_path="buildings.parquet",
        source_node_id="N-1",
    )
    return FactPack(
        run_id=run_id,
        world_id=_WORLD,
        building_id=_BUILDING,
        facts=[fact],
        slot_index={"slot.building.age": ["F-1"]},
        measure_index={},
        carrier_index={_BUILDING: ["F-1"]},
        source_tables=["buildings.parquet", "fragments.parquet"],
    )


def _make_rule_slice(run_id: str = _RUN_ID) -> RuleSlice:
    """最小合法 RuleSlice——一张卡 + 一个 family。"""
    card = RuleCardDTO(
        rule_card_id="RC-1",
        source_document_id="MBIS_CoP_2023",
        normalized_rule_text="示例规则文本。",
        family_id="mbis.inspection.drainage.ri.coverage",
    )
    family = RuleFamilyDTO(
        family_id="mbis.inspection.drainage.ri.coverage",
        family_name="排水检查覆盖",
    )
    return RuleSlice(
        run_id=run_id,
        rulecard_bundle_id="rule_card_v2",
        candidate_rule_cards=[card],
        rule_families=[family],
        semantic_slots=[],
        measures=[],
        artifacts=[],
        time_anchors=[],
        source_quotes=[],
        retrieval_policy={"cutoff": "score>0"},
    )


def _make_obligation(
    *,
    obligation_id: str,
    kind: str = "evidence",
    closure_status: str = "closed",
    satisfaction_status: str = "satisfied",
    open_reason_code: str | None = None,
    blocked_reason_code: str | None = None,
    notes: str = "",
) -> Obligation:
    """构造单条 Obligation；按 closure_status 自动配齐原因码。"""
    return Obligation(
        obligation_id=obligation_id,
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        source_rule_card_id="RC-1",
        source_family_id="mbis.inspection.drainage.ri.coverage",
        kind=kind,  # type: ignore[arg-type]
        closure_status=closure_status,  # type: ignore[arg-type]
        satisfaction_status=satisfaction_status,  # type: ignore[arg-type]
        open_reason_code=open_reason_code,  # type: ignore[arg-type]
        blocked_reason_code=blocked_reason_code,  # type: ignore[arg-type]
        notes=notes,
    )


def _make_closure_result(
    *,
    allow_stop: bool,
    obligations: list[Obligation] | None = None,
    run_id: str = _RUN_ID,
) -> ClosureValidationResult:
    """构造 ClosureValidationResult；summary / machine_report 与义务一致。"""
    obligations = obligations or [_make_obligation(obligation_id="OBL-1")]
    closed = sum(1 for o in obligations if o.closure_status == "closed")
    opened = sum(1 for o in obligations if o.closure_status == "open")
    blocked = sum(1 for o in obligations if o.closure_status == "blocked")
    satisfied = sum(1 for o in obligations if o.satisfaction_status == "satisfied")
    violated = sum(1 for o in obligations if o.satisfaction_status == "violated")
    unknown = sum(1 for o in obligations if o.satisfaction_status == "unknown")
    na = sum(1 for o in obligations if o.satisfaction_status == "not_applicable")

    stop_reason = (
        "all_applicable_obligations_closed_and_satisfied"
        if allow_stop
        else "open_obligations_remain"
    )
    summary = ClosureSummary(
        total_obligations=len(obligations),
        closed_count=closed,
        open_count=opened,
        blocked_count=blocked,
        satisfied_count=satisfied,
        violated_count=violated,
        unknown_count=unknown,
        not_applicable_count=na,
        open_reason_counts={},
        blocked_reason_counts={},
        rule_card_count=1,
        family_count=1,
        fragment_count=0,
        allow_stop=allow_stop,
        stop_reason=stop_reason,
    )
    obligation_set = ObligationSet(
        obligation_set_id="OS-1",
        run_id=run_id,
        world_id=_WORLD,
        building_id=_BUILDING,
        created_at="2026-05-23T00:00:00Z",
        rulecard_bundle_id="rule_card_v2",
        verifier_version="baseline_closure_v0.3",
        obligations=obligations,
        derivation_policy={},
    )
    machine_report = {
        "run_id": run_id,
        "world_id": _WORLD,
        "building_id": _BUILDING,
        "allow_stop": allow_stop,
        "stop_reason": stop_reason,
        "closure_summary": summary.model_dump(),
        "rule_slice_summary": {"rule_card_count": 1, "family_count": 1},
        "obligations": [o.model_dump() for o in obligations],
        "high_risk_items": [],
        "open_items": [o.model_dump() for o in obligations if o.closure_status == "open"],
        "blocked_items": [o.model_dump() for o in obligations if o.closure_status == "blocked"],
        "violated_items": [
            o.model_dump() for o in obligations if o.satisfaction_status == "violated"
        ],
        "source_guard": {"forbidden_source_check_passed": True, "forbidden_sources": []},
    }
    return ClosureValidationResult(
        run_id=run_id,
        obligation_set=obligation_set,
        closure_summary=summary,
        allow_stop=allow_stop,
        allow_report_generation=allow_stop,
        high_risk_items=[],
        machine_readable_report=machine_report,
    )


# ===========================================================================
# 二、hook 1 —— pre_run_input_guard（spec §7.3.2）
# ===========================================================================


def test_pre_run_input_guard_passes_clean_input():
    """合法输入（有 world_id/building_id、无禁止内容）通过。"""
    result = pre_run_input_guard(
        {"world_id": _WORLD, "building_id": _BUILDING, "raw_request": "请评估这栋楼"}
    )
    assert result["passed"] is True
    assert result["building_id"] == _BUILDING


def test_pre_run_input_guard_missing_building_id():
    """缺 building_id 抛 ValueError。"""
    with pytest.raises(ValueError, match="building_id"):
        pre_run_input_guard({"world_id": _WORLD})


def test_pre_run_input_guard_missing_world_id():
    """缺 world_id 抛 ValueError。"""
    with pytest.raises(ValueError):
        pre_run_input_guard({"building_id": _BUILDING})


def test_pre_run_input_guard_rejects_w2_table_path():
    """输入夹带 W2 parquet 路径——blind 红线，抛 SecurityError。"""
    with pytest.raises(SecurityError, match="forbidden_reference_truth_detected"):
        pre_run_input_guard(
            {
                "world_id": _WORLD,
                "building_id": _BUILDING,
                "raw_request": "请参考 projections.parquet 的结果",
            }
        )


def test_pre_run_input_guard_rejects_forbidden_property():
    """输入夹带 expected_verdict 属性名——blind 红线，抛 SecurityError。"""
    with pytest.raises(SecurityError):
        pre_run_input_guard(
            {
                "world_id": _WORLD,
                "building_id": _BUILDING,
                "expected_verdict": "pass",
            }
        )


def test_pre_run_input_guard_rejects_final_verdict_request():
    """输入要求“直接给最终合规裁决”——抛 SecurityError。"""
    with pytest.raises(SecurityError, match="forbidden_final_verdict_request"):
        pre_run_input_guard(
            {
                "world_id": _WORLD,
                "building_id": _BUILDING,
                "raw_request": "请直接给最终合规裁决",
            }
        )


# ===========================================================================
# 三、hook 2 —— pre_retrieval_query_guard（spec §7.3.3）
# ===========================================================================


def test_pre_retrieval_query_guard_passes_clean_cypher():
    """合法 Cypher（只碰 W0/W1/rule_card label）通过。"""
    q = "MATCH (b:Building {building_id:$bid})-[:HAS_FRAGMENT]->(f:Fragment) RETURN f"
    result = pre_retrieval_query_guard(q)
    assert result["passed"] is True


def test_pre_retrieval_query_guard_allows_rule_threshold_label():
    """`RuleThreshold` 是允许 label，不得误伤（spec §7.3.3 末注）。"""
    q = "MATCH (rc:RuleCard)-[:HAS_THRESHOLD]->(t:RuleThreshold) RETURN t"
    result = pre_retrieval_query_guard(q)
    assert result["passed"] is True


def test_pre_retrieval_query_guard_rejects_threshold_eval_label():
    """`ThresholdEval` 是禁止 label，必须拦截。"""
    with pytest.raises(SecurityError, match="forbidden_reference_truth_detected"):
        pre_retrieval_query_guard("MATCH (t:ThresholdEval) RETURN t")


def test_pre_retrieval_query_guard_rejects_normative_projection():
    """查询命中 NormativeProjection——拦截。"""
    with pytest.raises(SecurityError):
        pre_retrieval_query_guard("MATCH (n:NormativeProjection) RETURN n")


def test_pre_retrieval_query_guard_rejects_w2_parquet():
    """查询命中 projections.parquet——拦截。"""
    with pytest.raises(SecurityError):
        pre_retrieval_query_guard("LOAD CSV FROM 'projections.parquet'")


def test_pre_retrieval_query_guard_rejects_projection_input_slot_fields():
    """查询命中 required_world_core_slots 等 W2 projection input 字段——拦截。"""
    with pytest.raises(SecurityError):
        pre_retrieval_query_guard("MATCH (n) RETURN n.required_world_core_slots")


def test_pre_retrieval_query_guard_case_insensitive():
    """禁止片段大小写不敏感——expected_verdict 变体也拦。"""
    with pytest.raises(SecurityError):
        pre_retrieval_query_guard("RETURN n.Expected_Verdict")


# ===========================================================================
# 四、hook 3 —— post_retrieval_source_audit（spec §7.3.4）
# ===========================================================================


def test_post_retrieval_source_audit_passes_clean_payload():
    """干净的 FactPack/RuleSlice 通过审计。"""
    result = post_retrieval_source_audit(_make_fact_pack(), _make_rule_slice())
    assert result["passed"] is True
    assert result["forbidden_sources_loaded"] == []


def test_post_retrieval_source_audit_whitelist_world_id_fragment_id():
    """world_id / fragment_id 是 W0 合法字段，FactPack 含它们不应报违规。"""
    fp = _make_fact_pack()
    # FactAtom 本身就带 world_id；再确认 fragment carrier 不触发
    frag_fact = FactAtom(
        fact_id="F-2",
        world_id=_WORLD,
        building_id=_BUILDING,
        carrier_type="fragment",
        carrier_id="FRAG-1",
        target_ref="fragment_id::FRAG-1",
        slot_id=None,
        measure_key=None,
        value_json='"ok"',
        value_type="string",
        unit=None,
        source_path="fragments.parquet",
        source_node_id="N-2",
    )
    fp.facts.append(frag_fact)
    result = post_retrieval_source_audit(fp, _make_rule_slice())
    assert result["passed"] is True


def test_post_retrieval_source_audit_rejects_forbidden_property_in_facts():
    """FactPack 的事实里混入 expected_verdict——blind 红线，抛 SecurityError。"""
    fp = _make_fact_pack()
    # 把禁止属性名塞进 qualifiers——模拟泄漏
    fp.facts[0].qualifiers["expected_verdict"] = "pass"
    with pytest.raises(SecurityError, match="forbidden_reference_truth_detected"):
        post_retrieval_source_audit(fp, _make_rule_slice())


def test_post_retrieval_source_audit_rejects_forbidden_label_in_rule_slice():
    """RuleSlice 的 retrieval_policy 里混入禁止 label——拦截。"""
    rs = _make_rule_slice()
    rs.retrieval_policy["leaked"] = "NormativeProjection"
    with pytest.raises(SecurityError):
        post_retrieval_source_audit(_make_fact_pack(), rs)


# ===========================================================================
# 五、hook 4 —— post_verifier_stop_gate（spec §7.3.5）
# ===========================================================================


def test_post_verifier_stop_gate_allow_stop_true():
    """allow_stop=true → 模板 auxiliary_review_report，允许完整报告。"""
    result = post_verifier_stop_gate(_make_closure_result(allow_stop=True))
    assert result["allow_stop"] is True
    assert result["forced_template"] == "auxiliary_review_report"
    assert result["allow_full_report"] is True


def test_post_verifier_stop_gate_allow_stop_false():
    """allow_stop=false → 强制 incomplete_closure_notice，禁完整报告。"""
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    result = post_verifier_stop_gate(_make_closure_result(allow_stop=False, obligations=[open_ob]))
    assert result["allow_stop"] is False
    assert result["forced_template"] == "incomplete_closure_notice"
    assert result["allow_full_report"] is False


# ===========================================================================
# 六、hook 5 —— pre_output_language_guard（spec §7.3.6）
# ===========================================================================


def test_pre_output_language_guard_passes_clean_text():
    """合规话术（疑似未满足 / 建议人工复核）通过。"""
    result = pre_output_language_guard("闭包验证显示疑似未满足，建议人工复核。")
    assert result["passed"] is True


@pytest.mark.parametrize("phrase", FORBIDDEN_OUTPUT_PHRASES)
def test_pre_output_language_guard_rejects_each_forbidden_phrase(phrase):
    """每个禁止话术单独验证——出现即抛 OutputGuardError。"""
    with pytest.raises(OutputGuardError, match="output_blocked_forbidden_phrase"):
        pre_output_language_guard(f"结论：{phrase}。")


@pytest.mark.parametrize(
    "text",
    ["审查结论：最终**裁决**通过。", "审查结论：最终_合规。", "审查结论：最终`不合规`。"],
)
def test_pre_output_language_guard_rejects_markdown_split_phrases(text):
    with pytest.raises(OutputGuardError, match="output_blocked_forbidden_phrase"):
        pre_output_language_guard(text)


def test_pre_output_language_guard_rejects_final_verdict_in_paragraph():
    """禁止话术嵌在长段落中也要拦。"""
    text = "经过分析，本报告认为本建筑已合规，可以结案。"
    with pytest.raises(OutputGuardError):
        pre_output_language_guard(text)


# spec §7.3.6 [v0.4-D-1] 否定前缀白名单 → 实际用例样本（直接紧贴禁话术的真实文案）。
# 每条样本必须真正命中 FORBIDDEN_OUTPUT_PHRASES 中的子串，且该子串前紧贴的非空白
# 前缀正是白名单条目。新增前缀需同时：1) spec §7.3.6 加 2) 实际紧贴文案 3) 加入下表。
_NEGATION_PREFIX_SAMPLES = {
    "非": "本报告为人工审查辅助材料，非最终裁决。",
    "不是": "你不是最终裁决者。",
    "不构成": "本报告不构成最终合规裁决。",
    "不输出": "你不输出最终合规裁决。",
}


def test_output_negation_prefixes_match_sample_table():
    """code 的否定前缀白名单与样本表一一对齐；防止再次预防性扩展。"""
    assert set(OUTPUT_NEGATION_PREFIXES) == set(_NEGATION_PREFIX_SAMPLES.keys())


@pytest.mark.parametrize(
    "prefix,sample", list(_NEGATION_PREFIX_SAMPLES.items()), ids=list(_NEGATION_PREFIX_SAMPLES)
)
def test_pre_output_language_guard_allows_each_negation_prefix(prefix, sample):
    """每个否定前缀的真实文案都必须通过 guard（spec §7.3.6 [v0.4-D-1]）。"""
    assert prefix in sample, "样本必须真正含该前缀"
    result = pre_output_language_guard(sample)
    assert result["passed"] is True, f"否定前缀 {prefix!r} 的样本 {sample!r} 被误拦"


# ===========================================================================
# 七、禁止常量集合自检（spec 附录 A）
# ===========================================================================


def test_forbidden_labels_include_w2_and_eval():
    """禁止 label 集合必须含 W2 与 evaluator 关键 label。"""
    for lbl in ("NormativeProjection", "ThresholdEval", "ExpectedVerdict", "QueryEpisode"):
        assert lbl in AGENT_FORBIDDEN_LABELS
    # RuleThreshold 是允许 label，不得在禁止集合
    assert "RuleThreshold" not in AGENT_FORBIDDEN_LABELS


def test_forbidden_properties_include_projection_fields():
    """禁止属性集合必须含 expected_verdict / projection_id 等。"""
    for prop in ("expected_verdict", "projection_id", "coverage_status", "basis_items"):
        assert prop in AGENT_FORBIDDEN_PROPERTIES


def test_narrative_copyable_handle_uses_only_pack_aliases_without_judgment_words():
    """v3 模型载荷只给裸别名数组，不再暴露 Markdown copyable_handle。"""
    obligation = _make_obligation(
        obligation_id="OBL-OPEN-HANDLE",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    ).model_copy(
        update={
            "slot_ids": ["slot.building.age"],
            "evidence_fact_ids": ["F-1"],
        }
    )
    pack = build_narrative_evidence_pack(
        _make_closure_result(allow_stop=False, obligations=[obligation]),
        _make_rule_slice(),
        _make_fact_pack(),
    )

    payload = pack.to_model_payload()
    item = payload["key_items"][0]
    assert item["evidence_aliases"] == ["O1", "R1", "F1"]
    assert "copyable_handle" not in item
    assert set(item["evidence_aliases"]) <= set(pack.alias_map)
    assert all(real_id not in str(item) for real_id in pack.alias_map.values())


# ===========================================================================
# 八、report_writer —— incomplete_closure_notice（spec §7.4.2）
# ===========================================================================


def test_authoritative_closure_overview_uses_verifier_counts():
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN-AUTH",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    result = _make_closure_result(allow_stop=False, obligations=[open_ob])
    result.closure_summary.open_reason_counts = {"z_reason": 2, "a_reason": 2}
    text = render_authoritative_closure_overview(
        result,
        allow_stop=False,
        world_id=_WORLD,
        building_id=_BUILDING,
        generated_at="2026-07-11T00:00:00Z",
    )
    assert text.startswith("# MBIS 闭包未完成说明（非最终裁决）")
    assert "本节由系统确定性生成" in text
    assert "- total: 1" in text
    assert "- open: 1" in text
    assert "- blocked: 0" in text
    assert "- allow_stop: False" in text
    assert "a_reason=2、z_reason=2" in text
    assert f"- building_id: {_BUILDING}" in text
    assert f"- world_id: {_WORLD}" in text
    assert f"- run_id: {_RUN_ID}" in text
    assert "- 运行时间戳: 2026-07-11T00:00:00Z" in text


def test_verdict_counts_split_mirror_consistency_copies():
    """DEBT-083 丁护栏②消费端：satisfied 计数分「原生 + 镜像一致性副本」两账。

    镜像副本（notes 带 `consistency_mirror_of=`）与来源触发器同判、不构成独立
    法规判断——报告不分账会让消费者把同一触发器判定重复计数（批 I 实测
    `reporting.artifact.prepared` 一槽 512 条镜像）。无镜像时行格式逐字节不变。
    """
    native = _make_obligation(
        obligation_id="OBL-NATIVE-SAT",
        closure_status="closed",
        satisfaction_status="satisfied",
    )
    mirror = _make_obligation(
        obligation_id="OBL-MIRROR-SAT",
        closure_status="closed",
        satisfaction_status="satisfied",
        notes="satisfaction_binding=slot_ref:sr02; "
              "consistency_mirror_of=trigger_slot_ref:sr02",
    )
    result = _make_closure_result(
        allow_stop=False, obligations=[native, mirror])
    result.closure_summary.satisfied_count = 2
    text = render_authoritative_closure_overview(
        result, allow_stop=False, world_id=_WORLD,
        building_id=_BUILDING, generated_at="2026-08-02T00:00:00Z",
    )
    assert ("- satisfied: 2（原生 1 ＋ 镜像一致性副本 1；"
            "镜像与来源触发器同判，不构成独立法规判断）") in text
    # violated 无镜像 ⇒ 行保持旧格式（逐字节）。
    assert f"- violated: {result.closure_summary.violated_count}\n" in text + "\n"

    # 无镜像输入 ⇒ satisfied 行也保持旧格式。
    plain = _make_closure_result(allow_stop=False, obligations=[native])
    plain.closure_summary.satisfied_count = 1
    plain_text = render_authoritative_closure_overview(
        plain, allow_stop=False, world_id=_WORLD,
        building_id=_BUILDING, generated_at="2026-08-02T00:00:00Z",
    )
    assert "- satisfied: 1\n" in plain_text + "\n"
    assert "镜像一致性副本" not in plain_text


def test_authoritative_closure_overview_allow_stop_true_uses_auxiliary_title():
    result = _make_closure_result(allow_stop=True)
    text = render_authoritative_closure_overview(
        result,
        allow_stop=True,
        world_id=_WORLD,
        building_id=_BUILDING,
        generated_at="2026-07-11T00:00:00Z",
    )
    assert text.startswith("# MBIS 辅助审查报告（非最终裁决）")
    assert "闭包未完成说明" not in text


def test_incomplete_closure_notice_lists_open_and_blocked():
    """allow_stop=false 时说明列出 open / blocked 项与补充建议。"""
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN",
        kind="evidence",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
        notes="排水检查记录缺失",
    )
    blocked_ob = _make_obligation(
        obligation_id="OBL-BLK",
        kind="threshold",
        closure_status="blocked",
        satisfaction_status="unknown",
        blocked_reason_code="unsupported_formula",
        notes="公式不在白名单",
    )
    result = _make_closure_result(allow_stop=False, obligations=[open_ob, blocked_ob])
    text = render_incomplete_closure_notice(result)
    assert "闭包未完成说明" in text
    assert "本次资料闭包验证未通过" in text
    assert "OBL-OPEN" in text
    assert "OBL-BLK" in text
    assert "missing_fact" in text
    assert "unsupported_formula" in text
    assert "排水检查记录缺失" not in text
    assert "公式不在白名单" not in text
    assert "本次结果未带归因映射" in text
    # 不得出现完整报告的第 3-9 节标题
    assert "## 5. 逐项义务闭包表" not in text
    assert "## 7. 证据链与来源" not in text


def test_incomplete_closure_notice_no_forbidden_phrase():
    """未完成说明不得含禁止话术——可直接过 pre_output_language_guard。"""
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    text = render_incomplete_closure_notice(
        _make_closure_result(allow_stop=False, obligations=[open_ob])
    )
    # 不抛异常即合规
    assert pre_output_language_guard(text)["passed"] is True


# ===========================================================================
# 九、report_writer —— auxiliary_review_report（spec §7.4.1 / 附录 C）
# ===========================================================================


def test_auxiliary_review_report_has_all_sections():
    """allow_stop=true 报告含 spec §7.2.4 固定结构全部 9 节。"""
    result = _make_closure_result(allow_stop=True)
    text = render_auxiliary_review_report(
        result,
        kg_snapshot_id="KGS-1",
        rulecard_bundle_id="rule_card_v2",
        fact_source_tables=["buildings.parquet"],
    )
    for heading in (
        "## 1. 报告声明",
        "## 2. 建筑与资料范围",
        "## 3. 适用法规 / rule card 切片",
        "## 4. 闭包验证摘要",
        "## 5. 逐项义务闭包表",
        "## 6. 疑似未满足 / 风险项",
        "## 7. 证据链与来源",
        "## 8. 建议人工复核点",
        "## 9. 限制与未覆盖范围",
    ):
        assert heading in text, f"缺章节：{heading}"
    assert "非最终裁决" in text
    assert _RUN_ID in text


def test_auxiliary_review_report_shows_violated_item():
    """violated 义务进入第 6 节疑似未满足表，用‘建议人工复核’话术。"""
    violated_ob = Obligation(
        obligation_id="OBL-VIO",
        run_id=_RUN_ID,
        world_id=_WORLD,
        building_id=_BUILDING,
        source_rule_card_id="RC-1",
        source_family_id="mbis.inspection.drainage.ri.coverage",
        kind="threshold",
        closure_status="closed",
        satisfaction_status="violated",
        observed_value_json="3",
        threshold_value_json="5",
        notes="测量值低于阈值",
    )
    result = _make_closure_result(allow_stop=True, obligations=[violated_ob])
    text = render_auxiliary_review_report(result)
    assert "OBL-VIO" in text
    assert "测量值低于阈值" in text
    assert "建议人工复核" in text
    # 报告整体不含禁止话术
    assert pre_output_language_guard(text)["passed"] is True


def test_auxiliary_review_report_confirms_zero_open_blocked():
    """open/blocked 为 0 时报告第 4 节给出确认（spec §7.4.1 要求 6）。"""
    text = render_auxiliary_review_report(_make_closure_result(allow_stop=True))
    assert "open obligations = 0" in text
    assert "blocked obligations = 0" in text


# ===========================================================================
# 十、report_writer —— write_report 统一入口（spec §7.3.5 / §7.4）
# ===========================================================================


def test_write_report_picks_auxiliary_when_allow_stop_true():
    """allow_stop=true → 文件名 auxiliary_review_report.md。"""
    out = write_report(_make_closure_result(allow_stop=True))
    assert out["filename"] == "auxiliary_review_report.md"
    assert "辅助审查报告" in out["content"]


def test_write_report_picks_notice_when_allow_stop_false():
    """allow_stop=false → 文件名 incomplete_closure_notice.md。"""
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    out = write_report(_make_closure_result(allow_stop=False, obligations=[open_ob]))
    assert out["filename"] == "incomplete_closure_notice.md"
    assert "闭包未完成说明" in out["content"]


# ===========================================================================
# 十一、run_orchestrator —— 用 mock retrieval/closure 跑完整 §5.2 流程
# ===========================================================================


def _stub_retrieval(world_id, building_id, run_id):
    """retrieval stub——产 (FactPack, RuleSlice)，run_id 对齐。"""
    return _make_fact_pack(run_id=run_id), _make_rule_slice(run_id=run_id)


def _make_closure_stub(allow_stop: bool, obligations=None):
    """生成一个 closure stub callable，签名对齐 validate_building_closure。"""

    def _stub(rule_slice, fact_pack, config):
        return _make_closure_result(
            allow_stop=allow_stop,
            obligations=obligations,
            run_id=fact_pack.run_id,
        )

    return _stub


def test_orchestrator_happy_path_allow_stop_true(tmp_path):
    """完整流程 allow_stop=true：status=report_ready，落盘 7 个 artifact。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
        kg_snapshot_id="KGS-1",
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)

    assert isinstance(run, ComplianceAssessmentRun)
    assert run.status == "report_ready"
    assert run.allow_stop is True
    assert run.report_ref.endswith("auxiliary_review_report.md")
    assert run.closure_result_ref.endswith("closure_validation_result.json")

    run_dir = tmp_path / run.run_id
    for fname in (
        "fact_pack.json",
        "rule_slice.json",
        "obligation_set.json",
        "closure_validation_result.json",
        "run.json",
        "run_audit.json",
        "auxiliary_review_report.md",
    ):
        assert (run_dir / fname).exists(), f"缺 artifact：{fname}"

    # run_audit 中 forbidden_sources_loaded 必须为空（spec IT-002）
    audit = json.loads((run_dir / "run_audit.json").read_text(encoding="utf-8"))
    assert audit["forbidden_sources_loaded"] == []
    assert audit["status_trace"][-1] == "report_ready"


def _make_closure_stub_v5(allow_stop: bool, obligations=None):
    """v5 身份 closure stub：ObligationSet 携 v5 版本字段 + 1:1 manifest，machine_report 带 8 字段 run_audit。

    用于验证编排器 §7 原子版本传播（把 closure 的 8 身份字段透传进落盘 run_audit.json +
    会话载体抄录 obligation_identity_schema）。
    """

    def _stub(rule_slice, fact_pack, config):
        obls = obligations or [_make_obligation(obligation_id="OBL-1")]
        base = _make_closure_result(
            allow_stop=allow_stop, obligations=obls, run_id=fact_pack.run_id
        )
        v5_os = base.obligation_set.model_copy(update={
            "obligation_set_schema": "obligation_set_v2",
            "obligation_identity_schema": "obligation_identity_v5",
            "canonical_profile_id": "mbis_canonical_v2",
            "identity_key_policy": "canonical_identity_hash",
            "identity_manifest": [{"obligation_id": o.obligation_id} for o in obls],
        })
        mrr = dict(base.machine_readable_report)
        mrr["run_audit"] = {
            "obligation_set_schema": "obligation_set_v2",
            "obligation_identity_schema": "obligation_identity_v5",
            "canonical_profile_id": "mbis_canonical_v2",
            "identity_catalog_sha256": "a" * 64,
            "identity_key_policy": "canonical_identity_hash",
            "identity_binding_unbound_count": 0,
            "identity_collision_postcheck_passed": True,
            "legacy_v1_key_used": False,
        }
        return base.model_copy(
            update={"obligation_set": v5_os, "machine_readable_report": mrr}
        )

    return _stub


def test_orchestrator_persists_identity_run_audit_and_schema(tmp_path):
    """§7 原子版本传播：run_audit.json 含 8 身份字段 + run.json 携 obligation_identity_schema=v5。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub_v5(allow_stop=True),
        runs_root=str(tmp_path),
        kg_snapshot_id="KGS-1",
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    assert run.obligation_identity_schema == "obligation_identity_v5"

    run_dir = tmp_path / run.run_id
    audit = json.loads((run_dir / "run_audit.json").read_text(encoding="utf-8"))
    ira = audit["identity_run_audit"]
    for k in (
        "obligation_set_schema",
        "obligation_identity_schema",
        "canonical_profile_id",
        "identity_catalog_sha256",
        "identity_key_policy",
        "identity_binding_unbound_count",
        "identity_collision_postcheck_passed",
        "legacy_v1_key_used",
    ):
        assert k in ira, f"run_audit.json 缺身份字段 {k}"
    assert ira["obligation_identity_schema"] == "obligation_identity_v5"
    # run.json 落盘同样携身份 schema（replay/eval 分区锚）。
    run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["obligation_identity_schema"] == "obligation_identity_v5"


def test_orchestrator_v1_stub_leaves_identity_schema_none(tmp_path):
    """v1 桩（closure 结果无 run_audit / 身份字段）→ run.obligation_identity_schema=None（v1 只读，不谎标）。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
        kg_snapshot_id="KGS-1",
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    assert run.obligation_identity_schema is None
    run_dir = tmp_path / run.run_id
    audit = json.loads((run_dir / "run_audit.json").read_text(encoding="utf-8"))
    assert "identity_run_audit" not in audit  # 桩无 run_audit 块 → 不写伪身份


def test_closure_fn_expects_catalog_signature_detection():
    """§5.2：只认 keyword-only 必填 identity_blueprint_catalog；三位置参桩（含同名）判桩透传。"""
    from evo_agent_baseline.agent.run_orchestrator import (
        _closure_fn_expects_catalog,
        _wrap_closure_fn_with_catalog,
    )
    from evo_agent_baseline.closure.validator import validate_building_closure

    # 真 validate_building_closure：keyword-only 必填 → True。
    assert _closure_fn_expects_catalog(validate_building_closure) is True

    # 普通三位置参桩 → False（透传）。
    def stub3(rule_slice, fact_pack, config):
        return None

    assert _closure_fn_expects_catalog(stub3) is False

    # codex 点名：三**位置**参 callable 名叫 identity_blueprint_catalog（非 kw-only）→ 判桩。
    def stub_named(rule_slice, fact_pack, identity_blueprint_catalog):
        return "named"

    assert _closure_fn_expects_catalog(stub_named) is False
    wrapped = _wrap_closure_fn_with_catalog(stub_named)
    assert wrapped is stub_named  # 原样透传，不注入 catalog
    assert wrapped("rs", "fp", "cfg") == "named"  # 可调用不 TypeError

    # kw-only 但可选（有默认）→ 不认（要求无默认）。
    def stub_kw_opt(rule_slice, fact_pack, config=None, *, identity_blueprint_catalog=None):
        return None

    assert _closure_fn_expects_catalog(stub_kw_opt) is False


def test_orchestrator_allow_stop_false_emits_notice(tmp_path):
    """allow_stop=false：出 incomplete_closure_notice，不出完整报告。"""
    open_ob = _make_obligation(
        obligation_id="OBL-OPEN",
        closure_status="open",
        satisfaction_status="unknown",
        open_reason_code="missing_fact",
    )
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=False, obligations=[open_ob]),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)

    assert run.status == "report_ready"
    assert run.allow_stop is False
    assert run.report_ref.endswith("incomplete_closure_notice.md")
    run_dir = tmp_path / run.run_id
    assert (run_dir / "incomplete_closure_notice.md").exists()
    assert not (run_dir / "auxiliary_review_report.md").exists()


def test_orchestrator_input_guard_blocks_missing_world_id(tmp_path):
    """缺 world_id：pre_run_input_guard 拦截，status=failed。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id="", building_id=_BUILDING)
    assert run.status == "failed"
    assert run.input_guard_result["passed"] is False


def test_orchestrator_input_guard_blocks_forbidden_reference(tmp_path):
    """输入夹带 W2 参考真值：status=blocked，notes 记 forbidden 原因。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(
        world_id=_WORLD,
        building_id=_BUILDING,
        run_input={"raw_request": "对照 expected_verdict 给结论"},
    )
    assert run.status == "blocked"


def test_orchestrator_blocks_when_retrieval_leaks_forbidden_field(tmp_path):
    """检索结果泄漏 W2 字段：post_retrieval_source_audit 拦截，run blocked。"""

    def _leaky_retrieval(world_id, building_id, run_id):
        fp = _make_fact_pack(run_id=run_id)
        fp.facts[0].qualifiers["expected_verdict"] = "pass"
        return fp, _make_rule_slice(run_id=run_id)

    orch = RunOrchestrator(
        retrieval_fn=_leaky_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    assert run.status == "blocked"
    assert any("forbidden_reference_truth_detected" in n for n in run.notes)


def test_orchestrator_run_id_format(tmp_path):
    """run_id 形如 CAR-<timestamp>-<hash>（spec §5.1.1）。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    assert run.run_id.startswith("CAR-")
    assert len(run.run_id.split("-")) >= 3


def test_orchestrator_rejects_bad_retrieval_return(tmp_path):
    """retrieval 返回类型不对：编排器兜底为 status=failed。"""

    def _bad_retrieval(world_id, building_id, run_id):
        return {"not": "a FactPack"}, _make_rule_slice(run_id=run_id)

    orch = RunOrchestrator(
        retrieval_fn=_bad_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    assert run.status == "failed"


def test_orchestrator_persist_false_skips_disk(tmp_path):
    """persist=False 时不落盘 artifact 目录。"""
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path),
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING, persist=False)
    assert run.status == "report_ready"
    assert not (tmp_path / run.run_id).exists()


@pytest.fixture
def tmp_path(request):
    """受限 Windows 沙箱下使用 workspace 内的测试目录。"""
    path = Path.cwd() / "杂物箱" / "pytest_v3_paths" / request.node.name
    path.mkdir(parents=True, exist_ok=True)
    return path


# ===========================================================================
# 十二、DEBT-083 哨兵边界开关转正常开启（工单①，2026-08-02）
# ===========================================================================


def test_resolve_fallback_boundary_enabled_parsing(monkeypatch):
    """未设/空→True（四门已过、正常开启是新常态）；"1"→True；"0"→False；
    其它取值→ValueError fail-closed（防拼写静默退化）。"""
    from evo_agent_baseline.agent.run_orchestrator import (
        resolve_fallback_boundary_enabled,
    )

    monkeypatch.delenv("EVO_FALLBACK_BOUNDARY", raising=False)
    assert resolve_fallback_boundary_enabled() is True
    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "")
    assert resolve_fallback_boundary_enabled() is True
    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "1")
    assert resolve_fallback_boundary_enabled() is True
    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "0")
    assert resolve_fallback_boundary_enabled() is False
    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "yes")
    with pytest.raises(ValueError):
        resolve_fallback_boundary_enabled()


def test_closure_fn_accepts_fallback_boundary_detection():
    """只对签名里有 exclude_fallback_reasons_facts 的真验证器传参；三位置参桩不受影响。"""
    from evo_agent_baseline.agent.run_orchestrator import (
        _closure_fn_accepts_fallback_boundary,
    )
    from evo_agent_baseline.closure.validator import validate_building_closure

    assert _closure_fn_accepts_fallback_boundary(validate_building_closure) is True

    def stub3(rule_slice, fact_pack, config):
        return None

    assert _closure_fn_accepts_fallback_boundary(stub3) is False


def test_orchestrator_run_audit_records_fallback_boundary_enabled(
        tmp_path, monkeypatch):
    """run_audit.json 顶层必须记开关实际值（codex 终审硬条件②：记实际值不吃缺省）。"""
    monkeypatch.delenv("EVO_FALLBACK_BOUNDARY", raising=False)
    orch = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path / "on"),
        kg_snapshot_id="KGS-1",
    )
    run = orch.run(world_id=_WORLD, building_id=_BUILDING)
    audit = json.loads(
        (tmp_path / "on" / run.run_id / "run_audit.json").read_text(encoding="utf-8"))
    assert audit["fallback_boundary_enabled"] is True

    monkeypatch.setenv("EVO_FALLBACK_BOUNDARY", "0")
    orch_off = RunOrchestrator(
        retrieval_fn=_stub_retrieval,
        closure_fn=_make_closure_stub(allow_stop=True),
        runs_root=str(tmp_path / "off"),
        kg_snapshot_id="KGS-1",
    )
    run_off = orch_off.run(world_id=_WORLD, building_id=_BUILDING)
    audit_off = json.loads(
        (tmp_path / "off" / run_off.run_id / "run_audit.json")
        .read_text(encoding="utf-8"))
    assert audit_off["fallback_boundary_enabled"] is False
