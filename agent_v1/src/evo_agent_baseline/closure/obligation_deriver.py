"""义务推导 —— spec §6.3.3 ~ §6.3.10。

各义务源 → Obligation 的确定性推导：
- §6.3.3 trigger obligations + aggregate_trigger_logic
- §6.3.4 slot role obligations + qualifiers_match
- §6.3.5 threshold obligations（评估逻辑在 threshold_eval.py）
- §6.3.6 artifact / evidence obligations + [v0.4-C-1] artifact alias map
- §6.3.7 deadline obligations
- §6.3.8 exception obligations
- §6.3.9 definition obligations
- §6.3.10 obligation_graph nodes + edges

确定性、无 LLM、无 Neo4j。obligation_id 由 validator 在落库前统一回填，本模块
构造 Obligation 时先用占位 id（validator.assign_obligation_ids 重写）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, get_args

from evo_agent_baseline.contracts import (
    FactAtom,
    Obligation,
    ObligationKind,
    RuleCardDTO,
)

from .fact_binding import (
    SENTINEL_BARE,
    SENTINEL_NON_ADJUDICATIVE,
    FactIndex,
    bound_sentinel_classification,
    conflict_status,
    parse_value,
)
from .schema import ObligationEdgeDTO, ObligationNodeDTO
from .threshold_eval import (
    bind_measure,
    evaluate_threshold_comparison,
)

# 构造期占位 obligation_id；validator 落库前用确定性 hash 重写。
_PLACEHOLDER_OID = "PENDING"


class SourceToken(NamedTuple):
    """扁平化前来源令牌（identity-v5 现网键切换增补 §1.2/§1.4）——node/edge 求值器内部在「正在处理
    哪个源项」处**旁路登记**，供关联层按五元组从 catalog 取蓝图、组 `BoundObligation`。

    **纯旁路红线（§1.3）**：登记**不改**返回 v1 `Obligation` 字节、**不参与**任何状态判断、
    **不进** `evaluate_*` 判定分支——`source_sink=None`（默认，即现网 live 路径）时零副作用、
    产物 byte-identical。`primary_id` 为**原始源标识**（node_id / artifact_id / deadline_id /
    edge_id / target_node_id，未编码 SID）；SID 编码由关联层做（与 blueprint 侧同一编码，杜绝反推/漂移）。

    **fail-closed 完备令牌（§1.4，codex 阻断 2 修订）**：令牌**自携**关联所需全部维度——
    `scope_fid`（求值时冻结 scope，None=building）、`channel`（参与键构造、须 ↔ role 规范映射一致）、
    `member`/`edge_ids`（edge 分身/聚合判别）；关联层按令牌自身确定五元组，**调用者不得自由补 scope**。

    `role` discriminator（消 obligation_graph channel 内 node/method/edge 歧义）：
      node          —— node-level 主义务（out[0]）
      method        —— method-derivation 子义务（可分 → 独立 method-derived 身份；不可分 → 折回 node-main）
      edge_dangling —— 悬空 edge 审计（source ∨ target node 缺失，§3.4.3）
      edge_unknown  —— 未知 relation 分身审计（member=source/target，§3.4.3）
      edge_inactive —— inactive-target 聚合审计（edge_ids=完整排序集，§3.4.3）
      artifact      —— node 内 artifact 子义务（由 workflow_artifact channel 承载，§1.2）
      deadline      —— node 内 deadline 子义务（由 workflow_deadline channel 承载，§1.2）
    """

    channel: str
    primary_id: str
    role: str
    scope_fid: Optional[str]          # §1.4 冻结 scope（求值时 fragment_id；None=building）
    member: str = ""                  # edge_unknown 分身判别（"source"/"target"），其它 ""
    edge_ids: Tuple[str, ...] = ()    # edge_inactive 聚合完整排序集，其它 ()


# ===================================================================== #
# §6.3.6 [v0.4-C-1] artifact alias map（收口版）
# ===================================================================== #
# 17 个精确绑定 —— 每个 artifact_key 独占一个 sidecar slot，slot 互不共享。
ARTIFACT_KEY_TO_SIDECAR_SLOT: Dict[str, str] = {
    "certificate.material_compliance": "artifact.certificate.material_or_product",
    "drawing.annotated_location_plan": "artifact.plan.annotated",
    "form.mbi3_or_mbi3a": "artifact.form.mbi3_or_mbi3a",
    "form.mbi4": "artifact.form.mbi4",
    "form.mbi5": "artifact.form.mbi5",
    "notice.detailed_investigation_intention": "artifact.notice.investigation_intention",
    "photo.annotated_defect": "artifact.photo.annotated",
    "proposal.detailed_investigation": "artifact.proposal.detailed_investigation",
    "proposal.repair": "artifact.proposal.repair",
    "proposal.repair_revision": "artifact.proposal.repair_revision",
    "record.inspection_log": "artifact.record.inspection_log",
    "record.nonconformity_correction_sp2": "artifact.record.nonconformity_sp2",
    "report.completion": "artifact.report.completion",
    "report.inspection": "artifact.report.inspection",
    "report.test_result": "artifact.record.test_or_material_witness",
    "statement.mbis_repairs_separated_from_additional_upgrades": "artifact.statement.extra_works_separated",
    "statement.outstanding_order_scope_included": "artifact.statement.scope_and_order_coverage",
}

# 8 个无专属 slot —— 与他人共用 slot，sidecar 无 artifact_key 限定词无法消歧，
# 一律判 blocked + artifact_not_modeled_upstream，不桥接、不假 satisfied。
ARTIFACT_KEYS_NOT_MODELED: set = {
    "notice.representative_appointment_intended",
    "notice.ri_appointment",
    "notice.ri_cessation",
    "notice.ri_temporary_nomination",
    "notice.temporary_ri_nomination_cessation",
    "proposal.supervision",
    "record.site_visit_log",
    "record.supervision_checklist",
}

# W0_09 §5.2 sidecar artifact.* slot（实测 20 个）—— resolve_artifact_slot 安全断言用。
# W0-09 产物齐备槽登记表**权威源已移至中立层** `evo_agent_baseline.rulecard_assets`
# （2026-07-27 终审 P2：检索侧本来 import 这里，构成 `retrieval → closure` 反向依赖，
#  违反规格 v0.4:4739。移到两层都可安全 import 的纯数据层，**不复制第二份**）。
from evo_agent_baseline.rulecard_assets import W0_09_ARTIFACT_SLOTS  # noqa: E402,F401

# 全量 25 个 artifact_key（17 + 8）—— resolve_artifact_slot 用来识别「未登记新 key」。
_KNOWN_ARTIFACT_KEYS: set = set(ARTIFACT_KEY_TO_SIDECAR_SLOT) | ARTIFACT_KEYS_NOT_MODELED

# §6.3.6 truthy / falsy canonicalization。
TRUTHY_VALUES: set = {
    True,
    "true",
    "present",
    "submitted",
    "delivered",
    "completed",
    "available",
    "yes",
}
FALSY_VALUES: set = {
    False,
    "false",
    "absent",
    "missing",
    "not_submitted",
    "no",
}

# ---- spec §6.3.6 收口规则的内部一致性断言（import 时即校验）----
assert len(ARTIFACT_KEY_TO_SIDECAR_SLOT) == 17, "must be 17 precise bindings"
assert len(ARTIFACT_KEYS_NOT_MODELED) == 8, "must be 8 not-modeled keys"
assert (
    set(ARTIFACT_KEY_TO_SIDECAR_SLOT) & ARTIFACT_KEYS_NOT_MODELED == set()
), "two groups must be disjoint"
assert (
    len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values())) == 17
), "each slot bound by at most one key"
assert (
    set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values()) <= W0_09_ARTIFACT_SLOTS
), "all binding targets must be real W0_09 artifact slots"
assert (
    "form.mbi1" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
    and "form.mbi2" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
), "form.mbi1/mbi2 are sidecar slots without artifact_key, must not be in map"


class SchemaContractError(Exception):
    """rule_card 出现 spec 未登记的结构（spec §6.3.6 resolve_artifact_slot）。"""


def resolve_artifact_slot(artifact_key: str) -> Optional[str]:
    """artifact_key → sidecar slot（spec §6.3.6 resolve_artifact_slot）。

    - 在精确绑定 map 内 → 返回 slot
    - 在 NOT_MODELED 内 → 返回 None（上层判 blocked + artifact_not_modeled_upstream）
    - 既不在 map 也不在 NOT_MODELED → 抛 SchemaContractError（未登记新 key）

    禁止 prefix fallback。
    """
    if artifact_key in ARTIFACT_KEY_TO_SIDECAR_SLOT:
        return ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]
    if artifact_key in ARTIFACT_KEYS_NOT_MODELED:
        return None
    raise SchemaContractError(
        f"unknown artifact_key {artifact_key!r} — rule_card 出现 spec 未登记的新 key"
    )


# ===================================================================== #
# 产物齐备布尔的「证据许可闸」（2026-07-27）
# ===================================================================== #
# 病灶：语义**不是产物**的义务（检验涵盖范围 / 记录 / 报告栏目 / 动作）此前会因
# 「相关产物齐备布尔 = true」被判 satisfied、= false 被判 violated。
# 「檢驗報告已擬備」不等于「涵蓋範圍達標」——一份报告可以齐备而漏检半栋楼。
#
# 判据两侧都只读**已登记的封闭集合**，不涉族名 / ID 后缀 / 字符串猜测：
#
# 【世界侧】某条事实是不是「产物齐备布尔」——三枚各自权威的锚，取并集（fail-closed，
#   任一命中即算，缺一个锚不会让闸静默失效）：
#     ①`qualifiers.carrier_domain == "artifact"` —— W0 生成器 `registry.py` 给槽登记
#       的承载域，sidecar 正是按它把值路由进 `artifact_requirement_state` 桶
#       （`worldgen/sidecar.py:_CARRIER_DOMAIN_TO_BUCKET`）。这是**产生**该布尔的原因。
#     ②`slot_id ∈ W0_09_ARTIFACT_SLOTS` —— 闭包侧自有的 20 个 `artifact.*` 槽登记表
#       （本文件上方，带 import 期断言、且被 `resolve_artifact_slot` 的目标集约束）。
#     ③`provenance.derivation == "slot_target_fallback"` —— 检索侧
#       `derive_slot_target_fallback_facts` 把若干成员槽按 fragment 折叠成的派生布尔
#       （如 `reporting.artifact.prepared`）。**认的是派生通道，不是目标槽名白名单**；
#       成员全属产物域由生产者 import/调用期断言（成员 ⊆ `W0_09_ARTIFACT_SLOTS`）。
#       ①② 对这类派生事实均不命中（无 carrier_domain、槽名不在 20 表）。
#   实测（重锚批 30 栋全部 FactPack）：①② 在真实产物上判定完全一致，且都 ⇔
#   `provenance.entry_type == "artifact_requirement_state"`；③ 单独兜住派生通道。
#
# 【义务侧】哪些 kind 有资格据它下确定判定。`ObligationKind` 是 contracts 里的**封闭
#   枚举**，下面两个集合对它做完全划分（import 期断言完备 + 互斥；将来 contracts 新增
#   一个 kind 而忘了归类 → 第一次 import 就炸，不会静默 fail-open）：
#     · `artifact` —— 义务本体就是「该产物须齐备」。它只由三条既有结构规则产生：
#       `_BUCKET_DEFAULT_KIND`（for_submission / for_completion）、卡的
#       `workflow_operands.artifacts` 显式声明、`refine_action_kind`（action 以
#       submit / deliver 开头）。产物齐备布尔正是它的直接证据 —— 许可。
#     · `trigger` / `prerequisite` / `definition` / `exception` / `scope` —— 这些**不是
#       义务**，是记录世界状态的条件项（spec §6.3.4 role→kind）。「若已提交 MBI4 则…」
#       把产物状态当**条件**读是正当的，故许可。
#     · 其余 —— 义务语义都不是产物存在性：`evidence`（该义务的主证据）/ `report_field`
#       （报告须载明某栏）/ `action`（须执行某动作）/ `supervision` / `method` /
#       `prohibition` / `escalation` / `deadline` / `threshold`。一律不许可。
#
# ⚠️ 为什么 `evidence` 不许可，而卡仍有正当出路：`for_matching` bucket 默认 kind 是
#   evidence（「此证据供比对」），但 `evidence_requirement.evidence_kind` 是**卡侧已有
#   的显式声明字段**——真要表达「此产物须齐备」的卡可以写 `evidence_kind="artifact"`，
#   于是自动落进许可侧。故本闸不是堵死语义，是要求卡把语义**说出来**。
ARTIFACT_STATE_LICENSED_KINDS: frozenset = frozenset({
    "artifact",
    "trigger", "prerequisite", "definition", "exception", "scope",
})
ARTIFACT_STATE_UNLICENSED_KINDS: frozenset = frozenset({
    "evidence", "report_field", "action", "supervision", "method",
    "prohibition", "escalation", "deadline", "threshold",
})
assert ARTIFACT_STATE_LICENSED_KINDS & ARTIFACT_STATE_UNLICENSED_KINDS == frozenset(), (
    "许可 / 不许可两集合必须互斥"
)
assert (
    ARTIFACT_STATE_LICENSED_KINDS | ARTIFACT_STATE_UNLICENSED_KINDS
) == frozenset(get_args(ObligationKind)), (
    "两集合必须完全划分 ObligationKind —— contracts 新增 kind 时必须在此归类，"
    f"未归类={sorted(frozenset(get_args(ObligationKind)) - ARTIFACT_STATE_LICENSED_KINDS - ARTIFACT_STATE_UNLICENSED_KINDS)}；"
    f"多出={sorted(ARTIFACT_STATE_LICENSED_KINDS | ARTIFACT_STATE_UNLICENSED_KINDS - frozenset(get_args(ObligationKind)))}"
)

# 命中闸时统一的 open 原因码 + notes 前缀（notes 里带上槽名，便于消费者定位卡侧接线）。
ARTIFACT_STATE_OPEN_REASON = "artifact_state_not_valid_evidence"
# 2026-08-03 三方决策门仲裁「丁」路：非产物读数的诊断型绑定用**另一个**码。
# 对 `procedure.*` / `risk.*` 等说「查到了文件」是事实错误（详 contracts.py 该码注释）。
DIAGNOSTIC_BINDING_OPEN_REASON = "diagnostic_binding_not_valid_evidence"
# `building_reading_aggregation` 通道允许的 derivation 白名单（2026-08-03 决策门）。
# `None`/`""` ＝ 世界原生直采；`slot_target_lookup_rule` ＝
# `projection_runtime_mapping` 登记的查找规则派生。**不含** `slot_target_fallback`。
_BUILDING_READING_DERIVATIONS = frozenset({None, "", "slot_target_lookup_rule"})

# 🔴 `code_derived_reading` 通道：**戳 → 期望载体**的登记映射（2026-08-03 决策门乙案）。
#
# 只放 `test_performed_from_measurement` 一个戳：它由
# `fact_retriever.derive_verification_performed_facts` 产出——DEBT-049 第三阶段审过的
# 确定性桥（canonicalize-first、白名单方法集、每 (fragment, method) 去重一条），
# 语义＝「该 fragment 有该测试方法的量测记录 ⇒ 该试验已做」，正是槽名本义。
#
# **登记载体是必须项不是建议项**（kimi 判）：那个桥从量测行**拷贝** `carrier_type`
# （`fact_retriever.py`），**载体漂移即语义漂移**，闸就该响。
# 只核戳不核载体 ⇒ 将来桥改从别的载体拷，这道校验会静默失效。
_CODE_DERIVED_READINGS = {"test_performed_from_measurement": "measurement"}


def diagnostic_refusal_reason_code(facts: List[FactAtom]) -> str:
    """诊断型拒判该落哪个原因码——**只由已冻结的产物态事实分类器决定**。

    🔴 仲裁明令：不得由合同行里的自由文本出口字段控制（那等于把已封死的判定滑轨
    交给单行误填）。本函数是唯一分流点，`true_exit`/`false_exit` 只作声明与审计。
    """
    return (ARTIFACT_STATE_OPEN_REASON
            if any(is_artifact_state_fact(f) for f in facts)
            else DIAGNOSTIC_BINDING_OPEN_REASON)


def is_slot_target_fallback_fact(fact: FactAtom) -> bool:
    """该事实是否由 `_SLOT_TARGET_FALLBACKS` 回退表折叠而来（`is_artifact_state_fact` 第三锚）。

    单列出来，是因为它比另两锚**弱一档**：另两锚是世界模型真产的产物态布尔，
    而它是 `fact_retriever.py` 一张**硬编码回退表**把 12 个 `artifact.*`
    按 fragment 折叠出来的派生物，目标槽只有一个 `reporting.artifact.prepared`。
    """
    return str((fact.provenance or {}).get("derivation") or "") == "slot_target_fallback"


def is_artifact_state_fact(fact: FactAtom) -> bool:
    """该事实是否为「产物齐备布尔」（三锚取并集，见上方注释）。"""
    if str((fact.qualifiers or {}).get("carrier_domain") or "") == "artifact":
        return True
    if str(fact.slot_id or "") in W0_09_ARTIFACT_SLOTS:
        return True
    # 第三锚：认派生通道，不按目标槽名白名单。
    return is_slot_target_fallback_fact(fact)


def artifact_state_licenses_verdict(
    kind: str,
    facts: List[FactAtom],
    *,
    kind_from_action_refinement: bool = False,
) -> bool:
    """`kind` 是否有资格据 `facts` 下 satisfied / violated。

    只在**证据里含产物齐备布尔**时才可能拒绝；不含时恒 True（对既有判定零影响）。
    未登记的 kind 一律按不许可处理（fail-closed）。

    🔴 `kind_from_action_refinement`（2026-08-03）——本闸此前把 `kind="artifact"`
    的**三个来源**一视同仁地许可，而 docstring 自己列的第三个来源
    `refine_action_kind`（action 以 submit/deliver 开头）**不是结构规则、是对
    `action` 字段做字符串前缀猜测**，而 `action` **无受控词表、是卡作者写的译文**。

    实测后果（批 I `phase_i_fragcov2_seed301_20260729`，30 栋）：
      · 守则 §4.2.2「詳細調查的建議**須包括**目的／方法／範圍／理由」四张卡，
        action 写成 `submit_compliant_proposal` ⇒ 改类成 artifact ⇒ 拿
        「**建议书文件存在**」判 **satisfied**（20 条）。同条 (d) 因 action 写
        `include_*` 留在 `report_field`、落不许可侧，**诚实 unknown**——
        **五个并列子项待遇由一个译文动词决定。**
      · §5.3.4(b)「呈交替换物料证书**予建築事務監督**」等，拿「证书文件不在」
        判 **violated 27 条**——而世界侧 `artifact.*` **只有"文件存在与否"一个轴、
        没有签署/呈交轴**，故这是**假违规**。
    🔴 **隔离 A/B 实测 75 条**（satisfied **46** / violated 29）——
    「95 条（66/29）」是在**旧 HEAD 代码状态**上量的，**已不可引**
    （差的 20 条在当前工作树里已被其它改动拦下）。
    满血档 `baseline_v4_final_seed301` 命中 **0 条**（候选全 unknown ⇒ 数据依赖）。

    ⇒ **改类而来的 artifact 一律不许可**：它的义务谓词是「呈交/送达/载明」，
    不是「该产物存在」；缺的那个轴世界侧没有 ⇒ 正确结果是**诚实说不知道**
    （`open + artifact_state_not_valid_evidence`），不是猜一个判定。
    ⚠️ 这**不影响**由 `_BUCKET_DEFAULT_KIND` 与卡的 `workflow_operands.artifacts`
    两条**结构规则**产生的 artifact 义务。

    🔴🔴 **但「那两类的谓词确实就是『该产物须齐备』」是一条未经裁定的假设
    （2026-08-03 审核门指出，我原文把它写成了断言）。**

    它与本条刚推翻的那条（「产物状态当条件读是正当的」）**是同一形状的论证**：
    都是「这一类按定义就该如此」，都没有对任何一条具体条款做过裁定。
    我用 52 个组合逐条对中文原文把前者推翻了（「产物须齐备」**0 条**），
    却用同样的形式给后者发了豁免——**双重标准。**

    **规模（批 I 实测，比已处置的三件加起来还大）**：
    `kind=artifact` 且拿到确定判定、且**不靠**回退表槽的义务
    ＝ **20,178 条**（satisfied 13,991 ／ violated 6,187）。
    主要槽：`artifact.report.inspection` 9,610 ／ `artifact.report.completion` 4,537 ／
    `artifact.proposal.repair` 2,711。

    **具体隐患**：52 裁定里那 15 条「须呈交／签署／载明」，
    若同一张卡经桶通道另落一条 artifact 子义务，
    **节点义务被本闸拦成 unknown 之后，桶子义务可能仍是 satisfied**
    ——§4.2.2 那六条到底全翻了没有，**没有数**。

    ⇒ **此处不做改动**（无裁定依据就改，与无裁定依据就放行是同一种错），
    但**必须按同一标准逐条裁定**。已登记为待办，见规划 §2.9。
    """
    # 🔴 回退表折叠行**对任何 kind 都不许可**（2026-08-03，52 组合逐条裁定后落）。
    #
    # `reporting.artifact.prepared` 不是世界模型产的槽，是 `fact_retriever.py:601`
    # 一张硬编码回退表把 12 个 `artifact.*` 按 fragment 折叠出来的
    # （`_SLOT_TARGET_FALLBACKS`，卡侧用 `artifact_key` 限定符选中其中一份）。
    # 它只有**一条语义轴：这份特定文件存在与否**。
    #
    # 裁定依据（52 个 (artifact_key, action) 组合逐条对**中文法规原文**判，
    # 引文经 `scripts/verify_adjudication_quotes.py` 机器核回原文、**52/52 逐字命中**）：
    #
    #     产物须齐备（＝拿「文件存在」判定正当）   0 条   ← 一条都没有
    #     须呈交／签署／载明                      15 条
    #     行为须发生                              37 条
    #     存疑                                     0 条
    #
    # 典型：`report.completion × verify_repair_standard`（29 处引用）——
    # 「核实修葺标准」拿「完工报告存在」判 satisfied；
    # `report.inspection × review_background_information`（15 处）——「查阅背景资料」同理。
    #
    # 实测影响面（批 I）：仍靠该槽拿到确定判定的 **2,367 条**
    # ＝ `kind=trigger` **2,178** ＋ `kind=artifact` **189**。
    # ⚠️ trigger 那 2,178 条**本闸拦不到**——`evaluate_trigger` 根本不调本闸，
    # 那是第二件的活；本条只解决 189 条。
    if any(is_slot_target_fallback_fact(f) for f in facts):
        return False
    if kind_from_action_refinement:
        return not any(is_artifact_state_fact(f) for f in facts)
    if kind in ARTIFACT_STATE_LICENSED_KINDS:
        return True
    return not any(is_artifact_state_fact(f) for f in facts)


def _artifact_state_refusal(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    facts: List[FactAtom],
) -> Obligation:
    """构造「拒绝据产物齐备布尔下判定」的 open + unknown 义务。

    证据 id / 观测值**照旧落盘**——消费者要看得见「系统查到了什么、为什么不算」。
    """
    common = dict(common)
    common.pop("blocked_reason_code", None)
    code = diagnostic_refusal_reason_code(facts)
    common["open_reason_code"] = code
    if code == ARTIFACT_STATE_OPEN_REASON:
        slots = sorted({str(f.slot_id) for f in facts if is_artifact_state_fact(f)})
        common["notes"] = (
            common.get("notes", "")
            + f"; artifact-state slots {slots!r} cannot establish a {kind} obligation"
        ).strip("; ")
    else:
        # 🔴 非产物读数**绝不**称作 `artifact-state slots`——那不只是展示层不雅，
        # 会污染机器排障线索（仲裁列为判丙的决定性理由之一）。
        slots = sorted({str(f.slot_id) for f in facts})
        common["notes"] = (
            common.get("notes", "")
            + f"; adjudicated: slots {slots!r} cannot establish a {kind} obligation"
        ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _canon_truthy(value: Any) -> Optional[bool]:
    """artifact value canonicalization → True / False / None（无法判定）。"""
    if isinstance(value, str):
        v: Any = value.strip().lower()
    else:
        v = value
    # list/dict 等结构值不可直接做 set 成员测试；它们不是本通道可判的布尔证据。
    if v is True or (isinstance(v, (str, int, float)) and v in TRUTHY_VALUES):
        return True
    if v is False or (isinstance(v, (str, int, float)) and v in FALSY_VALUES):
        return False
    return None


# ===================================================================== #
# Obligation 构造辅助
# ===================================================================== #
def _new_obligation(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    closure_status: str,
    satisfaction_status: str,
    **extra: Any,
) -> Obligation:
    """统一构造 Obligation，回填 run/world/building、source 元数据与状态码。

    fact_pack_meta 携带 run_id / world_id / building_id。extra 透传义务专有字段。
    obligation_id 先填占位，validator 落库前重写。
    """
    base: Dict[str, Any] = dict(
        obligation_id=_PLACEHOLDER_OID,
        run_id=fact_pack_meta["run_id"],
        world_id=fact_pack_meta["world_id"],
        building_id=fact_pack_meta["building_id"],
        # fragment 级派生（spec 草案 §6.3.0）：fragment 作用域下派生的义务携带归属，
        # 楼级派生时 meta 无此键 → None（v0.4 行为不变）。在 obligation_id 生成前填
        # （compute_obligation_id 公式本含 fragment 段）。
        fragment_id=fact_pack_meta.get("fragment_id"),
        source_rule_card_id=card.rule_card_id,
        source_family_id=card.family_id,
        kind=kind,
        closure_status=closure_status,
        satisfaction_status=satisfaction_status,
    )
    base.update(extra)
    return Obligation(**base)


def _card_clause_ids(card: RuleCardDTO) -> List[str]:
    """从 card.source_section 收集 clause id（best-effort）。"""
    out: List[str] = []
    for sec in card.source_section or []:
        if isinstance(sec, dict):
            cid = sec.get("clause_id") or sec.get("section_id") or sec.get("id")
            if cid:
                out.append(str(cid))
    return out


def _card_quote_ids(card: RuleCardDTO) -> List[str]:
    """从 card.source_quote 收集 source_quote_id（best-effort）。"""
    out: List[str] = []
    for q in card.source_quote or []:
        if isinstance(q, dict):
            qid = q.get("source_quote_id") or q.get("quote_local_id") or q.get("id")
            if qid:
                out.append(str(qid))
    return out


def _sentinel_short_circuit(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    bound_facts: List[FactAtom],
    fact_index: FactIndex,
) -> Optional[Obligation]:
    """DEBT-083 裁决分叉一「甲」消费面短路（2026-08-02）。

    挂在既有开关上：FactIndex 以 `exclude_explanatory=False` 构建（缺省）时
    分类器恒判非哨兵、本函数恒返回 None——行为与改动前逐位相同。

    绑定事实组（值已判一致）经 `bound_sentinel_classification` 三态分类：
    - 非判定（哨兵值＋同载体同槽伴随行＋原因码在冻结集合）：
      `closed + not_applicable`、`comparator_result=False`（同触发器结构 NA
      形态），notes 写 `non_adjudicative_sentinel: reason=<原因码>`——生产者
      已明示"不适用"及原因，不是查不到事实，不落 open；
    - 裸哨兵（无伴随行或原因码出集）：`blocked + schema_contract_violation`，
      notes 写 `bare_sentinel_without_fallback_companion`——缺省拒绝，
      **不许猜成不适用**；
    - 非哨兵：返回 None，调用方走原求值路径。
    """
    sentinel_kind, reason = bound_sentinel_classification(bound_facts, fact_index)
    if sentinel_kind == SENTINEL_NON_ADJUDICATIVE:
        common["evidence_fact_ids"] = [f.fact_id for f in bound_facts]
        common["evidence_node_refs"] = [
            f.source_node_id for f in bound_facts if f.source_node_id
        ]
        common["observed_value_json"] = bound_facts[0].value_json
        common["comparator_result"] = False
        notes = common.get("notes", "")
        common["notes"] = (
            notes + f"; non_adjudicative_sentinel: reason={reason}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "not_applicable", **common
        )
    if sentinel_kind == SENTINEL_BARE:
        common["evidence_fact_ids"] = [f.fact_id for f in bound_facts]
        common["observed_value_json"] = bound_facts[0].value_json
        common["blocked_reason_code"] = "schema_contract_violation"
        notes = common.get("notes", "")
        common["notes"] = (
            notes + "; bare_sentinel_without_fallback_companion"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    return None


# ===================================================================== #
# §6.3.3 trigger obligations
# ===================================================================== #
# trigger predicate 支持的运算符。
_TRIGGER_OPERATORS = {"==", "!=", "in", "not_in", "<", "<=", ">", ">="}


def _compare_trigger(observed: Any, op: str, expected: Any) -> Optional[bool]:
    """trigger predicate 比较（复用 threshold 比较器语义）。"""
    from .threshold_eval import compare

    return compare(observed, op, expected)


def _evaluate_measure_trigger(
    card: RuleCardDTO,
    trigger: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    common: Dict[str, Any],
    measure_aliases: Optional[Dict[str, str]] = None,
) -> Obligation:
    """measure 型触发谓词（spec §6.3.3 增补案 2026-07-08 定稿）。

    求值整体复用 §6.3.5 阈值机器（bind_measure 全 5 级 + 单位规则 + 比较器）：
    把触发项适配成 threshold 形状交 evaluate_threshold_comparison，再把
    closed+satisfied / closed+violated 翻译回 trigger true / false 语义。
    绑定档位保留全 5 级（sidecar 兜底档 4/5 是覆盖率测量键的唯一居所——
    实测 3 键 30/30 楼全在 sidecar_entry）；作为对价，bind_path 必落 notes
    供审计（codex 合议验收条件）。缺量记 missing_measurement 与 slot 侧
    missing_fact 分账。
    """
    from .threshold_eval import evaluate_threshold_comparison  # 局部导入避免环依赖

    op = trigger.get("operator")
    measure_key = trigger.get("measure_key")
    if op not in _TRIGGER_OPERATORS:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = f"trigger operator {op!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )
    if not measure_key:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = "trigger predicate_kind=measure but measure_key missing"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    common["measure_keys"] = [str(measure_key)]
    pseudo_threshold = {
        "operator": op,
        "measure_key": measure_key,
        "qualifiers": dict(trigger.get("qualifiers") or {}),
        "unit": trigger.get("unit"),
        "value": trigger.get("expected_value", trigger.get("value")),
    }
    closure_status, satisfaction, detail = evaluate_threshold_comparison(
        pseudo_threshold, fact_index, measure_aliases
    )

    for key in (
        "open_reason_code",
        "blocked_reason_code",
        "evidence_fact_ids",
        "observed_value_json",
        "expected_value_json",
        "threshold_value_json",
        "comparator_result",
        "unit",
    ):
        if key in detail:
            common[key] = detail[key]
    note_bits = [b for b in (detail.get("notes"),) if b]
    if detail.get("bind_path"):
        note_bits.append(f"bind_path={detail['bind_path']}")
    if note_bits:
        common["notes"] = "; ".join(note_bits)

    if closure_status in ("open", "blocked"):
        return _new_obligation(
            card, fact_pack_meta, "trigger", closure_status, "unknown", **common
        )
    # closed：threshold 的 satisfied/violated → trigger true/false（spec §6.3.3 既有语义）。
    if satisfaction == "satisfied":
        return _new_obligation(
            card, fact_pack_meta, "trigger", "closed", "satisfied", **common
        )
    return _new_obligation(
        card, fact_pack_meta, "trigger", "closed", "not_applicable", **common
    )


def evaluate_trigger(
    card: RuleCardDTO,
    trigger: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    *,
    measure_aliases: Optional[Dict[str, str]] = None,
    scope_component_types: Optional[set] = None,
    known_component_types: Optional[set] = None,
    scope_location_classes: Optional[set] = None,
    known_location_classes: Optional[set] = None,
    auth_target: Optional[str] = None,
    w0_identity: Optional[str] = None,
    lattice_disjoint: Optional[set] = None,
    ct_disjoint_na_relaxed: bool = False,
    trigger_na_authorizations: Optional[Dict[tuple, Dict[str, Any]]] = None,
    w0_raw_type: Optional[str] = None,
) -> Obligation:
    """评估一个 trigger condition item（spec §6.3.3）。

    trigger 是 trigger_conditions.items[] 的一项 dict，含 condition_id /
    predicate_kind / slot_ref_id / operator / expected_value / qualifiers 等。
    spec §6.3.3 + §5.4.3：trigger 通过 slot_ref_id 引用 slot_role_map[]，由
    slot_role_map[] 提供 slot_id 和默认 qualifiers；slot_role_map[] 是
    "slot reference → 具体 slot_id" 的解析表。
    predicate_kind=measure 走 _evaluate_measure_trigger（§6.3.3 增补案）。

    scope_component_types（DEBT-050 修案·spec 增补 2026-07-08）：本求值作用域
    相容的 canonical 组件身份集（fragment 作用域=该部位组件类型、楼级=楼内组件
    类集，均含类目成员展开，由 validator 预计算）。None = 判定关闭（旧行为，
    含作用域身份未知的保守回落）。known_component_types：已知 canonical 组件
    身份宇宙（词表值+类目键）——T 不在其中（卡端脏值/未规范化）不得推断 NA
    （codex 裁决护栏），回落 missing_fact。
    scope_location_classes / known_location_classes（DEBT-050 location 维度扩展
    ②，2026-07-08）：位置维度同构护栏——required location_class_key 与作用域
    location 不相容（location 无类目层级，直接值判）→ 同判 NA；component 或
    location 任一结构不可满足即 NA（析取）。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    predicate_kind = trigger.get("predicate_kind")
    op = trigger.get("operator")

    # spec §6.3.3：trigger 通过 slot_ref_id 引用 slot_role_map[]。
    slot_ref_id = trigger.get("slot_ref_id")
    slot_id: Optional[str] = None
    map_qualifiers: Dict[str, Any] = {}
    if slot_ref_id:
        for sr in (card.slot_role_map or []):
            if isinstance(sr, dict) and sr.get("slot_ref_id") == slot_ref_id:
                slot_id = sr.get("slot_id")
                map_qualifiers = dict(sr.get("qualifiers") or {})
                break
    # 兼容直接给 slot_id 的旧字段（contract 兜底）。
    if not slot_id:
        slot_id = trigger.get("slot_id")
    qualifiers: Dict[str, Any] = dict(trigger.get("qualifiers") or map_qualifiers)

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        slot_ref_ids=[slot_ref_id] if slot_ref_id else [],
        slot_ids=[slot_id] if slot_id else [],
        operator=op if isinstance(op, str) else None,
    )

    # predicate_kind 支持 slot / measure（后者为 §6.3.3 2026-07-08 增补案）。
    if predicate_kind == "measure":
        return _evaluate_measure_trigger(
            card, trigger, fact_index, fact_pack_meta, common,
            measure_aliases=measure_aliases,
        )
    if predicate_kind != "slot":
        common["blocked_reason_code"] = "unsupported_predicate_kind"
        common["notes"] = f"predicate_kind={predicate_kind!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    # operator 不支持。
    if op not in _TRIGGER_OPERATORS:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = f"trigger operator {op!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    if not slot_id:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = "trigger predicate_kind=slot but slot_id missing"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    # 绑定 slot fact：统一候选绑定器（DEBT-083 第 4 步）。触发器路径今日口径＝
    # 限定符过滤后再过 §6.4.3 目标作用域分级（scoped_facts：楼级求值时 building
    # 载体聚合读数优先于 fragment 戳 sidecar 行）。qfiltered 保留给
    # qualifier_conflict 分账（DEBT-049 Phase 3 §3.2：用未经作用域选择的结果判，
    # 与 evaluate_slot_role 完全同构）。
    _sel = select_candidate_facts(
        fact_index, slot_id, qualifiers, scope_selection=True)
    candidates, qfiltered, bound, status = (
        _sel.candidates, _sel.qfiltered, _sel.bound, _sel.status)

    if status == "missing":
        # DEBT-050 修案（spec 增补·触发器限定符结构不可满足→NA，2026-07-08）：
        # required 限定的组件身份与本求值作用域不相容 → 该组合结构性不可满足，
        # 按闭世界空真判假（closed+not_applicable，下游不激活——本部位不是该类
        # 构件，"其上缺陷"是范畴性无此项而非漏记）。护栏：仅 bound=∅ 时触发
        # （绝不覆盖实际绑定）；身份相容时保持 missing_fact（供给缺口诚实为 open）。
        # 组件 或 位置任一结构不可满足即 NA（析取）。location 维度 DEBT-050 扩展
        # （2026-07-08 ②）：private-lane 排水卡不适用于 common-pipe-duct 排水
        # fragment——location 范畴不符=卡不适用该 fragment，同 component 空真。
        req_ct = qualifiers.get("component_type_key")
        req_lc = qualifiers.get("location_class_key")
        # DEBT-065 §3.2:触发器级同卡级判据——触发器组件限定须恒等于该卡授权目标叶型
        # (§3.2-④),与 fragment 单值身份显式登记排斥才 NA;楼级(身份 None)自然不早退
        # (组件维楼级结构 NA 废止)。缺省拒绝:未授权/身份未知/非恒等/未登记排斥 → 不 NA。
        ct_incompat = (
            auth_target is not None
            and isinstance(req_ct, str) and req_ct == auth_target
            and w0_identity is not None and w0_identity != auth_target
            and lattice_disjoint is not None
            and frozenset((auth_target, w0_identity)) in lattice_disjoint
        )
        # 「乙」放宽档（2026-08-01，**缺省关闭**——量测/决策门用；同日 codex 审核门
        # 裁决：实现作为缺省关闭的量测档有条件通过，**语义规则与默认开启均不通过**，
        # 未取得 276 种命中组合的逐项适用性裁定前不得默认开）：req_ct 本身与 fragment
        # 单值身份**显式登记 disjoint** 即 NA，不再要求 req_ct 恒等于该卡授权目标叶型。
        # 判据仍是「显式登记排斥才可证」——未登记/身份未知/同型一律保持原状，不猜
        # （v2.2 红线 1/4）。🔴 审核门收紧（codex 第 4 条）：**限定符键须恰好只有
        # component_type_key**——多轴命中（07-31 重放实测占 25.8%）在「组件轴是独立且
        # 充分的适用性前提」有规格授权之前一律保留 qualifier_conflict 原判。
        # ⚠️ 已知真实反例形状（审核门给出，勿放宽多轴/勿去掉登记要求）：附录五 §2.3
        # 环氧树脂卡的法规前提是「如使用環氧樹脂」不是片段主身份，wall_tiles 片段的
        # 混凝土底层裂缝会被主身份互斥错杀——该卡在重放中实际命中 106 次。
        ct_relaxed_hit = False
        if not ct_incompat and ct_disjoint_na_relaxed:
            ct_relaxed_hit = (
                isinstance(req_ct, str) and bool(req_ct)
                and set(qualifiers.keys()) == {"component_type_key"}
                and w0_identity is not None and w0_identity != req_ct
                and lattice_disjoint is not None
                and frozenset((req_ct, w0_identity)) in lattice_disjoint
            )
            ct_incompat = ct_incompat or ct_relaxed_hit
        lc_incompat = (
            scope_location_classes is not None
            and isinstance(req_lc, str) and req_lc
            and req_lc not in scope_location_classes
            and (known_location_classes is None or req_lc in known_location_classes)
        )
        if ct_incompat or lc_incompat:
            dim = "component_type_key=" + repr(req_ct) if ct_incompat else \
                "location_class_key=" + repr(req_lc)
            common["comparator_result"] = False
            common["notes"] = (
                f"structurally_unsatisfiable_qualifier: {dim} "
                "incompatible with evaluation scope"
                # 放宽档命中标记：让重放对账能把「乙」的翻转从严档 NA 里分账出来。
                + (" [relaxed_disjoint_na]" if ct_relaxed_hit else "")
            )
            return _new_obligation(
                card, fact_pack_meta, "trigger", "closed", "not_applicable",
                **common,
            )
        # ---- DEBT-081 触发器级结构 NA 正向授权（2026-08-02，决策门六字段键）----
        # 白名单本身即该精确组合的正向法律授权（276 组合逐卡对中文正文裁定 →
        # 反方复核 → 130 来源组合 → 172 行原生型授权），不依赖粗类关系表证互斥。
        # 键含 raw_component_type（防规范叶型过粗——fire_door 的叶身份就是
        # fire_safety_component，粗键会预先豁免未来的 fire_resisting_wall）；
        # 且触发器限定符形状须精确等于裁定时形状（qualifiers_shape_sha256）。
        # **缺省空 ⇒ 行为逐位不变**；位置在严档结构 NA 之后、qualifier_conflict
        # 归账之前（codex 接入点裁定）。
        if trigger_na_authorizations and w0_identity and w0_raw_type:
            _auth_key = (
                card.rule_card_id,
                str(trigger.get("condition_id") or ""),
                str(slot_ref_id or ""),
                str(req_ct or ""),
                w0_identity,
                w0_raw_type,
            )
            _auth = trigger_na_authorizations.get(_auth_key)
            if _auth is not None:
                from .applicability_v3 import canonical_hash as _c14n
                if _auth.get("qualifiers_shape_sha256") == _c14n(qualifiers):
                    common["comparator_result"] = False
                    common["notes"] = (
                        "authorized_structural_na: source_combo="
                        f"{_auth.get('source_combo_no')}"
                    )
                    return _new_obligation(
                        card, fact_pack_meta, "trigger", "closed",
                        "not_applicable", **common,
                    )
                # 形状漂移：授权行失效、保持原路径（fail-visible 记 notes）。
                common["notes"] = (
                    common.get("notes", "")
                    + "; trigger_na_auth_shape_drift"
                ).strip("; ")
        # DEBT-049 Phase 3 U1 分账对齐（spec §3.2）：结构 NA 判定之后、missing_fact
        # 兜底之前，镜像 evaluate_slot_role 的 qualifier_conflict 分支——原始候选存在、
        # required qualifier 非空、但没有一条 fact 带 required qualifier（=槽有事实但限定符
        # 对不上）→ blocked/qualifier_conflict（非事实缺失 open）。用未经 scoped_facts 的原始
        # candidates 判（与 slot-role:667-675 完全同构，与作用域无关）。只在直接 trigger cohort
        # 重归账 open→blocked；allow_stop 恒 False→False（trigger 自身两态均非 satisfied）。
        if candidates and qualifiers and not qfiltered:
            common["blocked_reason_code"] = "qualifier_conflict"
            # 追加式注记：无前置注记时与旧串逐字节同；有（如授权形状漂移
            # `trigger_na_auth_shape_drift`）则保留在前——fail-visible 不被覆盖。
            common["notes"] = (
                common.get("notes", "") + "; "
                + f"required qualifiers {qualifiers!r} matched no trigger fact "
                  f"for slot_id={slot_id!r}"
            ).strip("; ")
            return _new_obligation(
                card, fact_pack_meta, "trigger", "blocked", "unknown", **common
            )
        common["open_reason_code"] = "missing_fact"
        common["notes"] = (
            common.get("notes", "") + "; "
            + f"trigger slot fact missing for slot_id={slot_id!r}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, "trigger", "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = f"conflicting trigger facts for slot_id={slot_id!r}"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    fact = bound[0]
    observed = parse_value(fact.value_json)
    common["observed_value_json"] = fact.value_json
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["evidence_node_refs"] = [f.source_node_id for f in bound if f.source_node_id]
    # rule_card v2 字段名为 expected_value；兼容旧字段 value。
    expected = trigger.get("expected_value", trigger.get("value"))
    common["expected_value_json"] = json.dumps(expected, ensure_ascii=False)

    # DEBT-083 甲：绑定事实组过哨兵分类器（缺省开关关闭 ⇒ 恒 None，逐位不变）。
    # 非判定哨兵 → closed + not_applicable（比较器形态，comparator_result=False）；
    # 裸哨兵 → blocked + schema_contract_violation。
    sentinel_obl = _sentinel_short_circuit(
        card, fact_pack_meta, "trigger", common, bound, fact_index
    )
    if sentinel_obl is not None:
        return sentinel_obl

    if observed is None:
        common["open_reason_code"] = "null_observed_value"
        common["notes"] = "trigger slot observed value is null"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "open", "unknown", **common
        )

    if op in {"in", "not_in"} and not isinstance(expected, (list, tuple, set)):
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = f"trigger operator {op!r} requires list value"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    result = _compare_trigger(observed, op, expected)
    if result is None:
        common["blocked_reason_code"] = "unsupported_operator"
        common["notes"] = "trigger comparison type-incompatible"
        return _new_obligation(
            card, fact_pack_meta, "trigger", "blocked", "unknown", **common
        )

    common["comparator_result"] = result

    # 🔴 许可闸接进触发器通道（2026-08-03，毛病一第二件）。
    #
    # 此前 `evaluate_trigger` **完全不调本闸**——`artifact_state_licenses_verdict` /
    # `_unauthorized_aggregate_guard` / `authorized_scope_selection` 三者一个都不出现。
    # 而 `"trigger"` 在 `ARTIFACT_STATE_LICENSED_KINDS` 里，理由是
    # 「产物状态当条件读是正当的」（`:215-217`）——**那条理由是对*原生*产物态布尔说的**。
    # 实测（批 I）触发器通道消费的产物态依据 **100% 是第三锚回退表折叠行**，
    # 锚①② 零命中；而回退表折叠行经 52/52 逐条对中文原文裁定，
    # **「产物须齐备」0 条** ⇒ 那条理由对它不成立。
    #
    # **两个分支都要拦**：依据不成立时，既不能说「本卡适用」也不能说「不适用」。
    # 说「不适用」看着保守，实则同样是**没有依据的结论**——
    # 它会让整个作用域的义务被静默跳过（批 I 全批 12,515 次跳过里
    # 9.8% 由可疑依据决定），审查员连「这条没查」都看不到。
    if not artifact_state_licenses_verdict("trigger", bound):
        return _artifact_state_refusal(
            card, fact_pack_meta, "trigger", common, bound
        )

    # spec §6.3.3：trigger evidence 存在且为 false → closed + not_applicable；
    #              trigger true → closed + satisfied（下游激活）。
    if result:
        return _new_obligation(
            card, fact_pack_meta, "trigger", "closed", "satisfied", **common
        )
    return _new_obligation(
        card, fact_pack_meta, "trigger", "closed", "not_applicable", **common
    )


