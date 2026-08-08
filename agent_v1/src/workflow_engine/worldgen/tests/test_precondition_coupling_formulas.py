# -*- coding: utf-8 -*-
"""死声明补公式的结构闸与发射断言（2026-08-05，决议_33处置_20260805.md §一.1）。

## 补之前是什么样（红先行的「红」，实测记录在案）

运行时（**Round6/7 overlay 之后**——读源码字面会全线误判，那是官方线九条案情
订正的第一条）`sidecar_bool_slot_registry` 52 条里有 **3 条**声明了
`conditional_inputs` 却 `conditional_formula=None`：

| 槽 | order | 粒度 | 补前状态 |
|---|---|---|---|
| `actor.representative.assigned_role` | 20.5 | fragment | 有**部分**保护（`_apply_clamps` 单向钳制 planned=False ⇒ none），但层级分布与上游零耦合 |
| `procedure.investigation.detailed.intended` | 46 | building | **无公式、无钳制 ⇒ 完全独立伯努利 0.32** |
| `procedure.investigation.detailed.completed` | 47 | fragment | **无公式、无钳制 ⇒ 完全独立伯努利 0.15** |

其中 `.intended` 正是乙路（#30）§2.1.3(n) 要接的那个前件槽——照现状落，
等于把一个「与自己声明的三个上游零耦合」的槽接成规范前件。

## 🔴🔴 本文件真正的承重内容：`_eval_centered_linear` 对缺失键静默取 0.0

`conditional_eval._eval_centered_linear:239` 是 `context.get(name, 0.0)`
——**不抛异常、不走 fallback**。⇒ 公式里写一个求值上下文里根本不存在的键，
结果**不是**「回退边际」，而是**静默按 0.0 参与中心化**，得到一个偏移过的常数概率。

**那比死声明更糟**：死声明至少诚实地等于边际；错键公式看起来在条件化、
实际在按一个错误常数采样，**而且没有任何报警**。

⇒ 本文件的第一节把这件事从「要记得」变成**机器保证**：
**每条公式的每个 term 键，必须在该槽粒度下真的解析得到。**
这条闸对全部 48 条公式生效，不只是新补的 3 条。
"""
from __future__ import annotations

import random

import pytest

from workflow_engine.worldgen import registry as WR
from workflow_engine.worldgen import round6_formulas as RF
from workflow_engine.worldgen import sidecar as SC
from workflow_engine.worldgen.conditional_eval import (
    ALLOWED_HIDDEN_INPUTS,
    ALLOWED_SIDECAR_INPUTS,
    build_evaluator_context,
)
from workflow_engine.worldgen.registry import BUILDING_READING_AGGREGATION

NEW_SLOTS = (
    "actor.representative.assigned_role",
    "procedure.investigation.detailed.intended",
    "procedure.investigation.detailed.completed",
)

# 楼级槽的求值上下文（`sidecar.py` 里 `building_context` 字面构造的键）。
# 🔴 这份清单是**从生产代码抄下来的镜像**，两处不一致就是本闸失效——
# 故下面 `test_building_context_keys_mirror_production` 直接对着生产代码核。
BUILDING_CONTEXT_KEYS = frozenset({
    "building.metadata.building_age_years",
    "building_total_severity_max",
    "building_defect_count",
    # #37 恒等映射三键（2026-08-06）：生产 `building_context` 新增，
    # 是 13 条楼级公式里 3 个有楼级对应量的 H.* 项的合法解析源。
    "H.age_old_score",
    "H.case_active",
    "H.defect_severity_score",
})


