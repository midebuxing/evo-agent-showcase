"""授权资产行解析的缺省拒绝面（终审门 4，2026-08-02）。

面：①合法行全收 ②卡指纹失配逐行失效（不拒启）③模式违例整体拒启
④**重复键整体拒启**（修复前后行静默覆盖——文件顺序决定生效行）⑤拒启说明
可读。变异面：把重复键分支改回覆盖 → 测试 4 必须红。
"""
from __future__ import annotations

from evo_agent_baseline.closure.applicability_v3 import parse_trigger_na_rows


def _row(**over):
    r = {
        "rule_card_id": "RC.x", "condition_id": "trg01", "slot_ref_id": "sr01",
        "required_component_type_key": "structural_component",
        "physical_leaf_identity": "drainage_component",
        "raw_component_type": "drainage_stack",
        "card_content_sha256": "SHA-A",
        "qualifiers_shape_sha256": "Q1", "source_combo_no": 7,
    }
    r.update(over)
    return r


SHAS = {"RC.x": "SHA-A", "RC.y": "SHA-B"}


def test_valid_rows_all_loaded():
    auth, stale, refused = parse_trigger_na_rows(
        {"rows": [_row(), _row(rule_card_id="RC.y", card_content_sha256="SHA-B")]},
        SHAS)
    assert len(auth) == 2 and stale == 0 and refused is None


def test_stale_card_sha_row_level_invalidation():
    auth, stale, refused = parse_trigger_na_rows(
        {"rows": [_row(), _row(rule_card_id="RC.y", card_content_sha256="旧SHA")]},
        SHAS)
    assert len(auth) == 1 and stale == 1 and refused is None


def test_schema_violation_refuses_whole_feature():
    auth, stale, refused = parse_trigger_na_rows(
        {"rows": [_row(), _row(raw_component_type="")]}, SHAS)
    assert auth == {} and refused and "模式违例 1" in refused


def test_duplicate_key_refuses_whole_feature():
    """重复六字段键 → 整体拒启（不许后行静默覆盖前行）。"""
    a = _row(qualifiers_shape_sha256="Q1", source_combo_no=7)
    b = _row(qualifiers_shape_sha256="Q2", source_combo_no=8)   # 同键不同值
    auth, stale, refused = parse_trigger_na_rows({"rows": [a, b]}, SHAS)
    assert auth == {} and refused and "重复键 1" in refused


def test_source_combo_zero_is_not_schema_violation():
    auth, _, refused = parse_trigger_na_rows(
        {"rows": [_row(source_combo_no=0)]}, SHAS)
    assert refused is None and len(auth) == 1


def test_duplicate_with_stale_twin_still_refuses():
    """复审件 1′ 靶点：一行有效＋同键一行卡指纹失配 → 仍整体拒启。

    首版先剔失配行再查重复 ⇒ 该形状漏网（文件顺序决定生效行）。
    重复键检查必须在时效过滤之前。"""
    a = _row()                                        # 有效
    b = _row(card_content_sha256="旧SHA")              # 同键、指纹失配
    auth, stale, refused = parse_trigger_na_rows({"rows": [a, b]}, SHAS)
    assert auth == {} and refused and "重复键 1" in refused


def test_non_object_row_refuses_not_raises():
    auth, _, refused = parse_trigger_na_rows(
        {"rows": [_row(), "不是对象"]}, SHAS)
    assert auth == {} and refused and "结构异常" in refused


def test_bad_top_structure_refuses_not_raises():
    auth, _, refused = parse_trigger_na_rows({"rows": {"不是": "列表"}}, SHAS)
    assert auth == {} and refused and "结构异常" in refused
