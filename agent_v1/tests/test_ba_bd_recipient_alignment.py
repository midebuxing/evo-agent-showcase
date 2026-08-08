# -*- coding: utf-8 -*-
"""#29「BA→BD」落地后的语义硬断言（层二）＋ 病原回归（层三）。

## 层二锁什么

檢驗日誌的呈交对象，中文正文（**唯一权威**，DEBT-068：卡上英文引文是辅助译文、
无规范效力证据力）逐字写「呈交**屋宇署**」＝ Buildings Department ＝ `bd`：

| 条款 | 原文行 | 页锚 |
|---|---|---|
| §3.3.2(A)(c) | `:969` | p20 |
| §3.4.2(A)(b) | `:1110` | p26 |
| §3.5.2(A)(c) | `:1187` | p29 |
| §3.6.2(A)(d) | `:1311` | p33 |
| §3.7.1(d) | `:1372` | p35 |

五条**逐字同文**（复核已按字节比对坐实，唯一差异是 `:969` 多一个排版空格）。
⇒ 「其中四条该判错译、第五条另有立法本意」在结构上不可能成立。

🔴 **按 `section_id` 取射程，不按绑定表行号取**——行号是绑定表的编号偶然，
不是条款边界。#29 最初把射程算成「四卡」正是因为拿 c55 的 rows 123-126 当了条款边界
（原文其实是 5 条平行款，第五张卡落在 row 39）。用行号写断言 ＝ 把那个错误固化进护栏。

## 层三锁什么

守则**确有大量条款**收件人是「建築事務監督」＝ Building Authority ＝ `ba`
（§2.1.3 全族 / §7.2.2 / §3.7.1(c) / §3.7.3(a) / §5.3.4(b) / §6.4.4 / §6.4.6 …）。
本件**最危险的手滑**是把 `ba` 全局替换成 `bd`——那会让卡侧与世界侧**双侧同步错**、
限定符仍然对齐、**一个错都不报**，凭空造出一批看不出来的假判定。

⇒ 层三把**射程外的每一处 `ba`** 钉成「必须仍是 ba」。

## 纪律

两层都配**变异对照**：把射程内任一处改回 `ba` ⇒ 层二必须红；
把射程外任一处改成 `bd` ⇒ 层三必须红。不做变异对照 ＝ 空护栏（本项目既有教训）。
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

_REG_DIR = (pathlib.Path(__file__).resolve().parents[1] / "regulations"
            / "rulecard_v2" / "mbis_cop_2023")
_CARDS = _REG_DIR / "rule_cards.json"
_VOCAB = _REG_DIR / "controlled_vocabularies_v1.json"

# 五条平行款——**条款号**，不是绑定表行号。
PARALLEL_CLAUSES = frozenset({
    "3.3.2(A)(c)", "3.4.2(A)(b)", "3.5.2(A)(c)", "3.6.2(A)(d)", "3.7.1(d)",
})

# 射程外必须仍是 `ba` 的 A 表行（原文确为「建築事務監督」，已逐条对中文正文核实）。
BA_ROWS_OUT_OF_SCOPE = frozenset({109, 110, 111, 112, 119, 120, 121})

WORLD_SLOT = "reporting.record.submitted"
ARTIFACT_SLOT = "reporting.artifact.submitted"


def _cards() -> list[dict]:
    return json.loads(_CARDS.read_text(encoding="utf-8"))["cards"]


def _sections(card: dict) -> set[str]:
    return {s.get("section_id") for s in card.get("source_section", [])}


def _scope_cards(cards: list[dict]) -> list[dict]:
    """五条平行款上的卡里，**带收件人**的那些（备存卡 `recipients` 为空，不在射程）。"""
    return [c for c in cards
            if _sections(c) & PARALLEL_CLAUSES
            and c.get("workflow_operands", {}).get("recipients")]


# ---------------------------------------------------------------- 层二

def test_parallel_clause_cards_are_exactly_five():
    """五条平行款上带收件人的卡**恰好 5 张**——射程既不多也不少。

    另有 2 张同条款的「備存」卡 `recipients` 为空（§3.3.2(A)(c) 与 §3.4.2(A)(b)
    各拆成 c01 備存 ／ c02 呈交），故按条款反查命中 7 张、带收件人的 5 张。
    这条断言防的是「第六张漏网卡」和「射程被悄悄缩回四卡」两个方向。
    """
    cards = _cards()
    matched = [c for c in cards if _sections(c) & PARALLEL_CLAUSES]
    scope = _scope_cards(cards)
    assert len(scope) == 5, sorted(c["rule_card_id"] for c in scope)
    assert len(matched) - len(scope) == 2, "備存卡（recipients 为空）应恰 2 张"
    # 五条平行款**每一条**都要有恰好一张带收件人的卡，不许某条款上挂两张或零张。
    covered = [s for c in scope for s in _sections(c) & PARALLEL_CLAUSES]
    assert sorted(covered) == sorted(PARALLEL_CLAUSES), covered


def test_layer2_card_side_recipients_are_bd():
    """层二①：五条平行款的卡侧收件人取值集合 ⊆ `{bd}`。"""
    keys = {r["recipient_key"]
            for c in _scope_cards(_cards())
            for r in c["workflow_operands"]["recipients"]}
    assert keys == {"bd"}, keys


def test_layer2_card_side_qualifier_axis_is_bd():
    """层二①附：这些卡引用 `reporting.record.submitted` 的限定符角色也必须是 `bd`。

    ⚠️ 第五卡（§3.4.2(A)(b)）走的是 `artifact.record.inspection_log` 槽、
    **限定符轴为空**，故它对本断言零贡献——这是设计，不是遗漏。
    """
    roles = {entry["qualifiers"]["actor_role_key"]
             for c in _scope_cards(_cards())
             for entry in c.get("slot_role_map", [])
             if entry.get("slot_id") == WORLD_SLOT}
    assert roles == {"bd"}, roles


def test_layer2_world_axis_serves_both_recipient_groups():
    """层二②（#29 **甲案**）：世界 `reporting.record.submitted` 轴积恰 **2 格**，
    角色取值域 ＝ `{ba, bd}`，两格的 `artifact_key` 都是 `record.inspection_log`。

    🔴 沿革（别让旧结论复活）：#29 首版按底稿 §4.2 做的是「**1→1 替换**」
    （只留 `bd`）。那条判断的**唯一依据**是「全库没有任何卡要求檢驗日誌呈交建築事務監督」
    ——**该前提已实测证伪**：引用本槽 `{artifact_key=record.inspection_log}` 的卡共 **10 张**，
    射程外 **6 张**原文确为建築事務監督（或挂 #29b 待裁），它们正在读 `ba` 格。
    删掉 `ba` 格＝把那 6 张卡打成 `blocked/qualifier_conflict`
    ——把**证据力**问题误记成**供给缺口**。决策门 2026-08-05 裁定改甲案：**并存**。

    ⚠️ 这条断言**不是** `test_axis_expansion_one_row_per_combo_with_qualifiers` 的重复：
    那条拿「产出」比「声明」，声明本身被改小它照样绿；这条锁的是**声明本体**。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    reg = next(t for t in _build_registry_bundle().registries
               if t.registry_id == "sidecar_bool_slot_registry")
    rec = next(r for r in reg.records if r["slot_id"] == WORLD_SLOT)
    combos = rec["qualifier_axis_product"]
    assert len(combos) == 2, combos
    assert {c["actor_role_key"] for c in combos} == {"ba", "bd"}, combos
    assert {c["artifact_key"] for c in combos} == {"record.inspection_log"}, combos
    # 🔴 `ba` 格必须与 #29 之前**逐字相同**：`sub_rng` 是纯键派生、键里带 combo_key，
    #    键一字不差才谈得上「既有行不位移」。
    assert {"artifact_key": "record.inspection_log",
            "actor_role_key": "ba"} in combos, combos


