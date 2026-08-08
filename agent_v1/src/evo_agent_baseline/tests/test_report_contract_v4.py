"""报告契约 v4 测试（spec §7.4.5 / E-5，Gate C 严格 0 严重错释）。

核心断言:模型无法经任何字段注入规则语义;规则/状态/原因/证据/条文全由程序权威组装。
"""
from dataclasses import dataclass, field
from pathlib import Path
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


def test_renderer_degrades_when_quote_missing_but_fails_when_card_missing():
    """引文缺失分档（2026-08-04 语义升级，沿革见 placeholder 测试 docstring）：

    - 引文空/占位 ⇒ **诚实降级**（卡号引用行，不冒充引文）；
    - 卡整个缺失 ⇒ 仍整篇 fallback（这半边一寸不让）。"""
    pk = _pack()
    pk.rule_cards[0]["quote"] = ""  # R1 无引文 ⇒ 降级
    norm, _ = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    lines = render_v4_points(pk, norm)
    assert lines is not None and "显式缺席" in chr(10).join(lines)
    pk2 = _pack()
    pk2.rule_cards = []             # 卡缺失 ⇒ 整篇 fallback
    norm2, _ = validate_submission_payload_v4(_valid_payload(), pk2.key_items)
    assert render_v4_points(pk2, norm2) is None


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


def test_placeholder_quote_degrades_honestly_not_whole_fallback():
    """占位引文语义升级（2026-08-04）：**诚实降级**而非整篇 fallback。

    沿革：copilot 审#2（2026-07-23）立的规矩是「占位引文不算权威 ⇒ 整篇 fallback」，
    防的是占位符**冒充引文**渲给消费者。2026-08-04 实测该语义的代价：中文权威源
    11/470 张显式缺席卡把满血批 **15/30 栋**的叙述整篇黑洞——顶部 violated 项反而
    从叙述里消失，比降级更误导。新契约（`test_v4_absent_quote_degradation.py` 三条
    变异锁定）：引文缺席 ⇒ 渲染成功＋卡号引用行＋缺席说明；**绝不**出现引号包着的
    占位符（原防线保留）；卡整个缺失仍整篇 fallback。"""
    pk = _pack()
    pk.rule_cards[0]["quote"] = "（未取得引文）"
    norm, _ = validate_submission_payload_v4(_valid_payload(), pk.key_items)
    lines = render_v4_points(pk, norm)
    assert lines is not None, "缺席卡不得再拉黑整篇"
    joined = chr(10).join(lines)
    assert "「（未取得引文）」" not in joined, "占位符冒充引文＝copilot 审#2 那个洞复活"
    assert "显式缺席" in joined


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


# ===== 2026-07-27 codex 审核门 P1-A：原因码登记双向对齐 =====

def test_reason_code_spec_matches_authoritative_registry_both_ways():
    """🔴 结构性闸：`REASON_CODE_SPEC` 与 `contracts` 权威原因码清单**双向**集合差为空。

    修前失败形态（实测）：`missing_satisfaction_binding` 由派生器产出、已登记在
    `contracts.OpenReasonCode`，却漏进 `REASON_CODE_SPEC` ⇒ `reason_key_of` 返回
    None ⇒ 该义务被判 `no_authoritative_reason`、整篇 v4 提交被拒 ⇒ **消费者看不到
    这块缺口**。而模块内原有的那条 assert 只比本文件三张表之间是否自洽——
    漏登记时它们**依然自洽**，所以拦不住。故必须拿外部权威清单比。

    反方向同样拦：本表多出 contracts 没有的码 = 在解释一个不存在的状态。
    """
    from typing import get_args

    from evo_agent_baseline.contracts import BlockedReasonCode, OpenReasonCode

    authoritative = set(get_args(OpenReasonCode)) | set(get_args(BlockedReasonCode))
    spec = set(REASON_CODE_SPEC) - {"__violated__"}   # 合成键无 contracts 对应物
    assert spec == authoritative, (
        f"contracts 有而模板表缺={sorted(authoritative - spec)}；"
        f"模板表有而 contracts 缺={sorted(spec - authoritative)}")


