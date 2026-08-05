"""🔴 消费者端到端门 —— unknown 归因必须真的送到专业人员眼前。

验收标准是用户原话「**也不能无故 unknown**」⇒「**有故 unknown 须说清为什么**」。
说给谁看？给使用系统的专业人员看。归因活在 `ClosureValidationResult` 里不算数——
必须在他实际读到的报告里出现，**且两条报告入口说的是同一件事**。

五类样例 × 三条路径，每格都验：

| 类别 | cause_code / responsibility |
|---|---|
| 专业人员输入 | `professional_input_required`（构造样例 + 责任登记表真实路径） |
| 缺满足通道（透传验证器码） | `missing_satisfaction_binding` |
| 产物未建模（透传验证器码） | `artifact_not_modeled_upstream` |
| 卡级触发器堵死 | `upstream_trigger_blocked` |
| 别名命中 | 卡侧槽名经别名归一后命中世界槽池（**不得**误判 `slot_not_supplied`） |
| 限定符冲突 | `qualifier_mismatch` |
| 继承依赖 | `inherited_from_root` |

三条路径 = ①结果 JSON（含守恒门往返）②确定性报告（旧入口 `write_report`）
③模型报告组合路径（`render_contract_v2_report` + 模型分析节）。
"""

from __future__ import annotations

import json

import pytest

from evo_agent_baseline.agent import report_writer as rw
from evo_agent_baseline.closure import unknown_attribution as ua
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)
from evo_agent_baseline.contracts import ClosureValidationResult, UnknownAttribution

MODEL_TEXT = "## 模型分析\n\n模型在此复述归因要点。\n"


def _srole(ref, slot, *, role="evidence", required=True, qualifiers=None):
    return {
        "slot_ref_id": ref,
        "slot_id": slot,
        "roles": [role],
        "required": required,
        "qualifiers": qualifiers or {},
    }


def _evreqs(matching):
    return {"for_matching": matching, "for_submission": [], "for_completion": []}


def _evreq(rid, *, slot_ref_ids):
    return {
        "evidence_requirement_id": rid,
        "kind": "evidence",
        "required": True,
        "description": "",
        "artifact_ids": [],
        "slot_ref_ids": slot_ref_ids,
        "measure_keys": [],
        "required_field_groups": [],
    }


# ===================================================================== #
# 五类样例
# ===================================================================== #
def _case_missing_satisfaction_binding():
    """缺满足通道：真·义务图节点、没有任何事实槽 → 透传验证器码。"""
    card = make_rule_card(
        "RC.gate.noslot",
        family_id="FAM.gate1",
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N.gate.noslot",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                }
            ],
            "edges": [],
        },
    )
    return make_rule_slice([card]), make_fact_pack([]), "missing_satisfaction_binding"


def _case_artifact_not_modeled_upstream():
    """产物未建模：工作流产物派生、无义务图节点、只带文件句柄。"""
    card = make_rule_card(
        "RC.gate.nonslot",
        family_id="FAM.gate1b",
        workflow_operands={
            "primary_actor": "ri",
            "primary_action": "submit_form",
            "recipients": [],
            "artifacts": [
                {
                    "artifact_id": "A.gate",
                    "artifact_type": "",
                    "artifact_key": "proposal.supervision",
                }
            ],
            "deadlines": [],
            "audiences": [],
            "method_keys_allowed": [],
        },
    )
    return make_rule_slice([card]), make_fact_pack([]), "artifact_not_modeled_upstream"


def _case_upstream_trigger_blocked():
    """卡级触发器堵死：触发槽有候选但限定符全灭 → 聚合 blocked，下游从未求值。"""
    card = make_rule_card(
        "RC.gate.blocked",
        family_id="FAM.gate.blocked",
        trigger_conditions={
            "logic": "all",
            "items": [
                {
                    "condition_id": "C.block",
                    "predicate_kind": "slot",
                    "slot_ref_id": "SR.tb",
                    "operator": "==",
                    "expected_value": True,
                }
            ],
        },
        slot_role_map=[
            _srole(
                "SR.tb",
                "defect.class.present",
                role="trigger",
                required=True,
                qualifiers={"defect_class_key": "crack"},
            ),
            _srole("SR.eb", "evidence.gate.block"),
        ],
        evidence_requirements=_evreqs([_evreq("ER.b", slot_ref_ids=["SR.eb"])]),
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N.gate.blocked",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                    "trigger_condition_ids": ["C.block"],
                }
            ],
            "edges": [],
        },
    )
    return (
        make_rule_slice([card]),
        make_fact_pack(
            [
                make_fact(
                    "F.block",
                    slot_id="defect.class.present",
                    value=True,
                    value_type="boolean",
                    qualifiers={"defect_class_key": "corrosion"},
                )
            ]
        ),
        "upstream_trigger_blocked",
    )