def test_layer2_binding_table_axis_is_bd():
    """层二③：A 表上这些卡的轴串角色段 ＝ `bd`。

    🔴 **按 `rule_card_id` 取行，不按 row 号取**——见模块 docstring。
    """
    from evo_agent_baseline.closure import binding_contract_registry as reg
    scope_ids = {c["rule_card_id"] for c in _scope_cards(_cards())}
    rows = [r for r in reg.BINDING_CONTRACTS
            if r["rule_card_id"] in scope_ids and r.get("qualifier_axis")]
    assert rows, "五卡在 A 表上一行带轴的都没有？先查取法，别让断言空过"
    for r in rows:
        assert "actor_role_key=bd," in r["qualifier_axis"], (r["row"], r["qualifier_axis"])
        assert "actor_role_key=ba" not in r["qualifier_axis"], (r["row"], r["qualifier_axis"])


def test_layer2_three_sides_agree():
    """层二④：卡侧 / 世界侧 / 绑定表三处**互相一致**。

    这条是前三条的合取，但单独写有价值：它锁的是「三处同源」，
    而不是「三处各自碰巧都对」——本项目既有教训「生产者→消费者接口
    只测生产者自身等于没测」。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    from evo_agent_baseline.closure import binding_contract_registry as reg

    card_roles = {entry["qualifiers"]["actor_role_key"]
                  for c in _scope_cards(_cards())
                  for entry in c.get("slot_role_map", [])
                  if entry.get("slot_id") == WORLD_SLOT}
    world = next(t for t in _build_registry_bundle().registries
                 if t.registry_id == "sidecar_bool_slot_registry")
    world_roles = {c["actor_role_key"]
                   for r in world.records if r["slot_id"] == WORLD_SLOT
                   for c in r["qualifier_axis_product"]}
    scope_ids = {c["rule_card_id"] for c in _scope_cards(_cards())}
    table_roles = {seg.split("=", 1)[1]
                   for r in reg.BINDING_CONTRACTS
                   if r["rule_card_id"] in scope_ids and r.get("qualifier_axis")
                   for seg in r["qualifier_axis"].split(",")
                   if seg.startswith("actor_role_key=")}
    # 甲案后世界侧是**两格并存**，故判据由「三方相等」改为
    # 「卡侧与表侧相等，且**被世界侧供给**」——这才是绑定不断的充要形状。
    assert card_roles == table_roles == {"bd"}, (card_roles, table_roles)
    assert card_roles <= world_roles, (card_roles, world_roles)
    assert world_roles == {"ba", "bd"}, world_roles


def test_bd_is_in_both_vocabularies():
    """`bd` 必须同时在卡包受控词表与世界侧对照表里——只补一侧会当场拒卡／拒载。"""
    from workflow_engine.worldgen.actor_role_crosswalk import (
        CARD_TO_WORLD, WORLD_ROLE_VOCABULARY,
    )
    vocab = json.loads(_VOCAB.read_text(encoding="utf-8"))
    assert "bd" in vocab["vocabularies"]["actor_role_key"]
    assert "bd" in CARD_TO_WORLD and CARD_TO_WORLD["bd"] == "bd"
    assert "bd" in WORLD_ROLE_VOCABULARY
    # `ba` **不许被删**：守则确有大量条款收件人是建築事務監督。
    assert "ba" in vocab["vocabularies"]["actor_role_key"]
    assert "ba" in CARD_TO_WORLD and "ba" in WORLD_ROLE_VOCABULARY


# ---------------------------------------------------------------- 层三

def test_layer3_out_of_scope_binding_rows_stay_ba():
    """层三①：A 表射程外的 `actor_role_key=ba` 行**必须仍是 ba**，且恰是那 7 行。

    判别器三重冗余、机械可判：条款族（§2.1.3 vs §3.x）／`slot_id`
    （`reporting.artifact.submitted` vs `reporting.record.submitted`）／`artifact_key`。
    射程内外**分处两个不同的槽**。
    """
    from evo_agent_baseline.closure import binding_contract_registry as reg
    ba_rows = {r["row"] for r in reg.BINDING_CONTRACTS
               if "actor_role_key=ba" in str(r.get("qualifier_axis") or "")}
    assert ba_rows == BA_ROWS_OUT_OF_SCOPE, ba_rows
    for r in reg.BINDING_CONTRACTS:
        if r["row"] in BA_ROWS_OUT_OF_SCOPE:
            assert r["slot_id"] == ARTIFACT_SLOT, (r["row"], r["slot_id"])


def test_layer3_world_artifact_submitted_keeps_thirteen_ba():
    """层三②：世界 `reporting.artifact.submitted` 的 13 个 `ba` 组合原样保留。

    这 13 个 `artifact_key` 全是 form／report／notice／proposal 类，
    **不含 `record.inspection_log`** ⇒ 与本件的世界侧改动完全解耦。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    reg = next(t for t in _build_registry_bundle().registries
               if t.registry_id == "sidecar_bool_slot_registry")
    rec = next(r for r in reg.records if r["slot_id"] == ARTIFACT_SLOT)
    combos = rec["qualifier_axis_product"]
    assert len(combos) == 13, len(combos)
    assert {c["actor_role_key"] for c in combos} == {"ba"}
    assert "record.inspection_log" not in {c["artifact_key"] for c in combos}


