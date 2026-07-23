"""报告契约 v4 测试（spec §7.4.5 / E-5，Gate C 严格 0 严重错释）。

核心断言:模型无法经任何字段注入规则语义;规则/状态/原因/证据/条文全由程序权威组装。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

from evo_agent_baseline.agent.report_contract_v4 import (
    ANALYSIS_CODES,
    REASON_CODE_SPEC,
    REVIEW_ACTION_CODES,
    REVIEW_ACTION_ZH,
    render_v4_points,
    validate_submission_payload_v4,
)


# 最小 pack 桩:只需 key_items/rule_cards/facts 三个属性。
@dataclass
class _Pack:
    key_items: List[Dict[str, Any]] = field(default_factory=list)
    rule_cards: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[Dict[str, Any]] = field(default_factory=list)


def _pack():
    return _Pack(
        key_items=[
            {"alias": "O1", "obligation_id": "a" * 24, "category": "open",
             "closure_status": "open", "satisfaction_status": "unknown",
             "reason_code": "missing_artifact_evidence", "rule_card_alias": "R1",
             "fact_aliases": ["F1"]},
            {"alias": "O2", "obligation_id": "b" * 24, "category": "blocked",
             "closure_status": "blocked", "satisfaction_status": "unknown",
             "reason_code": "qualifier_conflict", "rule_card_alias": "R2",
             "fact_aliases": []},
        ],
        rule_cards=[
            {"alias": "R1", "rule_card_id": "rc.mbis.x.c01", "quote": "The RI shall obtain material evidence."},
            {"alias": "R2", "rule_card_id": "rc.mbis.y.c01", "quote": "The scope covers building envelope."},
        ],
        facts=[
            {"alias": "F1", "fact_id": "f" * 24, "slot_id": "artifact.record", "value": "false", "unit": None},
        ],
    )


def _valid_payload():
    return {
        "contract": "report_contract_v4",
        "points": [
            {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
             "selected_fact_aliases": ["F1"], "review_action_code": "OBTAIN_MISSING_EVIDENCE"},
            {"obligation_alias": "O2", "analysis_code": "AMBIGUITY_REVIEW",
             "selected_fact_aliases": [], "review_action_code": "DISAMBIGUATE_BINDING"},
        ],
    }


def test_valid_v4_payload_accepted():
    norm, errs = validate_submission_payload_v4(_valid_payload(), _pack().key_items)
    assert errs == []
    assert norm is not None and len(norm) == 2
    assert norm[0]["obligation_alias"] == "O1"


def test_free_text_field_is_rejected():
    """核心安全属性:任何自由文本字段整篇拒绝——错释义无处可藏。"""
    for bad_field in ("text", "gap_description", "rule_summary", "rule_alias",
                      "reason_code", "status", "observed_value", "threshold", "note"):
        p = _valid_payload()
        p["points"][0][bad_field] = "规则要求每周至少检查一次"  # 试图注入规则语义
        norm, errs = validate_submission_payload_v4(p, _pack().key_items)
        assert norm is None, f"{bad_field} 应致整篇拒绝"
        assert any(e["error_code"] == "additional_properties" for e in errs), bad_field


def test_unknown_obligation_alias_rejected():
    p = _valid_payload()
    p["points"][0]["obligation_alias"] = "O99"
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "unknown_obligation_alias" for e in errs)


def test_fact_not_in_obligation_rejected():
    """模型不能给义务挂不属于它的证据(防跨义务错绑)。"""
    p = _valid_payload()
    p["points"][0]["selected_fact_aliases"] = ["F1", "F9"]  # F9 不在 O1.fact_aliases
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "fact_not_in_obligation" for e in errs)


def test_analysis_code_must_match_authoritative_reason():
    """analysis_code 不能与权威 reason_code 冲突(防经 analysis_code 重定义状态)。"""
    p = _valid_payload()
    p["points"][0]["analysis_code"] = "MODELING_GAP"  # O1 reason=missing_artifact_evidence 应为 EVIDENCE_GAP
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "analysis_reason_incompatible" for e in errs)


def test_action_incompatible_with_reason_rejected():
    p = _valid_payload()
    p["points"][0]["review_action_code"] = "RECONCILE_UNIT"  # 与 missing_artifact_evidence 不兼容
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "action_reason_incompatible" for e in errs)


def test_duplicate_obligation_rejected():
    p = _valid_payload()
    p["points"].append(dict(p["points"][0]))  # O1 重复
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "duplicate_obligation" for e in errs)


def test_wrong_contract_version_rejected():
    p = _valid_payload()
    p["contract"] = "report_contract_v3"
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "wrong_contract" for e in errs)


def test_renderer_produces_authoritative_four_layers():
    """渲染器四层全来自权威对象:状态/原因/证据/动作/法规依据。"""
    norm, errs = validate_submission_payload_v4(_valid_payload(), _pack().key_items)
    assert errs == []
    lines = render_v4_points(_pack(), norm)
    assert lines is not None
    text = "\n".join(lines)
    # 权威条文逐字出现(法规依据层)
    assert "The RI shall obtain material evidence." in text
    # reason 中文模板(只解释为何 open,不含规则释义)
    assert "尚未取得用于核验该义务的材料/文件证据" in text
    # 证据值取自 FactPack 权威
    assert "artifact.record" in text and "value=false" in text
    # 动作措辞只建议复核/补证
    assert "重新运行核验" in text


def test_renderer_fails_closed_when_quote_missing():
    """缺权威条文 → 整篇 fallback(返回 None),不半渲染。"""
    pk = _pack()
    pk.rule_cards[0]["quote"] = ""  # R1 无引文
    norm, _ = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    assert render_v4_points(pk, norm) is None


def test_reason_templates_do_not_leak_rule_requirements():
    """E-5.5 红线:reason 模板只解释为何 open/blocked,不得声称"规则要求 X"。"""
    for code, spec in REASON_CODE_SPEC.items():
        zh = spec["zh"]
        assert "规则要求" not in zh, f"{code} 模板偷渡了规则释义:{zh}"
        assert spec["analysis"] in ANALYSIS_CODES
        assert all(a in REVIEW_ACTION_CODES for a in spec["actions"])


# ---- copilot 审核门整改回归（2026-07-23）----

def test_top_level_extra_field_rejected():
    """顶层额外字段（如 rule_summary）整篇拒绝（copilot 审#4）。"""
    p = _valid_payload()
    p["rule_summary"] = "规则要求每周检查"
    norm, errs = validate_submission_payload_v4(p, _pack().key_items)
    assert norm is None
    assert any(e["error_code"] == "top_additional_properties" for e in errs)


