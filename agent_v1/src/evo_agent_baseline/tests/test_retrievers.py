"""Fact / Rule KG-RAG 检索器测试（spec §5.3 + §5.4）。

不依赖 Neo4j：用 FakeNeo4jClient 喂预置查询结果，验证检索编排、
§5.4.4 排序打分、verifier 候选集选取、FactPack / RuleSlice 装配。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List

from evo_agent_baseline.contracts import FactPack, RuleSlice
from evo_agent_baseline.kg import queries
from evo_agent_baseline.retrieval import fact_retriever, rule_retriever
from evo_agent_baseline.retrieval.rule_retriever import CandidateSignals


class FakeNeo4jClient:
    """假 Neo4j 客户端：按 Cypher 字符串匹配返回预置结果。

    不连真实 Neo4j；只供检索器单测用。
    """

    def __init__(self, responses: Dict[str, List[Dict[str, Any]]]) -> None:
        """responses: Cypher 查询字符串 → 结果 record dict 列表。"""
        self._responses = responses

    def read(self, cypher: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """返回该 Cypher 的预置结果，未注册的返回空列表。"""
        return self._responses.get(cypher, [])


# ===========================================================================
# §5.4.4 排序打分
# ===========================================================================
def test_candidate_signals_score_formula() -> None:
    """CandidateSignals.score 严格按 §5.4.4 公式。"""
    sig = CandidateSignals(
        rule_card_id="rc.1",
        exact_slot_hit_count=2,            # 2 * 5.0 = 10
        exact_measure_hit_count=1,         # 1 * 4.0 = 4
        applicability_match_count=1,       # 1 * 2.0 = 2
        source_clause_fulltext_score=2.0,  # 2.0 * 1.5 = 3
        neighbor_family_hit_count=1,       # 1 * 1.0 = 1
        explicit_exclusion_match_count=1,  # 1 * -3.0 = -3
    )
    assert sig.score() == 10 + 4 + 2 + 3 + 1 - 3


def test_rank_candidates_descending() -> None:
    """rank_candidates 按分数降序、同分按 id 升序。"""
    signals = {
        "rc.b": CandidateSignals("rc.b", exact_slot_hit_count=1),  # 5.0
        "rc.a": CandidateSignals("rc.a", exact_slot_hit_count=2),  # 10.0
        "rc.c": CandidateSignals("rc.c", exact_slot_hit_count=1),  # 5.0
    }
    ranked = rule_retriever.rank_candidates(signals)
    assert ranked[0][0] == "rc.a"  # 最高分
    # 同分 5.0：rc.b、rc.c 按 id 升序。
    assert [cid for cid, _ in ranked[1:]] == ["rc.b", "rc.c"]


def test_select_verifier_candidates_score_gt_0() -> None:
    """verifier 候选集 = score>0 且未明确排除（spec §5.4.4）。"""
    signals = {
        "rc.hit": CandidateSignals("rc.hit", exact_slot_hit_count=1),     # 5.0 > 0
        "rc.zero": CandidateSignals("rc.zero"),                            # 0.0
        "rc.excluded": CandidateSignals(
            "rc.excluded", exact_slot_hit_count=2,
            explicit_exclusion_match_count=1,                              # 明确排除
        ),
    }
    selected = rule_retriever.select_verifier_candidates(signals)
    assert selected == ["rc.hit"]   # zero 与 excluded 都剔除


# ===========================================================================
# Fact KG-RAG 检索器
# ===========================================================================
def test_facts_from_raw_basic() -> None:
    """facts_from_raw 把承载节点字段展为 FactAtom。"""
    raw = fact_retriever.FactRetrievalRaw()
    raw.world = {"world_id": "WB-1"}
    raw.building = {"building_id": "BLD-1", "building_use": "industrial",
                    "storey_count": 16}
    raw.measurements = [{
        "measurement_id": "MSR-1", "slot_id": "test.slot",
        "value_json": "0.5", "qualifiers_json": "{}",
    }]
    atoms = fact_retriever.facts_from_raw(raw)
    # building_use + storey_count + measurement = 3 facts。
    fact_ids = {a.fact_id for a in atoms}
    assert "BLD-1::building_use" in fact_ids
    assert "BLD-1::storey_count" in fact_ids
    assert "MSR-1" in fact_ids


def test_retrieve_fact_pack_with_fake_client() -> None:
    """retrieve_fact_pack 端到端（FakeNeo4jClient）→ FactPack。"""
    responses = {
        queries.FACT_BUILDING_SHELL: [{
            "world": {"world_id": "WB-1"},
            "building": {"building_id": "BLD-1", "building_use": "industrial"},
        }],
        queries.FACT_FRAGMENT_SUBGRAPH: [{
            "fragment": {"fragment_id": "FRG-1", "fragment_role": "facade"},
            "component": None, "location": None,
        }],
        queries.FACT_SIDECAR_ENTRIES: [{
            "runtime_id": "SCR-1",
            "sidecar_entry": {
                "sidecar_entry_id": "SCR-1::facts::0", "slot_id": "qual.x",
                "value_json": "true", "qualifiers_json": "{}",
            },
        }],
    }
    client = FakeNeo4jClient(responses)
    pack = fact_retriever.retrieve_fact_pack(client, "RUN-1", "BLD-1")
    assert isinstance(pack, FactPack)
    assert pack.world_id == "WB-1"
    assert pack.building_id == "BLD-1"
    # building_use + fragment_role + sidecar entry 都成 fact。
    assert len(pack.facts) >= 3
    assert "qual.x" in pack.slot_index


# ===========================================================================
# Rule KG-RAG 检索器
# ===========================================================================
def test_collect_candidate_signals() -> None:
    """collect_candidate_signals 汇总 slot / measure / applicability 命中。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={"slot.a": ["F1"]}, measure_index={"measure.x": ["F2"]},
        carrier_index={}, source_tables=[],
    )
    responses = {
        queries.RULE_SLOT_DRIVEN_CARDS: [
            {"rule_card_id": "rc.1", "slot_hits": 2},
        ],
        queries.RULE_MEASURE_DRIVEN_CARDS: [
            {"rule_card_id": "rc.1", "threshold_hits": 1},
        ],
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [
            {"rule_card_id": "rc.1", "family_id": "fam.1"},
        ],
    }
    client = FakeNeo4jClient(responses)
    signals = rule_retriever.collect_candidate_signals(
        client, pack, regime="mbis", building_scope_tags=["tag1"]
    )
    sig = signals["rc.1"]
    assert sig.exact_slot_hit_count == 2
    assert sig.exact_measure_hit_count == 1
    assert sig.applicability_match_count == 1


