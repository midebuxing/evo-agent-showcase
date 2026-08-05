"""磁盘权威卡包 `bundle_id` 的单一读取点（2026-07-27 统一调用方标签）。

背景：`rulecard_bundle_id` 入参曾三个调用面三个值——资产
`rulecard_v2.mbis_cop_2023` / 四个脚本常量 `mbis_cop_2023` /
`RunOrchestrator` 缺省 `rule_card_v2`。该入参已降为纯诊断
（`rule_retriever.assemble_rule_slice` 的 P1-2 三方同源校验第三条腿改读
磁盘权威卡包声明值），但调用方标签仍有误导性，故统一为：

    **所有调用方从本模块读取，不再各自复制常量。**

权威锚点 = `closure.identity_blueprint_catalog.DEFAULT_AUTHORITATIVE_BUNDLE_PATH`
指向的卡包 JSON 自己声明的 `bundle_id` 字段。closure 常量经**模块属性惰性
取值**（closure ← retrieval 顶层导入有成环风险；且测试 monkeypatch 该常量
即可重定向，勿在模块顶层绑定）。
"""
from __future__ import annotations

import json
from typing import Optional


def read_authoritative_rulecard_bundle_id() -> Optional[str]:
    """读磁盘权威卡包声明的 `bundle_id`。

    - 文件缺失 → 返回 None（调用方自行决定保守路径）；
    - 🔴 fail-closed 形状护栏（与 `rule_retriever` 第三条腿同口径）：
      ① 顶层非 JSON 对象 → TypeError（否则 `.get()` 抛 AttributeError）；
      ② `bundle_id` 非字符串 → TypeError（否则下游 `set()` 不可哈希炸掉）。
    """
    # 🔴 2026-07-27 终审 P2：同上，原从 `closure` 取构成反向依赖。
    from evo_agent_baseline.rulecard_assets import DEFAULT_AUTHORITATIVE_BUNDLE_PATH


    if not DEFAULT_AUTHORITATIVE_BUNDLE_PATH.is_file():
        return None
    pack_doc = json.loads(
        DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8")
    )
    if not isinstance(pack_doc, dict):
        raise TypeError(
            f"权威卡包顶层须为对象, 实为 {type(pack_doc).__name__}")
    bundle_id = pack_doc.get("bundle_id")
    if bundle_id is not None and not isinstance(bundle_id, str):
        raise TypeError(
            f"权威卡包 bundle_id 须为字符串, 实为 {type(bundle_id).__name__}")
    return bundle_id


def authoritative_rulecard_bundle_id() -> str:
    """调用方取标签的唯一入口；读不到即 fail-closed 抛错。

    不许编一个标签继续跑——标签错比崩掉更隐蔽（历史三值不一致就是这么来的）。
    """
    bundle_id = read_authoritative_rulecard_bundle_id()
    if not bundle_id:
        raise RuntimeError(
            "磁盘权威卡包 bundle_id 读不到（文件缺失或字段为空）——"
            "调用方标签只有这一个权威来源，不回落任何硬编码缺省"
        )
    return bundle_id


__all__ = [
    "read_authoritative_rulecard_bundle_id",
    "authoritative_rulecard_bundle_id",
]
