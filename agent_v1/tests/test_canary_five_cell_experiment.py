"""落卡后六格脚本的权威卡读取与变异对照契约。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_card_applicability_manifest as build_manifest  # noqa: E402
import canary_five_cell_experiment as canary  # noqa: E402


def _write_pack(root: Path, cards: list[dict]) -> dict:
    doc = {"bundle_id": "test", "cards": cards}
    root.mkdir(parents=True, exist_ok=True)
    (root / "rule_cards.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )
    (root / "card_applicability_manifest_v1.json").write_text(
        json.dumps({
            "rulecard_pack_sha256": canary.canonical_hash(doc),
            "cards": {
                card["rule_card_id"]: {
                    "card_content_sha256": canary.canonical_hash(card)
                } for card in cards
            },
        }),
        encoding="utf-8",
    )
    return doc


def _target_card() -> dict:
    return {
        "rule_card_id": canary.CARD_ID,
        "obligation_graph": {"nodes": [{"obligation_node_id": f"{canary.CARD_ID}.n01"}]},
    }


def test_manifest_generator_freezes_unscoped_target_card_body():
    manifest = build_manifest.build()
    cards_doc = json.loads((canary.REG / "rule_cards.json").read_text(encoding="utf-8"))
    target = next(card for card in cards_doc["cards"]
                  if card["rule_card_id"] == canary.CARD_ID)

    entry = manifest["cards"][canary.CARD_ID]
    assert entry["authorized_target_leaf"] is None
    assert entry["card_content_sha256"] == canary.canonical_hash(target)

def test_load_authoritative_card_uses_unique_card_bound_to_pack_digest(tmp_path):
    original = _target_card()
    _write_pack(tmp_path, [{"rule_card_id": "rc.other"}, original])

    doc, card = canary.load_authoritative_card(tmp_path)

    assert card == original
    assert len([c for c in doc["cards"] if c["rule_card_id"] == canary.CARD_ID]) == 1


def test_load_authoritative_card_rejects_manual_card_mutation(tmp_path):
    """变异证据：发布清单生成后手改真实卡，六格验证必须在求值前失败。"""
    doc = _write_pack(tmp_path, [_target_card()])
    doc["cards"][0]["source_quote"] = [{"page": 999}]
    (tmp_path / "rule_cards.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )
    manifest_path = tmp_path / "card_applicability_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rulecard_pack_sha256"] = canary.canonical_hash(doc)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="card_content_sha256|目标卡"):
        canary.load_authoritative_card(tmp_path)


def test_load_authoritative_card_rejects_duplicate_id_even_with_fresh_digest(tmp_path):
    """变异证据：即使同步重算摘要，重复标识也不得被任取一张掩盖。"""
    _write_pack(tmp_path, [_target_card(), _target_card()])

    with pytest.raises(ValueError, match="恰好出现一次.*2"):
        canary.load_authoritative_card(tmp_path)


def test_mutation_replaces_real_card_without_adding_duplicate():
    original = _target_card()
    doc = {"cards": [{"rule_card_id": "rc.other"}, original]}
    mutation = _target_card()
    mutation["obligation_graph"]["nodes"] = []

    got = canary.replace_authoritative_card(doc, mutation)

    assert len(got["cards"]) == len(doc["cards"])
    assert sum(c["rule_card_id"] == canary.CARD_ID for c in got["cards"]) == 1
    assert got["cards"][1]["obligation_graph"]["nodes"] == []
    assert doc["cards"][1]["obligation_graph"]["nodes"], "输入权威卡不应被变异"

def test_canary_expected_reason_codes_exist_in_deriver() -> None:
    """🔴 回归闸：六格试验里写的预期原因码必须是**验证器真会产出**的码。

    2026-07-27 codex 四审 P2：F 场景原本写 `unresolvable_fact_value`——**全仓不存在**。
    脚本会把这段说明直接打印给人看 ⇒ 验收输出与真实结果对不上，
    该场景的原因码对不对**根本判不了**。

    这是「文档/脚本里的期望值与代码实际行为漂移」的典型——
    本项目已在多处栽过（`test_derivation.py` 的 docstring 曾把病灶当规格写着）。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    canary = (root / "scripts" / "canary_five_cell_experiment.py").read_text(encoding="utf-8")
    deriver = (root / "src" / "evo_agent_baseline" / "closure"
               / "obligation_deriver.py").read_text(encoding="utf-8")

    # 脚本注释里提到的所有 `open_reason_code=xxx`
    cited = set(re.findall(r"open_reason_code[=＝]`?([a-z_]+)`?", canary))
    assert cited, "脚本里没写任何预期原因码——本闸失去意义，先查脚本"

    produced = set(re.findall(r'open_reason_code"\]\s*=\s*"([a-z_]+)"', deriver))
    assert produced, "派生器里解析不到任何 open_reason_code 赋值——正则失效，本闸需重写"

    ghost = sorted(cited - produced)
    assert not ghost, (
        f"六格试验引用了派生器**不会产出**的原因码：{ghost}；"
        f"派生器实际会写的有 {sorted(produced)[:8]}…"
    )