def _building_available_keys(sid: str, recs: dict) -> set:
    """楼级槽 S 的修正可得集（#37，决议_37修法_20260805 §一.4 官方三项式）。

    照生产路径逐条对（`sidecar.py:_sample_sidecar_bool_slots_for_building`）：
      ① 楼级上下文键（`building_context` 字面构造，镜像测试盯本体）；
      ② **已采楼级槽无条件可得**——`upstream = dict(building_state)` 白拿，
        不要求出现在 `conditional_inputs`（首版闸漏了这一格会误伤 4 条合法依赖）；
      ③ 碎片级槽：必须**同时**在本槽 `conditional_inputs` 里 **且** 在
        `BUILDING_READING_AGGREGATION` 里有声明的聚合语义
        （`_resolve_building_upstream` 只解析声明过的、无聚合声明即 ValueError）。

    ⚠️ 首版闸用 `BUILDING_CONTEXT_KEYS | ALLOWED_SIDECAR_INPUTS`——假定全部
    sidecar 槽在楼级都取得到，**过宽**：正是 #37 那批非 H.* 缺键长期潜伏的原因。
    """
    own = float(recs[sid].get("sampling_order") or 9999)
    avail = set(BUILDING_CONTEXT_KEYS)
    for tid, r in recs.items():
        if r.get("granularity") == "building" and \
                float(r.get("sampling_order") or 9999) < own:
            avail.add(tid)
    for uid in recs[sid].get("conditional_inputs") or []:
        uid = str(uid)
        peer = recs.get(uid)
        if peer is not None and peer.get("granularity") != "building" \
                and uid in BUILDING_READING_AGGREGATION:
            avail.add(uid)
    return avail


def _records():
    bundle = WR._build_registry_bundle()
    tbl = next(t for t in bundle.registries
               if t.registry_id == "sidecar_bool_slot_registry")
    return {r["slot_id"]: r for r in tbl.records}


def _fragment_context_keys():
    """fragment 求值上下文**可能出现**的全部键（喂满全部入参后的并集）。"""
    ctx = build_evaluator_context(
        age_years=30.0, service_load_ratio=0.5, restraint_level=0.5,
        workmanship_deficit=0.5, maintenance_deficit=0.5,
        moisture_ingress_index=0.5, chloride_exposure=0.5,
        crack_severity_index=0.5, spall_severity_index=0.5,
        corrosion_severity_index=0.5, delamination_severity_index=0.5,
        detachment_severity_index=0.5, drainage_blockage_index=0.5,
        drainage_leakage_index=0.5, public_health_risk_index=0.5,
        defect_class_present=True, ubw_alteration_present=True,
        fire_safety_deficiency_present=True, repair_quality_index=0.5,
        fsp_structural_performance=0.5, building_total_severity_max=0.5,
        building_defect_count=3,
        hidden_state={k: 0.5 for k in ALLOWED_HIDDEN_INPUTS},
        sidecar_upstream={k: True for k in ALLOWED_SIDECAR_INPUTS},
    )
    return frozenset(ctx)


def _formula_term_keys(formula):
    if formula.get("type") == "centered_softmax_per_class":
        keys = set()
        for block in (formula.get("classes") or {}).values():
            keys |= set(block.get("terms") or {})
        return keys
    return set(formula.get("terms") or {})


# ===================================================================== #
# 一、结构闸：每条公式的每个 term 键必须在该粒度下真的解析得到
# ===================================================================== #

def test_no_dead_conditional_declarations_remain():
    """🔴 零死声明——声明了 `conditional_inputs` 就必须有可执行的公式。

    这条是**结构性**的：它不只护住本次补的 3 个槽，还让将来任何人往注册表里
    加「声明了不执行」的槽时**当场变红**。补前实测 3 条，补后必须是 0。
    """
    dead = [sid for sid, r in _records().items()
            if r.get("conditional_inputs") and not r.get("conditional_formula")]
    assert dead == [], f"仍有死声明（声明了条件依赖却无公式）：{dead}"


# ===================================================================== #
# 🔴🔴 既有缺陷登记（#37）：**已于 2026-08-06 修法归零，清单必须保持为空**
# ===================================================================== #
#
# 沿革（细节见 `团队文档/我的笔记/实施记录_23L2L3_37_20260806.md`）：
# · 2026-08-05 本闸首跑查出 13 个楼级槽的 Round 7 公式引用楼级上下文没有的
#   `H.*` 隐状态（静默按 0.0 中心化，恒定单向压低，13 槽 Δ 全负、最大 −0.1525）；
#   同日量化又查出**同病的非 H 半**：11 条碎片级 term 不在 `conditional_inputs`
#   ⇒ 从不解析（`_KNOWN_BUILDING_CONTEXT_GAPS` 首版只登记了 H 半）。
# · 2026-08-06 #37 修法（决议_37修法_20260805）：
#   步② 闸可得集修成三项式 ＋ 清单扩到恰等实测（按槽 13 / H 项 29 / 非 H 项 11；
#       决议的「24」＝13 组 H.* ＋ 11 条非 H 的合计口径——三套数同一集合三种单位）；
#   步③ 修法本体＝3 个 H.* 项楼级恒等映射（building_context 三键）＋ 7 个 H.* 项
#       删项折 anchor（乙形）＋ 丙路 `conditional_inputs` 同步 ＋ 3 条 artifact.*
#       聚合裁定 any_true；
#   步④ 清单归零（本状态）——**这是修法的验收断言，不是收尾动作**。
# 新增任何一条违例都会让下面的闸变红；把它重新变成非空前，先想想 #37 是怎么来的。
_KNOWN_BUILDING_CONTEXT_GAPS: dict[str, tuple] = {}


