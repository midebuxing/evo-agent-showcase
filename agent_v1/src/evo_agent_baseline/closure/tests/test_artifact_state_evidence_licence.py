"""🔴 证据许可闸 —— 产物齐备布尔不得为「语义不是产物」的义务定 satisfied / violated。

病灶（重锚批 30 栋离线重放实测）：`artifact_requirement_state` 里的产物齐备布尔
（如 `artifact.record.inspection_log`）此前会让**检验涵盖范围 / 记录 / 报告栏目 /
动作**类义务得到确定判定 —— 3,388 条 satisfied + 2,290 条 violated。
「檢驗報告已擬備」并不能证明「涵蓋範圍達標」：一份报告可以齐备而漏检半栋楼。

本文件锁住三件事：
1. **判据是结构的，不是族名白名单** —— 两侧都只读封闭集合（`ObligationKind` 枚举 /
   `carrier_domain` 承载域 / `W0_09_ARTIFACT_SLOTS` 槽登记表 / `derivation=slot_target_fallback`
   派生通道），源码里不得出现按细族 ID 判断的字面量，也不得把目标槽名写成第三白名单；
2. **不许可侧确实被拦**，且落 `open + artifact_state_not_valid_evidence`（而非静默）；
3. **许可侧一条不少** —— `kind="artifact"` 的判定逐字不变（回归护栏：那 7,222 条
   satisfied / 3,006 条 violated 是正当的，动了就是回归）。
"""

from __future__ import annotations

import pathlib
from typing import get_args

import pytest

from evo_agent_baseline.contracts import ObligationKind, OpenReasonCode
from evo_agent_baseline.agent import report_contract_v4 as v4
from evo_agent_baseline.closure import identity_v2
from evo_agent_baseline.closure import obligation_deriver as od

from .fixtures import make_fact, make_fact_pack, make_rule_card, make_rule_slice, run_closure

REASON = "artifact_state_not_valid_evidence"

# 真批里实际出现的一个产物齐备布尔槽（`W0_09_ARTIFACT_SLOTS` 成员）。
ART_SLOT = "artifact.record.inspection_log"
ART_KEY = "record.inspection_log"


def _art_fact(value=True, *, with_domain=True, fid="F-ART-1"):
    """产物齐备布尔事实。`with_domain=False` 时只留槽名锚，用来验两锚各自都能兜住。"""
    return make_fact(
        fid,
        slot_id=ART_SLOT,
        value=value,
        value_type="boolean",
        qualifiers={"carrier_domain": "artifact"} if with_domain else {},
        provenance={"entry_type": "artifact_requirement_state"},
    )


def _wf(action="inspect", *, with_artifact=True):
    """workflow_operands 严格容器（`WorkflowArtifactDTO` 三字段全必填）。"""
    return {
        "primary_actor": "ri", "primary_action": action, "recipients": [],
        "artifacts": [{"artifact_id": "art01", "artifact_type": "record",
                       "artifact_key": ART_KEY}] if with_artifact else [],
        "deadlines": [], "audiences": [], "method_keys_allowed": [],
    }


def _er(bucket):
    """evidence_requirements 严格容器；元素八字段全必填（真卡 370/370 皆如此）。"""
    item = {
        "evidence_requirement_id": "er01", "kind": "inspection_record",
        "required": True, "description": "test", "artifact_ids": ["art01"],
        "slot_ref_ids": [], "measure_keys": [], "required_field_groups": [],
    }
    out = {"for_matching": [], "for_submission": [], "for_completion": []}
    out[bucket] = [item]
    return out


def _obls(result):
    return list(result.obligation_set.obligations)


def _pick(result, kind):
    return [o for o in _obls(result) if o.kind == kind]


# ===================================================================== #
# 一、判据的结构性
# ===================================================================== #
def test_licence_partitions_the_closed_obligation_kind_enum():
    """许可 / 不许可两集合必须**完全划分** ObligationKind —— 新增 kind 忘归类必炸。

    这是「结构可靠」的核心依据：判据的定义域是 contracts 里的封闭枚举，
    不是随卡包增长的族名清单。
    """
    all_kinds = frozenset(get_args(ObligationKind))
    assert od.ARTIFACT_STATE_LICENSED_KINDS | od.ARTIFACT_STATE_UNLICENSED_KINDS == all_kinds
    assert od.ARTIFACT_STATE_LICENSED_KINDS & od.ARTIFACT_STATE_UNLICENSED_KINDS == frozenset()
    # 义务本体是产物的那一格必须在许可侧；四类实测中招的 kind 必须在不许可侧。
    assert "artifact" in od.ARTIFACT_STATE_LICENSED_KINDS
    for kind in ("evidence", "report_field", "action", "supervision"):
        assert kind in od.ARTIFACT_STATE_UNLICENSED_KINDS


