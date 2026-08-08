#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`check_override_registry_reconciliation.py`（换池前置 P5 对账闸）的行为锁定测试。

两组：

A. **现状特征化**（读真卡包，不造夹具）——把闸在真实数据上的读数钉住。
   沿革：本闸 2026-08-06 建立时断言一实测 **8 条违例**（7 槽未登记 ＋ 1 槽角色
   未授权），红着交付等逐槽裁定；同日 #38 八槽裁定落地
   （`决议_38裁定_20260806.md`：6 槽登记＋1 槽补角色＋2 谓词改绑），
   **A1 清零、三断言全绿**——本组期望值随裁定同批更新（改期望值，没放宽闸）。

B. **合成夹具 + 变异对照**——证明闸在合规输入上会绿（不是永远红），
   且三条断言各自被对应的变异独立打红（该红必须红）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_override_registry_reconciliation as gate  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# A. 现状特征化（真卡包）
# ══════════════════════════════════════════════════════════════════════════
#
# 2026-08-06 #38 落地后的实测冻结值。改动 card_overrides / semantic_slot_registry /
# 白名单任一，本组必须同批更新——这正是它存在的意义。
#
# 沿革：闸建立当日（同日早）A1 实测 8 条违例（CURRENT_UNREGISTERED_SLOTS 7 个
# ＋ certificate 槽角色未授权 1 个）；#38 八槽裁定（决议_38裁定_20260806）
# 6 槽登记＋1 槽补角色＋2 谓词改绑后清零。旧违例清单见
# 杂物箱/备份_38落地_20260806/ 与 实施记录_P5对账闸_20260806.md §二。
CURRENT_OVERRIDE_SLOTS = {
    # #38 后的 9 个去重 override 槽（含三处改绑目标）：
    "artifact.certificate.material_or_product",       # 槽1，唯一负形（==false）
    # 槽2 主案落地（换池批步 A1.3，2026-08-06）：过渡态 verification.test.failed
    # 改绑「发现不一致事项」事件槽（决议_38裁定 槽2 预授权的改绑）：
    "supervision.nonconformity.found",
    "procedure.investigation.detailed.intended",      # 乙路先例（2026-08-05）
    "procedure.repair.revision_required",             # 槽3 主案改绑目标（世界实采名）
    "procedure.repair_supervising_ri.appointment.completed",  # 槽4（已补实采）
    "procedure.ri_role.terminated",                   # 槽5
    "procedure.supervision_representative.planned",   # 槽6
    "procedure.supervision_team.changed",             # 槽7
    "procedure.temp_ri_nomination.terminated",        # 槽8
}
# 改绑后不得再出现在覆盖表里的旧槽名（幽灵名回流即红）：
RETIRED_OVERRIDE_SLOTS = {
    "artifact.record.nonconformity_correction_sp2",
    "procedure.repair.revision_proposal.submitted_to_ba",
    # 槽2 备案过渡态（换池批步 A1.3 主案落地后除名——欠覆盖近似不得回流）：
    "verification.test.failed",
}


@pytest.fixture(scope="module")
def live_result():
    return gate.reconcile(include_world_diagnostics=False)


def test_current_state_sampling_frame(live_result):
    """取样面钉死：12 张卡 / 12 条谓词 / 9 个去重槽。"""
    assert live_result.counts["override_cards"] == 12
    assert live_result.counts["override_predicates"] == 12
    assert live_result.counts["override_slots"] == 9
    assert live_result.counts["whitelist_slots"] == 9
    assert live_result.counts["whitelist_bindings"] == 12


def test_current_state_a2_whitelist_green(live_result):
    """断言二在现状全过——白名单首版成员就是实取现状。"""
    assert live_result.a2_violations == []


def test_current_state_a3_two_sides_green(live_result):
    """断言三在现状全过——含 s2_1_3_n 的 mirrored 关系（乙路两侧同批已落）。"""
    assert live_result.a3_violations == []