def trigger_state(o: Obligation) -> Any:
    """单条 trigger obligation → 四态（spec §6.3.3 aggregate_trigger_logic 注释）。

    True   = closed + satisfied
    False  = closed + not_applicable 或 closed + violated
    "open"   = closure_status == open
    "blocked"= closure_status == blocked
    """
    if o.closure_status == "open":
        return "open"
    if o.closure_status == "blocked":
        return "blocked"
    # closed
    if o.satisfaction_status == "satisfied":
        return True
    return False


def aggregate_trigger_logic(
    logic: str, trigger_obligations: List[Obligation]
) -> Any:
    """card-level trigger 聚合（spec §6.3.3 aggregate_trigger_logic）。

    输出四态：True / False / "open" / "blocked"。
    """
    states = [trigger_state(o) for o in trigger_obligations]
    if any(s == "blocked" for s in states):
        return "blocked"
    if not states:
        return True
    if logic == "all":
        if any(s is False for s in states):
            return False
        if any(s == "open" for s in states):
            return "open"
        return True
    if logic == "any":
        if any(s is True for s in states):
            return True
        if any(s == "open" for s in states):
            return "open"
        return False
    return "blocked"


# ===================================================================== #
# §6.3.4 slot role obligations
# ===================================================================== #
# role → ObligationKind（spec §6.3.4 表）。
_SLOT_ROLE_TO_KIND = {
    "trigger": "trigger",
    "prerequisite": "prerequisite",
    "evidence": "evidence",
    "definition_reference": "definition",
}


