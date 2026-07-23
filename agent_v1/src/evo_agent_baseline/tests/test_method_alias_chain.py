"""DEBT-049 Phase3 U3｜method 别名归一 → `verification.test.performed` 派生链单测。

U6 补遗（此前该链零专门覆盖：`derive_verification_performed_facts` 的 `method_aliases`
入参从未被任何测试传入过，CCTV 三拼法桥的「两件齐备」语义无任何用例）。

链路：W0 测量事实 `qualifiers.method_class`（原始词，如 `drainage_cctv`）
  → **canonicalize-first**（`build_method_canonical_map` 展开表归一成 `cctv_survey`）
  → 判 `_TEST_METHOD_CLASSES` 白名单（存 canonical 形）
  → 派生 `verification.test.performed{method_key=<canonical>}` 供卡端证据槽消费。

**门语义（§7 激活边界）**：CCTV 桥须 **alias 归一** 与 **白名单成员** 两件**同时**齐备
才派生——任一单独具备都不点亮。本文件把这两个半件的负向用例锁死。
"""

from __future__ import annotations

import json

from evo_agent_baseline.closure.fact_binding import (
    FactIndex,
    build_method_canonical_map,
)
from evo_agent_baseline.contracts import FactAtom
from evo_agent_baseline.retrieval.fact_retriever import (
    _TEST_METHOD_CLASSES,
    derive_verification_performed_facts,
)

# 冻结的 CCTV 三拼法桥展开表（mapping `method_aliases` 段实样）。
BRIDGE_MAP = build_method_canonical_map({"cctv_survey": ["drainage_cctv", "CCTV"]})


def _measurement(fid, method_class, frag="FR1", ctype="drainage_component",
                 slot="index.drainage.blockage"):
    """W0 排水测量事实（`method_class` 由 pack_builder 并入 qualifiers）。"""
    q = {"component_type_key": ctype, "fragment_id": frag}
    if method_class is not None:
        q["method_class"] = method_class
    return FactAtom(
        fact_id=fid, world_id="W1", building_id="B1",
        carrier_type="measurement", carrier_id=fid, target_ref=frag,
        slot_id=slot, measure_key=slot,
        value_json=json.dumps(0.42), value_type="number", unit="ratio",
        qualifiers=q, confidence_index=None,
        source_path="measurements.parquet", source_node_id=fid,
    )


# ===========================================================================
# 门①：CCTV 三拼法桥「两件齐备才激活」
# ===========================================================================
def test_cctv_bridge_both_pieces_present_derives_canonical_performed() -> None:
    """两件齐备（别名归一 + canonical 落白名单）→ 派生 method_key=cctv_survey。"""
    assert "cctv_survey" in _TEST_METHOD_CLASSES          # 件②白名单成员
    assert BRIDGE_MAP["drainage_cctv"] == "cctv_survey"   # 件①别名归一

    out = derive_verification_performed_facts(
        [_measurement("m1", "drainage_cctv")], BRIDGE_MAP)

    assert len(out) == 1
    o = out[0]
    assert o.slot_id == "verification.test.performed"
    # **规范名**入派生键（非原始 W0 词）——保白名单/派生/卡端求交同一词域。
    assert o.qualifiers["method_key"] == "cctv_survey"
    assert o.qualifiers["component_type_key"] == "drainage_component"
    assert o.qualifiers["fragment_id"] == "FR1"
    assert o.value_json == "true"


def test_cctv_bridge_missing_alias_piece_does_not_derive() -> None:
    """只有白名单成员、**缺别名归一**（空展开表）→ 原始 `drainage_cctv` 不在白名单 → 不派生。

    这是暗部署期的实际形态：`_TEST_METHOD_CLASSES` 已含 `cctv_survey`，但 mapping
    未上 `method_aliases` 段 → 展开表空 → identity 归一 → 桥不点亮。
    """
    assert "cctv_survey" in _TEST_METHOD_CLASSES
    assert "drainage_cctv" not in _TEST_METHOD_CLASSES  # 原始词不入白名单

    out = derive_verification_performed_facts(
        [_measurement("m1", "drainage_cctv")], {})
    assert out == []