def test_current_state_s2_1_3_n_is_mirrored():
    """乙路承重事实：s2_1_3_n 的 override 槽与卡本体 trigger 槽同值。"""
    bundle = gate.DEFAULT_BUNDLE_DIR
    cards = json.loads((bundle / gate.RULE_CARDS_FILE).read_text(encoding="utf-8"))["cards"]
    card_id = (
        "rc.mbis.reporting.ri_procedural_notifications.ri.submit."
        "s2_1_3_n_investigation_intention_to_ba.c01"
    )
    card = next(c for c in cards if c["rule_card_id"] == card_id)
    relation, trigger_slots = gate.card_side_relation(
        card, "procedure.investigation.detailed.intended"
    )
    assert relation == gate.RELATION_MIRRORED
    assert trigger_slots == ["procedure.investigation.detailed.intended"]


def test_current_state_a1_green_after_debt038(live_result):
    """#38 落地后断言一清零（原 8 条违例见沿革注释）——三断言全绿、闸放行。"""
    assert live_result.a1_violations == []
    assert live_result.ok


def test_current_state_override_slot_set_frozen():
    """9 个去重 override 槽逐字钉死；#38 除名的两个旧槽名不得回流。"""
    mapping = json.loads(
        (gate.DEFAULT_BUNDLE_DIR / gate.MAPPING_FILE).read_text(encoding="utf-8")
    )
    slots = {
        p["slot_id"]
        for override in mapping["card_overrides"].values()
        for p in override.get("extra_trigger_predicates", [])
    }
    assert slots == CURRENT_OVERRIDE_SLOTS
    assert not (slots & RETIRED_OVERRIDE_SLOTS)


def test_current_state_unique_negated_predicate():
    """唯一负形谓词钉死：只有 certificate 槽（App5 两卡）以 ==false 编码明文例外。

    附錄五 §1.1(b)(ii)：有效产品证明书 ⇒ 無須進行物料測試——义务只在证明书
    **缺席**时适用（决议_38裁定_20260806 槽1）。任何新增负形谓词都该在这里现形。
    """
    mapping = json.loads(
        (gate.DEFAULT_BUNDLE_DIR / gate.MAPPING_FILE).read_text(encoding="utf-8")
    )
    negated = {
        (card_id, p["slot_id"])
        for card_id, override in mapping["card_overrides"].items()
        for p in override.get("extra_trigger_predicates", [])
        if p.get("expected_value") is False
    }
    assert negated == {
        (
            "rc.mbis.repair.external_structural_validation.ri.verify."
            "sapp5_s1_1_b_7day_tests_if_no_coc.c01",
            "artifact.certificate.material_or_product",
        ),
        (
            "rc.mbis.repair.external_structural_validation.ri.verify."
            "sapp5_s1_1_b_two_specimens_each_property.c01",
            "artifact.certificate.material_or_product",
        ),
    }


def test_current_state_whitelist_fully_adjudicated():
    """#38 后白名单不再有 inherited_unadjudicated 成员，且逐条引用裁定来源。"""
    whitelist = json.loads(
        (gate.DEFAULT_BUNDLE_DIR / gate.WHITELIST_FILE).read_text(encoding="utf-8")
    )
    statuses = {e["slot_id"]: e["adjudication_status"] for e in whitelist["entries"]}
    assert set(statuses.values()) == {"adjudicated"}
    for entry in whitelist["entries"]:
        source = entry["adjudication_source"]
        assert ("决议_38裁定_20260806" in source) or ("决议_乙路_20260805" in source), (
            f"{entry['slot_id']} 的裁定来源没有引用决议：{source[:60]}…"
        )


def test_gate_problems_empty_after_debt038():
    """薄接口返回空清单 ⇒ 上游可生成真值队列（#38 前此处是 8 条债）。"""
    assert gate.gate_problems() == []


