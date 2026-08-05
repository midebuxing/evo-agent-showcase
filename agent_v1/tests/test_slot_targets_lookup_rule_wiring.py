"""slot_targets「登记—传输—消费」全链门（2026-07-27，DEBT 接线修复验收）。

背景：`kg/queries.py:FACT_SLOT_TARGETS` 取 `ProjectionRuntimeMapping.slot_targets_json`，
而 loader 曾从未写该属性 → 查询恒 null → `derive_slot_target_lookup_rule_facts`
空转且不报错。本测试防「生产者写了属性就收工」：四个集合必须完全相等——

    源集合   = 真实卡包 projection_runtime_mapping_v1.json 的 slot_targets 键
    加载器   = build_registry_graph 产出的节点属性 slot_targets_json 解析后的键
    传输     = 经 FACT_SLOT_TARGETS 查询行带回并解析后的键（桩库模拟，键名对齐）
    消费方   = retrieve_fact_pack 实际传给 derive_slot_target_lookup_rule_facts 的键

任何一环静默空表 / 静默删除 / 数量不一致，测试必须失败。

离线可证：上四环。必须等重灌 Neo4j 才能证：活体库节点真带该属性（Cypher 对库）。
"""

import json
from pathlib import Path

from evo_agent_baseline.contracts import FactAtom
from evo_agent_baseline.ingest.guard import AuditLog
from evo_agent_baseline.ingest.rulecard_loader import build_registry_graph
from evo_agent_baseline.kg import queries
from evo_agent_baseline.retrieval import fact_retriever

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULECARD_DIR = PROJECT_ROOT / "regulations" / "rulecard_v2" / "mbis_cop_2023"

# 4 条带 lookup_rule（S3 删 supervision 行后） 里语义最硬的一条（合取双子句，防简化成单项别名）。
_TARGET = "procedure.investigation.detailed.started"
_CLAUSE_SLOTS = ("procedure.investigation.started", "artifact.proposal.detailed_investigation")


