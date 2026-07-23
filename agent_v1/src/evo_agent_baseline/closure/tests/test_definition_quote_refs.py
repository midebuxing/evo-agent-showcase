"""DEBT-057: definition 引用字段的判定端直接回归。"""

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import evaluate_definition

from .fixtures import make_fact_pack, make_rule_card


_META = {"run_id": "R-def", "world_id": "W-def", "building_id": "B-def"}


def _evaluate(definition):
    card = make_rule_card()
    return evaluate_definition(card, definition, FactIndex(make_fact_pack()), _META)


def test_definition_true_source_quote_refs_field_is_consumed():
    obligation = _evaluate({"source_quote_refs": ["sq01"]})

    assert (obligation.closure_status, obligation.satisfaction_status) == (
        "closed", "satisfied",
    )
    assert "sq01" in obligation.source_quote_ids


def test_definition_all_nonempty_string_refs_are_deduplicated():
    obligation = _evaluate(
        {"source_quote_refs": ["sq02", "", "sq01", "sq02", None, 7]}
    )

    assert obligation.source_quote_ids == sorted(
        {"RC.test.001::q1", "sq01", "sq02"}
    )


def test_definition_empty_list_and_invalid_scalar_are_conservative():
    for definition in (
        {"source_quote_refs": []},
        {"source_quote_refs": "sq-not-a-list"},
        {"source_quote_refs": 7},
    ):
        obligation = _evaluate(definition)
        assert obligation.closure_status == "blocked"
        assert obligation.satisfaction_status == "unknown"
        assert obligation.blocked_reason_code == "missing_rule_edge"


def test_definition_legacy_single_value_keys_remain_compatible_and_union():
    obligation = _evaluate(
        {
            "source_quote_refs": ["sq02"],
            "source_quote_id": "sq01",
            "quote_local_id": "sq02",
        }
    )

    assert obligation.source_quote_ids == sorted(
        {"RC.test.001::q1", "sq01", "sq02"}
    )