def test_licence_is_not_a_family_name_whitelist():
    """闸的实现里不得出现细族 ID 字面量 —— 那类判据会随卡包腐化（本仓已有前科）。"""
    src = pathlib.Path(od.__file__).read_text(encoding="utf-8")
    for forbidden in (".ri.coverage", ".ri.record", ".ri.schema", "mbis.inspection."):
        assert forbidden not in src, f"派生器出现族名字面量 {forbidden!r}"


def test_artifact_state_fact_detector_has_three_independent_anchors():
    """三锚取并集 = fail-closed：任一锚单独存在都能识别出产物齐备布尔。"""
    assert od.is_artifact_state_fact(_art_fact())                       # ①② 都有
    assert od.is_artifact_state_fact(_art_fact(with_domain=False))      # 只剩槽名锚
    only_domain = make_fact(
        "F-D", slot_id="reporting.record.maintained", value=True,
        qualifiers={"carrier_domain": "artifact"},
    )
    assert od.is_artifact_state_fact(only_domain)                       # 只剩承载域锚
    # 第三锚：slot_targets 回退派生（reporting.artifact.prepared 形状）——
    # 无 carrier_domain、槽名不在 W0_09，只靠 provenance.derivation。
    prepared = make_fact(
        "F-PREP",
        slot_id="reporting.artifact.prepared",
        value=True,
        value_type="boolean",
        qualifiers={"artifact_key": "report.inspection", "fragment_id": "FRG-1"},
        provenance={"derivation": "slot_target_fallback", "carrier_label": "Fragment"},
    )
    assert od.is_artifact_state_fact(prepared)
    # 反向：同槽名但不是回退派生 → 不算（防把无关 reporting.* 误收）。
    plain_reporting = make_fact(
        "F-R", slot_id="reporting.artifact.prepared", value=True,
        value_type="boolean", qualifiers={"artifact_key": "report.inspection"},
        provenance={},
    )
    assert not od.is_artifact_state_fact(plain_reporting)
    plain = make_fact("F-P", slot_id="defect.class.present", value=True,
                      qualifiers={"carrier_domain": "condition"})
    assert not od.is_artifact_state_fact(plain)


def test_third_anchor_refuses_evidence_fed_by_prepared_fallback():
    """铁证形状：evidence 义务绑 reporting.artifact.prepared → 拒判。

    对应重锚批 0006 `31f27152227421d9fe7616bf`：拿「检验报告文件在」去满足
    「须在报告中突出未完成消防改善」——产物齐备 ≠ 栏目已载明。
    """
    prepared = make_fact(
        "F-PREP",
        slot_id="reporting.artifact.prepared",
        value=True,
        value_type="boolean",
        qualifiers={"artifact_key": "report.inspection", "fragment_id": "FRG-1"},
        provenance={"derivation": "slot_target_fallback", "carrier_label": "Fragment"},
    )
    card = make_rule_card(
        "RC.gate.prepared",
        slot_role_map=[{
            "slot_ref_id": "sr01",
            "slot_id": "reporting.artifact.prepared",
            "roles": ["evidence"],
            "required": True,
            "qualifiers": {"artifact_key": "report.inspection"},
        }],
    )
    result = run_closure(make_rule_slice([card]), make_fact_pack([prepared]))
    ev = _pick(result, "evidence")
    assert ev and {(o.closure_status, o.satisfaction_status, o.open_reason_code) for o in ev} == {
        ("open", "unknown", REASON)
    }