def test_retrieve_rule_slice_end_to_end() -> None:
    """retrieve_rule_slice 端到端（FakeNeo4jClient）→ RuleSlice。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={"procedure.x": ["F1"]}, measure_index={},
        carrier_index={}, source_tables=[],
    )
    expansion_row = {
        "rule_card": {
            "rule_card_id": "rc.1", "source_document_id": "MBIS_CoP_2023",
            "normalized_rule_text": "t", "family_id": "fam.1",
            "primary_actor": "ri", "primary_action": "submit",
            "method_keys_allowed": [], "neighbor_families": [],
            "version_authoring_revision": "1.0.0",
            "version_interpretation_revision": 1, "provenance_json": "{}",
        },
        "applicabilities": [], "trigger_conditions": [], "slot_refs": [],
        "thresholds": [], "measures": [], "time_anchors": [],
        "evidence_requirements": [], "obligation_nodes": [], "obligation_edges": [],
        "workflow_artifacts": [], "workflow_deadlines": [], "workflow_recipients": [],
        "source_quotes": [], "artifacts": [],
    }
    responses = {
        queries.RULE_SLOT_DRIVEN_CARDS: [{"rule_card_id": "rc.1", "slot_hits": 1}],
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [],
        queries.RULE_GRAPH_EXPANSION: [expansion_row],
        queries.RULE_FAMILIES_BY_ID: [
            {"rule_family": {"family_id": "fam.1", "family_name": "Fam One"}},
        ],
    }
    client = FakeNeo4jClient(responses)
    rule_slice = rule_retriever.retrieve_rule_slice(
        client, "RUN-1", pack, "bundle-1", regime="mbis",
    )
    assert isinstance(rule_slice, RuleSlice)
    assert len(rule_slice.candidate_rule_cards) == 1
    assert rule_slice.candidate_rule_cards[0].rule_card_id == "rc.1"
    assert len(rule_slice.rule_families) == 1
    # §5.4.4：retrieval_policy 必须记录 cutoff policy。
    assert "candidate_cutoff_policy" in rule_slice.retrieval_policy
    assert "score_weights" in rule_slice.retrieval_policy


def test_retrieve_rule_slice_excludes_zero_score() -> None:
    """score=0 的卡不进 verifier 候选集，也不出现在 RuleSlice（§5.4.4）。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={}, measure_index={}, carrier_index={}, source_tables=[],
    )
    # applicability 命中但 0 hit 的卡：applicability_match_count=1 → score=2.0>0。
    # 这里构造一张完全无命中的场景：无 slot / measure / applicability。
    responses = {
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [],
        queries.RULE_GRAPH_EXPANSION: [],
    }
    client = FakeNeo4jClient(responses)
    rule_slice = rule_retriever.retrieve_rule_slice(
        client, "RUN-1", pack, "bundle-1",
    )
    assert rule_slice.candidate_rule_cards == []
    assert rule_slice.retrieval_policy["verifier_candidate_count"] == 0