def _case_qualifier_mismatch():
    """限定符冲突：世界有 defect.class.present，但限定符值对不上。"""
    card = make_rule_card(
        "RC.gate.qual",
        family_id="FAM.gate2",
        slot_role_map=[
            _srole(
                "SR.q",
                "defect.class.present",
                qualifiers={"defect_class_key": "hollowing"},
            )
        ],
        evidence_requirements=_evreqs([_evreq("ER.q", slot_ref_ids=["SR.q"])]),
    )
    facts = [
        make_fact(
            "F.q",
            slot_id="defect.class.present",
            value=True,
            value_type="boolean",
            qualifiers={"defect_class_key": "spalling"},
        )
    ]
    return make_rule_slice([card]), make_fact_pack(facts), "qualifier_mismatch"


def _case_alias_hit():
    """别名命中：卡侧槽名 `repair.prescribed.started` 经别名表归一到世界侧
    `procedure.repair.prescribed.started`。

    🔴 这一类的意义是**反证**：按裸 `slot_id` 比对会把它误判成
    `slot_not_supplied`（"世界侧未供给"），而世界其实供了——今天就因为这个
    误判过一次。归因必须经 `canonical_slot()` 归一后再比。
    """
    card = make_rule_card(
        "RC.gate.alias",
        family_id="FAM.gate3",
        slot_role_map=[
            _srole(
                "SR.a",
                "repair.prescribed.started",
                qualifiers={"component_type_key": "external_component"},
            )
        ],
        evidence_requirements=_evreqs([_evreq("ER.a", slot_ref_ids=["SR.a"])]),
    )
    rule_slice = make_rule_slice(
        [card],
        retrieval_policy={
            "projection_runtime_mapping_v1": {
                "slot_aliases": {
                    "repair.prescribed.started": [
                        "procedure.repair.prescribed.started"
                    ]
                }
            }
        },
    )
    facts = [
        make_fact(
            "F.a",
            slot_id="procedure.repair.prescribed.started",
            value=True,
            value_type="boolean",
            qualifiers={"component_type_key": "external_wall"},
        )
    ]
    return rule_slice, make_fact_pack(facts), "qualifier_mismatch"


def _case_inherited():
    """继承依赖：触发器槽缺失 → 下游义务继承根因。"""
    card = make_rule_card(
        "RC.gate.inherit",
        family_id="FAM.gate4",
        trigger_conditions={
            "logic": "all",
            "items": [
                {
                    "condition_id": "C1",
                    "predicate_kind": "slot",
                    "slot_ref_id": "SR.t",
                    "operator": "==",
                    "expected_value": True,
                }
            ],
        },
        slot_role_map=[
            _srole("SR.t", "scope.gate.absent", role="trigger", required=False),
            _srole("SR.e", "evidence.gate.absent"),
        ],
        evidence_requirements=_evreqs([_evreq("ER.i", slot_ref_ids=["SR.e"])]),
    )
    return make_rule_slice([card]), make_fact_pack([]), "inherited_from_root"


ALL_WORLD_CASES = [
    ("缺满足通道", _case_missing_satisfaction_binding),
    ("产物未建模", _case_artifact_not_modeled_upstream),
    ("触发器堵死", _case_upstream_trigger_blocked),
    ("限定符冲突", _case_qualifier_mismatch),
    ("别名命中", _case_alias_hit),
    ("继承依赖", _case_inherited),
]


