"""🔴 前缀猜测改类而来的 `kind="artifact"` 不得据产物齐备布尔下判定。

## 病灶（批 I `phase_i_fragcov2_seed301_20260729` 实测 95 条：satisfied 66 / violated 29）

`refine_action_kind`（`obligation_deriver.py:2157`）按 `action` 的**字符串前缀**改类：
`action.startswith("submit") or startswith("deliver")` → `"artifact"`。
而 `"artifact"` 在 `ARTIFACT_STATE_LICENSED_KINDS` 里 ⇒ 许可闸无条件放行
⇒ 拿「文件存在」给「内容须载明 / 须呈交」类义务下确定判定。

**`action` 无受控词表、是卡作者写的译文**，所以这是猜，不是结构规则。

守则 §4.2.2 的七张卡是最干净的对照——**同一份建议书的七项内容要求，绑同一个 art01**：

| 子项 | `action` | `refine_action_kind` | 批 I 结果 |
|---|---|---|---|
| (a)目的 (b)範圍 (b)方法 (c)理由 (d)相片 (d)平面圖 | `submit_compliant_proposal` | **artifact** | **satisfied（假）** |
| (d)缺陷摘要 | `include_defect_summary_in_...` | `report_field` | unknown（对） |

**七条待遇由一个译文动词决定。** 反方向同样成立：拿「证书文件不在」判 violated，
而世界侧 `artifact.*` **只有「文件在不在」一个轴、没有呈交/签署轴** ⇒ 假违规。

## 本文件锁住四件事

1. 改类而来的 artifact **被拦**，落 `open + artifact_state_not_valid_evidence`；
2. `include_*`（留在 `report_field`）**行为不变**——证明拦的是「改类」不是「这张卡」；
3. **结构规则产生的 artifact 一条不少**（`workflow_operands.artifacts` 与桶默认）；
4. **反向变异验证**：进程内摘掉新参数的效果后，第 1 条必须失败
   （没有变异验证的防御性测试可能什么都没测——本项目既有教训）。

## 影响面为何精确

`refine_action_kind` 的返回值域是
`{artifact, report_field, supervision, method, action, prohibition, escalation}`
——**唯一落在许可集合里的只有 `artifact`**（`trigger`/`prerequisite`/`definition`/
`exception`/`scope` 它一个都产不出）。故本改动影响面 ＝ 「改类成 artifact 且证据含产物态布尔」，
不多不少。本文件 `test_refined_kind_domain_intersects_licensed_set_only_at_artifact` 锁住它。
"""

from __future__ import annotations

from typing import get_args

import pytest

from evo_agent_baseline.contracts import ObligationKind
from evo_agent_baseline.closure import obligation_deriver as od

from .fixtures import make_fact, make_fact_pack, make_rule_card, make_rule_slice, run_closure

REASON = "artifact_state_not_valid_evidence"
ART_SLOT = "artifact.record.inspection_log"
ART_KEY = "record.inspection_log"


def _obls(result):
    # ⚠️ 必须走 `result.obligation_set.obligations`。写成 `getattr(result, "obligations", [])`
    # 会**静默返回空表** ⇒ 所有断言测在空集上、看起来全是「东西不见了」。首版栽过一次。
    obls = list(result.obligation_set.obligations)
    assert obls, "闭包一条义务都没产出 ⇒ 夹具本身就没跑起来，后面的断言无意义"
    return obls


def _pick(result, kind):
    return [o for o in _obls(result) if o.kind == kind]


def _art_fact(value=True, fid="F-ART-1"):
    """产物齐备布尔（锚①：`carrier_domain == "artifact"`）。"""
    return make_fact(
        fid,
        slot_id=ART_SLOT,
        value=value,
        value_type="boolean",
        qualifiers={"carrier_domain": "artifact"},
        provenance={"entry_type": "artifact_requirement_state"},
    )


def _wf(action):
    return {
        "primary_actor": "ri", "primary_action": action, "recipients": [],
        "artifacts": [{"artifact_id": "art01", "artifact_type": "record",
                       "artifact_key": ART_KEY}],
        "deadlines": [], "audiences": [], "method_keys_allowed": [],
    }