# ===========================================================================
# §5.4.2 building scope 标签接线（2026-07-27 补：此前全仓无人计算、默认 None
# 直达查询层，适用性通道全批 0 行、50 张卡从未进候选）
# ===========================================================================
class RecordingFakeNeo4jClient(FakeNeo4jClient):
    """FakeNeo4jClient + 记录每条查询实收参数（接线闸用）。"""

    def __init__(self, responses: Dict[str, List[Dict[str, Any]]]) -> None:
        super().__init__(responses)
        self.seen_params: Dict[str, Dict[str, Any]] = {}

    def read(self, cypher: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        self.seen_params[cypher] = dict(params or {})
        return super().read(cypher, params)


def test_derive_building_scope_tags() -> None:
    """推导口径：regime=mbis（运行前提）→ MBIS 目标楼标签；其他 regime → 空（保守）。"""
    assert rule_retriever.derive_building_scope_tags(None, "mbis") == [
        rule_retriever.MBIS_TARGET_BUILDING_SCOPE_TAG
    ]
    assert rule_retriever.derive_building_scope_tags(None, "MBIS") == [
        rule_retriever.MBIS_TARGET_BUILDING_SCOPE_TAG
    ]
    assert rule_retriever.derive_building_scope_tags(None, "other") == []


def test_make_retrieval_fn_passes_nonempty_building_tags() -> None:
    """🔴 接线闸：make_retrieval_fn 产出的检索函数必须把**非空** building tags
    一路传到适用性查询参数层。

    这是本项目第八个「失败了但不说话」的原位复发形态：参数定义在、默认值 None、
    全仓无人计算 → 适用性通道静默 0 行。只测 `derive_building_scope_tags` 自身
    等于没测（生产者被测、调用点没被测），故本闸端到端走
    make_retrieval_fn → retrieve_fact_pack → retrieve_rule_slice → 查询参数。
    """
    from evo_agent_baseline.retrieval import make_retrieval_fn

    responses = {
        queries.FACT_BUILDING_SHELL: [{
            "world": {"world_id": "WB-1"},
            "building": {"building_id": "BLD-1", "building_use": "industrial"},
        }],
    }
    client = RecordingFakeNeo4jClient(responses)
    retrieval_fn = make_retrieval_fn(client, "bundle-1")
    fact_pack, rule_slice = retrieval_fn("WB-1", "BLD-1", "RUN-1")
    params = client.seen_params.get(queries.RULE_APPLICABILITY_BUILDING_SCOPE)
    assert params is not None, "适用性 building scope 查询根本没被发出"
    tags = params.get("building_scope_tags")
    assert tags, f"building_scope_tags 为空/缺省：{tags!r}——病灶复发"
    assert tags == [rule_retriever.MBIS_TARGET_BUILDING_SCOPE_TAG]
    # 溯源位：policy 必须记录本次实收标签。
    assert rule_slice.retrieval_policy["building_scope_tags"] == tags


def test_explicit_building_scope_tags_respected() -> None:
    """显式传列表（含空表）时尊重调用方、不推导——推导只补缺省 None。"""
    pack = FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={}, measure_index={}, carrier_index={}, source_tables=[],
    )
    client = RecordingFakeNeo4jClient({})
    rule_retriever.run_rule_retrieval(client, pack, "mbis", [])
    params = client.seen_params[queries.RULE_APPLICABILITY_BUILDING_SCOPE]
    assert params["building_scope_tags"] == []
    client2 = RecordingFakeNeo4jClient({})
    rule_retriever.run_rule_retrieval(client2, pack, "mbis", ["custom_tag"])
    assert client2.seen_params[queries.RULE_APPLICABILITY_BUILDING_SCOPE][
        "building_scope_tags"
    ] == ["custom_tag"]