def _component_type_ancestors(leaf_or_type: str, subsumption: Dict[str, Any]) -> set:
    """求某构件类型的**全部祖先**（多级，`subsumption` 是 父→子集合）。

    DEBT-076 契约措辞是「**后代 → 祖先**」而非「叶 → 父」，故须传递闭包。
    环已由类型格加载器拒绝，此处仍设访问集防御。
    """
    out: set = set()
    frontier = {leaf_or_type}
    seen = {leaf_or_type}
    while frontier:
        nxt = set()
        for parent, kids in (subsumption or {}).items():
            if parent in seen:
                continue
            if frontier & set(kids):
                out.add(parent)
                nxt.add(parent)
                seen.add(parent)
        frontier = nxt
    return out


def qualifiers_match(required: Dict[str, Any], observed: Dict[str, Any],
                     subsumption: Optional[Dict[str, Any]] = None) -> bool:
    """qualifier 子集匹配（spec §6.3.4）+ **构件类型的受控包含匹配**（DEBT-076）。

    基线：`required` 必须是 `observed` 的子集（逐键相等）。

    🔴 DEBT-076 裁定的唯一放宽 —— 仅对 `component_type_key` 一个键：

        卡侧要求 K 与世界事实 W 匹配 ⟺ W == K
                                    或 W 经**权威登记**的 `is_a` 关系单向推出 K

    四条限制（缺一不可，都是 codex 决策门明确的）：
    1. **只认显式登记**的关系（来自人裁 `component_type_relations_v1.json` →
       类型格 `subsumption`）——不得按名称相似、单复数或字符串前缀猜；
    2. **方向单向**：世界具体类型 → 卡侧上位类型。**反向不成立**——
       "某个外部构件"不能证明它一定是外墙；
    3. **缺省拒绝**：`subsumption` 未提供或关系未登记 → 不匹配（保持原严格行为）；
    4. 状态概念（`ubw` / `covered_component`）**不在类型轴上**，其关系在关系表里记为
       `crosses_axis`、**不进 `subsumption`**，故本函数自然不会用它们匹配。
    """
    for k, v in (required or {}).items():
        got = observed.get(k)
        if got == v:
            continue
        # 唯一放宽点：世界给的具体类型能否单向推出卡侧要求的上位类型
        if (k == "component_type_key" and subsumption and isinstance(got, str)
                and v in _component_type_ancestors(got, subsumption)):
            continue
        return False
    return True


def _filter_by_qualifiers(
    facts: List[FactAtom], required: Dict[str, Any],
    subsumption: Optional[Dict[str, Any]] = None,
) -> List[FactAtom]:
    """按 required qualifier 子集过滤 fact 列表。

    `subsumption`（父→子集合）为 None 时行为与改动前**逐字节等价**（严格相等匹配）；
    传入时对 `component_type_key` 启用「世界后代 → 卡侧祖先」单向包含匹配（DEBT-076）。
    """
    if not required:
        return list(facts)
    return [f for f in facts
            if qualifiers_match(required, f.qualifiers, subsumption)]


class FactBindingSelection(NamedTuple):
    """统一候选事实绑定器的返回（DEBT-083 第 4 步，决策门分叉二）。"""

    candidates: List[FactAtom]   # 槽名归一后的原始候选（qualifier_conflict 分账用）
    qfiltered: List[FactAtom]    # 限定符过滤后、作用域选择前
    bound: List[FactAtom]        # 作用域选择后（交 conflict_status 判定的集合）
    status: str                  # conflict_status(bound)
    audit: Dict[str, Any]        # 所选事实编号＋逐级排除理由（验收①审计要求）


def select_candidate_facts(
    fact_index: FactIndex,
    slot_id: str,
    qualifiers: Dict[str, Any],
    *,
    scope_selection: bool,
) -> FactBindingSelection:
    """统一候选事实绑定器——只统一"选事实"，各求值器的判定逻辑不动。

    固定顺序（决策门分叉二裁定，**先过滤后分级**——反序会让错 key 的高层行
    挤掉正确低层身份行）：
      ①槽名归一（`canonical_slot`）
      ②剔解释性事实（在 FactIndex 索引层完成，见 `exclude_explanatory`，
        DEBT-083 第 3 步）
      ③限定符过滤（§6.3.4 子集匹配＋DEBT-076 受控包含）
      ④授权作用域选择（§6.4.3 `scoped_facts`；`scope_selection=False` 时跳过
        ——槽位角色路径今日口径，逐槽授权启用属第 5 步，未经授权不得开）
      ⑤同身份值冲突判定（`conflict_status`）

    audit 记录所选事实编号与逐级排除数量，供第 5 步接入义务审计面；
    第 4 步不改变任何义务字段（两路径按各自今日口径接入，逐位等价）。
    """
    candidates = fact_index.slot_index.get(
        fact_index.canonical_slot(slot_id), []
    )
    qfiltered = _filter_by_qualifiers(
        candidates, qualifiers, fact_index.component_subsumption)
    bound = fact_index.scoped_facts(qfiltered) if scope_selection else list(qfiltered)
    status = conflict_status(bound, fact_index.numeric_tolerance)
    return FactBindingSelection(
        candidates=candidates,
        qfiltered=qfiltered,
        bound=bound,
        status=status,
        audit={
            "selected_fact_ids": [f.fact_id for f in bound],
            "excluded_by_qualifiers": len(candidates) - len(qfiltered),
            "excluded_by_scope": len(qfiltered) - len(bound),
            "scope_selection": scope_selection,
        },
    )


# DEBT-083 第 5 步逐槽授权登记（决策门分叉一：spec §6.4.3 分级是**逐槽授权**
# 不是通用规则；粒度规格二审 2026-08-02 通过后冻结）。数字权威＝逐槽授权矩阵
# `DEBT083_逐槽授权矩阵草案_20260801.md`（authorized 仅 2 槽/335 条）＋
# 已审规格 `spec草案_流程槽粒度语义_20260708.md`（started=任一真/completed=全真，
# 含完整性边界）。**扩这张表必须先过决策门拿到逐槽授权**，不许按名称形状推广。
SCOPE_SELECTION_AUTHORIZED_SLOTS = frozenset({
    "procedure.repair.prescribed.started",       # 任一真（矩阵 308 条）
    "procedure.inspection.prescribed.completed",  # 全真（矩阵 27 条）
})

# A′裁决（2026-08-02 决策门）：绑定级值消费授权。登记数据在独立模块
# `value_consumption_registry`（派生器受"无族名字面量"闸约束，数据与逻辑分居；
# 语义与扩表规矩见该模块 docstring）。
from .value_consumption_registry import (  # noqa: E402
    VALUE_CONSUMPTION_AUTHORIZED_BINDINGS,
)
# S1 权威结构表派生视图（逐行批准 2026-08-02）：三重交集门与节点路径合同
# 解释器共用同一份表——别在任何路径旁建第二份集合。
from .pending_adjudication_registry import (  # noqa: E402
    PENDING_ADJUDICATION_BINDINGS,
)
from .binding_contract_registry import (  # noqa: E402
    COARSE_SLOTS as BINDING_COARSE_SLOTS,
    DIAGNOSTIC_ONLY_BINDINGS as DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS,
    NODE_SLOT_BINDINGS as NODE_SLOT_AUTHORIZED_BINDINGS,
    REJECTED_BINDINGS as REJECTED_AUTHORIZED_BINDINGS,
    SCOPE_PRECISE_BINDINGS as SCOPE_PRECISE_AUTHORIZED,
    SLOT_ROLE_BINDINGS as SLOT_ROLE_AUTHORIZED_BINDINGS,
)


def _rejected_binding_refusal(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    binding_key: Tuple[str, str],
    *,
    enabled: bool,
) -> Optional[Obligation]:
    """失效绑定的运行态拒绝（S1 实施审二轮欠项②）。

    卡指纹失配/许可集合漂移/全表模式违例 ⇒ 该绑定不是"消失后回退通用求值"
    ——回退会让本被合同锁死的绑定滑回存在即满足/真伪即判（审核门探针实测
    closed/satisfied）。命中拒绝视图即 blocked/schema_contract_violation。
    """
    if not (enabled and binding_key in REJECTED_AUTHORIZED_BINDINGS):
        return None
    common["blocked_reason_code"] = "schema_contract_violation"
    common["notes"] = (
        str(common.get("notes", "")) + "; 授权绑定已失效（卡指纹/许可集合/表"
        "模式漂移），按否定授权条款拒绝判定，须重新过决策门"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "blocked", "unknown", **common
    )