def test_third_anchor_refuses_even_for_licensed_kinds():
    """🔴 **本测已于 2026-08-03 反转，原名 `..._keeps_artifact_kind_licensed_on_prepared`。**

    ## 原立场（已推翻）

    「`kind=artifact` 读派生齐备布尔仍正当 —— 第三锚不得误伤许可侧。」
    依据是一条**设计假设**（「产物状态当条件读是正当的」），
    **没有对任何一条具体法规条文做过裁定**。

    ## 推翻它的证据

    对全部 **52 个 (artifact_key, action) 组合**逐条读**中文法规原文**裁定
    （引文经 `scripts/verify_adjudication_quotes.py` 机器核回原文，**52/52 逐字命中**）：

        产物须齐备（＝拿「文件存在」判定正当）   0 条   ← 一条都没有
        须呈交／签署／载明                      15 条
        行为须发生                              37 条
        存疑                                     0 条

    典型：`report.completion × verify_repair_standard`（29 处引用）——
    中文原文要求的是「核实修葺标准」这个**行为**，而槽给的是「完工报告存在」。

    ## 为什么原立场看起来成立

    `reporting.artifact.prepared` 这个**槽名**读着像「产物已备妥」，
    于是「artifact 类义务读它天经地义」显得不言自明。
    但它不是世界模型产的槽——是 `fact_retriever.py:601` 一张硬编码回退表
    把 12 个 `artifact.*` 折叠出来的，**只有「这份特定文件存在与否」一条轴**。
    **槽名像不像，和它答不答得上那条义务，是两件事。**

    ⚠️ 本文件开头「许可侧一条不少（7,222 satisfied / 3,006 violated）」那条回归护栏，
    其数字**此前已被查实来自另一个批、且用的是超集过滤**。
    本改动的实测影响面是 **189 条**（批 I，`kind=artifact` 且证据含回退行），
    不是 7,222。
    """
    prepared = make_fact(
        "F-PREP",
        slot_id="reporting.artifact.prepared",
        value=True,
        value_type="boolean",
        qualifiers={"artifact_key": "report.inspection"},
        provenance={"derivation": "slot_target_fallback"},
    )
    # workflow_operands.artifacts 走 artifact 通道；这里用 submission 桶更直接。
    card = make_rule_card(
        "RC.gate.prepared.art",
        workflow_operands=_wf("submit"),
        evidence_requirements=_er("for_submission"),
    )
    # 🔴 反转后的不变量：回退表折叠行**对任何 kind 都不许可**，含许可集合里的 kind。
    assert od.artifact_state_licenses_verdict("artifact", [prepared]) is False
    assert od.artifact_state_licenses_verdict("trigger", [prepared]) is False
    assert od.artifact_state_licenses_verdict("evidence", [prepared]) is False
    # 边界：**真实** `artifact.*` 世界槽（非回退派生）对许可 kind 仍然放行
    # ——本改动只收窄第三锚，另两锚一字未动。
    assert od.artifact_state_licenses_verdict("artifact", [_art_fact(True)]) is True


def test_third_anchor_is_load_bearing_reverse_check():
    """反向验证：临时去掉第三锚后，prepared 识别与拒判必须失败。

    没有反向验证的测试可能什么都没测。本测在进程内临时替换谓词，不改磁盘文件。
    """
    prepared = make_fact(
        "F-PREP",
        slot_id="reporting.artifact.prepared",
        value=True,
        value_type="boolean",
        qualifiers={"artifact_key": "report.inspection"},
        provenance={"derivation": "slot_target_fallback"},
    )
    assert od.is_artifact_state_fact(prepared)

    original = od.is_artifact_state_fact

    def _two_anchor_only(fact):
        if str((fact.qualifiers or {}).get("carrier_domain") or "") == "artifact":
            return True
        return str(fact.slot_id or "") in od.W0_09_ARTIFACT_SLOTS

    # 🔴 2026-08-03：第三锚现在有**两条**消费路径，变异必须同时盖住，否则测空。
    # ① `is_artifact_state_fact`（三锚并集，老路径）；
    # ② `is_slot_target_fallback_fact`（新增，许可闸对任何 kind 一律拒判那一条）。
    # 首版只 patch ①，于是拒判仍由 ② 产生 ⇒ 断言「应放行」失败——
    # **那不是代码回归，是变异没盖全**。
    original_fb = od.is_slot_target_fallback_fact
    od.is_artifact_state_fact = _two_anchor_only  # type: ignore[assignment]
    od.is_slot_target_fallback_fact = lambda f: False  # type: ignore[assignment]
    try:
        assert not od.is_artifact_state_fact(prepared), "去掉第三锚后仍认出 prepared = 测空了"
        # 端到端：两锚下 evidence 会错误放行
        card = make_rule_card(
            "RC.gate.rev",
            slot_role_map=[{
                "slot_ref_id": "sr01",
                "slot_id": "reporting.artifact.prepared",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {"artifact_key": "report.inspection"},
            }],
        )
        result = run_closure(make_rule_slice([card]), make_fact_pack([prepared]))
        ev = _pick(result, "evidence")
        assert ev and all(o.satisfaction_status == "satisfied" for o in ev), (
            "去掉第三锚后 evidence 仍拒判 = 拒判不依赖第三锚，反向验证失效"
        )
    finally:
        od.is_artifact_state_fact = original  # type: ignore[assignment]
        od.is_slot_target_fallback_fact = original_fb  # type: ignore[assignment]

    # 还原后第三锚必须仍在（进程内替换，非改文件；再断言行为回到三锚）。
    assert od.is_artifact_state_fact(prepared)
    assert "slot_target_fallback" in pathlib.Path(od.__file__).read_text(encoding="utf-8")