def test_layer3_world_total_axis_combos_is_24():
    """层三②附：全表轴积合计 **24 个组合**（#29 甲案后）。

    沿革：#29 之前 23；甲案给 `reporting.record.submitted` 追加 `bd` 格 ⇒ **24**，
    每栋 +1 行。这是本件**唯一**的行数增量——其余三个轴积槽逐格不变
    （13 / 8 / 1，见上下两条断言）。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    reg = next(t for t in _build_registry_bundle().registries
               if t.registry_id == "sidecar_bool_slot_registry")
    per_slot = {r["slot_id"]: len(r["qualifier_axis_product"])
                for r in reg.records if r.get("qualifier_axis_product")}
    assert per_slot == {
        "reporting.artifact.submitted": 13,
        "reporting.artifact.delivered": 8,
        WORLD_SLOT: 2,
        "reporting.artifact.signed": 1,
    }, per_slot
    assert sum(per_slot.values()) == 24, per_slot


def test_layer3_deadline_anchor_recipient_stays_ba():
    """层三③：`duration.delivery.deadline.to_ba` 的收件人限定符**必须仍是 ba**。

    它对应 §2.1.3「向**建築事務監督**呈交」，原文正确，属期限锚侧、不在本件射程。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    hits = [r for t in _build_registry_bundle().registries for r in t.records
            if r.get("slot_id") == "duration.delivery.deadline.to_ba"]
    assert hits, "没扫到 duration.delivery.deadline.to_ba？先查取法"
    for r in hits:
        thr = r.get("rule_card_threshold") or {}
        qual = thr.get("recipient_qualifier") or {}
        if "actor_role_key" in qual:
            assert qual["actor_role_key"] == "ba", qual