# ===========================================================================
# P1-2 版本冻结:retriever 三方 bundle 同源校验(DEBT-065 复审补测)
# ===========================================================================
def _responses_with_assets(lattice_bundle: str, auth_bundle: str) -> Dict[str, List[Dict[str, Any]]]:
    expansion_row = {
        "rule_card": {
            "rule_card_id": "rc.1", "source_document_id": "MBIS_CoP_2023",
            "normalized_rule_text": "t", "family_id": "fam.1",
            "primary_actor": "ri", "primary_action": "submit",
            "method_keys_allowed": [], "neighbor_families": [],
            "version_authoring_revision": "1.0.0",
            "version_interpretation_revision": 1, "provenance_json": "{}",
        },
        "applicabilities": [], "trigger_conditions": [], "slot_refs": [],
        "thresholds": [], "measures": [], "time_anchors": [],
        "evidence_requirements": [], "obligation_nodes": [], "obligation_edges": [],
        "workflow_artifacts": [], "workflow_deadlines": [], "workflow_recipients": [],
        "source_quotes": [], "artifacts": [],
    }
    return {
        queries.RULE_SLOT_DRIVEN_CARDS: [{"rule_card_id": "rc.1", "slot_hits": 1}],
        queries.RULE_APPLICABILITY_BUILDING_SCOPE: [],
        queries.RULE_GRAPH_EXPANSION: [expansion_row],
        queries.RULE_FAMILIES_BY_ID: [
            {"rule_family": {"family_id": "fam.1", "family_name": "Fam One"}},
        ],
        queries.RULE_COMPONENT_TYPE_LATTICE: [
            {"version": "v1", "lattice_json": "{}", "rulecard_bundle_id": lattice_bundle},
        ],
        queries.RULE_EXACT_FRAGMENT_TARGET_AUTHORIZATIONS: [
            {"version": "v1", "authorized_targets_json": "{}", "rulecard_bundle_id": auth_bundle},
        ],
    }


def _pack_for_assets() -> FactPack:
    return FactPack(
        run_id="RUN-1", world_id="WB-1", building_id="BLD-1", facts=[],
        slot_index={"procedure.x": ["F1"]}, measure_index={},
        carrier_index={}, source_tables=[],
    )


def _disk_pack_bundle_id() -> str:
    """第三条腿的**真实来源**——磁盘权威卡包声明的 `bundle_id`。

    🔴 不许在测试里伪造这个值。旧版三个 fake 全写 `bundle-1`「三方一致」故恒通过,
    而生产里 `ComponentTypeLattice` 节点**根本没写过** `rulecard_bundle_id`
    (loader 漏写,2026-07-27 修),校验恒失败、组件结构早退自上线起从未开过。
    **伪造全部三条腿的测试结构上抓不到这个 bug。**
    """
    from evo_agent_baseline.closure.identity_blueprint_catalog import (
        DEFAULT_AUTHORITATIVE_BUNDLE_PATH,
    )

    return json.loads(
        DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8")
    )["bundle_id"]