def test_non_string_fields_rejected_cleanly_not_crash():
    """字段类型非法（analysis_code=[] 等）干净拒绝，不抛 TypeError（copilot 审#4）。"""
    for bad in ({"analysis_code": []}, {"review_action_code": []},
                {"obligation_alias": 3}, {"selected_fact_aliases": [["x"]]}):
        p = _valid_payload()
        p["points"][0].update(bad)
        norm, errs = validate_submission_payload_v4(p, _pack().key_items)  # 不得抛异常
        assert norm is None
        assert any(e["error_code"] == "field_type" for e in errs)


def test_placeholder_quote_fails_closed():
    """占位引文'（未取得引文）'不算权威 → 整篇 fallback（copilot 审#2）。"""
    pk = _pack()
    pk.rule_cards[0]["quote"] = "（未取得引文）"
    norm, _ = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    assert render_v4_points(pk, norm) is None


def test_unresolved_fact_omitted_not_shown_as_none(monkeypatch=None):
    """未解析事实（slot/value 皆 None）从证据行**略去**（不显 value=None），
    但不毁整篇报告（copilot 审#2 分级处置：缺值事实略去、占位 quote 才 fail-closed）。"""
    pk = _pack()
    pk.facts[0] = {"alias": "F1", "fact_id": "f" * 24, "slot_id": None,
                   "value": None, "unit": None}
    norm, _ = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    lines = render_v4_points(pk, norm)
    assert lines is not None  # 不 fallback
    text = "\n".join(lines)
    assert "value=None" not in text  # 未解析事实不显示 None
    assert "本义务暂无可列证据" in text  # 该点证据全略后显无证据


def test_obtain_missing_evidence_action_wording_is_generic():
    """OBTAIN_MISSING_EVIDENCE 可被 missing_fact（普通触发 slot）/
    null_observed_value（数值）等通用原因码选用，动作措辞必须通用——
    窄化为"材料/文件"会把普通字段/数值缺失错描成材料/文件缺失
    （copilot 终审四轮审出）。具体缺什么由原因行（reason_code 模板）说明。"""
    zh = REVIEW_ACTION_ZH["OBTAIN_MISSING_EVIDENCE"]
    assert "材料" not in zh
    assert "文件" not in zh
    assert "证据" in zh  # 仍是取证动作


# ---- 聚合展示形态(2026-07-23 codex 聚合设计定稿) ----


def test_same_signature_points_merge_into_one_group():
    """同(状态,分析码,原因,动作)四元组的点聚成一组:共享句一次,成员并集保全。"""
    pk = _pack()
    pk.key_items.append(
        {"alias": "O3", "obligation_id": "c" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_artifact_evidence", "rule_card_alias": "R2",
         "fact_aliases": []})
    p = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
         "selected_fact_aliases": ["F1"], "review_action_code": "OBTAIN_MISSING_EVIDENCE"},
        {"obligation_alias": "O3", "analysis_code": "EVIDENCE_GAP",
         "selected_fact_aliases": [], "review_action_code": "OBTAIN_MISSING_EVIDENCE"},
    ]}
    norm, errs = validate_submission_payload_v4(p, pk.key_items)
    assert errs == []
    lines = render_v4_points(pk, norm)
    text = "\n".join(lines)
    assert text.count("### G") == 1  # 一组
    assert "2 项" in text
    assert "[O1/R1]" in text and "[O3/R2]" in text  # 成员并集保全
    # 共享原因句只出现一次(主视图);逐义务引文仍各自紧邻(防"共享法规要求"误导)
    assert text.count("尚未取得用于核验该义务的材料/文件证据") == 1
    assert text.count("The RI shall obtain material evidence.") == 1
    assert text.count("The scope covers building envelope.") == 1


