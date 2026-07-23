"""canonical_profile 单测（spec 草案 v4 Block C，§C.0-C.9）。

覆盖：Decimal ingress / NFC / canonical_json 确定性 / 七维 registry 别名 + C.9
unknown/empty/conflict/cycle 规则 / qualifier 八键映射 / in_not_in 排序。
"""

import unicodedata
from decimal import Decimal

import pytest

from canonical_profile import (
    CANONICAL_PROFILE_ID,
    CanonicalProfileError,
    CanonicalRegistry,
    QUALIFIER_NAMESPACE,
    canonical_decimal_str,
    canonical_json,
    canonicalize_artifact,
    canonicalize_deadline,
    canonicalize_formula,
    canonicalize_measure,
    canonicalize_qualifier,
    canonicalize_slot,
    canonicalize_unit,
    in_not_in_sort,
    is_empty_source_value,
    nfc,
    parse_json_decimal,
    qualifier_fingerprint,
    sha256_hex_24,
)


# ------------------------------- C.8 Decimal ------------------------------- #


@pytest.mark.parametrize(
    "token,expected",
    [
        ("7", "7"),
        ("7.0", "7"),
        ("7e0", "7"),
        ("700e-2", "7"),
        ("7.50", "7.5"),
        ("-0", "0"),
        ("0.00", "0"),
        ("0", "0"),
        ("-3.14", "-3.14"),
        ("100", "100"),
        ("1E+2", "100"),
        (7, "7"),
        (Decimal("7.00"), "7"),
    ],
)
def test_canonical_decimal_str(token, expected):
    assert canonical_decimal_str(token) == expected


def test_canonical_decimal_int_float_equivalence():
    # 7 与 7.0 归一后 bytes 一致（整数/浮点等价）
    assert canonical_decimal_str("7") == canonical_decimal_str("7.0")
    assert canonical_decimal_str(7) == canonical_decimal_str(Decimal("7.0"))


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_canonical_decimal_rejects_non_finite(bad):
    with pytest.raises(CanonicalProfileError):
        canonical_decimal_str(bad)


def test_canonical_decimal_rejects_bool():
    with pytest.raises(CanonicalProfileError):
        canonical_decimal_str(True)


def test_parse_json_decimal_uses_decimal_and_rejects_nan():
    parsed = parse_json_decimal('{"v": 7.50, "n": 3}')
    assert parsed["v"] == Decimal("7.50")
    assert isinstance(parsed["v"], Decimal)
    assert parsed["n"] == 3 and isinstance(parsed["n"], int)
    with pytest.raises(CanonicalProfileError):
        parse_json_decimal('{"v": NaN}')


# ------------------------------- C.8 NFC ----------------------------------- #


def test_nfc_normalizes():
    # 组合字符 é (e + U+0301) → 预组合 é (U+00E9)
    decomposed = "é"
    assert nfc(decomposed) == "é"
    assert unicodedata.normalize("NFC", decomposed) == nfc(decomposed)


def test_canonical_json_nfc_applied_to_strings_and_keys():
    a = canonical_json({"é": "é"})
    b = canonical_json({"é": "é"})
    assert a == b


# --------------------------- C.8 canonical_json ---------------------------- #


def test_canonical_json_key_sorted_no_whitespace():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_number_normalization():
    assert canonical_json({"x": Decimal("7.0"), "y": 7}) == canonical_json(
        {"y": Decimal("7"), "x": 7}
    )


def test_canonical_json_list_order_preserved():
    assert canonical_json([3, 1, 2]) == "[3,1,2]"


def test_canonical_json_types():
    assert canonical_json(None) == "null"
    assert canonical_json(True) == "true"
    assert canonical_json(False) == "false"
    assert canonical_json("x") == '"x"'


def test_canonical_json_rejects_unserializable():
    with pytest.raises(CanonicalProfileError):
        canonical_json({"x": object()})


def test_sha256_hex_24_len():
    h = sha256_hex_24("abc")
    assert len(h) == 24 and all(c in "0123456789abcdef" for c in h)


# ---------------------- C.1-C.5/C.7 registry 别名 -------------------------- #


def test_measure_alias_resolves():
    assert canonicalize_measure("crackwidth").canonical_key == "measure.crack_width"
    assert canonicalize_measure("crackwidth").resolution == "resolved"
    # 本身即 canonical
    assert canonicalize_measure("measure.crack_width").resolution == "resolved"


def test_measure_unknown_passthrough():
    r = canonicalize_measure("never_seen_measure")
    assert r.resolution == "unresolved"
    assert r.diagnostic == "unknown_measure_key"
    assert r.canonical_key == "never_seen_measure"  # passthrough 原值


