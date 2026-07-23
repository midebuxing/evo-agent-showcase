"""identity-v2 阶段一·从源头冻结 blueprint —— fail-closed 连贯设计验收（R1-R11 + 证据）。

**R1-R11 强制验收**（fail-closed 逼出来，全绿才算完成）：
- R1 细化：真 1882 对按 v2 哈希分组、组内 v1 键唯一（v1 分 ⇒ v2 分）。
- R2 非平凡：∃ v1 dedupe 撞而 v2 分（母病真实例）。
- R3 别名稳定：同卡同 regime，measure ∈ {crack_width, measure.crack_width} → 同哈希。
- R4 真值敏感：measure.crack_width → measure.spalling_area → 哈希变。
- R5 不透明编号敏感：同 slot_id 异 slot_ref_id → 哈希变（source_item_id 承载编号）。
- R6 卡级多目标：A1→form.mbi4 与 A1→form.mbi5 → `unresolved_multi_target`。
- R7 运行级：两卡同 threshold_regime_id 异 op/value → `threshold_regime_signature_conflict`。
- R8 unresolved 区分：两未知 measure 异原串→异哈希；同原串同 namespace→闸。
- R9 Decimal：0.1 vs 0.10000000000000001 → 异 literal；0.1==0.10 同；float 入口必炸。
- R10 formula 闭合：`evil(x)`→`unsupported_formula`；`n^2-2n+3`→稳定 formula_id。
- R11 applicability：翻 regime → 该卡 applicability 义务哈希变、其他 channel 不变。

加性：本单元只**增加** v2 旁路，不改 v1 判定路径（compute_obligation_id/dedupe_key/
_merge_two/validate_building_closure/派生器现有输出行为字节不变）。
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import ValidationError

from canonical_profile import CanonicalProfileError, canonical_json
from evo_agent_baseline.contracts import RuleCardDTO
from evo_agent_baseline.closure import blueprint_deriver as B
from evo_agent_baseline.closure import obligation_deriver as D
from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.identity_v2 import ObligationContractError
from evo_agent_baseline.closure.rulecard_decimal_load import load_identity_cards
from evo_agent_baseline.closure.tests.fixtures import (
    make_fact,
    make_fact_pack,
    make_rule_card,
)
from evo_agent_baseline.closure.validator import (
    compute_obligation_id_v1 as compute_obligation_id,
    dedupe_key_v1 as dedupe_key,
)

_META = {"run_id": "R-bp-001", "world_id": "WB-bp-001", "building_id": "BLD-bp-001"}


def _empty_index() -> FactIndex:
    return FactIndex(make_fact_pack([]))


# =========================================================================== #
# 完整源子结构 dict 构造器（strict DTO model_validate 需全必填字段）
# =========================================================================== #


def _th(**kw) -> Dict[str, Any]:
    d = dict(
        threshold_regime_id="t.1",
        measure_key="m.x",
        operator="<=",
        unit="mm",
        qualifiers={},
        source_quote_refs=[],
        value=7,
    )
    d.update(kw)
    return d


def _slot_role(**kw) -> Dict[str, Any]:
    d = dict(
        slot_ref_id="sr1",
        slot_id="repair.required",
        qualifiers={},
        roles=["evidence"],
        required=True,
    )
    d.update(kw)
    return d


def _trigger(**kw) -> Dict[str, Any]:
    d = dict(
        condition_id="c.1",
        predicate_kind="slot",
        operator="==",
        expected_value=True,
        slot_ref_id="sr1",
    )
    d.update(kw)
    return d


def _evidence(**kw) -> Dict[str, Any]:
    d = dict(
        evidence_requirement_id="ev1",
        kind="photo",
        required=True,
        description="",
        artifact_ids=[],
        slot_ref_ids=[],
        measure_keys=[],
        required_field_groups=[],
    )
    d.update(kw)
    return d


def _applic(**kw) -> Dict[str, Any]:
    d = dict(
        regime="mbis",
        actors=[],
        phase="",
        subject="",
        component_scope=[],
        building_scope=[],
        exclusions=[],
    )
    d.update(kw)
    return d


def _wf_artifact(**kw) -> Dict[str, Any]:
    d = dict(artifact_id="A1", artifact_type="form", artifact_key="form.mbi4")
    d.update(kw)
    return d


def _workflow(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "primary_actor": "",
        "primary_action": "",
        "recipients": [],
        "artifacts": artifacts,
        "deadlines": [],
        "audiences": [],
        "method_keys_allowed": [],
    }


# =========================================================================== #
# 真卡语料双读（v1 走 float 生产读径；v2 走 Decimal identity 读径；positional 配对）
# =========================================================================== #


def _find_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = (
            base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
            / "rule_cards.json"
        )
        if cand.exists():
            return cand
    return None


def _load_cards_float() -> List[RuleCardDTO]:
    """v1 生产读径（json.loads → float）；v1 threshold_eval 的 json.dumps 不吃 Decimal。"""
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    data = json.loads(p.read_text(encoding="utf-8"))
    return [RuleCardDTO(**{**c, "neighbor_families": []}) for c in data["cards"]]


def _load_cards_decimal() -> List[RuleCardDTO]:
    """v2 identity 读径（parse_float=Decimal）；同文件同顺序，positional 与 float 卡对齐。"""
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    return load_identity_cards(p)


# =========================================================================== #
# R1 细化 + R2 非平凡（真派生义务集，v1 float / v2 Decimal 双读 positional 配对）
# =========================================================================== #


def _pairs_from_real_cards() -> List[Tuple[str, str, str]]:
    """397 真卡逐源项 → (v2_hash, v1_compute_obligation_id, v1_dedupe_key) 配对。

    v1 义务从 float 卡派生（生产读径），v2 blueprint 从 Decimal 卡派生（identity 读径）；
    同文件同顺序 positional 配对（同一源项）。
    """
    fcards = _load_cards_float()
    dcards = _load_cards_decimal()
    fi = _empty_index()
    out: List[Tuple[str, str, str]] = []

    def add(o, b):
        out.append((b.canonical_identity_hash, compute_obligation_id(o), dedupe_key(o)))

    for fc, dc in zip(fcards, dcards):
        f_items = (fc.trigger_conditions or {}).get("items", []) or []
        d_items = (dc.trigger_conditions or {}).get("items", []) or []
        for ft, dt in zip(f_items, d_items):
            if isinstance(ft, dict):
                add(
                    D.evaluate_trigger(fc, dict(ft), fi, _META),
                    B.build_trigger_blueprint(dc, dict(dt), _META),
                )
        for fs, ds in zip(fc.slot_role_map or [], dc.slot_role_map or []):
            if isinstance(fs, dict) and fs.get("required"):
                add(
                    D.evaluate_slot_role(fc, dict(fs), fi, True, _META),
                    B.build_slot_role_blueprint(dc, dict(ds), _META),
                )
        for ftr, dtr in zip(fc.threshold_regimes or [], dc.threshold_regimes or []):
            if isinstance(ftr, dict):
                add(
                    D.evaluate_threshold(fc, dict(ftr), fi, True, _META),
                    B.build_threshold_blueprint(dc, dict(dtr), _META),
                )
        f_arts = (fc.workflow_operands or {}).get("artifacts", []) or []
        d_arts = (dc.workflow_operands or {}).get("artifacts", []) or []
        for fa, da in zip(f_arts, d_arts):
            if not isinstance(fa, dict):
                continue
            key = D._extract_artifact_key(fa)
            if not key:
                continue
            o = D.evaluate_artifact_obligation(
                fc, key, "artifact", fi, True, _META,
                artifact_id=fa.get("artifact_id"), bucket="workflow_operands.artifacts",
            )
            add(o, B.build_workflow_artifact_blueprint(dc, dict(da), _META))
        fer = fc.evidence_requirements or {}
        der = dc.evidence_requirements or {}
        for bucket in sorted(fer.keys()):
            for fr, dr in zip(fer.get(bucket) or [], der.get(bucket) or []):
                if isinstance(fr, dict) and fr.get("required", True):
                    add(
                        D.evaluate_evidence_requirement(fc, bucket, dict(fr), fi, True, _META),
                        B.build_evidence_blueprint(dc, bucket, dict(dr), _META),
                    )
    return out


def _synthetic_alias_rows() -> Tuple[List[Tuple[str, str, str]], str]:
    """登记别名等价类：同 canonical measure 的三别名写法（crack_width / measure.crack_width /
    crackwidth）→ 归一同 canonical `measure.crack_width` → **同一 v2 身份哈希**；v1 侧用原始
    measure_key（不归一）→ **三个互异 v1 键**。返回 [(v2_hash, v1_oid, v1_ded), ...] + 该组 v2 hash。

    这是「v2 合法合并 v1 分开的**登记别名对**」——refinement 的合法例外（非回归）：v2 把三写法
    归一到同一 canonical 身份，而 v1 因用原始串把它们分成三个键。
    """
    card = make_rule_card("rc.r1alias")
    fi = _empty_index()
    rows: List[Tuple[str, str, str]] = []
    for mk in ("crack_width", "measure.crack_width", "crackwidth"):
        th = _th(threshold_regime_id="rg.alias", measure_key=mk, value=7)
        o = D.evaluate_threshold(card, dict(th), fi, True, _META)
        b = B.build_threshold_blueprint(card, dict(th), _META)
        rows.append((b.canonical_identity_hash, compute_obligation_id(o), dedupe_key(o)))
    return rows, rows[0][0]


def test_R1_refinement_v2_refines_v1_except_registered_aliases():
    """R1（**非空转**）：按 canonical 语义键（v2 身份哈希）分组，证 v2 refine v1 **except 登记别名对**。

    真语料无别名对（每项自成 singleton 类，nonsingleton=0）——单靠真语料的「组内 v1 键唯一」是
    「全 hash 唯一」**空证**。故**注入登记别名等价类**（同 canonical measure 三别名写法：同 v2 身份、
    异 v1 键）令 nonsingleton_groups>0：该 v2 组内 3 个 v1 键互异（v1 分）但同属一登记别名类
    （v2 合法合并、非回归）。断言（对 compute_obligation_id 与 dedupe_key 二者）：
    - 非空转：nonsingleton_groups>0（别名类令 ≥1 组 max_group>1，白名单非空）；
    - refinement：每个 nonsingleton 组**恰为登记别名类**（白名单内）——真语料无别名 → 白名单外
      出现 nonsingleton 组即「v2 误合并非别名的 v1-分开项」= refinement 违反（此断言即原严格
      refinement 检查的非空转版本）；
    - 别名合法：别名组内 v1 键=3（v1 分、v2 合），按 canonical 语义键归一恰对应一 v2 身份。
    """
    real = _pairs_from_real_cards()
    assert len(real) >= 1800, f"真派生义务对数异常偏少: {len(real)}"
    alias_rows, alias_hash = _synthetic_alias_rows()
    # 别名前提：三写法归一同一 v2 身份（1 个），但 v1 键互异（3 个 → v1 把别名分开）
    assert len({h for h, _o, _d in alias_rows}) == 1, "三别名写法应归一同一 v2 身份"
    assert len({d for _h, _o, d in alias_rows}) == 3, "三别名写法 v1 dedupe 应互异（v1 分别名）"
    assert len({o for _h, o, _d in alias_rows}) == 3, "三别名写法 v1 compute_obligation_id 应互异"

    rows = real + alias_rows
    alias_whitelist = {alias_hash}  # 登记别名类 v2 身份（白名单**非空** → 非空证）

    stats: Dict[str, Tuple[int, int, int]] = {}
    for keyname, idx in (("compute_obligation_id", 1), ("dedupe_key", 2)):
        groups: Dict[str, set] = defaultdict(set)
        for r in rows:
            groups[r[0]].add(r[idx])
        max_group = max(len(s) for s in groups.values())
        nonsingleton = {h: s for h, s in groups.items() if len(s) > 1}
        # 非空转：注入别名类 → 至少一组 v2 合并了多个 v1 键
        assert nonsingleton, f"nonsingleton_groups==0（{keyname} 空证）：refinement 未被非平凡验证"
        assert max_group >= 3, f"别名等价类应令 max_group≥3（{keyname}）: {max_group}"
        # refinement（非空转版）：任何 nonsingleton 组必须是登记别名组；白名单外出现 = v2 误合并非别名
        for h, keys in nonsingleton.items():
            assert h in alias_whitelist, (
                f"非登记别名的 v2 合并（refinement 违反，{keyname}）: "
                f"{h[:12]} 合并 {len(keys)} 个 v1 键 {sorted(keys)[:3]}"
            )
        # 别名组内确 v1 键>1（v1 分、v2 合）——「登记别名对」合法合并
        assert len(groups[alias_hash]) == 3, f"别名类应 3 个互异 v1 {keyname}: {len(groups[alias_hash])}"
        stats[keyname] = (len(rows), max_group, len(nonsingleton))
    print(f"[R1 stats] {stats}")


def test_R2_v2_strictly_finer_splits_real_v1_dedupe_collision():
    """R2：v2 **严格更细**——真语料里 ≥1 组 v1 dedupe_key 撞而 v2 分（母病真实例）。"""
    pairs = _pairs_from_real_cards()
    v1_ded_groups: Dict[str, set] = defaultdict(set)
    for h, _oid, ded in pairs:
        v1_ded_groups[ded].add(h)
    split = [ded for ded, hs in v1_ded_groups.items() if len(hs) > 1]
    assert len(split) >= 1, "预期至少 1 个 v1 dedupe 撞而 v2 分开的真实母病组"


# =========================================================================== #
# R3 别名稳定 / R4 真值敏感 / R5 不透明编号敏感
# =========================================================================== #


def test_R3_alias_stability_same_hash():
    """R3：同卡同 regime，measure_key ∈ {crack_width, measure.crack_width}（别名）→ 同哈希。

    §1：resolved → local_ref := canonical_key；两别名归一到同 canonical → 同 binding →
    同身份（regime_id 相同 → source_item_id 相同）。桥接（保原始编号）做不到别名稳定。
    """
    card = make_rule_card("rc.alias")
    b1 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg.1", measure_key="crack_width"), _META)
    b2 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg.1", measure_key="measure.crack_width"), _META)
    assert b1.identity.measure_bindings == b2.identity.measure_bindings
    assert b1.identity.measure_bindings[0].local_ref == "measure.crack_width"  # §1
    assert b1.canonical_identity_hash == b2.canonical_identity_hash


def test_R4_truth_sensitivity_diff_hash():
    """R4：measure.crack_width → measure.spalling_area（真值变）→ 哈希变。"""
    card = make_rule_card("rc.truth")
    b1 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg.1", measure_key="measure.crack_width"), _META)
    b2 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg.1", measure_key="measure.spalling_area"), _META)
    assert b1.canonical_identity_hash != b2.canonical_identity_hash


def test_R5_opaque_ref_sensitivity_diff_hash():
    """R5：slot_role 同 slot_id（repair.required）异 slot_ref_id → 哈希变。

    §1：resolved slot binding local_ref := canonical(slot_id)（两条相同）；不透明 slot_ref_id
    进 **source_item_id** → 异 slot_ref_id 令身份异（哈希变）。
    """
    card = make_rule_card("rc.opaque")
    s1 = B.build_slot_role_blueprint(card, _slot_role(slot_ref_id="sr1"), _META)
    s2 = B.build_slot_role_blueprint(card, _slot_role(slot_ref_id="sr2"), _META)
    assert s1.identity.slot_bindings == s2.identity.slot_bindings  # canonical 相同
    assert s1.canonical_identity_hash != s2.canonical_identity_hash  # source_item_id 承载编号


# =========================================================================== #
# R6 卡级多目标 / R7 运行级 regime 冲突
# =========================================================================== #


def test_R6_card_multi_target_hard_fails():
    """R6：卡内 A1→form.mbi4 与 A1→form.mbi5（一编号多目标）→ `unresolved_multi_target`。

    卡 workflow artifacts multimap A1→[form.mbi4, form.mbi5]；evidence 引 A1 → 一 blueprint
    内两 artifact binding 同原始 ref A1 异 canonical → 卡内多目标闸 hard-fail（**不静默压扁**）。
    """
    card = make_rule_card(
        "rc.multi",
        workflow_operands=_workflow(
            [_wf_artifact(artifact_id="A1", artifact_key="form.mbi4"),
             _wf_artifact(artifact_id="A1", artifact_key="form.mbi5")]
        ),
    )
    req = _evidence(artifact_ids=["A1"])
    with pytest.raises(ObligationContractError, match="unresolved_multi_target"):
        B.build_evidence_blueprint(card, "for_matching", req, _META)


def test_R7_run_level_regime_signature_conflict():
    """R7：两**卡**同 threshold_regime_id 异 op/value → `threshold_regime_signature_conflict`。

    跨卡 → 各卡 CardBindingRegistry 独立（无 duplicate_source_item），运行级
    `RegimeSignatureRegistry`（derive_run_blueprints 钩子）逮跨卡签名冲突。
    """
    cardA = make_rule_card("rc.A", threshold_regimes=[_th(threshold_regime_id="shared.rg", operator="<=", value=7)])
    cardB = make_rule_card("rc.B", threshold_regimes=[_th(threshold_regime_id="shared.rg", operator=">=", value=9)])
    with pytest.raises(ObligationContractError, match="threshold_regime_signature_conflict"):
        B.derive_run_blueprints([cardA, cardB], _META)
    # 一致签名（同 regime 同 op/value）跨卡不冲突
    cardC = make_rule_card("rc.C", threshold_regimes=[_th(threshold_regime_id="shared.rg", operator="<=", value=7)])
    B.derive_run_blueprints([cardA, cardC], _META)


def test_within_card_duplicate_regime_is_duplicate_source_item():
    """卡内同 threshold_regime_id 两条（同 source_item_id）→ `duplicate_source_item`（§2 卡级闸）。

    （运行级签名冲突见 R7；卡内因 source_item_id=regime_id 相同，更精确的错是重复源项。）
    """
    card = make_rule_card(
        "rc.dupreg",
        threshold_regimes=[_th(threshold_regime_id="rg.x", operator="<=", value=7),
                           _th(threshold_regime_id="rg.x", operator=">=", value=9)],
    )
    with pytest.raises(ObligationContractError, match="duplicate_source_item"):
        B.derive_card_blueprints(card, _META)


# =========================================================================== #
# R8 unresolved 区分 + 闸
# =========================================================================== #


def test_R8_unresolved_distinction_and_gate():
    """R8：两未知 measure 异原串 → 异哈希；同原串同 namespace（重复）→ 卡内闸 hard-fail。"""
    card = make_rule_card("rc.r8")
    ba = B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=["unknown.alpha"]), _META)
    bb = B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=["unknown.beta"]), _META)
    # 两未知 measure 均 unresolved（passthrough），异原串 → 异 local_ref → 异哈希
    assert ba.identity.measure_bindings[0].resolution == "unresolved"
    assert ba.canonical_identity_hash != bb.canonical_identity_hash
    # 同原串同 namespace（measure_keys 重复）→ 卡内闸 hard-fail（不静默去重）
    with pytest.raises(ObligationContractError, match="duplicate_local_ref_binding"):
        B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=["unknown.alpha", "unknown.alpha"]), _META)


# =========================================================================== #
# R9 Decimal ingress + float 必炸
# =========================================================================== #


def test_R9_decimal_ingress_distinct_and_float_boom():
    """R9：0.1 vs 0.10000000000000001 → 异 literal；0.1==0.10 同；float 入口必炸。"""
    from decimal import Decimal

    card = make_rule_card("rc.r9")
    b1 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg", value=Decimal("0.1")), _META)
    b2 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg", value=Decimal("0.10000000000000001")), _META)
    assert b1.identity.source_predicate_spec.literal_value_canonical == "0.1"
    assert b2.identity.source_predicate_spec.literal_value_canonical == "0.10000000000000001"
    assert b1.canonical_identity_hash != b2.canonical_identity_hash
    # 0.1 == 0.10 → canonical 归一相等（以 canonical_decimal_str 为准）
    b3 = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg", value=Decimal("0.10")), _META)
    assert b3.identity.source_predicate_spec.literal_value_canonical == "0.1"
    assert b3.canonical_identity_hash == b1.canonical_identity_hash
    # _literal_value 直测：Python float → `canonical_number_float_ingress` hard-fail（§3 防御闸）
    with pytest.raises(ObligationContractError, match="canonical_number_float_ingress"):
        B._literal_value(0.1)
    # 端到端：DTO ingress（strict Decimal union）拒 Python float（float 入口结构上被排除）
    with pytest.raises(ValidationError):
        B.build_threshold_blueprint(card, _th(value=0.1), _META)


# =========================================================================== #
# R10 formula 登记表闭合
# =========================================================================== #


def _formula_th(expression: str) -> Dict[str, Any]:
    return _th(
        threshold_regime_id="t.f",
        measure_key="count.pull_test.additional_after_failure",
        operator="formula",
        unit="test",
        value=None,
        formula={"expression": expression, "variables": [{"symbol": "n", "measure_key": "count.pull_test.failed_cumulative"}]},
    )


def test_R10_formula_registry_closed():
    """R10：`n^2-2n+3` → 稳定 formula_id（跨空白/写法变体一致）；`evil(x)` / 未登记式 → `unsupported_formula`。"""
    card = make_rule_card("rc.r10")
    b = B.build_threshold_blueprint(card, _formula_th("n^2 - 2n + 3"), _META)
    assert b.identity.source_predicate_spec.formula_id == "formula.pull_test_additional_after_failure"
    # 写法变体（去空白）→ 同 formula_id（规范 AST 匹配）
    b2 = B.build_threshold_blueprint(card, _formula_th("n^2-2n+3"), _META)
    assert b2.identity.source_predicate_spec.formula_id == b.identity.source_predicate_spec.formula_id
    # evil(x) 函数调用 → 越受限文法 → unsupported_formula
    with pytest.raises(ObligationContractError, match="unsupported_formula"):
        B.build_threshold_blueprint(card, _formula_th("evil(x)"), _META)
    # 合法多项式但未登记 → unsupported_formula（无任意散列兜底）
    with pytest.raises(ObligationContractError, match="unsupported_formula"):
        B.build_threshold_blueprint(card, _formula_th("n + 1"), _META)


def test_formula_variable_measure_mismatch_unsupported():
    """R10 补：表达式登记但变量→度量不匹配 → `unsupported_formula`（变量/度量精确匹配）。"""
    card = make_rule_card("rc.r10b")
    bad = _th(
        threshold_regime_id="t.f", measure_key="count.pull_test.additional_after_failure",
        operator="formula", unit="test", value=None,
        formula={"expression": "n^2 - 2n + 3", "variables": [{"symbol": "n", "measure_key": "length.crack.width"}]},
    )
    with pytest.raises(ObligationContractError, match="unsupported_formula"):
        B.build_threshold_blueprint(card, bad, _META)


# =========================================================================== #
# R11 applicability channel（§5）：翻 regime → applicability 哈希变、他 channel 不变
# =========================================================================== #


def test_R11_applicability_regime_isolation():
    """R11：翻 regime → 该卡 applicability 义务哈希变、其他 channel（threshold/slot_role）不变。"""
    kw = dict(threshold_regimes=[_th(threshold_regime_id="rg")], slot_role_map=[_slot_role()])
    c1 = make_rule_card("rc.r11", applicability=_applic(regime="mbis", subject="facade"), **kw)
    c2 = make_rule_card("rc.r11", applicability=_applic(regime="other", subject="facade"), **kw)
    h1 = {bp.identity.source_channel: bp.canonical_identity_hash for bp in B.derive_card_blueprints(c1, _META)}
    h2 = {bp.identity.source_channel: bp.canonical_identity_hash for bp in B.derive_card_blueprints(c2, _META)}
    assert h1["applicability"] != h2["applicability"], "regime 变 → applicability 义务哈希应变"
    assert h1["threshold"] == h2["threshold"], "regime 不进 threshold channel"
    assert h1["slot_role"] == h2["slot_role"], "regime 不进 slot_role channel"


def test_applicability_channel_shape():
    """§5：applicability blueprint 结构（source_channel/scope=building/无谓词）。"""
    card = make_rule_card("rc.ap", applicability=_applic(subject="facade"))
    bp = B.build_applicability_blueprint(card, _applic(subject="facade"), _META)
    assert bp.identity.source_channel == "applicability"
    assert bp.identity.kind == "scope_audit"
    assert bp.identity.scope.kind == "building"
    assert bp.identity.predicate_kind == "" and bp.identity.source_predicate_spec is None


# =========================================================================== #
# 无求值状态泄漏（身份 schema 从根上无求值态落点）
# =========================================================================== #

_EVAL_STATE_FIELD_NAMES = frozenset(
    {
        "observed_value_json", "comparator_result", "evaluated_comparator",
        "evaluated_expected_value_json", "expected_value_json", "threshold_value_json",
        "closure_status", "satisfaction_status", "open_reason_code",
        "blocked_reason_code", "merged_observation_bottom",
    }
)


def _all_field_names(model) -> set:
    from pydantic import BaseModel
    import typing

    names = set()
    for name, fld in model.model_fields.items():
        names.add(name)
        ann = fld.annotation
        origin = typing.get_origin(ann)
        args = typing.get_args(ann)
        candidates = [ann]
        if origin is not None:
            candidates += list(args)
        for a in candidates:
            inner = typing.get_origin(a)
            if inner is tuple:
                a = typing.get_args(a)[0]
            if isinstance(a, type) and issubclass(a, BaseModel):
                names |= _all_field_names(a)
    return names


def test_blueprint_identity_schema_excludes_all_eval_state_fields():
    """结构级：CanonicalObligationIdentity（+ 嵌套）全字段名 ∩ 求值态字段 == ∅。"""
    from evo_agent_baseline.closure.identity_v2 import (
        CanonicalObligationIdentity,
        ObligationBlueprint,
    )

    for model in (CanonicalObligationIdentity, ObligationBlueprint):
        leaked = _all_field_names(model) & _EVAL_STATE_FIELD_NAMES
        assert not leaked, f"{model.__name__} 身份含求值态字段: {sorted(leaked)}"


def test_formula_blueprint_uses_rule_side_operator_not_post_eval():
    """公式类具体证据：v1 求值把 operator 覆写为 `>=` 并算出 expected；v2 保规则侧 `formula`。"""
    th = {
        "threshold_regime_id": "t.f1",
        "measure_key": "count.pull_test.additional_after_failure",
        "operator": "formula",
        "unit": "test",
        "qualifiers": {},
        "source_quote_refs": [],
        "value": None,
        "formula": {
            "expression": "n^2 - 2n + 3",
            "variables": [{"symbol": "n", "measure_key": "count.pull_test.failed_cumulative"}],
        },
    }
    card = make_rule_card("rc.f", threshold_regimes=[th])
    facts = [
        make_fact("f1", measure_key="count.pull_test.failed_cumulative", value=3, value_type="number"),
        make_fact("f2", measure_key="count.pull_test.additional_after_failure", value=10, value_type="number"),
    ]
    fi = FactIndex(make_fact_pack(facts))
    o = D.evaluate_threshold(card, dict(th), fi, True, _META)
    assert o.operator == ">="  # 求值后覆写（threshold_eval:416）
    assert o.expected_value_json == "6"  # n^2-2n+3 with n=3
    assert o.observed_value_json == "10"

    b = B.build_threshold_blueprint(card, dict(th), _META)
    spec = b.identity.source_predicate_spec
    assert spec.source_operator == "formula"  # 规则侧，非 >=
    assert spec.predicate_kind == "threshold_formula"
    assert spec.literal_value_tag == "none" and spec.literal_value_canonical == ""
    assert spec.formula_id == "formula.pull_test_additional_after_failure"
    ident_json = json.dumps(b.identity.model_dump(), ensure_ascii=False)
    assert '">="' not in ident_json  # 无求值后 operator
    assert '"6"' not in ident_json  # 无算出的 expected
    assert "10" not in ident_json  # 无 observed


def test_binding_order_independence_no_positional_pairing():
    """binding 按真实配对非平行下标：源项内列表顺序变 → 同一身份 hash（全序排序）。"""
    card = make_rule_card(
        "rc.ev",
        slot_role_map=[
            _slot_role(slot_ref_id="srA", slot_id="repair.required"),
            _slot_role(slot_ref_id="srB", slot_id="repair.prescribed.completed"),
        ],
    )
    req_a = _evidence(slot_ref_ids=["srA", "srB"], required_field_groups=["g1", "g2"])
    req_b = _evidence(slot_ref_ids=["srB", "srA"], required_field_groups=["g2", "g1"])
    ba = B.build_evidence_blueprint(card, "for_matching", req_a, _META)
    bb = B.build_evidence_blueprint(card, "for_matching", req_b, _META)
    assert ba.canonical_identity_hash == bb.canonical_identity_hash


# =========================================================================== #
# fail-closed 强制探针（typed ingress / artifact hard-fail / 聚合闸 / channel）
# =========================================================================== #


def test_unresolved_multi_target_within_evidence():
    """卡内闸①：evidence 引 slot_ref_id 指两异 slot_id（同编号多目标）→ `unresolved_multi_target`。"""
    card = make_rule_card(
        "rc.srcdup",
        slot_role_map=[
            _slot_role(slot_ref_id="sr1", slot_id="repair.prescribed.started"),
            _slot_role(slot_ref_id="sr1", slot_id="repair.prescribed.completed"),
        ],
    )
    req = _evidence(slot_ref_ids=["sr1"])
    with pytest.raises(ObligationContractError, match="unresolved_multi_target"):
        B.build_evidence_blueprint(card, "for_matching", req, _META)


def test_duplicate_measure_key_hard_fails_not_deduped():
    """卡内闸①：evidence `measure_keys=["m.x","m.x"]`（同编号重复）→ `duplicate_local_ref_binding`。"""
    card = make_rule_card("rc.dup")
    with pytest.raises(ObligationContractError, match="duplicate_local_ref_binding"):
        B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=["m.x", "m.x"]), _META)
    # 单 m.x → 恰一条 binding（无误伤）
    bp = B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=["m.x"]), _META)
    assert len(bp.identity.measure_bindings) == 1


def test_alias_collapse_distinct_refs_same_canonical():
    """§1 alias 折叠：evidence 引两 slot_ref_id 指同一 slot_id → 折叠成一条 binding（非 hard-fail）。"""
    card = make_rule_card(
        "rc.collapse",
        slot_role_map=[
            _slot_role(slot_ref_id="srA", slot_id="repair.required"),
            _slot_role(slot_ref_id="srB", slot_id="repair.required"),
        ],
    )
    bp = B.build_evidence_blueprint(card, "for_matching", _evidence(slot_ref_ids=["srA", "srB"]), _META)
    assert len(bp.identity.slot_bindings) == 1  # 异 ref 归一同 canonical → 折叠一条
    assert bp.identity.slot_bindings[0].canonical_key == "repair.required"


def test_real_artifact_resolves_bogus_hard_fails():
    """填充 registry 后真 artifact key resolve（非 unresolved）；bogus → `unknown_artifact_key` hard-fail。"""
    card = make_rule_card("rc.art")
    bp = B.build_workflow_artifact_blueprint(card, _wf_artifact(artifact_key="form.mbi4"), _META)
    ab = bp.identity.artifact_bindings
    assert len(ab) == 1 and ab[0].resolution == "resolved" and ab[0].canonical_key == "form.mbi4"
    with pytest.raises(CanonicalProfileError, match="unknown_artifact_key"):
        B.build_workflow_artifact_blueprint(card, _wf_artifact(artifact_key="bogus.not_in_registry"), _META)


def test_ninth_qualifier_key_rejected_by_ingress():
    """typed ingress：第九 qualifier 键 → DTO extra=forbid ValidationError（母病闸真拦）。"""
    card = make_rule_card("rc.q9")
    sr = _slot_role(qualifiers={"unknown_9th_key": "x"})
    with pytest.raises(ValidationError):
        B.build_slot_role_blueprint(card, sr, _META)


def test_unknown_source_key_rejected_by_ingress():
    """typed ingress：源 dict 未声明键 → DTO model_validate ValidationError（不静默进入身份）。"""
    card = make_rule_card("rc.ingress")
    th = _th(brand_new_source_field="leak")
    with pytest.raises(ValidationError):
        B.build_threshold_blueprint(card, th, _META)


def test_trigger_unknown_predicate_kind_hard_fails():
    """typed ingress：trigger `predicate_kind ∉ {slot,measure}` → `unsupported_predicate_kind`（不静默归 slot）。"""
    card = make_rule_card("rc.tk")
    tr = _trigger(predicate_kind="brand_new_kind")
    with pytest.raises(ObligationContractError, match="unsupported_predicate_kind"):
        B.build_trigger_blueprint(card, tr, _META)


def test_ordinary_and_escalation_node_representable_v4():
    """v4 放宽：普通/升级 node 直调 builder → 成功（predicate_kind = raw node_kind、spec=None）。"""
    card = make_rule_card("rc.graph")
    base = {"obligation_node_id": "n01", "actor": "ri", "action": "conduct_x",
            "recipient_ids": [], "artifact_ids": [], "deadline_ids": [], "trigger_condition_ids": ["trg01"]}
    for nk in ("obligation", "escalation"):
        bp = B.build_obligation_node_blueprint(card, dict(base, node_kind=nk), _META)
        assert bp.identity.source_channel == "obligation_graph"
        assert bp.identity.predicate_kind == nk  # 携 raw node_kind（补 refine 有损洞）
        assert bp.identity.source_predicate_spec is None


def test_unknown_raw_node_kind_hard_fails_v4():
    """§3.1.1 raw-kind 闸：未知 raw node_kind（∉ 三值）经 covered/STRICT 入口 → `unknown_node_kind`
    hard-fail（`from_dict` 归一之前拒）；v1 归一路径不受影响（另测 test_method_semantics `duty`）。"""
    graph = {
        "nodes": [{"obligation_node_id": "n01", "node_kind": "brand_new_kind", "actor": "ri",
                   "action": "conduct_x", "recipient_ids": [], "artifact_ids": [],
                   "deadline_ids": [], "trigger_condition_ids": []}],
        "edges": [],
    }
    card = make_rule_card("rc.unkkind", obligation_graph=graph)
    with pytest.raises(ObligationContractError, match="unknown_node_kind"):
        B.derive_covered_card_blueprints(card, _META)
    with pytest.raises(ObligationContractError, match="unknown_node_kind"):
        B.derive_card_blueprints(card, _META)


def test_prohibition_node_and_edge_representable():
    """prohibition node + edge 可表示；v4：node deadline_ids 内嵌 identity（悬空 → hard-fail）。"""
    card = make_rule_card("rc.graph")
    prohib = {"obligation_node_id": "n01", "node_kind": "prohibition", "actor": "ri",
              "action": "conduct_x", "recipient_ids": [], "artifact_ids": [],
              "deadline_ids": [], "trigger_condition_ids": ["trg01"]}
    pbp = B.build_obligation_node_blueprint(card, prohib, _META)
    assert pbp.identity.source_channel == "obligation_graph"
    assert pbp.identity.predicate_kind == "prohibition"
    # v4：node 带 deadline_ids 但同卡无该 deadline 定义 → 悬空 hard-fail `dangling_node_deadline_ref`
    with pytest.raises(ObligationContractError, match="dangling_node_deadline_ref"):
        B.build_obligation_node_blueprint(card, dict(prohib, deadline_ids=["dl01"]), _META)
    # node 带 deadline_ids 且同卡有定义 → 内嵌完整 DeadlineBinding（identity）
    wo = _workflow([])
    wo["deadlines"] = [{"deadline_id": "dl01", "relation": "within",
                        "time_anchor_key": "inspection.prescribed.completed",
                        "offset_value": 7, "offset_unit": "day"}]
    card_dl = make_rule_card("rc.graphdl", workflow_operands=wo)
    nbp = B.build_obligation_node_blueprint(card_dl, dict(prohib, deadline_ids=["dl01"]), _META)
    assert len(nbp.identity.deadline_bindings) == 1
    assert nbp.identity.deadline_bindings[0].relation == "within"
    # edge → 三态审计身份（§3.4.3，codex 阻断 1 修订）：此卡无 n01/n02 node → dangling 审计蓝图；
    # predicate_kind=obligation_edge，obligation_edge_id 三元组派生。
    edge = {"source_node_id": "n01", "target_node_id": "n02", "relation": "if_failed_then"}
    card_edge = make_rule_card(
        "rc.graphedge", obligation_graph={"nodes": [], "edges": [edge]}
    )
    ebps = B.derive_edge_audit_blueprints(card_edge, _META)
    assert len(ebps) == 1
    ebp = ebps[0]
    assert ebp.identity.predicate_kind == "obligation_edge"
    assert ebp.identity.obligation_edge_ids == ("n01->n02:if_failed_then",)
    assert ebp.identity.source_item_id == B._edge_dangling_sid("n01->n02:if_failed_then")


def _gnode(nid: str, action: str) -> Dict[str, Any]:
    return {"obligation_node_id": nid, "node_kind": "obligation", "actor": "ri",
            "action": action, "recipient_ids": [], "artifact_ids": [], "deadline_ids": [],
            "trigger_condition_ids": []}


def test_edge_audit_three_state_blueprints():
    """edge 审计三态独立身份（§3.4.3，codex 阻断 1 修订）：dangling / unknown-relation 分身×2 /
    inactive-target 聚合各具独立、静态可声明身份；镜像 `evaluate_obligation_edges` 三分支。"""
    n1, n2, n3 = _gnode("n01", "a"), _gnode("n02", "b"), _gnode("n03", "c")

    # (a) dangling：target 缺失 → 1 条，obligation_node_id=""。
    dang = {"source_node_id": "n01", "target_node_id": "nX", "relation": "if_failed_then"}
    card_d = make_rule_card("rc.d", obligation_graph={"nodes": [n1], "edges": [dang]})
    bps_d = B.derive_edge_audit_blueprints(card_d, _META)
    assert len(bps_d) == 1 and bps_d[0].identity.obligation_node_id == ""

    # (b) unknown relation：source/target 两分身各携各自 node_id、**异身份**（v5 不误合并）。
    unk = {"source_node_id": "n01", "target_node_id": "n02", "relation": "weird_rel"}
    card_u = make_rule_card("rc.u", obligation_graph={"nodes": [n1, n2], "edges": [unk]})
    bps_u = B.derive_edge_audit_blueprints(card_u, _META)
    assert len(bps_u) == 2
    assert {bp.identity.obligation_node_id for bp in bps_u} == {"n01", "n02"}
    assert (bps_u[0].canonical_identity_hash != bps_u[1].canonical_identity_hash), (
        "source/target 两分身必须异 hash（旧一 edge 一 SID 会误合并）"
    )

    # (c) inactive-target 聚合：多 edge 同 target → 聚合身份含**完整 edge SID 排序集**。
    e1 = {"source_node_id": "n01", "target_node_id": "n03", "relation": "if_failed_then"}
    e2 = {"source_node_id": "n02", "target_node_id": "n03", "relation": "if_unable_then"}
    card_a = make_rule_card(
        "rc.a", obligation_graph={"nodes": [n1, n2, n3], "edges": [e1, e2]}
    )
    inact = [bp for bp in B.derive_edge_audit_blueprints(card_a, _META)
             if bp.identity.obligation_node_id == "n03"]
    assert len(inact) == 1
    assert len(inact[0].identity.obligation_edge_ids) == 2, "聚合身份须含完整集，非 min(edge_ids)"
    # 改**非最小** edge（e2 的 relation）→ 聚合身份 hash 变（旧只登 min 会丢此变化）。
    e2b = {"source_node_id": "n02", "target_node_id": "n03", "relation": "if_failed_then"}
    card_a2 = make_rule_card(
        "rc.a", obligation_graph={"nodes": [n1, n2, n3], "edges": [e1, e2b]}
    )
    inact2 = [bp for bp in B.derive_edge_audit_blueprints(card_a2, _META)
              if bp.identity.obligation_node_id == "n03"]
    assert inact2[0].canonical_identity_hash != inact[0].canonical_identity_hash, (
        "改非最小 edge 必须改聚合身份（旧 min(edge_ids) 丢其余身份）"
    )


# =========================================================================== #
# v4 缺口增补：deadline / node / method 身份 sentinel 变形（母病断根：改值→hash 变）
# =========================================================================== #


def _dl(**kw) -> Dict[str, Any]:
    d = dict(deadline_id="ddl01", relation="within", offset_value=7, offset_unit="day",
             time_anchor_key="inspection.prescribed.completed")
    d.update(kw)
    return d


def _node(**kw) -> Dict[str, Any]:
    d = dict(obligation_node_id="n01", node_kind="obligation", actor="ri", action="submit_x",
             recipient_ids=[], artifact_ids=[], deadline_ids=[], trigger_condition_ids=[])
    d.update(kw)
    return d


def test_workflow_deadline_sentinel_hash_sensitivity():
    """§2.4 sentinel：deadline relation/offset_value/offset_unit/time_anchor 改 → workflow_deadline
    hash 变（母病断根：deadline 复合键全进身份）。"""
    card = make_rule_card("rc.wdl")
    h0 = B.build_workflow_deadline_blueprint(card, _dl(), _META).canonical_identity_hash
    for field, newval in [
        ("relation", "before"),
        ("offset_value", 8),
        ("offset_unit", "month"),
        ("time_anchor_key", "repair.prescribed.started"),
    ]:
        h1 = B.build_workflow_deadline_blueprint(
            card, _dl(**{field: newval}), _META
        ).canonical_identity_hash
        assert h1 != h0, f"改 deadline.{field} 应变 workflow_deadline hash"


def test_node_embedded_deadline_sentinel_hash_sensitivity():
    """§2.5 sentinel：node.deadline_ids 改 **或** 底层 deadline 定义改 → node hash 变（identity 内嵌
    完整 DeadlineBinding，非 provenance）；node 内嵌与 workflow_deadline channel 同值对象字节相同。

    **加固（顺带）**：引用 ID sentinel **只改引用 ID**（ddl01→ddl02，两 deadline 定义
    relation/offset/offset_unit/time_anchor **全同**）——hash 变来自 DeadlineBinding.local_ref
    （`deadline:ddl01` vs `deadline:ddl02`）**独立于 relation 变化**，证引用 ID 本身进身份。"""
    # 两 deadline 定义除 deadline_id 外**完全相同**（同 relation/offset/unit/time_anchor）。
    wo = _workflow([])
    wo["deadlines"] = [_dl(deadline_id="ddl01"), _dl(deadline_id="ddl02")]
    card = make_rule_card("rc.ndl", workflow_operands=wo)
    node_a = _node(deadline_ids=["ddl01"])
    node_b = _node(deadline_ids=["ddl02"])
    bp_a = B.build_obligation_node_blueprint(card, dict(node_a), _META)
    bp_b = B.build_obligation_node_blueprint(card, dict(node_b), _META)
    # **仅引用 ID 改**（relation 等全同）→ node hash 变（local_ref 承载引用 ID，独立于 relation）
    assert bp_a.canonical_identity_hash != bp_b.canonical_identity_hash
    da = bp_a.identity.deadline_bindings[0]
    db = bp_b.identity.deadline_bindings[0]
    assert da.relation == db.relation and da.offset_value == db.offset_value  # relation 未变
    assert da.local_ref == "deadline:ddl01" and db.local_ref == "deadline:ddl02"  # 仅 ID 变
    # 底层 deadline 定义改（relation）→ node hash 变（与上正交，证复合键各维皆进身份）
    wo2 = _workflow([]); wo2["deadlines"] = [_dl(deadline_id="ddl01", relation="before")]
    card2 = make_rule_card("rc.ndl", workflow_operands=wo2)
    bp_a2 = B.build_obligation_node_blueprint(card2, dict(node_a), _META)
    assert bp_a2.canonical_identity_hash != bp_a.canonical_identity_hash
    # node 内嵌 DeadlineBinding == workflow_deadline channel binding（字节相同，§2.5 判据 4）
    wd = B.build_workflow_deadline_blueprint(card, _dl(deadline_id="ddl01"), _META)
    assert (
        canonical_json(bp_a.identity.deadline_bindings[0].model_dump())
        == canonical_json(wd.identity.deadline_bindings[0].model_dump())
    )


def test_workflow_deadline_offset_float_ingress_hard_fails():
    """加固（顺带）：deadline `offset_value` = Python float 经**公开入口** `build_workflow_deadline_blueprint`
    → `canonical_number_float_ingress` hard-fail（§2.4 Decimal ingress 拒 float，镜像 `_literal_value`；
    identity 入口结构上不该出现 float，漏入即炸）；int/Decimal 正常。"""
    card = make_rule_card("rc.wdlf")
    with pytest.raises(ObligationContractError, match="canonical_number_float_ingress"):
        B.build_workflow_deadline_blueprint(card, _dl(offset_value=0.5), _META)
    # int / Decimal 正常（不误伤）
    from decimal import Decimal
    assert B.build_workflow_deadline_blueprint(card, _dl(offset_value=7), _META)
    assert B.build_workflow_deadline_blueprint(card, _dl(offset_value=Decimal("0.5")), _META)
    # node 内嵌路径（`_resolve_node_deadline_bindings`）亦经同一 `_deadline_binding_from_dict` → 亦拒 float
    wo = _workflow([]); wo["deadlines"] = [_dl(deadline_id="ddl01", offset_value=0.5)]
    card_n = make_rule_card("rc.wdlfn", workflow_operands=wo)
    with pytest.raises(ObligationContractError, match="canonical_number_float_ingress"):
        B.build_obligation_node_blueprint(card_n, _node(deadline_ids=["ddl01"]), _META)


def test_node_kind_obligation_vs_escalation_hash_differs():
    """§3.1 sentinel：node_kind obligation↔escalation 变形（action=submit，refine 有损同 kind）→
    hash 变（predicate_kind 携 raw node_kind、补 refine 有损洞）。"""
    card = make_rule_card("rc.nk")
    bp_o = B.build_obligation_node_blueprint(card, _node(action="submit"), _META)
    bp_e = B.build_obligation_node_blueprint(card, _node(action="submit", node_kind="escalation"), _META)
    assert bp_o.identity.kind == bp_e.identity.kind == "artifact"  # refine 有损、kind 同
    assert bp_o.identity.predicate_kind == "obligation"
    assert bp_e.identity.predicate_kind == "escalation"
    assert bp_o.canonical_identity_hash != bp_e.canonical_identity_hash  # 携 raw → hash 异


def test_method_derived_method_keys_sentinel_hash_sensitivity():
    """§3.4② sentinel（blocker 2 订正）：method_keys_allowed 改（增删/改值）→ method-derived hash 变
    **且 node-main hash 也变**——v1 `_evaluate_node_main`（base_kind=='method'）直接用 method_keys 判
    open/closed，故 node-main 身份亦灌 method_keys（与 method-derived 同源 `_method_keys_qualifiers`）。"""
    wo = _workflow([]); wo["method_keys_allowed"] = ["pull_test"]
    card = make_rule_card("rc.mk", workflow_operands=wo)
    node = _node(action="conduct_validation_test")
    md0 = B.build_method_derived_blueprint(card, dict(node), _META).canonical_identity_hash
    main0 = B.build_obligation_node_blueprint(card, dict(node), _META).canonical_identity_hash

    wo2 = _workflow([]); wo2["method_keys_allowed"] = ["pull_test", "cctv_survey"]
    card2 = make_rule_card("rc.mk", workflow_operands=wo2)
    md1 = B.build_method_derived_blueprint(card2, dict(node), _META).canonical_identity_hash
    main1 = B.build_obligation_node_blueprint(card2, dict(node), _META).canonical_identity_hash

    assert md1 != md0, "method_keys_allowed 改 → method-derived hash 变"
    assert main1 != main0, "method_keys_allowed 改 → node-main hash 也变（node-main 判定依赖 method_keys）"
    # node-main 与 method-derived 同源 method_keys → 两身份 qualifiers 字节相同
    main_bp = B.build_obligation_node_blueprint(card, dict(node), _META)
    md_bp = B.build_method_derived_blueprint(card, dict(node), _META)
    assert main_bp.identity.qualifiers == md_bp.identity.qualifiers != ()
    # 但 SID 异（parts={"derived":"method"} vs {}）→ 身份不撞
    assert main_bp.identity.source_item_id != md_bp.identity.source_item_id
    # 非 method node（base_kind != method）的 node-main **不灌** method_keys（判定不涉）→ qualifiers=()
    non_method = _node(action="submit_x")  # refine → artifact，非 method
    assert B.build_obligation_node_blueprint(card, dict(non_method), _META).identity.qualifiers == ()


def test_v1_normalizes_unknown_node_kind_but_v2_rejects():
    """§3.1.1：v1 求值链 `evaluate_obligation_node` 对未知 node_kind 归一为 obligation（`from_dict`
    语义保留、不破旧测）；v2 STRICT 派生入口 raw-kind 闸拒之（`unknown_node_kind`）。"""
    fi = _empty_index()
    node = _node(node_kind="duty", action="conduct_x")
    # v1 归一：evaluate_obligation_node 走 from_dict → node_kind 归一 obligation、正常求值（不炸）
    out = D.evaluate_obligation_node(
        card=make_rule_card("rc.duty"),
        obligation_node=D.ObligationNodeDTO.from_dict(dict(node)),
        fact_index=fi, trigger_active=True, fact_pack_meta=_META,
    )
    assert out and out[0].closure_status in {"open", "closed", "blocked"}
    # v2 派生：raw-kind 闸拒未知 raw node_kind
    card_v2 = make_rule_card("rc.duty2", obligation_graph={"nodes": [node], "edges": []})
    with pytest.raises(ObligationContractError, match="unknown_node_kind"):
        B.derive_covered_card_blueprints(card_v2, _META)


def test_definition_and_exception_channels():
    """blocker 4：definition / exception channel 可表示、产 blueprint。"""
    from evo_agent_baseline.closure.identity_v2 import ObligationBlueprint

    card_def = make_rule_card(
        "rc.def",
        definitions=[{"definition_id": "d01", "term_key": "ri_supervision_team",
                      "definition_text": "t", "scope_note": "s", "source_quote_refs": ["sq01"]}],
    )
    dbp = B.build_definition_blueprint(card_def, card_def.definitions[0], _META)
    assert dbp.identity.source_channel == "definition"
    assert dbp.identity.predicate_kind == "" and dbp.identity.source_predicate_spec is None

    card_x = make_rule_card("rc.exc")
    exc = {"slot_id": "defect.class.present", "exception_kind": "exclusion", "qualifiers": {}}
    xbp = B.build_exception_blueprint(card_x, exc, _META)
    assert xbp.identity.source_channel == "exception"
    assert isinstance(xbp, ObligationBlueprint)


def test_scope_channel_removed_from_source_channel():
    """§5：可写 `scope` channel 已删——构造 source_channel='scope' 的身份 → ValidationError。"""
    from evo_agent_baseline.closure.identity_v2 import SourceChannel
    import typing

    assert "scope" not in typing.get_args(SourceChannel)
    assert "applicability" in typing.get_args(SourceChannel)


# =========================================================================== #
# 母病锚：threshold_regime_id 区分（桥接做不到的铁证）
# =========================================================================== #


def test_threshold_regime_id_star_v1_collides_v2_separates():
    """同卡/measure/op/value/unit/qualifiers 全同、**只 regime_id 不同** → v1 撞、v2 分。"""
    t1 = _th(threshold_regime_id="rc.x.c01.t01", measure_key="crack.width", value=7)
    t2 = _th(threshold_regime_id="rc.x.c01.t02", measure_key="crack.width", value=7)
    card = make_rule_card("rc.x", threshold_regimes=[t1, t2])
    fi = _empty_index()
    o1 = D.evaluate_threshold(card, dict(t1), fi, True, _META)
    o2 = D.evaluate_threshold(card, dict(t2), fi, True, _META)
    assert compute_obligation_id(o1) == compute_obligation_id(o2)  # v1 撞
    assert dedupe_key(o1) == dedupe_key(o2)
    b1 = B.build_threshold_blueprint(card, dict(t1), _META)
    b2 = B.build_threshold_blueprint(card, dict(t2), _META)
    assert b1.canonical_identity_hash != b2.canonical_identity_hash  # v2 分


# =========================================================================== #
# 全语料派生 + v2 双键 + 加性旁路
# =========================================================================== #


def test_full_corpus_derives_blueprints_cleanly():
    """397 真卡覆盖派生（v4：STRICT ≡ 覆盖，无剩余模型缺口）：channel 精确枚举锚 + 全 hash 唯一 + 零异常。

    v4 + blocker 1（§3.4③）：obligation_graph 全 node（396 obligation + 4 escalation + 1 prohibition
    + 4 edge + **12** method-derived（**仅结构可分节点**，`_node_method_separable`；v1=5：真卡 7 method
    产出 node 中 5 卡带 artifact_ids/deadline_ids 区分键才建独立 method-derived；DEBT-049 Phase3 U4 七卡
    action→conduct_validation_test 各 +1 可分 method-derived → 5+7=12）= **417**（v1=410））+
    workflow_deadline（25）。总 **2722**（v1=2715 + DEBT-049 Phase3 U4 七卡 method 化 +7）。
    """
    cards = _load_cards_decimal()
    assert len(cards) == 397
    by_channel: Dict[str, int] = defaultdict(int)
    hashes = []
    for card in cards:
        for bp in B.derive_covered_card_blueprints(card, _META):
            by_channel[bp.identity.source_channel] += 1
            hashes.append(bp.canonical_identity_hash)
    assert by_channel["applicability"] == 397  # §5：每卡一条 scope-audit
    assert by_channel["trigger"] == 376
    assert by_channel["slot_role"] == 769
    assert by_channel["threshold"] == 41
    assert by_channel["workflow_artifact"] == 326
    assert by_channel["workflow_deadline"] == 25  # v4：25 卡各 1 deadline
    assert by_channel["evidence"] == 370
    # DEBT-049 Phase3 U4：七卡 action perform_or_direct_validation_test→conduct_validation_test
    # → 各 node-main refine_action_kind 翻 method + separable（node 带 artifact_ids）→ 各 +1
    # method-derived blueprint。obligation_graph 通道 410→417（+7 method-derived；v1=410=401 node+4 edge+5 md）。
    assert by_channel["obligation_graph"] == 417  # 401 node + 4 edge + 12 method-derived（§3.4③；DEBT-049 Phase3 +7；v1=410）
    assert by_channel["definition"] == 1
    assert by_channel.get("exception", 0) == 0
    assert sum(by_channel.values()) == 2722  # DEBT-049 Phase3 U4 +7 method-derived（v1=2715）
    assert len(set(hashes)) == len(hashes)


def test_run_level_full_corpus_no_regime_conflict():
    """运行级全量派生（derive_run_blueprints）：真卡 41 regime_id 全唯一 → 零冲突、2722 条
    （v4+§3.4③+DEBT-049 Phase3 U4 七卡 method 化 +7；v1=2715）。"""
    cards = _load_cards_decimal()
    bps = B.derive_run_blueprints(cards, _META)
    assert len(bps) == 2722  # DEBT-049 Phase3 U4 +7（v1=2715）


def test_additive_side_channel_entry_produces_blueprints():
    """派生器加性入口 `derive_obligation_blueprints` 与 v1 并存产出 v2 blueprint。"""
    from evo_agent_baseline.closure.identity_v2 import ObligationBlueprint

    card = make_rule_card("rc.y", threshold_regimes=[_th(threshold_regime_id="rc.y.c01.t01", value=3)])
    bps = D.derive_obligation_blueprints(card, _META)
    assert bps and all(isinstance(b, ObligationBlueprint) for b in bps)
    assert any(b.identity.source_channel == "threshold" for b in bps)
    assert any(b.identity.source_channel == "applicability" for b in bps)


def test_v2_obligation_id_cross_building_distinct_n1():
    """N1：同身份跨楼 obligation_id 不撞（run_envelope 含 world/building）。"""
    card = make_rule_card("rc.z")
    th = _th(threshold_regime_id="rc.z.c01.t01", value=3)
    b1 = B.build_threshold_blueprint(card, dict(th), {**_META, "building_id": "BLD-A"})
    b2 = B.build_threshold_blueprint(card, dict(th), {**_META, "building_id": "BLD-B"})
    assert b1.canonical_identity_hash == b2.canonical_identity_hash
    assert B.blueprint_obligation_id(b1) != B.blueprint_obligation_id(b2)


# =========================================================================== #
# blind 扫描（正确 src 根 parents[2]，相对 import 感知，实测扫到依赖）
# =========================================================================== #

_SRC_ROOT = Path(B.__file__).resolve().parents[2]  # agent_v1/src
_FORBIDDEN_MODULE_PREFIXES = ("evo_agent_baseline.eval", "workflow_engine")
_FORBIDDEN_NAMES = ("TruthBundle", "threshold_evaluations")
_FIRST_PARTY = ("canonical_profile", "evo_agent_baseline", "workflow_engine", "research_kg")


def _module_to_path(mod: str) -> Optional[Path]:
    rel = mod.replace(".", "/")
    a = _SRC_ROOT / (rel + ".py")
    b = _SRC_ROOT / rel / "__init__.py"
    return a if a.exists() else (b if b.exists() else None)


def _resolve_relative(cur_mod: str, level: int, module: Optional[str]) -> str:
    parts = cur_mod.split(".")
    base = parts[: len(parts) - level]
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _collect_imports(path: Path, cur_mod: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module)
                for alias in node.names:
                    names.add(alias.name)
            elif node.level > 0:
                mods.add(_resolve_relative(cur_mod, node.level, node.module))
                for alias in node.names:
                    names.add(alias.name)
    return mods, names


def _transitive(start):
    seen, all_mods, all_names, reached = set(), set(), set(), []
    queue = list(start)
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = _module_to_path(mod)
        if path is None:
            continue
        reached.append(mod)
        mods, names = _collect_imports(path, mod)
        all_mods |= mods
        all_names |= names
        for m in mods:
            if m.startswith(_FIRST_PARTY) and m not in seen:
                queue.append(m)
    return reached, all_mods, all_names


def test_blind_scan_reaches_real_deps_and_is_clean():
    start = ["evo_agent_baseline.closure.blueprint_deriver"]
    assert _module_to_path(start[0]) is not None, "src 根解析错（空转风险）"
    reached, all_mods, all_names = _transitive(start)
    for dep in (
        "evo_agent_baseline.closure.blueprint_deriver",
        "evo_agent_baseline.closure.identity_v2",
        "evo_agent_baseline.closure.obligation_deriver",
        "evo_agent_baseline.closure.source_dtos",
        "canonical_profile.profile",
    ):
        assert dep in reached, f"blind 扫描未跑到依赖 {dep}（空转/相对 import 未跟进）"
    offending = {
        m for m in all_mods
        if any(m == p or m.startswith(p + ".") for p in _FORBIDDEN_MODULE_PREFIXES)
    }
    assert not offending, f"blind 违规 import 模块: {sorted(offending)}"
    assert not (set(all_names) & set(_FORBIDDEN_NAMES)), "blind 违规 import 名"


# =========================================================================== #
# codex 6 阻断复核·强制探针（fail-closed，全绿才算修透）
# =========================================================================== #

# 注：`_formula_th` 复用上文 R10 节定义（同 threshold_regime/measure/formula 构造器）。


# ---- 阻断① alias 折叠过度合并（v1 分 v2 合）修复 ----


def test_blocker1_diff_qualifier_same_canonical_no_fold():
    """阻断①：evidence 两 slot_ref 指**同 slot_id 异 qualifier**（代表不同 actor）→ **不折叠**
    （2 条 binding，各带 qualifier 指纹）；真语料母病（sapp6_tbl2 ri_rep_lvl1/lvl2）。"""
    card = make_rule_card(
        "rc.b1diff",
        slot_role_map=[
            _slot_role(slot_ref_id="srA", slot_id="supervision.site_visit.performed",
                       qualifiers={"actor_role_key": "ri_rep_lvl1"}),
            _slot_role(slot_ref_id="srB", slot_id="supervision.site_visit.performed",
                       qualifiers={"actor_role_key": "ri_rep_lvl2"}),
        ],
    )
    bp = B.build_evidence_blueprint(card, "for_completion", _evidence(slot_ref_ids=["srA", "srB"]), _META)
    site = [b for b in bp.identity.slot_bindings if b.canonical_key == "supervision.site_visit.performed"]
    assert len(site) == 2, "同 slot 异 qualifier（非纯别名）→ 不折叠"
    assert site[0].local_ref != site[1].local_ref  # qualifier 指纹进 local_ref


def test_blocker1_pure_alias_same_qualifier_folds():
    """阻断①：纯别名（同 slot_id **同 qualifier**）→ 折叠一条（R3 别名稳定保持）。"""
    card = make_rule_card(
        "rc.b1same",
        slot_role_map=[
            _slot_role(slot_ref_id="srA", slot_id="repair.required", qualifiers={"actor_role_key": "ri"}),
            _slot_role(slot_ref_id="srB", slot_id="repair.required", qualifiers={"actor_role_key": "ri"}),
        ],
    )
    bp = B.build_evidence_blueprint(card, "for_matching", _evidence(slot_ref_ids=["srA", "srB"]), _META)
    site = [b for b in bp.identity.slot_bindings if b.canonical_key == "repair.required"]
    assert len(site) == 1, "同 slot 同 qualifier 纯别名 → 折叠一条"


def test_blocker1_trigger_same_slot_diff_source_item_splits():
    """阻断①：两 trigger srA/srB 指同 slot、异 source_item（condition_id+slot_ref）→ v2 分。"""
    card = make_rule_card(
        "rc.b1tr",
        slot_role_map=[
            _slot_role(slot_ref_id="srA", slot_id="repair.required"),
            _slot_role(slot_ref_id="srB", slot_id="repair.required"),
        ],
    )
    b1 = B.build_trigger_blueprint(card, _trigger(condition_id="c1", slot_ref_id="srA"), _META)
    b2 = B.build_trigger_blueprint(card, _trigger(condition_id="c2", slot_ref_id="srB"), _META)
    assert (
        b1.identity.slot_bindings[0].canonical_key
        == b2.identity.slot_bindings[0].canonical_key
        == "repair.required"
    )
    assert b1.canonical_identity_hash != b2.canonical_identity_hash


def test_blocker1_R1_nonsingleton_equivalence_classes():
    """阻断① R1 非 singleton：构造别名/重复/异-ref-同-slot 变形的**非单元素等价类**——
    同语义（纯别名同 qualifier）→ 同哈希（等价类多成员）；异语义（异 qualifier / 异真值）→
    异哈希（替换'全 v2 hash 唯一'弱证：证折叠键既不过合并、也不过分裂）。"""
    card = make_rule_card("rc.b1eq")
    # 等价类①（非 singleton，3 成员）：measure 别名三形 → 同哈希
    h_alias = {
        B.build_threshold_blueprint(card, _th(threshold_regime_id="rg", measure_key=mk), _META).canonical_identity_hash
        for mk in ("crack_width", "measure.crack_width", "crackwidth")
    }
    assert len(h_alias) == 1, "纯别名同 qualifier → 同一等价类（非 singleton）"
    # 异语义：measure 真值变 → 落不同等价类
    h_other = B.build_threshold_blueprint(
        card, _th(threshold_regime_id="rg", measure_key="measure.spalling_area"), _META
    ).canonical_identity_hash
    assert h_other not in h_alias


# ---- 阻断② artifact 空键/悬空 hard-fail + formula 纳 output_measure ----


def test_blocker2_artifact_empty_and_dangling_hard_fail():
    """阻断②：空 artifact_key（有 id）+ evidence 悬空 artifact_id（不在 workflow multimap）→
    **hard-fail**（不降级 unresolved，C.9 artifact 维不可 unresolved）。"""
    card = make_rule_card("rc.b2art")
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.build_workflow_artifact_blueprint(
            card, {"artifact_id": "A1", "artifact_type": "form", "artifact_key": ""}, _META
        )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.build_evidence_blueprint(card, "for_matching", _evidence(artifact_ids=["A_ghost"]), _META)


def test_blocker2_formula_output_measure_mismatch_unsupported():
    """阻断②：登记式表达式 + 变量度量对，但 **output_measure 改**（threshold measure_key 换真度量）
    → 不再 fail-open 命中，hard-fail `unsupported_formula`。"""
    card = make_rule_card("rc.b2f")
    ok = _formula_th("n^2 - 2n + 3")
    b = B.build_threshold_blueprint(card, ok, _META)
    assert b.identity.source_predicate_spec.formula_id == "formula.pull_test_additional_after_failure"
    bad_output = dict(ok, measure_key="length.crack.width")  # output 改
    with pytest.raises(ObligationContractError, match="unsupported_formula"):
        B.build_threshold_blueprint(card, bad_output, _META)


# ---- 阻断③ typed ingress 聚合容器整体 model_validate ----


def test_blocker3_container_top_level_unknown_key_rejected():
    """阻断③：聚合源容器**顶层**未声明键 → 容器 model_validate ValidationError（非只遍历 leaf）。"""
    card = make_rule_card(
        "rc.b3top",
        trigger_conditions={"logic": "all", "items": [], "brand_new_top": "leak"},
    )
    with pytest.raises(ValidationError):
        B.derive_covered_card_blueprints(card, _META)


def test_blocker3_nested_unconsumed_key_rejected():
    """阻断③：**未消费部分**（recipients[].brand_new_nested）的嵌套越界键 → ValidationError
    （卡级对 workflow_operands 整体 model_validate，覆盖 closure 不读的 recipients）。"""
    wo = _workflow([])
    wo["recipients"] = [
        {"recipient_id": "r1", "recipient_type": "person", "recipient_key": "k",
         "delivery_mode": "post", "brand_new_nested": "leak"}
    ]
    card = make_rule_card("rc.b3nest", workflow_operands=wo)
    with pytest.raises(ValidationError):
        B.derive_covered_card_blueprints(card, _META)


# ---- v4 入口合一：STRICT ≡ 覆盖（§9，deadline / 普通 node 已可表示，不再 fail-closed）----


def test_v4_strict_entry_equals_covered_deadline_and_ordinary_node():
    """v4 入口合一：STRICT 总入口 `derive_card_blueprints` ≡ 覆盖入口——deadline / 普通 node 已可表示、
    不再 fail-closed；两入口对同卡产**逐 hash 相同**的 blueprint 集（§9）。"""
    graph = {
        "nodes": [{"obligation_node_id": "n01", "node_kind": "obligation", "actor": "ri",
                   "action": "conduct_x", "recipient_ids": [], "artifact_ids": [],
                   "deadline_ids": [], "trigger_condition_ids": []}],
        "edges": [],
    }
    card_node = make_rule_card("rc.v4node", obligation_graph=graph)
    strict = B.derive_card_blueprints(card_node, _META)
    covered = B.derive_covered_card_blueprints(card_node, _META)
    assert [b.canonical_identity_hash for b in strict] == [
        b.canonical_identity_hash for b in covered
    ]
    # 普通 node 现落 obligation_graph channel（predicate_kind=obligation、spec=None）
    node_bps = [b for b in strict if b.identity.source_channel == "obligation_graph"]
    assert len(node_bps) == 1 and node_bps[0].identity.predicate_kind == "obligation"

    wo = _workflow([])
    wo["deadlines"] = [{"deadline_id": "d1", "relation": "before",
                        "time_anchor_key": "repair.prescribed.completed",
                        "offset_value": 7, "offset_unit": "day"}]
    card_dl = make_rule_card("rc.v4dl", workflow_operands=wo)
    dl_bps = B.derive_card_blueprints(card_dl, _META)
    wd = [b for b in dl_bps if b.identity.source_channel == "workflow_deadline"]
    assert len(wd) == 1
    assert wd[0].identity.deadline_bindings[0].relation == "before"

    # 合成卡含 deadline + 普通 node 一起 → 两入口皆成功、逐 hash 相同
    card_both = make_rule_card("rc.v4both", obligation_graph=graph, workflow_operands=wo)
    assert [b.canonical_identity_hash for b in B.derive_card_blueprints(card_both, _META)] == [
        b.canonical_identity_hash for b in B.derive_covered_card_blueprints(card_both, _META)
    ]


# ---- 阻断①/② 入口级 fail-closed（覆盖入口 + 严格入口都炸，非只 builder）----


def test_blocker1_empty_artifact_hard_fails_at_both_entries():
    """阻断①（**入口级**）：空 artifact_id+artifact_key 的 workflow artifact / 空串 evidence
    artifact_id → **覆盖入口 `derive_covered_card_blueprints` + 严格入口 `derive_card_blueprints`
    都 hard-fail**（入口不 pre-filter 空值，非只直调 builder 才炸）。"""
    # workflow artifact 空 id+key（DTO 合法但空值 → artifact 维不可 unresolved）
    empty_art_card = make_rule_card(
        "rc.b1emptyart",
        workflow_operands=_workflow(
            [{"artifact_id": "", "artifact_type": "form", "artifact_key": ""}]
        ),
    )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(empty_art_card, _META)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_card_blueprints(empty_art_card, _META)
    # evidence.artifact_ids=[""] → 空串 artifact_id 送 hard-fail gate（旧 `if not aid: continue` 静默跳）
    empty_ev_card = make_rule_card(
        "rc.b1emptyev",
        evidence_requirements={
            "for_matching": [_evidence(artifact_ids=[""])],
            "for_submission": [],
            "for_completion": [],
        },
    )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(empty_ev_card, _META)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_card_blueprints(empty_ev_card, _META)


def test_blocker2_empty_container_and_nonrequired_slot_rejected_at_entry():
    """阻断②（**入口级无条件校验**）：空 dict 容器缺必填 + **非必需**槽位越界键 → ValidationError
    （覆盖入口 + 严格入口，非静默只返 applicability）。"""
    # trigger_conditions={} 缺必填 logic/items → 无条件整体 model_validate ValidationError
    empty_trig_card = make_rule_card("rc.b2emptytrig", trigger_conditions={})
    with pytest.raises(ValidationError):
        B.derive_covered_card_blueprints(empty_trig_card, _META)
    with pytest.raises(ValidationError):
        B.derive_card_blueprints(empty_trig_card, _META)
    # 非必需槽位（required=False）带越界键 → 逐条无条件 model_validate 拒（旧只校验 required=True 项）
    bad_slot_card = make_rule_card(
        "rc.b2slot",
        slot_role_map=[_slot_role(required=False, brand_new_slot_key="leak")],
    )
    with pytest.raises(ValidationError):
        B.derive_covered_card_blueprints(bad_slot_card, _META)
    with pytest.raises(ValidationError):
        B.derive_card_blueprints(bad_slot_card, _META)


# =========================================================================== #
# 2026-07-14 收官：系统性清「入口前置过滤跳过空/异常值、绕过 hard-fail gate」残留
# （codex 定位末 2 阻断 + 系统性扫描每一处前置过滤，各补空值→gate 两入口负测）
# =========================================================================== #


def _evidence_reqs(**buckets) -> Dict[str, Any]:
    """evidence_requirements 三 bucket 容器（缺省空组），供 required=False 反例卡构造。"""
    return {
        "for_matching": buckets.get("for_matching", []),
        "for_submission": buckets.get("for_submission", []),
        "for_completion": buckets.get("for_completion", []),
    }


def test_finalblocker1_nonrequired_evidence_empty_artifact_hard_fails_at_both_entries():
    """末阻断①（core，required=False 绕过修复）：**非必需** evidence 的空串 artifact_id →
    覆盖入口 `derive_covered_card_blueprints` + 严格入口 `derive_card_blueprints` **都 hard-fail**。

    旧代码只对 `required=True` evidence 建 blueprint（唯一到达 artifact hard-fail gate 的路径）；
    `required=False, artifact_ids=[""]` 通过 DTO（`List[str]` 视 "" 为合法元素）但整项被 required
    过滤跳过、两入口都不炸。修法：对所有 evidence req 先做 artifact 引用完整性校验、再 required 筛选。
    """
    empty_card = make_rule_card(
        "rc.fb1nreqempty",
        evidence_requirements=_evidence_reqs(
            for_matching=[_evidence(required=False, artifact_ids=[""])]
        ),
    )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(empty_card, _META)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_card_blueprints(empty_card, _META)


def test_finalblocker1_nonrequired_evidence_dangling_artifact_hard_fails_at_both_entries():
    """末阻断①（core 补）：**非必需** evidence 的悬空 artifact_id（不在 workflow multimap）→
    覆盖入口 + 严格入口都 `artifact_unresolved_hard_fail`（C.9：artifact 维不可 unresolved）。"""
    dangling_card = make_rule_card(
        "rc.fb1nreqdangling",
        evidence_requirements=_evidence_reqs(
            for_completion=[_evidence(required=False, artifact_ids=["A_ghost"])]
        ),
    )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(dangling_card, _META)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_card_blueprints(dangling_card, _META)


def test_finalblocker1_required_evidence_still_hard_fails_and_real_card_survives():
    """末阻断① 不误伤：required=True 空 artifact 照旧 hard-fail；无空/悬空 artifact 的合法卡不被
    完整性闸误拒（真语料 370 evidence 全 required、无空 artifact → 闸中性）。"""
    req_card = make_rule_card(
        "rc.fb1req",
        evidence_requirements=_evidence_reqs(
            for_matching=[_evidence(required=True, artifact_ids=[""])]
        ),
    )
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(req_card, _META)
    # 合法卡（无 artifact 引用的 evidence，required 与非必需混合）→ 完整性闸不误拒
    ok_card = make_rule_card(
        "rc.fb1ok",
        evidence_requirements=_evidence_reqs(
            for_matching=[_evidence(evidence_requirement_id="ev.a", required=True)],
            for_submission=[_evidence(evidence_requirement_id="ev.b", required=False)],
        ),
    )
    bps = B.derive_covered_card_blueprints(ok_card, _META)
    ev = [b for b in bps if b.identity.source_channel == "evidence"]
    assert len(ev) == 1  # 仅 required 项派生（非必需项过完整性闸但不派生）


def test_finalblocker2_prohibition_node_empty_artifact_hard_fails_at_both_entries():
    """末阻断②（core）：prohibition node 的空串 artifact_id → 直调 builder + 覆盖入口 + 严格入口
    **都 hard-fail**（旧 `for aid in node.artifact_ids: if not aid: continue` 静默跳空 artifact）。"""
    graph = {
        "nodes": [{"obligation_node_id": "n01", "node_kind": "prohibition", "actor": "ri",
                   "action": "conduct_x", "recipient_ids": [], "artifact_ids": [""],
                   "deadline_ids": [], "trigger_condition_ids": []}],
        "edges": [],
    }
    card = make_rule_card("rc.fb2node", obligation_graph=graph)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.build_obligation_node_blueprint(card, dict(graph["nodes"][0]), _META)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(card, _META)
    # 严格入口 ≡ 覆盖入口（v4 合一）→ reach node artifact gate、同样 hard-fail
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_card_blueprints(card, _META)


def test_finalblocker2_prohibition_node_dangling_artifact_hard_fails():
    """末阻断② 补：prohibition node 悬空 artifact_id（不在 workflow multimap）→ hard-fail（覆盖入口）。"""
    graph = {
        "nodes": [{"obligation_node_id": "n01", "node_kind": "prohibition", "actor": "ri",
                   "action": "conduct_x", "recipient_ids": [], "artifact_ids": ["A_ghost"],
                   "deadline_ids": [], "trigger_condition_ids": []}],
        "edges": [],
    }
    card = make_rule_card("rc.fb2dangling", obligation_graph=graph)
    with pytest.raises(ObligationContractError, match="artifact_unresolved_hard_fail"):
        B.derive_covered_card_blueprints(card, _META)


def test_finalblocker3_empty_applicability_hard_fails_at_both_entries():
    """末阻断③（codex 终审）：applicability 是九必存源容器之一（七字段全 required、进身份）——
    空 {} applicability 不得静默跳过；覆盖入口 + 严格入口都须 ValidationError。

    旧真值门 `if isinstance(applicability, dict) and applicability` 让空 {} 静默返 0 条
    applicability blueprint、两入口都不炸；修法：无条件 build_applicability_blueprint（内
    `ApplicabilityDTO.model_validate` → 空 {} 缺七 required 字段 → ValidationError，fail-closed）。
    fixtures.make_rule_card 的 applicability 默认由 `or` 改 `is not None`，故显式传 {} 不被默认对象掩盖。"""
    empty_appl_card = make_rule_card("rc.fb3emptyappl", applicability={})
    with pytest.raises(ValidationError):
        B.derive_covered_card_blueprints(empty_appl_card, _META)
    with pytest.raises(ValidationError):
        B.derive_card_blueprints(empty_appl_card, _META)


def test_finalblocker3_full_applicability_still_derives_and_real_card_survives():
    """末阻断③ 不误伤：完整 applicability（默认 fixture）→ 正常派生 1 条 applicability blueprint；
    真语料 397 卡全含完整 applicability，无条件校验对真卡零影响。"""
    card = make_rule_card("rc.fb3full")  # applicability 默认完整
    bps = B.derive_covered_card_blueprints(card, _META)
    appl = [b for b in bps if b.identity.source_channel == "applicability"]
    assert len(appl) == 1  # 完整 applicability 正常派生


def test_finalsweep_evidence_measure_key_empty_routed_to_gate_neutral():
    """系统性清前置过滤（evidence `if mk:` 去除·passthrough 中性证）：measure_keys=[""] 送
    `_make_binding` gate（measure 为 passthrough 维、空值 → None、`_finalize_bindings` 滤除）→
    无 spurious binding、不炸；非空 measure（unresolved）照常保留。去 `if mk:` 行为中性。"""
    card = make_rule_card("rc.fsmk")
    bp = B.build_evidence_blueprint(card, "for_matching", _evidence(measure_keys=[""]), _META)
    assert bp.identity.measure_bindings == ()  # 空 measure_key → gate 返 None → 无 binding
    bp2 = B.build_evidence_blueprint(
        card, "for_matching", _evidence(measure_keys=["", "unknown.m"]), _META
    )
    assert len(bp2.identity.measure_bindings) == 1  # 空滤除、非空 unresolved 保留
    assert bp2.identity.measure_bindings[0].resolution == "unresolved"


def test_finalsweep_evidence_deadfield_prefilter_dto_rejected_upstream():
    """系统性清前置过滤（evidence `artifact_keys` / `slot_ids` 的 `if X:` 去除·dead-field 记录）：
    二字段**不在** `EvidenceRequirementDTO`（extra=forbid）——带此键的 req 被上游 model_validate
    拒（ValidationError），其 `if X:` 前置过滤对已校验 req 不可达（无法触达 `_make_binding` gate）；
    去 `if X:` 纯消模式残留、无行为改变。此负测证 dead-field 由 DTO 层 fail-closed（非静默进入）。"""
    card = make_rule_card("rc.fsdead")
    with pytest.raises(ValidationError):
        B.build_evidence_blueprint(card, "for_matching", _evidence(artifact_keys=[""]), _META)
    with pytest.raises(ValidationError):
        B.build_evidence_blueprint(card, "for_matching", _evidence(slot_ids=[""]), _META)


def test_finalsweep_full_corpus_no_false_rejection():
    """去前置过滤后**零回归 + 真卡不误拒**：全 397 卡覆盖派生 2722 条（v4+§3.4③+DEBT-049 Phase3 U4 +7；
    v1=2715）、完整性闸/node artifact gate 对真卡零误拒（真语料 370 evidence 全 required、无空/悬空
    artifact，401 node 无空 artifact）。"""
    cards = _load_cards_decimal()
    assert len(cards) == 397
    total = 0
    by_channel: Dict[str, int] = defaultdict(int)
    for card in cards:
        for bp in B.derive_covered_card_blueprints(card, _META):
            total += 1
            by_channel[bp.identity.source_channel] += 1
    assert total == 2722  # DEBT-049 Phase3 U4 +7 method-derived（v1=2715）
    assert by_channel["evidence"] == 370
    assert by_channel["obligation_graph"] == 417  # DEBT-049 Phase3 U4 +7（v1=410）


# ---- v4 版本 bump v3→v4 ----


def test_identity_schema_is_v5():
    """v5：IDENTITY_SCHEMA == obligation_identity_v5；派生 blueprint 身份 schema 亦 v5。"""
    from evo_agent_baseline.closure.identity_v2 import IDENTITY_SCHEMA

    assert IDENTITY_SCHEMA == "obligation_identity_v5"
    card = make_rule_card("rc.v5")
    b = B.build_threshold_blueprint(card, _th(threshold_regime_id="rg"), _META)
    assert b.identity.identity_schema == "obligation_identity_v5"


# ---- 阻断⑥ Decimal 读径生产入口全 397 卡派生（13 卡 float 不再断线）----


def test_blocker6_decimal_bundle_all_397_derive():
    """阻断⑥：Decimal 读径生产入口 `derive_covered_blueprints_from_bundle` 全 397 卡覆盖派生成功
    （2722 条，v4+§3.4③+DEBT-049 Phase3 U4 七卡 method 化 +7；v1=2715），13 卡 float 阈值经
    Decimal 规范化落 literal（不再 float 断线）。"""
    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——证据闸不得 skip（skip=空转）")
    bps = B.derive_covered_blueprints_from_bundle(p, _META)
    assert len(bps) == 2722  # DEBT-049 Phase3 U4 +7（v1=2715）
    lits = {
        bp.identity.source_predicate_spec.literal_value_canonical
        for bp in bps
        if bp.identity.source_channel == "threshold" and bp.identity.source_predicate_spec
    }
    # 真语料 float 阈值 0.5 / 0.3 / 0.8 经 Decimal 规范化（v1 float 读径下这些卡断线）
    assert {"0.5", "0.3", "0.8"} <= lits, f"float 阈值 literal 未见 Decimal 规范化: {sorted(lits)[:10]}"
    # obligation_deriver 生产入口亦成功
    from evo_agent_baseline.closure import obligation_deriver as D2

    assert len(D2.derive_obligation_blueprints_from_bundle(p, _META)) == 2722  # DEBT-049 Phase3 U4 +7（v1=2715）