def test_layer3_card_side_ba_counts_are_frozen():
    """层三④：卡侧射程外的 `ba` 计数冻结——18 条限定符 ＋ 36 条收件人。

    沿革：#29 之前是 21 ／ 41。三条限定符改值（123/125/126）⇒ 21→18；
    五条收件人改值（含第五卡）⇒ 41→36。
    🔴 这条防的是「顺手全局替换」：全局替换会让这两个数直接掉到 0。
    """
    text = _CARDS.read_text(encoding="utf-8")
    assert text.count('"actor_role_key": "ba"') == 18
    assert text.count('"recipient_key": "ba"') == 36
    assert text.count('"actor_role_key": "bd"') == 4
    assert text.count('"recipient_key": "bd"') == 5


# ---------------------------------------------------------------- 变异对照

def test_mutation_layer2_turns_red_when_scope_reverts_to_ba():
    """变异：把射程内任一处改回 `ba` ⇒ 层二判据必须红。"""
    cards = copy.deepcopy(_cards())
    victim = _scope_cards(cards)[0]
    victim["workflow_operands"]["recipients"][0]["recipient_key"] = "ba"
    keys = {r["recipient_key"]
            for c in _scope_cards(cards)
            for r in c["workflow_operands"]["recipients"]}
    assert keys != {"bd"}, "改回 ba 之后层二判据仍然通过——空护栏"