def _card(action, rid="RC.refined"):
    """单节点卡 ＋ `slot_role_map` 主证据槽 —— §4.2.2 那七张卡的最小原型。

    单节点是必要的：`_node_satisfaction_slot_refs` 对多节点卡缺省拒绝
    （卡级表无 node 外键），走不到许可闸这一步。
    """
    return make_rule_card(
        rid,
        workflow_operands=_wf(action),
        slot_role_map=[{"slot_ref_id": "sr01", "slot_id": ART_SLOT,
                        "roles": ["evidence"], "required": True, "qualifiers": {}}],
        obligation_graph={"nodes": [{
            "obligation_node_id": f"{rid}.n01", "node_kind": "obligation",
            "actor": "ri", "action": action, "artifact_ids": ["art01"],
            "recipient_ids": [], "deadline_ids": [], "trigger_condition_ids": [],
        }], "edges": []},
    )


# ===================================================================== #
# 一、改类而来的 artifact 被拦
# ===================================================================== #
@pytest.mark.parametrize("action", ["submit_compliant_proposal", "deliver_report_to_ba"])
@pytest.mark.parametrize("value", [True, False])
def test_action_refined_artifact_is_refused(action, value):
    """`submit_*` / `deliver_*` 改类成 artifact 后**不得**据产物态布尔下判定。

    真假两侧都要拦：`value=True` 对应批 I 那 66 条假 satisfied，
    `value=False` 对应 29 条假 violated（世界侧根本没有呈交轴，判违规是冤枉人）。
    """
    assert od.refine_action_kind("obligation", action) == "artifact", "前提：该 action 确实改类"
    result = run_closure(make_rule_slice([_card(action)]), make_fact_pack([_art_fact(value)]))
    refused = [o for o in _obls(result) if o.open_reason_code == REASON]
    assert refused, f"{action}/{value}：改类 artifact 未被拦"
    assert all(o.closure_status == "open" for o in refused)
    assert all(o.satisfaction_status == "unknown" for o in refused)


def test_include_prefix_unchanged_same_card_shape():
    """对照组：`include_*` 留在 `report_field`，本就不许可 ⇒ 行为**不因本改动变化**。

    这一条证明拦的是「改类」这个动作，不是「这张卡」或「这个槽」。
    §4.2.2(d) 缺陷摘要走的正是这条路径，它一直是诚实 unknown。
    """
    action = "include_defect_summary_in_detailed_investigation_proposal"
    assert od.refine_action_kind("obligation", action) == "report_field"
    result = run_closure(make_rule_slice([_card(action, "RC.include")]),
                         make_fact_pack([_art_fact(True)]))
    refused = [o for o in _obls(result) if o.open_reason_code == REASON]
    assert refused, "report_field 侧本就该拦，拦没了说明改动误伤"


def test_the_seven_siblings_now_get_the_same_treatment():
    """§4.2.2 的核心不变量：**同一份产物的并列内容要求，待遇必须一致**。

    改动前：`submit_*` 六条 satisfied、`include_*` 一条 unknown——由译文动词决定。
    改动后：七条**全部** unknown ＋ 同一个原因码。
    """
    statuses = set()
    for i, action in enumerate([
        "submit_compliant_proposal",
        "include_defect_summary_in_detailed_investigation_proposal",
    ]):
        result = run_closure(make_rule_slice([_card(action, f"RC.sib{i}")]),
                             make_fact_pack([_art_fact(True)]))
        for o in _obls(result):
            if o.open_reason_code == REASON:
                statuses.add((o.closure_status, o.satisfaction_status, o.open_reason_code))
    assert statuses == {("open", "unknown", REASON)}, (
        f"并列子项待遇仍不一致：{statuses}")


