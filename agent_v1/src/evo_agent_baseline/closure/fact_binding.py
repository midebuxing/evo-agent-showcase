"""Fact binding —— fact 索引、canonicalization、target scoping、冲突处理。

实现 spec §6.4 全部：
- §6.4.1 fact indexes（slot/measure/carrier/artifact/method/alias 六索引）
- §6.4.2 canonicalization（slot/measure 别名归一、JSON canonical、数值容差）
- §6.4.3 target scoping（fragment > component > building > global 优先级）
- §6.4.4 conflict handling（0 命中 open / 全等 closed / 冲突 blocked）

闭包验证器确定性、无 LLM、无 Neo4j：本模块只吃 `FactPack` DTO，纯 Python。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from evo_agent_baseline.contracts import FactAtom, FactPack

# 默认数值容差（spec §6.4.4：numeric_tolerance 默认 1e-9）。
DEFAULT_NUMERIC_TOLERANCE = 1e-9

# S3 A 侧遮蔽目标（决策门 2026-08-02 显式冻结集合——本轮仅一个槽）。
# 语义：该槽的楼级真值由原生 all_true 聚合唯一权威，查询规则派生的楼级行
# （any_true、带假轴键）遮蔽出判定索引。**扩集合必须重过决策门。**
MASKED_LOOKUP_TARGETS = frozenset({"supervision.record.completed"})

# carrier_type 为 sidecar 行政事实的取值（spec §6.4.1 SidecarEntry 来源）。
_SIDECAR_CARRIER_TYPE = "sidecar_entry"

# ------------------------------------------------------------------ #
# DEBT-083 哨兵边界（codex 裁决分叉一「甲」，2026-08-02）：非判定事实分类器。
#
# 一条事实为「非判定」（兜底哨兵）**当且仅当三条件全满足**：
#   1. `provenance.derived_outcome_group` ∈ 下面四组，且 `value_json` 解析后
#      == 字符串 "not_applicable"；
#   2. 同 `carrier_id` 同 `slot_id` 存在 `derived_outcome_group == "fallback_reasons"`
#      的伴随行（批 I 实证 630 对 630、零孤儿）；
#   3. 伴随行原因码 ∈ `NON_ADJUDICATIVE_REASON_CODES` 冻结集合。
# 值命中条件 1 但条件 2/3 不成立 = 「裸哨兵」——不许猜成不适用，消费面一律
# 缺省拒绝（blocked + schema_contract_violation）。
#
# 🔴 禁全局字符串黑名单（凡值=="not_applicable" 就杀）：邻接通道
# （deficiency_class / 测量占位等，3 槽 24 行）同字符串语义不同、无伴随行，
# 三条件天然不误杀。
#
# 两个常量集合的权威来源（改动必须两处同步核对）：
#   ① 规格 06 §11 逐槽 unknown_policy 表（团队文档/我的笔记/蓝图汇总/
#     W0新版全量实现级设计规格包/06_surrogate公式噪声与unknown策略.md:731-747）；
#   ② 三方对账表（团队文档/我的笔记/DEBT083_哨兵三方对账表_20260802.md §3/§4，
#     批 I 实证词表，含生成器已登记但实证 0 次的 no_assessment / no_scope_target）。
# ------------------------------------------------------------------ #
NON_ADJUDICATIVE_OUTCOME_GROUPS = frozenset({
    "risk_flags", "repair_flags", "verification_flags", "assessment_flags",
})
NON_ADJUDICATIVE_REASON_CODES = frozenset({
    "no_drainage", "no_private_premises", "no_fire_component",
    "no_repair", "no_test", "no_assessment", "no_scope_target",
})
# 哨兵值字面量（批 I 实证四个判定组内唯一非布尔值，对账表 §3）。
NON_ADJUDICATIVE_SENTINEL_VALUE = "not_applicable"
# 分类结果三态。
SENTINEL_NOT = "not_sentinel"
SENTINEL_NON_ADJUDICATIVE = "non_adjudicative"
SENTINEL_BARE = "bare"


# `build_method_canonical_map` **权威源已移至** `evo_agent_baseline.slot_alias_policy`
# （2026-07-27 终审 P2 连带：检索侧 import 它构成 `retrieval → closure` 反向依赖）。
from evo_agent_baseline.slot_alias_policy import build_method_canonical_map  # noqa: F401


class FactIndex:
    """verifier 初始化构建的 fact 索引集合（spec §6.4.1）。

    六个索引：slot_index / measure_index / carrier_index / artifact_index /
    method_index / alias_index。前五个 value 为 `List[FactAtom]`，alias_index
    value 为 canonical key 列表（slot/measure 别名 → canonical）。
    """

    def __init__(
        self,
        fact_pack: FactPack,
        slot_aliases: Optional[Dict[str, str]] = None,
        measure_aliases: Optional[Dict[str, str]] = None,
        method_aliases: Optional[Dict[str, str]] = None,
        numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE,
        component_subsumption: Optional[Dict[str, Any]] = None,
        exclude_explanatory: bool = False,
        mask_lookup_targets: bool = False,
        c55_bucket_value_consumption: bool = False,
    ) -> None:
        self.fact_pack = fact_pack
        self.numeric_tolerance = numeric_tolerance
        # canonicalization 别名表（spec §6.4.2）。
        self.slot_aliases: Dict[str, str] = dict(slot_aliases or {})
        self.measure_aliases: Dict[str, str] = dict(measure_aliases or {})
        # method 维度运行态展开表 {alias→canonical}（DEBT-049 Phase3 U2；由
        # build_method_canonical_map 从 grouped raw 反转全展开而来，非 slot/measure 同形）。
        self.method_aliases: Dict[str, str] = dict(method_aliases or {})
        # 🔴 构件类型涵盖关系（DEBT-076）：来自**人裁**
        # `component_type_relations_v1.json` → 类型格 `subsumption`（父→子集合）。
        # 搭载在 FactIndex 上是因为它**已贯穿全部限定符过滤调用点**，且与别名表同类
        # （都是"权威登记的名字关系"）——比给 7 个调用点逐个加参数干净。
        # **缺省空 ⇒ 严格相等匹配，与改动前逐字节等价。**
        self.component_subsumption: Dict[str, Any] = dict(component_subsumption or {})
        # DEBT-083 第 3 步（2026-08-01，codex 决策门裁定的「事实用途边界分流」，
        # **缺省 False＝行为逐位不变**）：spec 明文 `fallback_reasons` 只解释
        # 未知/不适用、**不得参与满足/违反判定**，而事实包把它展成普通槽事实
        # （`pack_builder.fact_atoms_from_condition_derived_flags` 的 docstring 早写着
        # 这句，只是下游没人执行）。开启后：带
        # `provenance.derived_outcome_group == "fallback_reasons"` 的事实**不进四个
        # 判定绑定索引**（slot/measure/artifact/method），仍留在 `fact_pack.facts`
        # 与 carrier_index（解释面、作用域枚举不受影响）。
        # ⚠️ 不是按来源分组判冲突（决策门明拒——那是替上游遮丑）；是执行规格已
        # 写明的用途边界。分流后判定性通道仍异值必须继续 ambiguous。
        self.exclude_explanatory = bool(exclude_explanatory)
        # S3 A 侧（决策门 2026-08-02，缺省关闭）：查询规则派生的楼级真值行
        # 遮蔽出判定索引（原生 all_true 为唯一权威；两行互斥是结构性歧义源）。
        # 只对 MASKED_LOOKUP_TARGETS 冻结集合内的槽、且六条辨识**全部满足**
        # 才遮；审计面（carrier_index / fact_pack）保留原行。
        self.mask_lookup_targets = bool(mask_lookup_targets)
        # c55 桶通道值消费开关（方案甲缺省关；批配置下发进锚，DEBT-083 先例）。
        # 搭载在 FactIndex 是 mask_lookup_targets 同款理由：贯穿全部求值调用点。
        self.c55_bucket_value_consumption = bool(c55_bucket_value_consumption)

        self.slot_index: Dict[str, List[FactAtom]] = {}
        self.measure_index: Dict[str, List[FactAtom]] = {}
        self.carrier_index: Dict[str, List[FactAtom]] = {}
        # 期限锚索引（期限锚供给案 2026-08-05，决议 §三.1）：世界侧 sidecar duration
        # 行把注册表登记的 `rule_card_threshold.time_anchor_key` 回写进
        # `provenance.time_anchor_key`，闭包据此按**本条 deadline 自己的锚点**取事实。
        # 🔴 为什么必须独立成索引、且优先于 slot/measure 两条老通道：
        #    锚名 `repair.prescribed.{started,completed}` 经别名表归一后指向世界侧
        #    **布尔闸槽** `procedure.repair.prescribed.*`，老通道 `return facts[0]`
        #    不看值类型，必然先命中布尔行 ⇒ 量表通道永不可达 ⇒ 共 156 条期限义务
        #    （603 的 25.9%）任何纯供给动作都救不回（E1 实验 §四墙③全批实测）。
        # 键**不过别名归一**：锚点是卡侧与注册表共用的命名空间，与槽名空间无关，
        # 归一只会把两个空间搅在一起。
        self.time_anchor_index: Dict[str, List[FactAtom]] = {}
        self.artifact_index: Dict[str, List[FactAtom]] = {}
        self.method_index: Dict[str, List[FactAtom]] = {}
        # alias_index：原始 key -> [canonical key]（slot 与 measure 合并存）。
        self.alias_index: Dict[str, List[str]] = {}
        # DEBT-083 哨兵分类器伴随行索引（裁决分叉一条件 2/3）：
        # (carrier_id, slot_id) → [fallback_reasons 伴随行的原因码]。键用**原始**
        # slot_id（哨兵行与伴随行同 key 展出，命名关系见对账表），不做别名归一。
        # 无条件构建（便宜）；分类判定在 `classify_sentinel` 里受开关门控。
        self._fallback_reasons_by_carrier_slot: Dict[Any, List[str]] = {}

        self._build()

    # ------------------------------------------------------------------ #
    # §6.4.1 索引构建
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        """把 FactPack.facts 全部展进六索引。"""
        for orig, canon in self.slot_aliases.items():
            self.alias_index.setdefault(orig, [])
            if canon not in self.alias_index[orig]:
                self.alias_index[orig].append(canon)
        for orig, canon in self.measure_aliases.items():
            self.alias_index.setdefault(orig, [])
            if canon not in self.alias_index[orig]:
                self.alias_index[orig].append(canon)

        for fact in self.fact_pack.facts:
            # 解释性事实分流（DEBT-083 第 3 步，缺省关闭）：不进判定绑定索引，
            # 但 carrier_index 照常（见 __init__ 注释）。
            _explanatory = (
                self.exclude_explanatory
                and (fact.provenance or {}).get("derived_outcome_group")
                == "fallback_reasons"
            )
            # S3 A 侧遮蔽（六条全须满足；禁用假轴/编号格式当判据——裁决原文）。
            _masked = (
                self.mask_lookup_targets
                and fact.slot_id
                and self.canonical_slot(fact.slot_id) in MASKED_LOOKUP_TARGETS
                and (fact.provenance or {}).get("derivation")
                == "slot_target_lookup_rule"
                and (fact.provenance or {}).get("slot_target") == fact.slot_id
                and (fact.qualifiers or {}).get("aggregation") == "building"
                and (fact.provenance or {}).get("carrier_label") == "Building"
            )
            # slot 索引（按 canonical slot_id 归并）。
            if fact.slot_id and not _explanatory and not _masked:
                key = self.canonical_slot(fact.slot_id)
                self.slot_index.setdefault(key, []).append(fact)
                # artifact.* slot 同时进 artifact_index（spec §6.4.1）。
                if key.startswith("artifact."):
                    self.artifact_index.setdefault(key, []).append(fact)
            # measure 索引（按 canonical measure_key 归并）。
            if fact.measure_key and not _explanatory:
                key = self.canonical_measure(fact.measure_key)
                self.measure_index.setdefault(key, []).append(fact)
            # carrier 索引。（解释性事实**保留**——作用域枚举/解释面不受分流影响。）
            if fact.carrier_id:
                self.carrier_index.setdefault(fact.carrier_id, []).append(fact)
            # 期限锚索引（见 __init__ 注释）。解释性事实照 slot/measure 同款分流，
            # 不做载体过滤——过滤会在载体形态变化时**静默丢行**，而丢行的表征
            # （落 missing_time_anchor）与"世界没供"不可区分。
            _anchor = (fact.provenance or {}).get("time_anchor_key")
            if _anchor and not _explanatory:
                self.time_anchor_index.setdefault(str(_anchor), []).append(fact)
            # method 索引：qualifiers.method_class 按 canonical_method 归一后建键
            # （DEBT-049 Phase3 U2 事实端 method_class 落点；一处归一，node-main /
            # method-obligation 两消费点 key∈allowed 求交自动对齐）。四方法暗部署下
            # 展开表纯 identity → 键与归一前逐字一致（现网零漂移）。
            method_class = fact.qualifiers.get("method_class")
            if method_class is not None and not _explanatory:
                key = self.canonical_method(str(method_class))
                self.method_index.setdefault(key, []).append(fact)
            # 哨兵伴随行登记（DEBT-083 甲条件 2/3）：fallback_reasons 组的事实
            # 值即原因码，按 (carrier_id, slot_id) 归键；只收字符串值。
            if (fact.provenance or {}).get("derived_outcome_group") == "fallback_reasons":
                _reason = parse_value(fact.value_json)
                if isinstance(_reason, str) and _reason:
                    self._fallback_reasons_by_carrier_slot.setdefault(
                        (fact.carrier_id, fact.slot_id), []
                    ).append(_reason)

    # ------------------------------------------------------------------ #
    # DEBT-083 哨兵分类（裁决分叉一「甲」；挂 exclude_explanatory 既有开关，
    # 缺省 False ⇒ 恒返回 SENTINEL_NOT，行为逐位不变）
    # ------------------------------------------------------------------ #
    def classify_sentinel(self, fact: FactAtom) -> Tuple[str, Optional[str]]:
        """对单条事实做哨兵三态分类。

        返回 (kind, reason)：
        - `(SENTINEL_NOT, None)`：非哨兵（正常判定通道事实，照原路径求值）；
        - `(SENTINEL_NON_ADJUDICATIVE, <原因码>)`：三条件全满足的非判定事实——
          消费面应产 `closed + not_applicable`（生产者已明示"不适用"，非缺事实）；
        - `(SENTINEL_BARE, None)`：裸哨兵——值命中条件 1 但无伴随行、或伴随行
          原因码不在冻结集合。缺省拒绝，**不许猜成不适用**。
        """
        if not self.exclude_explanatory:
            return (SENTINEL_NOT, None)
        prov = fact.provenance or {}
        if prov.get("derived_outcome_group") not in NON_ADJUDICATIVE_OUTCOME_GROUPS:
            return (SENTINEL_NOT, None)
        if parse_value(fact.value_json) != NON_ADJUDICATIVE_SENTINEL_VALUE:
            return (SENTINEL_NOT, None)
        reasons = self._fallback_reasons_by_carrier_slot.get(
            (fact.carrier_id, fact.slot_id), []
        )
        valid = sorted(r for r in reasons if r in NON_ADJUDICATIVE_REASON_CODES)
        if valid:
            return (SENTINEL_NON_ADJUDICATIVE, valid[0])
        return (SENTINEL_BARE, None)

    # ------------------------------------------------------------------ #
    # §6.4.2 canonicalization
    # ------------------------------------------------------------------ #
    def canonical_slot(self, slot_id: str) -> str:
        """slot_id 别名归一（spec §6.4.2 canonical_slot）。"""
        return self.slot_aliases.get(slot_id, slot_id)

    def canonical_measure(self, measure_key: str) -> str:
        """measure_key 别名归一（spec §6.4.2 canonical_measure）。"""
        return self.measure_aliases.get(measure_key, measure_key)

    def canonical_method(self, method_class: str) -> str:
        """method_class 别名归一（DEBT-049 Phase3 U2；镜像 canonical_slot/measure 的
        ``.get(x, x)`` 兜底）。别名表为运行态展开表 ``{alias→canonical}``（含 identity 自
        映射）。四方法暗部署下纯 identity → 恒返回入参。"""
        return self.method_aliases.get(method_class, method_class)

    # ------------------------------------------------------------------ #
    # §6.4.3 target scoping —— 候选事实按 carrier 粒度排序
    # ------------------------------------------------------------------ #
    def scope_rank(
        self,
        fact: FactAtom,
        fragment_id: Optional[str] = None,
        component_id: Optional[str] = None,
    ) -> int:
        """target scoping 优先级 rank（spec §6.4.3，越小越优先）。

        1. fragment-specific fact
        2. component-specific fact for fragment.component_id
        3. building 载体事实（楼级主事实/聚合读数——spec 草案·流程槽粒度语义
           2026-07-08：楼级作用域下 building 载体优先于 sidecar_entry，聚合
           读数才不会与 fragment 戳的 sidecar 行混绑判 ambiguous）
        4. building/world-level sidecar fact
        5. global rule fact
        """
        carrier_type = fact.carrier_type
        # 1. fragment 专属。
        if fragment_id and (
            fact.carrier_id == fragment_id
            or fact.target_ref == fragment_id
            or carrier_type == "fragment"
        ):
            if fact.carrier_id == fragment_id or fact.target_ref == fragment_id:
                return 1
        # 2. component 专属。
        if component_id and (
            fact.carrier_id == component_id
            or fact.target_ref == component_id
            or carrier_type == "component"
        ):
            if fact.carrier_id == component_id or fact.target_ref == component_id:
                return 2
        # 3. building 载体（楼级主事实/聚合读数）先于 sidecar。
        if carrier_type == "building":
            return 3
        # 4. building / world-level sidecar。
        if carrier_type == _SIDECAR_CARRIER_TYPE:
            return 4
        # 5. 其余全局 / 兜底。
        return 5

    def scoped_facts(
        self,
        facts: List[FactAtom],
        fragment_id: Optional[str] = None,
        component_id: Optional[str] = None,
    ) -> List[FactAtom]:
        """对一组候选 fact 做 target scoping：取 rank 最小的一组。

        若有 fragment 专属事实，只回该组；否则逐级降级。返回的列表交给
        §6.4.4 conflict_status 判 0/1/N 命中。
        """
        if not facts:
            return []
        ranked = [
            (self.scope_rank(f, fragment_id, component_id), f) for f in facts
        ]
        best = min(r for r, _ in ranked)
        return [f for r, f in ranked if r == best]


# ====================================================================== #
# §6.4.2 JSON canonicalization & 值解析
# ====================================================================== #
def canonical_json(value: Any) -> str:
    """对象 key 排序、去空白的 canonical JSON 串（spec §6.4.2）。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_value(value_json: Optional[str]) -> Any:
    """把 FactAtom.value_json 解析为 Python 值。

    value_json 是 canonical JSON 串。None / 空串 视为 None。
    解析失败时退化为原始字符串（容错，不抛）。
    """
    if value_json is None:
        return None
    if isinstance(value_json, (int, float, bool, dict, list)):
        return value_json
    s = str(value_json).strip()
    if s == "" or s.lower() == "null":
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


