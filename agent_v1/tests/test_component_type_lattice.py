"""component_type_lattice_v1.json 共享本体资产完整性测试(DEBT-065 第一波)。

对齐 spec 草案 v2.2 §2.3 完整性自校验:断言 A(词表二分)、断言 B(生成计划映射
全覆盖)、disjoint 全覆盖+对称+无自反、快照哈希往返、subsumption 成员归属、卡包绑定。

纯读资产 + 源文件,不 import runtime 包(资产层测试,不碰判定逻辑)。
"""
import hashlib
import itertools
import json
import pathlib

import pytest

REG = pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2" / "mbis_cop_2023"

def _registry_component_types() -> set:
    """P2:动态读 W0 component_type_registry 全类型(防生成器/测试硬编码同步漂移)。"""
    from workflow_engine.worldgen.registry import _build_registry_bundle
    bundle = _build_registry_bundle()
    ct_reg = next(r for r in bundle.registries if r.registry_id == "component_type_registry")
    return {rec["component_type"] for rec in ct_reg.records}


def _canonical_hash(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def lattice():
    return json.loads((REG / "component_type_lattice_v1.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vocab_domain():
    v = json.loads((REG / "controlled_vocabularies_v1.json").read_text(encoding="utf-8"))
    return v["vocabularies"]["component_type_key"]


@pytest.fixture(scope="module")
def alias_map():
    m = json.loads((REG / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8"))
    return m["qualifier_value_aliases"]["component_type_key"]


def test_assert_a_vocabulary_partition(lattice, vocab_domain):
    """断言 A: leaf ∪ non_leaf 穷尽二分词表 component_type_key 值域。"""
    leaf = set(lattice["leaf_types"])
    non_leaf = set(lattice["non_leaf_types"])
    assert leaf | non_leaf == set(vocab_domain)
    assert leaf & non_leaf == set()


def test_assert_b_generation_plan_alias(lattice, alias_map, vocab_domain):
    """断言 B-1: 每个生成计划类型有别名,且映射结果落入词表值域。"""
    domain = set(vocab_domain)
    for native in lattice["w0_generation_plan_types"]:
        assert native in alias_map, f"生成计划类型 {native} 缺别名"
        assert alias_map[native] in domain, f"{native} 映射 {alias_map[native]} 不在词表值域"


def test_generation_plan_equals_alias_keys(lattice, alias_map):
    """断言 B-2: 生成计划类型集恰为投影别名表的键集(生成计划=投影别名源)。"""
    assert sorted(lattice["w0_generation_plan_types"]) == sorted(alias_map.keys())


def test_generation_and_dormant_cover_registry(lattice):
    """断言 B-3(P2 动态): 生成计划 ∪ 休眠 = W0 registry 全类型(动态读 component_type_registry,
    防生成器/测试硬编码同步漂移),且不相交(禁静默丢弃)。"""
    registry_types = _registry_component_types()
    gen = set(lattice["w0_generation_plan_types"])
    dormant = set(lattice["w0_dormant_types"])
    assert gen & dormant == set(), "生成计划与休眠清单相交"
    assert gen | dormant == registry_types, (
        f"生成∪休眠 != W0 registry 全集; 差集 {(gen | dormant) ^ registry_types}"
    )


def test_disjoint_pairs_complete_symmetric_irreflexive(lattice):
    """disjoint: 叶集 C(n,2) 全覆盖 + 对称(规范化)+ 无自反。"""
    leaf = lattice["leaf_types"]
    pairs = {tuple(sorted(p)) for p in lattice["disjoint_pairs"]}
    expected = {tuple(sorted(c)) for c in itertools.combinations(leaf, 2)}
    assert pairs == expected
    assert len(lattice["disjoint_pairs"]) == len(expected) == 10
    for a, b in lattice["disjoint_pairs"]:
        assert a != b, "disjoint 含自反对"


def test_subsumption_members_are_leaves(lattice):
    """subsumption 父类 ∈ non_leaf,成员 ∈ leaf。"""
    leaf = set(lattice["leaf_types"])
    non_leaf = set(lattice["non_leaf_types"])
    for parent, members in lattice["subsumption"].items():
        assert parent in non_leaf, f"subsumption 父类 {parent} 不是 non_leaf"
        for m in members:
            assert m in leaf, f"subsumption 成员 {m} 不是叶型"


def test_snapshot_hash_roundtrip(lattice, vocab_domain, alias_map):
    """双快照哈希与当前源资产一致(v2.2 §2.3 ①,漂移即失败)。"""
    assert lattice["vocabulary_snapshot_sha256"] == _canonical_hash(sorted(vocab_domain))
    assert lattice["alias_mapping_snapshot_sha256"] == _canonical_hash(alias_map)


def test_rulecard_bundle_binding(lattice):
    """rulecard_bundle_id 与当前卡包一致(配套强校验前提)。"""
    cards = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))
    assert lattice["rulecard_bundle_id"] == cards.get("bundle_id")
