"""DEBT-040 修复单测：别名表列表值归一（validator._normalize_alias_map）。

背景：projection_runtime_mapping_v1 的别名值是单元素列表，旧实现 `str(v)`
把列表搅成 "['procedure...']" 垃圾键，canonical 查找必 miss → 触发器 open。

DEBT-049 Phase3 U2（U6 补遗）追加：method 维度建表器 `build_method_canonical_map`
的专门单测。**method 维度 canonical 落 key 侧**（与 slot/measure 相反），故**不能**
复用 `_normalize_alias_map`——本文件同址锁死两者的方向差与丢别名反面对照。
"""

from evo_agent_baseline.closure.fact_binding import build_method_canonical_map
from evo_agent_baseline.closure.validator import _normalize_alias_map


def test_list_values_take_first():
    out = _normalize_alias_map(
        {"repair.prescribed.started": ["procedure.repair.prescribed.started"]}
    )
    assert out == {"repair.prescribed.started": "procedure.repair.prescribed.started"}


def test_str_values_passthrough():
    out = _normalize_alias_map({"a.b": "c.a.b"})
    assert out == {"a.b": "c.a.b"}


def test_multi_element_list_takes_first_nonempty():
    out = _normalize_alias_map({"k": ["", "x.y", "z.w"]})
    assert out == {"k": "x.y"}


def test_garbage_values_dropped():
    out = _normalize_alias_map({"k1": [], "k2": None, "k3": 42, "k4": ["ok.v"]})
    assert out == {"k4": "ok.v"}


def test_non_dict_returns_empty():
    assert _normalize_alias_map(["not", "a", "dict"]) == {}
    assert _normalize_alias_map(None) == {}


# ===========================================================================
# DEBT-049 Phase3 U2｜method 维度建表器（U6 补遗，此前全仓零测试引用）
# ===========================================================================
# 冻结表（projection_runtime_mapping_v1.json 的 method_aliases 段）实样。
FROZEN_METHOD_ALIASES = {
    "_note": "DEBT-049 Phase3 U2 说明性注释键，不得进展开表",
    "air_test": [],
    "ball_test": [],
    "water_test": [],
    "smoke_test": [],
    "cctv_survey": ["drainage_cctv", "CCTV"],
}


def test_method_map_full_expansion_keeps_every_alias():
    """反转 + 全展开：canonical 自映射 + 每个别名各一条，**一个都不许丢**。"""
    out = build_method_canonical_map({"cctv_survey": ["drainage_cctv", "CCTV"]})
    assert out == {
        "cctv_survey": "cctv_survey",      # identity 自映射
        "drainage_cctv": "cctv_survey",    # CCTV 三拼法桥别名①
        "CCTV": "cctv_survey",             # CCTV 三拼法桥别名②
    }


def test_method_map_must_not_reuse_normalize_alias_map():
    """方向差反面对照（§2.2 冻结理由）：`_normalize_alias_map` 同输入会把 canonical
    映到某别名并丢掉其余别名——故 method 维度必须走专用建表器。"""
    grouped = {"cctv_survey": ["drainage_cctv", "CCTV"]}
    wrong = _normalize_alias_map(grouped)
    right = build_method_canonical_map(grouped)
    assert wrong == {"cctv_survey": "drainage_cctv"}   # 方向反 + 丢 CCTV
    assert right["drainage_cctv"] == "cctv_survey"     # 专用建表器方向正确
    assert right["CCTV"] == "cctv_survey"              # 且不丢别名
    assert wrong != right


def test_method_map_skips_underscore_note_key():
    """`_` 前缀键（`_note` 等注释）不进展开表。"""
    out = build_method_canonical_map(FROZEN_METHOD_ALIASES)
    assert "_note" not in out
    assert not any(k.startswith("_") for k in out)


def test_method_map_frozen_table_shape():
    """冻结表全展开形状：四暗部署方法纯 identity + CCTV 三条。"""
    out = build_method_canonical_map(FROZEN_METHOD_ALIASES)
    assert out == {
        "air_test": "air_test",
        "ball_test": "ball_test",
        "water_test": "water_test",
        "smoke_test": "smoke_test",
        "cctv_survey": "cctv_survey",
        "drainage_cctv": "cctv_survey",
        "CCTV": "cctv_survey",
    }


def test_method_map_empty_alias_list_is_pure_identity():
    """空别名列表（暗部署档）→ 只出 identity 自映射，不炸。"""
    assert build_method_canonical_map({"air_test": []}) == {"air_test": "air_test"}


def test_method_map_null_and_non_dict_degrade_to_empty():
    """None / 非 dict → 空表（下游 `.get(x, x)` 退化成 identity 归一，保守不阻断）。"""
    assert build_method_canonical_map(None) == {}
    assert build_method_canonical_map("not-a-dict") == {}
    assert build_method_canonical_map(["a", "b"]) == {}
    assert build_method_canonical_map(42) == {}


def test_method_map_drops_malformed_entries():
    """非 str canonical / 非 str 别名条目丢弃，不污染展开表。"""
    out = build_method_canonical_map(
        {"ok": ["good", 42, None, ""], 7: ["x"], "": ["y"]}
    )
    assert out == {"ok": "ok", "good": "ok"}