def test_p1_2_bundle_match_keeps_lattice() -> None:
    """P1-2:lattice/授权表/**磁盘卡包** bundle 三方一致 → 组件类型格+授权表进 policy。"""
    real = _disk_pack_bundle_id()
    client = FakeNeo4jClient(_responses_with_assets(real, real))
    # 调用方标签故意写成与真身份不同的 `bundle-1`——它**不再参与校验**,
    # 正因为实测三个调用面三个值(资产 / 脚本常量 / orchestrator 缺省)。
    rs = rule_retriever.retrieve_rule_slice(client, "RUN-1", _pack_for_assets(), "bundle-1", regime="mbis")
    assert "component_type_lattice" in rs.retrieval_policy
    assert "exact_fragment_target_authorizations" in rs.retrieval_policy
    assert rs.retrieval_policy["component_type_lattice_version"] == "v1"
    assert (
        rs.retrieval_policy["exact_fragment_target_authorizations_version"]
        == "v1"
    )
    assert "component_structure_bundle_mismatch" not in rs.retrieval_policy


def test_p1_2_bundle_mismatch_drops_lattice() -> None:
    """P1-2:lattice bundle 与磁盘卡包不一致 → 组件类型格+授权表不进 policy(保守关闭)。"""
    real = _disk_pack_bundle_id()
    client = FakeNeo4jClient(_responses_with_assets("bundle-OTHER", real))
    rs = rule_retriever.retrieve_rule_slice(client, "RUN-1", _pack_for_assets(), "bundle-1", regime="mbis")
    assert "component_type_lattice" not in rs.retrieval_policy
    assert "exact_fragment_target_authorizations" not in rs.retrieval_policy
    assert "component_type_lattice_version" not in rs.retrieval_policy
    assert "exact_fragment_target_authorizations_version" not in rs.retrieval_policy
    assert "component_structure_bundle_mismatch" in rs.retrieval_policy


def test_p1_2_lattice_node_carries_bundle_id_from_loader() -> None:
    """🔴 回归闸:loader 必须给 `ComponentTypeLattice` 写 `rulecard_bundle_id`。

    这条测的是**生产者→消费者接口**,不是生产者自身:漏写该属性时检索侧读回 None,
    三方校验恒失败、早退恒关,而**全链不报错**——上面两条(伪造三条腿)全绿也照样漏。
    """
    import evo_agent_baseline.ingest.rulecard_loader as loader

    reg = pathlib.Path(loader.__file__).resolve().parents[3] / "regulations" / "rulecard_v2" / "mbis_cop_2023"
    pack = json.loads((reg / "rule_cards.json").read_text(encoding="utf-8"))
    # 🔴 真实键是 `cards`(398 张),**不是** `rule_cards`。写错键 → 传进去空列表 →
    # 授权表节点内容为空但仍带 bundle_id → 下面的断言照样过 = **本闸自己是空的**。
    # 2026-07-27 codex 审核抓出(我写这条闸的当次就犯了它本要防的错)。
    cards = pack["cards"]
    assert cards, "卡包 `cards` 为空——本闸失去意义,先查卡包"
    res = loader.RuleCardLoadResult(batch=loader.GraphBatch())
    res.bundle_id = pack["bundle_id"]
    loader._load_component_lattice_and_authorizations(
        res, cards, reg, loader.AuditLog()
    )
    nodes = {
        n.label: n
        for n in res.batch.nodes
        if n.label in ("ComponentTypeLattice", "ExactFragmentTargetAuthorizations")
    }
    assert set(nodes) == {"ComponentTypeLattice", "ExactFragmentTargetAuthorizations"}
    for label, node in nodes.items():
        assert node.props.get("rulecard_bundle_id") == pack["bundle_id"], label
        # 防空:节点必须真带载荷,否则「属性对了但内容是空的」照样过闸。
        payload = [
            v for k, v in node.props.items()
            if k != "rulecard_bundle_id" and isinstance(v, str) and v.strip()
        ]
        assert payload, f"{label} 除 bundle_id 外无任何载荷"
        assert any(len(v) > 2 for v in payload), f"{label} 载荷为空容器"