def test_every_formula_term_resolves_at_its_granularity():
    """🔴🔴 本文件的核心闸：公式里不许出现该粒度下取不到的键。

    取不到 ⇒ `_eval_centered_linear:239` 静默按 0.0 参与中心化 ⇒ 得到一个偏移过的
    常数概率，**没有任何报警**。这比死声明更糟，故必须机器拦住。

    既有 13 条违例已逐槽冻结在 `_KNOWN_BUILDING_CONTEXT_GAPS`（见上方长注释：
    是本闸查出的既有缺陷，本单不修、只封顶）；**新增一条即红**。
    """
    frag_keys = _fragment_context_keys()
    recs = _records()
    checked = 0
    unexpected = {}
    for sid, r in sorted(recs.items()):
        formula = r.get("conditional_formula")
        if not formula:
            continue
        checked += 1
        gran = r.get("granularity")
        if gran == "building":
            # 楼级：三项式可得集（上下文键 ∪ 已采楼级槽 ∪ 声明且可聚合的碎片槽）。
            # **拿不到**物理字段与未进 building_context 的 H.* 隐状态。
            available = _building_available_keys(sid, recs)
        else:
            available = frag_keys
        bad = set(_formula_term_keys(formula)) - available
        known = set(_KNOWN_BUILDING_CONTEXT_GAPS.get(sid, ()))
        if bad - known:
            unexpected[sid] = sorted(bad - known)
    assert not unexpected, (
        f"公式引用了该粒度取不到的键（**新增**违例，不在既有登记内）：{unexpected}"
        "——求值器会静默按 0.0 中心化，比不写公式更糟")
    assert checked >= 48, f"公式条数异常（{checked}），闸可能跑在空集合上"


def test_known_context_gap_list_is_exact_neither_grown_nor_stale():
    """既有缺陷清单必须**恰好**等于实测违例集——不许多也不许少。

    多了（登记了已修好的）⇒ 清单变成挡箭牌，会掩盖新违例；
    少了 ⇒ 上面那条闸会把既有缺陷报成新违例，噪声淹没真信号。
    本测把清单本身钉在实测上，让它只能随**真实修复**收缩。
    """
    frag_keys = _fragment_context_keys()
    recs = _records()
    measured = {}
    for sid, r in recs.items():
        formula = r.get("conditional_formula")
        if not formula:
            continue
        available = (_building_available_keys(sid, recs)
                     if r.get("granularity") == "building" else frag_keys)
        bad = sorted(set(_formula_term_keys(formula)) - available)
        if bad:
            measured[sid] = tuple(bad)
    assert measured == {k: tuple(sorted(v))
                        for k, v in _KNOWN_BUILDING_CONTEXT_GAPS.items()}, (
        "既有缺陷清单与实测不符——修好了就从清单里删，新增了先看是不是真该加")
    # 🔴 #37 修法的验收断言：清单必须为**零**（决议_37修法_20260805 §一.6 步④）。
    # 判据从「多大算可接受」（无任何规格）退回「有没有」（机器可判）。
    assert len(measured) == len(_KNOWN_BUILDING_CONTEXT_GAPS)


def test_the_newly_added_building_slot_has_zero_context_gap():
    """🔴 本次新补的楼级槽**不许**进那份既有缺陷清单。

    13/14 个既有楼级公式都踩了这个坑；新补的那个之所以没踩，是因为落公式前
    逐键实测过可得性。这条断言把「新东西必须干净」钉死，
    防止将来有人照着旧公式的形状抄一份新的进来。
    """
    assert "procedure.investigation.detailed.intended" not in \
        _KNOWN_BUILDING_CONTEXT_GAPS


