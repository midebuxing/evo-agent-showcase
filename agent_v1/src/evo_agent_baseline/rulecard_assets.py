"""卡包资产的中立常量层（闭包层与检索层共用，两边都不 import 对方）。

**为什么要有这个模块**：规格 v0.4 §4739 规定分层单向——只允许**闭包层消费检索数据对象**，
`retrieval` **不得 import `closure`**。但 2026-07-27 终审查出两处新增反向依赖：

| 处 | 原写法 |
|---|---|
| `retrieval/fact_retriever.py:626` | `from ...closure.obligation_deriver import W0_09_ARTIFACT_SLOTS` |
| `retrieval/rulecard_bundle_identity.py:30` | `from ...closure.identity_blueprint_catalog import DEFAULT_AUTHORITATIVE_BUNDLE_PATH` |

两处都写了「延迟 import 避免循环依赖」——但**延迟 import 不改变分层关系**，
仍是 `retrieval → closure` 的反向依赖。

⚠️ **更值得记的是：`agent_v1/.importlinter` 只有两条契约**
（感知层 ⊥ 认知层、runtime 不得 import `eval`），**`retrieval ⊥ closure` 从来没进过契约**
⇒ pre-commit 的架构闸对这条规格红线**一直是全盲的**，五轮人工审核才抓到。
本轮已同步补进契约（见 `.importlinter`）。

**本模块只放纯数据常量**（无行为、无依赖），故两层都可安全 import。
⇒ 往这里加东西前先问：它是不是**纯数据**？带行为的东西不属于这里。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["W0_09_ARTIFACT_SLOTS", "DEFAULT_AUTHORITATIVE_BUNDLE_PATH"]


# W0-09 产物齐备槽登记表（世界侧 `artifact.*` 槽名的封闭集合）。
# 闭包侧用它判「这条事实是不是产物齐备布尔」；检索侧用它锁死
# `_SLOT_TARGET_FALLBACKS` 的成员必须 ⊆ 本表（防有人塞非产物成员进回退表）。
W0_09_ARTIFACT_SLOTS: set = {
    "artifact.certificate.material_or_product",
    "artifact.form.mbi1",
    "artifact.form.mbi2",
    "artifact.form.mbi3_or_mbi3a",
    "artifact.form.mbi4",
    "artifact.form.mbi5",
    "artifact.notice.investigation_intention",
    "artifact.photo.annotated",
    "artifact.plan.annotated",
    "artifact.proposal.detailed_investigation",
    "artifact.proposal.repair",
    "artifact.proposal.repair_revision",
    "artifact.record.inspection_log",
    "artifact.record.nonconformity_sp2",
    "artifact.record.supervision_log_sp1",
    "artifact.record.test_or_material_witness",
    "artifact.report.completion",
    "artifact.report.inspection",
    "artifact.statement.extra_works_separated",
    "artifact.statement.scope_and_order_coverage",
}


# 磁盘权威卡包路径。三方同源校验的第三条腿读它——**取的是卡包自己声明的
# `bundle_id`，不是调用方随手写的标签**（实测三个调用面三个值）。
DEFAULT_AUTHORITATIVE_BUNDLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
    / "rule_cards.json"
)