def test_mutation_layer3_turns_red_when_out_of_scope_becomes_bd():
    """变异：把射程外任一行改成 `bd` ⇒ 层三判据必须红。

    这条模拟的正是本件**最危险的手滑**：全局替换 `ba`→`bd`。
    """
    from evo_agent_baseline.closure import binding_contract_registry as reg
    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    victim = next(r for r in rows if r["row"] in BA_ROWS_OUT_OF_SCOPE)
    victim["qualifier_axis"] = victim["qualifier_axis"].replace(
        "actor_role_key=ba", "actor_role_key=bd")
    ba_rows = {r["row"] for r in rows
               if "actor_role_key=ba" in str(r.get("qualifier_axis") or "")}
    assert ba_rows != BA_ROWS_OUT_OF_SCOPE, "射程外改成 bd 之后层三仍然通过——空护栏"


def _three_side_roles(cards: list[dict], world_records: list[dict],
                      table_rows: list[dict]) -> tuple[set, set, set]:
    """三方角色取值集合——**判据本体抽成函数**，供正测与变异对照共用。

    抽出来是为了让变异对照跑的是**同一个判据**，而不是我在测试里另写一遍。
    另写一遍 ＝ 变异对照测的是我的复制品，不是真闸（本项目既有教训）。
    """
    card_roles = {entry["qualifiers"]["actor_role_key"]
                  for c in _scope_cards(cards)
                  for entry in c.get("slot_role_map", [])
                  if entry.get("slot_id") == WORLD_SLOT}
    world_roles = {combo["actor_role_key"]
                   for r in world_records if r["slot_id"] == WORLD_SLOT
                   for combo in r["qualifier_axis_product"]}
    scope_ids = {c["rule_card_id"] for c in _scope_cards(cards)}
    table_roles = {seg.split("=", 1)[1]
                   for r in table_rows
                   if r["rule_card_id"] in scope_ids and r.get("qualifier_axis")
                   for seg in r["qualifier_axis"].split(",")
                   if seg.startswith("actor_role_key=")}
    return card_roles, world_roles, table_roles


def test_mutation_world_side_single_sided_change_is_detectable():
    """变异：**世界侧单侧**改回 `ba` ⇒ 三方一致判据必须红。

    金丝雀已在运行时证明单侧落卡会让证据绑定断裂（`qualifier_conflict`）；
    本条是它在**静态面**的对应物——两个面都要有闸，否则单侧漂移只在跑批时才暴露。

    🔴 这里跑的是 `_three_side_roles` 这个**判据本体**，喂进去的是深拷贝后
    改坏的世界记录，不是我手写的两个字面量集合。
    """
    from workflow_engine.worldgen.registry import _build_registry_bundle
    from evo_agent_baseline.closure import binding_contract_registry as reg

    world = next(t for t in _build_registry_bundle().registries
                 if t.registry_id == "sidecar_bool_slot_registry")
    records = copy.deepcopy(list(world.records))
    victim = next(r for r in records if r["slot_id"] == WORLD_SLOT)
    # 模拟「甲案被回退成只剩 ba 格」——即世界侧不再供给 bd
    victim["qualifier_axis_product"] = [
        c for c in victim["qualifier_axis_product"]
        if c["actor_role_key"] != "bd"
    ]
    assert victim["qualifier_axis_product"], "变异不该把这一槽清空"

    cards = _cards()
    rows = list(reg.BINDING_CONTRACTS)
    # 先证明未变异时判据是通过的（否则本变异对照可能在测别的东西）
    c0, w0, t0 = _three_side_roles(cards, list(world.records), rows)
    assert c0 == t0 == {"bd"} and c0 <= w0, (c0, w0, t0)
    card_roles, world_roles, table_roles = _three_side_roles(cards, records, rows)
    assert not card_roles <= world_roles, \
        "世界侧撤掉 bd 格之后「卡侧被世界供给」判据仍然通过——空护栏"


# ---------------------------------------------------------------- 甲案：#33 记账闸