# ===================================================================== #
# 三条路径
# ===================================================================== #
def _path_result_json(result) -> str:
    """路径①：结果 JSON —— 往返一次 model_validate，顺带过守恒门。"""
    dumped = json.loads(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
    reloaded = ClosureValidationResult.model_validate(dumped)
    assert reloaded.unknown_attribution_by_obligation_id is not None
    return json.dumps(
        dumped["unknown_attribution_by_obligation_id"], ensure_ascii=False
    )


def _path_deterministic_report(result) -> str:
    """路径②：确定性报告（旧入口 `write_report`）。"""
    return rw.write_report(result)["content"]


def _path_model_report(result) -> str:
    """路径③：模型报告组合路径（契约化入口 + 模型分析节）。"""
    return rw.render_contract_v2_report(
        result,
        world_id="W",
        building_id="B",
        generated_at="2026-07-27T00:00:00Z",
        analysis_markdown=MODEL_TEXT,
        analysis_is_llm=True,
        contract_version=4,
    )


ALL_PATHS = (
    ("结果JSON", _path_result_json),
    ("确定性报告", _path_deterministic_report),
    ("模型报告组合", _path_model_report),
)


@pytest.mark.parametrize("case_name,case_fn", ALL_WORLD_CASES, ids=[c[0] for c in ALL_WORLD_CASES])
@pytest.mark.parametrize("path_name,path_fn", ALL_PATHS, ids=[p[0] for p in ALL_PATHS])
def test_consumer_gate_every_case_through_every_path(
    case_name, case_fn, path_name, path_fn
):
    """五类 × 三条路径的 5×3 格（另加「专业人员输入」构造样例，见下）。"""
    rule_slice, fact_pack, expected_code = case_fn()
    result = run_closure(rule_slice, fact_pack)
    mapping = result.unknown_attribution_by_obligation_id
    assert mapping, f"[{case_name}] 场景必须产出 unknown，否则本格无效"

    codes = {a.cause_code for a in mapping.values()}
    assert expected_code in codes, f"[{case_name}] 期望 {expected_code}，实得 {codes}"

    rendered = path_fn(result)
    assert expected_code in rendered, f"[{case_name}/{path_name}] 报告里看不到 cause_code"
    # 逐项解释必须随行——只丢一个码等于没说清。
    sample = next(a for a in mapping.values() if a.cause_code == expected_code)
    if path_name != "结果JSON":
        assert rw._UNKNOWN_CAUSE_LABELS[expected_code] in rendered
        assert "这些项为什么还没有结论" in rendered
    else:
        assert sample.explanation[:20] in rendered


def test_alias_hit_is_not_misjudged_as_not_supplied():
    """别名命中反证：世界供了（别名下的）数据，就**不许**说"世界侧未供给"。"""
    rule_slice, fact_pack, _ = _case_alias_hit()
    result = run_closure(rule_slice, fact_pack)
    mapping = result.unknown_attribution_by_obligation_id
    offenders = [
        a for a in mapping.values() if a.cause_code == "slot_not_supplied"
    ]
    assert not offenders, (
        "别名归一失效：卡侧 repair.prescribed.started 被判成世界未供给，"
        f"实际世界有 procedure.repair.prescribed.started —— {offenders}"
    )


# ===================================================================== #
# 第五类：专业人员输入
# ===================================================================== #
@pytest.mark.parametrize("path_name,path_fn", ALL_PATHS, ids=[p[0] for p in ALL_PATHS])
def test_professional_input_required_renders_when_constructed(path_name, path_fn):
    """构造样例：责任二分表与消费者资料条目都带 professional_action。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    action = "提交现场量测记录，并附标注展示面积、被遮盖外墙范围的相片或位置图。"
    slot = "scope.component.covered_by_large_attached_signboard"
    forged = {
        oid: UnknownAttribution(
            obligation_id=oid,
            responsibility="professional_input_required",
            cause_code=a.cause_code,
            explanation="请补录该部位的缺陷类别记录后重跑。",
            root_dependency_ids=list(a.root_dependency_ids),
            policy_version="constructed_sample",
            responsible_slot_id=slot,
            professional_action=action,
        )
        for oid, a in result.unknown_attribution_by_obligation_id.items()
    }
    result = ClosureValidationResult.model_validate(
        result.model_copy(update={"unknown_attribution_by_obligation_id": forged}).model_dump()
    )
    rendered = path_fn(result)
    if path_name == "结果JSON":
        assert "professional_input_required" in rendered
        assert action in rendered
    else:
        # 责任表必须把这 n 条记在「需要专业人员提供」那一行，且系统侧记 0。
        assert f"| 需要专业人员提供 | {len(forged)} |" in rendered
        assert "| 系统未能确定 | 0 |" in rendered
        assert "请补录该部位的缺陷类别记录后重跑。" in rendered
        assert "需要你补充的资料" in rendered
        assert action in rendered
        assert slot not in rendered


def test_non_professional_world_cases_stay_system_unresolved():
    """世界样例不用白名单四槽时，即使登记表已接线，仍全落 system_unresolved。

    证明：接上登记表 ≠ 随便把 unknown 推给专业人员；只有命中白名单槽才翻责任。
    """
    for _case_name, case_fn in ALL_WORLD_CASES:
        rule_slice, fact_pack, _ = case_fn()
        result = run_closure(rule_slice, fact_pack)
        assert result.machine_readable_report["unknown_attribution_audit"][
            "responsibility_registry_present"
        ] is True
        assert all(
            a.responsibility == "system_unresolved"
            for a in result.unknown_attribution_by_obligation_id.values()
        )


# ===================================================================== #
# 报告层的三条硬约束
# ===================================================================== #
def test_report_layer_fails_loudly_on_inconsistent_mapping():
    """映射不全 → **显式失败**，不许猜、不许静默降级成不分家 unknown。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    broken = result.model_construct(
        **{
            **result.__dict__,
            "unknown_attribution_by_obligation_id": {},  # 绕过契约层校验器
        }
    )
    with pytest.raises(rw.UnknownAttributionRenderError):
        rw.render_unknown_attribution_section(broken)


def test_none_mapping_says_so_explicitly_instead_of_silent_fallback():
    """`None`（旧产物）→ 显式说明"本次未计算归因"，不静默按旧格式渲染。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    legacy = ClosureValidationResult.model_validate(
        {
            **result.model_dump(mode="json"),
            "unknown_attribution_by_obligation_id": None,
        }
    )
    for _name, path_fn in ALL_PATHS[1:]:
        rendered = path_fn(legacy)
        assert "未计算" in rendered
        assert "unknown 归因" in rendered


def test_report_layer_does_not_compute_attribution_itself():
    """报告层只渲染映射：改映射文本，报告必须跟着变（证明没有自算旁路）。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    sentinel = "哨兵解释文本ZZZ"
    patched = {
        oid: a.model_copy(update={"explanation": sentinel})
        for oid, a in result.unknown_attribution_by_obligation_id.items()
    }
    result2 = ClosureValidationResult.model_validate(
        result.model_copy(update={"unknown_attribution_by_obligation_id": patched}).model_dump()
    )
    for _name, path_fn in ALL_PATHS[1:]:
        assert sentinel in path_fn(result2)


def test_inherited_items_are_aggregated_by_root_not_listed_one_by_one():
    """继承项按根聚合：列根义务 + 受影响条数，不逐条列。"""
    rule_slice, fact_pack, _ = _case_inherited()
    result = run_closure(rule_slice, fact_pack)
    rendered = _path_deterministic_report(result)
    assert "根义务" in rendered and "受影响义务" in rendered
    assert "解决根义务即连带解开" in rendered


def test_model_text_cannot_replace_authoritative_attribution():
    """模型分析节与权威归因节并存：模型可复述，权威文本仍在程序骨架里。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    rendered = _path_model_report(result)
    assert "模型在此复述归因要点" in rendered
    assert "本节由系统确定性渲染" in rendered
    assert rendered.index("本节由系统确定性渲染") < rendered.index("模型在此复述归因要点")


def test_both_report_entries_agree_on_counts():
    """两条报告入口对同一结果的归因计数必须一致（共用同一渲染实现）。"""
    rule_slice, fact_pack, _ = _case_qualifier_mismatch()
    result = run_closure(rule_slice, fact_pack)
    n = len(result.unknown_attribution_by_obligation_id)
    for _name, path_fn in ALL_PATHS[1:]:
        assert f"unknown 共 {n} 条" in path_fn(result)


# ===================================================================== #
# 原因分节的公共后缀去重（2026-07-29）
# ===================================================================== #
def test_longest_common_suffix_is_correct():
    """🔴 这个函数第一版有索引 bug，**看起来对、实测省 0 KB**。

    bug：`ref[n - 1 - m]` 里 `n` 每轮都在缩，第二轮起就从错误位置比，
    于是任何 3 条以上的输入公共后缀恒被算成 0。
    单元层完全无感（两条输入时 n 恰好没缩，照样过），
    **只有在真实数据上量字节数才暴露**——所以这条测试至少要有 3 条输入。
    """
    from evo_agent_baseline.agent.report_writer import _longest_common_suffix as lcs

    assert lcs(["abcXYZ", "defXYZ", "gXYZ"]) == "XYZ"      # ≥3 条，能抓到那个 bug
    assert lcs(["xxTAIL", "yTAIL", "zzzTAIL", "TAIL"]) == "TAIL"
    assert lcs(["aQ", "bR"]) == ""                          # 无公共后缀
    assert lcs(["same", "same"]) == "same"
    assert lcs(["only"]) == ""                              # 少于 2 条不抽
    assert lcs([]) == ""


def test_cause_group_dedups_shared_explanation_tail():
    """同一原因码下的样板文字只出现一次，且行内不再重复它。"""
    from types import SimpleNamespace

    from evo_agent_baseline.agent.report_writer import _render_cause_group

    tail = (
        "候选事实多于一条，系统拒绝任取其一下结论（避免误判）。"
        "要由维护方收紧限定符或绑定规则，消歧后再判。"
        "**不需要你补录资料** —— 这是系统侧缺口，已记录待维护方跟进。"
    )
    items = [
        (f"O{i}", SimpleNamespace(explanation=f"这条义务（action / a{i}）{tail}"))
        for i in range(3)
    ]
    by_id = {
        f"O{i}": SimpleNamespace(source_rule_card_id=f"rc.mbis.x.y.z.s1.c0{i}")
        for i in range(3)
    }
    out = "\n".join(_render_cause_group(items, by_id, max_rows=10))

    assert out.count(tail) == 1, "样板文字应当只出现一次（在表上方），行内不得重复"
    for i in range(3):
        assert f"a{i}" in out, f"每组各自变化的部分（a{i}）必须保留——去重不是截断"
