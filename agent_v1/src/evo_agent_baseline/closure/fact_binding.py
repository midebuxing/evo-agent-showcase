"""Fact binding —— fact 索引、canonicalization、target scoping、冲突处理。

实现 spec §6.4 全部：
- §6.4.1 fact indexes（slot/measure/carrier/artifact/method/alias 六索引）
- §6.4.2 canonicalization（slot/measure 别名归一、JSON canonical、数值容差）
- §6.4.3 target scoping（fragment > component > building > global 优先级）
- §6.4.4 conflict handling（0 命中 open / 全等 closed / 冲突 blocked）

闭包验证器确定性、无 LLM、无 Neo4j：本模块只吃 `FactPack` DTO，纯 Python。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from evo_agent_baseline.contracts import FactAtom, FactPack

# 默认数值容差（spec §6.4.4：numeric_tolerance 默认 1e-9）。
DEFAULT_NUMERIC_TOLERANCE = 1e-9

# carrier_type 为 sidecar 行政事实的取值（spec §6.4.1 SidecarEntry 来源）。
_SIDECAR_CARRIER_TYPE = "sidecar_entry"


def build_method_canonical_map(method_aliases: Any) -> Dict[str, str]:
    """method 别名 grouped raw ``{canonical: [alias, ...]}`` → 运行态展开表 ``{alias: canonical}``。

    DEBT-049 Phase3 U2（链②别名传输）。method 维度 canonical 落 **key 侧**（卡端 CoP
    词，如 ``cctv_survey``），与 slot/measure 别名（canonical 落 value 侧）**方向相反**——
    故 **不能复用** closure 的 ``_normalize_alias_map``（那取列表首项 + 方向 ``{key→首项}``：
    对 grouped raw 会把 canonical 映到某别名并丢弃其余别名）。本建表器做**反转 + 全展开**：

    - identity 自映射：``canonical → canonical``（保 ``canonical_method(x)=表.get(x,x)`` 下
      canonical 自身亦命中）；
    - 每 canonical 的每 alias：``alias → canonical``；
    - ``_`` 前缀键（``_note`` 等注释）跳过。

    例：``{"cctv_survey": ["drainage_cctv", "CCTV"]}`` →
    ``{"cctv_survey": "cctv_survey", "drainage_cctv": "cctv_survey", "CCTV": "cctv_survey"}``。
    四方法暗部署 ``{"air_test": [], ...}`` → 纯 identity ``{"air_test": "air_test", ...}``。
    """
    out: Dict[str, str] = {}
    if not isinstance(method_aliases, dict):
        return out
    for canonical, aliases in method_aliases.items():
        if not isinstance(canonical, str) or not canonical or canonical.startswith("_"):
            continue
        out[canonical] = canonical  # identity 自映射
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias:
                    out[alias] = canonical
    return out


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
    ) -> None:
        self.fact_pack = fact_pack
        self.numeric_tolerance = numeric_tolerance
        # canonicalization 别名表（spec §6.4.2）。
        self.slot_aliases: Dict[str, str] = dict(slot_aliases or {})
        self.measure_aliases: Dict[str, str] = dict(measure_aliases or {})
        # method 维度运行态展开表 {alias→canonical}（DEBT-049 Phase3 U2；由
        # build_method_canonical_map 从 grouped raw 反转全展开而来，非 slot/measure 同形）。
        self.method_aliases: Dict[str, str] = dict(method_aliases or {})

        self.slot_index: Dict[str, List[FactAtom]] = {}
        self.measure_index: Dict[str, List[FactAtom]] = {}
        self.carrier_index: Dict[str, List[FactAtom]] = {}
        self.artifact_index: Dict[str, List[FactAtom]] = {}
        self.method_index: Dict[str, List[FactAtom]] = {}
        # alias_index：原始 key -> [canonical key]（slot 与 measure 合并存）。
        self.alias_index: Dict[str, List[str]] = {}

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
            # slot 索引（按 canonical slot_id 归并）。
            if fact.slot_id:
                key = self.canonical_slot(fact.slot_id)
                self.slot_index.setdefault(key, []).append(fact)
                # artifact.* slot 同时进 artifact_index（spec §6.4.1）。
                if key.startswith("artifact."):
                    self.artifact_index.setdefault(key, []).append(fact)
            # measure 索引（按 canonical measure_key 归并）。
            if fact.measure_key:
                key = self.canonical_measure(fact.measure_key)
                self.measure_index.setdefault(key, []).append(fact)
            # carrier 索引。
            if fact.carrier_id:
                self.carrier_index.setdefault(fact.carrier_id, []).append(fact)
            # method 索引：qualifiers.method_class 按 canonical_method 归一后建键
            # （DEBT-049 Phase3 U2 事实端 method_class 落点；一处归一，node-main /
            # method-obligation 两消费点 key∈allowed 求交自动对齐）。四方法暗部署下
            # 展开表纯 identity → 键与归一前逐字一致（现网零漂移）。
            method_class = fact.qualifiers.get("method_class")
            if method_class is not None:
                key = self.canonical_method(str(method_class))
                self.method_index.setdefault(key, []).append(fact)

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


__all__ = [
    "FactIndex",
    "DEFAULT_NUMERIC_TOLERANCE",
    "canonical_json",
    "parse_value",
    "parse_json_number",
    "values_equivalent",
    "facts_value_consistent",
    "conflict_status",
]
