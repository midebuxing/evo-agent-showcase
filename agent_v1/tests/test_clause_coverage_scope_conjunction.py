"""#23 L1/L2：细作用域标签「真合取」的回归闸 + B5 物料可达性断言。

背景（`决议_23路线_20260805.md`）：真值 `scope_type == "component_class"` 的 187 行
用细粒度标签（`structural_steel` / `cladding` / …），世界侧归一后只有 8 个粗值
⇒ 严格相等两边不在同一层，结构上永远匹配不上。

决策门**否决了丙路**（粗类对齐）：那会让钢筋混凝土樑承接「結構鋼」条款，
世界一个字节没变而 60 行从「漏」变「覆盖」——**造覆盖不是补覆盖**。
本文件的存在理由就是把「丙路的病」钉成不可能：**只测命中 > 0 是不够的，
必须同时测不该命中的没命中**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_v1" / "scripts"))
sys.path.insert(0, str(ROOT / "agent_v1" / "src"))

import score_clause_coverage as scorer  # noqa: E402

STEEL = {"structural_steel": [("structural_component",
                               frozenset({"structural_steel_section", "steel_transfer_beam"}))]}


def _pack(fragment_id: str, component_type_key: str, component_id: str, material: str) -> dict:
    """造一份与批产物 `fact_pack.json` 同形的最小事实包。"""
    return {"facts": [
        {"carrier_type": "fragment", "carrier_id": fragment_id, "slot_id": "fragment_role",
         "qualifiers": {"component_type_key": component_type_key}},
        {"slot_id": "w0_component_identity", "carrier_type": "fragment", "carrier_id": fragment_id,
         "qualifiers": {"fragment_id": fragment_id, "component_id": component_id,
                        "canonical_component_type": component_type_key}},
        {"carrier_type": "component", "carrier_id": component_id, "slot_id": "material_system",
         "qualifiers": {}, "value_json": json.dumps(material)},
    ]}


def _matches(scope_id: str, pack: dict, fragment_id: str, conjunctions=STEEL) -> bool:
    labels = scorer._fragment_scope_labels(pack, conjunctions)
    return scorer._scope_matches({"scope_type": "component_class", "scope_id": scope_id},
                                 {"fragment_id": fragment_id, "kind": "action"}, labels)


# ── 正向 ────────────────────────────────────────────────────────────────────

def test_steel_structural_fragment_matches_fine_label() -> None:
    pack = _pack("FRG-1", "structural_component", "CMP-1", "structural_steel_section")
    assert _matches("structural_steel", pack, "FRG-1") is True


def test_coarse_label_still_matches_after_refinement() -> None:
    """🔴 细标签是**追加**不是改写：钢片段必须**同时**满足粗标签。

    做成「细化替换」的话，scope_id 落在 8 个粗值里的真值行会被整批打掉——
    那是一次静默的分子塌方，召回会掉而没有任何告警。
    """
    pack = _pack("FRG-1", "structural_component", "CMP-1", "structural_steel_section")
    assert _matches("structural_component", pack, "FRG-1") is True
    assert _matches("structural_steel", pack, "FRG-1") is True


# ── 反向假匹配（第七段，本文件的核心）────────────────────────────────────────

def test_rc_structural_fragment_must_not_match_steel() -> None:
    """钢筋混凝土樑**不得**被判成結構鋼——这正是丙路 60 行假覆盖的形状。"""
    pack = _pack("FRG-1", "structural_component", "CMP-1", "reinforced_concrete")
    assert _matches("structural_steel", pack, "FRG-1") is False
    assert _matches("structural_component", pack, "FRG-1") is True


def test_ubw_cold_formed_steel_must_not_match_structural_steel() -> None:
    """僭建物的冷弯型钢**不得**被判成 §5.4.2 結構鋼。

    三者 `material_class` 同为 `structural_steel` ⇒ **只比 material_class 会误纳**。
    本条就是「必须下沉到 material_system 粒度」这句话的可执行形态。
    """
    pack = _pack("FRG-1", "ubw", "CMP-1", "cold_formed_steel")
    assert _matches("structural_steel", pack, "FRG-1") is False


def test_steel_material_on_wrong_component_class_must_not_match() -> None:
    """物料对、构件类不对 ⇒ 不匹配（真合取的另一半）。"""
    pack = _pack("FRG-1", "fire_safety_component", "CMP-1", "structural_steel_section")
    assert _matches("structural_steel", pack, "FRG-1") is False


def test_fragment_without_material_never_gains_fine_label() -> None:
    """取不到物料 ⇒ 只有粗标签，绝不猜。"""
    pack = {"facts": [
        {"carrier_type": "fragment", "carrier_id": "FRG-1", "slot_id": "fragment_role",
         "qualifiers": {"component_type_key": "structural_component"}}]}
    assert _matches("structural_steel", pack, "FRG-1") is False
    assert _matches("structural_component", pack, "FRG-1") is True


# ── 缺省等价 ────────────────────────────────────────────────────────────────

def test_empty_table_is_bitwise_equivalent_to_strict_equality() -> None:
    """空登记表 ⇒ 与 2026-08-05 之前的严格相等逐位等价。"""
    pack = _pack("FRG-1", "structural_component", "CMP-1", "structural_steel_section")
    assert _matches("structural_steel", pack, "FRG-1", conjunctions={}) is False
    assert _matches("structural_component", pack, "FRG-1", conjunctions={}) is True


# ── 供给侧与作用域匹配必须同源 ──────────────────────────────────────────────

def test_supply_side_and_scope_match_share_one_ruler() -> None:
    """有钢片段 ⇒ 不许再报「本栋无该类片段」；无钢 ⇒ 必须报。

    两处若用不同判据，会出现「匹配得上却仍记供给侧缺口」的自相矛盾，
    而供给侧计数正是轨二 `L1_no_world_asset` 的来源。
    """
    item = {"normative_item_id": "t", "source_clause_id": "X", "scope_type": "component_class",
            "scope_id": "structural_steel", "applicable": True, "expected_card_ids": ["rc.a"]}
    bundle = {"rc.a"}

    steel = scorer._fragment_scope_labels(
        _pack("FRG-1", "structural_component", "CMP-1", "structural_steel_section"), STEEL)
    assert scorer._classify_item(item, [], bundle, bundle, steel) != "supply_side_no_fragment_of_class"

    rc = scorer._fragment_scope_labels(
        _pack("FRG-1", "structural_component", "CMP-1", "reinforced_concrete"), STEEL)
    assert scorer._classify_item(item, [], bundle, bundle, rc) == "supply_side_no_fragment_of_class"


# ── 裸字符串 fail-loud（防子串匹配这条不报错的假覆盖通道）────────────────────

def test_bare_string_labels_fail_loud() -> None:
    """`"external" in "external_wall"` 为真 —— 裸字符串会静默退化成子串匹配。"""
    with pytest.raises(TypeError):
        scorer._labels_of({"FRG-1": "external_wall"}, "FRG-1")
    with pytest.raises(TypeError):
        scorer._present_labels({"FRG-1": "external_wall"})


# ── 加载器 fail-loud ────────────────────────────────────────────────────────

@pytest.mark.parametrize("entries, needle", [
    ([{"scope_id": "x", "pairs": [{"component_type_key": "structural_component",
                                   "material_systems": []}]}], "material_systems"),
    ([{"scope_id": "x", "pairs": [{"component_type_key": "", "material_systems": ["a"]}]}],
     "component_type_key"),
    ([{"scope_id": "x", "pairs": []}], "pairs"),
    ([{"pairs": [{"component_type_key": "a", "material_systems": ["b"]}]}], "scope_id"),
])
def test_loader_rejects_degenerate_conjunctions(tmp_path: Path, entries, needle) -> None:
    """真合取要求两侧非空——写成半边即退回丙路，必须 fail-loud 而不是静默放行。"""
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema_version": "component_class_scope_conjunction_v1",
                             "entries": entries}), encoding="utf-8")
    with pytest.raises(ValueError, match=needle):
        scorer._load_scope_conjunctions(p)


def test_loader_rejects_duplicate_scope_id(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    entry = {"scope_id": "x", "pairs": [{"component_type_key": "a", "material_systems": ["b"]}]}
    p.write_text(json.dumps({"schema_version": "component_class_scope_conjunction_v1",
                             "entries": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        scorer._load_scope_conjunctions(p)


def test_loader_rejects_wrong_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema_version": "nope", "entries": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        scorer._load_scope_conjunctions(p)


# ── B5：物料可达性断言（官方商议补的门）──────────────────────────────────────

def test_b5_every_registered_material_is_structurally_reachable() -> None:
    """B5：登记表依赖的每个 `material_system` 必须

    ①在 `material_system_registry` 里登记；
    ②出现在**某个** `component_type` 的 `material_compatibility` 里；
    ③该 `component_type` 归一后的键 == 登记的 `component_type_key`；
    ④该 `component_type` **有片段模板**。

    缺 ④ 就是本仓库反复出现的第三种「改了等于没改」：
    `curtain_wall_glazing` / `metal_louver_fin` / `glass_balustrade_panel` / `metal_gate`
    四个物料**在注册表里登记了、却不在任何 component_type 的 compat 里** ⇒ 世界永不产出；
    `intumescent_coating` 挂的 `fire_resisting_wall` 有 compat 却**没有片段模板** ⇒ 同样永不产出。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle

    bundle = _build_registry_bundle()
    tables = {t.registry_id: t for t in bundle.registries}
    known_materials = {r["material_system"] for r in tables["material_system_registry"].records}
    template_types = {r.get("component_type") for r in tables["fragment_template_registry"].records}
    aliases = json.loads((ROOT / "agent_v1/regulations/rulecard_v2/mbis_cop_2023/"
                          "projection_runtime_mapping_v1.json").read_text(encoding="utf-8"))
    alias = aliases["qualifier_value_aliases"]["component_type_key"]

    reachable: dict[str, set[str]] = {}
    for record in tables["component_type_registry"].records:
        key = alias.get(record["component_type"], record["component_type"])
        if record["component_type"] not in template_types:
            continue  # 无片段模板 ⇒ 结构上永不产片段，不算可达
        reachable.setdefault(key, set()).update(record.get("material_compatibility") or [])

    table = scorer._load_scope_conjunctions()
    assert table, "合取登记表为空——L1/L2 等于没落地"
    problems = []
    for scope_id, pairs in table.items():
        for component_type_key, materials in pairs:
            for material in materials:
                if material not in known_materials:
                    problems.append(f"{scope_id}: {material} 不在 material_system_registry")
                elif material not in reachable.get(component_type_key, set()):
                    problems.append(
                        f"{scope_id}: ({component_type_key} ∧ {material}) 世界结构上不可达"
                        f"——没有任何**带片段模板**的 component_type 同时满足这两条")
    assert not problems, "B5 物料可达性断言失败：\n" + "\n".join(problems)