# `reporting.record.submitted{artifact_key=record.inspection_log, actor_role_key=ba}`
# 那一格的消费卡（射程外 6 张）。原文收件人：前 4 张确为建築事務監督；
# 后 2 张（§3.6.3(c)）原文写屋宇署，挂 #29b 独立语义裁定。
BA_CONSUMER_CARDS = frozenset({
    "rc.mbis.inspection.drainage.ri.follow_up"
    ".s3_6_2_b_a_report_wrong_connection_to_ba.c01",
    "rc.mbis.inspection.drainage.ri.follow_up"
    ".s3_6_2_b_b_report_untreated_industrial_discharge_to_ba.c01",
    "rc.mbis.inspection.drainage.ri.follow_up"
    ".s3_6_3_b_public_health_emergency_notify_ba_owner_residents.c01",
    "rc.mbis.inspection.drainage.ri.follow_up"
    ".s3_6_3_c_public_danger_urgent_action_or_ba_report.c01",
    "rc.mbis.inspection.drainage.ri.follow_up"
    ".s3_6_3_c_public_health_threat_urgent_action_or_ba_report.c01",
    "rc.mbis.investigation.drainage.ri.follow_up"
    ".s4_4_3_arrange_urgent_action_or_report_ba_if_unable.c01",
})


def test_ba_consumer_cards_are_exactly_the_six():
    """先钉住人群本身：`ba` 格的消费卡**恰是这 6 张**。

    不先锁人群，下面那条「零行」断言会在人群悄悄变化时**空过**
    （新卡加进来、断言照样绿）。
    """
    actual = {c["rule_card_id"] for c in _cards()
              for e in c.get("slot_role_map", [])
              if e.get("slot_id") == WORLD_SLOT
              and (e.get("qualifiers") or {}).get("actor_role_key") == "ba"}
    assert actual == BA_CONSUMER_CARDS, sorted(actual ^ BA_CONSUMER_CARDS)


def test_ba_grid_has_no_value_consumption_authorization():
    """🔴 **#33 记账闸（甲案预注册断言）**：`ba` 格的 6 张消费卡在
    `BINDING_CONTRACTS`（A′ 值消费面）必须**零行**。

    ## 为什么这条断言是甲案「只进分母、不进分子」的**证明**，不是注释

    甲案给 #33 的**人群（分母）+1 格**（该格 `conditional_inputs=[]`、与程序闸零耦合，
    形状与 #33 病灶同族），但**契约行／satisfied／卡数三个计数 +0**。
    「+0」是**有条件的**，条件就是这条断言：

    - 世界侧该槽 `carrier_domain="artifact"` ⇒ 其事实是产物态事实；
    - 这 6 张卡以 `roles=["evidence"]` 引用它 ⇒ `kind=evidence`
      落在产物态证据许可闸的**不许可集合**内 ⇒ 恒落
      `open/artifact_state_not_valid_evidence`；
    - **唯一能绕过许可闸的出口**是 A′ 值消费契约，其启用门要求
      `(rule_card_id, slot_ref_id) ∈ VALUE_CONSUMPTION_AUTHORIZED_BINDINGS`。

    ⇒ 只要这 6 张卡不取得 A′ 授权行，该格**结构上无 satisfied 出口**。
    **一旦任一张取得 A′ 行，该格即由 #33 的分母转进分子，须重新过 #33 裁定。**
    把证明责任移到结构，不靠注释。

    ## 🔴 粒度：判据必须写在 **(卡, slot_ref_id)** 上，不能写在**卡**上

    A′ 启用门查的键是 `(rule_card_id, slot_ref_id)`，**不是** `rule_card_id`。
    写成卡级会假红：§4.4.3 那张卡确实**有**一行（row 103），但它挂在
    `sr01 / scope.component.inspection_included`（**另一个槽**）、且 `policy=diagnostic_only`
    / `verdict_permission="none"`，与本格的 `sr05 / reporting.record.submitted` 无关。
    （本项目既有教训：事实身份 ＝ 槽名 ＋ 限定符，只按一半判必错。）
    """
    from evo_agent_baseline.closure import binding_contract_registry as reg
    # 精确到「读 ba 格的那条引用」：(卡, slot_ref_id)
    ba_refs = {(c["rule_card_id"], e["slot_ref_id"])
               for c in _cards()
               for e in c.get("slot_role_map", [])
               if e.get("slot_id") == WORLD_SLOT
               and (e.get("qualifiers") or {}).get("actor_role_key") == "ba"}
    assert len(ba_refs) == 6, sorted(ba_refs)

    hits = [(r["row"], r["policy"]) for r in reg.BINDING_CONTRACTS
            if (r["rule_card_id"], r["slot_ref_id"]) in ba_refs]
    assert hits == [], (
        f"ba 格的消费引用取得了授权行 {hits}——该格已由 #33 分母转进分子，"
        "须重新过 #33 裁定，不许直接改这条断言")

    # 四个派生视图同样必须不含这些键（消费方不得绕过表自建集合）。
    for view_name in ("SCOPE_PRECISE_BINDINGS", "VALUE_CONSUMPTION_BINDINGS",
                      "DIAGNOSTIC_ONLY_BINDINGS", "REJECTED_BINDINGS"):
        view = getattr(reg, view_name)
        leaked = [k for k in view if k in ba_refs]
        assert leaked == [], f"{view_name} 泄漏了 ba 格消费引用：{leaked}"

    # 补一条更宽的观察闸：这 6 张卡**整卡**不得有任何 `value_consumption` 行。
    # 它比上面那条宽（宽到卡级），但方向安全——A′ 是唯一能绕过产物态许可闸的出口，
    # 任一张卡出现值消费行都值得当场看一眼，不该等到跑批。
    vc = [(r["row"], r["rule_card_id"].split(".")[-2])
          for r in reg.BINDING_CONTRACTS
          if r["rule_card_id"] in BA_CONSUMER_CARDS
          and r["policy"] == "value_consumption"]
    assert vc == [], f"ba 格消费卡出现值消费行：{vc}"