def evaluate_slot_role(
    card: RuleCardDTO,
    slot_ref: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    authorized_scope_selection: bool = False,
    is_consistency_mirror: bool = False,
) -> Obligation:
    """评估一个 required slot role ref（spec §6.3.4）。

    slot_ref 是 slot_role_map[] 的一项 dict，含 slot_ref_id / slot_id /
    role / qualifiers / required 等。每条义务带 slot_ref_id / slot_id /
    qualifiers_json。

    `authorized_scope_selection`（DEBT-083 第 5 步，**缺省 False 逐位等价**）：
    True 时仅对 `SCOPE_SELECTION_AUTHORIZED_SLOTS` 内的槽启用 §6.4.3 作用域
    选择（楼级聚合读数优先于部位 sidecar 行）；登记外的槽行为不变。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    # 🔴 键名漏改修复（2026-07-25）：卡包 slot_role_map 用的是**复数键 `roles`**
    # （769/769 条，单数 `role` 一条都没有）。原来读单数恒得 None，
    # `_SLOT_ROLE_TO_KIND.get(None, "evidence")` 于是把**所有**槽位角色一律归成
    # evidence、notes 全写 `unknown slot role=None`——全批实测 36,939 条中招
    # （占 evidence 义务 84.4%，其中 blocked 19,716 条 = 全批 blocked 的 42.1%）。
    # 同仓 blueprint_deriver.py:880-881 早就正确归一，主链这条是漏改。
    # 多角色条目（11 条）取首位：卡作者把主要角色写在前（trigger/prerequisite 在前、
    # evidence 在后），与 blueprint_deriver 同口径；次要角色语义暂不承载，另记债务。
    roles = slot_ref.get("roles") or []
    role = roles[0] if roles else None
    slot_id = slot_ref.get("slot_id")
    slot_ref_id = slot_ref.get("slot_ref_id")
    qualifiers: Dict[str, Any] = dict(slot_ref.get("qualifiers") or {})

    kind = _SLOT_ROLE_TO_KIND.get(role, "evidence")
    notes = "" if role in _SLOT_ROLE_TO_KIND else f"unknown slot role={role!r}"

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        slot_ref_ids=[slot_ref_id] if slot_ref_id else [],
        slot_ids=[slot_id] if slot_id else [],
        notes=notes,
    )

    # 下游受 trigger 聚合影响：False 跳过由 validator 主循环处理；这里只处理
    # open / blocked 继承（spec §6.3.3 下游标记表）。
    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    if not slot_id:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (notes + "; slot_id missing").strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # 统一候选绑定器（DEBT-083 第 4 步）。槽位角色路径缺省不做作用域选择
    # （scope_selection=False，bound==qfiltered 逐位等价）。
    # S1 逐行批准后（2026-08-02）启用门＝**粗门∩精确绑定∩允许路径**三重交集
    # （裁决原文；只按槽名会把未裁绑定一并放开）。三个集合全部从权威结构表
    # binding_contract_registry 派生——含逐行卡指纹护栏（卡变即行失效）。
    # 旧 SCOPE_SELECTION_AUTHORIZED_SLOTS 保留为聚合语义登记（agg 强验消费），
    # 不再单独构成启用判据。
    _binding_key = (card.rule_card_id, str(slot_ref_id or ""))
    # 失效绑定运行态拒绝——先于一切求值（不许回退通用路径）。
    _rej = _rejected_binding_refusal(
        card, fact_pack_meta, kind, common, _binding_key,
        enabled=authorized_scope_selection)
    if _rej is not None:
        return _rej
    _use_scope = (
        authorized_scope_selection
        and fact_index.canonical_slot(slot_id) in BINDING_COARSE_SLOTS
        and _binding_key in SLOT_ROLE_AUTHORIZED_BINDINGS
    )
    _sel = select_candidate_facts(
        fact_index, slot_id, qualifiers, scope_selection=_use_scope)
    candidates, qfiltered = _sel.candidates, _sel.qfiltered
    if _use_scope and _sel.audit["excluded_by_scope"] > 0:
        # 验收①审计要求：记所选事实编号与排除数量（决策门分叉五）。
        notes = (notes + "; authorized_scope_selection: selected="
                 + ",".join(_sel.audit["selected_fact_ids"])
                 + f" excluded_by_scope={_sel.audit['excluded_by_scope']}"
                 ).strip("; ")
        common["notes"] = notes
    # qualifiers 无法判定：候选有但 qualifier 既不全等也无交集 → qualifier_conflict。
    if candidates and qualifiers and not qfiltered:
        # 候选事实存在但 required qualifier 一个都不匹配。
        common["blocked_reason_code"] = "qualifier_conflict"
        common["notes"] = (
            notes + f"; required qualifiers {qualifiers!r} matched no fact"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    status = _sel.status   # scope_selection=False ⇒ 与 conflict_status(qfiltered) 逐位同
    if status == "missing":
        common["open_reason_code"] = "missing_fact"
        common["notes"] = (notes + f"; slot fact missing slot_id={slot_id!r}").strip(
            "; "
        )
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    # S3 甲′精确待裁层（裁决位置：候选缺失检查之后、含歧义封锁在内的一切
    # 出口之前——候选存在即转新码，150 条歧义与 152 条实判统一转轨）。
    _pend = _pending_adjudication_guard(
        card, fact_pack_meta, kind, common, _sel.bound,
        enabled=authorized_scope_selection, binding_key=_binding_key)
    if _pend is not None:
        return _pend
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = (notes + f"; conflicting facts slot_id={slot_id!r}").strip(
            "; "
        )
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # 以下统一消费 _sel.bound（作用域选择后的绑定集；scope_selection=False 时
    # bound 与 qfiltered 同一列表，逐位等价——开分级后若仍消费 qfiltered 会把
    # 被作用域排除的部位行当证据/取值，属绑定与证据不一致）。
    bound = _sel.bound

    # 诊断型强制终止（合同锁定出口，先于一切许可判断）＋A′共享解释器。
    _diag_obl = _diagnostic_contract_terminal(
        card, fact_pack_meta, kind, common, bound,
        use_scope=_use_scope, binding_key=_binding_key,
    )
    if _diag_obl is not None:
        return _diag_obl
    _aprime_obl = _value_consumption_contract(
        card, fact_pack_meta, kind, common, bound,
        use_scope=_use_scope, binding_key=_binding_key,
    )
    if _aprime_obl is not None:
        return _aprime_obl

    # DEBT-083 甲：绑定事实组过哨兵分类器（缺省开关关闭 ⇒ 恒 None，逐位不变）。
    sentinel_obl = _sentinel_short_circuit(
        card, fact_pack_meta, kind, common, bound, fact_index
    )
    if sentinel_obl is not None:
        return sentinel_obl

    # S3 甲′通用层：未登记绑定不得依赖楼级聚合读数产实判（存在即满足在即）。
    _agg_guard = _unauthorized_aggregate_guard(
        card, fact_pack_meta, kind, common, bound,
        enabled=authorized_scope_selection, binding_key=_binding_key,
        is_consistency_mirror=is_consistency_mirror)
    if _agg_guard is not None:
        return _agg_guard

    # consistent：closed，用全部 evidence refs。
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["evidence_node_refs"] = [
        f.source_node_id for f in bound if f.source_node_id
    ]
    common["observed_value_json"] = bound[0].value_json
    # 证据许可闸：本分支**连布尔值都不读**（有事实即 satisfied），拿产物齐备布尔当
    # 主证据时尤其不能成立——产物为 absent 也会被判 satisfied。
    if not artifact_state_licenses_verdict(kind, bound):
        return _artifact_state_refusal(
            card, fact_pack_meta, kind, common, bound
        )
    return _new_obligation(
        card, fact_pack_meta, kind, "closed", "satisfied", **common
    )


def _trigger_inheritance(
    trigger_active: Any, common: Dict[str, Any]
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """下游义务对 card-level trigger 聚合结果的继承（spec §6.3.3 下游标记表）。

    返回 None 表示正常评估（trigger True）；否则返回 (closure_status,
    satisfaction_status, 补充后的 common)。
    trigger False 不在此处理（由主循环 make_rule_not_applicable_by_trigger
    决定整张卡跳过）。
    """
    out = dict(common)
    if trigger_active == "open":
        out["depends_on_open_trigger"] = True
        out["open_reason_code"] = "depends_on_open_trigger"
        # trigger_dependency_ids 由调用方在 obligation 落库后补 trigger id；
        # 这里先放占位非空值满足 validator（trigger_dependency_ids 不得为空）。
        out.setdefault("trigger_dependency_ids", ["__card_trigger__"])
        out["trigger_state"] = "open"
        return ("open", "unknown", out)
    if trigger_active == "blocked":
        out["blocked_reason_code"] = "missing_rule_edge"
        out["trigger_state"] = "blocked"
        notes = out.get("notes", "")
        out["notes"] = (notes + "; trigger aggregate blocked").strip("; ")
        return ("blocked", "unknown", out)
    return None


# ===================================================================== #
# §6.3.5 threshold obligations
# ===================================================================== #
def evaluate_threshold(
    card: RuleCardDTO,
    threshold: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    measure_aliases: Optional[Dict[str, str]] = None,
) -> Obligation:
    """评估一个 threshold regime → kind=threshold obligation（spec §6.3.5）。"""
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    measure_key = threshold.get("measure_key")
    time_anchor_key = threshold.get("time_anchor_key")

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        measure_keys=[measure_key] if measure_key else [],
        time_anchor_keys=[time_anchor_key] if time_anchor_key else [],
        operator=threshold.get("operator")
        if isinstance(threshold.get("operator"), str)
        else None,
    )

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(
            card, fact_pack_meta, "threshold", *inherit[:2], **inherit[2]
        )

    closure_status, satisfaction, detail = evaluate_threshold_comparison(
        threshold, fact_index, measure_aliases
    )
    common.update(_detail_to_fields(detail))
    return _new_obligation(
        card, fact_pack_meta, "threshold", closure_status, satisfaction, **common
    )


def _detail_to_fields(detail: Dict[str, Any]) -> Dict[str, Any]:
    """把 threshold_eval 的 detail dict 映射进 Obligation 字段。"""
    out: Dict[str, Any] = {}
    for key in (
        "open_reason_code",
        "blocked_reason_code",
        "observed_value_json",
        "expected_value_json",
        "threshold_value_json",
        "comparator_result",
        "evidence_fact_ids",
        "unit",
        "operator",
    ):
        if key in detail and detail[key] is not None:
            out[key] = detail[key]
    if "notes" in detail and detail["notes"]:
        bind = detail.get("bind_path", "")
        out["notes"] = (
            f"{detail['notes']} (bind={bind})" if bind else detail["notes"]
        )
    elif detail.get("bind_path"):
        out["notes"] = f"bind={detail['bind_path']}"
    return out


# ===================================================================== #
# §6.3.6 artifact / evidence obligations
# ===================================================================== #
def _bind_artifact_fact(
    artifact_key: str, fact_index: FactIndex
) -> Tuple[str, List[FactAtom]]:
    """绑定 artifact_key 到 sidecar artifact slot fact。

    返回 (status, facts)，status ∈ missing / consistent / ambiguous。
    禁止 prefix fallback：只查精确 slot。
    """
    slot = ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]
    candidates = fact_index.artifact_index.get(slot, [])
    if not candidates:
        candidates = [
            f
            for f in fact_index.slot_index.get(slot, [])
            if f.carrier_type in ("sidecar_entry", "building")
        ]
    # §6.4.3 目标作用域分级：楼级求值时 building 载体聚合行（rank 3）压过
    # fragment 戳 sidecar 行（rank 4），文档类槽的跨部位聚合读数不再混绑。
    candidates = fact_index.scoped_facts(candidates)
    return conflict_status(candidates, fact_index.numeric_tolerance), candidates


def evaluate_artifact_obligation(
    card: RuleCardDTO,
    artifact_key: str,
    kind: str,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    artifact_id: Optional[str] = None,
    bucket: Optional[str] = None,
) -> Obligation:
    """单个 artifact_key → artifact / evidence obligation（spec §6.3.6）。

    kind 由调用方按 bucket 语义传入（for_matching→evidence 等）。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        artifact_keys=[artifact_key],
        artifact_ids=[artifact_id] if artifact_id else [],
    )
    if bucket:
        common["notes"] = f"bucket={bucket}"

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    # 解析 artifact slot。
    try:
        slot = resolve_artifact_slot(artifact_key)
    except SchemaContractError:
        # rule_card 出现 spec 未登记的新 key → blocked + missing_artifact_mapping。
        common["blocked_reason_code"] = "missing_artifact_mapping"
        common["notes"] = (
            (common.get("notes", "") + f"; unknown artifact_key {artifact_key!r}")
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # key ∈ NOT_MODELED → blocked + artifact_not_modeled_upstream。
    if slot is None:
        common["blocked_reason_code"] = "artifact_not_modeled_upstream"
        common["notes"] = (
            common.get("notes", "")
            + f"; artifact_key {artifact_key!r} not modeled in sidecar"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    common["slot_ids"] = [slot]
    status, facts = _bind_artifact_fact(artifact_key, fact_index)

    if status == "missing":
        common["open_reason_code"] = "missing_artifact_evidence"
        common["notes"] = (
            common.get("notes", "") + f"; artifact fact missing slot={slot}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = (
            common.get("notes", "") + f"; conflicting artifact facts slot={slot}"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )

    # consistent：canonical truthy / falsy。
    common["evidence_fact_ids"] = [f.fact_id for f in facts]
    common["evidence_node_refs"] = [
        f.source_node_id for f in facts if f.source_node_id
    ]
    observed = parse_value(facts[0].value_json)
    common["observed_value_json"] = facts[0].value_json
    truthy = _canon_truthy(observed)
    # ==================================================================== #
    # B 批桶通道收窄（2026-08-03 决策门，grok+kimi 六问全收敛）。
    #
    # 挂钩点＝**求值时、绑定成功后、许可闸之前**（「不产出义务」≠「产出但拒判」，
    # 后者才对齐丁；且求值时挂钩保证义务条数守恒）。
    # 🔴 只认桶通道：本函数全仓 5 个调用面（含蓝图双读径），`_extract_artifact_key`
    # 同时服务证据通道——不加 bucket 门控会超收窄。蓝图路径也调本函数 ⇒ 同门控。
    # ==================================================================== #
    # 🔴 门控扩至 for_submission（2026-08-04 晨，grok+qwen 两家商议后自决）：
    # 残余误评复测钉出 ~22 条走 `bucket=for_submission`（同一求值器、同样的
    # 无依据 violated——「修订建议不存在 ⇒ 判未按需修订」诬告），而 B 批门当时
    # 只议了防误伤 for_matching（证据匹配通道，继续排除）。两家同意扩 for_submission。
    # for_completion 门已按立案条款开启（2026-08-04 晚）：开门要件＝核 227 对
    # 裁定池覆盖，实测（`量测_forcompletion门开门要件_20260804.md`）按实判条数
    # 覆盖 98.99%（5,099/5,151）⇒ 属既裁语义（「产物须齐备」零条成立）的机械
    # 延伸，非新裁定。方向＝无依据实判→诚实拒判（止血保守向，无揭膜风险）。
    # 同卡实证：s3_3_2_a_c.c01×record.inspection_log 在 workflow 通道 206 条
    # 被收窄、在 for_completion 通道 206 条照出 163 satisfied/43 violated——
    # 门开前这是同一判据在两通道的双重标准。
    # 残余：34 对在池未落表（6 可直接补行／8 对证据槽是状态布尔、现表键形状
    # 建不出行属载体设计问题／20 存疑维持）＋135 对未裁（仅 1 对产 52 条判定）
    # ——台账有账。
    if bucket in ("workflow_operands.artifacts", "for_submission",
                  "for_completion"):
        from .bucket_binding_registry import (
            BUCKET_BINDINGS, REJECTED_BUCKET_BINDINGS, BUCKET_DECLARED_EXIT,
        )
        _bkey = (card.rule_card_id, artifact_key)
        if _bkey in REJECTED_BUCKET_BINDINGS:
            # 🔴 kimi 的最强风险：失效行**绝不**回退通用求值——那等于卡指纹一漂移
            # 假判定就静默复活（A 批多数行有回退表兜底，桶通道绑真 artifact.* 槽
            # 且 kind=artifact 默认被许可，**没有任何兜底**）。
            common["blocked_reason_code"] = "schema_contract_violation"
            common["notes"] = (
                str(common.get("notes", "")) + "; 桶通道绑定行已失效（卡指纹漂移或"
                "模式违例），拒绝回退通用求值"
            ).strip("; ")
            return _new_obligation(
                card, fact_pack_meta, kind, "blocked", "unknown", **common
            )
        if _bkey in BUCKET_BINDINGS:
            # c55 桶通道值消费（2026-08-04 工单 #20 第二步）：授权对（裁定
            # kind=artifact 判乙/甲日数 且已在桶表内的 4 对）改按呈交/送达轴
            # 楼级布尔消费——裁定「呈交为真蕴含产物在」。作用域收在本分支内部
            # ⇒ 结构上只动「现拒判」人群；轴事实缺席时落回下方拒判老路
            # （旧池无轴槽 ⇒ 本钩零扰动）。
            # 🔴 缺省关（方案甲，2026-08-04 决策门三线一致）：桶钩生效会揭膜
            # node 通道的存在轴 violated（合并保守序下从前被拒判压住），须等
            # 第三族案裁完再开。开关走批配置进锚（Q3 裁定，DEBT-083 先例），
            # 搭载在 FactIndex 上（mask_lookup_targets 同款载体）。
            _c55_on = bool(getattr(fact_index, "c55_bucket_value_consumption",
                                   False))
            from .bucket_binding_registry import (
                C55_BUCKET_VALUE_CONSUMPTION, C55_BUCKET_VC_REJECTED,
            )
            if _c55_on and _bkey in C55_BUCKET_VC_REJECTED:
                common["blocked_reason_code"] = "schema_contract_violation"
                common["notes"] = (
                    str(common.get("notes", "")) + "; c55 桶消费授权在案但值消费"
                    "行失效/缺失——拒绝判定，不许把「授权失效」伪装成「从未授权」"
                ).strip("; ")
                return _new_obligation(
                    card, fact_pack_meta, kind, "blocked", "unknown", **common
                )
            _vc_row = (C55_BUCKET_VALUE_CONSUMPTION.get(_bkey)
                       if _c55_on else None)
            if _vc_row is not None:
                _axis_ob = _bucket_axis_value_consumption(
                    card, fact_pack_meta, kind, common, _vc_row, fact_index
                )
                if _axis_ob is not None:
                    return _axis_ob
            # 丁⑤：声明出口必须等于终止器实际出口（由产物态事实分类器定），
            # 不一致 fail-closed——表文只作声明，绝不成为可执行语义。
            _actual = f"open/{diagnostic_refusal_reason_code(facts)}"
            if _actual != BUCKET_DECLARED_EXIT:
                common["blocked_reason_code"] = "schema_contract_violation"
                common["notes"] = (
                    str(common.get("notes", "")) + "; 桶通道声明出口与实际出口"
                    f"不一致（声明={BUCKET_DECLARED_EXIT!r}, 实际={_actual!r}）"
                ).strip("; ")
                return _new_obligation(
                    card, fact_pack_meta, kind, "blocked", "unknown", **common
                )
            common["notes"] = (
                str(common.get("notes", "")) + "; bucket_binding_contract"
            ).strip("; ")
            return _artifact_state_refusal(card, fact_pack_meta, kind, common, facts)
    # 证据许可闸：本函数读的就是产物齐备布尔，故 kind 非许可侧（如 for_matching
    # 默认的 evidence）一律拒判。kind="artifact" 走原路，逐字节不变。
    if truthy is not None and not artifact_state_licenses_verdict(kind, facts):
        return _artifact_state_refusal(card, fact_pack_meta, kind, common, facts)
    if truthy is True:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "satisfied", **common
        )
    if truthy is False:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "violated", **common
        )
    # 值非 truthy/falsy 词表 —— 视为 null_observed（无法判定 presence）。
    common["open_reason_code"] = "null_observed_value"
    common["notes"] = (
        common.get("notes", "") + f"; artifact value {observed!r} not truthy/falsy"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _extract_artifact_key(item: Any) -> Optional[str]:
    """从 workflow_operands.artifacts[] 或 evidence requirement 的 artifact 引用
    抽 artifact_key。item 可为 str 或 dict。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("artifact_key") or item.get("artifact_id") or None
    return None


def derive_workflow_artifact_obligations(
    card: RuleCardDTO,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """workflow_operands.artifacts → artifact obligations（spec §6.3.6）。

    `source_sink`（identity-v5 §1.2 纯旁路来源登记，默认 None = 现网 live 路径零副作用）：非 None
    时每 append 一条义务即同序 append 一个 `SourceToken`（role="artifact"，channel="workflow_artifact"，
    primary_id=`artifact_id or artifact_key`——与阶段一 blueprint SID `enc("workflow_artifact",
    artifact_id or artifact_key)` 同键）。登记**不改**返回义务字节、**不进**判定分支。
    """
    out: List[Obligation] = []
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    artifacts = (card.workflow_operands or {}).get("artifacts", []) or []
    for item in sorted(artifacts, key=lambda x: _stable_key(x)):
        key = _extract_artifact_key(item)
        if not key:
            continue
        artifact_id = item.get("artifact_id") if isinstance(item, dict) else None
        out.append(
            evaluate_artifact_obligation(
                card,
                key,
                "artifact",
                fact_index,
                trigger_active,
                fact_pack_meta,
                artifact_id=artifact_id,
                bucket="workflow_operands.artifacts",
            )
        )
        if source_sink is not None:
            artifact_key = item.get("artifact_key") if isinstance(item, dict) else None
            source_sink.append(
                SourceToken(
                    "workflow_artifact",
                    str(artifact_id or artifact_key or ""),
                    "artifact",
                    scope_fid,
                )
            )
    return out


def derive_workflow_deadline_obligations(
    card: RuleCardDTO,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """workflow_operands.deadlines → deadline obligations（spec §6.3.7）。

    spec §6.3.7 明确「从 workflow_operands.deadlines 生成 deadline obligation」；
    §6.6 主入口伪代码遗漏了该独立循环（只在 obligation_graph node 的
    deadline_ids 派生 deadline），故此处与 artifact 对称补一个独立 deriver。
    见交付报告决策点 D-3。

    `source_sink`（identity-v5 §1.2 纯旁路来源登记，默认 None）：非 None 时每 append 一条义务即同序
    append 一个 `SourceToken`（role="deadline"，channel="workflow_deadline"，primary_id=deadline_id
    ——与阶段一 blueprint SID `_deadline_sid(deadline)` 同键）。登记不改返回义务字节、不进判定分支。
    """
    out: List[Obligation] = []
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    deadlines = (card.workflow_operands or {}).get("deadlines", []) or []
    for item in sorted(deadlines, key=lambda x: _stable_key(x)):
        if not isinstance(item, dict):
            continue
        out.append(
            evaluate_deadline(
                card, dict(item), fact_index, trigger_active, fact_pack_meta
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken(
                    "workflow_deadline",
                    str(item.get("deadline_id") or ""),
                    "deadline",
                    scope_fid,
                )
            )
    return out


# bucket → kind（spec §6.3.6 表）。for_submission / for_completion 默认 artifact，
# 但若 requirement 显式标 evidence_kind=evidence 则用 evidence。
_BUCKET_DEFAULT_KIND = {
    "for_matching": "evidence",
    "for_submission": "artifact",
    "for_completion": "artifact",
}


def evaluate_evidence_requirement(
    card: RuleCardDTO,
    bucket_name: str,
    req: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    authorized_scope_selection: bool = False,
) -> Obligation:
    """评估一个 evidence requirement（spec §6.3.6，三 bucket 都必须消费）。

    req 含 evidence_requirement_id / artifact_ids / artifact_keys / slot_ids /
    required_field_groups / evidence_kind 等。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    default_kind = _BUCKET_DEFAULT_KIND.get(bucket_name, "evidence")
    kind = req.get("evidence_kind") or default_kind
    if kind not in {"artifact", "evidence"}:
        kind = default_kind

    req_id = req.get("evidence_requirement_id")
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        notes=f"bucket={bucket_name}",
    )
    if req_id:
        common["evidence_node_refs"] = [str(req_id)]

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(card, fact_pack_meta, kind, *inherit[:2], **inherit[2])

    # required_field_groups：缺失则 open + missing_required_field_group。
    field_groups = req.get("required_field_groups") or []
    if field_groups:
        missing_group = _check_required_field_groups(field_groups, fact_index)
        if missing_group is not None:
            common["open_reason_code"] = "missing_required_field_group"
            common["notes"] = (
                common["notes"] + f"; required field group {missing_group!r} missing"
            )
            return _new_obligation(
                card, fact_pack_meta, kind, "open", "unknown", **common
            )

    # ---- 三通道解引用（2026-07-08 诊断：第八例"登记了没接线"——本函数此前
    # ①不解 artifact_ids 卡内局部编号 ②读不存在的 req['slot_ids'] 且不走
    # slot_role_map 解引用（死链，DEBT-041 同族）③无 measure_keys 通道。
    # 修法均为 spec §6.3.6 既有引用语义的 code 侧兑现，不引入新判定语义。）----

    # 通道1：artifact 引用。artifact_keys 直取；artifact_ids 是卡内局部编号
    # （art01…），先过本卡 workflow_operands.artifacts 注册表解成 artifact_key，
    # 解不出再按字面兜底（兼容直接写键的卡）。
    local_artifact_registry: Dict[str, str] = {}
    for item in (card.workflow_operands or {}).get("artifacts", []) or []:
        if (
            isinstance(item, dict)
            and item.get("artifact_id")
            and item.get("artifact_key")
        ):
            local_artifact_registry[str(item["artifact_id"])] = str(
                item["artifact_key"]
            )

    artifact_keys: List[str] = []
    for ak in req.get("artifact_keys", []) or []:
        if ak:
            artifact_keys.append(str(ak))
    for aid in req.get("artifact_ids", []) or []:
        deref = (
            local_artifact_registry.get(str(aid)) if isinstance(aid, str) else None
        )
        k = deref or _extract_artifact_key(aid)
        if k:
            artifact_keys.append(k)

    if artifact_keys:
        # 取第一个 artifact_key 评估（多证物"取一"沿旧行为，是否合规格另核）。
        return evaluate_artifact_obligation(
            card,
            artifact_keys[0],
            kind,
            fact_index,
            trigger_active,
            fact_pack_meta,
            bucket=bucket_name,
        )

    # 通道2：slot 绑定。slot_ids 直取（契约兜底字段）；slot_ref_ids 是卡内引用，
    # 经 slot_role_map 解成 slot_id **并携带其 qualifiers**（v12 修正：此前丢限定符
    # 致有键派生行全撞判歧义——触发器路径带、证据路径漏，同款解引用补齐）。
    slot_ids = [str(s) for s in (req.get("slot_ids") or []) if s]
    slot_qualifiers: Dict[str, Dict[str, Any]] = {}
    srm_entries = {
        str(sr.get("slot_ref_id")): sr
        for sr in (card.slot_role_map or [])
        if isinstance(sr, dict) and sr.get("slot_ref_id")
    }
    for ref in req.get("slot_ref_ids", []) or []:
        sr = srm_entries.get(str(ref))
        if sr and sr.get("slot_id"):
            sid = str(sr["slot_id"])
            slot_ids.append(sid)
            q = sr.get("qualifiers")
            if isinstance(q, dict) and q:
                slot_qualifiers[sid] = q
    if slot_ids:
        return _evaluate_evidence_by_slot(
            card, kind, slot_ids, common, fact_index, fact_pack_meta,
            slot_qualifiers=slot_qualifiers,
            authorized_scope_selection=authorized_scope_selection,
        )

    # 通道3：measure 绑定（证据要求引测量记录：存在即证据在——测量是数值记录，
    # 不做真值性检查；缺量记 missing_measurement 与 artifact/slot 侧分账）。
    measure_keys = [str(m) for m in (req.get("measure_keys") or []) if m]
    if measure_keys:
        common["measure_keys"] = measure_keys
        bound: List[FactAtom] = []
        for mk in measure_keys:
            bound.extend(
                fact_index.measure_index.get(fact_index.canonical_measure(mk), [])
            )
        if not bound:
            common["open_reason_code"] = "missing_measurement"
            common["notes"] = common["notes"] + "; evidence measurement missing"
            return _new_obligation(
                card, fact_pack_meta, kind, "open", "unknown", **common
            )
        common["evidence_fact_ids"] = [f.fact_id for f in bound]
        common["observed_value_json"] = bound[0].value_json
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "satisfied", **common
        )

    # 三通道全空 —— evidence requirement 无可绑定引用（源卡内容缺口）。
    common["open_reason_code"] = "missing_artifact_evidence"
    common["notes"] = common["notes"] + "; evidence requirement has no bindable ref"
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _evaluate_evidence_by_slot(
    card: RuleCardDTO,
    kind: str,
    slot_ids: List[str],
    common: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    slot_qualifiers: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    authorized_scope_selection: bool = False,
) -> Obligation:
    """evidence requirement 按 slot_id 直接绑定评估（限定符过滤 + §6.4.3 作用域分级）。"""
    common = dict(common)
    common["slot_ids"] = slot_ids
    all_facts: List[FactAtom] = []
    for slot_id in slot_ids:
        candidates = fact_index.slot_index.get(
            fact_index.canonical_slot(slot_id), []
        )
        quals = (slot_qualifiers or {}).get(slot_id)
        if quals:
            candidates = _filter_by_qualifiers(candidates, quals, fact_index.component_subsumption)
        all_facts.extend(candidates)
    # §6.4.3 目标作用域分级（同触发器路径：楼级聚合读数优先）。
    all_facts = fact_index.scoped_facts(all_facts)
    status = conflict_status(all_facts, fact_index.numeric_tolerance)
    if status == "missing":
        common["open_reason_code"] = "missing_artifact_evidence"
        common["notes"] = common.get("notes", "") + "; evidence slot fact missing"
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = common.get("notes", "") + "; conflicting evidence facts"
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    # DEBT-083 甲：绑定事实组过哨兵分类器（缺省开关关闭 ⇒ 恒 None，逐位不变）。
    # 形态 B 的 36 条 `repair.outcome.safe_until_next_cycle` 证物（伴随 no_repair）
    # 在此自然落 NA；存量 true/false 布尔证物语义不动（非哨兵，走下方原路径）。
    sentinel_obl = _sentinel_short_circuit(
        card, fact_pack_meta, kind, common, all_facts, fact_index
    )
    if sentinel_obl is not None:
        return sentinel_obl

    common["evidence_fact_ids"] = [f.fact_id for f in all_facts]
    common["observed_value_json"] = all_facts[0].value_json
    observed = parse_value(all_facts[0].value_json)
    truthy = _canon_truthy(observed)
    # 通用判定边界（边界单首轮审核补：第三条实判通道）。本通道按 slot_id 直绑、
    # **无 slot_ref 身份** ⇒ 结构上不可能命中精确合同表 ⇒ 凡绑定集合含
    # `aggregation=building` 读数的实判一律转待裁（RC-0048 实测形状：楼级
    # slot_target_lookup 假值行在此被判 violated——正是"找不到有效精确合同
    # 仍产实判"的漏口）。日后若要授权本通道，合同表须先扩通道级身份。
    if (authorized_scope_selection
            and any((f.qualifiers or {}).get("aggregation") == "building"
                    for f in all_facts)):
        common.pop("blocked_reason_code", None)
        common["open_reason_code"] = "binding_requires_adjudication_authorization"
        common["notes"] = (
            str(common.get("notes", "")) + "; evidence_channel_aggregate_guard: "
            "证据要求通道无精确合同身份，含楼级聚合读数的实判转待裁"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    # 证据许可闸（evidence requirement 的 slot 通道）。
    if not artifact_state_licenses_verdict(kind, all_facts):
        return _artifact_state_refusal(
            card, fact_pack_meta, kind, common, all_facts
        )
    if truthy is False:
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "violated", **common
        )
    # truthy 或 非 presence 语义（普通 evidence 值）→ satisfied。
    return _new_obligation(
        card, fact_pack_meta, kind, "closed", "satisfied", **common
    )