def test_building_context_keys_mirror_production():
    """🔴 上面那条闸依赖 `BUILDING_CONTEXT_KEYS` 镜像生产代码——直接核对本体。

    生产侧在 `sidecar.py` 里字面构造 `building_context`；两处漂移会让闸失效
    （闸放行了实际取不到的键，或误拦实际取得到的键）。
    """
    import inspect
    src = inspect.getsource(SC)
    marker = 'building_context: Dict[str, float] = {'
    assert marker in src, "生产侧 building_context 构造点改了形状——先看那里"
    # #37 后构造块含恒等映射三键与随行注释——窗口取到字典闭括号为止
    # （构造块内无嵌套花括号，首个 `}` 即字典关闭；固定字符窗会把后续代码
    # 里的 `"fragment_id":` 之类扫进来造成假阳/假阴）。
    _start = src.index(marker)
    block = src[_start: src.index("}", _start) + 1]
    for key in BUILDING_CONTEXT_KEYS:
        assert f'"{key}"' in block, f"镜像键 {key} 已不在生产 building_context 里"
    # 反向：生产侧新增键而镜像没跟 ⇒ 本闸会过严。用键数粗核
    # （字面 `"key":` 形态的键数应恰等于镜像键数——多了少了都得回来对）。
    assert block.count('": float(') + block.count('": max(') >= 3
    import re
    literal_keys = set(re.findall(r'"([^"\n]+)":\s', block))
    assert literal_keys == set(BUILDING_CONTEXT_KEYS), (
        f"生产 building_context 键集与镜像不一致：{literal_keys ^ set(BUILDING_CONTEXT_KEYS)}")


def test_declared_inputs_match_formula_terms_for_new_slots():
    """声明与执行一致：新补 3 槽的 `conditional_inputs` 必须等于公式 term 键集。

    旧声明里有 `risk.building_safety.emergency` 这种**整个求值上下文里根本不
    存在**的名字；留着对不上的名字＝把「声明了不执行」这个坑原样埋回去。
    """
    recs = _records()
    for sid in NEW_SLOTS:
        r = recs[sid]
        assert set(r["conditional_inputs"]) == _formula_term_keys(
            r["conditional_formula"]), sid


def test_declared_inputs_match_formula_terms_for_all_slots():
    """🔴 #37 新闸②（决议_37修法_20260805 §一.4）：**全部**带公式槽的
    `conditional_inputs` 必须等于公式 term 键集。

    「声明」与「执行」是两份清单、谁也不校验谁——这正是 #37 两个半
    （H.* 缺键静默取 0 ＋ 11 条非 H term 从不解析）都能长期潜伏的共同结构原因。
    Round6/7 overlay 修成从公式 term 同步 `conditional_inputs` 后，本闸把
    一致性钉成机器不变量；修法没修干净它就不绿。
    """
    recs = _records()
    checked = 0
    for sid, r in sorted(recs.items()):
        formula = r.get("conditional_formula")
        if not formula:
            continue
        checked += 1
        declared = set(r.get("conditional_inputs") or [])
        terms = _formula_term_keys(formula)
        assert declared == terms, (
            f"{sid}: conditional_inputs 与公式 term 键集不一致 "
            f"(声明未执行={sorted(declared - terms)}, 执行未声明={sorted(terms - declared)})")
    assert checked >= 48, f"公式条数异常（{checked}）"


def test_building_inputs_declare_no_unaggregatable_fragment_slot():
    """🔴 #37 新闸①：楼级槽的 `conditional_inputs` 不许出现无聚合声明的碎片级槽。

    `_resolve_building_upstream` 对「声明了、碎片级、无 `BUILDING_READING_
    AGGREGATION` 条目」的上游抛 ValueError，且该抛点在 `_sample_one_bool_slot`
    的 try 之外——**不会被 conditional fallback 接住，是运行时硬崩**。
    丙路的硬序「先裁聚合后接线」由本闸固化：以后任何人接线漏裁，当场红。
    """
    recs = _records()
    bad = {}
    for sid, r in sorted(recs.items()):
        if r.get("granularity") != "building":
            continue
        offenders = [
            str(u) for u in (r.get("conditional_inputs") or [])
            if str(u) in recs
            and recs[str(u)].get("granularity") != "building"
            and str(u) not in BUILDING_READING_AGGREGATION
        ]
        if offenders:
            bad[sid] = offenders
    assert not bad, (
        f"楼级槽声明了无聚合语义的碎片级上游（会在采样期 ValueError 硬崩）：{bad}")


