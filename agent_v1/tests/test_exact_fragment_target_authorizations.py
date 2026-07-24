"""exact_fragment_target_authorizations_v1.json 授权表完整性测试(DEBT-065 第一波)。

对齐 spec 草案 v2.2 §2.5:card_fingerprint.v1 指纹可复算、单目标∈叶集、evidence 格式契约、
每卡单组件值、rule_card_id 唯一、bundle 绑定。纯读资产,不 import runtime 包。
"""
import hashlib
import json
import pathlib

import pytest

REG = pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2" / "mbis_cop_2023"
LEAF = {"external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"}
EVIDENCE_KINDS = {"slot_role_map", "threshold_regimes", "trigger_conditions"}


def _canonical_hash(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def table():
    return json.loads((REG / "exact_fragment_target_authorizations_v1.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cards_by_id():
    doc = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))
    return doc["bundle_id"], {c["rule_card_id"]: c for c in doc["cards"]}


def test_table_schema(table):
    assert table["version"] == "exact_fragment_target_authorizations.v1"
    assert table["card_fingerprint_profile"] == "card_fingerprint.v1"
    assert isinstance(table["entries"], list) and table["entries"]


def test_bundle_id_matches(table, cards_by_id):
    bundle_id, _ = cards_by_id
    assert table["rulecard_bundle_id"] == bundle_id


def test_rule_card_id_unique(table):
    ids = [e["rule_card_id"] for e in table["entries"]]
    assert len(ids) == len(set(ids)), "授权条目 rule_card_id 重复"


def test_single_leaf_target(table):
    for e in table["entries"]:
        tgt = e["exact_fragment_target_types"]
        assert isinstance(tgt, list) and len(tgt) == 1, f"{e['rule_card_id']} 非单目标"
        assert tgt[0] in LEAF, f"{e['rule_card_id']} 目标 {tgt[0]} 非叶型"


def test_evidence_contract(table):
    """v2.2 §2.5:每 evidence 项 slot_ref_id/condition_id 至少一非空 + kind 枚举。"""
    for e in table["entries"]:
        assert e["evidence"], f"{e['rule_card_id']} evidence 为空"
        for ev in e["evidence"]:
            assert ev["kind"] in EVIDENCE_KINDS, f"{e['rule_card_id']} kind {ev['kind']} 非法"
            assert ev.get("slot_ref_id") or ev.get("condition_id"), f"{e['rule_card_id']} evidence 无定位"


def test_card_fingerprint_recomputable(table, cards_by_id):
    """每条目 card_content_sha256 可从原始卡对象复算(指纹 = 判据锚)。"""
    _, by_id = cards_by_id
    for e in table["entries"]:
        card = by_id.get(e["rule_card_id"])
        assert card is not None, f"卡不存在: {e['rule_card_id']}"
        binding = e["card_version_binding"]
        assert binding["card_content_sha256"] == _canonical_hash(card), f"{e['rule_card_id']} 指纹失配"
        assert binding["authoring_revision"] == card["version"].get("authoring_revision")
        assert binding["interpretation_revision"] == card["version"].get("interpretation_revision")


def test_single_component_value_invariant(table, cards_by_id):
    """每卡单组件值不变量:授权卡的所有 component_type_key 值恒等于其单一目标。"""
    _, by_id = cards_by_id
    for e in table["entries"]:
        card = by_id[e["rule_card_id"]]
        target = e["exact_fragment_target_types"][0]
        values = set()
        for slot in card.get("slot_role_map", []):
            q = (slot.get("qualifiers") or {}).get("component_type_key")
            if q:
                values.add(q)
        for reg in card.get("threshold_regimes", []):
            q = (reg.get("qualifiers") or {}).get("component_type_key")
            if q:
                values.add(q)
        tc = card.get("trigger_conditions", {})
        for it in (tc.get("items", []) if isinstance(tc, dict) else []):
            q = (it.get("qualifiers") or {}).get("component_type_key")
            if q:
                values.add(q)
        assert values <= {target}, f"{e['rule_card_id']} 组件值 {values} 非单一目标 {target}"


def test_evidence_refs_resolve(table, cards_by_id):
    """evidence 引用存在性:slot_ref_id 能在该卡内定位到。"""
    _, by_id = cards_by_id
    for e in table["entries"]:
        card = by_id[e["rule_card_id"]]
        slot_refs = {s.get("slot_ref_id") for s in card.get("slot_role_map", [])}
        slot_refs |= {r.get("regime_id") or r.get("slot_ref_id") for r in card.get("threshold_regimes", [])}
        for ev in e["evidence"]:
            if ev.get("slot_ref_id"):
                assert ev["slot_ref_id"] in slot_refs, f"{e['rule_card_id']} evidence slot_ref {ev['slot_ref_id']} 无法定位"