def _check_required_field_groups(
    field_groups: List[Any], fact_index: FactIndex
) -> Optional[str]:
    """检查 required field group 是否在 sidecar qual.artifact_field_group 出现。

    返回第一个缺失的 field group 名；全部命中返回 None。
    """
    # qual.artifact_field_group slot 的事实，或任意 artifact entry 的
    # qualifiers.artifact_field_group。
    present: set = set()
    for f in fact_index.slot_index.get("qual.artifact_field_group", []):
        present.add(str(parse_value(f.value_json)))
    for facts in fact_index.artifact_index.values():
        for f in facts:
            g = f.qualifiers.get("artifact_field_group")
            if g is not None:
                present.add(str(g))
    for group in field_groups:
        if str(group) not in present:
            return str(group)
    return None


# ===================================================================== #
# §6.3.7 deadline obligations
# ===================================================================== #
_DEADLINE_RELATIONS = {"within", "before", "same_day_as"}

# 🔴 丙类禁供名单（期限锚供给案决议 §一.2，2026-08-05）。
#
# 这三个锚点**不得**由世界侧供给数值时长。名单落成模块级常量而不是文字纪律，是因为
# 「后来者顺手把 15 个锚点补齐」正是它要挡的事——文字纪律挡不住，测试才挡得住
# （`closure/tests/test_deadline_anchor_supply.py` B4 按锚点分组断言，
#  `workflow_engine/worldgen/tests/test_deadline_anchor_emission.py` 断世界侧不登记）。
#
# 逐条理由（中文守则原文见决议 §三丙类表；引文出自
# `agent_v1/regulations/markdown/MBIS_CoP_2023.md`）：
#
# - `appointment.representative.supervision.made`（§2.1.3(m)，30 条义务）
#   「於委任代表**前不少於7日**」——要的是「距未来事件还有多久」的**提前量**，
#   不是本通道能表达的「已歷时长」；且「不少於」＝ `>=`，而 `before` 分支写死
#   `observed <= offset_value`，方向相反（供了就会把提前 2 日判 satisfied、
#   提前 10 日判 violated）。
#   **本单禁供 ＋ 供路待「提前量」语义裁定**（决议把「永久」收窄为这一句）。
#
# - `investigation.detailed.commencement`（§2.1.3(n)／§4.2.1／§4.2.3，66 条）
#   原文只有纯先后次序（「須於進行詳細調查前…」／「未獲…認可前，不得進行」），
#   **根本没有数值时限**。补任何数值都是发明规范。**数值供给意义上永久禁供。**
#
# - `repair.prescribed.started`（§2.1.3(o)／(q)，63 条）
#   同上：「或進行訂明修葺前，以較早者為準」／「須於修葺工程開始前送交」——
#   纯先后次序，无数值。**数值供给意义上永久禁供。**
#
# ⚠️ 边界：禁的是**数值时长供给**。#14/#15 真正缺的是「先后次序谓词」布尔通道
# （`_DEADLINE_RELATIONS` 的 `before` 只有数值通道），那属规则扩展另案，
# 不因本名单而被否定。
FORBIDDEN_DEADLINE_ANCHOR_SUPPLY: frozenset = frozenset(
    {
        "appointment.representative.supervision.made",
        "investigation.detailed.commencement",
        "repair.prescribed.started",
    }
)

# 2026-07-27 移除 `_SIDECAR_DURATION_SLOTS`（原 spec §6.3.7 绑定来源优先级 1 的硬编码
# 4 槽清单）。两个理由：
#   ① 它被**无条件遍历**、不看本条 deadline 的 `time_anchor_key`，是锚点全塌缩的直接
#      病灶（详 `_bind_deadline_fact` docstring）；按锚点查之后这级与优先级 2 同体。
#   ② 它本身已过期——世界模型实际产出 6 个 sidecar duration 槽
#      （另有 `duration.delivery.deadline.to_person` / `.to_ba`），清单只列了 4 个。
#   保留它当"权威 duration 槽清单"会再次误导：真正的权威是事实侧 slot 命名 + 卡侧锚点。


def evaluate_deadline(
    card: RuleCardDTO,
    deadline: Dict[str, Any],
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 deadline → kind=deadline obligation（spec §6.3.7）。

    deadline 含 deadline_id / relation / offset_value / offset_unit /
    time_anchor_key。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    deadline_id = deadline.get("deadline_id")
    relation = deadline.get("relation")
    offset_value = deadline.get("offset_value")
    time_anchor_key = deadline.get("time_anchor_key")

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        deadline_ids=[deadline_id] if deadline_id else [],
        time_anchor_keys=[time_anchor_key] if time_anchor_key else [],
    )

    inherit = _trigger_inheritance(trigger_active, common)
    if inherit is not None:
        return _new_obligation(
            card, fact_pack_meta, "deadline", *inherit[:2], **inherit[2]
        )

    # 未知 relation。
    if relation not in _DEADLINE_RELATIONS:
        common["blocked_reason_code"] = "unsupported_deadline_relation"
        common["notes"] = f"deadline relation {relation!r} not supported"
        return _new_obligation(
            card, fact_pack_meta, "deadline", "blocked", "unknown", **common
        )

    # 绑定 duration / time anchor fact（spec §6.3.7 优先级 ＋ provenance 前置级）。
    fact, bind_status = _bind_deadline_fact(deadline, fact_index)
    if bind_status == "ambiguous":
        # 同（作用域,锚）候选多于一条：拒绝任取（决议 §三.2）。
        # `facts[0]` 是 2026-07-27 那条捏造 135 条期限判定的病灶形状——
        # 多候选时"任取"与"取对"在单候选测试下不可区分，故碰撞必须外显。
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = (
            f"multiple duration facts declare time_anchor_key="
            f"{time_anchor_key!r} in this scope; refusing to pick one"
        )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "blocked", "unknown", **common
        )
    if fact is None:
        common["open_reason_code"] = "missing_time_anchor"
        common["notes"] = (
            f"no duration/time-anchor fact bound for relation={relation!r}"
        )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "open", "unknown", **common
        )

    common["evidence_fact_ids"] = [fact.fact_id]
    observed = parse_value(fact.value_json)
    common["observed_value_json"] = fact.value_json
    if observed is None:
        common["open_reason_code"] = "null_observed_value"
        common["notes"] = "deadline observed value is null"
        return _new_obligation(
            card, fact_pack_meta, "deadline", "open", "unknown", **common
        )

    # within / before（precomputed duration fallback）：observed_duration <= offset。
    if relation in {"within", "before"}:
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            # before 需要 timestamp 但只有非数值且非 duration → missing_time_anchor。
            common["open_reason_code"] = "missing_time_anchor"
            common["notes"] = (
                f"relation={relation!r} needs duration/timestamp; "
                f"observed {observed!r} unusable"
            )
            return _new_obligation(
                card, fact_pack_meta, "deadline", "open", "unknown", **common
            )
        if offset_value is None:
            common["blocked_reason_code"] = "schema_contract_violation"
            common["notes"] = f"relation={relation!r} requires offset_value"
            return _new_obligation(
                card, fact_pack_meta, "deadline", "blocked", "unknown", **common
            )
        result = float(observed) <= float(offset_value)
        common["operator"] = "<="
        common["expected_value_json"] = json.dumps(offset_value)
        common["threshold_value_json"] = json.dumps(offset_value)
        common["comparator_result"] = result
        if result:
            return _new_obligation(
                card, fact_pack_meta, "deadline", "closed", "satisfied", **common
            )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "closed", "violated", **common
        )

    # same_day_as：已歷时长 == 0 日（R1，期限锚供给案决议 §一.1 / §四.1，2026-08-05）。
    #
    # 🔴 改前走 `_canon_truthy(observed)`，语义**恰好反转**：
    #     世界侧承载「同日送交」的是已歷日数，`_canon_truthy(0.0) is False`、
    #     `_canon_truthy(1.0) is True` ⇒ 同日送达（合规）判 violated、
    #     次日送达（违规）判 satisfied，`2.0` 这类还落 None → 该判而不判。
    #     改前没发作只因绑定先失败落 `missing_time_anchor`；**补供给即发作**，
    #     故本修必须先于世界侧供给落地。
    #     判据来源不是新发明：卡侧 §2.1.3(r) 两张 same_day 卡自己登记的就是
    #     `{"operator":"==","value":0,"unit":"day"}`——改前是判定侧读错了通道。
    #     ⚠️ §2.1.3(p)/(q) 两张卡 `threshold_regimes=[]`，其 `== 0` 来自
    #     **relation 结构常量**（「同日」的唯一数值读法就是差 0 日），
    #     故下面把该常量来源写进 notes，不静默硬编码。
    # 🔴 `_canon_truthy` 本体不动（另有 5 个跨 kind 消费点），只换本分支的通道。
    if isinstance(observed, (int, float)) and not isinstance(observed, bool):
        result = float(observed) == 0.0
        common["operator"] = "=="
        common["expected_value_json"] = json.dumps(0)
        common["threshold_value_json"] = json.dumps(0)
        common["comparator_result"] = result
        common["notes"] = (
            "same_day_as ⇒ elapsed duration == 0 day; "
            "threshold source = deadline relation structural constant "
            "(same_day_as 的唯一数值读法)"
        )
        if result:
            return _new_obligation(
                card, fact_pack_meta, "deadline", "closed", "satisfied", **common
            )
        return _new_obligation(
            card, fact_pack_meta, "deadline", "closed", "violated", **common
        )
    # 非数值的 same_day_as 输入（布尔门状态 / 日期字符串等）：不可比，诚实落 open。
    common["open_reason_code"] = "missing_time_anchor"
    common["notes"] = (
        f"same_day_as needs a numeric elapsed duration; observed {observed!r} unusable"
    )
    return _new_obligation(
        card, fact_pack_meta, "deadline", "open", "unknown", **common
    )


def _bind_deadline_fact(
    deadline: Dict[str, Any], fact_index: FactIndex
) -> Tuple[Optional[FactAtom], Optional[str]]:
    """deadline fact 绑定（spec §6.3.7 绑定来源优先级 1-4 ＋ provenance 前置级）。

    返回 `(fact, status)`：

    - `(<FactAtom>, None)` —— 唯一命中，可用；
    - `(None, None)` —— 一条都没有，诚实 miss（上游落 `missing_time_anchor`）；
    - `(None, "ambiguous")` —— 同（作用域,锚）候选多于一条，**拒绝任取**
      （上游落 `blocked / ambiguous_fact_binding`）。

    🔴 为什么返回二元组而不是 `Optional[FactAtom]`：把"没有"与"多于一条"压成同一个
    `None` 正是 2026-07-27 病灶的表达形状——调用方无从区分"世界没供"与"供了但歧义"，
    于是只能沿用 `facts[0]`。**碰撞必须外显**（决议 §三.2）。

    ## 级 0：provenance 锚点通道（优先于下面所有老通道）

    世界侧 sidecar duration 行把注册表登记的
    `rule_card_threshold.time_anchor_key` 回写进 `provenance.time_anchor_key`；
    这里读的是**生产者自己的登记**，不是猜 join（规则不完整时不许发明映射——
    2026-07-27 那条教训）。

    必须优先的实测理由（E1 实验 §四墙③，全批 30 栋）：锚名
    `repair.prescribed.{started,completed}` 是 `slot_aliases` 里仅有的两个与期限锚
    撞名的键，归一后指向世界侧**布尔闸槽** `procedure.repair.prescribed.*`。
    老通道第 1+2 级是 `if facts: return facts[0]`、**不看值类型**，故必然先命中布尔行，
    第 3 级量表通道永不可达 ⇒ #8 的 93 条 ＋ `repair.prescribed.started` 的 63 条
    ＝ 156 条（603 条期限义务的 25.9%）在不改本函数的前提下，**任何供给侧动作都救不回**。

    🔴 绑定必须由**本条 deadline 自己的 `time_anchor_key`** 决定，不许任取。

    2026-07-27 前的实现把优先级 1（sidecar numeric duration entries）写成
    **无条件遍历 `_SIDECAR_DURATION_SLOTS`、任一命中即 `return facts[0]`**——
    完全不看 `time_anchor_key`。后果实测（真实批 30 栋）：225 条 `kind=deadline`
    义务 **225/225 全部绑到同一条 `duration.notification.deadline`**，卡包 15 个
    不同时间锚点全部塌缩成同一条无关事实（且是 4 行 sidecar 里任取一行）。其中
    132 条 satisfied / 3 条 violated——等于拿**别的碎片的通知时长**去比 §2.1.3(o)
    「檢驗完成後 7 日內呈交」「完成修葺後 14 日內」这类法定期限，期限判定在结构上
    就是错的。

    第二处同批修：两级查找此前**未过别名归一**，而 `FactIndex.slot_index` /
    `measure_index` 都是**按 canonical key 建索引的**（`fact_binding.py:_build`），
    故卡侧 `repair.prescribed.{started,completed}`（别名 → 事实侧
    `procedure.repair.prescribed.*`）裸查恒 0 条。只修上面的早返回而不过归一，
    这几个锚点会立刻从「错绑」变成「真 miss」。
    """
    time_anchor_key = deadline.get("time_anchor_key")
    if time_anchor_key:
        anchor = str(time_anchor_key)
        # 0. provenance 锚点通道（见 docstring）。碰撞策略在此落地：
        #    0 条 → 落到下面的老通道；恰 1 条 → 用；>1 条 → 拒绝任取。
        #
        # 🔴 丙类禁供闸（决议 §一.2）：`FORBIDDEN_DEADLINE_ANCHOR_SUPPLY` 三锚
        #    **不经本通道取值**。世界侧今天一条都不产（`worldgen/tests/
        #    test_deadline_anchor_emission.py` 与 `test_deadline_anchor_supply.py` B4
        #    双向钉死），本闸是第二道：万一有人"顺手把 15 个锚点补齐"，
        #    #13 会立刻踩上 `before` 分支写死的 `observed <= offset_value`
        #    ——而 §2.1.3(m)「於委任代表前**不少於**7日」是 `>=`，方向相反，
        #    产出的是**反的确定判定**（提前 2 日判 satisfied、提前 10 日判 violated）。
        #    比较符方向（R2）本单不修，故这里让供给进不来，宁可 unknown。
        # ⚠️ 边界（诚实）：本闸只堵**本通道**，不堵下面的老 slot/measure 通道
        #    ——那两条是既有路径，堵它们会改动现存 159 条丙类义务的
        #    `evidence_fact_ids` 与 notes（#15 今天经别名桥绑着一条布尔门状态行），
        #    与本单"不注入锚点事实时全链零扰动"的病原回归判据冲突。
        anchored = (
            []
            if anchor in FORBIDDEN_DEADLINE_ANCHOR_SUPPLY
            else (fact_index.time_anchor_index.get(anchor) or [])
        )
        if len(anchored) == 1:
            return anchored[0], None
        if len(anchored) > 1:
            return None, "ambiguous"
        # 别名归一（spec §6.4.2 canonical_slot / canonical_measure）：两个索引都按
        # canonical key 建，裸 key 查找对任何命中别名表的锚点必 miss。
        anchor_slot = fact_index.canonical_slot(anchor)
        anchor_measure = fact_index.canonical_measure(anchor)
        # 1+2. sidecar 事实：按 canonical 锚点精确查。spec 把「numeric duration
        #      entries」与「time anchor entries」列为两级，但一旦按**本条锚点**查，
        #      两级的查找体完全相同（锚点命名的槽恰好是 duration 槽时即优先级 1），
        #      故合并为一次查找——分两级写只会得到逐字节相同的结果。
        facts = [
            f
            for f in fact_index.slot_index.get(anchor_slot, [])
            if f.carrier_type == "sidecar_entry"
        ]
        if facts:
            return facts[0], None
        # 3. RuleThreshold duration.* measure / 4. measurement slot|measure exact。
        m = fact_index.measure_index.get(anchor_measure)
        if m:
            return m[0], None
    # 4. 也试 deadline_id 当 measure / slot。
    # ⚠️ 未归一（2026-07-27 注）：这两处**裸查**，没过 `canonical_slot` /
    # `canonical_measure`。不修的理由——`deadline_id` 是卡内期限条目的**标识符**
    # （形如 `<rule_card_id>.deadline.N`），根本不是槽名/量表名命名空间里的东西，
    # 别名表里不可能有它的键，过不过归一逐字节同结果。这一段本身是摆设兜底：
    # 上面第 1-3 级按 `time_anchor_key` 归一后已覆盖真实锚点，走到这里只会返回
    # None。留着是 spec §6.3.6 的第 4 级形式完整性，不是活路径。
    deadline_id = deadline.get("deadline_id")
    if deadline_id:
        m = fact_index.measure_index.get(str(deadline_id))
        if m:
            return m[0], None
        s = fact_index.slot_index.get(str(deadline_id))
        if s:
            return s[0], None
    return None, None


# ===================================================================== #
# §6.3.8 exception obligations
# ===================================================================== #
def evaluate_exception(
    card: RuleCardDTO,
    exc: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 exception → kind=exception obligation（spec §6.3.8）。

    spec §6.3.8 baseline 默认：
    - exception 结构缺 required fields → blocked。
    - exception triggered 且有证据 → closed + not_applicable / closed + violated。
    - 语义无法由结构判断 → blocked + missing_rule_edge。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
    )

    exc_slot = exc.get("slot_id")
    exc_kind = exc.get("exception_kind")  # "exclusion" / "violation_condition"

    # 结构缺 required fields：既无 slot_id 也无可判定语义 → blocked。
    if not exc_slot:
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "exception missing slot_id / unresolvable by structure"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    common["slot_ids"] = [str(exc_slot)]
    facts = fact_index.slot_index.get(fact_index.canonical_slot(str(exc_slot)), [])
    qualifiers: Dict[str, Any] = dict(exc.get("qualifiers") or {})
    bound = _filter_by_qualifiers(facts, qualifiers, fact_index.component_subsumption)
    status = conflict_status(bound, fact_index.numeric_tolerance)

    if status == "missing":
        # exception 所需事实缺失 → open + missing_fact。
        common["open_reason_code"] = "missing_fact"
        common["notes"] = f"exception slot fact missing slot_id={exc_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "exception", "open", "unknown", **common
        )
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        common["notes"] = f"conflicting exception facts slot_id={exc_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["observed_value_json"] = bound[0].value_json
    triggered = _canon_truthy(parse_value(bound[0].value_json))
    if triggered is None:
        # 值无法判 triggered/未 triggered。
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "exception value not truthy/falsy; semantics unresolvable"
        return _new_obligation(
            card, fact_pack_meta, "exception", "blocked", "unknown", **common
        )

    if not triggered:
        # exception 未触发 —— 不排除义务、不违反；记 closed + satisfied。
        common["notes"] = "exception not triggered"
        return _new_obligation(
            card, fact_pack_meta, "exception", "closed", "satisfied", **common
        )

    # exception triggered。
    if exc_kind == "violation_condition":
        common["notes"] = "exception is a violation condition and is triggered"
        return _new_obligation(
            card, fact_pack_meta, "exception", "closed", "violated", **common
        )
    # 默认 / exclusion：排除义务。
    common["notes"] = "exception triggered; obligation excluded"
    return _new_obligation(
        card, fact_pack_meta, "exception", "closed", "not_applicable", **common
    )


