"""阅卷器 `component_class` 作用域两件（2026-08-07 波次二补完阶段 0）。

**第一件·回归闸**：`_scope_matches` 的 `fragment_id is None` 放行。
它 2026-07-29 立、**2026-08-05（#23）把「单值严格相等」改成「标签集合成员」时被
顺手删掉**，而函数 docstring 与注释当时仍宣称它在生效 —— 一次沉默的口径回归。
后果实测（批 `poolv2_llm_seed401_20260806` × 真值 v2）：§4.3.2/§4.3.3 一族
**49 条**已产出、`satisfaction_status=unknown` 而 `fragment_id=None` 的义务被全部滤掉，
条目落 `retrieved_no_evaluation`。本文件把它钉死成变异可证：删掉那一支，下面第一组必红。

**第二件·原生构件类对齐**：`component_class_scope_native_alias_v1.json`。
真值用**条款对象类**（懸臂式伸出構築物／欄杆類／外牆飾面），而片段标签只有
「归一后的粗 `component_type_key`」与「合取表细标签」两路，都看不到世界原生
`component_type` ⇒ `balcony_slab`（露台）与 `parapet_wall`（護牆）双双被归一成
`external_component`，「本栋有露台、有護牆」在阅卷器眼里成了「没有懸臂式伸出構築物、
没有欄杆類」。

🔴 **本文件的判别力来自反向断言**：只测「对齐后能匹配上」是不够的 ——
露台与護牆在池 v2 上**粗类与物料完全相同**，若判据退化成粗类或物料，
两者会互相冒名，而正向断言照样全绿。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_v1" / "scripts"))
sys.path.insert(0, str(ROOT / "agent_v1" / "src"))

import score_clause_coverage as scorer  # noqa: E402

REGULATION = ROOT / "agent_v1/regulations/markdown/MBIS_CoP_2023.md"

#: 中文正文里的「批盪及瓦片」两类物料（§5.3.1 节名 ＋ §3.3.1(a)(i)）。
FINISH_MATERIALS = frozenset(
    {"plaster_finish", "polymer_render", "masonry_plaster", "tile_finish"})


def _pack(fragment_id: str, coarse_key: str, component_id: str,
          native_type: str | None = None, material: str | None = None) -> dict:
    """造一份与批产物 `fact_pack.json` 同形的最小事实包。

    `native_type` 走的是**组件载体上 `slot_id == "component_type"` 的事实**，
    与归一后的 `canonical_component_type` 分开写 —— 本文件测的就是这两层的差。
    """
    facts = [
        {"carrier_type": "fragment", "carrier_id": fragment_id, "slot_id": "fragment_role",
         "qualifiers": {"component_type_key": coarse_key}},
        {"slot_id": "w0_component_identity", "carrier_type": "fragment",
         "carrier_id": fragment_id,
         "qualifiers": {"fragment_id": fragment_id, "component_id": component_id,
                        "canonical_component_type": coarse_key}},
    ]
    if native_type is not None:
        facts.append({"carrier_type": "component", "carrier_id": component_id,
                      "slot_id": "component_type", "qualifiers": {},
                      "value_json": json.dumps(native_type)})
    if material is not None:
        facts.append({"carrier_type": "component", "carrier_id": component_id,
                      "slot_id": "material_system", "qualifiers": {},
                      "value_json": json.dumps(material)})
    return {"facts": facts}


def _item(scope_id: str) -> dict:
    return {"scope_type": "component_class", "scope_id": scope_id}


# ════════════════════════════════════════════════════════════════════════════
# 第一件：`fragment_id is None` 放行（变异可证 —— 删掉那一支，本组必红）
# ════════════════════════════════════════════════════════════════════════════

def _match_unattached(obligation: dict, scope_id: str = "structural_component") -> bool:
    """作用域项 vs 一条**未挂片段**的义务。标签表故意留空，排除标签路径的干扰。"""
    return scorer._scope_matches(_item(scope_id), obligation, {})


def test_unattached_substantive_obligation_is_admitted() -> None:
    """🔴 这一条就是被 #23 删掉的那一格。

    删掉 `if frag_id is None: return not _is_bookkeeping(obligation)` 之后，
    `_labels_of(frag_labels, None)` 返回空集 ⇒ `in` 恒 False ⇒ 本断言必红。

    语义依据（2026-07-29 已裁）：详细调查一族的评估对象本就是「楼宇整體狀況」，
    义务不挂片段是**对的**；系统评过了，不该被记成漏。
    """
    assert _match_unattached(
        {"fragment_id": None, "kind": "action", "satisfaction_status": "unknown"}) is True


@pytest.mark.parametrize("obligation, why", [
    ({"fragment_id": None, "kind": "trigger"}, "触发器求值行不是义务本身"),
    ({"fragment_id": None, "kind": "scope"}, "作用域求值行不是义务本身"),
    ({"fragment_id": None, "kind": "action", "trigger_state": "inactive"},
     "触发条件求值为假 —— 拿它充当覆盖是 2026-07-28 反方审议裁定过的假覆盖"),
    ({"fragment_id": None, "kind": "action",
      "notes": scorer.STRUCTURAL_NA_NOTE_PREFIX + "…"},
     "结构早退记录不构成实质评估"),
])
def test_unattached_bookkeeping_is_still_rejected(obligation, why) -> None:
    """🔴 恢复的是**非簿记**放行，不是裸放行。

    裸恢复（`return True`）会让「只剩触发器簿记」的条目翻成
    `correctly_inactive_by_trigger` ——`裁定_11条供给侧_20260807.md` §七.1 点名的假覆盖形状。
    ⚠️ 这一支同时是 `component_class` 路径上**唯一**的 `_is_bookkeeping` 关卡：
    调用方 `_classify_item` 的 `kept` 过滤只作用于楼级作用域。
    """
    assert _match_unattached(obligation) is False, why


def test_attached_obligation_still_judged_by_label_membership() -> None:
    """挂了片段的义务不走上面那一支 —— 「挂在别的类型片段上仍判漏」必须继续成立。"""
    labels = {"FRG-1": frozenset({"external_wall"})}
    assert scorer._scope_matches(
        _item("structural_component"), {"fragment_id": "FRG-1", "kind": "action"},
        labels) is False
    assert scorer._scope_matches(
        _item("external_wall"), {"fragment_id": "FRG-1", "kind": "action"},
        labels) is True


def test_unattached_unknown_obligation_lifts_item_out_of_missed() -> None:
    """端到端：整项只有未挂片段的 unknown 记录时，落 `evaluated_unknown` 而非漏。

    这正是那 49 条的形状（`kind=action`＋`kind=evidence`，`satisfaction_status=unknown`、
    `closure_status=open`、`fragment_id=None`）。删掉放行支 ⇒ 落
    `retrieved_no_evaluation`（`MISSED_STATES` 成员）⇒ 本断言必红。
    """
    item = {"normative_item_id": "t", "source_clause_id": "4.3.2",
            "scope_type": "component_class", "scope_id": "structural_component",
            "applicable": True, "expected_card_ids": ["rc.a"]}
    obligations = [{"source_rule_card_id": "rc.a", "fragment_id": None, "kind": "action",
                    "satisfaction_status": "unknown", "closure_status": "open"}]
    labels = {"FRG-1": frozenset({"structural_component"})}
    state = scorer._classify_item(item, obligations, {"rc.a"}, {"rc.a"}, labels)
    assert state == "evaluated_unknown"
    assert state not in scorer.MISSED_STATES


# ════════════════════════════════════════════════════════════════════════════
# 第二件：世界原生构件类对齐（正向 + 反向互斥 + 加载器 fail-loud + 引文核对）
# ════════════════════════════════════════════════════════════════════════════

def _labels(pack: dict, fragment_id: str, aliases=None) -> frozenset[str]:
    return scorer._fragment_scope_labels(pack, {}, aliases)[fragment_id]


SHIPPED = None


def shipped_aliases():
    global SHIPPED
    if SHIPPED is None:
        SHIPPED = scorer._load_scope_native_aliases()
    return SHIPPED


# ── 正向：三条对齐规则各自命中 ──────────────────────────────────────────────

@pytest.mark.parametrize("native, material, expected", [
    ("balcony_slab", "reinforced_concrete", "cantilevered_canopy"),
    ("canopy", "reinforced_concrete", "cantilevered_canopy"),
    ("parapet_wall", "reinforced_concrete", "balustrade_railing"),
])
def test_shipped_table_aligns_external_component_natives(native, material, expected) -> None:
    """露台／簷篷／護牆：归一层把它们全吞成 `external_component`，对齐后各归各位。"""
    coarse = "cantilevered_canopy" if native == "canopy" else "external_component"
    pack = _pack("FRG-1", coarse, "CMP-1", native, material)
    assert expected in _labels(pack, "FRG-1", shipped_aliases())


@pytest.mark.parametrize("native, coarse, material", [
    ("external_wall", "external_wall", "polymer_render"),
    ("external_wall", "external_wall", "plaster_finish"),
    ("external_wall", "external_wall", "tile_finish"),
    ("wall_tile_finish", "wall_tiles", "tile_finish"),
])
def test_shipped_table_aligns_wall_finishes(native, coarse, material) -> None:
    """§5.3.1「批盪及瓦片」：外牆掷到批盪／瓦片物料时才算外牆飾面。"""
    pack = _pack("FRG-1", coarse, "CMP-1", native, material)
    assert "external_wall_finish" in _labels(pack, "FRG-1", shipped_aliases())


def test_alignment_labels_are_additive_not_replacing() -> None:
    """🔴 对齐标签是**追加**：粗标签照旧成立，否则落在 8 个粗值上的真值行会整批被打掉。"""
    pack = _pack("FRG-1", "external_component", "CMP-1", "parapet_wall", "reinforced_concrete")
    labels = _labels(pack, "FRG-1", shipped_aliases())
    assert "external_component" in labels
    assert "balustrade_railing" in labels


# ── 反向：本表存在的全部理由 ────────────────────────────────────────────────

def test_balcony_and_parapet_must_not_wear_each_others_label() -> None:
    """🔴 本文件最要紧的一条。

    池 v2 上 `balcony_slab` 与 `parapet_wall` 的**粗类与物料完全相同**
    （`external_component` ∧ `reinforced_concrete`）⇒ 合取表结构上表达不了两者的差，
    只能同时给两个标签（露台判成護牆、護牆判成露台）。
    判据一旦退化成粗类或物料，正向断言照样全绿而这一条会红 —— 它就是那道分辨力。
    """
    balcony = _pack("FRG-B", "external_component", "CMP-B", "balcony_slab", "reinforced_concrete")
    parapet = _pack("FRG-P", "external_component", "CMP-P", "parapet_wall", "reinforced_concrete")
    assert "balustrade_railing" not in _labels(balcony, "FRG-B", shipped_aliases())
    assert "cantilevered_canopy" not in _labels(parapet, "FRG-P", shipped_aliases())


@pytest.mark.parametrize("material", [
    "curtain_wall_aluminium_frame",   # 幕牆 —— §5.3.4 另有独立修葺章节
    "metal_gate",                     # 金屬閘 —— §5.3.6(c)
    "metal_louver_fin",               # 金屬百葉 —— §5.3.3
    "reinforced_concrete",            # 結構本體，不是飾面
    "clay_brick",                     # 砌體 —— §5.4.3
    "stone_cladding",                 # 覆蓋層 —— §5.3.2，合取表已给 `cladding`
])
def test_external_wall_without_finish_material_is_not_a_wall_finish(material) -> None:
    """🔴 这一条必须带物料合取：`external_wall` 在池 v2 上还会掷到上面这些物料。

    不带合取 ⇒ 幕牆／金屬閘／百葉／砌體全被判成 §5.3.1「批盪及瓦片」的對象，
    是纯造覆盖。
    """
    pack = _pack("FRG-1", "external_wall", "CMP-1", "external_wall", material)
    assert "external_wall_finish" not in _labels(pack, "FRG-1", shipped_aliases())


def test_native_type_is_never_inferred_from_the_normalized_key() -> None:
    """取不到原生 `component_type` ⇒ 只有粗标签，绝不从归一键或片段 ID 反推。

    归一键正是把 `balcony_slab` 吞成 `external_component` 的那一层；从它反推
    等于把本表的语义建在被吞掉的信息上。
    """
    pack = _pack("FRG-1", "external_component", "CMP-1", None, "reinforced_concrete")
    assert _labels(pack, "FRG-1", shipped_aliases()) == frozenset({"external_component"})


def test_empty_alias_table_is_bitwise_equivalent_to_pre_alignment() -> None:
    """空登记表 ⇒ 与 2026-08-07 之前逐位等价（缺席即退回，不静默半开）。"""
    pack = _pack("FRG-1", "external_component", "CMP-1", "parapet_wall", "reinforced_concrete")
    assert _labels(pack, "FRG-1", {}) == frozenset({"external_component"})


def test_supply_side_and_scope_match_share_one_ruler_after_alignment() -> None:
    """有護牆 ⇒ 不许再报「本栋无欄杆類片段」；没有 ⇒ 必须报。

    两处若用不同判据，会出现「匹配得上却仍记供给侧缺口」的自相矛盾 ——
    而供给侧计数正是轨二 `L1_no_world_asset` 的来源。
    """
    item = {"normative_item_id": "t", "source_clause_id": "5.3.6", "applicable": True,
            "scope_type": "component_class", "scope_id": "balustrade_railing",
            "expected_card_ids": ["rc.a"]}
    parapet = scorer._fragment_scope_labels(
        _pack("FRG-1", "external_component", "CMP-1", "parapet_wall", "reinforced_concrete"),
        {}, shipped_aliases())
    assert scorer._classify_item(item, [], {"rc.a"}, {"rc.a"}, parapet) \
        != "supply_side_no_fragment_of_class"

    balcony = scorer._fragment_scope_labels(
        _pack("FRG-1", "external_component", "CMP-1", "balcony_slab", "reinforced_concrete"),
        {}, shipped_aliases())
    assert scorer._classify_item(item, [], {"rc.a"}, {"rc.a"}, balcony) \
        == "supply_side_no_fragment_of_class"


# ── 落地表本体：删一条即红 ──────────────────────────────────────────────────

def test_shipped_table_covers_exactly_the_six_adjudicated_rows() -> None:
    """🔴 变异可证：从 `component_class_scope_native_alias_v1.json` 删掉任一条即红。

    对齐的授权是 `裁定_11条供给侧_20260807.md` §三.2 / §四.2 甲组终裁（6 条）：
      #1 #2 §3.4.2(B)(a)(b) @0010 ← 露台
      #6 #7 #8 §5.3.1 @0010/0017/0020 ← 外牆批盪瓦片
      #9 §5.3.6(b) @0010 ← 護牆
    """
    table = shipped_aliases()
    assert set(table) == {"cantilevered_canopy", "balustrade_railing", "external_wall_finish"}

    flat = {(scope_id, native): mats
            for scope_id, pairs in table.items() for native, mats in pairs}
    assert flat[("cantilevered_canopy", "balcony_slab")] is None, "露台不限物料（正文按形态列举）"
    assert flat[("cantilevered_canopy", "canopy")] is None
    assert flat[("balustrade_railing", "parapet_wall")] is None
    for native in ("external_wall", "wall_tile_finish"):
        assert flat[("external_wall_finish", native)] == FINISH_MATERIALS, \
            "外牆飾面必须带批盪瓦片物料合取，否则幕牆/金屬閘/砌體会被一并纳入"


def test_every_alias_entry_quotes_the_chinese_regulation_verbatim() -> None:
    """🔴 每条对齐必须带中文正文引文，且引文要在它声称的行号上逐字对得上。

    「页码须去法规原文实取，编一个就是造假来源」——本仓已立的纪律。
    这条测试让它机械可复核：引文写错行号、写错字，当场红。
    """
    doc = json.loads(
        (ROOT / scorer.SCOPE_NATIVE_ALIAS_PATH).read_text(encoding="utf-8"))
    lines = REGULATION.read_text(encoding="utf-8").splitlines()

    def page_of(lineno: int) -> int | None:
        page = None
        for line in lines[:lineno]:
            m = re.search(r"<!--\s*page:\s*(\d+)\s*-->", line)
            if m:
                page = int(m.group(1))
        return page

    assert doc["entries"], "登记表不许空"
    for entry in doc["entries"]:
        evidence = entry.get("zh_evidence") or []
        assert evidence, f"{entry['scope_id']} 缺 zh_evidence"
        for ev in evidence:
            lineno, quote = ev["line"], ev["quote"]
            assert quote in lines[lineno - 1], \
                f"{entry['scope_id']} / {ev['clause']}：第 {lineno} 行对不上引文"
            assert page_of(lineno) == ev["page"], \
                f"{entry['scope_id']} / {ev['clause']}：页码与正文的 page 标记不符"


# ── 加载器 fail-loud ────────────────────────────────────────────────────────

@pytest.mark.parametrize("entries, needle", [
    ([{"scope_id": "x", "pairs": [{"native_component_type": "a", "material_systems": []}]}],
     "material_systems"),
    ([{"scope_id": "x", "pairs": [{"native_component_type": "a"}]}], "material_systems"),
    ([{"scope_id": "x", "pairs": [{"native_component_type": "a", "material_systems": "ANY"}]}],
     "material_systems"),
    ([{"scope_id": "x", "pairs": [{"native_component_type": "", "material_systems": ["b"]}]}],
     "native_component_type"),
    ([{"scope_id": "x", "pairs": []}], "pairs"),
    ([{"pairs": [{"native_component_type": "a", "material_systems": ["b"]}]}], "scope_id"),
])
def test_loader_fails_loud_on_degenerate_entries(tmp_path: Path, entries, needle) -> None:
    """🔴 「不限物料」必须显式写 `"any"`。

    空列表 / 缺字段一律抛 —— 本仓已有「空集被当成放行」的静默退化先例，
    那条通道一旦开着，漏写物料就等于悄悄把合取降成析取。
    大小写也不放过（`"ANY"` 照抛）：判据不认「看起来像」。
    """
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema_version": "component_class_scope_native_alias_v1",
                             "entries": entries}), encoding="utf-8")
    with pytest.raises(ValueError, match=needle):
        scorer._load_scope_native_aliases(p)


def test_loader_rejects_duplicate_scope_id(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    entry = {"scope_id": "x",
             "pairs": [{"native_component_type": "a", "material_systems": "any"}]}
    p.write_text(json.dumps({"schema_version": "component_class_scope_native_alias_v1",
                             "entries": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        scorer._load_scope_native_aliases(p)


def test_loader_rejects_wrong_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema_version": "nope", "entries": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        scorer._load_scope_native_aliases(p)


def test_missing_table_falls_back_instead_of_crashing(tmp_path: Path) -> None:
    assert scorer._load_scope_native_aliases(tmp_path / "nope.json") == {}
