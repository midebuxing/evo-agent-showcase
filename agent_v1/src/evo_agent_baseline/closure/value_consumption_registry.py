# -*- coding: utf-8 -*-
"""绑定级值消费授权登记（A′裁决，2026-08-02 决策门）。

**为什么单独一个模块**：`obligation_deriver` 受常驻闸约束不得出现细族 ID
字面量（`test_licence_is_not_a_family_name_whitelist`——族名判据会随卡包腐化）。
本登记是**决策门逐绑定授权的数据**，不是派生器判据逻辑；数据与逻辑分居，
派生器只 import 名字。

登记键＝(rule_card_id, slot_ref_id)。命中且作用域选择确已选中楼级聚合行时：
值 true → closed+satisfied（沿用现状）；false → open+unknown+
`observed_false_without_violation_basis`；**不得产出 violated**。
A′原文：字面 A 若只按槽名生效，授权仍然过宽，不通过——**扩表必须逐绑定
重过决策门**，并同步四门验收（配对重放/实判核对/LLM 召回）。
裁决记录：`团队文档/我的笔记/技术与研究债.md` DEBT-083 节（2026-08-02）。
"""
from __future__ import annotations


# S1 逐行批准后（2026-08-02）本集合改为**从权威结构表派生**（裁决：「现有
# VALUE_CONSUMPTION_AUTHORIZED_BINDINGS 只能派生出 A′策略子集」——本轮恰
# 第 37 行 §2.1.3(a)）。权威在 binding_contract_registry.BINDING_CONTRACTS；
# 行 1-36 是产物态仅诊断，**不得**混进本集合（A′检查在产物态闸之前，混入会
# 把假值错落成 observed_false_… 而非合同承诺的 artifact_state_…）。
from .binding_contract_registry import (
    VALUE_CONSUMPTION_BINDINGS as VALUE_CONSUMPTION_AUTHORIZED_BINDINGS,
)

__all__ = ["VALUE_CONSUMPTION_AUTHORIZED_BINDINGS"]
