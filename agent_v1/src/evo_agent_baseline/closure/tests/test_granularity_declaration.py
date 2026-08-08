# -*- coding: utf-8 -*-
"""DEBT-085 件二·**第一步声明期**：粒度声明字段的守卫。

设计出处（不重开）：
- 决策门 Q1＝载体是**精确绑定表行字段** ＋ **同卡同质约束**（冲突拒载）；
  Q2＝**两段式**，第一步声明期未声明维持现状，冻结点后才 fail-closed。
  ——`技术与研究债.md` 「DEBT-085 粒度声明设计定案」节。
- 人群与共同待裁清单＝`团队文档/我的笔记/量测_DEBT085x27联合_20260804.md`。

本文件锁五件事：
1. **枚举**：非法值 / 显式 None 一律拒，且拒法是整表 fail-closed；
2. **同卡同质**：同表冲突 ＋ **跨表**冲突都要拒（变异测，不是"现表恰好没冲突"）；
3. **声明期逐位等价**：有声明字段与把字段抽掉，判定输出逐字节相同；
4. **零运行时读者**：声明期本字段不许被任何运行时模块消费
   ——这条同时是第二步的闸：第一个消费者接上时它转红，逼作者一次改完五处镜像；
5. **声明面与共同待裁清单一致**：18 键里的行一个都不许被声明。
"""
from __future__ import annotations

import ast
import copy
import json
import pathlib

import pytest

from evo_agent_baseline.closure import binding_contract_registry as reg
from evo_agent_baseline.closure import bucket_binding_registry as bkt

_REPO = pathlib.Path(__file__).resolve().parents[5]
_TOKEN = "granularity_declaration"

# 本次声明面（先量后冻，2026-08-04）：c55 值消费 row 105-126 共 22 行，全 building。
# 依据＝复算批 `reporting_axes_seed401_20260803` 全 30 栋 fact_pack：本批四个槽
# 合计 690 条事实，按 `validator._fact_frag` 同口径判**片段载体 0 条**
# （submitted 390 / delivered 240 / signed 30 / record.submitted 30，
#  carrier_type 全 sidecar_entry、fragment_id 全空）。
_DECLARED_ROWS_FROZEN = tuple(range(105, 127))

# `量测_DEBT085x27联合_20260804.md` §二 OFF 格 18 键（宽判据全集＝两案共同待裁面）。
# ⚠️ 同目录的机读产物 `量测_..._数据.json` 被 `.gitignore:190` 排除，
#    故本清单**在测试内冻结**；JSON 在场时下面另做一次漂移对照（不在场不静默放过，
#    因为冻结清单本身才是常驻闸）。
_PENDING_18_SLOT_REFS = frozenset({
    "rc.mbis.scope.building.ri.coverage.s3_1_1_common_drain_in_noncommon_part.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_1_envelope_or_lot_boundary.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_1_projection.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_1_signboard.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_2_drainage_system.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_2_external_elements.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_2_fire_safety_elements.c01.sr02",
    "rc.mbis.scope.building.ri.coverage.s3_1_2_structural_elements.c01.sr02",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "sapp6_tbl2_ri_first_inspection_and_level2_proof_tests.c01.sr03",
    "rc.mbis.investigation.detailed_investigation.ri.method."
    "s4_3_2_a_destructive_or_nondestructive_tests.c01.sr02",
    "rc.mbis.repair.supervision.ri.duty."
    "s2_1_3_b_supervise_rectification_and_repair.c01.sr01",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "s6_1_2_a_safe_working_environment.c01.sr02",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "s6_1_2_b_control_repair_and_scaffolding.c01.sr02",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "s6_2_1_provide_safety_measures.c01.sr02",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "s6_2_2_provide_safe_access.c01.sr02",
    "rc.mbis.supervision.ri_minimum_and_site_controls.ri.control."
    "s6_2_3_bamboo_scaffold_per_guide.c01.sr02",
    "rc.mbis.repair.external_structural_validation.ri.verify."
    "s5_4_2_b_replace_corroded_bolts_and_rivets.c01.sr02",
    "rc.mbis.inspection.personal_conduct.ri.duty."
    "s2_1_3_a_personally_conduct_inspection.c01.sr01",
})