# ===================================================================== #
# 二、结构规则产生的 artifact 一条不少
# ===================================================================== #
@pytest.mark.parametrize("value,expected", [(True, "satisfied"), (False, "violated")])
def test_structural_artifact_child_survives_while_refined_node_is_refused(value, expected):
    """🔴 本改动最重要的一条：**同一张卡上两条 `kind="artifact"`，待遇必须相反**。

    · `workflow_operands.artifacts` 派生的子义务 —— **结构规则**，
      谓词确实是「该产物须齐备」⇒ 判定逐字不变（closed/satisfied 或 closed/violated）；
    · node 主义务（`submit_*` 被 `refine_action_kind` 改类）—— **前缀猜测**
      ⇒ 必须落 `open + artifact_state_not_valid_evidence`。

    ⚠️ 两者 `kind` 字段**完全相同**，只能靠原因码区分。
    首版测试就是因为拿 `kind` 一把抓、把两条混在一起断言，
    看起来像「拦过头了」——**实际是断言写错了，不是代码错了**。
    这也正说明为什么这条必须分开锁：**拦过头和拦对了，在 `kind` 这一层看不出来。**
    """
    result = run_closure(make_rule_slice([_card("submit_compliant_proposal", "RC.wfchild")]),
                         make_fact_pack([_art_fact(value)]))
    art = _pick(result, "artifact")

    structural = [o for o in art if o.open_reason_code != REASON]
    refined = [o for o in art if o.open_reason_code == REASON]

    assert structural, "结构规则产生的 artifact 子义务消失 ⇒ 拦过头了"
    assert all((o.closure_status, o.satisfaction_status) == ("closed", expected)
               for o in structural), f"结构侧判定被改动：{[(o.closure_status, o.satisfaction_status) for o in structural]}"

    assert refined, "改类而来的 node 主义务没被拦 ⇒ 改动没生效"
    assert all((o.closure_status, o.satisfaction_status) == ("open", "unknown")
               for o in refined)


def test_licence_predicate_still_a_no_op_without_artifact_state_facts():
    """无产物态事实时，新参数**不得**改变任何行为（对既有判定零影响的前提）。"""
    plain = make_fact("F-PLAIN", slot_id="defect.class.present", value=True,
                      value_type="boolean", qualifiers={})
    for flag in (False, True):
        assert od.artifact_state_licenses_verdict("artifact", [plain],
                                                  kind_from_action_refinement=flag) is True
        assert od.artifact_state_licenses_verdict("action", [plain],
                                                  kind_from_action_refinement=flag) is True


def test_refined_kind_domain_intersects_licensed_set_only_at_artifact():
    """影响面精确性：`refine_action_kind` 的值域 ∩ 许可集合 == {"artifact"}。

    锁住「本改动影响面 ＝ 改类成 artifact 的那些，不多不少」这条推理。
    若将来有人给 `refine_action_kind` 加一个返回 `trigger`/`scope` 的分支，
    本测会红——那时必须重新审视 `kind_from_action_refinement=True` 那个硬传值。
    """
    domain = set()
    for node_kind in ("obligation", "prohibition", "escalation"):
        for action in ("submit_x", "deliver_x", "include_x", "report_x",
                       "conduct_supervision_x", "x_supervision", "x_method",
                       "perform_detailed_investigation_method", "conduct_validation_test",
                       "", "anything_else"):
            domain.add(od.refine_action_kind(node_kind, action))
    assert domain <= set(get_args(ObligationKind)), f"产出了非法 kind：{domain}"
    assert domain & od.ARTIFACT_STATE_LICENSED_KINDS == {"artifact"}, (
        f"值域与许可集合的交集变了：{domain & od.ARTIFACT_STATE_LICENSED_KINDS}")


# ===================================================================== #
# 三、反向变异验证
# ===================================================================== #
def test_mutation_removing_the_switch_makes_the_refusal_fail(monkeypatch):
    """摘掉新参数的效果 ⇒ 第一组断言必须失败。

    没有变异验证的防御性测试可能什么都没测（本项目既有教训：
    「闸显示 Passed ≠ 规则被检查了」）。这里在**进程内**把谓词换回改动前的语义，
    不碰磁盘文件。
    """
    def _old_gate(kind, facts, *, kind_from_action_refinement=False):
        # 改动前的实现：忽略来源，只看 kind 在不在许可集合里。
        if kind in od.ARTIFACT_STATE_LICENSED_KINDS:
            return True
        return not any(od.is_artifact_state_fact(f) for f in facts)

    monkeypatch.setattr(od, "artifact_state_licenses_verdict", _old_gate)
    result = run_closure(make_rule_slice([_card("submit_compliant_proposal", "RC.mut")]),
                         make_fact_pack([_art_fact(True)]))
    refused = [o for o in _obls(result) if o.open_reason_code == REASON]
    node_level = [o for o in refused if o.kind == "artifact"]
    assert not node_level, (
        "摘掉开关后 node 通道仍被拦 ⇒ 本测没有测到目标分支，"
        "断言写错了或拦截来自别处")
