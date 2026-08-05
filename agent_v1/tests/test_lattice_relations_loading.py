"""`build_component_type_lattice.load_relations` 的受控词表与 fail-closed（DEBT-081 清账前置）。

修复对象：旧实现只认 is_a/disjoint、**其它 relation 取值静默丢弃**——关系表清账要
引入 `undecidable_vocab_too_coarse`（人裁「降级为不可判」），静默丢弃会让该改动
无声变成「什么都没发生」（与「派生视图数不出它自己过滤掉的东西」同族）。

三面：①未知取值抛错（fail-closed）②已知非互斥值（crosses_axis /
undecidable_vocab_too_coarse）被接受且不产互斥 ③is_a/disjoint 行为与修复前逐位同。
"""
import importlib.util
import json
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "build_component_type_lattice.py")
_spec = importlib.util.spec_from_file_location("bctl_under_test", _SCRIPT)
bctl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bctl)


def _write_relations(tmp_path, relations):
    doc = {"version": "test.v1", "relations": relations}
    (tmp_path / bctl.RELATIONS_FILE).write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_unknown_relation_kind_fails_closed(tmp_path):
    reg = _write_relations(tmp_path, [
        {"relation": "layered_overlap", "type_a": "a", "type_b": "b"},
    ])
    with pytest.raises(ValueError, match="未登记的 relation"):
        bctl.load_relations(reg)


def test_known_non_disjoint_kinds_accepted_and_produce_no_pairs(tmp_path):
    reg = _write_relations(tmp_path, [
        {"relation": "crosses_axis", "type_a": "ubw", "type_b": "external_wall"},
        {"relation": "undecidable_vocab_too_coarse",
         "type_a": "structural_component", "type_b": "wall_tiles"},
    ])
    sub, disj, ver, sha = bctl.load_relations(reg)
    assert disj == []          # 不产互斥
    assert sub == {}
    assert ver == "test.v1"
    assert isinstance(sha, str) and len(sha) == 64   # 内容指纹随载入返回


def test_is_a_and_disjoint_semantics_unchanged(tmp_path):
    reg = _write_relations(tmp_path, [
        {"relation": "is_a", "parent": "external_component", "child": "wall_tiles"},
        {"relation": "is_a", "parent": "external_component", "child": "external_wall"},
        {"relation": "disjoint", "type_a": "b_type", "type_b": "a_type"},
    ])
    sub, disj, _, _ = bctl.load_relations(reg)
    assert sub == {"external_component": ["external_wall", "wall_tiles"]}
    assert disj == [("a_type", "b_type")]      # 排序对


def test_content_sha_tracks_content_not_version(tmp_path):
    """指纹钉内容：版本号不动、只改一条关系值 → sha 必变（清账查出的缺陷形状）。"""
    base = [{"relation": "disjoint", "type_a": "a", "type_b": "b"}]
    _, _, _, sha1 = bctl.load_relations(_write_relations(tmp_path, base))
    mutated = [{"relation": "crosses_axis", "type_a": "a", "type_b": "b"}]
    _, _, _, sha2 = bctl.load_relations(_write_relations(tmp_path, mutated))
    assert sha1 != sha2


def test_missing_file_fallback_unchanged(tmp_path):
    sub, disj, ver, sha = bctl.load_relations(tmp_path)   # 目录里没有关系表
    assert ver == "relations_file_missing"
    assert disj is None
    assert sha is None
    assert sub == bctl.SUBSUMPTION_FALLBACK