def parse_json_number(value_json: Optional[str]) -> Optional[float]:
    """把 value_json 解析为数值（spec §6.3.5 parse_json_number）。

    无法解析为 number 时返回 None。
    """
    v = parse_value(value_json)
    if isinstance(v, bool):
        # bool 是 int 子类，但语义上不是数值阈值输入，拒绝。
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def values_equivalent(
    a: Any, b: Any, numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE
) -> bool:
    """两个解析后的值是否等价（spec §6.4.4 equivalent 规则）。

    - numeric：差值小于 numeric_tolerance
    - bool / string：完全相等
    - object / list：canonical JSON 相等
    """
    a_num = a if isinstance(a, (int, float)) and not isinstance(a, bool) else None
    b_num = b if isinstance(b, (int, float)) and not isinstance(b, bool) else None
    if a_num is not None and b_num is not None:
        return abs(a_num - b_num) < numeric_tolerance
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return canonical_json(a) == canonical_json(b)
    return a == b


def facts_value_consistent(
    facts: List[FactAtom], numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE
) -> bool:
    """一组 fact 的 value 是否全部互相等价（spec §6.4.4）。"""
    if len(facts) <= 1:
        return True
    parsed = [parse_value(f.value_json) for f in facts]
    first = parsed[0]
    return all(values_equivalent(first, v, numeric_tolerance) for v in parsed[1:])