def test_repaired_building_slots_emit_conditional_path():
    """🔴 #37 发射断言（主半边）：修完的楼级槽在真实形状的上下文里必须走
    `conditional` 路径——不是 `marginal`（公式没装上）、不是
    `conditional_fallback_marginal`（装上了但求值抛异常）。

    上下文按生产形状喂：楼级 6 键 context ＋ 已采楼级槽 ＋ 按聚合解析出的
    碎片级上游（这里直接给布尔——生产聚合的产物就是布尔）。
    """
    recs = _records()
    bldg_ctx = {"building.metadata.building_age_years": 38.0,
                "building_total_severity_max": 0.62,
                "building_defect_count": 5.0,
                "H.age_old_score": 0.76,
                "H.case_active": 1.0,
                "H.defect_severity_score": 0.62}
    upstream_all_true = {
        sid: True for sid, r in recs.items()
        if r.get("granularity") == "building" or sid in BUILDING_READING_AGGREGATION
    }
    for sid, r in sorted(recs.items()):
        if r.get("granularity") != "building" or not r.get("conditional_formula"):
            continue
        if r.get("value_type") not in (None, "bool"):
            continue
        got = SC._sample_one_bool_slot(r, bldg_ctx, upstream_all_true,
                                       random.Random(99))
        assert got is not None and got[1] == "conditional", (sid, got)


def test_repaired_non_h_terms_actually_move_the_rate():
    """🔴 #37 发射断言（实质半边）：丙路接上的碎片级上游翻转必须显著移动边际。

    修前这些 term 从不解析（静默按 0.0 中心化）⇒ 翻转上游边际纹丝不动；
    修后聚合值真实进入公式 ⇒ 正系数 term 翻真必须抬升概率。
    抽三个有代表性的：intention_notified ← artifact.report.inspection（修前缺）、
    repair.revision_required ← artifact.record.nonconformity_sp2（修前连聚合
    声明都没有）、final_inspection_performed ← supervision.record.completed。
    """
    recs = _records()
    cases = [
        ("procedure.investigation.intention_notified", "artifact.report.inspection"),
        ("procedure.repair.revision_required", "artifact.record.nonconformity_sp2"),
        ("procedure.completed_work.final_inspection_performed",
         "supervision.record.completed"),
    ]
    bldg_ctx = {"building.metadata.building_age_years": 30.0,
                "building_total_severity_max": 0.45,
                "building_defect_count": 3.0,
                "H.age_old_score": 0.60,
                "H.case_active": 1.0,
                "H.defect_severity_score": 0.45}
    for sid, up_key in cases:
        r = recs[sid]
        rates = {}
        for flag in (False, True):
            hits = sum(
                1 for i in range(4000)
                if SC._sample_one_bool_slot(r, bldg_ctx, {up_key: flag},
                                            random.Random(50_000 + i))[0]
            )
            rates[flag] = hits / 4000.0
        assert rates[True] > rates[False] + 0.04, (
            f"{sid} 翻转 {up_key} 后边际几乎没动（{rates}）——term 仍未真实解析")


def test_identity_hidden_keys_match_fragment_side_semantics():
    """#37 恒等映射语义核：楼级 H 三键与碎片级派生同源。

    · H.age_old_score：碎片级 `clip(age/50)`——同年龄同值（逐值恒等）；
    · H.case_active：碎片级无条件 1.0——楼级同为 1.0；
    · H.defect_severity_score：碎片级兜底分支取 `building_total_severity_max`
      ——楼级即该值（语义对应，非逐值恒等，裁定见 sidecar.py 注释）。
    """
    hs = SC._build_round6_hidden_state_for_fragment(
        age_years=38.0, driver=None, mechanism=None, fragment_conditions=[],
        drainage=None, fire_safety=None, ubw=None, repair=None,
        building_total_severity_max=0.62, defect_present=False,
        crack_severity=None, spall_severity=None, delamination_severity=None,
        detachment_severity=None, corrosion_severity=None,
    )
    assert hs["H.age_old_score"] == pytest.approx(38.0 / 50.0)
    assert hs["H.case_active"] == 1.0
    assert hs["H.defect_severity_score"] == pytest.approx(0.62)