def test_open_blocked_partition_matches_authoritative_registry():
    """再细一层：open/blocked 的**归属**也须与 contracts 一致（不只是全集相等）。

    只比全集会放过「把一个 open 码写进 `_BLOCKED_REASONS`」——那会让状态兼容矩阵
    把合法项判成 `status_reason_incompatible`，同样触发整篇回退。
    """
    from typing import get_args

    from evo_agent_baseline.agent import report_contract_v4 as v4
    from evo_agent_baseline.contracts import BlockedReasonCode, OpenReasonCode

    assert set(v4._OPEN_REASONS) == set(get_args(OpenReasonCode))
    assert set(v4._BLOCKED_REASONS) == set(get_args(BlockedReasonCode))


def test_missing_satisfaction_binding_survives_the_v4_contract():
    """端到端：带该原因码的 open 义务必须能通过 v4 校验（而不是整篇被拒）。

    这是「消费者能不能看到这块缺口」的实质断言——只断言字典里有这个键
    等于只测了生产者自身。
    """
    pk = _pack()
    pk.key_items.append(
        {"alias": "O9", "obligation_id": "f" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_satisfaction_binding",
         "rule_card_alias": "R1", "fact_aliases": []})
    payload = {"contract": "report_contract_v4", "points": [
        {"obligation_alias": "O9", "analysis_code": "MODELING_GAP",
         "selected_fact_aliases": [], "review_action_code": "ESCALATE_MODELING_GAP"}]}
    norm, errs = validate_submission_payload_v4(payload, pk.key_items)
    assert errs == [], f"新原因码过不了 v4 契约 -> 整篇回退、缺口对消费者不可见：{errs}"
    assert norm and norm[0]["obligation_alias"] == "O9"


# ===== DEBT-099 回归：6 组行动项紧凑化（2026-08-08）=====


def _six_group_pack():
    """6 组构造样例（触发 0020/0047 两栋主视图 181 行的最大组数）。

    每组一个不同签名，对应实测 6 个分析码：疑似未满足 / 证据缺口 /
    字段完整性 / 测量数据 / 时间锚点 / 绑定歧义。
    """
    items = [
        {"alias": "O1", "obligation_id": "a" * 24, "category": "violated",
         "closure_status": "closed", "satisfaction_status": "violated",
         "reason_code": None, "rule_card_alias": "R1", "fact_aliases": []},
        {"alias": "O2", "obligation_id": "b" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_fact", "rule_card_alias": "R1",
         "fact_aliases": []},
        {"alias": "O3", "obligation_id": "c" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_required_field_group", "rule_card_alias": "R2",
         "fact_aliases": []},
        {"alias": "O4", "obligation_id": "d" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_measurement", "rule_card_alias": "R1",
         "fact_aliases": []},
        {"alias": "O5", "obligation_id": "e" * 24, "category": "open",
         "closure_status": "open", "satisfaction_status": "unknown",
         "reason_code": "missing_time_anchor", "rule_card_alias": "R2",
         "fact_aliases": []},
        {"alias": "O6", "obligation_id": "f" * 24, "category": "blocked",
         "closure_status": "blocked", "satisfaction_status": "unknown",
         "reason_code": "ambiguous_fact_binding", "rule_card_alias": "R2",
         "fact_aliases": []},
    ]
    return _Pack(
        key_items=items,
        rule_cards=[
            {"alias": "R1", "rule_card_id": "rc.mbis.x.c01",
             "quote": "条文一。"},
            {"alias": "R2", "rule_card_id": "rc.mbis.y.c01",
             "quote": "条文二。"},
        ],
        facts=[],
    )