# ══════════════════════════════════════════════════════════════════════════
# B. 合成夹具 + 变异对照
# ══════════════════════════════════════════════════════════════════════════
CARD_MIRRORED = "rc.test.mirrored.c01"
CARD_OVERRIDE_ONLY = "rc.test.override_only.c01"
SLOT_OK = "procedure.test.gate_open"
SLOT_OK2 = "procedure.test.other_gate"


def _predicate(slot_id: str) -> dict:
    return {
        "condition_id": "cfg01",
        "predicate_kind": "slot",
        "slot_id": slot_id,
        "alias_slot_ids": [],
        "partition": "sidecar",
        "operator": "==",
        "expected_value": True,
        "qualifiers": {},
        "lookup_rule": None,
        "owning_interface_ids": ["procedure_gate_sidecar"],
        "owning_interface_mode": "any_of",
        "deferred_reason_code": None,
        "deferred_note": None,
    }


def _write_bundle(root: pathlib.Path) -> pathlib.Path:
    """写一份三条断言全过的最小合规卡包。"""
    root.mkdir(parents=True, exist_ok=True)

    (root / gate.MAPPING_FILE).write_text(
        json.dumps(
            {
                "version": "test",
                "card_overrides": {
                    CARD_MIRRORED: {"extra_trigger_predicates": [_predicate(SLOT_OK)]},
                    CARD_OVERRIDE_ONLY: {"extra_trigger_predicates": [_predicate(SLOT_OK2)]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (root / gate.REGISTRY_FILE).write_text(
        json.dumps(
            {
                "registry_id": "semantic_slot_registry_v1",
                "schema_version": "1.0.0",
                "slots": [
                    {
                        "slot_id": SLOT_OK,
                        "semantic_domain": "procedure_status",
                        "allowed_roles": ["trigger"],
                        "semantic_meaning": "test",
                    },
                    {
                        "slot_id": SLOT_OK2,
                        "semantic_domain": "procedure_status",
                        "allowed_roles": ["trigger", "evidence"],
                        "semantic_meaning": "test",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (root / gate.RULE_CARDS_FILE).write_text(
        json.dumps(
            {
                "bundle_id": "test",
                "cards": [
                    {
                        "rule_card_id": CARD_MIRRORED,
                        "trigger_conditions": {
                            "logic": "all",
                            "items": [
                                {
                                    "condition_id": "trg01",
                                    "predicate_kind": "slot",
                                    "slot_ref_id": CARD_MIRRORED + ".sr01",
                                    "operator": "==",
                                    "expected_value": True,
                                }
                            ],
                        },
                        "slot_role_map": [
                            {
                                "slot_ref_id": CARD_MIRRORED + ".sr01",
                                "slot_id": SLOT_OK,
                                "qualifiers": {},
                                "roles": ["trigger"],
                                "required": True,
                            }
                        ],
                    },
                    {
                        "rule_card_id": CARD_OVERRIDE_ONLY,
                        "trigger_conditions": {"logic": "all", "items": []},
                        "slot_role_map": [],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (root / gate.WHITELIST_FILE).write_text(
        json.dumps(
            {
                "registry_id": "override_trigger_whitelist_v1",
                "schema_version": "1.0.0",
                "entries": [
                    {
                        "slot_id": SLOT_OK,
                        "adjudication_status": "adjudicated",
                        "adjudication_source": "test",
                        "card_bindings": [
                            {
                                "rule_card_id": CARD_MIRRORED,
                                "card_side_relation": gate.RELATION_MIRRORED,
                                "card_side_trigger_slot_ids": [SLOT_OK],
                            }
                        ],
                    },
                    {
                        "slot_id": SLOT_OK2,
                        "adjudication_status": "adjudicated",
                        "adjudication_source": "test",
                        "card_bindings": [
                            {
                                "rule_card_id": CARD_OVERRIDE_ONLY,
                                "card_side_relation": gate.RELATION_OVERRIDE_ONLY,
                                "card_side_trigger_slot_ids": [],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def _patch(root: pathlib.Path, filename: str, mutate) -> None:
    path = root / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def bundle(tmp_path: pathlib.Path) -> pathlib.Path:
    return _write_bundle(tmp_path / "bundle")


def _run(bundle_dir: pathlib.Path):
    return gate.reconcile(bundle_dir=bundle_dir, include_world_diagnostics=False)


def test_fixture_positive_all_three_green(bundle):
    """正例：合规夹具三条断言全过，退出码 0。"""
    result = _run(bundle)
    assert result.a1_violations == []
    assert result.a2_violations == []
    assert result.a3_violations == []
    assert result.ok
    assert gate.main(["--bundle-dir", str(bundle), "--no-world-diagnostics"]) == gate.EXIT_OK


# ── 变异一：未登记槽 ⇒ 断言一红 ─────────────────────────────────────────────
def test_mutation_unregistered_slot_trips_a1(bundle):
    _patch(
        bundle,
        gate.REGISTRY_FILE,
        lambda d: d.__setitem__("slots", [s for s in d["slots"] if s["slot_id"] != SLOT_OK]),
    )
    result = _run(bundle)
    assert len(result.a1_violations) == 1
    assert "A1·登记" in result.a1_violations[0]
    assert SLOT_OK in result.a1_violations[0]
    assert result.a2_violations == [] and result.a3_violations == []
    assert gate.main(["--bundle-dir", str(bundle), "--no-world-diagnostics"]) == gate.EXIT_VIOLATION


def test_mutation_role_not_authorized_trips_a1(bundle):
    """同属断言一的另一半：已登记但 allowed_roles 不含 trigger。"""

    def strip_trigger(payload):
        for slot in payload["slots"]:
            if slot["slot_id"] == SLOT_OK:
                slot["allowed_roles"] = ["evidence"]

    _patch(bundle, gate.REGISTRY_FILE, strip_trigger)
    result = _run(bundle)
    assert len(result.a1_violations) == 1
    assert "A1·角色" in result.a1_violations[0]
    assert result.a2_violations == [] and result.a3_violations == []


# ── 变异二：白名单外槽 ⇒ 断言二红 ───────────────────────────────────────────
def test_mutation_slot_outside_whitelist_trips_a2(bundle):
    _patch(
        bundle,
        gate.WHITELIST_FILE,
        lambda d: d.__setitem__("entries", [e for e in d["entries"] if e["slot_id"] != SLOT_OK]),
    )
    result = _run(bundle)
    assert len(result.a2_violations) == 1
    assert "A2·白名单" in result.a2_violations[0]
    assert SLOT_OK in result.a2_violations[0]
    assert result.a1_violations == []
    assert gate.main(["--bundle-dir", str(bundle), "--no-world-diagnostics"]) == gate.EXIT_VIOLATION


# ── 变异三：两侧不一致 ⇒ 断言三红 ───────────────────────────────────────────
def test_mutation_card_side_reverted_trips_a3(bundle):
    """只落真值侧：卡本体的 trigger 被撤掉，覆盖表照旧 ⇒ mirrored 塌成 override_only。"""

    def drop_card_trigger(payload):
        for card in payload["cards"]:
            if card["rule_card_id"] == CARD_MIRRORED:
                card["trigger_conditions"]["items"] = []

    _patch(bundle, gate.RULE_CARDS_FILE, drop_card_trigger)
    result = _run(bundle)
    assert len(result.a3_violations) == 1
    assert "A3·两侧" in result.a3_violations[0]
    assert "mirrored" in result.a3_violations[0]
    assert "override_only" in result.a3_violations[0]
    assert result.a1_violations == [] and result.a2_violations == []
    assert gate.main(["--bundle-dir", str(bundle), "--no-world-diagnostics"]) == gate.EXIT_VIOLATION


def test_mutation_card_side_slot_swapped_trips_a3(bundle):
    """卡本体换成别的 trigger 槽 ⇒ 关系由 mirrored 变 additive。"""

    def swap_slot(payload):
        for card in payload["cards"]:
            if card["rule_card_id"] == CARD_MIRRORED:
                card["slot_role_map"][0]["slot_id"] = SLOT_OK2

    _patch(bundle, gate.RULE_CARDS_FILE, swap_slot)
    result = _run(bundle)
    assert len(result.a3_violations) == 1
    assert "additive" in result.a3_violations[0]


def test_mutation_override_removed_one_side_trips_a3(bundle):
    """只撤真值侧：覆盖表条目消失，白名单冻结仍在 ⇒ 断言三红。"""
    _patch(
        bundle,
        gate.MAPPING_FILE,
        lambda d: d["card_overrides"].pop(CARD_MIRRORED),
    )
    result = _run(bundle)
    assert len(result.a3_violations) == 1
    assert "已消失" in result.a3_violations[0]


def test_mutation_new_binding_not_frozen_trips_a3(bundle):
    """覆盖表给已白名单的槽新增一张卡的绑定，但白名单未冻结该绑定 ⇒ 断言三红。"""

    def add_binding(payload):
        payload["card_overrides"][CARD_OVERRIDE_ONLY]["extra_trigger_predicates"].append(
            _predicate(SLOT_OK)
        )

    _patch(bundle, gate.MAPPING_FILE, add_binding)
    result = _run(bundle)
    assert len(result.a3_violations) == 1
    assert "未在白名单冻结" in result.a3_violations[0]
    assert result.a2_violations == []  # 槽本身在白名单内，红的只该是绑定层


# ── 前提不成立（exit 2，不宣绿） ────────────────────────────────────────────
def test_precondition_alias_slot_ids_not_supported(bundle):
    def add_alias(payload):
        payload["card_overrides"][CARD_MIRRORED]["extra_trigger_predicates"][0][
            "alias_slot_ids"
        ] = ["procedure.test.alias"]

    _patch(bundle, gate.MAPPING_FILE, add_alias)
    with pytest.raises(gate.PreconditionError):
        _run(bundle)
    assert (
        gate.main(["--bundle-dir", str(bundle), "--no-world-diagnostics"])
        == gate.EXIT_PRECONDITION
    )


def test_precondition_non_slot_predicate_not_supported(bundle):
    def change_kind(payload):
        payload["card_overrides"][CARD_MIRRORED]["extra_trigger_predicates"][0][
            "predicate_kind"
        ] = "threshold"

    _patch(bundle, gate.MAPPING_FILE, change_kind)
    with pytest.raises(gate.PreconditionError):
        _run(bundle)


def test_precondition_empty_overrides_does_not_pass(bundle):
    """零核不宣绿：覆盖表为空不是「全过」。"""
    _patch(bundle, gate.MAPPING_FILE, lambda d: d.__setitem__("card_overrides", {}))
    with pytest.raises(gate.PreconditionError):
        _run(bundle)
    assert gate.gate_problems(bundle_dir=bundle)  # 薄接口同样返回非空


def test_precondition_missing_whitelist(tmp_path):
    bundle_dir = _write_bundle(tmp_path / "bundle")
    (bundle_dir / gate.WHITELIST_FILE).unlink()
    with pytest.raises(gate.PreconditionError):
        _run(bundle_dir)


# ── 诊断不影响退出码 ────────────────────────────────────────────────────────
def test_stale_whitelist_member_is_diagnostic_only(bundle):
    def add_stale(payload):
        payload["entries"].append(
            {
                "slot_id": "procedure.test.no_longer_used",
                "adjudication_status": "adjudicated",
                "adjudication_source": "test",
                "card_bindings": [],
            }
        )

    _patch(bundle, gate.WHITELIST_FILE, add_stale)
    result = _run(bundle)
    assert result.ok
    assert any("白名单陈旧" in d for d in result.diagnostics)