def test_new_slots_declare_engineering_estimate_grade_not_mc_certified():
    """档位如实声明：这批**没过** 10,000 样本 MC 对齐闸，不许写 `alignment_check`。

    Round 7 那 45 条带 `alignment_check.status == "passed_round7_mc"`；
    给本批也写上就是伪造档位（本仓反复吃亏的形状：把工程估计伪装成实测）。
    """
    recs = _records()
    for sid in NEW_SLOTS:
        r = recs[sid]
        assert r["distribution_source"] == \
            RF.PRECONDITION_COUPLING_DISTRIBUTION_SOURCE, sid
        assert "engineering_estimate" in r["distribution_source"]
        assert not r.get("alignment_check"), (
            f"{sid} 带了 alignment_check——本批未过 MC 对齐闸，写上即伪造档位")


def test_overlay_does_not_touch_order_or_prevalence():
    """本 overlay 只装公式，**不动采样序与边际锚**（改序会挪 DAG 拓扑）。"""
    recs = _records()
    assert recs["actor.representative.assigned_role"]["sampling_order"] == 20.5
    assert recs["procedure.investigation.detailed.intended"]["sampling_order"] == 46
    assert recs["procedure.investigation.detailed.completed"]["sampling_order"] == 47
    assert recs["procedure.investigation.detailed.intended"]["prevalence"] == 0.32
    assert recs["procedure.investigation.detailed.completed"]["prevalence"] == 0.15
    assert recs["actor.representative.assigned_role"]["prevalence"] == [0.45, 0.385, 0.165]


def test_dag_legality_upstream_orders_strictly_smaller():
    """DAG 合法性：每个 sidecar 上游的 sampling_order 必须严格小于本槽。"""
    recs = _records()
    for sid in NEW_SLOTS:
        r = recs[sid]
        own = float(r["sampling_order"])
        for up in (r.get("upstream_inputs") or {}).get("sidecar", []):
            assert float(recs[up]["sampling_order"]) < own, (sid, up)


def _stub_table(records):
    from workflow_engine.worldgen.models import RegistryTable
    return RegistryTable(registry_id="sidecar_bool_slot_registry",
                         ownership="test", key_field="slot_id", records=records)


def test_overlay_is_fail_closed_on_double_patch():
    """反向变异：目标槽已带公式时 overlay 必须抛，不许静默覆盖。"""
    sid = NEW_SLOTS[1]
    assert sid in RF.get_precondition_coupling_formulas()
    tbl = _stub_table([{"slot_id": sid, "conditional_formula": {"type": "x"}}])
    with pytest.raises(WR.PreconditionCouplingOverlayError):
        WR._apply_precondition_coupling_overlay([tbl])


def test_overlay_is_fail_closed_on_missing_target():
    """反向变异：目标槽不在注册表 ⇒ 抛（登记了却没装上，必须可见）。"""
    with pytest.raises(WR.PreconditionCouplingOverlayError):
        WR._apply_precondition_coupling_overlay([_stub_table([])])


# ===================================================================== #
# 二、发射断言：公式**真的被采样器读到**了
# ===================================================================== #

def _sample_path(slot_id, base_ctx, upstream, seed=7):
    r = _records()[slot_id]
    return SC._sample_one_bool_slot(r, base_ctx, upstream, random.Random(seed))


def test_new_slots_actually_take_the_conditional_path():
    """🔴 发射断言：采样器返回的 `sampling_path` 必须是 `conditional`。

    不是 `marginal`（公式没装上）、也不是
    `conditional_fallback_marginal(reason=…)`（装上了但求值抛异常）。
    「声明了不执行」正是靠这条区分开的——只看注册表字段区分不了。
    """
    # ② 楼级槽：楼级上下文 ＋ 楼级 sidecar 上游
    bldg_ctx = {"building.metadata.building_age_years": 30.0,
                "building_total_severity_max": 0.6,
                "building_defect_count": 4.0}
    up = {"procedure.investigation.intention_notified": True,
          "procedure.investigation.proposal.recognized": True}
    got = _sample_path("procedure.investigation.detailed.intended", bldg_ctx, up)
    assert got is not None and got[1] == "conditional", got

    # ①③ 碎片槽：完整 fragment 上下文
    frag_ctx = {k: 0.5 for k in _fragment_context_keys()}
    got = _sample_path("procedure.investigation.detailed.completed", frag_ctx,
                       {"procedure.investigation.started": True,
                        "procedure.investigation.proposal.recognized": True})
    assert got is not None and got[1] == "conditional", got

    got = _sample_path("actor.representative.assigned_role", frag_ctx,
                       {"procedure.supervision_representative.planned": True})
    assert got is not None and got[1] == "conditional", got
    assert got[0] in ("none", "ri_rep_lvl1", "ri_rep_lvl2")