def bound_sentinel_classification(
    facts: List[FactAtom], fact_index: "FactIndex"
) -> Tuple[str, Optional[str]]:
    """对一组**值一致**的绑定事实做哨兵分类的保守归并（DEBT-083 甲消费面入口）。

    归并规则（宁严勿宽）：
    - 任一条判 `SENTINEL_BARE` ⇒ 整组 bare（存在契约异常，缺省拒绝）；
    - 全部判 `SENTINEL_NON_ADJUDICATIVE` ⇒ 整组非判定，原因码取排序后首个
      （同组值一致，正常情形伴随行同源同码）；
    - 其余（含混有正常判定通道事实）⇒ `SENTINEL_NOT`，整组走原求值路径——
      邻接通道的合法枚举值绝不被哨兵逻辑波及。
    """
    reasons: List[str] = []
    for f in facts:
        kind, reason = fact_index.classify_sentinel(f)
        if kind == SENTINEL_BARE:
            return (SENTINEL_BARE, None)
        if kind != SENTINEL_NON_ADJUDICATIVE:
            return (SENTINEL_NOT, None)
        reasons.append(reason or "")
    if reasons:
        return (SENTINEL_NON_ADJUDICATIVE, sorted(reasons)[0])
    return (SENTINEL_NOT, None)