def _six_group_payload():
    return {
        "contract": "report_contract_v4",
        "points": [
            {"obligation_alias": "O1", "analysis_code": "SUSPECTED_VIOLATION",
             "selected_fact_aliases": [], "review_action_code": "MANUAL_VERIFY"},
            {"obligation_alias": "O2", "analysis_code": "EVIDENCE_GAP",
             "selected_fact_aliases": [], "review_action_code": "OBTAIN_MISSING_EVIDENCE"},
            {"obligation_alias": "O3", "analysis_code": "FIELD_GROUP_REVIEW",
             "selected_fact_aliases": [], "review_action_code": "SUPPLY_REQUIRED_FIELDS"},
            {"obligation_alias": "O4", "analysis_code": "MEASUREMENT_REVIEW",
             "selected_fact_aliases": [], "review_action_code": "OBTAIN_MEASUREMENT"},
            {"obligation_alias": "O5", "analysis_code": "TIME_ANCHOR_REVIEW",
             "selected_fact_aliases": [], "review_action_code": "SUPPLY_TIME_ANCHOR"},
            {"obligation_alias": "O6", "analysis_code": "AMBIGUITY_REVIEW",
             "selected_fact_aliases": [], "review_action_code": "DISAMBIGUATE_BINDING"},
        ],
    }


def test_debt099_six_groups_compact_within_line_budget(tmp_path):
    """DEBT-099 回归：6 组行动项以紧凑格式渲染，每组主视图两行不随组数线性吃预算。

    改前每组 3 行（组头 + 义务入口 + 状态/原因/动作），6 组 = 18 主视图行；
    改后每组 2 行（组头 + 合并入口行），6 组 = 12 行。
    消失的字符仅为两条列表项间的换行，代之以 ` ｜ ` 分隔符；
    两个标签与全部取值逐字保留，语义零损失。
    A 门 v4 形态校验须通过（紧凑格式合法）。
    """
    pk = _six_group_pack()
    norm, errs = validate_submission_payload_v4(_six_group_payload(), pk.key_items)
    assert errs == [], f"构造样例校验失败: {errs}"
    lines = render_v4_points(pk, norm)
    assert lines is not None

    main_nonempty = []
    in_fold = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("<details"):
            in_fold = True
        if not in_fold and s:
            main_nonempty.append(ln)
        if s == "</details>":
            in_fold = False

    group_headers = [ln for ln in main_nonempty if ln.startswith("### G")]
    assert len(group_headers) == 6, f"应为 6 组，实得 {len(group_headers)}"

    assert len(main_nonempty) == 12, (
        f"6 组紧凑格式应 12 主视图行（2/组），实得 {len(main_nonempty)}；"
        "若为 18 则紧凑化未生效（DEBT-099 回归）")

    standalone = [ln for ln in main_nonempty
                  if ln.startswith("- 状态 / 原因 / 动作：")]
    assert standalone == [], "状态/原因/动作不应独立成行（应已合并）"

    merged = [ln for ln in main_nonempty if ln.startswith("- 义务入口：")]
    assert len(merged) == 6
    for ln in merged:
        assert "状态 / 原因 / 动作：" in ln, "合并行缺状态/原因/动作标签"

    text = "\n".join(lines)
    for alias in ("[O1/R1]", "[O2/R1]", "[O3/R2]", "[O4/R1]",
                  "[O5/R2]", "[O6/R2]"):
        assert alias in text, f"别名 {alias} 丢失"

    import importlib.util
    _script = Path(__file__).resolve().parents[3] / "scripts" / "check_report_usability.py"
    _spec = importlib.util.spec_from_file_location("_cru_debt099", _script)
    cru = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cru)
    report_text = "<!-- report contract v4 -->\n" + "\n".join(lines)
    p = tmp_path / "debt099_report.md"
    p.write_text(report_text, encoding="utf-8")
    r = cru.analyze(str(p), {"main_max": 9999, "dup_max": 1.0, "mix_max": 1.0})
    assert r["checks"]["v4_group_shape"][1] is True, (
        f"紧凑格式 v4 形态校验失败: {r['checks']['v4_group_shape']}")
    assert r["checks"]["v4_group_count"][1] is True
