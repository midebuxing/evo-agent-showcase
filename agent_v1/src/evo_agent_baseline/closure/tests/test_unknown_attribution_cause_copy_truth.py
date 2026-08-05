"""§2.2 硬要求：消费者看到的 `explanation` 里，可机械核验的事实性断言必须成立。

常驻测试两层：
1. 合成场景：覆盖所有当前会产出的码（含透传与分流）。
2. 真实批产物：对 `phase_d_cards72_seed301_20260728` 用**新策略重算**归因后，
   逐码断言 explanation 事实谓词成立率 = 100%。

🔴 本文件测的是 **`attr.explanation` 文本**（消费者真看到的），不是人工 claim 字符串，
也不是把判据本身再抄一遍。文案写得太满、比判据说得多 → 谓词过不了 →
必须改文案（不许给不可核验措辞开豁免）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import pytest

from evo_agent_baseline.agent import report_writer as rw
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
    make_rule_slice,
    run_closure,
)
from evo_agent_baseline.closure.unknown_attribution import (
    _PASSTHROUGH_CAUSE_CODES,
    _PASSTHROUGH_EXPLANATIONS,
)

# --------------------------------------------------------------------------- #
# 每个 cause_code → 若干（说明, 谓词(obligation_dict, attr_dict)）
# 谓词必须读 `a["explanation"]`，且不得只是该码判据的复述。
# --------------------------------------------------------------------------- #
ExplanationClaim = Tuple[str, Callable[[Dict[str, Any], Dict[str, Any]], bool]]


def _expl(a: Dict[str, Any]) -> str:
    return str(a.get("explanation") or "")


def _vcode(o: Dict[str, Any]) -> str | None:
    return o.get("open_reason_code") or o.get("blocked_reason_code")


def _has_slot(o: Dict[str, Any]) -> bool:
    return bool(o.get("slot_ids")) or bool(o.get("slot_ref_ids"))


def _kind_prefix(o: Dict[str, Any]) -> str:
    kind = o.get("kind") or ""
    action = o.get("action")
    if action:
        return f"这条义务（{kind} / {action}）"
    return f"这条义务（{kind}）"


def _passthrough_claims(code: str) -> List[ExplanationClaim]:
    body = _PASSTHROUGH_EXPLANATIONS[code]
    return [
        (
            f"explanation 含验证器原因码反引号 `{code}`（动态嵌入，不是判据复述）",
            lambda o, a, c=code: f"`{c}`" in _expl(a),
        ),
        (
            "explanation 含透传主体文案（与 _PASSTHROUGH_EXPLANATIONS 一致）",
            lambda o, a, b=body: b in _expl(a),
        ),
        (
            "explanation 嵌入的 kind/action 前缀与义务字段一致",
            lambda o, a: _kind_prefix(o) in _expl(a),
        ),
        (
            "explanation 含「不需要你补录资料」且责任仍是系统侧",
            lambda o, a: ("不需要你补录资料" in _expl(a))
            and a.get("responsibility") == "system_unresolved",
        ),
    ]


CAUSE_EXPLANATION_CLAIMS: Dict[str, List[ExplanationClaim]] = {
    "inherited_from_root": [
        (
            "explanation 中的根依赖条数 = len(root_dependency_ids)",
            lambda o, a: (
                f"未闭合根依赖 {len(a.get('root_dependency_ids') or [])} 条"
                in _expl(a)
            ),
        ),
        (
            "explanation 声明根因解决后自动重算",
            lambda o, a: "根因解决后本条会自动重算" in _expl(a),
        ),
        (
            "explanation 未声称「本条自身无病」（该断言无法从归因输入机械核验）",
            lambda o, a: "本条自身无病" not in _expl(a),
        ),
        (
            "root_dependency_ids 非空（文案声称有可追溯根依赖）",
            lambda o, a: bool(a.get("root_dependency_ids")),
        ),
    ],
    "upstream_trigger_blocked": [
        (
            "explanation 嵌入的 kind/action 前缀与义务字段一致",
            lambda o, a: _kind_prefix(o) in _expl(a),
        ),
        (
            "explanation 声明本条从未进入自身求值",
            lambda o, a: "从未进入" in _expl(a),
        ),
        (
            "explanation 承认在触发器可求值前无法判断本条是否还缺别的",
            lambda o, a: "无法判断本条自身是否还缺别的东西" in _expl(a),
        ),
        (
            "explanation 未过度声称「不需要你补录资料」",
            lambda o, a: "不需要你补录资料" not in _expl(a),
        ),
        (
            "explanation 未过度声称「不是这条义务本身缺资料」",
            lambda o, a: "不是这条义务本身缺资料" not in _expl(a),
        ),
    ],
    "no_slot_declared": [
        (
            "explanation 声称是义务图节点行，且义务确有 obligation_node_id",
            lambda o, a: ("是义务图节点行" in _expl(a))
            and bool(o.get("obligation_node_id")),
        ),
        (
            "explanation 声称未绑定事实槽，且义务两侧槽句柄皆空",
            lambda o, a: ("没有绑定任何事实槽" in _expl(a)) and (not _has_slot(o)),
        ),
        (
            "explanation 声称验证器未给更具体原因码，且两码皆空",
            lambda o, a: ("验证器未给出更具体的原因码" in _expl(a))
            and (_vcode(o) is None),
        ),
        (
            "explanation 嵌入的 kind/action 前缀与义务字段一致",
            lambda o, a: _kind_prefix(o) in _expl(a),
        ),
        (
            "explanation 含「不需要你补录资料」且责任为系统侧",
            lambda o, a: ("不需要你补录资料" in _expl(a))
            and a.get("responsibility") == "system_unresolved",
        ),
    ],
    "non_slot_handle": [
        (
            "explanation 声称不是义务图节点行，且义务确无 obligation_node_id",
            lambda o, a: ("不是义务图节点行" in _expl(a))
            and (not o.get("obligation_node_id")),
        ),
        (
            "explanation 声称未绑定事实槽，且义务两侧槽句柄皆空",
            lambda o, a: ("未绑定任何事实槽" in _expl(a)) and (not _has_slot(o)),
        ),
        (
            "explanation 声称验证器未给更具体原因码，且两码皆空",
            lambda o, a: ("验证器未给出更具体的原因码" in _expl(a))
            and (_vcode(o) is None),
        ),
        (
            "explanation 声明「不是系统漏查了事实槽」",
            lambda o, a: "不是系统漏查了事实槽" in _expl(a),
        ),
        (
            "explanation 嵌入的 kind/action 前缀与义务字段一致",
            lambda o, a: _kind_prefix(o) in _expl(a),
        ),
    ],
    "qualifier_mismatch": [
        (
            "explanation 声称世界侧有这些槽的数据",
            lambda o, a: "世界侧有这些槽的数据" in _expl(a),
        ),
        (
            "explanation 括号内点名的槽非空（动态嵌入，写死空括号会红）",
            lambda o, a: bool(
                _slots_listed_after(r"世界侧有这些槽的数据（([^）]+)）", _expl(a))
            ),
        ),
        (
            "explanation 归因于系统侧接线问题",
            lambda o, a: "属系统侧接线问题" in _expl(a),
        ),
        (
            "若文案写「不需要专业人员补录」，责任必须是 system_unresolved",
            lambda o, a: (
                a.get("responsibility") == "system_unresolved"
                if "不需要专业人员补录" in _expl(a)
                else True
            ),
        ),
    ],
    "slot_not_supplied": [
        (
            "explanation 声称事实包完全没有这些槽",
            lambda o, a: "本次事实包里完全没有这些槽" in _expl(a),
        ),
        (
            "explanation 括号内点名的槽非空",
            lambda o, a: bool(_slots_listed_after(r"完全没有这些槽（([^）]+)）", _expl(a))),
        ),
        (
            "explanation 归因于世界侧未供给",
            lambda o, a: "世界侧未供给" in _expl(a),
        ),
    ],
    "attribution_input_missing": [
        (
            "explanation 标明是归因层缺口/输入缺失/兜底之一",
            lambda o, a: any(
                marker in _expl(a)
                for marker in (
                    "未能判别原因",
                    "归因输入缺失",
                    "归因未产出",
                    "归因策略没有覆盖这个形态",
                )
            ),
        ),
        (
            "责任仍是系统侧（报警桶不许推给专业人员）",
            lambda o, a: a.get("responsibility") == "system_unresolved",
        ),
    ],
}

for _code in sorted(_PASSTHROUGH_CAUSE_CODES):
    CAUSE_EXPLANATION_CLAIMS[_code] = _passthrough_claims(_code)


def _slots_listed_after(pattern: str, text: str) -> List[str]:
    match = re.search(pattern, text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


# 🔴 锚到 `__file__`，不用相对 cwd（审核门 2026-08-03 实测钉出）：
# 原先写相对路径，从 `agent_v1/` 目录跑整套时直接 FileNotFoundError、
# **且无 skip 守卫**——于是「从哪个目录跑」决定了套件是 786 全绿还是 785+1 红，
# 而失败信息完全看不出根因是 cwd。本项目既有教训：
# 「验证工具把我带到错路径」。
BATCH_ROOT = (
    Path(__file__).resolve().parents[4]
    / "experiments" / "phase_d_cards72_seed301_20260728" / "buildings"
)


def _label_covers_claim(cause_code: str) -> None:
    """标签表必须覆盖每个有谓词的码（聚合表同步门）。"""
    assert cause_code in rw._UNKNOWN_CAUSE_LABELS, (
        f"report_writer 缺标签：{cause_code}"
    )
    # 2026-07-29 修：原文是 `assert ... or True`，**恒真**，看着像闸其实什么都没测
    # （第三方审核抓出）。实测 18 个码在标签表与顺序表里都齐，故这里就该是真断言。
    assert cause_code in rw._UNKNOWN_CAUSE_ORDER, (
        f"report_writer._UNKNOWN_CAUSE_ORDER 缺 {cause_code}——"
        "聚合表会把它排到兜底位置，读者看到的分组顺序与码表不一致"
    )


def _assert_explanation_claims(
    code: str, obl: Dict[str, Any], attr: Dict[str, Any]
) -> None:
    claims = CAUSE_EXPLANATION_CLAIMS[code]
    for claim_text, pred in claims:
        assert pred(obl, attr), (
            f"cause_code={code} explanation 声称「{claim_text}」不成立；\n"
            f"explanation={attr.get('explanation')!r}\n"
            f"obl_keys={{kind={obl.get('kind')}, action={obl.get('action')}, "
            f"trigger_state={obl.get('trigger_state')}, "
            f"open={obl.get('open_reason_code')}, blocked={obl.get('blocked_reason_code')}}}"
        )


def test_every_passthrough_and_core_code_has_structural_claim():
    """码表扩了就必须同步补 explanation 谓词——否则 §2.2 门会漏。"""
    from evo_agent_baseline.contracts import UnknownCauseCode
    import typing

    args = typing.get_args(UnknownCauseCode)
    missing = [c for c in args if c not in CAUSE_EXPLANATION_CLAIMS]
    assert not missing, f"以下 UnknownCauseCode 缺 explanation 谓词：{missing}"
    for code in args:
        assert CAUSE_EXPLANATION_CLAIMS[code], f"{code} 谓词列表为空"
        _label_covers_claim(code)


def test_cause_label_structural_truth_on_synthetic_closure():
    """合成闭包：每个产出的 cause_code 的 explanation 对携带它的义务 100% 满足谓词。"""
    card_trig = make_rule_card(
        "RC.truth.trig",
        family_id="FAM.truth1",
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
            {
                "slot_ref_id": "SR.t",
                "slot_id": "scope.truth.absent",
                "roles": ["trigger"],
                "required": False,
                "qualifiers": {},
            },
            {
                "slot_ref_id": "SR.e",
                "slot_id": "evidence.truth.absent",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {},
            },
        ],
        evidence_requirements={
            "for_matching": [
                {
                    "evidence_requirement_id": "ER1",
                    "kind": "evidence",
                    "required": True,
                    "description": "",
                    "artifact_ids": [],
                    "slot_ref_ids": ["SR.e"],
                    "measure_keys": [],
                    "required_field_groups": [],
                }
            ],
            "for_submission": [],
            "for_completion": [],
        },
    )
    card_node = make_rule_card(
        "RC.truth.node",
        family_id="FAM.truth2",
        obligation_graph={
            "nodes": [
                {
                    "obligation_node_id": "N.truth",
                    "node_kind": "obligation",
                    "actor": "ri",
                    "action": "perform_inspection",
                }
            ],
            "edges": [],
        },
    )
    card_qual = make_rule_card(
        "RC.truth.qual",
        family_id="FAM.truth3",
        slot_role_map=[
            {
                "slot_ref_id": "SR.q",
                "slot_id": "defect.class.present",
                "roles": ["evidence"],
                "required": True,
                "qualifiers": {"defect_class_key": "hollowing"},
            }
        ],
        evidence_requirements={
            "for_matching": [
                {
                    "evidence_requirement_id": "ER.q",
                    "kind": "evidence",
                    "required": True,
                    "description": "",
                    "artifact_ids": [],
                    "slot_ref_ids": ["SR.q"],
                    "measure_keys": [],
                    "required_field_groups": [],
                }
            ],
            "for_submission": [],
            "for_completion": [],
        },
    )
    result = run_closure(
        make_rule_slice([card_trig, card_node, card_qual]),
        make_fact_pack(
            [
                make_fact(
                    "F.truth",
                    slot_id="defect.class.present",
                    value=True,
                    value_type="boolean",
                    qualifiers={"defect_class_key": "spalling"},
                )
            ]
        ),
    )
    mapping = result.unknown_attribution_by_obligation_id
    by_id = {o.obligation_id: o.model_dump(mode="json") for o in result.obligation_set.obligations}
    rates: Dict[str, Tuple[int, int]] = {}
    for oid, attr in mapping.items():
        code = attr.cause_code
        attr_d = attr.model_dump(mode="json")
        _assert_explanation_claims(code, by_id[oid], attr_d)
        n_ok, n_tot = rates.get(code, (0, 0))
        rates[code] = (n_ok + 1, n_tot + 1)
    for code, (n_ok, n_tot) in rates.items():
        assert n_ok == n_tot
        assert n_tot > 0


def test_cause_label_structural_truth_on_batch_after_reattribute():
    """真实 30 栋：读 fact_pack+rule_slice 重建槽池，用新策略归因，逐码 explanation 成立率 100%。"""
    import json
    from collections import defaultdict

    from evo_agent_baseline.contracts import FactPack, Obligation, RuleSlice
    from evo_agent_baseline.closure.fact_binding import FactIndex
    from evo_agent_baseline.closure.unknown_attribution import (
        attribute_unknown_obligations,
        build_slot_ref_bindings,
        build_supplied_slot_pools,
        build_unknown_snapshots,
    )
    from evo_agent_baseline.closure.validator import (
        _measure_aliases_from_policy,
        _slot_aliases_from_policy,
    )

    def _frag(fact):
        q = getattr(fact, "qualifiers", None) or {}
        fid = q.get("fragment_id")
        return str(fid) if fid else None

    rates: Dict[str, list] = defaultdict(lambda: [0, 0])
    total_unknown = 0

    for bld in sorted(BATCH_ROOT.iterdir()):
        runs = list((bld / "runs").glob("*"))
        if not runs:
            continue
        run = runs[0]
        data = json.loads(
            (run / "closure_validation_result.json").read_text(encoding="utf-8")
        )
        fact_pack = FactPack.model_validate_json(
            (run / "fact_pack.json").read_text(encoding="utf-8")
        )
        rule_slice = RuleSlice.model_validate_json(
            (run / "rule_slice.json").read_text(encoding="utf-8")
        )
        fact_index = FactIndex(
            fact_pack,
            slot_aliases=_slot_aliases_from_policy(rule_slice),
            measure_aliases=_measure_aliases_from_policy(rule_slice),
        )
        obligations = [
            Obligation.model_validate(o)
            for o in data["machine_readable_report"]["obligations"]
        ]
        snaps, status_by_id, deps_by_id = build_unknown_snapshots(
            obligations,
            canonical_slot=fact_index.canonical_slot,
            slot_ref_bindings=build_slot_ref_bindings(rule_slice),
        )
        pools = build_supplied_slot_pools(
            fact_pack.facts,
            canonical_slot=fact_index.canonical_slot,
            fragment_of_fact=_frag,
        )
        new_map = attribute_unknown_obligations(
            snaps,
            closure_status_by_obligation_id=status_by_id,
            dependency_ids_by_obligation_id=deps_by_id,
            supplied_slot_pools=pools,
            responsibility_registry=None,
        )
        obl_by_id = {o.obligation_id: o for o in obligations}
        total_unknown += len(new_map)
        for oid, attr in new_map.items():
            code = attr.cause_code
            _assert_explanation_claims(
                code,
                obl_by_id[oid].model_dump(mode="json"),
                attr.model_dump(mode="json"),
            )
            rates[code][0] += 1
            rates[code][1] += 1

    assert total_unknown == 108294, f"总数不守恒：{total_unknown}"
    for code, (n_ok, n_tot) in sorted(rates.items()):
        assert n_ok == n_tot, f"{code} 成立率 {n_ok}/{n_tot} < 100%"


def test_explanation_claim_catches_overclaim_mutation():
    """变异闸：把 upstream 文案改回过度声称 → 谓词必须变红。

    证明本门盯的是 explanation 文本，不是判据复述（判据仍是 trigger_state==blocked）。
    """
    fake_obl = {
        "kind": "action",
        "action": "inspect",
        "trigger_state": "blocked",
        "obligation_node_id": "N1",
        "slot_ids": [],
        "slot_ref_ids": [],
    }
    # 过度声称版（审核抓过的旧措辞）
    bad_attr = {
        "cause_code": "upstream_trigger_blocked",
        "responsibility": "system_unresolved",
        "explanation": (
            "这条义务（action / inspect）所在卡的触发条件未能求值（堵死），"
            "本条因此从未进入自身求值。"
            "不是这条义务本身缺资料；不需要你补录资料。"
        ),
        "root_dependency_ids": [],
    }
    claims = CAUSE_EXPLANATION_CLAIMS["upstream_trigger_blocked"]
    failures = [text for text, pred in claims if not pred(fake_obl, bad_attr)]
    assert failures, "过度声称文案必须至少撞红一条谓词"
    assert any("不需要你补录资料" in f or "本身缺资料" in f for f in failures)


# ===================================================================== #
# DEBT-079：跨批对账锚（内容哈希不含 run_id）
# ===================================================================== #
def _fp(run_id: str, value: str = "true"):
    from evo_agent_baseline.contracts import FactAtom, FactPack

    # 字段照真实产物的形状填齐（`FactAtom` 有 13 个必填，缺一 pydantic 就拒）
    atom = FactAtom(
        fact_id="F1", world_id="W1", building_id="B1",
        carrier_type="condition", carrier_id="FRG-1", target_ref=None,
        slot_id="defect.class.present", measure_key=None,
        value_json=value, value_type="boolean", unit=None,
        source_path="test", source_node_id="N1",
        qualifiers={"fragment_id": "FRG-1"},
    )
    return FactPack(
        run_id=run_id, world_id="W1", building_id="B1", facts=[atom],
        slot_index={"defect.class.present": ["F1"]},
        carrier_index={"FRG-1": ["F1"]}, measure_index={}, source_tables=[],
    )


def test_content_hash_ignores_run_id_but_not_content():
    """🔴 DEBT-079：`fact_pack_hash` 含 `run_id` ⇒ 跨运行永远不等，当不了对账锚。

    实证（批 D vs 批 E，同池同库同档位）：两批事实包逐字段比对**只有 `run_id` 不同**，
    而 30/30 栋 `fact_pack_hash` **全部不同**——「事实包没变」这件事
    此前没有任何落盘哈希能证明。新加的内容哈希实测 30/30 相等。

    本测试锁两条，缺一不可：
    1. 只有 `run_id` 不同 ⇒ 内容哈希**必须相等**（否则锚没用）；
    2. 事实值不同 ⇒ 内容哈希**必须不等**（否则锚是假的，什么都证明不了）。
    """
    from evo_agent_baseline.closure.validator import (
        compute_fact_pack_content_hash,
        compute_fact_pack_hash,
    )

    a = _fp("CAR-20260101T000000-aaaaaaaa")
    b = _fp("CAR-20991231T235959-zzzzzzzz")          # 只换 run_id
    c = _fp("CAR-20260101T000000-aaaaaaaa", "false")  # 只换事实值

    assert compute_fact_pack_content_hash(a) == compute_fact_pack_content_hash(b), (
        "只有 run_id 不同，内容哈希却不等——锚失效"
    )
    assert compute_fact_pack_content_hash(a) != compute_fact_pack_content_hash(c), (
        "事实值都变了内容哈希还相等——锚是假的"
    )
    # 老哈希的病：同内容不同 run_id 就不等（这正是 DEBT-079 记的现象，锁住不让它悄悄"修好"）
    assert compute_fact_pack_hash(a) != compute_fact_pack_hash(b), (
        "老哈希若变成不含 run_id，说明有人改了 spec 口径而没同步 DEBT-079"
    )
