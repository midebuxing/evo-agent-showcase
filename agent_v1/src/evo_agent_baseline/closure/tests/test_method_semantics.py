"""method 义务空集/开放集语义（q5 专员判定 + codex 逐卡裁定转写，2026-07-08）。"""

from __future__ import annotations

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_obligation_node

from .fixtures import make_fact, make_fact_pack, make_rule_card

META = {"run_id": "R-test-001", "world_id": "WB-test-001",
        "building_id": "BLD-test-001"}


def _card(method_keys, action="select_repair_method"):
    return make_rule_card(
        workflow_operands={"method_keys_allowed": method_keys},
        obligation_graph={"nodes": [{
            "obligation_node_id": "n01", "node_kind": "duty",
            "actor": "ri", "action": action,
        }], "edges": []},
    )


def _method_fact():
    return make_fact("m1", measure_key="stress.pull_test.value", value=0.7,
                     value_type="number",
                     qualifiers={"method_class": "pull_test"})


def _run(card, facts):
    idx = FactIndex(make_fact_pack(facts))
    node = (card.obligation_graph or {}).get("nodes", [])[0]
    obls = evaluate_obligation_node(card, node, idx, True, META)
    return [o for o in obls if o.kind == "method"]


def test_empty_allowed_vacuous_not_applicable() -> None:
    """空集=条款无可枚举方法约束 → closed+not_applicable（vacuous）。"""
    out = _run(_card([]), [_method_fact()])
    assert out, "method 主节点义务应存在"
    assert all((o.closure_status, o.satisfaction_status)
               == ("closed", "not_applicable") for o in out)


def test_wildcard_open_set_any_method_satisfies() -> None:
    """["*"]=开放集 → 任意 method_class 证据满足。"""
    out = _run(_card(["*"]), [_method_fact()])
    assert any((o.closure_status, o.satisfaction_status)
               == ("closed", "satisfied") for o in out)


def test_wildcard_no_method_facts_stays_open() -> None:
    out = _run(_card(["*"]), [])
    assert all(o.closure_status == "open" for o in out)


def test_specific_allowed_whitelist_unchanged() -> None:
    """非空具体集：白名单匹配（既有语义回归护栏）。"""
    out = _run(_card(["pull_test"]), [_method_fact()])
    assert any(o.satisfaction_status == "satisfied" for o in out)
    out2 = _run(_card(["core_sample"]), [_method_fact()])
    assert all(o.closure_status == "open" for o in out2)
