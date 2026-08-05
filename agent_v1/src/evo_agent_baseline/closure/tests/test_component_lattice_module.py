"""component_lattice 判定逻辑模块单测(DEBT-065 第一波)。

覆盖 provable_disjoint、authorized_target(有效/stale/missing)、三阶段异常
(ingest hard-fail:快照失配/disjoint 不全/bundle 失配/重复卡/非叶目标/非法 evidence)。
"""
import copy
import json
import pathlib

import pytest

from evo_agent_baseline.closure.component_lattice import (
    Authorization,
    ComponentLattice,
    LatticeIngestError,
    card_fingerprint_v1,
    load_authorizations,
    load_component_lattice,
)

REG = pathlib.Path(__file__).resolve().parents[4] / "regulations" / "rulecard_v2" / "mbis_cop_2023"


@pytest.fixture(scope="module")
def sources():
    lattice = json.loads((REG / "component_type_lattice_v1.json").read_text(encoding="utf-8"))
    auth = json.loads((REG / "exact_fragment_target_authorizations_v1.json").read_text(encoding="utf-8"))
    vocab = json.loads((REG / "controlled_vocabularies_v1.json").read_text(encoding="utf-8"))
    mapping = json.loads((REG / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8"))
    cards_doc = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))
    return {
        "lattice": lattice,
        "auth": auth,
        "vocab_domain": vocab["vocabularies"]["component_type_key"],
        "alias_map": mapping["qualifier_value_aliases"]["component_type_key"],
        "bundle_id": cards_doc["bundle_id"],
        "cards_by_id": {c["rule_card_id"]: c for c in cards_doc["cards"]},
    }


@pytest.fixture(scope="module")
def lattice(sources):
    return load_component_lattice(
        sources["lattice"], sources["vocab_domain"], sources["alias_map"],
        expected_bundle_id=sources["bundle_id"],
    )


@pytest.fixture(scope="module")
def authorization(sources, lattice):
    return load_authorizations(sources["auth"], sources["bundle_id"], lattice.leaf_types)


# ---- 加载与结构 ----
def test_load_lattice_ok(lattice):
    assert isinstance(lattice, ComponentLattice)
    assert len(lattice.leaf_types) == 5
    # 🔴 2026-07-26（DEBT-076）：原断言 `== 10`（叶的 C(5,2)）锁死"互斥只在叶间"。
    # 裁定要求支持**跨层**互斥，故改为「叶全组合是下界」+ 跨层来自人裁关系表。
    import itertools as _it
    _leaf_pairs = {frozenset(c) for c in _it.combinations(lattice.leaf_types, 2)}
    assert len(_leaf_pairs) == 10
    assert _leaf_pairs <= lattice.disjoint_pairs, "叶×叶互斥必须全覆盖"


def test_load_auth_ok(authorization):
    assert isinstance(authorization, Authorization)
    # 高置信 55 + 中置信 27（2026-07-29 采纳草稿§四）= 82
    assert len(authorization.by_id) == 82


# ---- provable_disjoint ----
def test_provable_disjoint_leaf_pair(lattice):
    assert lattice.provable_disjoint("external_wall", "drainage_component") is True
    assert lattice.provable_disjoint("drainage_component", "external_wall") is True  # 对称


def test_provable_disjoint_same_leaf_false(lattice):
    assert lattice.provable_disjoint("external_wall", "external_wall") is False


def test_provable_disjoint_non_leaf_false(lattice):
    # 非叶(structural_component)不可证互斥(禁"未登记=互斥")
    assert lattice.provable_disjoint("external_wall", "structural_component") is False
    assert lattice.provable_disjoint("ubw", "drainage_component") is False


# ---- authorized_target ----
def test_authorized_target_valid(authorization, sources):
    rid = next(iter(authorization.by_id))
    card = sources["cards_by_id"][rid]
    target = authorization.authorized_target(card)
    assert target == authorization.by_id[rid].target
    assert target in {"external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"}


def test_authorized_target_stale_fingerprint(authorization, sources):
    rid = next(iter(authorization.by_id))
    card = copy.deepcopy(sources["cards_by_id"][rid])
    card["normalized_rule_text"] = (card.get("normalized_rule_text") or "") + " TAMPERED"
    assert authorized_fp_changed(card, authorization.by_id[rid].card_content_sha256)
    assert authorization.authorized_target(card) is None  # stale


def authorized_fp_changed(card, old_hash):
    return card_fingerprint_v1(card) != old_hash


def test_authorized_target_missing(authorization):
    assert authorization.authorized_target({"rule_card_id": "rc.mbis.nonexistent.c99", "version": {}}) is None


