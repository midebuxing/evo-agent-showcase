"""工单 #8：幻影覆盖只作可选旁路诊断，绝不改轨一。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import score_clause_coverage as scorer  # noqa: E402


CARD_ID = "rc.test.external_wall.c01"
FRAGMENT_ID = "FRG-MISLEADING-EXTERNAL-WALL-99"
ITEM = {
    "normative_item_id": "mbis.test.phantom",
    "source_clause_id": "X.1",
    "scope_type": "building",
    "scope_id": "BLD-T",
    "applicable": True,
    "expected_card_ids": [CARD_ID],
}
CARD = {
    "rule_card_id": CARD_ID,
    "trigger_conditions": {
        "logic": "all",
        "items": [{
            "condition_id": "trg01",
            "qualifiers": {"component_type_key": "external_wall"},
        }],
    },
    "slot_role_map": [{
        "slot_ref_id": "sr01",
        "slot_id": "defect.present",
        "qualifiers": {"component_type_key": "external_wall"},
        "roles": ["trigger"],
    }],
}


def _score(canonical_component_type: str | None, diagnostic: bool | None = None) -> dict:
    facts = []
    if canonical_component_type is not None:
        facts.append({
            "slot_id": "w0_component_identity",
            "carrier_type": "fragment",
            "carrier_id": FRAGMENT_ID,
            "qualifiers": {
                "fragment_id": FRAGMENT_ID,
                "canonical_component_type": canonical_component_type,
            },
        })
    payloads = {
        "rule_slice.json": {"candidate_rule_cards": [{"rule_card_id": CARD_ID}]},
        "obligation_set.json": {"obligations": [{
            "obligation_id": "obl-1",
            "source_rule_card_id": CARD_ID,
            "fragment_id": FRAGMENT_ID,
            "kind": "action",
            "satisfaction_status": "unknown",
            "closure_status": "blocked",
            "blocked_reason_code": "missing_rule_edge",
        }]},
        "fact_pack.json": {"facts": facts},
    }

    def fake_read_text(path: Path, encoding: str | None = None) -> str:
        del encoding
        return json.dumps(payloads[path.name])

    kwargs = {"cards_by_id": {CARD_ID: CARD}}
    if diagnostic is not None:
        kwargs["phantom_coverage_diag"] = diagnostic
    with patch.object(scorer, "_latest_run_dir", return_value=Path("r1")):
        with patch.object(Path, "read_text", fake_read_text):
            return scorer.score_building(Path("BLD-T"), [ITEM], {CARD_ID}, **kwargs)


def test_default_off_keeps_existing_result_shape() -> None:
    """缺省与显式关闭逐项相等，且不新增任何诊断键。"""
    default_result = _score("structural_component")
    explicit_off = _score("structural_component", diagnostic=False)

    assert default_result == explicit_off
    assert "phantom_coverage_diagnostic" not in default_result


def test_phantom_requires_all_witnesses_to_be_authoritatively_mismatched(
) -> None:
    """只认权威身份；匹配或无法判定的见证都不得算入幻影。"""
    mismatch = _score(
        "structural_component", diagnostic=True)["phantom_coverage_diagnostic"]
    assert mismatch["phantom_coverage"]["count"] == 1
    assert mismatch["robust_coverage"]["count"] == 0
    witness = mismatch["items"][0]["scope_rows"][0]["witnesses"][0]
    assert witness["actual_canonical_component_type"] == "structural_component"
    assert witness["component_type_mismatch"] is True

    matched = _score(
        "external_wall", diagnostic=True)["phantom_coverage_diagnostic"]
    assert matched["phantom_coverage"]["count"] == 0
    assert matched["robust_coverage"]["count"] == 1

    unknown = _score(None, diagnostic=True)["phantom_coverage_diagnostic"]
    assert unknown["phantom_coverage"]["count"] == 0
    assert unknown["undetermined_item_count"] == 1
    assert unknown["undetermined_reason_counts"] == {
        "authoritative_fragment_identity_missing": 1,
    }