def _source_slot_targets():
    doc = json.loads(
        (RULECARD_DIR / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8")
    )
    return {
        k: v for k, v in (doc.get("slot_targets") or {}).items() if not k.startswith("_")
    }


def _loader_slot_targets_json() -> str:
    batch = build_registry_graph(RULECARD_DIR, AuditLog())
    nodes = [n for n in batch.nodes if n.label == "ProjectionRuntimeMapping"]
    assert len(nodes) == 1, "加载器应产出恰好一个 ProjectionRuntimeMapping 节点"
    prop = nodes[0].props.get("slot_targets_json")
    assert prop, "加载器未写 slot_targets_json 属性（或为空串）"
    return prop


class _StubClient:
    """最小 KG 桩：FACT_SLOT_TARGETS 返回加载器属性值，其余查询一律空行。"""

    def __init__(self, slot_targets_json: str):
        self._slot_targets_json = slot_targets_json

    def read(self, query, params=None):
        if query == queries.FACT_SLOT_TARGETS:
            return [{"slot_targets_json": self._slot_targets_json}]
        return []


def _atom(slot_id: str, value: bool, building_id: str = "B1") -> FactAtom:
    return FactAtom(
        fact_id=f"{building_id}::{slot_id}",
        world_id="W",
        building_id=building_id,
        carrier_type="building",
        carrier_id=building_id,
        target_ref=None,
        slot_id=slot_id,
        measure_key=None,
        value_json="true" if value else "false",
        value_type="boolean",
        unit=None,
        qualifiers={},
        source_path="sidecar_entries.parquet",
        source_node_id=f"{building_id}::{slot_id}",
        provenance={},
    )


def test_slot_targets_full_chain_gate(monkeypatch):
    # 源集合（真实卡包：27 条登记，其中 4 条带 lookup_rule（S3 删 supervision 行后））。
    source = _source_slot_targets()
    source_keys = set(source)
    assert len(source_keys) == 27, f"卡包 slot_targets 条数漂移: {len(source_keys)}"
    lookup_keys = {
        k for k, v in source.items() if isinstance(v, dict) and v.get("lookup_rule")
    }
    assert len(lookup_keys) == 4, (   # S3 B 侧（2026-08-02）删 supervision 行：5→4
        f"lookup_rule 条数漂移: {sorted(lookup_keys)}")

    # 加载器集合。
    prop = _loader_slot_targets_json()
    loader_keys = set(json.loads(prop))

    # 传输集合（桩库经真实查询常量带回的行；键名/属性名对齐在此证）。
    rows = _StubClient(prop).read(queries.FACT_SLOT_TARGETS)
    assert rows and rows[0].get("slot_targets_json"), "传输环静默空表"
    transport_keys = set(json.loads(rows[0]["slot_targets_json"]))

    # 消费方集合：桩库跑真实 retrieve_fact_pack，间谍捕获消费函数实参。
    captured = {}
    real_derive = fact_retriever.derive_slot_target_lookup_rule_facts

    def _spy(facts, slot_targets, requested_qualifiers, world_id, building_id, **_kw):
        captured["slot_targets"] = slot_targets
        return real_derive(facts, slot_targets, requested_qualifiers, world_id, building_id)

    monkeypatch.setattr(fact_retriever, "derive_slot_target_lookup_rule_facts", _spy)
    fact_retriever.retrieve_fact_pack(_StubClient(prop), run_id="R", building_id="B1")
    assert captured, "retrieve_fact_pack 从未到达消费函数（slot_targets 静默缺席）"
    consumer_keys = set(captured["slot_targets"])

    # 四环完全相等——任何一环静默空表/删除/数量漂移即在此失败。
    assert source_keys == loader_keys == transport_keys == consumer_keys, (
        f"全链键集合不一致: 源{len(source_keys)} / 加载器{len(loader_keys)} / "
        f"传输{len(transport_keys)} / 消费方{len(consumer_keys)}; "
        f"差集: {source_keys ^ consumer_keys}"
    )


def test_consumer_actually_derives_from_transported_table():
    """消费方不只是「收到」表：真实 lookup_rule 表 + 合成事实须真派生（双极）。"""
    slot_targets = _source_slot_targets()
    derived_true = fact_retriever.derive_slot_target_lookup_rule_facts(
        [_atom(s, True) for s in _CLAUSE_SLOTS], slot_targets, {}, "W", "B1",
    )
    hits = [f for f in derived_true if f.slot_id == _TARGET]
    assert hits and all(f.value_json == "true" for f in hits), (
        "双子句皆 true 应派生 true（防合取被简化成单项别名）"
    )
    derived_false = fact_retriever.derive_slot_target_lookup_rule_facts(
        [_atom(_CLAUSE_SLOTS[0], True), _atom(_CLAUSE_SLOTS[1], False)],
        slot_targets, {}, "W", "B1",
    )
    misses = [f for f in derived_false if f.slot_id == _TARGET]
    assert misses and all(f.value_json == "false" for f in misses), (
        "一子句 false 且全可判应派生 false（封闭世界双极）"
    )


def test_missing_property_fails_closed(monkeypatch):
    """反向锁：属性缺席时消费方拿到空表 → 全链门恒失败（证明门不是摆设）。"""
    captured = {}
    real_derive = fact_retriever.derive_slot_target_lookup_rule_facts

    def _spy(facts, slot_targets, requested_qualifiers, world_id, building_id, **_kw):
        captured["slot_targets"] = slot_targets
        return real_derive(facts, slot_targets, requested_qualifiers, world_id, building_id)

    monkeypatch.setattr(fact_retriever, "derive_slot_target_lookup_rule_facts", _spy)
    fact_retriever.retrieve_fact_pack(_StubClient(""), run_id="R", building_id="B1")
    # 空串属性 → 消费函数不被调用或拿到空表；两者都必须与源集合不等。
    assert set(captured.get("slot_targets", {})) != set(_source_slot_targets())


# ===========================================================================
# 2026-07-27 codex 审核门 P1-C：`requested_qualifiers` 全链接线
#
# 修前形态：`retrieve_fact_pack` **固定传 `{}`**，`harvest_slot_target_requested_
# qualifiers` 写好了、导出了，全仓只有测试在调（第九个「登记了没接线」）。
# 本节锁的是「生产路径**真的调用了**采集结果、且结果**到达求值器**」——
# 不是「函数存在」，也不是「源码里出现过函数名」。
# ===========================================================================

_ACTOR_TARGET = "actor.representative.qualified_for_assigned_role"


def _source_requested_qualifiers():
    """源集合：直接对**真实卡包** rule_cards.json 跑采集函数。"""
    doc = json.loads((RULECARD_DIR / "rule_cards.json").read_text(encoding="utf-8"))
    return fact_retriever.harvest_slot_target_requested_qualifiers(doc)


class _StubClient2:
    """两张表都答的桩：slot_targets + requested_qualifiers（其余查询空行）。"""

    def __init__(self, slot_targets_json: str, requested_json: str):
        self._st = slot_targets_json
        self._rq = requested_json

    def read(self, query, params=None):
        if query == queries.FACT_SLOT_TARGETS:
            return [{"slot_targets_json": self._st}]
        if query == queries.FACT_SLOT_TARGET_REQUESTED_QUALIFIERS:
            return [{"slot_target_requested_qualifiers_json": self._rq}]
        return []


def _loader_props():
    batch = build_registry_graph(RULECARD_DIR, AuditLog())
    nodes = [n for n in batch.nodes if n.label == "ProjectionRuntimeMapping"]
    assert len(nodes) == 1
    return nodes[0].props


def test_requested_qualifiers_full_chain_reaches_evaluator(monkeypatch):
    """🔴 四环相等 + 求值器实参非空：源 → 加载器属性 → 查询运输 → 消费函数实参。

    修前失败：消费函数收到的是 `{}`（写死），与源集合（真实卡包 45 个槽）不等。
    """
    source = _source_requested_qualifiers()
    assert source, "采集函数对真实卡包返回空表 —— 源环就断了"

    props = _loader_props()
    prop = props.get("slot_target_requested_qualifiers_json")
    assert prop, "加载器未写 slot_target_requested_qualifiers_json 属性"
    loader = json.loads(prop)

    rows = _StubClient2(props["slot_targets_json"], prop).read(
        queries.FACT_SLOT_TARGET_REQUESTED_QUALIFIERS)
    transport = json.loads(rows[0]["slot_target_requested_qualifiers_json"])

    captured = {}
    real_derive = fact_retriever.derive_slot_target_lookup_rule_facts

    def _spy(facts, slot_targets, requested_qualifiers, world_id, building_id, **_kw):
        captured["rq"] = requested_qualifiers
        return real_derive(facts, slot_targets, requested_qualifiers, world_id, building_id)

    monkeypatch.setattr(fact_retriever, "derive_slot_target_lookup_rule_facts", _spy)
    fact_retriever.retrieve_fact_pack(
        _StubClient2(props["slot_targets_json"], prop), run_id="R", building_id="B1")
    assert "rq" in captured, "retrieve_fact_pack 从未到达消费函数"
    consumer = captured["rq"]
    assert consumer, "🔴 消费函数收到空表 —— 生产路径仍写死 {}（P1-C 回退）"
    assert source == loader == transport == consumer, (
        f"全链不一致：源{len(source)} / 加载器{len(loader)} / "
        f"运输{len(transport)} / 消费方{len(consumer)}")


def test_requested_qualifiers_absent_property_degrades_to_empty(monkeypatch):
    """反向锁：属性缺席 → 消费方拿到空表（暗部署语义），且**不抛异常**。

    证明上一条不是"恒真断言"：同一条链在属性缺席时确实会退成 {}。
    """
    props = _loader_props()
    captured = {}
    real_derive = fact_retriever.derive_slot_target_lookup_rule_facts

    def _spy(facts, slot_targets, requested_qualifiers, world_id, building_id, **_kw):
        captured["rq"] = requested_qualifiers
        return real_derive(facts, slot_targets, requested_qualifiers, world_id, building_id)

    monkeypatch.setattr(fact_retriever, "derive_slot_target_lookup_rule_facts", _spy)
    fact_retriever.retrieve_fact_pack(
        _StubClient(props["slot_targets_json"]), run_id="R", building_id="B1")
    assert captured.get("rq") == {}


def test_wiring_changes_derivation_on_real_lookup_table():
    """接线必须**真的改变派生结果**——否则"接通了"只是形式。

    真实 slot_targets + 真实采集表 + 合成事实：形态一目标槽在传 `{}` 时因
    「直接事实优先」对空组合恒命中而 0 派生；S3 B 侧删行后，本槽传真实组合
    也**必须 0 派生**（断言已反转，见下）。
    """
    st = _source_slot_targets()
    rq = _source_requested_qualifiers()
    target = "supervision.record.completed"
    facts = [_atom("supervision.record.completed_and_retained", True),
             _atom(target, True)]          # 该槽已有一条直接（无限定符）事实

    empty = [f for f in fact_retriever.derive_slot_target_lookup_rule_facts(
        facts, st, {}, "W", "B1") if f.slot_id == target]
    assert empty == [], "传 {} 时本应 0 派生（直接事实优先吃掉空组合）"

    wired = [f for f in fact_retriever.derive_slot_target_lookup_rule_facts(
        facts, st, rq, "W", "B1") if f.slot_id == target]
    # S3 B 侧（决策门 2026-08-02）：supervision 槽 lookup_rule 已删——
    # 原生 all_true 为楼级唯一权威，any_true 查询派生（带假轴键）正是被裁掉的
    # 病灶。本断言由「接通后必须派生」**反转为「派生必须为 0」**（新批验收）。
    assert wired == [], f"该槽 lookup_rule 已删，派生必须为 0: {len(wired)}"


def test_actor_role_vocabularies_are_disjoint_so_target_stays_empty():
    """🔴 诚实边界：接通 ≠ 会产出事实。

    `actor.representative.qualified_for_assigned_role` 的形态二子句查 `qual.actor_role`；
    卡侧请求的是**代表等级**（ri_rep_lvl1/lvl2），世界侧只有 4 类**行为者类型**
    （registered_inspector / registered_contractor / owner / building_authority）。
    两个词表结构上不相交 ⇒ containment 永不命中 ⇒ 派生 0 条。
    这是**卡包 authoring 问题**，不是接线问题。

    钉成显式断言的用意：将来卡改对了（或世界侧补了等级值），本测试会**失败并告诉
    你原因**，而不是让"0 条"继续被当成正常。
    """
    st = _source_slot_targets()
    rq = _source_requested_qualifiers()
    card_side = {v for combo in rq[_ACTOR_TARGET] for v in [combo.get("actor_role_key")]}
    world_side = {"registered_inspector", "registered_contractor",
                  "owner", "building_authority"}   # 真实批 30 栋实测取值全集
    assert card_side == {"ri_rep_lvl1", "ri_rep_lvl2"}, card_side
    assert not (card_side & world_side), (
        "卡侧与世界侧 actor_role 词表开始相交了 —— 上面那句「结构上不相交」已过期，"
        "请重测本目标槽的派生量并更新结论")

    facts = [_atom("procedure.supervision_team.submitted", True)]
    facts.append(_atom("qual.actor_role", True))
    facts[-1] = facts[-1].model_copy(update={
        "value_json": json.dumps(sorted(world_side)), "value_type": "array"})
    derived = [f for f in fact_retriever.derive_slot_target_lookup_rule_facts(
        facts, st, rq, "W", "B1") if f.slot_id == _ACTOR_TARGET]
    assert derived == [], (
        "词表不相交却派生出了事实 —— 形态二 containment 语义被放松了")


def test_lookup_rule_alias_table_is_actually_non_empty() -> None:
    """🔴 回归闸：`lookup_rule` 派生用的别名表必须**真的非空**。

    2026-07-27 codex 二审实测抓出：`slot_aliases_from_policy` 收的是
    **`retrieval_policy` 那层包裹结构**，而调用处喂的是**裸别名表**
    ⇒ 15 条变 **0 条**、`_canon_slot` 恒等 ⇒ **整个归一修复静默失效**。

    失效表现是「恒空」而不是报错——单测若只断言"函数能跑通"照样全绿。
    故这里直接拿**真实卡包**的别名表走**真实解析链**，断言条数与卡包一致。
    """
    import json
    import pathlib

    from evo_agent_baseline.slot_alias_policy import slot_aliases_from_policy

    pack = (pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2"
            / "mbis_cop_2023" / "projection_runtime_mapping_v1.json")
    raw = json.loads(pack.read_text(encoding="utf-8"))["slot_aliases"]
    assert raw, "卡包 slot_aliases 为空——本闸失去意义，先查卡包"

    # 裸表直喂（错误形状）必须是空的——证明这道闸测的是真问题，不是摆设。
    assert not slot_aliases_from_policy(raw), (
        "裸别名表直喂居然非空？`slot_aliases_from_policy` 的入参契约变了，本闸需重写"
    )
    # 正确形状必须拿到全部条目。
    wrapped = slot_aliases_from_policy({"slot_aliases": raw})
    assert len(wrapped) == len(raw), (
        f"包裹后条数 {len(wrapped)} != 卡包 {len(raw)}——解析链丢条目"
    )