def test_licence_predicate_is_a_no_op_without_artifact_state_facts():
    """不含产物齐备布尔时，闸对任何 kind 都恒许可 —— 既有判定零影响。"""
    plain = [make_fact("F-P", slot_id="defect.class.present", value=True)]
    for kind in get_args(ObligationKind):
        assert od.artifact_state_licenses_verdict(kind, plain) is True


def test_reason_code_registered_in_every_authority():
    """新原因码必须在**五处**同时登记，缺一处要么 import 炸、要么消费者看不到。"""
    assert REASON in get_args(OpenReasonCode)          # contracts 权威清单
    assert REASON in v4.REASON_CODE_SPEC               # v4 报告契约模板
    assert REASON in v4._OPEN_REASONS                  # 状态×原因兼容矩阵
    assert REASON in identity_v2.OPEN_REASON_ORDER     # 身份合并全序（缺则抛异常）
    assert REASON in od._NODE_OPEN_REASON_RANK         # node 通道合并排序
    assert v4.REASON_CODE_SPEC[REASON]["analysis"] == "MODELING_GAP"


# ===================================================================== #
# 二、不许可侧被拦（端到端过 validate_building_closure）
# ===================================================================== #
def _card_with_matching_evidence(**kw):
    """`for_matching` evidence requirement 指向产物 —— 默认 kind=evidence（不许可）。"""
    return make_rule_card(
        "RC.gate.evidence",
        workflow_operands=_wf(),
        evidence_requirements=_er("for_matching"),
        **kw,
    )


def test_evidence_requirement_refuses_verdict_from_artifact_state():
    result = run_closure(make_rule_slice([_card_with_matching_evidence()]),
                         make_fact_pack([_art_fact(True)]))
    ev = _pick(result, "evidence")
    assert ev, "应派生出 evidence 义务"
    assert {(o.closure_status, o.satisfaction_status, o.open_reason_code) for o in ev} == {
        ("open", "unknown", REASON)
    }
    # 证据 id 照旧落盘：消费者要看得见「系统查到了什么、为什么不算」。
    assert all(o.evidence_fact_ids for o in ev)


def test_evidence_requirement_refuses_even_when_artifact_absent():
    """布尔为 false 时同样不许判 violated —— 报告没齐备也不证明「涵盖范围不达标」。"""
    result = run_closure(make_rule_slice([_card_with_matching_evidence()]),
                         make_fact_pack([_art_fact(False)]))
    assert all(o.satisfaction_status == "unknown" for o in _pick(result, "evidence"))


@pytest.mark.parametrize("bucket", ["for_submission", "for_completion"])
def test_submission_and_completion_buckets_stay_licensed(bucket):
    """卡表达「此产物须齐备」的既有结构出路 = **放进 submission / completion 桶**。

    `_BUCKET_DEFAULT_KIND` 把这两桶定为 kind=artifact ⇒ 天然在许可侧、判定不变。
    ⚠️ 不是靠 `evidence_kind` 字段：真卡 370/370 用的是 `kind`（自由文本、70 个取值、
    无受控词表），`evaluate_evidence_requirement` 读的 `evidence_kind` 在真卡里
    **一条都不存在** —— 那是一处死读，与本闸无关但值得单独记账。
    """
    card = make_rule_card("RC.gate.bucket", workflow_operands=_wf("submit"),
                          evidence_requirements=_er(bucket))
    result = run_closure(make_rule_slice([card]), make_fact_pack([_art_fact(True)]))
    art = _pick(result, "artifact")
    assert art and all(
        (o.closure_status, o.satisfaction_status) == ("closed", "satisfied") for o in art
    )
    assert not _pick(result, "evidence")