_ROW37_SLOT_REF = ("rc.mbis.inspection.personal_conduct.ri.duty."
                   "s2_1_3_a_personally_conduct_inspection.c01.sr01")


def _declared(rows):
    return [r for r in rows if reg.GRANULARITY_DECLARATION_KEY in r]


# ---------------------------------------------------------------- ① 声明面 --

def test_declaration_surface_is_frozen():
    """声明面＝c55 值消费 22 行，全 `building`；桶表本步零声明。

    🔴 这是**冻结数**。改它必须是「先量后冻」的结果，不是把断言改成实测值。
    """
    d = _declared(reg.BINDING_CONTRACTS)
    assert tuple(sorted(r["row"] for r in d)) == _DECLARED_ROWS_FROZEN
    assert {r["granularity_declaration"] for r in d} == {"building"}
    # 声明行必须全是 c55 那 22 行（不许悄悄声明到别的行上）。
    # 🔴 2026-08-05 #33 保护闸：判据从 `policy=="value_consumption"` 改成
    # 「在 #33 闸内」——那 22 行的 policy 已翻成 `diagnostic_only`
    # （`重核准记录_33保护闸_20260805.md`）。判据的**意图**没变（还是「恰这批」），
    # 换的是识别它们的方式；老写法今天会选到空集、断言空过。
    assert all(reg.coupling_unproven_exit_code(r) is not None and r["row"] > 37
               for r in d)
    assert {r["row"] for r in d} == {r["row"] for r in reg.BINDING_CONTRACTS
                                     if reg.coupling_unproven_exit_code(r)}
    assert _declared(bkt.BUCKET_BINDING_CONTRACTS) == []
    # 两表现状健康——声明期不许把表跑挂
    assert reg.DISABLED_REASON is None and not reg.STALE_ROWS
    assert bkt.DISABLED_REASON is None and not bkt.STALE_ROWS


def test_declared_rows_are_disjoint_from_the_18_pending_keys():
    """共同待裁的 18 键一个都不许被声明（DEBT085×27 联合量测钉死的范围）。"""
    declared_refs = {r["slot_ref_id"] for r in _declared(reg.BINDING_CONTRACTS)}
    assert declared_refs & _PENDING_18_SLOT_REFS == set(), \
        "声明面越界进了共同待裁清单——范围由联合量测钉死，不许自行扩大"


def test_row37_is_pending_not_declared():
    """row 37 在 18 键清单内 ⇒ 本步**不填**（工单原文「读数全是楼级」对它不成立）。

    量测实测（30 栋 fact_pack）：其槽 `procedure.inspection.prescribed.completed`
    共 236 条事实＝片段载体 206 ／ 楼级载体 30，形状
    `B_card_building_but_slot_fragment_carried`。
    共同裁定落地前若有人给它填了声明，本测试转红。
    """
    row37 = [r for r in reg.BINDING_CONTRACTS if r["row"] == 37][0]
    assert row37["slot_ref_id"] == _ROW37_SLOT_REF
    assert _ROW37_SLOT_REF in _PENDING_18_SLOT_REFS
    assert reg.GRANULARITY_DECLARATION_KEY not in row37


def test_frozen_pending_list_matches_measurement_product_when_present():
    """机读量测产物在场时做一次漂移对照（产物被 gitignore，不在场则跳过对照）。"""
    p = _REPO / "团队文档" / "我的笔记" / "量测_DEBT085x27联合_20260804_数据.json"
    if not p.exists():
        pytest.skip("机读量测产物不在本工作副本（.gitignore:190）——"
                    "常驻闸是上面的冻结清单，本对照只在产物在场时加跑")
    data = json.loads(p.read_text(encoding="utf-8"))
    refs = {e["槽引用"] for e in data["宽判据_A_B_C"]["数③交叉格清单_OFF"]}
    assert refs == set(_PENDING_18_SLOT_REFS), \
        "冻结的 18 键与量测产物不一致——去核量测，别改断言"