def test_slot_alias_and_unknown():
    # 合成 alias demo（真卡 slot_id `repair.prescribed.started` 是 canonical 本体，故种子
    # alias key 改为明确 synthetic 的 legacy_alias.* 以免撞真键，见 profile.py 注）。
    assert (
        canonicalize_slot("legacy_alias.repair_prescribed_started").canonical_key
        == "procedure.repair.prescribed.started"
    )
    # 真卡枚举键灌 identity 后本体 resolve（尊重真卡权威）。
    assert canonicalize_slot("repair.prescribed.started").canonical_key == "repair.prescribed.started"
    assert canonicalize_slot("repair.prescribed.started").resolution == "resolved"
    assert canonicalize_slot("weird.slot").resolution == "unresolved"


def test_unit_case_insensitive():
    assert canonicalize_unit("MM").canonical_key == "mm"
    assert canonicalize_unit("mm").canonical_key == "mm"
    assert canonicalize_unit("Millimetre").canonical_key == "mm"


def test_unit_unknown_passthrough():
    r = canonicalize_unit("furlong")
    assert r.resolution == "unresolved" and r.diagnostic == "unknown_unit"


def test_artifact_unknown_hard_fail():
    assert (
        canonicalize_artifact("inspection_report").canonical_key
        == "artifact.inspection_report"
    )
    with pytest.raises(CanonicalProfileError):
        canonicalize_artifact("unknown_artifact")


def test_formula_unknown_hard_fail():
    assert canonicalize_formula("pull_test_additional_after_failure").resolution == "resolved"
    with pytest.raises(CanonicalProfileError):
        canonicalize_formula("bogus_formula")


def test_deadline_alias_and_unknown():
    assert canonicalize_deadline("completion").canonical_key == "time_anchor.completion"
    assert canonicalize_deadline("mystery").resolution == "unresolved"


# ---------------------- C.9 empty / cycle / conflict ----------------------- #


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_is_empty_source_value(empty):
    assert is_empty_source_value(empty) is True


def test_is_empty_source_value_nonempty():
    assert is_empty_source_value("x") is False
    assert is_empty_source_value(0) is False


def test_registry_cycle_hard_fail():
    with pytest.raises(CanonicalProfileError) as exc:
        CanonicalRegistry(
            "t", [("a", "b"), ("b", "a")], unknown_policy="passthrough", unknown_code="u"
        )
    assert "cycle" in str(exc.value)


def test_registry_conflict_hard_fail():
    with pytest.raises(CanonicalProfileError) as exc:
        CanonicalRegistry(
            "t", [("a", "b"), ("a", "c")], unknown_policy="passthrough", unknown_code="u"
        )
    assert "conflict" in str(exc.value)


def test_registry_non_idempotent_chain_hard_fail():
    # a->b, b->c 破坏 canon(canon(a))==canon(a)
    with pytest.raises(CanonicalProfileError) as exc:
        CanonicalRegistry(
            "t", [("a", "b"), ("b", "c")], unknown_policy="passthrough", unknown_code="u"
        )
    assert "idempotent" in str(exc.value)


def test_registry_self_map_is_not_cycle():
    reg = CanonicalRegistry(
        "t", [("x", "canon.x"), ("canon.x", "canon.x")],
        unknown_policy="passthrough", unknown_code="u",
    )
    assert reg.canonicalize("x").canonical_key == "canon.x"
    assert reg.canonicalize("canon.x").resolution == "resolved"


def test_registry_closure_idempotent():
    # canon(canon(x)) == canon(x)
    r1 = canonicalize_measure("crackwidth").canonical_key
    r2 = canonicalize_measure(r1).canonical_key
    assert r1 == r2


# ------------------------------- C.6 qualifier ----------------------------- #


def test_qualifier_eight_keys_present():
    assert len(QUALIFIER_NAMESPACE) == 8
    assert QUALIFIER_NAMESPACE["method_key"] == "qualifier.method"


def test_qualifier_canonicalize():
    assert canonicalize_qualifier("actor_role_key", "engineer") == (
        "qualifier.actor_role",
        "engineer",
    )


def test_qualifier_unknown_key_hard_fail():
    with pytest.raises(CanonicalProfileError):
        canonicalize_qualifier("bogus_key", "v")


def test_qualifier_fingerprint_sorted_deduped():
    fp = qualifier_fingerprint(
        [("method_key", "b"), ("artifact_key", "a"), ("method_key", "b")]
    )
    assert fp == (("qualifier.artifact", "a"), ("qualifier.method", "b"))


def test_qualifier_same_key_multi_value_multi_entry():
    fp = qualifier_fingerprint([("method_key", "b"), ("method_key", "a")])
    assert fp == (("qualifier.method", "a"), ("qualifier.method", "b"))


# ------------------------------- C.8 in/not_in ----------------------------- #


def test_in_not_in_sort_type_then_value():
    out = in_not_in_sort(
        [("string", "b"), ("decimal", "7"), ("string", "a"), ("decimal", "7"), ("none", "")]
    )
    assert out == (("none", ""), ("decimal", "7"), ("string", "a"), ("string", "b"))


def test_in_not_in_bad_tag():
    with pytest.raises(CanonicalProfileError):
        in_not_in_sort([("weird", "x")])


def test_profile_id_constant():
    assert CANONICAL_PROFILE_ID == "mbis_canonical_v2"
