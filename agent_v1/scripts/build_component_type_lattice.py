"""生成 component_type_lattice_v1.json 共享本体资产(DEBT-065 第一波)。

依据 spec 草案 v2.2 §2.2/§2.3。

架构定位:本资产是**共享本体**(组件类型的涵盖/排斥关系),供闭包验证器只读消费判定
组件结构不相容早退。W0 是 rule-blind 静态资源层「不消费 rule_card、不承接判定」,故排斥
关系不属 W0(叶集虽源于 W0 单类型链,但「排斥」是从正类型事实推出的本体断言)。正典归属
(独立共享本体规格包 vs v0.4 新章)待定,不影响本数据资产的生成与位置。

用法:python agent_v1/scripts/build_component_type_lattice.py
产物:agent_v1/regulations/rulecard_v2/mbis_cop_2023/component_type_lattice_v1.json
完整完整性断言在 tests/test_component_type_lattice.py(含跨 W0 生成计划/registry 对齐)。
"""
import json
import hashlib
import itertools
import pathlib
import sys

REG = pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2" / "mbis_cop_2023"

# 叶集/非叶集(v2.2 §2.2;二分穷尽词表 component_type_key 值域)
LEAF = ["external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"]
NON_LEAF = ["structural_component", "external_component", "ubw", "covered_component", "transfer_structure"]
# 涵盖关系(收编 projection_runtime_mapping 的 component_category_members,lattice 为唯一涵盖权威)
SUBSUMPTION = {"external_component": ["external_wall", "cantilevered_canopy", "wall_tiles"]}
# W0 registry 休眠(无组件计划生成)类型(v2.2 §2.2;来自 w0_ontology 勘察 19-11=8)
W0_DORMANT = [
    "access_panel", "floor_trap", "fire_resisting_wall", "escape_route",
    "smoke_vent", "fire_service_installation", "unknown_fire_component", "protective_render",
]
CANONICAL_HASH_ALGORITHM = "sha256(utf8(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)))"


def canonical_hash(obj):
    """v2.2 §2.2 规范哈希:排序键 + 紧凑分隔 + UTF-8,不 ASCII 转义。"""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build():
    vocab = json.loads((REG / "controlled_vocabularies_v1.json").read_text(encoding="utf-8"))
    mapping = json.loads((REG / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8"))
    cards = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))

    ct_domain = vocab["vocabularies"]["component_type_key"]
    alias = mapping["qualifier_value_aliases"]["component_type_key"]
    rulecard_bundle_id = cards.get("bundle_id")
    alias_mapping_version = mapping.get("version") or mapping.get("registry_id")
    w0_generation_plan_types = sorted(alias.keys())

    # 基础自检(完整断言在 test_component_type_lattice.py;此处只挡明显错乱,生成即失败)
    assert set(LEAF) | set(NON_LEAF) == set(ct_domain), "断言A: leaf∪non_leaf 未穷尽词表 component_type_key 值域"
    assert set(LEAF) & set(NON_LEAF) == set(), "断言A: leaf/non_leaf 相交"
    for native in w0_generation_plan_types:
        assert alias[native] in set(ct_domain), f"断言B: 原生类型 {native} 映射结果不在词表值域"
    assert set(w0_generation_plan_types) & set(W0_DORMANT) == set(), "生成计划与休眠清单相交"

    disjoint_pairs = [sorted(pair) for pair in itertools.combinations(sorted(LEAF), 2)]

    return {
        "version": "component_type_lattice.v1",
        "rulecard_bundle_id": rulecard_bundle_id,
        "leaf_types": LEAF,
        "non_leaf_types": NON_LEAF,
        "subsumption": SUBSUMPTION,
        "disjoint_pairs": disjoint_pairs,
        "w0_generation_plan_types": w0_generation_plan_types,
        "w0_dormant_types": W0_DORMANT,
        "vocabulary_snapshot_sha256": canonical_hash(sorted(ct_domain)),
        "alias_mapping_version": alias_mapping_version,
        "alias_mapping_snapshot_sha256": canonical_hash(alias),
        "canonical_hash_algorithm": CANONICAL_HASH_ALGORITHM,
        "provenance": {
            "authority": "W0 component_type_registry + 组件计划(单类型链)",
            "proof_anchors": ["models.py:447", "generator.py:502", "registry.py:1460", "fact_retriever.py:490"],
            "scope_statement": "互斥仅在 W0 生成模型内成立,不外推现实本体",
            "spec": "spec草案_DEBT065类型格与授权状态轴_v2.2",
        },
    }


def main():
    lattice = build()
    out = REG / "component_type_lattice_v1.json"
    out.write_text(json.dumps(lattice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("written:", out)
    print("vocabulary_snapshot_sha256:", lattice["vocabulary_snapshot_sha256"])
    print("alias_mapping_snapshot_sha256:", lattice["alias_mapping_snapshot_sha256"])
    print("disjoint_pairs:", len(lattice["disjoint_pairs"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