# ------------------------------------------------------------ ② 枚举与同质 --

def _violations_with(rows):
    """把改造过的行喂进 A 表模式校验，返回违例清单。"""
    mod = reg
    orig = mod.BINDING_CONTRACTS
    try:
        mod.BINDING_CONTRACTS = tuple(rows)
        return mod._schema_violations()
    finally:
        mod.BINDING_CONTRACTS = orig


@pytest.mark.parametrize("bad_value", ["fragment_level", "BUILDING", "", 1, None])
def test_illegal_declaration_value_is_rejected(bad_value):
    """受控枚举：越界值、大小写不符、空串、非字符串、**显式 None** 全拒。

    显式 `None` 必须与「键缺省」区分——若同形，冻结点的 fail-closed
    判据会退化成猜测（「声明了但为空」到底算不算已声明？）。
    """
    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    victim = next(r for r in rows if r["row"] == 105)
    victim[reg.GRANULARITY_DECLARATION_KEY] = bad_value
    bad = _violations_with(rows)
    assert any("非法粒度声明" in b and "row105" in b for b in bad), bad


def test_absent_key_is_the_declaration_free_default():
    """键缺省＝未声明＝合法（声明期缺省语义＝维持现状）。"""
    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    for r in rows:
        r.pop(reg.GRANULARITY_DECLARATION_KEY, None)
    assert _violations_with(rows) == []


def test_same_card_conflict_fails_the_whole_table_closed():
    """变异：同卡两行声明不同粒度 ⇒ 违例 ＋ **整表 fail-closed**（Q1 冲突拒载）。

    载体选 row 109/110——同一张卡 `…s2_1_3_o.c01` 的两个槽引用，
    正是「同卡邻槽不得改变另一槽判定粒度」那条不变式的最小实例。
    """
    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    a = next(r for r in rows if r["row"] == 109)
    b = next(r for r in rows if r["row"] == 110)
    assert a["rule_card_id"] == b["rule_card_id"], "载体前提变了，去改测试载体"
    b[reg.GRANULARITY_DECLARATION_KEY] = "fragment"
    bad = _violations_with(rows)
    assert any("同卡粒度声明冲突" in x for x in bad), bad
    # 拒法必须是整表失效，不是跳过坏行
    orig = reg.BINDING_CONTRACTS
    try:
        reg.BINDING_CONTRACTS = tuple(rows)
        active, stale, why = reg._validate_against_pack()
    finally:
        reg.BINDING_CONTRACTS = orig
    assert active == [] and len(stale) == len(rows)
    assert why and why.startswith("schema:")


def test_same_card_agreement_passes():
    """反向对照：同卡两行声明**相同**粒度 ⇒ 放行（闸不是见声明就拒）。"""
    rows = copy.deepcopy(list(reg.BINDING_CONTRACTS))
    for n in (109, 110):
        next(r for r in rows if r["row"] == n)[
            reg.GRANULARITY_DECLARATION_KEY] = "fragment"
    assert _violations_with(rows) == []


def test_cross_table_same_card_conflict_is_caught_by_bucket_gate():
    """**跨表**同卡冲突：A 表 building ＋ 桶表 fragment ⇒ 桶表整表 fail-closed。

    非空场景：A 表 c55 候选卡与桶表卡实测重合 6 张（2026-08-04）。
    只做单表同质会漏掉这一整类——桶表能看见 A 表，故闸挂在桶表侧
    （反向会成环，见 `bucket_binding_registry._schema_violations` docstring）。
    """
    shared = sorted(
        {r["rule_card_id"] for r in _declared(reg.BINDING_CONTRACTS)}
        & {r["rule_card_id"] for r in bkt.BUCKET_BINDING_CONTRACTS})
    assert shared, "两表已声明卡与桶表零重合——跨表闸会变成空转，去核前提"
    rows = copy.deepcopy(list(bkt.BUCKET_BINDING_CONTRACTS))
    victim = next(r for r in rows if r["rule_card_id"] == shared[0])
    victim[reg.GRANULARITY_DECLARATION_KEY] = "fragment"
    orig = bkt.BUCKET_BINDING_CONTRACTS
    try:
        bkt.BUCKET_BINDING_CONTRACTS = tuple(rows)
        bad = bkt._schema_violations()
        active, stale, why = bkt._validate_against_pack()
    finally:
        bkt.BUCKET_BINDING_CONTRACTS = orig
    assert any("同卡粒度声明冲突" in x and "跨表" in x for x in bad), bad
    assert active == [] and len(stale) == len(rows) and why.startswith("schema:")