# ===================================================================== #
# §6.3.9 definition obligations
# ===================================================================== #
def evaluate_definition(
    card: RuleCardDTO,
    definition: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """评估一个 definition → kind=definition obligation（spec §6.3.9）。

    - definition slot 有事实或 source quote → closed + satisfied
    - definition 引用缺失 → blocked + missing_rule_edge
    - definition 所需事实缺失 → open + missing_fact
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
    )

    # DEBT-057 修（2026-07-18，agy+Opus4.6 只读核证 + 主会话复核）：真卡 definition 对象的
    # 字段集是 definition_id / term_key / definition_text / scope_note / **source_quote_refs**
    # （list），此处原只读 `source_quote_id` / `quote_local_id` —— 二者在真卡上**都不存在**，
    # 致真语料唯一那张有 definitions 的卡恒落 blocked/missing_rule_edge（假阻断）。
    # 修法：真字段只接受 list/tuple 形状并保留**全部非空字符串引用**；再与旧单值键
    # （合成/历史卡兼容）做去重并集。非法标量 source_quote_refs 保守忽略，不能把字符串
    # 当 iterable 拆字符、也不能把任意标量冒充有效引用。半径 = 1 卡 1 义务。
    def_slot = definition.get("slot_id")
    _quote_refs = definition.get("source_quote_refs")
    if isinstance(_quote_refs, (list, tuple)):
        definition_quote_ids = [
            ref for ref in _quote_refs if isinstance(ref, str) and ref
        ]
    else:
        definition_quote_ids = []
    for legacy_key in ("source_quote_id", "quote_local_id"):
        legacy_ref = definition.get(legacy_key)
        if isinstance(legacy_ref, str) and legacy_ref:
            definition_quote_ids.append(legacy_ref)
    definition_quote_ids = sorted(set(definition_quote_ids))

    # definition 引用缺失：既无 slot 也无 quote。
    if not def_slot and not definition_quote_ids:
        common["blocked_reason_code"] = "missing_rule_edge"
        common["notes"] = "definition has neither slot_id nor source_quote reference"
        return _new_obligation(
            card, fact_pack_meta, "definition", "blocked", "unknown", **common
        )

    if definition_quote_ids:
        common["source_quote_ids"] = sorted(set(quote_ids + definition_quote_ids))

    if def_slot:
        common["slot_ids"] = [str(def_slot)]
        facts = fact_index.slot_index.get(
            fact_index.canonical_slot(str(def_slot)), []
        )
        if facts:
            common["evidence_fact_ids"] = [f.fact_id for f in facts]
            common["observed_value_json"] = facts[0].value_json
            common["notes"] = "definition slot has fact"
            return _new_obligation(
                card, fact_pack_meta, "definition", "closed", "satisfied", **common
            )
        if definition_quote_ids:
            # 无事实但有 source quote → closed + satisfied（术语可解释）。
            common["notes"] = "definition resolved by source quote"
            return _new_obligation(
                card, fact_pack_meta, "definition", "closed", "satisfied", **common
            )
        # definition 所需事实缺失。
        common["open_reason_code"] = "missing_fact"
        common["notes"] = f"definition slot fact missing slot_id={def_slot!r}"
        return _new_obligation(
            card, fact_pack_meta, "definition", "open", "unknown", **common
        )

    # 只有 source quote。
    common["notes"] = "definition resolved by source quote"
    return _new_obligation(
        card, fact_pack_meta, "definition", "closed", "satisfied", **common
    )


# ===================================================================== #
# §6.3.10 obligation_graph nodes + edges
# ===================================================================== #
def refine_action_kind(node_kind: str, action: str) -> str:
    """action → ObligationKind refinement（spec §6.3.10.2）。"""
    action = action or ""
    if action.startswith("submit") or action.startswith("deliver"):
        return "artifact"
    if "report" in action or action.startswith("include_"):
        return "report_field"
    if action.startswith("conduct_supervision") or "supervision" in action:
        return "supervision"
    if "method" in action or action in {
        "perform_detailed_investigation_method",
        "conduct_validation_test",
    }:
        return "method"
    return {
        "obligation": "action",
        "prohibition": "prohibition",
        "escalation": "escalation",
    }.get(node_kind, "action")


def _node_satisfaction_slot_refs(
    card: RuleCardDTO, node: ObligationNodeDTO
) -> List[Dict[str, Any]]:
    """返回能确定归属到 `node` 的必需主证据槽。

    `slot_role_map` 是卡级表，没有 node 外键。只有单节点卡才能确定归属；多节点卡、
    方法节点、非必需槽和次要 evidence 角色均缺省拒绝，不做语义猜测。
    """
    if refine_action_kind(node.node_kind, node.action) == "method":
        return []
    graph_nodes = (card.obligation_graph or {}).get("nodes", []) or []
    if len(graph_nodes) != 1:
        return []
    only = graph_nodes[0]
    only_id = (
        only.obligation_node_id
        if isinstance(only, ObligationNodeDTO)
        else only.get("obligation_node_id") if isinstance(only, dict) else None
    )
    if str(only_id or "") != str(node.obligation_node_id):
        return []
    selected: List[Dict[str, Any]] = []
    for ref in card.slot_role_map or []:
        if not isinstance(ref, dict) or ref.get("required") is not True:
            continue
        roles = ref.get("roles") or []
        if roles and roles[0] == "evidence":
            selected.append(ref)
    return sorted(selected, key=lambda r: str(r.get("slot_ref_id") or ""))


def _pending_adjudication_guard(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    bound: List[FactAtom],
    *,
    enabled: bool,
    binding_key: Tuple[str, str],
) -> Optional[Obligation]:
    """S3 甲′精确待裁层：7 条丁组绑定在逐绑定裁定前不得产生任何实判。

    位置＝候选缺失检查之后、一切实判出口（存在即满足/真伪即判/歧义封锁）之前
    ——**候选存在即转** `open + binding_requires_adjudication_authorization`
    （150 条歧义＋152 条实判统一转轨；连片段事实也拦，§6.1.3 专防）。
    """
    if not (enabled and binding_key in PENDING_ADJUDICATION_BINDINGS and bound):
        return None
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["observed_value_json"] = bound[0].value_json
    common.pop("blocked_reason_code", None)
    common["open_reason_code"] = "binding_requires_adjudication_authorization"
    common["notes"] = (
        str(common.get("notes", "")) + "; pending_adjudication_guard: 该绑定"
        "待丁组逐绑定裁定，读数已取得但程序不产判定"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _unauthorized_aggregate_guard(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    bound: List[FactAtom],
    *,
    enabled: bool,
    binding_key: Tuple[str, str],
    is_consistency_mirror: bool = False,
) -> Optional[Obligation]:
    """S3 甲′通用层：未登记绑定不得依赖 `aggregation=building` 读数产实判。

    一致绑定将进入实判出口（存在即满足/真伪即判）且首行带楼级聚合标记、而
    该绑定不在精确合同表内 ⇒ 转 `open + binding_requires_adjudication_
    authorization`。已登记绑定（诊断/A′）在更早的合同出口处置，到不了这里。
    """
    if not enabled or not bound:
        return None
    # 🔴 射程沿革（二轮审核门纠正）：首版按 `kind == "trigger"` **整类**排除，
    # 理由写的是"trigger 转 open 会扰动 allow_stop"——**该理由被驳回且驳得对**：
    # 会扰动 allow_stop 恰恰证明它**有判定后果**，不构成豁免理由。
    # 正确边界是**只排除显式标记的一致性镜像副本**：镜像不是独立法规判断，
    # 它复用真触发器的求值结果（`validator.py` 在 slot_role 求值后覆盖状态并
    # 写 `consistency_mirror_of=`），对它再独立裁定一次是重复计数。
    # 而**真正参与卡激活的触发器义务仍须受授权边界约束**——整类排除会让
    # 消费楼级聚合读数的真触发器逃过合同检查。
    # ⚠️ 镜像标记由 validator 在本函数返回**之后**才写进 notes，故本层看不到，
    # 判据须由调用方前置计算传入（与 validator 里的镜像条件同源，防两处漂移）。
    if is_consistency_mirror:
        return None
    # 边界单首轮审核修复：查**整个绑定集合**（首版只查 bound[0]——部位行在前/
    # 楼级行在后/同值混合会滑过；"任一楼级聚合读数"是裁决原文）。
    if not any((f.qualifiers or {}).get("aggregation") == "building"
               for f in bound):
        return None
    # 🔴 射程沿革：首版全域→S3 时收窄到遮蔽集合（investigation 族记账待裁）
    # →**2026-08-02 investigation 授权边界决策门裁定后恢复全域**：
    # 「任一楼级聚合事实若将进入 satisfied/violated，却找不到有效精确合同，
    # 一律转待裁保护」——slot_targets 登记只授权"生成候选事实"，不授权产
    # 实判；合取规整只证明派生事实相对输入可能成立（正文硬反例：§4.1.4 可
    # 聘请、§4.3.2(b)(c) 可选方法、§4.3.3(a) 已开始≠已完成、§4.2.3 例外）。
    # 调查槽 10 绑定的逐项裁定为独立后续工单，裁成的再进合同表恢复实判。
    if binding_key in SCOPE_PRECISE_AUTHORIZED:
        return None
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["observed_value_json"] = bound[0].value_json
    common.pop("blocked_reason_code", None)
    common["open_reason_code"] = "binding_requires_adjudication_authorization"
    common["notes"] = (
        str(common.get("notes", "")) + "; unauthorized_aggregate_guard: 绑定"
        "未登记，程序拒绝据楼级聚合读数下判定"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "open", "unknown", **common
    )


def _diagnostic_contract_terminal(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    bound: List[FactAtom],
    *,
    use_scope: bool,
    binding_key: Tuple[str, str],
) -> Optional[Obligation]:
    """诊断型授权的**强制终止规则**（S1 实施审核门欠项①，2026-08-02）。

    命中诊断型合同绑定后出口由合同锁定，**不取决于通用产物态许可集合**——
    审核门反向探针实测：把 evidence 移入许可集合、或改聚合行派生标记，首版
    都会滑成 closed+satisfied。本终止规则封死两条：
    - 聚合身份/来源与合同登记相符 ⇒ **恒**落 `open + unknown`，原因码由
      `diagnostic_refusal_reason_code()` 按**产物态事实分类器**在两个诊断码之间
      二选一（产物态 → `artifact_state_not_valid_evidence`；非产物读数 →
      `diagnostic_binding_not_valid_evidence`）——**状态硬编码、码窄枚举**，
      合同行的 `true_exit`/`false_exit` 只被**核对**、不作执行指令（丁③⑤）；
    - 不符（缺标记/多行/来源漂移）⇒ 拒绝式失败 blocked+schema_contract_violation。
    任一情形都**结构上不可能**产 satisfied/violated。
    """
    if not (use_scope and binding_key in DIAGNOSTIC_ONLY_AUTHORIZED_BINDINGS):
        return None
    row = SCOPE_PRECISE_AUTHORIZED.get(binding_key) or {}
    expected_src = row.get("aggregation_source")
    deriv = ((bound[0].provenance or {}).get("derivation")
             if bound else None)
    marked = (
        len(bound) == 1 and bound[0].carrier_type == "building"
        and (bound[0].qualifiers or {}).get("aggregation") == "building"
    )
    # 🔴 形状闸**按「世界有没有楼级聚合行」分档**（2026-08-03 决策门，两家族＋我）。
    #
    # 原判据把 `marked` 当无条件硬闸。实测（kimi 全链重放批 I 全 30 栋）：
    # 4 行绑定的槽**世界里根本不产楼级聚合行**（唯一行分别是 sidecar / measurement /
    # condition 载体）⇒ `marked` **结构上不可能为真** ⇒ 它们会落
    # `blocked/schema_contract_violation`。
    # **那不是「拦住了坏事」，是对专业审查员说「系统坏了」而系统没坏。**
    #
    # 分档理由：`marked` 的价值是**防漂移**（世界一旦不再产唯一聚合行立刻报警）。
    # 世界本就不产聚合行时，它不保护任何东西——诊断行**结构上不产判定**，
    # 聚合形状的严格性在这里**没有消费者**。
    # ⚠️ 但放宽不能变成看不见：走宽松分支时把**证据来自哪种载体**写进 notes
    # （形状闸管不到的那部分，改由留痕承担——这是我在两方裁定之上加的一条：
    # grok 主张「不放宽、把这 4 行排除」，但排除等于让它们**继续出无依据判定**）。
    has_building_aggregate = any(
        f.carrier_type == "building"
        and (f.qualifiers or {}).get("aggregation") == "building"
        for f in bound
    )
    if expected_src == "code_derived_reading":
        # 第三档**不走** `marked`／`has_building_aggregate` 分档：
        # 它的事实本来就不是楼级聚合行，套那套判据必假。
        # 多行允许——值一致性由上游 `conflict_status` 保证
        # （ambiguous 在终止器之前已被拦；实测 230 条派生事实同值）。
        # 形状约束改由 `src_ok` 的「戳 ∧ 载体」承担。
        shape_ok = True
    else:
        shape_ok = marked if has_building_aggregate else True
    # 🔴 来源白名单**按通道分档**（同上决策门，两家族同解）。
    #
    # 原判据「非回退表来源 ⇒ derivation 必须为空」是照产物态形状写的，
    # 实测误伤面 **66.7%**：`building_reading_aggregation` 通道上
    # 1,080 个（行×栋）对里 720 对带 `slot_target_lookup_rule`
    # ——那是 `projection_runtime_mapping` **登记在册的查找规则派生通道**，
    # 不是漂移。
    # ⚠️ **绝不放成「任意 derivation 都行」**——那等于这道来源校验对该通道完全失效。
    # 未在白名单内的戳（如 `category_membership`）**先不放行**，
    # 要放必须按槽实测后再扩。`slot_target_fallback` 明确排除，防通道串味。
    if expected_src == "slot_target_fallback":
        src_ok = deriv == "slot_target_fallback"
    elif expected_src == "code_derived_reading":
        # 第三档：戳必须在登记映射内，**且**载体与登记一致。
        # 明确不接受 `slot_target_fallback`（防通道串味）。
        # ⚠️ 多行 `bound` 时**戳按首行取**（`deriv` 上面取的是 `bound[0]`）、
        # **载体按全行核**（下面的 `all(...)`）。首行戳与其余行不一致的情形被载体核对
        # 兜住：登记映射把戳唯一映到一种载体，异戳行必带异载体（当前唯一登记的桥
        # `derive_verification_performed_facts` 从量测行拷贝 `carrier_type`）⇒ `all` 必假。
        # 「同载体、异戳」的混绑才会漏拦——当前派生器同槽同桥，结构上不产生；
        # 若将来出现，补法是把戳也改成全行核（`all(provenance.derivation == deriv ...)`）。
        _want_carrier = _CODE_DERIVED_READINGS.get(str(deriv or ""))
        src_ok = bool(bound) and _want_carrier is not None and all(
            f.carrier_type == _want_carrier for f in bound)
    else:
        src_ok = deriv in _BUILDING_READING_DERIVATIONS
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    if bound:
        common["observed_value_json"] = bound[0].value_json
    if not (shape_ok and src_ok):
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (
            str(common.get("notes", "")) + "; 诊断型授权绑定拒绝判定：聚合身份"
            f"或来源与合同登记不符（行数={len(bound)}, 来源={deriv!r}, "
            f"登记={expected_src!r}）"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    # 丁⑤：合同行声明的出口只作**审计**——这里核对它与终止器实际出口是否一致，
    # 不一致拒绝式失败，**不得**回退通用求值（否则声明与执行会静默分裂）。
    actual = f"open/{diagnostic_refusal_reason_code(bound)}"
    declared = {str(row.get("true_exit") or ""), str(row.get("false_exit") or "")}
    if declared != {actual}:
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (
            str(common.get("notes", "")) + "; 诊断型授权出口声明与终止器实际出口"
            f"不一致（声明={sorted(declared)!r}, 实际={actual!r}）"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    _note = "diagnostic_contract_terminal"
    if expected_src == "code_derived_reading":
        _note += (f"; 代码派生读数通道：戳={deriv!r} 载体="
                  f"{sorted({str(f.carrier_type) for f in bound})!r}（{len(bound)} 条）")
    elif not has_building_aggregate:
        # 🔴 走了宽松分支——**必须留痕**。放宽形状闸的代价是「绑到的可能不是
        # 楼级聚合行」，虽不影响判定（诊断行恒 open+unknown），但会影响
        # 消费者看到的 `evidence_fact_ids` / `observed_value_json` 是哪一条。
        # 把载体类型写出来，让「放宽」在产物里可见、可审计，而不是静默生效。
        _carriers = sorted({str(f.carrier_type) for f in bound})
        _note += (f"; 形状闸宽松分支：世界未产楼级聚合行，证据载体={_carriers!r}"
                  f"（{len(bound)} 条）")
    common["notes"] = (
        str(common.get("notes", "")) + f"; {_note}"
    ).strip("; ")
    return _artifact_state_refusal(card, fact_pack_meta, kind, common, bound)


def _is_building_axis_reading(f: FactAtom) -> bool:
    """「唯一楼级布尔读数」的载体形判据（c55 扩形，2026-08-04 轴批实测后修正）。

    契约意图不变＝恰一行楼级读数；**标记形随事实本相**，两种合法形：
    ①楼级聚合行：`carrier_type=building` ＋ `qualifiers.aggregation=building`
      （row 37 先例的形，procedure 域聚合读数）；
    ②轴 sidecar 行：`carrier_type=sidecar_entry` ＋ `qualifiers.granularity=building`
      ＋ **无 `fragment_id`**（reporting 三根轴的本相——每 (槽,轴键组合) 恰一行
      楼级伯努利；无 fragment_id 是防碎片级 sidecar 行混入的硬闸）。
    首版只认形①，轴批实测 925 条全落 blocked/SCV——夹具喂的是契约期望形，
    「测在缺陷显现不了的输入上」原样重演，故本判据必须配真实批形状测试。
    """
    q = f.qualifiers or {}
    if f.carrier_type == "building" and q.get("aggregation") == "building":
        return True
    return (f.carrier_type == "sidecar_entry"
            and q.get("granularity") == "building"
            and "fragment_id" not in q)


def _bucket_axis_value_consumption(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    row: Dict[str, Any],
    fact_index: FactIndex,
) -> Optional[Obligation]:
    """c55 桶通道值消费：按授权行读呈交/送达轴的楼级布尔（工单 #20 第二步）。

    ⚠️ 缺省不生效——调用方按 FactIndex 上的 `c55_bucket_value_consumption`
    开关门控（方案甲：等 node 通道第三族案裁完再开，防揭膜）。
    形状判据＝共享判据 `_is_building_axis_reading`（形①building+aggregation 聚合行
    ／形②sidecar_entry+granularity=building 轴本相行，glm F3 修正：原文误写只认
    building 载体）；与 A′ 合同解释器同判据；差异只有一处：**轴事实为空返回 None**
    （授权了但世界没供——旧池无轴槽属常态），调用方落回既有拒判老路，不制造噪声。
    真 → closed/satisfied（裁定：呈交为真蕴含产物在）；
    假 → open/observed_false_without_violation_basis（只指未查到呈交/送达，
    **绝不可读作产物不齐备**——单元 2 边界备注，52 组合裁定零条成立不被推翻）；
    形状坏（多行/混行/非布尔）→ blocked/schema_contract_violation。
    """
    from .fact_binding import parse_value as _pv
    quals = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
             for kv in str(row["qualifier_axis"]).split(",") if "=" in kv}
    candidates = fact_index.slot_index.get(
        fact_index.canonical_slot(str(row["slot_id"])), []
    )
    bound = _filter_by_qualifiers(candidates, quals)
    if not bound:
        return None   # 轴未供给——落回拒判老路（本钩对旧池零扰动的关键）
    _is_marked_agg = len(bound) == 1 and _is_building_axis_reading(bound[0])
    _v = _pv(bound[0].value_json) if _is_marked_agg else None
    # 证据链完整性（qwen 发现⑤）：判定依据换成轴事实后，三个证据字段一起换——
    # 只换 evidence_fact_ids 会留下指向存在轴的 node_refs／slot_ids，消费者回查断链。
    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["evidence_node_refs"] = [
        f.source_node_id for f in bound if f.source_node_id]
    # slot_ids 并集语义（grok 补审发现②的显式化）：证据两字段**换轴**（判定依据
    # 唯一），slot_ids **并集**（保留义务本体的原生槽名供消费者理解）——与 A′
    # contract_satisfied 分支同语义。
    common["slot_ids"] = sorted(
        set(common.get("slot_ids") or []) | {str(row["slot_id"])})
    common["observed_value_json"] = bound[0].value_json
    if not _is_marked_agg or not isinstance(_v, bool):
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (
            str(common.get("notes", "")) + "; c55 桶消费拒绝判定：轴读数非"
            f"「恰一行带 aggregation=building 标记且值为布尔」（行数={len(bound)}）"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    if _v is False:
        common["open_reason_code"] = "observed_false_without_violation_basis"
        common["notes"] = (
            str(common.get("notes", "")) + "; c55 桶消费：呈交/送达轴读数为假"
            "——未查到该行为发生；无期限终局依据不判违反，且按裁定不得读作"
            "产物不齐备，交专业人员复核"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    common["notes"] = (
        str(common.get("notes", "")) + "; c55 桶消费：呈交/送达轴楼级读数为真"
        "（裁定：呈交为真蕴含产物在），据授权行判满足"
    ).strip("; ")
    return _new_obligation(
        card, fact_pack_meta, kind, "closed", "satisfied", **common
    )


def _value_consumption_contract(
    card: RuleCardDTO,
    fact_pack_meta: Dict[str, str],
    kind: str,
    common: Dict[str, Any],
    bound: List[FactAtom],
    *,
    use_scope: bool,
    binding_key: Tuple[str, str],
) -> Optional[Obligation]:
    """A′值消费合同解释器（共用：槽位角色与节点满足两条路径，逐行批准裁决
    「共用同一个合同解释器」）。返回 None＝不在合同射程或值为 True（放行到
    调用方现状路径）；否则返回合同裁定的义务。

    门③实测拦下的形状：聚合值 false 仍被「存在即满足」判 satisfied＝造假合规。
    授权绑定一旦走到一致绑定，**无条件**进入本契约检查——二轮审核探针实测
    首版凭「有无楼级行」放行：无楼级行＋同值部位行会整体绕过滑进存在即满足。
    值授权对该绑定的唯一合法形状＝「恰一行带 aggregation=building 标记且值为
    布尔的楼级聚合读数」：①聚合身份必须核实；②值域必须是布尔——null/字符串/
    数值拒绝式失败；③多行/混行/纯部位行/单部位行同样拒绝
    （blocked+schema_contract_violation）。False → open+
    `observed_false_without_violation_basis`，**绝不产 violated**。
    """
    if not (use_scope and binding_key in VALUE_CONSUMPTION_AUTHORIZED_BINDINGS):
        return None
    from .fact_binding import parse_value as _pv
    # c55 扩形（2026-08-04）：合法形从「building+aggregation 标记」扩为共享判据
    # `_is_building_axis_reading`（含 reporting 轴 sidecar 本相形②）。
    # row 37 的 procedure 聚合行走形①，行为不变。
    _is_marked_agg = len(bound) == 1 and _is_building_axis_reading(bound[0])
    _v = _pv(bound[0].value_json) if _is_marked_agg else None
    if not _is_marked_agg or not isinstance(_v, bool):
        common["evidence_fact_ids"] = [f.fact_id for f in bound]
        common["observed_value_json"] = bound[0].value_json
        common["blocked_reason_code"] = "schema_contract_violation"
        common["notes"] = (
            str(common.get("notes", "")) + "; 值授权绑定拒绝判定：选中楼级行"
            "但非「恰一行带 aggregation=building 标记且值为布尔」的合法聚合"
            f"读数（行数={len(bound)}）"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "blocked", "unknown", **common
        )
    if _v is False:
        common["evidence_fact_ids"] = [bound[0].fact_id]
        common["observed_value_json"] = bound[0].value_json
        common["open_reason_code"] = "observed_false_without_violation_basis"
        common["notes"] = (
            str(common.get("notes", "")) + "; 完整聚合读数为假：正向条件尚未"
            "成立；无期限或终局违约依据，程序不判违反，交专业人员复核"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "open", "unknown", **common
        )
    # 真值出口按**行内显式 true_exit_mode** 分叉（Q2 裁定，2026-08-04 决策门
    # 三线一致——不按 row 号分叉：行增删重排会静默换义）。
    # caller_path（row 37）＝返 None 沿用现状路径（其调用方会判 satisfied）；
    # contract_satisfied（c55 证据通道）＝契约直接判满足——那里的「现状路径」
    # 是产物态拒判死路，轴批双臂重放实测正半边零转化后修正。
    from .binding_contract_registry import SCOPE_PRECISE_BINDINGS as _SPB
    _row = _SPB.get(binding_key)
    # 🔴 kind=artifact 排除（2026-08-04 重放二轮实测）：产物类义务经节点满足
    # 组合与 `artifact:art01` 存在轴绑定**同节点合取**——contract_satisfied 会让
    # 组合里存在轴的 violated 浮出（19 条实证，s2_1_3_s 等重定基卡），与桶侧
    # 揭膜同病。产物类正半边随重定基子案，此处只放行非产物类（证据类主力照转）。
    # kind 闸判据依据（glm 补审建议）：只有 kind=artifact 的义务会把 `artifact:*`
    # 存在轴绑定与本槽引用**同节点合取**（存在轴仅许可产物类产 violated；其它 kind
    # 的存在通道拒判为 open、合取里被压住浮不出）。黑名单形——将来若新增 kind
    # 绑存在轴同节点，须手动补排除。
    if (_row is not None and _row.get("true_exit_mode") == "contract_satisfied"
            and kind != "artifact"):
        common["evidence_fact_ids"] = [bound[0].fact_id]
        common["evidence_node_refs"] = (
            [bound[0].source_node_id] if bound[0].source_node_id else [])
        # slot_ids 取**并集**（与桶钩同语义，grok/glm 补审对齐项）：义务原生槽
        # 与消费轴槽都保留——判定依据是轴（见 evidence_fact_ids），原生槽名
        # 留在集合里供消费者理解义务本体，不是第二个判定依据。
        common["slot_ids"] = sorted(
            set(common.get("slot_ids") or []) | {str(_row["slot_id"])})
        common["observed_value_json"] = bound[0].value_json
        common["notes"] = (
            str(common.get("notes", "")) + "; A′值消费：唯一楼级读数为真，"
            "按行 true_exit_mode=contract_satisfied 由契约直接判满足"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, kind, "closed", "satisfied", **common
        )
    return None   # caller_path：放行到调用方现状路径。


def _evaluate_node_slot_binding(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    base_kind: str,
    slot_ref: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    *,
    authorized_scope_selection: bool = False,
) -> Obligation:
    """把一个已声明 evidence 槽求值为 node 满足通道；不参与通道选择。

    S1 逐行批准（2026-08-02）：本路径补 §6.4.3 分级腿——复用统一候选绑定器
    `select_candidate_facts` 与共享 A′合同解释器（裁决明令不得再实现第二套
    分级/值消费/假值处置）。启用门＝粗门∩精确绑定（NODE_SLOT 视图）∩开关；
    非合同绑定在开关关闭或不在登记内时逐位不变。

    🔴 前置不变量（2026-08-03 审核门要求）：`base_kind` **必须**是
    `refine_action_kind(node.node_kind, node.action)` 的输出。
    本函数下游对许可闸硬传 `kind_from_action_refinement=True`
    ——那是**基于「本通道的 kind 必来自前缀猜测改类」这一事实**。
    将来若有人新增第二个调用点、传入**结构来源**的 artifact（如桶通道 `_BUCKET_DEFAULT_KIND`），
    会被当成前缀猜测**误拒**，而且是**静默**的（方向是「该判的判不了」，不报错）。
    ⇒ 用断言把「未来静默出错」换成「当场炸」。成本一行。
    """
    assert base_kind == refine_action_kind(node.node_kind, node.action), (
        f"本通道的 base_kind 必须来自 refine_action_kind："
        f"传入 {base_kind!r}，但 node.action={node.action!r} 应得 "
        f"{refine_action_kind(node.node_kind, node.action)!r}。"
        f"下游硬传 kind_from_action_refinement=True 依赖这条不变量。"
    )
    slot_ref_id = slot_ref.get("slot_ref_id")
    slot_id = slot_ref.get("slot_id")
    qualifiers = dict(slot_ref.get("qualifiers") or {})
    common: Dict[str, Any] = dict(
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        obligation_node_id=node.obligation_node_id,
        actor=node.actor or None,
        action=node.action or None,
        recipient_ids=list(node.recipient_ids),
        slot_ref_ids=[str(slot_ref_id)] if slot_ref_id else [],
        slot_ids=[str(slot_id)] if slot_id else [],
        trigger_dependency_ids=list(node.trigger_condition_ids),
        notes=(
            f"satisfaction_binding=slot_ref:{slot_ref_id}; "
            f"slot_id={slot_id}; qualifiers={qualifiers!r}"
        ),
    )
    if not slot_ref_id or not slot_id:
        common["blocked_reason_code"] = "schema_contract_violation"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "blocked", "unknown", **common
        )

    _binding_key = (card.rule_card_id, str(slot_ref_id or ""))
    # 失效绑定运行态拒绝——先于一切求值（不许回退通用路径）。
    _rej = _rejected_binding_refusal(
        card, fact_pack_meta, base_kind, common, _binding_key,
        enabled=authorized_scope_selection)
    if _rej is not None:
        return _rej
    _use_scope = (
        authorized_scope_selection
        and fact_index.canonical_slot(str(slot_id)) in BINDING_COARSE_SLOTS
        and _binding_key in NODE_SLOT_AUTHORIZED_BINDINGS
    )
    _sel = select_candidate_facts(
        fact_index, str(slot_id), qualifiers, scope_selection=_use_scope)
    candidates, bound = _sel.candidates, _sel.bound
    if candidates and qualifiers and not _sel.qfiltered:
        common["blocked_reason_code"] = "qualifier_conflict"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "blocked", "unknown", **common
        )
    status = _sel.status
    if status == "missing":
        common["open_reason_code"] = "missing_fact"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "open", "unknown", **common
        )
    # S3 甲′精确待裁层（与槽位角色路径同位：候选缺失后、一切出口前；
    # §6.1.3 片段事实路径专防——批 I 现产物 29 条 false→satisfied 即此形状）。
    _pend = _pending_adjudication_guard(
        card, fact_pack_meta, base_kind, common, _sel.bound,
        enabled=authorized_scope_selection, binding_key=_binding_key)
    if _pend is not None:
        return _pend
    if status == "ambiguous":
        common["blocked_reason_code"] = "ambiguous_fact_binding"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "blocked", "unknown", **common
        )

    # 诊断型强制终止＋A′共享解释器（两路径同一实现）——**先于哨兵**（S1 二轮
    # 审核阻断①：节点路径原顺序哨兵在前，同一诊断绑定被哨兵截成
    # closed/not_applicable，推翻"出口合同锁定"；两路径优先级必须唯一）。
    _diag_obl = _diagnostic_contract_terminal(
        card, fact_pack_meta, base_kind, common, bound,
        use_scope=_use_scope, binding_key=_binding_key,
    )
    if _diag_obl is not None:
        return _diag_obl
    _aprime_obl = _value_consumption_contract(
        card, fact_pack_meta, base_kind, common, bound,
        use_scope=_use_scope, binding_key=_binding_key,
    )
    if _aprime_obl is not None:
        return _aprime_obl

    # DEBT-083 甲：绑定事实组过哨兵分类器（缺省开关关闭 ⇒ 恒 None，逐位不变）。
    sentinel_obl = _sentinel_short_circuit(
        card, fact_pack_meta, base_kind, common, bound, fact_index
    )
    if sentinel_obl is not None:
        return sentinel_obl

    # S3 甲′通用层：未登记绑定不得依赖楼级聚合读数产实判（真伪即判在即）。
    _agg_guard = _unauthorized_aggregate_guard(
        card, fact_pack_meta, base_kind, common, bound,
        enabled=authorized_scope_selection, binding_key=_binding_key)
    if _agg_guard is not None:
        return _agg_guard

    common["evidence_fact_ids"] = [f.fact_id for f in bound]
    common["evidence_node_refs"] = [f.source_node_id for f in bound if f.source_node_id]
    common["observed_value_json"] = bound[0].value_json
    # 证据许可闸（node 主义务的槽通道；`base_kind` 就是 node 自身的语义类别）
    # ——诊断型合同绑定（行 1-36）的冻结出口就在这里：产物态布尔＋不许可
    # kind ⇒ open/artifact_state_not_valid_evidence（否定授权条款机器面）。
    # base_kind 来自 `refine_action_kind`（见 evaluate_obligation_node）
    # ⇒ 该通道的 artifact 属"前缀猜测改类"，不得据产物齐备布尔下判定。
    if not artifact_state_licenses_verdict(
            base_kind, bound, kind_from_action_refinement=True):
        return _artifact_state_refusal(
            card, fact_pack_meta, base_kind, common, bound
        )
    truthy = _canon_truthy(parse_value(bound[0].value_json))
    if truthy is None:
        common["open_reason_code"] = "null_observed_value"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "open", "unknown", **common
        )
    return _new_obligation(
        card,
        fact_pack_meta,
        base_kind,
        "closed",
        "satisfied" if truthy else "violated",
        **common,
    )


_NODE_OPEN_REASON_RANK = {
    # 2026-08-03 三方仲裁「丁」路新增（档位取舍与影响面评估见 identity_v2 同表注释）。
    "diagnostic_binding_not_valid_evidence": 12,
    # 2026-08-02 S3 新增，取新最大值（不动既有档位 ⇒ 既有 merge 结果不变）。
    "binding_requires_adjudication_authorization": 11,
    # 2026-08-02 A′裁决新增，取新最大值（不动既有档位 ⇒ 既有 merge 结果不变）。
    "observed_false_without_violation_basis": 10,
    # 2026-07-27 新增，取新最大值（不动既有档位 ⇒ 既有 merge 结果不变）。
    "artifact_state_not_valid_evidence": 9,
    "missing_satisfaction_binding": 8,
    "applicability_uncertain": 7,
    "depends_on_open_trigger": 6,
    "missing_required_field_group": 5,
    "missing_measurement": 4,
    "missing_artifact_evidence": 3,
    "missing_time_anchor": 2,
    "missing_fact": 1,
    "null_observed_value": 0,
}
_NODE_BLOCKED_REASON_RANK = {
    "schema_contract_violation": 9,
    "internal_error": 8,
    "missing_rule_edge": 7,
    "unsupported_predicate_kind": 6,
    "unsupported_operator": 5,
    "unit_mismatch": 4,
    "qualifier_conflict": 3,
    "ambiguous_fact_binding": 2,
    "artifact_not_modeled_upstream": 1,
}


def _binding_audit_paths(bindings: List[Obligation]) -> List[str]:
    paths: List[str] = []
    for binding in bindings:
        paths.extend(f"slot_ref:{v}" for v in binding.slot_ref_ids)
        paths.extend(f"artifact:{v}" for v in binding.artifact_ids)
        paths.extend(f"deadline:{v}" for v in binding.deadline_ids)
    return sorted(set(paths))


def _merge_node_satisfaction_bindings(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    base_kind: str,
    common: Dict[str, Any],
    bindings: List[Obligation],
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """按合取聚合已声明通道；只搬运确定性子求值结果。"""
    merged = dict(common)
    for field in (
        "slot_ref_ids",
        "slot_ids",
        "artifact_ids",
        "artifact_keys",
        "deadline_ids",
        "time_anchor_keys",
        "evidence_fact_ids",
        "evidence_node_refs",
    ):
        values = list(merged.get(field) or [])
        for binding in bindings:
            values.extend(getattr(binding, field) or [])
        merged[field] = sorted(set(values))
    paths = _binding_audit_paths(bindings)
    merged["notes"] = (
        f"{merged.get('notes', '')}; satisfaction_bindings="
        f"{json.dumps(paths, ensure_ascii=False, separators=(',', ':'))}"
    ).strip("; ")

    # 禁止节点必须且只能有一个主证据槽；任何其它组合都拒绝。
    if node.node_kind == "prohibition" and (
        len(bindings) != 1 or len(bindings[0].slot_ref_ids) != 1
    ):
        merged["open_reason_code"] = "missing_satisfaction_binding"
        return _new_obligation(
            card, fact_pack_meta, base_kind, "open", "unknown", **merged
        )

    blocked = [b for b in bindings if b.closure_status == "blocked"]
    if blocked:
        winner = max(
            blocked,
            key=lambda b: _NODE_BLOCKED_REASON_RANK.get(b.blocked_reason_code or "", -1),
        )
        merged["blocked_reason_code"] = winner.blocked_reason_code
        # 🔴 把胜出子绑定的 notes **带上来**（2026-08-03）。
        #
        # 原先只搬 `blocked_reason_code`，子绑定说明「**为什么**被拒」的那句
        # 留在子对象里、随合并丢掉。实测后果：A 批落表后 256 条
        # `schema_contract_violation` 里有 **128 条**（`supervision.site_visit.performed`
        # 122 ＋ certificate 6）在产物里**只剩** `satisfaction_bindings=[…]`，
        # 看不出是哪一道闸拒的——**排障线索被自己抹掉了**。
        #
        # 这不只是「我查不到」：消费者文档也是照这些 notes 渲染的，
        # 等于对专业审查员说「模式契约违例」却说不出违了哪一条。
        # ⚠️ 只带**胜出那一条**，不是全部子绑定——合并语义是「取最强原因」，
        # 带全部会让 notes 与 `blocked_reason_code` 讲不同的故事。
        _wn = str(winner.notes or "").strip("; ")
        if _wn:
            merged["notes"] = (
                str(merged.get("notes", "")) + f"; blocked_by_binding: {_wn}"
            ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, base_kind, "blocked", "unknown", **merged
        )
    opened = [b for b in bindings if b.closure_status == "open"]
    if opened:
        winner = max(
            opened,
            key=lambda b: _NODE_OPEN_REASON_RANK.get(b.open_reason_code or "", -1),
        )
        merged["open_reason_code"] = winner.open_reason_code
        return _new_obligation(
            card, fact_pack_meta, base_kind, "open", "unknown", **merged
        )

    if len(bindings) == 1:
        merged["observed_value_json"] = bindings[0].observed_value_json
    # DEBT-083 哨兵收尾（**第五漏网口**，2026-08-02 第三门层 2 抓出 18 条后补）：
    # 绑定经分类器判非判定（closed+not_applicable 且 notes 带
    # `non_adjudicative_sentinel` 标记）时，本合并不得再按「非违反即满足」把
    # NA 当 satisfied——旧行为正是 18 条 action 假实判的通道。全部绑定均为
    # 哨兵 NA ⇒ 节点 closed+not_applicable（含禁止节点：哨兵下同样不可判）；
    # 混有真 satisfied/violated 时保持既有合取语义不变。**标记门控** ⇒ 开关
    # 关闭时不存在该形态，缺省行为逐位不变。
    _sentinel_na = [
        b for b in bindings
        if b.satisfaction_status == "not_applicable"
        and "non_adjudicative_sentinel" in (b.notes or "")
    ]
    if _sentinel_na and len(_sentinel_na) == len(bindings):
        merged["comparator_result"] = False
        merged["notes"] = (
            merged.get("notes", "")
            + "; non_adjudicative_sentinel: inherited_from_bindings"
        ).strip("; ")
        return _new_obligation(
            card, fact_pack_meta, base_kind, "closed", "not_applicable", **merged
        )
    if node.node_kind == "prohibition":
        truthy = _canon_truthy(parse_value(bindings[0].observed_value_json))
        if truthy is None:
            merged["open_reason_code"] = "null_observed_value"
            return _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **merged
            )
        satisfaction = "violated" if truthy else "satisfied"
    else:
        satisfaction = (
            "violated"
            if any(b.satisfaction_status == "violated" for b in bindings)
            else "satisfied"
        )
    return _new_obligation(
        card, fact_pack_meta, base_kind, "closed", satisfaction, **merged
    )


def evaluate_obligation_node(
    card: RuleCardDTO,
    obligation_node: Any,
    fact_index: FactIndex,
    trigger_active: Any,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
    authorized_scope_selection: bool = False,
) -> List[Obligation]:
    """评估一个 obligation_graph node（spec §6.3.10）。

    每个 node 至少生成 1 条 node-level obligation；artifact_ids / deadline_ids /
    method 派生子义务。返回该 node 产生的全部 obligation 列表。

    `source_sink`（§1.2 纯旁路来源登记，默认 None = 现网 live 路径零副作用）：非 None 时，
    每 append 一条义务即同序 append 一个 `SourceToken`（token[i] ↔ 返回列表[i]），供关联层组
    `BoundObligation`。登记**不改**返回义务字节、**不进**任何判定分支（fan-out N 条各携各自令牌）。
    """
    node = (
        obligation_node
        if isinstance(obligation_node, ObligationNodeDTO)
        else ObligationNodeDTO.from_dict(dict(obligation_node))
    )
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    base_kind = refine_action_kind(node.node_kind, node.action)
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）

    out: List[Obligation] = []

    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        obligation_node_id=node.obligation_node_id,
        actor=node.actor or None,
        action=node.action or None,
        recipient_ids=list(node.recipient_ids),
        artifact_ids=list(node.artifact_ids),
        deadline_ids=list(node.deadline_ids),
        trigger_dependency_ids=list(node.trigger_condition_ids),
        notes="sources=[obligation_graph]",
    )

    # ---- node-level closure/satisfaction 优先级（spec §6.3.10.4）----
    # 1. card-level trigger 聚合 false 由主循环跳过；这里处理 open/blocked 继承。
    if trigger_active == "open":
        node_common = dict(common)
        node_common["depends_on_open_trigger"] = True
        node_common["open_reason_code"] = "depends_on_open_trigger"
        node_common["trigger_state"] = "open"
        if not node_common["trigger_dependency_ids"]:
            node_common["trigger_dependency_ids"] = ["__card_trigger__"]
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out
    if trigger_active == "blocked":
        node_common = dict(common)
        node_common["blocked_reason_code"] = "missing_rule_edge"
        node_common["trigger_state"] = "blocked"
        node_common["notes"] = common["notes"] + "; trigger aggregate blocked"
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out

    # 4. node 引用的 artifact / deadline / recipient id 不存在 → blocked。
    missing_ref = _node_dangling_reference(card, node)
    if missing_ref is not None:
        node_common = dict(common)
        node_common["blocked_reason_code"] = "missing_rule_edge"
        node_common["notes"] = common["notes"] + f"; dangling ref {missing_ref}"
        out.append(
            _new_obligation(
                card, fact_pack_meta, base_kind, "blocked", "unknown", **node_common
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
            )
        return out

    # 子义务先求值一次；单节点卡才允许这些卡级/节点级通道参与 node 主义务。
    artifact_children: List[Tuple[str, Obligation]] = []
    # 同一个 artifact 通道有**两个不同身份的消费者**，许可判据不同，故各求值一次：
    #   · `artifact_children` —— 派生出去的独立 artifact 子义务（kind="artifact"，
    #     语义就是「该产物须齐备」）⇒ 许可，字节不变。
    #   · `artifact_bindings` —— 拿它当 **node 主义务**的满足通道。此时该判的是 node
    #     自己的语义（`base_kind`）：拿「檢驗記錄存在」证明「已完成涵蓋範圍檢驗」不成立。
    #     base_kind == "artifact"（submit_/deliver_ 类动作）时两者同一，直接复用。
    artifact_bindings: List[Obligation] = []
    for artifact_id in sorted(node.artifact_ids):
        key = _resolve_node_artifact_key(card, artifact_id)
        if key:
            child = evaluate_artifact_obligation(
                card,
                key,
                "artifact",
                fact_index,
                trigger_active,
                fact_pack_meta,
                artifact_id=artifact_id,
                bucket="obligation_graph.node",
            )
            artifact_children.append((artifact_id, child))
            artifact_bindings.append(
                child
                if base_kind == "artifact"
                else evaluate_artifact_obligation(
                    card,
                    key,
                    base_kind,
                    fact_index,
                    trigger_active,
                    fact_pack_meta,
                    artifact_id=artifact_id,
                    bucket="obligation_graph.node",
                )
            )
    deadline_children: List[Tuple[str, Obligation]] = []
    for deadline_id in sorted(node.deadline_ids):
        dl = _resolve_node_deadline(card, deadline_id)
        if dl is not None:
            deadline_children.append(
                (
                    deadline_id,
                    evaluate_deadline(card, dl, fact_index, trigger_active, fact_pack_meta),
                )
            )

    graph_nodes = (card.obligation_graph or {}).get("nodes", []) or []
    satisfaction_bindings: List[Obligation] = []
    if len(graph_nodes) == 1:
        satisfaction_bindings.extend(
            _evaluate_node_slot_binding(
                card, node, base_kind, ref, fact_index, fact_pack_meta,
                authorized_scope_selection=authorized_scope_selection,
            )
            for ref in _node_satisfaction_slot_refs(card, node)
        )
        if node.node_kind != "prohibition":
            satisfaction_bindings.extend(artifact_bindings)
            satisfaction_bindings.extend(o for _id, o in deadline_children)

    # 5/6/7/8 node-level 主义务判定。
    node_obl = _evaluate_node_main(
        card,
        node,
        base_kind,
        common,
        fact_index,
        fact_pack_meta,
        satisfaction_bindings,
    )
    out.append(node_obl)
    if source_sink is not None:
        source_sink.append(
            SourceToken("obligation_graph", node.obligation_node_id, "node", scope_fid)
        )

    # 派生 artifact 子义务（spec §6.3.10.3）。
    for artifact_id, child in artifact_children:
        out.append(child)
        if source_sink is not None:
            source_sink.append(
                SourceToken("workflow_artifact", artifact_id, "artifact", scope_fid)
            )

    # 派生 deadline 子义务（spec §6.3.10.3）。
    for deadline_id, child in deadline_children:
        out.append(child)
        if source_sink is not None:
            source_sink.append(
                SourceToken("workflow_deadline", deadline_id, "deadline", scope_fid)
            )

    # 派生 method 义务（spec §6.3.10.3）。
    method_keys = (card.workflow_operands or {}).get("method_keys_allowed", []) or []
    if method_keys and base_kind in {"method"}:
        out.append(
            _evaluate_method_obligation(
                card, node, method_keys, fact_index, fact_pack_meta
            )
        )
        if source_sink is not None:
            source_sink.append(
                SourceToken("obligation_graph", node.obligation_node_id, "method", scope_fid)
            )

    return out


def _evaluate_node_main(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    base_kind: str,
    common: Dict[str, Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    satisfaction_bindings: List[Obligation],
) -> Obligation:
    """node-level 主义务的 5/6/7/8 判定（spec §6.3.10.4）。"""
    common = dict(common)

    # method 类主节点走方法语义（q5 专员判定 + codex 逐卡裁定，2026-07-08）：
    # - method_keys_allowed 为空 = 条款无可枚举验证方法约束（专员积极判定，如
    #   重浇法/局部修补等修葺工法条款）→ closed+not_applicable（vacuous）；
    # - ["*"] = 开放集（验证义务真实、方法不限）→ 任意 method_class 证据满足；
    # - 非空具体集 → 白名单匹配（既有语义）。
    # 三案均在确定性验证器内，判定权/blind 红线不涉。
    if base_kind == "method":
        method_keys = (card.workflow_operands or {}).get(
            "method_keys_allowed", []
        ) or []
        if not method_keys:
            common["notes"] = (
                common.get("notes", "")
                + "; regulation prescribes no enumerable verification method"
                  " (q5 specialist-verified); method semantics vacuous"
            )
            return _new_obligation(
                card, fact_pack_meta, base_kind, "closed", "not_applicable",
                **common,
            )
        allowed = {str(k) for k in method_keys}
        if "*" in allowed:
            matched = [
                f for facts in fact_index.method_index.values() for f in facts
            ]
        else:
            matched = [
                f
                for key, facts in fact_index.method_index.items()
                if key in allowed
                for f in facts
            ]
        if not matched:
            common["open_reason_code"] = "missing_fact"
            common["notes"] = (
                common.get("notes", "") + "; method_class fact missing"
            )
            return _new_obligation(
                card, fact_pack_meta, base_kind, "open", "unknown", **common
            )
        common["evidence_fact_ids"] = [f.fact_id for f in matched]
        common["observed_value_json"] = matched[0].value_json
        return _new_obligation(
            card, fact_pack_meta, base_kind, "closed", "satisfied", **common
        )

    if satisfaction_bindings:
        return _merge_node_satisfaction_bindings(
            card, node, base_kind, common, satisfaction_bindings, fact_pack_meta
        )

    # 没有卡侧可确定通道：缺省拒绝，不把 action 当槽名，也不猜触发/收件人语义。
    common["open_reason_code"] = "missing_satisfaction_binding"
    common["notes"] = common.get("notes", "") + "; satisfaction_binding_missing"
    return _new_obligation(
        card, fact_pack_meta, base_kind, "open", "unknown", **common
    )


def _evaluate_method_obligation(
    card: RuleCardDTO,
    node: ObligationNodeDTO,
    method_keys: List[Any],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """method 义务（spec §6.3.10.3：绑定 qual.method_class 或 measurement method_class）。"""
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    common: Dict[str, Any] = dict(
        source_clause_ids=clause_ids,
        source_quote_ids=quote_ids,
        obligation_node_id=node.obligation_node_id,
        actor=node.actor or None,
        action=node.action or None,
        notes="sources=[obligation_graph]; method derivation",
    )
    # method_class fact：method_index 任意命中即视作可闭包。
    # "*" = 开放集哨兵（q5 专员判定 + codex 裁定 (iii)，2026-07-08）：条款要求
    # "合适的验证测试"但方法集开放（如 §5.1.1 专业判断表述）→ 任意验证测量
    # 方法证据均可满足。
    allowed = {str(k) for k in method_keys}
    if "*" in allowed:
        matched = [f for facts in fact_index.method_index.values() for f in facts]
    else:
        matched = [
            f
            for key, facts in fact_index.method_index.items()
            if key in allowed
            for f in facts
        ]
    if not matched:
        common["open_reason_code"] = "missing_fact"
        common["notes"] = common["notes"] + "; method_class fact missing"
        return _new_obligation(
            card, fact_pack_meta, "method", "open", "unknown", **common
        )
    common["evidence_fact_ids"] = [f.fact_id for f in matched]
    common["observed_value_json"] = matched[0].value_json
    return _new_obligation(
        card, fact_pack_meta, "method", "closed", "satisfied", **common
    )


def _node_dangling_reference(
    card: RuleCardDTO, node: ObligationNodeDTO
) -> Optional[str]:
    """检查 node 引用的 artifact / deadline / recipient id 是否在 card 内有定义。

    返回第一个悬空引用描述；全部存在返回 None。
    """
    wf = card.workflow_operands or {}
    # 已定义的 artifact_id / deadline_id / recipient_id 集合。
    defined_artifacts = {
        a.get("artifact_id")
        for a in (wf.get("artifacts", []) or [])
        if isinstance(a, dict) and a.get("artifact_id")
    }
    defined_deadlines = {
        d.get("deadline_id")
        for d in (wf.get("deadlines", []) or [])
        if isinstance(d, dict) and d.get("deadline_id")
    }
    defined_recipients = set()
    for r in wf.get("recipients", []) or []:
        if isinstance(r, dict):
            rid = r.get("recipient_id")
            if rid:
                defined_recipients.add(rid)
        elif isinstance(r, str):
            defined_recipients.add(r)

    # 只在 card 确实声明了对应定义列表时才判悬空（空列表视为「未建模」不判悬空）。
    if defined_artifacts:
        for aid in node.artifact_ids:
            if aid not in defined_artifacts:
                return f"artifact_id={aid!r}"
    if defined_deadlines:
        for did in node.deadline_ids:
            if did not in defined_deadlines:
                return f"deadline_id={did!r}"
    if defined_recipients:
        for rid in node.recipient_ids:
            if rid not in defined_recipients:
                return f"recipient_id={rid!r}"
    return None


def _resolve_node_artifact_key(
    card: RuleCardDTO, artifact_id: str
) -> Optional[str]:
    """从 workflow_operands.artifacts 把 node 的 artifact_id 解析成 artifact_key。

    若 artifact_id 本身就是已知 artifact_key，直接返回。
    """
    wf = card.workflow_operands or {}
    for a in wf.get("artifacts", []) or []:
        if isinstance(a, dict) and a.get("artifact_id") == artifact_id:
            return a.get("artifact_key") or artifact_id
    if artifact_id in _KNOWN_ARTIFACT_KEYS:
        return artifact_id
    return artifact_id  # 交由 resolve_artifact_slot 判未登记


def _resolve_node_deadline(
    card: RuleCardDTO, deadline_id: str
) -> Optional[Dict[str, Any]]:
    """从 workflow_operands.deadlines 把 node 的 deadline_id 解析成 deadline dict。"""
    wf = card.workflow_operands or {}
    for d in wf.get("deadlines", []) or []:
        if isinstance(d, dict) and d.get("deadline_id") == deadline_id:
            return d
    return None


class _NodeState:
    """summarize_node_state 的结果（spec §6.3.10.5）。"""

    def __init__(
        self,
        has_violation_or_failed_test: bool,
        has_open_or_blocked_or_unable_fact: bool,
    ) -> None:
        self.has_violation_or_failed_test = has_violation_or_failed_test
        self.has_open_or_blocked_or_unable_fact = has_open_or_blocked_or_unable_fact


def summarize_node_state(obligations: List[Obligation]) -> _NodeState:
    """汇总一个 node 的 obligations 状态（spec §6.3.10.5）。"""
    has_violation = any(
        (o.closure_status == "closed" and o.satisfaction_status == "violated")
        or o.comparator_result is False
        for o in obligations
    )
    has_open_blocked = any(
        o.closure_status in {"open", "blocked"} for o in obligations
    )
    return _NodeState(has_violation, has_open_blocked)


def evaluate_obligation_edges(
    card: RuleCardDTO,
    edges: List[Any],
    node_obligations: Dict[str, List[Obligation]],
    fact_index: FactIndex,
    fact_pack_meta: Dict[str, str],
    *,
    source_sink: Optional[List[SourceToken]] = None,
) -> List[Obligation]:
    """评估 obligation_graph edges（spec §6.3.10.5）。

    edges 表达义务间条件依赖。在所有 node-level obligations 初评后处理。
    返回 edge 相关的 audit obligation（target 未激活 / 悬空 / 未知关系）。

    `source_sink`（§1.2/§3.4.3 纯旁路来源登记，默认 None）：非 None 时每 append 一条边义务即同序
    append 一个 `SourceToken`，按 edge 审计三态携各自判别（§1.4/§3.4.3，codex 阻断 1 修订）：
      悬空 → role="edge_dangling"（primary_id=edge_id）；
      未知 relation → role="edge_unknown"（primary_id=edge_id, member=source/target）——source/target
        两义务各携 member 判别、**各绑各分身**（不再撞同一 SID 致 v5 误合并）；
      inactive-target 聚合 → role="edge_inactive"（primary_id=target_id, edge_ids=**完整排序集**）——
        身份携聚合全 edge（不再只登记 min(edge_id) 丢其余身份）。登记不改返回义务字节。
    """
    clause_ids = _card_clause_ids(card)
    quote_ids = _card_quote_ids(card)
    scope_fid = fact_pack_meta.get("fragment_id")  # §1.4：令牌冻结 scope（与义务 fragment_id 同源）
    nodes_by_id = {
        str(n.get("obligation_node_id")): n
        for n in (card.obligation_graph or {}).get("nodes", []) or []
        if isinstance(n, dict)
    }
    edge_dtos = [
        e if isinstance(e, ObligationEdgeDTO) else ObligationEdgeDTO.from_dict(dict(e))
        for e in edges or []
    ]

    out: List[Obligation] = []
    # 记录每个 target node 的激活情况：node_id -> (active, [edge_id]).
    activation: Dict[str, Tuple[bool, List[str]]] = {}

    for edge in sorted(
        edge_dtos, key=lambda e: (e.source_node_id, e.target_node_id, e.relation)
    ):
        common: Dict[str, Any] = dict(
            source_clause_ids=clause_ids,
            source_quote_ids=quote_ids,
            obligation_edge_ids=[edge.obligation_edge_id],
        )
        # 悬空 source / target。
        if (
            edge.source_node_id not in nodes_by_id
            or edge.target_node_id not in nodes_by_id
        ):
            common["blocked_reason_code"] = "missing_obligation_edge_target"
            common["notes"] = (
                f"edge {edge.obligation_edge_id} references missing node"
            )
            out.append(
                _new_obligation(
                    card, fact_pack_meta, "escalation", "blocked", "unknown", **common
                )
            )
            if source_sink is not None:
                source_sink.append(
                    SourceToken(
                        "obligation_graph", edge.obligation_edge_id,
                        "edge_dangling", scope_fid,
                    )
                )
            continue

        # 未知 relation。
        if edge.relation not in {"if_failed_then", "if_unable_then"}:
            common["blocked_reason_code"] = "unsupported_obligation_edge_relation"
            common["notes"] = f"edge relation {edge.relation!r} not supported"
            # source 与 target 均生成 blocked audit obligation（§3.4.3 两分身，各携 member 判别）。
            for member, nid in (
                ("source", edge.source_node_id),
                ("target", edge.target_node_id),
            ):
                c = dict(common)
                c["obligation_node_id"] = nid
                out.append(
                    _new_obligation(
                        card, fact_pack_meta, "escalation", "blocked", "unknown", **c
                    )
                )
                if source_sink is not None:
                    source_sink.append(
                        SourceToken(
                            "obligation_graph", edge.obligation_edge_id,
                            "edge_unknown", scope_fid, member=member,
                        )
                    )
            continue

        source_state = summarize_node_state(
            node_obligations.get(edge.source_node_id, [])
        )
        if edge.relation == "if_failed_then":
            active = source_state.has_violation_or_failed_test
        else:  # if_unable_then
            active = source_state.has_open_or_blocked_or_unable_fact

        prev_active, prev_edges = activation.get(
            edge.target_node_id, (False, [])
        )
        activation[edge.target_node_id] = (
            prev_active or active,
            prev_edges + [edge.obligation_edge_id],
        )

    # target 未激活 → closed + not_applicable audit obligation。
    for target_id, (active, edge_ids) in sorted(activation.items()):
        if not active:
            target_node = nodes_by_id.get(target_id, {})
            common = dict(
                source_clause_ids=clause_ids,
                source_quote_ids=quote_ids,
                obligation_node_id=target_id,
                obligation_edge_ids=sorted(edge_ids),
                notes="inactive_by_obligation_edge",
            )
            out.append(
                _new_obligation(
                    card,
                    fact_pack_meta,
                    "escalation",
                    "closed",
                    "not_applicable",
                    **common,
                )
            )
            if source_sink is not None:
                # inactive-target 聚合 → 身份携**完整 edge SID 排序集**（§3.4.3，codex 阻断 1 修订）：
                # primary_id=target_id、edge_ids=完整排序集——改/移除任一（含非最小）edge 改身份
                # （不再只登记 min(edge_id) 丢其余身份）。真语料每 target 恒 1 edge，退化为单元素集。
                source_sink.append(
                    SourceToken(
                        "obligation_graph", target_id, "edge_inactive", scope_fid,
                        edge_ids=tuple(sorted(edge_ids)),
                    )
                )
    return out


# ===================================================================== #
# §6.3.2 scope audit obligations
# ===================================================================== #
def make_scope_not_applicable(
    card: RuleCardDTO, applicability: Any, fact_pack_meta: Dict[str, str]
) -> Obligation:
    """not_applicable card 的 scope audit obligation（spec §6.3.2）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "scope",
        "closed",
        "not_applicable",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        applicability_state="not_applicable",
        notes="; ".join(applicability.reasons) or "card not applicable",
    )


