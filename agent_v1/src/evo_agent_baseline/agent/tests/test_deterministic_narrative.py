"""确定性兜底叙述的消费者可用性契约。"""

from __future__ import annotations

import re

from evo_agent_baseline.agent.report_writer import (
    NarrativeEvidencePack,
    render_deterministic_narrative,
)


_VALUE_LITERALS = {"false", "true", "null", "none", "nan"}
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def _pack(
    key_items: list[dict] | None = None,
    *,
    allow_stop: bool = False,
) -> NarrativeEvidencePack:
    items = list(key_items or [])
    return NarrativeEvidencePack(
        run_id="RUN",
        world_id="WORLD",
        building_id="BUILDING",
        allow_stop=allow_stop,
        key_items=items,
        alias_map={
            alias: alias
            for item in items
            for alias in (
                item["alias"],
                *([item["rule_card_alias"]] if item.get("rule_card_alias") else []),
            )
        },
    )


def _narrative_points(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("- ")]


def test_deterministic_narrative_has_no_latin_prose_and_hides_unknown_reason_code():
    rendered = render_deterministic_narrative(
        _pack(
            [
                {
                    "alias": "O1",
                    "rule_card_alias": "R1",
                    "category": "violated",
                    "observed": False,
                    "threshold": True,
                },
                {
                    "alias": "O2",
                    "rule_card_alias": "R2",
                    "category": "open",
                    "reason_code": "missing_fact",
                },
                {
                    "alias": "O3",
                    "rule_card_alias": "R3",
                    "category": "blocked",
                    "reason_code": "unregistered_reason_code",
                },
            ]
        )
    )

    words = {
        word.lower()
        for point in _narrative_points(rendered)
        for word in _LATIN_WORD_RE.findall(point)
        if word.lower() not in _VALUE_LITERALS
    }
    assert words == set()
    assert "unregistered_reason_code" not in rendered
    assert "原因码见未闭合项表" in rendered


def test_homogeneous_items_are_grouped_with_every_obligation_and_rule_alias():
    rendered = render_deterministic_narrative(
        _pack(
            [
                {
                    "alias": "O1",
                    "rule_card_alias": "R1",
                    "category": "violated",
                    "observed": False,
                    "threshold": 3,
                },
                {
                    "alias": "O2",
                    "rule_card_alias": "R2",
                    "category": "violated",
                    "observed": False,
                    "threshold": 3,
                },
                {
                    "alias": "O3",
                    "rule_card_alias": "R3",
                    "category": "violated",
                    "observed": 1,
                    "threshold": 3,
                },
            ]
        )
    )

    points = _narrative_points(rendered)
    assert len(points) == 2
    grouped = next(point for point in points if "以下 2 项" in point)
    for alias in ("[O1]", "[R1]", "[O2]", "[R2]"):
        assert alias in grouped
    assert "[O3]" not in grouped


def test_empty_key_items_keep_both_allow_stop_branches_single_point_and_chinese():
    completed = _narrative_points(
        render_deterministic_narrative(_pack(allow_stop=True))
    )
    incomplete = _narrative_points(
        render_deterministic_narrative(_pack(allow_stop=False))
    )

    assert len(completed) == len(incomplete) == 1
    assert "资料闭包已完成" in completed[0]
    assert "本次闭包验证未通过" in incomplete[0]
    for point in completed + incomplete:
        assert _LATIN_WORD_RE.findall(point) == []