def test_bucket_table_own_enum_is_enforced_too():
    """桶表自己的行也受枚举约束（本步零声明，但闸不能是摆设）。"""
    rows = copy.deepcopy(list(bkt.BUCKET_BINDING_CONTRACTS))
    rows[0][reg.GRANULARITY_DECLARATION_KEY] = "per_fragment"
    orig = bkt.BUCKET_BINDING_CONTRACTS
    try:
        bkt.BUCKET_BINDING_CONTRACTS = tuple(rows)
        bad = bkt._schema_violations()
    finally:
        bkt.BUCKET_BINDING_CONTRACTS = orig
    assert any("非法粒度声明" in x and "桶表" in x for x in bad), bad


# ------------------------------------------- ③ 声明期逐位等价 / 零运行时读者 --

def _code_refs_to_token(path: pathlib.Path) -> bool:
    """该文件是否**在代码里**引用了本字段名（注释与文档串不算）。

    判据：AST 里非 docstring 位置的字符串常量含该 token，或有同名属性访问 /
    同名标识符。用 AST 而非裸 grep，是因为空转钩位的说明**就写在 docstring 里**
    ——裸子串匹配会把「注释提到它」误判成「代码消费它」。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and _TOKEN in node.value and id(node) not in docstrings):
            return True
        if isinstance(node, ast.Attribute) and node.attr == _TOKEN:
            return True
        if isinstance(node, ast.Name) and node.id == _TOKEN:
            return True
    return False


def test_declaration_has_no_runtime_reader_in_declaration_period():
    """🔴 声明期＝**只登记不消费**：除两张登记表外，运行时模块零引用。

    这条同时是第二步冻结的闸——第一个消费者接上时本测试转红，
    逼作者当场面对「五处镜像必须同批改」（kimi 过渡期风险：只改声明读取路径、
    不管缺省回退路径，过渡期会按镜像不同产出两套判定）。
    转红时正确做法是**同批改完五处镜像并更新本测试**，不是把本测试删掉。
    """
    owners = {"binding_contract_registry.py", "bucket_binding_registry.py"}
    src = _REPO / "agent_v1" / "src" / "evo_agent_baseline"
    offenders = []
    for p in sorted(src.rglob("*.py")):
        if "tests" in p.parts or p.name in owners:
            continue
        if _code_refs_to_token(p):
            offenders.append(str(p.relative_to(_REPO)))
    assert offenders == [], f"声明期出现运行时消费者：{offenders}"
    # 反证空转：两张表里必须**真的**有代码级引用，否则上面那条恒真
    for name in sorted(owners):
        assert _code_refs_to_token(src / "closure" / name), name


def test_declaration_period_is_bitwise_equivalent_on_the_c55_contract_path():
    """逐位等价（**在字段真被读到的那条路径上**）：A′ 值消费契约。

    选这条路径是因为它拿 `binding_key` 回查行字典——声明字段就在那个字典里，
    是全仓离本字段最近的判定路径。跑真假两侧，比对义务对象的完整 JSON。
    （反面教材：拿合成卡跑通用闭包，行字典根本不在读径上，等于在
    「缺陷不可能显现的输入」上验等价。）
    """
    import evo_agent_baseline.closure.obligation_deriver as od
    from .test_c55_consumption_rows import _axis_fact_for, _c55_key_and_row
    from .test_binding_contract_registry import META, make_rule_card

    key, row = _c55_key_and_row()
    assert reg.GRANULARITY_DECLARATION_KEY in row, "载体行没声明，等价对照无意义"

    def _run():
        out = []
        for v in (True, False):
            card = make_rule_card()
            if hasattr(card, "model_copy"):
                card = card.model_copy(update={"rule_card_id": key[0]})
            ob = od._value_consumption_contract(
                card, META, "evidence", {}, [_axis_fact_for(row, v)],
                use_scope=True, binding_key=key)
            out.append(None if ob is None else
                       ob.model_dump_json() if hasattr(ob, "model_dump_json")
                       else json.dumps(ob, default=str, sort_keys=True))
        return out

    with_field = _run()
    live = reg.SCOPE_PRECISE_BINDINGS[key]           # 与 BINDING_CONTRACTS 同对象
    assert live is next(r for r in reg.BINDING_CONTRACTS
                        if r["row"] == row["row"]), \
        "派生视图与权威元组不是同一对象——下面的抽字段对照会变成空转"
    saved = live.pop(reg.GRANULARITY_DECLARATION_KEY)
    try:
        # 非空转自证：抽掉后权威元组里也必须真的没有了
        assert reg.GRANULARITY_DECLARATION_KEY not in next(
            r for r in reg.BINDING_CONTRACTS if r["row"] == row["row"])
        without_field = _run()
    finally:
        live[reg.GRANULARITY_DECLARATION_KEY] = saved
    assert with_field == without_field, "声明期出现行为差异——字段被消费了"
    assert next(r for r in reg.BINDING_CONTRACTS if r["row"] == row["row"]
                ).get(reg.GRANULARITY_DECLARATION_KEY) == "building", "还原失败"


def test_declaration_period_is_bitwise_equivalent_on_the_shared_fixture():
    """再用现成闭包夹具跑一次整链对照——覆盖导入期派生视图那一侧。

    `run_closure` 走合成卡（不命中登记表行），故它证的不是契约路径，
    而是「加字段没有经由派生视图 / 摘要 / 校验器扰动主链任何一位」。
    两条测试各证一半，别拿任一条冒充全部。
    """
    from .fixtures import make_fact, make_fact_pack, make_rule_slice, run_closure

    def _once():
        fp = make_fact_pack([make_fact("f-1", slot_id="slot.defect.present",
                                       value=True, value_type="boolean")])
        res = run_closure(make_rule_slice(), fp)
        return json.dumps(res.machine_readable_report, default=str,
                          sort_keys=True, ensure_ascii=False)

    before = _once()
    saved = {}
    for r in reg.BINDING_CONTRACTS:
        if reg.GRANULARITY_DECLARATION_KEY in r:
            saved[r["row"]] = r.pop(reg.GRANULARITY_DECLARATION_KEY)
    try:
        assert saved, "没有任何声明行——本对照会退化成自比"
        after = _once()
    finally:
        for r in reg.BINDING_CONTRACTS:
            if r["row"] in saved:
                r[reg.GRANULARITY_DECLARATION_KEY] = saved[r["row"]]
    assert before == after


def test_registry_digest_moved_and_that_is_expected():
    """诚实边界：**判定面逐位不变，但 A 表 `registry_digest` 变了**。

    摘要是批清单锚（`run_baseline_batch.py` 只落盘、不比对），不是判定值。
    这里只锁「摘要对本字段敏感」——若摘要对声明变化不敏感，
    「哪些行声明了什么粒度」这个自由度就逃出了可复现锚。
    桶表本步零声明 ⇒ 桶表摘要不动。
    """
    d0 = reg.registry_digest()
    live = reg.SCOPE_PRECISE_BINDINGS[
        (reg.BINDING_CONTRACTS[-1]["rule_card_id"],
         reg.BINDING_CONTRACTS[-1]["slot_ref_id"])]
    saved = live.pop(reg.GRANULARITY_DECLARATION_KEY)
    try:
        assert reg.registry_digest() != d0
    finally:
        live[reg.GRANULARITY_DECLARATION_KEY] = saved
    assert reg.registry_digest() == d0