def test_cctv_bridge_missing_whitelist_piece_does_not_derive() -> None:
    """只有别名归一、**缺白名单成员** → 归一到的 canonical 不在白名单 → 不派生。

    用一个确知不在白名单的 canonical 词模拟「白名单成员未合入」那一半。
    """
    fake = "cctv_survey_not_yet_whitelisted"
    assert fake not in _TEST_METHOD_CLASSES
    amap = build_method_canonical_map({fake: ["drainage_cctv"]})
    assert amap["drainage_cctv"] == fake  # 别名归一这件是齐的

    out = derive_verification_performed_facts(
        [_measurement("m1", "drainage_cctv")], amap)
    assert out == []


def test_uppercase_cctv_alias_also_bridges() -> None:
    """三拼法的第二个别名 `CCTV` 同样归一到 canonical。"""
    out = derive_verification_performed_facts(
        [_measurement("m1", "CCTV")], BRIDGE_MAP)
    assert len(out) == 1
    assert out[0].qualifiers["method_key"] == "cctv_survey"


# ===========================================================================
# 门②：暗部署四方法（现网零命中，identity 归一即可派生）
# ===========================================================================
def test_dark_deployed_four_methods_derive_under_identity_map() -> None:
    """air/ball/water/smoke 四方法白名单成员 + 纯 identity 展开表 → 各自派生。"""
    amap = build_method_canonical_map(
        {"air_test": [], "ball_test": [], "water_test": [], "smoke_test": []})
    facts = [
        _measurement("m1", "air_test", frag="FR1"),
        _measurement("m2", "ball_test", frag="FR2"),
        _measurement("m3", "water_test", frag="FR3"),
        _measurement("m4", "smoke_test", frag="FR4"),
    ]
    out = derive_verification_performed_facts(facts, amap)
    assert {o.qualifiers["method_key"] for o in out} == {
        "air_test", "ball_test", "water_test", "smoke_test"}


def test_non_test_method_class_not_derived() -> None:
    """非物理测试方法（视觉/公式）不派生（既有语义护栏）。"""
    out = derive_verification_performed_facts(
        [_measurement("m1", "visual_inspection"),
         _measurement("m2", "formula")], BRIDGE_MAP)
    assert out == []


# ===========================================================================
# 门③：去重 —— 每 (fragment, method_key) 一条
# ===========================================================================
def test_dedupe_per_fragment_and_method_key() -> None:
    """同 fragment 同方法多条测量 → 只派生一条（`seen` 去重路径）。"""
    facts = [
        _measurement("m1", "drainage_cctv", frag="FR1"),
        _measurement("m2", "drainage_cctv", frag="FR1"),  # 同 fragment 同法
        _measurement("m3", "drainage_cctv", frag="FR1"),
    ]
    out = derive_verification_performed_facts(facts, BRIDGE_MAP)
    assert len(out) == 1


def test_dedupe_key_is_canonical_not_raw_alias() -> None:
    """去重键用**归一后**的 canonical：同 fragment 上 `drainage_cctv` 与 `CCTV`
    两个不同原始词归一到同一 canonical → 仍只出一条（否则会重复派生）。"""
    facts = [
        _measurement("m1", "drainage_cctv", frag="FR1"),
        _measurement("m2", "CCTV", frag="FR1"),
    ]
    out = derive_verification_performed_facts(facts, BRIDGE_MAP)
    assert len(out) == 1
    assert out[0].qualifiers["method_key"] == "cctv_survey"


def test_distinct_fragments_derive_separately() -> None:
    """不同 fragment 同方法 → 各出一条（fragment 粒度不塌）。"""
    facts = [
        _measurement("m1", "drainage_cctv", frag="FR1"),
        _measurement("m2", "drainage_cctv", frag="FR2"),
    ]
    out = derive_verification_performed_facts(facts, BRIDGE_MAP)
    assert len(out) == 2
    assert {o.qualifiers["fragment_id"] for o in out} == {"FR1", "FR2"}