# ---- ingest hard-fail ----
def test_lattice_snapshot_mismatch_hardfail(sources):
    bad = copy.deepcopy(sources["lattice"])
    bad["vocabulary_snapshot_sha256"] = "deadbeef"
    with pytest.raises(LatticeIngestError):
        load_component_lattice(bad, sources["vocab_domain"], sources["alias_map"], expected_bundle_id=sources["bundle_id"])


def test_lattice_disjoint_incomplete_hardfail(sources):
    bad = copy.deepcopy(sources["lattice"])
    # 🔴 必须删一个**叶×叶**对（2026-07-26）：原写法 `[:-1]` 删排序后最后一对，
    # 而跨层互斥登记进来后那可能是跨层对——多/少跨层对**不该** hard-fail
    # （它们是人裁关系表的正当扩充），只有**缺叶对**才是类型格生成出错。
    import itertools as _it
    _leaves = bad["leaf_types"]
    _one_leaf_pair = sorted(next(_it.combinations(sorted(_leaves), 2)))
    bad["disjoint_pairs"] = [p for p in bad["disjoint_pairs"]
                            if sorted(p) != _one_leaf_pair]
    with pytest.raises(LatticeIngestError):
        load_component_lattice(bad, sources["vocab_domain"], sources["alias_map"], expected_bundle_id=sources["bundle_id"])


def test_lattice_partition_broken_hardfail(sources):
    bad = copy.deepcopy(sources["lattice"])
    # 破二分:从 non_leaf 抽掉一个真实存在的值(第二波后 ubw 已迁出组件类型轴,
    # 改用当前词表里仍在的 non_leaf 值构造,避免测试随词表变动失效)。
    bad["non_leaf_types"] = bad["non_leaf_types"][1:]
    with pytest.raises(LatticeIngestError):
        load_component_lattice(bad, sources["vocab_domain"], sources["alias_map"], expected_bundle_id=sources["bundle_id"])


def test_auth_bundle_mismatch_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    bad["rulecard_bundle_id"] = "wrong.bundle"
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types)


def test_auth_duplicate_card_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    bad["entries"].append(copy.deepcopy(bad["entries"][0]))  # 重复卡
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types)


def test_auth_nonleaf_target_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    bad["entries"][0]["exact_fragment_target_types"] = ["structural_component"]  # 非叶
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types)


def test_auth_bad_evidence_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    bad["entries"][0]["evidence"] = [{"slot_ref_id": None, "condition_id": None, "kind": "slot_role_map"}]
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types)


# ---- P1-3:类型格卡包配套校验 ----
def test_lattice_bundle_match_ok(sources):
    lat = load_component_lattice(
        sources["lattice"], sources["vocab_domain"], sources["alias_map"],
        expected_bundle_id=sources["bundle_id"],
    )
    assert lat.rulecard_bundle_id == sources["bundle_id"]


def test_lattice_bundle_mismatch_hardfail(sources):
    with pytest.raises(LatticeIngestError):
        load_component_lattice(
            sources["lattice"], sources["vocab_domain"], sources["alias_map"],
            expected_bundle_id="wrong.bundle",
        )


# ---- P1-4:授权摄入强失败护栏(证据引用存在性 + 每卡单组件值)----
def test_auth_evidence_ref_not_in_card_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    bad["entries"][0]["evidence"] = [
        {"slot_ref_id": "nonexistent.sr99", "condition_id": None, "kind": "slot_role_map"}
    ]
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types, cards_by_id=sources["cards_by_id"])


def test_auth_multi_component_value_hardfail(sources, lattice):
    bad = copy.deepcopy(sources["auth"])
    rid = bad["entries"][0]["rule_card_id"]
    bad["entries"][0]["evidence"] = [{"slot_ref_id": "sr01", "condition_id": None, "kind": "slot_role_map"}]
    fake_cards = dict(sources["cards_by_id"])
    fake_card = copy.deepcopy(fake_cards[rid])
    fake_card["slot_role_map"] = [
        {"slot_ref_id": "sr01", "qualifiers": {"component_type_key": "external_wall"}},
        {"slot_ref_id": "sr02", "qualifiers": {"component_type_key": "drainage_component"}},
    ]
    fake_card["threshold_regimes"] = []
    fake_card["trigger_conditions"] = {"items": []}
    fake_cards[rid] = fake_card
    with pytest.raises(LatticeIngestError):
        load_authorizations(bad, sources["bundle_id"], lattice.leaf_types, cards_by_id=fake_cards)