def make_scope_open(
    card: RuleCardDTO, applicability: Any, fact_pack_meta: Dict[str, str]
) -> Obligation:
    """uncertain card 的 scope open obligation（spec §6.3.2）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "scope",
        "open",
        "unknown",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        applicability_state="uncertain",
        open_reason_code="applicability_uncertain",
        notes="; ".join(applicability.reasons) or "applicability uncertain",
    )


def make_rule_not_applicable_by_trigger(
    card: RuleCardDTO,
    trigger_results: List[Obligation],
    fact_pack_meta: Dict[str, str],
) -> Obligation:
    """trigger 聚合 false 时的 trigger not_applicable audit obligation（spec §6.3.3）。"""
    return _new_obligation(
        card,
        fact_pack_meta,
        "trigger",
        "closed",
        "not_applicable",
        source_clause_ids=_card_clause_ids(card),
        source_quote_ids=_card_quote_ids(card),
        trigger_state="inactive",
        trigger_dependency_ids=[
            o.obligation_node_id or o.obligation_id
            for o in trigger_results
            if o.obligation_node_id
        ],
        notes="rule trigger aggregate evaluated false; action obligations skipped",
    )


# ===================================================================== #
# 排序辅助
# ===================================================================== #
def _stable_key(obj: Any) -> str:
    """对任意 dict / str 生成稳定排序键（spec §6.6 stable_json_key）。"""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


# ===================================================================== #
# identity-v2 阶段一旁路（加性；spec 草案 v4 A.1 两阶段架构）
# ===================================================================== #
def derive_obligation_blueprints(
    card: RuleCardDTO, fact_pack_meta: Dict[str, str]
) -> List[Any]:
    """派生器**并行**产出的 v2 `ObligationBlueprint`（从源头冻结身份，加性旁路）。

    与本模块的 v1 `Obligation` 产出**并存**：v1 判定路径零改，本入口只**增加** v2
    身份冻结（阶段一）。走 `blueprint_deriver.derive_covered_card_blueprints`（**可表示
    channel** 覆盖派生；真模型缺口 channel deadline / 普通-升级 node 显式排除、登记
    `MODEL_GAP_CHANNELS`，非静默伪装完整——STRICT 总入口
    `blueprint_deriver.derive_card_blueprints` 对含缺口的卡 fail-closed）。

    **blocker 6（Decimal 读径）**：本入口收**已解析** `RuleCardDTO`；须喂 **Decimal 读径**
    （`rulecard_decimal_load.load_identity_cards`，`parse_float=Decimal`）产出的卡——数字词元落
    int/Decimal。若喂 v1 float 读径（`json.loads`）产的卡，float 阈值会被 identity 入口
    hard-fail（13 卡 float 断线）。整包 Decimal 读+派生走 `derive_obligation_blueprints_from_bundle`。

    延迟 import 避免 import 期环依赖（`blueprint_deriver` 顶层 import 本模块的纯源读取 helper）。
    """
    from .blueprint_deriver import derive_covered_card_blueprints

    return derive_covered_card_blueprints(card, fact_pack_meta)


def derive_obligation_blueprints_from_bundle(
    bundle_path: Any, fact_pack_meta: Dict[str, str]
) -> List[Any]:
    """**blocker 6 生产入口**：从 `rule_cards.json` 路径经 Decimal 读径读原始词元 + 运行级覆盖
    派生（13 卡 float 阈值不再断线）。委托 `blueprint_deriver.derive_covered_blueprints_from_bundle`。
    """
    from .blueprint_deriver import derive_covered_blueprints_from_bundle

    return derive_covered_blueprints_from_bundle(bundle_path, fact_pack_meta)


__all__ = [
    "ARTIFACT_KEY_TO_SIDECAR_SLOT",
    "ARTIFACT_KEYS_NOT_MODELED",
    "W0_09_ARTIFACT_SLOTS",
    "ARTIFACT_STATE_LICENSED_KINDS",
    "ARTIFACT_STATE_UNLICENSED_KINDS",
    "ARTIFACT_STATE_OPEN_REASON",
    "is_artifact_state_fact",
    "artifact_state_licenses_verdict",
    "TRUTHY_VALUES",
    "FALSY_VALUES",
    "SchemaContractError",
    "resolve_artifact_slot",
    "qualifiers_match",
    "evaluate_trigger",
    "trigger_state",
    "aggregate_trigger_logic",
    "evaluate_slot_role",
    "evaluate_threshold",
    "evaluate_artifact_obligation",
    "derive_workflow_artifact_obligations",
    "derive_workflow_deadline_obligations",
    "evaluate_evidence_requirement",
    "evaluate_deadline",
    "evaluate_exception",
    "evaluate_definition",
    "refine_action_kind",
    "evaluate_obligation_node",
    "evaluate_obligation_edges",
    "summarize_node_state",
    "make_scope_not_applicable",
    "make_scope_open",
    "make_rule_not_applicable_by_trigger",
    "_stable_key",
    "derive_obligation_blueprints",
    "derive_obligation_blueprints_from_bundle",
]