# ===== DEBT-073：生产路径必须传卡内容失配校验参数 =====

def test_rulecard_digests_match_manifest_declarations():
    """🔴 口径必须与 manifest **生成时**一致，否则校验形同虚设或每次误报。

    我第一版把整包摘要猜成"文件字节 sha256"，实测逐卡 55/55 对、**整包对不上**——
    接上去会让每次运行都误报 `rulecard_pack_mismatch` 而整路径禁用早退。
    正确口径是 `canonical_hash(整个 cards_doc)`
    （`scripts/build_card_applicability_manifest.py:125`）。
    """
    import json
    import pathlib
    from evo_agent_baseline.agent.run_orchestrator import _rulecard_content_digests

    repo = pathlib.Path(__file__).resolve().parents[4]
    pack, shas = _rulecard_content_digests(repo)
    mani_p = (repo / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"
              / "card_applicability_manifest_v1.json")
    if not mani_p.is_file():
        import pytest
        pytest.skip("manifest 未生成（派生物）")
    mani = json.loads(mani_p.read_text(encoding="utf-8"))
    assert pack == mani.get("rulecard_pack_sha256"), "整包摘要口径与 manifest 不一致"
    bad = [cid for cid, e in (mani.get("cards") or {}).items()
           if e.get("card_content_sha256")
           and shas.get(cid) != e["card_content_sha256"]]
    assert not bad, f"逐卡指纹口径不一致：{bad[:3]}"


def test_production_call_site_passes_integrity_args():
    """🔴 接线闸：生产调用点必须真的传那两个参数。

    这是本项目「关键配置静默退化」族里**最坏的一种形态**——护栏函数写好了、
    单测覆盖了、发布门禁也真传参数验过，**唯独生产调用点没接线**，
    而 `load_bundle` 里两处校验都是条件式（参数为 None 就整段跳过）。
    「生产者→消费者接口只测生产者自身等于没测」在这里是"**校验函数被测了、调用点没被测**"。
    """
    import inspect
    from evo_agent_baseline.agent import run_orchestrator as ro

    src = inspect.getsource(ro.load_applicability_bundle_once)
    assert "rulecard_pack_sha256=" in src, "生产调用点没传卡包整体摘要"
    assert "card_content_shas=" in src, "生产调用点没传逐卡内容指纹"
    # 参数得是真算出来的，不能是写死的 None
    assert "_rulecard_content_digests(" in src, "参数不是真算的"


def test_chat_timeout_is_configurable_with_safe_fallback(monkeypatch):
    """🔴 超时写死 600 秒曾整批判废（2026-07-26 试跑实证）。

    两栋均 `native /api/chat 请求失败: timed out` → `tool_call_missing` → 批废。
    首栋要叠「灌库 + 冷推理」，600 秒不够。改为可配；非法值**回落缺省并出声**，
    不静默用一个坏值（静默退化是本项目反复踩的那族坑）。
    """
    from evo_agent_baseline.agent.llm_client import _chat_timeout_seconds

    monkeypatch.delenv("EVO_AGENT_LLM_TIMEOUT", raising=False)
    assert _chat_timeout_seconds() == 600, "缺省必须与改动前一致"
    monkeypatch.setenv("EVO_AGENT_LLM_TIMEOUT", "1800")
    assert _chat_timeout_seconds() == 1800
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv("EVO_AGENT_LLM_TIMEOUT", bad)
        assert _chat_timeout_seconds() == 600, f"非法值 {bad!r} 未回落缺省"


def test_timeout_is_actually_wired_into_the_request():
    """接线闸:超时必须真的用在 urlopen 上，不能只定义了函数没接。"""
    import inspect
    from evo_agent_baseline.agent import llm_client

    src = inspect.getsource(llm_client)
    assert "timeout=_chat_timeout_seconds()" in src, "超时函数没接进请求"
    assert "timeout=600" not in src, "还留着写死的 600"
