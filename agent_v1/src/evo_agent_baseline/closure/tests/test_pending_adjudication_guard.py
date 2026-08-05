# -*- coding: utf-8 -*-
"""S3 甲′待裁保护层（决策门 2026-08-02）。

面：①候选在即转新码——歧义形状（150 条锚）与单行一致形状（§6.1.3 的
123 true→satisfied / 29 false→satisfied 锚）都不得再产旧出口；
②位置在候选缺失之后（missing 仍 missing_fact）；③开关关闭逐位不变；
④登记外绑定不受待裁层影响；⑤节点满足路径同护（30 条 §2.1.3(b) 锚）。
"""
from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import (
    _evaluate_node_slot_binding,
    evaluate_slot_role,
)
from evo_agent_baseline.closure.schema import ObligationNodeDTO
from .fixtures import BUILDING_ID, make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R", "world_id": "W", "building_id": BUILDING_ID}
SLOT = "supervision.record.completed"


def _slot_ref():
    return {"slot_ref_id": "RC.t.c01.sr01", "slot_id": SLOT,
            "roles": ["evidence"], "required": True, "qualifiers": {}}


def _frag(fid, value):
    return make_fact(fid, slot_id=SLOT, value=value, value_type="boolean",
                     carrier_type="sidecar_entry", carrier_id=f"FRG-{fid}")


def _pend(monkeypatch, card, *, registered=True):
    import evo_agent_baseline.closure.obligation_deriver as od
    key = (card.rule_card_id, "RC.t.c01.sr01")
    monkeypatch.setattr(od, "PENDING_ADJUDICATION_BINDINGS",
                        frozenset({key}) if registered else frozenset())


def _eval(monkeypatch, facts, *, enabled=True, registered=True):
    card = make_rule_card()
    _pend(monkeypatch, card, registered=registered)
    idx = FactIndex(make_fact_pack(facts))
    return evaluate_slot_role(card, _slot_ref(), idx, True, META,
                              authorized_scope_selection=enabled)


def test_ambiguous_shape_converts_to_new_code(monkeypatch):
    """歧义形状（150 锚）：不再 blocked/ambiguous，转 open+新码。"""
    obl = _eval(monkeypatch, [_frag("a", True), _frag("b", False)])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert "pending_adjudication_guard" in str(obl.notes or "")


def test_single_false_fragment_converts_not_satisfied(monkeypatch):
    """§6.1.3 现存假实判形状（29 锚）：单行 false 一致绑定不再存在即满足。"""
    obl = _eval(monkeypatch, [_frag("a", False)])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
    assert obl.satisfaction_status == "unknown"


def test_single_true_fragment_converts_too(monkeypatch):
    """123 true→satisfied 锚同样转轨（待裁前一律不产实判）。"""
    obl = _eval(monkeypatch, [_frag("a", True)])
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"


def test_missing_candidates_stays_missing_fact(monkeypatch):
    """位置在候选缺失检查之后：无候选仍 missing_fact。"""
    obl = _eval(monkeypatch, [])
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "missing_fact"


def test_switch_off_bitwise_unchanged(monkeypatch):
    obl = _eval(monkeypatch, [_frag("a", False)], enabled=False)
    assert obl.satisfaction_status == "satisfied"   # 旧病原样（关闭态不改行为）
    obl2 = _eval(monkeypatch, [_frag("a", True), _frag("b", False)],
                 enabled=False)
    assert obl2.blocked_reason_code == "ambiguous_fact_binding"


def test_unregistered_binding_untouched(monkeypatch):
    obl = _eval(monkeypatch, [_frag("a", True), _frag("b", False)],
                registered=False)
    assert obl.blocked_reason_code == "ambiguous_fact_binding"


def test_registry_fingerprints_match_live_pack():
    """指纹恒等报警面（S3 审核门欠项）：7 行卡指纹须与磁盘卡包实算恒等——
    卡改动 ⇒ 本测试红 ⇒ 触发重裁（**不是**运行时自动解除保护）。"""
    import pathlib
    from evo_agent_baseline.closure.applicability_v3 import (
        rulecard_content_digests,
    )
    from evo_agent_baseline.closure.pending_adjudication_registry import (
        PENDING_ADJUDICATION_ROWS,
    )
    repo = pathlib.Path(__file__).resolve().parents[5]
    _, shas = rulecard_content_digests(repo)
    assert shas, "卡包不可读"
    mismatch = [r["rule_card_id"] for r in PENDING_ADJUDICATION_ROWS
                if shas.get(r["rule_card_id"]) != r["card_content_sha256"]]
    assert mismatch == [], f"待裁卡指纹漂移（须重裁，勿改本测试了事）: {mismatch}"


def test_fingerprint_mismatch_does_not_remove_protection(monkeypatch):
    """变异面：篡改登记行指纹——保护键集**不变**（失配不解除保护，
    解除=放开实判是危险方向；报警由上面的恒等测试承担）。"""
    from evo_agent_baseline.closure import pending_adjudication_registry as pr
    tampered = tuple(dict(r, card_content_sha256="0" * 64)
                     for r in pr.PENDING_ADJUDICATION_ROWS)
    monkeypatch.setattr(pr, "PENDING_ADJUDICATION_ROWS", tampered)
    rebuilt = frozenset((r["rule_card_id"], r["slot_ref_id"]) for r in tampered)
    assert rebuilt == pr.PENDING_ADJUDICATION_BINDINGS   # 键集与指纹无关
    # 端到端：指纹全坏时护栏照常转轨。
    card = make_rule_card()
    _pend(monkeypatch, card)
    idx = FactIndex(make_fact_pack([_frag("a", False)]))
    obl = evaluate_slot_role(card, _slot_ref(), idx, True, META,
                             authorized_scope_selection=True)
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"


def test_node_path_protected_too(monkeypatch):
    """§2.1.3(b) 节点满足路径 30 条锚：同一保护，false 不产 violated。"""
    card = make_rule_card()
    _pend(monkeypatch, card)
    node = ObligationNodeDTO.from_dict({
        "obligation_node_id": "n1", "node_kind": "duty",
        "actor": "ri", "action": "supervise",
    })
    idx = FactIndex(make_fact_pack([_frag("a", False)]))
    obl = _evaluate_node_slot_binding(
        card, node, "action", _slot_ref(), idx, META,
        authorized_scope_selection=True)
    assert obl.closure_status == "open"
    assert obl.open_reason_code == "binding_requires_adjudication_authorization"