def test_different_signature_points_stay_separate_groups():
    """不同签名不合并(O1 open/EVIDENCE_GAP vs O2 blocked/AMBIGUITY_REVIEW)。"""
    norm, errs = validate_submission_payload_v4(_valid_payload(), _pack().key_items)
    assert errs == []
    lines = render_v4_points(_pack(), norm)
    text = "\n".join(lines)
    assert text.count("### G") == 2


def test_group_split_at_eight_members():
    """单组成员 >8 按同签名确定性分片,不跨签名合并。"""
    pk = _pack()
    pk.key_items = [
        {"alias": f"O{i}", "obligation_id": chr(97 + i) * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_fact", "rule_card_alias": "R1", "fact_aliases": []}
        for i in range(1, 11)  # 10 个同签名义务
    ]
    p = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": f"O{i}", "analysis_code": "EVIDENCE_GAP",
         "selected_fact_aliases": [], "review_action_code": "OBTAIN_MISSING_EVIDENCE"}
        for i in range(1, 11)
    ]}
    norm, errs = validate_submission_payload_v4(p, pk.key_items)
    assert errs == []
    text = "\n".join(render_v4_points(pk, norm))
    assert text.count("### G") == 2  # 8+2 分片
    assert "8 项" in text and "2 项" in text


def test_status_reason_incompatible_rejected():
    """E-5.3 status↔reason 兼容矩阵:open 义务挂 blocked 原因码 → 整篇拒绝
    (codex 聚合设计商议补缺:此前从未验 category↔reason)。"""
    pk = _pack()
    pk.key_items[0]["reason_code"] = "qualifier_conflict"  # blocked 原因配 open 义务
    p = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": "O1", "analysis_code": "AMBIGUITY_REVIEW",
         "selected_fact_aliases": [], "review_action_code": "DISAMBIGUATE_BINDING"}]}
    norm, errs = validate_submission_payload_v4(p, pk.key_items)
    assert norm is None
    assert any(e["error_code"] == "status_reason_incompatible" for e in errs)


def test_group_order_violated_first():
    """组序 violated→open→blocked(疑似未满足最优先呈现)。"""
    pk = _pack()
    pk.key_items.append(
        {"alias": "O5", "obligation_id": "e" * 24, "category": "violated",
         "closure_status": "closed", "satisfaction_status": "violated",
         "reason_code": None, "rule_card_alias": "R2", "fact_aliases": []})
    p = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": "O1", "analysis_code": "EVIDENCE_GAP",
         "selected_fact_aliases": [], "review_action_code": "OBTAIN_MISSING_EVIDENCE"},
        {"obligation_alias": "O5", "analysis_code": "SUSPECTED_VIOLATION",
         "selected_fact_aliases": [], "review_action_code": "MANUAL_VERIFY"},
    ]}
    norm, errs = validate_submission_payload_v4(p, pk.key_items)
    assert errs == []
    text = "\n".join(render_v4_points(pk, norm))
    g1 = text.index("### G1")
    assert "疑似未满足待复核" in text[g1:text.index("### G2")]  # violated 组排第一


def test_details_summary_pairing_complete():
    """每组恰一对 <details>/<summary>,配对完整。"""
    norm, _ = validate_submission_payload_v4(_valid_payload(), _pack().key_items)
    text = "\n".join(render_v4_points(_pack(), norm))
    assert text.count("<details>") == text.count("</details>") == 2
    assert text.count("<summary>") == text.count("</summary>") == 2


def test_missing_category_fails_closed_not_defaulted_open():
    """权威状态缺失 → 整篇 fallback,不得凭空补 open(codex 聚合审核阻断#1)。"""
    pk = _pack()
    norm, errs = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    assert errs == []
    del pk.key_items[0]["category"]  # 校验后被抹掉权威状态
    assert render_v4_points(pk, norm) is None


def test_violated_requires_triple_consistency():
    """violated 三重一致:category=violated 必须配 closure=closed+satisfaction=violated,
    否则伪权威项 → 整篇 fallback(codex 聚合商议)。"""
    pk = _pack()
    pk.key_items.append(
        {"alias": "O5", "obligation_id": "e" * 24, "category": "violated",
         "closure_status": "open", "satisfaction_status": "unknown",  # 不一致
         "reason_code": None, "rule_card_alias": "R2", "fact_aliases": []})
    p = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": "O5", "analysis_code": "SUSPECTED_VIOLATION",
         "selected_fact_aliases": [], "review_action_code": "MANUAL_VERIFY"}]}
    norm, errs = validate_submission_payload_v4(p, pk.key_items)
    assert errs == []  # 校验层不看 closure 字段(其权威互证在渲染 resolve 层)
    assert render_v4_points(pk, norm) is None
