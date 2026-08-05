"""权威卡包 `bundle_id` 读径的 fail-closed（护栏缺口 3，2026-07-27）。

缺口：`assemble_rule_slice` 的 P1-2 同源校验第三条腿读磁盘权威卡包，
`json.loads()` 之后直接 `.get("bundle_id")`。两种**合法 JSON** 形状会让
整个规则检索**强失败**而不是保守关闭：
  ① 顶层是 JSON 数组 → `.get()` 抛 `AttributeError`（不在捕获列表里）；
  ② `bundle_id` 字段是数组 → 进 `set()` 抛 `TypeError`（不可哈希）。

文件缺失 / 读失败 / 非法 JSON / 导入失败四个分支本来就保守关闭，不动。

测试构造：真 `assemble_rule_slice` + 注入边界的桩 client（`read` 全空，
让控制流走到第三条腿）+ 临时磁盘文件替换 `DEFAULT_AUTHORITATIVE_BUNDLE_PATH`
（运行时经模块属性惰性取值，monkeypatch 生效）。不伪造被测对象本身。
"""
from __future__ import annotations

import json

import pytest

# 🔴 2026-07-27 终审 P2 连带：权威路径常量已移至中立层 `rulecard_assets`
# （原在 `closure.identity_blueprint_catalog`，检索侧 import 它构成
#  `retrieval → closure` 反向依赖，违反规格 v0.4:4739）。
# ⚠️ patch 必须打在**读取方实际取值的那个模块**上，否则 patch 打空、测试假绿。
import evo_agent_baseline.rulecard_assets as ibc
from evo_agent_baseline.retrieval.rule_retriever import (
    RuleRetrievalResult,
    assemble_rule_slice,
)


class _StubClient:
    """注入边界桩：所有 KG 读返回空，控制流直达第三条腿。"""

    def read(self, *args, **kwargs):
        return []


def _assemble(tmp_path, monkeypatch, payload) -> object:
    pack_file = tmp_path / "rule_cards.json"
    pack_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ibc, "DEFAULT_AUTHORITATIVE_BUNDLE_PATH", pack_file)
    return assemble_rule_slice(
        run_id="t-gap3",
        rulecard_bundle_id="rulecard_v2.test",
        result=RuleRetrievalResult(),
        client=_StubClient(),
    )


def test_pack_file_is_json_array_closes_conservatively(tmp_path, monkeypatch):
    """🔴 形状①：顶层是合法 JSON 数组 → 不得强失败，保守关早退 + 留诊断。"""
    slice_ = _assemble(tmp_path, monkeypatch, ["not", "an", "object"])
    policy = slice_.retrieval_policy
    assert "rulecard_pack_bundle_id_error" in policy, (
        "顶层数组应留可区分诊断（AttributeError），而不是无记录放行")
    assert "component_structure_bundle_mismatch" in policy, (
        "读不到 bundle_id ⇒ 同源校验失败 ⇒ 必须保守关闭组件结构早退")
    assert "component_type_lattice" not in policy


def test_pack_bundle_id_array_closes_conservatively(tmp_path, monkeypatch):
    """🔴 形状②：`bundle_id` 是数组 → 不得强失败，保守关早退 + 留诊断。"""
    slice_ = _assemble(tmp_path, monkeypatch, {"bundle_id": ["a", "b"]})
    policy = slice_.retrieval_policy
    assert "rulecard_pack_bundle_id_error" in policy, (
        "bundle_id 非字符串应留可区分诊断（TypeError），而不是放到 set() 里炸")
    assert "component_structure_bundle_mismatch" in policy
    assert "component_type_lattice" not in policy


def test_valid_pack_file_leaves_no_error_diagnostic(tmp_path, monkeypatch):
    """正对照：合法卡包文件不报读径错误（lattice/auth 缺席仍按既有路径关早退）。"""
    slice_ = _assemble(tmp_path, monkeypatch, {"bundle_id": "rulecard_v2.test"})
    policy = slice_.retrieval_policy
    assert "rulecard_pack_bundle_id_error" not in policy
    # 桩 client 下 lattice/auth 缺席 → 既有保守关闭路径（非本缺口范围）
    assert policy["component_structure_bundle_mismatch"]["pack_bundle_id"] == "rulecard_v2.test"