# ===========================================================================
# 门④：非 str method_class（含 None）不参与，保 `.get` 语义不炸
# ===========================================================================
def test_non_str_method_class_ignored_without_crash() -> None:
    """`method_class` 缺失 / 非 str → 跳过，不抛异常（canonicalize 前的类型守卫）。"""
    no_mc = _measurement("m1", None)                       # 无 method_class 键
    numeric = _measurement("m2", "x").model_copy(
        update={"qualifiers": {"method_class": 42, "fragment_id": "FR1"}})
    listy = _measurement("m3", "x").model_copy(
        update={"qualifiers": {"method_class": ["cctv_survey"], "fragment_id": "FR1"}})
    nulled = _measurement("m4", "x").model_copy(
        update={"qualifiers": {"method_class": None, "fragment_id": "FR1"}})

    out = derive_verification_performed_facts(
        [no_mc, numeric, listy, nulled], BRIDGE_MAP)
    assert out == []


def test_empty_qualifiers_fact_survives_derivation() -> None:
    """qualifiers 全空的事实不炸派生器。"""
    bare = _measurement("m1", "x").model_copy(update={"qualifiers": {}})
    assert derive_verification_performed_facts([bare], BRIDGE_MAP) == []


# ===========================================================================
# 门⑤：卡端 slot-role 证据槽按**规范名**命中派生事实
# ===========================================================================
def test_derived_performed_matches_card_evidence_slot_qualifiers() -> None:
    """卡端证据槽 `verification.test.performed{method_key=cctv_survey,
    component_type_key=drainage_component}`（两张真卡的 sr03 实样限定符）须被
    W0 原始词 `drainage_cctv` 派生出的事实**按规范名**命中（子集匹配语义）。
    """
    # 真卡 sr03 限定符（s4_4_2_a_cctv_survey / s5_6_5_e_cctv_survey_with_recording）。
    card_slot_id = "verification.test.performed"
    card_quals = {"method_key": "cctv_survey",
                  "component_type_key": "drainage_component"}

    out = derive_verification_performed_facts(
        [_measurement("m1", "drainage_cctv")], BRIDGE_MAP)
    assert len(out) == 1
    derived = out[0]

    assert derived.slot_id == card_slot_id
    # 卡端每个限定符都在派生事实上同名同值（子集匹配 → 命中）。
    for k, v in card_quals.items():
        assert derived.qualifiers.get(k) == v, f"卡端限定符 {k}={v} 未被派生事实命中"


def test_raw_alias_would_miss_card_slot_without_canonicalization() -> None:
    """反面：若不归一（空展开表），`drainage_cctv` 连派生都不发生 → 卡端证据槽必 miss。
    这是「桥没接上时卡为何 open」的根因锁。"""
    out = derive_verification_performed_facts(
        [_measurement("m1", "drainage_cctv")], {})
    assert out == []  # 无派生 → 卡端 sr03 无候选 → 义务 open/missing


# ===========================================================================
# 门⑥：FactIndex.method_index 建键同样走归一（闭包侧求交对齐）
# ===========================================================================
def test_fact_index_method_index_keyed_by_canonical() -> None:
    """`FactIndex` 用 `canonical_method` 建 `method_index` 键 → 卡端
    `method_keys_allowed=[cctv_survey]` 与 W0 原始词 `drainage_cctv` 自动求交对齐。"""
    from evo_agent_baseline.closure.tests.fixtures import make_fact_pack

    pack = make_fact_pack([_measurement("m1", "drainage_cctv")])
    idx = FactIndex(pack, method_aliases=BRIDGE_MAP)

    assert "cctv_survey" in idx.method_index      # 归一后的规范键
    assert "drainage_cctv" not in idx.method_index  # 原始词不留残键
    assert idx.canonical_method("drainage_cctv") == "cctv_survey"


def test_fact_index_identity_when_no_alias_map() -> None:
    """无别名表 → identity 建键（暗部署期现网零漂移的实现锁）。"""
    from evo_agent_baseline.closure.tests.fixtures import make_fact_pack

    pack = make_fact_pack([_measurement("m1", "drainage_cctv")])
    idx = FactIndex(pack)
    assert "drainage_cctv" in idx.method_index
    assert idx.canonical_method("drainage_cctv") == "drainage_cctv"