def test_slot_role_evidence_refuses_artifact_state():
    """`slot_role_map` 的 evidence 槽通道 —— 这条分支连布尔值都不读，尤其不能放行。"""
    card = make_rule_card(
        "RC.gate.slotrole",
        slot_role_map=[{"slot_ref_id": "sr01", "slot_id": ART_SLOT,
                        "roles": ["evidence"], "required": True, "qualifiers": {}}],
    )
    result = run_closure(make_rule_slice([card]), make_fact_pack([_art_fact(False)]))
    ev = _pick(result, "evidence")
    assert ev and {(o.closure_status, o.open_reason_code) for o in ev} == {("open", REASON)}


def _action_node_card():
    """单节点 action 卡，节点挂 artifact_ids —— 现网病灶的原型（`satisfaction_bindings`）。"""
    return make_rule_card(
        "RC.gate.node",
        workflow_operands=_wf("inspect"),
        obligation_graph={"nodes": [{
            "obligation_node_id": "RC.gate.node.n01", "node_kind": "obligation",
            "actor": "ri", "action": "inspect", "artifact_ids": ["art01"],
            "recipient_ids": [], "deadline_ids": [], "trigger_condition_ids": [],
        }], "edges": []},
    )


def test_node_main_action_refuses_but_its_artifact_child_survives():
    """同一 artifact 通道两个消费者，**判据不同**：

    · node 主义务 kind=action（「須檢驗」）→ 拒判；
    · 派生出去的 artifact 子义务 kind=artifact（「該記錄須齊備」）→ 照旧 satisfied。
    这正是「kind=artifact 一条不少」的最小回归护栏。
    """
    result = run_closure(make_rule_slice([_action_node_card()]),
                         make_fact_pack([_art_fact(True)]))
    action = _pick(result, "action")
    assert action and {(o.closure_status, o.open_reason_code) for o in action} == {
        ("open", REASON)
    }
    artifact = _pick(result, "artifact")
    assert artifact and all(
        (o.closure_status, o.satisfaction_status) == ("closed", "satisfied")
        for o in artifact
    )


# ===================================================================== #
# 三、许可侧一条不少
# ===================================================================== #
@pytest.mark.parametrize("value,expected", [(True, "satisfied"), (False, "violated")])
def test_workflow_artifact_obligation_unchanged(value, expected):
    """`workflow_operands.artifacts` → kind=artifact：真/假两侧判定都逐字不变。"""
    card = make_rule_card("RC.gate.wf", workflow_operands=_wf("submit"))
    result = run_closure(make_rule_slice([card]), make_fact_pack([_art_fact(value)]))
    art = _pick(result, "artifact")
    assert art and all(
        (o.closure_status, o.satisfaction_status) == ("closed", expected) for o in art
    )


def test_trigger_channel_may_still_read_artifact_state_as_a_condition():
    """把产物状态当**条件**读是正当的（「若已提交 MBI4 則…」），不在拦截范围内。"""
    card = make_rule_card(
        "RC.gate.trigger",
        slot_role_map=[{"slot_ref_id": "sr01", "slot_id": ART_SLOT,
                        "roles": ["trigger"], "required": True, "qualifiers": {}}],
    )
    result = run_closure(make_rule_slice([card]), make_fact_pack([_art_fact(True)]))
    trg = _pick(result, "trigger")
    assert trg and all(o.satisfaction_status == "satisfied" for o in trg)


def test_non_artifact_evidence_still_reaches_a_verdict():
    """闸只对产物齐备布尔生效；普通事实证据照旧能定 satisfied（防误伤全域）。"""
    card = make_rule_card(
        "RC.gate.plain",
        slot_role_map=[{"slot_ref_id": "sr01", "slot_id": "defect.class.present",
                        "roles": ["evidence"], "required": True, "qualifiers": {}}],
    )
    fact = make_fact("F-P", slot_id="defect.class.present", value=True,
                     value_type="boolean", qualifiers={"carrier_domain": "condition"})
    result = run_closure(make_rule_slice([card]), make_fact_pack([fact]))
    ev = _pick(result, "evidence")
    assert ev and all(
        (o.closure_status, o.satisfaction_status) == ("closed", "satisfied") for o in ev
    )