@pytest.mark.parametrize("slot_id,upstream_key,other", [
    # ⚠️ `.intended` 的上游**不是** `intention_notified`——那是本义务的履行，
    # 拿它当前提＝用结论当前提，`test_precondition_supplement_slots.py` 有常驻裁定。
    ("procedure.investigation.detailed.intended",
     "procedure.inspection.prescribed.completed", {}),
    ("procedure.investigation.detailed.completed",
     "procedure.investigation.started",
     {"procedure.investigation.proposal.recognized": False}),
])
def test_flipping_upstream_actually_moves_the_rate(slot_id, upstream_key, other):
    """🔴 耦合**真的建立了**：翻转上游必须显著改变边际。

    这一条是发射断言的实质半边——`sampling_path=="conditional"` 只证明走了
    条件分支，**不证明系数没写成 0**。补前这两个槽是完全独立伯努利，
    本测在补前必红（上下两档相等）。
    """
    recs = _records()
    r = recs[slot_id]
    gran = r.get("granularity")
    if gran == "building":
        ctx = {"building.metadata.building_age_years": 30.0,
               "building_total_severity_max": 0.45,
               "building_defect_count": 3.0}
    else:
        ctx = {k: 0.5 for k in _fragment_context_keys()}
    rates = {}
    for flag in (False, True):
        up = dict(other)
        up[upstream_key] = flag
        hits = sum(
            1 for i in range(4000)
            if SC._sample_one_bool_slot(r, ctx, up, random.Random(10_000 + i))[0]
        )
        rates[flag] = hits / 4000.0
    assert rates[True] > rates[False] + 0.05, (
        f"{slot_id} 翻转 {upstream_key} 后边际几乎没动（{rates}）"
        "——系数写成 0 或键没解析到，等于没建耦合")


def test_assigned_role_none_share_drops_when_planned():
    """① 的方向：监督代表已规划 ⇒ `none` 档占比必须下降。"""
    r = _records()["actor.representative.assigned_role"]
    ctx = {k: 0.5 for k in _fragment_context_keys()}
    share = {}
    for flag in (False, True):
        vals = [SC._sample_one_bool_slot(
            r, ctx, {"procedure.supervision_representative.planned": flag},
            random.Random(20_000 + i))[0] for i in range(4000)]
        share[flag] = vals.count("none") / 4000.0
    assert share[True] < share[False] - 0.05, share


def test_marginal_stays_near_declared_prevalence_at_anchor_point():
    """边际不许被条件化悄悄搬走：上游取先验期望值时，实测率应贴近声明 prevalence。

    这是「参数保守」的可测形态——中心化模式保证上游取 `upstream_expected`
    时 p 恰等于 anchor，故本测实际在核**anchor 与 prevalence 一致**、
    且求值链路没把值算歪。容差 ±0.03（4000 样本的采样噪声量级）。
    """
    recs = _records()
    r = recs["procedure.investigation.detailed.intended"]
    exp = r["conditional_formula"]["upstream_expected"]
    ctx = {"building.metadata.building_age_years": 30.0,
           "building_total_severity_max": exp["building_total_severity_max"],
           "building_defect_count": 3.0}
    # 上游布尔取先验期望：用概率抽，使其期望等于 anchor
    rnd = random.Random(4242)
    hits = 0
    n = 6000
    key = "procedure.inspection.prescribed.completed"
    for i in range(n):
        up = {key: rnd.random() < exp[key]}
        if SC._sample_one_bool_slot(r, ctx, up, random.Random(30_000 + i))[0]:
            hits += 1
    rate = hits / n
    assert abs(rate - float(r["prevalence"])) < 0.03, (
        f"条件化后边际漂移过大：实测 {rate:.4f} vs 声明 {r['prevalence']}")