def conflict_status(
    facts: List[FactAtom], numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE
) -> str:
    """conflict handling 三态（spec §6.4.4）。

    - 0 命中 → "missing"
    - 全部值等价 → "consistent"
    - 值冲突 → "ambiguous"
    """
    if len(facts) == 0:
        return "missing"
    if facts_value_consistent(facts, numeric_tolerance):
        return "consistent"
    return "ambiguous"


def sentinel_registry_digest() -> str:
    """哨兵登记三冻结常量的 canonical sha256（DEBT-083 开关转正常开启落地②）。

    批清单 `fallback_boundary.sentinel_registry_digest` 的唯一计算点——批驱动
    import 本函数，不许在驱动里重算逻辑。集合无序，先排序再 canonical JSON，
    保证跨进程/跨机器确定性；任一常量内容变动 → digest 变动 → 劈锚可检出。
    """
    payload = {
        "non_adjudicative_outcome_groups": sorted(NON_ADJUDICATIVE_OUTCOME_GROUPS),
        "non_adjudicative_reason_codes": sorted(NON_ADJUDICATIVE_REASON_CODES),
        "non_adjudicative_sentinel_value": NON_ADJUDICATIVE_SENTINEL_VALUE,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "FactIndex",
    "DEFAULT_NUMERIC_TOLERANCE",
    "canonical_json",
    "parse_value",
    "parse_json_number",
    "values_equivalent",
    "facts_value_consistent",
    "conflict_status",
    # DEBT-083 哨兵边界（甲）
    "NON_ADJUDICATIVE_OUTCOME_GROUPS",
    "NON_ADJUDICATIVE_REASON_CODES",
    "NON_ADJUDICATIVE_SENTINEL_VALUE",
    "SENTINEL_NOT",
    "SENTINEL_NON_ADJUDICATIVE",
    "SENTINEL_BARE",
    "bound_sentinel_classification",
    "sentinel_registry_digest",
]
