# -*- coding: utf-8 -*-
"""S3 甲′待裁保护表（决策门裁决 2026-08-02；丁组重送裁定前的过渡保护）。

7 条无键 `(rule_card_id, slot_ref_id)` 绑定（§2.1.3(b)/6.1.2(a)(b)/6.1.3/
6.2.1/6.2.2/6.2.3，全 roles=evidence、消费 `supervision.record.completed`）。
裁决要点：
- 这些绑定在丁组逐绑定裁定完成前**不得产生任何实判**——候选存在即转
  `open + binding_requires_adjudication_authorization`；
- **连片段事实也拦**（§6.1.3 按片段派生——批 I 现产物已有 29 条
  false→satisfied 假实判，这层专防它）；
- 位置＝候选缺失检查之后、通用「存在即满足」之前。

🔴 指纹方向与授权表相反：**保护在指纹失配时不解除**（解除保护=放开实判，
危险方向）；`card_content_sha256` 仅供审计与漂移报警（常驻测试锁定当前包
恒等，漂移=测试红=触发重裁，不是运行时自动放行）。
重送裁定后逐行移出本表（6 条按楼级 all_true 裁、§6.1.3 单列）。
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Tuple

PENDING_ADJUDICATION_ROWS: Tuple[Dict[str, Any], ...] = tuple(
[
    {
        "rule_card_id": "rc.mbis.repair.supervision.ri.duty.s2_1_3_b_supervise_rectification_and_repair.c01",
        "slot_ref_id": "rc.mbis.repair.supervision.ri.duty.s2_1_3_b_supervise_rectification_and_repair.c01.sr01",
        "card_content_sha256": "e1c811bbf46a6e1474f39f5121db2f0155947cc9a455ef4bb59d89ed633e0e09"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_2_a_safe_working_environment.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_2_a_safe_working_environment.c01.sr02",
        "card_content_sha256": "c53d24ffb6f11993152e2fcb0661b31e6733ed81c41c3a17a4e4ccf03041c355"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_2_b_control_repair_and_scaffolding.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_2_b_control_repair_and_scaffolding.c01.sr02",
        "card_content_sha256": "656421b2e9e936cdb6a795fd82816d9089cc4261dade75c4b6d932ec15782e6c"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_3_comply_bo_and_provide_supervision.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_1_3_comply_bo_and_provide_supervision.c01.sr02",
        "card_content_sha256": "3fb165d716042b17b5d5c31ef72218094307f3a9ea836ab0a16cab672d66bcbf"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_1_provide_safety_measures.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_1_provide_safety_measures.c01.sr02",
        "card_content_sha256": "9594f6f7e25c1de8068f2a3a128c220fd510b711599a6bffde750654dc30f929"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_2_provide_safe_access.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_2_provide_safe_access.c01.sr02",
        "card_content_sha256": "43d54b26e73adae8ee71fbf731660b9d29087b834e4fc2be7d44f9625c8986bd"
    },
    {
        "rule_card_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_3_bamboo_scaffold_per_guide.c01",
        "slot_ref_id": "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control.s6_2_3_bamboo_scaffold_per_guide.c01.sr02",
        "card_content_sha256": "1f6081d472a311b11c32e467ef4005bb81df312f8554c1571def148981d1dd8a"
    }
])

PENDING_ADJUDICATION_BINDINGS: FrozenSet[Tuple[str, str]] = frozenset(
    (r["rule_card_id"], r["slot_ref_id"]) for r in PENDING_ADJUDICATION_ROWS
)