def test_mutation_ba_grid_authorization_turns_red():
    """变异对照：人为给 `ba` 格消费卡塞一行 A′ 授权 ⇒ 上面那条闸必须转红。

    不做这个对照，「零行」可能只是因为我取行的方式写错了（恒空 ⇒ 恒绿）。

    ⚠️ 塞进去的行必须键在**真正读 ba 格的那个 `slot_ref_id`** 上，
    并用**与真闸同一个谓词**去查——否则变异对照测的是我手写的复制品，不是真闸。
    """
    from evo_agent_baseline.closure import binding_contract_registry as reg
    ba_refs = {(c["rule_card_id"], e["slot_ref_id"])
               for c in _cards()
               for e in c.get("slot_role_map", [])
               if e.get("slot_id") == WORLD_SLOT
               and (e.get("qualifiers") or {}).get("actor_role_key") == "ba"}
    victim_card, victim_ref = sorted(ba_refs)[0]

    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    # 先证明未变异时真闸是通过的
    assert [r for r in rows
            if (r["rule_card_id"], r["slot_ref_id"]) in ba_refs] == []

    injected = copy.deepcopy(
        next(r for r in rows if r["policy"] == "value_consumption"))
    injected["row"] = 9999
    injected["rule_card_id"] = victim_card
    injected["slot_ref_id"] = victim_ref
    rows.append(injected)

    hits = [r["row"] for r in rows
            if (r["rule_card_id"], r["slot_ref_id"]) in ba_refs]
    assert hits == [9999], f"塞了一行 A′ 授权之后闸仍然通过——空护栏（得 {hits}）"


@pytest.mark.parametrize("clause", sorted(PARALLEL_CLAUSES))
def test_every_parallel_clause_has_a_bd_card(clause: str):
    """逐条款点名：五条平行款**每一条**都必须有一张收件人为 `bd` 的卡。

    参数化到条款级，是为了让失败信息直接说出**是哪一条款漏了**，
    而不是只报「集合不等」。
    """
    hits = [c for c in _scope_cards(_cards()) if clause in _sections(c)]
    assert len(hits) == 1, [c["rule_card_id"] for c in hits]
    assert {r["recipient_key"]
            for r in hits[0]["workflow_operands"]["recipients"]} == {"bd"}
